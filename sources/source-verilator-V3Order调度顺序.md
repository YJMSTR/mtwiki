---
title: "V3Order调度顺序"
source_url: "https://github.com/verilator/verilator/tree/master/src/"
source_type: "github-code"
author: "Verilator Team"
date: ""
tags: ["verilator", "multithreading", "scheduling", "graph-partitioning", "critical-path", "mtask", "order-graph", "bipartite-graph"]
keywords: ["V3Order", "OrderGraph", "LogicMTask", "MTaskEdge", "Contraction", "FixDataHazards", "Partitioner", "critical path", "edge contraction", "sibling merge"]
capture_date: "2026-07-05"
---

# Verilator V3Order 调度顺序与并行分区源码分析

## 来源

- URL: https://github.com/verilator/verilator/tree/master/src/
- 类型: github-code
- 作者: Wilson Snyder / Verilator Team
- 日期: 2023–2026（持续活跃开发）
- 相关文件组:
  - `V3Order.h` / `V3Order.cpp`
  - `V3OrderGraph.h`
  - `V3OrderGraphBuilder.cpp`
  - `V3OrderParallel.cpp`
  - `V3OrderInternal.h`
  - `V3OrderCFuncEmitter.h`

## 摘要

V3Order 是 Verilator 中将 RTL 的 always/wire 语句计算**近最优调度顺序**的核心模块。它首先构建一个**二部依赖图**（OrderGraph），然后通过图排序打破循环、赋予 rank，再基于 domain/scope 构建 **MoveGraph**。在 `--threads` 模式下，`V3OrderParallel.cpp` 将细粒度逻辑图**粗化为 MTask 图**，通过**临界路径驱动的边收缩（edge contraction）**和**sibling merge** 将数千个逻辑节点压缩为数十个 `LogicMTask`，最终生成 `AstExecGraph` 供运行时线程池调度。整个流程是**编译时静态分区**，但其分区质量直接决定了仿真运行时能达到的并行度上限。

---

## 关键要点

1. **二部图建模**：OrderGraph 严格由 `OrderLogicVertex`（逻辑块）和 `OrderVarVertex`（变量约束顶点）组成，边只存在于两类顶点之间，利用这种结构可以高效地表达读写依赖和时序约束（PRE/POST/PORD/STD）。
2. **软硬约束分离**：`OrderEdge` 分为 `cutable`（软约束，可断开）和 `non-cutable`（硬约束）。硬约束必须形成 DAG；软约束用于优化延迟赋值（non-blocking）的存储消除。
3. **编译时并行分区**：`V3OrderParallel.cpp` 不是运行时调度器，而是**静态图粗化器**。它将每个逻辑节点映射为 `LogicMTask`，再通过临界路径（Critical Path, CP）驱动的合并策略，将细粒度图压缩到满足 `cpLimit` 的粗粒度图。
4. **数据冒险修复**：`FixDataHazards` 识别在并行模式下会导致运行时竞争的写-写对（如部分赋值的 RMW）和写-读对，通过**合并同 rank 的 MTask** 或添加新边来消除竞争。
5. **临界路径增量传播**：`PropagateCp` 使用 PairingHeap 实现**增量式 CP 更新**，避免每次合并后全图重算，使 `O(N^2)` 的朴素算法降到接近 `O(N log N)`。

---

## 文件级深度分析

### 1. V3Order.h / V3Order.cpp — 主入口与调度流程

#### 文件路径与行号

- `src/V3Order.h`: 定义 `V3Order` 命名空间接口
- `src/V3Order.cpp`:
  - `orderOrderGraph()` (line ~45)
  - `order()` (line ~55)

#### 关键类/数据结构

```cpp
// V3Order.h
using ExternalDomainsProvider = std::function<void(const AstVarScope*, std::vector<AstSenTree*>&)>;
using TrigToSenMap = std::unordered_map<const AstSenTree*, const AstSenTree*>;

AstCFunc* order(AstNetlist* netlistp,
                const std::vector<V3Sched::LogicByScope*>& logic,
                const TrigToSenMap& trigToSen,
                const string& tag,
                bool parallel,   // <-- 是否并行分区
                bool slow,
                const ExternalDomainsProvider& externalDomains) VL_MT_DISABLED;
```

- `parallel` 参数决定最终调用 `createParallel()` 还是 `createSerial()`。
- `VL_MT_DISABLED` 表示整个调度过程是**编译时单线程**执行的，不牵扯运行时锁竞争。

#### 关键函数分析

```cpp
// V3Order.cpp: order()
AstCFunc* V3Order::order(...) {
    const std::unique_ptr<OrderGraph> graph = buildOrderGraph(netlistp, logic, trigToSen);
    orderOrderGraph(*graph, tag);
    processDomains(netlistp, *graph, tag, externalDomains);
    const std::unique_ptr<OrderMoveGraph> moveGraphp = OrderMoveGraph::build(*graph, trigToSen);

    AstNodeStmt* stmtsp = nullptr;
    if (!moveGraphp->empty()) {
        if (parallel) {
            stmtsp = createParallel(*graph, *moveGraphp, tag, slow);  // <-- 多线程路径
        } else {
            stmtsp = createSerial(*moveGraphp, tag, slow);
        }
    }
    // ... 组装到 AstCFunc
}
```

- **流程**：构建 OrderGraph → 排序/破环 → 处理 domain → 构建 MoveGraph → （并行路径）分区生成 MTask → 包装为 `AstCFunc`。

---

### 2. V3OrderGraph.h — 二部依赖图与约束顶点

#### 文件路径与行号

- `src/V3OrderGraph.h`

#### 关键类/数据结构定义

```cpp
class OrderGraph final : public V3Graph {
    inline void addHardEdge(OrderLogicVertex* fromp, OrderVarVertex* top, int weight);
    inline void addSoftEdge(OrderLogicVertex* fromp, OrderVarVertex* top, int weight);
    // ... 反向也各有一对
};
```

- **二部图保证**：`addHardEdge`/`addSoftEdge` 的四个重载利用类型系统确保边只存在于 `OrderLogicVertex` ↔ `OrderVarVertex` 之间。

```cpp
class OrderLogicVertex final : public OrderEitherVertex {
    AstNode* const m_nodep;      // 代表的逻辑节点
    AstScope* const m_scopep;
    AstSenTree* const m_hybridp; // 混合组合逻辑的额外敏感列表
    // ...
};

class OrderVarVertex VL_NOT_FINAL : public OrderEitherVertex {
    AstVarScope* const m_vscp;
};

class OrderVarStdVertex  final : public OrderVarVertex {}; // 标准数据依赖
class OrderVarPreVertex  final : public OrderVarVertex {}; // 优化：让 _d=_q 成为 _q 的最后一次读
class OrderVarPostVertex final : public OrderVarVertex {}; // 确保顺序读在组合/延迟写之前
class OrderVarPordVertex final : public OrderVarVertex {}; // 确保 _d=_q 是 _d 的第一次写
```

- **四种变量顶点**分别对应 Verilog 中非阻塞赋值（`<=`）在 C++ 实现中的不同生命周期约束。特别地，`Pre` + `Pord` 的组合允许 V3LifePost 消除 `_d` 临时变量。

```cpp
class OrderEdge final : public V3GraphEdge {
    OrderEdge(..., int weight, bool cutable) : V3GraphEdge{..., weight, cutable} {}
};
```

- `cutable` 区分软硬约束。硬约束（`cutable=false`）必须满足；软约束可被切断用于打破循环或优化存储。

#### 多线程相关实现细节

- 该图本身**不包含线程、锁或原子操作**。它是纯粹的编译时数据结构，但为后续并行分区提供了**精确的依赖关系**。
- 二部图结构使得后续 `FixDataHazards` 能高效枚举“同一变量的所有写者/读者”。

---

### 3. V3OrderGraphBuilder.cpp — 依赖图构建

#### 文件路径与行号

- `src/V3OrderGraphBuilder.cpp`

#### 关键类/数据结构

```cpp
class OrderUser final {
    enum class VarVertexType : uint8_t { STD = 0, PRE = 1, PORD = 2, POST = 3 };
    std::array<OrderVarVertex*, 4> m_vertexps;
};
```

- 每个 `AstVarScope` 通过 `AstVarScope::user1p` 关联到一个 `OrderUser`，按需创建四种变量顶点。

#### 关键函数分析

```cpp
class OrderGraphBuilder final : public VNVisitor {
    void iterateLogic(AstNode* nodep) {
        m_logicVxp = new OrderLogicVertex{m_graphp, m_scopep, m_domainp, m_hybridp, nodep};
        iterateChildren(nodep);
        m_logicVxp = nullptr;
    }
};
```

```cpp
// visit(AstNodeVarRef* nodep) 中的核心逻辑 (~line 180-260)
if (gen) { // 变量被写入
    if (m_inPost) {
        m_graphp->addHardEdge(m_logicVxp, getVarVertex(varscp, STD),  WEIGHT_NORMAL);
        m_graphp->addHardEdge(getVarVertex(varscp, POST), m_logicVxp, WEIGHT_POST);
    } else if (!m_inClocked) { // 组合逻辑
        m_graphp->addHardEdge(m_logicVxp, getVarVertex(varscp, STD),  WEIGHT_NORMAL);
        m_graphp->addHardEdge(getVarVertex(varscp, POST), m_logicVxp, WEIGHT_POST);
    } else if (m_inPre) { // AlwaysPre (_d = _q)
        m_graphp->addHardEdge(m_logicVxp, getVarVertex(varscp, PORD), WEIGHT_NORMAL);
        m_graphp->addHardEdge(m_logicVxp, getVarVertex(varscp, STD),  WEIGHT_NORMAL);
    } else { // 顺序逻辑 (clocked)
        m_graphp->addHardEdge(getVarVertex(varscp, PORD), m_logicVxp, WEIGHT_NORMAL);
        m_graphp->addHardEdge(m_logicVxp, getVarVertex(varscp, STD),  WEIGHT_NORMAL);
    }
}
if (con) { // 变量被读取
    if (m_inPost) {
        m_graphp->addHardEdge(getVarVertex(varscp, STD), m_logicVxp, WEIGHT_MEDIUM);
    } else if (!m_inClocked) { // 组合逻辑
        m_graphp->addHardEdge(getVarVertex(varscp, STD), m_logicVxp, WEIGHT_MEDIUM);
    } else if (m_inPre) { // AlwaysPre
        m_graphp->addSoftEdge(getVarVertex(varscp, PRE), m_logicVxp, WEIGHT_PRE); // 软约束！
    } else { // 顺序逻辑
        m_graphp->addHardEdge(m_logicVxp, getVarVertex(varscp, PRE),  WEIGHT_NORMAL);
        m_graphp->addHardEdge(m_logicVxp, getVarVertex(varscp, POST), WEIGHT_POST);
    }
}
```

- **组合逻辑**使用 `WEIGHT_NORMAL` 硬边；`WEIGHT_COMBO`（1）用于标记可切割的循环依赖。
- **AlwaysPre**（`m_inPre`）对 `PRE` 顶点的读使用**软约束**（`addSoftEdge`），说明这是优化性约束而非正确性约束。
- **顺序逻辑**会同时生成 `PRE` 和 `POST` 边，确保 `_d = _q` 发生在所有读 `_q` 之后，且所有写 `_d` 之前。

---

### 4. V3OrderParallel.cpp — 并行分区器（核心多线程代码）

这是本文件组中最复杂、与多线程关系最直接的一个文件。它**不管理运行时线程**，而是**静态地将 RTL 逻辑图划分为可并行执行的 MTask（M=Multithreaded）**。

#### 文件路径与行号

- `src/V3OrderParallel.cpp`（共 2512 行）

#### 关键类/数据结构定义

##### 4.1 LogicMTask

```cpp
// ~line 280
class LogicMTask final : public V3GraphVertex {
    OrderMoveVertex::List m_mVertices;  // 包含的细粒度顶点（不拥有）
    uint64_t m_cost = 0;                // 执行代价（V3InstrCount 估计）
    std::array<uint64_t, GraphWay::NUM_WAYS> m_critPathCost = {}; // 前向/反向临界路径
    const uint32_t m_id;                // 唯一 ID（保证确定性输出）
    uint64_t m_generation = 0;            // 用于 pathExistsFrom 的剪枝标记
    std::unordered_set<LogicMTask*> m_edgeSet; // 快速相对顶点查询
    std::array<EdgeHeap, GraphWay::NUM_WAYS> m_edgeHeap; // 按 CP 排序的边堆
    std::set<LogicMTask*> m_siblings;
    // ...
};
```

- `m_cost` 由 `V3InstrCount::count()` 估算，单位为抽象时间。
- `stepCost()`（~line 315）实现**阶梯代价**：将代价向上取整到最近的 5% 对数边界，这样微小合并不会触发大规模 CP 重传播。

```cpp
static uint64_t stepCost(uint64_t cost) {
    double logcost = log(cost);
    logcost *= 20.0; logcost = ceil(logcost); logcost /= 20.0;
    return static_cast<uint64_t>(exp(logcost));
}
```

##### 4.2 MTaskEdge

```cpp
// ~line 240
class MTaskEdge final : public V3GraphEdge, public MergeCandidate {
    std::array<EdgeHeap::Node, GraphWay::NUM_WAYS> m_edgeHeapNode;
public:
    MTaskEdge(V3Graph* graphp, LogicMTask* fromp, LogicMTask* top, int weight);
    bool mergeWouldCreateCycle() const;
    void resetCriticalPaths();
};
```

- `MTaskEdge` 同时继承 `V3GraphEdge` 和 `MergeCandidate`，因为它既表示依赖，也作为**合并候选**被放入 Scoreboard。
- `mergeWouldCreateCycle()` 使用 `LogicMTask::pathExistsFrom()` 检查合并是否会引入环（~line 300）。

##### 4.3 MergeCandidate / SiblingMC

```cpp
// ~line 180
class MergeCandidate VL_NOT_FINAL : public MergeCandidateScoreboard::Node {
    static constexpr uint64_t IS_SIBLING_MASK = 1ULL << 0;
    // 为了省 8 字节并避免虚表，用 ID 的最低位标记子类型
    bool isSiblingMC() const { return m_key.m_id & IS_SIBLING_MASK; }
    SiblingMC* toSiblingMC();
    MTaskEdge* toMTaskEdge();
    bool mergeWouldCreateCycle() const;
};

class SiblingMC final : public MergeCandidate {
    LogicMTask* const m_ap;
    LogicMTask* const m_bp;
    // 两个 MTask 是某个共同邻居的“sibling”，可以合并以减少任务数
};
```

- **Sibling merge**：两个 MTask 如果都是同一个上游/下游节点的邻居（即没有直接依赖但共享前置/后置），合并它们不会增加该方向的 CP。这种合并对于“星型”图结构特别重要。

##### 4.4 PropagateCp

```cpp
// ~line 450
template <GraphWay::en N_Way>
class PropagateCp final {
    PendingHeap m_pendingHeap;  // PairingHeap，按 CP 增长量排序
    // ...
    void cpHasIncreased(V3GraphVertex* vxp, uint64_t newInclusiveCp);
    void go();
};
```

- `cpHasIncreased`：当某个节点代价增长时，向其**下游/上游**邻居的边堆中更新边权，并将受影响的邻居加入 pending。
- `go()`：从 pending heap 中**按增长量从大到小**处理。关键性质：**每个节点在当前 pass 中只被更新一次**，这避免了递归的 `O(N^2)` 行为。

#### 关键函数分析

##### 4.5 Contraction::contract() — 核心合并逻辑

```cpp
// ~line 1382
void contract(MergeCandidate* mergeCanp) {
    // 1. 决定 donor（被合并）和 recipient（保留）
    LogicMTask *recipientp, *donorp;
    if (fromp->cost() > top->cost()) { recipientp = fromp; donorp = top; }
    else { donorp = fromp; recipientp = top; }

    // 2. 计算合并后的新 CP（4 种情况：recipient/donor × forward/reverse）
    const NewCp recipientNewCpFwd = newCp<GraphWay::FORWARD>(recipientp, donorp, mergeEdgep);
    // ...

    // 3. 从 scoreboard 移除候选，删除连接边
    m_sb.remove(mergeCanp);
    // ...

    // 4. 合并顶点列表与代价
    recipientp->moveAllVerticesFrom(donorp);

    // 5. 设置新的 CP，并触发增量传播（如果传播条件满足）
    recipientp->setCritPathCost(GraphWay::FORWARD, recipientNewCpFwd.cp);
    if (recipientNewCpFwd.propagate) {
        m_forwardPropagator.cpHasIncreased(recipientp, recipientNewCpFwd.propagateCp);
    }
    // ... donor 也需要传播
    m_forwardPropagator.go();
    m_reversePropagator.go();

    // 6. 重定向所有边，删除 donor
    partRedirectEdgesFrom(m_mTaskGraph, recipientp, donorp, &m_sb);

    // 7. 重新生成 sibling 候选
    siblingPairFromRelatives<GraphWay::REVERSE, true>(recipientp);
    siblingPairFromRelatives<GraphWay::FORWARD, true>(recipientp);
    // ... 限制考虑的边数 PART_SIBLING_EDGE_LIMIT = 26
}
```

- **合并启发式**：优先合并对局部 CP 影响最小的 pair（score 最低）。
- **Score limit**：`cpLimit = totalGraphCost * 3 / (5 * threads)`。如果 `actualScore > m_scoreLimit` 且任务数仍超过 `maxMTasks`，则放宽 limit 继续合并（~line 1233）。
- **Entry/Exit 保护**：避免合并 entry/exit 节点，否则会导致全局串行化（~line 1261）。

##### 4.6 FixDataHazards — 数据竞争修复

```cpp
// ~line 1775
class FixDataHazards final {
    using TasksByRank = std::map<uint32_t /*rank*/, std::set<LogicMTask*, MTaskIdLessThan>>;

    void mergeSameRankTasks(const TasksByRank& tasksByRank) {
        LogicMTask* lastRecipientp = nullptr;
        for (const auto& pair : tasksByRank) {
            // 找出同 rank 中代价最大的作为 recipient
            LogicMTask* recipientp = ...;
            // 合并所有同 rank 的写者/读者
            for (LogicMTask* const donorp : pair.second) {
                if (donorp == recipientp) continue;
                recipientp->moveAllVerticesFrom(donorp);
                partRedirectEdgesFrom(m_mTaskGraph, recipientp, donorp, nullptr);
            }
            // 在不同 rank 之间添加串行边
            if (lastRecipientp && !lastRecipientp->hasRelativeMTask(recipientp)) {
                new MTaskEdge{&m_mTaskGraph, lastRecipientp, recipientp, 1};
            }
            lastRecipientp = recipientp;
        }
    }
};
```

- **为什么需要 FixDataHazards**：
  1. **部分赋值 RMW**：`sig[15:8] = ...` 和 `sig[7:0] = ...` 在 Verilator 中生成读-改-写（RMW）C++ 代码。串行模式下顺序无关，但并行模式下会竞争。
  2. **循环逻辑被切边**：V3Order 为打破循环会切断某些软边，串行模式下通过迭代收敛掩盖，并行模式下会导致无序读写竞争。
  3. **DPI 调用**：非线程安全的 DPI 导入函数必须被串行化。
  4. **SystemC 变量**：共享底层数据结构，必须全局串行化。

##### 4.7 Partitioner::setupMTaskDeps() — 建立初始 MTask 图

```cpp
// ~line 2197
uint64_t setupMTaskDeps() VL_MT_DISABLED {
    m_entryMTaskp = new LogicMTask{m_mTaskGraphp.get(), nullptr};
    // ... 为每个 OrderMoveVertex 创建 LogicMTask（除非被 bypass）
    m_exitMTaskp = new LogicMTask{m_mTaskGraphp.get(), nullptr};

    // bypassOk：如果变量顶点 fanIn*fanOut <= fanIn+fanOut，则跳过创建 MTask，直接添加传递边
    // 这能将工作集减少一个数量级
    static bool bypassOk(OrderMoveVertex* mvtxp) {
        if (mvtxp->logicp()) return false; // 逻辑顶点不 bypass
        unsigned fanIn = 0, fanOut = 0;
        // ... 计数到 3 停止
        return fanIn <= 1 || fanOut <= 1 || (fanIn + fanOut == 4);
    }
    // ...
    // 将孤立入口/出口连接到 entry/exit 顶点，使全图连通，允许 sibling merge
}
```

##### 4.8 createParallel() — 生成 AstExecGraph

```cpp
// ~line 2397
AstNodeStmt* V3Order::createParallel(const OrderGraph& orderGraph, OrderMoveGraph& moveGraph,
                                       const std::string& tag, bool slow) {
    // 1. 分区
    const std::unique_ptr<V3Graph> mTaskGraphp = Partitioner::apply(orderGraph, moveGraph);

    // 2. 清理未分配的变量顶点
    // ... reroute and delete

    // 3. 删除跨 MTask 的边，将顶点重新链入 MTask 列表
    // ...

    // 4. 创建 AstExecGraph
    AstExecGraph* const execGraphp = new AstExecGraph{flp, tag};
    V3Graph* const depGraphp = execGraphp->depGraphp();

    // 5. 按拓扑序遍历 MTask，序列化内部逻辑，生成 ExecMTask
    OrderMoveGraphSerializer serializer{moveGraph};
    V3OrderCFuncEmitter emitter{tag, slow};
    while (const V3GraphVertex* const vtxp = mtaskStream.nextp()) {
        const LogicMTask* const cMTaskp = vtxp->as<LogicMTask>();
        // ... 将内部 OrderMoveVertex 加入 serializer
        while (OrderMoveVertex* const mVtxp = mTaskp->vertexList().unlinkFront()) {
            if (mVtxp->inEmpty()) serializer.addSeed(mVtxp);
        }
        // 按就绪顺序发射逻辑
        while (OrderMoveVertex* const mVtxp = serializer.getNext()) {
            if (OrderLogicVertex* const logicp = mVtxp->logicp()) {
                if (domScopep != prevDomScopep) emitter.forceNewFunction();
                emitter.emitLogic(logicp);
            }
            VL_DO_DANGLING(mVtxp->unlinkDelete(&moveGraph), mVtxp);
        }
        ExecMTask* const execMTaskp = new ExecMTask{execGraphp, scopep, emitter.getStmts()};
        // ... 建立 ExecMTask 之间的依赖边
    }
    return execGraphp;
}
```

- `AstExecGraph` 是运行时可见的节点，它包含一个 `V3Graph`（`depGraphp`），其顶点是 `ExecMTask`，边是运行时依赖。
- `V3OrderCFuncEmitter` 将每个 `LogicMTask` 内的所有 `OrderLogicVertex` 发射为 `AstCFunc`；这些函数最终会被 `V3ExecGraph` 调度到线程池上执行。

---

### 5. V3OrderInternal.h — 内部接口

#### 文件路径与行号

- `src/V3OrderInternal.h`

该头文件仅暴露 `V3Order` 命名空间下的内部函数声明，供 `V3Order.cpp`、`V3OrderGraphBuilder.cpp`、`V3OrderParallel.cpp` 等使用。无多线程特有数据结构，但 `createParallel()` 的签名在此声明。

---

### 6. V3OrderCFuncEmitter.h — 逻辑顶点到 C 函数发射

#### 文件路径与行号

- `src/V3OrderCFuncEmitter.h`

#### 关键类定义

```cpp
class V3OrderCFuncEmitter final {
    const std::string m_tag;
    const bool m_slow;
    const bool m_split = v3Global.opt.outputSplitCFuncs();
    size_t m_size = 0;
    const size_t m_splitSize = ...;
    AstCFunc* m_funcp = nullptr;
    std::map<std::pair<AstNodeModule*, std::string>, unsigned> m_funcNums;
    std::vector<std::pair<AstCFunc*, AstSenTree*>> m_result;

    std::string cfuncName(FileLine* flp, AstScope* scopep, AstNodeModule* modp,
                          AstSenTree* domainp) {
        std::string name = "_" + m_tag;
        name += domainp->isMulti() ? "_comb" : "_sequent";
        name += "__" + scopep->nameDotless();
        name += "__" + std::to_string(m_funcNums[{modp, name}]++);
        return name;
    }

public:
    void emitLogic(const OrderLogicVertex* lVtxp);
    AstNodeStmt* getStmts();
};
```

#### 关键函数分析

```cpp
void emitLogic(const OrderLogicVertex* lVtxp) {
    AstSenTree* const domainp = lVtxp->domainp();
    AstNode* const logicp = lVtxp->nodep();
    AstNodeProcedure* const procp = VN_CAST(logicp, NodeProcedure);
    const bool suspendable = procp && procp->isSuspendable();

    // 可挂起进程（coroutine）必须独占函数
    if (suspendable) forceNewFunction();
    if (v3Global.opt.profCFuncs()) forceNewFunction();
    if (!m_result.empty() && m_result.back().second != domainp) forceNewFunction();

    // 拆分逻辑：非 procedure 整体处理；procedure 按语句拆分
    AstNode* const headp = ...;
    for (AstNode *currp = headp, *nextp; currp; currp = nextp) {
        if (!suspendable && m_size >= m_splitSize) forceNewFunction();
        if (!m_funcp) { /* 创建新 AstCFunc */ }
        m_funcp->addStmtsp(currp);
        if (m_split) m_size += currp->nodeCount();
    }
    if (suspendable) forceNewFunction();
}
```

- `getStmts()` 返回 `AstIf` 包裹的 `AstCCall` 列表，每个 `AstIf` 检查对应的 sensitivity trigger。
- 在并行模式下，每个 `LogicMTask` 会调用一次 `emitter.getStmts()`，生成一个 `ExecMTask` 对应的函数体。

---

## 对 RTL 仿真器多线程化的启示

### 1. 编译时静态分区 vs 运行时动态调度

Verilator 的 `V3OrderParallel` 采用**纯静态分区**：在编译时就决定了哪些逻辑块可以放到同一个 MTask 中，哪些必须串行。这种方式的优缺点：
- **优点**：运行时调度开销极低（只需按拓扑序启动 MTask），不需要运行时依赖分析；局部性好（同一个 MTask 内的逻辑连续执行）。
- **缺点**：无法适应输入相关的动态负载变化；如果某周期某些 MTask 无实际工作（敏感条件未触发），仍然需要在运行时判断是否跳过（通过 `AstIf` 条件）。

> **启示**：对于自研 RTL 仿真器，如果目标是**编译型仿真器**（类似 Verilator 的 AOT 模式），静态分区是首选；如果目标是**解释型/事件驱动型**（如 Icarus），则需要考虑运行时动态调度或混合策略。

### 2. 二部图建模的通用性

V3Order 用**二部图**（Logic ↔ Variable）精确建模 RTL 的读写依赖，而不是直接连接逻辑块。这种设计：
- 让变量的生命周期约束（PRE/POST/PORD/STD）天然成为图节点；
- 使 `FixDataHazards` 能直接通过变量顶点枚举所有相关 MTask；
- 让 `bypassOk` 优化成为可能（因为变量顶点是可丢弃的传递节点）。

> **启示**：在任何需要精确分析信号依赖的仿真器/编译器中，二部图比单纯逻辑块之间的 DAG 更灵活，尤其适合处理 Verilog/VHDL 中部分赋值、非阻塞赋值等复杂语义。

### 3. 临界路径（CP）驱动的图粗化

`Contraction` 的核心不是“负载均衡”，而是**控制临界路径长度**。`cpLimit` 的设定（`totalCost * 3 / (5 * threads)`）确保：
- 如果图完全可并行，则 CP ≈ totalCost / threads，理想加速比接近 threads；
- 如果图本身串行度高，分区器不会强行拆分到不合理的粒度，而是逐步放宽 limit。

> **启示**：对于 RTL 这类天然带有大量串行依赖（时钟域链、组合反馈）的 workload，直接用图割（graph cut）或负载均衡策略会严重拉长 CP。应该以**CP 优先**的合并策略，保证在任务数可控的前提下，不破坏并行潜力。

### 4. 阶梯代价（Stepped Cost）的工程智慧

`LogicMTask::stepCost()` 将代价向上取整到最近的 5% 对数边界。这是一个典型的**工程折中**：牺牲少量 CP 精度，换取 `PropagateCp` 在大图上的 `O(N log N)` 性能。文档中明确提到：
> "If there are huge vertices, when a tiny vertex merges into a huge vertex, we can often avoid increasing the huge vertex's stepped cost... Since huge vertices tend to have huge lists of children and parents, this can be a substantial savings."

> **启示**：在自研分区器或调度器中，引入**容忍一定误差的增量更新机制**（如步进量化、延迟传播）可能比精确全量重算快几个数量级，且对最终并行度影响微乎其微。

### 5. 数据冒险的保守修复策略

`FixDataHazards` 对“可能有问题”的情况采取**保守合并**（同 rank 全部合并），而不是精细分析。理由：
> "merging all readers and writers at the same rank together is 'the simplest thing that could possibly work'... We don't want to create tons of edges here, doing so is not nice to the main edge contraction pass."

> **启示**：在静态分区阶段，**宁可多串化一点，也不能留下运行时竞争**。因为运行时竞争是极难调试的 Heisenbug。对于自研仿真器，如果静态分析无法 100% 证明无竞争，应选择保守合并或添加 happens-before 边。

### 6. Sibling Merge 的必要性

文档中多次强调 sibling merge 的重要性。在纯 edge merge 中，星型图（中心节点连接大量输入/输出）会导致中心节点无限膨胀，而边缘节点无法合并。Sibling merge 允许合并“没有直接依赖但共享邻居”的节点，解决了这个问题。

> **启示**：图粗化算法如果只考虑直接边上的合并，在 Fan-in/Fan-out 极高的节点（如顶层 module 的时钟使能信号）周围会陷入局部最优。引入**间接邻居合并**（sibling/coarsening via common neighbor）是必要的补充策略。

### 7. Bypass 优化减少工作集

`bypassOk()` 的启发式 `fanIn * fanOut <= fanIn + fanOut` 是一个简单的**中间节点消除**条件。在从 MoveGraph 到 MTaskGraph 的转换中，它允许跳过创建大量低连通度的变量顶点，将细粒度图直接“坍缩”为粗粒度图。

> **启示**：在多层图转换中（RTL AST → 依赖图 → 调度图 → 执行图），引入**中间节点消除**能显著降低后续算法的输入规模。Verilator 在此处使用了一个非常保守但安全的阈值（1 或 2 度），确保不会引入过多传递边。

---

## 原文摘录

> "OrderGraph is a bipartite graph, with the two parts being formed of only OrderLogicVertex and OrderVarVertex vertices respectively (i.e.: edges are always between OrderLogicVertex and OrderVarVertex, and never between two OrderLogicVertex or OrderVarVertex). The fact that OrderGraph is bipartite is important and we take advantage of this fact in various algorithms, so this property must be maintained."
> — `V3OrderGraph.h` 注释

> "The partitioner attempts to deal with such densely connected graphs. Some of the tuning parameters below reference 'huge vertices', that's what they're talking about, vertices with tens of thousands of edges in and out."
> — `V3OrderParallel.cpp` 头部注释

> "Cost stepping can lead to corner cases. A developer may wish to disable cost stepping to rule it out as the cause of unexpected behavior."
> — `V3OrderParallel.cpp` 关于 `PART_STEPPED_COST`

> "Thread scheduler is unable to provide requested parallelism; suggest asking for fewer threads."
> — `V3OrderParallel.cpp` 警告 `UNOPTTHREADS`

> "In parallel mode, we must serialize these RMW's to avoid a race."
> — `V3OrderParallel.cpp` `FixDataHazards` 注释

> "If your vertices are small, the limit (at 26) approaches a no-op. Hence there's basically no cost to applying this limit even when we don't expect huge vertices."
> — `V3OrderParallel.cpp` 关于 `PART_SIBLING_EDGE_LIMIT`

---

## 相关链接

- [V3ExecGraph 执行图分析](wiki-verilator-V3ExecGraph执行图.md) — 运行时 MTask 调度与线程池
- [V3Sched 调度器](wiki-V3Sched调度器.md) — 触发条件与 sensitivity domain 管理
- [Verilator Thread Pool](wiki-verilator-v3threadpool.md) — 运行时线程池实现
- [Verilator 源码仓库](https://github.com/verilator/verilator)
- [Verilator 官方文档：多线程](https://verilator.org/guide/latest/verilating.html#multithreading)

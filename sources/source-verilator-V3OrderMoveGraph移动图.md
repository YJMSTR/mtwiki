---
title: "V3OrderMoveGraph 移动图与多线程调度"
source_url: "https://github.com/verilator/verilator/tree/master/src/V3OrderMoveGraph.h"
source_type: "github-code"
author: "Verilator Team"
date: ""
tags: ["verilator", "multithreading", "ordering", "move-graph", "domain-analysis", "serialization", "dependency-graph"]
keywords: ["OrderMoveGraph", "OrderMoveVertex", "OrderMoveDomScope", "OrderMoveGraphSerializer", "domainsExclusive", "V3OrderProcessDomains", "V3OrderSerial"]
capture_date: "2026-07-04"
---

# V3OrderMoveGraph 移动图与多线程调度

## 来源

- **V3OrderMoveGraph.h**: https://github.com/verilator/verilator/blob/master/src/V3OrderMoveGraph.h  
- **V3OrderMoveGraph.cpp**: https://github.com/verilator/verilator/blob/master/src/V3OrderMoveGraph.cpp  
- **V3OrderProcessDomains.cpp**: https://github.com/verilator/verilator/blob/master/src/V3OrderProcessDomains.cpp  
- **V3OrderSerial.cpp**: https://github.com/verilator/verilator/blob/master/src/V3OrderSerial.cpp  
- 类型: GitHub 源码  
- 作者: Verilator Team (Wilson Snyder)  
- 许可证: LGPL-3.0-only OR Artistic-2.0

## 摘要

`V3OrderMoveGraph` 是 Verilator 编译流水线中**从细粒度 OrderGraph 到粗粒度 MoveGraph 的转换层**，是连接前端依赖分析（V3OrderProcessDomains）与后端代码生成（V3OrderSerial）的关键桥梁。其核心设计思想是：**通过时钟域（domain）和作用域（scope）对逻辑顶点进行分组，并基于互斥域检测（domainsExclusive）消除不必要的依赖边，从而为后续的串行/并行代码生成提供最小化的调度图**。虽然 `OrderMoveGraph` 的构建过程本身标记为 `VL_MT_DISABLED`（编译期单线程），但它生成的图结构直接决定了多线程仿真运行时的**任务粒度、调度顺序和并行度上限**。

## 关键要点

- `OrderMoveGraph` 是 `OrderGraph` 的粗化版本，将变量顶点按 (domain, scope) 对折叠，显著降低图规模
- `domainsExclusive()` 是核心并行性分析函数：检测 `posedge clk` 与 `negedge clk` 等互斥时钟域，消除它们之间的依赖边
- `OrderMoveDomScope` 以 (domain, scope) 为键管理就绪顶点列表，是多线程任务分组的天然边界
- `OrderMoveGraphSerializer` 实现拓扑排序（Kahn 算法），其调度策略（优先同 domain 同 scope）可直接映射到多线程 work-list 调度器
- `V3OrderProcessDomains` 通过传播和合并输入域，为每个顶点确定唯一的触发域；从未触发的逻辑被标记为删除
- `V3OrderSerial::createSerial` 将 MoveGraph 展平为串行 C++ 语句序列，通过 `forceNewFunction()` 在 domain/scope 切换处划分函数边界

---

## 一、文件结构总览

| 文件 | 职责 | 行数（估算） | 多线程相关度 |
|------|------|-------------|-------------|
| `V3OrderMoveGraph.h` | 定义 `OrderMoveGraph`、`OrderMoveVertex`、`OrderMoveDomScope`、`OrderMoveGraphSerializer` | ~170 | ⭐⭐⭐⭐⭐ |
| `V3OrderMoveGraph.cpp` | 实现 `OrderMoveGraphBuilder`，从 `OrderGraph` 构建 `MoveGraph` | ~150 | ⭐⭐⭐⭐⭐ |
| `V3OrderProcessDomains.cpp` | 为每个顶点计算时钟域（domain），合并/简化域表达式 | ~200 | ⭐⭐⭐⭐ |
| `V3OrderSerial.cpp` | 使用 `OrderMoveGraphSerializer` 将 MoveGraph 序列化为 C++ 代码 | ~60 | ⭐⭐⭐⭐ |

---

## 二、关键类与数据结构定义

### 2.1 OrderMoveVertex（V3OrderMoveGraph.h 第 33–68 行）

```cpp
class OrderMoveVertex final : public V3GraphVertex {
    VL_RTTI_IMPL(OrderMoveVertex, V3GraphVertex)

    OrderLogicVertex* const m_logicp;      // 对应的逻辑顶点，nullptr 表示变量顶点
    OrderMoveDomScope& m_domScope;          // 所属 (domain, scope) 分组
    V3ListLinks<OrderMoveVertex> m_links;   // 用于 V3List 链表

public:
    using List = V3List<OrderMoveVertex, &OrderMoveVertex::links>;

    OrderMoveVertex(OrderMoveGraph& graph, OrderLogicVertex* lVtxp,
                    const AstSenTree* domainp) VL_MT_DISABLED;
    OrderLogicVertex* logicp() const VL_MT_STABLE { return m_logicp; }
    OrderMoveDomScope& domScope() const { return m_domScope; }
};
```

**分析**：
- `VL_MT_DISABLED` 标记在构造函数上，表明 `OrderMoveGraph` 的构建发生在**编译期单线程阶段**，不需要考虑并发安全。这是 Verilator 的典型设计模式：编译器前端在单线程下构建复杂数据结构，运行时复用这些预计算结构。
- `VL_MT_STABLE` 标记在 `logicp()` 上，表示返回的指针在对象生命周期内不会改变，多线程读取时无需同步。
- 每个 `OrderMoveVertex` 要么代表一个**逻辑顶点**（`m_logicp != nullptr`），要么代表一个**变量顶点在特定 domain 下的代理**（`m_logicp == nullptr`）。这种二象性是图粗化的关键。

### 2.2 OrderMoveDomScope（V3OrderMoveGraph.h 第 79–138 行）

```cpp
class OrderMoveDomScope final {
    OrderMoveVertex::List m_readyVertices;   // 该 (domain, scope) 下的就绪顶点列表
    V3ListLinks<OrderMoveDomScope> m_links;  // 用于全局就绪列表
    bool m_isOnList = false;                  // 是否已在全局就绪列表中
    const AstSenTree* const m_domainp;        // 时钟域
    const AstScope* const m_scopep;           // 作用域

    using DomScopeMap = std::unordered_map<DomScopeMapKey, OrderMoveDomScope, ...>;
    static DomScopeMap s_dsMap;  // 全局 (domain, scope) -> DomScope 映射

public:
    using List = V3List<OrderMoveDomScope, &OrderMoveDomScope::links>;

    static OrderMoveDomScope& getOrCreate(const AstSenTree* domainp, const AstScope* scopep);
    static void clear() { s_dsMap.clear(); }

    OrderMoveVertex::List& readyVertices() { return m_readyVertices; }
    bool isOnList() const { return m_isOnList; }
    void isOnList(bool value) { m_isOnList = value; }
};
```

**分析**：
- `OrderMoveDomScope` 是**多线程调度的天然任务桶**。每个实例对应一个唯一的 `(domain, scope)` 对，这意味着：
  - **同一 domain** 的顶点可以共享时钟触发条件，减少多线程运行时的事件分发开销
  - **同一 scope** 的顶点可以复用局部变量和上下文，提高缓存局部性
- `s_dsMap` 是全局静态映射，在编译期构建，运行时只读（线程安全）
- `m_readyVertices` 使用 Verilator 自定义的 `V3List` 双向链表，而非 `std::list`，避免动态分配开销
- `m_isOnList` 用于 O(1) 判断 DomScope 是否已在全局就绪队列中，防止重复入队

### 2.3 OrderMoveGraphSerializer（V3OrderMoveGraph.h 第 142–217 行）

```cpp
class OrderMoveGraphSerializer final {
    OrderMoveDomScope::List m_readyDomScopeps;  // 全局就绪 DomScope 列表
    OrderMoveDomScope* m_nextDomScopep = nullptr; // 下一个待处理的 DomScope

    void ready(OrderMoveVertex* vtxp) {
        if (vtxp->logicp()) {
            OrderMoveDomScope& domScope = vtxp->domScope();
            domScope.readyVertices().linkBack(vtxp);
            if (!domScope.isOnList()) {
                domScope.isOnList(true);
                m_readyDomScopeps.linkBack(&domScope);
            }
        } else {
            for (V3GraphEdge& edge : vtxp->outEdges()) {
                OrderMoveVertex* const dVtxp = edge.top()->as<OrderMoveVertex>();
                const uint32_t nDeps = dVtxp->user() - 1;
                dVtxp->user(nDeps);
                if (!nDeps) ready(dVtxp);
            }
        }
    }

public:
    explicit OrderMoveGraphSerializer(OrderMoveGraph& moveGraph) {
        for (V3GraphVertex& vtx : moveGraph.vertices()) {
            vtx.user(vtx.inEdges().size());  // user() = 入度（依赖数）
        }
    }

    void addSeed(OrderMoveVertex* vtxp) { ready(vtxp); }

    OrderMoveVertex* getNext() {
        if (!m_nextDomScopep) m_nextDomScopep = m_readyDomScopeps.frontp();
        if (!m_nextDomScopep) return nullptr;
        OrderMoveDomScope& currDomScope = *m_nextDomScopep;
        OrderMoveVertex::List& currReadyList = currDomScope.readyVertices();
        OrderMoveVertex* mVtxp = currReadyList.unlinkFront();

        // 处理出边，递减下游顶点依赖数
        for (V3GraphEdge& edge : mVtxp->outEdges()) {
            OrderMoveVertex* const dVtxp = edge.top()->as<OrderMoveVertex>();
            const uint32_t nDeps = dVtxp->user() - 1;
            dVtxp->user(nDeps);
            if (!nDeps) ready(dVtxp);
        }

        // 优先继续处理同 domain 的其他 scope
        if (currReadyList.empty()) {
            m_nextDomScopep = nullptr;
            for (OrderMoveDomScope& domScope : m_readyDomScopeps) {
                if (domScope.domainp() == currDomScope.domainp()) {
                    m_nextDomScopep = &domScope;
                    break;
                }
            }
        }
        return mVtxp;
    }
};
```

**分析**：
- 这是**编译期版本的 work-list 调度器**，算法本质为 Kahn 拓扑排序（BFS 版）。
- `user()` 字段被重载为**入度计数器**（剩余依赖数），归零时顶点变为就绪。
- `ready()` 函数是核心调度决策点：
  - 对于逻辑顶点：加入所属 `DomScope` 的就绪列表，若该 `DomScope` 不在全局列表中则入队
  - 对于变量顶点（`logicp() == nullptr`）：直接传播依赖释放，不加入就绪列表（因为变量顶点不生成代码）
- `getNext()` 的** domain 优先策略**非常巧妙：
  - 当当前 `DomScope` 处理完毕后，优先寻找**同 domain 的其他 scope**，而非跳到下一个全局 `DomScope`
  - 这确保了同一时钟域内的逻辑被连续执行，减少多线程仿真中的时钟同步事件数量
  - 在 MTRM（Multithreaded Runtime Model）中，这对应于**按域分批调度**，每批内部可以进一步并行化

---

## 三、关键函数深度分析

### 3.1 domainsExclusive() — 互斥域检测（V3OrderMoveGraph.cpp 第 86–108 行）

```cpp
bool domainsExclusive(AstSenTree* fromp, AstSenTree* top) {
    // 检测 posedge clk 与 negedge clk 是否互斥
    const AstSenItem* const fromSenItemp = getOrigSenItem(fromp);
    if (!fromSenItemp) return false;
    const AstSenItem* const toSenItemp = getOrigSenItem(top);
    if (!toSenItemp) return false;

    const AstNodeVarRef* const fromVarrefp = fromSenItemp->varrefp();
    if (!fromVarrefp) return false;
    const AstNodeVarRef* const toVarrefp = toSenItemp->varrefp();
    if (!toVarrefp) return false;

    // 必须是同一时钟信号
    if (fromVarrefp->varScopep() != toVarrefp->varScopep()) return false;

    return fromSenItemp->edgeType().exclusiveEdge(toSenItemp->edgeType());
}
```

**多线程意义**：
- 这是 Verilator 实现**隐式并行化**的关键优化点。在传统的 RTL 仿真中，`posedge clk` 和 `negedge clk` 的 always 块之间存在**写后读依赖**（通过变量连接），因此必须串行执行。
- 但 Verilator 通过 `domainsExclusive()` 证明：**同一时钟的上升沿和下降沿不可能在同一 eval 轮次中同时触发**，因此它们之间的依赖边可以被安全移除。
- 在 `iterateVarVertex()` 中（第 147–161 行），这条边被跳过：
  ```cpp
  if (domainsExclusive(domainp, lVtxp->domainp())) continue;
  ```
- **对多线程的启示**：编译期的域互斥分析可以**解除不必要的顺序约束**，在不引入竞态的情况下增加可并行任务数。对于自定义 RTL 仿真器，这意味着：
  - 必须维护一个精确的时钟域数据库
  - 在依赖图构建阶段就执行域互斥分析，而非运行时动态判断
  - 互斥信息可以编码为**调度图的颜色/标签**，供运行时调度器快速查询

### 3.2 iterateLogicVertex() — 逻辑顶点遍历（V3OrderMoveGraph.cpp 第 118–144 行）

```cpp
void iterateLogicVertex(const OrderLogicVertex* lvtxp) {
    AstSenTree* const domainp = lvtxp->domainp();
    OrderMoveVertex* const lMoveVtxp = static_cast<OrderMoveVertex*>(lvtxp->userp());
    for (const V3GraphEdge& edge : lvtxp->outEdges()) {
        if (edge.weight() == 0) continue;  // 被切断的边
        const OrderVarVertex* const vvtxp = static_cast<const OrderVarVertex*>(edge.top());
        DomainMap& mapp = *static_cast<DomainMap*>(vvtxp->userp());
        const auto pair = mapp.emplace(domainp, nullptr);
        OrderMoveVertex*& vMoveVtxp = pair.first->second;
        if (pair.second) vMoveVtxp = iterateVarVertex(vvtxp, domainp);
        if (!vMoveVtxp) continue;
        addEdge(lMoveVtxp, vMoveVtxp);  // 逻辑顶点 -> (变量, domain) 顶点
    }
}
```

**多线程意义**：
- `OrderGraph` 是**二分图**（LogicVertex ↔ VarVertex ↔ LogicVertex），`OrderMoveGraph` 将其粗化为**单分图**（LogicVertex/MoveVertex → MoveVertex）。
- 变量顶点按 `domain` 分组：同一个变量在不同 domain 下会生成不同的 `OrderMoveVertex`。这是** domain-aware 的依赖追踪**。
- `mapp.emplace(domainp, nullptr)` 使用 `DomainMap`（`std::map<const AstSenTree*, OrderMoveVertex*>`）按 domain 缓存变量顶点，避免重复遍历。复杂度从指数降到线性。

### 3.3 iterateVarVertex() — 变量顶点遍历（V3OrderMoveGraph.cpp 第 147–161 行）

```cpp
OrderMoveVertex* iterateVarVertex(const OrderVarVertex* vvtxp, AstSenTree* domainp) {
    OrderMoveVertex* vMoveVtxp = nullptr;
    for (const V3GraphEdge& edge : vvtxp->outEdges()) {
        if (edge.weight() == 0) continue;
        const OrderLogicVertex* const lVtxp = edge.top()->as<OrderLogicVertex>();
        if (domainsExclusive(domainp, lVtxp->domainp())) continue;  // 关键优化
        if (!vMoveVtxp) vMoveVtxp = new OrderMoveVertex{*m_moveGraphp, nullptr, domainp};
        OrderMoveVertex* const lMoveVxp = static_cast<OrderMoveVertex*>(lVtxp->userp());
        addEdge(vMoveVtxp, lMoveVxp);
    }
    return vMoveVtxp;
}
```

**多线程意义**：
- 如果某变量在某 domain 下没有下游逻辑（所有下游都在互斥域），`iterateVarVertex` 返回 `nullptr`，这意味着**该变量顶点在 MoveGraph 中不存在**，进一步减少了图规模。
- 这是**死路径消除**的一种形式：编译期证明某些变量在特定 domain 下不会触发任何计算，因此不需要建立依赖边。

### 3.4 V3OrderProcessDomains::processDomains() — 域传播（V3OrderProcessDomains.cpp 第 72–130 行）

```cpp
void processDomains() {
    for (V3GraphVertex& it : m_graph.vertices()) {
        OrderEitherVertex* const vtxp = it.as<OrderEitherVertex>();
        if (vtxp->domainp()) continue;  // 时序逻辑已有域

        AstSenTree* domainp = nullptr;
        OrderLogicVertex* const lvtxp = vtxp->cast<OrderLogicVertex>();
        if (lvtxp) domainp = lvtxp->hybridp();  // 显式混合敏感域

        for (V3GraphEdge& edge : vtxp->inEdges()) {
            if (!edge.weight()) continue;
            OrderEitherVertex* const fromVtxp = edge.fromp()->as<OrderEitherVertex>();
            if (!fromVtxp->domainMatters()) continue;
            AstSenTree* fromDomainp = fromVtxp->domainp();

            // 添加外部域（如 DPI/VPI 触发的变量）
            if (OrderVarVertex* const varVtxp = fromVtxp->cast<OrderVarVertex>()) {
                externalDomainps.clear();
                m_externalDomains(vscp, externalDomainps);
                for (AstSenTree* const externalDomainp : externalDomainps) {
                    fromDomainp = combineDomains(fromDomainp, externalDomainp);
                }
            }
            if (fromDomainp == m_deleteDomainp) continue;
            domainp = domainp ? combineDomains(domainp, fromDomainp) : fromDomainp;
        }

        if (!domainp) {
            domainp = m_deleteDomainp;
            if (lvtxp) m_logicpsToDelete.push_back(lvtxp);
        } else {
            domainp = simplifyDomain(domainp);
        }
        vtxp->domainp(domainp);
    }
}
```

**多线程意义**：
- `processDomains` 是**前向数据流分析**：从输入端（触发源）向输出端传播时钟域信息。
- 对于组合逻辑，如果所有输入都来自同一时序域，该组合逻辑会被**吸收进该域**（domain pushing），减少全组合逻辑的数量。
- `m_externalDomains` 是一个回调函数，允许外部模块（如 VPI/DPI）注入额外的敏感域。这保证了**多线程运行时与外部世界的正确交互**：如果某变量可能被外部代码修改，其域必须包含外部触发条件。
- `m_deleteDomainp` 标记从未触发的逻辑，这些逻辑在后续被删除，减少运行时无意义计算。

### 3.5 V3Order::createSerial() — 串行代码生成（V3OrderSerial.cpp 第 33–64 行）

```cpp
AstNodeStmt* V3Order::createSerial(OrderMoveGraph& moveGraph, const std::string& tag, bool slow) {
    OrderMoveGraphSerializer serializer{moveGraph};

    // 添加种子：入度为 0 的顶点（无依赖）
    for (V3GraphVertex& vtx : moveGraph.vertices()) {
        if (vtx.inEmpty()) serializer.addSeed(vtx.as<OrderMoveVertex>());
    }

    V3OrderCFuncEmitter emitter{tag, slow};
    OrderMoveDomScope* prevDomScopep = nullptr;
    while (OrderMoveVertex* const mVtxp = serializer.getNext()) {
        if (OrderLogicVertex* const logicp = mVtxp->logicp()) {
            OrderMoveDomScope* const domScopep = &mVtxp->domScope();
            if (domScopep != prevDomScopep) emitter.forceNewFunction();
            prevDomScopep = domScopep;
            emitter.emitLogic(logicp);
        }
        VL_DO_DANGLING(mVtxp->unlinkDelete(&moveGraph), mVtxp);
    }
    return emitter.getStmts();
}
```

**多线程意义**：
- `createSerial` 是**单线程代码生成路径**，但其中的调度逻辑（`getNext()` + `forceNewFunction()`）是理解多线程版本的基础。
- `forceNewFunction()` 在 domain 或 scope 切换时创建新函数，这意味着：
  - 同一 `(domain, scope)` 内的逻辑被合并到同一个 C++ 函数中
  - 不同 domain/scope 之间的切换是**显式函数调用边界**
- 在多线程版本中（`V3OrderParallel.cpp`，未在本次分析范围内），这些函数边界很可能成为**任务划分边界**：每个 `DomScope` 对应一个可独立调度的任务或任务组。

---

## 四、多线程相关实现细节总结

### 4.1 编译期 vs 运行期的线程安全分工

| 阶段 | 代码位置 | 线程安全标记 | 说明 |
|------|---------|-------------|------|
| 图构建 | `V3OrderMoveGraph.cpp` | `VL_MT_DISABLED` | 编译期单线程，无并发需求 |
| 顶点访问 | `V3OrderMoveGraph.h` | `VL_MT_STABLE` | 构建完成后只读，多线程安全 |
| 域处理 | `V3OrderProcessDomains.cpp` | `VL_MT_DISABLED` | 编译期单线程 |
| 串行生成 | `V3OrderSerial.cpp` | `VL_MT_DISABLED` | 编译期单线程 |

### 4.2 隐式并行化机制

`domainsExclusive()` 是 Verilator 实现**隐式并行化**的核心。通过证明两个时钟域在物理上不可能同时触发，编译器可以：
1. 移除它们之间的依赖边
2. 在 `OrderMoveGraph` 中形成**不连通的子图**
3. 这些子图在多线程运行时可以被**无锁地分配到不同线程**

### 4.3 数据结构的多线程扩展性

- `V3List` 是侵入式链表，无动态分配，非常适合多线程运行时的无锁队列实现（可用 CAS 操作 `linkBack`/`unlinkFront`）
- `user()` 字段作为入度计数器，在多线程版本中可替换为 `std::atomic<uint32_t>`，实现依赖计数的无锁递减
- `OrderMoveDomScope` 的 `(domain, scope)` 分组天然对应**任务窃取调度器**中的任务队列：每个 worker 线程优先处理同一 domain 的任务，窃取时跨 domain 窃取

### 4.4 调度策略的多线程映射

`OrderMoveGraphSerializer::getNext()` 的 domain 优先策略映射到多线程：
```
单线程版：
  currDomScope 为空 -> 寻找同 domain 的下一个 DomScope -> 返回顶点

多线程版（推测）：
  Worker 线程 A 持有 Domain_X 的多个 DomScope
  Worker 线程 B 持有 Domain_Y 的多个 DomScope
  Domain_X 和 Domain_Y 若互斥，则 A/B 可并行执行
  Domain 内通过 barrier 同步 eval 轮次
```

---

## 五、对 RTL 仿真器多线程化的启示

### 5.1 设计建议

1. **编译期域分析是并行化的前提**
   - 不要试图在运行时动态检测时钟域互斥，信息在编译期就已确定
   - 维护一个 `Domain -> 互斥 Domain 集合` 的映射表，作为调度器的只读输入

2. **(Domain, Scope) 是理想的任务分组键**
   - 同一 domain 的顶点共享触发事件，可以减少线程间的同步次数
   - 同一 scope 的顶点共享局部状态，可以提高缓存命中率
   - 这种二维分组键比纯拓扑分区和纯循环分区更适合 RTL 仿真

3. **依赖计数器用原子变量实现无锁就绪队列**
   - 借鉴 `user()` 作为入度计数器的设计，运行时版本可用 `std::atomic<int>`
   - 当计数器归零时，通过无锁队列（如 Michael-Scott queue）将任务推入全局就绪池

4. **消除死路径是并行化的副作用**
   - `V3OrderProcessDomains` 删除从未触发的逻辑，这在多线程中尤为重要：死路径会占用调度器和内存带宽

5. **函数边界 = 任务边界**
   - `V3OrderSerial::forceNewFunction()` 在 domain/scope 切换处划分函数，这种划分逻辑可以直接用于多线程任务划分

### 5.2 可迁移的代码模式

| Verilator 模式 | 自定义实现建议 |
|---------------|--------------|
| `domainsExclusive()` | 编译期域互斥表 + 运行时只读查询 |
| `OrderMoveDomScope` | `std::unordered_map<Key, TaskQueue>` 或固定大小的数组 |
| `V3List` + `user()` 计数 | `boost::lockfree::queue` + `std::atomic<int>` 依赖计数 |
| `getNext()` domain 优先 | 线程本地队列优先同 domain，全局队列跨 domain |
| `forceNewFunction()` | 任务边界标记，用于 OpenMP `#pragma omp task` 或 TBB `task_group` |

---

## 六、原文摘录

> "OrderMoveGraph is constructed from the fine-grained OrderGraph. It is a slightly coarsened representation of dependencies used to drive serialization."
> — V3OrderMoveGraph.h 第 72–74 行

> "Return 'true' if we can prove that both 'from' and 'to' cannot both be active on the same evaluation, or false if we can't prove this. This detects the case of 'always @(posedge clk)' and 'always @(negedge clk)' being exclusive."
> — V3OrderMoveGraph.cpp 第 86–92 行

> "If no more ready vertices in the current DomScope, prefer to continue with a new scope under the same domain."
> — V3OrderMoveGraph.h 第 205–207 行

> "Sequential logic already has their domain defined. Combo logic may be pushed into a seq domain if all its inputs are the same domain."
> — V3OrderProcessDomains.cpp 第 78–82 行

---

## 七、相关链接

- [Verilator 官方仓库](https://github.com/verilator/verilator)
- [V3OrderGraph.h — 基础 OrderGraph 定义](https://github.com/verilator/verilator/blob/master/src/V3OrderGraph.h)
- [V3OrderParallel.cpp — 多线程并行代码生成（未分析）](https://github.com/verilator/verilator/blob/master/src/V3OrderParallel.cpp)
- [Verilator 多线程文档](https://verilator.org/guide/latest/exe_verilator.html#multithreading)
- [source-verilator-mt-deep](source-verilator-mt-deep.md) — Verilator 多线程深层分析
- [source-verilator-partition-evolution](source-verilator-partition-evolution.md) — 分区策略演进

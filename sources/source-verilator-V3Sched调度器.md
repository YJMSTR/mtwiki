---
title: "Verilator V3Sched 调度器核心组"
source_url: "https://github.com/verilator/verilator/tree/master/src/"
source_type: "github-code"
author: "Verilator Team"
date: ""
tags: ["verilator", "multithreading", "scheduling", "V3Sched", "trigger-vector", "eval-loop", "NBA-region", "partitioning", "replication", "acyclic-break", "timing-integration"]
keywords: ["Verilator", "调度器", "多线程", "触发向量", "NBA", "Act", "分区", "复制", "组合循环"]
capture_date: "2026-07-05"
---

# Verilator V3Sched 调度器核心组

## 来源

- **仓库**: verilator/verilator
- **文件组**: V3Sched.h, V3Sched.cpp, V3SchedAcyclic.cpp, V3SchedPartition.cpp, V3SchedReplicate.cpp, V3SchedTiming.cpp, V3SchedTrigger.cpp
- **路径**: `src/V3Sched*.cpp/h`
- **类型**: github-code
- **作者**: Wilson Snyder / Verilator Team
- **捕获日期**: 2026-07-05

## 摘要

V3Sched 是 Verilator 编译流程中**最核心的调度模块**，负责将 Verilog 的逻辑（always 块、assign 等）分类、排序、分区，并生成 C++ 代码中的 `_eval` 函数。该文件组定义了触发向量（Trigger Vector）、评估循环（Eval Loop）、逻辑分区（act/nba/ico/obs/react）、组合循环打破、逻辑复制等关键机制。多线程并行化只在 **NBA 区域** 启用，Act/Ico 区域被实验证实为净损失。整个调度器被标记为 `VL_MT_DISABLED`，属于编译期单线程代码，但生成的运行时结构支持多线程执行。

## 关键要点

1. **调度是编译期单线程，生成运行时多线程结构**：V3Sched 本身被标记 `VL_MT_DISABLED_CODE_UNIT`，但生成的 NBA 区域函数可借助 `V3Order` 和 `mtasks()` 在多线程上执行。
2. **触发向量（Trigger Vector）是调度核心**：每个调度区域（act/nba/ico/obs/react）有独立的触发向量，用 64 位字组成的位数组存储触发状态，检测是否有工作需要执行。
3. **NBA 是唯一从多线程获益的区域**：V3Sched.cpp 第 9 步注释明确说明 Act/Ico 区域多线程总是净损失，只有 NBA 区域使用多线程。
4. **#0 延迟会摧毁并行性**：如果设计使用 `#0` 延迟，几乎所有逻辑必须进入 act 区域，导致 NBA 区域无逻辑可并行化。
5. **组合循环打破通过图算法实现**：V3SchedAcyclic.cpp 构建依赖图，使用强连通分量（SCC）检测和反馈弧集（Feedback Arc Set）算法将循环边转换为 hybrid 逻辑。
6. **逻辑复制解决跨区域依赖**：V3SchedReplicate.cpp 通过数据流图传播驱动区域信息，将组合逻辑复制到 ico/act/nba/obs/react 多个区域。
7. **触发器系统使用位级操作**：V3SchedTrigger.cpp 实现了触发位向量分配、触发检测函数、扩展触发向量和 before-trigger 优化。

---

## 文件 1: V3Sched.h — 核心数据结构定义

### 文件路径与行号

`src/V3Sched.h`（约 340 行）

### 关键类/数据结构

#### `LogicByScope`（第 48 行起）

```cpp
struct LogicByScope final : public std::vector<std::pair<AstScope*, AstActive*>> {
    void add(AstScope* scopep, AstSenTree* senTreep, AstNode* logicp);
    LogicByScope clone() const;
    void deleteActives();
    void foreachLogic(const std::function<void(AstNode*)>& f) const;
};
```

- **作用**：存储按作用域（AstScope）组织的逻辑块（AstActive）列表，是调度器的基础容器。
- **多线程意义**：`clone()` 允许为不同区域复制逻辑，为多线程执行准备独立的逻辑副本。

#### `LogicClasses`（第 77 行起）

```cpp
struct LogicClasses final {
    LogicByScope m_static;     // Static 变量初始化
    LogicByScope m_initial;    // initial 块
    LogicByScope m_final;      // final 块
    LogicByScope m_comb;       // 组合逻辑（隐式敏感）
    LogicByScope m_clocked;    // 时序逻辑（显式敏感）
    LogicByScope m_hybrid;     // 混合逻辑（组合 + 部分显式敏感）
    LogicByScope m_postponed;  // $strobe 等
    LogicByScope m_observed;   // always @(*)
    LogicByScope m_reactive;   // reactive 逻辑
};
```

- **作用**：按触发类型对设计中的所有逻辑进行分类。
- **多线程意义**：`m_comb` 和 `m_hybrid` 是循环打破和复制的核心对象；`m_clocked` 被分区到 act/nba。

#### `LogicRegions`（第 91 行起）

```cpp
struct LogicRegions final {
    LogicByScope m_pre;    // 'act' 区域中的 AlwaysPre
    LogicByScope m_act;    // 'act' 区域逻辑
    LogicByScope m_nba;    // 'nba' 区域逻辑
    LogicByScope m_obs;    // 'obs' 区域逻辑
    LogicByScope m_react;  // 're' 区域逻辑
};
```

- **作用**：将逻辑按 SystemVerilog 调度区域（Active/NBA/Observed/Reactive）分区。
- **多线程意义**：`m_nba` 是唯一被实验证实可以从多线程获益的区域。

#### `LogicReplicas`（第 103 行起）

```cpp
struct LogicReplicas final {
    LogicByScope m_ico;    // Input Combinational 区域
    LogicByScope m_act;    // Active 区域副本
    LogicByScope m_nba;    // NBA 区域副本
    LogicByScope m_obs;    // Observed 区域副本
    LogicByScope m_react;  // Reactive 区域副本
};
```

- **作用**：存储组合逻辑被复制到多个区域后的副本。
- **多线程意义**：复制后的逻辑允许不同区域独立执行，减少线程同步需求。

#### `TriggerKit`（第 115 行起）

**最核心的多线程支持类**。管理触发向量的创建、计算和使用。

```cpp
class TriggerKit final {
    static constexpr uint32_t WORD_SIZE_LOG2 = 6;  // 64-bit / VL_QUADSIZE
    static constexpr uint32_t WORD_SIZE = 1 << WORD_SIZE_LOG2;  // 64
    
    const uint32_t m_nSenseWords;   // Sense 触发器字数
    const uint32_t m_nExtraWords;   // Extra 触发器字数
    const uint32_t m_nPreWords;     // Pre 触发器字数
    const uint32_t m_nVecWords = m_nSenseWords + m_nExtraWords;
    
    AstVarScope* m_vscp = nullptr;       // 扩展触发向量
    AstVarScope* m_vscAccp = nullptr;    // 触发累加器（用于 act 区域迭代）
    AstCFunc* m_compVecp = nullptr;      // 计算基础触发器
    AstCFunc* m_compExtp = nullptr;      // 计算扩展触发器
    
    std::unordered_map<VNRef<const AstSenItem>, size_t> m_senItem2TrigIdx;
    std::unordered_map<const AstSenTree*, AstSenTree*> m_mapPre;
    std::unordered_map<const AstSenTree*, AstSenTree*> m_mapVec;
```

**触发向量布局**（文档注释，第 115-170 行）：

```
| <- bit N-1                                         bit 0 -> |
+--------------------+----------------+------------------------+--------------------+
| Pre triggers       | Extra triggers | Sense triggers         | Pre Sense triggers |
+--------------------+----------------+------------------------+--------------------+
|        'pre'       |                        'vec'                                  |
```

- **Pre triggers**：只在 act 区域单次评估中触发，用于 AlwaysPre 块。
- **Extra triggers**：表示非 SenItem 条件（如 DPI export 触发、first iteration）。
- **Sense triggers**：对应 SenItem 的常规触发。
- **Pre Sense triggers**：常规 Sense 触发器的副本，在首次触发时复制到 Pre 区域。

- **多线程意义**：
  - 触发向量用 **64 位字** 存储，适合位级并行操作（如 `VL_QUADSIZE`）。
  - `m_vscAccp`（触发累加器）用于在 act 区域多轮迭代中累加触发状态，避免丢失触发事件。
  - `createAnySetFunc()` 遍历所有字检查是否有触发位被设置，是循环开销的关键点。

#### `TimingKit`（第 210 行起）

```cpp
class TimingKit final {
    AstCFunc* m_resumeFuncp = nullptr;
    AstCFunc* m_readyFuncp = nullptr;
    std::map<const AstVarScope*, std::set<AstSenTree*>> m_externalDomains;
public:
    LogicByScope m_lbs;
    AstNodeStmt* m_postUpdates = nullptr;
    
    std::map<const AstVarScope*, std::vector<AstSenTree*>> remapDomains(
        const std::unordered_map<const AstSenTree*, AstSenTree*>& trigMap) const VL_MT_DISABLED;
    AstVarScope* getDelayScheduler(AstNetlist* const netlistp) VL_MT_DISABLED;
    AstCCall* createResume(AstNetlist* const netlistp) VL_MT_DISABLED;
    AstCCall* createReady(AstNetlist* const netlistp) VL_MT_DISABLED;
```

- **作用**：集成时序（timing）特性与静态调度。
- **多线程意义**：`VL_MT_DISABLED` 标记说明时序相关逻辑在编译期处理。`createResume`/`createReady` 生成运行时调用。

#### `VirtIfaceTriggers`（第 230 行起）

```cpp
class VirtIfaceTriggers final {
    struct TriggerEntry final {
        const AstIface* m_ifacep;
        const AstVar* m_memberp;
        AstVarScope* m_vscp;
    };
    std::vector<TriggerEntry> m_triggers;
    using VscpSensMap = std::map<const AstVarScope*, AstSenTree*>;
    VscpSensMap makeVscpToSensMap(...) const;
```

- **作用**：为虚拟接口（virtual interface）的值变化创建额外触发器。

### 全局函数声明

```cpp
VirtIfaceTriggers makeVirtIfaceTriggers(AstNetlist* nodep) VL_MT_DISABLED;
TimingKit prepareTiming(AstNetlist* const netlistp) VL_MT_DISABLED;
void transformForks(AstNetlist* const netlistp) VL_MT_DISABLED;
void schedule(AstNetlist*) VL_MT_DISABLED;  // 主入口

LogicByScope breakCycles(AstNetlist* netlistp, const LogicByScope& combinationalLogic) VL_MT_DISABLED;
LogicRegions partition(LogicByScope& clockedLogic, LogicByScope& combinationalLogic, LogicByScope& hybridLogic) VL_MT_DISABLED;
LogicReplicas replicateLogic(LogicRegions&) VL_MT_DISABLED;
```

所有主要函数标记为 `VL_MT_DISABLED`，说明调度器本身是**编译期单线程**的。

---

## 文件 2: V3Sched.cpp — 主调度器入口

### 文件路径与行号

`src/V3Sched.cpp`（约 580 行）

### 关键函数分析

#### `schedule()` — 顶级入口（第 500 行起）

```cpp
void schedule(AstNetlist* netlistp) {
    // Step 0: 准备虚拟接口触发器和时序逻辑
    const auto& virtIfaceTriggers = makeVirtIfaceTriggers(netlistp);
    TimingKit timingKit = prepareTiming(netlistp);
    
    // Step 1: 收集并分类所有逻辑
    LogicClasses logicClasses = gatherLogicClasses(netlistp);
    
    // Step 2: 按源码顺序调度 static/initial/final
    AstCFunc* const staticp = createStatic(netlistp, logicClasses);
    createInitial(netlistp, logicClasses);
    createFinal(netlistp, logicClasses);
    
    // Step 3: 打破组合循环
    logicClasses.m_hybrid = breakCycles(netlistp, logicClasses.m_comb);
    
    // Step 4: 创建 'settle' 区域
    createSettle(netlistp, staticp, senExprBuilder, logicClasses);
    
    // Step 5: 分区到时序/组合区域（pre/act/nba）
    LogicRegions logicRegions = partition(...);
    
    // Step 6: 复制组合逻辑
    LogicReplicas logicReplicas = replicateLogic(logicRegions);
    
    // Step 7: 创建 ico 输入组合逻辑循环
    AstNode* const icoLoopp = createInputCombLoop(...);
    
    // Step 8: 创建触发器
    const TriggerKit trigKit = TriggerKit::create(...);
    
    // Step 9: 创建 'act' 区域评估函数
    //    注意：Act 区域多线程被实验证实为净损失
    AstCFunc* const actFuncp = V3Order::order(...);
    
    // Step 10: 创建 'nba' 区域评估函数
    //    多线程标记：name == "nba" && v3Global.opt.mtasks()
    const EvalKit nbaKit = order("nba", {&logicRegions.m_nba, &logicReplicas.m_nba});
    
    // Step 11-12: 创建 obs/re 区域
    // Step 13: 创建 postponed 区域
    // Step 14: 组装 _eval 函数
    createEval(netlistp, icoLoopp, trigKit, actKit, nbaKit, obsKit, reactKit, postponedFuncp, timingKit);
    
    // Step 15-16: 清理和收尾
}
```

**16 步调度流程**是 Verilator 调度器的完整骨架。

#### `createEvalLoop()` — 评估循环构建（第 70 行起）

```cpp
EvalLoop createEvalLoop(
    AstNetlist* netlistp,
    const std::string& tag,      // 当前阶段标签
    const string& name,           // 阶段名称
    bool slow,                    // 是否创建慢函数
    const TriggerKit& trigKit,    // 触发器工具包
    AstVarScope* trigp,           // 触发向量（或 condp）
    AstNodeExpr* condp,           // 显式条件
    AstNodeStmt* innerp,          // 内层循环
    AstNodeStmt* phasePrepp,      // 检查触发器前的准备语句
    AstNodeStmt* phaseWorkp,      // 触发时执行的工作
    std::function<AstNodeStmt*(AstVarScope*)> phaseExtra  // 额外工作
) {
    // 如果无触发器/条件，直接返回内层循环
    if (!trigp && !condp) return {nullptr, innerp};
    
    // 创建 phase 函数（顶层或子函数）
    AstCFunc* const phaseFuncp = util::makeTopFunction(netlistp, "_eval_phase__" + tag, slow);
    
    // 执行标志：如果触发器被触发则执行工作
    AstVarScope* const executeFlagp = scopeTopp->createTemp(varPrefix + "Execute", 1);
    
    // 检查是否有任何触发器被触发
    AstNodeExpr* const rhsp = condp ? condp : trigKit.newAnySetCall(trigp);
    phaseFuncp->addStmtsp(new AstAssign{flp, lhsp, rhsp});
    
    // 循环结构：计数器 + 首次迭代标志 + 阶段结果
    AstVarScope* const counterp = addVar("IterCount", 32, 0, true);
    AstVarScope* const firstIterFlagp = addVar("FirstIteration", 1, 1, true);
    AstVarScope* const phaseResultp = addVar("PhaseResult", 1, 0, false);
    
    // 创建循环：检查迭代限制 -> 递增计数器 -> 执行内层 -> 调用 phase 函数
    // 直到 continuation flag 清除
}
```

- **多线程意义**：每个调度区域（act/nba/ico/obs/react）有自己的 EvalLoop。循环检查触发器是否有任何位被设置，这是多线程区域的入口判断。
- `firstIterFlagp` 用于区分首次迭代，对 settle 循环和 ico 循环很重要。

#### `createEval()` — 组装 _eval 函数（第 355 行起）

```cpp
void createEval(AstNetlist* netlistp, AstNode* icoLoop,
                const TriggerKit& trigKit, const EvalKit& actKit,
                const EvalKit& nbaKit, const EvalKit& obsKit,
                const EvalKit& reactKit, AstCFunc* postponedFuncp, TimingKit& timingKit) {
    // 1. 创建 act 区域的 eval loop（顶层循环）
    EvalLoop topLoop = createEvalLoop(netlistp, "act", "Active", false, trigKit,
        actKit.m_vscp, nullptr, nullptr, prep, work, extra);
    
    // 2. 如果有延迟调度器，创建 inact 循环（#0 延迟）
    if (delaySchedVscp) {
        topLoop = createEvalLoop(netlistp, "inact", "Inactive", false, trigKit,
            nullptr, condition, topLoop.stmtsp, nullptr, work);
    }
    
    // 3. 创建 NBA eval loop（默认顶层循环）
    topLoop = createEvalLoop(netlistp, "nba", "NBA", false, trigKit,
        nbaKit.m_vscp, nullptr, topLoop.stmtsp, nullptr, work, extra);
    
    // 4. 创建 Observed 和 Reactive 循环（如果有）
    // 5. 组装 _eval 函数：ico -> topLoop -> postponed
}
```

**循环嵌套结构**：
```
nba loop (最外层)
  inact loop (如果存在)
    act loop (核心)
      ico loop (如果存在)
```

#### 关键多线程注释（第 466 行）

```cpp
// Note: Experiments so far show that running the Act (or Ico) regions on
// multiple threads is always a net loss, so only use multi-threading for
// NBA for now. This can be revised if evidence is available that it would
// be beneficial
```

这是**最关键的注释**。Verilator 团队通过实验发现：
- **Act 区域多线程 = 净损失**：因为 Act 区域包含时钟逻辑和组合逻辑，存在大量数据依赖，线程同步开销超过收益。
- **Ico 区域多线程 = 净损失**：输入组合逻辑通常规模较小，且与顶层输入变化紧密耦合。
- **NBA 区域 = 唯一获益区域**：NBA（非阻塞赋值）区域通常包含大量独立的状态更新，适合并行化。

#### `order()` lambda — 创建区域评估函数（第 476 行起）

```cpp
const auto order = [&](const std::string& name,
                       const std::vector<V3Sched::LogicByScope*>& logic) -> EvalKit {
    AstVarScope* const trigVscp = trigKit.newTrigVec(name);
    const auto trigMap = cloneMapWithNewTriggerReferences(trigKit.mapVec(), trigVscp);
    
    AstCFunc* const funcp = V3Order::order(
        netlistp, logic, trigToSen, name,
        name == "nba" && v3Global.opt.mtasks(),  // <-- 多线程标记！
        false, ...);
    return {trigVscp, funcp};
};
```

- 只有当 `name == "nba"` 且 `v3Global.opt.mtasks()` 为 true 时，才启用多线程排序。
- `V3Order::order()` 将逻辑进一步排序并可能拆分为 mtasks（多线程任务）。

---

## 文件 3: V3SchedAcyclic.cpp — 打破组合循环

### 文件路径与行号

`src/V3SchedAcyclic.cpp`（约 330 行）

### 关键类/数据结构

#### `SchedAcyclicLogicVertex`（第 40 行）

```cpp
class SchedAcyclicLogicVertex final : public V3GraphVertex {
    AstNode* const m_logicp;      // 逻辑节点
    AstScope* const m_scopep;     // 作用域
public:
    SchedAcyclicLogicVertex(V3Graph* graphp, AstNode* logicp, AstScope* scopep);
    V3GraphVertex* clone(V3Graph* graphp) const override;
    AstNode* logicp() const;
    AstScope* scopep() const;
};
```

#### `SchedAcyclicVarVertex`（第 58 行）

```cpp
class SchedAcyclicVarVertex final : public V3GraphVertex {
    AstVarScope* const m_vscp;    // 变量节点
public:
    SchedAcyclicVarVertex(V3Graph* graphp, AstVarScope* vscp);
    AstVarScope* vscp() const;
    AstVar* varp() const;
};
```

### 关键函数分析

#### `buildGraph()` — 构建依赖图（第 82 行）

```cpp
std::unique_ptr<Graph> buildGraph(const LogicByScope& lbs) {
    std::unique_ptr<Graph> graphp{new Graph};
    
    for (const auto& pair : lbs) {
        AstScope* const scopep = pair.first;
        AstActive* const activep = pair.second;
        for (AstNode* nodep = activep->stmtsp(); nodep; nodep = nodep->nextp()) {
            SchedAcyclicLogicVertex* const lvtxp = new SchedAcyclicLogicVertex{...};
            
            nodep->foreach([&](AstVarRef* refp) {
                AstVarScope* const vscp = refp->varScopep();
                SchedAcyclicVarVertex* const vvtxp = getVarVertex(vscp);
                const int weight = vscp->width() / 8 + 1;  // 权重 = 位宽/8 + 1
                
                // 写操作：logic -> var
                if (refp->access().isWriteOrRW())
                    addEdge(lvtxp, vvtxp, weight, true);  // cuttable = true
                
                // 读操作：var -> logic（忽略被写的变量）
                if (refp->access().isReadOrRW() && !vscp->user2())
                    addEdge(vvtxp, lvtxp, weight, true);
            });
        }
    }
    return graphp;
}
```

- **权重策略**：`width/8 + 1`，优先切割**较窄**的信号，减少影响范围。
- **cuttable = true**：所有边默认可切割，通过 `acyclic()` 算法决定切割哪些边。

#### `removeNonCyclic()` — 移除非循环节点（第 115 行）

```cpp
void removeNonCyclic(Graph* graphp) {
    std::vector<V3GraphVertex*> queue;
    // 从入度或出度为 0 的节点开始
    for (V3GraphVertex& vtx : graphp->vertices()) {
        if (vtx.inEmpty() || vtx.outEmpty()) enqueue(&vtx);
    }
    // 迭代移除，直到只保留 SCC 中的节点
}
```

- 拓扑移除不形成循环的节点，只保留**强连通分量（SCC）**中的节点。

#### `breakCycles()` — 主入口（第 280 行）

```cpp
LogicByScope breakCycles(AstNetlist* netlistp, const LogicByScope& combinationalLogic) {
    // 1. 构建依赖图
    const std::unique_ptr<Graph> graphp = buildGraph(combinationalLogic);
    
    // 2. 移除非循环节点
    removeNonCyclic(graphp.get());
    
    if (graphp->empty()) return LogicByScope{};  // 无循环
    
    // 3. 使用 Feedback Arc Set 算法使图无环
    graphp->acyclic(&V3GraphEdge::followAlwaysTrue);
    
    // 4. 找到所有切割变量
    const std::vector<SchedAcyclicVarVertex*> cutVertices = findCutVertices(graphp.get());
    
    // 5. 报告循环和候选变量
    reportCycles(graphp.get(), cutVertices);
    
    // 6. 修复切割：将读取切割变量的逻辑转换为 hybrid 逻辑
    return fixCuts(netlistp, cutVertices);
}
```

- **多线程意义**：组合循环直接阻止并行化（因为循环依赖导致无法确定执行顺序）。通过将循环转换为 hybrid 逻辑（带显式敏感的组合逻辑），可以将剩余的组合逻辑视为无环 DAG，从而支持拓扑排序和并行分区。

#### `fixCuts()` — 修复切割（第 240 行）

```cpp
LogicByScope fixCuts(AstNetlist* netlistp,
                     const std::vector<SchedAcyclicVarVertex*>& cutVertices) {
    // 对于读取切割变量的逻辑，添加显式 hybrid 敏感度
    for (SchedAcyclicLogicVertex* const lvtxp : lvtxps) {
        AstNode* const logicp = lvtxp->logicp();
        // 构建 hybrid 敏感度列表：对切割变量使用 ET_HYBRID 敏感度
        AstSenItem* senItemsp = nullptr;
        for (AstVarScope* const vscp : lvtx2Cuts[lvtxp]) {
            AstVarRef* const refp = new AstVarRef{flp, vscp, VAccess::READ};
            AstSenItem* const nextp = new AstSenItem{flp, VEdgeType::ET_HYBRID, refp};
            senItemsp = AstNode::addNext(senItemsp, nextp);
        }
        AstSenTree* const senTree = new AstSenTree{flp, senItemsp};
        result.add(lvtxp->scopep(), finder.getSenTree(senTree), logicp);
    }
    return result;
}
```

- **hybrid 逻辑**：原本隐式 `@(*)` 的组合逻辑，现在显式加上对切割变量的 `ET_HYBRID` 敏感度。这允许调度器在变量变化时重新执行该逻辑，同时打破循环依赖。

---

## 文件 4: V3SchedPartition.cpp — 逻辑分区

### 文件路径与行号

`src/V3SchedPartition.cpp`（约 230 行）

### 关键类/数据结构

#### `SchedSenVertex`（第 40 行）

```cpp
class SchedSenVertex final : public V3GraphVertex {
    const AstSenItem* const m_senItemp;
public:
    SchedSenVertex(V3Graph* graphp, const AstSenItem* senItemp);
};
```

#### `SchedLogicVertex`（第 55 行）

```cpp
class SchedLogicVertex final : public V3GraphVertex {
    AstScope* const m_scopep;
    AstSenTree* const m_senTreep;
    AstNode* const m_logicp;
public:
    SchedLogicVertex(V3Graph* graphp, AstScope* scopep, AstSenTree* senTreep, AstNode* logicp);
    AstScope* scopep() const;
    AstSenTree* senTreep() const;
    AstNode* logicp() const;
};
```

#### `SchedVarVertex`（第 72 行）

```cpp
class SchedVarVertex final : public V3GraphVertex {
    const AstVarScope* const m_vscp;
public:
    SchedVarVertex(V3Graph* graphp, AstVarScope* vscp);
    AstVar* varp() const;
};
```

### 关键函数分析

#### `SchedGraphBuilder::visitLogic()` — 构建数据流边（第 115 行）

```cpp
void visitLogic(AstNode* nodep) {
    SchedLogicVertex* const logicVtxp = new SchedLogicVertex{...};
    
    // 时序/混合逻辑：添加从敏感度顶点到逻辑顶点的边
    if (!m_senTreep->hasCombo()) {
        m_senTreep->foreach([this, nodep, logicVtxp](AstSenItem* senItemp) {
            V3GraphVertex* const eventVtxp = getSenVertex(senItemp);
            new V3GraphEdge{m_graphp, eventVtxp, logicVtxp, 10};
        });
    }
    
    // 基于变量引用添加边
    nodep->foreach([this, logicVtxp, &forceReadEdgeIgnores](const AstVarRef* vrefp) {
        AstVarScope* const vscp = vrefp->varScopep();
        if (vrefp->access().isReadOrRW() && m_readTriggersThisLogic(vscp)
            && !forceReadEdgeIgnores.count(vscp)) {
            new V3GraphEdge{m_graphp, getVarVertex(vscp), logicVtxp, 10};  // var -> logic
        }
        if (vrefp->access().isWriteOrRW() && !vrefp->varp()->ignoreSchedWrite()) {
            new V3GraphEdge{m_graphp, logicVtxp, getVarVertex(vscp), 10};  // logic -> var
        }
    });
    
    // DPI 导出触发：如果逻辑调用 DPI import，可能触发 DPI export
    if (m_dpiExportTriggerp) {
        nodep->foreach([this, logicVtxp](const AstCCall* callp) {
            if (callp->funcp()->dpiImportWrapper() && callp->funcp()->dpiContext()) {
                new V3GraphEdge{m_graphp, logicVtxp, getVarVertex(m_dpiExportTriggerp), 10};
            }
        });
    }
}
```

- **DPI 导出触发**：如果 DPI import 调用可能触发 DPI export 写操作，则该逻辑必须进入 act 区域（因为可能改变时钟信号）。

#### `colorActiveRegion()` — 标记 Active 区域（第 170 行）

```cpp
void colorActiveRegion(V3Graph& graph) {
    std::vector<V3GraphVertex*> queue{};
    
    // 从所有 SenVertex 开始深度优先遍历
    for (V3GraphVertex& vtx : graph.vertices()) {
        if (const auto activeEventVtxp = vtx.cast<SchedSenVertex>()) {
            queue.push_back(activeEventVtxp);
        }
    }
    
    while (!queue.empty()) {
        V3GraphVertex& vtx = *queue.back();
        queue.pop_back();
        if (vtx.color() != 0) continue;
        
        vtx.color(1);  // 标记为 Active 区域
        
        // 入边传播：所有父节点也进入 Active
        for (V3GraphEdge& edge : vtx.inEdges()) queue.push_back(edge.fromp());
        
        // 如果逻辑顶点，其驱动的变量也进入 Active（确保所有设置都在同一区域）
        if (vtx.is<SchedLogicVertex>()) {
            for (V3GraphEdge& edge : vtx.outEdges()) queue.push_back(edge.top());
        }
    }
}
```

- **分区策略**：从敏感度列表（时钟/信号）反向追踪，所有可能影响时钟信号生成的逻辑进入 Active 区域。其余进入 NBA 区域。

#### `partition()` — 主入口（第 200 行）

```cpp
LogicRegions partition(LogicByScope& clockedLogic, LogicByScope& combinationalLogic,
                       LogicByScope& hybridLogic) {
    // 构建图
    const std::unique_ptr<V3Graph> graphp = SchedGraphBuilder::build(...);
    
    // 标记 Active 区域
    colorActiveRegion(*(graphp.get()));
    
    LogicRegions result;
    for (V3GraphVertex& vtx : graphp->vertices()) {
        if (const auto lvtxp = vtx.cast<SchedLogicVertex>()) {
            bool toAct = lvtxp->color();
            // 致命限制：如果设计使用 #0 延迟，几乎所有逻辑进入 act 区域
            if (v3Global.usesZeroDelay() && !VN_IS(lvtxp->logicp(), AlwaysPost)) toAct = true;
            LogicByScope& lbs = toAct ? result.m_act : result.m_nba;
            // ... 移动逻辑到对应区域
        }
    }
    
    // 进一步区分 Pre 逻辑（AlwaysPre）
    // ...
    return result;
}
```

**关键多线程影响**（第 220 行）：
```cpp
if (v3Global.usesZeroDelay() && !VN_IS(lvtxp->logicp(), AlwaysPost)) toAct = true;
```

- 如果设计使用了 `#0` 延迟，**所有非 Post 逻辑必须进入 act 区域**。
- 这意味着 NBA 区域几乎为空，多线程 NBA 并行化失去意义。
- 这是 Verilator 多线程的一个**重大限制**：不支持 `#0` 延迟的混合设计的多线程优化。

---

## 文件 5: V3SchedReplicate.cpp — 逻辑复制

### 文件路径与行号

`src/V3SchedReplicate.cpp`（约 210 行）

### 关键类/数据结构

#### `RegionFlags` 枚举（第 40 行）

```cpp
enum RegionFlags : uint8_t {
    NONE = 0x0,
    INPUT = 0x1,      // 顶层输入驱动
    ACTIVE = 0x2,     // act 区域驱动
    NBA = 0x4,        // nba 区域驱动
    OBSERVED = 0x8,   // obs 区域驱动
    REACTIVE = 0x10,  // re 区域驱动
};
```

- 位标志设计，允许组合多个区域。

#### `SchedReplicateVertex`（第 50 行）

```cpp
class SchedReplicateVertex VL_NOT_FINAL : public V3GraphVertex {
    RegionFlags m_drivingRegions{RegionFlags::NONE};
public:
    uint8_t drivingRegions() const { return m_drivingRegions; }
    void addDrivingRegions(uint8_t regions) {
        m_drivingRegions = static_cast<RegionFlags>(m_drivingRegions | regions);
    }
};
```

#### `SchedReplicateLogicVertex`（第 75 行）

```cpp
class SchedReplicateLogicVertex final : public SchedReplicateVertex {
    AstScope* const m_scopep;
    AstSenTree* const m_senTreep;
    AstNode* const m_logicp;
    RegionFlags const m_assignedRegion;  // 原始分配区域
public:
    SchedReplicateLogicVertex(V3Graph* graphp, AstScope* scopep, AstSenTree* senTreep,
                              AstNode* logicp, RegionFlags assignedRegion);
    RegionFlags assignedRegion() const { return m_assignedRegion; }
};
```

#### `SchedReplicateVarVertex`（第 95 行）

```cpp
class SchedReplicateVarVertex final : public SchedReplicateVertex {
    AstVarScope* const m_vscp;
public:
    SchedReplicateVarVertex(V3Graph* graphp, AstVarScope* vscp) : SchedReplicateVertex{graphp}, m_vscp{vscp} {
        // 顶层输入自动标记 INPUT
        if (varp()->isPrimaryInish() || varp()->isSigUserRWPublic() || varp()->sampled()
            || varp()->isWrittenByDpi() || varp()->sensIfacep() || varp()->isVirtIface()) {
            addDrivingRegions(INPUT);
        }
        // suspendable 进程写入的变量标记 ACTIVE
        if (varp()->isWrittenBySuspendable()) addDrivingRegions(ACTIVE);
    }
};
```

### 关键函数分析

#### `buildGraph()` — 构建复制图（第 115 行）

```cpp
std::unique_ptr<Graph> buildGraph(const LogicRegions& logicRegions) {
    std::unique_ptr<Graph> graphp{new Graph};
    
    const auto addLogic = [&](RegionFlags region, AstScope* scopep, AstActive* activep) {
        // 根据敏感度类型确定读触发条件
        std::function<bool(AstVarScope*)> readTriggersThisLogic;
        if (senTreep->hasClocked()) {
            readTriggersThisLogic = [](AstVarScope*) { return false; };
        } else if (senTreep->hasCombo()) {
            readTriggersThisLogic = [](AstVarScope*) { return true; };
        } else {  // hybrid
            readTriggersThisLogic = [](AstVarScope* vscp) { return !vscp->user4(); };
        }
        
        for (AstNode* nodep = activep->stmtsp(); nodep; nodep = nodep->nextp()) {
            SchedReplicateLogicVertex* const lvtxp = new SchedReplicateLogicVertex{...};
            nodep->foreach([&](AstVarRef* refp) {
                AstVarScope* const vscp = refp->varScopep();
                SchedReplicateVarVertex* const vvtxp = getVarVertex(vscp);
                
                // 读边：var -> logic（如果读触发此逻辑）
                if (refp->access().isReadOrRW() && readTriggersThisLogic(vscp))
                    addEdge(vvtxp, lvtxp);
                
                // 写边：logic -> var（忽略 AlwaysPostponed）
                if (refp->access().isWriteOrRW() && !VN_IS(nodep, AlwaysPostponed))
                    addEdge(lvtxp, vvtxp);
            });
        }
    };
    
    // 为所有区域添加逻辑
    for (const auto& pair : logicRegions.m_pre) addLogic(ACTIVE, ...);
    for (const auto& pair : logicRegions.m_act) addLogic(ACTIVE, ...);
    for (const auto& pair : logicRegions.m_nba) addLogic(NBA, ...);
    for (const auto& pair : logicRegions.m_obs) addLogic(OBSERVED, ...);
    for (const auto& pair : logicRegions.m_react) addLogic(REACTIVE, ...);
    
    return graphp;
}
```

#### `propagateDrivingRegions()` — 传播驱动区域（第 180 行）

```cpp
void propagateDrivingRegions(SchedReplicateVertex* vtxp) {
    if (vtxp->user()) return;  // 已访问
    
    // 计算所有输入的驱动区域并集
    uint8_t drivingRegions = 0;
    for (V3GraphEdge& edge : vtxp->inEdges()) {
        SchedReplicateVertex* const srcp = edge.fromp()->as<SchedReplicateVertex>();
        propagateDrivingRegions(srcp);
        drivingRegions |= srcp->drivingRegions();
    }
    
    vtxp->addDrivingRegions(drivingRegions);
    vtxp->user(true);  // 标记已访问
}
```

- 递归传播驱动区域信息。由于图是无环的（已被 breakCycles 处理），递归安全。

#### `replicate()` — 复制逻辑（第 195 行）

```cpp
LogicReplicas replicate(Graph* graphp) {
    LogicReplicas result;
    for (V3GraphVertex& vtx : graphp->vertices()) {
        if (SchedReplicateLogicVertex* const lvtxp = vtx.cast<SchedReplicateLogicVertex>()) {
            const auto replicateTo = [&](LogicByScope& lbs) {
                lbs.add(lvtxp->scopep(), lvtxp->senTreep(), lvtxp->logicp()->cloneTree(false));
            };
            // 需要复制到的目标区域 = 驱动区域 \ 原始区域
            const uint8_t targetRegions = lvtxp->drivingRegions() & ~lvtxp->assignedRegion();
            
            UASSERT(!lvtxp->senTreep()->hasClocked() || targetRegions == 0,
                    "replicating clocked logic");
            
            if (targetRegions & INPUT) replicateTo(result.m_ico);
            if (targetRegions & ACTIVE) replicateTo(result.m_act);
            if (targetRegions & NBA) replicateTo(result.m_nba);
            if (targetRegions & OBSERVED) replicateTo(result.m_obs);
            if (targetRegions & REACTIVE) replicateTo(result.m_react);
        }
    }
    return result;
}
```

- **关键断言**：时序逻辑（clocked）从不被复制。只有组合逻辑（combo/hybrid）可能被复制到多个区域。
- **复制目标**：如果组合逻辑被 act 区域和 nba 区域同时驱动，则需要在两个区域都有副本。

#### `replicateLogic()` — 主入口（第 220 行）

```cpp
LogicReplicas replicateLogic(LogicRegions& logicRegionsRegions) {
    const std::unique_ptr<Graph> graphp = buildGraph(logicRegionsRegions);
    if (dumpGraphLevel() >= 6) graphp->dumpDotFilePrefixed("sched-replicate");
    
    // 传播驱动区域标志
    for (V3GraphVertex& vtx : graphp->vertices()) {
        propagateDrivingRegions(vtx.as<SchedReplicateVertex>());
    }
    
    if (dumpGraphLevel() >= 6) graphp->dumpDotFilePrefixed("sched-replicate-propagated");
    
    // 复制必要逻辑
    return replicate(graphp.get());
}
```

- **多线程意义**：通过复制组合逻辑，不同区域可以独立执行而无需同步。NBA 区域的并行执行不依赖于其他区域正在执行的同一段组合逻辑。

---

## 文件 6: V3SchedTiming.cpp — 时序集成

### 文件路径与行号

`src/V3SchedTiming.cpp`（约 300 行）

### 关键类/数据结构

#### `AwaitVisitor`（第 110 行）

```cpp
class AwaitVisitor final : public VNVisitor {
    bool m_inProcess = false;
    bool m_gatherVars = false;
    AstScope* const m_scopeTopp;
    LogicByScope& m_lbs;
    AstNodeStmt*& m_postUpdatesr;
    std::map<const AstVarScope*, std::set<AstSenTree*>>& m_externalDomains;
    std::set<AstSenTree*> m_processDomains;
    std::vector<AstVarScope*> m_writtenBySuspendable;
```

### 关键函数分析

#### `TimingKit::remapDomains()`（第 40 行）

```cpp
std::map<const AstVarScope*, std::vector<AstSenTree*>>
TimingKit::remapDomains(const std::unordered_map<const AstSenTree*, AstSenTree*>& trigMap) const {
    std::map<const AstVarScope*, std::vector<AstSenTree*>> remappedDomainMap;
    for (const auto& vscpDomains : m_externalDomains) {
        const AstVarScope* const vscp = vscpDomains.first;
        const auto& domains = vscpDomains.second;
        auto& remappedDomains = remappedDomainMap[vscp];
        remappedDomains.reserve(domains.size());
        for (AstSenTree* const domainp : domains) {
            remappedDomains.push_back(trigMap.at(domainp));  // 映射到触发器 SenTree
        }
    }
    return remappedDomainMap;
}
```

- 将时序逻辑的外部敏感度域重新映射到触发向量索引。

#### `TimingKit::createResume()`（第 55 行）

```cpp
AstCCall* TimingKit::createResume(AstNetlist* const netlistp) {
    if (!m_resumeFuncp) {
        // 创建全局恢复函数 _timing_resume
        m_resumeFuncp = new AstCFunc{netlistp->fileline(), "_timing_resume", scopeTopp, ""};
        m_resumeFuncp->dontCombine(true);
        m_resumeFuncp->isLoose(true);
        m_resumeFuncp->isConst(false);
        m_resumeFuncp->declPrivate(true);
        
        // 将所有时序恢复操作放入此函数
        // 将时间延迟恢复放在最后
        // ...
    }
    AstCCall* const callp = new AstCCall{m_resumeFuncp->fileline(), m_resumeFuncp};
    callp->dtypeSetVoid();
    return callp;
}
```

#### `TimingKit::createReady()`（第 105 行）

```cpp
AstCCall* TimingKit::createReady(AstNetlist* const netlistp) {
    if (!m_readyFuncp) {
        // 只为 trigger schedulers 创建 _timing_ready 函数
        for (auto& p : m_lbs) {
            AstVarScope* const schedulerp = ...;
            if (!schedulerp->dtypep()->basicp()->isTriggerScheduler()) continue;
            
            // 创建 _timing_ready 函数
            m_readyFuncp = new AstCFunc{netlistp->fileline(), "_timing_ready", scopeTopp, ""};
            
            // 为每个 scheduler 创建 AstIf，敏感度为挂起触发器
            AstIf* const ifp = V3Sched::util::createIfFromSenTree(senTreep);
            m_readyFuncp->addStmtsp(ifp);
            
            // 调用 SCHED_READY 标记准备恢复
            AstCMethodHard* const callp = new AstCMethodHard{...};
            callp->method(VCMethod::SCHED_READY);
            ifp->addThensp(callp->makeStmt());
        }
    }
}
```

#### `prepareTiming()` — 主入口（第 200 行）

```cpp
TimingKit prepareTiming(AstNetlist* const netlistp) {
    if (!v3Global.usesTiming()) return {};  // 无时序，直接返回空
    
    LogicByScope lbs;
    AstNodeStmt* postUpdates = nullptr;
    std::map<const AstVarScope*, std::set<AstSenTree*>> externalDomains;
    { AwaitVisitor{netlistp, lbs, postUpdates, externalDomains}; }
    return {std::move(lbs), postUpdates, std::move(externalDomains)};
}
```

- **多线程影响**：时序逻辑（如 `always @(posedge clk) begin ... @(negedge rst); ... end`）引入可挂起进程。这些进程在 eval 循环中恢复，但 V3SchedTiming 本身标记为 `VL_MT_DISABLED`，在编译期处理。

#### `transformForks()` — Fork 转换（第 250 行）

```cpp
void transformForks(AstNetlist* const netlistp) {
    if (!v3Global.usesTiming()) return;
    { TransformForksVisitor{netlistp}; }
}
```

- 将 fork/join 子语句转换为独立函数（通常是 coroutine）。
- 每个 begin 块变成独立的 `VlCoroutine` 函数。

---

## 文件 7: V3SchedTrigger.cpp — 触发器系统

### 文件路径与行号

`src/V3SchedTrigger.cpp`（约 520 行）

### 关键函数分析

#### `TriggerKit::create()` — 创建触发器工具包（第 350 行起）

```cpp
TriggerKit TriggerKit::create(AstNetlist* netlistp, AstCFunc* const initFuncp,
                              SenExprBuilder& senExprBuilder,
                              const std::vector<const AstSenTree*>& preTreeps,
                              const std::vector<const AstSenTree*>& senTreeps,
                              const string& name, const ExtraTriggers& extraTriggers,
                              bool slow, bool useAcc) {
    // 1. 收集所有唯一的 SenItems
    std::vector<const AstSenItem*> senItemps;
    std::unordered_map<VNRef<const AstSenItem>, size_t> senItem2TrigIdx;
    
    // 先处理 Pre triggers（放在向量开头）
    for (const AstSenTree* const senTreep : preTreeps) {
        for (const AstSenItem *itemp = senTreep->sensesp(); itemp; itemp = nextp) {
            const auto pair = senItem2TrigIdx.emplace(*itemp, senItemps.size());
            if (pair.second) senItemps.push_back(itemp);
        }
    }
    const uint32_t nPreSenItems = senItemps.size();
    const uint32_t nPreTriggers = vlstd::roundUpToMultipleOf<WORD_SIZE>(senItemps.size());
    const uint32_t nPreWords = nPreTriggers / WORD_SIZE;
    
    // 处理剩余 SenItems
    for (const AstSenTree* const senTreep : senTreeps) {
        for (const AstSenItem *itemp = senTreep->sensesp(); itemp; itemp = nextp) {
            const auto pair = senItem2TrigIdx.emplace(*itemp, senItemps.size());
            if (pair.second) senItemps.push_back(itemp);
        }
    }
    const uint32_t nSenseTriggers = vlstd::roundUpToMultipleOf<WORD_SIZE>(senItemps.size());
    const uint32_t nSenseWords = nSenseTriggers / WORD_SIZE;
    
    // 分配 Extra triggers
    const uint32_t nExtraTriggers = vlstd::roundUpToMultipleOf<WORD_SIZE>(extraTriggers.size());
    const uint32_t nExtraWords = nExtraTriggers / WORD_SIZE;
    
    // 构造 TriggerKit
    TriggerKit kit{name, slow, nSenseWords, nExtraWords, nPreWords, senItem2TrigIdx, useAcc};
    
    // ... 构建 comp 函数和 dump 函数
}
```

- **触发器对齐**：所有触发器数量对齐到 64 位的倍数，便于按字处理。

#### `TriggerKit::createSenTrigVecAssignment()` — 触发向量赋值（第 330 行）

```cpp
AstAssign* TriggerKit::createSenTrigVecAssignment(AstVarScope* const target,
                                                  std::vector<AstNodeExpr*>& trigps) {
    // 按字分配触发器，使用平衡二叉树式连接（减少 AstConcat 深度）
    for (size_t i = 0; i < trigps.size(); i += WORD_SIZE) {
        for (uint32_t level = 0; level < WORD_SIZE_LOG2; ++level) {
            const uint32_t stride = 1 << level;
            for (uint32_t j = 0; j < WORD_SIZE; j += 2 * stride) {
                trigps[i + j] = new AstConcat{trigps[i + j]->fileline(), 
                                              trigps[i + j + stride], trigps[i + j]};
                trigps[i + j + stride] = nullptr;
            }
        }
        
        // 将整字设置到触发向量
        const int wordIndex = static_cast<int>(i / WORD_SIZE);
        AstArraySel* const aselp = new AstArraySel{...};
        trigStmtsp = AstNode::addNext(trigStmtsp, new AstAssign{flp, aselp, trigps[i]});
    }
    return trigStmtsp;
}
```

- **平衡二叉树连接**：64 个触发位通过 log2(64)=6 层 AstConcat 连接，避免过深的 AST 树。

#### `TriggerKit::createAnySetFunc()` — 检测是否有触发器被设置（第 120 行）

```cpp
AstCFunc* TriggerKit::createAnySetFunc(AstUnpackArrayDType* const dtypep) const {
    AstCFunc* const funcp = util::makeSubFunction(netlistp, name, m_slow);
    funcp->isStatic(true);
    funcp->rtnType("bool");
    
    AstVarScope* const iVscp = newArgument(funcp, dtypep, "in", VDirection::CONSTREF);
    AstVarScope* const nVscp = newLocal(funcp, u32DTypep, "n");
    
    // 循环遍历所有字
    AstLoop* const loopp = new AstLoop{flp};
    funcp->addStmtsp(util::setVar(nVscp, 0));
    funcp->addStmtsp(loopp);
    funcp->addStmtsp(new AstCReturn{flp, new AstConst{flp, AstConst::BitFalse{}}});
    
    // 循环体：如果任何字非零，返回 true
    const uint32_t nWords = dtypep->elementsConst();
    AstNodeExpr* const condp = new AstArraySel{flp, rd(iVscp), rd(nVscp)};
    AstNodeStmt* const thenp = new AstCReturn{flp, new AstConst{flp, AstConst::BitTrue{}}};
    AstNodeExpr* const limp = new AstConst{..., nWords};
    loopp->addStmtsp(new AstIf{flp, condp, thenp});
    loopp->addStmtsp(util::incrementVar(nVscp));
    loopp->addStmtsp(new AstLoopTest{flp, loopp, new AstLt{flp, rd(nVscp), limp}});
    
    return funcp;
}
```

- **多线程意义**：`newAnySetCall()` 是 EvalLoop 中判断是否需要执行区域工作的关键函数。在运行时，该函数遍历所有触发字，检查是否有任何位被设置。这是一个**O(nWords)** 操作，虽然复杂度不高，但在高频调用的仿真循环中可能成为瓶颈。

#### `TriggerKit::createOrIntoFunc()` — 触发器 OR 操作（第 180 行）

```cpp
AstCFunc* TriggerKit::createOrIntoFunc(AstUnpackArrayDType* const oDtypep,
                                       AstUnpackArrayDType* const iDtypep) const {
    AstCFunc* const funcp = util::makeSubFunction(netlistp, name, m_slow);
    funcp->isStatic(true);
    
    AstVarScope* const oVscp = newArgument(funcp, oDtypep, "out", VDirection::INOUT);
    AstVarScope* const iVscp = newArgument(funcp, iDtypep, "in", VDirection::CONSTREF);
    AstVarScope* const nVscp = newLocal(funcp, u32DTypep, "n");
    
    AstLoop* const loopp = new AstLoop{flp};
    funcp->addStmtsp(util::setVar(nVscp, 0));
    funcp->addStmtsp(loopp);
    
    // out[n] = out[n] | in[n]
    AstNodeExpr* const lhsp = new AstArraySel{flp, wr(oVscp), rd(nVscp)};
    AstNodeExpr* const oWordp = new AstArraySel{flp, rd(oVscp), rd(nVscp)};
    AstNodeExpr* const iWordp = new AstArraySel{flp, rd(iVscp), rd(nVscp)};
    AstNodeExpr* const rhsp = new AstOr{flp, oWordp, iWordp};
    loopp->addStmtsp(new AstAssign{flp, lhsp, rhsp});
    loopp->addStmtsp(util::incrementVar(nVscp));
    loopp->addStmtsp(new AstLoopTest{flp, loopp, new AstLte{flp, rd(nVscp), limp}});
    
    return funcp;
}
```

- **多线程意义**：`newOrIntoCall()` 用于在 act 和 nba 区域之间传递触发器状态。例如，`nbaKit.m_vscp |= actKit.m_vscp` 将 act 的触发状态传播到 nba。这是区域间同步的关键机制。

#### `newTriggerSenTree()` — 创建触发器 SenTree（第 270 行）

```cpp
AstSenTree* TriggerKit::newTriggerSenTree(AstVarScope* const vscp,
                                          const std::vector<uint32_t>& indices) const {
    AstSenTree* const senTreep = new AstSenTree{flp, nullptr};
    for (const uint32_t index : indices) {
        const uint32_t wordIndex = index / WORD_SIZE;
        const uint32_t bitIndex = index % WORD_SIZE;
        AstVarRef* const refp = new AstVarRef{flp, vscp, VAccess::READ};
        AstNodeExpr* const aselp = new AstArraySel{flp, refp, static_cast<int>(wordIndex)};
        AstConst* const maskp = new AstConst{..., 0};
        maskp->num().setBit(bitIndex, '1');
        AstNodeExpr* const termp = new AstAnd{flp, maskp, aselp};
        senTreep->addSensesp(new AstSenItem{flp, VEdgeType::ET_TRUE, termp});
    }
    return senTreep;
}
```

- 将触发器索引转换为 AstSenTree，用于 `V3Order` 排序。
- 每个触发位对应一个 `AstSenItem`（`ET_TRUE` 边类型），表示当对应位为 1 时触发。

#### `AwaitBeforeTrigVisitor` — 触发前优化（第 420 行起）

```cpp
class AwaitBeforeTrigVisitor final : public VNVisitor {
    // 在 CAwait 之前生成 before-trigger 函数
    // 这些函数在 await 之前检查是否有触发器被触发，并标记 scheduler 为 ready
    
    void visit(AstCAwait* const nodep) override {
        if (nodep->user1SetOnce()) return;
        
        if (const AstCMethodHard* const cMethodHardp = VN_CAST(nodep->exprp(), CMethodHard)) {
            if (cMethodHardp->method() == VCMethod::SCHED_TRIGGER) {
                AstCCall* const beforeTrigp = getBeforeTriggerStmt(nodep->sentreep());
                nodep->addHereThisAsNext(beforeTrigp->makeStmt());
                m_senTreeToSched.emplace_back(nodep->sentreep(), cMethodHardp->fromp());
            }
        }
        nodep->clearSentreep();  // 清除 SenTree（后续会被删除）
        iterate(nodep);
    }
```

- 为每个 CAwait 创建 before-trigger 函数，在挂起等待前检查触发状态。
- 使用 `m_trigKit.vscAccp()`（触发累加器）累加已处理的触发器。

---

## 多线程相关实现细节总结

### 1. 编译期 vs 运行时多线程

| 层面 | 状态 | 说明 |
|------|------|------|
| V3Sched 文件组 | `VL_MT_DISABLED` | 编译期单线程代码 |
| 生成的 `_eval` | 运行时多线程 | NBA 区域可调用 mtasks |
| 触发向量操作 | 运行时单线程 | 触发检测/清除/传播在单线程循环中 |

### 2. 多线程启用条件

```cpp
// V3Sched.cpp 第 476 行
name == "nba" && v3Global.opt.mtasks()
```

- 仅当调度 **NBA** 区域且用户启用 `--threads` 或 `--mtasks` 时才多线程。
- Act、Ico、Obs、React 区域**永远单线程**。

### 3. #0 延迟的致命影响

```cpp
// V3SchedPartition.cpp 第 220 行
if (v3Global.usesZeroDelay() && !VN_IS(lvtxp->logicp(), AlwaysPost)) toAct = true;
```

- 使用 `#0` 的设计几乎**无法从多线程获益**，因为所有逻辑进入 act 区域。

### 4. 触发向量位操作

- 触发向量用 **64 位字数组** 存储，位索引对应 SenItem。
- `anySet` 遍历所有字检查是否有触发。
- `orInto` 将一组触发位传播到另一组。
- `clear` 清除触发位。

### 5. 触发累加器（useAcc）

```cpp
// V3Sched.h 第 180 行
AstVarScope* m_vscAccp = nullptr;  // 触发累加器
```

- 在 act 区域多轮迭代中累加触发状态。
- 确保在 `beforeTrigVisitor` 中不会丢失触发事件。

---

## 对 RTL 仿真器多线程化的启示

### 启示 1：不是所有区域都适合并行化

Verilator 的实验表明：
- **Act 区域不适合多线程**：时钟驱动逻辑有大量数据依赖，线程同步开销超过收益。
- **NBA 区域适合多线程**：非阻塞赋值通常是独立的状态更新，可以并行执行。

**建议**：对于自定义 RTL 仿真器，应优先对**状态更新阶段**（类似 NBA）进行并行化，而非**组合逻辑评估**（类似 Act）。

### 启示 2：触发向量是轻量调度机制

Verilator 使用**位向量触发器**而非事件队列来调度逻辑：
- 每个时钟/信号变化对应一个触发位。
- 区域执行前检查是否有任何位被设置（`anySet`）。
- 位操作可以高度优化（64 位字操作）。

**建议**：在自定义仿真器中，考虑使用位向量触发器而非事件队列，减少调度开销。

### 启示 3：组合循环必须打破才能并行化

V3SchedAcyclic.cpp 的算法：
- 构建组合逻辑依赖图。
- 使用 SCC 检测找到循环。
- 将循环边转换为 hybrid 逻辑（带显式敏感度）。

**建议**：任何基于 DAG 的并行调度器都必须先处理循环依赖。如果不打破循环，就无法进行拓扑排序和并行分区。

### 启示 4：逻辑复制减少同步

V3SchedReplicate.cpp 复制组合逻辑到多个区域：
- 允许不同区域独立执行同一段逻辑。
- 避免运行时区域间的同步需求。

**建议**：在内存允许的情况下，复制共享逻辑到多个执行上下文，以空间换时间，减少同步开销。

### 启示 5：分区质量决定并行度

V3SchedPartition.cpp 的分区逻辑：
- 如果设计使用 `#0` 延迟，分区失效，所有逻辑进入 act 区域。
- 顶层输入变化影响 ico 区域，但不影响 nba 区域的并行度。

**建议**：仿真器的并行度受限于**可分区到非时钟区域的逻辑量**。设计约束（如避免 `#0`）直接影响多线程性能。

### 启示 6：触发器传播机制

V3Sched.cpp 的 `createEval()` 中：
```cpp
// act 准备：将 act 触发器传播到 nba 触发器
stmtsp = AstNode::addNext(stmtsp, trigKit.newOrIntoCall(nbaKit.m_vscp, actKit.m_vscp));
// nba 工作：将 nba 触发器传播到 obs 触发器
workp = trigKit.newOrIntoCall(obsKit.m_vscp, nbaKit.m_vscp);
```

- 区域间的触发器传播使用 OR 操作，确保下游区域知道上游有工作待执行。

**建议**：多级流水线式的仿真器需要明确的触发传播机制，确保各阶段之间的执行依赖被正确传递。

---

## 相关链接

- [V3Sched.h](https://github.com/verilator/verilator/blob/master/src/V3Sched.h)
- [V3Sched.cpp](https://github.com/verilator/verilator/blob/master/src/V3Sched.cpp)
- [V3SchedAcyclic.cpp](https://github.com/verilator/verilator/blob/master/src/V3SchedAcyclic.cpp)
- [V3SchedPartition.cpp](https://github.com/verilator/verilator/blob/master/src/V3SchedPartition.cpp)
- [V3SchedReplicate.cpp](https://github.com/verilator/verilator/blob/master/src/V3SchedReplicate.cpp)
- [V3SchedTiming.cpp](https://github.com/verilator/verilator/blob/master/src/V3SchedTiming.cpp)
- [V3SchedTrigger.cpp](https://github.com/verilator/verilator/blob/master/src/V3SchedTrigger.cpp)
- [Verilator Internals Documentation](https://verilator.org/guide/internals.html)

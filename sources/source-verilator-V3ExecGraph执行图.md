---
title: "V3ExecGraph 执行图"
source_url: "https://github.com/verilator/verilator/tree/master/src/V3ExecGraph.cpp"
source_type: "github-code"
author: "Verilator Team"
date: ""
tags: ["verilator", "multithreading", "exec-graph", "mtask", "thread-schedule", "static-scheduling", "packing"]
keywords: ["ExecMTask", "ThreadSchedule", "PackThreads", "MTask", "cross-thread dependency", "sandbagging", "critical path", "hierarchical thread"]
capture_date: "2026-07-04"
---

# V3ExecGraph 执行图：MTask 静态调度与多线程代码生成

## 来源

- **文件路径**: `src/V3ExecGraph.h`, `src/V3ExecGraph.cpp`
- **仓库**: verilator/verilator
- **类型**: github-code
- **作者**: Verilator Team
- **捕获日期**: 2026-07-04

## 摘要

V3ExecGraph 是 Verilator 多线程仿真后端的核心模块，负责将依赖图（MTask Graph）**静态调度**到固定数量的线程上，并生成对应的 C++ 多线程执行代码。它实现了：

1. **ExecMTask** 类 — 表示可并行执行的最小任务单元（继承自 V3GraphVertex）
2. **ThreadSchedule** 类 — 记录每个 MTask 被分配到哪个线程、何时开始/结束、同线程上的后继任务
3. **PackThreads** 类 — 核心静态调度算法，采用贪心策略将 MTask 打包到线程，引入 **Sandbag（沙袋）** 机制补偿跨线程依赖的时序不确定性
4. **代码生成** — 将调度结果转化为 C++ 线程池调用、MTask 状态变量（`__Vm_mtaskstate_*`）和同步原语

## 文件概述

| 文件 | 行数 | 作用 |
|------|------|------|
| `V3ExecGraph.h` | ~70 | 定义 `ExecMTask` 类和 `V3ExecGraph` 命名空间接口 |
| `V3ExecGraph.cpp` | ~700 | 实现静态调度算法 (`PackThreads::pack`)、成本计算、代码生成 |

---

## 关键类与数据结构

### 1. ExecMTask（V3ExecGraph.h:30-60）

```cpp
class ExecMTask final : public V3GraphVertex {
    VL_RTTI_IMPL(ExecMTask, V3GraphVertex)
private:
    const uint32_t m_id;                           // 唯一 ID
    static std::atomic<uint32_t> s_nextId;          // 原子 ID 生成器
    AstCFunc* const m_funcp;                        // 包含 MTask 函数体的 C 函数
    const std::string m_hashName;                   // 函数体哈希，用于性能分析
    uint32_t m_priority = 0;                      // 关键路径优先级（从当前到终点的代价）
    uint32_t m_cost = 0;                            // 预测执行时间（抽象单位）
    uint64_t m_predictStart = 0;                    // 预测开始时间
    int m_threads = 1;                              // 此 MTask 使用的线程数（>1 为宽任务）
```

**多线程相关细节**：
- `s_nextId` 是 `std::atomic<uint32_t>`，确保多线程编译时全局唯一 ID 分配安全（但构造时仍在单线程上下文 `VL_MT_DISABLED`）
- `m_priority` 和 `m_cost` 用于调度器的优先级启发式：优先执行关键路径上的任务
- `m_threads` 支持 **宽任务（wide task）**：某些 MTask 需要多个线程同时执行（如层次化模块调用），这引入了 **多线程调度复杂度**

### 2. ThreadSchedule（V3ExecGraph.cpp:52-240）

```cpp
class ThreadSchedule final {
    uint32_t m_id;
    static uint32_t s_nextId;
    std::unordered_set<const ExecMTask*> mtasks;    // 本调度包含的所有 MTask
    uint32_t m_endTime = 0;                         // 最晚结束时间

    struct MTaskState final {
        uint32_t completionTime = 0;                  // 估计完成时间
        uint32_t threadId = UNASSIGNED;               // 分配到的线程 ID
        const ExecMTask* nextp = nullptr;           // 同线程上的下一个 MTask
    };
    static std::unordered_map<const ExecMTask*, MTaskState> s_mtaskState;  // 全局 MTask 状态

    std::vector<std::vector<const ExecMTask*>> m_threads;  // threadId -> MTask 序列
```

**多线程相关细节**：
- `s_mtaskState` 是**全局静态变量**，记录每个 MTask 的调度状态（完成时间、线程分配、后继指针）
- `UNASSIGNED = 0xffffffff` 表示未分配状态
- `crossThreadDependencies()` 计算一个 MTask 有多少**入边来自其他线程** — 这决定了运行时是否需要等待上游完成（即是否需要阻塞）

### 3. PackThreads（V3ExecGraph.cpp:250-430）

核心静态调度器，采用**贪心列表调度（List Scheduling）**策略：

```cpp
class PackThreads final {
    const uint32_t m_nThreads;          // 普通线程数
    const uint32_t m_nHierThreads;      // 层次化线程数
    const uint32_t m_sandbagNumerator;  // 沙袋分子（默认 30）
    const uint32_t m_sandbagDenom;      // 沙袋分母（默认 100）
```

---

## 关键函数分析

### 1. `PackThreads::pack()` — 静态调度核心算法（V3ExecGraph.cpp:280-380）

```cpp
std::vector<ThreadSchedule> pack(V3Graph& mtaskGraph) {
    std::vector<ThreadSchedule> result;
    result.emplace_back(ThreadSchedule{m_nThreads});
    
    // 支持宽任务（threads > 1）的调度模式切换
    enum class SchedulingMode : uint8_t {
        SCHEDULING,            // 普通任务调度
        WIDE_TASK_DISCOVERED,  // 发现宽任务，准备切换
        WIDE_TASK_SCHEDULING   // 宽任务调度模式
    };
    SchedulingMode mode = SchedulingMode::SCHEDULING;
    
    std::vector<uint32_t> busyUntil(std::max(m_nThreads, m_nHierThreads), 0);
    std::set<ExecMTask*, MTaskCmp> readyMTasks;
```

**调度算法流程**：

1. **初始化就绪列表**：遍历所有 MTask，没有入边（或入边已调度）的进入 `readyMTasks`
2. **双重循环**：对每个线程，对每个就绪 MTask，计算其**最早可开始时间**（考虑本线程空闲时间 + 所有前驱在其他线程上的完成时间）
3. **选择最优**：选择 `timeBegin` 最小的 (MTask, threadId) 组合；如果相同，选择 `priority` 更高的（关键路径优先）
4. **处理宽任务**：如果当前有宽任务（`threads > 1`），创建**独立的 ThreadSchedule**，避免线程索引冲突
5. **更新就绪列表**：将已调度的 MTask 的后继加入就绪列表

**关键启发式**：
- 优先调度关键路径上的任务（高 `priority`），这是标准列表调度的核心策略
- 宽任务使用独立的调度表，防止与单线程任务混用线程池索引

### 2. `completionTime()` — 沙袋机制（Sandbagging，V3ExecGraph.cpp:260-290）

```cpp
uint32_t completionTime(const ThreadSchedule& schedule, const ExecMTask* mtaskp,
                        uint32_t threadId) {
    if (threadId == state.threadId) {
        return state.completionTime;  // 同线程：无开销
    }
    
    // 跨线程时增加 "padding"
    uint32_t sandbaggedEndTime
        = state.completionTime + (m_sandbagNumerator * mtaskp->cost()) / m_sandbagDenom;
    
    // 防止优先级反转：如果 A 在 thread 0 上完成后 B 开始，
    // 不能让 thread 1 认为 A 在 B 开始之后才完成
    if (state.nextp) {
        const uint32_t successorEndTime = completionTime(schedule, state.nextp, state.threadId);
        if ((sandbaggedEndTime >= successorEndTime) && (successorEndTime > 1)) {
            sandbaggedEndTime = successorEndTime - 1;
        }
    }
    return sandbaggedEndTime;
}
```

**多线程设计洞察**：

这是整个模块**最精妙的多线程策略**：
- **问题**：MTask 的执行时间预测误差很大（`±60%` 典型），如果乐观地按预测时间调度，跨线程依赖会导致频繁的阻塞等待
- **解法**：当线程 A 查看线程 B 上的任务完成时间时，额外增加 30% 的 "沙袋" 时间。这让调度器在跨线程依赖处**留出缓冲**，减少实际运行时的阻塞概率
- **优先级反转保护**：确保前驱任务的沙袋时间不会晚于后继任务的开始时间，否则调度器可能做出错误决策

### 3. `crossThreadDependencies()` — 跨线程依赖计数（V3ExecGraph.cpp:210-220）

```cpp
uint32_t crossThreadDependencies(const ExecMTask* mtaskp) const {
    const uint32_t thisThreadId = threadId(mtaskp);
    uint32_t result = 0;
    for (const V3GraphEdge& edge : mtaskp->inEdges()) {
        const ExecMTask* const prevp = edge.fromp()->as<ExecMTask>();
        if (threadId(prevp) != thisThreadId && contains(prevp)) ++result;
    }
    return result;
}
```

**作用**：决定运行时一个 MTask 是否需要**等待上游**。如果 `crossThreadDependencies > 0`，生成的代码会插入 `waitUntilUpstreamDone(even_cycle)` 调用。

### 4. `addMTaskToFunction()` — 为 MTask 生成同步代码（V3ExecGraph.cpp:500-560）

```cpp
void addMTaskToFunction(const ThreadSchedule& schedule, const uint32_t threadId,
                        AstCFunc* funcp, const ExecMTask* mtaskp) {
    if (const uint32_t nDependencies = schedule.crossThreadDependencies(mtaskp)) {
        // 创建 MTask 状态变量并等待上游完成
        const string name = "__Vm_mtaskstate_" + cvtToStr(mtaskp->id());
        AstVar* const varp = new AstVar{fl, VVarType::MODULETEMP, name, s_mtaskStateDtypep};
        varp->valuep(new AstConst{fl, nDependencies});  // 初始值为依赖数
        
        addCStmt("vlSelf->" + name + ".waitUntilUpstreamDone(even_cycle);");
    }
    
    // 调用 MTask 函数体
    AstCCall* const callp = new AstCCall{fl, mtaskp->funcp()};
    funcp->addStmtsp(callp->makeStmt());
    
    // 通知下游 MTask
    for (const V3GraphEdge& edge : mtaskp->outEdges()) {
        const ExecMTask* const nextp = edge.top()->as<ExecMTask>();
        if (schedule.threadId(nextp) != threadId && schedule.contains(nextp)) {
            addCStmt("vlSelf->__Vm_mtaskstate_" + cvtToStr(nextp->id())
                     + ".signalUpstreamDone(even_cycle);");
        }
    }
}
```

**多线程同步机制**：
- **MTaskState 变量**：每个有跨线程依赖的 MTask 都有一个计数器变量（`__Vm_mtaskstate_*`），类型为 `VBasicDTypeKwd::MTASKSTATE`
- **等待上游**：`waitUntilUpstreamDone(even_cycle)` — 这是一个**基于事件/周期的同步原语**，确保所有跨线程的上游 MTask 完成后才开始执行
- **信号下游**：`signalUpstreamDone(even_cycle)` — 每完成一个上游依赖，下游计数器减 1（或类似机制），当计数器归零时触发继续执行
- **even_cycle**：使用**双缓冲（Even/Odd Cycle）**机制避免周期之间的状态污染，即 MTask 状态变量按周期翻转，防止同一周期内的信号冲突

### 5. `createThreadFunctions()` — 线程入口函数生成（V3ExecGraph.cpp:560-610）

```cpp
const std::vector<AstCFunc*> createThreadFunctions(const ThreadSchedule& schedule, ...) {
    for (const std::vector<const ExecMTask*>& thread : schedule.m_threads) {
        if (thread.empty()) continue;
        const uint32_t threadId = schedule.threadId(thread.front());
        const string name{"__Vthread__" + tag + "__s" + cvtToStr(schedule.id()) + "__t"
                          + cvtToStr(threadId)};
        AstCFunc* const funcp = new AstCFunc{fl, name, nullptr, "void"};
        funcp->isStatic(true);
        funcp->entryPoint(true);  // 标记为线程入口点
        funcp->argTypes("void* voidSelf, bool even_cycle");
        
        // 调用本线程上的每个 MTask
        for (const ExecMTask* const mtaskp : thread) {
            addMTaskToFunction(schedule, threadId, funcp, mtaskp);
        }
        
        // 通知 "final" 虚拟 MTask 本线程已完成
        funcp->addStmtsp(new AstCStmt{fl, "vlSelf->__Vm_mtaskstate_final__..."});
    }
}
```

**设计特点**：
- 每个线程生成一个**静态函数**作为入口点，参数为 `voidSelf`（模块指针）和 `even_cycle`（周期奇偶标志）
- 线程按顺序执行分配给它的 MTask 链，不需要运行时动态调度
- 最后一个 MTask 通过 `signalUpstreamDone` 通知一个虚拟的 "final" 状态变量，主线程等待此变量完成同步

### 6. `addThreadStartToExecGraph()` — 启动线程池（V3ExecGraph.cpp:620-680）

```cpp
void addThreadStartToExecGraph(AstExecGraph* const execGraphp,
                               const std::vector<AstCFunc*>& funcps, uint32_t scheduleId) {
    const uint32_t last = funcps.size() - 1;
    for (AstCFunc* const funcp : funcps) {
        if (i != last) {
            // 前 N-1 个函数提交到线程池
            cstmtp->add("vlSymsp->__Vm_threadPoolp->workerp(...)->addTask(");
            cstmtp->add(new AstAddrOfCFunc{fl, funcp});
            cstmtp->add(", vlSelf, vlSymsp->__Vm_even_cycle__" + tag + ");");
        } else {
            // 最后一个在主线程执行（避免空转）
            AstCCall* const callp = new AstCCall{fl, funcp};
            callp->argTypes("vlSelf, vlSymsp->__Vm_even_cycle__" + tag);
            execGraphp->addStmtsp(callp->makeStmt());
        }
        ++i;
    }
    
    // 主线程等待所有线程完成
    addCStmt("vlSelf->__Vm_mtaskstate_final__" + std::to_string(scheduleId) + tag
             + ".waitUntilUpstreamDone(vlSymsp->__Vm_even_cycle__" + tag + ");");
}
```

**多线程执行模型**：
- 使用 `VerilatedThreadPool`（`__Vm_threadPoolp`）管理线程池
- 前 `N-1` 个线程函数提交到线程池，**最后一个在主线程执行**，避免主线程空转
- 主线程通过 `waitUntilUpstreamDone` 等待所有线程完成，实现**barrier 同步**
- 层次化仿真（`hierBlocks`）时支持动态 worker 索引分配/释放

### 7. `processMTaskBodies()` — MTask 函数体增强（V3ExecGraph.cpp:690-720）

```cpp
void processMTaskBodies(AstExecGraph* const execGraphp) {
    for (V3GraphVertex* const vtxp : execGraphp->depGraphp()->vertices().unlinkable()) {
        ExecMTask* const mtaskp = vtxp->as<ExecMTask>();
        // ...
        addCStmt("Verilated::mtaskId(" + std::to_string(mtaskp->id()) + ");");
        funcp->addStmtsp(stmtsp);  // 原始函数体
        addCStmt("Verilated::endOfThreadMTask(vlSymsp->__Vm_evalMsgQp);");
    }
}
```

**功能**：
- 设置当前 MTask ID（`Verilated::mtaskId`），用于调试/性能分析
- 在 MTask 结束时刷新消息队列（`endOfThreadMTask`），确保跨线程的 `$display` 等输出有序

### 8. `implement()` — 主入口（V3ExecGraph.cpp:730-780）

```cpp
void implement(AstNetlist* netlistp) {
    for (AstExecGraph* const execGraphp : execGraphps) {
        removeEmptyMTasks(execGraphp->depGraphp());
        fillinCosts(execGraphp->depGraphp());     // 重新计算成本
        finalizeCosts(execGraphp->depGraphp());    // 计算关键路径优先级
        
        const std::vector<ThreadSchedule> packed = PackThreads::apply(*execGraphp->depGraphp());
        processMTaskBodies(execGraphp);
        
        for (const ThreadSchedule& schedule : packed) {
            implementExecGraph(execGraphp, schedule);  // 生成多线程代码
        }
    }
}
```

**流程**：
1. 删除空 MTask
2. 基于指令计数和性能分析数据重新计算成本
3. 计算关键路径优先级（反向图遍历）
4. 静态调度（`PackThreads::apply`）
5. 生成线程函数和同步代码

---

## 同步机制分析

| 同步原语 | 位置 | 作用 |
|---------|------|------|
| `std::atomic<uint32_t> s_nextId` | V3ExecGraph.h | MTask ID 原子分配 |
| `__Vm_mtaskstate_*` 变量 | 生成代码 | 每个有跨线程依赖的 MTask 的计数器 |
| `waitUntilUpstreamDone(even_cycle)` | 生成代码 | 等待所有跨线程上游完成 |
| `signalUpstreamDone(even_cycle)` | 生成代码 | 通知下游一个上游已完成 |
| `__Vm_mtaskstate_final__*` | 生成代码 | 虚拟终点状态，用于 barrier 同步 |
| `even_cycle` / `!even_cycle` | 生成代码 | 双缓冲周期翻转，避免状态冲突 |
| `Verilated::mtaskId()` | 生成代码 | 设置当前 MTask ID（用于调试/性能分析） |
| `endOfThreadMTask()` | 生成代码 | 刷新线程消息队列 |

**注意**：没有显式锁（mutex）！同步完全依赖 **MTaskState 计数器 + 等待/通知机制**。这是高性能 RTL 仿真的关键设计选择。

---

## 对 RTL 仿真器多线程化的启示

### 1. 静态调度 vs 动态调度

Verilator 采用**编译期静态调度**（`PackThreads`）而非运行时动态调度。这意味着：
- **优点**：运行时零开销（无任务队列竞争、无动态调度器）
- **缺点**：需要精确预测任务执行时间，且对负载不均衡敏感
- **启示**：对于 RTL 仿真这种**任务图在编译期完全已知**的场景，静态调度是更优选择

### 2. Sandbag（沙袋）机制解决时序不确定性

实际调度中，任务执行时间预测误差可达 `±60%`。`completionTime()` 的 30% padding 是一个**工程智慧**：
- 跨线程依赖处留出缓冲，减少运行时阻塞
- 同时避免过度保守导致利用率下降（通过优先级反转保护）
- **启示**：RTL 仿真器的任务调度器必须**容忍预测误差**，不能假设预测完全准确

### 3. 无锁同步设计

MTask 间同步使用**计数器 + 等待/通知**（类似 semaphore），没有锁：
- 每个有跨线程依赖的 MTask 有一个计数器，初值为依赖数
- 每个上游完成后 `signalUpstreamDone`，计数器递减
- 当计数器归零时，MTask 可以开始执行
- **启示**：避免锁竞争是多线程 RTL 仿真器性能的关键；计数器/信号量是更合适的抽象

### 4. 宽任务（Wide Task）的隔离调度

对于需要多个线程的 MTask（如层次化模块），Verilator 创建**独立的 ThreadSchedule**：
- 防止线程索引冲突
- 简化调度逻辑
- **启示**：当任务具有**非均匀资源需求**（某些任务需要 2+ 线程），应将其与其他任务隔离调度

### 5. 主线程不空转

`addThreadStartToExecGraph` 将最后一个线程函数直接在主线程执行：
- 主线程既是调度者也是工作者
- 减少线程切换开销
- **启示**：多线程仿真器的主线程应参与实际计算，而非仅等待

### 6. 性能分析与反馈优化

`fillinCosts()` 支持**性能分析数据覆盖**：
- 如果存在 profiling 数据，使用实测值替代估计值
- 否则使用指令计数估计
- 支持混合场景（部分任务有 profile，部分没有）
- **启示**：多线程 RTL 仿真器应支持**profile-guided optimization (PGO)**，用实际运行数据优化调度

---

## 关键代码片段

### 静态调度核心循环

```cpp
// V3ExecGraph.cpp:300-350
while (!readyMTasks.empty()) {
    uint32_t bestTime = 0xffffffff;
    uint32_t bestThreadId = 0;
    ExecMTask* bestMtaskp = nullptr;
    
    for (uint32_t threadId = 0; threadId < schedule.m_threads.size(); ++threadId) {
        for (ExecMTask* const mtaskp : readyMTasks) {
            uint32_t timeBegin = busyUntil[threadId];
            for (const V3GraphEdge& edge : mtaskp->inEdges()) {
                const ExecMTask* const priorp = edge.fromp()->as<ExecMTask>();
                const uint32_t priorEndTime = completionTime(schedule, priorp, threadId);
                if (priorEndTime > timeBegin) timeBegin = priorEndTime;
            }
            if ((timeBegin < bestTime)
                || ((timeBegin == bestTime)
                    && (mtaskp->priority() > bestMtaskp->priority()))) {
                bestTime = timeBegin;
                bestThreadId = threadId;
                bestMtaskp = mtaskp;
            }
        }
    }
    // ...
}
```

### 跨线程依赖计数

```cpp
// V3ExecGraph.cpp:210-220
uint32_t crossThreadDependencies(const ExecMTask* mtaskp) const {
    const uint32_t thisThreadId = threadId(mtaskp);
    uint32_t result = 0;
    for (const V3GraphEdge& edge : mtaskp->inEdges()) {
        const ExecMTask* const prevp = edge.fromp()->as<ExecMTask>();
        if (threadId(prevp) != thisThreadId && contains(prevp)) ++result;
    }
    return result;
}
```

### 生成的同步代码模式

```cpp
// 生成代码示例（由 addMTaskToFunction 生成）
vlSelf->__Vm_mtaskstate_5.waitUntilUpstreamDone(even_cycle);  // 等待上游
// ... MTask 函数体 ...
vlSelf->__Vm_mtaskstate_7.signalUpstreamDone(even_cycle);     // 通知下游
```

---

## 相关链接

- [V3Graph 通用图结构](https://github.com/verilator/verilator/blob/master/src/V3Graph.h)
- [Verilator 多线程文档](https://verilator.org/guide/latest/verilating.html#multithreading)
- [MTask 划分（V3Order）](https://github.com/verilator/verilator/blob/master/src/V3Order.cpp)
- [VerilatedThreadPool 实现](https://github.com/verilator/verilator/blob/master/include/verilated_threads.h)

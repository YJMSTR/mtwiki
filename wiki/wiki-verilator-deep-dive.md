---
id: "wiki-verilator-deep-dive"
title: "Verilator多线程源码深度剖析"
description: "从V3OrderParallel MTask分区、V3ExecGraph静态线程调度、verilated_threads运行时线程池到并行trace，全面解析Verilator多线程架构，并对比Icarus/ngspice/GHDL及SystemC生态"
tags: ["verilator", "multithreading", "mtask", "partition", "static-scheduling", "thread-pool", "trace", "systemc", "iverilog", "ngspice", "ghdl"]
keywords: ["V3OrderParallel", "V3ExecGraph", "VlThreadPool", "MTask", "edge-contraction", "critical-path", "sandbag", "fork-join", "NUMA", "TLM-2.0", "MINRES-SCC"]
related_sources:
  - "source-verilator-mt-deep"
  - "source-notable-simulators"
  - "source-sim-frameworks"
last_updated: "2025-07-20"
---

# Verilator 多线程源码深度剖析

Verilator 是目前最快的开源 Verilog/SystemVerilog 仿真器，其核心优势在于将 Verilog 编译为高度优化的 C++ 模型，并支持多线程并行执行。本章从四个技术层面逐层解剖 Verilator 的多线程实现，并对比其他仿真器与框架的并行化现状，提炼对多线程 RTL 仿真器设计的通用启示。

> Verilator 的设计哲学：**"尽可能在编译期做决定，运行时只做执行"**。这与传统事件驱动仿真器的事件队列动态调度形成鲜明对比。

```
Verilator 多线程架构全景
┌─────────────────────────────────────────────────────────────┐
│  编译期（Compile Time）                                        │
│  ┌─────────────────┐   ┌─────────────────┐   ┌─────────────┐  │
│  │ V3OrderParallel │ → │ V3ExecGraph     │ → │ C++ CodeGen │  │
│  │  MTask 图分区    │   │ 静态线程调度     │   │ 线程入口函数  │  │
│  │ 边收缩+CP传播    │   │ PackThreads+    │   │ __Vthread__ │  │
│  │ 数据竞争修复     │   │ sandbag保守估计  │   │ 生成        │  │
│  └─────────────────┘   └─────────────────┘   └─────────────┘  │
│                           ↓                                  │
│  运行时（Run Time）                                            │
│  ┌─────────────────┐   ┌─────────────────┐   ┌─────────────┐  │
│  │ VlThreadPool    │   │ VlWorkerThread  │   │ verilated_  │  │
│  │ 线程池初始化     │   │ 极简任务队列     │   │ trace_imp.h │  │
│  │ NUMA 亲和绑定   │   │ 自旋+yield混合   │   │ fork-join   │  │
│  │ fork-join 模型  │   │ even/odd cycle  │   │ +顺序提交    │  │
│  └─────────────────┘   └─────────────────┘   └─────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. V3OrderParallel.cpp：MTask 图分区

`V3OrderParallel.cpp` 实现了核心的 **Partitioner**，将 `V3Order` 产生的细粒度依赖图（`OrderMoveVertex` 级别）压缩为 `LogicMTask` 级别的粗粒度图。每个 `LogicMTask` 是一个可独立执行的逻辑单元，内部包含一组顺序执行的逻辑节点。

### 1.1 从 V3OrderGraph 到 MTaskGraph 的转换

`V3Order` 阶段生成的是一个细粒度的逻辑依赖图，节点粒度小到单个表达式或赋值语句。直接在如此细粒度的图上做并行调度会导致：
- 任务数量爆炸，调度开销 > 执行收益
- 缓存局部性极差，每个 MTask 只执行少量指令就切换
- 跨线程依赖边过于密集，同步成本吞噬并行收益

因此，分区器需要将细粒度图**粗化**（coarsening）到 `LogicMTask` 级别。粗化的核心指标是 **"通信/计算比"**（communication-to-computation ratio）：合并后的 MTask 内部计算量应远大于跨 MTask 的通信量。

### 1.2 边收缩（Edge Contraction）与 Sibling 合并

分区器使用贪心算法，通过合并相邻的 MTask 来减少任务数量，同时控制临界路径长度。核心数据结构是 `MergeCandidate` 评分板：

```cpp
// src/V3OrderParallel.cpp
class MergeCandidate VL_NOT_FINAL : public MergeCandidateScoreboard::Node {
    // ... 省略 ...
    bool isSiblingMC() const { return m_key.m_id & IS_SIBLING_MASK; }
    SiblingMC* toSiblingMC();
    MTaskEdge* toMTaskEdge();
    bool mergeWouldCreateCycle() const;
    inline void rescore();
    uint64_t score() const { return m_key.m_score; }
};
```

每个候选合并对（边或 sibling）都有一个 **score**，表示合并后产生的局部临界路径长度。分区器始终选择 score 最低的候选进行合并，直到所有候选的 score 超过阈值，或 MTask 数量降到目标范围。

#### 边收缩核心循环

```cpp
// src/V3OrderParallel.cpp (Contraction 类)
while (true) {
    MergeCandidate* const mergeCanp = m_sb.best();
    if (!mergeCanp) { /* 无可用合并，退出 */ break; }

    const uint64_t cachedScore = mergeCanp->score();
    mergeCanp->rescore();
    const uint64_t actualScore = mergeCanp->score();

    if (actualScore > m_scoreLimit) {
        // 最好的选项也不够好，可能提高 scoreLimit 继续
        // ... 或退出
    }

    // 避免合并 entry/exit 节点，防止全局串行化
    if (MTaskEdge* const edgep = mergeCanp->toMTaskEdge()) {
        if (edgep->fromp() == m_entryMTaskp || edgep->top() == m_exitMTaskp) {
            m_sb.remove(mergeCanp);
            continue;
        }
    }

    // 检查是否会产生环（DAG 保护）
    if (mergeCanp->mergeWouldCreateCycle()) {
        m_sb.remove(mergeCanp);
        continue;
    }

    contract(mergeCanp);  // 执行合并
}
```

> **关键约束**：entry/exit 节点是全局调度图的入口和出口，合并它们会导致所有 MTask 被串行化，因此必须跳过。`mergeWouldCreateCycle()` 保证图始终保持 DAG 性质。

### 1.3 临界路径的增量传播

合并后必须更新前后向的临界路径（Critical Path）。`PropagateCp` 类使用 **PairingHeap** 实现高效增量传播：

```cpp
// src/V3OrderParallel.cpp
template <GraphWay::en N_Way>
class PropagateCp final {
    void cpHasIncreased(V3GraphVertex* vxp, uint64_t newInclusiveCp) {
        // 对 vxp 的每个 wayward 节点，更新边堆中的 CP 值
        for (V3GraphEdge& graphEdge : vxp->edges<way>()) {
            MTaskEdge& edge = static_cast<MTaskEdge&>(graphEdge);
            LogicMTask* const relativep = edge.furtherMTaskp<N_Way>();
            EdgeHeap::Node& edgeHeapNode = edge.m_edgeHeapNode[inv];
            if (newInclusiveCp > edgeHeapNode.key().m_score) {
                relativep->m_edgeHeap[inv].increaseKey(&edgeHeapNode, newInclusiveCp);
            }
            // ... 若 relativep 的 CP 增长，加入 pending heap
        }
    }

    void go() {
        // 从 pending heap 中取出 CP 增长最大的节点，按逆序处理
        // 保证每个节点在当前轮次只被更新一次
        while (!m_pendingHeap.empty()) {
            // ... 更新 CP，并继续传播 ...
        }
    }
};
```

> **关键洞察**：使用最大堆按 "CP 增长量" 的降序处理节点，确保每个节点只被更新一次，避免递归爆炸。这是处理密集连接图时保持 O(N log N) 级别性能的关键。

`PART_STEPPED_COST` 的优化细节：当一个小节点合并到大节点时，如果大节点的 stepped cost 未增加，且进入大节点的临界路径未增加，则无需向大节点之后的顶点传播新的临界路径。这一剪枝极大降低了稠密图上的传播开销。

### 1.4 数据竞争修复（FixDataHazards）

并行模式下，原本在串行模式中无问题的无序读写对会变成数据竞争。`FixDataHazards` 识别两类问题：
- **无序写-写对**：同一信号的不同位赋值，在并行模式下可能产生 R-M-W 竞争；
- **无序写-读对**：由循环逻辑或 V3Order 的边剪断导致的读者/写者无序。

修复策略是将同一 rank 内的所有读写 MTask 合并，并在不同 rank 之间添加依赖边。这确保了：
- 同一信号的所有写操作被序列化到同一个 MTask 内；
- 跨 rank 的读操作通过显式依赖边等待所有写操作完成。

```
FixDataHazards 修复流程
┌────────────────────────────────────────┐
│ 输入：V3OrderGraph（细粒度依赖图）       │
│ 1. 识别同一 rank 内的所有读写顶点对      │
│ 2. 对每对无序读写：                      │
│    - 若为写-写：合并到同一 MTask        │
│    - 若为写-读：添加跨 rank 依赖边       │
│ 3. 输出：无数据竞争的 MTaskGraph        │
└────────────────────────────────────────┘
```

---

## 2. V3ExecGraph.cpp：静态线程调度

`V3ExecGraph.cpp` 实现了 **PackThreads** 类，在编译期完成所有调度决策，运行时只需按固定顺序执行。这是 Verilator **"零运行时调度开销"** 哲学的核心体现。

### 2.1 调度策略：带 Sandbag 的贪心列表调度

```cpp
// src/V3ExecGraph.cpp (PackThreads 类)
std::vector<ThreadSchedule> pack(V3Graph& mtaskGraph) {
    std::vector<ThreadSchedule> result;
    result.emplace_back(ThreadSchedule{m_nThreads});

    // 初始就绪列表：所有无前驱的 MTask
    std::set<ExecMTask*, MTaskCmp> readyMTasks;
    for (V3GraphVertex& vtx : mtaskGraph.vertices()) {
        ExecMTask* const mtaskp = vtx.as<ExecMTask>();
        if (isReady(result.back(), mtaskp)) readyMTasks.insert(mtaskp);
    }

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
                if (timeBegin < bestTime || (timeBegin == bestTime && mtaskp->priority() > bestMtaskp->priority())) {
                    bestTime = timeBegin;
                    bestThreadId = threadId;
                    bestMtaskp = mtaskp;
                }
            }
        }

        bestMtaskp->predictStart(bestTime);
        schedule.scheduleOn(bestMtaskp, bestThreadId);
        busyUntil[bestThreadId] = bestEndTime;
        // 更新就绪列表 ...
    }
}
```

算法逻辑：
1. 初始就绪列表 = 所有无前驱的 MTask；
2. 对每个就绪 MTask，计算它在每个线程上**最早可开始时间**（考虑所有入边的跨线程依赖）；
3. 选择使最早开始时间最小化的 (MTask, Thread) 组合；
4. 若开始时间相同，优先选择优先级更高的 MTask；
5. 将选中的 MTask 从就绪列表移除，并将其后继 MTask 加入就绪列表（如果所有前驱已完成）。

### 2.2 Sandbag（保守估计）机制

由于 MTask 的实际执行时间存在较大误差（±60% 典型值），当线程 A 查看线程 B 上任务完成时间时，会添加一个保守的 padding：

```cpp
// src/V3ExecGraph.cpp
uint32_t completionTime(const ThreadSchedule& schedule, const ExecMTask* mtaskp, uint32_t threadId) {
    if (threadId == state.threadId) {
        return state.completionTime;  // 同线程无 overhead
    }
    // 跨线程查看时添加 sandbag
    uint32_t sandbaggedEndTime = state.completionTime
        + (m_sandbagNumerator * mtaskp->cost()) / m_sandbagDenom;
    // 避免优先级翻转的约束 ...
    return sandbaggedEndTime;
}
```

> **Sandbag 的本质**：在线程间引入一个 "安全缓冲"，避免因为一个任务实际执行时间超过预期而导致后续跨线程依赖的连锁等待。这类似于航空调度中的 "layover time"——宁可让线程空闲一小会儿，也不要让后续依赖链阻塞。

### 2.3 线程入口函数生成

调度完成后，为每个线程生成一个 C 函数，包含该线程要执行的所有 MTask 调用：

```cpp
// src/V3ExecGraph.cpp
createThreadFunctions(const ThreadSchedule& schedule, const string& tag) {
    for (const std::vector<const ExecMTask*>& thread : schedule.m_threads) {
        if (thread.empty()) continue;
        const uint32_t threadId = schedule.threadId(thread.front());
        const string name{"__Vthread__" + tag + "__s" + cvtToStr(schedule.id()) + "__t" + cvtToStr(threadId)};
        AstCFunc* const funcp = new AstCFunc{fl, name, nullptr, "void"};
        funcp->isStatic(true);
        funcp->isLoose(true);
        funcp->entryPoint(true);  // 标记为线程入口
        funcp->argTypes("void* voidSelf, bool even_cycle");

        // 每个 MTask 调用前可能插入跨线程依赖等待
        for (const ExecMTask* const mtaskp : thread) {
            addMTaskToFunction(schedule, threadId, funcp, mtaskp);
        }
    }
}
```

生成的线程入口函数形如：

```cpp
// 生成的 C++ 代码（概念）
void __Vthread__top__s1__t2(void* voidSelf, bool even_cycle) {
    VlSelf* selfp = (VlSelf*)voidSelf;
    // MTask 1: 等待上游依赖完成
    selfp->mtask_1_deps.waitUntilUpstreamDone(even_cycle);
    selfp->mtask_1_code();  // 执行 MTask 1 的逻辑
    selfp->mtask_1_deps.signalUpstreamDone(even_cycle);  // 通知下游
    
    // MTask 5: 无需等待（同线程顺序依赖）
    selfp->mtask_5_code();
    selfp->mtask_5_deps.signalUpstreamDone(even_cycle);
    
    // MTask 7: 再次等待跨线程依赖
    selfp->mtask_7_deps.waitUntilUpstreamDone(even_cycle);
    selfp->mtask_7_code();
    selfp->mtask_7_deps.signalUpstreamDone(even_cycle);
}
```

> **编译期绑定 vs 运行时动态调度**：传统线程池（如 OpenMP TBB）在运行时动态分配任务。Verilator 在编译期就确定了 "哪个线程执行哪个 MTask"，运行时的 "调度" 只是按预定顺序执行。这使得运行时开销趋近于零，但牺牲了负载动态平衡的能力（对 RTL 仿真的周期性 eval 而言，这是合理的 trade-off）。

---

## 3. verilated_threads.cpp/h：运行时线程池

运行时线程池实现极其轻量，核心代码在 `verilated_threads.cpp` 和 `verilated_threads.h` 中。整个设计遵循 **"fork-join 模型 + 最小化同步"** 的原则。

### 3.1 VlMTaskVertex：原子依赖计数

每个 MTask 的依赖状态用一个原子变量 `m_upstreamDepsDone` 表示，配合 even/odd cycle 交替计数：

```cpp
// include/verilated_threads.h
class VlMTaskVertex final {
    std::atomic<uint32_t> m_upstreamDepsDone;
    const uint32_t m_upstreamDepCount;

public:
    bool signalUpstreamDone(bool evenCycle) {
        if (evenCycle) {
            const uint32_t upstreamDepsDone
                = 1 + m_upstreamDepsDone.fetch_add(1, std::memory_order_release);
            return (upstreamDepsDone == m_upstreamDepCount);
        }
        const uint32_t upstreamDepsDone_prev
            = m_upstreamDepsDone.fetch_sub(1, std::memory_order_release);
        return (upstreamDepsDone_prev == 1);
    }

    void waitUntilUpstreamDone(bool evenCycle) const {
        unsigned ct = 0;
        while (VL_UNLIKELY(!areUpstreamDepsDone(evenCycle))) {
            VL_CPU_RELAX();
            ++ct;
            if (VL_UNLIKELY(ct > VL_LOCK_SPINS)) {
                ct = 0;
                yieldThread();  // 超过自旋阈值后主动 yield
            }
        }
    }
};
```

> **even/odd cycle 的巧妙之处**：传统实现每次 eval 结束后需要遍历所有 MTask 重置依赖计数器。Verilator 使用交替增减——even cycle 时 `fetch_add(+1)`，odd cycle 时 `fetch_sub(-1)`，无需重置。当 `upstreamDepsDone == upstreamDepCount`（even）或 `== 0`（odd）时，所有上游依赖完成。这是针对周期性 eval 场景的高性能无锁同步技巧。

> **自旋 + yield 混合策略**：`VL_CPU_RELAX()` 避免自旋时占用 CPU 前端总线；当自旋超过 `VL_LOCK_SPINS` 阈值后调用 `yieldThread()`，将 CPU 让给其他线程。这平衡了低延迟（自旋）和 CPU 占用（yield）。

> **原子变量比互斥锁小**：`verilated_threads.h` 注释明确指出 `"An atomic is smaller than a mutex, and lock-free. If an mtask has many downstream mtasks to notify, we hope these will pack into a small number of cache lines to reduce the cost of pointer chasing during done-notification."` 在通知链较长的场景下，原子变量的大小直接决定了 cache line 的数量。

### 3.2 VlWorkerThread：极简工作队列

```cpp
// include/verilated_threads.h
class VlWorkerThread final {
    mutable VerilatedMutex m_mutex;
    std::condition_variable_any m_cv;
    bool m_waiting VL_GUARDED_BY(m_mutex) = false;
    std::vector<ExecRec> m_ready VL_GUARDED_BY(m_mutex);
    std::atomic<size_t> m_ready_size;  // 原子计数，用于自旋等待

public:
    template <bool N_SpinWait>
    void dequeWork(ExecRec* workp) VL_MT_SAFE_EXCLUDES(m_mutex) {
        if VL_CONSTEXPR_CXX17 (N_SpinWait) {
            for (unsigned i = 0; i < VL_LOCK_SPINS; ++i) {
                if (VL_LIKELY(m_ready_size.load(std::memory_order_relaxed))) break;
                VL_CPU_RELAX();
            }
        }
        const VerilatedLockGuard lock{m_mutex};
        while (m_ready.empty()) {
            m_waiting = true;
            m_cv.wait(m_mutex);
        }
        m_waiting = false;
        *workp = m_ready.front();
        m_ready.erase(m_ready.begin());
        m_ready_size.fetch_sub(1, std::memory_order_relaxed);
    }

    void addTask(VlExecFnp fnp, VlSelfP selfp, bool evenCycle = false) {
        bool notify;
        {
            const VerilatedLockGuard lock{m_mutex};
            m_ready.emplace_back(fnp, selfp, evenCycle);
            m_ready_size.fetch_add(1, std::memory_order_relaxed);
            notify = m_waiting;
        }
        if (notify) m_cv.notify_one();
    }
};
```

> **为什么用 `std::vector` 而不是更复杂的队列？** 因为预计队列深度极短（0-2）。`m_ready_size` 的松散原子读允许工作线程在锁外快速自旋检测新任务。如果队列深度总是很小，vector 的 `erase(begin)` 开销比复杂队列的数据结构开销更小。

### 3.3 VlThreadPool：NUMA 亲和性绑定

```cpp
// include/verilated_threads.cpp
VlThreadPool::VlThreadPool(VerilatedContext* contextp, unsigned nThreads) {
    for (unsigned i = 0; i < nThreads; ++i) {
        m_workers.push_back(new VlWorkerThread{contextp});
        m_unassignedWorkers.push(i);
    }
    m_numaStatus = numaAssign(contextp);  // 绑定 CPU 亲和性
}

std::string VlThreadPool::numaAssign(VerilatedContext* contextp) {
    // 读取 /proc/cpuinfo，解析 processor 和 core id
    // 按 core-per-thread 策略分配 CPU 集合
    // 使用 pthread_setaffinity_np 绑定线程
    // ...
}
```

> **NUMA 绑定的策略**：从当前 CPU 的下一个 processor 开始分配，尽量让工作线程落在同一 socket，减少跨 NUMA 节点访问。这是多线程仿真在服务器级 CPU 上达到接近线性加速的关键细节。如果线程 0 在 socket 0，线程 1 在 socket 1，跨 socket 的 cache 一致性协议开销可能使加速比从 0.9× 降到 0.5×。

```
NUMA 亲和绑定示意
┌─────────────────────────────────────────────────────────────┐
│  Socket 0 (NUMA Node 0)        │  Socket 1 (NUMA Node 1)    │
│  ┌─────────┐ ┌─────────┐        │  ┌─────────┐ ┌─────────┐  │
│  │ Thread0 │ │ Thread1 │ ←────  │  │ Thread2 │ │ Thread3 │  │
│  │ Core 0  │ │ Core 1  │ 同Node │  │ Core 0  │ │ Core 1  │  │
│  └─────────┘ └─────────┘        │  └─────────┘ └─────────┘  │
│  共享 L3 Cache                  │  共享 L3 Cache             │
│  本地内存访问 <100ns             │  本地内存访问 <100ns        │
│  跨Node访问 >200ns               │  跨Node访问 >200ns         │
└─────────────────────────────────────────────────────────────┘
         Verilator 优先将线程绑定到同一 Socket，避免跨Node通信
```

---

## 4. verilated_trace_imp.h：并行 Trace

Trace（VCD/FST/FSDB 波形输出）是 RTL 仿真中的 I/O 密集型操作。Verilator 将 trace 回调分发到线程池，隐藏 I/O 延迟。

### 4.1 fork-join + 顺序提交模型

```cpp
// include/verilated_trace_imp.h
void runCallbacks(const std::vector<CallbackRecord>& cbVec) {
    if (parallel()) {
        VlThreadPool* threadPoolp = static_cast<VlThreadPool*>(m_contextp->threadPoolp());
        std::list<ParallelWorkerData> workerData;
        const unsigned threads = threadPoolp->numThreads() + 1;
        std::vector<ParallelWorkerData*> mainThreadWorkerData;

        for (const CallbackRecord& cbr : cbVec) {
            Buffer* const bufp = getTraceBuffer(cbr.m_fidx);
            workerData.emplace_back(cbr.m_dumpCb, cbr.m_userp, bufp);
            ParallelWorkerData* const itemp = &workerData.back();
            if (unsigned rem = cbr.m_fidx % threads) {
                threadPoolp->workerp(rem - 1)->addTask(parallelWorkerTask, itemp);
            } else {
                mainThreadWorkerData.push_back(itemp);
            }
        }

        // 主线程也执行一部分
        for (ParallelWorkerData* const itemp : mainThreadWorkerData) {
            parallelWorkerTask(itemp, false);
        }

        // 按顺序提交所有 trace buffer
        for (ParallelWorkerData& item : workerData) {
            item.wait();
            commitTraceBuffer(item.m_bufp);
        }
        return;
    }
    // 串行 fallback ...
}
```

> **分发策略**：按 `fidx % threads` 轮询分发到线程池，主线程也参与执行。这种轮询策略比动态负载均衡更简单，且因为 trace 回调的计算量大致均匀，轮询已经足够公平。

> **顺序提交的关键**：虽然 trace 计算是并行的，但输出（VCD/FSDB 文件）必须按时间戳顺序写入。因此所有并行结果先写入 per-thread buffer，然后按原始 `fidx` 顺序逐一 `commitTraceBuffer`。这是并行化 I/O 的通用模式：并行计算 + 串行提交。

### 4.2 时间戳排序合并

每个线程的 trace buffer 包含 (timestamp, signal_value) 对。提交阶段需要：
1. 等待所有线程的 buffer 填满；
2. 按时间戳排序合并所有 buffer；
3. 确保同一时刻的所有信号值在 VCD 文件中连续出现。

由于 RTL 仿真是按 eval 周期推进的，时间戳的分布通常是稀疏且有序的，合并开销可以接受。最坏情况下（所有时间戳都交错），需要使用优先队列做 K-way merge，时间复杂度 O(N log K)，其中 K 为线程数。

```
并行 Trace 流水线
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  Eval Cycle  │   │  Fork 阶段    │   │  Join+Commit │
│  完成，产生   │ → │ 每个线程将    │ → │ 按 fidx 顺序  │
│  trace 回调  │   │ 回调写入      │   │ 提交 buffer  │
│  列表 cbVec  │   │ per-thread   │   │ 到 VCD 文件   │
└──────────────┘   │ buffer       │   └──────────────┘
                   └──────────────┘
```

---

## 5. 其他仿真器：Icarus、ngspice、GHDL

并非所有 RTL/电路仿真器都采用 Verilator 式的 "编译为 C++ 多线程模型" 路线。理解它们的架构取舍，有助于在多线程 RTL 仿真器设计中做出更明智的 trade-off。

### 5.1 Icarus Verilog：事件驱动单线程经典

Icarus Verilog 是编译器 + 虚拟机组合：`iverilog` 生成 vvp 字节码，`vvp` 解释执行。根据开发者回复：

> "iverilog is the compiler, which is a single-threaded application. The simulator run-time, vvp, is mostly single-threaded too, although it will use a second thread in some contexts."

vvp 采用经典 Verilog 事件队列模型：事件按时间戳排序，每个时间步包含 active、inactive、NBA 等区域。主循环从队列中取出最早事件，更新信号，计算新事件，插回队列。

**多线程缺失的根本原因**：
1. **事件队列全局串行**：Verilog 语义要求在同一时间戳内按特定顺序处理事件，全局队列难以无损并行化；
2. **解释执行开销低**：vvp 字节码是中间形式，单线程性能已受限于解释器本身，多线程收益不明显；
3. **设计定位**：重点是语言覆盖和标准兼容，而非极致性能。

> **对多线程 RTL 仿真器的启示**：如果目标支持标准 Verilog 的事件语义，事件队列的并行化是根本性难题。可能的妥协：像 Verilator 那样放弃部分动态事件语义，换取编译期优化；或采用 "时间分片 + 周期精确" 的抽象层级来规避事件队列。

### 5.2 ngspice：共享库 API + 外部回调同步

ngspice 的核心求解器（矩阵求解、牛顿迭代）未实现内部多线程，但提供了一种独特的**粗粒度并行**方案：将 ngspice 编译为共享库，由外部主控加载多个实例，每个实例运行一个电路分区。

```c
// src/include/ngspice/sharedspice.h
/* 初始化回调接口 */
IMPEXP
int ngSpice_Init(SendChar* printfcn, SendStat* statfcn, ControlledExit* ngexit,
                 SendData* sdata, SendInitData* sinitdata, 
                 BGThreadRunning* bgtrun, void* userData);

/* 同步回调：请求外部提供电压源值 */
typedef int (GetVSRCData)(double* return_voltage, double actual_time, 
                          char* node_name, int lib_id, void* userData);

/* 同步回调：请求外部提供时间步长控制 */
typedef int (GetSyncData)(double actual_time, double* delta_time, 
                          double old_delta, int redostep, 
                          int lib_id, int call_location, void* userData);
```

**核心设计思想**：仿真器本身不处理并行，而是将并行责任交给外部主控。主控通过 `GetSyncData` 回调同步多个实例的仿真进度，通过 `GetVSRCData`/`GetISRCData` 在分区边界交换电压/电流数据。

| 维度 | ngspice | Verilator |
|------|---------|-----------|
| 并行粒度 | 粗粒度（电路分区级别） | 细粒度（MTask 级别） |
| 并行控制 | 外部主控 + 回调同步 | 编译期静态调度 |
| 适用场景 | 模拟/混合信号电路 | 数字 RTL |
| 线程安全 | 实例间完全隔离 | 共享模型状态，需处理数据竞争 |
| 扩展性 | 受分区质量限制 | 受临界路径限制 |

> **对多线程 RTL 仿真器的启示**：模拟电路的矩阵求解是强耦合的，内部分线程并行化难度远高于数字逻辑。若需支持混合信号，可能需要同时支持两种并行模式：数字部分的 MTask 细粒度并行 + 模拟部分的实例级粗粒度并行。

### 5.3 GHDL：LLVM JIT 实验

GHDL 是 VHDL 仿真器，支持解释执行（mcode）、编译为 C、以及实验性 LLVM JIT 后端。在实验分支中探索了 **multiprocessing** 模式，将 VHDL 进程映射到 OS 进程/线程来并行化。

与 Verilator 的 MTask 不同，GHDL 的并行单元是 VHDL 语言层面的 `process`：
- 每个 VHDL process 是独立执行的逻辑单元；
- 进程间通过信号通信，天然具有显式依赖；
- 进程触发的条件是敏感列表或 wait 语句，可被静态分析。

然而，VHDL 的 delta cycle 语义要求在同一仿真时刻内反复执行进程直到信号稳定，这导致了类似于 Verilog 事件队列的同步问题。GHDL 的多进程实验目前主要用于特定场景（如独立测试平台的并行执行），而非通用 RTL 模型加速。

> **对多线程 RTL 仿真器的启示**：编译型加速（Verilator 的 C++ 编译、GHDL 的 LLVM JIT）相比解释型执行有数量级的性能优势。对于频繁仿真的回归测试，JIT 编译可能比传统的 "Verilate -> 编译 C++ -> 链接" 流程更快迭代。

---

## 6. 仿真框架：SystemC、TLM-2.0、UVM-SystemC、MINRES SCC

SystemC 和 UVM 构成了现代 SoC 验证的骨架，但它们的并行化故事比 Verilator 复杂得多。核心矛盾在于：**SystemC 的内核是单线程的，但上层应用需要多线程/分布式能力**。

### 6.1 SystemC 单线程内核（SCDTHREADS）

SystemC 参考实现的仿真内核是单线程的：所有 `SC_METHOD`、`SC_THREAD`、`SC_CTHREAD` 都由一个 `sc_simcontext` 统一调度。即使你在 SystemC 模块中创建了 `std::thread`，这些线程也不能直接调用 SystemC API（如 `wait()`、`notify()`），因为内核不是线程安全的。

学术界探索了多种并行化方案：

**SCDTHREADS (UNICAMP)**：将 SystemC 进程分配到多个 OS 线程，通过 TLM 通道进行同步，避免修改内核的调度器。这是一种 **"进程级并行 + 通道级同步"** 的折中方案。

**分布式 SystemC 仿真 (ETH Zurich)**：将 SystemC 仿真分布到多台机器上，通过网络同步时间戳。适用于 MPSoC 设计空间探索（DSE），其中不同子系统可以在不同节点上独立推进，仅在时间同步点交互。

> **对多线程 RTL 仿真器的启示**：如果目标是与 SystemC 生态集成，必须面对 "SystemC 内核单线程" 这一约束。最务实的接口方式：将多线程仿真器作为 "外设" 通过 TLM socket 接入 SystemC 平台，而非试图将 SystemC 进程映射到线程模型。

### 6.2 TLM-2.0 时间解耦

TLM-2.0 定义了四种时间精度级别：UT（无时间）、LT（松散时间）、AT（近似时间）、Cycle-Accurate（精确周期）。LT 模式允许 initiator 在执行事务时 "借用" 时间（quantum），直到 quantum 耗尽才交还控制权。

**temporal decoupling 的两个效果**：
1. **减少同步频率**：多个 initiator 可在各自的 quantum 内独立推进；
2. **天然适合并行化**：如果不同 initiator 的 quantum 不重叠，它们可以真正并行执行。

> **对多线程 RTL 仿真器的启示**：在仿真器侧维护一个本地时间偏移量（local time），当收到 TLM 事务时将本地时间推进到事务时间戳，仅在 quantum 边界或显式同步点与 SystemC 全局时间对齐。这与 Verilator 的 `eval()` 模型类似：Verilator 模型可以在一个 eval 周期内推进多个时钟周期，只要外部 testbench 同意这种 "批量推进"。

### 6.3 UVM-SystemC 方法学限制

UVM-SystemC 的底层执行仍依赖 SystemC 的单线程内核：
- `uvm_sequence` 的 `body()` 运行在 `SC_THREAD` 中；
- 并发序列实际上是**协作式多任务**（cooperative multitasking），而非抢占式多线程；
- 没有内置的线程池或 MTask 分区概念。

UVM-SystemC 的价值在于**方法学统一**（相同的 testbench 架构可用于 SystemVerilog 和 SystemC），而非性能并行化。如果目标是 "UVM 风格的验证平台"，需要自行实现底层的并行执行引擎。

### 6.4 MINRES SCC：Verilated RTL 接入 SystemC VP

MINRES 的 SystemC Components Library (SCC) 提供了目前工业界最实用的 "SystemC VP + Verilated RTL" 混合仿真方案：

```
SystemC TLM Platform (Virtual Platform)
  -> TLM initiator (e.g., CPU model)
  -> TLM-2.0 interconnect (bus)
  -> SCC Adapter (TLM -> pin-level)
  -> Verilated RTL Module (Verilator generated)
  -> SCC Adapter (pin-level -> TLM)
  -> TLM target (e.g., memory model)
```

SCC 提供的解决方案：
- **Pin-level adapters**：将 TLM 事务转换为 pin wiggle（周期级信号翻转）；
- **Bus adapters**：将 AXI/APB 等总线 TLM 事务映射到 RTL 信号接口；
- **Verilated model wrapper**：将 Verilator 生成的 C++ 模型包装为 SystemC 模块。

> **核心启示**：不必将所有东西都做到一个仿真器里，而是做好**标准接口**（TLM-2.0 socket），让 Verilator 等专用工具处理 RTL 加速，自己负责系统级集成。跨语言并行的边界最好是**事务级**（粗粒度）而非**信号级**（细粒度）。如果 SystemC VP 和 Verilated RTL 之间需要每个周期都同步，通信开销将吞噬多线程收益。

---

## 7. 对多线程 RTL 仿真器的启示

综合 Verilator 源码与其他仿真器的对比，提炼以下五条核心启示：

### 启示 1：编译期分区是最佳实践参考

Verilator 的 MTask 分区通过边收缩和临界路径传播，将细粒度逻辑图粗化为适合多线程执行的并行单元。粗化的核心指标不是 "最大并行度"，而是 **"通信/计算比"**——每个 MTask 内部应有足够的计算量来摊平跨线程同步的开销。

### 启示 2：线程池 fork-join 模型简单有效

Verilator 的运行时线程池没有使用复杂的任务窃取或动态负载均衡，而是采用极简的 fork-join 模型：主线程分发任务，工作线程执行，然后 join 等待完成。这种设计适用于 RTL 仿真的周期性 eval 场景，因为每次 eval 的任务结构是固定的，无需运行时重新调度。

### 启示 3：Trace 的顺序提交是并行化的关键约束

并行 trace 的核心难点不是计算并行化，而是**输出的顺序性保证**。VCD/FSDB 文件格式要求信号值按时间戳顺序写入。Verilator 的解决方案（per-thread buffer + 顺序提交）是一个通用模式：并行计算结果先缓存在线程本地 buffer，最后按原始顺序提交到串行输出流。

### 启示 4：NUMA 亲和绑定是服务器级加速的关键细节

Verilator 花了一百多行代码做 `/proc/cpuinfo` 解析和 affinity 绑定。在多核服务器上，这一细节往往决定了超线程/多路 CPU 场景下的加速比能否接近理论值。跨 NUMA 节点的内存访问延迟（>200ns）足以抵消细粒度并行带来的收益。

### 启示 5：Sandbag 保守估计减少运行时同步等待

在编译期调度时引入执行时间的不确定性缓冲，当实际执行时间存在抖动时，保守调度反而能减少运行时的同步等待。这一思路适用于任何静态调度硬件仿真的场景。

---

## 8. 可操作建议

### 8.1 参考 MTask 分区实现静态任务图

如果你正在实现多线程 RTL 仿真器，建议参考 Verilator 的 MTask 分区流程：

```
1. 从 RTL 网表构建细粒度数据流图（节点 = 逻辑表达式，边 = 数据依赖）
2. 应用 FixDataHazards 修复并行模式下的数据竞争
3. 使用边收缩算法将图粗化为 MTask 级别（目标：每个 MTask 执行时间 > 100μs）
4. 用 PairingHeap 实现临界路径增量传播，控制粗化后的最长路径
5. 输出：带执行时间估计的 MTask DAG
```

> **关键参数**：`PART_STEPPED_COST` 控制合并时的步长代价权重，`scoreLimit` 控制合并的终止条件。需要根据目标硬件的 cache 大小和内存带宽调整这些参数。

### 8.2 使用 fork-join 线程池最小化同步开销

```cpp
// 最小化可运行的 fork-join 线程池实现
class ForkJoinPool {
    std::vector<std::thread> m_workers;
    std::vector<std::vector<Task>> m_perThreadQueues;  // 每个线程一个队列
    std::atomic<uint32_t> m_doneCount;
    
public:
    void fork(const std::vector<Task>& tasks, uint32_t nThreads) {
        m_doneCount.store(0);
        for (uint32_t i = 0; i < tasks.size(); ++i) {
            m_perThreadQueues[i % nThreads].push_back(tasks[i]);
        }
        for (uint32_t t = 0; t < nThreads; ++t) {
            m_workers[t] = std::thread([this, t]() {
                for (auto& task : m_perThreadQueues[t]) task.execute();
                m_doneCount.fetch_add(1, std::memory_order_release);
            });
        }
    }
    
    void join() {
        for (auto& w : m_workers) w.join();
    }
};
```

> **要点**：避免使用全局任务队列（竞争热点），改为每个线程一个队列（per-thread queue）。分发策略可以是轮询（如 Verilator 的 trace）或静态绑定（如 MTask 调度）。

### 8.3 Trace 使用 per-thread buffer + 时间戳排序合并

```cpp
// 并行 trace 的推荐实现模式
template<typename Buffer>
void parallelTrace(const std::vector<TraceCallback>& callbacks, uint32_t nThreads) {
    std::vector<Buffer> buffers(nThreads);
    std::vector<std::thread> threads;
    
    // Fork：每个线程写入自己的 buffer
    for (uint32_t t = 0; t < nThreads; ++t) {
        threads.emplace_back([&, t]() {
            for (size_t i = t; i < callbacks.size(); i += nThreads) {
                callbacks[i](buffers[t]);
            }
        });
    }
    for (auto& t : threads) t.join();
    
    // Join + 顺序提交：按原始顺序合并所有 buffer
    for (size_t i = 0; i < callbacks.size(); ++i) {
        commitBuffer(buffers[i % nThreads], i);
    }
}
```

> **注意**：如果 buffer 内的时间戳不是单调的，需要在提交阶段做 K-way merge（使用最小堆）。对于 RTL 仿真，由于 eval 是周期推进的，时间戳通常单调，可以直接按轮询顺序提交。

### 8.4 NUMA 亲和绑定减少跨节点通信

```cpp
// Linux 下的 NUMA 亲和绑定示例
#include <pthread.h>
#include <sched.h>

void bindThreadToCore(int threadId, int coreId) {
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(coreId, &cpuset);
    pthread_setaffinity_np(pthread_self(), sizeof(cpu_set_t), &cpuset);
}

// 策略：从当前 CPU 的下一个 core 开始，尽量落在同一 socket
// 需要读取 /proc/cpuinfo 解析 core id 与 socket id 的映射
```

> **Windows 对应 API**：`SetThreadAffinityMask()`。需要解析 `GetLogicalProcessorInformationEx()` 返回的 NUMA 节点信息。

---

## 总结

Verilator 的多线程架构是一个**"编译期做尽、运行时做轻"**的典范。从 `V3OrderParallel` 的 MTask 图分区到 `V3ExecGraph` 的静态线程调度，再到 `verilated_threads` 的极简 fork-join 线程池，每一层都在回答同一个问题：**如何在保证正确性的前提下，将同步开销推到编译期，让运行时只做执行？**

对比其他仿真器，Icarus 的事件驱动模型展示了标准 Verilog 语义与并行的根本性冲突；ngspice 的共享库方案说明模拟电路的强耦合性限制了细粒度并行；GHDL 的 LLVM JIT 实验展示了编译型加速的另一条路径。而 SystemC 生态则提醒我们：**做好标准接口比做好全能仿真器更重要**——TLM-2.0 的 temporal decoupling 和 MINRES SCC 的 adapter 模式，都是将 Verilator 的 RTL 加速能力嵌入更大验证框架的务实方案。

对于正在构建多线程 RTL 仿真器的开发者，最核心的四条行动准则是：
1. **静态分区优于动态调度**：编译期的 MTask 分区将同步开销降为零；
2. **粗粒度优于细粒度**：MTask 内部计算量应远大于跨线程通信量；
3. **顺序提交保证正确性**：并行计算后必须按原始顺序提交结果；
4. **NUMA 感知不可忽视**：线程绑定到同一 socket 是多核服务器接近线性加速的前提。

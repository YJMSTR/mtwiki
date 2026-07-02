---
title: "Verilator 多线程源码深度分析：V3OrderParallel、V3ExecGraph、VlThreadPool"
description: "对 Verilator 多线程核心源码的逐层解剖，涵盖 MTask 图分区、临界路径传播、线程静态调度、线程池实现与 NUMA 亲和性"
source_url: "https://github.com/verilator/verilator"
source_type: "github-repo"
author: "Wilson Snyder / Verilator 社区"
date: "2024-2025"
tags: ["verilator", "multithreading", "mtask", "partition", "thread-pool", "RTL-simulation"]
keywords: ["V3OrderParallel", "V3ExecGraph", "VlThreadPool", "MTask", "static-scheduling", "critical-path"]
capture_date: "2025-07-20"
---

# Verilator 多线程源码深度分析

## 来源

- **仓库**: https://github.com/verilator/verilator
- **核心文件**:
  - `src/V3OrderParallel.cpp` — MTask 图分区与临界路径传播
  - `src/V3ExecGraph.cpp` — 静态线程调度与执行图生成
  - `include/verilated_threads.cpp` / `include/verilated_threads.h` — 运行时线程池与 NUMA 亲和
  - `include/verilated_trace_imp.h` — 并行 trace 的线程池分发
- **类型**: GitHub 开源仓库源码
- **作者**: Wilson Snyder 及 Verilator 社区
- **日期**: 持续活跃（2024-2025 年大量多线程重构）

## 摘要

Verilator 是目前最快的开源 Verilog/SystemVerilog 仿真器，其核心优势在于将 Verilog 编译为高度优化的 C++ 模型，并支持多线程并行执行。本分析深入 Verilator 多线程实现的四个关键层面：

1. **编译期 MTask 分区** (`V3OrderParallel.cpp`)：将细粒度的逻辑依赖图粗化为 MTask 图，通过边收缩（edge contraction）与 sibling 合并，最大化并行度；
2. **静态线程调度** (`V3ExecGraph.cpp`)：在编译期将 MTask 静态绑定到线程，生成线程入口函数，避免运行时的动态调度开销；
3. **运行时线程池** (`verilated_threads.cpp`)：基于 pthread/std::thread 的轻量级工作线程队列，支持 NUMA 亲和性绑定；
4. **并行 Trace** (`verilated_trace_imp.h`)：将 VCD/FST 等 trace 回调分发到线程池，隐藏 I/O 延迟。

Verilator 的设计哲学是 **"尽可能在编译期做决定，运行时只做执行"**，这与传统事件驱动仿真器的事件队列动态调度形成鲜明对比。

## 关键要点

### 1. MTask 图分区：从细粒度逻辑图到粗粒度并行单元

`V3OrderParallel.cpp` 实现了核心的 **Partitioner**，将 `V3Order` 产生的细粒度依赖图（`OrderMoveVertex` 级别）压缩为 `LogicMTask` 级别的粗粒度图。每个 `LogicMTask` 是一个可独立执行的逻辑单元，内部包含一组顺序执行的逻辑节点。

#### 边收缩（Edge Contraction）与 Sibling 合并

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

#### 代码片段：边收缩核心循环

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

#### 临界路径的增量传播

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

> 关键洞察：使用最大堆按 "CP 增长量" 的降序处理节点，确保每个节点只被更新一次，避免递归爆炸。这是处理密集连接图时保持 O(N log N) 级别性能的关键。

#### 数据竞争修复（FixDataHazards）

并行模式下，原本在串行模式中无问题的无序读写对会变成数据竞争。`FixDataHazards` 识别两类问题：
- **无序写-写对**：同一信号的不同位赋值，在并行模式下可能产生 R-M-W 竞争；
- **无序写-读对**：由循环逻辑或 V3Order 的边剪断导致的读者/写者无序。

修复策略是将同一 rank 内的所有读写 MTask 合并，并在不同 rank 之间添加依赖边。

---

### 2. 静态线程调度：编译期绑定 MTask 到线程

`V3ExecGraph.cpp` 实现了 **PackThreads** 类，在编译期完成所有调度决策，运行时只需按固定顺序执行。

#### 调度策略：带 Sandbag 的贪心列表调度

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

#### Sandbag（保守估计）机制

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

> 这相当于在线程间引入一个 "安全缓冲"，避免因为一个任务实际执行时间超过预期而导致后续跨线程依赖的连锁等待。

#### 生成线程入口函数

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

---

### 3. 运行时线程池：VlWorkerThread 与 VlThreadPool

运行时线程池实现极其轻量，核心代码在 `verilated_threads.cpp` 和 `verilated_threads.h` 中。

#### VlMTaskVertex：原子依赖计数

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

> 用 even/odd cycle 交替增减，避免每次 eval 都要重置计数器。当上游依赖完成时，下游 MTask 才能开始执行。自旋 + yield 的混合策略平衡了低延迟和 CPU 占用。

#### VlWorkerThread：极简工作队列

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

> 工作队列使用 `std::vector` 而非更复杂的队列，因为预计队列深度极短（0-2）。`m_ready_size` 的松散原子读允许工作线程在锁外快速自旋检测新任务。

#### VlThreadPool：NUMA 亲和性

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

> NUMA 绑定从当前 CPU 的下一个 processor 开始分配，尽量让工作线程落在同一 socket，减少跨 NUMA 节点访问。这是多线程仿真在服务器级 CPU 上达到接近线性加速的关键细节。

---

### 4. 并行 Trace：隐藏 I/O 延迟

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

> Trace 回调按 `fidx % threads` 轮询分发到线程池，主线程也参与执行。所有结果按原始顺序提交，保证输出正确性。这是一个经典的 **"fork-join + 顺序提交"** 模式。

## 对 RTL 仿真器多线程化的启示

1. **编译期分区 vs 运行时动态调度**：Verilator 的静态调度在编译期完成所有负载平衡，运行时零开销。如果我们的仿真器需要支持动态事件，是否也能借鉴这种 "尽可能静态、必要时动态" 的混合策略？

2. **MTask 粗化粒度**：细粒度锁/任务在硬件仿真中代价极高。Verilator 通过 `PART_STEPPED_COST` 和临界路径传播控制分区质量，提示我们在设计分区算法时，应该关注 **"通信/计算比"** 而非盲目追求最大并行度。

3. **even/odd cycle 依赖计数**：`VlMTaskVertex` 使用交替增减避免重置，这是针对周期性 eval 场景的高性能无锁同步技巧。若我们的仿真器也是按 eval 周期推进，这种设计值得直接借鉴。

4. **NUMA 感知**：线程池实现中花了一百多行代码做 `/proc/cpuinfo` 解析和 affinity 绑定。在多核服务器上，这一细节往往决定了超线程/多路 CPU 场景下的加速比能否接近理论值。

5. **Sandbag 保守估计**：在编译期调度时引入执行时间的不确定性缓冲，这一思路可用于任何静态调度硬件仿真的场景。当实际硬件执行时间存在抖动时，保守调度反而能减少运行时的同步等待。

## 原文摘录

> "The fine-grained graph from V3Order may contain data hazards which are not a problem for serial mode, but which would be a problem in parallel mode. There are basically two classes: unordered pairs of writes, and unordered write-read pairs."
> —— `V3OrderParallel.cpp`, FixDataHazards 类注释

> "If there are huge vertices, when a tiny vertex merges into a huge vertex, we can often avoid increasing the huge vertex's stepped cost. If the stepped cost hasn't increased, and the critical path into the huge vertex hasn't increased, we can avoid propagating a new critical path to vertices past the huge vertex."
> —— `V3OrderParallel.cpp`, PART_STEPPED_COST 注释

> "Add some padding to the estimated runtime when looking from another thread... This extra 'padding' avoids tight 'layovers' at cross-thread dependencies."
> —— `V3ExecGraph.cpp`, PackThreads::completionTime

> "An atomic is smaller than a mutex, and lock-free. (Why does the size of this class matter? If an mtask has many downstream mtasks to notify, we hope these will pack into a small number of cache lines to reduce the cost of pointer chasing during done-notification.)"
> —— `verilated_threads.h`, VlMTaskVertex 注释

## 相关链接

- [Verilator 官方文档 — 多线程指南](https://verilator.org/guide/latest/verilating.html#multithreading)
- [V3OrderParallel.cpp @ GitHub](https://github.com/verilator/verilator/blob/master/src/V3OrderParallel.cpp)
- [V3ExecGraph.cpp @ GitHub](https://github.com/verilator/verilator/blob/master/src/V3ExecGraph.cpp)
- [verilated_threads.h @ GitHub](https://github.com/verilator/verilator/blob/master/include/verilated_threads.h)
- [Internals — 多线程调度原理](https://github.com/verilator/verilator/blob/master/docs/internals.rst)

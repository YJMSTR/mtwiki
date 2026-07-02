---
title: "任务调度器与负载均衡设计：Work-Stealing、优先级队列与线程亲和性"
description: "搜集任务调度器实现与负载均衡策略，包括 Max Liani 的渲染器调度器、Molecular Matters 的负载均衡系列、T_Threads 的锁无关 work-stealing + 优先级 + 线程亲和性，以及 lock-free priority-aware deque 研究。"
source_url: "https://maxliani.wordpress.com/2022/07/27/anatomy-of-a-task-scheduler/"
source_type: "blog"
author: "Max Liani, Molecular Matters, jay403894-bit, shadowcode0007"
date: "2012-2022"
tags: ["task-scheduler", "load-balancing", "work-stealing", "priority-queue", "thread-affinity", "nested-parallelism"]
keywords: ["task scheduler C++", "work stealing scheduler", "load balancing thread pool", "task queue priority", "scheduler thread affinity"]
capture_date: "2026-07-03"
---

# 任务调度器与负载均衡设计：Work-Stealing、优先级队列与线程亲和性

## 来源

- **Anatomy of a task scheduler** — Max Liani: https://maxliani.wordpress.com/2022/07/27/anatomy-of-a-task-scheduler/
- **Building a load-balanced task scheduler** — Molecular Matters (Part 1): https://blog.molecular-matters.com/2012/04/05/building-a-load-balanced-task-scheduler-part-1-basics/
- **T_Threads** — GitHub: https://github.com/jay403894-bit/T_Threads
- **Lock-Free Priority-Aware Work-Stealing Deque**: https://shadowcode0007.github.io/
- **Priority Work-Stealing Scheduler** — shamsimam: https://github.com/shamsimam/priorityworkstealing

---

## 摘要

线程池只是「容器」，真正的效率取决于调度策略。本资料聚焦于调度器的设计决策：

1. **Max Liani 的渲染器调度器**：拒绝无意义自旋、拒绝黑盒启发式，支持可控线程数并行、异步任务、透明嵌套并行。核心创新是将嵌套并行优先推入队列**前端**，保证内层循环优先完成，降低峰值内存。
2. **Molecular Matters 负载均衡系列**：从最简单的全局 mutex 队列出发，逐步引入 work-stealing，解释为何全局锁会成为瓶颈。
3. **T_Threads**：C++17 实现，融合 local queue（线程亲和性）、跨线程 work-stealing、5 级优先级队列、epoch-based GC，以及 forked task（从线程池临时剥离线程执行专用任务）。
4. **Lock-Free Priority-Aware Deque**：在经典 Chase-Lev 基础上增加优先级维度，使用 `compare_exchange` / `fetch_add` 实现无锁化，适合混合优先级任务场景。

---

## 关键要点

- **No Spinning 原则**：许多 work-stealing 调度器让所有线程像「饥饿的食人鱼」一样疯狂轮询其他队列。这不仅浪费 CPU，还会因 cache invalidation 拖慢真正干活的线程。Max Liani 的设计让线程在没有任务时**进入休眠**，由条件变量唤醒，使性能监控更诚实、CPU Turbo Boost 更有效。
- **嵌套并行优先级**：当外层循环并行化后，其每个单元可能再触发内层并行。调度器应优先执行内层任务（push to front），否则外层任务会占用线程导致内层无法展开，造成内存峰值飙升。Max Liani 用一个 `bool front = getNestingLevel() > 0` 实现。
- **线程亲和性（Thread Affinity）**：将特定任务绑定到指定 CPU 核心，可提升 cache locality。T_Threads 提供 `submitLocal(coreID, task)` 与 `submitFork(coreID, task)` 两种亲和性 API。
- **优先级 vs 公平性**：shamsimam 的 priority work-stealing 证明，即使 worker 非空闲也应执行偷取（steal），以确保高优先级任务尽快被调度，最大限度降低优先级反转。
- **调度器设计的最大敌人是「黑盒」**：TBB 等高度工程化的调度器往往内置复杂启发式，在偏离其早期 tuning 负载时效率骤降。可预测、可控制的手动分区通常更可靠。

---

## 对 RTL 仿真器多线程化的启示

RTL 仿真天然具备嵌套并行结构：
- **顶层**：按 module / hierarchy 分区；
- **中层**：每个 module 内的 always 块或连续赋值；
- **底层**：向量级位运算（如 1024-bit 总线按 64-bit 切片并行）。

调度器设计必须回答：
1. **谁优先？** 外层 module 的更新 vs 内层 gate 的并行计算。答案：**内层优先**，因为外层完成一个 module 意味着需要释放该 module 的临时数据结构，降低内存峰值。
2. **如何负载均衡？** 不同 module 的 always 块复杂度差异巨大。使用 work-stealing 让完成快的线程从慢线程偷取任务，避免「L 型」负载分布（一核干活、其余 idle）。
3. **线程亲和性**：RTL 仿真中某些 module 的 memory 在 NUMA 节点 A 上，将负责该 module 的 worker 绑定到 NUMA A 的核，可减少跨节点访存延迟。
4. **优先级队列**：组合逻辑（前向路径）应在时序逻辑（后向路径）之前执行？实际上取决于仿真模型。优先级队列允许为不同 event 类型赋予权重，实现更细粒度的调度策略。

---

## 原文摘录与代码片段

### 1. Max Liani 调度器 — 无自旋、嵌套优先、48 字节 Task 结构

**核心设计原则**：
> 1. Parallelize a workload over a controllable number of threads.
> 2. Launch asynchronous tasks.
> 3. Transparent support for nested parallelism.
> 4. No spinning.
> 5. No black boxes.

**Task 结构（48 字节）**：
```cpp
struct Scheduler::Task
{
    inline Task(int numUnits, void* data, TaskFn fn, TaskFn epilogue = nullptr)
        : data(data), fn(fn), epilogue(epilogue), parent(nullptr), numUnits(numUnits)
    {}

    void*      data;       // 任务数据（不透明指针）
    TaskFn       fn;       // 任务函数
    TaskFn epilogue;       // 可选收尾函数（归约等）
    Task*    parent;       // 嵌套并行时的父任务
    int    numUnits;       // 工作单元数（建议不超过硬件并发数）

    std::atomic<int> completed = 0;    // 已完成单元数
    std::atomic<int> refcount = 0;     // 生命周期引用计数
    std::atomic<int> dependencies = 1; // 未完成子任务数（含自身）

    bool valid() const { return numUnits != 0; }
};
```

**parallelize 阻塞式并行 + 当前线程参与计算**：
```cpp
void parallelize(uint32_t numThreads, void* data, TaskFn fn, TaskFn epilogue = nullptr)
{
    if (numThreads == k_all) numThreads = getNumThreads();
    if (numThreads == 0) return;

    int threadIndex = getOrAssignThreadIndex();
    bool front = getNestingLevel() > 0; // 嵌套任务推到队列前端
    constexpr int localRun = 1;
    TaskTracker result = async(numThreads, data, fn, epilogue, localRun, front);

    // 当前线程执行第一个工作单元，随后参与其他任务
    int chunkIndex = 0;
    runTask(result.task, chunkIndex, threadIndex);
    result.wait();
}
```

> **关键点**：`result.wait()` 不是阻塞等待，而是让调用线程**进入调度器参与计算**。这是避免嵌套并行死锁的核心机制。

**双端队列优先级实现（极简 deque）**：
```cpp
bool front = getNestingLevel() > 0; // 嵌套并行 -> 高优先级
if (front)
    work.push_front(task);
else
    work.push_back(task);
```

**工作量估算工具**：
```cpp
template<int k_unitSize, int k_maxThreads = 1<<16>
inline size_t estimateThreads(size_t workloadSize, const Scheduler& scheduler)
{
    size_t nChunks = (workloadSize + k_unitSize - 1) / k_unitSize;
    size_t numThreads = std::min<size_t>(nChunks,
        std::min<size_t>(k_maxThreads, scheduler.getNumThreads()));
    return numThreads;
}
```

### 2. Molecular Matters — 从全局队列到 Work-Stealing 的演进

**最简单的全局队列调度器**：
```cpp
AddTaskToScheduler(task)
{
    LockSynchronizationPrimitive();
    globalTaskQueue.Add(task);
    UnlockSynchronizationPrimitive();
}

while (threadShouldRun)
{
    WaitUntilTaskIsAvailable();
    LockSynchronizationPrimitive();
    task = globalTaskQueue.GetAndRemove();
    UnlockSynchronizationPrimitive();
    Execute(task);
}
```

> **全局队列的致命缺陷**：
> - 每次 push/pop 都加锁，高竞争下锁开销成为瓶颈；
> - 任务只能串行提交；
> - 无负载均衡：即使任务工作量相同，也无法保证各线程同时完成；
> - 等待任务完成时，调用线程 idle。

**Work-Stealing 的解决思路**：
- 每个 worker 维护**本地队列**；
- 提交任务时先放入全局队列或某个 worker 的本地队列；
- 当 worker 本地队列为空时，从其他 worker 的队列**偷取**任务；
- 全局队列仅用于外部任务提交，worker 本地操作无锁或仅轻量锁。

### 3. T_Threads — 锁无关-ish 的 C++17 任务调度器

**特性矩阵**：
| 特性 | 说明 |
|------|------|
| Local Queues | 任务可绑定到特定线程，提升 cache locality |
| Work-Stealing | 空闲线程从其他队列偷取任务 |
| Priority Queues | 5 级优先级（0-4） |
| Epoch GC | 每 500ms 一轮 epoch 清理，避免运行期内存分配 |
| Forked Tasks | 临时从线程池剥离线程执行专用任务，完成后可重新加入 |
| Periodic/Delayed | 支持周期性任务与延迟任务 |

**API 示例**：
```cpp
TaskScheduler& scheduler = TaskScheduler::instance();
scheduler.startPool(0); // 选择 core 0 运行时钟与堆管理线程

// 本地队列（round-robin 负载均衡）
scheduler.submitLocal([](){ std::cout << "Local task\n"; });
scheduler.submitLocal(1, [](){ std::cout << "Pinned to core 1\n"; });

// 优先级队列（0-4，默认 3）
scheduler.submitPQ(0, task);  // 最高优先级
scheduler.submitPQ(4, task);  // 最低优先级

// 从线程池 fork 出专用线程
scheduler.submitFork(coreID, task);
// task->stop() 后重新加入线程池

// 周期性/延迟任务
scheduler.submitPeriodic("heartbeat", 1000, task); // 每 1000ms
scheduler.submitDelayed(500, task); // 延迟 500ms
```

> **Epoch GC**：调度器内部使用 epoch-based 内存管理，所有任务节点按 epoch 批量释放，避免细粒度 `delete` 带来的 cache thrashing。

### 4. Lock-Free Priority-Aware Work-Stealing Deque

**核心伪代码**：
```cpp
while not done:
    task = pop_local_highest_priority_task()
    if task != NULL:
        execute(task)
    else:
        victim = check_other_threads()
        task = steal_lowest_priority_task_from(victim)
        if task != NULL:
            execute(task)
        else:
            increment local_priority
            spin_wait()
```

> **设计权衡**：
> - 本地队列按优先级排序，owner 线程始终取最高优先级；
> - 偷取线程取**最低优先级**，避免「把好任务都抢走」；
> - 使用 `std::atomic` + `compare_exchange` 替代锁，避免 contention；
> - 优先级 skew（倾斜）时可能引发 fairness 问题，需要动态调节偷取策略。

### 5. shamsimam — Priority Work-Stealing Scheduler（Java/C++ 可移植思想）

> 我们的调度器采用**非空闲偷取**（steal even if not idle）：worker 线程即使手头有任务，也会从其他队列偷取更高优先级任务，以最大限度减少优先级反转。实验表明，在细粒度任务场景下性能优于标准库调度器。

---

## 相关链接

- [Anatomy of a task scheduler — Max Liani](https://maxliani.wordpress.com/2022/07/27/anatomy-of-a-task-scheduler/)
- [Building a load-balanced task scheduler – Part 1](https://blog.molecular-matters.com/2012/04/05/building-a-load-balanced-task-scheduler-part-1-basics/)
- [T_Threads GitHub](https://github.com/jay403894-bit/T_Threads)
- [Lock-Free Priority-Aware Work-Stealing Deque](https://shadowcode0007.github.io/)
- [Priority Work-Stealing Scheduler — shamsimam](https://github.com/shamsimam/priorityworkstealing)
- [Accelerating Real-Time Applications with Predictable Work-Stealing (PMC7343420)](https://pmc.ncbi.nlm.nih.gov/articles/PMC7343420/)

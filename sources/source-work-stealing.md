---
title: "Work Stealing 调度：从 Cilk 到 TBB 和 Rayon 的负载均衡艺术"
source_url: "https://www.cs.cmu.edu/~guyb/papers/BL99.pdf"
source_type: "paper"
author: "Blumofe, Leiserson"
date: "1999"
tags: ["hpc", "multithreading", "cpp", "work-stealing", "scheduling", "task-parallelism"]
keywords: ["work-stealing", "Cilk", "TBB", "Rayon", "Chase-Lev-deque", "task-DAG", "load-balancing"]
capture_date: "2026-07-01"
---

## 来源

- **原文论文**: [Blumofe & Leiserson — Scheduling Multithreaded Computations by Work Stealing](https://www.cs.cmu.edu/~guyb/papers/BL99.pdf)
- **补充**: [Chase-Lev Deque — Dynamic Circular Work-Stealing Deque](https://dl.acm.org/doi/10.1145/1073970.1073974)
- **补充**: [Intel TBB Documentation](https://spec.oneapi.io/oneapi-spec.pdf)
- **补充**: [Rust rayon — Data Parallelism](https://github.com/rayon-rs/rayon)
- **补充**: [Cilk Plus — The Cilkview Scalability Analyzer](https://www.cilkplus.org/)

## 摘要

Work Stealing（工作窃取）是动态负载均衡的核心理论之一，最早由 Blumofe 和 Leiserson 在 1999 年正式证明其最优性。核心机制：每个线程维护一个**双端队列（deque）**，线程在本地 deque 的**尾部（LIFO）** push/pop 自己的任务；当线程空闲时，从**随机选择的其他线程 deque 的头部（FIFO）** steal 一个任务。理论证明，在随机 steal 策略下，期望 steal 次数为 **O(T1/P + T∞)**，其中 T1 是串行工作量，P 是线程数，T∞ 是关键路径长度。

Chase-Lev 双端队列（2005）解决了动态数组扩展的 lock-free 问题：使用**原子操作的 tail 指针**和**非原子的 head 指针**组合，配合**环形缓冲区**和**拷贝迁移**策略，实现 owner 端的 wait-free 和 thief 端的 lock-free。Intel TBB 的 `task_arena` 和 `task_group`、Rust 的 rayon 库都基于 Chase-Lev deque。

对于 RTL 仿真，work stealing 的关键优势在于：不需要静态分区平衡，线程可以动态地从过载分区"窃取"事件门到欠载分区。这特别适合**稀疏计算**——不同时间步的活跃门数量差异巨大，静态分区会导致负载不均衡。

## 关键要点

1. **Chase-Lev Deque 的核心设计**:
   - Owner 线程 push/pop 在 **tail** 端（LIFO），使用 `std::atomic<size_t> tail` 的 `fetch_add`/`fetch_sub`。
   - Thief 线程 steal 在 **head** 端（FIFO），使用 CAS 竞争 `head` 指针的推进。
   - 当 `tail == head` 时 deque 为空；当 `tail - head == capacity` 时 deque 满，owner 负责扩容。
   - 扩容时，owner 先复制旧数据到新数组，再原子地更新 `head` 和 `tail`。

2. **理论保证**:
   - 期望执行时间：**O(T1/P + T∞)**。当线程数 P ≤ 并行度（T1/T∞）时，接近线性加速。
   - 期望通信量（steal 次数）：**O(P · T∞)**。关键路径越短，steal 次数越少。
   - 空间开销：**O(P · S∞)**，其中 S∞ 是单个串行执行栈的最大深度。

3. **随机 victim 选择**:
   ```cpp
   std::random_device rd;
   std::mt19937 gen(rd());
   std::uniform_int_distribution<> dist(0, num_threads - 1);
   int victim = dist(gen);
   while (victim == my_id) victim = dist(gen);  // 不 steal 自己
   ```
   随机选择避免了多个 thief 同时涌入同一个 victim 的"羊群效应"（herd effect）。

4. **TBB 的 task_arena**: TBB 将 work stealing 封装为高层 API。`tbb::parallel_for` 将迭代范围切分为小任务，放入 arena 的 task pool，线程自动 steal。`task_arena` 可以限制并发线程数，避免超线程竞争。

5. **Rayon 的 join 语义**: Rust 的 rayon 提供 `rayon::join(a, b)`，将两个任务分派到线程池，如果线程池空闲则直接串行执行（避免任务切分开销）。这是**自适应并行度**——只在有并行资源时才并行。

6. **Work stealing vs Work sharing**: Work sharing（如 OpenMP 的 `dynamic` schedule）由调度器将任务分配给线程，需要集中式协调。Work stealing 是分布式协调——线程只在空闲时才主动获取任务，没有集中式瓶颈。

## 对 RTL 仿真器多线程化的启示

**稀疏计算 RTL 仿真器的核心挑战**：不同时间步的活跃门数量差异巨大，静态分区无法保证负载均衡。例如时间步 100 可能有 10% 的门活跃，而时间步 101 有 90% 的门活跃。如果分区是静态的，某些线程在时间步 100 几乎空闲，而另一些线程过载。Work stealing 允许空闲线程从繁忙线程的 deque 中窃取未处理的事件门，实现动态负载均衡。

**具体应用建议**:

1. **每个线程维护一个本地事件 deque（Chase-Lev 风格）**：
   每个线程处理完自己的门后，如果事件触发了其他分区的门，将事件放入目标线程的 deque（push 到 tail）。目标线程从 tail pop 处理。如果目标线程的 deque 为空，就从随机选择的 victim 的 head steal：
   ```cpp
   class ChaseLevDeque {
       std::atomic<size_t> head{0};
       std::atomic<size_t> tail{0};
       std::vector<std::optional<Event>> buffer;  // 环形缓冲区，需动态扩容
       mutable std::mutex resize_mutex;  // 仅用于扩容
   public:
       void push(Event e);      // owner: tail++, relaxed store
       std::optional<Event> pop();   // owner: tail--, CAS
       std::optional<Event> steal(); // thief: CAS head++
   };
   ```
   实际实现可以参考 `folly::DynamicBoundedQueue` 或直接使用 TBB 的 `concurrent_queue`。

2. **初始任务分派使用静态分区，运行时动态均衡**：
   仿真开始时，按门级图的 METIS 划分将初始事件分配给各线程。运行中，如果线程 A 的 deque 长度超过阈值（如 2x 平均），主动将尾部的一半"迁移"到全局 deque；空闲线程从全局 deque 窃取。这减少了 steal 的随机搜索成本。

3. **Steal 的粒度控制**：
   RTL 仿真的事件处理粒度很小（一个门的逻辑求值可能只需几十 ns）。Steal 单个事件的开销（CAS + cache coherence）可能大于事件处理本身。应该**批量 steal**（一次窃取 64-256 个事件），或使用 TBB 的 `range.split` 语义将门级子图作为 steal 单位。

4. **避免跨 NUMA 节点的 steal**：
   Work stealing 的 victim 选择应该**优先同 NUMA 节点**。先从同节点的线程 steal，如果全部为空，再考虑跨节点。这减少了跨 NUMA 内存访问的 penalty。实现时维护一个 `numa_local_victims` 数组和 `numa_remote_victims` 数组。

5. **Critical path 门使用 dedicated 线程**：
   在 RTL 电路中，某些信号（如全局时钟、复位）是关键路径。如果这些门被 work stealing 到随机线程，会导致关键路径上的 sequential 依赖被分散，反而增加同步。关键路径上的门应该被固定到单个线程（或专用 fast-path），不参与 stealing。

6. **Work stealing 的退出条件**：
   RTL 仿真是时间步推进的，每个时间步需要全局同步（barrier）。Work stealing 只在单个时间步内有效。当一个时间步完成，所有线程在 barrier 处汇合，然后进入下一个时间步。这天然限制了 work stealing 的范围，避免了跨时间步的依赖混乱。

## 原文摘录

> "The expected running time of a multithreaded computation scheduled by work stealing is O(T1/P + T∞), where T1 is the work and T∞ is the critical path."
> — Blumofe & Leiserson, 1999

> "A work-stealing deque supports three operations: push and pop at the tail (by the owner) and steal at the head (by other threads). The owner operations are wait-free; the steal operation is lock-free."
> — Chase & Lev, 2005

> "Random victim selection ensures that the expected number of steal attempts is bounded and that multiple thieves do not simultaneously target the same victim."
> — Blumofe & Leiserson

> "Work stealing is more efficient than work sharing because it avoids the centralized bottleneck of a work-distributing scheduler."
> — Cilk documentation

## 相关链接

- [Blumofe & Leiserson 论文 (PDF)](https://www.cs.cmu.edu/~guyb/papers/BL99.pdf)
- [Chase-Lev Deque 论文](https://dl.acm.org/doi/10.1145/1073970.1073974)
- [Intel TBB Documentation](https://spec.oneapi.io/oneapi-spec.pdf)
- [Rust rayon GitHub](https://github.com/rayon-rs/rayon)
- [Cilk Plus](https://www.cilkplus.org/)
- [ folly::DynamicBoundedQueue](https://github.com/facebook/folly/blob/main/folly/concurrency/DynamicBoundedQueue.h)

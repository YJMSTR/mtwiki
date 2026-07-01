---
title: "C++ Lock-Free 数据结构：从原子操作到无锁队列"
source_url: "https://moodycamel.com/blog/2014/a-fast-general-purpose-lock-free-queue-for-c++"
source_type: "blog"
author: "Cameron (moodycamel)"
date: "2014-03-20"
tags: ["hpc", "multithreading", "cpp", "lock-free", "data-structures", "atomic"]
keywords: ["lock-free", "wait-free", "CAS", "compare-and-swap", "ABA-problem", "hazard-pointer", "moodycamel", "concurrent-queue"]
capture_date: "2026-07-01"
---

## 来源

- **原文**: [moodycamel — A fast general-purpose lock-free queue for C++](https://moodycamel.com/blog/2014/a-fast-general-purpose-lock-free-queue-for-c+++)
- **源码**: [moodycamel::ConcurrentQueue GitHub](https://github.com/cameron314/concurrentqueue)
- **补充**: [atomic_queue — Maxim Egorushkin](https://github.com/max0x7ba/atomic_queue)
- **补充**: [Hazard Pointers — Safe Memory Reclamation](https://citeseerx.ist.psu.edu/viewdoc/download?doi=10.1.1.59.3093&rep=rep1&type=pdf)
- **补充**: [preshing.com — Atomic Operations and Memory Ordering](https://preshing.com/20130922/acquire-and-release-fences/)

## 摘要

Lock-Free 数据结构通过原子操作（CAS — Compare-And-Swap）替代传统锁（mutex），避免线程在竞争时进入内核态睡眠，从而将"同步开销"从**数百纳秒（futex）**降低到**几十纳秒（原子指令）**。然而，无锁编程的核心挑战在于：

1. **ABA 问题**：CAS 检查的值从 A→B→A，线程误以为没有变化，导致数据结构不一致。
2. **内存安全回收**：当节点从队列中移除后，其他线程可能还在读取它，必须延迟回收（hazard pointer / epoch-based reclamation）。
3. **内存顺序语义**：`memory_order_relaxed` 最快但最弱，`memory_order_seq_cst` 最安全但最慢。无锁代码的每一条 `atomic` 操作都需要精确指定内存序。

moodycamel::ConcurrentQueue 是目前 C++ 社区中应用最广的无锁队列之一，它采用**基于 sub-queues 的批量分配策略**和**SPSC 核心 + MPMC 外层的混合架构**，在单生产者或单消费者场景下接近 wait-free 性能。benchmark 显示在 x86-64 上，其入队/出队延迟约为 15-30 ns，而 `std::mutex` + `std::queue` 的延迟约为 80-200 ns（竞争时）。

atomic_queue 是另一个更激进的选择：它使用**预分配环形缓冲区 + 原子头/尾指针**，实现**单生产者单消费者（SPSC）的 wait-free** 保证，且完全不分配内存。

## 关键要点

1. **CAS 循环是无锁代码的核心模式**:
   ```cpp
   T* expected = head.load(std::memory_order_relaxed);
   do {
       T* desired = expected->next;
   } while (!head.compare_exchange_weak(expected, desired,
                                          std::memory_order_release,
                                          std::memory_order_relaxed));
   ```
   `compare_exchange_weak` 在 spurious failure 时允许循环重试，比 `strong` 在循环中更高效（x86 上两者一样，ARM 上 weak 更优）。

2. **ABA 问题的解决方案**:
   - **Tagged pointers**: 给指针附加一个 64-bit 版本计数器，即使地址回绕，版本号也不会重复。x86-64 的 16-byte CAS（`cmpxchg16b`）天然支持。
   - **Hazard Pointers**: 每个线程在读取共享节点前，先将指针写入自己的 hazard list；回收线程检查所有 hazard list 后再安全释放。需要 3 倍活跃线程数的 slots。
   - **Epoch-Based Reclamation (EBR)**: 所有线程定期报告当前 epoch，回收节点时延迟到所有线程都经过至少一个 epoch。逻辑更简单，但延迟更大。

3. **moodycamel::ConcurrentQueue 的设计**:
   - 内部使用**小粒度 sub-queues**（每个 producer 一个 token），减少 MPMC 竞争。
   - 支持**批量入队/出队**（`enqueue_bulk`），将多元素的 CAS 合并为一次，摊薄原子操作成本。
   - 使用 `std::atomic` + `memory_order_acq_rel` 进行头尾指针更新，不使用内存屏障（fence）。

4. **atomic_queue 的设计**:
   - 预分配固定大小的环形缓冲区，禁止动态内存分配。
   - 使用 `alignas(64)` 的 atomic head/tail 指针，避免 false sharing。
   - 提供 `wait_free` 的 SPSC 变体，以及 `lock-free` 的 MPMC 变体。

5. **无锁不是银弹**：当竞争非常激烈（>8 线程同时读写同一队列）时，CAS 重试次数会指数增长，可能导致**比锁更差的性能**（称为 "lock-free contention collapse"）。此时应该使用**分片队列**（每个线程有独立队列，需要时 steal）而非单一 MPMC 队列。

## 对 RTL 仿真器多线程化的启示

**稀疏计算 RTL 仿真器的核心挑战**：同步开销大于并行收益。RTL 仿真的事件驱动模型天然会产生大量细粒度同步——每个门可能触发下游门的更新。如果每次事件传递都需要锁，那么锁竞争将成为绝对瓶颈。Lock-Free 队列可以将事件传递的延迟从**~100ns（mutex）**降到**~20ns（原子 CAS）**，且在高并发下不进入内核态。

**具体应用建议**:

1. **线程间事件队列使用无锁 SPSC 队列**：如果 RTL 仿真采用"每个线程负责一个门分区，分区间通过事件队列通信"的模型，那么每个通信方向都是 1:1 的——恰好适合 SPSC 无锁队列。atomic_queue 的 `AtomicQueue2` 是理想选择：
   ```cpp
   #include <atomic_queue/atomic_queue.h>
   using EventQueue = atomic_queue::AtomicQueue2<Event, 65536, true, true, false, false>;
   // 65536 slots, fixed size, single producer, single consumer
   ```

2. **跨分区事件队列数组**：如果线程 A 可能向线程 B 和 C 发送事件，为每个 (source, target) 对预分配一个 SPSC 队列，避免 MPMC 竞争。空间换时间是合理 trade-off。

3. ** hazard pointer 或 epoch 回收用于动态节点**：如果 RTL 仿真使用动态分配的门节点（例如 Verilog 的 generate 结构），且这些节点可能在仿真中创建/销毁，需要 hazard pointer 保护跨线程的节点指针访问。但如果门级结构是静态预分配的，则不需要——直接按缓存行对齐即可。

4. **避免在 hot path 使用 MPMC 无锁队列**：对于全局事件队列（如果有的话），不要直接用 `moodycamel::ConcurrentQueue` 的默认 MPMC 模式。应该为每个生产者申请一个 `ProducerToken`，将竞争降到 O(1) per-thread。

5. **用 tagged pointer 解决 ABA**：如果事件队列的节点需要动态分配/释放，使用 128-bit CAS（`atomic<__int128>`）或 Boost.Atomic 的 `atomic<T*>` + `tag` 结构。在 x86-64 上，64-bit 地址 + 64-bit 版本号的 `cmpxchg16b` 是安全的。

## 原文摘录

> "Lock-free programming is hard. But once you get it right, the performance benefits are substantial. In our tests, the queue sustains about 10M operations per second on a single core, and scales almost linearly with core count under low contention."
> — moodycamel blog

> "The ABA problem: thread A reads value V, thread B changes V to X and back to V, thread A's CAS succeeds despite the intermediate change. In a linked structure, this can lead to the reuse of a freed node."
> — preshing.com on ABA

> "Hazard pointers require O(H) space per thread, where H is the number of hazard pointers. Typically H=3 is sufficient for most lock-free data structures."
> — Maged Michael, Hazard Pointers paper

> "atomic_queue is a C++17 lock-free queue that uses preallocated circular buffer and does not perform any heap allocations. It is wait-free in SPSC case and lock-free in MPMC case."
> — atomic_queue README

## 相关链接

- [moodycamel::ConcurrentQueue GitHub](https://github.com/cameron314/concurrentqueue)
- [atomic_queue GitHub](https://github.com/max0x7ba/atomic_queue)
- [preshing.com — 无锁编程系列](https://preshing.com/20120612/an-introduction-to-lock-free-programming/)
- [C++ Reference — std::atomic_compare_exchange_weak](https://en.cppreference.com/w/cpp/atomic/atomic_compare_exchange_weak)
- [Hazard Pointers 论文 (Maged Michael)](https://citeseerx.ist.psu.edu/viewdoc/download?doi=10.1.1.59.3093&rep=rep1&type=pdf)

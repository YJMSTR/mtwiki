---
title: "C++ 内存模型与 Atomic 操作：从 happens-before 到 acquire-release"
source_url: "https://en.cppreference.com/w/cpp/atomic/memory_order"
source_type: "doc"
author: "cppreference.com"
date: ""
tags: ["hpc", "multithreading", "cpp", "memory-model", "atomic", "happens-before"]
keywords: ["memory-order", "acquire-release", "seq-cst", "relaxed", "happens-before", "synchronizes-with", "fences"]
capture_date: "2026-07-01"
---

## 来源

- **原文**: [cppreference — std::memory_order](https://en.cppreference.com/w/cpp/atomic/memory_order)
- **补充**: [preshing.com — Memory Ordering at Compile Time](https://preshing.com/20120625/memory-ordering-at-compile-time/)
- **补充**: [preshing.com — Acquire and Release Fences](https://preshing.com/20130922/acquire-and-release-fences/)
- **补充**: [Bartosz Milewski — C++11 Memory Model](https://bartoszmilewski.com/2008/12/01/c-atomics-and-memory-ordering/)
- **补充**: [Hans Boehm — Threads Cannot Be Implemented As a Library](https://www.hpl.hp.com/techreports/2004/HPL-2004-209.pdf)

## 摘要

C++11 引入的内存模型是多线程编程的正式语义基础。它将 `std::atomic` 操作的内存序分为 6 个等级，从最强到最弱依次为：`memory_order_seq_cst` → `acquire`/`release` → `consume`（已弃用） → `relaxed`。理解这些语义的关键是建立两个概念：

- **Happens-before**：如果操作 A happens-before 操作 B，那么 A 的副作用在 B 执行时可见。
- **Synchronizes-with**：如果线程 T1 的 release store 与线程 T2 的 acquire load 操作同一原子变量，且 T2 读取到了 T1 写入的值，则两者 synchronizes-with，进而建立跨线程的 happens-before 关系。

在 x86-64 上，所有原子操作（即使是 `relaxed`）默认具有 `acquire-release` 的硬件保证（因为 x86 是 TSO — Total Store Order），所以 `relaxed` 和 `acquire/release` 在 x86 上的性能差异很小。但在 ARM/PowerPC 上，性能差异巨大：`relaxed` 可以比 `seq_cst` 快 5-10 倍。

Fence（`std::atomic_thread_fence`）是比原子操作更底层的同步原语。Acquire fence 阻止其后的读写被重排到 fence 之前；Release fence 阻止其前的读写被重排到 fence 之后。Fence 可以用于保护非原子变量的可见性，而不仅限于原子变量。

## 关键要点

1. **六种内存序**:
   - `memory_order_relaxed`: 只保证原子性，不保证顺序。用于单纯的计数器（如统计引用计数，不依赖顺序）。
   - `memory_order_consume`: 与 acquire 类似，但只对依赖链传播。C++17 已弃用，不推荐使用。
   - `memory_order_acquire`: 该 load 之后的所有读写不能被重排到该 load 之前。用于读取"信号"变量时。
   - `memory_order_release`: 该 store 之前的所有读写不能被重排到该 store 之后。用于写入"信号"变量时。
   - `memory_order_acq_rel`: 同时具有 acquire 和 release 语义。用于 read-modify-write 操作（如 CAS）。
   - `memory_order_seq_cst`: 最强，所有 seq_cst 操作在全局有一个统一顺序。这是默认行为，但性能最差（在弱序架构上需要 full barrier）。

2. **Acquire-Release 的经典用法**:
   ```cpp
   std::atomic<bool> ready{false};
   int data = 0;
   
   // Thread 1
   data = 42;
   ready.store(true, std::memory_order_release);  // release: data=42 必须先完成
   
   // Thread 2
   while (!ready.load(std::memory_order_acquire)) ;  // acquire: 保证看到 data=42
   assert(data == 42);  // 安全，不会触发
   ```
   这里的 `ready` 是一个**同步点（synchronization point）**。Release store 到 acquire load 的配对建立了 happens-before，使得 `data` 的写对 Thread 2 可见。

3. **Fence 的用途**:
   ```cpp
   // Thread 1
   data = 42;
   std::atomic_thread_fence(std::memory_order_release);
   ready.store(true, std::memory_order_relaxed);
   
   // Thread 2
   while (!ready.load(std::memory_order_relaxed)) ;
   std::atomic_thread_fence(std::memory_order_acquire);
   assert(data == 42);
   ```
   Fence 允许将 acquire/release 语义从原子变量"剥离"到非原子操作群上。这在批量数据同步中很有用——一批变量更新完成后，一次 fence + 一个 relaxed 标志位即可。

4. **平台差异**:
   - x86-64: Store 是 `release` 语义，Load 是 `acquire` 语义。所以 `relaxed` load/store 的性能几乎与 `acquire/release` 相同。只有 `seq_cst` 需要额外的 `lock` prefix（变成全序）。
   - ARM64: Load 和 Store 默认是 `relaxed`。`acquire` 需要 `ldar`，`release` 需要 `stlr`，`seq_cst` 需要 `dmb ish`。性能差异显著。
   - 如果目标平台确定是 x86-64，可以大胆使用 `relaxed` 来减少代码复杂度；如果代码需要跨平台（包括 ARM），则必须精确使用 `acquire/release`。

5. **常见错误**:
   - 对非原子变量使用 data race（两个线程同时读写，至少一个写），这是**未定义行为**，即使结果看起来正确。
   - 使用 `relaxed` 来同步标志位，认为"x86 上没问题"。这是不可移植的，而且编译器优化可能重排代码。
   - 忘记 fence 在批量数据同步中的作用，导致每个变量都用原子操作，浪费性能。

## 对 RTL 仿真器多线程化的启示

**稀疏计算 RTL 仿真器的核心挑战**：线程间需要同步"分区完成"、"事件就绪"、"新时间步"等信号。如果每个信号都用 `std::mutex` 或 `std::condition_variable`，每次同步都会触发系统调用，开销巨大。使用 `std::atomic` + 精确内存序，可以将这些轻量同步的延迟从**~100ns（mutex）**降到**~5-10ns（原子操作）**。

**具体应用建议**:

1. **时间步屏障（Time-step barrier）使用原子计数器 + acquire-release**：
   每个线程完成当前时间步的门级仿真后，对一个原子计数器做 `fetch_add(1, acq_rel)`。主线程等待计数器达到线程数。这比 `std::barrier`（C++20）更轻量，因为不需要内核同步：
   ```cpp
   std::atomic<size_t> completed_threads{0};
   
   // Worker thread
   simulate_partition(partition_id);
   completed_threads.fetch_add(1, std::memory_order_acq_rel);
   
   // Main thread
   while (completed_threads.load(std::memory_order_acquire) < num_threads) {
       _mm_pause();  // 自旋等待，避免总线风暴
   }
   // 所有线程完成，安全读取各分区结果
   ```
   注意：如果线程数很多（>核心数），自旋会浪费 CPU，此时应该使用 `std::atomic` + `std::condition_variable` 的混合策略，或直接使用 `std::latch`（C++20）。

2. **分区事件就绪标志使用 acquire-release 配对**：
   当线程 A 向线程 B 的事件队列写入一批事件后，设置一个原子标志：
   ```cpp
   std::atomic<bool> has_events{false};
   
   // Thread A (producer)
   queue.push_bulk(events);
   has_events.store(true, std::memory_order_release);
   
   // Thread B (consumer)
   if (has_events.load(std::memory_order_acquire)) {
       process_events();
       has_events.store(false, std::memory_order_release);
   }
   ```
   这里的 `has_events` 是一个**同步点**，保证 `process_events()` 能看到所有已入队的事件。

3. **批量数据同步使用 Fence + Relaxed 标志位**：
   如果每个时间步需要同步一个完整的"门状态快照"（例如所有 D 触发器的输出），不要用原子数组。用普通数组 + fence：
   ```cpp
   // Thread A 写入共享快照
   for (size_t i = 0; i < num_gates; ++i) {
       shared_state[i] = local_state[i];  // 普通写
   }
   std::atomic_thread_fence(std::memory_order_release);
   version.store(version.load() + 1, std::memory_order_relaxed);  // 仅标志位
   ```
   这比每个元素都用 `atomic` 快得多，因为普通写可以批量提交，而 fence 只保证顺序不保证可见性（由 version 的 acquire 来保证）。

4. **谨慎使用 `memory_order_relaxed`**：
   在 x86-64 上，用于纯统计性质的计数器（如"已仿真门数"、"已处理事件数"）可以用 `relaxed`。但任何用于逻辑同步的变量都必须至少使用 `acquire/release`。不要因为"x86 上 relaxed 和 acquire 一样快"就滥用 relaxed——代码可能在 ARM 服务器上编译运行。

5. **避免 `seq_cst` 除非必要**：
   `seq_cst` 是最安全的默认，但在大多数 RTL 仿真场景中，只需要一个同步点（如时间步完成标志），`acquire/release` 已经足够。`seq_cst` 的"全局顺序"语义在 x86 上需要 `lock` prefix，在 ARM 上需要 `dmb`，都更慢。

## 原文摘录

> "memory_order_release: A store operation with this memory order performs the release operation: no reads or writes in the current thread can be reordered after this store."
> — cppreference

> "If an atomic store in thread A is tagged memory_order_release and an atomic load in thread B from the same variable is tagged memory_order_acquire, all memory writes (non-atomic and relaxed atomic) that happened-before the atomic store from the point of view of thread A, become visible side-effects in thread B."
> — cppreference

> "On x86, any store has release semantics and any load has acquire semantics. So on x86, relaxed operations are essentially free. But on ARM, you pay for acquire and release."
> — preshing.com

> "Data races on non-atomic objects are undefined behavior in C++. The compiler is allowed to assume that no data races exist and optimize accordingly."
> — Hans Boehm

## 相关链接

- [cppreference — std::memory_order](https://en.cppreference.com/w/cpp/atomic/memory_order)
- [preshing.com — 无锁编程系列](https://preshing.com/20120612/an-introduction-to-lock-free-programming/)
- [preshing.com — Memory Barriers Are Like Source Control Operations](https://preshing.com/20120710/memory-barriers-are-like-source-control-operations/)
- [Bartosz Milewski — C++ Atomics and Memory Ordering](https://bartoszmilewski.com/2008/12/01/c-atomics-and-memory-ordering/)
- [Hans Boehm — Threads Cannot Be Implemented As a Library](https://www.hpl.hp.com/techreports/2004/HPL-2004-209.pdf)

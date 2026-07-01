---
title: "Thread-Local Storage 最佳实践：从 thread_local 到 per-thread allocator"
source_url: "https://maskray.me/blog/2021-02-14-all-about-thread-local-storage"
source_type: "blog"
author: "MaskRay"
date: "2021-02-14"
tags: ["hpc", "multithreading", "cpp", "thread-local", "tls", "memory-allocation", "performance"]
keywords: ["thread-local", "tls", "tcmalloc", "jemalloc", "per-thread-cache", "constinit", "tls-model"]
capture_date: "2026-07-01"
---

## 来源

- **原文**: [MaskRay — All about Thread-Local Storage](https://maskray.me/blog/2021-02-14-all-about-thread-local-storage)
- **补充**: [Google TCMalloc — Thread-Caching Malloc](https://google.github.io/tcmalloc/design.html)
- **补充**: [jemalloc — Thread-Local Storage](https://jemalloc.net/jemalloc.3.html)
- **补充**: [cppreference — thread_local](https://en.cppreference.com/w/cpp/language/storage_duration)
- **补充**: [GCC — TLS Model](https://gcc.gnu.org/onlinedocs/gcc/Thread-Local.html)

## 摘要

Thread-Local Storage（TLS）为每个线程提供独立的变量副本，是消除线程间数据竞争的最简单方法。但 TLS 的性能并非零成本——它取决于编译器选择的 TLS model：

- **Local-exec**: 最快，只需 2 条指令（x86-64: `mov %fs:offset, %reg`）。适用于可执行文件中的非抢占符号。
- **Initial-exec**: 稍慢，需要 3 条指令（加载 GOT 表项 + 间接访问）。适用于可执行文件或启动时加载的共享库。
- **General-dynamic**: 最慢，需要调用 `__tls_get_addr`，可能涉及动态分配和线程列表锁。适用于 `dlopen` 的共享库。

C++11 `thread_local` 增加了动态初始化（构造函数在首次使用时执行）和线程退出析构，这比 GCC 的 `__thread` 更灵活但开销更大。C++20 `constinit` 可以强制编译期初始化，使 `thread_local` 达到 `__thread` 的性能。

TCMalloc 和 jemalloc 是 TLS 在内存分配中的最佳实践代表。它们为每个线程（或每个 CPU）维护一个本地缓存，小对象分配完全不需要锁。TCMalloc 的 per-thread cache 使用 restartable sequences（rseq）实现无锁的 per-CPU 模式，在 Linux 上达到接近零开销的分配。

## 关键要点

1. **TLS Model 的性能层级**:
   ```cpp
   // Local-exec (executable, non-preemptible): 2 instructions
   _Thread_local int x;  // x86-64: movl %fs:x@TPOFF, %eax
   
   // Initial-exec (executable, preemptible): 3 instructions
   extern thread_local int y;  // x86-64: movq y@GOTTPOFF(%rip), %rax; movl %fs:(%rax), %eax
   
   // General-dynamic (shared object): function call + potential allocation
   // x86-64: leaq y@tlsgd(%rip), %rdi; call __tls_get_addr@PLT; movl (%rax), %eax
   ```
   使用 `-ftls-model=initial-exec` 编译器标志可以强制使用更快的 initial-exec model，前提是所有 TLS 符号在启动时已知。

2. **C++ thread_local vs __thread**:
   - `__thread`（GCC 扩展）：只支持 POD，无构造函数/析构函数，性能等同于最快的 TLS model。
   - `thread_local`（C++11）：支持动态初始化、析构、`constinit` 强制编译期初始化。如果变量有非平凡构造函数，`thread_local` 首次访问会触发 TLS wrapper 函数（`_ZTW*`），可能增加一次函数调用开销。

3. **C++20 constinit 优化**:
   ```cpp
   // 有动态初始化：首次访问时调用 _ZTWx + __tls_init
   thread_local std::vector<int> buf;
   
   // 编译期初始化：无 wrapper 开销，直接 local-exec
   constinit thread_local int counter = 0;
   ```

4. **TCMalloc 的 per-thread/per-CPU 缓存**:
   - 每个线程（或每个逻辑 CPU）有一个独立的缓存数组，按 size-class 分桶。
   - 分配：从本地缓存的链表头部弹出一个对象，无需锁。O(1)。
   - 释放：将对象压入本地缓存的链表头部。O(1)。
   - 本地缓存耗尽时，从中间层（CentralFreeList/TransferCache）批量获取一批对象。批量操作摊薄了锁竞争。
   - TCMalloc 的 per-CPU 模式使用 Linux rseq（restartable sequence），确保分配/释放操作在不被中断的情况下完成，无需原子操作。

5. **jemalloc 的 tcache（thread cache）**:
   - 每个线程有一个 `tcache_t`，缓存按 size-class 组织的对象。
   - 默认缓存 512 个对象 per size-class per thread。
   - 使用 `pthread_setspecific` 或 `__thread` 存储 tcache 指针，分配时直接访问本地 cache，无需锁。

6. **TLS 的隐性成本**:
   - 如果 `thread_local` 变量在循环内频繁访问，编译器通常能将其缓存到寄存器，消除重复加载。
   - 但在函数调用边界，如果编译器无法证明变量未被修改，可能每次重新加载 `%fs` 基址。将热 TLS 变量缓存到局部变量可以消除这个开销。
   - 大量 `thread_local` 变量会增加每个线程的 TLS 块大小，可能超出 glibc 的静态 TLS 预留空间（默认 ~1MB），导致 `dlopen` 失败。

## 对 RTL 仿真器多线程化的启示

**稀疏计算 RTL 仿真器的核心挑战**：每个线程处理一批门的事件。事件处理过程中需要频繁的临时分配（事件对象、输出列表、求值中间结果）。如果所有线程共享同一个 `malloc` arena，每次分配都会触发锁竞争，成为瓶颈。使用 per-thread 分配器可以将分配延迟从**~50-200ns（带锁）**降到**~5-10ns（无锁本地缓存）**。

**具体应用建议**:

1. **每个线程维护一个事件池（TLS + 内存池）**：
   ```cpp
   struct EventPool {
       std::vector<Event> free_list;
       std::vector<Event> allocated;  // 预分配，避免动态分配
   };
   
   thread_local EventPool* g_event_pool = nullptr;
   
   Event* alloc_event() {
       if (!g_event_pool) {
           g_event_pool = new EventPool();
           g_event_pool->allocated.reserve(4096);
       }
       if (g_event_pool->free_list.empty()) {
           // 批量从中间层获取
           return &g_event_pool->allocated.emplace_back();
       }
       Event* e = &g_event_pool->free_list.back();
       g_event_pool->free_list.pop_back();
       return e;
   }
   
   void free_event(Event* e) {
       g_event_pool->free_list.push_back(*e);  // 压入本地缓存
   }
   ```
   注意：这里的 `thread_local` 指针本身没有构造函数开销，是编译期初始化的（local-exec model）。

2. **使用 tcmalloc/jemalloc 替代系统 malloc**：
   如果 RTL 仿真器使用标准 `new`/`delete` 分配事件对象，直接链接 `-ltcmalloc` 或 `-ljemalloc` 即可获得 per-thread cache。对于小对象（<32KB），TCMalloc 的分配几乎零竞争。使用 `MallocExtension::SetMaxPerCpuCacheSize(256 * 1024)` 调整缓存大小。

3. **per-thread 门状态缓冲区**：
   每个线程在求值门时，可能需要临时存储输入值。使用 `thread_local` 数组避免堆分配：
   ```cpp
   constinit thread_local uint64_t input_buffer[64];  // 假设最大输入扇入为 64
   
   void evaluate_gate(uint32_t gate_idx) {
       uint32_t n = input_count[gate_idx];
       for (uint32_t i = 0; i < n; ++i) {
           input_buffer[i] = values[input_edges[input_start[gate_idx] + i]];
       }
       // 用 input_buffer 求值逻辑
   }
   ```
   `constinit` 确保无动态初始化开销，数组在 TLS 段中直接分配。

4. **避免 thread_local 在 hot loop 中直接访问**：
   如果 `thread_local` 变量在循环中被频繁修改，编译器可能无法优化掉 `%fs` 基址加载。将其缓存到局部变量：
   ```cpp
   // 低效：每次循环都重新加载 thread_local 地址
   for (...) {
       thread_local_stats.event_count++;
   }
   
   // 高效：缓存到局部变量，循环结束后写回
   uint64_t local_count = thread_local_stats.event_count;
   for (...) {
       local_count++;
   }
   thread_local_stats.event_count = local_count;
   ```

5. **per-thread 输出事件队列**：
   每个线程处理完门后，产生的输出事件先写入本地 `thread_local` 队列。当本地队列满或时间步结束时，批量提交到目标线程的全局队列。这避免了每个事件都触发一次跨线程同步。
   ```cpp
   constinit thread_local Event local_output_buffer[256];
   constinit thread_local size_t local_output_count = 0;
   
   void emit_event(Event e) {
       local_output_buffer[local_output_count++] = e;
       if (local_output_count == 256) {
           flush_local_outputs();  // 批量提交
       }
   }
   ```

6. **TLS 大小控制**：
   如果 RTL 仿真器有大量 `thread_local` 变量（如每个线程的完整门状态副本），注意总 TLS 大小。glibc 的静态 TLS 空间有限（默认约 1MB 减去线程控制块）。如果超过，考虑使用 `__thread` 而非 `thread_local`（减少 TLS 管理开销），或将大数据显式分配到线程堆（`pthread_create` 时传递参数）而非 TLS 段。

7. **jemalloc/tcmalloc 的 NUMA 感知**：
   TCMalloc 的 per-CPU 模式天然 NUMA 友好——每个逻辑 CPU 的缓存只使用本地节点的内存。如果使用 per-thread 模式，确保线程绑定到 NUMA 节点，这样线程缓存的内存也在本地节点上。

## 原文摘录

> "Local-exec TLS model is the most efficient. It applies when the TLS symbol is defined in the executable. The compiler picks this model in -fno-pic/-fpie modes. On x86-64, the instruction is just movl %fs:offset, %eax."
> — MaskRay

> "C++ thread_local adds dynamic initialization before first-use and destruction on thread exit. If you know x does not need dynamic initialization, C++20 constinit can make it as efficient as the plain old __thread."
> — MaskRay

> "TCMalloc's front-end is a cache that provides fast allocation and deallocation of memory to the application. This cache is only accessible by a single thread at a time, so it does not require any locks."
> — Google TCMalloc Design

> "In per-CPU mode, TCMalloc will reserve a slab of memory per-CPU (typically 256 KiB). To avoid holding memory on CPUs where the application no longer runs, MallocExtension::ReleaseCpuMemory frees objects held in a specified CPU's caches."
> — Google TCMalloc Design

## 相关链接

- [MaskRay — All about Thread-Local Storage](https://maskray.me/blog/2021-02-14-all-about-thread-local-storage)
- [Google TCMalloc Design](https://google.github.io/tcmalloc/design.html)
- [jemalloc Documentation](https://jemalloc.net/jemalloc.3.html)
- [cppreference — thread_local](https://en.cppreference.com/w/cpp/language/storage_duration)
- [GCC TLS Model](https://gcc.gnu.org/onlinedocs/gcc/Thread-Local.html)
- [Linux rseq (restartable sequences) man page](https://man7.org/linux/man-pages/man2/rseq.2.html)

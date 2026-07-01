---
title: 零拷贝 / 无锁事件传递：SPSC/MPMC 队列、Disruptor 与并发事件通道
description: 梳理 RTL 仿真器多线程化中事件传递的零拷贝与无锁方案，涵盖 moodycamel::ConcurrentQueue、atomic_queue、LMAX Disruptor 模式及其 C++ 移植，提供性能基准与选型建议。
source_url: "https://github.com/cameron314/concurrentqueue"
source_type: "github"  # github-pr, github-issue, blog, doc, paper, competition
author: "Cameron (moodycamel) / Maxim Egorushkin (atomic_queue) / LMAX / hangukquant"
date: "2014-2025"
tags: ["lock-free", "event-queue", "spsc", "mpmc", "disruptor", "zero-copy", "concurrent-queue"]
keywords: ["lock-free event queue simulation", "SPSC event queue", "moodycamel concurrentqueue", "disruptor pattern event passing"]
capture_date: "2025-07-02"
---

# 零拷贝 / 无锁事件传递：SPSC/MPMC 队列、Disruptor 与并发事件通道

## 来源

- **URL**: 
  - https://github.com/cameron314/concurrentqueue
  - https://max0x7ba.github.io/atomic_queue/
  - https://github.com/hangukquant/disruptor_cpp/
  - https://github.com/bytemaster/disruptor
  - https://lmax-exchange.github.io/disruptor/user-guide/index.html
- **类型**: github / doc
- **作者**: Cameron, Maxim Egorushkin, LMAX Team, hangukquant, bytemaster
- **日期**: 2014-2025

## 摘要

在 MT-RTL 仿真器中，事件传递的延迟直接决定并行加速比。当多个工作线程（Worker）需要向调度线程（Scheduler）或跨 LP 传递事件时，传统 `std::mutex` + `std::queue` 会成为严重瓶颈。无锁（lock-free）与零拷贝（zero-copy）技术通过原子操作和预分配环形缓冲区将线程间通信延迟压到纳秒级。`moodycamel::ConcurrentQueue` 以 SPSC 子队列模拟 MPMC，支持 bulk 操作；`atomic_queue` 采用极简环形数组，将 round-trip 延迟压至 **<100 ns**；LMAX Disruptor 则通过 Sequence Barrier + Ring Buffer 实现单线程写、多线程读的极致吞吐。本文对比三者实现原理、API 与性能，并给出 RTL 仿真器事件通道的集成建议。

## 关键要点

- **moodycamel::ConcurrentQueue**：工业级无锁 MPMC 队列，单头文件。内部由若干 SPSC 子队列组成，每个生产者绑定一个子队列；消费者轮询所有子队列。非线性化、非 NUMA 感知，但 bulk 操作极快。
- **atomic_queue**：极致极简主义，固定大小环形数组，无堆分配（构造后）。使用最少量原子指令，`push`/`pop` 可内联。支持 SPSC 模式（无昂贵 RMW，仅有原子 load/store）。在 x86-64 上 round-trip 可低于 100 ns。
- **LMAX Disruptor**：基于预分配 Ring Buffer 的 lock-free 事件通道。核心抽象：Ring Buffer（存储）、Sequence（原子序号）、Sequencer（单/多生产者算法）、Sequence Barrier（消费者依赖图）、Wait Strategy（忙等/阻塞/混合）。C++20 移植如 `disruptor_cpp` 实现了与 Java 版等价的语义。
- **零拷贝核心**：事件对象预先分配在 Ring Buffer 中，生产者仅通过 `memcpy` 或字段赋值写入，不触发 `new/delete`。这对于 RTL 仿真中高频、小体积的事件（如 `Event{timestamp, target_id, value}`）至关重要。
- **缓存行对齐**：`atomic_queue` 和 Disruptor 均对 Sequence 和队列元素做缓存行对齐（padding），避免 false sharing，是多核吞吐的关键。

## 对 RTL 仿真器多线程化的启示

1. **调度线程 ↔ 工作线程的事件分发**：
   - 若采用 **1 调度线程 + N 工作线程** 模型，可使用 **moodycamel::ConcurrentQueue** 或 **atomic_queue** 作为全局就绪事件队列。
   - 若每个工作线程有独立输出通道（1P1C），优先使用 **SPSC 队列**（如 `boost::lockfree::spsc_queue` 或 `atomic_queue` 的 SPSC 模式），速度最快、无锁竞争。

2. **跨 LP 的消息传递（PDES）**：
   - 在保守式 PDES 中，LP 间消息具有方向性，天然适合 **SPSC 队列**。每对 LP 建立一条无锁通道，避免全局 MPMC 队列的序号竞争。
   - Disruptor 的 **Sequence Barrier** 可建模复杂依赖图（如 diamond 拓扑），适合多级流水线式仿真（前端 → 执行 → 写回）。

3. **批量事件处理**：
   - RTL 仿真中事件往往「突发」：一个时钟沿触发数百个模块更新。`moodycamel::ConcurrentQueue` 的 `enqueue_bulk`/`try_dequeue_bulk` 和 Disruptor 的 batch read/write 能显著降低每事件 overhead。

4. **内存预分配**：
   - 仿真启动时预分配事件队列容量，运行期禁止 `new`。`try_enqueue` 在预分配失败时返回 false，可作为反压（backpressure）信号，提示调度线程应减缓推进或扩展队列。

5. **缓存与 NUMA 考量**：
   - `atomic_queue` 的 cache-line-swap 优化（将元素索引与缓存行索引交换）可显著降低多生产者竞争。对于跨 Socket 的 NUMA 架构，仍需尽量保证生产者-消费者在同 NUMA 节点内通信。

## 代码示例

### 1. moodycamel::ConcurrentQueue — 显式 Token + Bulk 操作

```cpp
#include "concurrentqueue.h"

struct SimEvent {
    uint64_t timestamp;
    uint32_t target_id;
    uint32_t value;
};

moodycamel::ConcurrentQueue<SimEvent> g_event_queue;

// 生产者线程
void producer_thread() {
    moodycamel::ProducerToken ptok(g_event_queue);
    SimEvent batch[64];
    for (int i = 0; i < 64; ++i) {
        batch[i] = SimEvent{/* ... */};
    }
    g_event_queue.enqueue_bulk(ptok, batch, 64);  // 批量入队
}

// 消费者线程（调度器）
void scheduler_thread() {
    moodycamel::ConsumerToken ctok(g_event_queue);
    SimEvent evs[64];
    size_t n = g_event_queue.try_dequeue_bulk(ctok, evs, 64);
    for (size_t i = 0; i < n; ++i) {
        process(evs[i]);
    }
}
```

### 2. atomic_queue — 极简 SPSC 低延迟通道

```cpp
#include <atomic_queue/atomic_queue.h>

using Queue = atomic_queue::AtomicQueueB2<
    SimEvent,       // 元素类型
    std::allocator<SimEvent>,
    1024            // 容量（运行期固定）
>;

Queue q(1024);

// 生产者（单线程）
void produce(const SimEvent& e) {
    q.push(e);  // 忙等直到有空间；若需非阻塞，用 try_push
}

// 消费者（单线程）
SimEvent consume() {
    return q.pop();  // 忙等直到有数据
}
```

> `AtomicQueueB2` 使用 `std::allocator` 分配固定环形数组，无后续堆操作。若元素为 `std::unique_ptr`，支持 move-only 类型。

### 3. LMAX Disruptor C++20 移植（disruptor_cpp）

```cpp
#include <disruptor/disruptor.hpp>

struct MarketEvent {
    uint64_t sequence;
    double   price;
};

constexpr size_t RING_SIZE = 1024;

disruptor::RingBuffer<MarketEvent, RING_SIZE> ring_buffer;

// 单生产者发布
void publish_event(double price) {
    auto seq = ring_buffer.next();
    try {
        auto& ev = ring_buffer[seq];
        ev.price = price;
    } catch (...) {
        ring_buffer.set_available(seq); // 异常回滚
        throw;
    }
    ring_buffer.publish(seq);
}

// 消费者通过 Sequence Barrier 等待
void consumer_loop() {
    int64_t next_seq = 0;
    while (running) {
        int64_t available = barrier->wait_for(next_seq);
        for (; next_seq <= available; ++next_seq) {
            process(ring_buffer[next_seq]);
        }
    }
}
```

### 4. SPSC 无锁队列（核心原理，简化版）

```cpp
#include <atomic>
#include <array>
#include <optional>

template<typename T, size_t N>
class SPSCQueue {
    static_assert((N & (N - 1)) == 0, "N must be power of 2");
    std::array<T, N> buffer;
    alignas(64) std::atomic<size_t> head{0};
    alignas(64) std::atomic<size_t> tail{0};

public:
    bool try_push(const T& item) {
        size_t h = head.load(std::memory_order_relaxed);
        size_t next = (h + 1) & (N - 1);
        if (next == tail.load(std::memory_order_acquire)) return false; // full
        buffer[h] = item;
        head.store(next, std::memory_order_release);
        return true;
    }

    std::optional<T> try_pop() {
        size_t t = tail.load(std::memory_order_relaxed);
        if (t == head.load(std::memory_order_acquire)) return std::nullopt; // empty
        T item = buffer[t];
        tail.store((t + 1) & (N - 1), std::memory_order_release);
        return item;
    }
};
```

## 性能数据

### atomic_queue 延迟基准（Ping-Pong 往返，2 线程，x86-64）

| 队列类型 | 同核 SMT 延迟 | 跨核延迟 | 备注 |
|---------|-------------|---------|------|
| `std::mutex` + `std::queue` | ~300–500 ns | ~500–800 ns | 基准对比 |
| `pthread_spinlock` | ~150–250 ns | ~250–400 ns | 自旋锁 |
| `moodycamel::ConcurrentQueue` | ~200 ns | ~350 ns | 1P1C 下较慢，高并发下扩展性好 |
| `moodycamel::ReaderWriterQueue` | ~80 ns | ~150 ns | SPSC 专用 |
| `atomic_queue::AtomicQueue` | **~50 ns** | **~90 ns** | 极简原子队列 |
| `atomic_queue::OptimistAtomicQueue` | **~40 ns** | **~80 ns** | 乐观忙等模式 |

> 来源：atomic_queue 官方基准（Ryzen 5950X, Linux, `SCHED_FIFO`, 1GB huge pages）。
> 关键结论：跨核通信延迟是同核 SMT 的 **3× 以上**，线程绑核（pinning）对 RTL 仿真器至关重要。

### moodycamel::ConcurrentQueue 吞吐量基准（MPMC, 1,000,000 消息）

- 单线程 `enqueue` + `dequeue`：接近非并发队列速度。
- bulk 操作 `enqueue_bulk`/`try_dequeue_bulk`：在重度竞争下仍能保持线性扩展，multi-producer 场景优于 Boost.Lockfree 和 Intel TBB。
- 非线性化警告：若两生产者间有额外同步，元素出队顺序不保证与全局入队顺序一致；但单生产者内部顺序稳定。

### Disruptor 性能（Java 原版 & C++ 移植）

- LMAX 官方：Disruptor 在 Java 上实现 **600万 订单/秒** 的吞吐量，延迟 **<1 μs**（P99）。
- C++ 移植（bytemaster/disruptor）：线程间事件投递比 `fc::thread` 快 **30×**，且支持 progressive-backoff（忙等→yield→睡眠）。
- FPGA 交易系统实测（XDP + Disruptor）：平均 IPC 延迟 **0.10 μs**（100 ns），P99 **0.29 μs**。

### 2025 论文：CMP 协调无关队列（Coordination-Free）

- 在 64P64C 极端竞争下，CMP 队列达到 **1.19M items/sec**，较 Boost 提升 **325%**，较 moodycamel 提升 **892%**。
- 在 8P8C 合成负载下，CMP 保持 **92%** 基线吞吐，moodycamel 仅 **76.9%**。
- 说明：纯学术实现，但验证了「消除生产者-消费者间同步」是极致吞吐的正确方向。

## 原文摘录

> "Knock-your-socks-off blazing fast performance. Single-header implementation. Fully thread-safe lock-free queue."
> —— moodycamel::ConcurrentQueue

> "Designed with a goal to minimize the latency between one thread pushing an element into a queue and another thread popping it from the queue."
> —— atomic_queue

> "The fastest synchronization of all is the kind that never takes place. Fundamentally, concurrent data structures require some synchronization, and that takes time. Every effort was made, of course, to minimize the overhead, but if you can avoid sharing data between threads, do so!"
> —— moodycamel::ConcurrentQueue, *Reasons not to use*

> "A lightweight, header-only C++ port of the LMAX Disruptor (v3) pattern for high-performance, lock-free event processing."
> —— hangukquant/disruptor_cpp

> "Progressive-backoff blocking. When one cursor needs to wait on another it starts out with a busy wait, followed by a yield, and ultimately falls back to sleeping wait if the queue is stalled."
> —— bytemaster/disruptor

## 相关链接

- [moodycamel::ConcurrentQueue](https://github.com/cameron314/concurrentqueue)
- [moodycamel::ReaderWriterQueue (SPSC)](https://github.com/cameron314/readerwriterqueue)
- [atomic_queue](https://max0x7ba.github.io/atomic_queue/)
- [disruptor_cpp – C++20 Disruptor 移植](https://github.com/hangukquant/disruptor_cpp/)
- [bytemaster/disruptor – C++ Disruptor 变体](https://github.com/bytemaster/disruptor)
- [LMAX Disruptor User Guide](https://lmax-exchange.github.io/disruptor/user-guide/index.html)
- [2025 论文: Coordination-Free Concurrent Lock-Free Queues](https://arxiv.org/html/2511.09410v1)

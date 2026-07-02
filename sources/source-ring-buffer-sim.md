---
title: Ring Buffer / Event Queue for Simulation
description: 搜集 LMAX Disruptor 模式在 C++ 中的实现，包括 disruptor_cpp、disruptor4cpp、bytemaster/disruptor 等，分析其 lock-free 环形缓冲区设计、sequence barrier、wait strategy 机制，以及用于 RTL 仿真事件队列的适配方案
source_url: "https://github.com/hangukquant/disruptor_cpp"
source_type: "github-repo"
author: "hangukquant / alexleemanfui / bytemaster"
date: "2025-2024"
tags: ["lock-free", "ring-buffer", "LMAX-Disruptor", "event-queue", "simulation", "SPSC", "MPMC", "C++20"]
keywords: ["disruptor", "ring buffer", "sequence barrier", "wait strategy", "event processor", "simulation"]
capture_date: "2025-07-15"
---

# Ring Buffer / Event Queue 实现汇总（LMAX Disruptor 模式）

## 来源

- URL:
  - https://github.com/hangukquant/disruptor_cpp (C++20 header-only)
  - https://github.com/alexleemanfui/disruptor4cpp (C++11 port)
  - https://github.com/bytemaster/disruptor (C++ style API)
  - https://github.com/concurrencykit/ck (基础 ring buffer 原语)
- 类型: github-repo
- 作者: hangukquant / alexleemanfui / Daniel Larimer (bytemaster)
- 日期: 2015-2025

## 摘要

LMAX Disruptor 是一种基于预分配环形数组的高性能并发框架，核心思想是用序列号（Sequence）替代锁，实现生产者-消费者之间的无锁协调。C++ 生态中有多个 Disruptor 移植实现，从 C++11 到 C++20 不等。本文汇总其 RingBuffer、SequenceBarrier、WaitStrategy、EventProcessor 等核心组件的代码骨架，并给出「适配到 RTL 仿真事件队列」的工程建议。

## 关键要点

- Disruptor 的 RingBuffer 是定长 2^n 的预分配数组，生产者通过 `next()` 申请序列号、`publish()` 发布，消费者通过 `SequenceBarrier.waitFor()` 等待可用事件
- 单生产者（SingleProducerSequencer）使用 `memory_order_release` 发布 sequence，多生产者（MultiProducerSequencer）需 CAS 竞争序列号
- SequenceBarrier 支持消费者依赖图：消费者 C 可声明依赖消费者 A、B 的 sequence，形成 diamond / pipeline 拓扑
- WaitStrategy 决定消费者等待策略：`BusySpinWaitStrategy`（最低延迟）、`SleepingWaitStrategy`（平衡 CPU）、`BlockingWaitStrategy`（最低 CPU）
- C++ 实现的关键差异在于零拷贝：使用 `std::aligned_storage` / `std::launder` 在预分配槽位就地构造事件，避免堆分配与深拷贝

## 对 RTL 仿真器多线程化的启示

RTL 仿真中，每个时间步会产生大量事件（信号翻转、进程唤醒、延迟回调）。传统实现使用 `std::queue` 或 `std::priority_queue`，每时间步频繁 new/delete 且串行化。Disruptor 模式的预分配 ring buffer 可将事件对象复用，消除 GC 压力；sequence barrier 支持「多消费者按依赖顺序处理事件」（例如组合逻辑必须先于时序逻辑），天然适合 RTL 的 eval-update 两阶段模型。

---

## 实现一：disruptor_cpp（C++20，header-only）

### 设计核心

直接移植 LMAX Disruptor v3，保留 `RingBuffer`、`Sequencer`、`SequenceBarrier`、`EventProcessor`、`WaitStrategy` 等核心概念。目前实现 `SingleProducerSequencer`，`MultiProducerSequencer` 仍在开发中。

### 架构

```
Application/Driver (Producer)
    │
    ▼
SingleProducerSequencer ──► RingBuffer (T[N])
    │                              │
    │ next() / get(seq) / publish(seq)
    │                              │
    ▼                              ▼
SequenceBarrier ◄────────── EventProcessor
(WaitStrategy +               (owns consumer Sequence)
 dependent sequences)
    │
    ▼
EventHandler::onEvent(event, seq, end_of_batch)
```

### 可复用代码片段（SPSC 示例）

```cpp
// disruptor_cpp — SPSC 示例骨架
// 原仓库: https://github.com/hangukquant/disruptor_cpp

#include "disruptor.hpp"
#include <iostream>
#include <thread>

struct Event {
    int value = 0;
};

class MyHandler : public disruptor::event_handler<Event> {
public:
    void on_event(Event& event, std::int64_t sequence, bool end_of_batch) override {
        std::cout << "Seq " << sequence << " Value " << event.value << "\n";
    }
};

int main() {
    // RingBuffer<事件类型, 大小必须是 2^n>
    disruptor::ring_buffer<Event, 1024,
        disruptor::busy_spin_wait_strategy,
        disruptor::producer_type::single> ring_buffer;

    auto barrier = ring_buffer.new_barrier();
    MyHandler handler;
    disruptor::batch_event_processor processor(ring_buffer, std::move(barrier), handler);

    std::thread consumer([&processor] { processor.run(); });

    // 生产者发布 1000 个事件
    for (int i = 0; i < 1000; ++i) {
        std::int64_t seq = ring_buffer.next();
        ring_buffer[seq] = Event{i};  // 就地赋值/构造
        ring_buffer.publish(seq);      // 发布后消费者可见
    }

    std::this_thread::sleep_for(std::chrono::seconds(1));
    processor.halt();
    consumer.join();
    return 0;
}
```

### 关键 API 说明

| API | 作用 |
|-----|------|
| `ring_buffer.next()` | 申请下一个可用序列号，若 buffer 满则阻塞/自旋（取决于 WaitStrategy） |
| `ring_buffer[seq]` | 获取序列号对应槽位的引用，直接写入事件数据 |
| `ring_buffer.publish(seq)` | 发布序列号，消费者通过 barrier 感知到新事件 |
| `barrier.wait_for(seq)` | 消费者等待直到指定序列号可用 |
| `processor.run()` | 事件循环：不断读取可用事件并回调 `on_event` |

---

## 实现二：disruptor4cpp（C++11，更接近 Java 原版）

### 特点

- 需要 C++11，已在 GCC 4.8 测试
- header-only，复制 `include/` 目录即可使用
- 支持 `busy_spin_wait_strategy`、`producer_type::multi` 等模板参数

```cpp
#include <disruptor4cpp/disruptor4cpp.h>

// 创建多生产者 ring buffer
disruptor4cpp::ring_buffer<int, 1024,
    disruptor4cpp::busy_spin_wait_strategy,
    disruptor4cpp::producer_type::multi> ring_buffer;

auto barrier = ring_buffer.new_barrier();
int_handler handler;
disruptor4cpp::batch_event_processor<decltype(ring_buffer)> processor(
    ring_buffer, std::move(barrier), handler);

// 生产者线程
std::thread producer([&]() {
    for (int i = 0; i < 1000; ++i) {
        int64_t seq = ring_buffer.next();
        ring_buffer[seq] = i;        // 直接写入预分配槽位
        ring_buffer.publish(seq);
    }
});

// 消费者线程
std::thread consumer([&]() { processor.run(); });
```

---

## 实现三：bytemaster/disruptor（C++ 风格 API，cursor 分离）

### 设计差异

该实现将「游标（cursor）」与「数据存储」分离：
- `ring_buffer<T, Size>`：纯数据容器，2^n 大小
- `write_cursor`：单线程写游标，跟踪生产位置
- `shared_write_cursor`：多线程安全写游标
- `read_cursor`：读游标，可跟随/阻塞于其他游标

这种分离允许构建复杂的数据流拓扑，例如「读游标跟随多个上游写游标」，实现 diamond 合并。

```cpp
// bytemaster/disruptor 示例风格
ring_buffer<int, 1024> buffer;
write_cursor wc;
read_cursor  rc;

// 生产者
auto seq = wc.claim(1);       // 申请 1 个槽位
buffer[seq] = 42;
wc.publish(seq);              // 发布

// 消费者
auto avail = rc.wait_for(wc); // 等待生产者游标
for (auto i = rc.begin(); i != avail; ++i) {
    process(buffer[i]);
}
rc.set(avail);                // 推进读游标
```

### 性能声明

> "Simple benchmarks indicate that performance of this implementation is better than other known C++ implementations of this pattern." —— 作者声称比当时其他 C++ Disruptor 移植更快。

---

## 实现四：C++17 零拷贝 RingBufferSlot（论文适配）

### 来自《C++ Design Patterns for Low-latency Applications》的适配方案

```cpp
// 预分配槽位 + 原地构造 + launder 避免编译器误优化
#include <new>
#include <type_traits>
#include <cstddef>
#include <array>

template<typename T>
class RingBufferSlot {
    alignas(T) std::array<std::byte, sizeof(T)> storage_;
public:
    T& construct(const T& src) {
        return *new (std::launder(storage_.data())) T(src);
    }
    template<typename... Args>
    T& emplace(Args&&... args) {
        return *new (std::launder(storage_.data())) T(std::forward<Args>(args)...);
    }
    void destroy() { std::launder(storage_.data())->~T(); }
};

// 使用示例
template<typename T, size_t N>
class EventRingBuffer {
    static_assert((N & (N - 1)) == 0, "N must be power of 2");
    RingBufferSlot<T> slots_[N];
    std::atomic<std::int64_t> write_seq_{0};
    std::atomic<std::int64_t> read_seq_{0};
public:
    template<typename... Args>
    bool try_emplace(Args&&... args) {
        std::int64_t seq = write_seq_.load(std::memory_order_relaxed);
        if (seq - read_seq_.load(std::memory_order_acquire) >= N) return false;  // full
        if (!write_seq_.compare_exchange_strong(seq, seq + 1,
                std::memory_order_acquire, std::memory_order_relaxed))
            return false;
        slots_[seq & (N - 1)].emplace(std::forward<Args>(args)...);
        write_seq_.store(seq + 1, std::memory_order_release);  // 二次发布
        return true;
    }

    std::optional<T> try_pop() {
        std::int64_t seq = read_seq_.load(std::memory_order_relaxed);
        if (seq >= write_seq_.load(std::memory_order_acquire)) return std::nullopt;  // empty
        T& obj = *std::launder(reinterpret_cast<T*>(
            slots_[seq & (N - 1)].storage_.data()));
        T result = std::move(obj);
        slots_[seq & (N - 1)].destroy();
        read_seq_.store(seq + 1, std::memory_order_release);
        return result;
    }
};
```

---

## 性能数据（Disruptor vs 传统队列）

来自《C++ Design Patterns for Low-latency Applications Including High-frequency Trading》(arXiv:2309.04259)：

| 方案 | 10⁶ 事件耗时 | 相对提升 |
|------|------------|---------|
| Simple `std::queue` + 堆分配 | 884,871,405 ns | 基准 |
| Disruptor (ring buffer + sequence) | 543,171,556 ns | **38.6%** |

来自 LMAX 官方 Java 数据（C++ 移植通常可接近该水平）：

| 指标 | 数值 |
|------|------|
| 吞吐量 | 600 万订单/秒 |
| 端到端延迟 | 亚毫秒级 |

来自 C++ MCP 网关工业级适配白皮书：

| 方案 | 平均延迟 | GC/分配压力 |
|------|----------|-------------|
| `std::queue` + 堆分配 | 850 ns | 高（频繁 new/delete） |
| Disruptor + 零拷贝 | 42 ns | 零（预分配复用） |

---

## 适配 RTL 仿真事件队列的建议

### 1. 事件槽位设计

```cpp
struct RtlEvent {
    enum Type { SIGNAL_UPDATE, PROCESS_WAKEUP, DELAYED_NOTIFY } type;
    uint64_t time;           // 仿真时间戳
    void* target;            // 目标进程/信号句柄
    uint32_t value;          // 新值（对信号更新）
    // 注意：避免在事件内持有 std::string/vector，保持 POD 或平凡可复制
};

// Disruptor ring buffer 预分配 RtlEvent[65536]，64K 事件/时间步对大部分设计足够
using EventRing = disruptor::ring_buffer<RtlEvent, 65536,
    disruptor::sleeping_wait_strategy,  // 仿真非极端高频，平衡延迟与 CPU
    disruptor::producer_type::single>;   // 单时间步内通常单线程收集事件
```

### 2. 消费者依赖拓扑（模拟 eval-update 两阶段）

```
[Producer: Scheduler]
         │
         ▼
    [RingBuffer]
         │
    ┌────┴────┐
    ▼         ▼
[Combinational]   [Sequential]
    │               │
    └────┬──────────┘
         ▼
    [PostUpdate]
         │
         ▼
    [TimeAdvance]
```

- `Combinational` 和 `Sequential` 消费者可并行（无依赖）
- `PostUpdate` 依赖前两者完成（SequenceBarrier 等待两者的 sequence）
- `TimeAdvance` 依赖 `PostUpdate`

### 3. 批量处理降低同步开销

```cpp
// 在 EventHandler 中利用 end_of_batch 做批量提交
void on_event(RtlEvent& event, std::int64_t seq, bool end_of_batch) override {
    local_batch.push_back(event);
    if (end_of_batch || local_batch.size() >= 64) {
        flush_batch(local_batch);  // 批量写回仿真数据库或调度下一级队列
        local_batch.clear();
    }
}
```

### 4. 多时间步的 RingBuffer 复用

若仿真时间步的事件数波动大，可维持一个全局 RingBuffer，每个时间步调用 `processor.halt()` / `processor.run()` 重置，或设计「时间步 epoch」让消费者的 sequence 自然回绕到 0。由于 RingBuffer 大小固定为 2^n，sequence 回绕时通过取模 `seq & (N-1)` 定位槽位，无需清空数组。

---

## 相关链接

- [hangukquant/disruptor_cpp](https://github.com/hangukquant/disruptor_cpp)
- [alexleemanfui/disruptor4cpp](https://github.com/alexleemanfui/disruptor4cpp)
- [bytemaster/disruptor](https://github.com/bytemaster/disruptor)
- [LMAX Disruptor 官方文档](https://lmax-exchange.github.io/disruptor/user-guide/index.html)
- [arXiv: C++ Design Patterns for Low-latency Applications](https://ar5iv.labs.arxiv.org/html/2309.04259)
- [C++ MCP 网关白皮书：Disruptor 零拷贝适配](https://blog.csdn.net/PixelWander/article/details/160502952)

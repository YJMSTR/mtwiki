---
title: SPSC / MPMC Lock-Free Queue Implementation
description: 搜集可直接复用的 C++ 无锁队列实现，涵盖 SPSC（单生产者单消费者）与 MPMC（多生产者多消费者）场景，包含 moodycamel::ReaderWriterQueue、moodycamel::ConcurrentQueue、boost::lockfree::spsc_queue、atomic_queue 等工业级实现及性能基准数据
source_url: "https://github.com/cameron314/readerwriterqueue"
source_type: "github-repo"
author: "Cameron Desrochers (moodycamel)"
date: "2020-03-15"
tags: ["lock-free", "SPSC", "MPMC", "queue", "C++11", "concurrentqueue"]
keywords: ["moodycamel", "ReaderWriterQueue", "ConcurrentQueue", "boost::lockfree", "atomic_queue", "wait-free"]
capture_date: "2025-07-15"
---

# SPSC / MPMC Lock-Free Queue 实现汇总

## 来源

- URL: 
  - https://github.com/cameron314/readerwriterqueue (SPSC)
  - https://github.com/cameron314/concurrentqueue (MPMC)
  - https://github.com/boostorg/lockfree (boost::lockfree)
  - https://github.com/max0x7ba/atomic_queue (atomic_queue benchmark)
- 类型: github-repo
- 作者: Cameron Desrochers / Boost / Maxim Egorushkin
- 日期: 2020-2024

## 摘要

本文汇总了 C++ 生态中最成熟、可直接落地的无锁队列实现。SPSC 场景以 moodycamel::ReaderWriterQueue 为代表，在 x86 上 enqueue/dequeue 可编译为纯 load/store，无需 CAS；MPMC 场景以 moodycamel::ConcurrentQueue 为代表，采用「每个生产者独占子队列」的设计，支持 bulk enqueue/dequeue，吞吐量远超 boost::lockfree::queue 与 tbb::concurrent_queue。atomic_queue 项目提供了跨实现的量化 benchmark 数据，可作为选型依据。

## 关键要点

- **moodycamel::ReaderWriterQueue** 是 wait-free SPSC 队列，x86 上内存屏障编译为 nop，enqueue/dequeue 仅为 O(1) 的 load/store + branch
- **moodycamel::ConcurrentQueue** 是 lock-free MPMC 队列，内部用连续 block 而非链表，支持 token 加速与 bulk 操作，但不保证 linearizability 与 NUMA-aware
- **boost::lockfree::spsc_queue** 同样是 wait-free SPSC，但限制元素类型必须有 trivial assign/destruct；MPMC 版本基于 Michael-Scott 算法
- **atomic_queue benchmark** 显示：SPSC 场景下 boost::lockfree::spsc_queue 与 moodycamel::ReaderWriterQueue 的吞吐量远高于 mutex/spinlock 方案；MPMC 场景下 moodycamel::ConcurrentQueue  bulk 操作接近单线程 std::queue 速度

## 对 RTL 仿真器多线程化的启示

RTL 仿真器的事件队列通常需要「一个时间步内由单线程收集事件、多线程分发执行」的模型。若将「事件注入」与「事件消费」严格分离，可使用 SPSC 队列作为线程间高速通道；若存在多个前端模块同时注入事件，则 MPMC 队列更合适。moodycamel::ConcurrentQueue 的 bulk dequeue 特性特别适合「一个时间步批量拉取所有待执行事件」的仿真模式。此外，token 机制可绑定到每个生产者线程，避免隐式生产者哈希表的动态扩容开销。

---

## 实现一：moodycamel::ReaderWriterQueue（SPSC, wait-free）

### 设计核心

基于「queue-of-queues」：底层是环形 buffer（block），高层是 block 的循环链表。生产者只写 tail，消费者只读 front，双方通过 atomic 的 front/tail 索引进行单向推进。x86 上 `memory_order_acquire/release` 屏障编译为 nop，因此热点路径仅为普通 load/store。

### 可复用代码片段（精简版）

```cpp
// readerwriterqueue.h — 精简核心 enqueue/dequeue 路径
// 原文件: https://github.com/cameron314/readerwriterqueue

template<typename T, size_t MAX_BLOCK_SIZE = 512>
class ReaderWriterQueue {
    struct Block {
        std::atomic<size_t> front;      // 消费者读取位置
        size_t localTail;               // 消费者本地缓存
        char pad0[64 - sizeof(std::atomic<size_t>) - sizeof(size_t)];
        std::atomic<size_t> tail;       // 生产者写入位置
        size_t localFront;
        char pad1[64 - sizeof(std::atomic<size_t>) - sizeof(size_t)];
        std::atomic<Block*> next;
        char* data;                     // 元素存储区
        const size_t sizeMask;
        // ... constructor omitted
    };

    std::atomic<Block*> frontBlock;   // 消费者当前 block
    char pad[64 - sizeof(std::atomic<Block*>)];
    std::atomic<Block*> tailBlock;    // 生产者当前 block
    size_t largestBlockSize;

public:
    // 生产者路径：仅操作 tailBlock->tail
    bool try_enqueue(T const& element) {
        Block* tailBlock_ = tailBlock.load();
        size_t blockFront = tailBlock_->localFront;
        size_t blockTail  = tailBlock_->tail.load();
        size_t nextBlockTail = (blockTail + 1) & tailBlock_->sizeMask;

        if (nextBlockTail != blockFront ||
            nextBlockTail != (tailBlock_->localFront = tailBlock_->front.load())) {
            fence(memory_order_acquire);
            char* location = tailBlock_->data + blockTail * sizeof(T);
            new (location) T(element);               // placement new
            fence(memory_order_release);
            tailBlock_->tail = nextBlockTail;
            return true;
        }
        // 需要分配新 block 或回绕（省略动态扩容逻辑）
        return false;
    }

    // 消费者路径：仅操作 frontBlock->front
    template<typename U>
    bool try_dequeue(U& result) {
        Block* frontBlock_ = frontBlock.load();
        size_t blockTail = frontBlock_->localTail;
        size_t blockFront = frontBlock_->front.load();

        if (blockFront != blockTail ||
            blockFront != (frontBlock_->localTail = frontBlock_->tail.load())) {
            fence(memory_order_acquire);
            auto element = reinterpret_cast<T*>(frontBlock_->data + blockFront * sizeof(T));
            result = std::move(*element);
            element->~T();
            blockFront = (blockFront + 1) & frontBlock_->sizeMask;
            fence(memory_order_release);
            frontBlock_->front = blockFront;
            return true;
        }
        return false;  // empty
    }
};
```

### 性能特征

| 特性 | 值 |
|------|-----|
| 算法复杂度 | enqueue O(1), dequeue O(1) |
| 内存屏障 | x86 上编译为 nop |
| 动态扩容 | 支持（enqueue 自动分配新 block） |
| 预分配保证 | `try_enqueue` 永不分配内存 |
| 线程模型 | 严格单生产者 + 单消费者 |

---

## 实现二：moodycamel::ConcurrentQueue（MPMC, lock-free）

### 设计核心

每个生产者拥有独立的「子队列」（sub-queue），由连续 block 构成。消费者轮询所有子队列直到找到非空者。enqueue 仅需更新本生产者的 tail 索引；dequeue 只需读取各生产者子队列的 front。隐式生产者通过线程局部哈希表查找，显式 producer token 可绕过哈希查找。

### 可复用代码片段（使用示例）

```cpp
// concurrentqueue.h — 典型使用模式与 token 加速
// 原文件: https://github.com/cameron314/concurrentqueue

#include "concurrentqueue.h"

moodycamel::ConcurrentQueue<int> q;

// 基础用法（隐式生产者，有哈希查找开销）
q.enqueue(25);
int item;
bool found = q.try_dequeue(item);

// 高效用法：显式 token（推荐用于固定生产者线程）
moodycamel::ProducerToken ptok(q);
moodycamel::ConsumerToken ctok(q);

q.enqueue(ptok, 17);
q.try_dequeue(ctok, item);

// Bulk 操作：仿真器一个时间步批量拉取事件
int items[] = {1, 2, 3, 4, 5};
q.enqueue_bulk(ptok, items, 5);

int results[5];
size_t count = q.try_dequeue_bulk(ctok, results, 5);
// count 为实际出队数量，可能小于 5 若队列元素不足
```

### 预分配公式（`try_enqueue` 永不分配）

```cpp
// 若需保证 N 个元素 + MAX_NUM_PRODUCERS 个显式生产者：
size_t prealloc = (ceil(N / BLOCK_SIZE) + 1) * MAX_NUM_PRODUCERS * BLOCK_SIZE;
// BLOCK_SIZE 默认 32，可通过 traits 调整

struct MyTraits : public moodycamel::ConcurrentQueueDefaultTraits {
    static const size_t BLOCK_SIZE = 256;
};
moodycamel::ConcurrentQueue<int, MyTraits> q(prealloc);
```

---

## 实现三：boost::lockfree::spsc_queue（SPSC, wait-free）

### 特点与限制

- 头文件: `<boost/lockfree/spsc_queue.hpp>`
- 要求元素类型具备 trivial assignment 与 trivial destructor
- 固定容量（编译时或运行时指定），不支持动态增长
- 同样基于环形数组 + atomic read/write 索引，无需 CAS

```cpp
#include <boost/lockfree/spsc_queue.hpp>

boost::lockfree::spsc_queue<int, boost::lockfree::capacity<1024>> queue;

// 非阻塞入队/出队
bool pushed = queue.push(42);
bool popped = queue.pop(value);

// 批量操作
boost::lockfree::spsc_queue<int>::size_type pushed_count = queue.push(items, items + 10);
```

---

## 性能基准数据（atomic_queue benchmark）

以下数据来自 `atomic_queue` 项目的 cross-implementation benchmark（约 2023 年，x86-64 Linux，编译优化 `-O3`）：

| 实现 | 模式 | 相对吞吐量（越高越好） | 备注 |
|------|------|------------------------|------|
| `std::queue` (单线程) | 基准 | 102.40M ops/s | 理论上限 |
| `moodycamel::ConcurrentQueue` (bulk) | MPMC | 23.56M ops/s | 多线程竞争下仍保持高效 |
| `moodycamel::BlockingConcurrentQueue` | MPMC | 24.73M ops/s | 含轻量信号量阻塞 |
| `tbb::concurrent_queue` | MPMC | 11.54M ops/s | 基于锁，非 lock-free |
| `boost::lockfree::queue` | MPMC | 3.44M ops/s | Michael-Scott 算法 |
| `moodycamel::ReaderWriterQueue` | SPSC | 极高（接近单线程） | 无 CAS，纯 load/store |
| `boost::lockfree::spsc_queue` | SPSC | 极高 | 同样无 CAS |

> 来源：moodycamel 博客 benchmark（Core 2 Quad Q9500@2.83GHz，更高频现代 CPU 绝对数值会更高，但相对比例仍具参考性）。

---

## 选型建议

| 场景 | 推荐实现 | 理由 |
|------|----------|------|
| 严格单生产者 → 单消费者 | `moodycamel::ReaderWriterQueue` | 热点路径无 CAS，x86 零开销 |
| 多生产者 → 多消费者，需 bulk | `moodycamel::ConcurrentQueue` | bulk 操作 amortize 同步成本 |
| 已有 Boost 依赖，元素类型简单 | `boost::lockfree::spsc_queue` | 成熟稳定，无额外依赖 |
| 必须固定容量，不允许动态分配 | `boost::lockfree::spsc_queue` 或 `atomic_queue` | 预分配、无堆分配 |
| 需要阻塞等待（消费者空转） | `moodycamel::BlockingConcurrentQueue` | 基于轻量信号量，开销低 |

---

## 相关链接

- [moodycamel/readerwriterqueue](https://github.com/cameron314/readerwriterqueue)
- [moodycamel/concurrentqueue](https://github.com/cameron314/concurrentqueue)
- [boost::lockfree](https://github.com/boostorg/lockfree)
- [max0x7ba/atomic_queue](https://github.com/max0x7ba/atomic_queue)
- [C++ 无锁队列 moodycamel::ConcurrentQueue 详解](https://www.shuzhiduo.com/A/GBJrB4gGJ0/)

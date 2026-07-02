---
title: Work-Stealing Deque Implementation
description: 搜集 C++ 生态中可直接复用的 Chase-Lev 工作窃取双端队列实现，涵盖 Taskflow (UnboundedWSQ / BoundedWSQ)、riften::Deque、Async++ 的 work_steal_queue，分析其锁-free SPMC 设计、内存序选择及动态扩容策略
source_url: "https://github.com/taskflow/taskflow/blob/master/taskflow/core/wsq.hpp"
source_type: "github-repo"
author: "Taskflow / ConorWilliams / Amanieu d'Antras"
date: "2024-2025"
tags: ["lock-free", "work-stealing", "deque", "Chase-Lev", "SPMC", "C++17", "C++20"]
keywords: ["work-stealing deque", "Chase-Lev", "taskflow", "riften::Deque", "pop", "steal", "CAS"]
capture_date: "2025-07-15"
---

# Work-Stealing Deque 实现汇总

## 来源

- URL:
  - https://github.com/taskflow/taskflow/blob/master/taskflow/core/wsq.hpp (Taskflow)
  - https://github.com/ConorWilliams/ConcurrentDeque (riften::Deque)
  - https://github.com/Amanieu/asyncplusplus (Async++ work_steal_queue)
  - https://github.com/ssbl/concurrent-deque (Chase-Lev C++ 实现)
- 类型: github-repo
- 作者: Tsung-Wei Huang (Taskflow) / Conor Williams / Amanieu d'Antras
- 日期: 2024-2025

## 摘要

Work-stealing deque 是任务调度系统的核心数据结构，支持「单所有者线程在底端 push/pop，多窃取线程在顶端 steal」的 SPMC 模型。Chase-Lev 算法通过 CAS 解决 pop 与 steal 的并发竞争，配合动态环形数组扩容实现无界任务缓冲。本文汇总 Taskflow、riften::Deque 与 Async++ 三个工业级 C++ 实现，提供可直接嵌入调度器的代码骨架与内存序分析。

## 关键要点

- Chase-Lev deque 的核心是三个 atomic 变量：`_top`（顶端索引，steal 操作 CAS 递增）、`_bottom`（底端索引，owner push/pop 读写）、`_array`（指向环形 buffer 的指针）
- Owner 的 `pop()` 与 thief 的 `steal()` 可能在仅剩一个元素时发生竞争：通过 `pop()` 先递减 `_bottom` 再 CAS `_top`，与 `steal()` 先读 `_top` 再 CAS `_top`，确保恰好一方成功
- 动态扩容通过 `resize` 实现：创建两倍容量的新数组，复制 `[top, bottom)` 区间，旧数组加入 garbage list 延后删除，避免窃取线程悬空引用
- Taskflow 实现了 `BoundedWSQ`（固定容量，无动态分配）与 `UnboundedWSQ`（自动扩容）两种变体，前者适合确定任务上界的实时系统

## 对 RTL 仿真器多线程化的启示

RTL 仿真器的「多线程事件调度」天然适合 work-stealing 模型：主线程将事件按时间步分发给各 worker 的本地队列；当某个 worker 提前完成时，可从其他 worker 的队列 steal 事件，实现负载均衡。Chase-Lev deque 的 LIFO owner / FIFO thief 特性也符合仿真局部性：owner 优先处理刚压入的子事件（缓存友好），而 steal 从 oldest 任务开始（减少与 owner 的冲突）。

---

## 实现一：Taskflow UnboundedWSQ（C++17，自动扩容）

### 设计核心

基于论文 "Correct and Efficient Work-Stealing for Weak Memory Models" (PPoPP 2013)。`Array` 封装原子元素数组，支持 modulo 索引与 resize。`_top`、`_bottom`、`_array` 分别置于独立 cache line，避免 false sharing。

### 可复用代码片段（精简骨架）

```cpp
// wsq.hpp — Taskflow UnboundedWSQ 精简版
// 原文件: https://github.com/taskflow/taskflow/blob/master/taskflow/core/wsq.hpp

#include <atomic>
#include <vector>
#include <optional>
#include <bit>  // C++20 std::bit_ceil, 可用自定义实现替换

template <typename T>
class UnboundedWSQ {
    struct Array {
        size_t C;                      // capacity
        size_t M;                      // mask = C-1
        std::atomic<T>* S;             // atomic 元素数组

        explicit Array(size_t c) : C{c}, M{c-1}, S{new std::atomic<T>[C]} {}
        ~Array() { delete[] S; }

        size_t capacity() const noexcept { return C; }
        void push(int64_t i, T o) noexcept {
            S[i & M].store(o, std::memory_order_relaxed);
        }
        T pop(int64_t i) noexcept {
            return S[i & M].load(std::memory_order_relaxed);
        }
        Array* resize(int64_t b, int64_t t) {
            Array* ptr = new Array(2 * C);
            for (int64_t i = t; i != b; ++i) ptr->push(i, pop(i));
            return ptr;
        }
    };

    alignas(64) std::atomic<int64_t> _top;
    alignas(64) std::atomic<int64_t> _bottom;
    int64_t _cached_top{0};            // owner 本地缓存，减少 top 读取
    alignas(64) std::atomic<Array*> _array;
    std::vector<Array*> _garbage;    // 旧数组延迟释放

public:
    explicit UnboundedWSQ(int64_t logSize = 8) {
        _top.store(0, std::memory_order_relaxed);
        _bottom.store(0, std::memory_order_relaxed);
        _array.store(new Array{size_t{1} << logSize}, std::memory_order_relaxed);
        _garbage.reserve(32);
    }
    ~UnboundedWSQ() {
        for (auto a : _garbage) delete a;
        delete _array.load();
    }

    // Owner push: LIFO
    void push(T o) {
        int64_t b = _bottom.load(std::memory_order_relaxed);
        Array* a = _array.load(std::memory_order_relaxed);

        // 检查是否需要扩容（使用 cached top 避免每次读 atomic）
        if (a->capacity() < static_cast<size_t>(b - _cached_top + 1)) [[unlikely]] {
            _cached_top = _top.load(std::memory_order_acquire);
            if (a->capacity() < static_cast<size_t>(b - _cached_top + 1)) [[unlikely]] {
                a = _resize_array(a, b, _cached_top);
            }
        }
        a->push(b, o);
        std::atomic_thread_fence(std::memory_order_release);
        _bottom.store(b + 1, std::memory_order_release);
    }

    // Owner pop: LIFO，与 steal 竞争最后一个元素
    std::optional<T> pop() {
        int64_t b = _bottom.load(std::memory_order_relaxed) - 1;
        Array* a = _array.load(std::memory_order_relaxed);
        _bottom.store(b, std::memory_order_relaxed);
        std::atomic_thread_fence(std::memory_order_seq_cst);
        int64_t t = _top.load(std::memory_order_relaxed);

        std::optional<T> item = std::nullopt;
        if (t <= b) {
            item = a->pop(b);
            if (t == b) {  // 最后一个元素，竞争窗口
                if (!_top.compare_exchange_strong(t, t + 1,
                        std::memory_order_seq_cst, std::memory_order_relaxed)) {
                    item = std::nullopt;  // thief 赢了
                }
                _bottom.store(b + 1, std::memory_order_relaxed);
            }
        } else {
            _bottom.store(b + 1, std::memory_order_relaxed);  // 回滚
        }
        return item;
    }

    // Thief steal: FIFO，任意线程可调用
    std::optional<T> steal() {
        int64_t t = _top.load(std::memory_order_acquire);
        std::atomic_thread_fence(std::memory_order_seq_cst);
        int64_t b = _bottom.load(std::memory_order_acquire);

        std::optional<T> item = std::nullopt;
        if (t < b) {
            Array* a = _array.load(std::memory_order_consume);
            item = a->pop(t);  // 先读数据，再 CAS top
            if (!_top.compare_exchange_strong(t, t + 1,
                    std::memory_order_seq_cst, std::memory_order_relaxed)) {
                return std::nullopt;  // 竞争失败
            }
        }
        return item;
    }

private:
    Array* _resize_array(Array* a, int64_t b, int64_t t) {
        Array* tmp = a->resize(b, t);
        _garbage.push_back(a);
        _array.store(tmp, std::memory_order_release);
        return tmp;
    }
};
```

### 内存序分析

| 操作 | 变量 | 内存序 | 原因 |
|------|------|--------|------|
| push | `_bottom` | `release` | 保证元素写入对 thief 可见后才更新索引 |
| pop | `_bottom` | `relaxed` + `seq_cst` fence | 先递减 bottom 关闭 steal 窗口，再用 seq_cst 同步 |
| pop | `_top` | `seq_cst` | 与 steal 竞争最后一个元素，需最强序 |
| steal | `_top` | `acquire` | 获取最新已 steal 位置 |
| steal | `_bottom` | `acquire` | 获取最新 push 位置 |
| steal | `_top` CAS | `seq_cst` | 确保全局唯一 winner |

---

## 实现二：riften::Deque（C++20，Chase-Lev 单头文件）

### 特点

- 单头文件：`riften/deque.hpp`
- 要求类型 `default_initializable` + `trivially_destructible` + `nothrow move`
- 使用 `std::optional<T>` 作为 pop/steal 的返回值，语义清晰
- 无 buffer 回收内存开销（garbage 由 `_garbage` vector 持有）

```cpp
#include "riften/deque.hpp"

riften::Deque<int> deque;

std::thread owner([&]() {
    for (int i = 0; i < 10000; ++i) deque.emplace(i);
    while (!deque.empty()) { auto item = deque.pop(); /* LIFO */ }
});

std::thread thief([&]() {
    while (!deque.empty()) { auto item = deque.steal(); /* FIFO */ }
});
```

### 关键差异 vs Taskflow

- `riften::Deque` 使用 `std::atomic<std::int64_t>` 配合 `std::atomic_thread_fence(seq_cst)`，而非 Taskflow 的 `seq_cst` CAS failure order；两者在 x86 上等价，但 riften 版本更贴近论文伪代码。
- `pop()` 中 `bottom.store(b, relaxed)` 后立即跟 `atomic_thread_fence(seq_cst)`，与 Taskflow 相同。

---

## 实现三：Async++ work_steal_queue（C++11，指针特化）

### 特点

- 存储 `void*` 而非泛型 T，适合任务句柄调度场景
- `circular_array` 维护链表式旧数组历史，窃取线程可能仍在读取旧数组元素
- `grow()` 返回新数组并保留旧数组链，直到队列析构才统一释放

```cpp
// async++/src/work_steal_queue.h — 核心逻辑
class work_steal_queue {
    class circular_array {
        detail::aligned_array<void*, 64> items;
        std::unique_ptr<circular_array> previous;
    public:
        circular_array(std::size_t n) : items(n) {}
        void* get(std::size_t i) { return items[i & (size() - 1)]; }
        void  put(std::size_t i, void* x) { items[i & (size() - 1)] = x; }
        circular_array* grow(std::size_t top, std::size_t bottom) {
            circular_array* new_array = new circular_array(size() * 2);
            new_array->previous.reset(this);
            for (std::size_t i = top; i != bottom; ++i)
                new_array->put(i, get(i));
            return new_array;
        }
    };

    std::atomic<circular_array*> array;
    std::atomic<std::size_t> top, bottom;

public:
    void push(task_run_handle x) {
        std::size_t b = bottom.load(std::memory_order_relaxed);
        std::size_t t = top.load(std::memory_order_acquire);
        circular_array* a = array.load(std::memory_order_relaxed);
        if (to_signed(b - t) >= to_signed(a->size())) {
            a = a->grow(t, b);
            array.store(a, std::memory_order_release);
        }
        a->put(b, x.to_void_ptr());
        std::atomic_thread_fence(std::memory_order_release);
        bottom.store(b + 1, std::memory_order_relaxed);
    }

    task_run_handle steal() {
        while (true) {
            std::size_t t = top.load(std::memory_order_acquire);
            std::atomic_thread_fence(std::memory_order_seq_cst);
            std::size_t b = bottom.load(std::memory_order_acquire);
            if (to_signed(b - t) <= 0) return task_run_handle();
            void* x = array.load(std::memory_order_consume)->get(t);
            if (top.compare_exchange_weak(t, t + 1,
                    std::memory_order_seq_cst, std::memory_order_relaxed))
                return task_run_handle::from_void_ptr(x);
            // 失败则循环重试（另一 thief 成功）
        }
    }
};
```

---

## 性能与行为对比

| 实现 | 扩容 | 元素类型限制 | 返回值 | 适用场景 |
|------|------|------------|--------|----------|
| Taskflow `UnboundedWSQ` | 自动 | 无（泛型） | `std::optional<T>` / `T*` | 通用任务调度 |
| Taskflow `BoundedWSQ` | 固定 | 无 | 同上 | 实时/嵌入式，禁止堆分配 |
| riften::Deque | 自动 | trivially destructible + nothrow move | `std::optional<T>` | 现代 C++20 项目 |
| Async++ | 自动 | 指针句柄（`void*`） | `task_run_handle` | 已有 Async++ 生态 |

---

## 嵌入 RTL 仿真调度器的建议

1. **Worker 本地队列**：每个仿真 worker 线程持有一个 `BoundedWSQ<Event*, 10>`（1024 容量），主线程 bulk_push 事件到各 worker；若事件数超出容量，回退到全局 MPMC 队列。
2. **窃取策略**：worker 完成本地事件后，先尝试 `steal()` 同 NUMA 节点其他 worker；失败则进入休眠或自旋（可配置 `Yield` / `Sleep` 等待策略）。
3. **避免 ABA**：Chase-Lev  deque 的 `top`/`bottom` 使用 `int64_t`，在 64 位系统上 overflow 几乎不可能，无需额外 tag。
4. **GC 延迟**：`UnboundedWSQ` 的旧数组通过 `_garbage` 延迟释放，适合长生命周期的线程池；若仿真为短批次，可用 `BoundedWSQ` 彻底避免动态分配。

---

## 相关链接

- [Taskflow wsq.hpp](https://github.com/taskflow/taskflow/blob/master/taskflow/core/wsq.hpp)
- [ConorWilliams/ConcurrentDeque](https://github.com/ConorWilliams/ConcurrentDeque)
- [Amanieu/asyncplusplus](https://github.com/Amanieu/asyncplusplus)
- [ssbl/concurrent-deque](https://github.com/ssbl/concurrent-deque)
- [Chase-Lev 原始论文](https://www.dre.vanderbilt.edu/~schmidt/PDF/work-stealing-dequeue.pdf)
- [Correct and Efficient Work-Stealing for Weak Memory Models (PPoPP 2013)](https://fzn.fr/readings/ppopp13.pdf)

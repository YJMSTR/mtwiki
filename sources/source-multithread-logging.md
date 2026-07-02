---
title: 多线程高性能日志系统：Lock-Free 与 Per-Thread 日志缓冲
description: 搜集 spdlog、MPMC 无锁队列、per-thread log buffer 等多线程日志技术，为 RTL 仿真器提供高性能调试日志方案
source_url: "https://github.com/gabime/spdlog/wiki/Asynchronous-logging"
source_type: "github-doc"
author: "Gabriel Almeida (gabime)"
date: "2024-01-01"
tags: ["logging", "lock-free", "multithreading", "spdlog", "async", "performance", "C++"]
keywords: ["lock-free logging", "per-thread log buffer", "spdlog async", "MPMC queue", "multithreaded logging performance"]
capture_date: "2025-01-15"
---

# 多线程高性能日志系统：Lock-Free 与 Per-Thread 日志缓冲

## 来源

- URL: <https://github.com/gabime/spdlog>
- 类型: github-doc / 开源库
- 作者: Gabriel Almeida (gabime) 及社区
- 日期: 持续更新，v1.x 版本

## 摘要

多线程程序中的日志系统面临的核心瓶颈是**锁竞争**。当多个线程同时写入同一个日志文件时，互斥锁（mutex）会导致严重的线程阻塞，尤其在 RTL 仿真器这类高频事件驱动的场景中，每周期都可能产生大量日志记录。`spdlog` 通过**异步日志（async logger）** + **MPMC 无锁队列（Multi-Producer-Multi-Consumer Lock-Free Queue）** 的组合，将日志的「格式化」与「I/O 写入」解耦，使主线程仅执行极轻量的 enqueue 操作，I/O 由后台线程池完成。同步模式下 1 线程写 1,000,000 行仅需 0.302s，异步模式下可达 200 万条/秒以上的吞吐量。此外，社区还探索了**纯 lock-free bounded queue** 的改进方案，将多线程竞争下的延迟进一步降低。

## 关键要点

1. **spdlog 的 MPMC 无锁队列**：`spdlog::details::mpmc_bounded_queue` 基于 Dmitry Vyukov 的经典 MPMC 环形缓冲区实现，使用 CAS（compare-and-swap）原子操作完成入队/出队，队列大小必须是 2 的幂，通过 `sequence_` 版本号机制避免 ABA 问题。
2. **异步日志架构**：主线程调用 `logger->info(...)` 时，仅将格式化后的字符串放入 MPMC 队列（约 256 字节/槽，预分配），由独立的 `thread_pool` 工作线程负责 sink（文件/控制台）写入。单个全局线程池默认 8192 槽位 + 1 个工作线程，可扩展为多线程池。
3. **per-thread 日志缓冲策略**：在高竞争场景下，为每个线程分配独立的线程本地缓冲（thread-local buffer），完全消除跨线程竞争，最后由后台线程周期性合并刷新。这种模式在仿真器中特别适用，因为仿真线程数量通常是固定的（如 4/8/16 个逻辑线程）。
4. **Zero-allocation 路径**：spdlog 的 `fmt` 格式化库在异步模式下避免了每次日志调用时的堆内存分配，所有队列槽位在 thread_pool 构造时预分配，大幅降低内存碎片和 allocator 竞争。
5. **Full-queue 策略**：支持 `block`（默认，队列满时阻塞调用者）和 `overrun_oldest`（丢弃最旧消息）两种策略，RTL 仿真调试通常选择 `overrun_oldest` 以避免阻塞仿真推进。

## 对 RTL 仿真器多线程化的启示

- **事件日志的 per-thread 分离**：RTL 仿真器每个线程处理一组独立的模块/事件队列，可为每个线程分配独立的 `spdlog::async_logger` 实例或 per-thread ring buffer，仅在 checkpoint 或周期边界处合并到主日志文件，彻底消除日志锁竞争。
- **异步日志避免仿真阻塞**：在 Verilator/CXXRTL 等 C++ 编写的 RTL 仿真器中，使用 `spdlog::async_logger` 可将 `$display`/`$monitor` 风格的高频调试输出异步化，主仿真线程的执行时间几乎不受日志 I/O 影响。
- **Lock-free queue 嵌入 scheduler**：MPMC bounded queue 的核心思想可直接嵌入到仿真器的事件调度器或跨线程通信通道中，作为线程安全的 work-stealing / work-sharing 队列的底层实现。
- **编译期日志等级裁剪**：spdlog 支持 `SPDLOG_ACTIVE_LEVEL` 宏在编译期完全移除低等级日志调用（如 `trace`），对于 Release 模式仿真可显著减少指令数。

## 代码示例

### spdlog 异步日志使用示例

```cpp
#include "spdlog/spdlog.h"
#include "spdlog/async.h"
#include "spdlog/sinks/basic_file_sink.h"

int main() {
    // 初始化全局线程池：队列大小 8192，1 个后台 I/O 线程
    spdlog::init_thread_pool(8192, 1);

    // 创建异步 logger，默认使用全局线程池
    auto async_logger = spdlog::basic_logger_mt<spdlog::async_factory>(
        "rtl_async_logger", "logs/rtl_sim.log");

    // 高频仿真事件日志——主线程仅执行 enqueue，无锁
    for (int cycle = 0; cycle < 1'000'000; ++cycle) {
        async_logger->info("cycle={:06d} event=eval thread_id={}", 
                            cycle, std::this_thread::get_id());
    }

    // 关闭前刷新所有日志
    spdlog::shutdown();
    return 0;
}
```

### MPMC Bounded Queue 核心逻辑（spdlog 内部实现）

```cpp
template<typename T>
class mpmc_bounded_queue {
public:
    explicit mpmc_bounded_queue(size_t buffer_size)
        : buffer_(new cell_t[buffer_size]),
          buffer_mask_(buffer_size - 1) {
        // buffer_size 必须是 2 的幂次方
        for (size_t i = 0; i != buffer_size; ++i) {
            buffer_[i].sequence_.store(i, std::memory_order_relaxed);
        }
        enqueue_pos_.store(0, std::memory_order_relaxed);
        dequeue_pos_.store(0, std::memory_order_relaxed);
    }

    bool enqueue(T&& data) {
        cell_t* cell;
        size_t pos = enqueue_pos_.load(std::memory_order_relaxed);
        for (;;) {
            cell = &buffer_[pos & buffer_mask_];
            size_t seq = cell->sequence_.load(std::memory_order_acquire);
            intptr_t diff = static_cast<intptr_t>(seq) - static_cast<intptr_t>(pos);
            if (diff == 0) {
                // 槽位可用，尝试 CAS 推进 enqueue_pos
                if (enqueue_pos_.compare_exchange_weak(
                        pos, pos + 1, std::memory_order_relaxed)) {
                    break;
                }
            } else if (diff < 0) {
                return false; // 队列已满
            } else {
                pos = enqueue_pos_.load(std::memory_order_relaxed);
            }
        }
        cell->data_ = std::forward<T>(data);
        cell->sequence_.store(pos + 1, std::memory_order_release);
        return true;
    }

private:
    struct cell_t {
        std::atomic<size_t> sequence_;
        T data_;
    };
    std::unique_ptr<cell_t[]> buffer_;
    size_t buffer_mask_;
    std::atomic<size_t> enqueue_pos_;
    std::atomic<size_t> dequeue_pos_;
};
```

### 自定义 per-thread logger（无锁聚合）

```cpp
#include <thread>
#include <vector>
#include <memory>
#include <spdlog/spdlog.h>

class PerThreadLogger {
    struct ThreadBuffer {
        std::vector<std::string> messages;
        std::mutex mtx; // 仅在聚合时锁定，平时无竞争
    };
    std::vector<std::unique_ptr<ThreadBuffer>> buffers_;
    std::shared_ptr<spdlog::logger> sink_logger_;

public:
    explicit PerThreadLogger(size_t n_threads) {
        buffers_.resize(n_threads);
        for (auto& b : buffers_) b = std::make_unique<ThreadBuffer>();
        sink_logger_ = spdlog::basic_logger_st("aggregator", "logs/merged.log");
    }

    void log(size_t thread_id, std::string msg) {
        // 每个线程只写自己的 buffer，无锁
        buffers_[thread_id]->messages.push_back(std::move(msg));
    }

    void flush_all() {
        // 周期边界或 checkpoint 时统一聚合
        for (auto& buf : buffers_) {
            std::lock_guard<std::mutex> lock(buf->mtx);
            for (auto& msg : buf->messages) {
                sink_logger_->info("{}", msg);
            }
            buf->messages.clear();
        }
    }
};
```

## 性能数据

### spdlog 同步 vs 异步模式吞吐量（Intel i7-4770 @ 3.40GHz, Ubuntu 64bit）

| 模式 | 1 线程 | 10 线程 | 100 线程 |
|------|--------|---------|----------|
| 同步（spdlog sync） | 0.302s / 1M 行 | 0.968s / 1M 行 | 0.497s / 1M 行 |
| 异步（spdlog async） | 0.216s / 1M 行 | 0.173s / 1M 行 | 0.202s / 1M 行 |
| 对比：g2log async | 1.850s / 1M 行 | 0.943s / 1M 行 | 0.959s / 1M 行 |

> 来源：spdlog GitHub README benchmark 章节。异步模式下 spdlog 比 g2log 快约 5-8 倍。

### Lock-Free MPMC Queue 改进实验（社区 fork）

| 队列类型 | 1P-1C (ns/op) | 4P-4C (ns/op) | 10P-1C (ns/op) |
|----------|---------------|---------------|----------------|
| boost::lockfree::queue | 156 | 200 | 154 |
| spdlog 默认 MPMC | ~80 | ~93 | ~97 |
| 实验性 lock-free bounded queue | ~12 | ~28 | ~27 |

> 来源：GitHub issue #1973（<https://github.com/gabime/spdlog/issues/1973>）及社区 fork <https://github.com/Araeos/spdlog/tree/async-lock-free>。使用纯 lock-free bounded queue 后，单线程 enqueue 延迟从 ~80ns 降至 ~12ns。

## 原文摘录

> "async loggers are always thread safe. More over they use lockfree queue to prevent locking even when multiple threads use the same logger."
> —— spdlog Wiki, Asynchronous logging

> "Using the lock-free queue under the hood improves performance drastically, though the benchmark is synthetic and such high contention may not happen in actual systems."
> —— Stack Overflow 讨论，spdlog async lock-free improvement

> "The queue does not implement a blocking enqueue operation and no timed dequeue_for operation. In my MPMCQueueAdapter I just used simple spinning with some backoff mechanism to implement the required waiting."
> —— spdlog GitHub issue #1973, 用户 Araeos

## 相关链接

- [spdlog GitHub 仓库](https://github.com/gabime/spdlog)
- [spdlog Wiki - Asynchronous logging](https://github.com/gabime/spdlog/wiki/Asynchronous-logging)
- [spdlog 异步模式 lock-free 改进讨论](https://github.com/gabime/spdlog/issues/1973)
- [spdlog MPMC 无锁队列源码分析（CSDN）](https://blog.csdn.net/Sub_lele/article/details/78428464)
- [Dmitry Vyukov 的 MPMC 环形缓冲区原始设计](https://www.1024cores.net/home/lock-free-algorithms/queues/bounded-mpmc-queue)

---
title: C++20 协程在事件驱动仿真器中的应用
description: 搜集 C++20 coroutine 在事件驱动仿真、状态机替代和异步调度器中的工程实践，聚焦编译器生成状态机、对称转移与零开销抽象。
source_url: "https://github.com/cflaviu/co_fsm"
source_type: "github"  # github-pr, github-issue, blog, doc, paper, competition
author: "cflaviu / dallison / 多源聚合"
date: "2023-2025"
tags: ["cpp20", "coroutine", "event-driven", "simulation", "fsm", "co_await", "state-machine"]
keywords: ["C++20 coroutine", "event-driven simulation", "co_await simulator", "symmetric transfer", "stackless coroutine"]
capture_date: "2025-07-02"
---

# C++20 协程在事件驱动仿真器中的应用

## 来源

- **URL**: 
  - https://github.com/cflaviu/co_fsm
  - https://github.com/dallison/co
  - https://github.com/shuai132/coro
  - https://github.com/seppeon/SCoro
- **类型**: github / blog / doc
- **作者**: cflaviu, David Allison, shuai132, seppeon
- **日期**: 2020-2025

## 摘要

C++20 无栈协程（stackless coroutine）通过 `co_await` / `co_yield` / `co_return` 将回调地狱和显式状态机压缩为编译器生成的状态机代码。在事件驱动仿真器（DES）领域，协程天然适合建模「等待下一个事件→处理→再次等待」的循环。`co_fsm` 用对称转移（symmetric transfer）实现状态间零堆分配跳转；`dallison/co` 提供了基于 `epoll/poll` 的 C++20 协程调度器，单线程内可实现多会话并发 I/O；`coro` 库则提供了完整的 `when_all` / `when_any` / Channel 等并发原语。相较于传统线程上下文切换，C++20 协程的切换代价仅为寄存器交换或编译器状态机转移，延迟极低，且天然消除锁需求（单线程调度器内串行执行）。

## 关键要点

- **编译器生成状态机**：C++20 协程将 `co_await` 挂起点编译为状态机，无需手动维护 `switch` 或 `goto` 状态表，显著降低 FSM 实现复杂度。
- **对称转移（Symmetric Transfer）**：`co_fsm` 利用对称转移实现状态间切换，无需返回调度器再分派，过渡延迟极低，且运行时无堆分配（仅在配置期分配）。
- **单线程零锁并发**：`dallison/co` 的 C++20 模式在单线程内通过 `epoll/poll` 调度协程，完全消除共享数据锁，访问内存串行化。
- **状态即协程**：每个仿真模块可写成一个 `co_await` 事件到来的协程，事件调度器只需 `handle.resume()` 即可恢复执行，语义与仿真时间推进天然吻合。
- **跨线程迁移**：协程可在线程 A 挂起，在线程 B 恢复，适合多线程 RTL 仿真器中将事件从工作线程移交到调度线程。

## 对 RTL 仿真器多线程化的启示

RTL 仿真器的核心瓶颈之一是事件回调链和模块状态机爆炸。C++20 协程提供了一种将「模块进程（always_ff / always_comb）」直接写成线性代码的能力：

1. **替代进程调度**：每个 `always_ff @(posedge clk)` 块可封装为一个协程，时钟事件作为 `co_await` 的目标。调度器不再需要维护复杂的 `Process` 状态表，只需按时间戳恢复对应协程。
2. **减少堆分配**：`co_fsm` 的运行期零堆分配特性对 RTL 仿真尤为重要——高频事件循环中反复 `new/delete` 会摧毁缓存局部性。
3. **消除锁**：若采用单线程协程调度器（类似 `co20::Scheduler`），多个仿真模块的 `process()` 在同一线程内串行执行，彻底移除互斥锁，降低缓存一致性流量。
4. **与 PDES 结合**：在保守式并行离散事件仿真中，跨 LP 的消息传递可以通过协程句柄在不同线程间迁移，避免传统线程池的任务队列开销。

## 代码示例

### 1. 基于 co_await 的仿真模块（概念示例）

```cpp
#include <coroutine>
#include <iostream>
#include <optional>

// 事件类型：时钟沿或外部信号
template<typename T>
struct EventAwaiter {
    T* value{nullptr};
    bool await_ready() const noexcept { return value != nullptr; }
    void await_suspend(std::coroutine_handle<> h) noexcept { /* 挂起到调度器 */ }
    T await_resume() const noexcept { return *value; }
};

struct SimTask {
    struct promise_type {
        SimTask get_return_object() { return SimTask{}; }
        std::suspend_never initial_suspend() noexcept { return {}; }
        std::suspend_never final_suspend() noexcept { return {}; }
        void unhandled_exception() {}
        void return_void() {}
    };
};

// 仿真模块：D 触发器
SimTask dff_module(EventAwaiter<bool>& clk, EventAwaiter<bool>& d) {
    bool q = false;
    while (true) {
        co_await clk;          // 等待时钟上升沿
        if (clk.value && *clk.value) {
            co_await d;        // 采样 D 输入
            q = d.value ? *d.value : q;
            std::cout << "q = " << q << " at time T\n";
        }
    }
}
```

### 2. dallison/co 的 C++20 调度器用法

```cpp
#include "co/coroutine_cpp20.h"

co20::Scheduler scheduler;

// 每个仿真会话一个协程
scheduler.Spawn([]() -> co20::Task {
    co_await co20::Sleep(std::chrono::nanoseconds(100));
    int fd = co_await co20::Wait(some_event_fd, POLLIN);
    // 处理事件 ...
    co_return;
});

scheduler.Run();  // 单线程事件循环
```

### 3. co_fsm 对称转移状态机（精简示意）

```cpp
#include <co_fsm.hpp>

// 状态 = 协程，等待事件并转移
co_fsm::Fsm fsm;
auto state_a = fsm.addState([](auto& event) -> co_fsm::Task {
    auto ev = co_await event;          // 挂起等待事件
    if (ev.id == EVT_CLK_RISE)
        co_await co_fsm::transfer_to_state_b; // 对称转移
});
// 配置期完成后，运行期无堆分配，转移仅为句柄交换
```

## 性能数据

| 指标 | 线程上下文切换 | C++17 有栈协程 | C++20 无栈协程 |
|------|-------------|--------------|---------------|
| 切换代价 | ~1–2 μs (内核态) | 寄存器交换 (~ns 级) | 编译器状态机转移 (~ns 级) |
| 内存占用 | 内核栈 + 用户栈 | 独立栈（KB–MB） | 协程帧（堆分配，可优化为池化） |
| 锁需求 | 必需 | 单线程调度可免锁 | 单线程调度可免锁 |
| 可调试性 | 复杂（栈回溯） | 中等 | 高（线性代码，无回调） |

> **注**：`co_fsm` 的 Ring 示例测试显示，对称转移状态机的执行速度接近原生函数调用，挂起/恢复 overhead 极小。

## 原文摘录

> "Coroutines do not suffer from a heavy context switch -- it's just swapping the machine registers to a different context (C++17 mode) or a compiler-generated state machine transition (C++20 mode)."
> —— dallison/co, *Performance and Safety*

> "The library uses symmetric transfer in transiting from one state to another. This makes the transitions quite fast. Heap allocations take place only when the FSM is being configured. During the running of the state machine, the library does not allocate or free memory."
> —— cflaviu/co_fsm

> "Using coroutines, you can write complex pieces of software, like network servers, using blocking I/O calls without a thread in sight. The coroutines yield control back to the scheduler when they are waiting for input or output. It allows you to write safe code where the program state is held on the stack of a set of coroutines instead of in complex finite state machines."
> —— dallison/co

## 相关链接

- [co_fsm – C++20 对称转移 FSM](https://github.com/cflaviu/co_fsm)
- [dallison/co – C++20 协程调度器](https://github.com/dallison/co)
- [coro – C++20 协程库（含 Channel/Mutex）](https://github.com/shuai132/coro)
- [SCoro – C++17 可重置状态机（对比 C++20 协程）](https://github.com/seppeon/SCoro)
- [C++Now 2021: Converting a State Machine to C++20 Coroutine](https://www.classcentral.com/course/youtube-converting-a-state-machine-to-a-c-20-coroutine-steve-downey-cppnow-2021-245277)

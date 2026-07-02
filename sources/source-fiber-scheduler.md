---
title: "协程与 Fiber 任务调度：C++20 无栈协程、栈切换与事件循环"
description: "搜集 C++20 coroutine 驱动的任务调度系统、P0876R18 fiber_context 提案、Boost::context / Boost::Fiber、folly::fibers 等用户级线程实现，分析栈式与无栈协程在 RTL 仿真任务切换中的适用性。"
source_url: "https://poniesandlight.co.uk/reflect/coroutines_job_system/"
source_type: "blog"
author: "Tim Gfrerer, Oliver Kowalke, Michael Eiler, Alex (StackOverflow)"
date: "2020-2024"
tags: ["coroutine", "fiber", "task-scheduler", "C++20", "boost-context", "user-level-threading", "job-system"]
keywords: ["C++20 coroutine task scheduler", "fiber task switching", "boost::context fcontext", "user-level threading simulation", "coroutine event loop"]
capture_date: "2026-07-03"
---

# 协程与 Fiber 任务调度：C++20 无栈协程、栈切换与事件循环

## 来源

- **C++20 Coroutines Driving a Job System** — Tim Gfrerer (Ponies & Light): https://poniesandlight.co.uk/reflect/coroutines_job_system/
- **P0876R18: fiber_context - fibers without scheduler** — Oliver Kowalke & Nat Goodspeed: https://www.open-std.org/jtc1/sc22/wg21/docs/papers/2024/p0876r18.pdf
- **C++20: Building a Thread-Pool With Coroutines** — Michael Eiler: https://blog.eiler.eu/posts/20210512/
- **StackOverflow — Scheduling a coroutine with a context**: https://stackoverflow.com/questions/62517752/scheduling-a-coroutine-with-a-context
- **GitHub — pal_tasks** (Ponies & Light 实现): https://github.com/tgfrerer/pal_tasks

---

## 摘要

C++20 引入的 **stackless coroutines**（无栈协程）为任务调度提供了编译器级别的 suspend/resume 支持，无需手动管理栈空间。然而，stackless 协程只能在协程体内部挂起，不能 suspend 普通函数调用栈中的叶子函数。与之相对，**stackful coroutines / fibers**（栈式协程）通过切换完整栈（`boost::context`、`fiber_context`）实现任意深度挂起，但需手动管理栈内存与边界。

本资料覆盖三类实现：

1. **Ponies & Light (pal_tasks)**：纯 C++20 无栈协程实现的 Fork-Join Job System。用 `co_await suspend_task()` 将任务挂起并重新推入调度队列，主线程与 worker 线程共同参与调度，无需自旋锁。
2. **P0876R18 fiber_context**：C++ 标准提案，提供最低层栈切换 API（`resume()` / `resume_with()`），作为构建栈式协程、green threads 的基石。分析了 x86_64 调用约定下仅需保存 6 个通用寄存器 + RSP/RIP 的高效切换机制。
3. **Michael Eiler 的 Coroutine Thread-Pool**：基于 `cppcoro` 思想的简化实现，展示 `task_promise`、awaiter、`schedule()` 入队、continuation 链式唤醒与 `sync_wait()` 阻塞等待。

---

## 关键要点

- **Stackless vs Stackful**：
  - Stackless（C++20 `co_await`）：内存占用极小（仅编译器分配的 coroutine frame），切换开销低，但**不能在非协程函数中挂起**。适合明确边界的事件驱动或任务图。
  - Stackful（`boost::context`、`fiber_context`）：保存完整栈上下文，可在任意调用深度挂起，内存开销较大（每个 fiber 需独立栈空间，通常 4KB~1MB），但 API 更直观。
- **无栈协程的 Job System 核心机制**：
  - `initial_suspend()` 返回 `std::suspend_always` → 任务创建后先挂起，由调度器决定何时 `resume()`；
  - `co_await suspend_task()` → 将当前协程句柄推回 `TaskList` 队列尾部，让出 CPU；
  - `final_suspend()` 返回自定义 `finalize_task` awaiter → 协程彻底完成后原子递减 `TaskList` 工作计数器；
  - 主线程调用 `wait_for_task_list()` 时不空转，而是亲自从队列取任务执行。
- **Fiber Context 的性能承诺**：在 x86_64 SYSV ABI 下，`resume()` 只需保存/恢复 `R12-R15, RBX, RBP` + `RSP/RIP`，行为等价于普通函数调用，CPU 周期开销与函数调用同级。
- **Continuation 链**：C++20 协程通过 `await_suspend()` 返回另一个协程句柄，可直接切换至 continuation 执行，无需经过调度器中介，减少一次入队/出队开销。
- **Boost 生态映射**：
  - `boost::context` ≈ `fiber_context`（底层栈切换）
  - `boost::fiber` ≈ 用户级线程 + 内置调度器
  - `folly::fibers` ≈ Facebook 的异步 C++ 框架，暴露 scheduler 并与事件循环（`EventBase`）集成
  - `quantum` ≈ Bloomberg 的 reactor 模式任务调度，支持流式 futures、任务优先级、预分配内存池

---

## 对 RTL 仿真器多线程化的启示

RTL 仿真器面临一个特殊问题：**事件执行通常不可重入或不可抢占**。在一个仿真时间步（time step）内，所有事件必须按确定顺序完成，才能进入下一时间步。协程/Fiber 调度提供了两种可能的解法：

1. **时间步内协作式多任务**：将每个 module 的 always 块或 eval 任务包装为 C++20 协程。当遇到 memory 访问延迟或需要等待子任务时，`co_await suspend_task()`，调度器立即切换到同一 time step 内的其他就绪任务。这避免了线程阻塞，但仍保持单 time step 的确定性顺序。
2. **Fiber 的「可抢占 eval」**：在更激进的实现中，将 Verilog 的 `always` 块编译为独立 fiber。每个 fiber 有自己的栈空间，可在任意表达式求值中间挂起。这相当于在 C++ 层面模拟硬件的并发性，但会带来巨大的栈内存开销（数万 always 块 × 栈空间）。
3. **事件循环集成**：RTL 仿真器通常已有事件循环（event loop）。`folly::fibers` 的模式值得借鉴——将 fiber manager 绑定到现有事件循环，而非替换它。这样 `co_await` 或 `fiber::yield` 本质上成为「向事件队列插入继续执行回调」。
4. **确定性考量**：无栈协程由于挂起点是编译器显式插入的（`co_await`），更容易保证跨平台的执行顺序一致性；而栈式 fiber 的切换点可能因编译器优化或 ABI 差异变得不可预测，对 RTL 仿真器这种追求 cycle-accurate 的场景是风险点。

---

## 原文摘录与代码片段

### 1. Ponies & Light — C++20 Coroutine Job System (pal_tasks)

**API 设计目标**：
```cpp
Scheduler* scheduler = Scheduler::create(3);
TaskList tasks;

tasks.add_task(
    [](int idx, Scheduler* s) -> Task {
        cout << "executing task" << idx << endl;
        co_await suspend_task();  // 挂起，让出 CPU
        cout << "resuming task" << idx << endl;
        co_return;
    }(42, scheduler)
);

scheduler->wait_for_task_list(tasks);  // 阻塞直到全部完成
delete scheduler;
```

> 关键：lambda 在传入时**立即执行**，返回一个已挂起的 `Task`（coroutine handle）。因此 `tasks.add_task` 添加的不是函数指针，而是**已就绪的协程句柄**。

**嵌套任务提交**：
```cpp
auto create_outer_task = [](int idx, Scheduler* s) -> Task {
    TaskList inner_tasks;
    for (int j = 0; j != 20; j++) {
        inner_tasks.add_task(create_inner_task(idx, j));
    }
    s->wait_for_task_list(inner_tasks);  // 内层完成后才继续
    co_await suspend_task();
    co_return;
};
```

> 这里 `wait_for_task_list` 在协程内部调用，意味着当前协程会**参与调度**内层任务，而不是阻塞线程。这是避免死锁的关键。

**Task / Promise 定义**：
```cpp
struct Task : std::coroutine_handle<TaskPromise> {
    using promise_type = ::TaskPromise;
};

struct TaskPromise {
    std::suspend_always initial_suspend() noexcept { return {}; }
    // ...
};
```

> `std::suspend_always::await_ready()` 永远返回 `false`，因此所有 `Task` 创建时即处于挂起状态。

**suspend_task 实现**：
```cpp
struct suspend_task {
    constexpr bool await_ready() noexcept { return false; }
    void await_suspend(std::coroutine_handle<TaskPromise> handle) noexcept {
        auto& promise = handle.promise();
        auto& task_list = promise.p_task_list;
        task_list->push_task(promise.get_return_object());  // 推回队列尾部
    }
    void await_resume() noexcept {}
};
```

**Eager Worker-Led Scheduling**：
```cpp
void suspend_task::await_suspend(...) noexcept {
    // ... 推回队列后，立即尝试取下一个任务执行
    coroutine_handle_t c = task_list->pop_task();
    if (c) { c.resume(); }
}
```

> Worker 线程在挂起当前任务后，不等调度器分配，**主动从队列前端偷取下一个任务**。这分散了调度压力，提高吞吐量。

**finalize_task（原子递减完成计数）**：
```cpp
void finalize_task::await_suspend(std::coroutine_handle<TaskPromise> h) noexcept {
    h.promise().p_task_list->decrement_task_count();
    h.destroy();  // 彻底销毁协程帧
}
```

### 2. P0876R18 — fiber_context 标准提案

**核心定位**：
> This paper proposes a minimal API that enables stackful context switching **without the need for a scheduler**. The API is suitable to act as building-block for high-level constructs such as stackful coroutines as well as cooperative multitasking (aka user-land/green threads that incorporate a scheduling facility).

**x86_64 切换开销分析**：
> The calling convention of SYSV ABI for x86_64 determines that general purpose registers `R12, R13, R14, R15, RBX` and `RBP` must be preserved by the sub-routine... In addition, the stack pointer and instruction pointer are preserved and exchanged too — thus, from the point of view of calling code, `resume()` behaves like an ordinary function call.

**Boost 生态映射**：
```cpp
// Boost.Fiber — 用户级线程 + 内置调度器
boost::fibers::fiber f1([chan]{ chan.push(1); ... });
boost::fibers::fiber f2([&chan]{ for(auto v: chan) { std::cout << v; } });
f1.join(); f2.join();

// folly::fibers — 与事件循环集成
folly::EventBase ev_base;
auto& fm = folly::fibers::getFiberManager(ev_base);
fm.addTask([&]{ baton.wait(); });
fm.addTask([&]{ baton.post(); });
ev_base.loop();

// quantum — reactor 模式 + 流式 futures
```

**Symmetric vs Asymmetric Coroutines**：
> Symmetric coroutines allow to suspend and switch to **any other** coroutine, while asymmetric coroutines suspend and resume **calling coroutine**. `boost::context` provides symmetric transfer; C++20 `co_await` is asymmetric by default.

### 3. Michael Eiler — Coroutine Thread-Pool（基于 cppcoro）

**最简 task_promise**：
```cpp
struct task_promise {
    task get_return_object() noexcept {
        return task{ std::coroutine_handle<task_promise>::from_promise(*this) };
    }
    std::suspend_never initial_suspend() const noexcept { return {}; }
    std::suspend_never final_suspend() const noexcept { return {}; }
    void return_void() noexcept {}
    void unhandled_exception() noexcept { std::cerr << "...\n"; exit(1); }
};
```

**schedule() awaiter — 将协程入队线程池**：
```cpp
auto schedule() {
    struct awaiter {
        threadpool* m_pool;
        constexpr bool await_ready() const noexcept { return false; }
        constexpr void await_resume() const noexcept {}
        void await_suspend(std::coroutine_handle<> coro) const noexcept {
            m_pool->enqueue_task(coro);
        }
    };
    return awaiter{this};
}
```

**Continuation 链实现**：
```cpp
struct task_promise {
    struct final_awaitable {
        bool await_ready() const noexcept { return false; }
        std::coroutine_handle<> await_suspend(std::coroutine_handle<task_promise> coro) noexcept {
            return coro.promise().m_continuation;  // 直接跳转到 continuation
        }
        void await_resume() noexcept {}
    };

    auto final_suspend() const noexcept { return final_awaitable(); }
    void set_continuation(std::coroutine_handle<> c) noexcept { m_continuation = c; }
private:
    std::coroutine_handle<> m_continuation = std::noop_coroutine();
};
```

> `std::noop_coroutine()` 是一个不执行任何操作的哨兵协程，避免空 continuation 时的未定义行为。

**sync_wait 阻塞等待（C++20 atomic_flag wait/notify）**：
```cpp
struct fire_once_event {
    void set() { m_flag.test_and_set(); m_flag.notify_all(); }
    void wait() { m_flag.wait(false); }
private:
    std::atomic_flag m_flag;
};

inline void sync_wait(task& t) {
    fire_once_event event;
    auto wait_task = [](task& t) -> sync_wait_task {
        co_await t;  // 注册本协程为 t 的 continuation
    }(t);
    wait_task.run(event);
    event.wait();  // 阻塞直到 continuation 触发 event.set()
}
```

> 注意：需要 GCC 11+ 或 Clang 才支持 `std::atomic_flag::wait/notify`。旧编译器需回退到 `std::mutex` + `condition_variable`。

### 4. StackOverflow — 脱离 coroutine 的调度策略

> 如果你需要 green threads / fibers，并且正在编写使用对称或不对称协程的调度器逻辑，那么 `C++20 coroutines` 可能不是最佳选择。此时应使用 **Boost::Fiber**（包含调度器）或 **Boost::Context**（允许对称协程）。

> 对称协程允许挂起并切换到**任意其他**协程，而不对称协程（`co_await`）只能挂起后恢复到调用者。对称性在实现用户级线程调度器时更为灵活。

**封装异步为同步的核心价值**：
> 当所有上下文切换、调度逻辑都隐藏在 `Channel`、`Queue` 或 `File` 等底层 I/O 类内部时，团队其他成员无需学习额外的并发心智模型，只需写线性代码 + 一个 `spawn()` 函数，即可避免锁、mutex 等复杂度。

---

## 相关链接

- [Ponies & Light — C++20 Coroutines Driving a Job System](https://poniesandlight.co.uk/reflect/coroutines_job_system/)
- [GitHub — pal_tasks](https://github.com/tgfrerer/pal_tasks)
- [P0876R18 — fiber_context (PDF)](https://www.open-std.org/jtc1/sc22/wg21/docs/papers/2024/p0876r18.pdf)
- [Michael Eiler — C++20: Building a Thread-Pool With Coroutines](https://blog.eiler.eu/posts/20210512/)
- [StackOverflow — Scheduling a coroutine with a context](https://stackoverflow.com/questions/62517752/scheduling-a-coroutine-with-a-context)
- [Lewis Baker — cppcoro](https://github.com/lewissbaker/cppcoro)
- [Boost.Context Documentation](https://www.boost.org/doc/libs/release/doc/html/context.html)
- [Boost.Fiber Documentation](https://www.boost.org/doc/libs/release/doc/html/fiber.html)

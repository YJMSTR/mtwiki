---
title: Multithreaded Error Handling & Assertions in C++
description: C++多线程程序中的异常处理、线程安全断言、std::terminate行为及自定义断言库的最佳实践
type: doc
source_type: doc
author: Multiple
keywords: ["thread-safe error handling", "assertion", "std::terminate", "std::system_error", "custom assert", "multithreaded exception", "C++ exception safety"]
tags: ["multithreading", "error-handling", "assertions", "C++", "debugging"]
capture_date: "2026-07-03"
---

# 多线程 C++ 错误处理与断言机制

## 来源

- Oracle Sun Studio 12 C++ User's Guide, Chapter 11: [Building Multithreaded Programs](https://docs.oracle.com/cd/E19205-01/820-7599/bkahz/index.html)
- Stack Overflow: [Writing Multithreaded Exception-Safe Code](https://stackoverflow.com/questions/329061/writing-multithreaded-exception-safe-code)
- Null Hypothesis: [Handling errno in multi-threaded C++ code](https://hnull.org/2022/06/11/handling-errno-in-multi-threaded-c-code/)
- GitHub: [gpakosz/PPK_ASSERT](https://github.com/gpakosz/PPK_ASSERT)
- GitHub: [rg3/xassert](https://github.com/rg3/xassert)

## 摘要

C++ 的异常处理机制虽然是线程安全的（一个线程中的异常不会干扰另一个线程），但异常无法跨线程传播——一个线程中抛出的异常不能在另一个线程中被捕获。当某个线程发生未捕获异常时，会调用 `std::terminate()`，默认行为是调用 `std::abort()` 终止整个进程，而非仅终止单个线程。对于多线程 RTL 仿真器，这意味着任何工作线程的断言失败或异常逃逸都会导致整个仿真进程崩溃，因此必须在每个线程入口函数中包裹 try/catch，或者使用 `std::promise`/`std::future` 将异常跨线程传递回主线程统一处理。POSIX `errno` 本身是线程安全的（自 POSIX.1c 1995 标准起），但 `strerror()` 不是线程安全的，应使用 `std::system_error` 或 `strerror_r()` / `strerror_l()`。

## 关键要点

- **异常不跨线程传播**：worker thread 抛出的异常必须通过 `std::promise` / `std::future` 或共享队列显式传递回主线程，否则将调用 `std::terminate()` 杀死整个进程
- **每个线程独立设置 `terminate()` handler**：`std::set_terminate()` 在一个线程中的调用只影响该线程的异常终止行为
- **未捕获异常 → 进程终止**：默认 `terminate_handler` 调用 `abort()`，程序必须终止，handler 不能返回（ISO 14882-2003 §18.6.1.3）
- **`strerror()` 不是线程安全的**：虽然 `errno` 是线程安全的，但 `strerror()` 在多线程环境下可能返回其他线程的错误信息；应使用 `std::system_error` 或 `strerror_r()` / `strerror_l()`
- **`pthread_cancel` 在 g++ 中通过抛出未知异常实现**：如果在 `catch(...)` 中没有重新抛出 `throw;`，会导致 `abort()`
- **自定义断言库（PPK_ASSERT, xassert）** 支持多级别断言（FATAL / ERROR / WARNING / DEBUG），可在断言失败时调用自定义 handler（如记录日志、打开调试器、而非直接 abort）

## 对 RTL 仿真器多线程化的启示

RTL 仿真器通常由主线程分派多个 worker thread 执行时间轮（time wheel）或事件处理。任何一个线程中的断言失败（如内存越界、空指针解引用）都会触发 `std::abort()` 导致整个仿真进程连同所有线程一起崩溃。为了能在崩溃前收集关键调试信息（如当前仿真时间、事件队列状态、各线程的活跃模型），建议：

1. 在每个线程入口函数外层包裹 `try { ... } catch (...) { ... }`，将异常信息写入线程安全的日志/队列
2. 使用 `std::promise<std::exception_ptr>` 将 worker thread 的异常传递回主线程，主线程统一处理并生成诊断报告
3. 使用 `std::set_terminate()` 设置自定义 terminate handler，在进程终止前打印所有线程的当前状态快照
4. 避免在 worker thread 中直接使用 `assert()`（调用 `abort()`），改用支持自定义 handler 的断言宏（如 PPK_ASSERT），在断言失败时先触发调试器断点（`__debugbreak()` / `SIGTRAP`）再优雅降级
5. 信号处理函数中不得使用 `new`/`delete`、iostream、异常或锁，否则会造成死锁

## 代码示例

### 1. 使用 `std::promise` / `std::future` 跨线程传递异常

```cpp
#include <thread>
#include <future>
#include <stdexcept>
#include <iostream>

void worker_task(std::promise<void> promise) {
    try {
        // 仿真工作：可能抛出异常
        if (/* some RTL invariant violated */) {
            throw std::runtime_error("RTL event queue corrupted");
        }
        promise.set_value();
    } catch (...) {
        promise.set_exception(std::current_exception());
    }
}

int main() {
    std::promise<void> prom;
    std::future<void> fut = prom.get_future();

    std::thread t(worker_task, std::move(prom));
    t.join();

    try {
        fut.get();  // 若 worker 抛异常，这里会重新抛出
    } catch (const std::exception& e) {
        std::cerr << "Worker thread exception: " << e.what() << "\n";
        // 此处可以统一生成 core dump 或保存调试状态
    }
}
```

### 2. 自定义 `std::terminate` Handler（进程终止前记录状态）

```cpp
#include <exception>
#include <iostream>
#include <csignal>
#include <thread>
#include <vector>

// 线程安全的全局状态快照（简化示意）
struct SimSnapshot {
    std::atomic<uint64_t> sim_time{0};
    std::atomic<int> active_threads{0};
} g_snapshot;

void custom_terminate_handler() {
    std::cerr << "[FATAL] std::terminate called. Sim time="
              << g_snapshot.sim_time.load()
              << ", active_threads=" << g_snapshot.active_threads.load() << "\n";
    // 可在此触发：
    // 1. 保存所有线程的当前调用栈（通过 libunwind / backtrace）
    // 2. 刷新日志缓冲区
    // 3. 触发 SIGTRAP 让调试器捕获（若附加了 GDB）
    std::abort();  // 必须终止，handler 不能返回
}

int main() {
    std::set_terminate(custom_terminate_handler);
    // ... 启动 RTL 仿真线程
}
```

### 3. 线程安全的 `std::system_error` 替代 `errno` + `strerror()`

```cpp
#include <system_error>
#include <fcntl.h>
#include <unistd.h>
#include <stdexcept>

// 错误写法：strerror() 在多线程下可能返回错误信息
// std::cerr << strerror(errno) << std::endl;  // ❌ 非线程安全

// 正确写法：使用 std::system_error
int fd = open("/BOGUS", O_RDONLY);
if (fd < 0) {
    throw std::system_error(errno, std::generic_category(), "open failed");
}
// catch 中 e.what() 会输出: "open failed: No such file or directory"
```

### 4. PPK_ASSERT 自定义断言 Handler（断言失败时先触发调试器）

```cpp
// 自定义断言 handler：先触发断点，再决定是否 abort
AssertAction::AssertAction my_assert_handler(
    const char* file, int line, const char* function,
    const char* expression, int level, const char* message) {

    std::cerr << "ASSERTION FAILED: " << expression
              << " at " << file << ":" << line
              << " (" << function << "): " << message << "\n";

#ifdef _DEBUG
    __debugbreak();  // Windows 调试器断点
    // raise(SIGTRAP); // Linux/macOS 调试器断点
#endif

    // 生产环境：记录日志后允许继续（WARNING 级别）或终止（FATAL 级别）
    return (level >= AssertLevel::FATAL) ? AssertAction::Abort : AssertAction::Continue;
}

// 在程序初始化时设置
ppk::assert::setAssertHandler(my_assert_handler);

// 使用宏
PPK_ASSERT(event_queue.size() > 0, "Event queue must not be empty at time %lu", sim_time);
```

### 5. `pthread_cancel` 的正确处理（g++ 中通过抛出异常实现）

```cpp
void* worker_thread(void* arg) {
    try {
        while (true) {
            // 仿真循环
            if (should_exit) return nullptr;
        }
    } catch (...) {
        // 必须重新抛出，否则会导致 abort()
        throw;  // 若移除这行，程序会以 abort 终止
    }
    return nullptr;
}
```

## 原文摘录

> "The current exception-handling implementation is safe for multithreading; exceptions in one thread do not interfere with exceptions in other threads. However, you cannot use exceptions to communicate across threads; an exception thrown from one thread cannot be caught in another."
> — Oracle Sun Studio 12 C++ User's Guide, §11.2

> "An uncaught exception will call `terminate()` which in turn calls the `terminate_handler` (which can be set by the program). By default the `terminate_handler` calls `abort()`. So, in summary, an uncaught exception will terminate the program not just the thread."
> — Stack Overflow, Michael Burr

> "In a multi-threaded program, if you use `strerror()`, your call to that function might report an error condition that occurs in a different thread. The C library has two other functions for reporting errno strings that are thread-safe: `strerror_r()` and `strerror_l()`."
> — Null Hypothesis

> "I don't recommend letting any exception remain uncaught. Wrap your top-level thread functions in catch-all handlers that can more gracefully (or at least verbosely) shut down the program."
> — Stack Overflow, j_random_hacker

## 相关链接

- [Oracle Sun Studio 12: Multithreaded C++ Programs](https://docs.oracle.com/cd/E19205-01/820-7599/bkahz/index.html)
- [Stack Overflow: Writing Multithreaded Exception-Safe Code](https://stackoverflow.com/questions/329061/writing-multithreaded-exception-safe-code)
- [Null Hypothesis: Handling errno in multi-threaded C++ code](https://hnull.org/2022/06/11/handling-errno-in-multi-threaded-c-code/)
- [GitHub: gpakosz/PPK_ASSERT](https://github.com/gpakosz/PPK_ASSERT)
- [GitHub: rg3/xassert](https://github.com/rg3/xassert)
- [C++ Reference: std::set_terminate](https://en.cppreference.com/w/cpp/error/set_terminate)

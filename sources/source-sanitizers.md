---
title: Sanitizers (TSan / ASan / MSan) for Multithreaded Simulators
description: ThreadSanitizer、AddressSanitizer、MemorySanitizer 在仿真器与多线程程序中的配置、使用方法和性能权衡
type: doc
source_type: doc
author: Multiple
keywords: ["ThreadSanitizer", "AddressSanitizer", "TSan", "ASan", "data race", "sanitizer", "simulation", "multithreaded performance", "memory leak detector"]
tags: ["multithreading", "sanitizers", "TSan", "ASan", "debugging", "RTL"]
capture_date: "2026-07-03"
---

# Sanitizer 在多线程 RTL 仿真器中的使用

## 来源

- GROMACS 2025 Documentation: [Build system overview](https://manual.gromacs.org/documentation/2025-rc/dev-manual/build-system.html)
- GROMACS 2024 Documentation: [Build system overview](https://manual.gromacs.org/2024.6/dev-manual/build-system.html)
- Clang/LLVM: [ThreadSanitizer Documentation](https://clang.llvm.org/docs/ThreadSanitizer.html)
- Clang/LLVM: [AddressSanitizer Documentation](https://clang.llvm.org/docs/AddressSanitizer.html)
- CSDN: [CppCon 2024: Building Safe and Reliable Surgical Robotics with C++](https://blog.csdn.net/TM1695648164/article/details/155538373)
- GROMACS 2022 Documentation: [Build system overview](https://manual.gromacs.org/documentation/2022-beta1/dev-manual/build-system.html)

## 摘要

Sanitizer 是编译器提供的运行时检测工具，能在不改变源代码的情况下捕获 C++ 中最危险的缺陷。对于多线程 RTL 仿真器，**ThreadSanitizer (TSan)** 是检测数据竞争（data race）的利器，但会引入 5~15 倍性能开销和 5~10 倍内存占用；**AddressSanitizer (ASan)** 检测内存越界、use-after-free、堆栈溢出，开销约 2 倍；**LeakSanitizer (LSan)** 内置于 ASan，检测内存泄漏。**MemorySanitizer (MSan)** 检测未初始化内存读取，但要求全程序及所有依赖库均用 MSan 编译。GROMACS（分子动力学仿真软件）的 CMake 构建系统提供了内置的 TSAN、ASAN、MSAN build type，其中 TSAN 配置会**禁用 atomics 实现，强制使用基于 mutex 的 ThreadMPI**，以便 sanitizer 能正确追踪内存访问。这对 RTL 仿真器具有直接参考价值：使用 TSan 时，可能需要将 lock-free 数据结构（如无锁队列）降级为 mutex 保护版本，否则 TSan 的检测会不完全。

## 关键要点

- **ThreadSanitizer (TSan)**：检测数据竞争（data race），是调试多线程 RTL 仿真器的核心工具；性能开销 5~15x，内存开销 5~10x
- **AddressSanitizer (ASan)**：检测内存越界、use-after-free、heap-buffer-overflow、stack-buffer-overflow；默认包含 LeakSanitizer (LSan)；开销约 2x
- **MemorySanitizer (MSan)**：检测未初始化内存读取；要求**整个程序及所有依赖库**均用 MSan 编译，使用门槛最高
- **UndefinedBehaviorSanitizer (UBSan)**：检测未定义行为（如整数溢出、空指针解引用、越界移位）
- **RealtimeSanitizer (RTSan)**：检测实时性违规（新兴，适用于硬实时系统）
- **GROMACS TSAN 构建配置**：禁用 atomics，改用 mutex-based 实现，以便 sanitizer 正确追踪内存访问——这对使用 lock-free 数据结构的 RTL 仿真器是重要启示
- **Sanitizer 互斥**：TSan 和 ASan 通常不能同时启用（官方支持 `ASAN+TSAN` 的组合有限），需要分别构建和运行

## 对 RTL 仿真器多线程化的启示

RTL 仿真器大量使用多线程来并行处理事件（如 Verilator 的 `--threads` 模式）。数据竞争是此类系统中最隐蔽的 bug 来源之一——一个线程在写入共享信号表时，另一个线程在读取，可能只在特定时序下才会暴露。Sanitizer 的使用策略建议：

1. **建立 CI 中的 TSan/ASan 构建管线**：与 Release 构建并行，定期（如每日或每次 PR）运行全量测试用例，使用 TSan 检测数据竞争，ASan 检测内存问题
2. **TSan 构建时降级 lock-free 结构**：若 RTL 仿真器使用了无锁队列、原子操作等 lock-free 技术，TSan 下应提供基于 `std::mutex` 的替代实现，确保 sanitizer 能正确追踪所有内存访问（参考 GROMACS 的 ThreadMPI 做法）
3. **ASan 用于检测事件队列内存泄漏**：RTL 仿真器的事件队列（event queue）经常动态分配和释放事件对象，ASan+LSan 可以捕获遗漏的释放和 use-after-free
4. **MSan 用于检测未初始化信号**：RTL 仿真中未初始化的 wire/reg 信号是常见 bug，MSan 可以检测读取未初始化内存的操作，但需确保所有依赖库（如 Verilator 生成的 C++ 代码、SystemC 库）也使用 MSan 编译
5. **性能权衡**：Sanitizer 构建的运行速度远低于 Release，因此不用于性能测试，仅用于功能正确性和并发安全性验证

## 各类 Sanitizer 功能对照表

| Sanitizer | 检测目标 | 典型编译选项 | 性能开销 | 内存开销 | 备注 |
|-----------|---------|------------|---------|---------|------|
| **AddressSanitizer (ASan)** | 内存越界、use-after-free、heap/stack/global buffer overflow | `-fsanitize=address` | ~2x | ~2x | 默认包含 LSan；不能与 TSan 同时用 |
| **ThreadSanitizer (TSan)** | 数据竞争 (data race)、race condition | `-fsanitize=thread` | 5~15x | 5~10x | 要求非 lock-free 实现以便追踪；不能和 ASan 同用 |
| **MemorySanitizer (MSan)** | 未初始化内存读取 | `-fsanitize=memory` | ~3x | ~3x | 要求全程序及所有库均用 MSan 编译 |
| **LeakSanitizer (LSan)** | 内存泄漏 | 内置于 ASan | ~1x | ~1x | 可单独使用 `-fsanitize=leak` |
| **UndefinedBehaviorSanitizer (UBSan)** | 未定义行为（整数溢出、空指针、越界移位等） | `-fsanitize=undefined` | ~1.2x | ~1x | 可细分 `-fsanitize=integer`, `null` 等 |
| **RealtimeSanitizer (RTSan)** | 实时性违规（函数执行时间超出预期） | 新兴 | — | — | 适用于硬实时系统 |

## 编译与配置示例

### 1. GCC/Clang 启用 TSan（检测数据竞争）

```bash
# 编译多线程 RTL 仿真器时使用 TSan
cmake -DCMAKE_BUILD_TYPE=TSAN \
      -DCMAKE_CXX_FLAGS="-fsanitize=thread -g -O1" \
      -DCMAKE_C_FLAGS="-fsanitize=thread -g -O1" \
      -B build-tsan

cmake --build build-tsan -j$(nproc)

# 运行测试（注意：性能开销极大，仅用于小测试集）
TSAN_OPTIONS=detect_deadlocks=1 ./build-tsan/rtl_simulator --test testcase1
```

> ⚠️ **TSan 与 Atomics**：TSan 无法正确检测基于纯原子操作（atomic）的 lock-free 数据竞争。GROMACS 的 TSAN build 配置明确**禁用 atomics，改用 mutex-based 实现**。RTL 仿真器在 TSan 构建下也应提供基于 `std::mutex` 的替代实现。

### 2. GCC/Clang 启用 ASan（检测内存问题）

```bash
# 编译时启用 ASan（默认包含 LSan）
cmake -DCMAKE_BUILD_TYPE=ASAN \
      -DCMAKE_CXX_FLAGS="-fsanitize=address -g -O1 -fno-omit-frame-pointer" \
      -DCMAKE_C_FLAGS="-fsanitize=address -g -O1 -fno-omit-frame-pointer" \
      -B build-asan

cmake --build build-asan -j$(nproc)

# 运行测试
ASAN_OPTIONS=detect_stack_use_after_return=1:detect_leaks=1 \
    ./build-asan/rtl_simulator --test testcase1
```

### 3. GROMACS 风格的 CMake 构建类型配置（参考）

```cmake
# cmake/BuildTypeTSAN.cmake
set(CMAKE_C_FLAGS_TSAN "-g -O1 -fsanitize=thread -fPIE -pie"
    CACHE STRING "Flags used by the C compiler during TSAN builds."
    FORCE)
set(CMAKE_CXX_FLAGS_TSAN "-g -O1 -fsanitize=thread -fPIE -pie"
    CACHE STRING "Flags used by the C++ compiler during TSAN builds."
    FORCE)
set(CMAKE_EXE_LINKER_FLAGS_TSAN "-fsanitize=thread -fPIE -pie"
    CACHE STRING "Linker flags during TSAN builds."
    FORCE)

# 在 CMakeLists.txt 中根据 build type 选择实现
if(CMAKE_BUILD_TYPE STREQUAL "TSAN")
    # TSan 构建：禁用 atomics，使用 mutex-based 实现
    set(RTL_USE_ATOMICS OFF)
    set(RTL_USE_MUTEX ON)
else()
    set(RTL_USE_ATOMICS ON)
    set(RTL_USE_MUTEX OFF)
endif()
```

### 4. 在代码中配合 Sanitizer 的宏定义

```cpp
// rtl_config.h
#ifdef __SANITIZE_THREAD__  // GCC/Clang 定义，当使用 -fsanitize=thread 时
    #define RTL_TSAN_BUILD 1
#else
    #define RTL_TSAN_BUILD 0
#endif

#ifdef __SANITIZE_ADDRESS__  // 当使用 -fsanitize=address 时
    #define RTL_ASAN_BUILD 1
#else
    #define RTL_ASAN_BUILD 0
#endif

// 根据 sanitizer 配置选择同步原语
#if RTL_TSAN_BUILD
    #include <mutex>
    #define RTL_ATOMIC_INT int  // 非原子，由外部 mutex 保护
    #define RTL_LOCK(m) std::lock_guard<std::mutex> lock(m)
#else
    #include <atomic>
    #define RTL_ATOMIC_INT std::atomic<int>
    #define RTL_LOCK(m)  // 空操作
#endif
```

### 5. 使用 `__attribute__((no_sanitize("thread")))` 绕过特定函数的 TSan 检测

```cpp
// 某些底层原子操作已知正确，但 TSan 无法识别，可标记为不检测
extern "C" {
__attribute__((no_sanitize("thread")))
void known_safe_atomic_write(int* ptr, int val) {
    *ptr = val;  // TSan 会忽略此处的数据竞争报告
}
}
```

> ⚠️ 谨慎使用：仅在经过严格验证的代码上使用此属性，否则会掩盖真正的数据竞争。

## TSan 数据竞争报告解读

当 TSan 检测到数据竞争时，会输出类似以下报告：

```
WARNING: ThreadSanitizer: data race (pid=12345)
  Read of size 8 at 0x7f1234567890 by thread T1:
    #0 rtl_simulator::EventQueue::pop() event_queue.cpp:45
    #1 rtl_simulator::WorkerThread::run() worker.cpp:120

  Previous write of size 8 at 0x7f1234567890 by thread T2:
    #0 rtl_simulator::EventQueue::push() event_queue.cpp:60
    #1 rtl_simulator::Scheduler::schedule() scheduler.cpp:88

  Location is global 'g_event_queue' of size 1024 at 0x7f1234567890 (event_queue.cpp:20)

SUMMARY: ThreadSanitizer: data race event_queue.cpp:45 in rtl_simulator::EventQueue::pop()
```

**解读**：
- `T1` 在 `event_queue.cpp:45` 读取 `g_event_queue`
- `T2` 在 `event_queue.cpp:60` 写入 `g_event_queue`
- 两者之间没有同步原语（mutex 或 atomic）保护，构成数据竞争

## 原文摘录

> "TSAN: Builds GROMACS for use with ThreadSanitizer in gcc and clang to detect data races. This disables the use of atomics in ThreadMPI, preferring the mutex-based implementation."
> — GROMACS 2025 Documentation, Build system overview

> "ASAN: Builds GROMACS for use with AddressSanitizer in gcc and clang to detect many kinds of memory mis-use. By default, AddressSanitizer includes LeakSanitizer."
> — GROMACS 2025 Documentation, Build system overview

> "Sanitizers are compiler-provided runtime detection tools for capturing dangerous vulnerabilities: AddressSanitizer (ASan) detects memory out-of-bounds and use-after-free; ThreadSanitizer (TSan) detects data races; LeakSanitizer (LSan) detects memory leaks; UndefinedBehaviorSanitizer (UBSan) detects undefined behavior; MemorySanitizer (MSan) detects uninitialized memory."
> — CppCon 2024, Building Safe and Reliable Surgical Robotics with C++

> "Reference build type compiles a version of GROMACS aimed solely at correctness. All parallelization and optimization possibilities are disabled."
> — GROMACS 2025 Documentation

## 相关链接

- [GROMACS 2025 Build System Overview](https://manual.gromacs.org/documentation/2025-rc/dev-manual/build-system.html)
- [GROMACS 2024 Build System Overview](https://manual.gromacs.org/2024.6/dev-manual/build-system.html)
- [Clang ThreadSanitizer Documentation](https://clang.llvm.org/docs/ThreadSanitizer.html)
- [Clang AddressSanitizer Documentation](https://clang.llvm.org/docs/AddressSanitizer.html)
- [Clang MemorySanitizer Documentation](https://clang.llvm.org/docs/MemorySanitizer.html)
- [CppCon 2024: Sanitizers in Medical Robotics](https://blog.csdn.net/TM1695648164/article/details/155538373)
- [GROMACS 2022 Build System (TSAN/ASAN/MSAN details)](https://manual.gromacs.org/documentation/2022-beta1/dev-manual/build-system.html)

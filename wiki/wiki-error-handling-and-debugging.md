---
title: 错误处理与多线程调试
description: 多线程RTL仿真器中的错误处理、GDB调试与Sanitizer使用指南，涵盖异常安全、线程级调试命令、数据竞争检测与CI集成策略
type: wiki
references: [source-mt-error-handling, source-gdb-multithread, source-sanitizers]
tags: [error-handling, debugging, GDB, sanitizer, multithreading, RTL-simulator]
keywords: [std::terminate, std::promise, ThreadSanitizer, AddressSanitizer, GDB multithread, data race, deadlock detection, PPK_ASSERT]
last_updated: 2026-07-03
---

# 错误处理与多线程调试

> 多线程RTL仿真器崩溃时，快速定位根因的能力决定调试效率。本章整合C++异常安全、GDB多线程调试技巧与Sanitizer工具链，建立从「崩溃现场」到「根因定位」的完整工作流。

---

## 1. 错误处理：线程安全与异常安全

### 1.1 异常不跨线程传播

C++异常机制是线程安全的——一个线程抛出的异常不会干扰另一个线程。但异常**无法跨线程捕获**：worker thread中抛出的异常若在thread入口函数中未被捕获，会触发`std::terminate()`，默认调用`std::abort()`终止**整个进程**，而非仅终止该线程。

```cpp
// ❌ 错误：worker thread 异常直接逃逸，导致整个进程崩溃
void worker_thread() {
    // 若此处抛出异常，未捕获 → std::terminate() → std::abort()
    throw std::runtime_error("RTL event queue corrupted");
}

// ✅ 正确：用 std::promise/future 将异常传回主线程统一处理
void worker_task(std::promise<void> promise) {
    try {
        // ... 仿真工作 ...
        if (/* invariant violated */) {
            throw std::runtime_error("event queue corrupted");
        }
        promise.set_value();
    } catch (...) {
        promise.set_exception(std::current_exception());  // 跨线程传递异常
    }
}

int main() {
    std::promise<void> prom;
    std::future<void> fut = prom.get_future();
    std::thread t(worker_task, std::move(prom));
    t.join();

    try {
        fut.get();  // 若worker抛异常，此处重新抛出
    } catch (const std::exception& e) {
        std::cerr << "Worker exception: " << e.what() << "\n";
        // 统一生成诊断报告、保存状态快照
    }
}
```

### 1.2 per-thread Terminate Handler

`std::set_terminate()` 设置自定义terminate handler，在进程崩溃前记录关键状态（仿真时间、活跃线程数、事件队列概要）。handler **不能返回**，必须以`std::abort()`结束。

```cpp
#include <exception>
#include <atomic>

struct SimSnapshot {
    std::atomic<uint64_t> sim_time{0};
    std::atomic<int>      active_threads{0};
} g_snapshot;

void custom_terminate_handler() {
    std::cerr << "[FATAL] std::terminate at sim_time=" 
              << g_snapshot.sim_time.load()
              << ", threads=" << g_snapshot.active_threads.load() << "\n";
    // 1. 刷新日志缓冲区
    // 2. 保存各线程调用栈（通过libunwind/backtrace）
    // 3. 触发SIGTRAP让调试器捕获（若GDB已attach）
    std::abort();  // 必须终止
}

int main() {
    std::set_terminate(custom_terminate_handler);
    // ... 启动仿真
}
```

### 1.3 strerror_r() 替代 strerror()

`errno`本身是线程安全的（POSIX.1c 1995起），但`strerror()`不是——多线程下可能返回其他线程的错误信息。应使用`std::system_error`或`strerror_r()`/`strerror_l()`。

```cpp
#include <system_error>
#include <cstring>
#include <fcntl.h>

// ❌ 非线程安全
// std::cerr << strerror(errno) << std::endl;

// ✅ 方案1：std::system_error（推荐）
int fd = open("/BOGUS", O_RDONLY);
if (fd < 0) {
    throw std::system_error(errno, std::generic_category(), "open failed");
}

// ✅ 方案2：strerror_r()（POSIX 线程安全）
char buf[256];
if (strerror_r(errno, buf, sizeof(buf)) == 0) {
    std::cerr << "Error: " << buf << "\n";
}
```

### 1.4 自定义断言：PPK_ASSERT / xassert

标准`assert()`调用`abort()`，无法在失败前触发调试器断点或记录诊断信息。PPK_ASSERT和xassert支持多级别断言（FATAL/ERROR/WARNING/DEBUG）和自定义handler。

```cpp
#include <csignal>

// 自定义断言handler：先触发调试器断点，再决定是否abort
AssertAction::AssertAction my_assert_handler(
    const char* file, int line, const char* function,
    const char* expression, int level, const char* message) {

    std::cerr << "ASSERTION FAILED: " << expression
              << " at " << file << ":" << line << "\n";

#ifdef _DEBUG
    __debugbreak();   // Windows: 调试器断点
    // raise(SIGTRAP); // Linux/macOS: 调试器断点
#endif

    // 生产环境：WARNING级别可继续，FATAL级别终止
    return (level >= AssertLevel::FATAL) 
           ? AssertAction::Abort 
           : AssertAction::Continue;
}

// 初始化时注册
ppk::assert::setAssertHandler(my_assert_handler);

// 使用
PPK_ASSERT(event_queue.size() > 0, 
           "Event queue must not be empty at time %lu", sim_time);
```

> ⚠️ 信号处理函数中**不得**使用`new`/`delete`、iostream、异常或锁，否则会造成死锁。

---

## 2. GDB调试：多线程崩溃现场分析

### 2.1 黄金命令：`thread apply all bt full`

分析多线程core dump时，首要命令是`thread apply all bt full`（简写`t a a bt`），一次性输出所有线程的调用栈和局部变量。

```gdb
# 列出所有线程
(gdb) info threads                    # ID、状态、当前函数
(gdb) info threads -full              # 更详细信息

# 切换线程
(gdb) thread 3                        # 切换到线程3
(gdb) bt full                         # 当前线程完整回溯+局部变量
(gdb) frame 2                         # 切换到第2帧
(gdb) info locals                     # 该帧局部变量
(gdb) info registers                  # 寄存器值

# 批量输出所有线程
(gdb) thread apply all bt             # 所有线程调用栈
(gdb) thread apply all bt full        # 所有线程调用栈+局部变量
(gdb) t a a bt                        # 简写
(gdb) thread apply 2-5 bt             # 仅线程2-5
```

### 2.2 调度器锁定：`set scheduler-locking`

单步调试时控制其他线程是否抢占，但开启后极易导致自死锁。

```gdb
(gdb) set scheduler-locking off       # 默认：其他线程可继续运行
(gdb) set scheduler-locking on        # 仅当前线程运行，其余冻结
(gdb) set scheduler-locking step      # step时锁定，next时允许其他线程
(gdb) show scheduler-locking          # 查看当前模式
```

> ⚠️ `set scheduler-locking on` 风险：若其他线程持有当前线程需要的锁，当前线程将永远等待，形成自死锁。

### 2.3 非侵入式进程快照

对运行中的进程attach后获取回溯再detach，耗时约0.1秒，用户几乎无感知。

```bash
# 不终止进程，采集所有线程回溯
pid=$(pidof rtl_simulator)
gdb -p "$pid" \
    -ex "set pagination off" \
    -ex "thread apply all bt full" \
    -ex "detach" \
    -ex "quit" > snapshot_$(date +%s).log 2>&1
```

### 2.4 GDB批量脚本自动化

将诊断命令写入脚本，崩溃后自动分析core dump。

```bash
# gdb_analyze.gdb
cat > gdb_analyze.gdb << 'EOF'
set pagination off
set logging on
set logging file gdb_analysis.log
echo === THREAD INFO ===\n
info threads
echo === ALL THREADS BACKTRACE FULL ===\n
thread apply all bt full
echo === ALL THREADS REGISTERS ===\n
thread apply all info registers
echo === DONE ===\n
quit
EOF

# 使用脚本分析core dump
gdb ./rtl_simulator core -x gdb_analyze.gdb

# 或使用 -ex 链式执行
gdb ./rtl_simulator core \
    -ex "set pagination off" \
    -ex "set logging on" \
    -ex "info threads" \
    -ex "thread apply all bt full" \
    -ex "quit"
```

### 2.5 死锁定位：`print *(pthread_mutex_t *)`

通过mutex的`__data.__owner`字段找到持有者TID，关联到GDB线程号确认死锁。

```gdb
# 假设mutex地址为0x7f1234567890
(gdb) print *(pthread_mutex_t *)0x7f1234567890
$1 = {__data = {__lock = 2, __count = 0, __owner = 1983, ...}}

# __owner = 1983 表示TID 1983持有此锁
(gdb) info threads
  Id   Target Id              Frame
  1    Thread 0x... (LWP 1983)  pthread_mutex_lock ()
  2    Thread 0x... (LWP 1984)  futex_wait ()

# 线程1(LWP 1983)持有锁，线程2(LWP 1984)在等待 → 确认死锁
```

### 2.6 日志捕获：`set logging on`

多线程回溯信息量大，启用日志避免刷屏丢失。

```gdb
(gdb) set logging on
(gdb) set logging file backtrace.log
(gdb) thread apply all bt full
(gdb) set logging off
```

### 2.7 堆栈损坏诊断

`Backtrace stopped: previous frame identical to this frame (corrupt stack?)`通常由：
- 缓冲区溢出 / 数组越界覆盖栈帧
- 未使用调试符号编译（`-g`缺失）
- 可执行文件与core文件不匹配

---

## 3. Sanitizers：编译器级运行时检测

### 3.1 功能对照表

| Sanitizer | 检测目标 | 编译选项 | 性能开销 | 内存开销 | 关键限制 |
|-----------|---------|---------|---------|---------|----------|
| **AddressSanitizer (ASan)** | 内存越界、use-after-free、堆栈缓冲区溢出 | `-fsanitize=address` | ~2x | ~2x | 默认含LSan；不能与TSan同用 |
| **ThreadSanitizer (TSan)** | 数据竞争(data race)、race condition | `-fsanitize=thread` | 5~15x | 5~10x | 需非lock-free实现以便追踪；不能与ASan同用 |
| **MemorySanitizer (MSan)** | 未初始化内存读取 | `-fsanitize=memory` | ~3x | ~3x | **全程序及所有库**均须用MSan编译 |
| **LeakSanitizer (LSan)** | 内存泄漏 | 内置于ASan | ~1x | ~1x | 可单独用`-fsanitize=leak` |
| **UndefinedBehaviorSanitizer (UBSan)** | 整数溢出、空指针解引用、越界移位等 | `-fsanitize=undefined` | ~1.2x | ~1x | 可细分`-fsanitize=integer,null`等 |
| **RealtimeSanitizer (RTSan)** | 实时性违规（函数执行超时） | 新兴 | — | — | 适用于硬实时系统 |

### 3.2 GROMACS TSAN/ASAN Build配置参考

GROMACS（分子动力学仿真软件）的CMake构建提供了内置TSAN/ASAN build type。关键启示：**TSAN配置禁用atomics，强制使用mutex-based实现**，否则sanitizer无法正确追踪内存访问。

```cmake
# cmake/BuildTypeTSAN.cmake
set(CMAKE_C_FLAGS_TSAN "-g -O1 -fsanitize=thread -fPIE -pie"
    CACHE STRING "C flags for TSAN builds." FORCE)
set(CMAKE_CXX_FLAGS_TSAN "-g -O1 -fsanitize=thread -fPIE -pie"
    CACHE STRING "CXX flags for TSAN builds." FORCE)
set(CMAKE_EXE_LINKER_FLAGS_TSAN "-fsanitize=thread -fPIE -pie"
    CACHE STRING "Linker flags for TSAN builds." FORCE)
```

### 3.3 CMake完整配置示例

```cmake
# CMakeLists.txt
if(CMAKE_BUILD_TYPE STREQUAL "TSAN")
    set(RTL_USE_ATOMICS OFF)  # TSAN下禁用atomics
    set(RTL_USE_MUTEX   ON)
elseif(CMAKE_BUILD_TYPE STREQUAL "ASAN")
    set(RTL_USE_ATOMICS ON)
    set(RTL_USE_MUTEX   OFF)
endif()

# 编译时识别sanitizer，代码中切换实现
# rtl_config.h
#ifdef __SANITIZE_THREAD__
    #define RTL_TSAN_BUILD 1
#else
    #define RTL_TSAN_BUILD 0
#endif

#ifdef __SANITIZE_ADDRESS__
    #define RTL_ASAN_BUILD 1
#else
    #define RTL_ASAN_BUILD 0
#endif
```

### 3.4 TSan数据竞争报告解读

```
WARNING: ThreadSanitizer: data race (pid=12345)
  Read of size 8 at 0x7f1234567890 by thread T1:
    #0 rtl_simulator::EventQueue::pop() event_queue.cpp:45
    #1 rtl_simulator::WorkerThread::run() worker.cpp:120

  Previous write of size 8 at 0x7f1234567890 by thread T2:
    #0 rtl_simulator::EventQueue::push() event_queue.cpp:60
    #1 rtl_simulator::Scheduler::schedule() scheduler.cpp:88

  Location is global 'g_event_queue' of size 1024 at 0x7f1234567890

SUMMARY: ThreadSanitizer: data race event_queue.cpp:45
```

**解读**：
- `T1`在`event_queue.cpp:45`读取`g_event_queue`
- `T2`在`event_queue.cpp:60`写入`g_event_queue`
- 两者之间无同步原语（mutex/atomic）保护 → 数据竞争

### 3.5 绕过已知安全代码：`__attribute__((no_sanitize("thread")))`

对于经过严格验证的底层原子操作，TSan可能误报，可标记为不检测。

```cpp
// 仅在经过严格验证的代码上使用
__attribute__((no_sanitize("thread")))
void known_safe_atomic_write(int* ptr, int val) {
    *ptr = val;  // TSan忽略此处的数据竞争报告
}
```

> ⚠️ 谨慎使用：仅在严格验证的代码上使用，否则会掩盖真正的数据竞争。

### 3.6 Sanitizer互斥与性能开销

- **TSan与ASan通常不能同时启用**：官方对`ASAN+TSAN`组合支持有限，需分别构建和运行
- **TSan 5~15x性能开销**：仅用于小测试集，不用于性能测试
- **ASan ~2x开销**：可在日常开发中频繁使用
- **分级策略**：ASan日常 → TSan专项数据竞争检测 → MSan全量未初始化检测（成本最高）

---

## 4. 对多线程RTL仿真器的启示

| 场景 | 首选工具 | 关键操作 |
|------|---------|----------|
| 多线程崩溃现场诊断 | **GDB** | `t a a bt full` 获取所有线程回溯；`set logging on`保存输出 |
| 数据竞争检测 | **TSan** | 构建TSan专用build type；禁用lock-free改用mutex实现 |
| 内存越界/泄漏 | **ASan+LSan** | 日常CI集成；检测event queue动态分配泄漏 |
| 未初始化信号 | **MSan** | 确保所有依赖库（Verilator生成代码、SystemC库）均用MSan编译 |
| 未定义行为 | **UBSan** | 低开销，可常驻开发build |
| 死锁定位 | **GDB + mutex owner** | `print *(pthread_mutex_t *)ADDR`查看`__data.__owner` |

**核心原则**：Sanitizer不能同时启用，需规划分级build矩阵；多线程崩溃时GDB是唯一直接诊断工具，Sanitizer用于预防性检测。

---

## 5. 可操作建议

### 5.1 CI集成TSan Build

在CI中添加独立的TSan build job，与Release/ASan build并行：

```yaml
# .gitlab-ci.yml / .github/workflows/ci.yml
build_tsan:
  script:
    - cmake -B build-tsan -DCMAKE_BUILD_TYPE=TSAN -DCMAKE_CXX_FLAGS="-fsanitize=thread -g -O1"
    - cmake --build build-tsan -j$(nproc)
    - TSAN_OPTIONS=detect_deadlocks=1 ctest --test-dir build-tsan --output-on-failure
```

### 5.2 GDB脚本自动化崩溃分析

将崩溃分析脚本纳入版本控制，core dump后一键诊断：

```bash
#!/bin/bash
# crash_analyze.sh
core_file=$1
exe_file=$2

gdb "$exe_file" "$core_file" \
    -ex "set pagination off" \
    -ex "set logging file analysis_$(basename $core_file).log" \
    -ex "set logging on" \
    -ex "info threads" \
    -ex "thread apply all bt full" \
    -ex "thread apply all info registers" \
    -ex "quit"
```

### 5.3 Sanitizer分级启用策略

| 阶段 | Build Type | 用途 | 运行频率 |
|------|-----------|------|----------|
| 日常开发 | ASan | 内存越界、use-after-free、泄漏 | 每次编译 |
| PR/提交前 | ASan + UBSan | 内存+未定义行为 | 每次PR |
| 夜间CI | TSan | 数据竞争检测 | 每日一次 |
| 版本发布前 | MSan | 未初始化内存 | 发布前一次 |

### 5.4 Assertion失败触发调试器断点

修改断言宏，在DEBUG构建下先触发`__debugbreak()`/`SIGTRAP`，让调试器捕获，而非直接`abort()`：

```cpp
#define RTL_ASSERT(cond, msg) \
    do { \
        if (!(cond)) { \
            std::cerr << "ASSERT: " << msg << " at " << __FILE__ << ":" << __LINE__ << "\n"; \
            __debugbreak();  /* 或 raise(SIGTRAP) */ \
            abort(); \
        } \
    } while(0)
```

### 5.5 快速检查清单

- [ ] 每个worker thread入口函数外层包裹`try/catch(...)`
- [ ] 使用`std::promise<std::exception_ptr>`将异常传回主线程统一处理
- [ ] 设置自定义`std::terminate` handler记录崩溃前状态快照
- [ ] 多线程环境中使用`strerror_r()`或`std::system_error`替代`strerror()`
- [ ] 自定义断言支持DEBUG下触发断点，生产环境优雅降级
- [ ] 编译保留`-g`符号（Release用`-O2 -g`的RelWithDebInfo）
- [ ] 启用core dump：`ulimit -c unlimited`
- [ ] CI中建立ASan日常 + TSan专项的sanitizer分级管线
- [ ] 准备GDB非侵入式快照脚本用于生产环境诊断

---

## 参考文献

- `source-mt-error-handling` — C++多线程错误处理与断言机制
- `source-gdb-multithread` — GDB多线程调试与core dump分析
- `source-sanitizers` — TSan/ASan/MSan在仿真器中的配置与使用

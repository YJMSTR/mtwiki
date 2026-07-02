---
title: Core Dump & GDB Multithreaded Debugging
description: GDB 多线程调试命令、Core Dump 分析方法、死锁检测脚本及批量自动化调试技术
type: doc
source_type: doc
author: Multiple
keywords: ["gdb multithreaded", "core dump", "thread apply all bt", "scheduler-locking", "deadlock detection", "gdb script", "pstack", "backtrace"]
tags: ["multithreading", "debugging", "GDB", "core-dump", "deadlock"]
capture_date: "2026-07-03"
---

# 多线程 Core Dump 与 GDB 调试技术

## 来源

- GDB Manual: [Backtrace](https://www.zeuthen.desy.de/unix/unixguide/infohtml/gdb/Backtrace.html)
- GDB Advanced Cheat Sheet: [Threads & Concurrency](https://gist.github.com/elmotec/99635d10683789b4eb7be708a92ac91b)
- CSDN: [gdb multithread debugging](https://blog.csdn.net/losemyheaven/article/details/50862030)
- Little Notebook: [View A Backtrace For All Threads With GDB](https://littlenotebook.uk/view-a-backtrace-for-all-threads-with-gdb/)
- Stack Overflow: [How do I get the backtrace for all the threads in GDB?](https://stackoverflow.com/questions/18391808/how-do-i-get-the-backtrace-for-all-the-threads-in-gdb)
- OSSO Blog: [gdb / backtrace / running process](https://www.osso.nl/blog/2011/gdb-backtrace-running-process/)
- CCRMA Stanford: [Multithread Backtrace in gdb](https://ccrma.stanford.edu/~jos/stkintro/Multithread_Backtrace_gdb.html)
- CSDN: [gdb core dump backtrace stopped](https://wenku.csdn.net/answer/5gbdy45k2p)
- HPE Community: [Core Dump with multi-threaded application](https://community.hpe.com/t5/operating-system-linux/core-dump-with-multi-threaded-application/td-p/3938221)

## 摘要

多线程 RTL 仿真器崩溃时，GDB 是最核心的诊断工具。`thread apply all bt`（或简写 `t a a bt`）是分析多线程 core dump 的"黄金命令"，能一次性输出所有线程的调用栈。`bt full` 进一步显示每个栈帧的局部变量。`set scheduler-locking` 可控制 GDB 在单步执行时是否冻结其他线程（`on` / `step` / `off`），但开启后容易导致进程自死锁。对于生产环境，可以使用 `gdb -p <pid> -ex 'thread apply all bt full' -ex detach -ex quit` 对运行中的进程进行"非侵入式"快照采集，耗时仅约 0.1 秒，用户几乎无感知。死锁检测的典型流程是：`info threads` → `thread apply all bt full` → 查找 `pthread_mutex_lock` / `futex_wait` → 通过 `print *(pthread_mutex_t *)<ptr>` 查看 `__data.__owner` 字段锁定线程 TID。

## 关键要点

- **`thread apply all bt`（或 `t a a bt`）**：一次性打印所有线程的 backtrace，是多线程 core dump 分析的首要命令
- **`bt full` / `thread apply all bt full`**：不仅打印调用栈，还显示每个栈帧的局部变量值，用于深入排查状态异常
- **`set scheduler-locking on|step|off`**：控制 GDB 执行命令时是否允许其他线程抢占；`on` 仅当前线程运行，但极易导致死锁
- **`info threads`**：列出所有线程的 ID、状态和当前函数；`thread <n>` 切换到指定线程
- **非侵入式快照**：`gdb -p <pid> -ex 'thread apply all bt full' -ex detach -ex quit` 可以在不终止进程的情况下获取所有线程调用栈，耗时约 0.1s
- **`set logging on`**：将 GDB 输出保存到 `gdb.txt`，避免多线程回溯信息刷屏导致无法阅读
- **core dump 堆栈损坏**：`Backtrace stopped: previous frame identical to this frame (corrupt stack?)` 通常由缓冲区溢出、数组越界、栈帧覆盖引起
- **死锁检测三步法**：`info threads` → `thread apply all bt full` → 查找 `pthread_mutex_lock` 和 `futex_wait`，并通过 mutex 的 `__owner` 字段关联 TID

## 对 RTL 仿真器多线程化的启示

RTL 仿真器通常在多线程环境下运行大量 worker thread 处理事件队列或时间推进。崩溃时，仅查看当前线程的 backtrace 往往无法定位根因——真正的死锁或数据竞争可能发生在另一个线程上。建议建立以下调试工作流：

1. **编译时开启 debug symbols**：始终使用 `-g -O0` 或 `-g -O1` 编译调试版本，保留 `-g` 在 Release 中使用 `-O2 -g`（RelWithDebInfo）
2. **启用 core dump**：`ulimit -c unlimited`，确保崩溃后能拿到 core 文件
3. **崩溃后自动化诊断**：编写 GDB 脚本，在加载 core dump 后自动执行 `thread apply all bt full`、`info threads`、`info registers`，输出到日志文件
4. **运行中定期快照**：对于长时间运行的仿真，可以周期性地使用 `gdb -p <pid> -ex 'thread apply all bt' -ex detach -ex quit` 采集线程状态，用于事后分析性能回归或死锁趋势
5. **利用 mutex owner 字段定位死锁**：在 glibc 下，`pthread_mutex_t` 的 `__data.__owner` 字段保存了当前持有锁的线程 TID，通过 `print *(pthread_mutex_t *)0xADDR` 可查看

## GDB 命令速查表

### 多线程基本操作

```gdb
(gdb) info threads                  # 列出所有线程：ID, 状态, 当前函数
(gdb) info threads -full            # 更详细的信息（需要 libthread_db）
(gdb) thread 3                      # 切换到线程 3
(gdb) thread apply all bt           # 所有线程的 backtrace
(gdb) thread apply all bt full      # 所有线程的 backtrace + 局部变量
(gdb) t a a bt                      # 简写：thread apply all backtrace
(gdb) thread apply 2-5 bt           # 仅线程 2 到 5 的 backtrace
(gdb) info thread 3                 # 线程 3 的详细信息
```

### 调度器锁定（单步调试时控制其他线程）

```gdb
(gdb) set scheduler-locking off     # 默认：不锁定，其他线程可抢占（多线程 continue/next/step 时）
(gdb) set scheduler-locking on      # 完全锁定：只有当前线程运行，其他线程全部冻结
(gdb) set scheduler-locking step    # step 时锁定（单步不抢占），next 时允许其他线程运行
(gdb) show scheduler-locking        # 查看当前模式
```

> ⚠️ **警告**：`set scheduler-locking on` 很容易导致进程自死锁——若其他线程持有当前线程需要的锁，则当前线程永远无法继续执行。

### Core Dump 分析

```bash
# 生成 core dump（运行时）
ulimit -c unlimited
./my_simulator
# 崩溃后生成 core 文件

# 使用 GDB 分析 core dump
gdb ./my_simulator core

(gdb) thread apply all bt full      # 查看所有线程的完整调用栈和局部变量
(gdb) info threads                  # 查看各线程状态
(gdb) thread 5                      # 切换到线程 5 深入分析
(gdb) bt full                       # 查看该线程的完整 backtrace
(gdb) frame 2                       # 切换到第 2 帧
(gdb) info locals                   # 查看该帧的局部变量
(gdb) info registers                # 查看寄存器
```

### 运行中进程的非侵入式快照

```bash
# 不终止进程，attach 后获取 backtrace 再 detach，耗时约 0.1s
gdb -p $(pidof my_simulator) \
    -ex "set pagination off" \
    -ex "thread apply all bt full" \
    -ex "detach" \
    -ex "quit" > snapshot_$(date +%s).log 2>&1
```

### GDB 批量脚本（自动化崩溃分析）

```bash
# 保存为 gdb_analyze.gdb
cat > gdb_analyze.gdb << 'EOF'
set pagination off
set logging on
echo === THREAD INFO ===\n
info threads
echo === ALL THREADS BACKTRACE FULL ===\n
thread apply all bt full
echo === ALL THREADS REGISTERS ===\n
thread apply all info registers
echo === DONE ===\n
quit
EOF

# 使用脚本分析 core dump
gdb ./my_simulator core -x gdb_analyze.gdb

# 或使用 -ex 链式执行
gdb ./my_simulator core \
    -ex "set pagination off" \
    -ex "set logging on" \
    -ex "info threads" \
    -ex "thread apply all bt full" \
    -ex "thread apply all info registers" \
    -ex "quit"
```

### 死锁检测：查看 mutex 持有者

```gdb
# 假设 mutex 地址为 0x7f1234567890
(gdb) print *(pthread_mutex_t *)0x7f1234567890
# 查看 __data.__owner 字段（持有该锁的线程 TID）

# 在 glibc 中，pthread_mutex_t 结构示意：
$1 = {__data = {__lock = 2, __count = 0, __owner = 1983, ...}}
# __owner = 1983 表示 TID 1983 的线程持有此锁

# 将 owner TID 映射到 GDB 线程号
(gdb) info threads
  Id   Target Id         Frame
  1    Thread 0x7f123456 (LWP 1983)  pthread_mutex_lock ()
  2    Thread 0x7f123457 (LWP 1984)  futex_wait ()
# 线程 1 (LWP 1983) 持有锁，线程 2 (LWP 1984) 在等待 -> 确认死锁
```

## 代码示例：生成可控的 core dump 的断言封装

```cpp
#include <csignal>
#include <iostream>
#include <unistd.h>
#include <sys/resource.h>

// 在仿真初始化时启用 core dump
void enable_core_dump() {
    struct rlimit rl;
    rl.rlim_cur = RLIM_INFINITY;
    rl.rlim_max = RLIM_INFINITY;
    if (setrlimit(RLIMIT_CORE, &rl) != 0) {
        std::cerr << "Warning: failed to set core dump limit\n";
    }
}

// 自定义断言：失败时先触发 SIGTRAP（让 GDB 捕获），再生成 core dump
#define RTL_ASSERT(cond, msg) \
    do { \
        if (!(cond)) { \
            std::cerr << "RTL_ASSERT failed: " << msg \
                      << " at " << __FILE__ << ":" << __LINE__ << "\n"; \
            raise(SIGTRAP);  /* 若 GDB 已 attach，此处会暂停 */ \
            abort();         /* 生成 core dump */ \
        } \
    } while (0)

// 使用示例
void event_loop() {
    enable_core_dump();
    RTL_ASSERT(event_queue != nullptr, "Event queue must be initialized");
    // ...
}
```

## 原文摘录

> "For example, if you type `thread apply all backtrace`, gdb will display the backtrace for all the threads; this is handy when you debug a core dump of a multi-threaded program."
> — GDB Manual, §8.2 Backtraces

> "By default, GDB stops all threads when any breakpoint is hit, and resumes all threads when you issue any command (such as continue, next, step, finish, etc.) which requires that the inferior process start to execute."
> — Stack Overflow, GDB Multithreading

> "Sometimes you want a backtrace or a core dump from a process that you do not want to stall. Firing up gdb would halt the process for as long as you're getting info. In comes the handy `gdb(1)` option `-ex`."
> — OSSO Blog, "gdb / backtrace / running process"

> "Deadlock check: 1. `info threads` – see which threads are waiting. 2. `thread apply all bt full` – look for `pthread_mutex_lock`, `futex_wait`. 3. Correlate owner TIDs from mutex structs to thread TIDs."
> — GDB Advanced Cheat Sheet

> "Backtrace stopped: previous frame identical to this frame (corrupt stack?)" — 原因分析：1. 堆栈损坏（Stack Corruption）是最常见原因；2. 未使用调试符号编译；3. 可执行文件与 core 文件不匹配；4. 多线程环境下的堆栈损坏。"
> — CSDN Core Dump Analysis

## 相关链接

- [GDB Manual: Backtrace](https://www.zeuthen.desy.de/unix/unixguide/infohtml/gdb/Backtrace.html)
- [GDB Advanced Cheat Sheet (Threads & Concurrency)](https://gist.github.com/elmotec/99635d10683789b4eb7be708a92ac91b)
- [GDB Multithreading - CSDN](https://blog.csdn.net/losemyheaven/article/details/50862030)
- [View A Backtrace For All Threads With GDB](https://littlenotebook.uk/view-a-backtrace-for-all-threads-with-gdb/)
- [Stack Overflow: backtrace for all threads](https://stackoverflow.com/questions/18391808/how-do-i-get-the-backtrace-for-all-the-threads-in-gdb)
- [OSSO Blog: Non-intrusive backtrace](https://www.osso.nl/blog/2011/gdb-backtrace-running-process/)
- [CCRMA Stanford: Multithread Backtrace](https://ccrma.stanford.edu/~jos/stkintro/Multithread_Backtrace_gdb.html)
- [gdb-pthread-utils Python Extension](https://github.com/gbpthreads/gdb-pthread-utils)

---
title: 多线程仿真器调试技术综述 — GDB、LLDB、rr 与确定性重放
description: 系统梳理多线程仿真器（如 Verilator、QEMU）的调试工具链，涵盖 GDB/LLDB 的线程级断点与反向调试、Mozilla rr 的记录-重放机制、以及 QEMU 内置的确定性重放（Deterministic Replay）技术，重点分析它们在调试非确定性并发 Bug 时的适用场景与实操命令。
source_url: "https://undo.io/resources/gdb-watchpoint/debugging-multithreaded-code-gdb-thread-names/"
source_type: "doc"  # github-pr, github-issue, blog, doc, paper, competition
author: "Mozilla / Undo.io / ISP RAS / 社区"
date: "2015-2025"
tags: ["gdb", "lldb", "rr", "record-replay", "multithreaded-debugging", "deterministic-debugging", "QEMU", "reverse-debugging", "simulation", "race-condition"]
keywords: ["gdb multithread", "rr record replay", "deterministic replay", "reverse debugging", "thread-specific breakpoint", "QEMU replay", "data race", "deadlock", "heisenbug"]
capture_date: "2026-07-02"
---

# 多线程仿真器调试技术综述 — GDB、LLDB、rr 与确定性重放

## 来源

- URL: https://undo.io/resources/gdb-watchpoint/debugging-multithreaded-code-gdb-thread-names/
- 类型: blog
- 作者: Undo.io
- 日期: 2025-09-22

- URL: https://republicroad.github.io/republic/diveintosystems/%E7%AC%AC3%E7%AB%A0-%E8%B0%83%E8%AF%95/3.6.%20Debugging%20Multithreaded%20Programs%20with%20GDB.html
- 类型: doc
- 作者: Dive Into Systems
- 日期: 2025

- URL: https://www.ispras.ru/en/publications/deterministic_replay_of_system_s_execution_with_multi_target_qemu_simulator_for_dynamic_analysis.pdf
- 类型: paper
- 作者: ISP RAS
- 日期: 2018

- URL: https://www.qemu.org/docs/master/devel/replay.html
- 类型: doc
- 作者: QEMU Project
- 日期: 2026

- URL: https://simplifycpp.org/books/cpp/GCC_Internals.pdf
- 类型: doc
- 作者: GCC Internals
- 日期: 2025

## 摘要

多线程仿真器（如 Verilator、QEMU、SystemC）的调试面临核心挑战：**非确定性（nondeterminism）**。线程调度顺序、数据竞争、内存序差异导致 Bug 难以复现。传统调试器（GDB、LLDB）提供线程级断点、冻结/解冻线程、反向步进（reverse stepping）等能力，但只能在一次执行中观察状态。Mozilla 的 `rr`（Record & Replay）通过**序列化线程调度**和**仅记录非确定性输入源**（系统调用返回值、信号），实现确定性重放，典型开销仅 1.2x–5x。QEMU 的 `icount` 模式则将确定性重放扩展到全系统仿真，通过指令计数精确控制外部事件（中断、网络包、输入）的注入时机，成为调试设备模型和内核驱动 Heisenbug 的终极武器。

## 关键要点

- **GDB 线程调试三板斧**：`info threads` 列出所有线程及其 LWP ID；`thread <no>` 切换上下文；`break foo thread 12` 设置线程专属断点。`thread apply all <cmd>` 对所有线程执行同一命令。
- **线程冻结与单线程步进**：GDB 默认命中断点时暂停所有线程。通过 `set scheduler-locking on` 或 Visual Studio 的「Freeze/Thaw」功能，可以只让当前线程执行，其他线程保持冻结，从而将并发问题转化为顺序问题来调试。
- **rr 的核心架构**：`rr` 并不记录完整内存状态，而是利用现代 x86 的**性能监控计数器（PMC）**追踪非确定性分支，通过序列化线程调度确保重放时执行路径完全一致。`rr record ./app` 记录后，`rr replay` 在 GDB 中启动重放会话，支持 `reverse-next`、`reverse-continue` 等反向操作。
- **QEMU 确定性重放**：QEMU 的 `-icount` 模式将虚拟时间基准从真实时间切换到**指令计数**。所有非确定性事件（键鼠输入、网络包、硬件时钟、中断）在执行时按 `事件类型 + 距上次事件的指令数` 格式写入日志。重放时按日志精确注入事件，实现完全等价的执行。这尤其适用于调试设备模型和内核驱动。
- **多线程死锁调试的 GDB 实操**：通过 `info threads` 找到所有线程的等待状态，结合 `p mymutex.__owner` 查看 mutex 所有者，可以迅速定位循环等待链。`thread apply all bt` 一次性打印所有线程的回溯栈，是诊断死锁的第一反应操作。

## 对 RTL 仿真器多线程化的启示

- **从「Heisenbug」到可复现**：RTL 仿真器引入多线程后，eval 阶段的不同线程调度顺序可能导致竞争条件（race condition），表现为时有时无的崩溃。使用 `rr` 可以在一次失败执行后无限次精确重放，从根本上消灭 Heisenbug。
- **GDB 线程断点与 Verilator 的 `mtask` 映射**：Verilator 的 `--threads` 模式将 DFG 划分为 mtask 并分配到 worker 线程。在 GDB 中，可以为每个 worker 线程设置命名（`pthread_setname_np`），并通过 `break <file>:<line> thread <tid>` 只拦截特定 mtask 的调度点，观察线程间的数据依赖违例。
- **QEMU 重放与 RTL 协同验证**：当 RTL 仿真器与 QEMU 系统仿真进行协同验证（co-simulation）时，QEMU 的 record/replay 可以确保外部 SoC 模型的事件注入是完全确定性的。这意味着 RTL 侧观察到的非确定性可以确信来源于 RTL 内部，而非 QEMU 的调度抖动。
- **反向调试在时钟域交叉（CDC）分析中的价值**：在调试跨时钟域的握手信号时，传统正向调试很难从「握手失败」的结果反推「哪一个线程先修改了信号」。`rr replay` 中的 `reverse-continue` 可以直接从失败点回退到「信号最后一次有效」的时刻，大幅缩短调试时间。
- **性能权衡**：`rr` 的 1.2x–5x 开销对于单次调试会话完全可接受；QEMU 的 icount 模式在记录时会有显著性能下降（120x 在纯 trace 模式下），但重放时只需按日志注入事件，无需实时交互。对于 RTL 仿真器，集成 `rr` 或自建轻量级 record/replay 框架（记录 scheduler 的随机种子和事件序列）是值得投资的长期基础设施。

## 原文摘录

> rr 的核心架构选择：序列化线程调度以确保确定性执行；仅记录非确定性来源（系统调用结果、信号投递）；避免完整内存日志，通过精确重放指令来实现。这使得 rr 特别适合调试数据竞争导致的堆损坏、与移动语义相关的瞬态生命周期 Bug、以及不正确的原子同步模式。—— GCC Internals

> QEMU 的确定性重放基于保存和重放非确定性事件（如键盘输入），并模拟确定性事件（如从 HDD 或 VM 内存读取）。仅保存非确定性事件使日志文件更小、仿真更快。—— QEMU Record/Replay 文档

> 在重放模式下，所有收到的网络包都会被写入事件日志；重放时，虚拟机将表现得如同实际接收了这些被记录的网络数据。—— ISP RAS 论文

> 调试多线程死锁时，使用 `thread apply all break demo.cpp:42` 在所有线程上设置断点，然后 `info threads` 查看各线程状态。通过 `p mymutex.__owner` 查看 mutex 当前所有者，可以迅速定位循环等待。—— Undo.io Blog

> GDB 中有三种线程标识：Pthreads 的 `pthread_t`、操作系统 LWP ID、以及 GDB 自己的线程编号。在大多数系统上这三者是一一对应的。—— Dive Into Systems

## 配置命令行示例

### 1. GDB 多线程调试核心命令

```bash
# 编译时保留调试信息（O0 优化级别）
gcc -g -O0 -pthread sim.c -o sim

# 启动 GDB
gdb ./sim

# 列出所有线程
(gdb) info threads
  Id   Target Id                                  Frame
* 1    Thread 0x7ffff7f96740 (LWP 2977) "main"     main () at sim.c:42
  2    Thread 0x7ffff7bff6c0 (LWP 2980) "worker0" worker_loop () at sim.c:88
  3    Thread 0x7ffff73fe6c0 (LWP 2981) "worker1" worker_loop () at sim.c:88

# 切换到线程 2
(gdb) thread 2

# 为特定线程设置断点（仅线程 2 在 foo 函数触发）
(gdb) break foo thread 2

# 对所有线程应用命令（如打印程序计数器）
(gdb) thread apply all print $pc
# 简写形式：taa print $pc

# 忽略错误地对所有线程执行命令
(gdb) thread apply all silent print errno
# 简写形式：taas print errno

# 查看线程栈回溯
(gdb) thread apply all bt

# 设置线程事件打印（观察线程创建/退出）
(gdb) set print thread-events on

# 设置调度器锁定：步进时只运行当前线程
(gdb) set scheduler-locking on
# 可选值：off（默认，全部运行）、on（仅当前）、step（单步时锁定）

# 继续运行，但仅当前线程（如 scheduler-locking=step）
(gdb) continue
```

### 2. rr 记录与重放（Record & Replay）

```bash
# 安装 rr（Ubuntu/Debian）
sudo apt install rr

# 记录程序执行（会自动处理多线程）
rr record ./verilator_sim
# 默认记录到 ~/.local/share/rr/ 目录

# 列出所有记录
rr ls

# 重放最近一次记录，自动启动 GDB
rr replay

# 在 GDB 中使用反向调试命令
(rr) reverse-next      # 反向单步，不进入函数
(rr) reverse-step      # 反向单步，进入函数
(rr) reverse-continue  # 反向运行到上一个断点/观察点
(rr) reverse-finish    # 反向执行到当前函数调用点

# 在重放中设置硬件观察点（watchpoint）
(rr) watch -l shared_var
(rr) reverse-continue  # 回退到 shared_var 最后一次被修改的位置

# 性能提示：rr 需要 /proc/sys/kernel/perf_event_paranoid <= 1
# 临时设置：
echo 1 | sudo tee /proc/sys/kernel/perf_event_paranoid
```

### 3. QEMU 确定性重放（Deterministic Replay）

```bash
# 启动记录模式（icount 必须启用）
qemu-system-x86_64 \
  -icount shift=auto,rr=record,rrfile=replay.log \
  -drive file=disk.qcow2,if=none,snapshot,id=img-direct \
  -drive driver=blkreplay,if=none,image=img-direct,id=img-blkreplay \
  -device ide-hd,drive=img-blkreplay \
  -net nic -net user,filter=replay \
  -m 4G -smp 4

# 启动重放模式
qemu-system-x86_64 \
  -icount shift=auto,rr=replay,rrfile=replay.log \
  -drive file=disk.qcow2,if=none,snapshot,id=img-direct \
  -drive driver=blkreplay,if=none,image=img-direct,id=img-blkreplay \
  -device ide-hd,drive=img-blkreplay \
  -m 4G -smp 4

# 连接 GDB 进行远程调试（QEMU 内置 gdbserver）
qemu-system-x86_64 ... -s -S  # -s = shorthand for -gdb tcp::1234, -S = freeze at startup
# 在另一个终端：
gdb-multiarch
(gdb) target remote :1234
(gdb) break driver_init
(gdb) continue

# 在重放中结合反向调试（需要 QEMU 反向执行补丁，上游化中）
# 参考: https://www.linux-kvm.org/images/d/d0/02x06b-DeterministicReplay.pdf
```

### 4. LLDB 多线程调试（macOS / clang 生态）

```bash
# 启动 LLDB
lldb ./verilator_sim

# 列出线程
(lldb) thread list

# 切换到线程 2
(lldb) thread select 2

# 为线程 2 设置断点
(lldb) breakpoint set --name foo --thread 2

# 打印所有线程的回溯
(lldb) thread backtrace all

# 逐步只运行当前线程
(lldb) settings set target.process.thread.step-avoid-nodebug true
(lldb) stepi
```

### 5. Visual Studio 冻结/解冻线程（Windows 场景参考）

```
在 Parallel Watch 窗口中：
1. 选中所有线程行 -> 右键 -> Freeze（冻结图标出现）
2. 单独选中一个线程 -> 右键 -> Thaw（该线程恢复运行）
3. 按 F11 步进时，只有未冻结的线程执行
4. 新生成的线程默认未被冻结，需要手动处理
```

## 相关链接

- [Undo.io: Debugging Multithreaded Code with GDB — Thread Names](https://undo.io/resources/gdb-watchpoint/debugging-multithreaded-code-gdb-thread-names/)
- [Dive Into Systems: 3.6. Debugging Multithreaded Programs with GDB](https://republicroad.github.io/republic/diveintosystems/%E7%AC%AC3%E7%AB%A0-%E8%B0%83%E8%AF%95/3.6.%20Debugging%20Multithreaded%20Programs%20with%20GDB.html)
- [QEMU Docs: Record/Replay](https://www.qemu.org/docs/master/devel/replay.html)
- [ISP RAS Paper: Deterministic Replay of System's Execution with Multi-target QEMU](https://www.ispras.ru/en/publications/deterministic_replay_of_system_s_execution_with_multi_target_qemu_simulator_for_dynamic_analysis.pdf)
- [Linux-KVM: Deterministic Replay and Reverse Debugging for QEMU (PDF)](https://www.linux-kvm.org/images/d/d0/02x06b-DeterministicReplay.pdf)
- [Mozilla rr GitHub](https://github.com/mozilla/rr)
- [Krybot Blog: Debugging Multithreaded Deadlocks with GDB](https://blog.krybot.com/t/debugging-multithreaded-deadlocks-with-gdb/14396)
- [Microsoft Docs: Get Started Debugging Multithreaded Applications](https://learn.microsoft.com/en-us/visualstudio/debugger/get-started-debugging-multithreaded-apps)

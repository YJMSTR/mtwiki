---
title: Deterministic RTL Simulation / Record & Replay
description: 搜集确定性仿真、记录与重放（Record & Replay）技术，包括 rr 调试器、DeLorean 硬件方案、ReEmu 全系统仿真及 RTL 级应用
source_url: "https://rr-project.org/"
source_type: "doc"  # github-pr, github-issue, blog, doc, paper, competition
author: "Mozilla rr Team; Montesinos, Ceze, Torrellas; Chen et al. (SJTU); SymbFuzz Team"
date: "2008-2024"
tags: ["deterministic-replay", "record-replay", "rr", "DeLorean", "ReEmu", "multithreaded", "parallel"]
keywords: ["deterministic RTL simulation", "record replay", "multithreaded replay", "rr debugger", "CREW protocol", "hardware-assisted replay"]
capture_date: "2025-06-14"
---

# 确定性仿真与记录重放技术

## 来源

- **URL**: https://rr-project.org/；http://www.cs.washington.edu/homes/ceze/publications/isca08_rep.pdf；https://ipads.se.sjtu.edu.cn/_media/publications/reemu-ppopp13-fix.pdf
- **类型**: 工具文档 + 学术论文
- **作者**: Mozilla rr 团队；Pablo Montesinos, Luis Ceze, Josep Torrellas；陈雨霏等（上海交大）；SymbFuzz 团队
- **日期**: 2008-2024

### 主要参考文献

- Mozilla rr: lightweight recording & deterministic debugging (https://rr-project.org/)
- DeLorean: Recording and Deterministically Replaying Shared-Memory Multiprocessor Execution Efficiently, ISCA 2008
- ReEmu: Scalable Deterministic Replay in a Parallel Full-system Emulator, PPoPP 2013
- SymbFuzz: Symbolic Execution Guided Hardware Fuzzing, MICRO 2025

## 摘要

确定性重放（Deterministic Replay）技术通过记录非确定性事件（如系统调用返回、异步中断、共享内存访问顺序）并在重放时精确复现，使得并发和多线程程序中的偶发 bug 可以被反复调试。本文档覆盖从软件级调试器（Mozilla rr）、硬件辅助方案（DeLorean）到全系统仿真器（ReEmu）的技术谱系，并分析其在 RTL 仿真器中的潜在应用——特别是多线程 RTL 仿真中的调度确定性、并发 bug 复现和快照回滚。

## 关键要点

### 1. Mozilla rr：软件级记录与重放调试器

**核心原理**：
- 使用 `ptrace` 拦截所有系统调用，记录输入输出值；重放时由 rr 模拟系统调用，不转发到内核。
- 使用处理器性能计数器（PMU）记录异步事件（如中断、信号），重放时基于计数器值精确触发。
- 因为重放时无真实 I/O 和通信，执行是确定性的，内存分配地址、寄存器值、系统调用返回完全相同。

**关键特性**：
- 低开销：单线程为主的程序记录开销仅 1.2x 左右。
- **单核模拟**：rr 本质上模拟单核机器，并行程序会被调度到单核运行。这是设计上的固有特性，使得弱内存序相关 bug 无法复现。
- 不支持与被记录进程树外共享内存的进程通信。
- 支持多进程（包括容器）和高效的反向执行（reverse execution）配合 gdb 数据观察点。

**局限性对 RTL 的启示**：rr 的单核模拟意味着它不适合直接用于多线程 RTL 仿真器的并行调度确定性记录；但其"记录事件而非记录每条指令"的思想可迁移。

### 2. DeLorean：硬件辅助的多线程确定性重放（ISCA 2008）

**核心创新**：
- 处理器以**原子块（chunk）**执行指令，类似事务内存或线程级推测（TLS）。系统只需记录这些块的全局提交顺序，而非每次共享内存访问的依赖。
- 相比记录单个共享内存依赖（FDR、RTR 等方案），DeLorean 将日志需求压缩到原来的 **0.6%-7.5%**。

**三种执行模式**：
- **OrderOnly**：记录速度接近 Release Consistency（RC）执行速度，重放速度约为 RC 的 82%；日志仅需 1.3 bits / 处理器 / kilo-instruction。
- **Stratified OrderOnly**：对日志按 Strata 设计重组，日志降至 RTR 的 7.5%，重放速度几乎不变。
- **PicoLog**：日志降至 0.05 bits / 处理器 / kilo-instruction（RTR 的 0.6%），但记录速度降至 RC 的 86%。估计 8 核 5GHz 机器一天日志仅约 20GB。

**对 RTL 的启示**：RTL 仿真器中的"事件步进"天然可视为原子块。若能记录各线程时间轮的推进顺序，而非每个信号赋值的交叉顺序，可大幅降低确定性重放的日志开销。

### 3. ReEmu：全系统仿真的可扩展确定性重放（PPoPP 2013）

**背景**：QEMU 等全系统仿真器缺乏确定性重放，限制了并发系统软件 bug 的复现。

**核心改进**：基于 CREW（Concurrent Read Exclusive Write）协议的优化
- **seqlock-like 设计**：避免频繁锁操作造成的严重竞争和饥饿。
- **最小化日志**：每个核心仅记录访问共享内存的局部信息（内存操作计数 + 版本号），依赖离线工具推导精确的共享内存依赖。
- **自动锁聚类**：将不冲突的内存对象聚类为 bulk，减少锁操作频率。

**重放算法**：
- 读操作：等待对象版本达到日志记录的版本，确保读到记录时的值。
- 写操作：等待之前所有写操作完成，并等待所有依赖读操作完成后，再执行写入。

**性能**：在 x86 多核平台仅引入 68.9% 性能开销，具有良好扩展性。支持 x86 和 ARM 全系统环境。

**对 RTL 的启示**：多线程 RTL 仿真器本质上也是全系统仿真（DUT + 调度器）。ReEmu 的 per-core 版本日志和 seqlock 设计可直接迁移：每个仿真线程维护局部信号更新版本，全局同步点验证版本一致性。

### 4. SymbFuzz：RTL 级 Checkpoint-Rollback 与确定性重放（MICRO 2025）

**应用背景**：硬件模糊测试中，需要快速回滚到之前状态以探索不同输入路径。

**技术方案**：
- 将 SMT 符号执行引擎与 UVM 的 sequencer-driver 结构集成，直接驱动 RTL 输入。
- **Checkpoint 与 Partial-Reset 加速**：使用轻量级快照机制，仅保存必要的事务历史和架构状态。可在复杂微架构状态间精确重入，无需完整系统重启。
- 在 Ibex（32 位 in-order）和 CVA6（64 位 out-of-order）等核心及多个外设 IP 上验证，无需 ISA 特定修改。

**对 RTL 的启示**：在确定性重放中，"完全重启 + 重放到某点"的开销可能很大。SymbFuzz 的轻量级 partial-reset 技术表明：仅保存与目标状态相关的子集（如寄存器、关键内存），可在多线程仿真中实现快速回滚。

### 5. 确定性重放 vs. RTL 多线程仿真

| 维度 | 软件调试 (rr) | 硬件方案 (DeLorean) | 全系统仿真 (ReEmu) | RTL 仿真的潜在方案 |
|------|---------------|---------------------|--------------------|-------------------|
| 记录粒度 | 系统调用 + PMU 事件 | 原子块提交顺序 | 共享内存对象版本 | 时间轮/事件步顺序 |
| 日志开销 | 低（1.2x） | 极低（0.6%） | 中等（68.9%） | 待研究 |
| 并行支持 | 单核模拟 | 多核原生 | 多核可扩展 | 需设计调度协议 |
| 反向执行 | 支持（gdb） | 无 | 无 | 可由快照链实现 |
| 弱内存序 | 不支持 | 需额外处理 | 需精确版本 | 一般无时序竞争 |

## 对 RTL 仿真器多线程化的启示

1. **调度确定性是核心**：多线程 RTL 仿真的非确定性主要来自事件调度顺序（哪个线程先处理同一时刻的敏感列表）和跨线程信号传递时机。DeLorean 的"原子块 + 记录提交顺序"思想可迁移：将每个时间步或 delta 周期视为原子块，记录各线程推进顺序即可重放。

2. **per-core 版本日志**：ReEmu 的 seqlock-like 版本机制启示我们——多线程 RTL 仿真器可为每个信号或信号组维护版本号，写时递增，读时校验。记录版本序列即可实现精确重放，而无需记录每个值变更。

3. **轻量级快照链**：SymbFuzz 的 checkpoint-rollback 结合 rr 的反向执行概念，可在 RTL 仿真器中构建"快照链"——在关键时间步（如时钟沿）保存增量快照，支持任意方向回滚，便于调试偶发竞争和时序异常。

4. **低开销记录策略**：rr 的"仅记录输入 + 非确定性 CPU 效果"策略启示 RTL 仿真器：若外部输入（testbench 激励、随机种子、环境中断）被完整记录，且内部调度算法是确定性的，则整个重放可以零开销推导。这要求多线程调度器本身设计为可确定性重放（如基于优先级和固定哈希的仲裁）。

## 原文摘录

> "rr records a group of Linux user-space processes and captures all inputs to those processes from the kernel, plus any nondeterministic CPU effects performed by those processes. rr replay guarantees that execution preserves instruction-level control flow and memory and register contents."
> — Mozilla rr Project

> "DeLorean uses a new execution substrate: one where processors execute large blocks of instructions atomically, separated by processor checkpoints, like in transactional memory or thread-level speculation. To capture a multithreaded execution, DeLorean only needs to record the total order in which blocks from different processors commit."
> — Montesinos et al., ISCA 2008

> "ReEmu refines the CREW protocol with a seqlock-like design, to avoid serious contention and possible starvation in instrumentation code tracks. ReEmu only logs minimal local information regarding accesses to a shared memory location, but instead relies on an offline log processing tool to derive precise shared memory dependence for faithful replay."
> — Chen et al., PPoPP 2013

> "We introduce a checkpoint and partial-reset acceleration technique. This approach uses a lightweight snapshot mechanism that saves only the essential transaction history and architectural state. It enables precise re-entry into complex microarchitectural states without requiring a full system reboot."
> — SymbFuzz, MICRO 2025

## 相关链接

- [Mozilla rr 官网](https://rr-project.org/)
- [rr Extended Technical Report](https://github.com/rr-debugger/rr/wiki)
- [DeLorean 论文 (ISCA 2008)](http://www.cs.washington.edu/homes/ceze/publications/isca08_rep.pdf)
- [ReEmu 论文 (PPoPP 2013)](https://ipads.se.sjtu.edu.cn/_media/publications/reemu-ppopp13-fix.pdf)
- [rr 深入解析](https://johnnysswlab.com/rr-the-magic-of-record-and-replay-debugging/)
- [SymbFuzz (MICRO 2025)](https://dl.acm.org/doi/10.1145/3725843.3756131)

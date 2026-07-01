---
title: "Verilator Issue #2913: Using multiple threads on tiny design shows dramatic slowdown"
source_url: "https://github.com/verilator/verilator/issues/2913"
source_type: "github-issue"
author: "skeetor (reported); gergoerdi (confirmed); wsnyder (responded)"
date: "2021-05-01"
tags: ["rtl-sim", "multithreading", "verilator", "synchronization", "overhead"]
keywords: ["verilator", "multithreading", "slowdown", "tiny design", "thread overhead", "Gantt", "macro-task"]
capture_date: "2026-07-01"
---

## 摘要

该 Issue 是 Verilator 多线程机制在小规模设计上产生**负优化**的经典实证案例。报告者 `skeetor` 使用一个极简的 Fibonacci 生成器模块（仅 32-bit 寄存器加法和赋值），发现多线程模拟不但没有加速，反而出现了显著的性能退化：

| 配置 | 耗时 |
|------|------|
| `--no-threads` | 1.896 s |
| `--threads 1` | 3.159 s |
| `--threads 4` | 7.638 s |

从单线程到 4 线程，**耗时翻了 4 倍**，甚至比单线程 Verilated 模型慢了近 3 倍。Verilator 维护者 `wsnyder` 的回应点明了核心原因：

> **Multithreading will only show speedups on much larger designs. In small designs the communication between cores will be much larger than leaving it on one core.**

这意味着 Verilator 的多线程模型基于**宏任务（macro-task）分区和线程间同步**，当设计的计算量不足以摊平线程间通信与同步开销时，多线程会严重拖累性能。

另一位报告者 `gergoerdi`（Stack Overflow 原始问题提出者）进一步指出，该问题甚至在一个更大的设计中——一个完整的 Space Invaders 街机模拟器（含 8080 核心，20468 行 Clash 生成的 Verilog）——也会出现类似的负优化。这表明**问题不单纯是"设计太小"**，而是 Verilator 的多线程调度在特定类型的工作负载上存在系统性开销过高的问题。`wsnyder` 建议其生成 Gantt 报告以分析线程负载均衡。

## 对"稀疏计算RTL仿真器多线程化"的启示

本项目（针对稀疏计算优化的 RTL 仿真器）从该 Issue 中获得的关键启示包括：

1. **线程同步开销是核心瓶颈**：Verilator 的 macro-task 分区模型在设计上需要频繁的线程间 barrier/condition variable 通信，这导致同步开销远大于并行收益。在稀疏计算场景下，如果大部分时钟周期中只有极少数信号翻转，线程间同步的开销会被进一步放大。

2. **小设计的"负优化"陷阱**：我们目标中的稀疏计算设计通常计算量本身就不大，但多线程同步开销是固定开销。因此，不能简单套用现有的多线程分区策略，必须设计**动态开销感知的调度器**，或仅在活跃信号数量超过阈值时才触发多线程执行。

3. **NUMA 和线程绑定的重要性**：Issue 中报告者提到使用了 `numactl` 但没有改善。这暗示如果基础调度模型本身开销过大，仅靠 NUMA 绑定无法解决问题。我们需要在调度模型层面减少跨线程通信，而不是依赖硬件亲和性来掩盖问题。

## 关键原文摘录

### 性能退化数据（报告者 skeetor）

> I built verilator from the latest master on running debian 10. I was using a simple module and tried to run it using multithreading, but the performance drops dramatically.
> 
> `--no-threads` : 1.89565s
> `--threads 1`: 3.15899s
> `--threads 4` : 7.63842s
> 
> Now I wonder why, because I expected an increase of performance, but not such a dramatic slowdown.

### 维护者核心回应（wsnyder）

> Multithreading will only show speedups on much larger designs. In small designs the communication between cores will be much larger than leaving it on one core.

### 更大设计中的同样问题（gergoerdi）

> @skeetor forgot to link to my original Stack Overflow question, where I stumbled upon this problem. That one is with a "real" (albeit simple) design that generates a VGA signal showing a bouncing ball. However, originally I came upon this behaviour (that multithreading slows down simulation tremendously, instead of speeding it up) in the context of a much larger design that implements a full Space Invaders arcade machine (with 8080 core and all); full (Clash-generated) Verilog of 20468 lines available on request (but I guess its specifics won't make much of a difference).
> 
> So in light of all this, @wsnyder can you characterize the circuits that *should* be able to benefit from multithreaded simulation?

### 建议的诊断工具（wsnyder）

> That sounds large enough to get some benefit but mileage varies. Can you make a Gantt report with 2 threads (see docs) and post the output please?

## 附加信息

- **状态**: Closed (resolved / answered)
- **标签**: `resolution: answered`
- **关闭时间**: 2021-05-01
- **关联 Stack Overflow**: https://stackoverflow.com/q/67335512/477476
- **核心模块代码**: 一个 Fibonacci 序列生成器（32-bit 寄存器，posedge clock 触发）

## 参考链接

- https://github.com/verilator/verilator/issues/2913
- https://stackoverflow.com/q/67335512/477476

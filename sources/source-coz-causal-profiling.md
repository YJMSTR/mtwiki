---
title: Coz Causal Profiling — 因果剖析器在并行程序中的原理与应用
description: 涵盖 Coz causal profiler 的虚拟加速（virtual speedup）原理、throughput/latency profiling 模式、在多线程 C++ 程序中的用法，以及对 RTL 仿真器多线程化的独特价值。
source_url: "https://github.com/plasma-umass/coz"
source_type: "github"
author: "Charlie Curtsinger, Emery Berger (UMass Amherst)"
date: "2015-2025"
tags: ["profiling", "coz", "causal-profiling", "multithreading", "parallel", "SOSP"]
keywords: ["virtual speedup", "causal profiling", "progress point", "critical path", "throughput", "latency"]
capture_date: "2026-07-01"
---

# Coz Causal Profiling — 因果剖析器在并行程序中的原理与应用

## 来源

- URL: https://github.com/plasma-umass/coz
- URL: https://arxiv.org/pdf/1608.03676
- URL: https://www.cs.otago.ac.nz/cosc440/readings/Coz-Curtsinger-Berger-SOSP2015.pdf
- URL: https://easyperf.net/blog/2020/02/26/coz-vs-sampling-profilers
- URL: https://manpages.ubuntu.com/manpages/noble/man1/coz.1.html
- 类型: github / paper (SOSP 2015 Best Paper)
- 作者: Charlie Curtsinger, Emery Berger (University of Massachusetts Amherst)
- 日期: 2015-2025

## 摘要

Coz 是首个实现 **Causal Profiling（因果剖析）** 的开源工具，2015 年发表于 SOSP 并获 Best Paper Award。与传统采样剖析器（如 perf、gprof）不同，Coz 不回答“哪行代码最耗时”，而是回答“**优化哪行代码能带来多少整体性能提升**”。它通过一种名为 **virtual speedup** 的技术，在运行时模拟“将某行代码加速 X%”的效果，从而建立因果链："优化函数 X → 整体性能提升 Y"。对于多线程程序，Coz 的独特价值在于能识别 **critical path** 上的瓶颈——那些导致其他线程被迫等待的代码行，而非单纯的 CPU 热点。

## 关键要点

### 1. 传统剖析器的盲区：相关性 ≠ 因果性

传统剖析器（采样、 instrumentation）报告的是代码的“CPU 时间占比”。但开发者真正想知道的是：
- 如果我优化函数 A，整体性能会提升多少？
- 为什么多线程程序中，优化一个“热点函数”有时完全无效？

答案在于：**多线程程序中，不在 critical path 上的热点，优化再多也不会加速整体执行**。线程间的同步、数据依赖、负载不均衡会掩盖局部优化的效果。传统剖析器无法区分“CPU 耗时”与“阻塞其他线程的耗时”。

### 2. Virtual Speedup — Coz 的核心机制

Coz 不实际优化代码，而是通过**虚拟加速**来预测优化效果：

```
假设：线程 T1 正在执行函数 f，同时线程 T2 执行函数 g。

实际加速 f 40%：
  T1: [f 缩短] → 整体运行时间减少
  
虚拟加速 f 40%（Coz 的做法）：
  每次 T1 执行 f 时，让 T2（及所有其他线程）暂停 f 原执行时间的 40%
  
效果：T1 的 f 相对“看起来快了 40%”，整体运行时间的变化与实际加速相同
```

**关键洞察**：虚拟加速通过“惩罚其他线程”来模拟“加速目标代码”，两者的相对时间变化等价。Coz 只需要测量总运行时间的变化，就能推断出“如果优化这行代码，性能会提升多少”。

**实现方式**：
- Coz 对目标程序进行极低开销的采样（利用 `perf_event_open` 或 macOS kperf）。
- 当采样命中被选中的代码行时，Coz 向其他线程注入延迟（pause）。
- 收集大量实验数据后，拟合出一条“虚拟加速比例 vs 整体性能提升”的曲线。

### 3. Progress Points — 定义吞吐量和延迟的度量

Coz 需要开发者标记“工作的单位”或“ latency 的起点/终点”，称为 **progress point**：

**吞吐量（Throughput）Profiling**：
```cpp
#include "coz.h"

void process_event() {
    // ... 处理一个仿真事件 ...
    COZ_PROGRESS;  // 标记一个工作单元完成
}
```
- 每执行一次 `COZ_PROGRESS`，表示完成一个“工作单元”。
- Coz 测量单位时间内 `COZ_PROGRESS` 的触发次数，即吞吐量。
- 虚拟加速某行代码后，若 `COZ_PROGRESS` 频率上升，说明优化该行能有效提升整体吞吐。

**延迟（Latency）Profiling**：
```cpp
#include "coz.h"

void handle_request() {
    COZ_BEGIN("event_latency");   // 事件处理开始
    // ... 仿真一个事件的时间推进 ...
    COZ_END("event_latency");     // 事件处理结束
}
```
- 使用 `COZ_BEGIN` / `COZ_END` 标记一对事件。
- Coz 通过 Little's Law 计算平均延迟，无需追踪单个事务 ID。
- 报告格式："优化行 L，延迟降低 X%"

**命令行指定 progress points**（实验性功能，有时不稳定）：
```bash
coz run --source-scope src/ --progress src/main.cpp:42 --- ./my_sim
```

### 4. Coz 命令行用法

```bash
# 基本用法（程序需带 -g 编译，保留 DWARF 调试信息）
coz run --- ./my_sim arg1 arg2

# 指定输出文件名
coz run -o my_sim.coz --- ./my_sim

# 限制剖析范围（只剖析特定源文件/可执行文件）
coz run --source-scope src/engine/% --binary-scope MAIN --- ./my_sim

# 只评估特定行的优化潜力
coz run --fixed-line src/scheduler.cpp:128 --fixed-speedup 50 --- ./my_sim

# 生成并查看因果剖析报告（自动打开浏览器）
coz plot

# 文本模式报告（适合 CI 流水线）
coz plot --text
```

**前置要求**：
```bash
# Linux 下调低 perf_event_paranoid 以允许用户态采样
sudo sh -c 'echo 1 > /proc/sys/kernel/perf_event_paranoid'

# 编译程序时必须保留调试信息
g++ -O2 -g -pthread -o my_sim my_sim.cpp
```

### 5. Coz 报告解读

Coz 输出的不是传统火焰图，而是**因果曲线图**：
- **X 轴**：虚拟加速比例（0% ~ 100%）
- **Y 轴**：吞吐量提升（或延迟降低）百分比
- **每条线**：对应一个被测试的源码行

**理想的优化目标**：
- 曲线斜率大、且延伸到较高 X 值的代码行。
- 这意味着：即使只优化 20%，整体吞吐也提升明显；如果完全优化，提升更大。

**危险的优化陷阱**：
- 传统剖析器显示“热点”，但 Coz 曲线平坦 → 说明优化该行不会提升整体性能（不在 critical path 上）。
- 多线程程序中常见：某个线程的 CPU 热点实际上在等待另一个线程，优化它只会让它等得更快，整体不会加速。

### 6. Coz 的局限性与演进

- **仅支持 native 代码**：C/C++/Rust 可行；Python、JS 等解释型语言不支持。
- **需要 progress points**：开发者必须定义工作单元，纯计算型无事务边界的程序不太适用。
- **SCOZ**：2020 年提出的系统级因果剖析器，将 virtual speedup 目标从线程扩展到 CPU 核心，可分析内核代码和多进程应用。
- **AI 辅助**：新版 Coz viewer 支持 LLM（Claude/GPT-4o）基于因果剖析结果给出优化建议。

## 对 RTL 仿真器多线程化的启示

1. **Critical Path 思维**：RTL 仿真器多线程化后，最容易犯的错误是“优化了 CPU 热点，但仿真总时间没变”。Coz 强迫开发者从 critical path 角度思考：哪些代码行拖慢了整体仿真推进？

2. **Progress Point 的天然映射**：RTL 仿真器天然有“工作单元”——仿真事件（event）、仿真周期（time step）、事务级请求（TBM）。
   - 在事件循环末尾放 `COZ_PROGRESS` → 测量“每秒处理事件数”
   - 在周期推进前后放 `COZ_BEGIN/COZ_END` → 测量“平均周期延迟”
   - 这比盲目优化某个 eval 函数更有方向感。

3. **验证并行化策略**：假设你尝试了两种并行方案：
   - A：按模块分线程，各模块有独立事件队列
   - B：按时间片分线程，全局队列加锁
   用 Coz 分别跑两次，对比因果曲线。若方案 A 的瓶颈曲线更平缓，说明其 critical path 更短，扩展性更好。

4. **与 perf 互补**：先用 `perf c2c` 排除 false sharing，再用 `perf record` 找到 CPU 热点，最后用 Coz 验证“优化这些热点是否真的能加速整体仿真”。三层验证避免“负优化”。

5. **回归测试集成**：Coz 的 `--text` 输出可以解析，适合在 CI 中设定规则：如果某次提交的 causal curve 斜率下降（即优化潜力变小），说明引入了新瓶颈。

## 原文摘录

> "Coz employs a novel technique we call causal profiling that measures optimization potential. This measurement matches developers' assumptions about profilers: that optimizing highly-ranked code will have the greatest impact on performance." — Coz GitHub README

> "A causal profiler uses the novel technique of virtual speedups to mimic the effect of optimizing a specific line of code by a fixed amount. A line is virtually sped up by inserting pauses to slow all other threads each time the line runs. The key insight is that this slowdown has the same relative effect as running that line faster." — Coz Paper, SOSP 2015

> "Causal profiling further departs from traditional profiling by making it possible to view the effect of optimizations on throughput and latency. To profile throughput, developers specify a progress point, indicating a line in the code that corresponds to the end of a unit of work." — Coz Paper, SOSP 2015

> "Coz imposes low execution time overhead (mean: 17%, min: 0.1%, max: 65%), making it substantially faster than gprof (up to 6x overhead)." — Coz Paper, SOSP 2015

> "Using traditional profilers provides little direction, but with Coz's guidance, over the course of three hours we were able to increase the performance of these applications by 8% and 20%, respectively." — Coz Paper (PARSEC benchmark case study)

> "The articles methodology analyzed each thread's blocking point, but they may not be the whole program's blocking point because they may not be on the critical path (there are causal relationships between threads)." — Denis Bakhvalov, Coz vs Sampling Profilers

## 相关链接

- [Coz GitHub Repository](https://github.com/plasma-umass/coz)
- [Coz Paper: Finding Code that Counts with Causal Profiling (SOSP 2015)](https://arxiv.org/pdf/1608.03676)
- [Coz Paper PDF ( Otago mirror)](https://www.cs.otago.ac.nz/cosc440/readings/Coz-Curtsinger-Berger-SOSP2015.pdf)
- [Coz vs Sampling Profilers - Easyperf](https://easyperf.net/blog/2020/02/26/coz-vs-sampling-profilers)
- [SCOZ: System-wide Causal Profiler (2020)](https://www.x-mol.com/paper/1324798944436523008)
- [Coz Manpage (Ubuntu)](https://manpages.ubuntu.com/manpages/noble/man1/coz.1.html)
- [Papers We Love: Coz Presentation](https://paperswelove.org/chapter/montreal)

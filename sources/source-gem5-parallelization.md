---
title: "gem5 仿真器并行化分析"
source_url: "https://github.com/gem5/gem5"
source_type: "github-code"
author: "gem5 Consortium"
date: "2011-2025"
tags: ["github", "parallel-code", "cpp", "simulator", "gem5", "pdes", "multi-core"]
keywords: ["gem5", "parallel-discrete-event-simulation", "PDES", "par-gem5", "parti-gem5", "timing-mode", "quantum-based"]
capture_date: "2026-07-01"
---

# gem5 仿真器并行化分析

## 来源

- URL: <https://github.com/gem5/gem5>
- 类型: github-code / 学术论文
- 作者: gem5 Consortium / RWTH Aachen University
- 日期: 2011-2025

## 摘要

gem5 是一个广泛使用的全系统体系结构仿真器，支持 ARM、x86、RISC-V 等 ISA。其原生内核是**单线程离散事件仿真（DES）**，即使模拟的系统有上百核，也只有一个主机线程执行所有事件。这导致仿真速度极低（ timing 模式下通常 0.01-0.1 MIPS）。近年来出现了多个并行化分支：par-gem5（原子模式并行）、parti-gem5（时序模式并行）、SplitSim（进程级分解）。

## 关键要点

### 1. 原生 gem5：单线程 DES

gem5 的事件调度核心基于全局事件队列（event queue），所有 SimObject（CPU、cache、memory 等）的事件按时间戳排序，由单个线程依次处理。

> "gem5 is mostly single threaded. All of the CPUs in your simulated system, and all of the other objects like caches, etc. are simulated in a single host thread."
> — gem5-users mailing list

### 2. par-gem5: Parallelizing gem5's Atomic Mode (DATE 2023)

**论文**: "par-gem5: Parallelizing gem5's Atomic Mode" by N. Zurstraßen et al., RWTH Aachen.  
**核心方法**: 基于量子（quantum-based）的保守式并行离散事件仿真（PDES）。

- 将时间划分为固定长度的量子（quantum）；
- 在每个量子内，不同核心的事件可以并行处理；
- 量子边界处进行全局同步；
- 允许时间误差（temporal errors）存在，但保证功能正确性。

**结果**：在 128 核主机上模拟 128 核 ARM MPSoC，**加速比达 124.7x**（原子模式）。

### 3. parti-gem5: Timing Mode Parallelised (SAMOS 2023)

**论文**: "parti-gem5: gem5's Timing Mode Parallelised" by Cubero-Cascante et al., RWTH Aachen.  
**核心方法**：扩展 par-gem5 以支持 gem5 的 **timing mode**（包括 O3CPU 和 Ruby cache/interconnect 模型）。

- 基于保守式 PDES，使用 LTSF（Lower Time Stamp First）协议；
- 将仿真域划分为多个 LP（Logical Process），每个 LP 有自己的局部事件队列；
- 在量子边界同步，通过跨域消息处理共享资源访问（cache、memory bus）。

**结果**：在 64 核 AMD Ryzen 3990x 主机上模拟 120 核 ARM MPSoC，**加速比达 42.7x**，总仿真时间误差低于 15%。

```
关键发现：
- 数据共享和交换量高的应用（如 canneal, dedup, ferret）加速比低（3.6x-10x），误差高；
- 数据独立、基于 barrier 的应用（如 blackscholes, swaptions）加速比高（12x-21x），误差低。
```

> "The extent of speedup achieved relies on the scalability of the simulated multi-thread software workload. Our evaluations reveal that applications based on barriers and those with limited data sharing derive the greatest benefit from parti-gem5."
> — parti-gem5 论文

### 4. SplitSim: 进程级并行分解

SplitSim 采用另一种策略：将 gem5 仿真分解为多个独立进程，每个进程模拟一个处理器核心，通过消息通道（SimBricks channel）通信。

- 每个核心一个 gem5 进程，原生事件循环保持串行；
- 跨核心通信通过外部消息通道转发；
- 对于 8 核模拟，获得了约 **5x 加速**；从 8 核扩展到 44 核，仿真时间仅增加 2x。

> "We leverage this and implement a SplitSim adapter for this interface, that forwards these messages across a SimBricks channel to a different process. This required roughly 1000 LoC of code to be added to gem5, without intrusive changes required."
> — SplitSim 论文

### 5. 共享资源串行化问题

所有并行 gem5 方案都面临同一个核心挑战：共享资源（cache、memory bus、interconnect）的访问必须串行化。

- parti-gem5 使用 mutex 保护共享资源，导致高数据共享 workload 性能下降；
- 时间误差主要来自跨域事件（cross-domain events）的延迟同步。

## 对 RTL 仿真器多线程化的启示

1. **PDES 是可行的但需权衡精度**：gem5 的 parti-gem5 证明，即使是对时序敏感的全系统仿真，也可以通过量子同步的 PDES 获得显著加速。对于 RTL 仿真器，如果精度要求允许微小的时间偏差，PDES 是扩展性的可行路径。

2. **数据共享是并行化的最大敌人**：parti-gem5 的结果明确显示，高数据共享 workload 的加速比显著低于独立 workload。RTL 仿真中的共享信号（总线、全局复位、时钟）是天然的串行瓶颈。需要在分区时尽量减少跨域共享状态。

3. **量子大小是精度-性能权衡的关键**：量子越大，同步开销越小，但时间误差越大；量子越小，精度越高，但同步越频繁。RTL 仿真中，量子可以对应为组合逻辑稳定时间或时钟周期边界。

4. **进程级分解 vs 线程级并行**：SplitSim 的进程级分解侵入性更小（仅 1000 行代码），但通信开销更高。对于 RTL 仿真器，如果目标是单机多核，线程级并行更轻量；如果是多机分布式，进程级分解更自然。

5. **缓存/内存层次是隐式共享资源**：RTL 仿真器在主机上运行时，所有线程共享 LLC 和内存带宽。像 gem5 一样，如果不同线程模拟的模块频繁访问同一主机内存区域，会产生 false sharing 和缓存竞争。Verilator 的变量 footprint 分组策略正是为了解决此问题。

## 相关链接

- [gem5 GitHub](https://github.com/gem5/gem5)
- [par-gem5 论文 (DATE 2023)](https://past.date-conference.com/proceedings-archive/2023/DATA/16.pdf)
- [parti-gem5 论文 (arXiv)](https://arxiv.org/html/2308.09445v2)
- [SplitSim 论文](https://pure.mpg.de/rest/items/item_3661742_3/component/file_3661743/content)
- [gem5-users: Multithreading in gem5](https://gem5-users.gem5.narkive.com/h4v8Xu4v/multithreading-in-gem5-full-system-mode)
- [Simulating Multi-Core RISC-V Systems in gem5](https://www.csl.cornell.edu/~cbatten/pdfs/ta-gem5-riscv-carrv2018.pdf)

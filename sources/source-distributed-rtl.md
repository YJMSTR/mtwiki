---
title: 分布式 RTL 仿真（Multi-Node MPI）资料汇编
description: 搜集利用 MPI 在 HPC/多节点集群上并行 RTL 仿真的方法，包括 Metro-MPI、Parendi 及商业仿真器的分布式扩展
source_url: "https://upcommons.upc.edu/handle/2117/390396"
source_type: "paper"
author: "Guillem López Paradís, Jonathan Balkind 等"
date: "2023-2025"
tags: ["distributed-rtl", "mpi", "multi-node", "hpc", "verilator", "parallel-simulation", "bsp"]
keywords: ["Metro-MPI", "Parendi", "MPI barrier", "Verilator multithreading", "BSP", "latency-insensitive interface", "OpenPiton", "IPU", "HPC cluster"]
capture_date: "2025-07-18"
---

# 分布式 RTL 仿真（Multi-Node MPI）资料汇编

## 来源

- [Metro-MPI: Fast Behavioural RTL Simulation of 10B Transistor SoC Designs (DATE 2023)](https://upcommons.upc.edu/handle/2117/390396)
- [Parendi: Thousand-Way Parallel RTL Simulation (ASPLOS 2025)](https://arxiv.org/abs/2403.04714)
- [Metro-MPI++ (GSoC 2024 / 扩展项目)](https://kislay536.github.io/projects/Metro-MPI++/)
- [FOSSi Foundation GSoC 2024 — Scaling Essent with Metro-MPI](https://fossi-foundation.org/gsoc/gsoc24-ideas)
- [Intel PIUMA Multi-Node Simulation](https://arxiv.org/abs/2010.06277)
- [ARENA — SST + MPI + PyMTL](https://arxiv.org/abs/2011.04931)

## 摘要

随着 SoC 规模达到百亿晶体管、上千核心，单节点 RTL 仿真已成为严重瓶颈。分布式 RTL 仿真通过利用芯片设计中的**天然边界**（NoC、AXI 等延迟不敏感接口）将设计分区到多个 MPI 进程，在 HPC 集群上并行运行。Metro-MPI 是这一领域的代表性工作，在 OpenPiton+Ariane 上实现了 **2.7 MIPS** 的吞吐量（1,024 核心，100亿+晶体管）。Parendi 则进一步将 RTL 仿真映射到 **Graphcore IPU** 的 5,888 核上，利用 Bulk-Synchronous Parallel (BSP) 模型达到比高端 x64 系统快 **4 倍** 的性能。两者共同揭示了分布式 RTL 仿真的核心挑战：同步开销、通信量、计算分区。

## 关键要点

### 1. Metro-MPI — 基于 MPI 的通用分布式 RTL 仿真

#### 核心思想
- **利用芯片天然边界**：现代 SoC（尤其是多核/众核）通过 NoC、AXI 等延迟不敏感接口连接可复用的同构模块（Tile）。Metro-MPI 将这些模块划分为独立的仿真进程，通过 MPI 消息传递进行每周期同步。
- **通用方法论**：适用于 Verilator（开源）和"三大"商业仿真器，只需对 RTL 设计做最小修改（主要是接口适配）。

#### 性能数据（OpenPiton+Ariane，2D Mesh NoC，1–1024 核心）

| 芯片规模 | 1x1 | 2x2 | 4x4 | 8x4 | 8x8 | 32x32 |
|---------|-----|-----|-----|-----|-----|-------|
| 核心数 | 1 | 4 | 16 | 32 | 64 | 1,024 |
| 编译时间 (min) | 5 | 9 | 25 | 82 | 296 | 4,167 |
| 仿真速度 | 基础 | 显著提升 | 接近线性 | 良好 | 良好 | 2.7 MIPS |

- **vs 顺序仿真**：最高 **135.98×** 加速（32x32 NoC）。
- **vs Verilator 多线程**：在单节点上 Metro-MPI 比 Verilator 自动多线程快 **5.64× (4x4)** 和 **9.29× (8x4)**。
- **商业仿真器**：16 核 x64 单节点上，4x4 设计获得 **8.44×** 仿真时间加速、**7.08×** CPS 加速、**7.35×** IPS 加速。
- **能耗**：典型回归测试能耗降低 **2.53×**。

#### 实验环境
- HPC 节点：2× Intel Xeon Platinum 8160（24 核，32MB LLC），2.10GHz，96GB DDR4。
- 网络：100 Gbit/s Intel Omni-Path。
- 最大配置：32x32 NoC（1,024 核）使用 22 个节点。
- 编译器：Verilator v4.034，GCC v10.1，Intel MPI v2017.7，编译标志 `-Os`（针对 I-Cache 瓶颈优化）。

#### 设计假设
- 每个 Tile 保守估计约 1,300 万晶体管（128-bit share vector）。
- 1,024 Tile 芯片总计超过 **100 亿晶体管**。
- 使用 OpenPiton L2 修改版，coherence share vector 扩展至 1,024 bits。
- 测试负载：Ariane 核心通过原子操作传递 token，与相邻核心同步通信。

### 2. Parendi — 千路并行 RTL 仿真（Graphcore IPU）

#### 核心思想
- **BSP 模型**：每 RTL 周期包含两个全局 barrier（计算 → 通信 → 计算）。
- **Fiber 概念**：每个 RTL 寄存器的 `next` 值的最小计算单元称为 fiber。Compiler 将 fiber 分区到 IPU tile（1,472 tiles/IPU，最多 4 IPU = 5,888 tiles）。
- **超图划分**：使用 KaHyPar 库对 fiber 超图进行 k-way 划分，最小化跨分区通信（cut）。

#### 性能数据

| 对比项 | 配置 | 结果 |
|--------|------|------|
| vs Verilator (x64) | 大设计 | 最高 **4.0×** 加速 |
| 编译时间 | 大设计 | 比 Verilator 快 **12×** |
| 内存占用 | 大设计 | 比 Verilator 少 **18×** |
| 单 IPU 强扩展 | 184 → 1472 tiles | 性能单调提升 |
| 多 IPU 扩展 | 1472 → 5888 tiles | 额外 **60%** 性能提升（lr9 设计）|

- **关键观察**：IPU 内部通信便宜，跨 IPU 边界通信昂贵（与跨 chiplet/socket 类似）。
- **Verilator 多线程局限**：x64 上超过 28 线程（socket 边界）后性能下降；IPU 上可扩展到 5,888 tiles。

#### 同步开销分析
- **IPU**：硬件 barrier 仅需几百个 IPU 周期；几千条指令即可掩盖同步开销。
- **x64**：用户空间原子 barrier 需数千周期；需数十万条指令才能掩盖同步开销。
- **结论**：x64 不适合细粒度并行 RTL 仿真；IPU/Groq/Cerebras 等具备低延迟同步和大容量 SRAM 的架构更适合。

### 3. Metro-MPI++ — 编译器层面的分区感知

- **问题**：现有并行仿真器（包括 Verilator 多线程）未给编译器/解析器提供硬件设计的物理结构信息，导致 AST 构造、elaboration、优化遵循通用软件编译器（如 GCC）的标准路径，忽略 HDL 携带的硬件边界信息。
- **目标**：在编译器前端就引入设计分区信息，使分区决策能影响 MPI 通信拓扑，减少跨进程数据移动。

### 4. Essent + Metro-MPI（GSoC 2024）

- **Essent**：高性能 FIRRTL 仿真器生成器，输出 C++ 编译为快速仿真器。
- **目标**：将 Metro-MPI 集成到 Essent 中，使 Essent 能用 MPI 在不同分区间通信，并影响分区决策。
- **里程碑**：(1) 使用 MPI 在分区间通信以加速仿真；(2) 让分区决策考虑 MPI 通信开销。

### 5. Intel PIUMA — 多节点仿真基础设施

- **FSim**：功能仿真器，基于 MPI 在多台主机上运行，处理大量线程和内存需求。
- **Sniper**：时序仿真器，作为单节点多线程应用运行，避免跨机器同步瓶颈。
- **规模**：成功模拟了最多 **256 个 PIUMA 块**（32 芯片，16,896 线程）。
- **FPGA 验证**：RTL 团队通过 FPGA  emulation 在流片前修复了 50+ 关键 bug。

### 6. ARENA — SST + MPI + PyMTL

- **SST (Structural Simulation Toolkit)**：扩展为基于 MPI 的多节点集群模拟。
- **PyMTL**：单节点周期精确仿真，生成可综合 Verilog 用于功耗/面积/时序分析。
- **网络**：1D Torus Ring，80 Gb/s 网络接口，每节点 1μs 跳延迟。

## 对 RTL 仿真器多线程化的启示

1. **延迟不敏感接口是分区关键**：Metro-MPI 的核心洞察 —— NoC、AXI、AXI-Stream 等接口天然具有延迟不敏感特性，意味着跨分区的信号可以延迟一个或数个周期传递而不破坏功能正确性。这为多线程仿真器的模块级并行提供了理论基础：按 AXI/NoC 接口切分设计，每个线程/进程独立推进内部状态，仅在这些标准接口处同步。

2. **同步开销决定可扩展性上限**：Parendi 的定量分析表明，x64 的 barrier 同步开销极高（数千周期），需要数十万指令才能掩盖；IPU 的硬件 barrier 仅需几百周期。对于多线程 RTL 仿真器，这意味着：
   - 若采用 BSP 模型，每周期两次全局 barrier 在多核 x64 上成本过高；
   - 更实际的做法是**局部同步**（如按模块层次或时钟域划分），减少全局 barrier 频率；
   - 或采用**乐观同步**（Time Warp / optimistic synchronization），允许进程超前推进，冲突时回滚。

3. **通信量 > 通信距离**：Parendi 的实验显示，IPU 内部通信延迟主要取决于每 tile 发送的字节数（b），而非 tile 总数（m）；跨 IPU 时则取决于总通信量（m×b）。这提示多线程仿真器：在分区时应优先**最小化跨线程通信量**（如让频繁交互的模块在同一线程），而非简单追求负载均衡。

4. **编译时间与仿真速度的权衡**：Metro-MPI 的 32x32 设计编译时间高达 4,167 分钟（约 69 小时），而 1x1 仅 5 分钟。多线程仿真器若采用编译时分区策略，需考虑编译时间是否可接受；或者采用运行时动态分区，但这会增加运行时开销。

5. **商业仿真器的扩展性**：Metro-MPI 在"三大"商业仿真器上的验证（单节点 16 核）证明分布式 RTL 仿真不是开源工具的专属领域。对于多线程仿真器，可以借鉴 Metro-MPI 的接口包装方法，将标准总线（AXI、CHI）的跨线程通信抽象为"延迟不敏感通道"。

## 原文摘录

> "We introduce Metro-MPI to enable fast behavioural RTL simulation of emerging-scale chips. In Metro-MPI, each chip is simulated with many independent processes, communicating via the standard Message Passing Interface (MPI). This enables us to scale simulation time and throughput by exploiting more processes and compute nodes as our chips grow."
> — Metro-MPI (DATE 2023)

> "Metro-MPI requires minimal design changes to enable parallel RTL simulation across multiple nodes in an HPC or cloud infrastructure. Metro-MPI can be used through the whole design process, starting with early-stage designs."
> — Metro-MPI

> "Speedup compared to sequential and multithreaded RTL simulations of up to 135.98× and 9.29×, respectively. Exceptional scaling of RTL simulation to tens of nodes, reaching 2.7 MIPS for a 10B+ transistor, 1,024-core chip."
> — Metro-MPI 实验结果

> "Parendi scales up to 5888 cores on 4 Graphcore IPU sockets. It allows us to run large RTL designs up to 4× faster than the most powerful state-of-the-art x64 multicore systems."
> — Parendi (ASPLOS 2025)

> "The cost of synchronization on x64 is high, even with many fibers per thread... The IPU has a native hardware barrier that consumes only a few hundred IPU cycles. By contrast, x64 barrier synchronization requires expensive atomic memory accesses that could require a few thousand cycles with 56 threads."
> — Parendi 同步开销分析

> "Communication within a single IPU appears to depend primarily on b, but communication between IPUs depends on m×b."
> — Parendi 通信模型分析

## 相关链接

- [Metro-MPI 论文 (UPC)](https://upcommons.upc.edu/handle/2117/390396)
- [Metro-MPI Open Source](https://github.com/metro-mpi)
- [Parendi 论文 (arXiv)](https://arxiv.org/abs/2403.04714)
- [Parendi GitHub](https://github.com/parendi)
- [Metro-MPI++ 项目页](https://kislay536.github.io/projects/Metro-MPI++/)
- [FOSSi GSoC 2024 — Essent + Metro-MPI](https://fossi-foundation.org/gsoc/gsoc24-ideas)
- [Intel PIUMA 论文](https://arxiv.org/abs/2010.06277)
- [ARENA 论文](https://arxiv.org/abs/2011.04931)

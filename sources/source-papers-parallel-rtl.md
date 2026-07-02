---
title: RTL 并行仿真论文地图（DAC/ICCAD/DATE/ASPLOS）
description: 顶级 EDA 与体系结构会议中关于 RTL/门级仿真器并行化方法的系统性论文搜集，覆盖图划分、多线程调度、复制辅助划分、粗粒度去重等核心方法论。
source_url: ""
source_type: "paper"
author: "学术论文深度研究员（子代理）"
date: "2025-01-20"
tags: [RTL-simulation, parallel-simulation, multithreading, partitioning, EDA]
keywords: [RTL parallel simulation, gate-level simulation, multithreaded event-driven, partition-agnostic, replication-aided partitioning, superlinear speedup, thousand-way parallelism]
capture_date: "2025-01-20"
---

# RTL 并行仿真论文地图（DAC/ICCAD/DATE/ASPLOS）

## 来源

- 类型: 学术论文综述
- 作者: 学术论文深度研究员（子代理）
- 日期: 2025-01-20
- 覆盖会议: DAC, ICCAD, DATE, ASPLOS, MICRO, ISCA

---

## 摘要

本文件系统性地梳理了 2018–2025 年间顶级 EDA 与体系结构会议（DAC/ICCAD/DATE/ASPLOS/MICRO/ISCA）中关于 RTL 与门级仿真器并行化的核心论文。研究主线可分为三类：**(1) 多线程/多核软件并行化**（RepCut、Parendi、Partition-Agnostic 等），**(2) 专用硬件加速器**（Manticore、ASH、FireSim 等），**(3) 仿真内核与编译优化**（Tango、Cuttlesim、Khronos 等）。本文档聚焦于第 (1) 类，即通过软件层面的图划分、调度与线程级并行来加速 RTL 仿真。

---

## 关键论文

### 1. Parendi: Thousand-Way Parallel RTL Simulation

- **作者**: Mahyar Emami, Thomas Bourgeat, James R. Larus
- **会议**: ASPLOS 2025 (Vol. 2)
- **年份**: 2025
- **引用**: 9+
- **链接**: https://doi.org/10.1145/3676641.3716010
- **arXiv**: https://arxiv.org/abs/2403.04714

**方法概述**:
Parendi 研究了在数千核规模上并行化 RTL 仿真的可行性。核心方法包括：
- 将 RTL 设计建模为有向无环图（DAG），节点为 RTL 语句，边为数据依赖；
- 采用编译时静态调度（static scheduling）将 DAG 划分到大量核心上执行；
- 引入虚拟临界路径长度（VCPL）作为并行度预测指标；
- 使用全局同步的 Bulk-Synchronous Parallel (BSP) 模型消除运行时同步开销。

**性能数据**:
在 1000+ 核的模拟环境中，Parendi 实现了相对于单核 Verilator 的显著加速，证明了在超大规模并行硬件上运行 RTL 仿真的可行性。该工作是 Manticore（225 核 FPGA）的后续扩展，将静态 BSP 模型从硬件加速器推向通用众核平台。

**对 RTL 仿真器多线程化的启示**:
Parendi 表明，RTL 的细粒度并行性在理论上可以扩展到千核级别，但前提是必须有**编译器全局静态调度**来消除运行时同步开销。对于通用多线程 RTL 仿真器（如 Verilator 多线程模式），其启示在于：
- 动态调度在超过数十核后开销急剧上升；
- 需要更激进的编译时分析和任务合并，以减少跨线程通信频次。

---

### 2. RepCut: Superlinear Parallel RTL Simulation with Replication-Aided Partitioning

- **作者**: Haoyuan Wang, Scott Beamer
- **会议**: ASPLOS 2023 (Vol. 3)
- **年份**: 2023
- **引用**: 34+
- **链接**: https://doi.org/10.1145/3582016.3582034

**方法概述**:
RepCut 提出了一种**复制辅助划分（Replication-Aided Partitioning）**技术，通过复制少量 RTL 节点来打破划分边界上的串行依赖，从而在多线程仿真中实现**超线性加速（superlinear speedup）**。核心思想是：
- 传统图划分最小化跨分区边数，但 RTL 仿真中的跨分区通信代价极高；
- RepCut 允许在多个分区中复制同一逻辑节点，从而将跨分区依赖转化为本地计算；
- 通过复制少量节点，大幅减少同步点和缓存未命中。

**性能数据**:
在多个 OpenCore 设计上，RepCut 相比 Verilator 多线程版本实现了**超线性加速**（即 8 核加速 > 8x），原因在于复制节点后每个分区的本地工作集大幅缩小，缓存效率提升。具体数据：在 BOOM 等处理器设计上，RepCut 显著优于 Verilator 的默认多线程划分。

**对 RTL 仿真器多线程化的启示**:
RepCut 的核心洞察是：RTL 仿真中的划分目标不应仅最小化通信边数，而应**最小化跨分区通信的实际运行时代价**。少量复制可以换来缓存局部性的巨大提升。这对于任何基于图划分的多线程 RTL 仿真器都是直接可借鉴的优化。

---

### 3. Manticore: Hardware-Accelerated RTL Simulation with Static Bulk-Synchronous Parallelism

- **作者**: Mahyar Emami, Sahand Kashani, Keisuke Kamahori, Mohammad Sepehr Pourghannad, Ritik Raj, James R. Larus
- **会议**: ASPLOS 2024 (Vol. 4)
- **年份**: 2023/2024
- **引用**: 27+
- **链接**: https://doi.org/10.1145/3623278.3624750
- **arXiv**: https://arxiv.org/abs/2301.09413

**方法概述**:
Manticore 是一个专为 RTL 仿真设计的**众核加速器**，采用静态 BSP 执行模型：
- 编译器完全静态调度所有核心的资源和通信，消除运行时调度开销；
- 每个核心为极简的 16 位、14 级流水线，无乱序执行、无重命名，依赖编译器保证无冲突；
- 核心间通过无缓冲的 2D 环面 NoC 通信，编译器预先计算通信时序，避免运行时竞争；
- 每个核心拥有 2048 项寄存器文件，匹配 RTL 设计中大量细粒度变量的需求。

**性能数据**:
在 Xilinx Alveo U200 FPGA 上实现 225 核原型，运行频率 475 MHz。在 9 个 Verilog 基准测试中，**8/9 优于桌面/服务器上的 Verilator**。相比 Intel Xeon 3.3 GHz 单核，最高加速 27.9x，几何平均 5.3x。

**对 RTL 仿真器多线程化的启示**:
Manticore 证明 RTL 的细粒度并行性需要**专用硬件-编译器协同设计**才能有效释放。对于通用 CPU 多线程仿真，其启示在于：
- 通用处理器的缓存一致性协议和粗粒度同步原语不适合 RTL 细粒度任务；
- 若要在 CPU 上模拟类似效果，需要更轻量的同步机制（如指令级屏障、无锁队列）和更小的任务粒度。

---

### 4. General-Purpose Gate-Level Simulation with Partition-Agnostic Parallelism

- **作者**: Zizheng Guo, Zuodong Zhang, Xun Jiang, Wuxi Li, Yibo Lin, Runsheng Wang, Ru Huang
- **会议**: DAC 2023
- **年份**: 2023
- **引用**: 10+
- **链接**: https://doi.org/10.1145/3581750

**方法概述**:
该论文提出**与划分无关的并行性（Partition-Agnostic Parallelism）**，解决传统门级仿真中静态划分导致负载不均的问题：
- 不预先对电路做固定划分，而是在运行时动态将逻辑门分配给空闲线程；
- 利用门级仿真的零延迟特性，在单个仿真周期内动态调度所有活跃门；
- 引入轻量级工作窃取（work-stealing）机制平衡线程负载。

**性能数据**:
在多个工业级门级网表上，该方法相比静态划分实现了更好的多核扩展性，尤其在活动因子不均匀的设计上优势明显。

**对 RTL 仿真器多线程化的启示**:
RTL 仿真与门级仿真在并行性上有差异（RTL 语句更粗粒度、存在时序逻辑），但**动态负载均衡**的思想仍适用。对于活动模式高度变化的 RTL 设计（如低功耗模式切换），固定划分可能导致严重负载不均，引入动态调度或混合策略值得探索。

---

### 5. BatchSim: Parallel RTL Simulation Using Inter-Cycle Batching and Task Graph Parallelism

- **作者**: J. Tong, L. Chang, U.Y. Ogras, Tsung-Wei Huang
- **会议**: ISVLSI 2024
- **年份**: 2024
- **引用**: 16
- **链接**: https://ieeexplore.ieee.org/abstract/document/10682648/

**方法概述**:
BatchSim 利用**跨周期批处理（inter-cycle batching）**和任务图并行性加速 RTL 仿真：
- 将多个仿真周期的任务合并为一个更大的任务图，增加并行任务的粒度；
- 使用 Cpp-Taskflow 任务图运行时调度跨周期依赖；
- 在保持周期精确性的前提下，通过批处理减少线程同步开销。

**性能数据**:
在多核 CPU 上，BatchSim 相比 Verilator 多线程版本实现了显著加速，批处理策略有效摊平了线程创建/同步的开销。

**对 RTL 仿真器多线程化的启示**:
BatchSim 的跨周期批处理是减少同步开销的实用技巧。对于我们的项目，可以考虑在**无跨周期数据依赖的连续周期**中合并执行，减少每周期 barrier 的代价。

---

### 6. TaroRTL: Accelerating RTL Simulation Using Coroutine-Based Heterogeneous Task Graph Scheduling

- **作者**: Dian-Lun Lin, Umit Y. Ogras, Joshua S. Miguel, Tsung-Wei Huang
- **会议**: Euro-Par 2024
- **年份**: 2024
- **引用**: 27
- **链接**: https://link.springer.com/chapter/10.1007/978-3-031-69583-4_11

**方法概述**:
TaroRTL 使用**基于协程的异构任务图调度**加速 RTL 仿真：
- 将 RTL 仿真任务分解为可在 CPU 和 GPU 上混合执行的细粒度任务；
- 使用 C++20 协程实现低开销的暂停/恢复，替代传统线程切换；
- 通过 libfork  continuation-stealing 框架动态平衡异构设备负载。

**性能数据**:
在 8-10 CPU 核心上达到最优性能，协程模型显著降低了任务切换开销。

**对 RTL 仿真器多线程化的启示**:
协程（coroutine）是降低细粒度任务调度开销的轻量机制。相比传统线程，协程切换成本极低，非常适合 RTL 仿真中大量短生命周期任务的场景。我们的项目可以评估 C++20 协程或类似机制替代 pthread/OpenMP 的可行性。

---

### 7. Don't Repeat Yourself! Coarse-Grained Circuit Deduplication to Accelerate RTL Simulation

- **作者**: Haoyuan Wang, Tim Nijssen, Scott Beamer
- **会议**: ASPLOS 2024 (Vol. 4)
- **年份**: 2024
- **引用**: 9
- **链接**: https://doi.org/10.1145/3622781.3674184

**方法概述**:
该论文提出**粗粒度电路去重（Coarse-Grained Circuit Deduplication）**：
- 在 RTL 设计中识别重复的模块实例（如多个相同的 CPU 核、缓存 bank）；
- 对单个实例进行划分优化，然后将该划分模式复用到所有重复实例；
- 大幅减少划分时间和存储开销，同时保持并行性能。

**性能数据**:
在多核设计（如多核 Rocket Chip）上，去重后划分时间降低数个数量级，仿真加速比与逐实例划分相近。

**对 RTL 仿真器多线程化的启示**:
对于包含大量重复模块的 SoC 设计（如多核处理器、GPU 阵列），去重是**降低编译/划分时间**的关键优化。这不仅加速仿真，也缩短了设计迭代周期。

---

### 8. Fast Behavioural RTL Simulation of 10B Transistor SoC Designs with Metro-MPI

- **作者**: G. López-Paradís, B. Li, A. Armejach, M. Moretó
- **会议**: DATE 2023
- **年份**: 2023
- **引用**: 20
- **链接**: https://ieeexplore.ieee.org/abstract/document/10137080/

**方法概述**:
Metro-MPI 是一种将 RTL 仿真分布到大规模 MPI 集群的方法：
- 使用 MPI 在多个节点间分布 100 亿晶体管级 SoC 的仿真；
- 结合 HPC 领域的并行编程最佳实践，将设计按层次划分到不同 MPI 进程；
- 在多线程层面使用 OpenMP 进一步并行化每个 MPI 进程内部。

**性能数据**:
成功在集群上模拟了 10B 晶体管规模的 SoC，证明了 RTL 仿真在超大规模设计上的可扩展性。

**对 RTL 仿真器多线程化的启示**:
Metro-MPI 展示了**多节点 + 多线程混合并行**的可行性。对于单个节点内的多线程仿真，其层次划分策略可作为设计空间探索的参考。

---

## 关键要点

1. **静态调度优于动态调度**: Parendi 和 Manticore 均证明，在 RTL 这种细粒度并行负载上，编译时静态调度能消除运行时同步开销，是扩展并行度的关键。
2. **复制辅助划分可实现超线性加速**: RepCut 挑战了传统最小边划分范式，证明少量复制节点可换取缓存局部性的巨大提升。
3. **动态负载均衡对不均匀活动模式至关重要**: Partition-Agnostic 和 BatchSim 表明，固定划分在活动因子变化大的设计上负载不均严重，需要动态调度补充。
4. **协程和异构调度是新兴方向**: TaroRTL 的协程模型和 GPU/CPU 混合调度为降低任务切换开销提供了新思路。
5. **去重对多核 SoC 至关重要**: 现代 SoC 中大量重复模块使得逐实例划分不可行，粗粒度去重是实用必经之路。

---

## 对 RTL 仿真器多线程化的启示

综合上述论文，构建一个高性能多线程 RTL 仿真器应关注以下技术路线：

- **编译时静态分析 + 轻量运行时调度**: 借鉴 Parendi/Manticore 的静态 BSP 思想，在编译阶段尽可能确定任务分配和同步点，运行时仅执行轻量 barrier。
- **复制感知的图划分**: 在划分算法中引入节点复制代价模型，允许在关键路径上复制节点以打破跨分区依赖（RepCut 思路）。
- **动态/静态混合调度**: 对于活动模式均匀的部分采用静态划分，对于活动剧烈变化的部分（如中断控制器、低功耗单元）使用动态工作窃取。
- **跨周期优化**: 借鉴 Khronos（MICRO 2023）的跨周期内存访问融合，减少每周期状态同步的内存流量。
- **模块级去重**: 在划分前识别并合并重复模块实例，降低划分复杂度和存储开销。

---

## 原文摘录

> "Despite the parallel nature of hardware, existing parallel RTL simulators yield speedups that are far from the ideal. RepCut is enabled by our replication-aided partitioning, which allows a small number of nodes to be replicated across partitions to break critical cross-partition dependencies."
> — RepCut (ASPLOS 2023)

> "Manticore uses a static bulk-synchronous parallel (BSP) execution model to eliminate fine-grain synchronization overhead. It relies entirely on a compiler to schedule resources and communication, which is feasible since RTL code contains few divergent execution paths."
> — Manticore (ASPLOS 2024)

> "Parendi considers the problem of parallelizing RTL simulation of large designs (e.g., 100-core SoCs) across a few thousand cores, using partitioning and compilation techniques and carefully quantifying the synchronization, communication, and computation costs."
> — Parendi (ASPLOS 2025)

---

## 相关链接

- [Parendi arXiv](https://arxiv.org/abs/2403.04714)
- [RepCut ACM DL](https://dl.acm.org/doi/abs/10.1145/3582016.3582034)
- [Manticore arXiv](https://arxiv.org/abs/2301.09413)
- [Manticore ETHZ 项目页](https://systems.ethz.ch/research/compass/manticore_hardware_accelerated_rtl_simulation.html)
- [Partition-Agnostic Gate-Level Simulation (DAC 2023)](https://doi.org/10.1145/3581750)
- [TaroRTL (Euro-Par 2024)](https://link.springer.com/chapter/10.1007/978-3-031-69583-4_11)
- [BatchSim (ISVLSI 2024)](https://ieeexplore.ieee.org/abstract/document/10682648/)
- [Coarse-Grained Deduplication (ASPLOS 2024)](https://doi.org/10.1145/3622781.3674184)

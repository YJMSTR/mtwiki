---
title: "最新 RTL 并行仿真论文汇总（2023-2026）"
description: "搜集 2023-2026 年间与多线程/并行 RTL 仿真器相关的顶级会议论文与预印本，涵盖 CPU、GPU、加速器及新型数学抽象等方向。"
source_url: "https://arxiv.org/abs/2508.02236"
source_type: "paper"
author: "Lu Chen et al."
date: "2025-08-04"
tags: [RTL-simulation, parallel-simulation, supernode, activity-factor, XiangShan, DAC]
keywords: [GSIM, Verilator, ESSENT, Arcilator, supernode partitioning, bit-level splitting]
capture_date: "2026-07-01"
---

# 最新 RTL 并行仿真论文汇总（2023–2026）

## 来源

- URL: 多篇论文链接见下方各条目
- 类型: paper
- 作者: 多个研究团队
- 日期: 2023–2026

---

## 摘要

本文档汇总了 2023 至 2026 年间在 RTL 仿真加速领域发表的关键论文，覆盖从 CPU 多线程优化、GPU 批量并行、专用加速器到张量代数抽象等多个前沿方向。核心主题包括：
- **活动因子感知**（activity-aware）vs. **全周期**（full-cycle）仿真策略；
- **超节点划分**、**冗余计算**、**差分同步**等多线程通信优化；
- **GPU SIMT 适配**与虚拟 VLIW 架构；
- **张量代数**对 RTL 数据流图的统一建模。

---

## 关键要点

### 1. GSIM —— 超节点/节点/比特三级优化（DAC 2025）

- **论文**: *GSIM: Accelerating RTL Simulation for Large-Scale Designs* (Lu Chen et al., DAC 2025)
- **链接**: [arXiv:2508.02236](https://arxiv.org/abs/2508.02236) | [PDF](https://talks-pubs.xiangshan.cc/publications/dac2025-GSIM.pdf) | [GitHub: OpenXiangShan/gsim](https://github.com/OpenXiangShan/gsim)
- **核心思想**: 将 RTL 仿真计算开销归纳为四个因素（活跃位访问、节点求值、总节点数、活动因子），并在**超节点级**、**节点级**、**比特级**分别提出优化技术：
  - **超节点级**: 增强型 Kernighan 划分算法，保护强关联节点不被拆分，平衡激活开销与活动因子；
  - **节点级**: 冗余节点消除、基于成本模型的内联决策、reset 信号检查前移；
  - **比特级**: 数据流分析后按比特访问模式拆分节点，进一步降低活动因子。
- **性能**: 在 XiangShan 上启动 Linux 比 Verilator 单线程快 **7.34×**，在 Rocket 上运行 CoreMark 快 **19.94×**；SPEC CPU2006 平均比单线程 Verilator 快 **3.72×**，与 8 线程 Verilator 相比仍快 **1.18×**。
- **关键结论**: GSIM 是目前唯一能正确仿真 XiangShan 的开源仿真器（ESSENT 和 Arcilator 在部分设计上会失败或 out-of-memory）。

### 2. RTeAAL Sim —— 张量代数重构 RTL 仿真（2026）

- **论文**: *RTeAAL Sim: Using Tensor Algebra to Represent and Accelerate RTL Simulation* (Extended Version, arXiv:2601.18140)
- **链接**: [arXiv:2601.18140](https://arxiv.org/html/2601.18140v1) | [GitHub: TAC-UCB/RTeAAL-Sim](https://github.com/TAC-UCB/RTeAAL-Sim)
- **核心思想**: 将 RTL 数据流图表示为**稀疏张量**，仿真执行描述为**扩展 Einsum 的级联**（cascade of extended Einsums）。借助 TeAAL 框架对稀疏张量代数核进行调度与优化，实现算法（cascade）、数据流（mapping）、格式（format）、硬件绑定（binding）的分离。
- **创新点**: 将 17 种来自 11 篇前作的 RTL 仿真优化技术统一映射到 TeAAL 的四层抽象中，证明了张量代数表述的**通用性**与**可扩展性**。
- **性能**: 概念验证原型在四种主机上与 Verilator 性能相当，但理论优化空间远大于现有实现。

### 3. GEM —— NVIDIA 的 GPU 加速 RTL 仿真（DAC 2025）

- **论文**: *GEM: GPU-Accelerated Emulator-Inspired RTL Simulation* (Zizheng Guo, Mark Haoxing Ren, NVIDIA Research, DAC 2025)
- **链接**: [NVIDIA Research](https://research.nvidia.com/publication/2025-06_gem-gpu-accelerated-emulator-inspired-rtl-simulation) | [PDF](https://yibolin.com/publications/papers/SIM_DAC2025_Guo.pdf) | [GitHub: NVlabs/GEM](https://github.com/NVlabs/GEM)
- **核心思想**: 受 FPGA 仿真器启发，提出**虚拟 VLIW 架构**并在 GPU 上通过 CUDA 解释执行。RTL 设计先综合为门级网表，再映射为 GEM 的布尔处理器指令流（bitstream），类比 FPGA CAD 流程。
- **关键设计**:
  - 三档指令长度（8192/16384/32768 bit），256 线程 lockstep 加载，完全合并内存访问；
  - Boomerang 折叠机制将逻辑级数压缩 6–8 倍；
  - 162.4 MB bitstream 即可承载 500 万门的 OpenPiton8 设计。
- **性能**: 平均比领先商业工具快 **9.15×**，比 8 线程 Verilator 快 **5.98×**，比单线程 Verilator 快 **24.87×**；NVDLA 上峰值加速达 **64.76×**（相对单线程 Verilator）。获 DAC 2025 **Best Paper Nomination**。

### 4. OmniSim —— HLS 数据流的多线程仿真（MICRO 2025）

- **论文**: *OmniSim: Simulating Hardware with C Speed and RTL Accuracy for High-Level Synthesis Designs* (Rishov Sarkar, Cong Hao, Georgia Tech, MICRO 2025)
- **链接**: [arXiv:2508.19299](https://arxiv.org/abs/2508.19299) | [ACM](https://dl.acm.org/doi/10.1145/3725843.3756033)
- **核心思想**: 针对 HLS 工具中复杂数据流（cyclic dependency、non-blocking FIFO）无法在 C 仿真层准确建模的问题，通过**软件多线程**精确模拟 FIFO 访问的硬件时序，并灵活耦合功能仿真与性能仿真线程。
- **关键设计**:
  - LLVM IR 层级重写 dataflow 函数，提取子任务并生成独立线程；
  - 运行时库维护 FIFO 表，记录每个 FIFO 访问的精确硬件时序；
  - 增量重仿真（incremental re-simulation）可在 78 µs 内完成，相对完整仿真加速 **26,966×**。
- **性能**: 在 11 个此前无任何 HLS 工具支持的设计上，比传统 C/RTL 协同仿真快 **35.9×**，比 LightningSim 快 **6.61×**。

### 5. Parendi —— 千路并行 RTL 仿真（ASPLOS 2025）

- **论文**: *Parendi: Thousand-Way Parallel RTL Simulation* (Mahyar Emami, Thomas Bourgeat, James R. Larus, EPFL, ASPLOS 2025)
- **链接**: [arXiv:2403.04714](https://arxiv.org/abs/2403.04714) | [PDF](https://infoscience.epfl.ch/bitstreams/690daaf4-d0c8-479b-b46f-cd47461bd50a/download)
- **核心思想**: 基于 Graphcore IPU（ Intelligence Processing Unit）的**消息传递架构**，将 RTL 设计的细粒度并行性映射到多达 **5888 核**的 IPU tile 上。采用 Bulk-Synchronous Parallel (BSP) 执行模型，通过子模负载平衡算法划分 RTL 数据流图的 fiber。
- **关键发现**:
  - x64 多核上的同步成本过高，导致小设计几乎无法从多线程获益；
  - IPU 的低成本同步与低延迟通信使千路并行成为可能，但单 tile 性能约为 x64 的 1/37–1/84；
  - 需要足够大的设计才能摊平跨 tile 通信开销。
- **性能**: 在 4 个 IPU socket（5888 核）上，大型设计比最强 x64 多核系统快 **4×**。

### 6. CCSS —— 多核 RTL 仿真加速器（2025）

- **论文**: *CCSS: Hardware-Accelerated RTL Simulation with Fast Combinational Logic Computing and Sequential Logic Synchronization* (arXiv:2507.08406)
- **链接**: [arXiv:2507.08406](https://arxiv.org/html/2507.08406v1)
- **核心思想**: 设计可扩展的多核 RTL 仿真平台，将组合逻辑计算与顺序逻辑同步解耦。细粒度节点映射到计算单元，暴露更多并行性，而 Manticore 的粗粒度图限制并行度。
- **性能**: 比 Verilator 单线程快 **45×**，比 Manticore 快 **12.9×**；编译时间显著优于 Manticore（VTA 从 15 分 29 秒降至 7 分 23 秒）。

### 7. Multisim —— 多实例分布式 RTL 仿真（Verification Futures 2025）

- **演讲/论文**: *Multisim: simulate RTL with real multi-threaded speed* (Antoine Madec, Tessolve, Verification Futures UK 2025)
- **链接**: [PDF](https://www.tessolve.com/wp-content/uploads/2025/06/Antoine-Madec-Multisim_Tessolve_uk_2025_0410.pdf) | [GitHub: antoinemadec/multisim](https://github.com/antoinemadec/multisim)
- **核心思想**: 以**牺牲周期精确性**换取可扩展性，通过 TCP/IP 通道将一个大 DUT 拆分为 1 个 Server 仿真（骨架 + NoC）和 64 个 Client 仿真（每个含 1 个大实例），各实例可运行不同仿真器（Verilator、VCS、Questa、Xcelium 等）。
- **关键特征**: 基于 Ready/Valid 的 channel 通信，client 与 server 可混用不同编译流程；支持 GLS 与 RTL 混合仿真。
- **局限**: 非周期精确，波形分散在 N+1 个仿真中，调试难度增加。

### 8. TaroRTL —— 基于协程的 RTL 仿真加速（Euro-Par 2024）

- **论文**: *TaroRTL: Accelerating RTL Simulation using Coroutine-based Task Graph Scheduling* (D.-L. Lin et al., Euro-Par 2024)
- **链接**: [PDF](https://jsm.ece.wisc.edu/docs/lin-europar2024.pdf)
- **核心思想**: 将 RTLflow 的异构 CPU/GPU 任务图用 C++20 coroutine 重新调度，在 CPU 线程等待 GPU 任务时无缝切换执行其他任务，消除空闲等待。
- **性能**: 在 riscv-mini 和 NVDLA 上，相比 RTLflow 的 CPU 等待模式，使用更少线程实现 **55–81%** 的加速；NVDLA 10 线程场景从 379 秒降至 236 秒。

---

## 对 RTL 仿真器多线程化的启示

1. **超节点划分是单线程优化的主杠杆**：GSIM 的实验表明，引入 supernode 对所有设计都有显著性能提升，且最优大小在 20–50 之间，可直接指导我们的划分策略。
2. **活动因子 vs. 并行度的权衡**：Parendi 和 GSIM 都强调，电路的自然 floorplan 和关键路径长度决定了仿真并行度。在划分时应兼顾物理布局的局部性，而非纯粹逻辑最小割。
3. **GPU 方向需要牺牲通用性**：GEM 和 RTLflow 证明 GPU 适合批量刺激（batch stimulus）或门级表查找，但 RTL 级的 SIMT 不兼容性是根本障碍。虚拟 VLIW 是绕过此障碍的有效方案。
4. **张量代数可能是下一代统一框架**：RTeAAL Sim 将 RTL 仿真映射到成熟稀疏张量代数优化生态，意味着未来可以自动复用 loop unrolling、format compression、operator fusion 等编译技术。
5. **多线程同步成本仍是 CPU 瓶颈**：Verilator 多线程在 8 线程后反而退化，RepCut 通过冗余计算降低同步，CCSS 通过细粒度调度避免粗粒度同步。我们的设计应优先降低线程间通信频率。

---

## 原文摘录

> "GSIM significantly outperforms multi-threading Verilator on most of the designs."
> —— *GSIM*, DAC 2025

> "A larger size of supernode reduces A, but increases af. The optimal size depends on the circuit design. For the designs we select, the optimal size ranges from 20 to 50."
> —— *GSIM*, Section V-E

> "We present a GPU-accelerated RTL simulator addressing critical challenges in high-speed circuit verification... achieves up to 64× speed-up over the best CPU simulators."
> —— *GEM*, NVIDIA Research, DAC 2025

> "Parendi scales up to 5888 cores on 4 Graphcore IPU sockets. It allows us to run large RTL designs up to 4× faster than the most powerful state-of-the-art x64 multicore systems."
> —— *Parendi*, ASPLOS 2025

> "We reformulate RTL simulation as a sparse tensor algebra problem... our proof-of-concept simulator achieves performance that is competitive with Verilator."
> —— *RTeAAL Sim*, arXiv 2026

---

## 相关链接

- [GSIM 论文 (arXiv)](https://arxiv.org/abs/2508.02236)
- [GSIM GitHub](https://github.com/OpenXiangShan/gsim)
- [GEM 论文 (NVIDIA Research)](https://research.nvidia.com/publication/2025-06_gem-gpu-accelerated-emulator-inspired-rtl-simulation)
- [GEM GitHub](https://github.com/NVlabs/GEM)
- [RTeAAL Sim 论文](https://arxiv.org/html/2601.18140v1)
- [RTeAAL Sim GitHub](https://github.com/TAC-UCB/RTeAAL-Sim)
- [OmniSim 论文](https://arxiv.org/abs/2508.19299)
- [Parendi 论文](https://arxiv.org/abs/2403.04714)
- [CCSS 论文](https://arxiv.org/html/2507.08406v1)
- [Multisim GitHub](https://github.com/antoinemadec/multisim)
- [TaroRTL 论文](https://jsm.ece.wisc.edu/docs/lin-europar2024.pdf)

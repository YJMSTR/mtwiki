---
title: "Parendi: Thousand-Way Parallel RTL Simulation (ASPOS'25)"
source_url: "https://arxiv.org/abs/2403.04714"
source_type: "paper"
author: "Mahyar Emami, Thomas Bourgeat, James R. Larus (EPFL)"
date: "2024-03-07 (arXiv v1); 2025-03-16 (v2)"
tags: ["rtl-sim", "multithreading", "parallelism", "IPU", "thousand-core", "Graphcore", "partitioning"]
keywords: ["Parendi", "RTL simulation", "Graphcore IPU", "massive parallelism", "fine-grained parallelism", "synchronization cost", "partitioning", "compilation"]
capture_date: "2026-07-01"
---

## 摘要

Parendi 是 EPFL 发表在 ASPLOS'25 上的 RTL 仿真器，利用 Graphcore IPU（Intelligence Processing Unit）的**大规模并行架构**实现了高达 **5888 核**的 RTL 仿真，比当时最先进的 x64 多核系统（以 Verilator 为代表）**快 2.8–4 倍**。

核心创新点：
1. **RTL 仿真中存在大量细粒度并行性**：Parendi 系统性地量化分析了并行 RTL 仿真中的同步、通信和计算代价，并针对性地开发了新的**分区（partitioning）和编译技术**。
2. **专为 IPU 架构优化的编译器**：IPU 是专为图神经网络（GNN）设计的众核处理器，每个核心有独立的本地 SRAM，核心间通过高带宽互连通信。Parendi 将 RTL 仿真映射到该架构时，需要解决变量排序、通信调度和核心负载均衡等特有挑战。
3. **性能对比**：在 4 个 Graphcore IPU 芯片（共 5888 核心）上，Parendi 比单芯片 IPU 仿真快 4 倍，比 x64 系统上的 Verilator 多线程快 2.8–4 倍。

## 对"稀疏计算RTL仿真器多线程化"的启示

1. **细粒度并行性的利用上限**：Parendi 证明 RTL 仿真中存在大量可并行的细粒度操作，但这些并行性需要**特定的硬件架构**（IPU 的高核心数、高带宽互连、本地 SRAM）才能有效利用。在通用 x86 多核上，由于缓存一致性协议和操作系统调度的限制，这些并行性被"隐藏"了。对于我们的稀疏计算 RTL 仿真器，这意味着不能盲目增加线程数，而需要设计**与硬件拓扑匹配的轻量级同步机制**。

2. **分区（Partitioning）策略是关键**：Parendi 的核心突破在于分区技术——如何将 RTL 设计切分成可以独立在大量核心上运行的子任务。对于稀疏计算场景，分区的挑战更加复杂：活跃信号在时间和空间上的分布都不均匀，静态分区可能产生大量空转。我们需要考虑**动态分区**或**时间维度上的自适应分区**。

3. **通信 vs 计算的量化分析**：Parendi 论文强调了"仔细量化同步、通信和计算代价"的重要性。在稀疏计算中，由于大部分信号大部分时间不翻转，通信/计算的比值比密集计算更高。这提示我们需要：
   - 设计**压缩通信协议**（仅传递翻转信号）
   - 采用**延迟同步策略**（不必每周期同步）
   - 考虑**事件驱动（event-driven）而非周期驱动（cycle-driven）**的多线程模型

4. **专用架构 vs 通用架构的权衡**：Parendi 在 IPU 上取得突破，但 IPU 是专用硬件。对于通用 x86 平台，我们需要从 Parendi 的编译技术中借鉴分区思想，同时用更轻量的同步原语（如无锁队列、spinlock 替代 mutex）来降低通用平台的同步开销。

## 关键原文摘录

### 摘要核心内容

> Hardware development critically depends on cycle-accurate RTL simulation. However, as chip complexity increases, conventional single-threaded simulation becomes impractical due to stagnant single-core performance.

> Parendi is an RTL simulator that addresses this challenge by exploiting the abundant fine-grained parallelism inherent in RTL simulation and efficiently mapping it onto the massively parallel Graphcore IPU (Intelligence Processing Unit) architecture. Parendi scales up to 5888 cores on 4 Graphcore IPU sockets. It allows us to run large RTL designs up to 4x faster than the most powerful state-of-the-art x64 multicore systems.

> To achieve this performance, we developed new partitioning and compilation techniques and carefully quantified the synchronization, communication, and computation costs of parallel RTL simulation.

### 相关论文引用（来自 arXiv 参考文献）

> [34] Guillem López-Paradís, Brian Li, Adrià Armejach, Stefan Wallentowitz, Miquel Moretó, and Jonathan Balkind. Fast Behavioural RTL Simulation of 10B Transistor SoC Designs with Metro-Mpi. pages 1–6, 2023.

> [21] Mahyar Emami, Sahand Kashani, Keisuke Kamahori, Mohammad Sepehr Pourghannad, Ritik Raj, and James R. Larus. Manticore: Hardware-Accelerated RTL Simulation with Static Bulk-Synchronous Parallelism. In Proceedings of the 28th ACM International Conference on Architectural Support for Programming Languages and Operating Systems, Volume 4, ASPLOS '23, page 219–237, New York, NY, USA, 2024. Association for Computing Machinery.

## 附加信息

- **会议**: ASPLOS'25 (30th ACM International Conference on Architectural Support for Programming Languages and Operating Systems, Volume 2)
- **DOI**: https://doi.org/10.1145/3676641.3716010
- **arXiv 版本**: v1 (2024-03-07), v2 (2025-03-16)
- **页码**: 783–797 (ASPOS'25 Volume 2)
- **对比基准**: Verilator 多线程 (x64 服务器), 单芯片 IPU 仿真

## 参考链接

- https://arxiv.org/abs/2403.04714
- https://doi.org/10.1145/3676641.3716010

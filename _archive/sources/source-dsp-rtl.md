---
title: DSP RTL 仿真与并行加速：从 FFT/滤波器到大规模 SoC
description: 搜集 DSP 模块（FFT、Viterbi、FIR 等）在 RTL 仿真中的验证方法，以及多核/众核并行加速 RTL 仿真的前沿研究
source_url: "https://arxiv.org/abs/2507.08406"
source_type: "paper"
author: "Yijia Zhang et al."
date: "2025-07-11"
tags: ["RTL-simulation", "DSP", "FFT", "parallel-simulation", "hardware-accelerated-simulation"]
keywords: ["DSP RTL simulation", "fixed point arithmetic RTL", "FFT hardware simulation", "digital filter RTL verification", "multithreaded RTL"]
capture_date: "2026-07-02"
---

# DSP RTL 仿真与并行加速：从 FFT/滤波器到大规模 SoC

## 来源

- URL: https://arxiv.org/abs/2507.08406
- 类型: paper
- 作者: Yijia Zhang et al.
- 日期: 2025-07-11
- 补充来源:
  - Parendi (ASPLOS 2025): https://arxiv.org/abs/2403.04714
  - VLSI Implementation of OFDM Modem (Pandey et al.): https://www.design-reuse.com/article/58253-vlsi-implementation-of-ofdm-modem/

## 摘要

随着单芯片晶体管数量突破数百亿，RTL 级仿真与验证的复杂度呈指数级增长，仿真周期往往长达数月。在工业实践中，RTL 仿真被划分为功能调试（functional debug）和系统验证（system validation）两个阶段。系统验证要求高仿真速度，通常使用 FPGA 加速；而功能调试依赖快速编译，多核 CPU 成为主流选择。然而 CPU 的仿真速度已成为主要瓶颈。

CCSS 提出了一种可扩展的多核 RTL 仿真平台，通过专用架构与编译策略加速组合逻辑计算和时序逻辑同步。其采用基于 LUT 的多核架构，通过编译器、计算核心与 NoC 的协同设计，在组合逻辑计算和时序逻辑同步两方面同时实现加速。实验结果显示，相比最先进的多核仿真器，CCSS 最高可达 **12.9 倍加速**。

Parendi (ASPLOS 2025) 则将 RTL 仿真映射到 Graphcore IPU 的 5888 核上，利用 Bulk Synchronous Parallel (BSP) 模型，将大规模 SoC（含 DSP 模块）的仿真速度提升至高 **4 倍于** 最强 x64 多核系统。其基准测试中包含 VTA（深度学习加速器）、MC（蒙特卡洛 FPGA 引擎）等含大量乘加运算的设计，对 DSP 密集型 RTL 的并行拆分具有直接参考价值。

## 关键要点

- **RTL 仿真瓶颈**：大型 SoC（如 NVIDIA A100 含 540 亿晶体管）在 CPU 上单线程仿真可能需要数月；RTL 仿真占整个开发周期的 **24% 以上**。
- **DSP 模块的验证复杂度**：OFDM 基带中的 FFT、Viterbi、NCO 等模块需要大量复数乘法器和加法器。以 802.11a 为例，Viterbi 解码器需要约 **4000 MIPS**，FFT 需要约 **500 MIPS**，全 DSP 软件实现难以满足实时需求，因此必须走向 RTL/VLSI 实现。
- **并行 RTL 仿真的核心矛盾**：同步（synchronization）、通信（communication）与计算（computation）三者之和大致等于单周期仿真时间。Parendi 通过 BSP 模型将每时钟周期的同步降至 **两次全局 barrier**，在 IPU 上实现了极细粒度的并行。
- **硬件加速仿真 vs FPGA**：FPGA 原型验证速度最快，但编译（placement & routing）耗时巨大；且一旦设计超单芯片容量，跨板链路会严重降低仿真速度。CPU 仿真编译快但运行慢。CCSS 等专用加速器试图在两者之间取得平衡。
- **DSP 设计的 RTL 验证方法**：在通信基带开发中，通常先用 C/MATLAB 做浮点算法验证，再转为定点仿真，最后与 RTL 输出进行比特级对比。SPW 等工具支持将 RTL 模块插入系统级环境进行 co-simulation。

## 对 RTL 仿真器多线程化的启示

1. **DSP 数据通路天然适合并行拆分**：FFT 的蝶形运算、FIR 滤波器的抽头乘法、Viterbi 的 ACS 单元均具有规则的数据流和局部依赖性，可按照数据流图（data dependence graph）拆分为多个 fiber，映射到不同线程/核上。Parendi 的 fiber 分区策略对 DSP 流水线尤其适用。
2. **通信基带的 RTL 仿真是典型的高计算密度场景**：802.11a/5G NR 基带在 RTL 仿真中需要同时验证调制、FFT、信道补偿、解码等多个模块。这些模块在单个时钟周期内产生大量组合逻辑计算，适合通过多线程分摊。
3. **bit-true 验证要求全精度同步**：DSP 模块从算法到 RTL 的验证流程强调"比特一致"（bit-true）。在并行仿真器中，所有分区在 barrier 处必须精确同步寄存器值，否则定点噪声分析会失效。BSP 的每周期双 barrier 机制恰好满足这一需求。
4. **定点位宽决定仿真内存与通信量**：复数乘法器从 12bit 扩到 16bit，门数从 6K 增至 10K；FFT 从 12bit 到 16bit，门数从 24K 增至 36K。更宽位宽意味着更大的 RTL 状态空间和更高的核间通信带宽需求。在多线程仿真器设计中，必须考虑 DSP 位宽对通信-计算比的影响。

## 原文摘录

> "As transistor counts in a single chip exceed tens of billions, the complexity of RTL-level simulation and verification has grown exponentially, often extending simulation campaigns to several months. In industry practice, RTL simulation is divided into two phases: functional debug and system validation."
> — CCSS, 2025

> "Parendi is the first scalable, multi-thousand-way parallel RTL simulator... It runs up to 4× faster than multithreaded Verilator (the fastest RTL simulator)."
> — Parendi, ASPLOS 2025

> "The total MIPS requirement is 4500+. Such high CPU power is not available even with the fastest DSPs in the market today."
> — Pandey et al., VLSI Implementation of OFDM Modem

> "A small change in the number of bits in the representation could result in a significant change in the size of arithmetic circuits especially multipliers."
> — Pandey et al., VLSI Implementation of OFDM Modem

## 相关链接

- [Parendi: Thousand-Way Parallel RTL Simulation (ASPLOS 2025)](https://arxiv.org/abs/2403.04714)
- [CCSS: Hardware-Accelerated RTL Simulation](https://arxiv.org/abs/2507.08406)
- [VLSI Implementation of OFDM Modem (Pandey et al.)](https://www.design-reuse.com/article/58253-vlsi-implementation-of-ofdm-modem/)
- [Verilator: Open-source multi-threaded RTL simulator](https://verilator.org/)
- [Switchboard: Open-Source Framework for Modular Simulation](https://arxiv.org/abs/2407.20537)

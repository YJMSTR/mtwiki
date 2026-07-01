---
title: SIMD/Vectorization in RTL Simulation and Gate-Level Simulation
description: AVX2/AVX-512 在门级仿真、布尔逻辑仿真中的应用，以及 RTL 仿真器中的向量化机会
source_url: "https://arxiv.org/abs/2601.18140"
source_type: "paper"
author: "Yan Zhu, TAC-UCB"
date: "2026-01-26"
tags: [simd, avx, rtl-simulation, vectorization, tensor-algebra, gate-level]
keywords: [SIMD, AVX2, AVX-512, RTL simulation, Verilator, bit-vector, parallel bitwise, gate-level simulation]
capture_date: "2026-07-01"
---

# SIMD/Vectorization 在 RTL 仿真与门级仿真中的应用

## 来源

- URL: <https://arxiv.org/abs/2601.18140>
  - 类型: paper
  - 作者: Yan Zhu et al., TAC-UCB
  - 日期: 2026-01-26
- URL: <https://arxiv.org/html/2604.05983v2>
  - 类型: paper
  - 作者: Arch HDL Team
  - 日期: 2026-04-20
- URL: <https://github.com/verilator/verilator/blob/master/docs/guide/simulating.rst>
  - 类型: doc
  - 作者: Verilator Project
  - 日期: 持续更新
- URL: <https://andrewdeorio.com/assets/research/DAC09Event.pdf>
  - 类型: paper
  - 作者: D. Chatterjee et al., DAC 2009
  - 日期: 2009-07
- URL: <https://arxiv.org/html/2506.09198v1>
  - 类型: paper
  - 作者: Low-Level Quantum Simulation Team
  - 日期: 2018-01-31

## 摘要

本文综合搜集了 SIMD/Vectorization 在 RTL 仿真器和门级仿真中的相关研究资料。核心发现包括：

1. **RTeAAL Sim** 将 RTL 仿真重新表述为稀疏张量代数问题，通过紧凑的循环表示替代庞大的静态生成指令序列，从根本上降低了指令缓存压力，其原型已在多 CPU/ISA 上达到与 Verilator 相当的性能。

2. **Arch HDL** 的语言不变性使得编译到原生后端时，宽向量类型（如 `Vec<SInt<8>, N>` 或 `Vec<UInt<N>, M>`）可以自动获得 SIMD 向量化，这对脉动阵列和注意力单元等 AI 加速器设计特别有价值。

3. **DAC 2009 GPU 门级仿真器** 通过位向量（bit-vector）和按位 AND 操作来并行判断宏门（macro-gate）是否应该激活，展示了 SIMD 范式在事件驱动门级仿真中的早期应用。

4. **量子态矢量模拟器**（如 ProjectQ、Google qsim、PennyLane Lightning）广泛使用 AVX2/AVX-512/FMA 指令来同时处理多个态矢量振幅，实现 2–4 倍以上的加速。

5. 当前主流 RTL 仿真器（Verilator、ESSENT）将 RTL 数据流图编译为近乎直线的 C++ 代码，代码复用率极低，导致严重的 I-cache 压力。张量代数方法和显式 SIMD 向量化是两条互补的优化路径。

## 关键要点

- **张量代数替代直线代码**：RTeAAL Sim 的核心洞见是，将 RTL 数据流图表示为稀疏张量、仿真过程表示为扩展 Einsum 级联，可以解耦仿真行为与二进制大小。这意味着同样的电路不再生成数百 MB 的 C++ 代码，而是几十 KB 的紧凑张量代数核。

- **自动 SIMD 向量化的语言前提**：Arch HDL 的编译时 DAG 分析将每个模块的 settle depth 静态确定为 1 或 2，生成固定边界循环而非无界 delta cycle 迭代。这种结构使得宽向量类型（systolic array、attention unit 中常用的 `Vec<SInt<8>, N>`）可以自动获得 SIMD 向量化，无需手写 intrinsics。

- **位向量并行在门级仿真中的早期验证**：DAC 2009 的 GPU 事件驱动门级仿真器通过将监控网（monitored nets）组织为位向量，每个宏门有一个敏感度列表（sensitivity lid），只需一次按位 AND 即可判断该宏门是否需要在下一层被激活。这本质上是 SIMD 的位级并行。

- **量子模拟器的 SIMD 加速经验**：ProjectQ 显式支持 Intel AVX 向量指令；Google qsim 使用 AVX2 + FMA intrinsics，通过 fused gate kernel 利用数据级并行；PennyLane Lightning 使用 AVX-512 一次处理 8 或 16 个值。学术模拟器 HpQC 报告使用 AVX2/FMA 平均加速 2.20 倍。

- **AVX-512 的位操作优势**：在人口计数（population count）和位并行全加器（bit-parallel full adder）等操作中，AVX-512 的 512 位寄存器、mask 寄存器和三元位运算（ternary logic）可以将吞吐量提升到 AVX2 的 2.5 倍以上。这些操作在门级仿真的布尔逻辑求值中直接适用。

- **Verilator 的编译模型**：Verilator 将 SystemVerilog 翻译为优化的 C++ 模型，编译后执行。官方文档指出"instruction cache size often limits large models"，且性能"depends primarily on your C++ compiler and the size of your CPU's caches"。

## 对 RTL 仿真器多线程化的启示

1. **SIMD 与多线程是不同维度的并行**：多线程化解决的是跨 cycle/跨模块的粗粒度并行，而 SIMD 解决的是单 cycle 内对多位宽信号、多位片（bit-slice）或多位向量（bit-vector）的细粒度并行。对于脉动阵列、向量 ALU、GPU 等包含大量相同结构重复的设计，SIMD 可以显著降低每 cycle 的指令数。

2. **将 RTL 数据流图映射为张量代数核**：RTeAAL Sim 的思路表明，与其为每个门生成独立 C++ 语句，不如将同类型操作（如所有 AND 门、所有 XOR 门）聚合为张量运算，利用编译器的自动向量化（auto-vectorization）生成 SIMD 指令。这同时缓解了 I-cache 压力和提升了 IPC。

3. **宽信号类型（`logic [255:0]`）天然适合 SIMD**：RTL 中常见的宽总线、向量寄存器、矩阵转置等操作，如果仿真器能够识别其结构规律，就可以映射为 AVX2/AVX-512 的 256/512 位向量操作，而非逐位循环。

4. **位向量活动检测（Activity Detection）**：在多线程 RTL 仿真中，每个线程需要知道自己负责的门/模块是否有输入变化。借鉴 DAC 2009 GPU 仿真器的位向量敏感度列表，可以将所有线程的"是否有活动"信息压缩为 512 位向量，一次 AVX-512 比较即可确定哪些线程需要进入计算阶段。

5. **注意 AVX-512 的频率降频（throttling）**：AVX-512 指令在某些微架构上会导致 CPU 降频。对于 RTL 仿真这种前段受限（frontend-bound）而非后端计算受限的工作负载，需要权衡 SIMD 宽度带来的指令减少与频率下降带来的周期损失。

## 原文摘录

> RTL simulation on CPUs remains a persistent bottleneck in hardware design. State-of-the-art simulators embed the circuit directly into the simulation binary, resulting in long compilation times and execution that is fundamentally CPU frontend-bound, with severe instruction-cache pressure. This work proposes RTeAAL Sim, which reformulates RTL simulation as a sparse tensor algebra problem.
> — *RTeAAL Sim, Abstract*

> SIMD vectorization is automatic for designs with wide `Vec<SInt<8>, N>` or `Vec<UInt<N>, M>` types—precisely the types used in systolic arrays and attention units in AI accelerator designs.
> — *Arch HDL, Section 7.3.2*

> The array is organized as a bit vector, with each monitored net being implicitly mapped to a unique location in the array. If a macro-gate simulation modifies the value of any of these nets, its corresponding location is tagged. Each macro-gate has a corresponding sensitivity lid where all the input nets triggering its activation are tagged. With this structure, a simple bit-wise AND operation between the monitored nets array and a macro-gate's sensitivity list determines if any input change has occurred and the macro-gate should be activated.
> — *DAC 2009, Event-Driven Gate-Level Simulation with GP-GPUs*

> By operating on multiple amplitudes in one CPU instruction, SIMD vectorization can significantly speed up state updates. For example, the ProjectQ simulator explicitly supports Intel AVX vector instructions. More recently, Google's qsim is built with AVX2 and fused multiply-add (FMA) intrinsics, using fused gate kernels to exploit data-level parallelism. Xanadu's PennyLane Lightning simulator similarly employs explicit intrinsic AVX-512, effectively unrolling loops to operate on 8 or 16 values at a time.
> — *Low-Level and NUMA-Aware Optimization for High-Performance Quantum Simulation, Section I*

> Experience shows that the instruction cache size often limits large models, and reducing code size, if possible, can be beneficial. The supplied `$VERILATOR_ROOT/include/verilated.mk` file uses the `OPT`, `OPT_FAST`, `OPT_SLOW`, and `OPT_GLOBAL` variables to control optimization. You can set these when compiling the output of Verilator with Make, for example: `make OPT_FAST="-Os -march=native" -f Vour.mk Vour__ALL.a`
> — *Verilator Documentation, Benchmarking & Optimization*

> A single AVX-512 FMA can execute 16 SP or 8 DP multiplies+adds per cycle, yielding a theoretical double-precision throughput per core of 2 × 8 × f_clk FLOPS. AVX-512 exposes thirty-two 512-bit ZMM registers, 8 mask registers for lane predication, and richer instruction subsets: gather/scatter, compress/expand, conflict detection, ternary bitwise logic, and wide integer/FMA support.
> — *Intel AVX Overview, Emergent Mind*

## 相关链接

- [RTeAAL Sim 论文 (arXiv)](https://arxiv.org/abs/2601.18140)
- [RTeAAL Sim 开源代码](https://github.com/TAC-UCB/RTeAAL-Sim)
- [Arch HDL: AI-Native HDL](https://arxiv.org/abs/2604.05983)
- [Verilator 官方文档](https://github.com/verilator/verilator/blob/master/docs/guide/simulating.rst)
- [DAC 2009 GPU 门级仿真](https://andrewdeorio.com/assets/research/DAC09Event.pdf)
- [量子模拟器 NUMA 优化论文](https://arxiv.org/abs/2506.09198)
- [AVX-512 人口计数优化](https://arxiv.org/abs/2412.16370)
- [VecDualSPHysics: SPH 向量化](https://www.sciencedirect.com/science/article/pii/S0021999122002960)

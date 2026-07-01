---
title: "Manticore: Hardware-Accelerated RTL Simulation with Static Bulk-Synchronous Parallelism (ASPOS'24 / DATE'23)"
source_url: "https://arxiv.org/abs/2301.09413 / https://dl.acm.org/doi/10.1145/3623278.3624750"
source_type: "paper"
author: "Mahyar Emami, Sahand Kashani, Keisuke Kamahori, Mohammad Sepehr Pourghannad, Ritik Raj, James R. Larus (EPFL, University of Tokyo, Sharif University, IIT)"
date: "2023-01-23 (arXiv); 2023-03 (ASPOS'24)"
tags: ["rtl-sim", "multithreading", "hardware-acceleration", "FPGA", "BSP", "static-scheduling", "many-core"]
keywords: ["Manticore", "RTL simulation", "hardware accelerator", "bulk-synchronous parallelism", "static scheduling", "FPGA", "225-core", "Verilator comparison"]
capture_date: "2026-07-01"
---

## 摘要

Manticore 是一个专为 RTL 仿真设计的**硬件加速器**（FPGA 实现），采用**静态 Bulk-Synchronous Parallel (BSP) 执行模型**，在 Xilinx Alveo U200 FPGA 上实现了 **225 个核心 @ 475 MHz**。相比在 AMD EPYC 7V73X (120 核) 和 Intel Core i7 9700K (8 核) 上运行的 Verilator v5.006，Manticore 在 9 个基准测试中的 8 个上取得了性能优势。

核心设计思想：
1. **静态 BSP 执行模型**：所有核心以锁步（lock-step）方式执行，使用编译时 arrive-await 屏障替代运行时同步。由于 RTL 代码很少包含发散执行路径（divergent code paths），静态调度是可行的。
2. **消息传递通信**：核心间通过消息传递而非共享内存通信，混合计算和通信，采用延迟更新（delayed updates）策略。
3. **编译器静态调度**：完全依赖编译器调度资源和通信，运行时无需动态同步原语，大幅简化了处理器实现，使得更多核心可以集成到芯片上。

与 Verilator 的关键对比（来自论文中的基准数据）：
- Verilator 多线程在部分基准上**几乎没有扩展性**，最多仅扩展到 6 个核心
- `jpeg` 基准在 Verilator 上完全是串行的，而 Manticore 的 225 核心可以充分利用其并行性
- **关键结论**：通用多核处理器在 RTL 仿真中的线程扩展性很差，同步开销限制了扩展至数十核

## 对"稀疏计算RTL仿真器多线程化"的启示

1. **运行时同步是扩展性杀手**：Manticore 的核心洞察是——通用多核处理器上的 RTL 仿真之所以无法有效扩展，根本原因在于**现代处理器无法高效处理细粒度并行**。在 x86 上使用 pthread/mutex/condition variable 等传统同步原语，同步开销会迅速超过并行收益。对于我们的稀疏计算 RTL 仿真器，这意味着：
   - 必须避免每周期使用操作系统级线程同步
   - 考虑使用**用户态轻量级同步**（如 futex、spinlock、RCU）或**无锁数据结构**
   - 甚至考虑**将多线程模型从 shared-memory 改为 message-passing**

2. **静态调度的可行性**：Manticore 证明了 RTL 的确定性特性使得静态调度成为可能。在稀疏计算中，虽然活跃信号模式可能动态变化，但**电路的依赖图是静态的**。我们可以考虑：
   - 在编译时构建信号的静态依赖图
   - 在运行时根据当前周期的活跃信号集合，动态选择预编译的调度路径
   - 这类似于"静态调度骨架 + 运行时动态激活"

3. **延迟更新的价值**：Manticore 的 delayed update 策略——在 BSP 的 superstep 边界才同步变量——减少了通信频率。在稀疏计算中，这可以进一步优化为：**仅当信号翻转时才传播**，而非每周期都传播所有信号。这本质上就是将 Manticore 的 BSP 模型与事件驱动仿真结合。

4. **专用硬件 vs 通用硬件的鸿沟**：Manticore 225 个简单核心在 FPGA 上 outperform 120 核的 AMD EPYC。这说明在 RTL 仿真中，**核心数量和同步效率比单核心性能更重要**。对于通用 x86 平台，我们需要在软件层面模拟 Manticore 的高效同步——例如使用 SIMD/AVX 指令在单个核心上模拟多个"虚拟核心"，减少跨核心同步需求。

5. **Amdahl 定律的现实**：论文也诚实指出 Manticore 并非免疫于 Amdahl 定律——如果设计中缺乏足够的并行性（如 jpeg 基准），扩展性会提前饱和。这提醒我们，稀疏计算设计的并行性天然较低，多线程策略需要非常谨慎。

## 关键原文摘录

### 核心问题陈述

> The demise of Moore's Law and Dennard Scaling has revived interest in specialized computer architectures and accelerators. Verification and testing of this hardware depend heavily upon cycle-accurate simulation of register-transfer-level (RTL) designs. The fastest software RTL simulators can simulate designs at 1--1000 kHz, i.e. more than three orders of magnitude slower than hardware.

> Unfortunately, state-of-the-art RTL simulators often perform best on a single core since modern processors cannot effectively exploit fine-grain parallelism.

### Manticore 设计哲学

> Manticore uses a static bulk-synchronous parallel (BSP) execution model to eliminate fine-grain synchronization overhead. It relies entirely on a compiler to schedule resources and communication, which is feasible since RTL code contains few divergent execution paths. With static scheduling, communication and synchronization no longer incur runtime overhead, making fine-grain parallelism practical.

> Moreover, static scheduling dramatically simplifies processor implementation, significantly increasing the number of cores that fit on a chip.

### 静态 BSP 执行细节

> Lock-step execution. Same PC on all cores. Message-passing: Mixed computation and communication. Delayed updates. Compile-time arrive-await barrier. "NOP" until straggler is done. No runtime synchronization.

### Verilator 多线程扩展性对比

> Few [benchmarks] did not scale at all with Verilator. At best scales up to only 6 cores with Verilator. jpeg is sequential.

> General-purpose multicores have poor thread scaling in RTL simulation. Synchronization overheads limit scaling to tens of cores.

### 硬件配置对比

| | Verilator v5.006 | Verilator | Manticore |
|---|---|---|---|
| Hardware | AMD EPYC 7V73X | Intel Core i7 9700K | Xilinx Alveo U200 |
| # cores | 120 (dual socket) | 8 | 225 |
| Freq. | 3.0–3.5 GHz | 4.6–4.9 GHz (overclocked) | 0.475 GHz |
| SRAM | 259.6 MiB | 14.5 MiB | 18.45 MiB |

### 结论

> RTL simulation is slow because even state-of-the-art simulators fail to improve their performance by exploiting the abundant fine-grained parallelism in RTL circuits due to the high communication and synchronization cost of modern processors.

> This work presented Manticore, a prototype, hardware-accelerated RTL simulator: Manticore's processes expose a deterministic machine that allows implementing Static BSP. Static BSP replaces runtime synchronization with compile-time synchronization. Statically schedule entire machine.

> Finally, Manticore is not immune to Amdahl's law. If there is insufficient parallelism in the workload, then Manticore's scaling plateaus. Depending on the RTL design, this may happen early (jpeg) or late (me).

## 附加信息

- **会议**: ASPLOS'24 (Volume 4, Vancouver, BC, CA, March 25-29, 2024)
- **DOI**: https://doi.org/10.1145/3623278.3624750
- **FPGA 实现**: 225 核心，475 MHz，Xilinx Alveo U200
- **开源代码**: https://github.com/ManticoreRTL
- **相关论文**: Manticore FPGA 物理设计论文 (FPGA'24)

## 参考链接

- https://arxiv.org/abs/2301.09413
- https://dl.acm.org/doi/10.1145/3623278.3624750
- https://github.com/ManticoreRTL
- https://mayyemami.com/manticore_fpga24_paper.pdf (FPGA'24 物理设计论文)

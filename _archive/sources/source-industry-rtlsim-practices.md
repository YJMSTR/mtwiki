---
title: "业界实践：Google / Intel / NVIDIA 的 RTL 仿真性能优化"
description: "搜集 Google（FireSim/Chipyard）、Intel（ROHD）、NVIDIA（GEM）等工业界大厂在 RTL 仿真加速上的公开技术、框架与社区动向。"
source_url: "https://github.com/chipsalliance/chisel/discussions/5142"
source_type: "doc"
author: "NVIDIA Research / Google / Intel"
date: "2025-2026"
tags: [industry-practice, RTL-simulation, GPU-acceleration, FPGA-emulation, Google, Intel, NVIDIA]
keywords: [FireSim, Chipyard, GEM, ROHD, ChiselSim, FPGA-emulation, GPU, CUDA]
capture_date: "2026-07-01"
---

# 业界实践：Google / Intel / NVIDIA 的 RTL 仿真性能优化

## 来源

- URL: 多篇技术文档与论文（见下）
- 类型: doc / blog / paper
- 作者: NVIDIA Research, Google (UC Berkeley), Intel
- 日期: 2023–2026

---

## 摘要

工业界对 RTL 仿真性能的需求远超学术界。Google（通过 UC Berkeley 的 FireSim/Chipyard）、Intel（ROHD 框架）、NVIDIA（GEM GPU 加速）分别从 **FPGA 全系统仿真**、**现代语言前端 + 验证生态**、**GPU 批量加速**三条路线推进。本文档汇总其公开的技术路线、性能数据和社区互动，为我们的多线程 RTL 优化器提供工业需求视角。

---

## 关键要点

### 1. NVIDIA —— GEM：GPU 加速 RTL 仿真（2025）

- **项目**: GEM (GPU-Accelerated Emulator-Inspired RTL Simulation)
- **链接**: [NVIDIA Research 页面](https://research.nvidia.com/publication/2025-06_gem-gpu-accelerated-emulator-inspired-rtl-simulation) | [GitHub](https://github.com/NVlabs/GEM) | [ChiselSim 集成讨论](https://github.com/chipsalliance/chisel/discussions/5142)
- **核心路线**: NVIDIA 认为传统 CPU 多线程 RTL 仿真遇到两大瓶颈：
  1. CPU 前端被编译后的电路代码量压垮；
  2. 标准多核 CPU 的内存带宽有限，并行度受限。
  因此，NVIDIA 转向 GPU，但发现 RTL 的**不规则分区**与 GPU 的 **SIMT 架构**天然冲突。解决方案是受 FPGA 仿真器启发的**虚拟 VLIW 架构**。
- **技术细节**:
  - 将 RTL 综合为门级网表（E-AIG），映射为 domain-specific ISA；
  - ISA 指令长度 8192/16384/32768 bit，由 256 线程 lockstep 加载；
  - 全局内存读取完全合并（coalesced），规避 GPU 的 irregular memory access 瓶颈；
  - Boomerang 折叠机制将逻辑级数从 148 压缩到 19（以 Gemmini 为例）。
- **性能数据**:
  - 平均比领先商业工具快 **9.15×**；
  - 平均比 8 线程 Verilator 快 **5.98×**；
  - 平均比单线程 Verilator 快 **24.87×**；
  - NVDLA 峰值快 **64.76×**。
- **工业落地信号**:
  - GEM 论文获 DAC 2025 **Best Paper Nomination**；
  - 2026 年 1 月，Chisel 社区（SiFive 主导）主动发起讨论，希望将 GEM 集成到 ChiselSim 作为可选后端；
  - 讨论中提到："Large Chisel designs can take hours or days to simulate on CPU" —— 这正是工业痛点。
- **对项目的启示**:
  - GPU 方向已被大厂验证可行，但需要全新的执行模型（虚拟 VLIW），而非简单移植现有 C++ 仿真核；
  - 如果我们的优化器保留 GPU 后端扩展能力，应在 IR 层就设计适合 GPU 批量执行的数据布局。

### 2. Google / UC Berkeley —— FireSim + Chipyard：FPGA 加速全系统仿真

- **项目**: FireSim ([firesim/firesim](https://github.com/firesim/firesim))
- **核心路线**: 不解决 CPU 软件仿真内部的多线程问题，而是**绕过**它——用 FPGA 直接硬件加速 RTL 仿真。FireSim 在 Amazon EC2 F1 / 本地 FPGA 上运行，将 RTL 设计（Rocket、BOOM、XiangShan 等）映射到 FPGA  fabric，实现 **10–100 MHz** 的仿真速度，比软件 RTL 仿真（~1 kHz）快数个数量级。
- **技术细节**:
  - 基于 FAME-1（FPGA-Accelerated Microarchitecture Evaluation）转换，将 RTL 中的时序逻辑替换为 FPGA 上的时钟；
  - 提供完整的全系统模型：DRAM、Ethernet、Disk、UART 等；
  - 支持从单节点到数千节点的数据中心级仿真；
  - 与 Chipyard 集成：RTL 设计 → FireSim 编译流程 → FPGA bitstream。
- **Chipyard 中的软件仿真优化**:
  - Chipyard 文档中明确提到 ["Speeding up your RTL Simulation by 2x!"](https://chipyard.readthedocs.io/en/latest/Simulation/index.html)；
  - 软件仿真用于快速编译和全波形调试，FPGA 仿真用于操作系统启动和完整 workload；
  - 两者互补，但软件仿真速度仍是瓶颈（O(1 kHz)）。
- **工业落地信号**:
  - FireSim 已被 Google、Intel、AMD、Apple 等公司的研究部门广泛使用；
  - 大量学术论文基于 FireSim 平台产出，验证了其工业级可靠性；
  - 2024 年起支持本地 FPGA 和云 FPGA 混合部署。
- **对项目的启示**:
  - FPGA 加速是"终极解"，但成本高、编译慢（数小时到数天）、调试可见性差。软件多线程仿真仍有不可替代的价值：快速迭代、全波形、低成本；
  - 我们的优化器应定位为**软件仿真器的性能增强层**，与 FireSim 形成互补而非替代。

### 3. Intel —— ROHD：Dart 硬件开发框架与仿真生态

- **项目**: ROHD (Rapid Open Hardware Development) —— [intel/rohd](https://github.com/intel/rohd)
- **核心路线**: Intel 选择用 **Dart** 语言构建硬件描述和验证框架，而非传统的 Verilog/SystemVerilog。ROHD 提供：
  - 硬件构造语言（HCL）前端；
  - 内置仿真器 backend；
  - 与 cocotb、UVM 等验证框架的集成能力。
- **技术细节**:
  - 用 Dart 的面向对象和函数式特性描述硬件模块，生成 Verilog 或直接仿真；
  - 仿真器支持波形 dump、断言、覆盖率收集；
  - 强调验证生产力（debuggability、test reuse）而非单纯仿真速度。
- **工业落地信号**:
  - 483 stars，83 forks，145 open issues，说明 Intel 在持续投入；
  - 被用于 Intel 内部部分原型验证流程；
  - 与 SystemVerilog 仿真器（VCS、Xcelium）的交互接口是重点。
- **对项目的启示**:
  - 工业界不只关心 "MHz"，还关心**调试能力**、**断言覆盖率**、**与现有验证流程的兼容性**；
  - 如果我们的多线程优化器破坏了波形时间一致性或断言触发顺序，工业用户会无法接受。Multisim 的"波形分散在 N+1 个仿真中"就是一个警示。

### 4. 其他工业动向

- **Xilinx/AMD / Cadence / Synopsys 的混合验证流**:
  - 根据 JETIR 2025 论文，工业界正在推动"Cloud FPGA Prototyping"和"AI-Powered Verification"；
  - 混合验证流（emulation + prototyping + cloud）将时间从 18–24 个月压缩到 6–9 个月；
  - 软件 RTL 仿真仍是早期验证和调试的主力，但性能瓶颈日益突出。
- **NVIDIA 内部仿真校准**:
  - 根据 NVIDIA 实习生简历（公开资料），NVIDIA 团队持续进行 "simulation accuracy calibration" 和 "GPU runtime estimation"，确保仿真结果与真实硅片性能的差异小于 1%；
  - 这说明工业级仿真器必须**精确**，加速不能以牺牲正确性为代价。

---

## 对 RTL 仿真器多线程化的启示

1. **性能是刚需，但正确性和调试能力是底线**：NVIDIA 愿意投入研发全新 GPU 架构来加速仿真，Intel 愿意用 Dart 重构验证流程，都说明工业界对仿真速度极度敏感。但所有加速方案都强调结果与参考模型一致（GEM 与商业工具对比、FireSim 与 ASIC 对比）。
2. **GPU 和 FPGA 是两条互补路线，软件多线程仍有不可替代性**：
   - FPGA（FireSim）最快，但编译慢、调试难；
   - GPU（GEM）较快且可访问，但需要新架构；
   - CPU 多线程（Verilator、我们的优化器）最易集成、调试最友好，但天花板最低。
   - 最佳方案可能是**三层架构**：CPU 快速调试 → GPU 批量回归 → FPGA 全系统签核。
3. **与现有生态的兼容性决定采用率**：ChiselSim 社区主动想集成 GEM，说明如果我们的优化器能提供 Verilator-compatible 接口（VPI、DPI、FIRRTL 前端），采用阻力会大幅降低。
4. **张量代数/编译器框架是工业界的长期兴趣点**：RTeAAL Sim 虽然来自学术界，但 NVIDIA 和 Intel 都有成熟的编译器团队（MLIR、CIRCT）。如果多线程优化能嵌入到 MLIR/CIRCT 生态，工业落地可能性会更高。
5. **周期精确性是硬约束，不能轻易牺牲**：Multisim 为了可扩展性牺牲周期精确性，只能用于接口级验证。Parendi 即使跑到 5888 核也保持 cycle-accurate。我们的优化器必须保证 cycle-accuracy。

---

## 原文摘录

> "GEM is an open-source RTL logic simulator developed by NVIDIA Research that leverages CUDA acceleration to dramatically speed up RTL simulation... delivers 5-40X speedup compared to leading CPU-based RTL simulators."
> —— chipsalliance/chisel Discussion #5142

> "FireSim allows RTL-level simulation at orders-of-magnitude faster speeds than software RTL simulators... simulations run at 10s to 100s of MHz."
> —— FireSim Documentation

> "The Rapid Open Hardware Development (ROHD) framework is a framework for describing and verifying hardware in the Dart programming language."
> —— Intel ROHD GitHub

> "RTL simulation—a critical phase in the verification flow—now accounts for over 24% of total development time. Meanwhile, first-pass silicon success rates have dropped by 18% over the past 12 years."
> —— CCSS Paper (arXiv:2507.08406), citing industry data

> "Calibrated simulation results against actual silicon performance, identifying and resolving discrepancies, which led to more accurate projections and informed decision-making."
> —— NVIDIA Intern CV (public)

---

## 相关链接

- [GEM (NVIDIA Research)](https://research.nvidia.com/publication/2025-06_gem-gpu-accelerated-emulator-inspired-rtl-simulation)
- [GEM GitHub](https://github.com/NVlabs/GEM)
- [ChiselSim GEM Integration Discussion](https://github.com/chipsalliance/chisel/discussions/5142)
- [FireSim GitHub](https://github.com/firesim/firesim)
- [Chipyard Simulation Docs](https://chipyard.readthedocs.io/en/latest/Simulation/index.html)
- [Intel ROHD](https://github.com/intel/rohd)
- [JETIR: Accelerating ASIC Verification Using FPGA](https://www.jetir.org/papers/JETIR2506550.pdf)
- [CCSS Paper (arXiv:2507.08406)](https://arxiv.org/html/2507.08406v1)

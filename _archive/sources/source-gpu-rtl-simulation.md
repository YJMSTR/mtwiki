---
title: GPU 加速 RTL 仿真：NVIDIA GEM 与 CUDA 门级并行评估
description: NVIDIA Research 开源的 GEM 模拟器及其 GPU 加速 RTL 仿真的技术路线、性能基准与生态集成现状
source_url: "https://github.com/NVlabs/GEM"
source_type: "github-repo"
author: "Zizheng Guo, Yanqing Zhang, Runsheng Wang, Yibo Lin, Haoxing Ren (NVIDIA Research)"
date: "2025-06"
tags: [gpu, cuda, rtl-simulation, gate-level, nvidia, gem, aig, vliw]
keywords: [GPU RTL simulation, NVIDIA GEM, CUDA gate-level simulation, parallel gate evaluation, AIG, Boolean processor, VLIW]
capture_date: "2026-07-02"
---

# GPU 加速 RTL 仿真：NVIDIA GEM 与 CUDA 门级并行评估

## 来源

- URL: https://github.com/NVlabs/GEM
- 类型: github-repo / paper
- 作者: Zizheng Guo, Yanqing Zhang, Runsheng Wang, Yibo Lin, Haoxing Ren (NVIDIA Research)
- 日期: 2025-06 (DAC 2025 论文发表)

## 摘要

GEM（GPU-Accelerated Emulator-Inspired RTL Simulation）是 NVIDIA Research 开源的 RTL 逻辑仿真器，利用 CUDA 加速在多种开源设计上实现了 **5–40 倍** 于主流 CPU 仿真器的性能提升。其核心创新在于：不采用传统的 LUT 查表或 RTL-to-CUDA 转译路线，而是将 RTL 综合为 AIG（And-Inverter Graph）门级网表，再映射到一颗虚拟的 VLIW（Very Long Instruction Word）多核布尔处理器上，由 GPU 线程块以锁步方式解释执行。映射流程（综合、划分、物理设计、位流生成）类比 FPGA CAD 流程，但完全在软件层面运行，一次综合成本可复用于多个测试向量。

## 关键要点

- **性能数据**：在 NVIDIA A100 上，NVDLA 深度学习加速器仿真速度达到 **Verilator 单线程的 64.76 倍**、商业单核仿真器的 38.85 倍；RocketChip 与 Gemmini 等 RISC-V 设计亦有显著加速。OpenPiton8（540 万门）位流仅占用 162.4 MB GPU 显存。
- **架构创新**：设计了面向 GPU 的 VLIW ISA（8192/16384/32768 bit 指令长度），256 线程以完全合并的内存读取方式加载指令，利用 CUDA Cooperative Groups 实现跨 cycle/stage 的设备级同步，避免内核启动开销。
- **映射流程**：RTL → Yosys AIG 综合 → RepCut 深度优化划分 → Boomerang 折叠减少逻辑级数 → 位流生成 → CUDA 核解释执行。Boomerang 层数通常为逻辑深度的 1/6–1/8。
- **工程实现**：映射流程（Rust）+ CUDA 解释核（C++/CUDA）。编译/综合时间慢于 CPU 仿真器，但为一次性成本，同一设计可换用不同 testbench 无需重新映射。
- **生态集成**：Chisel 社区已有讨论将 GEM 集成为 ChiselSim 后端（见 chipsalliance/chisel#5142），目标是为大规模 SoC 验证提供低成本 GPU 加速方案。
- **局限**：当前仅支持同步逻辑，异步逻辑支持有限；需要静态 VCD 输入（非交互式 testbench）；依赖 NVIDIA GPU 与 CUDA 环境。

## 对 RTL 仿真器多线程化的启示

GEM 的路线证明：GPU 加速 RTL 仿真的瓶颈不在于算力，而在于 **电路图的不规则稀疏性** 与 GPU 偏好的规则合并内存访问之间的错配。GEM 的解决方案是「编译时重构 + 运行时解释」——在 CPU 侧做 heavy-lifting 的划分与折叠，生成高度规则的 VLIW 位流，让 GPU 侧只需做简单的位运算与合并读取。这与 Verilator 的多线程化思路（在 C++ 层面做模块分区与线程调度）形成互补：前者用 GPU 数据并行吞吐掩盖延迟，后者用 CPU 任务并行降低单核负载。对于我们的多线程 RTL 仿真器项目，可借鉴的是：
1. **门级评估的批量化**：将组合逻辑评估转化为位运算批量处理，降低事件调度开销；
2. **AIG 作为通用中间表示**：Yosys 的 AIG 综合已经成熟，可作为 RTL 与后端执行器之间的桥梁；
3. **显存布局优化**：利用位流紧凑编码（OpenPiton8 仅 162.4 MB）实现大型设计在消费级 GPU 上的可运行性。

## 代码示例

### GEM 使用流程（精简版）

```bash
# 1. 安装依赖：CUDA、Yosys、Rust
git clone https://github.com/NVlabs/GEM.git
cd GEM

# 2. 综合与映射（一次性）
cargo run --release --bin gem-synth -- \
  --top top \
  -i design.v \
  -o design.bitstream

# 3. 运行仿真
cargo run --release --bin gem-sim -- \
  --bitstream design.bitstream \
  --inputs input.vcd \
  --outputs output.vcd
```

### 示例设计统计（来自论文 Table I）

| 设计 | E-AIG 门数 | 逻辑级数 | Boomerang 层数 | 位流大小 |
|------|-----------|---------|--------------|---------|
| NVDLA | 668,746 | 63 | 9 | 11.2 MB |
| RocketChip | 346,687 | 82 | 13 | 9.2 MB |
| Gemmini | 1,831,381 | 148 | 19 | 44.4 MB |
| OpenPiton1 | 682,646 | 66 | 119 | 18.4 MB |
| OpenPiton8 | 5,479,795 | 66 | 13 | 947 | 162.4 MB |

### 性能对比（来自论文 Table II，单位：Hz）

| 设计 | GEM (A100) | Verilator 1T | 商业工具 1T | 加速比 (vs Verilator) |
|------|-----------|-------------|------------|---------------------|
| NVDLA | 2,847.5 | 44.0 | 73.3 | **64.76x** |
| RocketChip | 1,023.5 | 78.3 | 112.5 | 13.07x |
| Gemmini | 238.3 | 18.3 | 28.3 | 13.02x |
| OpenPiton1 | 1,282.5 | 180.0 | 250.0 | 7.13x |

## 原文摘录

> "Rather than simulating circuits using LUT-based methods, we introduce a technique that maps circuit logic into a specialized virtual Boolean processor with a Very Long Instruction Word (VLIW) architecture, optimized for execution on CUDA-compatible GPUs."
> — GEM (DAC 2025)

> "The number of boomerang layers is 6–8× smaller than the logic depth (e.g., reduced from 148 to 19 for Gemmini). We note that the GEM bitstream is a very concise format for circuit logic. It takes only 162.4 MB of GPU memory to store the whole assembled GEM bitstream even for our largest design OpenPiton8 which has over 5 million logic gates."
> — GEM (DAC 2025)

> "GEM is an open-source RTL logic simulator with CUDA acceleration, developed and maintained by NVIDIA Research. GEM can deliver up to 5–40X speed-up compared to CPU-based leading RTL simulators."
> — https://github.com/NVlabs/GEM

## 相关链接

- [GEM GitHub 仓库](https://github.com/NVlabs/GEM)
- [GEM 论文 (DAC 2025)](https://d1qx31qr3h6wln.cloudfront.net/publications/GEM.pdf)
- [ChiselSim 集成 GEM 讨论](https://github.com/chipsalliance/chisel/discussions/5142)
- [GATSPI: GPU Accelerated Gate-level Simulation for Power Improvement (DAC 2022)](https://doi.org/10.1145/3489517.3530482)
- [GLOAM: GPU Logic Simulation Using 0-Delay and Re-simulation Acceleration (ICCAD 2024)](https://doi.org/10.1109/ICCAD57390.2024.10663616)
- [CUDA Cooperative Groups](https://developer.nvidia.com/blog/cooperative-groups/)

---
title: 标准 RTL 基准测试集汇总
description: 搜集适用于 RTL 仿真器性能评估的标准 benchmark suites，包括 RISC-V、OpenCores、IWLS、VTR、EPFL、OpenROAD 等来源
date: "2026-06-19"
source_type: "doc"
author: "Multiple Sources"
tags: ["benchmark", "test-suite", "RISC-V", "OpenCores", "IWLS", "VTR", "EPFL", "OpenROAD"]
keywords: ["RISC-V benchmark", "OpenCores", "IWLS benchmarks", "VTR benchmark", "EPFL benchmark", "OpenROAD benchmarks", "digital-design-dataset"]
capture_date: "2026-06-19"
---

# 标准 RTL 基准测试集汇总

## 来源

- URL: https://github.com/gtri/digital-design-dataset
- 类型: doc / github
- 作者: Georgia Tech Research Institute (GTRI) / digital-design-dataset 维护者
- 日期: 2024-11-04
- 补充来源:
  - EPFL Combinational Benchmark: https://github.com/lsils/benchmarks
  - IWLS 2005: https://iwls.org/iwls2005/benchmarks.html
  - OpenCores: https://opencores.org/
  - VTR (Verilog to Routing): https://github.com/verilog-to-routing/vtr-verilog-to-routing
  - OpenROAD: https://github.com/The-OpenROAD-Project
  - TopoRTL (ICLR 2026): https://github.com/BUPT-GAMMA/TopoRTL

## 摘要

本文档汇总了 RTL 仿真器性能评估中常用的标准 benchmark suites。Benchmark 的选择直接决定加速比结论的可信度——小设计（如 picorv32）在 16 线程下可能反而降速，大设计（如 NVDLA）才能展现多线程优势。核心推荐组合：**RISC-V 处理器核（小）+ OpenTitan / NVDLA（大）+ 组合逻辑基准（EPFL）** 构成覆盖小/中/大三个粒度的测试矩阵。

## 关键要点

### 1. 处理器核 / SoC 级 Benchmark（中等规模，~1K–50K 门）

| Benchmark | 来源 | 规模 | 说明 |
|-----------|------|------|------|
| **picorv32** | PicoRISC-V / OpenCores | ~3K LUT | 极简 RISC-V 核，广泛用于小设计基线 |
| **riscv-mini** | UC Berkeley | ~3.3K LOC | 教学级 RISC-V，RTLflow 论文使用 |
| **VexRiscv** | SpinalHDL | 中等 | 可配置 RISC-V 核，性能优化空间丰富 |
| **CVA6 (Ariane)** | OpenHW Group | 较大 | 6 级顺序 RISC-V，支持 Linux |
| **BlackParrot** | UCSD | 大 | 多核 RISC-V，适合多线程扩展测试 |
| **SERV Core** | OpenCores | 极小 | 最小面积 RISC-V 实现，适合 stress-test 小设计 |
| **OpenTitan** | lowRISC | ~500K 变量 | 安全芯片 SoC，倒波形测试中的"大型设计"代表 |
| **NVDLA** | NVIDIA | 512K LOC | 深度学习加速器，最大规模 benchmark 之一 |
| **Spinal** | SpinalHDL | 6.9K LOC | 可综合 RISC-V CPU，RTLflow 论文使用 |

### 2. 通用数字电路 Benchmark（小至中等规模）

| Benchmark | 来源 | 类型 | 说明 |
|-----------|------|------|------|
| **OpenCores / FreeCores** | https://opencores.org | 混合 | 126+ 设计的手选子集，涵盖 UART、SPI、FIFO、DES、AES 等 |
| **ITC'99 (IWLS)** | https://iwls.org/iwls2005/benchmarks.html | 时序电路 | RT-level 基准，带 ATPG 结果，适合故障模拟 |
| **IWLS 2005** | IWLS Workshop | 混合 | 含 Faraday / Gaisler 子集，Vth 优化论文常用 |
| **ISCAS 85 / 89** | 经典 | 组合/时序 | 门级基准，学术界最广泛使用的电路集 |
| **LGSynth 89 / 91** | Mentor Graphics | 组合 | 早期逻辑综合基准，适合面积/时序测试 |
| **MCNC 20** | 北卡大学 | 组合 | 20 个经典组合电路 |

### 3. FPGA / EDA 工具链 Benchmark（中至大规模）

| Benchmark | 来源 | 类型 | 说明 |
|-----------|------|------|------|
| **VTR (Verilog to Routing)** | https://github.com/verilog-to-routing | 混合 | 含 Titan 2.0、Koios 2.0，FPGA 综合与布局布线完整流程 |
| **EPFL Combinational Benchmark** | https://github.com/lsils/benchmarks | 组合 | 算术、控制、随机逻辑三大类，共 23 个电路，从少量门到百万门 |
| **Titan 2.0** | VTR 套件 | 大规模 | 百万门级 FPGA 设计，如 LU32PEEng（百万 LUT） |
| **Koios 2.0** | VTR 套件 | DNN 加速器 | 面向 FPGA 的深度学习加速器基准 |
| **OpenPiton Design Benchmark** | Princeton | 多核 | 开源多核研究平台，含 NoC 和缓存 |
| **HDLBits / VerilogEval Subset** | 在线平台 | 教学级 | 小规模组合逻辑，适合回归测试 |

### 4. 学术仿真器论文常用 Benchmark 组合

| 论文 | 使用 Benchmark | 覆盖范围 |
|------|----------------|----------|
| **Manticore (ASPLOS 2024)** | bc, mm, cgra, vta, rv32r, jpeg, blur, mc, noc | 小→大，含处理器、加速器、网络、编解码 |
| **Parendi (arXiv 2024)** | 对 Verilator 2–32 线程扫描 | 未公开完整列表，但包含大型工业 design |
| **RTLflow (DAC 2022)** | riscv-mini, Spinal, NVDLA | 小→大，处理器 + 加速器 |
| **yodalee FST 优化** | picorv32, vortex mini sgemm, OpenTitan SHA, NVDLA gnet | 小→大，验证波形 I/O 瓶颈 |
| **TopoRTL (ICLR 2026)** | ITC99, OpenCores, VexRiscv, DeepCircuitX | 适合 RTL 表示学习 |

### 5. Benchmark 选择策略（针对多线程 RTL 仿真）

根据 Manticore §7.1 的三个粒度区域，推荐按以下组合构建测试矩阵：

| 区域 | 代表设计 | 每周期指令数 | 预期多线程收益 | 用途 |
|------|----------|-------------|----------------|------|
| **小设计** | picorv32, SERV | < 3K | 负收益或 1.0–1.2× | 验证低开销/回归测试 |
| **中等设计** | riscv-mini, OpenTitan SHA | 10K–100K | 1.5–4× | 主要加速比测量区间 |
| **大设计** | NVDLA, OpenTitan, vta | > 100K | 3–10×+ | 验证多线程扩展上限 |
| **组合逻辑** | EPFL 算术/控制 | 无状态 | 取决于逻辑深度 | 评估 DAG 分区质量 |

### 6. 具体获取命令

```bash
# 1. digital-design-dataset（一键获取多个 benchmark）
git clone https://github.com/gtri/digital-design-dataset.git
cd digital-design-dataset
# 查看可用设计列表
cat dataset_sources.json | jq '.[] | select(.status == "✅") | .name'

# 2. EPFL Combinational Benchmark
git clone https://github.com/lsils/benchmarks.git
cd benchmarks/epfl
# 包含：adder, max, sin, sqrt, log2, multiplier, div, barrel shifter 等

# 3. VTR Benchmarks
git clone https://github.com/verilog-to-routing/vtr-verilog-to-routing.git
cd vtr-verilog-to-routing/vtr_flow/benchmarks
# 包含：titan_benchmarks, koios, mcnc, iscas 等

# 4. OpenCores 手动下载
# 访问 https://opencores.org/ 按项目下载 Verilog
# 推荐：aes, des, i2c, md5, sha256, uart16550

# 5. NVDLA（大型加速器）
git clone https://github.com/nvdla/hw.git
cd hw
# 使用 Verilator 编译时需注意 memory model 规模

# 6. OpenTitan（大型 SoC）
git clone https://github.com/lowRISC/opentitan.git
cd opentitan
# 构建系统使用 Bazel，需按文档准备依赖
```

## 对 RTL 仿真器多线程化的启示

1. **必须覆盖三个粒度区域**：仅用小设计（如 picorv32）会导致"多线程无效"的误判；仅用 NVDLA 会掩盖小设计的同步开销。
2. **EPFL 组合逻辑基准是 DAG 分区质量的照妖镜**：纯组合逻辑无状态，可精确评估 Verilator 的 macro-task 合并与分区算法优劣。
3. **OpenTitan 和 NVDLA 是编译时间的 stress test**：Verilator 对 sr15 级设计生成多线程代码需 8 小时+ 1TB 内存，benchmark 必须包含编译时间指标。
4. **RISC-V 处理器核是"黄金基准"**：学术界广泛认可，可横向对比 Manticore、Parendi、RTLflow 等结果。

## 原文摘录

> "OS - OpenCores / FreeCores (hand-curated subset, ~126 designs)"
> — digital-design-dataset, Dataset Sources

> "Benchmark: ITC99, OpenCores, VexRiscv, DeepCircuitX"
> — TopoRTL, Data Collection

> "The EPFL combinational benchmark suite. In International Workshop on Logic and Synthesis (IWLS), 2015."
> — Circuit Foundation Model Survey, Reference [126]

> "We evaluate RTLflow's performance on three industrial designs, NVDLA, Spinal, and riscv-mini."
> — RTLflow 论文, §4

> "Our testcase main source is rtlmeter, finally selected: vortex mini sgemm, OpenTitan SHA, NVDLA gnet."
> — yodalee, "让 Verilator 倒波形快还要更快"

## 相关链接

- [digital-design-dataset (GTRI)](https://github.com/gtri/digital-design-dataset)
- [EPFL Combinational Benchmarks](https://github.com/lsils/benchmarks)
- [IWLS 2005 Benchmarks](https://iwls.org/iwls2005/benchmarks.html)
- [OpenCores](https://opencores.org/)
- [VTR (Verilog to Routing)](https://github.com/verilog-to-routing/vtr-verilog-to-routing)
- [OpenROAD](https://github.com/The-OpenROAD-Project)
- [TopoRTL GitHub](https://github.com/BUPT-GAMMA/TopoRTL)
- [NVDLA Hardware](https://github.com/nvdla/hw)
- [OpenTitan](https://github.com/lowRISC/opentitan)
- [PicoRV32](https://github.com/YosysHQ/picorv32)

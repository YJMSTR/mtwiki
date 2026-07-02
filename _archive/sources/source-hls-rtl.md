---
title: "High-Level Synthesis (HLS) for RTL：工具链、编译流程与开源生态"
description: 全面梳理从C/C++/SystemC到RTL的高层次综合工具链，涵盖商业工具（Vitis HLS、Catapult、Stratus）和开源工具（LegUp、Bambu），分析HLS对RTL仿真器多线程化的影响与协同机会
source_url: "https://arxiv.org/abs/2306.15552"
source_type: "paper"
author: "A. Survey on DL Hardware Accelerators (et al.)"
date: "2023-04-18"
tags: ["hls", "high-level-synthesis", "vitis-hls", "catapult", "legup", "bambu", "systemc", "c-to-rtl"]
keywords: ["High-Level Synthesis", "Vitis HLS", "LegUp HLS", "Bambu HLS", "SystemC HLS", "C++ HLS Xilinx", "Catapult HLS", "Stratus HLS"]
capture_date: "2026-07-02"
---

# High-Level Synthesis (HLS) for RTL

## 来源

- URL: https://arxiv.org/abs/2306.15552 (A Survey on Deep Learning Hardware Accelerators)
- URL: https://www.amd.com/en/products/software/adaptive-socs-and-fpgas/vitis/vitis-hls.html
- URL: https://github.com/ferrandi/PandA-bambu
- URL: https://github.com/B-Lang-org/bsc (Bluespec含HLS相关)
- 类型: paper / doc / github
- 作者: Multiple / 行业报告
- 日期: 2023-2026

## 摘要

High-Level Synthesis（HLS）将C/C++/SystemC/MATLAB等高级语言算法自动转换为RTL（Verilog/VHDL），是弥合软件算法与硬件实现之间鸿沟的关键技术。商业工具（AMD Vitis HLS、Siemens Catapult、Cadence Stratus）已在FPGA/ASIC领域广泛应用；开源工具（LegUp、Bambu）则为学术研究和EDA民主化提供了重要基础。HLS生成的RTL代码质量与手写RTL日益接近，但其仿真、验证和调试流程仍依赖下游RTL仿真器。理解HLS工具链的编译流程、优化策略和局限性，对RTL仿真器多线程化具有重要的协同设计意义。

## 关键要点

### 1. HLS 核心编译流程

所有HLS工具遵循统一的三阶段范式：

```
高级语言源码 (C/C++/SystemC)
        ↓
[前端] 解析 → 中间表示 (LLVM IR / 自定义IR)
        ↓
[中端] 编译优化 (循环变换、数据流分析、别名分析)
        ↓
[后端] 调度(Scheduling) + 绑定(Binding) + 资源分配
        ↓
RTL生成 (Verilog / VHDL / SystemVerilog)
        ↓
逻辑综合 + 布局布线
```

关键后端步骤：
- **调度**：确定每个操作在哪个时钟周期执行
- **绑定**：将操作映射到具体功能单元（加法器、乘法器、寄存器）
- **控制逻辑生成**：状态机（FSM）控制数据通路

### 2. 商业HLS工具对比

| 工具 | 厂商 | 输入语言 | 目标平台 | 核心特点 | 许可 |
|------|------|----------|----------|----------|------|
| **Vitis HLS** | AMD/Xilinx | C/C++, OpenCL | FPGA/ACAP | 与Vivado深度集成，支持pragma驱动优化，MATLAB集成 | 商业（C综合免费） |
| **Catapult HLS** | Siemens/Mentor | C++, SystemC | ASIC/FPGA | 原生双语言支持，Design Checker预综合bug检测，物理感知流程 | 商业 |
| **Stratus HLS** | Cadence | SystemC, C++ | ASIC | 与Genus/Joules/Xcelium深度集成，支持低功耗设计 | 商业 |
| **Intel HLS** | Intel/Altera | C++ | Intel FPGA | 与Quartus集成，支持OpenCL | 商业 |

**Vitis HLS 关键特性**（2026版）：
- 支持`#pragma HLS`系列优化指令：pipeline、unroll、array_partition、interface、dataflow
- 新顶层性能pragma帮助自动达成高QoR（Quality of Results）
- 支持HLS任务（任务级并发）、HLS向量（数据级并行）、HLS流（任务间通信）
- 许多设计可实现FMAX ≥ 500MHz
- 支持浮点（IEEE-754单/双精度）直接综合

**Catapult HLS 关键特性**：
- 原生支持ANSI C++和SystemC双语言
- 抽象模型代码量通常比手写RTL减少80%，仿真速度提升1000倍
- 支持多VT（Multi-Threshold Voltage）物理感知流程，面向先进工艺节点
- 验证优化的RTL可直接接入UVM流程

### 3. 开源HLS工具：LegUp与Bambu

**LegUp HLS**（University of Toronto → Microchip，2020年被收购）：
- **独特定位**：不生成纯硬件，而是生成**处理器+加速器混合架构**（MIPS软核 + 硬件加速器）
- **LLVM集成**：作为LLVM后端pass实现，利用成熟编译器分析和优化
- **硬件/软件协同设计**：可在处理器上分析执行热点，将热点函数自动综合为硬件加速器
- **性能数据**：相比MIPS软核软件，LegUp生成的纯硬件实现执行速度提升8倍，能耗降低18倍
- **商业转化**：2020年被Microchip收购，集成到PolarFire FPGA的SmartHLS工具链中

> "LegUp enables software developers to exploit hardware acceleration without requiring manual RTL design, thereby reducing the complexity and entry barrier traditionally associated with hardware development." — From RTL to Fabrication (2026)

**Bambu HLS**（Politecnico di Milano）：
- **最成熟的开源HLS框架**：命令行工具，支持广泛的C/C++构造（包括指针运算、动态内存解析等Vitis HLS不支持的特性）
- **MLIR集成**：支持以LLVM IR作为输入，可与MLIR-based前端（如SODA Synthesizer）无缝衔接
- **多目标支持**：通过预表征的功能单元库，支持Xilinx/Intel/Lattice/NanoXplore等多家FPGA和ASIC目标
- **浮点支持**：通过FloPoCo框架或优化的soft-float库支持非标准浮点编码
- **OpenMP扩展**：最新版本支持多线程OpenMP应用的硬件综合
- **学术贡献**：被引用为开源HLS的基准工具，在CERN的FPGA ML推理（hls4ml后端）和ASAP 7nm等项目中得到验证

> "Bambu aids designers in the high-level synthesis of complex applications. It supports various C/C++ constructs and follows a software compilation-like flow. The tool consists of three phases: front-end, middle-end, and back-end." — Bambu DAC 2021 Paper

### 4. HLS 优化指令与编译器技术

HLS的核心优化由**pragma/directive**驱动，典型优化包括：

| 优化指令 | 作用 | 对性能的影响 |
|----------|------|-------------|
| `#pragma HLS PIPELINE` | 循环/函数流水线化 | 显著提升吞吐量，降低II（Initiation Interval） |
| `#pragma HLS UNROLL` | 循环展开 | 增加并行度，提高面积 |
| `#pragma HLS ARRAY_PARTITION` | 数组分割到多个BRAM | 提升并行访问能力 |
| `#pragma HLS DATAFLOW` | 任务级数据流并行 | 允许多个任务重叠执行 |
| `#pragma HLS INLINE` | 函数内联 | 减少调用开销，优化调度 |
| `#pragma HLS INTERFACE` | 定义硬件接口协议 | 控制AXI/AP/BRAM等接口 |

**编译器技术前沿**：
- **ScaleHLS**：基于MLIR的编译器，在图级、循环级、指令级三层优化，自动生成Vitis HLS pragma
- **HIDA**：扩展ScaleHLS，生成高效数据流加速器
- **C2HLSC**：利用LLM将C程序自动转换为HLS兼容版本
- **SODA Synthesizer**：端到端Python→MLIR→Bambu→OpenROAD→GDSII开源流程

### 5. HLS vs 手写RTL：性能对比

**BittWare案例研究**（RSS网络功能）：

| 指标 | Verilog RTL | HLS C++ | 变化 |
|------|-------------|---------|------|
| CLB | 44,435 | 2,385 | ↓ 94.6% |
| Block RAM | 12 | 1 | ↓ 91.7% |
| 寄存器 | 52,352 | 4,843 | ↓ 90.7% |
| 代码行数 | 650 | 459 | ↓ 29.4% |

> 关键原因：HLS版未使用FIFO，工具自动优化了流水线；RTL版手动实现导致冗余。

**学术界共识**：
- HLS在算法密集型、数据流型应用中通常优于手写RTL（开发速度、QoR平衡）
- 控制密集型、协议密集型设计仍倾向手写RTL
- 任意CPU目标代码直接HLS通常效果很差，需要按硬件思维重写

## 对 RTL 仿真器多线程化的启示

1. **HLS生成RTL的仿真瓶颈**：HLS工具通常生成高度流水线化、数据通路复杂的RTL，此类设计在事件驱动仿真器中活动节点极多，是多线程仿真器的理想优化目标。Verilator等编译型仿真器对此类设计已有数量级加速优势。

2. **C-simulation与RTL协同验证**：Vitis HLS等工具的C-simulation比RTL仿真快数个数量级，但co-simulation仍是最终验证手段。RTL仿真器若能在co-simulation接口（如VPI/DPI-C）上降低Python/C++回调开销，将显著加速HLS验证流程。

3. **开源HLS工具链的仿真集成**：Bambu与Verilator/Yosys的集成经验表明，开源RTL仿真器作为开源HLS后端是必然趋势。Verilator的UVM支持进展（如PlanV项目）将直接受益于开源HLS生态的扩张。

4. **多线程调度与HLS流水线的契合**：HLS生成的流水线RTL通常具有规则的节拍结构，RTL仿真器可采用静态调度或时间片调度（而非全局事件队列），实现更高效的线程并行。Verilator的 `--threads` 模式已在此方向取得进展。

5. **LLVM IR作为通用桥梁**：LegUp和Bambu均基于LLVM IR，而CIRCT/MLIR正在构建统一的硬件编译中间层。RTL仿真器若能直接消费LLVM IR或MLIR（而非仅Verilog），将打通从高级算法到高效仿真的全链路，这是长期演进方向。

## 原文摘录

> "High-level synthesis is a process that translates code in high-level programming languages into RTL descriptions suitable for FPGA implementation. It connects the software and hardware design, allowing developers to focus on algorithmic aspects rather than low-level hardware details." — Codilime HLS Blog (2024)

> "LegUp targets a hybrid processor–accelerator architecture. In this model, a soft-core processor executes the software portions, while computationally intensive functions are automatically synthesized into custom hardware accelerators." — From RTL to Fabrication (2026)

> "Bambu offers a command-line interface and is particularly useful for designers seeking assistance in HLS and optimizing hardware designs efficiently. It can generate optimized VHDL or Verilog code for various FPGA and ASIC targets." — DL Accelerator Survey (2023)

> "HLS allows generating accelerators for different platforms without altering the C/C++ source code apart from a few design directives. This makes it possible to explore the design space much faster than with HDL design." — DL Accelerator Survey (2023)

> "Vitis HLS C code is geared towards taking advantage of the benefits and characteristics offered by the architecture of AMD adaptive SoCs and FPGAs." — AMD Vitis HLS Official (2026)

## 相关链接

- [AMD Vitis HLS 官方](https://www.amd.com/en/products/software/adaptive-socs-and-fpgas/vitis/vitis-hls.html)
- [Vitis HLS User Guide (UG1399)](https://www.xilinx.com/support/documents/sw_manuals/xilinx2022_2/ug1399-vitis-hls.pdf)
- [PandA-Bambu GitHub](https://github.com/ferrandi/PandA-bambu)
- [Bambu DAC 2021 Paper](https://doi.org/10.1109/DAC18074.2021.9586110)
- [LegUp Computing (被Microchip收购)](https://www.microchip.com/en-us/products/fpgas-and-plds/fpga-and-soc-design-tools/smarthls)
- [Siemens Catapult HLS](https://eda.sw.siemens.com/en-US/ic/catapult-high-level-synthesis/)
- [Cadence Stratus HLS](https://www.cadence.com/en_US/home/tools/system-design-and-verification/high-level-synthesis-and-verification.html)
- [SODA Synthesizer (Python→GDSII)](https://github.com/pnnl/soda-opt)
- [ScaleHLS (MLIR-based)](https://github.com/hanchenye/scalehls)
- [hls4ml Bambu Backend (CERN)](https://indico.cern.ch/event/1549296/)

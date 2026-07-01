---
title: "ChiselSim / Chisel + FIRRTL 生态与 RTL 仿真"
description: "Chisel 硬件构造语言及其 FIRRTL 中间表示的仿真生态概述，涵盖 ChiselSim、Treadle、Verilator 后端、GEM GPU 加速提案及 CFC 协同仿真框架"
source_url: "https://github.com/chipsalliance/chisel"
source_type: "github-repo"
author: "Chips Alliance / UC Berkeley / 社区贡献者"
date: "2012-2015 起源，持续活跃"
tags: ["chisel", "firrtl", "chiselsim", "treadle", "verilator", "gem", "gpu-simulation", "co-simulation", "scala"]
keywords: ["Chisel", "FIRRTL", "ChiselSim", "Treadle", "RTL simulation", "Verilator backend", "GEM GPU", "CFC", "ChiselTest", "CIRCT", "firtool"]
capture_date: "2025-06-30"
---

# ChiselSim / Chisel + FIRRTL 生态与 RTL 仿真

## 来源

- URL: https://github.com/chipsalliance/chisel
- 类型: GitHub 开源组织仓库 + 官方文档 + 学术论文 / 学位论文
- 作者: Jonathan Bachrach, Adam Izraelevitz, Jack Koenig, Schuyler Eldridge 等（Chisel 核心团队）；UC Berkeley ADEPT / Chips Alliance 社区
- 日期: Chisel 2012 年首发，FIRRTL 2016 年规范，CIRCT/firtool 近年持续迭代
- 主要参考:
  - Chisel 官方文档: *Testing* — ChiselSim 与 FileCheck
  - GitHub Discussion: *Integrate NVIDIA GEM for 5-40x Faster RTL Simulation in ChiselSim* (#5142)
  - Ryan Lund 硕士论文: *Design and Application of a Co-Simulation Framework for Chisel* (UC Berkeley, 2021)
  - Jonathan Bruant 博士论文（法）: Chisel/FIRRTL 翻译性能对比
  - MemorySim (2025): Chisel/Chipyard 生态中的 RTL 级内存仿真器

## 摘要

Chisel（Constructing Hardware in a Scala Embedded Language）是由 UC Berkeley 开发的硬件构造语言，以 Scala 为宿主语言，通过参数化元编程生成 RTL。其编译产物为 **FIRRTL**（Flexible Intermediate Representation for RTL）——一种带规范的中级表示，可被转换为 Verilog、SystemVerilog、C++ 仿真模型或 FPGA 比特流。围绕 Chisel/FIRRTL 的仿真生态形成了三层架构：**解释层（Treadle）**、**编译层（Verilator/VCS via ChiselSim）**、**硬件加速层（FireSim/GEM）**。近年来，社区还提出了 GPU 加速后端（NVIDIA GEM）与协同仿真框架（CFC）等高性能方向。

## 关键要点

### 1. Chisel → FIRRTL → 下游工具链

- **Chisel**（`chipsalliance/chisel`，4700+ stars）: Scala 嵌入式 DSL，支持面向对象的模块继承、参数化、函数式硬件生成。最新版本基于 CIRCT 编译器（LLVM 子项目），`firtool` 将 FIRRTL 编译为 SystemVerilog。
- **FIRRTL**: 文本化的中间表示，支持多种变换（transform）：常量传播、死代码消除、模块内联、时钟域转换等。ESSENT、cxxrtl（经 Yosys FIRRTL 前端）等仿真器均以 FIRRTL 为输入。
- **CIRCT / firtool**: 新一代 LLVM 风格的 FIRRTL 编译器，替代旧版 Scala FIRRTL 编译器，生成更优化的 SystemVerilog，并改善编译速度。

### 2. ChiselSim — 官方仿真测试框架

- **定位**: Chisel 3.5+ 推出的标准仿真库，用于在 ScalaTest 中驱动 Chisel 生成的 SystemVerilog 仿真。
- **后端**: 默认使用 **Verilator**（开源）或 **VCS**（商业）。通过 `Simulator` CLI 选项可在测试时切换后端。
- **API**:
  - `simulate` / `simulateRaw`: 对 `Module`（含时钟/复位）或 `RawModule`（无默认时钟）运行仿真。
  - Peek/Poke/Expect: `foo.a.poke(1)`, `foo.c.expect(3)`, `foo.clock.step(1)` 等直观的端口激励 API。
  - 可复用刺激模式: `ResetProcedure`, `RunUntilFinished`, `RunUntilSuccess`。
  - VCD 波形: `-DemitVcd=1` 命令行选项直接生成波形。
- **ScalaTest 集成**: 自动按 test suite / scope 生成目录结构（`build/chiselsim/`），支持 `ConfigMap` 传参。

### 3. Treadle — 解释型 FIRRTL 仿真器（已归档）

- **仓库**: `chipsalliance/treadle`（157 stars，已 archived）。
- **定位**: 纯 Scala/JVM 实现的解释型 FIRRTL 执行引擎，无需 C++ 编译，启动极快，适合单元测试与快速调试。
- **性能**: 远低于 Verilator/ESSENT，仅用于小模块或 CI 快速冒烟测试。ESSENT 的 Java 后端（WOSET 2022）可视为其精神续作——在保持快速启动的同时，通过 JIT 提升吞吐量。

### 4. 性能对比与生态瓶颈

- **ChiselTest 二进制缓存**: 2021 年 Chisel 版本引入 Verilator 仿真二进制缓存，对重复测试同一 DUT 的用例可显著减少编译等待。Ryan Lund 的 CFC 论文指出，该优化使 Gemmini 的 matmul 测试在缓存命中时平均加速 **9.72×**（4×4 配置）与 **9.53×**（16×16 配置）。
- **Chisel 栈 vs. 原生 SystemVerilog**: Jonathan Bruant 的论文显示，在 Tree filters 架构上，Chisel/FIRRTL 栈的完整生成+仿真流程总耗时约 **29.5 分钟**，对比原生 SV 仅 **1 分钟**（ overhead 主要来自 FIRRTL 编译与 Verilator C++ 编译）。仿真速度本身从 916 ns/s 降至 300 ns/s，下降约 67%。
- **启示**: Chisel 生态的优势在于**生成能力**与**验证基础设施**，而非纯仿真速度。高性能 RTL 仿真器若面向 Chisel 用户，应尽量减少 FIRRTL→Verilog→C++ 的转换层级，或直接从 FIRRTL 生成仿真代码（如 ESSENT 路径）。

### 5. GEM GPU 加速提案（2026-01）

- **来源**: chipsalliance/chisel GitHub Discussion #5142
- **核心内容**: 社区提议将 NVIDIA 开源的 **GEM（GPU-Accelerated Emulator-Inspired RTL Simulation）**集成为 ChiselSim 的可选后端。GEM 通过 CUDA 加速，宣称比主流 CPU 仿真器快 **5–40×**。
- **GEM 架构**: 虚拟 VLIW 架构，类似 FPGA 仿真器——先将设计综合到门级网表，再映射到虚拟多核布尔处理器上在 GPU 执行。
- **集成挑战**: GEM 需要非交互式 testbench（静态 VCD 输入），合成/映射有一次性开销；需要 CUDA GPU。提案建议做成可选插件，CPU 后端保留用于调试，GPU 后端用于大规模回归。
- **对多线程仿真的意义**: GPU 的 SIMT 本质上是一种大规模数据并行（stimulus-level parallelism），与 wiki-mt-rtl-optimizer 关注的结构级多线程（structure-level parallelism）形成互补。可研究两者结合：CPU 多线程处理复杂控制逻辑，GPU 批量处理大量向量/矩阵运算或回归测试。

### 6. CFC 协同仿真框架（UC Berkeley, 2021）

- **论文**: *Design and Application of a Co-Simulation Framework for Chisel* (EECS-2021-133)
- **核心思想**: 将 Rocket Chip 的指令级功能模型（Spike）与 Chisel 生成的 RoCC 加速器 RTL 级仿真配对。通过剥离完整 SoC 的冗余 RTL 仿真，仅对加速器做 cycle-accurate 仿真，其余用软件模型替代。
- **成果**: 在 Gemmini 上实现 elaboration 加速 **15.8×**（4×4）与 **19.8×**（16×16）；仿真阶段加速 **6.5×–9.72×**。
- **启示**: **多线程 RTL 仿真器的终极目标不一定是在单仿真内塞满线程，而是合理划分精度边界**，让 cycle-accurate 部分最小化。这对架构设计有直接影响：支持黑盒/外接行为模型是高性能仿真框架的必备能力。

### 7. MemorySim（2025）—— Chisel 生态中的 RTL 级内存仿真

- **论文**: *MemorySim: An RTL-level, timing accurate simulator model for the Chisel ecosystem* (arXiv:2508.12636)
- **简介**: 在 Chisel/Chipyard 中实现了一个 RTL 级 DRAM 时序仿真器，直接嵌入硬件生成流程，可与 FireSim 等下游工具链联动。展示了 Chisel 生态在**全栈仿真**（从 ISA 到 DRAM 时序）上的扩展能力。

## 对 RTL 仿真器多线程化的启示

1. **FIRRTL 是多线程仿真器的理想输入 IR**: 相比解析 Verilog，FIRRTL 结构清晰、语义明确，自带类型信息与模块层次，便于自动划分并行分区。ESSENT 已证明 FIRRTL→C++ 仿真器的开发效率极高。
2. **ChiselSim 的 Verilator 后端暴露了多线程仿真的需求**: Chisel 用户习惯在 Scala 里写测试，但底层编译到 Verilator 的 C++ 模型。若 wiki-mt-rtl-optimizer 能提供一种**直接从 FIRRTL 生成多线程 C++ 仿真器**的方案，可绕过 Verilator 的单线程限制，同时保留 ChiselSim 的 API 兼容性。
3. **GPU（GEM）与 CPU 多线程的混合架构值得探索**: 对于大规模回归或数据密集型模块（如 Gemmini、SHA3 加速核），GPU 的批量并行有巨大优势；而 CPU 多线程更适合复杂分支、低延迟交互式调试。一个灵活的后端应允许用户在运行时选择设备。
4. **编译缓存与增量编译是用户体验的关键**: CFC 与 ChiselTest 的缓存机制显示，即使仿真速度提升，若编译时间不可接受，用户仍会感到瓶颈。多线程 RTL 仿真器应设计**可缓存的编译产物**与**增量分区重编译**机制。

## 原文摘录

> "The primary testing strategy is simulation. This is done using ChiselSim, a library for simulating Chisel-generated SystemVerilog on different simulators."
> — Chisel 官方 Testing 文档

> "I propose adding GEM (GPU-Accelerated Emulator-Inspired RTL Simulation) as an optional simulation backend for ChiselSim, enabling GPU-accelerated RTL simulation with 5-40x speedup over CPU-based simulators."
> — GitHub Discussion #5142, 2026-01-09

> "With ChiselTest binary caching enabled, CFC was able to execute the matmul test binary an average of 9.72x faster than a full-SoC simulation for a 4x4 Gemmini and 9.53x faster for a 16x16 Gemmini configuration."
> — Ryan Lund, UC Berkeley EECS-2021-133

> "Currently there is a dire limitation in register-transfer level (RTL) memory subsystem models with support for obtaining profiling data... We introduce MemorySim, a RTL-level memory simulator that strives to provide accurate timing simulations of memory systems while retaining correctness."
> — MemorySim, arXiv:2508.12636v1

> "Chisel provides several packages for testing generators with different strategies... Both ChiselSim and FileCheck are provided as packages inside Chisel."
> — Chisel 官方文档

## 相关链接

- [Chisel 官方仓库](https://github.com/chipsalliance/chisel) — 4700+ stars，活跃维护
- [Chisel 官方文档 — Testing](https://www.chisel-lang.org/docs/explanations/testing)
- [Treadle 解释型 FIRRTL 执行引擎](https://github.com/chipsalliance/treadle) — 已归档，157 stars
- [CIRCT / firtool](https://github.com/llvm/circt)
- [ChiselSim GEM GPU 加速提案 Discussion](https://github.com/chipsalliance/chisel/discussions/5142)
- [NVIDIA GEM 仓库](https://github.com/NVlabs/GEM)
- [GEM 论文](https://research.nvidia.com/publication/2025-06_gem-gpu-accelerated-emulator-inspired-rtl-simulation)
- [CFC 协同仿真框架论文 (PDF)](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2021/EECS-2021-133.pdf)
- [MemorySim 论文 (arXiv)](https://arxiv.org/html/2508.12636v1)
- [Chisel/FIRRTL 翻译性能论文 (Bruant)](https://theses.hal.science/tel-04019979/file/BRUANT_2022_archivage.pdf)
- [Chips Alliance 2021 秋季 Workshop 幻灯片](https://www.chipsalliance.org/news/recap-of-the-fall-2021-chips-alliance-workshop-rob-mains-chips-alliance/)

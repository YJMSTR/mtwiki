---
title: "GitHub 上最新的 RTL 仿真器项目"
description: "汇总 GitHub 上与多线程、并行、GPU 加速 RTL 仿真相关的活跃开源项目，包括传统编译型仿真器、新兴 Rust 实现、GPU 后端及工业框架。"
source_url: "https://github.com/search?q=RTL+simulator&type=repositories"
source_type: "github-repo"
author: "多个开源社区"
date: "2026-07-01"
tags: [RTL-simulator, open-source, GitHub, Verilator, GPU, Rust, multithreading]
keywords: [verilator, gsim, gem, jacquard, lyra, cxxrtl, rohd, multisim]
capture_date: "2026-07-01"
---

# GitHub 上最新的 RTL 仿真器项目

## 来源

- URL: GitHub 搜索
- 类型: github-repo
- 作者: 多个开源社区
- 日期: 2023–2026

---

## 摘要

本文档梳理了 GitHub 上 2023–2026 年间与 RTL 仿真器相关的活跃开源项目，覆盖传统编译型仿真器（Verilator）、学术原型（GSIM、GEM、Jacquard）、现代 Rust 实现（vitamin-rtl-simulator、maria）、工业框架（Intel ROHD）以及多线程/分布式方案（Multisim）。这些项目代表了 RTL 仿真器从单线程 C++ 到 GPU 加速、从 Verilog 单一前端到多语言多后端的技术演进。

---

## 关键要点

### 1. Verilator —— 最广泛使用的开源 SystemVerilog 仿真器

- **仓库**: [verilator/verilator](https://github.com/verilator/verilator)
- **Stars**: 3,708 | **Language**: C++ / SystemVerilog
- **核心能力**: 将 Verilog/SystemVerilog 编译为 C++/SystemC 可执行文件，支持 lint。
- **多线程支持**: 自 Verilator 4.0 起支持多线程（`--threads`），通过将 RTL 设计划分为多个分区实现并行。但论文（GSIM、GEM）反复指出，Verilator 多线程在 8 线程以上常出现性能退化（16 线程仅达 8 线程的 80–95%），同步开销是主要瓶颈。
- **与项目关联**: 本项目的基础基准，几乎所有新仿真器都以其为比较对象。

### 2. OpenXiangShan/GSIM —— 香山团队的新型 RTL 仿真器

- **仓库**: [OpenXiangShan/gsim](https://github.com/OpenXiangShan/gsim)
- **核心能力**: 接受 Chisel FIRRTL 输入，编译为 C++。实现超节点/节点/比特三级优化，是目前唯一能正确仿真 XiangShan 处理器的开源仿真器。
- **多线程现状**: 当前版本（截至 2025 DAC 论文）主要聚焦**单线程极致优化**，但论文明确指出 RepCut 等多线程方案与其正交，可作为未来工作方向。
- **值得关注的代码结构**: `build/gsim` 为编译器前端，`ready-to-run/` 提供 Rocket、BOOM、XiangShan 的 FIRRTL 测试用例，`--dump` 系列选项支持多阶段 DOT/JSON 图 dump，便于调试划分算法。

### 3. NVlabs/GEM —— NVIDIA 的 GPU 加速 RTL 仿真器

- **仓库**: [NVlabs/GEM](https://github.com/NVlabs/GEM)
- **核心能力**: 将 RTL 综合为门级网表后，映射为虚拟 VLIW 布尔处理器指令流，通过 CUDA 解释执行。
- **技术亮点**:
  - 用 Rust 实现映射流程，CUDA 实现解释器内核；
  - Boomerang 折叠将逻辑级数压缩 6–8 倍；
  - 162.4 MB bitstream 承载 500 万门设计。
- **与社区互动**: 2026 年 1 月，Chisel 社区（chipsalliance/chisel）已发起 [Discussion #5142](https://github.com/chipsalliance/chisel/discussions/5142) 探讨将 GEM 集成到 ChiselSim 作为可选后端，目标实现 5–40× 加速。

### 4. gpu-eda/Jacquard —— GPU 加速 RTL 逻辑仿真器（Metal/CUDA/HIP）

- **仓库**: [gpu-eda/Jacquard](https://github.com/gpu-eda/Jacquard)
- **Stars**: 66 | **Language**: Verilog / C++ / Metal
- **Created**: 2026-01-05
- **核心能力**: 开源 RTL 逻辑仿真器，支持多 GPU 后端：Apple Metal、NVIDIA CUDA、AMD HIP。
- **状态**: 非常新的项目（2026 年初创建），issue 25 个，说明处于活跃开发期。目标是在 macOS/Apple Silicon 上也能运行 GPU 加速 RTL 仿真。
- **与项目关联**: 如果我们的多线程 RTL 优化器未来要支持 GPU 后端，Jacquard 的多后端抽象值得参考。

### 5. TAC-UCB/RTeAAL-Sim —— 张量代数 RTL 仿真原型

- **仓库**: [TAC-UCB/RTeAAL-Sim](https://github.com/TAC-UCB/RTeAAL-Sim)
- **核心能力**: 将 RTL 数据流图表示为稀疏张量，仿真执行为扩展 Einsum 级联。基于 FIRRTL 输入，生成 C++ 仿真核。
- **技术亮点**: 概念验证级实现，展示张量代数优化（loop unrolling、format compression、operator fusion）在 RTL 仿真中的可行性。
- **与项目关联**: 如果未来考虑引入更高级的编译器优化框架，RTeAAL Sim 的 TeAAL 集成路径提供了参考。

### 6. hankhsu1996/lyra —— 现代 SystemVerilog 仿真工具链

- **仓库**: [hankhsu1996/lyra](https://github.com/hankhsu1996/lyra)
- **Stars**: 4 | **Language**: C++
- **Created**: 2025-04-22
- **核心能力**: 多阶段 IR 流水线（multi-stage IR pipeline）+ 多后端 SystemVerilog 仿真工具链。
- **与项目关联**: 多阶段 IR 的设计可能适合作为多线程优化的中间表示层，可以观察其 IR 分层是否有助于线程划分。

### 7. intel/rohd —— Intel 的 Dart 硬件开发框架

- **仓库**: [intel/rohd](https://github.com/intel/rohd)
- **Stars**: 483 | **Language**: Dart
- **核心能力**: 用 Dart 语言描述和验证硬件，提供仿真器 backend。虽然前端语言不是 Verilog，但其框架级别的验证基础设施和仿真器抽象设计对理解工业级需求有帮助。
- **与项目关联**: 工业界对仿真器的需求不仅限于性能，还包括调试能力、覆盖率、断言等。ROHD 的验证生态可作为功能需求的参考。

### 8. antoinemadec/multisim —— 分布式多实例 RTL 仿真

- **仓库**: [antoinemadec/multisim](https://github.com/antoinemadec/multisim)
- **核心能力**: 通过 TCP/IP 通道将一个大 DUT 拆分为多个独立仿真进程（Server + N Clients），各进程可使用不同仿真器（Verilator、VCS、Questa、Xcelium）。
- **技术特点**: SV/DPI 接口、Ready/Valid 协议、支持 AXI 等多通道抽象。以**牺牲周期精确性**换取可扩展性。
- **与项目关联**: 如果我们的优化器未来需要支持**跨进程/跨机器**的粗粒度并行，Multisim 的通道通信模型是现成的参考。

### 9. 新兴 Rust 实现

- **vitamin-rtl-simulator** ([tjddnr0912/vitamin-rtl-simulator](https://github.com/tjddnr0912/vitamin-rtl-simulator))
  - 纯 Rust 实现，无 C 依赖，SystemVerilog/Verilog → VCD。
  - 2026-06-29 创建，处于极早期。
- **maria** ([Yoriyoi-drop/maria](https://github.com/Yoriyoi-drop/maria))
  - Rust 构建的 SystemVerilog RTL 仿真器，Pipeline: lexer → parser → AST → IR → engine → VCD。
  - 2026-06-19 创建，同样处于早期阶段。
- **与项目关联**: Rust 的内存安全性和零成本抽象吸引硬件开发者，但目前功能远不及 Verilator。可跟踪其进展，但暂不列为直接竞品。

### 10. Yosys/CXXRTL 生态

- **sc-cxxrtl** ([lanserge/sc-cxxrtl](https://github.com/lanserge/sc-cxxrtl)) —— 基于 CXXRTL 的 cocotb 仿真器，用于 SiliconCompiler。
- **cxxrtl-vpi** ([lanserge/cxxrtl-vpi](https://github.com/lanserge/cxxrtl-vpi)) —— 为 CXXRTL 提供 IEEE-1364 VPI 接口，使 cocotb 可以驱动 CXXRTL 模型。
- **与项目关联**: CXXRTL 是 Yosys 的 C++ 仿真后端，以速度快著称。其 VPI 接口和 cocotb 集成模式展示了工业验证流程中对仿真器接口的需求。

---

## 对 RTL 仿真器多线程化的启示

1. **Verilator 仍是事实基准，但多线程天花板明显**: 几乎所有新项目都以 Verilator 为基准，但 8+ 线程的退化现象说明：单纯在 Verilator 上打补丁难以突破，需要重新思考调度与同步模型。
2. **GPU 后端需要全新架构，而非移植**: GEM 和 Jacquard 证明，RTL 直接转 CUDA 会遇到 SIMT 不兼容问题。虚拟 VLIW 或多后端抽象（Metal/CUDA/HIP）是可行路线。
3. **Rust 生态萌芽但尚未成熟**: 2026 年出现了多个 Rust RTL 仿真器，但均处于早期。如果追求极致性能，C++ 仍是主战场；如果追求安全性和可维护性，Rust 可作为长期跟踪方向。
4. **分布式/跨进程并行是另一条路**: Multisim 不解决单仿真器内部多线程，而是将问题上抛到系统架构层。对于超大规模 SoC，粗粒度 + 细粒度并行混合可能是最终答案。
5. **IR 中间层成为竞争焦点**: Lyra 的多阶段 IR、RTeAAL Sim 的张量 IR、GSIM 的 FIRRTL 前端都说明，RTL 仿真器正在从“Verilog 编译器”进化为“领域特定编译器”。多线程优化应发生在 IR 层级，而非 AST 层级。

---

## 原文摘录

> "Verilator: Open-source systemverilog simulator... 3,708 stars, 841 forks"
> —— GitHub, verilator/verilator

> "GEM is an open-source RTL logic simulator developed by NVIDIA Research that leverages CUDA acceleration to dramatically speed up RTL simulation."
> —— chipsalliance/chisel Discussion #5142

> "Open-source RTL logic simulator with GPU acceleration (Metal, CUDA, HIP/AMD)"
> —— gpu-eda/Jacquard

> "An open-source RTL simulator in pure Rust — simulates synthesizable SystemVerilog/Verilog to VCD, source-build with no C dependencies."
> —— vitamin-rtl-simulator

> "Multiple simulations running in parallel... Server & Client communicate through channels (TCP/IP)"
> —— Multisim README

---

## 相关链接

- [Verilator](https://github.com/verilator/verilator)
- [GSIM](https://github.com/OpenXiangShan/gsim)
- [GEM](https://github.com/NVlabs/GEM)
- [Jacquard](https://github.com/gpu-eda/Jacquard)
- [RTeAAL-Sim](https://github.com/TAC-UCB/RTeAAL-Sim)
- [Lyra](https://github.com/hankhsu1996/lyra)
- [Intel ROHD](https://github.com/intel/rohd)
- [Multisim](https://github.com/antoinemadec/multisim)
- [vitamin-rtl-simulator](https://github.com/tjddnr0912/vitamin-rtl-simulator)
- [maria](https://github.com/Yoriyoi-drop/maria)
- [sc-cxxrtl](https://github.com/lanserge/sc-cxxrtl)
- [cxxrtl-vpi](https://github.com/lanserge/cxxrtl-vpi)

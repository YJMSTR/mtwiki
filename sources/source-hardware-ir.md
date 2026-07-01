---
title: Hardware IR 生态：FIRRTL、LLHD、HIR 与 KIR 格式对比
description: 搜集数字电路设计领域中除 MLIR/CIRCT 之外的主流硬件 IR（FIRRTL、LLHD、HIR、KIR 等），分析其抽象层次、类型系统与在 RTL 仿真/综合流程中的定位。
source_url: "https://arxiv.org/abs/2004.03494"
source_type: "paper"
author: "Fabian Schuiki, Adam Izraelevitz, Kingshuk Majumder 等"
date: "2020-2024"
tags: ["FIRRTL", "LLHD", "HIR", "KIR", "hardware-IR", "CIRCT", "MLIR"]
keywords: ["FIRRTL", "LLHD", "hardware intermediate representation", "RTL IR comparison", "multi-level IR"]
capture_date: "2026-07-02"
---

# 硬件 IR 生态：FIRRTL、LLHD、HIR 与 KIR 格式对比

## 来源

- URL: 多篇论文与开源项目资料汇总，核心来源如下：
  - FIRRTL: [Reusability is FIRRTL Ground (ICCAD 2017)](http://albert-magyar.github.io/documents/firrtl-iccad17.pdf) / [DeepWiki FIRRTL Dialect](https://deepwiki.com/llvm/circt/2-firrtl-dialect-system)
  - LLHD: [LLHD: A Multi-level IR for HDLs (PLDI 2020)](https://dl.acm.org/doi/10.1145/3385412.3386024)
  - HIR: [HIR: An MLIR-based IR for Hardware Accelerator (ASPLOS 2021)](https://arxiv.org/abs/2103.00194)
  - KIR: [AIWareK: Compiling PyTorch for AI Processor (IEEE 2022)](https://ieeexplore.ieee.org/abstract/document/9869913/)
- 类型: paper / doc / github
- 作者: Fabian Schuiki (ETH Zurich), Adam Izraelevitz (UC Berkeley), Kingshuk Majumder (UIUC) 等
- 日期: 2017–2024

## 摘要

现代硬件设计流程中，SystemVerilog/VHDL 等源语言过于复杂，各 EDA 工具往往将其降维到私有的中间表示（IR）再进行处理，导致 IR 碎片化、冗余且互不兼容。社区因此提出多种**专用硬件 IR**，试图在「保留用户意图」与「面向下游工具」之间取得平衡。其中最具代表性的包括：

- **FIRRTL**：UC Berkeley 为 Chisel 生态设计的 RTL 级 IR，以 AST 为核心，提供高/中/低三级形式，现已成为 CIRCT 的 FIRRTL dialect；
- **LLHD**：ETH Zurich 提出的多层级 IR（行为级/结构级/网表级），基于 SSA，支持 SystemVerilog 语义完整降维，并自带 LLVM-JIT 仿真器；
- **HIR**：面向硬件加速器的高层 IR，以 MLIR dialect 实现，用显式调度（schedule）替代传统 datapath+FSM，适合 HLS 前端；
- **KIR（Kernel IR）**：AIWareK 编译器中的算子级 IR，用于将深度学习模型中的 kernel 进一步下译到处理器后端指令。

这些 IR 在抽象层次、类型系统和控制流表达上各有侧重，共同构成了除纯 MLIR/CIRCT 之外丰富的硬件 IR 图谱。

## 关键要点

- **FIRRTL 的「三阶降维」**：FIRRTL 通过 high form → middle form → low form 的渐进式 lowering，在每一阶段保留更少的语言特性，但允许转换 pass 灵活地指定其输入/输出 form。这种设计让前端（Chisel）可以保留高阶意图（如 memory、aggregate、clock type），而后端（Verilog 生成）只需处理低阶子集。
- **LLHD 的 SSA 与多层级设计**：LLHD 采用类 LLVM 的 SSA 形式，引入时间类型 `time`、信号类型 `T$`、九值逻辑 `lN` 等硬件专用类型。它的三级 IR（Behavioural / Structural / Netlist）分别对应仿真、综合与网表阶段，其中行为级 IR 自带 `wait` 指令，可精确描述时序控制。
- **LLHD 的仿真性能**：据 PLDI 2020 论文，LLHD 参考编译器自带的仿真器（后升级为 LLVM-JIT 版本）可比商业仿真器快 **2.4 倍**，同时保持 cycle-accurate 结果。这一结果直接证明了「以统一 IR 做硬件仿真」的可行性。
- **HIR 的 schedule 抽象**：HIR 用 **datapath + schedule** 替代传统 HLS 的 datapath + FSM，允许程序员显式描述循环流水、重定时（retiming）和细粒度无同步并行。其作为 MLIR dialect，可直接复用 MLIR 的 pass 基础设施。
- **KIR 在 AI 编译器中的角色**：AIWareK 将 PyTorch 模型 trace 为 Graph IR (GIR) 后，再 lower 为 Kernel IR (KIR) 和 Processor IR (PIR)。KIR 位于算子层面，负责将深度学习中的高维张量操作映射到目标 AI 处理器的 ISA，体现了「硬件 IR」在 AI 加速器领域的新延伸。
- **IR 对比总结**：FIRRTL 与 LLHD 都是低层级 IR，更接近 RTL；HIR 属于高层 IR，面向 HLS 与加速器；KIR 则进一步下沉到 AI 处理器后端。四者在「用户意图保留度」与「综合/仿真友好度」之间形成连续谱。

## 对 RTL 仿真器多线程化的启示

- **统一 IR 是并行化的前提**：LLHD 的实验表明，先将 SystemVerilog 完整降维到统一 IR，再基于 IR 做仿真，可以消除传统 event-driven 仿真中「各工具语义不一致」的障碍。若要在 RTL 仿真器中引入多线程，一个清晰、无歧义的 IR（如 LLHD 的行为级 SSA）是分割任务、消除竞态的基础。
- **SSA 天然适合数据流并行**：LLHD 与 XLS IR 都指出，硬件的「处处并行」本质与软件 CFG 的「串行假设」存在张力。SSA / dataflow 形式的 IR 更贴近硬件信号传播模型，可作为多线程调度中「识别无依赖节点并行执行」的静态分析输入。
- **三级降维策略可借鉴**：FIRRTL 的 high/middle/low form 策略提示，RTL 仿真器也可以维护多级 IR——在高层保留模块边界与接口语义，在低层展开为纯组合/时序网络，以便针对不同并行粒度（模块级 vs 节点级）选择不同执行策略。
- **HIR 的 schedule 思想**：对于需要 cycle-accurate 的多线程仿真，显式 schedule 比隐式 FSM 更容易分析「哪些 cycle 可以并行推进」。如果 RTL 仿真器能在 IR 层面对时钟域、复位域进行显式标注，可大幅降低跨线程同步开销。

## 原文摘录

> "Modern Hardware Description Languages (HDLs) such as SystemVerilog or VHDL are, due to their sheer complexity, insufficient to transport designs through modern circuit design flows. Instead, each design automation tool lowers HDLs to its own Intermediate Representation (IR)."
> —— LLHD Paper (PLDI 2020)

> "FIRRTL first prioritizes richness to capture as much source RTL user intent as possible... FIRRTL is also simple. Finally, FIRRTL is clear because it is rigorously defined and has straightforward width inference and type inference rules."
> —— Reusability is FIRRTL Ground (ICCAD 2017)

> "LLHD is designed as simple, unambiguous reference description of a digital circuit, yet fully captures existing HDLs."
> —— LLHD Paper Abstract

> "HIR replaces the traditional datapath + FSM representation of hardware with datapath + schedules."
> —— HIR Paper (ASPLOS 2021)

## 相关链接

- [FIRRTL Dialect System | DeepWiki](https://deepwiki.com/llvm/circt/2-firrtl-dialect-system)
- [LLHD Paper (arXiv)](https://arxiv.org/abs/2004.03494)
- [HIR Paper (arXiv)](https://arxiv.org/abs/2103.00194)
- [AIWareK Paper (IEEE Xplore)](https://ieeexplore.ieee.org/abstract/document/9869913/)
- [CIRCT: Circuit IR Compilers and Tools](https://github.com/llvm/circt)

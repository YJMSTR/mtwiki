---
title: IR 优化与 RTL 仿真：SSA、数据流与流水线优化的编译器技术
description: 搜集编译器 IR 优化技术（SSA 形式、数据流 IR、流水线优化）在硬件编译与 RTL 仿真中的前沿应用，重点关注 XLS、PipeRTL、CIRCT-HLS 及 SSA-based 加速器综合。
source_url: "https://google.github.io/xls/ir_overview/"
source_type: "doc"
author: "Google XLS Team, PipeRTL Authors, EPFL Dynamatic/CIRCT-HLS 团队 等"
date: "2020-2026"
tags: ["IR-optimization", "SSA", "dataflow-IR", "PipeRTL", "XLS", "CIRCT-HLS", "RTL-simulation"]
keywords: ["IR optimization RTL", "SSA form hardware", "dataflow IR simulation", "SSA hardware compilation"]
capture_date: "2026-07-02"
---

# IR 优化与 RTL 仿真：SSA、数据流与流水线优化的编译器技术

## 来源

- URL:
  - XLS IR: [XLS IR Overview](https://google.github.io/xls/ir_overview/)
  - PipeRTL: [PipeRTL Paper (arXiv 2605.01836)](https://arxiv.org/html/2605.01836v1)
  - Guac / SSA CGMA: [Guac Paper (arXiv 2402.13513)](https://arxiv.org/abs/2402.13513)
  - CIRCT-HLS / Dynamatic: [Dynamically Scheduled HLS Flow in MLIR (EPFL Thesis)](https://infoscience.epfl.ch/server/api/core/bitstreams/53d40326-975c-4341-9d1c-668ca0784bf8/content)
  - Xronos / SSA for HLS: [Xronos Thesis (EPFL)](https://infoscience.epfl.ch/server/api/core/bitstreams/edb31360-99f0-46d5-93cb-8f7e961ae140/content)
- 类型: doc / paper / thesis
- 作者: Google XLS Team, PipeRTL (ASPLOS 2025), Iulian Brumar (Harvard/Edinburgh), EPFL 等
- 日期: 2020–2026

## 摘要

软件编译器领域成熟的 IR 优化技术——特别是 **SSA（Static Single Assignment）**、**数据流图（Dataflow Graph）** 和 **流水线优化**——正在加速向硬件编译与 RTL 仿真渗透。传统硬件综合（HLS）虽然早已使用 CDFG/DFG，但将现代编译器基础设施（MLIR、LLVM）中的优化 pass 直接应用于 RTL 级 IR，是近年的显著趋势。

本文汇总四项关键工作：

1. **Google XLS IR**：一种面向硬件生成的数据流 IR，全程保持 SSA，但采用 **sea-of-nodes（SoN）** 而非 CFG，因为「硬件处处并行」的本质与 CPU 的串行执行模型截然不同。
2. **PipeRTL**：在 CIRCT/MLIR 上构建的时序感知流水线优化框架，通过引入 `pipe` dialect 和带权图（wGraph），在 IR 层面做全局寄存器重定位，平均减少寄存器数量 **19.8%**、数据容量 **12.6%**。
3. **Guac / SSA-based CGMA**：利用 LLVM-IR 的 SSA 形式进行粗粒度函数合并（CGFM），再经 HLS 生成加速器，证明 SSA 的 φ-node 在硬件中可被复用为 multiplexer，带来面积、功耗与能耗的显著节省。
4. **CIRCT-HLS / Dynamatic**：通过 Handshake IR（数据流 IR）将 C 代码转换为 RTL，并对比了两种数据流调度策略在 FPGA 资源占用与 clock period 上的差异。

## 关键要点

- **XLS IR 的「SoN + SSA」哲学**：XLS IR 认为，传统编译器为 CPU 开发的 CFG + 基本块抽象是「串行思维的产物」。在硬件中，所有逻辑门同时活跃，因此 XLS 使用 **sea-of-nodes** 表示：每个节点是一个操作，数据依赖即边。SSA 性质在此自然成立，因为 IR 初始即为函数式，无需显式 φ-node 更新。这种表示使得许多优化 pass（如常量传播、死码消除）的实现极为简洁。
- **XLS IR 的端到端统一**：与许多编译器在不同阶段使用不同 IR 不同，XLS 从高级 frontend 到 RTL 级仅使用 **单一 IR 表示**。这最大化了分析与转换组件的复用性，并允许平滑降级（lowering）到 RTL 门级。
- **PipeRTL 的 wGraph 抽象**：PipeRTL 在 CIRCT 核心 dialect（hw/comb/seq）之上引入 `pipe` dialect，将 RTL 中的寄存器重写为 `pipe.delay`，将广播结构抽象为 `pipe.bubble`。整个设计被建模为带权有向图 G(V,E)，边权 `w(e)` 表示寄存器延迟数，`β(e)` 表示数据容量。优化问题被转化为：在保持端到时延的前提下，全局重定位寄存器以最小化寄存器数量与容量。
- **PipeRTL 的时序预测模型**：为避免盲目优化，PipeRTL 使用 **XGBoost** 训练时序预测模型，基于 CIRCT `comb` dialect 的操作延迟数据集。该模型在路径延迟预测上取得了最佳 Kendall's Tau 和 R²，使 IR 级优化能在「知晓后端物理时序」的前提下做决策。
- **PipeRTL 的下游收益**：对比原始 RTL + DC retiming，PipeRTL + retiming 在 7nm ASAP7 工艺下平均改善 timing 2.1%、总动态功耗 6.6%、cell 漏电 5.1%、总面积 5.4%。关键在于，**IR 级优化与后端 retiming 不是竞争关系**，而是为后者提供更优的起始结构。
- **Guac 的 SSA 函数合并**：在 LLVM-IR 层面对相似函数进行粗粒度合并（CGFM），合并后的函数仍保持 SSA 形式。经 HLS 翻译后，φ-node 转化为硬件 multiplexer，函数共享转化为硬件资源共享。相比非 SSA 的合并方案，SSA-based CGFM 在面积、功耗与能耗上均显著更优，能量节省翻倍。
- **CIRCT-HLS 的数据流 IR 仿真**：CIRCT-HLS 和 Dynamatic 均使用 **Handshake IR** 表示数据流。Handshake IR 的每个操作节点带有 valid/ready 信号，天然支持异步数据驱动执行。在 RTL 仿真中，这种 IR 可直接映射到事件驱动或 cycle-based 仿真后端，为「从高级语言到 RTL 仿真」提供了统一的中间层。
- **SSA 在 HLS 中的经典应用**：Xronos 编译器在生成 RTL 前，将过程式 IR 转换为 **pruned SSA**，以最小化局部变量。结果是生成的硬件中更少的 wire 和 register。这体现了软件编译器中的 SSA 优化同样可直接降低硬件资源消耗。

## 对 RTL 仿真器多线程化的启示

- **SSA / Dataflow IR 是并行调度的天然输入**：XLS IR 的 sea-of-nodes 和 Handshake IR 的数据流图都证明，一旦 RTL 被表示为 SSA 或数据流形式，节点间的依赖关系即边，天然构成一张**并行执行图**。多线程仿真器可以基于这张图的拓扑序或动态调度，将无依赖的节点分配到不同线程，而无需担心传统 event-driven 仿真中的竞争冒险。
- **IR 级优化可为仿真器提供更轻量的设计**：PipeRTL 的寄存器减少和 Guac 的函数合并都说明，在 IR 阶段做优化可以显著减少最终 RTL 的硬件资源。对于仿真器而言，这意味着更少的信号节点、更简化的赋值关系，从而降低仿真器的内存占用和计算量，间接提升多线程扩展性。
- **时序预测模型可用于仿真加速**：PipeRTL 的 XGBoost 时序预测模型虽用于综合，但同样思路可迁移到仿真：若仿真器能在 IR 层面预测「哪些组合路径是长延迟关键路径」，可以优先调度这些路径上的节点，或预先缓存其计算结果，减少线程间的同步等待。
- **数据流 IR 的 valid/ready 语义适合 MIMD 线程模型**：Handshake IR 的 valid/ready 握手协议与数据令牌传递，本质上是一种**异步数据流执行模型**。这与多线程仿真中的「生产者-消费者」模型高度契合：每个线程可作为一个数据流节点，通过 valid/ready 信号进行跨线程同步，而非全局事件队列。这有望消除传统 event-driven 仿真中全局调度器的瓶颈。
- **Pruned SSA 减少仿真状态**：Xronos 的 pruned SSA 转换减少局部变量，对应到 RTL 仿真中即减少需维护的 signal 状态。状态越少，线程间的共享数据越少，缓存一致性开销越低，越有利于多线程 scale。
- **单一 IR 的端到端优势**：XLS 的「单一 IR 从 frontend 到 RTL」策略提示，RTL 仿真器若也能在编译链中保持统一 IR（如基于 MLIR dialect），则可复用同一套分析 pass（依赖分析、活跃变量分析、调度优化）来指导仿真执行，避免在 Verilog AST、网表、仿真引擎之间反复转换。

## 原文摘录

> "The XLS IR is a dataflow-oriented IR that has the static-single-assignment (SSA) property, but is specialized for generating circuitry... XLS IR is not control-flow graph (CFG) based, as many other compiler infrastructures. The insight is that the CFG abstraction was developed to model serial execution on a CPU. In hardware, however, everything happens at all times and in parallel. A sea-of-nodes (SoN) representation much more closely resembles this reality."
> —— XLS IR Overview

> "PipeRTL achieves an average register-count reduction of 19.84% and a data-capacity reduction of 12.61%... IR-level pipeline optimization does not compete with backend retiming for the same optimization budget. Instead, it provides a better sequential starting point on top of which backend retiming can continue refining the design."
> —— PipeRTL Paper (2025)

> "Coarse-grained function merging (CGFM) at the intermediate representation (IR) level can reuse control and dataflow patterns without dealing with the post-scheduling complexity of mapping operations onto functional units, wires, and registers."
> —— Guac Paper (2024)

> "To minimize the local variables, the Procedure IR form is transformed into a pruned SSA one. Thus, fewer wires and registers in the final RTL generation are needed."
> —— Xronos Thesis (EPFL)

> "HSdbg uses GraphViz .dot files to visualize a Handshake IR dataflow graph. This graph is then modified based on values read from a VCD trace to reflect the underlying state of the RTL simulation."
> —— CIRCT-HLS / Dynamatic Thesis (EPFL)

## 相关链接

- [XLS IR Overview](https://google.github.io/xls/ir_overview/)
- [PipeRTL Paper (arXiv)](https://arxiv.org/html/2605.01836v1)
- [Guac: SSA-based CGMA Paper (arXiv)](https://arxiv.org/abs/2402.13513)
- [CIRCT-HLS / Dynamatic Thesis (EPFL)](https://infoscience.epfl.ch/server/api/core/bitstreams/53d40326-975c-4341-9d1c-668ca0784bf8/content)
- [Xronos Thesis (EPFL)](https://infoscience.epfl.ch/server/api/core/bitstreams/edb31360-99f0-46d5-93cb-8f7e961ae140/content)

---
title: 逻辑综合与工艺映射对 RTL 仿真精度的影响
description: 分析逻辑综合（Logic Synthesis）将 RTL 转化为门级网表的过程，以及技术映射（Technology Mapping）如何引入 RTL 仿真无法捕捉的 X 传播、毛刺和时序失配，探讨 RTL 与门级仿真（GLS）不一致的根因
source_url: "https://www.leadsoc.com/rtl-vs-gate-level-simulation-whats-the-difference/"
source_type: "blog"
author: "LeadSoc / Synopsys / Cliff Cummings / Dan Gisselquist"
date: "2018-2026"
tags: ["logic-synthesis", "technology-mapping", "RTL-simulation", "gate-level-simulation", "synthesis-mismatch", "X-propagation"]
keywords: ["synthesis", "GLS", "SDF back-annotation", "X-optimism", "X-pessimism", "timing mismatch", "incomplete sensitivity list"]
capture_date: "2026-07-02"
---

# 逻辑综合与工艺映射对 RTL 仿真精度的影响

## 来源

- URL: https://www.leadsoc.com/rtl-vs-gate-level-simulation-whats-the-difference/
- 类型: blog
- 作者: LeadSoc / 多位行业专家
- 日期: 2026-04

其他关键来源：
- https://funrtl.wordpress.com/2017/06/26/rtl-coding-styles-that-leads-to-pre-and-post-synthesis-simulation-mismatch/ — RTL Coding Styles Causing Mismatch
- https://www.synopsys.com/glossary/what-is-synthesis.html — Synopsys: What is Synthesis?
- https://zipcpu.com/blog/2018/08/04/sim-mismatch.html — ZipCPU: Reasons why Synthesis might not match Simulation
- https://csg.csail.mit.edu/6.375/6_375_2009_www/papers/cummings-synth-mismatch-snug99.pdf — Cliff Cummings, SNUG 1999
- https://picture.iczhiku.com/resource/eetop/shKDEfluHjEYSBVV.pdf — X-optimism / X-pessimism in SystemVerilog
- https://adaptivesupport.amd.com/s/ — AMD/Xilinx Community: RTL and Gate Simulation Mismatch Case Study

## 摘要

逻辑综合将 RTL 描述（寄存器、运算、数据流）转化为由标准单元（逻辑门、触发器、多路器、缓冲器）构成的门级网表，并在此过程中执行技术映射、逻辑最小化、重定时、资源共享等优化。RTL 仿真运行在零延迟或单位延迟模型下，仅验证功能正确性；而门级仿真（GLS）通过 SDF 反标引入真实门延迟，可检测出综合引入的 X 传播、时序违例、毛刺等 RTL 阶段无法暴露的 bug。综合与仿真之间的差异（synthesis-simulation mismatch）是芯片流片失败的重要原因之一，其根因既包括 RTL 编码风格（如不完整敏感列表、`full_case`/`parallel_case` 指令、X 赋值），也包括综合工具对非综合结构的静默丢弃和延迟优化。

## 关键要点

- **综合五步骤**：解析与展开 → 技术映射 → 优化（面积/功耗/速度）→ 约束处理 → 输出门级网表。约束（时钟周期、时序要求、面积限制）是驱动优化的核心输入。[^1]
- **RTL 仿真局限**：零延迟模型无法检测 setup/hold 违例、毛刺和 X 传播；无法捕捉综合工具对 RTL 的“误读”；CDC（跨时钟域）问题在某些场景下被掩盖。[^2]
- **GLS 的两种模式**：零延迟 GLS（Functional GLS）验证综合功能正确性；SDF 反标 GLS（Timing-Annotated GLS）验证真实时序行为，可检测 setup/hold 违例和毛刺。GLS 比 RTL 仿真慢 10x–100x。[^2]
- **合成-仿真失配五大根因**：(1) 综合解释错误（不完整敏感列表被合成工具补全，但 RTL 仿真行为不同）；(2) X 传播差异（RTL 乐观，GLS 悲观）；(3) 时序违例（RTL 零延迟无法看见）；(4) 毛刺与险象（门延迟差异导致）；(5) DFT/扫描链逻辑在 RTL 中不存在。[^2]
- **编码风格陷阱**：不完整敏感列表、`full_case`/`parallel_case` 指令、赋值顺序错误、在 always 块左侧加 `#delay`、将 `X` 作为 don't-care 赋值，均会导致 RTL 与 GLS 结果不一致。[^3][^4]
- **2-state 仿真 vs 4-state**：SystemVerilog 的 `bit`/`int` 等 2-state 类型可消除 X 传播问题，但会掩盖初始化 bug 和总线竞争。综合工具通常将 X 视为 don't-care，而 RTL 仿真器将 X 视为未知值。[^5]
- **真实案例**：Xilinx Vivado 2018.x 曾存在综合后网表与 RTL 仿真不一致的 bug（CR#1020580），导致寄存器值在门级仿真中错误截断，用户需通过 RTL 代码改写 workaround。[^6]

## 对 RTL 仿真器多线程化的启示

1. **多线程化不能掩盖综合语义差异**：RTL 多线程仿真器加速的是零延迟模型下的功能验证，但综合后网表的延迟行为无法被零延迟模型捕捉。多线程 RTL 仿真应在验证流程中明确标注“功能正确性 ≠ 时序正确性”，避免将 RTL 仿真通过等同于芯片可工作。
2. **X 传播模型是多线程化难点**：RTL 仿真中 4-state（0/1/X/Z）编码的内存占用和运算开销远高于 2-state。多线程调度器处理 X 传播时需保证跨线程事件的一致性，这要求共享的 X 状态更新具备原子性，否则可能引入竞态条件。考虑在多线程模式默认使用 2-state（`bit`/`int`）以提升性能，但在关键初始化路径保留 4-state 断言检查。
3. **利用敏感列表完整性做静态检查**：综合工具会在编译时报告不完整敏感列表，而 RTL 多线程仿真器也可在编译阶段进行类似分析。将“敏感列表完整性”作为多线程编译前端的一个 lint 检查项，可在仿真前就阻断一类常见失配。
4. **线程边界与综合边界对齐**：综合优化通常以模块/层次为边界进行。若多线程 RTL 仿真器按相同模块边界划分线程，不仅可减少跨线程通信，还能在调试时方便地对比“模块级 RTL 仿真结果”与“模块级综合后网表结果”，加速 mismatch 定位。
5. **为 CDC 路径保留特殊处理**：跨时钟域信号在 RTL 零延迟仿真中往往看似正确，但综合后因真实延迟和亚稳态而失败。多线程仿真器可在编译时识别 CDC 路径（通过时钟域标记），在跨线程事件调度中引入随机延迟抖动或亚稳态模型，以更早暴露 CDC 风险。

## 原文摘录

> RTL simulation verifies the behavioral HDL code before synthesis using zero-delay or unit-delay models. Gate level simulation verifies the synthesized gate-level netlist after synthesis, using actual standard cells and optionally real gate delays from an SDF file.
> — LeadSoc, *RTL vs Gate Level Simulation* [^2]

> Synthesis is the process of transforming a high-level hardware description (such as RTL code) into a gate-level representation... Synthesis not only translates code but also optimizes the resulting circuit for key metrics such as power consumption, performance, and silicon area.
> — Synopsys [^1]

> For a combinational always block, the logic inferred is derived from the equations in the block and has nothing to do with the sensitivity list. However, for pre-synthesis simulation, the always block will only be executed when there are changes on variable a. Any changes on variable b that do not coincide with changes on a will not be observed on the output.
> — funRTL, *RTL Coding Styles Mismatch* [^3]

> Adding timing delays to the left side of an assignment... will cause pre-synthesis simulations to differ from post-synthesis simulations... The outputs will not be updated on every input change if changes happen more frequently than every 65 time units.
> — Cliff Cummings, SNUG 1999 [^4]

> 2-state simulation can offer several advantages: eliminates uninitialized register and X propagation problems... On the other hand, there are several hazards to consider when only 2-state values are simulated. First, a functional bug in the RTL or gate-level code might go undetected.
> — SystemVerilog X-optimism / X-pessimism Paper [^5]

> Product Application Engineers from Xilinx were able to reproduce this issue and considered this as BUG. They have filed CR#1020580 and communicated that this will be solved in upcoming Xilinx Vivado 2019.1.
> — AMD/Xilinx Community Forum [^6]

## 相关链接

- [RTL vs Gate Level Simulation — LeadSoc](https://www.leadsoc.com/rtl-vs-gate-level-simulation-whats-the-difference/)
- [RTL Coding Styles Causing Mismatch — funRTL](https://funrtl.wordpress.com/2017/06/26/rtl-coding-styles-that-leads-to-pre-and-post-synthesis-simulation-mismatch/)
- [Synopsys: What is Synthesis?](https://www.synopsys.com/glossary/what-is-synthesis.html)
- [ZipCPU: Why Synthesis Might Not Match Simulation](https://zipcpu.com/blog/2018/08/04/sim-mismatch.html)
- [Cliff Cummings, SNUG 1999: RTL Coding Styles That Yield Simulation and Synthesis Mismatch](https://csg.csail.mit.edu/6.375/6_375_2009_www/papers/cummings-synth-mismatch-snug99.pdf)
- [SystemVerilog X-optimism / X-pessimism Paper](https://picture.iczhiku.com/resource/eetop/shKDEfluHjEYSBVV.pdf)
- [AMD/Xilinx: RTL and Gate Simulation Mismatch](https://adaptivesupport.amd.com/s/question/0D52E00006hpkmaSAA/rtl-and-gate-simulation-mismatchnetlist-generated-with-vivado-2018xx-version?language=zh_CN)

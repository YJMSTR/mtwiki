---
title: SDC 综合约束与 RTL 仿真的关系
description: 搜集 Synopsys Design Constraints (SDC) 在 RTL 阶段的应用方式，以及 create_clock、set_false_path、set_multicycle_path 等核心约束命令对仿真与综合一致性的影响
source_url: "https://www.intel.com/content/www/us/en/docs/programmable/683236/22-3/applying-the-sdc-on-rtl-constraints.html"
source_type: "doc"
author: "Intel / Synopsys / 多位开源社区作者"
date: "2024-2025"
tags: ["SDC", "timing-constraints", "synthesis", "RTL", "multi-cycle-path", "false-path"]
keywords: ["create_clock", "set_false_path", "set_multicycle_path", "SDC-on-RTL", "path-group", "timing-exception"]
capture_date: "2026-07-02"
---

# SDC 综合约束与 RTL 仿真的关系

## 来源

- URL: https://www.intel.com/content/www/us/en/docs/programmable/683236/22-3/applying-the-sdc-on-rtl-constraints.html
- 类型: doc
- 作者: Intel FPGA / Synopsys / 开源社区
- 日期: 2024-2025

其他关键来源：
- https://docs.verilogtorouting.org/en/v9.0.0/vpr/sdc_commands/ — VPR SDC 命令参考
- https://www.intel.com/content/www/us/en/docs/programmable/683243/25-1/using-entity-based-sdc-on-rtl-constraints.html — Intel Entity-Based SDC-on-RTL
- https://www.latticesemi.com/view_document?document_id=54615 — Lattice Radiant Constraints Propagation Engine (CPE)
- https://fpgarelated.com/books/532.php — Sridhar Gangadharan, *Constraining Designs for Synthesis and Timing Analysis* (2013)

## 摘要

SDC（Synopsys Design Constraints）是数字芯片设计流程中贯穿综合、STA、P&R 的时序约束语言。传统上 SDC 在综合之后应用，但现代 FPGA/ASIC 工具（如 Intel Quartus Prime、Lattice Radiant）已支持 **SDC-on-RTL**，即在 RTL  elaboration 阶段就读取约束并作用于层次化网表。`create_clock`、`set_false_path`、`set_multicycle_path` 等核心命令不仅决定了综合工具如何优化网表，也深刻影响 RTL 仿真与门级仿真（GLS）之间的等价性。错误或不完整的约束会导致综合工具做出 RTL 仿真无法预见的优化，从而引发“功能正确但时序爆炸”的隐蔽问题。

## 关键要点

- **SDC-on-RTL 的工作机制**：在 Analysis & Elaboration 阶段读取 SDC 文件，将约束存储到内部网表，并在后续综合、优化、早期 STA 中自动传播和更新。修改约束后必须重新运行 elaboration。[^1]
- **Entity-Based SDC 封装**：允许 IP 作者将 SDC 约束封装在实体层级，防止约束泄漏到全局，通过 entity binding 自动前缀化路径名，使 IP 的时序约束独立于实例化位置。[^2]
- **核心约束命令的语义**：`create_clock` 定义时钟周期与波形；`set_false_path` 切断指定路径的时序分析；`set_multicycle_path` 覆盖单周期关系，允许数据在多周期内传播。这些命令在 RTL 阶段即被解析，决定了后续优化空间。[^3][^4]
- **CPE（Constraints Propagation Engine）**：Lattice Radiant 引入的约束传播引擎，在综合前自动编译多个 SDC/LDC 文件，统一生成 `.ldc` 文件，解决子层级与 IP 约束之间的命名冲突和优先级问题。[^5]
- **约束对面积-功耗-时序的权衡**：通过 path-group 约束可强制综合工具避免“为了让自然快路径变慢以节省面积/功耗”的过度优化，从而平滑 timing wall 现象。[^6]

## 对 RTL 仿真器多线程化的启示

1. **约束即隐式时序模型**：RTL 仿真器通常使用零延迟或单位延迟模型，无法反映 `create_clock` 规定的真实时钟周期。若要在多线程 RTL 仿真中引入“准真实时序”以更早发现 setup/hold 风险，可将 SDC 约束解析为事件调度中的延迟参数——但需警惕这会导致仿真速度显著下降。
2. **false_path / multicycle_path 作为线程切分提示**：被声明为 false_path 或 multicycle_path 的跨时钟/跨周期路径，在逻辑上被允许延迟更大，可作为多线程调度中“放宽同步要求”的启发式依据。反之，未被豁免的严格单周期路径应优先映射到同一线程或相邻线程，避免跨线程同步开销引入伪时序违例。
3. **约束验证应前移到 RTL 阶段**：DVCon 论文指出，在 RTL 回归中通过断言验证 SDC 约束的正确性，比等到门级仿真（GLS）再排错效率更高（3 天 vs 11+ 天）[^7]。多线程 RTL 仿真若能在编译时解析 SDC 并注入轻量级时序断言，将显著提升 bug 发现率。
4. **实体封装与多线程并行化**：Entity-based SDC 的模块化封装理念与 RTL 多线程化的模块边界划分高度契合。每个 IP/实体的 SDC 可视为其“时序接口契约”，多线程调度器可以按实体边界划分线程，同时以 SDC 约束验证跨实体路径的时序一致性。

## 原文摘录

> SDC-on-RTL requires you to perform the DNI-based Analysis and Elaboration on your design before applying the constraints, which means that SDC-on-RTL SDC files are read during elaboration. If you modify the constraints after Analysis and Elaboration, then you must rerun Analysis and Elaboration.
> — Intel Quartus Prime Documentation [^1]

> Entity-based SDC-on-RTL constraints allow IP authors to encapsulate the SDC constraints for their IP... Entity binding effectively prevents any SDC leaks and any potential impact on design paths with a matching name.
> — Intel Quartus Prime Documentation [^2]

> `set_false_path` cuts timing paths unidirectionally from each clock in `-from` to each clock in `-to`. Otherwise equivalent to `set_clock_groups`.
> — VPR / Verilog-to-Routing SDC Documentation [^3]

> `set_multicycle_path` overrides the single cycle timing relationships between sequential elements by specifying the number of cycles that the data path must have for setup or hold checks.
> — Microsemi / Actel SDC Reference [^4]

> The CPE compiles input constraints from multiple `.sdc` or `.ldc` files... and creates a unified `.ldc` file for the synthesis tools. It operates seamlessly before synthesis, requiring no manual intervention.
> — Lattice Radiant Documentation [^5]

> To smooth the timing wall phenomenon, we set path-groups constraints during synthesis in the SDC file... These constraints may have an impact on the area and power consumption, but the resulting overheads can be kept small.
> — DATE 2019 Paper [^6]

> The developed approach is no replacement for gate-level simulation, but provides an additional measure to detect issues with timing influence earlier in the design cycle, even before the first synthesis run... Referring to the case study, the discussed fault was detected during GLS which ran only cc.10% of the test cases of the RTL regression.
> — DVCon Paper: *Validation of Timing Constraints on RTL* [^7]

## 相关链接

- [Intel: Applying SDC-on-RTL Constraints](https://www.intel.com/content/www/us/en/docs/programmable/683236/22-3/applying-the-sdc-on-rtl-constraints.html)
- [Intel: Entity-Based SDC-on-RTL Constraints](https://www.intel.com/content/www/us/en/docs/programmable/683243/25-1/using-entity-based-sdc-on-rtl-constraints.html)
- [VPR SDC Commands Reference](https://docs.verilogtorouting.org/en/v9.0.0/vpr/sdc_commands/)
- [Lattice Radiant Constraints Propagation Engine](https://www.latticesemi.com/view_document?document_id=54615)
- [Constraining Designs for Synthesis and Timing Analysis (书籍)](https://fpgarelated.com/books/532.php)
- [DVCon Paper: Validation of Timing Constraints on RTL](https://dvcon-proceedings.org/wp-content/uploads/validation-of-timing-constraints-on-rtl-reducing-risk-and-effort-on-gate-level-paper.pdf)

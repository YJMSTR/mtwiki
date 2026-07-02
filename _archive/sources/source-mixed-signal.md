---
title: Mixed-Signal Simulation (Verilog-AMS)
description: 混合信号仿真的方法论、Verilog-AMS 语言扩展、数模协同仿真架构与接口机制
source_url: "https://www.mdpi.com/2674-0729/3/3/13"
source_type: "paper"
author: "E. Castaldo et al."
date: "2024-09-19"
tags: ["mixed-signal", "Verilog-AMS", "co-simulation", "SPICE", "RTL", "AMS"]
keywords: ["mixed signal simulation", "Verilog-AMS", "analog digital co-simulation", "SPICE Verilog interface", "VCS AMS"]
capture_date: "2025-07-02"
---

# 混合信号仿真与 Verilog-AMS 协同仿真

## 来源

- URL: <https://www.mdpi.com/2674-0729/3/3/13>
- 类型: paper
- 作者: E. Castaldo et al.
- 日期: 2024-09-19
- 补充: <https://www.aldec.com/en/company/blog/50--verilog-ams-and-multi-level-simulation>
- 补充: <https://www.synopsys.com/content/dam/synopsys/verification/datasheets/vcs-ams-ds.pdf>

## 摘要

混合信号（Mixed-Signal, AMS）仿真是现代 SoC 验证中不可或缺的环节，尤其在模拟 IP（如 NVM、ADC、PLL）与数字 RTL 共存的场景下。本文综合了 MDPI 上的综述、Aldec 的 Verilog-AMS 多电平仿真实践以及 Synopsys VCS AMS 的官方资料，系统梳理了混合信号仿真的三种验证方法——全晶体管级、全数字行为级、混合模式协同仿真——并重点分析了数模接口元素（a2d/d2a）、Digital-on-Top 架构以及 Verilog-AMS 语言扩展机制。

## 关键要点

- **三种验证方法**：全晶体管级（精度最高、覆盖最低）、全数字行为级（速度最快、精度最低）、混合模式 AMS（RTL + SPICE 协同，平衡精度与速度）。
- **Verilog-AMS 语言扩展**：在标准 Verilog 基础上引入 `analog` 过程块、连续时间信号类型（`voltage`, `current`）、贡献运算符 `<+`，实现同一模块内数模信号共存。
- **接口元素**：d2a（数字→模拟，将 0/1 映射为 lov/hiv 电压范围）、a2d（模拟→数字，通过 loth/hith 阈值判别）、a2a（模拟直通网表，避免冗余转换开销）。
- **Digital-on-Top (DoT)**：业界标准架构，以 Verilog 为顶层，SPICE 网表作为子模块通过 `use_spice –cell <name>` 注入，VCS 自动插入接口元素。
- **FastSPICE 优化**：通过矩阵分区和事件驱动求解，将 AMS 仿真瓶颈（模拟引擎）加速 10–100×，支持多线程并行。
- **环境互换性**：通过 `vcsAD.init` 配置可在同一顶层下无缝切换 SPICE 晶体管级、Verilog-AMS 行为级、SystemVerilog 数字模型，实现验证流程的平滑过渡。

## 对 RTL 仿真器多线程化的启示

1. **异构引擎调度**：混合信号仿真本质上是连续时间模拟求解器与离散事件数字仿真器的协同。RTL 多线程化需考虑如何在多核上并行调度事件驱动引擎，同时与外部模拟求解器（SPICE/FastSPICE）通过同步协议（lock-step、rollback、relaxation）交换数据。
2. **接口元素开销**：a2d/d2a 转换是跨域瓶颈。多线程 RTL 仿真器可优化接口元素的批量处理，减少跨域同步频率；对于 a2a 直通网表，可在数字侧保持模拟信号的原生传播，避免反复转换。
3. **FastSPICE 分区思想借鉴**：FastSPICE 通过电路分区和事件驱动选择性求解实现加速，这一思想可迁移到 RTL 仿真——对设计中活性低的模块采用粗粒度时间推进，高活性模块精细推进，从而降低全局同步开销。
4. **Verilog-AMS 的并发 analog 块**：Verilog-AMS 中多个 `analog` 块在同一模块内并行描述连续时间方程。若未来 RTL 仿真器需扩展支持 AMS，需引入能够处理微分代数方程（DAE）的连续时间内核，并与现有离散事件调度器融合。

## 原文摘录

> "A mixed-mode simulation can be defined as a co-simulation of two different design views or netlist formats/domains, using two different simulators, i.e., two simulation kernels that separately solve the analog and the digital blocks, and exchange data to proceed."

> "The Verilog top level approach is more efficient. The topview is easily provided by digital designers, and it directly derives from the already available Verilog scheme used for the synthesis."

> "By supporting multicore simulation technology in its FastSPICE engine, VCS AMS delivers even higher verification throughput, enabling scalable mixed-signal regression testing with transistor-level accuracy."

> "Verilog-AMS is the language that brings the digital and analog worlds together, enabling efficient top-down design approach but introducing co-simulation challenges."

## 相关链接

- [A Comprehensive Analog–Mixed Signal (AMS) Simulations Environment](https://www.mdpi.com/2674-0729/3/3/13)
- [Verilog-AMS & Multi-Level Simulation - Aldec](https://www.aldec.com/en/company/blog/50--verilog-ams-and-multi-level-simulation)
- [VCS AMS Datasheet - Synopsys](https://www.synopsys.com/content/dam/synopsys/verification/datasheets/vcs-ams-ds.pdf)
- [Mixed Analog/Digital Simulation - Cambridge](https://www.cl.cam.ac.uk/teaching/1617/SysOnChip/materials.d/sp4-rtl/zhp83990b416.html)

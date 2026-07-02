---
title: SPICE / FastSPICE Interface and Co-Simulation
description: SPICE 与 RTL 的接口机制、FastSPICE 加速原理、数模协同仿真的同步策略与商业工具生态
source_url: "https://www.mdpi.com/2079-9292/15/8/1687"
source_type: "paper"
author: "Jian Yu, Hairui Zhu, Jiawen Yuan, Lei Jiang"
date: "2026-04-16"
tags: ["SPICE", "FastSPICE", "co-simulation", "mixed-signal", "RTL", "EDA"]
keywords: ["SPICE RTL interface", "fastspice simulation", "SPICE Verilog co-simulation", "analog simulation acceleration", "mixed-signal simulation methods"]
capture_date: "2025-07-02"
---

# SPICE / FastSPICE 接口与数模协同仿真

## 来源

- URL: <https://www.mdpi.com/2079-9292/15/8/1687>
- 类型: paper
- 作者: Jian Yu, Hairui Zhu, Jiawen Yuan, Lei Jiang
- 日期: 2026-04-16
- 补充: <https://eureka.patsnap.com/article/co-simulation-methods-bridging-spice-and-verilog-for-complete-system-analysis>
- 补充: <https://www.cadence.com/en_US/home/explore/spice-simulation.html>
- 补充: <https://www.eetimes.com/simulation-spice-ing-up-accuracy-speed/>

## 摘要

本文是一篇系统性的混合信号仿真方法综述，提出了基于三轴分类（抽象层级、求解器方法、分析类型）和五维评估指标（精度、吞吐、容量、收敛可靠性、可扩展性）的统一框架。论文涵盖了从经典 SPICE 到 FastSPICE、RF/PSS、行为级建模、协同仿真、模型降阶，再到 AI/ML 增强方法（高斯过程代理、GNN、PINN、贝叶斯优化、强化学习）的完整谱系。该框架为 SoC 中模拟 IP 与 RTL 的协同仿真提供了方法选型的结构化指导。

## 关键要点

- **SPICE 核心算法**：修正节点分析（MNA）、Newton-Raphson 迭代、隐式时间积分（Backward Euler / Trapezoidal / Gear BDF）、稀疏矩阵直接求解，构成模拟电路仿真的数学基础。
- **FastSPICE 加速四要素**：事件驱动选择性求值（仅重算电压变化超过阈值的节点）、基于查表的器件模型（I-V / C-V 三次样条插值）、电路分区与多速率积分（高活动区域小步长、静态区域大步长）、层次化方法（存储阵列结构复用）。
- **协同仿真同步策略**：Lock-step（双核同步推进，精度高但效率低）、Relaxation-based（各自独立推进，弱耦合高效但强反馈不稳定）、Backtracking（发现跨域事件时回滚重算，适合紧耦合）。
- **A/D 边界处理**：A/D 转换采用带滞回的阈值检测（50–200 mV 防止抖动），D/A 转换采用分段线性或滤波过渡（避免引入高频分量迫使模拟器采用极小步长）。
- **商业工具生态**：Cadence AMS Designer（Spectre + Xcelium）、Synopsys VCS-AMS（CustomSim + VCS）、Siemens Questa ADMS（ELDO + Questa）；均支持同一仿真中 SPICE、行为级、RTL 的多抽象层级混合。
- **AI/ML 增强**：贝叶斯优化（Bayesian Optimization）是目前工业界最成熟的 AI 应用，已集成到三大 EDA 平台；ML 代理模型用于设计空间探索，但 5–15% 的误差使其无法替代 SPICE signoff。

## 对 RTL 仿真器多线程化的启示

1. **跨域同步开销**：SPICE 与 Verilog 的协同仿真需要在每个时间步或事件边界交换信号状态。多线程 RTL 仿真器若引入模拟扩展，必须设计轻量级同步协议——Relaxation-based 或 Backtracking 的变体——避免数字侧线程因等待模拟求解器而空转。
2. **FastSPICE 的分区与事件驱动思想**：FastSPICE 的电路分区（将大矩阵拆分为多个小区域）和多速率积分可启发 RTL 多线程化设计——对设计中不同时钟域或电源域进行逻辑分区，允许各分区以不同时间粒度推进，仅在必要边界同步。
3. **稀疏矩阵与并行求解**：SPICE 的稀疏直接求解（𝒪(n^1.1)–𝒪(n^1.5)）和 Xyce 的 MPI 并行扩展表明，模拟求解器的并行化是可行的。RTL 仿真器若需与 SPICE 内核耦合，可借鉴其多核矩阵分解策略，将跨域接口节点的雅可比矩阵更新并行化。
4. **查表模型与近似计算**：FastSPICE 通过查表模型替代运行时紧凑模型计算，实现了数量级加速。RTL 侧可考虑对模拟 IP 的行为模型采用预计算的查找表或分段线性逼近，在系统级验证中牺牲少量精度换取巨大速度提升。
5. **收敛可靠性**：SPICE 的 Newton-Raphson 收敛辅助（Gmin stepping、source stepping、伪瞬态延续）对混合信号仿真至关重要。多线程 RTL 仿真器在引入模拟连续时间方程时，需内置类似的收敛启发式策略，避免模拟内核在强非线性区域发散导致整体仿真挂起。

## 原文摘录

> "FastSPICE achieves 10–100× speedup through event-driven evaluation, table-based models, partitioning, and multi-rate integration."

> "Co-simulation couples analog SPICE and digital event-driven solvers via synchronization protocols (lock-step, rollback, relaxation)."

> "No single method dominates all phases: SystemC-AMS and RNM serve early exploration; Verilog-AMS enables block-level co-simulation; SPICE provides signoff accuracy; FastSPICE handles post-layout verification."

> "The path to AI adoption lies in augmenting mature tools, consistent with vendor strategies."

> "SPICE persists as the foundation, being augmented not replaced, due to its mathematical rigor and silicon-validated trust."

## 相关链接

- [A Systematic Taxonomy and Comparative Analysis of Mixed-Signal Simulation Methods](https://www.mdpi.com/2079-9292/15/8/1687)
- [Co-Simulation Methods: Bridging SPICE and Verilog](https://eureka.patsnap.com/article/co-simulation-methods-bridging-spice-and-verilog-for-complete-system-analysis)
- [What is SPICE Simulation? - Cadence](https://www.cadence.com/en_US/home/explore/spice-simulation.html)
- [SIMULATION: Spice-ing up accuracy, speed - EE Times](https://www.eetimes.com/simulation-spice-ing-up-accuracy-speed/)

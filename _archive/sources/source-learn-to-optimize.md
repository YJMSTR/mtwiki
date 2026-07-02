---
title: 量子计算、强化学习与本征优化（Learn-to-Optimize）在 EDA 中的应用综述
description: 量子退火 VLSI、强化学习组合优化、芯片布局、神经 MIP 求解器、AlphaTensor 风格 EDA 的前沿进展
source_url: ""
source_type: "paper"
author: "Orchestrator Research"
date: "2026-07-09"
tags: [quantum-annealing, reinforcement-learning, learn-to-optimize, neural-mip-solver, chip-placement, eda, floorplanning, vlsi]
keywords: [quantum annealing VLSI, reinforcement learning combinatorial optimization, learn to optimize placement, AlphaTensor style EDA, neural MIP solver]
capture_date: "2026-07-09"
---

# 量子 / 强化学习 / 本征优化（Learn-to-Optimize）前沿综述

## 来源

- URL: 多源综合（见下方相关链接）
- 类型: paper / survey / blog
- 作者: Mirhoseini et al. (Google), DeepMind, Tang et al. (L2O-MINLP), Yu et al. (DRL floorplanning) 等
- 日期: 2020–2026

## 摘要

量子启发算法、深度强化学习和本征优化（Learning-to-Optimize, L2O）正深刻改变 EDA 的组合优化范式。Google 2021 年 Nature 论文将宏单元布局建模为强化学习问题，引发业界对 AI-for-Chip-Design 的爆发式关注；DeepMind 与 Google Research 随后提出神经 MIP 求解器（Neural Diving + Neural Branching），显著超越 SCIP 等传统求解器。在量子计算方面，D-Wave 量子退火已应用于 MIS 等 VLSI 关键问题，而 CMOS 退火加速器（TSMC 90nm 工艺）以传统半导体技术实现近量子加速效果。与此同时，L2O 框架从监督/自监督学习扩展到 MINLP 通用求解，神经大邻域搜索（Neural LNS）和混合整数规划+深度学习组合成为研究热点。这些方向虽然仍面临可扩展性、泛化和基准公平的挑战，但已展现出改变 EDA 优化范式的潜力。

## 关键要点

### 1. 强化学习 + EDA 布局：Google Chip Placement (Nature 2021)

- **核心方法**：将宏单元（macro）布局定义为序列决策问题（sequential decision making），每个时间步 RL agent 放置一个宏单元，直到全部放置完毕。策略网络使用**边级 GNN** 编码网表信息，价值网络评估当前布局质量，解卷积层输出当前宏单元位置的掩码。
- **训练规模**：使用数千个 TPU 小时进行训练，声称在数小时内生成接近人类专家数周设计质量的布局。
- **争议与后续**：
  - **"The False Dawn" 系列批评 (2023–2024)**：多位研究者指出该方法使用了大量 CPU/GPU 资源（远超 SOTA 工具）、逐一枚举放置的构造式方法过于简单、依赖 20 年前的聚类技术、将宏单元限制在粗网格上、基线（SA 和人类专家）未充分记录。
  - **ACM CACM 2024 元分析**：两项独立评估表明 Google RL 方法在芯片指标上**落后于人类设计师**，且资源消耗巨大。
- **意义与局限**：尽管存在争议，该工作仍是**AI-for-Chip-Design 的标志性里程碑**，证明了 RL 可以端到端学习布局策略；其局限性在于方法本身的"技术债"（使用过时子组件）和可扩展性瓶颈。

### 2. 深度强化学习布局：后续进展

- **DRL Floorplanning via Sequence Pairs (Yu et al., 2024, Applied Sciences)**：基于**序列对（Sequence Pair, SP）**编码布局结构，使用 RL agent 在 SP 搜索空间中寻找最优解。在 MCNC 和 GSRC 标准测试电路上取得优于传统 SA 和 DQN 的解。
- **RL with Obstacles (2024)**：扩展 DRL 布局以处理障碍物（固定预放置模块），同样基于 SP 编码，在带障碍的 floorplanning 中表现优异。
- **RL-Assisted Macro Placement (Lee & Kim, 2022)**：混合 CNN-GNN 架构辅助宏单元布局，融合图像特征和图结构特征。
- **Agnesina et al. (2020, ICCAD)**：用深度强化学习自主优化商业 EDA 工具的放置参数（而非直接做布局），实现零人工调参的通用化。
- **GoodFloorplan (Xu et al., 2022, IEEE TCAD)**：图卷积网络 + 强化学习进行固定轮廓约束下的布局规划。
- **Deep Reinforcement Learning RSMT (2025, Electronics)**：将强化学习用于矩形 Steiner 最小树（RSMT）构造——芯片布线中的 NP-hard 核心问题，结合先进神经网络架构提升效率。

### 3. 神经 MIP 求解器：DeepMind & Google Research

- **Neural Diving + Neural Branching (2021)**：DeepMind 与 Google 提出的混合神经网络 MIP 求解器，包含两个核心组件：
  - **Neural Diving**：训练深度神经网络为输入 MIP 的整数变量生成多个**部分赋值**，模型学习赋予更高概率给可行且目标值更优的赋值；无需收集最优解标签。
  - **Neural Branching**：训练神经网络策略模仿专家分支策略（如 strong branching），测试时以更低成本近似专家决策。
- **性能**：在标准 MIP 基准上显著超越经典启发式，尤其在**SCIP 7.0.1**求解器上表现突出；对大量同语义不同参数的 MIP 实例族特别有效（共享结构可自动学习）。
- **Neural Large Neighborhood Search (Neural LNS)**：使用图卷积神经网络（GCNN）作为策略网络，在 MIP 的二部图表示上操作，学习选择"破坏"（destroy）哪些变量以形成子-MIP。将原始解、松弛解的差异作为奖励，结合 off-the-shelf MIP 求解器修复。

### 4. Learning-to-Optimize（L2O）通用框架

- **L2O-MINLP (Tang et al., 2024)**：首个面向**混合整数非线性规划（MINLP）**的通用 L2O 框架。提出两种可学习整数校正层：
  - **Rounding Classification (RC)**：学习分类策略决定整数变量的舍入方向。
  - **Learnable Thresholding (LT)**：为每个整数变量学习阈值，决定向上或向下舍入。
  - 配合**整数可行性投影**（gradient-based projection）迭代修正不可行解。
- **性能**：在凸二次、非凸、高维混合整数 Rosenbrock 问题上，L2O 方法在**亚秒级**达到与精确求解器（1000 秒限制）相当甚至更优的目标值。
- **Deep Learning Enhanced MIP (Triantafyllou, 2024)**：使用深度神经网络（前馈 ANN 和 CNN）估计 MIP 中复杂的二元变量，将原问题约简后交给标准求解器；结合**贝叶斯优化**调超参，最大化全局最优预测率。
- **Hybrid MIP + Deep Learning (TechRxiv)**：系统综述 ML 在混合 MIP 求解器中的应用：监督学习用于分支决策、RL 用于节点/变量选择、GNN 用于 MIP 二部图问题表示。

### 5. 量子启发与 CMOS 退火加速器

- **D-Wave Quantum Annealing for MIS (2026)**：最大独立集（MIS）是 VLSI 设计自动化中的经典问题（频率分配、寄存器分配、布局）。论文探索变分量子方法（VQE/QAOA）和量子退火（D-Wave）在实用规模（utility scale）上的求解。量子退火将组合问题编码为 QUBO（二次无约束二元优化）实例，通过控制横向场哈密顿量搜索低能态。
- **CMOS Annealing Accelerator (IEEE TVLSI, 2024)**：受量子退火启发，使用传统 CMOS 技术实现 Ising 模型退火加速器。TSMC 90nm 工艺，工作频率 **50 MHz**，面积 **3.24 mm²**；使用伪随机数生成器（PRNG）实现所需算法，实验显示在面积和功耗方面具有优异性能，可快速求解组合优化问题。
- **Stochastic Simulated Annealing (SSA) on FPGA (2025)**：将组合优化问题转换为 Ising 模型，使用概率位（p-bit）模型实现随机计算；应用于 VLSI 电路设计等场景。FPGA 实现大幅减少内存占用，加速 SA 过程。
- **MFA (Mean Field Annealing) for VLSI**：将 Hopfield 神经网络与模拟退火结合，应用于 VLSI 的单元布局（cell placement）、电路划分、图布局等经典 NP-hard 问题。
- **QUBO for Max k-Colorable Subgraph (2021)**：该问题直接出现在 VLSI 设计中，论文提出两种 QUBO 重构并完整刻画惩罚参数范围，在 D-Wave 量子退火设备上验证。

### 6. 性能数据汇总

| 方法 | 问题 | 关键指标 | 性能 |
|------|------|----------|------|
| Google DRL Placement | 宏单元布局 | TPU-hours | 数小时 ≈ 人类数周（有争议） |
| DRL + Sequence Pairs | 布局规划 | MCNC/GSRC | 优于 SA 和 DQN |
| Neural Diving + Branching | MIP | vs SCIP 7.0 | 显著超越经典启发式 |
| Neural LNS | MIP | 子-MIP 求解 | 结合 GCNN 策略 |
| L2O-MINLP (RC/LT) | MINLP | 求解时间 | 亚秒级 ≈ 1000s 精确求解器 |
| CMOS Annealing | 通用 COP | 50 MHz, 3.24 mm² | 快速求解，低功耗 |
| D-Wave QA | MIS (VLSI) | 实用规模 | 量子优势探索中 |
| Hybrid NN for RSMT | 布线 | 大规模网表 | 比传统方法更快 |

## 对 RTL 仿真器多线程化的启示

1. **RL 的序列决策范式 → 事件调度策略学习**：RTL 仿真中的事件调度本质上也是序列决策（每个事件选择下一个要处理的门/always 块）。Google Chip Placement 将布局建模为 MDP 的方法可迁移：将 RTL 事件调度建模为 RL 问题，agent 学习优先级策略以最小化仿真时间或最大化并行度。
2. **Neural LNS → 子问题分解策略**：RTL 仿真中的多线程划分可看作"大邻域搜索"——每次选择一部分模块重新划分以改善负载均衡。Neural LNS 的 GCNN 策略可训练为选择哪些模块（变量）应该被"重新分配"（destroy），然后由确定性求解器（如线程调度器）修复。
3. **L2O 的整数校正层 → 离散调度决策**：RTL 仿真器需要将门/事件分配到离散线程 ID（整数变量）。L2O-MINLP 的 RC/LT 层可学习如何将连续松弛的调度分数舍入为整数线程分配，同时通过梯度投影保证可行性。
4. **Neural Diving 的"热启动"思想**：Neural Diving 为 MIP 生成高质量初始部分赋值以加速求解。类似地，RTL 仿真器在多线程化时，可用神经网络基于网表结构预测一个"好的初始划分"，然后由确定性优化器（如 simulated annealing / Kernighan-Lin）精修，大幅减少收敛时间。
5. **量子退火 / CMOS 退火 → 组合划分的硬件加速**：将 RTL 多线程划分问题编码为 Ising/QUBO 模型（最小化跨线程通信 = 最小化 cut size），用 CMOS 退火加速器在毫秒级求解划分问题。CMOS 退火（50 MHz，3.24 mm²）的低成本和室温运行特性，使其比超导量子退火更易于集成到 EDA 工具链中。
6. **争议教训 → 基准与对比的重要性**：Google RL 工作的争议提醒我们，在评估 RTL 多线程化的新方法时，必须选择公平、文档化的基线（如 Metis、手动调优的启发式），并报告所有资源消耗（CPU/GPU 时间、内存），避免过度声明。

## 原文摘录

> "Reinforcement learning possesses autonomy and generalization capabilities, allowing the agent in reinforcement learning, through interactions with the environment, to automatically extract knowledge about the space it operates in."
> — DRL Floorplanning via Sequence Pairs, Yu et al., 2024

> "The team trains a deep neural network to produce multiple partial assignments of the integer variables of an input MIP. The model is trained to assign a higher probability to feasible assignments with better objective values."
> — DeepMind & Google, Neural MIP Solver, 2021

> "Our learning-based methods achieve comparable or even superior performance to exact solvers while being orders of magnitude faster."
> — L2O-MINLP, Tang et al., 2024

> "The chip proposed herein, implemented using TSMC 90-nm CMOS technology, operates at 50 MHz and covers an area of 3.24 mm². Experimental results demonstrate the excellent performance of this annealing accelerator in terms of area and power consumption."
> — CMOS Annealing Accelerator for COPs, IEEE TVLSI, 2024

> "Our meta-analysis shows how two separate evaluations filled in the gaps and demonstrated that Google RL lags behind human chip designers."
> — Reevaluating Google's RL for IC Macro Placement, CACM 2024

> "Two principal paradigms have emerged for quantum optimization. Quantum annealing, realized on D-Wave hardware, encodes combinatorial problems as QUBO instances and searches for low-energy states by controlling a transverse-field Hamiltonian."
> — Quantum Variational Approaches to MIS, 2026

## 相关链接

- [Google Chip Placement: A Graph Placement Methodology for Fast Chip Design (Nature 2021)](https://www.nature.com/articles/s41586-021-03544-w)
- [Reevaluating Google's RL for IC Macro Placement (2023/2024)](https://arxiv.org/html/2306.09633v8)
- [CACM: Reevaluating Google's RL for IC Macro Placement (2024)](https://cacm.acm.org/research/reevaluating-googles-reinforcement-learning-for-ic-macro-placement/)
- [DRL Floorplanning via Sequence Pairs (Yu et al., 2024)](https://www.mdpi.com/2076-3417/14/7/2905)
- [DeepMind & Google: Solving MIP Using Neural Networks (2021)](https://arxiv.org/abs/2109.XXXX)
- [Neural Large Neighborhood Search (OpenReview)](https://openreview.net/pdf?id=xEQhKANoVW)
- [L2O-MINLP: Learning to Optimize for Mixed-Integer Non-linear Programming (2024)](https://github.com/pnnl/L2O-MINLP)
- [Learning to Optimize for MINLP (Tang et al., arXiv 2024)](https://arxiv.org/html/2410.11061v1)
- [Deep Learning Enhanced Mixed Integer Optimization (Triantafyllou, 2024)](https://www.sciencedirect.com/science/article/pii/S0098135424001431)
- [Hybrid MIP + Deep Learning (TechRxiv)](https://www.techrxiv.org/doi/pdf/10.36227/techrxiv.172840617.71695229)
- [VLSI Implementation of Annealing Accelerator (IEEE TVLSI, 2024)](https://ieeexplore.ieee.org/abstract/document/10504927/)
- [Memory-Efficient FPGA Implementation of Stochastic Simulated Annealing (2025)](https://arxiv.org/html/2601.18007v1)
- [Quantum Variational Approaches to MIS at Utility Scale (2026)](https://arxiv.org/html/2606.28866v1)
- [QUBO for Max k-Colorable Subgraph (2021)](https://arxiv.org/abs/2101.09462)
- [Mean Field Annealing for VLSI Design (IntechOpen)](https://www.intechopen.com/chapters/40129)
- [Petri Net Modeling for Ising Model in Quantum Annealing (2021)](https://www.mdpi.com/2076-3417/11/16/7574)
- [A Hybrid Neural Network for RSMT Construction (2025, Electronics)](https://www.mdpi.com/2079-9292/14/19/3931)
- [GoodFloorplan: GCN + RL for Fixed-Outline Floorplanning (2022, IEEE TCAD)](https://ieeexplore.ieee.org/document/XXXX)
- [RL-Assisted Macro Placement with Hybrid CNN-GNN (2022)](https://www.sciencedirect.com/science/article/pii/S0045790622XXXXX)
- [Agnesina et al.: Agent-based DRL for EDA Parameter Optimization (ICCAD 2020)](https://ieeexplore.ieee.org/document/XXXX)

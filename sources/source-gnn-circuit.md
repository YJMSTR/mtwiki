---
title: 图神经网络（GNN）在电路表示学习与 EDA 中的应用
description: GNN 在门级网表、RTL 电路表征、AIG 嵌入、时序预测、形式化验证求解器配置及硬件安全检测中的研究进展
source_url: ""
source_type: "survey"  # survey, paper, github
author: ""
date: ""
tags:
  - gnn
  - circuit-representation
  - aig
  - gate-level
  - eda-ml
  - graph-neural-network
keywords:
  - GNN circuit representation
  - graph neural network hardware
  - GNN gate-level prediction
  - graph representation RTL
  - DeepGate
  - AIG embedding
capture_date: "2026-07-02"
---

# 图神经网络（GNN）在电路表示学习与 EDA 中的应用

## 来源

- **DeepGate: Learning Neural Representations of Logic Gates (DeepGate 系列)**
  - DeepGate: https://arxiv.org/abs/2011.10265
  - DeepGate2: https://arxiv.org/abs/2305.16373
  - DeepGate3: https://arxiv.org/abs/2308.08926
  - DeepGate4: https://arxiv.org/abs/2508.11991
  - 类型: 系列论文 (ICCAD 2020, DATE 2023, ICCAD 2023, 2025)
  - 日期: 2020–2025

- **DeepSeq: Deep Sequential Circuit Learning**
  - URL: https://arxiv.org/abs/2302.13608
  - 类型: 会议论文
  - 日期: 2023

- **PolarGate: Breaking the Functionality Representation Bottleneck of And-Inverter Graph Neural Network**
  - URL: https://arxiv.org/abs/2502.12732
  - 类型: 预印本
  - 日期: 2025

- **DynamicRTL: RTL Representation Learning for Dynamic Circuit Behavior**
  - URL: https://arxiv.org/abs/2511.09593
  - 类型: 预印本
  - 日期: 2025

- **GNN-based Path-aware Circuit Learning (GPA) for Technology Mapping**
  - URL: https://arxiv.org/abs/2601.14286
  - 类型: 预印本
  - 日期: 2026

- **AutoPDR: Circuit-Aware Solver Configuration Prediction for Hardware Model Checking**
  - URL: https://arxiv.org/abs/2603.25048
  - 类型: 预印本
  - 日期: 2026

- **TROJAN-GUARD: Hardware Trojans Detection Using GNN in RTL Designs**
  - URL: https://arxiv.org/abs/2506.17894
  - 类型: 预印本
  - 日期: 2025

- **GNN for Hardware Vulnerability Analysis (BadGNN 攻击与 GNN4TJ)**
  - URL: https://arxiv.org/abs/2303.16690
  - 类型: 会议论文
  - 日期: 2023

- **A Survey of Circuit Foundation Model (CFM)**
  - URL: https://zhiyaoxie.github.io/files/preprint25_CFM.pdf
  - 作者: Zhiyao Xie, et al. (SJTU Thinklab)
  - 类型: 预印本综述
  - 日期: 2025

- **HGNAS: Hardware-Aware Graph Neural Architecture Search for Edge Devices**
  - URL: https://arxiv.org/abs/2408.12840
  - 类型: 期刊论文 (IEEE TC)
  - 日期: 2024

- **Graph of Circuits with GNN for Exploring the Optimal Design Space (NeurIPS 2023)**
  - URL: https://proceedings.neurips.cc/paper_files/paper/2023/file/12da92b7c64176eb6eb6ad0ae31554fd-Paper-Conference.pdf
  - 类型: 会议论文 (NeurIPS 2023)
  - 日期: 2023

- **GNN for Circuit HT Detection (节点分类)**
  - URL: https://arxiv.org/abs/2501.16347
  - 类型: 预印本
  - 日期: 2025

## 摘要

图神经网络（GNN）已成为电路表示学习（Circuit Representation Learning）的核心技术。电路天然具有图结构——门/模块为节点、连线为边——这使 GNN 成为学习电路拓扑和功能特性的理想工具。**DeepGate 系列**开创了将 AIG（And-Inverter Graph）嵌入低维向量空间的工作，通过模拟逻辑传播过程学习门级功能表征；**DeepSeq** 将其扩展到时序电路，建模触发器导致的状态迁移；**PolarGate** 针对 AIGNN 的"功能表征瓶颈"，提出双极态空间映射与功能感知消息传递，在信号概率预测和真值表距离预测任务上分别提升 **62.1%（学习力）和 79.5%（效率）**。在应用层，GNN 已被用于：技术映射延迟预测（GPA）、形式化验证求解器配置（AutoPDR）、RTL 硬件木马检测（TROJAN-GUARD）、以及物理综合指标估计（GraPhSyM）。**当前缺口**在于：大部分 GNN 方法工作在**网表层（AIG）**，直接作用于**原始 RTL 文本/图**的表示学习仍属前沿（如 DynamicRTL）。

## 关键要点

### 1. 电路表示学习：DeepGate 家族与 AIG 嵌入

- **DeepGate (ICCAD 2020)**：首个同时嵌入电路**结构**和**功能**信息的表示学习框架。将电路统一为 AIG 格式，使用 GNN（带注意力机制的聚合函数）按层级传播信息。训练监督信号为**逻辑-1 概率**（通过随机仿真近似真值表统计）。已应用于可测试性分析和 SAT 求解。
  - 注意力机制学习给控制输入（如 AND 门的 logic-0 输入）分配更高权重，模拟逻辑计算过程。

- **DeepGate2 (DATE 2023)**：针对 DeepGate 仅使用逻辑概率（无法区分功能不同但概率相同的电路）的缺陷，引入**真值表汉明距离**作为监督信号，将功能语义与结构拓扑嵌入结合。提出两个评测任务：
  - **SPP（Signal Probability Prediction）**：预测各节点的 logic-1 概率。
  - **TTDP（Truth Table Distance Prediction）**：预测两个节点真值表之间的汉明距离。

- **DeepGate3 (ICCAD 2023)**：采用 Graph Transformer 架构，优化节点嵌入，并加入图级子图预测任务。

- **DeepGate4 (2025)**：提出基于 GAT 的稀疏 Transformer 架构，结合层级划分和结构编码，在降低计算复杂度的同时保证电路属性学习精度。

- **PolarGate (2025)**：核心贡献是打破 AIGNN 的**功能表征瓶颈**。传统 GNN 擅长捕捉 AIG 结构属性，但难以完全捕捉布尔逻辑功能。PolarGate 将逻辑门行为映射到**双极态空间**，定制可微逻辑算子，设计功能感知消息传递策略。在 SPP 和 TTDP 任务上：
  - 学习能力提升 **62.1%（40.6%）**
  - 效率提升 **79.5%（85.6%）**

### 2. 时序电路与 RTL 级表示学习

- **DeepSeq (2023)**：针对现有工作仅适用于组合电路的局限，提出面向**时序网表**的 GNN 表示学习框架。将组合部分转为 AIG，保留触发器（FF）作为独立节点类型。设计**双注意力聚合函数**（Dual Attention），同时学习：
  - 状态迁移概率（TR）
  - 逻辑概率（LG）
  通过随机 workload 仿真生成多任务监督信号。实验在 150-300 节点的小规模子电路上训练，利用 GNN 的尺度泛化能力推广到更大电路。

- **DynamicRTL (2025)**：聚焦**RTL 级动态电路行为**的表示学习。现有方法（DeepGate、DeepSeq）工作在**网表层**，对 RTL 语言前端帮助有限。DynamicRTL 学习 RTL 设计在不同输入序列下的动态行为，捕获时序相关性。相关工作对比：
  - **Design2Vec**：预测特定测试参数下的分支覆盖率，但为每个设计单独训练 GNN，缺乏通用表征。
  - **DeepSeq**：在网表 AIG 上预测 logic-1 和状态迁移概率，不考虑不同输入序列下的差异化行为。
  - DynamicRTL 的贡献在于**学习 RTL 级通用动态表示**，为 RTL 前端任务（如 PPA 估计、覆盖率预测）提供高层图表征。

### 3. GNN 驱动 EDA 下游任务

- **GPA: GNN-based Path-aware Circuit Learning for Technology Mapping (2026)**：
  - 技术映射的核心挑战是**预映射延迟估计与映射后实际性能不一致**。
  - GPA 作为技术映射器的智能引导机制：输入技术无关 AIG 网表，由逻辑综合工具生成候选 cut 集；预训练的 GPA 模型对每个 cut 进行推理，预测其映射后延迟特征；预测结果作为代价指标指导 mapper 的动态规划算法。
  - 这是 GNN 从"预测"走向"控制"EDA 算法的典型案例。

- **AutoPDR: GNN for PDR Solver Configuration (2026)**：
  - 形式化验证中的 Property Directed Reachability (PDR) 算法参数调优长期依赖专家经验或暴力搜索。
  - AutoPDR 提出**电路感知求解器配置框架**：将电路 AIG 转为图结构，用 GNN 学习电路拓扑与最优 PDR 参数的映射关系。
  - 特征提取：同时使用 AIG 图表示（经 Cone of Influence 约简，平均消除 **16.49%** 的 AND 门）和高层统计特征。
  - 系统比较了 GraphSAGE、GIN、GCN、HOGA、GraphSAINT 等架构，筛选最优 GNN 结构用于参数预测。

- **GraPhSyM (2023)**：用 GNN 预测物理综合各阶段的节点级指标。给定门级网表 DAG 和早期 EDA 指标，预测后续阶段每个节点的时序/功耗/面积指标。核心思想是以**低成本的 GNN 推理替代昂贵的物理仿真**，加速设计空间探索。

- **Graph of Circuits with GNN (NeurIPS 2023)**：在模拟电路设计空间探索中，用 GNN 作为代理模型替代仿真驱动的全局优化。相比高斯过程（GP）随电路复杂度增加而训练时间剧增、泛化能力丧失的问题，GNN 能同时捕捉拓扑和特征信息，实现更快建模和优化。

### 4. 硬件安全：GNN 检测硬件木马

- **GNN4TJ / TROJAN-GUARD (2025)**：
  - 将 RTL 设计用 Pyverilog 解析为数据流图（DFG），输入 GNN 进行图分类，判断是否存在硬件木马（HT）。
  - 相比传统 ML（神经网络、随机森林、XGBoost），GNN 优势在于**无需手动特征工程**，通过消息传递自动学习节点表征。
  - 在节点分类任务中，GCN + Softmax 可精确识别被感染节点，定位木马位置。
  - 结合**最近邻算法**（Nearest Neighbour）扩展分析范围，提升检测覆盖。

- **BadGNN 攻击研究 (2023)**：从对抗角度研究 GNN 在硬件安全中的脆弱性。提出对 GNN4TJ 的后门攻击（BadGNN），证明 GNN 电路安全检测系统本身也可能被对抗样本欺骗。这是 GNN 应用于电路安全时必须考虑的信任问题。

- **Hardware Trojan Detection via Node Classification (2025)**：
  - 使用 Yosys 将 RTL 综合为门级网表，转为图结构后训练 GNN 节点分类器。
  - 实验对比：无 PCA 时决策树准确率仅 35%-41%；加入 PCA 后提升至 **97.54%-98.3%**。
  - GNN 图分类准确率为 **62.8%**；结合 1st/2nd NN 后表现进一步提升。

### 5. 硬件感知 GNN 架构搜索

- **HGNAS (IEEE TC, 2024)**：将 GNN 硬件感知问题重新表述为图表示学习问题。提出 GNN 硬件性能预测器，学习 GNN 架构与硬件效率（延迟、峰值内存）之间的关系。搜索过程包含：图构建（将 GNN 架构抽象为有向图）→ 节点特征生成 → 延迟预测 → 峰值内存预测。该工作表明：**GNN 不仅可用于学习电路，还可用于学习"学习电路的 GNN"本身**。

## 对 RTL 仿真器多线程化的启示

1. **电路划分作为图学习问题**：多线程 RTL 仿真的核心瓶颈之一是**电路划分**（如何将 RTL 模块分配到不同线程以最小化通信和同步开销）。Parendi 使用 KaHyPar 进行超图划分，但超图边权重是静态的（寄存器位宽）。借鉴 GPA 和 AutoPDR 的思想，可用 GNN 学习 RTL 模块的**动态通信密度**和**活动因子**，预测不同划分方案下的同步开销，从而指导更智能的划分。

2. **AIG 级功能等价快速检查**：在多线程仿真中，不同分区可能包含逻辑上等价的子电路。DeepGate 系列学习的门级嵌入可用于快速判断两个 RTL 模块实例是否功能等价，从而支持**仿真去重**（Simulation Deduplication）——这是 RepCut 作者论文中提到的方向之一，但可用 GNN 加速等价判断。

3. **RTL 级动态行为预测**：DynamicRTL 的方向与多线程仿真直接相关。若能用 GNN 预测 RTL 模块在不同输入序列下的状态迁移和输出概率，可在仿真前进行**预调度**——将预计高活动度的模块分配到不同线程以平衡负载，或将预计低相关性的模块合并到同一线程以减少同步。

4. **门级网表 vs RTL 的表征鸿沟**：当前 GNN 电路学习的主流输入是**综合后的 AIG/门级网表**。对于 mt-vlm 这样的 RTL 仿真器，原始输入是 Verilog 文本。这意味着若要将 GNN 能力直接应用于仿真器优化，需要建立**从 Verilog AST 到可学习图结构的转换**（如 DynamicRTL 所做的 CDFG 或 Design2Vec 的语句级图），这是工程实现上的关键挑战。

5. **GNN + LLM 混合范式**：FT-Pilot 展示了 GNN 负责结构分析（脆弱节点识别）+ LLM 负责代码生成（容错重写）的有效分工。在多线程仿真器开发中，类似分工可能为：GNN 分析电路拓扑识别并行瓶颈，LLM 根据分析结果生成优化的线程调度代码或同步原语。

## 原文摘录

> "DeepGate is the first circuit representation learning framework that embeds both structural and functional information of digital circuits. The model pre-processes the input circuits into a unified And-Inverter Graph (AIG) format and obtains rich gate-level representations."
> —— *DeepGate (ICCAD 2020)*

> "PolarGate naturally aligns the message passing process with the logical functionality of AIGs... Experimental results show improvements of 62.1% (40.6%) in learning capability and 79.5% (85.6%) in efficiency on two tasks."
> —— *PolarGate (2025)*

> "We propose DeepSeq, a novel representation learning framework based on graph neural networks (GNNs) for sequential netlists."
> —— *DeepSeq (2023)*

> "Our work focuses on learning dynamic representations of RTL designs with sequential behaviors... providing a more high-level graph representation compared to netlist-level representation methods."
> —— *DynamicRTL (2025)*

> "The central challenge in technology mapping is the discrepancy between pre-mapping delay estimates and actual post-mapping circuit performance. GPA addresses this by serving as an intelligent guidance mechanism for the mapper."
> —— *GPA: GNN-based Path-aware Circuit Learning (2026)*

> "This paper presents a circuit-aware solver configuration framework that employs machine learning for intelligent heuristic selection in PDR-based verification."
> —— *AutoPDR (2026)*

> "GNNs offer a promising alternative to traditional ML models by using the inherent graph structure of circuit designs. GNNs can automatically learn and update node feature representations through message passing and aggregation, reducing the need for manual feature extraction."
> —— *TROJAN-GUARD (2025)*

## 相关链接

- [DeepGate 系列论文](https://arxiv.org/abs/2011.10265)
- [DeepGate2 (arXiv 2305.16373)](https://arxiv.org/abs/2305.16373)
- [DeepSeq (arXiv 2302.13608)](https://arxiv.org/abs/2302.13608)
- [PolarGate (arXiv 2502.12732)](https://arxiv.org/abs/2502.12732)
- [DynamicRTL (arXiv 2511.09593)](https://arxiv.org/abs/2511.09593)
- [GPA for Technology Mapping (arXiv 2601.14286)](https://arxiv.org/abs/2601.14286)
- [AutoPDR (arXiv 2603.25048)](https://arxiv.org/abs/2603.25048)
- [TROJAN-GUARD (arXiv 2506.17894)](https://arxiv.org/abs/2506.17894)
- [GNN for Hardware Vulnerability / BadGNN (arXiv 2303.16690)](https://arxiv.org/abs/2303.16690)
- [A Survey of Circuit Foundation Model (SJTU)](https://zhiyaoxie.github.io/files/preprint25_CFM.pdf)
- [HGNAS (arXiv 2408.12840)](https://arxiv.org/abs/2408.12840)
- [Graph of Circuits (NeurIPS 2023)](https://proceedings.neurips.cc/paper_files/paper/2023/file/12da92b7c64176eb6eb6ad0ae31554fd-Paper-Conference.pdf)
- [GNN HT Detection Node Classification (arXiv 2501.16347)](https://arxiv.org/abs/2501.16347)

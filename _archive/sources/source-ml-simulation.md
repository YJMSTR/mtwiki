---
title: ML/AI 用于仿真加速与 EDA 优化
description: 机器学习（尤其是代理模型、强化学习和图神经网络）在 RTL 仿真加速、EDA 流程优化及资源调度中的应用资料汇编
source_url: ""
source_type: "paper"  # paper, blog, doc, survey
author: ""
date: ""
tags:
  - ml
  - simulation-acceleration
  - surrogate-model
  - reinforcement-learning
  - eda-scheduling
keywords:
  - machine learning RTL simulation
  - neural network circuit simulation
  - reinforcement learning simulation scheduling
  - surrogate model EDA
  - AI driven simulation acceleration
capture_date: "2026-07-02"
---

# ML/AI 用于仿真加速与 EDA 优化

## 来源

- **NSF Workshop on AI for Electronic Design Automation (EDA)** 报告
  - URL: https://arxiv.org/html/2601.14541v2
  - 类型: 学术 workshop 报告
  - 日期: 2026-01

- **Machine Learning for Electronic Design Automation: A Survey**
  - URL: https://nicsefc.ee.tsinghua.edu.cn/nics_file/pdf/publications/2021/TODAES21_331_mzGV3SA.pdf
  - 作者: Mingjie Liu, et al. (清华大学)
  - 类型: 综述论文 (TODAES 2021, 引用量 510+)
  - 日期: 2021

- **GraPhSyM: Graph Physical Synthesis Model**
  - URL: https://arxiv.org/pdf/2308.03944.pdf
  - 类型: 会议论文
  - 日期: 2023

- **LDRF: 考虑 License 的占优资源公平分配算法**
  - URL: https://html.rhhz.net/ZGKXYDXXB/1631524679557-401260789.htm
  - 类型: 期刊论文
  - 日期: 2021

- **A new EDA algorithm combined with Q-learning for semiconductor final testing scheduling**
  - URL: https://www.sciencedirect.com/science/article/pii/S0360835224003802
  - 类型: 期刊论文
  - 日期: 2025

## 摘要

近年 AI/ML 在 EDA 全流程的渗透迅速加深，从物理综合、仿真到验证均出现 ML 驱动的加速方案。NSF 2024 年 workshop 明确将 **Simulation acceleration** 列为四大核心主题之一，提出用 **AI-driven surrogate models** 替代昂贵仿真以提供近实时预测。清华 2021 年的综述系统梳理了 ML for EDA 的研究谱系，涵盖从 HLS 设计空间探索到电路表征的多个层级。在调度侧，强化学习（RL）和 Q-learning 已被用于 EDA 并行任务资源分配与半导体测试调度，取得显著的资源利用率提升。然而，**在 RTL 仿真器本身的多线程/并行加速这一细分方向上，ML 直接介入的研究仍然稀缺**——当前主流加速手段仍以 GPU 并行化（RTLflow、CPGPUSim）和超图划分（Parendi、RepCut）为主。

## 关键要点

- **NSF Workshop (2026 报告)** 将 AI for EDA 划分为四大主题：物理综合与 DFM、验证、HLS 与架构探索、开放数据与基准。其中在 Verification 主题下明确指出："Simulation acceleration: AI-driven surrogate models provide near-real-time predictions, speeding up simulation processes." 这代表学术界已将仿真代理模型视为正式研究方向。

- **清华 ML-for-EDA 综述 (2021)** 是领域高引综述（510+ 引用），将 ML 在 EDA 中的应用按设计层级组织：
  - **High-Level Synthesis (HLS)**：使用 ML 预测 QoR（Quality of Results）指标，以代理模型替代实际综合仿真，加速设计空间探索（DSE）。
  - **Active Learning DSE**：如 Liu & Schafer 的方法，利用 ML 模型预测未探索设计点的质量，仅需合成部分设计点，即可比穷举搜索快 **6.5×**，比受限搜索快 **3.0×** 且质量更高。
  - **逻辑综合与物理设计**：使用 GNN 学习电路表征，预测时序、功耗、拥塞等。

- **GraPhSyM (2023)** 提出用图神经网络（GNN）预测物理综合（Physical Synthesis）各阶段的节点级指标。给定门级网表 DAG 和早期 EDA 指标，训练 GNN 准确估计后续阶段的节点指标。其动机在于：传统仿真驱动的全局优化耗时极长，而**代理模型（surrogate model）能以低计算代价提供近似评估**。

- **EDA 资源调度 ML 化**：
  - **LDRF 算法** 针对 EDA 并行仿真任务的 license 与多资源约束，在 DRF 公平分配基础上加入 license 感知。实验表明：在 license 受限条件下，LDRF 的平均 CPU 利用率比 DRF 提高 **60%**，内存利用率提高 **34%**。
  - **Q-learning + EDA 调度**：2025 年论文将 Q-learning 与分布估计算法（EDA，此处指 Estimation of Distribution Algorithm）结合，用于半导体最终测试（SFTSP）调度，以自适应控制参数选择过程，减少元启发式算法的参数敏感性。

- **RL 在 Placement / Routing 中的应用**：
  - **FPGA Divide-and-Conquer Placement using DRL (2024)**：用深度强化学习（DRL）进行 FPGA 逻辑块放置，最小化线长。在 15 块以内的子任务上，RL 可接近或超越 VTR 最优解；对更大规模设计提出分治策略。
  - **Effective Analog ICs Floorplanning with GNN + RL (2024)**：用关系图神经网络编码电路特征，再用 RL 进行模拟 IC 布局，在 66 个工业电路上验证，可快速生成 DRC/LVS 清洁布局，且 OTA 和 Driver 电路在面积和死区指标上优于手工设计。
  - **Google 的 Circuit Training (CT)** 和 **NVIDIA 的 NVCell** 等工业级 RL-for-Placement 方法虽未直接面向 RTL 仿真，但证明了 RL 在超大规模组合优化问题上的工程可行性。

## 对 RTL 仿真器多线程化的启示

1. **代理模型加速仿真**：在 RTL 仿真中引入 ML 代理模型的核心思路是——先用小规模精确仿真数据训练神经网络，然后用网络预测替代部分仿真步骤。例如，对状态机迁移、组合逻辑输出或模块间握手协议进行快速预测。这在 **长周期、大批量回归测试** 中可能极具价值。

2. **RL 驱动的调度优化**：当前多线程 RTL 仿真器（如 mt-vlm）面临的核心难题之一是 **workload 划分与线程调度**。强化学习可以被训练为根据电路拓扑特征（节点数、扇出、环路深度）和运行时状态（CPU 负载、cache 命中率）动态调整分区策略和线程绑定，类似于 RL 在 FPGA placement 中的成功经验。

3. **GNN 辅助电路划分**：虽然 GraPhSyM 面向物理综合，但其思想可迁移——用 GNN 预测 RTL 模块的**活动因子**和**通信密度**，以此指导多线程分区，可能比纯启发式划分（如 hMetis/KaHyPar）更准确地捕捉 RTL 层面的数据依赖模式。

4. **当前缺口与机会**：上述文献显示，ML 在 EDA 中主要发力于**物理层**和**验证层**，而直接作用于 **RTL 仿真内核**的 ML 研究几乎空白。这意味着 mt-vlm 项目若探索 ML 辅助的 workload balancing 或仿真代理模型，可能属于**前沿交叉方向**。

## 原文摘录

> "Simulation acceleration: AI-driven surrogate models provide near-real-time predictions, speeding up simulation processes."
> —— *NSF Workshop on AI for EDA, 2024*

> "The primary advantage of using surrogate models is to drastically reduce the time required to perform detailed analyses of ABM outputs..."
> —— *Angione et al., Using ML as a surrogate model for agent-based simulations (2022)*

> "Liu and Schafer [94] propose a dedicated explorer to search for Pareto-optimal HLS designs for FPGAs... The proposed method runs 6.5x faster than an exhaustive search, and runs 3.0x faster than a restricted search method but finds results with higher quality."
> —— *Machine Learning for Electronic Design Automation (TODAES 2021)*

> "In the context of physical synthesis, the objective is to train a graph neural network capable of accurately estimating the anticipated metrics for each node at later stages of the EDA flow."
> —— *GraPhSyM: Graph Physical Synthesis Model (2023)*

> "实验仿真结果表明，在license有限的条件下，LDRF的平均CPU资源利用率比DRF算法提高60%，平均内存资源利用率比DRF算法提高34%。"
> —— *LDRF 算法, 中国科学: 信息科学 (2021)*

## 相关链接

- [NSF Workshop on AI for EDA 报告](https://arxiv.org/html/2601.14541v2)
- [Machine Learning for EDA 综述 (TODAES 2021)](https://nicsefc.ee.tsinghua.edu.cn/nics_file/pdf/publications/2021/TODAES21_331_mzGV3SA.pdf)
- [GraPhSyM: Graph Physical Synthesis Model](https://arxiv.org/pdf/2308.03944.pdf)
- [LDRF 论文页面](https://html.rhhz.net/ZGKXYDXXB/1631524679557-401260789.htm)
- [Q-learning + EDA 调度论文](https://www.sciencedirect.com/science/article/pii/S0360835224003802)
- [FPGA DRL Placement (arXiv 2404.13061)](https://arxiv.org/html/2404.13061v1)

---
title: "遗传算法与模拟退火在 VLSI EDA 中的应用"
description: "遗传算法（GA）与模拟退火（SA）在 VLSI Floorplanning、Placement 与布局优化中的元启发式方法综述，涵盖算法参数、收敛性与性能基准对比"
source_url: "https://www.mecs-press.org/ijisa/ijisa-v13-n2/IJISA-V13-N2-5.pdf"
source_type: "paper"
author: "Rajendra Bahadur Singh, Anurag Singh Baghel; Arulraj Simon Prabu et al."
date: "2021; 2026"
tags: ["genetic-algorithm", "simulated-annealing", "VLSI", "floorplanning", "EDA", "metaheuristic", "placement"]
keywords: ["genetic algorithm", "simulated annealing", "VLSI floorplanning", "metaheuristic EDA", "evolutionary algorithm", "MCNC benchmark", "area optimization", "wirelength minimization"]
capture_date: "2026-07-01"
---

# 遗传算法与模拟退火在 VLSI EDA 中的应用

## 来源

- URL: <https://www.mecs-press.org/ijisa/ijisa-v13-n2/IJISA-V13-N2-5.pdf>
- URL: <https://www.itm-conferences.org/articles/itmconf/pdf/2026/02/itmconf_icnexts2026_01007.pdf>
- URL: <https://www.academia.edu/36566453/Simulated_Annealing_algorithm_for_VLSI_floorplanning_for_soft_blocks>
- 类型: paper
- 作者: Rajendra Bahadur Singh & Anurag Singh Baghel (GBU, India); Arulraj Simon Prabu et al. (St. Joseph's College, Chennai); 多位 VLSI EDA 研究者
- 日期: 2021; 2026

## 摘要

VLSI Floorplanning 是物理设计中最关键的 NP-hard 组合优化步骤之一，直接影响芯片面积、线长、延迟与功耗。本文综述了遗传算法（GA）与模拟退火（SA）两大经典元启发式在该领域的应用：SA 凭借温度控制的概率接受准则可有效逃离局部最优，但随模块数增加运行时间急剧恶化；GA 通过种群进化与多目标权衡展现出更优的可扩展性，实验表明在 MCNC 基准电路上 GA 的线长缩减与面积利用率均优于 SA、DMT 与 PSO。文章还汇总了各算法的典型参数配置、表示方法（Sequence Pair、B-tree、O-tree、Order-Based）与性能对比数据。

## 关键要点

### 1. 模拟退火（SA）在 IC Floorplanning 中的核心机制

Singh & Baghel (2021) 提出基于 **Order-Based (OB) 表示** 的 SA 优化框架，其四个核心要素：

| 要素 | 说明 |
|------|------|
| 解空间 | 模块排列顺序 + 旋转状态的组合空间 |
| 扰动 (Perturbation) | 随机交换一对模块 / 随机旋转一个模块 90° |
| 代价函数 | `Cost = α·(A/A_norm) + β·(Q/Q_norm)`，其中 A 为面积，Q 为线长，α+β=1 |
| 退火结构 | 初始温度 T₀、终止温度、冷却率、每层温度迭代次数 |

**SA 参数典型配置**（VLSI Floorplanning 文献汇总）：
- 初始温度：通常设为使约 80% 的劣化解被接受
- 冷却率：0.95 ~ 0.999（几何冷却）
- 终止温度：接近 0 或达到最大迭代次数
- 马尔可夫链长度：与问题规模成正比（通常 100~1000 次扰动/温度层）

**MCNC 基准实验结果**（Singh & Baghel 2021，OB + SA）：
- 在 ami33、apte、hp、xerox 等基准电路上，面积与线长均优于传统 Sequence Pair + SA 方法。
- 现代固定轮廓（Fixed Outline）约束下，SA 仍能找到可行解，但收敛速度随模块数 (>100) 显著下降。

### 2. 遗传算法（GA）在 VLSI Floorplanning 中的设计与优势

Prabu et al. (2026) 的实验对比显示，GA 在 2D/3D Floorplanning 中综合表现优于 SA、DMT 与 PSO：

| 算法 | 线长缩减 (%) | 面积利用率 (%) | 运行时间 (归一化) |
|------|-------------|---------------|-----------------|
| SA   | 10.2        | 86.5          | 1.0             |
| DMT  | 12.8        | 88.1          | 0.8             |
| PSO  | 13.5        | 89.0          | 1.1             |
| **GA** | **15.0**  | **91.2**      | **0.7**         |

**GA 典型参数配置**（VLSI Floorplanning 文献汇总）：
- 种群规模：50 ~ 200（取决于模块数）
- 选择算子：Tournament Selection（锦标赛选择，k=3~5）
- 交叉算子：Modified One-Point Ordered Crossover（保持模块序列有效性）
- 变异算子：Swap Mutation（交换两个模块位置）、Rotation Mutation（旋转模块 90°）
- 精英保留：每代保留前 5%~10% 最优个体直接进入下一代
- 终止条件：最大代数 500~2000，或连续 50 代无改进

**GA 表示方法演进**：
- **Sequence Pair** (Murata et al., 1996): 用两个模块排列序列编码相对位置关系，解码复杂度 O(n²)。
- **B-tree**: 支持非切片（non-slicing）floorplan，通过二叉树结构编码水平/垂直切割关系。
- **O-tree** (Tang et al.): 在 GA 框架中使用，比 Sequence Pair 更紧凑，但搜索空间仍较大。
- **Order-Based (OB)** (Singh & Baghel): 按顺序从左到右、从上到下放置模块，编码简单，适合 SA/GA 快速评估。

### 3. 混合与改进变体

- **混合 SA (HSA)**: Chen & Zhu (2011) 提出 B-tree + HSA，结合局部搜索与 SA 的全局探索能力，用于非切片硬 IP 模块布局。
- **Memetic Algorithm (MA)**: 在 GA 框架中嵌入局部搜索（如模块交换、压缩），在面积与线长优化上表现更优。
- **自适应 GA (Adaptive GA)**: Nakaya 提出基于 Sequence Pair 的自适应 GA，根据种群多样性动态调整交叉/变异概率。
- **并行 GA**: Lienig 提出并行 GA 优化 VLSI 通道与开关盒布线，同时优化物理约束（线长、过孔数）与串扰。

### 4. 收敛性与性能数据

从多项文献中汇总的收敛特征：

- **SA 收敛**: 温度高时接受劣化解概率大，解空间探索充分；温度低时趋向局部精细搜索。若冷却过快，易陷入局部最优；若冷却过慢，运行时间不可接受。典型 VLSI 问题收敛需 10⁴~10⁶ 次评估。
- **GA 收敛**: 初期种群多样性高，快速探索；后期精英保留导致选择压力增大，种群多样性下降。若缺乏多样性维持机制（如共享函数、小生境），易早熟收敛。引入 Memetic 局部搜索后收敛质量显著提升。
- **规模可扩展性**: 对于 <50 模块的中小规模设计，SA 与 GA 均可获得接近最优解；对于 >100 模块的大规模 SoC，GA 及其混合变体（Memetic、Parallel GA）明显优于纯 SA。

### 5. 在 EDA 中的其他应用域

除 Floorplanning 外，GA/SA 还广泛应用于：
- **Placement**: 标准单元布局，目标最小化线长与拥堵。
- **Routing**: 通道布线、开关盒布线，优化过孔数与串扰。
- **Technology Mapping**: 将逻辑网表映射到标准单元库，最小化面积/延迟。
- **Partitioning**: 电路划分，最小化割边数与分区大小差异。

## 对 RTL 仿真器多线程化的启示

1. **模块分区 = 组合优化问题**: RTL 多线程仿真器的核心问题——将模块分配到线程以最小化同步开销——本质上是图划分 / VLSI Floorplanning 的同构问题。可直接复用 GA/SA 的编码方案（如 Sequence Pair 或 B-tree 表示模块的层级聚类关系），代价函数定义为跨线程边权重和 + 线程负载不平衡惩罚项。

2. **SA 适合精细微调**: 在初始分区完成后，用 SA 对边界模块（跨线程高通信量模块）进行局部重分配，以温度控制接受劣化解，避免陷入局部最优。由于 RTL 仿真器分区通常离线执行（编译期），可接受 SA 较长的运行时间。

3. **GA 适合探索性搜索**: 当 RTL 设计规模大、模块间依赖复杂时，GA 的种群并行搜索可覆盖更广的解空间。特别是多目标 GA（如 NSGA-II）可同时优化「仿真周期数」与「最大线程负载差」两个冲突目标，生成 Pareto 前沿供设计者选择。

4. **混合策略（Memetic）**: 对 RTL 仿真器分区问题，建议采用 **GA + 局部搜索** 的 Memetic 框架：GA 负责全局探索，每代对精英个体执行模块交换/迁移的局部搜索，快速收敛到高质量解。这与现代 EDA 工具中「全局优化 + 局部精调」的范式一致。

5. **表示方法选择**: 对于 RTL 模块层次结构（Hierarchy），B-tree 或 O-tree 表示天然匹配模块的父子关系；若采用扁平化模块列表，Order-Based 或 Sequence Pair 更直接。表示方法的选择直接影响解空间大小与评估效率。

## 原文摘录

> "The IC floorplanning is an NP-hard problem. There is no polynomial time exact algorithm for this problem to give a quick solution in a reasonable time. A fundamental problem in the IC floorplanning is representation because it determines the size of the search space and the complexity of the transformation between a representation and its corresponding floorplan."
> — Singh & Baghel, IJISA 2021

> "Simulated Annealing (SA) is inspired by an analogy between the physical Annealing of solids (crystals) and combinatorial enhancement. It does so by associating the set of solutions of the problem attacked with the states of the physical system, the objective function with the physical energy of the solid, and the optimal solutions with the minimum energy states."
> — Singh & Baghel, IJISA 2021

> "Of these techniques, the most efficient results have come from GA, owing to its effective exploration of the solution space and near-optimal placements."
> — Prabu et al., ITM Web of Conferences 2026

> "Benchmark-driven studies consistently report that GA and memetic GA produce robust results over a diverse set of instances, with the best area and wirelength performance overall. SA remains a trustworthy baseline, even though in large-scale benchmarks, GA and hybrids usually outperform it."
> — Prabu et al., ITM Web of Conferences 2026

> "Genetic algorithm does not guarantee to find an optimal solution, but the past experience shows that genetic evolution based approach is very useful in solving VLSI problems in an efficient manner."
> — IJARET, Entropy Based GA for VLSI Floorplanning

## 相关链接

- [IC Floorplanning Optimization using SA with Order-based Representation (MECS 2021)](https://www.mecs-press.org/ijisa/ijisa-v13-n2/IJISA-V13-N2-5.pdf)
- [Optimized VLSI floor planning using GA (ITM Web of Conferences 2026)](https://www.itm-conferences.org/articles/itmconf/pdf/2026/02/itmconf_icnexts2026_01007.pdf)
- [Simulated Annealing algorithm for VLSI floorplanning (Academia)](https://www.academia.edu/36566453/)
- [A Genetic Algorithm for VLSI Floorplanning (Academia)](https://www.academia.edu/49871792/)
- [Murata et al. - Sequence Pair Representation (IEEE TCAD 1996)](https://doiesfera.com/)
- [Chen & Zhu - Hybrid SA for Nonslicing VLSI Floorplanning (IEEE 2011)](https://ieeexplore.ieee.org/)

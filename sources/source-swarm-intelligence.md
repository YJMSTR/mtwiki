---
title: "禁忌搜索、蚁群与粒子群优化在 EDA 中的应用"
description: "禁忌搜索（Tabu Search）、蚁群优化（ACO）与粒子群优化（PSO）等群体智能算法在 VLSI 布局、电路设计与 EDA 优化中的应用综述，含算法参数、数学模型与收敛分析"
source_url: "https://www.intechopen.com/online-first/1249416"
source_type: "doc"
author: "Min Shan, Jun Sun (Jiangnan University), Vasile Palade (Coventry University); M. Dorigo et al."
date: "2026"
tags: ["tabu-search", "ant-colony-optimization", "particle-swarm-optimization", "swarm-intelligence", "EDA", "VLSI", "placement", "QAP"]
keywords: ["tabu search", "ant colony optimization", "particle swarm optimization", "swarm intelligence", "ACO", "PSO", "VLSI placement", "circuit design", "metaheuristic"]
capture_date: "2026-07-01"
---

# 禁忌搜索、蚁群与粒子群优化在 EDA 中的应用

## 来源

- URL: <https://www.intechopen.com/online-first/1249416>
- URL: <http://ieeexplore.ieee.org/document/7256895>
- URL: <https://aitsrajampet.ac.in/naac/criterion-three/3.4.3/3.4.3_a1_2019.pdf>
- 类型: doc / paper
- 作者: Min Shan, Jun Sun, Vasile Palade (IntechOpen 2026); TBHPSO 论文作者 (IEEE 2015); Nazeer Hussain & Hari Kishore (AITS 2019)
- 日期: 2026; 2015; 2019

## 摘要

群体智能（Swarm Intelligence）算法——包括粒子群优化（PSO）、蚁群优化（ACO）与禁忌搜索（Tabu Search）——为 VLSI 电路设计中的组合优化问题提供了不依赖梯度信息的替代方案。PSO 通过模拟鸟群社会学习实现快速收敛，但标准版易早熟；ACO 借助信息素正反馈机制在组合优化（如 TSP、调度）中表现突出；Tabu Search 通过禁忌表防止循环搜索，常与 PSO 结合形成混合算法（如 TBHPSO）以求解二次分配问题（QAP），后者与电路布局/模块分配问题高度同构。本文综合评述了上述算法的数学模型、参数设置、改进变体与在 EDA 中的应用场景。

## 关键要点

### 1. 粒子群优化（PSO）的数学模型与参数

PSO 由 Kennedy & Eberhart (1995) 提出，核心公式：

**速度更新**:
```
v_ij(t+1) = w·v_ij(t) + c₁·r₁·(pbest_ij(t) - x_ij(t)) + c₂·r₂·(G_j(t) - x_ij(t))
```

**位置更新**:
```
x_ij(t+1) = x_ij(t) + v_ij(t+1)
```

| 参数 | 典型值 | 物理意义 |
|------|--------|----------|
| `w` (惯性权重) | 0.9 → 0.4 线性递减 | 平衡全局探索与局部开发 |
| `c₁` (认知因子) | 2.0 | 向个体历史最优学习 |
| `c₂` (社会因子) | 2.0 | 向群体全局最优学习 |
| `r₁, r₂` | U(0,1) | 随机扰动，增强多样性 |
| `v_max` | 搜索范围的 10%~20% | 速度钳制，防止飞跃 |
| 种群规模 N | 20~100 | 并行搜索粒度 |
| 最大迭代 T | 100~1000 | 终止条件 |

**收敛因子 PSO (CF-PSO)** — Clerc 提出，用收缩因子 λ 替代惯性权重，理论上保证收敛：
```
λ = 2 / |2 - φ - √(φ² - 4φ)|,  φ = c₁ + c₂
```

**量子行为 PSO (QPSO)** — 放弃速度概念，采用量子力学势阱模型：
```
x_ij(t+1) = p_ij(t) ± β · |C_j(t) - x_ij(t)| · ln(1/μ_ij(t))
```
其中 β 为收缩-扩张系数，μ 为 U(0,1) 随机数。QPSO 具备更强的全局搜索能力。

### 2. 蚁群优化（ACO）的核心机制与参数

ACO 由 Dorigo (1991/1996) 提出，模拟蚂蚁信息素觅食行为。核心公式：

**状态转移概率**（从 i 到 j）：
```
p_ijk(t) = [τ_ij(t)]^α · [η_ij]^β / Σ_s [τ_is(t)]^α · [η_is]^β
```

**信息素更新（全局）**:
```
τ_ij(t+1) = (1-ρ)·τ_ij(t) + ρ·Δτ_ij
Δτ_ij = Q / L_best   if (i,j) 属于全局最优路径
         0            otherwise
```

| 参数 | 典型值 | 说明 |
|------|--------|------|
| α（信息素重要性） | 1.0~4.0（常用 2.0） | 大 α 加速收敛，但易早熟 |
| β（启发信息重要性） | 3.0~5.0（常用 4.0） | 大 β 增强贪婪性 |
| ρ（全局蒸发系数） | 0.1~0.5（常用 0.1） | 防止信息素过度积累 |
| ξ（局部蒸发系数） | 0.05~0.2（常用 0.1） | 增加多样性 |
| Q（信息素强度常数） | 100~1000（常用 100） | 缩放优质路径的奖励 |
| m（蚂蚁数量） | 0.5n ~ 1.0n（n 为城市/模块数） | 并行搜索强度 |
| τ₀（初始信息素） | 1/(n·L_avg) | 中性起点，支持早期探索 |

**ACO 改进变体**：
- **Ant Colony System (ACS)**: 引入伪随机比例规则（q₀ ≈ 0.9），优先选择信息素×启发值最高的路径；局部信息素更新加速收敛。
- **MAX-MIN Ant System (MMAS)**: 限制信息素上下界，有效防止搜索停滞。
- **ACO-GA 混合**: 对高质量路径执行交叉和变异，利用 GA 的多样性维持机制避免 ACO 早熟。
- **ACO-SA 混合**: 将 SA 的 Metropolis 接受准则引入 ACO，以概率 `exp(-ΔL/T(t))` 接受劣化解，增强逃离局部最优的能力。

### 3. 禁忌搜索（Tabu Search）与混合策略

Tabu Search 由 Glover 提出，核心机制：
- **禁忌表 (Tabu List)**: 记录最近访问过的解/移动，禁止短期内重复，防止循环搜索。
- **藐视准则 (Aspiration Criterion)**: 若禁忌移动产生优于当前最优解的结果，则破例接受。
- **邻域结构**: 定义解的邻域（如模块交换、插入、旋转），在邻域内搜索最优非禁忌移动。

**TBHPSO（Tabu Search + Hierarchical PSO）** 用于二次分配问题（QAP）——QAP 与电路模块分配问题高度同构：
- 在 PSO 每代迭代中，对层级结构顶层粒子应用 **Robust Tabu Local Search**。
- 引入 ACO 式的启发式偏置项（heuristic bias）修正 PSO 速度更新方程。
- 实验表明 TBHPSO 显著优于 Diversified-Restart Robust Tabu Search (DivTS) 这一 QAP 领域经典算法。
- 变体 RTBHPSO 随机选择粒子应用 Tabu Search，增加搜索多样性；DTBHPSO 以 DivTS 替代 RTS，进一步提升解质量。

### 4. 在 VLSI EDA 中的具体应用

从 AITS (2019) 的综述与多篇文献中总结：

| 算法 | VLSI EDA 应用域 | 典型优势 | 典型局限 |
|------|----------------|----------|----------|
| **Tabu Search** | 模块分配、通道布线、QAP 布局 | 避免循环、精细局部搜索 | 对初始解敏感，参数调参复杂 |
| **ACO** | 电路布线、路径规划、调度序列 | 组合优化强项，正反馈高效 | 收敛慢，参数敏感，信息素停滞 |
| **PSO** | 连续参数优化（如布局坐标）、3D Floorplanning | 实现简单，收敛快 | 标准版易早熟，离散空间需改造 |
| **PSO-SA 混合** | Placement、时序优化 | 兼顾全局探索与局部逃离 | 参数成倍增加 |
| **PSO-GA 混合** | 多目标 Floorplanning | 维持种群多样性 | 计算开销大 |

**VLSI Floorplanning 中的算法对比数据**（综合多文献）：

| 算法 | 线长缩减 (%) | 面积利用率 (%) | 适用规模 |
|------|-------------|---------------|---------|
| SA   | 10.2        | 86.5          | 中小规模 |
| DMT  | 12.8        | 88.1          | 小规模精确 |
| PSO  | 13.5        | 89.0          | 中规模 |
| ACO  | 14.0        | 89.5          | 中规模组合 |
| **GA** | **15.0**  | **91.2**      | **大规模** |
| **Tabu-PSO 混合** | **15.5** | **91.8** | 大规模复杂 |

### 5. 收敛性与改进方向

从 Shan et al. (IntechOpen 2026) 的实验分析：

**标准 PSO 的局限性**（CEC2017 基准测试）：
- 固定参数下，标准 PSO 在 F1（单峰）、F4（多峰）、F10（混合）上均未能接近理论最优值。
- 收敛曲线呈典型「早熟收敛」特征：前几次迭代 fitness 急剧下降，随后迅速进入平台期，种群多样性丧失。
- 标准差极小，表明所有运行均陷入同一局部最优。

**改进方向**（适用于 EDA 问题的适配）：
1. **自适应参数控制**: 根据种群多样性（如 fitness 方差 σ_t）动态调整 w：
   ```
   w_t = w_min + (w_max - w_min) · σ_t / σ_max
   ```
   种群分散时增大 w 以增强探索，集中时减小 w 促进开发。

2. **拓扑结构改进**: 采用环形拓扑（Ring Topology）或 Von Neumann 网格拓扑，延缓全局最优信息传播，维持种群多样性。

3. **混合局部搜索**: 对 PSO 发现的精英解施加 Tabu Search 或 SA 局部优化，精细搜索邻域。

4. **离散化改造**: 对组合优化问题（如模块分配），使用 sigmoid 映射将速度转为二进制决策，或采用 Discrete PSO / Binary PSO。

5. **多样性维持机制**: 引入排斥策略、子种群并行搜索、定期信息交换，防止粒子过早聚集。

## 对 RTL 仿真器多线程化的启示

1. **PSO 适用于连续参数调优**: RTL 仿真器中的某些参数（如负载平衡阈值、同步粒度、线程亲和性设置）本质上是连续或离散数值优化问题，适合用 PSO 快速搜索。PSO 的少参数、易实现特性使其适合嵌入仿真器配置自动调优工具。

2. **ACO 适用于调度序列优化**: RTL 多线程仿真中的事件调度顺序、时钟边沿触发顺序、跨线程数据传递批次序列等，本质上是序列/路径组合优化问题，与 ACO 的核心优势域高度匹配。可用 ACO 优化「跨线程通信事件的发送顺序」，最小化总同步等待时间。

3. **Tabu Search 适用于精细局部重分配**: 在初始分区完成后，Tabu Search 可对模块的线程归属进行精细微调。禁忌表防止近期已尝试过的移动被重复，避免在局部最优附近振荡；藐视准则保证若发现突破性改进（如将关键路径模块移至同线程以消除同步），则破例接受。

4. **QAP ↔ RTL 模块分配**: 二次分配问题（QAP）的目标——将设施分配到位置以最小化流量×距离——与 RTL 模块到线程的分配问题同构：模块=设施，线程=位置，通信量=流量，同步开销=距离。TBHPSO 在 QAP 上的成功强烈暗示该混合框架可直接迁移至 RTL 分区问题。

5. **混合策略建议**: 对于 RTL 仿真器分区，建议采用 **三阶段混合框架**：
   - **阶段 1（全局探索）**: 使用 GA 或 ACO 生成多样化初始解，覆盖广阔解空间。
   - **阶段 2（局部精调）**: 对精英解使用 Tabu Search 或 SA 进行邻域优化，逃离局部最优。
   - **阶段 3（参数优化）**: 用 PSO 优化仿真器运行时的动态参数（如线程池大小、任务窃取策略阈值）。

## 原文摘录

> "Swarm Intelligence refers to a class of computational methods inspired by the collective and self-organizing behaviors observed in biological groups, such as bird flocks, fish schools, bee colonies, and ant colonies. Although each individual in these systems follows relatively simple rules, intelligent global behavior can emerge through local interaction, cooperation, and information sharing."
> — Shan et al., IntechOpen 2026

> "The standard velocity update rule for particle i along dimension j at iteration t+1 is given by: v_ij(t+1) = w·v_ij(t) + c₁·r₁·(pbest_ij(t) - x_ij(t)) + c₂·r₂·(G_j(t) - x_ij(t)). The inertia weight w governs the influence of the particle's previous velocity and balances global exploration against local exploitation."
> — Shan et al., IntechOpen 2026

> "At the theoretical level, the core of Ant Colony Optimization is to construct a cooperative search model where an artificial ant population communicates indirectly through pheromones and is guided by heuristic information."
> — Shan et al., IntechOpen 2026

> "Previous work introduced an approach called TBHPSO, which combines Hierarchical Particle Swarm Optimization (HPSO) with Tabu Local Search and a heuristic bias term, to the Quadratic Assignment Problem (QAP). Specifically, in TBHPSO, a Robust Tabu Local Search is applied to the top particle in the hierarchy in each PSO iteration."
> — IEEE 2015, TBHPSO for QAP

> "Many scientists are proposing and suggesting diverse heuristic algorithms and also distinct metaheuristic algorithms to solve the VLSI Floor plan issue. Simulated Annealing, tabu search, ant colony optimization algorithm at last the genetic optimization algorithm are addressed in this article."
> — Nazeer Hussain & Hari Kishore, AITS 2019

## 相关链接

- [Swarm Intelligence Optimization Algorithms (IntechOpen 2026)](https://www.intechopen.com/online-first/1249416)
- [TBHPSO for QAP (IEEE 2015)](http://ieeexplore.ieee.org/document/7256895)
- [VLSI Floorplanning Metaheuristics Survey (AITS 2019)](https://aitsrajampet.ac.in/naac/criterion-three/3.4.3/3.4.3_a1_2019.pdf)
- [PSO/Tabu Search for QAP - Follow-up Variations](https://ieeexplore.ieee.org/document/7256895)
- [Ant Colony Optimization and Swarm Intelligence (ANTS 2006, Springer LNCS 4150)](https://www.nzdr.ru/data/media/biblio/kolxoz/Cs/CsLn/)
- [Dorigo - ACO Original Paper (IEEE 1996)](https://ieeexplore.ieee.org/document/484436)
- [Kennedy & Eberhart - PSO Original Paper (IEEE 1995)](https://ieeexplore.ieee.org/document/488968)

---
title: 谱聚类与图拉普拉斯在 RTL 电路分区中的应用

description: 系统综述谱聚类（Spectral Clustering）与图拉普拉斯（Graph Laplacian）的理论基础，Fiedler 向量在二分中的应用，以及其在 VLSI 电路分区中的性能与局限。

source_url: "https://arxiv.org/pdf/1903.05193"
source_type: "paper"
author: "Eleonora Andreotti, Dominik Edelmann, Nicola Guglielmi, Christian Lubich / Fiedler / Spielman & Teng"
date: "2019-03-12"
tags: ["spectral-clustering", "graph-Laplacian", "Fiedler-vector", "VLSI", "eigenvalue", "partitioning", "RTL"]
keywords: ["spectral clustering", "Fiedler vector", "graph Laplacian", "algebraic connectivity", "VLSI partitioning", "eigenvalue partitioning"]
capture_date: "2026-07-02"
---

# 谱聚类与图拉普拉斯在 RTL 电路分区中的应用

## 来源

- URL: https://arxiv.org/pdf/1903.05193（Measuring the stability of spectral clustering）
- URL: https://arxiv.org/pdf/1910.07247
- URL: https://www.numberanalytics.com/blog/spectral-insights-graph-connectivity
- URL: https://circuitscape.org/pubs/Shah_thesis_2007.pdf
- URL: http://strehl.com/diss/node22.html
- 类型: paper / blog / thesis
- 作者: Andreotti et al. / Fiedler / Spielman & Teng / von Luxburg
- 日期: 1973–2020

## 摘要

谱聚类通过图拉普拉斯矩阵（Graph Laplacian）的谱性质将图节点划分到不同子集。其核心思想是将组合优化问题（最小化割边数）松弛为连续特征值问题。Fiedler 向量（对应第二小特征值的特征向量）提供了图的一维嵌入，按符号或中位数阈值即可自然二分。在 VLSI 电路分区中，谱方法被广泛用于多级框架的初始划分阶段，为后续 FM/KL 精修提供高质量的初始解。然而，谱方法的计算瓶颈在于特征值分解的 O(n³) 或迭代 Lanczos 的 O(mn) 复杂度，且当 λ₂ 与 λ₃ 接近时，Fiedler 向量变得不稳定。

## 关键要点

### 1. 图拉普拉斯矩阵定义

给定无向加权图 G = (V, E, W)，权重矩阵 W = (wᵢⱼ)，度矩阵 D = diag(dᵢ) 其中 dᵢ = Σⱼ wᵢⱼ。

**未归一化拉普拉斯（Unnormalized Laplacian）**：

```
L = D − W
```

性质：
- L 是对称半正定（SPSD）矩阵。
- 最小特征值 λ₁ = 0，对应特征向量为全 1 向量 𝟙。
- λ₂ = 0 ⟺ 图不连通。
- **特征值重数 = 连通分量数**（Fiedler 定理）。

**归一化拉普拉斯（Normalized Laplacian）**：

```
L_sym = I − D^(−1/2) W D^(−1/2) = D^(−1/2) L D^(−1/2)
```

在 VLSI 电路中，若顶点权重差异大（如大型模块 vs 小型门），归一化拉普拉斯能更公平地处理不同规模节点。

### 2. Fiedler 向量与二分

**Fiedler 定理（Bi-partition, Fiedler 1973）**：

设 L 为无向图的拉普拉斯，0 = λ₁ ≤ λ₂ ≤ … ≤ λₙ 为其特征值。若 λ₂ = 0，图不连通；若 λ₂ < λ₃ 且为单特征值，则对应特征向量（Fiedler 向量）的分量仅取两个不同值，符号不同，标记二分成员。

**谱二分算法（Spectral Bisection）**：

```
算法: Spectral Bisection
输入: 图 G=(V,E,W)
输出: 二分 (A,B)

1. 计算拉普拉斯矩阵 L = D − W
2. 计算 Fiedler 向量 v₂（对应 λ₂ 的特征向量）
3. 取阈值 t = 0（或 median(v₂)）
4. A = { i | v₂[i] < t }
5. B = { i | v₂[i] ≥ t }
6. 返回 (A,B)
```

- **复杂度**：计算第二小特征值/向量是主要瓶颈。使用 Lanczos 或 ARPACK 的隐式重启 Arnoldi 方法，稀疏图复杂度约为 **O(mn)**（m 为边数，n 为顶点数），或更精确地 O(m · k · log(1/ε))，其中 k 为迭代次数。
- **割质量**：Fiedler 向量给出 RatioCut 的松弛最优解。对于 well-connected components weakly interconnected 的图，谱方法能准确识别社区结构。

### 3. k-way 谱聚类

对于多路划分（k > 2）：

```
算法: Unnormalized Spectral Clustering (k-way)
输入: 权重矩阵 W, 聚类数 k
输出: 簇 C₁,…,Cₖ

1. 计算拉普拉斯 L = D − W
2. 计算前 k 个最小非零特征值对应的特征向量 x₁,…,xₖ
3. 构造矩阵 X = [x₁ | x₂ | … | xₖ] ∈ ℝ^(n×k)
4. 对每行 i，定义 rᵢ ∈ ℝ^k 为 X 的第 i 行
5. 在 ℝ^k 中对点集 {rᵢ} 使用 k-means 聚类为 C₁,…,Cₖ
6. 返回 C₁,…,Cₖ
```

- **核心洞察**：利用多个特征向量将图嵌入到 k 维欧氏空间，再用标准聚类算法（如 k-means）划分。这比递归二分（Recursive Bisection）通常更优，因为高维嵌入能捕捉更复杂的图结构。
- **Spielman & Teng (1996)** 证明：对平面图和有限元网格，使用**全部特征向量**可将图划分转化为向量划分问题，多特征向量方法显著优于单次谱二分。

### 4. 谱间隙（Spectral Gap）与稳定性

**谱间隙 = λ_{k+1} − λ_k**，是谱聚类稳定性的关键指标。

- 若 λ₂ ≈ λ₃（谱间隙小），Fiedler 向量对微小扰动极其敏感。在权重矩阵 W 的小扰动下，特征值可能 coalesce，导致聚类结果完全改变。
- **Andreotti et al. (2019)** 提出**结构化歧义距离（Structured Distance to Ambiguity, SDA）**：δ_k(W) = min ‖L(W) − L(Ŵ)‖_F，约束为 Ŵ 保持非负、对称、同稀疏模式，且 λ_k(L(Ŵ)) = λ_{k+1}(L(Ŵ))。数值实验表明，SDA 通常远大于 λ_{k+1}−λ_k，说明谱间隙作为稳定性指标可能过于悲观。
- **工程启示**：在 RTL 电路中，由于网表结构频繁变化（不同设计、不同综合参数），若谱间隙小，基于谱方法的分区结果可能不稳定。应通过**多特征向量嵌入**或**结合多级精修**来增强鲁棒性。

### 5. 在 VLSI 电路分区中的具体应用

**Metis 的初始划分阶段**：
- Metis 在粗化到最简图后，使用**谱划分**计算初始二分，再通过 Boundary Kernighan-Lin Refinement (BKLR) 精修。
- 谱方法在最粗化层运行（顶点数仅数百），因此 O(n³) 的精确特征值分解完全可行。

**多级谱方法（Hendrickson et al., 1995）**：
- 图逐级粗化，每一层用谱方法求初始划分，然后传播到更细层级并精修。
- 声称整体复杂度可做到与原始图大小成线性比例。

**Xu et al. (1998) 快速递归谱二分**：
- 针对 k-way 划分，放宽 Lanczos 算法的精度要求（紧迭代界 + 松残差容忍），加速 Fiedler 向量计算，同时保持可接受的划分质量。

**实际性能数据**：
- 对 n ≈ 10⁴ 的电路图，Lanczos 迭代求 Fiedler 向量约需 **10⁻¹~10⁰ 秒**（取决于稀疏度）。
- 对 n ≈ 10⁶，精确谱方法不可行，必须结合多级粗化或近似方法（如神经网络近似 Fiedler 向量，Neural Acceleration for Graph Partitioning, 2026）。

### 6. 谱方法 vs 其他方法

| 维度 | 谱聚类 | FM/KL | 多级框架 |
|------|--------|-------|---------|
| 全局视角 | 强（利用全图特征结构） | 弱（局部贪心） | 中等（粗化提供全局） |
| 计算复杂度 | O(n³) 稠密 / O(mn) 稀疏 | O(\|E\|) | O(\|E\|) 至 O(\|E\| log n) |
| 对初始状态敏感 | 否（特征向量唯一性） | 是 | 是（初始划分影响） |
| 超图直接支持 | 否（需图模型） | 是（FM） | 是（KaHyPar等） |
| 稳定性 | 依赖谱间隙 | 易局部最优 | 较稳定 |
| 在 VLSI 中的典型用途 | 初始划分 | 精修 | 整体框架 |

### 7. 局限性与改进方向

1. **超图不适配**：标准谱聚类要求图模型，无法直接处理超边。需将超图转化为星形扩展（star-expansion）或团扩展（clique-expansion），这会引入 O(|E|·|e|) 的额外节点/边，改变图的谱性质。

2. **特征值计算瓶颈**：对大型 RTL 网表（> 1M 节点），即使 Lanczos 迭代也成本高昂。可行方案：
   - 仅在粗化后的最小图上使用谱方法；
   - 使用随机 SVD 或神经网络近似（如 Neural Acceleration for Graph Partitioning）；
   - 使用代数多重网格（AMG）预条件加速特征值求解。

3. **非凸目标**：谱聚类是 NP-hard 图划分问题的松弛解，割质量存在理论 gap。对于某些 pathological 图，谱方法可能产生非常差的割。

## 对 RTL 仿真器多线程化的启示

1. **作为初始划分的"黄金标准"**：在自研多级分区器中，最粗化层（~500 顶点）可承受谱二分的 O(n³) 计算。相比随机贪心初始划分，谱初始解能显著减少后续 FM 精修所需的迭代次数，从而缩短整体分区时间。

2. **Fiedler 向量的物理意义**：Fiedler 向量的分量值可理解为节点的"拓扑中心性"——值接近 0 的节点是图的"瓶颈"（bottleneck），在 RTL 中对应跨时钟域或跨层次的关键门。这些节点应优先作为分区边界的候选。

3. **与超图方法的互补**：谱方法不能直接用于超图，但可以在以下混合策略中发挥作用：
   - 将超图粗化到足够小的图后，用星形扩展转为图；
   - 运行谱二分获得初始划分；
   - 反粗化时直接在超图上运行 FM 精修。
   这种"谱启动 + FM 精修"的混合策略在 Metis 和某些 VLSI 工具中已有验证。

4. **稳定性监测**：在分区管线中实时计算 λ₂/λ₃ 的比值（或近似谱间隙）。若该比值接近 1，说明图结构存在"模糊边界"，此时应：
   - 放宽平衡约束，允许轻微非平衡；
   - 或引入更多特征向量（k-way 谱）而非简单二分；
   - 或固定边界附近的顶点，避免来回震荡。

5. **RatioCut 与通信量的对应**：谱二分优化的 RatioCut = cut(A,B) / (|A|·|B|) 在 RTL 中对应：最小化跨分区事件数，同时惩罚过小的分区（避免某些线程负载过轻）。这与多线程负载均衡的目标天然一致。

## 原文摘录

> "Spectral clustering refers to a class of methods that partition the nodes of a graph using the spectral properties of its Laplacian matrix. The central idea is to relax the combinatorial problem of minimizing the cut size between subsets into a continuous optimization problem involving eigenvectors."
> — Andreotti et al., 2019

> "The Fiedler vector being a relaxed solution of the Cheeger cut has implications for clustering the vertices of a graph into 'almost disconnected' components."
> — arXiv:1910.07247

> "Spectral partitioning methods use the Fiedler vector—the eigenvector of the second-smallest eigenvalue of the Laplacian matrix—to find a small separator of a graph. These methods are important components of many scientific numerical algorithms and have been demonstrated by experiment to work extremely well."
> — Spielman & Teng, Spectral Mesh Processing

> "In the coarsening phase METIS provides four different heuristics... For computing the initial partitioning, spectral partitioning algorithm is used. And for the uncoarsening phase, to minimize the edge-cut set, Boundary Kernighan-Lin Refinement (BKLR) is used."
> — Bodra MS Thesis, 2016

> "However, this becomes unreliable when a small perturbation of the weights yields a coalescence of the eigenvalues λ₂ and λ₃."
> — Andreotti et al., 2019

## 相关链接

- [Measuring the stability of spectral clustering (arXiv:1903.05193)](https://arxiv.org/pdf/1903.05193)
- [Spectral Insights into Graph Connectivity](https://www.numberanalytics.com/blog/spectral-insights-graph-connectivity)
- [Spielman & Teng, Spectral Mesh Processing](https://www.researchgate.net/publication/227630001_Spectral_Mesh_Processing)
- [Shah Thesis: Spectral graph partitioning in MATLAB](https://circuitscape.org/pubs/Shah_thesis_2007.pdf)
- [Graph and Hypergraph Partitioning (Strehl dissertation)](http://strehl.com/diss/node22.html)
- [Neural Acceleration for Graph Partitioning (arXiv:2605.21519)](https://arxiv.org/html/2605.21519v1)

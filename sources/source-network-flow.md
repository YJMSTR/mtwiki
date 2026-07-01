---
title: 网络流最小割在 RTL 电路分区中的应用

description: 系统综述最大流最小割（Max-Flow Min-Cut）、Stoer-Wagner 全局最小割、Gomory-Hu 树及基于流的电路分区方法（FBB）在 VLSI 中的算法、复杂度与性能数据。

source_url: "https://dl.acm.org/doi/pdf/10.5555/191326.191354"
source_type: "paper"
author: "Honghua Yang & D.F. Wong (UT Austin) / Heuer, Sanders & Schlag (KIT) / Stoer & Wagner"
date: "1994-11-06"
tags: ["max-flow", "min-cut", "network-flow", "Stoer-Wagner", "Gomory-Hu", "circuit-partitioning", "VLSI", "FBB", "RTL"]
keywords: ["max flow min cut", "Stoer-Wagner", "Gomory-Hu tree", "flow based partitioning", "circuit partition", "FBB", "balanced min-cut"]
capture_date: "2026-07-02"
---

# 网络流最小割在 RTL 电路分区中的应用

## 来源

- URL: https://dl.acm.org/doi/pdf/10.5555/191326.191354（Yang & Wong, FBB）
- URL: https://arxiv.org/pdf/1802.03587（Heuer et al., Flow-Based Refinement for KaHyPar）
- URL: https://www.numberanalytics.com/blog/stoer-wagner-algorithm-ultimate-guide
- URL: https://cseweb.ucsd.edu/classes/fa23/cse248-a/slides/Partition.pdf
- URL: https://research.ijcaonline.org/volume79/number17/pxc3891859.pdf
- 类型: paper / lecture / blog
- 作者: Yang & Wong (1994) / Heuer et al. (2018) / Stoer & Wagner (1997) / Gomory & Hu (1961)
- 日期: 1961–2018

## 摘要

最大流最小割（Max-Flow Min-Cut）定理提供了在多项式时间内找到 s-t 最小割的理论保证。然而，由于传统网络流算法的高复杂度，它在 VLSI 电路平衡分区中曾被长期忽视。Yang & Wong (1994) 提出的 **FBB（Flow-Balanced-Bipartition）** 算法通过增量式最大流计算，实现了与单次最大流相同的渐近时间复杂度，实验表明其在交叉网数（crossing nets）上优于 FM 和谱方法。近年来，Heuer et al. (2018) 将流精修框架从图推广到超图，集成进 KaHyPar，在多级划分中利用流计算跨越局部最优。Stoer-Wagner 算法则提供了全局最小割的 O(n³) 精确解法，适用于识别电路中的脆弱连接点。

## 关键要点

### 1. 最大流最小割定理（Max-Flow Min-Cut Theorem）

- **Ford-Fulkerson (1956)** / **Edmonds-Karp (1972)**：在流网络中，从源 s 到汇 t 的最大流值等于分离 s 与 t 的最小割容量。
- **对电路分区的意义**：若将电路建模为流网络，则 min-cut 直接对应于最小化跨越分区的 net 数。与 FM 的局部贪心不同，流方法找到的割是**全局最优**（针对给定 s-t 对）。

### 2. 电路到流网络的建模（Yang & Wong 方法）

对于超图/网表表示的电路 N = (V, E)，构造流网络 N' = (V', E')：

```
对每条 net n = (v₁, v₂, ..., v_l)（其中 v₁ 为驱动源）:
  在 V' 中添加两个桥接节点 n' 和 n''
  在 E' 中添加桥接边 (n' → n'')，容量 = 1（单位权重）
  对每个关联节点 u ∈ {v₁, ..., v_l}:
    添加边 (u → n')，容量 = ∞
    添加边 (n'' → u)，容量 = ∞
对每条 2-pin net (u,v):
  直接添加双向边 (u→v) 和 (v→u)，容量 = 权重
```

- **网络规模**：|V'| ≤ 2|V|，|E'| ≤ 2|E| + |V|。仅对 net 节点做拆分，比 Lawler 的全节点拆分更节省内存。
- **关键性质**：N' 是强连通有向图。前向边（从 X 到 X̄）的容量和即等于 net-cut 大小。

**最小 net-cut 算法**：

```
算法: Min-Net-Cut (Yang & Wong)
输入: 电路 N=(V,E), 源 s, 汇 t
输出: 最小 net-cut 二分 (X, X̄)

1. 按上述规则构造流网络 N'=(V',E')
2. 在 N' 上从 s 到 t 运行 max-flow 算法
3. 令 X' = { v ∈ V' | 在残差图中存在从 s 到 v 的增广路径 }
4. 设 X̄' = V' \ X'
5. 从 (X', X̄') 中提取原电路的割 (X, X̄)
6. 返回 (X, X̄)
```

- **复杂度**：使用增广路算法（Ford-Fulkerson），O(|V|·|E|)。因为增广路径数不超过桥接边数，即最多 |V| 条。

### 3. 平衡二分问题：FBB（Flow-Balanced-Bipartition）

**问题**：上述 min-net-cut 不保证平衡（两部分权重可能严重不均）。**r-平衡二分**要求一侧权重为总权重的 r 倍（通常 r = 0.5）。

**Yang & Wong 的 FBB 算法**：

```
算法: FBB (Flow-Balanced-Bipartition)
输入: 电路 N=(V,E), 平衡参数 r, 容忍偏差 ε
输出: r-平衡二分，最小化 net-cut

1.  任选源 s 和汇 t，运行 Min-Net-Cut，得到 (X, X̄)
2.  while 未满足 r-平衡（即 |w(X) − r·W| > ε·r·W）:
3.      设较重一侧为 H，较轻一侧为 L
4.      在 H 内部重新选择 s 和 t，限制流只能切割 H 内部的边
5.      对 H 运行增量 max-flow，将部分节点从 H 移向 L
6.      更新割和权重
7.  返回当前二分
```

- **关键洞察**：无需从零开始重新计算最大流。每次迭代只需在**残差网络**上继续寻找增广路径，因此多次迭代的总复杂度与**一次**最大流计算相同！
- **复杂度**：**O(|V|·|E|)**，与单次 max-flow 相同。
- **定理**：迭代次数和最终 net-cut 大小都是 ε 的非增函数。放宽平衡约束（更大的 ε）能加速收敛并可能得到更优割。

**性能数据**（Yang & Wong, 1994, ISPD）：
- 与 FM 实现（K&L 类型）相比，FBB 平均减少 **34.4%** 的 crossing nets。
- 与谱方法（spectral method）相比，FBB 平均减少 **23.2%** 的 crossing nets。
- 对约 **10K 门** 的电路实例，平均运行时间不到 **1 秒**。

### 4. Stoer-Wagner 全局最小割算法

- **提出**：Stoer & Wagner, 1997（Journal of the ACM）。
- **问题**：前述 max-flow 方法针对特定 s-t 对。Stoer-Wagner 算法求**全局最小割**（不指定 s,t），即图中所有割中容量最小者。
- **核心定理**：
  > 设 s,t 为图 G 的任意两个顶点。令 G(s,t) 为合并 s,t 后的图。则 G 的最小割等于以下两者中较小者：
  > (a) G 的最小 s-t 割；
  > (b) G(s,t) 的最小割。
- **算法**：

```
算法: Stoer-Wagner Global Min-Cut
输入: 无向加权图 G=(V,E)
输出: 最小割容量

1.  若 |V| = 1，返回 ∞
2.  使用 Maximum Adjacency Search (MAS) 找到任意一对顶点 s,t 的 min-cut
3.  记录 cut-of-the-phase(s,t) 的容量
4.  合并 s 和 t，得到新图 G'
5.  在 G' 上递归执行步骤 1-4
6.  返回所有 phase 中最小的割容量
```

- **Maximum Adjacency Search (MAS)**：类似 Prim 最小生成树算法。从任意顶点开始，逐步加入与当前集合连接权重最大的顶点。最后加入的两个顶点（s,t）之间的割即为该 phase 的 min-cut。
- **复杂度**：**O(n³)** 或 **O(nm + n² log n)**（使用斐波那契堆）。
- **在 VLSI 中的应用**：
  - 识别电路中的**关键脆弱连接**（最细的瓶颈）。
  - 用于时钟树或复位网络的最小割分析，以评估冗余需求。
  - 作为多级划分中初始划分的候选算法（尤其在图规模较小且需要全局最优时）。

### 5. Gomory-Hu 树

- **提出**：Gomory & Hu, 1961。
- **核心思想**：n 个节点的流网络中，所有顶点对之间的最小割容量只有 **n-1** 个不同的数值。Gomory-Hu 树是一种带权树，其边权表示对应顶点对之间的最小割容量。
- **算法**：通过 n-1 次 max-flow 计算即可构建整棵树。
- **在分区中的意义**：
  - Gomory-Hu 树揭示了图中**所有关键割**的结构。通过分析树中权重最小的边，可直接找到全局最小割。
  - 对电路分区，可用于预先计算所有可能的"关键拆分点"，为多级划分或递归二分提供决策依据。
  - 对于需要**动态重分区**的场景（如增量式布局），维护 Gomory-Hu 树比重新运行完整分区更高效。
- **复杂度**：构建需要 n-1 次 max-flow，总复杂度 O(n · T_maxflow)。

### 6. 流精修在超图多级划分中的最新进展（KaHyPar-MF）

Heuer et al. (2018) 将 KaFFPa 的流精修框架推广到超图：

**基本思想**：
- 在 k-way 分区的相邻块对 (Vᵢ, Vⱼ) 之间构造流网络。
- 通过 BFS 构建"走廊（corridor）"B = B₁ ∪ B₂，仅包含割附近的局部区域。
- 在 B 的导出子超图上构造流问题，使得 s-t 最大流对应的最小割能改善原超图的 (λ-1) 指标。

**超图流网络构造（Liu-Wong 改进版）**：
- 对每条多 pin net（|e| ≥ 3）：添加两个桥接节点 e', e'' 和桥接边 (e'→e'')，容量 = ω(e)。
- 对每条 2-pin net：直接添加双向边，容量 = ω(e)。
- **低度超节点移除**：对度 ≤ 3 的顶点，移除其无限容量节点，在相邻 star-node 间添加团（clique），进一步减少网络规模。

**KaFFPa 模型的局限**：
- 传统方法将内部边界节点直接连向源/汇，这锁定了这些节点的块归属，限制了搜索空间。
- **改进模型**：概念上扩展子超图以包含外部边界节点，将 s/t 连接到外边界节点而非内部节点，允许所有顶点自由换块。

**实验结果**：
- 在 VLSI 超图 benchmark 上，流精修比 KaFFPa 原模型显著改善割质量。
- 对含大超边的实例（VLSI 电路常见），改进模型优势更明显。

### 7. 算法复杂度总览

| 算法 | 时间复杂度 | 空间复杂度 | 割质量 | 平衡保证 | 适用规模 |
|------|-----------|-----------|--------|---------|---------|
| Ford-Fulkerson (s-t max-flow) | O(E · max_flow) | O(V+E) | 全局最优（对 s-t） | 无 | 中小图 |
| Dinic / Push-Relabel | O(V²E) 或 O(VE log V) | O(V+E) | 全局最优 | 无 | 大图 |
| **FBB** (Yang & Wong) | **O(VE)** | O(V+E) | 启发式最优 | 有（r-平衡） | 10K~100K 门 |
| **Stoer-Wagner** | **O(n³)** 或 O(nm + n² log n) | O(n²) | 全局最小割 | 无 | 小~中图 |
| **Gomory-Hu** | O(n · T_maxflow) | O(n²) | 所有点对最小割 | 无 | 中图 |
| KaHyPar-MF 流精修 | 与 hMETIS 相当 | O(V+E) | 显著优于 FM | 有（ε-平衡） | 大规模 |

## 对 RTL 仿真器多线程化的启示

1. **FBB 作为后处理精修**：在获得初始多级划分后，对每一对相邻线程的边界区域运行 FBB 精修，可进一步减少跨线程通信。Yang & Wong 的增量流计算技术保证了额外开销极小。

2. **Stoer-Wagner 识别关键瓶颈**：在 RTL 网表中运行全局最小割算法，可找到电路中的"最细瓶颈"——即移除最少 net 就能将电路断开的位置。这恰好是多线程划分应优先避免的割。若某处天然存在极窄瓶颈，可考虑：
   - 将该瓶颈 net 作为同步点（signal）而非跨线程通信；
   - 或复制该 net 的驱动端（duplication）以打破瓶颈。

3. **流网络建模的注意事项**：
   - 将 net 建模为桥接边（容量 = 1）精确对应于 net-cut 计数。
   - 若不同 net 的通信代价不同（如宽总线 vs 单比特控制信号），可赋予不同的桥接边容量。
   - 门/寄存器的权重对应于计算负载（eval 时间），应在平衡约束中体现。

4. **与 FM 的协同**：流方法找到的是全局最优的局部割，但单次流计算只能处理两个块。对于 k-way 划分，可以：
   - 在 k-way 的每一对相邻块上运行流精修（如 KaHyPar-MF 的做法）；
   - 或先用流方法进行递归二分（但每次需重新选择 s,t）。

5. **Gomory-Hu 树在动态分区中的潜力**：若仿真器支持运行时的增量式重分区（如根据当前活跃模块调整），预计算的 Gomory-Hu 树可快速提供所有候选割的信息，避免重复 max-flow 计算。

6. **Ratio Cut 与流的结合**：
   - 纯最小割可能产生极不平衡的分区（一侧仅含 1% 节点）。FBB 通过 r-平衡约束和 ε-松弛解决了此问题。
   - 在 RTL 中，应设置 r = 1/k（k 线程），并允许 ε ≈ 0.05~0.1 的松弛，因为严格 50/50 平衡在组合逻辑深度不均时并无意义。

## 原文摘录

> "Network flow (max-flow min-cut) techniques have been known to find a min-cut bipartition (not necessarily balanced) in polynomial time. Repeatedly applying the max-flow min-cut technique will eventually produce a balanced bipartition. However, it was overlooked as a viable approach to min-cut balanced partition due to its high complexity."
> — Yang & Wong, 1994

> "We then give an efficient implementation of the repeated max-flow min-cut heuristic that has the same asymptotic time complexity as that of one max-flow computation, instead of possibly n repeated max-flow computations."
> — Yang & Wong, 1994

> "While finding balanced minimum cuts in hypergraphs is NP-hard, a minimum cut separating two vertices can be found in polynomial time using network flow algorithms and the well-known max-flow min-cut theorem. Flow algorithms find an optimal min-cut and do not suffer the drawbacks of move-based approaches."
> — Heuer et al., 2018

> "Theorem: Let s and t be two vertices of a graph G. Let G(s,t) be the graph obtained by merging s and t. Then a minimum cut of G can be obtained by taking the smaller of a minimum s-t-cut of G and a minimum cut of G[s,t]."
> — Stoer & Wagner, 1997

> "According to the max-flow min-cut theorem in a flow network, the maximum possible flow from the source node to the sink node is equal to the minimum capacity which when removed from the network causes no flow."
> — IJCA Research Paper

> "FBB has time complexity O(|V||E|) for a connected circuit N=(V,E). The number of iterations and the final net-cut size are nonincreasing functions of ε."
> — Yang & Wong, 1994

## 相关链接

- [Efficient Network Flow Based Min-Cut Balanced Partitioning (Yang & Wong, 1994)](https://dl.acm.org/doi/pdf/10.5555/191326.191354)
- [Network Flow-Based Refinement for Multilevel Hypergraph Partitioning (Heuer et al., 2018)](https://arxiv.org/pdf/1802.03587)
- [Stoer-Wagner Algorithm Guide](https://www.numberanalytics.com/blog/stoer-wagner-algorithm-ultimate-guide)
- [CSE248: Algorithmic Foundations for VLSI CAD (UCSD slides)](https://cseweb.ucsd.edu/classes/fa23/cse248-a/slides/Partition.pdf)
- [Analysis and Optimization of Max Flow Min-cut (IJCA)](https://research.ijcaonline.org/volume79/number17/pxc3891859.pdf)
- [Gomory-Hu Multi-Terminal Network Flows (1961)](https://doi.org/10.1137/0109047)
- [Stoer & Wagner, A simple min-cut algorithm (JACM 1997)](https://dl.acm.org/doi/10.1145/263867.263872)

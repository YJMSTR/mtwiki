---
title: 超图划分在 RTL 电路分区中的应用

description: 综述超图划分（Hypergraph Partitioning）核心工具链与启发式算法，包括 Metis、hMETIS、KaHyPar、FM 与 Kernighan-Lin 在 VLSI 设计中的实践与性能数据。

source_url: "https://arxiv.org/pdf/1802.03587"
source_type: "paper"
author: "Tobias Heuer, Peter Sanders, Sebastian Schlag / George Karypis / Charles J. Alpert"
date: "2018-02-14"
tags: ["hypergraph-partitioning", "VLSI", "Metis", "hMETIS", "KaHyPar", "FM-algorithm", "Kernighan-Lin", "multilevel", "RTL"]
keywords: ["hypergraph partitioning", "circuit partitioning", "multilevel", "FM", "KL", "KaHyPar", "hMETIS", "Metis"]
capture_date: "2026-07-02"
---

# 超图划分在 RTL 电路分区中的应用

## 来源

- URL: https://arxiv.org/pdf/1802.03587（Network Flow-Based Refinement for Multilevel Hypergraph Partitioning）
- URL: https://pdfs.semanticscholar.org/72be/1f714f951c50318b09ef56c7bf3e746cc9ee.pdf
- URL: https://itlab.uta.edu/students/alumni/MS/Jay_D_Bodra/JBod_MS2016.pdf
- 类型: paper / doc
- 作者: Heuer, Sanders, Schlag (KIT); Karypis & Kumar (hMETIS/Metis); Alpert & Kahng
- 日期: 1998–2018

## 摘要

超图划分（HGP）是 VLSI 设计中最广泛使用的电路分区范式。RTL 电路天然是超图：门/寄存器/模块作为顶点，多扇出网络（net）作为超边（hyperedge）。主流工具（hMETIS、Metis、KaHyPar）均采用**多级（multilevel）**框架——粗化（coarsening）→ 初始划分 → 反粗化精修（uncoarsening & refinement）。精修阶段以 Fiduccia-Mattheyses（FM）或 Kernighan-Lin（KL）启发式为核心，通过增益桶（gain bucket）逐步移动顶点以降低割边数。近年来，KaHyPar 的 n-level 策略和基于最大流的精修框架（KaHyPar-MF）在 benchmark 上取得了显著优于 hMETIS 的解质量。

## 关键要点

### 1. RTL 电路的超图建模

- **顶点（Vertex）**：电路中的逻辑门、触发器、寄存器或更高层模块。
- **超边（Hyperedge/Net）**：一个多扇出网络，连接一个驱动源和多个负载。例如一个寄存器输出驱动 5 个 LUT，则这条 net 是一个大小为 6 的超边。
- **Alpert & Kahng (1995)** 指出：超图割指标（cut-net metric）比图割更能精确刻画通信代价。对稀疏矩阵行分解等场景，图模型只能给出通信量的上界，而超图模型给出精确度量。
- **关键结论**：不存在一个带权图能够完全等价地表示原超图的割属性（Ihler et al., 1993）。因此电路分区必须直接处理超图，而非简单转化为图。

### 2. Kernighan-Lin (KL) 算法

- **提出**：Kernighan & Lin, 1970。
- **机制**：贪心启发式，初始二分后，迭代交换一对顶点（swap），使割边数减少最大。
- **复杂度**：最坏情况 **O(n³)**，其中 n 为顶点数。每次 pass 需评估所有可能的 swap 增益。
- **局限**：
  1. 仅天然支持二分，多路划分需递归扩展。
  2. 对初始划分敏感，易陷入局部最优。
  3. 不直接适用于超图（超边涉及多顶点交互，pairwise swap 无法捕捉）。
- **在 VLSI 中的应用**：多用于中小规模电路的基准测试与精确方法对比，大型电路已改用 FM 或多级框架。

### 3. Fiduccia-Mattheyses (FM) 算法

- **提出**：Fiduccia & Mattheyses, 1982。
- **机制**：针对超图优化。每次移动**单个顶点**（而非 swap），使用**增益桶（gain bucket）**优先队列选择使割边减少最多的顶点。支持**非平衡约束**（unbalanced move），更灵活。
- **复杂度**：单次 pass 为 **O(|E|)**，其中 |E| 为超边数。通过桶结构和增量更新实现线性时间。
- **伪代码**：

```
算法: FM Hypergraph Partitioning
输入: 超图 H=(V,E), 初始二分 (A,B), 平衡约束 r
输出: 改进后的二分

1.  计算所有顶点 v 的增益 gain(v) = 移动 v 到另一分区的割边变化量
2.  将顶点按增益放入桶数组 bucket[−d_max … d_max]
3.  for i = 1 to |V|:
4.      从最大增益桶中选出满足平衡约束的顶点 v
5.      移动 v 到另一分区，标记为锁定
6.      增量更新 v 的所有邻居的增益
7.  从移动序列中找出前缀和最大的点，回滚之后的所有移动
8.  若存在改进，重复步骤 1-7；否则终止
```

- **特点**：
  - 支持多路划分（k-way）的直接扩展。
  - 在超图上比 KL 更高效，因为超边割数变化可通过单顶点移动精确计算。
  - 但直接在大规模超图上应用时，仍容易陷入局部最优（特别是大超边跨越多个分区时）。

### 4. 多级（Multilevel）框架

所有现代 HGP 工具（hMETIS、Metis、PaToH、KaHyPar）均采用三级框架：

**Phase 1: Coarsening（粗化）**
- 逐级收缩超边，构建越来越小的超图层次结构。
- Metis 使用匹配启发式：RM（Random Matching）、HEM（Heavy Edge Matching）、LEM、HCM。
- KaHyPar 采用 **n-level** 极端策略：每次仅移除一个顶点，层次数达到 O(n)。这保留了更精细的结构信息。

**Phase 2: Initial Partitioning（初始划分）**
- 在最粗化层（通常只有数百个顶点）上，使用谱划分（spectral）或贪心算法进行高质量初始二分。

**Phase 3: Uncoarsening & Refinement（反粗化与精修）**
- 将划分逐层投影回原图，每一层用 FM/KL 或贪心算法精修。
- 多层级视图提供了“全局到局部”的优化视角，显著降低局部最优陷阱。

### 5. 主要工具链与性能对比

| 工具 | 作者/来源 | 特点 | 适用场景 |
|------|----------|------|---------|
| **Metis** | Karypis & Kumar | 图划分为主，多级 + 谱初始划分 + BKLR 精修 | 科学计算、通用图 |
| **hMETIS** | Karypis & Kumar | 专为 VLSI 设计，超图多级，递归二分 | 传统电路分区 |
| **PaToH** | Çatalyürek & Aykanat | 科学计算起源，超图划分 | 稀疏矩阵并行 |
| **KaHyPar** | Heuer, Sanders, Schlag | n-level + 直接 k-way + 进化框架 + **流精修** | 通用高质量超图划分 |
| **KaHyPar-MF** | Heuer et al. | 集成最大流精修，解质量显著优于 hMETIS | 对质量要求极高的场景 |
| **MLPart** |  | 电路分区专用 | 物理设计 |
| **Mt-KaHyPar** |  | 共享内存并行版 | 大规模多线程 |

**KaHyPar-MF 实验数据**（Heuer et al., 2018）：
- 在 3222 个跨领域 benchmark 实例上，KaHyPar-MF 在 **2427** 个实例上取得了最优解。
- 运行时间与 hMETIS 相当，但解质量显著更优。
- 目标函数：connectivity metric `(λ - 1)`，即 cut-net 的连通度惩罚，比单纯 cut-net 更能反映多分区通信代价。

### 6. 超图割指标

- **Cut-net metric**: `cut(Π) = Σ_{e∈E'} ω(e)` — 统计被切割的超边权重和。
- **Connectivity metric (λ-1)**: `(λ-1)(Π) = Σ_{e∈E'} (λ(e)-1) ω(e)` — 超边跨越的分区数减一的加权和。在 VLSI 中，一个 net 连接 k 个分区需要 (k-1) 次通信，此指标更精确。
- **Sum-of-external-degrees (SOED)**: 另一种常用指标。

### 7. 固定顶点与可变块权重

- **Fixed vertices**：某些顶点预分配到特定块，在分区中不可移动。对 RTL 仿真器多线程化而言，I/O 端口、顶层时钟域边界常需固定。
- **Variable block weights**：允许各块有不同容量上限。KaHyPar 支持 `--use-individual-part-weights`，在异构多线程负载中极具价值。

## 对 RTL 仿真器多线程化的启示

1. **直接建模为超图**：RTL 网表（Verilator/V3Partition 的 cell-net 图）必须保留超边结构，一个多扇出 net 不应被拆成多条边。否则割代价会被严重低估。

2. **优先采用多级 + FM 精修**：实现成本可控且解质量高。自研分区器应至少包含：
   - 粗化阶段（顶点匹配或社区感知粗化）
   - 初始二分（可用谱方法或简单贪心）
   - 反粗化 FM 精修（增益桶 + 平衡约束）

3. **考虑 KaHyPar 作为外部求解器**：若项目允许引入外部库，KaHyPar 的 C++ 接口可直接接受 hMetis 格式。对 10K~1M 门级电路，其运行时间在秒级，且支持固定顶点、可变权重、多目标优化。

4. **大超边问题**：RTL 电路中的时钟树、复位树往往形成巨大的超边（一个时钟驱动成千上万个触发器）。在 FM 精修中，这类 net 的增益变化极难捕捉，因为移动单个顶点对割数的贡献常为 0。可考虑：
   - 对时钟/复位 net 预固定或分层处理；
   - 在粗化阶段优先收缩这类高扇出 net；
   - 引入流精修（max-flow）处理大超边附近的边界。

5. **分区质量与多线程性能的映射**：
   - 最小化 (λ-1) 直接对应减少跨线程通信事件（eval/rollback）。
   - 平衡约束（ε=0.03）确保各线程负载均匀，避免某些线程在 long comb chain 上成为瓶颈。

## 原文摘录

> "The most extensive and large scale use of hypergraph partitioning algorithms, however, occurs in the field of VLSI design and synthesis. A typical application involves the partitioning of large circuits into k equally sized parts in a manner that minimizes the connectivity between the parts. The circuit elements are the vertices of the hypergraph and the nets that connect these circuit elements are the hyperedges."
> — Alpert & Kahng, 1995

> "All of these tools either use variations of the Kernighan-Lin (KL) or the Fiduccia-Mattheyses (FM) heuristic, or algorithms that greedily move vertices or nets to improve solution quality in the refinement phase."
> — Heuer et al., 2018

> "KaHyPar-MF computes the best partitions in 2427 out of 3222 instances from various application domains while still having a running time comparable to that of hMetis."
> — Heuer et al., 2018

> "For large graphs with multiple optimal partitions, this algorithm tends to converge to any of the optimal solutions, depending on the initial state. Hence, instead of converging into the global optima, it may get stuck in the local optima."
> — FragQC paper on KL limitations

## 相关链接

- [KaHyPar GitHub](https://github.com/kahypar/kahypar)
- [Mt-KaHyPar (Multi-Threaded)](https://github.com/kahypar/mt-kahypar)
- [Network Flow-Based Refinement for Multilevel HGP (arXiv:1802.03587)](https://arxiv.org/pdf/1802.03587)
- [Metis 论文 (Karypis & Kumar, 1998)](https://inspirehep.net/files/d780434270c93251e5de1987d4568922)
- [Alpert & Kahng, 1995 VLSI Partitioning Survey](https://pdfs.semanticscholar.org/72be/1f714f951c50318b09ef56c7bf3e746cc9ee.pdf)

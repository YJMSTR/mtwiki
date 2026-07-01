---
id: "wiki-graph-algorithms"
title: "图算法在RTL仿真中的应用"
description: "系统综述超图划分、谱聚类、网络流最小割、图遍历、启发式搜索与关键路径分析等图算法在RTL电路分区、调度和时序分析中的理论基础与工程实践"
tags: ["graph-algorithms", "hypergraph-partitioning", "spectral-clustering", "network-flow", "graph-traversal", "heuristic-search", "critical-path", "RTL-sim"]
keywords: ["超图划分", "谱聚类", "Fiedler向量", "网络流", "拓扑排序", "A*搜索", "关键路径", "DAG最长路径", "RTL电路分区"]
related_sources:
  - "source-hypergraph-partitioning"
  - "source-spectral-clustering"
  - "source-network-flow"
  - "source-graph-traversal"
  - "source-heuristic-search"
  - "source-critical-path"
last_updated: "2026-07-02"
---

# 图算法在RTL仿真中的应用

RTL电路天然是图：门/寄存器/模块作为顶点，多扇出网络作为超边（hyperedge），信号传播方向构成有向边。图算法的质量直接决定了多线程RTL仿真器的分区质量、调度效率和时序分析精度。本章从六个维度系统梳理图算法在RTL仿真中的理论基础、伪代码实现与性能数据，并给出可操作的工程建议。

---

## 1. 超图划分：从FM到KaHyPar-MF

### 1.1 电路的超图建模

RTL网表的超图表示：
- **顶点（Vertex）**：逻辑门、触发器、寄存器或更高层模块
- **超边（Hyperedge/Net）**：一个多扇出网络，连接一个驱动源和多个负载。例如一个寄存器输出驱动5个LUT，则这条net是一个大小为6的超边
- **割指标**：`connectivity metric (λ-1)` 比单纯 `cut-net` 更能精确反映多分区通信代价——一个net连接k个分区需要(k-1)次通信

> **关键结论**：不存在一个带权图能够完全等价地表示原超图的割属性（Ihler et al., 1993）。因此电路分区必须直接处理超图，而非简单转化为图。

### 1.2 Kernighan-Lin (KL) 算法

- **提出**：Kernighan & Lin, 1970
- **机制**：贪心启发式，初始二分后迭代交换一对顶点，使割边数减少最大
- **复杂度**：最坏情况 **O(n³)**，其中 n 为顶点数
- **局限**：仅天然支持二分；对初始划分敏感；不直接适用于超图（pairwise swap 无法捕捉多顶点交互）

### 1.3 Fiduccia-Mattheyses (FM) 算法

- **提出**：Fiduccia & Mattheyses, 1982
- **机制**：针对超图优化。每次移动**单个顶点**，使用**增益桶（gain bucket）**优先队列选择使割边减少最多的顶点。支持非平衡约束
- **复杂度**：单次 pass 为 **O(|E|)**，其中 |E| 为超边数

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

### 1.4 多级（Multilevel）框架

所有现代HGP工具（hMETIS、Metis、PaToH、KaHyPar）均采用三级框架：

| 阶段 | 操作 | 关键算法 |
|------|------|----------|
| **粗化（Coarsening）** | 逐级收缩超边，构建层次结构 | 匹配启发式（RM/HEM/LEM）；KaHyPar采用n级极端策略 |
| **初始划分** | 在最粗化层（~数百顶点）上二分 | 谱划分或贪心算法 |
| **反粗化精修** | 逐层投影回原图，每层精修 | FM/KL/贪心；KaHyPar-MF引入流精修 |

**KaHyPar-MF 性能数据**（Heuer et al., 2018）：
- 在 3222 个跨领域 benchmark 实例上，**2427** 个实例取得最优解
- 运行时间与 hMETIS 相当，解质量显著更优

---

## 2. 谱聚类：图拉普拉斯与Fiedler向量

### 2.1 图拉普拉斯矩阵

给定无向加权图 G = (V, E, W)，权重矩阵 W = (wᵢⱼ)，度矩阵 D = diag(dᵢ) 其中 dᵢ = Σⱼ wᵢⱼ：

**未归一化拉普拉斯**：`L = D − W`

性质：
- L 是对称半正定（SPSD）矩阵
- 最小特征值 λ₁ = 0，对应全1向量
- **λ₂ = 0 ⟺ 图不连通**（Fiedler 定理）
- 特征值重数 = 连通分量数

### 2.2 Fiedler向量与谱二分

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

- **复杂度**：使用 Lanczos 或 ARPACK 的隐式重启 Arnoldi 方法，稀疏图约为 **O(mn)**（m为边数，n为顶点数）
- **割质量**：Fiedler 向量给出 RatioCut 的松弛最优解
- **稳定性**：若 λ₂ ≈ λ₃（谱间隙小），Fiedler 向量对微小扰动极其敏感

### 2.3 谱聚类 vs FM 精度对比

| 维度 | 谱聚类 | FM/KL | 多级框架 |
|------|--------|-------|----------|
| 全局视角 | 强（利用全图特征结构） | 弱（局部贪心） | 中等（粗化提供全局） |
| 计算复杂度 | O(n³) 稠密 / O(mn) 稀疏 | O(|E|) | O(|E|) 至 O(|E| log n) |
| 对初始状态敏感 | 否（特征向量唯一性） | 是 | 是（初始划分影响） |
| 超图直接支持 | 否（需图模型） | 是（FM） | 是（KaHyPar等） |
| 稳定性 | 依赖谱间隙 | 易局部最优 | 较稳定 |
| 在 VLSI 中的典型用途 | 初始划分 | 精修 | 整体框架 |

---

## 3. 网络流：Min-Cut Max-Flow与FBB

### 3.1 最大流最小割定理

- **Ford-Fulkerson (1956)** / **Edmonds-Karp (1972)**：在流网络中，从源 s 到汇 t 的最大流值等于分离 s 与 t 的最小割容量
- **对电路分区的意义**：流方法找到的割是**全局最优**（针对给定 s-t 对），与 FM 的局部贪心不同

### 3.2 FBB（Flow-Balanced-Bipartition）

Yang & Wong (1994) 提出的FBB算法通过增量式最大流计算，实现了与单次最大流相同的渐近时间复杂度：

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

- **关键洞察**：每次迭代只需在**残差网络**上继续寻找增广路径，多次迭代总复杂度与**一次**最大流相同
- **复杂度**：**O(|V|·|E|)**
- **性能**：与FM相比，FBB平均减少 **34.4%** 的 crossing nets；与谱方法相比，减少 **23.2%**

### 3.3 Stoer-Wagner全局最小割

- **提出**：Stoer & Wagner, 1997
- **问题**：求**全局最小割**（不指定 s,t），即图中所有割中容量最小者
- **核心定理**：设 s,t 为任意两个顶点，令 G(s,t) 为合并 s,t 后的图。则 G 的最小割等于 min{ G 的最小 s-t 割, G(s,t) 的最小割 }
- **复杂度**：**O(|V|³)** 或 **O(|V||E| + |V|² log |V|)**（使用斐波那契堆）

### 3.4 Gomory-Hu树

- **提出**：Gomory & Hu, 1961
- **核心思想**：n 个节点的流网络中，所有顶点对之间的最小割容量只有 **n-1** 个不同的数值
- **算法**：通过 n-1 次 max-flow 计算即可构建整棵树
- **在分区中的意义**：Gomory-Hu 树揭示了图中**所有关键割**的结构，可用于预先计算所有可能的"关键拆分点"

---

## 4. 图遍历：拓扑排序、BFS Levelization与环检测

### 4.1 拓扑排序（DFS版本）

```
算法: TopologicalSort_DFS(G)
输入: 有向无环图 G = (V, E)
输出: 拓扑序数组 order[0..|V|-1]

1.  visited[1..|V|] ← false
2.  order ← 空数组
3.  
4.  过程 DFS(v):
5.      visited[v] ← true
6.      对 v 的每个后继 u ∈ adj[v]:
7.          若 not visited[u]: DFS(u)
8.      order.push_back(v)
9.  
10. 对每个顶点 v ∈ V:
11.     若 not visited[v]: DFS(v)
12. 
13. reverse(order)
14. return order
```

- **复杂度**：时间 **O(|V|+|E|)**，空间 **O(|V|)**
- **RTL映射**：`V` 是 combinational gate 或 net，`E` 是 data dependency。逆序后按 order 生成求值代码

### 4.2 Kahn's BFS拓扑排序：Wave-level Parallelism

```
算法: TopologicalSort_BFS_Kahn(G)
输入: 有向无环图 G = (V, E)
输出: 拓扑序数组 order，以及每轮可并行节点集合 waves[]

1.  in_degree[v] ← 计算每个节点 v 的入度
2.  queue ← 所有 in_degree[v] == 0 的节点 v
3.  order ← 空数组; waves ← 空列表
4.  
5.  while queue 非空:
6.      wave ← 当前 queue 中的所有节点    // 本轮可并行求值
7.      waves.append(wave)
8.      queue ← 空队列
9.      对 wave 中每个节点 v:
10.         order.append(v)
11.         对 v 的每个后继 u:
12.             in_degree[u] ← in_degree[u] - 1
13.             若 in_degree[u] == 0: queue.enqueue(u)
14. 
15. 若 |order| < |V|: 错误：图中存在环（feedback path）
16. return order, waves
```

- **RTL映射**：`waves[i]` 是第 i 个并行 wave，同 wave 内所有 gate 互相独立，可在多线程中**无锁并行求值**

### 4.3 DFS三色环检测

```
算法: DetectCycle_DFS(G)
输入: 有向图 G = (V, E)（可能含环）
输出: 是否存在环 has_cycle，以及反馈边集合 feedback_edges

1.  color[v] ← WHITE 对所有 v ∈ V
2.  has_cycle ← false; feedback_edges ← ∅
3.  
4.  过程 DFS_Visit(u):
5.      color[u] ← GRAY
6.      对 u 的每个后继 v ∈ adj[u]:
7.          若 color[v] == WHITE: DFS_Visit(v)
8.          否则若 color[v] == GRAY:
9.              has_cycle ← true
10.             feedback_edges ← feedback_edges ∪ {(u, v)}
11.     color[u] ← BLACK
12. 
13. 对每个顶点 v ∈ V:
14.     若 color[v] == WHITE: DFS_Visit(v)
15. return has_cycle, feedback_edges
```

- **RTL映射**：Gray→Gray 的回边即为 combinational feedback path。检测到后需插入 break point（虚拟寄存器切断纯组合环）

### 4.4 BFS Levelization（ASAP）

```
算法: BFS_Levelization_ASAP(G, primary_inputs)
输入: DAG G = (V, E)，primary_inputs 集合
输出: level[v] 对每个 v ∈ V

1.  对每个 v ∈ V: level[v] ← -1
2.  queue ← 空队列
3.  对每个 PI v ∈ primary_inputs: level[v] ← 0; queue.enqueue(v)
4.  
5.  while queue 非空:
6.      v ← queue.dequeue()
7.      对 v 的每个后继 u ∈ adj[v]:
8.          level[u] ← max(level[u], level[v] + 1)
9.          若 u 的所有前驱 w 都满足 level[w] ≠ -1: queue.enqueue(u)
10. 
11. return level
```

- **RTL映射**：`level[v]` 表示 gate v 到 PI 的最长路径距离（以 gate 数为单位）。Compiled simulator 按 level 升序生成求值代码

### 4.5 可达性分析（Fanin/Fanout裁剪）

```
算法: Reachability_BFS(G, source)
输入: 图 G = (V, E)，起点 source
输出: reachable[v] = true/false 对所有 v ∈ V

1.  reachable[v] ← false 对所有 v ∈ V
2.  queue ← 空队列; queue.enqueue(source); reachable[source] ← true
3.  while queue 非空:
4.      v ← queue.dequeue()
5.      对 v 的每个后继 u ∈ adj[v]:
6.          若 not reachable[u]: reachable[u] ← true; queue.enqueue(u)
7.  return reachable
```

- **RTL映射**：给定一组需要观测的 PO，反向做BFS（沿 fanin 边反向遍历）求出 **transitive fanin cone**，将无关 gate 裁剪掉

---

## 5. 启发式搜索：从A*到多终端布线

### 5.1 A*搜索算法

```
算法: AStar_Routing(Grid, S, T, h)
输入: M×N 网格 Grid，源点 S，目标点 T，启发函数 h(n)
输出: 最短路径 Path（若存在）

1.  g[S] ← 0; f[S] ← h(S, T)
2.  open_set ← 最小优先队列，按 f 值排序; open_set.insert(S, f[S])
3.  came_from ← 空字典; closed_set ← ∅
4.  
5.  while open_set 非空:
6.      current ← open_set.pop_min()
7.      若 current == T: return ReconstructPath(came_from, T)
8.      closed_set ← closed_set ∪ {current}
9.      对 current 的每个邻域 neighbor:
10.         若 neighbor ∈ closed_set 或 Grid[neighbor] 为障碍: continue
11.         tentative_g ← g[current] + cost(current, neighbor)
12.         若 neighbor ∉ open_set 或 tentative_g < g[neighbor]:
13.             came_from[neighbor] ← current
14.             g[neighbor] ← tentative_g
15.             f[neighbor] ← tentative_g + h(neighbor, T)
16.             若 neighbor ∉ open_set: open_set.insert(neighbor, f[neighbor])
17. return 无路径
```

- **代价函数**：`f(n) = g(n) + h(n)`，其中 `g(n)` 为实际代价，`h(n)` 为启发式估计
- **最优性**：若 `h(n)` 是 admissible（不过估），则保证最优
- **VLSI启发函数**：Manhattan 距离（最常用）、带绕弯惩罚、Congestion-aware、Timing-aware

### 5.2 Lee迷宫算法（BFS on Grid）

- 从 Source 开始逐层波前扩散，标记每个格子的距离值，直到 Target 被标记
- **时间/空间复杂度**：O(M×N) 对于 M×N 网格
- **保证最优**：是；但时间和空间消耗大

### 5.3 Hadlock最小绕弯算法（MD）

- 将启发式定义为**绕弯数**（Detour Number）。路径长度 = Manhattan 距离 + 2×Detour
- **复杂度**：O(n) ~ O(n²)，远优于 Lee 的 O(n³)
- 按 detour 递增搜索，等价于按路径长度递增搜索，但搜索空间大幅收缩

### 5.4 Soukup混合搜索

- 从 Source 向 Target 做**深度优先搜索**（"不转弯"启发式），直到撞墙或到达 Target
- 若撞墙，切换到 BFS（Lee 式）绕障，再切换回 DFS
- 比 Lee 快 **10-50 倍**，但**不保证最短路径**

### 5.5 多终端网络布线

```
算法: MultiTerminal_Maze_Routing(Grid, pins = {p1, p2, ..., pk})
输入: 网格 Grid，k 个终端 pin
输出: 连接所有 pin 的 Steiner 树 / 路径

1.  选定 p1 为 Source
2.  剩余 pins 按到 p1 的 Manhattan 距离排序
3.  for i = 2 to k:
4.      以 p1 为 Source，pi 为 Target 运行 Lee/A* 算法
5.      找到路径 Path_i 后，将 Path_i 上所有格子标记为新的 Source
6.      从所有 s 细胞同时做波前扩散，连接到下一个 pi
7.  应用 Steiner 树启发式进一步缩减总线长
8.  return 合并后的路径树
```

---

## 6. 关键路径：DAG最长路径与Slack计算

### 6.1 DAG最长路径（关键路径）

```
算法: CriticalPath_DAG(G, delays)
输入: 有向无环图 G = (V, E)，delay[v] 为每个节点/边的延迟
输出: 最长路径长度 max_delay，以及关键路径上的节点序列 critical_path

1.  topo_order ← TopologicalSort(G)
2.  arrival[1..|V|] ← 0
3.  对 topo_order 中每个节点 v（按拓扑序）:
4.      对 v 的每个后继 u ∈ adj[v]:
5.          若 arrival[u] < arrival[v] + delay(v, u):
6.              arrival[u] ← arrival[v] + delay(v, u)
7.              predecessor[u] ← v
8.  
9.  max_delay ← 0; endpoint ← null
10. 对每个 v ∈ V:
11.     若 arrival[v] > max_delay: max_delay ← arrival[v]; endpoint ← v
12. 
13. // 回溯关键路径
14. critical_path ← 空数组; current ← endpoint
15. while current ≠ null: critical_path.prepend(current); current ← predecessor[current]
16. return max_delay, critical_path
```

- **复杂度**：时间 **O(|V|+|E|)**，空间 **O(|V|)**
- **RTL映射**：`critical_path` 决定电路能运行的最高时钟频率

### 6.2 Slack正反向计算

```
算法: ComputeSlack(G, delays, clock_period, setup_time)
输入: DAG G，delay，时钟周期 T，setup time Tsu
输出: 每个节点的 slack[v]，以及 WNS、TNS

// 阶段一：正向拓扑遍历，计算 Arrival Time
1.  topo_order ← TopologicalSort(G); arrival[1..|V|] ← 0
2.  对 topo_order 中每个节点 v:
3.      对 v 的每个后继 u: arrival[u] ← max(arrival[u], arrival[v] + delay(v, u))

// 阶段二：反向拓扑遍历，计算 Required Time
4.  required[1..|V|] ← ∞
5.  对每个 PO / Register Input endpoint e: required[e] ← T - Tsu
6.  对 topo_order 的逆序中每个节点 u:
7.      对 u 的每个前驱 v: required[v] ← min(required[v], required[u] - delay(v, u))

// 阶段三：Slack = Required - Arrival
8.  对每个节点 v: slack[v] ← required[v] - arrival[v]
9.  WNS ← min(slack[e]); TNS ← Σ max(0, -slack[e])
10. return slack, WNS, TNS
```

- **Slack > 0**：时序满足（MET），可换用更慢/更小的单元（area 优化）
- **Slack < 0**：时序违例（VIOLATE），需优化（upsize gate、insert buffer）
- **WNS**（Worst Negative Slack）：最差的 Slack，反映极限频率
- **TNS**（Total Negative Slack）：所有负 Slack 绝对值之和，反映整体时序健康度

### 6.3 增量式关键路径更新

```
算法: IncrementalUpdate(G, changed_node, new_delay)
输入: DAG G，延迟发生变化的节点 changed_node，新延迟 new_delay
输出: 更新后的 arrival、slack、以及是否影响 WNS

1.  affected ← BFS_Fanout(changed_node)       // 从 changed_node 正向遍历
2.  sub_topo ← TopologicalSort(InducedSubgraph(G, affected))
3.  对 sub_topo 中每个节点 v:
4.      old_arrival ← arrival[v]
5.      arrival[v] ← max_{p∈pred(v)}(arrival[p] + delay(p, v))
6.      若 arrival[v] ≠ old_arrival: 标记 v 的 fanout 为 dirty
7.  若 affected ∩ endpoints ≠ ∅:
8.      对 affected cone 的逆拓扑序更新 required
9.      重算受影响节点的 slack
10. new_WNS ← min(slack[e]) for e in endpoints
11. return arrival, slack, new_WNS
```

- **复杂度**：**O(|ΔV|+|ΔE|)**，仅重算受影响子图，远小于全图重算
- **RTL映射**：event-driven simulation 中 gate delay 变化时，只需沿 fanout 方向增量更新

### 6.4 ML PBA Slack预测

ICCD 2018 提出用机器学习从 Graph-Based Timing Analysis（GBA）快速预测 Path-Based Timing Analysis（PBA）Slack：

- **输入特征**：GBA Slack、路径深度、总 gate delay / wire delay、最大输入 transition、输出负载电容、buffer/inverter 数量、工艺角
- **意义**：若多线程仿真器需要快速判断某个 partition 方案是否导致时序恶化，可用轻量 ML 模型预测关键路径延迟，无需运行完整 STA

---

## 7. 对多线程RTL仿真器的启示

### 7.1 核心映射关系

| 图算法 | 直接映射到RTL仿真器 | 影响维度 |
|--------|-------------------|---------|
| 超图划分 | 电路 = 超图，分区质量决定加速比 | 并行化上限 |
| 谱聚类 | 初始划分的"黄金标准" | 分区质量 |
| 网络流 | 边界精修与全局瓶颈识别 | 割质量 |
| 拓扑排序 | 编译期 levelization + wave调度 | 调度效率 |
| 关键路径 | 决定并行化的理论上限 | 加速比天花板 |
| 图遍历 | 环检测 + 可达性裁剪 | 编译正确性 |

### 7.2 可操作的建议

1. **KaHyPar做初始分区**：对 10K~1M 门级电路，KaHyPar 运行时间在秒级，支持固定顶点、可变权重、多目标优化。优先采用 n-level + 流精修（KaHyPar-MF）

2. **谱聚类做质量评估**：在自研多级分区器中，最粗化层（~500 顶点）可承受谱二分的 O(n³) 计算。相比随机贪心初始划分，谱初始解能显著减少后续 FM 精修迭代次数

3. **FBB做精修**：在获得初始多级划分后，对每一对相邻线程的边界区域运行 FBB 精修。Yang & Wong 的增量流计算技术保证额外开销极小

4. **拓扑排序做调度**：Kahn's BFS 的每一轮零入度节点集合天然构成一个并行 wave。这是多线程RTL仿真最核心的调度依据——同 wave 内所有 gate 互相独立，可无锁并行求值

5. **关键路径指导load balancing**：
   - 关键路径上的 gate 是性能瓶颈，partition 应优先保证这些节点处于同一线程
   - 非关键路径上的 gate 拥有正 Slack，可故意分配给负载较重的线程
   - 最长路径长度（以 level 数计）等于每个周期需要顺序执行的 wave 数量，即使无限线程也无法少于此时间

6. **大超边特殊处理**：RTL 电路中的时钟树、复位树往往形成巨大超边（一个时钟驱动成千上万个触发器）。在FM精修中，这类 net 的增益变化极难捕捉。建议：对时钟/复位 net 预固定或分层处理；在粗化阶段优先收缩这类高扇出 net；引入流精修处理大超边附近的边界

---

## 参考来源

- [source-hypergraph-partitioning](source-hypergraph-partitioning.md) — 超图划分、FM、KL、KaHyPar、多级框架
- [source-spectral-clustering](source-spectral-clustering.md) — 图拉普拉斯、Fiedler向量、谱二分、谱间隙稳定性
- [source-network-flow](source-network-flow.md) — Max-Flow Min-Cut、FBB、Stoer-Wagner、Gomory-Hu树、KaHyPar-MF流精修
- [source-graph-traversal](source-graph-traversal.md) — 拓扑排序、Kahn BFS、DFS三色环检测、BFS Levelization、可达性分析
- [source-heuristic-search](source-heuristic-search.md) — A*搜索、Lee迷宫算法、Hadlock MD、Soukup混合搜索、多终端布线
- [source-critical-path](source-critical-path.md) — DAG最长路径、Slack计算、增量式更新、ML PBA预测

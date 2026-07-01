---
title: BFS/DFS/拓扑排序在 RTL 仿真与电路分析中的应用
description: 图遍历算法（BFS、DFS、拓扑排序）在 RTL 仿真器编译、电平化、依赖分析、可达性分析中的核心作用，涵盖 compiled simulation 的 levelization、net dependency graph 的拓扑排序、以及 feedback path 检测。
source_url: ""
source_type: "doc"  # github-pr, github-issue, blog, doc, paper, competition
author: "综合整理（UT Austin VLSI Lecture, USC EE355, CP-Algorithms, GeeksforGeeks, ScienceDirect）"
date: ""
tags: ["graph-traversal", "topological-sort", "BFS", "DFS", "levelization", "compiled-simulation", "dependency-analysis", "reachability"]
keywords: ["topological sort", "levelization", "BFS", "DFS", "reachability", "RTL simulation", "compiled simulation", "feedback loop", "dependency graph", "net dependency"]
capture_date: "2026-07-02"
---

# BFS/DFS/拓扑排序在 RTL 仿真与电路分析中的应用

## 来源

- **URL 1**: [UT Austin VLSI-1 Lecture 20: Hardware Description Languages & Logic Simulation](https://users.ece.utexas.edu/~mcdermot/vlsi1/main/lectures/lecture_20.pdf)
- **URL 2**: [USC EE355: Simulation File Format and Logic Design Simulation](https://ee.usc.edu/~redekopp/ee355/ee355_pa5_gatesim_p2.pdf)
- **URL 3**: [CP-Algorithms: Topological Sorting](https://cp-algorithms.com/graph/topological-sort.html)
- **URL 4**: [GeeksforGeeks: Topological Sorting](https://www.geeksforgeeks.org/dsa/topological-sorting/)
- **URL 5**: [ScienceDirect: Compilation and Simulation / Levelization](https://www.sciencedirect.com/topics/computer-science/simulation-performance)
- **URL 6**: [YSC2229: Reachability and Graph Traversals](https://ilyasergey.net/YSC2229-static/week-12-reachability.html)
- **类型**: 学术讲义 / 算法文档 / 技术综述
- **作者**: Mark McDermott (UT Austin), ilya Sergey (Yale), 等综合
- **日期**: 2018-2025

## 摘要

图遍历算法（BFS、DFS、拓扑排序）是 RTL 仿真器从网表到可执行模型的桥梁。Compiled simulation 通过**拓扑排序**（Topological Sort）将电路 gate 组织为 level，实现无反向依赖的逐级求值；Event-driven simulation 则利用**可达性分析**（Reachability）和**环检测**定位 feedback path。本文档汇总了 BFS/DFS/拓扑排序在 RTL 仿真中的三大应用场景：电平化编译、依赖图排序、以及反馈路径检测，附带完整的算法伪代码与复杂度分析。

## 关键要点

- **Compiled Simulation 的核心步骤**：标记 feedback path → 拓扑排序（levelization）→ 按 level 生成求值代码 → 编译执行。拓扑排序确保每一级的 gate 输入都在前一级已计算完毕。
- **Levelization 的两种策略**：ASAP（尽可能早）将 PI 设为 level 0，逐级递推；ALAP（尽可能晚）从 PO 反向推导。ALAP 在 macro-gate segmentation 中更常用。
- **Net Dependency Graph vs. Gate Graph**：真正需要排序的是 net 的依赖关系，而非 gate 本身。每个 net 的依赖是其所有 driver gate 的 input net。延迟计算可伴随拓扑排序同步进行：`delay(N) = MAX_G[drive(G) + MAX_I∈inputs(G)(delay(I))]`。
- **DFS 的 Coloring 技巧**：White/Gray/Black 三色标记法可在 O(|V|+|E|) 时间内检测 combinational loop（feedback path），Gray 节点被二次访问即意味着存在环。
- **Kahn's Algorithm（BFS 拓扑排序）**：基于入度归零的迭代删除，天然支持并发调度——同一轮入度为 0 的节点可并行求值，直接对应多线程 RTL 仿真中的 wave-level parallelism。

## 对 RTL 仿真器多线程化的启示

1. **Wave-level Parallelism**：拓扑排序后的每一 level 内部，gate 之间不存在数据依赖，可安全并行求值。Kahn's BFS 拓扑排序的每一轮零入度节点集合，天然构成一个并行 wave。这是多线程 RTL 仿真最核心的调度依据。
2. **Macro-gate Segmentation**：在按 level 组织后，可将相邻 level 的 small macro-gate 合并为更大的求值单元，减少线程同步开销（合并后的 macro-gate 内部仍保持 DAG 结构）。
3. **Feedback Path 检测**：多线程仿真要求先解环（break combinational loops）。DFS 环检测可在编译期识别 feedback edge，将 loop 打断点（cut point）插入 DFF 或 latch 建模，从而保证剩余图仍为 DAG。
4. **延迟计算与拓扑排序的融合**：在 levelization 过程中同时计算每个 net 的 arrival time，可直接为后续 critical path analysis 提供数据，避免二次遍历。

---

## 算法详解与伪代码

### 1. 拓扑排序（DFS 版本）——用于 Compiled Simulation Levelization

**复杂度**: 时间 O(|V| + |E|)，空间 O(|V|)

```
算法: TopologicalSort_DFS(G)
输入: 有向无环图 G = (V, E)，V 为 gate/net，E 为依赖边
输出: 拓扑序数组 order[0..|V|-1]

1.  visited[1..|V|] ← false
2.  order ← 空数组
3.  
4.  过程 DFS(v):
5.      visited[v] ← true
6.      对 v 的每个后继 u ∈ adj[v]:
7.          若 not visited[u]:
8.              DFS(u)
9.      order.push_back(v)        // 后序追加：所有依赖已处理完毕
10. 
11. 对每个顶点 v ∈ V:
12.     若 not visited[v]:
13.         DFS(v)
14. 
15. reverse(order)                // 逆序即为拓扑序
16. return order
```

**RTL 映射**: 在 compiled simulation 中，`V` 是 combinational gate 或 net，`E` 是 data dependency（gate output → gate input）。逆序后按 order 生成求值代码，保证每个 gate 的输入 net 已在前文计算。

---

### 2. Kahn's Algorithm（BFS 版本）——用于 Wave-level Parallel 调度

**复杂度**: 时间 O(|V| + |E|)，空间 O(|V|)

```
算法: TopologicalSort_BFS_Kahn(G)
输入: 有向无环图 G = (V, E)
输出: 拓扑序数组 order[0..|V|-1]，以及每轮可并行节点集合 waves[]

1.  in_degree[v] ← 计算每个节点 v 的入度
2.  queue ← 所有 in_degree[v] == 0 的节点 v
3.  order ← 空数组
4.  waves ← 空列表
5.  
6.  while queue 非空:
7.      wave ← 当前 queue 中的所有节点      // 本轮可并行求值
8.      waves.append(wave)
9.      queue ← 空队列
10.     对 wave 中每个节点 v:
11.         order.append(v)
12.         对 v 的每个后继 u ∈ adj[v]:
13.             in_degree[u] ← in_degree[u] - 1
14.             若 in_degree[u] == 0:
15.                 queue.enqueue(u)
16. 
17. 若 |order| < |V|:
18.     错误：图中存在环（feedback path）
19. 
20. return order, waves
```

**RTL 映射**: `waves[i]` 是第 i 个并行 wave，同 wave 内所有 gate 互相独立，可在多线程中无锁并行求值。Verilator 等编译型仿真器的多线程 partition 即基于类似的 levelization。

---

### 3. DFS 三色标记法 —— 检测 Combinational Feedback Loop

**复杂度**: 时间 O(|V| + |E|)，空间 O(|V|)

```
算法: DetectCycle_DFS(G)
输入: 有向图 G = (V, E)（可能含环）
输出: 是否存在环 has_cycle，以及反馈边集合 feedback_edges

1.  color[v] ← WHITE 对所有 v ∈ V
2.  has_cycle ← false
3.  feedback_edges ← ∅
4.  
5.  过程 DFS_Visit(u):
6.      color[u] ← GRAY
7.      对 u 的每个后继 v ∈ adj[u]:
8.          若 color[v] == WHITE:
9.              DFS_Visit(v)
10.         否则若 color[v] == GRAY:
11.             // 发现回边：u → v，v 正在递归栈中
12.             has_cycle ← true
13.             feedback_edges ← feedback_edges ∪ {(u, v)}
14.     color[u] ← BLACK
15. 
16. 对每个顶点 v ∈ V:
17.     若 color[v] == WHITE:
18.         DFS_Visit(v)
19. 
20. return has_cycle, feedback_edges
```

**RTL 映射**: 在 gate-level 或 net-level dependency graph 中，Gray→Gray 的回边即为 combinational feedback path。检测到后，需要在该边处插入 break point（用一个虚拟寄存器或 latch 切断纯组合环），使剩余图成为 DAG，方可进行 levelization。

---

### 4. BFS Levelization（ASAP）—— 计算每个 Gate 的 Level 编号

**复杂度**: 时间 O(|V| + |E|)，空间 O(|V|)

```
算法: BFS_Levelization_ASAP(G, primary_inputs)
输入: DAG G = (V, E)，primary_inputs 集合
输出: level[v] 对每个 v ∈ V

1.  对每个 v ∈ V: level[v] ← -1
2.  queue ← 空队列
3.  
4.  对每个 PI v ∈ primary_inputs:
5.      level[v] ← 0
6.      queue.enqueue(v)
7.  
8.  while queue 非空:
9.      v ← queue.dequeue()
10.     对 v 的每个后继 u ∈ adj[v]:
11.         // u 的 level 取决于所有前驱的最大 level + 1
12.         level[u] ← max(level[u], level[v] + 1)
13.         // 当 u 的所有前驱都已分配 level 后，入队
14.         若 u 的所有前驱 w 都满足 level[w] ≠ -1:
15.             queue.enqueue(u)
16. 
17. return level
```

**RTL 映射**: `level[v]` 表示 gate v 到 PI 的最长路径距离（以 gate 数为单位）。Compiled simulator 按 level 升序生成求值代码，同一 level 的 gate 可以并行计算。注意：若存在多扇入（multi-fanin），必须等所有前驱的 level 都确定后才能计算当前 gate。

---

### 5. 可达性分析（Reachability）—— 用于 Fanin/Fanout 裁剪

**复杂度**: 时间 O(|V| + |E|)，空间 O(|V|)

```
算法: Reachability_BFS(G, source)
输入: 图 G = (V, E)，起点 source
输出: reachable[v] = true/false 对所有 v ∈ V

1.  reachable[v] ← false 对所有 v ∈ V
2.  queue ← 空队列
3.  queue.enqueue(source)
4.  reachable[source] ← true
5.  
6.  while queue 非空:
7.      v ← queue.dequeue()
8.      对 v 的每个后继 u ∈ adj[v]:
9.          若 not reachable[u]:
10.             reachable[u] ← true
11.             queue.enqueue(u)
12. 
13. return reachable
```

**RTL 映射**: 在 RTL 仿真中，给定一组需要观测的 PO（primary output），可以反向做 BFS（沿 fanin 边反向遍历）求出**transitive fanin cone**，将无关 gate 裁剪掉，极大减少每周期求值量。这是 compiled simulation 中 "node elimination" 的核心算法。

---

## 复杂度总结表

| 算法 | 时间复杂度 | 空间复杂度 | RTL 应用场景 |
|------|---------|---------|------------|
| 拓扑排序 DFS | O(|V|+|E|) | O(|V|) | Compiled simulation 生成求值顺序 |
| 拓扑排序 BFS (Kahn) | O(|V|+|E|) | O(|V|) | Wave-level 并行调度 |
| DFS 环检测 | O(|V|+|E|) | O(|V|) | Feedback path / combinational loop 检测 |
| BFS Levelization | O(|V|+|E|) | O(|V|) | ASAP/ALAP level 编号分配 |
| BFS 可达性 | O(|V|+|E|) | O(|V|) | Transitive fanin/fanout 裁剪 |

> **关键观察**：上述所有核心算法在线性时间内完成，因此 compiled simulation 的编译阶段（compilation time）是多项式可接受的，而换来的执行阶段（execution time）收益是巨大的——因为 dormant circuit 部分（10-30% 活动率）被完全跳过。

---

## 原文摘录

> "Compiled Simulation Algorithm: mark feedback paths; levelize circuit - topological sort; generate evaluation code by level in circuit; compile and link with control and I/O; execute."  
> —— UT Austin VLSI-1 Lecture 20

> "At first glance, it would appear that we want to perform a topological sort of the gates in the network... we want to perform a topological ordering of the net's in the design based on their dependence on other nets. The topological ordering also provides an opportunity to calculate delay."  
> —— USC EE355 Simulation Notes

> "After combinational logic extraction, the combinational netlist is then levelized. Logic gates are organized into levels based on their topological order, so that the fan-in of all gates in one level is computed in previous levels."  
> —— ScienceDirect, Compilation and Simulation

> "A topological sort is a linear ordering of the nodes in a directed acyclic graph (DAG) such that every directed edge (u→v) ensures that u appears before v in the ordering. In this context, the nodes correspond to gates, and the edges encode RAW and WAR dependencies between them."  
> —— eprint.iacr.org 2025/1915

---

## 相关链接

- [CP-Algorithms: Topological Sort](https://cp-algorithms.com/graph/topological-sort.html)
- [GeeksforGeeks: Topological Sorting in DAG](https://www.geeksforgeeks.org/dsa/topological-sorting/)
- [UT Austin VLSI Lecture 20 (PDF)](https://users.ece.utexas.edu/~mcdermot/vlsi1/main/lectures/lecture_20.pdf)
- [USC EE355 Gate Simulation Notes (PDF)](https://ee.usc.edu/~redekopp/ee355/ee355_pa5_gatesim_p2.pdf)
- [YSC2229: Reachability and Graph Traversals](https://ilyasergey.net/YSC2229-static/week-12-reachability.html)
- [ScienceDirect: Simulation Performance / Levelization](https://www.sciencedirect.com/topics/computer-science/simulation-performance)
- [eprint.iacr.org: Topological Sort for Gate Scheduling](https://eprint.iacr.org/2025/1915.pdf)

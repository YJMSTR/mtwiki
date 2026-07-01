---
title: A* 启发式搜索与迷宫布线算法在 VLSI/EDA 中的应用
description: A* 算法、Lee 迷宫布线算法、Soukup 混合搜索、Hadlock 最小绕弯算法等路径搜索算法在 VLSI 全局布线（Global Routing）和详细布线（Detailed Routing）中的应用，涵盖 heuristic function 设计、Manhattan 距离、congestion cost 融合。
source_url: ""
source_type: "paper"  # github-pr, github-issue, blog, doc, paper, competition
author: "综合整理（AiTPO@TODAES 2025, Northwestern EECS 357, VLSI System Design, VLSI-CAD IJRPR, IEEE/ACM 文献）"
date: ""
tags: ["A*", "heuristic-search", "maze-routing", "Lee-algorithm", "global-routing", "pathfinding", "VLSI", "EDA", "Soukup", "Hadlock", "congestion"]
keywords: ["A* algorithm", "Lee's algorithm", "maze routing", "Manhattan distance", "heuristic search", "VLSI routing", "global routing", "detour number", "congestion cost", "line search"]
capture_date: "2026-07-02"
---

# A* 启发式搜索与迷宫布线算法在 VLSI/EDA 中的应用

## 来源

- **URL 1**: [AiTPO: KAN-UNet Heterogeneous Network for Timing Prediction and Optimization at Global Routing (TODAES 2025)](https://ieda.oscc.cc/res/papers/25-TODAES-AiTPO.pdf)
- **URL 2**: [Northwestern EECS 357: Maze Router - Lee Algorithm (Lecture Notes)](https://users.eecs.northwestern.edu/~haizhou/357/lec6.pdf)
- **URL 3**: [VLSI System Design: Maze Routing - Lee's Algorithm](https://www.vlsisystemdesign.com/maze-routing-lees-algorithm/)
- **URL 4**: [VLSI-CAD Design Flow For RTL-NETLIST (IJRPR)](https://ijrpr.com/uploads/V4ISSUE8/IJRPR16156.pdf)
- **URL 5**: [Efficient Maze-Running and Line-Search Algorithms for VLSI Layout (IEEE)](http://users.cis.fiu.edu/~iyengar/publication/backup/J-(1993)%20-%20Efficient%20Maze%20Running%20and%20Line%20Search%20Algorithms%20for%20VLSI%20Layout%20-%5BIEEE%5D.pdf)
- **URL 6**: [ACE Proceedings: Routing Algorithms in VLSI Design](https://www.ewadirect.com/proceedings/ace/volumes/vol/21/85.pdf)
- **类型**: 学术论文 / 讲义 / 技术博客
- **作者**: He Liu et al. (AiTPO), Lee (1961), Hadlock (1977), Soukup (1978), 等
- **日期**: 1961-2025

## 摘要

VLSI 布线（Routing）本质上是一个**图搜索**问题：在芯片版图的有向网格图上，从源点（Source Pin）到目标点（Target Pin）寻找满足设计规则（DRC）的最短路径。Lee 算法（1961）是 BFS 在网格布线中的直接应用，保证最优但时间和空间复杂度均为 O(MN)；A* 算法通过引入**启发式函数** h(n)（通常为 Manhattan 距离）将搜索定向朝向目标，在保持最优性的同时显著减少扩展节点数。Hadlock 的 Minimum Detour 算法和 Soukup 的 DFS+BFS 混合算法则提供了不同精度和效率的折中。本文档汇总这些算法在 VLSI 全局/详细布线中的实现细节、启发函数设计、以及 congestion-aware 扩展策略。

## 关键要点

- **Lee 算法 = BFS on Grid**：从 Source 开始逐层波前扩散（wave propagation），标记每个格子的距离值，直到 Target 被标记，再回溯递减标签得到最短路径。时间/空间复杂度 O(MN) 对于 M×N 网格。
- **A* 算法的代价函数**：f(n) = g(n) + h(n)，其中 g(n) 是从 Source 到当前节点的实际代价（走线长度/RC 延迟），h(n) 是启发式估计（通常为 Manhattan 距离或考虑 congestion 的修正 Manhattan 距离）。A* 优先扩展 f(n) 最小的节点。
- **Hadlock 最小绕弯算法（MD）**：基于 A* 思想，将启发式定义为**绕弯数**（Detour Number）。路径长度 = Manhattan 距离 + 2×Detour。MD 算法按 detour 数递增的顺序搜索，最坏时间介于 O(n) 和 O(n²) 之间，远优于 Lee 的 O(n³)。
- **Soukup 混合算法**：从 Source 向 Target 做**深度优先搜索**（"不转弯"启发式），直到撞墙或到达 Target；若撞墙，则切换到 BFS（Lee 式）绕障。比 Lee 快 10-50 倍，但**不保证最短路径**。
- **Congestion-Aware A***：现代全局布线（Global Routing）将 congestion map 作为代价惩罚项加入 h(n)，使 A* 主动避开拥塞区域。AiTPO 框架通过 A* 生成多个候选路径，再用 ML 预测选择 timing 最优的拓扑。
- **Line-Search 算法**：Mikami-Tabuchi（每格点都是 escape point）和 Hightower（每线段一个 escape point），时间/空间复杂度降至 O(L)，L 为生成线段数，但均不保证最短路径。

## 对 RTL 仿真器多线程化的启示

1. **A* 的启发式思想可迁移到调度搜索**：在多线程 RTL 仿真中，若需要为某个信号寻找最快的仿真路径（如跨线程 dependency 的最短传播路径），可以将 Manhattan 距离或 level difference 作为启发式，快速剪枝不可能最优的调度方案。
2. **Congestion 映射到线程负载均衡**：VLSI 布线中的 congestion map 可类比为线程负载分布图。在多线程仿真器的 partition 阶段，可以借鉴 A* 的 congestion-aware 代价函数，将高 activity 区域均匀分散到不同线程，避免某些线程成为瓶颈。
3. **Lee 算法的波前扩散 = 数据流并行边界**：Lee 的 wave propagation 与 BFS levelization 有深刻同构性——每一波前对应一个并行层级。理解这种同构有助于将布线算法中的优化（如 double fan-out、framing）迁移到仿真器的 level scheduling 中。
4. **路径回溯与 critical path tracing**：A* 的父指针回溯机制可直接用于 RTL 仿真中的 critical path tracing——从 failing endpoint 反向回溯到 source register，记录路径上的每个节点。

---

## 算法详解与伪代码

### 1. Lee 迷宫布线算法（Maze Routing / BFS）

**时间复杂度**: O(M × N)  
**空间复杂度**: O(M × N)  
**最优性**: 保证找到最短路径（若存在）

```
算法: Lee_Maze_Routing(Grid, S, T)
输入: M×N 网格 Grid（0=自由, 1=障碍），源点 S，目标点 T
输出: 最短路径 Path（若存在）

1.  label[S] ← 1
2.  queue ← {S}
3.  
4.  // 阶段一：波前扩散（Wave Propagation）
5.  while queue 非空:
6.      v ← queue.dequeue()
7.      若 v == T: break
8.      对 v 的每个四邻域 u（上/下/左/右）:
9.          若 Grid[u] 为空且 label[u] 未定义:
10.             label[u] ← label[v] + 1
11.             queue.enqueue(u)
12. 
13. 若 label[T] 未定义:
14.     return 无路径
15. 
16. // 阶段二：回溯（Retrace）
17. Path ← [T]
18. current ← T
19. while current ≠ S:
20.     对 current 的每个四邻域 u:
21.         若 label[u] == label[current] - 1:
22.             Path.prepend(u)
23.             current ← u
24.             break
25. 
26. return Path
```

**优化策略**:
- **Akers 标签压缩**：相邻标签只可能是 k−1 或 k+1，可用 1,2,3,1,2,3... 或 1,1,2,2,1,1,2,2... 序列代替连续整数，减少存储位宽。
- **Double Fan-out**：同时从 S 和 T 双向扩散，相遇即停，减少搜索面积。
- **Framing**：在 S/T 的 bounding box 外扩 10-20% 的矩形区域内搜索，失败后再扩大。

---

### 2. A* 搜索算法（A* Maze Routing）

**时间复杂度**: 最坏 O(M × N)，实际远小于 Lee 算法（取决于启发函数质量）  
**空间复杂度**: O(M × N)  
**最优性**: 若 h(n) 是 admissible（不过估），则保证最优

```
算法: AStar_Routing(Grid, S, T, h)
输入: M×N 网格 Grid，源点 S，目标点 T，启发函数 h(n)
输出: 最短路径 Path（若存在）

1.  g[S] ← 0
2.  f[S] ← h(S, T)
3.  open_set ← 最小优先队列，按 f 值排序
4.  open_set.insert(S, f[S])
5.  came_from ← 空字典
6.  closed_set ← ∅
7.  
8.  while open_set 非空:
9.      current ← open_set.pop_min()       // f 值最小的节点
10.     若 current == T:
11.         return ReconstructPath(came_from, T)
12.     
13.     closed_set ← closed_set ∪ {current}
14.     
15.     对 current 的每个邻域 neighbor:
16.         若 neighbor ∈ closed_set: continue
17.         若 Grid[neighbor] 为障碍: continue
18.         
19.         tentative_g ← g[current] + cost(current, neighbor)
20.         若 neighbor ∉ open_set 或 tentative_g < g[neighbor]:
21.             came_from[neighbor] ← current
22.             g[neighbor] ← tentative_g
23.             f[neighbor] ← tentative_g + h(neighbor, T)
24.             若 neighbor ∉ open_set:
25.                 open_set.insert(neighbor, f[neighbor])
26. 
27. return 无路径

过程 ReconstructPath(came_from, T):
    Path ← [T]
    current ← T
    while current ∈ came_from:
        current ← came_from[current]
        Path.prepend(current)
    return Path
```

**启发函数设计（VLSI 场景）**:

| 启发函数 | 公式 | 特性 |
|---------|------|------|
| Manhattan 距离 | h(n) = \|x_n − x_T\| + \|y_n − y_T\| | 可采纳（admissible），最常用 |
| 带绕弯惩罚 | h(n) = Manhattan + λ × bend_count | 偏好直线路径，减少过孔 |
| Congestion-aware | h(n) = Manhattan + μ × congestion(n) | 避开高拥塞区域，不可完全采纳但实用 |
| Timing-aware | h(n) = estimated_RC_delay(n, T) | 需精确 RC 模型，用于 timing-driven routing |

---

### 3. Hadlock 最小绕弯算法（Minimum Detour / A* 变体）

**时间复杂度**: O(n) ~ O(n²) 对于 n×n 网格（优于 Lee 的 O(n³)）  
**空间复杂度**: O(n²)  
**最优性**: 保证最短路径

```
算法: Hadlock_MD(Grid, S, T)
输入: n×n 网格 Grid，源点 S，目标点 T
输出: 最短路径 Path

1.  M ← Manhattan_Distance(S, T)
2.  detour[S] ← 0
3.  queue ← 优先队列，按 detour 值排序
4.  queue.insert(S, 0)
5.  label[S] ← 1
6.  
7.  while queue 非空:
8.      v ← queue.pop_min()
9.      若 v == T: break
10.     对 v 的每个邻域 u:
11.         若 Grid[u] 为空且 label[u] 未定义:
12.             // 计算 u 相对 T 的绕弯方向
13.             若 u 向 T 靠近（Manhattan 距离减小）:
14.                 d ← detour[v]
15.             否则:
16.                 d ← detour[v] + 1
17.             detour[u] ← d
18.             label[u] ← label[v] + 1
19.             queue.insert(u, d)
20. 
21. // 路径长度 = M + 2 × detour[T]
22. return Retrace(Grid, label, T, S)
```

**核心思想**：用 detour 数替代 Lee 的绝对距离标签。Detour 定义为路径上远离目标的总单位数。因为路径长度 = Manhattan + 2×Detour，按 detour 递增搜索等价于按路径长度递增搜索，但搜索空间大幅收缩。

---

### 4. Soukup 混合搜索算法（DFS + BFS）

**时间复杂度**: O(M × N)（实际比 Lee 快 10-50 倍）  
**空间复杂度**: O(M × N)  
**最优性**: 不保证最短路径

```
算法: Soukup_Routing(Grid, S, T)
输入: M×N 网格 Grid，源点 S，目标点 T
输出: 可行路径 Path（不一定最短）

1.  阶段一：深度优先直线搜索（Line Probe）
2.  current ← S
3.  方向 dir ← 从 S 指向 T 的主方向（减少转弯）
4.  while current ≠ T:
5.      next ← 沿 dir 直线前进一步
6.      若 next 为障碍或越界:
7.          // 撞墙，切换到 BFS 绕障
8.          goto 阶段二
9.      current ← next
10.     若 current == T: return 回溯路径
11. 
12. 阶段二：BFS 绕障（Lee 式局部扩散）
13. 从 current 开始进行局部 BFS，直到找到能继续朝向 T 的 escape point
14. 从 escape point 继续阶段一的 DFS 直线搜索
15. 重复直到到达 T 或确认无路径
16. 
17. return 回溯路径
```

**RTL/EDA 启示**：Soukup 的 DFS→BFS→DFS 切换模式，可类比多线程 RTL 仿真中的调度策略：在没有冲突的区域（无障碍）使用激进的同步-free 并行执行，在冲突热点区域切换到保守的同步模式。

---

### 5. 多终端网络布线（Multi-Terminal Net）

```
算法: MultiTerminal_Maze_Routing(Grid, pins = {p1, p2, ..., pk})
输入: 网格 Grid，k 个终端 pin
输出: 连接所有 pin 的 Steiner 树 / 路径

1.  选定 p1 为 Source
2.  剩余 pins 按到 p1 的 Manhattan 距离排序
3.  
4.  for i = 2 to k:
5.      以 p1 为 Source，pi 为 Target 运行 Lee/A* 算法
6.      找到路径 Path_i 后，将 Path_i 上所有格子标记为新的 Source（"s 细胞"）
7.      从所有 s 细胞同时做波前扩散，连接到下一个 pi
8.  
9.  应用 Steiner 树启发式进一步缩减总线长
10. return 合并后的路径树
```

---

## 算法对比表

| 算法 | 时间 | 空间 | 保证最优？ | 保证连通？ | 网格/线段 | 适用场景 |
|------|------|------|---------|---------|----------|---------|
| **Lee (BFS)** | O(MN) | O(MN) | ✅ | ✅ | 网格 | 详细布线，小规模 |
| **A* (Manhattan)** | O(MN) 最坏 | O(MN) | ✅ | ✅ | 网格 | 全局布线，最优+高效 |
| **Hadlock (MD)** | O(n)~O(n²) | O(n²) | ✅ | ✅ | 网格 | 大规模网格最优路径 |
| **Soukup** | O(MN) | O(MN) | ❌ | ✅ | 网格 | 快速近似，大规模 |
| **Mikami-Tabuchi** | O(L) | O(L) | ❌ | ✅ | 线段 | 快速布线，大图 |
| **Hightower** | O(L) | O(L) | ❌ | ❌ | 线段 | 连续平面布线 |

> 注：L 为生成线段数，通常 L << MN。

---

## 原文摘录

> "The A* algorithm is a classic and powerful heuristic search algorithm, widely used in pathfinding and graph search fields. It combines the strengths of Dijkstra's algorithm with heuristic search strategies, considering both the actual cost and the estimated cost of the path. In the A* algorithm, each node has an associated cost function f(n)=g(n)+h(n), where g(n) is the actual path cost and h(n) is the heuristic estimate."  
> —— AiTPO, TODAES 2025

> "Lee's algorithm i.e. Maze Routing, is perhaps the most widely used algorithm to find path between 2 points. Lee's Algorithm guarantees there exists a valid path and it's the shortest path. But this algorithm is too time and memory consuming."  
> —— VLSI System Design Blog

> "Hadlock applied the idea of using lower bound on distance to the target to direct the search... He used a new labeling measure, called detour number... The minimum detour algorithm searches paths in the increasing order of detour numbers. It guarantees to find the shortest path using time between O(n) and O(n²)."  
> —— Efficient Maze-Running and Line-Search Algorithms for VLSI Layout (IEEE)

> "Soukup proposed a fast algorithm that combines the depth-first-search with the breadth-first-search... This algorithm guarantees to find a path if it exists, but not necessarily an optimal path. Soukup's algorithm executes a depth-first-search from the source node toward the target node using 'don't change direction' heuristic until an obstacle is hit."  
> —— Efficient Maze-Running and Line-Search Algorithms for VLSI Layout (IEEE)

---

## 相关链接

- [AiTPO Paper (TODAES 2025)](https://ieda.oscc.cc/res/papers/25-TODAES-AiTPO.pdf)
- [Northwestern EECS 357: Maze Routing Lecture](https://users.eecs.northwestern.edu/~haizhou/357/lec6.pdf)
- [VLSI System Design: Lee's Algorithm](https://www.vlsisystemdesign.com/maze-routing-lees-algorithm/)
- [VLSI-CAD RTL-Netlist Paper](https://ijrpr.com/uploads/V4ISSUE8/IJRPR16156.pdf)
- [Efficient Maze-Running and Line-Search (IEEE)](http://users.cis.fiu.edu/~iyengar/publication/backup/J-(1993)%20-%20Efficient%20Maze%20Running%20and%20Line%20Search%20Algorithms%20for%20VLSI%20Layout%20-%5BIEEE%5D.pdf)
- [ACE Proceedings: Routing Algorithms](https://www.ewadirect.com/proceedings/ace/volumes/vol/21/85.pdf)
- [Global-Sci: AAM Routing Algorithm](https://www.global-sci.com/aam/article/download/8437/16805)

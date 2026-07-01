---
title: 关键路径分析 / 最长路径算法在 RTL/电路时序分析中的应用
description: 关键路径分析（Critical Path Analysis）、DAG 最长路径算法、Slack 计算、Path-Based Timing Analysis 在 RTL 综合与静态时序分析（STA）中的核心算法。涵盖从综合报告（Design Compiler）到机器学习预测时序（AiTPO）的全链路。
source_url: ""
source_type: "doc"  # github-pr, github-issue, blog, doc, paper, competition
author: "综合整理（Synopsys Design Compiler, AiTPO@TODAES 2025, ScienceDirect, CP-Algorithms, ICCD 2018）"
date: ""
tags: ["critical-path", "longest-path", "DAG", "slack", "timing-analysis", "STA", "Design-Compiler", "path-based", "WNS", "TNS"]
keywords: ["critical path", "longest path", "DAG longest path", "slack", "setup time", "hold time", "arrival time", "required time", "WNS", "TNS", "path-based timing analysis", "Design Compiler"]
capture_date: "2026-07-02"
---

# 关键路径分析 / 最长路径算法在 RTL/电路时序分析中的应用

## 来源

- **URL 1**: [综合工具-Design Compiler使用（从RTL到综合出各种报告timing/area/critical_path）](https://www.bilibili.com/read/cv17138007/)
- **URL 2**: [AiTPO: KAN-UNet Heterogeneous Network for Timing Prediction and Optimization at Global Routing (TODAES 2025)](https://ieda.oscc.cc/res/papers/25-TODAES-AiTPO.pdf)
- **URL 3**: [ScienceDirect: Compilation and Simulation / Extraction of Combinational Logic](https://www.sciencedirect.com/topics/computer-science/simulation-performance)
- **URL 4**: [CP-Algorithms: Longest Path in a DAG (Practice Problem)](https://cp-algorithms.com/graph/topological-sort.html)
- **URL 5**: [Using Machine Learning to Predict Path-Based Slack from Graph-Based Timing Analysis (ICCD 2018)](https://xueshu.baidu.com/usercenter/paper/show?paperid=1w080gd0y41r04100v380vs026755465)
- **URL 6**: [USC EE355: Delay Computation via Topological Ordering](https://ee.usc.edu/~redekopp/ee355/ee355_pa5_gatesim_p2.pdf)
- **类型**: 技术文档 / 学术论文 / 工具教程
- **作者**: Synopsys, He Liu et al., ICCD 2018 等
- **日期**: 2018-2025

## 摘要

关键路径（Critical Path）决定了数字电路能运行的最高时钟频率。在 RTL 综合与静态时序分析（STA）中，电路被建模为**有向无环图（DAG）**，关键路径问题等价于 DAG 上的**最长路径问题**（Longest Path Problem）。与常规图的最短路径不同，DAG 最长路径可通过一次拓扑排序后在 O(|V|+|E|) 时间内求解。本文档汇总了关键路径分析的算法基础——从综合工具（Design Compiler）的 `report_timing` 到全局布线阶段（Global Routing）的 WNS/TNS 优化，涵盖 Arrival Time / Required Time / Slack 的完整计算链路，以及 Path-Based Timing Analysis 与 Graph-Based Timing Analysis 的区别。

## 关键要点

- **Critical Path = DAG 最长路径**：在 combinational logic 中，从任意输入到任意输出的最长延迟路径决定了电路的极限速度。综合工具（DC）的 `report_timing` 本质上就是在 DAG 上执行最长路径搜索。
- **Arrival Time vs. Required Time**：
  - **Arrival Time**（到达时间）：信号从时钟沿出发，经过 combinational path 到达 endpoint 的实际时间。计算方式：从 PI 正向拓扑遍历，累加 gate delay 和 wire delay。
  - **Required Time**（要求时间）：信号必须在此时之前到达，以满足 setup/hold 约束。通常 = 时钟周期 − setup time − clock skew。
  - **Slack** = Required Time − Arrival Time。Slack > 0 表示时序满足（MET），Slack < 0 表示违例（VIOLATE）。
- **WNS 与 TNS**：
  - **WNS**（Worst Negative Slack）：所有 endpoint 中最差的 Slack 值，反映整个设计的极限频率。
  - **TNS**（Total Negative Slack）：所有负 Slack 的绝对值之和，反映整体时序健康度。
- **Path-Based vs. Graph-Based STA**：
  - **Graph-Based**（GBA）：每个节点只存储 best/worst case 的 arrival time，保守但快速。
  - **Path-Based**（PBA）：对每个具体路径做精确分析（考虑输入转换率、负载电容等），更精确但计算量巨大。机器学习（如 ICCD 2018 工作）被用于从 GBA 快速预测 PBA Slack。
- **拓扑排序与最长路径的融合**：在 levelization 过程中同步计算 arrival time，可在同一趟遍历中完成 level 编号和关键路径识别。

## 对 RTL 仿真器多线程化的启示

1. **Critical Path 指导线程 Partition**：在多线程 RTL 仿真中，关键路径上的 gate 是性能瓶颈。若 partition 将关键路径上的 gate 拆分到不同线程，同步开销会直接叠加到关键路径延迟上。因此，partition 算法应优先保证关键路径上的节点处于同一线程（或同一 NUMA 节点）。
2. **Slack 驱动的负载均衡**：非关键路径上的 gate 拥有正 Slack，意味着它们可以"容忍"更多的调度延迟。多线程调度器可以故意将高 Slack 的 gate 分配给负载较重的线程，而将零 Slack（critical）gate 保留在最快路径上。
3. **Longest Path 作为 Wave Depth 上界**：在 compiled simulation 的 levelization 中，最长路径长度（以 level 数计）等于每个时钟周期需要顺序执行的 wave 数量。这个值直接决定了多线程并行化的理论上限——即使无限线程，也无法在少于 critical path level 数的时间内完成一个周期。
4. **Arrival Time 的增量更新**：在 event-driven simulation 中，当某个 gate 的 delay 变化（如由于输入 transition 变化），只需沿 fanout 方向增量更新下游节点的 arrival time，这正是一个 DAG 上的局部最长路径重算问题。

---

## 算法详解与伪代码

### 1. DAG 最长路径（关键路径）—— 基于拓扑排序

**时间复杂度**: O(|V| + |E|)  
**空间复杂度**: O(|V|)  
**前提**: 图必须是 DAG（无 combinational loop）

```
算法: CriticalPath_DAG(G, delays)
输入: 有向无环图 G = (V, E)，delay[v] 为每个节点/边的延迟
输出: 最长路径长度 max_delay，以及关键路径上的节点序列 critical_path

1.  topo_order ← TopologicalSort(G)          // 使用 Kahn 或 DFS 拓扑排序
2.  
3.  // 正向遍历：计算每个节点的最早到达时间（Arrival Time）
4.  arrival[1..|V|] ← 0
5.  对 topo_order 中每个节点 v（按拓扑序）:
6.      对 v 的每个后继 u ∈ adj[v]:
7.          若 arrival[u] < arrival[v] + delay(v, u):
8.              arrival[u] ← arrival[v] + delay(v, u)
9.              predecessor[u] ← v           // 记录最长路径上的前驱
10. 
11. // 找到终点（最大 arrival time）
12. max_delay ← 0
13. endpoint ← null
14. 对每个 v ∈ V:
15.     若 arrival[v] > max_delay:
16.         max_delay ← arrival[v]
17.         endpoint ← v
18. 
19. // 回溯关键路径
20. critical_path ← 空数组
21. current ← endpoint
22. while current ≠ null:
23.     critical_path.prepend(current)
24.     current ← predecessor[current]
25. 
26. return max_delay, critical_path
```

**RTL 映射**:
- `V` = gate / net / pin
- `E` = signal flow（gate output → gate input 或 net driver → net load）
- `delay(v, u)` = gate intrinsic delay + wire RC delay + input transition 影响
- `arrival[v]` = 从任意 PI 到 v 的最长路径延迟
- `critical_path` = 决定时钟周期的 bottleneck path

---

### 2. Slack 计算 —— 结合 Required Time 的完整时序分析

**时间复杂度**: O(|V| + |E|)（两趟遍历）  
**空间复杂度**: O(|V|)

```
算法: ComputeSlack(G, delays, clock_period, setup_time)
输入: DAG G = (V, E)，delay[v] 或 delay(u,v)，时钟周期 T，setup time Tsu
输出: 每个节点的 slack[v]，以及 WNS、TNS

// 阶段一：正向拓扑遍历，计算 Arrival Time
1.  topo_order ← TopologicalSort(G)
2.  arrival[1..|V|] ← 0
3.  对 topo_order 中每个节点 v:
4.      对 v 的每个后继 u:
5.          arrival[u] ← max(arrival[u], arrival[v] + delay(v, u))
6. 
// 阶段二：反向拓扑遍历，计算 Required Time
7.  required[1..|V|] ← ∞
8.  对每个 Primary Output / Register Input endpoint e:
9.      required[e] ← clock_period - setup_time    // 基础约束
10. 对 topo_order 的逆序中每个节点 u:
11.     对 u 的每个前驱 v:
12.         required[v] ← min(required[v], required[u] - delay(v, u))
13. 
// 阶段三：计算 Slack
14. 对每个节点 v:
15.     slack[v] ← required[v] - arrival[v]
16. 
// 阶段四：WNS / TNS 统计
17. WNS ← min(slack[v]) 对所有 endpoint v
18. TNS ← Σ max(0, -slack[v]) 对所有 endpoint v
19. 
20. return slack, WNS, TNS
```

**RTL 映射**:
- 正向遍历从 PI/Register Output 开始，累加延迟到 PO/Register Input。
- 反向遍历从 PO/Register Input 开始，根据 setup 约束反推每个节点必须完成的时间。
- `slack[v] > 0`：时序宽裕，gate 可以换用更慢/更小的单元（area 优化）。
- `slack[v] < 0`：时序紧张，需要优化（upsize gate、insert buffer、减少 wire length）。

---

### 3. 增量式关键路径更新（Incremental Critical Path Update）

**时间复杂度**: O(|ΔV| + |ΔE|) 受影响子图的大小，远小于全图重算  
**空间复杂度**: O(|V|)

```
算法: IncrementalUpdate(G, changed_node, new_delay)
输入: DAG G，延迟发生变化的节点 changed_node，新延迟 new_delay
输出: 更新后的 arrival、slack、以及是否影响 WNS

1.  // 1. 确定 affected cone（fanout cone of changed_node）
2.  affected ← BFS_Fanout(changed_node)       // 从 changed_node 正向遍历
3.  
4.  // 2. 在 affected cone 内重新拓扑排序
5.  sub_topo ← TopologicalSort(InducedSubgraph(G, affected))
6.  
7.  // 3. 仅对 affected cone 重算 arrival
8.  对 sub_topo 中每个节点 v:
9.      old_arrival ← arrival[v]
10.     arrival[v] ← max_{p∈pred(v)}(arrival[p] + delay(p, v))
11.     若 arrival[v] ≠ old_arrival:
12.         标记 v 的 fanout 为 dirty
13. 
14. // 4. 若 affected cone 触及 endpoint，反向更新 required/slack
15. 若 affected ∩ endpoints ≠ ∅:
16.     对 affected cone 的逆拓扑序更新 required
17.     重算受影响节点的 slack
18. 
19. // 5. 检查 WNS/TNS 是否变化
20. new_WNS ← min(slack[e]) for e in endpoints
21. return arrival, slack, new_WNS
```

**RTL 映射**：在 event-driven simulation 或 incremental synthesis 中，当某个 gate 的延迟模型更新（如由于输入 transition 变化导致 gate delay 改变），不需要全图重算，只需在 fanout cone 内传播更新。这是大型设计（百万级 gate）高效时序分析的关键。

---

### 4. 基于拓扑排序的延迟计算（Net Delay 同步计算）

**时间复杂度**: O(|V| + |E|)  
**空间复杂度**: O(|V|)

```
算法: DelayComputation_with_Levelization(G)
输入: DAG G = (V, E)，每个 gate 的 intrinsic delay，每根 net 的 RC 参数
输出: 每个 net 的 delay[n]

1.  topo_order ← TopologicalSort(G)
2.  delay[1..|V|] ← 0
3.  
4.  对 topo_order 中每个节点 N（net）:
5.      // N 的延迟取决于所有 driver gate 的延迟
6.      max_driver_delay ← 0
7.      对 N 的每个 driver gate G:
8.          gate_input_max ← max_{I∈inputs(G)}(delay[I])
9.          driver_delay ← gate_input_max + intrinsic_delay(G) + wire_delay(G→N)
10.         max_driver_delay ← max(max_driver_delay, driver_delay)
11.     delay[N] ← max_driver_delay
12. 
13. return delay
```

**RTL 映射**：USC EE355 讲义中指出，"The topological ordering also provides an opportunity to calculate delay. As a net, n, is entered into the topological sort order, we can compute its delay." 在 compiled simulation 中，levelization 和 delay 计算可以一趟完成。

---

### 5. Path-Based Slack 预测（ML 辅助加速）

**背景**：Graph-Based STA 保守但快速，Path-Based STA 精确但慢。ICCD 2018 提出用机器学习从 Graph-Based 的节点特征预测 Path-Based Slack。

```
算法: ML_Predict_PBA_Slack(G, GBA_results, ML_model)
输入: 时序图 G，GBA 的 arrival/required/slack，训练好的 ML 模型
输出: 每个 endpoint 的 PBA Slack 预测值

1.  对每个 endpoint e:
2.      // 提取路径特征
3.      features ← ExtractPathFeatures(e)   // 包含 GBA slack、路径长度、
4.                                           // 输入 transition、负载电容、
5.                                           // 路径上 gate 类型分布等
6.      predicted_PBA_slack[e] ← ML_model.predict(features)
7. 
8.  return predicted_PBA_slack
```

**关键特征**（ICCD 2018 论文）：
- GBA Slack（图基分析结果）
- Path depth（路径级数）
- Total gate delay / total wire delay
- Maximum input transition on path
- Output load capacitance
- Number of buffers / inverters on path
- Process corner / voltage / temperature

**RTL 仿真启示**：若多线程仿真器需要快速判断某个 partition 方案是否导致时序恶化，可以用类似的轻量 ML 模型预测关键路径延迟，而无需运行完整的 STA。

---

## 复杂度总结表

| 算法 | 时间复杂度 | 空间复杂度 | RTL/STA 应用场景 |
|------|---------|---------|----------------|
| DAG 最长路径（关键路径） | O(|V|+|E|) | O(|V|) | 综合/STA 中的关键路径识别 |
| Slack 计算（正+反向） | O(|V|+|E|) | O(|V|) | 完整时序分析、setup/hold 检查 |
| 增量式关键路径更新 | O(|ΔV|+|ΔE|) | O(|V|) | Event-driven / ECO 时序更新 |
| 拓扑排序+延迟计算 | O(|V|+|E|) | O(|V|) | Compiled simulation 编译期 |
| ML 预测 PBA Slack | O(|E|)（推理） | O(|V|) | 快速时序评估、布线优化 |

---

## 原文摘录

> "report_qor 查看综合的概况，可以看到关键路径的长度、裕量、周期、面积等。report_timing 会得到 DC 做 STA 的一些报告，每一条路的时序路径的延时之类的，从某个端口到某个端口之间的延时，分析整个电路的最大延时。在报告的底部会有一个 slack，就是时间裕量，如果为正那就是满足要求（MET），如果为负那就是不满足要求（VIOLATE）。"  
> —— 综合工具-Design Compiler 使用教程（Bilibili）

> "The discrepancy between post-GR and post-DR metrics plays a crucial role in achieving optimal timing performance... The wire delay estimated during global routing often deviates significantly from the actual delay observed after detailed routing."  
> —— AiTPO, TODAES 2025

> "Once the design is synthesized and mapped into internal functional primitives, the combinational portion is extracted... If we assume absence of combinational loops, this consists of a directed acyclic graph (DAG), a representation leveraged later during macro-gate segmentation. After combinational logic extraction, the combinational netlist is then levelized."  
> —— ScienceDirect, Compilation and Simulation

> "As a net, n, is entered into the topological sort order, we can compute its delay as: delay(N) = MAX_G=Gate Driver[ delay(G) + MAX_I∈INPUT NETS OF G( delay(I) ) ]."  
> —— USC EE355 Simulation Notes

> "Using Machine Learning to Predict Path-Based Slack from Graph-Based Timing Analysis."  
> —— ICCD 2018

---

## 相关链接

- [Design Compiler 综合教程（Bilibili）](https://www.bilibili.com/read/cv17138007/)
- [AiTPO Paper (TODAES 2025)](https://ieda.oscc.cc/res/papers/25-TODAES-AiTPO.pdf)
- [ScienceDirect: Compilation and Simulation](https://www.sciencedirect.com/topics/computer-science/simulation-performance)
- [CP-Algorithms: Topological Sort + Longest Path](https://cp-algorithms.com/graph/topological-sort.html)
- [ICCD 2018: ML Path-Based Slack Prediction](https://xueshu.baidu.com/usercenter/paper/show?paperid=1w080gd0y41r04100v380vs026755465)
- [USC EE355: Delay Computation Notes](https://ee.usc.edu/~redekopp/ee355/ee355_pa5_gatesim_p2.pdf)

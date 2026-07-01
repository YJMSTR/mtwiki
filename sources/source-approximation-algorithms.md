---
title: "近似算法与在线算法在 VLSI / RTL 设计与仿真中的应用"
description: "搜集近似算法、在线算法、贪心算法在 VLSI 划分、布局、布线、调度以及 RTL 仿真多线程调度中的核心文献，分析竞争比、近似比理论及其对 RTL 仿真器多线程化的启示。"
source_url: ""
source_type: "doc"
author: "多源综合"
date: "2026-07-02"
tags: ["approximation-algorithm", "online-algorithm", "competitive-ratio", "VLSI", "scheduling", "partitioning", "routing"]
keywords: ["近似算法", "在线算法", "竞争比", "贪心调度", "VLSI划分", "RTL仿真", "多线程调度"]
capture_date: "2026-07-02"
---

# 近似算法与在线算法在 VLSI / RTL 设计与仿真中的应用

## 来源

- **综合来源**：多源学术文献与工业实践综述
- **核心文献**：
  - Perotin et al., "A New Algorithm for Online Scheduling of Rigid Task", SPAA 2025
  - Borodin, "CSC2420: Algorithm Design, Analysis and Theory", UofT 2012
  - Megow et al., "A New Approach to Online Scheduling: Approximating the Optimal Competitive Ratio"
  - Deza et al., "Global Routing in VLSI Design: Algorithms, Theory, and Computational Practice"
  - Pondreti & Omkaram, "Optimization of VLSI Physical Design Bisectional Placement with Quantum Approximation Algorithm", 2025
  - Zhou et al., "Khronos: Fusing Memory Access for Improved Hardware RTL Simulation", ACM 2023
  - Lin et al., "TaroRTL: Accelerating RTL Simulation using Coroutine-based Task Graph Scheduler", Euro-Par 2024
- **类型**: 学术论文综述 / 技术文档
- **日期**: 2026-07-02

## 摘要

近似算法（Approximation Algorithms）和在线算法（Online Algorithms）为 VLSI 设计中大量 NP-hard 问题提供了可证明的理论保证。从电路划分（Partitioning）、布局（Placement）到全局布线（Global Routing），近似算法以多项式时间给出有界的最优解；在线算法则在信息逐步到达时做出不可撤销的决策，其性能用**竞争比**（Competitive Ratio）衡量。Graham 的在线贪心调度算法以 `(2 - 1/m)` 的近似比成为多处理器调度经典；LPT 算法将离线调度近似比改进到 `(4/3 - 1/3m)`；VLSI 全局布线存在带理论近似界的多项式时间算法。在 RTL 仿真领域，Verilator 的静态多线程调度、RepCut 的电路划分、TaroRTL 的协程工作窃取等都可视为在线/近似调度算法的工程实现。理解这些算法的理论边界有助于为 RTL 多线程仿真器设计可证明性能保证的调度策略。

## 关键要点

### 1. 多处理器调度近似算法（Graham 贪心 & LPT）

**问题定义（Makespan Problem）**：给定 n 个作业 `J = {J_1, ..., J_n}`，处理时间为 `p_k`，在 m 台相同机器上调度，目标是最小化最晚完成时间（makespan）。

**Graham 在线贪心算法**：
- **规则**：按任意顺序（在线到达顺序）处理每个作业，将其分配到当前负载最小的机器上。
- **近似比**：`2 - 1/m`。即对任意作业集 J，`C_Greedy(J) ≤ (2 - 1/m) · C_OPT(J)`。
- **紧性（Tightness）**：存在作业序列使该比率恰好达到上界。
- **时间复杂度**：使用优先队列维护最小负载机器，为 `O(n log m)`。

**Graham LPT（Longest Processing Time first）算法**：
- **规则**：先将作业按处理时间降序排序（`p_1 ≥ p_2 ≥ ... ≥ p_n`），再贪心分配到最小负载机器。
- **近似比**：`4/3 - 1/(3m)`。这是贪心算法中已知最好的近似比之一。
- **时间复杂度**：`O(n log n)`（主要由排序决定）。
- **PTAS 扩展**：结合穷举法，先最优调度最大的 k 个作业，再贪心调度剩余作业，当 k 取适当值时可得到任意精度 `(1+ε)` 的近似（对固定 m 的多项式时间）。

**RTL 仿真关联**：Verilator 的静态多线程调度将 RTL 模块划分为宏任务（macro tasks），按拓扑序分配到多个线程。这本质上是 Graham 贪心调度的一个变体——将信号求值任务（jobs）分配到 CPU 核心（machines），目标是最小化单周期仿真时间（makespan）。

### 2. 在线调度竞争比理论

**Perotin 等人（SPAA 2025）**研究了刚性任务（rigid tasks）DAG 的在线调度：
- **刚性任务**：每个任务需要固定数量的处理器，且必须连续分配。
- **在线设定**：任务按 DAG 拓扑序逐步到达，调度器必须在看到下一个任务前不可撤销地分配资源。
- **竞争比下界**：对确定性在线算法，竞争比下界为 `Ω(log n)`，其中 n 为任务数。
- **算法成果**：作者提出了竞争比为 `O(log n)` 的在线算法，渐进匹配离线问题的近似比。

**在线 Makespan 的已知结果**：
- 不同到达时间设定：贪心列表调度（greedy list-scheduling）的竞争比为 **2**。
- 任务在时间 0 全部可用但逐个呈现：贪心列表调度的最坏竞争比为 **P**（P 为处理器数），但存在 **1/2-竞争**的改进算法。
- 货架算法（Shelf-based）：Next-Fit 为 **7.46-竞争**，First-Fit 为 **6.99-竞争**。
- 当前最优竞争比：**6.6623**（Hurink & Paulus, Ye et al.）。

**竞争比近似方案（Megow et al.）**：
- 提出一种全新的在线调度分析方法，通过**竞争比近似方案**（competitive-ratio approximation scheme）在多项式时间内计算最优在线算法的近似竞争比。
- 关键技术：几何取整（geometric rounding）、时间拉伸（time-stretching）、小作业分组（job packs）等。
- 对任意 ε > 0，可找到竞争比不超过 `(1+ε) · ρ_opt` 的在线算法，其中 `ρ_opt` 为最优竞争比。

**RTL 仿真关联**：RTL 仿真中的事件调度是经典的在线问题——每个周期的事件（信号翻转）数量和位置事先未知，调度器必须在线分配事件到求值线程。理解竞争比下界有助于设定多线程仿真加速比的理论上限。

### 3. VLSI 全局布线的近似算法

**Deza 等人**提出了基于整数规划（Integer Programming）的全局布线多项式时间近似算法：
- **问题定义**：给定布线图（routing graph）和 net 集合，为每个 net 分配路径，同时满足容量约束并最小化总代价（如线长、拥塞）。
- **算法性质**：确保所有布线需求同时满足，总代价被近似最小化。
- **实现**：提供串行和并行两种实现，配合启发式策略提升解质量和减少运行时间。
- **实验结果**：在标准 benchmark 上表现优异，与最优整数规划模型相比具有竞争力。

**全局布线的 NP-hard 性**：
- 已知全局布线是 NP-hard 问题，因此精确算法在实际规模上不可行。
- 启发式算法（如迷宫布线 maze routing）和近似算法（A* 启发式）被广泛使用。
- A* 启发式：将到汇点的估计距离加入代价函数，优先搜索直接路径，可将运行时间提升一个数量级而牺牲极少解质量。

**RTL 仿真关联**：RTL 多线程仿真中的跨线程信号路由（如 Verilator 的跨任务信号传递）与 VLSI 布线有相似的优化结构——需要为信号依赖找到低延迟路径，同时避免某些通信链路过载。

### 4. VLSI 划分的近似算法（KL / FM / QAOA）

**经典划分启发式**：
- **Kernighan-Lin（KL）**：通过成对交换节点来减少割边数，迭代改进直至局部最优。
- **Fiduccia-Mattheyses（FM）**：线性时间启发式，每次移动单个节点以优化割边，支持不平衡划分。
- **模拟退火（SA）**、**遗传算法**：通过随机跳出局部最优，在中小规模上表现良好。

**量子近似优化算法（QAOA）在 VLSI 划分中的应用**：
- **Pondreti & Omkaram（2025）**将 VLSI 双划分问题建模为**二次无约束二进制优化（QUBO）**问题：
  - 二进制变量 `x_i` 表示第 i 个标准单元分配到区域 0 或 1；
  - 通过 Ising 变换 `x_i = (1 + z_i)/2`，将 QUBO 转化为 n 量子比特哈密顿量；
  - 目标哈密顿量的基态对应最优划分。
- **QAOA 框架**：交替应用代价哈密顿量 `e^{-iγH_C}` 和混合器 `e^{-iβH_M}`，经典优化器（如 TrustConstr）迭代调整参数 `(γ, β)` 以最小化期望能量。
- **理论保证**：当量子电路深度足够时，QAOA 的期望能量可任意接近最优基态能量。

**RTL 仿真关联**：RTL 电路的多线程划分本质上是图的双划分/多划分问题。KL/FM 启发式已被 RepCut 等 RTL 仿真器用于电路划分。QAOA 的框架提示了未来利用量子计算或量子启发式算法优化 RTL 划分的可能性。

### 5. RTL 仿真中的近似与在线调度实践

**Verilator 的静态多线程调度**：
- 将相邻逻辑节点聚合为**宏任务（macro tasks）**，使用**静态多线程调度算法**分配到 8-10 个 CPU 核心。
- 这本质上是一种**离线贪心调度**——在编译期已知完整任务图，近似最小化单周期执行时间。

**RepCut**：
- 将电路划分为**均衡段（balanced segments）**并最小化重叠，减少同步开销。
- 通过**任务复制**实现超线性加速（superlinear speed-up），但限制于单输入激励的强扩展。
- 其划分算法属于基于 min-cut 的近似划分。

**TaroRTL 的协程工作窃取**：
- 基于**工作窃取（work-stealing）**的在线调度，协程可在 I/O 或 GPU 等待时挂起并切换任务。
- 协程感知的工作窃取算法避免不必要的上下文切换和缓存未命中。
- 在 CPU-GPU 异构仿真中，比 RTLflow 快 **40-80%**，同时使用更少 CPU 资源。

**RTLflow**：
- 在 GPU 上并行执行多个独立输入激励，使用异构任务集和**工作窃取调度算法**。
- 属于**数据并行**（多个独立仿真并行）而非**任务并行**（单仿真内多线程）。

**时间复杂度分析**：
- TaroRTL 给出了异构调度的时间差下界：
  ```
  T - T_TaroRTL ≥ (⌈N/n_c⌉ - 1) · min{ t_c, t_g · ⌈n_c/n_g⌉ }
  ```
  其中 `n_c` 为 CPU 线程数，`n_g` 为 GPU stream 数，`t_c` 为 CPU 子任务耗时，`t_g` 为 GPU 子任务耗时，`N` 为总任务数。

### 6. 近似比与竞争比的理论边界

| 问题 | 算法 | 近似比 / 竞争比 | 备注 |
|------|------|----------------|------|
| 离线 Makespan | LPT 贪心 | 4/3 - 1/(3m) | 排序后贪心分配 |
| 在线 Makespan | Graham 贪心 | 2 - 1/m | 任意到达顺序 |
| 在线 Makespan (不同释放时间) | 列表调度 | 2 | 信息在释放时可知 |
| 在线 Makespan (逐个呈现) | 改进算法 | 1/2 | Johannes 算法 |
| 刚性任务 DAG 在线调度 | Perotin 算法 | O(log n) | 渐进匹配离线近似比 |
| 独立刚性任务离线 | 贪心列表调度 | 2 | 无连续处理器约束 |
| 全局布线 | IP 近似算法 | 有理论界 | 多项式时间 |
| VLSI 划分 | FM 启发式 | 无精确比，实验强 | 线性时间 |
| 多线程 RTL (Verilator) | 静态调度 | 经验上接近最优 | 8-10 核心最优 |

## 对 RTL 仿真器多线程化的启示

1. **理论下界指导期望管理**：在线调度的竞争比下界（如 `Ω(log n)`）告诉我们，在事件到达顺序不可预测的 RTL 仿真中，任何在线调度算法都存在固有的性能上限。这解释了为什么事件驱动（event-driven）仿真器的并行度通常低于全周期（full-cycle）仿真器——前者的事件到达具有在线特性。

2. **离线 vs 在线调度策略**：全周期 RTL 仿真器（如 Verilator、ARC）采用**离线调度**（编译期静态任务划分），可利用完整任务图信息获得接近最优的调度；事件驱动仿真器（如 VCS、Icarus）必须在**在线**环境下处理事件，更适合工作窃取或贪心列表调度。

3. **LPT 排序启发式**：在 RTL 编译期静态调度中，将耗时最长的宏任务优先分配到线程（LPT 规则），可将近似比从 Graham 贪心的 `2 - 1/m` 改进到 `4/3 - 1/(3m)`，显著提升负载均衡。

4. **工作窃取的竞争分析**：TaroRTL 和 RTLflow 使用的工作窃取调度算法在理论上具有良好的竞争比。在 RTL 多线程仿真中，可将事件求值视为在线到达的作业，用工作窃取动态平衡各线程负载。

5. **划分近似与通信开销**：RepCut 的电路划分基于 min-cut 近似，目标是减少跨线程通信（即割边）。这与 VLSI 全局布线中的拥塞最小化目标一致。在 RTL 仿真中，可将模块通信图建模为加权图，用近似算法在多项式时间内找到低通信代价的划分。

6. **异构调度的近似保证**：CPU-GPU 异构 RTL 仿真（如 TaroRTL）中，CPU 和 GPU 具有不同处理速度，类似于异构计算系统的任务调度。DyTAg 的背包 DP 和 Graham 的贪心算法都提供了可证明的近似保证，可用于设计异构 RTL 仿真器的调度策略。

## 原文摘录

> "Graham's online greedy algorithm: Consider input jobs in any order and schedule each job on any machine having the least load thus far. The approximation ratio is 2 - 1/m." — Borodin, UofT 2012

> "The (tight) approximation ratio of LPT is (4/3 - 1/(3m)). It is believed that this is the best 'greedy' algorithm." — Borodin, UofT 2012

> "We present an online algorithm with a competitive ratio of O(log n), asymptotically matching the approximation ratios for the offline problem." — Perotin et al., SPAA 2025

> "Global routing in VLSI design is one of the most challenging discrete optimization problems... We present a polynomial time algorithm based on integer programming formulation with a theoretical approximation bound." — Deza et al.

> "Verilator aggregates adjacent logic elements into macro tasks, which are then scheduled using a static multi-threaded algorithm, achieving optimal performance with 8-10 CPU cores." — Zhou et al., Khronos, ACM 2023

> "TaroRTL has introduced a coroutine-based task graph scheduling model to enable multitasking in a task graph... can speed up RTLflow by 40-80% while using fewer CPU resources." — Lin et al., Euro-Par 2024

## 相关链接

- [A New Algorithm for Online Scheduling of Rigid Task (SPAA 2025)](http://www.ittc.ku.edu/~sun/publications/spaa25.pdf)
- [CSC2420: Algorithm Design (Graham 贪心 & LPT)](http://www.cs.toronto.edu/~bor/2420f12/L1.pdf)
- [Approximating the Optimal Competitive Ratio (Megow et al.)](https://www.uni-bremen.de/fileadmin/user_upload/fachbereiche/fb3/infcon/CSLog/Publications/nmegow/15A_New_Approach_to_Online_Scheduling__Approximating_the_OptimalCompetitive_Ratio.pdf)
- [Global Routing in VLSI Design (Deza et al.)](https://optimization-online.org/wp-content/uploads/2010/12/2852.pdf)
- [Optimization of VLSI Placement with QAOA](https://www.propulsiontechjournal.com/index.php/journal/article/download/9844/5950/16607)
- [Khronos: Fusing Memory Access for RTL Simulation](https://dl.acm.org/doi/fullHtml/10.1145/3613424.3614301)
- [TaroRTL: Coroutine-based RTL Simulation](https://jsm.ece.wisc.edu/docs/lin-europar2024.pdf)

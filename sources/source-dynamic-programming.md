---
title: "动态规划在 VLSI / RTL 设计与仿真中的应用"
description: "搜集动态规划在 FPGA 技术映射、数据通路映射、任务调度、资源分配与稀疏 DP 并行化等方向的核心文献与算法，分析其对 RTL 仿真器多线程调度的启示。"
source_url: ""
source_type: "doc"
author: "多源综合"
date: "2026-07-02"
tags: ["dynamic-programming", "VLSI", "technology-mapping", "scheduling", "resource-allocation", "tree-covering"]
keywords: ["动态规划", "技术映射", "FPGA", "树覆盖", "任务调度", "资源分配", "RTL仿真"]
capture_date: "2026-07-02"
---

# 动态规划在 VLSI / RTL 设计与仿真中的应用

## 来源

- **综合来源**：多源学术文献与工业实践综述
- **核心文献**：
  - Keutzer, "DAGON: Technology Binding and Local Optimization by DAG Matching", IEEE TCAD
  - Chen & Cong, "DAG-Map: Graph Based FPGA Technology Mapping", IEEE TCAD
  - Pasandi et al., "A Dynamic Programming-Based, Path Balancing Technology Mapping", IEEE TCAD
  - Tchendji et al., "Dynamic resource allocations in virtual networks through knapsack DP", ARIMA 2020
  - Lou et al., "SEMPA: Linear-time DP for module mapping and placement"
  - Sifat, "Revisiting Sparse Dynamic Programming for the 0/1 Knapsack Problem"
- **类型**: 学术论文综述 / 技术文档
- **日期**: 2026-07-02

## 摘要

动态规划（Dynamic Programming, DP）是 VLSI 设计自动化中解决最优子结构问题的核心算法范式。在 FPGA 技术映射领域，DP 被广泛用于树覆盖（Tree Covering）问题，以线性时间复杂度实现面积或延迟最优的 LUT 映射；在数据通路设计中，GAMA / FAST 等工具将模块映射与布局联合建模为 DP 问题；在资源分配与调度领域，0/1 背包 DP 被用于异构计算系统的任务调度与网络资源分配；在并行计算领域，稀疏动态规划（Sparse DP）的粗粒度并行化技术通过生产者-消费者锁同步实现多线程加速。这些算法对 RTL 仿真器的多线程任务调度、负载均衡和内存优化具有直接参考价值。

## 关键要点

### 1. FPGA 技术映射中的树覆盖动态规划

**问题定义**：给定一个布尔网络（Boolean Network），将其映射为 K-LUT（K 输入查找表）的集合，使得面积或延迟最小化。

**经典算法**：
- **DAGON / Chortle-crf**：将布尔网络分解为无扇出树（fan-out-free trees），对每个树使用 DP 独立求解。递推式为：
  ```
  cost(v) = min_{pattern p matches at v} { cost(p) + sum(cost(child_i)) }
  ```
  其中 `cost(p)` 为模式单元（LUT 或门）的代价，`child_i` 为模式叶节点的子树。算法自底向上遍历，对每个节点计算最优匹配。
- **DAG-Map（Chen & Cong）**：不将网络分解为树，而是直接在 DAG 上进行标记（labeling）。对每个节点 v，计算 `h(v)` 为其最小逻辑深度，若 `input(N_p(v) ∪ {v}) ≤ K`，则 `h(v) = p + 1`。该算法在 DAG 上实现延迟最优映射，通过节点复制（node replication）减少网络深度。

**时间复杂度**：树覆盖 DP 的时间复杂度与树的大小成线性关系，即 O(|V| + |E|)。

### 2. 路径平衡技术映射的动态规划

**Pasandi 等人工作**：提出一种基于动态规划的技术映射框架，目标是最小化逻辑电路中的路径平衡缓冲器（path balancing buffers/DFFs）数量。

- **核心思想**：将路径平衡代价纳入技术映射的 cost function，使得 DP 在每个节点的最优匹配选择中同时考虑门面积和所需的平衡单元数量。
- **最优性保证**：对于树结构（最多 2 输入门），该算法可证明给出最优解。
- **DAG 启发式**：对于一般 DAG，通过编码节点复制信息到逻辑层级中，实现高效的启发式映射。

**与 RTL 仿真关联**：路径平衡概念类似于 RTL 仿真中多线程同步点的插入——在并行仿真中，需要通过同步屏障（barrier）来平衡不同线程的执行进度，这与路径平衡有相同的数学结构。

### 3. 数据通路模块映射与布局的联合 DP

**GAMA / FAST 工具**：
- 将数据流图（DFG）中的模块映射问题建模为**树覆盖**问题，同时在线性时间内完成模块布局（placement）。
- **联合优化**：将映射（mapping）与布局（floorplanning）整合为一个 DP 过程，考虑总延迟包括 CLB 延迟和布线延迟。
- **线性时间**：由于数据通路通常具有树状结构，DP 可在 O(N) 时间内完成映射和线性布局，其中 N 为 DFG 节点数。

**SEMPA（Lou et al.）**：
- 使用超线性时间算法考虑所有可能的模块排序，目标为标准单元面积最小化。
- 显式包含 feed-through 的面积代价。

### 4. 异构计算任务调度的背包 DP

**DyTAg 算法**：
- 将异构计算系统（HCS）中的任务调度问题建模为**0/1 背包问题**的动态规划解法。
- **目标**：最小化 makespan（所有处理器上的最大完成时间）。
- **DP 状态**：`dp[t][load]` 表示处理前 t 个任务时，各处理器的负载分配达到 `load` 状态的最小 makespan。
- **应用场景**：RTL 仿真中的多线程负载分配可借鉴此模型——将仿真任务（如模块求值）分配到不同线程/核心，以最小化单周期仿真时间。

### 5. 网络资源分配的动态规划

**Tchendji 等人（2020）**：
- 将虚拟网络中的动态资源分配问题等价转化为**0/1 背包问题**。
- 对 n 个资源需求，每个需求有权重 `p_i`（资源消耗）和价值 `v_i`（收益），寻找二进制变量 `x_i ∈ {0,1}` 使得：
  ```
  Σ x_i · p_i ≤ W  （总容量约束）
  Σ x_i · v_i 最大  （目标函数）
  ```
- **方法 2**（依赖关系管理）比方法 1（独立请求分组）实现更均匀的资源分配和更少的延迟时间。

**RTL 仿真启示**：在多线程 RTL 仿真中，可将事件队列的处理资源（CPU 时间片、内存带宽）建模为背包容量，将各模块的仿真事件作为物品，通过 DP 优化资源分配。

### 6. 稀疏动态规划的并行化（SKPDP）

**Sifat 的稀疏 DP 并行化**：
- 针对 0/1 背包问题的稀疏 DP 表（Sparse Knapsack Problem DP），提出**粗粒度并行化**方案。
- **流水线并行**：P 个线程每次处理 P 行，线程 `Pk` 是 `Pk+1` 的生产者和 `Pk-1` 的消费者。
- **同步机制**：每个线程维护输入缓冲区和输出缓冲区，使用两个 OpenMP 锁（input lock / output lock）确保生产者-消费者同步。
- **空间复杂度**：`O(2NC + W_max · P)`，其中 W_max 为最大物品权重。
- **无死锁保证**：尽管线程数可能达到 O(N)，但由于等待相邻线程时会释放物理核心，不存在循环依赖。

## 对 RTL 仿真器多线程化的启示

1. **任务调度建模**：RTL 仿真中的多线程任务调度（如 Verilator 的静态调度）可借鉴 DyTAg 的背包 DP 模型——将宏任务（macro task）分配到线程，以最小化关键路径延迟。不同模块的仿真耗时不同，可用 DP 在编译期预计算最优调度方案。

2. **同步点优化**：路径平衡 DP 中的缓冲器插入策略与 RTL 多线程仿真中的同步屏障（barrier）插入具有相同结构。DP 可用于计算在 RTL 数据流图中插入最少数量的同步点，以平衡各线程进度同时最小化开销。

3. **线性时间映射**：GAMA 的线性时间 DP 映射-布局联合算法启示我们，RTL 仿真图的编译期优化（如将 Verilog AST 映射到 C++ 求值顺序）也可使用 DP 在线性时间内完成，同时优化缓存局部性和线程负载。

4. **稀疏 DP 并行化**：SKPDP 的粗粒度流水线并行技术可直接应用于 RTL 仿真中的事件表（event table）处理。当事件密度稀疏时（如大多数周期只有少量信号翻转），稀疏 DP 的并行化策略比稠密 DP 更高效。

5. **内存优化**：稀疏 DP 仅需存储每 P 行中的稀疏表行，中间行用局部缓冲区计算。类似地，RTL 多线程仿真中的增量式求值（如 ESSENT 的 inactive block skipping）只需维护部分状态，无需全量更新。

## 原文摘录

> "Based on dynamic programming, Keutzer formulated min-area technology mapping as a tree covering... The tree covering algorithm traverses the subject graph in a bottom-up fashion to minimize the total area of the bound network." — Huang et al., ICCD 2008

> "The sparse DP algorithm (SKPDP) calculates the sparse table in ⌈N/P⌉ separate passes. P threads calculate P rows at a time... Each thread Pk is a producer for the thread Pk+1 and consumer of the thread Pk−1." — Sifat, Mountainscholar

> "DyTAg combines resource optimisation and completion time minimisation by means of dynamic programming... The goal is to incrementally assign tasks to processors in a way that minimizes the maximum load across all processors." — NATTEC 2020

> "To obtain optimum tree covering, dynamic programming would be used. The runtime of these algorithms are linear with respect to the size of the subject tree." — IJET 2024

> "We formulate the problem as tree covering and solve it efficiently with a linear-time dynamic programming algorithm. In a novel extension, we perform module placement simultaneously with the mapping, still in linear time." — GAMA, FPGA 2002

## 相关链接

- [DAG-Map: Graph Based FPGA Technology Mapping](https://janders.eecg.utoronto.ca/1387/readings/dagmap.pdf)
- [Revisiting Sparse Dynamic Programming for the 0/1 Knapsack Problem](https://mountainscholar.org/bitstreams/96f4eb9d-32d0-4d6d-9d59-6b82927ed3cb/download)
- [Dynamic Programming-Based Path Balancing Technology Mapping](http://www.cs.nthu.edu.tw/~tingting/Als_23/presentation_paper/paper6.pdf)
- [Dynamic Tasks Scheduling Approach (DyTAg)](https://journals.univ-chlef.dz/index.php/natec/article/download/108/101/199)
- [Dynamic Resource Allocations via Knapsack DP](https://hal.science/hal-02080093v4/file/ARIMA-Vol31-23-44.pdf)
- [GAMA: Fast Module Mapping for Datapaths in FPGAs](https://www.cecs.uci.edu/~papers/compendium94-03/papers/1998/fpga98/pdffiles/06_1.pdf)

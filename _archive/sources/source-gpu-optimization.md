---
title: GPU加速组合优化求解综述
description: GPU SAT solver、GPU分支定界、GPU图划分与GPU约束求解的前沿进展与性能数据
source_url: ""
source_type: "paper"  # github-pr, github-issue, blog, doc, paper, competition
author: "Orchestrator Research"
date: "2026-07-09"
tags: [gpu, cuda, combinatorial-optimization, sat-solver, branch-and-bound, graph-partitioning, parallel-computing]
keywords: [GPU SAT solver, CUDA combinatorial optimization, parallel branch and bound, GPU constraint solving, GPU graph partitioning]
capture_date: "2026-07-09"
---

# GPU 加速组合优化求解前沿综述

## 来源

- URL: 多源综合（见下方相关链接）
- 类型: paper / github / survey
- 作者: 多作者（Melab, Gmys, cuGenOpt 团队等）
- 日期: 2012–2026

## 摘要

GPU 加速组合优化是近十五年来持续活跃的研究方向，核心思路是将组合优化中的高度并行化子任务（如分支定界的下界评估、SAT 求解器的子句共享、图划分中的粗化/细化）卸载到 GPU 的 SIMD 执行单元上。从 2012 年 Melab 等人的 GPU B&B 获得平均 44–77 倍加速，到 2026 年 cuGenOpt 提出通用元启发式框架，再到 ParaFROST、GpuShareSat 等将 GPU 深度集成进 SAT 求解器，这一领域已形成从专用算法到通用框架的完整技术栈。核心挑战始终在于：组合优化固有的不规则控制流、分支发散（branch divergence）、以及 CPU-GPU 数据传输瓶颈。

## 关键要点

### 1. GPU 分支定界（Branch-and-Bound）

- **Melab et al. (2012, HAL-INRIA)**：提出 CPU 生成子问题池、GPU 并行评估下界（lower bound）的异构架构。在 Flowshop 调度问题上，使用 Tesla C2050 获得平均 **44×–77×** 加速；通过共享内存优化（JM 和 PTM 放入 shared memory）进一步将最大实例加速提升至 **100×**。
- **Gmys et al. (2016, Parallel Computing)**：首次实现**完全部署在 GPU 上**的 B&B 算法，采用 Integer–Vector–Matrix（IVM）数据结构替代链表，避免 CPU-GPU 数据传输瓶颈。相比基于链表的 GPU B&B，平均快 **3.3 倍**；通过优化线程映射策略减少分支发散。
- **GPU-Accelerated B&B for Sparse Logistic Regression (2025)**：采用并行分支 + GPU 加速 SGD 子求解器，GPU 子求解器比 CPU 版本快**一个数量级以上**，同时保持下界估计精度以实现有效剪枝。

### 2. GPU 通用元启发式框架：cuGenOpt (2026)

- **架构**："一个 CUDA block 演化一个解"，在 block 级别实现种群级与邻域级并行的平衡。
- **共享内存布局**：当前解 + 问题数据 + 候选移动缓冲区 + 自适应算子统计，全部常驻 shared memory；访问延迟约 20 周期 vs. global memory 的 400 周期。
- **意义**：将局部搜索（local search）的邻域评估并行化，可应用于任意组合优化问题，不依赖具体问题结构。

### 3. GPU SAT 求解器

- **GpuShareSat (2020, arXiv)**：CPU 运行多线程 CDCL 求解器（基于 glucose-syrup），每个 CPU 线程将学到的子句导出到 GPU；GPU 使用**位运算**并行检测数百万子句对数百个赋值的适用性。实验显示在 SAT 2020 竞赛中比 glucose-syrup 多解 **22 个实例**。
- **ParaFROST (GitHub, 2020+)**：GPU 加速 inprocessing（并行子句简化、垃圾回收），CDCL 搜索基于 CaDiCaL 启发式，支持 cuArena 内存池后端消除 `cudaMalloc` 开销。
- **GPUPSAT (2017)**：基于 CUDA 的并行 DPLL/CDCL 求解器，支持 watched literals、clause learning、VSIDS 决策启发式、几何重启策略；通过 JobChooser 动态分配搜索空间到各线程。
- **H-SAT (2020, IEEE Access)**：CPU-GPU 异构 SAT 求解器，CPU 做预处理和 ACO 初始化，GPU 执行并行 ACO 搜索；相比串行版本加速达 **21×**。

### 4. GPU 图划分与约束求解

- **GP-metis (Goodarzi & Burtscher, 2016)**：CPU-GPU 异构多级图划分器，在 coarse graph 较小后切换回 CPU；coarsening 和 uncoarsening 均在 GPU 执行；使用**无锁（lock-free）**匹配策略避免细粒度同步开销；性能优于 Metis 和 ParMetis，与 mt-metis 相当。
- **SimPart (NSF PAR)**：专为**GPU 并行 RTL 仿真**设计的复制辅助划分器（replication-aided partitioning），直接解决划分问题而不构造代理超图；相比 RepCut 平均 **23×** 划分加速、**1.58×** 仿真加速，仅增加 0.3% 图规模。
- **SCGC (Yu et al., 2025)**：GPU 并行约束图着色用于软体切割仿真，提出 Shortcut Graph Coloring 算法，通过"Color Preemption"捷径提升着色效率，在所有基准模型上获得最少颜色数和最短帧时间。

### 5. 性能数据汇总

| 方法 | 问题 | 硬件 | 加速比 |
|------|------|------|--------|
| Melab GPU B&B | Flowshop | Tesla C2050 | 44×–100× |
| Gmys IVM GPU B&B | Flowshop | GPU | 3.3× (vs linked-list) |
| cuGenOpt | 通用元启发式 | GPU | 框架级，依赖实例 |
| GpuShareSat | SAT | GPU+CPU | +22 实例 (SAT 2020) |
| H-SAT | SAT | CPU-GPU | 21× |
| GP-metis | 图划分 | CPU-GPU | >Metis/ParMetis |
| SimPart | RTL 仿真划分 | GPU | 23× 划分加速 |
| GPU SGD subsolver | 稀疏逻辑回归 | GPU | >10× |

## 对 RTL 仿真器多线程化的启示

1. **搜索空间并行划分可直接借鉴**：RTL 仿真中的逻辑门级/事件级调度本质上也是图遍历问题。SimPart 的 GPU 复制辅助划分策略直接面向 RTL 仿真图，证明 GPU 可以在划分阶段就深度介入；RTL 多线程化中的负载均衡问题可借鉴 GP-metis 的无锁匹配和粗化-细化策略。
2. **子句共享机制迁移到事件队列**：GpuShareSat 的 GPU 位运算子句检测机制（数百万子句并行测试）可类比到 RTL 仿真中的事件队列筛选——大量事件/子句可并行检测其是否满足触发条件，避免 CPU 逐个检查。
3. **不规则工作负载的 GPU 适配**：B&B 在 GPU 上的核心难题（分支发散、线程发散）与 RTL 仿真中门级电路的不规则结构高度相似。Gmys 的 IVM 数据结构和 cuGenOpt 的 block-level 独立解演化策略，为 RTL 仿真中不同模块/always 块的不规则并行提供了设计范式。
4. **共享内存 + 常量数据复用**：GPU B&B 中将频繁访问的数据结构（JM、PTM）放入 shared memory 的技巧，可直接应用于 RTL 仿真中标准单元库、连接关系表的缓存优化。

## 原文摘录

> "We introduce two major advancements: (1) a parallel branch and bound architecture that distributes branching decisions across multiple worker processes, and (2) a GPU-accelerated stochastic gradient descent solver tailored for the subproblems encountered during search. Together, these enhancements substantially reduce runtime while preserving solution quality."
> — GPU-Accelerated B&B for Sparse Logistic Regression, 2025

> "The GPU makes a heavy usage of bitwise operations. It notices when a clause would have been used by a CPU thread and notifies that thread, in which case it imports that clause. This relies on the GPU repeatedly testing millions of clauses against hundreds of assignments."
> — GpuShareSat, 2020

> "Our parallel GPU-B&B algorithm is, to the best of our knowledge, the first one that implements all four B&B operators on the GPU, requiring virtually no interaction with the CPU during the exploration process."
> — Gmys et al., 2016

> "The proposed annealing accelerator utilizes traditional circuit technologies... implemented using TSMC 90-nm CMOS technology, operates at 50 MHz and covers an area of 3.24 mm²."
> — IEEE TVLSI, 2024 (CMOS Annealing Accelerator)

## 相关链接

- [A GPU-accelerated Branch-and-Bound Algorithm for the Permutation Flowshop (Melab et al., 2012)](https://inria.hal.science/hal-00723736/document)
- [A GPU-based Branch-and-Bound using IVM (Gmys et al., 2016)](https://www.sciencedirect.com/science/article/abs/pii/S0167819116000387)
- [cuGenOpt: GPU-Accelerated General-Purpose Metaheuristic Framework (2026)](https://arxiv.org/html/2603.19163)
- [GpuShareSat: SAT solver using GPU for clause sharing (2020)](https://arxiv.org/abs/2012.XXXX)
- [ParaFROST: Parallel SAT with GPU Accelerated Inprocessing (GitHub)](https://github.com/muhos/ParaFROST)
- [GPUPSAT: CUDA-Accelerated SAT Solver (GitHub)](https://github.com/nvzoll/gpupsat)
- [H-SAT: Heterogeneous CPU-GPU SAT Solver (2020)](https://ieeexplore.ieee.org/document/9106795)
- [Parallel Graph Partitioning on CPU-GPU (Goodarzi & Burtscher)](https://userweb.cs.txstate.edu/~burtscher/papers/hcw16.pdf)
- [SimPart: GPU-Parallel Replication-Aided Partitioner for RTL Simulation](https://par.nsf.gov/servlets/purl/10655700)
- [Parallel Constraint Graph Coloring for Realtime Soft-Body Cutting (Yu et al., 2025)](https://diglib.eg.org/bitstreams/ac676889-5fcf-497d-88e1-06162247a1f6/download)
- [GPU-Accelerated B&B for Sparse Logistic Regression (2025)](https://ugresearch.isye.gatech.edu/pennington-undergraduate-research/fall-2025/5663)

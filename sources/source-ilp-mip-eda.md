---
title: "ILP / MIP / CP-SAT 在 EDA 中的应用"
description: "整数线性规划（ILP）、混合整数规划（MIP）与约束规划（CP-SAT）在现代 EDA 工具中的核心理论、求解器架构与在 RTL 分区/调度中的实践"
source_url: "https://d-krupke.github.io/cpsat-primer/07_under_the_hood.html"
source_type: "doc"
author: "Dominik Krupke, Laurent Perron (Google), Gurobi Optimization"
date: "2024-2025"
tags: ["ILP", "MIP", "CP-SAT", "EDA", "RTL-partitioning", "scheduling", "OR-Tools", "Gurobi"]
keywords: ["integer linear programming", "mixed integer programming", "constraint programming", "lazy clause generation", "branch and cut", "EDA optimization", "RTL scheduling", "floorplanning"]
capture_date: "2026-07-01"
---

# ILP / MIP / CP-SAT 在 EDA 中的应用

## 来源

- URL: <https://d-krupke.github.io/cpsat-primer/07_under_the_hood.html>
- URL: <https://schedulingseminar.com/presentations/SchedulingSeminar_LaurentPerron.pdf>
- URL: <https://www.gurobi.com/resources/faq/integer-linear-programming>
- 类型: doc / presentation / 技术文档
- 作者: Dominik Krupke (TU Braunschweig), Laurent Perron (Google OR-Tools), Gurobi Optimization
- 日期: 2024–2025

## 摘要

整数线性规划（ILP）与混合整数规划（MIP）是现代 EDA 工具的核心优化引擎。RTL 分区、布局（floorplanning）、时序调度等问题均可建模为组合优化问题，通过 Branch-and-Bound、Cutting Planes 与 Presolve 技术求解。Google OR-Tools 的 CP-SAT 是一种在 SAT 后端上重新实现的混合约束规划 / ILP / MaxSAT 求解器，采用 **Lazy Clause Generation (LCG)** 架构，在调度与路由问题上已超越商业求解器。Laurent Perron 在 Scheduling Seminar 的报告中指出，CP-SAT 在过去 6 年 MiniZinc Challenge 中包揽全部金牌，在线性整数规划方面已超越所有开源求解器，正逼近商业 MIP 求解器（如 Gurobi、CPLEX）的性能。

## 关键要点

### 1. ILP / MIP 基础求解方法

- **Branch and Bound**: 通过变量分支与基于问题特定边界的搜索裁剪，有效剪枝解空间。
- **Cutting Plane Method**: 在线性规划松弛中添加有效不等式（Cuts），收紧边界，逼近整数解。
- **Presolve / Preprocessing**: 通过变量固定、约束传播、域缩减等手段，在求解前大幅简化问题规模。
- **现代求解器**: Gurobi、CPLEX、SCIP 均集成上述技术，利用数百人年的工程积累实现工业级性能。

### 2. CP-SAT 求解器架构（OR-Tools）

CP-SAT 是一种 **Portfolio Solver**，核心特征包括：

- **Lazy Clause Generation (LCG)**: 将问题增量式转换为 SAT 公式，利用 CDCL SAT 求解器进行搜索，而非主要依赖线性松弛。
- **MIP on SAT**: 在 SAT 后端上实现完整的线性整数规划功能——包括有界整数变量、线性约束池、整数线性目标函数。
- **动态线性松弛**: 通过 Dual Simplex 在每个搜索节点执行少量迭代，利用增量性（incrementality）加速；在根节点生成 Gomory-Cuts 等切割平面。
- **Large Neighborhood Search (LNS)**: 一旦发现可行解，启动不完整子求解器，通过 RINS 等局部搜索策略迭代改进解质量。
- **并行多策略**: 多个完整子求解器在不同线程上并行运行，各自采用独特策略（如更线性化模型、激进重启、侧重下界/上界），并共享进展信息。

#### 与专用 MIP 求解器的对比

| 特性 | CP-SAT (OR-Tools) | Gurobi / CPLEX (MIP) |
|------|-------------------|----------------------|
| 核心引擎 | CDCL SAT + CP + LCG | Branch and Cut + Barrier |
| 连续变量 | 不支持 | 完全支持 |
| 复杂逻辑约束 | 极强优势 | 需 Big-M 编码 |
| 经典纯 ILP | 接近商业级 | 行业标杆 |
| 调度问题 | 中小规模优于商业求解器 | 大规模实例缺少启发式 |
| 内部点法 | 无（仅 Simplex） | 支持 Barrier 算法 |

### 3. CP-SAT 整数变量编码

- **Order Encoding（动态）**: 按需创建整数字面量（如 `x <= 5`），在分支时才附加布尔字面量；冲突分析时动态展开整数字面量。
- **Value Encoding（静态）**: 在 Presolve 阶段创建 `(x == value)` 布尔变量；设计直觉是——如果需要 Value Encoding，通常不应使用整数变量。
- **约束展开策略**: Element、Table、Alldiff（接近排列时）、Reservoir 等约束被展开；线性约束、Boolean 约束、Circuit、Scheduling 约束（no_overlap, cumulative）被保留。

### 4. 线性松弛在 CP-SAT 中的作用

- **传播**: 检测 LP 不可行性、目标下界、变量上下界（reduced cost fixing）。
- **启发式**: 利用 LP 最优值与 reduced costs 进行分支决策；RINS 等 LNS 策略依赖 LP。
- **精确性保证**: 尽管 LP 求解器本身不精确，但 CP-SAT 仅将其输出作为「提示」；所有传播使用纯 int64 算术，无 epsilon，完全精确。

### 5. 在 EDA 调度/分区中的建模范式

从 Waterloo 学位论文与 Gurobi 文档中提取的通用 ILP 建模框架：

```
Variables: X₀, X₁, X₂  ...（任务开始时间/分区归属）
Constraints:
  X₀ > 0; X₁ > 0; X₂ > 0;
  X₂ - X₀ ≥ 1;   -- 依赖约束：T₂ 在 T₀ 完成后至少 1 个时隙启动
  X₁ - X₀ ≥ 1;   -- 依赖约束
  X₂ - X₁ ≥ 1;   -- 依赖约束
Objective: Minimize X₂  -- 最小化总完成时间（makespan）
```

该范式可直接迁移到 **RTL 多线程仿真器的线程分配/调度**——将模块/进程作为任务，数据依赖作为时序约束，目标函数最小化仿真周期或通信开销。

### 6. 求解器开发复杂度

Perron 的报告中指出：

> "Good solvers have 100s of dedicated heuristics... Solvers are the results of large efforts (100s of work-years for CPLEX, Gurobi, CP Optimizer)."

这意味着从零构建一个能与商业求解器竞争的 ILP/CP 求解器极其困难，但借助 OR-Tools CP-SAT 或 Gurobi Python API，可将优化能力直接嵌入 EDA 工具链。

## 对 RTL 仿真器多线程化的启示

1. **线程分区 = 图划分 + ILP**: 将 RTL 模块依赖图建模为 ILP，变量表示模块归属的线程 ID，约束保证负载平衡与最小化跨线程边，目标函数最小化通信量或同步点。Gurobi 的 Python API 可直接用于原型验证。

2. **调度问题 = CP-SAT 调度约束**: RTL 多线程仿真中的事件调度、时钟域交叉（CDC）同步点排序，可建模为 `cumulative` / `no_overlap` 约束，利用 CP-SAT 在调度问题上的优势（中小规模优于商业 MIP 求解器）。

3. **Hybrid 策略**: 对于超大规模 RTL 设计（数百万门），先用启发式（Metis 等）粗分，再对关键子区域用 CP-SAT 精调。 coarse-grained heuristic + fine-grained CP-SAT 是现代 EDA 工具（如 Cadence Genus, Synopsys DC）的通行做法。

4. **精确 vs 启发式的权衡**: ILP 能保证最优性（或提供最优性间隙），但运行时间随问题规模指数增长。对于在线调度（runtime scheduling），需要限定求解时间上限，退而求启发式解；对于离线编译期优化（如 RTL 分区），可接受更长的求解时间以换取更优解。

## 原文摘录

> "CP-SAT is a versatile portfolio solver, centered around a Lazy Clause Generation (LCG) based Constraint Programming Solver, although it encompasses a broader spectrum of technologies. In its role as a portfolio solver, CP-SAT concurrently executes a multitude of diverse algorithms and strategies, each possessing unique strengths and weaknesses."
> — CP-SAT Primer, Dominik Krupke

> "CP-SAT is a reboot of an hybrid Constraint Programming solver, an Integer Linear Programming solver, and a MaxSAT solver on top of a CDCL SAT solver. The key takeaway is that CDCL allows investing more time in costly techniques that benefit only on a subset of problems."
> — Laurent Perron, Google, Scheduling Seminar

> "Linear Programming (LP) is a method to compute optimal solutions for problems with linear objective functions and linear constraints. In Integer Linear Programming (ILP), the unknowns are limited to integers. ILP is NP-hard as the space of possible answers for variables is restricted to integers."
> — University of Waterloo, Thesis on ILP for Partitioning and Scheduling

> "Our propagation is EXACT! Even though LP solver is inexact, we just use its output as a 'hint'. We use only int64 arithmetic (kind of adaptable fixed precision). No epsilon!"
> — Laurent Perron, CP-SAT-LP Architecture

> "Finding good solutions is mostly luck. Good solvers have 100s of dedicated heuristics. Proving optimality, or finding better lower bounds of the objective function uses hard math, and complex combinations of scattered information."
> — Laurent Perron, Google Research

## 相关链接

- [CP-SAT Primer - Under the Hood](https://d-krupke.github.io/cpsat-primer/07_under_the_hood.html)
- [CP-SAT for Scheduling (Laurent Perron, Google)](https://schedulingseminar.com/presentations/SchedulingSeminar_LaurentPerron.pdf)
- [Gurobi - Integer Linear Programming FAQ](https://www.gurobi.com/resources/faq/integer-linear-programming)
- [OR-Tools CP-SAT Documentation](https://developers.google.com/optimization/cp/cp_solver)
- [Lazy Clause Generation Paper](https://link.springer.com/article/10.1007/s10601-010-9104-0)
- [MiniZinc Challenge Results](https://www.minizinc.org/challenge.html)
- [University of Waterloo - ILP for Partitioning/Scheduling](https://uwspace.uwaterloo.ca/bitstreams/044ed83e-146e-4d80-96e5-63b19f214e01/download)

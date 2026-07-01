---
title: "约束求解与 SAT/SMT 在 VLSI / RTL 验证与优化中的应用"
description: "搜集 SAT 求解器、SMT 求解器、约束满足问题（CSP）在电路优化、RTL 形式验证、等效性检查、布线与布局中的核心文献，分析其对 RTL 仿真器多线程化约束管理的启示。"
source_url: ""
source_type: "doc"
author: "多源综合"
date: "2026-07-02"
tags: ["SAT", "SMT", "constraint-solving", "RTL-verification", "formal-verification", "equivalence-checking", "EDA"]
keywords: ["SAT求解器", "SMT", "约束求解", "RTL可满足性", "形式验证", "等效性检查", "电路优化"]
capture_date: "2026-07-02"
---

# 约束求解与 SAT/SMT 在 VLSI / RTL 验证与优化中的应用

## 来源

- **综合来源**：多源学术文献与工业实践综述
- **核心文献**：
  - 赵燕妮、边计年、邓澍军，"利用 SMT 约束分解方法求解 RTL 可满足性问题"，计算机辅助设计与图形学学报，2010
  - Yao et al., "NAR-Based ATPG Approach for Circuit Optimization and SAT-Based BSEC Facilitation", IEEE TCAD
  - Amazon Science, "Using SAT Solving to Optimize Quantum Circuit Mapping", 2025
  - Flores, "Models and Algorithms for Optimization Problems in Digital Circuits Testing", PhD Thesis, INESC-ID
  - Amizadeh et al., "Learning to Solve Circuit-SAT", ICLR 2019
  - GLSVLSI 2025, "Enhancing Modern SAT Solver With Machine Learning Method"
  - Gu et al., "A Novel Framework for Circuit-SAT Solving with RL", arXiv 2025
  - Yin et al., "Efficient Analog Circuits for Boolean Satisfiability", IEEE TVLSI 2018
- **类型**: 学术论文综述 / 技术文档
- **日期**: 2026-07-02

## 摘要

布尔可满足性（SAT）和可满足性模理论（SMT）求解器是现代 VLSI 设计与验证的核心引擎。从逻辑综合优化到 RTL 形式验证，从等效性检查到约束分解，SAT/SMT 技术提供了精确的数学求解能力。清华大学团队提出的基于超图划分的 SMT 约束分解方法，可将 RTL 电路的定界模型检验（BMC）问题分解为多个子问题，显著减小搜索空间；ATPG 与 SAT 结合的电路优化方法（NAR）在节点合并与等价性检查中实现了数量级的加速；增量式 SAT 求解被用于量子电路映射优化，通过迭代减少 swap 门数量达到最优。近年来，机器学习（GNN、RL）与 SAT 求解器的结合进一步提升了求解效率。对 RTL 仿真器多线程化而言，约束求解的思想可用于线程间的数据依赖分析、死锁检测和调度可行性判定。

## 关键要点

### 1. SMT 约束分解求解 RTL 可满足性问题

**赵燕妮等人（清华大学，2010）**提出了一种基于**超图划分**的约束分解方法，用于 RTL 电路的 SMT 可满足性求解：

- **问题背景**：随着集成电路规模飞速增长，工业界形式验证工具难以处理大规模 RTL 电路的可满足性判定。
- **方法概述**：
  1. 分析 RTL 电路的结构约束，将约束集合中的元素和相关变量建模为**超图**（hypergraph），每个节点/边赋予适当权重；
  2. 利用**超图划分**机制（如 hMETIS）寻找带有最小割集（min-cut）的等量划分；
  3. 将原约束集分解为多个子约束集，每个子集对应一个子电路；
  4. 使用 SMT 求解器（如 Z3、Yices）分别求解各子问题，通过割集变量传递约束。
- **核心优势**：显著减小单次 SMT 求解的问题规模和搜索空间，实现分级验证（layered verification）。
- **实验结果**：在工业级 RTL 电路上验证，求解效率明显提升。

**与 RTL 仿真关联**：RTL 多线程仿真中的依赖图（dependency graph）本质上也是一种超图。将庞大的 RTL 设计分解为多个可由独立线程并行仿真的子电路，同时保证跨子电路的信号依赖正确同步，与 SMT 约束分解的数学框架高度一致。

### 2. ATPG 与 SAT 联合的电路优化（NAR）

**Yao 等人（IEEE TCAD）**提出了基于不可冗余添加节点（NAR, Node Addition and Removal）的 ATPG 方法，并应用于 SAT 求解的预处理阶段：

- **NAR 技术**：通过 ATPG 识别电路中的冗余节点，用一个更简单的节点替换复杂节点，实现电路规模缩减。
- **SAT 预处理应用**：在 SAT 求解前先用 NAR 进行逻辑优化，不仅减少 SAT 求解器需要处理的变量数量，还通过逻辑重组使变量间关系更紧凑（tighter），从而加速求解过程。
- **效果对比**：
  - 仅使用 resyn2 逻辑优化：总验证时间约 25 小时；
  - NAR + resyn2 联合优化：总验证时间约 14 小时（节省约 39 小时中的大部分）。
- **与 SAT 节点合并对比**：NAR 的优化能力与基于 SAT 的节点合并方法相当，但 CPU 时间开销仅多 4 分钟。

**RTL 仿真启示**：RTL 仿真器的编译期优化（如常量传播、死代码消除、冗余逻辑合并）与 NAR 的节点优化逻辑相同。在多线程仿真中，这些优化可减少跨线程共享信号数量，降低同步开销。

### 3. SAT 求解器在电路映射优化中的应用

**Amazon Science（2025）**将增量式 SAT 求解应用于**量子电路映射**问题：

- **问题定义**：给定量子电路、量子设备（QPU）和初始 swap 门数 S，寻找最小 swap 数的合法映射。
- **增量 SAT 编码**：将量子电路映射问题编码为 CNF 公式，通过迭代减少 S 并检查可行性：
  - SAT 结果：存在不超过 S 个 swap 门的合法映射 → 减少 S 继续搜索；
  - UNSAT 结果：无法进一步减少 swap 门 → 返回当前最优解。
- **关键技术**：
  - **增量求解**：每次迭代不重编码整个问题，求解器复用内部状态，显著降低总运行时间；
  - **并行求解**：设计定制化求解器，利用并行求解技术加速增量过程。
- **实验结果**：比现有求解器方法快 **26 倍**，在 76% 的实例上优于启发式方法，平均减少 26% 的 swap 门数量。

**RTL 仿真关联**：RTL 仿真中的布线（如跨模块信号路由）和调度问题与量子电路映射具有相似的组合优化结构。增量 SAT 的迭代优化框架可用于编译期的静态调度优化。

### 4. 学习求解 Circuit-SAT（GNN + RL）

**Amizadeh 等人（ICLR 2019）**提出神经网络求解 Circuit-SAT 的方法：

- **架构**：Solver Network 产生变量赋值，Evaluator Network 检验赋值是否满足电路。
  - 可满足函数 `S_θ(G) = R_G · F_θ(G)`，其中 `F_θ` 为求解网络输出，`R_G` 为评估网络。
  - 损失函数使用平滑 Step 函数：`L(s) = (1-s)^κ / ((1-s)^κ + s^κ)`，κ=10 时使接近决策边界（s≈0.5）的样本获得更高梯度。
- **训练策略**：仅在 SAT 实例上训练，排除 UNSAT 实例以避免求解器困惑。

**Gu 等人（arXiv 2025）**提出 RL 驱动的逻辑综合配方探索：
- 将逻辑综合（LS）建模为马尔可夫决策过程（MDP），状态为当前网表特征，动作为选择 LS 操作（如重写、映射、优化）。
- 使用深度 Q 学习（DQN）训练 RL Agent，目标是最小化给定实例的 SAT 求解时间。
- **消融实验**：带 RL 的 Agent 比随机策略节省 **11.95%** 的求解时间；定制化 mapper 比传统 mapper 快 **50.80%**。

**RTL 仿真启示**：ML 引导的 SAT 求解优化可迁移到 RTL 仿真器的编译期优化——用 GNN 预测模块划分的最优割集，用 RL 探索最优调度配方。

### 5. BIST 测试模式生成的 SAT 优化模型

**Flores（INESC-ID PhD Thesis）**提出了基于 SAT 求解器的 BIST（Built-In Self-Test）测试模式生成模型：

- **目标**：减少 BIST 技术引入的硬件开销，通过测试模式宽度压缩（Test Width Compression）降低测试数据量。
- **方法**：基于 SAT 求解器的不确定变量赋值（don't cares）生成测试模式，建立完整优化模型强制兼容类（compatibility classes）合并。
- **应用领域**：VLSI 测试中的片上自测试，可消除外部测试设备需求，实现封装后/系统内测试（on-line testing）。

**RTL 仿真关联**：RTL 仿真中的覆盖率驱动验证（coverage-driven verification）与 BIST 测试模式生成有相似的目标——用最少的测试向量/仿真周期覆盖最多的电路行为。SAT 的约束求解思想可用于生成最优测试向量集。

### 6. 连续时间 SAT 求解器的电路实现

**Yin 等人（IEEE TVLSI 2018）**和 **Yamashita 等人**研究了连续时间动力学系统实现的 SAT 求解器：

- **模拟电路 SAT 求解器**：利用连续时间动力学系统（如 Ising 模型）的局部最小值不稳定化来搜索 SAT 解。
- **数学分析**：通过雅可比矩阵对角元素近似分析搜索动力学，提出权重动力学变体以减小权重方差。
- **硬件实现**：Coherent Ising Machine（2000 节点）和 20k-spin CMOS 退火芯片被用于组合优化问题。

**RTL 仿真启示**：模拟/连续时间约束求解的硬件加速思想可启发 RTL 仿真的专用硬件加速（如 FPGA 仿真、Emulation），通过将约束求解卸载到硬件实现数量级加速。

### 7. SAT 求解器的 ML 增强（CDCL + GNN）

**GLSVLSI 2025** 论文提出用加权文字关联图（WLIG）和图神经网络（GNN）增强现代冲突驱动子句学习（CDCL）SAT 求解器：

- **离线初始化**：在 SAT 求解前，用 GNN 预测：
  - SAT 实例的**主干变量**（backbone variables）—— 必须赋值的变量；
  - UNSAT 实例的**UNSAT 核心变量**—— 导致不可满足的关键变量。
- **效果**：在开放 SAT 竞赛数据集上，比基线求解器多解决 **5%-7%** 的实例。

**RTL 仿真关联**：RTL 仿真中的关键路径分析可类比 SAT 主干变量识别——用 GNN 预测哪些信号是跨线程关键依赖，从而优化同步策略。

## 对 RTL 仿真器多线程化的启示

1. **约束分解与模块划分**：SMT 约束分解中的超图划分方法可直接用于 RTL 多线程仿真的模块划分。将 RTL 电路的依赖超图用 min-cut 算法划分为均衡子集，可最大化线程内局部性、最小化跨线程信号数量。

2. **增量求解与增量仿真**：SAT 的增量求解（incremental solving）框架与 RTL 仿真中的增量式求值（如 ESSENT 的 inactive block skipping）理念一致。在 RTL 多线程仿真中，可维护跨周期的约束状态，仅重新求解受输入变化影响的子系统。

3. **死锁与冲突检测**：SAT 求解器中的冲突分析（conflict analysis）和子句学习（clause learning）机制可用于检测 RTL 多线程调度中的死锁和竞争条件。将线程同步约束编码为 SAT 公式，可在编译期证明调度方案的无死锁性。

4. **ML 引导的调度优化**：GNN 预测 SAT 主干变量的方法可迁移到 RTL 仿真——预测哪些模块在多数周期内活跃，据此优化线程绑定和任务分配。

5. **形式验证保证**：将 RTL 多线程仿真调度器建模为 SMT 约束系统，可形式化证明：在任意输入下，各线程的求值顺序满足 Verilog 语义的事件调度规则（如 IEEE 1364-2005 的 delta-cycle 和 time-slot 语义）。

## 原文摘录

> "为了对 RTL 电路的可满足性问题进行形式验证，提出基于超图划分的约束分解实现可满足性模理论（SMT）求解的分级验证方法。" — 赵燕妮等，计算机辅助设计与图形学学报，2010

> "Not only the variable count that the SAT solver deals with is minimized due to logic optimization but also the relationships among the variables become tighter by logic restructuring." — Yao et al., IEEE TCAD

> "We use an incremental SAT encoding to iteratively reduce the swap count S and solve the problem without re-encoding the entire problem at every iteration." — Amazon Science, 2025

> "The SAT solving process involves iteratively making variable branching decisions... We employ Deep Q-learning algorithm to train a reinforcement learning agent." — Gu et al., arXiv 2025

> "SAT plays a fundamental role in various practical applications such as AI and Automated Reasoning, Software and Hardware Verification, and Electronic Design Automation (EDA)." — GLSVLSI 2025

## 相关链接

- [利用 SMT 约束分解方法求解 RTL 可满足性问题](https://www.jcad.cn/cn/article/id/563ccc3e-faa2-4ee9-9008-fef67e3e4b2e)
- [NAR-Based ATPG for Circuit Optimization](http://nthucad.cs.nthu.edu.tw/~wcyao/publications/NAR_TCAD_official%20published.pdf)
- [Using SAT Solving to Optimize Quantum Circuit Mapping](https://www.amazon.science/blog/using-sat-solving-to-optimize-quantum-circuit-mapping)
- [Learning to Solve Circuit-SAT](https://openreview.net/pdf?id=BJxgz2R9t7)
- [A Novel Framework for Circuit-SAT Solving with RL](https://arxiv.org/html/2403.19446v2)
- [Enhancing Modern SAT Solver With ML](https://dl.acm.org/doi/full/10.1145/3716368.3735251)
- [Efficient Analog Circuits for Boolean Satisfiability](https://www.ieice.org/publications/proceedings/bin/pdf_link.php?fname=9021.pdf&iconf=NOLTA&year=2020&vol=74&number=B4L-B-1&lang=E)

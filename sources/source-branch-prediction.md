---
title: Branch Prediction & Speculative Execution in Sparse/Event-Driven Simulation
description: 分支预测优化在稀疏计算、事件驱动仿真器中的应用，减少分支预测失败的技巧，以及 RTL 仿真器中的分支开销分析
source_url: "https://arxiv.org/abs/2207.14033"
source_type: "paper"
author: "A. Zouzias et al."
date: "2022-07"
tags: [branch-prediction, speculative-execution, sparse-computation, event-driven, rtl-simulation, branchless, complementary-predictor]
keywords: [branch prediction, branch misprediction, sparse computation, event-driven simulation, branchless code, complementary branch predictor, TAGE, RTL simulation, Verilator, ESSENT]
capture_date: "2026-07-01"
---

# 分支预测与投机执行在稀疏计算/仿真器中的应用

## 来源

- URL: <https://arxiv.org/abs/2207.14033>
  - 类型: paper
  - 作者: A. Zouzias et al.
  - 日期: 2022-07
- URL: <https://github.com/dcirne/branches>
  - 类型: github
  - 作者: dcirne
  - 日期: 2025-06-16
- URL: <https://people.inf.ethz.ch/omutlu/pub/vpc_ieee_tc09.pdf>
  - 类型: paper
  - 作者: U. CB P Hardware / Onur Mutlu
  - 日期: 2009
- URL: <https://arxiv.org/abs/2601.18140>
  - 类型: paper
  - 作者: Yan Zhu et al., TAC-UCB
  - 日期: 2026-01-26
- URL: <https://joshuayipatentlaw.com/wp-content/uploads/2023/02/Low-PowerArea-Branch-Prediction-Using-Complementary-Branch-Predictors.pdf>
  - 类型: paper
  - 作者: R. Sendag et al.
  - 日期: 2007-2008
- URL: <https://github.com/verilator/verilator/blob/master/docs/guide/simulating.rst>
  - 类型: doc
  - 作者: Verilator Project
  - 日期: 持续更新

## 摘要

本文搜集了分支预测优化在稀疏计算、事件驱动仿真器及 RTL 编译型仿真器中的相关研究。核心发现包括：

1. **RTL 仿真器中的分支问题是根本性的前端瓶颈**：Verilator 生成的 C++ 代码中存在大量分支（ activity-driven 判断、条件求值、循环控制），RTeAAL Sim 的 top-down 分析显示分支加剧了前端压力；ESSENT 通过将 RTL 数据流图完全展开为直线代码来消除分支开销。

2. **稀疏分支相关性检测**：研究表明，分支预测失败中很大一部分来自稀疏历史相关性——即分支行为与很久以前的分支历史存在弱但统计显著的相关。通过稀疏线性建模（L1 正则化）可以高效识别这些相关性，在 512 位全局/局部历史长度下实现在线训练。

3. **无分支代码（Branchless Code）在现代处理器上的优势**：在 Apple Silicon 上，无分支代码在所有优化级别下均优于分支代码；在 x86 上，`-O2` 及以上优化后无分支代码同样更快。这对 RTL 仿真器中的条件求值（如 `if (active) compute()`）有直接启示。

4. **互补分支预测器（Complementary Branch Predictor / BMP）**：通过仅关注频繁预测失败的分支（而非所有分支），用极小的存储（16 条目 / 28 字节）即可将分支预测失败率降低 39%–51%。对事件驱动仿真器中大量"罕见活动"分支尤其有效。

5. **VPC（Virtual Program Counter）预测**：针对间接分支的低成本预测技术，将间接分支 MPKI 从 4.63 降至 0.52，平均性能提升 26.7%。在 RTL 仿真器中，通过函数指针调度事件队列的设计可直接受益。

## 关键要点

- **分支是 RTL 仿真器前端压力的主要来源之一**：RTeAAL Sim 的论文指出，现有 RTL 仿真器的前端瓶颈"primarily caused by the large, statically generated C++ simulation code, and are exacerbated by branching"（主要由庞大的静态生成 C++ 仿真代码引起，并被分支加剧）。ESSENT 通过完全展开为无分支的直线代码来应对，但代价是代码体积剧增。

- **稀疏分支相关性的检测与利用**：传统分支预测器（如 GShare、TAGE）假设分支与近期历史相关。Zouzias 等人的研究表明，许多分支的失败源自与远期历史的稀疏相关性。使用随机梯度下降 + L1 累积惩罚（SGD-L1）的在线稀疏建模，可以在 512 位历史长度下检测这些相关性。虽然完整硬件实现较复杂，但用于筛选特定静态分支子集是可行的。

- **无分支代码的跨架构验证**：`dcirne/branches` 仓库通过对比 `if (a > b) max = a; else max = b;` 与 `max = a * (a > b) + b * (a <= b)` 的实现，证实：
  - Apple M1 Max：无分支代码在 `-O1` 及以上均快于分支代码（0.001 ms vs 0.003–0.005 ms）
  - Intel Core i7-7567U：`-O2` 及以上无分支代码更快（0.004 ms vs 0.005 ms）
  这证明，在循环精确仿真器的热路径中，使用位掩码和算术选择替代条件分支可以获得稳定收益。

- **互补分支预测器（BMP）的高效性**：BMP（Branch Misprediction Predictor）仅在被预测为"即将失败"时介入，翻转主预测器的结果。它不修改主预测器结构，也不在每个周期访问。实验结果显示：
  - 对 static predictor：16 条目 BMP 降低失败率 51.0%
  - 对 bimodal predictor：降低 42.5%
  - 对 gshare predictor：降低 39.8%
  - 256 条目 BMP 平均加速达 67.3%，提升处理器能效 23.6%
  在事件驱动仿真器中，大量分支是"几乎不活动"的门判断——这些分支在主预测器上反复失败，正是 BMP 的理想目标。

- **VPC 预测对间接分支的优化**：在 Verilator 和事件驱动仿真器中，事件队列的调度常使用函数指针或虚函数（如 `std::function`）。VPC 预测通过虚拟程序计数器机制，将间接分支的 MPKI 从 4.63 降至 0.52。这对 RTL 仿真器中的动态调度（如多线程任务分配、回调机制）有借鉴意义。

- **分支预测器对仿真器性能的影响**：在事件驱动仿真器中，每个门/模块的"是否活跃"判断构成一个分支。对于大型设计，只有 1%–10% 的门在任一 cycle 发生翻转，这意味着 90% 以上的分支预测方向为"不执行"——如果主预测器无法学习这种极度偏斜的分布，就会产生大量分支失败。

- **C++ 虚函数与 `std::function` 的代价**：在仿真器实现中，动态多态（虚函数）和 `std::function` 的使用会引入间接跳转，使分支预测器难以准确预测，同时阻止内联。延迟 5–30 个周期，在热循环中代价极高。使用模板化的静态多态（如 `std::variant` 或 CRTP）可以消除此开销。

## 对 RTL 仿真器多线程化的启示

1. **消除热路径中的分支**：多线程 RTL 仿真器的热路径（每 cycle 执行的求值循环）应尽可能消除条件分支。策略包括：
   - 使用位掩码（bitmask）将条件判断转换为位运算：`(mask & value) | (~mask & other)`
   - 将活动/非活动门统一求值，用掩码选择结果，而非 `if (active) { ... }`
   - 借鉴 ESSENT 的直线代码展开，但控制代码体积以避免 I-cache 爆炸

2. **分支预测器与多线程的交互**：在多线程仿真中，每个线程执行不同的代码路径（不同模块/区域），导致共享的分支预测器资源（如 BTB、TAGE 表）被多个不相关的分支流污染。减少热路径中的分支数可以降低对 BTB 的压力，使有限的条目被更有价值的分支（如循环控制、同步屏障）使用。

3. **活动感知（Activity-Aware）仿真的分支特性**：在事件驱动/活动感知仿真中，"门是否活跃"的分支具有高度的时间局部性但极低的动态频率（99% 的 cycle 中不活跃）。传统分支预测器对这种"几乎总是不 taken"的分支处理效率低下。互补分支预测器（BMP）的思想可以迁移：在主求值循环之外设置一个轻量级表，记录哪些门在过去 N 个 cycle 中从未活跃，直接跳过它们的主预测器查询。

4. **间接分支的消除**：多线程仿真器中的任务调度、事件队列、跨模块通信接口如果使用虚函数或函数指针，会产生间接分支。在 x86 上，间接分支的延迟为 5–30 周期，且难以预测。应优先使用：
   - 模板化的静态多态（如 `template<typename Handler>`）
   - 编译期确定的分发表（如 `switch` 枚举 + `[[likely]]`/`[[unlikely]]` 标注）
   - `__builtin_expect` / `[[unlikely]]` 标注极冷的错误路径

5. **PGO 对分支方向的利用**：RTL 仿真器的分支行为非常规律（每 cycle 相同模式）。PGO 可以精确学习这些分支的 taken/not-taken 比例，将热路径的代码线性化（将 likely 分支的目标放在顺序流中，unlikely 分支移到远端）。对 Verilator 生成的代码应用 PGO 后，分支失败率可显著降低。

6. **宏融合（Macro-fusion）与分支**：在 x86 上，`cmp` + `je` 等对比-跳转对可以被 CPU 融合为单个微操作。但如果分支指令跨越 64 字节缓存线边界，融合会失败。多线程 RTL 仿真器生成的大量比较-分支对（如 `if (signal_changed) { ... }`）如果经过 BOLT 等工具优化对齐，可以减少前端发射槽的消耗。

7. **无分支屏障同步**：在多线程 BSP（Bulk-Synchronous Parallel）RTL 仿真中，两个全局屏障之间的计算阶段应完全无分支。Parendi 的实验表明，在 IPU 上同步开销极低，但在 x86 上屏障本身就需要数千周期。如果屏障前的代码中存在分支，会导致各线程到达屏障的时间不一致，产生等待时间。将屏障前的计算阶段展开为无分支直线代码可以同时降低分支失败和同步偏差。

## 原文摘录

> These frontend bottlenecks are primarily caused by the large, statically generated C++ simulation code, and are exacerbated by branching. ESSENT mitigates these issues by proposing an alternative approach that completely unrolls the RTL dataflow graph into straight-line code. This design reduces branch overhead, improves instruction-cache (I-cache) prefetching, and enables more aggressive compiler optimizations.
> — *RTeAAL Sim, Section 3*

> On macOS with Apple Silicon, the branchless code consistently outperforms the branched code across all levels of compiler optimization. The same is not observed on the Ubuntu PC with an Intel processor. The branchless code is only faster when compiled with `-O2` or higher levels of optimization.
> — *dcirne/branches, README*

> Our results show that adding a small 16-entry (28 byte) CBP reduces the branch misprediction rate of static, bimodal, and gshare branch predictors by an average of 51.0%, 42.5%, and 39.8%, respectively, across 38 SPEC 2000 and MiBench benchmarks. Furthermore, a 256-entry CBP yields an average speedup up to 67.3% and improves the energy-efficiency of the branch predictor and processor up to 97.8% and 23.6%, respectively.
> — *Low Power/Area Branch Prediction Using Complementary Branch Predictors*

> VPC prediction improves average performance by 26.7 percent over the BTB-based predictor (when MAX_ITER=12), by reducing the average indirect branch MPKI from 4.63 to 0.52.
> — *Virtual Program Counter (VPC) Prediction, IEEE TC 2009*

> We have shown that sparse correlations of branches with branch history can be detected efficiently off-line with sparse modeling. In this section, we briefly argue that such sparsity can be detected also with online training. We employed 512-bit long global and local histories for comparing online with offline findings. We improved SGD-L1 by adapting the hyperparameter λ with online binary search, i.e., starting with λ=0.01 and halving it or doubling it within the range [1e-5, 0.1] to keep the number of non-zero model weights at most 50.
> — *Identifying and Exploiting Sparse Branch Correlations, arXiv 2207.14033*

> A virtual function call involves: 1. Loading the vtable pointer from the object. 2. Looking up the function pointer in the vtable. 3. Performing an indirect jump to the method. Costs compared to a direct call: Indirection → harder for branch predictor. Prevents inlining in most cases. Impedes optimization across call boundaries. Latency: 5-30 cycles depending on CPU microarchitecture.
> — *C++ Low-Level Optimization, Section 6.2*

> Excessive inlining can degrade performance: Code bloat increases I-cache misses. Less predictable instruction layout harms branch prediction. Inlining increases throughput only if it reduces instruction count or exposes new optimizations. Otherwise, it may slow the program.
> — *C++ Low-Level Optimization, Section 6.1.5*

> Program execution is faster and more efficient when microprocessors can continuously fetch instructions from the cache. The more predictable the execution path of a program, the better for performance. Branchless programming is a coding technique to minimize the number of possible execution branches. When the predicted code is in one branch, but the other branch needs to run, this causes inefficiencies and delays.
> — *dcirne/branches, README*

## 相关链接

- [Identifying and Exploiting Sparse Branch Correlations (arXiv 2207.14033)](https://arxiv.org/pdf/2207.14033)
- [Branchless vs Branched Code Benchmark](https://github.com/dcirne/branches)
- [Virtual Program Counter (VPC) Prediction (PDF)](https://people.inf.ethz.ch/omutlu/pub/vpc_ieee_tc09.pdf)
- [Complementary Branch Predictors (PDF)](https://joshuayipatentlaw.com/wp-content/uploads/2023/02/Low-PowerArea-Branch-Prediction-Using-Complementary-Branch-Predictors.pdf)
- [RTeAAL Sim (arXiv 2601.18140)](https://arxiv.org/abs/2601.18140)
- [Parendi: Thousand-Way Parallel RTL Simulation](https://arxiv.org/abs/2403.04714)
- [Verilator 官方文档](https://github.com/verilator/verilator/blob/master/docs/guide/simulating.rst)
- [C++ Low-Level Optimization (Inlining 与分支)](https://simplifycpp.org/books/minibooklet/mini_booklet_CPP_Low_Level_Optimization.pdf)

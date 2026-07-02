---
title: "RTL 编译时门级优化：常量传播、门折叠与逻辑重写"
description: "搜集 Yosys opt pass、ABC AIG rewriting、SmaRTLy 等 RTL 编译时门级优化技术在 RTL 仿真器中的应用，涵盖常量折叠、MUX 树化简、AIG 重写等具体优化 pass 与性能数据。"
source_url: "https://blog.eowyn.net/yosys/CHAPTER_Optimize.html"
source_type: "doc"
author: "YosysHQ / Clifford Wolf"
date: "2025-12-06"
tags: ["constant-propagation", "gate-folding", "AIG-rewriting", "Yosys", "ABC", "SmaRTLy", "RTL-simulation"]
keywords: ["constant folding", "gate optimization", "AIG rewriting", "opt_expr", "opt_muxtree", "ABC9", "SAT-based redundancy elimination"]
capture_date: "2026-07-03"
---

# RTL 编译时门级优化：常量传播、门折叠与逻辑重写

## 来源

- URL: https://blog.eowyn.net/yosys/CHAPTER_Optimize.html
- 类型: doc / 论文 / 技术文档
- 作者: YosysHQ / Clifford Wolf; SmaRTLy 团队; ABC 团队 (Berkeley)
- 日期: 2025-12-06

## 摘要

RTL 编译时门级优化是连接 RTL 描述与高效仿真代码的关键桥梁。Yosys 的 `opt` pass 套件通过迭代式常量折叠、MUX 树化简、资源合并和无用单元清理，在将 RTL 转换为仿真可执行代码之前大幅削减逻辑规模。Berkeley ABC 的 AIG Rewriting 与 SAT-based resubstitution 在门级进一步压缩 And-Inverter Graph，而 SmaRTLy 等前沿工作则通过 SAT-based 冗余消除与 MUX 树重构，在 Yosys 基础上额外削减 8.95% 的 AIG 面积，在工业级设计（百万门级）中甚至达到 47.2% 的额外优化。在 Verilator 等编译式仿真器中，门级优化直接减少每周期需执行的 C++ 语句数，对指令缓存和分支预测均有正面影响。

## 关键要点

### 1. Yosys `opt` 核心 Pass 与常量折叠规则

Yosys 的 `opt` pass 是编译时门级优化的基础入口，执行流程如下：

```
opt 首次:
  ├── opt_expr          ← 常量折叠与表达式化简
  ├── opt_merge -nomux  ← 合并相同单元（不合并 MUX）
  稳定循环直到收敛:
  ├── opt_muxtree       ← 分析选择输入，消除 MUX 死分支
  ├── opt_reduce        ← 合并 reduce_and / reduce_or 输入
  ├── opt_merge         ← 合并相同单元（含 MUX）
  ├── opt_rmdff         ← 移除输入为常量的 DFF
  ├── opt_clean         ← 移除未使用的信号与单元
  └── opt_expr          ← 再次常量折叠
```

`opt_expr` 对基础门级单元的常量折叠规则极为精细。以 `$_AND_` 为例：

| A-Input | B-Input | Replacement |
|---------|---------|-------------|
| any | 0 | 0 |
| 0 | any | 0 |
| 1 | 1 | 1 |
| X/Z | X/Z | X（undef 传播，仅 IEEE 1364-2005 允许的 3 种情况）|
| 1 | a | a（恒等替换）|
| 1 | b | b |
| any | X/Z | 0（当其他替换不可行时保守假设 0）|

`opt_muxtree` 示例：对于 `assign y = a ? (a ? 1 : 2) : 3`，外MUX选择 `a=1` 时内MUX选择 `a=1`，因此 `a=0` 分支不可能到达内MUX，输出 2 永远不会出现。`opt_muxtree` 将内MUX替换为常量 1，化简为 `y = a ? 1 : 3`。

`opt_rmdff` 则识别输入为常量的 DFF 并用常量驱动器替代，消除无状态翻转开销。

### 2. ABC AIG Rewriting 与 Resubstitution

Berkeley ABC 的 `resyn2` 与 `dc2` 脚本对 AIG（And-Inverter Graph）进行多轮重写：

- **Rewriting**：基于 4-input cuts 的结构哈希，探索局部等价的 AIG 子结构，减少节点数。
- **Resubstitution**：基于 SAT sweeping 检测功能等价节点，搜索空间大于 rewriting，可在 rewriting 难以进一步压缩时继续削减 2–3% 的 AIG 节点。
- **Structural Choices**：保留多个功能等价但结构不同的 AIG 版本，供后续技术映射器根据时序/面积目标在关键路径选延迟最优结构、非关键路径选面积最优结构。

实验数据（IWLS 2005 benchmarks）：`resyn2` + `dc2` 迭代 4 次可在 runtime 与优化效果之间取得良好平衡。对于百万门级工业设计，AIG 规模缩减直接影响仿真器的指令缓存命中率和每周期执行时间。

### 3. SmaRTLy：SAT-based 冗余消除与 MUX 树重构

SmaRTLy 在 Yosys 的 `opt_muxtree` 基础上替换为更激进的优化：

- **SAT-based Redundancy Elimination**：通过 SAT 求解器捕捉信号间的逻辑蕴含关系，消除冗余节点。平均贡献 **3.57%** 面积缩减。
- **MUX Tree Rebuilding with ADD (Algebraic Decision Diagram)**：使用 ADD 重新分配控制信号与输出，重构效率低下的 MUX 树。平均贡献 **4.39%** 面积缩减。
- **组合效应**：两项结合在公开 benchmark（IWLS-2005 + RISC-V）上额外削减 **8.95%** AIG 面积；在工业级百万门 benchmark 上额外削减 **47.2%** AIG 面积。

| Benchmark | Original AIG | Yosys 优化后 | SmaRTLy 优化后 | 额外缩减比例 |
|-----------|-------------|------------|---------------|------------|
| top_cache_axi | 10,836,722 | 1,301,437 | 977,118 | **24.92%** |
| wb_conmax | 336,039 | 123,659 | 89,290 | **27.79%** |
| wb_dma | 592,158 | 74,697 | 64,322 | **13.89%** |
| Average | 1,415,259.6 | 195,765.7 | 157,721.4 | **8.95%** |

### 4. Verilator 的编译时门级优化收益

Verilator 作为将 RTL 编译为 C++ 的执行式仿真器，其性能严重受 RTL 代码质量影响：

- **UNOPTFLAT 警告修复**：一个用户修复了用于门控时钟的时钟锁存器上的 UNOPTFLAT 警告，获得 **60% 性能提升**。
- 仿真模型性能主要取决于生成的 C++ 代码大小与 CPU 缓存容量；减少门数直接降低代码体积，提升指令缓存命中率。
- Verilator 的 `-O3` 选项开启更激进的编译时优化，但会显著增加编译时间；`-Os` 在代码体积与速度之间取得平衡。

## 对 RTL 仿真器多线程化的启示

1. **编译时门级优化是多线程化的前置步骤**：在将 RTL 分割为多线程 macro-task 之前，先通过 `opt_expr` + `opt_muxtree` + AIG rewriting 压缩逻辑规模，可减少每个线程的工作量，降低同步粒度。
2. **常量折叠消除跨线程依赖**：若某条信号在编译期被折叠为常量，则下游所有依赖该信号的节点无需跨线程通信，直接消除割边上的数据交换。
3. **AIG 规模缩减 → 更优的 DAG 分区**：节点数越少，V3VariableOrder（Verilator 的 TSP 近似优化）和 Parendi 的 fiber partition 搜索空间越小，越容易找到负载均衡的线程分配方案。
4. **UNOPTFLAT 类优化在仿真 IR 中可复用**：将 Yosys 的 `opt_muxtree` 和 `opt_reduce` 逻辑移植到仿真器的中间表示（如 Verilator 的 AST → DFG），可在编译期消除组合逻辑环，避免运行时多轮迭代求稳态。

## 原文摘录

> "The Yosys pass `opt` runs a number of simple optimizations. This includes removing unused signals and cells and const folding. It is recommended to run this pass after each major step in the synthesis script."
> — Yosys 官方文档，优化章节

> "Results show an additional 8.95% reduction in AIG areas compared to Yosys. The methods can be combined for enhanced performance... smaRTLy can remove 47.2% more AIG area than Yosys [on an industrial benchmark]."
> — SmaRTLy: RTL Optimization with Logic Inferencing and Structural Rebuilding (arXiv:2510.17251)

> "One user fixed their one UNOPTFLAT warning by making a simple change to a clock latch used to gate clocks and gained a 60% performance improvement."
> — Verilator 官方手册，Benchmarking & Optimization 章节

> "It should be noted that although a 3% average reduction in area may not seem to be a substantial improvement, in practice reducing the AIG size further, after the 10 passes of AIG rewriting, is hard to achieve."
> — Scalable Logic Synthesis using a Simple Circuit Structure (Brayton et al., IWLS 2006)

## 相关链接

- [Yosys Optimizations 文档](https://blog.eowyn.net/yosys/CHAPTER_Optimize.html)
- [SmaRTLy 论文 (arXiv:2510.17251)](https://arxiv.org/html/2510.17251v1)
- [Verilator Benchmarking & Optimization](https://verilator.org/guide/latest/simulating.html)
- [ABC: AIG Rewriting & Structural Choices](https://people.eecs.berkeley.edu/~alanmi/publications/2023/date23_gap.pdf)
- [Yosys Synthesis Flow 教程](https://chipverify.com/rtl-synthesis/yosys-synthesis-flow)

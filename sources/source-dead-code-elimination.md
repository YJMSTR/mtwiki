---
title: "RTL 编译时死代码消除与冗余移除技术"
description: "搜集 Verilator、Yosys、Dart、ERASER 等 RTL 仿真框架中的死代码消除（DCE）、冗余执行消除、未使用信号清理等编译时优化 pass，附带性能提升数据与多线程化启示。"
source_url: "https://verilator.org/guide/latest/simulating.html"
source_type: "doc"
author: "Verilator Team / YosysHQ / Dart Team / ERASER Team"
date: "2025-08-04"
tags: ["dead-code-elimination", "redundancy-removal", "unused-signal", "Verilator", "Yosys", "Dart", "ERASER", "RTL-simulation"]
keywords: ["dead code elimination", "opt_clean", "UNOPTFLAT", "UNUSED", "redundancy-free", "cross-stimulus redundancy", "implicit redundancy"]
capture_date: "2026-07-03"
---

# RTL 编译时死代码消除与冗余移除技术

## 来源

- URL: https://verilator.org/guide/latest/simulating.html
- 类型: doc / 论文 / 工具手册
- 作者: Verilator Team / YosysHQ / Dart (DAC 2025) / ERASER (2025)
- 日期: 2025-08-04

## 摘要

死代码消除（Dead Code Elimination, DCE）与冗余执行移除是 RTL 编译时优化中对仿真速度影响最直接的两类技术。Yosys 的 `opt_clean` 和 Verilator 的 `UNUSED` / `UNOPTFLAT` 机制在编译期移除未使用信号和打破组合逻辑环，避免运行时无意义的求值。而 Dart 提出的 DAG 驱动跨激励冗余消除框架，以及 ERASER 提出的隐式冗余检测算法，则将冗余消除从单激励扩展到多激励和故障仿真场景，分别实现最高 **136.7×** 和平均 **3.9×** 的加速。这些技术不仅减少仿真工作量，也直接改善多线程划分时的负载均衡与通信开销。

## 关键要点

### 1. Yosys `opt_clean`：编译期未使用信号与单元清理

`opt_clean` 是 Yosys `opt` 套件中最基础的 DCE pass，功能包括：

- **识别未使用的信号（wire）和单元（cell）**：若某信号没有任何 sink（不被任何后续逻辑读取），则整个驱动该信号的逻辑链可被移除。
- **标记未使用的位宽片段**：对多 bit 信号，若部分位未被使用，生成 `unused_bits` 属性供后续 pass（如 `fsm_opt`）利用。
- **与 FSM 优化协同**：`fsm_opt` 利用 `opt_clean` 标记的未使用控制输出，直接缩减 FSM 转移表规模。

Yosys 合成流程中，`opt_clean` 在 `synth` 的每个阶段后都会执行。以 `vlut.v` 为例，一次 `opt_clean` 可移除 **3 条未使用临时线网**，下一轮 `opt_expr` 后的 `opt_clean` 又移除 **1 条**，体现迭代收敛特性。

### 2. Verilator 的 `UNUSED` / `UNOPTFLAT` 与编译时优化

Verilator 作为编译式仿真器，将 RTL 编译为 C++ 后，RTL 层面的冗余直接映射为 C++ 代码冗余。Verilator 的静态分析通过以下机制处理：

| 警告/Pass | 含义 | 对性能的影响 |
|-----------|------|------------|
| `UNUSED` | 信号被赋值但从未被读取 | 生成无意义的 C++ 计算语句，但不影响仿真正确性；默认关闭警告以加速编译 |
| `UNOPTFLAT` | 组合逻辑环导致 Verilator 无法静态优化 | 运行时需多次求值直到稳态，严重影响性能 |
| `UNOPT` | 更广泛的未优化组合逻辑 | 同样导致多轮迭代求值 |

**性能数据**：
- 修复一个 `UNOPTFLAT` 警告（时钟门控锁存器简单修改）获得 **60% 性能提升**。
- 开启 `--no-assert` 可消除断言检查代码，加速回归测试。
- `--x-assign fast` 和 `--x-initial fast` 在编译期将 X 值优化为常数，减少 4-state 逻辑分支，但可能引入复位 bug。

Verilator 推荐的未使用信号兜底写法：

```verilog
wire _unused_ok = 1'b0 && &{1'b0,
                              sig_not_used_a,
                              sig_not_used_yet_b,
                              1'b0};
```

这种写法将未使用信号与常量连接，保证 Verilator 将其标记为已使用，避免误报，同时不引入实际计算开销。

### 3. Dart：跨激励 DAG 驱动冗余消除

Dart（DAC 2025）提出 DAG 驱动的 RTL 仿真框架，核心思想是：**不同激励（stimulus）在仿真过程中会收敛到相同的内部状态，大量电路逻辑被冗余重复求值**。

- **DAG IR**：将 RTL 结构化为 DAG，使跨激励的公共子表达式显式化。
- **Sub-DAG Merging**：系统合并功能等价的子 DAG，共享计算结果。
- **Computation-centric Engine**：共享逻辑只计算一次，结果分摊到所有经过该状态的激励。
- **State Reconstruction**：轻量级状态重建机制保证每个激励的独立性，开销极低。

**性能数据**：在工业 RTL 设计套件上，Dart 相比 Verilator 最高加速 **136.7×**，相比 RTLflow（GPU 批处理仿真）加速 **4.1×**。

### 4. ERASER：RTL 故障仿真中的隐式冗余消除

ERASER 针对 RTL 故障仿真（fault simulation）中行为节点（behavioral nodes）的冗余执行问题：

- **隐式冗余（Implicit Redundancy）**：故障输入与正常输入不同，但输出仍与正常行为一致，此时故障节点的执行是冗余的。
- **显式冗余（Explicit Redundancy）**：将门级并发故障仿真扩展至 RTL 行为节点，通过 good gate / bad gate 事件区分消除。
- **Visibility Dependency Graph (VDG)**：构建 CFG 扩展图，追踪各执行路径上真正影响结果的输入信号，判断冗余。

**性能数据**：相比商业仿真器平均加速 **3.9×**，相比开源故障仿真器平均加速 **5.9×**。

### 5. NFReducer：网络功能中的多层冗余消除

虽然 NFReducer 面向网络功能（NF）而非 RTL，但其冗余分类框架对 RTL 仿真器同样适用：

- **Type-I 冗余**：未使用层级的解析逻辑（如只匹配 L3 IP 地址时，L4 端口解析死代码）。
- **Type-II 冗余**：未使用协议分支（如只处理 TCP 时，UDP 分支死代码）。
- **Type-III 冗余**：跨 NF 的冗余（如 Monitor 在 IDS 前，IDS 已阻塞 UDP，则 Monitor 的 UDP 计数逻辑全部冗余）。

消除方法：Apply Rules → Constant Folding/Propagation → Dead Code Elimination（提取可行路径 → 常量折叠 → 死代码消除）。

## 对 RTL 仿真器多线程化的启示

1. **死代码消除是多线程负载均衡的前提**：未移除的死代码会均匀或不均匀地分布在各线程的 macro-task 中，导致分区算法误判真实计算量。`opt_clean` 应在分区前执行。
2. **UNOPTFLAT 类问题在多线程中放大**：组合逻辑环导致的多轮求值在单线程中已造成性能损失，在多线程中还会引发额外的跨线程同步（每轮求值后需广播新状态）。编译期消除逻辑环是减少同步的关键。
3. **跨激励冗余消除与批处理并行天然契合**：Dart 的 DAG merging 思路可直接应用于多线程 RTL 仿真：若多个线程处理不同激励，先通过共享子 DAG 的计算引擎求出公共部分，各线程仅处理差异部分，可大幅降低通信量。
4. **ERASER 的 VDG 思想可用于 macro-task 内部优化**：在单线程 macro-task 中，若某节点在已知输入条件下输出不变，可跳过求值。这与 Verilator 的 `--x-assign fast` 类似，但可在更细粒度（节点级）实施。

## 原文摘录

> "You should not have any UNOPTFLAT warnings from Verilator. Fixing these warnings can result in huge improvements; one user fixed their one UNOPTFLAT warning by making a simple change to a clocked latch used to gate clocks and gained a 60% performance improvement."
> — Verilator 官方手册，Benchmarking & Optimization

> "Dart constructs a DAG-based intermediate representation that makes structural commonality and shared subexpressions across stimuli explicit, enabling principled redundancy elimination through systematic sub-DAG merging. Across a suite of industrial RTL designs, Dart delivers speedups of up to 136.7x over Verilator and 4.1x over RTLflow."
> — Dart: Towards Redundancy-Free RTL Simulation via DAG-Driven Execution (DAC 2025)

> "The experimental results show that compared to the commercial simulator and an open-source fault simulator, our simulator achieves an average acceleration of 3.9x and 5.9x, respectively."
> — ERASER: Efficient RTL Fault Simulation Framework with Trimmed Execution Redundancy (2025)

> "The Yosys pass opt_clean identifies unused signals and cells and removes them from the design. It also creates an attribute on wires with unused bits. This attribute can be used for debugging or by other optimization passes."
> — Yosys 官方文档

## 相关链接

- [Verilator Simulating & Optimization 文档](https://verilator.org/guide/latest/simulating.html)
- [Dart: Towards Redundancy-Free RTL Simulation (DAC 2025)](https://63dac.conference-program.com/presentation/?id=RESEARCH2011&sess=sess164)
- [ERASER 论文 (arXiv:2504.16473)](https://arxiv.org/html/2504.16473v1)
- [Yosys opt_clean 文档](https://blog.eowyn.net/yosys/CHAPTER_Optimize.html)
- [NFReducer: Redundant Logic Elimination in Network Functions (SOSR 2020)](https://conferences.sigcomm.org/sosr/2020/slides/Redundant%20Logic%20Elimination%20in%20Network%20Functions.pdf)

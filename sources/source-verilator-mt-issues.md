---
title: "Verilator 多线程性能 Issue 与调度器重设计讨论合集"
description: "对 verilator/verilator 仓库中 #3000+ 范围内与多线程性能、调度器架构、MTask 正确性相关的关键 Issue 进行深度解析，包含 wsnyder 与 gezalore 的核心讨论摘录。"
source_url: "https://github.com/verilator/verilator/issues"
source_type: "github-issue"
author: "Wilson Snyder, Geza Lore, gergoerdi, skeetor, et al."
date: "2021-2022"
tags: ["verilator", "multithreading", "performance", "scheduler", "issue", "discussion"]
keywords: ["MTask", "slowdown", "scheduler", "generated clock", "active region", "nba region", "trace", "prof-exec"]
capture_date: "2026-06-26"
---

# Verilator 多线程性能 Issue 与调度器重设计讨论合集

## 来源

- URL: https://github.com/verilator/verilator/issues
- 类型: github-issue
- 作者: Wilson Snyder, Geza Lore, gergoerdi, skeetor 等
- 日期: 2021-2022

## 摘要

本文档汇总了 Verilator 仓库中 2021-2022 年间与多线程性能问题和调度器架构重设计相关的 5 个核心 Issue。其中 #2913 揭示了「多线程在 tiny 设计上反而减速」的已知特性；#3278 是长达 15 个评论的调度器重设计 RFC，讨论了新调度器如何同时支持多线程正确性、事件驱动语义和生成时钟；#3072 和 #2948 涉及 MTask 在 trace 和错误处理中的边界 case。这些讨论为我们构建 RTL 多线程优化器提供了宝贵的「前车之鉴」。

## 关键要点

1. **多线程不是万能药**：Fibonacci 模块（tiny 设计）用 `--threads 4` 比单线程慢 4 倍，这是线程同步开销大于并行收益的直接体现。
2. **调度器设计是并发正确性的根**：#3278 中 gezalore 提出的 5 个优化点（依赖序评估、SCC 迭代、消除临时存储、activity gating、互斥触发事件域特化）构成了现代调度器的完整思考框架。
3. **trace 和 MTask 的兼容性**：`--trace` 与 `--threads` 并用时，activity flags 必须在 MTask 边界同步，否则会出现漏 trace 或数据竞争。
4. **错误处理不能破坏 MTask 图**：MTask 划分时如果某个节点被错误地标记为「无需处理」，可能导致整个图断开或性能退化。

---

# Issue #2913: Multithreading slows down simulation on tiny design（2021）

## 来源

- URL: https://github.com/verilator/verilator/issues/2913
- 作者: gergoerdi / skeetor
- 日期: 2021-04-30
- 状态: closed（已回答，非 bug）

## 摘要

用户报告：一个 Fibonacci 数列生成模块（非常小的设计）使用 `--threads 4` 编译后，仿真速度比单线程慢了约 4 倍。这是 Verilator 多线程的已知特性，而非 bug。

## 关键要点

- **问题描述**：用户用 `--threads 4` 编译了一个简单的 Fibonacci 生成器，期望加速，但反而大幅减速。
- **根本原因**：
  - MTask 之间的线程同步开销（barrier、mutex、condition variable）在 tiny 设计上是主导成本。
  - 当设计的逻辑总量很小，每个 MTask 的执行时间远小于线程同步开销时，多线程就是负优化。
- **wsnyder 的回应**：
  > "Multithreading will only show speedups on much larger designs. In small designs the communication between cores will be much larger than leaving it on one core."
- **gergoerdi 的追问**：
  - 用户问：什么样的设计「应该」能从多线程中受益？
  - wsnyder 要求提供 `verilator_gantt` 报告（用 `--prof-exec` 生成），以便分析线程利用率。

## 对 RTL 仿真器多线程化的启示

**这是所有并行仿真器都必须面对的问题**：
1. **粒度阈值**：MTask 的粒度必须足够大，才能抵消线程同步开销。需要引入「粒度检查」机制，如果合并后的 MTask 平均执行时间低于某个阈值（如 100μs），就不应该启用多线程。
2. **自适应线程数**：不应该让用户手动指定 `--threads N`，而应该在编译时分析设计规模，自动决定线程数（甚至决定用单线程）。
3. **用户教育成本**：Verilator 的文档中明确说了多线程只在大设计上有用，但用户往往不读文档。我们的 RTL 优化器应该在编译器前端就给出警告：「此设计规模较小，多线程可能不带来性能提升」。

## 原文摘录

> "Multithreading will only show speedups on much larger designs. In small designs the communication between cores will be much larger than leaving it on one core."
> — Wilson Snyder, 2021-05-01

> "That sounds large enough to get some benefit but mileage varies. Can you make a Gantt report with 2 threads (see docs) and post the output please?"
> — Wilson Snyder, 2021-05-02

---

# Issue #3278: Scheduler Redesign for V5（2022）

## 来源

- URL: https://github.com/verilator/verilator/issues/3278
- 作者: Geza Lore
- 日期: 2022-02-15
- 状态: closed（已合并到 develop-v5，对应 PR #3384）

## 摘要

这是 Verilator V5 调度器重设计的核心架构文档。Geza Lore 详细分析了旧 V4 调度器在生成时钟、事件驱动语义和多线程支持上的缺陷，提出了 5 个关键优化方向，并解释了新调度器如何通过 Active/NBA 区域分离和触发器向量来实现正确的并发仿真。

## 关键要点

### 1. 旧 V4 调度器的问题

- V4 的调度是 `eval()` + `change_detect()` 循环，直到没有变化。
- 问题：生成时钟（generated clocks）在 `change_detect()` 之后才更新，导致下游逻辑在时钟边沿到达时看到的是旧值。
- 问题：非阻塞赋值（NBA）的更新和应用是「延迟」的，在多线程环境下，如果多个 MTask 同时访问同一个变量的 `_q` 和 `_d`，没有明确的区域边界来同步。

### 2. 新 V5 调度器的核心思想

- 引入 `_q` / `_d` 术语：
  - `_q`：变量的当前值（旧值）
  - `_d`：非阻塞赋值计算出的新值，在 NBA 区域应用
- 调度循环变成：
  ```
  while (has_active_events) {
      // Active region
      evaluate_combinational_logic();
      execute_blocking_assignments();
      
      // NBA region
      apply_non_blocking_assignments();  // 将 _d 写入 _q
      
      // 检查是否有新事件触发
      update_triggers();
  }
  ```
- 组合逻辑收敛循环是 Active 区域的内层循环，不是全局外层循环。

### 3. 5 个关键优化方向

Geza Lore 在讨论中提出了 5 个优化方向，每个方向都直接影响多线程性能：

| # | 优化方向 | 说明 |
|---|---|---|
| 1 | **Evaluate in dependency order** | 按依赖顺序评估，减少不必要的重复计算。对多线程意味着更好的 MTask 划分。 |
| 2 | **SCC iteration** | 强连通分量（SCC）内的节点需要迭代收敛；SCC 之间可以并行。 |
| 3 | **Remove temporary storage** | 消除 eval 过程中的临时变量，减少内存带宽占用。 |
| 4 | **Activity gating** | 只有发生变化的信号才触发下游逻辑评估，避免无效计算。 |
| 5 | **Mutexed event domain specialization** | 对需要互斥访问的事件域进行特化，减少多线程同步开销。 |

### 4. 触发器向量的设计

- 新调度器使用 `VlTriggerVec<T_size>` 来批量表示事件触发状态。
- 每个触发器对应一个位，可以一次性检查多个事件是否触发。
- 多线程环境下，触发器向量的更新必须在 NBA 区域边界同步。

## 对 RTL 仿真器多线程化的启示

这是构建正确多线程 RTL 仿真器的「教科书级」架构讨论。我们的项目应该直接借鉴：
1. **区域分离是正确性的前提**：没有 Active/NBA 区域分离，多线程下对同一变量的读写必然出现 race condition。
2. **SCC 是并行化的天然边界**：强连通分量内的节点必须串行迭代；SCC 之间可以并行。这是图论告诉我们的，不需要猜测。
3. **触发器向量是调度器的核心数据结构**：如何高效表示和检查「哪些事件触发了」是调度器性能的关键。位向量（bitvector）是正确的设计选择。

## 原文摘录

> "The current scheduler is a single loop that evaluates all logic and then checks for changes. This is fundamentally broken for generated clocks and NBA semantics."
> — Geza Lore

> "The new scheduler separates Active and NBA regions, with combinational convergence as an inner loop within the Active region. This is the only way to support generated clocks correctly in a multithreaded context."
> — Geza Lore

> "For multithreading, the key insight is that SCCs must be evaluated serially, but different SCCs can run in parallel."
> — Geza Lore

---

# Issue #3072: Set trace activity flags in MTasks（2022）

## 来源

- URL: https://github.com/verilator/verilator/issues/3072
- 作者: Geza Lore
- 日期: 2022-01-10
- 状态: closed（已合并，对应 PR #2336 的延续）

## 摘要

在 MTask 并行执行时，trace activity flags 的设置必须在每个 MTask 内部完成，否则并行 trace 会遗漏或错误标记活动信号。这是对 PR #2336 的进一步细化。

## 关键要点

- 在单线程模式下，trace activity flags 可以在 eval 循环结束后统一设置。
- 在多线程模式下，如果 activity flags 在线程同步后统一设置，那么某些 MTask 内部触发的信号变化会被遗漏（因为 MTask 之间没有共享 activity flags 的写权限）。
- 解决方案：每个 MTask 在执行时，如果某个变量发生变化，立即设置对应的 activity flag。activity flags 的数组必须是每个线程可写的（或通过原子操作更新）。
- 这个改动与 #2336 密切相关，是对 trace + multithread 兼容性的补充修复。

## 对 RTL 仿真器多线程化的启示

Trace 功能在多线程环境下不是「可选的」，而是「必须正确实现的」。如果我们的 RTL 优化器支持波形输出，必须在 MTask 划分时考虑：
- 哪些变量被 trace 监控？
- 这些变量的写入分布在哪些 MTask 中？
- 如何确保所有 MTask 的 activity 都能被正确汇总到 trace 系统？

一个可能的优化是：将 trace activity flags 的更新延迟到 MTask 执行结束后的 barrier 同步点，而不是在每个 MTask 内部实时更新。这样可以减少 cache coherence 开销，但需要确保 barrier 同步不会遗漏 activity。

## 原文摘录

> "When running with --threads, the trace activity flags need to be set within each MTask, otherwise changes made by one MTask may not be visible to the trace system."

---

# Issue #2948: V3Partition error message improvement（2021）

## 来源

- URL: https://github.com/verilator/verilator/issues/2948
- 作者: 社区用户
- 日期: 2021-05-18
- 状态: closed（已修复）

## 摘要

V3Partition 在构建 MTask 图时，如果某个节点的 cost 计算出现错误（如 infinity 或 NaN），之前的错误信息无法定位到具体是哪个 Verilog 模块/节点出了问题。改进后，错误信息包含了 AstNode 的 source location。

## 关键要点

- MTask 的 cost model 中如果出现了无效值（如无穷大或 NaN），会导致整个 PartContraction 算法崩溃或产生不合理的划分。
- 改进后的错误信息：
  ```
  %Error: V3Partition.cpp:1234: MTask cost is infinity at node: MODULE 'foo' (foo.v:56)
  ```
- 这属于「可调试性」的改进，不是算法改进，但对大型设计的调试极其重要。

## 对 RTL 仿真器多线程化的启示

任何 cost model 都可能遇到异常值（如用户写了极其复杂的组合逻辑导致 cost 溢出）。我们的 RTL 优化器应该在 cost 计算中加入 sanitizer：
- 如果 cost 为 infinity 或 NaN，立即报告并定位到 RTL 源文件位置。
- 提供 `--partition-debug` 开关，输出每个 MTask 的 cost 明细。

---

# Issue #2929: MTask assignment with --trace and --threads（2021）

## 来源

- URL: https://github.com/verilator/verilator/issues/2929
- 作者: 社区用户
- 日期: 2021-05-03
- 状态: closed（与 #2913 相关，已回答）

## 摘要

用户在使用 `--trace` 和 `--threads` 时发现某些信号的 trace 输出不正确。根本原因是 MTask 的 assignment 节点没有被正确分配到 trace activity 的感知范围内。

## 关键要点

- 在 MTask 划分时，如果 assignment 节点（如 `assign x = a & b;`）被分到与变量 `x` 不同的 MTask 中，trace 系统可能无法正确捕获 `x` 的变化。
- 这是因为旧版 V3Partition 没有将「trace activity 的依赖」纳入 cost model 的考虑。
- 修复：在构建 MTask 图时，将 trace 的 write-after-write 依赖也作为边加入图中。

## 对 RTL 仿真器多线程化的启示

Trace 不是「事后附加」的功能，而是划分算法的一部分。如果我们的 RTL 优化器要支持 trace，必须在 MTask 划分时：
1. 识别所有被 trace 的变量。
2. 确保这些变量的所有写入操作都在同一个 MTask 中（或至少在同一个「trace 同步域」中）。
3. 在 MTask 边界处插入 trace activity 的同步点。

## 相关链接

- [Issue #2913](https://github.com/verilator/verilator/issues/2913) — 多线程小设计减速
- [Issue #3278](https://github.com/verilator/verilator/issues/3278) — V5 调度器重设计
- [Issue #3072](https://github.com/verilator/verilator/issues/3072) — MTask 内 trace activity flags
- [Issue #2948](https://github.com/verilator/verilator/issues/2948) — V3Partition 错误信息改进
- [Issue #2929](https://github.com/verilator/verilator/issues/2929) — MTask assignment 与 trace
- [PR #2336](https://github.com/verilator/verilator/pull/2336) — Internalize trace activity flags
- [PR #3384](https://github.com/verilator/verilator/pull/3384) — IEEE 1800-2017 compliant scheduler

---
title: "V3Order 调度顺序与并行分区"
author: "Verilator Team"
date: "2026-07-05"
tags: ["verilator", "multithreading", "scheduling", "graph-partitioning", "critical-path"]
keywords: ["V3Order", "OrderGraph", "LogicMTask", "MTaskEdge", "Contraction", "FixDataHazards"]
---

# V3Order 调度顺序与并行分区

## 概述

`V3Order` 是 Verilator 编译流水线中负责**计算 RTL 逻辑块近最优执行顺序**的核心模块。它不仅处理串行调度，更是在 `--threads` 多线程模式下，通过**静态图分区**将细粒度 RTL 依赖图粗化为可并行执行的 `MTask`（Multithreaded Task）图，直接决定了仿真运行时的并行度上限。

## 核心架构

### 1. 二部依赖图（OrderGraph）

V3Order 首先构建一个**严格的二部图**：

- **OrderLogicVertex**（逻辑块）：表示 `always`、`assign`、`initial` 等可执行逻辑。
- **OrderVarVertex**（变量约束）：表示信号的生命周期约束，细分为四种：
  - `OrderVarStdVertex`：标准数据依赖（组合逻辑、延迟赋值更新）。
  - `OrderVarPreVertex`：优化 `_d = _q` 的 `AlwaysPre`，使其成为 `_q` 的**最后一次读**。
  - `OrderVarPordVertex`：确保 `_d = _q` 是 `_d` 的**第一次写**。
  - `OrderVarPostVertex`：确保所有顺序逻辑读某信号发生在组合/延迟写之前。

边只存在于逻辑顶点与变量顶点之间，利用类型系统（`addHardEdge`/`addSoftEdge`）强制保证这一性质。硬边（non-cutable）必须满足，软边（cutable）用于优化（如打破循环、消除临时存储）。

### 2. 图排序与 Domain 分配

构建完成后：
1. **打破循环**：`graph.acyclic()` 切断软约束形成的环（实际逻辑环已在 `V3SchedAcyclic` 中通过 Hybrid sensitivity 消除）。
2. **赋予 Rank**：`graph.order()` 按拓扑排序赋予 rank，确定执行顺序。
3. **Domain 处理**：`processDomains()` 为组合逻辑推断其触发域（clock domain），确保时钟域内逻辑正确分组。

### 3. MoveGraph 构建

`OrderMoveGraph` 将 OrderGraph 进一步转换为更适合代码生成的中间表示，按 (domain, scope) 分组组织逻辑顶点，为后续串行/并行发射做准备。

## 并行分区：V3OrderParallel.cpp

当 `parallel=true` 时，`V3Order::order()` 调用 `createParallel()`，这是整个多线程编译路径的核心。

### 1. 初始 MTask 图构建

`Partitioner` 将 `OrderMoveGraph` 的每个顶点映射为初始的 `LogicMTask`：
- **Bypass 优化**：对于低连通度的变量顶点（`fanIn * fanOut <= fanIn + fanOut`），跳过创建独立的 `LogicMTask`，直接通过传递边连接上下游逻辑顶点。这能将工作集减少一个数量级。
- **Entry/Exit 顶点**：添加人工的单一入口和出口节点，确保即使原图不连通，也能进行 sibling merge。

### 2. 数据冒险修复（FixDataHazards）

在并行执行时，某些在串行模式下无问题的依赖缺失会导致数据竞争。`FixDataHazards` 识别并修复三类问题：
- **部分赋值 RMW**：`sig[15:8] = ...` 和 `sig[7:0] = ...` 在 C++ 中生成读-改-写序列，必须串行化。
- **循环逻辑切边**：V3Order 为打破循环切断的软边，在并行模式下必须重新建立顺序。
- **DPI / SystemC 调用**：非线程安全的 DPI 导入和 SystemC 变量写操作需要全局串行化。

修复策略是**保守合并**：将同一变量在同一 rank 上的所有写者（及读者）合并为一个 MTask，并在不同 rank 之间添加串行依赖边。

### 3. 临界路径驱动的图粗化（Contraction）

这是分区器的核心算法，目标是将数千个细粒度 MTask 合并为数十个粗粒度 MTask，同时控制**临界路径（Critical Path, CP）**长度。

#### 评分机制

每个合并候选（边合并或 sibling 合并）有一个 score，定义为合并后**局部 CP 长度**（即经过合并节点的最长路径）。Score 越低越好。

```
score = max(merged_fwd_cp) + max(merged_rev_cp) + stepCost(merged_cost)
```

- `merged_fwd_cp` / `merged_rev_cp`：合并后前向/反向的临界路径。
- `stepCost`：合并后的阶梯代价，对微小代价波动进行量化，避免频繁传播。

#### 边合并 vs Sibling 合并

- **Edge merge**：合并存在直接依赖边的两个 MTask。这是粗化的基本操作。
- **Sibling merge**：合并共享同一个上游（或下游）邻居的两个 MTask。这对星型图（高扇入/扇出）至关重要，防止中心节点无限膨胀而边缘节点无法合并。

Sibling 合并的 score 会额外加 1，使得在 score 相同时，sibling merge 被优先选择（避免星型图局部最优）。

#### 增量临界路径传播（PropagateCp）

每次合并后，合并节点的代价和 CP 会变化，需要向上下游传播。`PropagateCp` 使用 **PairingHeap** 实现增量传播：
1. 将被影响的邻居节点加入 pending heap，标记其 CP 需要增长多少。
2. 从 heap 中按**增长量从大到小**处理节点，每次更新后向更远节点传播。
3. **关键性质**：在当前 pass 中，每个节点的 CP 只被更新一次，避免递归的 `O(N^2)` 行为，使大规模图的粗化接近 `O(N log N)`。

#### 终止条件

- **CP 预算**：`cpLimit = totalGraphCost * 3 / (5 * threads)`。如果最优合并候选的 score 超过此 limit，则停止。
- **MTask 数量上限**：`maxMTasks = threads * 50`。如果 MTask 数仍超过上限，则放宽 limit 继续合并（发出 `UNOPTTHREADS` 警告）。
- **Entry/Exit 保护**：不允许合并到 entry/exit 节点，避免全局串行化。

### 4. 生成 AstExecGraph

粗化完成后，每个 `LogicMTask` 被转换为 `ExecMTask`：
- `V3OrderCFuncEmitter` 将 MTask 内的所有 `OrderLogicVertex` 按 (domain, scope) 分组发射为 `AstCFunc`。
- 创建 `AstExecGraph` 节点，包含一个 `V3Graph`（`depGraphp`），其顶点是 `ExecMTask`，边是运行时依赖。
- 最终输出是 `AstCCall` 列表，按拓扑序调用每个 `ExecMTask` 的函数。

`AstExecGraph` 是连接**编译时分区**与**运行时线程池调度**的桥梁。

## 关键设计决策

### 1. 编译时静态分区

Verilator 不在运行时做动态负载均衡，而是在编译时通过静态图粗化预先确定任务边界。这牺牲了运行时适应性，但换来了：
- **零运行时调度开销**：线程池只需按拓扑序启动就绪的 MTask。
- **极佳的局部性**：同一 MTask 内的逻辑在代码中连续存放，缓存友好。
- **确定性**：相同的输入总是生成相同的 MTask 图，便于调试和回归测试。

### 2. 阶梯代价（Stepped Cost）

`LogicMTask::stepCost()` 将实际代价向上取整到最近的 5% 对数边界。这是一种**容忍误差的增量优化**：当小节点合并到大节点时，如果代价增长未跨越下一个阶梯，就不需要向大量子节点重新传播 CP。这对处理 Verilog 中常见的“巨大 always 块”至关重要。

### 3. 保守的数据竞争修复

`FixDataHazards` 宁可多合并一些 MTask（导致轻微串行化），也绝不留下运行时竞争。因为：
- 运行时竞争是 Heisenbug，极难调试。
- 静态分析很难精确判断某个部分赋值是否一定生成 RMW。
- 合并同 rank 的节点只会增加局部串行度，不会破坏全局正确性。

## 对 RTL 仿真器多线程化的启示

| 设计点 | Verilator 的做法 | 自研仿真器的建议 |
|---|---|---|
| **依赖建模** | 二部图（Logic ↔ Variable） | 推荐采用二部图，变量生命周期约束天然成为节点 |
| **分区时机** | 编译时静态粗化 | AOT/编译型仿真器首选静态分区；JIT/解释型考虑动态或混合 |
| **分区目标** | 以临界路径为首要约束，负载均衡为辅 | 不要单纯追求负载均衡，CP 过长会直接抵消多线程收益 |
| **增量更新** | 阶梯代价 + PairingHeap 增量传播 | 引入量化容忍机制，避免每次合并后全图重算 |
| **竞争处理** | 保守合并同 rank 的读写者 | 静态分析阶段宁可多串化，不能留运行时竞争 |
| **高扇入扇出** | Sibling merge 解决星型图局部最优 | 粗化算法必须包含间接邻居合并策略 |
| **工作集缩减** | Bypass 低度变量顶点 | 多层图转换中引入中间节点消除，降低后续算法输入规模 |

## 相关页面

- [V3ExecGraph 执行图](wiki-verilator-V3ExecGraph执行图.md) — 运行时 MTask 的调度与线程池交互
- [V3Sched 调度器](wiki-V3Sched调度器.md) — 敏感域推断与触发条件管理
- [Verilator 线程池](wiki-verilator-v3threadpool.md) — 运行时多线程执行机制
- [V3Order 调度顺序源码详解](source-verilator-V3Order调度顺序.md) — 源码级逐函数分析

---
title: "Verilator DFG 数据流图编译优化系统"
description: "Verilator V3Dfg 模块的深度分析：数据流图表示、组件级优化、编译阶段并行化潜力"
author: "Wiki MT RTL Optimizer"
date: "2026-07-05"
tags: ["verilator", "dfg", "compiler-optimization", "multithreading", "parallel-compilation"]
keywords: ["DfgGraph", "DfgVertex", "DfgEdge", "DfgUserMap", "CSE", "splitIntoComponents", "component-level-parallelism"]
---

# Verilator DFG 数据流图编译优化系统

> 本页整合自源码分析 `source-verilator-v3dfg.md`。DFG 是 Verilator 编译流水线中的组合逻辑优化中间层，将 AST 片段转换为可高效操作的数据流图，执行 CSE、peephole、变量内联等优化后再转回 AST。

---

## 1. 架构概述

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────┐     ┌─────────────┐
│  AST 子树   │ ──→ │  DfgGraph   │ ──→ │  DFG 优化流水线  │ ──→ │  优化后 AST  │
│ (AstAlways) │     │ (V3Dfg.h)   │     │ (V3DfgOptimizer)│     │ (AstAssignW)│
└─────────────┘     └─────────────┘     └─────────────────┘     └─────────────┘
       ↑                                                        ↓
       └──────── V3DfgAstToDfg.cpp                    V3DfgDfgToAst.cpp ───┘
```

**DFG 在整个 Verilator 中的定位**：
- DFG 操作在 **编译时** 完成，不直接参与仿真调度。
- 输出结果（优化后的 AST）影响最终生成的 C++ 仿真代码质量。
- 与 **V3Partition**（仿真时多线程分区）有相似的分图逻辑，但作用于不同抽象层。

---

## 2. 核心数据结构

### 2.1 `DfgVertex` — 顶点

- **输入边**：`std::vector<std::unique_ptr<DfgEdge>> m_inputps`，支持 `O(1)` 索引。
- **输出边**：`V3List<DfgEdge> m_sinks`，侵入式链表，迭代时可安全解链当前元素。
- **用户数据**：`mutable void* m_userStorage` + `mutable uint32_t m_userGeneration`，支撑 `DfgUserMap` 零开销映射。

### 2.2 `DfgGraph` — 图容器（分类型存储）

```cpp
DfgVertex::List<DfgVertexVar> m_varVertices;     // ~40-50% 的顶点
DfgVertex::List<DfgVertexAst> m_astVertices;     // AST 引用
DfgVertex::List<DfgConst> m_constVertices;     // 常量
DfgVertex::List<DfgVertex> m_opVertices;         // 原语操作
```

**设计意图**：按类型分桶，避免遍历时做类型检查。变量顶点通常占大多数，且常被特殊处理（如 CSE 中视为哈希边界）。

### 2.3 `DfgUserMap` — 零开销属性映射

| 特性 | 实现 | 性能 |
|------|------|------|
| 小值存储 | 直接塞入 `m_userStorage`（一个 `void*`） | O(1)，无内存分配 |
| 大值存储 | `m_userStorage` 存指针，数据放在 `std::deque` | O(1) 访问，deque 扩容摊还 O(1) |
| 世代刷新 | `m_userGeneration` 比较，避免清空全图 | 初始化成本从 O(\|V\|) 降到 O(1) |
| 并发限制 | 同图同时只能有一个 `DfgUserMap` 在使用 | 单线程最优，多线程需扩展 |

### 2.4 `DfgWorklist` — 预取工作列表

使用 **sentinel 技巧**：用 `this` 的地址作为链表尾哨兵，使所有在列表中的顶点 `nextp != nullptr`。这样：
- `contains(vtx)` 仅需判断 `m_nextp[vtx] != nullptr`（O(1)）。
- `foreach` 循环中无需条件判断即可执行 `VL_PREFETCH_RW(m_headp)`。

---

## 3. 优化流水线（`V3DfgOptimizer.cpp`）

```
astToDfg
  ├─→ removeUnobservable        // 移除不可观测变量
  ├─→ synthesize                // 将 DfgLogic 拆分为原语操作
  ├─→ extractCyclicComponents   // 提取环状子图 → cyclicComps
  ├─→ breakCycles (optional)   // 尝试打破循环 → 部分转 DAG
  ├─→ removeSelects             // 消除冗余选择
  ├─→ splitIntoComponents      // 分割为弱连通分量 → acyclicComps
  │     ├─→ inlineVars         // 对每个组件：变量内联
  │     ├─→ cse                // 对每个组件：公共子表达式消除（第一轮）
  │     ├─→ binToOneHot        // 对每个组件：二进制转 one-hot
  │     ├─→ peephole           // 对每个组件：窥孔优化
  │     ├─→ pushDownSels       // 对每个组件：选择下推
  │     └─→ cse                // 对每个组件：公共子表达式消除（第二轮）
  ├─→ mergeGraphs               // 合并所有组件回主图
  └─→ regularize                // 规范化，统一变量引用
```

**关键发现**：`acyclicComps` 和 `cyclicComps` 的每个组件都是**互相独立的子图**（无跨组件边），当前串行优化，但天然可并行。

---

## 4. 公共子表达式消除（CSE）

### 算法：哈希 + 等价比较

1. **预哈希边界顶点**：变量、AST 引用、常量、CReset 各自赋予唯一哈希值。
2. **递归哈希操作顶点**：`vertexHash(vtx) = selfHash(vtx) + type + size + Σ vertexHash(src)`。结果被 `DfgUserMap<V3Hash>` 缓存。
3. **哈希桶分组**：将哈希值相同的顶点放入同一向量。
4. **精确等价比较**：对同桶顶点两两调用 `vertexEquivalent`，使用记忆化避免重复递归。等价则 `replaceWith` 消除重复。

### 复杂度

| 阶段 | 时间 | 空间 |
|------|------|------|
| 预哈希 | O(\|V\|) | O(\|V\|) for hash cache |
| 递归哈希 | O(\|V\|)（memoized） | O(\|V\|) |
| 桶内比较 | O(k²) per bucket, k = bucket size | O(\|V\|) for equiv cache |
| 最坏情况 | O(\|V\|²)（全碰撞） | O(\|V\|) |

---

## 5. 多线程相关分析

### 5.1 当前状态：编译时单线程

- 所有 6 个文件标记为 `// VL_MT_DISABLED_CODE_UNIT`。
- 大量方法标记 `VL_MT_DISABLED`。
- 文件中**无任何 `std::mutex`、`std::atomic`、`std::barrier` 或线程池**。

> 这意味着 DFG 优化的全部计算在**编译时串行**执行。对于百万级顶点的大型设计，这可能成为编译瓶颈。

### 5.2 组件级天然并行性

`splitIntoComponents` 和 `extractCyclicComponents` 将大图拆分为**无互连边的独立子图**。每个子图可独立执行：
- `inlineVars`
- `cse`
- `peephole`
- `pushDownSels`
- `removeSelects`

**并行化方案（最低侵入）**：
```cpp
// 将串行 for 改为并行 for（TBB / OpenMP / std::async）
#pragma omp parallel for
for (size_t i = 0; i < acyclicComps.size(); ++i) {
    V3DfgPasses::inlineVars(*acyclicComps[i]);
    V3DfgPasses::cse(*acyclicComps[i], per_thread_ctx);
    // ...
}
```

**实施注意事项**：
- `m_ctx` 统计字段需要 `std::atomic` 或 per-thread 累加器。
- `DfgDataType` 全局 intern 池是只读查表，无需同步。
- 调试 dump 输出需串行化或独立文件。

### 5.3 `DfgUserMap` 的并行化扩展

| 方案 | 描述 | 适用场景 |
|------|------|----------|
| **子图隔离** | 每个 worker 操作独立子图，各自 UserMap | 推荐：组件级并行已天然隔离 |
| **TLS 存储槽** | 扩展 `m_userStorage` 为 per-thread 数组 | 同一图内多 worker 需要不同属性 |
| **并发 hashmap** | 放弃零开销，用 `tbb::concurrent_hash_map` | 共享图且需要灵活属性映射 |

### 5.4 对仿真器多线程的间接启示

1. **图分割算法复用**：`splitIntoComponents` 的弱连通分量算法与 `V3Partition` 的仿真分区有相似逻辑。编译时分析可为运行时分区提供预计算信息。
2. **CSE 减少冗余计算**：消除的重复子表达式直接减少了仿真代码的冗余，降低仿真线程的计算负载。
3. **`isCheaperThanLoad()` 启发式**：在 NUMA 架构下，跨 socket 的内存加载代价极高。DFG 中判断"重新计算是否比加载更便宜"的启发式可直接迁移到多线程仿真内核中——本地重新计算可能优于跨 NUMA 读取。

---

## 6. 对 RTL 仿真器多线程化的核心启示

### 启示一：编译阶段并行化是"低垂的果实"

Verilator 的 DFG 优化当前是单线程的，但架构上**已经准备好了并行化**：
- 组件天然独立。
- 优化之间无跨组件依赖。
- 只需将 `for` 循环改为并行遍历，并处理统计上下文即可。

对于使用 Verilator 编译大型设计的用户，这可以直接缩短编译时间，不影响仿真性能。

### 启示二：零开销属性映射是高效图算法的基石

`DfgUserMap` 的 `m_userStorage + m_userGeneration` 模式展示了如何在不分配外部 hashmap 的情况下实现 O(1) 属性映射。这对于需要频繁访问顶点属性的图算法（如 CSE、可达性分析、拓扑排序）至关重要。在多线程场景下，可以通过**子图隔离**或**TLS 存储槽**保持这种零开销优势。

### 启示三：组件化设计是并行的前提

DFG 的优化流水线通过 `splitIntoComponents` 和 `extractCyclicComponents` 将问题分解为独立子问题。这是并行化的**必要条件**：
- 如果优化算法必须在全图上操作（如全局 CSE），并行化难度高。
- 如果算法天然可分解为组件级操作，并行化几乎是免费的。

对于 RTL 仿真器设计，这意味着：
- 在 IR 层面引入组件边界（如 `DfgGraph` 的独立子图）。
- 让优化算法尊重组件边界，避免跨组件边。
- 在运行时，每个组件可独立编译、独立优化、甚至独立调度。

### 启示四：预取与数据结构协同优化

`DfgWorklist` 的 `VL_PREFETCH_RW` 和 sentinel 技巧展示了**数据结构设计与硬件特性协同**的工程思想：
- 无条件预取消除了分支预测失败的代价。
- sentinel 消除了空指针检查和条件分支。
- 在多线程场景下，预取仍需注意 false sharing——多个线程不应同时预取同一缓存行的数据。

### 启示五：DAG 与 Cyclic 分离是优化策略的分水岭

DFG 明确将图分为 DAG 和 Cyclic 两部分分别处理：
- DAG 组件：大多数优化（CSE、peephole、pushDownSels）假设 DAG。
- Cyclic 组件：需要特殊处理（`breakCycles`）。

这种分离对 RTL 仿真器多线程调度同样重要：
- DAG 的组合逻辑可以**静态调度**（编译时确定执行顺序）。
- Cyclic 的逻辑（如组合循环）需要**动态调度**或特殊处理（如迭代收敛）。
- 多线程调度器可以针对不同类型使用不同策略。

---

## 相关页面

- [source-verilator-v3dfg](source-verilator-v3dfg.md) — 完整源码分析（含代码片段、行号、函数分析）
- [wiki-verilator-deep-dive](wiki-verilator-deep-dive.md) — Verilator 多线程仿真深度分析
- [wiki-verilator-partition-evolution](wiki-verilator-partition-evolution.md) — Verilator 分区机制演进
- [wiki-compiler-and-simd](wiki-compiler-and-simd.md) — 编译器优化与 SIMD

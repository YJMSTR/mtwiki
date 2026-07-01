---
title: "Verilator V3VariableOrder: 变量排序优化与多线程感知"
source_url: "https://github.com/verilator/verilator/blob/master/src/V3VariableOrder.cpp / https://github.com/verilator/verilator/blob/master/src/V3VariableOrder.h"
source_type: "github-pr"  # 核心改进来自 PR #5406
author: "Bartłomiej Chmiel, Antmicro Ltd. (PR #5406); Wilson Snyder (original implementation)"
date: "2024 (PR #5406 merged)"
tags: ["rtl-sim", "multithreading", "verilator", "variable-ordering", "cache-optimization", "MTask", "parallelism"]
keywords: ["V3VariableOrder", "variable ordering", "MTask affinity", "cache line alignment", "macro-task", "parallel variable ordering", "memory layout"]
capture_date: "2026-07-01"
---

## 摘要

V3VariableOrder 是 Verilator 编译器中负责**变量排序（Variable Ordering）** 的关键模块。它的作用是在生成 C++ 代码之前，为每个模块中的变量确定输出顺序，从而优化内存布局、缓存利用率和多线程访问模式。

该模块在 2024 年通过 PR #5406（作者 Bartłomiej Chmiel, Antmicro）进行了重大改进，核心变化是**将变量排序过程并行化**，以改善大规模设计下的编译时间性能。从 `Changes` 文件中可以看到：

> **Improve performance of V3VariableOrder with parallelism (#5406).** [Bartłomiej Chmiel, Antmicro Ltd.]

V3VariableOrder 的核心逻辑分为两个模式：
1. **非多线程模式 (`simpleSortVars`)**：按变量属性（static/non-static、anonymous 支持度、stratum/对齐要求）进行稳定排序，优化内存布局。
2. **多线程模式 (`mtaskSortVars`)**：在简单排序的基础上，**按 MTask 亲和性（MTask Affinity）分组**，将属于同一 macro-task 的变量排列在一起，并对齐到缓存行边界（`mtaskCacheLineAlign`），以减少多线程执行时的 false sharing 和 cache miss。

## 对"稀疏计算RTL仿真器多线程化"的启示

1. **MTask 亲和性分组是减少缓存竞争的关键**：`mtaskSortVars` 将具有相同 MTask 亲和性的变量分到同一组，并按缓存行对齐。这直接减少了多线程执行时不同核心访问重叠缓存行（false sharing）的概率。对于我们的稀疏计算 RTL 仿真器，这意味着：
   - 在生成仿真代码时，应该将**同一线程/同一任务处理的信号**在内存中排列在一起
   - 需要考虑变量之间的**活跃模式亲和性**，而非单纯的 MTask 静态亲和性
   - 对于稀疏计算，可以进一步优化为按**活跃周期模式**分组——同时活跃的变量放在一起

2. **并行编译器本身是性能瓶颈**：PR #5406 的动机说明，即使对于编译器本身，变量排序这种看似简单的操作在大规模设计下也成为瓶颈。这提示我们——如果我们的仿真器支持编译时优化，**编译器阶段本身的并行化** 也需要被考虑。

3. **缓存行对齐的权衡**：`mtaskSortVars` 在每组 MTask 亲和变量的开头插入缓存行对齐（`mtaskCacheLineAlign(true)`）。这用内存填充换取了多线程性能，对于稀疏计算场景：
   - 如果变量组很小，填充可能导致显著的内存浪费
   - 需要**动态评估**对齐的收益 vs 内存开销，而非无条件对齐

4. **stratum 排序的启发**：`orderModuleVars` 中的 stratum 分配逻辑（按信号宽度、类型、数组等确定对齐要求）体现了**内存布局对性能的影响**。在稀疏计算中，信号宽度差异可能更大（32-bit 计数器 vs 1-bit 控制信号），合理的内存布局可以减少缓存占用，提高 cache hit rate。

5. **从"按 MTask 分组"到"按活跃模式分组"**：Verilator 的 MTask 亲和性是基于静态 macro-task 分区的。在稀疏计算中，一个变量可能在某些周期属于任务 A，在另一些周期属于任务 B（如果活跃信号集合变化）。这提示我们可能需要**运行时动态重排**或**为不同活跃模式预编译多个变量布局**。

## 代码结构分析

### 文件位置
- `src/V3VariableOrder.h` — 公共接口声明
- `src/V3VariableOrder.cpp` — 实现
- `src/Verilator.cpp` — 调用点：`V3VariableOrder::orderAll(v3Global.rootp())`

### 核心类

#### `V3VariableOrder` (公共接口)
```cpp
class V3VariableOrder final {
public:
    static void orderAll(AstNetlist*);
};
```

#### `GatherMTaskAffinity` (MTask 亲和性收集)
- 遍历每个 ExecMTask 的函数体
- 收集每个变量被哪些 MTask 引用
- 结果存储在 `MTaskAffinityMap` 中（`unordered_map<const AstVar*, vector<bool>>`）
- 使用 `user1SetOnce()` 防止重复遍历

#### `VariableOrder` (排序引擎)
- `simpleSortVars`：非多线程排序
  - 非 static 变量优先于 static 变量
  - anonymous 支持变量优先
  - 按 stratum（对齐要求）排序
- `mtaskSortVars`：多线程感知排序
  - 将变量按 MTask 亲和性向量分组
  - 对每个组内调用 `simpleSortVars`
  - 在每组开头对齐缓存行
  - 最后处理无 MTask 亲和性的变量

#### `orderAll` 流程
1. 收集 MTask 亲和性（如果启用 `--threads`）
2. 并行对每个模块进行变量排序（`V3ThreadScope`）
3. 将排序后的变量重新链接到模块 AST

### Stratum 分配规则（来自 `orderModuleVars`）

```cpp
const uint8_t stratum = (v3Global.opt.hierChild() && varp->isPrimaryIO())   ? 0
                        : (varp->isPrimaryClock() && varp->widthMin() == 1) ? 1
                        : VN_IS(varp->dtypeSkipRefp(), UnpackArrayDType)    ? 9
                        : (varp->basicp() && varp->basicp()->isOpaque())    ? 8
                        : (varp->isScBv() || varp->isScBigUint())           ? 7
                        : (sigbytes == 8)                                   ? 6
                        : (sigbytes == 4)                                   ? 5
                        : (sigbytes == 2)                                   ? 3
                        : (sigbytes == 1)                                   ? 2
                                                                            : 10;
```

优先级：Primary IO (0) > Primary Clock (1) > 1-byte (2) > 2-byte (3) > 4-byte (5) > 8-byte (6) > SC types (7) > opaque (8) > unpack array (9) > default (10)

## 关键代码摘录

### MTask 亲和性排序

```cpp
void mtaskSortVars(std::vector<AstVar*>& varps) {
    // Map from "MTask affinity" -> "variable list"
    std::map<MTaskIdVec, std::vector<AstVar*>> m2v;
    const MTaskIdVec emptyVec(ExecMTask::numUsedIds(), false);
    for (AstVar* const varp : varps) {
        const auto it = m_mTaskAffinity.find(varp);
        const MTaskIdVec& key = it == m_mTaskAffinity.end() ? emptyVec : it->second;
        m2v[key].push_back(varp);
    }

    varps.clear();

    // Sort non-empty MTask affinity groups in the map's deterministic key order.
    size_t affinityGroups = 0;
    for (auto& pair : m2v) {
        if (emptyAffinity(pair.first)) continue;
        sortAndAppend(pair.second, true);  // alignFirst = true
        ++affinityGroups;
    }
    // Finally add the variables with no known MTask affinity
    sortAndAppend(m2v[emptyVec], false);
}
```

### 并行模块排序

```cpp
std::unordered_map<AstNodeModule*, std::vector<AstVar*>> sortedVars;
{
    V3ThreadScope threadScope;
    for (AstNodeModule* modp = v3Global.rootp()->modulesp(); modp;
         modp = VN_AS(modp->nextp(), NodeModule)) {
        std::vector<AstVar*>& varps = sortedVars[modp];
        threadScope.enqueue([modp, &mTaskAffinity, &varps]() {
            VariableOrder::processModule(modp, mTaskAffinity, varps);
        });
    }
}
```

## 附加信息

- **相关 PR**: #5406 (Improve performance of V3VariableOrder with parallelism)
- **相关 Commit**: 涉及 V3ThreadPool 的改进 (#5161, 也来自 Antmicro)
- **统计指标**: `VariableOrder, MTask affinity groups`, `VariableOrder, MTask aligned group starts`, `VariableOrder, no-affinity variables`
- **调用位置**: `src/Verilator.cpp` 中在 Verilation 的后期阶段调用，用于在生成 C++ 代码前优化变量布局

## 参考链接

- https://github.com/verilator/verilator/blob/master/src/V3VariableOrder.cpp
- https://github.com/verilator/verilator/blob/master/src/V3VariableOrder.h
- https://github.com/verilator/verilator/pull/5406 (PR 详情)
- https://github.com/verilator/verilator/pull/5161 (V3ThreadPool 改进)

---
title: "V3Partition / V3Order 代码演进历史（2020-2025）"
description: "基于 verilator/verilator 仓库的 commit 历史和 PR 记录，梳理 V3Partition 与 V3Order 从单体模块到多文件、职责分离的完整演进时间线，包含关键 commit 的代码变化和架构决策。"
source_url: "https://github.com/verilator/verilator"
source_type: "github-commit"
author: "Geza Lore, Wilson Snyder, Mariusz Glebocki, et al."
date: "2020-2025"
tags: ["verilator", "v3partition", "v3order", "code-evolution", "refactoring", "multithreading"]
keywords: ["V3Partition", "V3Order", "V3OrderParallel", "V3ExecGraph", "V3Sched", "PartContraction", "MTask", "commit-history"]
capture_date: "2026-06-26"
---

# V3Partition / V3Order 代码演进历史（2020-2025）

## 来源

- URL: https://github.com/verilator/verilator
- 类型: github-commit + github-pr
- 作者: Geza Lore, Wilson Snyder, Mariusz Glebocki, Krzysztof Bieganski 等
- 日期: 2020-2025

## 摘要

本文档基于 verilator/verilator 仓库的 `src/V3Partition.cpp` 和 `src/V3Order.cpp` 的 commit 历史，梳理了这两个核心模块从 2020 年到 2025 年的完整演进时间线。V3Partition 从 4000+ 行的单体文件（同时负责 MTask 划分算法和 AstExecGraph 代码生成）逐步被拆分为 V3OrderParallel、V3ExecGraph、V3OrderProcessDomains 等专注单一职责的模块；V3Order 也从直接生成调度代码的「全能选手」演变为只负责依赖排序分析的「专一分析师」，调度代码生成由 V3Sched 接管。这份演进历史为 RTL 多线程优化器的架构设计提供了「演化生物学」级别的参考。

## 关键要点

1. **V3Partition 的演进不是一次性重构，而是 4 年的渐进式拆分**：从 2020 年的单体文件，到 2021 年的 AstExecGraph 解耦，到 2022 年的 PartContraction 优化，到 2024 年的彻底拆分。
2. **V3Order 的演进与调度器语义升级（V4→V5）同步**：V3Order 的职责收窄伴随着 V3Sched 的引入和 IEEE 1800-2017 调度器的实现。
3. **Geza Lore 是主导者**：2020-2025 年间，几乎所有与多线程相关的重大架构变更都由 Geza Lore 发起或主导。
4. **每次拆分都是「纯代码移动，无功能改变」**：这是大规模重构的安全策略——先物理拆分，再逻辑优化，避免同时改动结构和行为。

---

## 演进时间线

### 2020：早期多线程基础（V3Partition 单体时代）

#### 2020-05-14 — PR #2336: Internalize trace activity flags
- **作者**: Wilson Snyder
- **文件**: `src/V3Partition.cpp`（少量改动）
- **内容**: 将 trace activity flags 的维护从 trace 代码移入核心仿真循环，使 MTask 能感知 activity。
- **影响**: 这是 V3Partition 与多线程 trace 兼容的最早基础工作。V3Partition 仍然是单体文件，但开始处理多线程相关的边界 case。

#### 2020 年 V3Partition 的整体状态
- 约 4000+ 行，同时包含：
  - MTask 划分算法（PartContraction、PartPropagate）
  - AstExecGraph 构造和线程分配（`V3Partition::finalize`）
  - Cost model 计算（变量 cost、logic cost、edge cost）
- 文件名：`src/V3Partition.cpp`
- V3Order 此时也是单体文件，直接生成 `eval_settle` / `eval` 循环。

---

### 2021：AstExecGraph 解耦（V3Partition 第一次拆分）

#### 2021-06-17 — PR #3022: Construct AstExecGraph inside V3Partition::finalize
- **作者**: Geza Lore
- **文件**: `src/V3Partition.cpp`, `src/V3EmitC.cpp`
- **内容**: 将线程调度逻辑从 `V3EmitC` 移回 `V3Partition::finalize`，引入 `ThreadSchedule` 类。
- **关键代码变化**:

```cpp
// 2021 年前：V3EmitC 直接操作 ExecMTask
// V3EmitC.cpp（旧代码）
void EmitC::emitMTask(const ExecMTask* mtaskp) {
    // 直接在这里决定 MTask 放在哪个线程
    // 直接生成线程入口代码
}

// 2021 年后：V3Partition::finalize 生成 AstExecGraph
// V3Partition.cpp（新代码）
class ThreadSchedule final {
    std::vector<std::vector<const ExecMTask*>> m_threads;
    std::unordered_map<const ExecMTask*, uint32_t> m_threadId;
public:
    uint32_t threadId(const ExecMTask* mtaskp) const { return m_threadId.at(mtaskp); }
    uint32_t nThreads() const { return m_threads.size(); }
};

void V3Partition::finalize(AstNetlist* nodep) {
    ThreadSchedule schedule = ...;  // 创建线程调度
    AstExecGraph* graphp = new AstExecGraph(...);  // 生成 AST 表示
    // ...
}
```

- **影响**: Emitter 与 Scheduler 的第一次解耦。V3Partition 仍然是单体文件，但职责边界开始清晰化。

---

### 2022：调度器升级 + PartContraction 优化

#### 2022-04-14 — PR #3329: V3Order/V3Sched 重构
- **作者**: Geza Lore
- **文件**: `src/V3Order.cpp`, 新增 `src/V3Sched.cpp`
- **内容**: 将 V3Order 中的调度代码生成剥离到 V3Sched，引入 `AstEval` 节点。
- **关键代码变化**:

```cpp
// 新增 V3Sched.h
class V3Sched final {
public:
    static void schedule(AstNetlist* nodep);
};

// V3Order.cpp 删除的代码（旧）
// void V3Order::order(...)
// {
//     // 分析依赖 + 生成 _eval_settle / _eval 循环
// }

// V3Sched.cpp 新增的代码（新）
void V3Sched::schedule(AstNetlist* nodep) {
    // 1. 从 V3Order 获取排序后的逻辑序列
    // 2. 生成 _eval_settle / _eval / _eval_initial
}
```

- **影响**: V3Order 的职责第一次收窄。这是 V5 调度器的基础。

#### 2022-09-01 — PR #3384: IEEE 1800-2017 Compliant Scheduler
- **作者**: Geza Lore
- **文件**: `src/V3Sched.cpp`, `src/V3Order.cpp`
- **内容**: 实现 IEEE 1800-2017 调度器，Active/NBA 区域分离。
- **关键代码变化**:

```cpp
// V3Sched.cpp 中的 Active/NBA 区域划分
void V3Sched::partition(AstNetlist* nodep) {
    // 将逻辑划分为 'act' 和 'nba' 区域
    // act: 组合逻辑 + 阻塞赋值（内层收敛循环）
    // nba: 非阻塞赋值更新（_d -> _q）
}

// 新增触发器向量类型
// V3TriggerVec.h（新文件）
template <size_t T_size>
class VlTriggerVec final {
    std::array<uint64_t, (T_size + 63) / 64> m_words;
public:
    void set(size_t idx) { m_words[idx / 64] |= (1ULL << (idx % 64)); }
    bool at(size_t idx) const { return (m_words[idx / 64] >> (idx % 64)) & 1; }
};
```

- **影响**: 这是 V3Sched 的里程碑。V3Order 现在只负责排序分析，V3Sched 负责生成符合 IEEE 标准的调度代码。

#### 2022-08-31 — PR #3587: V3Partition PartContraction 工作集优化
- **作者**: Geza Lore
- **文件**: `src/V3Partition.cpp`
- **内容**: 引入 `bypassOk()` 函数，在初始 MTask 图构建时跳过零成本顶点。
- **关键代码变化**:

```cpp
// V3Partition.cpp 新增
bool bypassOk(const V3GraphVertex* vxp) {
    const uint32_t fanIn = vxp->fanIn();
    const uint32_t fanOut = vxp->fanOut();
    return fanIn * fanOut <= fanIn + fanOut;  // 零成本顶点
}

// 在构建初始 MTask 图时
for (auto* vxp : graph.vertices()) {
    if (bypassOk(vxp)) continue;  // 跳过，不加入工作集
    addToScoreboard(vxp);
}
```

- **影响**: 编译时间提升 25%，但仿真性能因 tie-breaking 随机性出现波动。Geza Lore 在 PR 讨论中详细分析了这个问题。

---

### 2023：基础设施清理与微调

#### 2023-05-10 — Commit 4c0edd2: Improve --prof-exec infrastructure
- **作者**: Geza Lore
- **文件**: `src/V3Partition.cpp`, `src/V3Order.cpp` 等
- **内容**: 改进多线程性能分析基础设施，替换 eval/evl_loop 事件为通用的 section_push/section_pop 事件。
- **关键变化**: 由于 V3Sched 和 V3Partition 的代码结构变化，`--prof-exec` 的报告格式需要适配。这个 commit 将性能分析事件从硬编码的 `eval`/`evl_loop` 改为通用的 section 机制，可以灵活地插入到任意生成的代码段中。

#### 2023-10-21 — Commit 10d3323: Do not merge entry/exit MTasks during coarsening
- **作者**: Geza Lore
- **文件**: `src/V3Partition.cpp`
- **内容**: 在 PartContraction 粗化阶段，禁止合并 entry/exit MTask。
- **关键变化**:

```cpp
// 在 PartContraction 的合并逻辑中新增
bool canMerge(const ExecMTask* a, const ExecMTask* b) {
    if (a->isEntry() || a->isExit()) return false;  // 新增
    if (b->isEntry() || b->isExit()) return false;  // 新增
    // ... 其他合并条件
}
```

- **影响**: Entry/exit MTask 是线程调度的边界点，合并它们会破坏线程入口/出口的结构，影响后续代码生成。这是一个细微但重要的约束。

#### 2023-09-25 — PR #4228: Rework multithreading handling to separate by code units
- **作者**: Mariusz Glebocki (Antmicro)
- **文件**: 多个文件
- **内容**: 将多线程相关代码按「使用多线程」和「永不使用多线程」的代码单元分离。
- **影响**: 编译器基础设施清理，对 V3Partition/V3Order 没有直接代码改动，但减少了多线程宏的污染范围。

#### 2023-08-31 — PR #4397: Use runtime type info instead of dynamic_cast
- **作者**: Krzysztof Bieganski (Antmicro)
- **文件**: `src/V3Graph.h`, `src/V3Partition.cpp` 等
- **内容**: 用运行时类型信息替代 `dynamic_cast`，加速 graph 类型检查。
- **影响**: V3Partition 和 V3Order 大量使用 V3Graph，类型检查性能提升对大型设计有明显影响。

---

### 2024：大规模重构之年（V3Partition 和 V3Order 彻底拆分）

#### 2024-02-29 — PR #4933: Emit a separate CFunc for each MTask body
- **作者**: Geza Lore
- **文件**: `src/V3Partition.cpp`, `src/V3EmitC.cpp`
- **内容**: 为每个 MTask 的 body 生成独立的 CFunc。
- **关键代码变化**:

```cpp
// 旧代码：MTask 代码直接内联在线程函数中
// 线程函数 = [MTask1 代码] [MTask2 代码] ...

// 新代码：每个 MTask 对应一个独立 CFunc
// 线程函数 = call mtask1(); call mtask2(); ...
AstCFunc* mtaskCFuncp = new AstCFunc(...);
mtaskCFuncp->addStmtsp(mtaskBodyp);  // 将 MTask body 放入独立函数
threadFuncp->addStmtsp(new AstCCall(mtaskCFuncp));  // 线程函数调用它
```

- **影响**: 为后续 #4958 的拆分做好了准备。独立的 CFunc 让「代码生成」和「MTask 划分」更容易分离。

#### 2024-03-07 — PR #4950: Split V3Order.cpp into multiple smaller files
- **作者**: Geza Lore
- **文件**: 新增 `src/V3OrderGraphBuilder.cpp`, `src/V3OrderMoveGraphBuilder.cpp`
- **内容**: 纯代码移动，将 V3Order.cpp 拆分为多个小文件。
- **关键变化**:
  - `OrderBuildVisitor` → `V3OrderGraphBuilder.cpp`（重命名为 `V3OrderGraphBuilder`）
  - `ProcessMoveBuildGraph` → `V3OrderMoveGraphBuilder.cpp`（重命名为 `V3OrderMoveGraphBuilder`）
- **影响**: 这是纯代码移动，无任何逻辑改变。目的是让后续重构可以分别修改各个子文件。

#### 2024-03-09 — PR #4953: Split V3Order into further part and decouple components
- **作者**: Geza Lore
- **文件**: 新增 `src/V3OrderProcessDomains.cpp`, `src/V3OrderParallel.cpp`, `src/V3OrderSerial.cpp`, `src/V3OrderCFuncEmitter.cpp`
- **内容**: 将 V3Order 进一步拆分为四个独立模块。
- **关键变化**:

| 新文件 | 职责 | 来源 |
|---|---|---|
| V3OrderProcessDomains.cpp | 将组合逻辑分配到 sensitivity domain | 原 V3Order.cpp 中的 processDomain 部分 |
| V3OrderParallel.cpp | 并行代码构造（MTask 划分） | 原 V3Order.cpp 中的并行代码生成 |
| V3OrderSerial.cpp | 串行代码构造（单线程 eval） | 原 V3Order.cpp 中的串行代码生成 |
| V3OrderCFuncEmitter.cpp | 公共代码提取（processMoveOneLogic） | 原 V3Order.cpp 中的重复代码 |

- **影响**: V3OrderParallel.cpp 中包含了与 V3Partition 相关的并行代码生成逻辑。Geza Lore 在 PR 描述中提到：「Could combine this with some parts of V3Partition - those not called from V3Partition::finalize - but that's not for this patch」。

#### 2024-03-10 — PR #4958: Split V3Partition into logically separate pieces
- **作者**: Geza Lore
- **文件**: 新增 `src/V3OrderParallel.cpp`, `src/V3ExecGraph.cpp`；重命名 `src/V3Partition.cpp` 相关代码
- **内容**: 将 V3Partition 彻底拆分为两个逻辑上独立的模块。
- **关键变化**:

| 新文件 | 职责 | 来源 |
|---|---|---|
| V3OrderParallel.cpp | MTask 划分/粗化算法（PartContraction、PartPropagate） | 原 V3Partition.cpp 中的划分算法 |
| V3ExecGraph.cpp | AstExecGraph 下放到线程函数（V3Partition::finalize） | 原 V3Partition.cpp 中的 finalize |

```cpp
// V3ExecGraph.h（新文件）
class V3ExecGraph final {
public:
    static void implement(AstNetlist* nodep);
};

// V3ExecGraph.cpp
void V3ExecGraph::implement(AstNetlist* nodep) {
    // 1. 创建 ThreadSchedule
    // 2. 为每个 MTask 创建 CFunc（或与 #4933 配合）
    // 3. 在 thread 入口函数中创建 MTask 调用链
}
```

- **影响**: 这是 V3Partition 演进的终点。V3Partition 这个名字在 2024 年后基本不再作为核心模块名存在，取而代之的是 V3OrderParallel（算法）和 V3ExecGraph（实现）。

---

### 2025：触发器向量的简化和后续微调

#### 2025-08-19 — PR #6307: Remove AstAssignPre/AstAssignPost
- **作者**: Geza Lore
- **文件**: `src/V3Order.cpp`, `src/V3Sched.cpp` 等
- **内容**: 用 `AstAlwaysPre`/`AstAlwaysPost` 替代 `AstAssignPre`/`AstAssignPost`，为 #6280 做准备。
- **影响**: 这是 V3Sched 和 V3Order 的进一步清理，让 scheduling 相关的 AST 节点更语义化。

#### 2025-10-27 — PR #6581: Create if statements for triggers during scheduling
- **作者**: Geza Lore
- **文件**: `src/V3Sched.cpp`
- **内容**: 将 event trigger 的 `AstIf` 节点创建从 V3Clock 移到 V3Sched*。
- **影响**: 避免在 CFunc 或 MTask body 中传递 `AstActive`，让 MTask 的边界更清晰。

#### 2025-10-31 — PR #6616: Replace VlTriggerVec with unpacked array
- **作者**: Geza Lore
- **文件**: `src/V3SchedTrigger.cpp`, `src/V3Sched.cpp`
- **内容**: 将 `VlTriggerVec<T_size>` 模板类替换为普通的 unpacked 数组，触发器操作变成常规数组操作。
- **关键变化**:

```cpp
// 旧代码（V3Sched.cpp / V3TriggerVec.h）
template <size_t T_size>
class VlTriggerVec final {
    std::array<uint64_t, (T_size + 63) / 64> m_words;
public:
    void set(size_t idx) { ... }
    bool at(size_t idx) const { ... }
};

// 新代码（V3SchedTrigger.cpp）
// 触发器向量就是普通数组
// 特殊操作（如批量检查）作为常规 AstCFunc 生成
```

- **影响**: 去掉了模板类型，简化了代码。性能不变，因为编译器对数组和 `std::array` 的优化相同。这进一步表明 V3Sched 在持续简化。

---

## 演进总结：从单体到微服务化的架构变迁

### V3Partition 的 4 年演进

| 年份 | 状态 | 核心职责 | 文件 |
|---|---|---|---|
| 2020 | 单体 | MTask 划分 + AstExecGraph 生成 + 线程打包 | `src/V3Partition.cpp` |
| 2021 | 第一次解耦 | AstExecGraph 构造从 V3EmitC 移回 V3Partition::finalize | `src/V3Partition.cpp` |
| 2022 | 优化 | PartContraction 工作集优化，bypass 零成本顶点 | `src/V3Partition.cpp` |
| 2024 | 彻底拆分 | V3OrderParallel（划分算法）+ V3ExecGraph（实现） | `src/V3OrderParallel.cpp`, `src/V3ExecGraph.cpp` |

### V3Order 的 4 年演进

| 年份 | 状态 | 核心职责 | 文件 |
|---|---|---|---|
| 2020 | 单体 | 依赖排序 + 生成 _eval_settle / _eval 循环 | `src/V3Order.cpp` |
| 2022 | 职责分离 | 依赖排序 → V3Order；代码生成 → V3Sched | `src/V3Order.cpp`, `src/V3Sched.cpp` |
| 2024 | 彻底拆分 | 排序分析 + 图构建 + 并行/串行代码生成分离 | `src/V3Order*.cpp` (6 个文件) |

### 架构设计原则总结

1. **先物理拆分，再逻辑优化**：每次重构都是纯代码移动，先让文件边界对齐职责边界，再优化每个文件内部的逻辑。
2. **算法和代码生成必须分离**：V3OrderParallel（算法）和 V3ExecGraph（实现）的分离是最终目标。
3. **调度器语义是性能的前提**：V3Sched 的引入不是为了性能，而是为了正确性（IEEE 1800-2017）。但正确性为后续的优化（如 Activity Gating）打开了空间。
4. **模板类型不是免费的**：VlTriggerVec 最终也被替换为普通数组，说明模板类型增加了编译器复杂度和代码可读性成本，而性能收益可以靠编译器对普通数组的优化来替代。

## 对 RTL 仿真器多线程化的启示

这份演进历史告诉我们：
- **不要一开始就写一个大文件**：如果我们的 RTL 优化器一开始就有一个 4000 行的「多线程调度器」文件，4 年后它也会变成维护噩梦。应该从第一天就把「划分算法」和「代码生成」放在不同文件中，即使初期代码量很少。
- **调度器语义必须从一开始就正确**：如果我们在 V4 阶段（没有 Active/NBA 分离）就引入多线程，后续升级到 V5 的语义时，所有 MTask 的划分结果都需要重新验证。正确性应该在项目启动时就作为第一优先级。
- **profile 基础设施要跟着代码一起演进**：`--prof-exec` 在每次代码结构变化后都会「bit-rot」，需要持续维护。我们的项目应该让 profile 事件是「通用的 section_push/section_pop」，而不是硬编码的 eval/evl_loop。

## 相关链接

- [PR #2336](https://github.com/verilator/verilator/pull/2336) — Trace activity flags
- [PR #3022](https://github.com/verilator/verilator/pull/3022) — AstExecGraph 解耦
- [PR #3329](https://github.com/verilator/verilator/pull/3329) — V3Order/V3Sched 重构
- [PR #3384](https://github.com/verilator/verilator/pull/3384) — IEEE 1800-2017 调度器
- [PR #3587](https://github.com/verilator/verilator/pull/3587) — PartContraction 优化
- [PR #4950](https://github.com/verilator/verilator/pull/4950) — V3Order 拆分
- [PR #4953](https://github.com/verilator/verilator/pull/4953) — V3Order 进一步拆分
- [PR #4958](https://github.com/verilator/verilator/pull/4958) — V3Partition 拆分
- [PR #4933](https://github.com/verilator/verilator/pull/4933) — 独立 CFunc per MTask
- [PR #4228](https://github.com/verilator/verilator/pull/4228) — 多线程代码分离
- [Issue #3278](https://github.com/verilator/verilator/issues/3278) — 调度器重设计
- [Issue #2913](https://github.com/verilator/verilator/issues/2913) — 多线程小设计减速

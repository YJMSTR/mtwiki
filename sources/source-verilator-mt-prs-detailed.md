---
title: "Verilator 多线程相关 PR 深度分析合集"
description: "对 verilator/verilator 仓库中 #2200-#4994 范围内与多线程、MTask、Partition、调度器相关的关键 PR 进行逐条解析，包含代码 diff 片段、设计决策与性能影响讨论。"
source_url: "https://github.com/verilator/verilator"
source_type: "github-pr"
author: "Geza Lore, Wilson Snyder, Mariusz Glebocki, et al."
date: "2020-2024"
tags: ["verilator", "multithreading", "mtask", "partition", "scheduler", "v3partition", "v3order"]
keywords: ["MTask", "ExecMTask", "V3Partition", "V3Order", "ThreadSchedule", "PartContraction", "V3Sched", "V3ExecGraph"]
capture_date: "2026-06-26"
---

# Verilator 多线程相关 PR 深度分析合集

## 来源

- URL: https://github.com/verilator/verilator
- 类型: github-pr
- 作者: Geza Lore, Wilson Snyder, Mariusz Glebocki, Krzysztof Bieganski 等
- 日期: 2020-2024

## 摘要

本文档汇总了 Verilator 仓库中 2020-2024 年间与多线程仿真（`--threads` / `--MTask` / `V3Partition` / `V3Order`）相关的 10 个核心 PR 的深度分析。这些 PR 覆盖了从线程调度逻辑重构、调度器语义升级（V4 → V5）、MTask 合并优化、到 V3Partition 与 V3Order 彻底拆分的历史演进。每个 PR 都配有代码 diff 片段、关键讨论摘录和对我们 RTL 多线程优化器项目的启示。

---

## 关键要点

1. **V3Partition 的职责经历了从"包打天下"到"专事专办"的演进**：2020 年 V3Partition 同时负责 MTask 划分算法和 AstExecGraph 的线程打包；2024 年被拆分为 V3OrderParallel（划分）和 V3ExecGraph（实现）。
2. **调度器语义升级是 V5 最大的架构变化**：从 V4 的 `eval+change_detect` 循环改为符合 IEEE 1800-2017 的 Active/NBA 区域分离，这是支持多线程正确仿真的前提。
3. **MTask 合并顺序对性能有运气成分**：PartContraction 中 tie-breaking 依赖顶点创建顺序，导致同一优化在不同 benchmark 上表现不同。
4. **多线程不适合小设计**：线程同步开销在 tiny 设计（如 Fibonacci 模块）上远大于并行收益，这是已知特性而非 bug。
5. **代码组织持续"微服务化"**：2022-2024 年 Geza Lore 主导了 V3Order 和 V3Partition 的连续拆分，将单体文件拆为多个专注于单一算法的文件。

---

# PR #2336: Internalize trace activity flags（2020）

## 来源

- URL: https://github.com/verilator/verilator/pull/2336
- 作者: Wilson Snyder
- 日期: 2020-05-14
- 状态: merged

## 摘要

将 trace activity flags 的维护从 trace 代码中移入核心仿真循环，使其能被 MTask 感知。这是让多线程 trace 正确工作的早期基础工作。

## 关键要点

- 在 MTask 并行执行时，每个 MTask 需要知道自己是否触发了 trace 敏感的信号变化；之前这个逻辑在 trace 代码中串行执行，无法正确捕获并行 MTask 的 activity。
- 引入 `traceActivity` 标志的内联化，使得每个 MTask 在执行结束时可以设置对应的 activity flag。
- 为多线程 trace 的正确性奠定了基础，否则 `--trace` 与 `--threads` 并用时会出现数据竞争或遗漏。

## 对 RTL 仿真器多线程化的启示

Trace 活动标志的同步问题是所有并行仿真器都需要面对的。如果我们的多线程 RTL 优化器需要支持波形输出，必须在划分 MTask 时就把 trace 写入的依赖关系考虑进去，或者在 MTask 边界处显式同步 activity flags。

## 原文摘录

> "Move the activity tracking to be part of the generated eval loop, so that multithreading can track it."

---

# PR #3022: Construct AstExecGraph inside V3Partition::finalize（2021）

## 来源

- URL: https://github.com/verilator/verilator/pull/3022
- 作者: Geza Lore
- 日期: 2021-06-17
- 状态: merged

## 摘要

将线程入口点的构造逻辑从 `V3EmitC` 移入 `V3Partition::finalize`，并引入 `ThreadSchedule` 类来解耦 ExecMTask 的 thread/threadRoot/packNextp 状态。这是 V3Partition 与 Emitter 解耦的关键一步。

## 关键要点

- **before**: `V3EmitC` 直接负责把 `ExecMTask` 输出到 C 代码，它自己决定哪些 MTask 放在哪个线程。
- **after**: `V3Partition::finalize` 统一生成 `AstExecGraph`，包含完整的线程调度信息；`V3EmitC` 只负责把已经排好序的 AST 节点输出为 C 代码。
- 引入 `ThreadSchedule` 类：

```cpp
class ThreadSchedule final {
    std::vector<std::vector<const ExecMTask*>> m_threads;
    std::unordered_map<const ExecMTask*, uint32_t> m_threadId;
    uint32_t crossThreadDependencies(const ExecMTask* mtaskp) const {
        // 统计该 MTask 依赖多少个其他线程的 MTask
    }
};
```

- 引入 `MTASKSTATE` 基础数据类型，用于表示 MTask 内部状态变量。

## 代码 diff 片段

```cpp
// V3Partition.cpp 新增 ThreadSchedule
class ThreadSchedule final {
    const std::vector<const ExecMTask*> m_tasks;
    std::vector<std::vector<const ExecMTask*>> m_threads;
    std::unordered_map<const ExecMTask*, uint32_t> m_threadId;
    std::unordered_map<const ExecMTask*, uint32_t> m_crossThreadDeps;

public:
    uint32_t threadId(const ExecMTask* mtaskp) const { return m_threadId.at(mtaskp); }
    uint32_t nThreads() const { return m_threads.size(); }
    uint32_t crossThreadDependencies(const ExecMTask* mtaskp) const;
};
```

```cpp
// V3EmitC.cpp 删除的代码（不再在 Emitter 里构造线程调度）
- // Build thread schedule here
- // ... 大量直接操作 ExecMTask 的代码 ...
+ // 现在只需遍历 AstExecGraph 已经排好的节点
+ for (AstExecGraph* const graphp : ... ) {
+     emit(graphp);
+ }
```

## 对 RTL 仿真器多线程化的启示

Emitter 和 Scheduler 的解耦是良好架构的标志。在我们的项目中，如果「把 AST 编译为最终代码」与「决定哪些任务跑在哪个线程」混在同一个模块里，会导致后续优化极其困难。应该引入一个中间的 ThreadSchedule/ExecGraph 表示层，让划分算法和代码生成互不干扰。

---

# PR #3329: V3Order/V3Sched 重构：引入 V3Sched（2022）

## 来源

- URL: https://github.com/verilator/verilator/pull/3329
- 作者: Geza Lore
- 日期: 2022-04-14
- 状态: merged

## 摘要

将 V3Order 中直接生成调度逻辑的职责剥离出去，引入新的 `V3Sched` 模块。V3Order 现在只负责分析依赖关系图，V3Sched 负责生成实际的调度代码（如 `_eval_settle`、`_eval`、`_eval_initial`）。这是 V4 调度器架构现代化的关键一步。

## 关键要点

- V3Order 的职责收窄：从「分析依赖 + 生成调度代码」变成「分析依赖，生成排序后的逻辑序列」。
- 新增 `AstEval` 节点：表示一个评估函数，包含 `evalp`（正常评估）、`evalSettlep`（收敛评估）、`evalInitialp`（初始化评估）。
- 变更检测被拆分为 `_change_snapshot` + `_change_check`：
  - snapshot：在 eval 前保存状态
  - check：在 eval 后比较，决定是否需要下一轮收敛
- 为后续 V5 的 Active/NBA 区域分离做好了铺垫。

## 代码 diff 片段

```cpp
// V3Sched.h 新增接口
class V3Sched {
public:
    static void schedule(AstNetlist* nodep);
};

// V3Order.cpp 删除的调度代码
- // 直接在这里生成 AstActive / AstAlways 节点
- // 直接生成 _eval_settle / _eval 循环

// V3Sched.cpp 新增的调度代码
+ void V3Sched::schedule(AstNetlist* nodep) {
+     // 根据 V3Order 的输出，生成 eval / settle / initial 函数
+ }
```

```cpp
// AstEval 节点定义
class AstEval final : public AstNode {
    AstCFunc* m_evalp = nullptr;
    AstCFunc* m_evalSettlep = nullptr;
    AstCFunc* m_evalInitialp = nullptr;
public:
    AstCFunc* evalp() const { return m_evalp; }
    AstCFunc* evalSettlep() const { return m_evalSettlep; }
};
```

## 对 RTL 仿真器多线程化的启示

将「排序分析」和「调度代码生成」分离，是支持多种调度策略（单线程、多线程、V4 循环、V5 区域）的前提。在我们的 RTL 优化器中，如果「排序」和「代码生成」耦合在一起，每增加一种新的多线程调度模式（比如 Static Schedule vs Dynamic Schedule）都需要修改同一个文件，维护成本极高。

---

# PR #3384: IEEE 1800-2017 Compliant Scheduler（V5 核心调度器，2022）

## 来源

- URL: https://github.com/verilator/verilator/pull/3384
- 作者: Geza Lore
- 日期: 2022-09-01
- 状态: merged（进入 develop-v5 分支）

## 摘要

实现符合 IEEE 1800-2017 的调度器，将仿真循环划分为 Active 区域（阻塞赋值）和 NBA 区域（非阻塞赋值），支持生成时钟的正确行为。这是 Verilator 历史上最重要的调度器重构，也是多线程仿真正确性的基石。

## 关键要点

- **V4 调度器**：`eval()` + `change_detect()` 循环，直到没有变化。这不符合 IEEE 标准，对生成时钟和事件驱动语义支持不好。
- **V5 调度器**：严格区分 `Active` 和 `NBA` 区域：
  - Active 区域：执行组合逻辑和阻塞赋值
  - NBA 区域：应用非阻塞赋值的更新值
  - 组合逻辑收敛循环作为内层循环嵌套在 Active 区域内
- 引入 `VlTriggerVec<T_size>` 模板类：用于存储触发器向量，表示哪些事件被触发了。
- 新增边沿类型：`ET_CHANGED`, `ET_EVENT`, `ET_HYBRID`。
- `V3Sched::partition` 将逻辑划分为 `act` 和 `nba` 区域。

## 代码 diff 片段

```cpp
// VlTriggerVec<T_size> 模板类
// 用于存储触发器向量，表示哪些事件被触发了
template <size_t T_size>
class VlTriggerVec final {
    std::array<uint64_t, (T_size + 63) / 64> m_words;
public:
    void set(size_t idx) { m_words[idx / 64] |= (1ULL << (idx % 64)); }
    bool at(size_t idx) const { return (m_words[idx / 64] >> (idx % 64)) & 1; }
    void clear() { std::fill(m_words.begin(), m_words.end(), 0); }
};
```

```cpp
// V3Sched.cpp 中 Active/NBA 区域划分
void V3Sched::partition(AstNetlist* nodep) {
    // 将逻辑划分为 'act' 和 'nba' 区域
    // act: 组合逻辑 + 阻塞赋值
    // nba: 非阻塞赋值更新
    // 组合逻辑收敛循环作为内层循环
}
```

```cpp
// 生成时钟的正确行为（来自 PR 讨论）
// 旧 V4：在 change_detect 之后才更新时钟，导致生成时钟的仿真结果不正确
// 新 V5：在 NBA 区域直接应用更新，Active 区域立即能看到新值
```

## 对 RTL 仿真器多线程化的启示

如果我们的 RTL 优化器要支持事件驱动语义（非阻塞赋值、生成时钟），必须从一开始就区分 Active 和 NBA 区域。多线程划分时，如果两个 MTask 同时访问同一个变量的 `_q`（旧值）和 `_d`（新值），必须在区域边界上同步。V5 的调度器设计证明了：正确的语义是性能的前提，不能为了并行而牺牲正确性。

## 原文摘录

> "This implements the scheduler semantics according to IEEE 1800-2017 Chapter 4, which is required for correct behavior with generated clocks."

> "The key change is that we now have separate Active and NBA regions, with combinational convergence as an inner loop within the Active region."

---

# PR #3587: V3Partition PartContraction 工作集优化（2022）

## 来源

- URL: https://github.com/verilator/verilator/pull/3587
- 作者: Geza Lore
- 日期: 2022-08-31
- 状态: merged（经讨论后）

## 摘要

利用 MTask 输入图的拓扑性质，在 PartContraction 初始阶段就跳过大量不需要合并的候选边（bypass 零成本顶点），将 verilation 速度提升 25%。但合并顺序的随机性导致 benchmark 性能出现波动，引发了对「算法正确性 vs 性能稳定性」的深入讨论。

## 关键要点

- **核心优化**：引入 `bypassOk()` 函数，在构建初始 MTask 图时，如果某个变量节点的 `fanIn * fanOut <= fanIn + fanOut`，则跳过它，不把它加入 merge candidate 列表。
- **理论依据**：被 bypass 的顶点成本为 0，不影响关键路径估计，也不影响最终调度质量。
- **性能影响**：
  - 编译时间：在最大设计上调度阶段快 25%。
  - 仿真时间：Open Titan 4 线程慢约 2%，XiangShan 4 线程慢约 20%。
- **性能波动原因**：MTask 合并时 tie-breaking 依赖顶点 ID，而 ID 是按创建顺序分配的。跳过一些顶点改变了创建顺序，导致同样的合并算法在同样的 critical path 下，产生了不同的 MTask 划分结果。
- **讨论结论**：这是一个"算法正确性无可置疑，但性能对随机性敏感"的案例。Geza Lore 最终在 #3527 合并后，由于「星象对齐」（luck is on our side），整体 benchmark 表现反而最好。

## 代码 diff 片段

```cpp
// V3Partition.cpp 新增的 bypassOk 逻辑
bool bypassOk(const V3GraphVertex* vxp) {
    const uint32_t fanIn = vxp->fanIn();
    const uint32_t fanOut = vxp->fanOut();
    // 如果 fanIn * fanOut <= fanIn + fanOut，跳过该顶点
    return fanIn * fanOut <= fanIn + fanOut;
}

// 在构建初始 MTask 图时
for (auto* vxp : graph.vertices()) {
    if (bypassOk(vxp)) {
        // 不加入 merge candidate scoreboard
        continue;
    }
    // 否则加入工作集
    addToScoreboard(vxp);
}
```

```cpp
// 现有代码中已有的相关注释（Geza Lore 指出）
// https://github.com/verilator/verilator/blob/c0f9b0d8f689e695100aa9f0d9bb544a9edc3a4e/src/V3Partition.cpp#L2024-L2029
// 说明 tie-breaking 已经存在 order-dependent 的问题
// 同样 incorporate 到循环里也会改变 ID，产生类似的差异
```

## 对 RTL 仿真器多线程化的启示

MTask 合并/划分的性能对处理顺序极其敏感。这给我们的启示是：
1. 任何改变图遍历顺序的优化，都必须用大量 benchmark 验证，不能只看编译时间。
2. 如果我们的划分算法存在 tie-breaking 依赖，可以考虑引入确定性排序（如按字典序或按 cost 的精确值），而非依赖 ID 顺序。
3. 成本为 0 的顶点可以安全地提前 bypass，这是一个通用的图优化技巧。

## 原文摘录

> "The catch is that on the benchmarks I have access to, the model performance is worse... This performance regression however is only due to the order in which we process vertices/edges in the graph."

> "With this optimization in, we end up being unlucky on these benchmarks."

> "I am fairly confident there isn't anything more nefarious going on."

---

# PR #4228: Rework multithreading handling to separate by code units（2023）

## 来源

- URL: https://github.com/verilator/verilator/pull/4228
- 作者: Mariusz Glebocki (Antmicro)
- 日期: 2023-09-25
- 状态: merged

## 摘要

将多线程相关代码按「使用多线程」和「永不使用多线程」的代码单元分离。具体来说，将单线程仿真代码和 Verilator 编译器本身不依赖多线程的代码从多线程相关的宏/条件编译中解放出来，减少编译器复杂度。

## 关键要点

- 将 `VL_THREADS` 相关的宏条件进行更精确的范围控制。
- 让不依赖多线程的代码单元完全不需要包含多线程头文件或链接线程库。
- 减少了编译器在非多线程模式下的编译时间和依赖。
- 对生成的仿真模型代码没有直接影响，属于基础设施清理。

## 对 RTL 仿真器多线程化的启示

多线程支持不应该让不用的代码承担复杂度。在我们的项目中，如果编译器前端（如 RTL 解析、类型检查）不需要关心多线程，就不应该被多线程相关的宏和头文件污染。这能减少维护负担，也让单线程编译路径更轻量。

---

# PR #4950: Split V3Order.cpp into multiple smaller files（2024）

## 来源

- URL: https://github.com/verilator/verilator/pull/4950
- 作者: Geza Lore
- 日期: 2024-03-07
- 状态: merged

## 摘要

将 V3Order.cpp 这个 3000+ 行的单体文件拆分为多个更小的文件：V3OrderGraphBuilder、V3OrderMoveGraphBuilder 等。这是纯代码移动，无任何功能改变，为后续 #4953 和 #4958 的大规模重构做准备。

## 关键要点

- `OrderBuildVisitor` → `V3OrderGraphBuilder.cpp`（重命名为 `V3OrderGraphBuilder`）
- `ProcessMoveBuildGraph` → `V3OrderMoveGraphBuilder.cpp`（重命名为 `V3OrderMoveGraphBuilder`）
- 纯代码移动，不引入任何逻辑变化。
- 动机：V3Order.cpp 已经臃肿到单人难以维护的程度，拆分后才能继续后续重构。

## 对 RTL 仿真器多线程化的启示

大型单体文件（如 V3Order.cpp）的维护成本会指数增长。如果我们的 RTL 优化器中的某个模块（如「依赖分析 + 排序 + 代码生成」）已经膨胀到上千行，应该果断先拆分后重构，否则每次改动都需要理解整个文件的所有逻辑。

---

# PR #4953: Split V3Order into further part and decouple components（2024）

## 来源

- URL: https://github.com/verilator/verilator/pull/4953
- 作者: Geza Lore
- 日期: 2024-03-09
- 状态: merged

## 摘要

在 #4950 的基础上，将 V3Order 进一步拆分为 V3OrderProcessDomains、V3OrderParallel、V3OrderSerial、V3OrderCFuncEmitter。每个文件负责一个独立的算法步骤，彻底解耦了并行代码生成和串行代码生成。

## 关键要点

- **V3OrderProcessDomains**：处理 domain assignment，将组合逻辑分配到对应的 sensitivity domain。
- **V3OrderParallel**：并行代码构造（MTask 划分）。这是从 V3Partition 中移出来的逻辑，与 V3Partition 中的非 finalize 代码可以合并。
- **V3OrderSerial**：串行代码构造（单线程 eval 函数）。
- **V3OrderCFuncEmitter**：并行与串行代码生成中共享的极小公共代码（如 `processMoveOneLogic`）。
- 并行和串行代码生成现在完全独立，可以分别优化。

## 对 RTL 仿真器多线程化的启示

串行路径和并行路径的代码生成应该完全分离。在我们的项目中，如果生成单线程 eval 函数和生成多线程 MTask 函数混在同一个代码生成器里，任何对并行路径的优化都可能意外破坏串行路径。分离后，每个路径的优化都是局部化的，不会互相影响。

---

# PR #4958: Split V3Partition into logically separate pieces（2024）

## 来源

- URL: https://github.com/verilator/verilator/pull/4958
- 作者: Geza Lore
- 日期: 2024-03-10
- 状态: merged

## 摘要

将 V3Partition 彻底拆分为两个逻辑上独立的模块：V3OrderParallel（MTask 划分/粗化算法）和 V3ExecGraph（AstExecGraph 下放到线程函数）。这是 4 年来 V3Partition 演进的最大一步，也是整个多线程架构现代化的收官之作。

## 关键要点

- **V3OrderParallel.cpp**：从 V3Partition 移出的 MTask 划分/粗化算法（如 PartContraction、PartPropagate）。这些算法只关心如何把 logic nodes 合并成 MTask，不关心如何生成最终代码。
- **V3ExecGraph.cpp**：从 V3Partition 移出的 `V3Partition::finalize` 逻辑。负责将 AstExecGraph 中的 MTask 打包到线程函数中，创建 `packNextp` 链和 thread 入口函数。
- 新增 `V3ExecGraph::implement()` 作为单一入口函数。
- 这个 patch 只是代码移动/重命名，几乎没有逻辑改动，但为后续优化（如 #4933 的每个 MTask 独立 CFunc）铺平了道路。

## 代码 diff 片段

```cpp
// V3ExecGraph.h 新增接口
class V3ExecGraph final {
public:
    static void implement(AstNetlist* nodep);
};

// V3ExecGraph.cpp（从 V3Partition.cpp 移出的代码）
void V3ExecGraph::implement(AstNetlist* nodep) {
    // 1. 创建 ThreadSchedule
    // 2. 为每个 MTask 创建 CFunc
    // 3. 在 thread 入口函数中创建 MTask 调用链
}
```

```cpp
// V3OrderParallel.cpp（从 V3Partition.cpp 移出的代码）
// PartContraction、PartPropagate 等算法
// 只关心 MTask 的 cost model 和合并策略
// 不关心代码生成
```

## 对 RTL 仿真器多线程化的启示

这是架构设计的最终目标：划分算法（Partitioning）和代码生成（Codegen）完全分离。V3Partition 曾经是一个 4000+ 行的文件，既包含「哪些节点合并成 MTask」的图算法，又包含「如何把 MTask 变成 C 函数」的代码生成。在我们的 RTL 优化器中，应该在一开始就设计好这个边界：
- 上游：MTask Partitioner（纯算法，只输出 MTask 的 DAG）
- 下游：MTask Codegen（根据 DAG 生成线程函数，不关心 DAG 怎么来的）

---

# PR #4933: Emit a separate CFunc for each MTask body（2024）

## 来源

- URL: https://github.com/verilator/verilator/pull/4933
- 作者: Geza Lore
- 日期: 2024-02-29
- 状态: merged

## 摘要

为每个 MTask 的 body 生成一个独立的 CFunc，而不是把所有 MTask 的代码内联到线程函数中。这为后续的 MTask 内联/外联优化、以及更好的 profile 分析提供了基础。

## 关键要点

- before：线程函数直接包含 MTask 的所有代码，MTask 之间没有明确的函数边界。
- after：每个 MTask 对应一个独立的 CFunc，线程函数变成对这些 CFunc 的调用序列。
- 好处：
  1. 编译器（gcc/clang）可以对每个 MTask 的 CFunc 独立优化（LTO 时尤其有效）。
  2. 更容易做 profile analysis，每个 MTask 的函数名出现在 stack trace 中。
  3. 为未来可能的 MTask 动态调度（如 work-stealing）提供了统一的函数接口。

## 对 RTL 仿真器多线程化的启示

把 MTask 的「逻辑边界」和「函数边界」对齐，是多线程优化器可维护性和可分析性的关键。如果我们的 MTask 代码是内联在线程函数中的，profile 时很难区分「是哪个 MTask 在耗时」；生成独立函数后， flame graph 和 gantt 分析都会更清晰。

## 相关链接

- [PR #4950](https://github.com/verilator/verilator/pull/4950) — V3Order 拆分
- [PR #4953](https://github.com/verilator/verilator/pull/4953) — V3Order 进一步拆分
- [PR #4958](https://github.com/verilator/verilator/pull/4958) — V3Partition 拆分
- [PR #4957](https://github.com/verilator/verilator/pull/4957) — 图并行度报告泛化

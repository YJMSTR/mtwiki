---
title: "Verilator多线程PR演进与Issue地图"
description: "Verilator 2020-2025年多线程架构演进全景：从V3Partition单体到V3OrderParallel+V3ExecGraph分离，PR时间线、Issue地图、代码演进与对RTL仿真器的启示"
source_refs: ["source-verilator-mt-prs-detailed", "source-verilator-mt-issues", "source-verilator-partition-evolution"]
author: "Wiki写作_最终聚焦"
date: "2025-07-20"
tags: ["verilator", "multithreading", "PR演进", "MTask", "V3Partition", "V3Order", "调度器"]
---

# Verilator多线程PR演进与Issue地图

## 1. PR演进时间线（2020-2025）

| 年份 | PR | 作者 | 核心变更 | 性能/架构影响 |
|------|-----|------|----------|--------------|
| 2020 | **#2336** | Wilson Snyder | Trace activity flags 内联化，MTask可感知 | 多线程trace兼容基础 |
| 2021 | **#3022** | Geza Lore | `AstExecGraph`在`V3Partition::finalize`内构造，`ThreadSchedule`解耦 | Emitter与Scheduler首次解耦 |
| 2022 | **#3329** | Geza Lore | 引入`V3Sched`，V3Order只负责依赖排序 | V4调度器架构现代化 |
| 2022 | **#3384** | Geza Lore | IEEE 1800-2017 Compliant Scheduler（V5） | Active/NBA区域分离，多线程正确性基石 |
| 2022 | **#3587** | Geza Lore | `PartContraction`工作集优化，`bypassOk()` | 编译速度+25%，但仿真性能波动 |
| 2023 | **#4228** | Mariusz Glebocki | 多线程代码按代码单元分离 | 基础设施清理，降低编译复杂度 |
| 2024 | **#4933** | Geza Lore | 每MTask独立CFunc | 火焰图可分析、LTO独立优化 |
| 2024 | **#4950** | Geza Lore | `V3Order.cpp`拆分为6+文件 | 纯代码移动，为后续重构铺路 |
| 2024 | **#4953** | Geza Lore | V3Order进一步拆分为`V3OrderProcessDomains`/`Parallel`/`Serial`/`CFuncEmitter` | 并行/串行代码生成完全分离 |
| 2024 | **#4958** | Geza Lore | `V3Partition`彻底拆分为`V3OrderParallel`+`V3ExecGraph` | 划分算法与代码生成完全分离 |
| 2025 | **#6616** | Geza Lore | `VlTriggerVec`模板替换为unpacked数组 | 简化代码，编译器优化不变 |

### 关键PR深度解析

#### #3022: AstExecGraph解耦（2021）

```cpp
// 引入ThreadSchedule类，将线程调度信息从V3EmitC移回V3Partition
class ThreadSchedule final {
    std::vector<std::vector<const ExecMTask*>> m_threads;
    std::unordered_map<const ExecMTask*, uint32_t> m_threadId;
    std::unordered_map<const ExecMTask*, uint32_t> m_crossThreadDeps;
public:
    uint32_t threadId(const ExecMTask* mtaskp) const { return m_threadId.at(mtaskp); }
    uint32_t nThreads() const { return m_threads.size(); }
    uint32_t crossThreadDependencies(const ExecMTask* mtaskp) const;
};
```

**启示**：Emitter和Scheduler必须解耦。在我们的RTL优化器中，应引入中间表示层（如`ThreadSchedule`/`ExecGraph`），让划分算法和代码生成互不干扰。

#### #3329: V3Order/V3Sched重构（2022）

```cpp
// V3Sched.h 新增接口
class V3Sched {
public:
    static void schedule(AstNetlist* nodep);
};

// V3Order职责收窄：只分析依赖，生成排序后的逻辑序列
// V3Sched负责生成 _eval_settle / _eval / _eval_initial 函数
```

**启示**：「排序分析」和「调度代码生成」必须分离。每增加一种新的多线程调度模式，不应修改同一个文件。

#### #3384: IEEE 1800-2017调度器（V5核心，2022）

V4调度器：`eval()` + `change_detect()` 循环 → 不符合标准，生成时钟行为错误。

V5调度器：
```cpp
// Active区域：组合逻辑 + 阻塞赋值（内层收敛循环）
// NBA区域：非阻塞赋值更新（_d -> _q）
void V3Sched::partition(AstNetlist* nodep) {
    // 将逻辑划分为 'act' 和 'nba' 区域
}

// VlTriggerVec<T_size> 模板类 — 事件触发位向量
template <size_t T_size>
class VlTriggerVec final {
    std::array<uint64_t, (T_size + 63) / 64> m_words;
public:
    void set(size_t idx) { m_words[idx / 64] |= (1ULL << (idx % 64)); }
    bool at(size_t idx) const { return (m_words[idx / 64] >> (idx % 64)) & 1; }
};
```

**启示**：正确的调度器语义是性能的前提。多线程划分时，必须在Active/NBA区域边界同步，否则必然出现race condition。

#### #3587: PartContraction 25%编译加速（2022）

```cpp
// bypassOk()：跳过零成本顶点，不加入merge candidate
bool bypassOk(const V3GraphVertex* vxp) {
    const uint32_t fanIn = vxp->fanIn();
    const uint32_t fanOut = vxp->fanOut();
    return fanIn * fanOut <= fanIn + fanOut;  // 零成本顶点判定
}
```

**关键发现**：MTask合并顺序对性能有「运气成分」。tie-breaking依赖顶点创建顺序，跳过顶点改变了创建顺序，导致同一优化在不同benchmark上表现不同。

**启示**：任何改变图遍历顺序的优化，都必须用大量benchmark验证。可考虑引入确定性排序（如按字典序），而非依赖ID顺序。

#### #4950/#4953/#4958: 2024年彻底拆分6+文件

| 新文件 | 来源 | 职责 |
|--------|------|------|
| `V3OrderGraphBuilder.cpp` | V3Order.cpp | 依赖图构建 |
| `V3OrderMoveGraphBuilder.cpp` | V3Order.cpp | Move图构建 |
| `V3OrderProcessDomains.cpp` | V3Order.cpp | Domain assignment |
| `V3OrderParallel.cpp` | V3Partition.cpp | 并行代码构造（MTask划分） |
| `V3OrderSerial.cpp` | V3Order.cpp | 串行代码构造 |
| `V3OrderCFuncEmitter.cpp` | V3Order.cpp | 公共代码提取 |
| `V3ExecGraph.cpp` | V3Partition.cpp | AstExecGraph下放到线程函数 |

```cpp
// V3ExecGraph.h — 单一入口
class V3ExecGraph final {
public:
    static void implement(AstNetlist* nodep);
};
```

**启示**：这是架构设计的最终目标——划分算法（Partitioning）和代码生成（Codegen）完全分离。V3Partition从4000+行单体到两个独立模块，历时4年。

#### #4933: 每MTask独立CFunc（2024）

```cpp
// 旧：线程函数直接包含MTask代码（内联）
// 线程函数 = [MTask1代码] [MTask2代码] ...

// 新：每个MTask对应独立CFunc
// 线程函数 = call mtask1(); call mtask2(); ...
AstCFunc* mtaskCFuncp = new AstCFunc(...);
mtaskCFuncp->addStmtsp(mtaskBodyp);  // MTask body放入独立函数
threadFuncp->addStmtsp(new AstCCall(mtaskCFuncp));  // 线程函数调用
```

**收益**：
1. 编译器可对每个MTask独立优化（LTO时尤其有效）
2. 火焰图和profile分析更清晰
3. 为未来动态调度（work-stealing）提供统一函数接口

---

## 2. Issue地图

### #2913: 小设计多线程减速4x（2021）

**现象**：Fibonacci模块（tiny设计）用`--threads 4`比单线程慢约4倍。

**根本原因**：MTask间线程同步开销（barrier、mutex、condition variable）在tiny设计上是主导成本。当逻辑总量很小，每个MTask执行时间远小于线程同步开销时，多线程就是负优化。

> "Multithreading will only show speedups on much larger designs. In small designs the communication between cores will be much larger than leaving it on one core." — Wilson Snyder

**启示**：
- 引入「粒度检查」机制：若MTask平均执行时间低于阈值（如100μs），不启用多线程
- 自适应线程数：编译时分析设计规模，自动决定线程数
- 前端警告：「此设计规模较小，多线程可能不带来性能提升」

### #3278: V5调度器RFC — 5个优化方向（2022）

Geza Lore提出的V5调度器核心优化方向：

| # | 优化方向 | 说明 | 对多线程RTL仿真器的意义 |
|---|---------|------|------------------------|
| 1 | **Evaluate in dependency order** | 按依赖顺序评估，减少重复计算 | 更好的MTask划分基础 |
| 2 | **SCC iteration** | 强连通分量内串行迭代，SCC间并行 | 并行化的天然边界 |
| 3 | **Remove temporary storage** | 消除eval过程中的临时变量 | 减少内存带宽占用 |
| 4 | **Activity gating** | 只有变化的信号才触发下游评估 | 避免无效计算，显著提升仿真速度 |
| 5 | **Mutexed event domain specialization** | 对互斥事件域特化，减少同步开销 | 降低多线程barrier成本 |

**调度循环V5结构**：
```cpp
while (has_active_events) {
    // Active region
    evaluate_combinational_logic();   // 内层收敛循环
    execute_blocking_assignments();
    
    // NBA region
    apply_non_blocking_assignments();  // _d写入_q
    
    // 检查新事件触发
    update_triggers();
}
```

> "For multithreading, the key insight is that SCCs must be evaluated serially, but different SCCs can run in parallel." — Geza Lore

### #3072 / #2948 / #2929: Trace/MTask兼容性、边界case

| Issue | 问题 | 解决 |
|-------|------|------|
| #3072 | MTask并行执行时trace activity flags遗漏 | 每个MTask内部设置activity flag |
| #2948 | V3Partition cost计算异常值（inf/NaN）无法定位 | 错误信息包含AstNode source location |
| #2929 | `--trace`+`--threads`时assignment节点未正确分配 | 将trace write-after-write依赖纳入cost model |

**启示**：Trace不是「事后附加」功能，而是划分算法的一部分。必须在MTask划分时识别所有被trace变量，确保写入操作在同一MTask或同一trace同步域中。

---

## 3. 代码演进：从单体到微服务化的4年

### V3Partition演进

| 年份 | 状态 | 核心职责 | 文件 |
|------|------|----------|------|
| 2020 | 单体 | MTask划分 + AstExecGraph生成 + 线程打包 | `src/V3Partition.cpp` (~4000行) |
| 2021 | 第一次解耦 | AstExecGraph从V3EmitC移回V3Partition::finalize | `src/V3Partition.cpp` |
| 2022 | 优化 | PartContraction工作集优化，bypass零成本顶点 | `src/V3Partition.cpp` |
| 2024 | 彻底拆分 | V3OrderParallel（划分算法）+ V3ExecGraph（实现） | `src/V3OrderParallel.cpp`, `src/V3ExecGraph.cpp` |

### V3Order演进

| 年份 | 状态 | 核心职责 | 文件 |
|------|------|----------|------|
| 2020 | 单体 | 依赖排序 + 生成_eval_settle/eval循环 | `src/V3Order.cpp` |
| 2022 | 职责分离 | 依赖排序→V3Order；代码生成→V3Sched | `src/V3Order.cpp`, `src/V3Sched.cpp` |
| 2024 | 彻底拆分 | 排序分析+图构建+并行/串行代码生成分离 | `src/V3Order*.cpp` (6个文件) |

### 关键架构原则

1. **先物理拆分，再逻辑优化**：每次重构都是纯代码移动，先让文件边界对齐职责边界
2. **算法和代码生成必须分离**：V3OrderParallel（算法）和 V3ExecGraph（实现）的分离是最终目标
3. **调度器语义是性能的前提**：V3Sched的引入不是为了性能，而是为了正确性（IEEE 1800-2017）
4. **模板类型不是免费的**：VlTriggerVec最终也被替换为普通数组，说明模板增加了编译器复杂度和可读性成本

---

## 4. 对多线程RTL仿真器的启示

### 启示1：Verilator的演进路线是「先做单线程极致优化→再拆分职责→最后并行化」

Verilator没有一开始就做多线程。它先花10+年把单线程仿真速度做到极致（V4调度器），然后才开始逐步引入多线程。这告诉我们：
- **单线程优化是多线程优化的前提**：如果单线程路径还有30%的提升空间，应该先优化单线程
- **多线程引入的正确顺序**：正确调度器语义 → MTask划分 → 线程打包 → 动态优化
- **不要一开始写大文件**：4000行的V3Partition最终花了4年才拆完，维护成本指数增长

### 启示2：小设计多线程负优化的根本原因是同步开销

Verilator的MTask同步开销包括：
- barrier同步（每个eval步结束）
- trace activity flags的atomic更新
- 线程唤醒/睡眠的OS开销

**阈值估算**：对于tiny设计（<1000个always块），每个MTask执行时间<50μs，而线程同步开销约20-100μs，净收益为负。

### 启示3：V5调度器的5个方向值得参考

特别是**Activity Gating**（只有变化的信号才触发下游评估）和**SCC并行化**（强连通分量是并行化的天然边界）。这两个方向在RTL仿真器中可以带来显著收益：
- Activity gating：在时钟驱动的设计中，通常只有<10%的信号在每次时钟边沿变化
- SCC并行化：组合逻辑收敛循环内的SCC之间可以并行评估

---

## 5. 可操作建议

### 建议1：复刻V3OrderParallel→V3ExecGraph的拆分模式

在你的RTL仿真器架构中，从第一天就设计好以下边界：

```
┌─────────────────────────────────────────────────────────┐
│                    RTL Parser / Elaborator                 │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│              V3OrderParallel（MTask Partitioner）         │
│  - 输入：排序后的logic node DAG                         │
│  - 输出：MTask DAG（每个MTask包含哪些logic nodes）       │
│  - 不care：最终代码生成、线程分配                         │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│              V3ExecGraph（MTask Codegen）                │
│  - 输入：MTask DAG                                       │
│  - 输出：线程入口函数、CFunc调用链                         │
│  - 不care：MTask怎么划分来的                             │
└─────────────────────────────────────────────────────────┘
```

### 建议2：评估V5调度器中的activity gating和互斥事件域特化

**Activity Gating实现思路**：
```cpp
// 每个信号附加一个dirty flag
struct Signal {
    uint64_t value;
    std::atomic<bool> dirty;  // 本次时间步是否变化
};

// 只有dirty信号才触发下游评估
void eval_active_region() {
    for (auto* gate : scheduled_gates) {
        bool any_input_changed = false;
        for (auto* input : gate->inputs) {
            if (input->dirty.load(std::memory_order_relaxed)) {
                any_input_changed = true;
                break;
            }
        }
        if (any_input_changed) {
            gate->eval();
            gate->output->dirty.store(true, std::memory_order_relaxed);
        }
    }
}
```

**互斥事件域特化**：将从不同时触发的always块（如不同时钟域）分配到不同线程，无需同步。

### 建议3：参考--prof-exec做性能分析基础设施

Verilator的`--prof-exec`使用通用section机制：
```cpp
// 通用section_push/section_pop，而非硬编码eval/evl_loop
void section_push(const char* name);  // 开始计时
void section_pop();                    // 结束计时并记录

// 使用示例
section_push("MTask_42");
mtask_42_eval();
section_pop();
```

**优势**：代码结构变化后，profile基础设施不会「bit-rot」。

### 建议4：引入粒度检查自动降级机制

```cpp
// 编译时估算MTask平均执行时间
bool should_enable_multithreading(const Design& design) {
    size_t total_logic_nodes = design.count_logic_nodes();
    size_t estimated_mtasks = design.count_always_blocks() + design.count_assigns();
    
    // 经验阈值：每个MTask至少1000个逻辑操作才值得多线程
    double avg_ops_per_mtask = static_cast<double>(total_logic_nodes) / estimated_mtasks;
    
    if (avg_ops_per_mtask < 1000) {
        std::cerr << "Warning: Design too small for multithreading (avg "
                  << avg_ops_per_mtask << " ops/MTask). Using single thread.\n";
        return false;
    }
    return true;
}
```

---

## 相关链接

- [PR #3022](https://github.com/verilator/verilator/pull/3022) — AstExecGraph解耦
- [PR #3329](https://github.com/verilator/verilator/pull/3329) — V3Order/V3Sched重构
- [PR #3384](https://github.com/verilator/verilator/pull/3384) — IEEE 1800-2017调度器
- [PR #3587](https://github.com/verilator/verilator/pull/3587) — PartContraction优化
- [PR #4950](https://github.com/verilator/verilator/pull/4950) — V3Order拆分
- [PR #4953](https://github.com/verilator/verilator/pull/4953) — V3Order进一步拆分
- [PR #4958](https://github.com/verilator/verilator/pull/4958) — V3Partition拆分
- [PR #4933](https://github.com/verilator/verilator/pull/4933) — 独立CFunc per MTask
- [Issue #2913](https://github.com/verilator/verilator/issues/2913) — 多线程小设计减速
- [Issue #3278](https://github.com/verilator/verilator/issues/3278) — V5调度器RFC

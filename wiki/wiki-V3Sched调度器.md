# Verilator V3Sched 调度器核心组

> 知识库索引页。本页整合 V3Sched 调度器文件组的分析结果，链接到对应的 source 文件和延伸阅读。

---

## 快速概览

| 属性 | 内容 |
|------|------|
| **文件组** | V3Sched.h, V3Sched.cpp, V3SchedAcyclic.cpp, V3SchedPartition.cpp, V3SchedReplicate.cpp, V3SchedTiming.cpp, V3SchedTrigger.cpp |
| **仓库** | verilator/verilator |
| **路径** | `src/V3Sched*.cpp/h` |
| **核心职责** | 将 Verilog 逻辑分类、排序、分区，生成运行时 `_eval` 函数 |
| **多线程状态** | 编译期单线程（`VL_MT_DISABLED`），运行时 NBA 区域可并行 |
| **捕获日期** | 2026-07-05 |

---

## 核心结论（TL;DR）

1. **NBA 是唯一多线程获益区域**：Verilator 团队实验证实，Act/Ico 区域多线程总是**净损失**。只有 NBA（非阻塞赋值）区域启用多线程（`v3Global.opt.mtasks()`）。
2. **触发向量是调度核心**：64 位字组成的位数组存储触发状态，`anySet` / `orInto` / `clear` 是运行时调度开销的关键。
3. **#0 延迟摧毁并行性**：如果设计使用 `#0`，所有逻辑进入 act 区域，NBA 区域为空，多线程失效。
4. **组合循环必须先打破**：V3SchedAcyclic 通过 SCC 检测和反馈弧集算法将循环转换为 hybrid 逻辑，否则无法分区并行。
5. **逻辑复制减少同步**：组合逻辑被复制到 ico/act/nba/obs/react 多个区域，以空间换时间。

---

## 文件架构

```
V3Sched.h           ── 核心数据结构：LogicByScope, LogicClasses, LogicRegions, 
                        LogicReplicas, TriggerKit, TimingKit, VirtIfaceTriggers
    │
    ├── V3Sched.cpp        ── 主调度器入口 schedule()，16 步调度流程，
    │                        EvalLoop 构建，_eval 函数组装
    │
    ├── V3SchedAcyclic.cpp ── 打破组合循环：构建依赖图，SCC 检测，
    │                        反馈弧集切割，hybrid 逻辑转换
    │
    ├── V3SchedPartition.cpp ── 逻辑分区到 act/nba 区域：反向数据流追踪，
    │                        颜色标记，#0 延迟处理
    │
    ├── V3SchedReplicate.cpp ── 组合逻辑复制：驱动区域传播，
    │                        位标志 RegionFlags，复制到多区域
    │
    ├── V3SchedTiming.cpp  ── 时序集成：TimingKit，AwaitVisitor，
    │                        fork 转换，外部域映射
    │
    └── V3SchedTrigger.cpp ── 触发器系统：TriggerKit::create，触发向量分配，
                             anySet/clear/orInto 函数，before-trigger 优化
```

---

## 关键数据流

```verilog
[Verilog 源码]
      │
      ▼
[V3Sched::schedule() ── 16 步调度]
      │
      ├── Step 1: gatherLogicClasses() ── 分类逻辑（static/initial/comb/clocked/...）
      │
      ├── Step 3: breakCycles() ── 打破组合循环 → hybrid 逻辑
      │
      ├── Step 5: partition() ── 分区到 act/nba（颜色标记 DFS）
      │         ⚠️ usesZeroDelay() → 全部进 act
      │
      ├── Step 6: replicateLogic() ── 复制组合逻辑到 ico/act/nba/obs/react
      │
      ├── Step 7: createInputCombLoop() ── 创建 ico 区域（顶层输入变化检测）
      │
      ├── Step 8: TriggerKit::create() ── 分配触发向量（64 位字数组）
      │
      ├── Step 9:  create 'act' 区域函数  ── 单线程
      ├── Step 10: create 'nba' 区域函数  ── 🟢 多线程（mtasks）
      ├── Step 11: create 'obs' 区域函数  ── 单线程
      ├── Step 12: create 'react' 区域函数 ── 单线程
      │
      └── Step 14: createEval() ── 组装 _eval 函数
                  │
                  ▼
            [运行时 C++ _eval()]
                  │
    ┌─────────────┼─────────────┐
    ▼             ▼             ▼
 ico loop      act loop       nba loop   ← 嵌套结构
 (单线程)      (单线程)      (🟢 多线程)
```

---

## 触发向量布局

```
| <- bit N-1                                                                         bit 0 -> |
+--------------------+----------------+----------------------------------+--------------------+
| Pre triggers       | Extra triggers | Sense triggers                   | Pre Sense triggers |
+--------------------+----------------+----------------------------------+--------------------+
|        'pre'       |                                 'vec'                                  |
```

| 区域 | 说明 | 多线程意义 |
|------|------|-----------|
| Pre triggers | 只在 act 单次迭代中触发 | 控制 AlwaysPre 执行 |
| Extra triggers | DPI export、first iteration 等 | 外部条件触发 |
| Sense triggers | 时钟/信号边沿触发 | 主要触发源 |
| Pre Sense triggers | Sense 的副本，首次触发后复制 | 支持 act 区域迭代 |

---

## 多线程决策树

```
设计使用 Verilator 多线程？
    │
    ├── 是否使用 #0 延迟？ ── YES → 多线程无效（全部逻辑进 act）
    │
    ├── 是否使用 timing（always @ 挂起）？
    │   └── YES → 外部域映射，trigger scheduler 就绪检查
    │
    ├── NBA 区域是否有足够逻辑？
    │   └── YES → V3Order::order(..., mtasks=true) 生成并行任务
    │   └── NO  → 多线程开销 > 收益
    │
    └── Act/Ico 区域是否多线程？
        └── 永远 NO（实验证实为净损失）
```

---

## 关键代码片段索引

| 概念 | 文件 | 行号 | 说明 |
|------|------|------|------|
| 触发向量字大小 | V3Sched.h | ~150 | `WORD_SIZE_LOG2 = 6`，即 64 位 |
| 16 步调度流程 | V3Sched.cpp | ~500 | `schedule()` 主入口 |
| Act 多线程 = 净损失 | V3Sched.cpp | ~466 | 关键注释 |
| NBA 多线程标记 | V3Sched.cpp | ~476 | `name == "nba" && v3Global.opt.mtasks()` |
| EvalLoop 构建 | V3Sched.cpp | ~70 | `createEvalLoop()` |
| 组合循环打破 | V3SchedAcyclic.cpp | ~280 | `breakCycles()` |
| 分区到 act/nba | V3SchedPartition.cpp | ~200 | `partition()` |
| #0 延迟限制 | V3SchedPartition.cpp | ~220 | `usesZeroDelay()` 强制进 act |
| 逻辑复制 | V3SchedReplicate.cpp | ~220 | `replicateLogic()` |
| 触发器创建 | V3SchedTrigger.cpp | ~350 | `TriggerKit::create()` |
| 触发器检测 | V3SchedTrigger.cpp | ~120 | `createAnySetFunc()` |
| 时序集成 | V3SchedTiming.cpp | ~200 | `prepareTiming()` |

---

## 相关 Source 文件

- [source-verilator-V3Sched调度器.md](sources/source-verilator-V3Sched调度器.md) — 本文件组的详细分析

## 相关 Wiki 页面

- [wiki-verilator-deep-dive.md](wiki-verilator-deep-dive.md) — Verilator 总体深度分析
- [wiki-verilator-prs.md](wiki-verilator-prs.md) — Verilator 相关 PR 分析
- [wiki-verilator-lessons.md](wiki-verilator-lessons.md) — Verilator 多线程经验总结
- [wiki-scheduling.md](wiki-scheduling.md) — 调度策略综述
- [wiki-partitioning-implementation.md](wiki-partitioning-implementation.md) — 分区实现技术
- [wiki-thread-pool-and-scheduler.md](wiki-thread-pool-and-scheduler.md) — 线程池与调度器设计
- [wiki-graph-algorithms.md](wiki-graph-algorithms.md) — 图算法在并行化中的应用
- [wiki-sync-overhead.md](wiki-sync-overhead.md) — 同步开销分析
- [wiki-cache-and-memory.md](wiki-cache-and-memory.md) — 缓存与内存优化
- [wiki-barrier-and-compiler.md](wiki-barrier-and-compiler.md) — Barrier 与编译器优化
- [wiki-simulator-internals.md](wiki-simulator-internals.md) — 仿真器内部机制

---

## 延伸阅读

- [Verilator Internals](https://verilator.org/guide/internals.html)
- [Verilator Multi-Threading](https://verilator.org/guide/threads.html)
- [Verilator Scheduling Paper](https://ieeexplore.ieee.org/document/...)（如有）

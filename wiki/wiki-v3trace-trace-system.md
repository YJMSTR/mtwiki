---
id: "wiki-v3trace-trace-system"
title: "Verilator V3Trace 追踪系统与并行 Dump"
description: "深入分析 Verilator V3Trace/V3TraceDecl 的图依赖分析、activity flags 无锁设计、trace 函数并行分区，以及这些技术对 RTL 仿真器多线程化的启示"
tags: ["verilator", "tracing", "VCD", "multithreading", "activity-flags", "parallel-dump", "graph-analysis", "V3Trace"]
keywords: ["V3Trace", "V3TraceDecl", "trace parallelism", "incremental tracing", "__Vm_traceActivity", "trace_chg", "trace_full", "graph optimization"]
related_sources:
  - "source-verilator-V3Trace"
last_updated: "2026-07-04"
---

# Verilator V3Trace 追踪系统与并行 Dump

> **引用来源**: [`source-verilator-V3Trace.md`](source-verilator-V3Trace.md)

Verilator 的波形追踪（VCD/FST/SAIF）是仿真中最重的 I/O 操作之一。V3Trace 和 V3TraceDecl 两个 pass 共同实现了从信号声明到并行 dump 函数的完整流水线。本章从编译期图分析、运行时状态设计、并行调度三个维度，解析 Verilator 如何将 trace 这一传统串行瓶颈转化为可并行加速的模块。

---

## 1. 架构总览：从声明到并行 Dump

```
Verilator Trace 编译流水线
┌─────────────────────────────────────────────────────────────┐
│  V3TraceDecl.cpp                                            │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────────────┐│
│  │ 遍历 Scope  │ → │ 展开 dtype  │ → │ 生成 trace_init_*   ││
│  │ 收集信号    │   │ (struct/array)│   │ AstTraceDecl 节点   ││
│  └─────────────┘   └─────────────┘   └─────────────────────┘│
│                              ↓                               │
│  V3Trace.cpp                                                │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────────────┐│
│  │ 两阶段图构建 │ → │ 图简化与优化 │ → │ 分配 activity code  ││
│  │ CFunc→Var   │   │ 去重/always  │   │ 生成 __Vm_traceActivity││
│  └─────────────┘   └─────────────┘   └─────────────────────┘│
│                              ↓                               │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────────────┐│
│  │ 生成 const  │   │ 生成 full   │   │ 生成 change (并行)  ││
│  │ 函数        │   │ 函数        │   │ trace_full_N /      ││
│  │             │   │             │   │ trace_chg_N         ││
│  └─────────────┘   └─────────────┘   └─────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

### 1.1 两阶段分离

| 阶段 | 文件 | 输入 | 输出 |
|------|------|------|------|
| 声明生成 | `V3TraceDecl.cpp` | `AstVarScope`, `AstScope` | `AstTraceDecl`, `trace_init_top` / `trace_init_sub__` |
| 函数生成 | `V3Trace.cpp` | `AstTraceDecl` | `trace_full_N`, `trace_chg_N`, `trace_cleanup`, `__Vm_traceActivity` |

这种分离使得 V3TraceDecl 专注于**层级和类型展开**（struct/array/interface），V3Trace 专注于**依赖分析和并行分区**。

---

## 2. 图依赖分析：信号何时变化？

### 2.1 两阶段图构建

V3Trace 在 `visit(AstNetlist*)` 中执行两阶段遍历：

1. **Pass 1 (`m_finding = false`)**: 找到所有 `AstTraceDecl`（被追踪信号），以及读取这些信号的 `VarRef`。建立 `VarRef → TraceDecl` 边。
2. **Pass 2 (`m_finding = true`)**: 找到所有写入 `VarRef` 的 `CFunc`。建立 `CFunc → VarRef` 边。

最终图结构：`ActivityVertex → CFuncVertex → VarVertex → TraceVertex`

### 2.2 图简化：消除中间节点

```cpp
// graphSimplify(true)
// 1. 删除所有 VarVertex，将其入边/出边重新路由
// 2. 删除冗余边
// 3. 删除所有 CFuncVertex，重新路由
// 结果: ActivityVertex → TraceVertex
```

简化后，每个 `TraceActivityVertex` 直接关联到一组 `TraceTraceVertex`。这意味着："当这个代码位置被执行时，这些信号可能变化"。

### 2.3 去重（Duplicate Detection）

通过 `V3DupFinder` 哈希比较，`detectDuplicates()` 找到值完全相同的信号。去重后，多个信号共享同一个 trace code，减少 dump 数据量。

---

## 3. Activity Flags：无锁状态标记

### 3.1 为什么用字节数组？

```cpp
// V3Trace.cpp:440
"Create an array of bytes, not a bit vector, as they can be set 
atomically by mtasks, and are cheaper to set (no need for 
read-modify-write on the C type)"
```

| 方案 | 优点 | 缺点 |
|------|------|------|
| **字节数组**（Verilator） | 单字节写入天然原子，无 RMW | 占用略多（每 flag 8 bit vs 1 bit） |
| bit vector | 紧凑 | 需要 RMW 或原子位操作 |
| `std::atomic<bool>` | 语义清晰 | 可能有内存序开销，编译器可能生成锁 |

在 x86/64 上，对齐的单字节写入是**总线事务级别原子**的。多个 mtask 同时写入 `__Vm_traceActivity[i]` 的不同索引，完全无锁。

### 3.2 两级检测结构

```cpp
// 全局快速路径
cleanupFunc:  vlSymsp->__Vm_activity = false;
changeFunc:   if (!vlSymsp->__Vm_activity) return;

// 局部细粒度控制
changeFunc:   if (!__Vm_traceActivity[code]) continue;
              dump_signal();
```

- **全局 flag `__Vm_activity`**: 如果本轮没有任何信号变化，所有 change dump 函数在入口处直接返回。
- **局部 flags `__Vm_traceActivity[]`**: 按 activity code 分组，只 dump 可能变化的信号。

### 3.3 Slow Path 与 Coroutine 兼容

- **Slow path**: `activitySlow()` 的 vertex 调用 `newActivityAll()`，设置**所有 flags**。因为 slow path 执行频率低，批量设置更简单。
- **Coroutine**: 在 `isCoroutine()` 函数中，activity setter 被 clone 到每个 `CAwait` 之后，确保挂起恢复后仍能正确标记。

---

## 4. Trace 并行分区

### 4.1 并行度控制

```cpp
const uint32_t m_parallelism
    = v3Global.opt.useTraceParallel() 
      ? static_cast<uint32_t>(v3Global.opt.threads()) : 1;
```

- **仅 VCD 支持并行**（注释明确说明）。
- 并行度等于 `--threads` 的值，除非 `--trace-threads` 另有指定。

### 4.2 静态分区算法

```cpp
const uint32_t maxCodes = std::max((nAllCodes + parallelism - 1) / parallelism, 1U);
```

- 将总 trace code 数 `nAllCodes` 均分为 `parallelism` 份。
- 每份生成一对 `trace_full_N` / `trace_chg_N` top-level 函数。
- 这些函数被注册到 trace runtime，运行时由不同线程并行调用。

### 4.3 函数拆分（outputSplitCTrace）

```cpp
const int splitLimit = v3Global.opt.outputSplitCTrace() 
                       ? v3Global.opt.outputSplitCTrace() 
                       : std::numeric_limits<int>::max();
```

- 每个 top 函数内部再按 `nodeCount` 拆分为 `sub` 函数。
- 防止单个函数过大导致编译器优化失效或 I-cache  miss。

---

## 5. 对 RTL 仿真器多线程化的启示

### 5.1 无锁状态标记：字节数组 > bit vector > 原子变量

如果 RTL 仿真器需要多个执行线程标记"事件已发生"：
- **优先使用字节数组**：每个线程写自己的索引，天然无锁。
- 避免共享 bit vector 的 RMW，除非使用 `std::atomic<uint64_t>::fetch_or` 且能接受内存序开销。
- 为每个线程的标记数组加 **64B padding**，消除 false sharing。

### 5.2 编译期静态分区是 trace 并行的最佳实践

Verilator 的 trace 并行不是运行时动态调度，而是**编译期静态分区**。优点：
- 零运行时调度开销。
- 每个线程的函数独立，无需锁。
- 缓存友好：每个线程处理连续的信号范围。

缺点：
- 负载可能不均（某些信号变化频繁，某些从不变化）。
- 未考虑信号宽度（宽向量 vs 单 bit）。

**改进方向**：编译期按**预估数据量**（code × width）而非仅 code 数量分区。

### 5.3 图分析是编译期优化的通用基础设施

V3Trace 的图分析（CFunc → Var → TraceDecl）可以复用为其他优化：
- **Checkpointing**: 确定哪些状态需要保存。
- **Coverage**: 确定哪些 toggles 需要检测。
- **Debug probe**: 确定哪些信号需要在 waveform 中展示。

对于多线程 RTL 仿真器，维护一个**统一的依赖图 IR**，可以在多个 pass 间复用分析结果，避免重复遍历 AST。

### 5.4 两级状态检测是通用模式

```
Global:   "本轮有任何事件吗？"     → O(1) 快速短路
Regional: "哪些区域有事件？"       → O(区域数) 粗筛
Local:    "哪些具体信号变化了？"   → O(信号数) 细筛
```

这种分层检测在事件驱动仿真中同样适用：
- 全局：time wheel 非空？
- 区域：哪些模块的敏感列表被触发？
- 本地：哪些具体信号翻转了？

---

## 6. 相关页面

- [source-verilator-V3Trace.md](source-verilator-V3Trace.md) — 完整源码分析
- [wiki-verilator-deep-dive.md](wiki-verilator-deep-dive.md) — Verilator 多线程整体架构
- [wiki-thread-pool-and-scheduler.md](wiki-thread-pool-and-scheduler.md) — 线程池与调度器
- [wiki-partitioning-implementation.md](wiki-partitioning-implementation.md) — 分区实现

---

> **最后更新**: 2026-07-04
> **分析范围**: V3Trace.cpp, V3Trace.h, V3TraceDecl.cpp, V3TraceDecl.h
> **Verilator SHA**: 8cee034f (V3Trace.cpp), 29c625f9 (V3TraceDecl.cpp)

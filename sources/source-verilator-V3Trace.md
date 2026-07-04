---
title: "V3Trace 追踪系统"
source_url: "https://github.com/verilator/verilator/tree/master/src/V3Trace.cpp"
source_type: "github-code"
author: "Verilator Team"
date: ""
tags: ["verilator", "multithreading", "tracing", "waveform", "VCD", "activity-flags", "parallel-dump", "graph-analysis"]
keywords: ["V3Trace", "V3TraceDecl", "traceAll", "trace parallelism", "activity flags", "incremental tracing", "full tracing", "AstTraceDecl", "AstTraceInc"]
capture_date: "2026-07-04"
---

# V3Trace / V3TraceDecl 追踪系统源码深度分析

## 来源

- **URL**: https://github.com/verilator/verilator/tree/master/src/V3Trace.cpp
- **URL**: https://github.com/verilator/verilator/tree/master/src/V3Trace.h
- **URL**: https://github.com/verilator/verilator/tree/master/src/V3TraceDecl.cpp
- **URL**: https://github.com/verilator/verilator/tree/master/src/V3TraceDecl.h
- **类型**: github-code
- **作者**: Verilator Team
- **日期**: 2026 (文件 SHA: V3Trace.cpp 8cee034f, V3Trace.h 84d395f9, V3TraceDecl.cpp 29c625f9, V3TraceDecl.h 8a6189f0)

## 摘要

Verilator 的波形追踪（VCD/SAIF/FST）是仿真中最耗时的 I/O 操作之一。V3Trace 通过**图分析**确定哪些信号在何时可能变化，并引入**细粒度 activity flags** 避免对未变化信号做无意义的比较和写入。在 VCD 模式下，Verilator 进一步将追踪函数按信号数量**均分到多个线程并行执行**，实现 trace dump 的并行化。整套系统分为两阶段：V3TraceDecl 负责生成 `AstTraceDecl` 节点与层级初始化函数，V3Trace 负责构建依赖图、分配 activity code、生成 const/full/change 三类 dump 函数，并注入并行调度逻辑。

## 关键要点

- **两阶段架构**: V3TraceDecl 创建声明（`trace_init_top` / `trace_init_sub__`），V3Trace 基于声明构建依赖图并生成 dump 函数（`trace_full_0`、`trace_chg_0` 等）。
- **Activity Flags 原子写入**: `__Vm_traceActivity` 被设计为**字节数组**（而非 bit vector），因为字节可以被 mtask 原子设置，无需 read-modify-write，且速度不劣于 bit vector。
- **Trace 并行度**: 仅 VCD 追踪支持并行化，通过 `--trace-threads` / `--threads` 控制，`m_parallelism = threads`。
- **Graph 简化与优化**: 先移除变量节点和 CFunc 节点，消除冗余边，再将小信号的 activity 检测退化为 always-trace，降低 flag 检查开销。
- **函数拆分**: 通过 `outputSplitCTrace` 限制单个函数大小，生成 `_sub` 子函数，避免编译产物过大。
- **Coroutine 兼容**: activity setter 在 coroutine 的每个 `CAwait` 后都插入 clone，确保恢复后正确设置 flag。

---

## 文件结构概览

| 文件 | 职责 | 多线程相关度 |
|------|------|-------------|
| `V3Trace.h` | `V3Trace::traceAll()` 声明，标记 `VL_MT_DISABLED` | 低（接口声明） |
| `V3Trace.cpp` | 核心图分析、activity flag 分配、三类 dump 函数生成、并行分区 | **极高** |
| `V3TraceDecl.h` | `V3TraceDecl::traceDeclAll()` 声明，标记 `VL_MT_DISABLED` | 低 |
| `V3TraceDecl.cpp` | 遍历 scope 生成 `AstTraceDecl`、层级初始化、dtype 展开 | 中（为并行 dump 提供输入） |

---

## 一、类定义与数据结构

### 1.1 `TraceActivityVertex`（V3Trace.cpp:52）

```cpp
class TraceActivityVertex final : public V3GraphVertex {
    AstNode* const m_insertp;  // 插入 setter 的位置
    int32_t m_activityCode;    // 分配的 activity code
    bool m_slow;               // 是否仅由 slow path 触发
public:
    enum { ACTIVITY_NEVER = ((1UL << 31) - 1) };   // 常量信号，永不变化
    enum { ACTIVITY_ALWAYS = ((1UL << 31) - 2) };  // 总是变化，无需检测
    enum { ACTIVITY_SLOW = 0 };                      // 仅 slow path 设置
    // ...
};
```

每个 activity vertex 代表一个**代码位置**（`insertp`），当该位置被执行时，说明某些信号可能发生了变化。`ACTIVITY_ALWAYS` 和 `ACTIVITY_NEVER` 是两种特殊退化状态，用于优化。

### 1.2 `TraceTraceVertex`（V3Trace.cpp:106）

```cpp
class TraceTraceVertex final : public V3GraphVertex {
    AstTraceDecl* const m_nodep;
    TraceTraceVertex* m_duplicatep = nullptr;  // 重复信号指向 canonical
    uint32_t m_dtypeAliasOffset = 0;           // dtype 成员内的 code 偏移
    // ...
};
```

代表一个被追踪的信号。`duplicatep` 用于去重：如果两个信号值完全相同（如 dtype 的多个实例），它们共享同一个 trace code，减少 dump 工作量。

### 1.3 `TraceCFuncVertex` / `TraceVarVertex`（V3Trace.cpp:82, 130）

中间节点：CFunc → Var → TraceDecl。在图简化阶段会被删除，只保留 Activity → Trace 的边。

### 1.4 `TraceVisitor` 核心状态（V3Trace.cpp:150）

```cpp
class TraceVisitor final : public VNVisitor {
    // ...
    V3Graph m_graph;  // 依赖图
    TraceActivityVertex* const m_alwaysVtxp;  // 代表 ACTIVITY_ALWAYS
    
    // 并行度控制
    const uint32_t m_parallelism
        = v3Global.opt.useTraceParallel() 
          ? static_cast<uint32_t>(v3Global.opt.threads()) : 1;
    // ...
};
```

---

## 二、关键函数分析

### 2.1 `traceAll()` — 入口（V3Trace.cpp:721）

```cpp
void V3Trace::traceAll(AstNetlist* nodep) {
    UINFO(2, __FUNCTION__ << ":");
    { TraceVisitor{nodep}; }  // 构造即执行，析构前完成
    V3Global::dumpCheckGlobalTree("trace", 0, dumpTreeEitherLevel() >= 3);
}
```

整个 V3Trace 是一次性的 AST 遍历。`TraceVisitor` 构造时运行所有 pass，析构时输出统计。

### 2.2 `visit(AstNetlist*)` — 两阶段遍历（V3Trace.cpp:659）

```cpp
void visit(AstNetlist* nodep) override {
    // Pass 1: m_finding = false
    //   添加 TraceDecl, CFunc, CCall, VarRef 的顶点
    //   添加 CCall -> CFunc, VarRef -> TraceDecl 的边
    m_finding = false;
    iterateChildren(nodep);

    // Pass 2: m_finding = true
    //   添加 CFunc -> VarRef(被写入) 的边
    m_finding = true;
    iterateChildren(nodep);

    // 生成 trace 函数
    createTraceFunctions();
    nodep->nTraceCodes(m_code);  // 保存总 code 数
}
```

这是经典的**两阶段图构建**：先找到所有信号和读取关系，再找到所有写入关系，从而确定"哪些代码执行可能导致哪些信号变化"。

### 2.3 `createActivityFlags()` — Activity Flag 生成（V3Trace.cpp:430）

```cpp
void createActivityFlags() {
    m_activityNumber = assignactivityNumbers();  // 分配 code

    // 创建字节数组 __Vm_traceActivity
    AstNodeDType* const newScalarDtp = new AstBasicDType{flp, VFlagBitPacked{}, 1};
    AstRange* const newArange
        = new AstRange{flp, VNumRange{static_cast<int>(m_activityNumber) - 1, 0}};
    AstNodeDType* const newArrDtp = new AstUnpackArrayDType{flp, newScalarDtp, newArange};
    AstVar* const newvarp
        = new AstVar{flp, VVarType::MODULETEMP, "__Vm_traceActivity", newArrDtp};
    // ...
    m_activityVscp = newvscp;  // 保存变量引用

    // 插入 setter
    for (const V3GraphVertex& vtx : m_graph.vertices()) {
        if (const TraceActivityVertex* const vtxp = vtx.cast<const TraceActivityVertex>()) {
            AstNode* setterp = nullptr;
            if (vtxp->activitySlow()) {
                setterp = newActivityAll(vtxp->insertp());  // 设置所有 flags
            } else if (!vtxp->activityAlways()) {
                setterp = newActivitySetter(vtxp->insertp(), vtxp->activityCode());
            }
            // 插入到 insertp 之后（或 coroutine 的每个 await 之后）
            // ...
        }
    }
}
```

**关键设计**：`__Vm_traceActivity` 是**字节数组**（`AstBasicDType` 宽 1 bit，但包装成 `UnpackArrayDType`）。注释明确说明：

> "Create an array of bytes, not a bit vector, as they can be set atomically by mtasks, and are cheaper to set (no need for read-modify-write on the C type), and the speed of the tracing code is the same on largish designs."

这意味着在多线程仿真（mtasks）中，多个线程可以**无锁地原子写入**各自的 activity byte，无需同步原语。这是 trace 并行化的**核心前提**。

### 2.4 `newActivitySetter()` / `newActivityAll()`（V3Trace.cpp:418, 423）

```cpp
AstNode* newActivitySetter(AstNode* insertp, uint32_t code) {
    ++m_statSetters;
    FileLine* const fl = insertp->fileline();
    AstAssign* const setterp = new AstAssign{fl, 
        selectActivity(fl, code, VAccess::WRITE),
        new AstConst{fl, AstConst::BitTrue{}}};
    return setterp;
}

AstNode* newActivityAll(AstNode* insertp) {
    ++m_statSettersSlow;
    if (!m_actAllFuncp) {
        // 生成 __Vm_traceActivitySetAll 函数，循环设置所有 flags
        // ...
    }
    AstCCall* const callp = new AstCCall{insertp->fileline(), m_actAllFuncp};
    return callp->makeStmt();
}
```

`newActivitySetter` 生成 `__Vm_traceActivity[code] = 1;` 的单条赋值。`newActivityAll` 在 slow path 中调用一个函数批量设置所有 flags。

### 2.5 `createNonConstTraceFunctions()` — 并行 dump 函数生成（V3Trace.cpp:540）

```cpp
void createNonConstTraceFunctions(const TraceVec& traces, uint32_t nAllCodes,
                                  uint32_t parallelism) {
    // ...
    uint32_t topFuncNum = std::numeric_limits<uint32_t>::max();
    TraceVec::const_iterator it = traces.begin();
    while (it != traces.end()) {
        AstCFunc* topFulFuncp = nullptr;
        AstCFunc* topChgFuncp = nullptr;
        const uint32_t maxCodes = std::max((nAllCodes + parallelism - 1) / parallelism, 1U);
        uint32_t nCodes = 0;
        // ...
        for (; nCodes < maxCodes && it != traces.end(); ++it) {
            // ...
            if (!topFulFuncp) {
                ++topFuncNum;
                topFulFuncp = newCFunc(VTraceType::FULL, nullptr, topFuncNum);
                topChgFuncp = newCFunc(VTraceType::CHANGE, nullptr, topFuncNum);
            }
            // 生成 sub function，插入 TraceInc 节点
            // ...
            nCodes += declp->codeInc();
        }
    }
}
```

**这是 trace 并行化的核心算法**。`maxCodes = (nAllCodes + parallelism - 1) / parallelism` 将总信号数均分为 `parallelism` 份，每份对应一个 top-level `trace_full_N` / `trace_chg_N` 函数。这些函数会被注册到 trace runtime，由不同线程并行调用。

每个 top 函数内部再拆分为 `sub` 函数（受 `outputSplitCTrace` 控制大小），确保编译产物不会过大。

### 2.6 `newCFunc()` — 函数创建模板（V3Trace.cpp:351）

```cpp
AstCFunc* newCFunc(VTraceType traceType, AstCFunc* topFuncp, uint32_t funcNum,
                   uint32_t baseCode = 0, ...) {
    // ...
    if (traceType == VTraceType::CHANGE) {
        funcp->addStmtsp(
            new AstCStmt{flp, "if (VL_UNLIKELY(!vlSymsp->__Vm_activity)) return;"});
    }
    // ...
}
```

`CHANGE` 类型的 top 函数开头有全局短路检查：`if (!vlSymsp->__Vm_activity) return;`。如果没有任何 activity flag 被设置，整个 change dump 直接跳过。这是一个**全局快速路径**优化，在单线程和多线程场景都有效。

### 2.7 `createCleanupFunction()` — 清理（V3Trace.cpp:608）

```cpp
void createCleanupFunction() {
    AstCFunc* const cleanupFuncp = new AstCFunc{fl, "trace_cleanup", ...};
    // 清除全局 activity flag
    cleanupFuncp->addStmtsp(
        new AstCStmt{..., "vlSymsp->__Vm_activity = false;"s});
    // 清除细粒度 flags
    for (uint32_t i = 0; i < m_activityNumber; ++i) {
        AstNode* const clrp = new AstAssign{fl, 
            selectActivity(fl, i, VAccess::WRITE),
            new AstConst{fl, AstConst::BitFalse{}}};
        cleanupFuncp->addStmtsp(clrp);
    }
}
```

每次 time step 结束后，cleanup 函数被调用，清零所有 activity flags，为下一轮做准备。`__Vm_activity` 和 `__Vm_traceActivity[]` 是**每轮复用的状态**。

### 2.8 `graphOptimize()` — 图优化（V3Trace.cpp:319）

```cpp
void graphOptimize() {
    assignactivityNumbers();
    sortTraces(traces, unused1);

    // 对于 activity set 很小但信号很多的 group，退化为 always trace
    auto it = traces.begin();
    while (it != end) {
        // ...
        if (complexity <= actSet.size() * 2) {
            for (; head != it; ++head) {
                new V3GraphEdge{&m_graph, m_alwaysVtxp, head->second, 1};
            }
        }
    }
    graphSimplify(false);
}
```

如果检查 activity flags 的代价（`actSet.size()` 次读取）高于直接比较信号值（`complexity` 次比较），则将该 group 的信号标记为 `ACTIVITY_ALWAYS`，跳过 flag 检测。这是**运行时开销 vs 检测开销**的启发式权衡。

---

## 三、多线程相关实现细节

### 3.1 原子性 Activity Flags（无锁设计）

```cpp
// V3Trace.cpp:440
"Create an array of bytes, not a bit vector, as they can be set atomically by mtasks"
```

- 在 x86/64 上，单字节写入是**天然原子的**（不需要 `std::atomic`）。
- 多个 mtask 同时写入 `__Vm_traceActivity[i]` 的不同索引，**无竞争**。
- 即使两个 mtask 写入同一个索引（因为两个 activity 被合并），字节写入仍然是安全的，只是可能多触发一次 trace（不会丢失）。

### 3.2 并行分区算法

```cpp
// V3Trace.cpp:552
const uint32_t maxCodes = std::max((nAllCodes + parallelism - 1) / parallelism, 1U);
```

- **静态分区**：在编译期按 trace code 数量均分，不是动态负载均衡。
- 每个分区是一个独立的 `trace_full_N` / `trace_chg_N` 函数，可以并行执行。
- 分区只考虑**信号数量**（`codeInc`），未考虑**信号宽度**或**数组长度**。注释提到：
  > "We will split functions such that each have to dump roughly the same amount of data"

  但实现上是按 code 数量而非数据量均分，这是一种近似。

### 3.3 Coroutine 兼容

```cpp
// V3Trace.cpp:458
if (funcp->isCoroutine() && funcp->stmtsp()) {
    funcp->stmtsp()->foreachAndNext([setterp](AstCAwait* awaitp) {
        awaitp->addNextHere(setterp->cloneTree(false));
    });
    funcp->addStmtsp(setterp);
}
```

对于 coroutine（Verilator 的 `--timing` 模式），activity setter 不仅插入函数开头，还在每个 `CAwait` 之后插入 clone。这是因为 coroutine 可能在 await 点被挂起和恢复，恢复后的执行也需要设置 flag。这保证了 timing-aware 仿真的正确性。

### 3.4 `VL_MT_DISABLED` 标记

```cpp
// V3Trace.h:24
static void traceAll(AstNetlist* nodep) VL_MT_DISABLED;

// V3Trace.cpp:18
#include "V3PchAstNoMT.h"  // VL_MT_DISABLED_CODE_UNIT
```

V3Trace 和 V3TraceDecl 的**编译期代码单元**被标记为 `VL_MT_DISABLED_CODE_UNIT`，这意味着这些 pass 本身在编译 Verilator 时不参与多线程编译。但注意：它们**生成的代码**（`trace_chg_0` 等）是支持运行时多线程的。

### 3.5 V3TraceDecl 的 dtype 函数复用（V3TraceDecl.cpp:182）

```cpp
struct DtypeFuncKey final {
    const AstNodeDType* dtypep;
    VVarType varType;
    bool operator==(const DtypeFuncKey& other) const { ... }
};
std::unordered_map<DtypeFuncKey, AstCFunc*, DtypeFuncKeyHash> m_dtypeFuncs;
```

V3TraceDecl 为每种数据类型生成一次初始化函数，通过 hash 复用。这在多线程 trace 中减少了代码体积，间接降低了 I-cache 压力。

---

## 四、对 RTL 仿真器多线程化的启示

### 启示 1：用字节数组替代 bit vector 做线程状态标记

Verilator 选择字节数组的核心原因是**原子写入 + 无 read-modify-write**。在自行设计的 RTL 仿真器中：
- 如果需要多个线程标记"某区域发生了事件"，使用**每线程独立的 byte/bool 数组**是最简单的无锁方案。
- 避免 bit vector 的 RMW，除非使用 `std::atomic<uint64_t>` 的 fetch_or。
- 如果必须共享紧凑状态，考虑为每个线程分配独立的 cache line（padding 到 64B），避免 false sharing。

### 启示 2：静态分区 vs 动态负载均衡

Verilator 的 trace 并行是**编译期静态分区**：按 signal code 均分。优点是：
- 无运行时调度开销。
- 每个线程的函数独立，无锁。

缺点：
- 如果信号变化频率不均，可能导致负载倾斜。
- 未考虑信号宽度（宽向量 vs 单 bit）。

对于 RTL 仿真器：
- **编译期分区**适合事件密度相对均匀的场景（如 gate-level 仿真）。
- **动态任务队列**适合变化高度不均匀的场景（如只追踪少数顶层端口），但会引入锁或原子操作开销。

### 启示 3：Activity Flag 的两级检测

```
全局: __Vm_activity  (1 byte)   -> 快速短路
局部: __Vm_traceActivity[i] (N bytes) -> 细粒度控制
```

这种**两级检测**结构是高效追踪的关键：
- 如果全局 flag 为 false，所有 change dump 直接跳过（O(1)）。
- 如果全局为 true，再检查每个 group 的局部 flag。

对于 RTL 仿真器，可借鉴：
- 第一级："本 time step 是否有任何事件"。
- 第二级："哪些模块/区域有事件"。
- 第三级："具体哪些信号需要比较"。

### 启示 4：Graph-based 依赖分析是编译期优化的利器

V3Trace 通过构建 CFunc → Var → TraceDecl 的依赖图，在编译期确定"哪些信号何时可能变化"。这比运行时动态检测（如每周期比较所有信号）高效得多。对于多线程 RTL 仿真器：
- 在编译期分析模块间数据流，可以预分配**每模块的 activity flag**。
- 图分析还可以用于确定**哪些模块可以并行执行**（V3Partition 的 mtask 划分）。
- 将"依赖图"作为贯穿编译期的中间表示（IR），可以统一优化 scheduling、tracing、和 checkpointing。

### 启示 5：Coroutine 的细粒度状态标记

Verilator 在 coroutine 的每个 await 点后插入 activity setter clone，说明：
- 当线程模型包含挂起/恢复语义时，状态标记需要**跟随执行点**而非函数边界。
- 如果 RTL 仿真器支持 dynamic scheduling 或 fiber-based 模型，activity 标记必须插入到**所有可能的 yield/await 恢复点**。

---

## 原文摘录

> "Create an array of bytes, not a bit vector, as they can be set atomically by mtasks, and are cheaper to set (no need for read-modify-write on the C type), and the speed of the tracing code is the same on largish designs."
> — V3Trace.cpp:440

> "Trace parallelism. Only VCD tracing can be parallelized at this time."
> — V3Trace.cpp:167

> "We will split functions such that each have to dump roughly the same amount of data for this we need to keep tack of the number of codes used by the trace functions."
> — V3Trace.cpp:476

> "Automatics (typically, excluding forks) have no persistance over time, and may optimize differently when multithreadeded or hierarchical."
> — V3TraceDecl.cpp:290

---

## 相关链接

- [Verilator 官方文档](https://verilator.org/guide/latest/)
- [V3Trace.cpp 源码](https://github.com/verilator/verilator/blob/master/src/V3Trace.cpp)
- [V3TraceDecl.cpp 源码](https://github.com/verilator/verilator/blob/master/src/V3TraceDecl.cpp)
- [Verilator 多线程设计论文](https://verilator.org/papers/Verilator_WOS10.pdf)
- [V3Partition 分析](source-verilator-V3Partition.md)（假设存在）

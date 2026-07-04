---
title: "Verilator V3Gate 门级优化源码分析"
description: "Verilator V3Gate.cpp / V3Gate.h 源码深度分析，聚焦其编译时门级优化管线的图结构、串行执行策略，以及显式禁用多线程的设计决策对 RTL 仿真器多线程化的启示。"
source_url: "https://github.com/verilator/verilator/tree/master/src/V3Gate.cpp"
source_type: "github-code"
author: "Wilson Snyder / Verilator Team"
date: "2026-07-04"
tags: ["verilator", "multithreading", "gate-optimization", "V3Graph", "compile-time", "VL_MT_DISABLED", "AST-transform"]
keywords: ["V3Gate", "gateAll", "GateInline", "GateDedupe", "GateUnused", "GateGraph", "VL_MT_DISABLED_CODE_UNIT"]
capture_date: "2026-07-04"
---

# Verilator V3Gate 门级优化源码分析

## 来源

- URL: https://github.com/verilator/verilator/tree/master/src/V3Gate.cpp
- 类型: github-code
- 作者: Wilson Snyder / Verilator Team
- 日期: 2026-07-04 (源码分析基于最新 master)

## 摘要

`V3Gate` 是 Verilator 编译管线中负责**门级优化（gate-level optimization）**的核心 pass，主要包括变量内联（wire elimination）、常量传播、冗余逻辑消除、赋值合并与死逻辑清理。整个优化管线基于 `V3Graph` 构建一张**变量-逻辑依赖图**（Variable-Logic Dependency Graph），然后在这张图上执行一系列顺序遍历的图变换。值得注意的是，`V3Gate` 被显式标记为 `VL_MT_DISABLED`（多线程禁用），且其编译单元通过 `V3PchAstNoMT.h` 注入了 `VL_MT_DISABLED_CODE_UNIT` 属性。这意味着整个 pass 在**单线程、无锁、无原子操作**的假设下运行，所有图遍历和 AST 修改都是**顺序且不可重入**的。本文档分析其数据结构、关键算法、串行执行策略，并探讨这种设计对 RTL 仿真器多线程化的深层含义。

## 关键数据结构

### 1. 图顶点层级：`GateEitherVertex` → `GateVarVertex` / `GateLogicVertex`

`V3Gate.cpp` 第 38–112 行定义了图顶点的三层继承结构：

```cpp
// V3Gate.cpp:38
class GateEitherVertex VL_NOT_FINAL : public V3GraphVertex {
    VL_RTTI_IMPL(GateEitherVertex, V3GraphVertex)
    bool m_reducible = true;   // 可被消除
    bool m_dedupable = true;   // 可被去重
    bool m_consumed = false;   // 输出被有效使用
    bool m_staticInit = false; // 静态初始化节点
    // ...
};

// V3Gate.cpp:55
class GateVarVertex final : public GateEitherVertex {
    VL_RTTI_IMPL(GateVarVertex, GateEitherVertex)
    AstVarScope* const m_varScp;  // 指向 AST 变量作用域
    bool m_isTop = false;
    bool m_isClock = false;
    AstNode* m_rstSyncNodep = nullptr;
    AstNode* m_rstAsyncNodep = nullptr;
    // ...
};

// V3Gate.cpp:85
class GateLogicVertex final : public GateEitherVertex {
    VL_RTTI_IMPL(GateLogicVertex, GateEitherVertex)
    AstNode* const m_nodep;      // 指向 AST 逻辑节点
    AstActive* const m_activep;  // 所属 active block（时钟域）
    const bool m_slow;         // 是否属于 slow 代码块（Initial/Final）
    // ...
};
```

| 顶点类型 | 语义 | 多线程相关标注 |
|---------|------|--------------|
| `GateEitherVertex` | 抽象基类，承载 `reducible`/`dedupable`/`consumed` 状态 | 无 |
| `GateVarVertex` | 变量节点，代表 `AstVarScope` | `varScp()` 和 `name()` 标注 `VL_MT_STABLE` |
| `GateLogicVertex` | 逻辑节点，代表 always/assign/cfunc 等 | 无 MT 标注，但 `nodep()` 返回的 AST 在优化期间由单线程独占 |

**`VL_MT_STABLE`** 是 Verilator 内部线程安全注解，表示该对象在创建后不再被修改，因此可被多线程**并发读取**。但注意：整个 `V3Gate` pass 本身是 `VL_MT_DISABLED` 的，所以这里的 `VL_MT_STABLE` 更多是**对未来多线程读场景的准备**，而非当前 pass 的并发保证。

### 2. 图边：`GateEdge` 与 `V3GraphEdge`

```cpp
// V3Gate.cpp:105
class GateEdge final : public V3GraphEdge {
    std::string dotLabel() const override { return std::to_string(weight()); }
public:
    GateEdge(V3Graph* graphp, V3GraphVertex* fromp, V3GraphVertex* top, int weight)
        : V3GraphEdge{graphp, fromp, top, weight} {}
};
```

边使用 `weight` 记录依赖强度（同一逻辑块对同一变量的多次引用会累加权重）。`V3GraphEdge` 是 Verilator 的通用图边实现，**无锁、非线程安全**。

### 3. 图容器：`GateGraph`

```cpp
// V3Gate.cpp:112
class GateGraph final : public V3Graph {
    // AstVarScope::user1p → GateVarVertex* 映射缓存
    const VNUser1InUse m_inuser1;
public:
    GateVarVertex* makeVarVertex(AstVarScope* vscp) {
        // 使用 user1p 作为缓存，避免重复创建顶点
        GateVarVertex* vVtxp = reinterpret_cast<GateVarVertex*>(vscp->user1p());
        if (!vVtxp) { /* 创建并缓存 */ }
        return vVtxp;
    }
    void addEdge(GateVarVertex* srcp, GateLogicVertex* dstp, int weight);
    void addEdge(GateLogicVertex* srcp, GateVarVertex* dstp, int weight);
};
```

`VNUser1InUse` 是 Verilator 的 **AST 节点用户数据槽位管理器**。它在构造时占用 `AstVarScope::user1p` 这个全局槽位，在析构时释放。由于 `V3Gate` 是单线程执行的，这种**全局槽位复用**不会与任何其他 pass 冲突。

## 关键函数与算法

### 1. 入口函数：`V3Gate::gateAll`

```cpp
// V3Gate.h:19
class V3Gate final {
public:
    static void gateAll(AstNetlist* nodep) VL_MT_DISABLED;
};

// V3Gate.cpp:571
void V3Gate::gateAll(AstNetlist* netlistp) {
    UINFO(2, __FUNCTION__ << ":");
    {
        // 1. 构建依赖图
        std::unique_ptr<GateGraph> graphp = GateBuildVisitor::apply(netlistp);
        // 2. SYNCASYNC 警告
        v3GateWarnSyncAsync(*graphp);
        // 3. 合并冗余边
        graphp->removeRedundantEdgesSum(&V3GraphEdge::followAlwaysTrue);
        // 4. 移除无用逻辑
        GateUnused::apply(*graphp);
        // 5. 变量内联（两轮：先简单后复杂）
        GateInline::apply(*graphp);
        // 6. 逻辑去重（可选，由 --f-dedupe 控制）
        if (v3Global.opt.fDedupe()) GateDedupe::apply(*graphp);
        // 7. 赋值合并（可选，由 --f-assemble 控制）
        if (v3Global.opt.fAssemble()) GateMergeAssignments::apply(*graphp);
        // 8. 再次移除无用逻辑
        GateUnused::apply(*graphp);
    }
    V3Global::dumpCheckGlobalTree("gate", 0, dumpTreeEitherLevel() >= 3);
}
```

**关键观察**：`gateAll` 的执行流是**严格的顺序管线**（sequential pipeline）。每个步骤修改 `GateGraph` 和底层 AST 的状态，后一步依赖前一步的结果。没有任何步骤可以并行化，因为它们都操作**同一个可变图和同一棵 AST**。

### 2. 图构建：`GateBuildVisitor`

```cpp
// V3Gate.cpp:140
class GateBuildVisitor final : public VNVisitorConst {
    GateGraph* m_graphp = new GateGraph{};
    GateLogicVertex* m_logicVertexp = nullptr; // 当前正在追踪的逻辑节点
    const AstNodeModule* m_modp = nullptr;
    const AstScope* m_scopep = nullptr;
    AstActive* m_activep = nullptr;
    bool m_inClockedActive = false;
    bool m_inStaticActive = false;
    bool m_inSenItem = false;
    // ...
};
```

`GateBuildVisitor` 继承自 `VNVisitorConst`，即**常量访问者**——它遍历 AST 但不修改节点本身（只创建图顶点和边）。遍历顺序是深度优先的，且由于 AST 在此阶段不被修改，遍历是**确定性的**。

变量引用处理（`V3Gate.cpp:203`）：
```cpp
void visit(AstNodeVarRef* nodep) override {
    if (!m_logicVertexp) return;
    AstVarScope* const vscp = nodep->varScopep();
    GateVarVertex* const vVtxp = m_graphp->makeVarVertex(vscp);
    // 写依赖：逻辑 → 变量
    if (nodep->access().isWriteOrRW()) m_graphp->addEdge(m_logicVertexp, vVtxp, 1);
    // 读依赖：变量 → 逻辑
    if (nodep->access().isReadOrRW()) m_graphp->addEdge(vVtxp, m_logicVertexp, 1);
}
```

这建立了一张**有向二分图**：变量节点 ↔ 逻辑节点。边的方向表示**数据流向**（变量读入逻辑，逻辑写入变量）。

### 3. 变量内联：`GateInline::optimizeSignals`

`GateInline`（`V3Gate.cpp:285`）是 V3Gate 中最复杂的变换，核心思想是：**如果某个变量只有一个驱动源，且驱动逻辑足够简单，那么将驱动表达式直接替换到所有消费点，然后删除该变量及其驱动逻辑。**

```cpp
// V3Gate.cpp:370
void optimizeSignals(bool allowMultiIn) {
    auto& vertices = m_graph.vertices();
    // 顺序遍历所有变量顶点
    V3GraphVertex::List::iterator vIt = ffToVarVtx(vertices.begin());
    while (vIt != vertices.end()) {
        GateVarVertex* const vVtxp = (*vIt).as<GateVarVertex>();
        vIt = ffToVarVtx(++vIt); // 先取下一个，因为当前可能被删除

        if (!vVtxp->inSize1()) continue;      // 必须有且只有一个驱动
        if (!vVtxp->reducible()) continue;    // 必须可消除
        // ... 检查驱动逻辑是否简单 ...
        // ... 将表达式替换到每个消费逻辑 ...
        // ... 更新图边，删除变量顶点和驱动逻辑顶点 ...
    }
}
```

**关键顺序依赖**：
1. 迭代器 `vIt` 在可能删除当前顶点之前**预取下一个顶点**，这是典型的**顺序遍历中安全删除**模式。
2. `commitSubstitutions` 必须在 `optimizeSignals` 之前或之中被调用，因为一旦一个变量被内联，其消费逻辑的 AST 被修改，后续的图遍历需要看到**最新的依赖关系**。
3. `optimizeSignals` 被调用两次：第一次 `allowMultiIn=false`（只内联常量和简单变量引用），第二次 `allowMultiIn=true`（允许更复杂的表达式）。这种**分阶段策略**确保先消除"廉价"变量，再处理更复杂的内联，避免过早膨胀消费逻辑的表达式树。

### 4. 冗余逻辑消除：`GateDedupe`

```cpp
// V3Gate.cpp:482
class GateDedupe final {
    const VNUser2InUse m_inuser2;  // 占用 AstVarScope::user2 作为访问标记
    uint32_t m_depth = 0;          // 递归深度限制（GATE_DEDUP_MAX_DEPTH = 20）
    // ...
};
```

`GateDedupe` 通过比较不同逻辑块的**右值表达式（RHS）**，如果两个赋值产生功能等价的输出，则合并它们：将所有消费者重定向到其中一个变量，然后删除另一个。

它使用 `V3DupFinder`（哈希去重查找器）来加速等价检测。注意这里的 `user2` 被用作**访问标记**防止循环遍历，这是典型的 DFS 图遍历技巧。

### 5. 无用逻辑清理：`GateUnused`

```cpp
// V3Gate.cpp:549
class GateUnused final {
    void markRecurse(GateEitherVertex* vtxp) {
        if (vtxp->user()) return; // 已标记，跳过
        vtxp->user(true);
        vtxp->setConsumed("propagated");
        for (V3GraphEdge& edge : vtxp->inEdges()) {
            markRecurse(static_cast<GateEitherVertex*>(edge.fromp()));
        }
    }
};
```

从所有**已消费（consumed）**的顶点出发，反向遍历依赖图，标记所有可达顶点。未标记的顶点即**死逻辑**，被删除。这是经典的**反向可达性分析（backward reachability）**。

## 多线程相关实现细节

### 1. 显式禁用多线程

```cpp
// V3Gate.cpp:18
#include "V3PchAstNoMT.h"  // VL_MT_DISABLED_CODE_UNIT

// V3Gate.h:19
static void gateAll(AstNetlist* nodep) VL_MT_DISABLED;
```

`V3PchAstNoMT.h` 是 Verilator 的**预编译头文件变体**，专门为**不需要线程安全**的编译单元设计。它通常：
- 不包含 `V3Mutex` 等线程同步原语
- 将 `VL_MT_SAFE` 和 `VL_MT_STABLE` 宏定义为空或仅文档标记
- 禁用 `VL_MT_SAFE` 相关的断言检查

`VL_MT_DISABLED` 在函数声明上表示：**该函数不应在多线程上下文中调用**。如果在编译时启用了线程安全检查，调用者会被静态分析工具标记为违规。

### 2. 无锁、无原子的数据结构

整个 `V3Gate` 使用的所有数据结构都是**无锁**的：
- `std::unordered_map` / `std::unordered_set` / `std::vector` —— 标准库容器，无并发保护
- `V3Graph` / `V3GraphEdge` / `V3GraphVertex` —— Verilator 内部图结构，无原子引用计数
- `AstUser2Allocator` / `VNUser1InUse` / `VNUser2InUse` —— AST 用户数据槽位，全局分配，无线程隔离

### 3. AST 节点状态的全局复用

```cpp
// V3Gate.cpp:112  (GateGraph)
const VNUser1InUse m_inuser1;  // AstVarScope::user1p → GateVarVertex*

// V3Gate.cpp:285  (GateInline)
const VNUser2InUse m_inuser2;  // AstNode::user2 → Substitutions map

// V3Gate.cpp:482  (GateDedupe)
const VNUser2InUse m_inuser2;  // AstVarScope::user2 → bool visited
```

`VNUser1InUse` / `VNUser2InUse` 是 Verilator 的 **RAII 风格的 AST 用户数据槽位锁**。它们在构造时占用一个全局槽位（如 `user1p`），在析构时清零。由于 `V3Gate` 的所有子 pass 都是**顺序执行**的，它们不会同时存在，因此不会冲突。但如果试图并行化这些 pass，就必须将用户数据槽位改为**线程局部存储**或**显式的外部映射表**。

### 4. `VL_MT_STABLE` 的准备性标注

```cpp
// V3Gate.cpp:65
AstVarScope* varScp() const VL_MT_STABLE { return m_varScp; }

// V3Gate.cpp:77
std::string name() const override VL_MT_STABLE { return varScp()->name(); }
```

`VL_MT_STABLE` 告诉 Verilator 的静态分析器：该对象在构造后不会被修改，因此**读取是线程安全的**。这是 Verilator 向多线程编译过渡的**渐进式标记策略**——即使当前 pass 是单线程的，也为未来可能的多线程读场景（如多线程 `dumpTree` 或多线程 codegen）预留安全信息。

## 对 RTL 仿真器多线程化的启示

### 1. 编译时优化与运行时多线程的分界

`V3Gate` 的设计体现了 Verilator 的清晰架构分层：

```
RTL AST → [V3Gate: 单线程编译时优化] → 简化 AST → [V3Partition: 多线程分区] → MTask 图 → 多线程仿真代码
```

**门级优化必须在单线程中完成**，因为它涉及大量**跨节点的全局变换**（如变量内联会改变多个逻辑块的 AST，并需要立即更新图结构）。如果在多线程中执行，需要：
- 为每个线程维护独立的 AST 副本（内存开销巨大）
- 或使用细粒度锁保护每个 AST 节点和图边（同步开销巨大，且极易死锁）
- 或采用事务内存（Transactional Memory）回滚冲突（实现复杂，在 C++ 中无成熟支持）

Verilator 选择了**最务实的策略**：让编译时优化保持单线程，但确保优化后的输出（更简洁的 AST、更少的变量、更清晰的依赖关系）**有利于后续的多线程分区**。

### 2. 简化后的 AST 更利于分区

`V3Gate` 消除的每条冗余变量、每个死逻辑块、每个重复赋值，都会**减少后续多线程分区的节点数和边数**：
- **节点减少** → 分区搜索空间更小，启发式算法（如 Parendi 的 TSP 近似）更容易找到均衡解。
- **边减少** → 跨线程通信的割边（cut edges）更少，运行时同步开销更低。
- **常量折叠** → 如果某信号在编译期被消为常量，其下游所有依赖不再需要在多线程间传递，直接消除跨线程数据依赖。

### 3. `user1p`/`user2` 模式是编译时优化的常见设计

Verilator 在 AST 节点上预留的 `user1p`/`user2` 等槽位是**编译器 pass 中常见的设计模式**：利用 AST 节点本身存储临时状态，避免额外哈希表。但这种模式**天然与多线程冲突**：
- 如果多个线程同时写同一个节点的 `user2`，需要原子操作或锁。
- 如果线程 A 的 pass 用 `user1p` 存图顶点指针，线程 B 的 pass 用 `user1p` 存其他信息，会互相覆盖。

**多线程编译器的替代方案**：
- **External Dense Map**：使用 `std::unordered_map<AstNode*, T>` 或 `llvm::DenseMap` 存储 pass 状态，每个 pass 有自己的映射表。
- **Thread-Local Allocator**：为每个线程分配独立的 AST 副本或 AST 快照。
- **Versioned AST**：每个节点带版本号，多线程读取时检测版本冲突。

### 4. 顺序管线的可扩展性瓶颈

`V3Gate::gateAll` 中的 8 个步骤是**严格顺序**的。如果 Verilator 未来希望在编译阶段使用多线程加速，可考虑以下策略：

| 策略 | 适用场景 | 复杂度 |
|------|---------|--------|
| **模块级并行** | 不同 `AstNodeModule` 的图构建和优化独立执行 | 中。需要解决跨模块接口变量的合并问题。 |
| **Scope 级并行** | 同一模块内不同 `AstScope` 的局部优化可并行 | 高。需要处理 Scope 间的变量共享和信号穿透。 |
| **Pipeline 阶段拆分** | 将 `V3Gate` 拆分为更细粒度的 IR 阶段，每阶段输出不可变 IR，多线程消费 | 高。需要重构 Verilator 的 AST 为函数式 IR（类似 MLIR）。 |
| **保持现状** | 编译时优化不是瓶颈，运行时仿真才是 | 低。这是 Verilator 目前的实际策略。 |

### 5. 对 `[[黑胶唱片]]` 项目的启示

在 Ren'Py 视觉小说的元叙事设计中，Verilator 的 `V3Gate` 可以作为一个**隐喻原型**：

- **单线程的编译时优化**如同主角在深夜独自梳理代码中的冗余逻辑——这是他唯一能控制的部分，是“孤独的内省时刻”。
- **消除冗余变量**就像主角试图消除生活中不必要的社交表演，将“真实的自己”直接暴露给世界。
- **不可并行化的全局依赖**映射到小镇做题家的焦虑：你无法将“自我重构”外包给他人，因为每个变量都与其他变量纠缠。

在代码层面，如果未来 Ren'Py 引擎需要支持多线程场景（如多线程资源加载或后端仿真），可以参考 Verilator 的分层策略：**在单线程阶段完成所有会破坏全局状态的重构，然后输出一个干净、不可变的中间表示，供多线程阶段消费。**

## 原文摘录

> `// V3Gate.cpp:18`
> `#include "V3PchAstNoMT.h"  // VL_MT_DISABLED_CODE_UNIT`
> — 整个编译单元被标记为禁用多线程。

> `// V3Gate.h:19`
> `static void gateAll(AstNetlist* nodep) VL_MT_DISABLED;`
> — 入口函数显式声明不可在多线程环境中调用。

> `// V3Gate.cpp:65`
> `AstVarScope* varScp() const VL_MT_STABLE { return m_varScp; }`
> — 对变量的只读访问标注为 `VL_MT_STABLE`，为未来的并发读取做准备。

> `// V3Gate.cpp:374-379`
> ```cpp
> V3GraphVertex::List::iterator vIt = ffToVarVtx(vertices.begin());
> while (vIt != vertices.end()) {
>     GateVarVertex* const vVtxp = (*vIt).as<GateVarVertex>();
>     vIt = ffToVarVtx(++vIt); // 先取下一个，因为当前可能被删除
> ```
> — 顺序遍历中安全删除的经典模式。

> `// V3Gate.cpp:285-288`
> ```cpp
> class GateInline final {
>     using Substitutions = std::unordered_map<AstVarScope*, AstNodeExpr*>;
>     const VNUser2InUse m_inuser2;
>     AstUser2Allocator<AstNode, Substitutions> m_substitutions;
> ```
> — AST 用户数据槽位被用作状态存储，这是单线程编译器的典型模式，但在多线程环境中需要替换。

## 相关链接

- [Verilator V3Gate.cpp 源码 (GitHub)](https://github.com/verilator/verilator/blob/master/src/V3Gate.cpp)
- [Verilator V3Gate.h 源码 (GitHub)](https://github.com/verilator/verilator/blob/master/src/V3Gate.h)
- [Verilator 多线程文档](https://verilator.org/guide/latest/verilating.html#multithreading)
- [V3Graph 源码分析（同系列）](source-verilator-v3graph.md) —— 待创建
- [Parendi ASIC 2025 论文分析](source-parendi-asplos25.md) —— Verilator 多线程分区的前沿工作
- [Verilator Issue #2913：多线程编译时优化讨论](source-verilator-issue-2913.md)

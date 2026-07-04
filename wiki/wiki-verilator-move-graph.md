---
title: "Verilator MoveGraph 与多线程调度"
description: "Verilator V3OrderMoveGraph 模块的深度分析：从细粒度 OrderGraph 到粗粒度 MoveGraph 的转换、时钟域互斥检测、DomScope 分组策略，及其对 RTL 多线程仿真器设计的启示"
date: "2026-07-04"
tags: ["verilator", "multithreading", "ordering", "move-graph", "domain-analysis", "serialization", "dependency-graph", "DomScope"]
keywords: ["OrderMoveGraph", "OrderMoveVertex", "OrderMoveDomScope", "OrderMoveGraphSerializer", "domainsExclusive", "V3OrderProcessDomains", "V3OrderSerial", "RTL", "parallel-simulation"]
---

# Verilator MoveGraph 与多线程调度

## 1. 概述

`V3OrderMoveGraph` 是 Verilator 编译流水线中**从细粒度依赖图到粗粒度调度图的关键转换层**。它位于前端 AST 依赖分析（`V3OrderProcessDomains`）与后端代码生成（`V3OrderSerial` / `V3OrderParallel`）之间，负责将庞大的二分 `OrderGraph`（LogicVertex ↔ VarVertex）压缩为更紧凑的 `MoveGraph`，并通过**时钟域互斥检测**和**(Domain, Scope) 分组**为后续的串行/并行代码生成提供最小化的调度图。

虽然 `OrderMoveGraph` 的构建过程标记为 `VL_MT_DISABLED`（编译期单线程），但它生成的图结构直接决定了多线程仿真运行时的**任务粒度、调度顺序和并行度上限**。理解这一层的设计，是理解 Verilator 多线程调度策略的核心。

---

## 2. 核心概念

### 2.1 OrderGraph → MoveGraph 的粗化

`OrderGraph` 是**二分图**：
- `OrderLogicVertex`：代表一个 always/assign 块等逻辑单元
- `OrderVarVertex`：代表一个变量（信号），分为 Pre/Post/Pord 三种变体
- 边表示数据依赖：Logic → Var（写）或 Var → Logic（读）

`MoveGraph` 将其粗化为**单分图**：
- 每个 `OrderLogicVertex` 直接映射为一个 `OrderMoveVertex`
- 每个 `OrderVarVertex` 按 **domain** 分组，每组映射为一个 `OrderMoveVertex`（`logicp() == nullptr`）
- 边仅存在于 `OrderMoveVertex` 之间，消除了变量顶点的中间层

**粗化的意义**：
- 图规模从 O(L + V) 顶点数降低到 O(L + V × D)（D 为域数量），实际中由于 `domainsExclusive` 优化，V × D 往往远小于理论值
- 消除了大量不必要的中间变量顶点，使调度图更直接反映"逻辑块之间的执行顺序"

### 2.2 时钟域（Domain）与作用域（Scope）

| 维度 | 含义 | 多线程意义 |
|------|------|-----------|
| **Domain** (`AstSenTree`) | 触发条件（如 `posedge clk`、`@(a or b)`） | 同一 domain 的顶点共享触发事件，可以批量调度 |
| **Scope** (`AstScope`) | 模块层次（如 `top.dut.alu`） | 同一 scope 的顶点共享局部变量和上下文，缓存友好 |
| **(Domain, Scope)** | 唯一的调度分组键 | 多线程任务队列的天然边界 |

`OrderMoveDomScope` 就是围绕这个二维键设计的管理器：每个实例持有一个就绪顶点链表 `m_readyVertices`，并通过 `m_links` 链接到全局就绪列表。

### 2.3 互斥域（Exclusive Domains）

这是 Verilator 实现**隐式并行化**的关键机制。`domainsExclusive()` 检测两个时钟域是否**不可能在同一 eval 轮次中同时触发**。

**典型场景**：
```verilog
always @(posedge clk) a <= b;  // Domain: posedge clk
always @(negedge clk) c <= d;  // Domain: negedge clk
```

在物理上，同一时钟的上升沿和下降沿不可能同时发生，因此这两个 always 块之间**不需要顺序依赖**。Verilator 在 `iterateVarVertex()` 中跳过这些互斥域之间的边建立：

```cpp
if (domainsExclusive(domainp, lVtxp->domainp())) continue;
```

**对并行度的影响**：
- 移除互斥域之间的依赖边后，`MoveGraph` 中形成不连通的子图
- 这些子图在多线程运行时可以**无锁地分配到不同线程**
- 这是在不引入任何运行时同步开销的情况下，通过编译期分析获得免费并行度

---

## 3. 核心数据结构

### 3.1 OrderMoveVertex

```cpp
class OrderMoveVertex final : public V3GraphVertex {
    OrderLogicVertex* const m_logicp;      // nullptr = 变量代理顶点
    OrderMoveDomScope& m_domScope;          // 所属 (domain, scope)
    V3ListLinks<OrderMoveVertex> m_links;   // 侵入式链表链接
public:
    using List = V3List<OrderMoveVertex, &OrderMoveVertex::links>;
    OrderLogicVertex* logicp() const VL_MT_STABLE { return m_logicp; }
    OrderMoveDomScope& domScope() const { return m_domScope; }
};
```

- `VL_MT_STABLE` 表示构建完成后只读，多线程安全
- `m_domScope` 的引用在构造时确定，后续不可变

### 3.2 OrderMoveDomScope

```cpp
class OrderMoveDomScope final {
    OrderMoveVertex::List m_readyVertices;   // 该分组的就绪顶点
    V3ListLinks<OrderMoveDomScope> m_links;  // 全局就绪列表链接
    bool m_isOnList = false;                  // O(1) 判断是否在全局列表
    const AstSenTree* const m_domainp;        // 时钟域
    const AstScope* const m_scopep;           // 作用域
    static DomScopeMap s_dsMap;               // 全局映射表
};
```

- `s_dsMap` 是编译期构建的静态表，运行时只读（线程安全）
- `m_isOnList` 防止重复入队，避免全局就绪列表中的重复项
- `V3List` 是 Verilator 的侵入式双向链表，无动态分配，缓存友好

### 3.3 OrderMoveGraphSerializer

```cpp
class OrderMoveGraphSerializer final {
    OrderMoveDomScope::List m_readyDomScopeps;  // 全局就绪 DomScope 列表
    OrderMoveDomScope* m_nextDomScopep = nullptr;

    void ready(OrderMoveVertex* vtxp) {
        // 逻辑顶点：加入 DomScope 的就绪列表
        // 变量顶点：直接传播依赖释放
    }

    OrderMoveVertex* getNext() {
        // 优先处理当前 DomScope 的顶点
        // 当前 DomScope 为空时，优先寻找同 domain 的其他 DomScope
    }
};
```

- `user()` 字段重载为**入度计数器**（剩余依赖数）
- `getNext()` 的 domain 优先策略是 Verilator 调度策略的核心特征

---

## 4. 关键算法分析

### 4.1 拓扑排序（Kahn 算法）

`OrderMoveGraphSerializer` 实现了经典的 Kahn 拓扑排序：
1. 初始化：所有顶点 `user() = inEdges().size()`（入度）
2. 种子：入度为 0 的顶点加入就绪队列（`addSeed`）
3. 循环：取出就绪顶点，遍历其出边，将下游顶点入度减 1，归零时加入就绪队列
4. 终止：所有顶点处理完毕

**Verilator 的变体**：
- 就绪顶点不是按全局 FIFO 队列管理，而是按 `DomScope` 分组管理
- 这确保了同一 `(domain, scope)` 的顶点被连续处理，为函数合并和缓存优化创造条件

### 4.2 域传播（Domain Propagation）

`V3OrderProcessDomains::processDomains()` 是一个前向数据流分析：
1. 时序逻辑（`always @(posedge clk)`）已有显式域
2. 组合逻辑从输入端递归合并域：
   - 若所有输入来自同一域，组合逻辑被**吸收进该域**
   - 若输入来自不同域，组合逻辑获得**合并后的多触发域**
   - 若输入从未触发（无域），逻辑被标记为删除

**组合逻辑吸收进时序域**是多线程优化的关键：它减少了全组合逻辑（纯 `@(*)`）的数量，将更多逻辑绑定到明确的时钟域，使得这些逻辑可以被批量调度。

### 4.3 串行代码生成

`V3OrderSerial::createSerial()` 将拓扑排序结果展平为 C++ 语句：
- 每次 `DomScope` 切换时调用 `forceNewFunction()`，创建新函数
- 同一 `DomScope` 内的逻辑被合并到同一函数中

**函数边界 = 任务边界**：在多线程版本中，这些函数边界很可能成为 OpenMP task 或线程池的任务划分边界。

---

## 5. 多线程设计映射

### 5.1 从单线程到多线程的扩展路径

| 单线程组件 | 多线程对应物 | 实现建议 |
|-----------|------------|---------|
| `OrderMoveGraph`（编译期构建） | 运行时只读调度图 | `const` 全局指针，多线程安全读取 |
| `user()` 入度计数器 | `std::atomic<uint32_t>` | CAS 递减，归零时推入就绪队列 |
| `V3List` 就绪队列 | 无锁队列（如 Michael-Scott） | 每个 `DomScope` 一个队列，或每个线程一个队列 |
| `OrderMoveGraphSerializer::getNext()` | Work-stealing 调度器 | 线程本地优先同 domain，窃取时跨 domain |
| `forceNewFunction()` 边界 | `#pragma omp task` 或 `tbb::task` | 每个 `DomScope` 或每个函数一个任务 |

### 5.2 隐式并行化的运行时利用

`domainsExclusive()` 在编译期移除的边，在运行时表现为：
- `MoveGraph` 中存在不连通的子图
- 这些子图对应不同的互斥时钟域
- 运行时调度器可以**独立地 eval 每个子图**，无需 barrier 同步

例如，在双沿时钟设计中：
```
Eval 轮次：
  Thread 0: 执行 posedge clk 子图
  Thread 1: 执行 negedge clk 子图
  （无需同步，因为互斥）
```

这比显式同步更优，因为两个线程可以**完全独立地**完成各自的工作。

### 5.3 同步点设计

对于非互斥的域（如 `posedge clkA` 和 `posedge clkB`，其中 clkA 和 clkB 是不同时钟），Verilator 的调度策略是：
- 在 `MoveGraph` 中保留依赖边（如果存在变量读写依赖）
- 运行时通过** barrier **或**任务依赖图**确保执行顺序

`OrderMoveGraphSerializer::getNext()` 的 domain 优先策略可以映射为：
- 先完成 Domain_X 的所有就绪任务（可能分布在多个 scope 中）
- 然后切换到 Domain_Y
- 每个 domain 切换是一个自然的同步点

---

## 6. 对自定义 RTL 仿真器的启示

### 6.1 设计原则

1. **编译期域分析是并行化的前提**
   - 时钟域互斥信息在编译期已完全确定，不应在运行时动态检测
   - 维护 `Domain → 互斥 Domain 集合` 的只读表，作为调度器输入

2. **(Domain, Scope) 是理想的任务分组键**
   - 比纯拓扑分区更语义化，比纯循环分区更缓存友好
   - 二维键天然对应 RTL 设计中的"何时触发 × 在哪里执行"

3. **侵入式链表优于标准容器**
   - `V3List` 无动态分配、无额外指针开销、缓存行友好
   - 多线程版本可以基于同一结构实现无锁队列（CAS 操作 `next`/`prev` 指针）

4. **依赖计数递减是任务就绪的信号**
   - 借鉴 `user()` 模式，用原子计数器实现无锁任务释放
   - 当计数器归零时，通过无锁队列推入全局就绪池

5. **函数边界隐含任务边界**
   - `forceNewFunction()` 的 domain/scope 切换逻辑可以直接复用为任务划分逻辑
   - 每个生成的 C++ 函数可以包装为独立任务，提交到线程池

### 6.2 可迁移的代码模式

**模式 1：域互斥检测**
```cpp
// 编译期构建
bool isExclusive(Domain a, Domain b) {
    return sameClock(a, b) && oppositeEdge(a, b);
}
// 运行时只读查询
if (isExclusive(srcDomain, dstDomain)) skipDependencyEdge();
```

**模式 2：DomScope 分组就绪队列**
```cpp
struct DomScopeQueue {
    Domain domain;
    Scope scope;
    lockfree::queue<Task*> readyTasks;
};
std::unordered_map<DomScopeKey, DomScopeQueue> queues;
```

**模式 3：原子依赖计数 + 无锁释放**
```cpp
std::atomic<int> pendingDeps;
void onDependencySatisfied() {
    if (--pendingDeps == 0) {
        globalReadyQueue.push(this);
    }
}
```

**模式 4：Domain 优先调度**
```cpp
Task* stealTask() {
    // 优先从同 domain 的队列窃取
    for (auto& q : localQueues) {
        if (q.domain == currentDomain && !q.empty()) return q.pop();
    }
    // 其次从全局队列获取
    return globalQueue.pop();
}
```

---

## 7. 与 Verilator 其他模块的关系

```
V3OrderGraph (二分图)
    ↓
V3OrderProcessDomains (域传播 + 死路径消除)
    ↓
V3OrderMoveGraph (粗化图 + 互斥域边移除)
    ↓
    ├─ V3OrderSerial (单线程代码生成)
    └─ V3OrderParallel (多线程代码生成，未分析)
    ↓
V3EmitC (C++ 代码发射)
```

`V3OrderMoveGraph` 处于承上启下的位置：它接收经过域处理的细粒度图，输出经过粗化和优化的调度图，供串行/并行代码生成器使用。理解这一层，是理解 Verilator 从"前端分析"到"后端调度"完整链条的关键。

---

## 8. 相关资源

### 8.1 本知识库内的源文件

- [source-verilator-V3OrderMoveGraph移动图](source-verilator-V3OrderMoveGraph移动图.md) — 本主题的详细源码分析
- [source-verilator-mt-deep](source-verilator-mt-deep.md) — Verilator 多线程深层架构分析
- [source-verilator-partition-evolution](source-verilator-partition-evolution.md) — 分区策略演进
- [source-verilator-mt-prs-detailed](source-verilator-mt-prs-detailed.md) — 多线程相关 PR 详细分析

### 8.2 外部链接

- [Verilator 官方仓库](https://github.com/verilator/verilator)
- [V3OrderGraph.h](https://github.com/verilator/verilator/blob/master/src/V3OrderGraph.h)
- [V3OrderParallel.cpp](https://github.com/verilator/verilator/blob/master/src/V3OrderParallel.cpp) — 多线程并行代码生成
- [Verilator Multithreading Guide](https://verilator.org/guide/latest/exe_verilator.html#multithreading)

---

## 9. 术语表

| 术语 | 解释 |
|------|------|
| **OrderGraph** | Verilator 的基础依赖图，二分图结构（LogicVertex ↔ VarVertex） |
| **MoveGraph** | OrderGraph 的粗化版本，单分图，用于驱动代码生成 |
| **DomScope** | Domain + Scope 的二维分组键，管理就绪顶点 |
| **Serializer** | 拓扑排序器，将 MoveGraph 展平为执行顺序 |
| **Exclusive Domain** | 互斥时钟域（如 posedge 和 negedge），不可能同时触发 |
| **Domain Propagation** | 从输入向输出传播时钟域信息的数据流分析 |
| **VL_MT_DISABLED** | Verilator 宏，标记该函数/代码单元仅在单线程编译期执行 |
| **VL_MT_STABLE** | Verilator 宏，标记该函数返回值在对象生命周期内稳定，多线程读取安全 |
| **V3List** | Verilator 的侵入式双向链表，无动态分配 |

---

*最后更新: 2026-07-04*

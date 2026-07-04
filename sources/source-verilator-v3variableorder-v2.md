---
title: "V3VariableOrder 变量排序：MTask 亲和性与无锁并行编译"
source_url: "https://github.com/verilator/verilator/tree/master/src/"
source_type: "github-code"
author: "Verilator Team"
date: ""
tags: ["verilator", "multithreading", "variable-ordering", "MTask", "cache-line-align", "thread-pool", "data-partitioning", "false-sharing", "parallel-compiler"]
keywords: ["V3VariableOrder", "GatherMTaskAffinity", "VariableOrder", "MTaskAffinityMap", "MTaskIdVec", "V3ThreadScope", "cache line alignment", "stratum", "macro-task", "parallel variable ordering"]
capture_date: "2026-07-04"
---

# V3VariableOrder 源码深度分析

## 文件概览

| 文件 | 路径 | 行数 | 角色 |
|------|------|------|------|
| 头文件 | `src/V3VariableOrder.h` | ~25 | 公共接口声明 |
| 实现文件 | `src/V3VariableOrder.cpp` | ~200 | 排序算法、MTask 亲和性收集、多线程并行 |

## 来源

- URL: https://github.com/verilator/verilator/blob/master/src/V3VariableOrder.cpp
- URL: https://github.com/verilator/verilator/blob/master/src/V3VariableOrder.h
- 类型: github-code
- 作者: Verilator Team (Wilson Snyder 等); PR #5406 并行化改进来自 Bartłomiej Chmiel, Antmicro Ltd.

---

## 1. 设计目标与架构定位

`V3VariableOrder` 是 Verilator 编译流水线中**代码生成前最后一个优化内存布局的 Pass**。它负责：

1. **变量排序**：为每个模块内的 `AstVar` 节点确定最终输出顺序，直接影响生成的 C++ 结构体中字段的排列
2. **缓存优化**：将具有相同 MTask（Macro-Task）亲和性的变量聚集在一起，并插入缓存行对齐（`mtaskCacheLineAlign`），减少多线程仿真时的 false sharing
3. **内存填充最小化**：通过 `stratum` 分层将相同对齐要求的变量相邻放置，减少结构体内部填充（padding）

该模块运行时机：在 `src/Verilator.cpp` 中通过 `V3VariableOrder::orderAll(v3Global.rootp())` 调用，位于大部分编译优化之后、C++ 代码生成之前。

---

## 2. 关键数据结构

### 2.1 MTaskIdVec（MTask 亲和性位集）

**文件**: `src/V3VariableOrder.cpp` 第 30 行

```cpp
using MTaskIdVec = std::vector<bool>;  // Used as a bit-set indexed by MTask ID
```

- 以 `std::vector<bool>` 作为位集，索引为 `ExecMTask::id()`
- `m_usedIds = ExecMTask::numUsedIds()` 表示最大 ID + 1，即位集长度
- 每个位为 `true` 表示该变量被对应 MTask 引用

### 2.2 MTaskAffinityMap（变量到亲和性的映射）

**文件**: `src/V3VariableOrder.cpp` 第 31 行

```cpp
using MTaskAffinityMap = std::unordered_map<const AstVar*, MTaskIdVec>;
```

- 键：`const AstVar*`（变量节点指针）
- 值：`MTaskIdVec`（该变量被哪些 MTask 引用）
- 此映射在**单线程阶段**构建完成，随后作为**只读数据**共享给所有并行工作线程

### 2.3 VarAttributes（变量属性）

**文件**: `src/V3VariableOrder.cpp` 第 70–73 行

```cpp
struct VarAttributes final {
    uint8_t stratum;  // Roughly equivalent to alignment requirement, to avoid padding
    bool anonOk;      // Can be emitted as part of anonymous structure
};
```

- `stratum`：数值越小，对齐要求越高/越重要，在排序中排在前面
- `anonOk`：如果变量可以放入匿名结构体，则与其他 `anonOk` 变量聚集，节省命名开销

---

## 3. 核心类分析

### 3.1 V3VariableOrder（公共接口）

**文件**: `src/V3VariableOrder.h` 第 23–25 行

```cpp
class V3VariableOrder final {
public:
    static void orderAll(AstNetlist*);
};
```

- 极简的静态接口，只暴露 `orderAll` 入口
- `final` 关键字禁止继承，确保行为不变性

### 3.2 GatherMTaskAffinity（MTask 亲和性收集器）

**文件**: `src/V3VariableOrder.cpp` 第 34–86 行

```cpp
class GatherMTaskAffinity final : VNVisitorConst {
    const VNUser1InUse m_user1InUse;
    MTaskAffinityMap& m_results;
    const uint32_t m_id;
    const size_t m_usedIds = ExecMTask::numUsedIds();
```

- 继承 `VNVisitorConst`：常量访问者，不修改 AST，只遍历读取
- `m_user1InUse`：RAII 管理 `user1()` 节点标记位，确保遍历结束后清理
- `m_id`：当前正在分析的 MTask ID
- `m_results`：输出映射的引用

**关键访问函数：visit(AstNodeVarRef*)** 第 54–65 行

```cpp
void visit(AstNodeVarRef* nodep) override {
    if (nodep->user1SetOnce()) return;  // 防止重复遍历同一节点
    AstVar* const varp = nodep->varp();
    MTaskIdVec& affinity = m_results
        .emplace(std::piecewise_construct,
                 std::forward_as_tuple(varp),
                 std::forward_as_tuple(m_usedIds))
        .first->second;
    affinity[m_id] = true;
}
```

- 使用 `user1SetOnce()` 标记已访问，避免在同一 MTask 内重复遍历
- `std::piecewise_construct` + `std::forward_as_tuple`：避免 `emplace` 构建临时对象，性能优化
- 对 `MTaskIdVec` 的写入是**单线程的**：每个 `GatherMTaskAffinity` 实例只处理一个 MTask，不同 MTask 之间不会同时修改同一个 `AstVar` 的 affinity

**visit(AstCFunc*)** 第 67–70 行：防止函数体重复遍历，支持递归调用

```cpp
void visit(AstCFunc* nodep) override {
    if (nodep->user1SetOnce()) return;  // Prevent repeat traversals/recursion
    iterateChildrenConst(nodep);
}
```

**visit(AstNodeCCall*)** 第 72–76 行：遍历函数参数和 callee 函数体

```cpp
void visit(AstNodeCCall* nodep) override {
    iterateChildrenConst(nodep);   // Arguments
    iterateConst(nodep->funcp());  // Callee
}
```

**public 接口：apply** 第 83–85 行

```cpp
static void apply(const ExecMTask* mTaskp, MTaskAffinityMap& results) {
    GatherMTaskAffinity{mTaskp, results};
}
```

- 私有构造 + 公共静态 `apply`：工厂模式，确保正确使用 RAII

### 3.3 VariableOrder（排序引擎）

**文件**: `src/V3VariableOrder.cpp` 第 88–187 行

```cpp
class VariableOrder final {
    std::unordered_map<const AstVar*, VarAttributes> m_attributes;
    const MTaskAffinityMap& m_mTaskAffinity;
    std::vector<AstVar*>& m_varps;
```

- `m_attributes`：每个变量的属性（stratum + anonOk），在 `orderModuleVars` 中填充
- `m_mTaskAffinity`：只读引用，指向 `orderAll` 中构建的 `MTaskAffinityMap`
- `m_varps`：引用，存储排序后的变量列表

#### 3.3.1 simpleSortVars（非多线程排序）

**文件**: `src/V3VariableOrder.cpp` 第 100–118 行

```cpp
void simpleSortVars(std::vector<AstVar*>& varps) {
    stable_sort(varps.begin(), varps.end(),
                [this](const AstVar* ap, const AstVar* bp) -> bool {
        if (ap->isStatic() != bp->isStatic()) {
            return bp->isStatic();  // Non-statics before statics
        }
        const auto& attrA = m_attributes.at(ap);
        const auto& attrB = m_attributes.at(bp);
        if (attrA.anonOk != attrB.anonOk) {
            return attrA.anonOk;  // Anons before non-anons
        }
        return attrA.stratum < attrB.stratum;  // Sort by stratum
    });
}
```

- 使用 `std::stable_sort` 保持稳定性
- 三级排序键：
  1. 非 static 优先于 static（`bp->isStatic()` 等价于 `!ap->isStatic() && bp->isStatic()`）
  2. `anonOk` 为 true 的优先（可放入匿名结构）
  3. `stratum` 值小的优先（对齐要求高的在前，减少 padding）

#### 3.3.2 mtaskSortVars（MTask 感知排序）

**文件**: `src/V3VariableOrder.cpp` 第 124–166 行

```cpp
void mtaskSortVars(std::vector<AstVar*>& varps) {
    std::map<MTaskIdVec, std::vector<AstVar*>> m2v;
    const MTaskIdVec emptyVec(ExecMTask::numUsedIds(), false);
    for (AstVar* const varp : varps) {
        const auto it = m_mTaskAffinity.find(varp);
        const MTaskIdVec& key = it == m_mTaskAffinity.end() ? emptyVec : it->second;
        m2v[key].push_back(varp);
    }
    varps.clear();
```

- 使用 `std::map<MTaskIdVec, std::vector<AstVar*>>` 而非 `std::unordered_map`
- 关键原因：`std::vector<bool>` 没有 `std::hash` 特化，不能作为 `unordered_map` 的键；更重要的是 `std::map` 保证**确定性的遍历顺序**，确保跨平台/跨运行输出一致

**sortAndAppend lambda**（第 143–156 行）：

```cpp
const auto sortAndAppend = [this, &varps](std::vector<AstVar*>& subVarps, bool alignFirst) {
    simpleSortVars(subVarps);
    bool aligned = !alignFirst;
    for (AstVar* const varp : subVarps) {
        if (!aligned && !varp->isStatic()) {
            varp->mtaskCacheLineAlign(true);
            V3Stats::addStatSum("VariableOrder, MTask aligned group starts", 1);
            aligned = true;
        }
        varps.push_back(varp);
    }
};
```

- 对每个 MTask 亲和组内部调用 `simpleSortVars`
- `alignFirst = true` 时，组内第一个**非 static** 变量设置 `mtaskCacheLineAlign(true)`
- 静态变量不触发对齐，因为 static 变量通常不在实例结构体中
- `V3Stats::addStatSum` 记录统计信息，用于性能调优

**分组处理逻辑**（第 159–171 行）：

```cpp
size_t affinityGroups = 0;
for (auto& pair : m2v) {
    if (emptyAffinity(pair.first)) continue;
    sortAndAppend(pair.second, true);  // alignFirst = true
    ++affinityGroups;
}
sortAndAppend(m2v[emptyVec], false);  // 无亲和性变量，不对齐
```

- 先处理有 MTask 亲和性的组（每组开头对齐）
- 最后处理无 MTask 亲和性的变量（不插入额外对齐）
- 统计指标：`VariableOrder, MTask affinity groups`、`VariableOrder, no-affinity variables`

#### 3.3.3 orderModuleVars（模块变量排序入口）

**文件**: `src/V3VariableOrder.cpp` 第 174–187 行

**Stratum 计算**（第 180–191 行）：

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

优先级排序（从高到低对齐敏感度）：

| stratum | 条件 | 说明 |
|---------|------|------|
| 0 | `hierChild` 的 Primary IO | 最优先，层次化子模块的 IO |
| 1 | Primary Clock + 1-bit | 主时钟信号，通常频繁访问 |
| 2 | 1-byte 信号 | 基础对齐 |
| 3 | 2-byte 信号 | 半字对齐 |
| 5 | 4-byte 信号 | 字对齐 |
| 6 | 8-byte 信号 | 双字对齐 |
| 7 | SystemC 类型 (sc_bv, sc_biguint) | 特殊类型 |
| 8 | opaque 类型 | 不透明类型 |
| 9 | UnpackArrayDType | 解包数组，通常占用较大空间 |
| 10 | 默认 | 其他情况 |

**排序分支**（第 196–200 行）：

```cpp
if (!m_varps.empty()) {
    if (!v3Global.opt.mtasks()) {
        simpleSortVars(m_varps);
    } else {
        mtaskSortVars(m_varps);
    }
}
```

- 未启用多线程（`--threads` 未指定）→ 简单排序
- 启用多线程 → MTask 感知排序（含缓存行对齐）

---

## 4. 多线程并行实现细节

### 4.1 整体流程（orderAll）

**文件**: `src/V3VariableOrder.cpp` 第 193–243 行

```cpp
void V3VariableOrder::orderAll(AstNetlist* netlistp) {
    UINFO(2, __FUNCTION__ << ":");

    MTaskAffinityMap mTaskAffinity;

    // 阶段 1: 单线程收集 MTask 亲和性
    if (v3Global.opt.mtasks()) {
        netlistp->topModulep()->foreach([&](AstExecGraph* execGraphp) {
            for (const V3GraphVertex& vtx : execGraphp->depGraphp()->vertices()) {
                GatherMTaskAffinity::apply(vtx.as<const ExecMTask>(), mTaskAffinity);
            }
        });
    }
    if (v3Global.opt.stats()) V3Stats::statsStage("variableorder-gather");

    // 阶段 2: 多线程并行排序每个模块
    std::unordered_map<AstNodeModule*, std::vector<AstVar*>> sortedVars;
    {
        V3ThreadScope threadScope;  // RAII 线程池作用域
        for (AstNodeModule* modp = v3Global.rootp()->modulesp(); modp;
             modp = VN_AS(modp->nextp(), NodeModule)) {
            std::vector<AstVar*>& varps = sortedVars[modp];
            threadScope.enqueue([modp, &mTaskAffinity, &varps]() {
                VariableOrder::processModule(modp, mTaskAffinity, varps);
            });
        }
    }  // threadScope 析构时等待所有任务完成
    if (v3Global.opt.stats()) V3Stats::statsStage("variableorder-sort");

    // 阶段 3: 单线程重组 AST
    for (AstNodeModule* modp = v3Global.rootp()->modulesp(); modp;
         modp = VN_AS(modp->nextp(), NodeModule)) {
        const std::vector<AstVar*>& varps = sortedVars[modp];
        if (!varps.empty()) {
            // unlink 并重新链接到模块...
        }
    }
}
```

### 4.2 并行策略：数据分区 + 只读共享

| 数据 | 访问模式 | 同步机制 | 说明 |
|------|----------|----------|------|
| `mTaskAffinity` | 只读 | 无（构建后不变） | 单线程构建完成后，所有工作线程只读引用 |
| `sortedVars[modp]` | 每个模块独立写 | 无 | 主线程预先创建 `vector` 条目，每个 worker 写自己的 `vector` |
| `m_attributes` | 每个 `VariableOrder` 实例私有 | 无 | 无共享状态 |
| AST (AstVar) | 读取属性/写入 `mtaskCacheLineAlign` 标志 | 无冲突 | 每个模块的 AstVar 是独立的集合，不同模块不重叠 |

**核心设计原则**：
- **没有显式锁**：`std::mutex`、`std::atomic` 均未出现
- **没有线程间通信**：每个 worker 完全独立
- **数据并行**：按模块划分任务，每个模块是一个独立的排序单元

### 4.3 V3ThreadScope 的使用

```cpp
{
    V3ThreadScope threadScope;
    // ... enqueue tasks ...
}
```

- `V3ThreadScope` 是 Verilator 线程池的 RAII 作用域（定义在 `V3ThreadPool.h`）
- 构造函数可能初始化线程池或标记线程活跃状态
- 析构函数**等待所有 enqueued 任务完成**（join 语义）
- `threadScope.enqueue(lambda)`：将 lambda 提交到线程池的任务队列

### 4.4 Lambda 捕获分析

```cpp
threadScope.enqueue([modp, &mTaskAffinity, &varps]() {
    VariableOrder::processModule(modp, mTaskAffinity, varps);
});
```

- `modp`：按值捕获（指针拷贝，安全）
- `&mTaskAffinity`：按引用捕获只读映射（安全，因为构建后不变）
- `&varps`：按引用捕获 `sortedVars[modp]` 的 vector（安全，每个模块有自己的 vector）
- 没有捕获 `this`（`VariableOrder` 实例在 lambda 执行后才创建）

### 4.5 为什么不需要锁？

1. **MTaskAffinityMap 构建阶段**：完全单线程，通过 `foreach` 遍历所有 ExecGraph 的顶点，每个 `GatherMTaskAffinity` 实例处理一个 MTask。不同 MTask 的 affinity 位设置在不同的 `m_id` 索引上，即使写入同一 `AstVar` 的 `MTaskIdVec`，也是修改不同的 bit 位置。但由于 `GatherMTaskAffinity` 是顺序调用的，实际上没有并发。

2. **排序阶段**：`sortedVars` 是 `std::unordered_map<AstNodeModule*, std::vector<AstVar*>>`，主线程在 `enqueue` 之前通过 `sortedVars[modp]` 创建每个模块的条目。`operator[]` 可能触发 rehash，但这是在**主线程**中、**enqueue 之前**完成的。之后每个 worker 只读写自己模块的 `vector`。

3. **AST 重组阶段**：单线程执行，所有 worker 已完成后才进行。

---

## 5. 缓存优化与 False Sharing 防护

### 5.1 mtaskCacheLineAlign 的作用

`mtaskCacheLineAlign(true)` 在 `AstVar` 节点上设置一个标记，指示代码生成器在输出该变量前**插入缓存行对齐指令**（如 `alignas(64)` 或适当的填充）。

**为什么能防止 false sharing？**
- 多线程仿真时，每个 MTask 可能由不同线程执行
- 如果属于不同 MTask 的变量落在同一缓存行（64 字节），一个线程修改变量 A 会导致另一个线程的变量 B 缓存失效
- 将不同 MTask 亲和组的变量对齐到不同缓存行边界，确保它们不在同一缓存行

### 5.2 对齐策略的权衡

```cpp
if (!aligned && !varp->isStatic()) {
    varp->mtaskCacheLineAlign(true);
    aligned = true;
}
```

- 只在**每组开头**对齐一次（`aligned` 标志）
- 不 static 变量才需要对齐，因为 static 变量通常不在模块实例的结构体中
- 如果组很小（比如只有一个变量），对齐可能浪费 60+ 字节 padding
- 目前没有动态评估收益/开销的逻辑，是无条件对齐

### 5.3 与稀疏计算的关联

在稀疏计算 RTL 仿真器中：
- 变量活跃模式是**动态的**（时变），而非 Verilator 的静态 MTask 分区
- 可以考虑按**活跃周期模式**分组，而非静态 MTask 亲和性
- 如果活跃模式频繁变化，可能需要**运行时动态重排**或**预编译多个布局版本**
- 缓存行对齐的收益在稀疏场景下可能更高（因为每次访问更宝贵），但内存浪费也更大

---

## 6. 关键代码路径与行号索引

| 功能 | 行号范围 | 说明 |
|------|----------|------|
| MTaskIdVec 类型别名 | 30 | `std::vector<bool>` 位集 |
| MTaskAffinityMap 类型别名 | 31 | `unordered_map` |
| GatherMTaskAffinity 类定义 | 34–86 | 访问者模式收集亲和性 |
| visit(AstNodeVarRef*) | 54–65 | 设置 affinity 位 |
| VarAttributes 结构体 | 70–73 | stratum + anonOk |
| VariableOrder 类定义 | 88–187 | 排序引擎 |
| simpleSortVars | 100–118 | 稳定三级排序 |
| emptyAffinity | 120–122 | 检查空亲和性 |
| mtaskSortVars | 124–166 | MTask 感知分组排序 |
| sortAndAppend lambda | 143–156 | 组内排序 + 缓存行对齐 |
| orderModuleVars | 174–200 | 模块变量提取 + stratum 计算 + 分支 |
| stratum 计算 | 180–191 | 11 级优先级 |
| orderAll (入口) | 193–243 | 三阶段流程 |
| 单线程 MTask 亲和性收集 | 196–202 | 遍历 ExecGraph 顶点 |
| V3ThreadScope 并行排序 | 205–217 | 模块级并行 |
| 单线程 AST 重组 | 220–243 | unlink + 重新链接 |

---

## 7. 对 RTL 仿真器多线程化的启示

### 7.1 编译器自身的并行化是必需的

PR #5406 的动机说明，即使对于编译器本身，变量排序在大规模设计下也成为瓶颈。这提示：如果我们的仿真器支持编译时优化，**编译器阶段的并行化**不应被忽视。具体策略：

- 按模块/函数分区并行（如 V3VariableOrder 的做法）
- 共享只读 IR（如 `MTaskAffinityMap`），避免复制开销
- 结果聚合阶段单线程化，避免并发修改容器

### 7.2 数据分区是无锁并行的黄金法则

V3VariableOrder 的并行设计展示了**数据分区并行**的经典模式：

1. 找出天然的独立工作单元（这里是模块）
2. 预分配结果容器（`sortedVars`），避免 worker 竞争容器操作
3. 共享只读输入数据（`mTaskAffinity`）
4. 单线程后处理（AST 重组）

在稀疏计算仿真器中，同样的模式可以应用于：
- 并行活跃性分析（每个模块独立分析）
- 并行代码生成（每个模块独立生成 C++）
- 并行优化 pass（如死代码消除、常量传播）

### 7.3 缓存行对齐是双刃剑

V3VariableOrder 的 `mtaskCacheLineAlign` 无条件在每组开头对齐。在稀疏计算场景中：

- **收益**：减少 false sharing，对多核扩展性至关重要
- **代价**：如果变量组小，padding 可能浪费大量内存；在稀疏场景中，内存占用直接影响缓存效率
- **改进方向**：动态评估——只有当 MTask 亲和组内变量总大小接近缓存行时才对齐；或者按变量大小加权决定是否对齐

### 7.4 从静态 MTask 到动态活跃模式

Verilator 的 MTask 亲和性是**静态**的（编译时确定）。在稀疏计算中，变量的活跃模式是**时变**的：

- 一个变量可能在某些周期属于任务 A，在另一些周期属于任务 B
- 这提示我们可能需要：
  - **按活跃周期模式预编译多个变量布局版本**（如 "模式 A" 和 "模式 B" 的两种结构体）
  - **运行时动态重排**（如果模式切换频率不高，可以通过 `memcpy` 重排结构体）
  - **细粒度亲和性**：不仅按 MTask，还按时间步或事件类型分组

### 7.5 确定性输出的重要性

V3VariableOrder 使用 `std::map`（而非 `std::unordered_map`）来保持 MTask 亲和分组的确定性顺序。这确保了：

- 跨平台输出一致（C++ 代码生成结果相同）
- 调试可复现（同样的输入总是产生同样的输出）
- 回归测试稳定（不会因为哈希顺序变化导致无关的 diff）

在自定义仿真器中，如果并行化可能影响输出顺序，应特别注意：
- 使用有序容器（`std::map`、`std::set`）或显式排序
- 在并发阶段后添加单线程的确定性排序步骤
- 避免 `std::unordered_map` 的遍历顺序依赖（除非使用自定义确定性哈希）

---

## 8. 统计指标与调优

V3VariableOrder 收集以下统计指标（通过 `V3Stats::addStatSum`）：

| 指标名 | 含义 | 调优参考 |
|--------|------|----------|
| `VariableOrder, MTask affinity groups` | 有 MTask 亲和性的变量组数 | 值越大，分组越细，对齐开销越大 |
| `VariableOrder, MTask aligned group starts` | 触发缓存行对齐的组数 | 应等于 affinity groups |
| `VariableOrder, no-affinity variables` | 无 MTask 亲和性的变量数 | 值大说明变量共享度高或 MTask 划分粗糙 |

---

## 9. 相关依赖与调用链

```
Verilator.cpp
  └── V3VariableOrder::orderAll(v3Global.rootp())
        ├── V3ThreadPool.h (V3ThreadScope, threadScope.enqueue)
        ├── V3ExecGraph.h (ExecMTask, AstExecGraph)
        ├── V3AstUserAllocator.h (user1SetOnce)
        ├── V3EmitCBase.h (EmitCUtil::isAnonOk)
        └── V3Stats.h (性能统计)
```

---

## 10. 总结

V3VariableOrder 是 Verilator 多线程编译流水线中的一个**小而精的并行优化模块**。它的设计亮点在于：

1. **无锁并行**：通过数据分区（按模块）实现天然无锁，不需要任何同步原语
2. **只读共享**：MTaskAffinityMap 单线程构建后作为只读数据共享，消除竞争
3. **缓存感知**：MTask 亲和性分组 + 缓存行对齐，直接服务于多线程仿真阶段的 false sharing 减少
4. **稳定性优先**：使用 `std::stable_sort` 和 `std::map` 确保确定性输出

对于稀疏计算 RTL 仿真器的多线程化，V3VariableOrder 提供了以下可直接迁移的经验：
- **按模块/任务分区并行是编译器并行的最佳切入点**
- **预分配结果容器 + 只读共享输入 = 无锁并行**
- **缓存行对齐虽好，但需要评估内存开销**
- **静态亲和性可以扩展到动态活跃模式，以进一步优化稀疏场景**

## 参考链接

- https://github.com/verilator/verilator/blob/master/src/V3VariableOrder.cpp
- https://github.com/verilator/verilator/blob/master/src/V3VariableOrder.h
- https://github.com/verilator/verilator/pull/5406 (并行化改进)
- https://github.com/verilator/verilator/pull/5161 (V3ThreadPool 相关改进)

---
title: "Verilator V3Dfg 数据流图编译优化系统"
source_url: "https://github.com/verilator/verilator/tree/master/src/"
source_type: "github-code"
author: "Verilator Team"
date: "2024"
tags: ["verilator", "multithreading", "dfg", "dataflow-graph", "compiler-optimization", "cse", "rtl-simulation"]
keywords: ["DfgVertex", "DfgGraph", "DfgEdge", "DfgUserMap", "DfgWorklist", "V3DfgCse", "splitIntoComponents", "extractCyclicComponents", "VL_MT_DISABLED"]
capture_date: "2026-07-05"
---

# Verilator V3Dfg 数据流图编译优化系统

## 来源

- **仓库**: verilator/verilator
- **文件组**: V3Dfg.h, V3Dfg.cpp, V3DfgAstToDfg.cpp, V3DfgDfgToAst.cpp, V3DfgOptimizer.cpp, V3DfgCse.cpp
- **类型**: 源码分析
- **路径**: `src/V3Dfg*.cpp`, `src/V3Dfg.h`

---

## 摘要

Verilator 的 V3Dfg 模块实现了一套**数据流图（Data Flow Graph, DFG）**表示与编译优化系统。它将 AST 中的组合逻辑转换为以 `DfgVertex` 为节点、`DfgEdge` 为边的中间表示，在 DFG 层面执行 CSE、peephole、变量内联、选择消除等优化，然后再转回 AST。整个系统目前标记为 `VL_MT_DISABLED`，意味着所有 DFG 操作在**编译阶段串行执行**。但其架构中隐含着**组件级天然并行性**——`splitIntoComponents` 和 `extractCyclicComponents` 将大图拆分为互不连通的独立子图，每个子图可独立优化。此外，`DfgUserMap` 的零开销 generation 映射、`DfgWorklist` 的预取优化，以及分类型存储顶点的设计，均为 RTL 仿真器多线程编译优化提供了可借鉴的工程模式。

---

## 1. 文件架构与职责

| 文件 | 职责 | 行数规模 |
|------|------|----------|
| `V3Dfg.h` | 核心数据结构与内联方法定义（`DfgVertex`, `DfgEdge`, `DfgGraph`, `DfgUserMap`, `DfgWorklist`） | ~550 行 |
| `V3Dfg.cpp` | 图操作实现（`clone`, `mergeGraphs`, `splitIntoComponents`, `extractCyclicComponents`, `dumpDot`） | ~700 行 |
| `V3DfgAstToDfg.cpp` | AST → DFG 转换（`AstToDfgVisitor`） | ~200 行 |
| `V3DfgDfgToAst.cpp` | DFG → AST 转换（`DfgToAstVisitor`） | ~300 行 |
| `V3DfgOptimizer.cpp` | 优化入口与编排（`DataflowOptimize`） | ~200 行 |
| `V3DfgCse.cpp` | 公共子表达式消除（`V3DfgCse`） | ~250 行 |

---

## 2. 核心数据结构（`V3Dfg.h`）

### 2.1 `DfgVertex` — 数据流图顶点

```cpp
// V3Dfg.h, lines 82-140
class DfgVertex VL_NOT_FINAL {
    friend class DfgGraph;
    friend class DfgEdge;
    friend class DfgVisitor;

    V3ListLinks<DfgVertex> m_links;               // 在 DfgGraph 链表中的链接
    std::vector<std::unique_ptr<DfgEdge>> m_inputps;  // 输入边，vector 支持直接索引
    DfgEdge::List m_sinks;                         // 输出边（sink）链表

    FileLine* const m_filelinep;                   // 源码位置
    const DfgDataType& m_dtype;                    // 结果数据类型
    const VDfgType m_type;                         // 顶点类型标签

    mutable uint32_t m_userGeneration = 0;         // 用户数据世代号
    mutable void* m_userStorage = nullptr;         // 用户数据存储（仅一个指针）

#ifdef VL_DEBUG
    DfgGraph* m_dfgp = nullptr;                    // 调试：所属图
#endif
    // ...
};
```

**关键设计决策**：
- **输入边用 `vector<unique_ptr<DfgEdge>>`**：不同于 `V3Graph` 的链表结构，`DfgVertex` 直接用 vector 索引输入边，修改操作更高效。
- **输出边用 `V3List<DfgEdge>`**（链表）：`m_sinks` 是 sink 边链表，迭代时可安全解链当前元素（`unlinkable()`）。
- **`m_userStorage` + `m_userGeneration`**：这是 `DfgUserMap` 零开销映射的基础——每个顶点自带一个 `void*` 和一个世代号，避免外部 hashmap 的查找开销。

### 2.2 `DfgEdge` — 数据流边

```cpp
// V3Dfg.h, lines 69-81
class DfgEdge final {
    friend class DfgVertex;

    DfgVertex* m_srcp = nullptr;  // 驱动此边的源顶点（可能未连接）
    DfgVertex* const m_dstp;       // 被驱动的目标顶点（拥有此边，不可变）
    V3ListLinks<DfgEdge> m_links;  // 在 m_srcp->m_sinks 链表中的链接

    VL_UNCOPYABLE(DfgEdge);
    VL_UNMOVABLE(DfgEdge);
    // ...
};
```

**所有权模型**：`m_dstp` 是 `const`（目标顶点不可变），因为目标顶点拥有此边。边的创建/销毁由 `DfgVertex::newInput()` 和析构函数管理。

### 2.3 `DfgGraph` — 图容器（按类型分桶）

```cpp
// V3Dfg.h, lines 200-220
class DfgGraph final {
    DfgVertex::List<DfgVertexVar> m_varVertices;   // 变量顶点（~40-50% 的顶点）
    DfgVertex::List<DfgVertexAst> m_astVertices;     // AST 引用顶点
    DfgVertex::List<DfgConst> m_constVertices;     // 常量顶点
    DfgVertex::List<DfgVertex> m_opVertices;         // 操作顶点
    size_t m_size = 0;
    const std::string m_name;
    // ...
};
```

**多线程启示**：注释明确说明变量和常量占顶点总数的 40-50%，且这些顶点在算法中常被特殊处理。因此将顶点按类型分桶存储，避免遍历所有顶点时做类型检查——这是**空间换时间 + 分治**的经典策略。

### 2.4 `DfgUserMap` — 零开销顶点属性映射

```cpp
// V3Dfg.h, lines 340-430
class DfgUserMap<T_Value, true> final : public DfgUserMapBase {
    T_Value& operator[](const DfgVertex& vtx) {
        T_Value* const storagep = reinterpret_cast<T_Value*>(&vtx.m_userStorage);
        if (vtx.m_userGeneration != m_currentGeneration) {
            new (storagep) T_Value{};      // placement new 初始化
            vtx.m_userGeneration = m_currentGeneration;
        }
        return *storagep;
    }
};
```

**核心机制**：
- 如果 `T_Value` 能塞进 `void*`（`sizeof(T) <= sizeof(void*)` 且对齐兼容），直接存到 `m_userStorage`。
- 如果太大，则存指针到 `m_userStorage`，数据放在 `std::deque<T_Value>` 中。
- 通过 `m_userGeneration`（全局世代计数器）区分"当前映射"和"旧数据"，避免每次清空所有顶点的映射。
- 同一时刻一个图只能有一个 `DfgUserMap` 在使用（`m_vertexUserInUse` 断言）。

**多线程启示**：`DfgUserMap` 的设计在**单线程编译阶段**是极致的零开销优化。但在多线程场景下，同一图的多个 worker 需要各自的 `DfgUserMap` 时，必须扩展设计：
- 方案 A：每个 worker 操作一个独立子图（无需共享 UserMap）。
- 方案 B：引入 per-thread 的 `m_userStorage` 数组（类似 TLS 的存储槽）。
- 方案 C：使用外部 `thread_local` hashmap，牺牲一点性能换取并行能力。

### 2.5 `DfgWorklist` — 预取优化的工作列表

```cpp
// V3Dfg.h, lines 460-510
class DfgWorklist final {
    DfgGraph& m_dfg;
    DfgUserMap<DfgVertex*> m_nextp = m_dfg.makeUserMap<DfgVertex*>();
    DfgVertex* const m_sentinelp = reinterpret_cast<DfgVertex*>(this);
    DfgVertex* m_headp = m_sentinelp;

    bool push_front(DfgVertex& vtx) {
        DfgVertex*& nextpr = m_nextp[vtx];
        if (nextpr) return false;      // 已在列表中
        nextpr = m_headp;
        m_headp = &vtx;
        return true;
    }

    template <typename T_Callable>
    void foreach(T_Callable&& f) {
        while (m_headp != m_sentinelp) {
            DfgVertex& vtx = *m_headp;
            m_headp = m_nextp.at(vtx);
            VL_PREFETCH_RW(m_headp);     // 预取下一个元素
            m_nextp.at(vtx) = nullptr; // 标记已出队
            f(vtx);
        }
    }
};
```

**关键细节**：
- **sentinel 技巧**：用 `this` 的地址作为链表尾哨兵，保证所有在链表中的顶点 `nextp != nullptr`——可以 O(1) 判断成员资格，且无条件预取。
- **`VL_PREFETCH_RW(m_headp)`**：在调用 `f(vtx)` 之前预取下一个工作项，隐藏缓存延迟。
- **与 `DfgUserMap` 结合**：成员检测和入队/出队都通过 `m_nextp` 完成，无需额外 hashmap。

---

## 3. 关键图操作（`V3Dfg.cpp`）

### 3.1 `clone()` — 深拷贝图

```cpp
// V3Dfg.cpp, lines 35-170
std::unique_ptr<DfgGraph> DfgGraph::clone() const {
    DfgGraph* const clonep = new DfgGraph{name()};
    std::unordered_map<const DfgVertex*, DfgVertex*> vtxp2clonep(size() * 2);
    // 按类型逐个克隆，然后重建边连接
    // ...
}
```

**复杂度**：O(|V| + |E|)，需要遍历所有顶点并重建边连接。深拷贝在并行优化中可用于：
- 给每个 worker 一个独立的子图副本（避免同步）。
- 保存原始图用于回滚或比较优化前后结果。

### 3.2 `mergeGraphs()` — 多图合并

```cpp
// V3Dfg.cpp, lines 172-230
void DfgGraph::mergeGraphs(std::vector<std::unique_ptr<DfgGraph>>&& otherps) {
    // AstVarScope::user2p() -> 对应 DfgVertexVar* 在 'this' 图中的映射
    const VNUser2InUse user2InUse;
    for (DfgVertexVar& vtx : m_varVertices) vtx.vscp()->user2p(&vtx);

    for (const auto& otherp : otherps) {
        // 变量去重：如果变量已存在，用 this 中的变量替换 other 中的变量
        for (DfgVertexVar* vtxp : otherp->m_varVertices.unlinkable()) {
            if (DfgVertexVar* const altp = vtxp->vscp()->user2u().to<DfgVertexVar*>()) {
                vtxp->replaceWith(altp);          // 重连所有 sink
                VL_DO_DANGLING(vtxp->unlinkDelete(*otherp), vtxp);
            } else {
                vtxp->vscp()->user2p(vtxp);       // 注册新变量
            }
        }
        // 通过 splice 将 other 的链表接到 this 上（O(1)）
        m_varVertices.splice(m_varVertices.end(), otherp->m_varVertices);
        // ... 对 ast, const, op 同样处理
    }
}
```

**多线程启示**：`mergeGraphs` 是**并行优化的关键粘合剂**——先并行处理多个独立子图，再串行合并结果。合并过程使用 `splice`（链表 O(1) 拼接）和 `replaceWith`（重连边），效率很高。

### 3.3 `splitIntoComponents()` — 弱连通分量分割

```cpp
// V3Dfg.h, lines 250-255
std::vector<std::unique_ptr<DfgGraph>>
splitIntoComponents(const std::string& label) VL_MT_DISABLED;
```

**作用**：将图拆分为互不连通的独立子图，同时移除与任何变量弱连通的孤立顶点。

### 3.4 `extractCyclicComponents()` — 环状子图提取

```cpp
// V3Dfg.h, lines 260-270
std::vector<std::unique_ptr<DfgGraph>>
extractCyclicComponents(const std::string& label) VL_MT_DISABLED;
```

**作用**：提取包含强连通分量（SCC）的环状子图，保留原图中的 DAG 部分。返回的子图至少弱连通，且保证包含至少一个 SCC。提取后，原图变为无环（DAG）。

**多线程关键**：这是**组件级并行化的基础**——环状组件和 DAG 组件可以分别处理，多个独立的 DAG 组件之间完全无依赖，可以并行优化。

---

## 4. AST ↔ DFG 转换

### 4.1 `V3DfgAstToDfg.cpp` — AST 转 DFG

```cpp
// V3DfgAstToDfg.cpp, lines 90-180
class AstToDfgVisitor final : public VNVisitor {
    DfgGraph& m_dfg;
    V3DfgAstToDfgContext& m_ctx;
    AstScope* m_scopep = nullptr;

    bool convert(AstAlways* nodep) {
        // 处理组合逻辑（ALWAYS_COMB, CONT_ASSIGN）
        // 构建 CFG（控制流图）
        std::unique_ptr<CfgGraph> cfgp = CfgGraph::build(nodep->stmtsp());
        // 收集写入和读取的变量
        // 创建 DfgLogic 顶点，连接输入/输出
    }
};
```

**关键细节**：
- 使用 `AstVarScope::user2()` 和 `user3()` 作为节点状态（通过 `VNUser2InUse` RAII 管理）。
- 只处理组合逻辑（`AstAlways` 无 sensitivity tree 或 `CONT_ASSIGN`），时序逻辑直接 `markReferenced` 并跳过。
- `DfgLogic` 顶点暂存整个 AST 子树，后续由 `synthesize` 拆成原语操作。

### 4.2 `V3DfgDfgToAst.cpp` — DFG 转 AST

```cpp
// V3DfgDfgToAst.cpp, lines 120-200
class DfgToAstVisitor final : DfgVisitor {
    AstNodeExpr* m_resultp = nullptr;

    AstNodeExpr* convertDfgVertexToAstNodeExpr(DfgVertex* vtxp) {
        iterate(vtxp);  // 递归访问
        return m_resultp;
    }

    // 为有多个 sink 的顶点或顶层的变量创建临时变量
    void createAssignment(FileLine* flp, AstNodeExpr* lhsp, DfgVertex* driverp) {
        AstNodeExpr* rhsp = convertDfgVertexToAstNodeExpr(driverp);
        // ... 创建 AssignW 或 Assign
    }
};
```

**关键细节**：
- 递归渲染 DFG 为 AST 表达式。遇到 `DfgVertexVar`（存储位置）或多 sink 的顶点时停止递归，生成赋值语句。
- `getCombActive` 会复用已有的 `AstActive`（组合逻辑敏感树），避免重复创建。

---

## 5. 优化器编排（`V3DfgOptimizer.cpp`）

### 5.1 完整优化流水线

```cpp
// V3DfgOptimizer.cpp, lines 80-140
void optimize(DfgGraph& dfg) {
    V3DfgPasses::removeUnobservable(dfg, m_ctx);        // 移除不可观测变量
    V3DfgPasses::synthesize(dfg, m_ctx);                   // 合成 DfgLogic 为原语
    
    std::vector<std::unique_ptr<DfgGraph>> cyclicComps
        = dfg.extractCyclicComponents("cyclic");
    
    // 尝试打破循环
    if (v3Global.opt.fDfgBreakCycles()) {
        for (auto it = cyclicComps.begin(); it != cyclicComps.end();) {
            auto result = V3DfgPasses::breakCycles(**it, m_ctx);
            // ... 如果成功转 DAG，移到 madeAcyclicComponents
        }
    }
    dfg.mergeGraphs(std::move(madeAcyclicComponents));
    
    V3DfgPasses::removeSelects(dfg, m_ctx.m_removeSelectsContext);
    for (auto& cp : cyclicComps) V3DfgPasses::removeSelects(*cp, ...);
    
    std::vector<std::unique_ptr<DfgGraph>> acyclicComps
        = dfg.splitIntoComponents("acyclic");
    
    // ========== 组件级独立优化（当前串行）==========
    for (auto& cp : acyclicComps) V3DfgPasses::inlineVars(*cp);
    for (auto& cp : acyclicComps) V3DfgPasses::cse(*cp, m_ctx.m_cseContext0);
    for (auto& cp : acyclicComps) V3DfgPasses::binToOneHot(*cp, m_ctx.m_binToOneHotContext);
    for (auto& cp : acyclicComps) V3DfgPasses::peephole(*cp, m_ctx.m_peepholeContext);
    for (auto& cp : acyclicComps) V3DfgPasses::pushDownSels(*cp, m_ctx.m_pushDownSelsContext);
    for (auto& cp : acyclicComps) V3DfgPasses::cse(*cp, m_ctx.m_cseContext1);
    // ============================================
    
    dfg.mergeGraphs(std::move(acyclicComps));
    dfg.mergeGraphs(std::move(cyclicComps));
    
    V3DfgPasses::regularize(dfg, m_ctx.m_regularizeContext);
}
```

**多线程关键洞察**：

上述代码中，**`acyclicComps` 的每个组件完全独立**——它们之间没有边连接，因此对一个组件的修改不会影响其他组件。当前代码用串行 `for` 循环逐个处理，但**完全可以并行化**。

**并行化方案**：
```cpp
// 串行（当前）
for (auto& cp : acyclicComps) V3DfgPasses::cse(*cp, ctx);

// 并行（可扩展）
// 每个 worker 线程处理一个组件，使用 thread-local context
parallel_for_each(acyclicComps, [&](auto& cp) {
    V3DfgPasses::cse(*cp, thread_local_ctx);
});
```

**需注意的点**：
- `m_ctx` 中的统计计数器（如 `m_eliminated`）需要原子化或用 per-thread counter 汇总。
- `DfgDataType` 的 intern 缓存（`reset()` 在优化结束后调用）是全局的，但 intern 操作本身是只读查表，线程安全。

---

## 6. 公共子表达式消除（`V3DfgCse.cpp`）

### 6.1 算法概述

CSE 通过**哈希 + 等价比较**识别并消除重复子表达式：

```cpp
// V3DfgCse.cpp, lines 180-250
V3DfgCse(DfgGraph& dfg, V3DfgCseContext& ctx) {
    std::unordered_map<V3Hash, std::vector<DfgVertex*>> verticesWithEqualHashes;
    verticesWithEqualHashes.reserve(dfg.size());

    // 预哈希变量、AST 引用、常量、CReset（这些都是唯一的）
    uint32_t varHash = 0;
    for (const DfgVertexVar& vtx : dfg.varVertices()) m_hashCache[vtx] = V3Hash{++varHash};
    for (const DfgVertexAst& vtx : dfg.astVertices()) m_hashCache[vtx] = V3Hash{++varHash};
    for (const DfgVertex& vtx : dfg.opVertices()) {
        if (vtx.is<DfgCReset>()) m_hashCache[vtx] = V3Hash{++varHash};
    }
    for (DfgConst* vtxp : dfg.constVertices().unlinkable()) {
        m_hashCache[vtxp] = vtxp->num().toHash() + varHash;
    }

    // 对操作顶点进行哈希桶比较
    for (DfgVertex* vtxp : dfg.opVertices().unlinkable()) {
        if (!vtxp->hasSinks()) { vtxp->unlinkDelete(dfg); continue; }
        std::vector<DfgVertex*>& vec = verticesWithEqualHashes[vertexHash(*vtxp)];
        bool replaced = false;
        for (DfgVertex* candidatep : vec) {
            if (vertexEquivalent(*candidatep, *vtxp)) {
                ++ctx.m_eliminated;
                vtxp->replaceWith(candidatep);          // 重连所有 sink 到 candidate
                VL_DO_DANGLING(vtxp->unlinkDelete(dfg), vtxp);
                replaced = true; break;
            }
        }
        if (!replaced) vec.push_back(vtxp);
    }
}
```

### 6.2 `vertexHash` — 递归哈希（带 memoization）

```cpp
// V3DfgCse.cpp, lines 100-120
V3Hash vertexHash(DfgVertex& vtx) {
    V3Hash& result = m_hashCache[vtx];
    if (!result.value()) {  // 未缓存
        V3Hash hash{vertexSelfHash(vtx)};
        if (!vtx.is<DfgVertexVar>()) {  // 变量自身定义自己，不递归
            hash += vtx.type();
            hash += vtx.size();
            vtx.foreachSource([&](DfgVertex& src) {
                hash += vertexHash(src);  // 递归
                return false;
            });
        }
        result = hash;
    }
    return result;
}
```

### 6.3 `vertexEquivalent` — 递归等价比较（带缓存）

```cpp
// V3DfgCse.cpp, lines 220-260
bool vertexEquivalent(const DfgVertex& a, const DfgVertex& b) {
    if (&a == &b) return true;
    if (a.type() != b.type()) return false;
    if (a.dtype() != b.dtype()) return false;
    if (a.nInputs() != b.nInputs()) return false;
    if (!vertexSelfEquivalent(a, b)) return false;

    const VertexPair key = (&a < &b) ? std::make_pair(&a, &b) : std::make_pair(&b, &a);
    uint8_t& result = m_equivalentCache[key];
    if (!result) {  // 未缓存
        const bool equal = [&]() {
            for (size_t i = 0; i < a.nInputs(); ++i) {
                if (!vertexEquivalent(*a.inputp(i), *b.inputp(i))) return false;
            }
            return true;
        }();
        result = (static_cast<uint8_t>(equal) << 1) | 1;  // 编码：bit0=已计算, bit1=结果
    }
    return result >> 1;
}
```

**复杂度分析**：
- 哈希计算：O(|V|)（每个顶点一次递归，但 memoized）
- 最坏情况比较：O(|V|²)（如果所有顶点哈希碰撞，需要两两比较）
- 实际中 Verilator 的 `V3Hash` 质量足够，碰撞率很低。

**多线程启示**：CSE 在**单个组件**内执行，不同组件之间无共享顶点，因此组件级并行 CSE 是安全的。但如果想在**单个组件内**并行化 CSE，需要：
- 分治策略：将图按拓扑序分区，worker 处理不同层的顶点。
- 或：先计算所有顶点的 hash（可并行），再按 hash 桶分组并行比较。

---

## 7. 多线程相关代码扫描

### 7.1 `VL_MT_DISABLED` 标记

所有 6 个文件都包含 `// VL_MT_DISABLED_CODE_UNIT`，且大量方法标记为 `VL_MT_DISABLED`：

```cpp
// V3Dfg.h
DfgGraph(const string& name) VL_MT_DISABLED;
~DfgGraph() VL_MT_DISABLED;
clone() const VL_MT_DISABLED;
mergeGraphs(...) VL_MT_DISABLED;
splitIntoComponents(...) VL_MT_DISABLED;
extractCyclicComponents(...) VL_MT_DISABLED;

DfgVertex(...) VL_MT_DISABLED;
~DfgVertex() VL_MT_DISABLED = default;

// V3Dfg.cpp
DfgVertex::fanout() const VL_MT_DISABLED;
DfgVertex::getResultVar() VL_MT_DISABLED;
DfgVertex::scopep(...) VL_MT_DISABLED;
DfgVertex::unlinkDelete(...) VL_MT_DISABLED;
```

**含义**：`VL_MT_DISABLED` 是 Verilator 的宏，表示"该函数在仿真时**不应被多线程调用**。这通常是因为：
1. 函数操作非线程安全的数据结构（如 `V3List` 的修改）。
2. 函数在编译时（非仿真时）执行，而编译时 Verilator 是单线程的。
3. 函数依赖全局状态（如 `AstVarScope::user2p()`）。

### 7.2 无显式同步原语

在整个 6 个文件中，**没有发现任何 `std::mutex`、`std::atomic`、`std::barrier`、线程池或锁相关的代码**。这是因为整个 DFG 系统运行在编译时，Verilator 的编译阶段目前不使用多线程。

### 7.3 隐含的并行化潜力

虽然没有显式多线程代码，但架构上存在多处并行化潜力：

| 位置 | 并行化潜力 | 难度 |
|------|-----------|------|
| `acyclicComps` 的逐个优化 | 组件间完全独立，天然并行 | 低 |
| `cyclicComps` 的逐个优化 | 组件间完全独立，天然并行 | 低 |
| `breakCycles` 的逐个调用 | 组件间完全独立 | 低 |
| `removeSelects` 在 `acyclicComps` 上 | 组件间独立 | 低 |
| `vertexHash` 计算 | 无依赖的顶点子集可并行 | 中 |
| `dfgGraphCollectCone`（BFS/DFS） | 从多个种子并行出发 | 中 |
| `clone()` | 各类型顶点独立克隆 | 中 |
| `synthesize` | 每个 `DfgLogic` 内部可并行 | 中 |

---

## 8. 对 RTL 仿真器多线程化的启示

### 8.1 编译阶段并行化：最直接的收益

Verilator 的 DFG 优化是**编译时重度计算**的一部分。对大型设计，DFG 图可能有数百万顶点，优化耗时显著。组件级并行化可直接提升编译速度：

```cpp
// 当前：串行
for (auto& cp : acyclicComps) {
    V3DfgPasses::inlineVars(*cp);
    V3DfgPasses::cse(*cp, ctx);
    V3DfgPasses::peephole(*cp, ctx);
    // ...
}

// 并行化后：每个组件一个任务
std::vector<std::future<void>> futures;
for (auto& cp : acyclicComps) {
    futures.push_back(std::async(std::launch::async, [&]() {
        V3DfgPasses::inlineVars(*cp);
        V3DfgPasses::cse(*cp, per_thread_ctx);
        V3DfgPasses::peephole(*cp, per_thread_ctx);
        // ...
    }));
}
for (auto& f : futures) f.wait();
```

**实施要点**：
- 统计上下文 `m_ctx` 需要拆分为 per-thread 累加器，最后合并。
- `DfgDataType::reset()` 和全局 intern 池是只读查表，无需同步。
- 调试 dump 输出需要串行化，或用独立文件。

### 8.2 `DfgUserMap` 的并行化扩展

当前 `DfgUserMap` 限制一个图同时只能有一个映射在使用。要支持多线程 worker 同时操作一个图的不同区域，可以：
- **方案 1：子图隔离**：每个 worker 拿到独立的子图（通过 `splitIntoComponents` + `clone`），各自拥有独立的 UserMap。
- **方案 2：线程本地存储槽**：扩展 `DfgVertex` 的 `m_userStorage` 为 `std::array<void*, N_THREADS>` 或 `thread_local` 索引的外部数组。
- **方案 3：并发 hashmap**：放弃零开销优化，用 `tbb::concurrent_hash_map` 或 `absl::flat_hash_map`（per-thread shard）。

**推荐方案 1**：因为组件本来就是独立的，不需要共享图。

### 8.3 `DfgWorklist` 的并行化

当前 `DfgWorklist` 使用单链表 + 预取，适合单线程。多线程场景下：
- 使用 **work-stealing deque**（如 `boost::lockfree::deque` 或 `tbb::concurrent_queue`）。
- 或：每个 worker 维护自己的工作列表，处理完后再合并结果（bulk-synchronous 并行）。

### 8.4 对 RTL 仿真器多线程内核的间接启示

虽然 DFG 本身不直接参与仿真调度，但 DFG 优化的输出（优化后的 AST）直接决定了仿真代码的结构：
- **组件分割**与 Verilator 的 **多线程仿真分区（V3Partition）**有相似逻辑：都是将大图拆分为独立子图。
- DFG 的 `splitIntoComponents` 是**静态分析**（编译时），而 V3Partition 是**动态调度**（仿真时）。两者可以共享图分割算法。
- CSE 消除的重复子表达式减少了仿真代码的冗余计算，间接减少了仿真线程的负载。
- DFG 的 `isCheaperThanLoad()` 启发式（判断重新计算是否比从内存加载更便宜）对多线程仿真有启发：在 NUMA 架构下，跨 socket 的内存加载代价极高，可能重新计算更划算。

### 8.5 工程实践要点

1. **V3List 的线程安全性**：`V3List` 是侵入式链表，修改操作（`linkFront`, `unlink`, `splice`）非线程安全。并行化时必须保证操作的是不同链表的节点，或使用锁保护。
2. **RAII 状态管理**：`VNUser1InUse`, `VNUser2InUse` 等 RAII 对象管理 AST 节点状态。并行化时，每个 worker 需要独立的节点状态域，或者使用 lock-free 的标记位。
3. **统计上下文**：`V3DfgCseContext::m_eliminated` 等统计字段需要 `std::atomic<uint64_t>` 或 per-thread 累加。
4. **内存分配**：大量 `new DfgVertex` / `new DfgEdge` 使用默认分配器。并行化时建议用 per-thread arena allocator（如 `mimalloc` 的线程本地堆）减少争用。

---

## 关键代码片段摘录

### DfgGraph 组件分割（`V3Dfg.h:250-270`）

```cpp
// 将图分割为独立组件（无互连边）
std::vector<std::unique_ptr<DfgGraph>>
splitIntoComponents(const std::string& label) VL_MT_DISABLED;

// 提取环状子图（包含至少一个 SCC）
std::vector<std::unique_ptr<DfgGraph>>
extractCyclicComponents(const std::string& label) VL_MT_DISABLED;
```

### DFG 优化流水线（`V3DfgOptimizer.cpp:80-140`）

```cpp
// 当前串行组件优化
for (auto& cp : acyclicComps) V3DfgPasses::cse(*cp, m_ctx.m_cseContext0);
for (auto& cp : acyclicComps) V3DfgPasses::peephole(*cp, m_ctx.m_peepholeContext);
// 每个组件独立，天然可并行
```

### DfgUserMap 零开销映射（`V3Dfg.h:340-430`）

```cpp
// 利用顶点自身的 m_userStorage 和 m_userGeneration，避免外部 hashmap
T_Value& operator[](const DfgVertex& vtx) {
    T_Value* const storagep = reinterpret_cast<T_Value*>(&vtx.m_userStorage);
    if (vtx.m_userGeneration != m_currentGeneration) {
        new (storagep) T_Value{};
        vtx.m_userGeneration = m_currentGeneration;
    }
    return *storagep;
}
```

### DfgWorklist 预取优化（`V3Dfg.h:460-510`）

```cpp
// 处理工作列表时预取下一个元素
while (m_headp != m_sentinelp) {
    DfgVertex& vtx = *m_headp;
    m_headp = m_nextp.at(vtx);
    VL_PREFETCH_RW(m_headp);  // 硬件预取提示
    m_nextp.at(vtx) = nullptr;
    f(vtx);
}
```

---

## 相关链接

- [V3Dfg.h 源码](https://github.com/verilator/verilator/blob/master/src/V3Dfg.h)
- [V3Dfg.cpp 源码](https://github.com/verilator/verilator/blob/master/src/V3Dfg.cpp)
- [V3DfgAstToDfg.cpp 源码](https://github.com/verilator/verilator/blob/master/src/V3DfgAstToDfg.cpp)
- [V3DfgDfgToAst.cpp 源码](https://github.com/verilator/verilator/blob/master/src/V3DfgDfgToAst.cpp)
- [V3DfgOptimizer.cpp 源码](https://github.com/verilator/verilator/blob/master/src/V3DfgOptimizer.cpp)
- [V3DfgCse.cpp 源码](https://github.com/verilator/verilator/blob/master/src/V3DfgCse.cpp)
- [Verilator Internals 文档](https://verilator.org/guide/internals.html)

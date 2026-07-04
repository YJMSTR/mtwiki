---
title: "V3MergeCond 条件合并优化"
source_url: "https://github.com/verilator/verilator/tree/master/src/V3MergeCond.cpp"
source_type: "github-code"
author: "Verilator Team"
date: ""
tags: ["verilator", "multithreading", "optimization", "AST-pass", "conditional-merge", "code-motion"]
keywords: ["V3MergeCond", "条件合并", "三元操作符", "if-语句转换", "代码运动", "StmtProperties", "CodeMotionAnalysisVisitor", "CodeMotionOptimizeVisitor", "MergeCondVisitor"]
capture_date: "2026-07-05"
---

# V3MergeCond 条件合并优化深度分析

## 来源

- **V3MergeCond.h**: https://github.com/verilator/verilator/blob/master/src/V3MergeCond.h
- **V3MergeCond.cpp**: https://github.com/verilator/verilator/blob/master/src/V3MergeCond.cpp
- 类型: Verilator 源码 (编译时 AST 优化 Pass)
- 作者: Wilson Snyder / Verilator Team
- 许可证: LGPL-3.0-only OR Artistic-2.0

## 摘要

V3MergeCond 是 Verilator 编译管道中的一个关键优化 Pass，负责将**相同条件**的连续三元条件操作符 (`cond ? then : else`) 合并为 `if` 语句。该 Pass 还实现了**代码运动（Code Motion）**分析，通过重新排序语句来最大化可合并的条件组数量。虽然这是一个**单线程编译时 Pass**（标记为 `VL_MT_DISABLED`），但它生成的代码结构对多线程 RTL 仿真的分支预测效率和缓存局部性有深远影响。

## 关键要点

1. **条件合并转换**：将相同条件的连续 `?:` 三元操作符合并为 `if/else` 块，避免 C++ 编译器在优化这类模式时耗时过长。
2. **代码运动（Code Motion）**：通过 StmtProperties 分析语句间的数据依赖，在保持语义等价的前提下重新排序语句，使更多条件合并成为可能。
3. **复杂度控制**：代码运动的最大距离限制为 500 条语句（`MAX_DISTANCE = 500`），保证 `O(N)` 而非 `O(N²)` 的复杂度。
4. **副作用与公共状态感知**：通过 fence、sideEffect、implPubRd/implPubWr 等属性精确控制语句重排序的合法性。
5. **单线程编译时执行**：`mergeAll` 标记为 `VL_MT_DISABLED`，包含 `V3PchAstNoMT.h` 头文件，说明这是纯编译时优化，不直接涉及运行时多线程。
6. **对多线程仿真的间接性能影响**：合并后的 `if` 语句改善分支预测、减少重复条件求值、提高缓存局部性，对后续多线程执行性能有显著正面影响。

---

## 文件结构总览

| 文件 | 行数 | 角色 | 多线程相关 |
|------|------|------|------------|
| `V3MergeCond.h` | ~30 | 对外接口头文件 | `VL_MT_DISABLED` 标记 |
| `V3MergeCond.cpp` | ~750 | 核心实现 | 单线程 AST 遍历；代码运动分析 |

---

## V3MergeCond.h 分析

### 接口定义（V3MergeCond.h:17-23）

```cpp
// V3MergeCond.h
class V3MergeCond final {
public:
    static void mergeAll(AstNetlist* nodep) VL_MT_DISABLED;
};
```

**关键观察**：
- `VL_MT_DISABLED` 宏标记明确表示此函数**不能在多线程上下文中被调用**。
- 这是 Verilator 编译管道中的标准做法：AST 变换 Pass 通常在**单线程编译阶段**串行执行，确保 AST 修改的线程安全。
- 对于 RTL 仿真器多线程化设计而言，这揭示了一个重要原则：**编译时优化与运行时多线程执行是严格分离的**。编译时 Pass 可以激进地修改 AST，因为它们在运行时多线程启动之前就已经完成。

---

## V3MergeCond.cpp 核心实现分析

### 1. 转换目标（V3MergeCond.cpp:22-68）

```cpp
// V3MergeCond.cpp:22-68
// V3BranchMerge's Transformations:
//
//    Look for sequences of assignments with ternary conditional on the right
//    hand side with the same condition:
//      lhs0 = cond ? then0 : else0;
//      lhs1 = cond ? then1 : else1;
//      lhs2 = cond ? then2 : else2;
//
//    This seems to be a common pattern and can make the C compiler take a
//    long time when compiling it with optimization. For us it's easy and fast
//    to convert this to 'if' statements because we know the pattern is common:
//      if (cond) {
//          lhs0 = then0;
//          lhs1 = then1;
//          lhs2 = then2;
//      } else {
//          lhs0 = else0;
//          lhs1 = else1;
//          lhs2 = else2;
//      }
```

**为什么这个转换对多线程仿真重要**：
- 未合并的 `?:` 操作符序列在生成的 C++ 代码中会产生**大量独立的分支指令**。
- 每次求值 `cond ? then : else` 时，CPU 分支预测器需要独立判断 `cond` 的走向。
- 合并为 `if/else` 后，**只有一个分支点**，分支预测成功率大幅提高，降低流水线刷新（pipeline flush）开销。
- 在多线程环境下，分支预测失误的代价会被放大——因为每个线程都可能独立遭遇预测失误。

---

### 2. StmtProperties 数据结构（V3MergeCond.cpp:101-126）

```cpp
// V3MergeCond.cpp:101-126
struct StmtProperties final {
    AstNodeExpr* m_condp = nullptr;      // 条件表达式指针（如果是条件语句）
    std::set<const AstVar*> m_rdVars;    // 本语句读取的变量集合
    std::set<const AstVar*> m_wrVars;    // 本语句写入的变量集合
    bool m_isFence = false;              // 不可跨越的屏障语句
    bool m_sideEffect = false;           // 可能有副作用（但不访问模型状态）
    bool m_implPubRd = false;            // 可能隐式读取公共状态（非通过 VarRef）
    bool m_implPubWr = false;            // 可能隐式写入公共状态（非通过 VarRef）
    bool m_explPubRef = false;           // 显式通过 VarRef 引用公共状态
    AstNodeStmt* m_prevWithSameCondp = nullptr; // 同列表中前一个相同条件的语句

    bool writesConditionVar(bool condPubWritable) const {
        for (const AstVar* const varp : m_wrVars) {
            if (varp->user1()) return true;  // 条件变量被写入
        }
        if (condPubWritable && m_implPubWr) return true;
        return false;
    }
};
```

**对多线程设计启示**：
- `m_rdVars` / `m_wrVars` 使用 `std::set<const AstVar*>` 存储**读写集合**，这是编译时数据流分析的基础设施。
- 这种**读写集（Read/Write Set）**分析模式是后续多线程分区（partitioning）算法的核心前提——必须知道每个语句读写哪些变量，才能判断语句能否并行执行。
- `m_isFence` / `m_sideEffect` / `m_implPubRd` / `m_implPubWr` 构成了**语句安全重排序**的完整判断体系。类似地，多线程分区也需要判断"哪些语句可以放在不同线程中安全执行"。
- `writesConditionVar` 检查条件变量是否被后续语句修改——这直接对应多线程中的**数据依赖性**：如果条件变量的值在评估期间可能改变，则不能进行静态优化。

---

### 3. areDisjoint 函数（V3MergeCond.cpp:84-99）

```cpp
// V3MergeCond.cpp:84-99
bool areDisjoint(const std::set<const AstVar*>& a, const std::set<const AstVar*>& b) {
    if (a.empty() || b.empty()) return true;
    const auto endA = a.end();
    const auto endB = b.end();
    auto itA = a.begin();
    auto itB = b.begin();
    while (true) {
        if (*itA == *itB) return false;
        if (std::less<const AstVar*>{}(*itA, *itB)) {
            itA = std::lower_bound(++itA, endA, *itB);
            if (itA == endA) return true;
        } else {
            itB = std::lower_bound(++itB, endB, *itA);
            if (itB == endB) return true;
        }
    }
}
```

**算法分析**：
- 两个有序集合的交集检测，利用 `std::lower_bound` 进行**跳跃式搜索**，最坏复杂度 `O(min(|a|, |b|))`。
- 这是判断两条语句是否存在**数据冲突（data hazard）**的核心函数——若读写集合有交集，则语句不可交换顺序。
- 在多线程分区算法中，类似的"读写集冲突检测"是决定语句能否分配到不同线程的**关键判定**。这里使用的是编译时的精确分析，而运行时多线程通常需要更保守的判定（如基于变量粒度的锁或原子操作）。

---

### 4. CodeMotionAnalysisVisitor 分析 Visitor（V3MergeCond.cpp:136-260）

```cpp
// V3MergeCond.cpp:136-260
class CodeMotionAnalysisVisitor final : public VNVisitorConst {
    // NODE STATE
    // AstNodeStmt::user3   -> StmtProperties
    // AstNodeExpr::user3   -> AstNodeStmt*: 条件节点上设置，指向同列表中最后一个
    //                         遇到该条件的条件语句
    // AstNode::user4       -> Used by V3Hasher

    StmtPropertiesAllocator& m_stmtProperties;
    V3Hasher m_hasher;
    std::vector<V3DupFinder> m_stack;  // 条件表达式去重查找器栈
    StmtProperties* m_propsp = nullptr;

    void analyzeStmt(AstNodeStmt* nodep, bool tryCondMatch) {
        VL_RESTORER(m_propsp);
        StmtProperties* const outerPropsp = m_propsp;
        m_propsp = &m_stmtProperties(nodep);

        // 提取条件表达式
        if (AstNodeExpr* const condp = extractCondition(nodep)) {
            m_propsp->m_condp = condp;
            if (tryCondMatch) {
                V3DupFinder& dupFinder = m_stack.back();
                const V3DupFinder::iterator& dit = dupFinder.findDuplicate(condp);
                if (dit == dupFinder.end()) {
                    dupFinder.insert(condp);
                    condp->user3p(nodep);
                } else {
                    AstNodeExpr* const firstp = VN_AS(dit->second, NodeExpr);
                    m_propsp->m_prevWithSameCondp = static_cast<AstNodeStmt*>(firstp->user3p());
                    firstp->user3p(nodep);  // 更新"最后遇到"指针
                }
            }
        }

        analyzeNode(nodep);

        // 向父语句传播属性
        if (outerPropsp) {
            outerPropsp->m_rdVars.insert(m_propsp->m_rdVars.cbegin(), ...);
            outerPropsp->m_wrVars.insert(m_propsp->m_wrVars.cbegin(), ...);
            outerPropsp->m_isFence |= m_propsp->m_isFence;
            outerPropsp->m_sideEffect |= m_propsp->m_sideEffect;
            // ... 更多标志传播
        }
    }
```

**关键设计模式**：
- **Visitor 模式 + 节点属性分配器**：`AstUser3Allocator` 将临时属性绑定到 AST 节点，避免修改 AST 结构本身。这是 Verilator 编译管道的通用模式，也适用于多线程分析阶段。
- **V3DupFinder 条件去重**：使用 `V3DupFinder`（基于哈希的表达式去重器）在 `O(1)` 平均时间内判断两个条件表达式是否相同。这是 `O(N)` 整体复杂度的保证。
- **属性向上传播**：嵌套语句的读写集向父语句传播。例如，一个 `if` 语句的读写集是其 then/else 分支读写集的并集。这种**层次化属性传播**与多线程分区中"区域（region）读写集"的计算逻辑完全一致。
- **user3p 链式指针**：`condp->user3p(nodep)` 在条件表达式节点上记录"同列表中最后遇到该条件的语句"，形成隐式的链表结构，使得后续优化阶段能快速找到可合并的配对。

---

### 5. areSwappable 函数（V3MergeCond.cpp:280-305）

```cpp
// V3MergeCond.cpp:280-305
bool areSwappable(const AstNodeStmt* ap, const AstNodeStmt* bp) const {
    const StmtProperties& aProps = m_stmtProperties(ap);
    const StmtProperties& bProps = m_stmtProperties(bp);

    // 不可跨越屏障
    if (aProps.m_isFence) return false;
    if (bProps.m_isFence) return false;

    // 两个都有副作用的语句不能交换
    if (aProps.m_sideEffect && bProps.m_sideEffect) return false;

    // 公共状态写-读 / 读-写冲突
    const bool bPubRef = bProps.m_implPubWr || bProps.m_implPubRd || bProps.m_explPubRef;
    if (aProps.m_implPubWr && bPubRef) return false;
    const bool aPubRef = aProps.m_implPubWr || aProps.m_implPubRd || aProps.m_explPubRef;
    if (aPubRef && bProps.m_implPubWr) return false;

    // 精确数据依赖冲突
    if (!areDisjoint(aProps.m_rdVars, bProps.m_wrVars)) return false;  // a reads, b writes
    if (!areDisjoint(bProps.m_rdVars, aProps.m_wrVars)) return false;  // b reads, a writes
    if (!areDisjoint(aProps.m_wrVars, bProps.m_wrVars)) return false;  // 写写冲突

    return true;
}
```

**与多线程分区的映射**：
- `areSwappable` 的判定逻辑与判断"两条语句能否并行执行"的判定逻辑高度相似。
- 差异仅在于：代码运动是**改变顺序**，而多线程并行是**重叠执行**。两者都需要保证**数据依赖关系**不被破坏。
- `m_isFence` 对应多线程中的**同步点/屏障**——不可被重排序或跨越。
- `m_sideEffect` 对应多线程中的**I/O 操作或系统调用**——通常需要串行化或特殊同步。
- `m_implPubWr` / `m_implPubRd` 对应多线程中的**共享内存访问**——需要原子操作或锁保护。
- 这个函数展示了 Verilator 在**单线程编译阶段**就已经建立了完整的数据依赖分析基础设施，这些基础设施可以直接复用于多线程分区决策。

---

### 6. CodeMotionOptimizeVisitor 代码运动优化（V3MergeCond.cpp:310-390）

```cpp
// V3MergeCond.cpp:310-390
class CodeMotionOptimizeVisitor final : public VNVisitor {
    static constexpr unsigned MAX_DISTANCE = 500;  // O(N) 复杂度控制

    void visit(AstNodeStmt* nodep) override {
        if (nodep->user4SetOnce()) return;  // 只处理一次
        iterateChildren(nodep);

        AstNodeStmt* prevp = m_stmtProperties(nodep).m_prevWithSameCondp;
        if (!prevp) return;  // 没有相同条件的前驱

        // 尝试将 nodep 向后移动，靠近 prevp
        if (AstNodeStmt* predp = VN_CAST(nodep->backp(), NodeStmt)) {
            for (unsigned i = MAX_DISTANCE; i; --i) {
                if (predp == prevp) break;  // 已到达目标位置
                AstNodeStmt* const backp = VN_CAST(predp->backp(), NodeStmt);
                if (!backp) break;
                if (!areSwappable(predp, nodep)) break;
                predp = backp;
            }
            if (nodep->backp() != predp) {
                nodep->unlinkFrBack();
                predp->addNextHere(nodep);
                if (predp == prevp) return;  // 成功合并
            }
        }

        // 如果 nodep 无法完全靠近 prevp，尝试将 prevp 向前移动靠近 nodep
        for (AstNodeStmt* currp = nodep; prevp;
             currp = prevp, prevp = m_stmtProperties(currp).m_prevWithSameCondp) {
            if (AstNodeStmt* succp = VN_CAST(prevp->nextp(), NodeStmt)) {
                for (unsigned i = MAX_DISTANCE; --i;) {
                    if (succp == currp) break;
                    AstNodeStmt* const nextp = VN_CAST(succp->nextp(), NodeStmt);
                    if (!nextp) break;
                    if (!areSwappable(prevp, succp)) break;
                    succp = nextp;
                }
                if (prevp->nextp() != succp) {
                    prevp->unlinkFrBack();
                    succp->addHereThisAsNext(prevp);
                }
            }
        }
    }
```

**算法分析**：
- **双向代码运动**：先尝试将"后面的条件语句"向后移动（bubble sort 风格），如果失败，再尝试将"前面的条件语句"向前移动。这种双向策略最大化了可合并的配对数量。
- **MAX_DISTANCE = 500 的复杂度控制**：这是关键工程决策。没有此限制，最坏情况下（N/2 个唯一条件，后跟 N/2 个相同条件），每个节点需要移动 N/2 距离，总复杂度 `O(N²)`。限制距离后，每个节点最多移动 500 步，总复杂度严格为 `O(N)`。
- **对多线程的启示**：这种"有限范围滑动窗口"的策略可以直接迁移到多线程的**局部调度优化**中——在有限窗口内寻找可并行化的语句组，而非全局优化。
- **unlinkFrBack() / addNextHere() / addHereThisAsNext()**：这些 AST 节点操作是**单线程安全的**（因为整个 Pass 是单线程执行的），在多线程环境下修改 AST 需要更复杂的同步机制（如工作窃取 + 原子指针操作）。

---

### 7. MergeCondVisitor::process 主处理流程（V3MergeCond.cpp:472-505）

```cpp
// V3MergeCond.cpp:472-505
void process(AstNode* nodep) {
    std::queue<AstNode*> workQueue;
    m_workQueuep = &workQueue;
    m_workQueuep->push(nodep);

    do {
        // 每轮迭代设置独立的 user* 状态
        const VNUser1InUse user1InUse;
        const VNUser2InUse user2InUse;
        const VNUser3InUse user3InUse;
        StmtPropertiesAllocator stmtProperties;
        m_stmtPropertiesp = &stmtProperties;

        AstNode* currp = m_workQueuep->front();
        m_workQueuep->pop();

        // 1. 分析阶段：构建每个语句的属性
        CodeMotionAnalysisVisitor::analyze(currp, stmtProperties);
        // 2. 代码运动阶段（可选，由 --f-merge-cond-motion 控制）
        if (v3Global.opt.fMergeCondMotion()) {
            currp = CodeMotionOptimizeVisitor::optimize(currp, stmtProperties);
        }
        // 3. 合并阶段：遍历并执行条件合并
        iterateAndNextNull(currp);
        // 4. 清理
        if (m_mgFirstp) mergeEnd();
        m_stmtPropertiesp = nullptr;
    } while (!m_workQueuep->empty());
}
```

**执行模型分析**：
- **BFS 工作队列**：`std::queue<AstNode*>` 实现了广度优先的处理策略。合并一个 `if` 语句后，其 then/else 分支会被加入队列，供后续轮次处理。
- **每轮迭代的独立状态**：`VNUser1InUse` / `VNUser2InUse` / `VNUser3InUse` 是 RAII 对象，确保每轮迭代开始时 AST 节点的 user 字段是干净的。这是 Verilator 编译管道的**标准状态管理范式**——避免手动清理的遗漏风险。
- **三阶段流水线**：`分析 → 代码运动 → 合并` 构成了完整的编译优化流水线。这个模式可以映射到多线程的**分析-变换-优化（Analysis-Transform-Optimization）**范式。
- 注意：`fMergeCondMotion()` 由命令行选项控制，说明代码运动是**可选的额外优化**，其收益需要与编译时间成本权衡。

---

### 8. mergeEnd 合并结束处理（V3MergeCond.cpp:575-680）

```cpp
// V3MergeCond.cpp:575-680
void mergeEnd() {
    UASSERT(m_mgFirstp, "mergeEnd without list");

    // 丢弃首尾的"廉价节点"（它们只是为了扩展合并范围而被加入）
    while (m_mgFirstp->user2() && m_mgFirstp != m_mgLastp) { ... }
    while (m_mgLastp->user2() && m_mgFirstp != m_mgLastp) { ... }

    AstNodeIf* recursivep = nullptr;

    if (m_mgFirstp != m_mgLastp) {
        // 实际执行合并：创建 AstIf 节点，将列表"解压缩"到 then/else 分支
        m_mgCondp = m_mgCondp->cloneTreePure(false);
        AstIf* const resultp = new AstIf{m_mgCondp->fileline(), m_mgCondp};
        m_mgFirstp->addHereThisAsNext(resultp);

        size_t nLikely = 0, nUnlikely = 0;
        AstNode* nextp = m_mgFirstp;
        do {
            AstNode* const currp = nextp;
            nextp = currp != m_mgLastp ? currp->nextp() : nullptr;
            currp->unlinkFrBack();

            if (AstNodeAssign* const assignp = VN_CAST(currp, NodeAssign)) {
                AstNodeExpr* const rhsp = assignp->rhsp()->unlinkFrBack();
                AstNodeAssign* const thenp = assignp;
                AstNodeAssign* const elsep = assignp->cloneTree(false);
                thenp->rhsp(foldAndUnlink(rhsp, true));   // 条件为真分支
                elsep->rhsp(foldAndUnlink(rhsp, false));  // 条件为假分支
                resultp->addThensp(thenp);
                resultp->addElsesp(elsep);
                VL_DO_DANGLING(rhsp->deleteTree(), rhsp);
            } else {
                // 合并 AstNodeIf：将分支内容移动到新 if 下
                AstNodeIf* const ifp = VN_AS(currp, NodeIf);
                if (AstNode* const listp = ifp->thensp()) {
                    resultp->addThensp(listp->unlinkFrBackWithNext());
                }
                if (AstNode* const listp = ifp->elsesp()) {
                    resultp->addElsesp(listp->unlinkFrBackWithNext());
                }
                // 分支预测统计
                if (ifp->branchPred().likely()) ++nLikely;
                if (ifp->branchPred().unlikely()) ++nUnlikely;
                VL_DO_DANGLING(ifp->deleteTree(), ifp);
            }
        } while (nextp);

        // 统一分支预测
        if (nLikely && !nUnlikely) resultp->branchPred(VBranchPred::BP_LIKELY);
        if (!nLikely && nUnlikely) resultp->branchPred(VBranchPred::BP_UNLIKELY);

        // 将合并后的分支加入工作队列，供递归处理
        if (resultp->thensp()) m_workQueuep->push(resultp->thensp());
        if (resultp->elsesp()) m_workQueuep->push(resultp->elsesp());
    }
    // ... 重置状态
}
```

**合并逻辑详解**：
- **"解压缩"（Unzip）操作**：将列表中的每个语句拆分为 then/else 两个版本，放入 `AstIf` 的两个分支。这是**结构变换**的核心。
- **foldAndUnlink**：在分支中"折叠"条件表达式。例如 `lhs = cond ? a : b` 在 then 分支中变为 `lhs = a`，在 else 分支中变为 `lhs = b`。`cond` 本身被提取为 `if` 的条件。
- **分支预测传递**：合并多个 `if` 语句时，如果所有源 `if` 都标记为 `likely`，则合并后的 `if` 也标记为 `likely`。这对 C++ 编译器的分支预测提示（`__builtin_expect`）有直接影响，从而提升运行时性能。
- **递归处理**：`m_workQueuep->push(resultp->thensp())` 将新产生的分支加入队列，实现**自底向上的递归优化**。这保证了合并后的 `if` 内部还能继续合并更深的嵌套条件。

---

### 9. foldAndUnlink 表达式折叠（V3MergeCond.cpp:545-573）

```cpp
// V3MergeCond.cpp:545-573
AstNodeExpr* foldAndUnlink(AstNodeExpr* rhsp, bool condTrue) {
    if (rhsp->sameTree(m_mgCondp)) {
        return new AstConst{rhsp->fileline(), AstConst::BitTrue{}, condTrue};
    } else if (const AstCond* const condp = extractCondFromRhs(rhsp)) {
        AstNodeExpr* const resp
            = condTrue ? condp->thenp()->unlinkFrBack()
                       : condp->elsep()->unlinkFrBack();
        if (condp == rhsp) return resp;
        if (const AstAnd* const andp = VN_CAST(rhsp, And)) {
            UASSERT_OBJ(andp->rhsp() == condp, rhsp, "Should not try to fold this");
            return new AstAnd{andp->fileline(), andp->lhsp()->cloneTreePure(false), resp};
        }
    } else if (const AstAnd* const andp = VN_CAST(rhsp, And)) {
        if (andp->lhsp()->sameTree(m_mgCondp)) {
            return condTrue ? maskLsb(andp->rhsp()->unlinkFrBack())
                            : new AstConst{rhsp->fileline(), AstConst::BitFalse{}};
        } else {
            UASSERT_OBJ(andp->rhsp()->sameTree(m_mgCondp), rhsp,
                        "AstAnd doesn't hold condition expression");
            return condTrue ? maskLsb(andp->lhsp()->unlinkFrBack())
                            : new AstConst{rhsp->fileline(), AstConst::BitFalse{}};
        }
    } else if (VN_IS(rhsp, ArraySel) || VN_IS(rhsp, WordSel) || VN_IS(rhsp, VarRef)
               || VN_IS(rhsp, Const)) {
        return rhsp->cloneTree(false);
    }
    rhsp->v3fatalSrc("Should not try to fold this during conditional merging");
    return nullptr;
}
```

**表达式折叠规则**：
- `cond ? true : false` → 根据分支替换为 `true` 或 `false` 常量
- `cond ? a : b` → then 分支取 `a`，else 分支取 `b`
- `cond & value` → 这是 V3Clean 插入的位掩码，then 分支取 `value & 1`（`maskLsb`），else 分支取 `0`
- 普通 `VarRef` / `Const` / `ArraySel` → 直接克隆到两个分支

---

## 多线程相关实现细节总结

### 直接观察：没有运行时同步机制

V3MergeCond 是一个**纯编译时 AST 变换 Pass**，文件中**没有任何**以下多线程同步原语：
- 无 `std::mutex`、`std::lock_guard`、`std::atomic`
- 无 `pthread_barrier`、`pthread_cond_t`
- 无 `std::thread`、`std::future`、`std::async`
- 无线程局部存储（TLS）
- 无内存屏障（memory fence）或 `std::atomic_thread_fence`

### 间接关联：编译时优化为运行时多线程铺路

| 编译时机制 | 对运行时多线程的影响 |
|-----------|-------------------|
| `?:` → `if` 合并 | 减少分支预测失误，降低流水线刷新，提升每线程 IPC |
| 代码运动（Code Motion） | 提高缓存局部性，减少 cache miss，对多线程共享缓存友好 |
| 读写集分析（rdVars/wrVars） | 直接复用于多线程分区的依赖分析 |
| 副作用/屏障标记 | 与多线程中"不可并行化语句"的判定逻辑一致 |
| 分支预测传递（branchPred） | 生成的 C++ 代码中嵌入 `__builtin_expect`，提升运行时性能 |
| 复杂度控制（MAX_DISTANCE=500） | 编译时优化的时间预算管理思路，可迁移到运行时调度 |

### 编译时/运行时分离架构

```
┌──────────────────────────────────────────────────────────────┐
│                     Verilator 编译时（单线程）                   │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    │
│  │ V3MergeCond  │ →  │  V3Partition │ →  │  代码生成    │    │
│  │ 条件合并      │    │  多线程分区   │    │              │    │
│  │ VL_MT_DISABLED│    │              │    │              │    │
│  └──────────────┘    └──────────────┘    └──────────────┘    │
│         ↓                                                    │
│    AST 优化完成（单线程串行执行）                               │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│                     Verilator 运行时（多线程）                    │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    │
│  │  线程 0      │    │  线程 1      │    │  线程 N      │    │
│  │ 执行 Eval   │    │ 执行 Eval    │    │ 执行 Eval    │    │
│  │ （已优化代码）│    │ （已优化代码）│    │ （已优化代码）│    │
│  └──────────────┘    └──────────────┘    └──────────────┘    │
│                                                              │
│  V3MergeCond 的优化结果在这里发挥作用：                          │
│  - 更少的分支预测失误                                          │
│  - 更好的缓存局部性                                            │
│  - 更紧凑的条件结构                                            │
└──────────────────────────────────────────────────────────────┘
```

---

## 对 RTL 仿真器多线程化的启示

### 1. 编译时优化与运行时并行化的解耦

V3MergeCond 的设计验证了**编译时优化与运行时多线程应严格解耦**的架构原则：
- 编译时 Pass 可以在单线程下安全地、无锁地任意修改 AST。
- 所有优化完成后，生成的 C++ 代码是**只读的**（运行时不再修改 AST），因此多线程执行时无需考虑 AST 同步问题。
- 对于正在设计多线程 RTL 仿真器的人来说，这意味着："先在单线程编译阶段做尽优化，再让运行时多线程只读执行生成的代码。"

### 2. 读写集分析是多线程分区的基础

`StmtProperties` 中的 `m_rdVars` / `m_wrVars` 分析是 V3MergeCond 的核心，而这正是**多线程分区算法**（如 V3Partition）的输入数据。一个语句能否被分配到独立线程，本质上取决于它的读写集与其他语句的读写集是否冲突。Verilator 的编译管道已经建立了这套基础设施，后续的多线程分区 Pass 可以直接复用。

### 3. 代码运动的滑动窗口思想可迁移到运行时调度

`MAX_DISTANCE = 500` 的**有限滑动窗口优化**是一个重要的工程智慧：
- 全局最优（`O(N²)`）在编译时间上是不可接受的。
- 局部窗口内的近似最优（`O(N)`）在工程上已经足够好。
- 这个思想可以直接迁移到多线程的**局部调度器**：在每个线程的局部任务队列中，只在有限窗口内寻找可并行的任务，而非全局调度。

### 4. 分支合并对多线程分支预测的影响

在多线程 CPU 上（如现代 x86/ARM），每个硬件线程有独立的分支预测器，但它们共享**分支预测历史表（BHT）**和**分支目标缓冲区（BTB）**。
- 如果 N 个线程都在求值相同的 `cond ? a : b` 序列，每个 `?:` 独立占用分支预测资源，可能导致预测表冲突（aliasing）。
- 合并为单个 `if/else` 后，只有一个分支点，大幅降低预测器压力。
- 对于多线程 RTL 仿真器，这意味着：**编译时的条件合并直接影响运行时多线程的可扩展性**——分支预测器资源是共享的，减少分支点数量 = 减少线程间资源竞争。

### 5. 屏障（Fence）语义的统一

`m_isFence` 在 V3MergeCond 中表示"不可跨越的语句"。在多线程中，这对应于**内存屏障（memory fence）**或**同步点**。两个概念的本质是相同的：**某些操作点之前和之后的其他操作不能被重排序**。Verilator 在编译时就已经识别了这些点，可以在多线程分区时利用这些标记来决定"在哪里插入线程同步点"。

### 6. 副作用分析决定并行粒度

`m_sideEffect` 标记（`Display`、`Stop`、DPI 非纯函数调用等）在代码运动中限制重排序，在多线程中则限制并行化。例如：
- 包含 `\$display` 的语句不能被重排序（代码运动视角）
- 包含 `\$display` 的语句通常也不能被并行化（多线程视角），因为输出顺序需要保持确定性
- 这种"副作用 = 串行化约束"的语义在两个上下文中完全一致。

---

## 原文摘录

> "Look for sequences of assignments with ternary conditional on the right hand side with the same condition... This seems to be a common pattern and can make the C compiler take a long time when compiling it with optimization."
> — V3MergeCond.cpp:22-36

> "Because this optimization has notable performance impact, we go further and perform code motion to try to move mergeable conditionals next to each other, which in turn enable us to merge more conditionals."
> — V3MergeCond.cpp:51-56

> "We limit maximum distance a node can travel to an empirically chosen but otherwise arbitrary constant. This limits worst case complexity to be O(n) rather than O(n^2)."
> — V3MergeCond.cpp:60-66

> "If the list contains a single AstNodeIf, we will want to merge its branches."
> — V3MergeCond.cpp:582-583（递归处理的策略说明）

---

## 相关链接

- [V3MergeCond.h 源码](https://github.com/verilator/verilator/blob/master/src/V3MergeCond.h)
- [V3MergeCond.cpp 源码](https://github.com/verilator/verilator/blob/master/src/V3MergeCond.cpp)
- [Verilator 编译管道文档](https://verilator.org/guide/latest/internals.html)
- [V3Partition.cpp](https://github.com/verilator/verilator/blob/master/src/V3Partition.cpp) — 多线程分区 Pass（与 V3MergeCond 共享依赖分析基础设施）
- [V3Clean.cpp](https://github.com/verilator/verilator/blob/master/src/V3Clean.cpp) — 在 V3MergeCond 之前运行，插入 `And` 位掩码

---
title: "Verilator 多线程相关 PR 分析"
source_url: "https://github.com/verilator/verilator/pulls"
source_type: "github-pr"
author: "Verilator Contributors"
date: "2023-2025"
tags: ["github", "parallel-code", "cpp", "verilator", "thread-pool", "pr-analysis"]
keywords: ["verilator", "thread-pool", "V3ThreadPool", "MT_DISABLED", "partitioner", "edge-contraction"]
capture_date: "2026-07-01"
---

# Verilator 多线程相关 PR 分析

## 来源

- URL: <https://github.com/verilator/verilator/pulls>
- 类型: github-pr
- 作者: Verilator Contributors (b-chmiel, mglb, jdrowne, etc.)
- 日期: 2023-2025

## 摘要

Verilator 的多线程支持不是一次性完成的，而是通过一系列 PR 逐步迭代而来。本文分析其中 5 个最关键的 PR，涵盖线程池重写、代码安全分级、编译时并行化、等待优化和内联优化。这些 PR 记录了从一个复杂但脆弱的通用线程池，到一个极简、专用、高可靠线程池的演进过程。

## 关键 PR 分析

### PR #5161: Thread pool rewrite (2024-08-23, merged)

**作者**: b-chmiel (Antmicro)  
**链接**: <https://github.com/verilator/verilator/pull/5161>

#### 问题
旧版 `V3ThreadPool` 过于通用，带来了不必要的复杂性和调试困难：
- 后台可以在任意时刻执行 job，需要 `MT_DISABLED` 和 `requestExclusiveAccess` 来保证安全；
- `resize()` 支持运行时动态调整 worker 数量，从未使用却增加了复杂逻辑；
- 错误处理涉及多层嵌套（errors during errors, fatal errors...），导致 `~V3ThreadPool` 中出现了多个死锁/假锁 bug（[#4672](https://github.com/verilator/verilator/pull/4672), [#4938](https://github.com/verilator/verilator/pull/4938), [#5040](https://github.com/verilator/verilator/pull/5040)）。

#### 方案
- **移除通用功能**：去掉 futures、resize、动态停止/恢复等；
- **引入 V3ThreadScope**：将线程池的使用限制在明确的作用域内，RAII 确保进出时线程池处于 clean state（无运行中任务）；
- **简化错误处理**：出错时直接 `::_exit(1)`，泄漏线程池，避免析构死锁；
- **Spin 模型验证**：用 Spin model checker 证明了新线程池模型的正确性。

#### 关键代码变更
```cpp
// 旧版：复杂的 stop/resume/exclusive access 逻辑
// 新版：V3ThreadScope 构造函数绑定，析构自动 wait()
V3ThreadScope::V3ThreadScope() {
    UASSERT(v3Global.threadPoolp(), "ThreadPool must be initialized before ThreadScope.");
    m_pool = v3Global.threadPoolp();
    wait();  // 确保进入作用域前没有残留任务
}
V3ThreadScope::~V3ThreadScope() { wait(); }
```

**启示**: 专用线程池比通用线程池更可靠。RAII 作用域管理消除了显式 stop/resume 的需求。

---

### PR #4228: Rework multithreading handling to separate by code units (2023-09-25, merged)

**作者**: mglb (Antmicro)  
**链接**: <https://github.com/verilator/verilator/pull/4228>

#### 问题
并行化新阶段时，如果所有代码都需满足完整线程安全分析，需要重构整个代码库，工作量巨大。

#### 方案
将代码单元按编译标志分为三级：

| 级别 | 宏定义 | 线程安全分析 | 能否使用 V3ThreadPool | 说明 |
|------|--------|-------------|----------------------|------|
| MT_DISABLED | `VL_MT_DISABLED_CODE_UNIT=1` | 忽略 VL_REQUIRES/VL_GUARDED_BY | 禁止 include V3ThreadPool.h | 绝大多数编译阶段 |
| MT_ENABLED | 无 | 完整 | 可以 | 被并行化的阶段 |
| MT_CONTROL | `VL_MT_CONTROL_CODE_UNIT=1` | 完整 | 可以 + 能调用 v3MtDisabledLock() | 主控代码 |

```cpp
// 示例：MT_DISABLED 代码的声明需加 VL_MT_DISABLED
void V3Order::selfTestParallel() VL_MT_DISABLED;

// MT_CONTROL 代码中显式加锁后调用 MT_DISABLED 代码
{
    const V3LockGuard lock{v3MtDisabledLock()};
    V3Order::selfTestParallel();  // 安全
}
```

**启示**: 渐进式并行化的关键——不必让所有代码都线程安全，只需标记和保护真正并行化的模块。

---

### PR #6761: Optimize V3ThreadPool::wait() to use condition variable (2025-12-16, closed/draft)

**作者**: jdrowne  
**链接**: <https://github.com/verilator/verilator/pull/6761>

#### 问题
当前 `wait()` 使用 busy-wait loop (`std::this_thread::yield()`)，在等待任务完成时浪费 CPU 周期。

#### 方案
- 添加 `m_completionCV` 条件变量；
- `wait()` 先自旋一小段时间（`VL_LOCK_SPINS`），然后进入 `m_completionCV.wait()` 阻塞等待；
- worker 在 `m_pendingJobs` 减到 0 时通知 `m_completionCV`。

```cpp
// 伪代码：优化后的 wait()
void wait() {
    // 快速路径：自旋等待
    for (int i = 0; i < VL_LOCK_SPINS; ++i) {
        if (m_pendingJobs.load() == 0) return;
        std::this_thread::yield();
    }
    // 慢速路径：条件变量阻塞
    std::unique_lock lock{m_mutex};
    m_completionCV.wait(lock, [&]{ return m_pendingJobs == 0 || m_shutdown; });
}
```

**启示**: 混合策略（spin-then-block）是低延迟等待任务完成的标准做法。对于 RTL 仿真器，编译时的线程池等待不应消耗大量 CPU。

---

### PR #6763: Parallelize V3FuncOpt using V3ThreadScope (2025-12-06, closed/draft)

**作者**: jdrowne  
**链接**: <https://github.com/verilator/verilator/pull/6763>

#### 问题
`V3FuncOpt`（函数级优化）阶段在大型多模块设计中耗时较长，可以并行化。

#### 方案
- 在 `funcOptAll()` 中引入 `V3ThreadScope`；
- 每个 `AstCFunc` 独立并行处理；
- 将统计计数器 `FuncOptStats` 改为 `std::atomic<uint64_t>` 保证线程安全；
- `VL_MT_SAFE` 注解标记 `FuncOptVisitor::apply()` 为线程安全。

```cpp
void V3FuncOpt::funcOptAll(AstNetlist* nodep) {
    V3ThreadScope threadScope;
    for (AstCFunc* funcp = ...; funcp; funcp = funcp->nextp()) {
        threadScope.enqueue([funcp]() {
            FuncOptVisitor::apply(funcp);
        });
    }
}
```

**启示**: Verilator 的编译时并行化策略是"按函数/模块切分任务"，因为每个函数的 AST 子树是不相交的。RTL 仿真器的编译阶段也可以按模块或函数粒度并行化，天然避免数据竞争。

---

### PR #6765 (→ #6815): Inline small CFuncs to reduce function call overhead (2025-12-21, merged)

**作者**: jdrowne  
**链接**: <https://github.com/verilator/verilator/pull/6815>

#### 问题
`--output-split-cfuncs` 将函数拆到不同编译单元，导致 C++ 编译器无法内联，增加函数调用开销。

#### 方案
- 新增 `--inline-cfuncs`（默认阈值 20 个节点）和 `--inline-cfuncs-product`（默认 200）两个选项；
- 在单独 pass `V3InlineCFuncs` 中实现，运行时机在 `V3Reloop` 之后；
- 避免内联包含 `$c()` 语句的函数（作用域问题）和入口函数。

```cpp
// 内联时局部变量重命名：__Vinline_<func>_<var>
```

**启示**: 多线程并行编译时，如果函数粒度太细，会增加编译单元间调用的开销。在仿真器生成代码时，适当的内联可以减少跨线程调用边界，提升单线程和多线程性能。

## 对 RTL 仿真器多线程化的启示

1. **线程池不是越通用越好**：Verilator 的演进证明，从复杂通用线程池退化到极简专用线程池，反而消除了大量死锁和 bug。

2. **渐进式并行化是务实的路径**：通过 `MT_DISABLED`/`MT_ENABLED`/`MT_CONTROL` 分级，可以逐步并行化编译阶段，而无需一次性重写整个代码库。

3. **按函数/模块粒度并行是安全的**：只要每个任务的 AST 子树不相交，就不需要复杂的锁，仅需原子计数器即可。

4. **混合等待策略**：自旋 + 条件变量阻塞的组合能在低延迟和 CPU 效率之间取得平衡。

5. **关注生成代码的粒度**：多线程化不仅涉及运行时，也涉及生成代码的质量。内联、函数拆分策略会直接影响多线程性能。

## 相关链接

- [PR #5161 - Thread pool rewrite](https://github.com/verilator/verilator/pull/5161)
- [PR #4228 - Rework multithreading handling](https://github.com/verilator/verilator/pull/4228)
- [PR #6761 - Optimize wait() with condition variable](https://github.com/verilator/verilator/pull/6761)
- [PR #6763 - Parallelize V3FuncOpt](https://github.com/verilator/verilator/pull/6763)
- [PR #6815 - Inline small CFuncs](https://github.com/verilator/verilator/pull/6815)

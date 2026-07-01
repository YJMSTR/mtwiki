---
title: "Verilator 多线程源码分析"
source_url: "https://github.com/verilator/verilator"
source_type: "github-code"
author: "Wilson Snyder / Verilator Contributors"
date: "2024-2026"
tags: ["github", "parallel-code", "cpp", "rtl-simulator", "verilator", "thread-pool"]
keywords: ["verilator", "V3ThreadPool", "V3ThreadScope", "V3OrderParallel", "edge-contraction", "critical-path", "partitioner"]
capture_date: "2026-07-01"
---

# Verilator 多线程源码分析

## 来源

- URL: <https://github.com/verilator/verilator>
- 类型: github-code
- 作者: Wilson Snyder / Verilator Contributors
- 日期: 2024-2026 (持续活跃开发)

## 摘要

Verilator 是目前最主流的开源 SystemVerilog 仿真器之一。其多线程实现分为两个层面：
1. **编译时并行**（`--verilate-jobs`）：在 Verilator 前端编译过程中使用 `V3ThreadPool` 加速 AST 遍历和 C++ 代码生成；
2. **仿真时并行**（`--threads`）：将生成的 C++ 模型划分为多个 Macro-Task（MTask），在运行时由静态调度器分配到不同线程执行。

本文分析 Verilator 源码中 `V3ThreadPool`、`V3OrderParallel`（Partitioner）以及相关基础设施的实现细节。

## 关键要点

### 1. V3ThreadPool — 极简线程池

文件: `src/V3ThreadPool.h` / `src/V3ThreadPool.cpp`

```cpp
// src/V3ThreadPool.h
class V3ThreadPool final {
    std::vector<std::thread> m_workers;
    std::queue<std::function<void()>> m_queue VL_GUARDED_BY(m_mutex);
    std::condition_variable_any m_cv;
    std::atomic<bool> m_shutdown{false};
    std::atomic<size_t> m_pendingJobs{0};
    V3Mutex m_mutex;
public:
    explicit V3ThreadPool(int numThreads);
    ~V3ThreadPool() VL_EXCLUDES(m_mutex);
    void enqueue(std::function<void()>&& f) VL_MT_START VL_EXCLUDES(m_mutex);
    void wait() VL_MT_SAFE;
    void workerJobLoop() VL_MT_SAFE VL_EXCLUDES(m_mutex);
    static void startWorker(V3ThreadPool* selfThreadp) VL_MT_SAFE VL_EXCLUDES(m_mutex);
};

class V3ThreadScope final {
    V3ThreadPool* m_pool = nullptr;
public:
    V3ThreadScope() VL_MT_SAFE VL_ACQUIRE(VlOs::MtScopeMutex::s_haveThreadScope);
    ~V3ThreadScope() VL_MT_SAFE VL_RELEASE(VlOs::MtScopeMutex::s_haveThreadScope) { wait(); }
    void enqueue(std::function<void()>&& f) VL_MT_START;
    void wait() VL_MT_SAFE VL_REQUIRES(VlOs::MtScopeMutex::s_haveThreadScope);
};
```

**设计特点**:
- **极简主义**：摒弃了早期的动态 `resize`、 futures、复杂错误处理等过度设计。
- **RAII 作用域控制**：`V3ThreadScope` 构造函数绑定线程池，析构时自动 `wait()` 确保所有任务完成。这样保证了多线程只发生在显式标记的作用域内。
- **错误处理**：出错了直接 `::_exit(1)`，避免析构全局对象和线程池导致的死锁（如 [#4672](https://github.com/verilator/verilator/pull/4672)）。
- **Clang 线程安全注解**：`VL_GUARDED_BY`, `VL_EXCLUDES`, `VL_MT_SAFE` 等宏配合 `clang_check_attributes` 脚本在编译期检查线程安全。

```cpp
// src/V3ThreadPool.cpp
void V3ThreadPool::enqueue(std::function<void()>&& f) {
    if (m_workers.empty()) {
        f();  // 单线程时直接执行，零开销
    } else {
        {
            const V3LockGuard lock{m_mutex};
            m_queue.push(std::move(f));
        }
        m_pendingJobs.fetch_add(1, std::memory_order_release);
        m_cv.notify_one();
    }
}

void V3ThreadPool::wait() {
    while (m_pendingJobs.load(std::memory_order_acquire) > 0 && !m_shutdown) {
        std::this_thread::yield();
    }
    if (m_shutdown) {
        for (auto& worker : m_workers) worker.join();
    }
}

void V3ThreadPool::workerJobLoop() {
    while (true) {
        std::function<void()> job;
        {
            const V3LockGuard lock{m_mutex};
            m_cv.wait(m_mutex, [&]() VL_REQUIRES(m_mutex) {
                return !m_queue.empty() || m_shutdown;
            });
            if (m_shutdown) return;
            job = std::move(m_queue.front());
            m_queue.pop();
        }
        job();
        m_pendingJobs.fetch_sub(1, std::memory_order_release);
    }
}
```

### 2. V3OrderParallel — 基于边收缩的图划分器（Partitioner）

文件: `src/V3OrderParallel.cpp`

这是 Verilator 多线程仿真的核心。它将 V3Order 生成的细粒度语句级依赖图（可能有数百万节点）粗化为仅包含数十个 MTask 的执行图。

**核心算法**:

```cpp
// 初始化临界路径（Critical Path）
template <GraphWay::en N_Way>
static void partInitHalfCriticalPaths(V3Graph& mTaskGraph, bool checkOnly) {
    constexpr GraphWay way{N_Way};
    GraphStreamUnordered order{&mTaskGraph, way};
    for (const V3GraphVertex* vertexp; (vertexp = order.nextp());) {
        const LogicMTask* const mtaskcp = static_cast<const LogicMTask*>(vertexp);
        LogicMTask* const mtaskp = const_cast<LogicMTask*>(mtaskcp);
        uint64_t cpCost = 0;
        for (const V3GraphEdge& edge : vertexp->edges<way.invert()>()) {
            const LogicMTask* const relativep = static_cast<const LogicMTask*>(edge.furtherp<way.invert>());
            cpCost = std::max(cpCost, relativep->critPathCost(way) + relativep->stepCost());
        }
        mtaskp->setCritPathCost(way, cpCost);
    }
}
```

**边收缩（Edge Contraction）**:
- 初始时每个 OrderMoveVertex 对应一个 LogicMTask。
- 迭代合并有边连接的 MTask 对，选择使得**局部临界路径增长最小**的候选对。
- 使用 `MergeCandidateScoreboard`（基于 PairingHeap）维护候选合并的优先级。
- 合并直到 MTask 数量降到 `threads * PART_DEFAULT_MAX_MTASKS_PER_THREAD`（默认 50 个/线程）。

```cpp
class Contraction final {
    MergeCandidateScoreboard m_sb;  // 优先队列，按 score 排序
    PropagateCp<GraphWay::FORWARD> m_forwardPropagator;
    PropagateCp<GraphWay::REVERSE> m_reversePropagator;
    // ...
    void contract(MergeCandidate* mergeCanp) {
        // 1. 计算合并后新的 CP
        // 2. 从 scoreboard 移除被合并的边
        // 3. 重定向所有边（partRedirectEdgesFrom）
        // 4. 增量传播 CP 变化（PropagateCp::go）
        // 5. 重新生成 sibling merge 候选
    }
};
```

**关键数据结构**:

```cpp
class LogicMTask final : public V3GraphVertex {
    OrderMoveVertex::List m_mVertices;   // 包含的原子任务
    uint64_t m_cost = 0;               // 执行代价（指令计数）
    std::array<uint64_t, GraphWay::NUM_WAYS> m_critPathCost = {};
    std::array<EdgeHeap, GraphWay::NUM_WAYS> m_edgeHeap;  // 按 CP 排序的边堆
    std::unordered_set<LogicMTask*> m_edgeSet;  // 快速查重
};
```

**FixDataHazards**:
- 处理并行模式下原本在串行模式无问题的数据冒险（如 R-M-W 竞争、循环逻辑切割后的读写竞争）。
- 策略：将同一 rank 的读写 MTask 强制合并，并在不同 rank 之间添加串行边。

### 3. 静态调度与运行时同步

根据 `docs/internals.rst`:

> "Verilator takes this static approach. The only dynamic aspect is that each macro task may block before starting, to wait until its prerequisites on other threads have finished."

- **静态调度**：MTask 到线程的映射在 Verilation 时确定。
- **运行时同步**：每个 MTask 在启动前等待其所有前驱完成。同步成本很低（如果前驱已完成），但可能产生碎片化（空闲核心等待）。
- **变量局部性优化**：`V3VariableOrder` 根据 MTask 的访问模式将变量分组排列，提升缓存局部性。

### 4. 代码单元级别的线程安全分级

PR #4228 引入了三类代码单元：

- **MT_DISABLED**：绝大多数编译阶段，假设单线程运行，无需加锁。
- **MT_ENABLED**：可使用线程池，完整线程安全分析。
- **MT_CONTROL**：`Verilator.cpp` 主控，可获取 `v3MtDisabledLock()` 调用 MT_DISABLED 代码。

这种分级避免了为永远不并行化的代码添加锁开销。

## 对 RTL 仿真器多线程化的启示

1. **从细粒度图到粗粒度 MTask 的转化是核心**：Verilator 的 partitioner 证明，将百万级节点的依赖图收缩到数十个 MTask 是可行的，且能显著降低运行时同步开销。稀疏计算 RTL 仿真器同样需要先构建语句/单元级依赖图，再进行粗化。

2. **静态调度 + 轻量运行时同步**：对于确定性仿真，静态调度优于动态调度。Verilator 的实验表明动态调度（macro-dataflow）性能较差。RTL 仿真器可考虑静态分配任务到线程，仅在 MTask 边界同步。

3. **RAII 线程池作用域**：`V3ThreadScope` 的设计非常优雅——多线程只存在于明确标记的作用域，出作用域即完成同步。这避免了全局线程状态管理的心智负担和死锁风险。

4. **增量临界路径传播**：`PropagateCp` 使用最大堆实现增量传播，避免全图重算。对于需要频繁调整分区的仿真器，这是可借鉴的性能优化。

5. **变量排布优化**：按 MTask 访问足迹（footprint）分组排列变量， cache-line 对齐，能显著减少 false sharing。这对 memory-bound 的稀疏计算仿真尤为重要。

6. **代码单元分级**：不必一次性让整个代码库线程安全。明确标记哪些模块是多线程的、哪些是单线程的，可以渐进式并行化。

## 原文摘录

> "The partitioner's goal is to coarsen the fine-grained graph into a coarser graph, while maintaining as much available parallelism as possible. Often the partitioner can transform an input graph with millions of nodes into a coarsened execution graph with a few dozen nodes, while maintaining enough parallelism to take advantage of a modern multicore CPU."
> — `docs/internals.rst`

> "The only dynamic aspect is that each macro task may block before starting, to wait until its prerequisites on other threads have finished. The synchronization cost is cheap if the prereqs are done. If they're not, fragmentation (idle CPU cores waiting) is possible. This is the major source of overhead in this approach."
> — `docs/internals.rst`

> "The new thread pool is to remove all features that are not used by Verilator and tailor it to the specific problem we're solving... V3ThreadScope ensures that multi-threading is limited to certain scopes."
> — PR #5161

## 相关链接

- [Verilator 源码](https://github.com/verilator/verilator)
- [V3ThreadPool.h](https://github.com/verilator/verilator/blob/master/src/V3ThreadPool.h)
- [V3ThreadPool.cpp](https://github.com/verilator/verilator/blob/master/src/V3ThreadPool.cpp)
- [V3OrderParallel.cpp](https://github.com/verilator/verilator/blob/master/src/V3OrderParallel.cpp)
- [docs/internals.rst - Multithreaded Mode](https://github.com/verilator/verilator/blob/master/docs/internals.rst)
- [PR #5161 - Thread pool rewrite](https://github.com/verilator/verilator/pull/5161)
- [PR #4228 - Rework multithreading handling](https://github.com/verilator/verilator/pull/4228)

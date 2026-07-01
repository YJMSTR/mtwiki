---
id: "wiki-scheduling"
title: "调度与负载均衡"
description: "RTL仿真器中的任务调度策略：静态分区、动态work stealing、任务粒度控制与关键路径感知的综合设计"
tags: ["scheduling", "load-balancing", "work-stealing", "partitioning", "rtl-sim"]
keywords: ["work stealing", "static partition", "task granularity", "critical path", "macro-task", "micro-task", "NUMA-aware"]
related_sources:
  - "source-work-stealing"
  - "source-onetbb-scheduler"
  - "source-verilator-mt-code-analysis"
  - "source-parendi-asplos25"
last_updated: "2026-07-01"
---

# 调度与负载均衡

RTL仿真器的多线程性能，一半取决于数据布局，另一半取决于任务调度。静态分区（如 Verilator 的 V3Partition）在编译时确定任务映射，确定性高、运行时开销低；动态调度（如 work stealing）能适应运行时负载变化，但带来同步开销。本章对比两种范式，并给出在 RTL 仿真场景中可操作的任务粒度、批量窃取和关键路径感知策略。

---

## 1. 静态分区 vs 动态调度：两种哲学

### 1.1 Verilator 的静态分区：V3Partition

Verilator 将编译时生成的细粒度语句级依赖图（数百万节点）通过**边收缩（edge contraction）**粗化为数十个 Macro-Task（MTask）。每个 MTask 包含一组有数据依赖关系的门/语句，运行时由静态调度器分配到固定线程。

**核心流程**：
1. 构建细粒度依赖图（OrderMoveVertex 级别）
2. 计算关键路径（critical path）
3. 迭代合并边，优先选择**局部关键路径增长最小**的候选对
4. 最终 MTask 数量降到 `threads × 50`（默认）

**运行时同步**：每个 MTask 启动前等待所有前驱完成。同步成本很低（如果前驱已完成），但可能产生碎片化——空闲核心等待关键路径上的任务完成。

**优点**：
- 无运行时调度开销
- 确定性执行，调试可复现
- 静态调度器可以精确预估数据局部性

**缺点**：
- 无法适应运行时负载波动（稀疏计算中不同时间步活跃门数量差异巨大）
- 负载不均衡时，空闲线程只能空转

### 1.2 Work Stealing：动态负载均衡

Work stealing 的核心机制：每个线程维护一个**双端队列（deque）**，本地线程在**尾部（LIFO）**push/pop 任务，空闲线程从**随机选择的其他线程 deque 的头部（FIFO）**steal 一个任务。

**理论保证**（Blumofe & Leiserson, 1999）：
- 期望执行时间：**O(T₁/P + T∞)**，其中 T₁ 是串行工作量，P 是线程数，T∞ 是关键路径长度
- 期望 steal 次数：**O(P · T∞)**
- 当线程数 P ≤ 并行度（T₁/T∞）时，接近线性加速

**优点**：
- 不需要精确的静态分区
- 天然适应负载波动
- 无集中式调度瓶颈

**缺点**：
- 每个 steal 涉及原子 CAS 和缓存一致性流量
- 细粒度任务下，steal 开销可能超过任务本身

### 1.3 RTL 仿真中的选择

| 场景 | 推荐策略 | 理由 |
|------|----------|------|
| 同步数字逻辑、周期驱动、负载稳定 | 静态分区（Verilator 风格） | 确定性、低 overhead、cache 局部性可优化 |
| 事件驱动、稀疏活跃、负载波动大 | 动态 work stealing | 自动平衡不同时间步的活跃门数量差异 |
| 混合场景 | 静态分区 + 局部门级 work stealing | 宏观周期静态分配，微观事件动态均衡 |

---

## 2. 任务粒度：Macro-Task vs Micro-Task

### 2.1 粒度太细 = 调度开销吞噬并行收益

RTL 仿真的单个门级求值可能只需 **20~50 ns**。如果调度器 steal 一次的开销是 **100~200 ns**（CAS + 缓存失效 + 函数指针调用），那么 steal 一个门就是净亏损。

**Verilator 的经验**：将数百万节点收缩到 `threads × 50` 个 MTask 是必要的前置步骤。如果要在 RTL 仿真器中使用动态调度，也必须先粗化任务。

### 2.2 任务粒度建议

| 粒度层级 | 定义 | 适用调度 | 示例 |
|----------|------|----------|------|
| Micro-Task | 单个门/单个语句 | 仅静态调度内联 | 一个 AND 门的求值 |
| Mini-Task | 一个逻辑锥/一个模块 | 静态分配 | 一个组合逻辑模块的稳态求值 |
| Macro-Task | 一个时钟域的完整求值 | 静态或动态 | 一个时钟沿触发的所有寄存器更新 + 后续组合逻辑传播 |
| Mega-Task | 多个时钟域的一个周期 | 静态 | 整个电路一个周期的全量仿真 |

**操作建议**：
- 静态调度器（如 Verilator）的 MTask 应至少包含 **1000~10000 条指令**（约 100~500 个门）
- 动态 work stealing 的 steal 单位应至少是一个**逻辑锥**（数十到数百个门），而非单个门
- 事件驱动仿真中，将同一数据路径上的连续门组合为"fiber"或"cluster"，作为不可拆分的调度单位

### 2.3 粗化任务的代码示意

```cpp
struct LogicCone {
    uint32_t start_gate;      // 起始门索引
    uint32_t num_gates;       // 包含的门数量
    uint32_t output_gates[8]; // 输出接口（连接其他 cone）
};

// 一个 MTask 处理多个 LogicCone
void execute_mtask(const MTask& task) {
    for (const LogicCone& cone : task.cones) {
        evaluate_cone(cone);  // 内部串行，无同步
    }
}
```

---

## 3. 批量 Steal：摊薄同步开销

### 3.1 为什么需要批量

单次 steal 的开销包括：
1. 随机选择 victim
2. 读取 victim 的 head 指针（可能跨 NUMA）
3. CAS 竞争 head 推进
4. 将偷来的任务拷贝到本地 deque

如果一次只偷 1 个事件，而事件处理仅需 50ns，那么 steal 开销占 50% 以上。一次偷 **64~256 个事件**，将开销摊薄到可忽略。

### 3.2 批量 Steal 实现

```cpp
class StealableDeque {
    std::atomic<size_t> head{0};
    std::atomic<size_t> tail{0};
    std::vector<Task> buffer;  // 环形缓冲区，需动态扩容
public:
    // Owner: push 到尾部（LIFO）
    void push(Task t) {
        size_t t_idx = tail.fetch_add(1, std::memory_order_relaxed);
        buffer[t_idx % capacity] = std::move(t);
    }

    // Owner: pop 从尾部（LIFO）
    std::optional<Task> pop() {
        size_t t = tail.load(std::memory_order_relaxed) - 1;
        tail.store(t, std::memory_order_relaxed);
        std::atomic_thread_fence(std::memory_order_seq_cst);
        size_t h = head.load(std::memory_order_relaxed);
        if (h <= t) {
            return buffer[t % capacity];
        }
        // 空了，恢复 tail
        tail.store(t + 1, std::memory_order_relaxed);
        return std::nullopt;
    }

    // Thief: 批量 steal 从头部（FIFO）
    std::vector<Task> steal_batch(size_t max_batch = 64) {
        size_t h = head.load(std::memory_order_acquire);
        size_t t = tail.load(std::memory_order_acquire);
        if (h >= t) return {};  // 空

        size_t available = t - h;
        size_t batch = std::min(available, max_batch);

        // CAS 推进 head
        if (head.compare_exchange_weak(h, h + batch,
                                       std::memory_order_acq_rel)) {
            std::vector<Task> result;
            result.reserve(batch);
            for (size_t i = 0; i < batch; ++i) {
                result.push_back(std::move(buffer[(h + i) % capacity]));
            }
            return result;
        }
        return {};  // CAS 失败，其他 thief 抢先
    }
};
```

> **RTL 仿真中的批量单位**：64 个事件通常对应一个逻辑锥或一个子模块的活跃门，处理时间约 1~5 μs，远高于单次 CAS 的 ~50 ns。

---

## 4. NUMA-Aware Stealing：优先同节点

### 4.1 跨 NUMA steal 的隐性成本

Work stealing 的随机 victim 选择如果命中了远程 NUMA 节点，偷来的任务所访问的数据全部在远程内存，执行时每个内存访问都是 **~300 ns** 的延迟。原本是为了平衡负载，结果拖慢了执行速度。

### 4.2 实现：分层 Victim 选择

```cpp
class NumaAwareStealer {
    int numa_node;
    std::vector<int> local_victims;   // 同 NUMA 节点的线程
    std::vector<int> remote_victims;  // 其他 NUMA 节点的线程

public:
    std::vector<Task> steal() {
        // 第一步：优先从同 NUMA 节点 steal
        for (int victim : shuffle(local_victims)) {
            auto batch = deques[victim].steal_batch(64);
            if (!batch.empty()) return batch;
        }
        // 第二步：同节点全空，才跨 NUMA
        for (int victim : shuffle(remote_victims)) {
            auto batch = deques[victim].steal_batch(64);
            if (!batch.empty()) return batch;
        }
        return {};
    }
};
```

### 4.3 与数据布局的协同

NUMA-aware stealing 必须与 NUMA-aware 数据布局配合。如果分区 P 的数据在 node 0，但线程被 work stealing 到 node 1 处理分区 P，那么访问仍然是远程的。**最佳实践**：将任务和数据绑定到同一 NUMA 节点，steal 只在同节点内发生，除非节点内完全饱和。

---

## 5. 关键路径感知：避免关键路径迁移

### 5.1 为什么关键路径上的任务不能乱 steal

RTL 电路中存在关键路径（如全局时钟到输出端口的传播链）。如果关键路径上的门被 work stealing 分散到不同线程，每次传递都需要线程间同步，反而比串行执行更慢。Parendi 的论文指出，细粒度并行在通用 CPU 上受限的重要原因之一就是**关键路径上的依赖被跨线程拆分**。

### 5.2 关键路径固定策略

在编译时（elaboration 阶段）识别关键路径：
1. 计算每个门到 primary output 的**最大延迟路径长度**
2. 将关键路径上的门标记为 `CRITICAL_PATH`
3. 这些门必须分配到**同一线程**，且不参与 work stealing

```cpp
enum class GatePriority {
    CRITICAL_PATH,   // 固定到线程，不 steal
    NORMAL,          // 可参与 work stealing
    FAST_PATH        // 可优先本地处理，也可 steal
};

struct Task {
    GatePriority priority;
    std::vector<uint32_t> gates;
};

// 调度器跳过关键路径任务的 steal
std::optional<Task> steal_task(int thief_id) {
    for (int victim : random_victims) {
        if (victim == thief_id) continue;
        auto batch = deques[victim].steal_batch(64);
        // 过滤掉关键路径任务
        batch.erase(std::remove_if(batch.begin(), batch.end(),
            [](const Task& t){ return t.priority == GatePriority::CRITICAL_PATH; }),
            batch.end());
        if (!batch.empty()) return batch;
    }
    return std::nullopt;
}
```

### 5.3 Verilator 的边收缩天然保护关键路径

Verilator 的 partitioner 在合并 MTask 时，优先选择**对关键路径增长最小**的合并对。这保证了关键路径上的门不会被拆分到不同 MTask，从而避免了运行时同步。对于动态调度器，可以借鉴这一思想：在粗化任务时，将关键路径上的门强制归入同一调度单位。

---

## 6. 综合调度策略建议

### 6.1 推荐的混合架构

```
编译时：
  ├── 电路图分区（METIS / 自定义拓扑感知）
  ├── 识别关键路径，标记不可拆分门集合
  ├── 按 NUMA 节点分配分区（每个节点 N 个 MTask）
  └── 每个 MTask 包含 1000~10000 个门的逻辑锥

运行时（每个时间步）：
  ├── 线程绑定到 NUMA 节点，处理本地 MTask
  ├── 本地 deque 空 → 同 NUMA 节点批量 steal（64~256 个事件）
  ├── 同节点全空 → 跨 NUMA steal（仅作为兜底）
  └── 时间步结束 → barrier 同步，进入下一周期
```

### 6.2 配置参数表

| 参数 | 建议值 | 说明 |
|------|--------|------|
| MTask 数 | `threads × 20 ~ threads × 50` | 太少则并行度不足，太多则调度开销上升 |
| Steal 批量 | 64 ~ 256 个事件/门 | 覆盖单次 steal 的 CAS + 缓存开销 |
| 本地 deque 阈值 | 超过平均负载 2x 时主动迁移 | 避免 thief 被动等待 |
| 关键路径保护 | 编译时识别，运行时不可 steal | 参考 Verilator V3Partition 的 CP 算法 |
| NUMA 节点内饱和 | 优先同节点，跨节点作为 fallback | 数据局部性优先于完美负载均衡 |

### 6.3 性能诊断

- 如果 `perf` 显示大量 `lock cmpxchg` 或 `pthread_mutex_lock`，说明 steal 太频繁或粒度太细
- 如果 VTune 显示某核心持续 100% 而其他核心空闲，说明静态分区不均衡，需要引入动态 stealing
- 如果 `perf stat -e node-load-misses` 很高，说明 NUMA-aware 策略失效，steal 跨了节点

---

## 参考来源

- [source-work-stealing](source-work-stealing.md) — Chase-Lev deque、理论保证、随机 victim
- [source-onetbb-scheduler](source-onetbb-scheduler.md) — TBB 深度优先/广度优先、scheduler bypass
- [source-verilator-mt-code-analysis](source-verilator-mt-code-analysis.md) — V3Partition、边收缩、MTask、静态调度
- [source-parendi-asplos25](source-parendi-asplos25.md) — 千路并行、分区策略、关键路径、细粒度并行困境

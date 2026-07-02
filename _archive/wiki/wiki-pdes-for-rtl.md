---
id: "wiki-pdes-for-rtl"
title: "PDES在RTL仿真中的应用"
description: "将并行离散事件仿真（PDES）思想应用于RTL仿真器多线程化：保守与乐观同步、delta cycle处理、反消息实现与全周期并行化的设计指南"
tags: ["pdes", "rtl-sim", "time-warp", "conservative", "optimistic", "synchronization", "delta-cycle"]
keywords: ["PDES", "Time Warp", "conservative synchronization", "optimistic synchronization", "anti-message", "delta cycle", "GVT", "rollback", "full-cycle simulation"]
related_sources:
  - "source-pdes-making-of-field"
  - "source-timewarp-algorithm"
  - "source-pdes-vhdl-lungeanu"
  - "source-pdes-sync-comparison"
  - "source-pdes-rtlsim-modern"
  - "source-warped2-pdes-engine"
last_updated: "2026-07-01"
---

# PDES在RTL仿真中的应用

并行离散事件仿真（PDES）诞生于 1970~1980 年代，核心问题是：如何在多个逻辑进程（LP）之间维护因果一致性。保守同步（Chandy-Misra-Bryant）要求 LP 仅在确定安全时才执行；乐观同步（Time Warp）允许 LP 冒险超前，出错时回滚。将这两种思想应用于 RTL 仿真器，需要解决一个核心障碍：**RTL 的零延迟组合逻辑导致传统保守同步的 lookahead 为零，而乐观同步的 rollback 在门级状态极小的情况下反而成本极低**。

---

## 1. 保守同步（Barrier-Based）在 RTL 中的适用性

### 1.1 传统保守同步的致命伤：零 lookahead

CMB 保守同步依赖 lookahead —— LP 当前事件到其未来输出事件之间的最小虚拟时间差。在 RTL 门级仿真中，组合逻辑的传播延迟建模为**零**（或 delta cycle），lookahead 基本为零。这意味着 LP 几乎无法确定"安全执行窗口"，CMB 算法退化为串行执行，或需要发送大量 null message 来维持。

### 1.2 RTL 中保守同步仍有效的场景

虽然组合逻辑零 lookahead，但 RTL 电路中存在**天然的时间边界**：
- **时钟沿**：每个时钟周期是一个明确的同步点
- **寄存器输出**：D 触发器在时钟沿后才改变，寄存器之间天然存在 1 个周期的 lookahead
- **确定性路径**：如 reset 链路、时钟树，信号传播方向固定且可预测

### 1.3 周期级 Barrier 同步：保守同步的 RTL 变体

不要试图在事件级做保守同步，而是在**周期级**做 barrier 同步：

```cpp
// 每个周期（或每个 delta cycle 序列）结束时的屏障
std::atomic<size_t> completed_threads{0};

// Worker thread
void worker_thread(int tid) {
    while (current_time < end_time) {
        // 处理本分区在当前周期内的所有事件
        process_partition_events(tid, current_time);

        // 周期结束，报告完成
        completed_threads.fetch_add(1, std::memory_order_acq_rel);

        // 自旋等待所有线程完成
        while (completed_threads.load(std::memory_order_acquire) < num_threads) {
            _mm_pause();
        }

        // 所有线程到达屏障，进入下一周期
        if (tid == 0) {
            current_time += time_step;
            completed_threads.store(0, std::memory_order_release);
        }
    }
}
```

这种"周期级 barrier"本质上是保守同步的极端简化：lookahead 就是整个周期，所有 LP 在每个周期开始时同步。Verilator 的 `--threads` 模式正是采用这一策略 —— 静态 MTask 图在运行时按周期推进，MTask 边界用轻量原子标志同步。

### 1.4 YAWNS 窗口协议：更激进的保守变体

Nicol 提出的 YAWNS（Yet Another Windowing Network Simulator）协议，通过全局同步确定 lookahead 窗口，窗口内的事件可以安全并行执行。在 RTL 中，可以将窗口设为一个周期，允许周期内的组合逻辑自由并行，只要周期结束时全局同步。这与 Verilator 的 MTask 调度在思想上完全一致。

---

## 2. 乐观同步（Time Warp）在 RTL 中的潜力

### 2.1 为什么 RTL 门级特别适合 Time Warp

Time Warp 在通用 PDES 中的主要障碍是**状态保存开销**。但在 RTL 门级：
- 单个门的状态通常只有 **1~2 bit**（输出值）
- 完整状态保存（copy state saving）每事件只需复制一个 bit
- 增量状态保存反而因跟踪开销不划算

DSIM（RPI, 2005）在百万门 Viterbi 译码器上验证了这一点：rollback 比率仅 **0.79%**，却实现了 33 处理器 22.63 倍加速。这说明乐观同步在数字电路中远比理论最坏情况高效。

### 2.2 零延迟是 Time Warp 的优势而非劣势

传统保守同步在零延迟下几乎无法并行，但 Time Warp 的乐观同步**不依赖 lookahead**。组合逻辑 LP 可以自由执行，只有收到"过去事件"（straggler）时才 rollback。由于电路信号传播方向大多是固定的，下游 LP 收到过去事件的概率很小。

### 2.3 有界乐观：限制投机深度

纯 Time Warp 可能因过度乐观执行导致大量无用计算。为 RTL 仿真设置一个时间窗口边界：

```cpp
struct OptimisticLP {
    uint64_t local_time = 0;       // 本地虚拟时间（LVT）
    uint64_t gvt = 0;              // 全局虚拟时间（GVT）
    uint64_t max_lookahead = 10;   // 最多超前 GVT 10 个时间单位

    bool can_execute(const Event& e) {
        return e.timestamp <= gvt + max_lookahead;
    }
};
```

这种"乐观窗口"在通用 PDES 中被称为 optimistic time windows，在 RTL 中可以将窗口设为 1~2 个周期，既保留并行度，又避免过度投机。

### 2.4 反向计算（Reverse Computation）：RTL 的 rollback 捷径

Carothers 和 Perumalla 提出：对于可逆操作，rollback 不需要保存状态，而是计算逆操作。RTL 门级事件的效果通常是：
- bit 翻转（XOR/NOT）→ 逆操作就是再翻转一次
- 简单赋值（BUFFER）→ 逆操作是恢复旧值
- 与/或门求值 → 可以通过输入重新计算旧输出

在 RTL 门级，反向计算的开销往往比 copy state saving 更低。混合策略：
- bit 级状态：反向计算
- 寄存器文件/存储器：增量状态保存

---

## 3. 反消息（Anti-Message）在共享内存中的实现

### 3.1 原理

当 LP 收到 straggler 事件时，需要回滚到该事件时间戳之前的状态，并向所有已发送事件（且时间戳大于 straggler）的下游 LP 发送 anti-message。anti-message 与原始消息内容相同但标记为"反消息"，两者相遇时湮灭。

### 3.2 共享内存优化：Direct Cancellation

Fujimoto 在 Georgia Tech Time Warp (GTW) 中提出的 direct cancellation 技术，在共享内存中可以简化为**指针标记**：

```cpp
struct Event {
    uint64_t timestamp;
    uint32_t target_lp;
    uint32_t source_lp;
    uint64_t value;       // 信号值
    bool is_anti = false; // 反消息标记
    Event* paired = nullptr;  // 指向对应的正/反消息
};

// 发送事件时记录配对关系
void send_event(LP* src, LP* dst, const Event& evt) {
    Event* sent = dst->event_queue.insert(evt);
    src->sent_events[evt.timestamp].push_back(sent);
}

// Rollback 时，直接标记已发送事件为无效
void rollback(LP* lp, uint64_t to_time) {
    for (auto& [ts, events] : lp->sent_events) {
        if (ts <= to_time) continue;
        for (Event* e : events) {
            // 直接 cancellation：在目标队列中标记删除
            e->is_anti = true;  // 原子标记即可
            // 如果目标尚未处理，正/反消息可以原地湮灭
            if (e->paired && !e->paired->processed) {
                e->valid = false;
                e->paired->valid = false;
            }
        }
    }
    // 恢复状态到 to_time 之前的快照
    lp->restore_state(to_time);
}
```

在共享内存中，anti-message 不需要实际跨网络发送，只需在目标 LP 的队列中标记即可。这避免了分布式 PDES 中的序列化和反序列化开销。

### 3.3 实现建议

- **事件队列使用双向链表**：支持 O(1) 的删除/标记
- **anti-message 批量处理**：一次 rollback 可能产生数百个 anti-message，批量标记后统一清理
- **避免在 hot path 分配内存**：anti-message 和正消息共享预分配池

---

## 4. Delta Cycle 的处理

### 4.1 为什么 PDES 原始时间戳不够用

VHDL/Verilog 的 delta cycle 允许同一物理时间发生多轮零延迟事件传播。传统 PDES 假设"同时发生的事件可以按任意顺序处理"，但这会破坏 delta cycle 的语义 —— 第 3 个 delta cycle 的事件不能先于第 2 个 delta cycle 处理。

### 4.2 扩展时间戳：物理时间 + 逻辑相位

Lungeanu & Shi (DATE 2000) 的解决方案：将时间戳扩展为二元组：

```cpp
struct RtlTime {
    uint64_t physical_time;  // 物理时间（ps/ns）
    uint32_t delta_phase;    // delta cycle 序号，同一物理时间内递增

    bool operator<(const RtlTime& other) const {
        if (physical_time != other.physical_time)
            return physical_time < other.physical_time;
        return delta_phase < other.delta_phase;
    }
};
```

这保证 delta cycle 的因果序在任何并行调度下都不被破坏。每个物理时间步开始时，delta_phase = 0；组合逻辑传播产生的新事件使用 delta_phase + 1。

### 4.3 混合同步：同步元件保守 + 异步元件乐观

实验表明，将同步元件（寄存器、时钟域）映射为保守 LP，异步元件（组合逻辑）映射为乐观 LP，在大多数电路中表现最好：

```cpp
enum class LpSyncStrategy {
    CONSERVATIVE,  // 寄存器、时钟 —— 确定性路径
    OPTIMISTIC,    // 组合逻辑 —— 自由执行，出错 rollback
    ADAPTIVE       // 运行时根据 rollback 频率自动切换
};

// 同一物理时间步内：
// 1. 保守 LP 在 barrier 后确定执行（寄存器输出）
// 2. 乐观 LP 自由传播组合逻辑（多个 delta cycle）
// 3. 如果组合逻辑产生回环（feedback），触发 rollback
```

---

## 5. 全周期仿真（Cycle-Based）vs 事件驱动（Event-Driven）的并行化差异

### 5.1 全周期仿真的并行化

Parendi (ASPOS'25) 采用全周期仿真（每个周期评估整个电路），而非事件驱动。这带来几个并行化优势：
- **无动态事件队列**：每个周期知道哪些门需要求值，调度是静态的
- **无 delta cycle**：每个周期就是一个 superstep，天然适合 BSP（Bulk Synchronous Parallel）模型
- **SIMD 友好**：整个电路的状态更新可以用向量化/并行循环处理

Parendi 在 IPU 上的 BSP 模型：`计算 → 交换 → 同步`，每个 RTL 周期对应一个 superstep。在通用多核 CPU 上，可以借鉴这一思想：每个周期是一个固定工作量的并行区域，周期结束时 barrier 同步。

### 5.2 事件驱动的并行化

事件驱动仿真在稀疏计算时更高效（只处理活跃门），但并行化更复杂：
- 活跃门的分布是动态的，需要动态负载均衡（work stealing）
- 零延迟事件导致 delta cycle 内的频繁同步
- 事件队列的锁竞争是主要瓶颈

### 5.3 选择建议

| 设计类型 | 推荐模型 | 并行策略 |
|----------|----------|----------|
| 同步数字逻辑（处理器、SoC） | 全周期仿真 | 静态分区 + 周期级 barrier |
| 混合信号、异步逻辑 | 事件驱动 | 混合同步（保守 + 乐观） |
| 超大规模门级（百万门+） | 事件驱动 + 全周期混合 | 门聚类 + 乐观 Time Warp |

---

## 6. 可操作的设计建议

### 6.1 保守同步的 RTL 适配

- **不要**在事件级使用 CMB null message —— lookahead 为零导致死锁/串行
- **应该**在周期级使用 barrier 同步，每个周期内允许组合逻辑自由并行
- **考虑** YAWNS 窗口协议，将窗口设为 1 个周期，周期内门级并行

### 6.2 乐观同步的 RTL 适配

- **门级状态极小**（1~2 bit），优先使用 copy state saving 或反向计算
- **设置乐观窗口**（GVT + Δ），避免过度投机
- **共享内存 direct cancellation** 替代网络 anti-message，直接标记事件无效
- **监控 rollback 率**：如果 > 5%，说明分区质量差或乐观窗口太小，应调整

### 6.3 数据结构建议

```cpp
// 扩展时间戳（物理时间 + delta cycle）
struct ExtendedTime {
    uint64_t physical;
    uint32_t delta;
    bool operator<(const ExtendedTime& o) const {
        return physical < o.physical || (physical == o.physical && delta < o.delta);
    }
};

// 事件队列：支持 O(1) anti-message 标记
struct EventNode {
    ExtendedTime time;
    uint64_t value;
    std::atomic<bool> valid{true};   // 用于 direct cancellation
    std::atomic<bool> is_anti{false};
    EventNode* next = nullptr;
};

// 分区事件队列（参考 Warped2 的多 LTSF 队列）
class PartitionedEventSet {
    std::vector<LTSFQueue> queues;  // 每个分区一个队列
public:
    void insert(const Event& e, int partition);
    EventNode* pop(int partition);
};
```

### 6.4 从开源项目出发

- **Warped2**：通用 Time Warp 引擎，可直接映射 RTL 门级仿真（每个门 = LP，每个信号翻转 = Event）
- **Verilator**：成熟的全周期编译器，可作为静态调度基准
- **Parendi**：BSP 全周期模型，参考其 fiber 分区与通信调度

---

## 参考来源

- [source-pdes-making-of-field](source-pdes-making-of-field.md) — PDES 历史、保守与乐观的起源、共享内存优化
- [source-timewarp-algorithm](source-timewarp-algorithm.md) — Time Warp 机制、anti-message、GVT、虚拟时间理论
- [source-pdes-vhdl-lungeanu](source-pdes-vhdl-lungeanu.md) — VHDL 并行仿真、delta cycle 扩展时间戳、混合同步
- [source-pdes-sync-comparison](source-pdes-sync-comparison.md) — 保守 vs 乐观对比、反向计算、UVT 统一框架
- [source-pdes-rtlsim-modern](source-pdes-rtlsim-modern.md) — Parendi、DSIM、全周期 vs 事件驱动、现代 RTL 并行化
- [source-warped2-pdes-engine](source-warped2-pdes-engine.md) — Warped2 引擎、多 LTSF 队列、direct cancellation、共享内存优化

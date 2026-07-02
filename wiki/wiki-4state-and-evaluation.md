---
id: "wiki-4state-and-evaluation"
title: "4-State 逻辑与增量评估"
description: "系统梳理 RTL 仿真中的四值逻辑编码、真值表优化、多驱动 resolution、增量评估算法与延迟模型，提炼多线程 RTL 仿真器在 SIMD 向量化、指纹缓存、事件队列无锁化等方面的可操作建议"
tags: ["4-state-logic", "incremental-evaluation", "delay-model", "activity-factor", "simd", "lock-free"]
keywords: ["四值逻辑", "增量评估", "levelization", "activity-factor", "transport-delay", "inertial-delay", "SIMD", "指纹缓存"]
related_sources:
  - "source-4state-logic"
  - "source-incremental-evaluation"
  - "source-delay-models"
last_updated: "2026-07-03"
---

# 4-State 逻辑与增量评估

## 概述

本文档系统梳理 RTL 仿真中的三个核心技术领域：
1. **4-State（四值）逻辑**：编码、真值表、多驱动 resolution、X 传播策略
2. **增量评估**：Levelization、Activity Factor 利用、三种仿真模型对比
3. **延迟模型**：Transport vs Inertial、Timing Wheel、SDF 反标、优化技术

三者共同影响多线程 RTL 仿真器的正确性与性能。本文档从原理出发，给出可直接落地的代码模式与工程建议。

---

## 1. 4-State 逻辑：编码、真值表与 Resolution

### 1.1 2-Bit 编码方案

Verilog/SystemVerilog 使用四值逻辑系统（0, 1, X, Z）。每 bit 需要 2-bit 存储：

| 值 | 编码 (v1, v0) | 语义 | 典型场景 |
|----|---------------|------|----------|
| 0 | 00 | 明确低电平 | 确定的低电平 |
| 1 | 01 | 明确高电平 | 确定的高电平 |
| X | 10 | 未知/未初始化 | 仿真器无法预测硬件行为 |
| Z | 11 | 高阻态/未驱动 | 三态总线、开漏输出、未连接端口 |

```c
// 2-bit 编码枚举
enum Logic4 { LOGIC_0 = 0, LOGIC_1 = 1, LOGIC_X = 2, LOGIC_Z = 3 };

// 向量级存储：分离 abits 和 bbits（Icarus VVP 方案）
struct Vector4 {
    uint64_t abits;  // bit=1 表示值或 X；bit=0 表示 0 或 Z
    uint64_t bbits;  // bit=1 表示 X 或 Z；bit=0 表示 0 或 1
};
// 解码：abit=0, bbit=0 → 0; abit=1,bbit=0 → 1; abit=1,bbit=1 → X; abit=0,bbit=1 → Z
```

### 1.2 AND/OR 真值表：16×16 = 256 项 LUT

单 bit 4-state 运算可用 16-byte 查找表实现，避免分支判断：

```c
// 16-byte LUT：4×4 真值表，按 (a<<2)|b 索引
static const uint8_t AND4_LUT[16] = {
    //  a=0        a=1        a=X        a=Z
    //  b=0,1,X,Z  b=0,1,X,Z  b=0,1,X,Z  b=0,1,X,Z
    /* 0,0 */ 0, /* 0,1 */ 0, /* 0,X */ 0, /* 0,Z */ 0,   // a=0
    /* 1,0 */ 0, /* 1,1 */ 1, /* 1,X */ 2, /* 1,Z */ 2,   // a=1
    /* X,0 */ 0, /* X,1 */ 2, /* X,X */ 2, /* X,Z */ 2,   // a=X
    /* Z,0 */ 0, /* Z,1 */ 2, /* Z,X */ 2, /* Z,Z */ 2    // a=Z
};

inline Logic4 and4_lut(Logic4 a, Logic4 b) {
    return AND4_LUT[(a << 2) | b];  // 无分支，单次查表
}
```

**Bitwise OR 真值表**（Verilog 标准）：

| \|\| | 0 | 1 | X | Z |
|------|---|---|---|---|
| 0 | 0 | 1 | X | X |
| 1 | 1 | 1 | 1 | 1 |
| X | X | 1 | X | X |
| Z | X | 1 | X | X |

**Bitwise AND 真值表**：

| & | 0 | 1 | X | Z |
|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 |
| 1 | 0 | 1 | X | X |
| X | 0 | X | X | X |
| Z | 0 | X | X | X |

### 1.3 7 级 Strength Resolution

当 net 被多个驱动源驱动时（如双向总线），需要 resolution function 决定最终值。Verilog 使用**七级强度模型**：

| Strength Name | Level | 说明 |
|---------------|-------|------|
| supply | 7 | 电源级驱动 |
| strong | 6 | 强驱动（默认门级） |
| pull | 5 | 上拉/弱强驱动 |
| large | 4 | 电容级（已弃用） |
| weak | 3 | 弱驱动 |
| medium | 2 | 中等电容 |
| small | 1 | 小电容 |
| highz | 0 | 高阻态 |

**Resolution 规则**：
- 同强度的 0 与 1 冲突 → 解析为 X
- 不同强度时，高强度胜过低强度
- Z 不参与驱动（被忽略）

```c
// 简化的 resolution 逻辑：2-bit 值 + 3-bit 强度
struct ValStrength {
    uint8_t val : 2;      // 0, 1, X, Z
    uint8_t strength : 3; // 0..7
};

ValStrength resolve(ValStrength a, ValStrength b) {
    if (a.val == LOGIC_Z) return b;
    if (b.val == LOGIC_Z) return a;
    if (a.val == b.val) return (a.strength > b.strength) ? a : b;
    if (a.strength > b.strength) return a;
    if (b.strength > a.strength) return b;
    return {LOGIC_X, 6};  // 同强度冲突 → X (strong)
}
```

### 1.4 X-Optimism vs X-Pessimism

Sutherland 2013 DVCon 论文详细讨论了 X 传播的两种偏差：

- **X-Optimism（乐观）**：仿真器在条件判断中把 X 当作「假」，导致隐藏 bug。例如 `if (sel) y = a; else y = b;` 当 `sel = X` 时走 else 分支，可能掩盖初始化错误。
- **X-Pessimism（悲观）**：门级仿真中，X 输入导致 X 输出，即使实际硬件可能确定输出。过于悲观会导致验证无法收敛。

| 特性 | 2-state | 4-state |
|------|---------|---------|
| 内存占用 | 低（1 bit/信号） | 高（2 bit/信号 + 强度） |
| 运行速度 | 快（无需查表/编码） | 慢（2-4x） |
| 初始化检测 | 无法检测 | 可检测未初始化 X |
| 总线冲突 | 可能错误解析 | 正确解析为 X |
| 综合匹配度 | 与综合行为更接近 | 可能有 optimism/pessimism 差异 |

---

## 2. 增量评估：Levelization 与 Activity Factor

### 2.1 Levelization：静态拓扑排序求值

Levelization 将组合逻辑节点按拓扑顺序分层：
- 输入信号位于 level 0
- 门/模块的输出 level = max(输入 level) + 1
- 状态元素（寄存器）打破环，使组合逻辑图变为 DAG

```cpp
// 伪代码：Levelization 算法
void levelize(Graph& g) {
    std::queue<Node*> q;
    for (auto& n : g.nodes) {
        n.level = 0;
        for (auto& pred : n.predecessors) {
            if (!pred.is_state_element) n.level = std::max(n.level, pred.level + 1);
        }
        if (n.predecessors.empty()) q.push(&n);
    }
    // 按 level 排序后生成求值序列
    std::sort(g.nodes.begin(), g.nodes.end(),
              [](Node* a, Node* b) { return a->level < b->level; });
}
```

**优势**：
- 每个节点每周期最多求值一次（无重复求值）
- 无运行时事件队列管理开销
- 编译器可对同层节点进行 SIMD 向量化或指令级并行

**局限性**：
- 组合反馈环需先收缩为超节点（supernode）
- 每个周期仍遍历所有节点，无法跳过未变化部分

### 2.2 O3 Activity Factor Exploitation：输入指纹复用

ESSENT 的 O3 优化是增量评估的代表性实现。核心思想：**若一个 partition 的所有输入在上一周期到当前周期之间未发生变化，则该 partition 的输出可直接复用，无需重新求值。**

```cpp
// ESSENT O3 生成的 C++ 代码示意（简化）
struct Partition_0 {
    uint64_t in_sig;        // 输入指纹（所有输入的 XOR 或 hash）
    uint64_t out_val;       // 缓存输出
    uint64_t prev_in_sig;   // 上一周期输入指纹

    void eval() {
        if (in_sig == prev_in_sig) {
            // 输入未变，复用输出（跳过整个 partition 的求值）
            return;
        }
        prev_in_sig = in_sig;
        // 实际求值逻辑...
        out_val = compute_logic(...);
    }
};
```

**性能数据**（ESSENT DAC 2020）：

| 设计 | 活动因子 (Activity Factor) | 加速比 (O3 vs O0) |
|------|---------------------------|-------------------|
| Rocket Chip (small) | ~5% | 2.1x |
| BOOM (medium) | ~3% | 2.8x |
| Large SoC | ~1-2% | 3.5x+ |

> Activity Factor = 每周期发生翻转的节点数 / 总节点数。实际 RTL 设计的活动因子通常低于 10%，意味着 90% 以上的逻辑在任意给定周期处于「休眠」状态。

### 2.3 三种仿真模型对比

| 特性 | 事件驱动 (VCS/Xcelium) | 全周期编译 (Verilator O0) | 增量评估 (ESSENT O3) |
|------|------------------------|--------------------------|----------------------|
| 调度开销 | 高（运行时事件队列） | 无（静态内联） | 无（静态内联 + 指纹检查） |
| 每周期求值节点数 | 仅活跃节点 | 全部节点 | 仅输入变化的 partition |
| 编译时间 | 中等 | 长（全内联） | 长（划分 + 指纹逻辑） |
| 运行时内存 | 中等（事件队列） | 低（无队列） | 低（缓存指纹+输出） |
| 适用场景 | 任意延迟、异步设计 | 同步时钟域为主 | 同步时钟域 + 低 activity |
| 多线程扩展性 | 受事件队列瓶颈限制 | 良好（数据并行） | 良好（partition 独立） |

---

## 3. 延迟模型：Transport vs Inertial 与队列优化

### 3.1 Transport Delay vs Inertial Delay

| 特性 | Transport Delay | Inertial Delay |
|------|-----------------|----------------|
| 物理意义 | 信号在导线/传输线上的传播延迟 | 门电路的惯性延迟（RC 充放电） |
| 脉冲过滤 | 不过滤窄脉冲 | 过滤宽度 < 延迟的脉冲 |
| 适用场景 | 总线、互连线、时钟树 | 逻辑门、触发器、组合逻辑 |
| Verilog 语法 | `wire #5 w;` / `assign #5 out = in;` | 门原语默认：`and #5 (y, a, b);` |
| VHDL 语法 | `z <= transport a after 5ns;` | `z <= a after 5ns;` (默认) |

**Inertial Delay 的脉冲过滤机制**：

```c
// 伪代码：Inertial delay 事件调度
void schedule_inertial(Net* net, Value new_val, Time delay) {
    Time event_time = current_time + delay;

    // 检查已调度事件是否需取消（脉冲过滤）
    for (auto& pending : net->scheduled_events) {
        if (event_time - pending.time < delay) {
            cancel_event(pending);  // 脉冲太窄，取消
        }
    }

    if (net->current_value != new_val) {
        insert_event_queue(net, new_val, event_time);
    }
}
```

**Transport Delay**：从不取消旧事件，所有输入变化都传播到输出（FIFO 叠加）。

```c
// 伪代码：Transport delay 事件调度
void schedule_transport(Net* net, Value new_val, Time delay) {
    Time event_time = current_time + delay;
    insert_event_queue(net, new_val, event_time);  // 从不取消旧事件
}
```

### 3.2 Timing Wheel / Calendar Queue

**Timing Wheel（时间轮）**：

```c
#define WHEEL_SIZE 1024

struct TimingWheel {
    EventList bucket[WHEEL_SIZE];
    uint64_t current_time;

    void schedule_event(Event* e, Time delay) {
        uint64_t slot = (current_time + delay) % WHEEL_SIZE;
        bucket[slot].push_back(e);
    }

    EventList* get_current_events() {
        return &bucket[current_time % WHEEL_SIZE];
    }
};
```

**Calendar Queue（日历队列）**：分层时间轮，多粒度处理不同时间尺度的事件：
- 第一层：当前时间附近的精细粒度（1 delta cycle）
- 第二层：较长延迟的粗粒度（10/100/1000 time unit）
- 减少「空转」时间步，提升仿真速度

### 3.3 Zero / Unit / SDF 反标

| 阶段 | 延迟模型 | 目的 | 相对速度 |
|------|----------|------|----------|
| RTL 功能仿真 | Zero-delay | 验证功能正确性 | 最快（1x） |
| 综合后 GLS | Zero-delay | 验证综合未引入功能错误 | 快（10-20x） |
| 综合后 GLS | Unit-delay | 检测 race / 组合环 | 中等 |
| 布局后 GLS | SDF (pre-layout) | 初步时序验证 | 慢（100-1000x） |
| 布线后 GLS | SDF (post-layout) | 最终时序 sign-off | 最慢 |

```verilog
// SDF 回注：在 testbench 中加载延迟文件
initial begin
    $sdf_annotate("design.sdf", DUT, , "sdf.log", "MAXIMUM");
end
```

**SDF 文件结构**：

```sdf
(CELL
    (CELLTYPE "DFF")
    (INSTANCE U1)
    (DELAY (ABSOLUTE
        (IOPATH (posedge clk) (posedge q) (1.2:1.5:1.8))
    ))
    (TIMINGCHECK
        (SETUP (posedge d) (posedge clk) (0.8:1.0:1.2))
        (HOLD (posedge d) (posedge clk) (0.2:0.3:0.4))
    ))
```

### 3.4 延迟优化技术

- **Delay Scaling**：调试阶段将真实延迟按比例缩小（如 1/10），加速仿真同时保留相对时序关系
- **Model Abstraction**：非关键路径用 zero-delay，仅关键路径用 SDF
- **Glitch 合并**：若同一 net 在时间窗口内多次翻转，只保留最后一次（inertial delay 自动处理）
- **Delta Cycle 合并**：zero-delay 仿真中，多个 delta cycle 内的事件可合并为一次最终状态更新
- **Inactive Region 跳过**：若某时间槽无活跃事件，直接跳转到下一事件时间

---

## 4. 对多线程 RTL 仿真器的启示

### 4.1 4-State 在多线程中的挑战与对策

| 挑战 | 影响 | 对策 |
|------|------|------|
| **2-bit 编码向量运算** | 2-4x 性能损失 | SIMD 向量化：2-bit 交错编码到 64/128-bit 寄存器，AVX2/NEON 一次处理 32/64 bit |
| **Resolution 原子化** | 多驱动 net 跨线程竞争 | 使用 lock-free atomic 或 per-thread 局部缓存 + 合并阶段 |
| **Memory footprint 翻倍** | 状态快照大小翻倍，影响 checkpoint/replay | 按线程分片存储，checkpoint 仅保存脏页 |
| **X 传播污染** | 一个线程的 X 可能污染其他线程的计算 | **per-thread 污染标记**：每个线程维护自己的 X 状态表，commit 阶段统一合并 |

### 4.2 增量评估在多线程中的挑战与对策

| 挑战 | 影响 | 对策 |
|------|------|------|
| **指纹检查并行一致性** | 多线程同时读取/更新指纹可能竞争 | 指纹按 partition 存储，每个 partition 仅由一个线程负责；或使用 atomic 比较交换 |
| **跳过决策的负载不均** | 若某线程负责的 partition 全部活跃，而其他线程全跳过，导致负载不均 | 动态任务窃取：线程完成自身任务后，从繁忙线程窃取活跃 partition |
| **缓存失效** | 指纹比较引入额外内存访问 | 将指纹内联到 partition 结构体，确保同 cache line；使用 SIMD 批量比较 |

### 4.3 延迟事件队列在多线程中的挑战与对策

| 挑战 | 影响 | 对策 |
|------|------|------|
| **事件队列锁竞争** | 多线程同时插入事件成为热点 | **无锁插入**：使用 Michael-Scott 队列或 per-thread 子桶 + 定期合并 |
| **Inertial deschedule 线程安全** | 取消已调度事件需竞争访问 | per-thread 局部队列：每个线程先写入本地队列，barrier 后统一合并并处理 deschedule |
| **Timing wheel bucket 竞争** | 多线程向同一 bucket 插入 | 分片 bucket：每个线程有独立的 bucket 子集，定期全局合并 |
| **SDF 延迟计算** | 多 corner 独立计算 | 并行 corner simulation：MIN/TYP/MAX 三个 corner 同时运行 |

---

## 5. 可操作建议

### 5.1 2-Bit 编码 SIMD 向量化

```cpp
#include <immintrin.h>

// 将 64-bit 的 abits 和 bbits 打包到 128-bit 向量
// 使用 AVX2 一次处理 256-bit（128 个 2-bit 值）
struct Logic4VectorSIMD {
    __m256i abits;  // 每 bit 1=值/X 存在；0=0/Z
    __m256i bbits;  // 每 bit 1=X/Z；0=0/1

    // 批量 AND4：使用 LUT + shuffle
    __m256i and4(__m256i a_abits, __m256i a_bbits,
                 __m256i b_abits, __m256i b_bbits) {
        // 将 (a_abits, a_bbits, b_abits, b_bbits) 编码为 4-bit 索引
        __m256i idx = _mm256_or_si256(
            _mm256_slli_epi32(a_abits, 3),
            _mm256_or_si256(
                _mm256_slli_epi32(a_bbits, 2),
                _mm256_or_si256(
                    _mm256_slli_epi32(b_abits, 1),
                    b_bbits
                )
            )
        );
        // 使用 _mm256_shuffle_epi8 查 16-byte LUT（需扩展到 32-byte）
        return _mm256_shuffle_epi8(and4_lut_vec, idx);
    }
};
```

### 5.2 Per-Thread 输入指纹缓存

```cpp
// 每个线程维护独立的指纹缓存，避免 false sharing
struct alignas(64) ThreadFingerprintCache {
    uint64_t signatures[PARTITIONS_PER_THREAD];
    uint64_t prev_signatures[PARTITIONS_PER_THREAD];

    bool is_unchanged(size_t local_idx, uint64_t current_sig) {
        bool same = (signatures[local_idx] == current_sig);
        prev_signatures[local_idx] = current_sig;
        return same;
    }
};

// 全局调度：将活跃 partition 均匀分配给线程
void dispatch_partitions(ThreadPool& pool, const std::vector<Partition>& parts) {
    for (size_t t = 0; t < pool.num_threads(); t++) {
        pool.submit([&, t] {
            for (size_t i = t; i < parts.size(); i += pool.num_threads()) {
                if (!thread_caches[t].is_unchanged(i, parts[i].compute_signature())) {
                    parts[i].eval();  // 输入变化，执行求值
                }
            }
        });
    }
    pool.wait_all();
}
```

### 5.3 延迟事件用批量合并 + 时间戳排序

```cpp
// Per-thread 局部队列：无锁追加，定期合并
struct ThreadLocalEventQueue {
    std::vector<Event> local_buffer;

    void push(Event e) {
        local_buffer.push_back(e);  // 无锁，仅本线程访问
    }

    // 在 barrier 后将本地事件合并到全局队列
    std::vector<Event> flush() {
        return std::move(local_buffer);  // 交出所有权
    }
};

// 全局调度器：合并所有线程事件后按时间戳排序
struct GlobalEventScheduler {
    std::vector<Event> global_queue;

    void merge_and_sort(std::vector<std::vector<Event>>& thread_queues) {
        size_t total = 0;
        for (auto& tq : thread_queues) total += tq.size();
        global_queue.reserve(total);

        for (auto& tq : thread_queues) {
            global_queue.insert(global_queue.end(), tq.begin(), tq.end());
        }

        // 按时间戳排序（可用并行排序如 TBB parallel_sort）
        std::sort(global_queue.begin(), global_queue.end(),
                  [](const Event& a, const Event& b) { return a.time < b.time; });
    }
};
```

### 5.4 检查清单

#### 4-State 逻辑
- [ ] 是否使用 2-bit 分离编码（abits/bbits）？
- [ ] 单 bit 运算是否使用 16-byte LUT 避免分支？
- [ ] 多驱动 net 是否使用 per-thread 局部缓存 + 合并阶段？
- [ ] 是否实现 2-state fast path：输入无 X/Z 时回退到布尔运算？
- [ ] 状态快照是否按线程分片，checkpoint 仅保存脏页？

#### 增量评估
- [ ] 是否使用 levelization 静态拓扑排序避免重复求值？
- [ ] 是否实现输入指纹缓存跳过未变化的 partition？
- [ ] 指纹是否存储在独立 cache line（`alignas(64)`）避免 false sharing？
- [ ] 是否使用 SIMD 批量比较多个 partition 的指纹？
- [ ] 负载不均时是否支持动态任务窃取？

#### 延迟模型
- [ ] 事件队列是否使用 per-thread 子桶 + 定期合并，避免全局锁？
- [ ] Inertial delay 的 deschedule 是否在 barrier 后统一处理？
- [ ] 是否支持 delay scaling 加速调试阶段？
- [ ] SDF 多 corner 是否并行运行 MIN/TYP/MAX？
- [ ] 是否使用 calendar queue 分层处理不同时间尺度的事件？

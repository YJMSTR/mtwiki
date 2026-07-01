---
id: "wiki-cache-and-memory"
title: "Cache与内存优化"
description: "多线程RTL仿真器中的内存布局优化技术：false sharing消除、cache locality、NUMA感知与线程本地存储的综合实践指南"
tags: ["cache", "memory", "false-sharing", "numa", "thread-local", "rtl-sim"]
keywords: ["cache locality", "false sharing", "NUMA", "thread-local storage", "SOA", "AOS", "hot-cold splitting", "alignas"]
related_sources:
  - "source-false-sharing"
  - "source-cache-locality"
  - "source-numa-optimization"
  - "source-thread-local-storage"
  - "source-cpp-memory-model"
last_updated: "2026-07-01"
---

# Cache与内存优化

RTL仿真器在多线程化时，内存访问模式往往比计算本身更决定性能。一个门级求值可能只需几十条指令，但一次跨NUMA节点的内存访问或一次false sharing导致的缓存行失效，就能让性能倒退数倍。本章综合 false sharing 消除、cache locality 优化、NUMA 感知布局和线程本地存储（TLS）四项技术，给出可直接落地的代码级建议。

---

## 1. False Sharing 的检测与消除

### 1.1 为什么 RTL 仿真器特别怕 false sharing

缓存一致性协议以**64字节缓存行**为单位运作。当两个线程各自写一个看似无关的变量，但这两个变量恰好落在同一缓存行时，就会触发 MESI 协议的"乒乓失效"——缓存行在两个核心之间来回传递，吞吐量暴跌 3~10 倍。RTL仿真器中常见的受害者包括：
- 全局的 `std::atomic<int> event_counter[8]`（8线程各写一个元素，全在同一条或两条缓存行上）
- 紧凑的 `struct ThreadState { size_t gate_idx; size_t event_count; } states[16];`
- 多个线程的队列头/尾指针相邻分配

### 1.2 修复：按缓存行对齐 + Padding

C++17 提供 `std::hardware_destructive_interference_size`（通常 64 字节），比硬编码魔数更干净。每个线程的独占状态必须单独占一条缓存行：

```cpp
#include <new>  // hardware_destructive_interference_size

struct alignas(std::hardware_destructive_interference_size) ThreadState {
    size_t current_gate_idx = 0;
    size_t event_count = 0;
    void* local_queue = nullptr;
    // 16 bytes used, 48 bytes padding implicitly by alignas
};

std::vector<ThreadState> thread_states(num_threads);
// 现在 thread_states[0] 和 thread_states[1] 必定在不同缓存行
```

如果数组元素天然小于缓存行，**不要用紧凑数组**存储线程独占的计数器。改为：

```cpp
// 错误：所有 atomic 计数器挤在一起
std::atomic<uint64_t> global_counters[8];  // 64 bytes total, 全部冲突

// 正确：每个计数器独占一行
struct alignas(64) PaddedCounter {
    std::atomic<uint64_t> value{0};
};
std::vector<PaddedCounter> per_thread_counters(num_threads);
```

### 1.3 检测工具

| 工具 | 命令 | 看什么 |
|------|------|--------|
| `perf c2c` | `perf c2c record -a -- sleep 10; perf c2c report` | 跨核缓存行竞争热力图 |
| `pahole` | `pahole -C ThreadState ./simulator` | 结构体字段的缓存行分布 |
| VTune | Microarchitecture → False Sharing | 直观的 false sharing 指标 |

### 1.4 RTL 仿真中的特殊场景：门级数据结构布局审查

用 `pahole` 检查门级节点结构体。如果频繁访问的 `value` 字段和相邻门的 `value` 字段挤在同一条缓存行，即使多线程各访问不同门，也会触发 false sharing。SoA（Structure of Arrays）布局天然免疫这个问题，因为每个属性数组的元素独立访问。

---

## 2. Cache Locality：SOA vs AoS 与 Hot/Cold Splitting

### 2.1 数据布局决定 cache 效率

- **AoS（Array of Structs）**：适合"逐个元素处理所有属性"，但 cache line 利用率低。
- **SoA（Structure of Arrays）**：适合"批量处理单个属性"，每条 cache line 全是有效数据，SIMD 友好。

RTL 仿真中，每个时间步只访问门的**当前值**和**输入列表**，门类型、名称、延迟等是冷数据。AoS 布局会把冷热数据混装，每条 cache line 只有一小部分有效数据。

### 2.2 Hot/Cold Splitting 代码示例

```cpp
struct GateHot {
    uint64_t value;           // 8 bytes — 每个时间步都读/写
    uint32_t num_inputs;      // 4 bytes
    uint32_t input_start_idx; // 4 bytes — 索引到 cold 数组
};  // 16 bytes, 4 个 GateHot  fits in one cache line

struct GateCold {
    GateType type;            // 枚举，初始化时用
    uint32_t delay;           // 静态时序
    char name[32];            // 调试信息
    std::vector<uint32_t> outputs;  // 输出列表（只在事件传播时访问）
};

struct CircuitSoA {
    // Hot 数据：紧凑数组，活跃门处理时线性访问
    std::vector<uint64_t> values;
    std::vector<uint32_t> input_start;
    std::vector<uint32_t> input_count;
    std::vector<uint32_t> input_edges;  // 所有输入边摊平存储

    // Cold 数据：按需访问
    std::vector<GateType> types;
    std::vector<uint32_t> delays;
    std::vector<std::string> names;
};

// 时间步处理：只访问 hot 数据，每条 cache line 包含 4 个门的全部热数据
void eval_time_step(CircuitSoA& c, const std::vector<uint32_t>& active_gates) {
    for (uint32_t gate_idx : active_gates) {
        uint64_t new_val = evaluate_gate(
            gate_idx,
            c.values.data(),
            c.input_edges.data(),
            c.input_start.data(),
            c.input_count.data()
        );
        if (new_val != c.values[gate_idx]) {
            c.values[gate_idx] = new_val;
            schedule_outputs(gate_idx, new_val);
        }
    }
}
```

### 2.3 预取与间接访问优化

如果活跃门列表按拓扑排序编号，访问 `values[gate_idx]` 是近似线性的，硬件预取器能自动工作。但对于输入边遍历（`input_edges` 中的索引），需要软件预取：

```cpp
for (size_t i = 0; i < active_gates.size(); ++i) {
    uint32_t g = active_gates[i];
    // 预取下 4 个门的 value，覆盖 L2→L1 的 ~12ns 延迟
    if (i + 4 < active_gates.size()) {
        uint32_t next_g = active_gates[i + 4];
        __builtin_prefetch(&circuit.values[next_g], 0, 3);  // 0=read, 3=temporal locality
    }
    evaluate_gate(g);
}
```

> **操作原则**：预取距离通常 8~16 个 cache line，太近则预取未完成，太远则数据被踢出。RTL 仿真中 4~8 个门之后的数据通常足够。

---

## 3. NUMA：First-Touch、Thread Pinning 与跨节点通信成本

### 3.1 NUMA 的代价

现代多路服务器上，本地内存访问延迟约 **~90ns**，远程内存访问延迟约 **~300ns**，带宽只有本地的 1/4。Linux 的 **first-touch** 策略意味着：如果主线程一次性 `malloc` 整个电路状态，所有内存都在 node 0，其他节点的线程访问时全部变成远程访问。

### 3.2 First-Touch 初始化

```cpp
// 错误：主线程分配，所有内存集中在 node 0
std::vector<uint64_t> gate_values(total_gates);

// 正确：每个线程 touch 自己的分区，内存分配到对应 NUMA 节点
#pragma omp parallel
{
    int tid = omp_get_thread_num();
    for (size_t g = partition_start[tid]; g < partition_end[tid]; ++g) {
        gate_values[g] = initial_value(g);  // first-touch 触发本地分配
    }
}
```

### 3.3 Thread Pinning

```cpp
#include <sched.h>
#include <pthread.h>

void pin_thread_to_cpu(int cpu_id) {
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(cpu_id, &cpuset);
    pthread_setaffinity_np(pthread_self(), sizeof(cpuset), &cpuset);
}

// 使用 libnuma 更精确（绑定到 NUMA 节点）
#include <numa.h>

void pin_to_numa_node(int node_id) {
    numa_run_on_node(node_id);       // 绑定线程到 NUMA 节点
    numa_set_localalloc();            // 后续分配使用本地内存
}
```

### 3.4 NUMA 与 False Sharing 的叠加效应

如果多个 NUMA 节点的线程访问同一缓存行，不仅触发 false sharing，还叠加了跨节点互连带宽瓶颈（Intel QPI ~25.6 GB/s vs 本地 DDR4 ~100 GB/s）。**可写数据必须 NUMA-localize**，只读数据（如标准单元库、真值表）可用 `numactl --interleave=all` 均匀分布以利用全节点带宽。

### 3.5 RTL 仿真中的可操作建议

1. **按 NUMA 节点分区电路图**：在图划分时，每个分区分配到 NUMA 节点，处理线程绑定到对应节点。
2. **跨分区边（cut edges）批量化通信**：每时间步同步一次，而非每次事件传播都跨节点。
3. **监控远程访问**：`perf stat -e node-loads,node-load-misses` 检查跨节点访问比例。

---

## 4. Thread-Local Storage：Per-Thread Event Pool 与 Accumulator

### 4.1 TLS 不是零成本，但可以做到接近零成本

TLS 访问速度取决于 TLS model：
- **Local-exec**：2 条指令（x86-64: `mov %fs:offset, %reg`），最快
- **Initial-exec**：3 条指令
- **General-dynamic**：需要调用 `__tls_get_addr`，最慢

C++20 `constinit` 可强制编译期初始化，让 `thread_local` 达到 `__thread` 的性能：

```cpp
// 有动态初始化：首次访问调用 wrapper 函数
thread_local std::vector<int> buf;

// 编译期初始化：直接 local-exec，零开销
constinit thread_local uint64_t event_counter = 0;
```

### 4.2 Per-Thread Event Pool

```cpp
struct EventPool {
    alignas(64) std::vector<Event> free_list;
    alignas(64) std::vector<Event> allocated;
    size_t next_idx = 0;
};

constinit thread_local EventPool* g_event_pool = nullptr;

Event* alloc_event() {
    if (!g_event_pool) {
        g_event_pool = new EventPool();
        g_event_pool->allocated.reserve(4096);
    }
    if (g_event_pool->next_idx < g_event_pool->allocated.size()) {
        return &g_event_pool->allocated[g_event_pool->next_idx++];
    }
    // 批量扩展，避免频繁分配
    g_event_pool->allocated.emplace_back();
    return &g_event_pool->allocated[g_event_pool->next_idx++];
}

void free_event(Event* e) {
    // 在 TLS pool 中，"释放"只需重置状态，不归还 OS
    e->reset();
    // 可选：加入 free_list 复用
}
```

### 4.3 Per-Thread Accumulator + 批量合并

全局统计量是 false sharing 的经典温床。每个线程维护本地计数器，按时间片批量汇总：

```cpp
struct alignas(64) ThreadAccumulator {
    uint64_t events_processed = 0;
    uint64_t gates_evaluated = 0;
    uint64_t cache_misses = 0;  // 可扩展更多指标
};

// 每个线程的本地计数器（TLS + 缓存行对齐）
constinit thread_local ThreadAccumulator local_acc;

// 全局汇总（每 1000 个时间步或缓冲区满时合并）
ThreadAccumulator global_acc;
std::mutex global_acc_mutex;

void flush_accumulator() {
    ThreadAccumulator local_copy = local_acc;
    local_acc.events_processed = 0;
    local_acc.gates_evaluated = 0;
    local_acc.cache_misses = 0;

    std::lock_guard<std::mutex> lock(global_acc_mutex);
    global_acc.events_processed += local_copy.events_processed;
    global_acc.gates_evaluated += local_copy.gates_evaluated;
    global_acc.cache_misses += local_copy.cache_misses;
}
```

> **RTL 仿真天然适合批量汇总**：事件驱动特性使得"每 1000 个时间步合并一次"对统计精度几乎无影响，但彻底消除了跨核缓存流量。

### 4.4 避免 TLS 在 hot loop 中重复加载

编译器在函数边界可能无法证明 `thread_local` 未被修改，导致每次循环重新加载 `%fs` 基址：

```cpp
// 低效：每次循环都重新加载 thread_local 地址
for (size_t i = 0; i < n; ++i) {
    local_acc.events_processed++;  // 可能每次重新解析 TLS 偏移
}

// 高效：缓存到局部变量，循环结束后写回
uint64_t local_count = local_acc.events_processed;
for (size_t i = 0; i < n; ++i) {
    local_count++;
}
local_acc.events_processed = local_count;
```

---

## 5. 综合检查清单

在部署 RTL 仿真器多线程化之前，逐条确认：

- [ ] 所有 per-thread 状态数组使用 `alignas(64)` 或 `alignas(std::hardware_destructive_interference_size)`
- [ ] 门级数据使用 SoA + Hot/Cold Split，活跃门处理时只访问 hot 数组
- [ ] 电路状态按 NUMA 节点 first-touch 初始化，线程绑定到对应节点
- [ ] 全局统计量使用 per-thread accumulator + 批量合并，而非直接写全局原子变量
- [ ] 事件分配使用 TLS event pool，避免跨线程 `malloc` 竞争
- [ ] 使用 `perf c2c` 或 VTune 验证运行时不存在隐藏的 false sharing
- [ ] 只读 LUT 使用 `numactl --interleave=all`，可写数据严格 NUMA-localize
- [ ] 热循环中的 `thread_local` 变量缓存到局部寄存器变量

---

## 参考来源

- [source-false-sharing](source-false-sharing.md) — False sharing 检测与修复
- [source-cache-locality](source-cache-locality.md) — AoS/SoA、Hot/Cold Split、预取
- [source-numa-optimization](source-numa-optimization.md) — NUMA 架构、first-touch、thread pinning
- [source-thread-local-storage](source-thread-local-storage.md) — TLS model、per-thread allocator、TCMalloc/jemalloc
- [source-cpp-memory-model](source-cpp-memory-model.md) — 原子操作、内存序、fence

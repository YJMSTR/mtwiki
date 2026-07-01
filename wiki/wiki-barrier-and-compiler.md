---
id: "wiki-barrier-and-compiler"
title: "同步屏障与编译器优化"
description: "RTL仿真器多线程同步的屏障变体选择、编译器优化链（PGO/LTO/BOLT）与并行框架（OpenMP/TBB/C++17）的工程实践指南"
tags: ["barrier", "synchronization", "compiler-optimization", "PGO", "LTO", "BOLT", "OpenMP", "TBB", "rtl-sim"]
keywords: ["centralized barrier", "tree barrier", "dissemination barrier", "sense-reversal", "PGO", "LTO", "BOLT", "OpenMP", "TBB", "std::execution::par", "-march=native", "profile-guided optimization"]
related_sources:
  - "source-barrier-variants"
  - "source-pgo-lto"
  - "source-parallel-frameworks"
last_updated: "2026-07-01"
---

# 同步屏障与编译器优化

RTL 仿真器的多线程模型通常将电路划分到多个线程，每个时间步需要 barrier 同步。屏障的选择直接决定了 scaling 天花板——在 16 线程的规模下，一个糟糕的 barrier 可能让同步开销占据整个时间步的 50% 以上。与此同时，编译器优化链（PGO → LTO → BOLT）可以为仿真器的计算密集型内核带来 10%~25% 的额外加速，而并行框架（OpenMP / TBB / C++17）的选择则影响调度灵活性和负载均衡。本章将三者打通，给出可直接落地的工程方案。

---

## 1. 屏障变体对比：Centralized vs Tree vs Dissemination vs Sense-Reversal

### 1.1 核心结论先行

Mellor-Crummey 与 Scott 的经典论文论证了一个核心观点：**忙等同步的内存/互联竞争并非不可避免**。通过让每个线程仅在本地可访问的 flag 上自旋，可以用纯软件算法实现 O(1) 远程引用每次锁获取，以及 O(1) 或 O(log P) 的 barrier 同步。

### 1.2 屏障变体详细对比

| Barrier 类型 | 关键路径 | 总流量 | 是否需要原子操作 | 是否本地自旋 | 空间复杂度 | 最佳适用场景 |
|-------------|---------|--------|---------------|------------|-----------|------------|
| **Centralized (Sense-Reversal)** | O(1) | O(P) ~ O(P²) | Fetch&Add | ❌ 竞争同一点 | O(1) | 小 P（≤4），广播缓存一致性 |
| **Software Combining Tree** | O(log P) | O(P) | Fetch&Add | ❌ 动态分配 | O(P) | 中等 P，缓存一致性机器 |
| **Dissemination** | O(log P) | O(P log P) | 仅 Load/Store | ✅ **纯本地自旋** | O(P log P) | 无缓存一致性 / 高并发网络 |
| **Tournament** | O(log P) | O(P) | 无 | 部分 | O(P) | 无高级原子指令的旧架构 |
| **MCS Tree (4-ary + Central)** | O(log P) | O(P) | Fetch&Add | ✅ | O(P) | **广播缓存一致性，大 P（推荐）** |

> **注**："总流量"在缓存一致性机器上指 cache line invalidation 数量；在非一致性机器上指网络消息数。

### 1.3 Centralized Sense-Reversal Barrier（C 实现）

```c
typedef struct {
    _Atomic int counter;
    _Atomic bool sense;
    int n_threads;
} central_barrier_t;

void central_barrier_init(central_barrier_t *b, int n) {
    b->counter = n;
    b->sense = false;
    b->n_threads = n;
}

void central_barrier_wait(central_barrier_t *b) {
    bool local_sense = !atomic_load(&b->sense);
    if (atomic_fetch_sub(&b->counter, 1) == 1) {
        // 最后一个到达的线程：重置计数器，翻转 sense 唤醒所有等待者
        atomic_store(&b->counter, b->n_threads);
        atomic_store(&b->sense, local_sense);
    } else {
        while (atomic_load(&b->sense) != local_sense) {
            cpu_relax();  // PAUSE 指令，降低功耗与总线竞争
        }
    }
}
```

- **流量分析**：所有线程读取同一 `sense` 变量，释放时产生 P 次 invalidation。O(P) 操作在关键路径上。
- **陷阱**：Sense-reversal 解决了新旧轮次误读问题，但无法解决所有线程竞争同一缓存行的根本问题。
- **RTL 适用性**：仅在 2~4 线程的极简场景下可用，超过 4 线程后 cache line 乒乓将主导开销。

### 1.4 Dissemination Barrier（C 实现）

```c
#define MAX_THREADS 64
#define LOGP 6

typedef struct {
    bool flags[LOGP][2];  // [round][parity]，每个线程私有结构
} dis_barrier_t;

// 按线程分配，确保不同 cache line（需要上层保证对齐）
static dis_barrier_t barriers[MAX_THREADS];

void dis_barrier_wait(int my_id, int parity, int n_threads) {
    int logn = (int)ceil(log2(n_threads));
    for (int k = 0; k < logn; ++k) {
        int partner = (my_id + (1 << k)) % n_threads;
        // 通知 partner 我已到达本轮
        atomic_store_explicit(
            (_Atomic bool*)&barriers[partner].flags[k][parity],
            true, memory_order_release
        );
        // 等待 partner 的通知
        while (!atomic_load_explicit(
            (_Atomic bool*)&barriers[my_id].flags[k][parity],
            memory_order_acquire
        )) {
            cpu_relax();
        }
    }
}
```

- **流量分析**：每轮每个线程恰好写 1 次、读 1 次，总流量 O(P log P)。
- **关键优势**：每个线程**只在自己的 `flags` 数组上自旋**，绝对不产生远程自旋。`barriers` 数组应保证每个线程的元素位于独立的 cache line（`alignas(64)`）。
- **关键路径**：log₂ P 轮，每轮并行两两同步。
- **RTL 适用性**：非常适合固定线程数、高频同步的 RTL 仿真器。P log P 总流量在现代 CPU 的缓存一致性广播机制下，小常数开销往往比树 barrier 更可控。

### 1.5 MCS Tree Barrier（4-ary 到达树 + 中央唤醒）

```c
typedef struct {
    _Atomic int count;   // 到达子节点计数
    _Atomic bool sense;  // 本地 sense 标志
} tree_node_t;

static tree_node_t nodes[MAX_THREADS];
static _Atomic bool global_sense = false;

void mcs_tree_barrier_wait(int my_id, int n_threads) {
    bool local_sense = !atomic_load(&global_sense);
    int parent = (my_id - 1) / 4;
    
    // 到达阶段：向上计数
    if (atomic_fetch_add(&nodes[my_id].count, 1) == 3) {
        // 我是最后一个到达的子节点，通知父节点
        if (my_id == 0) {
            // 根节点：所有线程已到达，翻转全局 sense
            atomic_store(&global_sense, local_sense);
        } else {
            atomic_fetch_add(&nodes[parent].count, 1);
        }
    }
    
    // 等待阶段：根节点唤醒后全局 sense 翻转
    if (my_id == 0) return;  // 根节点无需等待
    while (atomic_load(&global_sense) != local_sense) {
        cpu_relax();
    }
    
    // 唤醒子节点（由父节点向下传播）
    for (int child = 4*my_id + 1; 
         child <= 4*my_id + 4 && child < n_threads; 
         ++child) {
        atomic_store(&nodes[child].sense, local_sense);
    }
}
```

- **流量分析**：到达阶段 O(P) 总流量，唤醒阶段 O(P) 总流量。关键路径 O(log₄ P)。
- **适用场景**：缓存一致性广播系统，根节点翻转 `global_sense` 时，广播 invalidation 比逐层传播更快。
- **RTL 适用性**：如果线程有层级化分组（如 per-NUMA-node 分组），4-ary 树可以匹配硬件拓扑，减少跨 socket 流量。

---

## 2. 选择策略：哪种 barrier 在 N=16 时最优

### 2.1 选择矩阵

| 场景 | 推荐 Barrier | 理由 |
|------|-------------|------|
| **2~4 线程，通用设计** | Centralized Sense-Reversal | 实现最简单，代码量最小，4 线程内竞争可控 |
| **8~16 线程，x86 共享内存** | **MCS Tree (4-ary)** | 关键路径短，匹配缓存一致性广播，NUMA 拓扑友好 |
| **8~16 线程，追求可移植性** | **Dissemination** | 纯 Load/Store，无原子指令依赖，本地自旋保证零远程竞争 |
| **16~64 线程，大规模多路服务器** | MCS Tree (8-ary) + 层级拓扑 | 匹配 NUMA 层级，减少跨 socket 流量 |
| **超过 64 线程 / 分布式内存** | Dissemination 或 Message-Passing | 避免共享内存一致性协议的 collapse |
| **RTL 仿真器，每周期 barrier** | **Dissemination 或 MCS Tree** | 固定线程数、高频同步、可静态分配 flag 数组 |

### 2.2 RTL 仿真器专用建议

对于 RTL 仿真器（如 Verilator）的多线程模型，每个时间步需要 barrier 同步：

1. **避免纯中心化 barrier**：如果仿真器使用 `pthread_barrier` 或自研计数器，高频时间步会导致大量 cache line 乒乓，尤其在 NUMA 机器上。
2. **Dissemination Barrier 的推荐度**：线程数相对固定（编译时确定），且 flag 可静态分配，可实现零远程自旋。虽然 O(P log P) 总消息量，但在现代 CPU 的缓存一致性广播机制下，小常数开销往往比树 barrier 更可控。
3. **MCS Tree 的 NUMA 优势**：如果 RTL 仿真器有层级化的线程分组（如 per-socket 分组），4-ary 树结构可以匹配 NUMA 拓扑，减少跨 socket 流量。
4. **Linux futex 的启发**：现代 futex 已实现 `FUTEX_WAIT_MULTIPLE` 等机制，本质上将内核态排队与用户态自旋结合。若仿真器使用自研线程池，可借鉴：忙等若干次 spin 后 fallback 到 futex，避免 CPU 空转浪费功耗。

---

## 3. PGO 三阶段：Instrumentation → LTO → Post-Link (BOLT/Propeller)

### 3.1 三阶段链路概览

```
源码 ──→ 编译期 PGO ──→ 链接期 LTO ──→ 后链接期 BOLT/Propeller
         (5%~15% 提升)    (2%~5% 提升)     (2%~5% 提升)
         分支预测/内联    跨模块优化      代码重排/热冷分离
```

| 阶段 | 工具 | 输入 | 输出 | 典型收益 | 编译时间开销 |
|------|------|------|------|----------|-------------|
| 编译期 PGO | Clang/GCC `-fprofile-*` | 运行时剖面数据 | 热点内联/分支布局 | 5%~15% | 2.0x (训练) + 1.5x (优化编译) |
| 链接期 LTO | Clang `-flto=thin/fat`, GCC `-flto` | 全程序 IR | 跨模块内联/去虚函数 | 2%~5% | 1.5~2.0x |
| 后链接期 BOLT | `llvm-bolt` | 采样 perf 数据 | 重排函数/基本块 | 2%~5% | 1.2x (后处理) |
| **合计** | | | | **10%~25%** | **显著增加** |

> 数据来源：PGO 综述论文 (Ji et al., 2025)、resvg/legba/Symbolicator 实际工程 benchmark。

### 3.2 RTL 仿真器为什么特别适合 PGO

RTL 仿真器（如 Verilator）属于**计算密集型、控制流复杂、热点函数集中**的应用，是 PGO/LTO 的理想目标：

1. **Verilator 的 Thread PGO 潜力**：Verilator 将 RTL 编译为 C++ 模型，多线程模式下每个时间步调度逻辑复杂，热点函数（如 `eval()`、`change()`）如果被内联或代码布局优化，可显著降低 I-Cache miss。
2. **LTO 的跨模块优化**：RTL 仿真器通常生成大量 `.cpp` 文件，标准编译模式下函数内联无法跨文件。LTO 允许全程序视角的 dead code elimination 和 devirtualization，对模型中大量虚函数（如多态信号处理）特别有益。
3. **BOLT 的适用性评估**：RTL 仿真器生成的二进制通常不如 Chromium 那样庞大（>100MB），BOLT 的收益可能不显著。但如果仿真器链接了庞大的标准库或第三方库，BOLT 仍有潜力（实际工程中 resvg/legba 的 BOLT 几乎无额外收益）。

### 3.3 Clang/LLVM PGO 完整流程（Instrumentation-based）

```bash
# ===== Stage 1: 编译 instrumented 版本 =====
clang++ -O3 -fprofile-instr-generate -flto=thin \
    -march=native \
    -o simulator_inst main.cpp model.cpp scheduler.cpp

# ===== Stage 2: 运行训练负载（必须是代表性工作负载）=====
# 注意：instrumented binary 运行时会慢 20%~50%，预留足够时间
mkdir -p prof
LLVM_PROFILE_FILE="prof/simulator_%p.profraw" \
    ./simulator_inst --benchmark typical_workload.v

# 多线程场景：%p 为每个进程生成独立文件，避免并发写入冲突
# 如果使用的是 pthread，每个线程共享一个文件句柄，需要更细粒度控制：
# LLVM_PROFILE_FILE="prof/simulator_%p_%m.profraw"  # %m = 线程标识

# ===== Stage 3: 合并多线程/多进程产生的 profile 文件 =====
llvm-profdata merge -sparse \
    -o simulator.profdata prof/simulator_*.profraw

# ===== Stage 4: 使用 profile 重新编译优化版本 =====
clang++ -O3 -fprofile-instr-use=simulator.profdata \
    -flto=thin -march=native \
    -o simulator_opt main.cpp model.cpp scheduler.cpp
```

**关键点**：
- `LLVM_PROFILE_FILE` 中的 `%p` 在多线程环境下为每个进程生成独立文件。
- **Thin LTO vs Fat LTO**：Thin LTO 编译速度快 3~5 倍，适合迭代开发；Fat LTO 全程序 IR 合并，优化更激进，适合最终发布构建。
- **训练集代表性至关重要**：PGO 训练集必须覆盖真实运行路径，否则性能可能下降（resvg 案例）。对于 RTL 仿真器，训练集应包含典型的设计规模和 toggle rate，而非极简 testbench。

### 3.4 GCC FDO 流程

```bash
# Step 1: 编译并生成 profile
gcc -O3 -fprofile-generate -flto -o simulator_inst main.c model.c
./simulator_inst --training-data

# Step 2: 使用 profile 优化构建
gcc -O3 -fprofile-use -fprofile-correction -flto \
    -march=native -o simulator_opt main.c model.c
```

- `-fprofile-correction` 在训练数据与优化构建不完全一致时（如条件编译差异），可修正不一致的 profile 计数。

### 3.5 BOLT 后链接优化（Post-Link）

```bash
# 前提：链接时保留重定位信息
clang++ -O3 -fprofile-instr-use=merged.profdata -flto=thin \
    -Wl,--emit-relocs -march=native \
    -o simulator_prebolt main.cpp

# 使用 perf 采样（或 LLVM sampling）
perf record -e cycles:u -o perf.data -- ./simulator_prebolt workload

# 转换 perf 数据为 BOLT 格式
perf2bolt ./simulator_prebolt -p perf.data -o perf.fdata

# 运行 BOLT 优化
llvm-bolt ./simulator_prebolt -o simulator_bolt \
    -b perf.fdata \
    -reorder-blocks=ext-tsp \
    -reorder-functions=hfsort+ \
    -split-functions \
    -split-all-cold \
    -dyno-stats
```

- `dyno-stats` 会打印优化前后的动态指令数、I-Cache miss、分支预测失误等对比。
- **BOLT 在中小规模二进制上的收益有限**：resvg 和 legba 的实测中，BOLT 几乎无额外提升。如果 RTL 仿真器二进制 < 50MB，可跳过 BOLT，专注 PGO+LTO。

### 3.6 实际工程 Benchmark 参考

| 项目 | 配置 | 运行时间/吞吐 | 二进制大小 | 来源 |
|------|------|-------------|-----------|------|
| resvg | Release | 276 s | 3.6 MiB | resvg#765 |
| resvg | + LTO | 262 s (-5.1%) | 3.1 MiB | resvg#765 |
| resvg | + LTO + PGO | 247 s (-10.5%) | 4.8 MiB | resvg#765 |
| resvg | + LTO + PGO + BOLT | 247 s (无额外收益) | 8.7 MiB | resvg#765 |
| Symbolicator | Release | 2616 req/s | — | symbolicator#1334 |
| Symbolicator | + LTO + PGO + PLO | 3898 req/s (+49%) | — | symbolicator#1334 |

---

## 4. OpenMP / TBB / C++17 Parallel Algorithms 在 RTL 仿真中的适用性

### 4.1 三条技术路线对比

| 特性 | OpenMP | Intel TBB / oneTBB | C++17 `std::execution::par` |
|------|--------|-------------------|---------------------------|
| 调度模型 | 编译器指令 + 运行时线程池 | **Work-stealing 任务队列** | 依赖标准库后端（通常 TBB/OpenMP） |
| 动态负载均衡 | 静态/guided 调度为主 | **自动 work-stealing** | 取决于后端 |
| 任务图/DAG | 有限（task depend 较复杂） | **flow_graph 原生支持** | 不支持 |
| 过度订阅鲁棒性 | 差（线程数 > 核心时性能骤降） | **良**（内置线程池管理） | 取决于后端 |
| 跨平台一致性 | 良 | 良 | **差**（libc++ 可能回退串行） |
| 编译依赖 | 编译器支持即可 | 需链接 `-ltbb` | 需后端库支持 |

### 4.2 RTL 仿真器中的适用场景

| 仿真器模块 | 推荐框架 | 理由 |
|-----------|---------|------|
| **模块级 `eval()` 调度**（动态复杂度差异大） | **TBB** | Work-stealing 自动平衡负载，无需手动 chunk size |
| **位向量/矩阵操作**（数据并行） | **OpenMP** | `#pragma omp simd` 高效利用 AVX2/AVX-512 |
| **跨平台可移植代码** | **TBB** | `std::execution::par` 在 macOS/Clang 上可能 silently fallback 到串行 |
| **混合架构** | **TBB + OpenMP** | TBB 负责任务级并行，OpenMP 负责数据级并行 |

### 4.3 TBB `parallel_for` 与 `flow_graph` 示例

```cpp
#include <tbb/parallel_for.h>
#include <tbb/blocked_range.h>
#include <tbb/flow_graph.h>

// --- 数据并行：模块 eval 批量执行 ---
void tbb_eval_modules(const std::vector<Module*>& modules) {
    tbb::parallel_for(
        tbb::blocked_range<size_t>(0, modules.size()),
        [&](const tbb::blocked_range<size_t>& r) {
            for (size_t i = r.begin(); i != r.end(); ++i) {
                modules[i]->eval();  // 各模块复杂度不同，work-stealing 自动平衡
            }
        }
    );
}

// --- 动态任务图：RTL 模块依赖 DAG ---
void tbb_module_dag() {
    tbb::flow::graph g;
    
    tbb::flow::function_node<int, int> alu_node(g, tbb::flow::unlimited,
        [](int) { return alu_eval(); });
    tbb::flow::function_node<int, int> reg_node(g, tbb::flow::unlimited,
        [](int) { return regfile_eval(); });
    tbb::flow::function_node<int, int> mem_node(g, tbb::flow::unlimited,
        [](int) { return mem_eval(); });
    
    // 建立依赖边：ALU → Regfile → Mem
    tbb::flow::make_edge(alu_node, reg_node);
    tbb::flow::make_edge(reg_node, mem_node);
    
    alu_node.try_put(0);
    g.wait_for_all();  // 等待 DAG 完成
}
```

### 4.4 OpenMP SIMD 向量操作示例

```cpp
#include <omp.h>

// 位向量批量操作：适合 OpenMP SIMD
void simd_bitvector_op(const uint64_t* in_a, const uint64_t* in_b, 
                       uint64_t* out, size_t n_words) {
    #pragma omp parallel for simd schedule(static)
    for (size_t i = 0; i < n_words; ++i) {
        out[i] = in_a[i] & in_b[i];  // AND 门向量级模拟
    }
}
```

### 4.5 C++17 `std::execution::par` 的陷阱

```cpp
#include <execution>
#include <algorithm>
#include <vector>

void std_parallel_for(std::vector<double>& v) {
    std::for_each(std::execution::par, v.begin(), v.end(),
        [](double& x) { x = heavy_compute(x); });
}
```

| 陷阱 | 影响 | 规避 |
|------|------|------|
| **macOS / libc++ 回退串行** | 性能只有 1x | 使用 TBB 或 OpenMP 直接替代 |
| **ForwardIterator 低效** | 并行开销 > 收益 | 确保使用 Random Access Iterator |
| **GCC 未链接 TBB 后端** | 编译通过但运行异常慢 | 显式链接 `-ltbb` 或 `-fopenmp` |

### 4.6 常见性能陷阱速查

| 陷阱 | 症状 | 解决方案 |
|------|------|----------|
| 过度订阅 | 线程数 > 逻辑核心，性能骤降 | `omp_set_num_threads(物理核心数)` 或 `OMP_PROC_BIND=close` |
| False Sharing | 扩展性差，即使小数据量也慢 | `alignas(64)` 或按 cache line 对齐 per-thread 数据 |
| 负载不均衡 | 部分核心空闲，部分核心满载 | `schedule(dynamic)` 或 `schedule(guided)`，或用 TBB |
| 任务粒度过细 | 调度开销 > 计算时间 | 设置串行 cutoff（如 `if (n < 1000) return serial()`） |
| 隐式 barrier | `#pragma omp for` 后自动 barrier | 使用 `nowait` 消除不必要的同步，但需数据依赖分析 |
| 内存带宽瓶颈 | 核心数增加但性能不增 | 减少数据搬移，使用 NUMA-aware allocator |

---

## 5. 编译器优化选项汇总表

### 5.1 编译选项速查表

| 选项 | 阶段 | Clang | GCC | 作用 | RTL 仿真器建议 |
|------|------|-------|-----|------|---------------|
| `-O3` | 编译 | ✅ | ✅ | 激进优化（内联、循环展开、向量化） | **必开** |
| `-march=native` | 编译 | ✅ | ✅ | 启用本机 SIMD（AVX2/AVX-512） | **必开** |
| `-flto=thin` | 链接 | ✅ | — | 跨模块内联、去虚函数 | **推荐** |
| `-flto` | 链接 | ✅ | ✅ | Fat LTO，全程序 IR 合并 | 最终发布构建 |
| `-fprofile-instr-generate` | 编译 | ✅ | — | 生成 instrumented 版本 | PGO Stage 1 |
| `-fprofile-instr-use` | 编译 | ✅ | — | 使用剖面数据优化 | PGO Stage 4 |
| `-fprofile-generate` | 编译 | — | ✅ | GCC 版 instrumentation | PGO Stage 1 |
| `-fprofile-use` | 编译 | — | ✅ | GCC 版 profile 使用 | PGO Stage 2 |
| `-fprofile-correction` | 编译 | — | ✅ | 修正 profile 计数不一致 | 推荐添加 |
| `-Wl,--emit-relocs` | 链接 | ✅ | ✅ | 保留重定位信息供 BOLT | BOLT 前置 |
| `-fopenmp` | 编译 | ✅ | ✅ | 启用 OpenMP | 数据并行场景 |
| `-ltbb` | 链接 | ✅ | ✅ | 链接 TBB 运行时 | 任务并行场景 |
| `-DNDEBUG` | 编译 | ✅ | ✅ | 禁用 assert | **发布构建必开** |
| `-fno-omit-frame-pointer` | 编译 | ✅ | ✅ | 保留帧指针（profiling 需要） | 性能分析时开启 |

### 5.2 推荐构建配置

```bash
# ===== 开发迭代配置（编译快，优化足够）=====
clang++ -O3 -march=native -flto=thin -DNDEBUG \
    -fopenmp -ltbb \
    -o simulator_dev main.cpp model.cpp

# ===== 性能发布配置（PGO + LTO）=====
# Stage 1: Instrumentation
clang++ -O3 -march=native -flto=thin \
    -fprofile-instr-generate \
    -DNDEBUG -fopenmp -ltbb \
    -o simulator_inst main.cpp model.cpp

# Stage 2: Training
LLVM_PROFILE_FILE="prof/sim_%p.profraw" ./simulator_inst --training

# Stage 3: Merge
llvm-profdata merge -sparse -o sim.profdata prof/sim_*.profraw

# Stage 4: Optimized build
clang++ -O3 -march=native -flto=thin \
    -fprofile-instr-use=sim.profdata \
    -DNDEBUG -fopenmp -ltbb \
    -o simulator_release main.cpp model.cpp

# ===== 极致配置（加 BOLT，仅大二进制推荐）=====
# 链接时加 --emit-relocs
# 然后 perf record → perf2bolt → llvm-bolt
```

---

## 6. 综合检查清单

### 6.1 屏障选择

- [ ] 线程数 ≤ 4：Centralized Sense-Reversal 足够简单。
- [ ] 线程数 8~16：优先使用 **Dissemination Barrier**（纯本地自旋）或 **MCS Tree**（匹配缓存广播）。
- [ ] 线程数 > 16：MCS Tree (8-ary) 按 NUMA 层级分组，减少跨 socket 流量。
- [ ] 验证 barrier 实现中所有 per-thread 状态已使用 `alignas(64)` 隔离。
- [ ] 考虑在忙等若干次后 fallback 到 futex，避免空转功耗。

### 6.2 编译器优化

- [ ] 所有发布构建使用 `-O3 -march=native -DNDEBUG`。
- [ ] 启用 Thin LTO（`-flto=thin`）获得跨模块内联收益。
- [ ] 若时间允许，运行 PGO 流程（instrument → train → optimize），预期 5%~15% 加速。
- [ ] 若二进制 > 100MB，尝试 BOLT；否则 PGO+LTO 已足够。
- [ ] 使用 `perf stat -e instructions,cycles,cache-misses,branch-misses` 验证优化效果。

### 6.3 并行框架

- [ ] 模块级动态调度 → TBB `parallel_for` / `flow_graph`。
- [ ] 位向量/矩阵数据并行 → OpenMP `simd`。
- [ ] 避免 `std::execution::par` 作为默认后端，跨平台一致性差。
- [ ] 设置串行 cutoff 避免任务粒度过细。
- [ ] 使用 `alignas(64)` 隔离 per-thread 数据，消除 false sharing。

---

## 参考来源

- [source-barrier-variants](source-barrier-variants.md) — Centralized/Tree/Dissemination/MCS Barrier 算法与性能对比
- [source-pgo-lto](source-pgo-lto.md) — PGO、LTO、BOLT 编译器优化链与工程 benchmark
- [source-parallel-frameworks](source-parallel-frameworks.md) — OpenMP、TBB、C++17 Parallel Algorithms 对比与陷阱

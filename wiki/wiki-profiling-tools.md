---
id: "wiki-profiling-tools"
title: "性能剖析与基准测试工具"
description: "多线程RTL仿真器的三层诊断体系：Layer1 缓存竞争检测（perf c2c）→ Layer2 热点定位（perf record/VTune）→ Layer3 因果分析（Coz），附可复现基准测试与CI集成方案"
tags: ["profiling", "perf", "vtune", "coz", "benchmark", "ci", "rtl-sim"]
keywords: ["perf c2c", "false sharing", "perf record", "火焰图", "VTune", "Threading Analysis", "Coz", "causal profiling", "benchmark", "性能回归", "CI"]
related_sources:
  - "source-linux-perf-tools"
  - "source-vtune-uprof"
  - "source-coz-causal-profiling"
last_updated: "2026-07-01"
---

# 性能剖析与基准测试工具

多线程RTL仿真器的优化很容易陷入"改了代码、性能反而下降"的困境。根本原因是：多线程程序中**CPU耗时≠瓶颈**，优化一个不在关键路径上的热点毫无意义。本章建立三层诊断体系，从缓存竞争（Layer1）到热点定位（Layer2）再到因果分析（Layer3），并给出可复现的基准测试方案和CI集成检查清单。

---

## 1. 三层诊断法概述

| 层级 | 工具 | 核心问题 | 典型输出 | 诊断目标 |
|------|------|---------|---------|---------|
| **Layer 1** | `perf c2c`, `perf stat` | "内存布局是否破坏并行性？" | cache-line竞争热力图、IPC指标 | 排除 false sharing、NUMA 问题 |
| **Layer 2** | `perf record/report`, VTune | "CPU时间花在哪里？" | 函数热点、调用栈火焰图 | 定位热点函数、锁竞争、同步开销 |
| **Layer 3** | Coz | "优化这个热点能提升整体性能吗？" | 因果曲线、虚拟加速比例 | 验证优化在 critical path 上 |

> **原则**：绝不跳过Layer 1。false sharing可以让多线程性能腰斩，且肉眼不可见。在未确认`perf c2c` clean之前，所有Layer 2/3的诊断结果都可能被内存布局问题污染。

---

## 2. Layer 1 — 缓存竞争与基础指标诊断

### 2.1 perf stat：建立基准指标

```bash
# 基础统计：cycles, instructions, cache-misses, branch-misses
perf stat -r 5 -d ./my_sim --benchmark --cycles=100000

# -r 5: 重复 5 次，输出均值和置信区间
# -d: 详细计数器（含 IPC、cache-miss rate）

# 多线程 RTL 仿真器特别关注的事件
perf stat -r 5 -e \
    cycles,instructions,L1-dcache-load-misses,L1-icache-load-misses,\
    cache-misses,cache-references,branch-misses,context-switches,\
    cpu-migrations,node-loads,node-load-misses \
    ./my_sim --benchmark --threads=16
```

**关键指标解读**：

| 指标 | 正常范围 | 警戒线 | RTL 仿真器含义 |
|------|---------|-------|---------------|
| **IPC** | 1.5–2.5 | <1.0 | 流水线严重停滞，多线程负优化常见信号 |
| **cache-misses rate** | <5% | >10% | 缓存布局或false sharing问题 |
| **L1-icache-load-misses** | 低 | MPKI > 50 | 代码体积过大，前端瓶颈 |
| **L1-dcache-load-misses** | 低 | 随线程数线性增长 | 可能 false sharing 或 NUMA 远程访问 |
| **branch-misses** | <1% | >5% | 分支预测失败严重，考虑无分支化 |
| **context-switches** | 低 | 与线程数成正比 | 线程 oversubscription 或锁竞争 |
| **cpu-migrations** | 接近0 | >100/秒 | 线程在CPU间迁移，破坏NUMA locality |
| **node-load-misses** | 接近0 | >10% | 跨NUMA节点访问，内存布局错误 |

**示例：false sharing vs 无 false sharing 的对比**（来自ARM Learn数据）：

```bash
perf stat -r 3 -d ./false_sharing 1
# 结果: 13.01s, IPC 0.74, L1-dcache-load-misses 262M

perf stat -r 3 -d ./no_false_sharing 1
# 结果: 6.49s, IPC 1.70, L1-dcache-load-misses 38K
```

**核心启示**：同样指令数，false sharing能让IPC腰斩、运行时间翻倍。

### 2.2 perf c2c：检测 False Sharing 与 True Sharing

`perf c2c`（Cache-to-Cache）是Linux内核4.2+引入的专用子命令，记录所有load/store内存地址，匹配不同线程访问同一cacheline的情况，并标注HITM（Hit in Modified cacheline）。

```bash
# 1. 调低 perf 权限（需要 root 或 CAP_PERFMON）
sudo sh -c 'echo 1 > /proc/sys/kernel/perf_event_paranoid'

# 2. 录制 c2c 数据（-a = all CPUs, -u = user-space only）
perf c2c record -a -u -- ./my_sim --benchmark --threads=16

# 3. 生成报告（TUI 或 stdio 输出）
perf c2c report
perf c2c report --stdio

# 4. 带调用栈记录（精确定位到源码行）
perf c2c record -g -- ./my_sim --benchmark --threads=16
perf c2c report -NN --stdio  # 按 HITM 排序的详细视图
```

**关键报告字段解读**：

```
# Trace Event Information
Load Local HITM     :  3402   # 同 NUMA 节点命中 Modified cacheline
Load Remote HITM    : 12757   # 跨 NUMA 节点命中 Modified cacheline ← false sharing 元凶
LLC Misses to Remote Cache (HITM) : 57.3%  # 高 = 严重的 false sharing
```

**c2c report 的 TUI 操作**：
- 按 `d` 查看cacheline详情，包括各线程在cacheline内的偏移量
- `Source:Line` 列直接映射到导致contention的源码行

**RTL 仿真器中的典型 false sharing 场景**：
- 全局的 `std::atomic<int> event_counter[16]`（16线程各写一个元素，全挤在两条缓存行）
- 紧凑的 `struct ThreadState { size_t gate_idx; size_t event_count; } states[16];`
- 多个线程的队列头/尾指针相邻分配

### 2.3 perf sched：调度分析（锁等待的补充）

当线程不是因缓存竞争，而是因锁等待导致性能下降时：

```bash
# 记录调度事件，分析线程等待时间
sudo perf record -e sched:sched_switch -g --call-graph dwarf -- ./my_sim
sudo perf report -n --stdio --no-call-graph -T

# 查看线程上下文切换频次
perf sched map
perf sched latency
```

这可以暴露`pthread_cond_wait` → `futex_wait`等热点路径，补充`perf c2c`的不足。

---

## 3. Layer 2 — 热点定位与微架构分析

### 3.1 perf record/report：函数级热点定位

```bash
# 记录默认事件（cycles）并带调用栈（-g）
perf record -g ./my_sim --benchmark --threads=16

# 报告热点（交互式 TUI）
perf report

# 只看用户态，减少内核噪音
perf record -u -g ./my_sim

# 指定采样频率（99Hz 避免与系统定时器对齐）
perf record -F 99 -g ./my_sim

# 指定关注 cache-misses 热点
perf record -e cache-misses,cache-references -g ./my_sim

# 生成文本报告方便离线分析
perf report -n --stdio > report.txt
```

`perf report` 按 `Overhead` 排序显示最热的函数。在RTL仿真器多线程优化中，特别关注：

| 热点函数 | 含义 | 行动 |
|---------|------|------|
| `pthread_mutex_lock` / `futex_wait` | 锁竞争严重 | 改用无锁队列、读写锁或分片锁 |
| `std::atomic` / `__sync_*` | shared counter 或 true sharing | 改为 per-thread accumulator + 批量合并 |
| 数据结构 accessor 占比高 | false sharing 或 NUMA remote | 检查 `perf c2c`，改用 SoA + 对齐 |
| `eval_xxx` / `compute_xxx` 占比高 | 正常计算热点 | 进入 Layer 3 (Coz) 验证是否值得优化 |

### 3.2 FlameGraph：可视化热点

```bash
# 生成火焰图（需安装 FlameGraph 工具）
git clone https://github.com/brendangregg/FlameGraph.git
perf record -g ./my_sim
perf script | ./FlameGraph/stackcollapse-perf.pl | ./FlameGraph/flamegraph.pl > perf.svg
```

横向为时间占比，纵向为调用栈，一眼看出多线程程序中哪个调用链是瓶颈。

### 3.3 Intel VTune：线程级诊断与微架构分析

VTune的**Threading Analysis**是多线程程序诊断利器，提供精确的等待时间地图。

```bash
# 采集 Threading Analysis（HWE + 上下文切换）
vtune -collect threading \
    -knob sampling-mode=hw \
    -knob enable-stack-collection=true \
    ./my_sim --benchmark --threads=16

# 采集 Microarchitecture Analysis（Top-Down）
vtune -collect uarch-exploration -knob sampling-interval=1 ./my_sim

# 采集 Memory Access 分析（检测 false sharing / NUMA 问题）
vtune -collect memory-access -knob sampling-mode=hw ./my_sim

# 查看结果
vtune -report summary -result-dir r000th
vtune -report hotspots -result-dir r000th
vtune -report callstacks -result-dir r000th

# 对比两次采集（验证优化效果）
vtune -compare r000th r001th
```

**VTune Threading Analysis 核心指标**：

| 问题类型 | VTune 指标 | 典型表现 | RTL 仿真器场景 |
|---------|-----------|---------|--------------|
| 锁竞争 | Inactive Sync Wait Time | 线程在mutex/condvar上长时间等待 | 全局事件队列锁 |
| 线程 oversubscription | Preemption Wait Time | 线程被OS调度器抢占 | 线程数 > 物理核心数 |
| 线程运行时开销 | Spin and Overhead Time | 自旋锁或线程库内部开销 | 轻量级 barrier 的自旋 |
| I/O 阻塞 | Wait Time on I/O objects | 文件/网络 I/O 阻塞 | VCD 转储、日志写入 |

**Top-Down 微架构分析**将CPU瓶颈分为四大类：

1. **Frontend Bound**：指令取指/译码瓶颈（I-cache miss、ITLB miss）→ RTL仿真器常见
2. **Backend Bound → Memory Bound**：L1/L2/L3/DRAM Bound → 多线程缓存竞争
3. **Bad Speculation**：分支预测失败和流水线flush → 活动感知仿真中的分支问题
4. **Retiring**：有效退休的uops比例（越高越好）

### 3.4 AMD uProf：AMD平台验证

如果目标部署在AMD EPYC服务器上，应使用uProf做最终验证：

```bash
# 启动 CPU Profile 采集
AMDuProfCLI collect --config tbp -o ./uprof_results ./my_sim

# 生成报告（时间线 + 热点）
AMDuProfCLI report -i ./uprof_results -o ./uprof_report.html

# 查看函数级热点
AMDuProfCLI report -i ./uprof_results --function-summary

# 采集特定事件（如 L3 cache miss）
AMDuProfCLI collect --event L3Miss -o ./uprof_l3 ./my_sim
```

AMD Zen架构的跨chiplet内存访问延迟更高，uProf的System Profile能精确展示跨CCD访问分布。

---

## 4. Layer 3 — Coz 因果分析：验证优化价值

### 4.1 为什么需要 Coz？

传统剖析器回答"哪行代码最耗时"，但多线程程序中**CPU耗时≠瓶颈**。Coz回答"优化哪行代码能带来多少整体性能提升"，通过**virtual speedup**技术模拟加速效果。

```bash
# 基本用法（程序需带 -g 编译，保留 DWARF 调试信息）
g++ -O2 -g -pthread -o my_sim my_sim.cpp

# 运行 Coz 因果剖析
coz run --- ./my_sim --benchmark --threads=16

# 指定输出文件名
coz run -o my_sim.coz --- ./my_sim

# 限制剖析范围（只剖析特定源文件）
coz run --source-scope src/engine/% --binary-scope MAIN --- ./my_sim

# 生成并查看因果剖析报告（自动打开浏览器）
coz plot

# 文本模式报告（适合 CI 流水线）
coz plot --text
```

### 4.2 Progress Points：定义RTL仿真的工作单元

RTL仿真器天然有"工作单元"——仿真事件、仿真周期、事务级请求。用`COZ_PROGRESS`标记：

```cpp
#include "coz.h"

// 吞吐量模式：每个仿真周期完成一个工作单元
void simulate_cycle() {
    eval_all_modules();
    update_registers();
    advance_time();
    COZ_PROGRESS;  // ← 标记一个工作单元完成
}

// 延迟模式：测量事件处理的延迟
void handle_event(const Event& e) {
    COZ_BEGIN("event_latency");   // 事件处理开始
    // ... 处理事件 ...
    COZ_END("event_latency");     // 事件处理结束
}
```

### 4.3 Coz 报告解读

Coz输出**因果曲线图**：X轴为虚拟加速比例（0%~100%），Y轴为吞吐量提升百分比，每条线对应一个被测试的源码行。

**理想的优化目标**：
- 曲线斜率大、且延伸到较高X值的代码行
- 意味着：即使只优化20%，整体吞吐也提升明显

**危险的优化陷阱**：
- 传统剖析器显示"热点"，但Coz曲线平坦 → 优化该行不会提升整体性能（不在critical path上）
- 多线程程序中常见：某个线程的CPU热点实际上在等待另一个线程，优化它只会让它等得更快

### 4.4 三层诊断的完整流程示例

```bash
# === Layer 1: 排除内存布局问题 ===
perf stat -r 5 -e cycles,instructions,cache-misses ./my_sim --threads=16
# IPC = 0.6 (严重偏低) → 怀疑 false sharing

perf c2c record -a -u -- ./my_sim --threads=16
perf c2c report -NN --stdio
# 发现 ThreadState::event_count 在 cacheline 0x7f3a... 上 HITM 12757 次
# 修复：给 ThreadState 加 alignas(64)

# 修复后验证
perf stat -r 5 -e cycles,instructions,cache-misses ./my_sim --threads=16
# IPC = 1.8 (恢复正常) → 进入 Layer 2

# === Layer 2: 定位热点 ===
perf record -g ./my_sim --threads=16
perf report
# 热点: eval_gate() 35%, pthread_mutex_lock 25%
# 锁竞争占 25% → 优化调度器

# === Layer 3: 验证优化价值 ===
coz run --- ./my_sim --threads=16
coz plot --text
# eval_gate() 因果曲线斜率大 → 优化该函数确实提升整体性能
# pthread_mutex_lock 曲线平坦 → 优化锁本身无意义，需要重构调度器架构
```

---

## 5. 为 RTL 仿真器建立可复现的基准测试

### 5.1 可复现性原则

性能测量若无可复现性，就无优化价值。RTL仿真器基准测试必须控制：

1. **硬件固定**：同一台服务器，禁止CPU频率缩放（`cpufreq` 设置 `performance`）
2. **线程绑定**：固定线程到物理核心，避免上下文迁移
3. **预热**：忽略前N个cycle的冷启动，只测量稳态
4. **统计**：重复运行≥5次，报告均值、标准差、最小值

### 5.2 基准测试脚本模板

```bash
#!/bin/bash
# benchmark.sh — RTL 仿真器可复现基准测试

set -euo pipefail

SIMULATOR="./my_sim"
BENCHMARK="typical_workload"
THREADS=(1 2 4 8 16)
CYCLES=100000
WARMUP=10000
REPEATS=5

# 固定 CPU 频率
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# 清除文件系统缓存（可选，用于测量冷启动）
# echo 3 | sudo tee /proc/sys/vm/drop_caches

for t in "${THREADS[@]}"; do
    echo "=== Benchmarking with $t threads ==="
    
    for r in $(seq 1 $REPEATS); do
        # 绑定到前 t 个物理核心（假设双路，每路 32c/64t）
        CORES=$(seq -s, 0 $((t-1)))
        
        # 使用 taskset 绑定，numactl 限制 NUMA 节点
        WALL_TIME=$(taskset -c $CORES numactl --cpunodebind=0 --membind=0 \
            $SIMULATOR --benchmark=$BENCHMARK \
                       --threads=$t \
                       --cycles=$CYCLES \
                       --warmup=$WARMUP \
                       --print-time-only)
        
        echo "  Run $r: ${WALL_TIME}ms"
    done
done
```

### 5.3 关键度量指标

| 指标 | 计算方法 | 目标 |
|------|---------|------|
| **Wall-clock Time** | `time ./my_sim` | 绝对性能，越低越好 |
| **IPC** | `perf stat -e cycles,instructions` | 每周期指令数，>1.5 正常 |
| **Speedup** | `T_1 / T_N` | N 线程的加速比，理想 = N |
| **Efficiency** | `Speedup / N` | 扩展效率，>0.5 可接受，>0.7 良好 |
| **L1 I-cache MPKI** | `perf stat -e L1-icache-load-misses,instructions` | <50 正常，<20 优秀 |
| **False Sharing HITM** | `perf c2c report` | 接近 0 |
| **Lock Wait %** | VTune Threading Analysis | <10% |
| **Effective CPU Utilization** | VTune | 每增加线程至少达到理想值的70% |

**Speedup 与 Efficiency 计算示例**：

```bash
# 1 线程: 10.0s, 4 线程: 3.5s, 16 线程: 2.0s
Speedup_4 = 10.0 / 3.5 = 2.86x
Efficiency_4 = 2.86 / 4 = 71.5%  # 良好

Speedup_16 = 10.0 / 2.0 = 5.0x
Efficiency_16 = 5.0 / 16 = 31.3%  # 差，需深入诊断
```

---

## 6. 检测和量化同步开销

### 6.1 同步开销的测量方法

同步开销是多线程RTL仿真器的首要瓶颈。量化方法：

```bash
# 方法 1: perf sched 量化等待时间
sudo perf record -e sched:sched_switch -g -- ./my_sim --threads=16
sudo perf sched latency
# 看 "Average delay" 和 "Maximum delay" 列

# 方法 2: VTune Threading Analysis 的 Inactive Sync Wait Time
vtune -collect threading ./my_sim
# 查看 Bottom-up 视图中 Inactive Sync Wait Time 占比

# 方法 3: 自定义轻量级计时（代码插桩）
```

### 6.2 自定义同步开销计时（代码插桩）

```cpp
#include <chrono>
#include <atomic>

struct SyncMetrics {
    alignas(64) std::atomic<uint64_t> barrier_wait_ns{0};
    alignas(64) std::atomic<uint64_t> mutex_lock_ns{0};
    alignas(64) std::atomic<uint64_t> queue_wait_ns{0};
    alignas(64) std::atomic<uint64_t> total_cycles{0};
};

SyncMetrics g_sync_metrics;

class ScopedTimer {
    std::atomic<uint64_t>& counter;
    std::chrono::high_resolution_clock::time_point start;
public:
    explicit ScopedTimer(std::atomic<uint64_t>& c) : counter(c) {
        start = std::chrono::high_resolution_clock::now();
    }
    ~ScopedTimer() {
        auto end = std::chrono::high_resolution_clock::now();
        counter.fetch_add(
            std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count(),
            std::memory_order_relaxed
        );
    }
};

// 使用示例
void barrier_wait() {
    ScopedTimer timer(g_sync_metrics.barrier_wait_ns);
    pthread_barrier_wait(&g_barrier);
}

// 报告：同步开销占比
void report_sync_overhead() {
    uint64_t barrier_ns = g_sync_metrics.barrier_wait_ns.load();
    uint64_t total_ns = g_sync_metrics.total_cycles.load();
    double barrier_pct = 100.0 * barrier_ns / total_ns;
    printf("Barrier wait: %.2f%% of total time\n", barrier_pct);
}
```

> 注意：per-thread计数器使用`alignas(64)`避免false sharing，批量汇总到全局。

---

## 7. CI 集成：性能回归检测

### 7.1 CI 流水线中的性能测试

```yaml
# .github/workflows/perf-regression.yml
name: Performance Regression

on: [push, pull_request]

jobs:
  benchmark:
    runs-on: self-hosted  # 专用 benchmark 服务器，硬件固定
    steps:
      - uses: actions/checkout@v4
      
      - name: Build Release
        run: cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build
      
      - name: Run Benchmark (1, 4, 16 threads)
        run: |
          ./scripts/benchmark.sh > benchmark_results.json
      
      - name: Compare with Baseline
        run: |
          python3 ./scripts/compare_baseline.py \
            --current benchmark_results.json \
            --baseline .baseline/benchmark_results.json \
            --threshold 15  # IPC 下降 15% 或 wall-time 增加 15% 即告警
      
      - name: Upload Results
        uses: actions/upload-artifact@v4
        with:
          name: benchmark-results
          path: benchmark_results.json
```

### 7.2 性能回归检测脚本（Python）

```python
#!/usr/bin/env python3
# compare_baseline.py

import json
import sys

THRESHOLD_IPC_DROP = 0.15   # IPC 下降 15% 告警
THRESHOLD_TIME_INCREASE = 0.15  #  wall-time 增加 15% 告警

def load_results(path):
    with open(path) as f:
        return json.load(f)

def compare(current, baseline):
    failed = False
    for threads in current["results"]:
        t = threads["threads"]
        c = threads
        b = next(b for b in baseline["results"] if b["threads"] == t)
        
        ipc_drop = 1.0 - c["ipc"] / b["ipc"]
        time_increase = c["wall_time_ms"] / b["wall_time_ms"] - 1.0
        
        if ipc_drop > THRESHOLD_IPC_DROP:
            print(f"❌ IPC regression @ {t} threads: {b['ipc']:.2f} → {c['ipc']:.2f} "
                  f"({ipc_drop*100:.1f}% drop)")
            failed = True
        if time_increase > THRESHOLD_TIME_INCREASE:
            print(f"❌ Wall-time regression @ {t} threads: {b['wall_time_ms']:.0f} → "
                  f"{c['wall_time_ms']:.0f}ms ({time_increase*100:.1f}% increase)")
            failed = True
    
    return failed

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", required=True)
    parser.add_argument("--baseline", required=True)
    args = parser.parse_args()
    
    current = load_results(args.current)
    baseline = load_results(args.baseline)
    
    if compare(current, baseline):
        sys.exit(1)  # CI 失败
    print("✅ All performance metrics within threshold")
```

### 7.3 CI 中的分层诊断集成

```bash
# CI 流水线中的快速诊断步骤（每次 PR 运行）

# 1. 快速 perf stat（1 次运行，~30秒）
perf stat -e cycles,instructions,cache-misses,branch-misses \
    ./my_sim --quick-benchmark --threads=16

# 2. 如果 IPC < 1.0 或 cache-miss rate > 10%，触发深度诊断
# 3. 深度诊断：perf c2c（~5分钟）
perf c2c record -a -u -- ./my_sim --benchmark --threads=16
perf c2c report --stdio | grep -E "HITM|Cacheline" | head -20

# 4. 如果 HITM > 0，PR 自动失败并提示修复 false sharing
```

---

## 8. 综合检查清单

### 每次优化前的诊断流程

- [ ] **Layer 1**: `perf stat -r 5` 建立基线，记录 IPC、cache-misses、branch-misses
- [ ] **Layer 1**: `perf c2c record` 确认无 false sharing（HITM ≈ 0）
- [ ] **Layer 1**: `perf stat -e node-load-misses` 确认无跨 NUMA 访问
- [ ] **Layer 2**: `perf record -g` 定位热点函数和锁竞争
- [ ] **Layer 2**: 若锁竞争 > 10%，用 VTune Threading Analysis 精确量化等待时间
- [ ] **Layer 3**: Coz 验证"优化该热点是否提升整体性能"（因果曲线斜率）
- [ ] **执行优化**
- [ ] **验证**: `perf stat -r 5` 对比优化前后，确认 IPC 提升或 wall-time 下降
- [ ] **扩展性验证**: 测试 1/2/4/8/16 线程，绘制 Speedup vs Threads 曲线
- [ ] **回归测试**: 确保单线程性能未下降（常见陷阱：优化多线程但劣化单线程）

### 基准测试环境检查清单

- [ ] 使用专用 benchmark 服务器，硬件配置文档化
- [ ] CPU 频率固定为 `performance` governor，禁用 Turbo Boost
- [ ] 线程绑定到物理核心（`taskset` / `numactl`），禁止超线程干扰
- [ ] 内存绑定到同一 NUMA 节点（`numactl --membind=0`）
- [ ] 每次运行前清除或控制文件系统缓存状态
- [ ] 预热阶段（≥10000 cycles）排除冷启动噪声
- [ ] 重复运行 ≥5 次，报告均值、标准差、最小值
- [ ] 每次 benchmark 同时记录 `perf stat` 指标，而非仅 wall-time

### 工具链前置检查

```bash
# 确认 perf 可用且权限正确
cat /proc/sys/kernel/perf_event_paranoid  # 应为 1 或 -1
which perf && perf --version

# 确认 VTune 安装（可选，Intel 平台）
which vtune && vtune --version

# 确认 Coz 安装（可选，Layer 3 因果分析）
which coz && coz --version

# 确认 FlameGraph 工具（可选，可视化）
ls ./FlameGraph/flamegraph.pl
```

---

## 参考来源

- [source-linux-perf-tools](source-linux-perf-tools.md) — Linux perf 统计、采样、false sharing 检测
- [source-vtune-uprof](source-vtune-uprof.md) — Intel VTune Threading/Microarchitecture Analysis、AMD uProf
- [source-coz-causal-profiling](source-coz-causal-profiling.md) — Coz 因果剖析器、virtual speedup、progress points

---
title: Linux perf 与 perf c2c 在多线程 C++ 程序中的性能剖析
description: 涵盖 perf stat、perf record、perf c2c 检测 false sharing、cache-misses 分析，以及 Linux perf 工具链在多线程程序中的实战用法。
source_url: "https://www.brendangregg.com/perf.html"
source_type: "doc"
author: "Brendan Gregg, Joe Mario, Denis Bakhvalov, Red Hat"
date: "2016-2025"
tags: ["profiling", "perf", "false-sharing", "cache-misses", "multithreading", "linux"]
keywords: ["perf c2c", "perf stat", "perf record", "HITM", "cache contention", "CPU profiling"]
capture_date: "2026-07-01"
---

# Linux perf 与 perf c2c 在多线程 C++ 程序中的性能剖析

## 来源

- URL: https://www.brendangregg.com/perf.html
- URL: https://easyperf.net/blog/2019/12/17/Detecting-false-sharing-using-perf
- URL: http://joemario.github.io/blog/2016/09/01/c2c-blog/
- URL: https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/8/html/monitoring_and_managing_system_status_and_performance/detecting-false-sharing_monitoring-and-managing-system-status-and-performance
- URL: https://learn.arm.com/learning-paths/servers-and-cloud-computing/false-sharing-arm-spe/how-to-4/
- 类型: doc / blog
- 作者: Brendan Gregg, Joe Mario, Denis Bakhvalov, Red Hat, ARM
- 日期: 2016-2025

## 摘要

Linux `perf`（perf_events）是 Linux 内核自带的性能剖析基础设施，无需插桩即可利用 CPU 硬件性能计数器（PMC）进行采样和统计。`perf stat` 提供高层 CPU 指标（cycles、instructions、cache-misses、branch-misses），`perf record` 捕获函数级热点，而 `perf c2c`（Cache-to-Cache）专用于检测多线程程序中的 cache-line contention，包括 false sharing 和 true sharing。在多线程 RTL 仿真器优化中，perf 是定位“负优化”根源、验证“正优化”效果的第一道防线。

## 关键要点

### 1. `perf stat` — 快速评估整体性能指标

`perf stat` 是最轻量的 perf 用法，不生成 `perf.data`，只输出计数器统计，适合 A/B 对比。

```bash
# 基础统计：cycles, instructions, cache-misses, branch-misses
perf stat ./my_multithreaded_sim

# 指定缓存相关事件（多线程程序中 cache-misses 通常剧增）
perf stat -e cache-misses,cache-references ./my_sim

# 多核监控，只看 CPU 0-3
perf stat -C 0-3 -e cycles,instructions,cache-misses ./my_sim

# 监控特定进程（适合长时间运行的仿真器进程）
perf stat -p $(pidof my_sim) -I 1000 -e cycles,cache-misses
```

关键指标解读：

| 指标 | 含义 | 多线程场景下的警示 |
|---|---|---|
| `cycles` | CPU 周期总数 | 高不一定坏，要结合 IPC 看 |
| `instructions` | 执行指令数 | 线程增多不应导致指令数爆炸性增长 |
| `IPC` (insns per cycle) | 每周期指令数 | **IPC < 1.0** 通常表示流水线停滞，多线程程序常因锁/缓存竞争导致 IPC 下降 |
| `cache-misses` | 缓存未命中 | 多线程程序中若 cache-miss rate > 10% 需警惕 |
| `cache-references` | 缓存引用次数 | 与 cache-misses 联算 miss rate |
| `L1-dcache-load-misses` | L1 数据缓存未命中 | 线程数增加时若此值暴涨，可能触发 false sharing |
| `context-switches` | 上下文切换次数 | 过多表明线程竞争或 oversubscription |
| `cpu-migrations` | CPU 迁移次数 | 频繁迁移会破坏 NUMA locality |

**示例：false sharing vs 无 false sharing 的对比**（来自 ARM Learn 数据）：

```bash
perf stat -r 3 -d ./false_sharing 1
# 结果: 13.01s, IPC 0.74, L1-dcache-load-misses 262M

perf stat -r 3 -d ./no_false_sharing 1
# 结果: 6.49s, IPC 1.70, L1-dcache-load-misses 38K
```

**核心启示**：同样的指令数，false sharing 能让 IPC 腰斩、运行时间翻倍。

### 2. `perf record` / `perf report` — 函数级热点定位

```bash
# 记录默认事件（cycles）并带调用栈
perf record -g ./my_sim

# 报告热点（交互式 TUI）
perf report

# 只看用户态，减少内核噪音
perf record -u -g ./my_sim

# 指定采样频率（99Hz 避免与系统定时器对齐）
perf record -F 99 -g ./my_sim

# 指定关注 cache-misses 热点
perf record -e cache-misses,cache-references -g ./my_sim

# 生成文本报告方便离线分析
perf report -n > report.txt
```

`perf report` 会按 `Overhead` 排序显示最热的函数。在多线程程序中，特别关注：
- `pthread_mutex_lock` / `futex_wait` 等同步原语占比高 → 锁竞争严重
- `std::atomic` 或 `__sync_*` 操作占比高 → 可能 shared counter 或 true sharing
- 某个数据结构的 accessor 函数占比高 → 可能 false sharing 或 NUMA remote access

### 3. `perf c2c` — 检测 False Sharing 与 True Sharing

`perf c2c` 是 Linux 内核 4.2+ 引入的专用子命令，用于分析 cache-line contention。它记录所有 load/store 的内存地址，匹配不同线程访问同一 cacheline 的情况，并标注 HITM（Hit in Modified cacheline）。

```bash
# 1. 录制 c2c 数据（需要 root 或放宽 perf_event_paranoid）
sudo sh -c 'echo 1 > /proc/sys/kernel/perf_event_paranoid'
perf c2c record -a -u -- ./my_sim

# 2. 生成报告（TUI 或 stdio）
perf c2c report
perf c2c report --stdio

# 带调用栈记录（更精确定位源码行）
perf c2c record -g ./my_sim
perf c2c report

# 过滤只看 HITM 严重的 cacheline
perf c2c report --stdio -NN  # 按 HITM 排序的详细视图
```

**关键报告字段解读**（来自 Joe Mario 博客）：

```
# Trace Event Information
Load Local HITM     :  3402   # 同 NUMA 节点上命中 Modified cacheline
Load Remote HITM    : 12757   # 跨 NUMA 节点命中 Modified cacheline ← false sharing 元凶
LLC Misses to Remote Cache (HITM) : 57.3%  # 此百分比高 = 严重的 false sharing
```

**c2c report 的 TUI 操作**：
- 按 `d` 查看 cacheline 详情，包括各线程在 cacheline 内的偏移量
- `Source:Line` 列直接映射到导致 contention 的源码行

### 4. `perf sched` — 多线程调度分析

```bash
# 记录调度事件，分析线程等待时间
sudo perf record -e sched:sched_switch -g --call-graph dwarf -- ./my_sim
sudo perf report -n --stdio --no-call-graph -T

# 查看线程上下文切换频次
perf sched map
perf sched latency
```

这可以补充 `perf c2c` 的不足：当线程不是因缓存竞争，而是因锁等待导致性能下降时，`sched:sched_switch` 能暴露 `pthread_cond_wait` → `futex_wait` 等热点路径。

### 5. 与 FlameGraph 结合生成可视化火焰图

```bash
perf record -g ./my_sim
perf script | stackcollapse-perf.pl | flamegraph.pl > perf.svg
```

横向为时间占比，纵向为调用栈，一眼看出多线程程序中哪个调用链是瓶颈。

## 对 RTL 仿真器多线程化的启示

1. **Baseline 必须先建**：在动手并行化之前，用 `perf stat -e cycles,instructions,cache-misses` 记录单线程基线。任何多线程优化后，必须对比 IPC 和 wall-clock time，避免“多线程负优化”被误认为是 gains。

2. **数据结构布局是 false sharing 重灾区**：RTL 仿真器通常有全局时间戳、事件队列指针、共享统计计数器（如 total gates evaluated）。如果多个线程的私有数据被编译器/分配器恰好放在同一 cacheline，性能会断崖式下跌。`perf c2c record -g` 能精确到结构体字段级别，指导 padding 或按线程分配私有副本。

3. **锁竞争可视化**：仿真器的事件调度循环（`while (!events.empty())`）往往是全局锁。`perf record -g` 若显示 `pthread_mutex_lock` 占比 > 10%，说明调度器是瓶颈。结合 `perf sched` 可以量化等待时间。

4. **NUMA  aware 内存分配**：在双路服务器上，RTL 仿真器的内存 footprint 大。`perf c2c` 中若 `Remote HITM` 高，意味着线程跨 socket 访问内存。应使用 `numa_alloc_onnode()` 或 `libnuma` 将线程绑定到本地 NUMA 节点。

5. **回归测试集成**：`perf stat -r 5`（重复 5 次取平均）适合 CI 流水线中的性能回归检测。可以设定阈值：若某次提交导致 `cache-misses` 增加 20% 或 IPC 下降 15%，自动触发告警。

## 原文摘录

> "`perf c2c` will show you the cachelines where false sharing was detected, the readers and writers to those cachelines, and the offsets where those accesses occur. It also shows pid, tid, instruction addr, function name, binary object names, source file and line number, average load latency, and the NUMA nodes and CPUs involved." — Joe Mario, Intel

> "There is a great tool for detecting cache contention such as false/true sharing: `perf c2c`. It tries to match up store/load addresses for different threads and see if the hit in a modified cacheline occurred." — Denis Bakhvalov, Easyperf

> "Comparing the results you can see the run time is significantly different (13.01 s vs. 6.49 s). The instructions per cycle (IPC) are also notably different, (0.74 vs. 1.70) and look to be commensurate to run time." — ARM Learn, False Sharing Detection

> "A cache miss rate above 10% means cache usage could be improved (e.g., using cache-friendly algorithms)." — Comprehensive Guide to Using perf

## 相关链接

- [Linux perf Examples - Brendan Gregg](https://www.brendangregg.com/perf.html)
- [Detecting false sharing with Data Address Profiling - Easyperf](https://easyperf.net/blog/2019/12/17/Detecting-false-sharing-using-perf)
- [C2C - False Sharing Detection in Linux Perf - Joe Mario](http://joemario.github.io/blog/2016/09/01/c2c-blog/)
- [Red Hat: Detecting false sharing](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/8/html/monitoring_and_managing_system_status_and_performance/detecting-false-sharing_monitoring-and-managing-system-status-and-performance)
- [ARM Learn: Perform root cause analysis with Perf C2C](https://learn.arm.com/learning-paths/servers-and-cloud-computing/false-sharing-arm-spe/how-to-4/)
- [Profiling Data Structures - LPC 2022](https://lpc.events/event/16/contributions/1200/attachments/1054/2013/Profiling%20Data%20Structures.pdf)
- [FlameGraph 工具](https://github.com/brendangregg/FlameGraph)

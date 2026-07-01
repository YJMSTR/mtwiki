---
title: "Verilator 官方文档：多线程仿真与性能优化"
source_url: "https://verilator.org/guide/latest/verilating.html#multithreading / https://verilator.org/guide/latest/simulating.html"
source_type: "doc"
author: "Verilator Project (Wilson Snyder et al.)"
date: "2024-2025 (latest)"
tags: ["rtl-sim", "multithreading", "verilator", "documentation", "performance", "NUMA", "PGO"]
keywords: ["verilator", "--threads", "macro-task", "thread affinity", "NUMA", "profile-guided optimization", "numactl", "lstopo", "L3 cluster"]
capture_date: "2026-07-01"
---

## 摘要

Verilator 官方文档对多线程仿真的机制、使用限制和性能优化提供了系统性说明。核心要点：

1. **多线程模型层级**：`--threads 1` 仅让库线程安全，允许用户 C++ 测试平台在不同线程中实例化模型；`--threads N`（N≥2）才生成真正的并行模型，其中调用 `eval()` 的线程是 N 个线程之一，其余 N-1 个线程由 Verilated 模型自行创建和管理。

2. **线程-CPU 亲和性**：默认 Linux 调度器假设线程是短命的，常把多线程调度到同一物理核心的超线程上。Verilator 会尝试自动设置线程亲和性（thread affinity），但文档明确建议在**多 L3 集群的 AMD EPYC / Ryzen** 等系统上使用 `numactl` 和 `lstopo` 来绑定到同一 L3 集群内的物理核心，以降低跨集群通信延迟。

3. **Profile-Guided Optimization (Thread PGO)**：Verilator 支持基于运行时剖析的线程任务调度优化。`--prof-pgo` 会生成 `profile.vlt` 文件，记录了各宏任务（macro-task）的实际执行时间；在重新 Verilate 时传入该文件，可替换估计代价，实现更均衡的线程负载分配。文档警告说如果 PGO 数据过期（源码改动），会触发 `PROFOUTOFDATE` 警告。

4. **编译器 PGO**：GCC/Clang 的 `-fprofile-generate` / `-fprofile-use` 对 Verilated 模型通常可带来 **5-15%** 的性能提升，适用于单线程和多线程模型。

5. **超线程 vs 跨 L3 集群的权衡**：文档指出，在某些情况下，使用同一 L3 集群内的超线程（SMT）可能比跨多个 L3 集群使用物理核心性能更好，这取决于模型特性和硬件拓扑。

## 对"稀疏计算RTL仿真器多线程化"的启示

1. **线程亲和性是必要但不充分条件**：Verilator 文档花了大量篇幅讨论 `numactl`、`VERILATOR_NUMA_STRATEGY=none`、`lstopo` 等工具，这说明在多线程 RTL 仿真中，**内存和线程的 NUMA 拓扑感知** 是性能优化的必要手段。但 Issue #2913 表明，如果基础调度模型的同步开销过高，仅靠亲和性无法解决根本问题。

2. **Thread PGO 的启发**：Verilator 的 PGO 通过测量实际 macro-task 运行时间来改进调度，这提示我们——如果设计的稀疏计算模式导致不同周期的活跃信号分布不均，那么**动态的、基于运行时反馈的调度** 可能比静态分区更有优势。对于稀疏计算 RTL，可以考虑设计一个**轻量级周期级计数器**，动态调整线程分配。

3. **跨 L3 集群通信代价**：文档提到 AMD EPYC 多 L3 集群系统上跨集群通信延迟的问题。对于我们的多线程 RTL 仿真器，如果采用类似的分区策略，必须将通信密集的线程绑定到同一 NUMA 节点或同一 L3 集群，否则稀疏计算带来的微小并行收益将被缓存一致性协议开销吞噬。

4. **超线程的意外价值**：在模型线程数超过单 L3 集群物理核心数时，使用同一集群内的超线程可能比跨集群物理核心更好。这提示我们在资源受限的情况下，**局部性优先于并行度**。

## 关键原文摘录

### 多线程基本机制

> With `--threads {N}`, where N is at least 2, the generated model will be designed to run in parallel on N threads. The thread calling eval() provides one of those threads, and the generated model will create and manage the other N-1 threads. It's the client's responsibility not to oversubscribe the available CPU cores.

> Under CPU oversubscription, the Verilated model should not livelock nor deadlock; however, you can expect performance to be far worse than it would be with the proper ratio of threads and CPU cores.

### 线程亲和性与 NUMA

> When running a multithreaded model, the default Linux task scheduler often works against the model by assuming short-lived threads and thus it often schedules threads using multiple hyperthreads within the same physical core. If there is no affinity already set, on Linux only, Verilator attempts to set thread-to-processor affinity in a reasonable way.

> For best performance, use the **numactl** program to (when the threading count fits) select unique physical cores on the same socket.

> On Systems with multiple L3 clusters per socket (e.g., AMD EPYC or Ryzen), consider using **lstopo** to determine the L3 cluster topology of the current system and **numactl** to bind CPUs within a single L3 cluster. This can improve performance for minimal communication latency between threads.

> Sometimes, for model's thread counts that are more than the core count per L3 cluster, using SMTs (hyperthreads) within a single L3 cluster can have better performance than spreading across multiple L3 clusters using physical cores only.

### Thread PGO 机制

> When using multithreading, Verilator computes how long macro tasks take and tries to balance those across threads. If the estimations are incorrect, the threads will not be balanced, leading to decreased performance. Thread PGO allows collecting profiling data to replace the estimates and better optimize these decisions.

> To use Thread PGO, Verilate the model with the `--prof-pgo` option. This will code to the verilated model to save profiling data for profile-guided optimization. Run the model executable. When the executable exits, it will create a profile.vlt file. Rerun Verilator, optionally omitting the `--prof-pgo` option and adding the `profile.vlt` generated earlier to the command line.

> If you provide any profile feedback data to Verilator and it cannot use it, it will issue the `PROFOUTOFDATE` warning that threads were scheduled using estimated costs.

### 编译器 PGO 收益

> Using compiler PGO typically yields improvements of 5-15% on both single-threaded and multithreaded models.

### 性能优化总结

> For best performance, run Verilator with the `-O3 --x-assign fast --x-initial fast --no-assert` options. ... If using Verilated multithreaded, consider overriding Verilator's default thread-to-processor assignment by using `numactl`; see Multithreading.

> If your OS can handle thread assignment for your design and hardware well, consider disabling Verilator's NUMA assignment by setting the `VERILATOR_NUMA_STRATEGY` environment variable to `none`.

> Experience shows that the instruction cache size often limits large models, and reducing code size, if possible, can be beneficial.

## 参考链接

- https://verilator.org/guide/latest/verilating.html#multithreading
- https://verilator.org/guide/latest/simulating.html
- Verilator internals: `docs/internals.rst` (macro-task 概念详解)

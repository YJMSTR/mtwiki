---
title: "NUMA 优化与 Thread Pinning：让内存访问不再跨节点"
source_url: "https://www.abhik.ai/concepts/systems/numa-architecture"
source_type: "blog"
author: "Abhik"
date: ""
tags: ["hpc", "multithreading", "cpp", "numa", "thread-affinity", "memory-locality"]
keywords: ["numa", "thread-pinning", "first-touch", "numactl", "libnuma", "local-memory", "remote-memory"]
capture_date: "2026-07-01"
---

## 来源

- **原文**: [Abhik.ai — NUMA Architecture](https://www.abhik.ai/concepts/systems/numa-architecture)
- **补充**: [Linux numactl man page](https://linux.die.net/man/8/numactl)
- **补充**: [libnuma API Reference](https://man7.org/linux/man-pages/man3/numa.3.html)
- **补充**: [OpenMP Thread Affinity — OMP_PROC_BIND](https://www.openmp.org/spec-html/5.0/openmpse55.html)
- **补充**: [Intel — NUMA Optimization Guide](https://www.intel.com/content/www/us/en/developer/articles/guide/optimizing-applications-for-numa.html)

## 摘要

NUMA（Non-Uniform Memory Access）架构是现代多路服务器的标准设计。在 NUMA 系统中，每个 CPU 插槽（socket）拥有本地内存，访问远程 socket 的内存需要经过 QPI/UPI/Infinity Fabric 互连，**延迟从本地内存的 ~90ns 增加到远程内存的 ~300ns，带宽也显著下降**。这意味着线程和数据如果不在同一个 NUMA 节点上，性能会严重劣化。

Linux 的 **first-touch 策略**规定：内存页被分配到第一个访问它的线程所在的 NUMA 节点。如果所有线程在初始化阶段都由主线程创建数据结构，那么所有内存都在主线程的本地节点，后续其他线程访问这些内存时全部变成远程访问。

Thread pinning（线程亲和性）通过 `sched_setaffinity` 或 `numa_run_on_node` 将线程绑定到特定 CPU 核心，防止 OS 调度器将线程迁移到远程节点。`numactl --physcpubind=0-3 --membind=0 ./program` 可以在命令行强制指定线程和内存分配节点。

## 关键要点

1. **NUMA 拓扑查看**: `numactl --hardware` 显示系统有多少个 NUMA 节点、每个节点有多少核心、本地内存大小。`numastat -m` 显示每个节点的内存使用统计。

2. **First-Touch 分配策略**:
   ```cpp
   // 错误：主线程分配，所有内存都在 node 0
   std::vector<int> data(N);
   
   // 正确：每个线程 touch 自己的数据，内存分配到对应节点
   #pragma omp parallel
   {
       int tid = omp_get_thread_num();
       for (size_t i = tid; i < N; i += num_threads) {
           data[i] = 0;  // first-touch 触发本地分配
       }
   }
   ```

3. **Thread Pinning 代码**:
   ```cpp
   #include <sched.h>
   #include <pthread.h>
   
   void pin_thread_to_cpu(int cpu_id) {
       cpu_set_t cpuset;
       CPU_ZERO(&cpuset);
       CPU_SET(cpu_id, &cpuset);
       pthread_setaffinity_np(pthread_self(), sizeof(cpuset), &cpuset);
   }
   ```
   使用 `libnuma` 更精确：
   ```cpp
   #include <numa.h>
   numa_run_on_node(node_id);      // 绑定到 NUMA 节点
   numa_set_localalloc();           // 本地内存分配
   ```

4. **OpenMP 亲和性**:
   ```bash
   export OMP_PROC_BIND=close   # 线程绑定到相邻核心
   export OMP_PLACES=cores      # 每个线程一个核心
   ```
   `close` 策略将线程依次分配到同一个 socket 的相邻核心，直到 socket 满，再到下一个 socket。`spread` 则将线程均匀分布到所有 socket。

5. **NUMA 与 False Sharing 的叠加效应**: 如果多个 NUMA 节点上的线程访问同一缓存行，不仅触发 false sharing，还叠加了**跨节点互连带宽瓶颈**。Intel QPI 带宽 ~25.6 GB/s，而本地 DDR4-3200 带宽可达 ~100 GB/s。跨节点访问的带宽只有本地的 1/4。

6. **内存交错（Interleave）**: `numactl --interleave=all` 将内存均匀分布在所有 NUMA 节点。对于无法 NUMA-localize 的数据（如只读全局查找表），交错可以利用所有节点的内存带宽。但**可写数据必须 NUMA-localize**，否则交错反而加剧跨节点竞争。

## 对 RTL 仿真器多线程化的启示

**稀疏计算 RTL 仿真器的核心挑战**：电路门级网络是一个巨大的图结构，通常用 CSR（Compressed Sparse Row）或邻接表表示。如果多个线程各自处理一个分区，但分区的数据被随机分配到 NUMA 节点，那么跨分区的边（net）访问会产生大量跨 NUMA 内存访问。**RTL 仿真器的瓶颈不仅是 false sharing，更是跨 NUMA 节点的高延迟内存访问**。

**具体应用建议**:

1. **按 NUMA 节点分区电路图**：在电路图分区（graph partitioning）时，不仅考虑负载均衡，还要将每个分区分配到一个 NUMA 节点。使用 `numa_node_of_cpu()` 查询核心所属节点，确保处理分区 P 的线程绑定到分区 P 所在的节点。
   ```cpp
   #include <numa.h>
   
   void assign_partition_to_numa_node(int partition_id, int numa_node) {
       // 分配分区数据到指定 NUMA 节点
       void* mem = numa_alloc_onnode(partition_size, numa_node);
       // 绑定处理线程到该节点的核心
       int cpu_start = numa_node_to_cpus(numa_node); // 伪代码，需遍历 cpumask
       pin_thread_to_cpu(cpu_start + partition_id % cores_per_node);
   }
   ```

2. **First-touch 初始化门级状态**：在 RTL 仿真启动时，每个线程初始化自己分区的门状态数组。不要由主线程一次性 `malloc` 整个电路状态。
   ```cpp
   // 每个线程初始化自己的分区
   #pragma omp parallel
   {
       int tid = omp_get_thread_num();
       for (size_t g = partition_start[tid]; g < partition_end[tid]; ++g) {
           gate_values[g] = init_value(g);  // first-touch 到本地节点
       }
   }
   ```

3. **只读 LUT（查找表）使用交错分配**：门类型定义、真值表、标准单元库等只读数据可以被所有线程共享。使用 `numactl --interleave=all` 或 `mmap` + `MPOL_INTERLEAVE` 均匀分布，最大化只读带宽。

4. **跨分区边（cut edges）的 NUMA 处理**：在图分区中，跨分区的边（cut edges）是跨线程通信的来源。如果分区 A 和分区 B 被分配到不同 NUMA 节点，这些跨分区边的访问天然是跨 NUMA 的。尽量减少 cut edge 数量（使用 METIS 等图划分工具），并将通信批量化（每时间步同步一次，而非每次事件传播）。

5. **线程绑定策略**：如果系统有 2 个 NUMA 节点，每个 32 核心，而 RTL 仿真使用 16 线程，最佳策略是将 16 线程全部绑定到**同一个 NUMA 节点**，获得最大本地内存带宽。不要为了"利用所有核心"而跨 NUMA 分布，除非数据已经 NUMA-localize。

6. **监控 NUMA 远程访问**：使用 `perf stat -e node-loads,node-load-misses` 监控远程内存访问比例。如果 `node-load-misses` 很高，说明数据布局与线程绑定不匹配。

## 原文摘录

> "Local memory access latency is ~90ns, while remote memory access is ~300ns. The 3-4x difference makes NUMA-aware design critical for high-performance applications."
> — Abhik.ai

> "The first-touch policy allocates memory on the NUMA node of the thread that first accesses it. If the main thread initializes all data, all memory ends up on node 0, and worker threads on other nodes suffer remote access."
> — Linux NUMA documentation

> "Thread affinity prevents the OS scheduler from migrating threads across NUMA nodes, which is essential for maintaining data locality."
> — Intel NUMA Optimization Guide

> "Interleave memory for read-only data to maximize bandwidth. Localize memory for read-write data to minimize latency."
> — numactl best practices

## 相关链接

- [numactl man page](https://linux.die.net/man/8/numactl)
- [libnuma API](https://man7.org/linux/man-pages/man3/numa.3.html)
- [OpenMP Thread Affinity](https://www.openmp.org/spec-html/5.0/openmpse55.html)
- [Intel NUMA Optimization Guide](https://www.intel.com/content/www/us/en/developer/articles/guide/optimizing-applications-for-numa.html)
- [Linux kernel NUMA documentation](https://www.kernel.org/doc/html/latest/admin-guide/mm/numa-memory-policy.html)

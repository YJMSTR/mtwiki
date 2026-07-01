---
title: HugePages 与 Transparent HugePages (THP) 在 HPC 中的 TLB 优化
description: HugePages 与 THP 如何降低 TLB miss、提升内存密集型多线程应用性能，包含 Linux 配置命令与 TLB 监控方法。
source_url: "https://www.abhik.ai/concepts/systems/transparent-huge-pages"
source_type: "blog"
author: "abhik.ai / Alibaba Cloud / arxiv"
date: "2025-02-11"
tags: ["hugepages", "THP", "TLB", "memory-optimization", "HPC", "multi-threading"]
keywords: ["HugePages", "Transparent HugePages", "TLB miss", "hugetlbfs", "MADV_HUGEPAGE", "memory bandwidth"]
capture_date: "2026-07-01"
---

# HugePages 与 Transparent HugePages (THP) 在 HPC 中的 TLB 优化

## 来源

- URL: https://www.abhik.ai/concepts/systems/transparent-huge-pages
- URL: https://www.alibabacloud.com/help/en/alinux/support/performance-tuning-method-related-to-transparent-large-page-thp-in
- URL: https://arxiv.org/html/2603.18690 (TurboMem: THP auto-merging for DPDK)
- URL: https://github.com/smat-dev/tlbperf
- 类型: blog / doc / paper
- 作者: abhik.ai / Alibaba Cloud / TurboMem authors
- 日期: 2025-02-11 / 2025-12-02 / 2026-03-19

## 摘要

在多线程 RTL 仿真器等内存密集型应用中，频繁访问大量分散的小对象会导致页表膨胀，Translation Lookaside Buffer (TLB) 命中率急剧下降。标准 4KB 页面下，TLB 仅能覆盖约 6MB 内存；当工作集达到 10GB 时，绝大多数地址翻译都会触发 TLB miss，每次 miss 需遍历 4 级页表，耗时 10~20 个周期以上。HugePages（2MB / 1GB）和 Transparent HugePages（THP）通过增大页面粒度来扩大 TLB 覆盖范围，减少页表遍历深度，从而显著降低 TLB miss 率并提升内存访问吞吐。本文介绍两者的原理、配置方法与适用场景，并结合 DPDK 和 HPC 实践给出性能数据。

## 关键要点

- **TLB 瓶颈**：4KB 页面下，1536 条 TLB entry 仅能覆盖约 6MB；10GB 工作集的应用几乎 100% TLB miss。2MB HugePage 将单条 TLB 覆盖范围扩大 512 倍，1GB 页面扩大 262,144 倍。
- **THP 自动合并**：Linux 内核在后台将连续的 4KB 页面提升为 2MB 页面，无需应用修改。适合数据库（PostgreSQL +30% 吞吐）、ML 训练（+9%~12%）、分析型 workload（Spark +35%）。
- **显式 HugePages**：通过 `hugetlbfs` 或 `mmap` 直接分配 2MB/1GB 页面，适合需要确定性的低延迟场景（如 DPDK、高频交易）。缺点是需预先预留内存，管理成本高。
- **THP 的副作用**：fork 密集型 workload（如 Apache prefork、Redis bgsave）因 COW 复制 2MB 页面会变慢 2~3 倍；稀疏内存访问模式会浪费带宽和缓存；快速分配/释放周期导致 `khugepaged` 无法成功合并，反而引入延迟抖动。
- **TurboMem 实测**：在 DPDK 100Gbps 场景中，THP auto-merging 比显式 1GB hugepages 提升 28% 吞吐，TLB miss 降低 41%。

## 对 RTL 仿真器多线程化的启示

RTL 仿真器的事件队列、信号网表、门级数据结构通常占用大量内存且生命周期较长。若将这些核心数据结构（如事件池、信号映射表）分配在 HugePages 上，可显著降低 TLB miss，减少内存访问延迟。对于不愿意手动管理 hugepages 的场景，可启用 `madvise` 模式的 THP，在关键内存区域通过 `madvise(MADV_HUGEPAGE)` 提示内核进行大页合并，兼顾性能与部署简便性。需要注意的是，如果仿真器频繁 fork 子进程（如分布式仿真启动），应禁用 THP 或改用显式 hugepages 避免 COW 惩罚。

## 原文摘录

> Every time your program accesses memory, the CPU must translate a virtual address into a physical one... with standard 4 KB pages, even a generous TLB with 1,536 entries only covers about 6 MB of memory. A database with a 10 GB working set will miss the TLB constantly -- over 99.9% of its address space has no TLB entry at any given moment.
> — abhik.ai, Transparent Huge Pages (THP): Reducing TLB Pressure

> THP delivers its greatest benefits to workloads that combine large memory footprints with dense, sequential access patterns... Databases like PostgreSQL, MongoDB, and Redis maintain large buffer pools (often 10 GB or more) and perform sequential scans over huge tables. THP can reduce TLB misses by 60-70% and improve throughput by 15-35%.
> — abhik.ai, THP Performance Impact by Workload Type

> TurboMem achieved up to 28% higher packet throughput and 41% fewer TLB misses than the standard DPDK mempool with explicit hugepages. These results suggest that in low-fragmentation, single-socket environments, THP-backed allocations can match or exceed the performance of static huge pages while simplifying deployment.
> — TurboMem paper (arxiv 2603.18690)

> Huge pages are your friend. x86 supports 4 KB, 2 MB, and 1 GB pages. Larger pages have multiple benefits: they reduce page table depth (2 MB pages skip the bottom level), massively increase TLB reach (one entry covers 512x more memory for 2 MB pages), and keep more page table entries in cache. These effects are multiplicative.
> — smat-dev/tlbperf

## 代码示例：Linux HugePages / THP 配置

```bash
# ===== 1. 查看当前 THP 状态 =====
cat /sys/kernel/mm/transparent_hugepage/enabled
# 输出: [always] madvise never

cat /sys/kernel/mm/transparent_hugepage/defrag
# 输出: [madvise] always defer defer+madvise never

# ===== 2. 推荐配置：defer+madvise（平衡性能与稳定性）=====
sudo bash -c "echo 'defer+madvise' > /sys/kernel/mm/transparent_hugepage/defrag"

# ===== 3. 禁用 THP（fork 密集型或延迟敏感服务）=====
sudo bash -c "echo 'never' > /sys/kernel/mm/transparent_hugepage/enabled"
# 永久禁用（需重启生效）：
sudo grubby --args="transparent_hugepage=never" --update-kernel="/boot/vmlinuz-$(uname -r)"

# ===== 4. 显式预留 2MB HugePages（适合 DPDK / RTL 仿真器常驻内存）=====
# 计算：若需要 16GB hugepage 内存，16GB / 2MB = 8192 页
echo 8192 | sudo tee /proc/sys/vm/nr_hugepages
# 按 NUMA 节点分配：
echo 4096 | sudo tee /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages
echo 4096 | sudo tee /sys/devices/system/node/node1/hugepages/hugepages-2048kB/nr_hugepages

# 查看预留结果
cat /proc/meminfo | grep Huge

# ===== 5. 使用 hugetlbfs 挂载 =====
sudo mkdir -p /mnt/huge
sudo mount -t hugetlbfs none /mnt/huge
# 应用可通过 mmap /mnt/huge 下的文件获取 hugepage 内存
```

```c
// ===== 6. 在代码中提示 THP（madvise 模式）=====
#include <sys/mman.h>

void* allocate_hugepage_hint(size_t size) {
    void* ptr = mmap(NULL, size, PROT_READ | PROT_WRITE,
                     MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (ptr != MAP_FAILED) {
        madvise(ptr, size, MADV_HUGEPAGE);  // 提示内核尝试合并为 THP
    }
    return ptr;
}
```

```bash
# ===== 7. TLB Miss 监控 =====
# 实时监控指定进程的 TLB 未命中率
perf stat -e dTLB-loads,dTLB-load-misses -p $(pgrep -f rtl_simulator) -I 1000

# 生成 TLB miss 火焰图
perf record -e dTLB-load-misses -ag -- sleep 30
perf script | FlameGraph/stackcollapse-perf.pl | FlameGraph/flamegraph.pl > tlb_miss.svg

# 使用 numastat 监控 NUMA 本地/远程访问
watch -n 1 numastat -czm
```

## THP 性能影响按 Workload 分类

| Workload          | 典型提升 | TLB Miss 降低 | 推荐模式 |
|-------------------|----------|---------------|----------|
| PostgreSQL        | +30% 吞吐 | 70% | madvise |
| MongoDB           | +25% 吞吐 | 65% | madvise |
| Redis             | +31% 吞吐 | 68% | madvise |
| ML Training (PyTorch) | +9% 吞吐 | 45% | defer |
| Spark Analytics   | +35% 吞吐 | 72% | madvise |
| Video Encoding    | +18% 吞吐 | 50% | defer |
| Web Fork (Apache prefork) | -28% 吞吐 | — | 禁用 THP |
| Sparse 内存访问   | -22% 吞吐 | — | 禁用 THP |

> 数据来源：abhik.ai 综合各 workload 公开基准测试数据。

## 相关链接

- [Transparent Huge Pages (THP): Reducing TLB Pressure](https://www.abhik.ai/concepts/systems/transparent-huge-pages)
- [Alibaba Cloud Linux THP 性能调优指南](https://www.alibabacloud.com/help/en/alinux/support/performance-tuning-method-related-to-transparent-large-page-thp-in)
- [TurboMem: THP Auto-Merging for DPDK (arxiv)](https://arxiv.org/html/2603.18690)
- [tlbperf: TLB 性能分析与优化](https://github.com/smat-dev/tlbperf)
- [CSDN: 从 TLB 原理到 HugePages 实践](https://wenku.csdn.net/answer/e2xa1pdsgd2)

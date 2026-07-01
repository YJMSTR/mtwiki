---
title: 多线程内存分配器性能对比：jemalloc / tcmalloc / mimalloc
description: jemalloc、tcmalloc、mimalloc 在多线程场景下的设计理念、线程本地缓存机制与实测性能对比，包含 LD_PRELOAD 替换示例。
source_url: "https://github.com/iqbqioza/v8malloc"
source_type: "github-repo"
author: "iqbqioza / youngju.dev"
date: "2026-04-28"
tags: ["memory-allocator", "jemalloc", "tcmalloc", "mimalloc", "thread-local", "multi-threading"]
keywords: ["jemalloc per-thread arena", "tcmalloc size class", "mimalloc thread local", "LD_PRELOAD", "malloc benchmark"]
capture_date: "2026-07-01"
---

# 多线程内存分配器性能对比：jemalloc / tcmalloc / mimalloc

## 来源

- URL: https://github.com/iqbqioza/v8malloc (v8malloc 跨分配器基准测试)
- URL: https://www.youngju.dev/blog/culture/2026-04-15-memory-allocators-malloc-jemalloc-tcmalloc-mimalloc-deep-dive-guide-2025
- 类型: github-repo / blog
- 作者: iqbqioza / youngju.dev
- 日期: 2026-04-28 / 2026-04-15

## 摘要

在 RTL 仿真器等多线程程序中，频繁的小对象分配/释放（门、事件、信号）是常见的性能瓶颈。glibc 的默认 ptmalloc 虽然可用，但在高并发场景下会出现严重的锁竞争和碎片问题。jemalloc、tcmalloc、mimalloc 是当前主流的替代方案，它们通过线程本地缓存（thread-local cache）、细粒度 size class 和减少锁竞争等机制，显著提升多线程分配吞吐。本文对比三者的核心架构与实测性能，并提供在 RTL 仿真器中快速替换分配器的实践方法。

## 关键要点

- **jemalloc** 以低碎片和可观测性见长：采用 per-thread arena + tcache 设计，99% 的分配/释放无需加锁；内置 `prof:true` 堆分析，Facebook/Redis 广泛采用。
- **tcmalloc** 追求极致速度：Thread Cache → Central Cache → Page Heap 三层架构，99.9% 命中线程本地缓存；新版默认 per-CPU 模式，使用 `rseq` 系统调用，数千线程下缓存开销仅与 CPU 数成正比。
- **mimalloc** 强调简洁与局部性：采用线程本地 free list + 非对称跨线程释放（MPSC 队列），跨线程 handoff 性能优异；代码量小，易于嵌入和审计。
- 多线程扩展性实测（64B 固定大小）：8 线程下 tcmalloc 290.8 M ops/s，v8malloc 296.4 M ops/s，而 mimalloc 为 217.5 M ops/s（落后 36%），glibc 为 295.2 M ops/s。
- 对于 RTL 仿真器频繁分配小对象（如 64B ~ 512B 的门/事件结构体）的场景，tcmalloc 或 jemalloc 的线程缓存机制可有效消除锁竞争。

## 对 RTL 仿真器多线程化的启示

RTL 仿真器在事件驱动模型中会高频创建和销毁 `Gate`、`Event`、`Signal` 等小型对象，这些对象通常落在 64B ~ 512B 的 size class 区间内。若使用默认 glibc malloc，多线程并行仿真时 arena 锁竞争将成为首要瓶颈。通过 `LD_PRELOAD` 替换为 jemalloc 或 tcmalloc，可在不修改源码的情况下验证分配器优化的收益。若后续需要更精细的控制，可参考 mimalloc 的轻量设计，为仿真器定制一个 bump/arena 混合分配器，专门管理短生命周期的事件对象。

## 原文摘录

> jemalloc은 스레드마다 **thread cache** 를 유지한다: 할당은 tcache에서 먼저 꺼냄 (락 없음), 해제는 tcache에 넣음 (락 없음). tcache가 너무 차면 arena로 반환. 일반 할당/해제의 99%가 **락 없이** 처리된다.
> — youngju.dev, jemalloc 深度分析

> tcmalloc은 세 레벨로 구성된다: **Thread cache** → (miss) → **Central Cache** → (miss) → **Page Heap** → (miss) → OS. thread cache hit이 압도적으로 많다. 일반적인 코드에서 **99.9% 이상** 의 할당이 thread cache에서 처리된다.
> — youngju.dev, tcmalloc 深度分析

> `v8malloc` leads the field at 1, 4, and 8 threads — including 296.4 M ops/s at 8 threads, edging tcmalloc's 290.8 M and beating mimalloc's 217.5 M by 36 %. The L2 per-CPU core cache plus the page-owner-CPU L2 routing on cross-thread frees keeps per-thread cost near-flat as the thread count climbs.
> — v8malloc benchmark (MB-02 multi-thread scalability, size = 64 B)

> tcmalloc takes the lead for allocations > 1KB and maintains a steady throughput up to 32KB. jemalloc has the lowest throughput for smaller allocation sizes, but maintains a decent throughput especially with increased parallelism compared to mimalloc and hoard.
> — dev.to libmalloc benchmark

## 代码示例：LD_PRELOAD 替换分配器

```bash
# 1. 安装 jemalloc（以 Ubuntu 为例）
sudo apt-get install libjemalloc-dev

# 2. 使用 LD_PRELOAD 运行你的 RTL 仿真器
LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so ./rtl_simulator -t 8

# 3. 使用 tcmalloc（需安装 gperftools 或 standalone tcmalloc）
LD_PRELOAD=/usr/local/lib/libtcmalloc.so ./rtl_simulator -t 8

# 4. 使用 mimalloc
LD_PRELOAD=/usr/local/lib/libmimalloc.so ./rtl_simulator -t 8
```

```bash
# jemalloc 性能分析模式
MALLOC_CONF="prof:true,prof_prefix:jeprof.out" ./rtl_simulator
jeprof --show_bytes --pdf ./rtl_simulator jeprof.out.*.heap > heap.pdf
```

```bash
# 限制 jemalloc arena 数量（避免 RSS 膨胀）
export MALLOC_ARENA_MAX=4
LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so ./rtl_simulator
```

## 性能对比表（MB-02 多线程扩展性，64B 固定大小）

| threads | glibc   | jemalloc | tcmalloc | mimalloc |
|---------|---------|----------|----------|----------|
| 1       | 44.4 M  | 38.1 M   | 45.3 M   | 31.5 M   |
| 2       | 86.5 M  | 73.2 M   | 86.5 M   | 58.8 M   |
| 4       | 134.9 M | 124.1 M  | 122.6 M  | 102.6 M  |
| 8       | 295.2 M | 271.3 M  | 290.8 M  | 217.5 M  |

> 数据来源：v8malloc 基准测试（MB-02）。jemalloc 在 1 线程下略低，但随着线程数增加保持较好的扩展性；tcmalloc 在高线程下与 glibc 接近；mimalloc 在小对象多线程分配中扩展性相对较弱。

## 相关链接

- [v8malloc 跨分配器基准测试](https://github.com/iqbqioza/v8malloc)
- [jemalloc 官方文档](https://jemalloc.net/jemalloc.3.html)
- [tcmalloc 官方设计文档](https://google.github.io/tcmalloc/design.html)
- [mimalloc 官方仓库](https://github.com/microsoft/mimalloc)
- [Memory Allocators 深度对比 (dev.to)](https://dev.to/frosnerd/libmalloc-jemalloc-tcmalloc-mimalloc-exploring-different-memory-allocators-4lp3)

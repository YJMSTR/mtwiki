---
title: "RCU (Read-Copy-Update) in Userspace — liburcu 与 QEMU 实现"
description: "Userspace RCU 库 liburcu 的五种变体、核心 API、性能特征，以及 QEMU 的 RCU 移植实现。涵盖 RCU 与 rwlock 的性能对比数据。"
source_url: "https://lwn.net/Articles/573424/"
source_type: "doc"
author: "Paul E. McKenney, Mathieu Desnoyers, Lai Jiangshan"
date: "2013-11-13"
tags: ["rcu", "liburcu", "userspace-rcu", "lock-free", "synchronization", "qemu"]
keywords: ["RCU", "read-copy-update", "liburcu", "QSBR", "grace period", "synchronize_rcu", "rcu_read_lock", "userspace"]
capture_date: "2026-07-02"
---

# RCU (Read-Copy-Update) in Userspace — liburcu 与 QEMU 实现

## 来源

- URL: https://lwn.net/Articles/573424/ (User-space RCU, LWN 2013)
- URL: https://terenceli.github.io/技术/2021/03/14/qemu-rcu (QEMU RCU 实现)
- URL: https://kernel-internals.org/locking/rcu/ (RCU Linux Kernel Internals)
- 类型: doc / blog
- 作者: Paul E. McKenney, Mathieu Desnoyers, Terence Li
- 日期: 2013-2021

## 摘要

RCU（Read-Copy-Update）是一种专为读多写少场景设计的同步机制，其核心洞察在于：**读者从不修改数据，因此可以在零同步开销下并发运行**。liburcu 是 Linux 内核 RCU 的用户空间移植，提供五种变体（QSBR、Memory-barrier、Bullet-proof、Signal-based、membarrier），覆盖从极致性能到通用库兼容的不同需求。QEMU 则从 liburcu 移植了 memory-barrier 版本的 RCU，用于保护其内部的并发数据结构。RCU 读操作在 QSBR 模式下几乎为零开销（通常 < 10 ns），相比 pthread rwlock 可实现 10~30 倍的读性能提升。

## 关键要点

- **liburcu 提供五种 RCU 变体**：QSBR（零读开销）、Memory-barrier（通用）、Bullet-proof（自动线程注册）、Signal-based（低开销无显式 QS）、sys_membarrier（内核辅助）。
- **RCU 读操作在 QSBR 模式下接近零开销**：`rcu_read_lock()` / `rcu_read_unlock()` 在非抢占内核中可编译为纯编译器屏障，无原子操作、无缓存行弹跳。
- **RCU 写操作需要等待 grace period**：`synchronize_rcu()` 阻塞直到所有已有读者退出；`call_rcu()` 异步延后释放。
- **QEMU 的 RCU 实现**：移植自 liburcu 的 memory-barrier 版本，使用全局 `rcu_gp_ctr` 和 per-thread `ctr` 追踪 grace period。
- **RCU 与 rwlock 的性能对比**：在千比一的读写下，RCU 可实现 110% 以上的读吞吐量提升；在高并发读场景下，优势可达 10~30 倍。

## 具体实现与代码示例

### liburcu QSBR 基本用法

```c
#include <urcu-qsbr.h>
#include <stdio.h>

struct my_data {
    int a, b, c;
};

static struct my_data __rcu *global_ptr = NULL;

/* 读者：零开销读路径 */
void reader(void)
{
    rcu_read_lock();
    struct my_data *p = rcu_dereference(global_ptr);
    if (p) {
        printf("%d %d %d\n", p->a, p->b, p->c);
    }
    rcu_read_unlock();
}

/* 写者：拷贝-修改-发布-等待 */
void writer(int new_a, int new_b, int new_c)
{
    struct my_data *new_data = malloc(sizeof(*new_data));
    new_data->a = new_a;
    new_data->b = new_b;
    new_data->c = new_c;

    rcu_assign_pointer(global_ptr, new_data);

    synchronize_rcu();  /* 等待 grace period */
    /* 旧数据在此处安全释放 */
}

int main(void)
{
    rcu_register_thread();  /* 每个使用 RCU 的线程必须注册 */

    /* ... 执行读写操作 ... */

    rcu_quiescent_state();  /* QSBR 需要显式声明 quiescent state */
    rcu_unregister_thread();
    return 0;
}
```

### liburcu 五种变体对比

| 变体 | Header | 链接库 | 读端开销 | 显式 QS | 线程注册 | 适用场景 |
|------|--------|--------|----------|---------|----------|----------|
| QSBR | `<urcu-qsbr.h>` | `-lurcu-qsbr` | **Free!** (零指令) | 是 | 是 | 独立应用，极致性能 |
| MEMBARRIER | `<urcu.h>` (RCU_MEMBARRIER) | `-lurcu` | ++ (test) | 否 | 是 | 需要内核 membarrier 补丁 |
| SIGNAL | `<urcu.h>` (RCU_SIGNAL) | `-lurcu-signal` | ++ (test) | 否 | 是 | 可保留 SIGUSR1 的应用 |
| MB | `<urcu.h>` (RCU_MB) | `-lurcu-mb` | ++, `smp_mb()` | 否 | 是 | 通用库，无特殊要求 |
| Bullet-proof | `<urcu-bp.h>` | `-lurcu-bp` | ++, `smp_mb()`, test | 否 | **否** | 无法控制线程生命周期的库 |

> 读端开销说明：`++` 表示本地 inc/dec 对，`test` 表示条件分支，`smp_mb()` 表示内存屏障。

### QEMU RCU 实现（简化版）

QEMU 选择从 liburcu 移植 memory-barrier 版本（`urcu-mb`），核心使用全局计数器 `rcu_gp_ctr` 和 per-thread 计数器：

```c
struct rcu_reader_data {
    /* 读者和 synchronize_rcu() 共用 */
    unsigned long ctr;
    bool waiting;

    /* 仅读者使用 */
    unsigned depth;

    /* 注册表链接，受 rcu_registry_lock 保护 */
    QLIST_ENTRY(rcu_reader_data) node;
};

static struct rcu_reader_data rcu_reader;

void rcu_register_thread(void)
{
    assert(rcu_reader.ctr == 0);
    qemu_mutex_lock(&rcu_registry_lock);
    QLIST_INSERT_HEAD(&registry, &rcu_reader, node);
    qemu_mutex_unlock(&rcu_registry_lock);
}

void rcu_read_lock(void)
{
    rcu_reader.depth++;
    if (rcu_reader.depth == 1) {
        rcu_reader.ctr = atomic_read(&rcu_gp_ctr);
        smp_mb();
    }
}

void rcu_read_unlock(void)
{
    if (rcu_reader.depth == 1) {
        smp_mb();
        rcu_reader.ctr = rcu_reader.ctr | 1;
    }
    rcu_reader.depth--;
}
```

### RCU 链表遍历（内核风格）

```c
#include <urcu/list.h>

struct node {
    int value;
    struct cds_list_head list;
};

static struct cds_list_head head;
static DEFINE_MUTEX(list_lock);

/* 读者：无锁遍历 */
void traverse(void)
{
    struct node *p;
    rcu_read_lock();
    cds_list_for_each_entry_rcu(p, &head, list) {
        /* 使用 p->value */
    }
    rcu_read_unlock();
}

/* 写者：加锁修改，再等待 grace period */
void delete_node(struct node *target)
{
    mutex_lock(&list_lock);
    cds_list_del_rcu(&target->list);
    mutex_unlock(&list_lock);

    synchronize_rcu();  /* 所有旧读者已退出 */
    free(target);
}
```

## 性能数据

- **RCU 读操作（QSBR）**：在 x86_64 非抢占环境下，读端通常 **< 10 ns**，接近裸指针访问速度。
- **RCU vs rwlock（M4 MacBook，千比一读/写）**：
  - pthread rwlock：5 秒内 2340 万次读
  - RCU：5 秒内 4920 万次读（**+110% 提升**）
- **RCU 读端优势来源**：rwlock 的读者需要原子操作增加共享计数器，导致缓存行在核心间来回弹跳；RCU 读者完全不触碰共享缓存行。
- **Mutex 开销对比**：
  - 无锁：~0.6 ns
  - `std::mutex`（无竞争）：~3.4 ns
  - `parking_lot::Mutex`：~3.8 ns
  - `spin::Mutex`：~2.5 ns

> 来源：InfoQ "Read-Copy-Update (RCU): the Secret to Lock-Free Performance" (2026)；Rust 社区 benchmark (2024)。

## 对 RTL 仿真器多线程化的启示

1. **事件调度器状态表**：RTL 仿真器的事件队列/时间轮是读多写少结构（大量线程查询下一个事件时间，少量线程插入/删除事件）。使用 RCU 保护时间轮表头可实现读者无锁并发，避免 rwlock 的读者计数器缓存行竞争。
2. **模块配置热更新**：仿真运行时可能切换波形记录配置、断点表。RCU 允许配置更新时旧读者继续使用旧配置，grace period 后统一释放，避免配置更新时的全局暂停。
3. **QEMU 已验证的路径**：QEMU 作为全系统仿真器，其设备模型、内存区域列表均使用 RCU 保护。RTL 仿真器可采用类似模式保护 module hierarchy 和 signal fanout 表。
4. **与 seqlock 的协同**：RCU 适合指针替换型数据结构；seqlock 适合小体积标量/结构体的频繁读写。RTL 仿真器的全局时间戳（`current_time`）可用 seqlock，而事件队列/模块树用 RCU。

## 原文摘录

> "RCU is most frequently used to provide concurrency control for read-mostly linked data structures, so that read-side overhead is minimal. The word 'minimal' is no euphemism: In some common cases, RCU's read-side overhead both in the kernel and in user space approaches zero."
> — Paul E. McKenney, LWN 2013

> "RCU delivers ten to thirty times the read performance over traditional locks by completely eliminating lock overhead from the read path, enabling linear scalability as core counts increase."
> — InfoQ, 2026

> "QEMU rcu is ported from liburcu. librcu has various version, for least invasive QEMU chose the urcu-mb implementation."
> — Terence Li, QEMU RCU 分析

> "On non-preemptible kernels, rcu_read_lock() is literally a compiler barrier with preemption disabled — no atomic operations, no cache line bouncing."
> — kernel-internals.org

## 相关链接

- [liburcu 官方仓库](https://github.com/urcu/userspace-rcu)
- [LWN: User-space RCU](https://lwn.net/Articles/573424/)
- [LWN: Memory-barrier menagerie](https://lwn.net/Articles/573436/)
- [QEMU RCU 实现分析](https://terenceli.github.io/技术/2021/03/14/qemu-rcu)
- [RCU Linux Kernel Internals](https://kernel-internals.org/locking/rcu/)
- [InfoQ: RCU Lock-Free Performance](https://www.infoq.com/articles/read-copy-update/)
- [What is RCU, Fundamentally? (LWN 2007)](https://lwn.net/Articles/262464/)

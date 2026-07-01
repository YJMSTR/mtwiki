---
title: "Linux Kernel Synchronization Primitives — Futex、Per-CPU 变量与内核级技术在用户空间仿真器中的应用"
description: "Linux 内核同步机制（futex、per-CPU 变量、seqlock、RCU）的设计原理、实现细节，以及如何在用户空间 RTL 仿真器中仿真或借用这些技术。"
source_url: "https://kernel-internals.org/locking/futex/"
source_type: "doc"
author: "Linux Kernel Community, Hubertus Franke, Rusty Russell, Ingo Molnár"
date: "2002-2025"
tags: ["futex", "percpu", "kernel-sync", "userspace-emulator", "rtl-simulation", "barrier", "seqlock", "rcu"]
keywords: ["futex", "fast userspace mutex", "per-CPU variable", "kernel synchronization", "FUTEX_WAIT", "FUTEX_WAKE", "FUTEX_REQUEUE", "PI futex", "emulator"]
capture_date: "2026-07-02"
---

# Linux Kernel Synchronization Primitives — Futex、Per-CPU 变量与内核级技术在用户空间仿真器中的应用

## 来源

- URL: https://kernel-internals.org/locking/futex/ (Futex Internals)
- URL: https://man7.org/linux/man-pages/man2/futex.2.html (futex(2) man page)
- URL: https://www.minzkn.com/linuxkernel/pages/futex.html (Futex 韩文详解)
- URL: https://stackoverflow.com/questions/26761905/seq-locks-vs-rcu-vs-per-cpu-use-cases (内核同步机制对比)
- URL: https://docs.kernel.org/RCU/Design/Requirements/Requirements.html (RCU Requirements)
- 类型: doc / man page / stackoverflow
- 作者: Linux Kernel Community, Ulrich Drepper, Ingo Molnár
- 日期: 2002-2025

## 摘要

Linux 内核提供了一套分层同步原语体系：futex 作为用户空间锁的基础（无竞争时纯用户空间原子操作，有竞争时陷入内核等待/唤醒），per-CPU 变量消除跨核缓存竞争，seqlock 和 RCU 分别应对高频读的低延迟和零开销需求。这些原语的组合构成了内核高性能并发的基础。对于用户空间 RTL 仿真器，**futex 可直接使用**（glibc 的 pthread 锁底层就是 futex），**per-CPU 变量可以模拟**（通过线程 ID 哈希到伪 CPU 槽），**seqlock 和 RCU 可以移植或借用已有库**（如 rigtorp/Seqlock、liburcu）。理解这些原语的设计约束，有助于在仿真器设计中做出正确的同步策略选择。

## 关键要点

- **Futex 的两层架构**：无竞争时完全在用户空间（~10-20 周期，原子 CAS）；有竞争时陷入内核（`FUTEX_WAIT`/`FUTEX_WAKE`），避免忙等浪费 CPU。
- **Per-CPU 变量**：每个 CPU 拥有独立副本，避免缓存行竞争。内核通过 `DEFINE_PER_CPU()` / `per_cpu()` 宏管理；用户空间可通过线程 ID 取模或 `thread_local` 模拟。
- **Seqlock vs RCU vs Per-CPU 的适用场景**：
  - Seqlock：数据小、可拷贝、读者需要一致性快照、写者极少。
  - RCU：数据通过指针访问、读者极多、允许短暂看到旧数据、需要 grace period 回收。
  - Per-CPU：数据天然按 CPU 分区、不需要跨 CPU 共享（如统计计数器、每核事件队列）。
- **FUTEX_REQUEUE 解决惊群**：`pthread_cond_broadcast` 使用 `FUTEX_CMP_REQUEUE` 将等待者从条件变量队列移动到互斥锁队列，避免所有等待者同时醒来竞争锁。
- **PI Futex 解决优先级反转**：当高优先级任务被低优先级任务持有的锁阻塞时，临时提升低优先级任务的优先级。

## 具体实现与代码示例

### Futex 基本实现（用户空间裸 futex）

```c
#include <linux/futex.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <atomic>

/* futex 封装 */
static int futex(int *uaddr, int futex_op, int val,
                 const struct timespec *timeout, int *uaddr2, int val3)
{
    return syscall(SYS_futex, uaddr, futex_op, val, timeout, uaddr2, val3);
}

/* 简单互斥锁：0 = 未锁定, 1 = 锁定, 2 = 有等待者 */
class FutexMutex {
    std::atomic<int> val_{0};

public:
    void lock() {
        int c = 0;
        /* 快速路径：无竞争时直接 CAS */
        if (!val_.compare_exchange_strong(c, 1, std::memory_order_acquire)) {
            /* 慢速路径：已有竞争 */
            if (c != 2) {
                c = val_.exchange(2, std::memory_order_acquire);
            }
            while (c != 0) {
                futex(&val_.load(), FUTEX_WAIT, 2, NULL, NULL, 0);
                c = val_.exchange(2, std::memory_order_acquire);
            }
        }
    }

    void unlock() {
        if (val_.fetch_sub(1, std::memory_order_release) != 1) {
            /* 有等待者，需要唤醒 */
            val_.store(0, std::memory_order_release);
            futex(&val_.load(), FUTEX_WAKE, 1, NULL, NULL, 0);
        }
    }
};
```

### Futex 状态转换

| 场景 | 初始值 | 动作 | 最终值 | 内核参与？ |
|------|--------|------|--------|------------|
| 无竞争获取 | 0 (UNLOCKED) | CAS 0→1 | 1 (LOCKED) | ❌ 否 |
| 竞争获取 | 1 (LOCKED) | Xchg→2, FUTEX_WAIT | 2 (CONTENDED) | ✅ 是 (wait) |
| 释放，无等待者 | 1 (LOCKED) | Xchg→0 | 0 (UNLOCKED) | ❌ 否 |
| 释放，有等待者 | 2 (CONTENDED) | Xchg→0, FUTEX_WAKE | 0 (UNLOCKED) | ✅ 是 (wake) |

> 无竞争路径仅需一次原子 CAS（~10-20 周期），比传统内核互斥锁（~100-300 ns 系统调用）快 10~50 倍。

### Per-CPU 变量（内核实现与用户空间模拟）

内核实现：

```c
#include <linux/percpu.h>

DEFINE_PER_CPU(unsigned long, cpu_stat);  /* 每 CPU 独立变量 */

void update_stat(unsigned long delta)
{
    /* 获取当前 CPU 的本地变量，禁止抢占 */
    unsigned long *stat = get_cpu_var(cpu_stat);
    *stat += delta;
    put_cpu_var(cpu_stat);  /* 恢复抢占 */
}

unsigned long read_total(void)
{
    unsigned long total = 0;
    for_each_online_cpu(cpu) {
        total += per_cpu(cpu_stat, cpu);
    }
    return total;
}
```

用户空间模拟（RTL 仿真器场景）：

```cpp
#include <thread>
#include <vector>
#include <atomic>

/* 模拟 per-CPU 统计：按线程 ID 哈希到伪 CPU 槽 */
class PerCpuCounter {
    static constexpr size_t NUM_SLOTS = 64;  /* 2 的幂，便于位运算 */
    alignas(64) std::atomic<uint64_t> slots_[NUM_SLOTS];

public:
    void add(uint64_t delta) {
        size_t slot = std::hash<std::thread::id>{}(std::this_thread::get_id()) & (NUM_SLOTS - 1);
        slots_[slot].fetch_add(delta, std::memory_order_relaxed);
    }

    uint64_t sum() const {
        uint64_t total = 0;
        for (size_t i = 0; i < NUM_SLOTS; ++i) {
            total += slots_[i].load(std::memory_order_relaxed);
        }
        return total;
    }
};

/* 更简单的 thread_local 模拟（仅统计本线程） */
thread_local uint64_t tl_event_count = 0;

void process_event() {
    tl_event_count++;  /* 零竞争，无需原子操作 */
}
```

### FUTEX_REQUEUE 与条件变量实现

```c
/* pthread_cond_broadcast 使用 FUTEX_CMP_REQUEUE 避免惊群 */

void cond_broadcast(pthread_cond_t *cond, pthread_mutex_t *mutex)
{
    /* 1. 原子增加 cond->seq（表示新广播事件） */
    int seq = atomic_fetch_add(&cond->seq, 1);

    /* 2. 唤醒 1 个等待者，其余 requeue 到 mutex */
    futex(&cond->seq,
          FUTEX_CMP_REQUEUE,
          1,              /* 唤醒 1 个 */
          INT_MAX,        /* 其余全部 requeue */
          &mutex->val,    /* 目标：mutex 的 futex word */
          seq);           /* 仅当 cond->seq 仍等于 seq 时执行 */
}
```

> 关键洞察：`FUTEX_CMP_REQUEUE` 将 N 个等待者从 condvar 队列移动到 mutex 队列，只唤醒 1 个。该 waiter 获取 mutex 后，释放时自然唤醒下一个 requeue 的 waiter。N 个等待者被顺序处理，而非同时竞争。

### PI Futex（优先级继承）

```c
/* 用户空间 PI 互斥锁（简化） */
void pi_mutex_lock(int *uaddr)
{
    /* 快速路径 */
    if (cmpxchg(uaddr, 0, gettid()) == 0)
        return;

    /* 慢速路径：内核处理优先级继承 */
    futex(uaddr, FUTEX_LOCK_PI, 0, NULL, NULL, 0);
}

void pi_mutex_unlock(int *uaddr)
{
    futex(uaddr, FUTEX_UNLOCK_PI, 0, NULL, NULL, 0);
}
```

> PI futex 在实时系统中至关重要：RTL 仿真器若使用实时调度（如与硬件仿真器协同），必须避免优先级反转导致的确定性丧失。

## 性能数据

- **Futex 无竞争路径**：~10-20 个 CPU 周期（~3-5 ns），仅一次原子 CAS。
- **传统内核互斥锁（pre-futex）**：每次操作 ~100-300 ns（系统调用开销）。
- **Mutex 竞争场景**：
  - `std::mutex` 平均：62 ms（16 线程，16384 次循环）
  - 最慢等待时间：2.9 ms（受调度器时间片影响）
- **Per-CPU 变量**：读/写无竞争，纯本地缓存访问，约 1-2 ns。
- **Futex 与 pthread 关系**：glibc 的 `pthread_mutex_t`、`pthread_cond_t`、`pthread_rwlock_t`、`sem_t` 和 C++ `std::mutex` 全部基于 futex 实现。

> 来源：probablydance.com 2020 年 benchmark；kernel-internals.org。

## 内核同步原语选择决策树

```
数据访问模式
├── 读多写少，数据小且可拷贝
│   └── seqlock（读者重试，写者不阻塞）
├── 读多写少，数据通过指针访问
│   └── RCU（读者零开销，写者延迟释放）
├── 数据天然按 CPU/线程分区
│   └── per-CPU 变量（零跨核竞争）
├── 读写均衡，需要严格互斥
│   └── futex-based mutex（pthread_mutex）
├── 需要阻塞等待条件
│   └── futex-based condvar（pthread_cond）
├── 实时调度，避免优先级反转
│   └── PI futex（FUTEX_LOCK_PI）
└── 广播通知，避免惊群
    └── FUTEX_CMP_REQUEUE
```

## 对 RTL 仿真器多线程化的启示

1. **直接使用 futex 基础设施**：不要自行实现裸自旋锁作为仿真器的主要同步机制。glibc 的 `pthread_mutex_t` 在无竞争时就是 futex 快速路径（~3-5 ns），有竞争时自动退化为内核等待。裸自旋锁在竞争超过 3-5 µs 时比 mutex 更浪费 CPU（probablydance.com 实测）。
2. **每线程/每核事件队列**：RTL 仿真器的事件调度是核心瓶颈。使用 per-CPU（或 per-thread）事件队列，每个线程将事件推入自己的队列，调度阶段仅合并各队列的队首事件。这消除了事件插入时的锁竞争，是 PDES（Parallel Discrete Event Simulation）的核心优化。
3. **全局时间戳用 seqlock**：`current_time` 的更新频率远低于读取频率。seqlock 保护允许读者在纳秒内获取一致的时间戳快照，写者（时间推进时）仅短暂加锁。
4. **模块层次结构用 RCU**：Verilator 等仿真器的 module hierarchy 在编译后几乎不变，但运行时需要遍历。使用 RCU 保护模块树，读者（事件传播路径）无锁遍历，写者（动态重配置、DPI 插入）拷贝-修改-替换。
5. **条件变量与屏障**：多线程仿真器的同步点（如"所有线程完成当前时间步"）使用 `pthread_barrier`（底层基于 futex）比自旋等待更节能，特别是在线程数超过物理核心数时。
6. **实时协同仿真**：若 RTL 仿真器需要与物理硬件或实时模型协同，考虑使用 PI futex 或 `SCHED_FIFO` + 优先级继承，防止高优先级实时线程被低优先级仿真线程阻塞。

## 原文摘录

> "A futex (fast userspace mutex) is the kernel mechanism that allows userspace locking primitives to be efficient. The key insight: in the common uncontended case, locking and unlocking should happen entirely in userspace with no kernel involvement. The kernel is only called when there's actual contention."
> — kernel-internals.org

> "Before futexes, every POSIX mutex operation went through the kernel. A syscall costs ~100–300 ns on modern hardware. A program that holds fine-grained mutexes for short durations could spend more time in the kernel than doing actual work."
> — kernel-internals.org

> "Futex solves the syscall tax problem: Traditional mutexes required kernel calls for every operation. Futex eliminates this for uncontended locks—the common case. Two-tier architecture: Lock state lives in userspace (fast), wait queues live in kernel (correct)."
> — onenoughtone.com

> "Per-CPU Variables these are mostly used with CPU specific structures can avoid global locks. Note these must still synchronize with ISR's."
> — StackOverflow 26761905

> "The fast path is atomic-only: Uncontended lock acquisition is a single atomic compare-and-swap instruction. ~10-20 cycles, no syscalls."
> — onenoughtone.com

## 相关链接

- [Futex Internals (kernel-internals.org)](https://kernel-internals.org/locking/futex/)
- [futex(2) man page](https://man7.org/linux/man-pages/man2/futex.2.html)
- [futex(4) man page](https://linux.die.net/man/4/futex)
- [Futex: Fast Userspace Mutex (onenoughtone.com)](https://www.onenoughtone.com/learn/futex/1)
- [Measuring Mutexes, Spinlocks and Linux Scheduler](https://probablydance.com/2019/12/30/measuring-mutexes-spinlocks-and-how-bad-the-linux-scheduler-really-is/)
- [Seq-locks vs RCU vs Per-CPU use cases](https://stackoverflow.com/questions/26761905/seq-locks-vs-rcu-vs-per-cpu-use-cases)
- [RCU Requirements (kernel docs)](https://docs.kernel.org/RCU/Design/Requirements/Requirements.html)
- [A Tour Through RCU's Requirements](https://www.infradead.org/~mchehab/kernel_docs/RCU/Design/Requirements/Requirements.html)

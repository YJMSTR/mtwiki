---
title: "高级同步原语与内核技术"
description: "RCU、Seqlock、Futex、Per-CPU 变量的内核原理与用户空间实现，以及它们在 RTL 多线程仿真器中的具体应用策略。"
sources:
  - source-rcu-userspace
  - source-seqlock
  - source-linux-kernel-sync
tags: ["rcu", "seqlock", "futex", "per-cpu", "kernel-sync", "rtl-simulation", "lock-free"]
keywords: ["RCU", "seqlock", "futex", "per-CPU", "grace period", "QSBR", "双重缓冲", "内核同步"]
author: "Wiki 合成"
date: "2026-07-02"
---

# 高级同步原语与内核技术

> 本文将 Linux 内核的四类核心同步机制——RCU、Seqlock、Futex、Per-CPU 变量——从内核原理翻译到用户空间实践，并直接映射到 RTL 仿真器的多线程设计决策中。每个原语都配有完整可编译代码、性能基准和「什么时候用、什么时候不用」的决策树。

---

## 1. RCU：读多写少的终极答案

### 1.1 核心洞察

RCU（Read-Copy-Update）的底层洞察极其朴素：**读者从不修改数据，因此可以零同步开销地并发运行**。写者采用「拷贝→修改→发布→等待 grace period→释放旧数据」的四步走策略，所有读者要么看到旧数据，要么看到新数据，绝不会看到中间态。

| 指标 | 值 | 说明 |
|------|-----|------|
| 读端（QSBR） | **< 10 ns** | 非抢占环境下纯编译器屏障，无原子操作 |
| 读端（MEMBARRIER） | ~15 ns | 一次 `smp_mb()` |
| 写端 | 数十 ~ 数百 µs | 取决于 grace period 长度和读者数量 |
| 读者并发 | 线性可扩展 | 读者不触碰共享缓存行 |

### 1.2 liburcu 五种变体对比

liburcu 提供五种 RCU 变体，覆盖从「极致性能」到「通用库兼容」的全谱系：

| 变体 | Header | 链接库 | 读端开销 | 显式 QS | 线程注册 | 适用场景 |
|------|--------|--------|----------|---------|----------|----------|
| **QSBR** | `<urcu-qsbr.h>` | `-lurcu-qsbr` | **Free!**（零指令） | 是 | 是 | 独立应用，极致性能 |
| **MEMBARRIER** | `<urcu.h>` (RCU_MEMBARRIER) | `-lurcu` | `++`（test） | 否 | 是 | 需要内核 membarrier 补丁 |
| **SIGNAL** | `<urcu.h>` (RCU_SIGNAL) | `-lurcu-signal` | `++`（test） | 否 | 是 | 可保留 SIGUSR1 的应用 |
| **MB** | `<urcu.h>` (RCU_MB) | `-lurcu-mb` | `++`, `smp_mb()` | 否 | 是 | 通用库，无特殊要求 |
| **Bullet-proof** | `<urcu-bp.h>` | `-lurcu-bp` | `++`, `smp_mb()`, test | 否 | **否** | 无法控制线程生命周期的库 |

> **读端开销说明**：`++` 表示本地 inc/dec 对；`test` 表示条件分支；`smp_mb()` 表示全内存屏障。QSBR 模式下 `rcu_read_lock()` 在 x86_64 上可编译为**零条指令**（纯编译器屏障）。

### 1.3 完整可编译代码：RCU 链表（liburcu QSBR）

```c
/* rcu_list_demo.c
 * 编译: gcc -O2 -o rcu_list_demo rcu_list_demo.c -lurcu-qsbr -lpthread
 */
#include <urcu-qsbr.h>
#include <urcu/list.h>
#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>
#include <unistd.h>

#define NUM_READERS 8
#define NUM_WRITES  100000

struct node {
    int value;
    struct cds_list_head list;
};

static struct cds_list_head head = CDS_LIST_HEAD_INIT(head);
static pthread_mutex_t write_lock = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int write_done = 0;

/* === 读者：零开销遍历 === */
void *reader_thread(void *arg)
{
    rcu_register_thread();
    long tid = (long)arg;
    long reads = 0;

    while (!write_done) {
        rcu_read_lock();
        struct node *p;
        int sum = 0;
        cds_list_for_each_entry_rcu(p, &head, list) {
            sum += p->value;  /* 读者无锁访问 */
        }
        rcu_read_unlock();
        reads++;

        /* QSBR 必须显式声明 quiescent state */
        rcu_quiescent_state();
    }

    rcu_unregister_thread();
    printf("Reader %ld: %ld reads, final sum=%d\n", tid, reads, sum);
    return (void *)reads;
}

/* === 写者：拷贝-修改-发布-等待 === */
void *writer_thread(void *arg)
{
    (void)arg;
    for (int i = 0; i < NUM_WRITES; i++) {
        struct node *new_node = malloc(sizeof(*new_node));
        new_node->value = i;

        pthread_mutex_lock(&write_lock);
        cds_list_add_tail_rcu(&new_node->list, &head);
        pthread_mutex_unlock(&write_lock);

        /* 可选：每 1000 次批量回收，或单独 synchronize_rcu() */
        if (i % 1000 == 0) {
            synchronize_rcu();  /* 等待所有旧读者退出 */
            /* 此处可安全释放被删除的节点 */
        }
    }
    write_done = 1;
    return NULL;
}

int main(void)
{
    pthread_t readers[NUM_READERS];
    pthread_t writer;

    /* 初始化链表，预先放入一个节点 */
    struct node *init = malloc(sizeof(*init));
    init->value = -1;
    cds_list_add_tail_rcu(&init->list, &head);

    for (long i = 0; i < NUM_READERS; i++) {
        pthread_create(&readers[i], NULL, reader_thread, (void *)i);
    }
    pthread_create(&writer, NULL, writer_thread, NULL);

    pthread_join(writer, NULL);
    for (int i = 0; i < NUM_READERS; i++) {
        pthread_join(readers[i], NULL);
    }

    return 0;
}
```

### 1.4 写者的两种回收策略

| 策略 | API | 延迟 | 适用场景 |
|------|-----|------|----------|
| **同步回收** | `synchronize_rcu()` | 阻塞，等待 grace period | 写频率低，可容忍短暂阻塞 |
| **异步回收** | `call_rcu(ptr, free_fn)` | 立即返回，延后到 GP 结束 | 写频率高，不能阻塞写路径 |

```c
/* 异步回收示例 */
static void free_node_rcu(struct rcu_head *rcu)
{
    struct node *p = container_of(rcu, struct node, rcu);
    free(p);
}

void delete_node_async(struct node *target)
{
    pthread_mutex_lock(&write_lock);
    cds_list_del_rcu(&target->list);
    pthread_mutex_unlock(&write_lock);

    call_rcu(&target->rcu, free_node_rcu);  /* 非阻塞！ */
}
```

---

## 2. Seqlock：写者优先的轻量快照

### 2.1 核心洞察

Seqlock 用**序列号**替代锁来保护读者：写者持锁修改数据，修改前后各翻转一次序列号；读者无锁读取，先读序列号，再拷贝数据，最后再读序列号——若序列号变化或为奇数，则重试。

| 指标 | 值 | 说明 |
|------|-----|------|
| 读端（无竞争） | **10~15 ns** | 两次 `memory_order_acquire` load + 拷贝 + 比较 |
| 读端（写者并发） | 1~2 次重试 | 写窗口极短（纳秒级），重试率极低 |
| 写端 | 自旋锁 + 两次序列号写 | 与自旋锁本身相当 |
| 保护数据量 | 任意 `TrivialType` | 不限于单个机器字 |

### 2.2 编译器重排陷阱（GCC -O3）

以下**裸实现**在 GCC `-O3` 下会被重排，导致 `copy = value_` 被移到 `seq0` 加载之前：

```cpp
/* ❌ 错误：编译器重排后可能读到撕裂数据 */
T load_buggy() const {
    T copy;
    size_t seq0, seq1;
    do {
        seq0 = seq_.load(std::memory_order_acquire);
        copy = value_;     /* 编译器可能重排到 seq0 之前！ */
        seq1 = seq_.load(std::memory_order_acquire);
    } while (seq0 != seq1 || seq0 & 1);
    return copy;
}
```

**GCC 5.2 -O3 生成的错误汇编**：

```asm
401ad0:  8b 47 08              mov  0x8(%rdi),%eax   ; copy = value_ （先读数据！）
401ad8:  48 8b 0f              mov  (%rdi),%rcx      ; seq0 = seq_
401adb:  48 8b 17              mov  (%rdi),%rdx      ; seq1 = seq_
```

**修复：插入 `std::atomic_signal_fence`**（x86 适用，零运行时开销）：

```asm
4014e8:  48 8b 31              mov  (%rcx),%rsi      ; seq0 = seq_ （正确顺序）
4014eb:  8b 07                 mov  (%rdi),%eax      ; copy = value_
4014ed:  48 8b 11              mov  (%rcx),%rdx      ; seq1 = seq_
```

### 2.3 完整可编译代码：Seqlock 时间戳（C++17）

```cpp
/* seqlock_timestamp.hpp
 * 编译: g++ -O3 -std=c++17 -o seqlock_demo seqlock_demo.cpp -lpthread
 */
#pragma once
#include <atomic>
#include <cstddef>
#include <thread>
#include <chrono>
#include <cstdio>

template <typename T, size_t N = 64>
class Seqlock {
    alignas(N) std::atomic<std::size_t> seq_{0};
    alignas(N) T value_{};

public:
    explicit Seqlock(T value = T{}) : value_(value) {}

    /* 写者：单线程独占（或通过外部锁支持多写者） */
    void store(const T& value) noexcept {
        std::size_t seq = seq_.load(std::memory_order_relaxed);
        seq_.store(seq + 1, std::memory_order_release);  /* 奇数 = 正在写 */

        /* 关键：编译器屏障，阻止 value_ 的读写被重排到 seq 操作之外 */
        std::atomic_signal_fence(std::memory_order_acq_rel);
        value_ = value;
        std::atomic_signal_fence(std::memory_order_acq_rel);

        seq_.store(seq + 2, std::memory_order_release);  /* 偶数 = 写完成 */
    }

    /* 读者：多线程并发，无锁 */
    T load() const noexcept {
        T copy;
        std::size_t seq0, seq1;
        do {
            seq0 = seq_.load(std::memory_order_acquire);
            if (seq0 & 1) {
                /* 正在写，忙等 */
                continue;
            }
            std::atomic_signal_fence(std::memory_order_acq_rel);
            copy = value_;
            std::atomic_signal_fence(std::memory_order_acq_rel);
            seq1 = seq_.load(std::memory_order_acquire);
        } while (seq0 != seq1 || seq0 & 1);
        return copy;
    }
};

/* ===== 使用示例：全局仿真时间戳 ===== */
struct SimTime {
    uint64_t time;       /* 当前仿真时间 */
    uint64_t cycle;      /* 当前周期数 */
    uint32_t phase;      /* 相位（0/1/2 for posedge/negedge/中间） */
};

static Seqlock<SimTime> g_sim_time(SimTime{0, 0, 0});

/* 时间推进（写者，单线程或外部锁保护） */
void advance_time(uint64_t new_time, uint64_t new_cycle, uint32_t phase)
{
    g_sim_time.store(SimTime{new_time, new_cycle, phase});
}

/* 任意线程读取当前时间（读者，无锁） */
SimTime get_current_time()
{
    return g_sim_time.load();  /* ~10-15 ns，极大概率一次成功 */
}

/* ===== 双重缓冲方案（全平台可移植，无需编译器屏障） ===== */
template <typename T>
class SeqlockDoubleBuffer {
    std::atomic<size_t> seq_{0};
    T values_[2];  /* 两份数据，按 seq 奇偶选择 */

public:
    void store(const T& value) {
        size_t seq = seq_.load(std::memory_order_relaxed);
        size_t idx = (seq + 1) & 1;  /* 下一版本写入另一个槽 */
        values_[idx] = value;
        seq_.store(seq + 1, std::memory_order_release);
    }

    T load() const {
        T copy;
        size_t seq0, seq1;
        do {
            seq0 = seq_.load(std::memory_order_acquire);
            copy = values_[seq0 & 1];  /* 读取当前版本 */
            seq1 = seq_.load(std::memory_order_acquire);
        } while (seq0 != seq1 || seq0 & 1);
        return copy;
    }
};

/* ===== 性能测试 ===== */
static constexpr int NUM_READERS = 16;
static constexpr int ITERATIONS  = 10'000'000;
static Seqlock<uint64_t> g_counter(0);
static _Atomic int g_done = 0;

void *reader_bench(void *arg)
{
    (void)arg;
    long long total = 0;
    for (int i = 0; i < ITERATIONS; i++) {
        total += g_counter.load();
    }
    g_done++;
    return (void *)total;
}

int main()
{
    pthread_t readers[NUM_READERS];
    auto t0 = std::chrono::steady_clock::now();

    for (int i = 0; i < NUM_READERS; i++) {
        pthread_create(&readers[i], nullptr,
                       [](void*) -> void* { return reader_bench(nullptr); },
                       nullptr);
    }

    for (int i = 0; i < NUM_READERS; i++) {
        pthread_join(readers[i], nullptr);
    }

    auto t1 = std::chrono::steady_clock::now();
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
    printf("%d readers x %d loads = %d total loads in %ld ms\n",
           NUM_READERS, ITERATIONS, NUM_READERS * ITERATIONS, ms);
    printf("Average load latency: %.2f ns\n",
           (ms * 1e6) / (NUM_READERS * ITERATIONS));
    return 0;
}
```

### 2.4 单写者 vs 多写者

| 模式 | 写者同步 | 实现复杂度 | 适用场景 |
|------|----------|------------|----------|
| 单写者 | 外部锁或天然单线程 | 低 | 时间推进、主调度器 |
| 多写者（CAS） | `compare_exchange_weak` 自旋 | 中 | 多个事件产生线程同时更新 |

多写者 CAS 实现的核心逻辑：

```cpp
do {
    seq = seq_.load(std::memory_order_relaxed);
} while (seq & 1 || !seq_.compare_exchange_weak(
    seq, seq + 1,
    std::memory_order_acquire,
    std::memory_order_relaxed));

value_ = value;  /* 安全写入 */
seq_.store(seq + 2, std::memory_order_release);
```

---

## 3. Futex：两层锁的工业标准

### 3.1 核心洞察

Futex（Fast Userspace muTEX）的设计哲学是**双层架构**：无竞争时完全在用户空间（一次原子 CAS），有竞争时陷入内核（`FUTEX_WAIT`/`FUTEX_WAKE`）。glibc 的 `pthread_mutex_t`、`pthread_cond_t`、`std::mutex` 全部基于此实现。

| 场景 | 延迟 | 说明 |
|------|------|------|
| 无竞争获取 | **3~5 ns** | 一次原子 `lock cmpxchg` |
| 有竞争（首次） | ~100 ns | 内核 syscall 进入 wait |
| 有竞争（唤醒） | ~100 ns | 内核 syscall + 上下文切换 |
| 自旋锁对比（竞争>5µs） | 更差 | 自旋锁浪费 CPU，futex 让出 CPU |

### 3.2 完整状态转换表

| 场景 | 初始值 | 动作 | 最终值 | 内核参与？ | 代码路径 |
|------|--------|------|--------|------------|----------|
| **无竞争获取** | 0 (UNLOCKED) | CAS 0→1 | 1 (LOCKED) | ❌ 否 | `lock()` 快速路径 |
| **竞争获取** | 1 (LOCKED) | Xchg→2, `FUTEX_WAIT` | 2 (CONTENDED) | ✅ 是 (wait) | `lock()` 慢速路径 |
| **释放，无等待者** | 1 (LOCKED) | `fetch_sub` 返回 1 | 0 (UNLOCKED) | ❌ 否 | `unlock()` 快速路径 |
| **释放，有等待者** | 2 (CONTENDED) | Store→0, `FUTEX_WAKE` | 0 (UNLOCKED) | ✅ 是 (wake) | `unlock()` 慢速路径 |

### 3.3 完整可编译代码：裸 Futex 互斥锁

```cpp
/* futex_mutex.cpp
 * 编译: g++ -O2 -std=c++17 -o futex_mutex futex_mutex.cpp -lpthread
 */
#include <atomic>
#include <linux/futex.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <cerrno>
#include <cstdio>
#include <thread>
#include <vector>

class FutexMutex {
    std::atomic<int> val_{0};
    /* 状态: 0 = 未锁定, 1 = 锁定(无等待), 2 = 锁定(有等待) */

    static int futex_wait(int *uaddr, int val) {
        return syscall(SYS_futex, uaddr, FUTEX_WAIT, val, nullptr, nullptr, 0);
    }
    static int futex_wake(int *uaddr, int nr) {
        return syscall(SYS_futex, uaddr, FUTEX_WAKE, nr, nullptr, nullptr, 0);
    }

public:
    void lock() {
        int c = 0;
        /* === 快速路径：无竞争 === */
        if (val_.compare_exchange_strong(c, 1, std::memory_order_acquire)) {
            return;  /* 3~5 ns，无 syscall */
        }

        /* === 慢速路径：已有竞争 === */
        if (c != 2) {
            c = val_.exchange(2, std::memory_order_acquire);
        }
        while (c != 0) {
            /* 陷入内核等待，线程被挂起 */
            futex_wait(reinterpret_cast<int *>(&val_.load()), 2);
            c = val_.exchange(2, std::memory_order_acquire);
        }
    }

    void unlock() {
        /* fetch_sub 返回旧值：1 表示无等待者，2 表示有等待者 */
        if (val_.fetch_sub(1, std::memory_order_release) != 1) {
            /* 有等待者，需要唤醒一个 */
            val_.store(0, std::memory_order_release);
            futex_wake(reinterpret_cast<int *>(&val_.load()), 1);
        }
    }
};

/* ===== 使用示例 ===== */
static FutexMutex g_mutex;
static uint64_t g_counter = 0;
static constexpr int NUM_THREADS = 8;
static constexpr int ITERATIONS  = 1'000'000;

void worker(int tid)
{
    (void)tid;
    for (int i = 0; i < ITERATIONS; i++) {
        g_mutex.lock();
        g_counter++;
        g_mutex.unlock();
    }
}

int main()
{
    std::vector<std::thread> threads;
    auto t0 = std::chrono::steady_clock::now();

    for (int i = 0; i < NUM_THREADS; i++) {
        threads.emplace_back(worker, i);
    }
    for (auto &t : threads) t.join();

    auto t1 = std::chrono::steady_clock::now();
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();

    printf("Final counter: %lu (expected: %lu)\n", g_counter,
           (uint64_t)NUM_THREADS * ITERATIONS);
    printf("Time: %ld ms, ops/ms: %.0f\n", ms,
           (double)NUM_THREADS * ITERATIONS / ms);
    return 0;
}
```

### 3.4 FUTEX_CMP_REQUEUE：条件变量广播的惊群免疫

`pthread_cond_broadcast` 的经典问题是「惊群」——所有等待者同时被唤醒，竞争同一把锁。`FUTEX_CMP_REQUEUE` 的解决方式优雅：只唤醒 1 个，其余全部「搬运」到 mutex 的等待队列。

```c
void cond_broadcast(struct condvar *cond, struct mutex *mutex)
{
    int seq = atomic_fetch_add(&cond->seq, 1);

    /* 唤醒 1 个，其余 requeue 到 mutex 队列 */
    syscall(SYS_futex, &cond->seq, FUTEX_CMP_REQUEUE,
            1,          /* 唤醒 1 个 */
            INT_MAX,    /* 其余全部 requeue */
            &mutex->val, /* 目标：mutex 的 futex word */
            seq);        /* 仅当 cond->seq == seq 时执行 */
}
```

> 关键洞察：被 requeue 的等待者不再竞争条件变量，而是按顺序获取 mutex。mutex 持有者释放时，自然唤醒下一个 requeue 的等待者。N 个等待者被**串行化**处理，而非同时竞争。

---

## 4. Per-CPU 变量：消除缓存行竞争的终极手段

### 4.1 核心洞察

当多个核心同时写同一个变量时，缓存行在核心间来回「弹跳」（cache line bouncing），速度暴跌。Per-CPU 变量的方案是**每个线程/核心拥有独立副本**，聚合时再做求和。

| 指标 | 值 | 说明 |
|------|-----|------|
| 本地写 | **~1 ns** | 纯线程本地写，无原子操作 |
| 本地读 | **~1 ns** | 同线程读取，缓存命中 |
| 聚合求和 | O(N_slots) | 仅需读取 N 个槽位，每个一次 `relaxed` load |
| 跨核竞争 | **零** | 每个线程写不同缓存行 |

### 4.2 完整可编译代码：Per-CPU 事件计数器（C++17）

```cpp
/* percpu_counter.hpp
 * 编译: g++ -O3 -std=c++17 -o percpu_demo percpu_demo.cpp -lpthread
 */
#pragma once
#include <atomic>
#include <thread>
#include <vector>
#include <cstdint>
#include <cstdio>
#include <chrono>

/* 方案 A：thread_local（最简，仅统计本线程） */
thread_local uint64_t tl_event_count = 0;

inline void count_event_tl() {
    tl_event_count++;  /* 零竞争，零原子操作，~1 ns */
}

uint64_t sum_events_tl(const std::vector<uint64_t*> &tls)
{
    uint64_t total = 0;
    for (auto *p : tls) total += *p;
    return total;
}

/* 方案 B：伪 Per-CPU（线程 ID 哈希到槽，支持任意线程聚合） */
class PerCpuCounter {
    static constexpr size_t NUM_SLOTS = 64;  /* 2 的幂，位运算取模 */
    /* 每个槽位对齐到缓存行（64B），避免 false sharing */
    struct alignas(64) Slot {
        std::atomic<uint64_t> value{0};
    };
    Slot slots_[NUM_SLOTS];

public:
    void add(uint64_t delta) {
        size_t slot = std::hash<std::thread::id>{}(
            std::this_thread::get_id()) & (NUM_SLOTS - 1);
        slots_[slot].value.fetch_add(delta, std::memory_order_relaxed);
        /* 同一线程总是落到同一槽位，实际无竞争 */
    }

    uint64_t sum() const {
        uint64_t total = 0;
        for (size_t i = 0; i < NUM_SLOTS; ++i) {
            total += slots_[i].value.load(std::memory_order_relaxed);
        }
        return total;
    }

    /* 重置 */
    void reset() {
        for (auto &s : slots_) s.value.store(0, std::memory_order_relaxed);
    }
};

/* ===== RTL 仿真器场景：每线程事件队列 + 全局计数器 ===== */
struct ThreadLocalStats {
    uint64_t events_processed = 0;
    uint64_t events_enqueued = 0;
    uint64_t cache_misses = 0;
};

thread_local ThreadLocalStats tl_stats;

class SimStats {
    PerCpuCounter total_events_;
    PerCpuCounter total_cycles_;

public:
    void record_event() {
        tl_stats.events_processed++;
        total_events_.add(1);
    }
    void record_cycle() { total_cycles_.add(1); }

    void print_summary() const {
        printf("=== Simulation Stats ===\n");
        printf("Total events: %lu\n", total_events_.sum());
        printf("Total cycles: %lu\n", total_cycles_.sum());
    }
};

/* ===== 性能测试 ===== */
static constexpr int NUM_THREADS = 16;
static constexpr int ITERATIONS  = 100'000'000;
static PerCpuCounter g_pcpu;
static _Atomic int g_done_threads = 0;

void bench_percpu(int tid)
{
    (void)tid;
    for (int i = 0; i < ITERATIONS; i++) {
        g_pcpu.add(1);
    }
    g_done_threads.fetch_add(1);
}

int main()
{
    std::vector<std::thread> threads;
    auto t0 = std::chrono::steady_clock::now();

    for (int i = 0; i < NUM_THREADS; i++) {
        threads.emplace_back(bench_percpu, i);
    }
    for (auto &t : threads) t.join();

    auto t1 = std::chrono::steady_clock::now();
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();

    printf("Threads: %d, Iterations: %d\n", NUM_THREADS, ITERATIONS);
    printf("Total: %lu (expected: %lu)\n",
           g_pcpu.sum(), (uint64_t)NUM_THREADS * ITERATIONS);
    printf("Time: %ld ms, ops/ms: %.0f\n", ms,
           (double)NUM_THREADS * ITERATIONS / ms);
    printf("Avg per op: %.2f ns\n",
           (ms * 1e6) / (NUM_THREADS * ITERATIONS));
    return 0;
}
```

---

## 5. 内核同步决策树：什么时候用什么？

```
数据访问模式
│
├─ 读多写少，数据小且可拷贝（≤ cache line）
│   └─ 写者极少（每毫秒一次或更少）→ 【seqlock】
│      读者：~10-15 ns，无锁，可能重试
│      写者：自旋锁保护，序列号翻转
│      示例：全局时间戳、jiffies、配置快照
│
├─ 读多写少，数据通过指针访问，读者极多
│   └─ 允许短暂看到旧数据，可延迟回收 → 【RCU】
│      读者：< 10 ns（QSBR），零开销
│      写者：拷贝-修改-发布，等待 grace period
│      示例：模块层次结构、事件队列表头、信号扇出表
│
├─ 数据天然按 CPU/线程分区，不需要跨核共享
│   └─ 统计计数器、每核事件队列 → 【Per-CPU 变量】
│      读/写：~1 ns，纯本地缓存访问
│      聚合：O(N_slots)，批量求和
│      示例：每线程事件计数、per-core 调度队列
│
├─ 读写均衡，需要严格互斥，临界区短
│   └─ 无竞争优先 → 【futex-based mutex（pthread_mutex / std::mutex）】
│      无竞争：~3-5 ns
│      有竞争：~100 ns 内核 wait，自动让出 CPU
│      示例：内存分配器、共享缓冲区的生产者-消费者
│
├─ 读写均衡，需要严格互斥，临界区长或不可预测
│   └─ 实时系统，避免优先级反转 → 【PI futex（FUTEX_LOCK_PI）】
│      内核管理优先级继承，防止死锁
│      示例：与硬件协同的实时仿真线程
│
├─ 需要阻塞等待条件，广播通知
│   └─ 避免惊群 → 【futex-based condvar + FUTEX_CMP_REQUEUE】
│      唤醒 1 个，其余 requeue 串行化
│      示例：线程池任务分发、仿真阶段同步
│
└─ 所有线程同步到达某一点（barrier）
    └─ 线程数 > 物理核心 → 【pthread_barrier（futex 实现）】
       自旋等待 > 5 µs 时比裸自旋锁更节能
       示例：时间步结束同步、波形转储同步
```

### 快速对照表

| 原语 | 读延迟 | 写延迟 | 读者并发 | 写者阻塞 | 数据量 | 代码复杂度 |
|------|--------|--------|----------|----------|--------|------------|
| **Seqlock** | 10~15 ns | 自旋锁 | 无限制 | 阻塞读者（重试） | 任意小结构 | 中（需防编译器重排） |
| **RCU (QSBR)** | **< 10 ns** | 等待 GP | 无限制 | 不阻塞读者 | 指针/链表 | 高（grace period 管理） |
| **Per-CPU** | **~1 ns** | **~1 ns** | 无（无共享） | 无 | 每个线程一份 | 低 |
| **Futex Mutex** | 3~5 ns（无竞争） | 3~5 ns（无竞争） | 1 | 内核等待 | 任意 | 低（直接用 pthread） |
| **自旋锁** | 10~20 ns | 10~20 ns | 1 | 忙等 | 任意 | 低 |

> **绝对不要**在 RTL 仿真器中把裸自旋锁作为主要同步机制。probablydance.com 实测：竞争超过 3~5 µs 时，自旋锁比 futex mutex 更浪费 CPU，因为自旋锁会让线程空转而不让出 CPU，导致调度器时间片被浪费。

---

## 6. 对 RTL 仿真器的具体启示与改造方案

### 6.1 模块层次结构 → RCU

**场景**：Verilator/Verilog 编译后的 module hierarchy 在仿真期间几乎不变，但事件传播需要频繁遍历（每周期每个信号变化都可能触发树遍历）。

**改造**：

```cpp
/* 用 RCU 保护模块层次结构 */
struct ModuleNode {
    std::string name;
    std::vector<ModuleNode*> children;  /* RCU 保护 */
    SignalTable *signals;                 /* RCU 保护 */
    struct rcu_head rcu;
};

/* 读者：每个事件传播线程无锁遍历 */
void propagate_event(ModuleNode *root, Signal *sig)
{
    rcu_read_lock();
    for (auto *child : rcu_dereference(root)->children) {  /* 无锁！ */
        /* 递归传播... */
    }
    rcu_read_unlock();
}

/* 写者：DPI 插入新模块或动态重配置 */
void insert_module(ModuleNode *parent, ModuleNode *new_child)
{
    pthread_mutex_lock(&module_lock);
    /* 复制父节点的 children 列表，加入新节点，原子替换 */
    auto *new_children = copy_children(parent);
    new_children->push_back(new_child);
    rcu_assign_pointer(parent->children, new_children);
    pthread_mutex_unlock(&module_lock);

    synchronize_rcu();  /* 或 call_rcu() 异步释放旧列表 */
    free_old_children(...);
}
```

**收益**：事件传播路径（读端）从 mutex + 条件变量的 ~100 ns 降到 **< 10 ns**，且读者数量线性扩展。

### 6.2 全局时间戳/周期计数 → Seqlock

**场景**：每个事件处理都需要读取 `current_time`，但只有时间推进时（每周期一次）才更新。

**改造**：

```cpp
static Seqlock<SimTime> g_sim_time;

/* 时间推进（单写者，或外部锁保护） */
void advance_time(uint64_t new_time)
{
    static uint64_t cycle = 0;
    g_sim_time.store(SimTime{new_time, cycle++, 0});
}

/* 任意事件处理线程读取时间 */
inline SimTime get_time() {
    return g_sim_time.load();  /* ~10-15 ns，无锁 */
}
```

**对比**：用 `std::atomic<uint64_t>` 只能保护单个 64-bit 值，而 `SimTime` 结构体（时间 + 周期 + 相位）用 seqlock 可原子性读取全部三个字段。如果用 mutex，每次读取 ~100 ns，在 100MHz 仿真中直接吃光性能预算。

### 6.3 每线程事件队列 → Per-CPU 变量

**场景**：PDES（Parallel Discrete Event Simulation）中，每个逻辑线程生成的事件插入全局队列是核心瓶颈。

**改造**：

```cpp
class PerThreadEventQueue {
    static constexpr int N = 64;
    struct alignas(64) Queue {
        std::vector<Event> local;
        std::mutex mut;  /* 仅用于调度阶段合并 */
    } queues_[N];

public:
    void enqueue(const Event &e) {
        size_t idx = std::hash<std::thread::id>{}(
            std::this_thread::get_id()) & (N - 1);
        queues_[idx].local.push_back(e);  /* 无锁！ */
    }

    /* 调度阶段：合并所有队列到全局时间轮 */
    std::vector<Event> merge_all() {
        std::vector<Event> merged;
        for (auto &q : queues_) {
            std::lock_guard<std::mutex> lk(q.mut);
            merged.insert(merged.end(), q.local.begin(), q.local.end());
            q.local.clear();
        }
        return merged;
    }
};
```

**收益**：事件插入从「所有线程竞争一个 mutex」变成「每个线程写本地 vector」，延迟从 ~100 ns 降到 **~1 ns**。

### 6.4 时间步同步 Barrier → Futex Barrier

**场景**：多线程仿真器中，所有线程必须完成当前时间步才能进入下一周期。

**改造**：直接用 `pthread_barrier_t`（底层就是 futex）：

```cpp
pthread_barrier_t cycle_barrier;
pthread_barrier_init(&cycle_barrier, nullptr, num_threads);

void simulation_thread(int tid)
{
    while (running) {
        /* 1. 处理本线程的事件 */
        process_local_events();

        /* 2. 同步：所有线程完成当前时间步 */
        pthread_barrier_wait(&cycle_barrier);
        /* 底层 futex：快速路径无竞争时 ~3-5 ns，有竞争时内核 wait */
    }
}
```

**对比**：裸自旋 barrier（`while (!all_done) pause();`）在线程数 > 物理核心时导致 CPU 空转，futex barrier 在同步时自动让出 CPU。

---

## 7. 完整可操作代码索引

| 代码 | 位置 | 说明 | 编译命令 |
|------|------|------|----------|
| RCU 链表 | 第 1.3 节 | liburcu QSBR 完整链表读写 | `gcc -O2 -lurcu-qsbr -lpthread` |
| RCU 异步回收 | 第 1.4 节 | `call_rcu()` 非阻塞释放 | 同上 |
| Seqlock 时间戳 | 第 2.3 节 | `SimTime` 结构体读写，含双重缓冲 | `g++ -O3 -std=c++17 -lpthread` |
| Seqlock 多写者 | 第 2.4 节 | CAS 循环支持多写者 | 同上 |
| Futex 互斥锁 | 第 3.3 节 | 裸 futex 封装，完整状态转换 | `g++ -O2 -std=c++17 -lpthread` |
| Per-CPU 计数器 | 第 4.2 节 | `thread_local` + 伪 Per-CPU 两种方案 | `g++ -O3 -std=c++17 -lpthread` |

---

## 8. 常见反模式与踩坑清单

| ❌ 反模式 | 为什么错 | ✅ 正确做法 |
|----------|----------|------------|
| 在 RCU 读端修改数据 | 读者无锁，写者按旧数据释放 | 读端纯只读，所有修改走写端 |
| Seqlock 不加编译器屏障 | GCC -O3 重排导致撕裂数据 | 插入 `std::atomic_signal_fence` 或用双重缓冲 |
| 用裸自旋锁替代 futex | 竞争 > 5µs 时浪费 CPU，调度器时间片被吃光 | 用 `pthread_mutex`（futex 底层），自动退化为内核 wait |
| Per-CPU 槽位数 = 线程数 | 线程动态创建销毁导致槽位抖动 | 槽位数 = 2 的幂且 ≥ 最大线程数，用线程 ID 哈希 |
| RCU 写端频繁 `synchronize_rcu()` | 阻塞写端，延迟累积 | 用 `call_rcu()` 异步回收，或批量回收 |
| 把 seqlock 用于大对象（> cache line） | 拷贝开销高，读者重试代价大 | 大对象用 RCU 指针替换，或只拷贝指针 |

---

## 9. 原文摘录

> "RCU is most frequently used to provide concurrency control for read-mostly linked data structures, so that read-side overhead is minimal. The word 'minimal' is no euphemism: In some common cases, RCU's read-side overhead both in the kernel and in user space approaches zero."
> — Paul E. McKenney, LWN 2013

> "A seqlock can be used as an alternative to a readers-writer lock. It will never block the writer and doesn't require any memory bus locks."
> — Erik Rigtorp, rigtorp/Seqlock

> "A futex (fast userspace mutex) is the kernel mechanism that allows userspace locking primitives to be efficient. The key insight: in the common uncontended case, locking and unlocking should happen entirely in userspace with no kernel involvement."
> — kernel-internals.org

> "Before futexes, every POSIX mutex operation went through the kernel. A syscall costs ~100–300 ns on modern hardware. A program that holds fine-grained mutexes for short durations could spend more time in the kernel than doing actual work."
> — kernel-internals.org

> "The fast path is atomic-only: Uncontended lock acquisition is a single atomic compare-and-swap instruction. ~10-20 cycles, no syscalls."
> — onenoughtone.com

---

## 相关页面

- [source-rcu-userspace](source-rcu-userspace.md) — RCU 用户空间实现与 QEMU 移植
- [source-seqlock](source-seqlock.md) — Seqlock C++11 实现与编译器重排陷阱
- [source-linux-kernel-sync](source-linux-kernel-sync.md) — Futex、Per-CPU 与内核同步决策树

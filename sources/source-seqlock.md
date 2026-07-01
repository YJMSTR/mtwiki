---
title: "Seqlock / Sequence Lock — 内核实现与用户空间 C++ 实现"
description: "Seqlock 的 Linux 内核实现、用户空间 C++11 实现（rigtorp/Seqlock），以及与 atomic 和传统锁的性能对比。涵盖 seqlock 在读写并发场景中的正确性陷阱与内存序问题。"
source_url: "https://github.com/rigtorp/Seqlock"
source_type: "github"
author: "Erik Rigtorp, Hans-J. Boehm (HP Labs), Linux Kernel Community"
date: "2016-01-04"
tags: ["seqlock", "sequence-lock", "lock-free", "c++11", "memory-order", "kernel"]
keywords: ["seqlock", "sequence lock", "memory_order_acquire", "atomic_signal_fence", "writer-priority", "torn-read", "retry"]
capture_date: "2026-07-02"
---

# Seqlock / Sequence Lock — 内核实现与用户空间 C++ 实现

## 来源

- URL: https://github.com/rigtorp/Seqlock (rigtorp/Seqlock)
- URL: https://stackoverflow.com/questions/79014088/is-this-seqlock-implementation-correct-from-the-c-memory-model-point-of-view
- URL: https://embetronicx.com/tutorials/linux/device-drivers/seqlock-in-linux-kernel/
- URL: https://github.com/jrajath94/low-latency-matching-engine (seqlock 在金融撮合引擎中的应用)
- 类型: github / doc / stackoverflow
- 作者: Erik Rigtorp, Linux Kernel Community, jrajath94
- 日期: 2016-2026

## 摘要

Seqlock（Sequence Lock）是一种**写者优先**的轻量级同步机制，读者完全不阻塞写者，代价是读者在检测到写操作并发时需要重试读取。其内核实现广泛用于 Linux 的 `jiffies`、`xtime` 等高频读、低频写的变量保护。用户空间 C++11 实现需特别注意**编译器重排**问题：GCC 在 `-O3` 优化下会将受保护数据的加载重排到序列号检查之外，必须通过 `std::atomic_signal_fence` 或双重缓冲修复。在正确实现下，seqlock 读操作仅涉及两次 `load(memory_order_acquire)` 和一次数据拷贝，延迟通常 < 20 ns，适合 RTL 仿真器的全局时间戳、配置快照等场景。

## 关键要点

- **写者优先**：写者通过自旋锁获得独占访问，读者无锁，仅在序列号变化时重试。适合写者极少、读者极多的场景。
- **C++11 实现陷阱**：裸实现中编译器可能重排 `copy = value_` 到 `seq0` 加载之前，导致读到撕裂数据（torn read）。
- **两种修复方案**：(1) `std::atomic_signal_fence(std::memory_order_acq_rel)` 作为编译器屏障（x86 适用）；(2) 双重缓冲，将数据存两份，根据序列号奇偶选择读取版本（全平台可移植）。
- **与 atomic 的对比**：seqlock 保护的数据量可以大于单个机器字；atomic 只能保护标量或指针。seqlock 的读者需要重试，atomic 的读者是 wait-free。
- **Linux 内核使用场景**：`seqlock` 用于保护 `jiffies`（系统节拍计数器）、`xtime`（墙上时间）等读者极多、写入频率低（通常每毫秒一次）的变量。

## 具体实现与代码示例

### Linux Kernel Seqlock API

```c
#include <linux/seqlock.h>

static seqlock_t my_seqlock;
static unsigned long my_data;

/* 初始化 */
void init(void)
{
    seqlock_init(&my_seqlock);
    my_data = 0;
}

/* 写者：必须持有锁，序列号在写前后各增 1 */
void writer_update(unsigned long new_val)
{
    write_seqlock(&my_seqlock);      /* seq += 1 (奇数) */
    my_data = new_val;               /* 写数据 */
    write_sequnlock(&my_seqlock);    /* seq += 1 (偶数) */
}

/* 读者：无锁，但可能重试 */
unsigned long reader(void)
{
    unsigned long val;
    unsigned seq;

    do {
        seq = read_seqbegin(&my_seqlock);
        val = my_data;               /* 拷贝数据 */
    } while (read_seqretry(&my_seqlock, seq));

    return val;
}
```

内核 `seqlock_t` 定义：

```c
typedef struct {
    unsigned seq;       /* 序列号：写前+1（奇数），写后+1（偶数） */
    spinlock_t lock;    /* 写者互斥 */
} seqlock_t;
```

### rigtorp/Seqlock — C++11 正确实现

```cpp
#include <atomic>
#include <cstddef>

template <typename T, size_t N = 64>
class Seqlock {
    alignas(N) std::atomic<std::size_t> seq_{0};
    alignas(N) T value_{};

public:
    Seqlock(T value = T()) : value_(value) {}

    /* 写者：单线程独占（或通过外部锁支持多写者） */
    void store(const T& value) noexcept {
        std::size_t seq = seq_.load(std::memory_order_relaxed);
        seq_.store(seq + 1, std::memory_order_release);  /* 奇数 = 正在写 */

        std::atomic_signal_fence(std::memory_order_acq_rel);  /* 编译器屏障 */
        value_ = value;
        std::atomic_signal_fence(std::memory_order_acq_rel);

        seq_.store(seq + 2, std::memory_order_release);  /* 偶数 = 写完成 */
    }

    /* 读者：多线程并发 */
    T load() const noexcept {
        T copy;
        std::size_t seq0, seq1;
        do {
            seq0 = seq_.load(std::memory_order_acquire);
            if (seq0 & 1) {
                /* 正在写，忙等或 yield */
                continue;
            }
            std::atomic_signal_fence(std::memory_order_acq_rel);  /* 关键：阻止编译器重排 */
            copy = value_;
            std::atomic_signal_fence(std::memory_order_acq_rel);
            seq1 = seq_.load(std::memory_order_acquire);
        } while (seq0 != seq1 || seq0 & 1);
        return copy;
    }
};

/* 使用示例 */
struct Data {
    std::size_t a, b, c;
};

Seqlock<Data> sl;
sl.store({100, 200, 300});

auto d = sl.load();  /* 读者：无锁，极大概率一次成功 */
```

### 编译器重排问题演示

以下**错误实现**在 GCC `-O3` 下会被重排：

```cpp
T load_buggy() const noexcept {
    T copy;
    size_t seq0, seq1;
    do {
        seq0 = seq_.load(std::memory_order_acquire);
        copy = value_;                 /* 编译器可能重排到 seq0 之前！ */
        seq1 = seq_.load(std::memory_order_acquire);
    } while (seq0 != seq1 || seq0 & 1);
    return copy;
}
```

GCC 5.2 `-O3` 生成的汇编（错误重排）：

```asm
401ad0:  8b 47 08              mov  0x8(%rdi),%eax   ; copy = value_ （先读数据！）
401ad3:  0f 1f 44 00 00        nopl 0x0(%rax,%rax,1)
401ad8:  48 8b 0f              mov  (%rdi),%rcx      ; seq0 = seq_
401adb:  48 8b 17              mov  (%rdi),%rdx      ; seq1 = seq_
```

插入 `std::atomic_signal_fence` 后，GCC 生成正确汇编：

```asm
4014e8:  48 8b 31              mov  (%rcx),%rsi      ; seq0 = seq_
4014eb:  8b 07                 mov  (%rdi),%eax      ; copy = value_ （在 seq0 之后）
4014ed:  48 8b 11              mov  (%rcx),%rdx      ; seq1 = seq_
```

### 双重缓冲方案（全平台可移植）

```cpp
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
```

### 多写者支持（CAS 循环）

```cpp
template <typename T>
class SeqlockMultiWriter {
    std::atomic<std::size_t> seq_{0};
    T value_{};

public:
    void store(const T& value) {
        std::size_t seq;
        do {
            seq = seq_.load(std::memory_order_relaxed);
            /* 等待其他写者完成 */
        } while (seq & 1 || !seq_.compare_exchange_weak(
            seq, seq + 1,
            std::memory_order_acquire,
            std::memory_order_relaxed));

        value_ = value;

        seq_.store(seq + 2, std::memory_order_release);
    }

    T load() const { /* 同单写者版本 */ }
};
```

## 性能数据

- **Seqlock 读延迟**：典型值 **< 20 ns**（两次 acquire load + 数据拷贝 + 比较），在 x86_64 上约为 10~15 ns。
- **与 rwlock 对比**：在高并发读场景下，rwlock 的读者需要原子操作更新共享读者计数器（缓存行竞争），seqlock 读者完全不触碰共享计数器（除序列号读取外）。
- **与 atomic 对比**：`std::atomic<int>` load 约 1~2 ns（x86_64 上 `mov` 即可），但只能保护单个标量；seqlock 可保护任意 `TrivialType` 结构体。
- **金融撮合引擎实测**：在订单簿快照场景中，seqlock 读者"重试极其罕见——写窗口仅为纳秒级"（来源：low-latency-matching-engine）。

## 对 RTL 仿真器多线程化的启示

1. **全局仿真时间戳**：`current_time` 是极高频读（每个事件处理都需要）、低频写（仅在时间推进时更新）的变量。seqlock 是理想保护机制：读者无锁读时间戳，时间推进时写者加锁更新。
2. **波形配置快照**：仿真过程中可能切换波形记录配置（开关某些信号的记录）。seqlock 允许读者获取一致的配置快照，写者切换配置时读者自动重试，无需全局暂停。
3. **与 RCU 的区分**：seqlock 适合小体积、可拷贝的标量/结构体；RCU 适合指针型、需要动态分配的数据结构（如事件队列、模块树）。RTL 仿真器的时间戳用 seqlock，事件队列用 RCU。
4. **编译器屏障的教训**：在 C++ 中实现类似 seqlock 的模式时，必须显式使用 `std::atomic_signal_fence` 或 `std::atomic_thread_fence`，不能依赖编译器的"合理行为"。RTL 仿真器若自行实现轻量级同步原语，必须验证生成的汇编。

## 原文摘录

> "A seqlock can be used as an alternative to a readers-writer lock. It will never block the writer and doesn't require any memory bus locks."
> — Erik Rigtorp, rigtorp/Seqlock

> "The seqlock pattern solves the concurrent reader problem without blocking the matching thread. The matching thread increments an atomic sequence counter before and after each write (odd = writing, even = done). Reader threads check the counter before reading, then check again after. If the counter changed, the reader retries. In practice, retries are extremely rare — the write window is nanoseconds."
> — low-latency-matching-engine

> "The main problem with seqlock is that writes can be reordered by the CPU which is why a C++ memory-model compliant implementation needs a compare-exchange on the writer side, which makes it not exactly a seqlock, but a slower modified version of it."
> — StackOverflow 讨论

> "Reading `seq0` with an acquire order is enough to establish a `synchronizes with` relationship with the writer, you don't need an RMW here... there is no scenario where `seq0 == seq1` and the data is not the same one."
> — StackOverflow 79014088

## 相关链接

- [rigtorp/Seqlock (GitHub)](https://github.com/rigtorp/Seqlock)
- [Seqlock in Linux Kernel (Embetronicx)](https://embetronicx.com/tutorials/linux/device-drivers/seqlock-in-linux-kernel/)
- [StackOverflow: C++11 seqlock 内存序正确性](https://stackoverflow.com/questions/79014088/is-this-seqlock-implementation-correct-from-the-c-memory-model-point-of-view)
- [StackOverflow: 如何实现 seqlock](https://stackoverflow.com/questions/20342691/how-to-implement-a-seqlock-lock-using-c11-atomic-library)
- [low-latency-matching-engine (GitHub)](https://github.com/jrajath94/low-latency-matching-engine)
- [htfy96/seqlock (C++11 多写者支持)](https://github.com/htfy96/seqlock)
- [Can Seqlocks Get Along With Programming Language Memory Models? (HP Labs, PDF)](https://www.hpl.hp.com/techreports/2012/HPL-2012-68.pdf)

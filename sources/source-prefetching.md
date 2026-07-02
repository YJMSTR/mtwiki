---
title: Prefetching & Cache Line Utilization in RTL Simulation
description: 软件预取、硬件预取器与缓存行利用在 RTL 仿真器中的优化策略，包含 __builtin_prefetch 示例、stride prefetching 机制及缓存行对齐数据
date: "2026-07-03"
source_url: "https://paweldziepak.dev/2019/05/02/on-lists-cache-algorithms-and-microarchitecture/"
source_type: "blog"
author: "Paweł Dziepak / Intel Optimization Manual / CMU 15-745"
tags: ["prefetching", "cache-line", "stride-prefetching", "spatial-locality", "software-prefetch", "RTL-simulation"]
keywords: ["__builtin_prefetch", "hardware prefetcher", "DCU prefetcher", "cache line utilization", "spatial locality", "memory-level parallelism"]
capture_date: "2026-07-03"
---

# 预取与缓存行利用在 RTL 仿真器中的优化

## 来源

- URL: https://paweldziepak.dev/2019/05/02/on-lists-cache-algorithms-and-microarchitecture/
- URL: https://www.techinterview.org/post/3233473069/lld-cpu-cache-optimization/
- URL: https://www.cis.upenn.edu/~cis5710/spring2026/slides/10_caches.pdf
- URL: https://yunmingzhang.wordpress.com/2019/02/12/software-prefetching-in-c-c/
- URL: https://jilp.org/vol6/v6paper7.pdf
- 类型: blog / lecture notes / research paper
- 作者: Paweł Dziepak / Intel / CMU / Yunming Zhang / JILP
- 日期: 2019-05-02 / 2018–2020

## 摘要

RTL 仿真器（如 gem5、Verilator、SST）的瓶颈常常不在 ALU 而在内存子系统：事件队列遍历、信号翻转记录、波形内存访问等都会产生大量不规则或半规则的指针追踪。现代 CPU 拥有四个硬件预取器（DCU、DCU IP-based、Spatial、Streamer），但对链表、B-tree、事件队列等小型离散对象的遍历无能为力。本文档汇总软件预取（`__builtin_prefetch`）、硬件预取器行为、缓存行对齐与 loop interchange 等技术，并给出带性能数据的汇编级示例，为 RTL 仿真器的数据结构优化提供底层参考。

## 关键要点

- **硬件预取器覆盖范围**：Intel 处理器的四个硬件预取器分别覆盖顺序访问、固定步长访问、相邻缓存行和空间流访问。对于链表、哈希表、事件队列等离散小对象，硬件预取器基本失效。
- **软件预取指令**：GCC/Clang 提供 `__builtin_prefetch(addr, rw, locality)`，其中 `rw=0` 为读、`1` 为写；`locality=0` 表示无时间局部性（用完即丢），`3` 表示高时间局部性（保留在各层缓存）。对应 x86 的 `PREFETCHT0`/`T1`/`T2`/`NTA`。
- **预取距离（Prefetch Distance）**：对 DRAM 延迟（约 80–200 周期），通常需要提前 10–20 次迭代发出预取；对 L2 命中则 4–8 次迭代即可。预取过早造成缓存污染，过晚则无法隐藏延迟。
- **缓存行对齐（Cache Line Alignment）**：C++11 `alignas(64)` 或 `__attribute__((aligned(64)))` 可将结构体起始地址对齐到缓存行边界，避免 false sharing 和跨行访问。RTL 仿真器中的事件结构、信号值、时间戳若未对齐，单条访问可能触发两次缓存行读取。
- **Loop Interchange 与 Spatial Locality**：row-major 的二维数组按列访问会丧失空间局部性；交换循环顺序可将 cache miss 降低一个数量级。
- **Memory-Level Parallelism (MLP)**：同时发出多个预取请求，让内存控制器并行处理，是隐藏 DRAM 延迟的核心手段。软件预取可显式提升 MLP。

## 汇编与代码示例

### 1. 基础软件预取：链表遍历

```cpp
template<typename Iterator, typename T, typename Function>
T accumulate(Iterator first, Iterator last, T init, Function fn) {
    while (first != last) {
        __builtin_prefetch(first.current_->next_);  // 预取下一个节点
        init = fn(init, *first);
        ++first;
    }
    return init;
}
```

GCC 编译出的 x86-64 汇编（Haswell, `-O3 -march=haswell`）：

```asm
.L3:
    mov     rcx, QWORD PTR [rdi+8]    ; current_->next_
    prefetcht0 [rcx]                  ; 预取到 L1
    add     eax, DWORD PTR [rdi+16]   ; fn(init, *first)
    mov     rdi, QWORD PTR [rdi]      ; first = first->next_
    cmp     rdi, rsi                  ; first != last?
    jne     .L3
```

### 2. 预取距离控制：数组遍历（提前 P 个元素）

```cpp
for (int i = 0; i < N; i++) {
    __builtin_prefetch(&a[i + P]);   // P 通常为 10–20
    __builtin_prefetch(&b[i + P]);
    sum += a[i] * b[i];
}
```

对应的 x86 预取指令：
```asm
    prefetcht0  [rax + P*4]           ; PREFETCHT0 到 L1
    prefetcht0  [rbx + P*4]
    vmulps      ymm0, ymm0, YMMWORD PTR [rax]
    add         rax, 32
```

### 3. 缓存行对齐：RTL 事件结构体

```cpp
struct alignas(64) Event {
    uint64_t timestamp;      // 8 bytes
    uint32_t signal_id;      // 4 bytes
    uint32_t value;          // 4 bytes
    Event*   next;           // 8 bytes
    uint8_t  flags;          // 1 byte
    // 填充到 64 字节，避免跨行
    uint8_t  pad[39];        // 64 - (8+4+4+8+1) = 39
};

static_assert(sizeof(Event) == 64, "Event must fit in one cache line");
```

对应汇编：访问 `Event` 的任何字段都只触及一条缓存行，不会出现两条 cache line 的 split load。

### 4. Loop Interchange：矩阵访问优化

**差（column-major 访问，row-major 存储）**：
```cpp
for (int j = 0; j < NCOLS; j++)       // 外层列
    for (int i = 0; i < NROWS; i++)    // 内层行
        sum += X[i][j];                // 每次跳跃 NCOLS * sizeof(T)
```

**好（row-major 访问，符合 C 数组布局）**：
```cpp
for (int i = 0; i < NROWS; i++)
    for (int j = 0; j < NCOLS; j++)
        sum += X[i][j];                // 顺序访问，空间局部性最大化
```

效果：差版本的 cache miss 率可高出 10–100 倍，因为每次内层迭代都跨行跳跃，硬件预取器无法识别 stride。

### 5. 双端遍历 + 双向预取（最大化 MLP）

```cpp
template<typename Iterator, typename T, typename Function>
T reduce(Iterator first, Iterator last, T init, Function fn) {
    T a = init, b{};
    while (first != last) {
        auto current = first;
        ++first;
        __builtin_prefetch(first.current_->next_);   // 正向预取
        a = fn(a, *current);
        if (first == last) break;
        --last;
        current = last;
        __builtin_prefetch(last.current_->prev_);     // 反向预取
        b = fn(b, *current);
    }
    return a + b;
}
```

此技巧利用内存控制器的 MLP：同时存在两个独立的指针链，处理器可在等待前一个 load 时并行处理后一个。

## 性能数据

### 链表遍历：软件预取效果（Paweł Dziepak, i7-5960X）

测试场景：随机内存分布的链表，每个节点含两个指针 + 一个 int（24 bytes）。`count_primes` 为每个节点做素数判断（计算密集型）。

| 链表大小 | 无预取 (ops/s) | 有预取 (ops/s) | 提升 |
|---|---|---|---|
| 1,024 | 16.92M | 17.56M | +3.8% |
| 16,384 | 16.95M | 18.01M | +6.3% |
| 131,072 | 16.50M | 17.95M | +8.8% |
| 1,048,576 | 10.60M | 16.09M | **+51.8%** |
| 8,388,608 | 7.31M | 14.11M | **+92.6%** |
| 33,554,432 | 6.98M | 13.93M | **+99.6%** |

结论：当数据集超出 L3 缓存、内存延迟成为瓶颈时，软件预取几乎能让性能翻倍。数据集较小时（L1/L2 命中），预取收益有限，甚至可能因额外指令带来轻微开销。

### 数组 vs 链表：顺序访问的带宽对比（同一来源）

| 数据结构 | L1 命中时 | 超出 L3 后 |
|---|---|---|
| 数组（vectorized） | ~17.7 G/s | ~3.4 G/s |
| 链表（顺序存储） | ~744 M/s | ~342 M/s |
| 链表（随机存储） | ~743 M/s | ~9.7 M/s |

说明：链表即使节点在内存中连续，也因指针追踪依赖和无法向量化而比数组慢 20–50 倍；随机存储后进一步恶化 30–100 倍。

### 硬件预取器与软件预取协同（JILP Vol 6）

在 80 周期内存延迟、带宽 1–64 GB/s 的模拟环境中：
- 纯硬件 stride prefetching：在规则步长访问中可将内存 stall 降低 50–90%
- 纯软件 prefetching：对不规则访问（如 CCMALLOC）表现优于硬件预取
- **协同（Stride + Software + Locality Opt）**：在大多数 benchmark 上表现最优，优于任何单一方案

> "Stride+Opt outperforms Pref+Opt overall. This result indicates locality optimization, when applied in concert with prefetching, not only reduces memory traffic, but also enables stride-based hardware prefetching for benchmarks that do not normally exhibit striding."

## 对 RTL 仿真器多线程化的启示

1. **事件队列/时间轮的数据结构选型**：RTL 仿真器常用的时间队列（timing wheel）或事件队列若采用链表实现，在事件数 > L3 容量时性能会急剧崩塌。考虑：
   - 将事件按时间桶分桶后，桶内用数组而非链表存储；
   - 遍历桶时插入 `__builtin_prefetch` 预取后续事件；
   - 对事件结构体使用 `alignas(64)` 确保单事件不跨缓存行。
2. **信号翻转记录的顺序访问**：波形 dump（VCD/FST）模块通常按时间顺序写入信号值。若数据布局为 SoA（Structure of Arrays）而非 AoS，可获得更好的空间局部性和自动向量化机会。
3. **跨线程的缓存行隔离**：多线程 RTL 仿真中，每个线程的局部状态变量（如当前时间、PC、临时寄存器值）应放在独立的 `alignas(64)` 结构体中，避免 false sharing 导致缓存行在核间来回弹跳。
4. **预取指令的调度距离调参**：RTL 仿真器的「执行阶段」通常包含多个子阶段（取指、译码、执行、访存、写回）。在访存阶段前 2–3 个阶段插入预取，可将 DRAM 延迟隐藏在前面阶段中。
5. **避免 PREFETCHNTA 误用**：`PREFETCHNTA`（non-temporal, locality=0）适合流式数据（如只读一次的波形 dump），但 RTL 仿真器核心状态（寄存器文件、内存模型）通常具有时间局部性，应使用 `PREFETCHT0`（locality=3）。

## 原文摘录

> "The processor has four hardware prefetchers: DCU prefetcher, DCU IP-based prefetcher, Spatial Prefetcher, Streamer. These prefetchers cover sequential accesses and large objects spanning multiple cache lines, but there's nothing that would help with lists of small objects. We need software prefetching."
> — Paweł Dziepak

> "If the prefetch is done early enough before the access then the data will be in the cache by the time it is accessed. In my experience, it actually made many applications slower... There could be several reasons: prefetching too late, too early, or polluting the cache."
> — Yunming Zhang, *Software prefetching in C/C++*

> "Effectiveness is determined by: Timeliness — initiate prefetches sufficiently in advance; Coverage — prefetch for as many misses as possible; Accuracy — don't pollute with unnecessary data."
> — CMU 15-745, *Prefetching Arrays*

> "Stride+Opt outperforms Pref+Opt overall. Locality optimization enables stride-based hardware prefetching for benchmarks that do not normally exhibit striding."
> — JILP Vol 6, *The Efficacy of Software Prefetching and Locality Optimizations*

## 相关链接

- [On lists, cache, algorithms, and microarchitecture](https://paweldziepak.dev/2019/05/02/on-lists-cache-algorithms-and-microarchitecture/)
- [Software prefetching in C/C++](https://yunmingzhang.wordpress.com/2019/02/12/software-prefetching-in-c-c/)
- [CMU 15-745: Prefetching Arrays](https://www.cs.cmu.edu/afs/cs/academic/class/15745-s16/www/lectures/L21-Prefetching-Arrays.pdf)
- [JILP: The Efficacy of Software Prefetching and Locality Optimizations](https://jilp.org/vol6/v6paper7.pdf)
- [Intel Optimization Manual: General Prefetch Coding Guidelines](https://zzqcn.github.io/perf/intel_opt_manual/7.html)
- [Data Prefetching Schemes (ETH Zurich)](https://safari.ethz.ch/architecture/fall2020/lib/exe/fetch.php?media=00288147.pdf)

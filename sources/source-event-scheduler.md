---
title: 事件调度引擎优化：Calendar Queue、Ladder Queue、Splay Tree 与数字事件轮
description: 系统梳理离散事件仿真（DES）中 Future Event List 的数据结构选型，聚焦 Calendar Queue、Ladder Queue、Splay Tree、Binary Heap 的复杂度、性能对比与 RTL 仿真器适用性。
source_url: "https://sigsim.acm.org/conf/mskr/Courseware/Fujimoto/Slides/FujimotoSlides-03-FutureEventList.pdf"
source_type: "doc"  # github-pr, github-issue, blog, doc, paper, competition
author: "Richard M. Fujimoto / D. Jones / R. Brown / W.T. Tang 等"
date: "1986-2005"
tags: ["event-queue", "calendar-queue", "ladder-queue", "splay-tree", "des", "scheduler", "priority-queue"]
keywords: ["event queue optimization", "calendar queue simulation", "ladder queue event driven", "splay tree event scheduler", "event wheel digital simulation"]
capture_date: "2025-07-02"
---

# 事件调度引擎优化：Calendar Queue、Ladder Queue、Splay Tree 与数字事件轮

## 来源

- **URL**: 
  - https://sigsim.acm.org/conf/mskr/Courseware/Fujimoto/Slides/FujimotoSlides-03-FutureEventList.pdf
  - https://www.scs-europe.net/services/esm2004/pdf/hpc-04.pdf (Goh et al., Demarcate Construction)
  - https://cacm.acm.org/research/calendar-queues-a-fast-01-priority-queue-implementation-for-the-simulation-event-set-problem/
  - https://www.cnblogs.com/llguanli/p/8296732.html (gem5 EventQueue)
- **类型**: doc / paper / blog
- **作者**: Richard M. Fujimoto, D. Jones, R. Brown, W.T. Tang 等
- **日期**: 1986-2005

## 摘要

离散事件仿真（DES）的核心是 Future Event List（FEL），即按时间戳排序的待处理事件集合。Comfort (1984) 指出，**高达 40%** 的仿真执行时间消耗在 FEL 管理上，其中 `enqueue` 与 `dequeue` 占 FEL 操作的 **98%**。本文梳理了主流 FEL 数据结构：线性链表（小队列最快）、二叉堆（稳定 O(log n)）、Splay Tree（均摊 O(log n)，自带 FIFO 稳定性）、Calendar Queue（期望 O(1)，但最坏 O(n)）、Ladder Queue（分层解决 CQ 不稳定问题）。对于 RTL 仿真器，事件调度引擎直接决定多线程化后事件分发的吞吐上限，选型需兼顾时间戳分布、事件规模与缓存局部性。

## 关键要点

- **线性链表**：n < 10 时最快，但 n > 50 后性能崩塌，仅适合微型仿真。
- **二叉堆**：稳定 O(log n)，实现简单，是 Network Simulator v2 等项目的默认选择，但非最优。
- **Splay Tree**：均摊 O(log n)，支持 `DeleteArbitrary`，且同优先级事件天然 FIFO；反复访问模式会自平衡，缓存友好性较好。
- **Calendar Queue (CQ)**：Brown 1988 提出，期望 O(1) insert/delete。类比日历桶数组，每个桶覆盖固定时间区间。当事件数 n 与均值增量 μ 稳定时性能极佳，但桶数量或桶宽选择不当会导致 O(n) 退化。
- **Ladder Queue**：Tang et al. 2005 提出，将 FEL 分为三层：Top（远未来无序列表）、Ladder（多级日历桶，可动态 spawn 新 rung）、Bottom（近未来有序列表）。在 n 和 μ 波动场景下比 CQ 更稳定。
- **数字事件轮（Event Wheel）**：固定桶宽的循环数组，适合硬件仿真中时钟周期密集、事件时间戳分布集中的场景，可实现 O(1) 推进。

## 对 RTL 仿真器多线程化的启示

RTL 仿真器（如 Verilator、gem5）的事件调度具有以下特征，直接影响 FEL 选型：

1. **时间戳分布高度集中**：数字电路中大量事件发生在下一个时钟沿（如 `posedge clk`），时间戳增量 μ 往往固定或集中在少数离散值。这恰好是 **Calendar Queue** 和 **Event Wheel** 的舒适区。
2. **事件规模巨大**：现代 SoC 仿真可能产生数百万级事件，线性链表不可接受；Splay Tree 或 Heap 的 O(log n) 成为可预测的下限。
3. **多线程事件插入**：在 MT 模式下，多个工作线程可能同时向全局 FEL 插入事件。若使用锁保护单个大顶堆，锁竞争将成为瓶颈。可借鉴 **Ladder Queue** 的分层思想，将「近未来事件」缓存在线程局部 Bottom 层，批量合并到全局队列。
4. **gem5 的实践**：gem5 的 EventQueue 将事件分为同步（synchronous，同队列内插入）和异步（asynchronous，跨队列插入）。异步事件先进入 `async_queue`，在 simulation quantum 结束时合并，避免跨线程锁死锁。这种「延迟批量合并」思路与 Ladder Queue 的 Bottom→Ladder 迁移异曲同工。
5. **缓存局部性优先**：对于超大规模 RTL 仿真，Calendar Queue 的桶数组具有良好缓存局部性，相比树结构指针跳跃更少。

## 代码示例

### 1. 基于 Calendar Queue 的事件插入（简化概念）

```cpp
struct Event {
    double timestamp;
    int    id;
};

class CalendarQueue {
    static constexpr int BUCKET_COUNT = 1024;
    static constexpr double DAY_WIDTH   = 1.0; // 桶宽 = 1 时间单位
    std::vector<std::list<Event>> buckets{BUCKET_COUNT};
    int current_year = 0;
    int today = 0; // 当前桶索引

    int bucket_index(double ts) const {
        int idx = static_cast<int>(std::floor(ts / DAY_WIDTH)) % BUCKET_COUNT;
        return idx;
    }

public:
    void enqueue(const Event& ev) {
        int idx = bucket_index(ev.timestamp);
        auto& lst = buckets[idx];
        // 桶内保持有序插入（线性搜索）
        auto it = lst.begin();
        for (; it != lst.end() && it->timestamp < ev.timestamp; ++it) {}
        lst.insert(it, ev);
    }

    Event dequeue() {
        // 从 today 桶开始扫描，找到当前年份最小事件
        for (int i = 0; i < BUCKET_COUNT; ++i) {
            int idx = (today + i) % BUCKET_COUNT;
            auto& lst = buckets[idx];
            if (!lst.empty()) {
                auto ev = lst.front();
                if (ev.timestamp < (current_year + 1) * BUCKET_COUNT * DAY_WIDTH) {
                    lst.pop_front();
                    today = idx;
                    return ev;
                }
            }
        }
        // 进入下一年
        ++current_year;
        today = 0;
        return dequeue(); // 递归进入新 year
    }
};
```

### 2. Ladder Queue 三层结构（伪代码）

```cpp
struct LadderQueue {
    std::list<Event> top;           // 远未来，无序
    std::vector<std::list<Event>> ladder; // 多级桶，每级桶宽递减
    std::list<Event> bottom;        // 近未来，有序

    static constexpr int BOTTOM_THRESHOLD = 64;

    void enqueue(Event ev) {
        if (ev.timestamp < top_start) {
            if (bottom.size() < BOTTOM_THRESHOLD) {
                // 插入 bottom 有序列表
                insert_sorted(bottom, ev);
            } else {
                // spawn 新 ladder rung，将 bottom 部分事件迁移
                spawn_new_rung();
                ladder_enqueue(ev);
            }
        } else {
            top.push_back(ev);
            update_top_stats(ev.timestamp);
        }
    }

    Event dequeue() {
        if (!bottom.empty()) return pop_front(bottom);
        // bottom 空，从 ladder 补充
        if (refill_bottom_from_ladder()) return dequeue();
        // ladder 空，从 top 抽取最小事件重建 ladder
        rebuild_ladder_from_top();
        return dequeue();
    }
};
```

### 3. Splay Tree 最小事件删除（经典）

```cpp
// Splay Tree 删除最小节点 = 不断访问左子树，然后删除根并 splay 父节点
// 均摊 O(log n)，自带 locality 优化
```

## 性能数据

### Jones 1986 (VAX 11/780) — 指数分布时间戳

| 数据结构 | n = 10 | n = 100 | n = 1,000 | n = 10,000 |
|----------|--------|---------|-----------|------------|
| 线性链表 | **1** (最快) | 8 | 11 | 11 |
| 二叉堆 | 5 | 3 | 3 | 3 |
| Splay Tree | 6 | 4 | 4 | 4 |
| Calendar Queue | 4 | 1 | **1** | **1** |

> 注：数字为相对排名，1 = 最快。Calendar Queue 在 n ≥ 100 时显著优于树结构，但严重依赖参数调优。

### Brown 1988 — Calendar Queue vs Splay Tree

- **Calendar Queue** 在 n = 10,000 时的 hold time（dequeue + enqueue）比 Splay Tree **短 3 倍**。
- 但 CQ 在桶宽不当或事件分布 skewed 时，可能出现 **O(n) 退化**，远超树结构的可预测上界。

### Goh et al. 2004 (ESM) — Demarcate Tree vs Calendar Queue

- 提出的 **Demarcate Construction** 树结构在多种场景下平均加速 **> 2×** 于单树结构（Splay/Skew Heap）。
- 在事件分布波动大的场景中，新型树结构甚至优于 Calendar Queue。

### gem5 EventQueue 特征

- 同步事件直接插入当前 EventQueue，无需跨线程锁。
- 异步事件通过 `async_queue` 延迟合并，防止死锁。
- 跨线程插入要求时间差超过一个 quantum，否则目标队列可能已处理过该时间点。

## 原文摘录

> "A priority queue plays an important role in stochastic discrete event simulations for as much as 40% of a simulation execution time is consumed by the pending event set management."
> —— Goh et al., *ESM 2004*

> "Comfort (1984) has revealed that up to 40% of the computational effort in a simulation may be devoted on the management of the PES alone, where the enqueue and dequeue operations account for as much as 98% of all operations on the PES."
> —— Goh et al., *ESM 2004*

> "Calendar Queue displays hold times three times shorter than splay trees for a queue size of 10,000 events. The new implementation is a very simple structure of the multiple list variety using a novel solution to the overflow problem."
> —— R. Brown, *Communications of the ACM, 1988*

> "Ladder Queue addresses unstable property of calendar queue... In practice, extremely poor performance sometimes observed, due to excessive resizing operations or many items mapping to the same bucket."
> —— Fujimoto, *Future Event List Slides*

## 相关链接

- [Fujimoto: Future Event List (Slides)](https://sigsim.acm.org/conf/mskr/Courseware/Fujimoto/Slides/FujimotoSlides-03-FutureEventList.pdf)
- [Brown 1988: Calendar Queue (CACM)](https://cacm.acm.org/research/calendar-queues-a-fast-01-priority-queue-implementation-for-the-simulation-event-set-problem/)
- [Goh et al. 2004: Demarcate Tree Priority Queue](https://www.scs-europe.net/services/esm2004/pdf/hpc-04.pdf)
- [Tang et al. 2005: Ladder Queue (TOMACS)](https://doi.org/10.1145/1082464.1082466)
- [gem5 EventQueue 分析（中文博客）](https://www.cnblogs.com/llguanli/p/8296732.html)
- [SO: Event Driven Simulation with Binary Heap](https://stackoverflow.com/questions/52429914/event-driven-simulation-using-priority-queue-implemented-with-binary-heap)

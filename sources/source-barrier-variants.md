---
title: Barrier Synchronization Variants 性能对比与实现
description: 搜集中心化 barrier、tree barrier、dissemination barrier、tournament barrier、MCS lock 等高级同步原语的性能数据与实现细节，特别关注减少 cache coherence traffic 的 barrier 设计。
source_url: "https://www.cs.rochester.edu/u/scott/papers/1991_TOCS_synch.pdf"
source_type: "paper"
author: "John M. Mellor-Crummey & Michael L. Scott"
date: "1991-02"
tags: ["barrier", "synchronization", "cache-coherence", "MCS", "dissemination", "tree-barrier"]
keywords: ["futex barrier", "sense-reversal barrier", "tree barrier", "dissemination barrier", "ticket barrier", "cache coherence traffic"]
capture_date: "2026-07-01"
---

# Barrier 同步变体：从中心化到无竞争设计

## 来源

- URL: <https://www.cs.rochester.edu/u/scott/papers/1991_TOCS_synch.pdf>
- 类型: paper (ACM TOCS, Vol. 9, No. 1, February 1991)
- 作者: John M. Mellor-Crummey (Rice University), Michael L. Scott (University of Rochester)
- 日期: 1991-02
- 辅助来源:
  - CMU 15-740 课程讲义: <https://www.cs.cmu.edu/afs/cs/academic/class/15740-f98/public/lectures/lect20.pdf>
  - Rochester Barrier Methods 讲义: <https://www.cs.rochester.edu/u/sandhya/csc458/seminars/jb_Barrier_Methods.pdf>

## 摘要

Mellor-Crummey 与 Scott 的这篇经典论文论证了一个核心观点：**忙等同步的内存/互联竞争并非不可避免**。通过让每个处理器仅在本地可访问的 flag 上自旋，可以用纯软件算法实现 O(1) 远程引用每次锁获取，以及 O(1) 或 O(log P) 的 barrier 同步。论文提出的 **MCS 队列锁**、**Tree Barrier**、**Dissemination Barrier** 等算法已成为现代并行运行时（包括 Linux futex、OpenMP runtime、TBB）的底层基础。对 RTL 仿真器这种线程密集、同步频繁的场景，选择合适的 barrier 算法直接影响 scaling 天花板。

## 关键要点

- **中心化 Barrier (Centralized / Sense-Reversal)**：实现最简单，但所有线程竞争同一共享变量，非缓存一致性机器上产生 O(P²) 流量，仅适用于少量线程或广播式缓存一致性系统。
- **Software Combining Tree Barrier**：将竞争分散到树结构上，关键路径 O(log P)，总流量 O(P)，但线程可能需要在动态分配的内存位置上远程自旋。
- **Dissemination Barrier**：log P 轮两两同步，每轮线程 i 与 (i+2^k) mod P 同步。关键路径 ≈ 1/3 短于 Tree Barrier，但总流量 O(P log P)。优势是 flag 可静态分配，实现纯本地自旋。
- **Tournament Barrier**：二进制组合树，无需 fetch&op 指令，代表处理器静态选定。无一致性缓存时表现良好。
- **MCS Tree Barrier**：结合 4-ary 到达树与中央 sense-reversing 唤醒标志，在广播式缓存一致机器上达到 O(1) 远程引用每次到达。
- **选择策略**：
  - 广播式缓存一致性机器 → 集中式计数器（线程数 modest）或 4-ary arrival tree + central sense-reversing wakeup。
  - 无一致性缓存 / 目录式一致性 → Dissemination barrier 或 tree-based barrier with tree wakeup。

## 对 RTL 仿真器多线程化的启示

RTL 仿真器（如 Verilator）的多线程模型通常将电路划分到多个线程，每个时间步需要 barrier 同步。对于 8~64 线程的规模：

1. **避免纯中心化 barrier**：如果仿真器使用 `pthread_barrier` 或自研计数器，高频时间步会导致大量 cache line 乒乓，尤其在 NUMA 机器上。
2. **Dissemination Barrier 的潜力**：由于线程数相对固定，且 flag 可静态分配，可实现零远程自旋。虽然 O(P log P) 总消息量，但在现代 CPU 的缓存一致性广播机制下，小常数开销往往比树 barrier 更可控。
3. **MCS 风格的 tree barrier**：如果 RTL 仿真器有层级化的线程分组（如 per-socket 分组），4-ary 树结构可以匹配 NUMA 拓扑，减少跨 socket 流量。
4. **Linux futex 的启发**：现代 futex 已实现 `FUTEX_WAIT_MULTIPLE` 等机制，本质上将内核态排队与用户态自旋结合，可直接借鉴到仿真器自研线程池的 barrier 实现。

## 原文摘录

> "We argue that this problem is not fundamental, and that one can in fact construct busy-wait synchronization algorithms that induce no memory or interconnect contention. The key to these algorithms is for every processor to spin on separate locally-accessible flag variables, and for some other processor to terminate the spin with a single remote write operation at an appropriate time."

> "For barrier synchronization we suggest: On a broadcast-based cache-coherent multiprocessor, use either a centralized counter-based barrier (for modest numbers of processors), or a barrier based on our 4-ary arrival tree and a central sense-reversing wakeup flag. On a multiprocessor without coherent caches, use either the dissemination barrier or our tree-based barrier with tree wakeup."

> "The critical path through the dissemination barrier algorithm is about a third shorter than that of the tree barrier, but the total amount of interconnect traffic is O(P log P) instead of O(P). The dissemination barrier will outperform the tree barrier on machines which allow non-interfering network transactions from many different processors to proceed in parallel."

## 代码示例

### 1. Centralized Sense-Reversal Barrier（C 伪代码）

```c
typedef struct {
    int counter;
    bool sense;
} central_barrier_t;

void central_barrier_init(central_barrier_t *b, int n) {
    b->counter = n;
    b->sense = false;
}

void central_barrier_wait(central_barrier_t *b, int n) {
    bool local_sense = !b->sense;
    if (atomic_fetch_sub(&b->counter, 1) == 1) {
        // 最后一个到达的线程
        b->counter = n;
        b->sense = local_sense;  // 单点写，唤醒所有等待者
    } else {
        while (b->sense != local_sense) {
            // 在本地缓存的共享变量上自旋
            cpu_relax();
        }
    }
}
```

- **流量分析**：在缓存一致性机器上，所有线程读取同一 `sense` 变量，释放时产生 P 次 invalidation。O(P) 操作在关键路径上，O(1) 空间。
- **陷阱**：必须确保线程离开 barrier 前，新进入的线程不会误读旧的 `sense` 值。Sense-reversal 解决了这一问题。

### 2. Dissemination Barrier（C 伪代码）

```c
#define P 64          // 线程数
#define LOGP 6

typedef struct {
    bool flags[LOGP][2];  // [round][parity]，每个线程私有结构
} dis_barrier_t;

dis_barrier_t barriers[P];  // 按线程分配，确保不同 cache line

void dis_barrier_wait(int my_id, int parity) {
    for (int k = 0; k < LOGP; k++) {
        int partner = (my_id + (1 << k)) % P;
        // 通知 partner 我已到达本轮
        barriers[partner].flags[k][parity] = true;
        // 等待 partner 的通知
        while (barriers[my_id].flags[k][parity] == false) {
            cpu_relax();
        }
    }
}
```

- **流量分析**：每轮每个线程恰好写 1 次、读 1 次，总流量 O(P log P)。
- **关键优势**：每个线程只在自己的 `flags` 数组上自旋，**绝对不产生远程自旋**。`barriers` 数组应保证每个线程的元素位于独立的 cache line。
- **关键路径**：log₂ P 轮，但由于每轮是并行两两同步，实际 wall-clock 延迟 ≈ log₂ P × (一次写 + 一次读)。

### 3. MCS Tree Barrier（4-ary 到达树 + 中央唤醒）

```c
typedef struct {
    int count;           // 到达子节点计数
    bool sense;          // 本地 sense 标志
} tree_node_t;

tree_node_t nodes[P];     // 静态分配，每个线程一个节点
bool global_sense = false;

void mcs_tree_barrier_wait(int my_id, int n) {
    bool local_sense = !global_sense;
    
    // 到达阶段：向上计数
    int parent = (my_id - 1) / 4;
    if (atomic_fetch_add(&nodes[my_id].count, 1) == 3) {
        // 我是最后一个到达的子节点，通知父节点
        if (my_id == 0) {
            // 根节点：所有线程已到达，翻转全局 sense
            global_sense = local_sense;
        } else {
            atomic_fetch_add(&nodes[parent].count, 1);
        }
    }
    
    // 等待阶段：根节点唤醒后全局 sense 翻转
    if (my_id == 0) return;  // 根节点无需等待
    while (global_sense != local_sense) {
        cpu_relax();
    }
    
    // 唤醒子节点（由父节点向下传播）
    for (int child = 4*my_id + 1; child <= 4*my_id + 4 && child < n; child++) {
        nodes[child].sense = local_sense;
    }
}
```

- **流量分析**：到达阶段 O(P) 总流量（每个内部节点一次 atomic add），唤醒阶段 O(P) 总流量（每个父节点写子节点 sense）。关键路径 O(log₄ P)。
- **适用场景**：缓存一致性广播系统，因为根节点翻转 `global_sense` 时，广播 invalidation 比逐层传播更快。

## 性能数据对比

| Barrier 类型 | 关键路径 | 总流量 | 是否需要原子操作 | 是否本地自旋 | 空间复杂度 | 适用场景 |
|---|---|---|---|---|---|---|
| Centralized (Sense-Reversal) | O(1) | O(P) ~ O(P²) | Fetch&Add | 否（竞争同一点） | O(1) | 小 P，广播缓存一致性 |
| Software Combining Tree | O(log P) | O(P) | Fetch&Add | 否（动态分配） | O(P) | 中等 P，缓存一致性 |
| Dissemination | O(log P) | O(P log P) | 仅 Load/Store | **是** | O(P log P) | 无缓存一致性 / 高并发网络 |
| Tournament | O(log P) | O(P) | 无 | 部分 | O(P) | 无高级原子指令 |
| MCS Tree (4-ary + Central) | O(log P) | O(P) | Fetch&Add | 是 | O(P) | 广播缓存一致性，大 P |

> **注**："总流量"在缓存一致性机器上指 cache line invalidation 数量；在非一致性机器上指网络消息数。

## 相关链接

- [Mellor-Crummey & Scott 1991 原始论文](https://www.cs.rochester.edu/u/scott/papers/1991_TOCS_synch.pdf)
- [CMU 15-740 Synchronization 讲义](https://www.cs.cmu.edu/afs/cs/academic/class/15740-f98/public/lectures/lect20.pdf)
- [Rochester Barrier Methods 讲义](https://www.cs.rochester.edu/u/sandhya/csc458/seminars/jb_Barrier_Methods.pdf)
- [Linux futex 手册](https://man7.org/linux/man-pages/man2/futex.2.html)

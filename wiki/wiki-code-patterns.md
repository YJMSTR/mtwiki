---
id: "wiki-code-patterns"
title: "可复用的代码模式"
description: "从多线程RTL仿真器相关项目中提取的6个可直接复用的C++代码模式：per-thread accumulator、SPSC队列、原子屏障、NUMA初始化、work-stealing deque、线程本地事件池"
tags: ["code-patterns", "cpp", "lock-free", "atomic", "thread-local", "work-stealing"]
keywords: ["per-thread accumulator", "SPSC queue", "lock-free", "atomic fence", "NUMA first-touch", "work-stealing deque", "thread-local event pool"]
related_sources:
  - "source-false-sharing"
  - "source-cache-locality"
  - "source-cpp-memory-model"
  - "source-numa-optimization"
  - "source-work-stealing"
  - "source-onetbb-scheduler"
  - "source-thread-local-storage"
  - "source-lock-free-cpp"
last_updated: "2026-07-01"
---

# 可复用的代码模式

本章从各个 source 中提取可直接嵌入 RTL 仿真器代码库的 C++ 模式。每个模式包含：**问题描述、解决方案、完整代码示例、适用场景、注意事项**。这些模式可以独立使用，也可以组合成更复杂的多线程调度框架。

---

## 模式1：Per-Thread Accumulator + 批量合并

**来源**: [source-false-sharing](source-false-sharing.md)、[source-cache-locality](source-cache-locality.md)

### 问题描述

多线程仿真需要统计全局指标（已处理事件数、门求值次数、仿真时间）。如果每个线程直接写全局 `std::atomic<uint64_t>`，跨核缓存行失效（false sharing）会让性能倒退 3~10 倍。

### 解决方案

每个线程维护**缓存行对齐的本地计数器**，按批次（时间片或事件数阈值）合并到全局。RTL 仿真的事件驱动特性使得"批量合并"对精度几乎无影响，但彻底消除跨核缓存流量。

### 代码示例

```cpp
#include <atomic>
#include <vector>
#include <mutex>
#include <new>

struct alignas(std::hardware_destructive_interference_size) ThreadLocalCounter {
    uint64_t events = 0;
    uint64_t gates_evaluated = 0;
    uint64_t cycles = 0;
    // 剩余空间由 alignas 自动填充到缓存行大小
};

class BatchAccumulator {
    std::vector<ThreadLocalCounter> locals_;
    ThreadLocalCounter global_;
    std::mutex global_mutex_;
    const size_t flush_threshold_;  // 每处理 N 个事件触发一次合并

public:
    explicit BatchAccumulator(size_t num_threads, size_t threshold = 10000)
        : locals_(num_threads), flush_threshold_(threshold) {}

    // 线程安全：每个线程只写自己的 locals_[tid]
    void record(size_t tid, uint64_t events, uint64_t gates) {
        locals_[tid].events += events;
        locals_[tid].gates_evaluated += gates;
        locals_[tid].cycles += 1;

        if (locals_[tid].events >= flush_threshold_) {
            flush(tid);
        }
    }

    // 批量合并：将本地计数器汇总到全局
    void flush(size_t tid) {
        ThreadLocalCounter local_copy = locals_[tid];
        locals_[tid].events = 0;
        locals_[tid].gates_evaluated = 0;
        locals_[tid].cycles = 0;

        std::lock_guard<std::mutex> lock(global_mutex_);
        global_.events += local_copy.events;
        global_.gates_evaluated += local_copy.gates_evaluated;
        global_.cycles += local_copy.cycles;
    }

    // 仿真结束时，强制合并所有线程数据
    ThreadLocalCounter finalize() {
        for (size_t tid = 0; tid < locals_.size(); ++tid) {
            flush(tid);
        }
        std::lock_guard<std::mutex> lock(global_mutex_);
        return global_;
    }
};

// 使用示例
void simulate_partition(int tid, BatchAccumulator& acc) {
    for (const Event& e : local_events) {
        evaluate_gate(e);
        acc.record(tid, 1, 1);  // 1 事件, 1 门
    }
}
```

### 适用场景
- 全局统计、性能计数器、仿真进度汇报
- 任何"多线程写、偶尔读汇总"的场景

### 注意事项
- `flush_threshold` 需要调优：太小则锁竞争上升，太大则全局数据延迟高
- 如果不需要实时全局视图，可以在仿真结束后再一次性合并，完全避免锁
- 确保 `ThreadLocalCounter` 的 `alignas` 不小于目标平台缓存行（通常 64 字节）

---

## 模式2：SPSC Lock-Free Event Queue

**来源**: [source-lock-free-cpp](source-lock-free-cpp.md)

### 问题描述

RTL 仿真中，线程 A 处理门后产生的输出事件需要传递给线程 B（目标门在 B 的分区）。如果每次传递都用 `std::mutex` + `std::queue`，延迟约 **80~200 ns**（竞争时进入内核态）。SPSC（Single Producer Single Consumer）无锁队列用原子操作替代锁，延迟降至 **~15~30 ns**。

### 解决方案

预分配环形缓冲区 + 原子头/尾指针。生产者（source 线程）在尾部写，消费者（target 线程）在头部读。`alignas(64)` 头/尾指针避免 false sharing。

### 代码示例

```cpp
#include <atomic>
#include <vector>
#include <optional>
#include <new>
#include <cassert>

template <typename T, size_t Capacity>
class SPSCQueue {
    static_assert((Capacity & (Capacity - 1)) == 0, "Capacity must be power of 2");

    alignas(64) std::atomic<size_t> head_{0};  // 消费者读位置
    alignas(64) std::atomic<size_t> tail_{0};  // 生产者写位置
    std::vector<T> buffer_;

    static constexpr size_t mask = Capacity - 1;

public:
    SPSCQueue() : buffer_(Capacity) {}

    // Producer only: 入队
    bool push(const T& item) {
        size_t t = tail_.load(std::memory_order_relaxed);
        size_t next_t = (t + 1) & mask;

        // 队列满：head 紧跟 tail
        if (next_t == head_.load(std::memory_order_acquire)) {
            return false;  // 队列满，需外部处理（如扩容或阻塞）
        }

        buffer_[t] = item;
        tail_.store(next_t, std::memory_order_release);
        return true;
    }

    // Consumer only: 出队
    std::optional<T> pop() {
        size_t h = head_.load(std::memory_order_relaxed);
        if (h == tail_.load(std::memory_order_acquire)) {
            return std::nullopt;  // 队列空
        }

        T item = std::move(buffer_[h]);
        head_.store((h + 1) & mask, std::memory_order_release);
        return item;
    }

    // 批量出队（减少原子操作次数）
    size_t pop_batch(T* out, size_t max_items) {
        size_t h = head_.load(std::memory_order_relaxed);
        size_t t = tail_.load(std::memory_order_acquire);
        size_t available = (t - h) & mask;  // 注意： Capacity 是 2 的幂时成立
        size_t count = std::min(available, max_items);

        for (size_t i = 0; i < count; ++i) {
            out[i] = std::move(buffer_[(h + i) & mask]);
        }
        head_.store((h + count) & mask, std::memory_order_release);
        return count;
    }

    bool empty() const {
        return head_.load(std::memory_order_acquire) ==
               tail_.load(std::memory_order_acquire);
    }
};

// 使用示例：线程间事件传递
struct Event {
    uint32_t target_gate;
    uint64_t new_value;
    uint64_t timestamp;
};

// 每个 (source, target) 对预分配一个 SPSC 队列
SPSCQueue<Event, 4096> inter_thread_queues[8][8];  // 8 线程互相通信

void produce_event(int source_tid, int target_tid, const Event& e) {
    while (!inter_thread_queues[source_tid][target_tid].push(e)) {
        // 队列满：消费者太慢，可降级为直接处理或扩容
        _mm_pause();
    }
}

void consume_events(int my_tid, int from_tid) {
    Event batch[64];
    size_t n = inter_thread_queues[from_tid][my_tid].pop_batch(batch, 64);
    for (size_t i = 0; i < n; ++i) {
        apply_event(batch[i]);
    }
}
```

### 适用场景
- 固定生产者-消费者对的线程间通信
- 事件驱动仿真中，每个分区向其他分区发送事件
- 每周期一次的批量同步（非逐事件同步）

### 注意事项
- **Capacity 必须是 2 的幂**，否则掩码计算失效
- 生产者只能有一个线程调用 `push`，消费者只能有一个线程调用 `pop`
- 如果多对一通信，需要为每个源分配独立队列（空间换时间）
- 队列满时要有 fallback（如直接处理、阻塞、或分配新队列）

---

## 模式3：Relaxed Atomic Barrier + Fence

**来源**: [source-cpp-memory-model](source-cpp-memory-model.md)

### 问题描述

多线程仿真中需要同步"一批数据更新完成"的信号（如一个分区完成当前周期，所有门状态已写入共享数组）。如果每个门状态都用 `std::atomic` 写，性能崩溃。需要一种机制：用普通写更新数据，用单个原子/ fence 保证可见性。

### 解决方案

使用 `std::atomic_thread_fence` + `memory_order_release/acquire` 配对。生产者侧：普通写数据 → `release fence` → 原子标志置位。消费者侧：读取原子标志 → `acquire fence` → 安全读取数据。

### 代码示例

```cpp
#include <atomic>
#include <vector>
#include <cstdint>

// 场景：线程 A 每周期更新一批门状态，线程 B 需要读取这批状态
class BatchStateSync {
    std::vector<uint64_t> shared_state_;  // 普通数组，非原子
    std::atomic<uint64_t> version_{0};    // 同步标志

public:
    explicit BatchStateSync(size_t num_gates) : shared_state_(num_gates) {}

    // Producer (线程 A): 写入状态，然后 fence + 版本号更新
    void publish_state(const std::vector<uint64_t>& local_state) {
        assert(local_state.size() == shared_state_.size());

        // 1. 普通写：无原子开销，可批量提交
        for (size_t i = 0; i < shared_state_.size(); ++i) {
            shared_state_[i] = local_state[i];
        }

        // 2. Release fence: 保证 shared_state_ 的写在 version 更新之前可见
        std::atomic_thread_fence(std::memory_order_release);

        // 3. Relaxed 版本号递增：仅作为信号，不携带顺序语义
        version_.store(version_.load(std::memory_order_relaxed) + 1,
                       std::memory_order_relaxed);
    }

    // Consumer (线程 B): 检查版本号，然后 fence，再读取状态
    bool try_read_state(uint64_t expected_version, std::vector<uint64_t>& out) {
        uint64_t v = version_.load(std::memory_order_relaxed);
        if (v <= expected_version) {
            return false;  // 还没有新数据
        }

        // Acquire fence: 保证 version 读之后的 shared_state_ 读能看到 publish 时的写
        std::atomic_thread_fence(std::memory_order_acquire);

        out = shared_state_;  // 安全读取
        return true;
    }
};

// 更轻量的变体：直接用 atomic 的 release/acquire 语义，无需显式 fence
class LightweightSync {
    std::vector<uint64_t> data_;
    alignas(64) std::atomic<bool> ready_{false};

public:
    void publish(const std::vector<uint64_t>& new_data) {
        data_ = new_data;  // 普通写
        ready_.store(true, std::memory_order_release);  // release: data_ 写必须先完成
    }

    bool consume(std::vector<uint64_t>& out) {
        if (!ready_.load(std::memory_order_acquire)) {
            return false;  // acquire: 保证看到 data_ 的最新值
        }
        out = std::move(data_);
        ready_.store(false, std::memory_order_release);
        return true;
    }
};
```

### 适用场景
- 每周期门状态快照同步
- 批量数据完成后通知其他线程
- 分区结果汇总到主线程

### 注意事项
- x86-64 上 `relaxed` 和 `acquire/release` 性能差异很小，但代码可移植到 ARM 时必须保留正确语义
- 不要对非原子变量产生 data race（两个线程同时读写，至少一个写）——这是 C++ 的未定义行为
- `fence` 比 `atomic` 数组轻量得多，但语义更微妙，需确保 release/acquire 配对正确

---

## 模式4：NUMA-Aware First-Touch Initialization

**来源**: [source-numa-optimization](source-numa-optimization.md)

### 问题描述

Linux 的 first-touch 策略将内存页分配到第一个访问它的线程所在的 NUMA 节点。如果主线程 `malloc` 整个电路状态后，多个 NUMA 节点的线程来访问，大部分内存访问变成远程访问（延迟 3~4x）。

### 解决方案

每个线程在初始化阶段 touch 自己分区的数据，确保内存分配到本地 NUMA 节点。配合 `numa_run_on_node` 或 `sched_setaffinity` 将线程绑定到目标节点。

### 代码示例

```cpp
#include <vector>
#include <thread>
#include <sched.h>
#include <pthread.h>

#ifdef HAS_NUMA
#include <numa.h>
#endif

class NumaAwareCircuit {
    std::vector<uint64_t> gate_values_;
    std::vector<uint32_t> input_edges_;
    size_t num_gates_;
    size_t num_threads_;

    static void pin_thread_to_cpu(int cpu_id) {
        cpu_set_t cpuset;
        CPU_ZERO(&cpuset);
        CPU_SET(cpu_id, &cpuset);
        pthread_setaffinity_np(pthread_self(), sizeof(cpuset), &cpuset);
    }

public:
    NumaAwareCircuit(size_t num_gates, size_t num_threads)
        : num_gates_(num_gates), num_threads_(num_threads) {}

    // 每个线程初始化自己的分区，first-touch 确保 NUMA 本地分配
    void parallel_initialize() {
        gate_values_.resize(num_gates_);
        input_edges_.resize(num_gates_ * 4);  // 假设平均 4 个输入

        std::vector<std::thread> workers;
        for (size_t tid = 0; tid < num_threads_; ++tid) {
            workers.emplace_back([this, tid]() {
                // 绑定到特定 CPU（简化版：tid 映射到 CPU）
                pin_thread_to_cpu(static_cast<int>(tid));

                // 计算本线程的分区范围
                size_t start = (num_gates_ * tid) / num_threads_;
                size_t end = (num_gates_ * (tid + 1)) / num_threads_;

                // First-touch：写入自己的分区，触发本地 NUMA 分配
                for (size_t g = start; g < end; ++g) {
                    gate_values_[g] = 0;  // 初始值
                }
                for (size_t e = start * 4; e < end * 4 && e < input_edges_.size(); ++e) {
                    input_edges_[e] = 0;
                }
            });
        }
        for (auto& t : workers) t.join();
    }

#ifdef HAS_NUMA
    // 更精确的 NUMA 绑定：使用 libnuma
    void numa_initialize(const std::vector<int>& numa_nodes) {
        gate_values_.resize(num_gates_);

        std::vector<std::thread> workers;
        for (size_t tid = 0; tid < num_threads_; ++tid) {
            int node = numa_nodes[tid % numa_nodes.size()];
            workers.emplace_back([this, tid, node]() {
                numa_run_on_node(node);
                numa_set_localalloc();

                size_t start = (num_gates_ * tid) / num_threads_;
                size_t end = (num_gates_ * (tid + 1)) / num_threads_;

                for (size_t g = start; g < end; ++g) {
                    gate_values_[g] = 0;
                }
            });
        }
        for (auto& t : workers) t.join();
    }
#endif
};

// 使用示例
int main() {
    NumaAwareCircuit circuit(1'000'000, 16);  // 100 万门，16 线程
    circuit.parallel_initialize();  // 每个线程 touch 自己的分区
    // 后续仿真中，线程访问自己分区的数据时，内存是 NUMA 本地的
}
```

### 适用场景
- 大规模电路状态数组的初始化（门值、边列表、延迟表）
- 只读 LUT（查找表）的交错分配（`numactl --interleave=all`）
- 多 NUMA 节点服务器上的仿真器启动流程

### 注意事项
- `first-touch` 只在初始化阶段生效，后续如果线程迁移到远程节点，访问仍然是远程的 → 必须配合 thread pinning
- 如果系统有 2 个 NUMA 节点、32 核心，而仿真只使用 8 线程，最佳策略是将 8 线程全部绑定到**同一个 NUMA 节点**，获得最大本地带宽
- `numa_run_on_node` 需要链接 `-lnuma`，运行时需要 `libnuma` 安装

---

## 模式5：Work-Stealing Task Deque

**来源**: [source-work-stealing](source-work-stealing.md)、[source-onetbb-scheduler](source-onetbb-scheduler.md)

### 问题描述

静态分区在 RTL 仿真中面临负载不均衡：时间步 100 可能只有 10% 的门活跃，时间步 101 有 90% 活跃。如果分区固定，某些线程在稀疏时间步几乎空闲。Work stealing 允许空闲线程从繁忙线程窃取未处理的任务。

### 解决方案

Chase-Lev 双端队列：owner 在尾部 LIFO push/pop，thief 在头部 FIFO steal。批量 steal（64~256 个任务）摊薄 CAS 开销。加入 NUMA 感知 victim 选择。

### 代码示例

```cpp
#include <atomic>
#include <vector>
#include <optional>
#include <memory>
#include <random>
#include <algorithm>
#include <new>

struct Task {
    uint32_t start_gate;
    uint32_t num_gates;
};

class WorkStealingDeque {
    static constexpr size_t INITIAL_CAPACITY = 1024;

    alignas(64) std::atomic<size_t> head_{0};
    alignas(64) std::atomic<size_t> tail_{0};
    std::vector<Task> buffer_{INITIAL_CAPACITY};
    mutable std::mutex resize_mutex_;  // 仅用于扩容

    void resize(size_t new_capacity) {
        std::lock_guard<std::mutex> lock(resize_mutex_);
        size_t h = head_.load(std::memory_order_relaxed);
        size_t t = tail_.load(std::memory_order_relaxed);
        std::vector<Task> new_buffer(new_capacity);
        for (size_t i = h; i < t; ++i) {
            new_buffer[i % new_capacity] = std::move(buffer_[i % buffer_.size()]);
        }
        buffer_ = std::move(new_buffer);
    }

public:
    // Owner: push to tail (LIFO)
    void push(Task t) {
        size_t t_idx = tail_.load(std::memory_order_relaxed);
        if (t_idx - head_.load(std::memory_order_relaxed) >= buffer_.size() - 1) {
            resize(buffer_.size() * 2);
        }
        buffer_[t_idx % buffer_.size()] = std::move(t);
        tail_.store(t_idx + 1, std::memory_order_release);
    }

    // Owner: pop from tail (LIFO)
    std::optional<Task> pop() {
        size_t t = tail_.load(std::memory_order_relaxed) - 1;
        tail_.store(t, std::memory_order_relaxed);
        std::atomic_thread_fence(std::memory_order_seq_cst);
        size_t h = head_.load(std::memory_order_relaxed);

        if (h <= t) {
            Task task = std::move(buffer_[t % buffer_.size()]);
            if (h == t) {
                // 最后一个元素，CAS 竞争 head
                if (!head_.compare_exchange_strong(h, h + 1,
                                                   std::memory_order_relaxed,
                                                   std::memory_order_relaxed)) {
                    tail_.store(t + 1, std::memory_order_relaxed);
                    return std::nullopt;
                }
                tail_.store(t + 1, std::memory_order_relaxed);
            }
            return task;
        }
        tail_.store(t + 1, std::memory_order_relaxed);
        return std::nullopt;
    }

    // Thief: steal from head (FIFO), batch
    std::vector<Task> steal_batch(size_t max_batch = 64) {
        size_t h = head_.load(std::memory_order_acquire);
        size_t t = tail_.load(std::memory_order_acquire);
        if (h >= t) return {};

        size_t available = t - h;
        size_t batch = std::min(available, max_batch);

        if (head_.compare_exchange_weak(h, h + batch,
                                         std::memory_order_acq_rel)) {
            std::vector<Task> result;
            result.reserve(batch);
            for (size_t i = 0; i < batch; ++i) {
                result.push_back(std::move(buffer_[(h + i) % buffer_.size()]));
            }
            return result;
        }
        return {};  // CAS 失败，其他 thief 抢先
    }
};

class NumaAwareWorkStealer {
    std::vector<WorkStealingDeque> deques_;
    size_t num_threads_;
    std::vector<int> thread_numa_nodes_;
    std::mt19937 rng_{std::random_device{}()};

public:
    NumaAwareWorkStealer(size_t num_threads, const std::vector<int>& numa_nodes)
        : num_threads_(num_threads), deques_(num_threads),
          thread_numa_nodes_(numa_nodes) {}

    void push_local(size_t tid, Task t) {
        deques_[tid].push(std::move(t));
    }

    std::optional<Task> pop_local(size_t tid) {
        return deques_[tid].pop();
    }

    // NUMA-aware steal: 优先同节点，再跨节点
    std::vector<Task> steal(size_t thief_tid) {
        int my_node = thread_numa_nodes_[thief_tid];

        // 第一阶段：同 NUMA 节点随机 steal
        std::vector<int> local_candidates;
        for (size_t i = 0; i < num_threads_; ++i) {
            if (i != thief_tid && thread_numa_nodes_[i] == my_node) {
                local_candidates.push_back(static_cast<int>(i));
            }
        }
        std::shuffle(local_candidates.begin(), local_candidates.end(), rng_);
        for (int victim : local_candidates) {
            auto batch = deques_[victim].steal_batch(64);
            if (!batch.empty()) return batch;
        }

        // 第二阶段：跨 NUMA 节点随机 steal（兜底）
        std::vector<int> remote_candidates;
        for (size_t i = 0; i < num_threads_; ++i) {
            if (i != thief_tid && thread_numa_nodes_[i] != my_node) {
                remote_candidates.push_back(static_cast<int>(i));
            }
        }
        std::shuffle(remote_candidates.begin(), remote_candidates.end(), rng_);
        for (int victim : remote_candidates) {
            auto batch = deques_[victim].steal_batch(64);
            if (!batch.empty()) return batch;
        }

        return {};
    }
};
```

### 适用场景
- 事件驱动仿真中，不同时间步的活跃门数量波动大
- 动态负载均衡，无需精确的静态分区
- 与静态分区混合：静态分区确定基础负载，work stealing 处理剩余不均衡

### 注意事项
- 批量 steal 至少 64 个任务，否则 CAS 开销超过收益
- 关键路径上的任务不应参与 steal（参考 `wiki-scheduling` 的关键路径感知）
- 扩容时的 `resize_mutex` 是热点，初始容量应设足够大（如 4096）以避免运行时扩容
- 在 RTL 仿真中，任务粒度应该是"一个逻辑锥"而非"单个门"

---

## 模式6：Thread-Local Event Pool

**来源**: [source-thread-local-storage](source-thread-local-storage.md)

### 问题描述

RTL 仿真的事件驱动模型需要频繁分配和释放事件对象（每个门翻转产生一个事件）。如果所有线程共享 `malloc` 的 arena，每次分配都会触发锁竞争，延迟从 **~5~10 ns**（无锁）升到 **~50~200 ns**（带锁）。

### 解决方案

每个线程维护一个 `thread_local` 事件池，事件分配和释放完全本地完成，无需原子操作。使用 `constinit` 确保编译期初始化，消除 TLS 动态构造开销。

### 代码示例

```cpp
#include <vector>
#include <new>

struct Event {
    uint32_t target_gate;
    uint64_t new_value;
    uint64_t timestamp;

    void reset() {
        target_gate = 0;
        new_value = 0;
        timestamp = 0;
    }
};

class ThreadLocalEventPool {
    // 编译期初始化，local-exec model，零开销
    static constinit thread_local ThreadLocalEventPool* instance_;

    alignas(64) std::vector<Event> pool_;
    size_t free_count_ = 0;
    size_t next_alloc_ = 0;

    static constexpr size_t BATCH_SIZE = 4096;

    ThreadLocalEventPool() {
        pool_.reserve(BATCH_SIZE * 4);
    }

public:
    static ThreadLocalEventPool* get() {
        if (!instance_) {
            instance_ = new ThreadLocalEventPool();
        }
        return instance_;
    }

    // 分配事件：从预分配池取，不调用 malloc
    Event* allocate() {
        if (next_alloc_ < pool_.size()) {
            return &pool_[next_alloc_++];
        }
        // 批量扩展，避免频繁分配
        size_t old_size = pool_.size();
        pool_.resize(old_size + BATCH_SIZE);
        next_alloc_ = old_size + 1;
        return &pool_[old_size];
    }

    // 释放事件：不归还 OS，标记为可复用
    void deallocate(Event* e) {
        e->reset();
        free_count_++;
        // 可选：将 e 加入 free_list 头部，实现 O(1) 复用
    }

    // 批量重置：一个时间步结束后，一次性重置整个池
    void reset_all() {
        next_alloc_ = 0;
        free_count_ = 0;
    }

    size_t allocated_count() const { return next_alloc_; }
    size_t free_count() const { return free_count_; }
};

constinit thread_local ThreadLocalEventPool* ThreadLocalEventPool::instance_ = nullptr;

// 使用示例：per-thread 输出事件缓冲区 + 批量提交
class ThreadLocalOutputBuffer {
    static constinit thread_local Event local_buffer_[256];
    static constinit thread_local size_t local_count_;

public:
    static void emit(const Event& e) {
        local_buffer_[local_count_] = e;
        local_count_++;
        if (local_count_ == 256) {
            flush();  // 批量提交到全局队列
        }
    }

    static void flush() {
        if (local_count_ == 0) return;
        // 将 local_buffer_[0..local_count_) 提交到目标线程的 SPSC 队列
        // 具体提交逻辑取决于通信拓扑
        // ...
        local_count_ = 0;
    }
};

constinit thread_local Event ThreadLocalOutputBuffer::local_buffer_[256];
constinit thread_local size_t ThreadLocalOutputBuffer::local_count_ = 0;

// 求值函数中使用 TLS 事件池
void evaluate_gate_with_pool(uint32_t gate_idx) {
    uint64_t new_val = compute_gate_output(gate_idx);
    if (new_val != gate_values[gate_idx]) {
        gate_values[gate_idx] = new_val;

        Event* e = ThreadLocalEventPool::get()->allocate();
        e->target_gate = gate_idx;
        e->new_value = new_val;
        e->timestamp = current_time;

        ThreadLocalOutputBuffer::emit(*e);
    }
}
```

### 适用场景
- 事件驱动仿真中，每个门翻转产生事件的动态分配
- 临时对象（输入缓冲区、输出列表、求值中间结果）的 per-thread 管理
- 替代 `malloc`/`new` 的高频小对象分配

### 注意事项
- `constinit` 要求 C++20，如果只能用 C++17，使用 `__thread`（GCC 扩展）替代 `thread_local` 以获得更快性能
- `thread_local` 指针本身没有构造函数开销，但指向的堆对象（`new ThreadLocalEventPool()`）在首次访问时分配，应在仿真预热阶段就触发 `get()`
- 如果 pool 的总大小可能超过 glibc 的静态 TLS 预留空间（~1MB），不要直接放大数据在 `thread_local` 段中，而是用指针指向堆分配
- TCMalloc/jemalloc 是更成熟的替代方案：直接链接 `-ltcmalloc` 或 `-ljemalloc`，即可获得 per-thread cache，无需手动实现池

---

## 模式7：Static upper-bound fast path for sparse serial fallback

**来源**: 稀疏 RTL 仿真器 codegen 通用模式。

### 问题描述

稀疏 RTL 仿真器常在每个 coarse region 入口做 runtime popcount：复制 active words、清零全局 flags、统计 active bit 数，再决定走 serial-inline fallback 还是并行 dispatch。若默认阈值远大于 region 的静态最大 active bits，这个 popcount 就是可由 codegen 静态证明为多余的热路径工作。

### 解决方案

在 codegen 阶段计算 region 的静态上界：

```cpp
int staticMaxBits = activeWordSpan * ACTIVE_WIDTH;
if (unlikely(inlineThreshold < staticMaxBits)) {
    int activeBits = 0;
    for (word : words) activeBits += popcount(word);
    if (activeBits <= inlineThreshold) serial_inline();
    else dispatch_parallel();
} else {
    // 静态保证 activeBits <= threshold，不需要 runtime popcount。
    serial_inline();
}
```

若 `serial_inline()` body 很大，通常不要为了少一次比较而复制 body。更稳妥的生成形态是保留单一 body，用静态上界给 `activeBits` 赋常量后继续走原有 gate。

### 适用场景
- region 的最大 active bits 可以在编译期给出保守上界。
- runtime threshold 通常高于该上界，但仍需要保留低 threshold 调试/调参路径。
- fallback body 很大，复制 body 会增加 I-cache 压力。

### 反模式
- 不要默认把 hot path 改成复制 serial-inline body 的 `if (likely(threshold >= staticMax)) { body } else { old_gate }`；少量 compare/assignment 的收益可能被代码体积和 I-cache 成本抵消。
- 不要仅凭直觉把简单整数 gate 改成额外 boolean gate；分支形态变化需要独立测量。
- 不要为了缩短大 OR guard 表达式而在 copy loop 中增加 per-word OR/store，除非稳定获益。
- 不要假设给已经稳定偏向的 threshold gate 加 `likely()` 一定更快；编译器和硬件分支预测可能已经足够好。

### 验证方法
- 生成代码 spot-check：确认低-threshold fallback 仍包含 popcount，默认 path 跳过 popcount。
- 小规模 correctness smoke：验证 sparse-evaluation 语义不变。
- profile-off A/B：固定 CPU mask、关闭诊断 profile，仅用真实 workload wall/host time 做性能结论。

---

## 模式组合建议

在实际 RTL 仿真器中，这些模式通常组合使用：

```
初始化/codegen阶段：
  ├── 模式4：NUMA-aware first-touch 初始化电路状态
  └── 模式7：为稀疏 serial fallback 生成 static upper-bound fast path

仿真阶段（每个时间步）：
  ├── 线程从本地 deque 取任务（模式5）
  ├── 求值门时，输出事件先写入 TLS 缓冲区（模式6）
  ├── 缓冲区满时，通过 SPSC 队列发送给目标线程（模式2）
  ├── 批量统计写入 per-thread accumulator（模式1）
  └── 时间步结束：fence + 版本号同步（模式3），批量合并统计（模式1）
```

---

## 参考来源

- [source-false-sharing](source-false-sharing.md) — False sharing 消除、alignas
- [source-cache-locality](source-cache-locality.md) — Hot/Cold Split、数据布局
- [source-cpp-memory-model](source-cpp-memory-model.md) — Atomic、Fence、内存序
- [source-numa-optimization](source-numa-optimization.md) — NUMA first-touch、thread pinning
- [source-work-stealing](source-work-stealing.md) — Chase-Lev deque、理论保证
- [source-onetbb-scheduler](source-onetbb-scheduler.md) — TBB 深度优先/广度优先、scheduler bypass
- [source-thread-local-storage](source-thread-local-storage.md) — TLS model、per-thread allocator
- [source-lock-free-cpp](source-lock-free-cpp.md) — SPSC 队列、CAS、ABA 问题

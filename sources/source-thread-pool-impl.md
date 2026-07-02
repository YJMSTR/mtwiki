---
title: "C++ 线程池实现汇编：Fork-Join、Work-Stealing 与轻量级任务队列"
description: "搜集具体的 C++ 线程池实现，包括 ForkUnion（零 mutex/CAS/alloc）、Chase-Lev deque work-stealing（dpuyda/scheduling）、BS::thread_pool 及传统 std::mutex 任务队列，附可直接复用的代码片段与性能数据。"
source_url: "https://github.com/ashvardanian/fork_union"
source_type: "github-repo"
author: "Barak Shoshany, ashvardanian, dpuyda, GeeksForGeeks"
date: "2024-2026"
tags: ["thread-pool", "C++", "fork-join", "work-stealing", "Chase-Lev", "header-only"]
keywords: ["std::thread pool", "task-based thread pool", "fork-join thread pool", "lightweight thread pool", "C++11 thread pool"]
capture_date: "2026-07-03"
---

# C++ 线程池实现汇编：Fork-Join、Work-Stealing 与轻量级任务队列

## 来源

- **ForkUnion**: https://github.com/ashvardanian/fork_union
- **dpuyda/scheduling**: https://github.com/dpuyda/scheduling（arxiv:2407.15805）
- **BS::thread_pool**: https://github.com/bshoshany/thread-pool
- **GeeksForGeeks Thread Pool**: https://www.geeksforgeeks.org/cpp/thread-pool-in-cpp/

---

## 摘要

绝大多数号称「线程池」的实现本质上是「任务队列」——`std::queue<std::function<void()>>` 加 `std::mutex` 保护，由 OS 调度器随机分配核心。这类方案在 Big Data 或 HPC 场景下存在高延迟、频繁内存分配、缓存伪共享等问题。本资料汇编了四种不同设计哲学的实现：

1. **ForkUnion**（零开销 Fork-Join）：C++17，无 mutex、无系统调用、无动态分配、无 CAS，支持 NUMA 绑核与静态/动态任务分片。
2. **dpuyda/scheduling**（Work-Stealing + 任务图）：C++20，基于 Chase-Lev lock-free deque，支持异步任务与 DAG 依赖执行。
3. **BS::thread_pool**（轻量 header-only）：C++17 单头文件，仅 247 行代码（不含注释），`submit()` 返回 `std::future`。
4. **经典 mutex+condition_variable** 实现：教学级基础模板，展示任务队列与线程生命周期管理。

---

## 关键要点

- **Fork-Join 模型** 适合 RTL 事件分区：父线程 fork 出若干子任务，join 等待全部完成。ForkUnion 的 `for_n` / `for_slices` / `for_n_dynamic` 三种 API 分别对应 OpenMP 的 `schedule(static)` / `schedule(dynamic)`。
- **Work-Stealing** 将任务队列下放到每个 worker 线程本地，其他线程在空闲时从队尾（bottom） steal，极大降低全局锁竞争。
- **Chase-Lev deque** 是工业界最常用的 lock-free work-stealing 队列，已被 Taskflow、Google Filament 等采用。核心实现仅依赖 `std::atomic` 的 `fetch_add` / `compare_exchange`。
- **线程池的核心开销** 不在线程创建，而在：a) 锁竞争；b) 动态内存分配；c) 任务分发时的 cache-line false sharing。ForkUnion 通过以下手段消除这三项：
  - 线程同步仅靠 3 个原子变量（`stop`, `fork_generation`, `threads_to_sync`）+ 1 个动态进度原子量；
  - 所有任务通过索引寻址，无需堆分配包装器；
  - 热路径变量按 128 字节对齐（`alignas`），避免伪共享。
- **BS::thread_pool** 证明了「简单够用」的哲学：单头文件、零依赖、自动 `std::future` 返回、支持 `parallelize_loop()`。

---

## 对 RTL 仿真器多线程化的启示

RTL 仿真器（如 Verilator、VCS）在 cycle-based 仿真中，可将组合逻辑分区为若干事件簇，每簇作为一个 fork-join 任务。ForkUnion 的设计哲学尤其契合：

- **无动态分配**：仿真周期内不允许堆分配，否则 GC 抖动会导致确定性丢失。ForkUnion 的纯索引模型完美满足。
- **NUMA 感知**：现代仿真服务器常为双路或四路 NUMA，将内存与线程绑定到同一节点可显著降低访存延迟。
- **静态 vs 动态调度**：对均匀组合逻辑（如大规模门阵列）使用 `for_n`（静态切片）；对非均匀负载（如含大量 memory 的 design）使用 `for_n_dynamic`（work-stealing）。
- **任务图依赖**：RTL 的 always 块与模块层级天然构成 DAG。可借鉴 dpuyda/scheduling 的 `Task.Succeed()` 机制，自动解析模块依赖并并行执行无依赖的 always 块。

---

## 原文摘录与代码片段

### 1. ForkUnion — 核心原子变量设计

> 整个线程池热路径上只有 3 个核心原子变量（`stop`, `fork_generation`, `threads_to_sync`），以及 1 个用于动态偷取的 `dynamic_progress`。无需 CAS，因为任务提交时所有 worker 都在睡眠，只有 fork 发起者修改状态，随后通过 `fork_generation` 增量唤醒 worker。

**使用示例（C++17）**:
```cpp
#include <fork_union.hpp>
namespace fu = ashvardanian::fork_union;

int main() {
    alignas(fu::default_alignment_k) fu::basic_pool_t pool;
    if (!pool.try_spawn(std::thread::hardware_concurrency())) {
        std::fprintf(stderr, "Failed to fork the threads\n");
        return EXIT_FAILURE;
    }

    // 静态调度：OpenMP #pragma omp parallel for schedule(static)
    pool.for_n(1000, [](std::size_t task_index) noexcept {
        // 处理 event cluster [task_index]
    });

    // 动态偷取：OpenMP #pragma omp parallel for schedule(dynamic, 1)
    pool.for_n_dynamic(3, [](std::size_t task_index) noexcept {
        // 非均匀负载任务
    });
    return EXIT_SUCCESS;
}
```

**性能数据（N-body 128 物体 × 1e6 迭代）**：

| 机器 | OpenMP (D) | OpenMP (S) | ForkUnion (D) | ForkUnion (S) |
|------|------------|------------|---------------|---------------|
| 16x Intel SPR | 18.9s | 12.4s | 16.8s | **8.7s** |
| 12x Apple M2 | 1m34.8s | 1m25.9s | 31.5s | **20.3s** |
| 96x Graviton 4 | 32.2s | 20.8s | 39.8s | **26.0s** |

> `D` = dynamic, `S` = static。ForkUnion 在 static 调度下超越 OpenMP，因其避免了 OMP 的运行时开销与内存分配。

**NUMA 分布式池示例**：
```cpp
fu::numa_topology_t numa_topology;
fu::linux_distributed_pool_t distributed_pool;
bool need_to_spawn = distributed_pool.threads_count() == 0;
if (need_to_spawn) {
    numa_topology.try_harvest();
    distributed_pool.try_spawn(numa_topology, sizeof(result_t));
}
auto slices = distributed_pool.for_slices(total_vectors,
    [&](fu::colocated_prong<> first, std::size_t count) noexcept {
        // 根据 first.colocation 选择 NUMA-local 内存分片
    });
slices.join();
```

### 2. dpuyda/scheduling — Chase-Lev Work-Stealing Deque + 任务图

**Chase-Lev deque 核心原理**：
- 每个 worker 线程拥有本地 deque；
- Owner 线程在 **bottom** 执行 `push` / `pop`；
- 偷取线程在 **top** 执行 `steal`；
- 仅使用 `std::atomic<size_t>` 的 `fetch_add` 与 `compare_exchange`，无显式锁。

> 与传统的基于线程 ID 映射到队列索引不同，本实现使用 **thread-local 变量** 定位当前线程对应的任务队列。这使得实现无法做成纯 header-only（需要 `.cpp` 中的 thread-local 定义），但在 C++20 modules 成熟后这一限制会消失。

**任务图（DAG）示例**：
```cpp
#include "scheduling/scheduling.hpp"
std::vector<scheduling::Task> tasks;

auto& get_a = tasks.emplace_back([&]{ a = 1; });
auto& get_b = tasks.emplace_back([&]{ b = 2; });
auto& sum_ab = tasks.emplace_back([&]{ sum_ab = a + b; });

get_sum_ab.Succeed(&get_a, &get_b);  // 依赖声明

scheduling::ThreadPool thread_pool;
thread_pool.Submit(tasks);  // 自动拓扑执行
```

**性能对比（Fibonacci 无缓存，wall time / CPU time）**：
- 在简单场景下，dpuyda/scheduling 的 CPU 性能与 Taskflow 相当。
- 由于实现极简（<1000 行代码），编译时间与二进制体积显著优于 Taskflow。

### 3. BS::thread_pool — 轻量级 Header-Only（C++17）

```cpp
#include "BS_thread_pool.hpp"
BS::thread_pool pool;  // 默认 hardware_concurrency 线程

// 提交任务并返回 future
auto future = pool.submit([]() {
    return 42;
});
int result = future.get();

// 并行化循环
auto loop_future = pool.parallelize_loop(0, 1000,
    [](int start, int end) {
        for (int i = start; i < end; ++i) { /* ... */ }
    });
loop_future.wait();
```

> BS::thread_pool_light.hpp 仅 **115 行代码**，适合嵌入到不允许重型依赖的仿真器代码库中。

### 4. 经典 C++11 mutex+condition_variable 线程池

```cpp
class ThreadPool {
public:
    ThreadPool(size_t num_threads = std::thread::hardware_concurrency()) {
        for (size_t i = 0; i < num_threads; ++i) {
            threads_.emplace_back([this] {
                while (true) {
                    std::function<void()> task;
                    {
                        std::unique_lock<std::mutex> lock(queue_mutex_);
                        cv_.wait(lock, [this] {
                            return !tasks_.empty() || stop_;
                        });
                        if (stop_ && tasks_.empty()) return;
                        task = std::move(tasks_.front());
                        tasks_.pop();
                    }
                    task();
                }
            });
        }
    }

    ~ThreadPool() {
        { std::unique_lock<std::mutex> lock(queue_mutex_); stop_ = true; }
        cv_.notify_all();
        for (auto& t : threads_) t.join();
    }

    void enqueue(std::function<void()> task) {
        { std::unique_lock<std::mutex> lock(queue_mutex_); tasks_.emplace(std::move(task)); }
        cv_.notify_one();
    }

private:
    std::vector<std::thread> threads_;
    std::queue<std::function<void()>> tasks_;
    std::mutex queue_mutex_;
    std::condition_variable cv_;
    bool stop_ = false;
};
```

> **缺陷**：全局锁导致高竞争；`std::function` 隐含类型擦除与堆分配；每个任务包装为 `std::function` 在细粒度任务（<1μs）下开销不可忽略。该实现仅作为教学基线，不适合高性能 RTL 仿真。

---

## 相关链接

- [ForkUnion GitHub](https://github.com/ashvardanian/fork_union)
- [dpuyda/scheduling GitHub](https://github.com/dpuyda/scheduling)
- [arxiv:2407.15805 — A simple and fast C++ thread pool implementation capable of running task graphs](https://arxiv.org/abs/2407.15805)
- [BS::thread_pool GitHub](https://github.com/bshoshany/thread-pool)
- [GeeksForGeeks — Thread Pool in C++](https://www.geeksforgeeks.org/cpp/thread-pool-in-cpp/)

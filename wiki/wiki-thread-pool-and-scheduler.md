---
title: "线程池与调度器实现代码库"
description: "Fork-Join/Work-Stealing线程池（ForkUnion/dpuyda/BS::thread_pool）、任务调度器（Max Liani/Molecular Matters/T_Threads）、C++20协程与Fiber（pal_tasks/fiber_context）的完整实现与RTL仿真器适配方案"
source_refs: ["source-thread-pool-impl", "source-task-scheduler", "source-fiber-scheduler"]
author: "Wiki写作_最终聚焦"
date: "2025-07-20"
tags: ["thread-pool", "task-scheduler", "work-stealing", "fork-join", "C++20-coroutine", "fiber", "RTL仿真器"]
---

# 线程池与调度器实现代码库

## 1. 线程池实现

### 1.1 ForkUnion（零mutex/CAS/alloc，NUMA感知）

**设计核心**：线程池热路径上只有3个核心原子变量（`stop`, `fork_generation`, `threads_to_sync`）+ 1个动态进度原子量。任务提交时所有worker都在睡眠，只有fork发起者修改状态，随后通过`fork_generation`增量唤醒worker。无需CAS，无需堆分配，热路径变量按128字节对齐避免false sharing。

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
        // 处理event cluster [task_index]
    });

    // 动态偷取：OpenMP #pragma omp parallel for schedule(dynamic, 1)
    pool.for_n_dynamic(3, [](std::size_t task_index) noexcept {
        // 非均匀负载任务
    });
    return EXIT_SUCCESS;
}
```

**性能数据（N-body 128物体 × 1e6迭代）**：

| 机器 | OpenMP (D) | OpenMP (S) | ForkUnion (D) | ForkUnion (S) |
|------|------------|------------|---------------|---------------|
| 16x Intel SPR | 18.9s | 12.4s | 16.8s | **8.7s** |
| 12x Apple M2 | 1m34.8s | 1m25.9s | 31.5s | **20.3s** |
| 96x Graviton 4 | 32.2s | 20.8s | 39.8s | **26.0s** |

> `D` = dynamic, `S` = static。ForkUnion在static调度下超越OpenMP，因其避免了OMP运行时开销与内存分配。

**NUMA分布式池示例**：
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
        // 根据first.colocation选择NUMA-local内存分片
    });
slices.join();
```

### 1.2 dpuyda/scheduling（Chase-Lev deque + 任务图）

**设计核心**：C++20实现，基于Chase-Lev lock-free deque，支持异步任务与DAG依赖执行。使用thread-local变量定位当前线程对应的任务队列。

```cpp
#include "scheduling/scheduling.hpp"

std::vector<scheduling::Task> tasks;

auto& get_a = tasks.emplace_back([&]{ a = 1; });
auto& get_b = tasks.emplace_back([&]{ b = 2; });
auto& sum_ab = tasks.emplace_back([&]{ sum_ab = a + b; });

get_sum_ab.Succeed(&get_a, &get_b);  // 依赖声明：sum_ab依赖get_a和get_b

scheduling::ThreadPool thread_pool;
thread_pool.Submit(tasks);  // 自动拓扑执行
```

**性能**：在简单场景下，dpuyda/scheduling的CPU性能与Taskflow相当，但实现极简（<1000行），编译时间与二进制体积显著优于Taskflow。

### 1.3 BS::thread_pool（247行header-only）

```cpp
#include "BS_thread_pool.hpp"
BS::thread_pool pool;  // 默认hardware_concurrency线程

// 提交任务并返回future
auto future = pool.submit([]() { return 42; });
int result = future.get();

// 并行化循环
auto loop_future = pool.parallelize_loop(0, 1000,
    [](int start, int end) {
        for (int i = start; i < end; ++i) { /* ... */ }
    });
loop_future.wait();
```

**特点**：`BS::thread_pool_light.hpp`仅**115行代码**，零依赖，自动`std::future`返回，支持`parallelize_loop()`。适合嵌入不允许重型依赖的仿真器代码库。

### 1.4 经典std::mutex基线（教学用）

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

**缺陷**：全局锁导致高竞争；`std::function`隐含类型擦除与堆分配；每个任务包装为`std::function`在细粒度任务（<1μs）下开销不可忽略。仅作为教学基线，不适合高性能RTL仿真。

### 1.5 线程池性能对比

| 实现 | 代码量 | 锁/CAS | 动态分配 | NUMA感知 | 任务图 | 适用场景 |
|------|--------|--------|----------|----------|--------|----------|
| ForkUnion | ~500行 | 无 | 无 | 是 | 否 | 极致性能、HPC |
| dpuyda/scheduling | ~1000行 | 无（lock-free） | 无 | 否 | 是 | DAG调度、中等规模 |
| BS::thread_pool | 115-247行 | 有（mutex） | 有（std::function） | 否 | 否 | 快速原型、轻量嵌入 |
| 经典mutex | ~50行 | 有（mutex） | 有（std::function） | 否 | 否 | 教学基线 |

---

## 2. 调度器设计

### 2.1 Max Liani调度器（48字节Task、无自旋、嵌套优先）

**核心设计原则**：
1. Parallelize a workload over a controllable number of threads.
2. Launch asynchronous tasks.
3. Transparent support for nested parallelism.
4. **No spinning.**
5. **No black boxes.**

**Task结构（48字节）**：
```cpp
struct Scheduler::Task {
    inline Task(int numUnits, void* data, TaskFn fn, TaskFn epilogue = nullptr)
        : data(data), fn(fn), epilogue(epilogue), parent(nullptr), numUnits(numUnits)
    {}

    void*      data;       // 任务数据（不透明指针）
    TaskFn       fn;       // 任务函数
    TaskFn epilogue;       // 可选收尾函数（归约等）
    Task*    parent;       // 嵌套并行时的父任务
    int    numUnits;       // 工作单元数

    std::atomic<int> completed = 0;    // 已完成单元数
    std::atomic<int> refcount = 0;     // 生命周期引用计数
    std::atomic<int> dependencies = 1; // 未完成子任务数

    bool valid() const { return numUnits != 0; }
};
```

**parallelize阻塞式并行 + 当前线程参与计算**：
```cpp
void parallelize(uint32_t numThreads, void* data, TaskFn fn, TaskFn epilogue = nullptr) {
    if (numThreads == k_all) numThreads = getNumThreads();
    if (numThreads == 0) return;

    int threadIndex = getOrAssignThreadIndex();
    bool front = getNestingLevel() > 0; // 嵌套任务推到队列前端
    constexpr int localRun = 1;
    TaskTracker result = async(numThreads, data, fn, epilogue, localRun, front);

    // 当前线程执行第一个工作单元，随后参与其他任务
    int chunkIndex = 0;
    runTask(result.task, chunkIndex, threadIndex);
    result.wait();  // 不是阻塞等待，而是进入调度器参与计算
}
```

> **关键点**：`result.wait()`不是阻塞等待，而是让调用线程**进入调度器参与计算**。这是避免嵌套并行死锁的核心机制。

**嵌套并行优先级**：
```cpp
bool front = getNestingLevel() > 0;  // 嵌套并行 -> 高优先级
if (front)
    work.push_front(task);  // 内层循环优先完成，降低峰值内存
else
    work.push_back(task);
```

**工作量估算**：
```cpp
template<int k_unitSize, int k_maxThreads = 1<<16>
inline size_t estimateThreads(size_t workloadSize, const Scheduler& scheduler) {
    size_t nChunks = (workloadSize + k_unitSize - 1) / k_unitSize;
    size_t numThreads = std::min<size_t>(nChunks,
        std::min<size_t>(k_maxThreads, scheduler.getNumThreads()));
    return numThreads;
}
```

### 2.2 Molecular Matters负载均衡演进

**最简单的全局队列调度器**：
```cpp
AddTaskToScheduler(task) {
    LockSynchronizationPrimitive();
    globalTaskQueue.Add(task);
    UnlockSynchronizationPrimitive();
}

while (threadShouldRun) {
    WaitUntilTaskIsAvailable();
    LockSynchronizationPrimitive();
    task = globalTaskQueue.GetAndRemove();
    UnlockSynchronizationPrimitive();
    Execute(task);
}
```

**全局队列的致命缺陷**：
- 每次push/pop都加锁，高竞争下锁开销成为瓶颈
- 任务只能串行提交
- 无负载均衡：即使任务工作量相同，也无法保证各线程同时完成
- 等待任务完成时，调用线程idle

**Work-Stealing的解决思路**：
- 每个worker维护**本地队列**
- 提交任务时先放入全局队列或某个worker的本地队列
- 当worker本地队列为空时，从其他worker的队列**偷取**任务
- 全局队列仅用于外部任务提交，worker本地操作无锁或仅轻量锁

### 2.3 T_Threads（本地队列+work-stealing+5级优先级+线程亲和性）

**特性矩阵**：

| 特性 | 说明 |
|------|------|
| Local Queues | 任务可绑定到特定线程，提升cache locality |
| Work-Stealing | 空闲线程从其他队列偷取任务 |
| Priority Queues | 5级优先级（0-4） |
| Epoch GC | 每500ms一轮epoch清理，避免运行期内存分配 |
| Forked Tasks | 临时从线程池剥离线程执行专用任务 |
| Periodic/Delayed | 支持周期性任务与延迟任务 |

```cpp
TaskScheduler& scheduler = TaskScheduler::instance();
scheduler.startPool(0); // 选择core 0运行时钟与堆管理线程

// 本地队列（round-robin负载均衡）
scheduler.submitLocal([](){ std::cout << "Local task\n"; });
scheduler.submitLocal(1, [](){ std::cout << "Pinned to core 1\n"; });

// 优先级队列（0-4，默认3）
scheduler.submitPQ(0, task);  // 最高优先级
scheduler.submitPQ(4, task);  // 最低优先级

// 从线程池fork出专用线程
scheduler.submitFork(coreID, task);
```

### 2.4 Lock-Free Priority-Aware Deque

```cpp
while not done:
    task = pop_local_highest_priority_task()
    if task != NULL:
        execute(task)
    else:
        victim = check_other_threads()
        task = steal_lowest_priority_task_from(victim)
        if task != NULL:
            execute(task)
        else:
            increment local_priority
            spin_wait()
```

**设计权衡**：
- 本地队列按优先级排序，owner线程始终取最高优先级
- 偷取线程取**最低优先级**，避免「把好任务都抢走」
- 使用`std::atomic` + `compare_exchange`替代锁

---

## 3. Fibers与协程

### 3.1 Ponies & Light pal_tasks（C++20无栈协程Job System）

```cpp
Scheduler* scheduler = Scheduler::create(3);
TaskList tasks;

tasks.add_task(
    [](int idx, Scheduler* s) -> Task {
        cout << "executing task" << idx << endl;
        co_await suspend_task();  // 挂起，让出CPU
        cout << "resuming task" << idx << endl;
        co_return;
    }(42, scheduler)
);

scheduler->wait_for_task_list(tasks);  // 阻塞直到全部完成
```

**核心机制**：
- `initial_suspend()`返回`std::suspend_always` → 任务创建后先挂起，由调度器决定何时`resume()`
- `co_await suspend_task()` → 将当前协程句柄推回`TaskList`队列尾部，让出CPU
- `final_suspend()`返回自定义`finalize_task` awaiter → 协程完成后原子递减工作计数器
- 主线程调用`wait_for_task_list()`时不空转，而是亲自从队列取任务执行

**suspend_task实现**：
```cpp
struct suspend_task {
    constexpr bool await_ready() noexcept { return false; }
    void await_suspend(std::coroutine_handle<TaskPromise> handle) noexcept {
        auto& promise = handle.promise();
        auto& task_list = promise.p_task_list;
        task_list->push_task(promise.get_return_object());  // 推回队列尾部
    }
    void await_resume() noexcept {}
};
```

**Eager Worker-Led Scheduling**：
```cpp
void suspend_task::await_suspend(...) noexcept {
    // 推回队列后，立即尝试取下一个任务执行
    coroutine_handle_t c = task_list->pop_task();
    if (c) { c.resume(); }
}
```

### 3.2 P0876R18 fiber_context（栈切换ABI）

**核心定位**：提供最低层栈切换API（`resume()` / `resume_with()`），作为构建栈式协程、green threads的基石。

**x86_64切换开销分析**：
> "The calling convention of SYSV ABI for x86_64 determines that general purpose registers `R12, R13, R14, R15, RBX` and `RBP` must be preserved by the sub-routine... In addition, the stack pointer and instruction pointer are preserved and exchanged too — thus, from the point of view of calling code, `resume()` behaves like an ordinary function call."

**性能承诺**：`resume()`只需保存/恢复6个通用寄存器 + RSP/RIP，行为等价于普通函数调用，CPU周期开销与函数调用同级（~10-20ns）。

### 3.3 Michael Eiler协程线程池

```cpp
struct task_promise {
    task get_return_object() noexcept {
        return task{ std::coroutine_handle<task_promise>::from_promise(*this) };
    }
    std::suspend_never initial_suspend() const noexcept { return {}; }
    std::suspend_never final_suspend() const noexcept { return {}; }
    void return_void() noexcept {}
};

// schedule() awaiter — 将协程入队线程池
auto schedule() {
    struct awaiter {
        threadpool* m_pool;
        constexpr bool await_ready() const noexcept { return false; }
        constexpr void await_resume() const noexcept {}
        void await_suspend(std::coroutine_handle<> coro) const noexcept {
            m_pool->enqueue_task(coro);
        }
    };
    return awaiter{this};
}

// Continuation链实现
struct task_promise {
    struct final_awaitable {
        bool await_ready() const noexcept { return false; }
        std::coroutine_handle<> await_suspend(std::coroutine_handle<task_promise> coro) noexcept {
            return coro.promise().m_continuation;  // 直接跳转到continuation
        }
        void await_resume() noexcept {}
    };
    auto final_suspend() const noexcept { return final_awaitable(); }
    void set_continuation(std::coroutine_handle<> c) noexcept { m_continuation = c; }
private:
    std::coroutine_handle<> m_continuation = std::noop_coroutine();
};

// sync_wait阻塞等待（C++20 atomic_flag wait/notify）
struct fire_once_event {
    void set() { m_flag.test_and_set(); m_flag.notify_all(); }
    void wait() { m_flag.wait(false); }
private:
    std::atomic_flag m_flag;
};

inline void sync_wait(task& t) {
    fire_once_event event;
    auto wait_task = [](task& t) -> sync_wait_task {
        co_await t;  // 注册本协程为t的continuation
    }(t);
    wait_task.run(event);
    event.wait();  // 阻塞直到continuation触发event.set()
}
```

### 3.4 Boost生态映射

| 库 | 类型 | 特点 |
|----|------|------|
| `boost::context` | 底层栈切换 | ≈ `fiber_context`，提供对称/非对称transfer |
| `boost::fiber` | 用户级线程 | 内置调度器，fiber之间可yield |
| `folly::fibers` | 异步框架 | 暴露scheduler并与事件循环（`EventBase`）集成 |
| `quantum` | reactor模式 | 支持流式futures、任务优先级、预分配内存池 |

---

## 4. 对多线程RTL仿真器的启示

### 启示1：ForkUnion的NUMA感知设计适合仿真器

现代仿真服务器常为双路或四路NUMA。ForkUnion的`linux_distributed_pool_t`可将内存与线程绑定到同一NUMA节点，显著降低访存延迟。RTL仿真中，某些模块的memory在NUMA节点A上，将负责该模块的worker绑定到NUMA A的核，可减少跨节点访存延迟。

### 启示2：无自旋策略避免CPU空转

Max Liani的「No Spinning」原则让线程在没有任务时**进入休眠**，由条件变量唤醒。这不仅节省CPU，还使性能监控更诚实、CPU Turbo Boost更有效。RTL仿真中，很多时间步事件数很少，worker线程大部分时间处于空闲状态，无自旋策略可显著降低功耗和热量。

### 启示3：C++20协程可替代状态机切换

RTL仿真器通常使用状态机管理always块的执行状态（如`ACTIVE` → `WAITING` → `ACTIVE`）。C++20协程的`co_await`可将这些状态机显式化，代码更易读：

```cpp
// 状态机版本（传统）
void always_block_fsm() {
    switch (state) {
        case ACTIVE: 
            eval_combinational_logic();
            if (posedge_clk) state = WAITING;
            break;
        case WAITING:
            if (posedge_clk) state = ACTIVE;
            break;
    }
}

// 协程版本（C++20）
Task always_block_coroutine() {
    while (true) {
        eval_combinational_logic();
        co_await posedge_clk();  // 挂起直到时钟上升沿
    }
}
```

---

## 5. 可操作建议

### 建议1：BS::thread_pool快速原型 → ForkUnion性能优化

```cpp
// 阶段1：快速原型（BS::thread_pool）
#include "BS_thread_pool.hpp"
BS::thread_pool pool;

void simulate_cycle_v1(const std::vector<MTask>& mtasks) {
    auto future = pool.parallelize_loop(0, mtasks.size(),
        [&](int start, int end) {
            for (int i = start; i < end; ++i) {
                mtasks[i].eval();
            }
        });
    future.wait();
}

// 阶段2：性能优化（ForkUnion）
#include <fork_union.hpp>
namespace fu = ashvardanian::fork_union;
fu::basic_pool_t pool;

void simulate_cycle_v2(const std::vector<MTask>& mtasks) {
    pool.for_n(mtasks.size(), [&](std::size_t i) noexcept {
        mtasks[i].eval();
    });
}
```

### 建议2：T_Threads优先级调度处理关键路径

```cpp
// 将组合逻辑（前向路径）设为高优先级，时序逻辑（后向路径）设为低优先级
class PriorityScheduler {
    TaskScheduler& scheduler_;
public:
    void schedule_combinational(std::function<void()> task) {
        scheduler_.submitPQ(0, task);  // 最高优先级：组合逻辑先执行
    }
    
    void schedule_sequential(std::function<void()> task) {
        scheduler_.submitPQ(2, task);  // 中等优先级：时序逻辑后执行
    }
    
    void schedule_testbench(std::function<void()> task) {
        scheduler_.submitPQ(4, task);  // 最低优先级：testbench最后执行
    }
};
```

### 建议3：fiber_context做轻量级任务切换（~10-20ns）

```cpp
// 将每个always块编译为独立fiber
class FiberBasedScheduler {
    std::vector<boost::context::fiber> fibers_;
    
public:
    void add_always_block(std::function<void()> always_fn) {
        fibers_.push_back(boost::context::fiber([always_fn](boost::context::fiber&& main) {
            always_fn();
            return std::move(main);  // 返回主fiber
        }));
    }
    
    void run_cycle() {
        for (auto& f : fibers_) {
            f = std::move(f).resume();  // 恢复fiber执行，~10-20ns
        }
    }
};
```

### 建议4：pal_tasks协程化事件调度

```cpp
// 将事件调度循环协程化
Task schedule_events(Scheduler* scheduler, EventQueue& queue) {
    while (!queue.empty()) {
        auto event = queue.pop();
        
        // 将事件处理包装为协程任务
        TaskList tasks;
        tasks.add_task([event](Scheduler* s) -> Task {
            event.target->eval();
            co_await suspend_task();  // 让出CPU，调度器执行下一个事件
            co_return;
        }(scheduler));
        
        scheduler->wait_for_task_list(tasks);  // 当前协程参与调度
    }
    co_return;
}
```

---

## 相关链接

- [ForkUnion GitHub](https://github.com/ashvardanian/fork_union)
- [dpuyda/scheduling GitHub](https://github.com/dpuyda/scheduling)
- [arxiv:2407.15805](https://arxiv.org/abs/2407.15805)
- [BS::thread_pool GitHub](https://github.com/bshoshany/thread-pool)
- [Anatomy of a task scheduler — Max Liani](https://maxliani.wordpress.com/2022/07/27/anatomy-of-a-task-scheduler/)
- [T_Threads GitHub](https://github.com/jay403894-bit/T_Threads)
- [Ponies & Light — C++20 Coroutines Job System](https://poniesandlight.co.uk/reflect/coroutines_job_system/)
- [P0876R18 — fiber_context](https://www.open-std.org/jtc1/sc22/wg21/docs/papers/2024/p0876r18.pdf)
- [Michael Eiler — Coroutine Thread-Pool](https://blog.eiler.eu/posts/20210512/)
- [Lewis Baker — cppcoro](https://github.com/lewissbaker/cppcoro)

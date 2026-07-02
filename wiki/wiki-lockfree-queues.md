---
title: "锁-free队列实现代码库"
description: "SPSC/MPMC无锁队列（moodycamel/boost/atomic_queue）、Work-Stealing双端队列（Taskflow/Chase-Lev/Async++）、Ring Buffer（LMAX Disruptor模式）的完整实现代码、性能数据与RTL仿真器适配方案"
source_refs: ["source-lockfree-queue-impl", "source-work-stealing-deque", "source-ring-buffer-sim"]
author: "Wiki写作_最终聚焦"
date: "2025-07-20"
tags: ["lock-free", "SPSC", "MPMC", "work-stealing", "ring-buffer", "disruptor", "Chase-Lev", "RTL仿真器"]
---

# 锁-free队列实现代码库

## 1. SPSC/MPMC无锁队列

### 1.1 moodycamel::ReaderWriterQueue（SPSC, wait-free）

**设计核心**：基于「queue-of-queues」——底层环形buffer（block），高层是block的循环链表。生产者只写tail，消费者只读front，双方通过atomic的front/tail索引单向推进。x86上`memory_order_acquire/release`屏障编译为nop，热点路径仅为普通load/store。

```cpp
// readerwriterqueue.h — 精简核心enqueue/dequeue路径
template<typename T, size_t MAX_BLOCK_SIZE = 512>
class ReaderWriterQueue {
    struct Block {
        std::atomic<size_t> front;      // 消费者读取位置
        size_t localTail;               // 消费者本地缓存
        char pad0[64 - sizeof(std::atomic<size_t>) - sizeof(size_t)];
        std::atomic<size_t> tail;       // 生产者写入位置
        size_t localFront;
        char pad1[64 - sizeof(std::atomic<size_t>) - sizeof(size_t)];
        std::atomic<Block*> next;
        char* data;                     // 元素存储区
        const size_t sizeMask;
    };

    std::atomic<Block*> frontBlock;   // 消费者当前block
    char pad[64 - sizeof(std::atomic<Block*>)];
    std::atomic<Block*> tailBlock;    // 生产者当前block
    size_t largestBlockSize;

public:
    // 生产者路径：仅操作tailBlock->tail
    bool try_enqueue(T const& element) {
        Block* tailBlock_ = tailBlock.load();
        size_t blockFront = tailBlock_->localFront;
        size_t blockTail  = tailBlock_->tail.load();
        size_t nextBlockTail = (blockTail + 1) & tailBlock_->sizeMask;

        if (nextBlockTail != blockFront ||
            nextBlockTail != (tailBlock_->localFront = tailBlock_->front.load())) {
            fence(memory_order_acquire);
            char* location = tailBlock_->data + blockTail * sizeof(T);
            new (location) T(element);               // placement new
            fence(memory_order_release);
            tailBlock_->tail = nextBlockTail;
            return true;
        }
        return false;  // 需要分配新block或回绕
    }

    // 消费者路径：仅操作frontBlock->front
    template<typename U>
    bool try_dequeue(U& result) {
        Block* frontBlock_ = frontBlock.load();
        size_t blockTail = frontBlock_->localTail;
        size_t blockFront = frontBlock_->front.load();

        if (blockFront != blockTail ||
            blockFront != (frontBlock_->localTail = frontBlock_->tail.load())) {
            fence(memory_order_acquire);
            auto element = reinterpret_cast<T*>(frontBlock_->data + blockFront * sizeof(T));
            result = std::move(*element);
            element->~T();
            blockFront = (blockFront + 1) & frontBlock_->sizeMask;
            fence(memory_order_release);
            frontBlock_->front = blockFront;
            return true;
        }
        return false;  // empty
    }
};
```

**性能特征**：

| 特性 | 值 |
|------|-----|
| 算法复杂度 | enqueue O(1), dequeue O(1) |
| 内存屏障 | x86上编译为nop |
| 动态扩容 | 支持（enqueue自动分配新block） |
| 预分配保证 | `try_enqueue`永不分配内存 |
| 线程模型 | 严格单生产者 + 单消费者 |

### 1.2 moodycamel::ConcurrentQueue（MPMC, lock-free）

**设计核心**：每个生产者拥有独立的「子队列」（sub-queue），由连续block构成。消费者轮询所有子队列直到找到非空者。enqueue仅需更新本生产者的tail索引；dequeue只需读取各生产者子队列的front。

```cpp
#include "concurrentqueue.h"

moodycamel::ConcurrentQueue<int> q;

// 基础用法（隐式生产者，有哈希查找开销）
q.enqueue(25);
int item;
bool found = q.try_dequeue(item);

// 高效用法：显式token（推荐用于固定生产者线程）
moodycamel::ProducerToken ptok(q);
moodycamel::ConsumerToken ctok(q);
q.enqueue(ptok, 17);
q.try_dequeue(ctok, item);

// Bulk操作：仿真器一个时间步批量拉取事件
int items[] = {1, 2, 3, 4, 5};
q.enqueue_bulk(ptok, items, 5);

int results[5];
size_t count = q.try_dequeue_bulk(ctok, results, 5);
// count为实际出队数量，可能小于5若队列元素不足
```

**预分配公式**（`try_enqueue`永不分配）：
```cpp
// 若需保证N个元素 + MAX_NUM_PRODUCERS个显式生产者
size_t prealloc = (ceil(N / BLOCK_SIZE) + 1) * MAX_NUM_PRODUCERS * BLOCK_SIZE;
// BLOCK_SIZE默认32，可通过traits调整

struct MyTraits : public moodycamel::ConcurrentQueueDefaultTraits {
    static const size_t BLOCK_SIZE = 256;
};
moodycamel::ConcurrentQueue<int, MyTraits> q(prealloc);
```

### 1.3 boost::lockfree::spsc_queue

```cpp
#include <boost/lockfree/spsc_queue.hpp>

boost::lockfree::spsc_queue<int, boost::lockfree::capacity<1024>> queue;

// 非阻塞入队/出队
bool pushed = queue.push(42);
bool popped = queue.pop(value);

// 批量操作
boost::lockfree::spsc_queue<int>::size_type pushed_count = queue.push(items, items + 10);
```

**特点**：要求元素类型具备trivial assignment与trivial destructor；固定容量，不支持动态增长；基于环形数组+atomic读写索引，无需CAS。

### 1.4 性能基准（atomic_queue benchmark）

| 实现 | 模式 | 吞吐量 | 备注 |
|------|------|--------|------|
| `std::queue` (单线程) | 基准 | 102.40M ops/s | 理论上限 |
| `moodycamel::ReaderWriterQueue` | SPSC | 极高（接近单线程） | 无CAS，纯load/store |
| `boost::lockfree::spsc_queue` | SPSC | 极高 | 同样无CAS |
| `moodycamel::ConcurrentQueue` (bulk) | MPMC | 23.56M ops/s | 多线程竞争下仍高效 |
| `moodycamel::BlockingConcurrentQueue` | MPMC | 24.73M ops/s | 含轻量信号量阻塞 |
| `tbb::concurrent_queue` | MPMC | 11.54M ops/s | 基于锁，非lock-free |
| `boost::lockfree::queue` | MPMC | 3.44M ops/s | Michael-Scott算法 |

---

## 2. Work-Stealing双端队列

### 2.1 Taskflow UnboundedWSQ（C++17，自动扩容）

**设计核心**：基于Chase-Lev算法，PPoPP 2013论文实现。`Array`封装原子元素数组，支持modulo索引与resize。`_top`、`_bottom`、`_array`分别置于独立cache line，避免false sharing。

```cpp
template <typename T>
class UnboundedWSQ {
    struct Array {
        size_t C;                      // capacity
        size_t M;                      // mask = C-1
        std::atomic<T>* S;             // atomic元素数组

        explicit Array(size_t c) : C{c}, M{c-1}, S{new std::atomic<T>[C]} {}
        ~Array() { delete[] S; }

        size_t capacity() const noexcept { return C; }
        void push(int64_t i, T o) noexcept {
            S[i & M].store(o, std::memory_order_relaxed);
        }
        T pop(int64_t i) noexcept {
            return S[i & M].load(std::memory_order_relaxed);
        }
        Array* resize(int64_t b, int64_t t) {
            Array* ptr = new Array(2 * C);
            for (int64_t i = t; i != b; ++i) ptr->push(i, pop(i));
            return ptr;
        }
    };

    alignas(64) std::atomic<int64_t> _top;
    alignas(64) std::atomic<int64_t> _bottom;
    int64_t _cached_top{0};
    alignas(64) std::atomic<Array*> _array;
    std::vector<Array*> _garbage;

public:
    explicit UnboundedWSQ(int64_t logSize = 8) {
        _top.store(0, std::memory_order_relaxed);
        _bottom.store(0, std::memory_order_relaxed);
        _array.store(new Array{size_t{1} << logSize}, std::memory_order_relaxed);
        _garbage.reserve(32);
    }

    // Owner push: LIFO
    void push(T o) {
        int64_t b = _bottom.load(std::memory_order_relaxed);
        Array* a = _array.load(std::memory_order_relaxed);

        if (a->capacity() < static_cast<size_t>(b - _cached_top + 1)) [[unlikely]] {
            _cached_top = _top.load(std::memory_order_acquire);
            if (a->capacity() < static_cast<size_t>(b - _cached_top + 1)) [[unlikely]] {
                a = _resize_array(a, b, _cached_top);
            }
        }
        a->push(b, o);
        std::atomic_thread_fence(std::memory_order_release);
        _bottom.store(b + 1, std::memory_order_release);
    }

    // Owner pop: LIFO，与steal竞争最后一个元素
    std::optional<T> pop() {
        int64_t b = _bottom.load(std::memory_order_relaxed) - 1;
        Array* a = _array.load(std::memory_order_relaxed);
        _bottom.store(b, std::memory_order_relaxed);
        std::atomic_thread_fence(std::memory_order_seq_cst);
        int64_t t = _top.load(std::memory_order_relaxed);

        std::optional<T> item = std::nullopt;
        if (t <= b) {
            item = a->pop(b);
            if (t == b) {  // 最后一个元素，竞争窗口
                if (!_top.compare_exchange_strong(t, t + 1,
                        std::memory_order_seq_cst, std::memory_order_relaxed)) {
                    item = std::nullopt;  // thief赢了
                }
                _bottom.store(b + 1, std::memory_order_relaxed);
            }
        } else {
            _bottom.store(b + 1, std::memory_order_relaxed);  // 回滚
        }
        return item;
    }

    // Thief steal: FIFO，任意线程可调用
    std::optional<T> steal() {
        int64_t t = _top.load(std::memory_order_acquire);
        std::atomic_thread_fence(std::memory_order_seq_cst);
        int64_t b = _bottom.load(std::memory_order_acquire);

        std::optional<T> item = std::nullopt;
        if (t < b) {
            Array* a = _array.load(std::memory_order_consume);
            item = a->pop(t);  // 先读数据，再CAS top
            if (!_top.compare_exchange_strong(t, t + 1,
                    std::memory_order_seq_cst, std::memory_order_relaxed)) {
                return std::nullopt;  // 竞争失败
            }
        }
        return item;
    }

private:
    Array* _resize_array(Array* a, int64_t b, int64_t t) {
        Array* tmp = a->resize(b, t);
        _garbage.push_back(a);
        _array.store(tmp, std::memory_order_release);
        return tmp;
    }
};
```

**内存序分析表**：

| 操作 | 变量 | 内存序 | 原因 |
|------|------|--------|------|
| push | `_bottom` | `release` | 保证元素写入对thief可见后才更新索引 |
| pop | `_bottom` | `relaxed` + `seq_cst` fence | 先递减bottom关闭steal窗口，再用seq_cst同步 |
| pop | `_top` | `seq_cst` | 与steal竞争最后一个元素，需最强序 |
| steal | `_top` | `acquire` | 获取最新已steal位置 |
| steal | `_bottom` | `acquire` | 获取最新push位置 |
| steal | `_top` CAS | `seq_cst` | 确保全局唯一winner |

### 2.2 riften::Deque（C++20，Chase-Lev单头文件）

```cpp
#include "riften/deque.hpp"

riften::Deque<int> deque;

std::thread owner([&]() {
    for (int i = 0; i < 10000; ++i) deque.emplace(i);
    while (!deque.empty()) { auto item = deque.pop(); /* LIFO */ }
});

std::thread thief([&]() {
    while (!deque.empty()) { auto item = deque.steal(); /* FIFO */ }
});
```

**特点**：单头文件；要求类型`default_initializable` + `trivially_destructible` + `nothrow move`；使用`std::optional<T>`作为返回值；与Taskflow在x86上等价，但更贴近论文伪代码。

### 2.3 Async++ work_steal_queue（C++11，指针特化）

```cpp
class work_steal_queue {
    class circular_array {
        detail::aligned_array<void*, 64> items;
        std::unique_ptr<circular_array> previous;
    public:
        circular_array(std::size_t n) : items(n) {}
        void* get(std::size_t i) { return items[i & (size() - 1)]; }
        void  put(std::size_t i, void* x) { items[i & (size() - 1)] = x; }
        circular_array* grow(std::size_t top, std::size_t bottom) {
            circular_array* new_array = new circular_array(size() * 2);
            new_array->previous.reset(this);
            for (std::size_t i = top; i != bottom; ++i)
                new_array->put(i, get(i));
            return new_array;
        }
    };

    std::atomic<circular_array*> array;
    std::atomic<std::size_t> top, bottom;

public:
    void push(task_run_handle x) {
        std::size_t b = bottom.load(std::memory_order_relaxed);
        std::size_t t = top.load(std::memory_order_acquire);
        circular_array* a = array.load(std::memory_order_relaxed);
        if (to_signed(b - t) >= to_signed(a->size())) {
            a = a->grow(t, b);
            array.store(a, std::memory_order_release);
        }
        a->put(b, x.to_void_ptr());
        std::atomic_thread_fence(std::memory_order_release);
        bottom.store(b + 1, std::memory_order_relaxed);
    }

    task_run_handle steal() {
        while (true) {
            std::size_t t = top.load(std::memory_order_acquire);
            std::atomic_thread_fence(std::memory_order_seq_cst);
            std::size_t b = bottom.load(std::memory_order_acquire);
            if (to_signed(b - t) <= 0) return task_run_handle();
            void* x = array.load(std::memory_order_consume)->get(t);
            if (top.compare_exchange_weak(t, t + 1,
                    std::memory_order_seq_cst, std::memory_order_relaxed))
                return task_run_handle::from_void_ptr(x);
        }
    }
};
```

### 2.4 Work-Stealing实现对比

| 实现 | 扩容 | 元素类型限制 | 返回值 | 适用场景 |
|------|------|------------|--------|----------|
| Taskflow `UnboundedWSQ` | 自动 | 无（泛型） | `std::optional<T>` | 通用任务调度 |
| Taskflow `BoundedWSQ` | 固定 | 无 | 同上 | 实时/嵌入式，禁止堆分配 |
| riften::Deque | 自动 | trivially destructible + nothrow move | `std::optional<T>` | 现代C++20项目 |
| Async++ | 自动 | 指针句柄（`void*`） | `task_run_handle` | 已有Async++生态 |

---

## 3. Ring Buffer（LMAX Disruptor模式）

### 3.1 disruptor_cpp（C++20，header-only）

```cpp
#include "disruptor.hpp"
#include <thread>

struct Event {
    int value = 0;
};

class MyHandler : public disruptor::event_handler<Event> {
public:
    void on_event(Event& event, std::int64_t sequence, bool end_of_batch) override {
        // 处理事件
        if (end_of_batch) {
            // 批量提交
        }
    }
};

int main() {
    // RingBuffer<事件类型, 大小必须是2^n>
    disruptor::ring_buffer<Event, 1024,
        disruptor::busy_spin_wait_strategy,
        disruptor::producer_type::single> ring_buffer;

    auto barrier = ring_buffer.new_barrier();
    MyHandler handler;
    disruptor::batch_event_processor processor(ring_buffer, std::move(barrier), handler);

    std::thread consumer([&processor] { processor.run(); });

    // 生产者发布事件
    for (int i = 0; i < 1000; ++i) {
        std::int64_t seq = ring_buffer.next();
        ring_buffer[seq] = Event{i};  // 就地赋值
        ring_buffer.publish(seq);     // 发布后消费者可见
    }

    processor.halt();
    consumer.join();
}
```

**关键API**：

| API | 作用 |
|-----|------|
| `ring_buffer.next()` | 申请下一个可用序列号 |
| `ring_buffer[seq]` | 获取序列号对应槽位的引用，直接写入 |
| `ring_buffer.publish(seq)` | 发布序列号，消费者通过barrier感知 |
| `barrier.wait_for(seq)` | 消费者等待直到指定序列号可用 |

### 3.2 disruptor4cpp（C++11，多生产者）

```cpp
#include <disruptor4cpp/disruptor4cpp.h>

// 多生产者ring buffer
disruptor4cpp::ring_buffer<int, 1024,
    disruptor4cpp::busy_spin_wait_strategy,
    disruptor4cpp::producer_type::multi> ring_buffer;

auto barrier = ring_buffer.new_barrier();
int_handler handler;
disruptor4cpp::batch_event_processor<decltype(ring_buffer)> processor(
    ring_buffer, std::move(barrier), handler);

// 多生产者线程同时发布
std::thread producer([&]() {
    for (int i = 0; i < 1000; ++i) {
        int64_t seq = ring_buffer.next();
        ring_buffer[seq] = i;
        ring_buffer.publish(seq);
    }
});
```

### 3.3 bytemaster/disruptor（cursor分离）

```cpp
ring_buffer<int, 1024> buffer;
write_cursor wc;
read_cursor  rc;

// 生产者
auto seq = wc.claim(1);       // 申请1个槽位
buffer[seq] = 42;
wc.publish(seq);              // 发布

// 消费者
auto avail = rc.wait_for(wc); // 等待生产者游标
for (auto i = rc.begin(); i != avail; ++i) {
    process(buffer[i]);
}
rc.set(avail);                // 推进读游标
```

**特点**：cursor与数据存储分离，允许构建复杂数据流拓扑（如「读游标跟随多个上游写游标」实现diamond合并）。

### 3.4 C++17零拷贝RingBufferSlot

```cpp
// 预分配槽位 + 原地构造 + launder避免编译器误优化
template<typename T>
class RingBufferSlot {
    alignas(T) std::array<std::byte, sizeof(T)> storage_;
public:
    T& construct(const T& src) {
        return *new (std::launder(storage_.data())) T(src);
    }
    template<typename... Args>
    T& emplace(Args&&... args) {
        return *new (std::launder(storage_.data())) T(std::forward<Args>(args)...);
    }
    void destroy() { std::launder(storage_.data())->~T(); }
};

// 使用示例
template<typename T, size_t N>
class EventRingBuffer {
    static_assert((N & (N - 1)) == 0, "N must be power of 2");
    RingBufferSlot<T> slots_[N];
    std::atomic<std::int64_t> write_seq_{0};
    std::atomic<std::int64_t> read_seq_{0};
public:
    template<typename... Args>
    bool try_emplace(Args&&... args) {
        std::int64_t seq = write_seq_.load(std::memory_order_relaxed);
        if (seq - read_seq_.load(std::memory_order_acquire) >= N) return false;
        if (!write_seq_.compare_exchange_strong(seq, seq + 1,
                std::memory_order_acquire, std::memory_order_relaxed))
            return false;
        slots_[seq & (N - 1)].emplace(std::forward<Args>(args)...);
        write_seq_.store(seq + 1, std::memory_order_release);
        return true;
    }

    std::optional<T> try_pop() {
        std::int64_t seq = read_seq_.load(std::memory_order_relaxed);
        if (seq >= write_seq_.load(std::memory_order_acquire)) return std::nullopt;
        T& obj = *std::launder(reinterpret_cast<T*>(
            slots_[seq & (N - 1)].storage_.data()));
        T result = std::move(obj);
        slots_[seq & (N - 1)].destroy();
        read_seq_.store(seq + 1, std::memory_order_release);
        return result;
    }
};
```

### 3.5 LMAX性能数据

| 方案 | 10⁶事件耗时 | 相对提升 |
|------|------------|---------|
| Simple `std::queue` + 堆分配 | 884,871,405 ns | 基准 |
| Disruptor (ring buffer + sequence) | 543,171,556 ns | **38.6%** |

| 方案 | 平均延迟 | GC/分配压力 |
|------|----------|-------------|
| `std::queue` + 堆分配 | 850 ns | 高（频繁new/delete） |
| Disruptor + 零拷贝 | **42 ns** | 零（预分配复用） |

---

## 4. 对多线程RTL仿真器的启示

### 启示1：事件队列用SPSC per-thread

RTL仿真器中，每个时间步的事件注入通常由单线程（调度器）完成，每个worker线程消费自己的事件。这种「1个生产者→N个消费者」的拓扑，可用N个SPSC队列实现，每个worker线程一个`moodycamel::ReaderWriterQueue`，无CAS、无锁竞争。

### 启示2：work stealing用Chase-Lev deque

当worker线程本地队列为空时，从其他worker的队列steal事件。Chase-Lev deque的LIFO owner / FIFO thief特性符合仿真局部性：owner优先处理刚压入的子事件（缓存友好），steal从oldest任务开始（减少与owner冲突）。

### 启示3：批量处理降低单次enqueue开销

moodycamel::ConcurrentQueue的`enqueue_bulk`/`try_dequeue_bulk`可将一个时间步的所有事件批量处理，将N次同步操作amortize为1次。在RTL仿真中，一个时间步通常产生64-256个事件，bulk操作可将队列开销从事件主导变为可忽略。

---

## 5. 可操作建议

### 建议1：moodycamel::ReaderWriterQueue做per-thread事件buffer

```cpp
// 每个worker线程一个SPSC队列
class PerThreadEventQueue {
    static constexpr size_t MAX_WORKERS = 64;
    std::vector<std::unique_ptr<moodycamel::ReaderWriterQueue<RtlEvent>>> queues_;
    
public:
    PerThreadEventQueue(size_t num_workers) {
        for (size_t i = 0; i < num_workers; ++i) {
            queues_.push_back(std::make_unique<moodycamel::ReaderWriterQueue<RtlEvent>>(1024));
        }
    }
    
    // 调度器线程：将事件分发到对应worker的队列
    void enqueue(size_t worker_id, const RtlEvent& event) {
        queues_[worker_id]->try_enqueue(event);  // 无锁，O(1)
    }
    
    // Worker线程：消费自己的队列
    bool try_dequeue(size_t worker_id, RtlEvent& event) {
        return queues_[worker_id]->try_dequeue(event);  // 无锁，O(1)
    }
};
```

### 建议2：Taskflow WSQ做work stealing

```cpp
// 每个worker线程一个UnboundedWSQ
class WorkStealingScheduler {
    std::vector<std::unique_ptr<UnboundedWSQ<EventTask>>> local_queues_;
    size_t num_workers_;
    
public:
    WorkStealingScheduler(size_t num_workers) : num_workers_(num_workers) {
        for (size_t i = 0; i < num_workers; ++i) {
            local_queues_.push_back(std::make_unique<UnboundedWSQ<EventTask>>(8));
        }
    }
    
    // 提交到指定worker的本地队列
    void submit(size_t worker_id, EventTask task) {
        local_queues_[worker_id]->push(task);
    }
    
    // Worker尝试从自己的队列pop，失败则steal其他队列
    std::optional<EventTask> next_task(size_t my_id) {
        auto task = local_queues_[my_id]->pop();
        if (task) return task;
        
        // 随机steal其他worker
        for (size_t i = 0; i < num_workers_; ++i) {
            if (i == my_id) continue;
            task = local_queues_[i]->steal();
            if (task) return task;
        }
        return std::nullopt;
    }
};
```

### 建议3：disruptor做eval-update管道

```cpp
// RTL eval-update两阶段适配Disruptor消费者依赖拓扑
struct RtlEvent {
    enum Type { SIGNAL_UPDATE, PROCESS_WAKEUP, DELAYED_NOTIFY } type;
    uint64_t time;
    void* target;
    uint32_t value;
};

// 消费者依赖拓扑：Combinational -> Sequential -> PostUpdate -> TimeAdvance
// Combinational和Sequential可并行（无依赖）
// PostUpdate依赖前两者完成
// TimeAdvance依赖PostUpdate

using EventRing = disruptor::ring_buffer<RtlEvent, 65536,
    disruptor::sleeping_wait_strategy,  // 平衡延迟与CPU
    disruptor::producer_type::single>;   // 单时间步内单线程收集

// 在EventHandler中利用end_of_batch做批量提交
class BatchEvalHandler : public disruptor::event_handler<RtlEvent> {
    std::vector<RtlEvent> local_batch_;
public:
    void on_event(RtlEvent& event, std::int64_t seq, bool end_of_batch) override {
        local_batch_.push_back(event);
        if (end_of_batch || local_batch_.size() >= 64) {
            flush_batch(local_batch_);  // 批量写回仿真数据库
            local_batch_.clear();
        }
    }
};
```

### 建议4：批量enqueue（64-256事件）

```cpp
// 一个时间步内收集所有事件，然后bulk enqueue
void process_time_step() {
    std::vector<RtlEvent> events = collect_events();  // 收集当前时间步的所有事件
    
    // 按worker_id分组
    std::vector<std::vector<RtlEvent>> worker_events(num_workers_);
    for (auto& e : events) {
        size_t worker = assign_to_worker(e);
        worker_events[worker].push_back(e);
    }
    
    // bulk enqueue到各worker的SPSC队列
    for (size_t w = 0; w < num_workers_; ++w) {
        if (!worker_events[w].empty()) {
            producer_tokens_[w].enqueue_bulk(
                worker_events[w].data(), worker_events[w].size());
        }
    }
    
    // 等待所有worker完成（barrier）
    barrier_.wait();
}
```

---

## 相关链接

- [moodycamel/readerwriterqueue](https://github.com/cameron314/readerwriterqueue)
- [moodycamel/concurrentqueue](https://github.com/cameron314/concurrentqueue)
- [boost::lockfree](https://github.com/boostorg/lockfree)
- [max0x7ba/atomic_queue](https://github.com/max0x7ba/atomic_queue)
- [Taskflow wsq.hpp](https://github.com/taskflow/taskflow/blob/master/taskflow/core/wsq.hpp)
- [ConorWilliams/ConcurrentDeque](https://github.com/ConorWilliams/ConcurrentDeque)
- [Amanieu/asyncplusplus](https://github.com/Amanieu/asyncplusplus)
- [hangukquant/disruptor_cpp](https://github.com/hangukquant/disruptor_cpp)
- [alexleemanfui/disruptor4cpp](https://github.com/alexleemanfui/disruptor4cpp)
- [bytemaster/disruptor](https://github.com/bytemaster/disruptor)
- [LMAX Disruptor官方文档](https://lmax-exchange.github.io/disruptor/user-guide/index.html)

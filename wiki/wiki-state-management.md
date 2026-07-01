---
id: "wiki-state-management"
title: "状态管理与确定性重放"
description: "RTL仿真器状态快照、增量Checkpoint、状态压缩与确定性重放技术综述，聚焦多线程仿真器的一致性、可调试性与回滚成本"
tags: ["state-management", "checkpoint", "deterministic-replay", "state-compression", "copy-on-write", "multithreading", "rtl-sim"]
keywords: ["checkpoint", "snapshot", "save-restore", "deterministic replay", "record-replay", "state compression", "copy-on-write", "Time Warp", "rollback", "CXXRTL", "ModelSim", "Xcelium", "rr", "DeLorean", "ReEmu"]
related_sources:
  - "source-checkpoint-replay"
  - "source-state-compression"
  - "source-deterministic-replay"
last_updated: "2026-07-01"
---

# 状态管理与确定性重放

多线程RTL仿真器的调试噩梦不是性能，而是**不可复现的race**。当某次回归测试在16线程下偶发失败，而单线程复跑一切正常时，开发者面临一个根本问题：如果无法精确重放导致失败的线程交互顺序，调试就无从谈起。状态管理（Checkpoint/Snapshot）与确定性重放（Deterministic Replay）正是解决这一问题的核心技术组合。本章将从商用工具实现、学术前沿压缩算法、软件/硬件重放系统三个维度展开，并给出可直接落地的设计建议。

---

## 1. Checkpoint / 快照：保存与恢复仿真状态

### 1.1 核心使用场景

- **加速长仿真调试**：回归测试运行数小时甚至数天后才失败。以固定间隔（如每5分钟）保存Checkpoint，失败后从最近快照恢复并开启波形，避免从头重跑。
- **跳过固定初始化**：SoC运行Linux等系统的boot序列耗时。在初始化完成后保存Checkpoint，之后快速启动不同驱动测试，甚至RTL变更后仍可复用（前提：被测硬件在Checkpoint前保持复位状态）。
- **激进波形压缩**：不保存完整波形，而是保存周期性增量快照 + 仿真模型本身。波形查看器需要时即时重新仿真生成信号值。

### 1.2 商用工具实现

| 工具 | 命令/API | 保存内容 | 不恢复/限制 |
|------|---------|---------|------------|
| **ModelSim / QuestaSim** | `checkpoint <file>` / `restore <file>` 或 `vsim -restore <file>` | 仿真内核状态、WLF文件、list/wave信号列表、VHDL `$fopen` 文件指针位置、foreign architecture状态 | 宏状态、Tcl CLI变更、GUI窗口状态、toggle统计 |
| **Cadence Xcelium** | SystemVerilog `$save("SNAPSHOT")` + `xrun -r "SNAPSHOT"` | 完整仿真状态 | SDI/Verilog信息不支持保存；恢复后新FSDB与先前波形无法自动合并 |

**ModelSim细节**：
- 默认压缩Checkpoint文件；可通过 `set CheckpointCompressMode 0` 关闭。
- 热恢复（`restore`）在已运行vsim中恢复；冷恢复（`vsim -restore`）从命令行启动时恢复。

**Xcelium细节**：
- 恢复时可修改 `UVM_TESTNAME` 运行不同测试，跳过公共初始化序列。
- 注意：SDI/Verilog 信息不支持保存，恢复后的新 FSDB 与先前初始化阶段波形无法自动合并，需要手动处理。

### 1.3 开源实现：CXXRTL的Checkpoint机制

CXXRTL（Yosys 的 C++ 仿真后端）通过**设计自省（design introspection）**实现极简 Checkpoint：

- 统一访问接口：`debug_item` 类暴露 `value` / `wire` / `memory` / `alias` 四种状态对象。
- 保存时仅序列化 `wire`（含当前值和下一值）和 `memory` 的原始数据；`value` 可由恢复后的单步仿真重新推导。
- 状态以纯文本（ASCII）保存，含完整层级名和 `uint32_t` 数据，文件格式可优化空间约两个数量级。
- **局限性**：不支持异步时钟域精准采样、testbench 外部状态需另行处理、设计变更后无法恢复。

### 1.4 UVM Save & Restore（SnR）方法论

DVCon 论文提出基于 UVM Factory Override 的 SnR 流程：

- **Saving Simulation**：在公共 sequence（初始化）后调用 `do_save()` DPI-C 函数，生成包含 DUT 和 testbench 全部状态的快照文件。
- **Restoring Simulation**：通过 UVM Factory 的 type override 机制，在恢复后替换原有 sequence 为新的测试 sequence，无需重新执行公共初始化。
- **实现前提**：被覆盖和被替换的 sequence 必须注册到 UVM factory、且类型一致；保存点后必须有 sequence 可被执行/覆盖。

---

## 2. 状态压缩：从波形到仿真状态的极致压缩

### 2.1 清华大学 GLSVLSI 2023：402x压缩率

高振一等人的论文《Efficient and Effective Digital Waveform Compression for Large-scale Logic Simulation》提出了工业级波形压缩方案，核心思想可直接迁移到仿真状态Checkpoint：

**核心贡献**：
- **Detailed-Encoding**：根据 TRB（Transition Block）的特性选择编码方式。若 TRB 内所有信号值均为 0/1（clean TRB），则每位只需 1 bit；若含 X/Z（dirty TRB），则沿用 2-bit 编码。每个 TRB 增加 1 bit 标识 clean/dirty。
- **预测编码**：利用历史表（HT）进行值预测。单比特信号预测为翻转（flip），多比特信号仅预测最后一位翻转。预测值与原始值做 XOR 后产生大量连续 0，利于二级压缩。
- **改进的别名查找表**：当 VTRA 长度超过 256 时，按单比特/多比特位宽变化进行启发式分段（sub-VTRA），减少长 VTRA 对查找表命中率的负面影响，峰值内存降低约 20%。
- **辅助信息精细编码**：信号类型从 ASCII 字符串（3-9 字节）压缩为 5-bit 整数；位宽信息用变长编码。

**实验结果**（8 个工业用例）：
- 相对原始 VCD 的**平均压缩率 402x**，最高 **1561x**。
- 相比前序方法，压缩率提升最高 2.56x，平均 1.62x。
- 压缩/解压时间减少 10-12%，大用例压缩时间减少 20%。
- 峰值内存：小用例 < 1GB，大用例 < 3GB，平均降低 19-20%。

### 2.2 三级流水线并行压缩

整个压缩/解压过程被设计为三级流水线，天然适配多线程：

1. **编码阶段**：完成 TRB 编码和数据存储格式构建。
2. **二级压缩阶段**：对数据流进行通用无损压缩（如 Deflate、ZSTD）。
3. **写盘阶段**：将数据流写入磁盘。

**多线程启示**：每个线程可在局部完成预测编码后，将压缩块交给全局写盘线程，避免 I/O 阻塞仿真主循环。不同线程的局部状态块可并行压缩，再合并为全局 Checkpoint 文件。

### 2.3 工业紧凑格式：FSDB 与 FST

| 格式 | 特点 | 压缩策略 | 开源性 |
|------|------|---------|--------|
| **FSDB** | Verdi支持，VCS/Ncsim/ModelSim可通过PLI生成 | 仅保存信号变化信息，去除VCD冗余，类似Huffman编码 | 专有格式 |
| **FST** | GTKWave支持，Verilator原生输出选项 | 块级压缩和去重，支持动态读取部分波形 | 开源，API提供deduplication和压缩选项 |

### 2.4 零页/恒值信号跳过策略

gVisor 的 `--exclude-committed-zero-pages` 策略可直接迁移到 RTL 仿真：

- 大量寄存器在大部分仿真时间内保持恒定或为零。
- Checkpoint 时仅保存 dirty 状态（自上次快照以来发生变化的信号），可缩小快照体积数倍。
- VCDiag 的统计压缩进一步表明：某些场景下（覆盖率分析、故障分类），仅保存均值、标准差、分位数等统计指标即可，压缩后数据量降低 50-123x。

---

## 3. 确定性重放：让race可以被反复调试

### 3.1 Mozilla rr：软件级记录与重放

**核心原理**：
- 使用 `ptrace` 拦截所有系统调用，记录输入输出值；重放时由 rr 模拟系统调用，不转发到内核。
- 使用处理器性能计数器（PMU）记录异步事件（如中断、信号），重放时基于计数器值精确触发。
- 因为重放时无真实 I/O 和通信，执行是确定性的，内存分配地址、寄存器值、系统调用返回完全相同。

**关键特性**：
- 低开销：单线程为主的程序记录开销仅 1.2x 左右。
- **单核模拟**：rr 本质上模拟单核机器，并行程序会被调度到单核运行。这是设计上的固有特性，使得弱内存序相关 bug 无法复现。
- 支持高效的反向执行（reverse execution），配合 gdb 数据观察点实现"时间旅行调试"。

**对 RTL 的启示**：rr 的"记录事件而非记录每条指令"思想可迁移。多线程 RTL 仿真器不需要记录每个门级计算，只需记录导致非确定性的关键事件（调度顺序、外部输入、随机种子）。

### 3.2 DeLorean：硬件辅助的多线程确定性重放（ISCA 2008）

**核心创新**：
- 处理器以**原子块（chunk）**执行指令，类似事务内存或线程级推测（TLS）。系统只需记录这些块的全局提交顺序，而非每次共享内存访问的依赖。
- 相比记录单个共享内存依赖（FDR、RTR 等方案），**日志需求压缩到原来的 0.6%-7.5%**。

**三种执行模式**：
- **OrderOnly**：记录速度接近 Release Consistency 执行速度，重放速度约为 RC 的 82%；日志仅需 1.3 bits / 处理器 / kilo-instruction。
- **Stratified OrderOnly**：对日志按 Strata 设计重组，日志降至 RTR 的 7.5%，重放速度几乎不变。
- **PicoLog**：日志降至 0.05 bits / 处理器 / kilo-instruction（RTR 的 0.6%），估计 8 核 5GHz 机器一天日志仅约 20GB。

**对 RTL 的启示**：RTL 仿真器中的"事件步进"天然可视为原子块。若能记录各线程时间轮的推进顺序，而非每个信号赋值的交叉顺序，可大幅降低确定性重放的日志开销。

### 3.3 ReEmu：全系统仿真的可扩展确定性重放（PPoPP 2013）

**核心改进**：基于 CREW（Concurrent Read Exclusive Write）协议的优化
- **seqlock-like 设计**：避免频繁锁操作造成的严重竞争和饥饿。
- **最小化日志**：每个核心仅记录访问共享内存的局部信息（内存操作计数 + 版本号），依赖离线工具推导精确的共享内存依赖。
- **自动锁聚类**：将不冲突的内存对象聚类为 bulk，减少锁操作频率。

**重放算法**：
- 读操作：等待对象版本达到日志记录的版本，确保读到记录时的值。
- 写操作：等待之前所有写操作完成，并等待所有依赖读操作完成后，再执行写入。

**性能**：在 x86 多核平台仅引入 68.9% 性能开销，具有良好扩展性。

**对 RTL 的启示**：多线程 RTL 仿真器本质上也是全系统仿真（DUT + 调度器）。ReEmu 的 per-core 版本日志和 seqlock 设计可直接迁移：每个仿真线程维护局部信号更新版本，全局同步点验证版本一致性。

### 3.4 技术谱系对比

| 维度 | Mozilla rr | DeLorean | ReEmu | RTL 仿真的潜在方案 |
|------|------------|----------|-------|-------------------|
| 记录粒度 | 系统调用 + PMU 事件 | 原子块提交顺序 | 共享内存对象版本 | 时间轮/事件步顺序 |
| 日志开销 | 低（1.2x） | 极低（0.6%） | 中等（68.9%） | 待研究 |
| 并行支持 | 单核模拟 | 多核原生 | 多核可扩展 | 需设计调度协议 |
| 反向执行 | 支持（gdb） | 无 | 无 | 可由快照链实现 |
| 弱内存序 | 不支持 | 需额外处理 | 需精确版本 | 一般无时序竞争 |

---

## 4. 对多线程RTL仿真器的核心启示

### 4.1 确定性重放是多线程仿真的前提

没有确定性重放，多线程RTL仿真器中的偶发race就是不可调试的。这意味着：

1. **调度器必须是确定性的或可记录的**：如果事件调度顺序依赖线程竞争（如谁先抢到锁就先执行），那么相同的输入和种子可能产生不同的执行路径。要么设计一个固有确定性的调度器（如基于优先级和固定哈希的仲裁），要么记录导致非确定性的关键事件。
2. **时间模型必须精确到可重放**：多线程RTL仿真通常将时间推进到全局同步点（如时钟沿）。如果各线程在不同步的时间点读取共享信号值，必须记录这些跨线程访问的顺序。

### 4.2 多线程下Checkpoint必须保存所有线程状态

单线程仿真中，快照随时保存都自然一致。多线程并行时，必须在全局同步点（如时钟沿、调度屏障）冻结所有线程后保存，否则状态切面可能包含跨时钟域的时序竞争。

**关键要求**：
- 保存 DUT 状态 + 每个线程的调度器状态（时间轮、事件队列、待处理信号列表）。
- 保存 testbench 外部状态（scoreboard、sequencer 队列、文件指针位置）。
- 确保快照时刻所有线程已完成该时间步的全部计算，没有"飞行中"的更新。

### 4.3 Time Warp rollback 需要低成本状态保存

Time Warp 乐观并行离散事件仿真（PDES）允许线程超前执行，当检测到因果错误时回滚到之前状态。这要求：

- 状态保存频率足够高（通常每个事件处理后就保存），使得回滚距离短。
- 单次保存成本足够低，否则频繁保存会抵消并行收益。
- 支持**增量反执行（reverse computation）**：不仅保存状态，还要保存如何撤销状态变更的信息。

**结论**：没有高效的增量 Checkpoint，Time Warp 在RTL仿真中不可行。完整状态保存（GB级数据拷贝）每周期执行一次会让仿真器慢数个数量级。

---

## 5. 可操作的设计建议

### 5.1 建议一：用 Copy-on-Write 做增量 Checkpoint

核心思路：不每次保存完整状态，而是利用操作系统页机制，仅复制发生变化的内存页。这适合状态以连续内存块组织的仿真器（如 CXXRTL 的 `debug_item` 设计）。

**实现方案**：
1. 快照前将所有状态页标记为只读（`mprotect(..., PROT_READ)`）。
2. 仿真继续运行，任何写入会触发页错误（SIGSEGV）。
3. 在信号处理程序中复制该页到快照缓冲区，然后将原页恢复为可写。
4. 下次快照时，只需保存新增的 dirty 页，未变化的页与前次快照共享。

**C++ 伪代码示例**：

```cpp
#include <sys/mman.h>
#include <signal.h>
#include <vector>
#include <cstdint>

// --- 页面级 copy-on-write 增量 Checkpoint 引擎 ---

class COWCheckpointEngine {
    static constexpr size_t PAGE_SIZE = 4096;
    
    struct Snapshot {
        uint64_t sim_time;           // 仿真时刻
        std::vector<uint8_t> dirty_pages;  // 被修改的页内容
        std::vector<size_t> page_offsets;  // 对应页在状态区中的偏移
    };
    
    uint8_t* state_region;           // 仿真状态区（wire + memory）
    size_t state_size;               // 状态区总大小
    std::vector<Snapshot> snapshot_chain;  // 快照链，支持反向执行
    
    // 信号处理：捕获页错误，复制 dirty 页
    static void segv_handler(int sig, siginfo_t* info, void* ctx) {
        void* fault_addr = info->si_addr;
        auto* engine = static_cast<COWCheckpointEngine*>(
            // 实际实现中通过 TLS 或全局注册表获取当前引擎实例
            get_current_engine()
        );
        
        size_t offset = (uint8_t*)fault_addr - engine->state_region;
        offset = (offset / PAGE_SIZE) * PAGE_SIZE;  // 对齐到页边界
        
        // 复制该页到 pending dirty 列表（下次快照时保存）
        engine->pending_dirty.emplace_back(
            engine->state_region + offset,
            engine->state_region + offset + PAGE_SIZE
        );
        
        // 恢复写权限，让程序继续
        mprotect(engine->state_region + offset, PAGE_SIZE, PROT_READ | PROT_WRITE);
    }
    
    std::vector<std::vector<uint8_t>> pending_dirty;  // 待保存的 dirty 页
    
public:
    void init(void* region, size_t size) {
        state_region = static_cast<uint8_t*>(region);
        state_size = size;
        
        // 注册 SIGSEGV 处理程序
        struct sigaction sa{};
        sa.sa_flags = SA_SIGINFO;
        sa.sa_sigaction = segv_handler;
        sigaction(SIGSEGV, &sa, nullptr);
        
        // 初始状态：全部可写，不做 COW
    }
    
    void prepare_cow_epoch() {
        // 在下一个仿真周期前，将所有状态页标记为只读
        // 这会触发后续的写入触发页错误，从而记录 dirty 页
        mprotect(state_region, state_size, PROT_READ);
        pending_dirty.clear();
    }
    
    Snapshot take_snapshot(uint64_t sim_time) {
        Snapshot snap;
        snap.sim_time = sim_time;
        
        for (auto& page : pending_dirty) {
            snap.dirty_pages.insert(snap.dirty_pages.end(), page.begin(), page.end());
            snap.page_offsets.push_back(
                // 计算偏移
                // ...
            );
        }
        
        snapshot_chain.push_back(std::move(snap));
        return snap;
    }
    
    void restore_from_snapshot(const Snapshot& snap) {
        // 恢复 dirty 页
        for (size_t i = 0; i < snap.page_offsets.size(); ++i) {
            size_t off = snap.page_offsets[i];
            // 将 dirty 页内容复制回状态区
            // ...
        }
    }
    
    void rollback_to_time(uint64_t target_time) {
        // 从快照链中找到最近的前置快照
        auto it = std::find_if(snapshot_chain.rbegin(), snapshot_chain.rend(),
            [&](const Snapshot& s) { return s.sim_time <= target_time; });
        
        if (it != snapshot_chain.rend()) {
            restore_from_snapshot(*it);
            // 如果 target_time 在快照和当前之间，需要重新仿真到 target_time
        }
    }
};
```

**注意事项**：
- `mprotect` 的系统调用开销不可忽视，在频繁小写入场景下可能不如软件级 dirty 标记。
- 适合状态区较大（MB~GB级）、但每周期变化比例小（<10%）的场景，与RTL稀疏计算特性天然匹配。
- 需要处理 `mmap` 返回的页对齐要求，状态区起始地址必须页对齐。

### 5.2 建议二：用 Per-Thread Deterministic Log 替代全局锁

核心思路：每个线程维护一个本地事件日志，记录该线程执行的所有非确定性操作（调度决策、随机数生成、跨线程信号读取）。重放时按全局顺序重播这些日志，无需全局锁。

**设计要点**：
1. **线程局部日志（Thread-Local Log）**：每个线程有一个无锁的环形缓冲区，顺序写入事件记录。
2. **全局定序（Global Ordering）**：在全局同步点（如每时钟沿），各线程交换日志序列号，确定全局事件顺序。
3. **重放调度器（Replay Scheduler）**：重放时不是真正并行运行，而是按全局顺序单线程"重播"各线程的执行路径，确保完全一致。

**C++ 伪代码示例**：

```cpp
#include <vector>
#include <atomic>
#include <thread>
#include <cstdint>

// --- Per-Thread 确定性日志 ---

enum class EventType : uint8_t {
    SCHEDULE_DECISION,   // 调度器选择哪个敏感列表执行
    RANDOM_NUMBER,       // 随机数生成器的返回值
    CROSS_THREAD_READ,   // 读取其他线程产生的信号值
    EXTERNAL_INPUT,      // 来自 testbench 的输入
};

struct EventRecord {
    EventType type;
    uint64_t sim_time;      // 仿真时间
    uint32_t thread_id;     // 产生事件的线程
    uint64_t data;          // 事件相关数据（如随机数、信号ID）
    uint64_t seq;           // 线程局部序列号
};

class PerThreadDeterministicLog {
    static constexpr size_t LOG_BUFFER_SIZE = 65536;  // 64K 事件缓冲
    
    struct ThreadLog {
        alignas(64) std::atomic<uint64_t> write_idx{0};
        alignas(64) std::atomic<uint64_t> read_idx{0};
        EventRecord buffer[LOG_BUFFER_SIZE];
        
        bool try_push(const EventRecord& evt) {
            uint64_t idx = write_idx.load(std::memory_order_relaxed);
            uint64_t next = (idx + 1) % LOG_BUFFER_SIZE;
            if (next == read_idx.load(std::memory_order_acquire)) {
                return false;  // 缓冲区满，需要同步flush
            }
            buffer[idx] = evt;
            write_idx.store(next, std::memory_order_release);
            return true;
        }
    };
    
    std::vector<ThreadLog> thread_logs;  // per-thread 日志
    
public:
    void init(int n_threads) {
        thread_logs.resize(n_threads);
    }
    
    // 记录线程 i 的事件
    void log_event(int thread_id, EventType type, uint64_t sim_time, uint64_t data) {
        EventRecord evt{type, sim_time, (uint32_t)thread_id, data, 0};
        
        // 分配线程局部序列号
        static thread_local uint64_t local_seq = 0;
        evt.seq = local_seq++;
        
        while (!thread_logs[thread_id].try_push(evt)) {
            // 缓冲区满，触发全局同步 flush
            flush_all_threads();
        }
    }
    
    // 全局同步点：合并所有线程日志，生成全局顺序
    std::vector<EventRecord> merge_global_order(uint64_t up_to_time) {
        std::vector<EventRecord> global_log;
        
        for (auto& tl : thread_logs) {
            uint64_t rd = tl.read_idx.load(std::memory_order_relaxed);
            uint64_t wr = tl.write_idx.load(std::memory_order_acquire);
            
            while (rd != wr) {
                EventRecord& evt = tl.buffer[rd];
                if (evt.sim_time <= up_to_time) {
                    global_log.push_back(evt);
                }
                rd = (rd + 1) % LOG_BUFFER_SIZE;
            }
            tl.read_idx.store(rd, std::memory_order_release);
        }
        
        // 按 (sim_time, thread_id, seq) 全局排序
        std::sort(global_log.begin(), global_log.end(),
            [](const EventRecord& a, const EventRecord& b) {
                if (a.sim_time != b.sim_time) return a.sim_time < b.sim_time;
                if (a.thread_id != b.thread_id) return a.thread_id < b.thread_id;
                return a.seq < b.seq;
            });
        
        return global_log;
    }
    
    void flush_all_threads() {
        // 将所有线程的日志写入磁盘或全局缓冲区
        // 实际实现可调用 merge_global_order 并写入文件
    }
};
```

### 5.3 建议三：状态压缩降低内存占用

1. **预测编码 + 变长编码**：借鉴清华大学 GLSVLSI 2023 方案，在保存 Checkpoint 时先对信号值做预测编码（XOR 差值），再对差值序列做变长编码（如 Golomb-Rice 或指数 Golomb 编码）。对 RTL 仿真器而言，每个周期信号翻转率通常 < 5%，预测编码后会产生大量连续 0，压缩效率极高。

2. **恒值信号跳过**：Checkpoint 时只保存自上次快照以来发生变化的信号（dirty signals）。建立一个 dirty 位图（bitmask），每个信号对应 1 bit，0 表示未变化、1 表示已变化。对于大型设计（数百万信号），位图本身仅需几百 KB，却可避免保存大量恒值数据。

3. **分层压缩策略**：
   - 第一层：per-thread 局部压缩（每个线程独立压缩自己的状态块，无全局锁）。
   - 第二层：全局去重（合并各线程的压缩块，去除跨线程重复状态）。
   - 第三层：通用压缩（ZSTD 或 LZ4 对整个 Checkpoint 文件做最终压缩）。

4. **内存映射快照（mmap snapshot）**：CXXRTL 的 `debug_item` 设计启示——将仿真状态暴露为统一内存接口，可以方便地实现快速 `mmap` 快照。配合 `MAP_SHARED` 和 `msync` 可实现异步写盘，避免昂贵的逐值序列化。

---

## 6. 综合检查清单

### 6.1 Checkpoint 设计

- [ ] 确定快照保存范围：DUT 状态 + 调度器状态 + testbench 状态，缺一不可。
- [ ] 选择快照触发策略：固定时间间隔、固定事件数、或事件驱动（仅在活跃度高时保存）。
- [ ] 验证快照时刻的全局一致性：所有线程必须完成当前时间步计算，无"飞行中"更新。
- [ ] 评估 copy-on-write 的适用性：状态区大、每周期变化比例小（<10%）时优先采用。
- [ ] 为 Time Warp 回滚设计快照链：支持快速定位到目标时刻的最近前置快照。

### 6.2 确定性重放设计

- [ ] 识别非确定性来源：线程调度顺序、随机数生成、外部输入、异步中断。
- [ ] 选择记录粒度：事件步顺序（DeLorean 风格）或 per-signal 版本号（ReEmu 风格）。
- [ ] 设计 per-thread 日志格式：包含事件类型、仿真时间、线程ID、数据、局部序列号。
- [ ] 确定全局定序机制：每时钟沿同步一次，还是按固定时间窗口批量合并。
- [ ] 验证重放一致性：相同输入 + 相同日志 → 相同输出，必须是数学可证明的。

### 6.3 状态压缩设计

- [ ] 实现 dirty 位图：每信号 1 bit，仅保存自上次快照以来变化的信号。
- [ ] 集成预测编码：单比特信号预测翻转，多比特预测最低位翻转。
- [ ] 采用三级压缩流水线：局部编码 → 全局去重 → 通用压缩（ZSTD/LZ4）。
- [ ] 测量压缩/解压时间：确保压缩开销 < 并行收益，否则得不偿失。
- [ ] 考虑内存映射异步写盘：避免 I/O 阻塞仿真主循环。

---

## 参考来源

- [source-checkpoint-replay](source-checkpoint-replay.md) — RTL 仿真器 Checkpoint/Snapshot 实现方案（CXXRTL、ModelSim、Xcelium、UVM SnR）
- [source-state-compression](source-state-compression.md) — 数字波形压缩与仿真状态去重技术（清华大学 GLSVLSI 2023、FSDB/FST、gVisor）
- [source-deterministic-replay](source-deterministic-replay.md) — 确定性重放技术谱系（Mozilla rr、DeLorean、ReEmu、SymbFuzz）

---
id: "wiki-cdc-and-clocking"
title: "时钟域跨越与多时钟仿真"
description: "系统梳理CDC验证（亚稳态建模/2-FF同步器/reconvergence）、复位同步（async-assert/sync-deassert/RDC/ICG glitch）与多时钟/异步设计（GALS/异步FIFO/Yale FPGA映射）的工业级实践，为多线程RTL仿真器提供跨时钟域并行调度的具体设计指南"
tags: ["CDC", "clock-domain-crossing", "metastability", "reset-synchronization", "GALS", "asynchronous-fifo", "multi-clock", "RDC", "ICG"]
keywords: ["CDC验证", "2-FF同步器", "亚稳态PRNG", "reconvergence", "复位同步", "异步置位同步释放", "RDC", "ICG glitch", "GALS", "异步FIFO", "Yale FPGA映射"]
related_sources:
  - "source-cdc-verification"
  - "source-reset-clock"
  - "source-multiclock-async"
last_updated: "2026-07-02"
---

# 时钟域跨越与多时钟仿真

多时钟域设计是现代SoC的常态——CPU核、GPU、DDR控制器、PCIe、USB各跑在自己的时钟频率上，甚至同一芯片内存在数十个时钟域。对RTL仿真器而言，多时钟域既是挑战也是机遇：挑战在于跨域信号同步、亚稳态建模和事件调度复杂度的陡增；机遇在于**时钟域天然构成并行分区的边界**——每个时钟域内部的事件可以独立推进，只在跨域通信点需要同步。本章从CDC验证、复位同步和多时钟/异步设计三个维度，提炼对多线程RTL仿真器时钟域调度层的具体架构建议。

---

## 1. CDC验证：2-FF同步器与亚稳态建模

### 1.1 标准CDC同步器：2-Flip-Flop链

跨时钟域信号传递的基本单元是两级触发器同步器（2-FF synchronizer）：

```verilog
module sync_2ff (
    input  logic clk_dst,      // 目标时钟域
    input  logic rst_n,
    input  logic sig_src,      // 源时钟域信号
    output logic sig_dst       // 同步后的目标域信号
);
    logic meta, sync;
    
    always_ff @(posedge clk_dst or negedge rst_n) begin
        if (!rst_n) { meta <= 1'b0; sync <= 1'b0; }
        else        { meta <= sig_src; sync <= meta; }
    end
    
    assign sig_dst = sync;
endmodule
```

**原理**：第一级FF采样源域信号时可能进入亚稳态（metastability），第二级FF在下一个目标时钟沿采样，利用亚稳态解析的概率性特性降低失败概率。MTBF（平均故障间隔时间）随级数指数增长，但延迟也线性增加。

| 级数 | 亚稳态解析失败概率 | 典型延迟 | 典型MTBF |
|------|-------------------|----------|----------|
| 1级 | 较高 | 1 cycle | 较短 |
| 2级 | 低（工业标准） | 2 cycles | 10^7~10^9 years |
| 3级 | 极低 | 3 cycles | 10^15 years+ |

### 1.2 CDC-Jitter建模：PRNG驱动的亚稳态随机解析

Bosch Sensortec团队（DVCon Europe 2017）提出的核心洞察是：**标准RTL仿真不包含亚稳态概念，同步器总是按固定延迟输出，导致reconvergence相关bug在仿真中完全不可见**。

**CDC-Jitter模型核心**：在2-FF同步器的第一级与第二级之间引入`META`枚举状态：

```verilog
module cdc_jitter_sync (
    input  logic clk_dst,
    input  logic rst_n,
    input  logic sig_src,
    output logic sig_dst
);
    typedef enum logic [1:0] { STABLE_0, META, STABLE_1 } meta_state_t;
    meta_state_t meta_state;
    logic sync;
    
    // 每个实例独立种子 = 实例ID ^ 全局种子
    localparam SEED = `INSTANCE_ID ^ `GLOBAL_CDC_SEED;
    PRNG #(.SEED(SEED)) prng();
    
    always_ff @(posedge clk_dst or negedge rst_n) begin
        if (!rst_n) begin
            meta_state <= STABLE_0;
            sync <= 1'b0;
        end else begin
            case (meta_state)
                STABLE_0: if (sig_src) meta_state <= META;
                META: begin
                    // 模拟亚稳态解析：PRNG随机决定解析为0或1
                    meta_state <= prng.random_bit() ? STABLE_1 : STABLE_0;
                end
                STABLE_1: if (!sig_src) meta_state <= META;
            endcase
            sync <= (meta_state == STABLE_1);
        end
    end
    
    assign sig_dst = sync;
endmodule
```

**关键特性**：
- 每个同步器实例使用**唯一实例种子** + 约束随机仿真种子，保证可复现性（random stability）
- 当setup/hold违例时，第二级FF从PRNG取随机值解析，模拟真实硅片中的非确定性行为
- 相比2006年既有方案，Bosch改进在精度上更适合验证带门控时钟的低功耗同步器电路

### 1.3 Reconvergence：理想仿真中不可见的致命bug

**Reconvergence问题**：多比特信号（如计数器）跨时钟域时，若逐bit同步，在理想仿真中看似正常，但在CDC-jitter模型下会因为各bit随机延迟不同而产生**腐化值**（corrupted value）。

```verilog
// 错误：多比特计数器逐bit同步 → reconvergence风险
logic [7:0] counter_src;
logic [7:0] counter_dst;
genvar i;
generate
    for (i = 0; i < 8; i++) begin : sync_bits
        sync_2ff u_sync(.clk_dst(clk_dst), .sig_src(counter_src[i]), .sig_dst(counter_dst[i]));
    end
endgenerate
// 问题：counter_dst可能在某一周期出现0x0F→0x18的中间值（非法状态）
```

**解决方案**：Gray编码同步——Gray编码相邻值只有1bit变化，消除了reconvergence腐化：

```verilog
// 正确：Gray编码 + 2-FF同步
logic [7:0] counter_src, gray_src, gray_dst, counter_dst;
assign gray_src = counter_src ^ (counter_src >> 1);  // Binary → Gray
// Gray码经2-FF同步后，目标域再转回Binary
sync_2ff #(.WIDTH(8)) u_gray_sync(.clk_dst(clk_dst), .sig_src(gray_src), .sig_dst(gray_dst));
assign counter_dst = gray_dst ^ (gray_dst >> 1);  // Gray → Binary
```

**关键数据**：Bosch论文展示，在CDC-jitter模型下，reconvergence bug"几乎必然在首次仿真中触发"；而在理想仿真中完全不可见。

### 1.4 商业工具映射：Questa CDC + MSI

| 工具 | 功能 | 亚稳态建模 | 与仿真集成 |
|------|------|-----------|-----------|
| **Cadence Jasper CDC** | 形式化CDC检查 | 形式化MSI模型 | 属性导出到仿真 |
| **Questa CDC** | 结构检查+功能仿真 | Metastability Injection (MSI) | 原生支持 |
| **Synopsys CDC** | 完整CDC sign-off | 支持 | 与VCS集成 |
| **Bosch DVCon方案** | RTL早期CDC-jitter | PRNG随机解析 | 可嵌入任意仿真器 |

---

## 2. 复位同步：async-assert/sync-deassert与RDC

### 2.1 异步置位、同步释放复位同步器

ASIC工业标准复位策略：

```verilog
module rst_sync (
    input  logic clk,
    input  logic arst_n,       // 异步复位（全局）
    output logic srst_n        // 同步释放复位（本地）
);
    logic [1:0] rst_chain;
    
    always_ff @(posedge clk or negedge arst_n) begin
        if (!arst_n) rst_chain <= 2'b00;
        else          rst_chain <= {rst_chain[0], 1'b1};
    end
    
    assign srst_n = rst_chain[1];  // 同步释放
endmodule
```

**设计原则**：
- 异步断言：保证复位快速响应，不依赖时钟
- 同步释放：每个时钟域独立同步释放，避免亚稳态和不同时钟边沿唤醒导致的功能错乱
- 严禁用组合逻辑门控复位信号：`rst_n = arst_n & local_cond`是错误做法

### 2.2 FPGA vs ASIC差异

| 维度 | ASIC | FPGA |
|------|------|------|
| 推荐策略 | 异步置位/同步释放 | 纯同步复位 |
| 原因 | 专用异步复位引脚 | FF通常只有一个SR/CE引脚 |
| 异步复位代价 | 低（专用电路） | 高（占用routing资源，增加复杂度） |
| 释放要求 | 每域独立同步 | 单时钟域内同步即可 |

### 2.3 CE模式 vs 组合门控时钟：glitch的根源

**错误做法**（glitch高危）：
```verilog
// 错误：组合逻辑门控时钟
wire gated_clk = clk & enable;
always_ff @(posedge gated_clk)  // enable变化时可能产生runt pulse
    q <= d;
```

**正确做法**（CE模式）：
```verilog
// 正确：Clock Enable模式，综合工具自动映射到FF的CE引脚
always_ff @(posedge clk) begin
    if (enable) q <= d;  // 综合为：FF.CE = enable，glitch-free
end
```

**关键区别**：CE引脚在时钟沿前采样，无法产生runt pulse；而组合门控在`clk=1`期间`enable`翻转会产生glitch。仿真使用unit delay时很难捕捉，但硅片会corrupt FF状态。

### 2.4 RDC：复位域交叉与Rivos案例

Rivos在AI大芯片上的RDC（Reset Domain Crossing）实践表明：复位域交叉和异步复位驱动的时钟门控使能端是两类极易引发系统故障的根因。

**Meridian RDC发现的典型bug**：异步复位置位时，驱动ICG使能端的FF输出会独立于时钟边沿翻转，形成静态时序分析无法覆盖的**untimed path**。该untimed path传播到ICG后产生时钟毛刺。

**Rivos修复方案**：驱动ICG使能的复位必须"断言和释放都与被门控时钟同步"。

**RDC sign-off流程**：
1. 在CDC-clean基础上运行RDC
2. 定义复位场景（boot、warm reset等）和约束（exclusive signals、blocking signals）
3. 通过Meridian RDC的iDebug工具区分setup error与真实RDC violation
4. 修复后sign-off

---

## 3. 多时钟/异步设计：GALS、异步FIFO与FPGA映射

### 3.1 GALS：全局异步局部同步

CMU团队（ISCA 2002）提出的GALS仿真框架是事件驱动多时钟仿真的经典实现：

```cpp
// CMU GALS事件驱动引擎核心结构
struct Event {
    void (*callback)(void*);  // 回调函数
    void* arg;                // 参数
    uint64_t time;            // 触发时间
    uint32_t priority;        // 优先级
    uint64_t period;          // 重复周期（时钟域用）
};

// 全局事件队列（按时间排序的单链表）
class EventQueue {
    EventNode* head;  // 按time递增排序
public:
    void insert(const Event& e);  // O(n)插入，保持有序
    Event pop();                   // 取出头部最小时间事件
};

// 多时钟域注册：每个域是一个周期性事件
void register_clock_domain(uint64_t period_ns, void (*eval_fn)(void*)) {
    Event clk_event = {
        .callback = eval_fn,
        .time = period_ns,      // 首次触发
        .period = period_ns,    // 周期性重复
    };
    event_queue.insert(clk_event);
}
```

**三时钟域示例**：
| 时钟域 | 频率 | 周期 | 事件间隔 |
|--------|------|------|----------|
| CPU core | 100 MHz | 10 ns | 10 ns |
| DDR controller | 66.7 MHz | 15 ns | 15 ns |
| Peripheral | 50 MHz | 20 ns | 20 ns |

引擎按时间顺序推进：10ns→15ns→20ns→20ns→30ns→30ns→... 每个事件处理完后，若为周期性事件则自动将下一个周期事件重新入队。

### 3.2 异步FIFO：跨域通信的工业标准

异步FIFO是多时钟域之间数据传输的首选接口，相比stretchable clock方案（每通信一次暂停两边时钟）具有更高吞吐和更低延迟。

```verilog
module async_fifo #(
    parameter DW = 32,
    parameter DEPTH = 16
)(
    input  logic wclk, wreset_n,
    input  logic rclk, rreset_n,
    input  logic winc, rinc,
    input  logic [DW-1:0] wdata,
    output logic [DW-1:0] rdata,
    output logic wfull, rempty
);
    // 双端口SRAM
    logic [DW-1:0] mem [DEPTH];
    
    // 写指针（wclk域）
    logic [$clog2(DEPTH):0] wptr, wptr_gray;
    // 读指针（rclk域）
    logic [$clog2(DEPTH):0] rptr, rptr_gray;
    
    // 指针跨域同步： Gray码 + 2-FF
    logic [$clog2(DEPTH):0] rptr_sync_wclk, wptr_sync_rclk;
    sync_2ff #(.WIDTH($clog2(DEPTH)+1)) sync_r2w(.clk_dst(wclk), .sig_src(rptr_gray), .sig_dst(rptr_sync_wclk));
    sync_2ff #(.WIDTH($clog2(DEPTH)+1)) sync_w2r(.clk_dst(rclk), .sig_src(wptr_gray), .sig_dst(wptr_sync_rclk));
    
    // full/empty在各自域内生成
    assign wfull  = (wptr_gray == {~rptr_sync_wclk[$clog2(DEPTH):$clog2(DEPTH)-1], rptr_sync_wclk[$clog2(DEPTH)-2:0]});
    assign rempty = (rptr_gray == wptr_sync_rclk);
    
    // ... 写/读逻辑
endmodule
```

**关键特性**：
- full信号在写时钟域生成，empty信号在读时钟域生成
- Gray码保证指针跨域同步时不会出现多bit同时跳变导致的reconvergence
- 深度为2^n时可用最高位取反技巧判断full

### 3.3 Yale异步电路到同步FPGA映射

Yale团队提出将异步电路自动映射到同步FPGA进行功能仿真：

| 映射规则 | 含义 | 目的 |
|----------|------|------|
| **CYC** | 切断组合环，在环上插入FF | 打破反馈，适配同步时钟 |
| **SH** | 状态保持门（state-holding gate）反馈处放FF | 保留状态语义 |
| **DIR** | 输入到输出的直接路径放FF | 保证信号传播延迟 |

**加速效果**：相比异步软件仿真器加速 **1.3×10^5** 倍，相比商业数字仿真器加速 **2.8×10^4** 倍。核心原因：FPGA的并行门评估能力使"idle firing"不增加额外计算成本。

### 3.4 GalsBlock统一模型

IEEE提出的GalsBlock计算模型将同步组件封装为带本地控制时钟的atom block，异步组件封装为无时钟atom block，数据端口连接实现异步通信。支持统一的操作语义和形式语义，可生成可综合的VHDL代码。

---

## 4. 对多线程RTL仿真器的启示

### 4.1 多时钟域是天然的分区边界

每个时钟域内部的事件具有**时间局部性**——同一域内的信号在同一个时钟沿更新，不需要与其他域频繁同步。这构成了一种天然的多线程分区策略：
- 按时钟域分配线程，每个线程推进自己的事件队列
- 跨域通信点（如异步FIFO、握手信号）作为线程间通信通道
- 避免了全局事件队列的锁竞争

### 4.2 异步事件需要特殊调度语义

CDC-jitter模型要求仿真器在特定timing window内触发随机解析，这不同于传统的"确定性事件"语义：
- 亚稳态注入需要精确建模setup/hold violation的边界条件
- 每个同步器实例的独立PRNG状态需要线程安全的种子管理
- Reconvergence检测要求维护跨域信号的"有效时间戳"而非简单按cycle推进

### 4.3 事件队列的并行化瓶颈

CMU论文中的单链表全局事件队列在现代多核上难以扩展。当所有线程共享一个全局队列时，锁竞争成为主要瓶颈。解决方案：
- 按时钟域维护本地future事件队列
- 全局合并仅在跨域通信点或周期边界发生
- 借鉴"时间窗口分片"或YAWNS协议减少全局同步频率

---

## 5. 可操作建议：按时钟域分区线程、异步FIFO用无锁SPSC、CDC monitor用观察者模式

### 5.1 架构级设计：按时钟域分区的多线程仿真器

```cpp
// 按时钟域分区的多线程仿真器核心
class ClockDomainPartitionedSimulator {
    struct ClockDomain {
        uint64_t period;                  // 时钟周期（fs/ps/ns）
        uint64_t next_edge;               // 下一个时钟沿时间
        std::vector<Partition*> partitions; // 该域内的RTL分区
        std::thread worker;               // 专属工作线程
    };
    
    std::vector<ClockDomain> domains_;
    std::vector<AsyncChannel*> cross_domain_channels_;
    
public:
    void run() {
        // 每个时钟域一个独立线程
        for (auto& domain : domains_) {
            domain.worker = std::thread([&domain, this]() {
                while (current_time_ < end_time_) {
                    // 1. 等待到下一个时钟沿（或更早的异步事件）
                    wait_until(domain.next_edge);
                    
                    // 2. 执行本域内所有组合逻辑（无需全局同步）
                    for (auto* part : domain.partitions) {
                        part->eval_combinational();
                    }
                    
                    // 3. 更新时序元件（本域内同步）
                    for (auto* part : domain.partitions) {
                        part->update_sequential();
                    }
                    
                    // 4. 推进到下一个时钟沿
                    domain.next_edge += domain.period;
                    
                    // 5. 向跨域通道写入更新后的信号
                    for (auto* ch : cross_domain_channels_) {
                        if (ch->source_domain == &domain) {
                            ch->enqueue_updates();
                        }
                    }
                }
            });
        }
        
        // 全局协调线程：处理跨域通信和barrier
        std::thread coordinator([&]() {
            while (current_time_ < end_time_) {
                // 找到所有域中最早的下一个事件时间
                uint64_t next_global = min_next_edge(domains_);
                
                // 等待所有域到达next_global或提交跨域更新
                barrier_wait(next_global);
                
                // 分发跨域更新到目标域的异步通道
                for (auto* ch : cross_domain_channels_) {
                    ch->transfer_pending();
                }
                
                current_time_ = next_global;
            }
        });
    }
};
```

### 5.2 异步FIFO用无锁SPSC队列

跨时钟域的数据传输应使用**无锁单生产者单消费者（SPSC）队列**替代全局锁：

```cpp
// 基于环形缓冲区的无锁SPSC队列（用于异步FIFO跨线程通信）
template<typename T, size_t Size>
class LockFreeSPSCQueue {
    // 容量必须是2的幂，以便用位掩模代替取模
    static_assert((Size & (Size - 1)) == 0, "Size must be power of 2");
    
    alignas(64) std::atomic<size_t> write_idx_{0};   // 仅生产者写入
    alignas(64) std::atomic<size_t> read_idx_{0};    // 仅消费者读取
    T buffer_[Size];
    
public:
    bool try_enqueue(const T& item) {
        const size_t w = write_idx_.load(std::memory_order_relaxed);
        const size_t r = read_idx_.load(std::memory_order_acquire);
        
        if ((w - r) >= Size) return false;  // full
        
        buffer_[w & (Size - 1)] = item;
        write_idx_.store(w + 1, std::memory_order_release);
        return true;
    }
    
    bool try_dequeue(T& item) {
        const size_t r = read_idx_.load(std::memory_order_relaxed);
        const size_t w = write_idx_.load(std::memory_order_acquire);
        
        if (w == r) return false;  // empty
        
        item = buffer_[r & (Size - 1)];
        read_idx_.store(r + 1, std::memory_order_release);
        return true;
    }
};

// 跨域信号通道：封装SPSC队列 + CDC-jitter模型
class CrossDomainSignalChannel {
    LockFreeSPSCQueue<SignalUpdate, 1024> queue_;
    CDCJitterModel jitter_model_;  // 每个通道独立PRNG
    
public:
    void send(const SignalUpdate& update, uint64_t send_time) {
        // 在源域发送时，计算CDC延迟（含jitter）
        uint64_t arrival_time = send_time + jitter_model_.sample_delay();
        SignalUpdate delayed = update;
        delayed.timestamp = arrival_time;
        queue_.try_enqueue(delayed);
    }
    
    // 目标域在周期边界调用
    void receive(uint64_t up_to_time, std::vector<SignalUpdate>& out) {
        SignalUpdate update;
        while (queue_.try_dequeue(update)) {
            if (update.timestamp <= up_to_time) {
                out.push_back(update);
            } else {
                // 时间未到，回退到队列（需要支持peek/dequeue回退）
                break;
            }
        }
    }
};
```

### 5.3 CDC Monitor用观察者模式

将CDC检测从仿真核心逻辑中解耦，使用观察者模式实现非侵入式监控：

```cpp
// CDC观察者模式：非侵入式监控跨域信号
class CDCMonitor : public SimulationObserver {
    struct SyncInstance {
        uint64_t instance_id;
        uint64_t seed;
        SignalHandle src_sig;
        SignalHandle dst_sig;
        CDCJitterModel jitter;
    };
    
    std::vector<SyncInstance> sync_instances_;
    
public:
    void on_signal_change(SignalHandle sig, LogicValue new_val, uint64_t time) override {
        for (auto& inst : sync_instances_) {
            if (sig == inst.src_sig) {
                // 源信号变化 → 触发CDC-jitter模型
                if (is_near_clock_edge(time, inst.dst_clock)) {
                    // Setup/hold violation可能发生
                    LogicValue resolved = inst.jitter.resolve_metastability(new_val);
                    schedule_delayed_update(inst.dst_sig, resolved, 
                        time + inst.jitter.sample_delay());
                }
            }
        }
    }
    
    void on_clock_edge(ClockHandle clk, uint64_t time) override {
        // 检查reconvergence：在时钟沿后比较跨域多bit信号的同步一致性
        for (auto& group : reconvergence_groups_) {
            if (group.clock == clk) {
                check_reconvergence(group, time);
            }
        }
    }
    
    void check_reconvergence(const ReconvergenceGroup& group, uint64_t time) {
        std::vector<LogicValue> synced_bits;
        for (auto sig : group.signals) {
            synced_bits.push_back(sig->value());
        }
        
        // 检测是否出现Gray编码不允许的中间值
        if (!is_valid_gray_transition(group.last_values, synced_bits)) {
            report_cdc_violation("RECONVERGENCE", group, time);
        }
        group.last_values = synced_bits;
    }
};

// 在仿真器初始化时注册观察者
void Simulator::init() {
    auto cdc_monitor = std::make_unique<CDCMonitor>();
    // 自动扫描设计中的跨域信号，注册同步实例
    cdc_monitor->auto_detect_sync_instances(design_);
    register_observer(std::move(cdc_monitor));
}
```

### 5.4 复位同步的多线程处理

```cpp
// 复位树分发：减少跨线程广播开销
class ResetDistributionTree {
    std::vector<LogicValue> per_thread_reset_;  // 每线程本地复位副本
    
public:
    void assert_global_reset() {
        // 全局异步断言：原子写所有线程副本
        for (auto& rst : per_thread_reset_) {
            rst.store(0, std::memory_order_release);  // 低有效
        }
    }
    
    void release_domain_reset(int domain_id, uint64_t release_time) {
        // 同步释放：仅更新指定域的本地副本
        per_thread_reset_[domain_id].store(1, std::memory_order_release);
    }
    
    LogicValue get_thread_local_reset(int thread_id) {
        return per_thread_reset_[thread_id].load(std::memory_order_acquire);
    }
};
```

### 5.5 时钟门控与动态线程挂起

```cpp
// 支持ICG的动态线程挂起/唤醒
class ClockGatedDomain {
    std::atomic<bool> active_{true};
    std::atomic<bool> shutdown_requested_{false};
    
public:
    void eval_cycle() {
        if (!active_.load(std::memory_order_acquire)) {
            // 门控关闭：自旋等待唤醒，或yield CPU
            while (!active_.load(std::memory_order_acquire)) {
                if (shutdown_requested_.load(std::memory_order_acquire)) return;
                _mm_pause();  // 提示CPU空闲
            }
        }
        // 正常执行周期...
    }
    
    void set_clock_gating(bool enable) {
        active_.store(enable, std::memory_order_release);
    }
};
```

---

## 6. 综合检查清单

在将CDC/多时钟支持集成到多线程RTL仿真器时，逐条确认：

- [ ] 支持按时钟域分区线程，每域维护独立的事件推进时间
- [ ] 跨域信号通信使用无锁SPSC队列，避免全局锁竞争
- [ ] 集成CDC-jitter模型，每个同步器实例有独立PRNG种子，保证可复现性
- [ ] Reconvergence检测在周期barrier后执行，自动扫描多bit跨域信号
- [ ] 复位树采用每线程本地副本，异步断言全局广播，同步释放按域独立
- [ ] 时钟门控支持动态线程挂起/唤醒，避免门控域的空转CPU消耗
- [ ] RDC验证支持在ICG使能端引入随机毛刺注入，转化静态RDC问题为可复现仿真失败
- [ ] 全局协调线程使用轻量级自旋barrier（非pthread条件变量），减少周期级同步开销
- [ ] 支持GALS风格的周期事件注册，每个域的周期和相位可独立配置
- [ ] 跨域通信时间戳使用扩展精度（物理时间+逻辑相位），确保delta cycle因果序

---

## 参考来源

- [source-cdc-verification](source-cdc-verification.md) — 2-FF同步器、CDC-jitter PRNG建模、reconvergence问题、Bosch DVCon论文、Questa/MSI工具
- [source-reset-clock](source-reset-clock.md) — 异步置位同步释放、CE模式vs组合门控、Rivos RDC、ICG glitch案例
- [source-multiclock-async](source-multiclock-async.md) — GALS(CMU ISCA'02)、异步FIFO、Yale FPGA映射、GalsBlock统一模型

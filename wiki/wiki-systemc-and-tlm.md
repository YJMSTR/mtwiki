---
title: SystemC/TLM与RTL协同仿真
description: SystemC内核机制、TLM-2.0抽象、TLM↔RTL桥接模式与跨层并行化策略的综合技术参考，面向多线程RTL仿真器设计的可操作建议
category: wiki
tags: ["SystemC", "TLM-2.0", "RTL", "co-simulation", "parallel-simulation", "transactor", "temporal-decoupling", "multi-thread"]
refs: [source-systemc-kernel, source-tlm-rtl, source-cross-layer-parallel]
authors: ["Wiki_写作_SystemC_TLM"]
date: 2026-07-03
---

# SystemC/TLM与RTL协同仿真

> **TLM 是 RTL 的「加速外套」**——先用 TLM 跑系统级验证，再用 RTL 抠 cycle 级细节。跨层并行化的核心命题是：如何让高层的时间解耦推进与低层的 delta-cycle 精确推进在同一平台上共存，并榨干多核主机的算力。

---

## 1. SystemC 内核：基于协程的合作式调度器

### 1.1 四状态机与进程模型

SystemC 调度器不是 OS 调度器，而是**单线程内的协程式合作调度器**。所有 `SC_THREAD` / `SC_METHOD` 在同一个 OS 线程上顺序执行，没有抢占、没有时间片。

```
┌─────────────────────────────────────────┐
│         SystemC 进程四状态机             │
├─────────────────────────────────────────┤
│                                         │
│  ┌──────────┐  wait(event/time)  ┌──────┐
│  │ Runnable │ ──────────────────→ │ Wait │
│  │ (就绪)   │ ←──────────────────│ (等待)│
│  └────┬─────┘   notify/event触发  └──────┘
│       │                                 │
│       ▼ resume()                       │
│  ┌──────────┐                          │
│  │ Running  │ ─── return / 结束 ──→ ┌────────┐
│  │ (运行中) │                       │Terminated│
│  └──────────┘                       └────────┘
│                                         │
└─────────────────────────────────────────┘
```

| 特性 | `SC_THREAD` | `SC_METHOD` |
|------|-------------|-------------|
| 栈上下文 | 有持久协程栈（`wait()` 挂起） | 无持久栈（函数返回即结束） |
| 触发方式 | 敏感列表事件 / `wait()` | 仅敏感列表事件 |
| 开销 | 协程切换（较重） | 函数调用（较轻） |
| 典型用法 | 复杂状态机、协议栈 | 组合逻辑、时钟触发 |

### 1.2 Delta-Cycle：Evaluate-Update 双阶段循环

这是 RTL 非阻塞赋值与 SystemC 信号更新的共同语义基础。同一仿真时刻 `t` 内，调度器会执行多轮 delta cycle，直到没有 pending 事件，才推进仿真时间。

```
仿真时间 T
  │
  ▼
┌──────────────┐
│  Initialize  │  ← 初始化阶段：所有进程执行到第一个 wait()
└──────┬───────┘
       │
       ▼
  ┌──────────┐     ┌──────────┐
  │ Evaluate │ ──→ │  Update  │  ← 一轮 delta cycle
  │  (执行)  │     │ (刷信号) │
  └────┬─────┘     └────┬─────┘
       │                │
       │ 有新delta事件?  │
       └────── 是 ───────┘
              否
               │
               ▼
       ┌────────────┐
       │  Timed     │  ← 推进到下一个定时事件
       │  Advance   │     (如 clk.posedge_event @ T+5ns)
       └─────┬──────┘
             │
             ▼
       下一个仿真时间 T'
```

```cpp
// 调度器核心伪代码（简化但准确）
void simulation_loop() {
  while (!done) {
    evaluate_update_loop();           // 处理当前时刻所有 delta cycle
    next_time = time_queue.next_wakeup();
    if (next_time == INFINITY) break; // 无事件，结束
    current_time = next_time;
    runnable_queue.add(time_queue.pop_due(current_time));
  }
}

void evaluate_update_loop() {
  while (runnable_queue not empty) {
    // ── Evaluate Phase ──
    while (runnable_queue not empty) {
      p = runnable_queue.pick_one();  // 顺序未指定！
      p.resume();                      // 运行到 wait() 或 return
    }
    // ── Update Phase ──
    for each channel c in update_queue:
      c.update();                      // new_value → current_value
      if (value_changed) {
        runnable_queue.add(c.sensitive_processes);
      }
    update_queue.clear();
  }
}
```

> ⚠️ **关键约束**：Evaluate 阶段进程执行顺序是**未指定（unspecified）**的。任何依赖特定执行顺序的代码都是非确定性的，必须被显式 `wait()` 或 `sc_buffer` 切断。

### 1.3 事件通知三队列

```
┌────────────────────────────────────────────┐
│          SystemC 事件通知架构               │
├────────────────────────────────────────────┤
│                                              │
│  ┌──────────────┐  ┌──────────────┐        │
│  │  EQ_imm      │  │  EQ_delta    │        │
│  │  (即时通知)  │  │  (零延迟通知) │        │
│  │  notify()    │  │  notify(SC_ZERO_TIME)│  │
│  │  同 evaluate │  │  下一delta触发       │  │
│  └──────┬───────┘  └──────┬───────┘        │
│         │                 │                │
│         └────────┬────────┘                │
│                  │                        │
│                  ▼                        │
│         ┌──────────────┐                  │
│         │  EQ_timed    │                  │
│         │  (定时通知)  │                  │
│         │  notify(t)   │                  │
│         │  时间 T 触发  │                  │
│         └──────┬───────┘                  │
│                │                          │
│                ▼                          │
│         ┌──────────────┐                  │
│         │ 时间推进轮次 │                  │
│         └──────────────┘                  │
│                                              │
└────────────────────────────────────────────┘
```

### 1.4 并行化引擎：SCOPE / parSC / SCGPSim

SystemC 标准实现的单线程调度器是性能瓶颈。学术界和工业界提出了多种并行化方案：

| 方案 | 作者 | 机制 | 加速比 | 核心洞察 |
|------|------|------|--------|----------|
| **SCOPE** | Weinstock (RWTH Aachen) | 时间解耦 + 远程事件队列 + 公平自旋锁 | **4–8×** | 每个线程本地 `EQ_timed` + 锁 `λ_i`，零延迟通知统一转 timed |
| **parSC** | Schumacher | Master-Worker 模型，evaluate 阶段 barrier 同步 | 良好（超线性） | 合作式调度可安全转化为分区并行 |
| **SCGPSim** | Mahesh et al. | SystemC 内核映射到 GPU CUDA 线程 | 显著加速 | 将单线程瓶颈 offload 到 GPU |
| **Jones 乐观式** | Samuel Jones | 多独立调度器 + 全局 quantum | 1.5–2× | 允许时间乱序，事后用 timing specifiers 约束 |

```cpp
// SCOPE 并行内核中的远程事件触发决策
Function TRIGGERDecision(RemoteEvent e)
  requests ← H_e[t_e ... t_i - Δt_la];  // 提取相关历史
  t_act ← ∞;                            // 假设事件未激活
  while requests ≠ ∅ do
    r ← extract earliest from requests;
    if r is cancel then
      t_act ← ∞;                        // 远程取消覆盖
    else if t_r < t_act then
      t_act ← t_r;                      // 远程通知覆盖
    end
  end
  if t_act == t_i then
    RQ ← RQ ∪ S_e ∪ D_e;               // 触发事件，加入就绪队列
    D_e ← ∅;
    t_e ← t_i;
  end
End
```

---

## 2. TLM-2.0：用函数调用替代 pin 级翻转

### 2.1 Loosely-Timed vs. Approximately-Timed

| 维度 | **Loosely-Timed (LT)** | **Approximately-Timed (AT)** |
|------|------------------------|------------------------------|
| 传输方式 | `b_transport()`（阻塞） | `nb_transport_fw/bw()`（非阻塞） |
| 时间模型 | Temporal Decoupling，本地时间超前 | 多阶段握手（BEGIN_REQ/END_REQ/...） |
| 同步频率 | 低（quantum 边界才同步） | 中（每阶段可能同步） |
| 适用场景 | 软件/功能验证、架构探索 | 吞吐/延迟分析、协议验证 |
| 仿真速度 | 最快（50,000 txn/s） | 较快（~5,000 txn/s） |
| 精度 | 功能级，无 timing | 协议级 timing |

```cpp
// ── Loosely-Timed: blocking transport ──
void do_transaction() {
  tlm_generic_payload trans;
  trans.set_command(TLM_WRITE_COMMAND);
  trans.set_address(MPEG_ENCODE_ADDR);
  trans.set_data_ptr(reinterpret_cast<unsigned char*>(&data));
  trans.set_data_length(4);

  sc_time delay = SC_ZERO_TIME;
  // 阻塞传输：整个事务在一个函数调用中完成
  // initiator 可以在此跑 ahead，直到 quantum 边界才同步
  out_socket->b_transport(trans, delay);

  if (trans.is_response_error())
    SC_REPORT_ERROR("TLM", "Response error");
}

// ── Approximately-Timed: non-blocking transport ──
void start_transaction() {
  tlm_generic_payload* trans = new tlm_generic_payload;
  trans->set_command(TLM_WRITE_COMMAND);
  trans->set_address(MPEG_ENCODE_ADDR);
  trans->set_data_ptr(data_ptr);

  sc_time delay = SC_ZERO_TIME;
  tlm_phase phase = BEGIN_REQ;
  tlm_sync_enum status;

  // 非阻塞前向传输：启动请求阶段
  status = out_socket->nb_transport_fw(*trans, phase, delay);

  if (status == TLM_UPDATED) {
    // 目标返回更新后的 phase，可能需要继续握手
  } else if (status == TLM_ACCEPTED) {
    // 目标将在后续回调中通知（如 END_REQ / BEGIN_RESP）
  }
}
```

### 2.2 Temporal Decoupling：TLM 的「时间超前」秘诀

```
┌─────────────────────────────────────────────┐
│         Temporal Decoupling 原理             │
├─────────────────────────────────────────────┤
│                                               │
│  Initiator 本地时间                           │
│  ├─ 0 ns: 发起事务 b_transport(trans, local) │
│  ├─ 10 ns: 目标返回，local += 10 ns         │
│  ├─ 再发起事务，local += 20 ns              │
│  ├─ 再发起事务，local += 30 ns              │
│  │                                            │
│  │  本地时间 = 60 ns                          │
│  │  全局 quantum = 100 μs                     │
│  │  60 ns < 100 μs → 无需同步！               │
│  │                                            │
│  ▼ 当 local >= quantum 时                    │
│     wait(local_time);  // 同步到全局时间      │
│     local_time = SC_ZERO_TIME;              │
│                                               │
└─────────────────────────────────────────────┘
```

```cpp
// 在 sc_main 中设置全局 quantum
const sc_time GLOBAL_QUANTUM(100, SC_US);
tlmu_global_quantum::instance().set(global_quantum);

// Initiator 中使用 local time
void initiator_thread() {
  tlm_generic_payload trans;
  sc_time local_time = SC_ZERO_TIME;

  while (true) {
    trans.set_command(TLM_READ_COMMAND);
    trans.set_address(next_addr);

    // 调用阻塞传输，local_time 会累加目标返回的延迟
    socket->b_transport(trans, local_time);

    // 检查是否需要同步到全局时间
    if (local_time >= tlmu_global_quantum::instance().get()) {
      wait(local_time);  // 同步到全局仿真时间
      local_time = SC_ZERO_TIME;
    }
  }
}
```

---

## 3. TLM ↔ RTL 桥接：跨抽象层的翻译官

### 3.1 Transactor 模式：TLM 事务 → pin 级信号

```
┌─────────────────────────────────────────────────────────┐
│              TLM ↔ RTL 混仿架构（Intel 模式）            │
├─────────────────────────────────────────────────────────┤
│                                                         │
│   ┌──────────┐      ┌────────────┐    ┌──────────┐   │
│   │ Traffic  │ ──→  │  TLM 模型   │    │ Correlation│   │
│   │Generator │      │  (LT/AT)   │    │  Module   │   │
│   └────┬─────┘      └────────────┘    └────▲─────┘   │
│        │                                     │         │
│        │ 同一激励同时驱动两条路径              │         │
│        │                                     │         │
│        └────────────┐  ┌──────────────────────┘         │
│                     │  │                                │
│   ┌─────────────────▼──▼────────────────────┐         │
│   │           AXI Transactor                 │         │
│   │  ┌────────────────────────────────────┐ │         │
│   │  │  tlm_generic_payload → AXI 握手    │ │         │
│   │  │  AW/W/B/AR/R 通道信号序列          │ │         │
│   │  └────────────────────────────────────┘ │         │
│   └─────────────┬───────────────────────────┘         │
│                 │                                     │
│   ┌─────────────▼─────────────────────┐              │
│   │  RTL DUT (via Commercial Simulator)│              │
│   │  64 txn/s  ← 性能断崖              │              │
│   └────────────────────────────────────┘              │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

```cpp
SC_MODULE(axi_transactor) {
  tlm_target_socket<32, tlm_generic_payload> target_socket;
  sc_out<bool> awvalid;
  sc_out<sc_uint<32>> awaddr;
  sc_in<bool> awready;
  // ... 其他 AXI 信号

  SC_CTOR(axi_transactor) : target_socket("target_socket") {
    target_socket.register_b_transport(this, &axi_transactor::b_transport);
  }

  void b_transport(tlm_generic_payload& trans, sc_time& delay) {
    // TLM → RTL: 将事务拆分为 AXI 握手序列
    uint32_t addr = trans.get_address();
    tlm_command cmd = trans.get_command();

    // 写地址通道
    wait(delay);  // 同步到 RTL 时间
    awaddr.write(addr);
    awvalid.write(true);
    wait(awready.posedge_event());  // 等待握手完成
    awvalid.write(false);

    // 写数据通道 ...（省略）
    // 写响应通道 ...（省略）

    trans.set_response_status(TLM_OK_RESPONSE);
    delay = SC_ZERO_TIME;
  }
};
```

### 3.2 性能断崖：从 50,000 到 64 txn/s

Intel DVCon 论文的实测数据揭示了跨抽象层仿真的最大痛点：

| 平台 | 仿真器 | 速度 | 相对加速 |
|------|--------|------|----------|
| 纯 TLM-2.0 (LT) | OSCI simulator | **50,000 txn/s** | ~781× |
| 纯 TLM-2.0 (AT) | OSCI simulator | ~5,000 txn/s | ~78× |
| **TLM-2.0 + RTL 混仿** | Commercial RTL simulator | **64 txn/s** | 1× (baseline) |

> **「64 txn/s」意味着一个 AXI burst 事务可能需要 1/64 秒 ≈ 15 ms 的仿真时间。对于需要跑 boot OS 的验证平台，这是不可接受的。**

瓶颈来源：
1. **Transactor 翻译开销**：每个 TLM 事务要拆分为数十个 pin 级翻转
2. **跨进程通信**：商业 RTL 仿真器与 SystemC 通过 DPI/PLI 接口通信，每次调用都有 IPC 开销
3. **时间同步**：RTL 每 cycle 都需要与 SystemC 全局时间同步
4. **事件密度差异**：TLM 一个函数调用 = RTL 数百个 delta cycle

### 3.3 RTL-to-TLM 抽象：反向加速（10–1000×）

```
┌─────────────────────────────────────────────┐
│         RTL-to-TLM 自动抽象流程              │
├─────────────────────────────────────────────┤
│                                               │
│  RTL 可综合设计                               │
│       │                                       │
│       ▼                                       │
│  ┌─────────────────┐                          │
│  │ 时序提取引擎     │  ← 提取 FSM、状态转换    │
│  │ 功耗分析引擎     │  ← 标注动态功耗模型      │
│  └────────┬────────┘                          │
│           │                                   │
│           ▼                                   │
│  ┌─────────────────────────────────────┐    │
│  │  时间-功耗注释的 TLM 模型             │    │
│  │  • 事务延迟 = 原 RTL cycle 数 × clk  │    │
│  │  • 功耗状态 = 活动/待机/关断          │    │
│  │  • 误差 < 10%（NoC 论文数据）        │    │
│  └────────┬────────────────────────────┘    │
│           │                                   │
│           ▼                                   │
│  仿真速度：10–1000× 于 RTL 仿真               │
│  适用场景：架构探索、软件提前开发、功耗分析     │
│                                               │
└─────────────────────────────────────────────┘
```

> 原文：*"Transaction-level modeling allows a simulation speed-up up to 1000x with respect to RTL. This paper presents a methodology to accelerate RTL fault simulation through automatic RTL-to-TLM abstraction."* — Bombieri et al., IEEE ETS 2011

---

## 4. 跨层并行化：让 TLM 和 RTL 一起飞

### 4.1 方案全景对比

| 方案 | 目标系统 | 关键机制 | 加速比 | 核心思想 |
|------|----------|----------|--------|----------|
| **SystemC-SMP (TLM-DT)** | 40 核 MPSoC VP | 分布式时间 + null message | **1.8×** | 每个组件本地时间，null message 防死锁 |
| **TLM/T + PDES** | 多集群 SoC | PDES + SC_THREAD 作为 LP | **50× vs BCA** | 逻辑进程 + 时间戳消息 |
| **SCOPE** | 真实工业 VP | 时间解耦 + 远程事件队列 | **4–8×** | 本地 `EQ_timed` + 公平锁 |
| **Jones 乐观式** | 通用 SoC | 多调度器 + 全局 quantum | 1.5–2× | 允许时间乱序，事后约束 |
| **SoCRocket** | ESA SoC 平台 | LT/AT/RTL 动态切换 | **1500× vs RTL** | 运行时配置抽象层级 |

### 4.2 TLM-DT / SystemC-SMP：分布式时间 + Null Message

Viaud 等人的核心创新：**放弃全局 SystemC 时间，让每个仿真组件拥有本地时间**。通过 null message（仅含时间戳的空消息）防止保守并行死锁。

```
潜在死锁场景：
  ┌────┐        ┌────┐        ┌────┐
  │ S1 │ ──m──→ │ S2 │ ──m'──→│ S3 │
  │    │  t=20  │    │  t=10  │    │
  └────┘        └────┘        └────┘
    ↑                          │
    └──── S3 等 S1 保证时间 ───┘

解决方案：S1 发送 null message 给 S3，时间戳 10
  "我不会在时间 10 之前发送任何真实事件"
  → S3 可以安全推进到时间 10
```

```cpp
// Null Message 发送
void send_null_message(sc_time guarantee_time, int target_lp) {
  tlm_generic_payload null_trans;
  null_trans.set_data_ptr(nullptr);  // 空数据
  null_trans.set_data_length(0);

  // 附加时间戳作为扩展属性
  sc_time local_time = get_local_time();
  assert(guarantee_time >= local_time);

  // 发送到目标 LP 的输入队列
  lp_channels[target_lp]->send(null_trans, guarantee_time);
}
```

### 4.3 乐观式并行化：Jones 的多调度器架构

```cpp
// 设置全局 quantum，限制任意两个调度器之间的时间差
sc_set_global_quantum(100, SC_US);

// 将进程绑定到不同调度器
SC_AFFINITY(prod.run_thread, SCHEDULER_0);
SC_AFFINITY(cons.run_thread, SCHEDULER_1);

// Producer 线程：局部时间推进，不需要每次同步
void Producer::run_thread() {
  while (true) {
    wait(50, SC_US);  // 本地推进 50 us
    produce_item();

    // 发送事务，附带 timing specifier
    tlm_generic_payload trans;
    sc_time delay = SC_ZERO_TIME;
    sync_type sync = SYNC_CATCH_UP;  // 事务前要求同步
    socket->b_transport(trans, delay, sync);
  }
}
```

| Timing Specifier | 含义 | 用途 |
|------------------|------|------|
| `SYNC_WAIT` | 阻塞直到对方同步 | 严格顺序依赖 |
| `SYNC_CATCH_UP` | 事务前要求对方追赶 | 定期对齐 |
| `FULL_SYNC` | 完全同步 | 关键检查点 |

### 4.4 SCOPE 引擎的时间解耦与锁管理

```cpp
// SCOPE 扩展：每个线程本地时间 + 公平自旋锁
class SCOPE_Thread {
private:
  sc_time t_i;           // 本地仿真时间
  mutex_t lambda_i;        // 本地时间队列锁（fair ticket-based spinlock）
  EventQueue EQ_timed;     // 本地定时事件队列

public:
  void process_timed_events() {
    acquire(lambda_i);   // 必须先获取锁

    while (!EQ_timed.empty()) {
      Event e = EQ_timed.front();
      if (e.timestamp > t_lim_i) {
        // 本地时间将超过限制，释放锁让其他线程通知
        release(lambda_i);
        spin_wait();       // 短暂自旋等待
        acquire(lambda_i);
      }
      t_i = e.timestamp;
      trigger_event(e);
      EQ_timed.pop();
    }

    release(lambda_i);
  }

  void remote_notify_zero_delay(Event e, int target_thread) {
    // 零延迟远程通知：转换为 Δt_notify = 0 的 timed 通知
    if (Delta_t_notify < Delta_t_la) {
      threads[target_thread]->EQ_timed.push(e, t_j);
    }
  }
};
```

---

## 5. 抽象层级连续谱：从 PV 到 Transistor

```
仿真速度（相对 RTL）
  ↑
10^4 │  ┌────────────────────────────────────┐
     │  │ PV (Programmer View, untimed)      │  ← 软件/算法团队
     │  │ 函数级调用，无 timing              │
     │  └────────────────────────────────────┘
     │
10^3 │  ┌────────────────────────────────────┐
     │  │ TLM-LT (Loosely-Timed)             │  ← 软件/架构团队
     │  │ b_transport, temporal decoupling   │     SoCRocket 1500×
     │  └────────────────────────────────────┘
     │
10^2 │  ┌────────────────────────────────────┐
     │  │ TLM-AT (Approximately-Timed)       │  ← 架构/验证团队
     │  │ nb_transport, 多阶段握手           │
     │  └────────────────────────────────────┘
     │
10^1 │  ┌────────────────────────────────────┐
     │  │ Bus-Functional / Cycle-Approximate │  ← 总线/协议验证
     │  │ 部分 cycle 精确，部分抽象          │
     │  └────────────────────────────────────┘
     │
  1  │  ┌────────────────────────────────────┐
     │  │ RTL (Cycle-Accurate)               │  ← 验证/后端团队
     │  │ 完整 delta-cycle, pin 级精确        │     baseline
     │  └────────────────────────────────────┘
     │
10^-1│  ┌────────────────────────────────────┐
     │  │ Gate-Level (门级)                   │  ← 后端/STA
     │  │ 带门延迟，SCL/SDF 反标              │
     │  └────────────────────────────────────┘
     │
10^-2│  ┌────────────────────────────────────┐
     │  │ Transistor (晶体管级)               │  ← 模拟电路
     │  │ SPICE/SPectre 仿真                 │
     │  └────────────────────────────────────┘
     │
     └──────────────────────────────────────────→ 精度
          低                                       高
```

> **抽象层级的选择不是非此即彼，而是设计阶段驱动的连续决策。** 算法团队用 PV 验证功能正确性，软件团队用 TLM-LT boot OS，架构团队用 TLM-AT 分析吞吐/延迟，验证团队用 RTL 确认 cycle 级行为，后端团队用 Gate-Level 跑 STA。

---

## 6. 对多线程 RTL 仿真器的启示

### 6.1 分层并行：TLM 乐观 + RTL 保守

```
┌─────────────────────────────────────────────────────────┐
│           跨层混合并行化架构（推荐模式）                  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────────┐   ┌──────────────────┐           │
│  │   TLM 层 (LT)    │   │   TLM 层 (LT)    │           │
│  │  ┌────────────┐  │   │  ┌────────────┐  │           │
│  │  │ Initiator  │  │   │  │ Initiator  │  │           │
│  │  │ (temporal  │  │   │  │ (temporal  │  │           │
│  │  │  decoupled)│  │   │  │  decoupled)│  │           │
│  │  └──────┬─────┘  │   │  └──────┬─────┘  │           │
│  │         │        │   │         │        │           │
│  │    乐观式同步    │   │    乐观式同步    │           │
│  │  (global quantum)│  │  (global quantum)│          │
│  └────┬────┴────┬───┘   └────┬────┴────┬───┘           │
│       │         │            │         │               │
│       │    ┌───┴────────────┴───┐     │               │
│       │    │   Transactor 线程     │     │               │
│       │    │  (quantum 边界同步)   │     │               │
│       │    └────┬──────────┬─────┘     │               │
│       │         │          │             │               │
│  ┌────┴─────────┐        ┌─┴─────────────┐              │
│  │  RTL 线程 #1 │        │  RTL 线程 #2  │              │
│  │  delta-cycle │        │  delta-cycle  │              │
│  │  保守同步    │        │  保守同步     │              │
│  │  (barrier)   │        │  (barrier)    │              │
│  └──────────────┘        └───────────────┘              │
│                                                         │
│  关键：TLM 部分用乐观同步跑在前面，RTL 部分用保守同步    │
│        在 transactor 的 quantum 边界定期对齐            │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 6.2 可直接借鉴的四大机制

| 来源机制 | 如何迁移到 RTL 多线程引擎 | 收益 |
|----------|--------------------------|------|
| **SystemC 的 Evaluate-Update 分离** | 多线程 RTL 引擎必须保留：先执行所有进程计算，再统一刷信号值 | 保证 cycle 内确定性 |
| **SCOPE 的分片时间队列** | 每个线程一个 `EQ_timed` + 本地锁，替代全局集中式队列 | 消除锁竞争热点 |
| **TLM-DT 的 Null Message** | 无事件的时钟域定期发送 null message，允许其他域提前推进 | 减少保守同步等待 |
| **parSC 的 Master-Worker 模型** | evaluate 阶段用 barrier 同步多个 worker，update 阶段独立刷值 | 4–8× 加速验证 |

### 6.3 SC_THREAD vs. 轻量回调：RTL 引擎的进程开销启示

```cpp
// RTL 仿真中大量进程是 method-style（每时钟边沿触发一次）
// 多线程 RTL 引擎应优先用轻量级回调而非重协程切换

// ❌ 重协程（类似 SC_THREAD）—— 每次触发都要栈切换
void thread_style_process() {
  while (true) {
    wait(clk.posedge_event());  // 协程挂起/恢复
    output = compute(input);     // 实际逻辑只有一行
  }
}

// ✅ 轻回调（类似 SC_METHOD）—— 函数调用级别开销
void method_style_process() {
  // 由调度器直接调用，无栈切换
  output = compute(input);
}
```

> RTL 多线程引擎中，**进程数量通常是 10⁴–10⁵ 级别**。如果每个进程都是重协程，上下文切换开销将吞噬所有并行收益。应采用轻量回调 + 线程池调度。

---

## 7. 可操作建议：设计混合抽象仿真引擎

### 7.1 架构级建议

```
┌──────────────────────────────────────────────────────────────┐
│              混合抽象仿真引擎参考架构                          │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              顶层调度器 (Top Scheduler)                 │   │
│  │  • 管理全局时间轴                                      │   │
│  │  • 协调 TLM 层与 RTL 层的同步点                        │   │
│  │  • 支持运行时切换抽象层级（SoCRocket 风格）            │   │
│  └────┬─────────────────────────────┬──────────────────┘   │
│       │                             │                        │
│       ▼                             ▼                        │
│  ┌────────────┐              ┌────────────┐                │
│  │  TLM 子系统 │              │  RTL 子系统 │                │
│  │  ┌────────┐│              │  ┌────────┐│                │
│  │  │ Thread ││              │  │ Thread ││                │
│  │  │ Pool   ││              │  │ Pool   ││                │
│  │  │ (乐观) ││              │  │ (保守) ││                │
│  │  └────┬───┘│              │  └────┬───┘│                │
│  │  ┌────┴──┐ │              │  ┌────┴──┐ │                │
│  │  │Temporal│ │              │  │ Delta  │ │                │
│  │  │Decouple│ │              │  │ Cycle  │ │                │
│  │  └────────┘ │              │  │ Engine │ │                │
│  └──────┬──────┘              └──────┬──────┘                │
│         │                          │                       │
│         └──────────┬───────────────┘                       │
│                    │                                       │
│              ┌─────┴─────┐                                 │
│              │ Transactor │  ← 双向翻译 + 量子边界同步        │
│              │  (Bridge) │                                 │
│              └───────────┘                                 │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

### 7.2 具体实施清单

#### 1. 设计混合抽象仿真引擎（支持 TLM + RTL 同平台）

- [ ] 定义统一的模块接口基类，支持 `AbstractionLevel { LT, AT, RTL }` 枚举
- [ ] 同一模块提供三种实现，通过工厂模式在运行时实例化
- [ ] 顶层调度器维护一张「抽象层级映射表」，记录每个模块当前模式

```cpp
enum class AbstractionLevel { LT, AT, RTL };

class SimModule : public sc_module {
public:
  virtual void set_abstraction(AbstractionLevel lvl) = 0;
  virtual AbstractionLevel get_abstraction() const = 0;
};

class MemoryModule : public SimModule {
  AbstractionLevel level;
  std::unique_ptr<MemoryLT> lt_impl;
  std::unique_ptr<MemoryAT> at_impl;
  std::unique_ptr<MemoryRTL> rtl_impl;

public:
  void set_abstraction(AbstractionLevel lvl) override {
    level = lvl;
    // 切换时保存/恢复状态，保持连续性
  }
};
```

#### 2. 用 Temporal Decoupling 减少 TLM/RTL 同步频率

- [ ] 在 TLM initiator 中维护 `local_time`，仅在 quantum 边界同步
- [ ] 推荐 quantum 设置：100 μs–1 ms（取决于 RTL 侧时钟频率）
- [ ] Transactor 中实现「批量事务缓冲」：积累多个 TLM 事务后统一翻译为 RTL 信号 burst

```cpp
// 批量缓冲优化：积累 N 个事务后统一同步
class BufferedTransactor {
  static constexpr size_t BATCH_SIZE = 16;
  std::vector<tlm_generic_payload> pending;

public:
  void b_transport(tlm_generic_payload& trans, sc_time& delay) {
    pending.push_back(trans);
    delay = trans.get_delay();

    if (pending.size() >= BATCH_SIZE || delay >= quantum) {
      flush_to_rtl();  // 一次性翻译所有事务
      pending.clear();
    }
  }
};
```

#### 3. 参考 SystemC-SMP 的线程池模型

- [ ] 采用 Master-Worker 架构：1 个主线程管理状态，N 个 worker 线程执行 evaluate
- [ ] 每个 worker 维护本地就绪队列，evaluate 阶段用 barrier 同步
- [ ] 优先调度 method-style 进程（函数回调），次选 thread-style（协程切换）

```cpp
class ParallelScheduler {
  std::vector<std::thread> workers;
  std::atomic<size_t> barrier_counter{0};
  std::mutex master_mutex;

public:
  void evaluate_phase() {
    // 分发 runnable 进程到 worker 线程
    for (auto& worker : workers) {
      worker.assign_runnable_queue(partition_processes());
    }
    // Barrier 等待所有 worker 完成 evaluate
    barrier_wait(workers.size());
  }

  void update_phase() {
    // 主线程统一执行 update（或并行但无依赖）
    for (auto& channel : update_queue) {
      channel.update();
    }
  }
};
```

#### 4. 支持 Null Message 的跨层时间同步

- [ ] 每个 RTL 线程维护「下一个可能输出事件的时间」
- [ ] 当某线程在 `[T, T+ΔT]` 内无事件时，向其他线程发送 null message `(T+ΔT)`
- [ ] 接收方可以据此将本地安全时间推进到 `T+ΔT`，无需阻塞等待

```cpp
struct NullMessage {
  sc_time safe_time;   // 发送方保证在此之前无事件
  int sender_id;       // 发送线程 ID
};

class RTLThread {
  sc_time next_event_time;  // 下一个事件时间（可能 = ∞）

public:
  void send_null_messages() {
    for (int i = 0; i < num_threads; ++i) {
      if (i == my_id) continue;
      channels[i]->send(NullMessage{next_event_time, my_id});
    }
  }

  sc_time get_safe_time() {
    // 本地安全时间 = min(本地时间, 所有接收到的 null message.safe_time)
    sc_time safe = local_time;
    for (auto& msg : received_nulls) {
      safe = std::min(safe, msg.safe_time);
    }
    return safe;
  }
};
```

---

## 8. 性能数据速查表

| 方案 | 抽象层级 | 仿真速度 | 相对 RTL 加速 | 精度/误差 | 关键机制 |
|------|----------|----------|--------------|----------|----------|
| 纯 TLM-2.0 (LT) | Loosely-Timed | 50,000 txn/s | ~781× | 功能级，无 timing | b_transport + temporal decoupling |
| 纯 TLM-2.0 (AT) | Approximately-Timed | ~5,000 txn/s | ~78× | 协议级 timing | nb_transport 多阶段 |
| TLM-2.0 + RTL 混仿 | Mixed | 64 txn/s | 1× (baseline) | Cycle-accurate | Transactor + DPI/PLI |
| RTL-to-TLM 抽象 (NoC) | 时序+功耗注释 TLM | — | 10–1000× | 功耗误差 < 10% | 自动时序+功耗提取 |
| FAST 框架 | TLM 抽象 | — | 100–1000× | 故障覆盖率等效 | RTL 结构信息抽象 |
| SystemC-SMP (TLM-DT) | TLM 分布式时间 | — | **1.8×** | 消息级 timing | 分布式时间 + null message |
| TLM/T + PDES | TLM + 并行 DES | — | **50× vs BCA** | timing error < 10⁻³ | PDES + SC_THREAD 作为 LP |
| SCOPE | TLM 时间解耦 | — | **4–8×** | 保持 SystemC 语义 | 本地事件队列 + 公平锁 |
| SoCRocket | LT/AT/RTL 混合 | — | **1500× vs RTL** | 近 RTL 精度 | 运行时抽象切换 |

---

## 参考来源

- `source-systemc-kernel` — SystemC 内核调度器、delta-cycle、SCOPE/parSC/SCGPSim 并行化
- `source-tlm-rtl` — TLM-2.0 / RTL 混合仿真、Transactor、RTL-to-TLM 抽象、性能断崖
- `source-cross-layer-parallel` — 跨层并行化、TLM-DT/SystemC-SMP、TLM/T+PDES、SoCRocket、Null Message

---
title: Cross-Layer Parallelization of Multi-Abstraction Simulation
description: 跨抽象层级并行仿真、TLM 与 RTL 并行协同、时间解耦、分层混合信号仿真的学术文献与性能数据汇总
source_url: "https://hal.science/tel-01709813v1/file/main.pdf"
source_type: "paper"  # github-pr, github-issue, blog, doc, paper, competition
author: "Multiple (Viaud et al., Weinstock, Becker, Jones, etc.)"
date: "2004-2018"
tags: ["parallel-simulation", "multi-abstraction", "TLM-RTL", "temporal-decoupling", "PDES", "speedup"]
keywords: ["multi abstraction level parallel", "TLM RTL parallel simulation", "abstraction level speedup", "hierarchical mixed signal simulation", "fast functional RTL simulation"]
capture_date: "2026-07-03"
---

# 跨抽象层级并行化仿真

## 来源

- **URL**: https://hal.science/tel-01709813v1/file/main.pdf
- **类型**: paper (PhD Dissertation)
- **作者**: D. Becker
- **日期**: 2017
- ---
- **URL**: http://publications.rwth-aachen.de/record/728315/files/728315.pdf
- **类型**: paper (PhD Dissertation)
- **作者**: Jan Henrik Weinstock
- **日期**: 2018
- ---
- **URL**: https://matthieu-moy.fr/spip/IMG/pdf/report-2.pdf
- **类型**: paper (M2R Report)
- **作者**: Samuel Jones
- **日期**: 2011
- ---
- **URL**: https://dl.acm.org/doi/full/10.1145/3735641
- **类型**: paper (ACM Survey)
- **作者**: A. Mahmoudi et al.
- **日期**: 2025-06-05
- ---
- **URL**: https://dl.gi.de/server/api/core/bitstreams/db5109a9-9de2-4db1-a54e-f78b44864bae/content#page=297
- **类型**: paper
- **作者**: 多位作者
- **日期**: 2019
- ---
- **URL**: https://upcommons.upc.edu/bitstreams/e29ac6b9-5fa8-4134-9467-b51db6859b70/download
- **类型**: paper
- **作者**: 巴塞罗那理工大学
- **日期**: 2018

## 摘要

跨抽象层级并行化（Cross-Layer Parallelization）的核心问题是：**如何让 TLM 层的高吞吐仿真与 RTL 层的 cycle-accurate 仿真在同一平台上协同工作，并利用多核主机实现加速**。Viaud 等人提出的 **TLM-DT（Transaction Level Modeling with Distributed Time）** 和 **SystemC-SMP** 引擎是关键突破：每个仿真组件拥有本地时间，通过消息传递和 null message 机制避免死锁，在 40 核 MPSoC VP 上实现 **1.8× 加速**。进一步地，TLM/T（带时间的 TLM）结合并行离散事件仿真（PDES）技术，将多个 SystemC SC_THREAD 作为独立 LP（逻辑进程）分布到多核，实现 **50× 加速**（相对于 BCA 仿真）。Weinstock 的 SCOPE 引擎在真实工业 VP 上达到 **4–8× 加速**。这些结果表明，**抽象层级越高，并行化潜力越大**，但 TLM 与 RTL 的混合边界是同步开销最大的位置。

## 关键要点

- **TLM-DT / SystemC-SMP**：Viaud 等人提出 TLM-DT 建模策略，为共享内存 MPSoC 建立通用模型，配合 SystemC-SMP 真正并行引擎。每个处理器不再使用全局 SystemC 仿真时间，而是根据接收到的消息推进本地时间。通过发送 null message（仅含时间戳）防止保守并行死锁。40 处理器 VP 在双核主机上获得 **1.8× 加速**。
- **TLM/T + PDES**：将多集群多处理器 SoC 的 TLM/T 仿真与 PDES 技术结合。每个 SC_THREAD 对应一个 LP，用 timestamped message 通信。在 50× BCA 仿真速度的同时，timing error 低于 **10⁻³**。
- **SCOPE 时间解耦并行**：Weinstock 提出的 SCOPE 引擎使用 ahead-of-time notification 和 cancellation 管理远程事件。每个线程持有本地时间 `t_i` 和锁 `λ_i`，零延迟通知通过 `EQ_timed` 统一处理，用 fair ticket-based spinlock 避免线程饥饿。真实 VP 上达到 **4–8× 加速**。
- **乐观式并行化**：Jones 的方法在 SMP 上运行多个独立调度器，每个调度器有本地时间，不自动同步。通过全局 quantum（最大时间分离上限）和事务级 timing specifiers（`SYNC_WAIT`, `SYNC_CATCH_UP`, `FULL_SYNC`）控制时序正确性。适合 TLM 层 coarse-grain 并行。
- **抽象层级连续谱**：硬件建模从最高（Programmer View untimed）到最低（RTL cycle-accurate）形成一个连续谱。速度提升呈数量级差异：PV 无定时模型最快，RTL 最慢。TLM 层内部也有 LT（loosely-timed）和 AT（approximately-timed）之分，不同抽象层级适用于不同设计阶段。
- **SoCRocket 平台**：ESA 项目衍生的开源框架，支持 LT、AT 和 RTL 的混合连接。通过 runtime 配置切换抽象层级，实现 **1500× 于 RTL 仿真**的速度，同时保持近 RTL 精度，代码量减少 50%。
- **SoC 混合信号仿真**：在包含模拟/混合信号组件的系统中，可以使用连续时间仿真器（如 SPICE）与 SystemC 的离散事件仿真并行运行，通过跨域同步协议交换数据。

## 对 RTL 仿真器多线程化的启示

1. **分层时间推进是 RTL 多线程引擎的可行架构**：低层（RTL）用精确的 delta-cycle 推进，高层（功能/TLM）用时间解耦在多个线程上独立推进，定期通过 quantum 边界同步。这种"异步推进 + 同步点收敛"模式可以大幅减少跨线程同步频率。
2. **Null message 机制可借鉴用于 RTL 多线程**：在保守并行仿真中，如果某个线程的本地时间远超其他线程，需要发送 null message（空时间戳消息）告诉其他线程"我不会在时间 X 之前发送真实事件"，从而解锁对方的等待。RTL 多线程引擎中，无事件的时钟域可以定期发送 null message，允许其他域提前推进。
3. **TLM-DT 的分布式时间模型揭示：全局时间推进是瓶颈**。标准 SystemC 的集中式时间队列在并行化中成为锁竞争热点。SCOPE 的分片时间队列（每个线程一个 `EQ_timed` + 本地锁）是更好的设计，RTL 多线程引擎应采用分片或分布式时间队列。
4. **SoCRocket 的 1500× 加速证明：抽象层级的动态切换是可行且有效的**。RTL 多线程引擎可以设计两种运行模式——Fast Mode（减少内部 timing 检查，类似功能仿真）和 Accurate Mode（完整 delta-cycle 精度），根据验证需求切换。
5. **不同抽象层级对应不同团队需求**：算法团队需要 untimed TLM，软件团队需要 loosely-timed（足够 boot OS），架构团队需要 approximately-timed（吞吐/延迟分析），验证团队需要 RTL。RTL 多线程引擎应支持这种"多视图"仿真，允许同一设计中不同模块运行在不同抽象层级。

## 原文摘录

> "In 2004, Mario Trams proposed a parallel simulation approach for SystemC using lookahead time. This work targets RTL simulations and is not applicable as-is, because it leaves many future work directions. Most of them are addressed by more recent papers."
> — Becker, *Parallel SystemC/TLM Simulation of Hardware* (2017)

> "Viaud et al. proposed a set of modeling rules to describe multi-processor systems on chip at the Transaction Level Modeling (TLM) abstraction level for parallel simulation. The key idea is to distribute the simulated time to each processor of the simulation. Thus, the SystemC simulated time is no longer used. Each component advances its local simulated time depending on messages received from other components."
> — Becker, *Parallel SystemC/TLM Simulation* (2017)

> "First experimental results on a 40 processor MPSoC virtual prototype running on a dual-core workstation demonstrate a 1.8 speedup, versus a sequential simulation."
> — Viaud et al., *SystemC-SMP* (TLM-DT)

> "The goal is to describe the dynamic behavior of a given software application running on a given hardware architecture (including the dynamic contention in the interconnect and the cache effects), in order to provide the system designer with the same reliable timing information as a cycle accurate simulation, with a simulation speed similar to a TLM simulation. The key idea is to apply parallel discrete event simulation (PDES) techniques to a collection of communicating SystemC SC-THREAD. Experimental results show a simulation speedup of a factor up to 50 versus a BCA simulation, for a timing error lower than 10-3."
> — Viaud et al., *TLM/T Parallel DES* (另一篇 Viaud 论文)

> "Their performance gains due to parallel simulation reach 4–8× over the current state-of-the-art implementation of SystemC on modern multi-core host."
> — Weinstock, *Parallel SystemC Simulation for ESL Design* (SCOPE, 2018)

> "We describe an experiment in parallelising SystemC for SMP machines by running multiple schedulers each responsible for a subset of the available SystemC processes. Each scheduler has its own local time and does not synchronise automatically with the others. We provide an interface for specifying coarse-grain and fine-grain timing constraints..."
> — Jones, *Optimistic Parallelisation of SystemC* (2011)

> "SoCRocket... brought a 1500× speed-up compared with RTL simulation with typically reduced description effort (50% of code size for standard accuracy). This resulted in a versatile and powerful environment for design-space exploration and design optimization."
> — Mahmoudi et al., *Systematic Mapping Study on SystemC/TLM* (ACM 2025)

> "Fig. 5: Continuum of abstractions levels between the highest and lowest extremes. Speed-up numbers denote the order of magnitude between the different approaches. RTL models are the most accurate models. TLM models, instead, help to explore the system architecture with the initial software/hardware partition, CPU selection and bus architecture exploration."
> — 多源论文, *HW modelling abstraction levels*

## 跨层并行仿真代码示例

### 1. TLM-DT 分布式时间模型中的 Null Message

```cpp
// S1, S2, S3 是三个独立仿真线程（LP）
// 消息格式: (m, t) = message m with timestamp t

// 潜在死锁场景：
// S1 等待 S2 处理 m' 在时间 20
// S2 等待 S3 处理 m 在时间 10
// S3 等待 S1 保证其时间至少为 10

// 解决方案：S1 发送 null message 给 S3，时间戳 10
// 告诉 S3："我不会在时间 10 之前发送任何真实事件"
// S3 因此可以安全推进到时间 10

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

### 2. 乐观式并行化中的全局 Quantum 约束

```cpp
// Samuel Jones 的乐观式并行化方法
// 设置全局 quantum，限制任意两个调度器之间的时间差

#define SC_AFFINITY(thread, scheduler) \
  sc_set_affinity(thread, scheduler)

void sc_main(int argc, char* argv[]) {
  // 设置全局 quantum：最大允许的时间分离
  sc_set_global_quantum(100, SC_US);

  Producer prod("prod");
  Consumer cons("cons");

  // 将进程绑定到不同调度器
  SC_AFFINITY(prod.run_thread, SCHEDULER_0);
  SC_AFFINITY(cons.run_thread, SCHEDULER_1);

  sc_start();
}

// Producer 线程
void Producer::run_thread() {
  while (true) {
    // 局部时间推进，不需要每次同步
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

### 3. SCOPE 引擎中的时间解耦与锁管理

```cpp
// SCOPE 扩展通知阶段（基于 Figure 6.4）
// 每个线程持有本地时间 t_i 和锁 λ_i

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

### 4. 抽象层级切换的 SoCRocket 风格配置

```cpp
// SoCRocket 支持在运行时切换模块抽象层级
// 同一模块可以有 LT（loosely-timed）、AT（approximately-timed）
// 和 RTL（via wrapper）三种实现

enum AbstractionLevel { LT, AT, RTL };

class MemoryModule : public sc_module {
  AbstractionLevel level;

public:
  tlm_initiator_socket<32, tlm_generic_payload> bus_socket;

  SC_HAS_PROCESS(MemoryModule);
  MemoryModule(sc_module_name nm, AbstractionLevel lvl) : sc_module(nm), level(lvl) {
    switch (level) {
      case LT:
        SC_THREAD(lt_thread);
        break;
      case AT:
        SC_THREAD(at_thread);
        break;
      case RTL:
        // RTL 实例通过 SystemC wrapper 连接
        rtl_wrapper = new MemoryRTL("rtl");
        rtl_wrapper->bus_socket(bus_socket);
        break;
    }
  }

  void lt_thread() {
    // 松散定时：使用 temporal decoupling
    sc_time local_time = SC_ZERO_TIME;
    while (true) {
      tlm_generic_payload trans;
      socket->b_transport(trans, local_time);
      // 大量工作在一个函数调用中完成，减少同步
    }
  }

  void at_thread() {
    // 近似定时：非阻塞传输，多阶段握手
    while (true) {
      tlm_generic_payload trans;
      tlm_phase phase = BEGIN_REQ;
      sc_time delay = SC_ZERO_TIME;
      socket->nb_transport_fw(trans, phase, delay);
      wait(phase_changed_event);  // 等待目标回调
    }
  }
};
```

## 性能数据

| 方案 | 目标系统 | 主机配置 | 加速比 | 精度/误差 | 关键机制 |
|------|----------|----------|--------|----------|----------|
| SystemC-SMP (TLM-DT) | 40 核 MPSoC VP | 双核工作站 | **1.8×** | 消息级 timing | 分布式时间 + null message |
| TLM/T + PDES | 多集群 SoC | 多核 | **50× vs BCA** | timing error < 10⁻³ | PDES + SC_THREAD 作为 LP |
| SCOPE (Weinstock) | 真实 VP (EURETILE/GEMSCLAIM) | 8 核 | **4–8×** | 保持 SystemC 语义 | 时间解耦 + 远程事件队列 |
| Jones 乐观式 | 通用 SoC | 双核 SMP | **1.5–2×** | 用户指定约束 | 多调度器 + 全局 quantum |
| SoCRocket | ESA SoC 平台 | 通用 | **1500× vs RTL** | 近 RTL 精度 | LT/AT/RTL 动态切换 |
| RTL → TLM 抽象 | 通用 IP | 通用 | **10–1000×** | 功耗误差 < 10% | 自动时序+功耗抽象 |
| FAST 框架 | 故障仿真 | 通用 | **100–1000×** | 故障覆盖率等效 | RTL 结构信息抽象 |
| 纯 RTL 仿真 | Gate-level | 单核 | 1× (baseline) | 100% cycle-accurate | — |

## 抽象层级速度对比（数量级）

```
仿真速度（相对 RTL）
  ↑
10^4 │  ┌─ PV (Programmer View, untimed)
     │  │
10^3 │  ├─ TLM-LT (Loosely-Timed) ── SoCRocket 1500×
     │  │
10^2 │  ├─ TLM-AT (Approximately-Timed)
     │  │
10^1 │  ├─ Cycle-Approximate / Bus-Cycle-Accurate
     │  │
 1   │  └─ RTL (Cycle-Accurate) ── baseline
     │
     └──────────────────────────────────────→ 精度
          低                                    高
```

## 相关链接

- [Parallel SystemC/TLM Simulation – Becker PhD (HAL)](https://hal.science/tel-01709813v1/file/main.pdf)
- [Parallel SystemC Simulation for ESL Design – Weinstock (RWTH Aachen)](http://publications.rwth-aachen.de/record/728315/files/728315.pdf)
- [Optimistic Parallelisation of SystemC – Jones (Grenoble)](https://matthieu-moy.fr/spip/IMG/pdf/report-2.pdf)
- [Systematic Mapping Study on SystemC/TLM – ACM 2025](https://dl.acm.org/doi/full/10.1145/3735641)
- [HW Modelling Abstraction Levels – GI Paper](https://dl.gi.de/server/api/core/bitstreams/db5109a9-9de2-4db1-a54e-f78b44864bae/content#page=297)
- [SoC Virtual Prototyping – UPC Barcelona](https://upcommons.upc.edu/bitstreams/e29ac6b9-5fa8-4134-9467-b51db6859b70/download)
- [SystemC Missing Asynchronous Features – DVCon](https://dvcon-proceedings.org/wp-content/uploads/the-missing-systemc-and-tlm-asynchronous-features-enabling-inter-simulation-synchronization.pdf)

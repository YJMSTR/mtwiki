---
title: SystemC Kernel Implementation & Scheduler Internals
description: SystemC 仿真内核调度器、事件通知机制、delta cycle、以及并行化仿真引擎的学术文献与技术资料汇总
source_url: "https://errbits.com/articles/systemc-scheduler-internals.html"
source_type: "doc"  # github-pr, github-issue, blog, doc, paper, competition
author: "Multiple (ErrBits, Accellera, RWTH Aachen, etc.)"
date: "2024-2026"
tags: ["SystemC", "kernel", "scheduler", "DES", "parallel-simulation", "delta-cycle", "event-notification"]
keywords: ["SystemC kernel implementation", "SystemC scheduler", "SystemC event notification", "SystemC simulation engine", "SystemC parallel simulation"]
capture_date: "2026-07-03"
---

# SystemC 内核实现与调度器机制

## 来源

- **URL**: https://errbits.com/articles/systemc-scheduler-internals.html
- **类型**: blog
- **作者**: Aditya Gaurav (ErrBits)
- **日期**: 2026-04-18
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
- **URL**: https://hal.science/tel-01709813v1/file/main.pdf
- **类型**: paper (PhD Dissertation)
- **作者**: D. Becker
- **日期**: 2017
- ---
- **URL**: https://caxapa.ru/thumbs/501417/mahesh_scgpsim.pdf
- **类型**: paper
- **作者**: Mahesh et al.
- **日期**: 2015
- ---
- **URL**: https://singularitykchen.github.io/blog/2020/06/12/SystemC-and-Its-Simulation-Kernel/
- **类型**: blog
- **作者**: SingularityKChen
- **日期**: 2020-06-12

## 摘要

SystemC 内核本质上是一个**基于协程（coroutine）的合作式单线程调度器**。它通过离散事件模拟（DES）算法管理仿真时间推进：所有进程在单个 OS 线程上顺序执行，依靠 `wait()` 主动让出控制权，不存在真正的抢占式多任务。Delta cycle 机制（Evaluate → Update 循环）保证了同一仿真时刻内信号赋值与读取的确定性。并行化方向包括：保守式分区（时间解耦，多调度器同步）、乐观式超前执行（允许时间乱序，事后回滚）、以及 GPU 加速（SCGPSim）。

## 关键要点

- **调度器本质**：不是 OS 调度器，而是单线程 coroutine-based cooperative scheduler。管理的是*模拟并发*，而非真正的物理并行。
- **四状态机**：Initialized → Runnable → Waiting → Terminated。`SC_THREAD` 和 `SC_METHOD` 共享同一调度循环，但 yield 机制不同：thread 靠 `wait()` 挂起栈；method 靠函数返回，无持久栈上下文。
- **Delta Cycle 核心**：同一仿真时刻 `t` 内，Evaluate 阶段执行所有 runnable 进程（一次一个，顺序不确定），Update 阶段将 `new_value` 刷入 `current_value`，然后检查是否触发新的 delta 通知。循环直到无 pending 事件，才推进到下一个时间戳。
- **事件通知三队列**：`EQ_imm`（即时通知）、`EQ_delta`（零延迟通知）、`EQ_timed`（定时通知）。所有远程通知（包括零延迟）在 SCOPE 并行内核中内部统一为 timed 通知，需用 mutex 保护。
- **并行化瓶颈**：标准 SystemC 的集中式调度器是性能瓶颈。Weinstock 的 SCOPE 引擎在真实 VP 上达到 **4–8× 加速**；Jones 的乐观式并行化在 SMP 机器上运行多个独立调度器，用全局 quantum 和事务级 timing specifiers 约束时序正确性；Schumacher 的 parSC 使用 master-worker 模型，在 evaluation 阶段用 barrier 同步多个 worker 线程。
- **GPU 加速**：SCGPSim 将 SystemC 内核映射到 GPU，利用 CUDA 线程并行执行 runnable 进程，缓解了 CPU 上单线程调度器的瓶颈。

## 对 RTL 仿真器多线程化的启示

1. **Evaluate-Update 分离是 RTL 仿真的核心结构**：任何多线程 RTL 引擎必须保留这一语义——先执行所有进程的计算逻辑，再统一更新信号值。这正是 SystemC delta cycle 与 Verilog 非阻塞赋值的共同基础。
2. **合作式调度可安全转化为分区并行**：如果不同进程集合之间没有共享变量（或仅有通过 channel 的通信），可以将它们分配到不同线程/核心，在每个 evaluate 阶段用 barrier 同步。parSC 和 SCOPE 已验证此路径可行。
3. **事件队列的并发访问是锁竞争热点**：`EQ_timed` 的插入/弹出在并行化时必须加锁。未来 RTL 多线程引擎需要设计无锁或分片时间队列，避免集中式锁瓶颈。
4. **SC_THREAD 的 coroutine 开销 vs SC_METHOD 的函数调用开销**：RTL 仿真中大量进程本质上是 method-style（每个时钟边沿触发一次）。这提示多线程 RTL 引擎应优先用轻量级回调而非重协程切换。
5. **Temporal decoupling 思想可迁移到 RTL**：在 RTL 混合 TLM 验证平台中，纯 TLM 部分可以用时间解耦跑在前面，RTL 部分按 cycle 精度推进，定期同步。这样可减少跨抽象层同步频率。

## 原文摘录

> "The SystemC scheduler is not an operating system scheduler. It does not preempt processes, does not assign time slices, and does not run on multiple threads (single-threaded by default). It is a **coroutine-based cooperative scheduler** built entirely inside a single OS thread."
> — ErrBits, *SystemC Scheduler Internals*

> "Algorithm 2.1: SystemC simulation algorithm.
> 1: Initialisation Phase: Execute all processes in an unspecified order.
> 2: Evaluate Phase (EPh): Select a process that is ready to run and resume its execution.
> 3: If there are still processes ready to run, go to EPh.
> 4: Update Phase: Execute any pending calls to update().
> 5: If there are pending delayed notifications, determine which processes are ready to run and go to EPh.
> 6: If there are no more timed notifications, simulation is finished.
> 7: Advance the current simulation time to the earliest pending timed notification."
> — SystemC-A: Analogue and Mixed-Signal Language

> "Each thread i holds a mutex λ_i for this purpose. Conceptually, holding λ_i grants the owner the ability to insert events and remote events into EQ_timed. Furthermore, any thread can prevent thread i from advancing its local time t_i by acquiring λ_i."
> — Weinstock, *Parallel SystemC Simulation for ESL Design* (SCOPE)

> "A parallel SystemC kernel called parSC has been proposed by Schumacher et al. ... There is one master thread, that manages the states of the simulation, and several worker threads. Each worker thread runs transitions during an evaluation step. A synchronization barrier is done at the end of each evaluation step."
> — Becker PhD thesis, *Parallel SystemC/TLM Simulation*

> "While this approach works perfectly fine for a single-core processor, it does not scale and take advantage of multi-core/multi-processor environment."
> — SCGPSim paper, *A Fast SystemC Simulator on GPUs*

## SystemC 调度器代码示例

### 1. 基本 SC_THREAD 进程（初始化 + 主循环）

```cpp
SC_HAS_PROCESS(Producer);

Producer(sc_module_name n) : sc_module(n) {
  SC_THREAD(run);
}

void run() {
  // ── 初始化阶段（在第一个 wait() 前执行）──
  out.write(false);
  count = 0;

  wait(5, SC_NS);  // ← 第一个 wait，初始化结束

  // ── 主仿真循环 ──
  while (true) {
    wait(clk.posedge_event());
    out.write(!out.read());
    count++;
  }
}
```

### 2. 事件驱动工作线程（SC_THREAD + SC_METHOD 协作）

```cpp
SC_MODULE(encode) {
  sc_in<bool> m_in;
  sc_event worker_event;

  SC_CTOR(encode) {
    SC_METHOD(int_handler);
    sensitive << m_in.pos_edge();
    SC_THREAD(worker);
  }

  void int_handler() {
    worker_event.notify();  // 即时通知
  }

  void worker() {
    while (true) {
      wait(worker_event);   // 等待事件唤醒
      work();                // 执行工作负载
    }
  }
};
```

### 3. 调度器伪代码（完整 Evaluate-Update 循环）

```cpp
// sc_start() 伪代码 —— 简化但准确
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
      p = runnable_queue.pick_one();  // 顺序未指定
      p.resume();                      // 运行到 wait() 或 return
    }
    // ── Update Phase ──
    for each channel c in update_queue:
      c.update();                      // new_value → current_value
      if value_changed:
        runnable_queue.add(c.sensitive_processes);
    update_queue.clear();
  }
}
```

### 4. SCOPE 并行内核中的远程事件触发算法

```cpp
// Algorithm 5.2: Trigger decision for remote events
Function TRIGGERDecision(RemoteEvent e)
  requests ← H_e[t_e ... t_i - Δt_la];  // 提取相关历史
  t_act ← ∞;                           // 假设事件未激活
  while requests ≠ ∅ do
    r ← extract earliest from requests;
    if r is cancel then
      t_act ← ∞;                       // 远程取消
    else if t_r < t_act then
      t_act ← t_r;                     // 远程通知覆盖
    end
  end
  if t_act == t_i then
    RQ ← RQ ∪ S_e ∪ D_e;               // 触发事件
    D_e ← ∅;
    t_e ← t_i;
  end
End
```

## 性能数据

| 方案 | 平台 | 核心数 | 加速比 | 备注 |
|------|------|--------|--------|------|
| SCOPE (Weinstock) | 真实 VP (EURETILE/GEMSCLAIM) | 8 | **4–8×** | 时间解耦并行 DES |
| parSC (Schumacher) | 通用 SystemC 模型 | 4–8 | 良好（含超线性） | 保守式 barrier 同步 |
| SCGPSim | NVIDIA GPU | 数百 CUDA cores | 显著加速 | 将内核映射到 GPU |
| Jones 乐观式 | 双核 SMP | 2 | 1.5–2× | 全局 quantum 约束 |
| SystemC-SMP (Viaud) | 40 核 MPSoC VP | 2 | 1.8× | TLM-DT 分布式时间 |

## 相关链接

- [SystemC Scheduler Internals – ErrBits](https://errbits.com/articles/systemc-scheduler-internals.html)
- [Accellera Forum: SystemC Simulation Kernel Scheduling](https://forums.accellera.org/topic/1216-systemc-simulation-kernel-scheduling/)
- [SystemC and Its Simulation Kernel – SingularityKChen](https://singularitykchen.github.io/blog/2020/06/12/SystemC-and-Its-Simulation-Kernel/)
- [Parallel SystemC Simulation for ESL Design (SCOPE) – RWTH Aachen](http://publications.rwth-aachen.de/record/728315/files/728315.pdf)
- [Optimistic Parallelisation of SystemC – Samuel Jones](https://matthieu-moy.fr/spip/IMG/pdf/report-2.pdf)
- [SCGPSim: A Fast SystemC Simulator on GPUs](https://caxapa.ru/thumbs/501417/mahesh_scgpsim.pdf)
- [SystemC-A: Analogue and Mixed-Signal Language](https://eprints.soton.ac.uk/465861/1/1011934.pdf)

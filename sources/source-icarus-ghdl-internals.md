---
title: "Icarus Verilog / GHDL 内核实现分析：仿真循环、事件调度与值存储"
description: 对 steveicarus/iverilog 和 ghdl/ghdl 两个开源仿真器的核心内核实现进行代码级分析，重点关注事件调度策略、值存储结构和仿真循环机制，为 RTL 仿真器多线程化提供对比基准。
source_url: "https://github.com/steveicarus/iverilog"
source_type: github-repo
author: "Stephen Williams / Tristan Gingold"
date: "2026-07-03"
tags: [iverilog, ghdl, event-scheduler, simulation-kernel, vvp, vhdl]
keywords: [iverilog, ghdl, event queue, stratified event, vthread, delta cycle, signal driver, transaction]
capture_date: "2026-07-03"
---

# Icarus Verilog / GHDL 内核实现分析

## 来源

- Icarus Verilog: `https://github.com/steveicarus/iverilog`
- GHDL: `https://github.com/ghdl/ghdl`
- 类型: github-repo
- 作者: Stephen Williams (Icarus) / Tristan Gingold (GHDL)
- 日期: 2026-07-03

## 摘要

本文档通过直接阅读两个开源仿真器的核心源码，提取了 Icarus Verilog 的 VVP 运行时事件调度器（`vvp/schedule.cc`）、值存储系统（`vvp/vvp_net.h`）以及 GHDL 的 GRT（GHDL Run Time）进程调度与信号传播系统（`src/grt/grt-processes.adb`、`src/grt/grt-signals.adb`）的关键实现细节。两者分别代表了 Verilog 事件驱动（event-driven）和 VHDL 基于进程/增量更新（process-based/delta-cycle）的两种经典仿真内核范式。

## 关键要点

### 1. Icarus Verilog — 分层事件队列（Stratified Event Queue）

**文件**: `vvp/schedule.cc` ([GitHub](https://github.com/steveicarus/iverilog/blob/master/vvp/schedule.cc))

Icarus Verilog 的 VVP 运行时实现了严格的 IEEE 1364 分层事件队列。核心数据结构如下：

```cpp
// vvp/schedule.cc
struct event_time_s {
      vvp_time64_t delay;
      struct event_s*start;      // T0 开始事件
      struct event_s*active;     // Active 事件
      struct event_s*inactive;   // Inactive 事件
      struct event_s*nbassign;    // Non-blocking assign
      struct event_s*rwsync;     // Read-write sync
      struct event_s*rosync;     // Read-only sync
      struct event_s*del_thr;     // 待删除线程
      struct event_time_s*next;  // 下一时间步
};

struct event_s {
      struct event_s*next;
      virtual void run_run(void) =0;
      // ...
};
```

每个时间步（`event_time_s`）内部包含 **7 个事件子队列**，按 `active → inactive → nbassign → rwsync → rosync` 的顺序依次执行。这种设计直接对应 Verilog 的 "stratified event queue" 语义，确保了非阻塞赋值（NBA）在 active 事件之后执行，read-only sync 在最后执行。

事件调度器的主循环（`schedule_simulate`）如下：

```cpp
// vvp/schedule.cc : schedule_simulate()
if (schedule_runnable) while (sched_list) {
      struct event_time_s* ctim = sched_list;
      if (ctim->delay > 0) {
            schedule_time += ctim->delay;
            ctim->delay = 0;
            // 处理 cbAtStartOfSimTime 回调
            while (ctim->start) { ... }
      }
      // 按优先级轮转队列
      if (ctim->active == 0) {
            ctim->active = ctim->inactive;
            ctim->inactive = 0;
            if (ctim->active == 0) {
                  ctim->active = ctim->nbassign;
                  ctim->nbassign = 0;
                  // ... 继续轮转 rwsync, rosync
            }
      }
      // 取出并执行单个事件
      struct event_s*cur = ctim->active->next;
      cur->run_run();
      delete (cur);
}
```

**关键观察**：
- **全局单线程**：整个 `schedule_simulate` 是一个巨大的 while 循环，事件按严格顺序串行执行。
- ** slab 分配器**：高频事件（`vthread_event_s`、`assign_vector4_event_s` 等）使用自定义 `slab_t` 分配器，避免 `malloc` 开销。
- **线程模型**：VVP 中的 "thread"（`vthread_t`）是**协作式软线程**（用户态状态机），不是 OS 线程，通过 `vthread_run()` 逐个执行。

### 2. Icarus Verilog — 值存储与网络传播（vvp_net）

**文件**: `vvp/vvp_net.h` ([GitHub](https://github.com/steveicarus/iverilog/blob/master/vvp/vvp_net.h))

VVP 使用 `vvp_vector4_t` 存储四值逻辑（0, 1, X, Z），采用 **双位分离存储**（split abits/bbits）：

```cpp
// vvp/vvp_net.h
class vvp_vector4_t {
      unsigned size_;
      union {
            unsigned long abits_val_;  // 小向量内联存储
            unsigned long*abits_ptr_; // 大向量堆分配
      };
      union {
            unsigned long bbits_val_;
            unsigned long*bbits_ptr_;
      };
      // 编码: abit=0, bbit=0 → 0; abit=1,bbit=0 → 1; abit=1,bbit=1 → X; abit=0,bbit=1 → Z
};
```

网络节点 `vvp_net_t` 是一个**固定 4 输入、无限输出的 fan-in 结构**：

```cpp
// vvp/vvp_net.h
class vvp_net_t {
      vvp_net_ptr_t port[4];   // 4 个输入端口
      vvp_net_fun_t*fun;        // 计算逻辑（与门、或门、触发器等）
      vvp_net_fil_t*fil;        // 输出过滤器（force/release 语义）
      vvp_net_ptr_t out_;      // 输出链（链表形式实现无限 fan-out）
      // ...
};
```

值传播通过 `vvp_send_vec4()` 沿着输出链表递归触发下游节点的 `recv_vec4()` 方法，形成**深度递归的波形传播链**。这种设计在复杂组合逻辑深度较大时可能引发栈深度问题，且所有传播发生在同一线程中，天然难以并行化。

### 3. GHDL — 基于进程的 Delta-Cycle 仿真循环

**文件**: `src/grt/grt-processes.adb` ([GitHub](https://github.com/ghdl/ghdl/blob/master/src/grt/grt-processes.adb))

GHDL 的 GRT 内核严格遵循 VHDL LRM 的 delta-cycle 语义。`Simulation_Cycle` 函数实现了标准仿真循环：

```ada
-- src/grt/grt-processes.adb
function Simulation_Cycle return Integer is
   --  a) 模拟时间推进到 Tn
   Current_Time := Next_Time;
   --  b) 调用回调（如 VPI）
   if Current_Delta = 0 then Call_Callbacks (Hooks.Cb_Next_Time_Step); end if;
   --  c) 更新信号（驱动器 → 有效值）
   Update_Signals;
   --  d) 恢复超时进程
   if Current_Time = Process_First_Timeout then ... Resume_Process ... end if;
   --  e) 运行非延迟进程
   Status := Run_Processes (Postponed => False);
   --  f) 计算下一个时间 Tn
   Tn := Compute_Next_Time;
   --  g) 若为 delta 周期则递增计数
   if Tn = Current_Time then Current_Delta := Current_Delta + 1; ...
```

**关键观察**：
- **进程恢复表**：`Resume_Process_Table` 和 `Postponed_Resume_Process_Table` 分别存储当前 delta 周期需要执行的普通进程和延迟进程。
- **多线程执行**：GHDL 支持 `--threads=N` 选项，在 `Run_Processes` 中通过 `Threads.Run_Parallel` 将进程恢复表分发给多个 OS 线程执行：

```ada
-- src/grt/grt-processes.adb : Run_Processes
if Options.Nbr_Threads = 1 then
      for I in 1 .. Last loop
            Proc.Subprg.all (Proc.This);  -- 串行执行
      end loop;
else
      Mt_Last := Last;
      Mt_Table := Table;
      Mt_Index := 1;
      Threads.Run_Parallel (Run_Processes_Threads'Access);  -- 并行执行
end if;
```

这是少数几个**原生支持多线程进程执行**的开源 RTL 仿真器之一。不过，`Update_Signals` 和进程调度本身仍然是单线程的，并行化仅限于 "执行 resumed 进程的主体代码" 阶段。

### 4. GHDL — 信号事务与驱动器模型

**文件**: `src/grt/grt-signals.adb` ([GitHub](https://github.com/ghdl/ghdl/blob/master/src/grt/grt-signals.adb))

GHDL 的信号系统基于**事务链表（Transaction Chain）**和**驱动器（Driver）**模型。每个信号维护一个驱动器数组，每个驱动器包含一个事务链表：

```ada
-- src/grt/grt-signals.adb
type Driver_Type is record
      First_Trans : Transaction_Acc;  -- 头事务（当前值）
      Last_Trans  : Transaction_Acc;  -- 尾事务（最新调度）
      Proc        : Process_Acc;      -- 所属进程
end record;

type Transaction is record
      Kind : Transaction_Kind;  -- Trans_Value, Trans_Null, Trans_Direct, Trans_Error
      Time : Std_Time;          -- 调度时间
      Next : Transaction_Acc;
      Val  : Value_Union;       -- 值（多态联合）
end record;
```

信号更新时，GHDL 使用 **Active Chain** 和 **Future List** 来跟踪需要在下一 delta 周期或未来时间更新的信号：

```ada
-- 活动信号链（下一 delta 周期需要更新）
Signal_Active_Chain : Ghdl_Signal_Ptr;
-- 未来事务列表（未来时间步需要更新）
Future_List : Ghdl_Signal_Ptr;
```

`Update_Signals` 按**信号依赖顺序**（通过 `Order_All_Signals` 预先计算的拓扑序）逐个更新信号有效值，并触发敏感进程。这种**预先排序 + 串行更新**的方式与多线程化存在结构性冲突：信号更新顺序必须严格遵循依赖拓扑，否则会产生竞争条件。

## 对 RTL 仿真器多线程化的启示

1. **事件队列 vs. 进程表**：Icarus 的 stratified event queue 是高度顺序化的数据结构，每个事件可能触发新事件，导致并行化困难。相比之下，GHDL 的 "resume process table" 在单个 delta 周期内是可并行化的（因为进程执行期间不直接修改共享信号，而是通过事务链表延后到 `Update_Signals` 阶段）。

2. **值存储的共享状态**：VVP 的 `vvp_net_t` 网络是全局共享的可变图结构，任何节点的 `recv_vec4` 都可能递归修改下游节点，这构成了多线程化的主要障碍。GHDL 的信号值虽然也是共享的，但通过 "事务调度 → 批量更新" 的两阶段协议，将 "并行计算" 和 "串行提交" 分离开，这是值得借鉴的模型。

3. **GHDL 的既有经验**：GHDL 已经实现了 `Run_Processes` 的多线程化，但加速比受限于 `Update_Signals` 的单线程瓶颈。对于我们的多线程 RTL 仿真器项目，这意味着：
   - **进程/线程级并行**是可行的，但需要一个明确的 "同步屏障" 来分隔 "并行计算阶段" 和 "串行更新阶段"。
   - **信号/网络更新顺序**需要静态分析（如 GHDL 的 `Order_All_Signals`）来预先确定，避免运行时动态调度带来的竞争。

## 原文摘录

> "The event_s and event_time_s structures implement the Verilog stratified event queue. The event_time_s objects are one per time step. Each time step in turn contains a list of event_s objects that are the actual events."
> — `vvp/schedule.cc`, Icarus Verilog

> "A simulation cycle consists of the following steps: a) The current time, Tc is set equal to Tn... d) Each signal on each net in the model that includes active drivers is updated in an order that is consistent with the dependency relation between signals..."
> — `src/grt/grt-processes.adb`, GHDL (注释引用 LRM 14.7.5.3)

> "Note: there is no real locks, since the kernel is single threading. Multi lock is allowed, and rules are just checked."
> — `src/grt/grt-processes.adb`, GHDL 关于 protected object 的注释

## 性能数据

| 指标 | Icarus Verilog | GHDL |
|------|---------------|------|
| 事件调度结构 | 分层 7 队列 + 时间步链表 | Delta-cycle + 事务链表 |
| 进程/线程模型 | 协作式软线程（vthread） | OS 线程（Ada Tasks）可选 |
| 多线程支持 | 无 | `--threads=N`（进程级并行） |
| 值存储 | 4-value abits/bbits（内联/堆） | 多态 Value_Union（按类型分派） |
| 信号更新 | 即时递归传播（vvp_send_vec4） | 两阶段：事务调度 + 批量更新 |
| 内存分配策略 | slab 分配器（高频事件） | 显式分配 + 事务回收链表 |

## 相关链接

- [Icarus Verilog GitHub](https://github.com/steveicarus/iverilog)
- [GHDL GitHub](https://github.com/ghdl/ghdl)
- [VVP 开发者文档](https://github.com/steveicarus/iverilog/blob/master/Documentation/developer/guide/vvp/vvp.rst)
- [GHDL 综合文档](https://github.com/ghdl/ghdl/blob/master/doc/using/Synthesis.rst)

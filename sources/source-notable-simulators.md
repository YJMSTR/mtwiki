---
title: "其他值得关注的仿真器多线程/并行实现：Icarus Verilog、ngspice、GHDL 等"
description: "对非 Verilator 类开源仿真器的多线程与架构现状进行调研，包括 Icarus Verilog 的事件驱动单线程模型、ngspice 的共享库并行分区方案、GHDL 的 LLVM JIT 实验等"
source_url: "https://github.com/steveicarus/iverilog / https://github.com/ngspice/ngspice"
source_type: "github-repo"
author: "Stephen Williams / Holger Vogt / 各社区"
date: "2024-2025"
tags: ["iverilog", "ngspice", "ghdl", "parallel", "event-driven", "circuit-simulation", "spice"]
keywords: ["vvp", "shared-ngspice", "parallel-simulation", "event-queue", "mixed-signal"]
capture_date: "2025-07-20"
---

# 其他值得关注的仿真器多线程/并行实现

## 来源

- **Icarus Verilog**: https://github.com/steveicarus/iverilog
- **ngspice**: https://github.com/ngspice/ngspice
- **GHDL**: https://github.com/ghdl/ghdl
- **类型**: GitHub 开源仓库 + 官方文档
- **作者**: Stephen Williams (Icarus), Holger Vogt 等 (ngspice), Tristan Gingold (GHDL)
- **日期**: 2024-2025 活跃

## 摘要

并非所有 RTL/电路仿真器都采用 Verilator 式的 "编译为 C++ 多线程模型" 路线。本分析覆盖三类代表性开源仿真器：

1. **Icarus Verilog (iverilog)**：经典的事件驱动解释型仿真器，编译器 (`iverilog`) 生成 vvp 字节码，由 `vvp` 运行时解释执行。其多线程支持极为有限，vvp 核心基本单线程，但具有教育意义的简洁事件队列实现；
2. **ngspice**：基于 Berkeley SPICE3 的混合信号/混合层级电路仿真器，通过 **shared library API** 支持 "多实例 + 回调同步" 的粗粒度并行，用于电路分区仿真；
3. **GHDL**：VHDL 仿真器，支持 LLVM JIT 编译和实验性多进程（multiprocessing）模式，代表了解释型 HDL 仿真器向编译型加速演进的另一条路径。

这些项目虽然未像 Verilator 那样实现细粒度多线程 RTL 模型，但它们的架构取舍、事件调度、以及针对模拟/混合信号场景的并行策略，对设计一个通用 RTL 仿真器框架仍有重要参考价值。

## 关键要点

### 1. Icarus Verilog：事件驱动单线程经典

#### 架构概述

Icarus Verilog 不是传统意义上的 "仿真器"，而是一个 **编译器 + 虚拟机** 组合：
- `iverilog`：将 Verilog 编译为 vvp 汇编/字节码；
- `vvp`：加载并解释执行 vvp 字节码，维护事件队列和信号状态。

```
iverilog hello.v -> 生成 a.out (vvp 字节码)
vvp a.out         -> 解释执行
```

根据 GitHub Issue #495 的开发者回复：

> "iverilog is the compiler, which is a single-threaded application. The simulator run-time, vvp, is mostly single-threaded too, although it will use a second thread in some contexts."

这说明即使编译器阶段也完全是单线程，而运行时 vvp 仅在特定上下文（如某些 VPI 调用或 I/O 操作）中可能用到第二个线程。

#### 事件队列机制

vvp 采用经典 Verilog 事件队列模型：
- 事件按时间戳排序；
- 每个时间步包含多个区域（active, inactive, NBA -- Non-Blocking Assignment）；
- 主循环从队列中取出最早事件，更新信号，计算新事件，插回队列。

```
初始化阶段
  -> 设置仿真时间、初始信号值、模块状态
  -> 创建事件队列

仿真主循环
  -> 提取最早事件
  -> 更新信号值
  -> 计算输出/新事件
  -> 将新事件插回队列
  -> 处理同时间戳的并发事件

结束阶段
  -> 监控队列直到仿真结束或到达预设时间
```

> 这是教科书级别的标准事件驱动架构。它的简洁性使其成为教育和小规模验证的利器，但也意味着很难向多线程扩展——事件队列的严格顺序性和 NBA 语义天然要求集中式调度。

#### 多线程的缺失与启示

Icarus Verilog 明确没有实现多线程 vvp 执行。原因包括：
1. **事件队列全局串行**：Verilog 语义要求在同一时间戳内按特定顺序处理事件，全局队列难以无损并行化；
2. **解释执行开销低**：vvp 字节码是中间形式，没有编译为机器码，单线程性能已受限于解释器本身，多线程收益不明显；
3. **设计定位**：作为 "编译器生成后端工具可用代码"，重点在于语言覆盖和标准兼容，而非极致性能。

> **启示**：如果我们的仿真器需要支持标准 Verilog 的事件语义，事件队列的并行化是一个根本性难题。可能的妥协方向是：像 Verilator 那样放弃部分动态事件语义，换取编译期优化；或者采用 "时间分片 + 周期精确" 的抽象层级来规避事件队列。

---

### 2. ngspice：共享库 + 分区并行的混合信号方案

#### 项目背景

ngspice 是 Berkeley SPICE3f5、Cider1b1 和 Xspice 的合并后继，支持：
- 纯模拟电路仿真（SPICE 网表）；
- 混合层级仿真（Cider 设备级 + 电路级）；
- 混合信号仿真（Xspice 数字事件驱动 + 模拟）；
- Verilog-A 紧凑模型（通过 OpenVAF）。

#### 多线程方案：Shared Library + 外部同步

ngspice 本身的核心求解器（矩阵求解、牛顿迭代）并未实现内部多线程，但它提供了一种独特的 **粗粒度并行** 方案：将 ngspice 编译为共享库 (`.so`/`.dll`)，由外部主控程序加载多个实例，每个实例运行一个电路分区。

```c
// src/include/ngspice/sharedspice.h
/* 初始化回调接口 */
IMPEXP
int ngSpice_Init(SendChar* printfcn, SendStat* statfcn, ControlledExit* ngexit,
                 SendData* sdata, SendInitData* sinitdata, 
                 BGThreadRunning* bgtrun, void* userData);

/* 同步回调：请求外部提供电压源值 */
typedef int (GetVSRCData)(double* return_voltage, double actual_time, 
                          char* node_name, int lib_id, void* userData);

/* 同步回调：请求外部提供时间步长控制 */
typedef int (GetSyncData)(double actual_time, double* delta_time, 
                          double old_delta, int redostep, 
                          int lib_id, int call_location, void* userData);

IMPEXP
int ngSpice_Init_Sync(GetVSRCData *vsrcdat, GetISRCData *isrcdat, 
                      GetSyncData *syncdat, int *ident, void *userData);
```

> 这一设计的核心思想是：**仿真器本身不处理并行，而是将并行责任交给外部主控**。主控程序通过 `GetSyncData` 回调同步多个 ngspice 实例的仿真进度，并通过 `GetVSRCData`/`GetISRCData` 在分区边界交换电压/电流数据。

#### 并行工作流程

```
外部主控程序
  -> 加载 ngspice.so 实例 A（电路分区 1）
  -> 加载 ngspice.so 实例 B（电路分区 2）
  -> 加载 ngspice.so 实例 C（电路分区 3）

每个实例独立线程运行
  -> 各自执行瞬态分析（TRAN）
  -> 在每个时间步通过 GetSyncData 回调请求同步
  -> 主控决定全局时间步长，回传给各实例

数据交换
  -> 实例 A 的边界节点电压通过 GetVSRCData 提供给实例 B
  -> 实例 B 的边界电流通过 GetISRCData 反馈给实例 A
```

官方文档描述：

> "A master program loads several ngspice library instances, and starts an individual ngspice thread in each instance. You have to divide your circuit into partitions and define their interconnections. Each ngspice thread loads one circuit partition and runs its simulation. The simulation progress is synchronized via a callback function, voltage or current data are exchanged according to the interface definition in another callback function."

#### 与 Verilator 的对比

| 维度 | ngspice | Verilator |
|------|---------|-----------|
| 并行粒度 | 粗粒度（电路分区级别） | 细粒度（MTask 级别） |
| 并行控制 | 外部主控 + 回调同步 | 编译期静态调度 |
| 适用场景 | 模拟/混合信号电路 | 数字 RTL |
| 线程安全 | 实例间完全隔离 | 共享模型状态，需处理数据竞争 |
| 扩展性 | 受分区质量限制 | 受临界路径限制 |

> **启示**：ngspice 的 "实例隔离 + 外部同步" 模式是模拟电路仿真的务实选择。模拟电路的矩阵求解是强耦合的，内部分线程并行化难度远高于数字逻辑。若我们的仿真器需要支持混合信号（analog + digital），可能需要同时支持两种并行模式：数字部分的 MTask 细粒度并行 + 模拟部分的实例级粗粒度并行。

#### KLU 矩阵求解器

ngspice-42 引入 KLU 矩阵求解器（替代老旧的 Sparse 1.3），大型电路加速 1.5~3 倍：

> "With KLU simulation speed-up by 1.5 to 3 for large circuits" —— ngspice FOSDEM 2024 幻灯片

这是单线程层面的算法优化，与多线程并行是正交的。

---

### 3. GHDL：VHDL 仿真器的 LLVM JIT 实验

#### 项目简介

GHDL 是完整的 VHDL 仿真器，支持：
- 解释执行（mcode 后端）；
- 编译为 C 代码后执行；
- 实验性 LLVM JIT 后端。

#### 多进程实验

GHDL 在实验分支中探索了 **multiprocessing** 模式，通过将 VHDL 进程映射到 OS 进程/线程来并行化。与 Verilator 的 MTask 不同，GHDL 的并行单元是 VHDL 语言层面的 `process`：

- 每个 VHDL process 是独立执行的逻辑单元；
- 进程间通过信号（signal）通信，天然具有显式依赖；
- 进程触发的条件是敏感列表或 wait 语句，可以被静态分析。

> 然而，VHDL 的 delta cycle 语义要求在同一仿真时刻内反复执行进程直到信号稳定，这导致了类似于 Verilog 事件队列的同步问题。GHDL 的多进程实验目前主要用于特定场景（如独立测试平台的并行执行），而非通用 RTL 模型加速。

---

### 4. 其他值得关注的项目

#### 4.1 EpicSim / EpicSim Verilog

EpicSim 是一个较新的开源 Verilog 仿真器项目，目标是提供一个现代、可扩展的仿真平台。其架构特点包括：
- 基于 C++ 的现代代码库；
- 事件驱动 + 周期精确的混合执行模式；
- 计划中的多线程支持（当前版本主要为单线程）。

由于项目相对年轻，多线程实现尚未成熟，但值得持续跟踪其架构演进。

#### 4.2 XspiceHDL / 混合信号仿真器

XspiceHDL 是 SPICE 和 Verilog 的混合信号仿真器，代表了另一类并行需求：
- 数字部分用 Verilog 事件驱动；
- 模拟部分用 SPICE 矩阵求解；
- 两者通过混合信号接口（MSI）耦合。

ngspice 本身已支持通过 Verilator 进行数字 Verilog 协同仿真：

> "Co-simulation ngspice mixed-signal-Verilog digital... Only two commands required: ngspice vlnggen adc.v; compile with Verilator, gcc; ngspice adc.cir run simulation" —— ngspice 文档

这说明在实际工程中，**数字部分用 Verilator 编译加速 + 模拟部分用 ngspice 分区并行** 的异构组合是可行的工程路径。

## 对 RTL 仿真器多线程化的启示

1. **事件驱动 vs 周期精确**：Icarus Verilog 的纯事件驱动模型难以并行，而 Verilator 的周期精确模型天然适合 MTask 分区。如果我们的仿真器需要支持两者，可能需要内部维护两套执行引擎。

2. **模拟电路的并行瓶颈**：ngspice 没有选择内部分线程，因为 SPICE 的矩阵求解是全局耦合的。这提醒我们：并行化的收益取决于问题的数学结构，数字逻辑的局部性远优于模拟电路。

3. **外部主控模式**：ngspice 的 shared library + callback 模式是一种 "反过来的架构"——仿真器作为库被外部框架调度。如果我们的目标是构建一个可嵌入的仿真引擎，这种设计可能比 "仿真器作为主程序" 更灵活。

4. **LLVM JIT 的潜力**：GHDL 的 LLVM 后端展示了编译型加速的另一条路径。对于频繁仿真的回归测试，JIT 编译可能比传统的 "Verilate -> 编译 C++ -> 链接" 流程更快迭代。

## 原文摘录

> "iverilog is the compiler, which is a single-threaded application. The simulator run-time, vvp, is mostly single-threaded too, although it will use a second thread in some contexts."
> —— GitHub Issue #495, steveicarus/iverilog

> "A master program loads several ngspice library instances, and starts an individual ngspice thread in each instance. You have to divide your circuit into partitions and define their interconnections."
> —— ngspice Parallel Simulation 文档

> "The shared ngspice option introduces the capability to run several ngspice invocations in parallel in individual threads, with their simulation progress synchronized, including the exchange of current or voltage data between the different threads."
> —— ngspice Shared Library 文档

> "With KLU simulation speed-up by 1.5 to 3 for large circuits."
> —— ngspice FOSDEM 2024 幻灯片

## 相关链接

- [Icarus Verilog GitHub](https://github.com/steveicarus/iverilog)
- [ngspice Parallel Simulation](https://ngspice.sourceforge.io/parallel.html)
- [ngspice Shared Library API](https://ngspice.sourceforge.io/shared.html)
- [GHDL GitHub](https://github.com/ghdl/ghdl)
- [ngspice FOSDEM 2024 幻灯片](https://archive.fosdem.org/2024/events/attachments/fosdem-2024-2834-ngspice-circuit-simulator-stand-alone-and-embedded-into-kicad/slides/22676/ngspice-HolgerVogt_tEfhemB.pdf)

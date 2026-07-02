---
title: Multi-Clock & Asynchronous Design Simulation Frameworks
description: GALS 架构仿真、异步电路同步 FPGA 映射、多时钟域事件驱动仿真框架
source_url: "https://users.ece.cmu.edu/~schen1/ece743/PwrPerf_of_GALS.pdf"
source_type: "paper"
author: "Anoop Iyer, Diana Marculescu (Carnegie Mellon University)"
date: "2002"
tags: ["GALS", "multi-clock", "asynchronous", "event-driven-simulation", "FPGA-prototyping"]
keywords: ["globally asynchronous locally synchronous", "asynchronous circuit simulation", "event queue", "multiple clock domains", "DVFS"]
capture_date: "2026-06-20"
---

# 多时钟与异步设计仿真

## 来源

- URL: https://users.ece.cmu.edu/~schen1/ece743/PwrPerf_of_GALS.pdf
- 类型: 学术论文 (ISCA 2002)
- 作者: Anoop Iyer, Diana Marculescu (Carnegie Mellon University)
- 日期: 2002
- 补充来源:
  - https://csl.yale.edu/~rajit/ps/TCAD3131546.pdf (Yale: 异步电路同步 FPGA 仿真)
  - https://ieeexplore.ieee.org/document/6874581/ (IEEE: GalsBlock 计算模型)
  - https://doisrpska.nub.rs/index.php/IJEEC/article/download/8265/8029 (GALS 综述)

## 摘要

CMU 团队在 ISCA 2002 上提出了一套针对 GALS (Globally Asynchronous Locally Synchronous) 超标量处理器的 cycle-accurate 仿真框架。该框架基于通用事件驱动引擎，用单链表实现全局事件队列，每个时钟域以独立周期事件插入队列；通过异步 FIFO 实现跨域通信，避免了 stretchable clock 方案中每周期都停顿时钟的性能损失。实验表明，5 时钟域 GALS 处理器相比全同步版本性能下降约 5–15%，但借助各域独立的 DVFS 可弥补差距并降低功耗。Yale 团队则提出将异步电路自动映射到同步 FPGA 进行功能仿真，利用 FPGA 的并行门评估能力实现比软件仿真器高 1.3×10⁵ 倍的加速。IEEE 的 GalsBlock 模型进一步统一了同步块、异步块和异步通信的语义，支持从模型到 VHDL 的自动生成。

## 关键要点

- **GALS 事件驱动仿真核心**：
  - 每个时钟域是一个周期性事件，包含：回调函数、参数、触发时间、优先级、重复周期。
  - 事件队列按时间排序，引擎依次读取头部事件并执行；周期性事件处理完后自动将下一个周期事件重新入队。
  - 三个不同频率的时钟域示例：100 MHz (周期 10 ns)、66.7 MHz (15 ns)、50 MHz (20 ns)，分别用独立事件建模。
- **异步 FIFO 作为跨域接口**：
  - 相比 stretchable clock（每通信一次就暂停两边时钟），异步 FIFO 在稳态时吞吐高、延迟低，更适合处理器流水线中几乎每周期都发生的数据交换。
  - full/empty 信号需分别同步到对方时钟域。
- **GALS 性能与功耗权衡**：
  - 同频同压下，GALS 平均性能下降约 10%（分支预测失败代价更高）。
  - 但消除全局时钟网格后，时钟分布功耗降低；加上各域独立 DVFS，可在特定负载下优于全同步设计。
- **异步电路的同步 FPGA 仿真 (Yale)**：
  - 将异步电路的每个信号映射为 FPGA 上的一个 FF，每个门用相同的布尔函数描述，实现 unit-delay 并行评估。
  - 三种 FF 放置规则：CYC（切断组合环）、SH（状态保持门反馈处放 FF）、DIR（输入到输出的直接路径放 FF）。
  - 相比异步软件仿真器加速 1.3×10⁵ 倍，相比商业数字仿真器加速 2.8×10⁴ 倍。
- **GalsBlock 统一模型**：
  - 将同步组件封装为带本地控制时钟的 atom block，异步组件封装为无时钟 atom block，数据端口连接实现异步通信。
  - 支持统一的操作语义和形式语义，可生成可综合的 VHDL 代码直接用于 FPGA。

## 对 RTL 仿真器多线程化的启示

1. **事件队列是多时钟仿真的天然瓶颈**：所有线程共享一个全局事件队列时，锁竞争会成为性能瓶颈。可考虑按「时间窗口分片」或「每个时钟域维护本地 future 事件队列 + 全局合并」的策略，减少跨线程同步。CMU 论文中的单链表实现虽然简单，但在现代多核上难以扩展。

2. **异步 FIFO 作为线程间通信通道**：在多线程 RTL 仿真中，不同 clock domain 的线程可以通过异步 FIFO 风格的「无锁单生产者单消费者队列」交换事务级事件，而非在每个 cycle 都进行全局屏障同步。这能显著降低跨域通信开销。

3. **FPGA 并行评估映射到 CPU SIMD/GPU**：Yale 的方法将每个门映射为一个 FF + 组合逻辑，利用 FPGA 的并行评估能力。对于 CPU 多线程 RTL 仿真器，可借鉴此思路：将设计按门级数据流图分片，使用 SIMD 或 GPU 进行批量信号评估，尤其适合异步/事件驱动的细粒度模型。

4. **GALS 的相位随机性需要「确定性重放」机制**：CMU 论文提到 GALS 性能随各时钟相对相位变化而有约 0.5% 的波动。在多线程仿真中，若各时钟域由不同线程推进，浮点/整数精度差异或调度顺序可能导致非确定性相位差。必须在仿真内核中显式记录各时钟的启动相位和事件顺序，以支持可复现的调试。

## 原文摘录

> "We have written a general-purpose event-driven simulation engine which can be used to simulate any asynchronous system, synchronous (clocked) system, or a system which contains both asynchronous and synchronous components. The guts of this event-driven simulation engine consist of an event queue and a global timer."

> "To simulate clocked systems, we need to insert one event for each clock domain; for each such event, we need to specify a time period. When the execution engine processes such a periodic event, it schedules another instance of the same event into the queue, thus representing the next cycle of execution of the clocked system."

> "We exploit the parallelism in the underlying FPGA to execute a large number of parallel signal evaluations, including those which do not change states. Unlike in CPU based solutions, in our approach an idle firing does not incur additional computational cost, i.e. without performance degradation."

> "GALS architectures are solution to deal with multiple clock domains. GALS paradigm has been proposed as a compromise between fully synchronous and fully asynchronous architectures."

## 相关链接

- [Yale: Async Circuits on Synchronous FPGAs (IEEE TCAD)](https://csl.yale.edu/~rajit/ps/TCAD3131546.pdf)
- [IEEE: GalsBlock Computation Model](https://ieeexplore.ieee.org/document/6874581/)
- [GALS Overview / Clocking Survey](https://doisrpska.nub.rs/index.php/IJEEC/article/download/8265/8029)
- [Cornell: Multi-Cycle Communication (ISPD 2003)](https://www.csl.cornell.edu/~zhiruz/pdfs/rdr-ispd2003.pdf)
- [ACM: DVFS + GALS NoC Simulation Framework](https://dl.acm.org/doi/10.1007/s11265-015-0989-1)

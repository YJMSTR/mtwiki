---
id: "wiki-overview"
title: "多线程RTL仿真器优化概述"
description: "解释单线程稀疏计算RTL仿真器难以并行化的根本原因，并概述现有解决方案的优缺点"
tags: ["rtl-sim", "multithreading", "overview", "sparse-computation"]
keywords: ["RTL仿真", "多线程", "稀疏计算", "同步开销", "并行化"]
related_sources:
  - "source-verilator-issue-2913"
  - "source-parendi-asplos25"
  - "source-manticore-date23"
  - "source-verilator-mt-doc"
last_updated: "2026-07-01"
---

# 多线程RTL仿真器优化概述

## 为什么单线程稀疏计算RTL仿真器很难并行化

RTL（寄存器传输级）仿真器的核心工作是在每个时钟周期内，按照信号依赖顺序计算所有逻辑门的输出。单线程实现下，这一流程高度优化：编译时静态排序、事件驱动跳过非活跃区域、缓存友好的内存布局。然而，当试图引入多线程时，看似自然的并行思路却屡屡碰壁。

根本原因在于：**同步开销 > 并行收益**。

### 核心瓶颈：稀疏计算的特性

稀疏计算RTL仿真器的基本假设是——每个时钟周期内，只有少量信号发生翻转，大部分电路处于静态。这种稀疏性在单线程下是优势：只需遍历活跃信号，跳过静默区域。但在多线程下，它变成了诅咒：

- **计算量太小**：每个周期的活跃逻辑门数量有限，将它们分给多个线程后，每个线程的计算量可能只有几百条指令，远低于线程上下文切换和同步的固定开销。
- **同步频率太高**：为了保证周期精确性，每个时钟周期结束都需要一次全局barrier，确保所有分区的结果同步。稀疏计算意味着barrier之间几乎无事可做。
- **负载不均衡**：活跃信号在时间和空间上分布不均，静态分区可能导致某些线程空转而其他线程满载。

Verilator Issue #2913 是一个经典实证：一个仅32-bit Fibonacci生成器的极简设计，从单线程到4线程，**耗时翻了4倍**（1.9s → 7.6s）。维护者wsnyder的回应直指要害：

> **"Multithreading will only show speedups on much larger designs. In small designs the communication between cores will be much larger than leaving it on one core."**

这一Issue中的设计虽小，但它揭示的问题在更大规模的设计中同样存在——gergoerdi报告了一个20468行Verilog的Space Invaders街机模拟器，多线程同样出现了负优化。这说明问题不单纯是"设计太小"，而是**Verilator的macro-task分区模型本身在特定工作负载上存在系统性同步开销过高的问题**。

### 目标：16线程下 >2x 加速比

在通用x86多核服务器上，将RTL仿真扩展到16线程并获得超过2倍的加速比，已经被证明是一个极具挑战的目标。Manticore论文指出，Verilator多线程在部分基准上"几乎没有扩展性"，最多仅扩展到6个核心。Parendi在5888核IPU上获得了2.8–4倍加速，但那是专用架构。

>2x @ 16线程意味着单线程效率（strong scaling efficiency）需要达到12.5%以上。对于同步密集型的RTL仿真，这已经是相当高的门槛。

## 现有解决方案概述

### 1. Verilator 多线程（共享内存，macro-task分区）

**原理**：将RTL电路编译为C++代码，通过V3Partition/V3Order将语句级依赖图粗化为数十个macro-task（MTask），静态调度到多个线程。线程间通过共享内存和条件变量同步。

**优点**：
- 完全开源，生态系统成熟，与现有Verilog/SystemVerilog设计流程无缝集成
- 编译时静态调度，运行时无需复杂动态调度逻辑
- 支持Thread PGO（剖析引导优化），可根据实际执行时间调整负载均衡
- 提供线程亲和性和NUMA绑定建议

**缺点**：
- 同步开销在小设计和稀疏计算场景下成为主导因素，易出现负优化（Issue #2913）
- 静态分区无法适应运行时的活跃信号分布变化
- 在通用x86上扩展性差，最多扩展到约6个核心（Manticore对比数据）
- 编译大型设计时内存消耗巨大（Parendi报告中sr15设计消耗1043 GiB）

**适用场景**：大规模、密集计算的RTL设计，且计算量足以摊平同步开销。

### 2. Parendi（千核IPU，消息传递BSP）

**原理**：基于Verilator前端，将目标从x64共享内存改为Graphcore IPU的消息传递Bulk-Synchronous Parallel（BSP）模型。每个RTL周期对应一个superstep：计算→交换→同步。通过METIS风格图划分将RTL纤维（fibers）映射到IPU的1472–5888个核心上。

**优点**：
- 在4芯片IPU（5888核）上实现比x64 Verilator多线程快2.8–4倍的性能
- 细粒度并行性被充分利用，证明RTL仿真中存在大量可并行操作
- 核心间高带宽互连和本地SRAM消除了缓存一致性瓶颈

**缺点**：
- 依赖专用硬件（Graphcore IPU），通用性差
- 全周期仿真（activity-oblivious）牺牲了事件驱动的精度，不适用于所有设计类型
- 编译时间和内存开销仍然很大

**关键启示**：Parendi证明RTL仿真的并行瓶颈不在算法本身，而在**通用x86架构的缓存一致性和同步机制**。这为软件层面的优化指明了方向——在通用CPU上，需要用更轻量的同步机制来模拟IPU的高效通信。

### 3. Manticore（FPGA硬件加速，静态BSP）

**原理**：在Xilinx Alveo U200 FPGA上实现225个简单核心 @ 475 MHz，采用静态Bulk-Synchronous Parallel执行模型。编译时确定所有调度和通信，运行时无需动态同步原语。核心间通过消息传递通信，采用延迟更新（delayed updates）策略。

**优点**：
- 在9个基准中的8个上 outperform AMD EPYC 7V73X（120核）和Intel Core i7 9700K（8核）上的Verilator
- 静态调度消除了运行时同步开销，核心数可以大量集成（225核 on FPGA）
- 证明了RTL代码的确定性特性使静态调度完全可行

**缺点**：
- 需要FPGA硬件，部署成本高
- 频率远低于通用CPU（0.475 GHz vs 3.5+ GHz），单核心性能低
- 同样受Amdahl定律约束——如果设计中缺乏足够并行性（如jpeg基准），扩展性会提前饱和

**关键启示**：Manticore的核心洞察是——**运行时同步是扩展性杀手**。在x86上使用pthread/mutex/condition variable等传统同步原语，同步开销会迅速超过并行收益。这提示软件RTL仿真器需要：
- 避免每周期使用操作系统级线程同步
- 考虑用户态轻量级同步（futex、spinlock、RCU）或无锁数据结构
- 甚至考虑将多线程模型从shared-memory改为message-passing

## 对稀疏计算RTL仿真器多线程化的方向性建议

基于上述分析，针对稀疏计算RTL仿真器的多线程优化，应遵循以下原则：

1. **动态开销感知**：不能简单套用静态分区策略。必须设计一个动态调度器，在活跃信号数量超过阈值时才触发多线程执行，否则回退到单线程。
2. **同步粒度与活跃度的匹配**：稀疏计算意味着每周期活跃区域小，因此同步必须更粗粒度——不是每周期一次barrier，而是每N周期或按事件驱动批量同步。
3. **专用架构启示迁移到通用平台**：从Parendi和Manticore学到的分区思想和延迟同步策略，需要在通用x86上用软件模拟（轻量级spinlock、无锁队列、批量消息传递）。
4. **局部性优先于并行度**：在资源受限时，将通信密集的线程绑定到同一NUMA节点或L3集群，比跨集群使用更多物理核心更有价值。

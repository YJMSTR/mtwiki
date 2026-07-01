---
title: "Warped2: An Open-Source PDES Engine with Time Warp Synchronization"
source_url: "https://github.com/wilseypa/warped2"
source_type: "github"
author: "Philip A. Wilsey, Sounak Gupta, et al. (University of Cincinnati)"
date: "2014-present"
tags: ["pdes", "time-warp", "optimistic", "open-source", "c++", "multi-core", "shared-memory", "mpi"]
keywords: ["warped2", "time-warp-kernel", "pdes-engine", "ltsf-queue", "pending-event-set", "multi-threaded"]
capture_date: "2026-07-01"
---

# Warped2: An Open-Source PDES Engine with Time Warp Synchronization

## 来源

- **GitHub仓库**: https://github.com/wilseypa/warped2
- **GitHub Models**: https://github.com/wilseypa/warped2-models
- **研究主页**: https://eecs.ceas.uc.edu/~wilseypa/research/warped/
- **相关论文**: 
  - "Time Warp Simulation on Multi-core Platforms" (WSC 2019 tutorial): https://www.informs-sim.org/wsc19papers/150.pdf
  - "A large-scale distributed parallel discrete event simulation engines based on Warped2 for Wargaming simulation" (arXiv 2025): https://arxiv.org/abs/2507.18050
  - University of Cincinnati硕士论文 (2024): "Efficient Synchronization and Input Queue Optimization in Parallel Discrete Event Simulation"
- 类型: github / doc
- 主要维护者: Philip A. Wilsey (University of Cincinnati EECS), Sounak Gupta 等
- 语言: C++11
- 依赖: MPI (MPICH/OpenMPI), tclap, cereal, autotools
- 许可证: 开源（MIT兼容）

## 摘要

Warped2是由University of Cincinnati开发的C++11开源PDES引擎，是原始Warped内核的完全重新架构版本。它整合了多线程执行与基于MPI的进程级并行，可在单个SMP节点或多核集群上运行。Warped2的核心设计特点包括：(1) 高度可配置的Time Warp优化子算法；(2) 2级Pending Event Set数据结构，使用Least Time-Stamp First (LTSF) 队列，支持多队列分区以降低锁竞争；(3) 针对共享内存的优化，在单SMP节点上可实现接近100%的事件提交率（几乎零rollback）；(4) 支持state saving和reverse computation。Warped2的设计经验直接证明了Time Warp在共享内存多核处理器上的高效性，为RTL仿真器的多线程化提供了重要的工程参考。近期（2025）有研究者基于Warped2构建了面向大规模战争游戏仿真的分布式引擎，取得了16倍加速。

## 关键要点

### 架构设计
- **5大组件**: Event Dispatcher（事件调度器）、Global Manager（全局管理器）、Communication Manager（通信管理器）、Statistics Manager（统计管理器）、Termination Manager（终止管理器）。
- **Local vs Global**: Local组件管理当前计算节点上所有LP的活动（事件集、状态、rollback）；Global组件管理整个集群（GVT计算、终止检测、统计聚合）。
- **多线程+MPI**: 每个节点有主线程（消息通信）和工作线程（事件处理），支持MPI跨节点通信和Pthreads/线程级节点内并行。

### Pending Event Set（待处理事件集）——核心创新
- **2级结构**: 每个LP的最低时间戳事件被放入一个或多个LTSF（Least Time-Stamp First）调度队列中执行。
- **多LTSF队列**: 初始设计只有1个LTSF队列，但工作线程超过5-7时锁竞争成为瓶颈。当前设计允许实例化多个LTSF队列，每个队列分配唯一的LP子集，工作线程绑定到特定队列。
- **效果**: 在单多核SMP平台上，Warped2可以实现几乎零rollback的乐观执行。工作线程能紧密跟随事件执行的关键路径。

### 共享内存优化
- **锁策略**: 探索了事务内存（transactional memory）、无锁数据结构（lock-free data structures）、读写锁（read-write locks）等多种同步机制。
- **最佳实践**: 每个硬件线程一个工作线程，LP分区到独立LTSF队列，始终获得最佳性能。
- **GVT算法**: 在共享内存中支持同步GVT计算，管理线程轻量级，不干扰工作线程。
- **SMT影响**: 超线程（SMT）超过物理核心数后性能显著下降；保留一个硬件线程给OS对性能影响不大。

### 可配置性
- Warped2不是单一仿真器，而是研究平台。它提供多种Time Warp子算法供比较研究：lazy cancellation, lazy reevaluation, direct cancellation, optimistic time windows等。
- 支持用户通过API构建自定义仿真模型（见warped2-models仓库）。

### 性能基准
- 单节点多核：可以实现接近100%的事件提交率。
- 2025年war游戏仿真扩展：基于Warped2的框架在GridWorld演示中达到16倍于基线的加速，单线程配置8倍加速，同步开销降低58.18%。
- ROSS对比：Warped2在内存管理和事件调度方面被认为比ROSS更简单高效。

### 局限性和批评
- 2025年论文指出Warped2在超大规模场景中的内部限制：(1) 处理大规模事件吞吐量的机制不足；(2) 不能自主调整每个进程的负载；(3) 缺乏实体交互接口（对特定领域如战争游戏）。
- 这些限制促使研究者在其上添加异步监听器线程、METIS负载重平衡、空间哈希等扩展。

## 对 RTL 仿真器多线程化的启示

1. **多LTSF队列是共享内存RTL仿真的关键**: Warped2最重要的工程发现是：将全局事件队列分区为多个LTSF队列，每个工作线程绑定一个队列，可以将锁竞争和rollback率同时降至接近零。在RTL仿真器中，这意味着：不应该让所有线程竞争一个全局事件队列，而应将电路分区为多个"仿真岛"，每个岛有自己的局部事件队列，线程优先处理本地事件。

2. **工作线程+管理线程分离**: Warped2采用工作线程纯执行事件（包括rollback和状态保存）+ 管理线程负责GVT和housekeeping的架构。在RTL仿真器中，可以借鉴：一个轻量级管理线程周期性计算GVT/回收内存，多个工作线程全速处理门级事件。管理线程的轻量性很重要——在Warped2中它不需要独立硬件线程。

3. **近乎零rollback是可能的**: Warped2在单SMP节点上接近100%事件提交率的实验表明，在共享内存环境下，如果队列分区得当，Time Warp的rollback开销可以被忽略。这对RTL仿真器极具鼓舞：意味着乐观同步在共享内存RTL仿真中的实际成本可能远低于传统认知，主要瓶颈不是rollback而是数据结构竞争。

4. **C++模板/宏定义LP状态**: Warped2使用宏（如WARPED_DEFINE_LP_STATE_STRUCT）来定义LP状态结构。在RTL仿真器中，这提示可以使用类似代码生成/宏定义的方式，让用户（或综合工具）自动声明门的输入、输出、内部状态，从而自动生成状态保存/反向计算代码。

5. **2级事件集的扩展**: Warped2的2级Pending Event Set可以进一步扩展为RTL友好的层次：L0级（全局周期队列）→ L1级（每个分区的LTSF队列）→ L2级（每个门LP的输入端口事件列表）。周期边界由全局时钟驱动，确保每个RTL周期开始时所有线程同步，周期内则允许乐观执行。

6. **从Warped2到RTL仿真器的迁移路径**: Warped2的C++ API和模型结构（LP、Event、State）可以相对直接地映射到RTL门级仿真：每个门=LP，每个信号翻转=Event，门的输出值=State。基于Warped2构建RTL仿真器原型是可行的技术路径，可以避免从零实现Time Warp基础设施。但需要注意的是，Warped2是为通用PDES设计的，RTL仿真器需要在其上添加：(a) 电路拓扑导入（Verilog/netlist）；(b) 周期/时钟语义；(c) 值解析（多值逻辑、X/Z状态）；(d) 与标准波形Dump的接口。

## 原文摘录

> "As part of these studies we have developed an open source time warp simulation kernel called warped2. The kernel is written in C++ and is freely available. The warped2 kernel is highly configurable and provides multiple Time Warp optimizations for exploration."
—— Warped2 Research Page

> "The design, called warped2, integrates multi-threaded execution with process-based parallelism and is suitable for execution on a single SMP node or on a cluster with SMP nodes."
—— Warped2 Research Page

> "The pending event set in warped2 is deployed so that the lowest time-stamped events from every LP are placed into one or more event scheduling queues (called Least Time-Stamp First or LTSF queues) for execution. The initial solution had only one LTSF queue, but lock contention for the LTSF queue became a detriment to performance once the number of worker threads exceeded 5-7."
—— Warped2 Research Page

> "The current design permits the instantiation of multiple LTSF queues and assigns unique subsets of the LPs to each LTSF queue. The system then binds a collection of one or more 'worker' threads to a specific LTSF queue that process events only from that queue. This organization alleviate contention for the LTSF queue and provides a highly efficient schedule of event execution that will closely follow the critical path of event execution. As a result, when executing on a single multi-core SMP platform, the warped2 kernel will experience few if any rollback events."
—— Warped2 Research Page

> "In general one worker thread per hardware processing thread delivers the best performance, although scaling drops off significantly once the number of threads exceeds the physical core count (entering the shared SMT thread space)."
—— WSC 2019 Tutorial

> "Warped2, a PDES engine leveraging Time Warp synchronization with Pending Event Set optimization, delivers strong performance, it struggles with inherent wargaming limitations: inefficient LP resource allocation during synchronization and unaddressed complex entity interaction patterns."
—— arXiv 2025 (基于Warped2的扩展)

## 相关链接

- [Warped2 GitHub主仓库](https://github.com/wilseypa/warped2)
- [Warped2 Models GitHub](https://github.com/wilseypa/warped2-models)
- [Warped2研究主页 (Cincinnati)](https://eecs.ceas.uc.edu/~wilseypa/research/warped/)
- [WSC 2019 Tutorial: Time Warp on Multi-core](https://www.informs-sim.org/wsc19papers/150.pdf)
- [arXiv 2025: 基于Warped2的大规模战争游戏引擎](https://arxiv.org/abs/2507.18050)
- [University of Cincinnati 2024硕士论文: Warped2 v2.x设计](https://etd.ohiolink.edu/acprod/odb_etd/etd/r/1501/10?p10_etd_subid=203123&clear=10&p1001_keyword=DES&p1002_sort_by=0)
- [ROSS (Rensselaer)](https://github.com/gonsie/ROSS) - Warped2的主要对比对象
- [ROOT-Sim](https://github.com/HPDCS/ROOT-Sim) - 另一Time Warp实现

---
title: "Parallel Discrete Event Simulation: The Making of a Field"
source_url: "https://ieeexplore.ieee.org/document/8247793"
source_type: "paper"
author: "Richard M. Fujimoto, Rajive Bagrodia, Randal E. Bryant, K. Mani Chandy, David Jefferson, Jayadev Misra, David Nicol, Brian Unger"
date: "2017"
tags: ["pdes", "history", "synchronization", "conservative", "optimistic", "time-warp", "survey"]
keywords: ["parallel-discrete-event-simulation", "making-of-a-field", "logical-processes", "chandy-misra-bryant", "time-warp", "virtual-time"]
capture_date: "2026-07-01"
---

# Parallel Discrete Event Simulation: The Making of a Field

## 来源

- URL: https://ieeexplore.ieee.org/document/8247793
- 备用PDF: https://www.informs-sim.org/wsc17papers/includes/files/019.pdf
- 类型: paper
- 作者: Richard M. Fujimoto, Rajive Bagrodia, Randal E. Bryant, K. Mani Chandy, David Jefferson, Jayadev Misra, David Nicol, Brian Unger
- 日期: 2017（发表于2017 Winter Simulation Conference）
- 引用: 被引55次（截至搜索时）

## 摘要

本文是PDES领域奠基人集体撰写的历史性综述，由Fujimoto、Bryant、Chandy、Jefferson、Misra等该领域核心开创者共同完成。文章追溯了PDES从1970年代末期到2010年代的发展历程，重点记录了两大同步范式的诞生：保守同步（Chandy/Misra/Bryant, CMB算法）和乐观同步（Time Warp）。1970年代末，Chandy与Misra在UT Austin、Bryant在MIT独立开发了后来被统称为CMB的保守同步算法；几年后，David Jefferson和Henry Sowizral在Rand Corporation提出了完全不同的Time Warp方法。这两个方向构成了PDES至今的两大主流算法类别。文中还详细回忆了1980-1990年代保守派与乐观派之间的学术竞争，PHOLD基准测试的诞生，以及HLA（High Level Architecture）标准的建立和PDES技术的商业化过程（Jade Simulations等）。

## 关键要点

- **保守同步的起源**: Chandy & Misra (1979) 和 Bryant (1977) 独立提出CMB算法，核心思想是LP只有在确定不会收到更小时间戳事件时才执行事件，通过null message避免死锁。
- **乐观同步的诞生**: Jefferson & Sowizral (1982-1985) 提出Time Warp，允许LP冒险超前执行，通过rollback和antimessage机制纠正因果错误。Jefferson后来承认，如果早知道CMB工作，他可能不会发明Time Warp。
- **PHOLD基准**: Fujimoto创造了PHOLD作为PDES的标准性能测试基准，但也承认它是高度规则的结构化负载，不能代表真实世界应用的不规则性。
- **共享内存优化**: Fujimoto在Georgia Tech开发了GTW (Georgia Tech Time Warp)，重点优化共享内存多处理器上的Time Warp，包括direct cancellation（用简单指针实现anti-message）、高效的GVT计算和on-the-fly fossil collection。
- **HLA标准**: 1990年代DoD推动的HLA标准（IEEE 1516）使PDES技术从学术界走向更广泛的工业应用。
- **商业Jade**: Brian Unger等人基于University of Calgary的Project JADE创建了Jade Simulations公司，将Time Warp技术商业化。

## 对 RTL 仿真器多线程化的启示

1. **共享内存优先**: Fujimoto明确指出Time Warp在共享内存多处理器上的效率远高于分布式内存系统。对于"稀疏计算RTL仿真器多线程化"项目，这意味着应优先考虑共享内存多线程架构（如pthread/OpenMP），而非MPI分布式方案。共享内存下的direct cancellation技术可以极大降低antimessage开销。

2. **分区是关键**: CMB和Time Warp的性能都极度依赖模型分区（partitioning）质量。对于RTL电路，将门/寄存器映射为LP时，必须最小化跨LP边界的信号传递。这提示RTL仿真器的多线程化需要专门的电路拓扑感知分区算法，而非通用图划分。

3. **混合同步策略**: 文中提到Fujimoto后来意识到保守和乐观并非互斥。对于RTL仿真，可以考虑将电路分为保守区域（如时钟域、同步逻辑）和乐观区域（如异步组合逻辑），实现混合同步。这可以兼顾组合逻辑的大并行度和同步逻辑的确定性。

4. **GVT计算优化**: 在共享内存多线程RTL仿真中，需要高效的GVT（Global Virtual Time）计算来决定何时可以安全回收状态。Fujimoto和Hybinette的共享内存GVT算法值得参考。

5. **状态保存成本**: Time Warp在RTL仿真中的最大障碍是状态保存开销。RTL门级LP的状态很小（通常只是一个bit或几个bit），这实际上是有利条件——增量状态保存或copy state saving的成本相对较低，与通用PDES应用中LP状态庞大的情况不同。

## 原文摘录

> "Parallel discrete event simulation (PDES) is a field concerned with the execution of discrete event simulation programs on a parallel computer. The field began with work in the 1970's and 1980's in first defining the synchronization problem along with associated terminology (e.g., logical processes) and the development of algorithmic solutions."

> "The first, now called conservative synchronization, grew from pioneering work by two groups working independently and without knowledge of each other in the late 1970's. K. Mani Chandy and Jay Misra at the University of Texas in Austin (Chandy and Misra 1979), and a master degree student at MIT, Randy Bryant (Bryant 1977a) developed what is now referred to as the Chandy/Misra/Bryant (CMB) algorithm."

> "A few years later, David Jefferson and Henry Sowizral at the Rand Corporation came up with an entirely different approach known as Time Warp (Jefferson 1985), resulting in a class of methods termed optimistic synchronization."

> "Interestingly, Jefferson was unaware of the work by Chandy, Misra, and Bryant when he invented Time Warp, and later remarked that had he known about their work, he likely would not have invented Time Warp, as his thinking would have been steered into an entirely different direction."

> "I developed a technique called direct cancellation that implemented anti-messages with a simple pointer (Fujimoto 1989a), leading to a very efficient implementation that yielded good speedup."

## 相关链接

- [PDF全文](https://www.informs-sim.org/wsc17papers/includes/files/019.pdf)
- [ResearchGate版本](https://www.researchgate.net/publication/322325092_Parallel_discrete_event_simulation_The_making_of_a_field)
- [Caltech Authors版本](https://authors.library.caltech.edu/records/hmerv-kge80)
- [Fujimoto PADS 2015演讲](https://simultech.scitevents.org/Documents/Previous_Invited_Speakers/2015/SIMULTECH2015_Fujimoto.pdf)

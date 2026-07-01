---
title: "Parallel and Distributed VHDL Simulation"
source_url: "https://dl.acm.org/doi/pdf/10.1145/343647.343884"
source_type: "paper"
author: "Dragos Lungeanu, C.J. Richard Shi"
date: "2000"
tags: ["pdes", "vhdl", "rtl-sim", "synchronization", "delta-cycle", "optimistic", "conservative", "digital-circuit"]
keywords: ["vhdl-simulation", "parallel-vhdl", "delta-cycle", "lamport-logical-clock", "lookahead-free", "self-adaptive"]
capture_date: "2026-07-01"
---

# Parallel and Distributed VHDL Simulation

## 来源

- URL: https://dl.acm.org/doi/pdf/10.1145/343647.343884
- 备用PDF: https://www.cecs.uci.edu/~papers/compendium94-03/papers/2000/date00/pdffiles/10a_1.pdf
- 类型: paper
- 作者: Dragos Lungeanu (University of Iowa), C.J. Richard Shi (University of Washington)
- 日期: 2000（发表于DATE '00: Design, Automation and Test in Europe）
- 页码: 658-662

## 摘要

本文提出了一种基于PDES范式进行VHDL并行与分布式仿真的方法论。核心挑战在于：标准PDES协议中，某些协议假设同时发生的事件（simultaneous events）可以按任意顺序处理，但这与VHDL的delta cycle语义冲突。作者提出的解决方案是：使用Lamport逻辑时钟对同时事件进行因果排序（tie-breaking），并将VHDL虚拟时间定义为（物理时间, 周期/相位逻辑时间）的二元组。这使得分布式VHDL仿真能够正确处理delta cycle。此外，作者将该方法与一种无需lookahead的混合PDES协议结合，允许逻辑进程（LP）在乐观模式和保守模式之间自适应切换。实验在SGI Challenge 16处理器并行机上进行，对5531到14704个LP的VHDL设计实现了接近线性的加速比。

## 关键要点

- **VHDL到PDES的映射**: 将VHDL信号和进程映射为PDES模型中的逻辑进程（LP），每个VHDL进程对应一个LP，信号也映射为LP。VHDL层次结构经过elaboration后展平为进程-信号图。
- **Delta Cycle问题**: VHDL仿真中delta cycle（零延迟的事件推进）导致大量时间戳相同的事件。传统PDES的"任意顺序处理同时事件"假设会破坏VHDL语义。
- **Lamport逻辑时钟**: 使用Lamport逻辑时钟对同时事件进行因果排序，将VHDL虚拟时间扩展为二元组 `(physical_time, cycle/phase_logical_time)`，确保分布式环境下delta cycle的正确性。
- **无需Lookahead的混合协议**: 该协议不依赖lookahead（而传统保守同步需要lookahead来避免死锁）。LP可以动态自适应地在乐观和保守模式之间切换，自动寻找最佳配置。
- **性能结果**: 在4种配置下测试（全乐观、全保守、寄存器保守+组合逻辑乐观、全动态），对FSM、IIR Filter、DCT Processor等电路实现了接近线性的加速比。
- **混合配置最佳**: 将同步组件（寄存器、时钟）映射为保守LP，异步组件（组合逻辑）映射为乐观LP的混合策略，在大多数实验中表现最好。

## 对 RTL 仿真器多线程化的启示

1. **Delta Cycle是RTL仿真的核心特殊挑战**: 任何将PDES应用于RTL/Verilog/VHDL仿真的方案都必须处理delta cycle。Lungeanu和Shi的方法证明，通过扩展时间戳为（物理时间, 逻辑相位）二元组可以正确维护因果序。这对于稀疏计算RTL仿真器多线程化是核心技术启示：不能简单地将PDES的原始时间戳直接套用到RTL仿真中，需要RTL语义感知的时间戳扩展。

2. **Lookahead-free的重要性**: 在门级RTL仿真中，lookahead（预测未来事件的最小时间间隔）通常为零或极难计算，因为组合逻辑的传播延迟可以是零。传统保守同步（如CMB）在零lookahead下会退化为串行执行。Lungeanu/Shi的lookahead-free协议证明了即使没有lookahead，也可以实现有效的并行RTL仿真。这直接解决了稀疏计算RTL仿真器的核心障碍。

3. **混合同步策略**: 实验表明，将同步部分（寄存器、时钟域）作为保守LP、异步部分（组合逻辑）作为乐观LP的混合配置效果最好。这与RTL电路的结构高度吻合：时钟信号是"持久且稳定的"，而组合逻辑事件通常沿数据流路径传播。对于稀疏计算RTL仿真器，这意味着可以自动识别电路中的同步/异步边界，并分配不同的同步策略。

4. **共享内存优于分布式**: 虽然论文使用MPI/TCP在SGI Challenge上实验，但VHDL仿真的LP间通信量极小（通常是单个bit值）。这暗示在共享内存多线程环境中，LP间通信可以通过直接内存访问完成，避免MPI消息传递开销，从而获得更高的加速比。

5. **状态保存可行性**: 论文指出乐观模式内存需求与处理器数量成正比。但对于RTL门级LP，单个门的状态通常只有1-bit（或少量bit），状态保存成本极低。这使得乐观同步在RTL仿真中比在其他PDES应用领域（如网络仿真）更具可行性。

## 原文摘录

> "This paper presents a methodology for parallel and distributed simulation of VHDL using the PDES paradigm. To achieve better features and performance, some PDES protocols assume that simultaneous events may be processed in arbitrary order. We describe a solution of how to apply these algorithms to have a correct simulation of the distributed VHDL cycle, including the delta cycle."

> "The solution is based on tie-breaking the simultaneous events using Lamport's logical clock to causally order them according to the VHDL simulation cycle, and defining the VHDL virtual time as a pair of simulation physical time and cycle/phase logical time."

> "The paper also shows how to use this method with a PDES protocol that relaxes the simulation of simultaneous events to arbitrary order, allowing the LPs to self-adapt to optimistic or conservative mode, without the lookahead requirement."

> "The parallel simulation of VHDL designs ranging from 5531 to 14704 LPs using these methods obtained a promising, almost linear speedup."

> "The mixed configuration in which synchronous components are mapped as conservative and asynchronous ones as optimistic worked very well for most of the cases, better than all optimistic or all conservative configurations."

> "We observe that in general the optimistic configuration is very suitable for digital simulation. Unfortunately, it demands huge amounts of memory, proportional to the number of processors. Heavy-state processes cannot save their state, so they must run conservatively."

## 相关链接

- [ACM Digital Library](https://dl.acm.org/doi/pdf/10.1145/343647.343884)
- [DATE 2000会议PDF](https://www.cecs.uci.edu/~papers/compendium94-03/papers/2000/date00/pdffiles/10a_1.pdf)
- [作者相关论文：Distributed VHDL-SPICE Mixed-Signal](https://sigmod.org/publications/dblp////db/conf/iccd/iccd2001.html)
- [Lungeanu & Shi ICCAD 1999: Lookahead-free self-adaptive optimistic and conservative synchronization](https://www.cecs.uci.edu/~papers/compendium94-03/papers/2000/date00/pdffiles/10a_1.pdf)

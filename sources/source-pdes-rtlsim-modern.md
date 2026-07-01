---
title: "Modern PDES in RTL Simulation: Parendi, DSIM, and Million-Gate Parallelism"
source_url: "https://arxiv.org/html/2403.04714v1"
source_type: "paper"
author: "Mahyar Emami, Thomas Bourgeat, James R. Larus (EPFL); Lijuan Zhu, Gilbert Chen, Boleslaw Szymanski, Carl Tropper (RPI/McGill)"
date: "2024-2025"
tags: ["pdes", "rtl-sim", "parallel-rtl", "verilator", "ipu", "message-passing", "shared-memory", "million-gate"]
keywords: ["parendi", "verilator", "parallel-rtl", "bsp", "ipu", "message-passing", "cycle-accurate", "full-cycle-simulation"]
capture_date: "2026-07-01"
---

# Modern PDES in RTL Simulation: Parendi, DSIM, and Million-Gate Parallelism

## 来源

- **Parendi (EPFL, ASPLOS 2025)**:
  - URL: https://arxiv.org/html/2403.04714v1
  - 作者: Mahyar Emami, Thomas Bourgeat, James R. Larus
  - 机构: EPFL (瑞士洛桑联邦理工学院)
  - 发表: ASPLOS 2025, Rotterdam

- **DSIM / Million-Gate VLSI (RPI, MASCOTS 2005)**:
  - URL: https://www.cs.rpi.edu/~szymansk/papers/milliongate.pdf
  - 作者: Lijuan Zhu, Gilbert Chen, Boleslaw K. Szymanski (RPI), Carl Tropper, Tong Zhang (McGill)
  - 发表: MASCOTS 2005

- **Temporal Parallel Gate-level Timing Simulation (UMass)**:
  - URL: http://www.ecs.umass.edu/ece/labs/vlsicad/papers/HLDVT-08_v8_mc.pdf
  - 作者: D. Kim, M. Ciesielski, K. Shim, S. Yang

- **Parendi GitHub**: https://github.com/epfl-vlsc/parendi

- **Verilator**: https://verilator.org

- 类型: paper / github

## 摘要

本文档综合了PDES在RTL仿真中的现代应用资料。Parendi (EPFL, ASPLOS 2025) 是一个针对Graphcore IPU（1472-5888核的消息传递架构）的Verilog编译器，实现了千路并行RTL仿真。它基于Verilator构建，但将目标从x64共享内存改为IPU的消息传递BSP模型。Parendi通过全周期（full-cycle, activity-oblivious）仿真而非事件驱动仿真，在IPU上实现了几何平均2.81倍于多线程Verilator的加速。DSIM (RPI, 2005) 是一个并行门级仿真器，在百万门Viterbi译码器上实现了33处理器22.63倍加速。Kim等人(2008)提出了利用高层模型进行时间并行门级时序仿真的方法。这些工作共同展示了PDES思想在现代RTL仿真中的两条路径：共享内存多线程（Verilator、DSIM）和消息传递大规模并行（Parendi）。

## 关键要点

### Parendi: IPU上的千路并行RTL仿真
- **架构选择**: Parendi的作者明确指出，RTL并行仿真更适合消息传递架构而非共享内存。共享内存的问题包括：(1) 细粒度并行导致频繁同步成本高昂；(2) RTL任务间通信量小但都是点对点，必须经过LLC；(3) RTL编译后代码的数据/指令复用距离极大，缓存性能差。
- **BSP模型**: Parendi采用Bulk Synchronous Parallel (BSP) 模型，每个RTL周期对应一个superstep：计算→交换→同步。这与传统PDES的异步事件驱动截然不同，是一种同步的"时间并行"。
- **全周期仿真**: Parendi使用全周期仿真（每个周期评估整个电路），而非事件驱动。作者指出在RTL层级跟踪值变化成本极高，全周期仿真通常快几个数量级。
- **分区策略**: 将RTL纤维（fibers）分区到IPU的tile上，使用METIS风格的图划分最小化通信量。
- **性能**: 在IPU上几何平均速度是Verilator多线程版本的2.81倍（ix3）和2.75倍（ae4）。
- **编译器**: 基于Verilator（约8K行新增代码），生成C++ BSP程序使用Poplar SDK。

### DSIM: 百万门并行逻辑仿真 (RPI)
- **乐观同步**: DSIM使用Time Warp乐观同步，每个门/输入/时钟建模为一个LP。
- **大规模验证**: 在1.2M门的Viterbi译码器上测试，使用1500输入向量。
- **性能结果**: 33处理器上实现22.63倍加速（相比单处理器），rollback比率仅0.79%，远程事件比率11.6%。
- **增量状态保存**: 采用增量状态保存减少rollback开销。
- **分区**: 使用hMeTiS进行电路划分。

### 时间并行门级时序仿真 (Kim et al., 2008)
- 提出利用高层模型指导的门级时序并行仿真，在HLDVT 2008发表。
- 关注temporal parallelism（时间维度并行）而非spatial parallelism（空间维度并行）。

### Verilator的现代多线程
- Verilator是当前最流行的开源RTL仿真器之一，通过多线程编译（--threads选项）支持并行仿真。
- 但在共享内存多处理器上，Verilator的多线程性能受限于缓存行为和锁竞争。
- Parendi指出Verilator编译大型设计时内存消耗巨大（sr15设计消耗1043 GiB），编译时间接近8小时。

## 对 RTL 仿真器多线程化的启示

1. **消息传递 vs 共享内存的再评估**: Parendi的一个重要结论是RTL并行仿真更适合消息传递而非共享内存。但在传统CPU上（非IPU），消息传递意味着MPI或进程间通信，开销较高。对于"稀疏计算RTL仿真器"项目，如果目标是普通多核CPU共享内存，需要特别关注：(a) 减少线程间同步频率；(b) 利用无锁数据结构；(c) 采用粗粒度LP而非细粒度门级LP。如果目标是多节点集群，则Parendi的BSP模型提供了一条全新路径。

2. **全周期仿真 vs 事件驱动**: Parendi的全周期方法牺牲了一些事件驱动的精度（零延迟组合逻辑），但获得了巨大的性能优势。对于稀疏计算RTL仿真器，需要权衡：如果目标设计以同步数字逻辑为主，全周期仿真是更优选择；如果设计包含大量模拟/混合信号或需要精细时序分析，事件驱动仍必要。但值得注意的是，标准数字RTL（如处理器核）通常完全适用全周期仿真。

3. **细粒度并行的困境**: 传统PDES将每个门作为一个LP的细粒度方法在共享内存上难以扩展。Parendi通过将多个门组合为fiber（纤维）分配到IPU tile上；DSIM将门聚类为分区。这提示：在共享内存多线程RTL仿真器中，不应该让每个门独立运行，而应该将多个门组成"宏LP"或"LP簇"，减少同步开销。

4. **状态保存和rollback在门级是可行的**: DSIM在百万门设计上仅0.79%的rollback比率，说明乐观同步在门级电路仿真中非常有效。这是因为数字电路的因果结构相对确定——信号传播方向通常固定，straggler事件相对稀少。这为稀疏计算RTL仿真器采用乐观同步提供了强有力证据。

5. **从Verilator出发**: Parendi选择基于Verilator而非从零开始，这是务实的方法。Verilator已处理了大量Verilog/SystemVerilog语义，优化了代码生成。对于稀疏计算RTL仿真器，同样可以考虑以Verilator或类似开源工具为基础，添加多线程/PDES同步层，而非从头构建完整仿真器。

6. **时间并行（Temporal Parallelism）**: Kim等人的工作和Parendi的BSP方法都暗示了一种新的并行维度：时间并行。不同于传统PDES将空间分区到不同LP，时间并行同时推进多个仿真周期（在流水线或预测模式下）。这可以与传统空间并行结合，形成时空并行的RTL仿真。

## 原文摘录

> "Parallel RTL simulation is better suited to message-passing computation (and architectures) than shared-memory. First, the fine-grained parallelism is challenging to execute on a shared-memory multiprocessor due to costly synchronization. Second, the RTL tasks have a high level of fine-grained point-to-point communication... Last, the RTL can have a high reuse distance in data and instructions, which makes caches perform poorly."
—— Parendi, ASPLOS 2025

> "We present the design and implementation of a new parallel simulator, called DSIM, and demonstrate DSIM's efficiency and speed by simulating a million gate circuit using different numbers of processors."
—— DSIM, MASCOTS 2005

> "The focus of this paper is an efficient simulation of large chip designs."
—— DSIM Abstract

> "Full-cycle simulators perform better—sometimes by orders of magnitude—because tracking value changes in RTL is expensive."
—— Parendi, ASPLOS 2025

## 相关链接

- [Parendi ASPLOS 2025 arXiv](https://arxiv.org/html/2403.04714v1)
- [Parendi GitHub](https://github.com/epfl-vlsc/parendi)
- [DSIM Million-Gate Paper](https://www.cs.rpi.edu/~szymansk/papers/milliongate.pdf)
- [DSIM Thesis (Lijuan Zhu, 2005)](https://www.cs.rpi.edu/~szymansk/theses/zhu.ms.05.pdf)
- [Temporal Parallel Simulation (Kim et al., 2008)](http://www.ecs.umass.edu/ece/labs/vlsicad/papers/HLDVT-08_v8_mc.pdf)
- [Verilator官网](https://verilator.org)
- [PSML综述 (2018)](http://www.sce.carleton.ca/faculty/wainer/papers/Poshtkohi2018_Article_PSMLParallelSystemModelingAndS.pdf) - 包含大量RTL PDES相关引用

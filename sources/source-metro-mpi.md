---
title: "Fast Behavioural RTL Simulation of 10B Transistor SoC Designs with Metro-MPI (DATE'23)"
source_url: "https://past.date-conference.com/proceedings-archive/2023/DATA/170.pdf / https://jbalkind.github.io/docs/date_2023_camera_ready.pdf"
source_type: "paper"
author: "Guillem López-Paradís, Brian Li, Adrià Armejach, Stefan Wallentowitz, Miquel Moretó, Jonathan Balkind (Barcelona Supercomputing Center, UC Santa Barbara, Munich University of Applied Sciences)"
date: "2023"
tags: ["rtl-sim", "multithreading", "distributed", "MPI", "SoC", "NoC", "HPC", "Verilator"]
keywords: ["Metro-MPI", "RTL simulation", "distributed simulation", "MPI", "network-on-chip", "OpenPiton", "Verilator", "multi-tile granule", "latency-insensitive interface"]
capture_date: "2026-07-01"
---

## 摘要

Metro-MPI 是一个利用 **MPI（Message Passing Interface）** 实现**分布式 RTL 仿真**的通用框架，发表于 DATE'23。它通过将现代 SoC 的自然边界（如 NoC、AXI 等延迟不敏感接口）作为分区点，将 RTL 仿真转化为一个 HPC 分布式计算问题。

核心成果：
1. **与顺序仿真相比高达 135.98× 的加速比**：在 OpenPiton+Ariane 的 1024 核、100 亿晶体管设计上达到 **2.7 MIPS** 的 RTL 仿真吞吐量。
2. **与多线程仿真相比高达 9.29× 的加速比**：说明分布式多进程方案比单机多线程方案有更大的扩展潜力。
3. **能耗降低 2.53×**：对于代表性回归测试，Metro-MPI 相比顺序仿真减少了超过一半的能耗。
4. **开源实现**：https://github.com/metro-mpi

关键技术：
- **NoC-based 分区**：利用 OpenPiton 中 tile-tile 的 NoC 连接作为天然边界，将每个 tile 或一组 tile 映射到独立的 MPI 进程
- **信号打包**：将同一方向的所有 NoC 信号（Valid, Data, Yummy）打包成单个 MPI 消息，减少通信开销
- **Multi-Tile Granule (MTG)**：支持将多个 tile 放在同一个 MPI 进程中，在节点资源受限时减少进程数
- **可配置通信间隔**：chipset 和 tile 之间不必每周期通信，可以配置通信间隔以减少 MPI 消息频率

## 对"稀疏计算RTL仿真器多线程化"的启示

1. **多进程 > 多线程的扩展潜力**：Metro-MPI 的核心发现是——对于大规模 SoC 仿真，**跨节点的分布式多进程方案比单机多线程方案扩展性更好**。Verilator 的多线程在单机上受限于同步开销和内存带宽，而 MPI 通过进程隔离和显式消息传递，将同步粒度从"每周期 barrier"降低为"每 N 周期消息交换"。对于我们的稀疏计算 RTL 仿真器，这提示：
   - 如果目标设计足够大，**多进程方案**可能比多线程方案更优
   - 对于中小规模设计，可以在单进程内使用**更粗粒度的同步**（如每 N 周期同步一次，而非每周期）

2. **利用延迟不敏感接口作为分区边界**：Metro-MPI 的分区策略不是基于电路结构，而是基于**接口的延迟不敏感性**。NoC、AXI 等协议天然允许通信延迟，因此这些连接点是最理想的分布式仿真边界。对于稀疏计算 RTL 设计，我们需要识别类似的"天然边界"——例如：
   - 处理器核心与内存控制器之间的接口
   - 不同时钟域之间的 CDC 边界
   - 总线矩阵与从设备之间的 AXI 接口

3. **信号打包与批量通信**：Metro-MPI 将 Valid/Data/Yummy 打包为单个 MPI 消息，在单节点上带来约 10% 的性能提升。对于稀疏计算，我们可以进一步压缩通信内容：**仅传递翻转信号，使用 run-length 编码或 delta 压缩**。在稀疏场景下，这种压缩的收益会更大。

4. **通信频率可配置**：Metro-MPI 允许 chipset 和 tile 以可配置间隔通信（而非每周期）。这相当于在分布式仿真中引入了**时间切片**的概念。对于稀疏计算，可以自适应地调整通信间隔：当检测到某个区域信号活跃度高时缩短间隔，活跃度高时延长间隔。

5. **Multi-Tile Granule 的权衡**：MTG 将多个 tile 合并到单个进程中，在减少进程间通信的同时增加了单进程的计算量。这类似于多线程中"任务粒度"的权衡。对于稀疏计算，我们需要找到一个**自适应的粒度平衡点**：太细的粒度导致通信开销高，太粗的粒度导致负载不均衡。

## 关键原文摘录

### 问题背景：RTL 仿真规模危机

> Designing today's 10 billion transistor-scale chips is only getting more difficult and expensive as their scale grows, with little improvement in EDA tool performance. Such performance stagnation has been seen in Register-Transfer Level (RTL) simulation, which is crucial for accurate modelling. Blocks of reasonable scale (10M-100M transistors) often see RTL simulation throughput of only a few thousands of cycles per second (CPS). This means that simulating a core running at 1 GHz with 1 instruction/cycle for 1 second of execution would require over 10 days of simulation time.

> With poor scaling as designs grow, RTL simulation of full chips has become too costly and is reserved for the final steps in the design process.

### Verilator 性能退化（OpenPiton 基准）

> To demonstrate this, we simulate large OpenPiton manycore chips with Verilator. Figure 1 shows that increasing the number of simulated cores causes a throughput degradation. For each chip size, we show the instructions per second or IPS (left, blue), CPS (right, green), and compilation time (black line). The CPS decreases as a larger design requires more simulation work per cycle. As this trend continues with size, it is not viable to simulate very large designs, especially since compilation time increases super-linearly with core count, rapidly becoming a bottleneck.

### Metro-MPI 核心思想

> Our key insight is to exploit modern SoCs' natural boundaries (e.g. NoCs) to partition the design and turn RTL simulation into a distributed HPC problem. We introduce Metro-MPI to enable fast behavioural RTL simulation of emerging-scale chips. In Metro-MPI, each chip is simulated with many independent processes, communicating via the standard Message Passing Interface (MPI) distributed computing runtime.

> Metro-MPI requires minimal design changes to enable parallel RTL simulation across multiple nodes in an HPC or cloud infrastructure. Metro-MPI can be used through the whole design process, starting with early-stage designs, unlike specialised hardware used to emulate RTL models such as FPGAs and hardware emulators.

### NoC 信号打包

> For our case study, partitions are connected through NoC routers' input and output signals which we turn into Metro-MPI messages. In OpenPiton, each tile-tile connection has 3 NoCs in each direction, and each NoC has three signals: Valid, Data, Yummy. All signals between two tiles can be grouped and sent using a single MPI message. Empirically, we see roughly a 10% improvement on a single node (regardless of design size) with this grouping, compared to partial or no grouping.

### Multi-Tile Granule

> Large designs can have hundreds of tiles so partitioning them using a single tile per MPI process (a "single-tile granule" or STG) requires many HPC nodes. We created multi-tile granules (MTGs) with multiple tiles in one MPI process, to enable scaling with fewer resources. As the granule grows, so does the amount of computation for an MPI process per simulated cycle. The advantage is lower communication costs from all intra-granule communication happening locally and the grouping of all signals between pairs of processes into a single MPI message.

### 性能数据

| 配置 | 顺序加速比 | 实际 KIPS | 实际 KCPS |
|------|-----------|-----------|-----------|
| 1×1 | 1.24 | 3.26 | 2.7 |
| 2×2 | 4.48 | 30.23 | 4.7 |
| 4×4 | 9.09 | 190.49 | 6.1 |
| 8×8 | 23.73 | 744.77 | 6.9 |
| 16×16 | 51.09 | 2698.12 | 6.7 |
| 32×32 | **135.98** | — | — |

> Speedup compared to sequential and multithreaded RTL simulations of up to 135.98× and 9.29×, respectively. Exceptional scaling of RTL simulation to tens of nodes, reaching 2.7 MIPS for a 10B+ transistor, 1,024-core chip.

## 附加信息

- **会议**: DATE 2023
- **DOI**: 10.23919/DATE56975.2023.10137080
- **开源代码**: https://github.com/metro-mpi
- **使用案例**: OpenPiton+Ariane tiled manycore (1,024 tiles, 32×32 NoC)
- **对比基准**: Verilator 顺序/多线程仿真，商业仿真器

## 参考链接

- https://jbalkind.github.io/docs/date_2023_camera_ready.pdf
- https://past.date-conference.com/proceedings-archive/2023/DATA/170.pdf
- https://github.com/metro-mpi
- https://upcommons.upc.edu/handle/2117/390396

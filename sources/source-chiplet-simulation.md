---
title: Multi-Die / Chiplet RTL 仿真与跨层设计资料汇编
description: 搜集 Chiplet、Multi-Die、2.5D/3D IC 的 RTL 仿真、Interposer 建模与跨层仿真框架的文献
source_url: "https://dl.acm.org/doi/10.1145/3665314.3680474"
source_type: "paper"
author: "Anna Burdina, Gabriel Catel Torres, Davide Schiavone 等 (EPFL/HE-SO)"
date: "2024-08"
tags: ["chiplet", "multi-die", "interposer", "cross-layer-simulation", "rtl-emulation", "fpga", "serial-link", "2.5d-ic"]
keywords: ["chiplet simulation", "multi-die RTL", "interposer", "3D IC", "Serial Link", "AXI", "X-HEEP", "PULP", "gem5", "Verilator", "FPGA emulation"]
capture_date: "2025-07-18"
---

# Multi-Die / Chiplet RTL 仿真与跨层设计资料汇编

## 来源

- [Cross-layer Exploration of 2.5D Energy-Efficient Heterogeneous Chiplets Integration (ISLPED 2024)](https://dl.acm.org/doi/10.1145/3665314.3680474)
- [Parendi: Thousand-Way Parallel RTL Simulation (ASPLOS 2025)](https://arxiv.org/abs/2403.04714) — Chiplet 边界对并行仿真的影响
- [Chiplet-based FPGA Verification (arXiv 2025)](https://arxiv.org/abs/2504.19418) — 基于阻抗感知的 Chiplet 验证
- [Intel PIUMA — Multi-Node & FPGA Emulation](https://arxiv.org/abs/2010.06277)
- [ARENA — SST + MPI + PyMTL](https://arxiv.org/abs/2011.04931)
- [OpenPiton — Manycore with NoC](https://openpiton.org/)

## 摘要

Chiplet（芯粒）技术通过将 SoC 组件分布到多个小裸片（Die）上并经由 Interposer/封装基板互连，解决了单片大芯片的良率问题和成本挑战。然而，跨 Die 通信的延迟、带宽和功耗成为新的设计瓶颈。本汇编覆盖：
1. **跨层仿真框架**（ISLPED 2024）：结合 RTL 级 FPGA 仿真/后布局时序提取与 gem5 全系统仿真，实现 2.5D Chiplet 系统的性能-功耗-温度联合探索；
2. **Chiplet 边界对并行仿真的影响**（Parendi）：跨 Chiplet 的通信延迟导致并行 RTL 仿真加速比显著下降（x64 上超过 8 线程/Chiplet 边界后性能衰减）；
3. **Chiplet 验证与安全**：基于阻抗感知的数字传感方法检测 Chiplet 间互连的篡改和硬件木马。

## 关键要点

### 1. 跨层 Chiplet 仿真框架（ISLPED 2024）

#### 框架概述
- **目标**：在 2.5D 异构 Chiplet 系统的架构设计空间中，寻找高性能/高能效权衡。
- **方法**：将**底层 RTL 仿真/FPGA 验证**（获取精确电路级时序）与**上层 gem5 全系统仿真**（运行真实软件栈、支持操作系统）结合。
- **输入**：RTL 后布局仿真或 FPGA emulation 提取的延迟值 → 校准 gem5 的 CPU 模型、互连时序、加速器抽象模型。

#### 目标平台：X-HEEP + Serial Link
- **X-HEEP**：可配置的 RISC-V 平台，覆盖从 mW 级微控制器到高能效异构 SoC，支持 OpenHW Group CPU、OpenTitan 外设、PULP 总线组件。
- **Serial Link IP**（PULP 组开发）：
  - 接口：AXI4 一侧，DDR 源同步接口另一侧。
  - 协议：实现 OSI 三层（Network, Data Link, Physical）。
  - 参数化：通道数和每通道线数（Lanes）可配置，支持高带宽/低延迟/低带宽应用。
  - 特性：全数字、透明、含 CDC（Clock Domain Crossing）功能。

#### 性能数据（Serial Link 仿真）
- **Verilator 仿真**：100 MHz 时钟，物理层时钟分频因子为 4。
- **最大带宽**：32 通道 × 8 Lane 配置下可达 **350 Mbps**。
- **最小配置**：单通道 × 4 Lane 下 **14.5 Mbps**。
- **带宽扩展性**：通道数增加带来线性带宽提升。
- **面积开销**：Xilinx Z-7020 FPGA 上，单通道 4 Lane 比基础 X-HEEP 面积增加 **<5%**；单通道 8 Lane 增加 **<8%**。
- **时钟域**：Serial Link 内部时钟远高于 CPU 时钟（100 MHz），确保瓶颈保持在内部总线而非跨 Die 链路。

#### 关键设计权衡
- **串行 vs 并行**：串行通信减少引脚数、封装尺寸、Interposer 层数；消除并行线的同时开关噪声（SSO）；功耗低于 HSTL 等高速并行标准。
- **多通道 vs 单通道多 Lane**：多通道适合高带宽场景（内存-加速器），但同步开销和故障检测面积更大；单通道多 Lane 适合核间通信，开销更低。
- **FPGA 验证**：15 MHz 系统时钟，物理层分频因子 4，单通道 4 Lane 最小配置。FPGA emulation 结果与 Verilator 仿真一致。

### 2. Parendi — Chiplet 边界对并行 RTL 仿真的影响

#### 关键发现
- **非均匀通信**：跨 Chiplet 或 Socket 的通信延迟显著高于片内/包内通信。
- **Verilator 多线程**：在 AMD EPYC（ae4）上，加速比在 **8 线程（Chiplet 边界）** 后迅速衰减；在 Intel Xeon（ix3）上，**28 线程（Socket 边界）** 后出现显著下降。
- **结论**：跨 Chiplet 的通信延迟增加对并行仿真器有显著性能成本，分区策略必须考虑物理封装边界。

#### 超线性加速现象
- 在 Chiplet 内部，增加核心数可减少每核心代码量/数据量，降低 Cache 压力，减少 Cache Miss，从而出现超线性加速。
- 一旦工作集超出本地 Cache 容量或 Chiplet 间通信成本占主导，超线性收益消失。

### 3. Chiplet 验证与安全（arXiv 2025）

- **问题**：Chiplet 生态系统中，不同来源的 Chiplet 集成到同一封装时面临供应链安全威胁（篡改、硬件木马）。
- **方法**：基于**数字阻抗感知**（Digital Impedance Sensing）的验证框架，在 Chiplet-0（SLR0）部署验证硬件，监测相邻及远端 Chiplet 的阻抗指纹。
- **场景**：
  1. 检测相邻 Chiplet 中不同硬件模块的阻抗指纹；
  2. 检测 Interposer 通信线利用率修改（模拟篡改/探针攻击）；
  3. 监测远端 Chiplet（SLR2）中单个 IP 的放置变化；
  4. 检测相邻 Chiplet 中的微小硬件木马。

### 4. Intel PIUMA — 多芯片仿真与 FPGA 验证

- **多节点仿真**：FSim（功能仿真器）基于 MPI 在多主机上运行，处理海量线程和内存；Sniper（时序仿真器）作为单节点多线程应用运行，避免跨机器同步瓶颈。
- **规模**：最大模拟 **256 个 PIUMA 块**（32 芯片，16,896 线程）。
- **FPGA Emulation**：
  - 始终从最新 RTL 生成，包含所有硬件层级和第三方 IP。
  - 与 RTL 团队并行开发，在流片前修复了 **50+ 关键 bug**。
  - 用于功能验证和性能相关性评估。

### 5. OpenPiton — 多 Tile 众核与 NoC

- **架构**：基于 Tile 的众核，Tile 间通过 NoC 连接，外设和加速器使用 NoC 或 AXI。
- **Metro-MPI 应用**：OpenPiton 是 Metro-MPI 的主要验证平台，利用 NoC 边界将 Tile 分组到不同 MPI 进程，实现分布式 RTL 仿真。
- **规模**：支持 1x1 到 32x32（1,024 核），每个 Tile 约 1,300 万晶体管。

## 对 RTL 仿真器多线程化的启示

1. **Interposer/跨 Die 链路是新的性能瓶颈**：在 Chiplet 架构中，跨 Die 通信延迟（通常通过 Serial Link、UCIe、PCIe 等）远高于片内总线。多线程 RTL 仿真器在分区时，应将**同一 Die 内的模块保留在同一线程/进程**，将跨 Die 接口作为显式的同步边界。这类似于 Metro-MPI 利用 NoC 边界进行分区。

2. **Serial Link 的 AXI 接口标准化**：PULP Serial Link 在 Die 侧暴露 AXI4 接口，这意味着跨 Die 通信可以抽象为 AXI 事务。多线程仿真器可以将 AXI 作为"跨线程总线契约"，在每个仿真周期结束时同步 AXI 通道信号，而内部状态可以独立推进。这与 NoC 的延迟不敏感接口原理一致。

3. **时钟域交叉（CDC）的仿真复杂度**：Serial Link 包含 CDC 功能，意味着跨 Die 通信涉及不同时钟域。多线程仿真器若按 Die 分区，需要处理多时钟域的同步问题：
   - 若各 Die 时钟频率不同，线程推进速度不同，需要更复杂的同步机制（如基于时间的同步而非基于周期的同步）；
   - 若使用统一的仿真时钟，CDC 逻辑的 FIFO 深度和握手信号需要精确建模。

4. **FPGA Emulation 作为黄金参考**：Intel PIUMA 和 ISLPED 2024 的工作都强调 FPGA  emulation 在验证 RTL 设计中的关键作用。对于多线程 RTL 仿真器，FPGA 的周期精确结果可以作为"黄金参考"，用于验证多线程仿真在功能等价性和时序准确性上的正确性。

5. **面积与带宽的 Chiplet 级权衡**：ISLPED 2024 的实验显示，增加 Serial Link 通道数可线性提升带宽，但面积和故障率也随之增加。多线程仿真器在 Chiplet 场景下的性能模型，需要考虑跨 Die 链路的带宽限制和争用（contention），而不仅仅是延迟。

6. **Chiplet 边界导致并行加速比"断崖"**：Parendi 的实验明确显示，跨 Chiplet 的通信延迟导致并行仿真加速比在 Chiplet 边界处急剧下降。对于基于多核 CPU 的多线程仿真器，这意味着：
   - **NUMA 感知**：如果仿真器运行在 NUMA 系统上，应避免将需要频繁通信的模块分配到不同 NUMA 节点；
   - **Cache 层次利用**：同一 Chiplet/Socket 内的线程共享 L3 Cache，应利用此特性减少跨线程通信的数据传输量。

## 原文摘录

> "To guide architectural exploration in 2.5D chiplet-based systems and find the best energy/performance trade-offs, we need to find ways to accurately simulate heterogeneous systems under representative modern workloads and communicated via standard interconnects. Cross-layer simulation aims at putting together the benefits of lower-level layout and RTL simulation and emulation — which enables the obtention of very accurate circuit-level timings — with those of full system-level simulation."
> — ISLPED 2024

> "The Serial Link is a simple, transparent, all-digital serialization link featuring a Double-Data-Rate (DDR) source-synchronous interface on one side and an AXI4 interface on the other. It implements the three lowest layers of the Open Systems Interconnection reference model: Network, Data Link, and Physical layers."
> — ISLPED 2024, Serial Link 描述

> "With a clock frequency of 100MHz, a serial link using a clock division factor of four can achieve up to 350Mbps in a 32-channel, 8-lane configuration. This is significantly higher than the 14.5Mbps achieved with a single channel and four lanes."
> — ISLPED 2024, Serial Link 带宽数据

> "The implemented designs show that the serial link occupies a minor part of the resources, altering the X-HEEP basic configuration area by less than 5% for a single channel with 4 lanes and 8% for a single channel with 8 lanes."
> — ISLPED 2024, FPGA 面积数据

> "Communication is non-uniform. On ae4, speedups fade after 8 threads (chiplet boundary). On ix3, we see a significant drop after 28 threads (socket boundary). The increased communication latency across chip boundaries has a noticeable performance cost, and parallel simulators should be aware of it."
> — Parendi (ASPLOS 2025)

> "We also made extensive use of FPGA emulation to verify the RTL design... This allowed the RTL teams to fix over 50 critical bugs before tape-out."
> — Intel PIUMA

## 相关链接

- [ISLPED 2024 Cross-layer Chiplet 论文](https://dl.acm.org/doi/10.1145/3665314.3680474)
- [Parendi 论文 (ASPLOS 2025)](https://arxiv.org/abs/2403.04714)
- [Chiplet Verification 论文 (arXiv 2025)](https://arxiv.org/abs/2504.19418)
- [Intel PIUMA 论文](https://arxiv.org/abs/2010.06277)
- [OpenPiton 官网](https://openpiton.org/)
- [X-HEEP 平台](https://github.com/esl-epfl/x-heep)
- [PULP 平台](https://github.com/pulp-platform)
- [ARENA 论文](https://arxiv.org/abs/2011.04931)

---
title: Network-on-Chip (NoC) RTL 仿真与性能分析资料汇编
description: 搜集 NoC 仿真器、RTL 级 NoC 实现、AXI 接口与拓扑性能的相关文献与开源项目
source_url: "https://www.andrew.cmu.edu/user/sobla/projects/noc/"
source_type: "doc"
author: "多篇论文 / 开源项目综合"
date: "2023-2025"
tags: ["noc", "rtl-simulation", "axi", "mesh", "torus", "fpga", "interconnect"]
keywords: ["NoC", "RTL simulation", "AXI-Stream", "mesh topology", "torus topology", "Verilator", "BookSim", "Garnet", "ReCONNECT", "Proteus"]
capture_date: "2025-07-18"
---

# NoC 仿真与 RTL 实现资料汇编

## 来源

本文件综合多篇学术论文与开源项目，核心来源包括：
- [ReCONNECT NoC (CMU)](https://www.andrew.cmu.edu/user/sobla/projects/noc/) — SystemVerilog RTL 实现
- [Proteus: HLS-based NoC Generator](https://past.date-conference.com/proceedings-archive/2023/DATA/80.pdf) — HLS + FPGA 验证
- [BookSim / Garnet](https://www.researchgate.net/publication/288492733) — C++ 周期精确 NoC 模拟器
- [Metro-MPI (UPC)](https://upcommons.upc.edu/handle/2117/390396) — 利用 NoC 边界进行分布式 RTL 仿真
- [Khan et al. Mesh & Torus Simulation](https://dspace.library.uvic.ca/bitstreams/4f958cf9-da19-44ca-bc27-4ab99e5cba52/download) — 虚拟通道性能分析

## 摘要

Network-on-Chip (NoC) 是多核/众核 SoC 的片上通信骨干。本汇编覆盖三个层面：
1. **C++ 级周期精确模拟器**（BookSim、Garnet）—— 用于架构探索，速度快但非硬件感知；
2. **RTL 级可综合 NoC**（ReCONNECT、Proteus）—— 直接生成 SystemVerilog，支持 FPGA 验证与真实频率评估；
3. **NoC 作为分布式 RTL 仿真的天然边界**（Metro-MPI）—— 利用 NoC/AXI 的延迟不敏感接口将仿真分区到多节点。

关键结论：AXI-Stream 封装、虫洞路由、信用流控是 RTL NoC 的标配；Mesh 与 Torus 拓扑在 4x4 至 8x8 规模下，VC 数量对饱和吞吐量和平均包延迟有显著影响。

## 关键要点

### 1. ReCONNECT — RTL-native FPGA NoC
- **频率**：Agilex 7 FPGA 上超过 **600 MHz**（原始版本标称 >500 MHz，最新页面更新为 >600 MHz）。
- **拓扑**：Mesh、Torus、Ring、Double-Ring、Butterfly、Fat-Tree、Fully Connected。
- **接口**：原生 **AXI-Stream** wrapper，支持跨平台 CDC（Clock Domain Crossing）与宽度转换。
- **流控**：虫洞路由（Wormhole Routing）+ 信用流控（Credit-Based Flow Control）+ 全交叉开关（Full Crossbar）。
- **仿真**：Verilator（默认）与 ModelSim 双支持；回归测试覆盖所有拓扑与配置；提供 `generate_load_latency.py` 自动负载-延迟扫描工具。
- **GitHub**: `shashankov/ReCONNECT`

### 2. Proteus — HLS-based NoC 生成器 + FPGA 验证
- **生成**：从 HLS 生成可综合 RTL，支持 Ring/Mesh/Torus 三种基础拓扑（占开源 NoC 生成器用户配置约 60%）。
- **参数范围**：Node 数 2–1024，链路宽度 8–1024 bit，VC 每端口 1–16，路由算法 XY/YX/North-Last/West-First。
- **FPGA 加速**：Ultra96v2 FPGA 板上运行速度比 Garnet（C++ 模拟器）快 **4.07–10.73 倍**。
- **RTL 仿真**：与 C++ 级模拟器速度相近，同时提供硬件实现影响评估。

### 3. BookSim / Garnet — C++ 周期精确模拟器
- **BookSim**：支持参数化拓扑、路由函数、流量负载、路由器微架构，已与 RTL 路由器实现验证准确性。
- **Garnet**（gem5 集成）：学术与工业界广泛使用的 NoC 模拟器，支持多种拓扑和组件配置。
- **局限**：大多数此类模拟器是硬件无感知（hardware-unaware）的，适合快速仿真但可能忽略硬件实现细节，导致误导性结论。

### 4. 虚拟通道（Virtual Channel）对 Mesh/Torus 性能的影响
- **4x4 Mesh**：VC8 在饱和点后吞吐量比 VC1 高 60%；VC16 在增大注入率时平均包延迟最低。
- **4x4 Torus**：VC16 吞吐量最高，阈值超过 0.8 flits/cycle；VC4 平均包延迟峰值最高。
- **8x8 Mesh**：VC8 吞吐量最高，VC1 最低；高注入率下平均包延迟显著上升。
- **通用规律**：增加 VC 数量通常降低延迟并提高吞吐量，但带来面积与功耗开销。

### 5. AXI 协议与 NoC 的桥接
- ReCONNECT 提供 `axis_mesh.sv`、`axis_torus.sv` 等 AXI-Stream wrapper。
- 包含 `axis_serializer_shim_in` / `axis_deserializer_shim_out` 支持串行化/反串行化。
- 双时钟 FIFO wrapper（`dcfifo_wrapper.sv`）支持 Altera（Intel）与 AMD（Xilinx）双平台。

## 对 RTL 仿真器多线程化的启示

1. **NoC 作为天然分区边界**：Metro-MPI 的核心洞察之一。NoC 路由器之间的延迟不敏感接口（Latency-Insensitive Interface）使得整个 SoC 可以按 Tile 为单位切分到不同 MPI 进程，每周期内各进程并行仿真后通过 MPI 同步。这与多线程 RTL 仿真器的分区策略（如按模块或按层次划分）高度相关。

2. **AXI-Stream 是标准切分面**：AXI/AXI-Stream 作为广泛使用的标准总线协议，在多线程仿真器中可以充当“通信契约”—— 只要保证 AXI 接口信号在周期边界的一致性，模块内部可以独立并行推进。这降低了跨线程同步的复杂度。

3. **虫洞路由 + 信用流控的仿真特性**：信用流控意味着存在跨周期的状态依赖（信用计数器），这增加了多线程仿真的记录-回放（log-and-replay）或乐观同步（optimistic synchronization）的复杂度。多线程仿真器需要特别处理这类跨周期状态。

4. **FPGA 加速 vs 软件仿真的权衡**：Proteus 的实验显示 FPGA 上运行比 C++ 模拟器快 4–10 倍，但编译时间更长。对于多线程 RTL 仿真器，参考此数据可以设定性能目标：在 x86 多核上达到 FPGA 仿真速度的某个比例（如 10–30%）即为可接受。

## 原文摘录

> "ReCONNECT is a highly parameterizable, high-performance soft Network-on-Chip (NoC) designed to be customizable to the needs of the application while remaining resource-minimal. Written directly in SystemVerilog (RTL), the NoC is specially optimized for high-frequency operations, exceeding 600 MHz on modern FPGA architectures."
> — ReCONNECT 项目主页

> "NoC simulators provide a fast and efficient way to model network traffic. For faster performance modeling, most network simulators are implemented in high-level languages (e.g. C++) instead of RTL. Since most such simulators are hardware unaware, they are ideal for faster simulation but fail to consider hardware implementation details."
> — Proteus (DATE 2023)

> "Metro-MPI works particularly well with replicated blocks of comparable size, such as manycores with NoCs. For each cycle, each process simulates in parallel then synchronises with its neighbours. This is enabled by the latency-insensitive interfaces throughout the design in the form of NoCs, AXI, etc."
> — Metro-MPI (DATE 2023)

> "We see speedup in the run-time of FPGA up to 10.73 times faster compared to Garnet runtime."
> — Proteus FPGA Evaluation

## 相关链接

- [ReCONNECT NoC 项目主页](https://www.andrew.cmu.edu/user/sobla/projects/noc/)
- [ReCONNECT GitHub](https://github.com/shashankov/ReCONNECT)
- [Proteus 论文 (DATE 2023)](https://past.date-conference.com/proceedings-archive/2023/DATA/80.pdf)
- [Metro-MPI 论文 / UPC](https://upcommons.upc.edu/handle/2117/390396)
- [BookSim / ResearchGate](https://www.researchgate.net/publication/288492733)
- [Garnet (gem5)](https://github.com/gem5/gem5)
- [NoC Mesh & Torus 仿真论文 (UVic)](https://dspace.library.uvic.ca/bitstreams/4f958cf9-da19-44ca-bc27-4ab99e5cba52/download)

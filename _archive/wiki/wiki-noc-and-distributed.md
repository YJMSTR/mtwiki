---
id: "wiki-noc-and-distributed"
title: "NoC与分布式RTL仿真"
description: "NoC仿真技术、分布式RTL仿真（Metro-MPI/Parendi/PIUMA）与Chiplet跨层仿真框架的综合指南，提供多线程RTL仿真器的架构决策矩阵与可操作策略"
tags: ["noc", "distributed-rtl", "mpi", "chiplet", "multi-die", "axistream", "metro-mpi", "parendi", "parallel-simulation", "rtl-sim"]
keywords: ["NoC", "Network-on-Chip", "分布式RTL仿真", "Metro-MPI", "Parendi", "ReCONNECT", "Proteus", "Chiplet仿真", "Serial Link", "AXI-Stream", "延迟不敏感接口", "跨层仿真", "BSP", "MPI"]
related_sources:
  - "source-noc-simulation"
  - "source-distributed-rtl"
  - "source-chiplet-simulation"
last_updated: "2026-07-01"
---

# NoC与分布式RTL仿真

随着芯片规模从百亿晶体管迈向千亿，仿真器面对的不再是"设计"，而是**设计群**。NoC（片上网络）原本是连接多核的通信骨干，但在多线程RTL仿真器的语境下，它恰好成为天然的**分区边界**——延迟不敏感、协议标准化、跨Tile通信量有限。本章将NoC仿真、分布式RTL仿真和Chiplet跨层仿真三条线拧成一股：从ReCONNECT在Agilex 7上跑出的600MHz，到Metro-MPI在1024核上堆出的2.7MIPS，再到Parendi在5888核IPU上证明的"x64同步机制才是瓶颈"，最终落到一句话：**分布式是终极扩展路径，但共享内存多线程是前置条件**。

---

## 1. NoC仿真：从架构探索到RTL-native实现

### 1.1 三种NoC仿真器的定位对比

| 仿真器 | 层级 | 核心优势 | 典型用途 | 速度特征 |
|--------|------|----------|----------|----------|
| **BookSim / Garnet** | C++ 周期精确 | 参数化拓扑、快速迭代 | 架构探索、路由算法评估 | 最快，但硬件无感知 |
| **ReCONNECT** | SystemVerilog RTL | 可综合、FPGA实测>600MHz | FPGA验证、真实频率评估 | RTL级，比C++慢但可流片 |
| **Proteus** | HLS生成RTL | HLS→RTL自动生成，4–10x加速 | 快速设计空间探索+FPGA验证 | 比Garnet快4.07–10.73x（FPGA上） |

> **关键洞察**：C++模拟器（BookSim/Garnet）在架构探索阶段不可替代，但它们的"硬件无感知"特性意味着某些结论（如VC数量与面积功耗的权衡）在RTL实现后可能完全反转。Proteus的实验直接将FPGA实现与C++模拟器对比，证明**FPGA运行比Garnet快4–10倍**，但编译时间更长——这要求多线程RTL仿真器在设定性能目标时，必须明确自己处于"验证"还是"探索"阶段。

### 1.2 ReCONNECT：RTL-native NoC的标杆

**ReCONNECT**（CMU / `shashankov/ReCONNECT`）是目前开源领域最成熟的RTL NoC之一，直接写SystemVerilog，不经过HLS抽象层：

- **频率**：Agilex 7 FPGA上 **>600 MHz**，原始版本标称>500 MHz，已迭代优化
- **拓扑**：Mesh、Torus、Ring、Double-Ring、Butterfly、Fat-Tree、Fully Connected（全参数化）
- **接口**：原生 **AXI-Stream wrapper**（`axis_mesh.sv`、`axis_torus.sv`），支持跨平台CDC与宽度转换
- **流控**：虫洞路由（Wormhole Routing）+ 信用流控（Credit-Based Flow Control）+ 全交叉开关
- **仿真**：Verilator（默认）与ModelSim双支持；回归测试覆盖所有拓扑；附带`generate_load_latency.py`自动负载-延迟扫描

```verilog
// ReCONNECT 的 AXI-Stream wrapper 示例：跨拓扑统一接口
// 无论底层是Mesh还是Torus，用户只看到标准的AXI-Stream握手
axis_mesh #(
    .DATA_WIDTH(64),
    .DEST_WIDTH(8),
    .MESH_DIM_X(4),
    .MESH_DIM_Y(4)
) noc_inst (
    .clk(clk),
    .rst_n(rst_n),
    .s_axis_tdata(s_axis_tdata),
    .s_axis_tvalid(s_axis_tvalid),
    .s_axis_tready(s_axis_tready),
    .m_axis_tdata(m_axis_tdata),
    .m_axis_tvalid(m_axis_tvalid),
    .m_axis_tready(m_axis_tready)
);
```

**对多线程仿真器的意义**：ReCONNECT的AXI-Stream wrapper将NoC内部复杂的路由、仲裁、流控全部封装在标准接口之后。这意味着——**如果多线程仿真器按AXI-Stream接口切分设计，内部模块可以独立并行推进，只需在握手信号（`valid`/`ready`/`tdata`）上做周期级同步**。这个切分面足够干净，几乎不需要额外设计修改。

### 1.3 虚拟通道（VC）对Mesh/Torus性能的影响

Khan等人的实验给出了VC数量的量化参考：

| 拓扑 | 规模 | 最优VC | 关键发现 |
|------|------|--------|----------|
| Mesh | 4x4 | VC8 | 饱和点后吞吐量比VC1高60% |
| Torus | 4x4 | VC16 | 吞吐量最高，阈值>0.8 flits/cycle |
| Mesh | 8x8 | VC8 | 高注入率下延迟显著上升 |

> **实操启示**：多线程仿真器在仿真带VC的NoC时，信用流控（credit-based）引入了跨周期状态依赖——信用计数器必须每周期精确同步。这要求线程分区时，**将信用计数器与对应端口绑定在同一分区**，避免跨线程同步信用状态的开销。

---

## 2. 分布式RTL仿真：从单节点到HPC集群

### 2.1 三种分布式方案的对比

| 方案 | 核心机制 | 最大规模 | 关键性能 | 适用场景 |
|------|----------|----------|----------|----------|
| **Metro-MPI** | MPI + 延迟不敏感接口 | 1,024核 / 100亿+晶体管 | 2.7 MIPS，135x加速 | 通用SoC，开源/商业仿真器均可 |
| **Parendi** | IPU BSP + 超图划分 | 5,888核（4 IPU） | 4x加速（vs x64），12x快编译 | 大规模设计，专用硬件加速 |
| **Intel PIUMA** | MPI多节点 + FPGA验证 | 256块 / 16,896线程 | 50+关键bug在流片前修复 | 超大规模加速器，多芯片 |

### 2.2 Metro-MPI：利用NoC边界的通用分布式框架

Metro-MPI的核心洞察极其简洁：**现代SoC已经被NoC/AXI切成了Tile，仿真器只需要把Tile映射到MPI进程**。

**OpenPiton+Ariane 规模扩展数据**：

| 芯片规模 | 核心数 | 编译时间(min) | 仿真速度 | 加速比(vs顺序) |
|----------|--------|---------------|----------|---------------|
| 1x1 | 1 | 5 | 基准 | 1x |
| 2x2 | 4 | 9 | 显著提升 | ~2.5x |
| 4x4 | 16 | 25 | 接近线性 | ~12x |
| 8x8 | 64 | 296 | 良好 | ~50x |
| 32x32 | 1,024 | 4,167 | **2.7 MIPS** | **135.98x** |

- **vs Verilator多线程**：单节点上快 **5.64x (4x4)** 和 **9.29x (8x4)**
- **商业仿真器**：16核x64上，4x4设计获 **8.44x** 仿真时间加速、**7.08x** CPS加速
- **能耗**：典型回归测试能耗降低 **2.53x**

```c
// Metro-MPI 伪代码：每周期两阶段（计算→同步）
for (int cycle = 0; cycle < max_cycles; cycle++) {
    // 阶段1：各MPI进程独立仿真本地Tile
    for (auto& tile : local_tiles) {
        tile.eval();  // 计算所有本地逻辑
    }
    
    // 阶段2：交换NoC/AXI边界信号（延迟不敏感接口）
    for (auto& neighbor : mpi_neighbors) {
        MPI_Sendrecv(local_boundary_signals, ..., neighbor, ...);
    }
    
    // 阶段3：全局同步（确保周期精确性）
    MPI_Barrier(MPI_COMM_WORLD);
}
```

**关键设计假设**：
- 每个Tile约1,300万晶体管（128-bit share vector）
- 1,024 Tile总计超过**100亿晶体管**
- 使用OpenPiton L2修改版，coherence share vector扩展至1,024 bits
- 最大配置32x32使用22个HPC节点（2×Xeon Platinum 8160, 100 Gbit/s Omni-Path）

### 2.3 Parendi：在IPU上证明x64同步才是瓶颈

Parendi将RTL仿真映射到Graphcore IPU的**5,888核**上，使用Bulk-Synchronous Parallel (BSP)模型，每RTL周期两次全局barrier：

**性能对比（vs Verilator x64多线程）**：

| 指标 | 大设计 | 备注 |
|------|--------|------|
| 加速比 | **4.0x** | vs 最强x64多核 |
| 编译时间 | **12x快** | 编译时间大幅缩短 |
| 内存占用 | **18x少** | 内存效率极高 |
| 单IPU强扩展 | 1,472 tiles | 性能单调提升 |
| 多IPU扩展 | 1,472→5,888 | 额外 **60%** 性能提升（lr9设计） |

**同步开销的致命对比**：

| 架构 | Barrier开销 | 掩盖开销所需指令 | 结论 |
|------|-------------|-------------------|------|
| IPU | 几百个IPU周期 | 几千条指令 | 硬件barrier极轻量 |
| x64 | 数千周期 | 数十万条指令 | 原子内存访问太重，不适合细粒度并行 |

> **对多线程仿真器的核心启示**：Parendi的同步开销数据直接回答了"为什么Verilator多线程在x64上扩展性差"。x64的缓存一致性协议和原子操作是瓶颈，不是RTL算法本身。这意味着在软件层面，**必须减少全局barrier频率，或者用局部同步替代全局同步**。

### 2.4 Intel PIUMA：多节点+FPGA验证的工业级实践

Intel PIUMA的仿真基础设施为超大规模设计提供了参考架构：

- **FSim（功能仿真器）**：基于MPI在多台主机上运行，处理海量线程和内存需求
- **Sniper（时序仿真器）**：作为单节点多线程应用运行，**避免跨机器同步瓶颈**
- **最大规模**：模拟 **256个PIUMA块**（32芯片，16,896线程）
- **FPGA验证**：始终从最新RTL生成，包含所有硬件层级和第三方IP；在流片前修复了**50+关键bug**

> **关键策略**：PIUMA将**功能仿真**（多节点MPI）和**时序仿真**（单节点多线程）解耦。时序仿真避免跨机器同步，因为时序精度对同步延迟极其敏感。多线程RTL仿真器在需要精确时序验证时，也应考虑类似的"时序敏感的留在单节点，功能验证可分布式"策略。

---

## 3. Chiplet仿真：跨Die通信的边界效应

### 3.1 跨层Chiplet仿真框架（ISLPED 2024）

EPFL/HE-SO的跨层框架将**RTL级FPGA仿真**与**gem5全系统仿真**结合，在2.5D Chiplet系统的架构设计空间中探索性能-功耗-温度权衡。

**Serial Link IP的关键参数**（PULP组开发）：

| 配置 | 带宽 | 面积开销（Xilinx Z-7020） |
|------|------|---------------------------|
| 单通道×4 Lane | 14.5 Mbps | <5% |
| 单通道×8 Lane | ~29 Mbps | <8% |
| 32通道×8 Lane | **350 Mbps** | 线性扩展 |

- **接口**：AXI4一侧，DDR源同步接口另一侧
- **协议**：OSI三层（Network, Data Link, Physical）
- **特性**：全数字、透明、含CDC功能
- **时钟**：Serial Link内部时钟远高于CPU时钟（100 MHz），确保瓶颈在总线而非跨Die链路

> **Verilator仿真**：100 MHz时钟，物理层分频因子4，FPGA emulation结果与仿真一致。

### 3.2 Chiplet边界对并行仿真的"断崖"效应

Parendi在AMD EPYC（ae4）和Intel Xeon（ix3）上的实验给出了明确的并行扩展边界：

| 平台 | 线程数 | 现象 | 物理边界 |
|------|--------|------|----------|
| AMD EPYC (ae4) | ≤8 | 超线性加速（缓存压力降低） | **Chiplet边界** |
| AMD EPYC (ae4) | >8 | 加速比迅速衰减 | 跨Chiplet延迟飙升 |
| Intel Xeon (ix3) | ≤28 | 良好扩展 | **Socket边界** |
| Intel Xeon (ix3) | >28 | 显著下降 | 跨Socket NUMA通信 |

**超线性加速的内在机制**：Chiplet内部增加核心数→每核心代码量/数据量减少→Cache压力降低→Cache Miss减少→出现超线性加速。一旦工作集超出本地Cache容量或跨Chiplet通信占主导，超线性收益立即消失。

```
加速比
  │
  │     ╱ 超线性区
  │    ╱
  │   ╱    ← 8线程（Chiplet边界）
  │  ╱╱────╲──── 断崖
  │ ╱         ╲
  │╱           ╲── 缓慢衰减区
  └──────────────────────→ 线程数
```

> **对多线程仿真器的致命启示**：如果你的仿真器运行在AMD EPYC上，**8线程是一个硬边界**。超过8线程需要跨Chiplet通信，性能收益可能为负。这意味着：
> 1. **同一Chiplet内的模块应放在同一线程/NUMA节点**
> 2. **跨Chiplet的模块应作为独立进程（MPI）而非线程**
> 3. **线程数不要超过物理Chiplet核心数**

---

## 4. 对多线程RTL仿真器的启示

### 4.1 NoC/AXI是天然的分区边界

Metro-MPI和Parendi的共同结论：**NoC路由器之间的延迟不敏感接口（Latency-Insensitive Interface）使得整个SoC可以按Tile为单位切分到不同进程/线程**。多线程RTL仿真器的分区策略应借鉴此思路：

- **按AXI/AXI-Stream接口切分**：保证接口信号在周期边界的一致性，模块内部独立推进
- **按Tile/Chiplet边界切分**：利用物理设计的天然结构，减少跨分区通信量
- **信用流控特殊处理**：信用计数器跨周期依赖，应绑定到同一分区

### 4.2 同步开销决定扩展性上限

Parendi的定量数据表明：
- **x64 barrier**：数千周期，需要数十万指令掩盖
- **IPU barrier**：几百周期，几千指令即可掩盖

**多线程仿真器的策略选择**：

| 同步策略 | 适用场景 | 开销 | 实现复杂度 |
|----------|----------|------|------------|
| **全局Barrier（每周期）** | 小设计、强验证需求 | 高 | 低 |
| **局部同步（按模块/时钟域）** | 中等规模、多时钟域 | 中 | 中 |
| **乐观同步（Time Warp）** | 大规模、稀疏计算 | 低（冲突时高） | 高 |
| **BSP（Parendi风格）** | 专用硬件（IPU/Groq） | 极低 | 中 |

### 4.3 通信量 > 通信距离

Parendi的通信模型：IPU内部通信延迟取决于每tile发送的字节数（b），而非tile总数（m）；跨IPU时取决于总通信量（m×b）。**分区时优先最小化跨线程通信量，而非简单追求负载均衡**。

---

## 5. 架构决策：什么时候分布？什么时候多线程？什么时候单线程？

### 5.1 决策矩阵

```
                    ┌─────────────────────────────────────────┐
                    │  设计规模  │  核心特征  │  推荐方案      │
┌───────────────────┼───────────┼───────────┼───────────────┤
│  单线程顺序仿真    │  <1亿晶体管│ 小模块   │  单线程（Verilator默认）│
│  共享内存多线程    │  1-100亿   │ 单节点   │  4-8线程（Verilator MT）│
│  NUMA-aware多线程  │  10-100亿  │ 多Socket │  ≤28线程，按Socket绑定  │
│  分布式MPI         │  >100亿    │ 多节点   │  Metro-MPI风格         │
│  专用硬件加速      │  任意规模  │ 可采购   │  Parendi/IPU或FPGA     │
└───────────────────┴───────────┴───────────┴───────────────┘
```

### 5.2 何时分布？何时多线程？何时单线程？

| 场景 | 判断条件 | 推荐方案 | 理由 |
|------|----------|----------|------|
| **单线程** | 设计<1亿晶体管；验证周期短；不需要回归测试 | 单线程Verilator | 多线程开销>并行收益（Issue #2913） |
| **多线程（4-8核）** | 设计1-50亿晶体管；运行在现代x64服务器；需要中等加速 | Verilator MT，静态MTask分区 | 在Chiplet边界内，同步开销可控 |
| **多线程（8-28核）** | 设计50-200亿晶体管；多Socket服务器；NUMA-aware | 按Socket绑定线程，局部同步 | 跨过Chiplet但不过Socket，需NUMA感知 |
| **分布式MPI** | 设计>200亿晶体管；多核/众核SoC；有HPC集群 | Metro-MPI，按Tile/NoC边界分区 | 单节点内存和计算都不够，必须跨节点 |
| **FPGA Emulation** | 需要流片前验证；有FPGA板卡；RTL冻结 | 始终从最新RTL生成，PIUMA风格 | 周期精确、真实硬件时序、可发现50+bug |

### 5.3 按Chiplet/Tile边界分区的具体策略

```cpp
// 分区决策伪代码：根据物理设计结构决定仿真分区
enum PartitionStrategy {
    SINGLE_THREAD,       // 小设计
    SHARED_MEMORY_MT,    // 单节点多线程
    NUMA_AWARE_MT,       // 跨Socket但同机器
    DISTRIBUTED_MPI,     // 多节点MPI
    FPGA_EMULATION       // FPGA验证
};

PartitionStrategy choose_partition_strategy(
    uint64_t total_transistors,
    uint32_t num_tiles,
    uint32_t num_chiplets,
    bool has_hpc_cluster,
    bool has_fpga_board
) {
    if (total_transistors < 100e6) {
        return SINGLE_THREAD;  // 1亿以下，单线程最稳
    }
    if (num_chiplets > 1 && has_hpc_cluster) {
        return DISTRIBUTED_MPI;  // 多Chiplet且有HPC，直接分布式
    }
    if (num_tiles > 64 && !has_hpc_cluster) {
        return NUMA_AWARE_MT;    // Tile多但无HPC，NUMA-aware多线程
    }
    if (num_tiles <= 64) {
        return SHARED_MEMORY_MT; // 64 Tile以内，共享内存多线程
    }
    if (has_fpga_board) {
        return FPGA_EMULATION;   // 有FPGA优先，尤其流片前
    }
    return SINGLE_THREAD;        // 默认回退
}
```

---

## 6. 可操作的设计建议

### 6.1 按Chiplet边界分区

1. **识别物理边界**：从物理设计团队获取Chiplet/Die的拓扑图，将同一Die内的模块映射到同一线程/进程
2. **延迟不敏感接口作为同步点**：AXI、AXI-Stream、NoC路由器的端口是天然同步点，每周期只在这些接口处同步
3. **Serial Link/UCIe作为跨进程边界**：跨Die的通信链路天然适合MPI进程间通信，带宽和延迟模型可直接映射到MPI的`Sendrecv`延迟

### 6.2 AXI天然适合分布式

```verilog
// 将AXI接口作为跨线程/跨进程的"契约"
// 线程A（本地Tile）                         线程B（远端Tile）
// ───────────────────                      ───────────────────
// 内部逻辑推进 → 更新AXI输出信号 ───→ 接收AXI输入 → 内部逻辑推进
//  ←──────────────────
// 同步周期：每周期结束时，所有AXI通道必须一致

// 关键假设：AXI是延迟不敏感的
// 允许信号延迟1-2个周期到达，不影响功能正确性
// 这给了分布式仿真器"松弛"（slack）来掩盖通信延迟
```

### 6.3 线程数不超过Chiplet核心数

| 硬件平台 | 最大推荐线程数 | 理由 |
|----------|---------------|------|
| AMD EPYC 单Chiplet | 8 | 8线程后跨Chiplet，延迟飙升 |
| AMD EPYC 双Socket | 16-32 | 按Socket绑定，不跨NUMA |
| Intel Xeon 单Socket | 28-32 | 28线程后跨Socket，性能下降 |
| Intel Xeon 双Socket | 56-64 | 按Socket绑定，使用local memory |
| ARM Neoverse N1 | 视Chiplet而定 | 通常16-32核/Chiplet |

### 6.4 编译时间与仿真速度的权衡

Metro-MPI的数据揭示了一个残酷的工程现实：

| 规模 | 编译时间 | 仿真速度 | 编译:仿真比 |
|------|----------|----------|------------|
| 1x1 | 5 min | 基准 | — |
| 8x8 | 296 min | 良好 | 编译成本显著上升 |
| 32x32 | 4,167 min | 2.7 MIPS | 编译时间占主导 |

> **建议**：对于需要频繁迭代的设计（前端开发阶段），**优先选择编译时间短的方案**（单线程或轻量多线程）。对于最终验证阶段（后端、回归测试），可以承受长编译时间换取仿真速度。或者，采用**运行时动态分区**来避免编译时的分区决策，但这会增加运行时开销。

### 6.5 用FPGA Emulation作为黄金参考

Intel PIUMA和ISLPED 2024的工作都强调：
- FPGA emulation始终从最新RTL生成，包含所有层级和第三方IP
- 与RTL团队并行开发，在流片前修复**50+关键bug**
- 周期精确结果可用于验证多线程仿真在功能等价性和时序准确性上的正确性

> **操作建议**：多线程RTL仿真器应建立"FPGA golden reference"回归测试，将多线程仿真结果与FPGA单周期精确结果逐周期对比，确保并行化没有引入功能偏差。

---

## 7. 总结

| 维度 | 结论 |
|------|------|
| **NoC作为分区边界** | 延迟不敏感接口（AXI/AXI-Stream）使得Tile级并行成为理论可行、工程可行的方案 |
| **分布式是终极路径** | 100亿+晶体管必须分布式，单节点内存和计算都不够 |
| **多线程是前置条件** | 分布式需要每个节点内部高效并行，单节点效率直接决定集群效率 |
| **x64同步是瓶颈** | Parendi证明RTL算法可并行，x64的缓存一致性和原子操作拖后腿 |
| **Chiplet边界是硬边界** | AMD EPYC 8线程后、Intel Xeon 28线程后，性能断崖式下降 |
| **AXI是标准切分面** | 按AXI接口切分设计，跨线程通信量最小化，同步复杂度最低 |
| **FPGA是最终验证** | 多线程仿真器的功能正确性，最终要靠FPGA golden reference确认 |

> **一句话策略**：小设计单线程，中等设计按Chiplet内多线程（≤8/≤28），超大规模按Chiplet/Tile边界分布式（MPI），全阶段用FPGA验证兜底。延迟不敏感接口（AXI）是贯穿所有层级的统一分区语言。

---

## 参考文献

- ReCONNECT NoC: https://github.com/shashankov/ReCONNECT
- Proteus (DATE 2023): https://past.date-conference.com/proceedings-archive/2023/DATA/80.pdf
- Metro-MPI (DATE 2023): https://upcommons.upc.edu/handle/2117/390396
- Parendi (ASPLOS 2025): https://arxiv.org/abs/2403.04714
- ISLPED 2024 Cross-layer Chiplet: https://dl.acm.org/doi/10.1145/3665314.3680474
- Intel PIUMA: https://arxiv.org/abs/2010.06277
- BookSim / Garnet: https://github.com/gem5/gem5
- X-HEEP Platform: https://github.com/esl-epfl/x-heep

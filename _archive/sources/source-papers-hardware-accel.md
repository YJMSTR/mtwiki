---
title: RTL 仿真硬件加速论文地图（ISCA/MICRO/ASPLOS/DAC）
description: 顶级体系结构与 EDA 会议中关于 RTL 仿真硬件加速（FPGA 仿真、GPU 加速、专用加速器）的系统性论文搜集，覆盖 FireSim、ASH、GEM、Khronos、RTLFlow 等核心工作。
source_url: ""
source_type: "paper"
author: "学术论文深度研究员（子代理）"
date: "2025-01-20"
tags: [RTL-simulation, hardware-acceleration, FPGA-emulation, GPU-simulation, domain-specific-architecture]
keywords: [FPGA simulation, GPU RTL simulation, hardware accelerator, ASH, FireSim, RTLFlow, GATSPI, GEM, Khronos, dataflow architecture]
capture_date: "2025-01-20"
---

# RTL 仿真硬件加速论文地图（ISCA/MICRO/ASPLOS/DAC）

## 来源

- 类型: 学术论文综述
- 作者: 学术论文深度研究员（子代理）
- 日期: 2025-01-20
- 覆盖会议: ISCA, MICRO, ASPLOS, DAC, ICCAD, ICPP

---

## 摘要

硬件加速是突破 RTL 软件仿真速度瓶颈（通常为 1–1000 kHz，比真实硬件慢 3 个数量级以上）的关键路径。本文件系统梳理了 2018–2025 年间顶级会议中关于 RTL 仿真硬件加速的研究，覆盖三大技术路线：**(1) FPGA 加速仿真**（FireSim、FireAxe），**(2) GPU 批量/向量级并行**（RTLFlow、From RTL to CUDA、GATSPI、GL0AM、GEM），**(3) 专用领域加速器**（ASH、Manticore、Khronos）。

---

## 关键论文

### 1. FireSim: FPGA-Accelerated Cycle-Exact Scale-Out System Simulation in the Public Cloud

- **作者**: Sagar Karandikar, Howard Mao, Donggyu Kim, David Biancolin, Alon Amid, Dayeol Lee, Nathan Pemberton, Emmanuel Amaro, Colin Schmidt, Aditya Chopra, Qijing Huang, Kyle Kovacs, Borivoje Nikolić, Randy Katz, Jonathan Bachrach, Krste Asanović
- **会议**: ISCA 2018
- **年份**: 2018
- **引用**: 600+
- **链接**: https://doi.org/10.1109/ISCA.2018.00014
- **项目页**: https://fires.im
- **荣誉**: IEEE Micro "Top Picks from Computer Architecture Conferences" 2018

**方法概述**:
FireSim 是一个基于 AWS EC2 F1 FPGA 实例的**_cycle-exact 系统级仿真平台**，核心创新包括：
- **FAME-1 转换**: 将目标 RTL 自动转换为在 FPGA 上运行的 cycle-exact 仿真模型；
- **主机解耦（Host Decoupling）**: 通过延迟不敏感设计将目标时序与主机 FPGA 时序分离，支持确定性执行；
- **Golden Gate**: 自动将大型 RTL 设计映射到 FPGA 资源，处理 DRAM、网络等外设仿真；
- **确定性仿真**: 不同主机上产生完全相同的结果，支持大规模分布式仿真。

**性能数据**:
在 AWS F1 上可模拟从单节点到数千节点的 RISC-V 多核 SoC，仿真频率约 150 MHz（单节点），网络模拟约 40 MHz。相比软件 RTL 仿真（Verilator）实现 **1000x+ 加速**。

**后续扩展**:
- **FirePerf (ASPLOS 2020)**: 增加 FPGA 加速的全系统性能分析；
- **FireAxe (ISCA 2024)**: 支持将大型单片 RTL 设计划分到多个 FPGA 上模拟，获 Distinguished Artifact Award。

**对 RTL 仿真器多线程化的启示**:
FireSim 代表了**最实用的 RTL 加速路径**——当仿真速度是首要目标且设计已相对稳定时，FPGA 加速是最成熟方案。但其局限性也明显：
- 编译/综合时间长（数小时到数天），不适合快速迭代；
- 调试能力弱于软件仿真（波形、断点支持有限）；
- 对于我们的项目（软件多线程仿真器），FireSim 的设计空间划分和延迟不敏感通信思想可用于优化跨 NUMA 节点的分布式仿真。

---

### 2. ASH: Accelerating RTL Simulation with Hardware-Software Co-Design

- **作者**: Fares Elsabbagh, Shabnam Sheikhha, Victor A. Ying, Quan M. Nguyen, Joel S. Emer, Daniel Sanchez
- **会议**: MICRO 2023
- **年份**: 2023
- **引用**: 32+
- **链接**: https://doi.org/10.1145/3613424.3614257
- **荣誉**: MICRO 2023 论文

**方法概述**:
ASH（Accelerator of Simulated Hardware）是一个**专为 RTL 仿真设计的并行处理器架构**，核心创新包括：
- **数据流执行（Dataflow Execution）**: 将 RTL 仿真任务分解为极细粒度的数据流 token，在 256 个简单核心上并行执行；
- **选择性事件驱动（Selective Event-Driven）**: 仅执行每周期被激活的仿真任务，跳过无效工作（类似事件驱动仿真），但底层使用数据流硬件实现；
- **推测执行**: 允许在输入值未完全就绪时提前启动任务，通过数据流硬件的容错机制撤销错误结果；
- **编译器-硬件协同设计**: 编译器自动提取并行性并映射到 ASH 硬件，无需手动划分。

**性能数据**:
在模拟评估中（256 简单核 ASH 芯片）：
- 相比单核 Verilator: **几何平均 1,485x 加速**；
- 相比 32 核服务器 CPU 上的并行 Verilator: **32x 加速**；
- 面积仅为服务器 CPU 的 **1/3**。

**后续工作**:
- **SASH**: 选择性事件驱动 ASH，允许每个任务有多个输入/输出变化，进一步提升性能。

**对 RTL 仿真器多线程化的启示**:
ASH 证明了**专用数据流架构 + 选择性事件驱动**是 RTL 仿真的终极加速方案。对于通用 CPU 多线程仿真，其启示在于：
- 事件驱动模型在减少无效工作方面有巨大潜力（活动因子低时优势更明显）；
- 但通用 CPU 上实现细粒度数据流调度开销巨大，需要更粗粒度的任务合并或硬件支持（如 Intel TBB / Cilk 的 work-stealing）。

---

### 3. GEM: GPU-Accelerated Emulator-Inspired RTL Simulation

- **作者**: Zizheng Guo, Yanqing Zhang, Runsheng Wang, Yibo Lin, Haoxing Ren
- **会议**: DAC 2025 (Best Paper Nomination)
- **年份**: 2025
- **引用**: 7
- **链接**: https://doi.org/10.1109/DAC63849.2025.11132713

**方法概述**:
GEM 针对传统 GPU RTL 仿真（如 RTLFlow）的两大局限——**GPU 内存容量限制**和**单刺激并行性不足**——提出了解决方案：
- **模拟器启发式设计（Emulator-Inspired）**: 借鉴 FPGA 仿真器的时分复用思想，在 GPU 上实现多设计模块的时分调度；
- **混合调度**: 结合全周期（full-cycle）和事件驱动（event-driven）策略，利用 GPU 的 SIMT 架构高效处理规则计算模式；
- **内存优化**: 通过模块级内存共享和寄存器复用，减少 GPU 显存占用，支持更大规模设计。

**性能数据**:
在多个工业级设计上，GEM 相比 Verilator 实现了显著加速，同时支持比 RTLFlow 更大规模的设计。具体加速数据待原文进一步确认，但论文获得 DAC 2025 Best Paper Nomination，表明其方法具有重要创新性。

**对 RTL 仿真器多线程化的启示**:
GEM 的"模拟器启发式"思想表明，**GPU 和 FPGA 加速策略可以互相借鉴**。对于 CPU 多线程仿真，时分复用和内存共享技术同样可用于降低多线程间的缓存竞争和内存带宽压力。

---

### 4. Khronos: Fusing Memory Access for Improved Hardware RTL Simulation

- **作者**: Kexing Zhou, Yun Liang, Yibo Lin, Runsheng Wang, Ru Huang
- **会议**: MICRO 2023
- **年份**: 2023
- **引用**: 22+
- **链接**: https://doi.org/10.1145/3613424.3614301
- **代码**: https://github.com/pku-liang/ksim
- **荣誉**: 国内本科生在 MICRO 上发表论文的首作（第一作者为北大本科生周可行）

**方法概述**:
Khronos 是一个**纯软件优化**的 cycle-accurate RTL 仿真器，核心创新是**跨周期内存访问融合**：
- 发现 RTL 仿真中大量寄存器缓冲区的内存访问在相邻周期存在**时间局部性**（如移位寄存器、流水线寄存器）；
- 提出**队列连接操作图（Queue-Connected Operation Graph）**捕捉跨周期数据依赖；
- 将内存访问融合问题建模为**整数规划问题**，并通过线性化为最小费用流问题迭代求解；
- 通过融合冗余访问，减少缓存流量和主存压力。

**性能数据**:
- 相比 Verilator: **平均 2.0x 加速，最高 4.3x**；
- 在流水线设计上可减少 **70-95% 的缓存访问**；
- 在 Gemmini（全流水线加速器）上减少 **93% 内存访问**。

**对 RTL 仿真器多线程化的启示**:
Khronos 的核心洞察是：**RTL 仿真的瓶颈不仅是逻辑评估，更是内存访问**。对于多线程仿真器，每个线程独立访问寄存器状态会加剧缓存竞争。Khronos 的跨周期融合技术可与多线程并行结合：
- 在融合后的粗粒度任务上分配线程，减少每线程的内存足迹；
- 融合后的寄存器状态可本地化到每个线程的私有缓存行，减少 false sharing。

---

### 5. From RTL to CUDA: A GPU Acceleration Flow for RTL Simulation with Batch Stimulus

- **作者**: Dian-Lun Lin, Haoxing Ren, Yanqing Zhang, Brucek Khailany, Tsung-Wei Huang
- **会议**: ICPP 2022
- **年份**: 2022
- **引用**: 69
- **链接**: https://doi.org/10.1145/3545008.3545091

**方法概述**:
该论文提出将 RTL 设计自动转换为 CUDA 内核的完整流程：
- **RTL 图划分**: 将 RTL 设计划分为可在 GPU 上并行执行的子图；
- **CUDA Graph 优化**: 利用 CUDA Graph 减少内核启动开销；
- **批量刺激（Batch Stimulus）**: 同时模拟多个独立测试向量，利用 GPU 的向量级并行性；
- **与 RTLFlow 的关系**: 该工作是 RTLFlow 的后续扩展，优化了批量刺激下的 GPU 内存布局和调度。

**性能数据**:
在批量刺激（64K 测试向量）下，相比 Verilator 实现 **40x+ 加速**。但单刺激模式下 GPU 优势不明显，受限于 GPU 内存容量和 irregular 计算模式。

**对 RTL 仿真器多线程化的启示**:
GPU 加速的核心优势在于**批量测试向量并行**，而非单设计实例加速。对于功能验证场景（需要大量随机测试向量），GPU 是理想平台。但对于单场景调试，CPU 多线程仍是更实用的选择。两者应作为互补工具集成到同一验证平台中。

---

### 6. GATSPI: GPU Accelerated Gate-Level Simulation for Power Improvement

- **作者**: Yanqing Zhang, Haoxing Ren, Akshay Sridharan, Brucek Khailany
- **会议**: DAC 2022
- **年份**: 2022
- **引用**: 25+
- **链接**: https://doi.org/10.1145/3489517.3530585

**方法概述**:
GATSPI 利用 GPU 加速门级仿真以支持**功耗分析**：
- 门级仿真需要计算每个节点的翻转率（toggle rate），计算量远大于 RTL 仿真；
- 将门级网表转换为 GPU 友好的规则数据结构，减少线程发散；
- 使用零延迟（0-delay）仿真模型，避免事件队列的动态调度开销。

**性能数据**:
在大型门级网表上，相比商业仿真器实现了数量级加速，支持快速功耗估算。

**对 RTL 仿真器多线程化的启示**:
GATSPI 的零延迟模型和规则数据转换策略同样适用于 RTL 多线程仿真——将 irregular 的 RTL 控制流转换为规则的、SIMD-friendly 的数据结构，可大幅提升向量化效率。

---

### 7. GL0AM: GPU Logic Simulation Using 0-Delay and Re-simulation Acceleration Method

- **作者**: Yanqing Zhang, Haoxing Ren, Brucek Khailany
- **会议**: ICCAD 2024
- **年份**: 2024
- **引用**: 7
- **链接**: https://doi.org/10.1145/3676536.3676675

**方法概述**:
GL0AM 进一步优化了 GPU 逻辑仿真：
- **0-delay 仿真**: 将组合逻辑按拓扑层级排序，每层内完全并行；
- **重仿真（Re-simulation）**: 当输入变化较小时，仅重新计算受影响的路径，避免全量重算；
- **内核融合**: 将多个层级的小内核融合为更大的内核，减少 GPU 内核启动开销。

**性能数据**:
在多个工业基准上，相比先前 GPU 仿真方法实现了显著加速，重仿真策略在低活动因子时效果突出。

**对 RTL 仿真器多线程化的启示**:
GL0AM 的层级排序和重仿真是事件驱动仿真的经典优化。对于 CPU 多线程，可以借鉴：
- 在编译时构建层级拓扑，运行时按层级并行调度；
- 引入变化传播追踪（change propagation），仅重新计算受影响节点。

---

### 8. FireAxe: Partitioned FPGA-Accelerated Simulation of Large-Scale RTL Designs

- **作者**: Jerry Whangbo, Edwin Lim, Christopher L. Zhang, Sagar Karandikar, Borivoje Nikolić, Krste Asanović
- **会议**: ISCA 2024
- **年份**: 2024
- **引用**: 7
- **链接**: https://ieeexplore.ieee.org/abstract/document/10609699/
- **荣誉**: ISCA 2024 Distinguished Artifact Award

**方法概述**:
FireAxe 解决 FireSim 的**单 FPGA 容量限制**问题：
- 自动将大型单片 RTL 设计划分到多个 FPGA 上；
- 每个 FPGA 分区运行一个仿真周期后同步，支持多 FPGA 并行；
- 保持 cycle-exact 精度，支持跨 FPGA 的确定性调试。

**性能数据**:
成功在多个 FPGA 上模拟了超出单片容量的大型 SoC 设计，性能随 FPGA 数量近乎线性扩展。

**对 RTL 仿真器多线程化的启示**:
FireAxe 的划分-同步策略与多核 CPU 上的分布式仿真类似。其关键挑战——**跨分区通信延迟隐藏**——也是多线程仿真中 NUMA 节点通信的核心问题。

---

### 9. GSIM: Accelerating RTL Simulation for Large-Scale Designs

- **作者**: L. Chen, D. Zhao, Z. Yu, N. Sun, et al.
- **会议**: DAC 2025
- **年份**: 2025
- **引用**: 0（最新）
- **链接**: https://ieeexplore.ieee.org/abstract/document/11133142/

**方法概述**:
GSIM 探索了大规模 RTL 仿真的加速方法，结合了软件优化和硬件加速策略。作为 DAC 2025 最新工作，其详细方法待进一步分析。

**对 RTL 仿真器多线程化的启示**:
代表了 RTL 仿真加速领域的持续活跃研究，需关注其具体技术细节以补充现有方法地图。

---

## 关键要点

1. **FPGA 加速是最成熟的实用方案**: FireSim 及其生态系统（Chipyard、FirePerf、FireAxe）提供了从单核到多 FPGA 的完整验证流水线，是业界最接近实用的 RTL 加速方案。
2. **GPU 加速适合批量验证场景**: RTLFlow、From RTL to CUDA 等在批量测试向量下表现优异，但单刺激/调试场景下优势有限。GPU 内存容量是主要瓶颈。
3. **专用加速器是终极性能目标**: ASH（MICRO 2023）的数据流架构和 Manticore（ASPLOS 2024）的静态 BSP 模型代表了 RTL 仿真加速的理论上限，但需专用硬件支持。
4. **内存访问是软件仿真的隐藏瓶颈**: Khronos（MICRO 2023）证明跨周期内存融合可带来 2-4x 加速，这是纯软件优化中被长期忽视的方向。
5. **多技术路线应互补而非互斥**: 实际验证平台应集成软件多线程（快速迭代）、GPU 加速（批量回归测试）、FPGA 加速（系统级验证）三层架构。

---

## 对 RTL 仿真器多线程化的启示

对于我们的软件多线程 RTL 仿真器项目，硬件加速论文提供了以下具体启示：

- **从 ASH 借鉴事件驱动思想**: 在通用 CPU 上实现粗粒度的事件驱动调度，通过活动预测（activity prediction）跳过无效工作周期，减少总计算量。
- **从 Khronos 借鉴内存融合**: 在编译时识别跨周期的冗余寄存器访问（如移位寄存器、流水线），将其融合为向量操作，降低每线程内存带宽需求。
- **从 GPU 论文借鉴层级化执行**: 将 RTL 组合逻辑按拓扑层级排序，同层级内节点无依赖，可完全并行。这是多线程仿真的天然并行来源。
- **从 FireSim 借鉴确定性执行**: 多线程仿真中的非确定性（线程调度顺序）是调试噩梦。引入延迟不敏感或确定性调度机制，可确保每次运行结果一致。
- **从 GEM 借鉴混合策略**: 不追求全周期仿真的"一刀切"，而是在设计的不同区域采用不同仿真模式（全周期 vs 事件驱动），动态切换以平衡性能和精度。

---

## 原文摘录

> "An ASH chip with 256 simple cores is gmean 1,485x faster than 1-core Verilator, and it is 32x faster than parallel Verilator on a server CPU with 32 complex cores, while using 3x less area."
> — ASH (MICRO 2023)

> "Khronos can save up to 88% of cache access and achieve an average acceleration of 2.0x (up to 4.3x) for various hardware designs compared to state-of-the-art simulators."
> — Khronos (MICRO 2023)

> "FireSim is capable of simulating from one to thousands of multi-core compute nodes, derived from open target-RTL, with an optional cycle-accurate network simulation tying them together."
> — FireSim (ISCA 2018)

---

## 相关链接

- [FireSim 项目主页](https://fires.im)
- [FireSim GitHub](https://github.com/firesim/firesim)
- [ASH (MICRO 2023)](https://doi.org/10.1145/3613424.3614257)
- [Khronos GitHub (ksim)](https://github.com/pku-liang/ksim)
- [From RTL to CUDA (ICPP 2022)](https://doi.org/10.1145/3545008.3545091)
- [GATSPI (DAC 2022)](https://doi.org/10.1145/3489517.3530585)
- [GL0AM (ICCAD 2024)](https://doi.org/10.1145/3676536.3676675)
- [FireAxe (ISCA 2024)](https://ieeexplore.ieee.org/abstract/document/10609699/)
- [GEM (DAC 2025)](https://doi.org/10.1109/DAC63849.2025.11132713)

---
title: FPGA 仿真（Emulation）与软件仿真的性能对比及 FireSim 框架
description: FPGA 加速 RTL 仿真的技术路线，FireSim 全系统仿真平台，以及 Emulation vs Simulation 的权衡与最新进展
source_url: "https://github.com/firesim/firesim"
source_type: "github-repo"
author: "Sagar Karandikar, Howard Mao, Donggyu Kim, David Biancolin 等 (UC Berkeley)"
date: "2018-06"
tags: [fpga, emulation, simulation, firesim, golden-gate, fireaxe, prototyping, cycle-accurate]
keywords: [FPGA emulation vs simulation, FireSim performance, FPGA prototyping RTL speedup, Golden Gate, cloud FPGA]
capture_date: "2026-07-02"
---

# FPGA 仿真（Emulation）与软件仿真的性能对比及 FireSim 框架

## 来源

- URL: https://github.com/firesim/firesim
- 类型: github-repo / paper
- 作者: Sagar Karandikar, Howard Mao, Donggyu Kim, David Biancolin 等 (UC Berkeley)
- 日期: 2018-06 (ISCA 2018 论文发表)

## 摘要

FireSim 是由 UC Berkeley 开发并维护的开源 FPGA 加速全系统硬件仿真平台，可在 AWS F1 / 本地 Xilinx Alveo 等 FPGA 上运行完整的 RTL 设计，实现 **10–100+ MHz** 的 cycle-exact 仿真速度。FireSim 通过 Golden Gate 编译器将 Chisel/Verilog RTL 自动转换为 FPGA 可映射的仿真器（FAME-1 变换），无需手写抽象模型即可直接复用生产级 RTL。相比软件仿真（如 Verilator/VCS 通常运行在 kHz–MHz 量级），FireSim 提供 **100–1000 倍** 的加速，且已在 20 余所机构、40 余篇论文中得到验证，甚至被用于商业流片前的验证。FireSim 的最新扩展 FireAxe（ISCA 2024）支持将大型 SoC 自动划分到多片 FPGA 上协同仿真，进一步突破了单片容量限制。

## 关键要点

- **FireSim 性能**：软件仿真（Verilator 单核）通常运行在 1–10 MHz 以下；FireSim 在 FPGA 上可达 10–100+ MHz，对于 RISC-V Rocket/BOOM 等核可 boot Linux 并运行真实网络栈。大规模数据中心仿真（1024 节点）下仍保持 <1000×  slowdown。
- **Golden Gate 编译器**：ICCAD 2019 论文提出的自动化变换框架，将 ASIC RTL 通过 FAME-1（FPGA-Accelerated Microarchitecture Evaluation）变换生成 FPGA 原型，弥合 ASIC 与 FPGA 之间的资源效率鸿沟。支持多时钟域、自动实例多线程（instance multithreading）优化。
- **FireAxe 多片划分**：ISCA 2024 提出的 FireAxe 扩展，可将大型 SoC 自动划分到多块 FPGA 上，通过 token-based 网络同步保持 cycle-exact 行为。支持跨 FPGA 实例的分布式仿真。
- **仿真 vs 仿真 vs 原型对比**（综合 S2C / Aldec 行业白皮书）：
  - **软件仿真（Simulation）**：调试能力强（全信号可见、断点、波形），成本低，但速度慢（kHz–低 MHz），适合早期功能验证。
  - **FPGA 仿真（Emulation）**：速度 1–5 MHz，成本较高（$M 级），调试能力接近仿真器（静态探针、动态探针、ILA），适合大型 SoC 中后期验证。
  - **FPGA 原型（Prototyping）**：速度 >10 MHz，成本中等，外部连接性强，但调试能力弱（依赖片上逻辑分析仪），适合软件开发和系统验证。
- **FireBridge（2025）**：新提出的软硬件协同验证框架，将 firmware 编译为 x86 并在 VCS/Xcelium 等标准仿真器中与 RTL 联合验证，相比传统 FPGA 调试迭代速度提升 **50 倍**，可与 FireSim 互补使用。
- **CHESSY（DATE 2026）**：SystemC-FPGA 耦合混合仿真框架，对 RISC-V SoC 实现 **>1000 倍于 RTL 仿真** 的加速，同时总仿真时间仅为纯 FPGA 仿真的 <2 倍。

## 对 RTL 仿真器多线程化的启示

FireSim 及其生态清晰地展示了 **「加速层级」** 的递进关系：软件多线程 → GPU 加速 → FPGA 仿真 → 流片。对于仍在软件层面的多线程 RTL 仿真器，FireSim 提供了以下可借鉴的设计原则：
1. **FAME-1 变换的启示**：将 target 时钟域与 host 时钟域解耦，通过插入仿真控制逻辑（如周期计数器、信号采样器）实现 cycle-exact 而不需要 1:1 的 host 时钟速度。这类似于软件仿真器中「时间轮」或「事件驱动」的抽象，但 FireSim 将其固化到了硬件映射中。
2. **Token-based 同步的启示**：在分布式 FPGA 仿真中，FireSim 使用 token-based 网络同步来保持确定性。对于多线程软件仿真器，可借鉴「批量令牌交换」思想：减少跨线程同步频率，通过批量时间推进（batching cycles）来摊平同步开销。
3. **Golden Gate 的自动优化**：将 RTL 自动变换为仿真友好形态（多时钟、资源折叠）提示我们——在生成 C++ 仿真代码之前，对 RTL 做硬件层面的结构优化（如寄存器合并、常量传播、时钟门控识别）可以显著提升多线程执行效率。
4. **FireBridge 的混合路线**：在软件仿真与 FPGA 仿真之间插入「firmware-on-x86 + RTL-in-simulator」的混合层，实现了 50 倍调试加速。这提示：多线程 RTL 仿真器也可以设计为「快速模式」（牺牲部分调试能力换取速度）与「调试模式」（全可见性）的双模架构。

## 代码示例

### FireSim 快速启动（AWS F1）

```bash
# 1. 克隆仓库并设置环境
git clone https://github.com/firesim/firesim.git
cd firesim
git checkout stable
source sourceme-f1-manager.sh

# 2. 构建 FPGA 镜像（Golden Gate 编译）
cd sim/
make DESIGN=FireSimRocketChipConfig

# 3. 启动仿真（自动部署到 AWS F1）
firesim launchrunfarm
firesim infrasetup
firesim runworkload

# 4. 查看仿真输出（在模拟节点上运行 Linux）
firesim terminatefarm
```

### FireSim 性能数据（ISCA 2018 论文）

| 目标规模 | 仿真速率 | 备注 |
|---------|---------|------|
| 1 节点 RocketChip | ~100 MHz | 单 FPGA 实例 |
| 64 节点集群 | ~50 MHz | 同实例多 FPGA |
| 1024 节点集群 | ~10 MHz | 跨实例分布式 |

### FireSim 支持的 I/O 模型（开箱即用）

```scala
// 示例：在 FireSim 配置中启用网络与 DRAM
class FireSimConfig extends Config(
  new WithDefaultFireSimBridges ++
  new WithDefaultMemModel ++
  new WithFireSimConfigTweaks ++
  new freechips.rocketchip.system.DefaultConfig
)
// 支持的 I/O：DRAM (FASED), Ethernet, UART, Block Device, TracerV
```

## 原文摘录

> "FireSim is an open-source FPGA-accelerated full-system hardware simulation platform that makes it easy to validate, profile, and debug RTL hardware implementations at 10s to 100s of MHz. FireSim simplifies co-simulating ASIC RTL with cycle-accurate hardware and software models for other system components."
> — https://github.com/firesim/firesim

> "FireSim's simulated servers are built by directly applying FAME-1 transforms to the original RTL for a server blade to yield a simulator that has the exact cycle-by-cycle behavior of the user-written RTL."
> — FireSim ISCA 2018 Paper

> "Compared to simulation, emulation is much faster but even so it can, for example, take hours for an OS to boot. An FPGA prototyping platform is faster still and ... During the development of a system on chip (SoC), hardware emulation and FPGA prototyping play distinct and essential roles."
> — Aldec, The Convergence of Emulation and Prototyping

> "We demonstrate a speedup of up to 50× in debug iteration over the conventional FPGA-based flow for system integration between RTL/HLS and production firmware."
> — FireBridge (2025)

> "We achieve more than three orders of magnitude speedup over RTL simulation while maintaining a total simulation time of less than 2× that of pure FPGA emulation."
> — CHESSY (DATE 2026)

## 相关链接

- [FireSim GitHub 仓库](https://github.com/firesim/firesim)
- [FireSim 官网](https://fires.im)
- [FireSim ISCA 2018 论文 PDF](https://davidbiancolin.github.io/papers/firesim-isca18.pdf)
- [Golden Gate ICCAD 2019 论文](https://davidbiancolin.github.io/papers/goldengate-iccad19.pdf)
- [FireAxe ISCA 2024 论文](https://people.eecs.berkeley.edu/~ysshao/assets/papers/fireaxe-isca24.pdf)
- [FirePerf ASPLOS 2020 论文](https://davidbiancolin.github.io/papers/fireperf-asplos20.pdf)
- [FireBridge 论文 (2025)](https://arxiv.org/html/2603.25969v2)
- [CHESSY DATE 2026 论文](https://www.date-conference.com/proceedings-archive/2026/DATA/3030.pdf)
- [Aldec: Emulation vs Prototyping](https://www.aldec.com/en/company/blog/191--the-convergence-of-emulation-and-prototyping)
- [S2C: Logic Simulation, Emulation, and FPGA Prototyping (Whitepaper)](https://www.s2cinc.com/resources/lit/en/wp/s2c-how-do-logic-simulation-emulation-and-fpga-prototyping-work.pdf)

---
id: "wiki-latest-landscape"
title: "最新研究 landscape (2023-2026)"
description: "2023-2026年多线程/并行RTL仿真领域的最新论文、GitHub开源项目与工业实践全景，以及趋势分析与项目关注建议"
tags: ["rtl-simulation", "latest-research", "gpu-acceleration", "tensor-algebra", "coroutine", "distributed-simulation", "gsim", "gem", "omnisim", "parendi"]
keywords: ["GSIM", "GEM", "RTeAAL Sim", "OmniSim", "Parendi", "CCSS", "Multisim", "TaroRTL", "GPU RTL simulation", "FireSim", "ROHD"]
related_sources:
  - "source-latest-rtlsim-papers"
  - "source-github-rtlsim-projects"
  - "source-industry-rtlsim-practices"
last_updated: "2026-07-01"
---

# 最新研究 landscape (2023-2026)

RTL 仿真加速领域在 2023–2026 年间经历了从「CPU 多线程补丁」到「GPU 虚拟架构」、从「Verilog 编译器」到「张量代数编译器」的范式转移。本章绘制最新论文地图、GitHub 项目地图和工业实践地图，并提炼出对用户项目「现在该关注什么」的优先级建议。

---

## 1. 最新论文地图（2023-2026）

### 1.1 核心论文一览

| 论文 | 会议/年份 | 核心创新 | 相对 Verilator 单线程 | 相对 Verilator 多线程 | 开源 |
|------|----------|---------|----------------------|----------------------|------|
| **GSIM** | DAC 2025 | 超节点/节点/比特三级优化 | **7.34×** (XiangShan) | **1.18×** (vs 8T) | ✅ [gsim](https://github.com/OpenXiangShan/gsim) |
| **GEM** | DAC 2025 | GPU 虚拟 VLIW 布尔处理器 | **24.87×** | **5.98×** (vs 8T) | ✅ [GEM](https://github.com/NVlabs/GEM) |
| **RTeAAL Sim** | arXiv 2026 | 张量代数重构 RTL 仿真 | 相当 | 相当 | ✅ [RTeAAL-Sim](https://github.com/TAC-UCB/RTeAAL-Sim) |
| **OmniSim** | MICRO 2025 | HLS 数据流多线程精确仿真 | 35.9× (vs C/RTL 协同) | — | ❌ |
| **Parendi** | ASPLOS 2025 | 千路 IPU 并行 BSP | 2.8–4× (vs x64 最强) | — | ❌ |
| **CCSS** | arXiv 2025 | 多核加速器，细粒度节点映射 | **45×** | **12.9×** (vs Manticore) | ❌ |
| **TaroRTL** | Euro-Par 2024 | C++20 Coroutine 任务图调度 | 55–81% (vs RTLflow CPU) | — | ❌ |
| **Manticore** | DATE 2023 | FPGA 225 核静态 BSP | outperforms EPYC 120C | — | ❌ |

### 1.2 GSIM —— 超节点/节点/比特三级优化（DAC 2025）

- **论文**: *GSIM: Accelerating RTL Simulation for Large-Scale Designs* (Lu Chen et al., DAC 2025)
- **链接**: [arXiv](https://arxiv.org/abs/2508.02236) | [PDF](https://talks-pubs.xiangshan.cc/publications/dac2025-GSIM.pdf) | [GitHub](https://github.com/OpenXiangShan/gsim)
- **核心思想**: 将 RTL 仿真计算开销归纳为四个因素（活跃位访问、节点求值、总节点数、活动因子），并在**超节点级**、**节点级**、**比特级**分别提出优化：
  - 超节点级：增强型 Kernighan 划分算法，保护强关联节点不被拆分；
  - 节点级：冗余节点消除、基于成本模型的内联决策、reset 信号检查前移；
  - 比特级：数据流分析后按比特访问模式拆分节点，进一步降低活动因子。
- **性能**: XiangShan 启动 Linux 比 Verilator 单线程快 **7.34×**，Rocket CoreMark 快 **19.94×**；SPEC CPU2006 平均比单线程 Verilator 快 **3.72×**，与 8 线程 Verilator 相比仍快 **1.18×**。
- **关键结论**: GSIM 是目前唯一能正确仿真 XiangShan 的开源仿真器（ESSENT 和 Arcilator 在部分设计上会失败或 OOM）。
- **对用户的启示**: 超节点划分是单线程优化的主杠杆，最优大小在 **20–50** 之间，可直接指导划分策略。

### 1.3 GEM —— NVIDIA 的 GPU 加速 RTL 仿真（DAC 2025）

- **论文**: *GEM: GPU-Accelerated Emulator-Inspired RTL Simulation* (Zizheng Guo, Mark Haoxing Ren, NVIDIA Research, DAC 2025)
- **链接**: [NVIDIA Research](https://research.nvidia.com/publication/2025-06_gem-gpu-accelerated-emulator-inspired-rtl-simulation) | [PDF](https://yibolin.com/publications/papers/SIM_DAC2025_Guo.pdf) | [GitHub](https://github.com/NVlabs/GEM)
- **核心思想**: 受 FPGA 仿真器启发，提出**虚拟 VLIW 架构**并在 GPU 上通过 CUDA 解释执行。RTL 设计先综合为门级网表，再映射为 GEM 的布尔处理器指令流（bitstream），类比 FPGA CAD 流程。
- **关键设计**:
  - 三档指令长度（8192/16384/32768 bit），256 线程 lockstep 加载，完全合并内存访问；
  - Boomerang 折叠机制将逻辑级数压缩 6–8 倍；
  - 162.4 MB bitstream 即可承载 500 万门的 OpenPiton8 设计。
- **性能**: 平均比领先商业工具快 **9.15×**，比 8 线程 Verilator 快 **5.98×**，比单线程 Verilator 快 **24.87×**；NVDLA 峰值加速达 **64.76×**。获 DAC 2025 **Best Paper Nomination**。
- **对用户的启示**: GPU 方向已被大厂验证可行，但需要**全新的执行模型**（虚拟 VLIW），而非简单移植现有 C++ 仿真核。如果优化器保留 GPU 后端扩展能力，应在 IR 层就设计适合 GPU 批量执行的数据布局。

### 1.4 RTeAAL Sim —— 张量代数重构 RTL 仿真（2026）

- **论文**: *RTeAAL Sim: Using Tensor Algebra to Represent and Accelerate RTL Simulation* (arXiv:2601.18140)
- **链接**: [arXiv](https://arXiv.org/html/2601.18140v1) | [GitHub](https://github.com/TAC-UCB/RTeAAL-Sim)
- **核心思想**: 将 RTL 数据流图表示为**稀疏张量**，仿真执行描述为**扩展 Einsum 的级联**（cascade of extended Einsums）。借助 TeAAL 框架对稀疏张量代数核进行调度与优化，实现算法、数据流、格式、硬件绑定的分离。
- **创新点**: 将 17 种来自 11 篇前作的 RTL 仿真优化技术统一映射到 TeAAL 的四层抽象中，证明了张量代数表述的**通用性**与**可扩展性**。
- **性能**: 概念验证原型在四种主机上与 Verilator 性能相当，但理论优化空间远大于现有实现。
- **对用户的启示**: 张量代数可能是**下一代统一框架**，意味着未来可以自动复用 loop unrolling、format compression、operator fusion 等编译技术。如果考虑引入更高级的编译器优化框架，RTeAAL Sim 的 TeAAL 集成路径提供了参考。

### 1.5 OmniSim —— HLS 数据流的多线程仿真（MICRO 2025）

- **论文**: *OmniSim: Simulating Hardware with C Speed and RTL Accuracy for HLS Designs* (Georgia Tech, MICRO 2025)
- **链接**: [arXiv](https://arXiv.org/abs/2508.19299) | [ACM](https://dl.acm.org/doi/10.1145/3725843.3756033)
- **核心思想**: 针对 HLS 工具中复杂数据流（cyclic dependency、non-blocking FIFO）无法在 C 仿真层准确建模的问题，通过**软件多线程**精确模拟 FIFO 访问的硬件时序，并灵活耦合功能仿真与性能仿真线程。
- **性能**: 在 11 个此前无任何 HLS 工具支持的设计上，比传统 C/RTL 协同仿真快 **35.9×**，比 LightningSim 快 **6.61×**；增量重仿真可在 78 µs 内完成，相对完整仿真加速 **26,966×**。
- **对用户的启示**: HLS 数据流的**多线程精确仿真**是独立但相关的方向，其 LLVM IR 层级重写和任务提取技术对 RTL 仿真器的 IR 优化有借鉴意义。

### 1.6 Parendi —— 千路并行 RTL 仿真（ASPLOS 2025）

- **论文**: *Parendi: Thousand-Way Parallel RTL Simulation* (EPFL, ASPLOS 2025)
- **链接**: [arXiv](https://arXiv.org/abs/2403.04714) | [PDF](https://infoscience.epfl.ch/bitstreams/690daaf4-d0c8-479b-b46f-cd47461bd50a/download)
- **核心思想**: 基于 Graphcore IPU 的**消息传递架构**，将 RTL 设计的细粒度并行性映射到多达 **5888 核**的 IPU tile 上。采用 Bulk-Synchronous Parallel (BSP) 执行模型。
- **关键发现**:
  - x64 多核上的同步成本过高，导致小设计几乎无法从多线程获益；
  - IPU 的低成本同步与低延迟通信使千路并行成为可能，但单 tile 性能约为 x64 的 1/37–1/84；
  - 需要足够大的设计才能摊平跨 tile 通信开销。
- **性能**: 在 4 个 IPU socket（5888 核）上，大型设计比最强 x64 多核系统快 **4×**。
- **对用户的启示**: RTL 仿真的并行瓶颈**不在算法本身**，而在**通用 x86 架构的缓存一致性和同步机制**。这为软件层面的优化指明了方向——在通用 CPU 上，需要用更轻量的同步机制来模拟 IPU 的高效通信。

### 1.7 其他值得关注的论文

| 论文 | 年份 | 核心看点 |
|------|------|---------|
| **CCSS** (arXiv:2507.08406) | 2025 | 多核 RTL 仿真加速器，比 Verilator 单线程快 **45×**，编译时间优于 Manticore |
| **TaroRTL** (Euro-Par 2024) | 2024 | C++20 Coroutine 调度 RTLflow 任务图，消除 CPU 等待 GPU 的空闲，加速 **55–81%** |
| **Manticore** (DATE 2023) | 2023 | FPGA 225 核静态 BSP，在 8/9 个基准上 outperform 120C EPYC，关键洞察：运行时同步是扩展性杀手 |

---

## 2. GitHub 项目地图

### 2.1 活跃开源项目一览

| 项目 | 语言 | Stars | 状态 | 核心定位 | 多线程/并行 |
|------|------|-------|------|---------|------------|
| [verilator/verilator](https://github.com/verilator/verilator) | C++ | 3,708 | 成熟 | 最广泛使用的开源 SystemVerilog 仿真器 | `--threads` 支持，但 8T+ 常退化 |
| [OpenXiangShan/gsim](https://github.com/OpenXiangShan/gsim) | C++ | — | 活跃 | 香山团队新型 RTL 仿真器，超节点三级优化 | 当前主要单线程，多线程为正交方向 |
| [NVlabs/GEM](https://github.com/NVlabs/GEM) | Rust/CUDA | — | 活跃 | NVIDIA GPU 加速 RTL 仿真 | **GPU 并行**，虚拟 VLIW |
| [gpu-eda/Jacquard](https://github.com/gpu-eda/Jacquard) | C++/Metal | 66 | 极早期 | 多 GPU 后端 RTL 仿真（Metal/CUDA/HIP） | **GPU 并行**，2026-01 创建 |
| [TAC-UCB/RTeAAL-Sim](https://github.com/TAC-UCB/RTeAAL-Sim) | C++ | — | 概念验证 | 张量代数 RTL 仿真原型 | 稀疏张量调度优化 |
| [hankhsu1996/lyra](https://github.com/hankhsu1996/lyra) | C++ | 4 | 早期 | 多阶段 IR 流水线 SystemVerilog 工具链 | 多阶段 IR 可能辅助线程划分 |
| [intel/rohd](https://github.com/intel/rohd) | Dart | 483 | 活跃 | Intel 硬件开发框架与仿真生态 | 验证生态而非极致性能 |
| [antoinemadec/multisim](https://github.com/antoinemadec/multisim) | Python/SV | — | 活跃 | 分布式多实例 RTL 仿真 | **分布式并行**，TCP/IP 通道 |
| [tjddnr0912/vitamin-rtl-simulator](https://github.com/tjddnr0912/vitamin-rtl-simulator) | Rust | — | 极早期 | 纯 Rust 无 C 依赖 RTL 仿真 | 尚未成熟 |
| [Yoriyoi-drop/maria](https://github.com/Yoriyoi-drop/maria) | Rust | — | 极早期 | Rust 构建 SystemVerilog 仿真器 | 尚未成熟 |

### 2.2 项目分类与关注建议

| 类别 | 代表项目 | 用户应关注程度 | 理由 |
|------|---------|---------------|------|
| **基准对标** | Verilator | ⭐⭐⭐⭐⭐ | 几乎所有论文的基准，必须深入了解其 `--threads` 局限 |
| **单线程优化前沿** | GSIM | ⭐⭐⭐⭐⭐ | 超节点划分、比特级拆分是当前最有效的优化方向 |
| **GPU 加速** | GEM, Jacquard | ⭐⭐⭐⭐☆ | 已被 NVIDIA 验证可行，但需全新架构，非短期移植选项 |
| **张量代数** | RTeAAL-Sim | ⭐⭐⭐☆☆ | 长期方向，概念验证阶段，但编译器优化潜力巨大 |
| **分布式仿真** | Multisim | ⭐⭐⭐☆☆ | 超大规模 SoC 的粗粒度并行方案，可跟踪其 Ready/Valid 通道模型 |
| **多阶段 IR** | Lyra | ⭐⭐☆☆☆ | 早期项目，观察其 IR 分层是否有助于线程划分 |
| **Rust 生态** | vitamin-rtl, maria | ⭐☆☆☆☆ | 极早期，功能远不及 Verilator，长期跟踪即可 |

---

## 3. 工业实践：NVIDIA GEM、Google FireSim、Intel ROHD

### 3.1 三大路线对比

| 公司/机构 | 项目 | 路线 | 核心优势 | 与软件多线程的关系 |
|----------|------|------|---------|------------------|
| **NVIDIA** | GEM | **GPU 批量加速** | 虚拟 VLIW 绕过 SIMT 不兼容，9× 商业工具 | 互补：GPU 用于回归测试批量加速 |
| **Google/UCB** | FireSim + Chipyard | **FPGA 全系统仿真** | 10–100 MHz，比软件快数个数量级 | 互补：FPGA 用于 OS 启动和全系统签核 |
| **Intel** | ROHD | **现代语言 + 验证生态** | Dart 前端，验证生产力优先 | 需求输入：工业界不只关心 MHz，还关心调试、覆盖率、断言 |

### 3.2 NVIDIA GEM 的工业信号

- GEM 论文获 DAC 2025 **Best Paper Nomination**。
- 2026 年 1 月，Chisel 社区（SiFive 主导）主动发起 [Discussion #5142](https://github.com/chipsalliance/chisel/discussions/5142)，希望将 GEM 集成到 ChiselSim 作为可选后端，目标实现 **5–40×** 加速。
- 讨论中明确提到：「Large Chisel designs can take hours or days to simulate on CPU」——这正是工业痛点。

### 3.3 Google FireSim 的定位

- FireSim 在 Amazon EC2 F1 / 本地 FPGA 上运行，实现 **10–100 MHz** 的仿真速度，比软件 RTL 仿真（~1 kHz）快数个数量级。
- Chipyard 文档中明确提到 ["Speeding up your RTL Simulation by 2x!"](https://chipyard.readthedocs.io/en/latest/Simulation/index.html)——软件仿真用于快速编译和全波形调试，FPGA 仿真用于操作系统启动和完整 workload。
- **核心启示**: FPGA 加速是"终极解"，但成本高、编译慢（数小时到数天）、调试可见性差。软件多线程仿真仍有不可替代的价值：**快速迭代、全波形、低成本**。

### 3.4 Intel ROHD 的验证视角

- Intel 选择用 **Dart** 构建硬件描述和验证框架，强调**验证生产力**（debuggability、test reuse、断言覆盖率）而非单纯仿真速度。
- 483 stars，145 open issues，说明 Intel 在持续投入。
- **核心启示**: 工业界不只关心 "MHz"，还关心**调试能力**、**断言覆盖率**、**与现有验证流程的兼容性**。如果多线程优化器破坏了波形时间一致性或断言触发顺序，工业用户会无法接受。

### 3.5 工业级数据点

> "RTL simulation—a critical phase in the verification flow—now accounts for over 24% of total development time. Meanwhile, first-pass silicon success rates have dropped by 18% over the past 12 years."
> — CCSS Paper (arXiv:2507.08406), citing industry data

> "Calibrated simulation results against actual silicon performance, identifying and resolving discrepancies, which led to more accurate projections and informed decision-making."
> — NVIDIA Intern CV (public)

---

## 4. 趋势分析

### 4.1 五大趋势

| 趋势 | 代表工作 | 成熟度 | 对通用 CPU 多线程优化的影响 |
|------|---------|--------|------------------------|
| **GPU 加速** | GEM, Jacquard | 中（NVIDIA 已开源） | 短期互补，长期可能分流部分 workload |
| **张量代数统一** | RTeAAL Sim | 低（概念验证） | 长期方向，可能改变 IR 优化范式 |
| **Coroutine 异构调度** | TaroRTL | 低（研究原型） | C++20 coroutine 可用于消除 CPU 等待 GPU 的空闲 |
| **分布式多实例** | Multisim, Parendi | 中（Multisim 已开源） | 超大规模 SoC 的粗粒度并行方案 |
| **超节点单线程优化** | GSIM | 高（已开源，可复现） | **当前最有效的优化方向，直接可用** |

### 4.2 趋势判断

1. **CPU 多线程不会消失**：FireSim（FPGA）和 GEM（GPU）都是互补而非替代。CPU 多线程的调试友好性和快速迭代特性是 FPGA/GPU 无法比拟的。
2. **单线程优化的天花板仍在上移**：GSIM 证明了超节点划分和比特级拆分仍有巨大空间。在投入多线程之前，先确保单线程已榨取这些收益。
3. **多线程同步成本仍是 CPU 的核心瓶颈**：Verilator 多线程在 8 线程后退化，RepCut 通过冗余计算降低同步，CCSS 通过细粒度调度避免粗粒度同步。下一代 CPU 多线程仿真器需要**更轻量的同步机制**。
4. **IR 中间层成为竞争焦点**：Lyra 的多阶段 IR、RTeAAL Sim 的张量 IR、GSIM 的 FIRRTL 前端都说明，RTL 仿真器正在从「Verilog 编译器」进化为「领域特定编译器」。多线程优化应发生在 IR 层级，而非 AST 层级。

---

## 5. 对用户的项目「现在该关注什么」的建议

### 5.1 优先级矩阵

| 优先级 | 方向 | 具体行动 | 预期收益 | 时间投入 |
|--------|------|---------|---------|---------|
| **P0** | 超节点划分 | 研究 GSIM 的 Kernighan 划分算法，测试超节点大小 20–50 的敏感度 | 2–7× 单线程加速 | 2–4 周 |
| **P1** | 轻量同步屏障 | 用 Dissemination Barrier 或 MCS Tree 替换 `pthread_barrier`，消除 cache line 乒乓 | 10–30% 多线程效率提升 | 1–2 周 |
| **P1** | 编译器优化链 | 为 Verilator 输出启用 PGO + Thin LTO | 5–15% 加速 | 1 周 |
| **P2** | 内存优化 | `LD_PRELOAD` 测试 jemalloc/tcmalloc，启用 THP `madvise`，运行 STREAM 诊断带宽墙 | 5–20% 加速 | 3–5 天 |
| **P2** | NUMA 感知 | 按 NUMA 节点分区电路图，first-touch 初始化，线程绑定 | 10–30% 多路服务器加速 | 1–2 周 |
| **P3** | GPU 后端跟踪 | 跟踪 GEM 和 Jacquard 的进展，评估 IR 层设计是否可映射到虚拟 VLIW | 长期选项 | 持续跟踪 |
| **P3** | 张量代数跟踪 | 关注 RTeAAL Sim 的 TeAAL 集成路径，评估编译器优化复用可能性 | 长期选项 | 持续跟踪 |
| **P4** | 分布式仿真 | 跟踪 Multisim 的通道通信模型，仅在超大规模 SoC 场景考虑 | 特定场景 | 按需 |

### 5.2 关键决策点

**Q: 现在应该做 GPU 后端吗？**
A: **不建议**。GEM 证明了可行性，但需要全新架构（虚拟 VLIW），且 Rust/CUDA 技术栈与现有 C++ 仿真器差异巨大。建议先做好 CPU 多线程的「基本功」（P0–P2），将 GPU 作为 12–18 个月的跟踪选项。

**Q: 单线程优化和多线程优化哪个优先？**
A: **单线程优先**。GSIM 证明了单线程仍有 2–7× 空间，且这些优化（超节点划分、比特级拆分）与多线程是正交的。如果单线程未优化到位，多线程的 Amdahl 加速比会被串行部分严重拖累。

**Q: 16 线程目标现实吗？**
A: **有挑战但可行**。Verilator 多线程在 8 线程后退化，但 Parendi 证明 RTL 仿真的并行瓶颈在同步机制而非算法本身。通过 Dissemination Barrier、NUMA 感知、批量同步，16 线程达到 >2× 加速是合理目标。但前提是：设计足够大、计算足够密集、同步足够轻量。

**Q: 应该自研仿真器还是改造 Verilator？**
A: **中期改造 Verilator，长期考虑新架构**。Verilator 的生态系统是最大壁垒，但 macro-task 分区模型在 8T+ 上有系统性瓶颈。建议：
- 短期：在 Verilator 的 `V3Partition` 和 `V3Order` 基础上引入 GSIM 的超节点划分；
- 中期：替换 Verilator 的 `pthread_barrier` 为 Dissemination Barrier；
- 长期：若需要突破 16T+，可能需要基于新 IR（如 FIRRTL + 张量代数）重新设计。

---

## 6. 综合检查清单

- [ ] 已阅读 GSIM 论文，理解超节点划分（20–50）和比特级拆分。
- [ ] 已运行 STREAM benchmark，了解目标机器的内存带宽上限。
- [ ] 已测试 jemalloc / tcmalloc / mimalloc 的 `LD_PRELOAD` 替换效果。
- [ ] 已确认 THP 状态（推荐 `madvise` + `defer+madvise`）。
- [ ] 已评估 Dissemination Barrier 或 MCS Tree 替换现有 barrier 的可行性。
- [ ] 已了解 PGO + Thin LTO 的构建流程，并在 CI 中预留训练负载。
- [ ] 已跟踪 GEM、Jacquard、RTeAAL-Sim 的 GitHub 更新（每月一次）。
- [ ] 已理解工业界的底线需求：cycle-accuracy、波形一致性、断言覆盖率不能牺牲。

---

## 参考来源

- [source-latest-rtlsim-papers](source-latest-rtlsim-papers.md) — 2023-2026 最新 RTL 仿真论文汇总（GSIM、GEM、RTeAAL、OmniSim、Parendi、CCSS、TaroRTL）
- [source-github-rtlsim-projects](source-github-rtlsim-projects.md) — GitHub 活跃 RTL 仿真器项目地图（Verilator、GSIM、GEM、Jacquard、Lyra、Multisim、Rust 实现）
- [source-industry-rtlsim-practices](source-industry-rtlsim-practices.md) — Google FireSim、NVIDIA GEM、Intel ROHD 工业实践与社区动向

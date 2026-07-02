---
title: "RTL 编译时向量化与位切片优化：字级仿真、位级压缩与数据流分裂"
description: "搜集 Word-level simulation、bit-vector optimization、bit-level splitting、supernode、E-AIG 等 RTL 仿真器中的向量化与位切片优化技术，涵盖 GEM、GSIM、Parendi 等前沿框架的性能数据。"
source_url: "https://arxiv.org/html/2403.04714v1"
source_type: "paper"
author: "Parendi Team / GEM Team / GSIM Team / LLVM Bit-level Optimization"
date: "2024-03-07"
tags: ["word-level-simulation", "bit-vector", "bit-slicing", "vectorization", "supernode", "E-AIG", "GEM", "GSIM", "Parendi", "RTL-simulation"]
keywords: ["word-level simulation", "bit-level splitting", "bit-vector packing", "E-AIG", "supernode", "boomerang executor", "bit-level activation"]
capture_date: "2026-07-03"
---

# RTL 编译时向量化与位切片优化：字级仿真、位级压缩与数据流分裂

## 来源

- URL: https://arxiv.org/html/2403.04714v1
- 类型: paper / 技术文档
- 作者: Parendi 团队 (Graphcore IPU) / GEM 团队 (DAC 2025) / GSIM 团队 (2025) / LLVM FPGA Bit-level Optimization
- 日期: 2024-03-07

## 摘要

RTL 仿真器的性能瓶颈不仅来自调度与同步开销，也来自数据表示的粒度失配。Word-level simulation 利用 64 位字长并行执行位运算，将复杂度从 O(2^k) 降至 O(|XAIG|·2^(k−l))；GEM 在 GPU 上利用 word-level parallelism 将 32 位整数视为 32 个并行位通道，实现相比 Verilator 最高 **64.76×** 的加速。GSIM 则通过超节点（supernode）聚合与位级分裂（bit-level splitting）相结合，在 XiangShan Linux 启动场景中获得 **7.34×** 加速、Rocket CoreMark 中获得 **19.94×** 加速。Parendi 在千核 IPU 上证明：将字级运算的负载均衡与数据流感知分区结合，可在 5888 核上实现比 Verilator 多线程 **2.8×** 的几何平均加速。这些技术共同指向一个优化方向：在编译期识别信号的位宽使用模式，以字级向量运算替代逐位循环，以位级分裂消除不必要的激活开销。

## 关键要点

### 1. Word-Level Simulation：从位级到字级的并行加速

Word-level simulation 的核心思想是将多个仿真模式的位值打包进一个机器字（如 64 位），从而用一条字级 AND/OR/XOR 指令同时处理 64 个模式。

- **复杂度分析**：对于 2^k 个输入模式，bit-level simulation 的代价为 O(2^k)；word-level simulation（字长 2^l = 64）的代价为 O(|XAIG| · 2^(k−l))，其中 |XAIG| 是扩展 AIG 的节点数。
- **AIG 紧凑性的重要性**：最小化 AIG 表示可进一步降低 word-level simulation 的偏移量 Δ ≈ log|XAIG| − l。若 AIG 过大，字级并行带来的加速会被节点数增长抵消。
- **适用场景**：布尔神经网络（BNN）仿真、蒙特卡洛仿真、批量故障仿真等需要大量独立模式的场景。

**原文数据**：对于 majority-of-9 函数，word-level simulation 相比 bit-level 呈现约 Δ ≈ −1.1 的指数偏移（即约 2^1.1 ≈ 2.1× 的常数级加速），但在大规模 BNN 推理中重复执行千次时，紧凑 AIG + word-level 的组合可完全替代 GPU 加速。

### 2. GEM：GPU 上的 E-AIG 与 Word-Level Parallelism

GEM（DAC 2025）将 RTL 设计视为扩展 AIG（E-AIG）的分区集合，在 GPU 上执行布尔运算：

- **E-AIG**：扩展 AIG，在标准 AIG 基础上支持更复杂的门类型（如 XOR、MUX），但仍保持以 2-input AND + INV 为主体的简单结构。
- **Word-Level Parallelism**：将 32 位无符号整数 `a, b, c` 的 `r = (a AND b) XOR c` 视为 **32 个并行位通道** 的 AND-then-Invert 指令。每位独立使用 `a, b` 作为输入，`c` 作为是否翻转的常量掩码。
- **Boomerang-Shaped Executor**：针对 AIG 逻辑深度分布极度不均衡（长尾特性）的问题，GEM 提出递归位排列与boomerang 层交错的执行器。将逻辑深度从 148 压缩到 19（以 Gemmini 为例），大幅降低 GPU 的层间同步开销。

**性能数据**：

| 对比基准 | 平均加速 | 峰值加速 (NVDLA) |
|---------|---------|------------------|
| 商业仿真器（单核） | **9.15×** | **64.76×** |
| Verilator 8 线程 | **5.98×** | 38.85× |
| Verilator 单线程 | **24.87×** | 64.76× |

GEM 的 bitstream 格式极为紧凑：500 万门、800 MB 扁平 Verilog 的设计，压缩后仅需 **162.4 MB** GPU 内存。

### 3. GSIM：超节点聚合 + 位级分裂

GSIM（2025）针对大规模 RTL 设计（如 XiangShan、BOOM）提出三层优化：

- **超节点（Supernode）**：将数据流图中频繁一起激活的节点聚合为超节点，减少调度开销和函数调用次数。对复杂设计（BOOM、XiangShan）贡献显著。
- **位级分裂（Bit-Level Splitting）**：扩展数据流分析到位级，根据相邻位的访问方向（读/写模式）判断何时将节点按位拆分。避免“整个 64 位总线被标记为活跃，但实际只翻转 3 位”的过度计算。
- **图分区（Graph Partitioning）**：对超节点后的图进行多目标分区，平衡各分区的计算量与通信量。

**性能数据**：

| 场景 | 加速 vs Verilator 单线程 | 备注 |
|------|------------------------|------|
| XiangShan 启动 Linux | **7.34×** | 实际系统级工作负载 |
| Rocket 运行 CoreMark | **19.94×** | 超越 ESSENT 和 Arcillator 2.52× |
| SPEC CPU 2006 (XiangShan) | **3.72×** 平均 | 对比单线程 Verilator；对比 8 线程 Verilator 为 1.18× |

**优化分解**：从无优化基线到完整优化，GSIM 的各项技术累积带来 **16.4× ~ 85.4×** 的改进。超节点贡献最大，位级分裂对 BOOM 和 XiangShan 有明显效果，但对 Rocket 和 stuCore 影响较小（说明位级分裂的收益与设计的数据通路宽度相关）。

### 4. Parendi：千核并行下的字级负载均衡

Parendi 在 Graphcore IPU（1472 核/芯片，最高 5888 核）上运行并行 RTL 仿真：

- **Fiber-based DAG Partition**：将 RTL DAG 划分为 fiber（独立子流），但传统方案将加减乘除视为同等操作导致负载严重失衡（一个乘法器的 LUT 数可能是加法的 10 倍）。
- **LUT-level Scheduling**：不以算术操作而以 LUT 节点为调度粒度，显著改善负载均衡。
- **Redundancy-Aware Partition**：相邻 fiber 常存在重叠节点（树状结构），若分配至不同核心会导致冗余计算。Parendi 联合优化负载均衡与冗余消除。

**性能数据**：

| 平台 | 单线程 | 最佳多线程 | Parendi 最佳 | 几何平均加速 |
|------|--------|-----------|-------------|------------|
| Verilator (x86) | 基准 | 20×+（仅大设计） | — | — |
| Parendi (IPU) | 84× 慢（pico） | 1472–5888 tiles | 2.81× (ix3) / 2.75× (ae4) | **2.8×** |

关键洞察：单 tile 的 IPU 执行比 x86 慢约 37–84 倍，因此必须大规模并行才能追上 Verilator。但 IPU 的高带宽通信使其在千核级别仍能获得近线性加速，而 x86 在跨 chiplet/socket 时加速比骤降。

### 5. LLVM Bit-Level Optimization for FPGA：位级变换与部分选择

LLVM 针对 FPGA 综合的位级优化技术同样适用于 RTL 仿真器的编译期优化：

- **BFG（Bit-Flow Graph）**：构建位的数据流图，每个节点表示 CONSTANT、VARIABLE、SET、NOT、AND/OR/XOR。
- **BFG 简化规则**（类似位级常量传播与窥孔优化）：
  - 规则 1–3：位级复制传播（SET/NOT 输入为 SET 时，直接指向原始输入）。
  - 规则 4：AND/OR/XOR 双输入均为常量 → 替换为常量节点。
  - 规则 5：AND 输入为常量 0 → 替换为 0；输入为常量 1 → 替换为另一输入。
  - 规则 6：OR 输入为常量 1 → 替换为 1；输入为 0 → 替换为另一输入。
- **部分选择（part_select）变换**：`(x >> 8) & y` 被识别为仅需 `x` 的低 24 位参与运算，生成 24 位 AND 而非 32 位。

**实验数据**：`bit_reverse` 函数经位级优化后，综合结果从 **34 slices + 3 周期** 降至 **0 slices + 0 延迟**（纯位重排赋值）。

## 对 RTL 仿真器多线程化的启示

1. **字级向量运算是多线程 cache 效率的关键**：将 64 位总线运算打包为单条机器字操作，减少每个线程的内存访问次数和指令数，使 macro-task 的代码体积适配 L1 缓存。
2. **位级分裂降低跨线程通信量**：若某 32 位信号只有 3 位被下游使用，编译期将其分裂为 3 个独立 1 位信号 + 29 位常量/死码，可减少分区割边（cut）上的数据交换量。
3. **超节点聚合与多线程粒度匹配**：超节点的大小应与 macro-task 的计算量匹配。超节点过小 → 调度开销高；超节点过大 → 负载均衡差。GSIM 的 20–50 阈值经验可作为 Verilator 多线程划分的参考。
4. **E-AIG 的紧凑表示适合 NUMA 多核**：GEM 将 800 MB Verilog 压缩为 162 MB E-AIG bitstream，启示：在 Verilator 的 V3VariableOrder（TSP 近似优化变量布局）之前，先用 AIG 重写压缩节点数，可显著降低其内存占用和运行时间（Parendi 指出 Verilator 的 V3VariableOrder 对 sr15 消耗 1043 GiB 内存，编译近 8 小时）。
5. **Word-level parallelism 与批处理测试向量的结合**：若 RTL 仿真器需要运行大量回归测试，可在编译期将测试向量打包为字级位向量，实现 SIMD 式并行求值——这本质上是将 Dart 的 cross-stimulus 冗余消除与 GEM 的 word-level parallelism 融合。

## 原文摘录

> "Word-level simulation leverages the structural representation by word-wise application of the Boolean operators. The computational cost of a bit-level simulation is O(2^k). Instead, word-level simulation for an XAIG representation has a cost O(|XAIG| 2^(k-l)) because we need to perform a binary operation for each node in the XAIG."
> — The Combinational-Complexity Game For Symmetric Functions (IWLS 2023)

> "We are on average 9.15x, 5.98x, and 24.87x faster than the leading commercial tool, 8-threaded Verilator and 1-threaded Verilator respectively. The peak speed-ups happen on the deep-learning accelerator NVDLA where we are 64.76x and 38.85x faster than Verilator 1 thread and the commercial tool."
> — GEM: GPU-Accelerated Emulator-Inspired RTL Simulation (DAC 2025)

> "GSIM succeeds in simulating XiangShan... compared to Verilator, GSIM can achieve speedup of 7.34x for booting Linux on XiangShan, and 19.94x for running CoreMark on Rocket."
> — GSIM: Accelerating RTL Simulation for Large-Scale Designs (arXiv:2508.02236)

> "We compare the simulation rate of the IPU against an Intel Xeon 6348... For large designs, RTL simulation is up to 4x faster than Verilator. The geometric mean speedups are 2.81 and 2.75 compared to ix3 and ae4."
> — Parendi: Thousand-Way Parallel RTL Simulation (arXiv:2403.04714)

> "Word-level abstraction of components is useful for several reasons. Firstly, simulating word-level operations is significantly faster than simulating its bit-level description. A word-level abstraction allows us to rewrite the component in terms of word-level operations prior to simulation."
> — DATE 2001, Word-Level Abstraction of RTL Designs

## 相关链接

- [Parendi: Thousand-Way Parallel RTL Simulation (arXiv:2403.04714)](https://arxiv.org/html/2403.04714v1)
- [GEM: GPU-Accelerated Emulator-Inspired RTL Simulation (DAC 2025)](https://yibolin.com/publications/papers/SIM_DAC2025_Guo.pdf)
- [GSIM: Accelerating RTL Simulation for Large-Scale Designs (arXiv:2508.02236)](https://arxiv.org/html/2508.02236v1)
- [LLVM Bit-Level Optimization for FPGA](https://llvm.org/pubs/2010-02-FPGA-BitLevel.pdf)
- [Word-Level Abstraction of RTL Designs (DATE 2001)](https://past.date-conference.com/proceedings-archive/2001/DATE01/PDFFILES/01A_1.PDF)
- [The Combinational-Complexity Game For Symmetric Functions (IWLS 2023)](https://people.eecs.berkeley.edu/~alanmi/publications/2023/iwls23_symm.pdf)

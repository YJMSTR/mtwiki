---
title: Roofline 模型在 RTL 仿真中的性能分析
description: 搜集 Roofline 性能模型在 RTL 仿真器、事件驱动仿真和多线程 CPU 架构上的应用，包含带宽瓶颈与算力瓶颈的识别方法、 ceilings 分析、以及针对 RTL 仿真负载特征的测量与调参策略
source_url: "https://docs.nersc.gov/tools/performance/roofline/"
source_type: "doc"
author: "NERSC / Samuel Williams / CMU Spiral"
date: "2009-2024"
tags: ["roofline", "performance-modeling", "bandwidth-bound", "compute-bound", "cache-analysis", "multicore"]
keywords: ["roofline model", "operational intensity", "memory bandwidth ceiling", "compute ceiling", "RTL simulation performance", "arithmetic intensity"]
capture_date: "2026-07-03"
---

# Roofline 模型在 RTL 仿真中的性能分析

## 来源

- URL: https://docs.nersc.gov/tools/performance/roofline/
- 类型: doc
- 作者: NERSC (Lawrence Berkeley National Laboratory)
- 日期: 持续更新
- 补充来源:
  - Williams, Waterman & Patterson (2009) 原始论文: https://people.eecs.berkeley.edu/~kubitron/cs252/handouts/papers/RooflineVyNoYellow.pdf
  - CMU Spiral Roofline 扩展: https://spiral.ece.cmu.edu/pub-spiral/pubfile/ispass-2013_177.pdf
  - NERSC Roofline 工具链与脚本: https://github.com/cyanguwa/nersc-roofline
  - Vortech GPU 迁移白皮书: https://www.vortech.nl/assets/uploads/851_12_24-VORtech-whitepaper-GPU-Transition-03.pdf
  - LBL AMCR Roofline 介绍: https://amcr.lbl.gov/departments/computer-science-department/ppan/roofline-performance-model/
  - FPGA Roofline 扩展 (HAL thesis): https://theses.hal.science/tel-05461322v1/file/LEE_Seungah.pdf
  - 扩展 Roofline 瓶颈分析 (Cabezas et al.): https://spiral.ece.cmu.edu/pub-spiral/pubfile/paper_181.pdf

## 摘要

Roofline 模型是一种将硬件算力上限与内存带宽上限结合为单一「屋顶」图的可视化性能分析工具。对于 RTL 仿真器而言，该模型的意义在于：RTL 仿真本质上是**整数位运算密集型负载**（非浮点），其瓶颈常常在「内存带宽天花板」与「CPU 算力天花板」之间切换。当设计规模较小（如 picorv32）时，仿真器受限于单线程整数运算吞吐；当设计规模增大（如 NVDLA 50 万变量），cache miss 导致内存带宽成为主导瓶颈；当多线程化后，同步开销（barrier / spin-lock）又构成一道新的「天花板」。本文档汇总 Roofline 模型的核心公式、测量方法、 ceilings 细分，以及针对 RTL 仿真负载的具体适配策略。

## 关键要点

### 1. Roofline 核心公式

标准 Roofline 模型的性能上限由以下公式描述：

```
P = min(P_peak, I × BW_peak)
```

- **P_peak**：硬件峰值算力（对 RTL 仿真，用「整数运算/秒」或「模拟 cycle/秒」替代 GFLOPS）
- **BW_peak**：峰值内存带宽（GB/s）
- **I**：运算强度（Operations / Byte），即每移动 1 字节数据所执行的运算量
- **ridge point**：P_peak / BW_peak，运算强度低于此值 → 内存带宽受限；高于此值 → 算力受限

对于 RTL 仿真器，运算强度需重新定义：

```
I_RTL = (每周期逻辑运算次数) / (每周期访问内存字节数)
```

由于 RTL 仿真以位运算、查找表、条件判断为主，**有效运算强度通常很低**（< 1 op/byte），这意味着大多数 RTL 仿真器天然偏向内存带宽瓶颈区域。

### 2. RTL 仿真负载的三层天花板

RTL 仿真器在 Roofline 图中面临的不是单一屋顶，而是多层 ceilings：

| 天花板层级 | 具体瓶颈 | 典型数值（x86 服务器） | 诊断方法 |
|-----------|---------|---------------------|----------|
| **L1: 原始算力** | CPU 核心频率、ILP、SIMD | 3–5 GHz 整数吞吐 | `perf stat -e cycles,instructions` |
| **L2: 内存带宽** | DRAM / LLC 带宽、cache miss | 50–200 GB/s | `perf stat -e cache-misses,LLC-load-misses` |
| **L3: 同步开销** | barrier、spin-lock、线程调度 | 无法用原始 Roofline 捕获 | VTune Threading 分析 / 自定义计时 |

**关键洞察**：RTL 仿真器的多线程扩展性受 L3 天花板（同步开销）影响最大。Manticore 论文指出：

> "Manticore is not immune to Amdahl's law. If there is insufficient parallelism in the workload, then Manticore's scaling plateaus."

这意味着即使硬件算力和内存带宽尚未饱和，RTL 设计的**串行数据依赖**（如 Huffman 表查找、顺序状态机）仍会压死并行扩展。

### 3. 测量 Roofline 的具体方法

#### 3.1 硬件参数测量（ ceilings 只需测一次）

```bash
# 1. 内存带宽测量（STREAM 基准）
# 编译并运行 STREAM，获取可持续内存带宽
gcc -O3 -march=native -fopenmp stream.c -o stream
OMP_NUM_THREADS=16 ./stream
# 记录 Triad 带宽作为 BW_peak

# 2. 整数算力峰值测量（microbenchmark）
# 使用自定义循环展开，测量纯整数位运算吞吐
# 或直接使用 Intel ERT (Empirical Roofline Toolkit)
git clone https://github.com/LLNL/empirical-roofline-toolkit
cd empirical-roofline-toolkit
make && ./run_ert.sh
```

#### 3.2 应用参数测量（每个 workload 需测）

```bash
# 1. 测量仿真器的「运算强度」与「实际性能」
# 运算次数：可通过 Verilator 的 --stats 或插入计数器获得
# 内存流量：使用 perf 或 PAPI
perf stat -e instructions,cache-references,cache-misses \
  -e uncore_imc/cas_count_read/,uncore_imc/cas_count_write/ \
  ./obj_dir/Vtop

# 2. 计算实际性能（simulated cycles / wall-clock time）
# 这是 RTL 仿真的「有效吞吐」，替代 GFLOPS
P_actual = (模拟的 RTL 周期数) / (实际运行时间，秒)
```

#### 3.3 绘制 Roofline 图（Python 示例）

```python
import numpy as np
import matplotlib.pyplot as plt

# 硬件参数（示例：Intel Xeon EPYC 类服务器）
P_peak = 100e9      # 100 Gops/s 整数峰值（假设）
BW_peak = 100e9     # 100 GB/s 内存带宽

# 运算强度轴
I = np.logspace(-2, 3, 500)  # 0.01 到 1000 ops/byte

# Roofline 公式
P_roof = np.minimum(P_peak, I * BW_peak)

# 实际测量点（示例：不同规模的 RTL 设计）
workloads = {
    'picorv32':  {'I': 0.1,  'P': 15e9},
    'small-SoC': {'I': 0.3,  'P': 25e9},
    'RISC-V-MP': {'I': 0.5,  'P': 35e9},
    'NVDLA':     {'I': 0.05, 'P': 5e9},   # 低运算强度，内存瓶颈
}

plt.figure(figsize=(10, 6))
plt.loglog(I, P_roof, 'k-', linewidth=2, label='Roofline')
plt.axvline(P_peak/BW_peak, color='gray', linestyle='--', label='Ridge Point')

for name, data in workloads.items():
    plt.loglog(data['I'], data['P'], 'o', markersize=10, label=name)

plt.xlabel('Operational Intensity (ops/byte)')
plt.ylabel('Performance (ops/sec)')
plt.legend()
plt.grid(True, which='both', linestyle=':')
plt.title('Roofline Model for RTL Simulation')
plt.show()
```

### 4. Ceilings 细分：从「屋顶」到「天花板」

原始 Roofline 论文提出的 ceilings 概念对 RTL 仿真器尤为实用：

**内存带宽 ceilings（自底向上）**：
1. **无软件预取**：带宽降低 30–50%（RTL 仿真器很少做预取）
2. **无 NUMA 亲和**：跨节点访问降低带宽 40%+
3. **无单位步长访问**：stride 访问进一步降低有效带宽

**算力 ceilings（自顶向下）**：
1. **无 SIMD 向量化**：RTL 仿真是标量位运算，SIMD 收益有限
2. **无 ILP**：指令级并行受限，因为每个 RTL 周期内有数据依赖
3. **分支预测失败**：X/Z 值处理引入不可预测分支

对于 RTL 仿真器，**最有意义的优化方向**通常是：
- **如果点在 ridge point 左侧（内存瓶颈）**：优化变量布局（V3VariableOrder）、减少 cache miss、使用 hugepage
- **如果点在 ridge point 右侧（算力瓶颈）**：提高逻辑运算吞吐、减少分支、使用更激进的编译优化（`-O3 -march=native`）
- **如果点远离两条线**：同步开销或 I/O 是主导，需分析线程调度或波形输出

### 5. FPGA Roofline 对 RTL 仿真器的反向启示

FPGA 的 Roofline 模型与 CPU 不同：

> "For both CPUs and GPUs, the roofline is fixed for a given architecture and does not depend on the applications and kernels executed. However, considering the reconfigurable characteristics of FPGA, the FPGA roofline model should be hardware-specific and application-specific."
> — LEE Seungah, FPGA Roofline Model

RTL 仿真器在 CPU 上运行，但模拟的是硬件。理解 FPGA Roofline 有助于：
- 预判被模拟设计的**并行潜力**：如果目标硬件设计本身串行度高（如 jpeg 的 Huffman 解码），则无论 CPU 多强，仿真速度都受限于该串行瓶颈。
- 识别「可并行模块」与「串行关键路径」：Roofline 分析可以帮助确定哪些模块值得投入多线程资源。

## 对 RTL 仿真器多线程化的启示

1. **RTL 仿真天然偏向内存带宽瓶颈**：由于运算强度低（位运算多、数据移动大），单纯提升 CPU 算力（超频、更多核）收益有限，必须同步优化内存子系统（cache、NUMA、带宽）。

2. **多线程引入的「同步天花板」是独立于 Roofline 的新维度**：原始 Roofline 模型不考虑同步开销。RTL 仿真器在 4 线程以上常出现「实际性能远低于 Roofline 预测」的情况，这正是同步开销所致。建议将 Roofline 图与线程扩展性图并列分析。

3. **变量布局优化可直接提升运算强度**：Parendi 论文证实，V3VariableOrder 通过减少跨线程 cache miss，相当于把「点」从左侧向 ridge point 移动，性能提升约 30%。这是 Roofline 框架下「优化内存效率」的具体实例。

4. **Benchmark 设计需覆盖三个运算强度区域**：
   - 低运算强度（大设计，内存瓶颈）：如 NVDLA、OpenTitan
   - 中等运算强度（中等设计，混合瓶颈）：如 RISC-V SoC
   - 高运算强度（小设计，算力瓶颈）：如 picorv32、纯组合逻辑

5. **测量周期只需一次，但需精确**：硬件的 P_peak 和 BW_peak 只需测量一次，但 RTL 仿真的 I 和 P_actual 必须对每个 workload 单独测量。建议使用 `perf` + `ERT` 组合，自动化绘制 Roofline 图。

## 原文摘录

> "The Roofline model visually relates performance P and operational intensity I of a given program to the platform's peak performance and memory bandwidth."
> — Williams, Waterman & Patterson, CACM 2009

> "The roofline model is a very simple tool to reason about the bottlenecks in an application. Point P is close to the memory bandwidth ceiling. In this case, we cannot get additional performance without increasing the memory bandwidth. Point Q is close to the performance ceiling. Point R is far away from both ceilings — the design can be modified to use far more memory bandwidth and much more computational capacity."
> — IIT Delhi 教材, Main Memory 章节

> "A roofline analysis is a practical approach to understand the performance potential of software that runs on specific hardware. While the model is limited in capturing the full complexity of modern hardware, it remains a valuable tool for analyzing the performance behavior of a specific hardware/software combination."
> — Vortech GPU 迁移白皮书

> "For external memory, its bandwidth is the multiplication of memory data rate and memory channel bit-width. In the case of an interface, the bandwidth is the multiplication of clock frequency, transfer data bit-width, and the number of interface ports."
> — LEE Seungah, FPGA Roofline 论文

> "Autotuning three of the four kernels gets very close to the compulsory memory traffic; in fact, the resultant working set is sometimes only a small fraction of the cache. Increasing cache size helps only with capacity misses and possibly conflict misses, so a larger cache can have no effect on the operational intensity for those three kernels."
> — Roofline 原始论文, 关于 cache 与运算强度关系的讨论

## 相关链接

- [NERSC Roofline Performance Model](https://docs.nersc.gov/tools/performance/roofline/)
- [Roofline: An Insightful Visual Performance Model (原始论文)](https://people.eecs.berkeley.edu/~kubitron/cs252/handouts/papers/RooflineVyNoYellow.pdf)
- [Empirical Roofline Toolkit (ERT)](https://github.com/LLNL/empirical-roofline-toolkit)
- [LBL AMCR Roofline 介绍](https://amcr.lbl.gov/departments/computer-science-department/ppan/roofline-performance-model/)
- [CMU Spiral Roofline 扩展论文](https://spiral.ece.cmu.edu/pub-spiral/pubfile/ispass-2013_177.pdf)
- [扩展 Roofline 瓶颈分析 (Cabezas et al.)](https://spiral.ece.cmu.edu/pub-spiral/pubfile/paper_181.pdf)
- [Manticore: Hardware-Accelerated RTL Simulation](https://ar5iv.labs.arxiv.org/html/2301.09413)
- [Parendi: Thousand-Way Parallel RTL Simulation](https://arxiv.org/html/2403.04714v2)

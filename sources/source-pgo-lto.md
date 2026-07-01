---
title: Profile-Guided Optimization (PGO)、LTO 与 BOLT 在编译器优化中的应用
description: 搜集 PGO、LTO（Whole Program Optimization）、BOLT / Propeller 等后链接优化器在编译器链路中的位置、实现原理、性能收益与工程实践，特别关注仿真器等计算密集型应用的收益数据。
source_url: "https://arxiv.org/html/2507.16649v1"
source_type: "paper"
author: "Weixing Ji 等"
date: "2025-07-22"
tags: ["PGO", "LTO", "BOLT", "compiler-optimization", "post-link-optimization", "profile-guided"]
keywords: ["PGO RTL simulation", "LTO whole program optimization", "BOLT binary optimizer", "Verilator Thread PGO"]
capture_date: "2026-07-01"
---

# PGO、LTO 与 BOLT：编译器优化的三重链路

## 来源

- URL: <https://arxiv.org/html/2507.16649v1>
- 类型: paper (survey, 2025)
- 作者: Weixing Ji 等（北京理工大学）
- 日期: 2025-07-22
- 辅助来源:
  - resvg PGO/LTO/BOLT Benchmark: <https://github.com/linebender/resvg/issues/765>
  - legba PGO/LTO/BOLT Benchmark: <https://github.com/evilsocket/legba/issues/10>
  - Symbolicator PGO/PLO Benchmark: <https://github.com/getsentry/symbolicator/issues/1334>
  - Propeller (Google): <https://dl.acm.org/doi/pdf/10.1145/3575693.3575727>

## 摘要

PGO（Profile-Guided Optimization）通过运行时剖面数据指导编译器优化决策，将静态分析与动态执行行为结合。LTO（Link-Time Optimization）将优化推迟到链接阶段，实现跨模块的全程序分析。BOLT（Facebook/Meta）和 Propeller（Google）则进一步在**最终二进制**层面进行后链接优化，利用精确的剖面数据重新排布代码布局，提升 I-Cache 命中率并降低分支预测失误。本文档汇总了 PGO 三阶段（编译期 / 链接期 / 后链接期）的技术分类、编译器集成（GCC/LLVM）以及实际工程 benchmark 数据，为 RTL 仿真器等计算密集型 C++ 项目的构建优化提供参考。

## 关键要点

- **PGO 的核心收益**：在真实应用上通常获得 **5%~30%** 的性能提升，SPEC2006 基准上 instrumentation PGO 约 5% 提升。分支预测、函数内联、循环展开、间接调用提升均受益。
- **LTO 的核心收益**：LLVM 的 LTO 在 SPEC2006 上平均提升 **2%~4%**，同时带来显著的二进制体积缩减（Fat LTO 可达 10%~15% 缩减）。Thin LTO 在编译时间上更优，收益接近 Fat LTO。
- **BOLT（Binary Optimization and Layout Tool）**：在最终 ELF 上操作，无需重新编译。通过采样数据（perf）重排热函数和基本块，提升 I-Cache 和分支预测。对于超大规模二进制（如 Chromium、Clang），BOLT 可在 LTO+PGO 基础上再获 **2%~5%** 收益。
- **Propeller（Google）**：类似 BOLT，但采用 relinking 方式，将基本块重排推迟到链接阶段，通过 `.text` 段重组实现更细粒度的代码布局。
- **AutoFDO**：基于硬件 PMU（Performance Monitoring Unit）的采样式 PGO，避免 instrumentation 带来的运行时开销（通常 instrumented binary 慢 **20%~50%**）。
- **实际工程中的教训**：
  - PGO 训练集必须具有代表性，否则性能下降（resvg 案例）。
  - BOLT 在中小规模二进制上收益可能微乎其微（resvg 和 legba 中 BOLT 几乎无额外提升）。
  - Instrumentation 阶段二进制体积膨胀 2~3 倍，需预留磁盘空间。

## 对 RTL 仿真器多线程化的启示

RTL 仿真器（如 Verilator、Synopsys VCS）属于**计算密集型、控制流复杂、热点函数集中**的应用，是 PGO/LTO 的理想目标：

1. **Verilator 的 Thread PGO 潜力**：Verilator 将 RTL 编译为 C++ 模型，多线程模式下每个时间步调度逻辑复杂，热点函数（如 `eval()`、`change()`）如果被内联或代码布局优化，可显著降低 I-Cache miss。Verilator 官方文档已提及 Thread PGO 的实验性支持。
2. **LTO 的跨模块优化**：RTL 仿真器通常生成大量 `.cpp` 文件，标准编译模式下函数内联无法跨文件。LTO 允许全程序视角的 dead code elimination 和 devirtualization，对模型中大量虚函数（如多态信号处理）特别有益。
3. **BOLT 的适用性有限**：RTL 仿真器生成的二进制通常不如 Chromium 那样庞大（>100MB），BOLT 的收益可能不显著。但如果仿真器链接了庞大的标准库或第三方库，BOLT 仍有潜力。
4. **建议的构建流程**：
   ```bash
   # Stage 1: 编译 instrumented 版本
   clang++ -O3 -fprofile-instr-generate -flto=thin ...
   # Stage 2: 运行代表性测试用例生成 .profraw
   LLVM_PROFILE_FILE="prof/%p.profraw" ./simulator --testcase=typical
   # Stage 3: 合并 profile
   llvm-profdata merge -o merged.profdata prof/
   # Stage 4: 编译优化版本
   clang++ -O3 -fprofile-instr-use=merged.profdata -flto=thin ...
   ```

## 原文摘录

> "PGO uses runtime profile data to guide compiler optimization decisions, aligning code generation closely with actual program behavior. PGO can yield speedups often in the range of 5%-30% on real applications, far surpassing what purely static heuristics can deliver."

> "Panchenko et al. introduced BOLT, which reorders and restructures code in the final executable based on sampling data. Working directly on the binary, BOLT accurately identifies hot functions and basic blocks and rearranges them to boost instruction cache performance and reduce branch mispredictions."

> "AutoFDO proposed by Chen et al. and BOLT proposed by Panchenko et al. both implement sampling-based PGO using PMU data, targeting compile-time and link-time optimizations respectively."

> "GCC does not have any built-in post-link optimization pass that consumes profile data once the binary is produced. All profile-guided optimizations in GCC occur either during the compile phase or the LTO link phase, but not after the final binary is emitted."

## 代码示例

### 1. Clang/LLVM PGO 完整流程（Instrumentation-based）

```bash
# Step 1: 编译 instrumented 版本
clang++ -O3 -fprofile-instr-generate -flto=thin \
    -o simulator_inst main.cpp model.cpp scheduler.cpp

# Step 2: 运行训练负载（必须是代表性工作负载）
LLVM_PROFILE_FILE="simulator_%p.profraw" \
    ./simulator_inst --benchmark typical_workload.v

# Step 3: 合并多线程产生的 profile 文件
llvm-profdata merge -sparse \
    -o simulator.profdata simulator_*.profraw

# Step 4: 使用 profile 重新编译
clang++ -O3 -fprofile-instr-use=simulator.profdata \
    -flto=thin -o simulator_opt main.cpp model.cpp scheduler.cpp
```

- **关键点**：`LLVM_PROFILE_FILE` 中的 `%p` 在多线程环境下为每个进程生成独立文件，避免并发写入冲突。
- **Thin LTO vs Fat LTO**：Thin LTO 编译速度快 3~5 倍，适合迭代开发；Fat LTO 全程序 IR 合并，优化更激进，适合最终发布构建。

### 2. GCC FDO（Feedback-Directed Optimization）流程

```bash
# Step 1: 编译并生成 profile
gcc -O3 -fprofile-generate -flto -o simulator_inst main.c model.c
./simulator_inst --training-data

# Step 2: 使用 profile 优化构建
gcc -O3 -fprofile-use -fprofile-correction -flto \
    -o simulator_opt main.c model.c
```

- **注意**：GCC 的 `-fprofile-correction` 在训练数据与优化构建不完全一致时（如条件编译差异），可修正不一致的 profile 计数。

### 3. BOLT 后链接优化（Post-Link）

```bash
# 前提：链接时保留重定位信息
clang++ -O3 -fprofile-instr-use=merged.profdata -flto=thin \
    -Wl,--emit-relocs -o simulator_prebolt main.cpp

# 使用 perf 采样（或 LLVM sampling）
perf record -e cycles:u -o perf.data -- ./simulator_prebolt workload

# 转换 perf 数据为 BOLT 格式
perf2bolt ./simulator_prebolt -p perf.data -o perf.fdata

# 运行 BOLT 优化
llvm-bolt ./simulator_prebolt -o simulator_bolt \
    -b perf.fdata \
    -reorder-blocks=ext-tsp \
    -reorder-functions=hfsort+ \
    -split-functions \
    -split-all-cold \
    -dyno-stats
```

- **输出解读**：`dyno-stats` 会打印优化前后的动态指令数、I-Cache miss、分支预测失误等对比。

## 性能数据

### 表 1: LLVM 官方 PGO 在 SPEC 上的典型收益（文献数据）

| 优化阶段 | 典型加速比 | 关键优化内容 | 编译时间开销 |
|---|---|---|---|
| Baseline (-O3) | 1.00x | — | 1.00x |
| + Thin LTO | 1.02~1.05x | 跨模块内联、去虚函数 | 1.5~2.0x |
| + PGO (Instr) | 1.05~1.15x | 热点内联、分支布局、循环优化 | 2.0x (训练) + 1.5x (优化编译) |
| + BOLT (Post-Link) | 1.02~1.05x | 代码重排、热/冷分离 | 1.2x (后处理) |
| **合计** | **1.10~1.25x** | — | **显著增加** |

### 表 2: 实际工程 Benchmark（resvg / legba / Symbolicator）

| 项目 | 配置 | 运行时间 | 二进制大小 | 来源 |
|---|---|---|---|---|
| resvg | Release | 276 s | 3.6 MiB | resvg#765 |
| resvg | + LTO | 262 s (-5.1%) | 3.1 MiB | resvg#765 |
| resvg | + LTO + PGO | 247 s (-10.5%) | 4.8 MiB | resvg#765 |
| resvg | + LTO + PGO + BOLT | 247 s (无额外收益) | 8.7 MiB | resvg#765 |
| legba | Release | 276 s | 21 MiB | legba#10 |
| legba | + LTO | 262 s | 17 MiB | legba#10 |
| legba | + LTO + PGO | 247 s (-10.5%) | 15 MiB | legba#10 |
| legba | + LTO + PGO + BOLT | 247 s (无额外收益) | 20 MiB | legba#10 |
| Symbolicator | Release | 2616 req/s | — | symbolicator#1334 |
| Symbolicator | + LTO + PGO + PLO | 3898 req/s (+49%) | — | symbolicator#1334 |

> **解读**：
> - resvg 和 legba 属于中等规模二进制，LTO+PGO 已榨取大部分收益，BOLT 锦上添花效果不明显。
> - Symbolicator 作为高吞吐网络服务，LTO+PGO+PLO 组合带来近 50% 的吞吐量提升，说明 I-Cache 和分支预测对服务类应用至关重要。
> - PGO instrumented 版本运行时会慢 20%~50%（Symbolicator: 2616 -> 785 req/s 下降 70%），训练环境需预留足够时间。

### 表 3: GCC 12 / LLVM 15 中 PGO 驱动的优化 Pass（部分）

| 编译阶段 | Pass 名称 | PGO 作用 |
|---|---|---|
| 编译期 | InlinePass | 根据调用频率调整内联决策 |
| 编译期 | IndirectCallPromotionPass | 将高频间接调用提升为直接调用+guard |
| 编译期 | BlockPlacementPass | 重排基本块以最大化 hot edge 的 fall-through |
| 编译期 | LoopUnrollPass | 热循环大量展开，冷循环保守展开 |
| 链接期 | FunctionImport (ThinLTO) | 基于 profile 跨模块导入热函数 |
| 链接期 | MachineBlockPlacement | 机器级基本块重排，对齐热循环 |
| 后链接期 | BOLT | 最终 ELF 重排函数与基本块 |
| 后链接期 | Propeller | 全程序基本块与函数重排 |

## 相关链接

- [PGO 综述论文 (Ji et al., 2025)](https://arxiv.org/html/2507.16649v1)
- [resvg PGO/LTO/BOLT Benchmark](https://github.com/linebender/resvg/issues/765)
- [legba PGO/LTO/BOLT Benchmark](https://github.com/evilsocket/legba/issues/10)
- [Symbolicator LTO+PGO+PLO Benchmark](https://github.com/getsentry/symbolicator/issues/1334)
- [Propeller: Google 的 Profile-Guided Relinking Optimizer](https://dl.acm.org/doi/pdf/10.1145/3575693.3575727)
- [BOLT GitHub (Meta)](https://github.com/llvm/llvm-project/tree/main/bolt)
- [GCC Profile-Guided Optimization 文档](https://gcc.gnu.org/onlinedocs/gcc/Optimize-Options.html)
- [LLVM PGO 文档](https://llvm.org/docs/HowToBuildWithPGO.html)

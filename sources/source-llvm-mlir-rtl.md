---
title: "LLVM/MLIR for RTL Optimization: CIRCT, Hardware Dialects, and Compiler Passes"
description: "系统梳理LLVM/MLIR生态在RTL优化与硬件设计中的应用，重点覆盖CIRCT项目架构（FIRRTL/HW/Comb/Seq/LLHD/SV方言）、PipeRTL等基于MLIR的时序优化工具、以及MLIR到Verilog/SystemVerilog的 lowering pipeline。"
source_url: "https://circt.llvm.org/"
source_type: "doc"
author: "CIRCT Community / LLVM Project"
date: "2021-2025"
tags: ["LLVM", "MLIR", "CIRCT", "RTL-optimization", "hardware-dialect", "FIRRTL", "LLHD", "HLS"]
keywords: ["MLIR dialect", "CIRCT", "hardware compiler", "RTL lowering", "optimization pass", "PipeRTL"]
capture_date: "2026-07-02"
---

# LLVM/MLIR 生态在 RTL 优化与硬件编译中的应用

## 来源

- **URL**: https://circt.llvm.org/
- **类型**: 开源项目文档 / 学术论文综述
- **作者**: CIRCT Community (LLVM 子项目)
- **日期**: 2021–2025（持续演进中）

## 摘要

CIRCT（Circuit IR Compilers and Tools）是LLVM生态中专门面向硬件设计的编译基础设施，基于MLIR（Multi-Level Intermediate Representation）构建。本文档汇总CIRCT及其周边项目在RTL优化中的核心技术：

1. **CIRCT 核心方言体系**：FIRRTL → HW/Comb/Seq → SV/LLHD 的多级 lowering pipeline；
2. **MLIR硬件Dialect**：hw（模块与端口）、comb（组合逻辑）、seq（时序逻辑）、llhd（低层仿真）各自的语义与优化机会；
3. **PipeRTL**：基于CIRCT的IR级流水线时序优化工具，通过寄存器重定位实现时序感知优化；
4. **ksim/MLIR to LLVM IR**：将RTL设计通过MLIR下沉到LLVM IR，再借助LLVM后端生成高效仿真代码；
5. **编译器优化遍**：常量传播（CF）、死代码消除（DCE）、公共子表达式消除（CSE）在硬件IR上的应用。

## 关键要点

### 1. CIRCT 架构与多级 Lowering Pipeline

CIRCT的设计哲学是借鉴LLVM/MLIR的模块化、可扩展架构，为硬件设计提供一套统一的中间表示与编译器基础设施。其核心方言按抽象层级从高到低排列：

```
┌─────────────────────────────────────────────────────────┐
│  High-Level: Handshake, HIR, Affine, Calyx               │  ← 高层综合入口
├─────────────────────────────────────────────────────────┤
│  Mid-Level:  FIRRTL → HW/Comb/Seq                       │  ← RTL级核心表示
├─────────────────────────────────────────────────────────┤
│  Low-Level:  LLHD (仿真) / SV (SystemVerilog生成)         │  ← 后端代码生成
├─────────────────────────────────────────────────────────┤
│  Target:     Verilog / SystemVerilog / LLVM IR           │  ← 输出到EDA或仿真器
└─────────────────────────────────────────────────────────┘
```

**核心方言详解**：

| Dialect | 作用 | 关键操作示例 |
|---------|------|------------|
| **FIRRTL** | Chisel编译器的IR，描述带类型参数的硬件模块 | `firrtl.module`, `firrtl.connect` |
| **HW** | 通用硬件结构：模块、端口、实例化 | `hw.module`, `hw.instance`, `hw.output` |
| **Comb** | 组合逻辑操作 | `comb.add`, `comb.and`, `comb.mux` |
| **Seq** | 时序逻辑（寄存器、时钟、复位） | `seq.firreg`, `seq.compreg` |
| **LLHD** | 低层硬件描述，支持时间类型与9值逻辑 | `llhd.entity`, `llhd.sig`, `llhd.drv` |
| **SV** | SystemVerilog语法导出，用于可读性优化 | `sv.always`, `sv.ifdef` |

### 2. MLIR Hardware Dialect 的优化机会

MLIR的方言系统允许开发者在不同抽象层级定义专用的分析与转换遍。CIRCT利用这一点，在RTL级别实现了以下优化：

**常量折叠（Constant Folding, CF）**：
- 在 `comb.and` 上若输入为常量，可在编译期直接计算结果；
- 示例：`and(x, 0) → 0`，`and(x, -1) → x`。

**死代码消除（Dead Code Elimination, DCE）**：
- 移除未被任何输出或端口驱动的内部逻辑；
- 对大型SoC设计尤为重要，可显著减少仿真时的计算量。

**公共子表达式消除（Common Subexpression Elimination, CSE）**：
- 识别硬件IR中重复的组合逻辑子树，合并为单一实例；
- 在CIRCT中通过MLIR的 `CSE` pass自动完成。

```mlir
// 优化前：两个相同的加法
%0 = comb.add %a, %b : i32
%1 = comb.add %a, %b : i32
%2 = comb.and %0, %1 : i32

// 优化后（CSE）：合并为一个加法
%0 = comb.add %a, %b : i32
%1 = comb.and %0, %0 : i32
```

### 3. PipeRTL：基于CIRCT的IR级流水线时序优化

**PipeRTL**（2026年论文）提出在CIRCT的HW/Comb/Seq方言层级上进行**时序感知的流水线优化**，避免传统HLS工具在高层C/C++处做调度的盲目性。

**核心机制**：
- 利用CIRCT的结构保留特性，在 lowering 到 Verilog 之前插入流水线专用语义；
- 通过寄存器重定位（register relocation）平衡关键路径；
- 与CIRCT的 `seq.firreg` 和 `comb.add` 等操作直接交互，无需重新解析文本RTL。

**性能数据**：
- 在IIR滤波器等多个基准电路上，PipeRTL相比直接综合可减少寄存器数量，同时满足时序约束；
- 由于优化发生在IR层，可与CIRCT现有遍（DCE、CSE）组合使用，形成完整的优化流水线。

### 4. ksim：MLIR → LLVM IR 的 RTL 仿真路径

ksim（Khronos）展示了如何利用CIRCT+LLVM实现RTL仿真的完整编译链：

```bash
# FIRRTL → MLIR (HW dialect)
firtool --ir-hw design.fir -o design.mlir

# MLIR → LLVM IR (ksim自定义lowering)
ksim design.mlir -o design.ll --out-header=design.h --out-driver=design.cpp

# LLVM IR → 机器码
llc -O2 -filetype=obj design.ll -o design.o
clang++ -O2 design.o design.cpp -o design_sim
```

**优化价值**：
- LLVM IR级别的优化（如循环展开、向量化、LTO）可自动作用于RTL生成的仿真代码；
- 通过 `--relocation-model=dynamic-no-pic` 减少间接跳转开销，提升仿真主循环速度；
- 多线程潜力：LLVM后端天然支持OpenMP，可将RTL的独立always块并行编译为线程安全函数。

### 5. LLHD：受LLVM启发的低层硬件仿真IR

LLHD（Low-Level Hardware Description）最初由Fabian Schuiki以Rust实现（含 `moore` 编译器与 `llhd-sim` 仿真器），后被整合进CIRCT作为核心方言之一。

**设计特点**：
- **时间类型内嵌**：`llhd.time` 将时间信息编码在类型系统中，而非注释或元数据；
- **9值逻辑**：支持标准逻辑值（0, 1, X, Z等）以及更细粒度的未初始化解；
- **SSA形式**：与LLVM IR一致，便于复用现有编译器分析与优化算法。

```mlir
// LLHD 示例：带延迟的驱动
llhd.entity @top (%arg0: !llhd.sig<i1>) -> (%arg1: !llhd.sig<i1>) {
  %t = llhd.constant_time <1ns, 0d, 0e> : !llhd.time
  %0 = llhd.prb %arg0 : !llhd.sig<i1>
  llhd.drv %arg1, %0 after %t : !llhd.sig<i1>
}
```

**CIRCT中的仿真路径**：
- `moore` 编译器（Rust原型）将SystemVerilog解析为LLHD IR；
- CIRCT中的 `llhd-sim` 引擎可直接执行LLHD IR，输出VCD波形；
- 未来路线：FIRRTL → RTL → LLHD，取代直接的 FIRRTL-to-LLHD，以复用更多中间优化。

## 对 RTL 仿真器多线程化的启示

1. **IR级优化先于线程划分**：在多线程RTL仿真之前，先在MLIR/CIRCT层级运行DCE、CSE、常量折叠，可减少每个线程需要执行的冗余计算，提升并行效率。

2. **LLHD/LLVM IR 是天然的并行中间层**：将RTL设计lower到LLVM IR后，可利用LLVM的 `loop-vectorize` 和 `slp-vectorizer` 对位宽运算进行向量化，适合现代CPU的SIMD单元。

3. **CIRCT方言支持增量编译**：MLIR的模块化设计允许仅重新编译修改过的模块，对大型SoC的增量仿真（incremental simulation）极为有利。

4. **PipeRTL表明时序优化可在IR层完成**：不必等待后端EDA工具做布局布线后的时序分析，可在CIRCT中提前做流水线调度，为多线程RTL仿真提供更均衡的负载划分。

5. **性能数据参考**：
   - Verilator（C++ AOT）比Icarus Verilog（解释执行）快约 **100x**；
   - ksim利用LLVM IR编译后，在单线程上可达 **42.66 kHz**（对比Icarus的 **1.49 kHz**）；
   - PipeRTL在多个IIR基准上减少寄存器数量，同时保持时序约束。

## 原文摘录

> "CIRCT is a framework for building hardware compiler infrastructure, with the goal of making hardware design more productive through better compiler optimization, analysis, and transformation tools. CIRCT is built on the MLIR framework (from the LLVM project), which provides robust infrastructure for defining specialized compiler IRs, transformations, and analyses."
> — CIRCT官方文档

> "CIRCT supports core dialects for RTL representation: hw dialect offers function-like semantics to represent module information; comb dialect represents combinational components; seq dialect represents sequential logic; sv dialect represents SystemVerilog semantics."
> — PipeRTL论文, arXiv:2605.01836

> "Some studies focus on optimizing and transforming the MLIR infrastructure to enhance HLS and code generation. For instance, CIRCT converts MLIR to RTL code, serving as an open-source HLS tool."
> — HEC论文, arXiv:2506.02290

> "The resulting Verilated executable performs the design simulation. Verilator compiles your code into a much faster optimized and optionally thread-partitioned model. [...] on a single thread is about 100 times faster than interpreted Verilog simulators."
> — Verilator官方文档

## 相关链接

- [CIRCT 官方网站](https://circt.llvm.org/)
- [CIRCT GitHub](https://github.com/llvm/circt)
- [MLIR 官方文档](https://mlir.llvm.org/)
- [PipeRTL: Timing-Aware Pipeline Optimization at IR-Level](https://arxiv.org/html/2605.01836v1)
- [HEC: Equivalence Verification Checking for MLIR](https://arxiv.org/html/2506.02290v2)
- [ksim (Khronos) GitHub](https://github.com/pku-liang/ksim)
- [LLHD: Multi-level IR for Hardware Description](https://github.com/fabianschuiki/moore)
- [Applying CIRCT to ML Applications (MLSys 2021 Slides)](https://media.mlsys.org/Conferences/MLSYS2021/Slides/Applying-CIRCT.pdf)
- [面向ASIC设备的编译器框架：TVM or MLIR？](https://zai.csdn.net/64d346d84c7ead5211f100b3.html)

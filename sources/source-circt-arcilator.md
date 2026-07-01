---
title: CIRCT / Arcilator：基于 MLIR 的编译器 IR 级 RTL 仿真
description: LLVM CIRCT 项目中的 Arcilator 仿真器，利用多层 IR 优化实现超越 Verilator 的周期精确仿真性能
source_url: "https://github.com/llvm/circt"
source_type: "github-repo"
author: "Martin Erhart, Fabian Schuiki, Zachary Yedidia, Bea Healy, Tobias Grosser (SiFive / CIRCT 社区)"
date: "2023-10"
tags: [circt, arcilator, mlir, llvm, rtl-simulation, compiler-ir, chisel, systemverilog]
keywords: [CIRCT Arcilator, mlir rtl simulation, llvm circt simulator, Arcilator performance, cycle-accurate, hardware simulation]
capture_date: "2026-07-02"
---

# CIRCT / Arcilator：基于 MLIR 的编译器 IR 级 RTL 仿真

## 来源

- URL: https://github.com/llvm/circt
- 类型: github-repo / conference-talk
- 作者: Martin Erhart, Fabian Schuiki 等 (SiFive / CIRCT 社区)
- 日期: 2023-10 (LLVM 2023 Dev Meeting 演讲)

## 摘要

Arcilator（原名 Circilator）是 LLVM 旗下 CIRCT（Circuit IR Compilers and Tools）项目的核心仿真后端，旨在利用 MLIR（Multi-Level Intermediate Representation）的编译器基础设施实现**周期精确、高性能的 RTL 仿真**。与 Verilator 直接将 SystemVerilog 转译为 C++ 不同，Arcilator 在 HW/Comb/Seq/Clock 等 CIRCT 核心方言上构建多层 IR 优化管线，再 lowering 到 Arc 方言，最终生成 LLVM IR 并编译为原生二进制。LLVM 2023 Dev Meeting 数据显示：Arcilator 在 Rocket-small 上比 Verilator 快 **4.3 倍**，二进制体积小 **4 倍**；在 BOOM-large 上仍保持 **1.9 倍** 速度优势。其设计哲学是将软件编译器的优化方法（死代码消除、常量传播、跨方言变换）系统性地引入硬件仿真领域。

## 关键要点

- **多层 IR 架构**：SystemVerilog/Chisel → Moore/HW/Comb/Seq/LLHD 方言 → Arc 方言 → LLVM IR → 二进制。每一层都可插入方言级优化，这是 Verilator 等直接转译器不具备的能力。
- **Cycle-Based 静态调度**：Arcilator 采用与 Verilator 类似的 full-cycle 静态调度（而非 LLHD-Sim 的事件驱动动态调度），适合高吞吐的 cycle-accurate 仿真。
- **性能基准**（LLVM 2023 演讲数据）：
  - Rocket-small：Arcilator 4.3x 快于 Verilator，二进制 4x 更小
  - BOOM-large：Arcilator 1.9x 快于 Verilator，二进制 1.8x 更小
  - 支持 Rocket、BOOM 等多款 RISC-V 核的完整仿真（见 [circt/arc-tests](https://github.com/circt/arc-tests)）
- **前端支持**：当前完整支持 Chisel/FIRRTL；通过 `circt-verilog` 支持 SystemVerilog 子集（基于 slang 前端），但仍有局限（如异步复位 `always_ff @(posedge clk or posedge rst)` 在 StripSV pass 中报错）。
- **工程状态**：作为 CIRCT 项目的一部分活跃开发中，SiFive 是主要贡献者。已支持 seq.firreg、comb 逻辑、时钟域等基本构造，延迟/事件驱动支持仍在完善（`llhd.constant_time` 尚未完整 lowering 到 Arc）。
- **生态整合**：Chisel 3.5+ 可直接通过 CIRCT 管线生成 Arcilator 仿真二进制；[circt/arc-tests](https://github.com/circt/arc-tests) 提供 BOOM 与 Rocket 的 benchmark 与 C++ testbench 模板。

## 对 RTL 仿真器多线程化的启示

Arcilator 的核心理念——**将 RTL 仿真视为编译问题**——对多线程化有深刻启发：
1. **IR 级优化优于源码级优化**：在 C++ 生成之后才做优化（如 Verilator 的 `--O3`）错过了跨模块、跨时钟域的硬件特定优化机会。如果在 HW/Comb/Seq 层就做死代码消除、常量传播、寄存器合并，可以直接减少仿真时每周期需要评估的逻辑量。
2. **静态调度简化并行化**：Arcilator 的 full-cycle 静态调度天然消除了事件队列的竞争瓶颈。对于多线程 RTL 仿真器，如果能在编译期将设计划分为时间推进方式一致的「周期岛屿」，线程同步开销将大幅降低。
3. **LLVM 后端复用**：将 RTL  lowering 到 LLVM IR 意味着可以自动享受 LLVM 的向量化、LTO、链接时优化等成熟基础设施。对于我们的项目，评估是否可将部分优化后代码委托给 LLVM JIT 而非手写 C++ 线程调度，是一个值得探索的方向。
4. **Arc 方言的借鉴**：Arc 方言将硬件描述转化为显式的数据流（Arc Data-Flow Comb）与控制流（Arc Control-Flow Comb），这种显式拆分有助于识别可并行评估的独立逻辑锥。

## 代码示例

### Arcilator 使用流程（SystemVerilog）

```bash
# 1. 编译安装 CIRCT（需 LLVM/MLIR）
git clone https://github.com/llvm/circt.git
cd circt && mkdir build && cd build
cmake -G Ninja .. \
  -DMLIR_DIR=$LLVM_BUILD/lib/cmake/mlir \
  -DLLVM_ENABLE_ASSERTIONS=ON \
  -DCMAKE_BUILD_TYPE=Release
ninja arcilator

# 2. SV → CIRCT HW IR → Arc → LLVM IR → 二进制
circt-verilog --ir-hw top.sv -o top.mlir
arcilator top.mlir --state-file=top.json | \
  opt -O3 --strip-debug -S | \
  llc -O3 --filetype=obj -o top.o
cc top.o -o top
./top
```

### Arcilator 使用流程（Chisel → FIRRTL）

```bash
# Chisel 生成 FIRRTL → CIRCT HW IR → Arcilator
firtool design.fir --ir-hw -o design.hw.mlir
arcilator design.hw.mlir --state-file=design.json | \
  opt -O3 | llc -O3 --filetype=obj -o design.o
cc design.o driver.cpp -o design_sim
./design_sim
```

### CIRCT 核心方言示例（Sum of Fibonacci）

```mlir
hw.module @sumoffibonacci(
  in %clock: !seq.clock,
  in %rst: i1,
  in %en: i1,
  out out: i32
) {
  %c0_i32 = hw.constant 0 : i32
  %c1_i32 = hw.constant 1 : i32
  %reg = seq.compreg %3, %clock reset %rst, %c0_i32 : i32
  %fib.out, %fib.count = hw.instance "fib" @fibonacci(
    clock: %clock: !seq.clock, rst: %rst: i1, en: %2: i1
  ) -> (out: i32, count: i32)
  %1 = comb.icmp ult %fib.count, %c12_i32 : i32
  %2 = comb.and %en, %1 : i1
  %3 = comb.mux %2, %fib.out, %reg : i32
  hw.output %3 : i32
}
```

## 原文摘录

> "Arcilator is a cycle-accurate hardware simulator in CIRCT that eliminates the need to export the design to Verilog and use a third-party OSS or proprietary simulator. It supports all frontend languages that are fully lowered to CIRCT's core representation, currently including Chisel and a subset of SystemVerilog."
> — LLVM Compiler Social Cambridge, 2024-12-04

> "Arcilator与Verilator最大的不同是前者将LLVM/MLIR中的软件开发方法应用于硬件设计中，即多层级中间表示的思想，其优势在于开发者可以在任何一层中间表示进行优化；而后者是直接将SystemVerilog代码转换为C++代码，没有中间表示的概念。"
> — 1nfinite.ai, 硬件仿真的两大范式

> "Arcilator的仿真速度比Verilator快4.3倍；即便是在对BOOM-large进行基准测试时，Arcilator仍然展现出优势，其速度是Verilator的1.9倍。此外，在仿真Rocket-small时，Arcilator生成的二进制文件大小比Verilator小4倍。"
> — 1nfinite.ai, 基于 LLVM 2023 Dev Meeting 数据

## 相关链接

- [CIRCT GitHub 仓库](https://github.com/llvm/circt)
- [Arcilator 论文/演讲 (LLVM 2023 Dev Meeting)](https://llvm.org/devmtg/2023-10/slides/techtalks/Erhart-Arcilator-FastAndCycleAccurateHardwareSimulationInCIRCT.pdf)
- [circt/arc-tests 基准测试仓库](https://github.com/circt/arc-tests)
- [CIRCT 官方文档](https://circt.llvm.org/)
- [Arcilator llhd.constant_time issue #9467](https://github.com/llvm/circt/issues/9467)
- [Arcilator async reset issue #10186](https://github.com/llvm/circt/issues/10186)
- [CIRCT 硬件仿真的两大范式 (中文)](https://1nfinite.ai/t/cycle-based-vs-event-driven/172)
- [Chisel 与 CIRCT 的无缝集成 (中文)](https://1nfinite.ai/t/chisel-circt/169)

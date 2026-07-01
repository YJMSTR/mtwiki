---
title: "cxxrtl / Yosys C++ Backend"
description: "Yosys 内置的 C++ 仿真后端，将 RTLIL 转换为可编译的 C++ 模型，支持黑盒、内省与 VCD 波形，是轻量级开源 RTL 仿真的重要选择"
source_url: "https://github.com/YosysHQ/yosys/tree/main/backends/cxxrtl"
source_type: "doc"
author: "whitequark (Catherine) / YosysHQ"
date: "2020-04"
tags: ["cxxrtl", "yosys", "c++-backend", "rtl-simulation", "open-source", "cycle-based"]
keywords: ["cxxrtl", "Yosys", "C++ simulation", "RTLIL", "write_cxxrtl", "blackbox", "introspection", "VCD"]
capture_date: "2025-06-30"
---

# cxxrtl / Yosys C++ Backend

## 来源

- URL: https://github.com/YosysHQ/yosys/tree/main/backends/cxxrtl
- 类型: 开源合成工具内置后端 / 技术博客 / 官方文档
- 作者: whitequark (Catherine) 主导开发，YosysHQ 维护
- 日期: 2020 年合并进 Yosys 主分支，持续迭代
- 主要参考:
  - Tom Verbeure 深度博客: *CXXRTL, a Yosys Simulation Backend* (2020-08-08)
  - Yosys DeepWiki 文档: *C++ Simulation* / *Backend Systems*
  - Yosys 官方 `help write_cxxrtl` 手册

## 摘要

CXXRTL 是 Yosys 开源综合工具链中内置的 C++ 仿真后端。它将 Yosys 内部的 RTLIL（Register Transfer Level Intermediate Language）表示转换为可直接编译的 C++ 模型，配合轻量级运行时头文件 `cxxrtl.h`，实现周期精确的 RTL 仿真。其设计哲学是**简洁优先**：整个后端仅约 4500 行代码，却提供了黑盒替换、VCD 波形、设计内省（introspection）、C API 等丰富功能。CXXRTL 自动受益于 Yosys 前端的改进——Verilog、VHDL（via ghdl-yosys-plugin）、SystemVerilog 等前端均可直通仿真。

## 关键要点

- **工作流**: 在 Yosys 中 `read_verilog` → `prep -top top` → `write_cxxrtl design.cc` → 用 C++ 编写 testbench → `g++` 编译 → 运行仿真。
- **核心设计**: 使用 C++ 模板类实现**统一位向量存储模型**（所有信号，无论 1 bit 还是 1024 bit，都用同一套模板处理），配合拓扑排序后的操作序列，生成每个模块一个 C++ class。
- **优化选项**: `-O0` / `-O1` / `-O2` / `-O3`（控制生成代码的优化程度）；`-Og` 保留更多调试信号但降低仿真速度；默认 `-O3` 追求最高性能。
- **黑盒（Blackbox）支持**: 可用 `cxxrtl_blackbox` 属性将设计中的任意模块替换为外部 C++ 行为模型。这对**硬件在环仿真**、**模型分发**、**CPU 行为级替换**（大幅提升非 CPU 相关测试的仿真速度）非常有价值。支持组合/同步端口属性（`cxxrtl_comb` / `cxxrtl_sync`），甚至能在黑盒内部维持组合反馈环。
- **设计内省（Introspection）**: 运行时可通过 `debug_items` 遍历整个设计层次，无需编译期知晓信号名。这是 VCD dumper、GUI 调试、检查点/恢复（checkpoint/restore）等功能的基础。
- **C API 与多语言绑定**: 除原生 C++ API 外，提供稳定的 C API（`cxxrtl_capi.h`），方便 Python（ctypes）、Rust 等语言绑定。已有社区项目如 `rust-cxxrtl`、`cxxrtl-vpi`（cocotb 驱动）、`pyhdlsim` 等。
- **性能数据（Tom Verbeure 基准测试）**:
  - 在 VexRiscv 小 CPU 跑 LED 闪烁程序的场景下，**CXXRTL 最快设置比单线程 Verilator 慢约 8 倍**；但比 Icarus Verilog 快数个数量级。
  - 其他用户报告的速度差距没有那么大，受 Verilog 编码风格与逻辑类型影响显著。
  - **编译时间**是 CXXRTL 的明显短板：由于重度依赖 C++ 模板，且输出单个扁平文件（无法并行编译），VexRiscv 模型在最高优化下编译需 **7 秒（clang9）** 对 Verilator **3.5 秒**；用 gcc10 甚至需 **32 秒**。大模型差距更悬殊。
  - 2025 年 ACM 论文（From RTL to CUDA）评价："CXXRTL suffers from extremely long compilation time on large designs and does not have any multi-threading capability."
- **局限**:
  - 仅支持可综合（synthesizable）子集，不处理 `$display` 等非综合语句（除非通过 `cxxrtl` 格式化系统间接支持）。
  - 不识别 `U`（未初始化）和 `X`（不定态），内部只有 0/1，对复位电路全迹线追踪需额外处理。
  - 无原生多线程支持；输出单文件导致 C++ 编译无法并行化。

## 对 RTL 仿真器多线程化的启示

1. **Yosys RTLIL → C++ 是多线程 RTL 仿真器的潜在中间表示**: 若 wiki-mt-rtl-optimizer 项目希望支持 Verilog/VHDL 输入，可复用 Yosys 前端将设计读入 RTLIL，再自行开发多线程 C++ 后端，而非从零写 Parser。CXXRTL 证明了 RTLIL 到 C++ 的可行性。
2. **单文件扁平输出的编译瓶颈**: CXXRTL 把所有逻辑 dump 到一个文件，导致 C++ 编译无法并行。多线程 RTL 仿真器若要支持 C++ 后端，应考虑**按分区生成多个独立编译单元**，让 `make -j` 发挥作用。
3. **模板 vs. 特化类型的权衡**: CXXRTL 的统一模板位向量模型牺牲了编译速度与部分运行性能，换取代码简洁。Verilator 则把信号降到最小适配的 C 类型（`char`、`uint32_t` 等）。在多线程场景下，**更紧凑的数据表示**不仅提升单线程性能，也降低线程间缓存行冲突。
4. **黑盒机制是混合粒度仿真的理想接口**: CXXRTL 的黑盒允许用 C++ 行为模型替换任意子模块。在多线程 RTL 仿真器中，可将某些子模块交给 GPU（如 GEM）或 FPGA（如 FireSim）作为黑盒，实现 CPU+GPU+FPGA 的异构加速。

## 原文摘录

> "CXXRTL is a new Yosys backend. It writes out the digital logic inside Yosys as a set of C++ classes, one for each remaining module, after performing whichever transformation pass you want to apply. In combination with cxxrtl.h, a single C++ include file with template classes that implement variable width bitvector arithmetic, the C++ classes become a simulation model of the digital design."
> — Tom Verbeure, 2020-08-08

> "In the fastest settings, CXXRTL is about 8x slower than single-threaded Verilator... But when speed is your first and foremost concern, CXXRTL is currently not for you."
> — Tom Verbeure, 基准测试

> "A CXXRTL model relies on C++ templates for all data types and operations... Templates are hard work for a C++ compiler. Compilation time is the price you pay. Furthermore, Verilator splits models into multiple C++ files that can be compiled in parallel. CXXRTL dumps out 1 flat file, so nothing about compiling the model can be done in parallel."
> — Tom Verbeure

> "CXXRTL is a high-performance simulation back-end for Yosys. It writes optimized C++ code that simulates the design. The generated code requires a driver program that instantiates the design, toggles its clock, and interacts with its ports. CXXRTL also supports replacing parts of the design with black boxes implemented in C++."
> — YosysHQ 官方介绍

> "CXXRTL suffers from extremely long compilation time on large designs and does not have any multi-threading capability."
> — From RTL to CUDA: A GPU Acceleration Flow for RTL Simulation with Batch Stimulus, ACM 2025

## 相关链接

- [Yosys 官方仓库 — CXXRTL 后端](https://github.com/YosysHQ/yosys/tree/main/backends/cxxrtl)
- [Tom Verbeure 深度博客](https://tomverbeure.github.io/2020/08/08/CXXRTL-the-New-Yosys-Simulation-Backend.html) — 最详尽的中文互联网外 CXXRTL 入门资料
- [cxxrtl_eval 实验项目](https://github.com/tomverbeure/cxxrtl_eval) — 含 blink_basic、blink_vcd、introspect 示例
- [Yosys DeepWiki — C++ Simulation](https://deepwiki.com/YosysHQ/yosys/7.1-c++-simulation)
- [cxxrtl-vpi (cocotb 驱动)](https://github.com/lanserge/cxxrtl-vpi)
- [rust-cxxrtl](https://github.com/NyanCAD/rust-cxxrtl)
- [pyhdlsim](https://github.com/michg/pyhdlsim)
- [whitequark 的 Yosys 初始 PR](https://github.com/YosysHQ/yosys/pull/2021) — 含设计哲学讨论

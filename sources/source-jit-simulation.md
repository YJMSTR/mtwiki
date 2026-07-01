---
title: "JIT Compilation in Simulators: From Instruction Set Simulation to RTL Emulation"
description: "搜集JIT编译技术在指令集仿真器与RTL仿真器中的应用，包括ArcSim LLVM后端、Khronos/ksim基于LLVM IR的周期精确仿真、LLVM ORCJIT/MCJIT引擎，以及OpenMP offloading JIT等技术的实现细节与性能数据。"
source_url: "https://groups.inf.ed.ac.uk/pasta/pub/projects/proposals/llvm-jit-backend-arcsim.pdf"
source_type: "paper"
author: "PASTA Project, University of Edinburgh"
date: "2009"
tags: ["JIT", "LLVM", "RTL-simulation", "instruction-set-simulator", "ArcSim", "ORCJIT", "MCJIT"]
keywords: ["just-in-time compilation", "LLVM backend", "simulator performance", "trace JIT", "hot block translation"]
capture_date: "2026-07-02"
---

# JIT Compilation in Simulators: 从指令集仿真到RTL模拟

## 来源

- **URL**: https://groups.inf.ed.ac.uk/pasta/pub/projects/proposals/llvm-jit-backend-arcsim.pdf
- **类型**: 学术论文 / 项目提案
- **作者**: PASTA Project, University of Edinburgh (Björn Franke, Nigel Topham)
- **日期**: 2009

## 摘要

指令集仿真器（ISS）和虚拟机广泛采用JIT（Just-In-Time）编译技术来提升运行时性能。本文档汇总了JIT编译在仿真器中的多条技术路线：

1. **ArcSim LLVM JIT后端**：爱丁堡大学PASTA项目为ARC指令集仿真器引入LLVM后端，用LLVM bitcode替代C代码作为中间表示，显著降低编译时间；
2. **Khronos/ksim**：北京大学开发的周期精确RTL仿真器，利用CIRCT将FIRRTL/MLIR下译至LLVM IR，再通过`llc`编译为机器码，实现AOT+JIT混合的RTL仿真；
3. **LLVM ORCJIT/MCJIT**：LLVM提供的两种JIT引擎，分别支持惰性编译与模块化替换，被广泛用于动态语言运行时与仿真器加速；
4. **OpenMP offloading JIT**：LLVM `-fopenmp-target-jit` 在设备端嵌入LLVM IR，运行时二次优化并编译为目标设备代码，展示了JIT在异构仿真中的潜力。

## 关键要点

### 1. ArcSim LLVM JIT Backend — 用LLVM Bitcode替代C作为IR

ArcSim是爱丁堡大学PASTA项目开发的面向ARC© ISA的高速ISS。其原有JIT引擎采用**C代码作为中间表示（IR）**，通过GCC在运行时编译为x86机器码。虽然可移植性好，但存在以下瓶颈：

- **词法分析、语法分析、语义检查**占据编译时间最大份额；
- **寄存器分配**（尤其是大型hot block）耗时显著；
- 其他优化遍（CSE、别名分析、SSA构造等）进一步拖慢编译。

**LLVM后端方案**：直接生成LLVM bitcode，跳过前端解析，利用LLVM的线性扫描寄存器分配（与Java HotSpot JIT相同算法）和丰富的优化遍，生成高效代码的同时大幅降低编译延迟。

| 指标 | C-as-IR + GCC | LLVM Bitcode + LLVM |
|------|--------------|---------------------|
| 前端解析开销 | 高（需词法/语法/语义分析） | 极低（直接生成bitcode） |
| 寄存器分配 | 图着色算法，慢 | 线性扫描，快 |
| 优化遍 | 依赖GCC选项 | LLVM Pass Pipeline，模块化 |
| 可移植性 | 高（C语言通用） | 中（LLVM IR跨平台但需LLVM运行时） |

### 2. Khronos / ksim — 基于CIRCT+LLVM IR的周期精确RTL仿真

**ksim**（Khronos）是北京大学开发的周期精确软件RTL仿真器，核心创新在于利用**时间数据局部性**（temporal data locality）在相邻周期间融合状态读写，降低主缓存与内存压力。

其编译管线（CIRCT → LLVM → 机器码）如下：

```bash
# Step 1: FIRRTL → MLIR HW dialect
firtool --ir-hw --disable-all-randomization $design.fir -o $design.mlir

# Step 2: MLIR → LLVM IR (ksim生成仿真器主体+头文件+驱动)
ksim $design.mlir -v -o $design.ll \
  --out-header=$design.h --out-driver=$design.cpp

# Step 3: LLVM IR → 目标机器码
llc --relocation-model=dynamic-no-pic -O2 -filetype=obj $design.ll -o $design.o

# Step 4: 链接测试平台与仿真器
clang++ -O2 $design.o $design.cpp -o $design
```

**性能启示**：ksim不是传统事件驱动仿真器，而是将RTL设计**编译为C++/LLVM IR再静态链接为可执行文件**，本质上属于AOT范畴，但其利用LLVM JIT生态（`llc` + `clang`）实现快速代码生成。该路线对RTL多线程仿真器的启示是：可将RTL模块编译为LLVM IR，通过JIT引擎在运行时按需加载、调度到不同线程执行。

### 3. LLVM ORCJIT vs MCJIT — 两代JIT引擎对比

LLVM提供两个JIT执行引擎，在仿真器/动态语言运行时中均有应用：

**MCJIT（Legacy）**：
- 一旦模块加入即**全量编译**为机器码；
- 调用 `finalizeObject()` 后返回可直接调用的原生代码指针；
- 缺乏模块化，无法单独卸载或重编译单个函数；
- 内部使用 `RuntimeDyld` + `RTDyldMemoryManager` 处理动态链接与内存管理。

**ORCJIT（Next-Generation）**：
- 支持**惰性编译**（lazy compilation），函数首次调用时才编译；
- 支持**运行时替换**与模块化卸载；
- 被 `lli`（LLVM IR解释器）默认采用（LLVM 18+）；
- 更适合需要频繁加载/卸载代码的仿真器场景。

```cpp
// MCJIT 典型使用流程（伪代码）
std::unique_ptr<ExecutionEngine> EE(
    EngineBuilder(std::move(Module))
        .setEngineKind(EngineKind::JIT)
        .create());
EE->finalizeObject();
void (*func)() = (void(*)())EE->getFunctionAddress("simulated_block");
func();
```

### 4. OpenMP Offloading JIT — 设备端运行时编译

LLVM从较新版本开始支持 `-fopenmp-target-jit`，将设备代码以LLVM IR形式嵌入目标文件，而非直接编译为目标设备二进制。运行时由 `libomptarget` 二次优化并JIT编译为实际设备代码：

```bash
# 编译时：嵌入LLVM IR
clang -fopenmp -fopenmp-target-jit foo.c -o foo

# 运行时：通过环境变量控制优化级别
LIBOMPTARGET_JIT_OPT_LEVEL=3 ./foo
```

这对RTL仿真器的启示：若仿真器需要面向多种目标架构（x86/ARM/RISC-V/GPU），可效仿此模式，将RTL仿真内核以LLVM IR形式分发，在目标机器上运行时JIT编译为最优本地代码，实现**一次编译、到处运行**的跨架构RTL仿真。

## 对 RTL 仿真器多线程化的启示

1. **JIT可弥补解释器开销**：传统事件驱动RTL仿真器（如Icarus Verilog）采用解释执行，单线程性能受限。引入JIT后，可将频繁执行的always块或组合逻辑编译为原生代码，获得数量级加速。

2. **LLVM IR作为跨平台RTL仿真IR**：LLVM IR本身即一种RISC-like指令集，与RTL级别的门/寄存器操作有天然映射关系。可将RTL模块lower为LLVM IR，再利用LLVM的优化遍（如DCE、CSE、循环展开）提升仿真效率。

3. **惰性编译支持多线程调度**：ORCJIT的惰性编译特性允许仿真器在运行时根据各线程负载动态加载、编译RTL模块的分片，避免启动时全量编译的巨大开销。

4. **性能数据参考**：
   - ArcSim C-as-IR方案：编译延迟高，但生成代码性能优异；
   - LLVM线性扫描寄存器分配：比图着色快一个数量级，代码质量接近；
   - ksim通过LLVM IR静态编译：在大型设计上可达事件驱动仿真器**100x+**的加速潜力。

## 原文摘录

> "The idea is to convert code compiled for some different architecture into native machine code at runtime to increase simulation speed. [...] By generating LLVM bitcode directly instead of C code, the time consumed by lexical analysis and parsing is drastically reduced. The LLVM IR resembles a RISC-like instruction set. Thus the mapping of ARC© RISC instructions onto LLVM RISC instructions should be straightforward."
> — PASTA Project, LLVM JIT Backend Proposal

> "Khronos is a cycle-accurate software RTL simulation tool that exploits the temporal data (hardware state) locality between consecutive cycles. By adjust the simulation order and re-schedule the simulation, Khronos can reducing the memory access and accelerate RTL simulation."
> — ksim README

> "QEMU's dynamic translation backend is called TCG, for 'Tiny Code Generator'. [...] The basic idea is to split every target instruction into a couple of RISC-like TCG ops. Some optimizations can be performed at this stage, including liveness analysis and trivial constant expression evaluation."
> — QEMU Internals

## 相关链接

- [ArcSim LLVM JIT Backend Proposal](https://groups.inf.ed.ac.uk/pasta/pub/projects/proposals/llvm-jit-backend-arcsim.pdf)
- [ksim (Khronos) GitHub](https://github.com/pku-liang/ksim)
- [LLVM ORCJIT Documentation](https://llvm.org/docs/ORCv2.html)
- [LLVM MCJIT Design and Implementation](https://llvm.org/docs/MCJITDesignAndImplementation.html)
- [OpenMP Target JIT](https://openmp.llvm.org/CommandLineArgumentReference.html)
- [QEMU TCG Internals](https://www.qemu.org/docs/master/devel/tcg.html)
- [IRvana: LLVM IR JIT Execution Framework](https://github.com/m3rcer/IRvana)

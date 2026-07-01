---
title: "JIT/AOT编译与代码生成"
description: "系统梳理RTL仿真器中的JIT（Just-In-Time）与AOT（Ahead-of-Time）编译技术路线，涵盖ArcSim LLVM JIT、ksim CIRCT→LLVM IR、ORCJIT vs MCJIT、Verilator静态编译、二进制翻译（QEMU TCG、RISC-V 20MIPS）以及MLIR/CIRCT优化管线。提供架构决策矩阵与可操作的编译器前端选型建议。"
references:
  - source-jit-simulation
  - source-llvm-mlir-rtl
  - source-aot-binary-translation
tags: ["JIT", "AOT", "LLVM", "CIRCT", "MLIR", "Verilator", "QEMU", "TCG", "binary-translation", "compiler-pipeline"]
last_updated: "2026-07-02"
---

# JIT/AOT编译与代码生成

> **核心结论 upfront**：AOT 是单线程 RTL 仿真的终极优化（用编译时间换运行时间），JIT 适合快速迭代和调试，二进制翻译是 FPGA/EMU 的替代中间路径。对于自研多线程 RTL 仿真器，推荐以 **CIRCT + LLVM 作为前端编译管线**，原生支持 JIT/AOT 双模式。

---

## 1. JIT 编译：从指令集仿真到 RTL 周期精确模拟

### 1.1 ArcSim LLVM JIT — 用 LLVM Bitcode 替代 C-as-IR

爱丁堡大学 PASTA 项目为 ARC ISA 仿真器 ArcSim 引入 LLVM 后端，核心思路是将原有「C 代码作为中间表示（IR）→ GCC 运行时编译」的管线，替换为「直接生成 LLVM Bitcode → LLVM JIT 编译」。

| 指标 | C-as-IR + GCC | LLVM Bitcode + LLVM |
|------|---------------|---------------------|
| 前端解析开销 | **高**（词法/语法/语义分析全走一遍） | **极低**（直接生成 bitcode，跳过前端） |
| 寄存器分配 | 图着色算法，慢 | 线性扫描（与 Java HotSpot JIT 同算法），快一个数量级 |
| 优化遍 | 依赖 GCC 选项，模块化差 | LLVM Pass Pipeline，按需组合 |
| 可移植性 | 高（C 语言通用） | 中（LLVM IR 跨平台，但需 LLVM 运行时） |
| 编译延迟 | 高 | 显著降低（省去前端解析） |

**对 RTL 仿真器的启示**：LLVM IR 本身是一种 RISC-like 指令集，与 RTL 级别的门/寄存器操作有天然映射。将 RTL 模块 lower 为 LLVM IR 后，可直接复用 LLVM 的线性扫描寄存器分配、DCE、CSE 等优化遍，无需自研编译器后端。

### 1.2 ksim (Khronos) — CIRCT → LLVM IR 的周期精确 RTL 仿真

ksim（北京大学）利用 **CIRCT 将 FIRRTL/MLIR 下译至 LLVM IR**，再通过 `llc` 编译为机器码，实现 AOT + JIT 混合的 RTL 仿真。

**编译管线**：

```
┌─────────────────┐    ┌──────────────────┐    ┌──────────────┐    ┌──────────────┐
│  FIRRTL 设计     │ → │  firtool         │ → │  ksim        │ → │  llc + clang │
│  (.fir)          │    │  --ir-hw         │    │  MLIR → LLVM IR │    │  -O2 → 机器码 │
└─────────────────┘    └──────────────────┘    └──────────────┘    └──────────────┘
         │                                               │
         ▼                                               ▼
   FIRRTL dialect                                  LLVM IR (.ll)
   (Chisel 编译器 IR)                               + C++ 头文件/驱动
```

```bash
# Step 1: FIRRTL → MLIR HW dialect
firtool --ir-hw --disable-all-randomization $design.fir -o $design.mlir

# Step 2: MLIR → LLVM IR (ksim 生成仿真器主体 + 头文件 + 驱动)
ksim $design.mlir -v -o $design.ll \
  --out-header=$design.h --out-driver=$design.cpp

# Step 3: LLVM IR → 目标机器码
llc --relocation-model=dynamic-no-pic -O2 -filetype=obj $design.ll -o $design.o

# Step 4: 链接测试平台与仿真器
clang++ -O2 $design.o $design.cpp -o $design
```

**性能数据**：ksim 在单线程上可达 **42.66 kHz**，对比 Icarus Verilog 的 **1.49 kHz**（约 **28.6x 加速**）。其本质不是事件驱动仿真器，而是将 RTL 设计 **编译为 C++/LLVM IR 再静态链接为可执行文件**——属于 AOT 范畴，但借助 LLVM JIT 生态实现快速代码生成。

### 1.3 LLVM ORCJIT vs MCJIT — 两代 JIT 引擎的选型

| 特性 | MCJIT（Legacy） | ORCJIT（Next-Gen） |
|------|----------------|-------------------|
| 编译策略 | 模块加入即**全量编译** | 支持**惰性编译**（lazy compilation） |
| 运行时替换 | ❌ 不支持 | ✅ 支持模块化卸载与重编译 |
| 内存管理 | RuntimeDyld + RTDyldMemoryManager | 更灵活的 JITLink / ORC runtime |
| 适用场景 | 一次性加载的仿真器 | 需频繁加载/卸载模块的仿真器 |
| 默认使用 | LLVM 早期版本 | `lli`（LLVM IR 解释器）LLVM 18+ |

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

**对 RTL 仿真器的启示**：ORCJIT 的惰性编译特性允许仿真器在运行时根据各线程负载**动态加载、编译 RTL 模块的分片**，避免启动时全量编译的巨大开销。若 RTL 设计需面向多种目标架构（x86/ARM/RISC-V/GPU），可将仿真内核以 LLVM IR 形式分发，运行时 JIT 编译为最优本地代码，实现「一次编译、到处运行」。

---

## 2. AOT 编译：静态编译与二进制翻译

### 2.1 Verilator — AOT 静态编译的标杆

Verilator 是开源 RTL 仿真器的性能之王，本质是将 Verilog/SystemVerilog **AOT 编译为高度优化的 C++/SystemC 模型**。

**编译管线**：

```
Verilog RTL (.v) ──→ Verilator (RTL → C++) ──→ make (C++ 编译) ──→ 原生可执行仿真器
     │                      │                         │
     ▼                      ▼                         ▼
  lint 检查            层次扁平化               常量传播 + DCE
  --lint-only          时序逻辑转换             多线程分区 (--threads)
```

```bash
# Step 1: Lint 检查
verilator --lint-only -Wall design.v

# Step 2: Verilate (RTL → C++)
verilator -Wall --cc design.v --exe testbench.cpp

# Step 3: 编译 C++ 模型
make -C obj_dir -f Vdesign.mk

# Step 4: 运行仿真
./obj_dir/Vdesign
```

**核心优化技术**：

| 优化 | 说明 | 效果 |
|------|------|------|
| 层次扁平化 | 将所有模块实例合并到顶层 C++ 类，消除模块调用开销 | 减少虚函数/间接调用 |
| 常量传播 | 编译期计算所有可静态确定的值 | 大量逻辑在编译期消失 |
| 死代码消除 | 移除不影响输出的逻辑 | 显著减少仿真计算量 |
| 时序逻辑转换 | 将 `always @(posedge clk)` 转换为状态机/寄存器更新 | 便于 C++ 高效实现 |
| 多线程分区 | `--threads` 将设计划分为多个线程 | 额外 2–10x 加速 |

**性能对比**：

| 仿真器 | 类型 | 单线程性能 | 相对速度 |
|--------|------|-----------|---------|
| Icarus Verilog | 解释执行 | 1.49 kHz | 1x (baseline) |
| Verilator | AOT 编译 C++ | 42.66 kHz | **~29x** |
| Verilator + 多线程 | AOT + 分区 | 可达 200–1000x | **200–1000x** |

### 2.2 Verilator AOT 的代价：编译时间 vs 运行时间的残酷权衡

Verilator 的 AOT 模式并非免费午餐。对于大型设计（如 ARM 互联），多线程编译代价极为惊人：

| 设计规模 | 编译时间 | 内存峰值 | 来源 |
|---------|---------|---------|------|
| 小型设计 | 分钟级 | < 10 GiB | Verilator 官方 |
| 大型 SoC（ARM 互联） | **~8 小时** | **1043 GiB** | Parendi 论文 |

- **变量排序遍（V3VariableOrder）**近似 TSP 优化，虽可提升运行时性能 30%，但编译成本极高；
- **Parendi（IPU 千核并行）**可将大型设计编译时间从 8 小时降至 40 分钟，比 32 线程 Verilator 快 **2.8–4.0x**。

**关键洞察**：AOT 是「编译时间换运行时间」的终极形态。对于需要运行数万周期以上的稳态仿真，数小时的编译时间完全值得；但对于仅跑几百周期的单元测试，AOT 的编译开销将吞噬全部收益。

### 2.3 二进制翻译：QEMU TCG 与 RISC-V 20 MIPS

#### QEMU TCG — 动态二进制翻译引擎

QEMU 的 Tiny Code Generator（TCG）将目标架构指令拆分为 **RISC-like 微操作（TCG ops）**，再由后端编译为主机代码。

**TCG 编译管线**：

```
Guest Binary (x86/ARM/RISC-V) ──→ 目标前端（指令解码）
         │
         ▼
  TCG IR（微操作序列）
         │
         ▼
  优化（活性分析、常量折叠）
         │
         ▼
  Host Backend (x86/ARM) ──→ Translation Block (TB) 缓存
```

| 机制 | 说明 | 对 RTL 仿真的启示 |
|------|------|------------------|
| **Translation Block (TB)** | 以跳转/分支为边界的基本块，TCG 翻译的最小单位 | RTL 可将 always 块或组合逻辑块视为 TB，惰性翻译 |
| **Direct Block Chaining** | 直接跳转时无需返回主循环，通过 patch 跳转指令实现零开销链接 | 多线程 RTL 中可跨线程链式调度独立的逻辑块 |
| **CPU State 编码** | 将特权级、段基址等状态编码到 TB key 中 | RTL 可将时钟相位、复位状态编码为 TB 上下文，减少分支 |
| **自修改代码处理** | 写保护翻译代码页，触发 SIGSEGV 后使相关 TB 失效 | 支持配置寄存器动态修改时，可复用该机制使缓存失效 |

**性能数据**：
- 用户态仿真：可达原生速度的 **30%–70%**；
- 系统态仿真：因软件 MMU 和异常处理，降至 **10%–30%**；
- 单线程 TCG 在 ARM Cortex-A9 上运行 RISC-V 32I 时，因翻译开销满载一个核心。

#### 多核 RISC-V 二进制翻译仿真器 — 精度与速度的平衡

2020 年论文提出了一种**多功能仿真器**，在功能模式与时序模式间动态切换：

| 模式 | 速度 | 精度 | 适用场景 |
|------|------|------|---------|
| 功能模式 | 超越 QEMU | 无周期信息 | 快速启动、长时间运行 |
| 时序模式 | **20 MIPS** | 周期级 | RISC-V 多核系统仿真 |
| 详细周期模型 | 0.1–1 MIPS | 全信号级 | gem5 等 |

该速度比详细周期模型快近 **100 倍**，为 RTL 多线程仿真器提供了**中间精度**的可行路线：**先用二进制翻译快速热身，再对关键模块切入周期精确模式**。

---

## 3. MLIR/CIRCT 优化管线：从 FIRRTL 到 Verilog

### 3.1 CIRCT 多级 Lowering Pipeline

CIRCT（Circuit IR Compilers and Tools）是 LLVM 生态中专为硬件设计的编译基础设施，基于 MLIR 构建。其核心方言按抽象层级排列：

```
┌─────────────────────────────────────────────────────────────────┐
│  High-Level:  Handshake, HIR, Affine, Calyx                      │  ← 高层综合入口
├─────────────────────────────────────────────────────────────────┤
│  Mid-Level:   FIRRTL → HW/Comb/Seq                               │  ← RTL 级核心表示
├─────────────────────────────────────────────────────────────────┤
│  Low-Level:   LLHD (仿真) / SV (SystemVerilog 生成)              │  ← 后端代码生成
├─────────────────────────────────────────────────────────────────┤
│  Target:      Verilog / SystemVerilog / LLVM IR                  │  ← 输出到 EDA 或仿真器
└─────────────────────────────────────────────────────────────────┘
```

| Dialect | 作用 | 关键操作 | 优化机会 |
|---------|------|----------|---------|
| **FIRRTL** | Chisel 编译器的 IR，描述带类型参数的硬件模块 | `firrtl.module`, `firrtl.connect` | 宽度推断、常量传播 |
| **HW** | 通用硬件结构：模块、端口、实例化 | `hw.module`, `hw.instance`, `hw.output` | 模块内联、端口剪枝 |
| **Comb** | 组合逻辑操作 | `comb.add`, `comb.and`, `comb.mux` | 常量折叠、CSE、代数化简 |
| **Seq** | 时序逻辑（寄存器、时钟、复位） | `seq.firreg`, `seq.compreg` | 寄存器重定时、冗余寄存器消除 |
| **LLHD** | 低层硬件描述，支持时间类型与 9 值逻辑 | `llhd.entity`, `llhd.sig`, `llhd.drv` | 时间类型优化、信号驱动合并 |
| **SV** | SystemVerilog 语法导出 | `sv.always`, `sv.ifdef` | 可读性优化、条件编译处理 |

### 3.2 IR 级优化遍

**常量折叠（Constant Folding, CF）**：
- `comb.and(x, 0) → 0`，`comb.and(x, -1) → x`
- 在编译期直接计算常量输入的组合逻辑结果。

**死代码消除（Dead Code Elimination, DCE）**：
- 移除未被任何输出或端口驱动的内部逻辑；
- 对大型 SoC 设计尤为重要，可显著减少仿真时的计算量。

**公共子表达式消除（Common Subexpression Elimination, CSE）**：

```mlir
// 优化前：两个相同的加法
%0 = comb.add %a, %b : i32
%1 = comb.add %a, %b : i32
%2 = comb.and %0, %1 : i32

// 优化后（CSE）：合并为一个加法
%0 = comb.add %a, %b : i32
%1 = comb.and %0, %0 : i32
```

### 3.3 PipeRTL：IR 级流水线时序优化

PipeRTL（2026 年论文）在 CIRCT 的 HW/Comb/Seq 方言层级上进行**时序感知的流水线优化**，避免传统 HLS 工具在高层 C/C++ 处做调度的盲目性。

- **核心机制**：利用 CIRCT 的结构保留特性，在 lowering 到 Verilog 之前插入流水线专用语义；通过寄存器重定位（register relocation）平衡关键路径；
- **与现有遍组合**：PipeRTL 可与 CIRCT 的 DCE、CSE 组合使用，形成完整优化流水线；
- **性能**：在 IIR 滤波器等多个基准电路上，可减少寄存器数量，同时满足时序约束。

**对 RTL 仿真器的启示**：不必等待后端 EDA 工具做布局布线后的时序分析，可在 CIRCT 中提前做流水线调度，为多线程 RTL 仿真提供**更均衡的负载划分**。

---

## 4. 对 RTL 仿真器的五大启示

1. **AOT 是单线程的终极优化（编译时间换运行时间）**
   - Verilator 证明：投入数小时编译大型设计，可将运行速度提升 2–3 个数量级；
   - 对于需要运行数万周期以上的回归测试，AOT 的编译开销完全值得。

2. **JIT 适合快速迭代和调试**
   - ORCJIT 的惰性编译允许仿真器在运行时按需加载、编译 RTL 模块分片；
   - 对于仅跑几百周期的单元测试或交互式调试，JIT 避免了 AOT 的漫长编译等待。

3. **多线程 AOT 编译器可能并行化编译阶段**
   - Parendi 在 IPU 上实现千核并行编译，将大型设计编译时间从 8 小时降至 40 分钟；
   - RTL 多线程仿真器应支持**增量编译**（仅重新编译修改过的模块）与**分布式编译**。

4. **二进制翻译是 FPGA/EMU 的替代路径**
   - QEMU TCG 式的二进制翻译可在功能仿真（快）与时序仿真（精确）间动态切换；
   - 对于缺乏 FPGA 硬件的场景，二进制翻译提供了「中间精度」的可行路线；
   - FERIVer 框架展示了 FPGA + QEMU 混合架构的验证潜力。

5. **IR 级优化先于线程划分**
   - 在多线程 RTL 仿真之前，先在 MLIR/CIRCT 层级运行 DCE、CSE、常量折叠；
   - 可减少每个线程需要执行的冗余计算，提升并行效率；
   - LLVM 的 `loop-vectorize` 和 `slp-vectorizer` 可对位宽运算进行向量化，适合现代 CPU 的 SIMD 单元。

---

## 5. 架构决策：解释器 vs JIT vs AOT vs 二进制翻译

| 维度 | 解释器（Icarus） | JIT（ORCJIT/ksim） | AOT（Verilator） | 二进制翻译（QEMU TCG） |
|------|----------------|-------------------|------------------|----------------------|
| **编译延迟** | 无 | 中（惰性编译） | 高（数小时/大型设计） | 低（运行时翻译） |
| **运行速度** | 1x (baseline) | 10–50x | 100–1000x | 10–100x（功能模式） |
| **调试能力** | 优秀（随时中断） | 良好（可映射回源码） | 差（已优化） | 中等 |
| **代码变更响应** | 即时 | 较快（增量编译） | 慢（全量重编译） | 即时（TB 缓存失效） |
| **多线程友好** | 差 | 良好（ORCJIT 模块化） | 优秀（Verilator --threads） | 中等（单线程 TCG） |
| **跨架构支持** | 无关 | 优秀（LLVM IR 跨平台） | 需重新编译 | 优秀（原生设计） |
| **内存占用** | 低 | 中 | 高（编译期峰值） | 中（TB 缓存） |
| **典型场景** | 单元测试、调试 | 交互式仿真、快速迭代 | 回归测试、长时间仿真 | 系统级仿真、混合精度 |

**决策树**：

```
                    开始
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
   设计是否频繁变更？         是否需运行 > 10K 周期？
   │                         │
   ├─ 是 → JIT 模式          ├─ 是 → AOT 模式
   │   (快速迭代)             │   (编译时间换运行时间)
   │                         │
   └─ 否 → 继续              └─ 否 → 继续
         │                         │
         ▼                         ▼
   是否需要跨架构？          是否需要混合精度？
   │                         │
   ├─ 是 → LLVM IR + JIT    ├─ 是 → 二进制翻译
   │   (一次编译到处运行)     │   (QEMU TCG 模式切换)
   │                         │
   └─ 否 → 解释器            └─ 否 → 纯 AOT
         (简单调试)                 (Verilator)
```

---

## 6. 可操作的建议：CIRCT + LLVM 作为前端编译管线

基于以上分析，为自研多线程 RTL 仿真器提出以下可落地的编译器前端方案：

### 6.1 推荐架构：双模式编译管线

```
                    ┌────────────────────────────────────────┐
                    │         RTL 设计输入（Verilog/SV）        │
                    └────────────────────────────────────────┘
                                       │
                                       ▼
                    ┌────────────────────────────────────────┐
                    │  CIRCT 前端：moore / firtool → LLHD / FIRRTL │
                    │  (解析 + 类型检查 + 高层优化)              │
                    └────────────────────────────────────────┘
                                       │
                      ┌────────────────┼────────────────┐
                      ▼                ▼                ▼
              ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
              │   AOT 路径     │ │   JIT 路径     │ │  混合路径      │
              │              │ │              │ │              │
              │ HW/Comb/Seq  │ │ HW/Comb/Seq  │ │  HW/Comb/Seq │
              │ ↓            │ │ ↓            │ │  ↓           │
              │ LLVM IR      │ │ LLVM IR      │ │  LLVM IR     │
              │ (llc -O3)    │ │ (ORCJIT)     │ │  (缓存 +     │
              │ ↓            │ │ ↓            │ │   增量编译)  │
              │ C++ 模型     │ │ 原生机器码    │ │              │
              │ (Verilator式)│ │ (运行时加载)  │ │  运行时决定   │
              │              │ │              │ │  AOT or JIT  │
              └──────────────┘ └──────────────┘ └──────────────┘
```

### 6.2 具体行动项

| 优先级 | 行动项 | 技术栈 | 预期收益 |
|--------|--------|--------|---------|
| **P0** | 以 CIRCT 作为 RTL 解析与 IR  lowering 前端 | CIRCT (`moore`, `firtool`), MLIR | 复用成熟基础设施，避免自研 parser |
| **P0** | 在 MLIR 层级运行 DCE + CSE + 常量折叠 | MLIR Pass Pipeline | 减少冗余计算，为后续多线程铺路 |
| **P1** | 实现 FIRRTL → HW/Comb/Seq → LLVM IR 的 lowering | CIRCT + LLVM | 打通到 LLVM 后端的完整链路 |
| **P1** | 基于 ORCJIT 实现仿真内核的惰性加载 | LLVM ORCJIT v2 | 支持快速迭代与调试模式 |
| **P2** | 对稳态仿真启用 AOT 模式（`llc -O3` + LTO） | LLVM `llc`, `lld` | 100x+ 加速，对标 Verilator |
| **P2** | 实现增量编译：仅重新编译修改过的模块 | MLIR 模块化设计 | 大型 SoC 迭代编译从小时降至分钟 |
| **P3** | 探索二进制翻译作为 FPGA 的替代验证路径 | QEMU TCG 参考实现 | 为无硬件环境提供中等精度仿真 |
| **P3** | 引入 PipeRTL 时序优化，平衡多线程负载 | CIRCT + PipeRTL pass | 更均衡的线程间负载分配 |

### 6.3 关键设计原则

1. **编译器管线是仿真器的性能天花板**：再优秀的并行调度算法，也无法弥补低质量代码生成带来的开销。先把 LLVM/CIRCT 的优化管线跑满，再谈多线程并行。
2. **JIT 与 AOT 不是互斥的**：仿真器应同时支持两种模式——日常开发用 JIT（快速启动），回归测试用 AOT（极限性能）。
3. **IR 级优化 > 线程级优化**：在 HW/Comb/Seq 方言层级消除冗余计算，比在线程间通信协议上做优化更具性价比。
4. **编译时间也是用户体验的一部分**：参考 Parendi 的分布式编译思路，大型设计的 AOT 编译不应阻塞开发者。

---

## 性能数据汇总

| 技术/工具 | 类型 | 速度 | 精度 | 关键代价 |
|-----------|------|------|------|---------|
| Icarus Verilog | 解释器 | 1.49 kHz | 信号级 | 无编译延迟，速度慢 |
| ksim (LLVM IR) | AOT | 42.66 kHz | 周期精确 | 需完整编译链路 |
| Verilator (单线程) | AOT | ~29x Icarus | 信号级 | 编译时间随设计规模增长 |
| Verilator (多线程) | AOT | 200–1000x | 信号级 | 大型设计编译 8h / 1043 GiB |
| QEMU TCG | 动态二进制翻译 | 原生 10%–70% | 功能级 | 单线程翻译瓶颈 |
| RISC-V 混合仿真器 | 二进制翻译 | 20 MIPS | 周期级 | 模式切换开销 |
| ArcSim LLVM JIT | JIT | 优于 C-as-IR | 指令级 | 需 LLVM 运行时 |

---

## 参考来源

- [ArcSim LLVM JIT Backend Proposal](https://groups.inf.ed.ac.uk/pasta/pub/projects/proposals/llvm-jit-backend-arcsim.pdf) — PASTA Project, University of Edinburgh, 2009
- [ksim (Khronos) GitHub](https://github.com/pku-liang/ksim) — 北京大学, 周期精确 RTL 仿真器
- [LLVM ORCJIT Documentation](https://llvm.org/docs/ORCv2.html) — LLVM Project
- [Verilator 官方文档](https://www.veripool.org/verilator/) — Veripool
- [QEMU TCG Internals](https://www.qemu.org/docs/master/devel/tcg.html) — QEMU Project
- [Accelerate Multi-Core RISC-V with Binary Translation](https://arxiv.org/abs/2005.11357) — Xuan Guo et al., 2020
- [Parendi: Thousand-Way Parallel RTL Simulation](https://arxiv.org/html/2403.04714v1) — IPU 千核并行 RTL 仿真
- [PipeRTL: Timing-Aware Pipeline Optimization](https://arxiv.org/html/2605.01836v1) — IR 级流水线优化
- [CIRCT 官方文档](https://circt.llvm.org/) — LLVM 子项目
- [FERIVer: FPGA-assisted RTL Verification](https://arxiv.org/html/2504.05284v1) — FPGA + QEMU 混合验证

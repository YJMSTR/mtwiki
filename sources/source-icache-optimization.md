---
title: Instruction Cache Optimization for RTL Simulators
description: 指令缓存优化在 RTL 仿真器中的应用，包括 PGO/BOLT、函数内联权衡、代码段压缩、代码布局优化
source_url: "https://engineering.fb.com/2018/06/19/data-infrastructure/accelerate-large-scale-applications-with-bolt/"
source_type: "blog"
author: "Facebook Engineering / Rafael Auler"
date: "2018-06-19"
tags: [icache, pgo, bolt, code-layout, rtl-simulator, verilator, essent, binary-optimization]
keywords: [instruction cache, I-cache, PGO, BOLT, profile-guided optimization, code layout, function inlining, code size, RTL simulation, Verilator, frontend-bound]
capture_date: "2026-07-01"
---

# 指令缓存优化在 RTL 仿真器中的应用

## 来源

- URL: <https://engineering.fb.com/2018/06/19/data-infrastructure/accelerate-large-scale-applications-with-bolt/>
  - 类型: blog
  - 作者: Facebook Engineering (Rafael Auler)
  - 日期: 2018-06-19
- URL: <https://arxiv.org/abs/2601.18140>
  - 类型: paper
  - 作者: Yan Zhu et al., TAC-UCB
  - 日期: 2026-01-26
- URL: <https://arxiv.org/abs/2403.04714>
  - 类型: paper
  - 作者: Parendi Team
  - 日期: 2024-03
- URL: <https://arxiv.org/abs/2408.12592>
  - 类型: paper
  - 作者: Skeia / Shadow Branches Team
  - 日期: 2024-08
- URL: <https://arxiv.org/pdf/1809.04676v1>
  - 类型: paper
  - 作者: Sergey Pupyrev, Facebook
  - 日期: 2018
- URL: <https://github.com/verilator/verilator/blob/master/docs/guide/simulating.rst>
  - 类型: doc
  - 作者: Verilator Project
  - 日期: 持续更新

## 摘要

本文综合搜集了指令缓存（I-cache）优化在 RTL 仿真器（尤其是 Verilator 及其同类编译型仿真器）中的应用资料。核心发现包括：

1. **Verilator 官方文档明确指出**："instruction cache size often limits large models"（指令缓存大小经常限制大型模型的性能），并建议通过减小代码体积（code size）来缓解。

2. **RTeAAL Sim** 对 Verilator 和 ESSENT 的 top-down 分析显示：Verilator 的 L1 I-cache MPKI 高达 80–120，ESSENT 通过将 RTL 数据流图完全展开为直线代码（straight-line code）将 MPKI 降至 64–70，但仍存在显著的前端压力。

3. **Facebook BOLT** 是一种二进制级优化工具，通过重排函数和基本块、剥离对齐 NOP、进行相同代码折叠（ICF）等手段，将大型数据中心应用的 CPU 时间减少 2%–15%。它已在 Verilator 上进行了验证应用（"verilator-bolted"）。

4. **Parendi**（千核并行 RTL 仿真器）指出，在 x86 上 aggressive inline 会急剧增加代码大小和 I-cache 压力；但在 IPU（无 I-cache，仅有 624 KiB 本地内存）上则可以放心内联。这揭示了 I-cache 容量对内联策略的直接影响。

5. **PGO/FDO**（Profile-Guided Optimization / Feedback-Directed Optimization）和基本块重排序算法是改善 I-cache 利用率和分支预测器效率的核心技术，在实际应用（如 HHVM、Clang）中可带来 5%–15% 的加速。

## 关键要点

- **RTL 仿真器的前端瓶颈是根本性的**：Verilator 和 ESSENT 都将 RTL 数据流图编译为 C++ 后再编译为可执行文件。由于每个电路节点被展开为独立的指令序列，代码复用率极低，导致 I-cache  miss 严重。Verilator 的 I-cache MPKI 高达 80–120，意味着每千条指令就有 80–120 次 L1 指令缓存未命中。

- **ESSENT 的直线代码策略**：ESSENT 将 RTL 数据流图完全展开为直线代码（straight-line code），消除了分支开销，改善了 I-cache 预取，并使得编译器优化更激进。代价是代码体积急剧膨胀，编译时间和内存消耗显著增加。

- **RTeAAL Sim 的张量代数方法**：通过将仿真表示为稀疏张量代数核，二进制体积从数百 MB 降至几十 KB，同时保持了代码复用（循环执行），从根本上缓解了 I-cache 压力。这代表了从"编译电路到指令"到"编译电路到数据结构+通用核"的范式转移。

- **BOLT 的二进制级优化**：BOLT 在链接后阶段工作，直接操作二进制文件。其优化包括：
  - 基于执行 profile 重排函数和基本块（reorder-blocks=cache+, reorder-functions=hfsort+）
  - 函数体拆分（split-functions=3, split-all-cold），将热代码与冷代码分离
  - 相同代码折叠（ICF=1），减少代码体积
  - 剥离对齐 NOP 和 AMD 友好的 REPZ 字节
  - 修复 macro-fusion 边界问题（避免指令对在 64 字节缓存线边界处断开）
  - 基础内联（处理编译器遗漏的 assembly 代码等）

- **Parendi 的 inline 权衡**：在 RTL 仿真中，几乎每条指令每 RTL cycle 只执行一次，因此函数调用的开销比例很高。但 aggressive inline 在 x86 上会导致 I-cache 压力剧增，因为代码体积膨胀。Parendi 在 IPU（无 I-cache，200 KiB 本地指令内存）上可以放心 aggressive inline，但在 x86 多线程 RTL 仿真中必须谨慎权衡。

- **PGO 的编译期优化**：PGO 在编译阶段利用运行时 profile 数据指导：热函数内联、冷函数外置、代码布局重排、间接调用去虚拟化。典型加速 5%–15%，在大型代码库（如 Chromium、Firefox、Clang）中已成为标准做法。

- **Shadow Branches 的启示**：在现代处理器的前端设计中，BTB（Branch Target Buffer）miss 会导致 FDIP（Fetch-Directed Instruction Prefetching）无法正确预取指令。对 Verilator 这类大型代码库应用 BOLT 后，虽然 I-cache MPKI 降低，但 BTB 压力仍可通过前端结构优化进一步改善。

## 对 RTL 仿真器多线程化的启示

1. **I-cache 是多线程 RTL 仿真的首要瓶颈**：在多线程场景下，多个线程共享同一 L2/L3 缓存和内存带宽。如果每个线程的 I-cache working set 过大，不仅自身 L1 I-cache 频繁 miss，还会相互驱逐 L2/L3 中的指令行，导致整体性能崩塌。Verilator 文档明确建议对大型模型使用 `-Os` 编译选项减小代码体积。

2. **多线程编译模型中冷热代码分离**：Parendi 和 BOLT 的 split-functions 策略可以直接迁移到 RTL 仿真器。将每个 cycle 必执行的"热路径"（组合逻辑求值、寄存器更新）紧凑地排布在相邻内存区域，将初始化、调试、报错等"冷路径"移到远离热路径的段中，可以显著减少 I-cache 冲突和容量 miss。

3. **PGO + BOLT 对 RTL 仿真器的适用性**：RTL 仿真器的工作负载具有高度规律性（每 cycle 执行相同的求值循环），非常适合收集稳定的 profile 数据。对 Verilator 生成的 C++ 代码使用 `clang -fprofile-generate` → 运行典型 benchmark → `clang -fprofile-use` + LTO → BOLT 后处理，是一条成熟的优化路径。已有研究（Exposing Shadow Branches）明确验证了对 Verilator 应用 BOLT 的有效性。

4. **代码体积 vs IPC 的权衡**：多线程 RTL 仿真中，每个线程的指令流不重叠，因此代码体积膨胀的代价被放大。ESSENT 的直线代码策略虽然降低了分支数，但大幅增加了代码体积，在多线程 x86 上可能适得其反。需要研究一种折中：将频繁重复的子图（如多位加法器、多路选择器）保留为函数调用，而非全部 inline。

5. **OPT_FAST 与 OPT_SLOW 的双轨编译**：Verilator 的 `verilated.mk` 已支持 `OPT_FAST`（热路径，`-O3`）和 `OPT_SLOW`（冷路径，`-Os`）分离。多线程 RTL 仿真器应进一步扩展此机制：对单 cycle 求值核使用极致优化但控制代码体积，对测试平台、VCD 转储、断言检查使用 `-Os` 甚至 `-O0`。

6. **宏观融合（Macro-fusion）对齐**：BOLT 发现的 bzip2 案例中，1 字节的指令流偏移导致 macro-fusion 对断裂，产生 5% 性能回退。RTL 仿真器生成的 C++ 代码经过编译器优化后，热循环中的比较+跳转对（如 `cmp` + `je`）如果跨越 64 字节缓存线边界，同样会损失 macro-fusion。后链接优化器应识别并修复此类边界问题。

## 原文摘录

> The high compilation costs and severe frontend bottlenecks in full-cycle RTL simulation are well known in the RTL simulation community. These frontend bottlenecks are primarily caused by the large, statically generated C++ simulation code, and are exacerbated by branching. ESSENT mitigates these issues by proposing an alternative approach that completely unrolls the RTL dataflow graph into straight-line code. This design reduces branch overhead, improves instruction-cache (I-cache) prefetching, and enables more aggressive compiler optimizations.
> — *RTeAAL Sim, Section 3*

> We evaluate Verilator and ESSENT in terms of both simulation performance and compilation overhead... Verilator incurs between 80 and 120 MPKI, while ESSENT reduces this to between 64 and 70 MPKI, indicating improved instruction locality but still substantial frontend pressure.
> — *RTeAAL Sim, Section 3*

> Aggressive inline. Parendi ensures that the simulation program on the IPU is free of function calls. Inlining can increase code size and produce excessive instruction cache pressure on x86, especially in RTL simulation, where nearly every instruction executes only once per RTL cycle, except for code in functions invoked multiple times. An IPU tile has no instruction cache but a 624 KiB local memory, of which 200 KiB holds executable code. So, a single IPU chip has ≈300 MiB of on-chip instruction memory space, which allows Parendi to aggressively inline code.
> — *Parendi: Thousand-Way Parallel RTL Simulation, Section 5.2*

> Experience shows that the instruction cache size often limits large models, and reducing code size, if possible, can be beneficial. The supplied `$VERILATOR_ROOT/include/verilated.mk` file uses the `OPT`, `OPT_FAST`, `OPT_SLOW`, and `OPT_GLOBAL` variables to control optimization. You can set these when compiling the output of Verilator with Make, for example: `make OPT_FAST="-Os -march=native" -f Vour.mk Vour__ALL.a`
> — *Verilator Documentation, Benchmarking & Optimization*

> BOLT rearranges code inside functions based on their execution profile. Then the body of the function can be split based on how frequently the code is executed. Once this is done, the final step is to perform an optimal layout of the hot chunks of code depending on the call graph profile.
> — *Accelerate large-scale applications with BOLT, Facebook Engineering*

> We found that a pair of instructions could be folded internally by the CPU into a single micro-op for faster execution. This operation, called macro-fusion, allows the CPU to execute additional macro instructions per cycle. But it can't happen if the second instruction is aligned at a cache line boundary (64 bytes), as was the case with an instruction from a pair inside the hottest loop of bzip2. We then modified the BOLT layout algorithm so that it can prevent such misshapenness and also detect and fix similar issues.
> — *Accelerate large-scale applications with BOLT, Facebook Engineering*

> BOLT is a relatively recent software technique where the binary is instrumented and then profiled and this profiling data is used to improve the instruction cache and BTB behavior. By its nature it can only be applied to pre-compiled binaries, thus of the applications we examined it was only applied to Verilator (hence all results to this point are shown as "verilator-bolted").
> — *Exposing Shadow Branches, Section 5.3*

> Profile-guided binary optimization (PGO) is an important step for improving performance of large-scale applications that tend to contain huge amounts of code. Such techniques, also known as feedback-driven optimization (FDO), are designed to improve code locality which leads to better utilization of CPU instruction caches. In practice tools like AutoFDO, FDO, and BOLT speed up binaries by 5%–15% depending on workload and CPU architecture.
> — *Improved Basic Block Reordering, Sergey Pupyrev*

> Our findings show that, for large applications, it is better to aggressively reduce I-cache occupation, except if the change incurs D-cache overhead, since cache is one of the most constrained resources in the data-center space. This explains BOLT's policy of discarding all NOPs after reading the input binary. Even though compiler-generated alignment NOPs are generally useful, the extra space required by them does not pay off and simply stripping them from the binary provides a small but measurable performance improvement.
> — *BOLT: A Practical Binary Optimizer, Section 3*

## 相关链接

- [Accelerate large-scale applications with BOLT (Facebook Engineering)](https://engineering.fb.com/2018/06/19/data-infrastructure/accelerate-large-scale-applications-with-bolt/)
- [RTeAAL Sim 论文](https://arxiv.org/abs/2601.18140)
- [Parendi: Thousand-Way Parallel RTL Simulation](https://arxiv.org/abs/2403.04714)
- [Exposing Shadow Branches (含 Verilator+BOLT 验证)](https://arxiv.org/abs/2408.12592)
- [Improved Basic Block Reordering (PGO 综述)](https://arxiv.org/pdf/1809.04676v1)
- [BOLT 论文 (arXiv)](https://arxiv.org/pdf/1807.06735)
- [PGO Inlining Policy (.NET Runtime)](https://github.com/dotnet/runtime/issues/43914)
- [C++ Low-Level Optimization (Inlining 风险)](https://simplifycpp.org/books/minibooklet/mini_booklet_CPP_Low_Level_Optimization.pdf)
- [Verilator 官方优化文档](https://github.com/verilator/verilator/blob/master/docs/guide/simulating.rst)

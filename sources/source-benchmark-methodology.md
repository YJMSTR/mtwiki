---
title: RTL 仿真器性能基准测试方法论
description: 搜集 RTL 仿真器加速比测量规范、Amdahl 定律应用、Verilator 多线程 benchmark 方法及具体测量命令
source_url: "https://ar5iv.labs.arxiv.org/html/2301.09413"
source_type: "paper"
author: "Manticore Team (ASPLOS 2024)"
date: "2023-08-29"
tags: ["benchmark", "speedup", "parallel-simulation", "Verilator", "Amdahl"]
keywords: ["RTL simulation benchmark", "speedup measurement", "multithreading", "cycle-accurate simulation", "full-cycle simulation"]
capture_date: "2026-06-19"
---

# RTL 仿真器性能基准测试方法论

## 来源

- URL: https://ar5iv.labs.arxiv.org/html/2301.09413
- 类型: paper
- 作者: Manticore Team (ASPLOS 2024)
- 日期: 2023-08-29
- 补充来源:
  - Parendi (arXiv:2403.04714): https://arxiv.org/html/2403.04714v2
  - RTLflow (DAC 2022): https://dl.acm.org/doi/fullHtml/10.1145/3545008.3545091
  - Verilator 官方文档: https://www.veripool.org/verilator/
  - Embecosm Verilator 评估: https://www.embecosm.com/

## 摘要

本资料汇总了 RTL 仿真器性能基准测试的核心方法论，包括加速比测量规范、Amdahl 定律在并行仿真中的约束、以及业界主流工具（Verilator、Parendi、Manticore、RTLflow）的实验设定惯例。关键发现：Verilator 单线程比解释型仿真器（如 Icarus Verilog）快约 100×，多线程再获 2–10× 额外加速；但通用 CPU 上的多线程扩展受限于同步开销与缓存压力，小设计在 2 线程以上反而降速。测量应以 **几何平均（geometric mean）** 跨多个 benchmark 报告，并区分串行 vs 多线程的加速比。

## 关键要点

### 1. 加速比计算公式

- **单线程加速比（vs 解释型仿真器）**:
  ```
  Speedup_single = T_interpreted / T_verilator_single
  ```
  Verilator 文档声称约 100× 于 Icarus Verilog；Embecosm 独立测量在 SoC benchmark 上约 30×。

- **多线程加速比（vs 自身单线程）**:
  ```
  Speedup_MT = T_single_thread / T_multi_thread
  ```
  注意：Manticore 论文中记为 `×self`，即相对于自身串行版本的加速。

- **跨平台加速比（vs 其他工具）**:
  ```
  Speedup_cross = T_baseline / T_target
  ```
  Parendi 报告相对 Verilator 多线程的几何平均加速为 2.81×（ix3）和 2.75×（ae4）。

- **几何平均（Geometric Mean）**: 跨多个 benchmark 时必须使用几何平均而非算术平均，以避免被单一异常值扭曲。
  ```
  Geomean = (Π speedup_i)^(1/n)
  ```

### 2. 测量规范与实验设定

| 项目 | 业界惯例 |
|------|----------|
| **关闭波形输出** | 测量纯仿真吞吐量时必须禁用 FST/VCD dump（见 yodalee 博客：倒波形本身触发 cache miss，可占运行时 50% 以上） |
| **禁用 timing/delay** | 与 cycle-accurate 工具对比时，统一关闭 Verilator 的 timing 支持（`--no-timing`） |
| **优化级别** | 统一使用 `-O3`（Verilator）或对应编译器的最高优化 |
| **预热与稳态** | 运行 "millions to billions of cycles" 以捕获稳态性能（Manticore 论文） |
| **线程数扫描** | Verilator 论文惯例：从 2 到 32 线程，步长 2（Parendi） |
| **报告单位** | 仿真频率（kHz / MHz）= 模拟的 RTL cycles /  wall-clock time |
| **重复次数** | 至少 3 次以上取平均，变异系数（CV）< 5% 视为可信 |

### 3. 具体测量命令（Verilator）

```bash
# 1. 单线程编译与运行
verilator --cc --exe --build --trace-fst -O3 -CFLAGS "-O3 -march=native" \
  -Mdir obj_dir_single --threads 1 top.v sim_main.cpp
./obj_dir_single/Vtop

# 2. 多线程编译（以 16 线程为例）
verilator --cc --exe --build --trace-fst -O3 -CFLAGS "-O3 -march=native" \
  -Mdir obj_dir_mt --threads 16 top.v sim_main.cpp
./obj_dir_mt/Vtop

# 3. 禁用波形（纯性能测量）
verilator --cc --exe --build -O3 --no-trace --threads 16 top.v sim_main.cpp

# 4. 使用 perf 统计 IPC / cache miss（详见 source-simulator-profiling.md）
perf stat -e cycles,instructions,cache-misses,cache-references,branches,branch-misses \
  ./obj_dir_mt/Vtop

# 5. 使用 taskset 绑核（避免跨 NUMA 抖动）
taskset -c 0-15 ./obj_dir_mt/Vtop
```

### 4. Amdahl 定律在 RTL 仿真中的约束

Manticore 论文明确指出：

> "Manticore is not immune to Amdahl’s law. If there is insufficient parallelism in the workload, then Manticore’s scaling plateaus. Depending on the RTL design, this may happen early (jpeg) or late (mc)."

- **jpeg benchmark**：串行数据依赖（Huffman 表查找）导致并行度仅提升约 17%，无法弥补单核性能差距。
- **mc benchmark**：并行度足够高，扩展性持续到 200–300 核。

对于通用 CPU 上的 Verilator 多线程，论文 §7.1 的模型揭示了三个性能区域：

1. **小电路（< 几千指令/周期）**：1→2 线程即因同步开销陡降。
2. **中等电路（2K–20K 指令/周期）**：多线程有收益，但同步成本 eventually 超过拆分收益。
3. **大电路（> 100K 指令/周期）**：并行有利，但需要大量核心才能把频率推到 100 kHz 以上。

### 5. Roofline 模型视角

RTL 仿真本质上是 **计算密集型整数位运算负载**（无浮点操作），其 roofline 特征：
- 算力瓶颈：逻辑运算、位操作、条件判断。
- 内存瓶颈：当设计规模增大时，cache miss 成为主导（见 yodalee 博客：NVDLA 的 50 万变量导致 cache miss 吃掉所有优化红利）。
- 同步瓶颈： barrier / spin-lock 是通用 CPU 上的天花板，与指令粒度成反比。

## 对 RTL 仿真器多线程化的启示

1. **Benchmark 选择必须覆盖三个粒度区域**：小（picorv32）、中（RISC-V SoC）、大（NVDLA/OpenTitan），否则加速比结论不具有代表性。
2. **测量时必须禁用波形输出**：FST dump 是独立的 I/O 瓶颈，会掩盖多线程的真实收益。
3. **16 线程 > 2× 加速比并非 trivial**：Verilator 在 EPYC 上最大 `×self` 为 4.6×（vta），但 jpeg 仅 0.3×（多线程比单线程更慢）。要科学地声称 > 2×，必须报告几何平均并说明 benchmark 分布。
4. **编译时间也是成本**：Verilator 多线程代码生成对大型设计（如 sr15）可能需要 8 小时和 1TB+ 内存，benchmark 实验需预留编译时间指标。

## 原文摘录

> "Verilator's documentation reports compiled Verilator models running about 100 times faster than interpreted Verilog simulators such as Icarus Verilog; an independent Embecosm evaluation measured ~30× on a representative SoC benchmark. The exact speedup is workload-dependent."
> — Arch HDL 论文, §7.3.2

> "Multithreaded Verilator improves performance by up to 3.9× and 4.6× on desktop and server processors, respectively. Multithreading could not improve performance on the smaller benchmarks (e.g., bc and jpeg)."
> — Manticore 论文, §7.6.1

> "Overall, Parendi outperforms Verilator: geometric mean speedups are 2.81 and 2.75 compared to ix3 and ae4."
> — Parendi 论文, §6.1

> "The jpeg benchmark contains sizeable sequential data dependencies that cannot be parallelized. Huffman table lookup is the bottleneck. Manticore's slow sequential performance hurts us on this serial benchmark. Parallelism improves jpeg's single-core performance by only ≈17%."
> — Manticore 论文, §7.6.2

> "Design 愈大的时候，能吃到的加速红利就愈小，甚至在刚完成的时候，我们的实作还会比 gtkwave 的 C 实作还要慢。原因是大型设计的变量多很多，光是把对应的储存处找出来就会先触动到 cache miss，去记忆体拉资料的时间就把整个模拟给卡死。"
> — yodalee, "让 Verilator 倒波形快还要更快"

## 相关链接

- [Manticore: Hardware-Accelerated RTL Simulation with Static Bulk-Synchronous Parallelism](https://ar5iv.labs.arxiv.org/html/2301.09413)
- [Parendi: Thousand-Way Parallel RTL Simulation](https://arxiv.org/html/2403.04714v2)
- [RTLflow: From RTL to CUDA](https://dl.acm.org/doi/fullHtml/10.1145/3545008.3545091)
- [Verilator Official Documentation](https://www.veripool.org/verilator/)
- [让 Verilator 倒波形快还要更快](https://yodalee.me/2026/02/libfstpp/)

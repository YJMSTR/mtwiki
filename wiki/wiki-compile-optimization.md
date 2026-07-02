---
title: "编译时RTL优化技术"
description: "综合门优化、死代码消除、向量化三类编译时RTL优化技术，涵盖Yosys/ABC/SmaRTLy、Verilator/Dart/ERASER、GEM/GSIM/Parendi等工具链，提供面向多线程RTL仿真器的可操作建议。"
source_refs:
  - source-gate-optimization
  - source-dead-code-elimination
  - source-vectorization-rtl
date: "2026-07-03"
tags: ["compile-time-optimization", "gate-optimization", "dead-code-elimination", "vectorization", "RTL-simulation", "multithreading"]
keywords: ["Yosys opt", "ABC AIG", "SmaRTLy", "UNOPTFLAT", "Dart", "ERASER", "GEM", "GSIM", "Parendi", "word-level simulation", "bit-level splitting"]
---

# 编译时RTL优化技术

编译时优化是RTL仿真器性能的第一道防线。在RTL被翻译为C++/CUDA/IPU代码之前，通过门级压缩、死代码消除和数据表示向量化，可以大幅减少每周期执行指令数、降低缓存压力，并为多线程划分创造更优的DAG结构。本章将三类优化技术——**门优化**、**死代码消除**、**向量化**——整合为一套可操作的编译管线。

---

## 1. 门优化：从RTL到极简AIG

门优化的目标是在保持功能等价的前提下，将RTL描述压缩为最小规模的And-Inverter Graph（AIG），直接减少仿真器每周期需执行的逻辑运算量。

### 1.1 Yosys `opt` 套件：迭代式常量折叠与MUX化简

Yosys 的 `opt` pass 是开源RTL综合中门优化的基础入口，执行流程如下：

```
opt 首次:
  ├── opt_expr          ← 常量折叠与表达式化简
  ├── opt_merge -nomux  ← 合并相同单元（不合并MUX）
  稳定循环直到收敛:
  ├── opt_muxtree       ← 分析选择输入，消除MUX死分支
  ├── opt_reduce        ← 合并 reduce_and / reduce_or 输入
  ├── opt_merge         ← 合并相同单元（含MUX）
  ├── opt_rmdff         ← 移除输入为常量的DFF
  ├── opt_clean         ← 移除未使用信号与单元
  └── opt_expr          ← 再次常量折叠
```

**`opt_expr` 常量折叠规则（以 `$_AND_` 为例）**：

| A-Input | B-Input | Replacement |
|---------|---------|-------------|
| any | 0 | 0 |
| 0 | any | 0 |
| 1 | 1 | 1 |
| X/Z | X/Z | X（undef 传播，仅 IEEE 1364-2005 允许的 3 种情况）|
| 1 | a | a（恒等替换）|
| any | X/Z | 0（当其他替换不可行时保守假设 0）|

**`opt_muxtree` 示例**：
对于 `assign y = a ? (a ? 1 : 2) : 3`，外MUX选择 `a=1` 时内MUX选择 `a=1`，因此 `a=0` 分支不可能到达内MUX，输出 2 永远不会出现。`opt_muxtree` 将内MUX替换为常量 1，化简为 `y = a ? 1 : 3`。

**`opt_rmdff`** 识别输入为常量的DFF并用常量驱动器替代，消除无状态翻转开销。

### 1.2 ABC AIG Rewriting + Resubstitution

Berkeley ABC 的 `resyn2` 与 `dc2` 脚本对AIG进行多轮重写：

| 技术 | 机制 | 效果 |
|------|------|------|
| **Rewriting** | 基于4-input cuts的结构哈希，探索局部等价子结构 | 减少节点数 |
| **Resubstitution** | 基于SAT sweeping检测功能等价节点 | rewriting后再削减2–3%节点 |
| **Structural Choices** | 保留多个功能等价但结构不同的AIG版本 | 供技术映射器按延迟/面积目标选择 |

实验数据（IWLS 2005 benchmarks）：`resyn2` + `dc2` 迭代4次可在runtime与优化效果间取得良好平衡。对于百万门级工业设计，AIG规模缩减直接影响仿真器指令缓存命中率和每周期执行时间。

### 1.3 SmaRTLy：SAT-based冗余消除与MUX树重构

SmaRTLy 在 Yosys `opt_muxtree` 基础上进行更激进的优化：

- **SAT-based Redundancy Elimination**：通过SAT求解器捕捉信号间逻辑蕴含关系，消除冗余节点。平均贡献 **3.57%** 面积缩减。
- **MUX Tree Rebuilding with ADD**：使用ADD重新分配控制信号与输出，重构效率低下的MUX树。平均贡献 **4.39%** 面积缩减。
- **组合效应**：两项结合在公开benchmark（IWLS-2005 + RISC-V）上额外削减 **8.95%** AIG面积；在工业级百万门benchmark上额外削减 **47.2%** AIG面积。

| Benchmark | Original AIG | Yosys 优化后 | SmaRTLy 优化后 | 额外缩减比例 |
|-----------|-------------|------------|---------------|------------|
| top_cache_axi | 10,836,722 | 1,301,437 | 977,118 | **24.92%** |
| wb_conmax | 336,039 | 123,659 | 89,290 | **27.79%** |
| wb_dma | 592,158 | 74,697 | 64,322 | **13.89%** |
| **Average** | 1,415,259.6 | 195,765.7 | 157,721.4 | **8.95%** |

---

## 2. 死代码消除：消除无意义计算

死代码消除（Dead Code Elimination, DCE）直接移除不参与输出的逻辑链，是仿真器性能提升最明显的单类优化之一。

### 2.1 Yosys `opt_clean`：编译期未使用信号清理

`opt_clean` 是Yosys `opt` 套件中最基础的DCE pass：

- 识别未使用的信号（wire）和单元（cell），移除整个驱动链。
- 对多bit信号标记未使用位宽片段（`unused_bits`属性），供后续 `fsm_opt` 利用。
- 在合成流程中每个阶段后执行，体现迭代收敛特性。

以 `vlut.v` 为例：一次 `opt_clean` 可移除 **3 条** 未使用临时线网，下一轮 `opt_expr` 后又移除 **1 条**。

### 2.2 Verilator UNOPTFLAT：打破组合逻辑环

Verilator将RTL编译为C++，RTL层面的冗余直接映射为C++代码冗余：

| 警告/Pass | 含义 | 对性能的影响 |
|-----------|------|------------|
| `UNUSED` | 信号被赋值但从未被读取 | 生成无意义C++计算语句 |
| `UNOPTFLAT` | 组合逻辑环导致无法静态优化 | 运行时需多次求值直到稳态，**严重影响性能** |
| `UNOPT` | 更广泛的未优化组合逻辑 | 同样导致多轮迭代求值 |

**关键性能数据**：修复一个 `UNOPTFLAT` 警告（时钟门控锁存器简单修改）获得 **60% 性能提升**。

**Verilator未使用信号兜底写法**：

```verilog
wire _unused_ok = 1'b0 && &{1'b0,
                              sig_not_used_a,
                              sig_not_used_yet_b,
                              1'b0};
```

将未使用信号与常量连接，保证Verilator标记为已使用，避免误报，同时不引入实际计算开销。

### 2.3 Dart：跨激励DAG驱动冗余消除

Dart（DAC 2025）提出DAG驱动的RTL仿真框架，核心思想是**不同激励在仿真中会收敛到相同内部状态，大量电路逻辑被冗余重复求值**：

- **DAG IR**：将RTL结构化为DAG，使跨激励公共子表达式显式化。
- **Sub-DAG Merging**：系统合并功能等价的子DAG，共享计算结果。
- **Computation-centric Engine**：共享逻辑只计算一次，结果分摊到所有经过该状态的激励。

**性能数据**：相比Verilator最高加速 **136.7×**，相比RTLflow（GPU批处理）加速 **4.1×**。

### 2.4 ERASER：RTL故障仿真中的隐式冗余消除

ERASER针对RTL故障仿真中行为节点的冗余执行问题：

- **隐式冗余**：故障输入与正常输入不同，但输出仍与正常行为一致，此时故障节点执行是冗余的。
- **显式冗余**：将门级并发故障仿真扩展至RTL行为节点，通过good gate/bad gate事件区分消除。
- **Visibility Dependency Graph (VDG)**：构建CFG扩展图，追踪各执行路径上真正影响结果的输入信号。

**性能数据**：相比商业仿真器平均加速 **3.9×**，相比开源故障仿真器平均加速 **5.9×**。

### 2.5 NFReducer：三层冗余消除框架

NFReducer面向网络功能，但其冗余分类框架对RTL仿真器同样适用：

| 类型 | 冗余来源 | RTL对应场景 |
|------|----------|------------|
| **Type-I** | 未使用层级的解析逻辑 | 总线中仅使用部分位宽，其余位解析逻辑冗余 |
| **Type-II** | 未使用协议分支 | 设计仅处理特定协议时，其他协议分支死代码 |
| **Type-III** | 跨模块冗余 | 上游模块已过滤某条件，下游模块重复判断逻辑冗余 |

消除方法：Apply Rules → Constant Folding/Propagation → Dead Code Elimination。

---

## 3. 向量化：字级并行与位级压缩

向量化优化在编译期识别信号的位宽使用模式，以字级向量运算替代逐位循环，以位级分裂消除不必要的激活开销。

### 3.1 Word-Level Simulation：从位级到字级的并行加速

Word-level simulation将多个仿真模式的位值打包进一个机器字（如64位），用一条字级AND/OR/XOR指令同时处理64个模式：

- **复杂度分析**：对于2^k个输入模式，bit-level simulation代价为 **O(2^k)**；word-level simulation（字长2^l=64）代价为 **O(|XAIG| · 2^(k−l))**。
- **AIG紧凑性**：最小化AIG表示可进一步降低偏移量 Δ ≈ log|XAIG| − l。若AIG过大，字级并行加速会被节点数增长抵消。
- **适用场景**：布尔神经网络仿真、蒙特卡洛仿真、批量故障仿真等需大量独立模式的场景。

### 3.2 GEM：GPU上的E-AIG与Word-Level Parallelism

GEM（DAC 2025）将RTL设计视为扩展AIG（E-AIG）的分区集合，在GPU上执行布尔运算：

- **E-AIG**：在标准AIG基础上支持XOR、MUX等复杂门类型，仍以2-input AND + INV为主体。
- **Word-Level Parallelism**：将32位整数运算视为 **32个并行位通道**。
- **Boomerang-Shaped Executor**：针对AIG逻辑深度分布不均衡（长尾特性），递归位排列与boomerang层交错执行，将逻辑深度从148压缩到19（以Gemmini为例）。

| 对比基准 | 平均加速 | 峰值加速（NVDLA） |
|---------|---------|------------------|
| 商业仿真器（单核） | **9.15×** | **64.76×** |
| Verilator 8线程 | **5.98×** | 38.85× |
| Verilator 单线程 | **24.87×** | 64.76× |

GEM的bitstream格式极为紧凑：500万门、800MB扁平Verilog的设计，压缩后仅需 **162.4 MB** GPU内存。

### 3.3 GSIM：超节点聚合 + 位级分裂

GSIM（2025）针对大规模RTL设计（XiangShan、BOOM）提出三层优化：

- **超节点（Supernode）**：将数据流图中频繁一起激活的节点聚合，减少调度开销和函数调用次数。
- **位级分裂（Bit-Level Splitting）**：扩展数据流分析到位级，根据相邻位的访问方向判断何时将节点按位拆分。避免"整个64位总线被标记为活跃，实际只翻转3位"的过度计算。
- **图分区**：对超节点后的图进行多目标分区，平衡计算量与通信量。

| 场景 | 加速 vs Verilator 单线程 | 备注 |
|------|------------------------|------|
| XiangShan 启动Linux | **7.34×** | 实际系统级工作负载 |
| Rocket 运行CoreMark | **19.94×** | 超越ESSENT和Arcillator 2.52× |
| SPEC CPU 2006 (XiangShan) | **3.72×** 平均 | 对比8线程Verilator为1.18× |

从无优化基线到完整优化，GSIM各项技术累积带来 **16.4× ~ 85.4×** 改进。超节点贡献最大，位级分裂对BOOM和XiangShan效果明显，但对Rocket和stuCore影响较小（说明收益与设计数据通路宽度相关）。

### 3.4 Parendi：千核并行下的字级负载均衡

Parendi在Graphcore IPU（1472核/芯片，最高5888核）上运行并行RTL仿真：

- **Fiber-based DAG Partition**：将RTL DAG划分为fiber（独立子流）。
- **LUT-level Scheduling**：不以算术操作而以LUT节点为调度粒度，一个乘法器的LUT数可能是加法的10倍，LUT级调度显著改善负载均衡。
- **Redundancy-Aware Partition**：联合优化负载均衡与冗余消除，避免相邻fiber重叠节点分配至不同核心导致的冗余计算。

| 平台 | 单线程 | 最佳多线程 | Parendi 最佳 | 几何平均加速 |
|------|--------|-----------|-------------|------------|
| Verilator (x86) | 基准 | 20×+（仅大设计） | — | — |
| Parendi (IPU) | 84×慢（pico） | 1472–5888 tiles | 2.81× (ix3) / 2.75× (ae4) | **2.8×** |

关键洞察：单tile的IPU执行比x86慢约37–84倍，必须大规模并行才能追上Verilator。但IPU的高带宽通信使其在千核级别仍能获得近线性加速，而x86在跨chiplet/socket时加速比骤降。

### 3.5 LLVM BFG：位级优化与部分选择

LLVM针对FPGA综合的位级优化技术同样适用于RTL仿真器编译期优化：

- **BFG（Bit-Flow Graph）**：构建位的数据流图，每个节点表示CONSTANT、VARIABLE、SET、NOT、AND/OR/XOR。
- **BFG简化规则**：
  - 规则1–3：位级复制传播（SET/NOT输入为SET时直接指向原始输入）。
  - 规则4：AND/OR/XOR双输入均为常量 → 替换为常量节点。
  - 规则5：AND输入为常量0 → 替换为0；输入为常量1 → 替换为另一输入。
  - 规则6：OR输入为常量1 → 替换为1；输入为0 → 替换为另一输入。
- **部分选择变换**：`(x >> 8) & y` 被识别为仅需`x`的低24位参与运算，生成24位AND而非32位。

实验数据：`bit_reverse` 函数经位级优化后，综合结果从 **34 slices + 3周期** 降至 **0 slices + 0延迟**（纯位重排赋值）。

---

## 4. 对多线程RTL仿真器的启示

### 4.1 编译优化与多线程的协同关系

| 优化类型 | 对单线程的影响 | 对多线程的额外收益 |
|----------|---------------|-------------------|
| 门优化（AIG压缩） | 减少每周期指令数 | 节点越少→DAG分区搜索空间越小→负载均衡越易实现 |
| 死代码消除 | 消除无意义计算 | 死代码会均匀/不均匀分布在macro-task中，分区前清除可避免误判真实计算量 |
| 向量化（字级） | 单线程内并行64/32位 | 减少每个线程内存访问次数，macro-task代码体积适配L1缓存 |
| 位级分裂 | 消除过度计算 | 减少割边（cut）数据交换量，降低跨线程通信 |

### 4.2 关键洞察

1. **编译时门优化是多线程化的前置步骤**：在RTL分割为多线程macro-task之前，先通过`opt_expr` + `opt_muxtree` + AIG rewriting压缩逻辑规模，减少每个线程工作量，降低同步粒度。
2. **常量折叠消除跨线程依赖**：若某信号在编译期被折叠为常量，下游所有依赖该信号的节点无需跨线程通信，直接消除割边数据交换。
3. **AIG规模缩减 → 更优DAG分区**：节点数越少，V3VariableOrder（Verilator的TSP近似优化）和Parendi的fiber partition搜索空间越小，越容易找到负载均衡的线程分配方案。
4. **UNOPTFLAT类问题在多线程中放大**：组合逻辑环导致的多轮求值在单线程中已造成性能损失，在多线程中还会引发额外跨线程同步（每轮求值后需广播新状态）。编译期消除逻辑环是减少同步的关键。
5. **字级向量运算是多线程cache效率的关键**：将64位总线运算打包为单条机器字操作，减少每个线程的内存访问次数和指令数，使macro-task代码体积适配L1缓存。
6. **超节点聚合与多线程粒度匹配**：超节点大小应与macro-task计算量匹配。超节点过小→调度开销高；超节点过大→负载均衡差。GSIM的20–50阈值经验可作为Verilator多线程划分的参考。

---

## 5. 可操作建议：编译优化管线与检查清单

### 5.1 推荐编译管线：Yosys → ABC → AIG优化

```bash
# Step 1: Yosys 基础优化（常量折叠 + MUX化简 + 死代码消除）
yosys -p "read_verilog design.v; synth -top top; opt -full; opt_clean;" \
      -p "write_verilog design_opt.v"

# Step 2: ABC AIG 重写与resubstitution（需Yosys abc pass）
yosys -p "read_verilog design_opt.v; synth -top top;" \
      -p "abc -script resyn2; abc -script dc2;" \
      -p "write_verilog design_abc.v"

# Step 3: Verilator 编译，启用最高优化 + 多线程
verilator --cc --exe --build -O3 --threads 16 \
  -CFLAGS "-O3 -march=native" \
  --no-trace \
  design_abc.v sim_main.cpp
```

### 5.2 UNOPTFLAT 修复与多线程启用检查清单

```bash
# 1. 编译时检查所有UNOPTFLAT警告
verilator --cc --exe --build -O3 --threads 1 design.v sim_main.cpp 2>&1 | \
  grep -E "UNOPTFLAT|UNOPT|UNUSED" | tee warnings.log

# 2. 逐一修复UNOPTFLAT（参考Verilator手册建议）
# 常见修复：将时钟门控锁存器改为显式时钟使能，或添加 /*verilator split_var*/

# 3. 修复后重新测量单线程基线
perf stat -e cycles,instructions ./obj_dir_single/Vtop

# 4. 确认无UNOPTFLAT后启用多线程
verilator --cc --exe --build -O3 --threads 16 --no-trace design.v sim_main.cpp
perf stat -e cycles,instructions taskset -c 0-15 ./obj_dir_mt/Vtop
```

### 5.3 Word-Level + SIMD 双重加速策略

| 步骤 | 操作 | 预期收益 |
|------|------|----------|
| 1. AIG压缩 | Yosys opt + ABC resyn2/dc2 | 减少节点数10–50% |
| 2. 字级打包 | 将64个独立测试向量打包为64位字 | 单线程内64×并行 |
| 3. SIMD指令 | 使用编译器向量化（`-mavx2` / `-mavx512`） | 额外2–8× |
| 4. 位级分裂 | 编译期识别未使用位宽，分裂信号 | 减少激活开销 |
| 5. 超节点聚合 | 将频繁共激活节点合并为超节点 | 减少调度开销 |

### 5.4 快速诊断命令

```bash
# 检查Yosys优化效果（门数对比）
yosys -p "read_verilog design.v; synth -top top; stat" > before.stat
yosys -p "read_verilog design.v; synth -top top; opt -full; abc -script resyn2; stat" > after.stat
diff before.stat after.stat

# 检查Verilator生成代码体积（间接反映RTL优化效果）
wc -l obj_dir/Vtop__ALL.cpp

# 检查UNOPTFLAT是否已清零
grep -c "UNOPTFLAT" warnings.log  # 期望输出：0

# 检查perf IPC（验证优化后指令效率）
perf stat -e cycles,instructions ./obj_dir/Vtop 2>&1 | grep "insn per cycle"
```

---

## 6. 参考来源

- [Yosys Optimizations 文档](https://blog.eowyn.net/yosys/CHAPTER_Optimize.html)
- [SmaRTLy 论文 (arXiv:2510.17251)](https://arxiv.org/html/2510.17251v1)
- [Verilator Benchmarking & Optimization](https://verilator.org/guide/latest/simulating.html)
- [ABC: AIG Rewriting & Structural Choices](https://people.eecs.berkeley.edu/~alanmi/publications/2023/date23_gap.pdf)
- [Dart: Towards Redundancy-Free RTL Simulation (DAC 2025)](https://63dac.conference-program.com/presentation/?id=RESEARCH2011&sess=sess164)
- [ERASER 论文 (arXiv:2504.16473)](https://arxiv.org/html/2504.16473v1)
- [GEM: GPU-Accelerated Emulator-Inspired RTL Simulation (DAC 2025)](https://yibolin.com/publications/papers/SIM_DAC2025_Guo.pdf)
- [GSIM: Accelerating RTL Simulation (arXiv:2508.02236)](https://arxiv.org/html/2508.02236v1)
- [Parendi: Thousand-Way Parallel RTL Simulation (arXiv:2403.04714)](https://arxiv.org/html/2403.04714v1)
- [LLVM Bit-Level Optimization for FPGA](https://llvm.org/pubs/2010-02-FPGA-BitLevel.pdf)

---
title: RTL并行仿真论文全景
description: 覆盖2018-2025年间顶级EDA与体系结构会议中RTL仿真加速的核心论文，从多线程软件并行、硬件加速到仿真内核编译优化，提供技术路线地图、选型决策树与复现路线。
author: 论文综合研究员（子代理）
date: 2025-08-20
tags: [RTL-simulation, parallel-simulation, multithreading, hardware-acceleration, compiled-simulation, EDA, ASPLOS, MICRO, ISCA, DAC, DATE]
keywords: [Parendi, RepCut, Manticore, ASH, GEM, Khronos, FireSim, Verilator, Tango, Cuttlesim, GATSPI, GL0AM, GSIM]
source_refs: [source-papers-parallel-rtl, source-papers-hardware-accel, source-papers-sim-kernel]
---

# RTL并行仿真论文全景

## 论文全景地图

RTL仿真加速研究在2018-2025年间呈现井喷态势，技术路线可分为三大主线：

| 主线 | 代表工作 | 核心思想 | 典型加速比 | 成熟度 |
|------|----------|----------|------------|--------|
| **多线程/多核软件并行** | Parendi, RepCut, Manticore, BatchSim, TaroRTL | 图划分、静态调度、复制辅助、跨周期批处理 | 2x–135x | ★★★☆☆ |
| **硬件加速** | FireSim/FireAxe, ASH, GEM, Khronos, GATSPI, GL0AM | FPGA cycle-exact、GPU批量并行、数据流专用架构 | 2x–1993x | ★★★★☆ |
| **仿真内核与编译优化** | Cuttlesim, Tango, LECSIM, SSIM, Verilator 4.0 | 编译式仿真、层级化执行、JIT优化、活动因子感知 | 2x–30k sim/s | ★★★★★ |

> **纯度提示**：这三条线不是互斥的。最优的工程实践往往是在软件仿真器（快速迭代）→ GPU批量回归 → FPGA系统验证的三层架构中按需切换。试图用单一技术路线解决所有场景，往往「蚌埠住了」。

---

## 一、多线程/多核软件并行

### 1.1 核心论文速览表

| 论文 | 会议 | 年份 | 核心方法 | 加速比 | 关键洞察 |
|------|------|------|----------|--------|----------|
| **Parendi** | ASPLOS'25 | 2025 | 千核BSP静态调度，DAG划分，VCPL预测 | 千核级扩展 | 动态调度在>数十核后开销爆炸，编译时静态调度是关键 |
| **RepCut** | ASPLOS'23 | 2023 | 复制辅助划分（Replication-Aided Partitioning） | **超线性**（8核>8x） | 少量复制节点换缓存局部性，打破最小边划分迷信 |
| **Manticore** | ASPLOS'24 | 2023/24 | 225核FPGA加速器，静态BSP，无缓冲NoC | 最高27.9x，几何平均5.3x | 专用硬件-编译器协同设计是RTL细粒度并行的终极形态 |
| **Partition-Agnostic** | DAC'23 | 2023 | 运行时动态门分配，工作窃取 | 优于静态划分 | 固定划分在活动因子变化大的设计上负载严重不均 |
| **BatchSim** | ISVLSI'24 | 2024 | 跨周期批处理 + Cpp-Taskflow任务图 | 显著优于Verilator MT | 无跨周期依赖的连续周期可合并，摊平同步开销 |
| **TaroRTL** | Euro-Par'24 | 2024 | C++20协程 + CPU/GPU异构调度 | 8-10核最优 | 协程切换成本远低于线程，适合RTL大量短生命周期任务 |
| **Deduplication** | ASPLOS'24 | 2024 | 粗粒度电路去重，复用划分模式 | 2x–6x | 多核SoC中重复模块实例的逐实例划分不可行 |
| **Metro-MPI** | DATE'23 | 2023 | MPI多节点 + OpenMP多线程混合 | 模拟10B晶体管SoC | 多节点+多线程混合并行在超大规模设计上可行 |

### 1.2 技术路线对比

```
┌─────────────────────────────────────────────────────────────┐
│              多线程RTL仿真：两条技术路线                       │
├─────────────────────────────────────────────────────────────┤
│  静态调度路线（Parendi/Manticore）                             │
│  ├── 编译时构建完整DAG，静态分配到各核心                        │
│  ├── 运行时仅执行轻量barrier，无动态调度开销                     │
│  ├── 适合：规则计算、活动因子均匀、核数>32的场景                │
│  └── 代价：编译时间极长（Verilator sr15峰值1043 GiB）          │
│                                                              │
│  动态/混合调度路线（RepCut/Partition-Agnostic/BatchSim）      │
│  ├── 运行时根据活动状态动态分配任务                            │
│  ├── 复制辅助或工作窃取平衡负载                                │
│  ├── 适合：活动因子变化大、设计迭代频繁、核数<32的场景         │
│  └── 代价：运行时同步开销，扩展性受限                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、硬件加速

### 2.1 核心论文速览表

| 论文 | 会议 | 年份 | 核心方法 | 加速比 | 关键洞察 |
|------|------|------|----------|--------|----------|
| **FireSim** | ISCA'18 | 2018 | AWS F1 FPGA cycle-exact系统仿真 | **1000x+** | 最成熟的实用方案，但编译时间长（数小时到数天） |
| **FireAxe** | ISCA'24 | 2024 | 多FPGA划分仿真，延迟不敏感通信 | 线性扩展 | 解决单FPGA容量限制，跨FPGA确定性调试 |
| **ASH** | MICRO'23 | 2023 | 256核数据流专用处理器，选择性事件驱动 | **1485x**（vs单核Verilator） | 数据流+选择性事件驱动是理论上限，但需专用硬件 |
| **GEM** | DAC'25 | 2025 | GPU模拟器启发式，时分复用，混合调度 | 64x+（批量） | GPU与FPGA策略可互相借鉴，时分复用降低显存占用 |
| **Khronos** | MICRO'23 | 2023 | 纯软件跨周期内存访问融合 | 2.0x–4.3x | 内存访问是隐藏瓶颈，融合可减少70-95%缓存访问 |
| **GATSPI** | ISCA'25 | 2025 | 数据流门级仿真 | **1993x** | 零延迟模型+规则数据转换，适合向量化 |
| **GL0AM** | HPCA'26 | 2024 | GPU 0-delay + 重仿真 | 4x–76x | 层级排序+变化传播追踪，仅重算受影响路径 |
| **From RTL to CUDA** | ICPP'22 | 2022 | RTL自动转CUDA，批量刺激 | 40x+（64K向量） | GPU核心优势在批量测试向量，非单实例加速 |
| **GSIM** | DAC'25 | 2025 | 大规模RTL仿真软硬件混合策略 | 待确认 | 代表了RTL加速领域持续活跃的研究方向 |

### 2.2 硬件加速技术路线选择指南

```
设计阶段/需求 → 推荐方案 → 加速比 → 主要局限
─────────────────────────────────────────────────────────
快速迭代/调试    → 软件多线程（Verilator MT）   → 2-8x   → 核数扩展性差
批量回归测试     → GPU（RTLFlow/GEM/GL0AM）      → 40-64x → 显存容量，单刺激优势弱
系统级验证      → FPGA（FireSim/FireAxe）       → 1000x+ → 编译/综合时间长（数小时~数天）
理论极限探索     → 专用加速器（ASH/Manticore）    → 1000x+ → 需定制硬件，不可量产
功耗分析        → GPU门级（GATSPI）             → 数量级  → 仅门级，非RTL
```

---

## 三、仿真内核与编译优化

### 3.1 核心论文速览表

| 论文 | 会议 | 年份 | 核心方法 | 加速比 | 关键洞察 |
|------|------|------|----------|--------|----------|
| **Cuttlesim** | ASPLOS'21 | 2021 | 从Koika直接编译C++，保留高层语义 | 2x–5x（vs Verilator） | 高层语义信息可消除RTL级无法发现的冗余 |
| **Tango** | DATE'20 | 2020 | JIT编译，Proxy Coalescing，SNC/SRO | **6.9x**（vs Verilator） | JIT优化与多线程并行是正交可叠加方向 |
| **LECSIM** | DAC'90 | 1990 | 层级化编译+事件过滤共存 | 奠定现代基础 | 层级化是并行天然结构，事件过滤减少无效计算 |
| **SSIM** | DAC'87 | 1987 | 最早的软件层级化编译仿真器 | 奠基工作 | 状态保持+组合逻辑分离，周期精确模型原型 |
| **GPU Gate-Level** | DAC'09 | 2009 | GPU层级化内核，混合事件驱动 | 开创性 | 同层级完全并行，层级间barrier同步 |
| **French et al.** | DAC'95 | 1995 | 事件驱动仿真编译为静态代码结构 | 5x–9x | 动态调度静态化，编译时确定跨线程通信模式 |
| **Beamer & Donofrio** | DAC'20 | 2020 | 低活动因子感知，时钟/电源门控跳过 | 2x–10x | 现代设计大量时间处于空闲，不增加并行度即可数倍加速 |
| **Verilator 4.0** | ORConf'18 | 2018 | 多线程C++模型生成，pthread粗粒度 | 150–30k sim/s | 开源多线程RTL仿真基准，>8核扩展性显著下降 |
| **Kupriyanov et al.** | 2004 | 2004 | RTL层级化编译+事件过滤 | 5x–9x | 显式构建层级依赖图，为多线程调度提供精确边界 |

### 3.2 编译优化与多线程的关系

> **核心原则**：编译优化减少**单线程计算量**，多线程并行增加**并发度**。两者是正交的，但存在耦合点——编译时生成的代码结构直接影响多线程调度效率。

| 编译优化技术 | 对多线程的影响 | 耦合程度 |
|--------------|----------------|----------|
| Proxy Coalescing（Tango） | 减少跨分区指针追踪，降低缓存一致性流量 | ★★★☆☆ |
| 顺序节点合并 SNC（Tango） | 向量操作更利于SIMD/向量化并行 | ★★★★☆ |
| 跨周期内存融合（Khronos） | 融合后粗粒度任务分配线程，减少内存足迹 | ★★★★★ |
| 层级化拓扑排序（LECSIM/SSIM） | 同层级天然并行，是多线程调度的基础数据结构 | ★★★★★ |
| 活动因子感知（Beamer & Donofrio） | 每周期跳过无效分区，减少线程数和同步开销 | ★★★★☆ |
| 移位寄存器优化 SRO（Tango） | 标量操作替代内存复制，减少线程间false sharing | ★★★☆☆ |

---

## 四、对多线程RTL仿真器的启示

### 4.1 关键性能瓶颈总结

基于上述论文全景，多线程RTL仿真器的性能瓶颈可归为四类：

| 瓶颈类型 | 具体表现 | 来源论文 | 缓解方向 |
|----------|----------|----------|----------|
| **同步开销** | pthread barrier在>8核后急剧上升 | Verilator 4.0, Parendi | 静态调度替代动态调度 |
| **缓存竞争** | 跨线程共享寄存器状态的false sharing | RepCut, Khronos | 复制辅助划分、内存融合、V3VariableOrder |
| **负载不均** | 活动因子变化导致固定划分失衡 | Partition-Agnostic, Beamer & Donofrio | 动态工作窃取+活动因子预检测 |
| **内存带宽** | 每周期全量寄存器状态读写成为瓶颈 | Khronos, Tango | 跨周期融合、SoA布局、cache line对齐 |

### 4.2 论文全景地图：技术路线演进

```
1987  SSIM ─────── 层级化编译奠基
  │
1990  LECSIM ───── 层级化+事件过滤共存
  │
1995  French et al. ── 动态调度静态化
  │
2004  Kupriyanov ── RTL层级化编译
  │
2009  GPU Gate-Level ── GPU层级化并行
  │
2018  Verilator 4.0 ── 开源多线程基准
  │
2020  Tango ────── JIT编译优化（6.9x）
  │    Beamer & Donofrio ── 活动因子感知（2-10x）
  │    Partition-Agnostic ── 动态负载均衡
  │
2021  Cuttlesim ── 高层语义编译优化
  │
2023  Manticore ─── 225核FPGA BSP（27.9x）
  │    ASH ───────── 256核数据流（1485x）
  │    Khronos ───── 内存融合（2-4x）
  │    RepCut ────── 复制辅助划分（超线性）
  │    Metro-MPI ─── 10B晶体管混合并行
  │
2024  BatchSim ──── 跨周期批处理
  │    TaroRTL ───── 协程异构调度
  │    Deduplication ─ 粗粒度去重
  │    FireAxe ───── 多FPGA划分
  │    GL0AM ─────── GPU重仿真（4-76x）
  │
2025  Parendi ───── 千核BSP静态调度
  │    GEM ───────── GPU模拟器启发式（64x）
  │    GATSPI ────── 数据流（1993x）
  │    GSIM ──────── 大规模混合策略
  │
      ↓
   【下一代多线程RTL仿真器】← 你的位置
```

### 4.3 自研方法映射：任务粒度（MAXMT）的解析预测（2026-08-30，提交 114fec0）

**学术问题归类**：静态任务图划分的粒度选择 = 经典 makespan/装箱理论中的"任务粒度-同步开销权衡"（cf. Parendi 的静态 BSP 调度、Verilator 4.0 的 mtask 划分、French et al. 1995 的调度静态化）。文献中该超参数普遍靠手工扫描或默认启发式（gsim/Verilator 均为 50×threads）；我们的贡献是**发射前解析预测**：

**方法**：层级同步执行器的周期时间下界为

$$T_{cycle}(N) \approx \tau_w \cdot \underbrace{\sum_{L} \max_{w}(\text{work}[L][w])}_{\text{lvlSum}} + \tau_s \cdot E_{cross}(N) + c_0 N$$

其中 N 为任务数（MAXMT 控制收缩终点）。lvlSum（各层 straggler 之和）随 N 递减（装箱更匀），cross 同步项随 N 递增——U 形曲线的最低点即最优粒度。lvlSum 可在代码发射前从调度结构（Kahn 分层 + 静态指派）直接算出。

**系统**：`GSIM_MT_DENSE_VCONTRACT_MAXMT_AUTO=1` 生成内探针——对候选梯度逐个从 pristine 副本重跑收缩、按 lvlSum 排序。成本 +2~5 分钟生成时间、零构建零测量。

**实证**（双 RTL 交错扫描验证）：
- v86-T16：lvlSum argmin = 1200 = 实测最优**零拟合精确命中**（默认 800 差 11.4%）
- kunminghu-v3-T16：选 1600，距实测最优 2000 约 1-3%
- 反例教训：全局 maxW+cross 地板两项两 RTL 均排错；带回归系数的墙时拟合不跨图泛化（LORO 双向失败）——**层级结构是必要物理量**，回归系数不是
- 已知局限：有界 lookahead 会拯救被层级地板高估的调度（只高估不低估）；协议上取 top-2 实测确认兜底

**学术定位**：与 Partition-Agnognostic/Beamer & Donofrio 的"活动因子感知"互补——他们解决时间维（负载何时变），我们解决结构维（图形状决定的粒度最优点）；两者都指向"仿真器超参数应从问题结构解析推导而非扫描"这一新兴方向。

---

## 五、可操作建议

### 5.1 技术选型决策树

```
┌─────────────────────────────────────────┐
│   你的场景是什么？                         │
└─────────────────────────────────────────┘
              │
    ┌─────────┴─────────┐
    ▼                   ▼
  快速迭代/调试        批量回归测试
  （每天编译>10次）    （每晚跑数千测试）
    │                   │
    ▼                   ▼
  软件多线程仿真器      GPU加速（RTLFlow/GEM）
  Verilator 4.0+改进    或 FPGA（FireSim）
    │                   │
    ▼                   ▼
  重点：静态调度+       重点：批量刺激+
  复制辅助划分           内存布局优化
    │
    ▼
  核数>32？
    │
  ┌─┴─┐
  ▼   ▼
  是   否
  │    │
  ▼    ▼
  Parendi  RepCut+
  静态BSP  动态混合
  思想     调度
```

### 5.2 参考论文复现路线

#### 阶段一：单核性能基线（1-2周）

1. **Verilator 4.0 多线程基线**
   - 目标：复现2-8核的线性加速，确认>8核后的扩展瓶颈
   - 工具：Verilator 5.x + OpenCore/BOOM设计
   - 验证点：pthread barrier开销占比、各核负载均衡度

2. **Khronos 内存融合**
   - 目标：在单核Verilator上复现2-4x加速
   - 工具：[ksim](https://github.com/pku-liang/ksim) 开源代码
   - 验证点：流水线设计的缓存访问减少比例（目标70-95%）

#### 阶段二：多线程扩展性（2-4周）

3. **RepCut 复制辅助划分**
   - 目标：在8核上实现超线性加速（>8x）
   - 关键：实现复制代价模型，允许少量节点复制到多个分区
   - 验证点：复制节点比例（通常<5%）、缓存未命中减少比例

4. **BatchSim 跨周期批处理**
   - 目标：合并无依赖的连续周期，减少barrier频率
   - 关键：静态分析跨周期数据依赖，构建安全批处理窗口
   - 验证点：批处理窗口平均长度、同步开销降低比例

#### 阶段三：前沿探索（4-8周）

5. **TaroRTL 协程调度**
   - 目标：用C++20协程替代pthread，降低任务切换开销
   - 关键：将RTL eval任务分解为可挂起的coroutine
   - 验证点：协程切换延迟 vs 线程切换延迟（目标降低10x+）

6. **Parendi 静态BSP调度**
   - 目标：在>32核上实现可扩展的加速
   - 关键：编译时构建完整DAG并静态分配，消除运行时调度器
   - 验证点：核数从32扩展到256时的加速比曲线

### 5.3 推荐阅读顺序

| 优先级 | 论文 | 阅读目的 | 预计时间 |
|--------|------|----------|----------|
| P0 | Verilator 4.0 (ORConf'18) | 理解开源多线程基线实现 | 2h |
| P0 | RepCut (ASPLOS'23) | 复制辅助划分，最直接的改进思路 | 4h |
| P1 | Khronos (MICRO'23) | 内存融合，单核到多核均可受益 | 4h |
| P1 | Tango (DATE'20) | JIT编译优化，与多线程正交叠加 | 3h |
| P1 | BatchSim (ISVLSI'24) | 跨周期批处理，减少同步开销 | 3h |
| P2 | Parendi (ASPLOS'25) | 千核静态调度，扩展性理论上限 | 4h |
| P2 | Manticore (ASPLOS'24) | 专用硬件-编译器协同设计参考 | 4h |
| P2 | ASH (MICRO'23) | 数据流+选择性事件驱动，终极形态 | 4h |
| P3 | FireSim (ISCA'18) | FPGA加速实用方案，理解工程权衡 | 3h |
| P3 | TaroRTL (Euro-Par'24) | 协程异构调度，前沿方向 | 3h |

---

## 原文摘录

> "Despite the parallel nature of hardware, existing parallel RTL simulators yield speedups that are far from the ideal. RepCut is enabled by our replication-aided partitioning, which allows a small number of nodes to be replicated across partitions to break critical cross-partition dependencies." — RepCut (ASPLOS 2023)

> "Manticore uses a static bulk-synchronous parallel (BSP) execution model to eliminate fine-grain synchronization overhead. It relies entirely on a compiler to schedule resources and communication." — Manticore (ASPLOS 2024)

> "Parendi considers the problem of parallelizing RTL simulation of large designs across a few thousand cores, using partitioning and compilation techniques and carefully quantifying the synchronization, communication, and computation costs." — Parendi (ASPLOS 2025)

> "An ASH chip with 256 simple cores is gmean 1,485x faster than 1-core Verilator, and it is 32x faster than parallel Verilator on a server CPU with 32 complex cores, while using 3x less area." — ASH (MICRO 2023)

> "Khronos can save up to 88% of cache access and achieve an average acceleration of 2.0x (up to 4.3x) for various hardware designs compared to state-of-the-art simulators." — Khronos (MICRO 2023)

> "Tango achieves a 6x average speedup compared to the state-of-the-art simulators." — Tango (DATE 2020)

---

## 相关链接

- [Parendi arXiv](https://arxiv.org/abs/2403.04714)
- [RepCut ACM DL](https://dl.acm.org/doi/abs/10.1145/3582016.3582034)
- [Manticore arXiv](https://arxiv.org/abs/2301.09413)
- [Manticore ETHZ 项目页](https://systems.ethz.ch/research/compass/manticore_hardware_accelerated_rtl_simulation.html)
- [Partition-Agnostic Gate-Level Simulation (DAC 2023)](https://doi.org/10.1145/3581750)
- [TaroRTL (Euro-Par 2024)](https://link.springer.com/chapter/10.1007/978-3-031-69583-4_11)
- [BatchSim (ISVLSI 2024)](https://ieeexplore.ieee.org/abstract/document/10682648/)
- [Coarse-Grained Deduplication (ASPLOS 2024)](https://doi.org/10.1145/3622781.3674184)
- [Metro-MPI (DATE 2023)](https://ieeexplore.ieee.org/abstract/document/10137080/)
- [FireSim 项目主页](https://fires.im)
- [FireSim GitHub](https://github.com/firesim/firesim)
- [ASH (MICRO 2023)](https://doi.org/10.1145/3613424.3614257)
- [Khronos GitHub (ksim)](https://github.com/pku-liang/ksim)
- [From RTL to CUDA (ICPP 2022)](https://doi.org/10.1145/3545008.3545091)
- [GATSPI (DAC 2022)](https://doi.org/10.1145/3489517.3530585)
- [GL0AM (ICCAD 2024)](https://doi.org/10.1145/3676536.3676675)
- [GEM (DAC 2025)](https://doi.org/10.1109/DAC63849.2025.11132713)
- [Cuttlesim (ASPLOS 2021)](https://doi.org/10.1145/3445814.3446720)
- [Tango (DATE 2020)](https://doi.org/10.23919/DATE48585.2020.9116253)
- [LECSIM (DAC 1990)](https://doi.org/10.1145/123186.123349)
- [SSIM (DAC 1987)](https://doi.org/10.1145/37888.37890)
- [Low Activity Factor RTL Acceleration (DAC 2020)](https://doi.org/10.1145/3379137.3380762)
- [Verilator 4.0 Multithreaded (ORConf 2018)](https://veripool.org/papers/Verilator_v4_Multithreaded_OrConf2018.pdf)

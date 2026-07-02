---
title: "KaHyPar 参数调优与配置详解"
description: "Mt-KaHyPar 的 preset 配置体系、coarsening / initial partitioning / refinement 参数含义、以及针对 RTL 电路分区的调优建议"
source_url: "https://github.com/kahypar/mt-kahypar/tree/master/config"
source_type: "github"
author: "Sebastian Schlag, Lars Gottesbüren, Tobias Heuer et al. (Karlsruhe Institute of Technology)"
date: "2025-02-11"
tags: ["KaHyPar", "参数调优", "preset", "coarsening", "refinement", "FM", "flow", "质量指标"]
keywords: ["default_preset.ini", "quality_preset", "highest_quality", "coarsening threshold", "refinement rounds", "V-cycle", "parameter tuning"]
capture_date: "2025-01-20"
---

# KaHyPar 参数调优与配置详解

## 来源

- URL: <https://github.com/kahypar/mt-kahypar/tree/master/config>
- 类型: github / 论文
- 作者: KIT 算法工程组
- 日期: 2025-02-11
- 相关论文: "Network Flow-Based Refinement for Multilevel Hypergraph Partitioning" (ALENEX'18), "Deterministic Parallel High-Quality Hypergraph Partitioning" (2025), "Asynchronous n-Level Hypergraph Partitioning" (2023)

## 摘要

Mt-KaHyPar 提供 6 种内置 preset（`default`, `quality`, `highest_quality`, `deterministic`, `deterministic_quality`, `large_k`），每种对应不同的 coarsening、initial partitioning、refinement 策略组合。
本文档基于官方 `config/*.ini` 文件和参数调优论文，详细解析各阶段关键参数的含义与默认值，并给出针对 RTL 电路分区场景的调优建议。

## 关键要点

- **Preset 质量等级**: `large_k` < `default` < `deterministic` < `quality` < `deterministic_quality` < `highest_quality`。
- **Coarsening 阶段**: 控制超图收缩到最粗层的速度；`c-t` 定义最粗层节点数阈值，`c-s` 控制重节点惩罚，直接影响初始解质量。
- **Refinement 阶段**: `default` 使用 unconstrained FM（快速），`quality` / `highest_quality` 加入 flow-based refinement（高质量但慢）。
- **V-cycle**: 通过 `improve_partition()` 在已有分区上执行额外的多轮改进，适合 RTL 仿真器对同一设计多次迭代调优。
- **确定性模式**: `deterministic` 和 `deterministic_quality` 保证相同输入和 seed 产生相同输出，适合需要可重复分区的 CI/CD 场景。
- **与 hMetis / PaToH 对比**: KaHyPar-MF 在 ISPD98 等电路基准集上比 hMetis-R 平均提升 13-21% 的解质量。

## 对 RTL 仿真器多线程化的启示

在 RTL 多线程仿真器的设计中，划分质量直接决定跨线程通信量（cut-net），进而影响同步开销。
- 对 **小规模设计**（<10 万门）：使用 `default` preset，快速得到可接受解。
- 对 **大规模 SoC**（百万门级）：使用 `quality` preset，牺牲划分时间换取更少的跨线程信号线。
- 对 **需要确定性回归测试** 的场景：使用 `deterministic` preset，确保每次代码修改后分区结果一致。
- 对 **多 FPGA 原型验证**（k >= 1024）：使用 `large_k` preset。

## 原文摘录

### 1. Preset 概览与选择策略

> 来自 Mt-KaHyPar README.md

```bash
# 默认配置，最快
./MtKaHyPar -h netlist.hgr --preset-type=default -t 8 -k 4 -e 0.03 -o km1

# 高质量，使用 flow-based refinement
./MtKaHyPar -h netlist.hgr --preset-type=quality -t 8 -k 4 -e 0.03 -o km1

# 最高质量，使用 n-level coarsening + flow-based refinement
./MtKaHyPar -h netlist.hgr --preset-type=highest_quality -t 8 -k 4 -e 0.03 -o km1

# 确定性分区
./MtKaHyPar -h netlist.hgr --preset-type=deterministic -t 8 -k 4 -e 0.03 -o km1

# 大 k 值（k >= 1024）
./MtKaHyPar -h netlist.hgr --preset-type=large_k -t 8 -k 1024 -e 0.03 -o km1
```

| Preset | 特点 | 推荐场景 |
|--------|------|----------|
| `large_k` | 最快，质量最低 | k >= 1024 的多 FPGA 划分 |
| `default` | 快速，质量良好 | 日常开发、快速迭代 |
| `deterministic` | 快速且结果可复现 | CI/CD 回归测试 |
| `quality` | 使用 flow-based refinement | 生产环境最终分区 |
| `deterministic_quality` | 高质量 + 可复现 | 需要确定性的生产环境 |
| `highest_quality` | n-level + flow，最慢 | 对质量极端敏感的场景 |

### 2. Default Preset 完整配置解析

> 来自 `config/default_preset.ini`

```ini
# === general ===
mode=direct
preset-type=default
maxnet-removal-factor=0.01
smallest-maxnet-threshold=50000
maxnet-ignore=1000
num-vcycles=0

# === main -> shared_memory ===
s-use-localized-random-shuffle=false
s-static-balancing-work-packages=128

# === main -> preprocessing -> community_detection ===
p-enable-community-detection=true
p-louvain-edge-weight-function=hybrid
p-max-louvain-pass-iterations=5
p-louvain-min-vertex-move-fraction=0.01
p-vertex-degree-sampling-threshold=200000

# === main -> coarsening ===
c-type=multilevel_coarsener
c-use-adaptive-edge-size=true
c-min-shrink-factor=1.01
c-max-shrink-factor=2.5
c-s=1
c-t=160
c-vertex-degree-sampling-threshold=200000

# === main -> coarsening -> rating ===
c-rating-score=heavy_edge
c-rating-heavy-node-penalty=no_penalty
c-rating-acceptance-criterion=best_prefer_unmatched

# === main -> initial_partitioning ===
i-mode=rb
i-runs=20
i-use-adaptive-ip-runs=true
i-min-adaptive-ip-runs=5
i-perform-refinement-on-best-partitions=true
i-remove-degree-zero-hns-before-ip=true
i-fm-refinement-rounds=1
i-lp-maximum-iterations=20
i-lp-initial-block-size=5

# === main -> initial_partitioning -> refinement -> fm ===
i-r-fm-type=kway_fm
i-r-fm-multitry-rounds=5
i-r-fm-rollback-parallel=true
i-r-fm-rollback-balance-violation-factor=1
i-r-fm-seed-nodes=25
i-r-fm-obey-minimal-parallelism=false
i-r-fm-release-nodes=true
i-r-fm-time-limit-factor=0.25
i-r-fm-iter-moves-on-recalc=true

# === main -> refinement -> fm ===
r-fm-type=unconstrained_fm
r-fm-multitry-rounds=10
r-fm-unconstrained-rounds=8
r-fm-rollback-parallel=true
r-fm-rollback-balance-violation-factor=1.0
r-fm-threshold-border-node-inclusion=0.7
r-fm-imbalance-penalty-min=0.2
r-fm-imbalance-penalty-max=1.0
r-fm-seed-nodes=25
r-fm-release-nodes=true
r-fm-min-improvement=-1.0
r-fm-unconstrained-min-improvement=0.002
r-fm-obey-minimal-parallelism=true
r-fm-time-limit-factor=0.25

# === main -> refinement -> flows ===
r-flow-algo=do_nothing
```

### 3. 关键参数详解

#### Coarsening 参数

| 参数 | 默认值 | 含义 | RTL 调优建议 |
|------|--------|------|-------------|
| `c-type` | `multilevel_coarsener` | 收缩器类型 | 保持默认；`nlevel_coarsener` 在 `highest_quality` 中使用 |
| `c-s` | 1 | 重节点惩罚系数 | 若 RTL 中某些模块权重极大（如大型 RAM），可适当增大 |
| `c-t` | 160 | 最粗层节点数阈值 | 对 k-way 划分，最粗层保留约 `k * c-t` 个节点；增大可改善初始解但增加时间 |
| `c-min-shrink-factor` | 1.01 | 每层最小收缩因子 | 若超图本身很稀疏，可适当降低以允许更细粒度收缩 |
| `c-max-shrink-factor` | 2.5 | 每层最大收缩因子 | 控制收缩速度，保持默认即可 |
| `c-rating-score` | `heavy_edge` | 评分函数 | `heavy_edge` 对电路网表效果良好；`sameness` 适合社区结构明显的设计 |
| `c-rating-acceptance-criterion` | `best_prefer_unmatched` | 匹配策略 | 优先选择未匹配顶点，有助于保持平衡 |

#### Initial Partitioning 参数

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `i-mode` | `rb` | 递归二分（recursive bisection）或 `direct` k-way |
| `i-runs` | 20 | 初始划分的重复运行次数 |
| `i-use-adaptive-ip-runs` | true | 自适应调整运行次数 |
| `i-min-adaptive-ip-runs` | 5 | 最少运行次数 |
| `i-fm-refinement-rounds` | 1 | 初始划分阶段的 FM 改进轮数 |

#### Refinement 参数

| 参数 | 默认值 (default) | 含义 | RTL 调优建议 |
|------|-----------------|------|-------------|
| `r-fm-type` | `unconstrained_fm` | FM 类型 | `unconstrained` 允许暂时违反平衡约束，更易找到优质解 |
| `r-fm-multitry-rounds` | 10 | 每轮 FM 的尝试次数 | 增大可提升质量但增加时间；RTL 场景建议 10-20 |
| `r-fm-unconstrained-rounds` | 8 | 无约束 FM 轮数 | 保持默认 |
| `r-fm-seed-nodes` | 25 | 每次 FM 搜索的种子数 | 对大规模电路可适当增大到 50-100 |
| `r-fm-time-limit-factor` | 0.25 | FM 时间限制因子 | 减小可加速，增大可提升质量 |
| `r-flow-algo` | `do_nothing` | 流式改进算法 | `default` 关闭；`quality` preset 启用 `flow_cutter` 或 `whfc` |
| `r-rebalancer-type` | `advanced_rebalancer` | 重平衡器 | 保持默认 |

### 4. Quality Preset 与 Flow-Based Refinement

> 来自 `config/quality_preset.ini` 的核心差异（与 default 对比）

`quality` preset 在 refinement 阶段启用 **flow-based refinement**（网络流改进），使用 `do_nothing` 之外的具体流算法（如 `whfc` 或 `flow_cutter`）。

Flow-based refinement 的基本思想：
1. 在分区的边界区域识别两个相邻块；
2. 构建一个 **flow network**，将超边转换为边、节点容量对应顶点权重；
3. 计算最小割以重新分配边界节点，从而降低全局目标函数。

这种方法在 VLSI 网表上效果显著，因为电路网表的局部边界通常包含大量可重新分配的小型逻辑门。

### 5. 参数调优实验结果

> 来自论文 "Algorithm Configuration for Hypergraph Partitioning" (C. Öhl, 2018)

**Coarsening 调优参数范围**：
- `ict` (初始划分器最粗层节点数): [5, 200]
- `ct` (主划分器最粗层节点数): [0, 150]
- `s` (重节点惩罚): [1, 7]，步长 1/4

**Initial Partitioning 调优**：
- 运行次数 (`i-runs`): [1, 100]，对数效应递减

**实验结论**：
- 经过 SMAC 自动调优后，KaHyPar 的运行时间比默认配置减少约 **30%**，而质量基本保持不变；
- 调优后的配置在 Pareto 前沿上优于 hMetis 和 PaToH；
- 针对特定领域（如电路网表）的 **实例调优** 比通用调优效果更好。

### 6. 与 hMetis / PaToH / Metis 的性能对比

> 来自 "Network Flow-Based Refinement for Multilevel Hypergraph Partitioning" (KaHyPar-MF, ALENEX'18)

| 算法 | 相对 KaHyPar-MF 的质量差距 | 备注 |
|------|---------------------------|------|
| KaHyPar-CA | +2.44% | 社区感知 coarsening |
| hMetis-R | +13.61% | 递归二分 |
| hMetis-K | +13.23% | k-way |
| PaToH-Q | +8.67% | 质量模式 |
| PaToH-D | +14.35% | 默认模式 |

在 ISPD98 电路基准集上，KaHyPar-MF 比 hMetis-R 提升 **1.6%-3.89%**；在更大的 SPM 和 WebSoc 数据集上，优势扩大到 **16%-41%**。

> 来自 "Deterministic Parallel High-Quality Hypergraph Partitioning" (Jet, 2025)

DetJet（确定性 Jet refinement）在超图上质量与 Mt-KaHyPar 非确定性默认模式相当，但在不规则图上比 Mt-KaHyPar-SDet 提升 **1.18×**（几何均值），对 irregular graph 提升 **1.42×**。

### 7. RTL 电路分区调优建议

#### 针对 RTL 网表的超图特性：
1. **超边大小分布极不均匀**：时钟线、复位线可能连接数万个节点；普通数据信号仅连接 2-5 个节点。
2. **节点权重差异大**：小型逻辑门 vs 大型 RAM/乘法器。
3. **社区结构明显**：模块化设计（module hierarchy）天然形成社区。

#### 具体调优配置：

```ini
; RTL 专用配置（基于 default 调优）

; === preprocessing ===
p-enable-community-detection=true
p-louvain-edge-weight-function=hybrid
; 电路网表社区检测效果很好，保持开启

; === coarsening ===
c-t=200
; 增大最粗层节点数，给初始划分更多空间
c-s=2
; 增大重节点惩罚，防止大型模块被过早合并
c-rating-score=heavy_edge
; heavy_edge 对带权超边效果最佳
c-rating-acceptance-criterion=best_prefer_unmatched
; 优先未匹配，保持负载平衡

; === initial partitioning ===
i-runs=30
; 初始划分增加尝试次数，RTL 初始解质量很重要
i-use-adaptive-ip-runs=true

; === refinement ===
r-fm-multitry-rounds=15
; 增加 FM 尝试次数
r-fm-seed-nodes=50
; 增大种子数，覆盖更多边界节点
r-fm-unconstrained-min-improvement=0.001
; 降低改进阈值，允许更精细的调整

; === objective ===
; 对 RTL 仿真器，优先使用 KM1（connectivity-1）
; 因为它比 cut-net 更能反映跨线程通信代价
```

#### 不平衡度 (epsilon) 选择：
- **标准场景**: `0.03` (3%)
- **异构负载场景**: `0.05` 到 `0.10`，允许更多灵活性以容纳大型模块
- **严格平衡场景**: `0.01`，但需要配合自定义块权重使用

#### 目标函数选择：
- **`KM1`** (connectivity-1): **推荐**。最小化跨分区信号线的总"连接数-1"，直接对应 RTL 仿真中的跨线程通信事件数。
- **`CUT`** (cut-net): 最小化被切开的超边数量。适合需要最小化"需要同步的不同信号数"的场景。
- **`SOED`** (sum of external degrees): 最小化外部度之和。适合关注总通信带宽的场景。

## 相关链接

- [Mt-KaHyPar config 目录](https://github.com/kahypar/mt-kahypar/tree/master/config)
- [Algorithm Configuration for Hypergraph Partitioning (C. Öhl, 2018)](https://schulzchristian.github.io/thesis/ba_oehl.pdf)
- [Network Flow-Based Refinement for Multilevel Hypergraph Partitioning (ALENEX'18)](https://arxiv.org/pdf/1802.03587)
- [Deterministic Parallel High-Quality Hypergraph Partitioning (2025)](https://arxiv.org/html/2504.12013v2)
- [Asynchronous n-Level Hypergraph Partitioning (2023)](https://ae.iti.kit.edu/documents/theses/Asynchronous_n-Level_Hypergraph_Partitioning.pdf)
- [Engineering Learned Heuristics to Improve Clustering (SEA 2026)](https://drops.dagstuhl.de/storage/00lipics/lipics-vol371-sea2026/LIPIcs.SEA.2026.25/LIPIcs.SEA.2026.25.pdf)

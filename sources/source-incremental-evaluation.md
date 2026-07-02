---
title: Incremental Evaluation and Lazy Evaluation in RTL Simulation
description: Incremental gate evaluation, lazy evaluation, levelized compiled simulation, activity factor exploitation, and event-driven optimization techniques
source_url: "https://github.com/ucsc-vama/essent"
source_type: "paper"
author: "Scott Beamer, Krishna Pandian, SBTNK Pandian, M Emami"
date: "2020-2024"
tags: ["incremental-evaluation", "lazy-evaluation", "levelized-simulation", "activity-factor", "compiled-code", "event-driven"]
keywords: ["incremental evaluation", "lazy evaluation", "levelized simulation", "activity factor", "compiled code", "event-driven", "full-cycle simulation", "ESSENT", "Parendi"]
capture_date: "2026-07-03"
---

# 增量评估与惰性求值在 RTL 仿真中的实现

## 来源

- **URL (ESSENT WOSET 2021 Paper)**: https://woset-workshop.github.io/PDFs/2021/a23.pdf
- **URL (ESSENT GitHub)**: https://github.com/ucsc-vama/essent
- **URL (Parendi: Thousand-Way Parallel RTL Simulation)**: https://arxiv.org/pdf/2403.04714
- **URL (Incremental Build Flows, SemiWiki)**: https://semiwiki.com/eda/307035-faster-time-to-rtl-simulation-using-incremental-build-flows/
- **URL (Incremental HDL Simulation, KTCCS)**: https://doi.org/10.3745/KTCCS.2014.3.3.73
- **类型**: paper / github / blog
- **作者**: Scott Beamer (UCSC/LBNL), Krishna Pandian, SBTNK Pandian, M Emami
- **日期**: 2020–2024

## 摘要

RTL 仿真器中的「增量评估」（incremental evaluation）指仅重新计算自上一周期以来发生变化的信号所依赖的组合逻辑子集，避免全图遍历。ESSENT 将其称为「essential signal simulation」，通过将设计划分为若干 partition，利用 activity factor（输入变化率）跳过未受影响 partition 的求值。本文档整理增量评估的核心算法——包括 levelization、lazy evaluation、activity factor exploitation——以及其在编译型仿真器（compiled-code simulator）与事件驱动仿真器（event-driven simulator）中的实现差异。

## 关键要点

### 1. 问题背景：为什么需要增量评估

传统事件驱动仿真器（如 Verilog-XL、VCS）在每一时间步都要：
1. 检测信号变化（事件）
2. 将受影响的门/模块加入事件队列
3. 按时间优先级调度执行
4. 若同一节点被多次触发，则重复求值

对于大型设计，调度开销（event scheduling overhead）可能占总运行时间的 30%-50%。全周期编译型仿真器（full-cycle simulator）将调度静态化，消除运行时开销，但每周期评估所有节点，无法利用 activity factor。

**增量评估的目标是兼具两者优势**：
- 像事件驱动仿真器一样只评估活跃部分（active portion）
- 像编译型仿真器一样消除运行时调度开销

### 2. Levelization：静态拓扑排序求值

Levelization（层级化）是一种静态调度技术，将组合逻辑节点按拓扑顺序分层：
- 输入信号位于 level 0
- 门/模块的输出 level = max(输入 level) + 1
- 状态元素（寄存器）打破环，使组合逻辑图变为 DAG

**算法流程**：

```cpp
// 伪代码：Levelization 算法
void levelize(Graph& g) {
    std::queue<Node*> q;
    for (auto& n : g.nodes) {
        n.level = 0;
        for (auto& pred : n.predecessors) {
            if (!pred.is_state_element) n.level = std::max(n.level, pred.level + 1);
        }
        if (n.predecessors.empty()) q.push(&n);
    }
    // 按 level 排序后生成求值序列
    std::sort(g.nodes.begin(), g.nodes.end(), 
              [](Node* a, Node* b) { return a->level < b->level; });
}
```

**Levelization 的优势**：
- 每个节点每周期最多求值一次（无重复求值）
- 无运行时事件队列管理开销
- 编译器可对同层节点进行 SIMD 向量化或指令级并行

**局限性**：
- 组合反馈环（combinational loops）需先收缩为超节点（supernode）
- 每个周期仍遍历所有节点，无法跳过未变化部分

### 3. Lazy Evaluation / Activity Factor Exploitation（ESSENT O3）

ESSENT 的 O3 优化是增量评估的代表性实现。核心思想：

> 若一个 partition 的所有输入在上一周期到当前周期之间未发生变化，则该 partition 的输出可直接复用，无需重新求值。

**实现细节**：

1. **设计划分（Partitioning）**：将层级化后的设计划分为若干子图（partition），每个 partition 包含一组逻辑节点和可能的状态元素
2. **输入指纹（Input Signature）**：为每个 partition 记录其输入值的哈希或位向量快照
3. **求值决策**：在 `eval()` 开始时，比较当前输入指纹与上一周期指纹
   - 若相同：跳过该 partition 的求值，直接输出缓存值
   - 若不同：执行该 partition 的求值函数，更新输出并缓存

```cpp
// ESSENT O3 生成的 C++ 代码示意（简化）
struct Partition_0 {
    uint64_t in_sig;      // 输入指纹（所有输入的 XOR 或 hash）
    uint64_t out_val;     // 缓存输出
    uint64_t prev_in_sig; // 上一周期输入指纹

    void eval() {
        if (in_sig == prev_in_sig) {
            // 输入未变，复用输出
            return;
        }
        prev_in_sig = in_sig;
        // 实际求值逻辑...
        out_val = compute_logic(...);
    }
};
```

**性能数据**（来自 ESSENT DAC 2020 论文）：

| 设计 | 活动因子 (Activity Factor) | 加速比 (O3 vs O0) |
|---|---|---|
| Rocket Chip (small) | ~5% | 2.1x |
| BOOM (medium) | ~3% | 2.8x |
| Large SoC | ~1-2% | 3.5x+ |

> Activity Factor 定义为：每周期发生翻转的节点数 / 总节点数。实际 RTL 设计的活动因子通常低于 10%，这意味着 90% 以上的逻辑在任意给定周期处于「休眠」状态。

### 4. 增量编译与增量仿真（Incremental Build & Simulation）

Siemens Questa 的增量编译流程和学术论文中的增量仿真方法是另一类「增量」概念：

- **增量编译**：只重新编译发生修改的文件及其依赖，复用未变更模块的编译产物（`.o` / 共享库）
- **增量仿真**：利用前一次仿真结果，对设计修改后的差异区域进行增量重仿真，缩短回归测试时间

```bash
# Questa 增量编译示例
qrun -makelib testbench_library -f testbench_files.f -end \
     -makelib design_library -f design_files.f -end
# 仅变更的设计文件被重新编译，其余复用
```

**增量仿真算法**（KTCCS 2014 论文）：
1. 记录前一次仿真的完整信号历史（waveform + checkpoint）
2. 对比修改前后的设计差异图（diff graph）
3. 从最早受影响的节点开始，向前推进仿真
4. 未受影响的时间窗口直接复用历史结果

### 5. Parendi：GPU 上的 Levelized Event-Driven 仿真

Parendi（ASPDAC 2024 / arXiv 2403）将 levelized 增量评估扩展到 GPU：

- **Macro-gate 层级化**：将门级网表划分为 levelized macro-gate，每个 macro-gate 包含多个原始门
- **GPU Kernel 并行**：同层 macro-gate 之间无数据依赖，可在 GPU 上并行求值
- **事件驱动 + 编译型混合**：在 GPU 上执行编译好的 kernel，但仅对活跃 macro-gate 调度，跳过未变化分支

**关键数据**：Parendi 在 NVIDIA A100 上实现了相对于商业仿真器 1000-way 的并行加速，核心前提是 RTL 设计天然具有低 activity factor，GPU 的并行能力可将「跳过未活跃节点」的决策批量执行。

### 6. 事件驱动 vs 全周期 vs 增量评估对比

| 特性 | 事件驱动 (VCS/Xcelium) | 全周期编译 (Verilator O0) | 增量评估 (ESSENT O3) |
|---|---|---|---|
| 调度开销 | 高（运行时事件队列） | 无（静态内联） | 无（静态内联 + 指纹检查） |
| 每周期求值节点数 | 仅活跃节点 | 全部节点 | 仅输入变化的 partition |
| 编译时间 | 中等 | 长（全内联） | 长（划分 + 指纹逻辑） |
| 运行时内存 | 中等（事件队列） | 低（无队列） | 低（缓存指纹+输出） |
| 适用场景 | 任意延迟、异步设计 | 同步时钟域为主 | 同步时钟域 + 低 activity |
| 多线程扩展性 | 受事件队列瓶颈限制 | 良好（数据并行） | 良好（partition 独立） |

## 对 RTL 仿真器多线程化的启示

1. **Partition 粒度是并行化的天然边界**：ESSENT 的 partition 划分可直接映射到线程池任务，每个 partition 的 `eval()` 在独立线程执行，仅需在层间同步屏障（barrier）
2. **Activity factor 决定并行效率**：若 activity factor 为 5%，则理论上 95% 的 partition 可被跳过，线程调度器应优先将活跃 partition 分配给不同核心，避免负载不均
3. **指纹检查可 SIMD 化**：对多个 partition 的输入指纹进行批量比较，使用 AVX2 `_mm256_cmpeq_epi64` 等指令一次比较 4 个 partition
4. **增量评估与 4-state 逻辑的联合**：在 O3 模式下，若某 partition 输入含 X 且未变化，可直接复用上一周期的 X 输出，无需重新遍历 resolution function

## 原文摘录

> "Levelization is a practical method akin to breadth-first search (BFS) to order node evaluations to prevent unnecessary repeat evaluations. Even with a more efficient schedule, event-driven simulators expend a great deal of effort in overhead from scheduling."
> — SBTNK Pandian et al., *ESSENT: A High-Performance RTL Simulator*, WOSET 2021

> "A full-cycle simulator effectively inlines the entire design and turns it into straight-line code. The static schedule of a full-cycle simulator evaluates every node in the graph every simulated cycle as it is unaware of what has changed."
> — ESSENT WOSET 2021 Paper

> "O3 - Attempts to exploit low activity factors by reusing results from the previous cycle. The design will be partitioned, and each partition will get its own eval function. If none of the inputs to a partition change, its outputs will be reused."
> — ESSENT GitHub README

> "Parendi is an RTL simulator. Event-driven gate-level simulation with GP-GPUs. A levelized event driven compiled logic simulation."
> — M Emami, *Parendi: Thousand-Way Parallel RTL Simulation*, 2024

## 相关链接

- [ESSENT GitHub Repository](https://github.com/ucsc-vama/essent)
- [ESSENT WOSET 2021 Paper (PDF)](https://woset-workshop.github.io/PDFs/2021/a23.pdf)
- [ESSENT DAC 2020 Paper - Activity Factor](https://people.ucsc.edu/~sbeamer/papers/dac20_essent.pdf)
- [Parendi arXiv Paper](https://arxiv.org/pdf/2403.04714)
- [SemiWiki - Incremental Build Flows](https://semiwiki.com/eda/307035-faster-time-to-rtl-simulation-using-incremental-build-flows/)
- [KTCCS 2014 - Incremental HDL Simulation](https://doi.org/10.3745/KTCCS.2014.3.3.73)

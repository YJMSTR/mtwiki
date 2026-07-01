---
id: "wiki-sparse-parallelization"
title: "稀疏计算并行化策略"
description: "分析稀疏计算RTL仿真中如何有效并行化，对比静态分区与动态调度、时间片并行与空间分区、粗粒度与细粒度同步策略"
tags: ["rtl-sim", "sparse-computation", "parallelization", "partitioning", "scheduling"]
keywords: ["稀疏计算", "静态分区", "动态调度", "时间片并行", "空间分区", "macro-task", "micro-task"]
related_sources:
  - "source-verilator-issue-2913"
  - "source-verilator-v3variableorder"
  - "source-metro-mpi"
  - "source-pdes-rtlsim-modern"
last_updated: "2026-07-01"
---

# 稀疏计算并行化策略

## 稀疏计算并行的特殊挑战

稀疏计算RTL仿真器的核心特征是：每个时钟周期内，只有极少量信号发生翻转，大部分电路处于静态。这种稀疏性在单线程下是巨大优势（只需遍历活跃区域），但在多线程下却成为最大障碍——计算量不足以摊平同步开销。

Verilator Issue #2913 的教训表明，一个32-bit Fibonacci生成器（极小活跃计算量）在4线程下性能退化4倍。这揭示了一个关键原则：

> **并行化策略必须与每周期活跃计算量动态匹配，不能一刀切。**

## 策略一：静态分区 vs 动态调度

### 静态分区（Static Partitioning）

**原理**：在编译时根据电路结构将RTL设计划分为若干固定区域，每个区域绑定到一个线程。

**典型实现**：
- Verilator的V3Partition/V3Order：将语句级依赖图通过边收缩（edge contraction）粗化为数十个macro-task，静态映射到线程
- Parendi的METIS风格图划分：将RTL纤维（fibers）分区到IPU tile上，最小化通信量
- Metro-MPI的NoC-based分区：利用SoC的自然边界（tile-tile连接）将设计分成分布式进程

**优点**：
- 运行时零调度开销，无需复杂的动态负载均衡逻辑
- 确定性执行，易于调试和复现
- 可以基于编译时分析优化局部性（如V3VariableOrder按MTask亲和性排列变量）

**缺点**：
- 无法适应运行时的活跃信号分布变化。如果某周期活跃区域集中在某个分区，对应线程满载而其他线程空转
- 分区边界上的信号需要跨线程同步，产生固定通信开销
- 对于稀疏计算，静态分区可能产生大量空转周期

**适用场景**：设计活跃模式相对均匀、或计算量足够大以摊平分区边界通信开销的情况。

### 动态调度（Dynamic Scheduling）

**原理**：在运行时根据当前周期的活跃信号集合，动态将任务分配给线程。

**典型实现**：
- 任务窃取（Work Stealing）：每个线程维护自己的任务队列，空闲时从其他线程队列窃取任务
- 中央调度器：由一个调度线程根据活跃信号图动态分配macro-task到工作线程
- 自适应粒度切换：根据当前活跃信号数量决定使用单线程还是多线程

**优点**：
- 可以适应活跃信号的时间和空间分布变化，减少空转
- 负载均衡更优，特别适合活跃模式高度动态的设计

**缺点**：
- 调度本身引入运行时开销，在稀疏计算场景下可能抵消并行收益
- 需要复杂的同步机制保护调度数据结构
- 缓存局部性较差，因为任务分配不可预测

**可操作的建议**：

1. **采用混合策略**：编译时生成多个候选分区方案（如"高活跃度分区"和"低活跃度分区"），运行时根据当前活跃信号数量选择方案。这类似于Manticore的"静态调度骨架 + 运行时动态激活"思想。
2. **活跃度阈值控制**：维护一个轻量级周期级计数器，当活跃信号数超过阈值（如每周期活跃门数 > 1000）时触发多线程，否则回退到单线程。这避免了Verilator Issue #2913中的负优化陷阱。
3. **线程池的专用化**：不要设计通用线程池。参考Verilator PR #5161的教训——从复杂通用线程池退化到极简专用线程池，反而消除了大量死锁和bug。RTL仿真器的线程池应只支持"enqueue task → wait for all"这一种模式。

## 策略二：时间片并行 vs 空间分区并行

### 空间分区并行（Spatial Parallelism）

**原理**：将电路的物理/逻辑空间划分到不同线程，每个线程处理自己的分区，周期边界同步。

**典型实现**：Verilator的macro-task分区、Parendi的fiber-to-tile映射、Metro-MPI的tile-to-process映射。

**与稀疏计算的关系**：空间分区在稀疏计算中的核心问题是——如果某周期只有某个分区内有活跃信号，其他线程无事可做。分区越细，这个问题越严重。

### 时间片并行（Temporal Parallelism）

**原理**：同时推进多个仿真周期（如流水线或预测模式下），在时间维度上并行。

**典型实现**：
- Parendi的BSP模型：每个RTL周期是一个superstep，在IPU上可以重叠相邻superstep的计算和通信
- Kim等人(2008)的时间并行门级时序仿真：利用高层模型指导，同时仿真多个时间步
- Time Warp乐观同步：LP可以超前执行多个周期，遇到straggler时rollback

**与稀疏计算的关系**：时间片并行在稀疏计算中有独特优势——如果设计大部分时间静态，可以"预测"未来多个周期内状态不变，从而跳过这些周期的计算。但实现复杂，需要状态保存或反向计算能力。

**可操作的建议**：

1. **优先考虑空间分区，但引入时间批处理**：不要每周期都同步，而是每N个周期同步一次。这类似于Metro-MPI的"可配置通信间隔"——chipset和tile之间不必每周期通信。在稀疏计算中，N可以根据活跃度自适应调整：活跃度高时N=1，活跃度低时N增大。
2. **时空混合并行**：在粗粒度上按空间分区（如处理器核心与内存控制器分开），在每个分区内利用时间片并行（如预测下一周期的状态）。Parendi的BSP模型本质上是这种混合：空间分区到IPU tile，时间上通过superstep流水线重叠计算和通信。
3. **全周期仿真优先**：Parendi的一个重要发现是——全周期仿真（每个周期评估整个电路）在RTL层级通常比事件驱动快几个数量级，因为"跟踪值变化成本极高"。对于稀疏计算，这看似反直觉（全周期意味着做更多"无用"计算），但实际上避免了事件队列管理的复杂开销。建议采用**带活跃区域提示的全周期仿真**：先快速扫描活跃区域，然后只评估可能受影响的门，而不是完全的事件驱动。

## 策略三：Macro-task vs Micro-task

### Macro-task（粗粒度任务）

**原理**：将大量逻辑门聚合为一个任务单元，减少任务数量和同步频率。

**典型实现**：Verilator的MTask（每个MTask包含数百到数千个原始语句），Parendi的fiber（多个门组合），DSIM的门聚类分区。

**优点**：
- 任务粒度大，同步开销相对计算量占比小
- 缓存局部性好，一个MTask内的变量通常具有时间局部性
- 调度开销低，适合静态调度

**缺点**：
- 如果MTask内部活跃门数很少，整个MTask仍需执行（虽然可以内部跳过，但分支预测成本增加）
- 负载均衡粒度粗，难以适应细粒度的活跃分布变化

### Micro-task（细粒度任务）

**原理**：将单个门或一小簇门作为任务单元，最大化并行潜力。

**典型实现**：传统PDES中将每个门建模为一个LP，Verilator初始的语句级依赖图（数百万节点）。

**优点**：
- 理论上可以挖掘最大并行度
- 负载均衡最精细

**缺点**：
- 同步开销爆炸。在共享内存上，数百万个节点的动态调度完全不现实
- 缓存性能极差，任务切换频繁导致数据局部性丧失
- Parendi明确指出："细粒度并行在共享内存上难以执行，因为同步成本高昂"

**可操作的建议**：

1. **采用两级任务层次**：
   - **Macro-level**：编译时静态划分为MTask，用于线程间分配
   - **Micro-level**：在MTask内部，根据当前周期活跃信号动态跳过非活跃门
   这结合了静态调度的低开销和动态跳过的灵活性。

2. **自适应任务粒度**：根据设计的活跃特征动态调整。对于活跃模式稳定的大区域（如ALU），使用较大的macro-task；对于活跃模式动态变化的小区域（如控制逻辑），使用较小的macro-task或引入动态任务窃取。

3. **任务内联与内聚**：参考Verilator PR #6815的inline small CFuncs优化——在生成仿真代码时，将跨MTask边界的小函数内联，减少函数调用开销。对于稀疏计算，这意味着将频繁一起活跃的门在代码生成时尽量内联到同一个函数体中。

## 策略四：粗粒度同步 vs 细粒度同步

### 粗粒度同步（每周期一次barrier）

**原理**：所有线程在每个时钟周期结束时同步一次，确保全局状态一致。

**典型实现**：Verilator的MTask执行模型——每个MTask在启动前等待其前驱完成，本质上是一个DAG上的依赖同步。Metro-MPI的进程间通信也是以周期为单位。

**在稀疏计算中的问题**：如果每周期活跃计算量很小，barrier的固定开销（通常100ns–1μs）会完全吞噬并行收益。Verilator Issue #2913中，极简设计的单线程周期时间极短，barrier成为绝对主导因素。

### 细粒度同步（按需同步、无锁通信）

**原理**：仅在真正需要数据交换时才同步，使用无锁数据结构和轻量级原子操作。

**典型实现**：
- C++ memory model的acquire-release原子操作：~5-10ns延迟，比mutex（~100ns）快一个数量级
- Lock-free队列：线程间通过无锁SPSC/MPSC队列传递事件
- 延迟更新：Manticore的delayed updates策略，在superstep边界才同步变量

**可操作的建议**：

1. **批量同步替代每周期同步**：将N个周期的计算结果批量同步，而非每周期一次。N的选取可以自适应：当检测到分区间通信量小时增大N，通信量大时减小N。这是Metro-MPI"可配置通信间隔"在共享内存上的等价实现。

2. **使用无锁原子操作代替mutex**：
   - 时间步完成标志：使用`std::atomic` + `acquire-release`内存序，而不是`std::mutex` + `condition_variable`
   - 任务完成计数器：每个线程完成后对原子计数器做`fetch_add(1, acq_rel)`，主线程自旋等待
   - 具体代码参考source-cpp-memory-model

3. **消息传递替代共享内存**：Parendi和Manticore都证明，在大量核心场景下，消息传递优于共享内存。在通用x86多线程上，虽然纯消息传递不现实，但可以采用**混合模型**：线程内使用共享内存，线程间使用无锁消息队列（每个线程一个队列，避免锁竞争）。

4. **引入乐观同步减少barrier频率**：参考PDES中的乐观同步（Time Warp）——允许线程超前执行若干周期，仅在检测到因果错误时rollback。DSIM在百万门电路中rollback率仅0.79%，说明数字电路的因果结构使乐观同步 surprisingly well。对于稀疏计算，可以允许线程在"预测"状态不变的情况下超前执行，减少barrier等待。

## 综合建议：稀疏计算RTL并行化的最佳实践

| 策略维度 | 推荐方案 | 理由 |
|---------|---------|------|
| 分区方式 | 静态分区 + 运行时动态选择 | 静态调度开销低，但多准备几个候选分区应对不同活跃度 |
| 并行维度 | 空间分区为主，时间批处理为辅 | 空间分区实现简单，时间批处理减少同步频率 |
| 任务粒度 | 粗粒度macro-task（1000+门/任务） | 细粒度同步开销在稀疏场景下不可接受 |
| 同步粒度 | 批量同步（N周期/barrier），N自适应 | 每周期同步在稀疏计算中致命 |
| 同步原语 | 无锁原子操作 + acquire-release | 比mutex快一个数量级，见source-cpp-memory-model |
| 线程模型 | 专用线程池，非通用线程池 | 参考Verilator PR #5161的简化经验 |
| 回退机制 | 活跃度阈值控制 | 活跃信号数低于阈值时回退单线程，避免负优化 |

最终的指导原则：

> **在稀疏计算RTL仿真中，并行化的目标不是最大化线程利用率，而是最小化同步开销。空转线程是可以接受的，只要它避免了不必要的barrier等待。**

## gsim-mt 实证补充：先优化稀疏串行回退，再优化调度

XiangShan/CoreMark + NEMU diff 的 `gsim-mt` A110 后续实验给出一个可复用结论：当默认热路径已经绕开 D-static coarse dispatch 时，继续调度层调参收益很小；更有效的是把 clean coarse serial-inline fallback 做到足够轻。

已验证的正向组合：
- `GSIM_MT_STATIC_INLINE_BOUND` 默认开启：当 `active_word_span * ACTIVE_WIDTH <= mtCoarseInlineThreshold` 时，生成代码跳过每个 region 的 runtime popcount threshold scan，直接走 serial-inline fallback；低 threshold 仍保留旧 popcount gate。
- `GSIM_MT_SUBCHUNK_RUNTIME` 默认关闭：在 static-bound 后，默认不再生成 runtime subchunk 字段/分支/counter，profile-off 模型更小。需要诊断时显式 `GSIM_MT_SUBCHUNK_RUNTIME=1`。

关键测量：
- v49 static-bound/no-env 相对 v44 region-profile split：C=50000 host `22630ms` vs `23179ms`。
- v52/v53 static-bound + no-subchunk 相对 v49：`22320ms` vs `22586ms`、`22577ms` vs `22602ms`、`22257ms` vs `22555ms`。

被否定的近邻优化同样重要：
- direct static-bound branch 复制 serial-inline body，v54 `22546ms` vs v53 `22206ms`，代码体积/I-cache 成本超过少量 compare/assignment 收益。
- boolean gate 形态不复制 body，但 v51 `24392ms` vs v49 `22619ms`，分支形态明显更差。
- coarse guard accumulator 用 `mtCoarseAny` 替换长 OR 表达式，三轮结果混合：`22521ms` vs `22420ms`、`22784ms` vs `22936ms`、`22495ms` vs `22428ms`，不能推广。
- clean-region batching 需要先跑 segment report；当前 v57 的 conservative contiguous bidirectional boundary check 得到 `clean_region_count=423`、`segment_count=423`、`max_segment_regions=1`，没有可批量合并的 multi-region clean segment。不要在没有更强 visibility/order proof 前实现 batching。

工程规则：在稀疏 RTL 仿真里，先删除默认热路径上的固定诊断分支、popcount、额外 body 复制和不稳定 guard 改形；只有当热串行 fallback 足够轻之后，再尝试 clean-region batching 或调度层优化。

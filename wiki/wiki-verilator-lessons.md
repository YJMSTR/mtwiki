---
id: "wiki-verilator-lessons"
title: "Verilator多线程化经验总结"
description: "从Verilator多线程实现中吸取的经验教训，包括图划分策略、变量排序优化、PGO和NUMA绑定等具体实践建议"
tags: ["rtl-sim", "verilator", "multithreading", "lessons-learned", "optimization"]
keywords: ["Verilator", "V3Partition", "V3Order", "V3VariableOrder", "Thread PGO", "NUMA", "macro-task"]
related_sources:
  - "source-verilator-issue-2913"
  - "source-verilator-mt-doc"
  - "source-verilator-mt-prs"
  - "source-verilator-mt-code-analysis"
  - "source-verilator-v3variableorder"
last_updated: "2026-07-01"
---

# Verilator多线程化经验总结

Verilator是目前最主流的开源SystemVerilog仿真器，其多线程实现经历了数年的迭代和优化。从Issue #2913的负优化教训，到PR #5161的线程池重写，再到V3VariableOrder的并行化改进，Verilator社区积累了大量关于"RTL仿真器多线程化"的实战经验。本节系统总结这些经验，为稀疏计算RTL仿真器的多线程设计提供参考。

## 一、小设计负优化的原因

### 现象：不是"多线程不够快"，而是"多线程慢得多"

Verilator Issue #2913中的核心数据：

| 配置 | 耗时 |
|------|------|
| `--no-threads` | 1.896 s |
| `--threads 1` | 3.159 s |
| `--threads 4` | 7.638 s |

从单线程Verilated模型到4线程，耗时翻了4倍，**比单线程慢了近3倍**。这不是"多线程收益不够"，而是严重的性能退化。

### 原因分析

1. **Macro-task分区的固定开销**：Verilator的多线程模型将电路编译为C++代码，然后划分为macro-task（MTask）。每个MTask需要：
   - 独立的函数调用入口（函数调用开销）
   - 与前后驱MTask的同步点（condition variable或自旋等待）
   - 线程池的任务分发和回收（enqueue/dequeue开销）
   这些开销在计算量小的设计下完全无法摊平。

2. **线程管理的固定成本**：即使`--threads 1`（仅让库线程安全），性能也比`--no-threads`慢66%。这说明Verilator的线程安全机制本身就有显著开销。

3. **同步开销在稀疏计算下被放大**：如果每周期只有少数门翻转，线程完成计算后大部分时间都在等待barrier。活跃信号越少，等待时间占比越大。

### 经验教训

> **对于稀疏计算RTL仿真器，必须有"活跃度阈值"机制。当设计的活跃计算量低于某个阈值时，自动回退到单线程模式。不能盲目开启多线程。**

具体实现建议：
- 在编译时为每个MTask标注"预估最小计算量"
- 在运行时维护一个周期级计数器（可用`std::atomic` + `relaxed`）统计每周期活跃门数
- 如果连续K个周期的活跃门数都低于阈值，关闭多线程直到活跃度回升

## 二、V3Partition / V3Order 的图划分策略

### 原理：从百万级节点到数十个MTask的边收缩

Verilator的多线程核心在于`V3OrderParallel`（Partitioner）。它将V3Order生成的细粒度语句级依赖图（可能有数百万节点）粗化为仅包含数十个MTask的执行图。核心算法是**边收缩（Edge Contraction）**：

1. 初始时每个OrderMoveVertex对应一个LogicMTask
2. 迭代合并有边连接的MTask对，选择使得**局部临界路径增长最小**的候选对
3. 使用`MergeCandidateScoreboard`（基于PairingHeap）维护候选合并的优先级
4. 合并直到MTask数量降到`threads * PART_DEFAULT_MAX_MTASKS_PER_THREAD`（默认50个/线程）

### 关键设计决策

1. **从细粒度到粗粒度**：Verilator文档指出："The partitioner's goal is to coarsen the fine-grained graph into a coarser graph, while maintaining as much available parallelism as possible. Often the partitioner can transform an input graph with millions of nodes into a coarsened execution graph with a few dozen nodes, while maintaining enough parallelism to take advantage of a modern multicore CPU."

2. **静态调度优于动态调度**：Verilator实验表明动态调度（macro-dataflow）性能较差。因此采用静态调度——MTask到线程的映射在Verilation时确定，运行时仅通过轻量级同步等待前驱完成。

3. **FixDataHazards**：处理并行模式下原本在串行模式无问题的数据冒险（如R-M-W竞争）。策略是将同一rank的读写MTask强制合并，并在不同rank之间添加串行边。

### 对稀疏计算RTL仿真器的启示

1. **图划分需要两阶段**：第一阶段构建细粒度语句/门级依赖图，第二阶段通过边收缩粗化为macro-task。对于稀疏计算，第一阶段可以加入"活跃模式权重"——将经常在同一周期内一起活跃的门赋予更小的合并惩罚。

2. **MTask数量不能太多**：Verilator默认每个线程50个MTask。对于稀疏计算，建议减少到每个线程10-20个MTask，因为MTask的同步开销在稀疏场景下更显著。

3. **增量临界路径传播**：`PropagateCp`使用最大堆实现增量传播，避免全图重算。如果需要频繁调整分区（如运行时自适应分区），这是可借鉴的性能优化。

4. **静态调度 + 轻量运行时同步**：对于确定性仿真，静态调度是正确选择。稀疏计算RTL仿真器应考虑静态分配任务到线程，仅在MTask边界同步。

## 三、V3VariableOrder 的变量排序优化

### 原理：按MTask亲和性分组 + 缓存行对齐

V3VariableOrder在2024年通过PR #5406进行了重大改进，核心逻辑：

1. **收集MTask亲和性**：遍历每个ExecMTask的函数体，收集每个变量被哪些MTask引用
2. **按亲和性分组排序**：将具有相同MTask亲和性向量的变量分到同一组
3. **缓存行对齐**：在每组MTask亲和变量的开头插入对齐（`mtaskCacheLineAlign(true)`），减少false sharing
4. **并行模块排序**：使用`V3ThreadScope`并行对每个模块进行变量排序

```cpp
void mtaskSortVars(std::vector<AstVar*>& varps) {
    // 按MTask亲和性向量分组
    std::map<MTaskIdVec, std::vector<AstVar*>> m2v;
    for (AstVar* const varp : varps) {
        const auto it = m_mTaskAffinity.find(varp);
        const MTaskIdVec& key = it == m_mTaskAffinity.end() ? emptyVec : it->second;
        m2v[key].push_back(varp);
    }
    // 对齐并排序
    for (auto& pair : m2v) {
        if (emptyAffinity(pair.first)) continue;
        sortAndAppend(pair.second, true);  // alignFirst = true
    }
}
```

### 对稀疏计算RTL仿真器的启示

1. **从"按MTask分组"到"按活跃模式分组"**：Verilator的MTask亲和性是基于静态macro-task分区的。在稀疏计算中，一个变量可能在某些周期属于任务A，在另一些周期属于任务B（如果活跃信号集合变化）。这提示我们可能需要：
   - 运行时动态重排（可能过于昂贵）
   - 为不同活跃模式预编译多个变量布局（内存开销大但运行时零开销）
   - 或者采用更简单的策略：将经常同时活跃的变量（通过剖析统计）分到同一组

2. **缓存行对齐的权衡**：`mtaskCacheLineAlign`用内存填充换取多线程性能。对于稀疏计算：
   - 如果变量组很小（如只有几个1-bit信号），填充可能导致显著的内存浪费（64字节对齐意味着最多浪费63字节/组）
   - 需要**动态评估**对齐收益 vs 内存开销，而非无条件对齐
   - 建议：仅对"高频同时活跃"的变量组进行对齐，低频组使用紧凑布局

3. **Stratum排序的启发**：`orderModuleVars`中的stratum分配逻辑（按信号宽度、类型、数组等确定对齐要求）体现了内存布局对性能的影响。在稀疏计算中，信号宽度差异可能更大（32-bit计数器 vs 1-bit控制信号），合理的内存布局可以减少缓存占用，提高cache hit rate。

## 四、Thread PGO 的作用

### 原理：运行时剖析引导的线程负载均衡

Verilator支持`--prof-pgo`选项：
1. 第一次编译时传入`--prof-pgo`，运行模型生成`profile.vlt`文件
2. 该文件记录了各macro-task的实际执行时间
3. 重新Verilate时传入`profile.vlt`，替换估计代价，实现更均衡的线程负载分配

Verilator文档指出："When using multithreading, Verilator computes how long macro tasks take and tries to balance those across threads. If the estimations are incorrect, the threads will not be balanced, leading to decreased performance. Thread PGO allows collecting profiling data to replace the estimates and better optimize these decisions."

### 对稀疏计算RTL仿真器的启示

1. **PGO在稀疏计算中更有价值**：因为稀疏计算下，不同周期的活跃信号分布差异大，静态估计的代价更容易偏离实际。通过PGO收集实际运行数据，可以：
   - 识别哪些MTask在稀疏场景下实际计算量很小，考虑合并
   - 识别负载不均衡的周期模式，调整分区策略

2. **PGO需要周期性刷新**：Verilator文档警告"如果PGO数据过期（源码改动），会触发PROFOUTOFDATE警告"。对于稀疏计算RTL仿真器，如果设计本身支持重配置（如不同的测试用例导致不同活跃模式），可能需要：
   - 多个profile文件（对应不同工作负载）
   - 或在线增量更新profile数据（运行时收集，定期刷新分区）

3. **轻量级周期级计数器**：如果不想做完整的PGO，可以设计一个更轻量的机制——运行时记录每个MTask的周期级活跃门数，维护一个滑动窗口平均值。当检测到持续不均衡时，触发动态调整或报警。

## 五、NUMA 绑定的影响

### Verilator的官方建议

Verilator文档对NUMA绑定的讨论非常详细：

> "When running a multithreaded model, the default Linux task scheduler often works against the model by assuming short-lived threads and thus it often schedules threads using multiple hyperthreads within the same physical core."

> "For best performance, use the **numactl** program to (when the threading count fits) select unique physical cores on the same socket."

> "On Systems with multiple L3 clusters per socket (e.g., AMD EPYC or Ryzen), consider using **lstopo** to determine the L3 cluster topology of the current system and **numactl** to bind CPUs within a single L3 cluster."

> "Sometimes, for model's thread counts that are more than the core count per L3 cluster, using SMTs (hyperthreads) within a single L3 cluster can have better performance than spreading across multiple L3 clusters using physical cores only."

### Issue #2913 的NUMA经验

Issue中报告者提到使用了`numactl`但没有改善。这暗示：**如果基础调度模型本身同步开销过大，仅靠NUMA绑定无法解决问题**。必须先优化调度模型，再辅之以NUMA绑定。

### 对稀疏计算RTL仿真器的具体建议

1. **NUMA绑定是必要但不充分条件**：在部署多线程仿真时，始终使用`numactl`或`taskset`绑定线程到同一L3集群。但不要把性能优化的全部希望寄托于此。

2. **优先使用物理核心，但超线程有其价值**：
   - 如果线程数 <= 单L3集群物理核心数：使用物理核心，禁用SMT
   - 如果线程数 > 单L3集群物理核心数：宁可使用同一集群内的超线程，也不要跨集群使用物理核心

3. **绑定到同一NUMA节点并分配本地内存**：
   ```bash
   numactl --cpunodebind=0 --membind=0 ./simulator
   ```
   确保内存分配和访问都在本地，避免跨节点缓存一致性开销。

4. **lstopo查看拓扑**：
   ```bash
   lstopo --no-io --no-legend --of txt
   ```
   了解系统的L3集群分布、NUMA节点划分，制定最优绑定策略。

## 六、对用户的项目给出具体建议

### 如果你是Verilator用户

1. **先测试单线程vs多线程**：不要默认使用多线程。用`--no-threads`和`--threads N`对比，确认多线程确实有收益。
2. **使用Gantt报告诊断**：`--prof-pgo`和Gantt报告可以帮助分析线程负载均衡。如果看到大量空闲时间（fragmentation），说明分区需要优化。
3. **NUMA绑定**：在AMD EPYC/Ryzen上，使用`numactl`绑定到同一L3集群。
4. **尝试编译器PGO**：GCC/Clang的`-fprofile-generate` / `-fprofile-use`通常带来5-15%提升，适用于单线程和多线程。
5. **超线程权衡**：线程数超过单L3集群核心数时，测试"同集群超线程" vs "跨集群物理核心"，选择更优者。

### 如果你正在开发新的稀疏计算RTL仿真器

1. **设计动态开销感知调度器**：不要固定使用多线程。根据每周期活跃信号数动态决定是否启用多线程。
2. **采用批量同步**：不要每周期barrier，而是每N周期同步一次，N自适应调整。
3. **使用无锁原子操作替代mutex**：所有轻量级同步用`std::atomic` + `acquire-release`，避免`std::mutex`和`std::condition_variable`。
4. **专用线程池而非通用线程池**：参考Verilator PR #5161，移除通用功能（futures、resize、动态停止），使用RAII作用域管理（`V3ThreadScope`模式）。
5. **变量排序按活跃模式分组**：超越Verilator的静态MTask亲和性，按运行时活跃模式统计优化变量布局。
6. **渐进式并行化**：参考PR #4228，将代码单元分为MT_DISABLED/MT_ENABLED/MT_CONTROL三级，不必一次性让整个代码库线程安全。
7. **考虑消息传递替代共享内存**：如果目标平台支持（如多节点集群），参考Parendi和Metro-MPI的BSP/MPI模型，可能比共享内存多线程扩展性更好。
8. **乐观同步用于组合逻辑**：参考PDES研究，数字电路的rollback率极低（<1%），可以考虑在组合逻辑部分使用乐观同步，减少barrier等待。

## 关键经验总结

> **Verilator的多线程化经验可以归结为一句话：RTL仿真器的多线程不是"加线程池"那么简单，而是需要在编译时分区、运行时同步、内存布局、线程管理四个层面进行系统性设计。对于稀疏计算，这些层面的挑战被进一步放大——计算量太小，任何固定开销都是致命的。因此，稀疏计算RTL仿真器的多线程设计必须更加保守、更加动态、更加轻量。**

---
title: Simulation State Compression / Deduplication & Waveform Compression
description: 搜集数字波形压缩（VCD/FSDB/FST）、仿真状态去重与压缩技术的研究进展与工业实践
source_url: "https://numbda.cs.tsinghua.edu.cn/papers/glsvlsi23_2.pdf"
source_type: "paper"  # github-pr, github-issue, blog, doc, paper, competition
author: "Zhenyi Gao, Yuyang Xie, Wenjian Yu (Tsinghua); Verilator; GTKWave"
date: "2021-2023"
tags: ["state-compression", "waveform-compression", "VCD", "FSDB", "FST", "deduplication", "value-change-dump"]
keywords: ["simulation state compression", "VCD compression", "FSDB compression", "waveform compression", "Siloti"]
capture_date: "2025-06-14"
---

# 仿真状态压缩与波形数据去重技术

## 来源

- **URL**: https://numbda.cs.tsinghua.edu.cn/papers/glsvlsi23_2.pdf
- **类型**: 学术论文 + 开源工具文档 + 工业实践
- **作者**: 高振一、谢雨洋、喻文健（清华大学）；Verilator 社区；GTKWave 项目
- **日期**: 2021-2023

### 主要参考文献

- Gao et al., *Efficient and Effective Digital Waveform Compression for Large-scale Logic Simulation*, GLSVLSI 2023
- Xie et al., 前序工作（数字波形压缩基础格式）
- FSDB (Fast Signal DataBase) 工业格式说明
- Verilator FST 格式支持
- Synopsys Siloti 增量波形重建技术

## 摘要

大规模 IC 逻辑仿真产生的数字波形数据（VCD 格式）可达数百 GB 甚至 TB 级。本文档综述了学术界提出的专用波形压缩算法（最高达 1561x 压缩率）、工业界的 FSDB/FST 紧凑格式，以及仿真状态去重与增量保存的关键技术。核心思想是：利用数字信号值变化的稀疏性、时间局部性和信号别名重复性，通过预测编码 + 变长编码 + 二级通用压缩，实现比通用工具（bzip2）更高的压缩率；同时，去重查找表和分段策略可显著降低内存开销。

## 关键要点

### 1. VCD 文件格式与数据冗余特征

VCD（Value Change Dump）是 ASCII 文本格式，包含两部分：
- **头部辅助信息**：仿真时间、周期、信号定义（类型、位宽、别名、名称）。
- **信号跳变信息**：仅记录发生值变化的时刻点及对应信号值。

每个信号有一个短别名（alias，ASCII 33-126 字符），在跳变信息中引用。信号定义通常较长，别名较短，但不同时间点的别名序列（VTRA）往往重复，存在大量冗余。

### 2. 清华大学 GLSVLSI 2023 压缩算法

**核心贡献**：
- **Detailed-Encoding**：根据 TRB（Transition Block）的特性选择编码方式。若 TRB 内所有信号值均为 0/1（clean TRB），则每位只需 1 bit；若含 X/Z（dirty TRB），则沿用 2-bit 编码。每个 TRB 增加 1 bit 标识 clean/dirty。
- **预测编码**：利用历史表（HT）进行值预测。单比特信号预测为翻转（flip），多比特信号仅预测最后一位翻转。预测值与原始值做 XOR 后产生大量连续 0，利于二级压缩。
- **改进的别名查找表**：当 VTRA 长度超过 256 时，按单比特/多比特位宽变化进行启发式分段（sub-VTRA），减少长 VTRA 对查找表命中率的负面影响，峰值内存降低约 20%。
- **辅助信息精细编码**：信号类型从 ASCII 字符串（3-9 字节）压缩为 5-bit 整数；位宽信息用变长编码。

**实验结果**（8 个工业用例）：
- 相对原始 VCD 的**平均压缩率 402x**，最高 **1561x**。
- 相比前序方法（Xie et al.），压缩率提升最高 2.56x，平均 1.62x。
- 压缩/解压时间减少 10-12%，大用例压缩时间减少 20%。
- 峰值内存：小用例 < 1GB，大用例 < 3GB，平均降低 19-20%。

### 3. 三级流水线并行压缩

整个压缩/解压过程被设计为三级流水线：
1. **编码阶段**：完成 TRB 编码和数据存储格式构建。
2. **二级压缩阶段**：对数据流进行通用无损压缩（如 Deflate、ZSTD）。
3. **写盘阶段**：将数据流写入磁盘。

流水线支持线程级并行计算，显著降低压缩/解压运行时间，可与 IC 逻辑仿真流程无缝集成。

### 4. 工业紧凑格式：FSDB 与 FST

**FSDB（Fast Signal DataBase）**
- Verdi / Novas 支持的原生格式，可被 VCS、Ncsim、ModelSim 等工具通过 Verilog PLI 接口生成。
- 仅保存调试所需的信号变化信息，去除 VCD 中的冗余信息，类似于对 VCD 做 Huffman 编码。
- 文件体积远小于 VCD，同时提升仿真速度（因为写入数据量更少）。
- 算法未公开，属于专有格式。

**FST（Fast Signal Trace）**
- GTKWave 支持的高效压缩格式，被 Verilator 作为原生输出选项之一。
- 采用块级压缩和去重技术，支持动态读取部分波形，无需解压完整文件。
- 开源实现，API 提供 deduplication 和压缩选项，便于仿真器直接集成。

### 5. 状态去重与增量保存策略

**gVisor Checkpoint 的启发**（虽非 RTL 仿真，但技术可迁移）：
- `--exclude-committed-zero-pages`：跳过仅含 0 的已提交内存页，显著减少 LLM 等大内存应用的快照大小。
- `--compression` 支持 `none` 和 `flate-best-speed`，权衡 CPU 与空间。
- `--direct` I/O：绕过宿主机页缓存，适合首次从磁盘读取快照且不会在原机恢复的场景。

**VCDiag（2025）中的统计压缩**：
- 将信号压缩为均值、标准差、分位数等统计指标（SummaryTransformer），用于 ML 训练故障分类。
- 压缩后数据量降低 50-123x，结合多核并行实现 4.4x 加速。
- 启示：仿真状态不一定需要逐位精确保存，某些场景下（如覆盖率分析、故障分类）统计摘要即可。

## 对 RTL 仿真器多线程化的启示

1. **线程级压缩并行**：三级流水线设计天然适配多线程仿真。每个线程可在局部完成预测编码后，将压缩块交给全局写盘线程，避免 I/O 阻塞仿真主循环。多线程下，不同线程的局部状态块可并行压缩，再合并为全局 Checkpoint 文件。

2. **内存友好型去重**：大型多线程仿真中，信号别名查找表（VTRA2INDEX）可能成为内存瓶颈。清华大学的分段 VTRA 策略启示我们：在并行环境中，每个线程维护自己的局部别名子表，Checkpoint 时合并去重，可降低全局锁竞争和峰值内存。

3. **增量状态 vs. 完整波形**：多线程仿真若同时输出波形，FSDB/FST 的增量写入机制比 VCD 更适合。每个线程维护本地值变更缓冲区，周期性 flush 到共享文件，避免每有信号跳变就触发全局锁。

4. **零页/恒值信号跳过**：gVisor 的 zero-page 排除策略可直接迁移到 RTL 仿真——大量寄存器在大部分仿真时间内保持恒定或为零。Checkpoint 时仅保存 dirty 状态，可缩小快照体积数倍。

## 原文摘录

> "The proposed scheme encodes different values according to their detailed characteristics and utilizes a modified look-up table to reduce the memory cost for storing signal aliases. Experiments with the digital waveforms from industry show that the proposed method enables 402X average (and up to 1561X) compression ratio with respect to the original VCD format."
> — Gao et al., GLSVLSI 2023

> "The whole compression or decompression process can be regarded as a three-stage pipeline as shown in Fig. 4. The first step in the pipeline completes the encoding of the TRB and the construction of the data storage format, the second step performs the secondary compression of the data stream, and the third step writes the data stream to file. The three-stage pipeline facilitates thread-level parallel computing."
> — Gao et al., GLSVLSI 2023

> "FSDB is the spring Soft (Novas) company Debussy/verdi support waveform files, generally smaller, more widely used... The Fsdb file is Verdi uses a proprietary data format, similar to a VCD, but it is only a useful information to signal the simulation process, removing the information redundancy in the VCD, like the VCD data for a Huffman encoding."
> — 工业文档：FSDB 格式说明

> "By providing the --exclude-committed-zero-pages flag to runsc checkpoint, gVisor skips saving memory pages that are committed but contain only zeros. This can significantly reduce the checkpoint size for applications that have large, zero-filled memory regions."
> — gVisor Checkpoint/Restore 文档

## 相关链接

- [GLSVLSI 2023 论文 (PDF)](https://numbda.cs.tsinghua.edu.cn/papers/glsvlsi23_2.pdf)
- [TCAD 2021 前序论文 (PDF)](https://numbda.cs.tsinghua.edu.cn/papers/tcad21_2.pdf)
- [GTKWave FST API Issue #70](https://github.com/gtkwave/gtkwave/issues/70)
- [FSDB 格式说明](https://adaptivesupport.amd.com/s/article/58159)
- [Verilator FST 波形支持](https://open-verify.cc/mlvp/en/docs/env_usage/wave/)
- [gVisor Checkpoint/Restore 文档](https://gvisor.dev/docs/user_guide/checkpoint_restore/)
- [VCDiag 波形故障分类论文](https://arxiv.org/html/2506.03590v3)

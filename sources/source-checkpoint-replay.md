---
title: RTL Simulation Checkpoint / Snapshot Save & Restore
description: 搜集 RTL 仿真器中 Checkpoint 与 Snapshot 的实现方案、商用工具支持及实际应用场景
source_url: "https://tomverbeure.github.io/2020/10/26/Simulation-Save-Restore-with-CXXRTL.html"
source_type: "blog"  # blog, doc, paper, github-pr, github-issue
author: "Tom Verbeure, Cadence, Siemens EDA, DVCon"
date: "2020-2024"
tags: ["checkpoint", "snapshot", "save-restore", "CXXRTL", "ModelSim", "Xcelium", "VCS", "UVM"]
keywords: ["RTL simulation checkpoint", "simulator snapshot", "warm restore", "cold restore", "Siloti"]
capture_date: "2025-06-14"
---

# RTL 仿真器 Checkpoint / Snapshot 技术综述

## 来源

- **URL**: https://tomverbeure.github.io/2020/10/26/Simulation-Save-Restore-with-CXXRTL.html
- **类型**: 技术博客 + 商用工具文档 + 学术论文
- **作者**: Tom Verbeure / Cadence / Siemens EDA / DVCon
- **日期**: 2020-2024

### 主要参考文献

- CXXRTL Save/Restore Checkpointing (Tom Verbeure, 2020)
- ModelSim/QuestaSim Checkpoint/Restore 手册
- Cadence Xcelium Save & Restart 官方文档
- DVCon 论文：*Saving and Restoring Simulation Methodology Using UVM Factory Overriding*
- Synopsys Siloti 波形压缩与增量 Checkpoint 技术

## 摘要

RTL 仿真器的 Checkpoint（快照）技术允许在仿真过程中保存完整状态，并在之后从该点恢复，避免重复执行耗时的初始化序列。本文档综述了开源仿真器（CXXRTL）和商用工具（ModelSim、Xcelium、VCS）的 Checkpoint 实现方案，以及 UVM 测试平台中的 Save & Restore（SnR）方法论。核心应用场景包括：加速长仿真调试、跳过固定初始化序列、以及配合增量保存实现波形数据压缩。

## 关键要点

### 1. Checkpoint 的核心使用场景

- **加速长仿真调试**：在回归测试中，数千次仿真日以继夜地运行。当仿真运行数小时甚至数天后才失败时，需要从头重新开启波形转储再跑一次。Checkpoint 允许以固定间隔（如每 5 分钟）保存状态，失败后从最近快照恢复并开启波形，极大缩短调试周期。
- **激进波形压缩**：Synopsys Siloti 等产品不直接保存波形数据，而是定期保存仿真状态快照 + 仿真模型本身。查看波形时由波形查看器即时重新仿真生成。这种方案下，Checkpoint 甚至可以做到增量式（ incremental from one step to the other）。
- **跳过固定的长初始化**：SoC 运行 Linux 等系统需要漫长的 boot 序列。在初始化完成后保存 Checkpoint，之后可快速从该点启动不同驱动测试，甚至可以在 RTL 变更后复用同一快照（只要被测硬件在 Checkpoint 前保持复位状态）。

### 2. 商用工具实现

**ModelSim / QuestaSim**
- 命令：`checkpoint <filename>` 保存，`restore <filename>` 热恢复，或 `vsim -restore <filename>` 冷启动恢复。
- 保存内容：仿真内核状态、WLF 文件、list/wave 窗口信号列表、VHDL `$fopen` 文件指针位置、foreign architecture 状态。
- **不恢复**：宏状态、Tcl CLI 变更、GUI 窗口状态、toggle 统计。
- 默认压缩 Checkpoint 文件；可通过 `set CheckpointCompressMode 0` 关闭。

**Cadence Xcelium**
- 支持 SystemVerilog 中的 `$save("SNAPSHOT_init")` 调用，结合 `xrun -r "SNAPSHOT_init"` 恢复。
- 支持在保存 Snapshot 后，通过修改 `UVM_TESTNAME` 恢复并运行不同测试，从而跳过公共初始化序列。
- 注意：SDI/Verilog 信息不支持保存，恢复后的新 FSDB 与先前初始化阶段波形无法自动合并，需要手动处理。

### 3. 开源实现：CXXRTL 的 Checkpoint 机制

CXXRTL（Yosys 的 C++ 仿真后端）通过**设计自省（design introspection）**实现极简的 Checkpoint：
- 统一访问接口：`debug_item` 类暴露 `value` / `wire` / `memory` / `alias` 四种状态对象。
- 保存时仅序列化 `wire`（含当前值和下一值）和 `memory` 的原始数据；`value` 可由恢复后的单步仿真重新推导。
- 示例实现中，状态以纯文本（ASCII）保存，含完整层级名和 `uint32_t` 数据，文件格式可优化空间约两个数量级。
- 局限性：不支持异步时钟域精准采样、testbench 外部状态需另行处理、设计变更后无法恢复。

### 4. UVM Save & Restore（SnR）方法论

DVCon 论文提出基于 UVM Factory Override 的 SnR 流程：
- **Saving Simulation**：在公共 sequence（初始化）后调用 `do_save()` DPI-C 函数，生成包含 DUT 和 testbench 全部状态的快照文件。
- **Restoring Simulation**：通过 UVM Factory 的 type override 机制，在恢复后替换原有 sequence 为新的测试 sequence，无需重新执行公共初始化。
- 实现前提：被覆盖和被替换的 sequence 必须注册到 UVM factory、且类型一致；保存点后必须有 sequence 可被执行/覆盖。

### 5. 增量 Checkpoint 与波形压缩的结合

Tom Verbeure 提出扩展方案：
- 不保存完整波形，而是保存**周期性增量快照**（相邻快照间差异）。
- 波形查看器需要时基于模型 + 快照即时仿真生成信号值。
- 仿真时跟踪每个信号是否保持恒定，为波形查看器提供即时视觉反馈，指示哪些信号有事件发生。
- Synopsys Siloti 已采用类似方法减少波形数据量。

## 对 RTL 仿真器多线程化的启示

1. **多线程快照一致性**：异步时钟域和多线程调度下，快照必须捕获**全局一致的状态切面**。单线程仿真中随时保存都自然一致；多线程并行时，需要在全局同步点（如时钟沿、调度屏障）冻结所有线程后保存，否则状态切面可能包含跨时钟域的时序竞争。

2. **增量快照对多线程更友好**：完整状态保存可能涉及 GB 级数据拷贝；增量保存仅记录差异，可显著降低多线程仿真因 Checkpoint 导致的停顿。差异检测可以按线程局部状态进行，合并后写入全局日志。

3. **Testbench 外部状态**：多线程仿真中，testbench 本身也携带状态（如 scoreboard、sequencer 队列）。SnR 方法要求保存 DUT + testbench 的联合状态，这在多线程环境下需要更精细的序列化协议。

4. **内存映射快照**：CXXRTL 的 `debug_item` 设计启示我们——将仿真状态暴露为统一内存接口，可以方便地实现快速 mmap 快照，避免昂贵的逐值序列化。

## 原文摘录

> "With a checkpoint save/restore option, one could simulate without dumping waveforms but instead save the state of the design at fixed intervals, say, every 5 minutes, while deleting the previous snapshot to save disk space. After a simulation failure, one can quickly get waveforms by restarting the simulation after the last saved checkpoint."
> — Tom Verbeure, *Simulation Save/Restore with CXXRTL*

> "The things that are saved with checkpoint and restored with the restore command are: simulation kernel state, vsim.wlf file, signals listed in the list and wave windows, file pointer positions for files opened under VHDL, file pointer positions for files opened by the Verilog $fopen system task, state of foreign architectures."
> — ModelSim Reference Manual

> "Instead of dumping the changed values of signals whenever they happen, one could instead save checkpoints at regular intervals, together with the simulation model. The checkpoints themselves could even be incremental from one step to the other. Siloti by Synopsys uses this kind of method to reduce the bulk of waveform data."
> — Tom Verbeure

> "In the SnR methodology workflow, the restoring simulation can proceed after the snapshot is created while the saving simulation and the restoring simulation performing the UVM factory overriding."
> — DVCon Paper: *Saving and Restoring Simulation Methodology Using UVM Factory Overriding*

## 相关链接

- [CXXRTL Save/Restore Blog](https://tomverbeure.github.io/2020/10/26/Simulation-Save-Restore-with-CXXRTL.html)
- [ModelSim Checkpoint/Restore Manual](http://www.pldworld.com/_hdl/2/_ref/se_html/manual_html/a_tnt2.html)
- [Cadence Xcelium Save & Restart Discussion](https://community.cadence.com/cadence_technology_forums/f/functional-verification/42036/how-do-we-use-the-concept-of-save-and-restore-during-real-developing-debugging)
- [EETOP Checkpoint + UVM_TESTNAME 讨论](https://bbs.eetop.cn/thread-627062-1-1.html)
- [DVCon SnR Paper (PDF)](https://dvcon-proceedings.org/wp-content/uploads/saving-and-restoring-simulation-methodology-using-uvm-factory-overriding-to-reduce-simulation-turnaround-time_paper.pdf)

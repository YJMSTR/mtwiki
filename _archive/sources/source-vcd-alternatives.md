---
title: "VCD 替代波形格式与性能对比调研"
description: "系统梳理RTL仿真波形dump的各种格式（VCD、FST、FSDB、GHW、WLF、VPD、SHM、LXT/LXT2/VZT），对比其压缩率、随机访问能力、写入开销、生态支持，为多线程仿真器的波形子系统选型提供依据。"
source_url: "https://veripool.org/guide/latest/faq.html"
source_type: "doc"
author: "多源整合"
date: "2026-07-02"
tags: ["VCD", "FST", "FSDB", "GHW", "waveform-format", "compression", "performance", "dump-format"]
keywords: ["波形格式", "VCD替代", "快速信号跟踪", "二进制波形", "流式dump", "仿真I/O优化"]
capture_date: "2026-07-02"
---

# VCD 替代波形格式与性能对比调研

## 来源

- URL: 多源整合（Verilator FAQ / GHDL文档 / GDBWave博客 / CSDN技术博客 / EETOP论坛）
- 类型: doc / blog / github-issue
- 作者: 多源
- 日期: 2026-07-02

## 摘要

Value Change Dump (VCD) 是IEEE 1364 Verilog标准定义的ASCII波形格式，通用性最强但效率最差。随着设计规模膨胀，VCD的体积膨胀、写入速度慢、不支持随机访问等问题日益凸显。业界发展出多种替代格式：FST（GTKWave开源，50x压缩）、FSDB（Synopsys专有，商业标准）、GHW（GHDL原生，支持VHDL全类型）、WLF/VPD/SHM（各EDA厂商锁定格式）等。本文系统对比这些格式的技术特性、压缩效率、生态支持，并探讨「流式波形dump」作为下一代方向的可行性。

## 关键要点

### 1. VCD — 通用但低效的标准格式

- **标准**: IEEE 1364 (Verilog) / IEEE 1364-2001 (EVCD扩展)
- **格式**: 纯文本ASCII，包含头信息、变量定义、值变更时间戳
- **优点**:
  - 几乎所有仿真器和波形查看器都支持
  - 人类可读，易于脚本解析和处理
  - 仿真中断后，已写入部分仍可读取（顺序写入的文本格式）
- **缺点**:
  - **体积庞大**: 无压缩，大型仿真可达数百GB
  - **读取低效**: 必须从头扫描到目标时间点，无法随机访问
  - **类型局限**: 源自Verilog，无法表达VHDL的枚举、记录、数组等复杂类型
  - **写入开销**: 频繁fprintf导致显著的I/O瓶颈
- **典型场景**: 小型设计教学、脚本化后处理、通用兼容性要求

### 2. FST — 开源社区的最优替代

- **开发者**: Tony Bybell (GTKWave作者)
- **全称**: Fast Signal Trace / Fast Signal Transition
- **格式**: 二进制，两级压缩方案
- **压缩机制**:
  1. **Stage 1**: 将信号值变更编码为delta值（差分编码）
  2. **Stage 2**: 使用LZ4或GZIP对Stage 1输出进一步压缩
- **性能数据**:
  - 文件体积约为等效VCD的 **1/50**（Tom Verbeure实测：VCD 3.4MB → FST 76KB，约45x）
  - 压缩/解压速度快，对仿真 slowdown 影响小（Verilator `--trace-fst` 支持）
  - 内置多线程压缩支持：大量信号时可并行压缩（需配置）
- **随机访问能力**:
  - 文件按chunk分块存储，支持中间数据快速定位
  - 无需读取整个文件即可提取目标时间段数据
  - **支持「边写边读」**: 仿真尚未结束时即可打开FST查看已记录部分
- **生态支持**:
  - 写入: Verilator (`--trace-fst`)、Icarus Verilog (`-fst`)、GHDL
  - 读取: GTKWave、Surfer、VaporView
  - 转换: `vcd2fst` (GTKWave自带工具)
- **局限**:
  - 无正式格式规范，文档仅存在于源码注释和作者回复中
  - 无独立库，需从GTKWave源码树提取
  - 不支持LSB非0的向量（如`[31:2]`会被存为`[29:0]`）
  - 某些场景下写入可能比VCD慢（Verilator Issue #2014报告了100x slowdown，但后续已优化）
- **关键使用建议**:
  - 使用Verilator FST时，**切勿每周期调用 `flush()`**，否则性能暴跌20倍
  - FST文件对中断敏感：仿真被Ctrl+C终止时，文件缺少尾部索引，可能损坏无法打开（与VCD的容错性形成对比）

### 3. FSDB — 商业EDA的事实标准

- **开发者**: Synopsys (Verdi配套)
- **全称**: Fast Signal DataBase
- **格式**: 专有二进制，未公开规范
- **核心优势**:
  - 高度压缩，文件体积小
  - 支持随机访问和层次化信号存储
  - 与VCS/Verdi深度集成，支持RTL ↔ 波形 ↔ 源码交叉跳转
  - 支持增量写入（仿真中即可查看）
- **局限**:
  - **专有格式**，未逆向工程成功；读取需链接Verdi提供的预编译库
  - 仅能在Synopsys生态内使用（Verdi、VCS、DVE）
  - 许可费用高昂
- **生态地位**: 大型SoC设计调试的黄金标准，但开源/学术用户无法使用

### 4. GHW — GHDL的原生VHDL波形格式

- **开发者**: Tristan Gingold (GHDL作者)
- **全称**: GHDL Waveform
- **设计动机**: VCD/EVCD无法表达VHDL的复杂类型（枚举、记录、多维数组、用户定义类型等）
- **特性**:
  - 支持VHDL全类型系统，包括自定义枚举和记录
  - GHDL默认dump所有信号事务到GHW文件（可配置过滤）
  - 提供共享库 `libghw` 供外部工具读取
  - 配套工具 `ghwdump` 用于文本化导出和回归测试
- **读取支持**: GTKWave（通过libghw）、Surfer（自有实现）
- **局限**:
  - 格式未完全固定，可能随GHDL版本迭代微调
  - 缺乏跨工具标准化，仅VHDL生态使用
  - 大型文件（300MB+）时GTKWave内存消耗可能较高
- **对Verilog用户**: GHW与Verilog无关，但若仿真器同时支持VHDL和Verilog，GHW格式可作为VHDL部分的「类型安全」dump方案

### 5. 厂商锁定格式 — WLF、VPD、SHM

| 格式 | 厂商 | 全称 | 特性 | 局限 |
|------|------|------|------|------|
| **WLF** | Mentor/Siemens | Wave Log File | Modelsim/QuestaSim原生格式 | 仅限Modelsim读取，通用性差 |
| **VPD** | Synopsys | VCD Plus Dump | VCS的增强VCD，二进制 | 仅限Synopsys工具链，DVE查看 |
| **SHM** | Cadence | Simulation History Manager | ncverilog/irun原生格式 | 仅限SimVision查看，Cadence锁定 |

- **共同问题**: 各厂商试图以波形格式锁定用户，导致跨工具协作困难
- **开源社区对策**: FST和VCD作为通用格式，被Surfer/GTKWave等工具统一支持，打破厂商锁定

### 6. 旧GTKWave格式 — LXT、LXT2、VZT

- **LXT/LXT2**: GTKWave早期自研格式，压缩率一般，已被FST取代
- **VZT**: 针对超大型设计的压缩格式，但复杂度高、生态支持有限
- **现状**: 维护模式，新项目应优先使用FST

### 7. 流式波形dump — 下一代方向

- **问题**: 所有文件格式（VCD/FST/FSDB）本质上都是「先dump到文件，再打开文件查看」的批处理模式
- **新需求**: 交互式调试要求「边仿真边查看」的流式模式
- **现有探索**:
  - **Surfer Server**: 远程按需拉取数据，不是真正的流式但接近
  - **Surfer与运行中仿真器集成**: 通过协议实时推送值变更
  - **GTKWave的FST「边写边读」**: 文件级别的流式支持，但非网络协议
- **技术挑战**:
  - 如何在不阻塞仿真主循环的情况下，将trace数据推送到网络/查看器？
  - 多线程仿真器中，trace数据可能来自多个线程，需要合并和排序
  - 压缩应该在推送到网络前进行，还是在查看器端解压？
- **可能方案**:
  - 在仿真器内部维护一个**环形缓冲区（Ring Buffer）**，每个worker线程将自己的值变更写入本地槽位，由专门的I/O线程定期合并并压缩推送
  - 采用**增量编码**（如FST的delta值）+ **LZ4实时压缩**（速度优先）
  - 协议设计：基于WebSocket或gRPC的轻量级波形流协议，支持「订阅信号子集」以减少带宽

## 格式对比总表

| 格式 | 类型 | 压缩率 | 随机访问 | 边写边读 | VHDL类型 | 开源 | 主要工具 |
|------|------|--------|----------|----------|----------|------|----------|
| **VCD** | ASCII文本 | 1x（基准） | ❌ | ⚠️部分 | ❌ | ✅ | 所有 |
| **FST** | 二进制 | ~50x | ✅ | ✅ | ⚠️有限 | ✅ | GTKWave, Surfer, VaporView |
| **FSDB** | 二进制 | ~50x+ | ✅ | ✅ | ✅ | ❌ | Verdi, VCS |
| **GHW** | 二进制 | ~10x | ✅ | ❓ | ✅ | ✅ | GTKWave, GHDL, Surfer |
| **WLF** | 二进制 | ~10x | ✅ | ❓ | ⚠️ | ❌ | Modelsim |
| **VPD** | 二进制 | ~20x | ✅ | ✅ | ❌ | ❌ | DVE, VCS |
| **SHM** | 二进制 | ~10x | ✅ | ✅ | ❌ | ❌ | SimVision |
| **LXT2** | 二进制 | ~5x | ✅ | ❌ | ❌ | ✅ | GTKWave（legacy） |

> 注：压缩率数据为经验估算，实际取决于设计信号密度和切换频率。FSDB和FST通常被认为在同一量级。

## 对 RTL 仿真器多线程化的启示

1. **波形格式的选择是架构决策，不是后期优化**
   - 如果目标是开源生态，FST是最务实的选择（Verilator、Icarus、GHDL已支持，GTKWave/Surfer/VaporView已能读取）
   - 如果目标是商业兼容，可考虑同时支持VCD（通用）和FSDB（客户需求），但FSDB需Synopsys许可
   - 对于VHDL支持，GHW是类型安全的选择，但会增加实现复杂度

2. **I/O子系统必须是独立的并发模块**
   - 波形dump不应阻塞仿真主循环。设计一个独立的I/O线程/线程池，通过无锁队列从仿真线程接收trace数据
   - 多线程仿真器尤其需要注意：每个仿真worker线程的trace事件需要按时间戳排序后写入，否则波形会乱序
   - 可参考FST的「多线程压缩」设计：当信号数量巨大时，将chunk压缩任务分发到多个CPU核心

3. **选择性dump是性能的生命线**
   - Verilator的 `--trace-depth`、`/*verilator tracing_off*/` 和GHDL的 `--read-wave-opt` 证明：允许用户精确控制「哪些模块、哪些信号、多深的层次」被dump，对大型设计至关重要
   - 多线程仿真器应提供运行时动态开关（通过VPI或自定义协议），让用户在仿真过程中调整追踪范围

4. **流式输出是交互式调试的基础设施**
   - 文件dump是事后分析，流式推送是实时调试。两者应共享同一trace采集管道
   - 建议在架构中预留一个抽象的「Trace Backend」接口，当前实现`FstFileWriter`和`VcdFileWriter`，未来可扩展为`WebSocketStreamer`或`SurferProtocolClient`
   - 流式协议应支持「订阅/取消订阅」语义，避免全量信号带宽爆炸

5. **VCD的兼容性不应被抛弃**
   - 尽管VCD效率低下，但它是最通用的格式。许多脚本工具、CI流程、教学场景依赖VCD
   - 建议将VCD作为「后备输出格式」，由用户显式选择 `--trace-vcd` 启用，默认使用FST

## 原文摘录

> "VCD is disk space hog with little or no compression. It requires you to read in the full file even if you want to extract the values of a signal out of thousands or more signals. You also can't extract values for a given time range without first processing the values of all time steps before that."
> — Tom Verbeure, GDBWave博客

> "FST files are roughly 50x smaller than equivalent VCD files. This is because it uses a two-stage compression scheme: in the first stage, it encodes signal value changes as delta values. During an optional second stage, the output of the first stage is compressed by the standard LZ4 or GZIP method."
> — Tom Verbeure, GDBWave博客

> "FST files are saved in multiple chunks. If you need to access data somewhere in the middle of a large simulation, it will only read in the chunks that contain the desired data, and skip whatever came before."
> — Tom Verbeure, GDBWave博客

> "If you're using the FST format as part of a Verilator testbench, make sure to NOT call the flush() method on the VerilatedFstC trace object after each simulation cycle. I did this in one of my testbenches and my simulation speed dropped by a factor of 20 compared to using VCD!"
> — Tom Verbeure, GDBWave博客（重要性能陷阱）

> "VCD/EVCD cannot handle certain signal types from the VHDL language. There is neither any equivalent in the VHDL LRM. So, the author of GHDL, Tristan Gingold, implemented an alternative format named GHW, for allowing all VHDL types to be dumped."
> — GHDL 官方文档

> "Verilator can produce waveform traces in the FST format, the native format of GTKWave. FST traces are much smaller and more efficient to write, but require the use of GTKWave."
> — Verilator 官方文档

> "FST is a trace file format developed by GTKWave. Verilator provides basic FST support. To dump traces in FST format, add the --trace-fst option. Currently, supporting both FST and VCD in a single simulation is not supported."
> — Verilator FAQ

## 相关链接

- [Verilator FAQ — FST波形生成](https://veripool.org/guide/latest/faq.html)
- [GHDL GHW 格式文档](https://ghdl.github.io/ghdl/ghw/index.html)
- [GDBWave 博客 — FST格式详解](https://tomverbeure.github.io/2022/02/20/GDBWave-Post-Simulation-RISCV-SW-Debugging.html)
- [Verilator Issue #2014 — FST dumping 100x slower than VCD](https://github.com/verilator/verilator/issues/2014)
- [Cocotb + Verilator FST 问题](https://github.com/cocotb/cocotb/issues/1709)
- [CSDN — Verilator FST波形文件中断损坏分析](https://blog.csdn.net/postgres8guard/article/details/156017659)
- [CSDN — 波形文件(WLF/VCD/FSDB/SHM/VPD)区别](https://blog.csdn.net/dajiao_zi/article/details/134684860)
- [EETOP — 各种波形文件的区别与生成](https://blog.eetop.cn/blog-523930-36594.html)
- [GTKWave 手册 — 格式概述](https://gtkwave.sourceforge.net/gtkwave.pdf)

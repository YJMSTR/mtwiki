---
title: RTL 仿真波形数据库格式与工具：VCD / FST / FSDB 全景对比
description: 系统梳理 RTL 仿真中主流波形数据库格式（VCD、FST、FSDB）的技术特性、压缩效率、随机访问性能与工具生态，为海量波形数据的高效存储和查询提供选型参考。
source_url: "https://github.com/toem/impulse.playground.eda"
source_type: "doc"  # github-pr, github-issue, blog, doc, paper, competition
author: "GTKWave / Synopsys / Surfer 社区文档与多篇技术博客综合"
date: "2024-2026"
tags: ["waveform-database", "VCD", "FST", "FSDB", "GTKWave", "Surfer", "RTL-simulation", "compression"]
keywords: ["VCD", "FST", "FSDB", "waveform", "GTKWave", "Surfer", "Verdi", "compression", "random-access"]
capture_date: "2026-07-02"
---

# RTL 仿真波形数据库格式与工具：VCD / FST / FSDB 全景对比

## 来源

- URL: 综合来源
  - GTKWave 官方文档：https://gtkwave.sourceforge.net/gtkwave.pdf
  - impulse EDA Playground (VCD/FST/FSDB 格式对比): https://github.com/toem/impulse.playground.eda
  - GDBWave 博客 (FST 格式深度解析): https://tomverbeure.github.io/2022/02/20/GDBWave-Post-Simulation-RISCV-SW-Debugging.html
  - UnityChip Verification 波形生成文档: https://open-verify.cc/mlvp/en/docs/env_usage/wave/
  - vcd2fst 手册页: https://umarcor.github.io/gtkwave/man/vcd2fst.1.html
  - Synopsys FSDB 技术文档: https://iccircle.com/static/upload/img20241018151626.pdf
  - Surfer 学术论文 (CAV 2025): https://link.springer.com/chapter/10.1007/978-3-031-98685-7_19
- 类型: doc / blog / paper 综合
- 作者: 综合 (Tony Bybell, Tom Verbeure, Synopsys, Linköping University 等)
- 日期: 2022–2026

## 摘要

RTL 仿真产生的波形数据量呈指数级增长：一个中等规模的 SoC 在数小时仿真中可生成数十 GB 的 VCD 文件。为了高效存储和快速查询，业界发展出多种波形数据库格式——从 ASCII 文本的 VCD，到开源压缩的 FST，再到商业的 FSDB。与此同时，波形查看工具生态也在不断演进：GTKWave 长期统治开源领域，Surfer 作为新兴 Rust 实现正带来交互式仿真与远程查看的新范式。本文综合对比各格式的压缩比、随机访问性能与工具链支持，并分析波形数据库对 RTL 仿真器多线程化的直接影响。

## 关键要点

### 波形格式全景对比

| 格式 | 类型 | 压缩比 (vs VCD) | 随机访问 | 支持工具 | 许可证 |
|------|------|----------------|----------|----------|--------|
| **VCD** (Value Change Dump) | ASCII 文本 | 1× (基准) | ❌ 线性扫描 | 几乎所有仿真器 | IEEE 标准 / 开放 |
| **FST** (Fast Signal Trace) | 二进制 + 两阶段压缩 | ~50× 更小 | ✅ 分块随机访问 | GTKWave, Surfer, Vaporview | BSD-like (开源) |
| **FSDB** (Fast Signal Database) | 二进制 + 专有压缩 | 5×–50× 更小 | ✅ 快速随机访问 | Verdi, GTKWave (有限), impulse (需 license) | Synopsys 专有 |
| **LXT2** | 块化压缩 | 优于 LXT | ✅ 块级随机访问 | GTKWave (deprecated in v4) | 开源 |
| **VZT** | 块化 + 字典压缩 | 最小文件体积 | ✅ 多核并行读取 | GTKWave (deprecated in v4) | 开源 |
| **VPD** (VCD Plus) | 二进制 | 优于 VCD | 有限 | VCS, GTKWave (需转换) | Synopsys 专有 |
| **WLF** | 二进制 | 中等 | 有限 | ModelSim | 专有 |

### 1. VCD： universally supported，但几乎全是缺点

VCD 是 IEEE-1364 标准化的文本格式，虽然被几乎所有仿真器原生支持，但存在严重缺陷：

- **磁盘空间黑洞**：无压缩，文本格式导致文件体积巨大。
- **全文件扫描**：即使只关心一个信号，也必须读取整个文件。
- **时间范围查询受限**：要提取某个时间范围的值，必须先处理之前所有时间步的数据。
- **内存占用高**：GTKWave 处理 VCD 时"要求最多内存"，且是"查看器处理最慢的格式"。

> "VCD is disk space hog with little or no compression. It requires you to read in the full file even if you want to extract the values of a signal out of thousands or more signals."
> — Tom Verbeure, GDBWave 博客

### 2. FST：开源生态的救星

FST (Fast Signal Trace) 由 GTKWave 作者 Tony Bybell 开发，是目前开源领域最主流的波形压缩格式。

**核心设计**：
- **两阶段压缩**：第一阶段将信号值变化编码为 delta 值；第二阶段用 LZ4 (默认) 或 GZIP 压缩输出。
- **分块存储**：文件按块存储，支持中间位置的随机访问——只需读取包含目标数据的块，跳过前面的块。
- **多线程压缩**：`vcd2fst` 的 `-p` 选项支持并行模式，开启 worker 线程在后台处理 FST 块压缩。
- **流式读取**：文件可在写入过程中读取，对长时间仿真特别有用。

**性能数据**（来自 GDBWave 实测）：
- 一个 VCD 文件 3,458,688 字节 → FST 仅 76,836 字节，**压缩比约 45×**。
- Tom Verbeure 的测试显示 FST 文件"大致比等效 VCD 文件小 50 倍"。

**vcd2fst 压缩选项**：
| 选项 | 说明 |
|------|------|
| `-4, --fourpack` | 使用 LZ4 压缩值变化数据（默认） |
| `-F, --fastpack` | 使用 fastlz 替代 LZ4 |
| `-Z, --zlibpack` | 使用 zlib 替代 LZ4 |
| `-c, --compress` | 关闭时对整块文件运行 gzip，进一步减小体积但增加打开时的解压开销 |
| `-p, --parallel` | 启用并行模式，多线程处理 |

### 3. FSDB：商业验证的黄金标准

FSDB (Fast Signal Database) 是 Synopsys Verdi 平台的原生格式，在 ASIC 验证领域广泛使用。

**优势**：
- 文件体积比 VCD 小 **5 到 50 倍**（Synopsys 官方数据）。
- Verdi 平台使用 FSDB 时，波形显示和信号反标速度更快。
- 支持直接从仿真器（VCS 等）dump，无需事后转换。

**限制**：
- **专有格式**：需要 Synopsys 许可证和 FSDB reader 库 (ffrAPI)。
- 第三方工具支持受限：GTKWave 需要配置 `fsdb2vcd`/`fsdbdebug` 转换器，或找到 `nffr`/`nsys` 库才能直接读取。
- 在 GTKWave 4 中，FSDB 支持计划被移除（deprecation），除非社区提出需求保留。

**工具链支持**：
- Verdi / nWave / nTrace：原生支持，最优体验。
- GTKWave：需配置转换器，或 FSDB reader 库。
- impulse：支持原生 FSDB 读取（需配置 FSDB Native Reader）。
- Vaporview：支持 FSDB（需外部库）。

### 4. Surfer：新一代波形查看器与交互式仿真

Surfer 是由 Linköping University 和 FOSSi Foundation 维护的 Rust 实现开源波形查看器，代表波形工具的新范式。

**关键特性**：
- **格式支持**：原生 VCD、FST、GHW，通过扩展可支持更多格式。
- **远程服务器模式**：在远程计算服务器上打开波形文件，本地 Surfer 实例按需拉取数据。利用内存中信号压缩，大幅减少网络传输量。
- **交互式仿真**：首个支持直接与运行中仿真器集成的开源查看器（之前仅限商业工具的紧密集成）。
- **类型系统扩展**：可扩展的 Translator 系统，支持 Chisel、Spade 等现代 HDL 的语义值渲染，而非仅显示原始比特向量。
- **性能**：Rust 实现 + 安全子集解析，避免内存漏洞；利用现代多核 CPU 快速加载。
- **嵌入能力**：可嵌入 Web 应用和 VSCode（Vaporview 扩展）。

**WAL (Waveform Analysis Language)**：Surfer 支持的脚本语言，可在波形上运行程序收集信息，支持相对时间求值（`signal@1` 检测值变化）和条件表达式。

### 5. GTKWave 格式弃用计划（GTKWave 4）

GTKWave 4 计划移除以下格式的原生支持：LXT、LXT2、VZT、IDX、AET2、VPD、WLF、FSDB。这将进一步巩固 **FST 作为开源波形格式的唯一标准**。

## 对 RTL 仿真器多线程化的启示

1. **波形 dump 的 I/O 瓶颈**：多线程 RTL 仿真器产生波形数据的速度可能远超单线程写入能力。FST 的多线程压缩（`vcd2fst -p`）和分块写入机制可以匹配仿真器的并行产出。

2. **增量/按需波形生成**：在回归测试中，无需 dump 所有信号。FSDB/FST 的流式写入 + 块级随机访问，使得"先快速仿真，再按需深入查看失败用例"成为可能。

3. **远程查看减少数据迁移**：Surfer 的 server 模式意味着波形文件可以留在服务器上，开发者只拉取感兴趣的区间，避免数十 GB 文件的网络传输。

4. **覆盖率和波形数据统一管理**：仿真回归产生的不只是波形，还有覆盖率数据库（.vdb/.ucdb）、日志和指标。这些异构数据需要统一的时序索引——这正是时序数据库（见 source-timeseries-db.md）的切入点。

5. **并行 dump 的锁竞争**：在多线程仿真器中，多个线程同时写入波形数据需要同步机制。FST 的块化结构天然适合"每个线程写独立块，后合并"的并行策略，值得在自研波形后端中借鉴。

## 原文摘录

> "VCD is the industry standard file format generated by most Verilog simulators and is specified in IEEE-1364. This is the slowest of the formats for the viewer to process and requires the most memory. However, this format is ubiquitous, and almost all tools support it, which is why native support remains."
> — GTKWave 官方文档, Supported Formats

> "FST files are roughly 50x smaller than equivalent VCD files. This is because it uses a two-stage compression scheme: in the first stage, it encodes signal value changes as delta values. During an optional second stage, the output of the first stage is compressed by the standard LZ4 or GZIP method."
> — Tom Verbeure, GDBWave 博客

> "An FSDB file is more compact than a standard VCD file. Typically, an FSDB file is about 5 to 50 times smaller than a VCD file. Using FSDB files, the Verdi platform displays waveform and back-annotated signal values faster."
> — Synopsys Verdi / Novas 文档

> "Surfer is also the first open-source tool to support direct integration with a running simulator. A custom waveform backend quickly loads VCD, FST or GHW files, taking advantage of modern multicore CPUs while minimizing user-facing latency and memory use."
> — Surfer: An Extensible Waveform Viewer, CAV 2025

> "It is planned to remove support for the following formats in GTKWave 4: LXT, LXT2, VZT, IDX, AET2, VPD, WLF, FSDB."
> — GTKWave GitHub, formats.md

## 相关链接

- [GTKWave 官方文档](https://gtkwave.sourceforge.net/gtkwave.pdf)
- [Surfer 项目官网](https://surfer-project.org)
- [GDBWave 博客 - FST 格式深度解析](https://tomverbeure.github.io/2022/02/20/GDBWave-Post-Simulation-RISCV-SW-Debugging.html)
- [impulse EDA Playground - 多格式波形示例](https://github.com/toem/impulse.playground.eda)
- [vcd2fst 手册](https://umarcor.github.io/gtkwave/man/vcd2fst.1.html)
- [Surfer 学术论文 (CAV 2025)](https://link.springer.com/chapter/10.1007/978-3-031-98685-7_19)
- [Vaporview - VSCode 波形查看器](https://github.com/Lramseyer/vaporview)
- [Tywaves - 基于 Surfer 的 Chisel 类型化波形查看器](https://arxiv.org/html/2408.10082)

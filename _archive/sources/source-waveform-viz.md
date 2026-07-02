---
title: "波形可视化工具全景调研"
description: "搜集主流波形可视化工具（GTKWave、Surfer、Verdi、WaveDrom、VaporView、Scansion）的技术特性、性能表现与生态地位，为RTL仿真器调试体验设计提供参考。"
source_url: "https://github.com/TM90/awesome-hwd-tools"
source_type: "doc"
author: "多源整合"
date: "2026-07-02"
tags: ["waveform", "visualization", "GTKWave", "Surfer", "Verdi", "VaporView", "WaveDrom", "debug"]
keywords: ["波形查看器", "VCD", "FST", "RTL调试", "开源EDA", "VSCode扩展"]
capture_date: "2026-07-02"
---

# 波形可视化工具全景调研

## 来源

- URL: 多源整合（GTKWave / Surfer / VaporView / WaveDrom / Scansion / Verdi）
- 类型: doc / github / blog
- 作者: 多源
- 日期: 2026-07-02

## 摘要

波形可视化是数字仿真调试的核心环节。本文汇总了当前RTL仿真生态中六款代表性波形工具的技术特性：GTKWave作为开源界的事实标准，拥有最广泛的格式支持；Surfer以Rust重写、强调扩展性与交互式调试集成；VaporView将波形查看嵌入VSCode，追求IDE原生体验；WaveDrom以JSON驱动生成时序图，擅长文档与沟通；Scansion是macOS原生VCD查看器；Synopsys Verdi则凭借FSDB格式与深度RTL集成，占据商业EDA的统治地位。这些工具在格式支持、性能、交互模式和扩展性上各有侧重，共同构成了RTL调试体验的多层竞争格局。

## 关键要点

### 1. GTKWave — 开源波形查看器的「老大哥」

- **开发者**: Tony Bybell（长期维护）
- **支持格式**: VCD、EVCD、FST、GHW、LXT/LXT2、VZT、SHM（有限支持）
- **核心特性**:
  - 信号分组、颜色编码、模拟波形显示（Analog Step/Interpolate）
  - 基数切换（Bin/Hex/Dec/ASCII/Analog）
  - 会话保存（`.gtkw`文件）可快速恢复调试场景
  - Tcl脚本与回调支持，允许外部应用远程控制
- **性能**: FST格式打开速度远快于VCD；但GTKWave本身为单线程设计，大型文件UI可能卡顿
- **生态地位**: 几乎所有开源Verilog/VHDL仿真器的默认配套工具（Verilator、Icarus、GHDL）

### 2. Surfer — 现代、可扩展的Rust波形查看器

- **开发团队**: Linköping University（Frans Skarman, Oscar Gustafsson, Lucas Klemmer等）
- **论文**: *Surfer: An Extensible Waveform Viewer* (CAV 2025)
- **支持格式**: VCD、FST、GHW（通过`wellen`解析库）
- **核心特性**:
  - **首个开源波形查看器支持与运行中仿真器的直接集成**（交互式调试）
  - 可扩展的Translator系统：支持RISC-V/LA64/MIPS指令解码、现代HDL类型显示
  - 远程服务器模式：在计算服务器上打开波形，本地Surfer按需拉取数据，减少数十GB的VCD传输
  - 基于Rust的安全解析，避免内存漏洞；解析库`wellen`已外供给VaporView等工具使用
  - 键盘驱动界面、可配置性高、Web版本可用
- **性能**: 多核CPU并行解析；延迟优先设计——先加载元数据和信号层次，后台持续解析值变更数据
- **生态地位**: 2024-2025年快速崛起的开源波形查看器，被RISC-V社区和开源EDA广泛采用

### 3. VaporView — VSCode内的原生波形查看器

- **开发者**: Lramseyer（个人开源项目）
- **GitHub**: https://github.com/Lramseyer/vaporview
- **Stars**: 343+（截至2026-06）
- **支持格式**: VCD、FST、GHW（通过WASM编译的`wellen`库）；FSDB（需外部库）
- **核心特性**:
  - **VSCode原生集成**：无需离开编辑器即可查看波形，支持`.vcd`/`.fst`文件直接打开
  - **WebAssembly高性能解析**：React渲染引擎 + 优化的WASM解析器，支持大文件
  - **终端链接集成**：自动识别日志中的时间戳（如`@50000`）和网表路径（`top.submodule.signal`），Ctrl+Click跳转
  - **RTL联动**：支持SV Pathfinder（RTL链接追踪）、slang-server（SystemVerilog语言服务器）等扩展互操作
  - **远程波形查看**：通过VSCode Remote Development或Surfer Server协议连接远程机器
  - **WaveDrom导出**：可将选区波形导出为WaveDrom JSON
- **License**: AGPL-3.0，作者承诺所有功能永久免费开源

### 4. WaveDrom — JSON驱动的时序图渲染引擎

- **开发者**: Alexey Drom（drom）
- **官网**: https://wavedrom.com/
- **核心特性**:
  - 基于WaveJSON（JSON格式）描述数字时序图，实时渲染为SVG/PNG
  - 浏览器内双面板编辑器：左侧输入JSON，右侧即时渲染波形
  - 支持标准波形字符：`p`（时钟）、`0`/`1`/`x`/`z`/`=`（数据）、`.`（无变化）
  - 支持相位、周期、边缘标注、spacer分割等高级时序图特性
- **应用场景**:
  - 文档和论文中的协议时序图（如DDR DRAM访问时序）
  - 教学演示（RISC-V流水线信号时序）
  - 与VaporView等工具联动，从仿真波形导出为时序图
- **生态**: VSCode扩展（`waveform-render-vscode`）、npm包、Chrome扩展、GitHub渲染支持

### 5. Scansion — macOS原生波形查看器

- **平台**: macOS only
- **支持格式**: VCD、开放XML格式的TLM（Transaction Level Modeling）trace
- **核心特性**:
  - 原生macOS应用，利用OSX技术如iChat Theater
  - 支持模拟波形显示（混合信号数据）
  - 支持Transaction Level Modeling事件追踪，超越纯信号波形
  - 在macOS上比GTKWave（X11依赖）更稳定
- **现状**: 更新缓慢（最后版本1.12，2015年左右），但仍是macOS用户查看VCD的轻量选择

### 6. Synopsys Verdi — 商业EDA的调试黄金标准

- **支持格式**: FSDB（Fast Signal DataBase，专有格式）、VCD
- **核心特性**:
  - FSDB格式：高度压缩、支持随机访问、层次化信号存储，是VCD的「商业级替代」
  - 与VCS/NC-Verilog深度集成，支持RTL ↔ 波形 ↔ 源码的交叉跳转
  - 自动信号追踪、协议分析器、功耗分析集成
  - 支持后仿真调试（Post-simulation）与实时仿真调试
- **局限**: FSDB为专有格式，需链接Verdi提供的预编译二进制库；无法被开源工具直接读取
- **地位**: 大型SoC设计调试的事实标准，但高昂许可费限制了个人/学术用户的使用

## 对 RTL 仿真器多线程化的启示

1. **波形dump格式直接影响I/O性能**：FST相比VCD体积缩小约50倍，且支持多线程压缩；Verilator的`--trace-fst`选项虽然可能引入仿真 slowdown（早期报告有100x问题），但文件体积和网络传输优势显著。对于多线程RTL仿真器，选择/设计一种高效的流式波形格式是核心竞争力的组成部分。

2. **交互式调试是差异化竞争点**：Surfer的「直接集成运行中仿真器」能力和VaporView的「VSCode终端链接跳转」代表了调试体验的新方向——不再「先跑完仿真再回头分析波形」，而是让波形查看器与仿真器实时联动。这要求仿真器暴露VPI/VHPI或自定义协议接口，允许外部工具查询当前信号值和仿真状态。

3. **解析性能与并发设计**：Surfer的`wellen`库使用Rust safe subset避免内存漏洞，并采用「先加载元数据、后台解析值数据」的策略，值得多线程仿真器的波形子系统借鉴。将波形写入（仿真端）和波形读取（查看端）解耦为独立的并发任务，可以显著降低用户感知的延迟。

4. **远程调试是刚需**：大型设计仿真常在服务器集群上运行，波形文件可达数十GB。Surfer的远程服务器模式（按需拉取压缩数据）和VaporView的VSCode Remote支持都瞄准这一痛点。多线程RTL仿真器应考虑内置轻量级波形服务器，支持HTTP/WebSocket或Surfer兼容协议，让用户无需下载完整文件即可开始调试。

## 原文摘录

> "Surfer can be easily embedded in web-applications and features a novel remote control protocol. It is also the first open-source viewer to support direct integration with a running simulator."
> — Surfer CAV 2025 论文

> "VCD is a disk space hog with little or no compression. It requires you to read in the full file even if you want to extract the values of a signal out of thousands or more signals."
> — Tom Verbeure, GDBWave博客

> "FST files are roughly 50x smaller than equivalent VCD files. This is because it uses a two-stage compression scheme: in the first stage, it encodes signal value changes as delta values. During an optional second stage, the output of the first stage is compressed by the standard LZ4 or GZIP method."
> — Tom Verbeure, GDBWave博客

> "This extension was originally written by one person, with a full time job that doesn't involve anything to do with writing javascript or typescript."
> — VaporView README（开源社区个人项目的典范）

## 相关链接

- [GTKWave 官网](https://gtkwave.sourceforge.net/)
- [Surfer 项目](https://surfer-project.org/) | [GitLab](https://gitlab.com/surfer-project/surfer) | [CAV 2025 论文 PDF](https://kevinlaeufer.com/pdfs/surfer_cav2025.pdf)
- [VaporView GitHub](https://github.com/Lramseyer/vaporview)
- [WaveDrom 编辑器](https://wavedrom.com/editor.html)
- [Scansion (MacUpdate)](https://scansion.macupdate.com/)
- [GDBWave 博客](https://tomverbeure.github.io/2022/02/20/GDBWave-Post-Simulation-RISCV-SW-Debugging.html)
- [Verilator FAQ — FST波形](https://veripool.org/guide/latest/faq.html)
- [ChipVerify — GTKWave波形分析教程](https://chipverify.com/rtl-synthesis/waveform-analysis-with-gtkwave)

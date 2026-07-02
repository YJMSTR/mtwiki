---
title: "SystemVerilog / UVM 编译器与运行时：开源工具链生态"
description: 梳理开源SystemVerilog编译器生态，包括Surelog/UHDM解析器、Verilator仿真器UVM支持进展、Verible开发工具套件、slang编译器，分析其对RTL仿真器多线程化的影响
source_url: "https://www.chipsalliance.org/news/open-source-systemverilog-tools-in-asic-design/"
source_type: "doc"
author: "CHIPS Alliance / Antmicro / Google"
date: "2021-08-04"
tags: ["systemverilog", "surelog", "uhdm", "verilator", "verible", "slang", "uvm", "open-source-eda"]
keywords: ["SystemVerilog compiler", "Surelog parser", "Verilator UVM", "Verible lint", "slang SystemVerilog", "开源SystemVerilog", "UHDM"]
capture_date: "2026-07-02"
---

# SystemVerilog / UVM 编译器与运行时

## 来源

- URL: https://www.chipsalliance.org/news/open-source-systemverilog-tools-in-asic-design/
- URL: https://github.com/chipsalliance/Surelog
- URL: https://github.com/chipsalliance/UHDM
- URL: https://github.com/chipsalliance/verible
- URL: https://github.com/MikePopoloski/slang
- URL: https://github.com/verilator/verilator
- 类型: doc / github
- 作者: CHIPS Alliance / Antmicro / Google / Mike Popoloski / Verilator Team
- 日期: 2021-2026

## 摘要

SystemVerilog是当今ASIC/FPGA设计的事实标准语言，但其复杂性使开源工具链长期滞后于商业EDA。近年来，CHIPS Alliance主导的开源生态快速突破：Surelog/UHDM提供了完整的SystemVerilog 2017解析和中间表示；Verilator从编译型仿真器向支持UVM的通用仿真器演进；Verible成为Google OpenTitan等项目的标准开发工具；slang则以极高速度和标准合规性成为新一代前端引擎。这些工具共同构建了一个日益完整、可与商业工具互补甚至替代的开源SystemVerilog生态，对RTL仿真器多线程化具有直接的基础设施意义。

## 关键要点

### 1. 开源SystemVerilog工具全景

| 工具 | 类别 | 主要功能 | 语言 | 标准合规 | GitHub Stars | 活跃度 |
|------|------|----------|------|----------|-------------|--------|
| **Surelog** | 解析器/编译器 | SV2017预处理、解析、 elaboration、UHDM生成 | C++ | SV2017 | 高 | 非常活跃 |
| **UHDM** | 数据模型 | SystemVerilog对象模型的完整VPI表示 | C++ | SV2017 | 中 | 活跃 |
| **Verilator** | 仿真器 | SV→C++/SystemC编译型仿真 | C++ | 可综合子集+ | 极高 | 非常活跃 |
| **Verible** | 开发者工具 | 解析器、Linter、Formatter、LSP | C++ | SV2017 | 高 | 活跃 |
| **slang** | 编译器/库 | 词法/语法/类型检查/elaboration | C++ | SV2017 | 高 | 非常活跃 |
| **sv2v** | 转换器 | SystemVerilog → Verilog | Haskell | 合成子集 | 中 | 活跃 |
| **sv-parser** | 解析库 | Rust实现的SV2017解析器 | Rust | SV2017 | 低 | 维护中 |

### 2. Surelog + UHDM：统一SystemVerilog前端

**Surelog**（Alain Dargelas创建，Google赞助，CHIPS Alliance托管）：
- **完整前端**：SystemVerilog 2017预处理、解析、elaboration、UHDM编译
- **多线程解析**：使用Antlr4生成器，支持多线程编译大型文件/模块
- **增量编译**：基于Google Flatbuffers的持久化AST，支持增量编译
- **多语言API**：提供C/C++ VPI API和Python AST API
- **工程验证**：成功解析并综合了BlackParrot、OpenTitan等复杂开源设计
- **工具集成**：已集成到Yosys（SystemVerilog plugin）、Verilator（自定义前端）、SiliconCompiler等

**UHDM（Universal Hardware Data Model）**：
- **标准VPI接口**：完整的IEEE SystemVerilog对象模型，符合VPI标准
- **可序列化**：可持久化到磁盘，作为工具间交换格式
- **解耦架构**：解析器只需实现一次，其他工具（综合、仿真、形式验证）通过UHDM消费数据
- **生态优势**：任何改进统一惠及所有下游工具，避免重复造轮子

> "Surelog is only a language frontend designed to integrate well with other tools – it outputs an elaborated design in an intermediate format called UHDM. This is much easier than implementing a full SystemVerilog parser within each tool." — CHIPS Alliance Blog (2021)

### 3. Verilator：从编译型仿真器到UVM支持

**Verilator**是开源硬件仿真领域最成功的项目之一，核心特点：
- **编译型仿真**：将Verilog/SystemVerilog编译为高度优化的C++/SystemC，仿真速度比传统事件驱动仿真器快10-100倍
- **多线程支持**：`--threads` 选项支持多线程并行仿真，利用多核CPU
- **SystemVerilog扩展**：持续扩展SV支持，包括类、随机化、断言、fork/join等
- **DPI-C/VPI**：支持与C++测试台和Python（cocotb）集成

**Verilator 5.x SystemVerilog支持状态**（2025年6月）：

| 功能类别 | 支持状态 | 备注 |
|----------|----------|------|
| DPI-C | ✅ 完整 | C++集成首选，最稳定快速 |
| VPI | △ 部分 | 读基本完整，写受限制（packed logic/scalar） |
| 类/OOP | △ 部分 | 嵌套/生成类已支持，virtual方法/`$cast`未支持 |
| 随机化 | △ 部分 | `solve...before`稳定，`randc`周期保证未实现 |
| 断言(SVA) | △ 部分 | 即时断言支持，时序/序列属性未实现 |
| 覆盖率 | △/✗ | `covergroup`未实现，单周期`cover property`部分支持 |
| fork/join | △ 部分 | v5.034稳定性提升，automatic变量生命周期有警告 |
| virtual interface | ✗ 未实现 | UVM支持的主要障碍之一 |
| 4值/Z | △ 部分 | 2值为主体，`--x-assign`随机化X |

**UVM支持进展**：
- Antmicro、Western Digital、Google、PlanV等组织正推进Verilator的UVM支持
- Verilator 5.0引入了事件驱动仿真能力（`--timing`），为UVM奠定基础
- PlanV建立了CI系统，持续测试pyuvm和sv-uvm模型
- 当前已可运行基础uvm_test（如异步FIFO验证），但完整UVM库支持仍在进行中

> "Verilator is commonly used for simulation and testing, but originally wasn't considered capable of handling UVM testbenches due to the lack of event-driven simulation. Since Verilator 5.0, this has changed." — CHIPS Alliance (2023)

### 4. Verible：SystemVerilog开发者工具套件

**Verible**（Google创建，CHIPS Alliance托管）：
- **解析器**：`verible-verilog-syntax`，支持JSON导出语法树，Python wrapper
- **风格检查器**：`verible-verilog-lint`，基于语法树模式匹配，支持规则配置和豁免
- **格式化器**：`verible-verilog-format`，自动管理空白、缩进、换行，支持增量格式化
- **语言服务器**：`verible-verilog-ls`，实现LSP协议，支持VS Code等IDE实时lint和格式化
- **词法差异**：`verible-verilog-diff`，比较两个文件的等价性
- **代码混淆**：保护代码敏感信息

**核心亮点**：
- OpenTitan等安全项目大量使用Verible进行代码规范 enforcement
- GitHub Action可用，直接集成CI/CD
- 支持自定义规则文件（`.rules.verible_lint`、`.rules.verible_format`）
- 与Verilator、Surelog等工具互补，形成从lint到仿真到综合的完整开源流程

### 5. slang：最快的SystemVerilog前端

**slang**（Mike Popoloski，MIT许可）：
- **速度最快**：根据CHIPS Alliance sv-tests基准，slang是目前最快且最合规的开源SystemVerilog前端
- **手写递归下降解析器**：与Antlr4生成器不同，采用手工编写的递归下降解析器，性能更高
- **完整功能**：词法、预处理、解析、类型检查、elaboration全功能
- **鲁棒性**：即使源码有错误也能继续编译，适合编辑器实时高亮和补全场景
- **AST可回写**：解析树可以无损回写到原始源码，支持重构和代码生成工具
- **多绑定**：提供C++库、命令行工具、Python绑定（`pyslang`），以及Rust绑定（`slang-rs`）
- **编辑器支持**：可作为语言服务器引擎，支持实时错误检测

**使用场景**：
- 快速语法检查和linting工具
- 项目AST导出JSON进行静态分析
- 综合/仿真工具的前端（如Qihe编译器的SystemVerilog模式）
- 编辑器语言服务器（如slang-server）

> "slang is the fastest and most compliant SystemVerilog frontend (according to the open source chipsalliance test suite)." — sv-lang.com

### 6. 其他工具补充

**sv2v**（Haskell）：SystemVerilog到Verilog的转换器，帮助仅支持Verilog的工具（如部分版本的Yosys）处理SystemVerilog输入。

**sv-parser**（Rust）：IEEE 1800-2017完全合规的Rust解析库，适合Rust生态的硬件工具开发。

**sv-tests**：CHIPS Alliance维护的SystemVerilog测试套件，用于跟踪各工具的语言特性支持状态，是开源EDA的重要基础设施。

## 对 RTL 仿真器多线程化的启示

1. **Surelog/UHDM作为统一前端**：若RTL仿真器需要支持SystemVerilog输入，直接集成Surelog/UHDM比自己实现完整SV前端更经济。Verilator的UHDM前端尝试、Yosys的SystemVerilog plugin均证明了此路径的可行性。

2. **slang的高性能解析**：对于需要频繁解析和重新编译的增量仿真场景（如交互式调试），slang的极高解析速度（比Antlr4-based工具快数倍）意味着更短的编译-仿真迭代周期，这对多线程仿真器的用户体验至关重要。

3. **Verilator的多线程架构验证**：Verilator的 `--threads` 模式是编译型RTL仿真器多线程化的成功先例。其将设计分区到多个线程、通过MTask调度并行执行的策略，为多线程RTL仿真器提供了直接参考。但Verilator不支持动态调度（如Verilog event queue），因此事件驱动仿真器的多线程化需要不同策略。

4. **UVM支持对验证生态的影响**：UVM是工业界验证的事实标准，Verilator对UVM的支持进展将决定开源工具链能否进入主流验证流程。RTL仿真器若计划支持UVM，需要提前规划：类支持、随机化、约束求解、覆盖率收集、虚拟接口等功能的并行化实现。

5. **Verible的LSP与增量编译**：Verible的语言服务器支持增量格式化，而RTL仿真器若能支持增量编译（仅重新编译变更模块），结合LSP的实时错误反馈，可构建类似软件开发体验的硬件开发环境。这是提升HDL开发效率、降低多线程仿真调试门槛的重要方向。

6. **开源工具链的协同效应**：Surelog(解析) → UHDM(中间表示) → Verilator(仿真) / Yosys(综合) → OpenROAD(物理设计) 正在形成完整的开源ASIC流程。RTL仿真器多线程化作为此流程的关键环节，与上游解析器和下游综合工具的接口设计需要统一规划。

## 原文摘录

> "Surelog, originally created and led by Alain Dargelas, aims to be a fully-featured SystemVerilog 2017 preprocessor, parser, and elaborator. It's a modern tool and thus follows the current version of the SV standard without unnecessary deviations or legacy baggage." — CHIPS Alliance (2021)

> "Verilator is a shining example of a widely-accepted open source tool which provides state-of-the-art results in the ASIC design space. It is commonly used for simulation and testing." — CHIPS Alliance (2023)

> "slang is a software library that provides various components for lexing, parsing, type checking, and elaborating SystemVerilog code. It is the fastest and most compliant SystemVerilog frontend." — sv-lang.com

> "Verible is a suite of SystemVerilog developer tools, including a parser, style-linter, formatter and language server." — chipsalliance.github.io/verible

> "No open-source simulator is able to compile the full UVM library as of 2023. This is due to the incredible undertaking of providing complete support for the extremely intricate non-synthesizable superset of SystemVerilog." — DVCon Paper (Verilator + UVM-SystemC)

## 相关链接

- [Surelog GitHub](https://github.com/chipsalliance/Surelog)
- [UHDM GitHub](https://github.com/chipsalliance/UHDM)
- [Verilator GitHub](https://github.com/verilator/verilator)
- [Verible GitHub](https://github.com/chipsalliance/verible)
- [slang GitHub](https://github.com/MikePopoloski/slang)
- [slang 文档](https://sv-lang.com)
- [sv-tests](https://github.com/chipsalliance/sv-tests)
- [sv2v GitHub](https://github.com/zachjs/sv2v)
- [PlanV Verilator UVM CI](https://planv.tech/2024/10/08/enabling-uvm-support-in-verilator-series-our-ci-system-and-test-models/)
- [Verilator 5 SystemVerilog支持指南](https://qiita.com/sukimaengineer/items/e4ccaeb7aa3ac874d6da)
- [Verilator + UVM-SystemC DVCon论文](https://dvcon-proceedings.org/wp-content/uploads/90555.pdf)
- [Yosys SystemVerilog Plugin](https://github.com/chipsalliance/yosys-f4pga-plugins)

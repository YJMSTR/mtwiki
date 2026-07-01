---
title: SystemVerilog 前端 AST 设计与解析技术：Surelog、slang、UHDM 与解析器组合子
description: 梳理 SystemVerilog 前端领域的主流解析器（Surelog、slang、Verible 等）及其 AST/UHDM 设计，并考察解析器组合子（parser combinator）在硬件语言处理中的潜在应用。
source_url: "https://github.com/chipsalliance/Surelog"
source_type: "doc"
author: "Alain Marcel (Surelog), Mike Popoloski (slang), 等"
date: "2019-2025"
tags: ["Surelog", "slang", "UHDM", "AST", "SystemVerilog", "parser", "parser-combinator"]
keywords: ["Surelog AST UHDM", "slang AST design", "SystemVerilog parser performance", "parser combinator hardware"]
capture_date: "2026-07-02"
---

# SystemVerilog 前端 AST 设计与解析技术：Surelog、slang、UHDM 与解析器组合子

## 来源

- URL: 
  - Surelog: [GitHub - chipsalliance/Surelog](https://github.com/chipsalliance/Surelog)
  - slang: [GitHub - MikePopoloski/slang](https://github.com/MikePopoloski/slang) / [slang 文档](https://sv-lang.com/parsing.html)
  - UHDM: [GitHub - alainmarcel/uhdm2rtlil](https://github.com/alainmarcel/uhdm2rtlil)
  - SV Tests: [SV-Tests Results](https://chipsalliance.github.io/sv-tests-results/)
  - Parser Combinator in Hardware: [Hardware Sequence Combinators](https://papers.academic-conferences.org/index.php/iccws/article/download/1965/1913/7550)
- 类型: github / doc / paper
- 作者: Alain Marcel, Mike Popoloski, CHIPS Alliance 等
- 日期: 2019–2025

## 摘要

SystemVerilog 2017 的语法复杂度（宏展开、generate、参数化类、UVM 等）使得一个「完整前端」成为硬件 EDA 领域的稀缺基础设施。当前开源社区形成了两大主流路线：

1. **以 Surelog 为代表的「全功能前端」**：基于 ANTLR 4 生成解析器，输出持久化的 **UHDM（Universal Hardware Data Model）** 数据库，支持 preprocessor → parser → elaborator 的完整流程，并提供 Python/C++ VPI API 供下游工具消费。
2. **以 slang 为代表的「现代 C++ 前端」**：采用手写递归下降 + 语法 DSL 生成 C++ 语法树类，追求 **最快速、最符合标准** 的解析体验，同时保证 parse tree 可 round-trip 回原始源码，便于重构和 formatter 工具。

此外，**解析器组合子（parser combinator）** 虽然在软件语言（Haskell/Scala）中已成熟，但在硬件语言解析领域仍属边缘探索。本文同时搜集其在硬件包解析（如 Ethernet frame）中的 FPGA 实现，以评估其用于 DSL 前端的可能性。

## 关键要点

- **Surelog 的架构与 AST 持久化**：Surelog 使用 ANTLR 4 生成 preprocessor 与 parser，其 AST 被序列化到磁盘（Cap'n Proto / Google Flatbuffers），实现增量编译。解析阶段支持多线程，大文件可按行数切分并行处理。最终输出 UHDM 数据库，内含完整的 VPI 对象模型，可被 Verilator、Yosys、仿真器、综合工具等直接读取。
- **UHDM 作为通用硬件数据模型**：UHDM 是 Surelog 的「编译后产物」，提供 IEEE 标准 VPI 接口。它不仅是 AST 的序列化，更是经过 elaboration 的「设计数据库」，包含模块展开、参数传递、接口绑定等完整语义。Yosys 的 `read_uhdm` / `read_systemverilog` 插件正是通过 UHDM 实现完整的 SystemVerilog 综合支持。
- **slang 的语法树设计**：slang 的解析流程分为两层：先产生 **Concrete Syntax Tree (CST)**，再构造 **Abstract Syntax Tree (AST)**。CST 由 `syntax::SyntaxNode` 派生类构成，每个节点链接到父节点，叶子是 `Token`（包含 trivia 如注释和空白）。这种设计保证「从源码到源码」的 round-trip 能力，非常适合 formatter 和语言服务器（LSP）。
- **slang 的 Visitor 模式**：slang 内置 SyntaxVisitor 与 AST Visitor，支持对语法树进行模式匹配和遍历。开发者可以自定义 visitor 实现 lint 规则或代码生成。例如，formatter 工具可通过 visitor 读取 CST 并重写源码，同时保留 trivia 的位置信息。
- **解析器性能对比（SV-Tests）**：根据 CHIPS Alliance 维护的 sv-tests 测试集，**slang 在解析合规性上表现最优**，几乎通过全部 3427 项测试；Surelog 紧随其后（约 3114 项）。从资源消耗看，slang 最大内存仅约 25 MB，而 Surelog 需要 3184 MB；slang 用户时间 15s，Surelog 为 1598s。这表明手写递归下降 + 增量解析在性能上远超 ANTLR 生成方案。
- **解析器组合子的硬件探索**：在 FPGA 领域，parser combinator 的概念被用于**硬件包解析**（如 Ethernet frame、JSON 数字）。Hammer 等库提供了 C 语言实现的组合子原语，可在 FPGA 上实例化为 LALR parser。虽然这主要用于网络协议而非 HDL 前端，但证明了「组合子 → 硬件结构」的映射是可行的。
- **其他前端工具**：
  - **Verible**（Google）：提供 parser、linter、formatter 和语言服务器，可解析未预处理源码。
  - **sv-parser**（Rust）：返回 concrete syntax tree，完全合规 IEEE 1800-2017。
  - **hdlConvertor**：基于 ANTLR4 的 C++/Python 解析器，支持 Verilog/VHDL。
  - **tree-sitter-verilog**：为编辑器提供增量解析支持。

## 对 RTL 仿真器多线程化的启示

- **AST 的线程安全设计是前端并行化的基础**：Surelog 的「多线程解析 + 大文件切分」策略证明，SystemVerilog 前端本身可以高度并行。对于 RTL 仿真器，如果需要在编译阶段并行处理多个模块/文件，可以借鉴 Surelog 的「按文件/模块切分 + 增量缓存」思路。
- **UHDM 作为跨工具互操作层**：若 RTL 仿真器希望与综合工具、形式验证工具共享前端结果，采用 UHDM 作为标准数据交换格式可避免重复解析。Surelog → UHDM → Verilator/Yosys 的成功案例已经验证了这一路径的可行性。
- **slang 的「round-trip CST」启示**：在仿真器需要支持源码级调试（如设置断点、单步执行）时，保留从 AST 到源码的精确映射（包括行号、列号、注释）至关重要。slang 的 trivia 机制可以作为仿真器 debug info 的参考模型。
- **解析器组合子用于轻量级 DSL**：如果 RTL 仿真器需要引入一种轻量级的「测试向量 DSL」或「断言子语言」，解析器组合子（如 Rust 的 `nom` 或 C++ 的组合子库）可能是比 ANTLR 更灵活、更易于嵌入的选择。虽然目前尚无成熟案例，但 Hammer 在 FPGA 上的实现给出了「组合子 → 硬件/软件混合解析」的可能性。
- **性能标杆**：slang 的极低内存占用和高速解析表明，对于 RTL 仿真器的前端（尤其是 linter 或增量编译场景），手写递归下降 + arena allocator 比通用 parser generator 更具性能优势。若仿真器需要「边编辑边编译」的交互体验，slang 的架构是更好的参考。

## 原文摘录

> "Surelog is a SystemVerilog 2017 Pre-processor, Parser, Elaborator, UHDM Compiler. Provides IEEE Design/TB C/C++ VPI and Python AST API."
> —— Surelog GitHub 首页

> "slang is a software library that provides various components for lexing, parsing, type checking, and elaborating SystemVerilog code... slang is the fastest and most compliant SystemVerilog frontend."
> —— slang GitHub 首页

> "The parse tree should round trip back to the original source, making it easy to write refactoring and code generation tools."
> —— slang 设计目标

> "In recent years there has been considerable interest in expanding the expressiveness of parsers... others employ combinators: primitive elemental parsers with well-defined methods for combining them into more expressive parsers."
> —— Hardware Sequence Combinators Paper

## 相关链接

- [Surelog GitHub](https://github.com/chipsalliance/Surelog)
- [slang GitHub](https://github.com/MikePopoloski/slang)
- [slang 文档 - Parsing](https://sv-lang.com/parsing.html)
- [SV-Tests 结果](https://chipsalliance.github.io/sv-tests-results/)
- [UHDM 到 Yosys 插件](https://github.com/alainmarcel/uhdm2rtlil)
- [Hardware Sequence Combinators Paper](https://papers.academic-conferences.org/index.php/iccws/article/download/1965/1913/7550)

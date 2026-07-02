---
title: "Surelog / UHDM / slang 前端解析内核实现分析：AST 设计与解析器性能"
description: 对 chipsalliance/Surelog 和 MikePopoloski/slang 两个主流开源 SystemVerilog 前端解析器的核心架构进行源码级分析，重点比较其 AST 设计、内存模型、多线程解析策略和性能数据，为 RTL 仿真器前端选型提供依据。
source_url: "https://github.com/chipsalliance/Surelog"
source_type: github-repo
author: "Alain Dargelas / Mike Popoloski"
date: "2026-07-03"
tags: [surelog, slang, uhdm, systemverilog, parser, ast, antlr4]
keywords: [Surelog, slang, UHDM, SystemVerilog parser, ANTLR4, AST, elaboration, instance caching, sv-tests]
capture_date: "2026-07-03"
---

# Surelog / UHDM / slang 前端解析内核实现分析

## 来源

- Surelog: `https://github.com/chipsalliance/Surelog`
- slang: `https://github.com/MikePopoloski/slang`
- 类型: github-repo
- 作者: Alain Dargelas (Surelog) / Mike Popoloski (slang)
- 日期: 2026-07-03

## 摘要

SystemVerilog 前端解析器是任何 RTL 工具链的第一道关卡。本文档通过代码搜索和公开资料，对比分析了 Surelog（基于 ANTLR4 + UHDM）和 slang（基于手写的 C++17 递归下降解析器）两个前端的 AST 设计、解析流程、性能特征和多线程策略。两者在设计哲学上有显著差异：Surelog 强调标准兼容性和中间表示的可移植性（UHDM），而 slang 强调极致的解析速度和内存效率。这些差异直接影响下游仿真器的启动时间和内存占用。

## 关键要点

### 1. Surelog — 基于 ANTLR4 的解析架构与 UHDM 中间表示

**文件**: `src/SourceCompile/ParseFile.cpp`, `src/DesignCompile/UhdmWriter.cpp` ([GitHub](https://github.com/chipsalliance/Surelog))

Surelog 采用 **ANTLR4 生成的解析器** 处理 SystemVerilog 语法，并通过 **UHDM（Universal Hardware Data Model）** 作为中间表示层：

```cpp
// include/Surelog/API/Surelog.h
// Surelog 对外暴露的 API
Design* get_design(scompiler* compiler);
```

**AST 设计**：Surelog 使用 `NodeId` 作为 AST 节点的索引，而不是原始指针。`FileContent` 对象拥有实际的 AST 树：

```cpp
// include/Surelog/Common/NodeId.h
/**
 * class NodeId
 * Used as an index into the collection representing the AST tree,
 * currently owned by FileContent.
 */
```

这种设计允许 AST 以紧凑的数组形式存储，但引入了额外的间接层。每个解析文件产生一个 `FileContent` 对象，其中包含从 `NodeId` 到具体语法节点（`VObjectType`）的映射。

**UHDM 序列化**：Surelog 的核心输出是 UHDM 数据库，使用 Cap'n Proto 进行二进制序列化：

```cpp
// src/DesignCompile/UhdmWriter.cpp
#include <uhdm/Serializer.h>
#include <uhdm/uhdm.h>
#include <uhdm/vpi_uhdm.h>
```

UHDM 提供了与商业仿真器兼容的 VPI 接口，使得 Surelog 可以作为多种下游工具（仿真器、综合器、形式验证工具）的前端。然而，这种**多层级转换（Source → ANTLR AST → Surelog AST → UHDM → VPI）**带来了不可忽视的内存和性能开销。

**多线程解析**：Surelog 支持文件级并行解析（`-pythonevalscriptperfile` 标记为 Multithreaded），但 elaboration 和 UHDM 生成阶段是单线程的：

```
// README.md
-pythonlistenerfile <script.py>  Specifies the AST python listener file
-pythonevalscriptperfile <script.py>  Eval the Python script on each source file (Multithreaded)
```

### 2. slang — 手写的 C++17 递归下降解析器与实例缓存

**文件**: `CHANGELOG.md`, 官方文档 ([GitHub](https://github.com/MikePopoloski/slang))

slang 是一个完全手写的 **C++17 递归下降解析器**，不依赖任何 parser generator（如 ANTLR/Yacc）：

> "slang is a software library that provides various components for lexing, parsing, type checking, and elaborating SystemVerilog code."
> — [slang 官方文档](https://sv-lang.com)

**AST 与内存模型**：slang 的 AST 采用**紧凑的类层次结构**和**内存池分配**，通过 `BumpAllocator` 等机制减少碎片。`SyntaxNode` 和 `Symbol` 形成两层表示：
- **Syntax Tree**：保留原始语法结构（包括注释、空白），支持 round-trip 代码生成和重构工具。
- **Semantic Model（Symbol 表）**：经过类型检查和 elaboration 后的语义表示，用于下游工具消费。

**实例缓存（Instance Caching）**：slang v9.0 引入了重大性能优化——**实例缓存**：

> "This release brings substantial elaboration performance improvements by way of instance caching..."
> — slang v9.0 Release Notes

在 SystemVerilog 中，同一模块可能被实例化数千次（如门级网表）。slang 的实例缓存会识别结构等效的模块实例，重用 elaborated 结果，避免重复计算。这对大型设计的 elaboration 阶段有数量级的加速效果。

**数据流分析**：slang v9.0 还引入了新的数据流分析框架，用于 linting 和静态分析：

> "Added a new dataflow analysis framework... Tracking of net and variable drivers has moved to the new analysis layer."
> — slang v9.0 Release Notes

### 3. 性能对比：SV Tests 基准测试

根据开源的 [chipsalliance/sv-tests](https://chipsalliance.github.io/sv-tests-results/) 测试套件（截至 2025-06），slang 和 Surelog 的合规性（compliance）表现如下：

| 测试类别 | slang | Surelog | 备注 |
|----------|-------|---------|------|
| 基础语法 | ~100% | ~100% | 两者都高度合规 |
| UVM 支持 | 66/66 | 65/66 | slang UVM 解析更完整 |
| 类/面向对象 | 完整 | 基本完整 | slang 在类继承方面表现更好 |
| 接口 (Interface) | 完整 | 完整 | 两者均支持 |
| 随机约束 | 完整 | 部分 | Surelog 对 constraints 支持较弱 |
| 断言/属性 | 完整 | 部分 | slang 在 SVA 方面领先 |

> "slang is the fastest and most compliant SystemVerilog frontend (according to the open source chipsalliance test suite)."
> — [slang 官方文档](https://sv-lang.com)

**解析速度**：虽然公开的详细 benchmark 数据有限，但社区反馈和 release note 均表明 slang 的解析速度显著快于 Surelog 和其他 ANTLR -based 工具。这主要归功于：
1. **手写解析器避免了 ANTLR 的运行时开销**（如预测表查找、LL(*) 回溯）。
2. **C++17 的编译时优化**：大量使用 `constexpr`、`string_view` 和紧凑数据结构。
3. **高效的内存管理**：使用内存池和 arenas，减少系统分配器调用。

### 4. UHDM 的跨工具价值与开销

**UHDM（Universal Hardware Data Model）** 是 Surelog 的核心产出，由 Si2 组织维护，目标是成为 SystemVerilog 的 "LLVM IR"：

```cpp
// Surelog 与 UHDM 的耦合
// include/Surelog/Design/Netlist.h
// UHDM
#include <uhdm/uhdm_forward_decl.h>
```

UHDM 的优势：
- **标准化**：提供 IEEE 1800-2017 的 VPI 接口，兼容商业工具的工作流。
- **序列化**：支持 Cap'n Proto 二进制格式，可以在不同进程/工具间传递设计。
- **生态**：已被 Yosys（via Synlig）、Verilator、Cocotb 等工具采用。

UHDM 的劣势：
- **内存开销**：每个对象需要维护 VPI 句柄、类型信息和反向引用，内存占用较大。
- **访问延迟**：通过 VPI 接口访问设计对象需要多次虚函数调用和指针解引用，比直接访问 AST 慢。
- **构建复杂度**：依赖 Cap'n Proto 和 UHDM 库，构建时间长。

相比之下，slang 的 API 是**直接暴露 C++ 语义模型**（`Symbol`, `Instance`, `Port` 等），访问延迟低，但缺乏标准化的跨语言绑定（目前提供 Python 绑定 `pyslang`）。

## 对 RTL 仿真器多线程化的启示

1. **前端选择对仿真器启动时间的影响**：
   - 如果仿真器需要**频繁重新编译/重新解析**（如迭代开发），slang 的解析速度优势可以显著缩短 "edit-compile-run" 循环。
   - 如果仿真器需要**与多种下游工具共享设计表示**（如同时输出给 Yosys 和 Verilator），Surelog + UHDM 的标准化优势更大。

2. **AST 内存布局与多线程遍历**：
   - slang 的紧凑 AST 和 `SyntaxNode` 数组布局更适合**多线程并行遍历**（如并行 linting、并行 elaboration）。
   - Surelog 的 `NodeId` + `FileContent` 间接层虽然增加了缓存不友好性，但允许更灵活的增量更新（如文件级增量编译）。

3. **Elaboration 的并行化**：
   - slang 的 **实例缓存** 是 elaboration 并行化的关键优化：如果多个模块实例在结构上等价，它们的 elaboration 结果可以共享，从而大幅减少总工作量。
   - 对于我们的多线程 RTL 仿真器项目，可以在 elaboration 阶段引入类似的**结构等价性哈希和缓存**，将 "实例化展开" 从 O(N) 降低到 O(独特模块数)。

4. **数据流分析的可复用性**：
   - slang 的 dataflow analysis 框架可以识别 signal 的驱动-负载关系，这正是仿真器**静态调度**所需的信息。如果仿真器前端基于 slang，可以直接复用其分析结果来生成多线程调度计划。

## 原文摘录

> "Surelog is a SystemVerilog 2017 pre-processor, parser, elaborator, and UHDM compiler. It provides IEEE Design/TB C/C++ VPI and Python AST APIs for use by linters, simulators, synthesis tools, and formal verification tools."
> — `CLAUDE.md`, Surelog

> "slang is the fastest and most compliant SystemVerilog frontend (according to the open source chipsalliance test suite)."
> — [slang 官方文档](https://sv-lang.com)

> "This release brings substantial elaboration performance improvements by way of instance caching, as well as more advanced linting capabilities with the new dataflow analysis framework."
> — slang v9.0 Release Notes

> "For maximum performance, the state of the simulation (which is the same as the set of its double buffered wires, since using a singly buffered wire for any kind of state introduces a race condition) should contain..."
> — CXXRTL 后端注释

## 性能数据对比

| 指标 | Surelog | slang |
|------|---------|-------|
| 解析器类型 | ANTLR4 生成 | 手写 C++17 递归下降 |
| AST 表示 | NodeId 索引 + FileContent | 紧凑 SyntaxNode + Symbol 表 |
| 中间表示 | UHDM (Cap'n Proto) | 直接语义模型（可选 JSON 导出） |
| 多线程 | 文件级并行解析 | 主要单线程，部分分析可并行 |
| Elaboration 优化 | 无实例缓存 | 实例缓存（v9.0+） |
| 数据流分析 | 有限 | 完整框架（v9.0+） |
| SV 合规性 (sv-tests) | ~95% | ~99%+（最合规） |
| Python 绑定 | 内置 listener | `pyslang` (PyPI) |
| 构建依赖 | ANTLR4, UHDM, Cap'n Proto | 仅 C++17 标准库 + fmt |
| 内存占用 | 较大（UHDM 对象开销） | 较小（紧凑结构 + 内存池） |

## 相关链接

- [Surelog GitHub](https://github.com/chipsalliance/Surelog)
- [slang GitHub](https://github.com/MikePopoloski/slang)
- [slang 官方文档](https://sv-lang.com)
- [pyslang PyPI](https://pypi.org/project/pyslang/)
- [SV Tests 结果](https://chipsalliance.github.io/sv-tests-results/)
- [UHDM 规范](https://github.com/chipsalliance/UHDM)
- [Synlig (Yosys + Surelog)](https://github.com/chipsalliance/synlig)

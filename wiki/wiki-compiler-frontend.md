---
id: "wiki-compiler-frontend"
title: "编译器前端与IR设计"
description: "系统梳理硬件IR生态（FIRRTL/LLHD/HIR/KIR）、SystemVerilog前端AST设计（Surelog/slang/UHDM）与IR优化技术（XLS/PipeRTL/Guac/CIRCT-HLS），为多线程RTL仿真器提供编译器层面的并行化设计指南"
tags: ["compiler-frontend", "IR", "FIRRTL", "LLHD", "HIR", "XLS", "PipeRTL", "SSA", "AST", "slang", "Surelog", "MLIR"]
keywords: ["硬件IR", "FIRRTL三阶降维", "LLHD-SSA", "HIR-schedule", "sea-of-nodes", "PipeRTL流水线", "Guac函数合并", "Handshake-IR", "解析器组合子", "UHDM"]
related_sources:
  - "source-hardware-ir"
  - "source-ast-parser"
  - "source-ir-optimization"
last_updated: "2026-07-02"
---

# 编译器前端与IR设计

现代RTL仿真器若要在多线程架构下获得实质性加速，仅靠调度器优化是不够的。编译器前端如何将SystemVerilog降维到清晰、无歧义的中间表示（IR），以及IR层面如何保留并行化所需的数据流信息，直接决定了仿真器能否安全、高效地分片执行。本章从硬件IR生态、AST前端设计和IR优化三个维度，提炼对多线程RTL仿真器架构设计的关键启示。

---

## 1. 硬件IR生态：从RTL到AI编译器的抽象谱系

### 1.1 FIRRTL：三阶降维的RTL级IR

FIRRTL（Flexible Intermediate Representation for RTL）由UC Berkeley为Chisel生态设计，现已成为CIRCT的核心dialect。其核心设计哲学是**渐进式降维**：

| 形式 | 保留特性 | 适用阶段 | 对仿真器的意义 |
|------|----------|----------|---------------|
| **High Form** | 模块、内存、聚合类型、时钟类型 | 前端语义捕获 | 保留模块边界，便于按模块粗粒度分区 |
| **Middle Form** | 展开后的寄存器、连线、组合逻辑 | 转换pass输入 | 明确的reg/wire区分，利于时序分析 |
| **Low Form** | 纯门级组合+时序网络 | 后端生成 | 最小语义子集，适合细粒度节点级并行 |

FIRRTL的**三阶降维**让前端保留高阶意图（如`memory`语义的读写端口冲突），而后端只需处理低阶子集。对RTL仿真器而言，这意味着：在high form阶段按模块边界分线程，在low form阶段按数据流图分节点——**同一IR的不同层级对应不同并行粒度**。

### 1.2 LLHD：SSA多层级IR与2.4x仿真加速

ETH Zurich提出的LLHD是一种基于SSA的多层级硬件IR，其设计目标是成为"SystemVerilog/VHDL的完整、无歧义参考描述"。

**LLHD的三级IR架构**：

| 层级 | 抽象 | 关键指令 | 对应仿真阶段 |
|------|------|----------|-------------|
| **Behavioural** | 过程式行为描述 | `wait`, `wait_time`, `proc` | 事件驱动仿真 |
| **Structural** | 模块实例化、信号连接 | `entity`, `inst`, `sig` | 结构级仿真 |
| **Netlist** | 门级网表 | `and`, `or`, `not`, `reg` | 门级cycle仿真 |

LLHD引入了硬件专用类型系统：
- `time`：显式时间值，支持精确的事件调度
- `T$`：信号类型，区分信号本身与信号当前值
- `lN`：九值逻辑（0, 1, X, Z, U, W, L, H, -），完整覆盖Verilog四态语义

**关键性能数据**：LLHD参考编译器（后升级为LLVM-JIT版本）在PLDI 2020论文中报告了比商业仿真器快**2.4倍**的cycle-accurate仿真性能。这证明了一个统一、无歧义的IR在消除工具链语义碎片化后，本身就能带来显著加速——**IR质量是仿真性能的上游决定因素**。

### 1.3 HIR：面向硬件加速器的显式Schedule抽象

HIR（Hardware IR）以MLIR dialect实现，用**datapath + schedule**替代传统HLS的datapath + FSM。其核心思想是将"何时执行"与"执行什么"解耦：

```mlir
// HIR示例：显式循环流水与重定时
hir.func @mac_loop(%a: !hir.memref<256xf32>, %b: !hir.memref<256xf32>) -> f32 {
  %sum = hir.alloca : f32
  hir.for %i = 0 to 256 step 1 {
    %av = hir.load %a[%i] : f32
    %bv = hir.load %b[%i] : f32
    %prod = hir.mul %av, %bv : f32
    %old = hir.load %sum : f32
    %new = hir.add %old, %prod : f32
    hir.store %new -> %sum : f32
  } { hir.schedule = "pipelined", II = 1 }
  hir.return %sum : f32
}
```

对RTL仿真器的启示：如果将时钟域、复位域、握手协议显式标注为schedule约束，仿真器可以在IR层面直接分析"哪些操作可以跨周期并行"，而非在运行时动态推断。

### 1.4 KIR：AI编译器中的硬件IR延伸

AIWareK编译器将PyTorch模型trace为Graph IR (GIR)后，再lower为Kernel IR (KIR)和Processor IR (PIR)。KIR位于算子层面，负责将深度学习中的高维张量操作映射到目标AI处理器的ISA。虽然KIR面向AI加速器而非通用RTL，但它体现了硬件IR的最新延伸方向：**从电路描述到计算图描述的谱系正在融合**。

### 1.5 四种IR的定位对比

| IR | 抽象层次 | 形式 | 核心优势 | 与仿真器的关系 |
|----|----------|------|----------|---------------|
| **FIRRTL** | RTL级 | AST-based | 三阶降维，意图保留 | 模块分区、接口语义保留 |
| **LLHD** | 多层级 | SSA | 完整语义覆盖，2.4x加速 | 统一IR消除工具碎片化 |
| **HIR** | HLS/加速器 | datapath+schedule | 显式调度，循环流水 | 时钟域显式标注，降低同步开销 |
| **KIR** | 算子级 | 数据流图 | AI处理器映射 | 数据流并行模型借鉴 |

---

## 2. AST前端设计：解析器的性能与可互操作性

### 2.1 Surelog：ANTLR + UHDM持久化的全功能前端

Surelog是CHIPS Alliance维护的SystemVerilog 2017完整前端，其架构适合大规模设计的并行处理：

```
SystemVerilog源码 → Preprocessor → ANTLR4 Parser → AST → Elaborator → UHDM数据库
                                                              ↓
                                    Verilator / Yosys / 仿真器 / 综合工具
```

**核心特性**：
- **多线程解析**：大文件可按行数切分，并行预处理与解析
- **UHDM持久化**：AST经Cap'n Proto/Flatbuffers序列化到磁盘，支持增量编译
- **VPI标准接口**：下游工具通过IEEE标准VPI API消费设计数据

对RTL仿真器的意义：若仿真器需要与综合工具、形式验证工具共享前端结果，采用UHDM作为标准数据交换格式可避免重复解析。Surelog → UHDM → Verilator/Yosys的成功路径已验证这一模式的可行性。

### 2.2 slang：round-trip CST/AST与现代C++性能标杆

slang由Mike Popoloski开发，采用手写递归下降 + 语法DSL生成，追求"最快速、最符合标准"的解析体验。

**slang的两层语法树设计**：

| 层级 | 节点类型 | 特性 | 用途 |
|------|----------|------|------|
| **CST** | `syntax::SyntaxNode` | 链接父节点，保留trivia（注释/空白） | 源码到源码的round-trip |
| **AST** | 语义节点 | 类型检查、elaboration后的抽象表示 | 代码生成、lint、仿真器输入 |

**SV-Tests性能对比**（3427项测试集）：

| 指标 | slang | Surelog | 倍数差距 |
|------|-------|---------|----------|
| 合规测试通过数 | ~3427 | ~3114 | slang更优 |
| 最大内存 | ~25 MB | ~3,184 MB | **127x** |
| 用户时间 | ~15 s | ~1,598 s | **106x** |

**关键启示**：手写递归下降 + arena allocator在性能和内存效率上远超通用parser generator。对于需要"边编辑边编译"的交互式仿真器（如IDE集成），slang架构是更优的参考。

### 2.3 解析器组合子：轻量级DSL的潜在选择

解析器组合子（parser combinator）在软件语言（Haskell/Scala/Rust nom）中已成熟，但在HDL前端仍属边缘探索。Hammer等库在FPGA上实现了Ethernet frame等硬件包解析的组合子原语，证明"组合子 → 硬件结构"的映射可行。

对RTL仿真器的实际价值：若仿真器需要嵌入轻量级"测试向量DSL"或"断言子语言"，解析器组合子（如Rust nom或C++组合子库）比ANTLR更灵活、更易嵌入。

### 2.4 前端工具全景

| 工具 | 语言 | 解析器类型 | 持久化 | 适用场景 |
|------|------|-----------|--------|----------|
| **Surelog** | C++ | ANTLR4生成 | UHDM(Cap'n Proto) | 全功能前端，跨工具互操作 |
| **slang** | C++20 | 手写递归下降 | 内存内 | 高性能解析，LSP/formatter |
| **Verible** | C++ | 手写 | 内存内 | Google linter/formatter/LSP |
| **sv-parser** | Rust | 手写 | 内存内 | 完全合规IEEE 1800-2017 |
| **hdlConvertor** | C++/Python | ANTLR4 | Python AST | 多语言支持(VHDL/Verilog) |
| **tree-sitter-verilog** | C/Rust | GLR | 增量 | 编辑器增量解析 |

---

## 3. IR优化：从SSA到数据流并行的编译器技术

### 3.1 XLS IR：Sea-of-Nodes + SSA的硬件哲学

Google XLS团队提出了一种面向硬件生成的数据流IR，其核心洞察是：**传统编译器的CFG（控制流图）是CPU串行执行模型的产物，而硬件的"处处并行"本质需要Sea-of-Nodes（SoN）表示**。

```
// 传统CFG（串行思维）:
BB1: a = load(x)
     b = load(y)
     c = mul(a, b)
     br BB2

// XLS SoN（并行思维）:
//     load(x) ─┐
//              ├─→ mul ─→ ...
//     load(y) ─┘
// 所有节点同时存在，数据依赖即边
```

XLS IR从高级frontend到RTL门级仅使用**单一IR表示**，最大化分析与转换组件的复用性。其SSA性质自然成立——IR初始即为函数式，无需显式φ-node更新。这使得常量传播、死码消除等优化pass的实现极为简洁。

### 3.2 PipeRTL：时序感知流水线优化

PipeRTL在CIRCT/MLIR上构建，通过引入`pipe` dialect和带权图（wGraph）在IR层面做全局寄存器重定位：

```mlir
// PipeRTL抽象：将寄存器重写为pipe.delay，广播为pipe.bubble
// 边权 w(e) = 寄存器延迟数，β(e) = 数据容量
// 优化目标：在保持端到时延前提下，全局最小化寄存器数量与容量

hw.module @example(%in: i32, %clk: i1) -> (out: i32) {
  %r1 = seq.compreg %in, %clk : i32
  %r2 = seq.compreg %r1, %clk : i32
  %r3 = seq.compreg %r2, %clk : i32
  // PipeRTL可分析：r1→r2→r3链是否可被retiming优化
  hw.output %r3 : i32
}
```

**关键性能数据**：
- 平均寄存器数量减少 **19.84%**
- 数据容量减少 **12.61%**
- 在7nm ASAP7工艺下：timing改善2.1%、动态功耗降低6.6%、总面积降低5.4%

**核心方法**：使用XGBoost训练时序预测模型（基于CIRCT `comb` dialect操作延迟数据集），在IR优化阶段就"知晓"后端物理时序，避免盲目重定位。

### 3.3 Guac：SSA函数合并与硬件资源共享

Guac在LLVM-IR层面对相似函数进行粗粒度合并（CGFM），合并后的函数仍保持SSA形式。经HLS翻译后，φ-node转化为硬件multiplexer，函数共享转化为硬件资源共享。

**关键发现**：相比非SSA的合并方案，SSA-based CGFM在面积、功耗与能耗上均显著更优，**能量节省翻倍**。这说明SSA形式不仅是软件编译器的优化基石，同样是硬件综合的资源优化利器。

### 3.4 CIRCT-HLS Handshake：数据流IR的valid/ready语义

CIRCT-HLS和Dynamatic使用**Handshake IR**表示数据流。每个操作节点带有valid/ready信号，天然支持异步数据驱动执行：

```mlir
// Handshake IR示例：数据流节点带valid/ready握手
handshake.func @main(%arg0: !handshake.control<>, %arg1: !handshake.control<>) -> !handshake.control<> {
  %0:2 = fork [2] %arg0 : <>
  %1 = addi %0#0, %0#1 : i32
  %2 = buffer [2] %1 : i32  // 流水线缓冲
  return %2 : i32
}
```

Handshake IR的valid/ready握手协议与数据令牌传递，本质上是一种**异步数据流执行模型**，与多线程仿真中的"生产者-消费者"模型高度契合。

### 3.5 IR优化技术对比

| 技术 | 核心机制 | 关键收益 | 对仿真器的意义 |
|------|----------|----------|---------------|
| **XLS SoN** | Sea-of-Nodes + SSA | 单一IR端到端 | 并行执行图天然拓扑可分区 |
| **PipeRTL** | wGraph + XGBoost时序预测 | 寄存器-19.8% | IR优化减少仿真状态数 |
| **Guac** | SSA-based CGFM | 能量节省翻倍 | SSA减少状态，降低缓存一致性开销 |
| **Handshake IR** | valid/ready数据流 | 异步执行模型 | 生产者-消费者线程模型直接映射 |
| **Pruned SSA** | 最小化局部变量 | 更少的wire/register | 仿真器需维护的信号更少 |

---

## 4. 对多线程RTL仿真器的启示

### 4.1 IR层并行化是更安全的并行化

RTL仿真器在Verilog AST层面做并行分区时，面临宏展开、generate块、参数传递等复杂语义的困扰。但若先将设计完整降维到统一IR（如LLHD的行为级SSA），再基于IR做并行调度：
- **数据流天然分区**：SSA/数据流IR中的节点依赖关系即边，无依赖的节点天然可并行
- **消除语义歧义**：IR的精确定义避免了Verilog方言差异导致的竞态
- **静态分析友好**：SSA形式使活跃变量分析、依赖分析可以直接指导分区决策

### 4.2 SSA形式利于静态分析指导调度

XLS IR的sea-of-nodes和Handshake IR的数据流图都证明，一旦RTL被表示为SSA或数据流形式，节点间的依赖关系构成一张**并行执行图**。多线程仿真器可以：
- 基于拓扑序将无依赖节点分配到不同线程
- 使用动态调度（work stealing）处理运行时活跃节点
- 无需传统event-driven仿真中的全局竞争冒险分析

### 4.3 多级IR对应多级并行粒度

FIRRTL的三阶降维策略提示，RTL仿真器也可以维护多级IR：
- **High form**：按模块边界粗粒度分区，线程间通信为模块接口信号
- **Middle form**：按寄存器/组合逻辑边界中粒度分区
- **Low form**：按门级节点细粒度分区，适合数据流并行

不同设计在不同阶段启用不同粒度——大模块用粗粒度，计算密集模块用细粒度。

### 4.4 显式Schedule降低跨线程同步开销

HIR的schedule思想对cycle-accurate多线程仿真尤为关键：如果IR层面显式标注了时钟域、复位域、握手协议，仿真器可以：
- 按时钟域分配线程，避免跨时钟域的每周期同步
- 利用valid/ready语义实现异步生产者-消费者通信
- 预计算"安全并行窗口"，减少运行时barrier频率

---

## 5. 可操作建议：用MLIR方言描述RTL，在IR层做并行调度

### 5.1 架构级建议

| 设计决策 | 推荐方案 | 替代方案 | 避免 |
|----------|----------|----------|------|
| IR选择 | MLIR CIRCT dialect (hw/comb/seq) | LLHD SSA | 直接使用Verilog AST做并行分区 |
| 分区输入 | 降维后的IR（middle/low form） | 模块级AST | 在high form做细粒度分区 |
| 并行粒度 | 数据流节点级（ dense设计） | 模块级（sparse设计） | 固定粒度一刀切 |
| 同步策略 | 周期级barrier + 域内异步 | 每delta cycle barrier | 事件级全局锁 |

### 5.2 实现参考代码：基于MLIR IR的并行分区器

```cpp
// 简化的IR层并行分区器框架
#include "mlir/IR/BuiltinOps.h"
#include "mlir/Dialect/Func/IR/FuncOps.h"

class IRParallelPartitioner {
public:
    // 从MLIR module构建数据流依赖图
    void buildDataflowGraph(mlir::ModuleOp module) {
        module.walk([&](mlir::Operation *op) {
            // 每个operation成为一个节点
            NodeId id = graph_.addNode(op);
            // SSA use-def链即数据流边
            for (mlir::Value result : op->getResults()) {
                for (mlir::Operation *user : result.getUsers()) {
                    graph_.addEdge(id, nodeMap_[user], EdgeType::DataFlow);
                }
            }
        });
    }
    
    // 基于METIS或自定义启发式分区
    std::vector<Partition> partition(int numThreads, PartitionStrategy strategy) {
        switch (strategy) {
            case PartitionStrategy::ModuleBoundary:
                // High form: 按模块实例分区
                return partitionByModule(numThreads);
            case PartitionStrategy::DataflowCut:
                // Low form: 最小边割分区
                return partitionByMinCut(numThreads);
            case PartitionStrategy::ClockDomain:
                // 按时钟域分区，跨域边作为异步通道
                return partitionByClockDomain(numThreads);
        }
    }
    
private:
    DataflowGraph graph_;
    llvm::DenseMap<mlir::Operation*, NodeId> nodeMap_;
};
```

### 5.3 仿真引擎集成建议

```cpp
// 周期级并行仿真调度器（基于IR层分区）
class IRBasedParallelScheduler {
    std::vector<std::unique_ptr<PartitionEvaluator>> partitions_;
    std::vector<std::unique_ptr<AsyncChannel>> crossDomainChannels_;
    
public:
    void stepCycle() {
        // Phase 1: 各分区独立执行组合逻辑（无全局同步）
        #pragma omp parallel for
        for (size_t i = 0; i < partitions_.size(); ++i) {
            partitions_[i]->evalCombinational();
        }
        
        // Phase 2: 跨域异步信号交换（通过无锁SPSC队列）
        for (auto& ch : crossDomainChannels_) {
            ch->transfer();
        }
        
        // Phase 3: 各分区更新时序元件（barrier确保全局一致性）
        #pragma omp parallel for
        for (size_t i = 0; i < partitions_.size(); ++i) {
            partitions_[i]->updateSequential();
        }
    }
};
```

### 5.4 开发优先级清单

- [ ] 集成CIRCT作为前端，将SystemVerilog降维到hw/comb/seq dialect
- [ ] 在middle/low form IR上构建数据流依赖图，替代AST级依赖分析
- [ ] 实现按模块边界（high form）和按节点数据流（low form）的两种分区策略
- [ ] 为跨分区信号设计无锁SPSC队列（借鉴Handshake IR的valid/ready语义）
- [ ] 在IR层面预计算时钟域信息，按域分配线程避免不必要的全局同步
- [ ] 引入PipeRTL风格的时序预测，优化分区边界上的寄存器布局以减少跨线程通信
- [ ] 评估Pruned SSA对仿真状态数的减少效果，量化缓存一致性开销改善

---

## 参考来源

- [source-hardware-ir](source-hardware-ir.md) — FIRRTL三阶降维、LLHD SSA多级IR、HIR schedule抽象、KIR AI编译器
- [source-ast-parser](source-ast-parser.md) — Surelog ANTLR+UHDM、slang round-trip CST/AST、解析器组合子、SV-Tests性能
- [source-ir-optimization](source-ir-optimization.md) — XLS sea-of-nodes+SSA、PipeRTL时序感知流水线、Guac SSA函数合并、CIRCT-HLS Handshake

---
title: "RTL 形式化安全验证：信息流跟踪与硬件安全属性证明"
description: "形式化安全验证在 RTL 设计中的应用，涵盖信息流跟踪（IFT）、GLIFT/RTLIFT、安全属性（保密性/完整性/隔离性）验证、以及 SoC 级仿真与形式化混合验证方法。"
source_url: "https://dl.acm.org/doi/fullHtml/10.1145/3447867"
source_type: "paper"
author: "Wei Hu et al. (ACM Computing Surveys)"
date: "2021"
tags: ["formal-verification", "security", "information-flow", "RTL", "IFT", "GLIFT", "RTLIFT", "confidentiality", "integrity"]
keywords: ["formal security verification", "information flow tracking", "GLIFT", "RTLIFT", "confidentiality", "integrity", "isolation", "SAT solving", "equivalence checking", "theorem proving"]
capture_date: "2026-07-02"
---

# RTL 形式化安全验证：信息流跟踪与硬件安全属性证明

## 来源

- **URL**: https://dl.acm.org/doi/fullHtml/10.1145/3447867
- **类型**: paper
- **作者**: Wei Hu, S debating, et al. (ACM Computing Surveys 2021)
- **日期**: 2021

> 补充来源：
> - Emulation-based SoC Security Verification (arXiv, 2026): https://arxiv.org/html/2604.15073v1
> - Formal Security Verification in SoC Design (Alpinum, 2026): https://alpinumconsulting.com/blogs/verification/formal-security-verification-soc-design/
> - Security Verification in Semiconductor Development (SemiEngineering, 2025): https://semiengineering.com/security-verification-in-semiconductor-development/
> - Information Flow Coverage Metrics (arXiv, 2022): https://ar5iv.labs.arxiv.org/html/2304.08263
> - GLIFT/RTLIFT 原始论文合集 (NTU Survey): https://dr.ntu.edu.sg/bitstreams/e2952c35-2e09-4507-b8b0-e5ce08d58f9b/download

## 摘要

形式化安全验证是证明硬件设计满足保密性、完整性和隔离性等安全属性的核心技术。信息流跟踪（Information Flow Tracking, IFT）是该领域的基础方法，它通过为数据分配安全标签（如 secret / public / trusted / untrusted）并追踪标签在 RTL 设计中的传播，来验证是否存在未授权的信息泄露或篡改。从门级 IFT（GLIFT）演进至 RTL 级 IFT（RTLIFT），验证性能提升约 5 倍。与此同时，静态 IFT（SIFT）和动态 IFT（DIFT）各有优劣：SIFT 适合早期漏洞筛查但可能产生误报，DIFT 在运行时捕获实际执行路径但引入额外开销。形式化验证技术包括等价性检查、SAT 求解、定理证明（如 Coq）和类型系统，这些方法可在标准 EDA 环境（如 Yosys + ABC + SVA）中执行。然而，SoC 规模的形式化验证面临状态空间爆炸、安全属性难以完整规约、以及固件/软件环境建模困难等挑战。仿真与形式化混合验证（如 Synopsys VCS T-Prop 污点传播）正成为工业界的主流方向。

## 关键要点

- **IFT 核心机制**：为每个 RTL 变量关联安全标签，通过显式流（直接赋值）和隐式流（条件依赖）追踪信息传播。显式流较易处理，隐式流（如 `if (secret) then public = 1`）的建模是精度与复杂度的关键权衡。
- **GLIFT → RTLIFT 演进**：GLIFT（Gate-Level IFT）在门级网表上追踪信息流，奠定了跟踪逻辑形式化、复杂度理论等基础，但门级规模导致验证瓶颈。RTLIFT 直接在 RTL 描述上操作，利用更高抽象层级减少状态空间，实现约 5 倍性能提升。
- **安全属性分类**：
  - **保密性（Confidentiality）**：防止敏感信息泄露到未授权位置（如密钥不应出现在非安全输出）。
  - **完整性（Integrity）**：禁止不可信实体覆盖可信数据（如用户程序不可修改系统配置）。
  - **隔离性（Isolation）**：防止不同信任域实体间的非法通信（如安全世界与非安全世界）。
  - **常数时间（Constant Time）**：通过运行时可变性捕获信息泄露（如缓存时序攻击）。
  - **设计完整性（Design Integrity）**：检测恶意设计修改导致的信息流异常。
- **形式化验证技术**：
  - **等价性检查**：构建 miter 电路，检查污点源在不同取值下是否影响目标点。
  - **SAT 求解**：Yosys + ABC 将 IFT 模型转换为 CNF 公式，由 MiniSAT / zChaff 证明安全属性。
  - **定理证明**：PCH-IP / VeriCoq 将 RTL Verilog 转换为 Coq 语义电路模型，使用 Coq 证明器验证保密性。已扩展至晶体管级以检测模拟木马。
- **SIFT vs DIFT**：静态 IFT 分析 RTL/网表构建依赖图，无需执行但可能过度近似；动态 IFT 在仿真运行时追踪标签，捕获实际执行路径和瞬态行为，但增加运行时开销。
- **Hyperflow Graphs**：在 RTL 设计上建模信息流的超流图，通过 IFT 增强仿真进行属性标注，图算法可揭示安全弱点并提供覆盖率指标。
- **工业实践**：Synopsys VCS 的 T-Prop（Taint Propagation）在 RTL 仿真中动态追踪污点传播，评估设计的保密性和弹性。FSV App（Formal Security Verification）使用 "any value" SVA 属性检查源是否能影响目标。
- **SoC 级挑战**：状态空间爆炸、安全属性难以完整规约、固件/软件环境建模困难。传统形式化方法适合证明局部不变量（如访问控制规则、特权转换正确性），但在全 SoC 尺度上难以收敛。

## 对 RTL 仿真器多线程化的启示

1. **SIFT 的并行图分析**：静态 IFT 需要构建和分析 RTL 设计的依赖图（如 Hyperflow Graphs）。图的构建（节点 = RTL 信号，边 = 数据/控制依赖）和分析（可达性、标签传播）天然适合并行化。多线程仿真器若能输出中间表示（IR），可加速 SIFT 的图分析阶段。

2. **DIFT 的并行标签传播**：动态 IFT 在仿真中实时追踪每个信号的安全标签。标签传播的计算可以与功能仿真逻辑并行执行——每个线程维护独立的标签状态，但跨模块边界的标签传递需要同步。这类似于多线程仿真中的跨模块信号更新问题。

3. **形式化验证的并行求解**：SAT 求解和等价性检查是形式化验证的核心瓶颈。虽然 SAT 求解本身难以并行，但现代 EDA 工具（如 Yosys）支持将设计分块后并行证明。多线程仿真器可作为形式化验证的前端，快速生成验证用的边界条件和反例测试向量。

4. **混合验证的并行 campaign**：仿真（提供调试可见性和灵活性）+ 形式化（提供严格证明）的混合验证流程需要大量仿真 campaign。多线程仿真器可并行运行多个验证场景（如不同安全属性、不同攻击假设），最终由形式化工具统一验证关键路径。

5. **覆盖率的并行收集**：安全验证中的信息流覆盖率（information flow coverage）需要在大量仿真中统计标签传播路径。多线程仿真中每个线程可独立收集局部覆盖率，最终通过线程安全的数据结构合并全局覆盖率，避免串行瓶颈。

6. **SoC 规模的分层验证**：大型 SoC 的安全验证通常按子系统分层进行。多线程仿真器可为每个子系统分配独立线程，各线程内部运行完整的安全属性验证，最后通过顶层协议检查确保跨子系统的隔离性。这要求仿真器支持层次化的线程分配和跨层次同步机制。

## 原文摘录

> "Information flow tracking (IFT) is a fundamental computer security technique used to understand how information moves through a computing system. It labels data objects with a tag to denote security classes, which are assigned different meanings depending on the type of security property under analysis. IFT updates the tags as the data is computed upon and verifies information flow properties by observing the state of the tags."
> —— Wei Hu et al., ACM Computing Surveys 2021

> "RTLIFT has observed ~5X improvement in verification performance as compared to GLIFT. Clepsydra provides a formal model for timing-only information flow and allows proving constant time properties in order to detect timing channels in caches and cryptographic cores. VeriSketch employs the sketch technique to automatically synthesize hardware designs that satisfy desired security properties such as confidentiality, integrity and constant time."
> —— NTU Survey Paper

> "Formal verification and assertion-based checking are effective when the security property is precisely specified and the design scope remains tractable. In practice, these methods are particularly useful for proving localized invariants, such as access-control rules, privilege-transition correctness, and protocol safety properties in selected subsystems. However, formal methods face well-known obstacles at SoC scale, including state-space explosion, the difficulty of specifying complete security intent, and the challenge of modeling realistic firmware and software environments."
> —— Emulation-based SoC Security Verification, arXiv 2026

> "The simulation component of data propagation verification tracks the propagation of data taints through the design. This entails inserting a taint into the design and seeing how far it propagates (permeability), and for how long (permanence), as the design is simulated. The Synopsys VCS simulator include taint propagation (T-Prop) capabilities for just this purpose."
> —— SemiEngineering, 2025

> "A workable formal security verification flow usually looks like this: Inputs: synthesizable RTL, clock/reset definitions, constraints for valid modes and environmental assumptions, plus a set of security properties. Objective: prove that information from defined sources cannot reach protected assets (confidentiality) and cannot influence protected state or outputs (integrity). Debug: when the property fails, the tool should provide a trace that explains how the flow occurs and through which logic cone or state transition."
> —— Alpinum Consulting, 2026

## 相关链接

- [ACM Computing Surveys — Hardware Information Flow Tracking](https://dl.acm.org/doi/fullHtml/10.1145/3447867)
- [Kastner Research Group — Hardware IFT Survey PDF](https://kastner.ucsd.edu/wp-content/uploads/2021/05/admin/hardware-ift.pdf)
- [Emulation-based SoC Security Verification (arXiv, 2026)](https://arxiv.org/html/2604.15073v1)
- [Formal Security Verification in SoC Design (Alpinum, 2026)](https://alpinumconsulting.com/blogs/verification/formal-security-verification-soc-design/)
- [Security Verification in Semiconductor Development (SemiEngineering, 2025)](https://semiengineering.com/security-verification-in-semiconductor-development/)
- [Information Flow Coverage Metrics (arXiv, 2022)](https://ar5iv.labs.arxiv.org/html/2304.08263)
- [RTLIFT — Register Transfer Level Information Flow Tracking](https://github.com/Trust-Hub/RTLIFT)
- [GLIFT — Gate Level Information Flow Tracking](https://github.com/Trust-Hub/GLIFT)
- [Yosys Open Synthesis Suite (含 SAT 求解器集成)](https://github.com/YosysHQ/yosys)
- [ABC — System for Sequential Synthesis and Verification](https://github.com/berkeley-abc/abc)

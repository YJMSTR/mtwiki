---
title: LLM 辅助 RTL 验证与硬件设计（Copilot for RTL）
description: 大语言模型（LLM）在 RTL 代码生成、验证测试平台生成、断言生成、形式化验证及硬件安全分析中的应用资料汇编
source_url: ""
source_type: "survey"  # survey, paper, blog, github
author: ""
date: ""
tags:
  - llm
  - rtl-verification
  - code-generation
  - formal-verification
  - copilot
keywords:
  - LLM verilog verification
  - GPT RTL code generation
  - AI assisted hardware verification
  - LLM formal verification
  - ChipNeMo
  - VeriAssist
  - assertion generation
capture_date: "2026-07-02"
---

# LLM 辅助 RTL 验证与硬件设计（Copilot for RTL）

## 来源

- **Hardware Design and Verification with Large Language Models: A Scoping Review, Challenges, and Open Issues**
  - URL: https://www.mdpi.com/2079-9292/14/1/120
  - 作者: Mahdi Abdollahi, et al.
  - 类型: 综述论文 (Electronics 2024, Cited by 109+)
  - 日期: 2024-12-30

- **A Survey of Circuit Foundation Model: Foundation AI Models for VLSI Circuit Design and EDA**
  - URL: https://zhiyaoxie.github.io/files/preprint25_CFM.pdf
  - 作者: Zhiyao Xie, et al. (SJTU Thinklab)
  - 类型: 预印本综述
  - 日期: 2025

- **Towards LLM-Powered Verilog RTL Assistant: Self-Verification and Self-Correction (VeriAssist)**
  - URL: https://arxiv.org/abs/2406.00115
  - 作者: Hanxian Huang, et al. (UCSD / NVIDIA)
  - 类型: 会议论文
  - 日期: 2024-05

- **ChipNeMo: Domain-Adapted LLMs for Chip Design**
  - URL: https://arxiv.org/abs/2311.00176
  - 作者: Mingjie Liu, et al. (NVIDIA)
  - 类型: 会议论文 (NeurIPS 2023 Workshop)
  - 日期: 2023-11

- **LAAG-RV: LLM Assisted Assertion Generation for RTL Design Verification**
  - URL: https://www.themoonlight.io/en/review/laag-rv-llm-assisted-assertion-generation-for-rtl-design-verification
  - 类型: 论文解读
  - 日期: 2025-03

- **FT-Pilot: Automated Fault-Tolerant RTL Rewriting via Vulnerability-Guided LLMs**
  - URL: https://arxiv.org/html/2605.28169
  - 类型: 预印本
  - 日期: 2026-05

- **FormalRTL: Verified RTL Synthesis at Scale**
  - URL: https://arxiv.org/html/2603.08738v1
  - 类型: 预印本
  - 日期: 2026-03

- **Survey and Benchmarking of Large Language Models for RTL Code Generation**
  - URL: https://www.preprints.org/manuscript/202509.1681
  - 类型: 预印本
  - 日期: 2025-09

- **Hardware Verification: What AI Gets Right When It Generates Your Testbench**
  - URL: https://www.embedded.com/hardware-verification-what-ai-gets-right-when-it-generates-your-testbench-and-what-it-misses/
  - 作者: Vikash Kumar
  - 类型: 博客/实验报告
  - 日期: 2026-04-13

- **Agentic AI for Chip Design Verification 2026 (PatSnap)**
  - URL: https://www.patsnap.com/de/resources/blog/rd-blog/agentic-ai-for-chip-design-verification-2026-patsnap-eureka/
  - 类型: 行业分析
  - 日期: 2026-06-16

- **Application of AI to Accelerate Formal Verification Workflow**
  - URL: https://designthesolution.org/wp-content/uploads/2025/09/application-of-ai-to-accelerate-formal-verification-workflow-liya.pdf
  - 类型: 白皮书/论文
  - 日期: 2025-09

## 摘要

LLM 在 RTL 设计和验证领域的应用正从"玩具级 demo"迅速迈向工业级落地。2024 年的高引综述（109+ 引用）系统梳理了 LLM 在硬件设计与验证中的任务谱系，涵盖代码生成、断言生成、测试平台生成、形式化验证辅助、Bug 检测与修复等。工业界代表 **NVIDIA ChipNeMo**（基于 LLaMA2 的域适配模型，在 231 亿 token 的内部数据上继续预训练）证明，仅需 13B 参数的定制模型即可在芯片设计任务上媲美甚至超越 70B 通用模型。学术研究方面，**VeriAssist** 提出自验证-自修正闭环，通过将 RTL 仿真器嵌入代码生成循环，大幅提升生成代码的语法和功能正确率。**Formal Verification Copilot** 市场预计在 2025-2034 年间以 **14.7% CAGR** 增长，从 18 亿美元增至 62 亿美元。然而，当前 LLM 生成验证环境的覆盖率鸿沟仍然显著——Vikash Kumar 的实验显示，LLM 生成的 UVM 测试平台在固件-硬件契约边界（firmware-hardware contract）的验证上存在盲区。

## 关键要点

### 1. 代码生成与验证自动化

- **VeriAssist (2024)**：提出 LLM 驱动的 RTL 助手，核心创新是将 **RTL 仿真器（如 Icarus Verilog）嵌入代码生成循环**。工作流：生成初始 RTL 代码 → 自动生成 testbench → 自验证（逐步推理代码时序行为） → 自修正（读取编译/仿真结果并修复错误）。实验表明，该闭环显著提升了语法正确率和功能正确率，**降低了人工干预**。

- **VeriAssist 变体与后续工作**：
  - **VeriGen**：早期基于 CodeGen-16B 在 GitHub 和教科书数据上微调，证明领域数据即可超越 GPT-3.5 在 HDLBits 上的完成率。
  - **VeriOpt**：多 agent 工作流（规划、编程、评审、评估），支持 PPA 感知提示（时钟门控、功耗门控、资源共享、FSM 编码、流水线），并将综合报告、时序图、硬件指标作为多模态反馈输入 LLM。
  - **VeriReason**：在 Qwen 2.5 上加入类人推理轨迹和高质量 testbench，用 Guided Reward Proximal Optimisation 微调，在 VerilogEval 上评估。
  - **VerilogCoder**：基于任务-电路关系图规划器，四 agent 协作（规划、编码、验证、AST 追踪），通过 AST 回溯定位故障信号后再生成。

- **ChipNeMo (NVIDIA, 2023)**：
  - 基于 LLaMA2 7B/13B/70B，使用 **Domain-Adaptive Pre-Training (DAPT)** 在 231 亿 token 的内部芯片设计数据上继续预训练。
  - 定制 tokenizer，仅对芯片设计领域术语添加新 token，提升 tokenization 效率 **3.3%**。
  - 三大应用场景：工程助理聊天机器人（专家评分 7.4/10）、EDA 脚本生成（正确率 >50%）、Bug 总结分析（评分 4-5/7）。
  - **关键结论**：13B 参数的 ChipNeMo 在芯片设计任务上可匹配或超越 70B 通用模型（如 LLaMA2 70B），且在所有基准上超越 GPT-3.5，在设计知识和 Bug 基准上超越 GPT-4。
  - 使用 RAG（检索增强生成）并微调检索模型，将检索命中率提升 **30%**。

### 2. 断言生成与形式化验证

- **LAAG-RV**：用 LLM（基于 GPT-4）将自然语言规格转换为 **SystemVerilog Assertions (SVA)**。框架包含：规格输入 → 初始 SVA 生成 → 一次性 Verilog 循环进行信号同步 → 迭代验证（Synopsys VCS）→ 错误反馈驱动 LLM 修正。在 OpenTitan 的 RV Timer 上测试，1 分钟内生成 10 个 assert property 和 3 个 cover property。

- **Formal Verification Copilot 市场报告 (2025-2034)**：
  - 2025 年市场规模 **18 亿美元**，预计 2034 年达到 **62 亿美元**，CAGR **14.7%**。
  - LLM 在形式化验证中的生产力提升：自动断言生成准确率 **78%+**，手动属性规范负担减少 **35%-42%**；反例解释功能将调试周期缩短 **25%**；RL 驱动的证明策略选择器（BDD/SAT/k-induction）可提升证明吞吐量 **30%**。

- **AI for Formal Verification 白皮书**：展示了用 GPT-4o 对一般 FSM 设计生成 6 类形式化验证属性（状态转移、可达性、非法状态检测、互斥性、时序约束、输出行为），然后基于具体设计生成 10 个 assert property 和 3 个 cover property，耗时 **1 分钟**。

- **FormalRTL (2026)**：提出统一多 agent 框架，将高层设计意图转换为已验证的 RTL 实现。使用 **GPT-4.1（规划 agent）和 GPT-5（初始化/调试 agent）**，结合静态分析（Clang）和软硬件等价验证工具（hw-cbmc），形成高可信 RTL 综合流程。

### 3. 测试平台生成与覆盖率分析

- **Vikash Kumar 实验 (2026)**：使用 Claude Code（Anthropic 的 agentic coding assistant）从自然语言规格生成完整的双通道 AHB-Lite DMA 控制器验证环境。输出包含 **15+ SystemVerilog 文件**（RTL、UVM 环境、scoreboard、3 个 progress monitor、sequence telemetry agent、5 个 test class）。传统上这需要初级工程师 **2-3 周** 的工作量，而 LLM 在单会话内完成。
  - 但实验同时揭示了关键盲区：**固件-硬件契约（firmware-hardware contract）** 的验证缺失。测试平台可能正确提交了描述符并验证了完成信号，但从未建模 IRQ 清除义务，导致通道永久阻塞而 scoreboard 仍报告 PASSED。
  - 提出三个量化指标：PMC（Progress Monitor Coverage）、CVL（Coverage Value Leakage）、DFS（Descriptor Fidelity Score），用于衡量 LLM 生成验证环境的完整性。

- **LLM-Aided Testbench Generation and Bug Detection for FSM (2024)**：研究 LLM 在覆盖引导的 testbench 生成和自动 Bug 检测方面的能力。指出创建 testbench 和生成有效测试模式是设计和验证工程师的痛点，LLM 可通过分析 RTL 代码自动标记潜在错误（如组合环路、缺失 always 块、不正确的信号赋值）。

### 4. Agentic AI 与闭环验证

- **Agentic AI for Chip Design Verification (PatSnap, 2026)**：从 2024-2025 专利分析中提取出四大趋势：
  1. **闭环仿真-调试-修复 Agent**：Google DeepMind 2024 年论文描述了完整的验证闭环——生成修复假设、应用到 RTL、重新仿真、验证修正，而非仅标记 Bug。
  2. **跨层验证 Agent（RTL-to-Silicon）**：NVIDIA 2024 年专利提出多 agent AI 系统，覆盖从 RTL 验证到硅后验证的全流程。
  3. **RTL IDE Copilot**：涌现的 IDE 内嵌 copilot 专利申请。
  4. **领域 LLM 微调**：在专有 RTL 语料和 Bug trace 数据上微调 LLM 构建持久竞争壁垒。

- **FT-Pilot (2026)**：提出自动化容错 RTL 重写框架。首先将 RTL 转换为 **And-Inverter Graph (AIG)** 并用 **GNN 识别脆弱资产**，然后设计两阶段 LLM 重写流水线（RTL Analyzer 分配容错策略 → RTL Rewriter 执行策略感知重写）。该框架将机器学习的电路结构分析与 LLM 的代码生成能力结合，代表了 **ML + LLM 混合范式** 的前沿。

- **Awesome-LLM4EDA (SJTU Thinklab)**：维护的 GitHub 仓库系统追踪 LLM for EDA 的进展，涵盖：代码分析、验证（断言生成）、Bug 检测与修复、安全分析、大型电路模型（LCMs）等方向。

## 对 RTL 仿真器多线程化的启示

1. **LLM 生成多线程测试平台**：mt-vlm 的多线程特性需要专门的回归测试套件。LLM 可快速生成针对不同线程数、分区策略、workload 特征的 testbench 和断言，加速验证环境搭建。VeriAssist 的"仿真器嵌入生成循环"思想可直接迁移——用 mt-vlm 的仿真输出反馈给 LLM，自动修正测试激励。

2. **覆盖率引导的测试生成**：当前多线程 RTL 仿真器的测试覆盖主要依赖手工编写的定向测试和随机约束。借鉴 LAAG-RV 的迭代 SVA 生成框架，可尝试用 LLM 根据覆盖率报告（如分支覆盖率、toggle 覆盖率）自动生成补充测试模式和断言，实现**覆盖率闭环**。

3. **Bug 检测与诊断**：多线程仿真器特有的 Bug 类别（如数据竞争、死锁、内存序问题）需要特定的检测模式。LLM 可分析仿真波形和日志，自动识别异常时序模式并生成诊断报告。Vikash Kumar 的实验表明，LLM 在信号级监测上表现良好，但在**固件-软件契约边界**上易遗漏——这提示多线程仿真器的验证设计需要显式建模线程同步契约。

4. **领域模型轻量化**：ChipNeMo 证明 13B 参数模型即可在芯片设计任务上媲美 70B 通用模型。对于 mt-vlm 项目，未来可考虑在开源 Verilog/RTL 语料和 Verilator 代码库上微调小型代码模型（如 Qwen-Coder-7B、DeepSeek-Coder-7B），构建专属于 RTL 仿真器领域的 copilot，辅助代码生成、调试和文档撰写。

## 原文摘录

> "We propose VeriAssist, an LLM-powered programming assistant for Verilog RTL design workflow... VeriAssist enables the LLM to self-correct and self-verify the generated code by adopting an automatic prompting system and integrating RTL simulator in the code generation loop."
> —— *VeriAssist (arXiv:2406.00115, Huang et al.)*

> "ChipNeMo with 13B parameters matches or exceeds the performance of much larger general-purpose LLMs... on multiple chip design benchmarks."
> —— *ChipNeMo (NVIDIA, arXiv:2311.00176)*

> "The formal verification copilot market was valued at $1.8 billion in 2025 and is projected to reach $6.2 billion by 2034, growing at a CAGR of 14.7%."
> —— *DataIntelo, Formal Verification Copilot Market Report (2025)*

> "LLM-based copilots trained on SystemVerilog and PSL assertion corpora can generate syntactically correct property sets from natural language design descriptions with accuracy rates above 78%, reducing the manual property specification burden by 35% to 42%."
> —— *DataIntelo, AI in Formal Verification Report*

> "The experiment produced a fully working simulation in a fraction of traditional development time. What it also produced — and what the metrics below quantify — is a specific and measurable gap between what the AI generated and what a complete verification plan would require."
> —— *Vikash Kumar, Embedded.com (2026)*

> "Current LLM-based verification approaches focus on two primary directions: 1) Assertion generation with LLMs... 2) Test bench generation with LLMs."
> —— *A Survey of Circuit Foundation Model (SJTU, 2025)*

## 相关链接

- [Hardware Design and Verification with LLMs (Electronics 2024)](https://www.mdpi.com/2079-9292/14/1/120)
- [A Survey of Circuit Foundation Model (SJTU)](https://zhiyaoxie.github.io/files/preprint25_CFM.pdf)
- [VeriAssist: Self-Verification and Self-Correction](https://arxiv.org/abs/2406.00115)
- [ChipNeMo (NVIDIA)](https://arxiv.org/abs/2311.00176)
- [LAAG-RV 解读](https://www.themoonlight.io/en/review/laag-rv-llm-assisted-assertion-generation-for-rtl-design-verification)
- [FT-Pilot (arXiv 2605.28169)](https://arxiv.org/html/2605.28169)
- [FormalRTL (arXiv 2603.08738)](https://arxiv.org/html/2603.08738v1)
- [LLM RTL Code Generation Survey (2025)](https://www.preprints.org/manuscript/202509.1681)
- [Vikash Kumar 实验报告](https://www.embedded.com/hardware-verification-what-ai-gets-right-when-it-generates-your-testbench-and-what-it-misses/)
- [Agentic AI for Chip Verification (PatSnap)](https://www.patsnap.com/de/resources/blog/rd-blog/agentic-ai-for-chip-design-verification-2026-patsnap-eureka/)
- [Awesome-LLM4EDA (GitHub)](https://github.com/Thinklab-SJTU/Awesome-LLM4EDA)

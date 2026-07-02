---
title: "RTL 级功耗侧信道分析：SCAR 框架与预硅安全评估"
description: "RTL 级功耗侧信道分析（PSC）研究，重点关注 SCAR 框架、差分功耗分析（DPA）、相关功耗分析（CPA）及预硅安全验证方法。"
source_url: "https://www.x-mol.com/paper/1784270070721794048"
source_type: "paper"
author: "SCAR 研究团队 (IEEE TVLSI)"
date: "2024"
tags: ["side-channel", "power-analysis", "RTL", "SCAR", "GNN", "DPA", "CPA", "pre-silicon"]
keywords: ["SCAR", "power side-channel", "RTL-level analysis", "correlation power analysis", "DPA", "GNN", "CDFG", "pre-silicon"]
capture_date: "2026-07-02"
---

# RTL 级功耗侧信道分析：SCAR 框架与预硅安全评估

## 来源

- **URL**: https://www.x-mol.com/paper/1784270070721794048 (IEEE TVLSI 发表版本)
- **类型**: paper
- **作者**: SCAR 研究团队
- **日期**: 2024

> 补充来源：
> - SCAR arXiv 预印本: https://www.x-mol.com/paper/1712324714435465216
> - IEEE TDSC 远程/本地功耗侧信道攻击对策分析: https://www.x-mol.com/paper/1763053787086032896
> - RTL 功耗分析与功能仿真: https://www.xjishu.com/en/083/y475601.html

## 摘要

功耗侧信道攻击（Power Side-Channel Attack, PSC）利用加密硬件执行过程中的动态功耗差异来泄露敏感信息。传统的侧信道分析主要依赖后硅（post-silicon）物理测量，但这意味着只能在流片后发现漏洞，修复成本极高。SCAR 是一个基于图神经网络（GNN）的预硅（pre-silicon）RTL 级功耗侧信道分析框架，它将加密硬件的 RTL 设计转换为控制数据流图（CDFG），利用 GNN 检测易受侧信道泄露的设计模块，定位准确率高达 94.49%。SCAR 还集成了基于大语言模型（LLM）的自动加固组件，可在定位到的脆弱区域自动生成并插入防护代码。该框架对 AES、RSA、PRESENT、Saber、CRYSTALS-Kyber 等算法进行了验证。预硅侧信道分析的核心需求是大量 RTL 仿真以生成功耗轨迹，这对仿真器的吞吐量和并行化能力提出了极高要求。

## 关键要点

- **SCAR 框架架构**：RTL → CDFG（控制数据流图）→ GNN 推理 → 脆弱模块定位 → LLM 自动加固。这是首个将 GNN 与 LLM 结合用于 RTL 级侧信道分析的端到端框架。
- **预硅 vs 后硅分析**：后硅 PSC 分析在物理芯片上测量功耗，成本高、周期长、修复需重新流片；预硅 PSC 在 RTL 阶段通过仿真分析功耗，可在设计早期发现漏洞，但需要海量仿真数据支撑统计显著性。
- **GNN 模型性能**：在 AES、RSA、PRESENT 及后量子密码算法（Saber、CRYSTALS-Kyber）上，定位准确率 94.49%，精确率 100%，召回率 90.48%。可解释性分析将 GNN 训练特征减少了 57%。
- **DPA / CPA 基础**：差分功耗分析（DPA）和相关功耗分析（CPA）是侧信道攻击的经典方法。CPA 通过计算功耗轨迹与假设功耗模型之间的相关系数来恢复密钥，需要大量（通常 >10,000）功耗轨迹进行统计分析。
- **TVLA 与互信息分析**：Test Vector Leakage Assessment（TVLA）是标准化侧信道泄漏评估方法；互信息分析（mutual information analysis）量化信息泄露量。这些方法均需要大量仿真或测量数据。
- **防护对策**：集成稳压器（IVR）对本地攻击有效但对远程攻击无效；电源噪声注入可将所需攻击轨迹数增加 37 倍；封装去耦电容仅增加 1.3 倍，效果有限。
- **LLM 自动加固**：SCAR 使用大语言模型在 GNN 定位的脆弱区域自动生成防护代码（如掩码、随机延迟插入），实现设计加固的自动化。

## 对 RTL 仿真器多线程化的启示

1. **海量功耗轨迹生成**：CPA 和 TVLA 需要数万至数十万条功耗轨迹才能达到统计置信度。每条轨迹对应一次完整的 RTL 仿真运行。多线程仿真器可将这些轨迹生成任务并行分发到多个线程，实现近乎线性的加速。

2. **RTL 功耗建模的并行计算**：RTL 级功耗估算通常基于信号翻转率（toggle rate）和电容模型。在多线程仿真中，不同模块的功耗计算可以并行进行，但需要注意全局电源网络的耦合效应——线程间需要同步电源状态以准确建模压降（IR drop）和耦合噪声。

3. **GNN 推理与仿真 pipeline**：SCAR 框架中，RTL → CDFG 的转换和 GNN 推理可以离线进行，但验证加固效果需要反复仿真-分析循环。多线程仿真可缩短每次循环的迭代时间，加速设计空间探索（DSE）。

4. **统计分析的并行前缀**：在 TVLA 和 CPA 中，相关系数和 t-test 统计量的计算可以受益于 SIMD 和 GPU 加速。若多线程仿真器将功耗轨迹数据以内存共享方式输出，后续统计分析的并行化更为高效。

5. **时间窗口分片**：长仿真（如加密算法的完整轮次）可以按时间窗口分片，多个线程各自计算不同时段的功耗轨迹，最后拼接成完整波形。这要求仿真器支持 checkpoint/restore 或确定性重放（deterministic replay）。

## 原文摘录

> "Power side-channel (PSC) attacks exploit the dynamic power consumption of cryptographic operations to leak sensitive information about encryption hardware. Therefore, it is necessary to conduct a PSC analysis to assess the susceptibility of cryptographic systems and mitigate potential risks. Existing PSC analysis primarily focuses on postsilicon implementations, which are inflexible in addressing design flaws, leading to costly and time-consuming postfabrication design re-spins. Hence, presilicon PSC analysis is required for the early detection of vulnerabilities to improve design robustness."
> —— SCAR, IEEE TVLSI 2024

> "SCAR converts register-transfer level (RTL) designs of encryption hardware into control-data flow graphs (CDFGs) and use that to detect the design modules susceptible to side-channel leakage. Furthermore, we incorporate a deep-learning-based explainer in SCAR to generate quantifiable and human-accessible explanations of our detection and localization decisions. We have also developed a fortification component as a part of SCAR that uses large-language models (LLMs) to automatically generate and insert additional design code at the localized zone to shore up the side-channel leakage."
> —— SCAR, IEEE TVLSI 2024

> "From the experimental analysis, it is observed that within the range of designs' practical values, the adoption of on-package decoupling capacitors provides only a 1.3x increase in the minimum number of traces required to discover the secret key. However, the injection of noise in the IC power delivery network yields a 37x increase in the minimum number of traces to discover."
> —— IEEE TDSC 2024, Countermeasures Against Power Side-Channel Attacks

> "RTL Power Analysis and Optimization with Function Simulation: 基于功能仿真的RTL功耗分析及优化。"
> —— 相关学术短句索引

## 相关链接

- [SCAR: Power Side-Channel Analysis at RTL Level (IEEE TVLSI)](https://www.x-mol.com/paper/1784270070721794048)
- [SCAR arXiv 预印本](https://www.x-mol.com/paper/1712324714435465216)
- [IEEE TDSC — 远程/本地功耗侧信道攻击对策](https://www.x-mol.com/paper/1763053787086032896)
- [TVLA 标准化侧信道泄漏评估](https://www.rambus.com/tvla/)
- [SimplePower — 功耗分析工具](https://www.cs.binghamton.edu/~kannan/simplepower.html)
- [Emulation-based SoC Security Verification (arXiv, 2026)](https://arxiv.org/html/2604.15073v1)

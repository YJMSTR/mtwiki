---
title: CDC Verification & Metastability Simulation in RTL
description: 跨时钟域(CDC)验证、亚稳态建模与同步器仿真技术的综合资料
source_url: "https://dvcon-proceedings.org/wp-content/uploads/use-of-cdc-jitter-modeling-in-clock-domaincrossing-circuits-in-rtl-design-phase.pdf"
source_type: "paper"
author: "Dr. Jan Hayek, Bosch Sensortec GmbH"
date: "2017"
tags: ["CDC", "metastability", "synchronizer", "RTL-simulation", "reconvergence"]
keywords: ["clock domain crossing", "CDC-jitter", "2-FF synchronizer", "metastability injection", "multi-clock simulation"]
capture_date: "2026-06-20"
---

# CDC 验证与亚稳态仿真

## 来源

- URL: https://dvcon-proceedings.org/wp-content/uploads/use-of-cdc-jitter-modeling-in-clock-domaincrossing-circuits-in-rtl-design-phase.pdf
- 类型: 会议论文 (DVCon Europe)
- 作者: Dr. Jan Hayek, Jochen Neidhardt, Robert Richter (Bosch Sensortec GmbH)
- 日期: 2017

## 摘要

Bosch 团队在 RTL 设计阶段早期引入 CDC-jitter 建模技术，用行为级描述替代传统的确定性 2-Flip-Flop 同步器模型。该模型通过伪随机数生成器(PRNG)模拟亚稳态解析过程，使得每个同步器实例在每次仿真中表现出独立且可复现的随机行为。相比 2006 年的既有方案，Bosch 的改进在精度上更适合验证带门控时钟的低功耗同步器电路，解决了既有方案因过度悲观而无法覆盖门控时钟场景的痛点。论文还展示了 CDC reconvergence（再汇聚）问题在理想 RTL 仿真中无法暴露、但在带 jitter 的模型中几乎必然在首次仿真中触发的案例。

## 关键要点

- **RTL 仿真的确定性盲区**：标准数字 RTL 仿真不包含亚稳态概念，同步器总是按固定延迟输出，导致 reconvergence 相关 bug 在仿真中完全不可见。
- **CDC-jitter 建模核心**：在 2-FF 同步器的第一级与第二级之间引入 `META` 枚举状态，当 setup/hold 违例时，第二级 FF 从 PRNG 取随机值解析，从而模拟真实硅片中的非确定性行为。
- **种子策略**：每个同步器实例使用唯一实例种子 + 约束随机仿真种子，保证可复现性(random stability)。
- **Reconvergence 示例**：多比特计数器跨时钟域时，若逐 bit 同步，在理想仿真中看似正常，但在 CDC-jitter 模型下会因为各 bit 随机延迟不同而产生腐化值；只有 Gray 编码同步能在 jitter 存在时保持数据一致性。
- **商业工具映射**：Cadence Jasper CDC App、Questa CDC 均支持将形式化验证的属性与 Metastability Injection (MSI) 模型导出到仿真环境复用，实现「结构检查 + 功能仿真 + 亚稳态注入」的闭环验证。

## 对 RTL 仿真器多线程化的启示

1. **亚稳态注入是事件驱动调度器的变体**：在并行事件仿真中，CDC-jitter 需要在特定 timing window 内触发随机解析，这要求仿真引擎能精确建模 setup/hold violation 的边界条件。多线程化时，若不同线程分别推进不同 clock domain 的事件队列，必须保证跨域信号采样点上的全局时间同步，否则亚稳态注入的随机窗口会被错误偏移。

2. **同步器实例级别的独立随机状态**：每个 2-FF 同步器实例携带独立的 PRNG 状态，天然适合按实例分片到不同线程/NUMA 节点。但需要注意 reconvergence 路径上多个同步器实例的随机延迟必须按全局时间顺序交互，不能简单地按模块边界切分。

3. **Reconvergence 检测需要跨域数据依赖分析**：多线程仿真器在并行推进各 clock domain 时，若要复现 Bosch 论文中的 reconvergence bug，需要维护跨域信号的「有效时间戳」而非仅仅按 cycle 推进。这提示在并行仿真框架中，CDC 边界点应作为细粒度同步屏障。

## 原文摘录

> "Digital RTL simulations do not incorporate the concept of metastability and will always behave in the same deterministic way. Resolving metastability in real silicon is not deterministic. If a register becomes metastable, it resolves with a high probability within a clock-cycle to either high or low with an unpredictable probability called CDC-jitter."

> "Using CDC-jitter-modeling in addition is closing the gap between strict deterministic circuit behavior during simulation and nondeterministic behavior of silicon circuits. If used instantly from the beginning of the design phase, CDC-reconvergence problems show up with very high probability in the first simulations."

> "The advantage over existing solutions of CDC-jitter modeling is an improved precision that helps verifying custom synchronizer circuits for low-power design that use extensive clock-gating."

## 相关链接

- [VLSIFacts: Two-Stage Flip-Flop Synchronizer](https://vlsifacts.com/designing-a-two-stage-flip-flop-synchronizer-to-eliminate-metastability-in-clock-domain-crossing/)
- [MDPI: DEVS-Based CDC Synchronizer Design](https://www.mdpi.com/2079-9292/13/24/5048)
- [Questa CDC Verification Whitepaper](https://www.cadlog.com/pdf/challenges-and-trends-in-the-ic-verification-era.pdf)
- [Efficient Verification of a RADAR SoC (arXiv)](https://arxiv.org/html/2404.15371v1)

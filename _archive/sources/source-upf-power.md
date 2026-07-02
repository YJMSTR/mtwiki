---
title: UPF Power Intent & Low-Power Simulation in RTL
description: UPF（IEEE 1801）驱动的电源意图描述、低功耗 RTL 仿真中的电源域/隔离/保持机制，以及多线程仿真器对 power-gating 场景的建模挑战
source_url: "https://verificationacademy.com/topics/low-power/a-guide-to-upf-based-power-intent-verification-questa-one/"
source_type: "doc"
author: "Mentor Graphics / Siemens EDA / SemiDesignJobs / ChipVerify"
date: "2024-2026"
tags: ["UPF", "IEEE-1801", "power-gating", "low-power", "isolation-cell", "retention-register", "power-aware-simulation", "RTL"]
keywords: ["UPF", "power intent", "power domain", "isolation", "retention", "level shifter", "power aware simulation", "low power verification"]
capture_date: "2026-07-02"
---

# UPF 电源意图与低功耗 RTL 仿真

## 来源

- URL: https://verificationacademy.com/topics/low-power/a-guide-to-upf-based-power-intent-verification-questa-one/ (Questa One UPF 验证白皮书)
- URL: https://www.semidesignjobs.com/blog/low-power-asic-design-upf-ieee-1801 (低功耗 ASIC 设计实践)
- URL: https://chipverify.com/unified-power-format/upf-power-aware-synthesis (UPF 功耗感知综合)
- URL: https://www.neurealm.com/blogs/getting-started-with-unified-power-format-upf-part-1/ (UPF 入门与语法示例)
- URL: https://chipxpert.in/upf-in-vlsi-the-smartest-way-forward-for-low-power-chip-design/ (UPF 设计概述)
- URL: https://arxiv.org/pdf/2103.03564v1 (Multi-Dataflow Composer: CPF 自动生成)
- 类型: 工业白皮书 / 技术文档 / 学术论文
- 作者: Siemens EDA / SemiDesignJobs / ChipVerify / Neurealm
- 日期: 2021-2026

## 摘要

UPF（Unified Power Format，IEEE 1801）是工业界将电源意图从功能 RTL 中分离出来的标准语言。通过 UPF，设计者可以定义电源域（power domain）、供电网络（supply net）、隔离策略（isolation）、状态保持（retention）和电平转换（level shifter），而无需修改 RTL 代码本身。在 RTL 仿真阶段，支持 UPF 的仿真器（VCS、Xcelium、Questa One）能够根据电源状态在电源关断域的输出插入 X-腐蚀（corruption X），从而验证隔离逻辑是否正确。一个典型的移动 SoC 可能有 8 个电源域、2400 个隔离单元、800 个保持 FF 和 150 个电平转换器，这些特殊单元在综合阶段由工具根据 UPF 自动插入。多电压域和低功耗设计引入了「电源状态转换」这一额外的仿真维度，对 RTL 仿真器的并发调度提出了新的要求：电源域的开关操作需要原子性地影响域内所有逻辑，且与功能事件的时序关系必须精确建模。

## 关键要点

- **UPF 核心概念与语法**：
  - `create_power_domain`：定义电源域，指定域内包含的 RTL 实例。域内逻辑共享同一电源，可独立开关。
  - `create_supply_net` / `create_supply_set`：定义供电网络（VDD、VSS）和供电集，将电源域与物理电源关联。
  - `set_isolation`：在电源域边界插入隔离逻辑，当域被关断时将其输出钳位到固定值（0 或 1），防止浮空信号传播到活动域。
  - `set_retention`：定义状态保持策略，指定在电源关断期间需要保存的寄存器，通过 shadow latch 或 retention FF 实现。
  - `set_level_shifter`：处理跨电压域信号的电平转换，确保低电压域到高电压域或反之的信号完整性。
- **Flat vs Hierarchical UPF**：
  - Flat UPF：顶层文件一次性定义所有域和策略，适合小型设计，但可维护性差。
  - Hierarchical UPF：顶层文件通过 `read_upf` 引入子模块的 UPF（如 `core_a.upf`、`core_b.upf`），各子域独立维护其策略。这是大型 SoC 的标准做法。
- **Power-Aware RTL 仿真**：
  - 标准 RTL 仿真（无 UPF）无法检测电源关断导致的 bug，因为所有逻辑始终被当作「上电」状态。
  - UPF 驱动的仿真器中，当电源域被关断时，域内逻辑输出被置为 X（corruption），若未正确隔离则 X 会传播到活动域，触发仿真失败。
  - 验证重点：隔离完整性、电平转换器正确性、保持寄存器的 save/restore 时序、电源状态转换覆盖率。
- **低功耗综合与特殊单元**：
  - 标准综合（仅 RTL + 约束）会忽略 UPF，必须启用功耗感知综合（Power-Aware Synthesis）。
  - 工具自动插入隔离单元（isolation cell）、保持寄存器（retention register）、电平转换器（level shifter）和时钟门控（ICG）。
  - 物理实现阶段：在 Innovus / Fusion Compiler 中读取 UPF，完成电源开关阵列布局、常通电源环布线、IR drop 分析。
- **低功耗验证方法论**：
  - **动态仿真**：构建 UVM 测试序列，显式触发电源状态转换（active → sleep → deep-sleep），检查功能正确性。
  - **形式化验证**：JasperGold Power Apps / VC LP 可穷举检查 UPF 意图与网表的一致性，无需仿真向量，适合发现层次化设计中的隔离漏洞。
  - **覆盖率模型**：电源域状态覆盖率、电源状态转换覆盖率、跨域信号覆盖率，这些需要作为 sign-off 标准的一部分。
- **RTL 编码对低功耗的影响**：
  - 避免从电源关断域到活动域的无意组合路径。
  - 确保使能条件与 ICG 插入点对齐，以便综合工具正确推断时钟门控。
  - 在电源状态转换期间，控制信号必须保持确定值，避免在 domain power-up/down 时产生毛刺。
- **UPF 与仿真中的 X-传播**：
  - 电源关断域的输出在 UPF 仿真中变为 X，这是 X-Propagation 的一个特殊场景——与未初始化寄存器的 X 不同，这类 X 是「预期的」且应由隔离单元阻止。
  - 若隔离策略缺失或 clamp 值错误，X 会泄漏到活动域，这在 XPROP 模式下会被放大为大量下游 X，从而暴露隔离缺陷。

## 对 RTL 仿真器多线程化的启示

1. **电源域作为动态线程分组**：电源域的开关状态可以作为线程调度的一个维度。当某电源域被关闭时，域内所有逻辑应停止产生事件，对应线程可被标记为「休眠」并从调度队列中移除；当域被重新上电时，线程被唤醒。这比按固定时钟域分区更灵活，也更能反映实际功耗行为。

2. **隔离边界的跨线程同步**：隔离单元位于电源域边界，其输出值取决于活动域与关断域的相对状态。在多线程仿真中，隔离单元的评估需要同时访问两个域的信号，这要求线程间在电源状态转换点进行显式同步（barrier），确保所有域的电源状态一致后再评估边界逻辑。

3. **UPF 语义的事件驱动集成**：UPF 的电源状态转换（如 `power_state` 变化）通常由 RTL 中的控制信号触发，但在仿真中需要以「零延迟」或指定延迟立即影响域内所有逻辑。多线程引擎需要支持「全局事件」——如电源关闭命令，能够瞬间中断所有相关线程的当前评估，并强制将域内信号置为 X，而不是等待各线程自然处理到下一个事件周期。

4. **保持寄存器的 save/restore 原子性**：`set_retention_control` 的 save 和 restore 信号需要在特定时序窗口内同时作用于域内所有保持寄存器。在并行仿真中，这一操作必须是原子的：要么所有寄存器同时 save，要么都不 save，否则会出现部分保持状态、部分丢失的不一致。线程调度器需要支持「批量寄存器操作」原语，将跨多个线程的保持寄存器更新打包为单个原子事务。

5. **低功耗仿真与性能权衡**：UPF 仿真比标准 RTL 仿真更慢，因为需要额外跟踪电源状态、评估隔离逻辑和模拟 corruption。多线程引擎可以通过以下方式优化：
   - 缓存电源状态查询结果，避免每周期重复解析 UPF 策略。
   - 仅在电源状态转换后的几个周期内启用完整的 corruption 检查，其余时间按普通模式运行。
   - 对「常通域」（always-on domain）使用完全优化的 2-state 路径，仅在可关断域启用 4-state + corruption 逻辑。

6. **电源状态转换覆盖率的并行收集**：多线程仿真器需要线程安全的覆盖率数据库，用于收集电源域状态覆盖和转换覆盖。由于电源状态转换是低频事件（相对于功能事件），建议由一个专用线程（或主线程）统一记录，而非各线程分散上报后合并，以减少锁竞争。

## 原文摘录

> "The UPF, formalized as IEEE 1801, was developed to give engineers a way to describe how power is managed in a chip without having to embed that information directly into the RTL. By separating RTL from power intent, the design can be reused and can target multiple market segments."

> "Functional simulation with UPF requires a power-aware simulator. Cadence Xcelium and Synopsys VCS both support UPF-annotated simulation. The simulator models supply states, inserting corruption X-propagation when a domain is off and logic in that domain is accessed, which catches missing isolation or incorrect clamp values."

> "A mobile processor design had 8 power domains with 2,400 isolation cells, 800 retention flip-flops, and 150 level shifters. The first power-aware synthesis run took 6 hours and consumed 45,000 um² for special cells (3% of total area). After optimizing cell placement and using smaller library cells, area dropped to 28,000 um² (1.8%)."

> "Power-aware verification must run in parallel with RTL development; catching isolation or retention errors in simulation is orders of magnitude cheaper than catching them in silicon."

> "Standard synthesis optimizes for area, timing, and dynamic power in a single voltage domain. Power-aware synthesis extends this to handle multiple power domains, insert special cells (isolation, retention, level shifters), manage multiple supply networks, and optimize leakage power through multi-Vt cell selection."

## 相关链接

- [Questa One: UPF-Based Power Intent Verification (Siemens)](https://verificationacademy.com/topics/low-power/a-guide-to-upf-based-power-intent-verification-questa-one/)
- [Low-Power ASIC Design: UPF and IEEE 1801 Flows (SemiDesignJobs)](https://www.semidesignjobs.com/blog/low-power-asic-design-upf-ieee-1801)
- [UPF Power Aware Synthesis (ChipVerify)](https://chipverify.com/unified-power-format/upf-power-aware-synthesis)
- [Getting Started with UPF Part 1 (Neurealm)](https://www.neurealm.com/blogs/getting-started-with-unified-power-format-upf-part-1/)
- [UPF in VLSI: Low-Power Chip Design (ChipXpert)](https://chipxpert.in/upf-in-vlsi-the-smartest-way-forward-for-low-power-chip-design/)
- [Multi-Dataflow Composer: CPF Auto-Generation (arXiv)](https://arxiv.org/pdf/2103.03564v1)

---
title: Reset Strategy & Power-On Initialization in RTL Simulation
description: 复位策略选型、上电初始化序列、复位树与异步复位同步释放的工业实践，以及 RTL 仿真中复位相关 bug 的排查方法论
source_url: "https://www.realintent.com/reset-domain-crossing-methodology-ai-llm-chips-rivos/"
source_type: "blog"
author: "Real Intent / EcrioniX / OpenROAD Community"
date: "2024-2026"
tags: ["reset-strategy", "power-on-reset", "async-reset-sync-release", "reset-tree", "RDC", "initialization", "RTL-simulation"]
keywords: ["asynchronous reset", "synchronous reset", "reset synchronizer", "reset domain crossing", "power-on reset", "reset tree", "boot sequence", "POR"]
capture_date: "2026-07-02"
---

# RTL 仿真中的复位策略与上电初始化

## 来源

- URL: https://www.realintent.com/reset-domain-crossing-methodology-ai-llm-chips-rivos/ (RDC 方法论)
- URL: https://github.com/The-OpenROAD-Project/OpenROAD/issues/4623 (MegaBoom 复位树与 QoR)
- URL: https://github.com/The-OpenROAD-Project/OpenROAD/discussions/4522 (同步复位与 pipeline staging)
- URL: https://github.com/chipsalliance/chisel3/issues/1735 (CDC / Reset 库提案)
- URL: https://www.verific.com/faq/index.php?title=Difference_between_RTL_and_gate-level_simulations (RTL vs GLS 复位行为差异)
- 类型: 技术博客 / GitHub Issue / 工业实践
- 作者: Rivos / Real Intent / OpenROAD 社区 / Verific
- 日期: 2022-2024

## 摘要

复位是 RTL 仿真中最容易出错的领域之一。工业界的标准策略是「异步置位、同步释放」(async-assert / sync-deassert)：复位信号在任意时刻异步拉低，但通过每个时钟域独立的 2~3 级复位同步器释放，以避免亚稳态和不同时钟域唤醒顺序导致的功能错乱。大型 SoC（如 Chipyard MegaBoom）的复位树面临高达 50,000+ 扇出的同步复位信号，需要插入 pipeline stage 才能满足时序；FPGA 与 ASIC 在复位策略上存在根本差异——FPGA 通常采用纯同步复位以节省 SR/CE 资源。复位域交叉（RDC）和 RTL 与门级仿真（GLS）的复位行为差异是两类极隐蔽的 bug 来源。此外，Chisel/FIRRTL 社区正在推进将复位类型（异步/同步/异步置位同步释放）作为类型系统的一部分，以便在编译期检查复位域一致性。

## 关键要点

- **异步置位、同步释放的复位同步器**：
  - 每时钟域放置一个 `reset_synchronizer` 模块，使用异步复位输入 `arst_n`，输出 `srst_n`（同步释放）。
  - 典型实现：2 级 FF 链，第一级捕获异步复位，第二级在目标时钟域同步释放。
  - 避免了「复位释放时的亚稳态」和「不同域 FF 在不同时钟沿退出复位导致的功能不一致」。
- **同步复位的高扇出困境**：
  - MegaBoom 的同步复位信号扇出超过 50,000，仅靠 3 级 pipeline stage 在 high-frequency 下仍可能不足。
  - 解决方案：在 RTL 中显式插入更多级 reset pipeline，或依赖综合 retiming（但 retiming 会引入验证风险）。
  - 同步复位本质上是「具有巨大扇出的同步使能信号」，其分发问题必须在 RTL 和综合阶段同时解决。
- **FPGA vs ASIC 复位策略差异**：
  - ASIC：标准做法是 async-assert / sync-deassert，允许快速响应但保证释放同步。
  - FPGA：推荐纯同步复位，因为 FPGA FF 通常只有一个 SR/CE 引脚，异步复位会占用专用资源并增加 routing 复杂度。
  - 某些设计（如 NoX RISC-V core）通过宏定义 `TARGET_FPGA` / `TARGET_ASIC` 在编译期切换复位策略。
- **RTL vs GLS 的复位行为差异**：
  - RTL 仿真中，异步 set/reset 的 always 块在 `posedge clk` 或 `negedge rst_n` 触发时，若同时存在 set 和 reset，LRM 的优先级规则可能导致与门级仿真不同的结果。
  - 例如：当 `rst_n` 和 `set_n` 同时变化时，RTL 仿真可能输出与 GLS 不一致的值，需要通过 `translate_off`/`translate_on` 块中的 `force`/`release` 在仿真中显式修正。
- **RDC（Reset Domain Crossing）风险**：
  - 与 CDC 类似，复位信号跨域时若未同步，可能导致释放顺序错乱。
  - 异步复位驱动的时钟门控使能端（ICG enable）会产生 static timing analysis 无法覆盖的 untimed path，复位断言时 FF 输出会独立于时钟翻转，在 ICG 后产生时钟毛刺。
- **复位树与初始化序列**：
  - 大型 SoC 的上电初始化序列通常分为：POR（Power-On Reset）→ 时钟稳定 → 复位释放 → 软件初始化寄存器/刷 FIFO → 功能启动。
  - 并非所有 FF 都需要硬件复位；数据通路 pipeline 寄存器通常不需要，可通过有效数据流自然冲刷。但控制寄存器、状态机必须复位。
  - 未复位的 FF 上电后为 X 态，是 X-Propagation 仿真的主要源头之一。

## 对 RTL 仿真器多线程化的启示

1. **复位树是全局广播信号**：复位信号通常驱动成千上万个 FF，在并行仿真中属于跨线程广播。若每个线程都独立处理复位信号，需要确保「复位释放」在所有线程中满足同一个时钟沿的同步约束。一种策略是将复位同步器放在主线程，释放后的 `srst_n` 作为每线程本地常量广播，避免每周期重复评估。

2. **上电初始化与 X-传播**：未复位 FF 的 X 态在并行仿真中需要特殊处理。若多线程引擎采用 2-state 优化（将 X 映射为 0/1），则与 4-state 仿真的行为可能不一致。多线程 RTL 仿真器若支持 X-Propagation 模式，需在初始化阶段统一标记未复位寄存器为 X，并确保跨线程传递时保持 X 的语义完整性。

3. **复位释放顺序与确定性**：多线程仿真的非确定性事件调度可能在复位释放阶段引入不同的 interleaving，导致有时序敏感的设计（如握手协议）在每次运行中表现不同。建议多线程仿真器在「复位释放窗口」内强制使用确定性调度（barrier-sync），确保所有域在释放后的第一个时钟沿前状态一致。

4. **RDC 检测与并行仿真**：RDC 问题（如异步复位驱动的 ICG enable）在 RTL 仿真中通常不可见，因为仿真不建模 untimed path。多线程仿真器可在仿真初始化阶段引入静态 RDC 分析结果，在门控时钟使能端插入 assertion，一旦发现复位信号与时钟域不匹配即报错，而非依赖 GLS 后才发现。

## 原文摘录

> "ASIC: async-assert / sync-deassert is the standard. Fast, glitch-free assertion; metastability-safe deassert. Requires a 2-stage reset synchronizer per clock domain. The cardinal rule either way: never gate the reset signal with logic in RTL — reset must come from a properly synchronized source."

> "A synchronous reset should not be thought of as a reset. It is better thought of as a synchronous enable signal with a giant fan-out. The solution to handling this fanout is indeed what you describe above: add pipeline stages. MegaBoom does add these pipeline stages (though I think 3 stages for a fanout of at least 50000 is a bit light at higher frequencies)."

> "To correct this issue, the simulator needs some help from the designer. The RTL code is modified to force q to 1 when rst_n is 1 and set_n is 0... The 'extra' code is ignored by synthesis tools due to the pragmas translate_off/on. Now the result of RTL simulation matches that of gate-level simulation."

> "There are mainly three flop coding styles which are: Flop with asynchronous set/reset; Flop with synchronous set/reset; Flop with asynchronous and synchronous set/reset. Asynchronous set/reset pin is not synchronized with the clock and it has got highest priority as compared to all other inputs."

## 相关链接

- [Rivos' Reset Domain Crossing Methodology (Real Intent)](https://www.realintent.com/reset-domain-crossing-methodology-ai-llm-chips-rivos/)
- [OpenROAD: MegaBoom QoR — Reset & Clock Tree Issues](https://github.com/The-OpenROAD-Project/OpenROAD/issues/4623)
- [OpenROAD Discussion: Synchronous Reset Pipeline](https://github.com/The-OpenROAD-Project/OpenROAD/discussions/4522)
- [Chisel3 RFC: CDC Library with Reset Type Annotation](https://github.com/chipsalliance/chisel3/issues/1735)
- [Verific: RTL vs Gate-Level Simulation — Async Set/Reset](https://www.verific.com/faq/index.php?title=Difference_between_RTL_and_gate-level_simulations)
- [NoX RISC-V Core: FPGA vs ASIC Reset Targeting](https://github.com/aignacio/nox)

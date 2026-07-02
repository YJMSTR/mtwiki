---
title: Reset Synchronization & Glitch-Free Clock Gating in RTL
description: 复位同步策略、复位域交叉(RDC)验证与无 glitch 时钟门控的工业级实践
source_url: "https://ecrionix.org/rtl_design/coding-guidelines/"
source_type: "blog"
author: "EcrioniX"
date: "2026-05-23"
tags: ["reset-synchronization", "clock-gating", "RDC", "glitch-free", "RTL-coding"]
keywords: ["async assert sync deassert", "reset synchronizer", "reset domain crossing", "ICG", "clock gating cell", "glitch"]
capture_date: "2026-06-20"
---

# 复位同步与时钟门控验证

## 来源

- URL: https://ecrionix.org/rtl_design/coding-guidelines/
- 类型: 技术博客 / RTL 设计最佳实践
- 作者: EcrioniX
- 日期: 2026-05-23
- 补充来源:
  - https://www.realintent.com/reset-domain-crossing-methodology-ai-llm-chips-rivos/ (Rivos RDC 案例)
  - https://www.edn.com/design-faults-leading-to-clock-and-data-glitches/ (EDN: 时钟与数据毛刺)

## 摘要

ASIC 工业界的标准复位策略是「异步置位、同步释放」(async-assert / sync-deassert)：复位信号异步断言以保证快速响应，但通过每个时钟域独立的 2 级复位同步器释放，避免亚稳态和不同时钟边沿唤醒导致的功能错乱。与之相对，时钟门控在 RTL 中严禁用组合逻辑直接写 `gated_clk = clk & enable`，因为这会在 enable 变化时产生 glitch；正确做法是写 Clock Enable (CE) 模式，让综合工具自动插入 ICG (Integrated Clock Gating) 库单元。Rivos 在 AI 大芯片上的 RDC (Reset Domain Crossing) 实践表明，复位域交叉和异步复位驱动的时钟门控使能端是两类极易引发系统故障的根因，需要通过静态工具 + 场景化约束进行 sign-off。

## 关键要点

- **异步置位同步释放复位同步器**：
  - 每时钟域放置一个 `rst_sync` 模块，使用 2 级（或更多）FF 链将异步 `arst_n` 转换为同步释放的 `srst_n`。
  - 设计中的 FF 使用 `always_ff @(posedge clk or negedge srst_n)`，确保复位断言无时钟依赖、释放时与目标时钟同步。
- **FPGA 与 ASIC 的差异**：
  - ASIC 标准：async-assert / sync-deassert。
  - FPGA：推荐纯同步复位，因为 FPGA FF 通常只有一个 SR/CE 引脚，异步复位会占用宝贵资源并增加 routing 复杂度。
- **CE 模式 vs 门控时钟**：
  - 错误：`wire gated_clk = clk & cond; always @(posedge gated_clk)` —— 当 `cond` 在 `clk=1` 期间翻转时会产生 runt pulse，仿真因为 unit delay 很难捕捉，硅片却会 corrupt FF 状态。
  - 正确：`always_ff @(posedge clk) if (enable) q <= d;` —— 综合工具会映射到 FF 的专用 CE 引脚，glitch-free 且功耗优化由 UPF/CPF 驱动的 ICG 插入完成。
- **RDC 与复位交叉毛刺**：
  - 当异步复位置位时，驱动时钟门控使能端的 FF 输出会独立于时钟边沿翻转，形成静态时序分析无法覆盖的 untimed path，传播到 ICG 后产生时钟毛刺。
  - Rivos 的修复方案：要求驱动 ICG 使能的复位必须「断言和释放都与被门控时钟同步」。
- **Rivos 的 RDC 方法论**：
  - 在 CDC-clean 的基础上运行 RDC；定义复位场景（boot、warm reset 等）和约束（exclusive signals、blocking signals）。
  - 通过 Meridian RDC 的 iDebug 工具区分 setup error 与真实 RDC violation，修复后再 sign-off。

## 对 RTL 仿真器多线程化的启示

1. **复位树是全局高扇出信号**：复位信号通常驱动成千上万个 FF，在并行仿真中属于「广播式」控制信号。多线程化时，复位网络的分发不应成为瓶颈——可考虑将复位同步器后的 `srst_n` 作为每线程本地副本，减少跨线程同步开销。

2. **时钟门控与事件驱动调度**：ICG 的使能端来自组合逻辑或 FF 输出，在并行仿真中，若门控时钟域被 shutting down，事件调度器需要支持「跳过无活动事件的时钟域」以节省 CPU。这要求多线程引擎能够动态挂起/唤醒特定时钟域的线程，而非按固定周期轮询。

3. **RDC 验证与仿真一致性**：RDC 静态工具发现的 violation（如异步复位驱动 ICG）在 RTL 仿真中可能表现正常，因为仿真不建模 untimed path 的 glitch。多线程 RTL 仿真器若要增强 RDC 检测能力，可在门控时钟使能端引入类似 CDC-jitter 的随机毛刺注入机制，把静态 RDC 问题转化为可复现的仿真失败。

## 原文摘录

> "ASIC: async-assert / sync-deassert is the standard. Fast, glitch-free assertion; metastability-safe deassert. Requires a 2-stage reset synchronizer per clock domain. The cardinal rule either way: never gate the reset signal with logic in RTL — reset must come from a properly synchronized source."

> "The CE pattern writes always_ff with an if(enable) condition, which synthesis maps to the flip-flop's dedicated CE input. This is glitch-free because the CE pin samples before the clock edge — it cannot create a runt pulse. Gating the clock signal with combinational logic (clk AND cond) creates glitches whenever cond changes while clk=1. These glitches are hard to detect in simulation (which uses unit delay) and can corrupt flip-flop state in silicon."

> "Meridian RDC identified an incorrectly reset clock gater (gating cell) bug where an asynchronously reset flop drove the clock gater enable input. When asynchronous reset asserts, the reset flop output toggles independently of the clock edge. Since static timing analysis operates clock-edge to clock-edge, this created an untimed path that can propagate metastability."

## 相关链接

- [Rivos' Reset Domain Crossing Methodology (Real Intent)](https://www.realintent.com/reset-domain-crossing-methodology-ai-llm-chips-rivos/)
- [EDN: Design Faults Leading to Clock and Data Glitches](https://www.edn.com/design-faults-leading-to-clock-and-data-glitches/)
- [EE News Europe: Structural Faults Leading to Glitches](https://www.eenewseurope.com/en/structural-faults-leading-to-glitches/)
- [RTL Development Guide — EcrioniX](https://ecrionix.org/rtl_design/rtl-development/)

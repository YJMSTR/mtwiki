---
title: X-Propagation & Initialization in RTL Simulation
description: RTL 仿真中 X-传播（X-Optimism / X-Pessimism）的机制、未初始化寄存器的影响，以及 VCS / Xcelium 等工具中 XPROP 模式的工业实践
source_url: "https://www.einfochips.com/blog/x-propagation-simulation-a-powerful-feature/"
source_type: "blog"
author: "Abhay Sonagara / Stuart Sutherland / Tuukka Haapakumpu"
date: "2013-2026"
tags: ["X-propagation", "X-optimism", "X-pessimism", "initialization", "RTL-simulation", "SystemVerilog", "GLS"]
keywords: ["X propagation", "unknown state", "uninitialized register", "X optimism", "X pessimism", "SystemVerilog 4-state", "VCS xprop", "Xcelium", "gate-level simulation"]
capture_date: "2026-07-02"
---

# RTL 仿真中的 X-传播与初始化问题

## 来源

- URL: https://www.einfochips.com/blog/x-propagation-simulation-a-powerful-feature/ (X-Propagation 仿真概述)
- URL: https://trepo.tuni.fi/bitstream/handle/10024/143682/HaapakumpuTuukka.pdf (硕士论文：X-Propagation in RTL Simulation)
- URL: https://sutherland-hdl.com/papers/2013-DVCon_In-love-with-my-X_paper.pdf (Stuart Sutherland DVCon 2013)
- URL: https://www.verilogpro.com/systemverilog-verilog-x-optimism-pessimism/ (X Optimism vs Pessimism 技术博客)
- URL: https://www.thevtool.com/how-to-maskor-unmask-certain-modules-paths-in-x-propagation/ (X-Propagation 模块掩码)
- URL: https://jantsch.se/AxelJantsch/papers/2017/ChristianKrieg-DAC.pdf (X-Optimism 与硬件安全)
- 类型: 技术博客 / 学术论文 / 工业白皮书
- 作者: Abhay Sonagara (eInfochips) / Stuart Sutherland (Sutherland HDL) / Tuukka Haapakumpu (Tampere University)
- 日期: 2013-2026

## 摘要

Verilog/SystemVerilog 定义了 4 值逻辑（0, 1, Z, X），其中 X 表示未知或不确定值。在 RTL 仿真中，LRM 规定条件表达式含 X 时默认求值为 false，这导致「X-乐观主义」(X-optimism)：X 被悄悄地转换为 0 或 1，隐藏深层设计 bug。与之相对，门级仿真（GLS）和 X-Propagation（XPROP）模式采用更悲观的传播规则，使 X 值扩散到下游逻辑，从而暴露初始化缺陷。然而过度悲观（X-pessimism）会导致「X 污染」——大量寄存器被 X 淹没，掩盖真正的数据来源。X 的最主要来源是未复位的寄存器/锁存器、上电未初始化的存储器，以及电源关断域的输出。在工业实践中，Synopsys VCS 的 `xprop` 模式和 Cadence Xcelium 的 `-xfile` 配置是检测 X-optimism bug 的标准手段，但会带来 15-20% 的仿真性能下降。论文还指出，X-optimism 不仅是功能验证问题，还可能被恶意利用来隐藏硬件木马。

## 关键要点

- **X-Optimism（X-乐观主义）**：
  - SystemVerilog LRM 默认行为：条件表达式中的 X 求值为 false，导致 `if (sel) y = a; else y = b;` 在 `sel = X` 时总是走 else 分支。
  - 这会在 RTL 仿真中把 X 悄悄「吃掉」，输出看起来是确定的值，但硅片行为可能并非如此。
  - 例如：AND 门输入 `0` 和 `X`，RTL 输出 `0`（与硅片一致）；但 OR 门输入 `1` 和 `X`，RTL 输出 `1`（也与硅片一致）——这些属于「合理的乐观」。然而当选择信号为 X 而数据输入不同时，RTL 输出确定值而硅片输出不确定，属于「过度乐观」。
- **X-Propagation（X-传播）**：
  - 当 RTL 综合为门级网表后，选择信号为 X 时，输出会变为 `XX...X`，因为门级实现是真实的多路选择器/逻辑门。
  - XPROP 模式让 RTL 仿真器模拟门级的 X 传播行为，在 RTL 阶段就提前发现 GLS 才会暴露的 bug。
- **X-Pessimism（X-悲观主义）**：
  - 仿真器将 X 值无差别地传播到下游，即使某些位在物理上并无不确定性。
  - 例如：时钟分频器的 FF 上电时若为 X，经反相器反馈后输入也变为 X，在悲观仿真中该分频器会永远卡在 X 态，而物理芯片会随机上电为 0 或 1 并正常分频。
  - 过度悲观导致调试困难——X 的来源可能在很远的前级，需要逐周期追溯。
- **X 的主要来源与初始化策略**：
  - 未复位的 FF 和锁存器是 X 的最大来源；在大型设计中，并非所有 FF 都连到复位树（尤其数据通路 pipeline）。
  - 未初始化的存储器（RAM）上电后读出 X，若直接用于条件判断会触发 X-optimism。
  - 电源关断域（power-gated domain）恢复供电时，输出可能为 X，需要隔离单元（isolation cell）在关断期间将输出钳位到确定值。
  - 一种极端策略是「随机初始化」：仿真开始时将所有未复位寄存器随机赋值为 0 或 1，而非 X。这消除了 X 问题，但可能遗漏仅在某些上电状态才会触发的 bug。
- **工业工具实践**：
  - **Synopsys VCS**：`+vcs+xprop` 或 `xprop` 配置文件，支持 `merge` / `tmerge` 模式，可选择性地按模块启用/禁用 XPROP。
  - **Cadence Xcelium**：`-xfile <xfile.config>`，支持 `C`（Compute-as-Ternary）和 `D`（Default RTL）模式，可精确控制每个模块的 X 传播行为。
  - **Mentor Questa**：`+acc` 与 `xprop` 插件，支持 `pass` / `resolve` / `trap` / `none` 模式，其中 `resolve` 最接近硅片行为。
- **调试 XPROP 问题的方法论**：
  - 追溯第一个 X 的来源：重点关注未复位的数据通路 FF 和初始化前的内部时钟生成逻辑。
  - 在 UVM TB 中避免驱动不必要的 X（如顶层 tie-off 信号不应为 X）。
  - 使用 `ifdef XPROP_SIM` 封装 TB workaround，确保不影响正常 RTL 仿真。
  - 启用 X-detect assertion：`assert (^cond === 1'bx)` 或 `$isunknown()` 系统函数。
  - Formal X-Propagation Verification（FXP）：形式化引擎在疑似 X 源点注入 X，穷举检查关键目的地是否被污染。

## 对 RTL 仿真器多线程化的启示

1. **4-state 与 2-state 的多线程一致性**：X-Propagation 要求仿真器维护 4-state 语义。若多线程引擎为提升性能采用 2-state（bit-packed）存储，则必须在 XPROP 模式下回退到 4-state，或至少在 X 值跨线程边界时正确传播。线程间数据交换的 packing/unpacking 逻辑必须保留 X/Z 编码，不能简单截断为 0/1。

2. **初始化阶段的并行 determinism**：上电初始化时，各线程并行设置未复位寄存器为 X。若使用「随机初始化」策略（用不同 seed 给各线程随机赋值），必须确保 seed 的全局一致性，否则每次运行结果不同，导致不可复现的 bug。建议由主线程统一生成随机初始化向量，再广播到各工作线程。

3. **X-传播范围控制与局部性**：XPROP 模式支持按模块/路径选择性启用。多线程调度器可以利用这一局部性：仅标记处于 XPROP 模块的线程需要执行 4-state 传播逻辑，其余模块可走优化的 2-state 路径。模块级的 XPROP 掩码可作为编译期信息，指导线程分区策略。

4. **X-悲观主义与仿真收敛**：X-pessimism 会导致大量信号变为 X，增加事件队列中的「不确定事件」数量。多线程事件调度器需要高效处理「X 到 X」的无效翻转（不产生新事件），避免在 X 污染区域空转。一种优化是：当某信号处于 X 态且所有输入也为 X 时，跳过该信号的事件评估。

5. **与 GLS 的 X 语义对齐**：多线程 RTL 仿真器若引入 XPROP，其目标是「RTL 仿真结果尽可能接近 GLS」。这意味着线程间需要统一实现与门级等效的 X 传播表（如真值表级 X 处理），而不是各线程自行解释 LRM。这要求仿真核心有一个全局共享的 X-传播真值表，或至少保证各线程实现严格一致。

## 原文摘录

> "X-optimism has been defined in this paper as any time simulation converts an X value on the input to an operation or logic gate into a 0 or 1 on the output. X-optimism is essential for some simulation conditions, such as the synchronous reset circuit. SystemVerilog can be overly optimistic, meaning an X propagates as a 0 or 1 in simulation when actual silicon is still ambiguous."

> "X-propagation simulation is a digital design verification technique used in EDA to trace 'unknown' logical states through a digital circuit, making it essential for identifying potential issues early in the verification process. XPROP sims are not as slow as the GLS and the Xs also get debugged easily."

> "One component often mentioned is a multiplexer declared with an if-else statement... When the control signal is X and other inputs are the same, the output takes these values, but when the inputs are different, the output should be X in silicon. However, in RTL simulation, the output gets assigned the else value."

> "X-pessimism means the simulator handles X-values too pessimistically, resulting in an excessive amount of X-values being assigned and propagated. A simulation might lock up because of X-values where possibly ambiguous values in silicon wouldn't cause this problem."

> "All RTL models intended for synthesis should have SystemVerilog assertions detect X values on if...else and case select conditions. Other critical signals can also have X-detect assertions on them."

## 相关链接

- [X-Propagation Simulation: A Powerful Feature (eInfochips)](https://www.einfochips.com/blog/x-propagation-simulation-a-powerful-feature/)
- [Tampere University: X-Propagation in RTL Simulation (PDF)](https://trepo.tuni.fi/bitstream/handle/10024/143682/HaapakumpuTuukka.pdf)
- [Stuart Sutherland: I'm Still In Love With My X! (DVCon 2013)](https://sutherland-hdl.com/papers/2013-DVCon_In-love-with-my-X_paper.pdf)
- [SystemVerilog X Optimism vs Pessimism (VerilogPro)](https://www.verilogpro.com/systemverilog-verilog-x-optimism-pessimism/)
- [Vtool: Masking Modules in X-Propagation](https://www.thevtool.com/how-to-maskor-unmask-certain-modules-paths-in-x-propagation/)
- [Toggle MUX: X-Optimism & Hardware Security (DAC 2017)](https://jantsch.se/AxelJantsch/papers/2017/ChristianKrieg-DAC.pdf)

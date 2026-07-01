---
title: "形式化验证与 RTL 仿真结合：BMC、K-Induction 与 Tandem 验证"
description: "涵盖有界模型检查（BMC）、K-Induction、IC3/PDR 等 SAT/SMT 形式化方法在 RTL 硬件验证中的应用，以及开源工具链（Yosys/SymbiYosys、rIC3）与商业工具（JasperGold、Questa Formal）的对比。"
source_url: "https://arxiv.org/html/2502.13605v1"
source_type: "paper"
author: "Yuheng Gao, Song Qiu, et al."
date: "2025-02-19"
tags: ["formal-verification", "BMC", "k-induction", "IC3", "RTL", "Yosys", "SymbiYosys", "rIC3", "JasperGold"]
keywords: ["bounded model checking", "k-induction", "hardware model checking", "SAT solver", "SMT solver", "RTL verification", "formal simulation tandem"]
capture_date: "2026-07-02"
---

# 形式化验证与 RTL 仿真结合：BMC、K-Induction 与 Tandem 验证

## 来源

- **URL**: https://arxiv.org/html/2502.13605v1 (rIC3 Hardware Model Checker)
- **URL**: https://arxiv.org/html/2407.12232v1 (RTL Verification for Secure Speculation)
- **URL**: https://dl.acm.org/doi/pdf/10.1145/3620666.3651346 (RTL-REPAIR)
- **URL**: https://electronics.stackexchange.com/questions/594846 (BMC/k-induction in RTL formal verification)
- **类型**: 论文 / 技术文档 / 社区问答
- **作者**: Yuheng Gao et al. (rIC3); Multiple authors
- **日期**: 2024–2025

## 摘要

形式化验证（Formal Verification）与 RTL 仿真之间并非替代关系，而是互补的协同关系。有界模型检查（BMC）将 RTL 设计的状态转移关系展开 k 个周期，利用 SAT 或 SMT 求解器穷尽搜索所有可能的输入组合，以发现深度 bug。K-Induction 在 BMC 基础上增加归纳步骤，弥补 BMC 的固有不完备性。IC3/PDR 则通过增量构造归纳不变量，无需显式展开即可获得完备证明。rIC3 等现代工具采用 16 线程并行 Portfolio 策略（11 线程 IC3 + 4 线程 BMC + 1 线程 K-Induction），在 HWMCC'24 中取得最优成绩。开源工具链 Yosys + SymbiYosys + yosys-smtbmc 为工业 RTL 设计提供了零成本的形式化验证入口，而 Cadence JasperGold 和 Mentor Questa Formal 则代表了商业级完备方案。

## 关键要点

- **BMC（Bounded Model Checking）**: 从任意状态出发，将系统展开 k 个周期，询问 SAT/SMT 求解器是否存在使断言失败的输入。结果要么保证断言在 k 步内全部成立，要么给出反例跟踪。BMC 随 k 增大通常呈指数级变慢。工具实现：Yosys-SMTBMC、Cadence JasperGold BMC、Mentor Questa Formal。

- **K-Induction**: 在 BMC 的基例（Base Case）之外增加归纳步骤（Induction Step），检查若属性在前 k 个状态成立，则第 k+1 个状态是否也成立。对于非归纳属性，K-Induction 通过 strengthen（属性加强）来寻找归纳不变量。K-Induction 与 BMC 结合，在理论上可逼近完备性（需增加路径约束）。

- **IC3/PDR（Property Directed Reachability）**: 通过单调帧序列和归纳子句挖掘，增量构造不变量，无需显式展开转移关系。与 BMC 相比，IC3 在证明收敛上往往更稳健，但归纳泛化（inductive generalization）的质量直接决定效率。CtgDown、EXCTG 等优化显著提升了泛化能力。

- **rIC3 并行 Portfolio**: rIC3 在 Rust 中实现，IC3 引擎仅约 1700 行代码。其竞赛版本采用 16 线程并行 Portfolio：11 线程运行不同参数组合的 IC3，4 线程运行不同步长的 BMC，1 线程运行 K-Induction。此策略已被集成到 SymbiYosys 后端，可直接验证工业 RTL 设计。

- **Tandem Verification（形式化 + 仿真协同）**: Cadence JasperGold 的 "assertion-driven simulation" 模式允许先用仿真探索状态空间，再将剩余深度交给形式化引擎。Broadcom 的 Alderaan 案例研究显示，对控制逻辑块和小顺序深度的模块，纯形式化验证可节省 30–40% 时间；而复杂数据通路仍需仿真补充。JasperGold 的 Trident 多引擎协作技术会根据逻辑行为动态切换引擎，将证明任务在不同引擎间移交。

- **Yosys/SymbiYosys 开源工具链**: 
  - Yosys 读取 Verilog/SystemVerilog 并综合为内部网表；
  - `yosys-smtbmc` 将 RTL 转换为 SMT-LIB 格式，调用 SMT 求解器（Yices 2、Z3、Bitwuzla、CVC5）进行 BMC；
  - SymbiYosys（SBY）作为前端驱动，支持 `bmc`（有界证明）、`prove`（无界证明）、`cover`（覆盖目标搜索）三种模式；
  - rIC3 已作为 SBY 后端集成（PR #313），支持工业级 RTL 验证。

- **性能数据**:
  - BMC 的运行时间随展开深度 k 通常呈指数增长；
  - rIC3 的 IC3 引擎仅约 1700 LOC，在 HWMCC'24 位级和字级（bit-blasting）双赛道均排名第一；
  - Cadence 第三代 JasperGold 平台宣称平均 2× 开箱即用证明加速，回归测试可达 5× 提速；
  - Broadcom 的 Alderaan 项目（网络数据包路由器）使用纯形式化签核，共 63K 属性，耗时约一年，接收端数据通路成功闭合，发射端数据通路因复杂度评估困难未完全闭合。

## 对 RTL 仿真器多线程化的启示

1. **BMC 的展开深度 k 直接对应仿真时间窗口**: 如果 RTL 仿真器能并行展开多个时间窗口（如将 k 周期切分为多个子区间并行求解），可借鉴 BMC 的 SAT 并行化思路。但 RTL 事件驱动仿真与 SAT 求解器的状态空间搜索机制不同，直接映射并不 trivial。

2. **Portfolio 并行策略可迁移**: rIC3 的 16 线程 Portfolio（多配置 BMC + K-Induction + IC3）证明，对同一 RTL 设计同时运行多种验证策略，并取最先完成的结果，是一种高性价比的并行加速范式。RTL 多线程仿真器可以借鉴此思路，同时运行不同随机种子、不同约束条件的测试，通过覆盖率共享减少冗余。

3. **形式化 + 仿真的 Tandem 模式对调度提出新要求**: 当仿真器与形式化引擎协同工作时，两者需要频繁交换覆盖率和反例信息。RTL 仿真器的线程调度若能在检测到覆盖率饱和时，自动触发形式化引擎的补全验证，可形成更高效的混合验证闭环。

4. **Yosys 的 AIG 表示与 RTL 仿真器的 IR 层可复用**: Yosys 在内部将 RTL 转换为 AIG（And-Inverter Graph）以加速 SAT 求解。如果 RTL 仿真器在编译阶段同样采用 AIG 或类似中间表示，可在形式化验证与仿真之间共享底层数据结构，减少重复编译开销。

## 原文摘录

> "Bounded model checking (BMC) is a popular formal technique to find bugs in hardware designs: Starting from an arbitrary state, it unrolls the system for k cycles and asks a formal engine based on SAT or SMT if there exist any inputs, and starting state which will make an assertion in the design fail. The result is either the assurance that all assertions hold for up to k cycles or a trace that shows how the assertion can fail. Bounded model checking generally gets slower as k increases, often exponentially so."
> — RTL-REPAIR (ASPDAC 2024)

> "rIC3 includes a 16-thread parallel portfolio combining IC3, BMC, and K-Induction configurations, which is also the competition version. Specifically, it uses 11 threads for IC3 with different combinations of the techniques mentioned above, 4 threads for BMC with varying steps, and 1 thread for K-Induction."
> — rIC3 paper (arXiv:2502.13605)

> "You first explore with simulation then hand over to the formal engine to explore... I might not want to waste the engine's time completely verifying on a FIFO, so I might simulate its behavior and then hand over the rest to the formal engine."
> — Pete Hardee, Cadence (2015)

> "SymbiYosys is an open-source frontend driver program for Yosys-based formal hardware verification flow. It supports bounded verification of safety properties (assertions), unbounded verification of safety properties (k-induction), and generation of test benches from cover statements."
> — YosysHQ documentation

> "Broadcom's Alderaan project... delivered to plan. Most RTL time was spent on feature-complete activity. Most verification time was spent on closure activity. The receive datapath was closed, but they didn't complete the bounded proof closure on the transmit datapath for various reasons, including difficulty in assessing complexity and determining which abstractions to apply."
> — Cadence Breakfast Bytes (Formal Signoff with JasperGold)

## 相关链接

- [rIC3: The rIC3 Hardware Model Checker](https://arxiv.org/html/2502.13605v1)
- [RTL-REPAIR: Fast Symbolic Repair of Hardware Design Code](https://dl.acm.org/doi/pdf/10.1145/3620666.3651346)
- [RTL Verification for Secure Speculation](https://arxiv.org/html/2407.12232v1)
- [Why is BMC/k-induction used in RTL formal verification?](https://electronics.stackexchange.com/questions/594846)
- [Yosys Formal Verification Documentation](https://yosys.readthedocs.io/)
- [SymbiYosys (sby) GitHub](https://github.com/YosysHQ/sby)
- [Cadence JasperGold Formal Verification](https://www.cadence.com/en_US/home/tools/system-design-and-verification/formal-verification.html)
- [Broadcom Formal Signoff Case Study](https://community.cadence.com/cadence_blogs_8/b/breakfast-bytes/posts/formal-signoffx)

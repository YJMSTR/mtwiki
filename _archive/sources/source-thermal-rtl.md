---
title: "RTL 与热仿真结合：从 Pre-RTL 架构级到 3D IC 热分析"
description: "搜集 RTL 仿真与热仿真结合的方法，重点包括 HotSpot 架构级热仿真器、Pre-RTL 热设计空间探索、3D IC 与微流道冷却的热仿真框架"
source_url: "https://arxiv.org/html/2403.20050v1"
source_type: "paper"
author: "Han et al. / Skadron et al. / Kaplan et al."
date: "2002-2024"
tags: ["thermal-simulation", "pre-rtl", "hotspot", "3d-ic", "microfluidic-cooling", "architecture-level", "temperature-aware"]
keywords: ["HotSpot", "thermal model", "pre-RTL thermal simulator", "3D IC thermal", "microfluidic cooling", "CoMeT", "Hot-LEGO", "compact thermal model", "RC thermal network", "temperature aware simulation"]
capture_date: "2026-07-02T01:14:46+0800"
---

# RTL 与热仿真结合：从 Pre-RTL 架构级到 3D IC 热分析

## 来源

- **URL**: https://arxiv.org/html/2403.20050v1
- **类型**: paper (ACM IGSC '23)
- **作者**: Jun-Han Han, Xinfei Guo, Kevin Skadron, Mircea R. Stan
- **日期**: 2023-10

- **URL**: https://www.bu.edu/peaclab/files/2017/06/kaplan_itherm17.pdf
- **类型**: paper (ITHERM 2017)
- **作者**: Fulya Kaplan, Sherief Reda, Ayse K. Coskun
- **日期**: 2017

- **URL**: https://github.com/uvahotspot/HotSpot
- **类型**: github
- **作者**: UVA HotSpot Team (Kevin Skadron, Mircea Stan, et al.)
- **日期**: 2002-2023

- **URL**: https://www.cse.iitd.ac.in/~srsarangi/files/papers/tempsurvey.pdf
- **类型**: paper (Survey)
- **作者**: IIT Delhi Thermal Simulator Survey
- **日期**:  ongoing

## 摘要

RTL 仿真器通常不直接建模温度，但温度对芯片性能、漏电功耗和可靠性有决定性影响。HotSpot 是目前最广泛使用的 **pre-RTL 架构级热仿真器**，它将 floorplan 和功耗 trace 转换为等效热阻-热容（RC）网络，通过求解热微分方程获得芯片温度分布。HotSpot 已与 gem5、McPAT、Sniper 等性能/功耗仿真器深度集成，形成从「架构仿真 → 功耗 trace → 热分布」的完整 toolchain。近年来，Hot-LEGO、CoMeT 等框架进一步将 HotSpot 扩展至 **3D IC 微流道冷却** 的 Pre-RTL 设计空间探索，实现了在 RTL 编码之前即可评估热约束下的架构决策。Cadence 的多物理场系统分析生态也将功耗估计、紧凑热模型（CTM）和系统级热分析在 RTL 阶段之前进行了对齐。

## 关键要点

- **HotSpot** 是一款开源的 pre-RTL 热仿真器，由 UVA 的 Kevin Skadron 等人于 2002 年提出，现已演进至 v7.0。它不需要门级或 RTL 电路细节，仅需 floorplan（各模块尺寸与位置）和功耗 trace，即可生成稳态（Steady-State）和瞬态（Transient）温度分布。
- **热建模原理**：HotSpot 将芯片堆叠结构离散化为 3D 网格，每个网格单元对应热 RC 网络中的一个节点，温度类比电压、热流类比电流、热阻类比电阻。求解方程为 `G·T(t) + C·T'(t) = U(t)`，其中 G 为热导矩阵，C 为热容矩阵，U 为功耗矩阵。
- **与 RTL/架构仿真的集成**：HotSpot 通常与 gem5（性能）、McPAT/CACTI（功耗面积）串联使用。gem5 生成架构级行为统计，McPAT 计算各模块功耗，HotSpot 读取功耗 trace 和 floorplan 输出温度分布。整个流程无需 RTL 代码，属于 Pre-RTL 探索。
- **Hot-LEGO 框架**：在 CoMeT 基础上扩展，支持微流道冷却（microfluidic cooling）的 3DIC 热仿真，可在 cache 级、ALU 级等细粒度进行热分析。相比传统风冷，微流道冷却可将核心层热点温度显著降低（见热图对比）。
- **3D IC 热仿真挑战**：3D 堆叠导致垂直方向热阻累积，下层 die 散热困难。HotSpot 3D 支持多层硅、TIM（Thermal Interface Material）、TSV 等结构的建模，输入包括每层物理尺寸、材料热导率、各 block 功耗分布。
- **紧凑热模型（CTM）精度**：Kaplan 等人的混合冷却模型（TEC + 微流道）在 HotSpot-6.0 上实现，与 COMSOL 多物理场仿真相比，TEC 模型平均误差 2.07°C，液冷模型平均误差 0.36°C，仿真速度提升 4 个数量级。
- **Cadence 早期热分析**：Cadence 的多物理场生态支持在架构定义阶段使用高阶功耗预算（无需完整 RTL activity vector）进行一阶热估计，识别热敏感区域，指导 block 划分和 die 分配。

## 对 RTL 仿真器多线程化的启示

1. **热-电联合仿真的并行化需求**：HotSpot 的 RC 求解（稳态用 SuperLU/迭代法，瞬态用 Runge-Kutta）与 RTL 仿真器是解耦的，但功耗 trace 的生成速率可能跟不上 RTL 仿真速度。多线程 RTL 仿真器若以高速率产生功耗数据，需要高效的 inter-process 通信或共享内存机制将 power trace 实时喂给热求解器。
2. **RTL 仿真内嵌紧凑热模型的可行性**：在 RTL 仿真器内部以粗粒度（如每个模块一个热节点）内嵌简化版 HotSpot 模型，可在功能验证的同时实时报告温度，用于动态热管理（DTM）策略验证。多线程 event-driven 仿真需要保证温度状态更新与逻辑事件的时间一致性。
3. **温度反标对漏电功耗的迭代影响**：温度升高 → 漏电功耗增加 → 总功耗增加 → 温度进一步升高。RTL 仿真器若要进行温度感知仿真，需要实现温度-功耗的迭代反馈环，这对多线程仿真的确定性 replay 提出了挑战（温度变化引入非线性反馈）。
4. **3D IC 与 Chiplet 仿真**：多线程 RTL 仿真器若用于 3D IC 或 Chiplet 的联合验证，需要支持跨 die 的功耗/温度数据交换。HotSpot v7.0 已支持 2D/2.5D/3D 和 Chiplet 配置，可作为外部热求解器与多线程 RTL 仿真器协同。

## 原文摘录

> "HotSpot is a pre-RTL thermal simulator intended for use early in the design process. HotSpot supports simulation of traditional 2D Integrated Circuits (2D ICs) and 3D ICs as well as microfluidic cooling."
> — HotSpot GitHub README

> "The inputs to the simulator are (i) the physical geometry of the chip stack, (ii) the floorplan of each layer, (iii) the thermal properties of the materials used in the layers, and (iv) the power dissipation of the blocks. Based on the input parameters, the simulator constructs a 3D RC network representation of the chip stack."
> — Kaplan et al., ITHERM 2017

> "Existing computer architecture simulators evaluate a design mainly on its power, performance, and area (PPA). For example, Gem5 is a performance simulator... For power simulators, CACTI and McPAT can be used to generate power traces. And for general thermal simulations, HotSpot provides fast and accurate thermal models. These simulators can be integrated together to provide an agile methodology for designers to explore design ideas in the Pre-RTL design phase."
> — Hot-LEGO, IGSC '23

> "The HotSpot compact thermal modeling approach is especially well suited for pre-register transfer level (RTL) and pre-synthesis thermal analysis."
> — Semantic Scholar, HotSpot Paper Summary

> "Thermal analysis must begin in parallel with the architectural definition itself. Early-stage compact models enable architects to approximate temperature distributions using only high-level power budgets, long before physical implementation."
> — Cadence Community Blog, Dec 2025

> "HotSpot takes the floorplan of the chip as input, which contains a description of the microarchitectural units, and their locations. It also takes the power dissipation of each of these units over a time step as input. Based on these values, it generates a thermal RC network."
> — A Survey of Chip Level Thermal Simulators, IIT Delhi

## 相关链接

- [Hot-LEGO: Architect Microfluidic Cooling Equipped 3DICs with Pre-RTL Thermal Simulation (arXiv)](https://arxiv.org/html/2403.20050v1)
- [HotSpot GitHub (v7.0)](https://github.com/uvahotspot/HotSpot)
- [Fast Thermal Modeling of Liquid, Thermoelectric, and Hybrid Cooling (BU)](https://www.bu.edu/peaclab/files/2017/06/kaplan_itherm17.pdf)
- [A Survey of Chip Level Thermal Simulators (IIT Delhi)](https://www.cse.iitd.ac.in/~srsarangi/files/papers/tempsurvey.pdf)
- [Cadence: Thermal Management in 3D-IC](https://community.cadence.com/cadence_blogs_8/b/corporate-news/posts/thermal-management-in-3d-ic-modeling-hotspots-materials-cooling-strategies)
- [Pre-RTL Voltage and Power Optimization (IEEE)](https://ieeexplore.ieee.org/document/8119277)

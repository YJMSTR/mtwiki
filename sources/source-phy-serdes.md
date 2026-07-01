---
title: Physical Layer / SerDes Simulation
description: 高速 SerDes 物理层仿真方法、IBIS-AMI 建模框架、通道仿真与均衡技术
source_url: "https://www.synopsys.com/designware-ip/technical-bulletin/modeling-integration-112g-phy-ip.html"
source_type: "doc"
author: "Synopsys"
date: "2020-07-20"
tags: ["SerDes", "PHY", "IBIS-AMI", "high-speed serial", "channel simulation", "equalization"]
keywords: ["SerDes RTL simulation", "PHY simulation", "high speed serial simulation", "IBIS-AMI simulation", "PAM-4", "112G"]
capture_date: "2025-07-02"
---

# 物理层 / SerDes 仿真与 IBIS-AMI 建模

## 来源

- URL: <https://www.synopsys.com/designware-ip/technical-bulletin/modeling-integration-112g-phy-ip.html>
- 类型: doc
- 作者: Synopsys
- 日期: 2020-07-20
- 补充: <https://www.mdpi.com/2079-9292/8/11/1233>
- 补充: <https://www.mathworks.com/discovery/serdes.html>
- 补充: <https://www.signalintegrityjournal.com/articles/2698-zero-cost-serdes-system-channel-simulation>
- 补充: <https://www.serdesdesign.com/home/statistical-model-development-for-high-speed-serdes/>

## 摘要

随着 400G/800G Ethernet 和 die-to-die 互联需求的激增，112G PAM-4 SerDes PHY 成为 HPC 和 AI 加速芯片的关键 IP。本文综合了 Synopsys 的 112G PHY 集成技术白皮书、PySerDes 开源框架、MATLAB SerDes Toolbox 文档以及 Signal Integrity Journal 的通道仿真实践，系统梳理了 SerDes 系统级仿真的核心方法：IBIS-AMI 建模框架、统计仿真与时域 bit-by-bit 仿真、通道 S 参数与均衡技术（FFE、CTLE、DFE、CDR），以及从 RTL 到系统级仿真的协同验证策略。

## 关键要点

- **IBIS-AMI 框架**：IBIS Algorithmic Modeling Interface 是业界标准 SerDes 建模方法，通过 `.ibs`（缓冲器特性）、`.ami`（算法参数）、`.dll/.so`（可执行模型）三文件组合，实现 Tx/Rx 在通道仿真器中的快速验证。
- **112G PAM-4 架构演进**：从传统模拟密集型架构转向 ADC + 灵活 DSP 架构（AFE → ADC → FFE/DFE/CDR/ADAPT），信号均衡大量后移至数字域，对仿真建模提出新挑战——需在 IBIS-AMI 中模拟连续时间的 DSP 均衡效果。
- **两种仿真模式**：
  - **统计仿真**（Statistical）：基于 LTI 假设，速度快，可下探任意低 BER，但不适用于含 CDR、自适应状态机的非线性时变系统。
  - **时域逐 bit 仿真**（Time-domain / Bit-by-bit）：支持 NLTV 模型，可捕捉非线性、自适应、抖动等动态效应，但速度较慢。
- **通道建模**：整个模拟通道（Tx IBIS → Tx Pkg → Channel → Rx Pkg → Rx IBIS）被视为 LTI 系统，通过单端冲激响应表征，支持 Touchstone S 参数格式。关键指标为插损（Insertion Loss）和 Nyquist 频率处的衰减。
- **均衡技术链**：
  - **Tx FFE**：发射端前馈均衡，预补偿通道损耗。
  - **Rx CTLE**：连续时间线性均衡器，补偿高频衰减。
  - **Rx DFE**：判决反馈均衡器，消除码间干扰（ISI）。
  - **CDR**：时钟数据恢复，基于 PLL 或数字相位/频率锁定环。
- **通道仿真器生态**：Keysight ADS ChannelSim、Cadence Sigrity SystemSI、Synopsys 方案、SerDesDesign.com 云工具等，均支持 IBIS-AMI 标准兼容模型。
- **眼图与浴盆曲线**：核心验证指标，通过大量 bit 的叠加形成眼图开口，评估抖动容限和噪声裕量；浴盆曲线（Bathtub Curve）描述 BER 随采样相位变化的分布。

## 对 RTL 仿真器多线程化的启示

1. **混合抽象层级**：SerDes 仿真天然是多层抽象共存的典型——晶体管级（AFE、均衡器电路）、行为级（IBIS-AMI 模型）、RTL 级（DSP 数字逻辑、CDR 状态机）、系统级（通道 S 参数）。RTL 多线程仿真器可作为数字域的核心引擎，与 IBIS-AMI 可执行模型通过 DPI/VPI 接口交互，实现数模混合的高速串行链路验证。
2. **大量 bit 的并行处理**：通道仿真需要在数百万 bit 上统计眼图。RTL 多线程化可通过向量化/批量化激励生成，在多个线程上同时推进不同数据模式的仿真，最后聚合统计眼图——这与 Verilator 的批量仿真（batch simulation）思路一致。
3. **均衡算法的 RTL 验证**：112G SerDes 中大量均衡功能（FFE、DFE、CDR）以数字逻辑实现。多线程 RTL 仿真器可高效验证这些 DSP 模块的功能正确性和收敛速度，而模拟前端（AFE、ADC）则通过 IBIS-AMI 或 Verilog-AMS 行为模型提供激励。
4. **自适应算法的收敛测试**：CDR 和自适应均衡器包含反馈环路，其收敛特性需要大量仿真周期验证。多线程 RTL 仿真可通过并行运行不同初始条件和 PVT 角点的仿真，加速自适应算法的覆盖率收敛。
5. **IBIS-AMI 的 DPI 封装**：IBIS-AMI 模型以 C/C++ DLL 形式提供。RTL 仿真器可通过 SystemVerilog DPI-C 接口调用这些模型，实现数字 RTL 与模拟通道模型的联合仿真。多线程环境下需注意 DPI 调用的线程安全性——要么将 AMI 调用序列化为单线程，要么为每个线程维护独立的 AMI 模型实例。

## 原文摘录

> "The IBIS-AMI modeling and simulation framework has enabled system and hardware engineers to verify off-chip interconnect designs by running simulations in an accurate yet efficient manner."

> "Today’s PAM-4 112G PHY uses ADC-based flexible DSP architecture instead of a PVT-dependent and hard-to-scale analog architecture. This architectural shift has significant implications on simulation and modeling of high-speed SerDes transceivers."

> "IBIS-AMI defines two approaches to SerDes modeling and simulation flow: time domain or bit-by-bit simulation for nonlinear and/or time variant (NLTV) model and statistical simulation for linear and time invariant (LTI) model."

> "A key channel simulator property to keep in mind is that it considers that the entire analog content ... is linear and time invariant (LTI). As an LTI system, the entire differential analog section in the SerDes system is accurately represented by its single ended impulse response."

> "PySerDes provides a series of container libraries that can be flexibly integrated into the open source scientific computing eco-system and potentially supporting many SerDes system modeling experiments and analyses."

## 相关链接

- [Accurate Modeling and Integration for 112G SerDes PHY IP - Synopsys](https://www.synopsys.com/designware-ip/technical-bulletin/modeling-integration-112g-phy-ip.html)
- [System Level Optimization for High-Speed SerDes - MDPI](https://www.mdpi.com/2079-9292/8/11/1233)
- [What Is a SerDes? - MATLAB & Simulink](https://www.mathworks.com/discovery/serdes.html)
- [Zero Cost SerDes System Channel Simulation - Signal Integrity Journal](https://www.signalintegrityjournal.com/articles/2698-zero-cost-serdes-system-channel-simulation)
- [Statistical Model Development for High Speed SerDes - SerDesDesign](https://www.serdesdesign.com/home/statistical-model-development-for-high-speed-serdes/)
- [An End-to-End Design and Simulation Methodology for PCIe Channels - MDPI](https://www.mdpi.com/2072-666X/17/2/218)

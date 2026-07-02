---
title: "云EDA与SaaS仿真：从Synopsys Cloud到Azure弹性计算的产业迁移"
description: 搜集主流云厂商（AWS、Azure、Google Cloud）及EDA三巨头（Synopsys、Cadence、Siemens）的云原生EDA部署方案，涵盖SaaS模式、弹性计算与数据中心混合架构。
source_url: "https://www.embedded.com/chip-design-in-the-cloud-now-you-can-have-pay-as-you-go-eda/"
source_type: "blog"
author: "Synopsys / Microsoft / Rescale / SemiAnalysis"
date: "2022-2026"
tags: ["cloud-eda", "saas-simulation", "azure-eda", "aws-eda", "flexeda", "burst-compute"]
keywords: ["Synopsys Cloud", "FlexEDA", "Cadence Cloud", "Rescale", "Azure HBv3", "cloud RTL simulation", "SaaS EDA"]
capture_date: "2026-07-08"
---

# 云EDA与SaaS仿真：产业云化全景

## 来源

- URL: [Synopsys Cloud 官宣 — Embedded.com](https://www.embedded.com/chip-design-in-the-cloud-now-you-can-have-pay-as-you-go-eda/)
- URL: [FlexEDA 五大变革 — Synopsys Blog](https://www.synopsys.com/blogs/chip-design/5-ways-flexeda-saas-model-transforms-chip-design.html)
- URL: [Azure Connected Cloud + Pure Storage — Microsoft TechCommunity](https://techcommunity.microsoft.com/blog/azurehighperformancecomputingblog/connected-cloud-architecture-for-eda-workloads-in-azure-at-scale-with-data-secur/3025153)
- URL: [Rescale EDA Cloud PAAS — SemiWiki](https://semiwiki.com/forum/threads/eda-cloud-ramifications.12737/)
- URL: [The EDA Primer — SemiAnalysis Newsletter](https://newsletter.semianalysis.com/p/the-eda-primer-from-rtl-to-silicon)
- 类型: blog / doc / 产业分析
- 作者: Synopsys VP Sandeep Mehndiratta, Microsoft Azure HPC Team, SemiAnalysis, Rescale
- 日期: 2020-2026

## 摘要

半导体行业正经历从本地数据中心到公有云的历史性迁移。Synopsys 于 2022 年推出 **Synopsys Cloud**——业界首个大规模云 SaaS EDA 解决方案，基于 Microsoft Azure 构建，支持按分钟计费的 **FlexEDA** 模式。与此同时，Cadence Cloud、Siemens Cloud Solutions 以及第三方平台（Rescale）纷纷入局。Azure 与 Pure Storage 合作验证了 "Connected Cloud" 架构：FlashBlade 存储设备部署于 Equinix 共置数据中心，通过 ExpressRoute 连接 Azure VM，实现计算弹性扩展与数据主权的平衡。SemiAnalysis 指出，现代 SoC 验证回归一次可消耗数千 CPU core-hours，本地专用验证服务器已捉襟见肘，云仿真成为 Tapeout 前的关键缓冲。

## 关键要点

- **Synopsys Cloud 架构**：基于 Azure 的 SaaS 平台，支持 BYOC（Bring Your Own Cloud）模式；通过专利待审的计量技术实现「无限按需 EDA 工具可用性」，无需修改 EDA 软件代码本身。
- **FlexEDA 计费模式**：按小时/分钟计费，RTL/Gate-level 仿真（VCS）和库特征化（Library Characterization）均支持细粒度计量；无需预先承诺许可证数量或计算资源。
- **Azure Connected Cloud 方案**：Pure Storage FlashBlade 部署在 Equinix 数据中心，与 Azure 通过 10Gbps ExpressRoute 互联；EDA 前后端工作负载（高元数据 IOPS + 高带宽）经 SPECstorage2020 EDA_BLENDED 验证，延迟稳定在 2ms 以内，IOPS 随 VM 数量线性扩展。
- **Rescale PAAS 中立平台**：整合 Cadence、Synopsys、Siemens 等主流 EDA 工具，采用「自带许可证」（BYOL）模式；新用户从注册到启动作业通常不到一小时；Samsung SAFE CDP 上云后 TTM 提升 30%。
- **市场驱动力**：SemiAnalysis 强调，复杂 SoC 的一次完整回归套件（tens of thousands of test cases）需消耗数千 CPU core-hours，云仿真可在 Tapeout  crunch period 提供 burst capacity；单芯片数据量可达多 PB。
- **云优化计算选型**：Azure E96as_v4（AMD EPYC 7452, 96 vCPUs, 672GiB）等实例经 Synopsys 测试，针对仿真、综合、物理验证等不同 EDA 负载预优化。

## 对 RTL 仿真器多线程化的启示

1. **云原生环境 = 多线程化的理想试验场**：云实例的 vCPU 数量远高于本地工作站（96 vCPU 起步），RTL 仿真器的多线程化收益在云上会被急剧放大。如果一个 32-thread 的优化能将单机仿真时间从 4 小时压缩到 1 小时，在云 burst 场景下意味着成本直接下降 75%。
2. **FlexEDA 的分钟级计费倒逼性能优化**：Synopsys Cloud 按分钟计费，仿真器每多榨取一倍的并行效率，用户的直接支出就少一半。这构成了一个极其强烈的外部激励，推动 EDA 厂商在仿真内核中引入更激进的多线程/多进程策略。
3. **Connected Cloud 架构提示 IO 瓶颈**：Azure + FlashBlade 测试显示 EDA 负载是「高元数据 IOPS + 高带宽」的混合体。多线程仿真器如果设计不当，多个线程同时访问 UVM 测试平台文件或波形数据库（FSDB），可能导致元数据 IO 争用。多线程架构需要与云存储的 NFS 挂载选项（如 `nconnect`, `rsize/wsize`）协同调优。
4. **Burst 模式与回归测试的并行度**：Rescale 描述的场景——20,000 个验证作业各需 1 核时，全部并行可在 1 小时内完成——前提是仿真器本身具备足够好的多线程/多进程扩展性。否则，即使云提供了无限核数，仿真器也会成为阿喀琉斯之踵。
5. **SaaS 标准化倒逼接口统一**：当 EDA 工具以 SaaS 形式交付时，用户期望统一的 API/CLI 来触发仿真。多线程 RTL 仿真器如果暴露为云原生微服务（Docker 容器 + REST API），则更易融入自动化回归流水线。

## 原文摘录

> "On-premise cloud, where an organization hosts its own data center infrastructure, does come with challenges in terms of limited compute capacity as well as access to the most advanced compute resources. This model also doesn't address license management challenges. Tool flows are complicated, encompassing licensing and legal agreements that often involve different vendors with different tool use specifications. Also, there are a fixed number of licenses available, and license servers represent single points of failure."
> — Sandeep Mehndiratta, VP of Synopsys Cloud Solutions

> "The core promise of the FlexEDA model is unlimited EDA license availability with pay-per-use on an hourly or per-minute basis. Chip designers design, schedule, and run a specific EDA job based on where they are in the design cycle and their PPA goals. Synopsys Cloud can automatically scale the EDA software based on the elastic cloud scale infrastructure enabled by the designer for this specific job."
> — Synopsys FlexEDA 官宣

> "Dedicated on-prem verification servers are usually insufficient these days, with cloud-based simulation on AWS and Azure shoring up short-term demand as teams try to burst capacity during crunch periods before tapeout. The amount of data this generates is also staggering, with multiple Petabytes of disk space required to house just a single chip's entire definition and test items."
> — SemiAnalysis, The EDA Primer

> "For example, if you needed to run 20,000 verification jobs that take an hour each on one core, you could do all 20,000 at once in the cloud with flexible on-demand style licenses, reducing your run time to just one hour. This kind of flexibility would allow companies to leverage additional parallelism when needed."
> — Rescale / SemiWiki EDA Cloud Ramifications

> "The test results validate the performance of FlashBlade in Equinix over the ExpressRoute link. For the EDA workloads, E96as_v4 Azure VM with ultra-performance gateway and 10Gbps ExpressRoute connection to FlashBlade scales the IOPs linearly and consistently under 2ms."
> — Microsoft Azure HPC Blog

## 相关链接

- [Synopsys Cloud 官方页面](https://www.synopsys.com/cloud.html)
- [Cadence Cloud Solutions](https://www.cadence.com/en_US/home/solutions/cadence-cloud.html)
- [Rescale EDA Platform](https://rescale.com/)
- [Azure HBv3 Series (AMD EPYC with 3D V-Cache)](https://learn.microsoft.com/en-us/azure/virtual-machines/hbv3-series)
- [ChipXpert: Cloud-Based VLSI Design Tools in 2025](https://chipxpert.in/cloud-based-vlsi-design-tools-chip-design-in-2025/)

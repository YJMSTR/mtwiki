---
title: Bus Functional Model (BFM) 与 Verification IP (VIP) — 验证方法学、性能优化与协同仿真
description: 系统梳理 BFM 与 VIP 的定义、分类、UVM 集成方法，以及 Veloce 硬件仿真加速中的 VIP 性能优化实践。分析多线程 RTL 仿真器在 BFM/VIP 层的高效调度策略。
source_url: "https://www.maven-silicon.com/blog/soc-verification-flow-and-methodologies/"
source_type: "blog"
author: "Maven Silicon, Aldec, Cadence, E. Kokkonen (Tampere University), R. Wang (DVCon)"
date: "2021-2022"
tags: ["BFM", "VIP", "UVM", "Verification-IP", "Simulation-Acceleration", "Co-emulation", "SCE-MI", "RTL"]
keywords: ["Bus Functional Model", "Verification IP", "UVM VIP", "simulation acceleration", "Veloce", "SCE-MI", "Transactor", "Monitor", "Speed Adapter"]
capture_date: "2026-07-02"
---

# Bus Functional Model (BFM) 与 Verification IP (VIP) — 验证方法学、性能优化与协同仿真

## 来源

- **URL**: https://www.maven-silicon.com/blog/soc-verification-flow-and-methodologies/
- **URL**: https://www.aldec.com/en/solutions/hardware_emulation_solutions/verification_ip
- **URL**: https://trepo.tuni.fi/bitstream/10024/125270/2/KokkonenEetu.pdf
- **URL**: https://dvcon-proceedings.org/wp-content/uploads/wrapping-verilog-bus-functional-model-bfm-and-rtl-as-drivers-in-customized-uvm-vip-using-abstract-classes-poster.pdf
- **URL**: https://www.cadence.com/en_US/home/tools/system-design-and-verification/verification-ip/simulation-vip/amba/amba-axi.html
- **类型**: blog / paper / doc
- **作者**: Maven Silicon, Aldec, Eetu Kokkonen (Tampere University), R. Wang (DVCon), Cadence
- **日期**: 2021-2022

## 摘要

在 SoC 验证流程中，**Bus Functional Model (BFM)** 与 **Verification IP (VIP)** 是连接测试平台（Testbench）与被测设计（DUT）的桥梁。VIP 是一种特殊的 IP Core，它融合了 BFM 的接口协议建模能力和 Test Harness 的测试激励功能。根据用途，VIP 可分为 **Transactor**（双向通信）、**Monitor**（只读监控）和 **Speed Adapter**（速度适配）三类。在 UVM 验证方法学中，AXI/AHB/APB/GPIO/UART/SPI/I2C 等接口的 VIP/UVC 被配置并连接到对应接口，配合参考模型（Reference Model）、记分板（Scoreboard）和 UVM RAL 构建自检查验证环境。随着设计规模增长，纯仿真效率急剧下降，硬件仿真加速（Veloce/Palladium/ZeBu）成为关键路径。研究表明，针对仿真加速优化的 VIP 可将运行时间从纯仿真的数十分钟压缩到加速模式的数秒，最高实现约 **40 倍**加速比。

## 关键要点

- **BFM 与 VIP 的定义关系**：
  - **BFM (Bus Functional Model)**：对特定接口总线功能的行为级模型，负责将高级事务（如"写 4 字节到地址 0x1000"）转换为符合协议的信号级时序（如 AXI 的 AWVALID/AWADDR/WVALID/WDATA 握手序列）。
  - **VIP (Verification IP)** = BFM + Test Harness。它不仅建模协议，还提供测试激励生成、错误注入、覆盖率收集等功能。

- **VIP 的三大分类（Aldec 定义）**：
  - **Transactors**：建立软件测试平台（HDL Simulator、Virtual Platform）与 DUT 之间的通信通道。通过高级消息（high-level messages）与 BFM 交互，BFM 负责将消息翻译为标准接口信号。支持总线传输注入和错误注入。
  - **Monitors**：与 Transactor 类似，但只具备监控/只读能力。BFM 捕获标准接口信号并翻译为高级消息，供测试平台分析或调试。
  - **Speed Adapters**：用于将硬件仿真器（emulator）中的设计与外部真实设备连接。主要功能是将仿真时钟域与真实设备（通常时钟速率更高）同步，在协议层实现正确同步。

- **UVM 验证环境中的 VIP 集成（Maven Silicon）**：
  - **IP 级验证**：采用白盒验证，使用 SystemVerilog UVM Testbench 进行穷尽随机仿真，生成功能、断言和代码覆盖率。需要 HVL 编程、Formal/Dynamic ABV、仿真调试和 VIP/EDA 工具的专业知识。
  - **子系统级验证**：采用灰盒验证，将预验证的 IP 与桥接器、系统控制器通过 AMBA 总线集成。配置 AXI、AHB、APB、GPIO、UART、SPI、I2C 等 VIP UVC，配合参考模型、记分板和 UVM RAL 实现自检查。在顶层执行 VIP UVM 序列，验证数据流并测量总线性能。
  - **SoC 级验证**：采用黑盒验证，使用硬件仿真或仿真技术。SoC Testbench 包含标准 UVM VIP（USB/Bluetooth/WiFi）、传统 HDL BFM 的 UVM Wrapper、自定义 UVM Agent（Firmware Agent）和 SystemC/C/C++ 功能模型。ARM 处理器 RTL 通常替换为 DSM（Design Simulation Model），用 C 编写的 firmware 作为激励驱动所有外设 RTL。

- **VIP 在仿真加速中的性能优化（Kokkonen 硕士论文，2021）**：
  - **研究背景**：Nokia SoC 部门需要优化现有 AXI-Stream VIP 以提升 Veloce 硬件仿真加速的运行性能。
  - **纯仿真 vs 加速对比**：Wisniewski 等人报告加速比约 **170 倍**（纯仿真 75 分钟 → 加速 27 秒）。Jain 等人使用 UVM 环境，小 DUT（~5M 门）加速比 **30 倍**（657 秒 → 21 秒），大 DUT（~9.5M 门）加速比 **40 倍**（2044 秒 → 50 秒）。
  - **优化策略**：
    1. **降低通信频率**：减少测试平台与 HDL 域之间的通信次数。
    2. **增加单次传输数据量**：通过批量传输减少通信 overhead。
  - **优化效果**：初始 VIP 在加速模式下已比纯仿真快 10-20 倍；优化后，最长测试用例的运行时间再减半，相比纯仿真实现近 **40 倍**加速。
  - **编码规范**：为 Veloce 仿真加速编写了一系列编码指南，帮助将传统 UVM 测试环境转换为适合加速的形式。

- **BFM 与 UVM 的抽象类封装（DVCon, R. Wang）**：
  - 在 SoC 级验证中，将 IP 级 UVM 序列和自定义 VIP 重用，用 dummy stub 替换 Master IP RTL，通过抽象类将 Verilog BFM 和 RTL 包装为 UVM 中的驱动器（Driver）。
  - 这种方法解决了不同接口（如 AXI-Full 和 AXI-Lite）中同名类型（如 `t_xresp`）的命名冲突问题，通过完整包名限定（`uvvm_util_axi_bfm_pkg.t_xresp`）实现多 BFMs 共存。

- **Cadence VIP 的标准化支持**：
  - 提供完整的 AXI BFM + 自动协议检查 + 覆盖率模型。
  - 支持所有主流仿真器，兼容 SystemVerilog 和 `e` 语言，遵循 UVM 和 OVM 方法学。
  - 支持 AMBA 3/4/5 AXI、AXI-Lite、CHI 等多种协议规范。

- **SCE-MI 标准的重要性**：
  - Aldec 的 VIP 严格遵循 Accellera SCE-MI 标准，确保 Transactor 和 Monitor 可在纯仿真和硬件仿真两种模式下复用。
  - SCE-MI 定义了软件测试平台与硬件仿真器之间的标准化消息传递接口，是 VIP 跨平台复用的基石。

## 对 RTL 仿真器多线程化的启示

1. **BFM 的事务层与信号层分离**：BFM 天然分为两层——上层处理高级事务（如 AXI 事务对象），下层处理信号级时序（如时钟周期精度的握手）。多线程 RTL 仿真器可将事务层放在独立线程中预生成和排队，信号层线程按需从队列取事务并驱动信号。这种"事务流水线"大幅减少线程间同步开销。

2. **VIP 通信优化的线程级映射**：Kokkonen 论文中提到的"降低通信频率、增加数据量"策略，在多线程仿真器中可直接映射为：减少主仿真线程与 VIP 线程之间的 IPC 次数，改用大消息块（batch）通过无锁队列传递。VIP 线程本地缓存事务批量，一次性注入到 DUT 的接口线程。

3. **Monitor 的只读观察者模式**：Monitor VIP 不驱动信号，只读取和翻译。多线程仿真器中，Monitor 可作为纯观察者线程附加到共享信号状态（通过 atomic/lock-free 读取）。由于不修改状态，无需获取写锁，可实现真正的零干扰监控，多个 Monitor 可同时观察同一接口而不竞争。

4. **UVM Scoreboard 的并行检查**：Scoreboard 需要比对 DUT 输出与参考模型预期。多线程架构可将不同接口的 Scoreboard 检查分配到独立线程，每个线程维护本地预期队列和实际队列，独立执行比对。全局覆盖率收集可通过原子计数器合并各线程结果。

5. **SCE-MI 风格的跨域消息传递**：多线程 RTL 仿真器可借鉴 SCE-MI 的设计哲学，将软件线程（VIP/测试平台）与硬件线程（DUT 仿真引擎）通过消息队列严格解耦。软件线程以事务粒度工作，硬件线程以事件粒度工作，两者之间通过生产者-消费者模型桥接，这是多线程 RTL 仿真器实现"软件友好"接口的关键。

6. **形式验证与动态仿真的混合线程**：Formal 工具（JasperGold、VC Formal）与动态仿真器可在多线程架构中 coexist。Formal 引擎在后台线程执行属性证明，动态仿真主线程推进具体场景。两者可共享状态空间的部分结果，实现 hybrid verification。

## 原文摘录

> "Verification IP (VIP) is a special kind of IP Core that combines function of Bus Functional Model (BFM) of a given interface with Test Harness features for use in the testbench."
> — Aldec, Verification IP Solutions

> "Transactors are modules that establish communication channel between software part of testbench and the design. The testbench can inject bus transfers or respond to transfer requests using transactor."
> — Aldec

> "The run time of simulation acceleration with the initial VIP was approximately ten to twentyfold shorter when compared to the pure simulation with it. The optimized VIP was able to decrease the simulation acceleration run time almost to half of the initial VIP's run time with the longest test case. This means almost fortyfold reduction when compared to the pure simulation."
> — E. Kokkonen, AXI-Stream VIP Optimization for Simulation Acceleration (Tampere University, 2021)

> "All the VIPs like AXI, AHB, APB, GPIO, UART, SPI, and I2C UVCs will be configured and connected with the respective interfaces. We create other TB components like reference models, scoreboards, and UVM RAL for making the verification environment self-checking. We execute various VIP UVM sequences at the top level, verify the data flow, and measure the performance of the bus."
> — Maven Silicon, SoC Verification Flow and Methodologies

> "We reuse the IP level UVM sequences and customized UVM VIP on the SoC level, replace the master IP RTL with dummy stub in the Verilog file list, and execute..."
> — R. Wang, Wrapping Verilog BFM and RTL as Drivers in Customized UVM VIP (DVCon)

> "Very important factor that should be considered when choosing or developing VIP is their reuse in emulation as simulation becomes inefficient when the design grows. For this reason well designed VIP should be based on co-emulation industry standard, namely the Accellera's SCE-MI."
> — Aldec

## 相关链接

- [Maven Silicon: SoC Verification Flow and Methodologies](https://www.maven-silicon.com/blog/soc-verification-flow-and-methodologies/)
- [Aldec: Verification IP Solutions](https://www.aldec.com/en/solutions/hardware_emulation_solutions/verification_ip)
- [Kokkonen 硕士论文: AXI-Stream VIP Optimization for Simulation Acceleration](https://trepo.tuni.fi/bitstream/10024/125270/2/KokkonenEetu.pdf)
- [DVCon: Wrapping Verilog BFM in UVM VIP](https://dvcon-proceedings.org/wp-content/uploads/wrapping-verilog-bus-functional-model-bfm-and-rtl-as-drivers-in-customized-uvm-vip-using-abstract-classes-poster.pdf)
- [Cadence AXI VIP](https://www.cadence.com/en_US/home/tools/system-design-and-verification/verification-ip/simulation-vip/amba/amba-axi.html)
- [UVVM Forum: AXI BFM & AXILite BFM 共存问题](https://forum.uvvm.org/t/axi-bfm-and-axilite-bfm-usage-error-at-the-same-time/265)
- [Accellera SCE-MI 标准](https://accellera.org/community/standards/systemc-emulation)

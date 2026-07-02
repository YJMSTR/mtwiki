---
title: TLM-2.0 / Mixed Abstraction Simulation with RTL
description: TLM-2.0 与 RTL 混合仿真、transactor 桥接、RTL-to-TLM 自动抽象、性能对比与工业实践文献汇总
source_url: "https://dvcon-proceedings.org/wp-content/uploads/bridging-the-gap-between-tlm-2-0-at-models-and-rtl-experiments-and-opportunities.pdf"
source_type: "paper"  # github-pr, github-issue, blog, doc, paper, competition
author: "Multiple (Intel, Bombieri et al., Zhou et al., etc.)"
date: "2011-2024"
tags: ["TLM-2.0", "RTL", "mixed-abstraction", "co-simulation", "transactor", "RTL-to-TLM", "virtual-prototype"]
keywords: ["TLM-2.0 RTL bridge", "mixed abstraction simulation", "transaction level RTL co-simulation", "TLM RTL adapter", "virtual prototype RTL"]
capture_date: "2026-07-03"
---

# TLM-2.0 / RTL 混合抽象仿真

## 来源

- **URL**: https://dvcon-proceedings.org/wp-content/uploads/bridging-the-gap-between-tlm-2-0-at-models-and-rtl-experiments-and-opportunities.pdf
- **类型**: paper (DVCon)
- **作者**: Zhu Zhou, Atul Kwatra, Rajesh Gadiyar, Paul Heraty (Intel)
- **日期**: 2013
- ---
- **URL**: https://dl.acm.org/doi/10.1109/ETS.2011.58
- **类型**: paper (IEEE ETS)
- **作者**: N. Bombieri, F. Fummi, V. Guarnieri, W. Rosenstiel, E. Macii
- **日期**: 2011
- ---
- **URL**: https://www.eetimes.com/defining-the-tlm-to-rtl-design-flow/
- **类型**: blog
- **作者**: EE Times
- **日期**: 2010
- ---
- **URL**: https://www.cnblogs.com/sys-123456/p/18226270
- **类型**: blog
- **作者**: 匿名 (中文技术博客)
- **日期**: 2024-06-03
- ---
- **URL**: https://www.researchgate.net/publication/288492733_On_RTL_to_TLM_Abstraction_to_Benefit_Simulation_Performance_and_Modeling_Productivity_in_NoC_Design_Exploration
- **类型**: paper
- **作者**: 多位作者
- **日期**: 2015
- ---
- **URL**: https://www.dbpia.co.kr/Journal/articleDetail?nodeId=NODE01599630
- **类型**: paper
- **作者**: 韩国研究团队
- **日期**: 2015

## 摘要

TLM-2.0 与 RTL 的混合仿真（Mixed Abstraction Simulation）是现代 SoC 验证平台的核心技术。工业界的主流做法是：**TLM 层作为系统级 golden reference 和性能模型**，在 RTL 实现阶段复用同一套 SystemC 测试平台，通过 **transactor** 将高层事务（`tlm_generic_payload`）翻译为 RTL 信号级波形。Intel 的 DVCon 论文展示了这种架构：同一 traffic generator 同时驱动 TLM 路径和 RTL 路径，通过性能对比模块检测差异。另一方面，RTL-to-TLM 自动抽象技术（如 FAST 框架）可以将已有 RTL IP 抽象为 TLM 模型，获得 **10×–1000×** 的仿真加速，同时保持行为与功耗误差低于 10%。

## 关键要点

- **Transactor 是 TLM-RTL 边界的翻译官**：它负责将 `tlm_generic_payload` 的读写请求转换为 pin-level 信号序列（如 AXI 的 AR/AW/R/W/B 通道），反之亦然。SystemC 与商业 RTL 仿真器的混仿通常依赖 SystemC wrapper 或 DPI/PLI 接口。
- **性能断崖式下降**：纯 TLM-2.0 平台在 OSCI 仿真器上可达 **50,000 transactions/sec**；一旦接入 RTL DUT 通过商业仿真器混仿，速度骤降至 **64 transactions/sec**（Intel 实测）。这是跨抽象层仿真的最大痛点。
- **RTL-to-TLM 抽象方法论**：从可综合 RTL 提取时序与功耗状态机，生成时间-功耗注释的 TLM 模型。NoC 论文报告 **10–1000× 加速**，功耗相对误差 < 10%。FAST 框架通过结构信息自动注入故障模型，在 TLM 层快速生成测试向量，再合成回 RTL 层。
- **并行 TLM-RTL 调试**：为了根因分析 TLM 与 RTL 之间的性能差异，Intel 将同一测试平台实例化两次，分别驱动 TLM 模型和 RTL DUT，通过 TLM-2.0 analysis ports 导出性能数据到 correlation module 进行差异检测。
- **时间解耦（Temporal Decoupling）是关键**：TLM 的 Loosely-Timed 编码风格允许 initiator 在本地时间中跑在前面，减少与全局仿真时间的同步频率。这与 RTL 的 cycle-accurate 推进形成天然矛盾，需要在 transactor 中定期同步。
- **HLS 作为桥梁**：理想的设计流是从高层描述生成 TLM-2.0 AT 模型 + 可综合 RTL，确保两者同源。但现有工具多生成 cycle-accurate SystemC，需要额外 transactor 才能插入 TLM 平台。

## 对 RTL 仿真器多线程化的启示

1. **TLM 层的多线程推进与 RTL 层的 cycle 精确推进可以在混合平台中共存**：TLM 部分用 temporal decoupling 在多个线程上跑，RTL 部分用精确的 delta-cycle 推进，两者通过 transactor 的 quantum 边界同步。这为 RTL 多线程引擎提供了"分层并行"的架构范式。
2. **Transactor 的翻译开销是混合仿真瓶颈**：如果 RTL 引擎本身是多线程的，transactor 可以嵌入在 RTL 线程的 evaluate 阶段，减少跨进程通信。未来设计应考虑将 TLM socket 直接绑定到 RTL 模块的 SystemC wrapper 端口上，而非通过外部 DPI 调用。
3. **RTL-to-TLM 抽象加速比证明：降低精度可以换取数量级的速度提升**。这暗示 RTL 多线程引擎可以在"快速功能模式"（减少内部 timing 检查）和"精确验证模式"之间切换，根据验证阶段动态调整抽象层级。
4. **分析端口（analysis port）与性能监控模块的架构值得借鉴**：在 RTL 多线程仿真中，可以设计无锁的 performance probe 通道，让每个线程周期性地导出 latency/throughput 数据到全局监控器，而不阻塞仿真推进。

## 原文摘录

> "One main reason of moving to higher abstraction levels is to achieve several magnitudes higher simulation speed. With that, extensive architectural exploration can be conducted within a reasonable time frame. Table 1 shows the speed difference between pure SystemC simulation and SystemC/RTL mixed simulation."
> — Intel DVCon, *Bridging the gap between TLM-2.0 AT models and RTL*

> | Platform | Simulator | Speed (transactions/second) |
> |----------|-----------|----------------------------|
> | Pure TLM-2.0 | OSCI simulator | 50,000 |
> | Mixed TLM-2.0/RTL | Commercial RTL simulator | 64 |

> "Transaction-level modeling (TLM) allows a simulation speed-up up to 1000x with respect to RTL. This paper presents a methodology to accelerate RTL fault simulation through automatic RTL-to-TLM abstraction."
> — Bombieri et al., *Accelerating RTL Fault Simulation through RTL-to-TLM Abstraction* (IEEE ETS 2011)

> "The proposed techniques allow the integration of existing RTL IP components into virtual platforms for early software development and platform design, configuration, and exploration. With the proposed approach, IP models can be natively integrated into SystemC TLM-2.0 platforms and executed 10-1000 times faster compared to state-of-the-art RTL simulators."
> — NoC Design Exploration, *On RTL to TLM Abstraction*

> "RTL is about abstraction structure logic and timing in contrast TLM is all about the abstraction of communication... The key point about transaction level modeling is that it accelerates simulation so comparing RTL side-by-side RTL models communicate by wiggling pins over a period of time. transaction level models communication with simple function calls and that makes transaction models more faster than RTL of simulation."
> — 中文技术博客, *RTL vs TLM and AT vs LT in SystemC*

> "TLM + RTL flow is an emerging design method... Not all modules will have sufficiently accurate high-level models but only RTL representations. To maintain the speed of a virtual prototype, emulation technology linked to a virtual prototype is required to maintain the required speed."
> — EE Times, *Defining the TLM-to-RTL Design Flow*

## TLM-2.0 / RTL 混合仿真代码示例

### 1. Loosely-Timed 编码风格（blocking transport）

```cpp
void do_transaction() {
  tlm_generic_payload trans;
  trans.set_command(TLM_WRITE_COMMAND);
  trans.set_address(MPEG_ENCODE_ADDR);
  trans.set_data_ptr(reinterpret_cast<unsigned char*>(&data));
  trans.set_data_length(4);

  sc_time delay = SC_ZERO_TIME;
  // 阻塞传输：整个事务在一个函数调用中完成
  // initiator 可以在此跑 ahead，直到 quantum 边界才同步
  out_socket->b_transport(trans, delay);

  if (trans.is_response_error())
    SC_REPORT_ERROR("TLM", "Response error");
}
```

### 2. Approximately-Timed 编码风格（non-blocking transport，多阶段）

```cpp
void start_transaction() {
  tlm_generic_payload* trans = new tlm_generic_payload;
  trans->set_command(TLM_WRITE_COMMAND);
  trans->set_address(MPEG_ENCODE_ADDR);
  trans->set_data_ptr(data_ptr);

  sc_time delay = SC_ZERO_TIME;
  tlm_phase phase = BEGIN_REQ;
  tlm_sync_enum status;

  // 非阻塞前向传输：启动请求阶段
  status = out_socket->nb_transport_fw(*trans, phase, delay);

  if (status == TLM_UPDATED) {
    // 目标返回更新后的 phase，可能需要继续握手
  } else if (status == TLM_ACCEPTED) {
    // 目标将在后续回调中通知（如 END_REQ / BEGIN_RESP）
  }
}

// 目标回调（反向路径）
tlm_sync_enum nb_transport_bw(tlm_generic_payload& trans,
                               tlm_phase& phase, sc_time& delay) {
  if (phase == BEGIN_RESP) {
    // 响应到达，事务完成
    return TLM_COMPLETED;
  }
  return TLM_ACCEPTED;
}
```

### 3. Transactor 将 TLM 事务翻译为 RTL 信号（简化版）

```cpp
SC_MODULE(axi_transactor) {
  tlm_target_socket<32, tlm_generic_payload> target_socket;
  sc_out<bool> awvalid;
  sc_out<sc_uint<32>> awaddr;
  sc_in<bool> awready;
  // ... 其他 AXI 信号

  SC_CTOR(axi_transactor) : target_socket("target_socket") {
    target_socket.register_b_transport(this, &axi_transactor::b_transport);
  }

  void b_transport(tlm_generic_payload& trans, sc_time& delay) {
    // TLM → RTL: 将事务拆分为 AXI 握手序列
    uint32_t addr = trans.get_address();
    tlm_command cmd = trans.get_command();

    // 写地址通道
    wait(delay);  // 同步到 RTL 时间
    awaddr.write(addr);
    awvalid.write(true);
    wait(awready.posedge_event());  // 等待握手
    awvalid.write(false);

    // 写数据通道 ...（省略）
    // 写响应通道 ...（省略）

    trans.set_response_status(TLM_OK_RESPONSE);
    delay = SC_ZERO_TIME;
  }
};
```

### 4. Temporal Decoupling（时间解耦）设置与使用

```cpp
// 在 sc_main 中设置全局 quantum
const sc_time GLOBAL_QUANTUM(100, SC_US);
tlmu_global_quantum::instance().set(global_quantum);

// Initiator 中使用 local time
void initiator_thread() {
  tlm_generic_payload trans;
  sc_time local_time = SC_ZERO_TIME;

  while (true) {
    // 准备事务
    trans.set_command(TLM_READ_COMMAND);
    trans.set_address(next_addr);

    // 调用阻塞传输，local_time 会累加目标返回的延迟
    socket->b_transport(trans, local_time);

    // 检查是否需要同步到全局时间
    if (local_time >= tlmu_global_quantum::instance().get()) {
      wait(local_time);  // 同步到全局仿真时间
      local_time = SC_ZERO_TIME;
    }
  }
}
```

## 性能数据

| 方案 | 抽象层级 | 仿真速度 | 相对 RTL 加速 | 精度/误差 |
|------|----------|----------|--------------|----------|
| 纯 TLM-2.0 (LT) | Loosely-Timed | 50,000 txn/s | ~781× | 功能级，无 timing |
| 纯 TLM-2.0 (AT) | Approximately-Timed | ~5,000 txn/s | ~78× | 协议级 timing |
| TLM-2.0 + RTL 混仿 | Mixed | 64 txn/s | 1× (baseline) | Cycle-accurate |
| RTL-to-TLM 抽象 (NoC) | 时序+功耗注释 TLM | 10–1000× | 10–1000× | 功耗误差 < 10% |
| FAST 框架 (故障仿真) | TLM 抽象 | 100–1000× | 100–1000× | 故障覆盖率等效 |
| SoCRocket (LT+AT) | LT / AT / RTL 混合 | 1500× vs RTL | 1500× | 近 RTL 精度 |

## 相关链接

- [Bridging the gap between TLM-2.0 AT models and RTL – Intel DVCon](https://dvcon-proceedings.org/wp-content/uploads/bridging-the-gap-between-tlm-2-0-at-models-and-rtl-experiments-and-opportunities.pdf)
- [Accelerating RTL fault simulation through RTL-to-TLM abstraction – IEEE ETS](https://dl.acm.org/doi/10.1109/ETS.2011.58)
- [Defining the TLM-to-RTL Design Flow – EE Times](https://www.eetimes.com/defining-the-tlm-to-rtl-design-flow/)
- [RTL vs TLM and AT vs LT in SystemC – 中文博客](https://www.cnblogs.com/sys-123456/p/18226270)
- [On RTL to TLM Abstraction for NoC Design – ResearchGate](https://www.researchgate.net/publication/288492733)
- [Co-simulation of SystemC TLM with RTL HDL – IEEE](https://ieeexplore.ieee.org/document/4674893/)
- [Modeling of CableCARD SoC Platform based on RTL-TLM Co-Simulation](https://www.dbpia.co.kr/Journal/articleDetail?nodeId=NODE01599630)
- [TLM 2.0 simple sockets synthesis to RTL – IEEE](https://ieeexplore.ieee.org/document/4938013/)

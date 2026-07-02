---
title: "仿真框架与库的多线程支持：SystemC、UVM-SystemC、TLM-2.0 与协同仿真"
description: "分析 SystemC 内核、UVM-SystemC、TLM-2.0 及多语言协同仿真框架的并行化现状与架构设计，包括 UVMC 跨语言 TLM 通信、MINRES SCC 的 Verilated RTL 集成等"
source_url: "https://github.com/accellera-official/uvm-systemc / https://systemc.org"
source_type: "github-repo"
author: "Accellera / OSCI / MINRES 等"
date: "2024-2025"
tags: ["systemc", "uvm-systemc", "tlm", "co-simulation", "multithreading", "virtual-platform"]
keywords: ["sc_thread", "TLM-2.0", "UVM-Connect", "UVMC", "Verilated-RTL", "MINRES-SCC"]
capture_date: "2025-07-20"
---

# 仿真框架与库的多线程支持

## 来源

- **SystemC / TLM-2.0**: https://systemc.org / Accellera 标准
- **UVM-SystemC**: https://github.com/accellera-official/uvm-systemc
- **UVM Connect (UVMC)**: Accellera 贡献包（Mentor Graphics 捐赠）
- **MINRES SystemC Components (SCC)**: https://www.minres.com
- **类型**: 标准文档 + GitHub 开源仓库 + 学术论文
- **作者**: Accellera / OSCI / MINRES 等
- **日期**: 2024-2025 持续活跃

## 摘要

SystemC 和 UVM 构成了现代 SoC 验证的骨架，但它们的并行化故事比 Verilator 复杂得多。本分析覆盖：

1. **SystemC 内核**：单线程事件调度内核的架构，以及学术界的并行化尝试（SCDTHREADS、分布式仿真）；
2. **TLM-2.0**：事务级建模如何通过时间解耦提升仿真速度，以及 LT/AT 模式对并行化的影响；
3. **UVM-SystemC**：UVM 方法学在 SystemC 中的实现，其多线程能力受限于底层 SystemC 内核；
4. **跨语言协同仿真**：UVM Connect (UVMC) 实现 SystemC 与 SystemVerilog 的 TLM 通信；MINRES SCC 将 Verilated RTL 集成到 SystemC TLM 平台中。

这些框架的核心矛盾在于：**SystemC 的内核是单线程的，但上层应用需要多线程/分布式能力**。各种解决方案都围绕 "不修改内核" 或 "最小修改内核" 的约束展开。

## 关键要点

### 1. SystemC 内核：单线程事件的遗产与困境

#### 单线程调度内核

SystemC 参考实现（Accellera 的 `systemc` 仓库）的仿真内核是单线程的：
- 所有 `SC_METHOD`、`SC_THREAD`、`SC_CTHREAD` 都由一个 `sc_simcontext` 统一调度；
- 事件通过 `sc_event` 和 `sc_signal` 传递，但调度器本身是串行的；
- 仿真推进的基本单位是 **delta cycle**（时间片）和 **time advance**（时间推进）。

```cpp
// SystemC 参考实现概念模型
while (m_simulation_status == SC_RUNNING) {
    // 1. 执行当前 delta cycle 内的所有 runnable 进程
    for (sc_thread_handle thread_p : m_runnable_threads) {
        thread_p->execute();  // 每个线程执行到下一个 wait() 或 return
    }
    // 2. 更新所有信号（signal update phase）
    update_signals();
    // 3. 如果有 delta 事件，继续下一轮 delta
    // 4. 否则推进到下一个时间点的 timed 事件
}
```

> 这意味着即使你在 SystemC 模块中创建了 `std::thread`，这些线程也不能直接调用 SystemC API（如 `wait()`、`notify()`），因为内核不是线程安全的。这是 SystemC 与 Verilator 运行时最本质的区别。

#### 学术界的并行化尝试

尽管官方内核是单线程的，学术界探索了多种并行化方案：

**SCDTHREADS (UNICAMP)**：

> "O presente trabalho visa a paralelizacao do SystemC atraves do conceito de sistemas multi-threaded (SCDTHREADS), assim, evitando grandes mudancas em seu nucleo de simulacao."
> —— 论文 "Scalably Distributed SystemC Simulation for Embedded Applications"

SCDTHREADS 的核心思想是将 SystemC 进程分配到多个 OS 线程，通过 TLM 通道进行同步，避免修改内核的调度器。这是一种 **"进程级并行 + 通道级同步"** 的折中方案。

**分布式 SystemC 仿真 (ETH Zurich)**：

> "We propose a technique which supports the geographical distribution of an arbitrary number of SystemC simulations, without modifying the SystemC simulation kernel. This technique is suited to distribute functional and approximated-timed TLM simulation."

ETH 的方案更进一步，将 SystemC 仿真分布到多台机器上，通过网络同步时间戳。适用于 MPSoC 设计空间探索（DSE），其中不同子系统可以在不同节点上独立推进，仅在时间同步点交互。

> **启示**：如果我们的仿真器需要与 SystemC 生态集成，必须面对 "SystemC 内核单线程" 这一约束。可能的接口方式：将我们的多线程仿真器作为一个 "外设" 通过 TLM socket 接入 SystemC 平台，而非试图将 SystemC 进程映射到我们的线程模型。

---

### 2. TLM-2.0：时间解耦作为并行化的前奏

#### 事务级建模的抽象层级

TLM-2.0 定义了四种时间精度级别：
- **UT (Untimed)**：完全无时间概念，仅功能正确性；
- **LT (Loosely Timed)**：有时间戳，但允许时间跳跃（temporal decoupling）；
- **AT (Approximately Timed)**：有精确到相位（phase）的协议时序；
- **Cycle-Accurate**：精确到时钟周期。

```
UT  -> LT  -> AT  -> Cycle-Accurate
|      |      |         |
最快   较快    中等      最慢
并行度最高          并行度最低
```

#### 时间解耦与并行化

LT 模式允许一个 initiator 在执行一系列事务时 "借用" 时间（`quantum`），直到 quantum 耗尽才将控制权交还给仿真内核。这种 **temporal decoupling** 有两个效果：

1. **减少同步频率**：多个 initiator 可以在各自的 quantum 内独立推进，无需每个事务都同步；
2. **天然适合并行化**：如果不同 initiator 的 quantum 不重叠，它们可以真正并行执行。

> "SystemC allows describing hardware from Algorithm to RTL models. As we move towards the RTL description, the timing accuracy increases compromising on the simulation performance. This flexibility in SystemC to be more time independent in TLM abstraction layer favors to conduct a simulation performance comparison."
> —— 硕士论文 "Case Study on UVM SystemC Testbench for RTL Verification"

#### 对我们的启示

如果我们的 RTL 仿真器需要与 TLM 平台集成，应当支持 LT 模式下的 temporal decoupling：
- 在仿真器侧维护一个本地时间偏移量（local time）；
- 当收到 TLM 事务时，将本地时间推进到事务时间戳；
- 仅在 quantum 边界或显式同步点与 SystemC 全局时间对齐。

这与 Verilator 的 `eval()` 模型类似：Verilator 模型可以在一个 eval 周期内推进多个时钟周期，只要外部 testbench 同意这种 "批量推进"。

---

### 3. UVM-SystemC：方法学层的多线程局限

#### UVM-SystemC 现状

UVM-SystemC 是 Accellera 标准化的 UVM 方法学在 SystemC 中的实现，包含：
- `uvm_component` 层次结构；
- `uvm_sequence` / `uvm_sequencer` 机制；
- `uvm_phase` 阶段管理；
- TLM-1.0/2.0 端口支持。

然而，UVM-SystemC 的底层执行仍依赖 SystemC 的单线程内核：
- `uvm_sequence` 的 `body()` 运行在 `SC_THREAD` 中；
- 并发序列实际上是 **协作式多任务**（cooperative multitasking），而非抢占式多线程；
- 没有内置的线程池或 MTask 分区概念。

```cpp
// UVM-SystemC 中的序列执行（概念上）
class my_sequence : public uvm_sequence {
    UVM_OBJECT_UTILS(my_sequence)
public:
    virtual void body() {
        // 这是 SC_THREAD，执行到 wait() 时让出 CPU
        req = create_item<my_item>();
        start_item(req);
        // ... 随机化 ...
        finish_item(req);  // 内部会调用 wait()
    }
};
```

> UVM-SystemC 的价值在于 **方法学统一**（相同的 testbench 架构可用于 SystemVerilog 和 SystemC），而非性能并行化。对于我们的项目，如果目标是 "UVM 风格的验证平台"，需要自行实现底层的并行执行引擎。

---

### 4. 跨语言协同仿真：UVM Connect 与 MINRES SCC

#### UVM Connect (UVMC)：SystemC ↔ SystemVerilog 的 TLM 桥梁

UVM Connect 是 Accellera 的标准包，实现 SystemC 和 SystemVerilog 之间的 TLM 事务传递：

> "UVM Connect is a package providing complete SystemC interop support for SystemVerilog UVM/OVM via TLM1/TLM2 to easily integrate models in either language."
> —— Accellera UVM Connect 文档

实现机制：
- 使用 **SystemVerilog DPI** 作为跨语言调用接口；
- 在 SystemC 侧和 SV 侧各有一个适配层，将 TLM 事务序列化/反序列化；
- 支持 blocking 和 non-blocking 的 TLM 传输。

```cpp
// UVMC 使用示例（概念）
// SystemC 侧
uvmc_connect(tlm_socket, "sv_tlm_target");  // 绑定到 SV 侧的 TLM target

// SystemVerilog 侧
uvmc_connect(tlm_target, "sc_tlm_socket");  // 绑定到 SC 侧的 initiator
```

> 限制：UVMC 不支持跨语言线程的 disable/kill，且接口参数按值传递（pass-by-copy），修改不会立即反映到另一侧。这说明跨语言并行的边界最好是 **事务级**（粗粒度）而非 **信号级**（细粒度）。

#### MINRES SCC：将 Verilated RTL 接入 SystemC TLM 平台

MINRES 的 SystemC Components Library (SCC) 提供了一个实用的混合仿真方案：

> "One of the main challenges in building a hybrid simulation platform is integration. The SystemC model generated from an RTL design is typically expressed at the sc_signal level, while the rest of the virtual platform often operates at the TLM level. This mismatch requires adapters at the boundary to convert higher-level transactions into signal activity across one or more cycles and the inverse."
> —— MINRES "SystemC TLM Meets Verilated RTL"

SCC 提供的解决方案：
- **Pin-level adapters**：将 TLM 事务转换为 pin wiggle（周期级信号翻转）；
- **Bus adapters**：将 AXI/APB 等总线 TLM 事务映射到 RTL 信号接口；
- **Verilated model wrapper**：将 Verilator 生成的 C++ 模型包装为 SystemC 模块。

```
SystemC TLM Platform (Virtual Platform)
  -> TLM initiator (e.g., CPU model)
  -> TLM-2.0 interconnect (bus)
  -> SCC Adapter (TLM -> pin-level)
  -> Verilated RTL Module (Verilator generated)
  -> SCC Adapter (pin-level -> TLM)
  -> TLM target (e.g., memory model)
```

> 这是目前工业界最实用的 "SystemC VP + Verilated RTL" 混合仿真方案。对我们的启示是：不必将所有东西都做到一个仿真器里，而是做好 **标准接口**（TLM-2.0 socket），让 Verilator 等专用工具处理 RTL 加速，自己负责系统级集成。

#### Verilator + SystemC 的协同仿真模式

ngspice 的文档也提到了与 Verilator 的协同：

> "Co-simulation ngspice mixed-signal-Verilog digital... For Verilator see https://www.veripool.org/verilator/"

这说明 "Verilator 加速数字 + 其他工具处理模拟/系统级" 的异构模式已被多个项目验证。

---

### 5. 多线程框架的技术选型建议

| 需求 | 推荐方案 | 理由 |
|------|---------|------|
| 纯数字 RTL 高性能仿真 | Verilator + 自研线程池 | 编译型加速，MTask 静态调度 |
| 系统级验证平台（VP） | SystemC + TLM-2.0 + SCC | 事务级抽象，可集成多方模型 |
| 跨语言验证（SV + SC） | UVM + UVMC | 标准方法学，团队熟悉 |
| 混合信号（模拟 + 数字） | ngspice + Verilator | 各取所长，回调同步 |
| 需要 UVM 方法学但用 C++ | UVM-SystemC | 方法学统一，但性能受限于单线程内核 |

## 对 RTL 仿真器多线程化的启示

1. **不要重复造 SystemC**：SystemC 的 ecosystem 优势在于其庞大的模型库和行业标准地位。如果我们的仿真器要打入工业验证流程，提供 SystemC TLM socket 接口比试图替代 SystemC 更现实。

2. **TLM-2.0 作为标准边界**：将我们的多线程 RTL 仿真器通过 TLM-2.0 target/initiator 接入外部平台，可以：
   - 隐藏内部的多线程细节（外部只看到事务级接口）；
   - 利用 temporal decoupling 减少跨语言同步开销；
   - 复用现有的 adapter 生态（如 SCC 的 pin-level adapters）。

3. **UVM 方法学 vs 性能**：UVM-SystemC 证明了方法学可以移植到 C++，但底层执行引擎的性能取决于实现。如果我们要做 "UVM 风格的多线程 testbench"，需要自己设计一个支持真正并发的 sequence/sequencer 执行引擎，而非依赖 SystemC 的 cooperative threads。

4. **跨语言并行的粒度**：UVMC 的限制表明，跨语言并行最适合 **事务级**（一个事务一个事务地传递）而非 **信号级**（每个时钟周期同步）。如果 SystemC VP 和 Verilated RTL 之间需要每个周期都同步，通信开销将吞噬多线程收益。

## 原文摘录

> "SystemC becomes popular as an efficient system-level modelling language and simulation platform. However, the sole-thread simulation kernel obstacles its performance progress from the potential of modern multi-core machines."
> —— 论文 "Scalably Distributed SystemC Simulation for Embedded Applications" (ETH Zurich)

> "The behavior of each module is provided by a number of parallel threads. Threads are functions of the C++ class which communicate with the threads in other modules by passing data through the sockets. This communication is known as a transaction and the data passed as a payload."
> —— SpaceFibre SoC 设计论文

> "UVM Connect is a package providing complete SystemC interop support for SystemVerilog UVM/OVM via TLM1/TLM2 to easily integrate models in either language, supports any compliant simulator, and works with both UVM and OVM."
> —— Accellera UVM Connect 文档

> "One of the main challenges in building a hybrid simulation platform is integration. The SystemC model generated from an RTL design is typically expressed at the sc_signal level, while the rest of the virtual platform often operates at the TLM level."
> —— MINRES "SystemC TLM Meets Verilated RTL"

> "Disabling or killing of blocking the multi-language threads are not supported. The interface class type arguments are passed by copy and therefore the changes made to argument valued are not immediately visible across language boundaries."
> —— 硕士论文 "Case Study on UVM SystemC Testbench for RTL Verification" (UVMC 限制)

## 相关链接

- [SystemC 官方](https://systemc.org)
- [UVM-SystemC GitHub](https://github.com/accellera-official/uvm-systemc)
- [Accellera UVM Connect](https://forums.accellera.org/files/file/92-uvm-connect-a-systemc-tlm-interface-for-uvmovm-v22/)
- [MINRES SystemC Components](https://www.minres.com/systemc-tlm-meets-verilatedrtl/)
- [Learn SystemC 教程](https://www.learn-systemc.com/)

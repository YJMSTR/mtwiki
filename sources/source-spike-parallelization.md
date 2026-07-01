---
title: "Spike RISC-V 模拟器并行化分析"
source_url: "https://github.com/riscv-software-src/riscv-isa-sim"
source_type: "github-code"
author: "RISC-V Community"
date: "2016-2025"
tags: ["github", "parallel-code", "cpp", "simulator", "riscv", "spike", "interpretive"]
keywords: ["spike", "riscv-isa-sim", "interpretive", "lock-step", "functional-simulation", "tandem-verification"]
capture_date: "2026-07-01"
---

# Spike RISC-V 模拟器并行化分析

## 来源

- URL: <https://github.com/riscv-software-src/riscv-isa-sim>
- 类型: github-code
- 作者: RISC-V Community (UC Berkeley / SiFive)
- 日期: 2016-2025

## 摘要

Spike 是 RISC-V 官方的功能性 ISA 模拟器（Instruction Set Simulator），采用解释执行方式逐条模拟指令。与 gem5 不同，Spike 的设计目标是**指令集验证和软件测试**，而非性能仿真。Spike 本身**没有原生多线程并行化**实现，但它在多核仿真和与其他仿真器协同验证的场景中，展现了功能级模拟器与性能级模拟器结合的可能性。

## 关键要点

### 1. Spike 的架构：解释执行，无多线程

Spike 是一个逐条解释执行 RISC-V 指令的 C++ 程序。每个 hart（硬件线程）由一个 `processor_t` 对象表示，模拟循环依次执行每个 hart 的指令：

```cpp
// 简化逻辑（基于 Spike 源码结构）
for (auto& proc : procs) {
    proc->step(1);  // 执行一条指令
}
```

Spike 的 Makefile 中明确使用 `-j1`（单线程编译和运行），因为它本身就是单线程程序。

> "The simulator is running Spike (a RISC-V ISA simulator) in parallel to the DUT in a lock-step manner to ensure the DUT isn't diverging."
> — NaxRiscv 文档

### 2. 多核模拟：串行轮询，非真正并行

Spike 支持多 hart（RISC-V 多核）模拟，但实现方式是在一个主机线程内轮询执行各 hart：

- 每个 hart 有独立的寄存器文件和程序计数器；
- 内存模型通过共享内存状态实现；
- 同步原语（如原子操作、fence）在 Spike 内部被模拟，而非真正利用主机多核。

这意味着即使模拟 8 核 RISC-V，主机也只有一个线程在运行。Spike 的仿真速度因此受限（通常低于 1 MIPS）。

### 3. 与 Verilator 的协同验证（Lock-Step）

Spike 在硬件验证领域的一个重要应用是**与 Verilator 的协同验证**（tandem verification / co-simulation）：

- Spike 作为**黄金参考模型（Golden Reference）**运行；
- Verilator 编译的 RTL 作为**被测设备（DUT）**运行；
- 两者在每个提交点（commit point）比较 architectural state（寄存器、内存）；
- 如果状态不一致，立即报告 divergence。

**实现方式**（以 NaxRiscv 为例）：
- Spike 被编译为共享库（`.so`）；
- Verilator 仿真在 C++ testbench 中加载 Spike 库；
- Verilator 的 `eval()` 循环每推进一个周期，调用 Spike 执行对应数量的指令，然后比较状态。

```cpp
// 伪代码：Verilator + Spike lock-step
while (!done) {
    dut->eval();           // 推进 RTL 一个时钟周期
    spike_step(1);         // Spike 执行一条指令
    compare_state(dut, spike);  // 比较寄存器/内存
}
```

### 4. P-RISC 扩展：为 Spike 添加 Fork/Join 多线程模拟

巴塞罗那理工大学（UPC）的硕士论文《Hardware support for fine-grained parallelism and simultaneous multithreading in RISC-V》对 Spike 进行了扩展，以支持 P-RISC 模型的多线程指令验证：

- 添加 `Fork` 和 `Join` 自定义指令；
- 在 Spike 顶层动态实例化新的 `SProc`（流处理器）对象来模拟新创建的线程；
- 每个 `SProc` 独立模拟一个指令流，与硬件 DUT 的 SMT 行为对比。

> "We modified the Spike ISA simulator to make it suitable for the verification of hardware that implements the P-RISC model and instructions... When a Fork instruction is detected, a new SProc is instantiated, added to the system, and attached to memory."
> — P-RISC 论文

### 5. 与其他 RISC-V 模拟器的对比

| 模拟器 | 执行方式 | 多线程支持 | SystemC 集成 | 适用场景 |
|--------|---------|-----------|-------------|---------|
| Spike | 解释执行 | 无（主机单线程） | 无 | ISA 验证、功能测试 |
| QEMU (TCG) | 动态二进制翻译 | MTTCG 模式 | 无（QBox 插件支持） | 快速系统仿真 |
| SIM-V | JIT (FTL) | 支持（SystemC TLM-2.0） | 原生支持 | 虚拟平台 |
| gem5 | 微架构模拟 | 单线程（par-gem5/parti-gem5 支持并行） | 部分支持 | 体系结构研究 |

> "Spike does not offer a SystemC TLM-2.0 integration. Therefore, integration into full system simulations is not easily possible."
> — SIM-V 论文

## 对 RTL 仿真器多线程化的启示

1. **功能级模拟器与性能级模拟器的分工**：Spike 的 lock-step 验证模式表明，RTL 仿真器（如 Verilator）不需要自己验证指令正确性——可以委托给 Spike 作为参考模型。这样 RTL 仿真器可以专注于并行化性能仿真，而正确性由 Spike 保证。

2. **动态实例化模拟对象**：Spike 的 P-RISC 扩展展示了如何在解释执行框架中动态创建/销毁模拟对象（`SProc`）。如果 RTL 仿真器需要支持动态模块实例化（如 FPGA 动态重配置），可以借鉴这种动态对象管理。

3. **解释执行不适合并行化**：Spike 是解释执行器，每条指令都有大量分支和函数调用，天然难以并行化。RTL 仿真器如果采用编译执行（如 Verilator 生成 C++），则更适合并行化，因为编译后的代码是 flat 的，没有解释开销。

4. **验证是并行化的前提**：在将 RTL 仿真器多线程化之前，必须建立可靠的验证机制（如 lock-step 或自检查）。Spike 作为黄金参考模型，是建立这种验证机制的理想工具。

5. **多核模拟 ≠ 主机多线程**：Spike 可以在单主机线程内模拟多核 RISC-V，只是速度受限。对于 RTL 仿真器，如果目标仅仅是功能验证而非性能，可以先在单线程内正确实现多核逻辑，再逐步引入主机多线程加速。

## 相关链接

- [Spike GitHub](https://github.com/riscv-software-src/riscv-isa-sim)
- [NaxRiscv Spike 协同验证文档](https://spinalhdl.github.io/NaxRiscv-Rtd/main/NaxRiscv/simulation/index.html)
- [P-RISC 论文 - Spike 扩展](https://upcommons.upc.edu/bitstreams/862e5d1b-9864-445f-875b-6ca05e62b554/download)
- [SIM-V 论文 - RISC-V 模拟器对比](https://dvcon-proceedings.org/wp-content/uploads/74137.pdf)
- [Spike issue #911 - shared object usage](https://github.com/riscv-software-src/riscv-isa-sim/issues/911)

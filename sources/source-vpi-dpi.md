---
title: "VPI/DPI 接口性能与多线程仿真适配"
description: "SystemVerilog DPI 与 Verilog VPI 接口的性能开销分析、优化策略及在多线程 RTL 仿真器中的实现要点"
source_url: "https://dvcon-proceedings.org/wp-content/uploads/c-you-on-the-faster-side-accelerating-sv-dpi-based-co-simulation.pdf"
source_type: "paper"
author: "DVCon Proceedings / Multiple Sources"
date: "2024-05"
tags: ["vpi", "dpi", "systemverilog", "co-simulation", "performance", "multi-threading"]
keywords: ["VPI callback", "DPI overhead", "DPI-C", "parallel simulation", "PLI", "context import", "pure function"]
capture_date: "2025-06-19"
---

# VPI / DPI 接口性能与多线程仿真适配

## 来源

- URL: https://dvcon-proceedings.org/wp-content/uploads/c-you-on-the-faster-side-accelerating-sv-dpi-based-co-simulation.pdf
- 类型: 论文 / 技术博客综合
- 作者: DVCon Proceedings; CSDN 博主; systemverilog.dev
- 日期: 2024

## 摘要

VPI（Verilog Procedural Interface）和 DPI（Direct Programming Interface）是 RTL 仿真器与外部 C/C++ 世界交互的两条主要通道。VPI 基于回调机制，可深入访问仿真层次结构与信号值，但存在显著的性能开销；DPI 以「直接调用」替代了复杂的 PLI 层，大幅降低了跨语言调用成本，但牺牲了部分对仿真内部状态的直接访问能力。对于多线程 RTL 仿真器而言，DPI/VPI 的线程安全、同步模型和锁竞争是核心瓶颈。

## 关键要点

### 1. VPI 与 DPI 的架构差异

| 特性 | VPI | DPI |
|------|-----|-----|
| 调用方向 | C → 仿真器（回调） | 双向直接调用 |
| 访问能力 | 可遍历层次结构、注册信号变化回调 | 仅支持函数/任务级调用，不能直接访问仿真数据结构 |
| 性能开销 | 高（需维护回调表、事件调度） | 低（接近原生 C 函数调用） |
| 线程安全 | 需仿真器内核锁保护 | 依赖编译器实现，纯函数可免锁 |
| 标准来源 | IEEE 1364 (Verilog) | IEEE 1800 (SystemVerilog) |

### 2. DPI 性能优化数据（DVCon 实测）

以下数据来自 PCIe transactor 与视频解码器参考模型的实际优化案例：

| 优化手段 | 性能提升 |
|---------|---------|
| 减少 DPI 调用次数（35 次 → 20 次 / 100s → 30s） | **3.33×** |
| 使用标准文件流替代低效 IO（90s → 15s） | **6×** |
| 二进制文件加载替代 hex（−） | **5×** |
| C 端引入多线程加载文件（50s → 10s） | **5×** |
| 使用紧凑原生 C 数据类型 | **1.5×** |
| C 端离线处理（减少 SV↔C 往返） | **2×** |

**核心结论**：DPI 调用次数是最大瓶颈；每次跨越 SV/C 边界都会触发数据拷贝、类型转换和可能的仿真器锁竞争。

### 3. DPI 导入函数的分类与开销

```systemverilog
// 1. Pure 函数 — 无副作用，可缓存，性能最高
import "DPI-C" pure function real cos(input real n);

// 2. Generic 函数 — 默认类别，无上下文访问
import "DPI-C" function int factorial(input int i);

// 3. Context 函数 — 可访问 SV 侧数据，需保存上下文，额外开销
import "DPI-C" context function void my_task_with_context(...);
```

- **pure**：不访问任何全局状态，仿真器可自由优化调用顺序，**推荐用于计算密集型函数**。
- **context**：需访问 SV 变量或调用 export 函数，会触发上下文保存/恢复，**开销显著增加**。仅在必要时使用。

### 4. VPI 回调开销分析

```c
// VPI 注册信号变化回调示例
s_cb_data cb_data = {
    .reason = cbValueChange,
    .cb_rtn = &on_value_change_callback,
    .obj    = signal_handle,
    .time   = &time,
    .value  = &value,
};
vpiHandle cb = vpi_register_cb(&cb_data);
```

VPI 回调的隐性成本：
1. **事件调度开销**：每次信号变化都需进入仿真器事件队列，触发回调调度。
2. **数据拷贝**：`vpi_get_value` / `vpi_put_value` 在 SV 与 C 堆栈间复制数据。
3. **锁竞争**：多线程仿真器下，回调执行通常需要获取仿真内核锁，成为串行瓶颈。

### 5. 多线程仿真器中的 DPI/VPI 适配策略

```systemverilog
// 推荐：将高频 DPI 调用批量化，减少跨边界次数
import "DPI-C" function void batch_process(
    input  bit [31:0] data_in [0:99],
    output bit [31:0] data_out [0:99]
);
```

```c
// C 端批量处理，避免逐元素调用
void batch_process(const svBitVecVal* data_in, svBitVecVal* data_out) {
    for (int i = 0; i < 100; i++) {
        data_out[i] = heavy_compute(data_in[i]);  // 纯 C 内循环，无 SV 交互
    }
}
```

- **批量化调用**：将细粒度调用合并为数组/结构体批处理，减少边界穿越次数。
- **离线计算**：把参考模型（reference model）完全放在 C 侧，仅在需要比对结果时进行一次 DPI 调用。
- **线程安全设计**：在 C 侧使用独立线程池处理计算任务，通过无锁队列与仿真主线程通信。

## 对 RTL 仿真器多线程化的启示

1. **DPI 是纯函数优先**：多线程调度器可将纯 DPI 调用并行化到工作线程，不阻塞仿真时间推进。
2. **VPI 回调是锁热点**：`cbValueChange` 类回调会强制串行化，多线程仿真器应考虑将监控逻辑下沉到 C 侧，通过周期性采样替代事件驱动回调。
3. **Context import 是串行瓶颈**：任何 context 函数都隐含对仿真状态的访问，多线程实现需在内核加锁，建议用 thread-local 存储替代全局共享状态。
4. **覆盖率收集的 DPI 化**：传统 VPI 遍历层次收集覆盖率的方式在多线程下代价高昂，可考虑在仿真编译期注入覆盖率探针，运行时通过轻量 DPI 接口批量读取。

## 原文摘录

> "DPI 标准源自两个专有接口，一个来自 Synopsys 公司的 VCS DirectC 接口，另一个来自 Co-Design 公司的 SystemSim Cblend 接口。Accellera 的 SystemVerilog 标准委员会把这两个技术合并在一起，使得 DPI 能够与任何 Verilog 仿真器一起工作。" — Accellera SystemVerilog LRM

> "PLI 方式给仿真带来了额外的负担，为了保护 Verilog 的数据结构，仿真器需要不断的在 Verilog 和 C 之间复制数据。SystemVerilog 引入了 DPI，能够更简洁地连接 C/C++。" — CSDN 博客

> "Improvement using less number of DPI calls: 100 secs for 35 DPI calls got reduced to 30 secs for 20." — DVCon Paper "C You on the Faster Side"

> "DPI を使うと C 側から SystemVerilog の task を直接に呼べる。OBJECT レベルのリンクなので、オーバヘッドは 0 または VPI に比べると小さい。逆にいうとチェックがない。" — Sugawara Systems

## 相关链接

- [C You on the Faster Side: Accelerating SV DPI Co-Simulation](https://dvcon-proceedings.org/wp-content/uploads/c-you-on-the-faster-side-accelerating-sv-dpi-based-co-simulation.pdf)
- [SystemVerilog DPI Tutorial (GitHub)](https://github.com/adki/DPI_Tutorial)
- [systemverilog.dev — VPI and DPI](https://systemverilog.dev/9.html)
- [VPI 与 DPI 的关系 (CSDN)](https://www.cnblogs.com/Alfred-HOO/articles/15473255.html)
- [SV 通过 DPI 调用 C (CSDN)](https://www.cnblogs.com/-9-8/p/6306946.html)
- [VPI callback 与 Verilator 实现 (GitHub Issue)](https://github.com/verilator/verilator/issues/7092)

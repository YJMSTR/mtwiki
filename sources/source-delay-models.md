---
title: Delay Model Optimization in RTL Simulation
description: Transport delay, inertial delay, zero delay, unit delay, SDF back-annotation, and delay model optimization techniques in RTL and gate-level simulation
date: "2026-07-03"
---

# 延迟模型优化在 RTL 仿真中的实现

## 来源

- **URL (Delay Modeling in Verilog)**: https://vlsiweb.com/delay-modeling-transport-inertial-in-verilog/
- **URL (RTL vs Gate Level Simulation)**: https://www.leadsoc.com/rtl-vs-gate-level-simulation-whats-the-difference/
- **URL (Gate Level Simulation Methodology, Cadence)**: https://www.multimediadocs.com/assets/cadence_emea/documents/gatelevel_simulation_methodology.pdf
- **URL (RTL-DEVS Delay Control)**: https://www.mdpi.com/2673-4001/4/1/2
- **URL (Accurate Power Analysis - Inertial Delay)**: http://oops.uni-oldenburg.de/341/1/371.pdf
- **URL (Verilog Delay Back-Annotation)**: https://www.alexceli.org/download/libros/PDF-TECH/Electronics/Digital Design/Verilog - A Guide to Digital Design and Synthesis.pdf
- **类型**: doc / blog / paper
- **作者**: VLSIWeb, Cadence, MDPI, Samir Palnitkar (Verilog Guide), various
- **日期**: 2017–2026

## 摘要

RTL 仿真器的延迟模型决定了信号变化在时间和逻辑上的传播方式。从最简单的 zero-delay 模型到精确的 SDF back-annotation，延迟模型直接影响仿真速度、内存占用和时序验证精度。本文档整理 Verilog/VHDL 中两种核心延迟语义——transport delay 与 inertial delay——的实现机制、优化策略，以及 zero-delay、unit-delay、SDF back-annotation 在 RTL 与门级仿真中的工程实践。

## 关键要点

### 1. Transport Delay vs Inertial Delay

Verilog/VHDL 支持两种基本延迟模型：

| 特性 | Transport Delay | Inertial Delay |
|---|---|---|
| 物理意义 | 信号在导线/传输线上的传播延迟 | 门电路的惯性延迟（RC 充放电） |
| 脉冲过滤 | 不过滤窄脉冲 | 过滤宽度 < 延迟的脉冲 |
| 适用场景 | 总线、互连线、时钟树 | 逻辑门、触发器、组合逻辑 |
| Verilog 语法 | `wire #5 w;` / `assign #5 out = in;` | 门原语默认：`and #5 (y, a, b);` |
| VHDL 语法 | `z <= transport a after 5ns;` | `z <= a after 5ns;` (默认) |

**Inertial Delay 的脉冲过滤机制**：

当输入脉冲宽度小于门延迟时，输出不发生变化。仿真器实现：
1. 输入变化时，在事件队列中调度输出变化事件（时间戳 = 当前时间 + 延迟）
2. 若在事件触发前输入再次变化，检查新旧事件的时间差
3. 若时间差 < 延迟，则取消（deschedule）先前事件

```c
// 伪代码：Inertial delay 事件调度
void schedule_inertial(Net* net, Value new_val, Time delay) {
    Time event_time = current_time + delay;
    
    // 检查已调度事件是否需取消
    for (auto& pending : net->scheduled_events) {
        if (event_time - pending.time < delay) {
            cancel_event(pending);  // 脉冲太窄，取消
        }
    }
    
    if (net->current_value != new_val) {
        insert_event_queue(net, new_val, event_time);
    }
}
```

**Transport Delay 的事件调度**：
- 所有输入变化都被传播到输出，即使脉冲宽度小于延迟
- 新事件不取消旧事件，而是叠加（FIFO 队列）
- 常用于建模长距离互连线的延迟，这些线不会「吸收」窄脉冲

```c
// 伪代码：Transport delay 事件调度
void schedule_transport(Net* net, Value new_val, Time delay) {
    Time event_time = current_time + delay;
    insert_event_queue(net, new_val, event_time);  // 从不取消旧事件
}
```

### 2. 事件队列数据结构优化

事件队列是延迟模型实现的核心数据结构。常见优化：

**Timing Wheel（时间轮）**：
- 将仿真时间划分为固定槽位（bucket），每个槽位存储该时间点的事件链表
- 时间推进时只需移动到下一个槽位，O(1) 获取下一事件
- 适用于事件密集、时间跨度有限的场景

```c
#define WHEEL_SIZE 1024
struct TimingWheel {
    EventList bucket[WHEEL_SIZE];
    uint64_t current_time;
    
    void schedule_event(Event* e, Time delay) {
        uint64_t slot = (current_time + delay) % WHEEL_SIZE;
        bucket[slot].push_back(e);
    }
    
    EventList* get_current_events() {
        return &bucket[current_time % WHEEL_SIZE];
    }
};
```

**Calendar Queue（日历队列）**：
- 分层时间轮，使用多个粒度级别处理不同时间尺度的事件
- 第一层：当前时间附近的精细粒度（1 delta cycle）
- 第二层：较长延迟的粗粒度（10/100/1000 time unit）
- 减少「空转」时间步，提升仿真速度

### 3. Zero Delay, Unit Delay, 与 SDF Back-Annotation

在 RTL → 门级 → 布局布后的验证流程中，使用三种延迟模式：

#### Zero Delay Simulation（零延迟仿真）
- 所有门延迟和互连延迟设为 0
- 使用 `-nospecify` 或 `-delay_mode zero` 开关
- 用途：系统初始化、复位序列验证、DFT 验证、功能正确性检查
- 速度最快，但无法检测 race condition、glitch、timing violation

```bash
# Cadence Xcelium / Incisive
xrun -nospecify ...
# Synopsys VCS
vcs -delay_mode zero ...
```

#### Unit Delay Simulation（单位延迟仿真）
- 每个元素固定为一个单位延迟（通常 #1）
- 用途：检测 race condition、组合逻辑环、粗略时序分析
- 比 zero-delay 稍慢，但无需真实 SDF 文件

```bash
xrun -delay_mode unit ...
```

#### SDF Back-Annotation（标准延迟格式回注）
- SDF 文件包含每个单元和连线的最小/典型/最大延迟：
  - `MINIMUM`：最佳情况（best case）
  - `TYPICAL`：典型情况
  - `MAXIMUM`：最坏情况（worst case）
- 在 Verilog testbench 中使用 `$sdf_annotate` 系统任务加载：

```verilog
initial begin
    $sdf_annotate("design.sdf", DUT, , "sdf.log", "MAXIMUM");
end
```

**SDF 文件结构示例**：

```sdf
(CELL
    (CELLTYPE "DFF")
    (INSTANCE U1)
    (DELAY (ABSOLUTE
        (IOPATH (posedge clk) (posedge q) (1.2:1.5:1.8))
    ))
    (TIMINGCHECK
        (SETUP (posedge d) (posedge clk) (0.8:1.0:1.2))
        (HOLD (posedge d) (posedge clk) (0.2:0.3:0.4))
    )
)

(CELL
    (CELLTYPE "digital_top")
    (INSTANCE)
    (DELAY (ABSOLUTE
        (INTERCONNECT in1 top/my_reg/D (0.027::0.028) (0.029::0.030))
    ))
)
```

### 4. 延迟模型优化技术

#### Delay Scaling（延迟缩放）
- 在调试阶段将真实延迟按比例缩小（如 1/10），加速仿真同时保留相对时序关系
- 对 SDF 延迟进行全局缩放：

```verilog
// 在 testbench 中全局缩放
initial begin
    $sdf_annotate("design.sdf", DUT, , , , "1.0:0.5:0.1"); // 缩放因子
end
```

#### Model Abstraction（模型抽象）
- 对非关键路径使用 zero-delay 或 unit-delay 模型
- 仅对关键路径（setup/hold 路径、时钟树）使用 SDF back-annotation
- 分层仿真：顶层模块用 zero-delay，子模块用 SDF

#### Event Optimization（事件优化）
- **Glitch 合并**：若同一 net 在时间窗口内发生多次翻转，只保留最后一次（当使用 inertial delay 时自动处理）
- **Delta Cycle 合并**：在 zero-delay 仿真中，多个 delta cycle 内的事件可合并为一次最终状态更新
- **Inactive Region 跳过**：若某时间槽无活跃事件，直接跳转到下一事件时间

#### Parallel Simulation（并行仿真）
- 在 SDF 模式下，不同延迟路径之间通常无数据依赖，可在多线程中并行求值
- 使用 **Parallel Discrete Event Simulation (PDES)** 技术：将设计空间划分为 LP（Logical Process），各 LP 使用自己的局部事件队列，通过时间同步协议（如 Time Warp、Conservative Barrier）协调

### 5. 延迟模型与 RTL/GLS 验证流程

| 阶段 | 延迟模型 | 目的 | 速度 |
|---|---|---|---|
| RTL 功能仿真 | Zero-delay | 验证功能正确性 | 最快 |
| 综合后 GLS | Zero-delay | 验证综合未引入功能错误 | 快 |
| 综合后 GLS | Unit-delay | 检测 race / 组合环 | 中等 |
| 布局后 GLS | SDF (pre-layout) | 初步时序验证 | 慢 |
| 布线后 GLS | SDF (post-layout) | 最终时序 sign-off | 最慢 |

**性能对比**：
- RTL zero-delay：基准速度 1x
- Gate-level zero-delay：10-20x  slower（门数量激增）
- Gate-level SDF：100-1000x slower（事件队列爆炸、延迟计算、timing check）

### 6. RTL 仿真器中的延迟模型简化

对于编译型 RTL 仿真器（如 Verilator、ESSENT、CXXRTL），延迟模型被大幅简化：

- **Verilator**：默认 zero-delay cycle-accurate 模型，忽略所有 `#delay` 和 specify block
- **ESSENT**：基于 FIRRTL 的时钟同步抽象，假设所有组合逻辑在一个 delta cycle 内收敛
- **CXXRTL**：将 `always_ff` 和 `always_comb` 编译为 C++ 函数，寄存器更新在显式边界完成

这些工具不支持完整的 transport/inertial delay，但利用简化获得数量级性能优势。对于需要精确时序的场景，通常 fallback 到商业事件驱动仿真器（VCS/Xcelium/Questa）。

## 对 RTL 仿真器多线程化的启示

1. **Zero-delay 模型天然适合多线程**：无事件队列依赖，所有组合逻辑可并行求值，只需在寄存器更新点同步
2. **Inertial delay 的 deschedule 操作需线程安全**：多线程访问事件队列时，取消已调度事件需使用 lock-free 或 per-thread 局部队列 + 合并
3. **SDF back-annotation 的并行化**：不同路径的延迟计算独立，可在 SIMD 寄存器中批量处理 min/typ/max 三种 corner
4. **Timing wheel 的 bucket 访问是潜在瓶颈**：多线程向同一 bucket 插入事件时，需使用无锁队列（如 Michael-Scott queue）或 per-thread 子桶 + 定期合并
5. **Delay scaling 可用于并行 corner simulation**：同时运行 MIN/TYP/MAX 三个 corner，利用多线程并行，总时间接近单次 SDF 仿真

## 原文摘录

> "Inertial delay has been proposed to model gates or circuits that do not transfer short pulses from input to output. If the gate has a delay time of t, the pulse signal with a width shorter than t is ignored."
> — MDPI RTL-DEVS Paper

> "Transport delay is intended to model the delay time that occurs in the wiring due to various physical factors. In other words, when an input change occurs, the input change is received, but the actual output is scheduled after a defined time."
> — RTL-DEVS Paper

> "Replacing delay path, or distributed with global zero or unit delays, can reduce simulation time by an appreciable amount. You can use delay modes during design debugging phases, when checking design functionality is more important than timing correctness."
> — Cadence Gate-Level Simulation Methodology

> "The inertial delay is also a member of the real delay models. In addition to the filtering mechanism of the transport delay model, pulses of shorter duration than the element's delay are generally not passed through an instance."
> — Accurate Power Analysis of Integrated CMOS Circuits

> "RTL simulation runs with zero delay — it cannot catch setup time violations or hold time violations. Timing-annotated GLS (with SDF back-annotation) makes it possible to catch setup time violations, hold time violations, glitches, and race conditions hidden by zero-delay RTL simulation."
> — LeadSoC, RTL vs Gate Level Simulation

## 相关链接

- [VLSIWeb - Delay Modeling in Verilog](https://vlsiweb.com/delay-modeling-transport-inertial-in-verilog/)
- [LeadSoC - RTL vs Gate Level Simulation](https://www.leadsoc.com/rtl-vs-gate-level-simulation-whats-the-difference/)
- [Cadence Gate-Level Simulation Methodology (PDF)](https://www.multimediadocs.com/assets/cadence_emea/documents/gatelevel_simulation_methodology.pdf)
- [MDPI RTL-DEVS - Delay Control](https://www.mdpi.com/2673-4001/4/1/2)
- [Verilog Guide - Delay Back-Annotation (PDF)](https://www.alexceli.org/download/libros/PDF-TECH/Electronics/Digital%20Design/Verilog%20-%20A%20Guide%20to%20Digital%20Design%20and%20Synthesis.pdf)
- [Gate Level Simulation Guide (Verifast)](https://verifasttech.com/gate-level-simulation-ensuring-chip-functionality-and-timing/)
- [StackOverflow - Inertial vs Transport Delay](https://stackoverflow.com/questions/47580661/why-verilog-simulators-model-net-delay-as-inertial-delay-rather-than-transport-d)

---
id: "wiki-mixed-signal"
title: "混合信号与物理层仿真"
description: "系统梳理Verilog-AMS协同仿真、SPICE/FastSPICE数值方法与加速技术、SerDes/PHY的IBIS-AMI框架与112G PAM-4仿真，为多线程RTL仿真器处理混合信号场景提供分区策略与并行化建议"
tags: ["mixed-signal", "Verilog-AMS", "SPICE", "FastSPICE", "SerDes", "PHY", "IBIS-AMI", "co-simulation", "rtl-sim"]
keywords: ["Verilog-AMS", "Digital-on-Top", "a2d", "d2a", "MNA", "Newton-Raphson", "FastSPICE", "Lock-step", "Relaxation", "Backtracking", "IBIS-AMI", "PAM-4", "112G", "PySerDes", "眼图", "浴盆曲线"]
related_sources:
  - "source-mixed-signal"
  - "source-spice-interface"
  - "source-phy-serdes"
last_updated: "2026-07-02"
---

# 混合信号与物理层仿真

混合信号仿真（Mixed-Signal, AMS）是数字RTL与模拟电路之间的"无人区"。当SoC集成ADC、PLL、SerDes PHY等模拟IP时，RTL仿真器必须跨越离散事件与连续时间的鸿沟。本章从Verilog-AMS的三种协同仿真方法出发，深入SPICE/FastSPICE的数值内核，延伸到112G PAM-4 SerDes的物理层仿真，最终推导出对多线程RTL仿真器的核心启示：**模拟部分是瓶颈，数字部分应尽可能并行，跨域接口用批量同步**。

---

## 1. Verilog-AMS：三种协同仿真方法与数模接口

### 1.1 三种验证方法的精度-速度权衡

| 方法 | 精度 | 速度 | 覆盖范围 | 适用场景 |
|------|------|------|---------|---------|
| **全晶体管级** | 最高 | 最慢 | 最低（小规模电路） | 模拟IP signoff、噪声分析 |
| **全数字行为级** | 最低 | 最快 | 最高（全系统） | 早期架构探索、软件协同验证 |
| **混合模式AMS** | 中 | 中 | 中（RTL + SPICE子模块） | 块级验证、ADC/PLL集成验证 |

混合模式AMS是RTL仿真器最常遇到的场景：数字部分以RTL或行为级运行，模拟部分（如ADC、LDO）以SPICE或Verilog-AMS模型运行，两者通过数模接口元素交换数据。

### 1.2 数模接口元素：a2d / d2a / a2a

Verilog-AMS定义了三种跨域接口元素，是混合信号仿真的"翻译官"：

```
┌─────────────────────────────────────────────────────┐
│  Digital Domain (0/1, event-driven)                │
│                          │                          │
│                    ┌─────┴─────┐                    │
│                    │   d2a     │  数字→模拟：0/1映射  │
│                    │  (driver) │  为 lov/hiv 电压范围 │
│                    └─────┬─────┘                    │
│                          │                          │
│  ┌───────────────────────┼───────────────────────┐  │
│  │      Analog Net       │   (continuous)        │  │
│  │  (voltage, current)   │                       │  │
│  └───────────────────────┼───────────────────────┘  │
│                          │                          │
│                    ┌─────┴─────┐                    │
│                    │   a2d     │  模拟→数字：阈值判别 │
│                    │ (sampler) │  loth/hith 带滞回  │
│                    └─────┬─────┘                    │
│                          │                          │
│  Digital Domain (0/1, event-driven)                │
└─────────────────────────────────────────────────────┘
```

| 接口元素 | 方向 | 转换机制 | 关键参数 | 多线程影响 |
|---------|------|---------|---------|-----------|
| **d2a** | 数字→模拟 | 0/1 → 分段线性/滤波电压 | 转换时间、电压范围 | 需同步到模拟时间步 |
| **a2d** | 模拟→数字 | 电压 → 0/1（带滞回） | 阈值电压、滞回宽度 | 可能触发数字事件 |
| **a2a** | 模拟→模拟 | 直通网表，避免冗余转换 | 无 | 无额外开销 |

> **滞回设计**：a2d转换采用50–200mV的滞回窗口，防止模拟噪声在阈值附近引起数字端的抖动事件。

### 1.3 Digital-on-Top (DoT) 架构

业界标准做法是以Verilog/SystemVerilog为顶层，SPICE网表作为子模块注入：

```verilog
// Digital-on-Top：Verilog顶层 + SPICE子模块
module top;
    // 数字部分：RTL或行为级
    digital_controller u_ctrl (.clk(clk), .adc_data(adc_out));
    
    // 模拟部分：通过`use_spice注入SPICE网表
    // VCS自动插入a2d/d2a接口元素
    adc_spice u_adc (.vin(vin), .dout(adc_out));
endmodule
```

| 特性 | Digital-on-Top | Analog-on-Top |
|------|---------------|---------------|
| 顶层语言 | Verilog/SV | SPICE/SPICE-like |
| 适用场景 | 数字主导设计、已有RTL Testbench | 模拟主导设计、射频电路 |
| 工具支持 | VCS-AMS、Spectre-AMS | ADMS、ELDO |
| 效率 | 更优（数字仿真器主导调度） | 模拟器主导，数字事件为"外来者" |

### 1.4 Verilog-AMS语言扩展

在标准Verilog基础上引入`analog`过程块和连续时间信号：

```verilog
// Verilog-AMS：同一模块内数模共存
module resistor(p, n);
    inout p, n;
    electrical p, n;  // 连续时间电气节点
    parameter real R = 1k;  // 实数参数
    
    // analog过程块：连续时间方程
    analog begin
        V(p, n) <+ I(p, n) * R;  // 贡献运算符：V = I*R
    end
endmodule
```

---

## 2. SPICE/FastSPICE：数值内核与加速技术

### 2.1 SPICE核心算法：MNA + Newton-Raphson

SPICE仿真的数学基础由三个核心组件构成：

| 组件 | 算法 | 复杂度 | 作用 |
|------|------|--------|------|
| **MNA** (Modified Nodal Analysis) | 线性方程组 Ax = b | O(n^1.1–n^1.5) 稀疏直接求解 | 建立电路方程 |
| **Newton-Raphson** | 非线性方程迭代 | 每时间步3–10次迭代 | 求解器件非线性 |
| **隐式积分** | Backward Euler / Trapezoidal / Gear BDF | O(1) per step | 时域推进 |

```
每时间步的计算流程：
┌──────────────────────────────────────────┐
│  1. 计算所有器件的I-V/C-V（紧凑模型）      │
│  2. 填充雅可比矩阵 J 和残差向量 F           │
│  3. 求解 J * Δx = -F （Newton-Raphson）   │
│  4. 更新解 x ← x + Δx                     │
│  5. 检查收敛：‖Δx‖ < tol ?               │
│     否 → 回到步骤1                        │
│     是 → 下一步时间积分                    │
└──────────────────────────────────────────┘
```

### 2.2 FastSPICE四大加速技术

FastSPICE通过牺牲少量精度换取10–100×加速：

| 加速技术 | 原理 | 加速效果 | 对RTL的启发 |
|---------|------|---------|------------|
| **事件驱动选择性求值** | 仅重算电压变化超过阈值的节点 | 5–20× | 活性低模块粗粒度推进 |
| **查表器件模型** | I-V/C-V用三次样条插值替代运行时计算 | 2–10× | 模拟IP行为模型预计算LUT |
| **电路分区与多速率积分** | 高活动区域小步长、静态区域大步长 | 3–10× | 不同时钟域/电源域独立推进 |
| **层次化方法** | 存储阵列结构复用，避免重复建模 | 2–5× | 重复模块的模板实例化 |

### 2.3 三种协同仿真同步策略

数字仿真器（离散事件）与模拟仿真器（连续时间）的同步是混合信号仿真的核心难题：

| 策略 | 机制 | 精度 | 效率 | 适用场景 |
|------|------|------|------|---------|
| **Lock-step** | 双核严格同步推进，每步交换状态 | 最高 | 最低 | 紧耦合反馈环路（如PLL） |
| **Relaxation** | 各自独立推进，定期交换边界解 | 中 | 高 | 弱耦合模块（如独立ADC） |
| **Backtracking** | 发现跨域事件时回滚重算 | 高 | 中 | 数字事件触发模拟重启动 |

```cpp
// Lock-step同步伪代码（最保守策略）
while (t < T_end) {
    // 数字侧：推进到下一个事件时间
    double next_digital_event = digital_sim.advance();
    
    // 模拟侧：用自适应步长积分到该时间点
    analog_sim.integrate_to(next_digital_event, lock_step_mode);
    
    // 双向交换：a2d/d2a转换
    exchange_boundary_signals();
    
    // 检查一致性：如果模拟步长被拒绝，回退并减小步长
    if (!analog_sim.converged()) {
        analog_sim.rollback();
        analog_sim.reduce_step();
    }
}
```

### 2.4 收敛辅助技术

SPICE的Newton-Raphson在强非线性区域（如MOS管亚阈值、SRAM读操作）可能不收敛。工业界采用三种辅助策略：

| 技术 | 原理 | 适用场景 |
|------|------|---------|
| **Gmin stepping** | 逐步减小并联电导Gmin，从线性过渡到非线性 | 一般性收敛困难 |
| **Source stepping** | 逐步将电源电压从0V升到目标值 | 大信号瞬态 |
| **Pseudo-transient** | 引入伪时间变量，将DC问题转化为瞬态问题 | DC工作点分析 |

> **对RTL仿真器的启示**：如果引入模拟连续时间方程，需内置类似的收敛启发式策略，避免模拟内核发散导致整体仿真挂起。

---

## 3. SerDes/PHY：IBIS-AMI框架与112G PAM-4仿真

### 3.1 IBIS-AMI建模框架

IBIS-AMI（Algorithmic Modeling Interface）是SerDes系统级仿实的业界标准，由三文件组成：

| 文件 | 扩展名 | 内容 | 角色 |
|------|--------|------|------|
| **IBIS** | `.ibs` | 缓冲器的I-V曲线、V-T曲线、封装寄生参数 | 模拟缓冲器电气特性 |
| **AMI** | `.ami` | 算法参数JSON（均衡系数、CDR配置、自适应步长） | 配置数字均衡算法 |
| **可执行模型** | `.dll` / `.so` | C/C++实现的Tx/Rx均衡算法（FFE、DFE、CTLE、CDR） | 运行时可调用模型 |

```
系统级通道仿真链路：

   ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
   │  Tx AMI  │────→│  Tx IBIS │────→│  Channel │────→│  Rx IBIS │────→│  Rx AMI  │
   │  (.dll)  │     │  (.ibs)  │     │  (S参数) │     │  (.ibs)  │     │  (.dll)  │
   └──────────┘     └──────────┘     └──────────┘     └──────────┘     └──────────┘
        ↑                                                              ↑
   ┌──────────┐                                                    ┌──────────┐
   │ RTL验证： │                                                    │ RTL验证： │
   │  FFE/TX  │                                                    │  DFE/CDR │
   │  数字逻辑 │                                                    │  数字逻辑 │
   └──────────┘                                                    └──────────┘
```

### 3.2 112G PAM-4架构演进

从传统模拟密集型架构转向ADC + 灵活DSP架构：

| 架构 | 实现方式 | 仿真挑战 | 多线程机会 |
|------|---------|---------|-----------|
| **传统模拟架构** | 纯模拟FFE/DFE/CTLE | 晶体管级精度，难以加速 | 有限 |
| **ADC-based DSP** | AFE → ADC → FFE/DFE/CDR/ADAPT | 数字均衡算法占主导 | 大量数字逻辑可并行 |

```
112G PAM-4 Rx DSP链路（数字部分）：

ADC采样 → FFE → CTLE → DFE → CDR → 自适应算法(ADAPT)
   ↑                                    ↑
 模拟前端                           数字反馈环路
（IBIS-AMI模型）                    （RTL验证重点）
```

> **关键趋势**：信号均衡大量后移至数字域，意味着多线程RTL仿真器可以高效验证FFE、DFE、CDR等DSP模块的功能正确性和收敛速度，而模拟前端（AFE、ADC）通过IBIS-AMI或Verilog-AMS行为模型提供激励。

### 3.3 两种仿真模式

| 模式 | 假设 | 速度 | 适用性 | 与RTL仿真器的关系 |
|------|------|------|--------|-----------------|
| **统计仿真** | LTI系统、线性时不变 | 极快 | 仅适用于线性/时不变模型 | 不适用于含状态机的RTL |
| **时域逐bit仿真** | NLTV（非线性时变） | 慢 | 支持CDR、自适应、抖动 | 可直接驱动RTL仿真 |

### 3.4 眼图与浴盆曲线

| 指标 | 定义 | 验证目标 | 多线程统计方法 |
|------|------|---------|--------------|
| **眼图** | 大量bit的波形叠加形成的"眼睛" | 评估抖动容限和噪声裕量 | 多线程并行生成不同bit模式，最后聚合 |
| **浴盆曲线** | BER随采样相位变化的分布 | 确定最优采样点和链路裕量 | 各线程独立统计不同相位区间，原子计数器合并 |

### 3.5 PySerDes：开源验证工具

PySerDes提供灵活的容器库，可集成到Python科学计算生态中，用于：
- 快速原型验证均衡算法
- 参数扫描（PVT corner分析）
- 与RTL仿真器的联合验证（通过Python-SV DPI接口）

---

## 4. 对多线程RTL仿真器的启示

### 4.1 模拟部分是瓶颈

在混合信号仿真中，SPICE/FastSPICE的连续时间求解是绝对的性能瓶颈。数字RTL仿真即使单线程，通常也比模拟求解快数个数量级。因此，多线程化的首要目标不是"让模拟更快"，而是"让数字部分不等待模拟"。

| 部分 | 计算特性 | 瓶颈来源 | 并行化策略 |
|------|---------|---------|-----------|
| **数字RTL** | 离散事件、布尔运算 | 规模 | 多线程并行（已讨论） |
| **模拟SPICE** | 连续时间、矩阵求解 | Newton-Raphson收敛 | FastSPICE多核分区 |
| **跨域接口** | 格式转换、阈值检测 | 同步频率 | 批量同步、减少交换次数 |

### 4.2 需要混合精度并行

混合信号仿真天然涉及不同精度需求：
- 数字部分：0/1布尔值，精度无意义
- 模拟部分：浮点电压/电流，精度决定收敛性
- 接口部分：混合精度，a2d/d2a转换涉及量化

多线程RTL仿真器若扩展支持AMS，需引入混合精度数据路径：

```cpp
// 混合精度信号值表示
union MixedSignalValue {
    bool     digital;      // 数字域：0/1
    double   analog;       // 模拟域：电压/电流
    uint16_t quantized;    // 接口域：量化值（如ADC输出）
};

// 每信号标注域类型，调度器根据域类型选择计算引擎
enum Domain { DIGITAL, ANALOG, INTERFACE };
struct Signal {
    Domain domain;
    MixedSignalValue value;
};
```

### 4.3 分区策略不同

数字RTL的多线程分区基于**逻辑依赖图**（combinational/sequential边界），而模拟SPICE的分区基于**电路拓扑**（节点连接、RC树、反馈环路）：

| 维度 | 数字RTL分区 | 模拟SPICE分区 |
|------|------------|--------------|
| 依据 | 信号依赖图、时钟域 | 电路拓扑、RC常数 |
| 目标 | 减少跨区边、均衡负载 | 减少矩阵耦合、利用多速率 |
| 边界同步 | 周期级barrier | 时间步级lock-step |
| 负载特征 | 稀疏活跃（每周期少数门翻转） | 密集计算（每步全矩阵求解） |

---

## 5. 可操作建议

### 5.1 数字部分多线程

将混合信号设计中的数字部分最大化并行化，模拟部分通过轻量接口耦合：

```cpp
// 数字-模拟混合调度器
class MixedSignalScheduler {
    std::vector<std::thread> digital_threads;
    std::thread analog_thread;  // FastSPICE通常在独立线程
    
    void run_cycle() {
        // 数字部分：多线程并行推进RTL
        parallel_for_each(digital_partitions, [](auto& part) {
            part.eval_cycle();
        });
        
        // 数字→模拟：批量转换（每N周期或事件触发）
        if (cycle_count % N == 0 || has_digital_event()) {
            d2a_batch_convert();
            analog_cv.notify_one();  // 唤醒模拟线程
        }
        
        // 模拟→数字：非阻塞检查
        if (analog_result_ready()) {
            a2d_batch_convert();
        }
    }
};
```

### 5.2 模拟部分FastSPICE多核

利用商业FastSPICE工具的多核能力，将模拟子电路分配到独立线程：

```cpp
// FastSPICE分区与多核映射（概念性）
class FastSPICEMultiCore {
    // 按电路拓扑分区：弱耦合子电路独立求解
    std::vector<SubCircuit> partitions;
    
    void parallel_solve() {
        #pragma omp parallel for
        for (size_t i = 0; i < partitions.size(); ++i) {
            // 各子电路独立Newton-Raphson迭代
            partitions[i].solve_local();
        }
        // 全局弱耦合节点：Jacobi迭代或Gauss-Seidel迭代
        solve_global_coupling();
    }
};
```

> **实际部署**：Cadence Spectre APS、Synopsys VCS AMS均支持多核FastSPICE。将模拟子电路绑定到独立NUMA节点，避免与数字线程竞争内存带宽。

### 5.3 接口用批量同步

减少a2d/d2a转换和跨域同步的频率是最有效的优化：

```cpp
// 批量同步接口：每N周期交换一次边界信号
class BatchSyncInterface {
    static constexpr int BATCH_CYCLES = 8;
    std::array<DigitalState, BATCH_CYCLES> digital_buffer;
    std::array<AnalogState, BATCH_CYCLES> analog_buffer;
    int batch_idx = 0;
    
    void digital_cycle(const DigitalState& d) {
        digital_buffer[batch_idx] = d;
        if (++batch_idx == BATCH_CYCLES) {
            // 批量d2a转换：减少模拟器唤醒次数
            for (int i = 0; i < BATCH_CYCLES; ++i) {
                d2a_convert(digital_buffer[i], analog_buffer[i]);
            }
            analog_thread.inject_batch(analog_buffer);
            batch_idx = 0;
        }
    }
};
```

| 同步策略 | 同步频率 | 适用场景 | 性能影响 |
|---------|---------|---------|---------|
| 每周期同步 | 最高 | PLL等紧耦合环路 | 严重拖累数字侧 |
| 每N周期批量 | 中 | 一般混合信号模块 | 推荐默认策略 |
| 事件触发 | 最低 | 弱耦合、事件稀疏 | 最优，需设计保证 |

### 5.4 DPI-C调用AMI模型的线程安全

IBIS-AMI模型以C/C++ DLL形式提供。多线程RTL仿真器通过DPI-C调用时需注意：

```cpp
// 方案A：每个线程维护独立AMI实例（无锁，内存开销大）
class PerThreadAMI {
    std::vector<IBIS_AMI_Model*> per_thread_models;
    
    void init(int num_threads) {
        for (int i = 0; i < num_threads; ++i) {
            per_thread_models[i] = ami_model_create("rx_ami.dll");
        }
    }
};

// 方案B：单例序列化（内存小，可能成为瓶颈）
class SerializedAMI {
    IBIS_AMI_Model* model;
    std::mutex ami_mutex;
    
    void process(const Waveform& in, Waveform& out) {
        std::lock_guard<std::mutex> lock(ami_mutex);
        model->process(in, out);
    }
};
```

> **推荐**：对于眼图统计等可并行场景，采用方案A；对于需要共享自适应状态的CDR模型，采用方案B。

### 5.5 综合检查清单

在将混合信号仿真集成到多线程RTL仿真器时，逐条确认：

- [ ] 数字RTL部分已完全多线程化，不因为模拟求解而空转
- [ ] 模拟部分使用FastSPICE多核分区，电路拓扑分区已优化
- [ ] 跨域同步采用批量策略（每N周期），非每周期lock-step
- [ ] a2d/d2a转换已批量处理，减少模拟引擎唤醒次数
- [ ] IBIS-AMI模型通过DPI-C调用时，线程安全策略已明确（per-thread实例或序列化）
- [ ] 数字均衡算法（FFE、DFE、CDR）在RTL侧充分验证，模拟前端用行为模型
- [ ] 眼图/浴盆曲线统计在后台线程异步聚合，不阻塞主仿真
- [ ] 混合信号回归测试使用不同抽象层级（SPICE→AMS→数字行为级），按需降级
- [ ] 模拟求解的收敛失败有容错机制，不导致整体仿真挂起
- [ ] FastSPICE的多速率分区思想已借鉴到数字侧（不同时钟域独立推进）

---

## 参考来源

- [source-mixed-signal](source-mixed-signal.md) — Verilog-AMS三种协同仿真方法、a2d/d2a接口、Digital-on-Top架构、FastSPICE多核
- [source-spice-interface](source-spice-interface.md) — SPICE核心算法（MNA+Newton-Raphson）、FastSPICE四大加速技术、三种同步策略（Lock-step/Relaxation/Backtracking）
- [source-phy-serdes](source-phy-serdes.md) — IBIS-AMI框架、112G PAM-4架构、统计/时域仿真、眼图/浴盆曲线、PySerDes

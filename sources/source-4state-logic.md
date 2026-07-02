---
title: 4-State Logic Implementation in RTL Simulation
description: 4-state logic (0/1/X/Z) encoding, truth table optimization, resolution functions, and X-propagation strategies in Verilog/SystemVerilog simulators
source_url: "https://github.com/ucsc-vama/essent"
source_type: "paper"
author: "Stuart Sutherland, Scott Beamer, Kyoungmin Park"
date: "2013-2024"
tags: ["4-state-logic", "X-propagation", "resolution-function", "simulation-encoding", "SystemVerilog"]
keywords: ["4-state logic", "Verilog X", "logic type", "truth table", "inertial delay", "transport delay", "Z state", "multi-driver resolution"]
capture_date: "2026-07-03"
---

# 4-State Logic 实现与优化

## 来源

- **URL (Sutherland X-optimism/pessimism paper)**: https://sutherland-hdl.com/papers/2013-DVCon_In-love-with-my-X_paper.pdf
- **URL (Samsung 4-State Emulation, DVCon 2024)**: https://dvcon-proceedings.org/wp-content/uploads/Emulation-Moves-Into-4-State-Logic-and-Real-Number-Modeling-.pdf
- **URL (Arm SoC 四值逻辑)**: https://armkeil.blob.core.windows.net/developer/Files/pdf/ebook/arm-modern-soc-design-on-arm.pdf
- **URL (Cambridge SoC Notes)**: https://www.cl.cam.ac.uk/teaching/1617/SysOnChip/materials.d/socdam-notes-revC.pdf
- **类型**: paper / doc / conference
- **作者**: Stuart Sutherland (Sutherland HDL), Kyoungmin Park (Samsung), Scott Beamer (UCSC)
- **日期**: 2013 / 2024

## 摘要

Verilog 与 SystemVerilog 使用四值逻辑系统（0, 1, X, Z）进行 RTL 仿真。X 代表「未知/未初始化/无法确定」，Z 代表「高阻态」。相比二值逻辑（0/1），四值逻辑能捕获初始化缺陷、总线冲突等隐藏 bug，但会带来 2-4 倍的内存开销与运行时性能损失。本文档整理四值逻辑的编码实现、真值表优化、多驱动 resolution function、X 传播策略（optimism vs pessimism）以及仿真器中的性能折中方案。

## 关键要点

### 1. 四值逻辑的语义与用途

| 值 | 含义 | 应用场景 |
|---|---|---|
| 0 | 逻辑低 | 确定的低电平 |
| 1 | 逻辑高 | 确定的高电平 |
| X | 未知 / 未初始化 / 不确定 | 仿真器无法预测硬件行为；或综合中的 don't-care |
| Z | 高阻态 / 未驱动 | 三态总线、开漏输出、未连接端口 |

SystemVerilog 的 `logic` 类型是 4-state，`bit` 是 2-state。RTL 设计推荐使用 `logic` 以捕获初始化问题；testbench 中可用 `bit` 提升性能。

```systemverilog
// 4-state: 可检测 X/Z
logic [7:0] rtl_data;   // 默认值为 X

// 2-state: 更快，但 X 被静默转为 0
bit [7:0]  tb_data;     // 默认值为 0
int        counter;     // 2-state
```

### 2. 编码实现：双比特编码

每个逻辑值可用 2-bit 编码存储，常见方案如下（不同仿真器实现略有差异）：

| 值 | 编码 (v1, v0) | 说明 |
|---|---|---|
| 0 | 00 | 明确低电平 |
| 1 | 01 | 明确高电平 |
| X | 10 | 未知（结果未知） |
| Z | 11 | 高阻态（未驱动） |

**C/C++ 实现示例（仿真器内核）**：

```c
// 2-bit 编码，低位表示值，高位表示有效/已知标志
// 编码：00=0, 01=1, 10=X, 11=Z
enum Logic4 { LOGIC_0 = 0, LOGIC_1 = 1, LOGIC_X = 2, LOGIC_Z = 3 };

inline Logic4 and4(Logic4 a, Logic4 b) {
    // 真值表查找：4x4 = 16 项，可用 16-byte LUT
    static const uint8_t lut[4][4] = {
        //        0       1       X       Z
        /* 0 */ {LOGIC_0, LOGIC_0, LOGIC_0, LOGIC_0},
        /* 1 */ {LOGIC_0, LOGIC_1, LOGIC_X, LOGIC_X},
        /* X */ {LOGIC_0, LOGIC_X, LOGIC_X, LOGIC_X},
        /* Z */ {LOGIC_0, LOGIC_X, LOGIC_X, LOGIC_X}
    };
    return lut[a][b];
}

// 对于多位向量，按位展开并查表
uint64_t and_vec(uint64_t a_val, uint64_t a_known,
                 uint64_t b_val, uint64_t b_known) {
    // 0: val=0, known=1
    // 1: val=1, known=1
    // X: known=0 (val 可为任意)
    // Z: known=0 (val 可为任意)
    uint64_t known = a_known & b_known;
    uint64_t val   = (a_val & b_val) & known;
    return val;  // 简化示意，实际需要区分 X 和 Z
}
```

### 3. 真值表与运算优化

**Bitwise OR 真值表**（Verilog 标准）：

| \|\| | 0 | 1 | x | z |
|---|---|---|---|---|
| 0 | 0 | 1 | x | x |
| 1 | 1 | 1 | 1 | 1 |
| x | x | 1 | x | x |
| z | x | 1 | x | x |

**Bitwise AND 真值表**：

| & | 0 | 1 | x | z |
|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 |
| 1 | 0 | 1 | x | x |
| x | 0 | x | x | x |
| z | 0 | x | x | x |

**优化策略**：

- **LUT 查表**：单 bit 运算用 16-byte 查找表，避免分支判断
- **SIMD 并行**：对 64-bit 向量，使用 2-bit 交错编码，利用 AVX2/NEON 一次处理 32 个 bit
- **2-state fast path**：如果信号已确认不含 X/Z，回退到布尔运算（&、|）提升速度

### 4. 多驱动 Resolution Function

当 net 被多个驱动源驱动时（如双向总线），需要 resolution function 决定最终值。Verilog 使用**七级强度模型**（7-level drive strength）：

| Strength Name | Level | 说明 |
|---|---|---|
| supply | 7 | 电源级驱动 |
| strong | 6 | 强驱动（默认门级） |
| pull | 5 | 上拉/弱强驱动 |
| large | 4 | 电容级（已弃用） |
| weak | 3 | 弱驱动 |
| medium | 2 | 中等电容 |
| small | 1 | 小电容 |
| highz | 0 | 高阻态 |

**Resolution 规则**：
- 同强度的 0 与 1 冲突 → 解析为 X
- 不同强度时，高强度胜过低强度
- Z 不参与驱动（被忽略）

```c
// 简化的 resolution 逻辑（2-bit 值 + 3-bit 强度）
struct ValStrength { uint8_t val; uint8_t strength; };

ValStrength resolve(ValStrength a, ValStrength b) {
    if (a.val == LOGIC_Z) return b;
    if (b.val == LOGIC_Z) return a;
    if (a.val == b.val) return (a.strength > b.strength) ? a : b;
    if (a.strength > b.strength) return a;
    if (b.strength > a.strength) return b;
    return {LOGIC_X, 6}; // 同强度冲突 → X
}
```

### 5. X-Optimism vs X-Pessimism

Sutherland 2013 DVCon 论文详细讨论了 X 传播的两种偏差：

- **X-Optimism（乐观）**：仿真器在条件判断中把 X 当作「假」，导致隐藏 bug。例如 `if (sel) y = a; else y = b;` 当 `sel = X` 时走 else 分支，可能掩盖错误。
- **X-Pessimism（悲观）**：门级仿真中，X 输入导致 X 输出，即使实际硬件可能确定输出。过于悲观会导致无法收敛的验证。

**2-state 仿真 vs 4-state 仿真**：

| 特性 | 2-state | 4-state |
|---|---|---|
| 内存占用 | 低（1 bit/信号） | 高（2 bit/信号 + 强度） |
| 运行速度 | 快（无需查表/编码） | 慢（2-4x） |
| 初始化检测 | 无法检测 | 可检测未初始化 X |
| 总线冲突 | 可能错误解析 | 正确解析为 X |
| 综合匹配度 | 与综合行为更接近 | 可能有 optimism/pessimism 差异 |

### 6. Samsung 4-State Emulation 实现（DVCon 2024）

Samsung 在硬件仿真器（Palladium/Veloce 类）中实现了 4-state 支持，关键思路：

- **RTL 表示不变**：4-state 处理在实现层完成，不修改 RTL 源码
- **X-resolve 逻辑**：`Xresolve(a, b) := a if a === b else X`
- **Memory 实现**：用一对物理 memory 存储 4-state 值（2-bit 编码 0/1/X），Z 在逻辑上通过其他方式处理
- **CAT mode**：在处理器粒度的计算单元中，最多 4 输入的 X 计算在 synthesized netlist 上完成

## 对 RTL 仿真器多线程化的启示

1. **4-state 向量运算可 SIMD 化**：将 2-bit 编码打包到 64-bit/128-bit 寄存器，使用 AVX2 或 NEON 指令一次处理 32/64 个 bit，可抵消 4-state 带来的性能损失
2. **Activity factor 与 4-state 联合优化**：若某 partition 的输入全部确定（无 X），可切换至 2-state fast path，ESSENT 的 O3 优化已验证此思路有效
3. **Resolution function 在多线程中需原子化**：多驱动 net 的 resolution 涉及跨线程信号，需使用 lock-free atomic 或每线程局部缓存 + 合并阶段
4. **Memory footprint 翻倍**：4-state 使状态快照大小翻倍，影响 checkpoint/replay 与分布式仿真的带宽需求

## 原文摘录

> "Encoding 4-state values for each bit, along with strength values for net types, requires much more memory than just storing simple 2-state values. Improves simulation run-time performance, since 4-state encoding, decoding, and operations do not need to be performed."
> — Stuart Sutherland, *I'm Still In Love With My X*, DVCon 2013

> "RTL and Gate representation is unchanged for 4-state. Still emulating the same design as 2-state. X handling is done in the implementation and not written into the RTL."
> — Kyoungmin Park, Samsung Semiconductor, DVCon US 2024

> "In a four-value logic system each net (wire or signal), at a particular time, has one of the following logic values: 0 logic zero, 1 logic one, Z high impedance, X uncertain."
> — ARM, *Modern System-on-Chip Design on Arm*

## 相关链接

- [Sutherland HDL - X-Optimism Paper](https://sutherland-hdl.com/papers/2013-DVCon_In-love-with-my-X_paper.pdf)
- [Samsung DVCon 2024 - 4-State Emulation](https://dvcon-proceedings.org/wp-content/uploads/Emulation-Moves-Into-4-State-Logic-and-Real-Number-Modeling-.pdf)
- [ChipVerify - SystemVerilog logic](https://chipverify.com/systemverilog/systemverilog-data-types-logic-bit)
- [VLSI Verification - 4-State vs 2-State](https://vlsiverification.net/tutorials/sv/datatypes-basics.html)
- [Cambridge SoC Notes - 4-value Logic](https://www.cl.cam.ac.uk/teaching/1617/SysOnChip/materials.d/socdam-notes-revC.pdf)
- [ARM Modern SoC Design (PDF)](https://armkeil.blob.core.windows.net/developer/Files/pdf/ebook/arm-modern-soc-design-on-arm.pdf)

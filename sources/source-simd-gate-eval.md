---
title: SIMD 在门级（Gate-Level）评估中的具体实现
description: 基于 AVX2/AVX-512 的位向量运算，展示如何在 RTL 门级仿真器中使用 SIMD 指令并行评估 AND/OR/XOR/NOT 门
source_url: "https://markaicode.com/simd-programming-cpp23-avx512/"
source_type: "blog"
author: "Mark AI Code / Daniel Kusswurm / Intel"
date: "2022-2025"
tags: ["SIMD", "AVX2", "AVX-512", "gate-evaluation", "bit-vector", "RTL"]
keywords: ["AVX2", "AVX-512", "_mm256_and_si256", "_mm512_and_epi64", "bitwise SIMD", "parallel gate evaluation", "bit-vector simulation"]
capture_date: "2026-07-03"
---

# SIMD 在门级（Gate-Level）评估中的具体实现

## 来源

- URL: https://markaicode.com/simd-programming-cpp23-avx512/
- 类型: blog
- 作者: Mark AI Code
- 日期: 2025-04

- URL: https://arxiv.org/html/2512.09157
- 类型: paper
- 作者: William B. Langdon et al.
- 日期: 2025-11

- URL: https://blog.csdn.net/CodeTrick/article/details/153180074
- 类型: blog
- 作者: CSDN CodeTrick
- 日期: 2025-10

- URL: https://link.springer.com/chapter/10.1007/978-1-4842-7918-2_8
- 类型: book-chapter
- 作者: Daniel Kusswurm
- 日期: 2022

## 摘要

SIMD（单指令多数据）指令集天然适合门级仿真器的位向量（bit-vector）评估模型。在 RTL 仿真中，每个信号在 N 个测试向量上可表示为 N 位宽的位向量；使用 AVX2（256-bit）一次可并行处理 256 个逻辑值，AVX-512（512-bit）则可处理 512 个。Intel AVX-512 的 `__m512i` 类型与 `_mm512_and_epi64`、`_mm512_or_epi64`、`_mm512_xor_epi64` 等内在函数，可直接对应到逻辑门的并行评估。GPengine 论文报告从 SSE 256 迁移到 AVX-512 后，性能达到 3.5 Giga GP/s，相比 SSE 版本提升 3.9 倍。对于 RTL 仿真器，这意味着在单核上即可同时评估 512 个输入向量下的同一逻辑门。

## 关键要点

- **AVX2 位运算基础**: `_mm256_and_si256`、`_mm256_or_si256`、`_mm256_xor_si256`、`_mm256_andnot_si256` 对应 AND/OR/XOR/NOT 门，一次处理 256 bit（4×64-bit 或 8×32-bit）。
- **AVX-512 的扩展**: `_mm512_and_epi64`、`_mm512_or_epi64`、`_mm512_xor_epi64` 将位宽扩展至 512-bit，同时提供 mask 寄存器（`__mmask8`/`__mmask16`）用于条件评估（如 tri-state 或 mux）。
- **门级评估映射**: 将每个门的一个输入在 M 个测试向量上的取值打包为一个 `__m512i`（512 个 1-bit 值），则一个时钟周期的评估简化为一次 SIMD 位运算。
- **编译器 flags**: 使用 `-mavx2`（GCC/Clang）或 `-mavx512f -mavx512dq -mavx512bw`（AVX-512 完整支持）来生成目标代码；`-march=native` 在支持 AVX-512 的机器上自动启用。
- **内存对齐**: SIMD load/store 对 32/64 字节对齐要求严格。使用 `_mm_malloc(size, 64)` 分配并配合 `_mm512_load_si512`（对齐）而非 `_mm512_loadu_si512`（非对齐）可获得最佳性能。
- **向量中嵌套向量 (Vector-within-vector)**: AVX-512 的 32-bit lane 粒度允许每个 SIMD lane 执行独立的子向量操作，例如 16 个 4×8-bit 的 RGB 打包操作。对于门级仿真，这可将 16 组 32-bit 位向量同时评估。

## 对 RTL 仿真器多线程化的启示

1. **单核 SIMD 是线程级并行的前级**：在启动多线程之前，应先用 SIMD 将单核利用率打满。门级仿真中，一个逻辑门在 N 个测试向量上的 N 次独立评估，天然是 SIMD 的完美用例。
2. **事件队列可按向量宽度分块**：将仿真事件按 256/512 的倍数批量处理，每批内部用 SIMD 同时推进。这样可减少事件队列的锁竞争次数。
3. **FF 和 LUT 的位向量模型**：时序元件（D-FF）在 SIMD 模型下变为对 512-bit 向量整体的移位/锁存操作；组合 LUT 可预先将真值表映射为 SIMD 的查找序列。
4. **Mask 寄存器 = 条件信号**：AVX-512 的 mask 寄存器可直接对应 RTL 中的 `if (enable) q <= d;` 这种条件赋值。`_mm512_mask_and_epi64` 等 mask 操作允许在不引入分支的情况下实现 gated clock 或 latch 行为。
5. **与多线程结合**：可在多线程间按 gate 分组并行，每个线程内部再使用 SIMD 按 test vector 分块。两层并行（thread + SIMD）最大化硬件利用率。

## 原文摘录

> "AVX-512 instructions can process 16 single-precision floating-point operations in parallel... The peak speed of the evolved GPengine interpreter is 3.5 billion GP operations per second (3.5 Giga GP/s), i.e. 3.9 times faster than the SSE 256 version." — Langdon et al., Improving a Parallel C++ Intel AVX-512 SIMD Linear Genetic Programming Interpreter

> "Vector-within-vector means each SIMD lane executes a small vector operation independently from the other lanes... with AVX-512 the whole instruction becomes a 16×4×8-bit vector-within-vector instruction." — Intel Community, AVX-512 Discussion

> "AVX-512 adds things that make it highly suitable for vectorizing generic loops. A fast gather operation is essential when you're doing any indexed addressing, predication masks keep branches efficient, broadcast allows to have scalar constants." — Intel Community

## 核心代码示例：使用 AVX2 并行评估 256 个逻辑门

```cpp
#include <immintrin.h>
#include <cstdint>
#include <vector>
#include <iostream>

// AVX2 评估：256-bit 寄存器，一次处理 256 个 1-bit 逻辑值
// （以下使用 4 个 64-bit 通道打包）

struct SimdGateAVX2 {
    __m256i inputs[2];   // 两个输入，各 256-bit
    __m256i output;      // 输出 256-bit
};

// 并行 AND 门评估：256 个输入向量同时计算
inline __m256i eval_and_avx2(const __m256i& a, const __m256i& b) {
    return _mm256_and_si256(a, b);
}

// 并行 OR 门评估
inline __m256i eval_or_avx2(const __m256i& a, const __m256i& b) {
    return _mm256_or_si256(a, b);
}

// 并行 XOR 门评估
inline __m256i eval_xor_avx2(const __m256i& a, const __m256i& b) {
    return _mm256_xor_si256(a, b);
}

// 并行 NOT 门评估（AND NOT）
inline __m256i eval_not_avx2(const __m256i& a) {
    __m256i all_ones = _mm256_set1_epi64x(-1);
    return _mm256_andnot_si256(a, all_ones);  // ~a & 0xFF...FF
}

// 批量评估：一个 NAND 门在 256 个 test vectors 上的结果
void eval_nand_gate_batch_avx2(const uint64_t* a, const uint64_t* b,
                                uint64_t* out, size_t num_vectors) {
    // 256-bit = 4×64-bit，每次处理 4 个 64-bit 块 = 256 个逻辑值
    size_t simd_chunks = num_vectors / 256;
    for (size_t i = 0; i < simd_chunks; i++) {
        __m256i va = _mm256_loadu_si256((__m256i*)(a + i * 4));
        __m256i vb = _mm256_loadu_si256((__m256i*)(b + i * 4));
        __m256i vand = _mm256_and_si256(va, vb);
        __m256i vnot = eval_not_avx2(vand);  // NAND = NOT (A AND B)
        _mm256_storeu_si256((__m256i*)(out + i * 4), vnot);
    }
    // 尾部处理（标量回退）
    for (size_t i = simd_chunks * 256; i < num_vectors; i++) {
        out[i] = ~(a[i] & b[i]);
    }
}
```

## 核心代码示例：使用 AVX-512 并行评估 512 个逻辑门

```cpp
#include <immintrin.h>
#include <cstdint>
#include <vector>

// AVX-512 评估：512-bit 寄存器，一次处理 512 个 1-bit 逻辑值
// （8×64-bit 通道打包）

// 编译命令：
// g++ -O3 -march=native -mavx512f -mavx512dq -mavx512bw -o gate_sim gate_sim.cpp

// 并行 AND 门评估：512 个输入向量同时计算
inline __m512i eval_and_avx512(const __m512i& a, const __m512i& b) {
    return _mm512_and_epi64(a, b);
}

// 并行 OR 门评估
inline __m512i eval_or_avx512(const __m512i& a, const __m512i& b) {
    return _mm512_or_epi64(a, b);
}

// 并行 XOR 门评估
inline __m512i eval_xor_avx512(const __m512i& a, const __m512i& b) {
    return _mm512_xor_epi64(a, b);
}

// 并行 NOT 门评估
inline __m512i eval_not_avx512(const __m512i& a) {
    __m512i all_ones = _mm512_set1_epi64(-1);
    return _mm512_andnot_epi64(a, all_ones);
}

// 带条件 mask 的 AND：实现 enable 信号控制
// 当 enable_mask 对应位为 1 时，输出 a & b；否则输出 0
inline __m512i eval_and_masked_avx512(const __m512i& a, const __m512i& b,
                                       __mmask8 enable_mask) {
    return _mm512_mask_and_epi64(_mm512_setzero_si512(), enable_mask, a, b);
}

// 批量评估：一个 MUX2 门在 512 个 test vectors 上的结果
// MUX2(sel, a, b) = sel ? a : b
// 使用 AVX-512 mask 操作实现无分支 MUX
void eval_mux2_gate_batch_avx512(const uint64_t* sel, const uint64_t* a,
                                   const uint64_t* b, uint64_t* out,
                                   size_t num_vectors) {
    size_t simd_chunks = num_vectors / 512;
    for (size_t i = 0; i < simd_chunks; i++) {
        __m512i vsel = _mm512_loadu_si512((__m512i*)(sel + i * 8));
        __m512i va   = _mm512_loadu_si512((__m512i*)(a + i * 8));
        __m512i vb   = _mm512_loadu_si512((__m512i*)(b + i * 8));

        // 生成 mask：sel 的每个 64-bit lane 非零则 mask=1
        __mmask8 mask = _mm512_test_epi64_mask(vsel, vsel);

        // result = mask ? va : vb
        __m512i result = _mm512_mask_mov_epi64(vb, mask, va);
        _mm512_storeu_si512((__m512i*)(out + i * 8), result);
    }
    // 尾部标量处理
    for (size_t i = simd_chunks * 512; i < num_vectors; i++) {
        out[i] = sel[i] ? a[i] : b[i];
    }
}

// 完整仿真器核心：多门级联评估（组合逻辑块）
// 假设 netlist 已拓扑排序，每个 gate 的 inputs 指向先前 gate 的 output
void eval_combinational_block_avx512(
    const std::vector<uint64_t*>& gate_inputs,  // 每门输入指针
    const std::vector<int>& gate_types,          // 0=AND, 1=OR, 2=XOR, 3=NOT
    std::vector<uint64_t*>& gate_outputs,
    size_t num_vectors) {

    size_t simd_chunks = (num_vectors + 511) / 512;  // 向上取整

    for (size_t g = 0; g < gate_types.size(); g++) {
        uint64_t* in0 = gate_inputs[g * 2];
        uint64_t* in1 = gate_inputs[g * 2 + 1];
        uint64_t* out = gate_outputs[g];

        for (size_t chunk = 0; chunk < simd_chunks; chunk++) {
            __m512i va = _mm512_loadu_si512((__m512i*)(in0 + chunk * 8));
            __m512i vb = _mm512_loadu_si512((__m512i*)(in1 + chunk * 8));
            __m512i vout;

            switch (gate_types[g]) {
                case 0: vout = eval_and_avx512(va, vb); break;
                case 1: vout = eval_or_avx512(va, vb); break;
                case 2: vout = eval_xor_avx512(va, vb); break;
                case 3: vout = eval_not_avx512(va); break;  // NOT 忽略 in1
                default: vout = _mm512_setzero_si512(); break;
            }
            _mm512_storeu_si512((__m512i*)(out + chunk * 8), vout);
        }
    }
}
```

## 编译命令与性能测试

```bash
# AVX2 版本编译
g++ -O3 -march=native -mavx2 -DNDEBUG -o gate_sim_avx2 gate_sim.cpp

# AVX-512 版本编译（需要 Skylake-X+ 或 Ice Lake+）
g++ -O3 -march=native -mavx512f -mavx512dq -mavx512bw -DNDEBUG \
    -o gate_sim_avx512 gate_sim.cpp

# 带 LTO 的极致优化
g++ -O3 -march=native -mavx512f -mavx512dq -mavx512bw -flto \
    -DNDEBUG -o gate_sim_avx512_lto gate_sim.cpp
```

## SIMD 寄存器宽度与门级并行度对照表

| ISA | 寄存器宽度 | 64-bit 通道数 | 1-bit 逻辑值并行数 | 典型 CPU |
|-----|-----------|--------------|-------------------|---------|
| SSE2 | 128-bit | 2 | 128 | 任何 x86-64 |
| AVX2 | 256-bit | 4 | 256 | Haswell+ (2013+) |
| AVX-512 | 512-bit | 8 | 512 | Skylake-X+ / Ice Lake+ / Zen 4+ |

## 相关链接

- [Mark AI Code: SIMD Programming in C++23](https://markaicode.com/simd-programming-cpp23-avx512/)
- [arXiv: Improving a Parallel C++ Intel AVX-512 SIMD Linear Genetic Programming Interpreter](https://arxiv.org/html/2512.09157)
- [CSDN: 如何用 SIMD 指令集加速 C++ 数据处理](https://blog.csdn.net/CodeTrick/article/details/153180074)
- [Springer: AVX-512 C++ Programming Part 2](https://link.springer.com/chapter/10.1007/978-1-4842-7918-2_8)
- [Intel Intrinsics Guide](https://www.intel.com/content/www/us/en/docs/intrinsics-guide/index.html)
- [GitHub: Simd-1 C++ image processing library](https://github.com/clayne/Simd-1)

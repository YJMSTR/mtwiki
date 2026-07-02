---
title: "编译器优化与SIMD实现"
description: "GCC/Clang编译器优化flag（-O3/-Ofast/-march=native/-flto/PGO）、AVX2/AVX-512 SIMD门评估intrinsics、自动向量化pragma与restrict用法的完整代码示例与RTL仿真器适配方案"
source_refs: ["source-compiler-flags", "source-simd-gate-eval", "source-auto-vectorization"]
author: "Wiki写作_最终聚焦"
date: "2025-07-20"
tags: ["compiler-optimization", "SIMD", "AVX2", "AVX-512", "auto-vectorization", "LTO", "PGO", "RTL仿真器"]
---

# 编译器优化与SIMD实现

## 1. 编译器Flag

### 1.1 优化级别对比

| 优化级别 | 包含内容 | 适用场景 | RTL仿真器建议 |
|---------|---------|---------|--------------|
| `-O0` | 无优化，可调试 | 调试 | 仅debug使用 |
| `-O1` | 基本优化，降低代码大小 | 快速编译 | 不推荐 |
| `-O2` | 几乎所有支持的优化算法 | 通用发布 | 基线选项 |
| `-O3` | `-O2` + 激进循环展开/向量化/内联 | 性能关键 | **推荐基线** |
| `-Ofast` | `-O3` + `-ffast-math`等不标准优化 | 极致性能 | 验证后用于hottest path |
| `-Og` | 与`-g`兼容的优化 | 调试优化平衡 | 不推荐用于release |

### 1.2 关键Flag详解

| Flag | 作用 | 风险 | RTL仿真器适用性 |
|------|------|------|----------------|
| `-O3` | 激进循环展开、向量化、内联 | 代码膨胀、编译时间增加 | **强烈推荐** |
| `-Ofast` | `-O3` + `-ffast-math` | 牺牲IEEE 754兼容性 | 整数逻辑为主，**风险极低** |
| `-march=native` | 启用本机CPU全部ISA（AVX2/AVX-512） | 不可在其他CPU运行 | **强烈推荐**（CI时指定具体架构） |
| `-flto` | 链接时优化，跨TU内联 | 编译时间显著增加 | **强烈推荐** |
| `-fomit-frame-pointer` | 释放一个通用寄存器 | 调试时堆栈回溯困难 | 现代x86-64默认已启用 |
| `-funroll-loops` | 手动循环展开 | 代码膨胀 | 对门级事件循环可能有效 |
| `-DNDEBUG` | 禁用assert | 可能隐藏bug | Release构建必须启用 |

### 1.3 PGO（Profile-Guided Optimization）

**三阶段流程**：
```bash
# 阶段1：生成profile数据
$ g++ -O3 -march=native -fprofile-generate -DNDEBUG -o rtl_sim main.cpp
$ ./rtl_sim --run-representative-workload  # 运行代表性负载

# 阶段2：使用profile重新编译
$ g++ -O3 -march=native -fprofile-use -DNDEBUG -o rtl_sim main.cpp
```

**RTL仿真器PGO收益极高**：门级仿真器的热点极不均匀（时钟树、复位逻辑被反复执行），通过PGO可让编译器将hottest gate eval函数内联到scheduler循环中，减少调用开销。

### 1.4 Benchmark数据

> "GCC 12.1 was the auto-vectorizer enabled when -O2 is specified... The most notable improvements were a 55% improvement on the 625.x264_s benchmark and a 20% improvement on the 638.imagick_s benchmark." — Red Hat Developer

> "Unlike the GCC 11 tests where the `-flto` runs actually were coming in slightly slower overall, that wasn't the case with this Clang benchmarking." — Phoronix, Clang 12优化级别评测

### 1.5 完整CMake配置

```cmake
# CMakeLists.txt中的RTL仿真器Release配置
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 通用Release flags
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -DNDEBUG -fomit-frame-pointer")

# 架构特化（CI构建时应指定具体-march=xxx而非native）
set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -march=native")

# LTO
set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -flto=auto")
set(CMAKE_EXE_LINKER_FLAGS_RELEASE "${CMAKE_EXE_LINKER_FLAGS_RELEASE} -flto=auto")

# PGO阶段1: 生成profile
# set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -fprofile-generate")
# PGO阶段2: 使用profile
# set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -fprofile-use")
```

### 1.6 推荐编译命令

```bash
# GCC推荐组合（Release构建）
g++ -O3 -march=native -flto=auto -fomit-frame-pointer \
    -DNDEBUG -o rtl_sim main.cpp gate_eval.cpp scheduler.cpp

# GCC + PGO（最终优化）
g++ -O3 -march=native -flto=auto -fomit-frame-pointer \
    -fprofile-use -DNDEBUG -o rtl_sim main.cpp gate_eval.cpp scheduler.cpp

# Clang推荐组合
clang++ -O3 -march=native -flto=auto -fomit-frame-pointer \
    -DNDEBUG -o rtl_sim main.cpp gate_eval.cpp scheduler.cpp
```

---

## 2. SIMD门评估

### 2.1 AVX2位运算基础（256-bit）

```cpp
#include <immintrin.h>
#include <cstdint>

struct SimdGateAVX2 {
    __m256i inputs[2];   // 两个输入，各256-bit
    __m256i output;      // 输出256-bit
};

// 并行AND门评估：256个输入向量同时计算
inline __m256i eval_and_avx2(const __m256i& a, const __m256i& b) {
    return _mm256_and_si256(a, b);
}

// 并行OR门评估
inline __m256i eval_or_avx2(const __m256i& a, const __m256i& b) {
    return _mm256_or_si256(a, b);
}

// 并行XOR门评估
inline __m256i eval_xor_avx2(const __m256i& a, const __m256i& b) {
    return _mm256_xor_si256(a, b);
}

// 并行NOT门评估（AND NOT）
inline __m256i eval_not_avx2(const __m256i& a) {
    __m256i all_ones = _mm256_set1_epi64x(-1);
    return _mm256_andnot_si256(a, all_ones);  // ~a & 0xFF...FF
}

// 批量评估：一个NAND门在256个test vectors上的结果
void eval_nand_gate_batch_avx2(const uint64_t* a, const uint64_t* b,
                                  uint64_t* out, size_t num_vectors) {
    // 256-bit = 4×64-bit，每次处理4个64-bit块 = 256个逻辑值
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

### 2.2 AVX-512位运算（512-bit）

```cpp
#include <immintrin.h>
#include <cstdint>

// 编译命令：
// g++ -O3 -march=native -mavx512f -mavx512dq -mavx512bw -DNDEBUG -o gate_sim gate_sim.cpp

// 并行AND门评估：512个输入向量同时计算
inline __m512i eval_and_avx512(const __m512i& a, const __m512i& b) {
    return _mm512_and_epi64(a, b);
}

// 并行OR门评估
inline __m512i eval_or_avx512(const __m512i& a, const __m512i& b) {
    return _mm512_or_epi64(a, b);
}

// 并行XOR门评估
inline __m512i eval_xor_avx512(const __m512i& a, const __m512i& b) {
    return _mm512_xor_epi64(a, b);
}

// 并行NOT门评估
inline __m512i eval_not_avx512(const __m512i& a) {
    __m512i all_ones = _mm512_set1_epi64(-1);
    return _mm512_andnot_epi64(a, all_ones);
}

// 带条件mask的AND：实现enable信号控制
inline __m512i eval_and_masked_avx512(const __m512i& a, const __m512i& b,
                                       __mmask8 enable_mask) {
    return _mm512_mask_and_epi64(_mm512_setzero_si512(), enable_mask, a, b);
}

// 批量评估：一个MUX2门在512个test vectors上的结果
// MUX2(sel, a, b) = sel ? a : b
void eval_mux2_gate_batch_avx512(const uint64_t* sel, const uint64_t* a,
                                   const uint64_t* b, uint64_t* out,
                                   size_t num_vectors) {
    size_t simd_chunks = num_vectors / 512;
    for (size_t i = 0; i < simd_chunks; i++) {
        __m512i vsel = _mm512_loadu_si512((__m512i*)(sel + i * 8));
        __m512i va   = _mm512_loadu_si512((__m512i*)(a + i * 8));
        __m512i vb   = _mm512_loadu_si512((__m512i*)(b + i * 8));

        // 生成mask：sel的每个64-bit lane非零则mask=1
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
void eval_combinational_block_avx512(
    const std::vector<uint64_t*>& gate_inputs,
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
                case 3: vout = eval_not_avx512(va); break;
                default: vout = _mm512_setzero_si512(); break;
            }
            _mm512_storeu_si512((__m512i*)(out + chunk * 8), vout);
        }
    }
}
```

### 2.3 SIMD寄存器宽度与门级并行度对照表

| ISA | 寄存器宽度 | 64-bit通道数 | 1-bit逻辑值并行数 | 典型CPU |
|-----|-----------|-------------|-------------------|---------|
| SSE2 | 128-bit | 2 | 128 | 任何x86-64 |
| AVX2 | 256-bit | 4 | 256 | Haswell+ (2013+) |
| AVX-512 | 512-bit | 8 | 512 | Skylake-X+ / Ice Lake+ / Zen 4+ |

### 2.4 编译命令与寄存器宽度

```bash
# AVX2版本编译
g++ -O3 -march=native -mavx2 -DNDEBUG -o gate_sim_avx2 gate_sim.cpp

# AVX-512版本编译（需要Skylake-X+或Ice Lake+）
g++ -O3 -march=native -mavx512f -mavx512dq -mavx512bw -DNDEBUG \
    -o gate_sim_avx512 gate_sim.cpp

# 带LTO的极致优化
g++ -O3 -march=native -mavx512f -mavx512dq -mavx512bw -flto \
    -DNDEBUG -o gate_sim_avx512_lto gate_sim.cpp
```

### 2.5 性能数据

> "The peak speed of the evolved GPengine interpreter is 3.5 billion GP operations per second (3.5 Giga GP/s), i.e. 3.9 times faster than the SSE 256 version." — Langdon et al., AVX-512 SIMD Genetic Programming

---

## 3. 自动向量化

### 3.1 Pragma用法对比

| Pragma | 编译器 | 作用 | 适用场景 |
|--------|--------|------|----------|
| `#pragma omp simd` | GCC/Clang | 强制向量化，使用unlimited cost model | 循环无依赖，确定可向量化 |
| `#pragma GCC ivdep` | GCC | 忽略可能存在的数据依赖 | 编译器保守但程序员确信无依赖 |
| `#pragma clang loop vectorize(enable)` | Clang | 显式启用向量化，可指定vector width | Clang专用 |
| `__restrict` / `__restrict__` | GCC/Clang | 指针级别断言无别名 | 消除运行时别名检查 |

### 3.2 核心代码示例

```cpp
#include <cstdint>
#include <cstddef>

// ============ 场景1：编译器因别名无法向量化 ============

// 原始版本：编译器不知道a/b/c是否重叠，插入运行时检查
void add_scalar(float* a, float* b, float* c, size_t n) {
    for (size_t i = 0; i < n; i++) {
        c[i] = a[i] + b[i];
    }
    // GCC -O2下：可能生成运行时检查，very cheap model可能直接放弃向量化
}

// 改进版本1：使用__restrict消除别名假设
void add_restrict(float* __restrict a,
                  float* __restrict b,
                  float* __restrict c,
                  size_t n) {
    for (size_t i = 0; i < n; i++) {
        c[i] = a[i] + b[i];
    }
    // 编译器可安全假设无别名，-O2下即可向量化
}

// 改进版本2：使用#pragma omp simd强制向量化（GCC/Clang通用）
void add_omp_simd(float* a, float* b, float* c, size_t n) {
    #pragma omp simd
    for (size_t i = 0; i < n; i++) {
        c[i] = a[i] + b[i];
    }
    // 编译：g++ -O2 -fopenmp-simd -march=native ...
}

// 改进版本3：GCC专用ivdep
void add_gcc_ivdep(float* a, float* b, float* c, size_t n) {
    #pragma GCC ivdep
    for (size_t i = 0; i < n; i++) {
        c[i] = a[i] + b[i];
    }
}

// 改进版本4：Clang专用loop hint
void add_clang_hint(float* a, float* b, float* c, size_t n) {
    #pragma clang loop vectorize(enable) interleave(enable)
    for (size_t i = 0; i < n; i++) {
        c[i] = a[i] + b[i];
    }
}
```

### 3.3 RTL门级评估循环向量化友好重构

```cpp
// 编译器友好的门级评估：连续数组 + 无分支 + 无跨迭代依赖
struct GateEvalContext {
    uint64_t* __restrict inputs[2];   // 2-D数组：gate_count × vector_chunks
    uint64_t* __restrict outputs;     // 1-D数组：gate_count × vector_chunks
    uint8_t* gate_types;              // 0=AND, 1=OR, 2=XOR, 3=NOT
    size_t gate_count;
    size_t vector_chunks;             // 每个gate的64-bit块数
};

void eval_gates_simd(GateEvalContext* ctx) {
    // 外层循环：遍历每个gate
    // 内层循环：遍历该gate的所有test vector块
    // 这种结构允许编译器对内层循环进行向量化

    for (size_t g = 0; g < ctx->gate_count; g++) {
        uint64_t* in0 = ctx->inputs[0] + g * ctx->vector_chunks;
        uint64_t* in1 = ctx->inputs[1] + g * ctx->vector_chunks;
        uint64_t* out = ctx->outputs + g * ctx->vector_chunks;

        #pragma omp simd
        for (size_t i = 0; i < ctx->vector_chunks; i++) {
            switch (ctx->gate_types[g]) {
                case 0: out[i] = in0[i] & in1[i]; break;
                case 1: out[i] = in0[i] | in1[i]; break;
                case 2: out[i] = in0[i] ^ in1[i]; break;
                case 3: out[i] = ~in0[i]; break;
            }
        }
    }
}

// 优化版本：消除switch分支，按gate type分块处理
// 这样每个inner loop内gate type恒定，编译器更容易向量化
void eval_gates_simd_optimized(
    const uint64_t* __restrict in0,
    const uint64_t* __restrict in1,
    uint64_t* __restrict out,
    size_t chunks,
    uint8_t gate_type) {

    #pragma omp simd
    for (size_t i = 0; i < chunks; i++) {
        if (gate_type == 0)       out[i] = in0[i] & in1[i];
        else if (gate_type == 1)  out[i] = in0[i] | in1[i];
        else if (gate_type == 2)  out[i] = in0[i] ^ in1[i];
        else                      out[i] = ~in0[i];
    }
}
```

### 3.4 编译器向量化诊断命令

```bash
# ============ GCC ============

# 1. 查看哪些循环被向量化
g++ -O3 -march=native -fopt-info-vec-optimized -o sim sim.cpp

# 2. 查看哪些循环未被向量化及原因
g++ -O3 -march=native -fopt-info-vec-missed -o sim sim.cpp

# 3. 查看所有向量化信息（optimized + missed + note）
g++ -O3 -march=native -fopt-info-vec-all -o sim sim.cpp

# 4. 更详细的向量器决策树（dump到文件）
g++ -O3 -march=native -fdump-tree-vect-details -o sim sim.cpp
# 输出在sim.cpp.XXXt.vect文件中

# 5. 仅启用OpenMP simd pragma（不启用线程并行）
g++ -O2 -fopenmp-simd -march=native -o sim sim.cpp

# 6. 改变cost model（强制更激进的向量化）
g++ -O2 -fvect-cost-model=cheap -march=native -o sim sim.cpp
g++ -O3 -fvect-cost-model=unlimited -march=native -o sim sim.cpp

# 7. 检测misaligned access（向量化崩溃调试）
g++ -O3 -march=native -fsanitize=undefined -o sim sim.cpp

# ============ Clang ============

# 1. 查看成功向量化的循环
clang++ -O3 -march=native -Rpass=loop-vectorize -o sim sim.cpp

# 2. 查看向量化失败的循环
clang++ -O3 -march=native -Rpass-missed=loop-vectorize -o sim sim.cpp

# 3. 查看失败原因分析
clang++ -O3 -march=native -Rpass-analysis=loop-vectorize -o sim sim.cpp

# 4. 强制指定向量宽度和交织因子
clang++ -O3 -mllvm -force-vector-width=8 \
        -mllvm -force-vector-interleave=2 -o sim sim.cpp

# 5. 禁用自动向量化（对比基准）
clang++ -O3 -fno-vectorize -o sim sim.cpp
```

### 3.5 向量化成功条件速查表

| 条件 | 要求 | 常见反例 |
|------|------|---------|
| 无循环携带依赖 | 迭代i不依赖i-1, i+1的结果 | `a[i] = a[i-1] + 1`（前向依赖） |
| 无指针别名 | 输出指针与输入指针不重叠 | `f(&a[1], a)` |
| 连续内存访问 | 数组索引线性递增 | `a[idx[i]]`（scatter/gather） |
| 简单控制流 | 无switch/复杂if/early break | `switch(A[i])`在循环内 |
| 单一数据类型 | 循环内类型一致 | `int`与`char`混用 |
| 已知/可推断的trip count | 循环边界可计算 | `while (p != nullptr)` |

---

## 4. 对多线程RTL仿真器的启示

### 启示1：编译器flag通常能带来10-30%单线程提升

从`-O2`到`-O3 -march=native -flto`的组合，在计算密集型代码上通常能获得10-30%的性能提升。对于RTL仿真器，门级评估的主体是整数位运算，`-Ofast`的`-ffast-math`对其无影响，因此可安全使用`-Ofast`获取最大收益。

### 启示2：SIMD在门级评估中效果有限（控制流不规则）

虽然AVX-512可以一次处理512个逻辑值，但RTL仿真中的门级评估通常面临：
- 不同gate type混合（AND/OR/XOR/NOT/MUX），需要switch/if分支
- 每个gate的输入输出指向不同的内存位置，gather/scatter开销高
- 实际仿真中每个时间步变化的gate数远小于总gate数，SIMD利用率低

**结论**：SIMD在RTL仿真器中的收益主要在「向量化测试向量」场景（一次仿真多个测试向量），而非「单测试向量加速」。

### 启示3：自动向量化在评估循环中最有效

自动向量化对「门级评估循环」（`for each gate: output[i] = AND(input0[i], input1[i])`）最有效，因为：
- 循环体简单，无跨迭代依赖
- 内存访问连续（inputs/outputs为连续数组）
- 数据类型单一（uint64_t）

关键是让编译器「看到」这些特性：使用`restrict`消除别名，用`#pragma omp simd`标记 hottest loop，用诊断命令验证向量化是否成功。

---

## 5. 可操作建议

### 建议1：基线用`-O3 -march=native -DNDEBUG`

```cmake
# CMakeLists.txt最小可行Release配置
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -march=native -DNDEBUG -fomit-frame-pointer")
```

这是RTL仿真器Release构建的最低要求。`-O3`启用自动向量化，`-march=native`启用AVX2/AVX-512，`-DNDEBUG`禁用assert。

### 建议2：启用LTO和PGO

```cmake
# LTO配置
set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -flto=auto")
set(CMAKE_EXE_LINKER_FLAGS_RELEASE "${CMAKE_EXE_LINKER_FLAGS_RELEASE} -flto=auto")

# PGO配置（需要两次编译）
# 第一次编译：生成profile
set(CMAKE_CXX_FLAGS_PGO_GEN "-O3 -march=native -DNDEBUG -fprofile-generate")
# 第二次编译：使用profile
set(CMAKE_CXX_FLAGS_PGO_USE "-O3 -march=native -DNDEBUG -fprofile-use")
```

**PGO实施步骤**：
```bash
# 1. 编译带profile的版本
mkdir build_pgo && cd build_pgo
cmake .. -DCMAKE_CXX_FLAGS="-O3 -march=native -DNDEBUG -fprofile-generate"
make

# 2. 运行代表性workload
./rtl_sim --run-benchmark-suite

# 3. 重新编译使用profile
cmake .. -DCMAKE_CXX_FLAGS="-O3 -march=native -DNDEBUG -fprofile-use"
make
```

### 建议3：用`#pragma omp simd`标记评估循环

```cpp
// 对已经过拓扑排序、确定无依赖的组合逻辑评估循环，添加pragma
void eval_combinational_block(const GateEvalContext* ctx) {
    for (size_t g = 0; g < ctx->gate_count; g++) {
        uint64_t* in0 = ctx->inputs[0] + g * ctx->vector_chunks;
        uint64_t* in1 = ctx->inputs[1] + g * ctx->vector_chunks;
        uint64_t* out = ctx->outputs + g * ctx->vector_chunks;

        // 强制向量化 hottest inner loop
        #pragma omp simd
        for (size_t i = 0; i < ctx->vector_chunks; i++) {
            out[i] = in0[i] & in1[i];  // AND门
        }
    }
}
```

编译时需加`-fopenmp-simd`（GCC）或`-fopenmp`（Clang）。

### 建议4：用`restrict`消除指针别名

```cpp
// 原始：编译器可能插入运行时别名检查，导致放弃向量化
void eval_bad(uint64_t* inputs, uint64_t* outputs, size_t n);

// 改进：restrict告诉编译器这些指针不重叠
void eval_good(uint64_t* __restrict inputs,
               uint64_t* __restrict outputs,
               size_t n);
```

**注意**：`restrict`是程序员承诺，如果实际存在别名，行为未定义。在RTL仿真器中，inout端口可能指向同一内存，需要对明确独立的数组使用`restrict`。

### 建议5：诊断优先于盲目优化

```bash
# 先诊断哪些循环向量化失败，再针对性修改
g++ -O3 -march=native -fopt-info-vec-missed -o sim sim.cpp 2>&1 | grep "missed"

# 常见输出及对策：
# "loop not vectorized: loop contains function calls or data references that cannot be analyzed"
# → 添加restrict或使用内联函数
#
# "loop not vectorized: not suitable for load/store widening"
# → 检查内存访问是否连续，避免结构体数组（AoS），改用数组结构体（SoA）
#
# "loop not vectorized: control flow in loop"
# → 消除switch/if，或按branch条件拆分循环
```

---

## 相关链接

- [Phoronix: Clang 12 Benchmarks](https://www.phoronix.com/review/clang-12-opt)
- [Phoronix: GCC 11 Benchmarks](https://www.phoronix.com/review/gcc-11-benchmarks)
- [GitHub: bit-counter-benchmarks](https://github.com/daedsidog/bit-counter-benchmarks)
- [Red Hat Developer: Vectorization in GCC](https://developers.redhat.com/articles/2023/12/08/vectorization-optimization-gcc)
- [GCC Optimize Options](https://gcc.gnu.org/onlinedocs/gcc/Optimize-Options.html)
- [Clang User Manual: Optimization](https://clang.llvm.org/docs/UsersManual.html#optimization-options)
- [Intel Intrinsics Guide](https://www.intel.com/content/www/us/en/docs/intrinsics-guide/index.html)
- [arXiv: AVX-512 SIMD Genetic Programming](https://arxiv.org/html/2512.09157)
- [LLVM Docs: Auto-Vectorization](https://llvm.org/docs/Vectorizers.html)

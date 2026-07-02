---
title: Rust SIMD 与 Rayon 数据并行在数值仿真中的实践
description: 搜集 Rust 的 SIMD（std::simd / packed_simd）和 Rayon 数据并行库在科学计算、数值仿真中的性能实践，分析向量化与多核并行对仿真吞吐量的增益
source_url: "https://docs.rs/rayon"
source_type: "doc"
author: "Rayon / packed_simd / NPB-Rust 社区"
date: "2024-2025"
tags: [rust, simd, rayon, parallel, data-parallelism, avx, vectorization, performance]
keywords: [rust rayon parallel simulation, rust simd avx, portable simd rust, rayon data parallelism, work-stealing]
capture_date: "2026-07-02"
---

# Rust SIMD 与 Rayon 数据并行在数值仿真中的实践

## 来源

- **URL**: https://docs.rs/rayon (官方文档)
- **URL**: https://docs.rs/packed-simd (Portable SIMD)
- **URL**: https://arxiv.org/html/2502.15536v1 (NPB-Rust 论文)
- **URL**: https://gendignoux.com/blog/2024/11/18/rust-rayon-optimized.html (Rayon 优化博客)
- **类型**: 文档 / 学术论文 / 技术博客
- **作者**: Rayon 团队、Portable SIMD Project Group、NPB-Rust 作者
- **日期**: 2024-2025

## 摘要

Rust 在数据并行层面拥有两大核心工具：**Rayon**（多核数据并行）与 **SIMD**（单核向量化）。Rayon 通过 `par_iter()` 将串行迭代器转换为并行迭代器，底层基于 **work-stealing** 调度算法自动平衡负载；SIMD 通过 `packed_simd`（RFC #2366）提供跨平台向量类型，一次操作处理多个数据。二者结合可模拟 ISPC 的 SPMD 编程模型，在科学计算和仿真中达到接近 C++/OpenMP 的性能。NPB-Rust 论文显示，在 EP（完全并行）和 FT（内存密集）基准上，Rayon 甚至超越 OpenMP。

## 关键要点

1. **Rayon 的极简并行**：将 `.iter()` 改为 `.par_iter()` 即可实现并行，编译器通过 `Send + Sync` 自动排除数据竞争。work-stealing 调度器在 8 核机器上可为计算密集型任务带来 **7-8× 加速**。
2. **packed_simd 的跨平台向量**：提供 `f32x4`、`i32x8` 等类型，操作分为 vertical（逐 lane）和 horizontal（跨 lane）。vertical 操作在几乎所有架构上都是最快的。
3. **SIMD + Rayon 组合**：packed_simd 的示例目录中大量使用 `rayon` 来模拟 ISPC 的 SPMD 模型。例如 `stencil` 计算中，组合使用可达 **1.72×** 于纯 SIMD 的性能。
4. **NPB-Rust 基准**：NAS Parallel Benchmarks 的 Rust 实现（Rayon）在 EP 基准上达到 29.7× 加速，超过 C++ OpenMP 的 27.7×；在 40 线程下，几何均值仅比 Fortran 慢 2.74%、比 C++ 慢 7.7%。
5. **安全边界**：Rayon 的所有闭包必须满足 `Send` bound；SIMD 的 `packed_simd` 无需 `unsafe` 即可使用跨平台向量（但 `into_bits` 等高级特性需要 nightly）。

## 对 RTL 仿真器多线程化的启示

- **信号批量评估**：RTL 中的组合逻辑（如大量 AND/OR 门）可通过 SIMD 向量化一次处理 4-8 个信号位。`u8x16` 或 `u64x8` 类型可直接映射到多 bit 逻辑向量运算。
- **并行事件分区**：RTL 的 independent combinational blocks（无依赖的组合逻辑块）可用 Rayon 的 `par_iter()` 并行评估。work-stealing 自动处理负载不均衡，优于静态分区。
- **Testbench 向量并行**：在回归测试中，大量独立测试向量（如随机约束测试）天然 embarrassingly parallel，Rayon 的 `par_iter()` 可直接并行化测试场景，无需锁。
- **内存带宽瓶颈**：FT 基准表明，Rayon 在内存密集型负载上的动态调度优于 OpenMP。RTL 的波形 dump（VCD/FST）和数据结构访问可能受益。
- **安全无数据竞争**：Rust 类型系统确保并行迭代中不会意外共享可变状态——对于 RTL 这种状态敏感的领域，这意味着更可靠的并发仿真。

## 具体代码示例

### Rayon 并行迭代器：从串行到并行只需一行

```rust
use rayon::prelude::*;

fn sequential_eval(gates: &[LogicGate]) -> Vec<bool> {
    gates.iter()
         .map(|g| g.evaluate())
         .collect()
}

fn parallel_eval(gates: &[LogicGate]) -> Vec<bool> {
    gates.par_iter()  // <-- 只需改这里
         .map(|g| g.evaluate())
         .collect()
}

/// 并行蒙特卡洛仿真（示例）
fn parallel_monte_carlo(samples: u64) -> f64 {
    use rand::random;
    let count: usize = (0..samples)
        .into_par_iter()  // 并行范围迭代
        .filter(|_| {
            let x: f64 = random();
            let y: f64 = random();
            x * x + y * y <= 1.0
        })
        .count();
    4.0 * (count as f64) / (samples as f64)
}
```

### packed_simd 向量运算：批量逻辑信号处理

```rust
use packed_simd::u8x16;

/// 批量 AND 门：16 个信号同时评估
fn batch_and_gate(a: &[u8], b: &[u8]) -> Vec<u8> {
    let mut result = vec![0u8; a.len()];
    
    // 每次处理 16 字节（128-bit SIMD）
    for i in (0..a.len()).step_by(16) {
        let va = u8x16::from_slice_unaligned(&a[i..]);
        let vb = u8x16::from_slice_unaligned(&b[i..]);
        let vand = va & vb;  // 16 个 AND 同时计算
        vand.store_unaligned(&mut result[i..]);
    }
    result
}

/// 使用 vertical 操作进行快速归约
fn fast_sum(data: &[i32]) -> i32 {
    let mut sum = i32x4::splat(0);
    for i in (0..data.len()).step_by(4) {
        sum += i32x4::from_slice_unaligned(&data[i..]);
    }
    sum.wrapping_sum()  // 最终 horizontal 归约
}
```

### SIMD + Rayon 组合：SPMD 风格并行计算

```rust
use rayon::prelude::*;
use packed_simd::f32x4;

/// 并行 stencil 计算（简化版）
fn parallel_stencil(data: &mut [f32], width: usize) {
    let chunk_size = width * 4; // 每个线程处理一个 chunk
    
    data.par_chunks_mut(chunk_size)
        .for_each(|chunk| {
            // 在 chunk 内使用 SIMD 向量化
            for i in (0..chunk.len()).step_by(4) {
                let v = f32x4::from_slice_unaligned(&chunk[i..]);
                let v_smooth = v * f32x4::splat(0.5); // 平滑滤波
                v_smooth.store_unaligned(&mut chunk[i..]);
            }
        });
}
```

### 线程池配置与性能调优

```rust
use rayon::ThreadPoolBuilder;

fn configure_pool() {
    ThreadPoolBuilder::new()
        .num_threads(8)          // 固定线程数（避免超线程竞争）
        .stack_size(2 * 1024 * 1024) // 大栈（SP 基准需要）
        .build_global()
        .unwrap();
}

/// 控制粒度：避免小集合并行化 overhead
fn selective_parallel(data: &[f64]) -> Vec<f64> {
    if data.len() > 10_000 {
        data.par_iter().map(|x| x.sqrt()).collect()
    } else {
        data.iter().map(|x| x.sqrt()).collect()
    }
}
```

## 性能对比

### NPB-Rust (Rayon) vs OpenMP 最佳加速比

| Benchmark | Rust Rayon | C++ OpenMP | Fortran OpenMP | 备注 |
|-----------|-----------|-----------|---------------|------|
| EP | **29.7×** | 27.7× | 28.2× | embarrassingly parallel，Rayon work-stealing 最优 |
| FT | **22.2×** | 20.2× | 18.1× | 内存密集型，Rayon 动态调度反超 |
| BT | 14.9× | 15.4× | **15.7×** | 计算密集，Fortran 微胜 |
| LU | 9.0× | 11.6× | **10.9×** | 数据依赖复杂，Rayon 锁开销较大 |
| MG | 5.1× | **8.2×** | 6.8× | 细粒度任务，Rayon 扩展性受限 |

> 几何均值（40 线程，EP/FT/IS/BT/LU）：Rayon 比 Fortran 慢 2.74%，比 C++ 慢 7.7%。

### packed_simd 示例性能（与 ISPC 对比）

| 示例 | SIMD 加速范围 | 备注 |
|------|-------------|------|
| aobench | -1.02x ~ +1.53x | 视平台而定，通常优于 ISPC 默认 |
| stencil | +1.06x ~ +1.72x | 结合 Rayon 可达最佳 |
| mandelbrot | -1.74x ~ +1.2x | 边界分支多，SIMD 优势不稳定 |
| black_scholes | +1.0x | 与 ISPC 持平 |
| binomial_put | +1.4x | 优于 ISPC 默认 |

### Rayon 图像处理基准（外部参考）

| 方案 | 执行时间 | 加速比 |
|------|---------|-------|
| 串行迭代 | 427 秒 | 1× |
| Rayon 并行 | **99 秒** | **4.3×** |

> 来源：机器学习中的数据并行实践（Rayon 图像处理）。

### 并行 vs 串行蒙特卡洛（双核 i5）

| 实现 | 时间/迭代 | 加速 |
|------|---------|------|
| sequential_integrate | 1,532 ns | 1× |
| parallel_integrate (Rayon) | **958 ns** | **1.6×** |
| sequential_monte_carlo | 9,737 ns | 1× |
| parallel_monte_carlo (Rayon) | **4,604 ns** | **2.1×** |

> 来源：24 days of Rust — Rayon 基准测试。

## 原文摘录

> "Rayon offers robust tools for parallel computation while preserving Rust's renowned safety guarantees. It offers a high-level abstraction for data parallelism, simplifying the process of writing concurrent code. In practical terms, parallelizing a CPU-bound operation with Rayon often requires changing just a single line of code."
> — 数据并行与机器学习评论

> "Rayon uses a work-stealing algorithm to efficiently distribute tasks across available CPU cores, automatically balancing the workload to maximize throughput."
> — 同上

> "On an 8-core machine, compute-bound work can see up to 7-8× speedup for large collections. Smaller collections have overhead that reduces gains: typically Rayon is worth it for more than ~10,000 elements."
> — Rustify Glossary

> "The vertical operations are, by default, applied to each vector lane in isolation of the others... In virtually all architectures vertical operations are fast, while horizontal operations are, by comparison, much slower."
> — packed_simd 文档

> "While SPMD is not the intended use case for packed_simd, it is possible to combine the library with rayon to poorly emulate ISPC's SPMD programming model in Rust... with some care one can easily match and often out-perform ISPC's 'default performance'."
> — packed_simd Performance 章节

> "The most portably-efficient way of performing a reduction over a slice is to collect the results into a vector using vertical operations, and performing a single horizontal operation at the end."
> — packed_simd 性能指南

> "Rayon scales considerably better compared to OpenMP when Hyper-Threading is enabled. On the other hand, for applications like MG and SP, which are known to stop scaling with fewer threads, Rayon scales similarly to OpenMP at first but hits a limit earlier."
> — NPB-Rust 论文

## 相关链接

- [Rayon 官方文档](https://docs.rs/rayon)
- [Rayon GitHub](https://github.com/rayon-rs/rayon)
- [packed_simd 文档](https://docs.rs/packed-simd)
- [Rust Portable SIMD RFC #2366](https://rust-lang.github.io/rfcs/2366-portable-simd.html)
- [NPB-Rust: NAS Parallel Benchmarks in Rust](https://arxiv.org/html/2502.15536v1)
- [Optimization adventures: making a parallel Rust workload 10x faster with Rayon](https://gendignoux.com/blog/2024/11/18/rust-rayon-optimized.html)
- [24 days of Rust — Rayon](https://zsiciarz.github.io/24daysofrust/book/vol2/day3.html)
- [avx_parallel crate](https://docs.rs/avx-parallel/latest/avx_parallel/simd/fn.simd_dot_f64.html)

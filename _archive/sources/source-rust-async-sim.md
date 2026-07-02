---
title: Rust Async / Tokio 在事件驱动仿真器中的应用
description: 搜集 Rust 异步运行时（Tokio / async-await）在离散事件仿真（DES）和事件驱动仿真器中的实践案例，分析其所有权模型对并发仿真的安全保证
source_url: "https://github.com/rupakm/DesCartes"
source_type: "github-pr"
author: "DesCartes / NeXosim / Bach 社区"
date: "2025-2026"
tags: [rust, async, tokio, des, event-driven, simulation, concurrency]
keywords: [rust async simulation, tokio simulation engine, discrete event simulation, deterministic simulation, async await des]
capture_date: "2026-07-02"
---

# Rust Async / Tokio 在事件驱动仿真器中的应用

## 来源

- **URL**: https://github.com/rupakm/DesCartes (核心参考)
- **URL**: https://github.com/asynchronics/nexosim
- **URL**: https://github.com/camshaft/bach
- **类型**: GitHub 仓库 / 开源框架
- **作者**: DesCartes 团队、NeXosim 团队、Bach 作者
- **日期**: 2020-2025

## 摘要

Rust 的所有权模型与生命周期机制为并发仿真提供了**编译期安全保证**。在离散事件仿真（DES）领域，Rust 社区已经涌现出多个利用 `async`/`await` 构建的高性能仿真框架：**DesCartes** 提供确定性、可重放的 Tokio 替代运行时；**NeXosim** 基于 Actor 模型的异步实现，在多线程 Rust 执行器上达到顶尖性能；**Bach** 则支持非实时环境中的异步系统测试与网络协议模拟。这些框架的共同特点是：将事件驱动的时间推进模型与 Rust 的 `async`/`await` 原生语法结合，使并发仿真代码既安全又高效。

## 关键要点

1. **DesCartes** — 提供 `descartes_tokio` 作为 Tokio 的仿真替代，让基于真实 Tokio 的分布式系统可以在确定性调度器上运行，支持 trace 记录与重放。
2. **NeXosim** — 基于异步 Actor 模型实现离散事件仿真，每个仿真模型是一个 Actor，通过异步 bounded MPSC channel 通信。其自定义运行时比任何其他多线程 Rust 执行器在消息传递密集型仿真负载上更快。
3. **Bach** — 专注于非实时异步仿真，支持 UDP 网络模拟、可组合队列（延迟/丢包/乱序）、Partial Order Reduction 优化测试空间，以及 PCAP 导出。
4. **Rust 所有权优势** — `async` 闭包捕获事件值，通过 `&mut self` 访问模型，编译器在编译期排除数据竞争，无需运行时锁检查开销。
5. **确定性调度** — DesCartes 的单线程确定性执行通过交错模拟并发，而非依赖 OS 线程；相同种子/输入保证可复现结果。

## 对 RTL 仿真器多线程化的启示

- **确定性仿真**：RTL 仿真需要时序确定性（同一输入始终产生同一输出）。DesCartes 的确定性调度器思想可直接迁移——用单线程事件交错替代多线程竞态，便于调试与验证。
- **异步事件推进**：RTL 的 delta 周期与事件队列模型天然适配 Rust 的 `async`/`await` + 自定义运行时。每个逻辑门或模块可视为一个异步任务，通过仿真时间推进器协调。
- **所有权解耦**：Rust 所有权模型允许将仿真状态与事件处理解耦，无需 GC 暂停。对于长时间运行的 RTL 回归测试，这意味着**零意外停顿**和**可预测的低延迟**。
- **并行探索**：DesCartes 的 `des-explore` 模块提供状态空间系统探索，RTL 可借鉴此模式进行并行测试场景生成与覆盖分析。

## 具体代码示例

### DesCartes 最小化异步仿真

```rust
use descartes_core::{Execute, Executor, SimTime, Simulation};
use std::time::Duration;

fn main() {
    let mut sim = Simulation::default();

    // 安装 Tokio-like 异步运行时
    descartes_tokio::runtime::install(&mut sim);

    // 在仿真时间 10ms 后触发一个异步任务
    descartes_tokio::task::spawn(async {
        descartes_tokio::time::sleep(Duration::from_millis(10)).await;
        println!("Event at 10ms");
    });

    // 推进仿真到 20ms
    Executor::timed(SimTime::from_duration(Duration::from_millis(20)))
        .execute(&mut sim);
}
```

### NeXosim Actor 模型事件投递

```rust
use nexosim::prelude::*;

struct Gate {
    output: Output<bool>,
}

impl Gate {
    async fn on_input(&mut self, value: bool) {
        // 在仿真时间 5ns 后调度输出事件
        self.output.send(!value).await;
    }
}

// 创建仿真器并推进时间
let mut simu = Simulation::new();
let mut gate = Gate { output: Output::new() };
// 调度输入事件到 gate 的 on_input
// simu.process_event(); // 推进到下一个事件时间点
```

### Bach 队列与网络模拟

```rust
use bach::environment::Network;

let mut net = Network::new();
let (client, server) = net.register((client, server));

// 模拟 10ms 延迟 + 1% 丢包率的 UDP 链路
client.link.set_latency(Duration::from_millis(10));
client.link.set_loss_rate(0.01);

// 在仿真时序中发送数据包
client.send_to(b"hello", server.addr).await?;
```

## 性能对比

| 框架 | 并发模型 | 调度器 | 消息传递延迟 | 确定性 | 典型场景 |
|------|----------|--------|-------------|--------|----------|
| DesCartes | 单线程交错 | 自定义 DES | 事件粒度 | ✅ 完全确定 | 分布式系统验证 |
| NeXosim | 多线程 Actor | 自定义 async | 优先队列 | ✅ 可复现 | 大规模系统仿真 |
| Bach | 单/多线程 | 自定义 DES | 微秒级 | ✅ 可配置 | 网络协议测试 |
| Tokio (原生) | 多线程 OS | I/O 事件循环 | 纳秒级 | ❌ 非确定 | 生产级服务 |

**NAS Parallel Benchmarks (NPB) 中 Rust 的并发表现**（参考 `NPB-Rust` 论文）：

| Benchmark | Rust Rayon Speedup | C++ OpenMP Speedup | Fortran OpenMP Speedup |
|-----------|------------------|-------------------|----------------------|
| EP ( embarrassingly parallel ) | **29.7×** | 27.7× | 28.2× |
| FT ( memory-intensive ) | **22.2×** | 20.2× | 18.1× |
| IS | 12.3× | **14.9×** | 13.5× |
| MG | 5.1× | 8.2× | **6.8×** |

> 注：EP/FT 中 Rayon 因 work-stealing 动态调度反超 OpenMP；MG 因细粒度任务与 unsafe 需求，Rust 略逊。

## 原文摘录

> "DesCartes is a Rust workspace for building deterministic, single-threaded discrete-event simulations (DES) of distributed and concurrent systems. It provides a stand-in replacement for core Rust libraries (tokio, tower, tonic, etc.) so that systems using these libraries can be simulated deterministically."
> — DesCartes README

> "NeXosim relies on a fully custom runtime. Even though the runtime was largely influenced by Tokio, it features additional optimizations that make it faster than any other multi-threaded Rust executor on the typically message-passing-heavy workloads seen in discrete-event simulation."
> — NeXosim Implementation Notes

> "Bach is a Rust-based framework for simulating and testing complex async/await-based systems in a non-real-time environment. It's capable of modeling network protocols, queueing systems, and concurrent task interactions."
> — Bach README

> "Rust showed clear edges in live conditions where milliseconds matter: sub-millisecond to low-ms native performance, no garbage collector pauses, zero unexpected stalls during high-volatility windows."
> — Polymarket Trading Bot Rust vs Python/TS 对比

## 相关链接

- [DesCartes — 确定性离散事件仿真](https://github.com/rupakm/DesCartes)
- [NeXosim — 高性能异步系统仿真](https://github.com/asynchronics/nexosim)
- [Bach — 异步仿真测试框架](https://github.com/camshaft/bach)
- [NPB-Rust: NAS Parallel Benchmarks in Rust](https://arxiv.org/html/2502.15536v1)
- [Rustify — Rayon 并行迭代器详解](https://rustify.rs/glossary/rayon)

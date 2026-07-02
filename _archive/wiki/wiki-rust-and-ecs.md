---
id: "wiki-rust-and-ecs"
title: "Rust与ECS架构在仿真器中的应用"
description: "分析Rust所有权模型与ECS架构对RTL仿真器的启示：从编译期并发安全、数据导向设计到可操作的C++重构建议"
tags: ["rust", "ecs", "data-oriented-design", "concurrency", "rtl-simulation", "bevy", "rayon"]
keywords: ["rust rtl simulation", "ecs architecture", "entity component system", "bevy archetype", "rayon work stealing", "simd rtl", "data oriented design"]
related_sources:
  - "source-rust-async-sim"
  - "source-ecs-architecture"
  - "source-rust-simd-rayon"
last_updated: "2026-07-02"
---

# Rust与ECS架构在仿真器中的应用

## 核心论点

Rust 的所有权模型 + ECS（Entity-Component-System）架构为 RTL 仿真器提供了一条**从根本上消除并发 bug** 的技术路径。它不是简单的「用 Rust 重写 Verilator」，而是将**数据导向设计（Data-Oriented Design）**、**编译期安全验证**和**自动并行调度**的思想注入现有 C++ 仿真器，使其获得接近 Bevy ECS 的缓存友好性与调度效率。

> **一句话总结**：Rust 在编译期把 data race 变成编译错误；ECS 把「面向对象的门级模型」变成「按类型连续存储的批量数据」，让 SIMD 和并行调度器能发挥最大效能。

---

## 1. Rust 所有权模型：编译期消除 data race

### 1.1 为什么 RTL 仿真器特别容易出并发 bug

RTL 仿真器的状态是**全局共享的**——所有逻辑门共享信号网表，每个时钟周期都有读写交叉。传统 C++ 的做法是：

```cpp
// C++: 手动锁保护信号更新
std::mutex signal_mutex;
for (auto& gate : active_gates) {
    std::lock_guard<std::mutex> lock(signal_mutex);
    gate->eval();  // 可能读写其他门的输出
}
```

问题：锁粒度太粗 → 串行化；锁粒度太细 → 死锁/性能崩溃。Verilator 的 V3Order 和 MTask 分区本质上是在解决「手动并发安全」的问题，但只能在运行时暴露 bug。

### 1.2 Rust 的编译期保证

Rust 的所有权（Ownership）+ 借用检查（Borrow Checker）在编译期就禁止了以下模式：

```rust
// Rust: 编译错误！不能同时持有可变和不可变引用
let mut signals = vec![false; 1000];
let ref1 = &signals[0];      // 不可变借用
let ref2 = &mut signals[1];  // ✅ 允许：不同元素
// let ref3 = &mut signals[0]; // ❌ 编译错误：与 ref1 冲突
```

在 RTL 仿真中，这意味着：
- **组合逻辑评估**：如果一个 System 要写入 `SignalValue`，另一个 System 同时读取同一 `SignalValue`，Rust 编译器会拒绝编译——除非你通过显式调度（如 ECS 的 stage）来串行化。
- **跨时钟域同步**：Rust 的 `Send + Sync` trait 强制要求共享状态必须是线程安全的类型。RTL 的时钟域交叉（CDC）信号天然需要 `Arc<Mutex<T>>` 或 channel，编译器会逼你显式处理。

### 1.3 对确定性仿真的意义

DesCartes 的确定性调度器之所以可行，正是因为 Rust 的所有权模型保证了：**在单线程交错执行中，不会意外共享可变状态**。没有 data race，就不需要复杂的 happens-before 分析——仿真的可重复性从「希望程序员不犯错」变成了「编译器强制不犯错」。

> **可操作点**：即使不迁移到 Rust，C++ 仿真器也可以引入 Rust 风格的「唯一所有权」规则——每个信号在同一时间只能被一个 MTask 写入，通过静态分析工具（如 Clang Thread Safety Analysis）在编译期检查。

---

## 2. DesCartes / Tokio / Bach：Rust 异步事件驱动仿真器

### 2.1 三个框架对比

| 框架 | 并发模型 | 调度器 | 确定性 | 核心特点 |
|------|----------|--------|--------|----------|
| **DesCartes** | 单线程交错 | 自定义 DES | ✅ 完全确定 | Tokio 替代运行时，trace 可重放 |
| **NeXosim** | 多线程 Actor | 自定义 async | ✅ 可复现 | Actor 模型 + MPSC channel，消息密集型负载最优 |
| **Bach** | 单/多线程 | 自定义 DES | ✅ 可配置 | 网络模拟、队列丢包/延迟、PCAP 导出 |

### 2.2 DesCartes：确定性事件推进

DesCartes 提供 `descartes_tokio` 作为 Tokio 的仿真替代，让基于真实 Tokio 的分布式系统可以在确定性调度器上运行：

```rust
use descartes_core::{Execute, Executor, SimTime, Simulation};
use std::time::Duration;

fn main() {
    let mut sim = Simulation::default();
    descartes_tokio::runtime::install(&mut sim);

    // 在仿真时间 10ms 后触发事件
    descartes_tokio::task::spawn(async {
        descartes_tokio::time::sleep(Duration::from_millis(10)).await;
        println!("Event at 10ms");
    });

    // 推进到 20ms
    Executor::timed(SimTime::from_duration(Duration::from_millis(20)))
        .execute(&mut sim);
}
```

**RTL 映射**：RTL 的 delta 周期（零延迟传播）天然是一个事件队列。DesCartes 的确定性调度器思想可直接迁移——用单线程事件交错替代多线程竞态，同一输入始终产生同一输出，便于调试与验证。

### 2.3 NeXosim：Actor 模型的 RTL 映射

NeXosim 将每个仿真模型视为一个 Actor，通过异步 bounded MPSC channel 通信：

```rust
use nexosim::prelude::*;

struct LogicGate {
    output: Output<bool>,
}

impl LogicGate {
    async fn on_input(&mut self, value: bool) {
        // 在仿真时间 5ns 后调度输出事件
        self.output.send(!value).await;
    }
}

let mut simu = Simulation::new();
let mut gate = LogicGate { output: Output::new() };
// simu.process_event(); // 推进到下一个事件时间点
```

**RTL 映射**：每个逻辑门或模块可以视为一个 Actor，输入事件触发 `on_input`，输出通过 channel 投递到下游门。这种模型天然避免了共享状态——数据通过消息传递，而不是通过全局信号网表。

> **可操作点**：在 C++ 仿真器中，尝试将「共享信号网表」改为「事件驱动的消息传递模型」——每个门评估完成后，通过无锁队列（如 Folly MPMCQueue）将事件投递到下游门，减少锁竞争。

---

## 3. ECS 架构：Entity-Component-System 如何映射到 RTL

### 3.1 核心映射关系

| ECS 概念 | RTL 映射 | 说明 |
|----------|----------|------|
| **Entity** | 逻辑门 / 寄存器实例 | 每个门是一个唯一标识的实体（如 `AND_0`, `FF_3`） |
| **Component** | 门的类型属性 | `SignalValue(bool)`、`WireDelay(u64)`、`GateType(And/Or/Xor)` |
| **System** | 评估函数 | `eval_comb_system`（组合逻辑评估）、`sample_reg_system`（时序采样） |
| **Archetype** | 模块类型 | 所有 AND 门共享一个 archetype，组件连续存储 |
| **Query** | 遍历过滤器 | "所有拥有 `SignalValue` + `GateType::And` 的实体" |
| **Scheduler** | 时钟调度器 | 按读写依赖自动推导哪些 System 可以并行 |

### 3.2 为什么面向对象的 RTL 模型是反模式

传统 OOP 的 RTL 建模：

```cpp
// C++ OOP: 每个门是一个对象，数据分散在堆上
class AndGate : public Gate {
    bool output;
    std::vector<Gate*> inputs;  // 指针跳跃！
public:
    void eval() override { output = inputs[0]->output & inputs[1]->output; }
};

std::vector<std::unique_ptr<Gate>> gates;  // 虚函数表 + 指针跳跃
gates[0]->eval();  // cache miss 高，预取器失效
```

ECS 的 RTL 建模：

```rust
// Rust ECS: 同类型数据连续存储，无指针跳跃
#[derive(Component)]
struct SignalValue(bool);

#[derive(Component)]
struct GateType(u8);  // 0=AND, 1=OR, 2=XOR, 3=FF

#[derive(Component)]
struct InputIndices([u32; 2]);  // 输入信号索引（不是指针！）

/// 批量评估所有 AND 门
fn eval_and_system(
    mut signals: Query<(&mut SignalValue, &GateType, &InputIndices)>,
) {
    for (mut output, gate_type, inputs) in signals.iter_mut() {
        if gate_type.0 == 0 {  // AND
            // 通过索引访问输入信号（连续内存访问）
            output.0 = signal_array[inputs.0[0] as usize].0 
                     & signal_array[inputs.0[1] as usize].0;
        }
    }
}
```

**关键差异**：OOP 中 `gates[0]->eval()` 是一次虚函数调用 + 两次指针解引用（`inputs[0]` 和 `inputs[1]` 可能指向不同缓存行）。ECS 中，所有 `SignalValue` 连续存储在一个 `Vec<bool>` 中，CPU 预取器可以完美工作——一次 cache line 加载包含 64 个信号值。

---

## 4. Bevy ECS：archetype 存储、并行调度器、SoA 布局

### 4.1 Archetype 存储：类型相同的实体分组存放

Bevy ECS 将拥有相同组件类型的实体归为同一个 archetype。例如：

- Archetype A：所有 AND 门 → `Vec<SignalValue>`, `Vec<GateType>`, `Vec<InputIndices>`
- Archetype B：所有 OR 门 → 同上
- Archetype C：所有 D 触发器 → `Vec<SignalValue>`, `Vec<GateType>`, `Vec<RegState>`

```rust
use bevy_ecs::prelude::*;

#[derive(Component)]
struct SignalValue(bool);

#[derive(Component)]
struct WireDelay(u64);

// 创建 1000 个 AND 门实体，全部进入同一 archetype
let mut world = World::new();
for i in 0..1000 {
    world.spawn((
        SignalValue(i % 2 == 0),
        WireDelay(100),  // 100ps 延迟
        GateType(0),     // AND
    ));
}

// 查询时，Bevy 直接遍历 archetype 的连续数组，无哈希查找
fn eval_and_system(mut query: Query<(&mut SignalValue, &GateType)>) {
    for (mut signal, gate_type) in query.iter_mut() {
        if gate_type.0 == 0 { signal.0 = /* AND 逻辑 */; }
    }
}
```

**缓存性能**：ECS 的 Struct of Arrays（SoA）布局比 Array of Objects（AoO）快 **10×** 以上：

| 方案 | 10000 实体迭代耗时 | 相对速度 | 内存访问模式 |
|------|-----------------|---------|------------|
| OOP (Array of Objects) | ~1000 ns | 1× | 指针跳跃，cache miss 高 |
| ECS (Struct of Arrays) | ~100 ns | **10×** | 线性连续，cache hit 高 |

### 4.2 并行调度器：自动推导 System 依赖

Bevy 的调度器自动检查每个 System 对组件的读写权限，无冲突的 System 自动并行执行：

```rust
fn physics_system(time: Res<Time>, mut q: Query<(&mut Position, &Velocity)>) {
    let dt = time.delta_seconds();
    for (mut pos, vel) in q.iter_mut() {
        pos.x += vel.x * dt;
    }
}

fn render_prep_system(q: Query<(&Position, &Sprite)>) {
    for (pos, _sprite) in q.iter() {
        // 只读 Position，写入渲染队列
    }
}

// 调度器配置
app.add_systems(
    Update,
    (
        physics_system,     // 写 Position，读 Velocity
        render_prep_system,   // 读 Position，读 Sprite
    ).chain(),
);
```

**RTL 映射**：
- `physics_system` → `eval_comb_system`（组合逻辑评估，写输出信号）
- `render_prep_system` → `sample_reg_system`（时序采样，读上一周期状态）

如果两个 System 读写的是**不同的组件**（如一个写 `SignalValue`，一个读 `RegState`），调度器自动并行。如果存在读写冲突（如都访问 `SignalValue`），调度器自动串行化——**无需手动加锁**。

> **关键优势**：在 C++ 中，判断两个 MTask 是否可以并行需要复杂的依赖分析（V3Order）。在 Rust ECS 中，编译器通过类型系统**自动验证**并行安全性——如果两个 System 的参数类型没有重叠的可变引用，它们就是安全的。

---

## 5. Rayon work-stealing：par_iter() 在门级评估中的应用

### 5.1 从串行到并行：只需一行

Rayon 的 `par_iter()` 将串行迭代器转换为并行迭代器，底层基于 work-stealing 调度：

```rust
use rayon::prelude::*;

// 串行：逐个评估逻辑门
fn sequential_eval(gates: &[LogicGate]) -> Vec<bool> {
    gates.iter()
         .map(|g| g.evaluate())
         .collect()
}

// 并行：work-stealing 动态负载均衡
fn parallel_eval(gates: &[LogicGate]) -> Vec<bool> {
    gates.par_iter()  // <-- 只需改这里
         .map(|g| g.evaluate())
         .collect()
}
```

### 5.2 RTL 门级评估的并行化

RTL 仿真中，**无依赖的组合逻辑块**天然 embarrassingly parallel：

```rust
use rayon::prelude::*;

/// 并行评估独立组合逻辑块
fn parallel_comb_eval(blocks: &mut [CombBlock]) {
    blocks.par_iter_mut().for_each(|block| {
        for gate in &block.gates {
            let new_val = gate.eval();
            // 注意：每个 block 只写自己的信号，无跨 block 写入
            block.set_output(gate.id, new_val);
        }
    });
}

/// 选择性并行：小集合不并行化（避免 overhead）
fn selective_eval(gates: &[Gate]) -> Vec<bool> {
    if gates.len() > 10_000 {
        gates.par_iter().map(|g| g.eval()).collect()
    } else {
        gates.iter().map(|g| g.eval()).collect()
    }
}
```

### 5.3 Work-stealing 的优势：超越静态分区

Verilator 的 MTask 是**静态分区**——编译时确定哪个门属于哪个线程。但 RTL 的活跃门在每个周期变化，静态分区可能导致某些线程空转。

Rayon 的 work-stealing 是**动态负载均衡**：
- 活跃门多的线程自动分配更多工作
- 当某线程完成自己的 chunk，它会从其他线程的队列中「偷」任务
- 在 NPB 基准中，Rayon 在 EP（完全并行）和 FT（内存密集）上分别达到 **29.7×** 和 **22.2×** 加速，超过 C++ OpenMP

| Benchmark | Rust Rayon | C++ OpenMP | 备注 |
|-----------|-----------|-----------|------|
| EP (embarrassingly parallel) | **29.7×** | 27.7× | work-stealing 动态调度最优 |
| FT (memory-intensive) | **22.2×** | 20.2× | 动态调度反超 |
| MG (fine-grained) | 5.1× | **8.2×** | 细粒度任务，Rayon 扩展性受限 |

> **RTL 启示**：对于细粒度门级评估（如 MG 类的细粒度任务），Rayon 的 work-stealing 开销可能超过收益。但对于粗粒度模块评估（如处理器核级仿真），work-stealing 可以显著改善负载均衡。

---

## 6. Rust SIMD：packed_simd 跨平台向量、位操作仿真

### 6.1 批量逻辑门评估：一次处理 16 个 AND 门

RTL 仿真的本质是位操作——AND、OR、XOR、NOT。SIMD 可以一次处理多个信号位：

```rust
use packed_simd::u8x16;

/// 批量 AND 门：16 个信号同时评估
fn batch_and_gate(a: &[u8], b: &[u8]) -> Vec<u8> {
    let mut result = vec![0u8; a.len()];
    
    for i in (0..a.len()).step_by(16) {
        let va = u8x16::from_slice_unaligned(&a[i..]);
        let vb = u8x16::from_slice_unaligned(&b[i..]);
        let vand = va & vb;  // 16 个 AND 同时计算（单条指令）
        vand.store_unaligned(&mut result[i..]);
    }
    result
}
```

### 6.2 SIMD + ECS 组合：SoA 布局让向量化 trivial

ECS 的 SoA 布局天然适配 SIMD——因为所有信号值已经是连续存储的：

```rust
use packed_simd::u64x8;

// ECS 中所有 SignalValue 存储在一个 Vec<bool> 中
// 我们可以将其 reinterpret 为 SIMD 向量
fn simd_eval_not(signals: &mut [bool]) {
    // 将 bool 数组打包为 u64 块，每 64 个 bool 变成一个 u64
    let packed = signals.as_mut_ptr() as *mut u64;
    let len = signals.len() / 64;
    
    for i in 0..len {
        unsafe {
            let v = u64x8::splat(*packed.add(i));
            let vnot = !v;  // 64 个 NOT 同时计算
            *packed.add(i) = vnot.extract(0);  // 简化：实际用 store
        }
    }
}
```

### 6.3 SIMD + Rayon 组合：SPMD 风格

packed_simd 的示例目录中大量使用 `rayon` 模拟 ISPC 的 SPMD 模型：

```rust
use rayon::prelude::*;
use packed_simd::f32x4;

/// SIMD + 多线程组合：每个线程处理一个 chunk，chunk 内 SIMD 向量化
fn parallel_stencil(data: &mut [f32], width: usize) {
    let chunk_size = width * 4;
    
    data.par_chunks_mut(chunk_size)
        .for_each(|chunk| {
            for i in (0..chunk.len()).step_by(4) {
                let v = f32x4::from_slice_unaligned(&chunk[i..]);
                let v_smooth = v * f32x4::splat(0.5);
                v_smooth.store_unaligned(&mut chunk[i..]);
            }
        });
}
```

**RTL 映射**：在回归测试中，大量独立测试向量（如随机约束测试）天然 embarrassingly parallel。Rayon 的 `par_iter()` 并行化测试场景，每个场景内 SIMD 加速门级评估——**多线程 × 向量化 = 双重加速**。

---

## 7. 对 RTL 仿真器的启示：优势与障碍

### 7.1  Rust + ECS 可能消除的并发 bug

| 问题类型 | C++ 现状 | Rust + ECS 方案 |
|----------|---------|----------------|
| Data race | 运行时 TSan/Helgrind 检测，漏检率高 | 编译期拒绝编译 |
| 死锁 | 锁顺序依赖，复杂设计易犯错 | 无锁：调度器自动推导并行，无显式锁 |
| 时序不确定性 | 多线程调度顺序不可复现 | DesCartes 确定性交错，同一输入始终同一输出 |
| 野指针/Use-after-free | Valgrind 检测，性能开销大 | 编译期生命周期检查 |
| 负载不均衡 | 静态 MTask 分区，活跃门变化导致空转 | Rayon work-stealing 动态均衡 |
| Cache thrashing | 面向对象指针跳跃 | ECS SoA 连续存储，缓存命中率 10× 提升 |

### 7.2 现实障碍：编译时间、生态、存量代码

| 障碍 | 描述 | 缓解策略 |
|------|------|----------|
| **编译时间** | Rust 的 borrow checker 分析导致编译慢于 C++ | 增量编译 + `cranelift` 后端；对仿真器来说，编译一次运行多次，可接受 |
| **生态系统** | Verilator/Chisel/商业仿真器都是 C++/Java 生态 | 渐进迁移：从 Rust FFI 绑定开始，逐步替换核心引擎 |
| **存量代码** | 海量现有 Verilog/SystemVerilog 设计 | CIRCT/MLIR 提供 Rust 绑定路径；或保留 C++ 前端，Rust 替换后端执行引擎 |
| **学习曲线** | 团队需要掌握 Rust 所有权和 ECS 思维 | 从「用 ECS 设计模式重构 C++」开始，无需切换语言 |
| **细粒度并行** | MG 基准显示 Rayon 在细粒度任务上不如 OpenMP | 粗粒度模块并行（处理器核级）+ SIMD 门级向量化 |

---

## 8. 技术路线对比：C++17/20 vs Rust for RTL 仿真器

### 8.1 语言特性对比

| 维度 | C++17/20 | Rust |
|------|----------|------|
| 并发安全 | 运行时工具（TSan、Mutex） | 编译期保证（Borrow Checker） |
| 内存安全 | 智能指针 + RAII，但仍可 UAF | 所有权 + 生命周期，UAF 编译错误 |
| 数据并行 | OpenMP（编译指令） | Rayon（库级，一行代码） |
| SIMD | 平台相关 intrinsic（AVX-512/SVE） | `packed_simd` 跨平台抽象 |
| 异步/事件驱动 | `std::async`、coroutines（C++20） | `async`/`await` + 自定义运行时（Tokio/DesCartes） |
| ECS 生态 | EnTT、Flecs（C++） | Bevy ECS、Legion、hecs（Rust 原生） |
| 编译速度 | 较快（尤其增量编译） | 较慢（但 cranelift  backend 改善中） |
| 调试体验 | GDB/LLDB 成熟 | Rust 生态改善中，但并发 bug 少意味着调试需求少 |
| 存量集成 | 无缝（Verilator 本身就是 C++） | 需 FFI 或重写 |

### 8.2 性能对比（NPB 基准）

在 NAS Parallel Benchmarks 中，Rust Rayon 与 C++ OpenMP 的对比：

| Benchmark | Rust Rayon | C++ OpenMP | Fortran OpenMP | 分析 |
|-----------|-----------|-----------|---------------|------|
| EP | **29.7×** | 27.7× | 28.2× | embarrassingly parallel，Rayon 最优 |
| FT | **22.2×** | 20.2× | 18.1× | 内存密集，动态调度反超 |
| BT | 14.9× | 15.4× | **15.7×** | 计算密集，Fortran 微胜 |
| LU | 9.0× | 11.6× | **10.9×** | 数据依赖复杂，Rayon 锁开销较大 |
| MG | 5.1× | **8.2×** | 6.8× | 细粒度任务，Rayon 扩展性受限 |

**结论**：Rust 在数据并行和内存密集型负载上**可以超越** C++，但在细粒度、复杂依赖的任务上略逊。对于 RTL 仿真器——如果主要并行单位是「模块/处理器核」而非「单个逻辑门」——Rust 的性能是足够的。

---

## 9. 可操作的建议：用 ECS 设计模式重构 C++ 仿真器

### 9.1 阶段一：数据结构 ECS 化（无需换语言）

将现有 C++ 仿真器的「面向对象门级模型」改为 ECS 风格的 SoA 布局：

```cpp
// 阶段一：C++ 中实现 ECS 风格的数据结构
// 不要 std::vector<std::unique_ptr<Gate>>，而是：

struct SignalValues {
    std::vector<bool> values;        // 所有信号值连续存储
    std::vector<uint64_t> delays;    // 所有延迟连续存储
};

struct AndGates {
    std::vector<uint32_t> output_ids;   // 输出信号索引
    std::vector<uint32_t> input0_ids;   // 输入0索引
    std::vector<uint32_t> input1_ids;   // 输入1索引
};

// 批量评估：连续内存访问，CPU 预取器友好
void eval_and_gates(const AndGates& gates, SignalValues& signals) {
    for (size_t i = 0; i < gates.output_ids.size(); ++i) {
        bool in0 = signals.values[gates.input0_ids[i]];
        bool in1 = signals.values[gates.input1_ids[i]];
        signals.values[gates.output_ids[i]] = in0 & in1;
    }
}
```

**收益**：仅这一步就可以获得 5-10× 的缓存性能提升，为后续 SIMD 和并行化打下基础。

### 9.2 阶段二：引入 Archetype 思想

将不同门类型（AND、OR、XOR、FF）按 archetype 分组：

```cpp
// 按类型分组的门存储（类似 Bevy 的 archetype）
class GateArchetype {
    std::vector<uint32_t> output_ids;
    std::vector<uint32_t> input0_ids;
    std::vector<uint32_t> input1_ids;
    
public:
    void eval(SignalValues& signals) {
        // 批量评估，连续内存访问
        for (size_t i = 0; i < output_ids.size(); ++i) {
            signals.values[output_ids[i]] = 
                signals.values[input0_ids[i]] & signals.values[input1_ids[i]];
        }
    }
};

class SimulationWorld {
    GateArchetype and_gates;
    GateArchetype or_gates;
    GateArchetype xor_gates;
    // ...
    
public:
    void eval_all() {
        // 按阶段顺序评估：组合逻辑 → 时序采样
        and_gates.eval(signals);
        or_gates.eval(signals);
        xor_gates.eval(signals);
        // 时序采样（只读上一周期，可并行）
        sample_registers();
    }
};
```

### 9.3 阶段三：并行调度（C++20 或 TBB）

使用 C++20 `std::jthread` 或 Intel TBB 实现类似 Bevy 的并行调度器：

```cpp
#include <tbb/parallel_for.h>

// 独立的组合逻辑块可以并行评估
void eval_comb_blocks_parallel(std::vector<CombBlock>& blocks, SignalValues& signals) {
    tbb::parallel_for(
        tbb::blocked_range<size_t>(0, blocks.size()),
        [&](const tbb::blocked_range<size_t>& r) {
            for (size_t i = r.begin(); i != r.end(); ++i) {
                blocks[i].eval(signals);  // 每个 block 只读/写自己的信号
            }
        }
    );
}

// 注意：必须保证 blocks 之间无写冲突！
// 这类似于 Bevy 调度器的「读写依赖检查」
```

### 9.4 阶段四：渐进引入 Rust（可选）

如果团队决定引入 Rust，建议从以下路径开始：

1. **FFI 绑定**：保留 C++ 的 Verilog 解析前端，用 Rust 重写仿真执行引擎
   ```rust
   // Rust 端：通过 FFI 接收 C++ 解析后的网表
   #[no_mangle]
   pub extern "C" fn rust_simulate_step(world_ptr: *mut c_void) {
       let world = unsafe { &mut *(world_ptr as *mut SimulationWorld) };
       world.eval_all();  // Rust 执行引擎
   }
   ```

2. **关键模块先行**：从确定性要求最高的模块（如测试框架、重放系统）开始，用 DesCartes 的确定性调度器替代

3. **利用 Rust 的 SIMD 和 Rayon**：将批量信号评估和回归测试并行化用 Rust 实现，通过 FFI 暴露给 C++ 主程序

### 9.5  Cemetery 内存管理：减少动态分配

ECS 的 cemetery 系统（内存池复用）可直接应用于 RTL 仿真：

```cpp
// 内存池：避免频繁的实体创建/销毁（如动态测试向量）
class EntityPool {
    std::vector<uint32_t> freed_slots;
    std::vector<SignalValue> storage;
    
public:
    uint32_t allocate() {
        if (!freed_slots.empty()) {
            uint32_t id = freed_slots.back();
            freed_slots.pop_back();
            return id;
        }
        storage.emplace_back();
        return storage.size() - 1;
    }
    
    void free(uint32_t id) {
        freed_slots.push_back(id);  // 不释放内存，只标记复用
    }
};
```

> **Verilator 的 Mtask 已经使用了类似思路**，但 ECS 的 cemetery 系统更系统化，可以推广到所有动态实体管理。

---

## 10. 总结与行动清单

### 核心结论

1. **Rust 的所有权模型** 可以将 RTL 仿真器的并发 bug 从「运行时调试」变为「编译期拒绝编译」，对于确定性要求极高的 RTL 验证有根本性优势。

2. **ECS 架构** 将 RTL 的「面向对象门级模型」转换为「数据导向的批量处理」，SoA 布局带来 **10× 缓存性能提升**，archetype 存储让 SIMD 和并行调度 trivial。

3. **Rayon work-stealing** 在粗粒度模块并行上优于静态分区，适合处理器核级/模块级 RTL 仿真；但在细粒度门级评估上， overhead 可能超过收益。

4. **Rust SIMD** (`packed_simd`) 提供跨平台向量抽象，一次处理 16/64 个信号位，与 ECS 的 SoA 布局天然适配。

5. **现实路径**：不必全盘迁移到 Rust。先从 **C++ 中实现 ECS 设计模式**（SoA 数据结构 + archetype 分组 + 调度器并行）开始，验证收益后再考虑引入 Rust 的编译期安全保证。

### 行动清单

| 优先级 | 行动 | 预期收益 | 工作量 |
|--------|------|----------|--------|
| P0 | 将现有 C++ 仿真器的信号存储从 AoS 改为 SoA | 5-10× 缓存性能提升 | 2-4 周 |
| P1 | 按门类型（AND/OR/FF）分组存储（archetype） | 简化批量评估逻辑，为 SIMD 铺路 | 1-2 周 |
| P2 | 引入 Intel TBB/Rayon 风格并行调度器 | 粗粒度并行加速，负载均衡 | 2-3 周 |
| P3 | 使用 SIMD 批量评估（AVX-512/SVE） | 4-16× 门级评估加速 | 1-2 周 |
| P4 | 评估 Rust FFI 路径，用 Rust 重写确定性调度器 | 编译期并发安全，确定性保证 | 1-2 月 |
| P5 | 探索 CIRCT/MLIR → Rust 的完整前端替代 | 长期 Rust 原生 RTL 仿真器 | 6-12 月 |

---

## 参考资料

- [DesCartes — 确定性离散事件仿真](https://github.com/rupakm/DesCartes)
- [NeXosim — 高性能异步系统仿真](https://github.com/asynchronics/nexosim)
- [Bach — 异步仿真测试框架](https://github.com/camshaft/bach)
- [Bevy ECS GitHub](https://github.com/bevyengine/bevy/tree/main/crates/bevy_ecs)
- [krABMaga / ECS 并行性能论文](https://ceur-ws.org/Vol-4124/paper43.pdf)
- [Rayon 官方文档](https://docs.rs/rayon)
- [packed_simd 文档](https://docs.rs/packed-simd)
- [NPB-Rust: NAS Parallel Benchmarks in Rust](https://arxiv.org/html/2502.15536v1)

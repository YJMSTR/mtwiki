---
title: "Wiki: V3ExecGraph 执行图与 MTask 静态调度"
date: "2026-07-04"
tags: ["verilator", "multithreading", "wiki"]
---

# V3ExecGraph 执行图与 MTask 静态调度

## 概述

V3ExecGraph 是 Verilator 多线程后端的**调度器核心**，负责将经过 V3Order 划分得到的 MTask 依赖图，**静态分配**到固定数量的线程，并生成对应的 C++ 多线程执行代码。

**核心输入**：`V3Graph` 形式的 MTask 依赖图（来自 V3Order）  
**核心输出**：每个线程的 C++ 入口函数 + MTask 状态同步变量 + 线程池启动代码

---

## 架构图

```
┌─────────────────┐
│   V3Order       │  MTask 划分（基于逻辑依赖和变量访问）
│  (MTask Graph)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   V3ExecGraph   │  静态调度 + 代码生成
│   implement()   │
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌────────┐ ┌────────────┐
│PackThreads│ │Code Gen    │
│::pack()  │ │(Thread Func)│
└────────┘ └────────────┘
    │         │
    └────┬────┘
         ▼
┌─────────────────┐
│  Generated C++  │  线程池 + MTaskState 同步
│   (Verilated)   │
└─────────────────┘
```

---

## 核心概念

### MTask（Multi-threaded Task）

Verilator 将 RTL 设计划分成**最粗粒度的可并行任务单元**。每个 MTask 是一个**无内部同步**的纯计算任务，包含一段可顺序执行的 C++ 代码。

- **粒度**：一个 MTask 通常包含多个 always block 的逻辑
- **依赖**：MTask 之间有数据依赖（通过 V3GraphEdge 表示）
- **执行**：一个 MTask 在其所有上游依赖完成后才能执行

### ThreadSchedule（线程调度表）

一个 `ThreadSchedule` 对象记录了一组 MTask 到一组线程的**静态分配**：

- `m_threads[threadId]` = 该线程按顺序执行的 MTask 列表
- `s_mtaskState[mtaskp]` = 全局状态：完成时间、线程 ID、同线程后继
- 支持多个 ThreadSchedule（用于隔离宽任务）

### PackThreads（打包算法）

采用**列表调度（List Scheduling）**的贪心变体：

1. 维护"就绪"集合（所有入边已调度的 MTask）
2. 对每个就绪 MTask，计算在每个线程上的**最早可开始时间**
3. 选择 `(MTask, thread)` 组合，使得开始时间最小
4. 若平局，选择**关键路径更长**（priority 更高）的 MTask
5. 重复直到所有 MTask 都被调度

**Sandbag（沙袋）机制**：跨线程查看任务完成时间时，额外增加 30% padding。这是为了**容忍执行时间预测误差**，减少运行时阻塞。

---

## 同步机制

Verilator 的 MTask 同步采用**计数器 + 等待/通知**模式，**无锁设计**：

```
MTask A (Thread 0)          MTask B (Thread 1)
     │                           │
     │  signalUpstreamDone()     │ waitUntilUpstreamDone()
     ├────────────────────────────►│
     │                           │ (计数器减到 0 后唤醒)
     │                           │
     ▼                           ▼
  完成                          开始执行
```

**关键设计**：
- `__Vm_mtaskstate_*` 是计数器变量，初始值为跨线程入边数
- 每个上游完成后调用 `signalUpstreamDone`，计数器递减
- 当计数器归零，`waitUntilUpstreamDone` 返回，MTask 开始执行
- 使用 `even_cycle`（双缓冲）避免同一仿真周期内的状态冲突

---

## 多线程执行模型

```cpp
// 主线程（Verilator 生成代码）
vlSymsp->__Vm_even_cycle__tag = !vlSymsp->__Vm_even_cycle__tag;

// 提交前 N-1 个线程到线程池
for (i = 0; i < N-1; i++) {
    vlSymsp->__Vm_threadPoolp->workerp(i)->addTask(
        threadFunc_i, vlSelf, even_cycle
    );
}

// 最后一个线程在主线程直接执行
threadFunc_N(vlSelf, even_cycle);

// 等待所有线程完成
vlSelf->__Vm_mtaskstate_final__*.waitUntilUpstreamDone(even_cycle);
```

**特点**：
- 主线程也参与计算（不空转）
- 线程池是固定的（`VerilatedThreadPool`）
- 每个线程按 ThreadSchedule 中的顺序串行执行 MTask

---

## 对 RTL 仿真器多线程化的设计启示

### 1. 静态调度 vs 动态调度

| 维度 | 静态调度（Verilator） | 动态调度（如 TBB） |
|------|----------------------|------------------|
| 运行时开销 | 无调度器开销 | 有任务队列竞争 |
| 负载均衡 | 依赖预测精度 | 自适应更好 |
| 适用场景 | 任务图编译期已知 | 任务图动态变化 |
| RTL 仿真 | ✅ 非常适合 | 过度设计 |

**结论**：RTL 仿真器的任务图（MTask 依赖）在编译期完全确定，静态调度是更优选择。

### 2. 预测误差的工程处理

任务执行时间预测误差 `±60%` 是常态。Verilator 的解法：
- 同线程内：精确时序（无 padding）
- 跨线程时：30% sandbag padding
- 优先级反转保护：确保前驱的 padded 时间不会晚于后继的开始

**启示**：不要假设预测完美，要在调度算法中**内建误差容忍**。

### 3. 无锁同步的重要性

MTask 同步使用计数器 + 等待/通知，没有 mutex：
- 每个 MTask 的同步点是**编译期确定的**
- 只有存在跨线程依赖的 MTask 才需要同步
- 无锁设计避免了线程竞争开销

**启示**：RTL 仿真器的并行粒度较大（MTask 通常包含数千条指令），同步点应该稀疏且编译期可优化。

### 4. 宽任务（Wide Task）隔离

当某些 MTask 需要多个线程（如层次化模块），Verilator 创建**独立的 ThreadSchedule**：
- 防止线程索引冲突
- 简化资源分配逻辑
- 避免与普通任务混调带来的复杂度

**启示**：非均匀资源需求的任务应**隔离调度**，而非在统一调度器中处理。

### 5. Profile-Guided Optimization (PGO)

`fillinCosts()` 支持混合使用：
- 指令计数估计（编译期）
- 实际性能分析数据（运行期）
- 自动归一化和缩放

**启示**：多线程 RTL 仿真器应支持 PGO，用实测数据优化调度质量。

---

## 源码导航

| 组件 | 文件 | 行号 | 功能 |
|------|------|------|------|
| ExecMTask 定义 | V3ExecGraph.h | 30-60 | MTask 数据模型 |
| ThreadSchedule 定义 | V3ExecGraph.cpp | 52-240 | 调度结果存储 |
| PackThreads::pack | V3ExecGraph.cpp | 280-380 | 核心调度算法 |
| completionTime (sandbag) | V3ExecGraph.cpp | 260-290 | 跨线程时序补偿 |
| addMTaskToFunction | V3ExecGraph.cpp | 500-560 | 同步代码生成 |
| createThreadFunctions | V3ExecGraph.cpp | 560-610 | 线程入口函数生成 |
| addThreadStartToExecGraph | V3ExecGraph.cpp | 620-680 | 线程池启动代码 |
| implement | V3ExecGraph.cpp | 730-780 | 主入口函数 |
| processMTaskBodies | V3ExecGraph.cpp | 690-720 | MTask 函数体增强 |
| fillinCosts | V3ExecGraph.cpp | 430-480 | 成本计算 |
| finalizeCosts | V3ExecGraph.cpp | 480-500 | 关键路径计算 |

---

## 相关页面

- [V3Order MTask 划分](wiki-verilator-V3Order.md)
- [V3Graph 通用图](wiki-verilator-V3Graph.md)
- [VerilatedThreadPool](wiki-verilator-ThreadPool.md)

---

*本页由 Verilator 源码分析自动生成，基于 verilator/verilator 仓库 master 分支。*

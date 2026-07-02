---
title: "CXXRTL / Yosys Simulation Loop 内核实现分析：编译时生成与增量求值"
description: 对 Yosys CXXRTL 后端的核心运行时和代码生成进行源码级分析，重点剖析其 eval/commit 两阶段仿真循环、编译时特化的值类型系统、以及基于反馈弧集最小化的调度算法，为多线程 RTL 仿真器设计提供参考。
source_url: "https://github.com/YosysHQ/yosys"
source_type: github-repo
author: "whitequark / Yosys Team"
date: "2026-07-03"
tags: [cxxrtl, yosys, compiled-simulation, delta-cycle, rtlil, feedback-arc-set]
keywords: [cxxrtl, yosys, compiled simulator, eval commit, wire, memory, chunk, flow graph, scheduling]
capture_date: "2026-07-03"
---

# CXXRTL / Yosys Simulation Loop 内核实现分析

## 来源

- URL: `https://github.com/YosysHQ/yosys`
- 类型: github-repo
- 作者: whitequark (CXXRTL 主要作者) / Yosys Team
- 日期: 2026-07-03

## 摘要

CXXRTL 是 Yosys 的 C++ 编译型仿真后端，将 RTLIL（Yosys 中间表示）翻译成专门的 C++ 代码，再利用 C++ 编译器进行激进优化。本文档通过分析 `backends/cxxrtl/runtime/cxxrtl/cxxrtl.h`（运行时库）和 `backends/cxxrtl/cxxrtl_backend.cc`（代码生成器），提取了 CXXRTL 的仿真循环模型、值存储抽象和调度策略的关键实现细节。CXXRTL 代表了 "编译型仿真（compiled simulation）" 方向，与解释型/事件驱动型仿真器有本质不同的并行化潜力。

## 关键要点

### 1. CXXRTL 运行时 — 编译时特化的值类型系统

**文件**: `backends/cxxrtl/runtime/cxxrtl/cxxrtl.h` ([GitHub](https://github.com/YosysHQ/yosys/blob/master/backends/cxxrtl/runtime/cxxrtl/cxxrtl.h))

CXXRTL 的核心创新是**利用 C++ 模板在编译时生成特化的任意位宽算术类型**，避免运行时的位宽检查和动态分配：

```cpp
// backends/cxxrtl/runtime/cxxrtl/cxxrtl.h
typedef uint32_t chunk_t;

template<size_t Bits>
struct value : public expr_base<value<Bits>> {
      static constexpr size_t bits = Bits;
      static constexpr size_t chunks = (Bits + chunk::bits - 1) / chunk::bits;
      chunk::type data[chunks] = {};  // 固定大小的数组，编译时确定

      // 所有操作都是编译时展开的内联函数
      CXXRTL_ALWAYS_INLINE
      value<Bits> add(const value<Bits> &other) const {
            value<Bits> result;
            for (size_t n = 0; n < result.chunks; n++)
                  result.data[n] = data[n] + other.data[n];
            // ...
            return result;
      }
      // ...
};
```

`value<Bits>` 使用 `uint32_t` 作为 chunk，通过 `constexpr` 计算 chunk 数量和 MSB 掩码。这种设计的优势：
- **无动态分配**：所有值类型在编译时确定大小，直接在栈或对象内部分配。
- **编译器优化友好**：C++ 编译器可以展开循环、向量化、甚至将整个表达式常量折叠。
- **FFI 友好**：固定 chunk 大小使得 Python 等外部语言可以通过 `ctypes` 直接访问底层数据。

**Wire（双缓冲状态）**：

```cpp
// backends/cxxrtl/runtime/cxxrtl/cxxrtl.h
template<size_t Bits>
struct wire {
      value<Bits> curr;  // 当前周期值（可读）
      value<Bits> next;  // 下一周期值（eval 阶段写入）
      // ...
      template<class ObserverT>
      bool commit(ObserverT &observer) {
            if (curr != next) {
                  observer.on_update(...);
                  curr = next;
                  return true;  // 发生了状态变化
            }
            return false;
      }
};
```

`wire` 是**双缓冲（double-buffered）**的：
- `eval()` 阶段：组合逻辑读取 `curr`，写入 `next`（或者对于时序逻辑，直接写入 `next`）。
- `commit()` 阶段：如果 `curr != next`，则原子性地交换，并通知 observer。

这种设计天然地将 "计算" 和 "状态更新" 分离开，为多线程化提供了清晰的同步点。

### 2. CXXRTL — 两阶段仿真循环（eval + commit）

**文件**: `backends/cxxrtl/runtime/cxxrtl/cxxrtl.h`

CXXRTL 的顶层仿真循环极其简洁，与 Verilator 的 "eval()" 模型类似：

```cpp
// backends/cxxrtl/runtime/cxxrtl/cxxrtl.h
struct module {
      virtual bool eval(performer *performer = nullptr) = 0;
      virtual bool commit() = 0;

      size_t step(performer *performer = nullptr) {
            size_t deltas = 0;
            bool converged = false;
            do {
                  converged = eval(performer);
                  deltas++;
            } while (commit() && !converged);
            return deltas;
      }
};
```

`step()` 的核心逻辑：
1. `eval()`：执行所有组合逻辑和时序逻辑，计算 `next` 值。返回 `converged` 表示是否没有新的状态变化被引入。
2. `commit()`：将所有 `wire` 的 `next` 提交到 `curr`，返回 `changed` 表示是否有任何状态发生了改变。
3. 如果 `commit()` 返回 true（有变化）且 `eval()` 未收敛，则继续循环（delta cycle）。

**与事件驱动仿真器的本质区别**：
- **无事件队列**：没有 `schedule` 或 `event queue`。所有计算都是确定性的函数求值。
- **无 stratified queue**：非阻塞赋值、阻塞赋值等语义在代码生成阶段就被静态转换成了 `wire` 和 `value` 的读写模式。
- **Delta cycle 由编译期拓扑排序控制**：如果设计中有组合环（benign SCC），`step()` 需要多次迭代才能收敛；如果无环，一次 `eval()` + `commit()` 即可收敛。

### 3. Yosys CXXRTL 后端 — 调度与代码生成

**文件**: `backends/cxxrtl/cxxrtl_backend.cc` ([GitHub](https://github.com/YosysHQ/yosys/blob/master/backends/cxxrtl/cxxrtl_backend.cc))

CXXRTL 后端需要为每个 RTLIL 模块生成一个 `module` 子类。代码生成面临的核心问题是：**RTLIL 中的 cell、process、wire 之间存在数据依赖，需要确定一个合法的求值顺序**。

后端使用了 **Feedback Arc Set (FAS) 最小化启发式算法**（基于 Eades-Lin-Smyth 1993 论文）来对 RTLIL 的依赖图进行拓扑排序：

```cpp
// backends/cxxrtl/cxxrtl_backend.cc
// 引用: Peter Eades; Xuemin Lin; W. F. Smyth,
// "A Fast Effective Heuristic For The Feedback Arc Set Problem"
// Information Processing Letters, Vol. 47, pp 319-323, 1993

template<class T>
struct Scheduler {
      struct Vertex {
            T *data;
            pool<Vertex*> preds, succs;
            int delta() const { return succs.size() - preds.size(); }
      };
      std::vector<Vertex*> schedule() {
            // 1. 反复移除 sink 节点（无后继）到 s2
            // 2. 反复移除 source 节点（无前驱）到 s1
            // 3. 从剩余节点中选取 delta 最大（出度-入度最大）的节点移除到 s1
            // 4. 最后 s1 + reverse(s2) 即为近似最优排序
      }
};
```

这个调度算法在 `FlowGraph` 上运行。`FlowGraph` 将 RTLIL 的 connect、cell、process、memory 抽象为统一的 `Node`，并分析它们的定义-使用关系（def-use）：

```cpp
// backends/cxxrtl/cxxrtl_backend.cc
struct FlowGraph::Node {
      enum class Type {
            CONNECT, CELL_SYNC, CELL_EVAL, EFFECT_SYNC,
            PROCESS_SYNC, PROCESS_CASE, MEM_RDPORT, MEM_WRPORTS
      };
      // 每种节点类型记录其 comb/sync 定义和使用的 wire
};
```

**Wire 类型分类**：后端根据数据流分析将 wire 分为 8 种类型，直接决定了生成的 C++ 代码中的存储方式：

| 类型 | 含义 | 生成代码 |
|------|------|----------|
| `BUFFERED` | 时序/状态信号 | `wire<Bits>` 类成员 |
| `MEMBER` | 组合输出，但需保留 | `value<Bits>` 类成员 |
| `OUTLINE` | 按需重新计算（debug） | `value<Bits>` + 延迟求值 |
| `LOCAL` | 局部变量 | `value<Bits>` eval 方法局部变量 |
| `INLINE` | 可内联表达式 | 直接替换为右值表达式 |
| `ALIAS` | wire 别名 | 替换为对另一 wire 的引用 |
| `CONST` | 常量 | 替换为常量值 |
| `UNUSED` | 未使用 | 不生成代码 |

### 4. 存储模型：Memory 的 Write Queue

**文件**: `backends/cxxrtl/runtime/cxxrtl/cxxrtl.h`

CXXRTL 的存储器（`memory<Width>`）使用了**写队列（Write Queue）**来简化多端口写入的优先级处理：

```cpp
// backends/cxxrtl/runtime/cxxrtl/cxxrtl.h
template<size_t Width>
struct memory {
      struct write {
            size_t index;
            value<Width> val;
            value<Width> mask;
            int priority;
      };
      std::vector<write> write_queue;

      void update(size_t index, const value<Width> &val,
                  const value<Width> &mask, int priority = 0) {
            // 按 priority 插入到队列中
            write_queue.insert(...);
      }

      bool commit(ObserverT &observer) {
            for (const write &entry : write_queue) {
                  value<Width> elem = data[entry.index];
                  elem = elem.update(entry.val, entry.mask);
                  data[entry.index] = elem;
            }
            write_queue.clear();
      }
};
```

在 `eval()` 阶段，所有写入操作被记录到 `write_queue` 中；在 `commit()` 阶段，按优先级顺序一次性应用。这种设计避免了在 `eval()` 阶段就修改存储器状态，从而允许多个写入端口在 `eval()` 阶段并行计算。

## 对 RTL 仿真器多线程化的启示

1. **编译型仿真的并行化优势**：CXXRTL 的 `eval()` 本质上是一个纯函数（在给定 `curr` 状态下，计算所有 `next`），没有全局事件队列的锁竞争。这意味着：
   - **模块级并行**：如果设计中有多个不相互依赖的子模块，它们的 `eval()` 可以并行执行。
   - **数据流并行**：`eval()` 方法内部由大量独立的 `value<Bits>` 运算组成，C++ 编译器可以自动向量化，甚至可以用 OpenMP/TBB 进行任务并行。

2. **eval/commit 屏障作为同步点**：`commit()` 是唯一的全局状态修改点。如果要在多线程环境中运行 CXXRTL，可以：
   - 并行执行多个 `eval()` 任务（只读 `curr`，只写 `next`）。
   - 在全局屏障处串行执行 `commit()`（或按依赖图分阶段 commit）。
   这与 GHDL 的 "进程并行 + 信号串行更新" 模型异曲同工，但 CXXRTL 的粒度更细（wire 级而非进程级）。

3. **拓扑排序决定并行上限**：`FlowGraph` 的调度算法已经给出了 RTLIL 级别的依赖图。如果我们在运行时保留这个依赖图，可以：
   - 识别无依赖的节点（独立 cell、process），在多个线程上并行 `eval()`。
   - 对于反馈弧（feedback arcs），必须保留 delta-cycle 语义，按顺序迭代直到收敛。
   - 这与 Verilator 的 "静态调度 + 多线程分块" 策略非常相似，可以作为我们多线程 RTL 仿真器的直接参考。

## 原文摘录

> "CXXRTL essentially uses the C++ compiler as a hygienic macro engine that feeds an instruction selector. It generates a lot of specialized template functions with relatively large bodies that, when inlined into the caller and (for those with loops) unrolled, often expose many new optimization opportunities."
> — `backends/cxxrtl/runtime/cxxrtl/cxxrtl.h`, 注释

> "A topological sort is always possible in a fully flattened RTLIL design without processes or logic loops where every wire has a single driver. Logic loops are illegal in RTLIL and wires with multiple drivers can be split by the `splitnets` pass; however, interdependencies between processes or module instances can create strongly connected components without introducing evaluation nondeterminism. We wish to support designs with such benign SCCs..."
> — `backends/cxxrtl/cxxrtl_backend.cc`, 注释

> "For maximum performance, the state of the simulation (which is the same as the set of its double buffered wires, since using a singly buffered wire for any kind of state introduces a race condition) should contain..."
> — `backends/cxxrtl/cxxrtl_backend.cc`, 注释

## 性能数据

| 指标 | CXXRTL |
|------|--------|
| 仿真类型 | 编译型（C++ 模板特化） |
| 值存储 | `value<Bits>`（固定 chunk 数组，编译时大小） |
| 状态更新 | 双缓冲 `wire<Bits>`（curr/next） |
| 事件模型 | 无事件队列，纯 eval/commit 循环 |
| 调度策略 | 静态拓扑排序 + FAS 启发式（编译时确定） |
| Delta Cycle | 由 `step()` 循环处理，收敛即停 |
| 内存模型 | `memory<Width>` 写队列 + 优先级提交 |
| 多线程潜力 | 高（eval 只读 curr，commit 是唯一切换点） |

## 相关链接

- [Yosys CXXRTL 文档](https://yosyshq.net/yosys/documentation.html)
- [CXXRTL 运行时代码](https://github.com/YosysHQ/yosys/tree/master/backends/cxxrtl/runtime/cxxrtl)
- [cxxrtl_backend.cc](https://github.com/YosysHQ/yosys/blob/master/backends/cxxrtl/cxxrtl_backend.cc)
- [Eades-Lin-Smyth FAS 论文](https://pdfs.semanticscholar.org/c7ed/d9acce96ca357876540e19664eb9d976637f.pdf)

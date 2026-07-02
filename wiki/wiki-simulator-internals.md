---
id: "wiki-simulator-internals"
title: "开源仿真器内核实现对比"
description: "对比 Icarus VVP、GHDL GRT、CXXRTL、SystemC 四大开源仿真器内核的事件调度、值存储、仿真循环与并行化策略，提炼对多线程 RTL 仿真器的可操作建议"
tags: ["simulator-kernel", "icarus", "ghdl", "cxxrtl", "systemc", "event-scheduler", "parallelization"]
keywords: ["VVP", "GRT", "delta-cycle", "eval-commit", "FAS", "双缓冲", "stratified-event-queue", "frontend-parser"]
related_sources:
  - "source-icarus-ghdl-internals"
  - "source-cxxrtl-internals"
  - "source-surelog-slang-internals"
  - "source-systemc-kernel"
last_updated: "2026-07-03"
---

# 开源仿真器内核实现对比

## 概述

本文档对比四个主流开源仿真器内核——Icarus Verilog VVP、GHDL GRT、Yosys CXXRTL、SystemC——在事件调度、值存储结构、仿真循环模型和并行化潜力上的核心实现差异。这些差异直接决定了多线程 RTL 仿真器应借鉴什么、规避什么。

---

## 1. Icarus VVP：分层事件队列与完全串行模型

### 1.1 分层事件队列（7 子队列）

Icarus Verilog 的 VVP 运行时严格遵循 IEEE 1364 的 **stratified event queue** 语义。每个时间步（`event_time_s`）内部包含 **7 个事件子队列**，按优先级轮转执行：

```cpp
// vvp/schedule.cc
struct event_time_s {
    vvp_time64_t delay;
    struct event_s *start;      // T0 开始事件（cbAtStartOfSimTime）
    struct event_s *active;     // Active 事件（阻塞赋值、门级求值）
    struct event_s *inactive;   // Inactive 事件（#0 延迟）
    struct event_s *nbassign;   // Non-blocking assign（非阻塞赋值）
    struct event_s *rwsync;     // Read-write sync（$readmem 等）
    struct event_s *rosync;     // Read-only sync（$monitor 等）
    struct event_s *del_thr;    // 待删除线程
    struct event_time_s *next;  // 下一时间步链表
};
```

调度顺序：`active → inactive → nbassign → rwsync → rosync`。这确保了非阻塞赋值在 active 事件之后执行，read-only 同步在最后执行。

```cpp
// schedule_simulate() 主循环：按顺序轮转队列，逐个执行事件
while (sched_list) {
    struct event_time_s *ctim = sched_list;
    // 将 inactive 事件提升到 active
    if (ctim->active == 0) {
        ctim->active = ctim->inactive;
        ctim->inactive = 0;
        // 继续轮转 nbassign, rwsync, rosync...
    }
    struct event_s *cur = ctim->active->next;
    cur->run_run();   // 虚函数分派，执行单个事件
    delete (cur);     // 使用 slab 分配器回收
}
```

### 1.2 vvp_vector4_t：双位分离存储

VVP 使用 `vvp_vector4_t` 存储四值逻辑，采用 **双位分离（split abits/bbits）** 编码：

```cpp
// vvp/vvp_net.h
class vvp_vector4_t {
    unsigned size_;
    union {
        unsigned long abits_val_;   // 小向量：内联存储
        unsigned long *abits_ptr_;  // 大向量：堆分配
    };
    union {
        unsigned long bbits_val_;
        unsigned long *bbits_ptr_;
    };
    // 编码: abit=0, bbit=0 → 0; abit=1,bbit=0 → 1; abit=1,bbit=1 → X; abit=0,bbit=1 → Z
};
```

| 编码 | abit | bbit | 值 | 说明 |
|------|------|------|-----|------|
| 00 | 0 | 0 | 0 | 明确低电平 |
| 01 | 1 | 0 | 1 | 明确高电平 |
| 10 | 1 | 1 | X | 未知/未初始化 |
| 11 | 0 | 1 | Z | 高阻态 |

### 1.3 vvp_net_t：4 输入网络 → 完全串行传播

网络节点 `vvp_net_t` 是一个固定 4 输入、无限输出的 fan-in 结构：

```cpp
// vvp/vvp_net.h
class vvp_net_t {
    vvp_net_ptr_t port[4];    // 4 个输入端口
    vvp_net_fun_t *fun;       // 计算逻辑（与门、或门、触发器等）
    vvp_net_fil_t *fil;       // 输出过滤器（force/release 语义）
    vvp_net_ptr_t out_;     // 输出链（链表实现无限 fan-out）
};
```

值传播通过 `vvp_send_vec4()` 沿着输出链表**递归触发**下游节点的 `recv_vec4()`，形成深度递归的波形传播链。所有传播发生在**同一线程**，天然难以并行化。

### 1.4 对多线程的启示

- **分层队列是顺序化堡垒**：7 子队列的严格优先级意味着事件之间高度耦合，很难拆分为独立任务。
- **递归传播链是共享状态陷阱**：`vvp_send_vec4` 的递归调用会动态修改下游节点状态，导致线程间竞争无法静态预测。
- **/slab 分配器是单线程优化**：`slab_t` 分配器避免了 `malloc` 开销，但假设了单线程无竞争。

---

## 2. GHDL GRT：Delta-Cycle + 进程级并行

### 2.1 标准 Delta-Cycle 仿真循环

GHDL 的 GRT（GHDL Run Time）严格遵循 VHDL LRM 的 delta-cycle 语义：

```ada
-- src/grt/grt-processes.adb
function Simulation_Cycle return Integer is
   Current_Time := Next_Time;                    -- a) 时间推进到 Tn
   if Current_Delta = 0 then Call_Callbacks(...); end if;  -- b) VPI 回调
   Update_Signals;                               -- c) 更新信号（驱动器 → 有效值）
   if Current_Time = Process_First_Timeout then  -- d) 恢复超时进程
       Resume_Process(...);
   end if;
   Status := Run_Processes (Postponed => False); -- e) 运行非延迟进程
   Tn := Compute_Next_Time;                      -- f) 计算下一时间
   if Tn = Current_Time then Current_Delta := Current_Delta + 1; end if; -- g) delta 递增
```

### 2.2 Run_Processes：多线程执行，Update_Signals：单线程瓶颈

GHDL 支持 `--threads=N` 选项，在 `Run_Processes` 中通过 `Threads.Run_Parallel` 将进程恢复表分发给多个 OS 线程：

```ada
-- src/grt/grt-processes.adb : Run_Processes
if Options.Nbr_Threads = 1 then
    for I in 1 .. Last loop
        Proc.Subprg.all (Proc.This);  -- 串行执行
    end loop;
else
    Mt_Last := Last;
    Mt_Table := Table;
    Mt_Index := 1;
    Threads.Run_Parallel (Run_Processes_Threads'Access);  -- 并行执行
end if;
```

**关键瓶颈**：`Update_Signals` 和进程调度本身仍然是**单线程**。`Update_Signals` 按 `Order_All_Signals` 预先计算的拓扑序逐个更新信号，必须串行执行以避免竞争条件。

### 2.3 信号事务与驱动器模型

GHDL 的信号系统基于**事务链表**和**驱动器**模型：

```ada
-- src/grt/grt-signals.adb
type Driver_Type is record
    First_Trans : Transaction_Acc;  -- 头事务（当前值）
    Last_Trans  : Transaction_Acc;  -- 尾事务（最新调度）
    Proc        : Process_Acc;      -- 所属进程
end record;

type Transaction is record
    Kind : Transaction_Kind;  -- Trans_Value, Trans_Null, Trans_Direct, Trans_Error
    Time : Std_Time;          -- 调度时间
    Next : Transaction_Acc;
    Val  : Value_Union;       -- 值（多态联合）
end record;
```

`Signal_Active_Chain` 和 `Future_List` 分别跟踪下一 delta 周期和未来时间步需要更新的信号。这种**事务调度 → 批量更新**的两阶段协议，将「并行计算」和「串行提交」分离开。

### 2.4 对多线程的启示

- **两阶段协议是并行化的可行路径**：「并行执行进程 → 串行更新信号」的模型已被 GHDL 验证。
- **并行加速比受限于串行瓶颈**：`Update_Signals` 的单线程特性意味着加速比存在上限，类似于 Amdahl 定律中的串行部分。
- **拓扑排序是避免动态锁的关键**：`Order_All_Signals` 的静态分析预先确定了更新顺序，避免了运行时动态调度的竞争。

---

## 3. CXXRTL：编译时特化 + 双缓冲 + FAS 调度

### 3.1 value<Bits>：编译时特化的任意位宽类型

CXXRTL 的核心创新是**利用 C++ 模板在编译时生成特化的值类型**：

```cpp
// backends/cxxrtl/runtime/cxxrtl/cxxrtl.h
typedef uint32_t chunk_t;

template<size_t Bits>
struct value : public expr_base<value<Bits>> {
    static constexpr size_t bits = Bits;
    static constexpr size_t chunks = (Bits + chunk::bits - 1) / chunk::bits;
    chunk::type data[chunks] = {};  // 固定大小数组，编译时确定

    CXXRTL_ALWAYS_INLINE
    value<Bits> add(const value<Bits> &other) const {
        value<Bits> result;
        for (size_t n = 0; n < result.chunks; n++)
            result.data[n] = data[n] + other.data[n];
        return result;
    }
};
```

**优势**：
- 无动态分配，栈/对象内直接分配
- C++ 编译器可展开循环、向量化、常量折叠
- 固定 chunk 大小便于 FFI（Python ctypes 直接访问）

### 3.2 wire：双缓冲状态管理

`wire` 是**双缓冲（double-buffered）**的，天然将「计算」和「状态更新」分离开：

```cpp
// backends/cxxrtl/runtime/cxxrtl/cxxrtl.h
template<size_t Bits>
struct wire {
    value<Bits> curr;  // 当前周期值（eval 阶段只读）
    value<Bits> next;  // 下一周期值（eval 阶段写入）

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

**两阶段协议**：
- `eval()` 阶段：组合逻辑读取 `curr`，计算并写入 `next`（只读共享状态，只写私有 `next`）
- `commit()` 阶段：如果 `curr != next`，原子性交换并通知 observer（唯一全局状态修改点）

### 3.3 eval/commit 两阶段仿真循环

CXXRTL 的顶层仿真循环极其简洁：

```cpp
// backends/cxxrtl/runtime/cxxrtl/cxxrtl.h
struct module {
    virtual bool eval(performer *performer = nullptr) = 0;
    virtual bool commit() = 0;

    size_t step(performer *performer = nullptr) {
        size_t deltas = 0;
        bool converged = false;
        do {
            converged = eval(performer);   // 计算所有 next 值
            deltas++;
        } while (commit() && !converged);  // 提交状态，若变化则继续 delta
        return deltas;
    }
};
```

**与事件驱动仿真的本质区别**：
- 无事件队列，无 stratified queue
- 非阻塞/阻塞赋值语义在代码生成阶段静态转换
- Delta cycle 由编译期拓扑排序控制

### 3.4 FAS 调度：Feedback Arc Set 最小化

CXXRTL 后端使用 **Eades-Lin-Smyth 1993 启发式算法**对 RTLIL 依赖图进行拓扑排序：

```cpp
// backends/cxxrtl/cxxrtl_backend.cc
// 引用: Eades, Lin, Smyth — "A Fast Effective Heuristic For the Feedback Arc Set Problem"

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

Wire 类型分类直接决定生成代码的存储方式：

| 类型 | 含义 | 生成代码 |
|------|------|----------|
| `BUFFERED` | 时序/状态信号 | `wire<Bits>` 类成员 |
| `MEMBER` | 组合输出，需保留 | `value<Bits>` 类成员 |
| `OUTLINE` | 按需重新计算（debug） | `value<Bits>` + 延迟求值 |
| `LOCAL` | 局部变量 | `value<Bits>` eval 方法局部变量 |
| `INLINE` | 可内联表达式 | 直接替换为右值表达式 |
| `ALIAS` | wire 别名 | 替换为对另一 wire 的引用 |
| `CONST` | 常量 | 替换为常量值 |
| `UNUSED` | 未使用 | 不生成代码 |

### 3.5 对多线程的启示

- **eval 是天然并行点**：`eval()` 只读 `curr`、只写 `next`，多个模块的 `eval()` 可并行执行。
- **commit 是全局同步屏障**：唯一状态修改点，可按依赖图分阶段 commit。
- **静态依赖图决定并行上限**：`FlowGraph` 的调度算法已给出 RTLIL 级依赖图，可直接用于运行时并行调度。

---

## 4. SystemC：四状态机 + Evaluate-Update + 并行化引擎

### 4.1 四状态机与 Evaluate-Update 循环

SystemC 内核是一个**基于协程的合作式单线程调度器**，通过离散事件模拟（DES）管理时间推进：

```cpp
// sc_start() 伪代码 —— 简化但准确
void simulation_loop() {
    while (!done) {
        evaluate_update_loop();           // 处理当前时刻所有 delta cycle
        next_time = time_queue.next_wakeup();
        if (next_time == INFINITY) break; // 无事件，结束
        current_time = next_time;
        runnable_queue.add(time_queue.pop_due(current_time));
    }
}

void evaluate_update_loop() {
    while (runnable_queue not empty) {
        // ── Evaluate Phase ──
        while (runnable_queue not empty) {
            p = runnable_queue.pick_one();  // 顺序未指定
            p.resume();                      // 运行到 wait() 或 return
        }
        // ── Update Phase ──
        for each channel c in update_queue:
            c.update();                      // new_value → current_value
            if value_changed:
                runnable_queue.add(c.sensitive_processes);
        update_queue.clear();
    }
}
```

进程状态：Initialized → Runnable → Waiting → Terminated。`SC_THREAD` 靠 `wait()` 挂起栈；`SC_METHOD` 靠函数返回，无持久栈上下文。

### 4.2 事件通知三队列

```cpp
EQ_imm    // 即时通知（notify()）
EQ_delta  // 零延迟通知（notify(SC_ZERO_TIME)）
EQ_timed  // 定时通知（notify(delay)）
```

所有远程通知在 SCOPE 并行内核中统一为 timed 通知，需用 mutex 保护。

### 4.3 并行化引擎：4–8x 加速已验证

| 方案 | 平台 | 核心数 | 加速比 | 机制 |
|------|------|--------|--------|------|
| **SCOPE** (Weinstock) | 真实 VP | 8 | **4–8×** | 时间解耦 + 多调度器同步 |
| **parSC** (Schumacher) | 通用模型 | 4–8 | 良好（含超线性） | Master-worker + barrier 同步 |
| **SCGPSim** | NVIDIA GPU | 数百 CUDA cores | 显著 | 内核映射到 CUDA 线程 |
| **Jones 乐观式** | 双核 SMP | 2 | 1.5–2× | 全局 quantum 约束 |

**SCOPE 的远程事件触发算法**（关键创新）：

```cpp
// Algorithm 5.2: Trigger decision for remote events
Function TRIGGERDecision(RemoteEvent e)
    requests ← H_e[t_e ... t_i - Δt_la];  // 提取相关历史
    t_act ← ∞;
    while requests ≠ ∅ do
        r ← extract earliest from requests;
        if r is cancel then t_act ← ∞;           // 远程取消
        else if t_r < t_act then t_act ← t_r;    // 远程通知覆盖
    end
    if t_act == t_i then
        RQ ← RQ ∪ S_e ∪ D_e;  // 触发事件
        D_e ← ∅;
        t_e ← t_i;
    end
End
```

---

## 5. 前端对比：Surelog vs slang

SystemVerilog 前端解析器的选型直接影响仿真器的编译速度和内存效率。

### 5.1 Surelog：ANTLR4 + NodeId + UHDM

```cpp
// include/Surelog/Common/NodeId.h
// NodeId 作为 AST 节点的索引，FileContent 拥有实际 AST 树

// src/DesignCompile/UhdmWriter.cpp
#include <uhdm/Serializer.h>
#include <uhdm/uhdm.h>
```

- **多层级转换**：Source → ANTLR AST → Surelog AST → UHDM → VPI，内存和性能开销不可忽视
- **多线程**：文件级并行解析，但 elaboration 和 UHDM 生成是单线程
- **优势**：标准化 VPI 接口，兼容商业工具，已被 Yosys/Verilator/Cocotb 采用

### 5.2 slang：手写 C++17 递归下降 + 实例缓存

- **手写解析器**：无 ANTLR 运行时开销（预测表查找、LL(*) 回溯）
- **实例缓存（v9.0+）**：结构等价的模块实例重用 elaborated 结果，数量级加速
- **数据流分析**：完整框架，可直接复用于仿真器静态调度

### 5.3 性能对比

| 指标 | Surelog | slang |
|------|---------|-------|
| 解析器类型 | ANTLR4 生成 | 手写 C++17 递归下降 |
| AST 表示 | NodeId 索引 + FileContent | 紧凑 SyntaxNode + Symbol 表 |
| 中间表示 | UHDM (Cap'n Proto) | 直接语义模型 |
| 多线程 | 文件级并行解析 | 主要单线程 |
| Elaboration 优化 | 无实例缓存 | 实例缓存（v9.0+） |
| 数据流分析 | 有限 | 完整框架 |
| SV 合规性 (sv-tests) | ~95% | ~99%+ |
| 构建依赖 | ANTLR4, UHDM, Cap'n Proto | 仅 C++17 标准库 + fmt |
| 内存占用 | 较大 | 较小（内存池） |

---

## 6. 对多线程 RTL 仿真器的启示

### 6.1 内核设计启示

| 仿真器 | 可借鉴之处 | 应规避之处 |
|--------|-----------|-----------|
| **Icarus VVP** | 分层队列语义正确性 | 递归传播的共享状态；完全串行模型 |
| **GHDL GRT** | 两阶段：并行进程 + 串行信号更新 | Update_Signals 单线程瓶颈 |
| **CXXRTL** | 双缓冲 + eval/commit 两阶段；静态 FAS 调度 | 编译时间较长；不支持完整延迟模型 |
| **SystemC** | Evaluate-Update 分离；SCOPE/parSC 并行经验 | 协程开销重；集中式事件队列锁竞争 |

### 6.2 前端选型启示

- **频繁重新编译场景**：选 slang，解析速度优势缩短 edit-compile-run 循环
- **多工具共享场景**：选 Surelog + UHDM，标准化 VPI 接口兼容性更好
- **多线程遍历**：slang 的紧凑 AST 更适合并行 linting / elaboration
- **结构等价缓存**：slang 的实例缓存可直接借鉴，将 elaboration 从 O(N) 降到 O(独特模块数)

---

## 7. 可操作建议

### 7.1 采用 eval/commit 两阶段模型

```cpp
// 推荐的多线程 RTL 仿真循环结构
class MultithreadedSimulator {
    Phase phase_ = Phase::kEval;

    void step() {
        bool changed = true;
        size_t delta = 0;
        while (changed && delta < max_delta) {
            // Phase 1: 并行 eval — 只读 curr，只写 next
            changed = parallel_eval();  // 多线程安全：无共享写

            // Phase 2: 全局 barrier
            barrier_wait();

            // Phase 3: 串行或分阶段 commit
            changed = commit_all();     // 唯一状态切换点

            // Phase 4: 再次 barrier
            barrier_wait();
            delta++;
        }
    }
};
```

### 7.2 双缓冲状态管理

```cpp
// 每线程的求值上下文
template<size_t Bits>
struct ThreadLocalEvalCtx {
    value<Bits> next;  // 本线程 eval 阶段写入 next
};

// 全局 wire：双缓冲 + 观察者模式
template<size_t Bits>
struct DoubleBufferedWire {
    value<Bits> curr;         // 只读（eval 阶段）
    std::atomic<bool> dirty;  // 标记 next 是否被写入
    value<Bits> next;         // 各线程 eval 后写入（需按依赖合并）

    bool commit() {
        if (dirty.load()) {
            curr = next;       // 单线程 commit 阶段执行
            dirty.store(false);
            return true;
        }
        return false;
    }
};
```

### 7.3 静态 FAS 调度图

```cpp
// 编译时构建的静态调度图
struct StaticSchedule {
    std::vector<std::vector<NodeId>> levels;  // 按层级分组的节点
    std::vector<NodeId> feedback_arcs;         // 反馈弧（需迭代收敛）

    // 同层节点无数据依赖，可并行 eval
    void parallel_eval_level(size_t level) {
        for (NodeId node : levels[level]) {
            thread_pool.submit([=] { eval_node(node); });
        }
        thread_pool.wait_all();  // barrier
    }
};
```

### 7.4 检查清单

- [ ] 仿真循环是否明确分为 eval 和 commit 两个阶段？
- [ ] 状态信号是否使用双缓冲（curr/next）？
- [ ] 是否通过静态分析（拓扑排序/FAS）预先确定求值顺序？
- [ ] 组合逻辑节点是否按层级分组，同层节点可并行？
- [ ] 反馈弧（组合环）是否被识别并特殊处理（delta 迭代）？
- [ ] commit 阶段是否单线程或按依赖分阶段执行？
- [ ] 前端选型是否匹配使用场景（slang for 速度 / Surelog for 兼容性）？

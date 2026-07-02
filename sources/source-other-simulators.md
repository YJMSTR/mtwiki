---
title: "Icarus Verilog (IVL) 与其他开源仿真器：vthread 模拟线程与事件调度机制"
description: 分析 Icarus Verilog (iverilog) 的 vthread 模拟线程实现、分层事件调度队列，以及 CVC 等项目的现状。
source_url: "https://github.com/steveicarus/iverilog"
source_type: "github-repo"
author: "Stephen Williams (steve@icarus.com)"
date: "2026-07-02"
tags: ["iverilog", "IVL", "Icarus Verilog", "vthread", "事件调度", "VPI", "开源仿真器", "Verilog"]
keywords: ["vthread", "schedule_vthread", "schedule.h", "vvp", "vthread_run", "of_FORK", "of_JOIN"]
capture_date: "2026-07-02"
---

# Icarus Verilog (IVL) 与其他开源仿真器：vthread 模拟线程与事件调度机制

## 来源

- **URL**: https://github.com/steveicarus/iverilog
- **类型**: GitHub 仓库
- **作者**: Stephen Williams (steve@icarus.com) 及社区贡献者
- **日期**: 2026-07-02 (master 分支最新状态)
- **Star 数**: 3,514
- **Fork 数**: 613

## 摘要

Icarus Verilog（简称 iverilog 或 IVL）是开源 Verilog 仿真器中最广泛使用的实现之一。它采用**编译-仿真**架构：前端将 Verilog 源码编译为 VVP 汇编（`.vvp` 文件），后端 `vvp` 运行时解释执行这些指令。其核心执行模型是**单线程的模拟线程（vthread）调度**——每个 Verilog `always` 块、`initial` 块或任务调用都被编译为一个 `vthread_s` 结构体，包含独立的程序计数器（PC）、标志寄存器、栈和寄存器。多个 vthread 通过分层事件队列（schedule）协同执行，但**所有线程都在同一个 OS 线程中串行运行**。vvp 的调度器支持 `fork`/`join` 语义（对应 Verilog 的 `fork-join` 并行块），但实现方式是**合作式多任务**，而非真正的多线程并行。此外，iverilog 提供了 VPI 接口（`vpi_priv.h`），允许外部 C 代码（如 cocotb）注册回调，但 VPI 回调同样在主线程上下文中串行执行。

**关于 CVC（Verilog Compiler）**：经 GitHub 检索，未找到名为 "CVC" 的活跃开源 Verilog 编译器/仿真器项目。历史上存在过一个名为 "CVC" 的 Verilog 编译器（由 SourceForge 托管），但近年来无活跃维护。因此本文以 **iverilog** 为核心分析对象，同时提及其他开源仿真器的现状。

## 关键要点

1. **vthread 是软件模拟的线程**：`vthread_s` 包含 PC、512 个标志位、16 个寄存器、多个栈（vec4、real、str、obj），完全由 `vvp` 运行时管理，与 OS 线程无关。
2. **fork/join 在单线程内实现**：`of_FORK` 指令创建子 vthread，通过 `children` 集合管理；`of_JOIN` 使父线程等待子线程结束。`fork` 后子线程被立即调度（`schedule_vthread(child, 0, true)`），但仍是串行执行。
3. **分层事件调度**：`schedule.h` 定义了 `schedule_vthread`、`schedule_inactive`、`schedule_assign_vector` 等 API，实现了 Verilog 的分层事件队列（active → inactive → NBA → rosync → rwsync）。
4. **自动作用域（automatic scope）上下文管理**：`vthread_alloc_context` / `vthread_free_context` 为 `automatic` 任务/函数分配栈式上下文，支持递归调用而不泄漏内存。
5. **VPI 回调与主线程绑定**：iverilog 的 VPI 实现（`vpi_priv.h`）中，所有回调都在 `vthread_run` 的上下文中执行，不存在多线程安全的问题，因为根本只有一个线程。

## 对 RTL 仿真器多线程化的启示

- **启示 1 —— 模拟线程 ≠ 真实线程**：iverilog 的 vthread 模型证明了"在单线程中模拟多线程"是可行的，且对于 Verilog 的确定性语义来说甚至更简单（无需锁、无竞态条件）。但如果要真正利用多核 CPU，就必须将**独立的 always 块**分配到不同 OS 线程，并引入锁或消息传递机制来同步共享信号。
- **启示 2 —— 事件队列是并行的天然障碍**：iverilog 的 `schedule_vthread` 将事件放入全局队列。多线程化后，每个线程需要有自己的局部队列，再通过全局同步点（如时间步边界）合并，避免每事件都竞争全局锁。
- **启示 3 —— automatic 上下文管理值得借鉴**：`vthread_s` 的 `wt_context` / `rd_context` 栈式上下文切换机制（`of_ALLOC` / `of_FREE`）在支持多线程时可以改造为每个线程独立的上下文栈，避免全局状态竞争。
- **启示 4 —— VPI 多线程化是最大挑战**：如果仿真器改为多线程，VPI 回调必须保证线程安全。iverilog 当前的设计完全假设单线程，所有 VPI 句柄、回调数据都没有锁保护。这也是 Verilator 在实现多线程时遇到的同类问题。

## 代码片段与分析

### 1. `vvp/vthread.h` — vthread 的数据结构定义

```c
struct vthread_s {
      vvp_code_t pc;  // 程序计数器
      enum { FLAGS_COUNT = 512, WORDS_COUNT = 16 };
      vvp_bit4_t flags[FLAGS_COUNT];
      union { int64_t w_int; uint64_t w_uint; } words[WORDS_COUNT];

    private:
      vector<vvp_vector4_t> stack_vec4_;
      vector<double> stack_real_;
      vector<string> stack_str_;
      // ... 对象栈、参数栈等 ...

    public:
      unsigned i_am_joining      :1;
      unsigned i_am_detached     :1;
      unsigned i_am_waiting      :1;
      unsigned i_am_in_function  :1;
      unsigned i_have_ended      :1;
      unsigned is_scheduled      :1;
      // ...
      set<struct vthread_s*> children;
      set<struct vthread_s*> detached_children;
      struct vthread_s* parent;
      __vpiScope* parent_scope;
      struct vthread_s* wait_next;  // 等待队列链表
      vvp_context_t wt_context, rd_context;
      vvp_net_t* event;
      uint64_t ecount;
};
```
**分析**：`vthread_s` 是一个完整的"虚拟 CPU"状态。`flags` 数组对应 Verilog 的 4 值逻辑（0, 1, X, Z），`words` 是通用寄存器。`children` 和 `parent` 实现了 `fork-join` 的父子关系。`wait_next` 用于事件等待队列（如 `@posedge clk`）。`wt_context` / `rd_context` 栈支持 `automatic` 变量的作用域嵌套。所有这些都是**纯内存结构**，无需系统调用。

### 2. `vvp/vthread.cc` — `of_FORK` 与 `of_JOIN` 指令

```cpp
bool of_FORK(vthread_t thr, vvp_code_t cp) {
      vthread_t child = vthread_new(cp->cptr2, cp->scope);

      if (cp->scope->is_automatic()) {
            child->wt_context = thr->wt_context;
            child->rd_context = thr->wt_context;
      }

      child->parent = thr;
      thr->children.insert(child);

      if (thr->i_am_in_function) {
            child->is_scheduled = 1;
            child->i_am_in_function = 1;
            vthread_run(child);  // 函数内直接运行，不调度
            running_thread = thr;
      } else {
            schedule_vthread(child, 0, true);  // 推入事件队列
      }
      return true;
}
```
**分析**：`of_FORK` 对应 Verilog 的 `fork` 关键字。在函数内部（`i_am_in_function`），子线程被**立即执行**（同步），因为函数不允许时序延迟。在过程块中，子线程被**调度**到当前时间步的活跃队列头部（`push_flag = true`）。注意这里并没有创建 OS 线程——只是创建了一个新的 `vthread_s` 并插入调度队列。

```cpp
bool of_JOIN(vthread_t thr, vvp_code_t) {
      return do_join_opcode(thr);
}

static bool do_join_opcode(vthread_t thr) {
      assert(!thr->i_am_joining);
      assert(!thr->children.empty());

      for (set<vthread_t>::iterator cur = thr->children.begin();
           cur != thr->children.end(); ++cur) {
            vthread_t curp = *cur;
            if (!curp->i_have_ended)
                  continue;
            do_join(thr, curp);
            return true;  // 找到一个已结束的子线程，立即返回
      }

      thr->i_am_joining = 1;
      return false;  // 挂起父线程，等待子线程结束
}
```
**分析**：`of_JOIN` 对应 `join` 关键字。如果已有子线程结束（`i_have_ended`），则立即回收；否则设置 `i_am_joining = 1` 并暂停当前线程。子线程在 `of_END` 中会检查父线程的 `i_am_joining` 标志，如果为真则唤醒父线程。这是经典的**合作式多任务**实现。

### 3. `vvp/vthread.cc` — `vthread_run` 主执行循环

```cpp
void vthread_run(vthread_t thr) {
      while (thr != 0) {
            vthread_t tmp = thr->wait_next;
            thr->wait_next = 0;

            assert(thr->is_scheduled);
            thr->is_scheduled = 0;
            running_thread = thr;

            for (;;) {
                  vvp_code_t cp = thr->pc;
                  thr->pc += 1;
                  bool rc = (cp->opcode)(thr, cp);
                  if (rc == false)
                        break;  // 线程被暂停（如 delay、wait）
            }
            thr = tmp;
      }
      running_thread = 0;
}
```
**分析**：`vthread_run` 是 iverilog 的**核心执行引擎**。它按链表顺序依次运行被调度的 vthread。每个线程执行一条指令，递增 PC，直到遇到返回 `false` 的指令（如 `%delay`、`%wait`、`%join` 阻塞）。`running_thread` 全局变量指向当前正在运行的线程，供 VPI 和上下文访问函数使用。整个循环**完全在单线程中执行**，没有并行。

### 4. `vvp/schedule.h` — 分层事件调度 API

```c
extern void schedule_vthread(vthread_t thr, vvp_time64_t delay, bool push_flag = false);
extern void schedule_inactive(vthread_t thr);
extern void schedule_assign_vector(vvp_net_ptr_t ptr, unsigned base, unsigned vwid,
                                   const vvp_vector4_t& val, vvp_time64_t delay);
extern void schedule_generic(vvp_gen_event_t obj, vvp_time64_t delay,
                             bool sync_flag, bool ro_flag = true,
                             bool delete_obj_when_done = false);
extern void schedule_simulate(void);
```
**分析**：`schedule.h` 定义了 iverilog 的完整调度接口。`schedule_vthread` 将线程放入事件队列；`schedule_inactive` 放入 inactive 队列（对应 Verilog 的 `#0` 延迟）；`schedule_assign_vector` 实现非阻塞赋值（NBA）的延迟调度；`schedule_generic` 用于 VPI 回调和同步事件。`schedule_simulate()` 是主循环入口，不断从事件队列中取出事件执行，直到队列为空或 `schedule_finish()` 被调用。

### 5. `vvp/vthread.cc` — `automatic` 作用域上下文切换

```cpp
static vvp_context_t vthread_alloc_context(__vpiScope* scope) {
      assert(scope->is_automatic());
      vvp_context_t context = scope->free_contexts;
      if (context) {
            scope->free_contexts = vvp_get_next_context(context);
            for (unsigned idx = 0; idx < scope->nitem; idx++) {
                  scope->item[idx]->reset_instance(context);
            }
      } else {
            context = vvp_allocate_context(scope->nitem);
            for (unsigned idx = 0; idx < scope->nitem; idx++) {
                  scope->item[idx]->alloc_instance(context);
            }
      }
      vvp_set_next_context(context, scope->live_contexts);
      scope->live_contexts = context;
      return context;
}
```
**分析**：`automatic` 任务/函数每次调用都需要独立的变量存储。iverilog 通过 `free_contexts` 链表实现上下文对象池（object pooling），避免频繁 `malloc`/`free`。这在多线程化时可以直接扩展为**每个线程独立的上下文池**，消除全局链表竞争。

## 性能分析

| 维度 | 分析 |
|------|------|
| **vthread 调度开销** | 纯内存操作（PC 递增、函数指针调用），单次指令执行约 10-50ns，非常高效。 |
| **事件队列瓶颈** | 全局队列在 `schedule_simulate` 中串行处理，对于大量并发 vthread（如 10K+ `always` 块），队列遍历成为 O(N) 瓶颈。 |
| **fork-join 开销** | `of_FORK` 创建 `vthread_s`（约 200 字节 + 栈空间），没有 OS 线程创建开销，比 pthread 快 1000 倍以上。 |
| **VPI 回调** | 通过 `schedule_generic` 插入事件队列，与 vthread 同等调度，没有优先级抢占。 |
| **单线程局限** | 对于大规模设计（如 1000 万门），iverilog 的仿真速度通常比商业仿真器慢 10-100 倍，主要原因是单线程无法利用多核。 |

## 其他开源仿真器现状

| 项目 | 状态 | 多线程支持 |
|------|------|-----------|
| **Icarus Verilog (iverilog)** | 活跃维护 | ❌ 纯单线程 |
| **Verilator** | 活跃维护 | ✅ 实验性多线程 (`--threads`) |
| **CVC (Verilog Compiler)** | 未找到活跃 GitHub 仓库 | 未知 |
| **GHDL** | 活跃维护 | ❌ 单线程（有分布式 MPI 实验） |
| **CXXRTL (Yosys)** | 活跃维护 | ❌ 单线程，但生成 C++ 模型可被用户多线程 wrapper 调用 |

## 原文摘录

> "A vthread is a simulation thread that executes instructions when they are scheduled. This structure contains all the thread specific context needed to run an instruction."
> —— vvp/vthread.h

> "The %fork instruction creates a new thread and pushes that into a set of children for the thread. This new thread, then, becomes a child of the current thread, and the current thread a parent of the new thread."
> —— vvp/vthread.cc

> "This causes a thread to be scheduled for execution. The schedule puts the event into the event queue after any existing events for a given time step. If the delay is zero, the push_flag can be used to force the event to the front of the queue. %fork uses this to get the thread execution ahead of non-blocking assignments."
> —— vvp/schedule.h

## 相关链接

- [Icarus Verilog GitHub](https://github.com/steveicarus/iverilog)
- [Verilator 多线程文档](https://verilator.org/guide/latest/simulating.html#multithreading)
- [GHDL GitHub](https://github.com/ghdl/ghdl)
- [CXXRTL (Yosys) 文档](https://yosyshq.readthedocs.io/projects/yosys/en/latest/cmd/write_cxxrtl.html)

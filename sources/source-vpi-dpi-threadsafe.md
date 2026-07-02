---
title: VPI/DPI/PLI 在多线程仿真器中的线程安全实现
description: 搜集 VPI、DPI、PLI 接口在多线程仿真器中的线程安全机制、回调同步、DPI context 切换及 POSIX 线程互锁方案
source_url: ""
source_type: "doc"  # github-pr, github-issue, blog, doc, paper, competition
author: ""
date: ""
tags: ["vpi", "dpi", "pli", "thread-safety", "multithreading", "simulation", "callback", "mutex"]
keywords: ["VPI thread safe", "DPI multithreaded", "PLI callback thread safety", "svSetScope", "DPI context", "pthread mutex"]
capture_date: "2026-07-25"
---

# VPI / DPI / PLI 在多线程仿真器中的线程安全实现

## 来源

- URL: https://sunaku.github.io/masters_thesis.html
- URL: https://systemverilog.dev/9.html
- URL: https://www.eda-twiki.org/cgi-bin/view.cgi/P1076/DpiProposal
- URL: https://verificationacademy.com/forums/t/can-systemverilog-spawn-a-parallel-dpi-c-thread-and-exchange-data-with-it-periodically/38787
- URL: https://github.com/cocotb/cocotb/discussions/4174
- 类型: doc / thesis / forum
- 作者: 多篇综合
- 日期: 2020-2024

## 摘要

本资料综合了 VPI（Verilog Procedural Interface）、DPI（Direct Programming Interface）和 PLI（Programming Language Interface）在多线程仿真器中的线程安全实现。核心内容包括：

1. VPI 回调与 POSIX 线程的分离调用栈方案，通过双互斥锁实现仿真器与外部线程的交替执行；
2. DPI `context` 与 `pure` 关键字对多线程安全性的影响；
3. `svSetScope` / `svGetScope` 的 DPI 上下文切换机制；
4. 多线程 DPI 调用中的典型问题（非 DPI 回调中调用 export 任务、并发访问共享状态）。

## 关键要点

- **VPI 调用栈共享问题**：VPI/DPI 被调用时，C 函数与仿真器共享同一条调用栈。多线程方案需将仿真器与外部代码置于不同线程或不同进程中。
- **POSIX 线程 + 双互斥锁交替执行**：经典方案通过 `specLock` 和 `simLock` 两个 `pthread_mutex_t` 实现「只能有一方在执行」的串行化语义。
- **DPI `context` 修饰符**：标记为 `context` 的 DPI 函数需要在调用前由仿真器设置正确的 scope 上下文，显著增加开销；若不加 `context` 但内部调用 `svSetScope` 等 scope 函数，属于未定义行为。
- **DPI `pure` 修饰符**：`pure` 表示函数无副作用，允许编译器重排调用顺序。若函数内部修改了全局状态或使用了多线程共享对象，**绝不可**标记为 `pure`。
- **`svSetScope` 的线程安全陷阱**：`svSetScope` 只允许在 `context` DPI 函数内部调用。从非 DPI 上下文的 C 函数（如独立线程）中调用 export 任务会触发 `*E,NONCONG` 或 `*E,NOCONTG` 错误。
- **DPI 的 reentrant 安全**：当多个 VHDL/SystemVerilog 进程同时调用同一个 C 函数时，必须遵循 reentrant 编码规范——避免使用静态变量、注意库调用的线程安全。

## 对 RTL 仿真器多线程化的启示

在多线程 RTL 仿真器中集成 VPI/DPI 时，面临以下核心挑战：

1. **回调调度冲突**：多线程仿真器的事件调度器与 VPI 回调（`cbStartOfSimulation`, `cbEndOfSimulation`, `cbValueChange`）可能在不同线程上触发，需要加锁保护回调注册表。
2. **DPI 调用串行化**：DPI 函数本身不是线程安全的。如果仿真器内部采用时间轮或分片并行，DPI 调用必须串行化到单线程执行，否则 scope 上下文会错乱。
3. **外部语言绑定（Python/Rust/C++）的并发调用**：当外部语言通过 VPI/DPI 回调驱动仿真时，必须保证外部线程与仿真线程的同步——不能简单地在后台线程中调用 `vpi_register_cb`。

## 原文摘录

### 1. VPI 与 POSIX 线程的分离调用栈

> "The call stacks of simulator and specification can be separated through POSIX threads and semaphores as follows: The specification runs within a POSIX thread while the simulator runs within the main process. Semaphores ensure that only the specification or the simulator is running at any given time."

> — Suraj N. Kurapati, *Specification-driven functional verification with Verilog PLI & VPI and SystemVerilog DPI*, Section 3.1

```c
#include <stddef.h>
#include <pthread.h>
#include <vpi_user.h>

void* spec_run(void* dummy) {
    /* 1. schedule a callback to relay_spec();
       2. invoke relay_sim();
       3. repeat */
    return NULL;
}

pthread_t specThread;
pthread_mutex_t specLock;
pthread_mutex_t simLock;

PLI_INT32 relay_init(p_cb_data dummy) {
    pthread_mutex_init(&specLock, NULL);
    pthread_mutex_lock(&specLock);    /* 先锁住 spec，让仿真器先跑 */
    pthread_mutex_init(&simLock, NULL);
    pthread_mutex_lock(&simLock);    /* 先锁住 sim，让 spec 线程释放 */
    /* 启动外部规格线程 */
    pthread_create(&specThread, NULL, spec_run, NULL);
    pthread_mutex_lock(&simLock);  /* 等待 spec 线程释放 simLock */
    return 0;
}

/* 将控制权交给外部规格线程 */
void relay_spec() {
    pthread_mutex_unlock(&specLock);  /* 释放 spec，让规格线程跑 */
    pthread_mutex_lock(&simLock);     /* 等待规格线程释放 sim */
}

/* 将控制权交还 Verilog 仿真器 */
void relay_sim() {
    pthread_mutex_unlock(&simLock);   /* 释放 sim，让仿真器跑 */
    pthread_mutex_lock(&specLock);    /* 等待仿真器释放 spec */
}

void startup() {
    s_cb_data call;
    call.reason    = cbStartOfSimulation;
    call.cb_rtn    = relay_init;
    call.obj       = NULL;
    call.time      = NULL;
    call.value     = NULL;
    call.user_data = NULL;
    vpi_free_object(vpi_register_cb(&call));
}

void (*vlog_startup_routines[])() = { startup, NULL };
```

**线程安全分析**：
- 这是一个**交替执行（alternating execution）**模型，而非真正的并行。
- `relay_init` 初始化时存在短暂的竞态窗口：如果 `pthread_create` 在 `relay_init` 返回前就开始执行 `spec_run`，且 `spec_run` 立即调用 `relay_sim`，那么 `relay_sim` 可能先于 `relay_init` 的 `pthread_mutex_lock(&simLock)` 执行完毕。不过在本代码中，`spec_run` 首先会注册一个回调到 `relay_spec`，而回调由仿真器主线程在 cbStartOfSimulation 之后调度，因此时序是安全的。
- 若要在多线程仿真器中复用此方案，需将 `relay_spec`/`relay_sim` 的锁操作扩展为**可重入锁（recursive mutex）**，或改用 condition variable，因为现代多线程仿真器可能同时有多个 VPI 回调排队。

### 2. DPI Context 与 `svSetScope` 的线程安全规则

> "An imported C procedure, that calls an exported VHDL procedure containing a wait, may be called by several VHDL processes at the same time, and therefore should be written to be multi-thread safe. Rules for re-entrant C coding include care with static variables and library calls."

> — IEEE P1076 / DPI Proposal, Section Implementation details - Part 2

```c
#include "svdpi.h"
#include "stdio.h"

extern void export_func(void);

void import_func() {
    printf("C: Called from scope %s\n",
           svGetNameFromScope(svGetScope()));
    export_func();  /* 隐式使用 svGetScope() 的上下文 */
}
```

**线程安全分析**：
- `svGetScope()` 返回当前线程的 DPI scope。在多线程仿真器中，如果两个线程同时调用 `import_func`，而 `import_func` 内部使用 `svGetScope()` 获取 scope，每个线程将获得**不同**的 scope 对象。这本身是安全的，因为 scope 是线程局部或调用帧相关的。
- 危险在于：如果 C 代码内部使用**全局静态变量**缓存了 `svGetScope()` 的结果，那么两个线程的并发写入会导致 scope 污染。解决方案是使用线程局部存储（`thread_local`）或函数参数传递 scope。

### 3. 从非 DPI 上下文调用 Export 任务的错误示例

```c
/* 错误：从普通 C 线程中调用 DPI export 任务 */
void interrupt_handler_thread() {
    /* 假设这是独立线程，不是从 DPI import 进入的 */
    svSetScope(svGetScopeFromName("tb_wrapper"));
    /* 错误：ncsim: *E,NOCONTG: DPI Scope function call allowed only from context function */
    sv_dpi_export_task();
}
```

**正确做法**：
```c
/* 正确：使用原子操作同步后，从 context DPI 函数内部调用 */
static volatile int interrupt_flag = 0;

/* 此函数被声明为 context import */
void dpi_interrupt_notify() {
    __sync_lock_test_and_set(&interrupt_flag, 1);
}

/* 在仿真器主线程的某个回调中检查 */
void check_interrupt() {
    if (__sync_lock_test_and_set(&interrupt_flag, 0)) {
        /* 现在安全地调用 export */
        svSetScope(svGetScopeFromName("tb_wrapper"));
        export_task();
    }
}
```

**线程安全分析**：
- `__sync_lock_test_and_set` 是 GCC 内置的原子操作，提供轻量级同步。在多线程仿真器中，中断线程与仿真主线程之间的通信需要**无锁队列或原子标志**，而不是互斥锁，因为仿真器主线程通常有严格的调度时序要求。
- `svSetScope` 的调用线程**必须是**从 DPI import 进入的线程（即 context 线程），否则仿真器无法确定正确的进程上下文（process context），会导致时间推进异常或段错误。

### 4. DPI 数据类型的线程安全映射

```c
/* SystemVerilog 端 */
import "DPI-C" context function void compare_values(
    bit[7:0]  mem_idx,
    bit[15:0] CAL_VAL,
    bit[31:0] ADDRESS
);

/* C 端 */
void compare_values(
    const svBitVecVal* mem_idx,   /* 8-bit */
    const svBitVecVal* CAL_VAL,   /* 16-bit */
    const svBitVecVal* ADDRESS    /* 32-bit */
) {
    /* 注意：svBitVecVal* 指向的是仿真器内部内存，
       多线程下读取是安全的，但写入需要加锁 */
}
```

**线程安全分析**：
- `svBitVecVal*` 和 `svLogicVecVal*` 是指向仿真器内部数据结构的**裸指针**。在多线程仿真器中，如果多个线程同时通过 DPI 写入同一个 `logic` 或 `reg`，必须保证写操作是原子的，或串行化到同一个线程。
- `svOpenArrayHandle` 允许零拷贝访问多维数组。多线程环境下，持有 `svOpenArrayHandle` 的 C 函数在返回后不应保留该句柄，因为仿真器可能在下一次时间推进时重新分配数组内存。

## 相关链接

- [Ruby-VPI: Specification-driven verification thesis](https://sunaku.github.io/masters_thesis.html)
- [SystemVerilog DPI Guide](https://systemverilog.dev/9.html)
- [IEEE P1076 DPI Proposal](https://www.eda-twiki.org/cgi-bin/view.cgi/P1076/DpiProposal)
- [QuestaSim DPI-C 调用指南](https://www.elektroda.com/qa,questasim-systemverilog-dpi-c-c-function.html)
- [Verilator DPI 文档](https://verilator.org/guide/latest/extensions.html#dpi)
- [cocotb DPI 讨论: 从 Python 调用 C 再调用 export DPI](https://github.com/cocotb/cocotb/discussions/4174)

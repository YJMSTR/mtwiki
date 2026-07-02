---
title: 多语言外部接口（FFI）的线程安全实现：Python / Rust / C
description: 搜集 Python C API / PyBind11、Rust FFI、C 外部函数接口在多线程环境下的安全实践，包括 GIL、Send/Sync 标记、无锁同步等机制
tags: ["ffi", "python", "pybind11", "rust", "gil", "thread-safety", "free-threading", "multithreading"]
keywords: ["Python C API thread safety", "PyBind11 multithreaded", "Rust FFI thread safety", "C foreign function interface", "language binding simulation"]
source_type: "doc"
source_url: ""
author: ""
date: ""
capture_date: "2026-07-25"
---

# 多语言外部接口（FFI）的线程安全实现：Python / Rust / C

## 来源

- URL: https://pybind11.readthedocs.io/en/stable/advanced/misc.html
- URL: https://github.com/pybind/pybind11/issues/2765
- URL: https://github.com/pybind/pybind11/issues/5245
- URL: https://github.com/pybind/pybind11/issues/5316
- URL: https://labs.quansight.org/blog/free-threaded-python-halfway
- URL: https://doc.rust-lang.org/nomicon/ffi.html
- URL: https://cxx.rs/extern-c++.html
- URL: https://stackoverflow.com/questions/42006337/python-c-api-is-it-thread-safe
- URL: https://blog.serghei.pl/posts/a-quick-dive-into-ffi-in-python/
- 类型: doc / github-issue / blog
- 作者: 多篇综合
- 日期: 2017-2024

## 摘要

本资料综合了 Python、Rust、C 三语言在 FFI（Foreign Function Interface）场景下的线程安全实践。核心内容包括：

1. **Python C API / PyBind11 的 GIL 机制**：`Py_BEGIN_ALLOW_THREADS` / `Py_END_ALLOW_THREADS` 的释放与重获取、PyBind11 的 `gil_scoped_release` / `gil_scoped_acquire`、Python 3.13+ free-threading（无 GIL）对扩展的影响；
2. **Rust FFI 的 Send/Sync 契约**：如何通过 `PhantomData` 标记 C 类型为非线程安全，何时需要手动 `unsafe impl Send`/`Sync`；
3. **CXX 库的线程安全声明**：`#[cxx::bridge]` 下 extern C++ 类型默认不实现 `Send`/`Sync`；
4. **C 语言 FFI 的通用线程安全原则**：函数指针穿越边界、无状态回调、内存分配所有权。

## 关键要点

- **Python GIL 不是万能锁**：GIL 保证的是 Python 对象访问的串行化，而不是 C 扩展内部全局变量的线程安全。在 `Py_BEGIN_ALLOW_THREADS` 块内修改 C 全局变量仍需显式锁。
- **PyBind11 的 `loader_life_support` 非线程安全**：`pybind11::cast` 内部使用全局 `loader_patient_stack` 向量。如果 cast 过程中释放了 GIL（例如触发了 `__del__`），两个线程的 push/pop 操作可能交错，导致段错误（#2765）。
- **Python 3.13+ free-threading 彻底改变假设**：无 GIL 构建中，C 扩展不能再依赖 GIL 隐式保护全局缓存。必须使用原子初始化、互斥锁或 Python 3.14 的 `PyMutex`。
- **Rust FFI 中默认不实现 Send/Sync**：通过 `#[repr(C)]` 暴露的 opaque 类型自动是 `!Send` 且 `!Sync`。如果 C 库底层是线程安全的，必须手动 `unsafe impl Send` / `unsafe impl Sync`，并承担证明责任。
- **CXX 的 `Pin<&mut T>` 要求**：跨越 FFI 边界时，C++ 类型的可变引用必须使用 `Pin<&mut T>`，防止 Rust 执行 `mem::swap` 破坏 C++ 的内存不变式。
- **「谁分配，谁释放」原则**：FFI 边界上，内存分配器可能不同（Rust jemalloc vs C malloc）。Rust 用 `CString` /`CStr` 管理字符串，C 返回的指针必须用 C 的 `free` 释放。

## 对 RTL 仿真器多线程化的启示

多线程 RTL 仿真器越来越多地采用 Python 或 Rust 作为外部验证语言（如 cocotb 使用 Python，newer 工具用 Rust 写 testbench）。FFI 的线程安全直接影响仿真器性能与稳定性：

1. **Python testbench 驱动多线程仿真**：cocotb 等框架通过 VPI 与仿真器交互。如果 Python 侧的 VPI 回调在多个线程上触发，必须保证 GIL 的正确获取/释放，否则死锁或崩溃。
2. **Rust 写的 UVM-like 验证组件**：Rust 的 ownership 模型天然适合验证组件的内存管理。通过 FFI 调用 C 编写的 VPI 库时，需正确标记 `Send`/`Sync`，否则 Rust 编译器会阻止跨线程共享 VPI 句柄。
3. **free-threading Python 的机遇**：Python 3.13+ 无 GIL 意味着 Python 侧可以实现真正的多核并行 testbench。但仿真器 C 扩展必须同步改造，否则会成为瓶颈或崩溃源。

## 原文摘录

### 1. Python C API 的 GIL 释放与线程安全

> "Python will not release the GIL when you are running C code (unless you either tell it to or cause the execution of Python code). It only releases the GIL just before a bytecode instruction. Therefore, unless you do anything specific your C code will be the only thread running and thus any operation you do in it should be thread safe."

> — Stack Overflow: *Python C API - Is it thread safe?*

```c
/* 在长时间计算中释放 GIL，允许其他 Python 线程运行 */
static PyObject* my_long_computation(PyObject* self, PyObject* args) {
    long result;
    
    Py_BEGIN_ALLOW_THREADS
    /* GIL 已释放：不能调用任何 Python API */
    result = heavy_cpu_bound_work();  /* 纯 C 代码 */
    Py_END_ALLOW_THREADS
    
    /* GIL 已重新获取：可以安全返回 Python 对象 */
    return PyLong_FromLong(result);
}
```

**线程安全分析**：
- `Py_BEGIN_ALLOW_THREADS` 宏展开为 `PyThreadState *_save = PyEval_SaveThread()`，保存当前线程状态并释放 GIL。此操作是原子的。
- 在 `Py_BEGIN_ALLOW_THREADS` 和 `Py_END_ALLOW_THREADS` 之间，**绝对禁止**调用任何 Python C API（包括 `Py_DECREF`）。如果 `heavy_cpu_bound_work()` 内部调用了某个回调，而该回调可能执行 Python 代码，必须先 `Py_END_ALLOW_THREADS` 再调用回调。
- 多线程仿真器中的 VPI 回调（从 C 调用 Python）必须遵循此规则：在调用 Python 函数前获取 GIL，返回后立即释放。

### 2. PyBind11 的 GIL 管理与 free-threading 适配

```cpp
#include <pybind11/pybind11.h>
#include <atomic>

namespace py = pybind11;

/* === Python 3.12 及以前：带 GIL 版本 === */
PYBIND11_MODULE(old_example, m) {
    static size_t seed = 0;  /* 非线程安全！ */
    m.def("calc_next", []() {
        auto old = seed;
        seed = (seed + 1) * 10;
        return old;
    });
}

/* === Python 3.13+ free-threading：无 GIL 版本 === */
PYBIND11_MODULE(free_example, m, py::mod_gil_not_used()) {
    static std::atomic<size_t> seed(0);  /* 必须原子化 */
    m.def("calc_next", []() {
        size_t old, next;
        do {
            old = seed.load();
            next = (old + 1) * 10;
        } while (!seed.compare_exchange_weak(old, next));
        return old;
    });
}
```

**线程安全分析**：
- `py::mod_gil_not_used()` 是一个**承诺**：你告诉 Python 运行时，此模块不需要 GIL 也能正确运行。如果模块内部仍有非线程安全的全局状态（如未加锁的 `std::vector`），多线程并发调用将导致数据竞争。
- `compare_exchange_weak` 是无锁算法的标准模式。在 x86-64 上，`std::atomic<size_t>` 的 CAS 通常映射到 `lock cmpxchg`，开销很小。但在 ARM 上可能需要 LL/SC 重试循环。
- PyBind11 的 `internals` 全局单例在 free-threading 下存在**双初始化竞态**（#5316）。当两个线程同时导入不同模块时，可能各自创建一份 `internals`。PyBind11 团队正在使用 `std::once_flag` 或 `std::mutex` 修复此问题。

### 3. PyBind11 的 `loader_life_support` 线程安全漏洞

```cpp
// pybind11 内部代码（问题 #2765）
std::vector<PyObject*> loader_patient_stack; // 全局！非线程安全！

// 如果 cast 过程中释放了 GIL，两个线程的 push/pop 可能交错：
// Thread A: push(objA)
// Thread B: push(objB)  ← 可能发生在 A 的 push 和 pop 之间
// Thread A: pop()       ← 现在弹出的可能是 objB！
```

**影响与缓解**：
- 此漏洞在 PyBind11 2.6+ 中已部分修复，但根本问题（全局向量 + GIL 可能释放）的完全修复需要重构为线程局部存储。
- 在**多线程仿真器**中，如果多个 worker 线程同时通过 PyBind11 将 C 结果转换回 Python 对象（如 `py::array` 或 `py::dict`），必须在外部加锁串行化这些转换，或使用 PyBind11 的 debug 构建启用额外断言。

### 4. Python 3.13 free-threading 下原生扩展的改造

```c
/* Python 3.14 提供的 PyMutex（比 pthread_mutex 更轻量） */
#include <Python.h>
#include <stdatomic.h>

static _Atomic int cache_initialized = 0;
static PyMutex cache_mutex = {0};
static PyObject* global_cache = NULL;

PyObject* get_cached_value(void) {
    /* 快速路径：已初始化 */
    if (atomic_load(&cache_initialized)) {
        return global_cache;
    }
    
    /* 慢速路径：需要初始化 */
    PyMutex_Lock(&cache_mutex);
    if (!atomic_load(&cache_initialized)) {  /* 双重检查锁定 */
        global_cache = PyDict_New();
        /* ... 填充缓存 ... */
        atomic_store(&cache_initialized, 1);
    }
    PyMutex_Unlock(&cache_mutex);
    return global_cache;
}
```

**线程安全分析**：
- 双重检查锁定（Double-Checked Locking）在 C11 `_Atomic` 下是安全的，因为 `atomic_store` 和 `atomic_load` 提供了必要的 happens-before 关系。
- `PyMutex` 是 Python 3.14 引入的轻量级锁，针对无 GIL 场景优化。在仍使用 GIL 的 Python 3.13 上，`PyMutex` 退化为简单的忙等或 futex，不会显著拖慢性能。
- 在**多线程 RTL 仿真器**中，如果多个仿真线程同时调用 Python 扩展的缓存函数（如共享的覆盖率数据库），必须采用此模式或更高级的无锁数据结构（如 `ConcurrentHashMap`）。

### 5. Rust FFI 的 Send/Sync 标记与线程安全封装

```rust
use std::ffi::{c_int, c_void};
use std::marker::PhantomData;
use std::sync::Mutex;

/* C 库提供的 opaque handle */
#[repr(C)]
pub struct CHandle {
    _data: [u8; 0],
    _marker: PhantomData<(*mut u8, PhantomPinned)>,
    /* PhantomData<(*mut u8, PhantomPinned)> 确保 CHandle 默认 !Send + !Sync */
}

extern "C" {
    fn c_create_handle() -> *mut CHandle;
    fn c_destroy_handle(handle: *mut CHandle);
    fn c_process(handle: *mut CHandle, value: c_int) -> c_int;
}

/* 安全封装：如果 C 库文档声明线程安全，手动标记 */
unsafe impl Send for CHandle {}
unsafe impl Sync for CHandle {}

pub struct SafeHandle {
    raw: *mut CHandle,
    /* 即使 CHandle 是 Sync 的，我们再加一层 Mutex 以提供 &self API */
    lock: Mutex<()>,
}

impl SafeHandle {
    pub fn new() -> Option<Self> {
        let raw = unsafe { c_create_handle() };
        if raw.is_null() {
            None
        } else {
            Some(SafeHandle {
                raw,
                lock: Mutex::new(()),
            })
        }
    }

    pub fn process(&self, value: i32) -> i32 {
        let _guard = self.lock.lock().unwrap();
        unsafe { c_process(self.raw, value as c_int) }
    }
}

impl Drop for SafeHandle {
    fn drop(&mut self) {
        unsafe { c_destroy_handle(self.raw); }
    }
}
```

**线程安全分析**：
- `PhantomData<(*mut u8, PhantomPinned)>` 是一种**编译期技巧**：`*mut u8` 是 `!Send` 且 `!Sync` 的，`PhantomPinned` 是 `!Unpin` 的。这样 `CHandle` 默认不能跨线程传递，也不能被多线程共享引用。
- `unsafe impl Send for CHandle {}` 是一个**安全承诺**。开发者必须确保 C 库的 `c_create_handle` 返回的指针可以安全地在不同线程间传递（即 C 库内部不依赖线程局部存储）。
- `unsafe impl Sync for CHandle {}` 承诺 `c_process` 可以在多个线程同时以 `&CHandle` 调用时安全执行。如果 C 库内部使用全局状态，这个 `unsafe impl` 是**错误**的，应该用 `Mutex<CHandle>` 或 `RwLock<CHandle>` 包装。
- 在**多线程 RTL 仿真器**中，如果 Rust 验证组件需要将 VPI handle（`vpiHandle`）传递给多个线程，同样的模式适用：默认 `!Send`/`!Sync`，仅在确认仿真器 VPI 实现线程安全后手动标记。

### 6. CXX 库的 Pin<&mut T> 与线程安全

```rust
// CXX bridge 定义
#[cxx::bridge]
mod ffi {
    extern "C++" {
        include!("simulator/vpi_host.h");
        type VpiContext;
        
        fn create_context() -> UniquePtr<VpiContext>;
        fn process_event(ctx: Pin<&mut VpiContext>, event_id: u32);
    }
}

// 使用
let mut ctx = ffi::create_context();
ffi::process_event(ctx.pin_mut(), 42);
```

**线程安全分析**：
- CXX 桥接器不会为 extern C++ 类型自动生成 `Send` 或 `Sync`。上述 `VpiContext` 默认是 `!Send` 且 `!Sync` 的。
- 如果 `VpiContext` 内部使用了 `std::mutex` 或原子操作，且设计为线程安全，需要在 bridge 模块外显式声明：
  ```rust
  unsafe impl Send for ffi::VpiContext {}
  unsafe impl Sync for ffi::VpiContext {}
  ```
- `Pin<&mut VpiContext>` 阻止 Rust 代码对 C++ 对象执行 `mem::swap` 或 `std::mem::replace`。这在 C++ 类型具有非平凡移动构造函数或内部自引用指针时至关重要。

### 7. C FFI 的回调函数与线程安全

```c
/* C 库 API：注册回调 */
typedef void (*event_callback_t)(int event_id, void* user_data);
void register_callback(event_callback_t cb, void* user_data);

/* === 线程安全版本：无状态回调 + 上下文指针 === */
struct callback_context {
    pthread_mutex_t mutex;
    int counter;
};

static void threadsafe_callback(int event_id, void* user_data) {
    struct callback_context* ctx = (struct callback_context*)user_data;
    pthread_mutex_lock(&ctx->mutex);
    ctx->counter++;
    printf("Event %d, counter=%d\n", event_id, ctx->counter);
    pthread_mutex_unlock(&ctx->mutex);
}

/* 错误做法：使用全局静态变量 */
static int global_counter = 0;  /* 多线程下竞态！ */
static void unsafe_callback(int event_id, void* user_data) {
    (void)user_data;
    global_counter++;  /* 数据竞争！ */
}
```

**线程安全分析**：
- 好的 C API 设计遵循「函数指针 + `void*` 上下文」模式。上下文指针让调用者传递任意数据给回调，避免全局变量。
- 在多线程 RTL 仿真器中，如果仿真器的事件引擎在不同线程上触发回调（如时间轮并行），每个线程必须拥有独立的 `callback_context`，或所有线程共享同一个带有 `mutex` 的 `callback_context`。
- 使用 `user_data` 指针而非全局变量，还可以实现**线程局部回调**：每个 worker 线程创建自己的 `callback_context`，只处理该线程负责的事件。

## 相关链接

- [PyBind11 官方文档：Miscellaneous - GIL 与 Free-threading](https://pybind11.readthedocs.io/en/stable/advanced/misc.html)
- [PyBind11 Issue #2765: pybind11::cast is not thread safe](https://github.com/pybind/pybind11/issues/2765)
- [PyBind11 Issue #5316: internals initialization free-threading race](https://github.com/pybind/pybind11/issues/5316)
- [Quansight Labs: Free-threaded Python 现状](https://labs.quansight.org/blog/free-threaded-python-halfway)
- [Stack Overflow: Python C API thread safety](https://stackoverflow.com/questions/42006337/python-c-api-is-it-thread-safe)
- [Rust FFI: The Rustonomicon](https://doc.rust-lang.org/nomicon/ffi.html)
- [CXX: Safe interop between Rust and C++](https://cxx.rs/extern-c++.html)
- [Rust FFI 线程安全封装讨论](https://users.rust-lang.org/t/thread-safely-wrapping-c-ffi-library-with-effective-interior-mutability/58714)
- [Python FFI 演进史：从 ctypes 到 Rust 与后 GIL 时代](https://blog.serghei.pl/posts/a-quick-dive-into-ffi-in-python/)

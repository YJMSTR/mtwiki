---
title: 结构化与二进制日志格式：从 JSON 到 Protobuf/FlatBuffers 的高性能序列化
description: 搜集结构化日志、二进制日志格式、Protobuf/FlatBuffers 序列化及 Chrome Trace Event 格式在仿真领域的应用，为 RTL 仿真器设计高效可解析的日志/追踪格式
source_url: "https://github.com/chronoxor/CppSerialization"
source_type: "github-repo"
author: "Ivan Shynkarenka (chronoxor)"
date: "2024-01-01"
tags: ["structured-logging", "binary-format", "protobuf", "flatbuffers", "serialization", "trace-event", "performance"]
keywords: ["structured logging simulation", "binary log format", "protobuf logging", "flatbuffers logging", "chrome trace event format RTL"]
capture_date: "2025-01-15"
---

# 结构化与二进制日志格式：从 JSON 到 Protobuf/FlatBuffers 的高性能序列化

## 来源

- URL: <https://github.com/chronoxor/CppSerialization>
- 类型: github-repo / 性能对比基准
- 作者: Ivan Shynkarenka (chronoxor)
- 日期: 2024 持续更新

## 摘要

结构化日志（Structured Logging）将日志从自由文本转变为带有固定字段的机器可读格式（如 JSON），而二进制序列化（Protobuf、FlatBuffers、SBE、Cap'n Proto）进一步消除了文本解析开销。对于 RTL 仿真器而言，每周期可能产生数万条信号变化、事件调度或模块求值日志，文本格式的解析和存储开销极为昂贵。二进制格式可将日志体积压缩至 JSON 的 1/3~1/5，序列化/反序列化速度提升 5~10 倍。Chrome Trace Event Format 则提供了一个轻量级的、可可视化的结构化追踪标准，已被广泛用于性能剖析和事件追踪。本资料综合了 CppSerialization 的基准测试数据、Google 官方文档及社区实践，为 RTL 仿真器的日志格式选型提供量化依据。

## 关键要点

1. **Protobuf 的 schema-first 设计**：通过 `.proto` 文件定义强类型日志 schema，编译生成 C++ 代码，确保字段名和类型在编译期固化，避免运行时字符串解析，日志体积比 JSON 小约 3 倍。
2. **FlatBuffers 的 zero-copy 读取**：FlatBuffers 将数据直接序列化为内存对齐的二进制块，反序列化时无需解析（parsing），直接通过偏移量访问字段，特别适合「写一次、读多次」的仿真追踪场景（如后处理波形分析）。
3. **SBE (Simple Binary Encoding) 的极致性能**：在 CppSerialization 基准测试中，SBE 的序列化速度达到 35 ns/op，远超 Protobuf 的 322 ns/op 和 FlatBuffers 的 272 ns/op，但 schema 复杂度更高，维护成本大。
4. **Chrome Trace Event Format**：Google 推出的 JSON 格式事件追踪标准，支持 `B`（begin）、`E`（end）、`X`（complete）等事件类型，可被 Chrome 浏览器 `chrome://tracing` 直接加载，是仿真事件时间线可视化的理想中间格式。
5. **结构化日志的核心字段**：timestamp（ns 级精度）、level、thread_id、event_type、module_path、signal_delta 等字段的标准化，使后处理工具（如波形对比、回归分析）能够直接按字段过滤聚合。

## 对 RTL 仿真器多线程化的启示

- **仿真事件追踪 = 结构化日志**：将每个 `eval()`、`update()`、`schedule()` 调用视为一个结构化日志事件，记录 cycle、domain、thread_id、latency_us，可用 Chrome Trace Event 格式导出，直接在浏览器中可视化多线程调度瓶颈。
- **二进制波形转储替代 VCD**：FSDB 已证明了二进制波形格式比 VCD 文本格式小 5~50 倍的优越性。对于 RTL 仿真器自研的日志系统，采用 Protobuf/FlatBuffers 定义 `SignalChange` / `EventRecord` 消息类型，可在保持通用解析能力的同时，大幅压缩磁盘 I/O。
- **跨线程日志合并**：每个仿真线程将本线程的事件日志序列化为独立的 FlatBuffers 内存块，在 cycle 边界通过 zero-copy 拼接（FlatBuffers 支持 `CreateVectorOfTables` 合并），无需反序列化即可生成全局追踪文件。
- **后处理 pipeline 的 schema 演化**：使用 Protobuf 的 field number 向后兼容机制，可在不破坏旧版追踪解析工具的前提下，新增字段（如 `power_estimate`、`coverage_hit`）。

## 代码示例

### Protobuf 日志 Schema 定义（仿真事件）

```protobuf
// rtl_event.proto
syntax = "proto3";
package rtlsim;

message SignalChange {
    uint64 timestamp_ps = 1;      // 皮秒级时间戳
    string signal_path = 2;       // 信号层次路径
    bytes value = 3;              // 4-state 值：0/1/X/Z
    uint32 width = 4;             // 位宽
}

message SimEvent {
    uint64 cycle = 1;
    uint32 thread_id = 2;
    string event_type = 3;      // "EVAL", "SCHEDULE", "UPDATE", "COMMIT"
    string module_path = 4;
    uint64 latency_ns = 5;
    repeated SignalChange deltas = 6;
}

message SimTrace {
    repeated SimEvent events = 1;
    uint64 total_cycles = 2;
    uint32 num_threads = 3;
}
```

### FlatBuffers 零拷贝日志访问（C++）

```cpp
// 生成的 FlatBuffers C++ 代码使用示例
#include "rtlsim_event_generated.h"

void process_trace(const uint8_t* buf, size_t len) {
    // 零拷贝：直接映射内存，无需解析
    auto trace = rtlsim::GetSimTrace(buf);
    
    for (auto event : *trace->events()) {
        uint64_t cycle = event->cycle();
        uint32_t tid = event->thread_id();
        auto ev_type = event->event_type();
        
        // 直接访问 SignalChange 数组，无堆分配
        for (auto delta : *event->deltas()) {
            auto path = delta->signal_path();
            auto val = delta->value();
            // 处理信号变化...
        }
    }
}
```

### Chrome Trace Event Format 导出（JSON）

```cpp
#include <fstream>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

void emit_trace_event(std::ofstream& out, 
                      const std::string& name, 
                      uint64_t ts_us, 
                      uint64_t dur_us, 
                      uint32_t tid) {
    json event;
    event["name"] = name;
    event["ph"] = "X";              // Complete event
    event["ts"] = ts_us;
    event["dur"] = dur_us;
    event["tid"] = tid;
    event["pid"] = 1;               // RTL 仿真进程
    event["args"] = json::object();
    out << event.dump() << ",\n";
}

// 使用示例：在仿真器的事件调度器中插桩
emit_trace_event(trace_file, "eval_comb_cycle_42", 
                 123456,  // 开始时间 (us)
                 15,      // 持续时间 (us)
                 thread_id);
```

生成的 `.json` 文件可直接在 `chrome://tracing` 中加载，查看多线程仿真的事件时间线。

### 序列化性能基准测试（CppSerialization）

```cpp
// 基准测试对象：含 1 account + 1 wallet + 3 orders，共 128 bytes 领域数据
// 运行环境：x86_64 Linux, GCC 12

// Protocol         | 消息大小 | 序列化时间 | 反序列化时间
// -----------------|----------|------------|--------------
// Cap'n'Proto      | 208 B    | 247 ns     | 184 ns
// FastBinaryEncoding| 234 B    | 77 ns      | 84 ns
// FlatBuffers      | 280 B    | 272 ns     | 81 ns
// Protobuf         | 120 B    | 322 ns     | 351 ns
// SimpleBinaryEncoding| 138 B | 35 ns      | 52 ns
// zpp::bits        | 130 B    | 34 ns      | 37 ns
// JSON             | 301 B    | 696 ns     | 291 ns
```

## 性能数据

### 多格式序列化延迟对比（ns/op）

| 协议 | 格式 | 序列化延迟 | 反序列化延迟 | 消息大小 | 最佳场景 |
|------|------|-----------|-------------|----------|---------|
| FlatBuffers | 二进制 | 272 ns | **81 ns** | 280 B | 读-heavy，零拷贝 |
| Protocol Buffers | 二进制 | 322 ns | 351 ns | 120 B | 跨服务通信，schema 稳定 |
| JSON | 文本 | 696 ns | 291 ns | 301 B | 人可读，调试接口 |
| SBE | 二进制 | **35 ns** | **52 ns** | 138 B | 极致性能（金融交易） |
| zpp::bits | 二进制 | **34 ns** | **37 ns** | 130 B | C++ 现代编译期反射 |

> 来源：CppSerialization GitHub 仓库基准测试。测试对象大小约 128 bytes。

### 文本 vs 二进制格式延迟对比（另一组独立测试）

| 协议 | 执行时间 (ns/op) | 内存分配 | 适用场景 |
|------|-----------------|----------|---------|
| FlatBuffers | 711.2 | 最低 | 读-heavy AI 工作负载 |
| Protocol Buffers | 1,827 | 1,856 bytes/op | 微服务间通信 |
| JSON | 7,045 | 2,288 bytes/op | Web API、调试 |

> 来源：Latitude.so 博客 "Serialization Protocols for Low-Latency AI Applications"。

### 二进制格式 shootout（IEX 市场数据，10 轮平均）

| Schema | 序列化中位数 | 序列化 P99 | 反序列化中位数 | 反序列化 P99 |
|--------|------------|-----------|--------------|-------------|
| SBE | 91 ns | 1,535 ns | 116 ns | 286 ns |
| Cap'n'Proto Unpacked | 273 ns | 1,828 ns | 366 ns | 737 ns |
| FlatBuffers | 355 ns | 2,185 ns | 173 ns | 421 ns |
| Cap'n'Proto Packed | 413 ns | 1,751 ns | 539 ns | 1,216 ns |

> 来源：speice.io "Binary format shootout"。

## 原文摘录

> "Protocol buffers are Google's language-neutral, platform-neutral, extensible mechanism for serializing structured data — think XML, but smaller, faster, and more straightforward."
> —— Google Protocol Buffers 官方文档

> "FlatBuffers maintains a zero-copy approach, accessing data directly from the serialized buffer. Protobuf requires deserialization into native objects, consuming additional memory and processing time."
> —— Kite Metric, "JSON vs. Protocol Buffers vs. FlatBuffers"

> "Pino is great, thanks for keeping it fast and simple. I've been playing with the idea of adding a binary log format (protobuf or flatbuffers style) as an optional mode. Main motivation is, at very high throughput, JSON serialization and deserialization is still expensive, and binary logs are smaller and cheaper to write and parse."
> —— pinojs GitHub issue #2296

> "The main outputs of this trace-based framework are on the one hand performance statistics, such as the execution time of the application, utilization status of both processors and buses, and maximum buffer fill levels for the different channels. On the other hand, we can visualize simulation traces by using the SystemC build-in library, i.e. Value Change Dump (VCD)."
> —— ETH Zürich, SIES'09 paper

## 相关链接

- [CppSerialization 性能对比仓库](https://github.com/chronoxor/CppSerialization)
- [Protocol Buffers 官方文档](https://protobuf.dev/)
- [FlatBuffers 官方文档](https://flatbuffers.dev/)
- [Chrome Trace Event Format 规范](https://docs.google.com/document/d/1CvAClvFfyA5R-PhYUmn5OOQtYMH4h6I0nSsKchNAySU/preview)
- [Latitude.so - Serialization Protocols for Low-Latency AI](https://latitude.so/blog/serialization-protocols-for-low-latency-ai-applications)
- [Kite Metric - JSON vs Protobuf vs FlatBuffers](https://kitemetric.com/blogs/json-vs-protocol-buffers-vs-flatbuffers-data-serialization-showdown)
- [pinojs binary log proposal](https://github.com/pinojs/pino/issues/2296)
- [Google Vulkan Performance Layers - Trace Event 实现](https://github.com/google/vulkan-performance-layers/issues/130)

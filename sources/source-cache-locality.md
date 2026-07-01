---
title: "Cache Locality 优化：从 AoS/SoA 到预取与数据导向设计"
source_url: "https://en.algorithmica.org/hpc/cpu-cache/prefetching/"
source_type: "blog"
author: "Algorithmica"
date: ""
tags: ["hpc", "multithreading", "cpp", "cache-locality", "prefetching", "data-oriented-design"]
keywords: ["cache-locality", "AoS", "SoA", "prefetching", "data-oriented-design", "DOD", "loop-tiling", "hot-cold-split"]
capture_date: "2026-07-01"
---

## 来源

- **原文**: [Algorithmica — Prefetching](https://en.algorithmica.org/hpc/cpu-cache/prefetching/)
- **补充**: [Mike Acton — Data-Oriented Design (C++ Con)](https://www.youtube.com/watch?v=rX0ItVEVjHc)
- **补充**: [Handmade Hero — SoA vs AoS](https://handmadehero.org/)
- **补充**: [Intel — Cache Blocking Techniques](https://www.intel.com/content/www/us/en/developer/articles/technical/cache-blocking-techniques.html)
- **补充**: [Wikipedia — Loop tiling](https://en.wikipedia.org/wiki/Loop_tiling)

## 摘要

Cache locality 决定了现代 CPU 能发挥多少理论性能。内存延迟约 100ns，而 CPU 每个周期约 0.3ns（3GHz），意味着 CPU 在等待一次内存访问时可以执行约 300 条指令。Cache locality 优化的核心目标就是**减少 cache miss**，让数据在 CPU 需要时已经在 L1/L2 cache 中。

数据布局有两种基本模式：
- **AoS（Array of Structs）**：每个元素是一个结构体，包含多个属性。访问模式是"逐个元素处理所有属性"时最优，但 cache line 利用率低（如果只需要一个属性，其他属性被浪费加载）。
- **SoA（Structure of Arrays）**：每个属性单独一个数组。访问模式是"处理所有元素的某个属性"时最优，SIMD 友好，cache line 利用率最高。

**Prefetching（预取）**是在 CPU 真正需要数据之前，提前将其加载到 cache。硬件预取器能识别线性访问和固定步幅模式，但无法处理不规则访问（如指针追逐、哈希表遍历）。软件预取使用 `__builtin_prefetch` 或 `_mm_prefetch`，需要精确控制预取距离（通常 8-16 个 cache line 提前）。

Data-Oriented Design（DOD）的核心原则：不是按"对象"组织数据，而是按"访问模式"组织数据。将**热数据（hot）**和**冷数据（cold）**分离，让热数据紧凑排列，每条 cache line 包含更多有效数据。

## 关键要点

1. **AoS vs SoA 的对比**:
   ```cpp
   // AoS: 适合"逐个元素处理所有属性"
   struct Particle {
       float x, y, z;      // 12 bytes
       float vx, vy, vz;   // 12 bytes
       int id;             // 4 bytes
       char name[32];      // 32 bytes — 很少访问的冷数据
   };
   std::vector<Particle> particles;
   
   // SoA: 适合"批量处理单个属性"
   struct Particles {
       std::vector<float> x, y, z;
       std::vector<float> vx, vy, vz;
       std::vector<int> id;
       std::vector<char[32]> name;  // 冷数据分离
   };
   ```
   在 RTL 仿真中，门级节点通常有：当前值、类型、输入列表、输出列表、延迟等。如果每次仿真只访问"当前值"和"输入列表"，那么 AoS 会加载大量无用数据（类型、延迟、名称等）到 cache。

2. **Hot/Cold Splitting**:
   ```cpp
   struct GateHot {
       uint64_t value;           // 8 bytes — 每个时间步都访问
       uint32_t num_inputs;      // 4 bytes
       uint32_t input_start_idx; // 4 bytes — 索引到 cold 数组
   };  // 16 bytes, 4 个 GateHot  fits in one cache line
   
   struct GateCold {
       GateType type;            // 枚举，很少改变
       uint32_t delay;           // 静态时序
       char name[32];            // 调试信息
       std::vector<uint32_t> outputs;  // 输出列表（只在事件传播时访问）
   };
   ```
   将 `GateHot` 紧凑排列，每条 cache line 容纳 4 个门的热数据；`GateCold` 只在初始化或调试时访问。

3. **软件预取**:
   ```cpp
   for (size_t i = 0; i < n; ++i) {
       // 预取 8 个元素之后的数据
       __builtin_prefetch(&data[i + 8], 0, 3);  // 0=read, 3=high locality
       process(data[i]);
   }
   ```
   Algorithmica 的 benchmark 显示，在 LCG 指针追逐测试中，软件预取可以将性能提升约 **2 倍**。但预取距离（lookahead distance）需要精确调整：太近则预取未完成，太远则数据被踢出 cache。通常在循环中预取 8-16 个迭代步之后的数据。

4. **Loop Tiling / Blocking**:
   对于矩阵乘法或大规模数组操作，将循环按 cache size 分块：
   ```cpp
   // 原始：A[i][k] * B[k][j] — A 的列访问和 B 的行访问都是 stride-N，cache 不友好
   // 分块后：每次处理 BLOCK x BLOCK 的子矩阵，子矩阵能 fit in L1 cache
   for (int ii = 0; ii < N; ii += BLOCK)
     for (int jj = 0; jj < N; jj += BLOCK)
       for (int kk = 0; kk < N; kk += BLOCK)
         for (int i = ii; i < min(ii+BLOCK, N); ++i)
           for (int j = jj; j < min(jj+BLOCK, N); ++j)
             for (int k = kk; k < min(kk+BLOCK, N); ++k)
               C[i][j] += A[i][k] * B[k][j];
   ```
   在 RTL 仿真中，如果门级数据量超过 L2 cache，可以对门级数组按 cache line 分块处理，每次加载一个 block 到 cache 后集中处理。

5. **硬件预取器的利用**:
   现代 CPU 的硬件预取器可以识别：
   - 线性正向/反向扫描（`for (i=0; i<N; ++i)`）
   - 固定步幅访问（`for (i=0; i<N; i+=stride)`），stride 在 64B-4KB 之间
   无法识别：
   - 指针追逐（链表遍历）
   - 随机索引访问（`data[hash(key)]`）
   - 间接访问（`data[index[i]]`）
   在 RTL 仿真中，如果门的输入列表是指针数组，硬件预取器无法预取。需要软件预取或重排为索引数组 + 连续数据。

6. **Indirect Access 优化**:
   ```cpp
   // 原始：指针追逐，cache miss 每次迭代
   for (Gate* g = head; g; g = g->next) {
       process(g);
   }
   
   // 优化：索引数组 + 连续存储，让硬件预取器工作
   for (uint32_t idx : gate_indices) {
       __builtin_prefetch(&gate_data[gate_indices[i + 4]], 0, 3);
       process(gate_data[idx]);
   }
   ```

## 对 RTL 仿真器多线程化的启示

**稀疏计算 RTL 仿真器的核心挑战**：RTL 仿真本质上是事件驱动的图遍历。每个时间步，只有一小部分门（活跃门）需要被求值。活跃门的分布是稀疏且动态的。如果门级数据按 AoS 布局，且结构体包含大量冷数据（门类型、名称、延迟、调试信息），那么每次活跃门求值都会加载大量无用数据，浪费宝贵的 cache 带宽。

**具体应用建议**:

1. **门级数据使用 SoA + Hot/Cold Split**：
   将每个门的属性分离为独立的数组。每个时间步的活跃门列表（`active_gates`）是一个索引数组。处理时，按活跃门索引依次访问 `values[gate_idx]`、`input_indices[gate_idx]` 等：
   ```cpp
   struct CircuitSoA {
       std::vector<uint64_t> values;           // hot: 每个时间步都读/写
       std::vector<uint32_t> input_start;       // hot: 每个时间步读
       std::vector<uint32_t> input_count;       // hot: 每个时间步读
       std::vector<uint32_t> input_edges;       // hot: 求值时遍历输入
       
       std::vector<GateType> types;             // cold: 初始化时用
       std::vector<uint32_t> delays;            // cold: 静态时序分析
       std::vector<std::string> names;          // cold: 调试/波形输出
   };
   
   // 时间步处理：只访问 hot 数据
   for (uint32_t gate_idx : active_gates) {
       uint64_t new_val = evaluate(gate_idx, values, input_edges, input_start, input_count);
       if (new_val != values[gate_idx]) {
           values[gate_idx] = new_val;
           schedule_outputs(gate_idx, new_val, event_queue);
       }
   }
   ```
   这种布局让活跃门处理时，每条 cache line 都包含有效数据。假设 `values` 是 8 字节，`input_start` 和 `input_count` 各 4 字节，每条 cache line 可以容纳 4 个门的全部热数据。

2. **活跃门列表按数据依赖排序**：
   在仿真编译阶段（elaboration），按拓扑排序对门编号。同一层级的门之间没有数据依赖，可以并行处理。活跃门列表按门编号排序后，访问 `values` 数组是线性的，硬件预取器可以完美工作。

3. **输入边列表预取**：
   在 evaluate 函数中，遍历门的输入时，可以预取下几个门的输入边：
   ```cpp
   for (size_t i = 0; i < active_gates.size(); ++i) {
       uint32_t g = active_gates[i];
       // 预取下几个门的输入数据
       if (i + 4 < active_gates.size()) {
           uint32_t next_g = active_gates[i + 4];
           __builtin_prefetch(&values[next_g], 0, 3);
       }
       // 求值当前门
       evaluate(g);
   }
   ```
   预取距离 4 个门通常足够覆盖 L1 miss latency（~4-5ns × 4 = 16-20ns，而 L2 到 L1 的延迟约 4-12ns）。

4. **事件队列按目标门编号排序**：
   如果事件队列中的事件按目标门编号排序，处理事件时访问 `values` 数组也是线性的。可以用基数排序（radix sort）每时间步对事件队列排序，成本 O(N)，但 cache 效率提升远大于排序成本。

5. **冷数据按需加载**：
   门类型（AND/OR/NOT 等）在仿真运行时不会改变。可以将类型编码为 1-2 字节的 `uint8_t` 存储在 hot 数组中，而不是引用完整的 `GateType` 结构体。或者将求值逻辑编译为函数指针数组（vtable），避免运行时类型判断。

6. **门级输出列表的延迟加载**：
   输出列表（哪些门被当前门驱动）只在事件传播阶段访问。如果输出列表很大，可以将它存储在单独的结构中，只有在门值改变时才加载。这符合 DOD 的"按访问模式组织数据"原则。

## 原文摘录

> "Hardware prefetching is 100% harmless as it only activates when the memory and cache buses are not busy. Software prefetching is more powerful but harder to use correctly."
> — Algorithmica

> "The simplest way to do software prefetching is to load any byte in the cache line with the mov or any other memory instruction, but CPUs have a separate prefetch instruction that lifts a cache line without doing anything with it."
> — Algorithmica on __builtin_prefetch

> "Data-oriented design is about transforming data into the ideal form for the machine to process it. It is not about objects."
> — Mike Acton, CppCon 2014

> "AoS is cache-friendly when you access all fields of a struct sequentially. SoA is cache-friendly when you access one field across all elements sequentially."
> — Handmade Hero

## 相关链接

- [Algorithmica — CPU Cache Prefetching](https://en.algorithmica.org/hpc/cpu-cache/prefetching/)
- [Mike Acton — Data-Oriented Design (CppCon 2014)](https://www.youtube.com/watch?v=rX0ItVEVjHc)
- [Intel — Cache Blocking Techniques](https://www.intel.com/content/www/us/en/developer/articles/technical/cache-blocking-techniques.html)
- [Wikipedia — Loop Tiling](https://en.wikipedia.org/wiki/Loop_tiling)
- [Handmade Hero](https://handmadehero.org/)

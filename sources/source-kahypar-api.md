---
title: "KaHyPar C++ API 使用指南与代码示例"
description: "Mt-KaHyPar 官方仓库提供的 C Library 接口、超图创建、分区、固定顶点、自定义块权重等完整 API 调用示例"
source_url: "https://github.com/kahypar/mt-kahypar"
source_type: "github"
author: "Sebastian Schlag, Lars Gottesbüren, Tobias Heuer et al. (Karlsruhe Institute of Technology)"
date: "2025-02-11"
tags: ["KaHyPar", "超图划分", "C++ API", "Mt-KaHyPar", "RTL分区", "多线程"]
keywords: ["mtkahypar.h", "mt_kahypar_context_t", "hypergraph creation", "partition", "fixed vertices", "block weights"]
capture_date: "2025-01-20"
---

# KaHyPar C++ API 使用指南与代码示例

## 来源

- URL: <https://github.com/kahypar/mt-kahypar>
- 类型: github
- 作者: Sebastian Schlag, Lars Gottesbüren, Tobias Heuer 等 (KIT 算法工程组)
- 日期: 2025-02-11 (最新 master)

## 摘要

Mt-KaHyPar 是 KIT 开发的共享内存多级超图/图划分器，提供 C Library 接口 (`mtkahypar.h`)。
本文档汇总了从官方仓库 `lib/examples/` 中提取的 6 个完整示例：
超图文件读取、手动构建超图、图划分、固定顶点划分、自定义块权重划分、以及已有分区的改进（V-cycle）。
所有示例均使用 C++17 编译，可直接用于 RTL 电路网表的多线程划分原型。

## 关键要点

- **初始化**: `mt_kahypar_initialize(num_threads, interleaved_NUMA)` 必须先调用，创建 TBB 线程池。
- **Context**: 通过 `mt_kahypar_context_from_preset(PRESET)` 获取预设配置，支持 DEFAULT / QUALITY / HIGHEST_QUALITY / DETERMINISTIC / LARGE_K 等。
- **超图创建**: 支持从 `.hgr` (hMetis) 文件读取，也支持通过 `hyperedge_indices` + `hyperedges` 数组手动构建。
- **固定顶点**: 可预先指定某些节点归属的块，KaHyPar 保证在划分过程中不移动它们——对 RTL 中必须绑定到特定线程的 I/O 模块极其有用。
- **兼容性检查**: 不同 preset 使用不同的内部数据结构，必须在 partition 前调用 `mt_kahypar_check_compatibility()` 验证。
- **资源释放**: 必须调用 `mt_kahypar_free_context()` / `free_hypergraph()` / `free_partitioned_hypergraph()` 避免内存泄漏。

## 对 RTL 仿真器多线程化的启示

在 RTL 仿真器并行化中，Verilog 网表天然可建模为超图：
- **顶点 (node)** = 模块实例 / 逻辑门 / 组合逻辑块
- **超边 (hyperedge)** = 信号线 (net)，连接多个模块实例

使用 KaHyPar 的 C API 可以：
1. 将解析后的 Verilog 网表转换为 `hMetis .hgr` 格式或直接用内存数组构建超图；
2. 利用 **固定顶点** 将顶层输入/输出模块绑定到主线程，避免跨线程同步开销；
3. 利用 **自定义块权重** 根据各模块的仿真负载（组合逻辑深度、寄存器数量）设定不同线程的目标负载；
4. 通过 `KM1`（connectivity-1）目标函数最小化跨线程通信量，即跨分区切开的信号线数量；
5. 使用 Mt-KaHyPar 的多线程能力，在划分阶段本身也并行化，处理百万级实例的大规模 RTL 设计。

## 原文摘录

### 1. 基础超图划分 (从文件读取)

> 来自 `lib/examples/partition_hypergraph.cc`

```cpp
#include <cassert>
#include <memory>
#include <vector>
#include <iostream>
#include <thread>
#include <mtkahypar.h>

int main(int argc, char* argv[]) {
  mt_kahypar_error_t error{};

  // 1. 初始化线程池
  mt_kahypar_initialize(
    std::thread::hardware_concurrency() /* 使用全部核心 */,
    true /* 激活交错 NUMA 分配策略 */ );

  // 2. 设置分区上下文
  mt_kahypar_context_t* context = mt_kahypar_context_from_preset(DEFAULT);
  mt_kahypar_set_partitioning_parameters(context,
    2 /* 块数 */, 0.03 /* 不平衡度 3% */,
    KM1 /* 目标函数：connectivity-1 */);
  mt_kahypar_set_seed(42);
  mt_kahypar_status_t status =
    mt_kahypar_set_context_parameter(context, VERBOSE, "1", &error);
  assert(status == SUCCESS);

  // 3. 从 hMetis 文件读取超图
  mt_kahypar_hypergraph_t hypergraph =
    mt_kahypar_read_hypergraph_from_file("ibm01.hgr",
      context, HMETIS /* 文件格式 */, &error);
  if (hypergraph.hypergraph == nullptr) {
    std::cout << error.msg << std::endl; std::exit(1);
  }

  // 4. 执行分区
  mt_kahypar_partitioned_hypergraph_t partitioned_hg =
    mt_kahypar_partition(hypergraph, context, &error);
  if (partitioned_hg.partitioned_hg == nullptr) {
    std::cout << error.msg << std::endl; std::exit(1);
  }

  // 5. 提取结果
  auto partition = std::make_unique<mt_kahypar_partition_id_t[]>(
    mt_kahypar_num_hypernodes(hypergraph));
  mt_kahypar_get_partition(partitioned_hg, partition.get());

  auto block_weights = std::make_unique<mt_kahypar_hypernode_weight_t[]>(2);
  mt_kahypar_get_block_weights(partitioned_hg, block_weights.get());

  const double imbalance = mt_kahypar_imbalance(partitioned_hg, context);
  const int km1 = mt_kahypar_km1(partitioned_hg);

  std::cout << "Imbalance = " << imbalance << std::endl;
  std::cout << "Km1       = " << km1 << std::endl;

  // 6. 释放资源
  mt_kahypar_free_context(context);
  mt_kahypar_free_hypergraph(hypergraph);
  mt_kahypar_free_partitioned_hypergraph(partitioned_hg);
}
```

编译命令：
```bash
g++ -std=c++17 -DNDEBUG -O3 partition_hypergraph.cc -o example -lmtkahypar
```

### 2. 手动构建超图 (内存构造)

> 来自 `lib/examples/construct_and_read_hypergraph.cc`

```cpp
const mt_kahypar_hypernode_id_t num_nodes = 7;
const mt_kahypar_hyperedge_id_t num_hyperedges = 4;

// hyperedge_indices 定义每条超边的 pin 范围
std::unique_ptr<size_t[]> hyperedge_indices = std::make_unique<size_t[]>(5);
hyperedge_indices[0] = 0; hyperedge_indices[1] = 2; hyperedge_indices[2] = 6;
hyperedge_indices[3] = 9; hyperedge_indices[4] = 12;

std::unique_ptr<mt_kahypar_hyperedge_id_t[]> hyperedges =
  std::make_unique<mt_kahypar_hyperedge_id_t[]>(12);
// 超边 0: 节点 0, 2
hyperedges[0] = 0;  hyperedges[1] = 2;
// 超边 1: 节点 0, 1, 3, 4
hyperedges[2] = 0;  hyperedges[3] = 1; hyperedges[4] = 3;  hyperedges[5] = 4;
// 超边 2: 节点 3, 4, 6
hyperedges[6] = 3;  hyperedges[7] = 4; hyperedges[8] = 6;
// 超边 3: 节点 2, 5, 6
hyperedges[9] = 2; hyperedges[10] = 5; hyperedges[11] = 6;

// 节点权重
std::unique_ptr<mt_kahypar_hypernode_weight_t[]> node_weights =
  std::make_unique<mt_kahypar_hypernode_weight_t[]>(7);
node_weights[0] = 2; node_weights[1] = 1; node_weights[2] = 2; node_weights[3] = 4;
node_weights[4] = 1; node_weights[5] = 3; node_weights[6] = 3;

// 超边权重
std::unique_ptr<mt_kahypar_hyperedge_weight_t[]> hyperedge_weights =
  std::make_unique<mt_kahypar_hyperedge_weight_t[]>(4);
hyperedge_weights[0] = 1; hyperedge_weights[1] = 10;
hyperedge_weights[2] = 1; hyperedge_weights[3] = 10;

// 构建超图
mt_kahypar_context_t* context = mt_kahypar_context_from_preset(DEFAULT);
mt_kahypar_hypergraph_t hypergraph =
  mt_kahypar_create_hypergraph(context, num_nodes, num_hyperedges,
    hyperedge_indices.get(), hyperedges.get(),
    hyperedge_weights.get(), node_weights.get(), &error);
```

### 3. 图划分 (Metis 格式)

> 来自 `lib/examples/partition_graph.cc`

```cpp
mt_kahypar_context_t* context = mt_kahypar_context_from_preset(DEFAULT);
mt_kahypar_set_partitioning_parameters(context,
  2 /* 块数 */, 0.03 /* 不平衡度 */, CUT /* 目标函数：edge cut */);

// 从 Metis 格式读取图
mt_kahypar_hypergraph_t graph = mt_kahypar_read_hypergraph_from_file(
  "delaunay_n15.graph", context, METIS /* 文件格式 */, &error);

mt_kahypar_partitioned_hypergraph_t partitioned_graph =
  mt_kahypar_partition(graph, context, &error);

const int cut = mt_kahypar_cut(partitioned_graph);
std::cout << "Cut = " << cut << std::endl;
```

### 4. 固定顶点划分

> 来自 `lib/examples/partition_with_fixed_vertices.cc`

```cpp
mt_kahypar_hypergraph_t hypergraph =
  mt_kahypar_read_hypergraph_from_file("ibm01.hgr", context, HMETIS, &error);

// 读取固定顶点文件
std::unique_ptr<mt_kahypar_partition_id_t[]> fixed_vertices =
  std::make_unique<mt_kahypar_partition_id_t[]>(mt_kahypar_num_hypernodes(hypergraph));
status = mt_kahypar_read_fixed_vertices_from_file(
  "ibm01.k4.p1.fix", mt_kahypar_num_hypernodes(hypergraph), fixed_vertices.get(), &error);

// 将固定顶点添加到超图
status = mt_kahypar_add_fixed_vertices(
  hypergraph, fixed_vertices.get(), 4 /* 块数 */, &error);

// 分区
mt_kahypar_partitioned_hypergraph_t partitioned_hg =
  mt_kahypar_partition(hypergraph, context, &error);
```

固定顶点文件格式（每行一个节点，值为 -1 表示不固定，0..k-1 表示固定到对应块）：
```
-1
0
1
-1
...
```

### 5. 自定义块权重

> 来自 `lib/examples/partition_with_individual_block_weights.cc`

```cpp
// 设置各块的目标权重上限
std::unique_ptr<mt_kahypar_hypernode_weight_t[]> individual_block_weights =
  std::make_unique<mt_kahypar_hypernode_weight_t[]>(4);
individual_block_weights[0] = 2131;  // block 0 <= 2131
individual_block_weights[1] = 1213;  // block 1 <= 1213
individual_block_weights[2] = 7287;  // block 2 <= 7287
individual_block_weights[3] = 2501;  // block 3 <= 2501
mt_kahypar_set_individual_target_block_weights(
  context, 4, individual_block_weights.get());

mt_kahypar_hypergraph_t hypergraph =
  mt_kahypar_read_hypergraph_from_file("ibm01.hgr", context, HMETIS, &error);
mt_kahypar_partitioned_hypergraph_t partitioned_hg =
  mt_kahypar_partition(hypergraph, context, &error);
```

### 6. 已有分区改进 (V-cycle)

> 来自 `lib/examples/improve_partition.cc`

```cpp
// 先用 DEFAULT 读取超图
mt_kahypar_hypergraph_t hypergraph =
  mt_kahypar_read_hypergraph_from_file("ibm01.hgr", context_default, HMETIS, &error);

// 用 QUALITY preset 读取已有分区并改进
mt_kahypar_context_t* context_quality = mt_kahypar_context_from_preset(QUALITY);
mt_kahypar_set_partitioning_parameters(context_quality, 8, 0.03, KM1);

mt_kahypar_partitioned_hypergraph_t partitioned_hg =
  mt_kahypar_read_partition_from_file(
    hypergraph, context_quality, 8, "ibm01.hgr.part8", &error);

const int km1_before = mt_kahypar_km1(partitioned_hg);
// 执行一次 V-cycle 改进
mt_kahypar_improve_partition(partitioned_hg, context_quality,
  1 /* 1 次 multilevel improvement cycle */, &error);
const int km1_after = mt_kahypar_km1(partitioned_hg);
```

### 7. 兼容性检查

```cpp
mt_kahypar_context_t* context = mt_kahypar_context_from_preset(QUALITY);
if ( mt_kahypar_check_compatibility(hypergraph, QUALITY) ) {
  mt_kahypar_partitioned_hypergraph_t partitioned_hg =
    mt_kahypar_partition(hypergraph, context, &error);
}
```

### 8. CMake 集成

```cmake
find_package(MtKaHyPar)
if(MtKaHyPar_FOUND)
  add_executable(example example.cc)
  target_link_libraries(example MtKaHyPar::mtkahypar)
endif()
```

或使用 `FetchContent`：
```cmake
FetchContent_Declare(
  MtKaHyPar EXCLUDE_FROM_ALL
  GIT_REPOSITORY https://github.com/kahypar/mt-kahypar
  GIT_TAG        v1.5
)
FetchContent_MakeAvailable(MtKaHyPar)
add_executable(example example.cc)
target_link_libraries(example MtKaHyPar::mtkahypar)
```

## 相关链接

- [Mt-KaHyPar GitHub 仓库](https://github.com/kahypar/mt-kahypar)
- [KaHyPar (单线程版本)](https://github.com/kahypar/kahypar)
- [KaHyPar.jl (Julia 接口)](https://github.com/kahypar/KaHyPar.jl)
- [mt-kahypar-rs (Rust 绑定)](https://github.com/gzz2000/mt-kahypar-rs)
- [PyPI: mtkahypar](https://pypi.org/project/mtkahypar/)
- [官方文档: mtkahypar.h](https://github.com/kahypar/mt-kahypar/blob/master/include/mtkahypar.h)

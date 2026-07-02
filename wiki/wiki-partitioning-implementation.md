---
title: "分区算法实现指南"
description: "KaHyPar C++ API完整代码示例、参数调优配置、电路分区实践（hMetis/OpenROAD/CHSZLabLib），以及RTL多线程仿真器的分区策略与可操作建议"
source_refs: ["source-kahypar-api", "source-kahypar-tuning", "source-circuit-partitioning-tool"]
author: "Wiki写作_最终聚焦"
date: "2025-07-20"
tags: ["KaHyPar", "超图划分", "电路分区", "RTL分区", "hMetis", "OpenROAD", "VLSI"]
---

# 分区算法实现指南

## 1. KaHyPar API：6个官方示例

### 1.1 超图文件读取（从.hgr文件）

```cpp
#include <cassert>
#include <memory>
#include <vector>
#include <iostream>
#include <thread>
#include <mtkahypar.h>

int main(int argc, char* argv[]) {
    mt_kahypar_error_t error{};
    
    // 1. 初始化线程池（TBB）
    mt_kahypar_initialize(
        std::thread::hardware_concurrency(),  // 使用全部核心
        true                                  // 激活交错NUMA分配
    );
    
    // 2. 设置分区上下文
    mt_kahypar_context_t* context = mt_kahypar_context_from_preset(DEFAULT);
    mt_kahypar_set_partitioning_parameters(context,
        2,      // 块数（k=2）
        0.03,   // 不平衡度3%
        KM1     // 目标函数：connectivity-1
    );
    mt_kahypar_set_seed(42);
    mt_kahypar_set_context_parameter(context, VERBOSE, "1", &error);
    
    // 3. 从hMetis文件读取超图
    mt_kahypar_hypergraph_t hypergraph =
        mt_kahypar_read_hypergraph_from_file("ibm01.hgr", context, HMETIS, &error);
    if (hypergraph.hypergraph == nullptr) {
        std::cout << error.msg << std::endl; 
        std::exit(1);
    }
    
    // 4. 执行分区
    mt_kahypar_partitioned_hypergraph_t partitioned_hg =
        mt_kahypar_partition(hypergraph, context, &error);
    
    // 5. 提取结果
    auto partition = std::make_unique<mt_kahypar_partition_id_t[]>(
        mt_kahypar_num_hypernodes(hypergraph));
    mt_kahypar_get_partition(partitioned_hg, partition.get());
    
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

**编译命令**：`g++ -std=c++17 -DNDEBUG -O3 partition_hypergraph.cc -o example -lmtkahypar`

### 1.2 手动内存构建超图

```cpp
const mt_kahypar_hypernode_id_t num_nodes = 7;
const mt_kahypar_hyperedge_id_t num_hyperedges = 4;

// hyperedge_indices定义每条超边的pin范围 [start, end)
std::unique_ptr<size_t[]> hyperedge_indices = std::make_unique<size_t[]>(5);
hyperedge_indices[0] = 0;  hyperedge_indices[1] = 2;
hyperedge_indices[2] = 6;  hyperedge_indices[3] = 9;
hyperedge_indices[4] = 12;

std::unique_ptr<mt_kahypar_hyperedge_id_t[]> hyperedges =
    std::make_unique<mt_kahypar_hyperedge_id_t[]>(12);
// 超边0: 节点0, 2
hyperedges[0] = 0;  hyperedges[1] = 2;
// 超边1: 节点0, 1, 3, 4
hyperedges[2] = 0;  hyperedges[3] = 1; 
hyperedges[4] = 3;  hyperedges[5] = 4;
// 超边2: 节点3, 4, 6
hyperedges[6] = 3;  hyperedges[7] = 4; 
hyperedges[8] = 6;
// 超边3: 节点2, 5, 6
hyperedges[9] = 2;  hyperedges[10] = 5; 
hyperedges[11] = 6;

// 节点权重（仿真负载）
std::unique_ptr<mt_kahypar_hypernode_weight_t[]> node_weights =
    std::make_unique<mt_kahypar_hypernode_weight_t[]>(7);
node_weights[0] = 2;  node_weights[1] = 1;  node_weights[2] = 2;
node_weights[3] = 4;  node_weights[4] = 1;  node_weights[5] = 3;
node_weights[6] = 3;

// 超边权重（通信代价）
std::unique_ptr<mt_kahypar_hyperedge_weight_t[]> hyperedge_weights =
    std::make_unique<mt_kahypar_hyperedge_weight_t[]>(4);
hyperedge_weights[0] = 1;  hyperedge_weights[1] = 10;
hyperedge_weights[2] = 1;  hyperedge_weights[3] = 10;

// 构建超图
mt_kahypar_hypergraph_t hypergraph =
    mt_kahypar_create_hypergraph(context, num_nodes, num_hyperedges,
        hyperedge_indices.get(), hyperedges.get(),
        hyperedge_weights.get(), node_weights.get(), &error);
```

### 1.3 图划分（Metis格式）

```cpp
mt_kahypar_context_t* context = mt_kahypar_context_from_preset(DEFAULT);
mt_kahypar_set_partitioning_parameters(context, 2, 0.03, CUT);  // 目标函数：edge cut

mt_kahypar_hypergraph_t graph = 
    mt_kahypar_read_hypergraph_from_file("delaunay_n15.graph", context, METIS, &error);

mt_kahypar_partitioned_hypergraph_t partitioned_graph =
    mt_kahypar_partition(graph, context, &error);

const int cut = mt_kahypar_cut(partitioned_graph);
std::cout << "Cut = " << cut << std::endl;
```

### 1.4 固定顶点划分

```cpp
// 固定顶点文件格式：每行一个节点，-1=不固定，0..k-1=固定到对应块
// -1
// 0
// 1
// -1
// ...

std::unique_ptr<mt_kahypar_partition_id_t[]> fixed_vertices =
    std::make_unique<mt_kahypar_partition_id_t[]>(
        mt_kahypar_num_hypernodes(hypergraph));

mt_kahypar_read_fixed_vertices_from_file(
    "ibm01.k4.p1.fix", 
    mt_kahypar_num_hypernodes(hypergraph), 
    fixed_vertices.get(), 
    &error
);

mt_kahypar_add_fixed_vertices(hypergraph, fixed_vertices.get(), 4, &error);
mt_kahypar_partitioned_hypergraph_t partitioned_hg =
    mt_kahypar_partition(hypergraph, context, &error);
```

**RTL应用**：固定顶点可将顶层I/O模块绑定到主线程，避免跨线程同步开销。

### 1.5 自定义块权重

```cpp
// 设置各块的目标权重上限（异构负载场景）
std::unique_ptr<mt_kahypar_hypernode_weight_t[]> individual_block_weights =
    std::make_unique<mt_kahypar_hypernode_weight_t[]>(4);
individual_block_weights[0] = 2131;  // block 0 <= 2131
individual_block_weights[1] = 1213;  // block 1 <= 1213
individual_block_weights[2] = 7287;  // block 2 <= 7287
individual_block_weights[3] = 2501;  // block 3 <= 2501

mt_kahypar_set_individual_target_block_weights(
    context, 4, individual_block_weights.get());
```

### 1.6 V-cycle改进已有分区

```cpp
// 先用DEFAULT读取超图
mt_kahypar_hypergraph_t hypergraph =
    mt_kahypar_read_hypergraph_from_file("ibm01.hgr", context_default, HMETIS, &error);

// 用QUALITY preset读取已有分区并改进
mt_kahypar_context_t* context_quality = mt_kahypar_context_from_preset(QUALITY);
mt_kahypar_set_partitioning_parameters(context_quality, 8, 0.03, KM1);

mt_kahypar_partitioned_hypergraph_t partitioned_hg =
    mt_kahypar_read_partition_from_file(
        hypergraph, context_quality, 8, "ibm01.hgr.part8", &error);

const int km1_before = mt_kahypar_km1(partitioned_hg);
mt_kahypar_improve_partition(partitioned_hg, context_quality, 1, &error);  // 1次V-cycle
const int km1_after = mt_kahypar_km1(partitioned_hg);
```

### 1.7 CMake集成

```cmake
find_package(MtKaHyPar)
if(MtKaHyPar_FOUND)
    add_executable(example example.cc)
    target_link_libraries(example MtKaHyPar::mtkahypar)
endif()

# 或使用FetchContent
include(FetchContent)
FetchContent_Declare(
    MtKaHyPar EXCLUDE_FROM_ALL
    GIT_REPOSITORY https://github.com/kahypar/mt-kahypar
    GIT_TAG        v1.5
)
FetchContent_MakeAvailable(MtKaHyPar)
add_executable(example example.cc)
target_link_libraries(example MtKaHyPar::mtkahypar)
```

---

## 2. 参数调优

### 2.1 6种Preset质量/速度权衡

| Preset | 特点 | 速度 | 质量 | 推荐场景 |
|--------|------|------|------|----------|
| `large_k` | 最快，质量最低 | ★★★★★ | ★☆☆☆☆ | k >= 1024的多FPGA划分 |
| `default` | 快速，质量良好 | ★★★★☆ | ★★★☆☆ | 日常开发、快速迭代 |
| `deterministic` | 快速且结果可复现 | ★★★★☆ | ★★★☆☆ | CI/CD回归测试 |
| `quality` | 使用flow-based refinement | ★★☆☆☆ | ★★★★☆ | 生产环境最终分区 |
| `deterministic_quality` | 高质量+可复现 | ★★☆☆☆ | ★★★★☆ | 需要确定性的生产环境 |
| `highest_quality` | n-level+flow，最慢 | ★☆☆☆☆ | ★★★★★ | 对质量极端敏感的场景 |

**质量等级排序**：`large_k` < `default` < `deterministic` < `quality` < `deterministic_quality` < `highest_quality`

### 2.2 Default Preset核心参数解析

```ini
# === main -> coarsening ===
c-type=multilevel_coarsener
c-s=1                          # 重节点惩罚系数
c-t=160                        # 最粗层节点数阈值
c-min-shrink-factor=1.01       # 每层最小收缩因子
c-max-shrink-factor=2.5        # 每层最大收缩因子
c-rating-score=heavy_edge      # 评分函数
c-rating-acceptance-criterion=best_prefer_unmatched

# === main -> initial_partitioning ===
i-mode=rb                      # 递归二分
i-runs=20                      # 初始划分重复次数
i-use-adaptive-ip-runs=true
i-fm-refinement-rounds=1

# === main -> refinement -> fm ===
r-fm-type=unconstrained_fm
r-fm-multitry-rounds=10
r-fm-unconstrained-rounds=8
r-fm-seed-nodes=25
r-fm-time-limit-factor=0.25
r-flow-algo=do_nothing         # default关闭flow-based refinement
```

### 2.3 关键参数RTL专用调优配置

```ini
; RTL专用配置（基于default调优）

; === preprocessing ===
p-enable-community-detection=true
p-louvain-edge-weight-function=hybrid
; 电路网表社区检测效果很好，保持开启

; === coarsening ===
c-t=200                        ; 增大最粗层节点数，给初始划分更多空间
c-s=2                          ; 增大重节点惩罚，防止大型模块被过早合并
c-rating-score=heavy_edge      ; heavy_edge对带权超边效果最佳

; === initial partitioning ===
i-runs=30                      ; 初始划分增加尝试次数

; === refinement ===
r-fm-multitry-rounds=15
r-fm-seed-nodes=50             ; 增大种子数，覆盖更多边界节点
r-fm-unconstrained-min-improvement=0.001

; === objective ===
; 对RTL仿真器，优先使用KM1（connectivity-1）
; 因为它比cut-net更能反映跨线程通信代价
```

### 2.4 目标函数选择指南

| 目标函数 | 含义 | RTL场景适用性 |
|----------|------|--------------|
| **KM1** (connectivity-1) | 最小化跨分区信号线的总"连接数-1" | **推荐**。直接对应跨线程通信事件数 |
| CUT (cut-net) | 最小化被切开的超边数量 | 适合需要最小化"需要同步的不同信号数" |
| SOED (sum of external degrees) | 最小化外部度之和 | 适合关注总通信带宽的场景 |

### 2.5 不平衡度(epsilon)选择

| 场景 | epsilon | 说明 |
|------|---------|------|
| 标准场景 | 0.03 (3%) | 默认 |
| 异构负载场景 | 0.05-0.10 | 允许更多灵活性以容纳大型模块 |
| 严格平衡场景 | 0.01 | 需配合自定义块权重使用 |

---

## 3. 电路实践

### 3.1 hMetis .hgr格式

hMetis格式是电路网表超图的事实标准输入格式：

```
第一行（可选）：<has_edge_weights> <has_vertex_weights> <has_edge_sizes>
后续每行：一个超边（net），列出所有连接的顶点ID（1-indexed）
```

**无权重示例**（4个超边，7个顶点）：
```
4 7
1 3
1 2 4 5
3 4 6
2 5 6 7
```

**带权重示例**：
```
1 1 1
10 1 2 4 5    # 超边0，权重10，连接顶点1,2,4,5
5 3 4 6        # 超边1，权重5，连接顶点3,4,6
10 2 5 6 7     # 超边2，权重10，连接顶点2,5,6,7
1 1 3          # 超边3，权重1，连接顶点1,3
```

在电路语境中：
- **顶点** = 标准单元（cell）、门（gate）或模块实例（module instance）
- **超边** = 网（net），即连接多个单元的信号线
- **超边权重** = 信号位宽 × 切换频率 × 时序关键度

### 3.2 OpenROAD TritonPart时序感知分区

```tcl
# 基本分区命令
triton_part_hypergraph \
    -hypergraph_file des90.hgr \
    -num_parts 5 \
    -balance_constraint 2 \
    -seed 2

# 时序感知分区（关键路径权重因子）
triton_part_hypergraph \
    -hypergraph_file $hypergraph_file \
    -num_parts $num_parts \
    -balance_constraint $balance_constraint \
    -timing_aware_flag true \
    -net_timing_factor 1.0 \
    -path_timing_factor 1.0
```

**关键参数**：
| 参数 | 默认值 | 含义 |
|------|--------|------|
| `-timing_aware_flag` | true | 启用时序感知模式 |
| `-net_timing_factor` | 1.0 | 超边时序权重因子 |
| `-path_timing_factor` | 1.0 | 关键路径权重因子 |
| `-thr_coarsen_hyperedge_size_skip` | 200 | 忽略大于此阈值的超边（对大扇出时钟线有用） |

**对RTL仿真器的启示**：时序感知分区可将高优先级事件路径保持在同一线程内，减少跨线程调度延迟。

### 3.3 CHSZLabLib VLSI应用

```python
from chszlablib import HyperGraph, Decomposition

# 将电路网表加载为超图
hg = HyperGraph.from_hmetis("circuit_netlist.hgr")

# 计算最小割（瓶颈分析）
r = Decomposition.hypergraph_mincut(hg, algorithm="kernelizer", threads=8)
print(f"Min cut: {r.cut_value} nets, computed in {r.time:.2f}s")

# 流式划分：nets逐个到达，O(k + num_nets)内存
from chszlablib import FreightPartitioner
fp = FreightPartitioner(num_nodes=100_000, num_nets=50_000, k=8)
for node_id, nets in net_stream():
    block = fp.assign_node(node_id, nets=nets)
result = fp.get_assignment()
```

### 3.4 模块级vs门级划分

| 划分粒度 | 优点 | 缺点 | 适用场景 |
|----------|------|------|----------|
| **模块级** | 保持模块边界、利用层次信息、cutsize更小、便于调试 | 可能负载不平衡 | 初始划分首选 |
| **门级** | 更精细的负载平衡、可处理不规则设计 | 丢失层次信息、cutsize可能更大 | 模块级不平衡时展平后使用 |

**模块级+选择性展平算法**：
```
1. 构建超图：每个Verilog实例 = 一个顶点
2. 执行初始划分（如KaHyPar）
3. 检查负载平衡：
   - 若平衡 → 输出分区
   - 若不平衡 → 找到最大实例，将其展平为多个顶点
4. 在展平后的超图上重新划分
5. 重复3-4直到达到平衡约束
```

> "Our experiments show that this partitioning algorithm produces a smaller cutsize than is produced by hMetis on a gate-level netlist." — Lijun Li & Carl Tropper, 2003

### 3.5 ISPD98基准集

| 电路 | 单元数 | 网数 | 引脚数 | 特点 |
|------|--------|------|--------|------|
| ibm01 | 12,752 | 14,111 | 50,566 | 小型控制逻辑 |
| ibm02 | 19,601 | 19,584 | 81,949 | 中等规模 |
| ibm03 | 22,899 | 27,401 | 93,573 | 数据通路 |
| ibm04 | 27,520 | 28,220 | 105,859 | 复杂混合 |
| ... | ... | ... | ... | ... |
| ibm18 | 201,920 | 201,354 | 840,000+ | 大型SoC |

**KaHyPar vs hMetis在ISPD98上的性能**（2-way, 2% imbalance）：

| 电路 | hMetis cut | KaHyPar改进 | 提升幅度 |
|------|-----------|-------------|----------|
| ibm01 | 237 | 216 | -21 (-8.9%) |
| ibm03 | 923 | 887 | -36 (-3.9%) |
| ibm05 | 1,200 | 1,111 | -89 (-7.4%) |
| ibm06 | 810 | 765 | -45 (-5.6%) |

### 3.6 Verilog→超图→KaHyPar Python工作流

```python
class RTLPartitioner:
    def __init__(self, k, imbalance=0.03):
        self.k = k
        self.imbalance = imbalance
        self.instance_id = {}      # module instance -> hypernode ID
        self.net_to_pins = {}       # signal name -> [instance IDs]
        self.instance_weights = {}  # instance -> weight (load)
        self.net_weights = {}       # signal -> weight (communication cost)
    
    def add_instance(self, name, module_type, weight=1):
        self.instance_id[name] = len(self.instance_id)
        self.instance_weights[name] = weight
    
    def add_net(self, signal_name, pins, weight=1):
        self.net_to_pins[signal_name] = [self.instance_id[p] for p in pins]
        self.net_weights[signal_name] = weight
    
    def write_hmetis(self, filename):
        with open(filename, 'w') as f:
            # 第一行：超边数 顶点数 [格式标志]
            f.write(f"{len(self.net_to_pins)} {len(self.instance_id)} 1\n")
            # 每行：超边权重 顶点ID1 顶点ID2 ...
            for net, pins in self.net_to_pins.items():
                weight = self.net_weights.get(net, 1)
                pin_str = ' '.join(str(p+1) for p in pins)  # 1-indexed
                f.write(f"{weight} {pin_str}\n")
    
    def partition(self, preset="default"):
        import mtkahypar
        mtkahypar.initializeThreadPool(8)
        
        hypergraph = mtkahypar.Hypergraph(
            num_hypernodes=0, num_hyperedges=0,
            index_vector=[], edge_vector=[], weight_vector=[],
            k=self.k, imbalance=self.imbalance,
            objective=mtkahypar.Objective.KM1
        )
        hypergraph.readFromFile("netlist.hgr")
        
        context = mtkahypar.Context()
        context.loadPreset(getattr(mtkahypar.PresetType, preset.upper()))
        mtkahypar.partition(hypergraph, context)
        
        return {
            name: hypergraph.blockID(self.instance_id[name])
            for name in self.instance_id
        }

# 使用示例
p = RTLPartitioner(k=4)
p.add_instance("cpu_core", "CPU", weight=1000)
p.add_instance("memory_ctrl", "MEM", weight=500)
p.add_instance("uart", "UART", weight=50)
p.add_instance("spi", "SPI", weight=50)
p.add_net("cpu_bus", ["cpu_core", "memory_ctrl"], weight=32)
p.add_net("interrupt", ["cpu_core", "uart", "spi"], weight=1)
p.write_hmetis("soc_netlist.hgr")
assignment = p.partition(preset="quality")
print(f"CPU -> Thread {assignment['cpu_core']}")
print(f"Memory -> Thread {assignment['memory_ctrl']}")
```

---

## 4. 对多线程RTL仿真器的启示

### 启示1：门级超图划分是最佳分区粒度

模块级划分利用Verilog的层次结构信息，天然产生更小的cutsize。Verilog的`module`/`instance`层次对应超图的社区结构，KaHyPar的社区感知coarsening（`p-enable-community-detection=true`）能自动利用这一特性。

### 启示2：KaHyPar的V-cycle可提升质量

对同一设计多次迭代调优时，V-cycle能显著改善partition质量。RTL仿真器的分区通常在编译时只做一次，因此值得用V-cycle换取更少的跨线程通信。

### 启示3：时序感知分区减少关键路径跨线程

将关键路径上的信号赋予更高权重，避免时序关键路径被切开。在RTL仿真器中，这对应于将高优先级事件路径保持在同一线程内，减少跨线程调度延迟。

---

## 5. 可操作建议

### 建议1：用KaHyPar的C++ API直接集成

```cpp
// 在你的RTL仿真器编译器前端中集成KaHyPar
class MTaskPartitioner {
    mt_kahypar_context_t* context_;
    
public:
    MTaskPartitioner(int k, double imbalance = 0.03) {
        mt_kahypar_initialize(std::thread::hardware_concurrency(), true);
        context_ = mt_kahypar_context_from_preset(DEFAULT);
        mt_kahypar_set_partitioning_parameters(context_, k, imbalance, KM1);
    }
    
    std::vector<int> partition(const Netlist& netlist) {
        // 将netlist转换为KaHyPar超图
        auto [nodes, edges, indices, weights] = netlist.to_hypergraph();
        
        mt_kahypar_error_t error{};
        mt_kahypar_hypergraph_t hg = mt_kahypar_create_hypergraph(
            context_, nodes.size(), edges.size(),
            indices.data(), edges.data(), nullptr, weights.data(), &error);
        
        auto partitioned = mt_kahypar_partition(hg, context_, &error);
        
        std::vector<int> partition(nodes.size());
        mt_kahypar_get_partition(partitioned, partition.data());
        
        mt_kahypar_free_hypergraph(hg);
        mt_kahypar_free_partitioned_hypergraph(partitioned);
        return partition;
    }
};
```

### 建议2：先模块级粗分，再门级细分

```cpp
// 两阶段分区策略
class TwoStagePartitioner {
    std::vector<int> partition_module_level(const Design& design, int k) {
        // 第一阶段：模块级划分
        RTLPartitioner p(k, 0.05);  // 较宽松的不平衡度
        for (auto& inst : design.instances()) {
            p.add_instance(inst.name, inst.module_type, inst.estimate_weight());
        }
        for (auto& net : design.nets()) {
            p.add_net(net.name, net.connected_instances(), net.estimate_weight());
        }
        return p.partition("default");
    }
    
    std::vector<int> refine_gate_level(const Design& design, 
                                       const std::vector<int>& module_partition) {
        // 第二阶段：对不平衡的块进行门级细化
        for (int block = 0; block < k; block++) {
            if (is_imbalanced(block, module_partition)) {
                auto flattened = flatten_largest_instance(block);
                refine_with_gate_level(flattened);
            }
        }
        return final_partition;
    }
};
```

### 建议3：V-cycle提升partition质量

```cpp
// 编译时先用quality preset做初始分区，再用V-cycle改进
mt_kahypar_context_t* ctx_quality = mt_kahypar_context_from_preset(QUALITY);
mt_kahypar_set_partitioning_parameters(ctx_quality, k, 0.03, KM1);

auto partitioned = mt_kahypar_partition(hg, ctx_quality, &error);

// 执行1-2轮V-cycle改进
for (int i = 0; i < 2; i++) {
    mt_kahypar_improve_partition(partitioned, ctx_quality, 1, &error);
}
```

### 建议4：用OpenROAD验证时序约束

```tcl
# 在分区后使用时序分析验证关键路径是否被切开
read_verilog design.v
link_design design

# 提取时序报告
report_timing -path_type full -max_paths 10 > timing_report.rpt

# 检查关键路径是否跨线程
# 如果关键路径跨越了多个partition，考虑固定这些节点到同一线程
```

---

## 相关链接

- [Mt-KaHyPar GitHub](https://github.com/kahypar/mt-kahypar)
- [KaHyPar (单线程版本)](https://github.com/kahypar/kahypar)
- [PyPI: mtkahypar](https://pypi.org/project/mtkahypar/)
- [OpenROAD TritonPart文档](https://openroad.readthedocs.io/en/latest/main/src/par/README.html)
- [CHSZLabLib - VLSI超图操作](https://github.com/CHSZLab/CHSZLabLib)
- [ISPD98 Circuit Benchmark Suite](https://vlsicad.ucsd.edu/UCLAdvBench/)
- [circuitpartitioning.org](https://circuitpartitioning.org/)

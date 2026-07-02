---
title: "电路网表超图划分工具与 RTL 实践"
description: "hMETIS、KaHyPar、OpenROAD TritonPart 等工具在 VLSI 电路网表划分中的应用，以及从 RTL 到超图、从网表到多线程仿真分区的完整流程"
source_url: "https://circuitpartitioning.org/"
source_type: "doc"
author: "Multiple (hMETIS: G. Karypis; OpenROAD: DARPA IDEA; KaHyPar: KIT)"
date: "2025-01-20"
tags: ["电路划分", "VLSI", "hMETIS", "RTL分区", "netlist", "OpenROAD", "ISPD98", "benchmark"]
keywords: ["hMETIS", "hgr format", "netlist hypergraph", "gate-level partitioning", "RTL module partition", "circuit benchmark", "TritonPart"]
capture_date: "2025-01-20"
---

# 电路网表超图划分工具与 RTL 实践

## 来源

- URL: <https://circuitpartitioning.org/>
- URL: <https://openroad.readthedocs.io/en/latest/main/src/par/README.html>
- URL: <https://github.com/CHSZLab/CHSZLabLib>
- 类型: doc / github / paper
- 作者: 多源（G. Karypis / OpenROAD 团队 / KIT 算法工程组）
- 日期: 1998-2025

## 摘要

电路划分（Circuit Partitioning）是 VLSI CAD 和 EDA 领域的核心问题，目标是将门级网表或 RTL 模块划分为若干块，最小化跨块连线数（cut-net）同时保持负载平衡。
本文档综合 hMETIS 格式定义、OpenROAD TritonPart 的分区命令、CHSZLabLib 的 VLSI 应用示例，以及学术界对模块级 vs 门级划分的研究，为 RTL 仿真器多线程化提供完整的电路→超图→分区的实践路径。

## 关键要点

- **hMetis 格式 (.hgr)** 是电路网表超图的事实标准输入格式：第一行可选权重标志，第二行起每行一个超边（net），列出连接的所有节点（cell/门）。
- **hMETIS**（1998）是经典工具，但已停止维护；**KaHyPar** 和 **Mt-KaHyPar** 在 ISPD98 基准上全面超越 hMETIS，质量提升 3%-21%。
- **模块级划分**（module/instance-based）比门级划分（gate-level）更能利用设计层次信息，产生更小的 cutsize 和更好的仿真加速比。
- **OpenROAD TritonPart** 提供了工业级 Tcl 接口，支持时序感知分区、placement 感知分区、固定顶点、社区属性等高级特性。
- **ISPD98** 是电路划分最广泛使用的公开基准集（ibm01-ibm18）。

## 对 RTL 仿真器多线程化的启示

将 RTL 设计映射到多线程仿真器的核心步骤：
1. **解析 Verilog/VHDL 网表** → 提取模块实例和信号连接；
2. **构建超图** → 实例 = 顶点，信号线 = 超边；
3. **赋予权重** → 节点权重 = 实例的组合逻辑深度 / 仿真事件频率；超边权重 = 信号位宽 / 切换频率；
4. **划分** → 使用 KaHyPar 的 `KM1` 目标函数，最小化跨线程通信事件；
5. **映射到线程** → 将每个块分配给一个仿真线程，块内通信无需同步，跨块信号通过事件队列/锁/无锁结构传递。

模块级划分的额外优势：
- 保持模块边界完整，便于调试和性能分析；
- 自然对应 Verilog 的 `module` / `instance` 层次，无需展平网表；
- 可利用设计者的模块化意图（哪些模块应紧密协作）。

## 原文摘录

### 1. hMetis 超图文件格式 (.hgr)

> 来自 hMetis 用户手册和 circuitpartitioning.org

hMetis 格式是电路网表超图的标准输入格式，被 hMetis、KaHyPar、PaToH、TritonPart 等工具广泛支持。

**格式定义**：
```
第一行（可选）：<has_edge_weights> <has_vertex_weights> <has_edge_sizes>
  - 若第一行有 3 个整数，则解释为格式标志；若只有 1 个整数，则仅表示超边数

后续每行：一个超边（net），列出所有连接的顶点 ID
  - 顶点 ID 从 1 开始（1-indexed）
  - 每行第一个数可以是超边权重（若 has_edge_weights=1）
```

**示例**（无权重，4 个超边，7 个顶点）：
```
4 7
1 3
1 2 4 5
3 4 6
2 5 6 7
```

在电路语境中：
- **顶点** = 标准单元（cell）、门（gate）或模块实例（module instance）
- **超边** = 网（net），即连接多个单元的信号线
- 每条超边（net）的权重可设为：信号位宽 × 切换频率 × 时序关键度

**带权重的 hMetis 格式示例**：
```
1 1 1
10 1 2 4 5    # 超边 0，权重 10，连接顶点 1,2,4,5
5 3 4 6        # 超边 1，权重 5，连接顶点 3,4,6
10 2 5 6 7      # 超边 2，权重 10，连接顶点 2,5,6,7
1 1 3           # 超边 3，权重 1，连接顶点 1,3
```

顶点权重文件（`.vwgt`）格式：
```
2
1
2
4
1
3
3
```
每行对应一个顶点的权重，可用于表示模块的仿真负载。

### 2. hMETIS 命令行参数

> 来自 hMetis 用户手册 (G. Karypis, 1998)

```bash
# 递归二分（2-way bisection）
hmetis <hgr_file> <Nparts> <UBfactor> <Nruns> <CType> <RType> <VCycle> <Reconst> <dbglvl>

# k-way 划分（k >= 4）
khmetis <hgr_file> <Nparts> <UBfactor> <Nruns> <CType> <OType> <VCycle> <dbglvl>
```

**参数说明**：
| 参数 | 含义 | 示例值 |
|------|------|--------|
| `Nparts` | 目标块数 | 2, 4, 8 |
| `UBfactor` | 不平衡因子（%） | 5 = 49.5/50.5, 10 = 49/51 |
| `Nruns` | 每级递归的运行次数 | 10, 20 |
| `CType` | Coarsening 类型 | 1=FC, 2=GFC, 3=HFC, 11=FC+HEM |
| `RType` | Refinement 类型 | 1=FM, 2=FM+HEM, 3=FM+HEM+SHEM |
| `OType` | 目标函数 | 1=hyperedge cut, 2=SOED |
| `VCycle` | V-cycle 次数 | 0=无, 1=基本, 2=强化, 3=始终 |
| `Reconst` | 递归二分时的超边重构 | 0=移除切开超边, 1=重构 |

```bash
# 示例：将 ibm03.hgr 2 分，不平衡 5%，10 次运行，HFC coarsening，FM refinement，始终 V-cycle
hmetis ibm03.hgr 2 5 10 1 1 3 0 1 0

# 输出：
# Summary for the 2-way partition:
#   Hyperedge Cut: 956 (minimize)
#   Sum of External Degrees: 1912 (minimize)
#   Partition Sizes: 12419 [956] 10717 [956]
#   Timing: 85.190 sec
```

### 3. OpenROAD TritonPart 分区命令

> 来自 <https://openroad.readthedocs.io/en/latest/main/src/par/README.html>

OpenROAD 是 DARPA IDEA 项目支持的工业级开源 EDA 工具链，其 `TritonPart` 模块提供超图网表划分功能。

**基本分区命令**：
```tcl
# 类似 hMETIS 的最小割分区
triton_part_hypergraph \
  -hypergraph_file des90.hgr \
  -num_parts 5 \
  -balance_constraint 2 \
  -seed 2
```

**Placement 感知分区**：
```tcl
set num_parts 2
set balance_constraint 2
set seed 0
set design sparcT1_chip2
set hypergraph_file "${design}.hgr"
set placement_file "${design}.hgr.ubfactor.2.numparts.2.embedding.dat"
set solution_file "${design}.hgr.part.${num_parts}"

triton_part_hypergraph \
  -hypergraph_file $hypergraph_file \
  -num_parts $num_parts \
  -balance_constraint $balance_constraint \
  -seed $seed \
  -placement_file $placement_file \
  -placement_wt_factors { 0.00005 0.00005 } \
  -placement_dimension 2
```

**关键参数**：
| 参数 | 默认值 | 含义 |
|------|--------|------|
| `-num_parts` | 2 | 分区数 |
| `-balance_constraint` | 1.0 | 不平衡约束 |
| `-hyperedge_dimension` | 1 | 超边维度（多权重） |
| `-vertex_dimension` | 1 | 顶点维度（多权重） |
| `-thr_coarsen_hyperedge_size_skip` | 200 | 忽略大于此阈值的超边（对大扇出时钟线有用） |
| `-thr_coarsen_vertices` | 10 | 最粗层顶点数阈值 |
| `-thr_coarsen_hyperedges` | 50 | 最粗层超边数阈值 |
| `-timing_aware_flag` | true | 启用时序感知模式 |
| `-net_timing_factor` | 1.0 | 超边时序权重因子 |
| `-path_timing_factor` | 1.0 | 关键路径权重因子 |

**TritonPart 的时序感知特性**对 RTL 仿真器分区极具参考价值：
- `-net_timing_factor` 和 `-path_timing_factor` 允许将关键路径上的信号赋予更高权重，避免时序关键路径被切开；
- 在 RTL 仿真器中，这对应于将高优先级的事件路径保持在同一线程内，减少跨线程调度延迟。

### 4. CHSZLabLib VLSI 应用示例

> 来自 <https://github.com/CHSZLab/CHSZLabLib>

```python
from chszlablib import HyperGraph, Decomposition

# 将电路网表加载为超图（nets = hyperedges, cells = vertices）
hg = HyperGraph.from_hmetis("circuit_netlist.hgr")

# 计算最小割（瓶颈分析）
r = Decomposition.hypergraph_mincut(hg, algorithm="kernelizer", threads=8)
print(f"Min cut: {r.cut_value} nets, computed in {r.time:.2f}s")

# 对比多种算法
for algo in ["kernelizer", "submodular", "trimmer"]:
    r = Decomposition.hypergraph_mincut(hg, algorithm=algo)
    print(f"  {algo:12s}: cut={r.cut_value}, time={r.time:.3f}s")
```

**流式超图划分**（适合在线 RTL 设计）：
```python
from chszlablib import HyperGraph, Decomposition, FreightPartitioner

# 批量划分完整超图
hg = HyperGraph.from_hmetis("vlsi_netlist.hgr")
result = Decomposition.stream_hypergraph_partition(hg, k=8, algorithm="fennel_approx_sqrt")
print(f"Assignment: {result.assignment}")

# 流式划分：nets 逐个到达，O(k + num_nets) 内存
fp = FreightPartitioner(num_nodes=100_000, num_nets=50_000, k=8)
for node_id, nets in net_stream():  # 你的数据流
    block = fp.assign_node(node_id, nets=nets)
result = fp.get_assignment()
```

### 5. 模块级划分 vs 门级划分

> 来自 Lijun Li & Carl Tropper, "An Novel F-M Partitioning Algorithm for Parallel Logic Simulation" (2003)

> 原文摘录：
> "Many partitioning algorithms have been proposed for distributed Very-large-scale integration (VLSI) simulation. Typically, they make use of a gate level netlist and attempt to achieve a minimal cutsize subject to a load balance constraint. The algorithm executes on a hypergraph which represents the netlist. We propose a design-driven iterative partitioning algorithm for Verilog based on module instances instead of gates. We do this in order to take advantage of the design hierarchy information contained in the modules and their instances. A Verilog instance represents one vertex in the circuit hypergraph. The vertex can be flattened into multiple vertices in the event that a load balance is not achieved by instance-based partitioning. In this case, the algorithm flattens the largest instance and moves gates between the partitions in order to improve the load balance. Our experiments show that this partitioning algorithm produces a smaller cutsize than is produced by hMetis on a gate-level netlist. It produces better speedup for the simulation because it takes advantage of the design hierarchy."

**核心结论**：
1. **模块级划分**（instance-based）比门级划分产生 **更小的 cutsize**；
2. 利用设计层次信息获得 **更好的仿真加速比**；
3. 当负载不平衡时，可对最大实例进行 **选择性展平**（flatten），然后移动门级单元以改善平衡。

**算法流程**：
```
1. 构建超图：每个 Verilog 实例 = 一个顶点
2. 执行初始划分（如 hMetis / KaHyPar）
3. 检查负载平衡：
   - 若平衡 → 输出分区
   - 若不平衡 → 找到最大实例，将其展平为多个顶点
4. 在展平后的超图上重新划分
5. 重复 3-4 直到达到平衡约束
```

### 6. ISPD98 电路基准集

> 来自 <https://upcommons.upc.edu/>

ISPD98 是电路划分领域最广泛使用的公开基准集，包含 18 个电路（ibm01-ibm18）。

| 电路 | 单元数 | 网数 | 引脚数 | 特点 |
|------|--------|------|--------|------|
| ibm01 | 12,752 | 14,111 | 50,566 | 小型控制逻辑 |
| ibm02 | 19,601 | 19,584 | 81,949 | 中等规模 |
| ibm03 | 22,899 | 27,401 | 93,573 | 数据通路 |
| ibm04 | 27,520 | 28,220 | 105,859 | 复杂混合 |
| ... | ... | ... | ... | ... |
| ibm18 | 201,920 | 201,354 | 840,000+ | 大型 SoC |

**KaHyPar 在 ISPD98 上的性能**（2-way, 2% imbalance）：

| 电路 | hMetis cut | KaHyPar 改进 |
|------|-----------|-------------|
| ibm01 | 237 | -21 |
| ibm02 | 266 | +0 |
| ibm03 | 923 | -36 |
| ibm04 | 503 | -16 |
| ibm05 | 1,200 | -89 |
| ibm06 | 810 | -45 |

### 7. 异构 FPGA 的网表变换

> 来自 HETRIS (FPGA 2015)

> "Automated partitioning tools typically attempt to minimize the (hyper-)graph cut-size, while keeping the different partitions 'well balanced'. The heterogeneous nature of FPGA resources complicates balancing, and precludes using hMetis, as it does not support heterogeneous balance constraints. Metis does support heterogeneous balance constraints, but requires the input netlist to be transformed from a hyper-graph into a simple graph. A variety of netlist transformations have been proposed. We experimentally found a star net model with the inverse net fanout as the edge weights produced good partitions."

**对 RTL 仿真器的启示**：
- 当目标平台（CPU 线程）是**异构**的（如大核+小核），标准超图划分可能不够；
- 可考虑将超图转换为**简单图**（star net model），用每条边的权重 = 1/fanout 来近似超边代价；
- 或者使用 KaHyPar 的 **自定义块权重** 功能，为不同性能等级的线程设置不同容量限制。

### 8. 从 RTL 到超图的完整工作流

```python
# 伪代码：Verilog 网表 → 超图 → KaHyPar 分区 → 线程分配

class RTLPartitioner:
    def __init__(self, k, imbalance=0.03):
        self.k = k
        self.imbalance = imbalance
        self.instance_id = {}  # module instance -> hypernode ID
        self.net_to_pins = {}   # signal name -> [instance IDs]
        self.instance_weights = {}  # instance -> weight (load)
        self.net_weights = {}   # signal -> weight (communication cost)

    def add_instance(self, name, module_type, weight=1):
        self.instance_id[name] = len(self.instance_id)
        self.instance_weights[name] = weight

    def add_net(self, signal_name, pins, weight=1):
        # pins: list of instance names connected to this signal
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
        context.loadPreset(
            getattr(mtkahypar.PresetType, preset.upper())
        )
        mtkahypar.partition(hypergraph, context)

        # 返回 instance -> block 映射
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

## 相关链接

- [circuitpartitioning.org](https://circuitpartitioning.org/) - 电路划分资源汇总站
- [OpenROAD TritonPart 文档](https://openroad.readthedocs.io/en/latest/main/src/par/README.html)
- [CHSZLabLib - VLSI 超图操作](https://github.com/CHSZLab/CHSZLabLib)
- [ISPD98 Circuit Benchmark Suite](https://vlsicad.ucsd.edu/UCLAdvBench/)
- [hMETIS 用户手册 (PDF)](https://janders.eecg.utoronto.ca/1387/ex2_circuits/manual_hmetis.pdf)
- [Modularity-based clustering for placement (Integration 2020)](https://www.sciencedirect.com/science/article/abs/pii/S0167926019305711)
- [HETRIS: Adaptive Floorplanning for Heterogeneous FPGAs (FPT 2015)](https://www.eecg.utoronto.ca/~kmurray/hetris/fpt2015_hetris.pdf)
- [CoMHP: Multilevel cooperative search for circuit partitioning (IEEE TCAD 2002)](https://www.academia.edu/61354763/)

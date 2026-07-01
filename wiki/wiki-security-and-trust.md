---
id: "wiki-security-and-trust"
title: "硬件安全与可信验证"
description: "系统梳理RTL级硬件安全验证（Trust-Hub/AI检测/形式化工具）、功耗侧信道分析（SCAR/DPA/CPA/TVLA）与信息流跟踪（GLIFT/RTLIFT/SIFT/DIFT），为多线程RTL仿真器设计安全验证层的并行化架构"
tags: ["hardware-security", "trust-verification", "trojan-detection", "side-channel", "SCAR", "GLIFT", "RTLIFT", "SIFT", "DIFT", "formal-security"]
keywords: ["硬件木马", "Trust-Hub", "SCAR框架", "GNN侧信道", "DPA", "CPA", "TVLA", "GLIFT", "RTLIFT", "信息流跟踪", "形式化安全验证", "SAT求解"]
related_sources:
  - "source-hardware-security"
  - "source-side-channel"
  - "source-formal-security"
last_updated: "2026-07-02"
---

# 硬件安全与可信验证

安全验证不再是SoC设计的"附加题"，而是与功能验证同等关键的sign-off环节。RTL级多线程仿真器若要服务于现代安全关键型设计，必须考虑一个核心问题：**安全验证的计算密度远高于功能验证**——数百万次随机测试、数万条功耗轨迹、数亿节点的信息流图分析，这些任务在单线程下耗时惊人，而并行化又面临数据一致性、覆盖率合并与确定性调试的挑战。本章从硬件安全检测、侧信道分析和形式化安全验证三个维度，提炼对多线程RTL仿真器安全层设计的具体指导。

---

## 1. 硬件安全：从Trust-Hub到AI辅助检测

### 1.1 Trust-Hub基准：硬件安全验证的"ImageNet"

Trust-Hub是业界公认的硬件木马检测基准数据集，包含AES、RS232、PIC、VGA等经典设计的带木马版本。其核心价值在于提供了**ground truth**，使研究者可以客观比较不同检测算法的性能。

| 基准设计 | 木马类型 | 触发机制 | 检测难度 |
|----------|----------|----------|----------|
| AES-T100 | 组合触发 | 特定输入向量 | 低（覆盖率易触达） |
| AES-T200 | 时序触发 | 计数器+特定序列 | 中（需要长仿真） |
| RS232-T300 | 状态机篡改 | 协议异常序列 | 高（协议知识依赖） |
| PIC-T400 | 信息泄露 | 旁路编码 | 高（需要侧信道分析） |

### 1.2 UCI：未使用电路识别

Unused Circuit Identification（UCI）通过代码覆盖率分析识别RTL中从未被触发的逻辑——这些"死逻辑"可能是木马触发电路。但先进木马可利用低概率事件（如特定计数器序列、罕见I/O组合）规避UCI检测。

### 1.3 AI辅助检测：GNN与LLM的双轨路线

**GNN路线**：将RTL网表转换为图结构（节点=门/寄存器，边=连线），利用图神经网络自动提取结构异常特征。GNN对组合逻辑拓扑的敏感性使其能检测人工难以发现的微小植入。

**LLM路线**：Hayashi博士论文（USP, 2025）在Trust-Hub数据集上测试了Llama 3.3等模型，通过角色扮演提示优化，在196个复杂后量子密码设计上的检测准确率达**91%**。但70B参数以下模型泛化能力有限，且对提示工程高度敏感。

| 方法 | 输入表示 | 优势 | 局限 | 并行化需求 |
|------|----------|------|------|------------|
| **GNN** | RTL网表图 | 结构敏感，可解释 | 需大规模标注数据 | 图构建+推理可并行 |
| **LLM** | RTL源码文本 | 无需特征工程，语义理解 | 计算昂贵，泛化不稳 | 大batch推理可并行 |
| **规则-based** | 模式匹配 | 确定性，可解释 | 无法应对未知木马 | 独立规则可并行 |

### 1.4 形式化安全工具：Formal-PCH与QIF-RTL

**Formal-PCH（Proof-Carrying Hardware）**：将安全属性编码为证明，随硬件设计一起传递。下游验证者只需检查证明，无需重跑完整验证。

**QIF-RTL**：在RTL级量化信息流（Quantitative Information Flow），精确度量从敏感输入到公开输出的信息泄露量。

### 1.5 开源工具链验证流水线

```
SystemVerilog RTL
      ↓
  Yosys（综合）→ 网表
      ↓
  Verilator（快速仿真）→ 覆盖率+波形
      ↓
  OpenROAD（布局布线）→ 物理级验证
      ↓
  Trust-Hub基准对比 → 检测报告
```

---

## 2. 侧信道分析：SCAR框架与预硅安全评估

### 2.1 SCAR：RTL → CDFG → GNN → LLM 的端到端框架

SCAR（Side-Channel Analysis at RTL）是IEEE TVLSI 2024提出的预硅功耗侧信道分析框架，其核心创新在于**将GNN脆弱定位与LLM自动加固结合**：

```
RTL设计 ──→ CDFG（控制数据流图）──→ GNN推理 ──→ 脆弱模块定位 ──→ LLM加固
                ↑                                          ↓
           节点=操作, 边=依赖                    自动生成掩码/延迟插入代码
```

**关键性能数据**：
- 脆弱模块定位准确率：**94.49%**
- 精确率：**100%**
- 召回率：**90.48%**
- GNN可解释性分析：训练特征减少 **57%**

验证覆盖算法：AES、RSA、PRESENT、Saber、CRYSTALS-Kyber。

### 2.2 DPA / CPA / TVLA：经典侧信道方法论

| 方法 | 原理 | 所需轨迹数 | 统计基础 | 适用场景 |
|------|------|-----------|----------|----------|
| **DPA** | 差分功耗分析 | 数千~数万 | 均值差分假设 | 汉明重量模型 |
| **CPA** | 相关功耗分析 | 1万~10万 | Pearson相关系数 | 线性功耗模型 |
| **TVLA** | 测试向量泄漏评估 | 数万~数十万 | t-test Welch | 标准化泄漏评估 |
| **互信息** | 信息论量化 | 大量 | 互信息估计 | 精确泄露量度量 |

**核心瓶颈**：CPA和TVLA需要数万至数十万条功耗轨迹才能达到统计置信度。每条轨迹对应一次完整的RTL仿真运行。这意味着**单次侧信道安全评估 campaign 可能需要数百万次仿真迭代**。

### 2.3 防护对策量化：噪声注入vs封装电容

IEEE TDSC 2024的对策分析给出了关键量化数据：

| 对策 | 攻击轨迹数增加倍数 | 实现代价 | 对远程攻击有效 |
|------|-------------------|----------|--------------|
| 集成稳压器（IVR） | 高（对本地） | 中 | 否 |
| 电源噪声注入 | **37x** | 低 | 是 |
| 封装去耦电容 | 1.3x | 低 | 有限 |

**37x的噪声注入效果**意味着：如果原本1万条轨迹可破解密钥，注入噪声后需要37万条。但这对仿真器提出了更高要求——需要更多的仿真吞吐量来验证对策有效性。

### 2.4 LLM自动加固

SCAR在GNN定位脆弱区域后，使用大语言模型自动生成并插入防护代码（如掩码、随机延迟插入）。验证加固效果需要反复仿真-分析循环，即**设计空间探索（DSE）**。

---

## 3. 形式化安全验证：信息流跟踪与属性证明

### 3.1 信息流跟踪（IFT）核心机制

IFT为每个RTL变量关联安全标签（secret/public/trusted/untrusted），通过显式流（直接赋值）和隐式流（条件依赖）追踪信息传播。

```verilog
// 显式流：直接赋值，标签传播明确
assign public_data = secret_key ^ mask;  // secret标签流向public

// 隐式流：条件依赖，标签通过控制流传播
if (secret_bit)  // secret_bit影响控制流
    public_flag = 1;  // 即使直接赋值常数，也存在隐式流
```

**隐式流的建模是精度与复杂度的关键权衡**——精确追踪会导致状态空间爆炸，过度近似则产生误报。

### 3.2 GLIFT → RTLIFT：5倍性能跃迁

| 技术 | 抽象层级 | 状态空间 | 验证性能 | 精度 |
|------|----------|----------|----------|------|
| **GLIFT** | 门级网表 | 极大（百万门） | 基线 | 高（门级精确） |
| **RTLIFT** | RTL描述 | 显著减小 | **~5x提升** | 中（RTL级抽象） |
| **SIFT** | 静态分析 | 无需执行 | 快速（误报可能） | 低（过度近似） |
| **DIFT** | 动态仿真 | 执行路径决定 | 中（运行时开销） | 高（实际路径） |

RTLIFT直接在RTL描述上操作，利用更高抽象层级减少状态空间，实现约5倍性能提升。这证明**抽象层级每提升一级，验证吞吐量可数量级改善**——对需要海量验证的安全分析而言，这是关键杠杆。

### 3.3 安全属性分类与验证技术

| 属性 | 定义 | 验证技术 | 工具示例 |
|------|------|----------|----------|
| **保密性** | 敏感信息不泄露到未授权位置 | 等价性检查、SAT | Yosys+ABC+MiniSAT |
| **完整性** | 不可信实体不可覆盖可信数据 | 定理证明 | Coq/VeriCoq |
| **隔离性** | 不同信任域不可非法通信 | 类型系统、SMT | SVA + JasperGold |
| **常数时间** | 运行时无信息泄露（防时序攻击） | 模型检查 | Clepsydra |
| **设计完整性** | 检测恶意设计修改 | 信息流覆盖 | Hyperflow Graphs |

### 3.4 形式化验证技术栈

```
RTL Verilog
    ↓
Yosys（综合优化）→ 网表/逻辑表达式
    ↓
ABC（逻辑综合）→ AIG/CNF
    ↓
├─→ MiniSAT/zChaff（SAT求解）→ 可满足/不可满足
├─→ Yices2/Z3/Bitwuzla/CVC5（SMT）→ 模型/反例
└─→ Coq（定理证明）→ 严格数学证明
```

### 3.5 工业实践：Synopsys VCS T-Prop

Synopsys VCS的T-Prop（Taint Propagation）在RTL仿真中动态追踪污点传播，评估设计的保密性和弹性。FSV App（Formal Security Verification）使用"any value" SVA属性检查源是否能影响目标——这是**仿真与形式化混合验证**的工业标杆。

---

## 4. 对多线程RTL仿真器的启示

### 4.1 安全验证的计算密度是功能验证的10-100倍

从Trust-Hub的UCI方法到SCAR的功耗轨迹分析，安全验证的共性特征是**需要海量数据**：
- 木马检测：数百万次独立仿真运行
- 侧信道分析：数万至数十万条功耗轨迹
- 信息流覆盖：数亿节点图的可达性分析
- 形式化求解：大规模SAT/SMT实例

单线程仿真器无法在规定时间内完成这些任务。多线程化不是"锦上添花"，而是**安全验证可行性的前提**。

### 4.2 安全验证的并行化具有天然数据独立性

| 安全任务 | 数据独立性 | 并行策略 | 同步需求 |
|----------|-----------|----------|----------|
| **随机测试 campaign** | 完全独立（不同种子） | 每线程独立运行 | 最终覆盖率合并 |
| **功耗轨迹生成** | 完全独立（不同输入/密钥） | 每线程生成子集 | 离线统计聚合 |
| **SIFT图分析** | 读共享图，分析独立 | 图分片并行 | 结果合并 |
| **DIFT标签传播** | 功能仿真+标签跟踪耦合 | 每线程独立状态 | 跨模块边界标签同步 |
| **SAT求解** | 问题本身难并行 | 分块+Portfolio | 统一结果 |

### 4.3 覆盖率合并是安全验证的并行瓶颈

功能覆盖率在安全验证中升级为**信息流覆盖率**（information flow coverage），需要统计标签传播路径的覆盖情况。多线程仿真中：
- 每线程独立收集局部覆盖率 → 无锁、高效
- 最终合并全局覆盖率 → 需要线程安全的数据结构
- 覆盖率饱和度判断触发形式化补全 → 实时性要求高

---

## 5. 可操作建议：per-thread功耗轨迹生成 + 并行SIFT分析 + 安全覆盖率合并

### 5.1 架构级设计：安全验证层的并行化

```cpp
// 多线程安全验证引擎架构
class SecurityVerificationEngine {
    // 1. 每线程独立功耗轨迹生成
    struct PowerTraceGenerator {
        ThreadSafeRNG rng;
        std::vector<uint8_t> input_vectors;
        
        PowerTrace generate() {
            // 线程独立运行RTL仿真，采集toggle rate
            // 输出：时间-功耗样本序列
            return simulate_and_sample(rng.next());
        }
    };
    
    // 2. 并行SIFT信息流分析
    struct SIFTAnalyzer {
        // 共享的RTL依赖图（只读）
        const DataflowGraph& rtl_graph;
        
        // 分析指定子图的标签传播
        FlowResult analyze_subgraph(NodeRange range, SecurityLabel source) {
            // 图分析天然适合并行：每个子图独立BFS/DFS
            return label_propagation_bfs(rtl_graph, range, source);
        }
    };
    
    // 3. 线程安全的安全覆盖率合并
    struct SecurityCoverage {
        alignas(64) struct { std::atomic<uint64_t> hits; } 
            flow_path_counters[MAX_FLOW_PATHS];
        
        void merge_local(const LocalFlowCoverage& local) {
            for (auto [path_id, count] : local.hits) {
                flow_path_counters[path_id].hits.fetch_add(count, std::memory_order_relaxed);
            }
        }
    };
};
```

### 5.2 功耗轨迹生成的并行流水线

```cpp
// CPA/TVLA所需的功耗轨迹并行生成
class ParallelPowerTracePipeline {
    std::vector<std::thread> workers_;
    LockFreeSPSCQueue<PowerTrace> output_queue_;
    
public:
    void run_campaign(size_t total_traces, size_t num_threads) {
        const size_t per_thread = total_traces / num_threads;
        
        for (size_t t = 0; t < num_threads; ++t) {
            workers_.emplace_back([=]() {
                ThreadSafeRNG rng(global_seed_, t);
                for (size_t i = 0; i < per_thread; ++i) {
                    // 每线程：独立RTL仿真 + 功耗采样
                    auto plaintext = generate_plaintext(rng);
                    auto trace = run_simulation_and_sample(plaintext, key_);
                    output_queue_.enqueue(std::move(trace));
                }
            });
        }
        
        // 后台消费者：实时聚合相关系数
        std::thread stats_worker([&]() {
            StreamingCPA cpa;
            PowerTrace trace;
            while (output_queue_.dequeue(trace)) {
                cpa.update(trace);
                if (cpa.confidence_reached()) {
                    abort_campaign(); // 提前收敛，节省算力
                }
            }
        });
    }
};
```

### 5.3 多线程DIFT的标签传播同步

```cpp
// 动态信息流跟踪的跨线程标签同步
class ParallelDIFT {
    // 每个信号关联一个安全标签（bitmask）
    std::vector<std::atomic<TaintLabel>> signal_labels_;
    
public:
    void propagate_taint(const SignalUpdate& update, int thread_id) {
        TaintLabel new_label = TaintLabel::NONE;
        for (auto input : update.inputs) {
            new_label |= signal_labels_[input.id].load(std::memory_order_acquire);
        }
        
        // 显式流：直接传播
        if (update.is_explicit_flow) {
            signal_labels_[update.output.id].store(new_label, std::memory_order_release);
        }
        
        // 隐式流：控制依赖标签
        if (update.is_implicit_flow) {
            TaintLabel ctrl = signal_labels_[update.control_signal].load(std::memory_order_acquire);
            signal_labels_[update.output.id].store(new_label | ctrl, std::memory_order_release);
        }
    }
    
    // 跨线程一致性断言：检测非确定性标签传播
    bool check_cross_thread_consistency() {
        // 在barrier点验证：所有线程对同一信号的标签视图一致
        return verify_label_consistency_across_threads();
    }
};
```

### 5.4 安全覆盖率合并策略

| 合并频率 | 策略 | 开销 | 精度 | 推荐场景 |
|----------|------|------|------|----------|
| **每周期** | 全局原子更新 | 极高 | 精确 | 仅小设计 |
| **每1000周期** | 批量增量合并 | 中 | 近似 | 通用场景 |
| **每checkpoint** | 完全复制替换 | 高 | 精确 | 确定性调试 |
| **仿真结束** | 最终汇总 | 低 | 精确 | 非实时需求 |

推荐方案：每1000周期增量合并 + 仿真结束最终汇总。使用`std::memory_order_relaxed`的批量原子累加，避免每周期锁竞争。

### 5.5 混合验证的并行调度

```cpp
// 仿真+形式化混合验证的并行调度器
class HybridSecurityScheduler {
    enum class Engine { SIMULATION, BMC, SAT_SOLVER };
    
    void run() {
        #pragma omp parallel sections
        {
            #pragma omp section
            { // Section 1: 多线程仿真 campaign
              run_simulation_campaign(num_threads);
            }
            
            #pragma omp section
            { // Section 2: 形式化引擎（监控覆盖率饱和度）
              while (!coverage_saturated()) { sleep(100ms); }
              launch_bmc_for_uncovered_paths();
            }
            
            #pragma omp section
            { // Section 3: SAT求解器（处理形式化生成的子问题）
              run_sat_solver_pool();
            }
        }
    }
};
```

---

## 6. 综合检查清单

在将安全验证集成到多线程RTL仿真器时，逐条确认：

- [ ] 仿真器支持每线程独立的功耗轨迹生成，且随机种子可派生以保证可复现性
- [ ] 支持按时间窗口分片的功耗采集，多线程分片后支持离线拼接
- [ ] SIFT/Hyperflow Graph分析可基于IR层依赖图并行执行，图分区质量决定扩展性
- [ ] DIFT标签传播采用线程本地标签状态 + 跨边界原子同步，避免全局锁
- [ ] 安全覆盖率（信息流覆盖率）采用每线程本地副本 + 增量原子合并
- [ ] 支持覆盖率饱和度检测，自动触发形式化引擎补全验证
- [ ] CPA/TVLA统计分析的相关系数计算支持SIMD或GPU加速
- [ ] 形式化发现的反例能直接回注仿真器，生成VCD和调试信息
- [ ] 验证层资源（内存、CPU）与仿真引擎动态隔离，避免SAT求解器峰值OOM
- [ ] 支持Trust-Hub基准测试的自动化回归，结果可比对已知ground truth

---

## 参考来源

- [source-hardware-security](source-hardware-security.md) — Trust-Hub基准、AI检测（GNN/LLM）、形式化工具（Formal-PCH/QIF-RTL）、开源工具链
- [source-side-channel](source-side-channel.md) — SCAR框架、DPA/CPA/TVLA、防护对策量化（37x噪声）、LLM自动加固
- [source-formal-security](source-formal-security.md) — 信息流跟踪（GLIFT→RTLIFT 5x）、SIFT/DIFT、安全属性、SAT/定理证明、工业实践

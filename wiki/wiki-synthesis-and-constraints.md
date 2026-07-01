---
id: "wiki-synthesis-and-constraints"
title: "综合约束与逻辑综合影响"
description: "系统梳理SDC时序约束（create_clock / set_false_path / set_multicycle_path）、逻辑综合五步骤与RTL-GLS失配根因、STA静态时序分析模型（UDSM→FTGS），提炼对多线程RTL仿真器在分区指导、编译前端lint、SDF反标一致性方面的可操作建议"
tags: ["SDC", "logic-synthesis", "STA", "timing-constraints", "synthesis-mismatch", "SDF-back-annotation", "multicycle-path", "false-path", "entity-based-SDC"]
keywords: ["SDC约束", "逻辑综合", "STA", "setup/hold", "slack", "关键路径", "RTL vs GLS", "SDF反标", "UDSM", "FTGS", "Entity-Based SDC", "CPE约束传播"]
related_sources:
  - "source-sdc-constraints"
  - "source-synthesis-impact"
  - "source-sta-timing"
last_updated: "2026-07-08"
---

# 综合约束与逻辑综合影响

RTL 代码写完只是芯片设计长征的第一步。从 RTL 到门级网表，综合工具依据 SDC 约束做决策：哪些路径可以放松、哪些必须严格守时、多深的关键路径能容忍。对多线程 RTL 仿真器而言，这些约束不仅决定了“综合后芯片能不能跑”，还蕴含着**并行分区的天然提示**——`set_false_path` 标记的路径意味着同步可以放宽，`create_clock` 定义的是周期边界，`set_multicycle_path` 则给出了跨周期依赖的延迟预算。本章从 SDC 约束、逻辑综合、STA 时序分析三个维度，提炼对多线程 RTL 仿真器编译前端和运行时的具体设计指南。

---

## 1. SDC 约束：从 RTL 到网表的时序契约

### 1.1 核心约束命令语义

SDC（Synopsys Design Constraints）是贯穿综合、STA、P&R 的时序约束语言。现代 FPGA/ASIC 工具（Intel Quartus Prime、Lattice Radiant）已支持 **SDC-on-RTL**，即在 RTL elaboration 阶段就读取约束并作用于层次化网表。

| 命令 | 语义 | 对多线程仿真的映射 |
|------|------|------------------|
| `create_clock -name CLK -period 10 [get_ports clk]` | 定义时钟周期 10ns，占空比默认 50% | 周期边界 = 线程批量同步的 natural 时间点 |
| `set_false_path -from [get_clocks CLK_A] -to [get_clocks CLK_B]` | 切断指定路径的时序分析，不做 setup/hold 检查 | 跨时钟域路径可映射到不同线程，放宽同步要求 |
| `set_multicycle_path -setup 2 -from A_reg -to B_reg` | 允许数据在 2 个周期内传播，覆盖单周期关系 | 跨周期数据依赖 → 线程间通信可容忍 2-cycle 延迟 |
| `set_clock_groups -asynchronous -group {CLK_A} -group {CLK_B}` | 声明时钟组之间异步，不做跨组时序检查 | 天然线程分区边界：每组一个线程 |
| `set_max_delay / set_min_delay` | 显式覆盖路径的延迟上下界 | 可作为跨线程通信通道的延迟预算 |

### 1.2 Entity-Based SDC：模块化时序契约

Intel 的 Entity-Based SDC-on-RTL 允许 IP 作者将 SDC 约束封装在实体层级，通过 entity binding 自动前缀化路径名，防止约束泄漏到全局。每个 IP/实体的 SDC 可视为其**时序接口契约**——多线程调度器可以按实体边界划分线程，同时以 SDC 约束验证跨实体路径的时序一致性。

```tcl
# Entity-Based SDC 示例：封装在 my_fifo 实体内的约束
set_current_design my_fifo

create_clock -name fifo_clk -period 5 [get_ports clk]
set_false_path -from [get_clocks fifo_clk] -to [get_ports status*]

# 该约束仅在 my_fifo 实例内部生效，不会泄漏到顶层
```

### 1.3 CPE 约束传播引擎

Lattice Radiant 的 CPE（Constraints Propagation Engine）在综合前自动编译多个 `.sdc`/`.ldc` 文件，统一生成 `.ldc` 文件，解决子层级与 IP 约束之间的命名冲突和优先级问题。CPE 的**分层编译**思想可映射到多线程仿真器：将各模块的 SDC 约束编译为独立的时序元数据，运行时按需加载，避免全局解析瓶颈。

```cpp
// 多线程仿真器中的 CPE 式约束编译缓存
struct ConstraintModule {
    std::string module_name;
    std::vector<TimingConstraint> clocks;
    std::vector<PathException> false_paths;
    std::vector<PathException> multicycle_paths;
};

class CPECache {
    std::unordered_map<std::string, ConstraintModule> module_constraints_;
    
public:
    void compile_sdc_for_module(const std::string& module, const SDCFile& sdc);
    const ConstraintModule& lookup(const std::string& module) const;
};
```

---

## 2. 逻辑综合：五步骤与 RTL-GLS 失配

### 2.1 综合五步骤

综合工具将 RTL 描述转化为标准单元门级网表，执行以下五步骤：

| 步骤 | 动作 | 可能引入的失配 |
|------|------|---------------|
| 1. 解析与展开 | 读取 RTL、解析语法、展开 generate / 参数 | 非综合结构（如 `$display`）被静默丢弃 |
| 2. 技术映射 | 将 RTL 运算映射到标准单元库（NAND/NOR/FF/MUX） | 隐式延迟与 RTL 零延迟模型不一致 |
| 3. 优化 | 面积/速度/功耗三目标优化（重定时、资源共享、合并） | 数据依赖图改变，RTL 仿真无法预见 |
| 4. 约束处理 | 以 SDC 为输入，执行 timing-driven optimization | 约束不足 → 欠优化；约束过严 → 面积爆炸 |
| 5. 输出网表 | 生成 Verilog 网表 + SDF 延迟文件 | 网表结构变化导致 GLS 与 RTL 行为差异 |

### 2.2 RTL vs GLS：零延迟与真实延迟的鸿沟

RTL 仿真运行在零延迟或单位延迟模型下，仅验证功能正确性；门级仿真（GLS）通过 SDF 反标引入真实门延迟，可检测综合引入的 X 传播、时序违例、毛刺等 RTL 阶段无法暴露的 bug。

| 维度 | RTL 仿真 | 零延迟 GLS | SDF 反标 GLS |
|------|----------|-----------|--------------|
| 延迟模型 | 零延迟 / 单位延迟 | 所有门零延迟 | 真实 pin-to-pin 延迟 |
| 时序违例检测 | ❌ 无 | ❌ 无 | ✅ 可检测 setup/hold 违例 |
| X 传播 | LRM 默认乐观 | 网表结构决定 | 与网表一致 |
| 毛刺检测 | ❌ 无 | ❌ 无 | ✅ 门延迟差异导致 |
| 运行速度 | 最快（基准 1x） | 10x–30x 慢 | 100x 慢 |
| DFT/扫描链 | 不存在 | ✅ 存在 | ✅ 存在 |

### 2.3 综合-仿真失配五大根因

综合与仿真之间的差异（synthesis-simulation mismatch）是芯片流片失败的重要原因之一：

| # | 根因 | 典型场景 | 检测方法 |
|---|------|----------|----------|
| 1 | 综合解释错误 | 不完整敏感列表被综合工具补全，但 RTL 仿真行为不同 | 编译期 lint 检查敏感列表完整性 |
| 2 | X 传播差异 | RTL 乐观（X 求值为 false），GLS 悲观（X 扩散） | 启用 XPROP 模式 |
| 3 | 时序违例 | RTL 零延迟无法看见 setup/hold 违例 | SDF 反标 GLS 或 STA 报告 |
| 4 | 毛刺与险象 | 门延迟差异导致组合逻辑产生 runt pulse | SDF 反标 +  hazard 检测 |
| 5 | DFT/扫描链 | 综合后插入的扫描逻辑在 RTL 中不存在 | 专用 DFT 验证向量 |

### 2.4 编码风格陷阱：可综合性的 lint 检查清单

以下编码风格在 RTL 中合法，但会导致综合后行为不一致：

```verilog
// ❌ 陷阱1：不完整敏感列表（综合会补全，仿真不会）
always @(a)  // 缺少 b!
    y = a + b;

// ❌ 陷阱2：always 块左侧加 #delay（仿真延迟，综合忽略）
always @(posedge clk)
    #5 q <= d;  // 综合后 q 在 clk 沿立即更新

// ❌ 陷阱3：full_case/parallel_case 指令误导综合
always @(*)
casez(sel) // synopsys full_case parallel_case
    2'b0?: y = a;
    2'b1?: y = b;
endcase

// ❌ 陷阱4：将 X 作为 don't-care 赋值（综合视为任意，仿真传播 X）
assign next_state = (state == 2'b00) ? 2'b01 :
                    (state == 2'b01) ? 2'b10 : 2'bXX;  // X 在仿真中扩散
```

---

## 3. 时序分析：setup/hold 与延迟模型

### 3.1 setup / hold / slack 核心概念

| 概念 | 定义 | 公式 | 通过条件 |
|------|------|------|----------|
| **Setup Time** (Tsu) | 数据在时钟沿前必须稳定的最短时间 | — | Tclk ≥ Tcq + Tcomb + Tsu |
| **Hold Time** (Th) | 数据在时钟沿后必须保持的最短时间 | — | Th ≤ Tcq + Tcomb |
| **Slack** | 时序裕量 = 实际可用时间 − 要求时间 | Slack = Treq − Tarrival | Slack ≥ 0 通过 |
| **Critical Path** | 设计中 slack 最小的路径 | min(Slack) | 决定最高工作频率 |

### 3.2 延迟模型层级：UDSM → FTGS

从 RTL 到 GLS，延迟模型经历四个层级，精度逐步提升：

```
RTL (零延迟) → UDSM → FTSM → FTBM → FTGS
```

| 模型 | 名称 | 精度 | 用途 | 多线程仿真器映射 |
|------|------|------|------|------------------|
| **UDSM** | Unit Delay Structural Model | 组合单元 1ns、时序单元 2ns | 早期功能验证 | 可作为编译期静态检查目标 |
| **FTSM** | Full-Timing Structural Model | 含线延迟和 pin-to-pin 延迟 | 综合后初步 STA | 可选的轻量级延迟注入 |
| **FTBM** | Full-Timing Behavioral Model | 详细时序验证 | 网表级验证 | 需 SDF 解析支持 |
| **FTGS** | Full-Timing Optimized Gate-Level Simulation | 可调度 X 输出并报告时序违例 | 最终 sign-off | 完整 SDF 反标 + 多线程一致性 |

### 3.3 STA 与 GLS 的互补关系

STA 和 GLS 不是替代关系，而是互补：

- **STA**：数学遍历所有路径，速度快且完备；是 timing sign-off 的主力工具
- **GLS**：验证网表功能正确性、捕捉 X 传播、验证 DFT 逻辑；无法达到 STA 的路径覆盖
- **RTL 仿真**：验证功能逻辑正确性，覆盖率远高于 GLS（约 10x），但零延迟掩盖时序问题

DVCon 论文指出，在 RTL 阶段通过断言验证时序约束，可将 bug 发现时间从 GLS 的 **11+ 天** 缩短到 **3 天**。

---

## 4. 对多线程 RTL 仿真器的启示

### 4.1 SDC 约束蕴含同步信息

SDC 中的时序异常命令（`set_false_path`、`set_multicycle_path`）直接告诉仿真器：**哪些路径的同步可以放宽**。这对多线程调度是宝贵的启发式信息：

- `false_path` 标记的跨时钟域路径 → 可映射到不同线程，无需每周期 barrier
- `multicycle_path` 标记的路径 → 线程间通信可容忍 N-cycle 延迟，允许批量同步
- 未被豁免的严格单周期路径 → 优先映射到同一线程或相邻线程，避免跨线程同步开销引入伪时序违例

### 4.2 综合优化改变数据依赖图

综合优化（重定时、资源共享、合并）会改变 RTL 的数据依赖图。多线程 RTL 仿真器若按 RTL 原始依赖图分区，综合后的实际依赖可能不同，导致：

- 某些在 RTL 中看似独立的逻辑，综合后共享了门级资源 → 引入隐式数据依赖
- 某些在 RTL 中的长路径，综合后因重定时被拆分为短路径 → 并行度提升

**启示**：多线程仿真器应在编译时预留“综合优化模拟”的钩子，允许加载综合后的网表信息以重新优化分区。

### 4.3 需要支持 SDF 延迟反标的多线程一致性

当多线程 RTL 仿真器支持 SDF 反标（进入 FTGS 模式）时，必须保证：

- 跨线程的信号延迟一致性：同一条路径在两个线程中的延迟反标值必须相同
- 时序违例报告的原子性：setup/hold 违例检测不能因线程调度差异而漏报或误报
- Delta cycle 因果序：带延迟的事件仍需满足 delta cycle 的因果序，多线程下不能破坏

---

## 5. 可操作建议

### 5.1 用 SDC 约束指导多线程分区

```cpp
// SDC-aware 分区器：利用时序异常信息优化线程分配
class SDCAwarePartitioner {
    struct PathInfo {
        int src_partition;
        int dst_partition;
        bool is_false_path;      // set_false_path?
        bool is_multicycle;      // set_multicycle_path?
        int multicycle_cycles;   // N cycles
    };
    
    std::vector<PathInfo> paths_;
    
public:
    void load_sdc_constraints(const SDCFile& sdc);
    
    int assign_partition(const Module& module, const PathInfo& path) {
        if (path.is_false_path) {
            // false_path 路径：允许任意跨线程，无同步开销
            return load_balance_assign(module);
        } else if (path.is_multicycle) {
            // multicycle 路径：可容忍延迟，但需周期性同步
            return assign_with_lazy_sync(module, path.multicycle_cycles);
        } else {
            // 严格单周期路径：优先同线程
            return assign_same_or_adjacent(path.src_partition);
        }
    }
};
```

### 5.2 在编译器前端加入 lint 检查

```cpp
// 多线程 RTL 编译前端 lint 检查清单
enum LintSeverity { WARNING, ERROR };

struct LintRule {
    std::string name;
    LintSeverity severity;
    std::function<bool(const AST&)> check;
};

std::vector<LintRule> synthesis_mismatch_lint_rules = {
    {"incomplete-sensitivity-list", ERROR, 
     [](const AST& ast) { return check_sensitivity_completeness(ast); }},
    
    {"delay-on-lhs", ERROR,
     [](const AST& ast) { return !has_delay_on_assignment_lhs(ast); }},
    
    {"x-as-dontcare", WARNING,
     [](const AST& ast) { return !has_x_in_conditional_output(ast); }},
    
    {"full-parallel-case-misuse", WARNING,
     [](const AST& ast) { return !has_unsafe_synopsys_directives(ast); }},
    
    {"implicit-latch", ERROR,
     [](const AST& ast) { return !has_implicit_latch_in_combinational(ast); }},
    
    {"cdc-signal-missing-sync", ERROR,
     [](const AST& ast) { return check_cdc_sync_present(ast); }},
};

// 编译时自动运行，阻断综合失配根因
void compile_with_lint(const RTLFile& rtl) {
    AST ast = parse(rtl);
    for (auto& rule : synthesis_mismatch_lint_rules) {
        if (!rule.check(ast)) {
            report_lint(rule.severity, rule.name, ast.source_loc);
            if (rule.severity == ERROR) throw CompilationError(rule.name);
        }
    }
}
```

### 5.3 支持 SDF 反标的多线程一致性

```cpp
// SDF 反标在多线程环境下的原子延迟表
class SDFBackAnnotation {
    // 全局共享的延迟表（只读，线程安全）
    struct DelayEntry {
        uint64_t pin_delay_ps;      // pin-to-pin 延迟（皮秒）
        uint64_t wire_delay_ps;     // 线延迟
        uint64_t setup_time_ps;     // setup 约束
        uint64_t hold_time_ps;      // hold 约束
    };
    
    std::shared_ptr<const std::unordered_map<PinPath, DelayEntry>> delay_table_;
    
    // 线程本地时序违例缓存（周期性合并到全局）
    struct ThreadLocalTimingReport {
        std::vector<TimingViolation> violations;
        alignas(64) char pad[64];  // 防止 false sharing
    };
    std::vector<ThreadLocalTimingReport> per_thread_reports_;
    
public:
    void load_sdf(const SDFFile& sdf);
    
    // 查询延迟：只读，无锁
    uint64_t get_delay(const PinPath& path) const {
        return delay_table_->at(path).pin_delay_ps;
    }
    
    // 报告时序违例：写入线程本地缓存，避免锁竞争
    void report_violation(int thread_id, const TimingViolation& v) {
        per_thread_reports_[thread_id].violations.push_back(v);
    }
    
    // 周期边界：主线程合并所有线程的违例报告
    std::vector<TimingViolation> flush_violations() {
        std::vector<TimingViolation> all;
        for (auto& local : per_thread_reports_) {
            all.insert(all.end(), local.violations.begin(), local.violations.end());
            local.violations.clear();
        }
        return all;
    }
};
```

### 5.4 建立 RTL ↔ STA ↔ GLS 三角验证框架

```cpp
// 三角验证框架：多线程 RTL 仿真与 STA/GLS 的协同
class TriVerificationFramework {
    enum class Phase { RTL_SIM, STA_CHECK, GLS_SIGNOFF };
    
    // 1. 多线程 RTL 仿真：高覆盖率功能验证
    void run_rtl_regression() {
        // 生成大规模回归向量，利用多线程加速
        auto results = multithread_simulator_.run(test_vectors_);
        coverage_db_.merge(results.coverage);
    }
    
    // 2. STA 快速检查：每次 RTL 修改后运行
    void run_sta_quick_check() {
        // 解析 SDC，检查关键路径 slack
        auto critical_paths = sta_engine_.analyze(sdc_file_, rtl_netlist_);
        for (auto& path : critical_paths) {
            if (path.slack < 0) {
                warning("Critical path %s has negative slack: %f ps", 
                        path.name.c_str(), path.slack);
            }
        }
    }
    
    // 3. GLS 里程碑确认：在关键节点进行
    void run_gls_signoff() {
        // 用 SDF 反标网表，运行精选向量
        auto gls_results = gate_level_sim_.run_with_sdf(sdf_file_, signoff_vectors_);
        assert(gls_results.x_propagation_clean);
        assert(gls_results.no_timing_violations);
    }
    
    // 4. 相关性分析：VCD toggle 活动率 ↔ PrimePower 功耗
    void correlate_power() {
        auto toggle_activity = extract_toggle_activity(vcd_dump_);
        auto power_estimate = prime_power_.estimate(toggle_activity, netlist_);
        power_report_.compare(toggle_activity, power_estimate);
    }
};
```

---

## 6. 综合检查清单

- [ ] SDC 约束文件在编译期被解析为结构化时序元数据，支持 Entity-Based 模块化查询
- [ ] `set_false_path` 和 `set_multicycle_path` 信息被传递给线程分区器，指导同步粒度
- [ ] 编译器前端集成综合失配 lint 检查（敏感列表、延迟 LHS、X-don't-care、隐式锁存）
- [ ] 支持 UDSM → FTGS 四级延迟模型的可选反标，运行时按精度需求切换
- [ ] SDF 延迟表全局只读共享，时序违例报告采用线程本地缓存 + 周期性合并
- [ ] 关键路径（slack 最小）的逻辑区域优先分配到同一线程或相邻线程
- [ ] 建立 RTL 多线程回归 ↔ STA 快速检查 ↔ GLS 里程碑确认的三角验证流程
- [ ] 多线程下的 delta cycle 因果序在带延迟事件时仍被严格保持
- [ ] 支持加载综合后网表信息，重新优化线程分区以匹配实际数据依赖

---

## 参考来源

- [source-sdc-constraints](source-sdc-constraints.md) — SDC-on-RTL 机制、Entity-Based SDC、CPE 约束传播、path-group 约束
- [source-synthesis-impact](source-synthesis-impact.md) — 综合五步骤、RTL vs GLS 对比、五大失配根因、编码风格陷阱、X 传播差异
- [source-sta-timing](source-sta-timing.md) — STA 核心定义、setup/hold/slack、UDSM→FTGS 延迟模型、RTL 断言验证时序约束的价值

---
title: "RTL 回归测试与 CI/CD 集成：从夜间回归到覆盖率驱动的持续验证"
description: "RTL 仿真回归测试（Regression Testing）的自动化框架、Makefile 驱动流程、覆盖率闭环及与 CI/CD 工具的集成实践"
source_url: "https://www.cnblogs.com/loves6036/p/5811661.html"
source_type: "blog"
author: "Synopsys / VCS User Community / 技术博客"
date: "2024-06"
tags: ["regression-testing", "ci-cd", "nightly-regression", "coverage-driven", "vcs", "uvm", "makefile"]
keywords: ["regression suite", "nightly regression", "coverage merge", "urg", "autograding", "CI EDA", "batch simulation"]
capture_date: "2025-06-19"
---

# RTL 回归测试与 CI/CD 集成：从夜间回归到覆盖率驱动的持续验证

## 来源

- URL: https://www.cnblogs.com/loves6036/p/5811661.html (Synopsys VCS Makefile 模板)
- 类型: 技术博客 / 官方文档综合
- 作者: Synopsys; VCS 用户社区; LocusIT; Virtuoso QA
- 日期: 2024–2025

## 摘要

RTL 回归测试（Regression Testing）是芯片验证流程的「守门员」——每次设计变更后，通过自动运行全套测试激励来确保没有引入新的功能缺陷。现代验证团队通常采用「夜间回归（Nightly Regression）」配合「覆盖率驱动（Coverage-Driven）」策略，利用 Makefile 或 Python 脚本编排数百乃至数千个测试用例，并通过 URG 等工具合并覆盖数据。对于多线程 RTL 仿真器，回归测试的并行执行（多测试并发）和覆盖率数据的增量合并是天然的多线程场景。

## 关键要点

### 1. 回归测试的两阶段流程：Debug vs. Regression

Synopsys VCS 官方 Makefile 模板清晰区分了两个流程：

| 流程 | 波形 Dump | 覆盖率收集 | 目的 |
|------|----------|-----------|------|
| **Debug** | ✅ VPD/FSDB 开启 | ❌ 关闭 | 单测试调试、波形分析 |
| **Regression** | ❌ 关闭 | ✅ line+cond+fsm+branch+tgl | 批量跑测试、收集覆盖率 |

```bash
# Debug 流程：编译 + 运行 + 看波形
make test_1          # 编译并运行 test_1，生成 VPD
make gui_1           # 用 DVE 打开波形调试

# Regression 流程：编译 + 多种子运行 + 合并覆盖率
make regress_build_1         # 编译（覆盖率开启）
make regress_run_1 SEED=1234 # 用指定种子运行
make regress_urg             # 合并所有测试的覆盖率并生成报告
```

### 2. Makefile 驱动的回归自动化框架

```makefile
# 编译（Debug 模式）
COMPILE_DEBUG = vcs -full64 -sverilog -debug_access+all -f filelist.f

# 编译（Regression 模式）
COMPILE_REGRESS = vcs -full64 -sverilog \
    -cm line+cond+fsm+branch+tgl \
    -cm_name $(TEST_NAME) \
    -f filelist.f

# 运行（Regression）
RUN_REGRESS = ./simv -cm line+cond+fsm+branch+tgl +ntb_random_seed=$(SEED)

# 覆盖率合并
URG_MERGE = urg -dir simv.vdb -report report/
```

关键参数说明：
- `-cm line+cond+fsm+branch+tgl`：启用多维度覆盖率收集
- `-cm_name $(TEST_NAME)`：为每个测试单独命名覆盖率数据库，便于后续合并
- `+ntb_random_seed=$(SEED)`：UVM 随机测试的种子管理，保证回归可复现

### 3. 多测试批量运行脚本

```bash
#!/bin/bash
# run.sh：批量运行回归测试
for seed in $(seq 1 100); do
    make regress_run_1 SEED=$seed &
    # 控制并发度，避免许可证耗尽
    if (( seed % 8 == 0 )); then wait; fi
done
wait
make regress_urg
```

```bash
#!/bin/bash
# extract_coverage.sh：从所有测试报告中提取覆盖率指标
for dir in test_*/; do
    echo "Extracting from $dir..."
    grep -E "Line|Toggle|FSM|Branch" $dir/report/*.txt >> coverage_summary.csv
done
```

### 4. 覆盖率自动评分（Autograding）与测试精简

```bash
# 生成自动评分报告，识别每个测试对各覆盖率维度的独特贡献
vcs -cm_pp -cm line -cm_autograding 100
```

| Test No. | Incremental | Difference | Covered | Accumulated | Test Name |
|----------|------------|------------|---------|------------|-----------|
| 0 | 82.35 | 82.35 | 82.35 | 82.35 | TEST1 |
| 1 | 11.76 | 55.88 | 50.00 | 94.12 | TEST2 |
| 2 | 5.88 | 70.59 | 35.29 | 100.00 | TEST3 |

**Autograding 的意义**：
- 若某测试的 Incremental 为 0，说明它对总覆盖率没有新增贡献，可考虑移除以缩短回归时间。
- 通过 Difference 指标识别「最值钱」的测试，优先安排其在 CI 中运行。

### 5. CI/CD 集成：从夜间回归到每次提交触发

```yaml
# GitHub Actions / GitLab CI 示例
stages:
  - compile
  - regress
  - coverage

compile_job:
  stage: compile
  script:
    - make regress_build
  artifacts:
    paths:
      - simv

regress_job:
  stage: regress
  parallel: 8          # 8 个并发测试槽
  script:
    - make regress_run SEED=$CI_JOB_ID
  artifacts:
    paths:
      - simv.vdb/

coverage_job:
  stage: coverage
  script:
    - make regress_urg
    - python check_coverage_threshold.py --line 95 --toggle 90
```

**RTL 验证 CI 的最佳实践**：
- **Smoke Test**：每次代码提交后立即运行（5–10 分钟），快速拦截编译错误和基础功能崩溃。
- **Nightly Regression**：每晚运行完整测试套件（数百测试、不同种子），收集覆盖率并生成趋势报告。
- **Pre-Release Regression**：发布前运行全部测试 + 形式验证（Formal），作为 sign-off 条件。
- **资源管理**：EDA 工具许可证昂贵，CI 系统需实现许可证队列（License Queue）和动态任务调度。

### 6. 回归测试的性能优化

```bash
# 使用 VCS simprofile 分析回归测试的时间瓶颈
./simv +simprofile=time
profrpt -view time all simprofile_dir
```

从某硕士论文的 VCS 性能分析中可见，回归测试的时间分布：

| 组件 | 占比 |
|------|------|
| UCLI | 69.23% |
| KERNEL | 15.38% |
| License | 7.69% |
| PLI/DPI/DirectC | 7.69% |
| VERILOG | 7.69% |

**优化方向**：
- 减少不必要的波形 Dump（回归阶段关闭 VPD/FSDB）。
- 使用并行编译（`-j`）和增量编译（`-Mupdate`）加速 build。
- 对于纯随机测试，使用 coverage 反馈动态调整随机约束，减少冗余测试。

## 对 RTL 仿真器多线程化的启示

1. **测试级并行（Test-Level Parallelism）**：回归测试天然适合多进程/多线程并行——每个测试运行独立的仿真进程。多线程 RTL 仿真器可进一步在同一进程内并行化时间推进，实现「进程间并行 + 进程内多线程」的两层加速。

2. **覆盖率数据的增量合并**：多测试并发跑完后，合并 `.vdb` 目录中的覆盖率数据是瓶颈。多线程仿真器可以在线程本地维护覆盖位图，仅在 checkpoint 时刻通过原子操作合并到全局数据库，避免 I/O 密集型后处理。

3. **回归测试的确定性重播**：多线程仿真器必须支持「指定种子 → 相同结果」的确定性。VCS 的 `+ntb_random_seed` 机制依赖于线程调度顺序的稳定，因此多线程实现需保证随机数生成与线程分配关系的可复现性。

4. **CI 中的快速失败（Fail Fast）**：多线程仿真器可以在检测到首个断言失败或 UVM error 时立即终止整个测试（而非等到所有时间步跑完），这能显著缩短 CI 反馈周期。实现上需要线程安全的错误广播机制。

5. **许可证感知调度**：商业 EDA 仿真器的许可证是昂贵资源。多线程仿真器通过单进程多线程方式运行，可以复用同一个许可证运行更多并发测试，降低 CI 基础设施成本。

## 原文摘录

> "Regression tests are used to collect coverage information. The REGRESSION flow turns off VPD dumping and turns on Coverage Metrics and TB coverage collection." — Synopsys VCS Makefile Template

> "Autograding is coverage-type dependent. For example, a particular test case can be valuable for line coverage, but not for toggle or other types of coverage." — VCS Workshop Material

> "Nightly builds execute comprehensive regression suites overnight when infrastructure utilization is low. Teams arrive to fresh results each morning." — Virtuoso QA

> "Every code change undergoes regression validation. Failed tests prevent broken code from advancing." — Virtuoso QA on CI/CD Integration

> "The Makefile works on two separate flows. The DEBUG flow is intended to be used during debugging of a testcase and/or the DUT. The REGRESSION flow is used during regression runs and collects coverage data." — Synopsys Makefile 头部注释

## 相关链接

- [Synopsys VCS Makefile 模板详解](https://www.cnblogs.com/loves6036/p/5811661.html)
- [VCS 回归测试与形式验证集成 (LocusIT)](https://locusit.com/learning/advanced-and-trending-it-trainings/advanced-vcs-features-regression-formal-integration/)
- [Automated Regression Testing Guide](https://www.virtuosoqa.com/post/automated-regression-testing)
- [VCS 覆盖率自动评分与合并 (PDF)](https://picture.iczhiku.com/resource/eetop/WhIEfEITJdDHRCXM.pdf)
- [VCS 仿真性能分析（含回归测试时间分解）](https://escholarship.org/content/qt9dk022mm/qt9dk022mm.pdf)
- [VCS 查看代码覆盖率](https://www.cnblogs.com/dpc525/p/5071841.html)

---
id: "wiki-bounded-lookahead-rtl-sim"
title: "有界前瞻：多线程 RTL 仿真的 worker 内乱序执行"
description: "静态 worker 链内有界乱序执行协议：链内排序边 87.5% 保守洞察、DAG-only 传递归约 + 分组 owner-ready token + publisher-sibling 约束、内联热路径 + 冷尾表驱动、head 优先权、CoreMark -11.8%/Linux -12.6% 实测收益及被否决的协议设计"
tags: ["lookahead", "out-of-order", "worker-chain", "owner-ready", "token-grouping", "DAG-transitive-reduction", "head-priority", "stall-hiding", "rtl-sim"]
keywords: ["bounded lookahead", "worker idle spin", "conservative edge", "chain-aware reduction", "synthetic chain edge", "publisher sibling", "doneBit", "cold tail", "inline hot path", "head priority", "IPC stall hiding", "window sweep"]
last_updated: "2026-08-02"
---

# 有界前瞻：多线程 RTL 仿真的 worker 内乱序执行

## 概述

gsim-mt 的 dense 执行器把 45,163 个 SCC 收缩成 ~12,500 个 MTask，按关键路径分配到 32 个固定 worker，每个 worker 每拍按**静态链序**执行自己的 MTask 链。跨 worker 依赖用 owner-ready token 同步：head（链首）的 token 未就绪时，worker 只能自旋等待。

**实测各 worker 有 43–67%（均值 ~50%）的周期处于空转状态**--这是 T32 性能的头号浪费源。

有界前瞻（Bounded Lookahead）在 head 阻塞时让 worker 扫描链后方窗口内已就绪的条目提前执行，用独立条目的工作填掉 stall 气泡。

> **源文档**：`<workspace>/gsim-mt-lookahead-algorithm.zh.md`（完整设计与证明）
> **台账**：`<workspace>/gsim-task-verilator-dual-default4488/candidates.jsonl` v422/v426/v427/v428/v429/v434/v435

---

## 1. 核心洞察：链内排序边 87.5% 是保守的

对 12,539 条链内排序边的可达性证明（v422 W1.1）：

| 类别 | 数量 | 含义 |
|---|---|---|
| 真实 DAG 依赖（TRUE_DEP） | 1,569（12.5%） | 必须保持顺序 |
| **保守边（无路径）** | **10,967（87.5%）** | 仅由链序保证，两端无真实依赖 |
| 间接路径 | 3 | - |

**结论**：head 阻塞时，链后方绝大多数条目与 head 之间不存在真实依赖--它们已经可以安全提前执行。

离线模拟（W1.3）：有界前瞻窗口 N=128 可消除 17.2% 的 makespan。

> **v422a 否决**：编译时链重排（dep_depth / earliest-start / cross-pred-count）全面更差（−19.1% / −44.2% / invalid）。现 schedorder 的 cp 优先级链序已是最优固定链序，改善只能来自运行时乱序。

---

## 2. 协议设计（b1-constrained）

### 2.1 运行时流程

```
每拍开始: worker 进入内联 Phase 1
  ┌─ head 全部 token == target? ── 是 ── 内联直调 body + 内联释放 store list + head++
  │                                    └─ 回到检查
  └─ 否, 首个阻塞 ── 调用冷尾 stepDenseLookaheadTail（完整表 + 全局 startHead）
                         ┌─ head token 就绪? ── 是 ── 执行 head + 立即释放 + head++ + 跳过已置位项
                         │                         └─ 回到检查
                         └─ 否 ── 扫描窗口 head+1 .. head+1+N
                                    ┌─ 候选 j: 全部 wait token 就绪 且 本地前置全部完成?
                                    │    └─ 是 ── 执行 j + 立即释放 + doneBit 置位 + 立即 break 重检 head
                                    │              └─ 回到 head 检查
                                    └─ 窗口扫完无进展 ── 对 head 阻塞自旋（256 poll/yield）
```

### 2.2 内联热路径 + 冷尾表驱动

| 路径 | 结构 | 原因 |
|---|---|---|
| **Phase 1（热路径）** | 内联直调 body、内联释放 store list | 全链改表循环会交 4% 税（v379 实测 +4.02% 回退） |
| **冷尾** | 完整表 + 全局 startHead + 成员函数指针 | 仅在 head 首次阻塞时进入；表/位图只存在于冷尾 |

热路径保持内联直调，仅把阻塞自旋换成非阻塞就绪测试。

### 2.3 三个安全门

候选 j 可执行 ⟺ 全部满足：

1. **跨 worker 门**：j 的 wait list 中全部 token == 当前拍 target（非阻塞读）。token 按 (destination, producerOwner) 分组，覆盖全部跨 worker 真依赖。
2. **同 worker 本地前置门**：j 的全部本地前置位置完成--判定式 `p < head || (anyOutOfOrder && doneBit(p))`。前置集 = 同 worker DAG 保留前驱 ∪ **publisher sibling**。
3. **head 优先权**：每执行一个候选立即 break 重检 head--head 在关键路径上，其启动延迟比扫描开销更贵。

---

## 3. 为什么不能复用旧协议（三个陷阱与解法）

| 陷阱 | 后果 | 解法 |
|---|---|---|
| 旧运行时归约注入了**合成链边**（`previousOnWorker->mtaskId`）才做删除--删除只在全链有序下成立 | 乱序下被删的真实跨 worker 依赖裸奔，消费者读过期数据 | **从原始 MTask DAG 重做仅 DAG 的传递归约**，用其重建 token 分组（13,679–14,116 组 vs 原 5,195，建模回归仅 +3.06%） |
| 分组 token 的释放只由组内链序最后的 source（publisher）执行；publisher 乱序先于同组独立 sibling → 提前发布 | 消费者在全部组内生产者完成前读取 | **publisher-sibling 位置物化为本地前置**（909 条目 / 3,163 位置，建模代价 <1%） |
| 表驱动常路径（成员函数指针）实测 +4.02%（v379） | 把全链改表循环会交 4% 税 | **内联 Phase 1 + 冷尾**：热路径保持内联直调，仅阻塞自旋换成非阻塞就绪测试 |

### 3.1 chain-aware 传递归约为何在 OOO 下不成立

旧协议的传递归约依赖合成链边 `previousOnWorker->mtaskId`：它假设全链按序执行，因此链上相邻条目间的跨 worker 依赖可以通过链边传递到达，无需直接保留。但在乱序执行下，链边不再是执行顺序的保证--被链边"覆盖"删除的真实跨 worker 依赖会裸奔，消费者可能在生产者尚未执行时读取过期数据。

**解法**：从原始 MTask DAG（不含合成链边）重做传递归约。代价是 token 组数从 5,195 增至 13,679–14,116（更多组 = 更多 token），建模回归仅 +3.06%。

---

## 4. 正确性要点（6 引理，详见设计文档 §W3）

1. **链序即拓扑序**：同 worker 真依赖 pred→succ 满足 position(pred) < position(succ)。
2. **仅 DAG 归约保可达**：token + 本地前置覆盖全部全 DAG 前驱。
3. **publisher 约束保证释放不会早于其代表的全部写入**。
4. **head 无需检查**（head 性质）；候选须过三个安全门的全部。
5. **完成归纳**：任意完成 ⟹ 其全部全 DAG 前驱完成（跨 worker HB 与严格序相同）。
6. **确定性**：扫描升序、首合格即执行、独立条目可交换。

> **经验证据**：C5000 与 C50000 各 100 次重复 NEMU-clean、端点全一致。stdout 帧框非 bit 一致属 v370 打印警告类（L3 豁免，参见 [[wiki-pointer-order-nondeterminism]] §1）。

---

## 5. 实测收益（全部 NEMU 精确、fixed-mask 交错、非重叠）

### 5.1 主结果

| 负载 | 对照（无前瞻） | LOOKAHEAD=128 | delta |
|---|---|---|---|
| CoreMark C50000 | 7,177.7ms | **6,329.7ms** | **−11.81%** |
| Linux 100K | 14,466.0ms | **12,644.3ms** | **−12.60%** |
| Linux 1M | 142,674.7ms | **126,232.7ms** | **−11.52%** |

### 5.2 机制证据（perf，C50000）

| 指标 | 对照 | N=16 | N=128 |
|---|---|---|---|
| 指令数 | 262.3G | 318.9G | 505.2G |
| **IPC** | **0.31** | **0.42** | **0.69** |
| 分支误预测率 | 1.20% | 1.19% | 0.91% |

**收益机制**：head 阻塞时 worker 不再空转，转去执行链后方已就绪的条目--stall 被填掉（IPC 0.31→0.69）。扫描/簿记指令虽然多（最高 +92.6%），但运行在否则闲置的 stall 周期里。分支预测不受影响（表间接未表现为 v379 式误预测）。

### 5.3 收益归因：依赖 stall 消除，不是带宽再平衡

perf 专项（C50000，对照 vs N=128）：

| 指标 | 对照 | N=128 | delta |
|---|---|---|---|
| cycles | 842.5G | 742.2G | −11.9% |
| **stalled-cycles-backend** | **228.3G（27.09%）** | **158.2G（21.31%）** | **−30.7%** |
| stalled-cycles-frontend | 2.38G（0.28%） | 2.67G（0.36%） | +12% |
| cache-references | 31.4G | 30.1G | −4.0% |
| cache-misses | 13.1G（41.75%） | 12.8G（42.59%） | −2.1% |

周期下降的 ~70% 来自**后端 stall 消除**（228.3G→158.2G），而访存流量几乎不变（misses −2.1%、miss 率持平 41.8%→42.6%）。若机器受 DRAM/L3 带宽饱和约束，不可能在流量不变下削掉 30% 后端 stall--**带宽本来就有余量**。stall 的本质是跨 worker token 的依赖等待，前瞻用独立条目的工作（连同其访存，现在被重叠发射）把气泡填掉。"计算与访存重叠"只在 MLP 重叠这个有限意义上成立，**不是 roofline 式再平衡**。

---

## 6. 窗口 N 的选择

### 6.1 实测扫描（同一 12,571 调度双生，仅窗口字面量不同）

| N | CoreMark 均值 | Linux 100K 均值 | 指令数（C50000） |
|---|---|---|---|
| 16 | 6,483.0ms | - | 318.9G |
| 32 | 6,406.0ms | 12,717ms | - |
| 64 | 6,350.7ms | **12,583ms** | - |
| 128 | 6,355.3ms | 12,888ms | 505.2G |
| 256 | **6,294.7ms** | 12,660ms | - |

### 6.2 结论：弱 workload 相关，宽平台

- **宽平台**：N=64–256 在两种负载下互相差距都在 ~2%（噪声级）。
- **弱 workload 相关**：精确最优点随负载移动--CoreMark 偏好 ≥128（stall 深、就绪窗口利用率随 N 增大仍有微益），Linux 偏好 ~64（依赖链更短、IPC 更高，过大窗口的扫描开销开始抵消收益）。**这不是强相关：取 N∈[64,128] 在两类负载上都接近最优**。
- **指令效率视角**：N=16 用 63% 的指令数拿到大部分收益（−9.68%）；若未来 CPU 成为瓶颈，N=16 是指令效率最优点。
- **当前冠军值 N=128 不是精确最优但处于平台内**：离 CoreMark 实测最优（N=256，−0.9%）和 Linux 实测最优（N=64，−2.4%）都在噪声范围。若重调，N=64 是两类负载上最稳健的单值；N=128 保留为冠军默认（default-off knob，可随时切换）。

---

## 7. head 优先权与批量执行否决

**v429 批量扫描（cap 4）**：执行最多 4 个合格候选后再重检 head，以减少重扫开销。

| 指标 | cap-1（break 重检） | cap-4（批量） | delta |
|---|---|---|---|
| C50000 均值 | 6,302.0ms | 6,787.3ms | **+7.71%** |

**隔离**：不可变调度双生（`diff -qr` 仅 1 文件 23 行差异 = 批量改动本身），12,571-MTask 调度一致，emu 大小一致。全部 6 次 NEMU 精确。

**结论**：head 优先权代价远超重扫节省。head 在关键路径上，其启动延迟比省下的扫描指令更贵。**REJECTED，已回退**。

---

## 8. 被否决的协议设计（选型证据）

| 设计 | 结果 | 教训 |
|---|---|---|
| **b1 DAG-only token + publisher 约束（晋级）** | +18.2% 建模 / +11.8% 实测 | - |
| b2 witness-safe（现 token + 仅无链见证删边者可乱序） | +0.5%，自由塌缩（71.1% 条目带见证删边） | 保守利用链序不可行 |
| b7 epoch 混合（每 MTask epoch + 逐个前驱 epoch 扫描） | λ≥40ns 或 f≥0.25 即亏；候选确认读数 4× 于 b1 | 逐前驱远程读太贵，分组是压缩 |
| producer counting（每边 fetch_sub） | 17,663 RMW/拍，全面劣于 b1 分组 load/store | v285 单写结构不可放弃 |
| v429 批量扫描（cap 4） | +7.7% 回退（不可变调度双生隔离） | head 优先权 > 重扫节省 |
| 表驱动常路径（v379） | +4.02% 回退 | 表/指针只能进冷路径 |
| 等待期预取（v435） | +4.67% 回退 | 预取循环指令开销超过隐藏的 L2/L3 延迟 |
| 提前释放（release-point f=0.5/0.7/0.9） | −0.45%/+0.00%/+0.27%，预检否决 | 前瞻已重叠大部分生产者延迟 |
| LPT 静态分配 | 模拟 strict 9,436.7 vs 7,411.5，前瞻后 6,997.4 vs 5,711.3--全面更差 | 现分配策略更优 |
| worker 内链重排（cp/成本序） | strict 11,740 vs 7,411--更差 | v422a 结论在前瞻下复现：现 cp 优先级已最优 |

### 8.1 等待期预取（v435）详细否决

**设计**：head 阻塞自旋时预取跨 worker 生产者状态字段（offsetof via definedNode-exact fields），重叠 L2/L3 延迟。

**机制评估**：成立（stall 为 µs 级，预取有充足时间；stall 是延迟非带宽）。

**实测**：{7,960, 7,883, 7,770} vs 对照 {7,627, 7,553, 7,378}，**+4.67% 回退**。同调度双生（指纹 `2ff374a4802a561ecad0277e` 一致）、全 NEMU 精确。8,916 列表条目 / 459,740 offsets；每次阻塞的预取循环指令开销超过其隐藏的 L2/L3 延迟。**REJECTED，已回退**。

---

## 9. 动态化评估（离线模拟）

| 方向 | 机制 | 结果 | 结论 |
|---|---|---|---|
| 运行时自适应窗口 N | 按 stall 深度动态调窗口 | 受宽平台限制（N=64–256 实测互相 ~2%） | 上限 ~2%，边际收益不抵策略复杂度 |
| 动态候选选择（maxcp / maxcost） | 窗口内选最关键候选而非升序首个 | N=128 maxcp 5670.8 vs first 5711.3（仅 +0.7%）；maxcost 更差（5765.3） | 首合格升序（零比较开销）已近最优 |
| 跨 worker 动态（窃取/迁移） | 打破固定 owner | owner-ready 协议语义依赖固定归属（workSteal 存在但禁用） | 大改无证据基础 |

**结论**：前瞻杠杆已结构性耗尽（~12% 上限）；动态化变体合计 ≤1–2%，不构成晋级候选。

---

## 10. 复现要点

- **生成**：v371 T32 配方 + `GSIM_MT_DENSE_LOOKAHEAD=N`（default-off；flag-off 生成与无 knob 输出 byte-identical）。
- **验证**：独立 checker（`check-mt-dense-lookahead.py`，从原始 DAG 重算仅 DAG 归约并核对全部 emitted 组/前置）；NEMU C5000/C50000；100× 确定性；fixed-mask 交错 A/B。
- **窗口变体**：克隆生成模型、改 `SimTop.h` 的 `kDenseLookaheadWindow` 字面量即可做同调度双生（v434 窗口扫描即此法）。
- **详细设计与证明**：`docs/plan-v422-dynamic-scheduling.md`；证据：`profile/v426-lookahead-epoch-hybrid/`。

---

## 11. 经典系统机制适用性裁决

| 经典机制 | gsim-mt 映射 | 结论 |
|---|---|---|
| 分支预测 | 预测 token 就绪 | 硬件 BP 已覆盖（误预测率 0.91–1.20% 且前瞻后更低）；软件预测 token ≈ 前瞻本身。**不适用** |
| 页表/TLB | 大页、地址间接 | dTLB miss 率实测 0.07–0.09%--**实测非问题** |
| 乱序执行（深化） | 全局 OOO/中心就绪队列 | Phase 111/134 已否决：通知开销杀死全局动态调度；worker 内 OOO 即前瞻（已落地）。**不扩展** |
| 投机执行 | 按旧值投机 + 回滚 | 同步 RTL 每拍所有触发器都更新，投机恒错且回滚代价高。**不成立** |
| 计算通信融合 | 等待期重叠通信与计算 | 前瞻本体即此类；延伸候选（预取/提前释放/LPT/重排）全部已否决 |

前瞻（worker 内有界 OOO + 分组 token）是当前证据下唯一 ≥10% 的调度类杠杆。后续性能工作应转向非调度类杠杆。

---

## 相关页面

- [[wiki-scheduling]] - 调度与负载均衡：静态分区 vs 动态调度、任务粒度、关键路径保护
- [[wiki-pointer-order-nondeterminism]] - 指针序非确定性：前瞻战役同期发现的生成器非确定性问题
- [[wiki-verilator-v3variableorder]] - 变量排序与 MTask 亲和性：编译时为并行仿真做准备的布局优化
- [[wiki-V3Order调度顺序]] - V3Order 调度顺序与并行分区：MTask 图的构建与关键路径

## 参考来源

- `<workspace>/gsim-mt-lookahead-algorithm.zh.md` - 有界前瞻完整设计与证明
- `<workspace>/gsim-task-verilator-dual-default4488/candidates.jsonl` - 台账 v422（W1 验证）、v426（N=16 晋级）、v427（N=128 晋级）、v428（Linux 验证）、v429（批量否决）、v434（窗口扫描）、v435（预取否决）

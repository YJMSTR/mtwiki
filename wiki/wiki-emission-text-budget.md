---
id: "wiki-emission-text-budget"
title: "发射文本预算：生成模型体积的归因与削减"
description: "生成代码仿真器的模型体积是构建时间与迭代成本的乘数。一次把 12.4GB 模型压到 1.1GB（-91%）的完整归因链：先逐字节普查（86.8% 是全限定标识符——71M 次出现、平均 153B），再发现求值体被发射了四份（dense 变体 / buffered 变体 / 普通串行 subStep / SerialFast），各自服务不同运行时；削减杠杆按'死文本先砍、活文本再压'排序：运行时门控发射（dense-only codegen）→ 名字 interning（发射期 Node::name 替换 + 已烘焙 InstInfo 字符串的 token 边界重写 + NAME-keyed 重命名映射处理寄存器孪生 + I/O 与黑盒函数名豁免）。配套纪律：census before emit、默认值反转的配方门控与 =0 逃生口、门禁脚本在默认反转后必须显式钉住 =0。"
tags: ["emission", "model-size", "codegen", "census-before-emit", "identifier-bloat", "name-interning", "runtime-gated-emission", "dead-text", "default-flip", "legacy-escape", "byte-identity"]
keywords: ["emitted model size", "identifier bytes census", "qualified identifier bloat", "evaluation body copies", "dense only codegen", "sparse dispatch runtime dead text", "SerialFast fallback", "name interning", "token boundary rewrite", "InstInfo baked strings", "name keyed rename map", "REG DST RESET twins", "IO accessor contract", "blackbox function names", "default on knobs", "escape hatch", "fir gate explicit off"]
last_updated: "2026-08-27"
---

# 发射文本预算：生成模型体积的归因与削减

## 概述

生成代码仿真器的**模型体积**是流水线的隐藏乘数：构建时间、磁盘占用、编译器内存、增量迭代的反馈环全部随它放大。XiangShan 案例中 dense 执行器的模型膨胀到 12.4GB（上游串行版同输入仅 2.5GB，5×），把 -O3 构建推到 25 分钟——"改一个旋钮重编一次"的实验节律直接被杀死。

本页记录把它压到 **1.1GB（-91%）** 的完整方法论，核心是三条纪律的顺序执行：

1. **逐字节普查先于任何优化**（见 [[wiki-value-change-census]] 的同一条纪律）——体积问题的"直觉解释"几乎总是错的；
2. **死文本先砍、活文本再压**——先按运行时可达性分级（哪些发射体是当前部署目标永远不会执行的），再考虑压缩真正执行的文本；
3. **每个削减旋钮默认可回退**——`=0` 必须逐字节还原旧发射，这是冠军链与历史基线的安全网。

---

## 1. 普查：体积到底花在哪

### 1.1 三层普查法

| 层级 | 方法 | 案例结果 |
|---|---|---|
| L1 文本分类 | 正则逐行分类（赋值/声明/激活/同步/函数签名） | **所有类别均匀 ~5×于上游**——不是某类开销，是整体复制 |
| L2 函数普查 | 按函数名（数字归一化）累加字节数 | 90,624 个 `mtTaskN` 函数 vs 8,436 个 MTask ≈ 每个任务体多份副本 |
| L3 字节归因 | 限定标识符（含 `__DOT__` 模式）逐出现累加 | **86.8% 的字节是全限定标识符**（71M 次 × 平均 153B） |

### 1.2 案例归因结论

L1 的"均匀 5×"排除了"砍某类开销"的路线；L2 定位到**求值体被发射了四份**：

| 副本 | 服务运行时 | 在 dense 部署中的状态 |
|---|---|---|
| `mtTaskN(flag)`（45,312 个） | dense 执行器 | 热路径 |
| `mtTaskN(flag, ActivationDelta&)`（45,312 个） | sparse coarse 运行时 | **死文本** |
| 普通串行 `subStepN()` | sparse dispatch 串行回退 | **死文本** |
| `subStepN SerialFast`（253 个文件） | T≤4 快速串行 | 按需保留 |

关键判定工具：**调用面普查**——在已发模型里 grep 每个变体的调用者（buffered 变体的引用全部落在 `mtRunCoarse*WorkerRange`/pure-batch 分片 = sparse 运行时专有）。引用面 + 部署配置 → 死文本判定。

---

## 2. 削减杠杆（按性价比排序）

### 2.1 杠杆一：运行时门控发射（砍死文本）

发射器在 codegen 时**知道**自己服务哪种运行时。dense-only 门控（`GSIM_MT_DENSE_ONLY_CODEGEN`）跳过：

- buffered 变体及其 RepCut 帮手；
- 普通串行 subStep 全套（含内嵌 coarse 分发机制）；
- coarse/pure-batch 运行时、分发表、worker-pool 的 sparse 任务类型；
- `step()` 落体改为明确 `abort()`（带清晰报错信息）。

案例收益：12.4GB → 7.1GB（-42%），emu 215→110MB。**正确性边界**：保留的路径（dense + 需要时的 SerialFast）逐位不变；NEMU 双门精确；5 对 A/B 性能中性。

### 2.2 杠杆二：名字 interning（压活文本）

普查说 86.8% 字节是标识符 → 把长名换成 `v<idx>`。发射期实现的四个不可省细节：

1. **改 `Node::name` 覆盖 ~22 个活发射点，但同时必须重写已烘焙的 `InstInfo.inst` 字符串**——insts 在更早的 pass 里已把名字拼进字符串，只改 Node 不重写 inst，主体文本纹丝不动（这是第一次实现失败的直接原因）。
2. **重命名映射必须 NAME-keyed 而非 Node-keyed**——`REG_DST`/`REG_RESET` 孪生节点与 `REG_SRC` 共享同一名字字符串，指针 key 会漏改一半（第二次失败的编译错误来源）。
3. **I/O 成员与黑盒函数名豁免**——`set_/get_` 访问器拼写是 harness 契约（difftest gsim.h 按名调用）；extmodule 黑盒函数名在 `computeExtMod` 里烘焙于 InstInfo 之外，改成 `_v52` 会出现"未声明函数"。
4. **可调试性**：声明行保留 `// orig=<fullName>` 注释，映射不丢失。

重写算法用 **token 边界替换**（复用 RepCut 替换器的判定：`[A-Za-z0-9_$]` 边界 + 最长名优先），杜绝 `_reg` 误吃 `_reg_3`。

案例收益：叠加后 4.8GB → 1.1GB；`__DOT__` 残留恰好等于 I/O 访问器集合（25 个）。

### 2.3 杠杆三（独立）：巨型函数分块

见 [[wiki-compiler-frontend]]——重置体是百万语句单函数，前端超线性。这是**构建时间**杠杆而非体积杠杆，但同属发射期文本整形。

---

## 3. 默认值反转的纪律

正确性已验证（NEMU 位精确 + 性能中性）的削减旋钮，在性能交付分支上应当默认开。反转有三条配套：

1. **配方门控**：默认开只在"dense 配方"下生效（`--mt-helper-mode=mt-level-dispatch` + executor codegen）；配方外的生成路径（上游风格）默认保持旧行为，避免无谓破坏。
2. **`=0` 逃生口**：显式置 0 逐字节还原旧发射——恒等性用 FIR 门验证（22/22）。
3. **门禁脚本必须跟着改**：原来"不设环境变量 = 关"的门禁，反转后变成"不设 = 开"，两侧输出**按设计**不同 → 门禁失效或全红。修法：门禁脚本显式导出三个 `=0` 再比较。**这不是小事**：同一个 FIR 门在本次战役里刚抓住过一次误删 `else if` 分支的真实回归，它失效等于安全网没了。

---

## 4. 检查清单

- [ ] 体积问题先跑三层普查（行分类 → 函数普查 → 字节归因），不接受"应该是 XXX"的解释
- [ ] 每个求值体副本问一句：它的引用面是谁？部署配置会不会走到？
- [ ] 发射期改名字：活点 + 烘焙 inst 字符串**两处都要**，映射 NAME-keyed，I/O 与黑盒豁免
- [ ] 每个旋钮独立提交，默认关验证字节恒等，再单独提交默认反转
- [ ] 反转后立刻审计所有依赖旧默认的脚本（门禁/配方/文档），显式钉住语义

## 相关页面

- [[wiki-value-change-census]] — "census before emit" 纪律的运行时孪生
- [[wiki-compiler-frontend]] — 巨型函数分块与前端超线性
- [[wiki-generator-speed]] — 生成器自身的速度工程与确定性门禁
- [[wiki-reproducibility-and-config]] — 默认值、逃生口与可复现性

# 多线程 RTL 仿真器优化知识 Wiki

> 为将高度优化的单线程稀疏计算 RTL 仿真器改造为多线程并行（16 线程下 >2x 加速比）而构建的知识库。

## 架构

```
wiki-mt-rtl-optimizer/
├── sources/          # 原始数据：GitHub PR、博客、文档、比赛资料的不可变总结
├── wiki/             # 合成知识页面：YAML frontmatter + 正文，按 id 交叉引用
├── queries/          # 自动生成的交叉引用索引（勿手动编辑）
│   └── by-tag/
│   └── by-source/
│   └── by-keyword/
├── scripts/
│   └── generate-indices.py   # 索引生成脚本
└── README.md
```

## 三层模型

| 层级 | 目录 | 说明 | 编辑方式 |
|------|------|------|----------|
| L1 Sources | `sources/` | 原始资料的不可变摘要 | 手动添加新资料 |
| L2 Wiki | `wiki/` | 合成知识页面，带 YAML frontmatter | 手动编写 + 引用 sources |
| L3 Indices | `queries/` | 自动生成的交叉引用 | `python scripts/generate-indices.py` |

## 快速开始

```bash
# 生成所有索引
python scripts/generate-indices.py

# 搜索知识
python scripts/generate-indices.py --search "lock-free"
python scripts/generate-indices.py --search "cache coherency"
```

## 添加新资料

1. 在 `sources/` 下新建 Markdown 文件（见 `sources/_template.md`）
2. 在 `wiki/` 下编写合成知识页面，YAML frontmatter 中引用 source id
3. 运行 `python scripts/generate-indices.py` 更新索引

## 动态更新原则

- `sources/` 中的文件一旦创建，内容**不可变**（只追加新文件）
- `wiki/` 中的页面可以迭代更新，但保留版本历史
- `queries/` 完全自动生成，从不手动编辑

## 核心关注领域

1. **多线程 RTL 仿真** — Verilator、Icarus、Commercial 仿真器的并行化策略
2. **稀疏计算并行化** — 事件驱动、动态调度、数据局部性
3. **高性能 C++ 多线程** — Lock-free、Thread-local、Memory model、False sharing
4. **并行离散事件仿真（PDES）** — Time Warp、保守同步、乐观同步
5. **HPC 优化技术** — Cache locality、NUMA、SIMD、Prefetching
6. **真实项目参考** — GitHub 上的高性能并行项目 PR/Issue/代码


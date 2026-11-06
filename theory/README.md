# Theory · 深度解析

这个目录放**长篇、按主题组织的技术解析**：不是论文摘要，也不是链接表，而是
“问题设定 → 表示 → 架构 → 损失 → 下游 → 实验 → 复现 → 失败模式 → 与后续工作的关系”的完整拆解。

与 [`notes/`](../notes/README.md) 的分工：

| 目录 | 形态 | 适合 |
|---|---|---|
| `theory/` | 长篇可读解析，面向理解/面试/选型 | 一个方法族、一个核心范式 |
| `notes/` | 短篇论文笔记，模板化、证据优先 | 单篇论文的数字核对、复现记录 |

## 目录

| 文章 | 主题 | 状态 | 核查日期 |
|---|---|---|---|
| [DUSt3R 深度解析](3r/dust3r_dissection.md) | pointmap 回归、全局对齐、无约束 3D 重建 | verified | 2026-11-06 |
| [MASt3R 深度解析](3r/mast3r_dissection.md) | 3D grounded matching、metric pointmaps、快速互惠匹配 | verified | 2026-11-06 |
| [VGGT 深度解析](3r/vggt_dissection.md) | 多视图一次前向、相机/深度/点图/跟踪 | verified | 2026-11-06 |
| [GLUEMAP 深度解析](slam/gluemap_dissection.md) | 全局 SfM、前馈星图推理、运动平均、增强 BA | verified | 2026-11-06 |
| [VidMap 深度解析](slam/vidmap_dissection.md) | 视频 SfM、时序 track、provenance-aware 优化、metric depth 先验 | verified | 2026-11-06 |

## 写作约定

- 每个数字必须能在论文表格/代码中找到，并在文末“来源与核查”中列出。
- 预印本、会议版、代码版的结果分开写；不混用协议。
- 作者声称与作者判断分开写；失败模式要标明是论文承认的还是后续工作观察到的。
- 架构图优先用 ASCII，保证 GitHub/终端可读。
- 公式用 LaTeX（`$...$` / `$$...$$`），代码引用带文件路径和行号。
- 新增文章后，在 `README.md`、`AGENTS.md` 和本表里登记。

## 固定模板与自动化

所有新文章必须从 [`_template.md`](_template.md) 生成，文件名统一为
`theory/<section>/<slug>_dissection.md`。

- **建骨架**：`python3 scripts/new_dissection.py --title ... --arxiv ... --section 3r --slug ...`
- **格式审计**：`python3 scripts/audit_theory.py`（缺章节、缺 source marker、残留 TODO 都会失败）
- **自动化 skill**：[`.claude/skills/paper-dissection/SKILL.md`](../.claude/skills/paper-dissection/SKILL.md)

固定章节（缺一不可）：

```text
快速判断 → X-Ray 开场 → 研究全景时间线 → 1 架构总览（1.1/1.2/1.3）
→ 2 数学核心（Napkin Formula）→ 3 玩具例子 → 4 工程视角
→ 5 数据与评测（5.1/5.2/5.3）→ 6 能力与失败模式（6.1 隐含假设）
→ 7 相关工作对比 → 8 精读建议 → 9 Q&A → 10 复现清单 → 11 来源与核查
```

**写作铁律**：每个数字必须有出处；论文没报告就写“论文未报告”，自己的估算标
`UNVERIFIED`；不编造数据集名、指标、repo、issue 或 commit。

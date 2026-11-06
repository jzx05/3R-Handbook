# AGENTS.md

本文件面向在本仓库中工作的自动化 agent（Claude Code / Codex / Cursor / CI bot），
说明哪些文件可以改、哪些只能由 pipeline 生成，以及撰写深度笔记时必须遵守的证据规则。

## 目标

- 维护一个**可追溯**的 3R / 前馈重建 / SLAM 论文手册。
- 自动层负责“全、快、可复查”；人工层负责“深、准、有边界”。
- 任何数字、结论和版本差异都必须能回到论文、代码或官方页面。

## 仓库地图

| 路径 | 性质 | 说明 |
|---|---|---|
| `data/papers.json` | ⚙️ 自动生成 | 规范化论文库，唯一事实源 |
| `data/papers.jsonl` | ⚙️ 自动生成 | 每行一篇，便于 diff / grep |
| `data/upstream/README.md` | ⚙️ 自动生成 | 上游原始快照 |
| `data/arxiv-cache.json` | ⚙️ 自动生成 | arXiv 元数据缓存 |
| `data/sync-log.jsonl` | ⚙️ 自动生成 | 每次同步的审计日志 |
| `data/supplements/papers.json` | ✍️ 人工 | 上游没有、但手册需要保留的条目 |
| `papers/*.md` | ⚙️ 自动生成 | 分类索引、已移除条目 |
| `cheat-sheet/timeline.md` | ⚙️ 自动生成 | 年份分布 |
| `cheat-sheet/venue-stats.md` | ⚙️ 自动生成 | 会议分布 |
| `reports/daily/*` | ⚙️ 自动生成 | 每日新增 / 更新 / 移除 |
| `README.md` 的 `AUTO:*` 区块 | ⚙️ 自动生成 | 统计、分类表、最近新增 |
| `book/`、`theory/`、`notes/`、`cheat-sheet/glossary.md`、`docs/` | ✍️ 人工 | 深度内容 |
| `scripts/` | ✍️ 人工 | pipeline 代码，改动需带测试 |

自动生成文件带有 `<!-- AUTO-GENERATED ... -->` 头。**不要手改**，下一次同步会覆盖。

## 自动层写入协议

1. 只允许 `scripts/sync_upstream.py` 写 `data/papers.json`、`data/papers.jsonl`、
   `data/upstream/*`、`data/arxiv-cache.json`、`data/sync-log.jsonl`。
2. 只允许 `scripts/build_pages.py` 写 `papers/*.md`、`cheat-sheet/timeline.md`、
   `cheat-sheet/venue-stats.md`、`reports/daily/*`、README 的 `AUTO:*` 区块、`CHANGELOG.md`
   的自动条目。
3. 上游抓取失败、解析结果为 0、或条目数较上次骤降 >50% 时，pipeline 必须**拒绝更新**，
   由人判断是否传入 `--allow-mass-removal`。
4. 自动提交只包含上述文件；不要顺手 `git add -A` 把人工草稿带进去。

## 人工层写作规范

### 深度笔记

复制 `notes/_template.md`。每篇笔记必须包含七节：

1. **一句话结论** — 它到底解决了什么，不写营销句。
2. **问题设定** — 输入、输出、假设、与相邻工作的差别。
3. **方法核心** — 关键模块、损失、训练/推理数据流。
4. **关键数字** — 必须来自论文原文；写清数据集、指标、协议和对照。
5. **适用边界 / 失败模式** — 什么条件下不成立；作者承认的局限与你的观察分开写。
6. **复现要点** — 入口脚本、权重、显存/延迟、常见坑。
7. **来源与核查** — 论文链接、代码 commit、项目页、核查日期。

### 证据规则

- **每个数字都要能在来源中找到**。找不到就写“未核实”，不要估算。
- 预印本、会议版、代码版可能不同；写清版本，不要混用结果。
- 引用二手博客时，标为二手来源，并尽量回到一手论文/代码。
- 不把“作者声称”改写成“事实”；保留 `声称 / 在 X 设置下` 这类限定。
- 不伪造实验、链接、作者、会议或日期。

### 添加人工条目

编辑 `data/supplements/papers.json`：

```json
{
  "title": "Paper Title",
  "venue": "ECCV 2026",
  "year": 2026,
  "section": "SLAM",
  "links": {
    "paper": "https://arxiv.org/abs/2607.27194",
    "code": "https://github.com/org/repo"
  },
  "arxiv_id": "2607.27194"
}
```

- `title` 必填；与上游标题规范化后相同则以上游为准。
- `section` 使用上游的六个分类名之一，或新增分类（会自动生成页面）。
- 条目会被标记 `source=manual`，不会因上游删除而消失。

## 论文解析（theory/）

- **唯一模板**：[`theory/_template.md`](theory/_template.md)。
- **命名**：`theory/<section>/<slug>_dissection.md`。
- **建骨架**：`python3 scripts/new_dissection.py --title ... --arxiv ... --section ... --slug ...`。
- **格式审计**：`python3 scripts/audit_theory.py`；缺章节、缺 `<!-- source: ... -->`、残留
  `TODO` 都会失败。
- **自动化 skill**：[`.claude/skills/paper-dissection/SKILL.md`](.claude/skills/paper-dissection/SKILL.md)。

固定 11 节：快速判断 / X-Ray / 研究全景时间线 / 1 架构总览 / 2 数学核心 / 3 玩具例子 /
4 工程视角 / 5 数据与评测 / 6 能力与失败模式 / 7 相关工作对比 / 8 精读建议 /
9 Q&A / 10 复现清单 / 11 来源与核查。

写作铁律：

- 每个数字必须能在论文全文、表格或官方代码中找到；找不到就写“论文未报告”。
- 自己的估算必须标 `UNVERIFIED` 并写清假设。
- 不编造数据集名、benchmark、指标、repo、issue、commit 或项目页。
- 预印本 / 会议版 / 代码版的结果分开写。
- 作者声称与作者判断分开写。

## 修改 pipeline

改动 `scripts/` 后必须运行：

```bash
python3 -m unittest discover -s scripts -p 'test_*.py' -v
python3 scripts/sync_upstream.py --dry-run
python3 scripts/audit.py --strict
```

如果改动了解析规则，补一个 `scripts/test_sync.py` 用例，覆盖脏数据形态
（缺括号、空链接、`Paper-todo`、标题含逗号、重复标题）。

## 禁止事项

- ❌ 手改自动生成文件或 README 的 `AUTO:*` 区块。
- ❌ 用模型“补全”论文摘要、作者、会议或数字。
- ❌ 把未核实的项目页/代码链接写成官方链接。
- ❌ 在自动提交里夹带人工笔记或无关文件。
- ❌ 删除 `data/sync-log.jsonl` 或 `reports/daily/` 的历史记录。

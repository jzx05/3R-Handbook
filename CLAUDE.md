# CLAUDE.md

本仓库的完整维护规范见 [AGENTS.md](AGENTS.md)。下面是 Claude Code 在这个仓库工作时的最短约定。

## 常用命令

```bash
python3 scripts/sync_upstream.py           # 抓取 + 解析 + arXiv 富化 + 重建页面
python3 scripts/sync_upstream.py --offline # 不联网，使用 data/upstream/README.md
python3 scripts/sync_upstream.py --dry-run # 只预览
python3 scripts/build_pages.py             # 从 data/papers.json 重建页面
python3 scripts/audit.py --strict          # 结构审计
python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

## 不可违反的规则

1. `data/papers.json`、`data/papers.jsonl`、`papers/*.md`、`cheat-sheet/timeline.md`、
   `cheat-sheet/venue-stats.md`、`reports/daily/*`、README 的 `AUTO:*` 区块都是自动生成的，
   **不要手改**；要改内容就改上游解析逻辑或 `data/supplements/papers.json`。
2. 人工补充条目写 `data/supplements/papers.json`。
3. 深度笔记写 `notes/`，使用 `notes/_template.md`；每个数字必须能在原文找到。
4. 改动 `scripts/` 必须补/跑测试与审计。
5. 自动提交只包含 pipeline 产物；不要 `git add -A` 夹带草稿。

## 结构速览

- `scripts/sync_upstream.py` — 抓取、解析、合并、调用富化与构建
- `scripts/enrich_arxiv.py` — arXiv 元数据（作者/摘要/日期）
- `scripts/build_pages.py` — 生成所有 Markdown 页面
- `scripts/audit.py` — 结构与链接检查
- `config/sources.json` — 上游源配置
- `data/supplements/papers.json` — 人工补充
- `book/`、`theory/`、`notes/` — 人工内容

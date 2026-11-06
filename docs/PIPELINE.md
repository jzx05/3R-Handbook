# Pipeline 文档

## 一句话

```text
上游 README → 快照 → 解析 → 合并历史 → arXiv 富化 → 生成页面 → 有变化才提交
```

## 数据流

| 阶段 | 脚本 | 产物 | 是否联网 |
|---|---|---|---|
| 抓取 | `scripts/sync_upstream.py` | `data/upstream/README.md`、`data/upstream/state.json` | 是 |
| 解析 | 同上 | 内存中的条目列表 | 否 |
| 合并 | 同上 | `data/papers.json`、`data/papers.jsonl` | 否 |
| 富化 | `scripts/enrich_arxiv.py` | `data/arxiv-cache.json`、补全的元数据 | 是（arXiv API） |
| 生成 | `scripts/build_pages.py` | `papers/`、`cheat-sheet/`、`reports/`、README 区块 | 否 |
| 审计 | `scripts/audit.py` | 终端报告（可选链接检查） | 可选 |

## 上游解析

上游条目的标准形态：

```markdown
- DUSt3R: Geometric 3D Vision Made Easy, *CVPR 2024*. [[Paper](https://...)] [[Code](https://...)] [[Website](https://...)]
```

解析器做了这些容错：

- 链接缺右括号：`[[Website](url) [[Code](url)]`
- 空链接：`[[Paper]()]`
- 占位文本：`Paper-todo`
- 会议字段里多写年份：`*CVPR Finding 2026 2026*`
- 同一标题重复出现：合并链接，保留第一条的分类

标题规范化后做 SHA-1，取前 10 位作为稳定 ID。**标题变化 = 旧条目移除 + 新条目新增**，
这是有意为之：不要在标题不变的情况下改 ID。

## 合并与历史

- `first_seen` 在首次出现时写入，之后保持不变。
- 上游不再出现的条目不会删除，而是 `status=removed` + `removed_at`，
  进入 `papers/removed.md`，不计入分类统计。
- 人工补充条目（`data/supplements/papers.json`）标记 `source=manual`，
  上游删除不会影响它们。
- 上游条目数较上次活跃数下降 >50% 时，脚本默认拒绝更新。

## 富化

- 从任意链接中提取 arXiv ID：`arxiv.org/abs/<id>` 或 `arxiv.org/pdf/<id>`。
- 每 20 个 ID 一批调用 `export.arxiv.org/api/query`，批次之间 sleep 3 秒。
- 缓存按 arXiv ID 去重；同一论文的预印本/会议版只请求一次。
- 网络失败不阻塞同步；条目标记 `enrichment=pending`，下次重试。
- 摘要截断到 2000 字符，仅用于检索与日报预览。

## 生成规则

- 分类页按年份降序、标题升序排列。
- `cheat-sheet/timeline.md` 只统计有年份标注的活跃条目。
- `cheat-sheet/venue-stats.md` 去掉年份后统计会议/期刊。
- `reports/daily/YYYY-MM-DD.md` 同一天多次运行会合并到一份报告，原始运行记录在
  `reports/daily/YYYY-MM-DD.json`。
- README 的 `AUTO:STATS` / `AUTO:SECTIONS` / `AUTO:RECENT` 区块由脚本替换。
- `CHANGELOG.md` 只在有新增/更新/移除时追加。

## GitHub Actions

### `sync-upstream.yml`

- 计划：`17 */2 * * *`（每 2 小时的第 17 分钟，UTC）。
- 手动：Actions → Sync upstream → Run workflow。
- 权限：`contents: write`、`issues: write`。
- 流程：checkout → Python 3.11 → sync → audit → test → 有 diff 才 commit/push。
- 失败时创建/追加 `[pipeline-alert]` issue；恢复后自动关闭。

### `audit.yml`

- 触发：push / PR 到 `main`。
- 运行解析测试和 `audit.py --strict`，不联网。

## 添加第二个上游

在 `config/sources.json` 的 `sources` 数组里追加：

```json
{
  "id": "awesome-dust3r",
  "name": "ruili3/awesome-dust3r",
  "repo": "ruili3/awesome-dust3r",
  "branch": "main",
  "readme_url": "https://raw.githubusercontent.com/ruili3/awesome-dust3r/main/README.md",
  "enabled": true
}
```

当前 `sync_upstream.py` 只读取第一个 enabled 源。要合并多个源，需要在
`main()` 里循环抓取/解析，并按标题做二次去重；建议先把第二个源的标题格式跑一遍
`--dry-run` 再改代码。

## 本地调试

```bash
# 用缓存快照解析，完全不联网
python3 scripts/sync_upstream.py --offline --no-enrich --dry-run

# 强制重建页面（上游没变也执行）
python3 scripts/sync_upstream.py --force --no-enrich

# 只验证链接（较慢，8 线程）
python3 scripts/audit.py --check-links
```

## 已知限制

- GitHub Actions 的 cron 是尽力而为，可能延迟几分钟到几十分钟。
- arXiv API 可能限流；失败会保留 `pending`，不影响主流程。
- 上游没有稳定的 schema，解析器只能覆盖当前观察到的格式；新增格式需要补测试。
- 标题哈希对“只改标点/大小写”的编辑不敏感（规范化后相同），但对改词敏感。
- 上游 README 未声明许可证，本仓库只保存元数据并注明来源，不复制正文。

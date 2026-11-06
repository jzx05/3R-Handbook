# 数据目录

| 文件 | 维护 | 说明 |
|---|---|---|
| `papers.json` | ⚙️ 自动 | 唯一事实源。schema_version=1，包含 `source`、`sections`、`counts`、`papers` |
| `papers.jsonl` | ⚙️ 自动 | 每行一篇，便于 `grep` / `jq` / diff |
| `stats.json` | ⚙️ 自动 | 派生统计，供徽章或外部工具读取 |
| `last-run.json` | ⚙️ 自动 | 最近一次同步的摘要（模式、新增/更新/移除 ID） |
| `sync-log.jsonl` | ⚙️ 自动 | 追加式同步日志 |
| `arxiv-cache.json` | ⚙️ 自动 | 按 arXiv ID 缓存的作者/摘要/日期 |
| `upstream/README.md` | ⚙️ 自动 | 上游原始快照，离线模式使用 |
| `upstream/state.json` | ⚙️ 自动 | ETag + SHA-256，用于判断是否变化 |
| `supplements/papers.json` | ✍️ 人工 | 上游没有、但需要保留的条目 |

## paper 对象字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 标题规范化后的稳定哈希，`p-` 前缀 |
| `title` | string | 论文标题 |
| `venue` | string | 会议/期刊/预印本标注，如 `CVPR 2025` |
| `year` | int/null | 从 venue 提取的最后一个个年份 |
| `section` | string | 上游分类名 |
| `slug` | string | 分类页文件名 |
| `links` | object | `paper` / `code` / `website` / `project` / `demo` / `dataset` |
| `arxiv_id` | string | 从链接提取的 arXiv ID，可为空 |
| `order` | int | 上游顺序，用于稳定排序 |
| `first_seen` | date | 首次进入目录的日期 |
| `status` | string | `active` / `removed` |
| `removed_at` | date | 仅 removed 条目 |
| `manual` | bool | 是否来自人工补充 |
| `source` | string | 上游 repo 或 `manual`（仅人工条目显式写入） |
| `authors` | list | arXiv 富化结果 |
| `abstract` | string | arXiv 摘要（截断 2000 字符） |
| `published` | date | arXiv 首次提交日期 |
| `categories` | list | arXiv 分类 |
| `enrichment` | string | `ok` / `pending` / `no-arxiv` |

## 手工编辑

不要直接改 `papers.json`。要加条目，改 `supplements/papers.json`；
要改解析规则，改 `scripts/sync_upstream.py` 并补测试。

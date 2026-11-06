# Scripts

| 脚本 | 作用 |
|---|---|
| `sync_upstream.py` | 抓取上游 README → 解析 → 合并历史 → arXiv 富化 → 重建页面 |
| `enrich_arxiv.py` | 单独运行 arXiv 元数据补全 |
| `build_pages.py` | 从 `data/papers.json` 重建所有生成页面 |
| `audit.py` | 结构审计；`--check-links` 检查链接 |
| `audit_theory.py` | 论文解析格式审计（固定章节 / source marker / TODO） |
| `new_dissection.py` | 从 `theory/_template.md` 生成论文解析骨架 |
| `test_sync.py` | 解析/合并逻辑的回归测试 |
| `run_sync.sh` | 本地一键同步 + 审计 |
| `common.py` | 共享常量与工具 |

## 常用命令

```bash
python3 scripts/sync_upstream.py
python3 scripts/sync_upstream.py --offline --no-enrich
python3 scripts/sync_upstream.py --dry-run
python3 scripts/sync_upstream.py --force
python3 scripts/enrich_arxiv.py --limit 50
python3 scripts/build_pages.py
python3 scripts/audit.py --strict
python3 scripts/audit.py --check-links
python3 -m unittest discover -s scripts -p 'test_*.py' -v
./scripts/run_sync.sh
```

## sync_upstream.py 选项

| 选项 | 作用 |
|---|---|
| `--offline` | 使用 `data/upstream/README.md`，不联网 |
| `--dry-run` | 只解析和打印摘要，不写文件 |
| `--force` | 上游哈希未变也重建页面 |
| `--no-enrich` | 跳过 arXiv 请求 |
| `--limit-enrich N` | 本次最多补全 N 个 arXiv ID（默认 200） |
| `--allow-mass-removal` | 允许活跃条目减少超过 50% |
| `--config PATH` | 使用其他源配置 |

## 退出码

- `0`：成功 / 无变化
- `1`：抓取失败、解析为 0、条目骤降、或审计发现结构错误

## 新增上游源

编辑 `config/sources.json`。当前实现只读第一个 `enabled=true` 的源；
合并多个源需要改 `main()` 并补去重测试，详见 `docs/PIPELINE.md`。

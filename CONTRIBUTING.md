# Contributing

欢迎补充论文、修正链接、撰写深度笔记或改进 pipeline。

## 三种贡献方式

### 1. 补充上游没有的论文

编辑 `data/supplements/papers.json`，添加一个对象：

```json
{
  "title": "Paper Title",
  "venue": "CVPR 2026",
  "year": 2026,
  "section": "SLAM",
  "links": {
    "paper": "https://arxiv.org/abs/XXXX.XXXXX",
    "code": "https://github.com/org/repo"
  },
  "arxiv_id": "XXXX.XXXXX"
}
```

要求：标题与官方一致；至少有一个可验证链接；`section` 尽量复用现有分类。

### 2. 写深度笔记

复制 `notes/_template.md` 到 `notes/<short-name>.md`，按七节模板填写。硬性要求：

- 每个数字都能在论文/代码/官方页面找到，并附链接。
- 预印本与会议版结果分开写。
- 作者声称与你的判断分开写。
- 最后写核查日期。

### 3. 写论文解析（theory/）

长篇解析统一使用固定模板，不要手工复制：

```bash
python3 scripts/new_dissection.py \
  --title "English Paper Title" \
  --title-zh "中文标题" \
  --arxiv 2401.00000 \
  --venue "CVPR 2025" \
  --section 3r \
  --slug short-name \
  --code https://github.com/org/repo \
  --topic "一句话主题"

# 填完后
python3 scripts/audit_theory.py
```

硬性要求：

- 文件名 `<slug>_dissection.md`，位于 `theory/<section>/`。
- 必须保留模板的 11 个固定章节和 `<!-- source: ... -->` marker。
- 每个数字有出处；论文没报告就写“论文未报告”，自己的估算标 `UNVERIFIED`。
- 不编造数据集/指标/repo/issue；预印本与会议版分开写。
- 在 `theory/README.md` 登记并更新状态（draft / verified / reproduced）。

### 4. 改 pipeline

改 `scripts/` 后请运行：

```bash
python3 -m unittest discover -s scripts -p 'test_*.py' -v
python3 scripts/sync_upstream.py --dry-run
python3 scripts/audit.py --strict
```

解析规则的改动要补测试用例，覆盖脏数据（缺括号、空链接、`Paper-todo`、重复标题）。

## PR 检查清单

- [ ] 没有手改自动生成文件（`data/papers.json`、`papers/*.md`、`cheat-sheet/timeline.md`、
      `cheat-sheet/venue-stats.md`、`reports/daily/*`、README 的 `AUTO:*` 区块）。
- [ ] 新增链接可访问，且指向论文/代码/官方项目页。
- [ ] 数字有出处；没有“大概是”“约”这类无法核实的表述。
- [ ] 本地跑了测试和 `audit.py --strict`。
- [ ] 没有把个人草稿、密钥、大文件带进提交。

## 不接受的内容

- 编造的作者、会议、指标、链接或实验结果。
- 纯营销、无法验证的“SOTA”宣称。
- 与 3D 几何 / 前馈重建 / SLAM 无关的批量灌水条目。
- 直接复制受版权保护的论文正文或大段博客内容。

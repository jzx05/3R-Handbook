---
name: paper-dissection
description: Write or update a 3R Handbook paper dissection using the fixed AeroAct-style template. Use when the user asks to 解析/dissect a paper, add a theory article, or update an existing dissection in theory/.
---

# Paper Dissection Skill

本 skill 把一篇论文写成 **“可面试复述、可工程落地、可快速定位”** 的结构化中文解析。
唯一模板是 `theory/_template.md`；唯一命名是 `theory/<section>/<slug>_dissection.md`。
格式审计是 `scripts/audit_theory.py`，不通过就不算完成。

## 何时使用

- 用户说“解析这篇论文”“写个 dissection”“加到 theory/”。
- 用户给了一个 arXiv 链接、PDF、项目页或代码仓库，要求深入分析。
- 要更新已有 `*_dissection.md` 的某个章节（保持结构不变）。

## 铁律（违反 = 重写）

1. **反捏造是第一原则**。每个数字必须能在论文全文、表格、官方代码或官方页面找到。
2. **§4 工程视角**：论文没给延迟/显存/FPS/吞吐/硬件型号，就写 `论文未报告`；
   自己的估算必须标 `UNVERIFIED` 并写清假设。绝不凭空填一个数字。
3. **§5 数据与评测**：数据集名、benchmark 名、指标数字必须逐字来自全文；
   不要把论文的数据集替换成你以为常见的名字；不确定就写 `论文未报告`。
4. **§7 相关工作**：只写论文/官方 repo 里真实存在的对比；不要编造 issue 编号、
   commit hash、项目页或“SOTA 提升 X%”。
5. **预印本 / 会议版 / 代码版**的结果分开写；不要混用协议。
6. **作者声称**与**你的判断**分开写；失败模式要标明是论文承认的还是后续工作观察到的。
7. 玩具例子的数字可以自造，但必须明确写“玩具设定”；工程数字不能自造。

## 工作流

### 1. 收集来源

- 论文：arXiv abstract / HTML / PDF（优先 HTML 表格；PDF 用 `pdftotext`）。
- 代码：官方 repo 的 README、模型定义、损失、推理入口、issue（可选）。
- 项目页：只用于补充可视化/演示，不当作技术事实来源。
- 如果论文没有官方 repo，`**代码**` 写“无”，不要编造链接。

### 2. 建骨架

```bash
python3 scripts/new_dissection.py \
  --title "English Paper Title" \
  --title-zh "中文标题" \
  --arxiv 2401.00000 \
  --venue "CVPR 2025" \
  --section 3r \
  --slug short-name \
  --code https://github.com/org/repo \
  --project https://project.page \
  --topic "一句话主题" \
  --positioning "一句话核心定位"
```

- `section` 用现有分类目录（`3r` / `slam` / `calibration` / `loop-closure` / `downstream`），
  或新建一个安全的目录名。
- 脚本会自动：
  - 从 `theory/_template.md` 复制；
  - 填标题、日期、论文/代码/项目链接、source marker；
  - 在 `theory/README.md` 插入一行（状态 `draft`）。
- 不要手工复制模板，避免漏掉固定章节。

### 3. 逐节填写

严格保留模板的章节标题（审计按标题匹配）：

1. 标题 + 元信息块（论文/链接/代码/核心定位）。
2. `## ⚡ 快速判断`：5 行表格（核心结论 / 适合精读 / 可以跳过 / 落地可行性 / 主要风险）。
3. `💡 X-Ray 开场`：2-3 句。
4. `📍 研究全景时间线`：ASCII 时间轴 + 本文位置 + 局限。
5. `## 1. 核心架构/方法总览`：
   - `### 1.1 系统对比概览`：组件 / 输入 / 输出 / 训练-推理差异。
   - `### 1.2 关键机制`：3-5 条；最后写 `⚡ Eureka Moment`。
   - `### 1.3 信息流/架构图`：ASCII 训练 + 推理图。
6. `## 2. 数学核心`：`📌 Napkin Formula` → 目标 → 变量说明 → 直觉。
7. `## 3. 带数字走一遍`：输入尺寸/token 数/输出形状/关键数字。
8. `## 4. 工程视角`：规模/延迟/显存/训练成本/许可 + 部署约束 + 代码地图。
9. `## 5. 数据与评测`：5.1 数据组成、5.2 评测设置、5.3 关键结果。
10. `## 6. 能力与失败模式`：能做什么 / 不能做什么 / 6.1 隐含假设。
11. `## 7. 与相关工作对比`：对比表 + 面试 Tip。
12. `## 8. 精读建议`：谁该读 / 章节路径 / 谁不必读。
13. `## 9. 补充：面试高频 Q&A`：至少 5 问。
14. `## 10. 补充：复现清单`：最小命令、默认值、常见坑。
15. `## 11. 补充：来源与核查`：每个数字的来源表 + 未核实项。

### 4. 校验

```bash
python3 scripts/audit_theory.py          # 严格：不能有 TODO
python3 scripts/audit.py --strict
python3 -m unittest discover -s scripts -p 'test_*.py'
```

- 草稿阶段可以 `python3 scripts/audit_theory.py --allow-todo`，但提交前必须清掉 TODO。
- 本地链接检查：确保 `[← Back to Theory](../README.md)` 和论文/代码链接可达。

### 5. 更新索引与状态

- `theory/README.md` 的行状态从 `draft` 改为 `verified`（数字已回原文核对）
  或 `reproduced`（跑过代码/权重）。
- 如新增分类目录，更新 `theory/README.md` 的目录说明。
- 如果文章被引用到 `book/` 或根 `README.md`，同步链接。

### 6. 提交

```bash
git add theory/ scripts/ .claude/skills/paper-dissection/
git commit -m "docs(theory): add <paper> dissection"
```

提交信息末尾加：

```
Co-Authored-By: Claude Code <noreply@anthropic.com>
```

## 质量检查清单

- [ ] 文件名是 `<slug>_dissection.md`，位于 `theory/<section>/`。
- [ ] 第一行是 `# 中文标题 (English Title)`。
- [ ] 有 `<!-- source: https://arxiv.org/abs/XXXX.XXXXX -->`。
- [ ] 11 个固定章节 + 所有必需小节都在。
- [ ] 没有 `TODO`（提交前）。
- [ ] §4/§5 的数字有出处；没有出处就写 `论文未报告`。
- [ ] §6 有“隐含假设”子节。
- [ ] §7 有面试 Tip。
- [ ] §11 有来源核查表。
- [ ] `theory/README.md` 有条目。
- [ ] `python3 scripts/audit_theory.py` 通过。

## 常见错误

- **把模板占位符留在正文**：审计会失败；清掉所有 TODO。
- **编造 dataset 名字**：论文用 N3V，你写成 KITTI，是最常见的硬伤。
- **把预印本数字当会议版**：写清版本。
- **把“作者声称”写成“事实”**：保留限定词。
- **只写摘要**：本模板要求架构、数学、数字、工程、失败模式五件套。
- **没有代码就编 repo**：`**代码**: 无` 是合法答案。

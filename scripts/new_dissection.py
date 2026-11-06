#!/usr/bin/env python3
"""Scaffold a new paper dissection from theory/_template.md.

Example:
    python3 scripts/new_dissection.py \
      --title "DUSt3R: Geometric 3D Vision Made Easy" \
      --title-zh "DUSt3R: 几何 3D 视觉变得简单" \
      --arxiv 2312.14132 \
      --section 3r --slug dust3r \
      --code https://github.com/naver/dust3r \
      --topic "pointmap 回归、全局对齐、无约束 3D 重建"

After scaffolding, fill the TODOs, then run:
    python3 scripts/audit_theory.py
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, utc_today  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a new theory dissection from the template.")
    parser.add_argument("--title", required=True, help="English paper title")
    parser.add_argument("--title-zh", default="", help="Chinese title (optional)")
    parser.add_argument("--arxiv", required=True, help="arXiv id, e.g. 2312.14132")
    parser.add_argument("--venue", default="", help="venue/year, e.g. 'CVPR 2024'")
    parser.add_argument("--section", required=True, help="theory subdirectory, e.g. 3r")
    parser.add_argument("--slug", required=True, help="file slug, e.g. dust3r")
    parser.add_argument("--code", default="", help="official code URL")
    parser.add_argument("--project", default="", help="project page URL")
    parser.add_argument("--topic", default="", help="one-line topic for theory/README.md")
    parser.add_argument("--positioning", default="", help="one-line core positioning")
    parser.add_argument("--date", default=utc_today())
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-index", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = Path(args.root)
    arxiv = args.arxiv.strip()
    if not re.fullmatch(r"\d{4}\.\d{4,5}", arxiv):
        print(f"error: invalid arXiv id: {arxiv!r}", file=sys.stderr)
        return 1
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.slug):
        print(f"error: slug must be lowercase letters/digits/hyphens: {args.slug!r}", file=sys.stderr)
        return 1
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.section):
        print(f"error: section must be a safe path segment: {args.section!r}", file=sys.stderr)
        return 1

    template_path = root / "theory" / "_template.md"
    template = template_path.read_text(encoding="utf-8")
    target = root / "theory" / args.section / f"{args.slug}_dissection.md"
    if target.exists() and not args.force:
        print(f"error: {target} already exists (use --force to overwrite)", file=sys.stderr)
        return 1

    venue = args.venue.strip() or f"arXiv {arxiv}"
    paper_link = f"https://arxiv.org/abs/{arxiv}"
    code = args.code.strip() or "无"
    project = args.project.strip() or paper_link
    title_line = f"# {args.title_zh.strip()} ({args.title.strip()})" if args.title_zh.strip() else f"# {args.title.strip()}"

    rendered = template
    rendered = re.sub(r"^# .*$", title_line, rendered, count=1, flags=re.MULTILINE)
    rendered = rendered.replace("<YYYY-MM-DD>", args.date)
    rendered = rendered.replace(
        "> **论文**: <完整标题、会议/年份、arXiv 版本>",
        f"> **论文**: {args.title.strip()}（{venue}）",
    )
    rendered = rendered.replace("> **链接**: <arXiv / 项目页>", f"> **链接**: {paper_link}")
    rendered = rendered.replace("> **代码**: <官方 repo，若无写“无”>", f"> **代码**: {code}")
    rendered = rendered.replace(
        "> **核心定位**: 一句话——它解决什么痛点 / 比谁强什么 / 代价是什么",
        f"> **核心定位**: {args.positioning.strip() or 'TODO：一句话定位'}",
    )
    rendered = rendered.replace("https://arxiv.org/abs/<XXXX.XXXXX>", paper_link)
    rendered = rendered.replace("- 论文：TODO", f"- 论文：{paper_link}")
    rendered = rendered.replace("- 代码：TODO", f"- 代码：{code}")
    rendered = rendered.replace("- 项目页：TODO", f"- 项目页：{project}")

    if args.dry_run:
        print(rendered)
        print(f"\n[dry-run] would write {target}", file=sys.stderr)
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")

    if not args.no_index:
        index_path = root / "theory" / "README.md"
        if index_path.exists():
            index = index_path.read_text(encoding="utf-8")
            rel = f"{args.section}/{args.slug}_dissection.md"
            if rel not in index:
                topic = args.topic.strip() or "TODO"
                row = f"| [{args.title_zh.strip() or args.title.strip()}]({rel}) | {topic} | draft | {args.date} |"
                lines = index.splitlines()
                insert_at = None
                for i, line in enumerate(lines):
                    if line.startswith("| 文章 |") or line.startswith("|------") or line.startswith("|---"):
                        insert_at = i + 1
                if insert_at is None:
                    index += f"\n{row}\n"
                else:
                    lines.insert(insert_at, row)
                    index = "\n".join(lines) + ("\n" if index.endswith("\n") else "")
                index_path.write_text(index, encoding="utf-8")

    print(f"created: {target.relative_to(root)}")
    print("next: fill TODO sections, then run `python3 scripts/audit_theory.py`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

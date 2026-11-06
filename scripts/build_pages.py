#!/usr/bin/env python3
"""Render the 3R Handbook pages from data/papers.json.

Everything this script writes carries an AUTO-GENERATED marker and should not be
edited by hand. Human notes live in notes/, book/, cheat-sheet/glossary.md.

Usage:
    python3 scripts/build_pages.py          # rebuild all generated pages
    python3 scripts/build_pages.py --check  # exit 1 if generated files are stale
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    AUTO_MARKER,
    ROOT,
    SECTION_DESCRIPTIONS,
    dump_json,
    load_json,
    utc_today,
)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def display_time(value: str) -> str:
    if not value:
        return "—"
    return value.replace("T", " ").replace("Z", "")[:16] + " UTC"


def md_escape(text: str) -> str:
    return clean(text).replace("|", "\\|")


def active_papers(doc: dict) -> list[dict]:
    return [paper for paper in doc.get("papers", []) if paper.get("status") == "active"]


def paper_title_md(paper: dict) -> str:
    title = md_escape(paper["title"])
    url = paper.get("links", {}).get("paper") or paper.get("links", {}).get("code")
    return f"[{title}]({url})" if url else title


def paper_resources_md(paper: dict) -> str:
    links = paper.get("links", {})
    parts: list[str] = []
    seen: set[str] = set()
    for key, label in (
        ("code", "Code"),
        ("website", "Project"),
        ("project", "Project"),
        ("demo", "Demo"),
        ("dataset", "Data"),
        ("video", "Video"),
    ):
        url = links.get(key)
        if url and url not in seen:
            parts.append(f"[{label}]({url})")
            seen.add(url)
    if not parts and links.get("paper"):
        parts.append(f"[PDF]({links['paper']})")
    return " · ".join(parts) if parts else "—"


def sort_for_display(papers: list[dict]) -> list[dict]:
    return sorted(
        papers,
        key=lambda paper: (
            -(paper.get("year") or 0),
            paper.get("title", "").lower(),
        ),
    )


def section_filename(slug: str) -> str:
    return f"{slug}.md"


def render_section_page(section: dict, papers: list[dict], source: dict) -> str:
    slug = section["slug"]
    name = section["name"]
    description = SECTION_DESCRIPTIONS.get(slug, f"{name} 方向的论文索引。")
    lines = [
        AUTO_MARKER,
        "",
        f"# {name}",
        "",
        f"> {description}",
        "",
        f"**{len(papers)} 篇** · 数据来源：[{source.get('repo', 'upstream')}]"
        f"(https://github.com/{source.get('repo', '')}) · 本页自动生成，最后同步见仓库首页。",
        "",
        "| # | 论文 | 会议/年份 | 年份 | 资源 |",
        "|---:|---|---|---:|---|",
    ]
    for index, paper in enumerate(sort_for_display(papers), start=1):
        lines.append(
            f"| {index} | {paper_title_md(paper)} | {md_escape(paper.get('venue') or '—')} "
            f"| {paper.get('year') or '—'} | {paper_resources_md(paper)} |"
        )
    if not papers:
        lines.append("| — | 暂无条目 | — | — | — |")
    lines.append("")
    lines.append(
        "> 条目由 [scripts/sync_upstream.py](../scripts/sync_upstream.py) 从上游 README 解析生成；"
        "标题、会议与链接以原论文/项目页为准。"
    )
    lines.append("")
    return "\n".join(lines)


def render_removed_page(removed: list[dict], source: dict) -> str:
    lines = [
        AUTO_MARKER,
        "",
        "# 已移除条目",
        "",
        "> 上游 README 中不再出现、但仍保留在本仓库历史里的条目。不会出现在分类页和统计中。",
        "",
        f"**{len(removed)} 篇** · 数据来源：{source.get('repo', 'upstream')}",
        "",
        "| 论文 | 会议/年份 | 移除日期 | 原分类 | 资源 |",
        "|---|---|---|---|---|",
    ]
    for paper in sorted(removed, key=lambda item: item.get("removed_at", ""), reverse=True):
        lines.append(
            f"| {paper_title_md(paper)} | {md_escape(paper.get('venue') or '—')} "
            f"| {paper.get('removed_at') or '—'} | {md_escape(paper.get('section') or '—')} "
            f"| {paper_resources_md(paper)} |"
        )
    if not removed:
        lines.append("| — | — | — | — | — |")
    lines.append("")
    return "\n".join(lines)


def render_index(doc: dict, last_run: dict) -> str:
    papers = active_papers(doc)
    counts = doc.get("counts", {})
    source = doc.get("source", {})
    sections = [section for section in doc.get("sections", []) if section.get("count", 0) > 0]

    lines = [
        AUTO_MARKER,
        "",
        "# 论文总览",
        "",
        f"> 自动抓取并解析自 [{source.get('repo', 'upstream')}](https://github.com/{source.get('repo', '')})，"
        "人工补充条目单独标记。",
        "",
        f"**{counts.get('active', len(papers))} 篇** · **{len(sections)} 个分类** · "
        f"最近同步：{display_time(last_run.get('sync_time', ''))}",
        "",
        "## 分类",
        "",
        "| 分类 | 数量 | 入口 |",
        "|---|---:|---|",
    ]
    for section in sections:
        lines.append(
            f"| {md_escape(section['name'])} | {section.get('count', 0)} "
            f"| [{section['slug']}]({section['slug']}.md) |"
        )
    lines.extend(
        [
            "",
            f"- [已移除条目](removed.md)（{counts.get('removed', 0)} 篇）",
            "",
            "## 最近新增",
            "",
        ]
    )

    recent_ids = last_run.get("created", [])
    by_id = {paper["id"]: paper for paper in papers}
    recent = [by_id[paper_id] for paper_id in recent_ids if paper_id in by_id]
    if not recent:
        recent = sorted(
            papers,
            key=lambda paper: (paper.get("first_seen", ""), -int(paper.get("order", 0))),
            reverse=True,
        )[:10]
    for paper in recent[:15]:
        lines.append(
            f"- {paper_title_md(paper)} — *{md_escape(paper.get('venue') or '未标注')}* "
            f"· {md_escape(paper.get('section') or '')}"
        )
    if not recent:
        lines.append("- 暂无记录")
    lines.append("")
    return "\n".join(lines)


def render_timeline(doc: dict) -> str:
    papers = active_papers(doc)
    counts = Counter(str(paper["year"]) for paper in papers if paper.get("year"))
    total = sum(counts.values()) or 1
    max_count = max(counts.values(), default=1)
    lines = [
        AUTO_MARKER,
        "",
        "# 时间线",
        "",
        "> 按论文标注的会议/预印本年份统计，不代表首次公开日期。数据自动生成。",
        "",
        "| 年份 | 论文数 | 占比 | 分布 |",
        "|---:|---:|---:|---|",
    ]
    for year in sorted(counts, reverse=True):
        count = counts[year]
        bar = "█" * max(1, round(count / max_count * 24))
        lines.append(f"| {year} | {count} | {count / total * 100:.1f}% | {bar} |")
    lines.append("")
    lines.append(f"共 **{sum(counts.values())}** 篇有年份标注；{len(papers) - sum(counts.values())} 篇未标注。")
    lines.append("")
    return "\n".join(lines)


def venue_key(venue: str) -> str:
    text = re.sub(r"\b(?:19|20)\d{2}\b", "", venue or "")
    text = re.sub(r"[,，]\s*$", "", text)
    return clean(text) or "未标注"


def render_venue_stats(doc: dict) -> str:
    papers = active_papers(doc)
    counts = Counter(venue_key(paper.get("venue", "")) for paper in papers)
    total = sum(counts.values()) or 1
    lines = [
        AUTO_MARKER,
        "",
        "# 会议 / 期刊分布",
        "",
        "> 从会议/年份字段中去掉年份后统计；`arXiv` 表示预印本。数据自动生成。",
        "",
        "| 会议 / 期刊 | 论文数 | 占比 |",
        "|---|---:|---:|",
    ]
    for venue, count in counts.most_common(30):
        lines.append(f"| {md_escape(venue)} | {count} | {count / total * 100:.1f}% |")
    lines.append("")
    return "\n".join(lines)


def render_daily_report(doc: dict, summary: dict, root: Path) -> None:
    created = summary.get("created", [])
    updated = summary.get("updated", [])
    removed = summary.get("removed", [])
    if not (created or updated or removed):
        return

    date = summary["date"]
    reports_dir = root / "reports" / "daily"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{date}.md"
    meta_path = reports_dir / f"{date}.json"
    meta = load_json(meta_path, {"date": date, "runs": []})
    run_entry = {
        "sync_time": summary.get("sync_time"),
        "mode": summary.get("mode"),
        "created": created,
        "updated": updated,
        "removed": removed,
        "counts": summary.get("counts", {}),
        "source": summary.get("source", {}),
    }
    runs = meta.setdefault("runs", [])
    run_key = (run_entry["sync_time"], run_entry["mode"])
    for index, existing in enumerate(runs):
        if (existing.get("sync_time"), existing.get("mode")) == run_key:
            runs[index] = run_entry
            break
    else:
        runs.append(run_entry)

    all_created: list[str] = []
    all_updated: list[str] = []
    all_removed: list[str] = []
    for run in meta["runs"]:
        for target, values in (
            (all_created, run.get("created", [])),
            (all_updated, run.get("updated", [])),
            (all_removed, run.get("removed", [])),
        ):
            for value in values:
                if value not in target:
                    target.append(value)

    by_id = {paper["id"]: paper for paper in doc.get("papers", [])}
    mode = summary.get("mode", "incremental")
    title = "基线快照" if mode == "baseline" else "同步报告"
    lines = [
        AUTO_MARKER,
        "",
        f"# {date} {title}",
        "",
        f"> 上游：`{summary.get('source', {}).get('repo', '')}` @ "
        f"`{(summary.get('source', {}).get('commit') or {}).get('sha', 'unknown')}` · "
        f"模式：`{mode}` · 生成时间：{display_time(summary.get('sync_time', ''))}",
        "",
        f"本次新增 **{len(created)}** 篇 · 更新 **{len(updated)}** 篇 · 移除 **{len(removed)}** 篇。"
        f" 当前共 **{summary.get('counts', {}).get('active', 0)}** 篇。",
        "",
        "## 新增",
        "",
    ]
    if all_created:
        for paper_id in all_created:
            paper = by_id.get(paper_id)
            if not paper:
                continue
            links = paper_resources_md(paper)
            lines.append(
                f"- **{paper_title_md(paper)}** — *{md_escape(paper.get('venue') or '未标注')}* "
                f"· {md_escape(paper.get('section') or '')} · {links}"
            )
            abstract = clean(paper.get("abstract", ""))
            if abstract:
                snippet = abstract[:320] + ("…" if len(abstract) > 320 else "")
                lines.append(f"  <br><sub>{md_escape(snippet)}</sub>")
    else:
        lines.append("- 无")
    lines.extend(["", "## 更新", ""])
    if all_updated:
        for paper_id in all_updated:
            paper = by_id.get(paper_id)
            if paper:
                lines.append(
                    f"- {paper_title_md(paper)} — *{md_escape(paper.get('venue') or '未标注')}*"
                )
    else:
        lines.append("- 无")
    lines.extend(["", "## 移除", ""])
    if all_removed:
        for paper_id in all_removed:
            paper = by_id.get(paper_id)
            if paper:
                lines.append(f"- {paper_title_md(paper)} — *{md_escape(paper.get('venue') or '未标注')}*")
    else:
        lines.append("- 无")
    lines.append("")
    if len(meta["runs"]) > 1:
        lines.extend(["## 当日运行记录", "", "| 时间 (UTC) | 模式 | 新增 | 更新 | 移除 |", "|---|---|---:|---:|---:|"])
        for run in meta["runs"]:
            lines.append(
                f"| {run.get('sync_time', '')} | {run.get('mode', '')} "
                f"| {len(run.get('created', []))} | {len(run.get('updated', []))} "
                f"| {len(run.get('removed', []))} |"
            )
        lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    dump_json(meta_path, meta)


def render_reports_index(root: Path) -> None:
    reports_dir = root / "reports" / "daily"
    entries = []
    for path in sorted(reports_dir.glob("*.md"), reverse=True):
        meta = load_json(path.with_suffix(".json"), {})
        runs = meta.get("runs", [])
        created = sum(len(run.get("created", [])) for run in runs)
        updated = sum(len(run.get("updated", [])) for run in runs)
        removed = sum(len(run.get("removed", [])) for run in runs)
        entries.append((path.stem, path.name, created, updated, removed, len(runs)))

    lines = [
        "| 日期 | 新增 | 更新 | 移除 | 运行次数 | 报告 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for date, filename, created, updated, removed, runs in entries:
        lines.append(f"| {date} | {created} | {updated} | {removed} | {runs} | [{filename}](daily/{filename}) |")
    if not entries:
        lines.append("| — | — | — | — | — | — |")
    content = "\n".join(lines)

    index_path = root / "reports" / "README.md"
    existing = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    marker = re.compile(r"(<!-- AUTO:REPORTS:BEGIN -->).*?(<!-- AUTO:REPORTS:END -->)", re.S)
    if marker.search(existing):
        existing = marker.sub(
            lambda match: f"{match.group(1)}\n{content}\n{match.group(2)}", existing
        )
    else:
        existing = (
            "# 同步归档\n\n"
            "每次上游发生变化的同步都会生成一份日报：新增、更新、移除的条目，以及当次运行模式。\n\n"
            "<!-- AUTO:REPORTS:BEGIN -->\n"
            f"{content}\n"
            "<!-- AUTO:REPORTS:END -->\n"
        )
    index_path.write_text(existing, encoding="utf-8")


def replace_block(text: str, name: str, content: str) -> tuple[str, bool]:
    pattern = re.compile(rf"(<!-- AUTO:{name}:BEGIN -->).*?(<!-- AUTO:{name}:END -->)", re.S)
    if not pattern.search(text):
        return text, False
    replacement = f"{pattern.search(text).group(1)}\n{content.strip()}\n{pattern.search(text).group(2)}"
    return pattern.sub(lambda _: replacement, text), True


def update_readme(doc: dict, last_run: dict, root: Path) -> None:
    readme_path = root / "README.md"
    if not readme_path.exists():
        return
    text = readme_path.read_text(encoding="utf-8")
    papers = active_papers(doc)
    counts = doc.get("counts", {})
    source = doc.get("source", {})
    commit = source.get("commit") or {}
    commit_sha = commit.get("sha", "")
    commit_url = (
        f"https://github.com/{source.get('repo', '')}/commit/{commit_sha}" if commit_sha else ""
    )
    source_label = source.get("repo", "upstream")
    source_link = f"[{source_label}](https://github.com/{source_label})"
    if commit_sha:
        source_link += f"@[{commit_sha}]({commit_url})"

    by_year = counts.get("by_year", {})
    year_line = " · ".join(f"{year} 年 {count} 篇" for year, count in sorted(by_year.items()))
    stats = (
        f"> **{counts.get('active', 0)}** 篇论文 · **{len([s for s in doc.get('sections', []) if s.get('count', 0) > 0])}** 个分类"
        f" · 人工补充 **{counts.get('manual', 0)}** 篇 · 最近同步 **{display_time(last_run.get('sync_time', ''))}**\n>\n"
        f"> 数据源：{source_link} · {year_line or '暂无年份统计'}"
    )
    text, ok_stats = replace_block(text, "STATS", stats)

    section_lines = ["| 分类 | 数量 | 入口 |", "|---|---:|---|"]
    for section in doc.get("sections", []):
        if section.get("count", 0) <= 0:
            continue
        section_lines.append(
            f"| {md_escape(section['name'])} | {section.get('count', 0)} "
            f"| [{section['slug']}](papers/{section['slug']}.md) |"
        )
    section_lines.append(f"| 已移除（历史） | {counts.get('removed', 0)} | [removed](papers/removed.md) |")
    text, ok_sections = replace_block(text, "SECTIONS", "\n".join(section_lines))

    by_id = {paper["id"]: paper for paper in papers}
    recent = [by_id[paper_id] for paper_id in last_run.get("created", []) if paper_id in by_id]
    if not recent:
        recent = sorted(
            papers,
            key=lambda paper: (paper.get("first_seen", ""), -int(paper.get("order", 0))),
            reverse=True,
        )[:8]
    recent_lines = []
    for paper in recent[:8]:
        recent_lines.append(
            f"- {paper_title_md(paper)} — *{md_escape(paper.get('venue') or '未标注')}*"
            f" · {md_escape(paper.get('section') or '')}"
        )
    if not recent_lines:
        recent_lines.append("- 暂无记录")
    text, ok_recent = replace_block(text, "RECENT", "\n".join(recent_lines))

    if not (ok_stats and ok_sections and ok_recent):
        print("warning: README is missing one or more AUTO blocks; skipped that block", file=sys.stderr)
    readme_path.write_text(text, encoding="utf-8")


def update_changelog(summary: dict, root: Path) -> None:
    if not (summary.get("created") or summary.get("updated") or summary.get("removed")):
        return
    path = root / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8") if path.exists() else "# Changelog\n\n"
    date = summary["date"]
    line = (
        f"- {len(summary.get('created', []))} 篇新增 / {len(summary.get('updated', []))} 篇更新 / "
        f"{len(summary.get('removed', []))} 篇移除；当前 {summary.get('counts', {}).get('active', 0)} 篇"
        f"（`{summary.get('mode', 'incremental')}`）。"
    )
    heading = f"## {date}"
    if heading in text:
        if line in text:
            return
        start = text.index(heading) + len(heading)
        # insert after the heading (and an optional blank line)
        rest = text[start:]
        blank = "\n" if rest.startswith("\n") else "\n\n"
        text = text[:start] + blank + line + "\n" + rest.lstrip("\n")
    else:
        first_section = text.find("\n## ")
        if first_section == -1:
            text = text.rstrip() + f"\n\n{heading}\n\n{line}\n"
        else:
            text = text[:first_section] + f"\n\n{heading}\n\n{line}\n" + text[first_section:]
    path.write_text(text, encoding="utf-8")


def write_jsonl(doc: dict, root: Path) -> None:
    path = root / "data" / "papers.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for paper in doc.get("papers", []):
            handle.write(json.dumps(paper, ensure_ascii=False) + "\n")


def write_stats(doc: dict, root: Path) -> None:
    stats = {
        "schema_version": doc.get("schema_version", 1),
        "counts": doc.get("counts", {}),
        "sections": [
            {"name": section["name"], "slug": section["slug"], "count": section.get("count", 0)}
            for section in doc.get("sections", [])
        ],
        "source": {
            "repo": doc.get("source", {}).get("repo"),
            "commit": (doc.get("source", {}).get("commit") or {}).get("sha"),
        },
    }
    dump_json(root / "data" / "stats.json", stats)


def build_all(doc: dict, summary: dict | None = None, root: Path = ROOT, render_report: bool = False) -> None:
    root = Path(root)
    summary = summary or load_json(root / "data" / "last-run.json", {}) or {}
    last_run = load_json(root / "data" / "last-run.json", {}) or summary
    papers = active_papers(doc)
    by_slug: dict[str, list[dict]] = {}
    for paper in papers:
        by_slug.setdefault(paper.get("slug") or "misc", []).append(paper)

    papers_dir = root / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)
    keep = {"README.md", "removed.md"}
    for section in doc.get("sections", []):
        slug = section["slug"]
        path = papers_dir / section_filename(slug)
        path.write_text(render_section_page(section, by_slug.get(slug, []), doc.get("source", {})), encoding="utf-8")
        keep.add(path.name)

    removed = [paper for paper in doc.get("papers", []) if paper.get("status") == "removed"]
    (papers_dir / "removed.md").write_text(
        render_removed_page(removed, doc.get("source", {})), encoding="utf-8"
    )
    (papers_dir / "README.md").write_text(render_index(doc, last_run), encoding="utf-8")

    for path in papers_dir.glob("*.md"):
        if path.name in keep:
            continue
        try:
            if path.read_text(encoding="utf-8").startswith(AUTO_MARKER):
                path.unlink()
        except OSError:
            pass

    cheat_dir = root / "cheat-sheet"
    cheat_dir.mkdir(parents=True, exist_ok=True)
    (cheat_dir / "timeline.md").write_text(render_timeline(doc), encoding="utf-8")
    (cheat_dir / "venue-stats.md").write_text(render_venue_stats(doc), encoding="utf-8")

    if render_report:
        render_daily_report(doc, summary, root)
    render_reports_index(root)
    update_readme(doc, last_run, root)
    update_changelog(summary, root)
    write_jsonl(doc, root)
    write_stats(doc, root)
    print(f"built: {len(papers)} active papers across {len(by_slug)} sections")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild generated 3R Handbook pages.")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    doc = load_json(Path(args.root) / "data" / "papers.json")
    if not doc:
        print("error: data/papers.json is missing; run sync_upstream.py first", file=sys.stderr)
        return 1
    build_all(doc, load_json(Path(args.root) / "data" / "last-run.json", {}), Path(args.root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

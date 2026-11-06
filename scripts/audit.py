#!/usr/bin/env python3
"""Structural and (optional) link audit for the 3R Handbook.

Usage:
    python3 scripts/audit.py
    python3 scripts/audit.py --strict
    python3 scripts/audit.py --check-links
    python3 scripts/audit.py --fail-on-warnings

Exit codes: 0 = clean, 1 = errors (or warnings with --fail-on-warnings).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import AUTO_MARKER, ROOT, load_json, normalize_title  # noqa: E402


def check_links(urls: list[str], timeout: int = 12) -> list[tuple[str, str]]:
    context = ssl.create_default_context()

    def probe(url: str) -> tuple[str, str]:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; 3R-Handbook-Audit/1.0)"}
        for method in ("HEAD", "GET"):
            try:
                request = urllib.request.Request(url, method=method, headers=headers)
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    if response.status < 400:
                        return url, ""
                    return url, f"HTTP {response.status}"
            except urllib.error.HTTPError as exc:
                if method == "HEAD" and exc.code in (403, 405, 400):
                    continue
                return url, f"HTTP {exc.code}"
            except Exception as exc:  # noqa: BLE001
                if method == "GET":
                    return url, str(exc)[:120]
        return url, "unreachable"

    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for url, error in pool.map(probe, urls):
            if error:
                failures.append((url, error))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the 3R Handbook structure.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--strict", action="store_true", help="return 1 on errors")
    parser.add_argument("--check-links", action="store_true", help="network-check paper/code URLs")
    parser.add_argument("--fail-on-warnings", action="store_true")
    parser.add_argument("--timeout", type=int, default=12)
    args = parser.parse_args()

    root = Path(args.root)
    errors: list[str] = []
    warnings: list[str] = []

    doc = load_json(root / "data" / "papers.json")
    if not doc:
        print("ERROR: data/papers.json is missing")
        return 1

    if doc.get("schema_version") != 1:
        errors.append(f"schema_version is {doc.get('schema_version')!r}, expected 1")

    papers = doc.get("papers", [])
    if not papers:
        errors.append("papers list is empty")

    ids = [paper.get("id") for paper in papers]
    duplicate_ids = [item for item, count in Counter(ids).items() if count > 1]
    if duplicate_ids:
        errors.append(f"duplicate ids: {duplicate_ids[:10]}")

    active = [paper for paper in papers if paper.get("status") == "active"]
    removed = [paper for paper in papers if paper.get("status") == "removed"]
    for paper in papers:
        pid = paper.get("id", "<missing>")
        if paper.get("status") not in {"active", "removed"}:
            errors.append(f"{pid}: invalid status {paper.get('status')!r}")
        for field in ("id", "title", "section", "slug"):
            if not paper.get(field):
                errors.append(f"{pid}: missing {field}")
        if paper.get("status") == "removed" and not paper.get("removed_at"):
            errors.append(f"{pid}: removed entry has no removed_at")

    counts = doc.get("counts", {})
    if counts.get("active") != len(active):
        errors.append(f"counts.active={counts.get('active')} but {len(active)} active papers")
    if counts.get("removed") != len(removed):
        errors.append(f"counts.removed={counts.get('removed')} but {len(removed)} removed papers")

    section_counts = Counter(paper["section"] for paper in active)
    for section in doc.get("sections", []):
        expected = section.get("count", 0)
        actual = section_counts.get(section["name"], 0)
        if expected != actual:
            errors.append(f"section {section['name']!r}: count={expected}, actual={actual}")
        page = root / "papers" / f"{section['slug']}.md"
        if not page.exists():
            errors.append(f"missing section page: {page}")

    titles = Counter(normalize_title(paper["title"]) for paper in active)
    duplicates = [title for title, count in titles.items() if count > 1]
    if duplicates:
        warnings.append(f"duplicate active titles (normalised): {duplicates[:5]}")

    no_venue = [paper["id"] for paper in active if not paper.get("venue")]
    if no_venue:
        warnings.append(f"{len(no_venue)} active papers have no venue (e.g. {no_venue[:5]})")

    no_paper_link = [paper["id"] for paper in active if not paper.get("links", {}).get("paper")]
    if no_paper_link:
        warnings.append(f"{len(no_paper_link)} active papers have no paper link (e.g. {no_paper_link[:5]})")

    readme = root / "README.md"
    if not readme.exists():
        errors.append("README.md is missing")
    else:
        text = readme.read_text(encoding="utf-8")
        for name in ("STATS", "SECTIONS", "RECENT"):
            if f"<!-- AUTO:{name}:BEGIN -->" not in text:
                errors.append(f"README.md is missing AUTO:{name} block")

    generated = [
        root / "papers" / "README.md",
        root / "papers" / "removed.md",
        root / "cheat-sheet" / "timeline.md",
        root / "cheat-sheet" / "venue-stats.md",
    ]
    for path in generated:
        if not path.exists():
            errors.append(f"missing generated page: {path}")
        elif not path.read_text(encoding="utf-8").startswith(AUTO_MARKER):
            warnings.append(f"generated page lacks AUTO marker: {path}")

    jsonl = root / "data" / "papers.jsonl"
    if not jsonl.exists():
        errors.append("data/papers.jsonl is missing")
    else:
        line_count = sum(1 for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip())
        if line_count != len(papers):
            errors.append(f"papers.jsonl has {line_count} lines, expected {len(papers)}")

    if not (root / "data" / "last-run.json").exists():
        errors.append("data/last-run.json is missing")

    if args.check_links:
        urls = sorted(
            {
                url
                for paper in active
                for url in paper.get("links", {}).values()
                if isinstance(url, str) and url.startswith("http")
            }
        )
        print(f"checking {len(urls)} links ...")
        failures = check_links(urls, timeout=args.timeout)
        for url, error in failures:
            warnings.append(f"link check failed: {url} ({error})")
        print(f"link check: {len(urls) - len(failures)} ok, {len(failures)} failed")

    for message in errors:
        print(f"ERROR: {message}")
    for message in warnings:
        print(f"WARN:  {message}")
    print(f"audit: {len(errors)} errors, {len(warnings)} warnings, {len(active)} active papers")

    if errors:
        return 1
    if args.fail_on_warnings and warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Synchronise the 3R Handbook catalogue from upstream awesome lists.

Pipeline
--------
fetch README -> snapshot -> parse bullets -> merge with history + manual
supplements -> optional arXiv enrichment -> rebuild pages -> log

Usage examples
--------------
    python3 scripts/sync_upstream.py
    python3 scripts/sync_upstream.py --offline
    python3 scripts/sync_upstream.py --dry-run
    python3 scripts/sync_upstream.py --force
    python3 scripts/sync_upstream.py --no-enrich

Only the Python standard library is required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    ROOT,
    dump_json,
    extract_arxiv_id,
    load_json,
    normalize_title,
    section_slug,
    sha256_text,
    utc_now,
    utc_today,
)

DEFAULT_CONFIG = ROOT / "config" / "sources.json"
HEADING_RE = re.compile(r"^(#{2,4})\s+(.+?)\s*$")
BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)\s*$")
LINK_RE = re.compile(r"\[\[([A-Za-z][A-Za-z0-9 _-]*)\]\(([^)]*)\)\s*\]?")
VENUE_RE = re.compile(r",\s*\*([^*]+)\*\s*\.?\s*$")
LINK_LABELS = {
    "paper": "paper",
    "pdf": "paper",
    "arxiv": "paper",
    "code": "code",
    "github": "code",
    "website": "website",
    "project": "project",
    "project page": "project",
    "demo": "demo",
    "video": "video",
    "dataset": "dataset",
}


def http_get(url: str, etag: str | None = None, token: str | None = None, timeout: int = 30):
    """Return (status, text, headers). 304 is returned instead of raised."""
    headers = {"User-Agent": "3R-Handbook/1.0 (+https://github.com/jzx05/3R-Handbook)"}
    if etag:
        headers["If-None-Match"] = etag
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, body, {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return 304, "", {k.lower(): v for k, v in (exc.headers or {}).items()}
        raise


def fetch_commit(repo: str, branch: str, token: str | None = None):
    """Best-effort GitHub commit metadata. Never fatal."""
    url = f"https://api.github.com/repos/{repo}/commits/{branch}"
    try:
        status, body, _ = http_get(url, token=token)
        if status != 200:
            return None
        data = json.loads(body)
        return {
            "sha": data["sha"][:12],
            "date": data["commit"]["committer"]["date"],
            "message": data["commit"]["message"].splitlines()[0][:200],
        }
    except Exception as exc:  # noqa: BLE001 - metadata is optional
        print(f"  ! commit metadata unavailable: {exc}", file=sys.stderr)
        return None


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def clean_venue(venue: str) -> str:
    venue = clean_text(venue)
    return venue.strip(" .,;，;")


def make_id(title: str, used_ids: set[str]) -> str:
    base = "p-" + hashlib.sha1(normalize_title(title).encode("utf-8")).hexdigest()[:10]
    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def parse_entry(raw: str, section: str, order: int, used_ids: set[str], seen_titles: dict):
    """Parse one bullet. Returns a paper dict or None."""
    links: dict[str, str] = {}
    for label, url in LINK_RE.findall(raw):
        url = url.strip()
        if not re.match(r"^https?://", url):
            continue
        key = LINK_LABELS.get(label.strip().lower(), label.strip().lower())
        if key not in links:
            links[key] = url

    remainder = LINK_RE.sub("", raw)
    remainder = re.sub(r"(?i)\bpaper[\s-]*todo\b", " ", remainder)
    remainder = clean_text(remainder).strip(" .,;,]")

    venue = ""
    title = remainder
    match = VENUE_RE.search(remainder)
    if match:
        venue = clean_venue(match.group(1))
        title = remainder[: match.start()].strip(" ,")

    title = clean_text(title).strip(" .")
    if len(title) < 4:
        return None
    if title.lower() in {"paper", "code", "website", "project"}:
        return None

    key = normalize_title(title)
    if key in seen_titles:
        existing = seen_titles[key]
        for link_key, link_url in links.items():
            existing["links"].setdefault(link_key, link_url)
        if section not in existing["also_in"]:
            existing["also_in"].append(section)
        return None

    years = re.findall(r"(?:19|20)\d{2}", venue)
    year = int(years[-1]) if years else None
    arxiv_id = extract_arxiv_id(links.values())
    paper_id = make_id(title, used_ids)

    paper = {
        "id": paper_id,
        "title": title,
        "venue": venue,
        "year": year,
        "section": section,
        "slug": section_slug(section),
        "links": links,
        "arxiv_id": arxiv_id,
        "order": order,
        "first_seen": utc_today(),
        "status": "active",
        "manual": False,
        "also_in": [],
    }
    seen_titles[key] = paper
    return paper


def parse_readme(text: str):
    """Return (papers, sections) parsed from an awesome-list README."""
    papers: list[dict] = []
    sections: list[dict] = []
    section = None
    order = 0
    used_ids: set[str] = set()
    seen_titles: dict[str, dict] = {}

    for line in text.splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            name = clean_text(heading.group(2))
            if level == 2:
                section = name
                if not any(item["name"] == name for item in sections):
                    sections.append(
                        {"name": name, "slug": section_slug(name), "order": len(sections), "count": 0}
                    )
            continue

        bullet = BULLET_RE.match(line)
        if not bullet or not section:
            continue

        paper = parse_entry(bullet.group(1), section, order, used_ids, seen_titles)
        if paper:
            papers.append(paper)
            order += 1

    return papers, sections


def load_supplements():
    path = ROOT / "data" / "supplements" / "papers.json"
    data = load_json(path, {"papers": []})
    return data.get("papers", []) if isinstance(data, dict) else []


def merge_catalogue(parsed: list[dict], previous: dict | None, supplements: list[dict], today: str):
    previous_papers = (previous or {}).get("papers", [])
    previous_by_id = {paper["id"]: paper for paper in previous_papers}
    merged: list[dict] = []
    created: list[dict] = []
    updated: list[dict] = []
    removed: list[dict] = []
    parsed_ids: set[str] = set()

    for paper in parsed:
        parsed_ids.add(paper["id"])
        old = previous_by_id.get(paper["id"])
        if old:
            paper["first_seen"] = old.get("first_seen", today)
            for field in (
                "authors",
                "abstract",
                "published",
                "arxiv_title",
                "categories",
                "enrichment",
                "enriched_at",
            ):
                if field in old and field not in paper:
                    paper[field] = old[field]
            changed = any(
                old.get(field) != paper.get(field)
                for field in ("title", "venue", "year", "section", "links", "arxiv_id")
            )
            if changed:
                updated.append(paper)
        else:
            paper["first_seen"] = today
            created.append(paper)
        paper["status"] = "active"
        paper.pop("removed_at", None)
        merged.append(paper)

    for old in previous_papers:
        if old["id"] in parsed_ids:
            continue
        if old.get("manual"):
            # Manual entries are re-added from data/supplements/papers.json below,
            # so edits to the supplement file are picked up instead of frozen.
            continue
        if old.get("status") == "removed":
            merged.append(old)
            continue
        old["status"] = "removed"
        old["removed_at"] = today
        removed.append(old)
        merged.append(old)

    existing_ids = {paper["id"] for paper in merged}
    for index, supplement in enumerate(supplements):
        title = clean_text(supplement.get("title", ""))
        if not title:
            continue
        paper_id = supplement.get("id") or make_id(title, set())
        if paper_id in existing_ids:
            continue
        old = previous_by_id.get(paper_id)
        paper = {
            "id": paper_id,
            "title": title,
            "venue": clean_venue(supplement.get("venue", "")),
            "year": supplement.get("year"),
            "section": supplement.get("section", "Downstream Tasks"),
            "slug": section_slug(supplement.get("section", "Downstream Tasks")),
            "links": supplement.get("links", {}),
            "arxiv_id": supplement.get("arxiv_id")
            or extract_arxiv_id(supplement.get("links", {}).values()),
            "order": 100000 + index,
            "first_seen": today,
            "status": "active",
            "manual": True,
            "also_in": [],
            "source": "manual",
        }
        if paper["year"] is None:
            years = re.findall(r"(?:19|20)\d{2}", paper["venue"])
            paper["year"] = int(years[-1]) if years else None
        if old:
            paper["first_seen"] = old.get("first_seen", today)
            for field in (
                "authors",
                "abstract",
                "published",
                "arxiv_title",
                "categories",
                "enrichment",
                "enriched_at",
            ):
                if field in old and field not in paper:
                    paper[field] = old[field]
            if any(old.get(f) != paper.get(f) for f in ("title", "venue", "links")):
                updated.append(paper)
        else:
            created.append(paper)
        existing_ids.add(paper_id)
        merged.append(paper)

    def sort_key(paper):
        if paper.get("status") == "removed":
            return (2, paper.get("order", 999999), paper["title"].lower())
        if paper.get("manual"):
            return (1, paper.get("order", 100000), paper["title"].lower())
        return (0, paper.get("order", 999999), paper["title"].lower())

    merged.sort(key=sort_key)
    return merged, created, updated, removed


def build_doc(source: dict, sections: list[dict], papers: list[dict]) -> dict:
    active = [paper for paper in papers if paper.get("status") == "active"]
    section_counts: dict[str, int] = {}
    for paper in active:
        section_counts[paper["section"]] = section_counts.get(paper["section"], 0) + 1

    for item in sections:
        item["count"] = section_counts.get(item["name"], 0)

    existing_slugs = {item["slug"] for item in sections}
    for paper in active:
        if paper["slug"] not in existing_slugs:
            sections.append(
                {
                    "name": paper["section"],
                    "slug": paper["slug"],
                    "order": len(sections),
                    "count": section_counts.get(paper["section"], 0),
                }
            )
            existing_slugs.add(paper["slug"])

    by_year: dict[str, int] = {}
    for paper in active:
        if paper.get("year"):
            by_year[str(paper["year"])] = by_year.get(str(paper["year"]), 0) + 1

    return {
        "schema_version": 1,
        "source": source,
        "sections": sections,
        "counts": {
            "total": len(papers),
            "active": len(active),
            "removed": len(papers) - len(active),
            "manual": sum(1 for paper in active if paper.get("manual")),
            "by_year": dict(sorted(by_year.items())),
            "by_section": section_counts,
        },
        "papers": papers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync the 3R Handbook from upstream sources.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--offline", action="store_true", help="use data/upstream/README.md")
    parser.add_argument("--dry-run", action="store_true", help="parse and report, write nothing")
    parser.add_argument("--force", action="store_true", help="rebuild even when the hash is unchanged")
    parser.add_argument("--no-enrich", action="store_true", help="skip arXiv metadata enrichment")
    parser.add_argument("--limit-enrich", type=int, default=200)
    parser.add_argument(
        "--allow-mass-removal",
        action="store_true",
        help="allow the active catalogue to shrink by more than 50%%",
    )
    args = parser.parse_args()

    config = load_json(args.config, {})
    sources = [source for source in config.get("sources", []) if source.get("enabled", True)]
    if not sources:
        print(f"error: no enabled source in {args.config}", file=sys.stderr)
        return 1
    source_config = sources[0]

    state_path = ROOT / "data" / "upstream" / "state.json"
    snapshot_path = ROOT / "data" / "upstream" / "README.md"
    state = load_json(state_path, {})
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    fetch_mode = "network"
    if args.offline:
        if not snapshot_path.exists():
            print(f"error: --offline but {snapshot_path} is missing", file=sys.stderr)
            return 1
        text = snapshot_path.read_text(encoding="utf-8")
        fetch_mode = "offline"
    else:
        try:
            status, text, headers = http_get(source_config["readme_url"], etag=state.get("etag"), token=token)
            if status == 304:
                text = snapshot_path.read_text(encoding="utf-8") if snapshot_path.exists() else ""
            else:
                state["etag"] = headers.get("etag")
                state["last_modified"] = headers.get("last-modified")
        except Exception as exc:  # noqa: BLE001
            if snapshot_path.exists():
                print(f"warning: fetch failed ({exc}); falling back to cached snapshot", file=sys.stderr)
                text = snapshot_path.read_text(encoding="utf-8")
                fetch_mode = "cached"
            else:
                print(f"error: fetch failed and no snapshot exists: {exc}", file=sys.stderr)
                return 1

    if not text.strip():
        print("error: upstream README is empty", file=sys.stderr)
        return 1

    digest = sha256_text(text)
    previous = load_json(ROOT / "data" / "papers.json")
    unchanged = bool(state.get("sha256") == digest and previous)
    if unchanged and not args.force:
        print(f"upstream unchanged (sha256 {digest[:12]}); nothing to do")
        return 0

    parsed, sections = parse_readme(text)
    if not parsed:
        print("error: parsed zero papers; refusing to update", file=sys.stderr)
        return 1

    previous_active = 0
    if previous:
        previous_active = sum(
            1
            for paper in previous.get("papers", [])
            if paper.get("status") == "active" and not paper.get("manual")
        )
    if previous_active >= 10 and len(parsed) < previous_active * 0.5 and not args.allow_mass_removal:
        print(
            f"error: parsed {len(parsed)} entries vs {previous_active} active before; "
            "refusing a >50% shrink (pass --allow-mass-removal to override)",
            file=sys.stderr,
        )
        return 1

    commit = None if args.offline else fetch_commit(
        source_config["repo"], source_config.get("branch", "main"), token
    )
    today = utc_today()
    merged, created, updated, removed = merge_catalogue(parsed, previous, load_supplements(), today)

    source_meta = {
        "id": source_config["id"],
        "repo": source_config["repo"],
        "branch": source_config.get("branch", "main"),
        "readme_url": source_config["readme_url"],
        "readme_sha256": digest,
        "snapshot": "data/upstream/README.md",
        "commit": commit,
        "mode": fetch_mode,
    }
    doc = build_doc(source_meta, sections, merged)

    if previous is None:
        mode = "baseline"
    elif created or updated or removed:
        mode = "incremental"
    else:
        mode = "rebuild"

    run_summary = {
        "date": today,
        "sync_time": utc_now(),
        "mode": mode,
        "source": source_meta,
        "created": [paper["id"] for paper in created],
        "updated": [paper["id"] for paper in updated],
        "removed": [paper["id"] for paper in removed],
        "counts": doc["counts"],
    }

    print(
        f"parsed {len(parsed)} entries | active {doc['counts']['active']} | "
        f"created {len(created)} | updated {len(updated)} | removed {len(removed)} | mode {mode}"
    )
    if args.dry_run:
        print("dry-run: no files written")
        return 0

    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(text, encoding="utf-8")
    state.update(
        {
            "source_id": source_config["id"],
            "sha256": digest,
            "fetched_at": run_summary["sync_time"],
            "commit": commit,
        }
    )
    dump_json(state_path, state)

    enrichment = {"enriched": 0, "pending": 0, "skipped": args.no_enrich or args.offline}
    if not args.no_enrich and not args.offline:
        try:
            from enrich_arxiv import enrich_papers

            enrichment = enrich_papers(doc, ROOT, limit=args.limit_enrich)
        except Exception as exc:  # noqa: BLE001 - enrichment is optional
            print(f"warning: arXiv enrichment skipped: {exc}", file=sys.stderr)
    run_summary["enrichment"] = enrichment

    dump_json(ROOT / "data" / "papers.json", doc)
    dump_json(ROOT / "data" / "last-run.json", run_summary)

    with (ROOT / "data" / "sync-log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(run_summary, ensure_ascii=False) + "\n")

    from build_pages import build_all

    build_all(doc, run_summary, ROOT, render_report=True)
    print("done: data/papers.json + generated pages updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

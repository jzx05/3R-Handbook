#!/usr/bin/env python3
"""Enrich catalogue entries with arXiv metadata (title, authors, abstract).

The cache in data/arxiv-cache.json is keyed by arXiv id, so a paper that appears
twice upstream (e.g. a preprint and its conference version) is only fetched once.

Usage:
    python3 scripts/enrich_arxiv.py            # enrich pending entries
    python3 scripts/enrich_arxiv.py --all      # refresh every arXiv entry
    python3 scripts/enrich_arxiv.py --limit 50

Only the Python standard library is required.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    ROOT,
    dump_json,
    extract_arxiv_id,
    load_json,
    utc_today,
)

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
ARXIV_API = "https://export.arxiv.org/api/query"
BATCH_SIZE = 20
REQUEST_DELAY = 3.0  # arXiv asks for at least 3 seconds between API calls


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def fetch_batch(arxiv_ids: list[str], timeout: int = 60) -> dict:
    query = urllib.parse.urlencode({"id_list": ",".join(arxiv_ids), "max_results": len(arxiv_ids)})
    request = urllib.request.Request(
        f"{ARXIV_API}?{query}",
        headers={"User-Agent": "3R-Handbook/1.0 (+https://github.com/jzx05/3R-Handbook)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()

    root = ET.fromstring(payload)
    results: dict[str, dict] = {}
    for entry in root.findall(f"{ATOM}entry"):
        identifier = entry.findtext(f"{ATOM}id", default="")
        match = re.search(r"abs/([0-9]{4}\.[0-9]{4,5})", identifier)
        if not match:
            continue
        arxiv_id = match.group(1)
        authors = [
            collapse(author.findtext(f"{ATOM}name", default=""))
            for author in entry.findall(f"{ATOM}author")
        ]
        categories = [
            category.get("term")
            for category in entry.findall(f"{ATOM}category")
            if category.get("term")
        ]
        results[arxiv_id] = {
            "title": collapse(entry.findtext(f"{ATOM}title", default="")),
            "abstract": collapse(entry.findtext(f"{ATOM}summary", default="")),
            "authors": [author for author in authors if author],
            "published": entry.findtext(f"{ATOM}published", default="")[:10],
            "updated": entry.findtext(f"{ATOM}updated", default="")[:10],
            "categories": sorted(set(categories)),
            "fetched_at": utc_today(),
        }
    return results


def apply_metadata(paper: dict, metadata: dict) -> None:
    paper["arxiv_title"] = metadata.get("title", "")
    paper["authors"] = metadata.get("authors", [])
    paper["abstract"] = (metadata.get("abstract") or "")[:2000]
    paper["published"] = metadata.get("published", "")
    paper["categories"] = metadata.get("categories", [])
    paper["enrichment"] = "ok"
    paper["enriched_at"] = metadata.get("fetched_at") or utc_today()


def enrich_papers(doc: dict, root: Path = ROOT, limit: int = 200, delay: float = REQUEST_DELAY) -> dict:
    """Enrich active papers in-place. Returns counters; network errors are non-fatal."""
    cache_path = Path(root) / "data" / "arxiv-cache.json"
    cache = load_json(cache_path, {})
    cache_changed = False

    by_arxiv: dict[str, list[dict]] = {}
    pending_ids: list[str] = []

    for paper in doc.get("papers", []):
        if paper.get("status") != "active":
            continue
        arxiv_id = paper.get("arxiv_id") or extract_arxiv_id(paper.get("links", {}).values())
        if not arxiv_id:
            paper["enrichment"] = "no-arxiv"
            continue
        paper["arxiv_id"] = arxiv_id
        by_arxiv.setdefault(arxiv_id, []).append(paper)
        if arxiv_id in cache:
            apply_metadata(paper, cache[arxiv_id])
        elif paper.get("enrichment") == "ok" and paper.get("abstract"):
            continue
        elif arxiv_id not in pending_ids:
            pending_ids.append(arxiv_id)

    pending_ids = pending_ids[: max(0, limit)]
    fetched = 0
    failed = 0

    for start in range(0, len(pending_ids), BATCH_SIZE):
        batch = pending_ids[start : start + BATCH_SIZE]
        try:
            metadata = fetch_batch(batch)
        except Exception as exc:  # noqa: BLE001 - enrichment must not break sync
            failed += len(batch)
            print(f"warning: arXiv batch failed ({exc}); {len(batch)} ids left pending", file=sys.stderr)
            continue
        for arxiv_id, item in metadata.items():
            cache[arxiv_id] = item
            cache_changed = True
            fetched += 1
            for paper in by_arxiv.get(arxiv_id, []):
                apply_metadata(paper, item)
        if start + BATCH_SIZE < len(pending_ids):
            time.sleep(delay)

    unknown = [arxiv_id for arxiv_id in pending_ids if arxiv_id not in cache]
    for arxiv_id in unknown:
        for paper in by_arxiv.get(arxiv_id, []):
            paper["enrichment"] = "pending"

    if cache_changed:
        dump_json(cache_path, cache)

    return {
        "enriched": fetched,
        "pending": len(unknown),
        "failed_batches": failed,
        "cached_ids": len(cache),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich papers.json with arXiv metadata.")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--all", action="store_true", help="refresh entries already marked ok")
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY)
    args = parser.parse_args()

    doc_path = ROOT / "data" / "papers.json"
    doc = load_json(doc_path)
    if not doc:
        print(f"error: {doc_path} is missing; run sync_upstream.py first", file=sys.stderr)
        return 1

    if args.all:
        for paper in doc.get("papers", []):
            paper.pop("enrichment", None)
            paper.pop("abstract", None)

    stats = enrich_papers(doc, ROOT, limit=args.limit, delay=args.delay)
    dump_json(doc_path, doc)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

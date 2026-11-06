#!/usr/bin/env python3
"""Regression tests for the upstream parser and merge logic.

Run with:
    python3 -m unittest discover -s scripts -p 'test_*.py' -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_upstream  # noqa: E402

SAMPLE = """# Test README

## Survey Paper

- A survey of things, *arXiv 2025*. [[Paper](https://arxiv.org/pdf/2501.00001)]

## SLAM

- Foo: A method, *CVPR 2025*. [[Paper](https://arxiv.org/pdf/2501.12345)] [[Code](https://github.com/foo/bar)]
- Bar: Another method, *ICRA, 2026*. Paper-todo
- Foo: A method, *CVPR 2025*. [[Paper](https://arxiv.org/pdf/2501.12345)] [[Website](https://foo.github.io)]
- Malformed link, *arXiv 2026*. [[Website](https://x.example) [[Code](https://github.com/x/y)]
- Empty link, *ECCV 2026*. [[Paper]()] [[Code](https://github.com/e/f)]
"""


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.papers, self.sections = sync_upstream.parse_readme(SAMPLE)

    def test_section_headings(self):
        self.assertEqual([section["name"] for section in self.sections], ["Survey Paper", "SLAM"])
        self.assertEqual(self.sections[1]["slug"], "slam")

    def test_duplicate_title_is_merged(self):
        foo = [paper for paper in self.papers if paper["title"].startswith("Foo:")]
        self.assertEqual(len(foo), 1)
        self.assertEqual(foo[0]["links"]["code"], "https://github.com/foo/bar")
        self.assertEqual(foo[0]["links"]["website"], "https://foo.github.io")

    def test_venue_and_year(self):
        bar = next(paper for paper in self.papers if paper["title"].startswith("Bar:"))
        self.assertEqual(bar["venue"], "ICRA, 2026")
        self.assertEqual(bar["year"], 2026)
        self.assertEqual(bar["links"], {})
        self.assertIn("Paper-todo", SAMPLE)  # source still contains it
        self.assertNotIn("Paper-todo", bar["title"])

    def test_malformed_links_still_parse(self):
        paper = next(paper for paper in self.papers if paper["title"].startswith("Malformed"))
        self.assertEqual(paper["links"]["website"], "https://x.example")
        self.assertEqual(paper["links"]["code"], "https://github.com/x/y")

    def test_empty_link_is_ignored(self):
        paper = next(paper for paper in self.papers if paper["title"].startswith("Empty"))
        self.assertNotIn("paper", paper["links"])
        self.assertEqual(paper["links"]["code"], "https://github.com/e/f")

    def test_arxiv_id(self):
        survey = self.papers[0]
        self.assertEqual(survey["arxiv_id"], "2501.00001")

    def test_ids_are_stable(self):
        papers_again, _ = sync_upstream.parse_readme(SAMPLE)
        self.assertEqual([paper["id"] for paper in self.papers], [paper["id"] for paper in papers_again])


class MergeTests(unittest.TestCase):
    def test_first_seen_preserved_and_removal_detected(self):
        parsed, sections = sync_upstream.parse_readme(SAMPLE)
        old_paper = dict(parsed[0], first_seen="2025-01-01", status="active")
        vanished = {
            "id": "p-vanished",
            "title": "Vanished Paper",
            "venue": "CVPR 2020",
            "year": 2020,
            "section": "SLAM",
            "slug": "slam",
            "links": {},
            "arxiv_id": "",
            "order": 99,
            "first_seen": "2025-01-01",
            "status": "active",
            "manual": False,
            "also_in": [],
        }
        previous = {"papers": [old_paper, vanished]}
        merged, created, updated, removed = sync_upstream.merge_catalogue(
            parsed, previous, supplements=[], today="2026-11-06"
        )
        kept = next(paper for paper in merged if paper["id"] == old_paper["id"])
        self.assertEqual(kept["first_seen"], "2025-01-01")
        self.assertEqual([paper["id"] for paper in removed], ["p-vanished"])
        self.assertFalse([paper for paper in created if paper["id"] == old_paper["id"]])

    def test_manual_supplement_is_added_and_preserved(self):
        parsed, _ = sync_upstream.parse_readme(SAMPLE)
        supplement = {
            "title": "Manual Paper",
            "venue": "ECCV 2026",
            "year": 2026,
            "section": "SLAM",
            "links": {"paper": "https://arxiv.org/abs/2607.27194"},
        }
        merged, created, _, _ = sync_upstream.merge_catalogue(
            parsed, None, supplements=[supplement], today="2026-11-06"
        )
        manual = next(paper for paper in merged if paper["title"] == "Manual Paper")
        self.assertTrue(manual["manual"])
        self.assertEqual(manual["source"], "manual")
        self.assertEqual(manual["arxiv_id"], "2607.27194")

        merged_again, _, _, _ = sync_upstream.merge_catalogue(
            parsed, {"papers": merged}, supplements=[supplement], today="2026-11-07"
        )
        manual_again = next(paper for paper in merged_again if paper["title"] == "Manual Paper")
        self.assertEqual(manual_again["first_seen"], "2026-11-06")


if __name__ == "__main__":
    unittest.main()

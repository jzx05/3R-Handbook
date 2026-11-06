#!/usr/bin/env python3
"""Enforce the fixed paper-dissection format.

Every `theory/**/*_dissection.md` must follow theory/_template.md:
- required sections and markers,
- a source marker with an arXiv id,
- no unresolved TODO placeholders,
- a row in theory/README.md.

Usage:
    python3 scripts/audit_theory.py
    python3 scripts/audit_theory.py --allow-todo   # draft check
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT  # noqa: E402

REQUIRED = [
    ("快速判断", r"^## ⚡ 快速判断"),
    ("X-Ray 开场", r"^💡 \*\*X-Ray 开场\*\*"),
    ("研究全景时间线", r"^📍 \*\*研究全景时间线\*\*"),
    ("§1 核心架构/方法总览", r"^## 1\. 核心架构/方法总览"),
    ("§1.1 系统对比概览", r"^### 1\.1 系统对比概览"),
    ("§1.2 关键机制", r"^### 1\.2 关键机制"),
    ("§1.3 信息流/架构图", r"^### 1\.3 信息流/架构图"),
    ("§2 数学核心", r"^## 2\. 数学核心"),
    ("Napkin Formula", r"📌 \*\*Napkin Formula\*\*"),
    ("§3 带数字走一遍", r"^## 3\. 带数字走一遍"),
    ("§4 工程视角", r"^## 4\. 工程视角"),
    ("§5 数据与评测", r"^## 5\. 数据与评测"),
    ("§5.1 数据组成", r"^### 5\.1 数据组成"),
    ("§5.2 评测设置", r"^### 5\.2 评测设置"),
    ("§5.3 关键结果", r"^### 5\.3 关键结果"),
    ("§6 能力与失败模式", r"^## 6\. 能力与失败模式"),
    ("能做什么", r"^### 能做什么"),
    ("不能做什么", r"^### 不能做什么"),
    ("§6.1 隐含假设", r"^### 6\.1 隐含假设"),
    ("§7 与相关工作对比", r"^## 7\. 与相关工作对比"),
    ("§8 精读建议", r"^## 8\. 精读建议"),
    ("§9 面试 Q&A", r"^## 9\. 补充：面试高频 Q&A"),
    ("§10 复现清单", r"^## 10\. 补充：复现清单"),
    ("§11 来源与核查", r"^## 11\. 补充：来源与核查"),
    ("Back to Theory", r"\[← Back to Theory\]"),
]

SOURCE_RE = re.compile(r"<!--\s*source:\s*https?://arxiv\.org/abs/\d{4}\.\d{4,5}")
TODO_RE = re.compile(r"\bTODO\b")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit paper dissection format.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--allow-todo", action="store_true")
    args = parser.parse_args()

    root = Path(args.root)
    theory = root / "theory"
    index_path = theory / "README.md"
    index_text = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    errors: list[str] = []
    warnings: list[str] = []

    files = sorted(theory.glob("**/*_dissection.md"))
    if not files:
        errors.append("no theory/**/*_dissection.md files found")

    for path in files:
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")

        if not text.startswith("# "):
            errors.append(f"{rel}: first line must be a level-1 title")

        if not SOURCE_RE.search(text):
            errors.append(f"{rel}: missing '<!-- source: https://arxiv.org/abs/XXXX.XXXXX -->' marker")

        for label, pattern in REQUIRED:
            if not re.search(pattern, text, re.MULTILINE):
                errors.append(f"{rel}: missing required section '{label}' ({pattern})")

        if not args.allow_todo and TODO_RE.search(text):
            line_numbers = [str(i) for i, line in enumerate(text.splitlines(), 1) if TODO_RE.search(line)]
            errors.append(f"{rel}: unresolved TODO placeholders at lines {', '.join(line_numbers[:10])}")

        if path.name not in index_text and rel not in index_text:
            errors.append(f"{rel}: not listed in theory/README.md")

    for message in errors:
        print(f"ERROR: {message}")
    for message in warnings:
        print(f"WARN:  {message}")
    print(f"theory audit: {len(files)} dissection(s), {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

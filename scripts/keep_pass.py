#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/keep_pass.py
=====================

Applies
keep-with-next / keep-together to a built CV or letter .docx, driven by its
markdown SOURCE — build-cv.js emits plain paragraphs with no style name, so this
can't classify from the .docx alone. Prevents a page from opening on an orphaned
bullet or splitting an entry title from its date (rules/cv-build.md's pre-ship
check 5).

Requires python-docx (`pip install python-docx`) — this is the one script in the
toolchain that needs it, since it rewrites paragraph formatting in place rather
than just reading structure.

Usage: python scripts/keep_pass.py <source.md> <built.docx>
Rewrites <built.docx> in place.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def classify(line: str) -> str:
    if line.startswith("# "):
        return "bind"
    if line.startswith("@ "):
        return "bind"
    if line.startswith("## "):
        return "bind"
    if line.startswith("### "):
        return "bind"
    if re.match(r"^\*[^*].*\*$", line):
        return "bind"
    if line.startswith("- "):
        return "bullet"
    if re.match(r"^\*\*[^*]+:\*\*", line):
        return "skill"
    return "body"


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python scripts/keep_pass.py <source.md> <built.docx>", file=sys.stderr)
        return 2

    try:
        from docx import Document
    except ImportError:
        print("keep_pass: python-docx not installed. `pip install python-docx`", file=sys.stderr)
        return 3

    md_path, docx_path = Path(sys.argv[1]), Path(sys.argv[2])
    raw_lines = md_path.read_text(encoding="utf-8").splitlines()

    kinds = []
    for line in raw_lines:
        t = line.rstrip()
        if not t.strip():
            continue
        kinds.append(classify(t))

    doc = Document(str(docx_path))
    paras = doc.paragraphs
    n = min(len(paras), len(kinds))
    for i in range(n):
        p = paras[i]
        k = kinds[i]
        nxt = kinds[i + 1] if i + 1 < n else None
        p.paragraph_format.keep_together = True
        if k == "bullet":
            bind = nxt == "bullet"
        elif k == "skill":
            bind = nxt == "skill"
        elif k == "bind":
            bind = True
        else:
            bind = False
        p.paragraph_format.keep_with_next = bind
    doc.save(str(docx_path))
    print(f"keep_pass: {docx_path} ({n} paragraphs classified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

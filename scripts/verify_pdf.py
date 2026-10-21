#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/verify_pdf.py
=======================

Prints page
count plus the first and last line of each page, so a human reviewer (per
rules/cv-build.md's pre-ship check 5, "actually look at the pages") can quickly spot
a page opening on an orphaned bullet or a heading split from its date without
opening the PDF itself — though opening it is still the real check.

Requires pypdf (`pip install pypdf`).

Usage: python scripts/verify_pdf.py <file.pdf>
"""

from __future__ import annotations

import sys

# Windows consoles default to a legacy codepage (cp1252) that can't encode bullet
# glyphs (●) or curly punctuation from the rendered CV text -- reconfigure stdout to
# UTF-8 (falling back silently if the runtime is too old to support it) so this
# script's own output never crashes on the very content it's supposed to review.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/verify_pdf.py <file.pdf>", file=sys.stderr)
        return 2

    try:
        import pypdf
    except ImportError:
        print("verify_pdf: pypdf not installed. `pip install pypdf`", file=sys.stderr)
        return 3

    path = sys.argv[1]
    reader = pypdf.PdfReader(path)
    print(len(reader.pages), "pages")
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        lines = [line for line in text.split("\n") if line.strip()]
        first = lines[0][:60] if lines else ""
        last = lines[-1][:60] if lines else ""
        print(i + 1, repr(first), "->", repr(last))
    return 0


if __name__ == "__main__":
    sys.exit(main())

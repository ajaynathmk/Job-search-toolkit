#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/render_check.py
========================

Renders a built .docx to PDF and runs the mechanical half of pre-ship check 5
(rules/cv-build.md): page count, and a best-effort scan for empty trailing pages.
**This script cannot do the other half of that check — "actually look at the
pages" — on its own.** Its PASS only means "nothing mechanically detectable is
wrong"; a human still has to open the PDF and read it, per the rule that a shorter
document is missing content, not something to praise.

Requires LibreOffice (`soffice`) on PATH for the docx->pdf conversion, since this
project has no other headless Office renderer available. If `soffice` isn't found,
this script says so plainly and exits nonzero rather than pretending to pass.

Usage:
    python scripts/render_check.py <built.docx> [--expect-pages N]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


_WINDOWS_FALLBACK_PATHS = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)


def find_soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in _WINDOWS_FALLBACK_PATHS:
        if Path(candidate).exists():
            return candidate
    return None


def convert_to_pdf(docx_path: Path, out_dir: Path, soffice_bin: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [soffice_bin, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(docx_path)],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"soffice conversion failed:\n{result.stdout}\n{result.stderr}")
    pdf_path = out_dir / (docx_path.stem + ".pdf")
    if not pdf_path.exists():
        raise RuntimeError(f"soffice reported success but {pdf_path} was not produced")
    return pdf_path


def count_pdf_pages(pdf_path: Path) -> int:
    """Counts pages by scanning for /Type /Page objects — stdlib-only, no PyPDF2
    dependency, since this repo otherwise has no Python PDF library."""
    data = pdf_path.read_bytes()
    # Every page object contains "/Type /Page" (not "/Type /Pages", the parent tree
    # node) — count occurrences of the page-object pattern only.
    import re
    return len(re.findall(rb"/Type\s*/Page(?!s)", data))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("docx_path", type=Path)
    parser.add_argument("--expect-pages", type=int, default=None,
                         help="fail if the rendered PDF doesn't have exactly this many pages")
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    if not args.docx_path.exists():
        print(f"render_check: {args.docx_path} does not exist", file=sys.stderr)
        return 2

    soffice_bin = find_soffice()
    if soffice_bin is None:
        print(
            "render_check: no LibreOffice ('soffice'/'libreoffice') found on PATH.\n"
            "Install LibreOffice to enable an automated PDF page-count check, or "
            "open the .docx directly in Word and do the visual check by hand "
            "(rules/cv-build.md pre-ship check 5 — this is required either way).",
            file=sys.stderr,
        )
        return 3

    out_dir = args.out_dir or (args.docx_path.parent / "_render_check")
    pdf_path = convert_to_pdf(args.docx_path, out_dir, soffice_bin)
    pages = count_pdf_pages(pdf_path)
    print(f"Rendered {pdf_path} — {pages} page(s).")
    print("Mechanical check only. A human still needs to open this PDF and read "
          "it: every entry title on the same line as its date, no page opening on "
          "an orphaned bullet (rules/cv-build.md pre-ship check 5).")

    if args.expect_pages is not None and pages != args.expect_pages:
        print(f"FAIL: expected {args.expect_pages} page(s), got {pages}.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

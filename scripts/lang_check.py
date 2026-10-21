#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/lang_check.py
=====================

A mechanical second opinion on top of rules/language-quality.md's manual checklist:
sends a markdown source (cover-letter.md, cv.md, or any paragraph, in any language LanguageTool supports)
to the public LanguageTool API (https://languagetool.org) and reports every
grammar/spelling issue it finds. This is a real network call to a third-party
service, so only run it on drafts, never on anything containing an employer's own
confidential material.

This does NOT replace the manual grammar-checklist pass in rules/language-quality.md
-- LanguageTool catches objective errors (agreement, case, spelling, some word-
choice confusions) but has no opinion on register, naturalness, or the "perfect,
professional" bar this project sets for every document it writes.

Usage:
    python scripts/lang_check.py <file.md> [file2.md ...]     # auto-detects language
    python scripts/lang_check.py --lang en-US <file.md>        # force a language

Exit code 0 if LanguageTool found nothing, 1 if it found anything (same convention
as scripts/aicheck.py's TOTAL: 0 gate) -- but read the actual findings; not every
flagged item is a real error (LanguageTool has false positives on names/jargon).

STANDALONE ONLY -- deliberately NOT wired into scripts/ship-package.sh. It was
tried there as a required step on 2026-09-24 and removed the same day: audited
against all 76 real packages, ~88% of hits were proper-noun/domain-jargon noise,
and most of the rest were false positives specific to this genre of writing
(job-title header lines misread as sentences, English department names embedded
in German text flagged as compounds). Real, worth-fixing catches across 76
letters: about 3. Run this by hand for a second opinion on one specific letter,
never as an always-on gate, and read every hit with skepticism.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402


def _owner_name_tokens() -> list[str]:
    return [t for t in re.split(r"\s+", config.get().owner_name) if t]

API_URL = "https://api.languagetool.org/v2/check"

# The owner's own name, split into tokens -- LanguageTool's dictionary doesn't
# know it and flags every occurrence as a "possible typo", on every single letter,
# forever. Not a real finding; suppress it rather than let it drown out actual issues.
_KNOWN_PROPER_NOUNS = set(_owner_name_tokens())

# Lines that are pure contact-block noise (address, email, phone) -- checking
# these against a grammar checker only produces false positives.
_SKIP_LINE_RE = re.compile(
    r"^\s*("
    r"[\w.+-]+@[\w-]+\.[\w.-]+"          # email
    r"|\+?\d[\d ()/-]{6,}\d"             # phone number
    r"|\d{4,5}\s+\S+"                    # postal code + city
    r")\s*$"
)


def _clean_markdown(raw: str) -> str:
    """Strip this project's markdown control syntax (see cv-build.md) so the
    grammar checker sees prose, not markup. Keeps line structure so offsets in
    the report still make rough sense against the source file."""
    lines = []
    for line in raw.splitlines():
        if _SKIP_LINE_RE.match(line):
            continue
        line = re.sub(r"^#{1,3}\s*", "", line)          # # / ## / ### headings
        line = re.sub(r"^@\s*", "", line)                # @ header line
        line = re.sub(r"\s*\|\|\|.*$", "", line)          # ### Title ||| Date
        line = re.sub(r"^-\s*", "", line)                 # - bullet
        line = line.replace("**", "").replace("*", "")     # bold/italic markers
        lines.append(line)
    return "\n".join(lines)


def check_text(text: str, lang: str) -> tuple[list[dict[str, Any]], str]:
    resp = requests.post(
        API_URL,
        data={"text": text, "language": lang},
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    detected = body.get("language", {}).get("detectedLanguage", {}).get("name", lang)
    return body.get("matches", []), detected


def _is_known_proper_noun(m: dict[str, Any]) -> bool:
    ctx = m.get("context", {})
    ctx_text = ctx.get("text", "")
    offset, length = ctx.get("offset", 0), ctx.get("length", 0)
    return ctx_text[offset:offset + length] in _KNOWN_PROPER_NOUNS


def report(file_path: Path, matches: list[dict[str, Any]], detected_lang: str) -> int:
    print(f"\n=== {file_path} (detected: {detected_lang}) ===")
    suppressed = sum(1 for m in matches if _is_known_proper_noun(m))
    matches = [m for m in matches if not _is_known_proper_noun(m)]
    if not matches:
        print(f"  no issues found{f' ({suppressed} name-only hits suppressed)' if suppressed else ''}")
        return 0
    for m in matches:
        ctx = m.get("context", {})
        ctx_text = ctx.get("text", "")
        offset = ctx.get("offset", 0)
        length = ctx.get("length", 0)
        snippet = (
            ctx_text[:offset]
            + ">>>" + ctx_text[offset:offset + length] + "<<<"
            + ctx_text[offset + length:]
        )
        rule = m.get("rule", {})
        replacements = [r["value"] for r in m.get("replacements", [])[:5]]
        print(f"  [{rule.get('id', '?')} / {rule.get('category', {}).get('name', '?')}]")
        print(f"    {m.get('message', '')}")
        print(f"    ...{snippet}...")
        if replacements:
            print(f"    suggested: {', '.join(replacements)}")
    if suppressed:
        print(f"  ({suppressed} additional name-only hits suppressed)")
    return len(matches)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument(
        "--lang", default="auto",
        help="LanguageTool language code, or 'auto' (default) to let LanguageTool "
             "detect the language per file.",
    )
    args = parser.parse_args()

    total = 0
    for file_path in args.files:
        if not file_path.exists():
            print(f"SKIP (not found): {file_path}", file=sys.stderr)
            continue
        raw = file_path.read_text(encoding="utf-8")
        cleaned = _clean_markdown(raw)
        try:
            matches, detected_lang = check_text(cleaned, args.lang)
        except requests.RequestException as e:
            print(f"SKIP ({file_path}): LanguageTool API call failed: {e}", file=sys.stderr)
            continue
        total += report(file_path, matches, detected_lang)

    print(f"\nTOTAL: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())

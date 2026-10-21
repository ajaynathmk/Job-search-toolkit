#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/extract_locked_terms.py
=================================

Identifies the "cannot be changed" tokens in the owner's master CVs — tool and
software names, standards, and named methods (ALDY, Ensembl VEP, GATK4, hesim,
scikit-learn, ...) plus the master's own precise figures (6,000+, 98%, 2,504,
...). the owner's rule (rules/applications.md): tailoring may reorder and reword
everything else, but these exact strings must survive verbatim into every
tailored CV that carries the bullet they came from — "ALDY should be ALDY
only."

This is a SEEDING tool, not a live check. Run it by hand whenever
a profile/master-cv-<language>.md changes, review the output
for noise, and save the reviewed result to profile/locked_terms.json.
scripts/consistency_check.py reads that file at check time — it does not
re-derive the list itself, so a bad auto-extraction never silently changes
what gets enforced.

Usage:
    python scripts/extract_locked_terms.py > data/locked_terms.json
    python scripts/extract_locked_terms.py --diff   # show additions/removals vs.
                                                     # the existing data/locked_terms.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
MASTER_FILES = sorted(config.profile_path().glob("master-cv-*.md"))     # one master CV per language
LOCKED_TERMS_PATH = config.profile_path("locked_terms.json")

# All-caps tokens that show up structurally (headings, locale tags, generic
# words) rather than as a real tool/process name — excluded even though the
# regex below would otherwise catch them. Extend by hand if a new false
# positive shows up in --diff output.
STOPLIST = {
    "THE", "AND", "FOR", "WITH", "FROM", "INTO", "OVER", "THIS", "THAT",
    "CV", "EN", "DE", "ID", "PDF", "URL", "USA",
}

# Multi-word / hyphenated / mixed-case tool and method names a single-token
# regex can't reliably catch — curated by hand, not auto-derived. Extend
# `locked_terms` in profile/domain.json whenever the master profile gains a new named tool or method.
KNOWN_MULTIWORD_TERMS = list(config.get().domain.get("locked_terms") or [])     # profile/domain.json: tool and method names the CV must keep verbatim

# A short, code-like parenthetical is a tool/standard name (e.g. "(ALDY)",
# "(STAR, BWA-MEM, GATK4, SAMtools)"); a long, lower-case parenthetical is a
# free-text aside ("(e.g. for a strong match)") and must not be locked.
ALLCAPS_TOKEN = re.compile(r"\b[A-Z][A-Z0-9]{1,6}\b")
PAREN_CONTENT = re.compile(r"\(([^()]+)\)")
METRIC_TOKEN = re.compile(r"\b\d{1,3}(?:[.,]\d{3})+\+?\b|\b\d+%\b")


def _looks_like_a_name(part: str) -> bool:
    return bool(part) and (
        re.search(r"\d", part) or "/" in part or part.isupper() or
        (part[:1].isupper() and " " not in part and len(part) > 1)
    )


def extract_from_text(text: str) -> set[str]:
    terms: set[str] = set()

    for m in ALLCAPS_TOKEN.finditer(text):
        tok = m.group(0)
        if tok not in STOPLIST:
            terms.add(tok)

    for m in PAREN_CONTENT.finditer(text):
        for part in m.group(1).split(","):
            part = part.strip()
            if _looks_like_a_name(part):
                terms.add(part)

    for m in METRIC_TOKEN.finditer(text):
        terms.add(m.group(0))

    for term in KNOWN_MULTIWORD_TERMS:
        if term in text:
            terms.add(term)

    return terms


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diff", action="store_true",
                         help="show additions/removals vs. the existing locked_terms.json")
    args = parser.parse_args()

    all_terms: set[str] = set()
    for path in MASTER_FILES:
        if path.exists():
            all_terms |= extract_from_text(path.read_text(encoding="utf-8"))

    if args.diff:
        existing = set(json.loads(LOCKED_TERMS_PATH.read_text(encoding="utf-8"))) \
            if LOCKED_TERMS_PATH.exists() else set()
        added = sorted(all_terms - existing)
        removed = sorted(existing - all_terms)
        print(f"+ {len(added)} new term(s): {added}")
        print(f"- {len(removed)} term(s) no longer found in the masters: {removed}")
        return 0

    print(json.dumps(sorted(all_terms), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

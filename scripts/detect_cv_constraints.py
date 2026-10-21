#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/detect_cv_constraints.py
==================================

Some postings explicitly ask for a one-page CV, or say only certain
information should be included ("please keep your CV to one page", "nur eine
Seite", "kurz und relevant"). The content-regulation rule (rules/applications.md,
formerly called the no-cut rule) exists to stop tailoring from silently
deleting real content — but a posting's own explicit instruction is the one
thing that rule was never meant to override. This script is the MECHANICAL
half of handling that: it flags candidate clauses in a cached JD's text so a
Claude session can read them, decide whether they're a real constraint or
just noise, and log the decision (with the exact quoted clause) in that
package's match-report.md — which is what actually grants the exemption
(scripts/consistency_check.py reads that quote, not this script's output,
before relaxing anything). This script never decides anything on its own and
never touches the tracker's `my_notes`; it only writes the plain, freely-
overwritable `constraints` column via scripts/db.py.

Usage:
    python scripts/detect_cv_constraints.py <jd_path.md>            # just scan, print matches
    python scripts/detect_cv_constraints.py --job-id <job_id>        # scan + write to db.constraints
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# English + German clauses that name an explicit CV length or content
# restriction. Deliberately narrow and literal (a real posting's own words),
# not a heuristic guess at "this JD feels short" — a false negative here just
# means a human reads the JD anyway (the normal path); a false positive would
# license a cut that shouldn't happen, so precision matters more than recall.
_STOP = r"(?:\s+[^\s.,;()\n]+){0,5}"  # up to 5 more whole words, cut at the first clause boundary

PAGE_LIMIT_PATTERNS = [
    r"(?i)\bone[- ]page\b" + _STOP,
    r"(?i)\bsingle[- ]page\b" + _STOP,
    r"(?i)\bno more than (?:one|1) pages?\b" + _STOP,
    r"(?i)\bmax(?:imum|\.)?\s*(?:of\s+)?(?:one|1)\s*pages?\b" + _STOP,
    r"(?i)\b(?:CV|resume|Lebenslauf)\s+(?:of|to)\s+(?:one|1)\s*pages?\b" + _STOP,
    r"(?i)\bmaximal\s+eine\s+Seite\b" + _STOP,
    r"(?i)\bnicht\s+mehr\s+als\s+eine\s+Seite\b" + _STOP,
    r"(?i)\beine\s+Seite\b" + _STOP,
    r"(?i)\beinseitig(?:e[rns]?)?\b" + _STOP,
    r"(?i)\bein(?:e)?\s+DIN-?A4-?(?:Seite|Blatt)\b" + _STOP,
]

CONTENT_RESTRICTION_PATTERNS = [
    r"(?i)\bplease\s+only\s+include\b" + _STOP,
    r"(?i)\bonly\s+relevant\s+experience\b" + _STOP,
    r"(?i)\bkeep\s+(?:your\s+)?CV\s+(?:short|brief|concise)\b" + _STOP,
    r"(?i)\bshort(?:ened)?\s+(?:CV|resume)\b" + _STOP,
    r"(?i)\bbrief\s+(?:CV|resume)\b" + _STOP,
    r"(?i)\bkurz(?:e[nr]?)?\s+(?:und\s+)?(?:aussagekr[aä]ftig(?:e[nr]?)?\s+)?(?:Lebenslauf|Bewerbung)\b" + _STOP,
    r"(?i)\bnur\s+relevante\b" + _STOP,
    r"(?i)\bKurzbewerbung\b" + _STOP,
]


def _spans_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def scan_text(text: str) -> list[dict]:
    """Returns [{type, clause}] for every distinct matched clause found,
    ordered by position, with overlapping matches (the same clause caught by
    two patterns) collapsed to the longest one. `type` is 'page_limit' or
    'content_restriction' — the two categories rules/applications.md's
    content-regulation exemption recognizes."""
    raw: list[tuple[int, int, str, str]] = []  # (start, end, type, clause)
    for pattern in PAGE_LIMIT_PATTERNS:
        for m in re.finditer(pattern, text):
            raw.append((m.start(), m.end(), "page_limit", m.group(0).strip()))
    for pattern in CONTENT_RESTRICTION_PATTERNS:
        for m in re.finditer(pattern, text):
            raw.append((m.start(), m.end(), "content_restriction", m.group(0).strip()))

    raw.sort(key=lambda r: (r[0], -(r[1] - r[0])))  # earliest first, longest first at a tie
    kept: list[tuple[int, int, str, str]] = []
    for start, end, kind, clause in raw:
        if any(_spans_overlap((start, end), (ks, ke)) for ks, ke, _, _ in kept):
            continue
        kept.append((start, end, kind, clause))

    kept.sort(key=lambda r: r[0])
    return [{"type": kind, "clause": clause} for _, _, kind, clause in kept]


def scan_file(jd_path: Path) -> list[dict]:
    return scan_text(jd_path.read_text(encoding="utf-8"))


def write_to_tracker(job_id: str, findings: list[dict]) -> None:
    import db

    job = db.get_job(job_id)
    if job is None:
        raise KeyError(f"no such job: {job_id}")
    if not findings:
        return
    summary = "; ".join(f"[{f['type']}] {f['clause']}" for f in findings)
    existing = job.get("constraints") or ""
    combined = f"{existing} | CV-format clause(s) found: {summary}" if existing else \
        f"CV-format clause(s) found: {summary}"
    db.update_job(job_id, {"constraints": combined}, expected_version=job["version"])


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jd_path", nargs="?", type=Path)
    parser.add_argument("--job-id", help="also write matches to this job's tracker row (constraints column)")
    args = parser.parse_args()

    if args.job_id:
        import db
        job = db.get_job(args.job_id)
        if job is None:
            print(f"detect_cv_constraints: no such job: {args.job_id}", file=sys.stderr)
            return 2
        if not job.get("jd_path"):
            print(f"detect_cv_constraints: {args.job_id} has no jd_path yet", file=sys.stderr)
            return 2
        jd_path = Path(job["jd_path"])
        if not jd_path.is_absolute():
            jd_path = Path(__file__).resolve().parent.parent / jd_path
        findings = scan_file(jd_path)
        write_to_tracker(args.job_id, findings)
    elif args.jd_path:
        findings = scan_file(args.jd_path)
    else:
        parser.error("pass a jd_path, or --job-id <id>")
        return 2

    if not findings:
        print("no CV-format clause found")
        return 0

    print("CV-format clause(s) found — read these in context before deciding whether they're a "
          "real constraint; if so, the match report must quote the exact clause "
          "(rules/applications.md's content-regulation exemption):")
    for f in findings:
        print(f"  [{f['type']}] {f['clause']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

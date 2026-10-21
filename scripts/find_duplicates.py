#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/find_duplicates.py
===========================

Surfaces candidate duplicate tracker rows: the same underlying posting tracked
twice under different ids (found via a different board, a re-post, a mail-redirect
token vs. the resolved URL, etc.). This is the reusable form of the ad-hoc sweep
run by hand once on a real tracker, which found 7 real duplicates among 224 rows.

This script only SURFACES candidates -- it never merges anything itself. A fuzzy
employer+title match is a good way to find candidates, a bad way to decide: two
roles at the same employer with a shared title template (e.g. BMW's many
"Werkstudent Data Science" openings across departments) are false positives far
more often than not. Every candidate this script prints still needs its actual
URL or JD text read before folding one into the other, exactly as the 2026-09-29
sweep did by hand.

Extra value over a plain title match: when two candidates in the same group
disagree on approval/status (e.g. one is `blocked`, the other `applied`), that is
flagged as a SCORING CONFLICT -- the same JD was judged two different ways, which
is worth investigating on its own even if the "duplicate" call turns out wrong,
since it can mean a scoring/blocking bug (one posting scored two different ways).

Usage:
    python scripts/find_duplicates.py              # print all candidate groups
    python scripts/find_duplicates.py --min-ratio 0.7   # stricter title match
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

# Windows consoles default to cp1252, which can't encode every employer/title
# string in the tracker (accents, en-dashes) -- never let a print crash the scan.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db as jobdb  # noqa: E402

_EMPLOYER_STOPWORDS = re.compile(
    r"\b(gmbh|ag|se|group|holding|deutschland|europe|inc|co\.?|kg|the)\b"
)


def norm_employer(e: str | None) -> str:
    e = (e or "").lower()
    e = _EMPLOYER_STOPWORDS.sub("", e)
    e = re.sub(r"[^a-z0-9]+", " ", e)
    return e.strip()


def norm_title(t: str | None) -> str:
    t = (t or "").lower()
    t = re.sub(r"\(.*?\)", "", t)  # drop (m/w/d) etc, which pads similarity noise
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return t.strip()


def find_groups(jobs: list[dict], min_ratio: float) -> list[list[dict]]:
    by_emp: dict[str, list[dict]] = {}
    for j in jobs:
        by_emp.setdefault(norm_employer(j.get("employer")), []).append(j)

    groups = []
    for ne, items in by_emp.items():
        if len(items) < 2 or not ne:
            continue
        used = set()
        for i in range(len(items)):
            if i in used:
                continue
            cluster = [items[i]]
            ti = norm_title(items[i]["title"])
            for k in range(i + 1, len(items)):
                if k in used:
                    continue
                tk = norm_title(items[k]["title"])
                if SequenceMatcher(None, ti, tk).ratio() >= min_ratio:
                    cluster.append(items[k])
                    used.add(k)
            if len(cluster) > 1:
                used.add(i)
                groups.append(cluster)
    return groups


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-ratio", type=float, default=0.55,
                         help="title-similarity threshold, 0-1 (default 0.55)")
    args = parser.parse_args()

    jobs = jobdb.list_jobs()
    groups = find_groups(jobs, args.min_ratio)

    print(f"Scanned {len(jobs)} rows, found {len(groups)} candidate group(s).\n")
    print("Every candidate below still needs its actual URL/JD text read before "
          "folding -- this is a surfacing tool, not a merge tool.\n")

    for cluster in groups:
        statuses = {j.get("status") for j in cluster}
        approvals = {j.get("approval") for j in cluster}
        conflict = len(statuses) > 1 or len(approvals) > 1
        tag = " ** SCORING CONFLICT -- same-ish JD judged differently **" if conflict else ""
        print(f"--- {cluster[0]['employer']}{tag} ---")
        for j in cluster:
            print(f"  {j['id']} | {j['title']!r} | status={j.get('status')} "
                  f"approval={j.get('approval')} pkg={j.get('package_path')}")
        print()


if __name__ == "__main__":
    main()

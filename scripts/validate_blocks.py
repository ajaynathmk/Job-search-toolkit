#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/validate_blocks.py
==========================

Flags rows with approval="blocked" whose `blocked_reason` does not look like one of the walls this profile actually has (the walls of the region pack,
the domain file and the profile, plus a stated language level above the owner's own). A block that rests on a loose reason (an alternative the posting
also accepts, a "preferred" qualification, a stale note) hides a role the owner could apply to, so this narrows "every blocked row" down to "these N look
wrong, read them first".

The rule it enforces: a wall is a requirement the owner cannot meet, quoted from the full JD. A requirement listing several alternative fields or
qualifications ("A, B or C") is a preference to score, not a wall.

It never unblocks anything itself: a flagged row still needs its JD read and a real judgment (scripts/analyze.py show <id>, then review).

Usage:
    python scripts/validate_blocks.py
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import db as jobdb  # noqa: E402

# A stated language level is a wall whenever the profile's own level is below it, however it is phrased ("C1", "mind. C1", "C1-level").
_LEVEL = re.compile(r"\b(?:c1|c2|b2|native|mother tongue|muttersprache|langue maternelle|lengua materna|madrelingua)\b", re.I)
_ALTERNATIVES = re.compile(r"\b(?:or|oder|ou|o|of)\b", re.I)


def _wall_patterns() -> list[re.Pattern]:
    out = []
    for w in config.get().walls:
        try:
            out.append(re.compile(w["re"], re.I | re.S))
        except (re.error, KeyError):
            continue
    return out


def looks_suspicious(reason: str, patterns: list[re.Pattern]) -> str | None:
    if not reason or not reason.strip():
        return "blocked with no reason recorded"
    if any(p.search(reason) for p in patterns):
        return None                                   # one of this profile's own walls: leave it alone
    if _LEVEL.search(reason):
        return None                                   # a language-level wall; analyze.py checks it against the profile
    if re.search(r"recorded block|first full read", reason, re.I):
        return None
    if _ALTERNATIVES.search(reason) and len(reason) < 200:
        return "the reason lists alternatives; a list of acceptable options is a preference to score, not a wall"
    return "the reason does not match any wall in the profile, the domain or the region pack: read the JD before leaving it blocked"


def main() -> int:
    patterns = _wall_patterns()
    rows = [j for j in jobdb.list_jobs() if j.get("approval") == "blocked" or j.get("verdict") == "BLOCKED"]
    flagged = []
    for j in rows:
        why = looks_suspicious(j.get("blocked_reason") or "", patterns)
        if why:
            flagged.append((j["id"], j.get("employer"), j.get("title"), why))
    print(f"{len(rows)} blocked rows, {len(flagged)} look wrong:")
    for ref, emp, title, why in flagged:
        print(f"  {ref}  {emp} | {title}\n      {why}")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/rank_skills.py
=======================

The mechanical half of applications.md Step 2: sort a role's keywords[] by
tier (must>preferred>context), then frequency (desc), then source
(hardReqs>softReqs>body) — exactly as applications.md specifies, and NEVER
recomputed by hand. This script does the SORT and the exact-string match against
a structured skills file; it deliberately does NOT attempt the semantic met/
partial/gap judgment call (whether a skill genuinely evidences a keyword beyond an
exact string/alias match) — that's Claude's job against master-profile.md's honesty
notes, not a regex's.

Input: a structured skills file (default data/master_profile_skills.json), a JSON
list of {"id": "SKL-1", "category": "...", "text": "...", "aliases": [...]}. This
is a hand-maintained mirror of profile/master-profile.md's Skills section (see
a known gap: keep it in sync by
hand when the master profile changes).

A second mode, `check <application-folder>`, is `cv-build.md`'s "must-tier
keyword coverage check" — wired into `ship-package.sh` on 2026-09-27. It was
previously documented as "a hard stop" with nothing actually enforcing it: no
script call in the gate, and no application folder had ever saved a
keywords.json artifact. `check` closes that gap: it resolves the folder back
to its tracker row (by `package_path`), reads that row's `keywords[]`, and for
every `must`-tier keyword the profile genuinely supports (an exact/alias match
in the skills file), confirms the term or its matched skill's alias actually
appears in the folder's `cv.md` text. A `must`-tier keyword with NO skills-file
match at all is a genuine gap, not a failure (cv-build.md is explicit about
this distinction) — it's only reported, never counted in the exit code.

Usage:
    python scripts/rank_skills.py --keywords keywords.json [--skills data/master_profile_skills.json]
    python scripts/rank_skills.py --job-id li-1234567 [--skills ...]   # reads keywords from db/tracker.db
    python scripts/rank_skills.py check <application-folder>            # the ship-gate mode
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
DEFAULT_SKILLS_FILE = config.profile_path("master_profile_skills.json")

TIER_ORDER = {"must": 0, "preferred": 1, "context": 2}
SOURCE_ORDER = {"hardReqs": 0, "softReqs": 1, "body": 2}


def sort_keywords(keywords: list[dict]) -> list[dict]:
    """applications.md Step 2's mechanical sort. Decides order only, never inclusion."""
    return sorted(
        keywords,
        key=lambda k: (
            TIER_ORDER.get(k.get("tier"), 99),
            -int(k.get("frequency", 0)),
            SOURCE_ORDER.get(k.get("source"), 99),
        ),
    )


def load_skills(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _phrase_contains(haystack: str, needle: str) -> bool:
    """Word-boundary phrase containment, not raw character substring. A real
    bug found 2026-09-27 while testing the must-tier coverage check: a bare
    `needle in haystack` let a short alias like "r" (the R language) match
    inside almost any English word ("unsupported", "regulatory", ...), which
    corrupted both this function's own matches and, downstream, the coverage
    check built on it. `needle` must appear as a whole word/phrase — bounded
    by non-word characters or the string ends — not merely as a character
    run inside something longer."""
    needle = needle.strip()
    if not needle:
        return False
    return re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack, re.IGNORECASE) is not None


def match_keyword_to_skills(keyword: dict, skills: list[dict]) -> list[str]:
    """Exact string/alias match only (case-insensitive, word-boundary — see
    _phrase_contains). Returns matching skill ids. This is deliberately
    mechanical — it does not upgrade a fuzzy or semantic match to "met";
    applications.md Step 2 forbids upgrading partial to met, and a script
    guessing at semantic equivalence would violate that in the other
    direction."""
    term = keyword.get("term", "").strip()
    if not term:
        return []
    hits = []
    for skill in skills:
        candidates = [skill.get("text", "")] + skill.get("aliases", [])
        if any(_phrase_contains(c, term) or _phrase_contains(term, c) for c in candidates if c):
            hits.append(skill.get("id", "?"))
    return hits


def _find_job_for_folder(folder: Path):
    """Resolves an applications/ folder back to its tracker row via
    package_path — the only link between the two, since a folder's name
    (<date>_<Employer>_<role-slug>) is not the tracker's id scheme. Matches on
    the folder's basename since package_path has been stored inconsistently
    (relative in most rows, one absolute Windows path seen in the wild) —
    basename comparison is robust to both."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import db as jobdb

    target = folder.resolve().name
    for job in jobdb.list_jobs(limit=5000):
        pp = job.get("package_path")
        if pp and Path(pp).name == target:
            return job
    return None


def _appears_verbatim(term: str, text: str) -> bool:
    """Case-insensitive, word-boundary match — a substring hit inside an
    unrelated longer word doesn't count (same convention as
    consistency_check.py's locked-term check). Same underlying test as
    _phrase_contains above; kept as a separate name here since the argument
    order reads more naturally at each call site."""
    return _phrase_contains(text, term)


def check_cv_coverage(cv_text: str, keywords: list[dict], skills: list[dict]) -> dict:
    """cv-build.md's must-tier keyword coverage check. Returns:
      - missing_in_cv: must-tier keywords the profile DOES support (an exact/
        alias match exists) but that don't actually appear, verbatim, anywhere
        in cv_text — the real hard stop.
      - gaps: must-tier keywords with NO skills-file match at all — a genuine
        gap, reported for the match report's honesty log, never a failure.

    Two real bugs caught before this shipped (2026-09-27), both found with a
    synthetic test (a CV missing "Docker" entirely, alongside a keyword list
    where Docker and Python share one skills-file row):

    1. The first version checked the keyword's term against the MATCHED
       SKILL'S WHOLE ALIAS LIST, not just the keyword's own term. Since one
       skills-file row bundles many distinct tools together (SKL-1 alone
       covers Python, R, Docker, Git, Conda, ...), "Docker" was marked
       present the moment ANY sibling alias of the same row — "Python" —
       showed up anywhere in the CV, regardless of whether Docker itself
       was ever mentioned.
    2. The fix for #1 tried to narrow this to "only the alias(es) this
       specific term matched", using the same substring containment
       match_keyword_to_skills() uses for the coarser gap check above. That
       broke the same way for a different reason: substring containment is
       unreliable for a short alias like "r" (the R language) — "r" is a
       literal substring of "docker" itself, so "Docker" matched the "r"
       alias defined for an unrelated keyword and "r" then matched the "R"
       already in the CV, letting a missing Docker mention through again.

    Both failure modes are the same shape: trying to expand a keyword into
    "equivalent" alias strings via substring matching is too fragile for a
    hard-stop check on data this loosely structured (one row = many
    unrelated short tokens). The fix is to stop trying — check ONLY the
    keyword's own term, exactly as scored, case-insensitive and
    word-bounded. This can false-positive on a genuine acronym mismatch
    (JD says "artificial intelligence", CV only ever writes "AI") — that's
    an acceptable, safer failure mode for a hard-stop gate than the
    opposite: a real miss shipping silently, which is what both bugs above
    actually did."""
    missing_in_cv, gaps = [], []
    for kw in sort_keywords([k for k in keywords if k.get("tier") == "must"]):
        skill_ids = match_keyword_to_skills(kw, skills)
        if not skill_ids:
            gaps.append(kw)
            continue
        if not _appears_verbatim(kw.get("term", ""), cv_text):
            missing_in_cv.append({**kw, "matching_skill_ids": skill_ids})
    return {"missing_in_cv": missing_in_cv, "gaps": gaps}


def build_report(keywords: list[dict], skills: list[dict]) -> dict:
    ranked = sort_keywords(keywords)
    rows = []
    gaps = []
    for kw in ranked:
        matches = match_keyword_to_skills(kw, skills)
        row = {**kw, "matching_skill_ids": matches, "status": "evidence_found" if matches else "no_exact_match"}
        rows.append(row)
        if not matches and kw.get("tier") == "must":
            gaps.append(kw)
    return {"ranked_keywords": rows, "must_tier_gaps": gaps}


def _run_check(folder: Path, skills_path: Path) -> int:
    """The ship-gate mode: cv-build.md's must-tier keyword coverage check,
    resolved against a real application folder instead of a bare keywords
    list. Exit code (and TOTAL) counts only missing_in_cv — a genuine gap
    (no skills-file match at all) is reported but never a failure, per
    cv-build.md's explicit distinction."""
    cv_path = folder / "cv.md"
    if not cv_path.exists():
        print(f"rank_skills check: {cv_path} does not exist", file=sys.stderr)
        return 2

    job = _find_job_for_folder(folder)
    if job is None:
        print(f"rank_skills check: no tracker row's package_path points at {folder.name} "
              f"— must-tier check skipped (not a failure; this is a bookkeeping gap, "
              f"not a content defect)")
        return 0

    keywords = job.get("keywords") or []
    if not keywords:
        print(f"rank_skills check: {job['id']} has no keywords[] recorded — must-tier "
              f"check skipped (the JD-scoring step never populated it for this role; "
              f"not a failure, but the coverage check did not actually run)")
        return 0

    skills = load_skills(skills_path)
    if not skills:
        print(f"rank_skills check: no skills loaded from {skills_path} — every "
              f"must-tier keyword would show as a gap, which is almost certainly wrong; "
              f"refusing to run rather than report misleading gaps", file=sys.stderr)
        return 2

    cv_text = cv_path.read_text(encoding="utf-8")
    result = check_cv_coverage(cv_text, keywords, skills)

    if result["gaps"]:
        print("Must-tier keyword(s) with no skills-file match at all — genuine gaps, "
              "log these against their pillar in master-profile.md, not a failure:")
        for kw in result["gaps"]:
            print(f"  - {kw.get('term')} (pillar={kw.get('pillar', '?')})")

    for kw in result["missing_in_cv"]:
        print(f"{cv_path.relative_to(REPO_ROOT)}  [must_tier_missing]  "
              f"{kw.get('term')!r} is supported by the profile "
              f"(skill(s) {kw.get('matching_skill_ids')}) but does not appear anywhere "
              f"in this CV's rendered text")

    print(f"\nTOTAL: {len(result['missing_in_cv'])}")
    return len(result["missing_in_cv"])


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    if len(sys.argv) > 1 and sys.argv[1] == "check":
        check_parser = argparse.ArgumentParser(prog="rank_skills.py check")
        check_parser.add_argument("folder", type=Path)
        check_parser.add_argument("--skills", type=Path, default=DEFAULT_SKILLS_FILE)
        args = check_parser.parse_args(sys.argv[2:])
        if not args.folder.is_dir():
            print(f"rank_skills check: {args.folder} is not a directory", file=sys.stderr)
            return 2
        return _run_check(args.folder.resolve(), args.skills)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keywords", type=Path, help="JSON file: a list of keyword records")
    parser.add_argument("--job-id", help="read keywords[] from this job's row in db/tracker.db instead")
    parser.add_argument("--skills", type=Path, default=DEFAULT_SKILLS_FILE)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.keywords and not args.job_id:
        parser.error("pass --keywords <file.json> or --job-id <id>, or `check <application-folder>`")

    if args.job_id:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import db as jobdb  # noqa: E402
        row = jobdb.get_job(args.job_id)
        if row is None:
            print(f"rank_skills: no such job {args.job_id!r} in db/tracker.db", file=sys.stderr)
            return 2
        keywords = row.get("keywords") or []
    else:
        keywords = json.loads(args.keywords.read_text(encoding="utf-8"))

    skills = load_skills(args.skills)
    if not skills:
        print(f"rank_skills: warning: no skills loaded from {args.skills} "
              f"(file missing or empty) — every keyword will show no_exact_match", file=sys.stderr)

    report = build_report(keywords, skills)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    print("Ranked keywords (tier -> frequency desc -> source):")
    for row in report["ranked_keywords"]:
        matches = ", ".join(row["matching_skill_ids"]) or "-"
        print(f"  [{row.get('tier','?'):9}] freq={row.get('frequency','?'):<3} "
              f"{row.get('term',''):40} matches: {matches}")

    if report["must_tier_gaps"]:
        print("\nMust-tier keywords with NO exact-string match against the skills "
              "file (log these against their pillar in master-profile.md's "
              "recurring-gaps table if a human review confirms they're a genuine gap):")
        for kw in report["must_tier_gaps"]:
            print(f"  - {kw.get('term')} (pillar={kw.get('pillar','?')})")

    return 0


if __name__ == "__main__":
    sys.exit(main())

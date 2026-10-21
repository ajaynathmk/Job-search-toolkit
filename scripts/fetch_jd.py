#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/fetch_jd.py
=====================

The JD-first rule (rules/runbook.md, rules/applications.md), enforced
end-to-end for one role in a single script, so the exact defect
an early audit found — 70 of 98 rows marked
`jd_read=1` with only a distilled summary on the tracker row and no saved
copy of the JD text anywhere — cannot happen again. The tracker write only
ever happens AFTER the file is confirmed on disk.

What it does, in order, for one job_id:
  1. Refuses to run if the row already has `jd_read=1` — a JD is fetched
     exactly once, ever. The one licensed exception is --recheck.
  2. Fetches the JD text AND verifies the link in the same page open
     (scripts/link_verify.py's verify_url — confirms both employer and role
     title appear in the page text; never trusts a 200 status alone).
  3. On success: saves the raw text to
     jd/<Employer>_<role-slug>/description.md, mechanically scans it for a
     CV-format clause (scripts/detect_cv_constraints.py — "one page", "nur
     eine Seite", etc.), THEN writes jd_read=1, jd_fetched_at, jd_path, url,
     url_verified, and (if any clause was found) constraints back to the
     tracker row — the write is the last step, never the first, and never
     happens without the file existing.
  4. On failure: leaves jd_read=0, records exactly what was tried in `notes`
     (never `my_notes`), and the row stays a candidate for the one retry
     rules/runbook.md's Step 7 allows for an unreadable survivor.

This is the mechanical implementation of rules/runbook.md's Step 7 for a
single role; scripts/intake.py's step_6_7_jd_read_and_link_verify
calls it once per candidate id found during Steps 4-6's search.

Usage:
    python scripts/fetch_jd.py <job_id>
    python scripts/fetch_jd.py <job_id> --url <candidate_url>   # a link found this run
    python scripts/fetch_jd.py <job_id> --recheck                # the one licensed re-read
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402
from link_verify import verify_url  # noqa: E402
from detect_cv_constraints import scan_text  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
JD_ROOT = REPO_ROOT / "jd"

# A real posting is never this short — guards against caching a stub/login page
# that happened to pass the employer+title text match.
MIN_JD_LENGTH = 200


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip()
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-") or "role"


def jd_folder(employer: str, title: str) -> Path:
    """rules/runbook.md's JD-first folder convention: jd/<Employer>_<role-slug>/,
    named the same way as the eventual applications/ package but with no date
    prefix, so anything else about the job later belongs in the same folder."""
    return JD_ROOT / f"{slugify(employer)}_{slugify(title)}"


def fetch_and_cache(job_id: str, *, url_override: str | None = None,
                     recheck: bool = False, headed: bool = False) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise KeyError(f"no such job: {job_id}")

    if job.get("jd_read") and not recheck:
        raise RuntimeError(
            f"{job_id} already has jd_read=1 (jd_path={job.get('jd_path')}) — a JD "
            f"is fetched exactly once, ever. Pass --recheck if this is the one "
            f"licensed re-read (rules/runbook.md)."
        )

    url = url_override or job.get("url")
    if not url:
        raise ValueError(f"{job_id} has no url to fetch")

    result = verify_url(url, job["employer"], job["title"], headed=headed)
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    text_len = len(result.text or "")
    if not result.ok or text_len < MIN_JD_LENGTH:
        if result.ok:
            reason = f"link verified but extracted text too short ({text_len} chars) — not saved"
        else:
            reason = result.reason
        db.update_job(job_id, {
            "notes": f"[jd fetch {today_date}] failed: {reason} (url tried: {url})",
        }, expected_version=job["version"])
        return {"ok": False, "reason": reason}

    folder = jd_folder(job["employer"], job["title"])
    folder.mkdir(parents=True, exist_ok=True)
    jd_path = folder / "description.md"
    jd_path.write_text(
        f"# {job['title']} — {job['employer']}\n\n"
        f"Source: {result.final_url or url}\n"
        f"Fetched: {now_iso}\n\n"
        f"---\n\n{result.text.strip()}\n",
        encoding="utf-8",
    )
    # Only now that the file demonstrably exists does the tracker write
    # happen — the mechanical fix for that audit's defect
    # (jd_read=1 with no saved file behind it).
    if not jd_path.exists():
        raise RuntimeError(f"wrote {jd_path} but it does not exist immediately after — aborting the tracker write")

    # Mechanical scan for a CV-format clause (one page / restricted content) —
    # rules/applications.md's content-regulation exemption. This only flags
    # candidates in `constraints`; it never decides on its own that a cut is
    # allowed, and the actual exemption still requires a Claude session to
    # quote the clause in match-report.md before consistency_check.py honors it.
    constraint_hits = scan_text(result.text)
    changes = {
        "jd_read": 1,
        "jd_fetched_at": now_iso,
        "jd_path": str(jd_path.relative_to(REPO_ROOT)),
        "url": result.final_url or url,
        "url_verified": today_date,
    }
    if constraint_hits:
        summary = "; ".join(f"[{f['type']}] {f['clause']}" for f in constraint_hits)
        existing = job.get("constraints") or ""
        changes["constraints"] = (f"{existing} | CV-format clause(s) found: {summary}"
                                   if existing else f"CV-format clause(s) found: {summary}")

    db.update_job(job_id, changes, expected_version=job["version"])

    return {"ok": True, "jd_path": str(jd_path.relative_to(REPO_ROOT)),
             "constraint_hits": constraint_hits}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    parser.add_argument("--url", help="a candidate url found this run, overriding the stored one")
    parser.add_argument("--recheck", action="store_true",
                         help="the one licensed re-read of an already-cached JD")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    try:
        result = fetch_and_cache(args.job_id, url_override=args.url,
                                  recheck=args.recheck, headed=args.headed)
    except (KeyError, ValueError, RuntimeError) as exc:
        print(f"fetch_jd: {exc}", file=sys.stderr)
        return 2

    if result["ok"]:
        print(f"OK — saved {result['jd_path']}, jd_read=1")
        if result.get("constraint_hits"):
            print("  CV-format clause(s) found — read these before tailoring "
                  "(rules/applications.md's content-regulation exemption):")
            for f in result["constraint_hits"]:
                print(f"    [{f['type']}] {f['clause']}")
        return 0
    print(f"FAILED — {result['reason']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

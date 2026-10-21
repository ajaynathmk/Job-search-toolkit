#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JD-first for PDF postings (fetch_jd.py's browser verifier cannot read PDF text).

Downloads the row's url, extracts the PDF text with pypdf, checks that BOTH the
employer and the title strings appear in that text (same test as link_verify), saves
jd/<Employer>_<role-slug>/description.md, and only then writes jd_read=1, jd_path,
url_verified. A row whose PDF does not contain both strings is left untouched.

Usage: python scripts/cache_pdf_jd.py <job_id> [--employer-text "string in PDF"] [--title-text "string in PDF"]
"""
import argparse
import io
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402
from detect_cv_constraints import scan_text  # noqa: E402
from fetch_jd import MIN_JD_LENGTH, REPO_ROOT, jd_folder  # noqa: E402


def norm(s):
    return re.sub(r"\s+", " ", s.replace("­", "")).lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id")
    ap.add_argument("--employer-text")
    ap.add_argument("--title-text")
    a = ap.parse_args()
    job = db.get_job(a.job_id)
    if job is None:
        sys.exit("no such job")
    if job.get("jd_read"):
        sys.exit("already jd_read=1: a JD is fetched once")
    r = requests.get(job["url"], timeout=40, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages)
    n = norm(text)
    emp = norm(a.employer_text or job["employer"])
    tit = norm(a.title_text or job["title"])
    if len(text) < MIN_JD_LENGTH or emp not in n or tit not in n:
        sys.exit(f"FAILED: len={len(text)} employer_found={emp in n} title_found={tit in n}")
    folder = jd_folder(job["employer"], job["title"])
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "description.md"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(f"# {job['title']} — {job['employer']}\n\nSource: {job['url']}\nFetched: {now}\n"
                    f"Extracted from PDF with pypdf.\n\n---\n\n{text.strip()}\n", encoding="utf-8")
    assert path.exists()
    changes = {"jd_read": 1, "jd_fetched_at": now, "jd_path": str(path.relative_to(REPO_ROOT)),
               "url_verified": now[:10]}
    hits = scan_text(text)
    if hits:
        changes["constraints"] = "; ".join(f"[{h['type']}] {h['clause']}" for h in hits)
    db.update_job(a.job_id, changes, expected_version=job["version"])
    print("OK saved", path)


if __name__ == "__main__":
    main()

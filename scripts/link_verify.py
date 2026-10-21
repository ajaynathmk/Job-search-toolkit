#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/link_verify.py
========================

THE LINK RULE (rules/runbook.md), mechanically enforced instead of trusted by
convention: a url on a tracker card is only ever written back after THIS script
has opened it in THIS run, read the visible page text, and confirmed it names
both the employer and a matching role title. A 200 status is never enough on
its own — a search-results page, a login wall, or a differently-titled role can
all return 200.

Two fetch routes, chosen by domain:
  - linkedin.com / xing.com — blocked by robots.txt for a plain HTTP fetch
    (rules/runbook.md's "one hard never" on both domains) — routed through
    scripts/browser_jd_reader.py's Playwright context instead.
  - everything else (employer careers sites, ATS platforms, a board post that
    exposes a per-posting URL) — a plain HTTP GET via `requests`.

Budget (rules/runbook.md): 3 page opens per role, one fallback host. The
fallback host tried here is the row's own `apply_url` when it differs from
`url` — this script verifies an already-identified URL; finding a *new*
candidate URL via the employer-site -> ATS -> board search order is
scripts/fetch_jd.py's job (and the reading subagent's, during a live search).

Usage:
    python scripts/link_verify.py <job_id>                # verify the row's stored url
    python scripts/link_verify.py <job_id> --url <url>     # verify a candidate url instead
    python scripts/link_verify.py --stale-days 30          # re-verify every open row
                                                            # whose url_verified is
                                                            # missing or older than N days
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402

# rules/runbook.md's "one hard never" — a plain HTTP fetch is blocked by
# robots.txt on both domains, for any purpose, ever.
BROWSER_ONLY_DOMAINS = ("linkedin.com", "xing.com")

# rules/runbook.md's link-check budget: 3 page opens per role, one fallback host.
MAX_ATTEMPTS = 3

# Signals that a 200-status page is not actually the posting: a search-results
# page, a login wall, or a "this posting is gone" page dressed up as 200 — THE
# LINK RULE's "never stored" list, checked mechanically instead of by eye.
DEAD_SIGNS = re.compile(
    r"job (?:has been removed|is no longer available|posting has expired)|"
    r"(?:this )?position (?:has been filled|is no longer)|"
    r"page (?:not found|doesn.t exist|could not be found)|"
    r"diese (?:stelle|anzeige) (?:ist nicht mehr verf|wurde bereits|existiert nicht)|"
    r"sign in to (?:see|view|continue)|please log in|anmelden, um|bitte melden sie sich an|"
    r"\b0 (?:jobs|results|stellen|treffer) (?:found|gefunden)\b",
    re.IGNORECASE,
)


@dataclass
class VerifyResult:
    ok: bool
    url: str
    final_url: str | None
    status_code: int | None
    matched_employer: bool
    matched_title: bool
    reason: str
    text: str | None = None


def _domain(url: str) -> str:
    return urlsplit(url).netloc.lower()


def _requires_browser(url: str) -> bool:
    d = _domain(url)
    return any(bd in d for bd in BROWSER_ONLY_DOMAINS)


def _strip_html(html: str) -> str:
    """Cheap tag stripper — good enough for a keyword-presence check, not a
    real renderer. Script/style contents are dropped first so they never count
    as visible page text (a page that merely *mentions* the employer name in a
    tracking script shouldn't pass)."""
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = re.sub(r"&nbsp;", " ", html)
    html = re.sub(r"\s+", " ", html)
    return html.strip()


def _fetch_plain(url: str, timeout: int = 15) -> tuple[int | None, str | None, str | None]:
    """Plain HTTP GET for any host other than linkedin.com/xing.com."""
    import requests

    try:
        resp = requests.get(
            url, timeout=timeout, allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; job-tracker-link-check/1.0)"},
        )
    except requests.RequestException as exc:
        return None, None, f"request failed: {exc}"

    return resp.status_code, resp.url, _strip_html(resp.text)


def _fetch_browser(url: str, headed: bool = False) -> tuple[int | None, str | None, str | None]:
    """LinkedIn/Xing route — Playwright only, per rules/runbook.md's one hard
    'never' on a plain fetch against either domain."""
    import browser_jd_reader as bjr
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx, cleanup = bjr._launch(p, headed=headed, user_data_dir=None)
        try:
            page = ctx.new_page()
            resp = page.goto(url, timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            text = page.inner_text("body")
            status = resp.status if resp else None
            return status, page.url, text
        except Exception as exc:  # noqa: BLE001
            return None, None, f"browser fetch failed: {exc}"
        finally:
            cleanup()


def verify_url(url: str, employer: str, title: str, *, headed: bool = False) -> VerifyResult:
    """Open the URL now, read its text, and confirm it names both the employer
    and the role. Never trusts a 200 status alone (rules/runbook.md)."""
    if _requires_browser(url):
        status, final_url, text = _fetch_browser(url, headed=headed)
    else:
        status, final_url, text = _fetch_plain(url)

    if text is None:
        return VerifyResult(False, url, final_url, status, False, False,
                             f"fetch failed: {status if isinstance(status, str) else 'no response'}")
    if status is not None and status >= 400:
        return VerifyResult(False, url, final_url, status, False, False,
                             f"dead: HTTP {status}", text=text)

    lower = text.lower()
    if DEAD_SIGNS.search(lower):
        return VerifyResult(False, url, final_url, status, False, False,
                             "page matched a dead/login-wall/search-results signature", text=text)

    matched_employer = employer.lower() in lower
    title_words = [w for w in re.findall(r"\w+", title) if len(w) > 3]
    matched_title = bool(title_words) and (
        sum(w.lower() in lower for w in title_words) >= max(1, len(title_words) // 2)
    )

    ok = matched_employer and matched_title
    reason = ("verified: employer and role both found in page text" if ok else
              f"not verified: employer_found={matched_employer} title_found={matched_title}")
    return VerifyResult(ok, url, final_url, status, matched_employer, matched_title, reason, text=text)


def _candidate_urls(primary_url: str, job: dict) -> list[str]:
    """The stored url, plus the row's own apply_url as the one documented
    fallback host, if it differs — rules/runbook.md's "3 page opens per role,
    one fallback host" budget."""
    urls = [primary_url]
    fallback = job.get("apply_url")
    if fallback and fallback != primary_url:
        urls.append(fallback)
    return urls


def verify_job(job_id: str, *, url_override: str | None = None, headed: bool = False) -> VerifyResult:
    """Verifies one tracker row's url and writes the result straight back:
    url_verified (today) + the possibly-updated final url on success; a
    cleared url_verified and a `notes` entry naming exactly what was tried on
    failure — never a raw guess, never silence."""
    job = db.get_job(job_id)
    if job is None:
        raise KeyError(f"no such job: {job_id}")
    url = url_override or job.get("url")
    if not url:
        raise ValueError(f"{job_id} has no url to verify")

    result = None
    tried: list[str] = []
    for attempt_url in _candidate_urls(url, job):
        if len(tried) >= MAX_ATTEMPTS:
            break
        tried.append(attempt_url)
        result = verify_url(attempt_url, job["employer"], job["title"], headed=headed)
        if result.ok:
            break

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if result and result.ok:
        db.update_job(job_id, {
            "url": result.final_url or result.url,
            "url_verified": today,
        }, expected_version=job["version"])
    else:
        db.update_job(job_id, {
            "url_verified": None,
            "notes": (f"[link check {today}] not verified after {len(tried)} attempt(s): "
                      f"{tried}. Last reason: {result.reason if result else 'no candidate url'}"),
        }, expected_version=job["version"])
    return result


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", nargs="?")
    parser.add_argument("--url", help="verify this url instead of the row's stored url")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--stale-days", type=int,
                         help="instead of one job_id, re-verify every open row whose "
                              "url_verified is missing or older than N days")
    args = parser.parse_args()

    if args.stale_days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.stale_days)).strftime("%Y-%m-%d")
        rows = [j for j in db.list_jobs(status="open")
                if not j.get("url_verified") or j["url_verified"] < cutoff]
        print(f"{len(rows)} row(s) need re-verification (no url_verified, or older than {cutoff})")
        exit_code = 0
        for job in rows:
            try:
                result = verify_job(job["id"], headed=args.headed)
            except (KeyError, ValueError) as exc:
                print(f"  {job['id']}: SKIP — {exc}")
                continue
            status = "OK" if result.ok else "FAIL"
            print(f"  {job['id']} ({job['employer']}): {status} — {result.reason}")
            if not result.ok:
                exit_code = 1
        return exit_code

    if not args.job_id:
        parser.error("pass a job_id, or --stale-days N")

    result = verify_job(args.job_id, url_override=args.url, headed=args.headed)
    print(f"{'OK' if result.ok else 'FAIL'}: {result.reason}")
    print(f"  url tried: {result.url}")
    print(f"  final url: {result.final_url}")
    print(f"  status: {result.status_code}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())

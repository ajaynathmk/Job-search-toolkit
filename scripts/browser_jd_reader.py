#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/browser_jd_reader.py
=============================

Replaces the claude.ai browser pane for reading LinkedIn/Xing job descriptions and
verifying links (rules/runbook.md's JD_READ_ROUTES). A plain HTTP fetch is blocked
by robots.txt on both domains — this is the only route that works for either site.

Two open questions (see rules/known-issues.md) that
this script exists to answer:
  1. Does LinkedIn's guest JD endpoint still render without a login in a fresh,
     cookie-less Playwright context?
  2. Does Xing's /m/ redirect behave the same way outside a browser that's ever
     been signed into Xing?
Run this file's __main__ block against a couple of known-good ids to find out
before trusting it inside the full daily scan.

Setup (one time per machine):
    pip install playwright
    python -m playwright install chromium

Usage:
    python scripts/browser_jd_reader.py linkedin <job_id>
    python scripts/browser_jd_reader.py xing <redirect_token>
    python scripts/browser_jd_reader.py linkedin <job_id> --headed --user-data-dir .pw-profile

If headless comes back empty/blocked, rerun with --headed --user-data-dir <dir> once,
log in by hand in the window that opens, close it, and reruns against that same
--user-data-dir will reuse the session (rules/runbook.md's documented fallback).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from dataclasses import dataclass, asdict
from urllib.parse import urlsplit, urlunsplit

LINKEDIN_EXTRACTION_SELECTOR = (
    ".description__text, .show-more-less-html__markup, section.description"
)


def _stealth_playwright():
    """A drop-in replacement for sync_playwright() that also applies
    playwright-stealth's evasion patches (navigator.webdriver, missing
    chrome.runtime, and other headless-Chromium tells that Cloudflare's active
    JS challenge checks for) to every context created within it. Added
    2026-09-28 after reviewing Cloudflare's detection methods — TLS/HTTP2
    fingerprinting and IP reputation aren't something this fixes (a real
    Chromium browser on the owner's home IP is already fine on both counts), but the
    headless-specific fingerprint gaps are worth closing for free."""
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth
    return Stealth().use_sync(sync_playwright())


@dataclass
class JDReadResult:
    ok: bool
    canonical_url: str | None
    text: str | None
    employer_hint: str | None
    error: str | None = None


def _strip_query(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def read_linkedin_jd(job_id: str, *, headed: bool = False, user_data_dir: str | None = None,
                      timeout_ms: int = 20000) -> JDReadResult:
    """Reads a LinkedIn JD via the guest endpoint. The url STORED on the tracker
    row must stay the human-facing https://de.linkedin.com/jobs/view/<id> — this
    function returns the read-only guest-endpoint text plus that canonical url,
    never the guest-endpoint url itself (rules/runbook.md)."""
    read_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    canonical_url = f"https://de.linkedin.com/jobs/view/{job_id}"

    with _stealth_playwright() as p:
        browser_ctx, cleanup = _launch(p, headed=headed, user_data_dir=user_data_dir)
        try:
            page = browser_ctx.new_page()
            page.goto(read_url, timeout=timeout_ms, wait_until="domcontentloaded")
            try:
                page.wait_for_selector(LINKEDIN_EXTRACTION_SELECTOR, timeout=5000)
            except Exception:
                pass
            text = page.eval_on_selector(
                LINKEDIN_EXTRACTION_SELECTOR,
                "el => el ? el.innerText : null",
            ) if page.query_selector(LINKEDIN_EXTRACTION_SELECTOR) else None

            if not text:
                body_text = page.inner_text("body")
                return JDReadResult(
                    ok=False, canonical_url=canonical_url, text=None, employer_hint=None,
                    error=(
                        "extraction selector matched nothing — likely a login wall or "
                        "layout change. First 300 chars of body: "
                        + body_text[:300].replace("\n", " ")
                    ),
                )
            return JDReadResult(ok=True, canonical_url=canonical_url, text=text, employer_hint=None)
        except Exception as exc:  # noqa: BLE001
            return JDReadResult(ok=False, canonical_url=canonical_url, text=None,
                                 employer_hint=None, error=str(exc))
        finally:
            cleanup()


def read_xing_jd(url: str, *, headed: bool = False, user_data_dir: str | None = None,
                  timeout_ms: int = 20000) -> JDReadResult:
    """Reads a Xing JD directly from its canonical xing.com/jobs/... URL (the
    normal job URL, not a /m/ redirect — per rules/runbook.md, this one works
    directly in the browser; the description is in document.body.innerText)."""
    canonical_url = _strip_query(url)

    with _stealth_playwright() as p:
        browser_ctx, cleanup = _launch(p, headed=headed, user_data_dir=user_data_dir)
        try:
            page = browser_ctx.new_page()
            page.goto(canonical_url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
            text = page.evaluate("document.body.innerText")
            if not text or len(text) < 200:
                return JDReadResult(ok=False, canonical_url=canonical_url, text=text,
                                     employer_hint=None,
                                     error=f"page text too short ({len(text or '')} chars) — "
                                           f"likely a 404, login wall, or removed posting")
            return JDReadResult(ok=True, canonical_url=canonical_url, text=text, employer_hint=None)
        except Exception as exc:  # noqa: BLE001
            return JDReadResult(ok=False, canonical_url=canonical_url, text=None,
                                 employer_hint=None, error=str(exc))
        finally:
            cleanup()


def read_xing_redirect(token: str, *, headed: bool = False, user_data_dir: str | None = None,
                        timeout_ms: int = 20000) -> JDReadResult:
    """Follows a xing.com/m/<token> mail-redirect link. The /m/ link is a harvest
    key only, per rules/runbook.md — this function returns the canonical
    xing.com/jobs/... URL the redirect lands on (query params stripped), which is
    what actually gets stored."""
    redirect_url = f"https://www.xing.com/m/{token}"

    with _stealth_playwright() as p:
        browser_ctx, cleanup = _launch(p, headed=headed, user_data_dir=user_data_dir)
        try:
            page = browser_ctx.new_page()
            page.goto(redirect_url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)  # let the redirect settle
            landed_url = page.evaluate("location.href")
            canonical_url = _strip_query(landed_url)
            text = page.evaluate("document.body.innerText")
            if not text or "xing.com/jobs" not in canonical_url:
                return JDReadResult(
                    ok=False, canonical_url=canonical_url, text=text, employer_hint=None,
                    error=f"did not land on a xing.com/jobs/... URL (landed on {canonical_url})",
                )
            return JDReadResult(ok=True, canonical_url=canonical_url, text=text, employer_hint=None)
        except Exception as exc:  # noqa: BLE001
            return JDReadResult(ok=False, canonical_url=None, text=None,
                                 employer_hint=None, error=str(exc))
        finally:
            cleanup()


def _title_alternation() -> str:
    """The words a posting's TITLE must carry to pass the search filter, built from the person's configuration: the role-type words of the kinds they look for
    (resources/levels.json, in the languages of their region), plus the field words of their core sub-fields when they look for experienced roles.
    A title filter is the only use of a title this toolkit allows: the full posting decides everything else."""
    import config
    cfg = config.get()
    al = cfg.watch_aliases()
    words: list[str] = []
    for terms in al["level"].values():
        words += terms
    if not words or {"mid", "senior"} & set(cfg.levels_sought):
        for terms in al["pillars"].values():
            words += terms
    parts = []
    for t in words:
        t = t.rstrip("*").strip().lower()
        if t:
            parts.append(re.escape(t).replace("\\ ", "\\s+").replace("\\-", "-"))
    return "|".join(dict.fromkeys(parts)).replace("/", "\/") or "intern|internship"      # a "/" would end the JavaScript regex literal


def _extractor(js: str, extra_title_terms: str = "") -> str:
    """Put the person's title filter into one of the page-scraping scripts (`extra_title_terms`: more alternatives, each starting with "|")."""
    return js.replace("__TITLE_RX__", _title_alternation() + extra_title_terms)


XING_SEARCH_SCOPE_REGEX = (
    r"werkstudent|working student|praktik|intern\b|internship|masterarbeit|trainee|"
    r"studentische|hilfskraft"
)

_XING_SEARCH_EXTRACTOR = r"""
const RX=/__TITLE_RX__/i;
const s=new Set(),o=[];
for(const a of document.querySelectorAll('a[href*="/jobs/"]')){
  const h=a.getAttribute('href')||'';
  const m=h.match(/^\/jobs\/(.+)-(\d{6,})$/); if(!m||s.has(m[2]))continue;
  const card=a.closest('article')||a.closest('li')||a.parentElement;
  const txt=((card&&card.innerText)||'').split('\n').map(x=>x.trim()).filter(Boolean);
  const title=txt[0]||m[1].replace(/-/g,' '); if(!RX.test(title))continue;
  s.add(m[2]);
  o.push({id:m[2],t:title,co:txt[1]||'',lo:txt[2]||'',u:'https://www.xing.com'+h});
}
JSON.stringify({n:o.length,j:o})
"""


def search_xing_jobs(keyword: str, *, headed: bool = False, timeout_ms: int = 25000) -> list[dict]:
    """Attended-only Xing keyword search (rules/known-issues.md). Never call this from
    an unattended/scheduled run — the original system restricted Xing browser access
    to attended sessions by design, and that convention is kept even though the
    technical per-action-approval limitation it was working around (a claude.ai
    browser-pane restriction) doesn't apply to a local Playwright context.

    Returns a list of {id, t (title), co (employer), lo (location), u (canonical url)}
    dicts, deduplicated by the trailing numeric Xing id. Titles are already filtered
    to scope-relevant role types (Werkstudent/Praktikum/Intern/Masterarbeit/Trainee/
    Hilfskraft) by the extractor's own regex — this is still a title-only filter, so
    every result still needs a real JD read before scoring (rules/runbook.md's
    JD-first rule)."""
    url = f"https://www.xing.com/jobs/search?keywords={keyword.replace(' ', '%20')}&sort=date&filter.country=de"

    with _stealth_playwright() as p:
        browser_ctx, cleanup = _launch(p, headed=headed, user_data_dir=None)
        try:
            page = browser_ctx.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            result = json.loads(page.evaluate(_extractor(_XING_SEARCH_EXTRACTOR)))
            return result["j"]
        finally:
            cleanup()


_GLASSDOOR_SEARCH_EXTRACTOR = r"""
const RX=/__TITLE_RX__/i;
const RATING_RX=/^[0-9],[0-9]$/;
const s=new Set(),o=[];
for(const a of document.querySelectorAll('a[href*="/job-listing/"], a[data-test="job-title"]')){
  const h=a.getAttribute('href')||''; if(s.has(h))continue;
  const t=(a.innerText||a.getAttribute('aria-label')||'').trim(); if(!t||!RX.test(t))continue;
  s.add(h);
  // Glassdoor's card CSS classes churn often enough that a class selector is
  // brittle (confirmed empty on a live run 2026-09-29); read the card's own
  // text lines instead, which are stable even when class names change. The
  // employer name is the line immediately before the title line, skipping a
  // bare rating number ("4,2") if the card shows one.
  const card=a.closest('li')||a.closest('[data-test="jobListing"]')||a.closest('div')||a.parentElement;
  const lines=((card&&card.innerText)||'').split('\n').map(x=>x.trim()).filter(Boolean);
  const idx=lines.indexOf(t.split('\n')[0]);
  let co='';
  if(idx>0){
    let j=idx-1;
    if(RATING_RX.test(lines[j])) j--;
    co=lines[j]||'';
  }
  o.push({t,co,lo:lines[idx+1]||'',href:h.startsWith('http')?h:('https://www.glassdoor.de'+h)});
}
JSON.stringify({n:o.length,j:o,bodySample:document.body.innerText.slice(0,600)})
"""


def read_glassdoor_jd(url: str, *, headed: bool = False, user_data_dir: str | None = None,
                       timeout_ms: int = 20000) -> JDReadResult:
    """Reads a Glassdoor job-listing page's JD text (rules/runbook.md Steps 6-7).
    Glassdoor gives no per-posting URL of its own per the standing finding in
    known-issues.md -- THE LINK RULE's employer's-own-site check still comes
    first; this exists for the case where the employer's own posting can't be
    found and Glassdoor's own listing page is the only real text available, or
    to cross-check the listing before trusting search_glassdoor_jobs()'s title
    match. No stable data-test selector is assumed (Glassdoor's markup churns --
    see search_glassdoor_jobs()'s docstring) -- this reads the whole body text,
    same fallback LinkedIn's reader uses when its own selector comes up empty."""
    with _stealth_playwright() as p:
        browser_ctx, cleanup = _launch(p, headed=headed, user_data_dir=user_data_dir)
        try:
            page = browser_ctx.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            text = page.inner_text("body")
            canonical_url = _strip_query(page.evaluate("location.href"))
            # The search-results page and an individual listing page get
            # challenged independently -- confirmed live 2026-09-29: a search
            # sweep passed clean, the very next individual-listing read on the
            # same result hit Cloudflare's interstitial ("Ray ID:", a cookie
            # banner, no real JD text). That page is long enough to pass a bare
            # length check, so this looks for the interstitial's own fingerprint
            # explicitly rather than trusting text length alone.
            challenged = text and ("Ray ID:" in text or "Cloudflare Location:" in text)
            if not text or len(text) < 200 or challenged:
                return JDReadResult(
                    ok=False, canonical_url=canonical_url, text=text, employer_hint=None,
                    error="Cloudflare interstitial" if challenged else "body text too short or empty",
                )
            return JDReadResult(ok=True, canonical_url=canonical_url, text=text, employer_hint=None)
        except Exception as exc:  # noqa: BLE001
            return JDReadResult(ok=False, canonical_url=None, text=None,
                                 employer_hint=None, error=str(exc))
        finally:
            cleanup()


def search_glassdoor_jobs(keyword: str, *, headed: bool = False, timeout_ms: int = 25000) -> dict:
    """Glassdoor board sweep (rules/runbook.md Step 5). A plain HTTP fetch gets
    Cloudflare-403'd (documented in rules/known-issues.md) -- this is the
    stealth-Playwright equivalent of search_xing_jobs()/search_linkedin_jobs(),
    added 2026-09-29 so this doesn't need improvising fresh each run (every prior
    session's run_log entry for a Glassdoor sweep describes writing this same
    Playwright call ad hoc). Glassdoor gives no stable per-posting URL on its own
    per the standing finding in known-issues.md -- THE LINK RULE's employer's-own-
    site verification still applies before anything reaches the tracker.

    Uses a fresh browser context per call by design; the caller is responsible for
    pacing between keywords (6-8s worked when this was last hand-run per
    data/scan-state.json's run_log, after an earlier same-session attempt without
    pacing got Cloudflare-challenged) and for the 6-fetch-per-run budget.

    Returns {"n": <count>, "j": [{"t","co","lo","href"}], "bodySample": <str>}.
    bodySample is included so a caller can tell a real empty result apart from a
    Cloudflare interstitial/CAPTCHA page even when extraction finds zero cards."""
    url = (f"https://www.glassdoor.de/Job/jobs.htm?sc.keyword={keyword.replace(' ', '%20')}"
           f"&locT=N&locId=96&fromAge=3")

    with _stealth_playwright() as p:
        browser_ctx, cleanup = _launch(p, headed=headed, user_data_dir=None)
        try:
            page = browser_ctx.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            return json.loads(page.evaluate(_extractor(_GLASSDOOR_SEARCH_EXTRACTOR)))
        finally:
            cleanup()


_LINKEDIN_SEARCH_EXTRACTOR = r"""
const RX=/__TITLE_RX__/i;
const s=new Set(),o=[];
for(const a of document.querySelectorAll('a[href*="/jobs/view/"]')){
  const u=a.href.split('?')[0]; if(s.has(u))continue; s.add(u);
  const c=a.closest('li')||a.parentElement;
  const t=(a.innerText||'').trim().split('\n')[0]; if(!RX.test(t))continue;
  const co=((c.querySelector('.base-search-card__subtitle,h4')||{}).innerText||'').trim();
  const lo=((c.querySelector('.job-search-card__location')||{}).innerText||'').trim();
  const tm=c.querySelector('time');
  o.push({t,co,lo,d:tm?tm.getAttribute('datetime'):'',u});
}
JSON.stringify({n:o.length,j:o})
"""


# Local-language student-role words for the Europe sweep (runbook Step 5b). The default
# title filter only knows German and English, which silently dropped French "stage",
# Spanish "practicas", Italian "tirocinio" etc. (found 2026-10-06 when Sanofi's
# Montpellier "stage 6 mois ... pharmacocinetique" never reached the sweep output).
EUROPE_TITLE_TERMS = (r"|stage\b|stagiaire|tirocin|pr[aá]cticas|becari|est[aá]gio|afstudeer"
                      r"|examensarbete|harjoittel|praktika|gyakornok|sta[zż]\b|bijbaan|studentenjob"
                      r"|job [eé]tudiant|graduate programme|student assistant")


def search_linkedin_jobs(keyword: str, *, window: str = "r604800", headed: bool = False,
                          timeout_ms: int = 25000, location: str | None = None,
                          extra_title_terms: str = "") -> list[dict]:
    """LinkedIn keyword search. window is f_TPR: r86400=24h, r259200=3d, r604800=7d.

    extra_title_terms: regex alternatives (each starting with "|") appended to the
    title filter, e.g. EUROPE_TITLE_TERMS for local-language searches outside the home market.
    location: defaults to the name of the home region pack (profile.regions[0]).

    IMPORTANT — read rules/known-issues.md before assuming this is safe to run
    unattended: the original system RETIRED this exact capability after finding a
    SIGNED-IN browser returned the same loose semantic results for every keyword,
    destroying precision. Re-tested 2026-09-23 in a fresh, logged-out Playwright
    context (no cookies, never authenticated) at the owner's explicit request: 8
    keywords each returned genuinely different, keyword-relevant results — the
    failure mode did not reproduce. The working theory is that it was specific to
    LinkedIn's personalized/collaborative-filtering ranking for an authenticated
    session, not a property of LinkedIn search itself. Do NOT log this context in
    (no cookies, no saved session, no user_data_dir) — that's what keeps this
    working. If results ever start looking identical across keywords again, stop
    and re-read known-issues.md before trusting the output.

    Returns a list of {t (title), co (employer), lo (location), d (iso date), u
    (canonical url)} dicts, title-filtered to scope-relevant role types the same
    way search_xing_jobs() is — still title-only, still needs a real JD read
    before scoring (rules/runbook.md's JD-first rule)."""
    if location is None:
        import config
        location = config.get().region.get("name") or ""
    url = (f"https://www.linkedin.com/jobs/search/?keywords={keyword.replace(' ', '%20')}"
           f"&location={location.replace(' ', '%20')}&f_TPR={window}&sortBy=DD")

    with _stealth_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        # deliberately no user_data_dir -- stay logged out
        ctx = browser.new_context(user_agent=random.choice(_USER_AGENTS), viewport=_VIEWPORT)
        try:
            page = ctx.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            result = json.loads(page.evaluate(_extractor(_LINKEDIN_SEARCH_EXTRACTOR, extra_title_terms)))
            return result["j"]
        finally:
            ctx.close()
            browser.close()


def verify_link(url: str, expect_employer: str, expect_title: str, *, headed: bool = False,
                 timeout_ms: int = 15000) -> bool:
    """THE LINK RULE (rules/runbook.md): open it, read the page text, confirm it
    names both the employer AND a matching role title. Never trust a 200 status
    alone — a 404 page or login wall can still return 200."""
    with _stealth_playwright() as p:
        browser_ctx, cleanup = _launch(p, headed=headed, user_data_dir=None)
        try:
            page = browser_ctx.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            body_text = page.inner_text("body").lower()
            has_employer = expect_employer.lower() in body_text
            has_title_words = any(
                w.lower() in body_text for w in re.findall(r"\w+", expect_title) if len(w) > 3
            )
            return has_employer and has_title_words
        except Exception:
            return False
        finally:
            cleanup()


# Real-world desktop Chrome UA strings (current as of Sep 2026), rotated per launch
# instead of leaving Playwright's bare default Chromium UA on every request — a cheap
# fingerprint reduction borrowed from firecrawl's playwright-service-ts, which draws
# from a dataset of real UAs rather than a fixed or fabricated string.
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
    " Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"
    " Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
    " Chrome/130.0.0.0 Safari/537.36",
]
_VIEWPORT = {"width": 1280, "height": 800}


def _launch(playwright_module, *, headed: bool, user_data_dir: str | None):
    """Returns (browser_context, cleanup_fn). Uses a persistent context with
    user_data_dir when given, so a manual login (headed, once) is reusable on
    later headless runs — the documented fallback in rules/known-issues.md.

    Sets a random real-world desktop UA and a standard desktop viewport on every
    context instead of Playwright's bare defaults (2026-09-28, per firecrawl's
    playwright-service-ts)."""
    user_agent = random.choice(_USER_AGENTS)
    if user_data_dir:
        ctx = playwright_module.chromium.launch_persistent_context(
            user_data_dir, headless=not headed, user_agent=user_agent, viewport=_VIEWPORT,
        )
        return ctx, ctx.close
    browser = playwright_module.chromium.launch(headless=not headed)
    ctx = browser.new_context(user_agent=user_agent, viewport=_VIEWPORT)
    return ctx, lambda: (ctx.close(), browser.close())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_li = sub.add_parser("linkedin")
    p_li.add_argument("job_id")
    p_li.add_argument("--headed", action="store_true")
    p_li.add_argument("--user-data-dir", default=None)

    p_xi = sub.add_parser("xing")
    p_xi.add_argument("token")
    p_xi.add_argument("--headed", action="store_true")
    p_xi.add_argument("--user-data-dir", default=None)

    p_xu = sub.add_parser("xing-url")
    p_xu.add_argument("url")
    p_xu.add_argument("--headed", action="store_true")
    p_xu.add_argument("--user-data-dir", default=None)

    args = parser.parse_args()

    if args.cmd == "linkedin":
        result = read_linkedin_jd(args.job_id, headed=args.headed, user_data_dir=args.user_data_dir)
    elif args.cmd == "xing-url":
        result = read_xing_jd(args.url, headed=args.headed, user_data_dir=args.user_data_dir)
    else:
        result = read_xing_redirect(args.token, headed=args.headed, user_data_dir=args.user_data_dir)

    print(json.dumps(asdict(result), indent=2, ensure_ascii=False)[:4000])
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())

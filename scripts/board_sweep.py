#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/board_sweep.py: search LinkedIn and Xing for the person's field with Boolean queries built from their own profile.

Why Boolean. Measured on 20 Oct 2026: LinkedIn and Xing treat the topic word of a keyword search as optional. A made-up word still returned 60 (LinkedIn) and 16 (Xing)
generic student roles, only 16 to 18% of returned titles contained any word of the searched term, and the plain `omics werkstudent` found 2 of the 7 omics-titled student
roles that a Boolean `(term OR term ...) AND (student word OR ...)` found all 7 of. So every query here has that shape: one per sub-field of the person's domain, the
sub-field's own words in the first group, the role-type words of their region and the kinds of role they want in the second (rules/search-terms.md, rules/job-watch.md).

    python scripts/board_sweep.py build                 write profile/saved-queries.json from the profile (edit it by hand if you like)
    python scripts/board_sweep.py run [--sites linkedin,xing] [--max-queries 10] [--no-intake]
    python scripts/board_sweep.py plan                  print the queries, run nothing

Every student-level hit that the tracker does not know and that fits the person's field is filed as an unscored stub (source <site>_sweep); intake.py then fetches the
full posting and analyze.py scores it. Nothing is scored from a title. Needs Playwright (`onboard.py doctor`); it never logs in.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import unicodedata
from datetime import date
from itertools import zip_longest
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import config  # noqa: E402

SAVED = config.PROFILE_DIR / "saved-queries.json"
OUT = ROOT / "data" / "sweeps"
ROLE_RANK = {"core": 0, "bridge": 1, "income": 2}

_LI_JS = r"""
const s=new Set(),o=[];
for(const a of document.querySelectorAll('a[href*="/jobs/view/"]')){
  const u=a.href.split('?')[0]; if(s.has(u))continue; s.add(u);
  const c=a.closest('li')||a.parentElement;
  const t=(a.innerText||'').trim().split('\n')[0];
  const co=((c.querySelector('.base-search-card__subtitle,h4')||{}).innerText||'').trim();
  const lo=((c.querySelector('.job-search-card__location')||{}).innerText||'').trim();
  o.push({t,co,lo,u});
}
JSON.stringify(o)
"""


def fold(s: str) -> str:
    s = (s or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def _clean_terms(words: list[str], cap: int = 10) -> list[str]:
    out: list[str] = []
    for w in words:
        w = (w or "").replace("*", "").strip()
        if len(w) < 3 or re.search(r"[\\()\[\]|?+^$]", w) or w.lower() in {x.lower() for x in out}:
            continue
        out.append(w)
    return out[:cap]


def _group(words: list[str]) -> str:
    return "(" + " OR ".join(f'"{w}"' if re.search(r"[\s/\-]", w) else w for w in words) + ")"


def locations(cfg) -> list[dict]:
    """One LinkedIn location per region of the person that has a LinkedIn board, read from the region pack's own search URL."""
    out = []
    for code in cfg.region_codes:
        pack = config.resource_region(code) if hasattr(config, "resource_region") else None
        pack = pack or _read_region(code)
        for b in (pack or {}).get("boards", []):
            if "linkedin" in (b.get("name") or "").lower():
                m = re.search(r"location=([^&]+)", b.get("url", ""))
                place = (m.group(1) if m else (pack.get("name") or "")).replace("%20", " ")
                if place and "{" not in place:                                     # a pack's own template (a placeholder) is not a place to search
                    out.append({"region": code, "linkedin": place})
            if "xing" in (b.get("name") or "").lower():
                for o in out:
                    if o["region"] == code:
                        o["xing"] = True
                if not any(o["region"] == code for o in out):
                    out.append({"region": code, "xing": True})
    return out


def _read_region(code: str) -> dict:
    for base in (config.PROFILE_DIR / "regions", ROOT / "regions"):
        p = base / code / "region.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8-sig"))
            except ValueError:
                pass
    return {}


def build(cfg=None, max_queries: int = 10) -> dict:
    """The saved queries: one Boolean query per sub-field (core first), plus the locations. Written to profile/saved-queries.json."""
    cfg = cfg or config.get()
    al = cfg.watch_aliases()
    kinds = [k for k in cfg.levels_sought if al["level"].get(k)] or list(al["level"])
    per_kind = [_clean_terms(al["level"][k], 4) for k in kinds]                 # every kind the person wants gets its words in, not only the first kind's
    level_words = [w for tier in zip_longest(*per_kind) for w in tier if w]
    students = _clean_terms(level_words, 14)
    role = {s.get("id"): s.get("role") for s in cfg.domain.get("subfields", [])}
    label = {s.get("id"): s.get("label") for s in cfg.domain.get("subfields", [])}
    order = sorted(al["pillars"], key=lambda k: ROLE_RANK.get(role.get(k), 3))
    queries = []
    for sid in order:
        terms = _clean_terms(al["pillars"][sid], 10)
        if terms and students:
            queries.append({"name": sid, "label": label.get(sid) or sid, "role": role.get(sid), "query": f"{_group(terms)} AND {_group(students)}"})
    data = {"_about": "Boolean queries for LinkedIn and Xing, built from your profile by `board_sweep.py build`. Edit freely; `run` uses this file. Measured reason for the shape: scripts/board_sweep.py docstring.",
            "built": date.today().isoformat(), "locations": locations(cfg), "queries": queries[:max_queries]}
    SAVED.parent.mkdir(parents=True, exist_ok=True)
    SAVED.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return data


def student_title_rx() -> re.Pattern:
    import browser_jd_reader as b
    return re.compile(b._title_alternation().replace("\\/", "/"), re.I)


def field_rx(cfg) -> re.Pattern:
    """A hit is kept when its title or employer carries a word of one of the person's sub-fields, an industry word of their domain, or a priority employer.
    The analysis reads the whole posting afterwards; this only keeps a board's loose matches from filling the tracker."""
    parts: list[str] = []
    for s in cfg.domain.get("subfields", []):
        if s.get("role") in ROLE_RANK:                                              # core, bridge or income; a sub-field marked "other" is not the person's field
            parts += [t for t in (s.get("terms") or []) if t]
    if cfg.domain.get("industry_regex"):
        parts.append(cfg.domain["industry_regex"])
    parts += [re.escape(fold(e)) for e in (cfg.domain.get("priority_employers") or []) if isinstance(e, str)]
    good = []
    for p in parts:
        try:
            re.compile(p)
            good.append(p)
        except re.error:
            continue
    return re.compile("|".join(f"(?:{p})" for p in good) or r"(?!x)x", re.I)


def search_linkedin(query: str, location: str, sort: str = "R", window: str = "r2592000") -> list[dict]:
    import browser_jd_reader as b
    rows_rx = student_title_rx()
    url = f"https://www.linkedin.com/jobs/search/?keywords={quote(query)}&location={quote(location)}&f_TPR={window}&sortBy={sort}"
    with b._stealth_playwright() as p:
        ctx, cleanup = b._launch(p, headed=False, user_data_dir=None)       # never logged in
        try:
            pg = ctx.new_page()
            pg.goto(url, timeout=30000, wait_until="domcontentloaded")
            pg.wait_for_timeout(2500)
            last = 0
            for i in range(8):                                              # scroll until nothing more loads (about 60 on the first screen, up to about 115)
                pg.mouse.wheel(0, 6000)
                pg.wait_for_timeout(1200)
                try:
                    pg.click("button:has-text('See more jobs'), button:has-text('Mehr Jobs anzeigen'), button.infinite-scroller__show-more-button", timeout=800)
                except Exception:  # noqa: BLE001
                    pass
                n = pg.evaluate("document.querySelectorAll('a[href*=\"/jobs/view/\"]').length")
                if n == last and i > 2:
                    break
                last = n
            return [r for r in json.loads(pg.evaluate(_LI_JS)) if rows_rx.search(r["t"])]
        finally:
            cleanup()


def file_hits(site: str, hits: dict[str, dict], cfg) -> tuple[list[str], int]:
    import intake
    import mail_sync as M
    urls, wids, pairs = M.tracked_index()
    keep = field_rx(cfg)
    source = f"{site}_sweep"
    filed, new = [], 0
    for u, h in hits.items():
        r = h["row"]
        co, t = r.get("co") or "", r.get("t") or ""
        m = re.search(r"(\d{6,})", u.split("?")[0])
        wid = f"mail-{source}-{m.group(1) if m else abs(hash(u))}"
        pair = (M.fold(co), " ".join(M.words(t)))
        if intake.norm_url(u) in urls or wid in wids or pair in pairs:
            continue
        new += 1
        if not keep.search(fold(t) + " " + fold(co)):
            continue
        urls.add(intake.norm_url(u))
        pairs.add(pair)
        kind = "thesis" if re.search(r"masterarbeit|abschlussarbeit|master.?s? thesis|bachelorarbeit|thesis", t, re.I) else "job"
        ref = intake.make_stub({"id": wid, "url": u, "title": t, "employer": co, "location": r.get("lo", ""), "source": source, "origin": "mail",
                                "first_seen": date.today().isoformat(), "kind": kind}, None)
        if ref:
            filed.append(ref)
    return filed, new


def run(sites: list[str], max_queries: int, no_intake: bool) -> int:
    cfg = config.get()
    config.require_configured()
    try:
        import browser_jd_reader  # noqa: F401
        import playwright  # noqa: F401
    except ImportError:
        print("Playwright is not installed: board search is skipped. `python -m pip install playwright playwright-stealth` then `python -m playwright install chromium`.", file=sys.stderr)
        return 2
    saved = json.loads(SAVED.read_text(encoding="utf-8")) if SAVED.exists() else build(cfg, max_queries)
    queries = saved["queries"][:max_queries]
    locs = saved.get("locations") or []
    import db
    db.init_db()
    summary = {}
    for site in sites:
        hits: dict[str, dict] = {}
        if site == "linkedin":
            for loc in [l for l in locs if l.get("linkedin")]:
                for q in queries:
                    try:
                        rows = search_linkedin(q["query"], loc["linkedin"])
                    except Exception as exc:  # noqa: BLE001
                        print(f"  [linkedin {loc['region']}] {q['name']}: error {type(exc).__name__}", flush=True)
                        continue
                    for r in rows:
                        hits.setdefault(r["u"], {"row": r})
                    print(f"  [linkedin {loc['region']}] {q['name']}: {len(rows)} student-level", flush=True)
                    time.sleep(random.uniform(4, 7))
        elif site == "xing" and any(l.get("xing") for l in locs):
            import browser_jd_reader as b
            for q in queries:
                try:
                    rows = b.search_xing_jobs(q["query"])
                except Exception as exc:  # noqa: BLE001
                    print(f"  [xing] {q['name']}: error {type(exc).__name__}", flush=True)
                    continue
                for r in rows:
                    hits.setdefault(r["u"], {"row": r})
                print(f"  [xing] {q['name']}: {len(rows)} student-level", flush=True)
                time.sleep(random.uniform(3, 5))
        filed, new = file_hits(site, hits, cfg)
        summary[site] = {"hits": len(hits), "new_to_tracker": new, "filed": len(filed)}
        print(f"{site}: {len(hits)} hits, {new} new to the tracker, {len(filed)} filed", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{date.today().isoformat()}-boards.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    if not no_intake:
        import intake
        print(json.dumps(intake.run(None, True, True), ensure_ascii=False, indent=1, default=str)[:1200])
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["build", "run", "plan"])
    ap.add_argument("--sites", default="linkedin,xing")
    ap.add_argument("--max-queries", type=int, default=10)
    ap.add_argument("--no-intake", action="store_true")
    a = ap.parse_args()
    if a.cmd == "build":
        d = build(max_queries=a.max_queries)
        print(f"{len(d['queries'])} queries written to {SAVED}")
        return 0
    if a.cmd == "plan":
        d = json.loads(SAVED.read_text(encoding="utf-8")) if SAVED.exists() else build(max_queries=a.max_queries)
        print("locations:", d["locations"])
        for q in d["queries"]:
            print(f"- {q['name']} ({q['role']}): {q['query']}")
        return 0
    return run(a.sites.split(","), a.max_queries, a.no_intake)


if __name__ == "__main__":
    sys.exit(main())

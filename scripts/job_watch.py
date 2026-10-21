#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Job watch: the employer-side twin of uni_watch.py. Polls employer and job-board sources that can be read without a browser or a login, keeps
the roles at the levels the profile looks for, classifies them with the profile's own field words, de-duplicates against what was already reported
and against the tracker, and writes a candidate inbox.

Sources (regions/<code>/sources.json plus profile/sources.json, merged by scripts/config.py `sources()`):
  national_board  the country's public job-board API where there is one (adapter `bundesagentur` for Germany; a region pack can add others)
  workday         Workday career sites (large employers): POST search
  greenhouse / lever / smartrecruiters / recruitee   public ATS JSON feeds

Like the institution watch it NEVER writes the tracker. It writes data/jobwatch/<date>.json, data/jobwatch/seen.json and digests/job-watch-<date>.md.
The dashboard's Inbox reads the JSON next to the institution feed. A Claude session promotes a candidate only after opening and reading the posting
(JD-first, THE LINK RULE, rules/runbook.md).

Usage:
    python scripts/job_watch.py                  # full run
    python scripts/job_watch.py --only workday   # one adapter family
    python scripts/job_watch.py --no-write       # dry run, prints the summary
    python scripts/job_watch.py --all-regions    # also keep roles outside the countries searched
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import intake  # noqa: E402  (country_of)
import uni_watch as uw  # noqa: E402  (reuses the alias classifier)

warnings.filterwarnings("ignore")
ROOT = uw.ROOT
OUT = ROOT / "data" / "jobwatch"
H = {"User-Agent": "Mozilla/5.0 (job-search-toolkit watch; personal use)"}
TIMEOUT = 25

HEALTH_FALLBACK = ()


def in_scope(country: str) -> bool:
    """A role is in scope in a country the search covers, or where the country could not be read (then the full JD decides, never the title)."""
    scope = config.get().scope_countries
    return (not scope) or country in scope or country == "ZZ"


def employer_matches(name: str) -> tuple[bool, bool]:
    """(is a priority employer, is in the user's industry), both from profile/domain.json."""
    cfg = config.get()
    e = (name or "").lower()
    pri = any(p.lower() in e for p in (cfg.domain.get("priority_employers") or []))
    ind = cfg.regex("industry_regex")
    return pri, bool(ind and ind.search(e))


def get(url, **kw):
    for _ in range(2):
        try:
            return requests.get(url, headers=H, timeout=TIMEOUT, **kw)
        except requests.RequestException:
            time.sleep(1.0)
    return None


def post(url, payload):
    for _ in range(2):
        try:
            return requests.post(url, json=payload, headers={**H, "Content-Type": "application/json"}, timeout=TIMEOUT)
        except requests.RequestException:
            time.sleep(1.0)
    return None


def mk(source, employer, title, url, **kw):
    d = uw.item(source, employer, title, url, **kw)
    d["employer"] = employer
    d["origin"] = "company"
    return d


# --------------------------------------------------------------------------- adapters

BA = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"


def bundesagentur(cfg):
    """Germany's Bundesagentur für Arbeit job-search API (all German employers). Region pack settings: {adapter, queries, days, page_size}."""
    out, seen = [], set()
    since = cfg.get("days", 14)

    def one(q):
        got = []
        for page in (1, 2):
            try:
                r = requests.get(BA, params={"was": q, "size": cfg.get("page_size", 100), "page": page, "veroeffentlichtseit": since},
                                 headers={**H, "X-API-Key": "jobboerse-jobsuche"}, timeout=TIMEOUT)
            except requests.RequestException:
                break
            if not r.ok:
                break
            rows = r.json().get("ergebnisliste", [])
            got += rows
            if len(rows) < cfg.get("page_size", 100):
                break
        return got

    with ThreadPoolExecutor(6) as ex:
        results = list(ex.map(one, cfg.get("queries") or config.get().board_queries(cfg.get("query_prefixes"))))
    for rows in results:
        for e in rows:
            ref = e.get("referenznummer")
            if not ref or ref in seen or e.get("stellenangebotsart") == "AUSBILDUNG":
                continue
            seen.add(ref)
            loc = (e.get("stellenlokationen") or [{}])[0].get("adresse", {}).get("ort", "")
            ext = e.get("externeURL")
            it = mk("bundesagentur", e.get("firma") or "(employer not shown)", e.get("stellenangebotsTitel", ""),
                    f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}",
                    posted=uw.iso(e.get("datumErsteVeroeffentlichung") or ""), location=loc,
                    category=("Praktikum Trainee" if e.get("stellenangebotsart") == "PRAKTIKUM_TRAINEE" else ""))
            if ext:
                it["employer_url"] = ext
            out.append(it)
    return out


def _wd_posted(s: str):
    s = (s or "").lower()
    today = date.today()
    if "today" in s:
        return today.isoformat()
    if "yesterday" in s:
        return (today - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\+?\s*days", s)
    return (today - timedelta(days=int(m.group(1)))).isoformat() if m else None


def workday(src, terms):
    base = f"https://{src['tenant']}.wd{src['wd']}.myworkdayjobs.com"
    out, seen = [], set()
    for term in terms:
        for offset in (0, 20, 40):
            r = post(f"{base}/wday/cxs/{src['tenant']}/{src['site']}/jobs",
                     {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": term})
            if r is None or not r.ok:
                break
            rows = r.json().get("jobPostings", [])
            for p in rows:
                path = p.get("externalPath")
                if not path or path in seen:
                    continue
                seen.add(path)
                out.append(mk("workday", src["institution"], p.get("title", ""), f"{base}/en-US/{src['site']}{path}",
                              posted=_wd_posted(p.get("postedOn", "")), location=p.get("locationsText", "")))
            if len(rows) < 20:
                break
    return out


def greenhouse(src):
    r = get(f"https://boards-api.greenhouse.io/v1/boards/{src['slug']}/jobs")
    if r is None or not r.ok:
        return []
    return [mk("greenhouse", src["institution"], j.get("title", ""), j.get("absolute_url", ""),
               posted=uw.iso(j.get("updated_at") or ""), location=(j.get("location") or {}).get("name", "")) for j in r.json().get("jobs", [])]


def lever(src):
    r = get(f"https://api.lever.co/v0/postings/{src['slug']}?mode=json")
    if r is None or not r.ok:
        return []
    out = []
    for j in r.json():
        ts = j.get("createdAt")
        out.append(mk("lever", src["institution"], j.get("text", ""), j.get("hostedUrl", ""),
                      posted=datetime.fromtimestamp(ts / 1000).date().isoformat() if ts else None,
                      location=(j.get("categories") or {}).get("location", "")))
    return out


def smartrecruiters(src):
    out, seen = [], set()
    for term in src.get("terms", ["intern"]):
        r = get(f"https://api.smartrecruiters.com/v1/companies/{src['slug']}/postings", params={"q": term, "limit": 100, **({"country": src["country"]} if src.get("country") else {})})
        if r is None or not r.ok:
            continue
        for p in r.json().get("content", []):
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            loc = p.get("location") or {}
            out.append(mk("smartrecruiters", src["institution"], p.get("name", ""), f"https://jobs.smartrecruiters.com/{src['slug']}/{p['id']}",
                          posted=uw.iso(p.get("releasedDate") or ""),
                          location=", ".join(x for x in (loc.get("city"), loc.get("country", "").upper()) if x)))
    return out


def recruitee(src):
    r = get(f"https://{src['slug']}.recruitee.com/api/offers/")
    if r is None or not r.ok:
        return []
    return [mk("recruitee", src["institution"], o.get("title", ""), o.get("careers_url", ""), posted=uw.iso(o.get("created_at") or ""),
               location=o.get("location", "")) for o in r.json().get("offers", [])]


ATS = {"greenhouse": greenhouse, "lever": lever, "smartrecruiters": smartrecruiters, "recruitee": recruitee}


# --------------------------------------------------------------------------- run

class JobClassifier(uw.Classifier):
    def classify(self, title, text="", category=""):
        c = super().classify(title, text, category)
        if c["kind"] == "other" and "trainee" in c["levels"]:
            c["kind"] = "trainee"
        return c


def seen_state():
    p = OUT / "seen.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--all-regions", action="store_true")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    cfg = config.get().sources()
    sys.stdout.reconfigure(encoding="utf-8")

    tasks = []  # (label, family, callable)
    nb = cfg.get("national_board")
    if nb and (not only or nb.get("adapter", "bundesagentur") in only):
        tasks.append((nb.get("name", "National job board"), nb.get("adapter", "bundesagentur"), lambda: bundesagentur(nb)))
    for s in cfg["workday"]:
        if not only or "workday" in only:
            tasks.append((s["institution"], "workday", lambda s=s: workday(s, cfg["workday_terms"])))
    for s in cfg["ats"]:
        if not only or s["adapter"] in only:
            tasks.append((s["institution"], s["adapter"], lambda s=s: ATS[s["adapter"]](s)))

    items, errors, per_source = [], [], {}

    def run(t):
        label, fam, fn = t
        try:
            return label, fam, fn(), None
        except Exception as e:  # noqa: BLE001
            return label, fam, [], f"{label} [{fam}]: {type(e).__name__}: {str(e)[:80]}"

    with ThreadPoolExecutor(6) as ex:
        for label, fam, got, err in ex.map(run, tasks):
            if err:
                errors.append(err)
            per_source[f"{label} [{fam}]"] = len(got)
            items.extend(got)

    clf, seen, in_tracker = JobClassifier(), seen_state(), uw.tracker_urls()
    today = date.today().isoformat()
    results, ids = [], set()
    for it in items:
        if it["id"] in ids:
            continue
        ids.add(it["id"])
        it.update(clf.classify(it["title"], it.get("text", ""), it.get("category", "")))
        it["country"] = intake.country_of(it.get("location", ""), it.get("source", ""))
        if it["country"] == "ZZ":
            it["country"] = intake.country_of(re.sub(r"[-_/]+", " ", (it["url"] or "").split("/job/")[-1].split("/")[0]), it.get("source", ""))
        it["in_scope"] = in_scope(it["country"])
        # on-topic = one of the user's own fields, or an adjacent skill (income role) at an employer in their industry or on their priority list
        roles = {k: v.get("role") for k, v in config.get().subfields.items()}
        own = [p for p in it["pillars"] if roles.get(p) in ("core", "bridge")]
        pri, ind = employer_matches(it["employer"])
        it["on_topic"] = bool(own) or (bool(it["pillars"]) and (pri or ind))
        if not it["in_scope"] and it["prov_score"]:
            it["prov_score"] = max(0, it["prov_score"] - 2)
        if it["country"] in config.get().primary_countries:
            it["prov_score"] += 1
        it["new"] = it["id"] not in seen
        it["in_tracker"] = (it["url"] or "").split("?")[0].rstrip("/") in in_tracker
        results.append(it)

    student = [r for r in results if r["levels"] and not r["excluded"] and (a.all_regions or r["in_scope"])]
    relevant = [r for r in student if r["on_topic"]]
    new_rel = sorted([r for r in relevant if r["new"] and not r["in_tracker"]], key=lambda r: (-r["prov_score"], r["employer"]))
    summary = {"date": today, "sources": len(per_source), "items": len(results), "student_level": len(student),
               "on_topic": len(relevant), "new_on_topic": len(new_rel), "errors": errors}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if a.no_write:
        for r in new_rel[:40]:
            print(f"- [{r['prov_score']}] {r['employer']}: {r['title'][:80]} | {r['kind']} {r['country']} {r['location'][:25]} | {r['pillars'][:2]} | {r['url']}")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    day_file = OUT / f"{today}.json"
    if day_file.exists():
        # A partial run (--only) or a second run on the same day merges into the day's file instead of replacing it.
        prev = json.loads(day_file.read_text(encoding="utf-8"))
        merged = {i["id"]: i for i in prev.get("items", [])}
        merged.update({i["id"]: i for i in student})
        student = list(merged.values())
        per_source = {**prev.get("per_source", {}), **per_source}
        summary = {**summary, "items": max(summary["items"], prev.get("summary", {}).get("items", 0)), "student_level": len(student)}
    day_file.write_text(json.dumps({"summary": summary, "per_source": per_source, "items": student}, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in results:
        seen.setdefault(r["id"], {"first_seen": today, "employer": r["employer"], "title": r["title"][:120]})
    (OUT / "seen.json").write_text(json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = [f"# Job watch, {today}", "", f"{summary['sources']} sources polled, {summary['items']} postings read, {summary['student_level']} at the levels sought, "
             f"{summary['on_topic']} on-topic, **{summary['new_on_topic']} new on-topic**.", ""]
    if errors:
        lines += ["## Source errors", *[f"- {e}" for e in errors], ""]
    lines += ["## New on-topic roles at the levels sought (highest provisional score first)", ""]
    if not new_rel:
        lines.append("None since the last run.")
    for r in new_rel[:60]:
        lines.append(f"- **{r['title'][:150]}** ({r['employer']}, {r['location'] or 'location not shown'}; {r['kind']}) "
                     f"[{', '.join(r['title_pillars'] or r['pillars'])}] {r['url']}")
    d = ROOT / "digests"
    d.mkdir(exist_ok=True)
    (d / f"job-watch-{today}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

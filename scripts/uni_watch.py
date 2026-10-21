#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Institution watch (universities, research institutes, hospitals): poll every source that can be read without a browser, classify,
de-duplicate against what has been seen, and write a candidate inbox.

Techniques (cheapest and most reliable first; see rules/institutions.md "Tool matrix"):
  bite_api   JSON API of the b-ite platform (about 30 institutions): one POST per listing,
             exact title, start/end dates (= deadline), employer, address, category.
  bite_site  b-ite sites that expose only a hostname: list page -> /jobposting/<hash> links.
  adsapi     b-ite 'adsapi/jobads?apikey=' JSON (TH OWL).
  rss        job-specific RSS/Atom feeds (TUM HiWi board, Duisburg-Essen SHK/WHK, FU Berlin,
             Bremen, Tuebingen, Mainz, Leipzig, ...).
  sap_rss    SAP SuccessFactors recruiting RSS (`/services/rss/category/?catid=`), e.g. MHH, UKSH.
  html_list  plain HTML list pages (anchors + dates) for sites with no feed or API.
Anything not reachable this way is covered by the browser sweep (a Claude session's browser sweep (rules/runbook.md)).

The watch NEVER writes the tracker. It writes data/watch/<date>.json (all items found this
run, new ones flagged), data/watch/seen.json (ids already reported) and
digests/university-watch-<date>.md. A Claude session promotes candidates into the tracker
after opening, reading and verifying each posting (THE LINK RULE, JD-first).

Usage:
    python scripts/uni_watch.py                 # full run
    python scripts/uni_watch.py --only bite_api,rss
    python scripts/uni_watch.py --no-write      # dry run, prints the summary
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import warnings

import requests
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WATCH = DATA / "watch"
H = {"User-Agent": "Mozilla/5.0 (job-search-toolkit watch; personal use)"}
TIMEOUT = 25


# --------------------------------------------------------------------------- aliases / classifier

def _fold(s: str) -> str:
    """Lower-case and fold umlauts so 'Pharmazeutische Hilfskräfte' == 'hilfskraefte'."""
    s = s.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def _compile(terms):
    """Terms -> one regex. A trailing * means prefix match; others match as whole tokens
    (so 'KI' does not fire inside 'Kind' and 'IBE' not inside 'Fibel')."""
    parts = []
    for t in terms:
        t = _fold(t.strip())
        if not t:
            continue
        stem = t.endswith("*")
        t = re.escape(t.rstrip("*")).replace(r"\ ", r"\s+")
        parts.append(rf"(?<![a-z0-9]){t}" + (r"[a-z0-9]*" if stem else r"(?![a-z0-9])"))
    return re.compile("|".join(parts)) if parts else re.compile(r"(?!x)x")


class Classifier:
    def __init__(self):
        a = config.get().watch_aliases()        # the role-type words, field words and exclusions of this profile (profile/domain.json, resources/levels.json)
        self.level = {k: _compile(v) for k, v in a["level"].items() if not k.startswith("_")}
        self.exclude = _compile(a["exclude_level"]["terms"])
        # Terms of 3 characters or fewer (KI, AI, IBE, HITS-like acronyms) are ambiguous: they count
        # in the title/category only, never inside a long description.
        self.pillars_title, self.pillars_text = {}, {}
        for k, v in a["pillars"].items():
            if k.startswith("_"):
                continue
            self.pillars_title[k] = _compile(v)
            self.pillars_text[k] = _compile([t for t in v if len(_fold(t).rstrip("*")) > 4])

    def classify(self, title: str, text: str = "", category: str = "") -> dict:
        t = _fold(title)
        tc = _fold(title + " " + category)
        levels = [k for k, rx in self.level.items() if rx.search(tc)]
        title_levels = [k for k, rx in self.level.items() if rx.search(t)]
        excluded = bool(self.exclude.search(t)) and not title_levels
        body = _fold(text[:6000])
        title_pillars = [k for k, rx in self.pillars_title.items() if rx.search(tc)]
        pillars = list(dict.fromkeys(title_pillars + [k for k, rx in self.pillars_text.items() if rx.search(body)]))
        kind = "other"
        for k in ("thesis", "student_assistant", "working_student", "internship", "trainee", "entry", "mid", "senior"):
            if k in levels:
                kind = k
                break
        score = (2 if levels else 0) + min(len(pillars), 3) + min(len(title_pillars), 2)
        return {"kind": kind, "levels": levels, "excluded": excluded, "pillars": pillars,
                "title_pillars": title_pillars, "prov_score": score}


# --------------------------------------------------------------------------- helpers

def get(url, **kw):
    for attempt in range(2):
        try:
            r = requests.get(url, headers=H, timeout=TIMEOUT, **kw)
            return r
        except requests.RequestException:
            time.sleep(1.0)
    return None


def item(source, institution, title, url, **kw):
    uid = hashlib.sha1((url or title).encode("utf-8")).hexdigest()[:16]
    d = {"id": uid, "source": source, "institution": institution, "title": " ".join((title or "").split()),
         "url": url, "posted": kw.get("posted"), "deadline": kw.get("deadline"), "category": kw.get("category", ""),
         "location": kw.get("location", ""), "text": kw.get("text", "")[:3000]}
    return d


def iso(s):
    if not s:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


# --------------------------------------------------------------------------- adapters

def _working_keys(cands):
    """Listing scripts contain the api key but also other 40-hex strings; keep the ones the
    search endpoint accepts (it answers with a jobPostings object)."""
    good = []
    for k in list(cands)[:6]:
        try:
            r = requests.post("https://jobs.b-ite.com/api/v1/postings/search",
                              json={"key": k, "channel": 0, "locale": config.get().local_languages[0] if config.get().local_languages else "en", "limit": 1},
                              headers={**H, "Content-Type": "application/json"}, timeout=TIMEOUT)
            if r.ok and "jobPostings" in r.json():
                good.append(k)
        except Exception:  # noqa: BLE001
            continue
    return good


def bite_api(src):
    """src: {institution, listings:[customer:file], keys?:[...]}. The api key sits in each
    customer's cs-assets listing script."""
    out, keys = [], set(src.get("keys", []))
    for listing in src.get("listings", []):
        cust, _, fname = listing.partition(":")
        r = get(f"https://cs-assets.b-ite.com/{cust}/jobs-api/{fname}.js")
        if r is not None and r.ok:
            keys.update(re.findall(r'(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])', r.text))
    keys = _working_keys(keys)
    for key in keys:
        page, total = 0, None
        while total is None or page < total:
            try:
                r = requests.post("https://jobs.b-ite.com/api/v1/postings/search",
                                  json={"key": key, "channel": 0, "locale": config.get().local_languages[0] if config.get().local_languages else "en", "offset": page, "limit": 100},
                                  headers={**H, "Content-Type": "application/json"}, timeout=TIMEOUT)
                d = r.json()
            except Exception:  # noqa: BLE001
                break
            postings = d.get("jobPostings", [])
            total = d.get("page", {}).get("total", len(postings))
            for p in postings:
                cat_parts, long_parts = [], []
                for v in (p.get("custom") or {}).values():
                    for x in (v if isinstance(v, list) else [v]):
                        x = str(x)
                        (cat_parts if len(x) <= 60 and "<" not in x else long_parts).append(x)
                body = BeautifulSoup(" ".join(long_parts), "lxml").get_text(" ", strip=True)
                out.append(item("bite_api", src["institution"], p["title"], p.get("url"),
                                posted=iso(p.get("startsOn") or p.get("createdOn")), deadline=iso(p.get("endsOn")),
                                category=",".join(cat_parts), location=(p.get("address") or {}).get("city", ""),
                                text=" ".join(p.get("keywords", [])) + " " + body))
            page += max(len(postings), 1)
            if not postings:
                break
    return out


def adsapi(src):
    out = []
    r = get(src["url"])
    if r is None or not r.ok:
        return out
    for a in r.json().get("advertisements", []):
        out.append(item("adsapi", src["institution"], a["title"], (a.get("url") or {}).get("href"),
                        posted=iso(a.get("channel0StartDate") or a.get("ctime")), deadline=iso(a.get("expires")),
                        category=a.get("custom_field1", ""), location=a.get("job_site", "")))
    return out


def bite_site(src):
    out, seen = [], set()
    for page in src.get("pages", []):
        r = get(page)
        if r is None or not r.ok:
            continue
        soup = BeautifulSoup(r.content, "lxml")
        for a in soup.find_all("a", href=True):
            if not re.search(r"/jobposting/[0-9a-f]{40}", a["href"]):
                continue
            u = urljoin(r.url, a["href"]).split("?")[0]
            if u in seen:
                continue
            seen.add(u)
            t = a.get_text(" ", strip=True) or a.get("title", "")
            out.append(item("bite_site", src["institution"], t, u))
    # titles on list pages are sometimes truncated or empty: fill from the detail page
    for it in out:
        if len(it["title"]) < 8:
            r = get(it["url"])
            if r is not None and r.ok:
                s = BeautifulSoup(r.text, "lxml")
                h = s.find(["h1", "title"])
                it["title"] = (h.get_text(" ", strip=True) if h else it["title"])[:200]
    return out


def rss(src):
    out = []
    r = get(src["url"])
    if r is None or not r.ok:
        return out
    soup = BeautifulSoup(r.content, "xml")
    for e in soup.find_all(["item", "entry"]):
        title = (e.find("title").get_text(" ", strip=True) if e.find("title") else "")
        link = e.find("link")
        url = (link.get("href") or link.get_text(strip=True)) if link else ""
        desc = e.find(["description", "summary", "content"])
        pub = e.find(["pubDate", "published", "updated", "date"])
        text = BeautifulSoup(desc.get_text(" ", strip=True), "lxml").get_text(" ", strip=True) if desc else ""
        pdt = None
        if pub:
            try:
                from dateutil import parser as dp
                pdt = dp.parse(pub.get_text(strip=True)).date().isoformat()
            except Exception:  # noqa: BLE001
                pdt = None
        out.append(item("rss", src["institution"], title, url, posted=pdt, text=text))
    return out


def sap_rss(src):
    return [dict(i, source="sap_rss") for i in rss(src)]


def html_list(src):
    """Anchors on a list page whose text looks like a posting; date is taken from the anchor's
    parent text when present (dd.mm.yyyy / yyyy-mm-dd)."""
    out, seen = [], set()
    r = get(src["url"])
    if r is None or not r.ok:
        return out
    soup = BeautifulSoup(r.content, "lxml")
    for a in soup.find_all("a", href=True):
        t = a.get_text(" ", strip=True)
        if not (14 < len(t) < 240):
            continue
        u = urljoin(r.url, a["href"]).split("#")[0]
        if u in seen or u.startswith(("mailto", "javascript")):
            continue
        if src.get("include") and not re.search(src["include"], u + " " + t, re.I):
            continue
        seen.add(u)
        ctx = a.find_parent(["li", "tr", "div", "article"])
        dates = re.findall(r"\d{1,2}\.\d{1,2}\.\d{4}|\d{4}-\d{2}-\d{2}", ctx.get_text(" ") if ctx else "")
        out.append(item("html_list", src["institution"], t, u, posted=iso(dates[0]) if dates else None))
    return out


ADAPTERS = {"bite_api": bite_api, "adsapi": adsapi, "bite_site": bite_site, "rss": rss,
            "sap_rss": sap_rss, "html_list": html_list}


# --------------------------------------------------------------------------- sources

def load_sources():
    """Institution sources (universities, research institutes, hospitals, public bodies): {adapter, institution, ...adapter args}, from the
    region pack's sources.json plus the user's profile/sources.json (scripts/config.py `sources()`)."""
    return config.get().sources()["institutions"]


def seen_state():
    p = WATCH / "seen.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def tracker_urls():
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import db
        return {(j.get("url") or "").split("?")[0].rstrip("/") for j in db.list_jobs()}
    except Exception:  # noqa: BLE001
        return set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--all-levels", action="store_true", help="also report non-student items")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None

    clf = Classifier()
    seen, in_tracker = seen_state(), tracker_urls()
    today = date.today().isoformat()
    items, errors, per_source = [], [], {}
    for src in load_sources():
        ad = src["adapter"]
        if only and ad not in only:
            continue
        try:
            got = ADAPTERS[ad](src)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{src['institution']} [{ad}]: {type(e).__name__}: {str(e)[:80]}")
            continue
        per_source[f"{src['institution']} [{ad}]"] = len(got)
        items.extend(got)

    sys.stdout.reconfigure(encoding="utf-8")
    results, ids = [], set()
    for it in items:
        if it["id"] in ids:
            continue
        ids.add(it["id"])
        c = clf.classify(it["title"], it.get("text", ""), it.get("category", ""))
        it.update(c)
        it["new"] = it["id"] not in seen
        it["in_tracker"] = (it["url"] or "").split("?")[0].rstrip("/") in in_tracker
        results.append(it)

    student = [r for r in results if r["levels"] and not r["excluded"]]
    new_student = [r for r in student if r["new"] and not r["in_tracker"]]
    new_student.sort(key=lambda r: (-r["prov_score"], r["institution"]))

    summary = {"date": today, "sources": len(per_source), "items": len(results),
               "student_level": len(student), "new_student_level": len(new_student), "errors": errors}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if a.no_write:
        for r in new_student[:40]:
            print(f"- [{r['prov_score']}] {r['institution']}: {r['title'][:90]} | {r['kind']} {r['pillars']} | {r['url']}")
        return 0

    WATCH.mkdir(parents=True, exist_ok=True)
    (WATCH / f"{today}.json").write_text(json.dumps(
        {"summary": summary, "per_source": per_source, "items": results if a.all_levels else student},
        ensure_ascii=False, indent=1), encoding="utf-8")
    for r in results:
        seen.setdefault(r["id"], {"first_seen": today, "institution": r["institution"], "title": r["title"][:120]})
    (WATCH / "seen.json").write_text(json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8")

    top = [r for r in new_student if r["prov_score"] >= 3]
    rest = len(new_student) - len(top)
    lines = [f"# Institution watch, {today}", "",
             f"{summary['sources']} sources polled, {summary['items']} postings read, "
             f"{summary['student_level']} at the levels sought, **{summary['new_student_level']} new** "
             f"({len(top)} with a provisional score of 3 or more are listed; {rest} lower-scored are on the dashboard's Watch page).", ""]
    if errors:
        lines += ["## Source errors", *[f"- {e}" for e in errors], ""]
    lines += ["## New postings at the levels sought (highest provisional score first)", ""]
    if not top:
        lines.append("None since the last run.")
    for r in top:
        dl = f", deadline {r['deadline']}" if r.get("deadline") else ""
        lines.append(f"- **{r['title'][:160]}** ({r['institution']}; {r['kind']}{dl}) "
                     f"[{', '.join(r['title_pillars'] or r['pillars']) or 'no pillar term'}] {r['url']}")
    d = ROOT / "digests"
    d.mkdir(exist_ok=True)
    (d / f"institution-watch-{today}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

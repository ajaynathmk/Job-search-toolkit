#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Intake (rules/pipeline.md, S20-S21): every student-level posting the two watches found becomes a tracker row, unscored, then its FULL JD
is fetched and cached, then the analyzer reads it. Nothing is dropped for being off-topic: the topic is decided from the full text.

  1. gather   all in-scope items of data/watch/*.json and data/jobwatch/*.json (the countries the profile searches; others are kept out by the region pack's scope)
  2. stub     one row per posting that is not in the tracker yet (matched by URL and by watch id): a thesis becomes a thesis row, anything else
              a job row. analysis_level='stub', no score, no verdict.
  3. fetch    the whole description from the posting itself (Workday and Bundesagentur APIs, ATS APIs, PDF, plain HTML), saved to
              jd/<Employer>_<slug>/description.md; jd_read=1 only after the file exists with real content; THE LINK RULE: url_verified only when
              the fetched text carries the posting's title. Unreadable twice -> analysis_level='unreadable' (it stays visible, never scored).
  4. analyse  scripts/analyze.py scores, categorises and sets the verdict from the full text.

    python scripts/intake.py run [--limit N] [--no-fetch] [--no-analyze]
    python scripts/intake.py retry          # re-fetch the stubs whose JD could not be read
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import db  # noqa: E402
import definitions as D  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
H = {"User-Agent": "Mozilla/5.0 (job-search-toolkit intake; personal use)"}
BA_HEAD = {**H, "X-API-Key": "jobboerse-jobsuche"}
TODAY = date.today().isoformat()
MAX_ATTEMPTS = 2

_COUNTRIES = config.resource("countries.json", {}).get("countries", [])


def country_of(location: str, source: str) -> str:
    """ISO code of the posting's country from its location text: the region pack's own hints first, then resources/countries.json (first match wins).
    A source the region pack lists as local (a national job board, its universities) with no readable place counts as the home country;
    anything else with a place we cannot read is 'ZZ' (unknown)."""
    cfg = config.get()
    loc = (location or "").lower()
    for code, rx in (cfg.region.get("country_hints") or {}).items():
        if not code.startswith("_") and re.search(rx, loc):
            return code.upper()
    for c in _COUNTRIES:
        rx = c["rx"]
        if re.search(rx, location or "") if "[A-Z]" in rx else re.search(rx, loc):
            return c["code"]
    home = (cfg.region.get("home_country") or "").upper()
    if home and (source in set(cfg.region.get("local_sources") or []) or not location):
        return home
    return "ZZ"


def fold(s: str) -> str:
    s = s.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def slug(s: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(s)).strip("-")[:n].strip("-")


def norm_url(u: str | None) -> str:
    return (u or "").split("?")[0].split("#")[0].rstrip("/")


# ----------------------------------------------------------------------------- 1. gather

def watch_items() -> list[dict]:
    seen_all, out = {}, {}
    for feed, origin in ((ROOT / "data" / "watch", "university"), (ROOT / "data" / "jobwatch", "company")):
        seen = json.loads((feed / "seen.json").read_text(encoding="utf-8")) if (feed / "seen.json").exists() else {}
        for f in sorted(feed.glob("20*.json")) if feed.exists() else []:
            for it in json.loads(f.read_text(encoding="utf-8")).get("items", []):
                it = dict(it)
                it["origin"] = origin
                it["first_seen"] = (seen.get(it["id"]) or {}).get("first_seen", f.stem)
                out[it["id"]] = it
    return [it for it in out.values() if D.is_student_level(it) and it.get("url")]


# ----------------------------------------------------------------------------- 2. stubs

def existing_index() -> tuple[set[str], set[str]]:
    urls, wids = set(), set()
    for j in db.list_jobs():
        urls.add(norm_url(j.get("url")))
        urls.add(norm_url(j.get("apply_url")))
        if j.get("watch_id"):
            wids.add(j["watch_id"])
    for t in db.list_thesis():
        urls.add(norm_url(t.get("posting_url")))
        if t.get("watch_id"):
            wids.add(t["watch_id"])
    urls.discard("")
    return urls, wids


def make_stub(it: dict, manual: dict | None) -> str | None:
    title = " ".join((it.get("title") or "").split())
    employer = " ".join((it.get("employer") or it.get("institution") or "").split()) or "(employer not shown)"
    h = hashlib.sha1((it["url"]).encode()).hexdigest()[:4]
    country = country_of(it.get("location", ""), it.get("source", ""))
    note = f"Found by the {it['origin']} watch ({it.get('source')}) on {it['first_seen']}; filed unscored, the full JD is fetched and analysed next (rules/pipeline.md S20-S22)."
    if manual:
        note += f" Earlier manual read: {manual.get('verdict')}: {manual.get('reason')}"
    if it["kind"] == "thesis" or it.get("kind") == "thesis":
        tid = f"th-{slug(employer, 22)}-{slug(title, 38)}-{h}"
        db.create_thesis({"id": tid, "title": title, "institution": employer, "department": it.get("category") or None, "location": it.get("location") or None,
                          "country": country, "source_type": "university" if it["origin"] == "university" else "company", "posting_kind": "advertised",
                          "posting_url": it["url"], "posted_at": it.get("posted"), "deadline": it.get("deadline"), "status": "lead", "watch_id": it["id"],
                          "analysis_level": "stub", "notes": note})
        return tid
    jid = f"w-{slug(employer, 20)}-{slug(title, 36)}-{h}"
    db.create_job({"id": jid, "title": title, "employer": employer, "location": it.get("location") or None, "country": country,
                   "source": f"{it['origin']}_watch", "date_found": it["first_seen"], "status": "open", "approval": "none", "url": it["url"],
                   "posted_at": it.get("posted"), "deadline": it.get("deadline"), "watch_id": it["id"], "analysis_level": "stub", "jd_read": 0, "notes": note})
    return jid


# ----------------------------------------------------------------------------- 3. fetch the full JD

def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "nav", "header", "footer", "noscript", "form", "svg"]):
        t.decompose()
    main = soup.select_one("main, article, [role=main], #content, .content, #main")
    node = main if main and len(main.get_text(strip=True)) > 600 else soup
    text = node.get_text("\n")
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    # TUM's Schwarzes Brett and similar portals wrap the posting in navigation and news headlines
    m = re.search(r"(?:Browse in News|Back to News Board|Zurück zu Nachrichten-Bereich)(.*?)(?:\nDrucken|\nPrint\b|\nAktuelles\n)", text, re.S)
    if m and len(m.group(1)) > 400:
        text = m.group(1)
    return text.strip()


def pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader
    rd = PdfReader(io.BytesIO(content))
    return re.sub(r"[ \t]+", " ", "\n".join((p.extract_text() or "") for p in rd.pages)).strip()


def decode(r) -> str:
    """The page as text. A response with no declared charset is decoded as UTF-8, not as the HTTP default Latin-1 (which turns every umlaut into 'Ã¤')."""
    ct = (r.headers.get("content-type") or "").lower()
    if "charset" not in ct:
        try:
            return r.content.decode("utf-8")
        except UnicodeDecodeError:
            return r.content.decode(r.apparent_encoding or "latin-1", "replace")
    return r.text


def xing_posting(html: str) -> str:
    """A xing.com/jobs page carries the posting as schema.org JSON-LD; the visible page is mostly 'Ähnliche Jobs'. Returns '' when there is none."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            d = json.loads(tag.string or "")
        except ValueError:
            continue
        for node in (d if isinstance(d, list) else [d]):
            if isinstance(node, dict) and node.get("@type") == "JobPosting":
                org = (node.get("hiringOrganization") or {}).get("name") or ""
                loc = node.get("jobLocation") or {}
                loc = loc[0] if isinstance(loc, list) and loc else loc
                addr = (loc.get("address") or {}) if isinstance(loc, dict) else {}
                head = f"{node.get('title') or ''}\n{org}\nLocation: {addr.get('addressLocality') or ''} {addr.get('addressCountry') or ''}\n"
                head += f"Posted: {node.get('datePosted') or ''}  Valid through: {node.get('validThrough') or ''}  Employment: {node.get('employmentType') or ''}\n\n"
                desc = BeautifulSoup(node.get("description") or "", "html.parser").get_text("\n")
                return head + re.sub(r"\n\s*\n+", "\n", desc)
    return ""


class Transient(Exception):
    """The site refused or rate-limited the request (a blocked LinkedIn/Xing page, HTTP 429): not the posting's fault, so it does not use up one of the two attempts."""


def fetch_full(url: str) -> tuple[str, str]:
    """(text, route). Raises on network trouble; returns '' text when the page has nothing readable."""
    m = re.match(r"https://(\w+)\.wd(\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)(/.*)", url)
    if m:
        t, w, site, path = m.groups()
        j = requests.get(f"https://{t}.wd{w}.myworkdayjobs.com/wday/cxs/{t}/{site}{path}", headers=H, timeout=60).json()["jobPostingInfo"]
        head = f"{j.get('title')}\nLocation: {j.get('location')} {j.get('additionalLocations') or ''}\nStart: {j.get('startDate')}  Posted: {j.get('postedOn')}  Req: {j.get('jobReqId')}\n"
        return head + BeautifulSoup(j.get("jobDescription") or "", "html.parser").get_text("\n"), "workday-api"
    m = re.search(r"arbeitsagentur\.de/jobsuche/jobdetail/([^/?]+)", url)
    if m:
        ref = m.group(1)
        d = requests.get("https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/" + base64.b64encode(ref.encode()).decode(), headers=BA_HEAD, timeout=40).json()
        head = f"{d.get('stellenangebotsTitel')}\n{d.get('firma')}\nBeginn: {(d.get('eintrittszeitraum') or {}).get('von')}  Befristung: {d.get('vertragsdauer')} {d.get('befristungInMonaten') or ''}\n"
        return head + (d.get("stellenangebotsBeschreibung") or ""), "bundesagentur-api"
    m = re.match(r"https://(?:job-boards|boards)\.greenhouse\.io/([^/]+)/jobs/(\d+)", url)
    if m:
        j = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}", headers=H, timeout=40).json()
        import html as _h
        return f"{j.get('title')}\n{(j.get('location') or {}).get('name', '')}\n" + BeautifulSoup(_h.unescape(j.get("content") or ""), "html.parser").get_text("\n"), "greenhouse-api"
    m = re.match(r"https://jobs\.lever\.co/([^/]+)/([0-9a-f-]+)", url)
    if m:
        j = requests.get(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}", headers=H, timeout=40).json()
        return f"{j.get('text')}\n" + (j.get("descriptionPlain") or "") + "\n" + "\n".join(f"{x.get('text')}\n" + BeautifulSoup(x.get("content") or "", "html.parser").get_text("\n") for x in j.get("lists", [])), "lever-api"
    m = re.match(r"https://jobs\.smartrecruiters\.com/([^/]+)/(\d+)", url)
    if m:
        j = requests.get(f"https://api.smartrecruiters.com/v1/companies/{m.group(1)}/postings/{m.group(2)}", headers=H, timeout=40).json()
        secs = (j.get("jobAd") or {}).get("sections") or {}
        return f"{j.get('name')}\n" + "\n".join(BeautifulSoup((v or {}).get("text") or "", "html.parser").get_text("\n") for v in secs.values()), "smartrecruiters-api"
    m = re.search(r"linkedin\.com/jobs/view/(?:[\w-]*-)?(\d{6,})", url)
    if m:                                                    # LinkedIn's own guest endpoint for a posting: the full text, no sign-in
        import time
        for attempt in range(3):
            r = requests.get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{m.group(1)}", headers=H, timeout=45)
            soup = BeautifulSoup(r.text, "html.parser")
            body = soup.select_one(".show-more-less-html__markup") or soup.select_one(".description__text")
            if r.status_code == 404 or (r.status_code == 200 and body is not None):
                break
            time.sleep(4 * (attempt + 1))
        else:
            raise Transient(f"LinkedIn answered HTTP {r.status_code} without the posting text")
        if r.status_code == 200 and body is not None:
            title = (soup.select_one(".top-card-layout__title") or soup.select_one("h2") or body).get_text(" ", strip=True)
            org = soup.select_one(".topcard__org-name-link") or soup.select_one(".top-card-layout__card a")
            crit = "\n".join(li.get_text(" ", strip=True) for li in soup.select(".description__job-criteria-item"))
            return f"{title}\n{org.get_text(' ', strip=True) if org else ''}\n{crit}\n\n" + body.get_text("\n", strip=True), "linkedin-guest"
    r = requests.get(url, headers=H, timeout=45, allow_redirects=True)
    if r.content[:5] == b"%PDF":
        return pdf_text(r.content), "pdf"          # decided by the file itself: some .pdf links return an HTML page
    html = decode(r)
    text = (xing_posting(html) if re.search(r"xing\.com/jobs/", url) else "") or clean_html(html)
    if len(text.strip()) < 300 and "xing.com" in url:
        raise Transient(f"Xing answered with a page of {len(text.strip())} characters (blocked or not rendered)")
    return text, "html"


def title_match(title: str, text: str) -> bool:
    toks = [t for t in re.findall(r"[a-z0-9]+", fold(title)) if len(t) >= 4]
    if not toks:
        return True
    f = fold(text)
    return sum(1 for t in toks if t in f) / len(toks) >= 0.6


def jd_folder(row: dict) -> str:
    emp = row.get("employer") or row.get("institution") or "employer"
    return "jd\\" + re.sub(r"[^A-Za-z0-9]+", "-", unicodedata.normalize("NFKD", emp).encode("ascii", "ignore").decode()).strip("-")[:30] + "_" + \
        re.sub(r"[^A-Za-z0-9]+", "-", unicodedata.normalize("NFKD", row["title"]).encode("ascii", "ignore").decode()).strip("-")[:56] + "-" + hashlib.sha1((row.get("url") or row.get("posting_url") or row["id"]).encode()).hexdigest()[:4]


def s_deferrals(row: dict) -> int:
    return (row.get("notes") or "").count("[intake] fetch deferred")


def attempts_of(row: dict) -> int:
    return len(re.findall(r"\[intake\] fetch attempt", row.get("notes") or ""))


def fetch_one(ref: str) -> dict:
    """Fetch and cache one stub's JD. Returns {'ref', 'ok', 'reason'}; the caller writes the row."""
    kind = "thesis" if ref.startswith("th-") else "job"
    row = db.get_thesis(ref) if kind == "thesis" else db.get_job(ref)
    url = row.get("posting_url") if kind == "thesis" else row.get("url")
    try:
        text, route = fetch_full(url)
    except Transient as e:
        return {"ref": ref, "ok": False, "transient": True, "reason": str(e)[:120]}
    except Exception as e:  # noqa: BLE001
        return {"ref": ref, "ok": False, "reason": f"{type(e).__name__}: {str(e)[:90]}"}
    text = text.strip()
    if len(text) < db.JD_MIN_CHARS:
        return {"ref": ref, "ok": False, "reason": f"only {len(text)} readable characters ({route})"}
    import analyze
    if not analyze.text_quality_ok(text):
        return {"ref": ref, "ok": False, "reason": f"the content is not readable text (binary or garbled, {route})"}
    folder = jd_folder(row)
    path = ROOT / folder.replace("\\", "/")
    path.mkdir(parents=True, exist_ok=True)
    title = row["title"]
    (path / "description.md").write_text(f"# {title} — {row.get('employer') or row.get('institution')}\n\nSource: {url}\nFetched: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} ({route})\n\n---\n\n{text}\n", encoding="utf-8")
    return {"ref": ref, "ok": True, "folder": folder, "route": route, "title_ok": title_match(title, text), "chars": len(text)}


MOJIBAKE = re.compile(r"Ã[\u0080-\u00bf]|â€")
SIMILAR_JOBS = re.compile(r"(?:^|\n)(?:Ähnliche Jobs|Ã\u0084hnliche Jobs|Similar jobs)\n")


def defective_cache(row: dict) -> str:
    """Why a cached JD cannot be trusted ('' when it can): garbled umlauts, or a Xing page whose text is mostly other postings."""
    f = db.jd_file(row)
    if f is None or not f.exists():
        return ""
    t = f.read_text(encoding="utf-8", errors="replace")
    if len(MOJIBAKE.findall(t)) >= 5:
        return "garbled umlauts (UTF-8 decoded as Latin-1)"
    if SIMILAR_JOBS.search(t) and "xing.com" in (row.get("url") or row.get("posting_url") or ""):
        return "Xing page text with lists of other jobs mixed in"
    return ""


def repair(limit: int | None = 150, analyze_after: bool = True) -> dict:
    """Fetch every defective cached JD again from its own posting (the first fetch was defective, so this is a repair, not a second read) and analyse the repaired text."""
    todo = [r["id"] for r in db.list_jobs() + db.list_thesis() if defective_cache(r)]
    if limit:
        todo = todo[:limit]
    fixed, failed = [], []
    with ThreadPoolExecutor(4) as ex:
        for res in ex.map(fetch_one, todo):
            if res["ok"]:
                record_fetch(res)
                fixed.append(res["ref"])
            else:
                failed.append(res["ref"])
    out = {"defective": len(todo), "repaired": len(fixed), "still_defective": len(failed)}
    if analyze_after and fixed:
        import analyze
        out["analysis"] = analyze.run({"stub", "legacy", "auto", "reviewed"}, fixed, None, False)
    return out


def record_fetch(res: dict) -> None:
    ref = res["ref"]
    kind = "thesis" if ref.startswith("th-") else "job"
    row = db.get_thesis(ref) if kind == "thesis" else db.get_job(ref)
    upd = db.update_thesis if kind == "thesis" else db.update_job
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if res["ok"]:
        ch = {"jd_path": res["folder"], "last_checked": TODAY}
        if kind == "job":
            ch.update({"jd_read": 1, "jd_fetched_at": now})
            if res["title_ok"]:
                ch["url_verified"] = TODAY
        else:
            if res["title_ok"]:
                ch["url_verified"] = TODAY
        if row.get("analysis_level") == "unreadable":
            ch["analysis_level"] = "stub"
        upd(ref, ch)
    elif res.get("transient") and s_deferrals(row) < 5:
        upd(ref, {"notes": (row.get("notes") or "") + f"\n[intake] fetch deferred on {TODAY} (not counted as an attempt): {res['reason']}"})
    else:
        n = attempts_of(row) + 1
        note = (row.get("notes") or "") + f"\n[intake] fetch attempt {n} on {TODAY} failed: {res['reason']}"
        ch = {"notes": note}
        if n >= MAX_ATTEMPTS:
            ch["analysis_level"] = "unreadable"
        upd(ref, ch)


# ----------------------------------------------------------------------------- run

def run(limit: int | None, fetch: bool, analyze_after: bool) -> dict:
    db.init_db()
    manual = json.loads((ROOT / "data" / "reviewed.json").read_text(encoding="utf-8")) if (ROOT / "data" / "reviewed.json").exists() else {}
    urls, wids = existing_index()
    items = watch_items()
    new = [it for it in items if it["id"] not in wids and norm_url(it["url"]) not in urls]
    seen_urls: set[str] = set()
    uniq = []
    for it in new:                                  # the same posting can come from two sources
        u = norm_url(it["url"])
        if u not in seen_urls:
            seen_urls.add(u)
            uniq.append(it)
    if limit:
        uniq = uniq[:limit]
    created = [make_stub(it, manual.get(it["id"])) for it in uniq]
    created = [c for c in created if c]
    # every stub still without a cached JD (new ones, and earlier failures that have attempts left)
    pending = []
    for j in db.list_jobs():
        if j.get("analysis_level") == "stub" and not db.jd_cache_ok(j)[0]:
            pending.append(j["id"])
    for t in db.list_thesis():
        if t.get("analysis_level") == "stub" and not db.jd_cache_ok(t)[0]:
            pending.append(t["id"])
    fetched = failed = 0
    if fetch and pending:
        with ThreadPoolExecutor(8) as ex:
            for res in ex.map(fetch_one, pending):
                record_fetch(res)
                fetched += res["ok"]
                failed += not res["ok"]
                if (fetched + failed) % 50 == 0:
                    print(f"  fetched {fetched} failed {failed} of {len(pending)}", flush=True)
    analysed = {}
    if analyze_after:
        import analyze
        analysed = analyze.run({"stub"}, None, None, False)
    repaired = repair(120, analyze_after) if fetch else {}
    return {"watch_items_student_level": len(items), "already_in_tracker": len(items) - len(new), "stubs_created": len(created), "jd_fetched": fetched, "jd_failed": failed, "analysis": analysed, "repair": repaired}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "retry", "repair"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--no-analyze", action="store_true")
    a = ap.parse_args()
    config.require_configured()
    sys.stdout.reconfigure(encoding="utf-8")
    if a.cmd == "retry":
        for tbl in (db.list_jobs(), db.list_thesis()):
            for r in tbl:
                if r.get("analysis_level") == "unreadable":
                    (db.update_thesis if r["id"].startswith("th-") else db.update_job)(r["id"], {"analysis_level": "stub"})
    if a.cmd == "repair":
        print(json.dumps(repair(a.limit or None, not a.no_analyze), indent=1, ensure_ascii=False, default=str))
        return 0
    print(json.dumps(run(a.limit, not a.no_fetch, not a.no_analyze), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

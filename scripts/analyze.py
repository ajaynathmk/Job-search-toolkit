#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The analysis stage (rules/pipeline.md, S22): read the FULL cached JD, then wall-check, classify, compare with the CV, score and decide.

What it does for one role (a job row or a thesis row), always from the whole description text on disk, never a title or summary:
  1. walls: what the posting demands that the owner cannot meet (a language level, work authorization, a credential, clearance, a country outside
     the search), quoting the sentence. The walls come from the region pack, the domain file and the profile (scripts/config.py).
  2. language requirements, checked against the owner's own declared levels (profile.languages): an explicit level far above theirs is a wall,
     one level above caps the verdict at BACKUP, an unquantified "very good X" costs a point
  3. deadline, and whether it has passed
  4. category and sub-field, by weighted terms in the title and the text (profile/domain.json, written from the CV during onboarding)
  5. the CV comparison (domain.cv_evidence): what the posting asks for that the CV covers, partly covers, or lacks
  6. the score from the components below, with the breakdown stored; the work-authorization route adjusts it
  7. the verdict (APPLY, BACKUP, PLAN, LATER, PASS, BLOCKED, EXPIRED) and a one-paragraph reason
It writes them with the proof the database demands (the JD hash, the level, the breakdown). 'auto' means this script read the full text; 'reviewed'
means a Claude session read it too (`show`, then `review`) and confirmed or overrode.

Scores are dynamic: every re-analysis compares with the stored score, appends to score_history and sets score_flag when it moved (the JD changed,
the configuration changed, the posting got older, a deadline passed). A reviewed verdict is never overwritten; the flag says the script now
disagrees and the row goes back to review.

    python scripts/analyze.py run [--levels stub,legacy,auto] [--ids a,b] [--limit N] [--dry]
    python scripts/analyze.py show <id>                  # prints the full JD, records a Claude read receipt
    python scripts/analyze.py explain <id>               # the analysis of the cached JD, nothing written
    python scripts/analyze.py review <id> --verdict APPLY --reason "..." [--score N] [--category c --subfield s]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import db  # noqa: E402
import definitions as D  # noqa: E402

ROOT = config.ROOT
TODAY = date.today()


def fold(s: str) -> str:
    s = s.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def rx(pattern: str, flags: int = re.S) -> re.Pattern:
    """Compile a configured pattern: it is written in plain letters, matched against folded text, so umlauts and accents in it are folded too."""
    return re.compile(fold(pattern), flags)


# ----------------------------------------------------------------------------- reading the cached JD

FOOTER = ("ähnliche jobs", "similar jobs", "terms & conditions", "datenschutz", "privacy policy", "alle stellenangebote", "unternehmens-details", "offres similaires",
          "empleos similares", "cookie settings", "cookie-einstellungen")


def text_quality_ok(t: str) -> bool:
    """False for binary or garbled content (a spreadsheet saved as text, a PDF with no text layer)."""
    if len(t) < 200:
        return False
    sample = t[:6000]
    if len(re.findall(r"Ã[\u0080-¿]|â€", sample)) >= 3:
        return False                      # UTF-8 decoded as Latin-1: every accent is wrong, so every word the analysis looks for can be wrong
    printable = sum(1 for ch in sample if ch.isprintable() or ch in "\n\t")
    words = len(re.findall(r"[^\W\d_]{3,}", sample))
    return printable / len(sample) >= 0.92 and words >= 30


def read_jd(row: dict) -> str:
    f = db.jd_file(row)
    if f is None or not f.exists():
        return ""
    t = f.read_text(encoding="utf-8", errors="ignore")
    t = re.sub(r"^#[^\n]*\n+Source:[^\n]*\n(?:Fetched:[^\n]*\n)?(?:Found via:[^\n]*\n)?(?:Extracted[^\n]*\n)?-*\n", "", t, count=1)
    if "LinkedIn" in t[:900]:
        t2 = re.sub(r"^.*?(Bewerben\s+Speichern|Apply\s+Save)(\s+Ihre Eignung mit KI bewerten.*?Lebenslauf anpassen)?", "", t, count=1, flags=re.S)
        if t2 == t:                       # guest page: the login wall repeats and "Save" is not next to "Apply"; drop through the last wall at the top, or the privacy word in it cuts the real text at FOOTER
            walls = list(re.finditer(r"von LinkedIn zu\.?|LinkedIn's[^\n]{0,60}Cookie Policy\.?", t))
            walls = [w for w in walls if w.end() < 2500]
            if walls:
                t2 = t[walls[-1].end():]
        t = t2
    if "Navigation überspringen" in t[:300] or "Skip navigation" in t[:300]:
        t = re.sub(r"^.*?(Stellenbeschreibung|About this job|Über diesen Job|Beschreibung)", "", t, count=1, flags=re.S)
    if not text_quality_ok(t):
        return ""
    if "xing.com" in (row.get("url") or row.get("posting_url") or "") and re.search(r"(?:^|\n)(?:Ähnliche Jobs|Similar jobs)\n", t):
        return ""                       # a page whose text is mostly other postings: nothing here can be attributed to this role
    low = t.lower()
    cuts = [low.find(m, 700) for m in FOOTER]
    cuts = [c for c in cuts if c > 0]
    if cuts:
        t = t[:min(cuts)]
    return t.strip()


def quote(s: str, n: int = 230) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n - 1] + "…"


# ----------------------------------------------------------------------------- the posting's own language

_LANG = config.resource("languages.json", {})
STOP = {code: tuple(v.get("stop", ())) for code, v in (_LANG.get("languages") or {}).items() if v.get("stop")}


def detect_lang(text: str) -> str:
    words = re.findall(r"[a-z]+", fold(text[:6000]))
    n = max(len(words), 1)
    sc = {k: sum(words.count(w) for w in ws) / n for k, ws in STOP.items()}
    return max(sc, key=sc.get) if sc else "en"


NICE = re.compile(r"von vorteil|wuenschenswert|ideal|\bplus\b|nice to have|desirable|advantage|bonus|preferred|bevorzugt|souhait|apprecie|valuable|helpful|hilfreich|vorteilhaft|"
                  r"nicht zwingend|not essential|gerne|welcome|wuenschen|optional|un plus|deseable|valorable|gradito|wenselijk|a mais-valia")


class Doc:
    """The full JD, folded for matching, with a map back to the original so a match can be quoted as written.
    Matching on the whole text (not on sentences) is deliberate: web text has no reliable sentence breaks, and
    abbreviations such as 'e.g.' or 'approx.' would cut a requirement in two."""

    def __init__(self, text: str):
        self.text = text
        out, idx = [], []
        for i, ch in enumerate(text):
            f = fold(ch)
            out.append(f)
            idx.extend([i] * len(f))
        self.f = "".join(out)
        self.idx = idx

    def orig(self, a: int, b: int, pad: int = 0) -> str:
        a = self.idx[min(max(a, 0), len(self.idx) - 1)] if self.idx else 0
        b = self.idx[min(max(b - 1, 0), len(self.idx) - 1)] + 1 if self.idx else 0
        return quote(self.text[max(0, a - pad): b + pad], 240)

    def window(self, a: int, b: int, pad: int = 70) -> str:
        return self.f[max(0, a - pad): b + pad]

    def search(self, pattern, flags: int = re.S):
        return (pattern if isinstance(pattern, re.Pattern) else re.compile(pattern, flags)).search(self.f)

    def finditer(self, pattern, flags: int = re.S):
        return (pattern if isinstance(pattern, re.Pattern) else re.compile(pattern, flags)).finditer(self.f)

    def nice_near(self, a: int, b: int) -> bool:
        """Is the requirement at [a, b) marked optional? Only its own line counts (a marker on the next bullet is about the next bullet);
        on a flat text with no line breaks, 70 characters either side."""
        ls = self.f.rfind("\n", 0, a) + 1
        le = self.f.find("\n", b)
        le = len(self.f) if le < 0 else le
        seg = self.f[ls:le]
        if len(seg) > 300:
            seg = self.f[max(0, a - 70): b + 70]
        return bool(NICE.search(seg))


# ----------------------------------------------------------------------------- language requirements (checked against the owner's own levels)

_PH = _LANG.get("phrases", {})
_ORDER = {"none": 0, "advantage": 1, "good": 2, "b1": 2, "very_good": 3, "b2": 3, "hard": 4}
# What a posting's wording asks, on the same ladder as the owner's levels (config.LEVELS: none a1 a2 b1 b2 c1 c2 native = 0..7): "hard" = C1 or above or native,
# an unquantified "very good" is read as B2 and "good" as B1. A stated level two or more steps above the owner's is a wall, one step above caps the verdict.
_REQ_INDEX = {"hard": 5, "b2": 4, "b1": 3, "very_good": 4, "good": 3, "advantage": 0, "none": 0}
LEVEL_WORDS = {"hard": "C1 or above (or native)", "very_good": "very good", "b2": "B2", "b1": "B1", "good": "good", "advantage": "an advantage", "none": "none"}
_LANG_RX: dict[str, list[tuple[re.Pattern, str]]] = {}


def _lang_patterns(code: str) -> list[tuple[re.Pattern, str]]:
    if code in _LANG_RX:
        return _LANG_RX[code]
    info = (_LANG.get("languages") or {}).get(code)
    if not info:
        _LANG_RX[code] = []
        return []
    a = "(?:" + "|".join(re.escape(x) for x in info["anchors"]) + ")"
    nat, hard, vg, good = _PH.get("native", ""), _PH.get("hard", ""), _PH.get("very_good", ""), _PH.get("good", "")
    pats = [
        (rf"{a}.{{0,60}}\bc[12]\b|\bc[12]\b.{{0,60}}{a}|(?:{nat}).{{0,25}}{a}|{a}.{{0,25}}(?:{nat})|{a}.{{0,40}}(?:{hard})|(?:{hard}).{{0,40}}{a}", "hard"),
        (rf"{a}.{{0,60}}\bb2\b|\bb2\b.{{0,60}}{a}", "b2"),
        (rf"{a}.{{0,60}}\bb1\b|\bb1\b.{{0,60}}{a}|grundkenntnisse.{{0,20}}{a}|basic {a}", "b1"),
        (rf"(?:{vg})[^.]{{0,20}}{a}|{a}.{{0,30}}(?:{vg})|{a}.{{0,20}}fluent", "very_good"),
        (rf"(?:{good})[^.]{{0,12}}{a}|{a} (?:language )?skills|kenntnisse der {a}en sprache|{a}kenntnisse|knowledge of {a}", "good"),
    ]
    _LANG_RX[code] = [(re.compile(p, re.S), lvl) for p, lvl in pats]
    return _LANG_RX[code]


def language_requirement(doc: Doc, code: str) -> dict:
    """{'level': hard | very_good | b2 | b1 | good | advantage | none, 'quote': ...} for one language. 'hard' = C1/C2/native/negotiation level."""
    best = {"level": "none", "quote": ""}
    info = (_LANG.get("languages") or {}).get(code)
    if not info:
        return best
    anchor = re.compile("|".join(re.escape(x) for x in info["anchors"]))
    for g in anchor.finditer(doc.f):
        win_a, win_b = max(0, g.start() - 90), g.end() + 110
        w = doc.f[win_a:win_b]
        nice = doc.nice_near(g.start(), g.end())
        for pat, level in _lang_patterns(code):
            m = pat.search(w)
            if m:
                if level == "hard" and re.search(r"(?:" + _PH.get("native", "x") + r").{0,40}\bb[12]\b|\bb[12]\b.{0,40}(?:" + _PH.get("native", "x") + r")|native.{0,30}or.{0,30}\bb[12]\b", w, re.S):
                    level = "b2"           # 'native or at least B2' means B2 is enough
                lvl = ("advantage" if nice else level) if level in ("very_good", "good", "hard") else level
                if _ORDER[lvl] > _ORDER[best["level"]]:
                    best = {"level": lvl, "quote": doc.orig(win_a + m.start(), win_a + m.end(), 60)}
                break
    return best


_COUNTRY_LANGS = config.resource("country_languages.json", {}).get("countries", {})


def language_checks(doc: Doc, posting_lang: str, country: str = "ZZ") -> list[dict]:
    """For every language the owner's search is exposed to (the region's local languages, the languages of the posting's own country, the language
    the posting is written in, plus English when the owner's English is below C1), what the posting demands and what that means for the owner's own
    level: effect = wall | cap | penalty | ok."""
    cfg = config.get()
    mine = cfg.user_languages
    tracked = list(dict.fromkeys(cfg.local_languages + list(_COUNTRY_LANGS.get(country, [])) + ([posting_lang] if posting_lang != "en" else [])
                                 + (["en"] if mine.get("en", 0) < 5 else [])))
    tracked = [c for c in tracked if c in (_LANG.get("languages") or {})]
    out = []
    for code in tracked:
        req = language_requirement(doc, code)
        if req["level"] in ("none", "advantage"):
            out.append({"code": code, "name": _LANG["languages"].get(code, {}).get("name", code), "level": req["level"], "quote": req["quote"], "effect": "ok", "mine": mine.get(code, 0)})
            continue
        need, have = _REQ_INDEX[req["level"]], mine.get(code, 0)
        explicit = req["level"] in ("hard", "b2", "b1")
        diff = need - have
        effect = "ok"
        if explicit and diff >= 2:
            effect = "wall"
        elif not explicit and diff >= 3:
            effect = "wall"
        elif explicit and diff == 1:
            effect = "cap"
        elif diff >= 1:
            effect = "penalty"
        out.append({"code": code, "name": _LANG["languages"].get(code, {}).get("name", code), "level": req["level"], "quote": req["quote"], "effect": effect, "mine": have})
    return out


OTHER_LANG_RX = {c: v["anchors"] for c, v in (_LANG.get("languages") or {}).items()}


def other_language_bar(doc: Doc, posting_lang: str, tracked: set[str]) -> str | None:
    """Languages the posting asks for that are not among those the search already checks: reported as a flag, not a wall."""
    mine = config.get().user_languages
    out = []
    for code, anchors in OTHER_LANG_RX.items():
        if code in tracked or mine.get(code, 0) >= 3:
            continue
        for m in doc.finditer("|".join(re.escape(a) for a in anchors)):
            w = doc.window(m.start(), m.end(), 60)
            if re.search(r"fluent|required|mastery|native|proficien|speak|spoken|written|b2|c1|c2|erforderlich|exig|requis|nivel|level|maitrise|courant", w):
                lvl = re.search(r"\b([abc][12])\b", w)
                out.append(f"{_LANG['languages'][code]['name']} {lvl.group(1).upper() if lvl else 'required'}" + (" (advantage)" if NICE.search(w) else ""))
                break
    if posting_lang not in ("en",) and posting_lang not in tracked and posting_lang in _LANG.get("languages", {}) and mine.get(posting_lang, 0) < 3:
        name = _LANG["languages"][posting_lang]["name"]
        if not any(o.startswith(name) for o in out):
            out.append(f"{name} (posting written in {name})")
    return "; ".join(out) or None


# ----------------------------------------------------------------------------- walls

def _when_ok(when: dict, ctx: dict) -> bool:
    """A wall or route rule applies only when its `when` conditions hold. Keys: country, not_country (lists of ISO codes), kind (list), authorization
    (list of profile work_authorization statuses), needs_authorization (bool), stage (list of career stages), employer_re / url_re (regex)."""
    if not when:
        return True
    if "any" in when and not any(_when_ok(w, ctx) for w in when["any"]):
        return False                        # {"any": [{...}, {...}]}: at least one of the alternatives must hold
    cfg = config.get()
    home = (cfg.region.get("home_country") or "").upper()          # "__home__" in a country list stands for the home market of the first region pack
    countries = lambda key: [home if c == "__HOME__" else c for c in (x.upper() for x in when[key])]  # noqa: E731
    if "country" in when and ctx["country"] not in countries("country"):
        return False
    if "not_country" in when and ctx["country"] in countries("not_country"):
        return False
    if "kind" in when and ctx["kind"] not in when["kind"]:
        return False
    if "authorization" in when and cfg.work_authorization.get("status") not in when["authorization"]:
        return False
    if "needs_authorization" in when and cfg.needs_authorization != bool(when["needs_authorization"]):
        return False
    if "stage" in when and cfg.profile.get("career_stage") not in when["stage"]:
        return False
    if "employer_re" in when and not rx(when["employer_re"]).search(fold(ctx.get("employer") or "")):
        return False
    if "url_re" in when and not rx(when["url_re"]).search((ctx.get("url") or "").lower()):
        return False
    if "source_re" in when and not rx(when["source_re"]).search((ctx.get("source") or "").lower()):
        return False
    if "text_re" in when and not rx(when["text_re"]).search(ctx.get("text") or ""):
        return False
    if "not_text_re" in when and rx(when["not_text_re"]).search(ctx.get("text") or ""):
        return False
    return True


def find_walls(doc: Doc, langs: list[dict], country: str, ctx: dict) -> list[dict]:
    cfg = config.get()
    out = []
    scope = cfg.scope_countries
    if scope and country not in scope and country not in ("ZZ", ""):
        out.append({"wall": f"Outside the countries searched ({', '.join(scope)}): the posting is in {country}", "quote": f"location in {country}", "route_block": cfg.needs_authorization})
    for L in langs:
        if L["effect"] == "wall":
            out.append({"wall": f"{L['name']} {LEVEL_WORDS[L['level']]} required, the profile says {config.LEVELS[L['mine']].upper()}", "quote": L["quote"]})
    for w in cfg.walls:
        if not _when_ok(w.get("when") or {}, ctx):
            continue
        pattern = rx(w["re"])
        unless = rx(w["unless_re"]) if w.get("unless_re") else None
        for m in doc.finditer(pattern):
            win = doc.window(m.start(), m.end(), 80)
            if w.get("ignore_if_optional", True) and NICE.search(doc.window(m.start(), m.end(), 25)):
                continue
            if unless and unless.search(win):
                continue
            out.append({"wall": w["label"], "quote": doc.orig(m.start(), m.end(), 70), "route_block": bool(w.get("route_block"))})
            break
    return out


# ----------------------------------------------------------------------------- deadline

MONTHS = {"jan": 1, "janv": 1, "ene": 1, "gen": 1, "feb": 2, "fev": 2, "mar": 3, "mrt": 3, "maer": 3, "apr": 4, "avr": 4, "abr": 4, "mai": 5, "may": 5, "mag": 5, "mei": 5,
          "jun": 6, "juin": 6, "giu": 6, "jul": 7, "juil": 7, "lug": 7, "aug": 8, "ago": 8, "aou": 8, "sep": 9, "sept": 9, "set": 9, "okt": 10, "oct": 10, "ott": 10,
          "nov": 11, "dez": 12, "dec": 12, "dic": 12}


def find_deadline(text: str, row_deadline: str | None) -> tuple[str | None, bool]:
    dates = []
    f = fold(text)
    trig = (r"bewerbungsfrist|bewerbungsschluss|deadline|apply by|application (deadline|closing)|bewerben bis|bewerbung bis|bis zum|closing date|applications? close|frist|"
            r"date limite|candidater avant|fecha limite|scadenza|candidature entro|sluitingsdatum|uiterlijk|prazo|apply before|submit (your )?application by|due date|closes on")
    for m in re.finditer(trig, f):
        seg = f[m.end(): m.end() + 60]
        for d in re.finditer(r"(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})|(\d{4})-(\d{2})-(\d{2})|(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\.?,?\s+(\d{4})|([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})|(\d{1,2})/(\d{1,2})/(\d{4})", seg):
            try:
                if d.group(1):
                    dates.append(date(int(d.group(3)), int(d.group(2)), int(d.group(1))))
                elif d.group(4):
                    dates.append(date(int(d.group(4)), int(d.group(5)), int(d.group(6))))
                elif d.group(7) and d.group(8)[:3] in MONTHS:
                    dates.append(date(int(d.group(9)), MONTHS[d.group(8)[:3]], int(d.group(7))))
                elif d.group(10) and d.group(10)[:3] in MONTHS:
                    dates.append(date(int(d.group(12)), MONTHS[d.group(10)[:3]], int(d.group(11))))
                elif d.group(13):
                    a, b2 = int(d.group(13)), int(d.group(14))
                    # month/day/year (US) when the first number cannot be a month, else day/month/year; ambiguous ones use the profile's region habit
                    us = config.get().region.get("date_order", "dmy") == "mdy"
                    mm, dd = (a, b2) if (us and a <= 12) or b2 > 12 else (b2, a)
                    dates.append(date(int(d.group(15)), mm, dd))
            except ValueError:
                pass
            break
    if row_deadline and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row_deadline)[:10]):
        dates.append(date.fromisoformat(str(row_deadline)[:10]))
    dates = [d for d in dates if d.year >= 2024]
    if not dates:
        return None, False
    future = sorted(d for d in dates if d >= TODAY)
    if future:
        return future[0].isoformat(), False
    return max(dates).isoformat(), True


# ----------------------------------------------------------------------------- classification (the owner's field, from profile/domain.json)

def _subfield_terms() -> dict[str, list[tuple[re.Pattern, int]]]:
    out = {}
    for s in config.get().domain["subfields"]:
        w = int(s.get("weight", 3))
        out[s["id"]] = [(rx(t, re.S), w) for t in (s.get("terms") or [])]
    return out


def classify(title: str, text: str) -> tuple[str, str | None, dict]:
    cfg = config.get()
    ft, fb = fold(title), fold(text)
    terms = _subfield_terms()
    scores = {}
    for sf, plist in terms.items():
        sc = 0
        for pat, w in plist:
            sc += 3 * w * min(len(pat.findall(ft)), 1) + w * min(len(pat.findall(fb)), 4)
        scores[sf] = sc
    roles = {k: v.get("role", "other") for k, v in cfg.subfields.items()}
    own = [k for k in scores if roles.get(k) in ("core", "bridge")]
    other = [k for k in scores if k not in own]
    order = cfg.tie_order
    cat_of = {k: v["category"] for k, v in cfg.subfields.items()}
    default_cat = next((c["id"] for c in cfg.domain["categories"] if c.get("fit") == "none"), cfg.domain["categories"][-1]["id"])
    if not scores:
        return default_cat, None, scores
    for ov in cfg.domain.get("classification_overrides") or []:      # e.g. bench work with no computational part is not the owner's field
        sf = ov["subfield"]
        if scores.get(sf, 0) >= ov.get("min", 4) and not (ov.get("unless_re") and re.search(fold(ov["unless_re"]), fb)) \
                and scores[sf] >= ov.get("ratio_vs_own", 0.5) * max([scores[k] for k in own] or [0]):
            return cat_of.get(sf, default_cat), sf, scores
    own_best = max(own, key=lambda k: (scores[k], -order.index(k))) if own else None
    other_best = max(other, key=lambda k: (scores[k], -order.index(k))) if other else None
    if own_best is None:
        best = other_best
    elif other_best is None:
        best = own_best
    else:
        best = own_best if scores[own_best] >= 5 and scores[own_best] >= 0.7 * scores[other_best] else other_best
    if best is None or scores[best] < 2:
        return default_cat, None, scores
    if best in own and scores[best] < 5 and other_best is not None:
        best = other_best if scores[other_best] >= scores[own_best] else best
    return cat_of[best], best, scores


# ----------------------------------------------------------------------------- CV comparison

def cv_compare(doc: Doc) -> dict:
    covered, partial, gaps = [], [], []
    for e in config.get().cv_evidence:
        m = doc.search(rx(e["re"]))
        if not m:
            continue
        asked = "nice" if doc.nice_near(m.start(), m.end()) else "must"
        item = {"term": e["term"], "evidence": e.get("evidence", ""), "asked": asked, "where": doc.orig(m.start(), m.end(), 50)}
        {"covered": covered, "partial": partial, "gap": gaps}[e["status"]].append(item)
    must_gaps = [g for g in gaps if g["asked"] == "must"]
    total_must = len(must_gaps) + sum(1 for x in covered + partial if x["asked"] == "must")
    ratio = round((sum(1 for x in covered if x["asked"] == "must") + 0.5 * sum(1 for x in partial if x["asked"] == "must")) / total_must, 2) if total_must else None
    return {"covered": covered, "partial": partial, "gaps": gaps, "must_gaps": len(must_gaps), "coverage": ratio}


# ----------------------------------------------------------------------------- the kind of role, the employer, the route

ADMIN = re.compile(r"data entry|dateneingabe|archivier|ablage|einscannen|scannen|clerical|secretar|sekretariat|administrativ|filing|answering phones|telefon|abrechnung|saisie de donnees")


def detect_kind(title: str, text: str) -> tuple[str, str | None]:
    """(kind, employment). kind is one of resources/kinds.json (thesis, student_assistant, working_student, internship, trainee, senior, mid, entry, other);
    employment is permanent, contract or None."""
    cfg = config.get()
    ft = fold(title)
    head = fold(text[:500])
    kind = "other"
    for k in _kinds_order():
        pat = cfg.kinds_table.get(k, {}).get("title_re")
        if k != "other" and pat and re.search(fold(pat), ft):
            kind = k
            break
    if kind == "trainee" and re.search(r"praktik|intern\b", ft):
        kind = "internship"
    if kind == "other" and not cfg.student_stage and cfg.profile.get("career_stage") in ("experienced", "career_change"):
        kind = "mid"                       # a title with no seniority word is, for an experienced searcher, an ordinary professional role
    if kind in ("mid", "entry", "other"):
        # a title with no seniority word is placed by the experience the posting asks for: five or more years is a senior role, none or one is entry level
        f = fold(text)
        ys = [int(m.group(1) or m.group(2)) for m in re.finditer(
            r"(\d{1,2})\+?\s*(?:-|to)?\s*(?:\d{1,2})?\s*\+?\s*(?:years|yrs|jahre|jahren|ans|anos|jaar)\\b[^.]{0,40}(?:experience|erfahrung|experiencia|ervaring)"
            r"|(?:experience|erfahrung|experiencia|ervaring)[^.]{0,30}?(\d{1,2})\+?\s*(?:years|yrs|jahre|jahren|ans|anos|jaar)", f)]
        if ys and min(ys) >= 5:
            kind = "senior"
        elif ys and min(ys) <= 1 and kind in ("mid", "other"):
            kind = "entry"
    emp = None
    for name, pat in (config.resource("kinds.json", {}).get("employment") or {}).items():
        if re.search(fold(pat), ft + " " + head):
            emp = name
            break
    return kind, emp


def _kinds_order() -> list[str]:
    base = config.resource("kinds.json", {}).get("order") or []
    extra = [k for k in config.get().kinds_table if k not in base]
    return extra + base


def route(country: str, kind: str, employer: str, walls: list[dict], text: str, url: str, source: str) -> tuple[int, str, str]:
    """(adjustment, work_route, explanation): the work-authorization route, from the region pack's route rules (regions/<code>/region.json)."""
    cfg = config.get()
    if any(w.get("route_block") for w in walls):
        return -4, "none_found", "no legal route: the posting excludes applicants without existing work authorization"
    ctx = {"country": country, "kind": kind, "employer": employer, "url": url, "source": source, "text": text}
    for r in cfg.route_rules:
        if _when_ok(r.get("when") or {}, ctx):
            return int(r.get("adj", 0)), r.get("route", "unknown"), r.get("note", "")
    d = cfg.region.get("route_default") or {}
    if not cfg.needs_authorization:
        return 0, "unrestricted", "no work-authorization limit in the profile"
    return int(d.get("adj", -3)), d.get("route", "unknown"), d.get("note", "no route rule matched this role: the work-authorization route is unassessed")


# ----------------------------------------------------------------------------- is it a posting at all

INFO_TITLE = re.compile(r"^(abschlussarbeiten?( themen)?|fertige abschlussarbeiten|thesis regulations|download dokument|richtlinie|guidelines?|merkblatt|"
                        r"themenliste|themen fuer abschlussarbeiten|praktikantenamt|praktikum im ausland|free mover|arbeiten und praktikum|start ins praktikum|"
                        r"erasmus|abschlussarbeit im ausland|labor.?praktika|praktika (im|in) |careers? (at|home)|jobs? (at|home)|open positions|stellenangebote|"
                        r"search jobs|job (search|board|alerts?)|our teams?|life at|working at|why (join|work))|themenliste|guideline|regulations|richtlinie|merkblatt", re.I)


def looks_like_posting(title: str, doc: "Doc") -> tuple[bool, str]:
    """A posting offers a role: it says what you do, what is asked, and how to apply. A rules page, a topic list or an index page does not."""
    signals = {
        "how to apply": r"bewerb|apply|application|bewirb|candidater|postul|kontaktier|senden sie|schicken sie|send (your|us)|per e-?mail an|e-?mail to|solicitar|inscri|sollicit",
        "what is asked": r"profil|anforderung|requirements|qualification|voraussetzung|your profile|what you bring|das bringst|sie bringen|du bringst|wir erwarten|danach suchen wir|wir suchen|derzeitiges studium|immatrikul|eingeschrieben|enrolled in|you have|you are|exigences|competences|requisitos|requisiti|vereisten",
        "what you do": r"aufgaben|your tasks|responsibilit|your role|taetigkeit|ihre aufgabe|du unterstuetzt|you will|sie unterstuetzen|mission|ihr aufgabengebiet|your mission|stelle im ueberblick|unterstuetzung bei|mithilfe bei|mitarbeit bei|what you.ll do|funciones|compiti|taken",
        "who to ask": r"kontakt|contact|ansprechpartner|@",
    }
    got = [k for k, p in signals.items() if doc.search(p)]
    if INFO_TITLE.search(fold(title)) and len(got) < 4:
        return False, f"the title reads as an information page ('{title[:60]}') and the text offers no role"
    if len(got) < 2:
        return False, "the page does not describe a role (no tasks, profile or way to apply): an information or index page"
    return True, ""


# ----------------------------------------------------------------------------- the analysis of one text

def analyze_text(row: dict, text: str, kind_hint: str = "job") -> dict:
    cfg = config.get()
    title = row["title"]
    employer = row.get("employer") or row.get("institution") or ""
    emp_f = fold(employer)
    location = row.get("location") or ""
    country = (row.get("country") or "ZZ").upper()
    doc = Doc(text)
    lang = detect_lang(text)
    kind, employment = detect_kind(title, text)
    ctx = {"country": country, "kind": kind, "employer": employer, "url": row.get("url") or row.get("posting_url") or "", "source": row.get("source") or row.get("source_type") or "",
           "text": doc.f}
    langs = language_checks(doc, lang, country)
    walls = find_walls(doc, langs, country, ctx)
    if row.get("approval") == "blocked" and row.get("blocked_reason") and not any(w["wall"].startswith("Recorded") for w in walls):
        # a block recorded when the full posting was first read stays, even if the cached page is a thinner copy
        walls.append({"wall": "Recorded block from the first full read of the posting", "quote": quote(row["blocked_reason"])})
    deadline, expired = find_deadline(text, row.get("deadline"))
    category, subfield, field_scores = classify(title, text)
    role = cfg.subfields.get(subfield or "", {}).get("role", "other")
    cv = cv_compare(doc)
    fb = fold(text)
    industry = cfg.regex("industry_regex")
    priority = rx("|".join(cfg.domain.get("priority_employers") or []), re.I) if cfg.domain.get("priority_employers") else None
    industry_ok = bool(industry and industry.search(emp_f))
    priority_ok = bool(priority and priority.search(emp_f))
    comp: dict[str, int] = {}
    # ---- the field
    sf = cfg.subfields.get(subfield or "", {})
    if role == "core" and field_scores.get(subfield, 0) >= 5:
        comp["core field (+4)"] = 4
    elif role in ("core", "bridge") and sf.get("core_if_re") and re.search(fold(sf["core_if_re"]), fb):
        comp[f"core field: {sf.get('label', subfield)} in the owner's own domain (+4)"] = 4
    elif role == "bridge":
        comp["bridge field (+2)"] = 2
    elif role == "income":
        ctx_re = cfg.regex("income_context_re")
        if ctx_re and len(ctx_re.findall(fb)) >= int(cfg.domain.get("income_context_min", 4)) and (industry_ok or priority_ok):
            comp["adjacent skills used on relevant data (+2)"] = 2
    if priority_ok:
        comp["priority employer (+2)"] = 2
    # ---- recency: the posting's own date when the source gave one; otherwise only a role found today. It decays by itself: the daily
    # re-analysis drops the point and flags the move.
    if cfg.profile.get("recency_points", True):
        try:
            posted = row.get("posted_at")
            if posted:
                if (TODAY - date.fromisoformat(str(posted)[:10])).days <= 1:
                    comp["posted within 24 hours (+2)"] = 2
            elif (row.get("date_found") or "")[:10] == TODAY.isoformat():
                comp["found today, no posting date (+2)"] = 2
        except ValueError:
            pass
    loc = cfg.location_preference()
    if loc and loc.search(fold(location + " " + title)):
        comp["preferred place or remote (+1)"] = 1
    local_codes = list(_COUNTRY_LANGS.get(country, [])) or cfg.local_languages
    local = [L for L in langs if L["code"] in local_codes]
    if local and cfg.user_languages.get(local[0]["code"], 0) < 5:
        if lang == "en" or local[0]["level"] == "advantage":
            comp[f"posting in English or {local[0]['name']} only an advantage (+1)"] = 1
    if any(L["effect"] in ("penalty", "cap") for L in langs):
        comp["a language level above the owner's is stated (-1)"] = -1
    for pen in cfg.domain.get("penalty_subfields") or []:
        if subfield == pen["subfield"]:
            comp[f"{pen.get('label', pen['subfield'])} ({pen.get('points', -2):+d})"] = int(pen.get("points", -2))
    if role == "income" and not industry_ok and not priority_ok and cfg.domain.get("subfields"):
        comp["unrelated industry (-2)"] = -2
    if len(ADMIN.findall(fb)) >= 3 and role in ("core", "bridge", "other"):
        comp["administrative or clerical tasks (-2)"] = -2
    for bonus in cfg.domain.get("evidence_bonus") or []:
        have = any(x["term"].startswith(tuple(bonus.get("have_terms") or [])) for x in cv["covered"])
        if role in ("core", "bridge") and re.search(fold(bonus["ask_re"]), fb) and have:
            comp[f"{bonus.get('label', 'evidence on the CV')} (+{int(bonus.get('points', 1))})"] = int(bonus.get("points", 1))
    content = sum(comp.values())
    adj, work_route, route_note = route(country, kind, employer, walls, doc.f, ctx["url"], ctx["source"])
    score = max(0, min(10, content + adj))
    t1, t2 = D.score_tiers()
    # ---- the verdict
    reason_parts = []
    sought = kind in cfg.levels_sought
    primaries = cfg.primary_countries
    in_primary = (not primaries) or country in primaries or (country == "ZZ" and cfg.profile.get("remote_ok", True))
    is_posting, not_posting_why = looks_like_posting(title, doc)
    caps = [L for L in langs if L["effect"] == "cap"]
    if not is_posting:
        verdict = "PASS"
        reason_parts.append("not a posting: " + not_posting_why)
    elif walls:
        verdict = "BLOCKED"
    elif expired:
        verdict = "EXPIRED"
    elif role in ("core", "bridge"):
        if in_primary and sought and score >= t2:
            verdict = "APPLY"
            if cv["must_gaps"] >= 3 and (cv["coverage"] or 0) < 0.5:
                verdict = "BACKUP"
                reason_parts.append(f"{cv['must_gaps']} required skills are not on the CV, so it is a stretch")
        elif in_primary and sought and score >= 2:
            verdict = "BACKUP"
        elif in_primary and not sought:
            verdict = "LATER"
        elif not in_primary and not sought:
            verdict = "LATER" if score >= 1 else "PASS"
        elif not in_primary and score >= 3:
            verdict = "PLAN"
        else:
            verdict = "PASS"
    elif role == "income":
        verdict = "BACKUP" if in_primary and sought and score >= 3 and (industry_ok or priority_ok) else "PASS"
    else:
        verdict = "BACKUP" if (cfg.profile.get("accept_unrelated_income") and in_primary and sought and score >= 2) else "PASS"
    if verdict == "APPLY" and caps:
        verdict = "BACKUP"
        reason_parts.append(f"{caps[0]['name']} {LEVEL_WORDS[caps[0]['level']]} is stated and the profile says {config.LEVELS[caps[0]['mine']].upper()}, so it is not a first-choice application")
    # ---- the reason
    cat_label = D.CATEGORY_LABELS.get(category, category)
    sf_label = D.SUBFIELD_LABELS.get(subfield, subfield or "no sub-field")
    why = [f"{cat_label} / {sf_label}; {kind}; score {score} = " + " ".join(f"{v:+d}" for v in comp.values()) + (f" {adj:+d} route" if adj else " 0 route") + f" = {score}"]
    if walls:
        why.append("wall: " + "; ".join(f"{w['wall']} ('{w['quote'][:110]}')" for w in walls))
    if expired:
        why.append(f"deadline {deadline} has passed")
    elif deadline:
        why.append(f"deadline {deadline}")
    for L in langs:
        if L["level"] not in ("none", "advantage"):
            why.append(f"{L['name']}: {LEVEL_WORDS[L['level']]} ('{L['quote'][:100]}')")
    if cv["covered"]:
        why.append("CV covers " + ", ".join(x["term"].split(" (")[0] for x in cv["covered"] if x["asked"] == "must")[:160] if any(x["asked"] == "must" for x in cv["covered"]) else "CV covers " + ", ".join(x["term"].split(" (")[0] for x in cv["covered"][:5]))
    if cv["gaps"]:
        why.append("gaps: " + ", ".join(f"{g['term'].split(' (')[0]}{'' if g['asked'] == 'must' else ' (nice)'}" for g in cv["gaps"][:6]))
    why += reason_parts
    if route_note:
        why.append(route_note)
    tracked = {L["code"] for L in langs}
    top_lang = next((L for L in sorted(langs, key=lambda x: -_ORDER[x["level"]]) if L["level"] not in ("none",)), None)
    return {
        "category": category, "subfield": subfield, "field_scores": field_scores, "kind": kind, "employment": employment, "lang": lang, "langs": langs, "walls": walls,
        "deadline": deadline, "expired": expired, "cv": cv, "components": comp, "content": content, "route_adj": adj, "work_route": work_route,
        "route_note": route_note, "is_posting": is_posting, "score": score, "tier": D.tier_of(score), "verdict": verdict, "reason": " | ".join(why),
        "language_bar": other_language_bar(doc, lang, tracked), "lang_bar": (f"{LEVEL_WORDS[top_lang['level']]}: {top_lang['quote']}" if top_lang and top_lang["level"] != "advantage" else None),
        "chars": len(text),
    }


# ----------------------------------------------------------------------------- applying an analysis, with dynamic flags

def _row(ref: str) -> tuple[str, dict]:
    if ref.startswith("th-"):
        return "thesis", db.get_thesis(ref)
    return "job", db.get_job(ref)


def _history_entry(old_score, new_score, trigger, why):
    return {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "from": old_score, "to": new_score, "trigger": trigger, "why": why}


def db_update(kind: str, ref: str, ch: dict):
    return db.update_thesis(ref, ch) if kind == "thesis" else db.update_job(ref, ch)


def analyze_row(ref: str, *, dry: bool = False) -> dict:
    kind, row = _row(ref)
    if row is None:
        raise KeyError(ref)
    text = read_jd(row)
    if len(text) < db.JD_MIN_CHARS:
        f = db.jd_file(row)
        if f is not None and f.exists() and len(f.read_text(encoding="utf-8", errors="ignore")) >= db.JD_MIN_CHARS:
            # the file is big but not text: it was fetched wrongly. Withdraw every judgment and mark it unreadable (clearing needs no proof).
            if not dry and row.get("analysis_level") in ("auto", "stub", "legacy"):
                db_update(kind, ref, {"analysis_level": "unreadable", "verdict": None, "verdict_reason": None, "score": None, "tier": None, "category": None, "subfield": None,
                                      "cv_match": None, "score_breakdown": None} if kind == "job" else
                          {"analysis_level": "unreadable", "verdict": None, "verdict_reason": None, "category": None, "subfield": None, "cv_match": None, "score_breakdown": None, "score": None, "fit_score": None, "route_adjustment": None})
            return {"ref": ref, "skipped": "garbled"}
        return {"ref": ref, "skipped": "no readable JD text"}
    a = analyze_text(row, text)
    sha = db.current_jd_sha(row)
    old_score = row.get("score")
    level = row.get("analysis_level")
    hist = list(row.get("score_history") or []) if isinstance(row.get("score_history"), list) else []
    flag = row.get("score_flag")
    trigger = None
    if level in (None, "stub"):
        trigger = "first analysis"
    elif level == "legacy":
        trigger = "earlier score replaced by the analysis"
    elif row.get("jd_sha") and row["jd_sha"] != sha:
        trigger = "the cached JD changed"
    elif row.get("rule_version") != D.RULE_VERSION:
        trigger = "the profile, the domain, the region or the analysis rules changed"
    else:
        trigger = "time-dependent components changed (recency, deadline)"
    moved = old_score is not None and old_score != a["score"]
    verdict_moved = row.get("verdict") not in (None, a["verdict"])
    result = {"ref": ref, "kind": kind, "analysis": a, "old_score": old_score, "moved": moved}
    if dry:
        return result
    db.record_jd_read(kind, ref, sha, "analyzer")
    breakdown = {"components": a["components"], "content": a["content"], "route": {"adjustment": a["route_adj"], "work_route": a["route_note"]}, "kind": a["kind"], "lang": a["lang"],
                 "languages": {L["code"]: L["level"] for L in a["langs"] if L["level"] != "none"}, "field_scores": {k: v for k, v in a["field_scores"].items() if v}, "rule_version": D.RULE_VERSION}
    cvm = {"covered": a["cv"]["covered"], "partial": a["cv"]["partial"], "gaps": a["cv"]["gaps"], "must_gaps": a["cv"]["must_gaps"], "coverage": a["cv"]["coverage"]}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if level == "reviewed":
        # never overwrite a reviewed verdict: say that the script now disagrees and send the row back to review
        diff = []
        if a["score"] != old_score:
            diff.append(f"score {old_score}->{a['score']}")
        if a["verdict"] != row.get("verdict"):
            diff.append(f"verdict {row.get('verdict')}->{a['verdict']}")
        if row.get("jd_sha") and row["jd_sha"] != sha:
            diff.append("the cached JD changed")
        material = a["verdict"] != row.get("verdict") or (old_score is not None and abs(a["score"] - old_score) >= 2) or (row.get("jd_sha") and row["jd_sha"] != sha)
        if diff and material:
            new_flag = f"{now[:10]}: the analysis now says {'; '.join(diff)} (reason: {trigger}); the reviewed verdict is kept until re-reviewed"
            if new_flag != flag:
                db_update(kind, ref, {"score_flag": new_flag, "score_history": hist + [_history_entry(old_score, a["score"], trigger, "auto-analysis disagrees with the reviewed row: " + "; ".join(diff))]})
        elif flag and not material:
            db_update(kind, ref, {"score_flag": None})      # the script and the review agree again
        return {**result, "kept_reviewed": True}
    ch = {"category": a["category"], "subfield": a["subfield"], "verdict": a["verdict"], "verdict_reason": a["reason"], "cv_match": cvm, "analysis_level": "auto",
          "analyzed_at": now, "jd_sha": sha, "score_breakdown": breakdown, "rule_version": D.RULE_VERSION, "jd_lang": a["lang"] if kind == "job" else None}
    if kind == "job":
        ch.update({"score": a["score"], "tier": a["tier"], "work_route": a["work_route"], "language_bar": a["language_bar"], "lang_bar": a["lang_bar"]})
        if a["deadline"] and not row.get("deadline"):
            ch["deadline"] = a["deadline"]
        if a["walls"]:
            ch["blocked_reason"] = a["walls"][0]["quote"]
    else:
        ch.pop("jd_lang", None)
        ch.update({"fit_score": a["content"] if a["content"] >= 0 else 0, "route_adjustment": a["route_adj"], "work_route": a["work_route"], "language_bar": a["language_bar"]})
        if not row.get("pillar"):
            ch["pillar"] = (config.get().domain.get("thesis_pillars") or {}).get(a["subfield"], "other")
        if a["deadline"] and not row.get("deadline"):
            ch["deadline"] = a["deadline"]
    if moved or verdict_moved:
        why = f"{trigger}: score {old_score}->{a['score']}" + (f", verdict {row.get('verdict')}->{a['verdict']}" if verdict_moved else "")
        hist.append(_history_entry(old_score, a["score"], trigger, why))
        ch["score_flag"] = f"{now[:10]}: {why}"
    elif level in (None, "stub"):
        hist.append(_history_entry(None, a["score"], "first analysis", "scored from the full JD"))
        ch["score_flag"] = None
    ch["score_history"] = hist
    db_update(kind, ref, ch)
    return {**result, "verdict": a["verdict"], "score": a["score"]}


# ----------------------------------------------------------------------------- show and review (the Claude path)

def show(ref: str) -> None:
    kind, row = _row(ref)
    text = read_jd(row)
    sha = db.current_jd_sha(row)
    if not text or not sha:
        print(f"{ref}: no cached JD to show. Fetch it first (scripts/intake.py).")
        return
    db.record_jd_read(kind, ref, sha, "claude")
    print(f"# {row['title']}\n{row.get('employer') or row.get('institution')} | {row.get('location')} | country {row.get('country')} | url {row.get('url') or row.get('posting_url')}\n"
          f"deadline {row.get('deadline')} | JD hash {sha} | {len(text)} characters (read receipt recorded)\n\n{'=' * 78}\n{text}\n{'=' * 78}")
    a = analyze_text(row, text)
    print("\nANALYSIS OF THIS TEXT (confirm or override with `review`):")
    print(f"  {a['category']}/{a['subfield']} | kind {a['kind']} | score {a['score']} | verdict {a['verdict']}")
    print(f"  {a['reason']}")
    print("  CV covers :", ", ".join(x["term"] for x in a["cv"]["covered"]) or "-")
    print("  partial   :", ", ".join(x["term"] for x in a["cv"]["partial"]) or "-")
    print("  gaps      :", ", ".join(f"{g['term']} ({g['asked']})" for g in a["cv"]["gaps"]) or "-")


def review(ref: str, verdict: str, reason: str, score: int | None, category: str | None, subfield: str | None) -> dict:
    kind, row = _row(ref)
    text = read_jd(row)
    sha = db.current_jd_sha(row)
    a = analyze_text(row, text)
    final_score = a["score"] if score is None else score
    cat = category or a["category"]
    sub = subfield or a["subfield"]
    hist = list(row.get("score_history") or []) if isinstance(row.get("score_history"), list) else []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    breakdown = {"components": a["components"], "content": a["content"], "route": {"adjustment": a["route_adj"], "work_route": a["route_note"]}, "kind": a["kind"],
                 "reviewed_by": "claude", "analyzer_said": {"score": a["score"], "verdict": a["verdict"]}, "override": score is not None or verdict != a["verdict"], "rule_version": D.RULE_VERSION}
    ch = {"category": cat, "subfield": sub, "verdict": verdict, "verdict_reason": f"REVIEWED: {reason} | analyzer: {a['reason']}",
          "cv_match": {"covered": a["cv"]["covered"], "partial": a["cv"]["partial"], "gaps": a["cv"]["gaps"], "must_gaps": a["cv"]["must_gaps"], "coverage": a["cv"]["coverage"]},
          "analysis_level": "reviewed", "analyzed_at": now, "jd_sha": sha, "score_breakdown": breakdown, "rule_version": D.RULE_VERSION, "score_flag": None}
    if kind == "job":
        ch.update({"score": final_score, "tier": D.tier_of(final_score), "work_route": a["work_route"], "language_bar": a["language_bar"]})
    else:
        ch.update({"fit_score": max(0, final_score - a["route_adj"]), "route_adjustment": a["route_adj"], "work_route": a["work_route"]})
    if row.get("score") != final_score:
        hist.append(_history_entry(row.get("score"), final_score, "review", reason))
    ch["score_history"] = hist
    return db_update(kind, ref, ch)


# ----------------------------------------------------------------------------- CLI

def run(levels: set[str], ids: list[str] | None, limit: int | None, dry: bool) -> dict:
    db.init_db()
    refs: list[str] = []
    if ids:
        refs = ids
    else:
        refs += [j["id"] for j in db.list_jobs() if (j.get("analysis_level") or "stub") in levels and j["status"] == "open"]
        refs += [t["id"] for t in db.list_thesis() if (t.get("analysis_level") or "stub") in levels]
    if limit:
        refs = refs[:limit]
    tally = {"analysed": 0, "skipped": 0, "moved": 0, "kept_reviewed": 0, "errors": 0, "garbled": 0}
    verdicts: dict[str, int] = {}
    for ref in refs:
        try:
            r = analyze_row(ref, dry=dry)
        except Exception as e:  # noqa: BLE001
            tally["errors"] += 1
            print(f"{ref}: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
            continue
        if r.get("skipped") == "garbled":
            tally["garbled"] += 1
            continue
        if r.get("skipped"):
            tally["skipped"] += 1
            continue
        tally["analysed"] += 1
        tally["moved"] += bool(r.get("moved"))
        tally["kept_reviewed"] += bool(r.get("kept_reviewed"))
        v = r.get("verdict") or r["analysis"]["verdict"]
        verdicts[v] = verdicts.get(v, 0) + 1
    return {**tally, "verdicts": verdicts}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--levels", default="stub,legacy,auto")
    r.add_argument("--ids")
    r.add_argument("--limit", type=int)
    r.add_argument("--dry", action="store_true")
    for name in ("show", "explain"):
        sub.add_parser(name).add_argument("id")
    v = sub.add_parser("review")
    v.add_argument("id")
    v.add_argument("--verdict", required=True, choices=sorted(db.VERDICT_VALUES))
    v.add_argument("--reason", required=True)
    v.add_argument("--score", type=int)
    v.add_argument("--category")
    v.add_argument("--subfield")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if a.cmd == "run":
        config.require_configured()
        print(json.dumps(run(set(a.levels.split(",")), a.ids.split(",") if a.ids else None, a.limit, a.dry), indent=1))
    elif a.cmd == "show":
        show(a.id)
    elif a.cmd == "explain":
        kind, row = _row(a.id)
        res = analyze_text(row, read_jd(row))
        print(json.dumps({k: res[k] for k in ("category", "subfield", "kind", "score", "verdict", "components", "route_adj", "walls", "deadline", "expired", "langs", "reason")}, indent=1, ensure_ascii=False))
    else:
        row = review(a.id, a.verdict, a.reason, a.score, a.category, a.subfield)
        print(f"{a.id}: reviewed -> {row['verdict']} score {row.get('score')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/config.py: the one place the toolkit learns who it is searching for, where, and in which field.

The engine (analysis, intake, watches, mail, digest, dashboard) contains no knowledge of any person, country or field. Everything it needs comes from
three small JSON documents, written during onboarding (`/start`, see docs/ONBOARDING.md) and kept in the git-ignored `profile/` folder:

  profile/profile.json   WHO: name, e-mail, career stage, what kinds of roles are sought, languages and levels, work authorization, where to search
  profile/domain.json    WHAT: the user's fields (inferred from their CV), the words that identify each, the CV evidence, priority employers
  regions/<code>/region.json  WHERE: a region pack (job boards, role-type words, local walls such as a required language or work authorization,
                         how work authorization changes a score). Shipped for de (Germany), eu and us; `onboarding` researches and writes a pack
                         for any other country. A user's own overrides live in profile/region.override.json.

`JOBKIT_PROFILE_DIR` points the toolkit at another profile folder (the tests and `examples/` use it). Nothing here ever reads a network or a
mailbox; it only reads those files, merges them and offers the result. `rule_version()` is a hash of the merged configuration: when the profile,
the domain or the region changes, every analysed role is automatically re-analysed and every score that moves is flagged.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = Path(os.environ.get("JOBKIT_PROFILE_DIR") or (ROOT / "profile"))
REGIONS_DIR = ROOT / "regions"
RESOURCES = ROOT / "resources"
ENGINE_VERSION = "1.7"

# Common European Framework levels, plus "native". An unknown or missing level counts as none.
LEVELS = ["none", "a1", "a2", "b1", "b2", "c1", "c2", "native"]


def level_index(level: str | None) -> int:
    s = (level or "none").strip().lower().replace("mother tongue", "native").replace("fluent", "c1").replace("bilingual", "native")
    return LEVELS.index(s) if s in LEVELS else 0


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


# ----------------------------------------------------------------------------- defaults (an unconfigured toolkit still runs, and says so)

DEFAULT_PROFILE: dict[str, Any] = {
    "name": "", "email": "", "extra_emails": [], "career_stage": "experienced",
    "levels_sought": ["entry", "mid"], "regions": [], "cities": [], "remote_ok": True,
    "languages": [{"code": "en", "level": "c1"}], "work_authorization": {"status": "unrestricted"},
    "accept_unrelated_income": False, "min_salary": None, "owner_label": "you",
}
DEFAULT_DOMAIN: dict[str, Any] = {
    "categories": [{"id": "core", "label": "My field", "fit": "core"}, {"id": "adjacent", "label": "Adjacent", "fit": "bridge"}, {"id": "other", "label": "Other", "fit": "none"}],
    "subfields": [], "penalty_subfields": [], "priority_employers": [], "industry_regex": "", "cv_evidence": [], "evidence_bonus": [], "thesis_pillars": {},
}
DEFAULT_REGION: dict[str, Any] = {
    "code": "XX", "name": "Not set", "primary_countries": [], "scope_countries": [], "kinds": {}, "walls": [], "route_rules": [], "language_walls": [], "boards": [],
}
DEFAULT_VERDICTS = {
    "APPLY": {"label": "Apply", "tone": "success", "rank": 1, "help": "Fits the field and can be taken now: worth applying to first"},
    "BACKUP": {"label": "Backup", "tone": "accent", "rank": 2, "help": "A weaker fit or an income option"},
    "PLAN": {"label": "Plan", "tone": "info", "rank": 3, "help": "In the field but abroad or later: needs a plan"},
    "LATER": {"label": "Later", "tone": "plain", "rank": 4, "help": "In the field but not the kind of role sought now: a target for later"},
    "PASS": {"label": "Not a fit", "tone": "plain", "rank": 6, "help": "Read in full and not a fit for this profile"},
    "BLOCKED": {"label": "Blocked", "tone": "danger", "rank": 5, "help": "A wall in the posting (language, work authorization, degree, clearance)"},
    "EXPIRED": {"label": "Deadline passed", "tone": "warning", "rank": 7, "help": "The application deadline has passed"},
}
# which role kinds (resources/kinds.json) a career stage looks for unless the profile says otherwise
STAGE_LEVELS = {
    "student": ["thesis", "student_assistant", "working_student", "internship", "trainee"],
    "new_grad": ["internship", "trainee", "entry"],
    "experienced": ["entry", "mid", "senior"],
    "career_change": ["internship", "entry", "mid"],
}


class Config:
    """The merged, read-only view of profile + domain + region. Build one with `get()`."""

    def __init__(self) -> None:
        self.profile = _deep_merge(DEFAULT_PROFILE, _read(PROFILE_DIR / "profile.json", {}))
        self.domain = _deep_merge(DEFAULT_DOMAIN, _read(PROFILE_DIR / "domain.json", {}))
        codes = [str(c).lower() for c in ([self.profile.get("region")] if self.profile.get("region") else []) + list(self.profile.get("regions") or []) if c]
        codes = list(dict.fromkeys(codes))
        self.region_codes = codes
        self.region_code = codes[0] if codes else ""
        # The first pack is the home market (its primary countries, languages and defaults rule); every further pack widens the search with its own
        # route rules, walls and boards (for example ["de", "eu"]: Germany first, the rest of Europe behind it).
        packs = [self._load_pack(c) for c in codes]
        base = packs[0] if packs else {}
        for extra in packs[1:]:
            base = self._extend_pack(base, extra)
        self.region = _deep_merge(_deep_merge(DEFAULT_REGION, base), _read(PROFILE_DIR / "region.override.json", {}))
        self.configured = bool(self.profile.get("name") or self.profile.get("email")) and bool(self.domain.get("subfields"))
        self.kinds_table: dict[str, Any] = _read(RESOURCES / "kinds.json", {}).get("kinds", {})
        for k, v in (self.region.get("kinds") or {}).items():       # a region pack may add or retune role-type words
            self.kinds_table[k] = _deep_merge(self.kinds_table.get(k, {}), v)

    @staticmethod
    def _load_pack(code: str) -> dict:
        base = _read(REGIONS_DIR / code / "region.json", {})
        if not base:                       # an onboarding-written pack for a country the toolkit does not ship lives in the profile folder
            base = _read(PROFILE_DIR / "regions" / code / "region.json", {})
        return base

    @staticmethod
    def _extend_pack(base: dict, extra: dict) -> dict:
        out = copy.deepcopy(base)
        for k in ("scope_countries", "local_sources"):
            out[k] = list(dict.fromkeys(list(out.get(k) or []) + list(extra.get(k) or [])))
        for k in ("route_rules", "walls", "boards"):
            out[k] = list(out.get(k) or []) + list(extra.get(k) or [])
        for k in ("routes", "country_hints", "kinds"):
            merged = dict(extra.get(k) or {})
            merged.update(out.get(k) or {})
            out[k] = merged
        mail = copy.deepcopy(out.get("mail") or {})
        for k, v in (extra.get("mail") or {}).items():
            mail[k] = list(dict.fromkeys(list(mail.get(k) or []) + list(v)))
        out["mail"] = mail
        for k, v in extra.items():             # anything the home pack leaves unset comes from the extension
            out.setdefault(k, copy.deepcopy(v))
        return out

    # ------------------------------------------------------------------ owner
    @property
    def owner_name(self) -> str:
        return self.profile.get("name") or "you"

    @property
    def owner_emails(self) -> set[str]:
        out = {e.lower() for e in ([self.profile.get("email")] + list(self.profile.get("extra_emails") or [])) if e}
        return out

    @property
    def digest_to(self) -> str:
        return (self.profile.get("email") or "").lower()

    # ------------------------------------------------------------------ the field
    @property
    def categories(self) -> dict[str, str]:
        return {c["id"]: c["label"] for c in self.domain["categories"]}

    @property
    def category_fit(self) -> dict[str, str]:
        return {c["id"]: c.get("fit", "none") for c in self.domain["categories"]}

    @property
    def subfields(self) -> dict[str, dict]:
        return {s["id"]: s for s in self.domain["subfields"]}

    @property
    def subfield_labels(self) -> dict[str, str]:
        return {k: v.get("label", k) for k, v in self.subfields.items()}

    @property
    def category_subfields(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {c: set() for c in self.categories}
        for s in self.domain["subfields"]:
            out.setdefault(s["category"], set()).add(s["id"])
        return out

    def subfields_with_role(self, role: str) -> tuple[str, ...]:
        return tuple(s["id"] for s in self.domain["subfields"] if s.get("role") == role)

    @property
    def tie_order(self) -> tuple[str, ...]:
        return tuple(s["id"] for s in self.domain["subfields"])

    # ------------------------------------------------------------------ verdict vocabulary
    @property
    def verdicts(self) -> dict[str, dict]:
        out = copy.deepcopy(DEFAULT_VERDICTS)
        for k, v in (self.profile.get("verdict_labels") or {}).items():
            if k in out and isinstance(v, str):
                out[k]["label"] = v
        return out

    # ------------------------------------------------------------------ what is sought, and where
    @property
    def levels_sought(self) -> list[str]:
        sought = self.profile.get("levels_sought") or STAGE_LEVELS.get(self.profile.get("career_stage"), [])
        return list(dict.fromkeys(sought))

    @property
    def student_stage(self) -> bool:
        return self.profile.get("career_stage") == "student"

    @property
    def primary_countries(self) -> list[str]:
        return [c.upper() for c in (self.profile.get("primary_countries") or self.region.get("primary_countries") or [])]

    @property
    def scope_countries(self) -> list[str]:
        return [c.upper() for c in (self.profile.get("scope_countries") or self.region.get("scope_countries") or self.primary_countries)]

    @property
    def work_authorization(self) -> dict:
        return self.profile.get("work_authorization") or {"status": "unrestricted"}

    @property
    def needs_authorization(self) -> bool:
        return self.work_authorization.get("status", "unrestricted") not in ("unrestricted", "citizen", "permanent_resident", "eu_citizen", "")

    # ------------------------------------------------------------------ languages
    @property
    def user_languages(self) -> dict[str, int]:
        return {x["code"].lower(): level_index(x.get("level")) for x in (self.profile.get("languages") or []) if x.get("code")}

    @property
    def local_languages(self) -> list[str]:
        return [x.lower() for x in (self.region.get("local_languages") or [])]

    # ------------------------------------------------------------------ analysis tables
    @property
    def walls(self) -> list[dict]:
        return list(self.region.get("walls") or []) + list(self.domain.get("walls") or []) + list(self.profile.get("walls") or [])

    @property
    def route_rules(self) -> list[dict]:
        return list(self.profile.get("route_rules") or []) + list(self.region.get("route_rules") or [])

    @property
    def cv_evidence(self) -> list[dict]:
        return list(self.domain.get("cv_evidence") or [])

    @property
    def tiers(self) -> tuple[int, int]:
        t = self.profile.get("tiers") or {}
        return int(t.get("tier1", 7)), int(t.get("tier2", 4))

    def regex(self, key: str, source: str = "domain") -> re.Pattern | None:
        raw = (self.domain if source == "domain" else self.profile if source == "profile" else self.region).get(key)
        if isinstance(raw, list):
            raw = "|".join(f"(?:{x})" for x in raw if x)
        return re.compile(raw, re.I) if raw else None

    def location_preference(self) -> re.Pattern | None:
        cities = [c for c in (self.profile.get("cities") or []) if c and c.lower() != "remote"]
        words = [re.escape(c.lower()) for c in cities]
        if self.profile.get("remote_ok", True):
            words += [r"remote", r"home ?office", r"hybrid"]
        extra = self.profile.get("location_regex")
        if extra:
            words.append(extra)
        return re.compile("|".join(words), re.I) if words else None

    # ------------------------------------------------------------------ the watchers' classifier tables (aliases)
    def watch_aliases(self) -> dict:
        levels = _read(RESOURCES / "levels.json", {})
        want = set(self.levels_sought) | ({"working_student", "student_assistant", "internship", "thesis", "trainee"} if self.student_stage else set())
        level = {k: v for k, v in (levels.get("level") or {}).items() if k in want}
        pillars = {s["id"]: list(s.get("aliases") or []) for s in self.domain["subfields"] if s.get("aliases") and s.get("role") in ("core", "bridge")}
        exclude = list(levels.get("exclude_noise") or [])
        if "senior" not in self.levels_sought:          # someone who looks for senior roles must not have them filtered out
            exclude += list(levels.get("exclude_senior") or [])
        exclude += list(self.profile.get("exclude_titles") or [])
        return {"level": level, "exclude_level": {"terms": exclude}, "pillars": pillars}

    def route_labels(self) -> dict[str, str]:
        """Display names of the work-authorization routes (regions/<code>/region.json: routes {id: label})."""
        r = self.region.get("routes") or {}
        return dict(r) if isinstance(r, dict) else {x: x for x in r}

    def pillar_labels(self) -> dict[str, str]:
        """Thesis pillar ids (profile/domain.json: thesis_pillars {subfield: pillar}) with the sub-field's label."""
        labels = self.subfield_labels
        return {p: labels.get(sf, p) for sf, p in (self.domain.get("thesis_pillars") or {}).items()}

    # ------------------------------------------------------------------ what the watchers poll
    def sources(self) -> dict:
        """The sources the watches poll: the region pack's own (regions/<code>/sources.json: national job board, big employers' feeds, universities)
        plus the user's (profile/sources.json, written by onboarding from their field's employers). Lists are concatenated; `workday_terms` and
        `bundesagentur` (the national-board adapter settings) come from whichever has them."""
        bases = []
        for code in self.region_codes:
            b = _read(REGIONS_DIR / code / "sources.json", {}) or _read(PROFILE_DIR / "regions" / code / "sources.json", {})
            if b:
                bases.append(b)
        mine = _read(PROFILE_DIR / "sources.json", {})
        out: dict[str, Any] = {"institutions": [], "workday": [], "ats": [], "workday_terms": [], "national_board": None}
        for src in bases + [mine]:
            for k in ("institutions", "workday", "ats"):
                out[k] += list(src.get(k) or [])
            if src.get("workday_terms"):
                out["workday_terms"] = list(src["workday_terms"])
            if src.get("national_board"):
                out["national_board"] = src["national_board"]
        if not out["workday_terms"]:
            out["workday_terms"] = self.search_terms()[:8]
        return out

    def search_terms(self) -> list[str]:
        """Short keyword queries for the boards: the domain's own list, else the labels of its core sub-fields."""
        terms = list(self.domain.get("search_terms") or [])
        if not terms:
            terms = [s.get("label", s["id"]) for s in self.domain["subfields"] if s.get("role") in ("core", "bridge")]
        return terms

    def board_queries(self, prefixes: dict[str, list[str]] | None = None, cap: int = 60) -> list[str]:
        """Keyword queries for a job board's search API: each role-type word of the region (`prefixes`: kind -> words, e.g. thesis -> ["Masterarbeit",
        "Master thesis"]) in front of each of the user's field terms, for the kinds the user looks for; the bare field terms when no prefixes are given."""
        terms = self.search_terms()
        if not prefixes:
            return terms[:cap]
        out: list[str] = []
        for kind in self.levels_sought:
            for pre in prefixes.get(kind, []):
                out += [f"{pre} {t}".strip() for t in terms]
        return list(dict.fromkeys(out or terms))[:cap]

    # ------------------------------------------------------------------ identity of this configuration
    def rule_version(self) -> str:
        blob = json.dumps({"p": self.profile, "d": self.domain, "r": self.region, "v": ENGINE_VERSION}, sort_keys=True, ensure_ascii=False)
        return f"{ENGINE_VERSION}-" + hashlib.sha1(blob.encode("utf-8")).hexdigest()[:8]

    def summary(self) -> dict:
        return {"configured": self.configured, "name": self.owner_name, "region": self.region.get("name"), "stage": self.profile.get("career_stage"),
                "levels_sought": self.levels_sought, "categories": self.categories, "subfields": len(self.domain["subfields"]), "rule_version": self.rule_version()}


@lru_cache(maxsize=1)
def get() -> Config:
    return Config()


def require_configured() -> None:
    """Stop a command that would judge postings for a person who has not been set up: with no domain every role would be PASS and stored as such.
    `JOBKIT_ALLOW_UNCONFIGURED=1` lifts it (tests of the plumbing only)."""
    if not get().configured and not os.environ.get("JOBKIT_ALLOW_UNCONFIGURED"):
        raise SystemExit("Not configured: there is no profile/profile.json and profile/domain.json for this person yet. Run /start in Claude Code "
                         "(or `python scripts/onboard.py status` to see what is missing).")


def reload() -> Config:
    get.cache_clear()
    return get()


def resource(name: str, default: Any = None) -> Any:
    """A shipped data table from resources/ (languages, kinds, countries, mail patterns, applicant-system senders)."""
    return _read(RESOURCES / name, default)


def profile_path(*parts: str) -> Path:
    return PROFILE_DIR.joinpath(*parts)


if __name__ == "__main__":
    print(json.dumps(get().summary(), indent=1, ensure_ascii=False))

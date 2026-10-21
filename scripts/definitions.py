#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One place for the definitions every part of the toolkit must agree on (rules/pipeline.md, "Definitions").

The pipeline, the analyser, the intake, the dashboard API and the dashboard itself (through /api/definitions) all read these. Nothing else may
define a stage, a category, a verdict, a window or what "in scope" means. The fixed vocabularies (statuses, approvals, verdicts, analysis levels)
come from scripts/db.py; the user-specific ones (categories, sub-fields, role-type labels, verdict wording) come from the configuration written
during onboarding (scripts/config.py), so a different user, field or country changes this file's values and nothing else.
"""
from __future__ import annotations

from typing import Any

import config
import db

# ----------------------------------------------------------------------------- stages (status + approval -> one stage)
# First match wins. A rule's conditions are ANDed; a list means "any of these values".
STAGE_RULES: list[dict[str, Any]] = [
    {"stage": "applied", "when": {"status": ["applied"]}},
    {"stage": "interview", "when": {"status": ["interview"]}},
    {"stage": "declined", "when": {"status": ["rejected"], "applied_at": "set"}},
    {"stage": "closed", "when": {"status": ["rejected", "skip"]}},
    {"stage": "candidate", "when": {"analysis_level": ["stub", "unreadable"]}},
    {"stage": "blocked", "when": {"approval": ["blocked"]}},
    {"stage": "ready", "when": {"approval": ["prepared"]}},
    {"stage": "queued", "when": {"approval": ["requested", "recheck"]}},
    {"stage": "review", "when": {}},
]
STAGE_LABELS = {
    "candidate": "Not analysed yet", "review": "To review", "queued": "In progress", "ready": "Ready to send", "blocked": "Blocked",
    "applied": "Applied", "interview": "Interview", "declined": "Declined", "closed": "Closed",
}


def stage_of(job: dict[str, Any]) -> str:
    for rule in STAGE_RULES:
        ok = True
        for k, want in rule["when"].items():
            v = job.get(k)
            if want == "set":
                ok = ok and bool(v)
            else:
                ok = ok and v in want
        if ok:
            return rule["stage"]
    return "review"


# ----------------------------------------------------------------------------- the user's field, verdicts, kinds (from the configuration)
BEST_FIT_VERDICTS = ("APPLY", "BACKUP", "PLAN", "LATER")           # the ones a Claude session must confirm
ANALYSIS_LEVEL_LABELS = {"stub": "Not analysed", "auto": "Read by script", "reviewed": "Reviewed", "legacy": "Earlier score", "unreadable": "JD unreadable"}

CATEGORY_LABELS: dict[str, str] = {}
SUBFIELD_LABELS: dict[str, str] = {}
VERDICT_META: dict[str, dict[str, Any]] = {}
KIND_LABELS: dict[str, str] = {}
RULE_VERSION = ""


def refresh() -> None:
    """Recompute the configuration-derived values (called at import, and after a configuration reload in tests and in onboarding)."""
    global RULE_VERSION
    cfg = config.get()
    db.refresh_vocab()
    CATEGORY_LABELS.clear()
    CATEGORY_LABELS.update(cfg.categories)
    SUBFIELD_LABELS.clear()
    SUBFIELD_LABELS.update(cfg.subfield_labels)
    VERDICT_META.clear()
    VERDICT_META.update({k: {"label": v["label"], "tone": v["tone"], "rank": v["rank"]} for k, v in cfg.verdicts.items()})
    KIND_LABELS.clear()
    KIND_LABELS.update({k: v.get("label", k) for k, v in cfg.kinds_table.items()})
    RULE_VERSION = cfg.rule_version()       # a hash of profile + domain + region + engine: change any and every analysis is redone and every move flagged


# ----------------------------------------------------------------------------- windows and thresholds
WATCH_WINDOW_DAYS = 30             # how far back a watch candidate counts as new, everywhere (worklist, Inbox)
WATCH_MAX_AGE_DAYS = 4             # a watch older than this is stale (the task runs about every day or two)
LINK_MAX_AGE_DAYS = 30
DEADLINE_SOON_DAYS = 7
APPROVAL_CAP = 2                   # packages built per run (rules/runbook.md budgets)
RECHECK_CAP = 3


def tier_of(score: int | None) -> int | None:
    if score is None:
        return None
    t1, t2 = config.get().tiers
    return 1 if score >= t1 else 2 if score >= t2 else None


def score_tiers() -> tuple[int, int]:
    return config.get().tiers


def is_in_scope(item: dict[str, Any]) -> bool:
    """Intake takes every posting a watch found at a level the user looks for and in a country the search covers, whatever its title says:
    nothing is dropped for being off-topic, because the topic is decided by reading the full JD (THE READING RULE), not by a title or a snippet."""
    return bool(item.get("levels")) and not item.get("excluded") and item.get("in_scope", True)


is_student_level = is_in_scope        # the name the first versions used


def as_dict() -> dict[str, Any]:
    """What /api/definitions serves to the dashboard."""
    t1, t2 = score_tiers()
    return {
        "stage_rules": STAGE_RULES, "stage_labels": STAGE_LABELS, "category_labels": CATEGORY_LABELS, "subfield_labels": SUBFIELD_LABELS,
        "category_subfields": {k: sorted(v) for k, v in db.CATEGORY_SUBFIELDS.items()},
        "verdict_meta": VERDICT_META, "verdict_help": db.VERDICT_VALUES, "best_fit_verdicts": list(BEST_FIT_VERDICTS),
        "analysis_levels": ANALYSIS_LEVEL_LABELS, "kind_labels": KIND_LABELS, "rule_version": RULE_VERSION,
        "windows": {"watch_days": WATCH_WINDOW_DAYS, "deadline_soon_days": DEADLINE_SOON_DAYS},
        "tiers": {"tier1": t1, "tier2": t2}, "owner": config.get().owner_name,
        "route_labels": config.get().route_labels(), "pillar_labels": config.get().pillar_labels(),
    }


refresh()
assert set(VERDICT_META) == set(db.VERDICT_VALUES), "VERDICT_META differs from db.VERDICT_VALUES"
assert set(ANALYSIS_LEVEL_LABELS) == db.ANALYSIS_LEVELS, "ANALYSIS_LEVEL_LABELS differs from db.ANALYSIS_LEVELS"

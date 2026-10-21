#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/db.py
=============

The ONLY sanctioned access layer for db/tracker.db. Every other script (the pipeline, the Gmail sync, the CV builder, the dashboard) imports this module
rather than opening sqlite3 directly against the tracker.

Why this file exists (read this before touching update_job):
---------------------------------------------------------------------------
`my_notes` is the owner's field, and only theirs. update_job() refuses to write `my_notes` or `my_notes_at` unless the caller passes source="owner"
explicitly. A bug in scan code, a copy-paste of a dict that happened to carry a stale `my_notes` key, a well-meaning "let me just update everything from
the JD reread": none of these can silently overwrite what the owner typed, because the guard raises instead of writing.

If you are an automation script and you think you need to write my_notes, you are almost certainly wrong. Write `notes` instead.

The strict scoring guard: a score, tier, verdict or category is refused (ScoreWithoutJDError) unless the full job description is cached, the write carries
the hash of that cached text, the analysis level says who read it, and a score comes with its breakdown.

Concurrency: every write goes through `version`. Callers that read a row before writing back should pass `expected_version` so a stale write raises
instead of clobbering a change made since the read.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

import config

import os

# JOBKIT_DB points the whole toolkit at another tracker file (the application's tests use it so that child processes see the same throwaway database).
DB_PATH = Path(os.environ.get("JOBKIT_DB") or (Path(__file__).resolve().parent.parent / "db" / "tracker.db"))
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
REPO_ROOT = Path(__file__).resolve().parent.parent

# Where a package folder lives, keyed by the job's own status: a package folder always sits in the applications/ subfolder matching its status, so
# the owner never hunts a flat pile of 100+ folders for the handful still active. "open" and "interview" have no bucket (they stay at the top level
# of applications/); only a settled outcome is filed away.
STATUS_FOLDER = {
    "applied": "Applied",
    "rejected": "Rejected",
    "skip": "Skip",
}

# Closed vocabularies (rules/tracker-schema.md). A write outside these raises rather than silently dropping the card out of every view.
STATUS_VALUES = {"open", "applied", "interview", "rejected", "skip"}
APPROVAL_VALUES = {"none", "requested", "prepared", "recheck", "blocked"}
# stub = filed unscored, JD not analysed yet; auto = a script read the full JD and decided; reviewed = a Claude session read the full JD against the CV
# and confirmed or overrode; legacy = scored before this record existed; unreadable = the JD could not be fetched in full.
ANALYSIS_LEVELS = {"stub", "auto", "reviewed", "legacy", "unreadable"}
JUDGMENT_FIELDS = {"score", "tier", "verdict", "verdict_reason", "category", "subfield", "cv_match", "score_breakdown"}
THESIS_JUDGMENT_FIELDS = JUDGMENT_FIELDS | {"fit_score", "route_adjustment"}

# The user-specific vocabularies are derived from the configuration (scripts/config.py): the fields found in the CV, the work-authorization routes of
# the region, the verdict wording. refresh_vocab() recomputes them (at import, and after onboarding changes the configuration).
CATEGORY_SUBFIELDS: dict[str, set[str]] = {}
CATEGORY_VALUES: set[str] = set()
SUBFIELD_VALUES: set[str] = set()
VERDICT_VALUES: dict[str, str] = {}
WORK_ROUTE_VALUES: set[str] = set()
THESIS_PILLAR_VALUES: set[str] = set()
OWNER_SOURCE = "owner"


def refresh_vocab() -> None:
    cfg = config.get()
    CATEGORY_SUBFIELDS.clear()
    CATEGORY_SUBFIELDS.update(cfg.category_subfields)
    CATEGORY_VALUES.clear()
    CATEGORY_VALUES.update(CATEGORY_SUBFIELDS)
    SUBFIELD_VALUES.clear()
    SUBFIELD_VALUES.update(set().union(*CATEGORY_SUBFIELDS.values()) if CATEGORY_SUBFIELDS else set())
    VERDICT_VALUES.clear()
    VERDICT_VALUES.update({k: v.get("help", "") for k, v in cfg.verdicts.items()})
    WORK_ROUTE_VALUES.clear()
    WORK_ROUTE_VALUES.update({"none_found", "unknown", "unrestricted"} |          # "unrestricted": a profile with no work-permit limit (citizen, EU citizen, resident)
                               {r["route"] for r in cfg.route_rules if r.get("route")} | set(cfg.region.get("routes") or []))
    THESIS_PILLAR_VALUES.clear()
    THESIS_PILLAR_VALUES.update(set((cfg.domain.get("thesis_pillars") or {}).values()) | {"other"})


refresh_vocab()

# Columns nothing but the owner's own explicit input may ever write.
OWNER_ONLY_FIELDS = {"my_notes", "my_notes_at"}

# Columns no automation write may touch at all (server-managed).
SERVER_MANAGED_FIELDS = {"id", "created_at", "updated_at", "version"}


class MyNotesGuardError(PermissionError):
    """Raised when a caller tries to write an owner-only field without source='owner'."""


class StaleWriteError(RuntimeError):
    """Raised when expected_version doesn't match the row's current version."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create db/tracker.db from schema.sql if it doesn't exist yet. Idempotent."""
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with _connect() as conn:
        conn.executescript(schema_sql)
        _migrate(conn)


# Columns added after the first release. CREATE TABLE IF NOT EXISTS leaves an
# existing tracker.db untouched, so each one is added here when missing. Existing
# rows get the default (ZZ = unknown country).
_ADDED_COLUMNS = {
    "country": "TEXT NOT NULL DEFAULT 'ZZ'",
    "work_route": "TEXT",
    "language_bar": "TEXT",
    "category": "TEXT",
    "subfield": "TEXT",
    # the analysis record (rules/pipeline.md, S22): what the full JD said, how it was scored, and the verdict
    "verdict": "TEXT",
    "verdict_reason": "TEXT",
    "cv_match": "TEXT",
    "analysis_level": "TEXT",
    "analyzed_at": "TEXT",
    "jd_sha": "TEXT",
    "score_breakdown": "TEXT",
    "score_history": "TEXT",
    "score_flag": "TEXT",
    "rule_version": "TEXT",
    "posted_at": "TEXT",            # the posting's own date when the source gives it (the recency point uses it)
    "watch_id": "TEXT",             # id of the university/company watch item this row came from (intake never files it twice)
}

# The same record on the thesis table.
_ADDED_THESIS_COLUMNS = {
    "category": "TEXT", "subfield": "TEXT", "verdict": "TEXT", "verdict_reason": "TEXT", "cv_match": "TEXT",
    "analysis_level": "TEXT", "analyzed_at": "TEXT", "jd_sha": "TEXT", "score_breakdown": "TEXT",
    "score_history": "TEXT", "score_flag": "TEXT", "rule_version": "TEXT", "posted_at": "TEXT", "watch_id": "TEXT",
}


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    for name, decl in _ADDED_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {decl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_country ON jobs(country)")
    t_existing = {r["name"] for r in conn.execute("PRAGMA table_info(thesis)")}
    if t_existing:
        for name, decl in _ADDED_THESIS_COLUMNS.items():
            if name not in t_existing:
                conn.execute(f"ALTER TABLE thesis ADD COLUMN {name} {decl}")
    # Read receipts: proof that a JD was shown in full to a reader (script or Claude session) before a verdict was written.
    conn.execute("""CREATE TABLE IF NOT EXISTS jd_reads (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, ref TEXT NOT NULL, sha TEXT NOT NULL,
        reader TEXT NOT NULL, read_at TEXT NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jd_reads ON jd_reads(kind, ref, sha)")
    conn.execute("""CREATE TABLE IF NOT EXISTS mail_events (
        msg_id TEXT PRIMARY KEY, thread_id TEXT, direction TEXT NOT NULL, kind TEXT NOT NULL, confidence TEXT, sender TEXT, recipient TEXT,
        subject TEXT, mail_date TEXT, employer_hint TEXT, job_id TEXT, thesis_id TEXT, action TEXT, note TEXT, state TEXT NOT NULL DEFAULT 'new',
        judged_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mail_events_kind ON mail_events(kind, state)")
    # Rows scored before the analysis record existed are 'legacy': kept, but queued for re-analysis.
    conn.execute("UPDATE jobs SET analysis_level = 'legacy' WHERE analysis_level IS NULL AND (score IS NOT NULL OR tier IS NOT NULL)")
    if t_existing:
        conn.execute("UPDATE thesis SET analysis_level = 'legacy' WHERE analysis_level IS NULL AND score IS NOT NULL")


_JSON_COLUMNS = {"hard_reqs", "soft_reqs", "keywords", "cv_match", "score_breakdown", "score_history"}


def _relocate_package_folder(current_package_path: str | None, new_status: str) -> str | None:
    """Physically move a package folder to match its new status (STATUS_FOLDER),
    e.g. applications/<folder> -> applications/Applied/<folder>. Returns the new
    package_path to write, or None if nothing should change: no package_path on
    the row, the folder isn't actually there (already moved by hand, or never
    built), it's already in the right place, or a folder already exists at the
    destination (never clobber -- leave it for a human to sort out). A status
    change must never fail just because the filesystem side of it hit a snag;
    worst case package_path is simply left as it was.
    """
    if not current_package_path:
        return None
    norm = current_package_path.replace("\\", "/")
    if "applications/" not in norm:
        return None
    rel = norm.split("applications/", 1)[1]
    parts = rel.split("/", 1)
    bare = parts[1] if len(parts) == 2 and parts[0] in STATUS_FOLDER.values() else rel
    target_bucket = STATUS_FOLDER.get(new_status)  # None for open/interview
    new_rel = f"{target_bucket}/{bare}" if target_bucket else bare
    if new_rel == rel:
        return None
    src = REPO_ROOT / "applications" / rel
    dst = REPO_ROOT / "applications" / new_rel
    if not src.is_dir() or dst.exists():
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return f"applications/{new_rel}"


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for col in _JSON_COLUMNS:
        if d.get(col):
            try:
                d[col] = json.loads(d[col])
            except (TypeError, json.JSONDecodeError):
                pass
    return d


class ScoreWithoutJDError(ValueError):
    """Raised when a score, tier, category or verdict is written without the proof that the full JD was read."""


JD_MIN_CHARS = 500  # a cached description shorter than this is a stub, a login wall or page navigation, not a read JD
READ_RECEIPT_HOURS = 24


def jd_file(row: dict[str, Any]) -> Path | None:
    path = (row.get("jd_path") or "").replace("\\", "/")
    if not path:
        return None
    f = Path(path) if path.endswith(".md") else Path(path) / "description.md"
    return f if f.is_absolute() else SCHEMA_PATH.parent.parent / f


def jd_text_sha(text: str) -> str:
    import hashlib
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()[:16]


def jd_cache_ok(row: dict[str, Any]) -> tuple[bool, str]:
    """A score exists only for a role whose full JD text is cached on disk (CLAUDE.md rule 3)."""
    f = jd_file(row)
    if f is None:
        return False, "no jd_path"
    if not f.exists():
        return False, f"no cached JD file at {f}"
    n = len(f.read_text(encoding="utf-8", errors="ignore"))
    return (n >= JD_MIN_CHARS, f"cached JD is only {n} characters")


def current_jd_sha(row: dict[str, Any]) -> str | None:
    f = jd_file(row)
    return jd_text_sha(f.read_text(encoding="utf-8", errors="ignore")) if f and f.exists() else None


def record_jd_read(kind: str, ref: str, sha: str, reader: str) -> None:
    """Receipt that `reader` (analyzer | claude) was shown the full JD with this hash. Written by analyze.show()/analyze_row()."""
    with _connect() as conn:
        conn.execute("INSERT INTO jd_reads (kind, ref, sha, reader, read_at) VALUES (?,?,?,?,?)", (kind, ref, sha, reader, _now_iso()))


def has_jd_read(kind: str, ref: str, sha: str, reader: str, hours: int = READ_RECEIPT_HOURS) -> bool:
    from datetime import datetime, timedelta, timezone
    cut = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _connect() as conn:
        r = conn.execute("SELECT 1 FROM jd_reads WHERE kind=? AND ref=? AND sha=? AND reader=? AND read_at>=? LIMIT 1", (kind, ref, sha, reader, cut)).fetchone()
    return r is not None


def _guard_judgment(kind: str, ref: str, row: dict[str, Any] | None, changes: dict[str, Any], source: str) -> None:
    """THE STRICT SCORING RULE, enforced for jobs and thesis rows alike (CLAUDE.md rule 3).

    Any write to a judgment field (score, tier, category, verdict, fit_score, ...) must carry the proof of the read:
      - the full JD is cached on disk (800+ characters);
      - the write names the hash of the text that was analysed (jd_sha) and it is the hash of the cached file now,
        so the cache cannot have been swapped or edited after the analysis;
      - the analysis level is 'auto' (a script read the full text) or 'reviewed' (a Claude session did);
      - a score or tier comes with its score_breakdown;
      - 'reviewed' needs a read receipt: analyze.show() printed the full JD to that reader within the last 24 hours.
    source='rollback' restores an earlier value and is the only exception. Clearing a field (None) needs no proof."""
    fields = THESIS_JUDGMENT_FIELDS if kind == "thesis" else JUDGMENT_FIELDS
    touched = {k for k in fields & changes.keys() if changes[k] is not None}
    if source == "rollback" or not touched:
        return
    merged = {**(row or {}), **changes}
    ok, why = jd_cache_ok(merged)
    if not ok:
        raise ScoreWithoutJDError(f"Refusing to write {sorted(touched)} for {ref}: {why}. Fetch and cache the full JD first.")
    sha = current_jd_sha(merged)
    if changes.get("jd_sha") != sha:
        raise ScoreWithoutJDError(f"Refusing to write {sorted(touched)} for {ref}: jd_sha {changes.get('jd_sha')!r} is not the hash of the cached JD ({sha}); "
                                  f"analyse the cached text and pass its hash.")
    level = merged.get("analysis_level")
    if level not in ("auto", "reviewed"):
        raise ScoreWithoutJDError(f"Refusing to write {sorted(touched)} for {ref}: analysis_level must be 'auto' or 'reviewed', got {level!r}.")
    if {"score", "tier", "fit_score"} & touched and not merged.get("score_breakdown"):
        raise ScoreWithoutJDError(f"Refusing to write a score for {ref} without its score_breakdown.")
    if level == "reviewed" and not has_jd_read(kind, ref, sha, "claude"):
        raise ScoreWithoutJDError(f"Refusing a 'reviewed' verdict for {ref}: no read receipt. Run `python scripts/analyze.py show {ref}` "
                                  f"and read the full JD first.")


# ----------------------------------------------------------------------------- mail events (scripts/mail_sync.py)

MAIL_KINDS = ("alert", "sent_application", "ack", "rejection", "interview", "offer", "info_request", "reply", "other_job")
MAIL_STATES = ("new", "applied", "already", "unmatched", "needs_read", "acted", "dismissed")


def mail_event(msg_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        r = conn.execute("SELECT * FROM mail_events WHERE msg_id = ?", (msg_id,)).fetchone()
    return dict(r) if r else None


def save_mail_event(ev: dict[str, Any]) -> dict[str, Any]:
    """Insert or update one mail event (keyed by the Gmail message id). Holds the job-related facts of a mail, never its body."""
    if ev.get("kind") not in MAIL_KINDS:
        raise ValueError(f"unknown mail kind {ev.get('kind')!r}")
    if ev.get("state", "new") not in MAIL_STATES:
        raise ValueError(f"unknown mail state {ev.get('state')!r}")
    cols = ("msg_id", "thread_id", "direction", "kind", "confidence", "sender", "recipient", "subject", "mail_date", "employer_hint", "job_id",
            "thesis_id", "action", "note", "state", "judged_by")
    now = _now_iso()
    old = mail_event(ev["msg_id"])
    row = {c: ev.get(c, (old or {}).get(c)) for c in cols}
    row["state"] = row["state"] or "new"
    with _connect() as conn:
        if old:
            sets = ", ".join(f"{c} = ?" for c in cols[1:])
            conn.execute(f"UPDATE mail_events SET {sets}, updated_at = ? WHERE msg_id = ?", [row[c] for c in cols[1:]] + [now, ev["msg_id"]])
        else:
            conn.execute(f"INSERT INTO mail_events ({', '.join(cols)}, created_at, updated_at) VALUES ({', '.join('?' * len(cols))}, ?, ?)", [row[c] for c in cols] + [now, now])
    return mail_event(ev["msg_id"])  # type: ignore[return-value]


def delete_mail_events(states: tuple[str, ...]) -> int:
    """Forget events that are still open (never ones that moved a status), so a changed classifier can read those mails again."""
    with _connect() as conn:
        cur = conn.execute(f"DELETE FROM mail_events WHERE state IN ({','.join('?' * len(states))}) AND judged_by IS NULL", list(states))
    return cur.rowcount


def list_mail_events(*, kind: str | None = None, state: str | None = None, since: str | None = None, job_id: str | None = None) -> list[dict[str, Any]]:
    clauses, params = [], []
    for col, val in (("kind", kind), ("state", state), ("job_id", job_id)):
        if val is not None:
            clauses.append(f"{col} = ?")
            params.append(val)
    if since:
        clauses.append("mail_date >= ?")
        params.append(since)
    sql = "SELECT * FROM mail_events" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY mail_date DESC, created_at DESC"
    with _connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_job(job_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_jobs(
    *,
    status: str | None = None,
    approval: str | None = None,
    source: str | None = None,
    jd_read: bool | None = None,
    country: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    clauses, params = [], []
    if country is not None:
        clauses.append("country = ?")
        params.append(country)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if approval is not None:
        clauses.append("approval = ?")
        params.append(approval)
    if source is not None:
        clauses.append("source = ?")
        params.append(source)
    if jd_read is not None:
        clauses.append("jd_read = ?")
        params.append(1 if jd_read else 0)
    sql = "SELECT * FROM jobs"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY updated_at DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def create_job(job: dict[str, Any]) -> dict[str, Any]:
    """Insert a new role. `id`, `title`, `employer` are required. Never accepts
    my_notes/my_notes_at at creation — a freshly-discovered role has no owner notes yet."""
    if "id" not in job or "title" not in job or "employer" not in job:
        raise ValueError("create_job requires id, title, employer")
    bad = OWNER_ONLY_FIELDS & job.keys()
    if bad:
        raise MyNotesGuardError(
            f"create_job() cannot set {bad} — a new role has no owner notes yet"
        )
    _validate_enums(job)
    _guard_judgment("job", job["id"], None, job, "automation")

    cols = dict(job)
    for col in _JSON_COLUMNS:
        if col in cols and not isinstance(cols[col], str):
            cols[col] = json.dumps(cols[col], ensure_ascii=False)
    now = _now_iso()
    cols.setdefault("created_at", now)
    cols["updated_at"] = now
    cols["version"] = 1

    columns = ", ".join(cols.keys())
    placeholders = ", ".join("?" for _ in cols)
    with _connect() as conn:
        conn.execute(
            f"INSERT INTO jobs ({columns}) VALUES ({placeholders})",
            list(cols.values()),
        )
    return get_job(job["id"])  # type: ignore[return-value]


def update_job(
    job_id: str,
    changes: dict[str, Any],
    *,
    source: str = "automation",
    expected_version: int | None = None,
) -> dict[str, Any]:
    """The single write path for every column except id/created_at.

    source="owner" is the ONLY way to write my_notes/my_notes_at — pass it explicitly,
    from code that is directly relaying the owner's own typed input, never from a scan
    or a JD re-read. Every other caller hitting an OWNER_ONLY_FIELDS key raises.

    expected_version, when given, must match the row's current version or the write
    is rejected with StaleWriteError instead of silently overwriting a concurrent
    change (optimistic concurrency on `version`).
    """
    if not changes:
        raise ValueError("update_job called with no changes")

    touched_owner_fields = OWNER_ONLY_FIELDS & changes.keys()
    if touched_owner_fields and source != "owner":
        raise MyNotesGuardError(
            f"Refusing to write {touched_owner_fields}: only source='owner' may write "
            f"owner-only fields. This call came from source={source!r}."
        )

    touched_server_fields = SERVER_MANAGED_FIELDS & changes.keys()
    if touched_server_fields:
        raise ValueError(f"update_job cannot set server-managed fields {touched_server_fields}")

    _validate_enums(changes)
    _guard_judgment("job", job_id, get_job(job_id), changes, source)

    if "status" in changes and "package_path" not in changes:
        current = get_job(job_id)
        if current is not None:
            relocated = _relocate_package_folder(current.get("package_path"), changes["status"])
            if relocated:
                changes = dict(changes)
                changes["package_path"] = relocated

    cols = dict(changes)
    for col in _JSON_COLUMNS:
        if col in cols and not isinstance(cols[col], str):
            cols[col] = json.dumps(cols[col], ensure_ascii=False)

    if touched_owner_fields and "my_notes_at" not in cols:
        cols["my_notes_at"] = _now_iso()
    cols["updated_at"] = _now_iso()

    set_clause = ", ".join(f"{k} = ?" for k in cols)
    params: list[Any] = list(cols.values())

    with _connect() as conn:
        if expected_version is not None:
            sql = (
                f"UPDATE jobs SET {set_clause}, version = version + 1 "
                f"WHERE id = ? AND version = ?"
            )
            cur = conn.execute(sql, params + [job_id, expected_version])
            if cur.rowcount == 0:
                current = conn.execute(
                    "SELECT version FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()
                if current is None:
                    raise KeyError(f"no such job: {job_id}")
                raise StaleWriteError(
                    f"{job_id} is at version {current['version']}, "
                    f"expected {expected_version}"
                )
        else:
            sql = f"UPDATE jobs SET {set_clause}, version = version + 1 WHERE id = ?"
            cur = conn.execute(sql, params + [job_id])
            if cur.rowcount == 0:
                raise KeyError(f"no such job: {job_id}")

    return get_job(job_id)  # type: ignore[return-value]


def batch_update(
    updates: Iterable[tuple[str, dict[str, Any]]],
    *,
    source: str = "automation",
) -> list[dict[str, Any]]:
    """update_job for several rows. Each item is (job_id, changes). No version
    pinning at this layer — callers doing a scan-wide batch write typically don't
    hold a prior read to pin against; use update_job directly when they do."""
    return [update_job(jid, changes, source=source) for jid, changes in updates]


def _validate_enums(changes: dict[str, Any]) -> None:
    if changes.get("verdict") is not None and changes["verdict"] not in VERDICT_VALUES:
        raise ValueError(f"verdict must be one of {sorted(VERDICT_VALUES)}, got {changes['verdict']!r}")
    if changes.get("analysis_level") is not None and changes["analysis_level"] not in ANALYSIS_LEVELS:
        raise ValueError(f"analysis_level must be one of {sorted(ANALYSIS_LEVELS)}, got {changes['analysis_level']!r}")
    if changes.get("category") is not None and changes["category"] not in CATEGORY_VALUES:
        raise ValueError(f"category must be one of {CATEGORY_VALUES}, got {changes['category']!r}")
    if changes.get("subfield") is not None and changes["subfield"] not in SUBFIELD_VALUES:
        raise ValueError(f"subfield must be one of {SUBFIELD_VALUES}, got {changes['subfield']!r}")
    if changes.get("category") and changes.get("subfield") and changes["subfield"] not in CATEGORY_SUBFIELDS[changes["category"]]:
        raise ValueError(f"subfield {changes['subfield']!r} does not belong to category {changes['category']!r}")
    if "status" in changes and changes["status"] not in STATUS_VALUES:
        raise ValueError(f"status must be one of {STATUS_VALUES}, got {changes['status']!r}")
    if "approval" in changes and changes["approval"] not in APPROVAL_VALUES:
        raise ValueError(f"approval must be one of {APPROVAL_VALUES}, got {changes['approval']!r}")
    if "country" in changes:
        c = changes["country"]
        if not (isinstance(c, str) and len(c) == 2 and c.isalpha() and c.isupper()):
            raise ValueError(f"country must be a 2-letter uppercase ISO code, got {c!r}")
    if "work_route" in changes and changes["work_route"] is not None \
            and changes["work_route"] not in WORK_ROUTE_VALUES:
        raise ValueError(
            f"work_route must be one of {WORK_ROUTE_VALUES}, got {changes['work_route']!r}"
        )


def export_csv(out_path: str | Path) -> Path:
    """jobs-master.csv export (an append-only mirror of the tracker for spreadsheets).
    Uses csv.writer (a real quoting writer) — an unquoted comma once shifted
    every column in an earlier hand-written export."""
    import csv

    out_path = Path(out_path)
    rows = list_jobs()
    with _connect() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            flat = dict(row)
            for col in _JSON_COLUMNS:
                if isinstance(flat.get(col), (list, dict)):
                    flat[col] = json.dumps(flat[col], ensure_ascii=False)
            writer.writerow(flat)
    return out_path


# ---------------------------------------------------------------------------
# thesis table: thesis and research-project leads for students. Same rules as jobs: written only
# here, my_notes only with source="owner", writes pinned to `version` when the caller
# holds a prior read.

THESIS_STATUS_VALUES = {"lead", "outreach_drafted", "outreach_sent", "replied", "interview",
                        "accepted", "declined", "closed"}
THESIS_KIND_VALUES = {"advertised", "topic_list", "open_call", "lead"}
_THESIS_JSON = {"publications", "cv_match", "score_breakdown", "score_history"}


def _thesis_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for col in _THESIS_JSON:
        if d.get(col):
            try:
                d[col] = json.loads(d[col])
            except (TypeError, json.JSONDecodeError):
                pass
    return d


def _validate_thesis(ch: dict[str, Any]) -> None:
    _validate_enums({k: ch[k] for k in ("verdict", "analysis_level", "category", "subfield") if k in ch})
    checks = (("status", THESIS_STATUS_VALUES), ("posting_kind", THESIS_KIND_VALUES),
              ("pillar", THESIS_PILLAR_VALUES), ("work_route", WORK_ROUTE_VALUES))
    for k, allowed in checks:
        if k in ch and ch[k] is not None and ch[k] not in allowed:
            raise ValueError(f"thesis {k} must be one of {sorted(allowed)}, got {ch[k]!r}")
    if "country" in ch:
        c = ch["country"]
        if not (isinstance(c, str) and len(c) == 2 and c.isalpha() and c.isupper()):
            raise ValueError(f"country must be a 2-letter uppercase ISO code, got {c!r}")


def get_thesis(thesis_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM thesis WHERE id = ?", (thesis_id,)).fetchone()
    return _thesis_row(row) if row else None


def list_thesis(*, status: str | None = None, country: str | None = None,
                pillar: str | None = None) -> list[dict[str, Any]]:
    clauses, params = [], []
    for col, val in (("status", status), ("country", country), ("pillar", pillar)):
        if val is not None:
            clauses.append(f"{col} = ?")
            params.append(val)
    sql = "SELECT * FROM thesis" + (" WHERE " + " AND ".join(clauses) if clauses else "")
    sql += " ORDER BY COALESCE(score, -1) DESC, updated_at DESC"
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_thesis_row(r) for r in rows]


def create_thesis(t: dict[str, Any]) -> dict[str, Any]:
    if not all(k in t for k in ("id", "title", "institution")):
        raise ValueError("create_thesis requires id, title, institution")
    if OWNER_ONLY_FIELDS & t.keys():
        raise MyNotesGuardError("create_thesis cannot set my_notes: a new lead has no owner notes yet")
    _validate_thesis(t)
    _guard_judgment("thesis", t["id"], None, t, "automation")
    cols = dict(t)
    for col in _THESIS_JSON:
        if col in cols and not isinstance(cols[col], str):
            cols[col] = json.dumps(cols[col], ensure_ascii=False)
    if "score" not in cols and cols.get("fit_score") is not None:
        cols["score"] = max(0, min(10, cols["fit_score"] + (cols.get("route_adjustment") or 0)))
    now = _now_iso()
    cols.setdefault("created_at", now)
    cols["updated_at"], cols["version"] = now, 1
    with _connect() as conn:
        conn.execute(f"INSERT INTO thesis ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                     list(cols.values()))
    return get_thesis(t["id"])  # type: ignore[return-value]


def update_thesis(thesis_id: str, changes: dict[str, Any], *, source: str = "automation",
                  expected_version: int | None = None) -> dict[str, Any]:
    if not changes:
        raise ValueError("update_thesis called with no changes")
    if OWNER_ONLY_FIELDS & changes.keys() and source != "owner":
        raise MyNotesGuardError("only source='owner' may write my_notes on a thesis row")
    if SERVER_MANAGED_FIELDS & changes.keys():
        raise ValueError("update_thesis cannot set server-managed fields")
    _validate_thesis(changes)
    _guard_judgment("thesis", thesis_id, get_thesis(thesis_id), changes, source)
    cols = dict(changes)
    for col in _THESIS_JSON:
        if col in cols and not isinstance(cols[col], str):
            cols[col] = json.dumps(cols[col], ensure_ascii=False)
    if OWNER_ONLY_FIELDS & changes.keys() and "my_notes_at" not in cols:
        cols["my_notes_at"] = _now_iso()
    if ("fit_score" in cols or "route_adjustment" in cols) and "score" not in cols:
        cur = get_thesis(thesis_id) or {}
        fs = cols.get("fit_score", cur.get("fit_score"))
        ra = cols.get("route_adjustment", cur.get("route_adjustment")) or 0
        if fs is not None:
            cols["score"] = max(0, min(10, fs + ra))
    cols["updated_at"] = _now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in cols)
    params: list[Any] = list(cols.values())
    with _connect() as conn:
        if expected_version is not None:
            cur_ = conn.execute(
                f"UPDATE thesis SET {set_clause}, version = version + 1 WHERE id = ? AND version = ?",
                params + [thesis_id, expected_version])
            if cur_.rowcount == 0:
                row = conn.execute("SELECT version FROM thesis WHERE id = ?", (thesis_id,)).fetchone()
                if row is None:
                    raise KeyError(f"no such thesis: {thesis_id}")
                raise StaleWriteError(f"{thesis_id} is at version {row['version']}, expected {expected_version}")
        else:
            cur_ = conn.execute(f"UPDATE thesis SET {set_clause}, version = version + 1 WHERE id = ?",
                                params + [thesis_id])
            if cur_.rowcount == 0:
                raise KeyError(f"no such thesis: {thesis_id}")
    return get_thesis(thesis_id)  # type: ignore[return-value]


if __name__ == "__main__":
    init_db()
    print(f"tracker.db ready at {DB_PATH}")

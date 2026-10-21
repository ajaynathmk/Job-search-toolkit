#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The pipeline, start to end (rules/pipeline.md is the document; this file is the conductor).

Every stage of the system is registered here with its owner, its command, what it reads and writes, and the gate that must hold
before the next stage. Four kinds of owner:
  script   runs here, unattended, and never needs a judgment call (the watches, intake, the analysis, the checks, the mirror)
  session  needs a Claude session with the rules loaded (reading the best fits against the CV and confirming, tailoring, the digest);
           this file prepares its worklist and checks its gates, and refuses to fake the work
  owner    a decision only the owner makes, taken on the dashboard (approve, recheck, applied)
  request  only when the owner asks (version export)

Commands:
  python scripts/pipeline.py status [--json]             every stage, with live evidence of when it last ran
  python scripts/pipeline.py check  [--json] [--tests]   audit of the system's invariants (read-only)
  python scripts/pipeline.py queue                       the worklist for the session stages + digests/pipeline-<date>.md
  python scripts/pipeline.py run [--force] [--ignore-power]   the unattended part (once per day, on AC power)
  python scripts/scheduler.py install | remove | status   schedule the unattended run (Windows task, launchd or cron)

It never writes the tracker except through intake/analysis (which carry their proof), never sends mail, never submits anything.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import db  # noqa: E402
import definitions as D  # noqa: E402

DATA = ROOT / "data"
DIGESTS = ROOT / "digests"
LOGS = ROOT / "logs"
PY = sys.executable

PHASES = [
    ("P0", "Preflight"), ("P1", "Collect"), ("P2", "Intake and analysis"),
    ("P3", "Review and decide"), ("P4", "Build"), ("P5", "Report and persist"),
]


# ----------------------------------------------------------------------------- helpers

MAIL_STALE_DAYS = 2


def mail_state() -> dict:
    return _json(DATA / "mail" / "state.json", {})


def mail_events_open() -> dict:
    """Mail the pipeline could not settle on its own, and mail that asks the owner to act. Read from the event log (scripts/mail_sync.py)."""
    today = date.today()
    since14 = (today - timedelta(days=14)).isoformat()
    since30 = (today - timedelta(days=30)).isoformat()
    ev = db.list_mail_events(since=since30)
    act = [e for e in ev if e["kind"] in ("interview", "offer", "info_request") and e["mail_date"] >= since14 and e["state"] != "dismissed"]
    needs = [e for e in ev if e["state"] in ("unmatched", "needs_read") and e["kind"] in ("rejection", "interview", "offer", "info_request", "sent_application", "other_job")]
    return {"act_now": act, "needs_read": needs}


def _json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _latest(dirpath: Path) -> tuple[str | None, int]:
    files = sorted(dirpath.glob("20*.json")) if dirpath.exists() else []
    if not files:
        return None, 0
    return files[-1].stem, len(_json(files[-1], {}).get("items", []))


def _age_days(stem: str | None) -> int | None:
    try:
        return (date.today() - date.fromisoformat(stem)).days  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return None


def jd_text_ok(row: dict) -> bool:
    return db.jd_cache_ok(row)[0]


def on_ac_power() -> bool:
    """True when the PC is plugged in (or has no battery). Windows only; anywhere else we assume yes."""
    try:
        class S(ctypes.Structure):
            _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte), ("BatteryLifePercent", ctypes.c_byte), ("Reserved1", ctypes.c_byte),
                        ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
        s = S()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):  # type: ignore[attr-defined]
            return s.ACLineStatus != 0
    except Exception:  # noqa: BLE001
        pass
    return True


# ----------------------------------------------------------------------------- the audit

def check(run_tests: bool = False) -> list[dict]:
    """Invariants of the whole system. Each result: {id, severity FAIL|WARN|INFO|OK, title, count, items, fix}."""
    db.init_db()
    jobs = db.list_jobs()
    th = db.list_thesis()
    today = date.today()
    open_jobs = [j for j in jobs if j["status"] == "open"]
    out: list[dict] = []

    def add(cid, sev, title, items, fix=""):
        out.append({"id": cid, "severity": sev if items else "OK", "title": title, "count": len(items), "items": items[:12], "fix": fix})

    # ---- the strict scoring rule (CLAUDE.md rule 3)
    add("C01", "FAIL", "A score, tier or verdict with no full JD cached and no analysis record (strict scoring rule)",
        [j["id"] for j in jobs + th if ((j.get("score") is not None or j.get("tier") or j.get("verdict")) and j.get("analysis_level") in (None, "stub", "unreadable"))
         or ((j.get("verdict") or j.get("score") is not None) and j.get("analysis_level") in ("auto", "reviewed") and not jd_text_ok(j))],
        "Fetch the JD (scripts/intake.py), analyse it (scripts/analyze.py run), or restore the old value with source='rollback'.")
    add("C25", "WARN", "The cached JD changed after it was analysed (jd_sha no longer matches)",
        [j["id"] for j in jobs + th if j.get("jd_sha") and j.get("analysis_level") != "unreadable" and jd_text_ok(j) and db.current_jd_sha(j) != j["jd_sha"]], "python scripts/analyze.py run --levels auto,legacy,reviewed")
    add("C26", "INFO", f"Analysed under older rules (rule_version is not {D.RULE_VERSION})",
        [j["id"] for j in jobs + th if j.get("analysis_level") == "auto" and j.get("rule_version") != D.RULE_VERSION], "python scripts/analyze.py run --levels auto")
    # ---- intake
    add("C19", "WARN", "Stub row with a cached JD that has not been analysed", [j["id"] for j in jobs + th if j.get("analysis_level") == "stub" and jd_text_ok(j)],
        "python scripts/analyze.py run --levels stub")
    add("C20", "INFO", "JD could not be read in full after two attempts (unreadable): never scored",
        [j["id"] for j in jobs + th if j.get("analysis_level") == "unreadable"], "Open the posting by hand; python scripts/intake.py retry")
    add("C27", "INFO", "Stub row whose JD is not fetched yet", [j["id"] for j in jobs + th if j.get("analysis_level") == "stub" and not jd_text_ok(j)], "python scripts/intake.py run")
    import intake
    add("C32", "WARN", "Cached JD that cannot be trusted: garbled umlauts (UTF-8 read as Latin-1) or a Xing page with lists of other jobs mixed in",
        [f"{j['id']}: {intake.defective_cache(j)}" for j in jobs + th if intake.defective_cache(j)], "python scripts/intake.py repair (the daily intake pass repairs up to 120 a day)")
    # ---- the phone inbox (S31)
    rs = _json(DATA / "remote-state.json", {})
    if (ROOT / "config" / "remote.json").exists():
        rl = (rs.get("last_ok") or "")[:10]
        rage = (today - date.fromisoformat(rl)).days if re.fullmatch(r"\d{4}-\d{2}-\d{2}", rl) else None
        bad = [("last sync failed: " + str(rs["last_error"])[:140])] if rs.get("last_error") else ([f"last sync {rl or 'never'}"] if rage is None or rage >= 2 else [])
        add("C34", "WARN", "The phone inbox has not synced in 2+ days or the last sync failed (decisions on the phone are not reaching the PC)", bad,
            "python scripts/remote_sync.py sync (needs internet; the key is in config/remote.json; redeploy: cd remote && npx wrangler deploy)")
    # ---- the digest (S50)
    ps_ = _json(DATA / "pipeline-state.json", {})
    dg = _json(DATA / "digest-state.json", {})
    add("C33", "WARN", "The pipeline ran today but today's digest email did not go out",
        [f"run {str(ps_.get('last_run'))[:16]}, last digest {dg.get('date') or 'never'}"] if str(ps_.get("last_run", ""))[:10] == today.isoformat() and dg.get("date") != today.isoformat() else [],
        "python scripts/digest_email.py send (needs a valid Gmail token: python scripts/gmail_client.py auth)")
    # ---- verdicts and review
    add("C21", "INFO", "Best-fit verdict not yet confirmed by a Claude session (analysis_level auto or legacy)",
        [j["id"] for j in jobs + th if j.get("verdict") in D.BEST_FIT_VERDICTS and j.get("analysis_level") in ("auto", "legacy") and (j.get("status") in (None, "open", "lead"))],
        "python scripts/analyze.py show <id>, then review <id> --verdict ...")
    add("C22", "WARN", "Score or verdict changed after it was written (score_flag)", [f"{j['id']}: {j['score_flag']}" for j in jobs + th if j.get("score_flag")],
        "Read the flag on the dashboard; re-review if it matters. A reviewed verdict is never overwritten by the script.")
    add("C23", "WARN", "Open role with a cached JD but no verdict", [j["id"] for j in open_jobs if jd_text_ok(j) and not j.get("verdict") and j.get("analysis_level") != "unreadable"], "python scripts/analyze.py run --levels legacy,stub")
    add("C24", "WARN", "Package built or approved for a role the analysis says is not a fit (PASS, BLOCKED or EXPIRED)",
        [f"{j['id']} ({j['verdict']})" for j in open_jobs if j["approval"] in ("prepared", "requested") and j.get("verdict") in ("PASS", "BLOCKED", "EXPIRED")],
        "Decide on the dashboard: set Not for me, or review the verdict if it is wrong.")

    # ---- Gmail (S10, S11)
    ms = mail_state()
    last = (ms.get("last_ok") or "")[:10]
    age = (today - date.fromisoformat(last)).days if re.fullmatch(r"\d{4}-\d{2}-\d{2}", last) else None
    mail_bad = []
    if ms.get("last_error"):
        mail_bad.append("the last read failed: " + str(ms["last_error"])[:140])
    elif age is None or age >= MAIL_STALE_DAYS:
        mail_bad.append(f"last read {last or 'never'}")
    add("C28", "WARN", f"Gmail has not been read in {MAIL_STALE_DAYS}+ days, or the last read failed (replies and alerts are not coming in)", mail_bad,
        "python scripts/gmail_client.py auth (a token of a Google app in 'Testing' mode dies after 7 days; publish the app to 'In production' to stop that), then python scripts/mail_sync.py run")
    mo = mail_events_open()
    add("C29", "WARN", "Mail about an application that the pipeline could not match to a row or read with confidence (a Claude session reads it)",
        [f"{e['mail_date']} {e['kind']}: {e['subject'][:60]} [{e['msg_id']}]" for e in mo["needs_read"] if e["kind"] != "other_job" and e["kind"] != "sent_application"][:12],
        "python scripts/mail_sync.py show <msg_id>, then judge <msg_id> --kind K --job <id>")
    add("C30", "INFO", "Employer mail that asks the owner to act (interview, assessment, offer, documents to send or confirm), last 14 days",
        [f"{e['mail_date']} {e['kind']}: {e['subject'][:60]} -> {e.get('job_id') or e.get('thesis_id') or 'unmatched'}" for e in mo["act_now"]],
        "Do it, then python scripts/mail_sync.py judge <msg_id> --kind other_job (dismisses it) or answer the employer yourself.")
    pend = _json(DATA / "mail" / "pending.json", {})
    add("C31", "INFO", "Alert postings waiting for their own address (a Xing link that did not resolve to the posting)", [f"{v.get('employer')}: {v.get('title')}" for v in pend.values()][:12],
        "Resolve them with scripts/browser_jd_reader.py read_xing_redirect(<token>) in a session; THE LINK RULE: the /m/ link is never stored.")

    # ---- link rule, state integrity
    def _no_file(j):
        return j["jd_read"] and not (j["jd_path"] and (db.jd_cache_ok({"jd_path": j["jd_path"]})[0] or (ROOT / j["jd_path"].replace("\\", "/")).exists()))
    add("C02", "FAIL", "Open role with jd_read=1 but no JD file on disk (the 24 Sep defect)", [j["id"] for j in open_jobs if _no_file(j)],
        "Re-run scripts/fetch_jd.py --recheck for the row, or set jd_read=0.")
    add("C02b", "INFO", "Applied or closed role marked read with no JD file (applied before the cache existed; history, not fixable)",
        [j["id"] for j in jobs if j["status"] != "open" and _no_file(j)], "")
    add("C03", "WARN", "Open role with a URL that was never verified (THE LINK RULE)", [j["id"] for j in open_jobs if j["url"] and not j["url_verified"]], "python scripts/link_verify.py <id>")
    dead = re.compile(r"\[link check[^\]]*\][^\n]*dead: HTTP (404|410)")
    add("C03b", "WARN", "Open role whose last link check found the posting gone (HTTP 404/410)", [j["id"] for j in open_jobs if dead.search(j["notes"] or "")],
        "Confirm on the posting's own site, then mark Not for me on the dashboard.")
    stale_cut = (today - timedelta(days=D.LINK_MAX_AGE_DAYS)).isoformat()
    add("C04", "INFO", f"Link last verified more than {D.LINK_MAX_AGE_DAYS} days ago",
        [j["id"] for j in open_jobs if j["url_verified"] and str(j["url_verified"])[:10] < stale_cut], "python scripts/link_verify.py --stale-days 30")
    add("C05", "WARN", "Row says prepared/requested but its own notes record a block (state conflict)",
        [j["id"] for j in open_jobs if j["approval"] in ("prepared", "requested") and re.search(r"BLOCKED[^.\n]{0,120}(C1|C2|Humanmedizin|native|Muttersprache|mindestens)", j["notes"] or "")],
        "Decide on the dashboard: set Blocked, or Approve anyway after re-reading the posting.")
    add("C06", "WARN", "approval=blocked with no blocked_reason", [j["id"] for j in open_jobs if j["approval"] == "blocked" and not j["blocked_reason"]], "Quote the posting's own sentence in blocked_reason.")
    add("C07", "WARN", "approval=prepared but the package folder is missing or holds no CV file",
        [j["id"] for j in open_jobs if j["approval"] == "prepared" and not (j["package_path"] and (ROOT / j["package_path"].replace("\\", "/")).is_dir()
                                                                           and any(f.suffix in (".docx", ".pdf") for f in (ROOT / j["package_path"].replace("\\", "/")).iterdir()))],
        "Rebuild with scripts/ship-package.sh or set approval back.")
    soon, expired = [], []
    for j in open_jobs:
        dl = (j["deadline"] or "")[:10]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", dl):
            diff = (date.fromisoformat(dl) - today).days
            if diff < 0:
                expired.append(f"{j['id']} ({dl})")
            elif diff <= D.DEADLINE_SOON_DAYS and j["approval"] != "blocked":
                soon.append(f"{j['id']} ({dl})")
    add("C08", "INFO", f"Deadline within {D.DEADLINE_SOON_DAYS} days and not applied", soon, "Act today: dashboard -> Today.")
    add("C09", "WARN", "Deadline already passed, row still open", expired, "Mark Not for me, or confirm the posting is still open.")
    add("C10", "WARN", "Open role with no category (profile/domain.json)", [j["id"] for j in open_jobs if not j["category"] and j.get("analysis_level") not in ("stub", "unreadable")],
        "python scripts/analyze.py run")
    add("C11", "WARN", "Tier does not match score (7+ is tier 1, 4-6 tier 2, below 4 none)",
        [j["id"] for j in open_jobs if j["score"] is not None and j["approval"] != "blocked" and D.tier_of(j["score"]) != j["tier"]], "Set tier from score.")
    add("C12", "INFO", "Open role never read (jd_read=0) that is not a stub", [j["id"] for j in open_jobs if not j["jd_read"] and j.get("analysis_level") not in ("stub", "unreadable")],
        "python scripts/fetch_jd.py <id>")
    add("C13", "WARN", "Thesis lead with no cached posting text", [t["id"] for t in th if t.get("analysis_level") != "stub" and not jd_text_ok(t)], "Save the posting under jd/ and set jd_path.")
    uni_day, _ = _latest(DATA / "watch")
    job_day, _ = _latest(DATA / "jobwatch")
    for cid, label, day in (("C14", "Institution watch", uni_day), ("C15", "Company/job-board watch", job_day)):
        age = _age_days(day)
        add(cid, "WARN", f"{label} has not run in {D.WATCH_MAX_AGE_DAYS}+ days (last: {day or 'never'})", [f"last run {day}"] if age is None or age >= D.WATCH_MAX_AGE_DAYS else [], "python scripts/pipeline.py run --force")
    reviewed = _json(DATA / "reviewed.json", {})
    tracked_ids = {j["id"] for j in jobs} | {t["id"] for t in th}
    filed_missing = []
    for rid, v in reviewed.items():
        if v.get("verdict") == "filed":
            m = re.search(r"filed as (?:thesis )?(\S+)", v.get("reason", ""))
            if m and m.group(1).strip(".,") not in tracked_ids:
                filed_missing.append(f"{rid}: {m.group(1)}")
    add("C16", "FAIL", "Review log says 'filed' but the tracker has no such row", filed_missing, "File the role or correct data/reviewed.json.")
    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip() if (ROOT / "VERSION").exists() else "?"
    chlog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    add("C17", "FAIL", "VERSION does not match the open section of CHANGELOG.md", [] if re.search(rf"^## \[{re.escape(ver)}\] — in progress", chlog, re.M) else [f"VERSION={ver}"], "Fix VERSION or the changelog header.")
    if run_tests:
        failed = []
        for t in ("test_db.py", "test_analyze.py", "test_pipeline_e2e.py", "test_onboard.py", "test_webapp.py", "test_mail_sync.py", "test_remote_e2e.py", "test_privacy.py"):
            r = subprocess.run([PY, str(ROOT / "scripts" / "tests" / t)], capture_output=True, text=True, cwd=ROOT)
            if r.returncode != 0:
                failed.append(f"{t}: " + (r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "failed"))
        add("C18", "FAIL", "scripts/tests (my_notes guard, strict scoring, version pinning, analysis, Gmail stage)", failed, "Fix before anything else.")
    return out


# ----------------------------------------------------------------------------- the worklist

def unfiled_watch_items() -> int:
    """Watch postings intake has not filed yet (should be 0 right after intake)."""
    import intake
    urls, wids = intake.existing_index()
    return sum(1 for it in intake.watch_items() if it["id"] not in wids and intake.norm_url(it["url"]) not in urls)


def worklist() -> dict:
    jobs = db.list_jobs()
    th = db.list_thesis()
    open_jobs = [j for j in jobs if j["status"] == "open"]
    today = date.today()

    def row(j, kind="job"):
        return {"id": j["id"], "kind": kind, "title": j["title"][:80], "employer": (j.get("employer") or j.get("institution") or "")[:30], "deadline": j.get("deadline"), "score": j.get("score"),
                "verdict": j.get("verdict"), "level": j.get("analysis_level"), "flag": j.get("score_flag")}

    def rank(r):
        return (D.VERDICT_META.get(r["verdict"], {"rank": 9})["rank"], -(r["score"] or 0))
    review = [row(j) for j in open_jobs if j.get("verdict") in D.BEST_FIT_VERDICTS and j.get("analysis_level") in ("auto", "legacy")]
    review += [row(t, "thesis") for t in th if t.get("verdict") in D.BEST_FIT_VERDICTS and t.get("analysis_level") in ("auto", "legacy") and t.get("status") == "lead"]
    flagged = [row(j) for j in open_jobs if j.get("score_flag") and j.get("analysis_level") == "reviewed"]
    due = []
    for j in open_jobs:
        dl = (j["deadline"] or "")[:10]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", dl) and 0 <= (date.fromisoformat(dl) - today).days <= D.DEADLINE_SOON_DAYS and j["approval"] != "blocked":
            due.append(row(j))
    ready = [row(j) for j in open_jobs if j["approval"] == "prepared"]
    return {
        "date": today.isoformat(),
        "S10_mail_act_now": [{"date": e["mail_date"], "kind": e["kind"], "from": e["employer_hint"], "subject": e["subject"], "ref": e.get("job_id") or e.get("thesis_id"), "msg_id": e["msg_id"]}
                             for e in mail_events_open()["act_now"]],
        "S10_mail_needs_read": [{"date": e["mail_date"], "kind": e["kind"], "from": e["employer_hint"], "subject": e["subject"], "action": e["action"], "msg_id": e["msg_id"]}
                                for e in mail_events_open()["needs_read"] if e["kind"] not in ("other_job", "sent_application")],
        "S20_new_watch_items_to_file": unfiled_watch_items(),
        "S20_stubs_waiting_for_jd": [row(j) for j in open_jobs if j.get("analysis_level") == "stub" and not jd_text_ok(j)][:40],
        "S20_unreadable": [row(j) for j in open_jobs if j.get("analysis_level") == "unreadable"][:40],
        "S23_review_queue": sorted(review, key=rank),
        "S23_flagged_reviewed": flagged,
        "S40_rechecks": [row(j) for j in sorted(open_jobs, key=lambda x: x["updated_at"]) if j["approval"] == "recheck"][:D.RECHECK_CAP],
        "S40_approvals": [row(j) for j in sorted(open_jobs, key=lambda x: x["updated_at"]) if j["approval"] == "requested"][:D.APPROVAL_CAP],
        "S30_ready_to_send": ready,
        "S30_ready_not_a_fit": [r for r in ready if r["verdict"] in ("PASS", "BLOCKED", "EXPIRED")],
        "S30_deadlines_within_7_days": due,
    }


def write_queue() -> Path:
    w = worklist()
    (DATA / "queue.json").write_text(json.dumps(w, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = [c for c in check() if c["severity"] in ("FAIL", "WARN")]
    rq = w["S23_review_queue"]
    L = [f"# Pipeline brief, {w['date']}", "",
         "Written by `scripts/pipeline.py queue`. The session stages below need a Claude session with `rules/pipeline.md` loaded. "
         "Strict scoring rule: `python scripts/analyze.py show <id>` prints the full JD and records the read; only then `review <id> --verdict ...`.", ""]
    L += ["## Audit", ""] + ([f"- **{c['severity']}** {c['id']} {c['title']}: {c['count']}" for c in bad] or ["- all invariants hold"]) + [""]
    ms = mail_state()
    L += ["## S10-S11 Gmail", "", f"- last read: {ms.get('last_ok') or 'never'} via {ms.get('source') or '-'}" + (f"; **last attempt failed:** {ms.get('last_error')}" if ms.get("last_error") else ""),
          f"- alert mails read: {ms.get('alerts', 0)}; postings filed from them: {ms.get('filed', 0)}; waiting for an address: {ms.get('pending_url', 0)}"]
    L += [f"- **ACT NOW** {r['date']} {r['kind']}: {r['from']} - {r['subject'][:70]} ({r['ref'] or 'unmatched'})" for r in w["S10_mail_act_now"]]
    L += [f"- to read: {r['date']} {r['kind']} {r['from']} - {r['subject'][:60]} [{r['msg_id']}]" for r in w["S10_mail_needs_read"][:12]] + [""]
    L += ["## S20-S22 Intake and analysis", "", f"- new watch postings not filed yet: {w['S20_new_watch_items_to_file']}",
          f"- stubs waiting for a JD: {len(w['S20_stubs_waiting_for_jd'])}; unreadable: {len(w['S20_unreadable'])}", ""]
    L += [f"## S23 Review the best fits against the CV: {len(rq)} to confirm, {len(w['S23_flagged_reviewed'])} reviewed rows whose analysis moved", ""]
    L += [f"- {r['verdict']} {r['score']}: {r['title']} ({r['employer']}) `{r['id']}`" for r in rq[:30]] or ["- none"]
    L += ["", f"## S30 the owner decides: {len(w['S30_ready_to_send'])} ready to send ({len(w['S30_ready_not_a_fit'])} the analysis says are not a fit), {len(w['S30_deadlines_within_7_days'])} deadlines within {D.DEADLINE_SOON_DAYS} days", ""]
    L += [f"- {r['deadline']}: {r['title']} ({r['employer']}) {r['verdict']} {r['score']}" for r in sorted(w["S30_deadlines_within_7_days"], key=lambda r: r["deadline"])] or ["- none"]
    L += ["", f"## S40 Build: {len(w['S40_rechecks'])} rechecks (max {D.RECHECK_CAP}), {len(w['S40_approvals'])} approvals (max {D.APPROVAL_CAP})", ""]
    L += [f"- recheck {r['id']}: {r['title']}" for r in w["S40_rechecks"]] + [f"- approval {r['id']}: {r['title']}" for r in w["S40_approvals"]] or ["- none"]
    DIGESTS.mkdir(exist_ok=True)
    p = DIGESTS / f"pipeline-{w['date']}.md"
    p.write_text("\n".join(L) + "\n", encoding="utf-8")
    return p


# ----------------------------------------------------------------------------- the stage registry

def _S(id, phase, name, owner, run, rule, reads, writes, gate, evidence=None):
    return {"id": id, "phase": phase, "name": name, "owner": owner, "run": run, "rule": rule, "reads": reads, "writes": writes, "gate": gate, "evidence": evidence}


def _ev_watch(feed):
    def f():
        day, n = _latest(DATA / feed)
        age = _age_days(day)
        return ("ok" if age is not None and age < D.WATCH_MAX_AGE_DAYS else "stale", f"last run {day or 'never'}, {n} items at the levels sought")
    return f


def _ev_mail():
    ms = mail_state()
    if ms.get("last_error"):
        return ("blocked", "Gmail unreadable: " + str(ms["last_error"])[:90] + " (python scripts/gmail_client.py auth)")
    last = (ms.get("last_ok") or "")[:10]
    age = _age_days(last) if last else None
    mo = mail_events_open()
    detail = f"read {last or 'never'} via {ms.get('source') or '-'}; {len(mo['act_now'])} ask the owner to act, {len([e for e in mo['needs_read'] if e['kind'] not in ('other_job', 'sent_application')])} to read"
    return ("ok" if age is not None and age < MAIL_STALE_DAYS else "stale", detail)


def _ev_remote():
    st = _json(DATA / "remote-state.json", {})
    if not (ROOT / "config" / "remote.json").exists():
        return ("manual", "not set up (python scripts/remote_sync.py init)")
    if st.get("last_error"):
        return ("blocked", "last sync failed: " + str(st["last_error"])[:90])
    last = (st.get("last_ok") or "")[:10]
    age = _age_days(last) if last else None
    pl = st.get("last_pull") or {}
    return ("ok" if age is not None and age < 2 else "stale", f"synced {str(st.get('last_ok') or 'never')[:16].replace('T', ' ')}; last pull {pl.get('events', 0)} decisions ({pl.get('applied', 0)} applied); {st.get('decisions_applied_total', 0)} applied in all")


def _ev_check():
    c = [x for x in check() if x["severity"] in ("FAIL", "WARN")]
    f = [x for x in c if x["severity"] == "FAIL"]
    return ("blocked" if f else "warn" if c else "ok", f"{len(f)} FAIL, {len(c) - len(f)} WARN")


def _ev_intake():
    jobs = db.list_jobs() + db.list_thesis()
    stubs = sum(1 for j in jobs if j.get("analysis_level") == "stub")
    unread = sum(1 for j in jobs if j.get("analysis_level") == "unreadable")
    new = unfiled_watch_items()
    return ("pending" if new or stubs else "ok", f"{new} new postings to file, {stubs} stubs waiting, {unread} unreadable")


def _ev_analysis():
    jobs = db.list_jobs() + db.list_thesis()
    flagged = sum(1 for j in jobs if j.get("score_flag"))
    levels: dict[str, int] = {}
    for j in jobs:
        k = j.get("analysis_level") or "none"
        levels[k] = levels.get(k, 0) + 1
    return ("ok" if not levels.get("legacy") and not levels.get("stub") else "pending", f"{levels}; {flagged} scores moved")


def _ev_review():
    w = worklist()
    n = len(w["S23_review_queue"])
    return ("pending" if n else "ok", f"{n} best fits to confirm, {len(w['S23_flagged_reviewed'])} flagged")


def _ev_digest():
    st = _json(DATA / "digest-state.json", {})
    ok = st.get("date") == date.today().isoformat()
    return ("ok" if ok else "pending", f"sent {str(st.get('sent_at'))[:16].replace('T', ' ')}" if ok else f"not sent today (last: {st.get('date') or 'never'})")


def _ev_ready():
    w = worklist()
    return ("manual", f"{len(w['S30_ready_to_send'])} packages ready ({len(w['S30_ready_not_a_fit'])} not a fit)")


def _ev_mirror():
    p = DATA / "jobs-master.csv"
    return ("ok" if p.exists() and datetime.fromtimestamp(p.stat().st_mtime).date() == date.today() else "stale", "jobs-master.csv " + (datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d") if p.exists() else "missing"))


def stages() -> list[dict]:
    return [
        _S("S00", "P0", "Audit the invariants", "script", [PY, "scripts/pipeline.py", "check", "--tests"], "rules/pipeline.md (Audit)",
           "db/tracker.db, jd/, VERSION", "data/pipeline-check.json", "no FAIL; a FAIL stops intake and review until fixed", _ev_check),
        _S("S10", "P1", "Mail sync: what happened to my applications (sent, acknowledged, rejected, invited, offered, documents asked for)", "script", [PY, "scripts/mail_sync.py", "run"],
           "rules/mail.md, rules/runbook.md Step 3b", "Gmail (read only) via scripts/gmail_client.py: mail the owner sent, employer and portal replies",
           "mail_events table; jobs.status (applied/interview/rejected), applied_at, closed_at, status_source='gmail <date>'; thesis.status; digests/mail-<date>.md",
           "matched on employer AND role (address or reference number beat both); a weak match may confirm an application but never rejects or invites; an offer is never applied by the script; "
           "a hand-set status is never downgraded and a rejection always wins; never replies, labels or sends", _ev_mail),
        _S("S11", "P1", "Alert mail: LinkedIn and the region's job-board alerts become unscored rows (runbook 4)", "script", [PY, "scripts/mail_sync.py", "run"],
           "rules/mail.md, rules/alerts.md", "the same mailbox pass", "stub rows via intake.make_stub (watch_id mail-...), data/mail/pending.json",
           "every in-scope posting the tracker does not know is filed; nothing is scored from an email; a Xing /m/ link is resolved to the posting's own address or it waits", _ev_mail),
        _S("S12", "P1", "Board sweep: the region's job boards and WebSearch (runbook 5, 6)", "session", None, "rules/runbook.md Steps 5-6, rules/search-terms.md",
           "boards via scripts/browser_jd_reader.py, WebSearch", "candidate postings, filed as stubs", "LinkedIn/Xing keyword search only when attended"),
        _S("S13", "P1", "Wider-region sweep (runbook 5b)", "session", None, "rules/regions.md, regions/<code>/region.json", "boards per country",
           "candidate postings with country and route", "coverage line names the countries searched and not searched"),
        _S("S14", "P1", "Institution watch: universities, research institutes, hospitals, public bodies (runbook 5c)", "script", [PY, "scripts/uni_watch.py"], "rules/institutions.md", "regions/<code>/sources.json and profile/sources.json (institutions), the profile's role words",
           "data/watch/<date>.json, digests/institution-watch-<date>.md", "never writes the tracker", _ev_watch("watch")),
        _S("S15", "P1", "Company and job-board watch", "script", [PY, "scripts/job_watch.py"], "rules/job-watch.md", "regions/<code>/sources.json and profile/sources.json (national job board, Workday, ATS feeds)",
           "data/jobwatch/<date>.json, digests/job-watch-<date>.md", "never writes the tracker", _ev_watch("jobwatch")),
        _S("S16", "P1", "Thesis sweeps (boards, companies, faculty pages)", "request", None, "rules/institutions.md",
           "WebSearch and the institutions' own pages", "candidate theses (students only)", "weekly or when asked; facts about a professor come from the group's own page"),
        _S("S20", "P2", "Intake: file every in-scope posting as an unscored row and fetch its full JD", "script", [PY, "scripts/intake.py", "run"], "rules/pipeline.md (Intake)",
           "data/watch, data/jobwatch, the postings themselves", "stub rows (jobs and thesis), jd/<Employer>_<slug>/description.md, url_verified (THE LINK RULE)",
           "nothing is dropped for being off-topic; jd_read=1 only after the file exists; unreadable twice is kept and never scored", _ev_intake),
        _S("S22", "P2", "Analyse: read the full JD, check the walls, classify, compare with the CV, score, set the verdict", "script", [PY, "scripts/analyze.py", "run"],
           "profile/profile.json, profile/domain.json (cv_evidence), the region pack", "the cached JD in full, the CV evidence file",
           "category, subfield, score and breakdown, verdict and reason, cv_match, score_history, score_flag",
           "db.py refuses any judgment without the JD hash, the level and the breakdown; scores are re-computed every run and every move is flagged", _ev_analysis),
        _S("S23", "P3", "Review the best fits against the CV (a Claude session reads the full JD and confirms or overrides)", "session", None,
           "rules/job-watch.md (THE READING RULE), rules/pipeline.md (Verdicts)", "analyze.py show <id> (prints the full JD, records the read receipt)",
           "analysis_level=reviewed, the verdict and its reason", "a reviewed verdict needs a read receipt; the script never overwrites it, it only flags", _ev_review),
        _S("S30", "P3", "The owner decides on the dashboard", "owner", [PY, "scripts/webapp.py"], "docs/OPERATING.md", "http://127.0.0.1:5057 (Today, Jobs, Thesis, Review, Pipeline)",
           "approval, status, applied_at, my_notes (source=owner)", "nothing is built or sent without the owner's approval", _ev_ready),
        _S("S31", "P3", "Phone inbox: decisions made on the phone are applied here, a fresh snapshot goes out", "script", [PY, "scripts/remote_sync.py", "sync"], "rules/remote.md",
           "the Cloudflare Worker (remote/): decisions waiting in its KV", "approval / status / applied_at / my_notes (source=owner) through db.py; a snapshot of the best fits, ready packages and mail asking you to act",
           "decisions only queue on the phone side; the PC applies them through the same guards as the dashboard; a stale decision is reported, never forced", _ev_remote),
        _S("S40", "P4", "Rechecks, then approvals: tailor and write", "session", None, "rules/applications.md, rules/cv-build.md, rules/language-quality.md, profile/master-profile.md",
           "cached JD, my_notes, master-profile.md", "applications/<date>_<Employer>_<slug>/cv.md, cover-letter.md, match-report.md", "reorder only, never cut, never invent; max 3 rechecks and 2 approvals per run"),
        _S("S41", "P4", "Ship gate", "script", ["bash", "scripts/ship-package.sh", "<application-folder>"], "rules/cv-build.md", "cv.md, cover-letter.md",
           "CV and letter in .docx, .pdf", "aicheck, consistency_check, build-cv.js, fingerprint, render_check, verify_pdf pass, in that order"),
        _S("S42", "P4", "Draft or checklist, never send", "session", None, "CLAUDE.md rule 2, rules/applications.md", "the shipped package",
           "Gmail draft (create_draft only) or submission-checklist.md, approval=prepared", "never submits, never touches a portal with the owner's data"),
        _S("S50", "P5", "Digest email, always sent (structured HTML, once a day)", "script", [PY, "scripts/digest_email.py", "send"], "rules/digest.md, rules/runbook.md Step 9, CLAUDE.md rule 1",
           "the tracker, the mail pass, data/pipeline-state.json (so it runs after the state is written)", "digests/<date>.html and .txt, data/digest-state.json, one email to the owner only (send_digest_email)",
           "goes out even on zero hits; a second run the same day does not mail again; a failed send is recorded and audited (C33), never silent", _ev_digest),
        _S("S51", "P5", "Write back and mirror", "script", [PY, "scripts/pipeline.py", "run"], "rules/runbook.md Steps 10-11", "tracker",
           "data/jobs-master.csv, data/pipeline-state.json, logs/pipeline-run.log", "append-only CSV; my_notes untouched", _ev_mirror),
        _S("S52", "P5", "Version and toolkit export", "request", None, "CLAUDE.md (Versioning)", "CHANGELOG.md, VERSION",
           "closed version section; job-search-toolkit export without personal data", "only when the owner says 'this is version N' or asks for the export"),
    ]


def status() -> list[dict]:
    out = []
    for s in stages():
        ev = s["evidence"]() if s["evidence"] else (("manual", "needs a Claude session") if s["owner"] == "session" else ("manual", "on request") if s["owner"] == "request" else ("ok", ""))
        out.append({**{k: v for k, v in s.items() if k != "evidence"}, "state": ev[0], "detail": ev[1]})
    return out


# ----------------------------------------------------------------------------- run, tasks

def _run(cmd: list[str]) -> int:
    return subprocess.run(cmd, cwd=ROOT).returncode


def run_unattended(force: bool = False, ignore_power: bool = False) -> int:
    """Once per day, on AC power. Every log-on and every hour while plugged in triggers it (install-task); the first run of the day wins."""
    config.require_configured()
    started = datetime.now()
    try:                                                    # phone decisions are applied at every trigger (log-on, hourly), whatever else the run decides
        import remote_sync
        rs_ = remote_sync.sync()
        print("S31 phone inbox:", rs_.get("error") or {"decisions": rs_["pull"]["events"], "applied": rs_["pull"]["applied"], "snapshot_items": rs_["push"]["pushed"]})
    except Exception as exc:  # noqa: BLE001
        print("S31 phone inbox: skipped:", exc)
    state_p = DATA / "pipeline-state.json"
    prev = _json(state_p, {})
    if not force and prev.get("last_success_date") == date.today().isoformat():
        print(f"already ran today ({prev.get('last_run')}); use --force to run again")
        return 0
    if not ignore_power and not on_ac_power():
        print("on battery power: waiting for the charger (the task retries every hour)")
        return 0
    print("S00 audit")
    res = check(run_tests=True)
    fails = [c for c in res if c["severity"] == "FAIL"]
    (DATA / "pipeline-check.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("S10-S11 Gmail: replies to applications and alert mail")
    rc_mail = _run([PY, "scripts/mail_sync.py", "run"])
    print("S14 institution watch")
    rc = _run([PY, "scripts/uni_watch.py"])
    print("S15 company watch")
    rc |= _run([PY, "scripts/job_watch.py"])
    print("S20 intake: stubs, full JDs, first analysis")
    rc |= _run([PY, "scripts/intake.py", "run"])
    print("S22 re-analysis of every analysed row (dynamic scores, flags)")
    rc |= _run([PY, "scripts/analyze.py", "run", "--levels", "legacy,auto,reviewed"])
    print("worklist")
    brief = write_queue()
    try:
        import remote_sync
        remote_sync.sync()                                  # the snapshot now reflects this run's intake and analysis
    except Exception:  # noqa: BLE001
        pass
    print("S51 mirror")
    db.export_csv(DATA / "jobs-master.csv")
    w = _json(DATA / "queue.json", {})
    state = {"last_run": started.isoformat(timespec="seconds"), "last_success_date": date.today().isoformat() if rc == 0 else prev.get("last_success_date"), "exit": rc,
             "audit_fail": [c["id"] for c in fails], "mail_ok": rc_mail == 0, "review_queue": len(w.get("S23_review_queue", [])), "brief": str(brief.relative_to(ROOT))}
    state_p.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print("S50 digest email")
    import digest_email
    dres = digest_email.send_once()
    state["digest"] = dres
    state_p.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print("  ", dres)
    LOGS.mkdir(exist_ok=True)
    with (LOGS / "pipeline-run.log").open("a", encoding="utf-8") as f:
        f.write(f"{started:%Y-%m-%d %H:%M} exit={rc} audit_fail={state['audit_fail']} review_queue={state['review_queue']} took={(datetime.now() - started).seconds}s\n")
    print(f"done: brief {brief.name}, {state['review_queue']} best fits to review, audit FAIL: {state['audit_fail'] or 'none'}")
    return 1 if fails or rc else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["status", "check", "queue", "run"])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--tests", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--ignore-power", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if a.cmd == "status":
        st = status()
        if a.json:
            print(json.dumps(st, ensure_ascii=False, indent=1))
            return 0
        for pid, pname in PHASES:
            print(f"\n{pid} {pname}")
            for s in [x for x in st if x["phase"] == pid]:
                print(f"  {s['id']} [{s['state']:7}] {s['owner']:7} {s['name']}  -- {s['detail']}")
        return 0
    if a.cmd == "check":
        res = check(run_tests=a.tests)
        if a.json:
            print(json.dumps(res, ensure_ascii=False, indent=1))
        else:
            for c in res:
                print(f"{c['severity']:5} {c['id']} {c['title']}: {c['count']}")
                for it in c["items"][:5]:
                    print(f"        {it}")
                if c["count"] and c["fix"]:
                    print(f"        fix: {c['fix']}")
        return 1 if any(c["severity"] == "FAIL" for c in res) else 0
    if a.cmd == "queue":
        print(write_queue())
        return 0
    return run_unattended(a.force, a.ignore_power)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/webapp.py
==================

A local-only dashboard for db/tracker.db. Everything stays on this machine: Flask
binds to 127.0.0.1 only, the frontend is one static page, and every write goes
through scripts/db.py — the same guarded access layer everything else uses. This
is deliberately NOT a hosted page; it exists so the owner never has to hand-write SQL or
read raw JSON to work the tracker.

Why this file is allowed to write my_notes: every note submitted through this
UI's textarea is the owner typing directly into a page only he can reach (bound to
localhost, no auth needed because nothing outside this machine can open it) — that
is exactly the source="owner" case scripts/db.py's guard exists to allow. No other
script in this repo passes source="owner"; keep it that way.

Usage:
    python scripts/webapp.py            # serves http://127.0.0.1:5057
    python scripts/webapp.py --port 8080

Do not expose this beyond localhost (no --host 0.0.0.0) — it has no authentication
and can write to your tracker.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db as jobdb  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "webapp_static"
REPO_ROOT = Path(__file__).resolve().parent.parent

app = Flask(__name__, static_folder=None)

import app_routes  # noqa: E402  (the application page /start: upload a CV, run the pipeline, see the jobs)
import config as _config  # noqa: E402

app_routes.register(app)


@app.after_request
def add_no_cache(resp):
    # This is a local operator tool over live data — never let the browser serve a
    # stale cached copy of the tracker.
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/")
@app.route("/today")
@app.route("/jobs")
@app.route("/inbox")
@app.route("/review")
@app.route("/mail")
@app.route("/pipeline")
@app.route("/thesis")
@app.route("/watch")
def index():
    # The single-page interface (docs/OPERATING.md). /thesis and /watch land on its Thesis and Inbox pages.
    # Until a CV has been turned into a profile, the front door is the start page.
    if request.path == "/" and not _config.get().configured:
        return send_from_directory(STATIC_DIR, "start.html")
    return send_from_directory(STATIC_DIR, "app.html")


@app.route("/assets/<path:name>")
def assets(name):
    if name not in ("app.css", "app.js"):
        return jsonify({"error": "not found"}), 404
    return send_from_directory(STATIC_DIR, name)


@app.route("/api/watch", methods=["GET"])
def api_watch():
    """New postings from the institution watch (data/watch/*.json),
    first seen within the last `days` days. Read-only: promotion into the tracker or the thesis
    section happens only after a posting is opened, read and verified."""
    import json as _json
    from datetime import date, timedelta
    days = int(request.args.get("days", 7))
    wdir = REPO_ROOT / "data" / "watch"
    seen_p = wdir / "seen.json"
    seen = _json.loads(seen_p.read_text(encoding="utf-8")) if seen_p.exists() else {}
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    tracked = {(j.get("url") or "").split("?")[0].rstrip("/") for j in jobdb.list_jobs()}
    tracked |= {(t.get("posting_url") or "").split("?")[0].rstrip("/") for t in jobdb.list_thesis()}
    items = {}
    runs = sorted(wdir.glob("20*.json")) if wdir.exists() else []
    # Two feeds share one Inbox: the university watch (data/watch) and the company/job-board watch
    # (data/jobwatch, scripts/job_watch.py). Each item is tagged with its origin.
    feeds = [(wdir, seen, "university", runs)]
    jdir = REPO_ROOT / "data" / "jobwatch"
    if jdir.exists():
        jseen_p = jdir / "seen.json"
        feeds.append((jdir, _json.loads(jseen_p.read_text(encoding="utf-8")) if jseen_p.exists() else {}, "company", sorted(jdir.glob("20*.json"))))
    # Postings a Claude session has already read in full carry a verdict in data/reviewed.json
    # (rules/job-watch.md): they leave the Inbox, whatever the verdict, so nothing is judged twice.
    rev_p = REPO_ROOT / "data" / "reviewed.json"
    reviewed = _json.loads(rev_p.read_text(encoding="utf-8")) if rev_p.exists() else {}
    for _dir, _seen, origin, files in feeds:
        for f in files:
            for it in _json.loads(f.read_text(encoding="utf-8")).get("items", []):
                first = (_seen.get(it["id"]) or {}).get("first_seen", f.stem)
                if first >= cutoff and not it.get("excluded") and it["id"] not in reviewed:
                    it["first_seen"] = first
                    it["origin"] = origin
                    if origin == "company":
                        it["institution"] = it.get("employer") or it.get("institution", "")
                    it["in_tracker"] = (it.get("url") or "").split("?")[0].rstrip("/") in tracked
                    items[it["id"]] = it
    out = sorted(items.values(), key=lambda r: (-r.get("prov_score", 0), r.get("institution", "")))
    return jsonify({"runs": [f.stem for f in runs][-5:], "days": days, "count": len(out), "items": out})


@app.route("/api/definitions", methods=["GET"])
def api_definitions():
    """The one set of definitions (stages, categories, verdicts, windows) the dashboard uses: scripts/definitions.py."""
    import definitions as _d
    return jsonify(_d.as_dict())


# The list endpoints leave out the heavy analysis columns; the drawer fetches the full row on open.
_HEAVY = ("cv_match", "score_breakdown", "score_history", "verdict_reason", "jd_summary", "keywords")


def _slim(rows):
    return [{k: v for k, v in r.items() if k not in _HEAVY} for r in rows]


@app.route("/api/mail", methods=["GET"])
def api_mail():
    """What Gmail told the pipeline (scripts/mail_sync.py): mail that asks you to act, mail it could not settle, rejections and confirmations it recorded,
    and the state of the last read. Read-only; the event log holds facts about each mail, never its body."""
    import mail_sync as _ms
    q = _ms.queue()
    q["pending_count"] = len(q.get("pending_candidates", []))
    return jsonify(q)


@app.route("/api/pipeline", methods=["GET"])
def api_pipeline():
    """The whole system at a glance (rules/pipeline.md): every stage with live evidence, the invariant audit
    and the worklist. Read-only; computed from the same registry the unattended run uses."""
    import json as _json
    import pipeline as _pl
    state_p = REPO_ROOT / "data" / "pipeline-state.json"
    return jsonify({"phases": _pl.PHASES, "stages": _pl.status(), "check": _pl.check(), "queue": _pl.worklist(),
                    "state": _json.loads(state_p.read_text(encoding="utf-8")) if state_p.exists() else {}})


@app.route("/api/thesis", methods=["GET"])
def api_list_thesis():
    return jsonify(_slim(jobdb.list_thesis(status=request.args.get("status") or None,
                                           country=request.args.get("country") or None,
                                           pillar=request.args.get("pillar") or None)))


@app.route("/api/thesis/<thesis_id>", methods=["GET"])
def api_get_thesis(thesis_id):
    row = jobdb.get_thesis(thesis_id)
    return (jsonify(row), 200) if row else (jsonify({"error": "not found"}), 404)


@app.route("/api/thesis/<thesis_id>/status", methods=["POST"])
def api_thesis_status(thesis_id):
    body = request.get_json(force=True) or {}
    status = body.get("status")
    if status not in jobdb.THESIS_STATUS_VALUES:
        return jsonify({"error": f"status must be one of {sorted(jobdb.THESIS_STATUS_VALUES)}"}), 400
    changes = {"status": status}
    if status == "outreach_sent":
        changes["outreach_sent_at"] = _today()
    if status == "replied":
        changes["replied_at"] = _today()
    try:
        return jsonify(jobdb.update_thesis(thesis_id, changes))
    except KeyError:
        return jsonify({"error": "not found"}), 404


@app.route("/api/thesis/<thesis_id>/note", methods=["POST"])
def api_thesis_note(thesis_id):
    note = ((request.get_json(force=True) or {}).get("note") or "").strip()
    if not note:
        return jsonify({"error": "note is empty"}), 400
    try:
        return jsonify(jobdb.update_thesis(thesis_id, {"my_notes": note}, source="owner"))
    except KeyError:
        return jsonify({"error": "not found"}), 404


@app.route("/api/jobs", methods=["GET"])
def api_list_jobs():
    status = request.args.get("status") or None
    approval = request.args.get("approval") or None
    source = request.args.get("source") or None
    rows = jobdb.list_jobs(status=status, approval=approval, source=source)
    return jsonify(_slim(rows))


@app.route("/api/jobs/<job_id>", methods=["GET"])
def api_get_job(job_id):
    row = jobdb.get_job(job_id)
    if row is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(row)


@app.route("/api/jobs/<job_id>/open-folder", methods=["POST"])
def api_open_folder(job_id):
    """Opens this job's application package folder in Windows Explorer, on this
    machine only -- same "bound to localhost, nothing else can reach it" trust
    model as the my_notes write path above. Never call this from anywhere that
    isn't this local dashboard."""
    row = jobdb.get_job(job_id)
    if row is None:
        return jsonify({"error": "not found"}), 404
    package_path = (row.get("package_path") or "").strip()
    if not package_path:
        return jsonify({"error": "no package folder recorded for this job yet"}), 404

    folder = Path(package_path)
    folder = folder if folder.is_absolute() else (REPO_ROOT / folder)
    folder = folder.resolve()

    # This endpoint has no auth beyond "the request came from localhost" -- keep
    # it from being pointed at an arbitrary path anywhere else on the owner's machine.
    try:
        folder.relative_to(REPO_ROOT)
    except ValueError:
        return jsonify({"error": "package_path resolves outside the repo, refusing to open it"}), 400

    if not folder.is_dir():
        return jsonify({"error": f"folder does not exist on disk: {folder}"}), 404

    try:
        if sys.platform.startswith("win"):
            os.startfile(str(folder))  # noqa: S606 -- local machine only
        else:
            import subprocess
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])
    except Exception as e:  # pragma: no cover -- OS-dependent failure path
        return jsonify({"error": str(e)}), 500

    return jsonify({"opened": str(folder)})


@app.route("/api/jobs/<job_id>/approve", methods=["POST"])
def api_approve(job_id):
    return _act(job_id, {"approval": "requested", "approved_at": _today()})


@app.route("/api/jobs/<job_id>/recheck", methods=["POST"])
def api_recheck(job_id):
    return _act(job_id, {"approval": "recheck", "recheck_at": _today()})


@app.route("/api/jobs/<job_id>/reject", methods=["POST"])
def api_reject(job_id):
    return _act(job_id, {"status": "rejected", "approval": "none", "closed_at": _today()})


@app.route("/api/jobs/<job_id>/note", methods=["POST"])
def api_note(job_id):
    """Save a note with no button pressed -- 'standing context', per
    rules/tracker-schema.md's note-reading table. Does not touch approval/status."""
    body = request.get_json(force=True) or {}
    note = (body.get("note") or "").strip()
    if not note:
        return jsonify({"error": "note is empty"}), 400
    try:
        row = jobdb.update_job(job_id, {"my_notes": note}, source="owner")
    except KeyError:
        return jsonify({"error": "not found"}), 404
    return jsonify(row)


@app.route("/api/jobs/<job_id>/status", methods=["POST"])
def api_set_status(job_id):
    body = request.get_json(force=True) or {}
    new_status = body.get("status")
    if new_status not in jobdb.STATUS_VALUES:
        return jsonify({"error": f"status must be one of {sorted(jobdb.STATUS_VALUES)}"}), 400
    changes = {"status": new_status}
    if new_status == "applied":
        # The dashboard lets the owner pick the actual date he applied (e.g. recording
        # something he sent yesterday, not always "right now") -- a well-formed
        # date from the client wins; anything missing or malformed falls back to
        # today rather than rejecting the whole status change over a date field.
        applied_at = body.get("applied_at")
        if applied_at:
            try:
                from datetime import date as _date
                _date.fromisoformat(applied_at)
            except ValueError:
                applied_at = None
        changes["applied_at"] = applied_at or _today()
    row = jobdb.update_job(job_id, changes)
    return jsonify(row)


_SET_FIELDS = {"status", "approval", "applied_at", "closed_at", "approved_at", "recheck_at"}


@app.route("/api/jobs/<job_id>/set", methods=["POST"])
def api_set(job_id):
    """Whitelisted multi-field update used by the interface for stage changes and their
    undo. Only workflow fields; my_notes and everything else is refused."""
    body = request.get_json(force=True) or {}
    bad = set(body) - _SET_FIELDS
    if bad or not body:
        return jsonify({"error": f"allowed fields: {sorted(_SET_FIELDS)}"}), 400
    if "status" in body and body["status"] not in jobdb.STATUS_VALUES:
        return jsonify({"error": "invalid status"}), 400
    if "approval" in body and body["approval"] not in jobdb.APPROVAL_VALUES:
        return jsonify({"error": "invalid approval"}), 400
    from datetime import date as _d
    for k in ("applied_at", "closed_at", "approved_at", "recheck_at"):
        if body.get(k):
            try:
                _d.fromisoformat(body[k])
            except ValueError:
                return jsonify({"error": f"{k} must be YYYY-MM-DD"}), 400
    try:
        return jsonify(jobdb.update_job(job_id, body))
    except KeyError:
        return jsonify({"error": "not found"}), 404
    except jobdb.StaleWriteError as e:
        return jsonify({"error": str(e)}), 409


def _act(job_id, changes):
    body = request.get_json(silent=True) or {}
    note = (body.get("note") or "").strip()
    if note:
        changes["my_notes"] = note
    try:
        row = jobdb.update_job(job_id, changes, source="owner" if note else "automation")
    except KeyError:
        return jsonify({"error": "not found"}), 404
    except jobdb.StaleWriteError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify(row)


def _today() -> str:
    from datetime import date
    return date.today().isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5057)
    args = parser.parse_args()

    jobdb.init_db()
    print(f"Job-search dashboard: http://127.0.0.1:{args.port}  (local only — do not expose this)")
    # use_reloader=True (independent of debug, which stays off -- no interactive
    # debugger on a page that can write to the tracker) watches every imported
    # module, including db.py, and restarts on change. Without this, a long-running
    # dashboard process keeps serving whatever version of db.py it imported at
    # startup, silently, with no error -- see a real
    # bug this caused.
    _phone_sync_loop()
    app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=True)


def _phone_sync_loop():
    """While the dashboard runs, keep the phone inbox in step every 5 minutes (rules/remote.md). A missing config or no internet is silent: the pipeline audit reports it."""
    import threading
    import time

    def loop():
        import remote_sync
        while True:
            try:
                if (REPO_ROOT / "config" / "remote.json").exists():
                    remote_sync.sync()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(300)
    threading.Thread(target=loop, daemon=True, name="phone-sync").start()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/app_routes.py: the web side of the application (page /start). Registered by scripts/webapp.py.

The page asks for a CV, starts scripts/app_core.py as a separate process (so closing the tab, a crash or a sleeping laptop loses nothing; progress is in
profile/app/state.json) and shows what the engine found. Everything is local: the server binds to 127.0.0.1 and refuses requests whose Host or Origin is
another site, so a web page you happen to have open cannot start a run, upload files or read your jobs.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, abort, jsonify, request, send_from_directory

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app_core as A  # noqa: E402
import claude_runner  # noqa: E402
import config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "webapp_static"
LOGS = ROOT / "logs"
LOCAL = ("127.0.0.1", "localhost", "::1", "[::1]")
bp = Blueprint("jobkit_app", __name__)


def register(app) -> None:
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
    app.register_blueprint(bp)


@bp.before_app_request
def guard():
    host = (request.host or "").rsplit(":", 1)[0] if not (request.host or "").startswith("[") else request.host.split("]")[0] + "]"
    if host not in LOCAL:
        abort(403)                                          # a DNS-rebinding page reaches the server under its own name
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("Origin")
        if origin and (urlparse(origin).hostname or "") not in ("127.0.0.1", "localhost", "::1"):
            abort(403)                                      # a form on another site posting to localhost


def err(message: str, hint: str = "", status: int = 400):
    return jsonify({"error": message, "hint": hint}), status


# ----------------------------------------------------------------------------- processes

def alive(pid) -> bool:
    if not pid:
        return False
    try:
        pid = int(pid)
        if os.name == "nt":
            import ctypes
            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x1000, False, pid)           # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            code = ctypes.c_ulong()
            k.GetExitCodeProcess(h, ctypes.byref(code))
            k.CloseHandle(h)
            return code.value == 259                        # STILL_ACTIVE
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, AttributeError):
        return False


def kill_tree(pid) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, timeout=20)
        else:
            os.kill(int(pid), 15)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass


def spawn(args: list[str], log_name: str) -> int:
    LOGS.mkdir(exist_ok=True)
    log = open(LOGS / log_name, "ab")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "JOBKIT_PROFILE_DIR": str(config.PROFILE_DIR)}
    kw = {"creationflags": 0x00000200 | 0x00000008} if os.name == "nt" else {"start_new_session": True}     # its own process group: it outlives the page
    p = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "app_core.py"), *args], cwd=str(ROOT), stdout=log, stderr=log, env=env, **kw)
    return p.pid


def current_state() -> dict:
    """The state file, with a run or a tailoring job whose process has died turned into an error the page can show (never left spinning)."""
    st = A.load_state()
    if st["status"] == "running" and not alive(st.get("pid")):
        stages = [dict(s, status="pending") if s["status"] == "running" else s for s in st["stages"]]
        st = A.patch_state(status="error", error="The run stopped before it finished (the computer slept or the window was closed).",
                           hint="Press Start again: every finished step is kept.", stages=stages, pid=None)
    for jid, t in list((st.get("tailor") or {}).items()):
        if t.get("status") == "running" and t.get("pid") and not alive(t.get("pid")):
            A.set_tailor(jid, {**t, "status": "error", "message": "The writing stopped before it finished. Press the button again."})
            st = A.load_state()
    return st


# ----------------------------------------------------------------------------- pages and read-only data

@bp.route("/start")
def start_page():
    return send_from_directory(STATIC, "start.html")


@bp.route("/assets/start.css")
def start_css():
    return send_from_directory(STATIC, "start.css")


@bp.route("/assets/start.js")
def start_js():
    return send_from_directory(STATIC, "start.js")


@bp.route("/api/app/engine")
def api_engine():
    packs = sorted(p.name for p in (ROOT / "regions").iterdir() if p.is_dir() and not p.name.startswith("_") and (p / "region.json").exists()) if (ROOT / "regions").exists() else []
    return jsonify({"claude": claude_runner.status(), "configured": config.get().configured, "region_packs": packs,
                    "has_cv": (config.PROFILE_DIR / "cv-source.txt").exists(), "model": os.environ.get("JOBKIT_CLAUDE_MODEL") or "sonnet"})


@bp.route("/api/app/status")
def api_status():
    st = current_state()
    st["cv_now"] = {"has": (config.PROFILE_DIR / "cv-source.txt").exists(), "notes": (config.PROFILE_DIR / "user-notes.txt").exists()}
    return jsonify(st)


@bp.route("/api/app/understood")
def api_understood():
    return jsonify(A.understood())


@bp.route("/api/app/results")
def api_results():
    return jsonify({"results": A.results(int(request.args.get("limit", 600))), "counts": A.counts() if config.get().configured else {}})


# ----------------------------------------------------------------------------- actions

@bp.route("/api/app/cv", methods=["POST"])
def api_cv():
    st = current_state()
    if st["status"] == "running":
        return err("A run is in progress", "Stop it first, or wait until it finishes.", 409)
    try:
        if request.files.get("file"):
            f = request.files["file"]
            info = A.accept_cv(f.filename or "cv", data=f.read())
        else:
            body = request.get_json(silent=True) or {}
            info = A.accept_cv("pasted.txt", text=str(body.get("text") or ""))
        if request.form.get("notes") is not None:
            A.save_notes(request.form.get("notes", ""))
    except A.Fail as exc:
        return err(str(exc), exc.hint)
    return jsonify(info)


@bp.route("/api/app/notes", methods=["POST"])
def api_notes():
    A.save_notes(str((request.get_json(silent=True) or {}).get("text") or ""))
    return jsonify({"ok": True})


@bp.route("/api/app/run", methods=["POST"])
def api_run():
    st = current_state()
    if st["status"] == "running":
        return err("A run is already in progress", "", 409)
    if not (config.PROFILE_DIR / "cv-source.txt").exists():
        return err("Upload your CV first", "")
    body = request.get_json(silent=True) or {}
    args = ["run", "--review-limit", str(int(body.get("review_limit") if body.get("review_limit") is not None else 30))]
    if body.get("budget"):
        args += ["--budget", str(float(body["budget"]))]
    if body.get("force"):
        args += ["--force"]
    if body.get("from"):
        args += ["--from", str(body["from"])]
    pid = spawn(args, "app-run.log")
    A.patch_state(status="running", pid=pid, error=None, hint=None)
    return jsonify({"ok": True, "pid": pid})


@bp.route("/api/app/stop", methods=["POST"])
def api_stop():
    st = current_state()
    A.APP_DIR.mkdir(parents=True, exist_ok=True)
    A.STOP_P.write_text("stop", encoding="utf-8")
    if (request.get_json(silent=True) or {}).get("now") and st.get("pid"):
        kill_tree(st["pid"])
        A.patch_state(status="stopped", pid=None)
        A.STOP_P.unlink(missing_ok=True)
    return jsonify({"ok": True})


@bp.route("/api/app/assumptions", methods=["POST"])
def api_assumptions():
    try:
        out = A.apply_edits((request.get_json(silent=True) or {}).get("edits") or {})
    except A.Fail as exc:
        return err(str(exc), exc.hint)
    pid = spawn(["refresh"], "app-refresh.log")
    return jsonify({**out, "rescoring": True, "pid": pid})


@bp.route("/api/app/tailor/<job_id>", methods=["POST"])
def api_tailor(job_id):
    t = current_state().get("tailor") or {}
    if any(v.get("status") == "running" for v in t.values()):
        return err("Another application is being written", "One at a time keeps the usage low.", 409)
    pid = spawn(["tailor", job_id], "app-tailor.log")
    A.set_tailor(job_id, {"status": "running", "message": "Claude is writing your CV and letter (3 to 8 minutes)", "started": A._now(), "pid": pid})
    return jsonify({"ok": True})


@bp.route("/api/app/package/<job_id>")
def api_package(job_id):
    t = (A.load_state().get("tailor") or {}).get(job_id) or {}
    return jsonify({"folder": t.get("folder"), "files": t.get("files") or [], "status": t.get("status")})


@bp.route("/api/app/package/<job_id>/<path:name>")
def api_package_file(job_id, name):
    t = (A.load_state().get("tailor") or {}).get(job_id) or {}
    if not t.get("folder"):
        abort(404)
    folder = (ROOT / t["folder"]).resolve()
    if not str(folder).startswith(str((ROOT / "applications").resolve())):
        abort(404)
    return send_from_directory(folder, name)


# ----------------------------------------------------------------------------- the rest of the toolkit

def run_script(args: list[str], timeout: int = 120) -> str:
    try:
        p = subprocess.run([sys.executable, *args], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8", "JOBKIT_PROFILE_DIR": str(config.PROFILE_DIR)})
        return ((p.stdout or "") + (p.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return "timed out"


@bp.route("/api/app/extras")
def api_extras():
    cfgdir = ROOT / "config"
    return jsonify({
        "schedule": run_script(["scripts/scheduler.py", "status"], 30)[-300:],
        "gmail": {"credentials": (cfgdir / "gmail_credentials.json").exists(), "token": (cfgdir / "gmail_token.json").exists(), "guide": "docs/GMAIL.md"},
        "phone": {"configured": (cfgdir / "remote.json").exists(), "guide": "docs/PHONE.md"},
        "tools": run_script(["scripts/onboard.py", "doctor"], 60)[-1500:],
    })


@bp.route("/api/app/schedule", methods=["POST"])
def api_schedule():
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if action == "install":
        t = str(body.get("time") or "07:30")
        if not __import__("re").fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
            return err("Time must look like 07:30")
        out = run_script(["scripts/scheduler.py", "install", "--time", t], 60)
    elif action == "remove":
        out = run_script(["scripts/scheduler.py", "remove"], 60)
    else:
        return err("action must be install or remove")
    return jsonify({"output": out[-400:]})


@bp.route("/api/app/digest", methods=["POST"])
def api_digest():
    """Preview the daily summary, or send it to the person's own address (the only mail the toolkit ever sends)."""
    import digest_email
    if (request.get_json(silent=True) or {}).get("send"):
        try:
            return jsonify({"sent": digest_email.send_once(force=True)})
        except Exception as exc:  # noqa: BLE001
            return err(f"Could not send: {type(exc).__name__}", "Connect Gmail first (docs/GMAIL.md).")
    subject, text, html = digest_email.build()
    return jsonify({"subject": subject, "html": html, "text": text[:4000]})

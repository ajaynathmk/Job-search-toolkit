#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/app_core.py: the application's engine. A CV goes in; ranked, fully read jobs come out.

The application (`app.py`, page `/start`) needs one thing from a person: their CV. This module does the rest by calling the toolkit's own scripts in order and
Claude Code (scripts/claude_runner.py) for the three steps that need judgment. Progress is written to profile/app/state.json after every step, so closing the
browser, stopping the run or a crash loses nothing: starting again resumes at the first step that is not done.

    understand  Claude reads the CV and writes profile.json, domain.json, master-profile.md and assumptions.json (onboarding/app/understand.md)
    configure   the configuration is validated; Claude repairs what fails (at most twice)
    search      the employer feeds for the person's industries (onboard.py build-sources)
    collect     the watches read the sources: employers, universities, boards
    read        intake files every student-level posting and fetches its full text; the script analyses all of it
    review      Claude reads the best fits in full against the CV and confirms or overrides each verdict (onboarding/app/review.md)

    python scripts/app_core.py run [--review-limit 30] [--budget 8] [--from STAGE] [--force]
    python scripts/app_core.py tailor <job id>       build a tailored CV and letter for one approved role
    python scripts/app_core.py refresh               re-score after the person corrected an assumption (no Claude, no network)
    python scripts/app_core.py status                the state file

Nothing here submits an application, sends mail or creates an account. The person's data lives in profile/ and db/ (git-ignored).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import claude_runner  # noqa: E402
import config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
APP_DIR = config.PROFILE_DIR / "app"
STATE_P = APP_DIR / "state.json"
STOP_P = APP_DIR / "stop"
UPLOADS = APP_DIR / "uploads"
PROMPTS = ROOT / "onboarding" / "app"

STAGES = [
    ("understand", "Understand your CV: your field, your strengths, what to search for"),
    ("configure", "Check the configuration"),
    ("search", "Find the employers in your field"),
    ("collect", "Collect postings from the sources"),
    ("read", "Read every posting in full and score it against your CV"),
    ("review", "Confirm the best fits by reading them again"),
]
BEST = ("APPLY", "BACKUP", "PLAN", "LATER")

# Allowed to run without a prompt, one pattern at a time. Nothing here can send mail or reach a portal.
TOOLS_UNDERSTAND = (["Read", "Write", "Edit", "Glob", "Grep", "Bash", "WebSearch", "WebFetch"],
                    ["Read", "Write", "Edit", "Glob", "Grep", "Bash(python scripts/onboard.py *)", "WebSearch", "WebFetch"])
TOOLS_REVIEW = (["Read", "Glob", "Grep", "Bash"],
                ["Read", "Glob", "Grep", "Bash(python scripts/analyze.py *)", "Bash(python scripts/detect_cv_constraints.py *)"])
TOOLS_TAILOR = (["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
                ["Read", "Write", "Edit", "Glob", "Grep", "Bash(bash scripts/ship-package.sh *)", "Bash(node scripts/build-cv.js *)", "Bash(python scripts/aicheck.py *)",
                 "Bash(python scripts/consistency_check.py *)", "Bash(python scripts/analyze.py show *)", "Bash(python scripts/fingerprint.py *)"])


# ----------------------------------------------------------------------------- state

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def fresh_state() -> dict:
    return {"version": 1, "status": "idle", "error": None, "hint": None, "cost_usd": 0.0, "budget_usd": 8.0, "started": None, "finished": None, "pid": None,
            "cv": {}, "stages": [{"id": i, "label": l, "status": "pending", "message": "", "started": None, "finished": None, "cost_usd": 0.0} for i, l in STAGES],
            "counts": {}, "understood_sha": None, "needs_rescore": False, "tailor": {}, "log": []}


ENGINE_KEYS = ("status", "error", "hint", "cost_usd", "budget_usd", "started", "finished", "pid", "stages", "counts", "understood_sha", "log")


@contextmanager
def _locked(timeout: float = 8.0):
    """One writer at a time across processes: the engine, the page's server and the tailoring process all update state.json. A stale lock (a crashed writer) is broken after 10 s."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    lock = APP_DIR / "state.lock"
    end = time.time() + timeout
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 10:
                    lock.unlink()
                    continue
            except OSError:
                pass
            if time.time() > end:
                break                                       # better to write without the lock than to lose the update
            time.sleep(0.03)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _read_raw() -> dict | None:
    for attempt in range(6):                                # a reader can meet the instant of a replace on Windows
        try:
            return json.loads(STATE_P.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (PermissionError, ValueError):
            time.sleep(0.05 * (attempt + 1))
    return None


def load_state() -> dict:
    base = fresh_state()
    base.update(_read_raw() or {})
    ids = {x["id"] for x in base["stages"]}
    for i, l in STAGES:                                     # a newer version added a stage
        if i not in ids:
            base["stages"].append({"id": i, "label": l, "status": "pending", "message": "", "started": None, "finished": None, "cost_usd": 0.0})
    return base


def _write(cur: dict) -> None:
    tmp = STATE_P.with_name(f"state.{os.getpid()}.{threading.get_ident()}.tmp")       # a name of its own: two writers never share a temp file
    tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    for attempt in range(8):
        try:
            os.replace(tmp, STATE_P)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    STATE_P.write_text(tmp.read_text(encoding="utf-8"), encoding="utf-8")
    tmp.unlink(missing_ok=True)


def save_state(st: dict, keys: tuple = ENGINE_KEYS) -> None:
    """Write only the keys this caller owns, onto the freshest copy on disk, so the engine and the page never overwrite each other's updates."""
    with _locked():
        cur = _read_raw() or fresh_state()
        for k in keys:
            if k in st:
                cur[k] = st[k]
        _write(cur)


def patch_state(**kw) -> dict:
    with _locked():
        cur = load_state()
        cur.update(kw)
        _write(cur)
        return cur


def set_tailor(job_id: str, entry: dict) -> None:
    with _locked():
        cur = load_state()
        cur.setdefault("tailor", {})[job_id] = entry
        _write(cur)


def stage(st: dict, sid: str) -> dict:
    return next(s for s in st["stages"] if s["id"] == sid)


def note(st: dict, text: str) -> None:
    st["log"] = (st.get("log") or [])[-60:] + [f"{datetime.now():%H:%M:%S} {text}"]


def begin(st: dict, sid: str, message: str = "") -> None:
    s = stage(st, sid)
    s.update(status="running", message=message, started=_now(), finished=None)
    note(st, f"{s['label']}: started")
    save_state(st)


def finish(st: dict, sid: str, status: str, message: str, cost: float = 0.0) -> None:
    s = stage(st, sid)
    s.update(status=status, message=message, finished=_now())
    s["cost_usd"] = round(s.get("cost_usd", 0) + cost, 4)
    st["cost_usd"] = round(st.get("cost_usd", 0) + cost, 4)
    note(st, f"{s['label']}: {status}" + (f" ({message})" if message else ""))
    save_state(st)


class Stop(Exception):
    """The person pressed Stop."""


class Fail(Exception):
    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


def check_stop() -> None:
    if STOP_P.exists():
        raise Stop()


# ----------------------------------------------------------------------------- helpers

def script(args: list[str], timeout: int = 3600) -> tuple[int, str]:
    """Run one of the toolkit's scripts as a child process; returns (exit code, the tail of its output)."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "JOBKIT_PROFILE_DIR": str(config.PROFILE_DIR)}
    try:
        p = subprocess.run([PY, *args], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    return p.returncode, ((p.stdout or "") + (p.stderr or ""))[-3000:]


def cv_sha() -> str:
    p = config.PROFILE_DIR / "cv-source.txt"
    notes = config.PROFILE_DIR / "user-notes.txt"
    h = hashlib.sha256()
    for f in (p, notes):
        if f.exists():
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def guess_language(text: str) -> str:
    t = " " + re.sub(r"[^a-zäöüß]+", " ", text.lower()) + " "
    de = sum(t.count(w) for w in (" und ", " der ", " die ", " das ", " mit ", " für ", " von ", " ich ", " bei "))
    en = sum(t.count(w) for w in (" and ", " the ", " with ", " for ", " of ", " in ", " at ", " to "))
    return "de" if de > en * 0.6 and de > 8 else "en"


def accept_cv(filename: str, data: bytes | None = None, text: str | None = None) -> dict:
    """Store an uploaded CV (or pasted text) and extract it to profile/cv-source.txt. Returns what the page shows."""
    import onboard
    APP_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS.mkdir(parents=True, exist_ok=True)
    if text is not None:
        body = text
        saved = UPLOADS / "cv-pasted.txt"
        saved.write_text(text, encoding="utf-8")
    else:
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename or "cv").name)[:80] or "cv"
        ext = Path(name).suffix.lower()
        if ext not in (".pdf", ".docx", ".md", ".txt", ".markdown"):
            raise Fail("This file type is not supported", "Upload a PDF, a Word file (.docx), Markdown or plain text, or paste the text.")
        saved = UPLOADS / name
        saved.write_bytes(data or b"")
        try:
            body = onboard.extract_text(saved)
        except Exception as exc:  # noqa: BLE001
            raise Fail(f"The file could not be read ({type(exc).__name__})", "Try another format, or paste the text of the CV.")
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if len(body) < 300:
        raise Fail("There is almost no text in this CV", "A scanned PDF has no text layer. Paste the text of the CV instead, or upload a Word or text version.")
    (config.PROFILE_DIR / "cv-source.txt").parent.mkdir(parents=True, exist_ok=True)
    (config.PROFILE_DIR / "cv-source.txt").write_text(body + "\n", encoding="utf-8", newline="\n")
    cv = {"file": saved.name, "chars": len(body), "language": guess_language(body), "uploaded": _now()}
    cur = load_state()
    patch_state(cv=cv, **({"status": "idle"} if cur["status"] in ("done", "error", "stopped") else {}))
    return cv


def save_notes(text: str) -> None:
    p = config.PROFILE_DIR / "user-notes.txt"
    text = (text or "").strip()
    if text:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text[:4000] + "\n", encoding="utf-8")
    elif p.exists():
        p.unlink()


def budget_left(st: dict) -> float:
    return max(0.0, float(st.get("budget_usd") or 0) - float(st.get("cost_usd") or 0))


def claude_step(st: dict, sid: str, prompt: str, tools: tuple, label: str, cap: float, max_turns: int, timeout: int = 1800) -> claude_runner.Result:
    left = budget_left(st)
    if left < 0.25:
        raise Fail("The usage cap for this run is used up", "Raise the usage cap on the start page and press Start again: finished steps are kept.")
    real_profile = Path(os.path.realpath(config.PROFILE_DIR))                          # the long form: Windows 8.3 short names (PROGRA~1) are refused by Claude Code's permission layer
    outside = [str(real_profile)] if not str(real_profile).startswith(str(Path(os.path.realpath(ROOT)))) else []
    if outside:
        prompt += ("\n\nNote: the profile folder is at " + str(real_profile) + " (outside the toolkit folder). Wherever these instructions say `profile/`, they mean that folder; "
                   "use that absolute path for every file you read or write there.\n")
    r = claude_runner.run(prompt, label=label, tools=tools[0], allowed=tools[1], max_turns=max_turns, budget_usd=min(cap, left), timeout_s=timeout, add_dirs=outside)
    st["cost_usd"] = round(st.get("cost_usd", 0) + r.cost_usd, 4)               # list-price value of the usage; on a subscription it is not a charge
    stage(st, sid)["cost_usd"] = round(stage(st, sid).get("cost_usd", 0) + r.cost_usd, 4)
    save_state(st)
    if r.error.startswith("PLAN LIMIT"):
        raise Fail("Your Claude plan's usage limit is reached", "Wait until your plan's limit resets (Claude shows when), then press Start again: finished steps and finished reviews are kept.")
    return r


# ----------------------------------------------------------------------------- stages

def s_understand(st: dict, opts: dict) -> None:
    import onboard
    pd = config.PROFILE_DIR
    if not (pd / "cv-source.txt").exists():
        raise Fail("No CV yet", "Upload your CV first.")
    have = (pd / "profile.json").exists() and (pd / "domain.json").exists() and not understood_problem()
    if have and st.get("understood_sha") == cv_sha() and not opts.get("force"):
        errors, _ = onboard.validate()
        if not errors:
            finish(st, "understand", "skipped", "already understood; the CV has not changed")
            return
    begin(st, "understand", "Claude is reading your CV (about 2 to 5 minutes)")
    status = claude_runner.status()
    if not status.get("installed") or not status.get("logged_in") or (not status.get("subscription") and os.environ.get("JOBKIT_CLAUDE_BIN") is None):
        raise Fail(status.get("message", "Claude Code is not ready"), "Install Claude Code, run `claude` once in a terminal and sign in with your Claude account, then press Start again.")
    prompt = (PROMPTS / "understand.md").read_text(encoding="utf-8")
    r = claude_step(st, "understand", prompt, TOOLS_UNDERSTAND, "understand", cap=3.0, max_turns=80)
    problem = understood_problem()
    if problem or not r.ok:
        said = " ".join((r.error or r.text or "").split())[:300]
        denied = f" Claude Code was refused {len(r.denials)} action(s)." if r.denials else ""
        raise Fail(f"Claude did not finish writing your profile ({problem or 'it reported an error'}).{denied} It said: {said}",
                   "Press Start again. If it keeps failing, add a few lines about what you want in the box on the start page.")
    cost = 0.0
    finish(st, "understand", "done", (r.text.strip().splitlines() or [""])[-1][:300] or "profile written", cost)
    st["understood_sha"] = cv_sha()
    save_state(st)


def understood_problem() -> str:
    """What is missing after the understand step, or an empty string. The empty templates that `onboard.py init` writes must not pass for a profile."""
    pd = config.PROFILE_DIR
    prof, dom, ass = _json(pd / "profile.json", {}), _json(pd / "domain.json", {}), _json(pd / "assumptions.json", None)
    if not prof or not dom:
        return "profile.json or domain.json is missing"
    if not isinstance(ass, list) or not ass:
        return "assumptions.json was not written"
    labels = {str(s.get("label", "")).strip().lower() for s in dom.get("subfields", [])}
    if not labels or labels <= {"example core field", ""}:
        return "the field description is still the empty template"
    if len(dom.get("cv_evidence") or []) < 3:
        return "the CV evidence is empty"
    return ""


def s_configure(st: dict, opts: dict) -> None:
    import onboard
    begin(st, "configure", "validating")
    for attempt in range(3):
        check_stop()
        errors, warns = onboard.validate()
        if not errors:
            config.reload()
            finish(st, "configure", "done", f"valid ({len(warns)} warnings)")
            return
        if attempt == 2:
            break
        stage(st, "configure")["message"] = f"repairing {len(errors)} problems with Claude (attempt {attempt + 1} of 2)"
        save_state(st)
        prompt = (PROMPTS / "repair.md").read_text(encoding="utf-8").replace("{errors}", "\n".join(f"- {e}" for e in errors[:25]))
        r = claude_step(st, "configure", prompt, TOOLS_UNDERSTAND, "repair", cap=1.0, max_turns=30)
        if not r.ok:
            break
    raise Fail("The configuration written for you has errors Claude could not fix: " + "; ".join(errors[:3]), "Press Start again, or open the profile folder and fix the file named above.")


def s_search(st: dict, opts: dict) -> None:
    begin(st, "search", "choosing employers by industry and writing the board queries")
    rc, out = script(["scripts/onboard.py", "build-sources"], 300)
    m = re.search(r"added (\d+) employers", out)
    msg = f"{m.group(1)} employer feeds added" if m else (out.strip().splitlines() or ["no employer directory match"])[-1][:200]
    if (ROOT / "scripts" / "board_sweep.py").exists():
        rc2, out2 = script(["scripts/board_sweep.py", "build"], 120)
        q = re.search(r"(\d+) queries written", out2)
        msg += f"; {q.group(1)} board queries" if q else ""
    finish(st, "search", "done" if rc == 0 else "skipped", msg)


def s_collect(st: dict, opts: dict) -> None:
    begin(st, "collect", "reading employer feeds, universities and boards (several minutes)")
    notes = []
    for name, args in (("employers", ["scripts/job_watch.py"]), ("institutions", ["scripts/uni_watch.py"])):
        check_stop()
        stage(st, "collect")["message"] = f"reading {name}"
        save_state(st)
        rc, out = script(args, 1800)
        last = [l for l in out.strip().splitlines() if l.strip()][-1:] or [""]
        notes.append(f"{name}: " + ("ok" if rc == 0 else f"problem ({last[0][:80]})"))
    if (ROOT / "scripts" / "board_sweep.py").exists():
        check_stop()
        stage(st, "collect")["message"] = "searching the job boards"
        save_state(st)
        rc, out = script(["scripts/board_sweep.py", "run", "--no-intake"], 3 * 3600)
        tail = [l for l in out.strip().splitlines() if "hits," in l]
        notes.append("boards: " + (", ".join(tail) if rc == 0 and tail else "ok" if rc == 0 else "skipped (needs Playwright, see `onboard.py doctor`)"))
    finish(st, "collect", "done", "; ".join(notes))


def s_read(st: dict, opts: dict) -> None:
    begin(st, "read", "fetching every posting in full and scoring it (this is the long step)")
    rc, out = script(["scripts/intake.py", "run"], 4 * 3600)
    if rc != 0:
        raise Fail("Reading the postings stopped with an error: " + (out.strip().splitlines() or [""])[-1][:200], "Press Start again: postings already read are kept.")
    m = re.search(r'"jd_fetched":\s*(\d+)', out)
    s2 = re.search(r'"stubs_created":\s*(\d+)', out)
    finish(st, "read", "done", f"{m.group(1) if m else '0'} postings read in full, {s2.group(1) if s2 else '0'} new")
    st["counts"] = counts()
    save_state(st)


def counts() -> dict:
    import db
    db.init_db()                                           # a fresh install has no tracker yet; this is idempotent
    jobs = [j for j in db.list_jobs() if j["status"] == "open"]
    th = [t for t in db.list_thesis() if t.get("status") == "lead"]
    best = [j for j in jobs + th if j.get("verdict") in BEST]
    return {"postings": len(jobs) + len(th), "read_in_full": sum(1 for j in jobs + th if j.get("analysis_level") in ("auto", "reviewed")),
            "best_fits": len(best), "confirmed": sum(1 for j in best if j.get("analysis_level") == "reviewed")}


def review_queue() -> list[str]:
    import db
    db.init_db()                                           # a fresh install has no tracker yet; this is idempotent
    D = __import__("definitions")
    rows = [j for j in db.list_jobs() if j["status"] == "open" and j.get("verdict") in BEST and j.get("analysis_level") in ("auto", "legacy")]
    rows += [t for t in db.list_thesis() if t.get("status") == "lead" and t.get("verdict") in BEST and t.get("analysis_level") in ("auto", "legacy")]
    rows.sort(key=lambda r: (D.VERDICT_META.get(r["verdict"], {"rank": 9})["rank"], -(r.get("score") or 0)))
    return [r["id"] for r in rows]


def s_review(st: dict, opts: dict) -> None:
    limit = int(opts.get("review_limit") if opts.get("review_limit") is not None else 30)
    queue = review_queue()[:limit]
    if not queue:
        finish(st, "review", "skipped", "no best fits waiting for a second read")
        return
    begin(st, "review", f"Claude is reading {len(queue)} best fits in full")
    done = 0
    for i in range(0, len(queue), 5):
        check_stop()
        chunk = queue[i:i + 5]
        stage(st, "review")["message"] = f"reading roles {i + 1} to {i + len(chunk)} of {len(queue)}"
        save_state(st)
        prompt = (PROMPTS / "review.md").read_text(encoding="utf-8").replace("{ids}", ", ".join(chunk))
        try:
            r = claude_step(st, "review", prompt, TOOLS_REVIEW, "review", cap=2.0, max_turns=60)
        except Fail as exc:
            if done:
                finish(st, "review", "done", f"{done} confirmed; stopped: {exc}")
                st["counts"] = counts()
                save_state(st)
                return
            raise
        still = set(review_queue())
        done += sum(1 for c in chunk if c not in still)
        if not r.ok:
            note(st, f"review step problem: {r.error[:120]}")
    st["counts"] = counts()
    finish(st, "review", "done", f"{done} of {len(queue)} confirmed after a full second read")


RUNNERS = {"understand": s_understand, "configure": s_configure, "search": s_search, "collect": s_collect, "read": s_read, "review": s_review}


# ----------------------------------------------------------------------------- the run

def run_all(opts: dict | None = None) -> dict:
    opts = opts or {}
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if STOP_P.exists() and not opts.get("keep_stop_flag"):
        STOP_P.unlink()                                   # a flag left over from an earlier Stop must not stop this Start
    st = load_state()
    st.update(status="running", error=None, hint=None, started=_now(), finished=None, pid=os.getpid())
    if opts.get("budget"):
        st["budget_usd"] = float(opts["budget"])
    if opts.get("force"):
        for s in st["stages"]:
            s.update(status="pending", message="")
        st["cost_usd"] = 0.0
    start_at = opts.get("from")
    order = [i for i, _ in STAGES]
    until = opts.get("until")
    for sid in order:
        s = stage(st, sid)
        if start_at and order.index(sid) < order.index(start_at):
            continue
        if until and order.index(sid) > order.index(until):
            break                                          # a partial run (for example up to "configure" to look at what Claude wrote)
        if s["status"] in ("done", "skipped") and not start_at and not opts.get("force"):
            continue
        try:
            check_stop()
            RUNNERS[sid](st, opts)
        except Stop:
            finish(st, sid, "pending", "stopped by you")
            st.update(status="stopped", finished=_now(), pid=None)
            save_state(st)
            return st
        except Fail as exc:
            finish(st, sid, "error", str(exc))
            st.update(status="error", error=str(exc), hint=exc.hint, finished=_now(), pid=None)
            save_state(st)
            return st
        except Exception as exc:  # noqa: BLE001
            finish(st, sid, "error", f"{type(exc).__name__}: {exc}"[:300])
            st.update(status="error", error=f"{type(exc).__name__}: {exc}"[:300], hint="Press Start again. The log is in logs/.", finished=_now(), pid=None)
            save_state(st)
            return st
    st["counts"] = counts()
    st.update(status="done", finished=_now(), pid=None, needs_rescore=False)
    save_state(st)
    return st


def refresh() -> dict:
    """Re-score every posting after the person corrected an assumption. No Claude, no network: the configuration hash changed, so every row is analysed again
    and every score that moves is flagged (rules/pipeline.md)."""
    config.reload()
    rc, out = script(["scripts/analyze.py", "run", "--levels", "legacy,auto,reviewed"], 3600)
    st = load_state()
    st["needs_rescore"] = rc != 0
    st["counts"] = counts()
    note(st, "re-scored after your changes" if rc == 0 else "re-scoring failed: " + out.strip()[-120:])
    save_state(st, ("needs_rescore", "counts", "log"))
    return st


# ----------------------------------------------------------------------------- what the person sees

def understood() -> dict:
    """The page's 'what I understood' card: the field, the sub-fields, the assumptions to correct."""
    pd = config.PROFILE_DIR
    prof = _json(pd / "profile.json", {})
    dom = _json(pd / "domain.json", {})
    ass = _json(pd / "assumptions.json", [])
    subs = [{"label": s.get("label"), "role": s.get("role")} for s in dom.get("subfields", [])]
    evid = dom.get("cv_evidence", [])
    return {"configured": bool(prof and dom), "career_stage": prof.get("career_stage"), "regions": prof.get("regions"), "levels_sought": prof.get("levels_sought"),
            "languages": prof.get("languages"), "work_authorization": prof.get("work_authorization"), "cities": prof.get("cities"), "remote_ok": prof.get("remote_ok"),
            "document_language": prof.get("document_language"), "goal": prof.get("goal"), "subfields": subs,
            "categories": [c.get("label") for c in dom.get("categories", [])],
            "evidence": {"covered": sum(1 for e in evid if e.get("status") == "covered"), "partial": sum(1 for e in evid if e.get("status") == "partial"), "gap": sum(1 for e in evid if e.get("status") == "gap")},
            "search_terms": (dom.get("search_terms") or [])[:14], "priority_employers": (dom.get("priority_employers") or [])[:12], "assumptions": ass}


def _json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


EDITABLE = {"career_stage": str, "levels_sought": list, "regions": list, "cities": list, "remote_ok": bool, "languages": list, "document_language": str,
            "accept_unrelated_income": bool, "work_authorization": dict, "goal": str, "primary_countries": list, "scope_countries": list}


def apply_edits(edits: dict) -> dict:
    """Write the person's corrections into profile.json (a whitelist of keys), validate, and mark the assumptions as theirs. Returns the validation result."""
    import onboard
    p = config.PROFILE_DIR / "profile.json"
    prof = _json(p, None)
    if prof is None:
        raise Fail("There is no profile yet", "Run the start first.")
    before = json.dumps(prof, sort_keys=True)
    for k, v in edits.items():
        if k not in EDITABLE or not isinstance(v, EDITABLE[k]):
            raise Fail(f"'{k}' cannot be changed here")
        prof[k] = v
    p.write_text(json.dumps(prof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    errors, warns = onboard.validate()
    if errors:
        p.write_text(before and json.dumps(json.loads(before), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        raise Fail("That change is not valid: " + "; ".join(errors[:3]))
    ap = config.PROFILE_DIR / "assumptions.json"
    ass = _json(ap, [])
    for a in ass:
        top = str(a.get("key", "")).split(".")[0]
        if top in edits:
            a.update(value=edits[top] if "." not in a["key"] else prof.get(top), source="you", confidence="high")
    ap.write_text(json.dumps(ass, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    patch_state(needs_rescore=True)
    config.reload()
    return {"ok": True, "warnings": warns}


LANG_NAMES = {"de": "German", "en": "English", "fr": "French", "es": "Spanish", "it": "Italian", "nl": "Dutch", "pt": "Portuguese", "sv": "Swedish", "da": "Danish",
              "pl": "Polish", "cs": "Czech", "tr": "Turkish", "ar": "Arabic", "ja": "Japanese", "zh": "Chinese", "ko": "Korean", "ru": "Russian", "hi": "Hindi"}
KIND_WORDS = {"thesis": "thesis", "student_assistant": "student assistant job", "working_student": "working-student job", "internship": "internship", "trainee": "trainee programme",
              "entry": "entry-level role", "mid": "mid-level role", "senior": "senior role"}


def plain_reason(j: dict) -> str:
    """What the script saw, in words a person reads: the field, the kind of role, the language asked, what counted in its favour. The script's own line quotes the posting
    in fragments; this one does not. A role a session has re-read shows that session's reasoning instead (see results())."""
    cfg = config.get()
    bd = j.get("score_breakdown") or {}
    parts = []
    cat = next((c.get("label") for c in cfg.domain.get("categories", []) if c.get("id") == j.get("category")), None)
    sub = (cfg.subfield_labels or {}).get(j.get("subfield")) if hasattr(cfg, "subfield_labels") else None
    if cat or sub:
        parts.append("Field: " + ", ".join(x for x in (cat, sub) if x) + ".")
    kind = KIND_WORDS.get(bd.get("kind") or j.get("kind") or "")
    if kind:
        parts.append(("An " if kind[0] in "aeiou" else "A ") + kind + ".")
    langs = bd.get("languages") or {}
    if langs:
        parts.append("Language asked: " + ", ".join(f"{LANG_NAMES.get(k, k)} {str(v).replace('_', ' ')}" for k, v in langs.items()) + ".")
    meta = re.compile(r"found|posting date|posted|recen|fresh", re.I)                     # when a posting was seen says nothing about whether it fits
    good = [re.sub(r"\s*\([+-]\d+\)", "", k) for k, v in (bd.get("components") or {}).items() if isinstance(v, (int, float)) and v > 0 and not meta.search(k)]
    if good:
        parts.append("In its favour: " + ", ".join(good) + ".")
    route = ((bd.get("route") or {}).get("work_route") or "")
    if route and "no work-authorization limit" not in route and route not in ("unrestricted", "unknown"):
        parts.append("Work route: " + route.replace("_", " ") + ".")
    if j.get("blocked_reason"):
        parts.append("Wall: " + str(j["blocked_reason"])[:160])
    return " ".join(parts)


def results(limit: int = 600) -> list[dict]:
    """The best fits, in the order a person should look at them."""
    import db
    db.init_db()                                           # a fresh install has no tracker yet; this is idempotent
    D = __import__("definitions")
    out = []
    for kind, rows in (("job", [j for j in db.list_jobs() if j["status"] == "open"]), ("thesis", [t for t in db.list_thesis() if t.get("status") == "lead"])):
        for j in rows:
            if j.get("verdict") not in BEST:
                continue
            cv = j.get("cv_match") or {}
            out.append({"id": j["id"], "kind": kind, "title": j.get("title"), "employer": j.get("employer") or j.get("institution"),
                        "place": ", ".join(x for x in (j.get("location"), j.get("country")) if x), "verdict": j["verdict"], "score": j.get("score"),
                        "confirmed": j.get("analysis_level") == "reviewed",
                        "why": ((j.get("verdict_reason") or "").replace("REVIEWED: ", "").split(" | analyzer:")[0][:600] if j.get("analysis_level") == "reviewed" else plain_reason(j)),
                        "covered": [x.get("term") for x in (cv.get("covered") or [])][:8], "gaps": [x.get("term") for x in (cv.get("gaps") or [])][:6],
                        "deadline": j.get("deadline"), "url": j.get("url") or j.get("posting_url"), "verified": bool(j.get("url_verified")),
                        "approval": j.get("approval"), "posted": (j.get("posted_at") or j.get("date_found") or "")[:10], "found_via": j.get("source") or j.get("source_type")})
    out.sort(key=lambda r: (D.VERDICT_META.get(r["verdict"], {"rank": 9})["rank"], -(r["score"] or 0)))
    return out[:limit]


# ----------------------------------------------------------------------------- tailoring one approved role

def tailor(job_id: str) -> dict:
    import db
    db.init_db()                                           # a fresh install has no tracker yet; this is idempotent
    row = db.get_job(job_id)

    def fail(msg: str) -> dict:
        entry = {"status": "error", "message": msg}
        set_tailor(job_id, entry)
        return entry
    if row is None:
        return fail("no such role")
    if row.get("verdict") in ("PASS", "BLOCKED", "EXPIRED"):
        return fail(f"the analysis says this role is not a fit ({row['verdict']}): nothing was built")
    if not (config.PROFILE_DIR / "master-profile.md").exists():
        return fail("there is no master profile yet; run the start first")
    db.update_job(job_id, {"approval": "requested", "approved_at": _now()})
    set_tailor(job_id, {"status": "running", "message": "Claude is writing your CV and letter (3 to 8 minutes)", "started": _now(), "pid": os.getpid()})
    prompt = (PROMPTS / "tailor.md").read_text(encoding="utf-8").replace("{id}", job_id)
    t_start = time.time() - 2
    r = claude_runner.run(prompt, label="tailor", tools=TOOLS_TAILOR[0], allowed=TOOLS_TAILOR[1], max_turns=80, budget_usd=3.0, timeout_s=2400)
    if r.error.startswith("PLAN LIMIT"):
        return fail("Your Claude plan's usage limit is reached. Try again when it resets; nothing was built.")
    # the package folder is the one whose cv.md was written during this run: a new folder, or one rebuilt over an earlier attempt on the same day
    made = [p for p in (ROOT / "applications").glob("*") if p.is_dir() and (p / "cv.md").exists() and (p / "cv.md").stat().st_mtime >= t_start] if (ROOT / "applications").exists() else []
    folder = max(made, key=lambda p: (p / "cv.md").stat().st_mtime) if made else None
    if r.ok and folder and (folder / "cv.md").exists():
        db.update_job(job_id, {"approval": "prepared"})
        entry = {"status": "done", "message": (r.text.strip().splitlines() or [""])[-1][:300], "folder": str(folder.relative_to(ROOT)),
                 "files": sorted(f.name for f in folder.iterdir() if f.is_file()), "cost_usd": r.cost_usd}
    else:
        entry = {"status": "error", "message": (r.error or r.text or "nothing was built")[:300], "cost_usd": r.cost_usd}
    set_tailor(job_id, entry)
    return entry


# ----------------------------------------------------------------------------- command line

def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "tailor", "refresh", "status"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--review-limit", type=int, default=30)
    ap.add_argument("--budget", type=float)
    ap.add_argument("--from", dest="from_stage", choices=[i for i, _ in STAGES])
    ap.add_argument("--until", dest="until_stage", choices=[i for i, _ in STAGES], help="stop after this stage")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.cmd == "status":
        print(json.dumps(load_state(), ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "refresh":
        print(json.dumps(refresh()["counts"]))
        return 0
    if a.cmd == "tailor":
        if not a.arg:
            print("give a job id", file=sys.stderr)
            return 2
        print(json.dumps(tailor(a.arg), ensure_ascii=False))
        return 0
    st = run_all({"review_limit": a.review_limit, "budget": a.budget, "from": a.from_stage, "until": a.until_stage, "force": a.force})
    print(json.dumps({"status": st["status"], "error": st["error"], "counts": st.get("counts"), "cost_usd": st["cost_usd"]}, ensure_ascii=False))
    return 0 if st["status"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main())

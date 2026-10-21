#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/remote_sync.py — the PC side of the phone inbox (rules/remote.md).

The phone page lives on Cloudflare (remote/, a Worker with KV). It cannot reach this PC; the PC reaches it:

  push   builds a slim snapshot (best fits to decide, packages ready to send, mail that asks you to act, thesis leads) and uploads it.
         CV material, your contact data, the tracker's other columns and your existing notes never leave the PC (the posting's own public text does, for reading on the phone).
  pull   downloads the decisions made on the phone (approve, recheck, not for me, I applied, a note) and applies each one through scripts/db.py,
         exactly as the dashboard would (the my_notes guard and the status rules still hold), then tells the phone what happened.
  sync   pull, then push (so the phone sees the result). Called at every log-on / hourly by the pipeline task, by the dashboard while it runs,
         and at the start of `pipeline.py run`.

    python scripts/remote_sync.py init [--url https://...]    one-time: create the secrets and the phone passphrase (shown once)
    python scripts/remote_sync.py sync | push | pull | status
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402
import definitions as D  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "remote.json"
STATE = ROOT / "data" / "remote-state.json"
LOG = ROOT / "data" / "remote-log.jsonl"
DEV_VARS = ROOT / "remote" / ".dev.vars"
PBKDF2_ITER = 100_000
WORDS = ("amber anchor apple arrow aspen basil beacon birch bridge cactus canyon cedar cherry cliff cloud cobalt comet coral cove crane daisy delta dune eagle ember fable falcon fern "
         "fjord flint forest fox garnet glacier harbor hazel heron hill iris island ivory jade juniper kite lagoon lark lemon lilac lotus maple meadow mint moss nectar oak olive "
         "orbit otter pearl pine plum pond quartz quill raven reef river robin sage sierra silver sparrow spruce stone summit sun tiger timber topaz tulip valley velvet violet "
         "willow wren yarrow zephyr").split()


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def load_config() -> dict:
    if not CONFIG.exists():
        raise FileNotFoundError("config/remote.json missing: run `python scripts/remote_sync.py init`")
    return json.loads(CONFIG.read_text(encoding="utf-8-sig"))


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


# ----------------------------------------------------------------------------- init (secrets)

def make_secrets(passphrase: str | None = None) -> dict:
    passphrase = passphrase or "-".join(secrets.choice(WORDS) for _ in range(4)) + "-" + str(secrets.randbelow(9000) + 1000)
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", passphrase.encode(), salt, PBKDF2_ITER, 32)
    return {"passphrase": passphrase, "PASS_HASH": f"{PBKDF2_ITER}${b64u(salt)}${b64u(h)}", "PC_KEY": secrets.token_urlsafe(32), "COOKIE_KEY": secrets.token_urlsafe(32)}


def init(url: str | None, reset_passphrase: bool) -> dict:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig")) if CONFIG.exists() else {}
    sec = make_secrets()
    if cfg.get("pc_key") and cfg.get("cookie_key") and not reset_passphrase:
        raise SystemExit("config/remote.json already holds the secrets; use --reset-passphrase to issue a new passphrase (the PC key and cookie key are kept)")
    cfg.update({"url": url or cfg.get("url", ""), "pc_key": cfg.get("pc_key") or sec["PC_KEY"], "cookie_key": cfg.get("cookie_key") or sec["COOKIE_KEY"], "pass_hash": sec["PASS_HASH"]})
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    DEV_VARS.write_text(f"PC_KEY={cfg['pc_key']}\nCOOKIE_KEY={cfg['cookie_key']}\nPASS_HASH={cfg['pass_hash']}\n", encoding="utf-8")
    return {"passphrase": sec["passphrase"], "url": cfg["url"]}


# ----------------------------------------------------------------------------- push

def clip(s, n: int) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def why_of(r: dict) -> str:
    txt = (r.get("verdict_reason") or "").replace("REVIEWED: ", "").split(" | analyzer:")[0].strip()
    if not txt or "read in full when the lead was filed" in txt:
        txt = D.CATEGORY_LABELS.get(r.get("category") or "", "") or ""
    return clip(txt, 280)


def shape(r: dict, kind: str) -> dict:
    url = r.get("url") if kind == "job" else r.get("posting_url")
    return {"id": r["id"], "kind": kind, "title": clip(r.get("title"), 110), "employer": clip(r.get("employer") or r.get("institution"), 60), "location": clip(r.get("location"), 40),
            "verdict": r.get("verdict"), "score": r.get("score") if r.get("score") is not None else r.get("fit_score"), "why": why_of(r), "deadline": (r.get("deadline") or "")[:10] or None,
            "status": r.get("status"), "approval": r.get("approval"), "channel": clip(r.get("apply_channel"), 24) or None, "etype": D.KIND_LABELS.get(r.get("kind") or "", "") if hasattr(D, "KIND_LABELS") else "",
            "url": url or None, "verified": bool(r.get("url_verified"))}


def build_snapshot() -> dict:
    jobs = [j for j in db.list_jobs() if j["status"] == "open"]
    items = []
    for j in jobs:
        ready = j["approval"] in ("prepared", "requested")
        if (j.get("verdict") in D.BEST_FIT_VERDICTS and j["approval"] != "blocked") or ready:
            items.append(shape(j, "job"))
    for t in db.list_thesis():
        if t.get("status") == "lead" and t.get("verdict") in D.BEST_FIT_VERDICTS:
            items.append(shape(t, "thesis"))
    mail = {"act_now": [], "replies": []}
    qp = ROOT / "data" / "mail" / "queue.json"
    if qp.exists():
        q = json.loads(qp.read_text(encoding="utf-8"))
        mail["act_now"] = [{"kind": m["kind"], "employer": clip(m.get("employer") or m.get("from"), 40), "role": clip(m.get("role") or m.get("subject"), 90), "date": m["date"]} for m in q.get("act_now", [])][:12]
    since = (date.today() - timedelta(days=7)).isoformat()
    for e in db.list_mail_events(since=since):
        if e["kind"] in ("rejection", "interview", "offer") and e["state"] in ("applied", "already", "acted"):
            row = (db.get_job(e["job_id"]) if e.get("job_id") else None) or {}
            mail["replies"].append({"kind": e["kind"], "employer": clip(row.get("employer") or e.get("employer_hint"), 40), "role": clip(row.get("title") or e["subject"], 90), "date": e["mail_date"]})
    mail["replies"] = mail["replies"][:15]
    return {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "items": items, "mail": mail,
            "stats": {"open": len(jobs), "best_fits": sum(1 for i in items if i["verdict"] in D.BEST_FIT_VERDICTS)}}


DETAIL_TEXT_MAX = 9000


def _label(table: dict, key) -> str:
    return table.get(key or "", "") or ""


def build_details(items: list[dict]) -> dict:
    """What the phone's 'Details' sheet shows for each role in the snapshot: key facts, why, the comparison with the CV, how it scored, and the posting's own text
    (the public job description, capped). Never my_notes, never CV or cover-letter material, never contact data."""
    import analyze
    out = {}
    for it in items:
        kind = it["kind"]
        row = (db.get_job(it["id"]) if kind == "job" else db.get_thesis(it["id"])) or {}
        facts = []

        def add(k, v):
            if v not in (None, "", "None"):
                facts.append([k, clip(v, 160)])
        add("Type", D.KIND_LABELS.get(row.get("kind") or ((row.get("score_breakdown") or {}).get("kind")) or "", ""))
        add("Employer", it.get("employer"))
        add("Place", ", ".join(x for x in (row.get("location"), row.get("country")) if x))
        add("Deadline", it.get("deadline"))
        add("Start", row.get("start_window"))
        add("Duration", row.get("duration"))
        add("Language required", row.get("lang_bar") or row.get("language_bar"))
        add("Field", _label(D.CATEGORY_LABELS, row.get("category")) + (" / " + _label(D.SUBFIELD_LABELS, row.get("subfield")) if row.get("subfield") else ""))
        add("Posted", (row.get("posted_at") or row.get("date_found") or "")[:10])
        add("Apply via", row.get("apply_channel"))
        if kind == "thesis":
            add("Supervisor", row.get("pi_name"))
            add("Group", clip(row.get("group_summary"), 300))
        cv = row.get("cv_match") or {}
        br = row.get("score_breakdown") or {}
        text = analyze.read_jd(row) if row else ""
        if kind == "thesis":
            extra = "\n\n".join(x for x in (row.get("posting_text"), ("Requirements: " + row["requirements"]) if row.get("requirements") else "") if x)
            text = text or extra
        reason = (row.get("verdict_reason") or "").replace("REVIEWED: ", "")
        out[it["id"]] = {
            "facts": facts, "why": clip(reason.split(" | analyzer:")[0], 900),
            "cv": {k: [{"t": clip(x.get("term", "").split(" (")[0], 40), "a": x.get("asked", "")} for x in (cv.get(k) or [])][:14] for k in ("covered", "partial", "gaps")},
            "score": {"parts": {k: v for k, v in ((br.get("components") or {}).items())}, "route": (br.get("route") or {}).get("work_route"), "adj": (br.get("route") or {}).get("adjustment"), "total": it.get("score")},
            "level": row.get("analysis_level"), "text": (text or "")[:DETAIL_TEXT_MAX] + ("…" if len(text or "") > DETAIL_TEXT_MAX else ""), "verified": bool(row.get("url_verified"))}
    return out


def _http(cfg: dict, method: str, path: str, body: dict | None = None):
    import requests
    r = requests.request(method, cfg["url"].rstrip("/") + path, headers={"Authorization": "Bearer " + cfg["pc_key"], "Content-Type": "application/json"},
                         data=json.dumps(body) if body is not None else None, timeout=40)
    r.raise_for_status()
    return r.json()


HEARTBEAT_SNAPSHOT_MIN = 60       # an unchanged snapshot is still re-sent this often so the phone's "PC synced" time stays honest
HEARTBEAT_DETAILS_H = 24          # unchanged details are re-sent this often


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _age_min(iso: str | None) -> float:
    try:
        return (datetime.now() - datetime.fromisoformat(iso)).total_seconds() / 60
    except (TypeError, ValueError):
        return 1e9


def push(cfg: dict | None = None, force: bool = False) -> dict:
    """Upload only what changed. Each upload is a Cloudflare KV write and the free plan allows 1,000 a day for the whole account (shared with other
    projects), so an unchanged snapshot is skipped (hourly heartbeat) and unchanged details are skipped (daily)."""
    cfg = cfg or load_config()
    st = load_state()
    snap = build_snapshot()
    snap_hash = _digest({k: v for k, v in snap.items() if k != "generated"})
    out = {"pushed": 0, "details": 0, "skipped": []}
    if force or snap_hash != st.get("snap_hash") or _age_min(st.get("snap_at")) >= HEARTBEAT_SNAPSHOT_MIN:
        res = _http(cfg, "POST", "/api/pc/snapshot", snap)
        out["pushed"] = res.get("items", len(snap["items"]))
        st.update(snap_hash=snap_hash, snap_at=datetime.now().isoformat(timespec="seconds"))
    else:
        out["pushed"] = len(snap["items"])
        out["skipped"].append("snapshot unchanged")
    det = build_details(snap["items"])
    det_hash = _digest(det)
    if force or det_hash != st.get("det_hash") or _age_min(st.get("det_at")) >= HEARTBEAT_DETAILS_H * 60:
        _http(cfg, "POST", "/api/pc/details", {"generated": snap["generated"], "details": det})
        st.update(det_hash=det_hash, det_at=datetime.now().isoformat(timespec="seconds"))
    else:
        out["skipped"].append("details unchanged")
    out["details"] = len(det)
    save_state({**load_state(), **{k: st[k] for k in ("snap_hash", "snap_at", "det_hash", "det_at") if k in st}})
    return out


# ----------------------------------------------------------------------------- pull and apply

def _append_note(row: dict, text: str, source_kind: str) -> dict:
    stamp = f"[phone {date.today().isoformat()}] {text.strip()}"
    cur = (row.get("my_notes") or "").rstrip()
    return {"my_notes": (cur + "\n" if cur else "") + stamp}


def apply_event(ev: dict) -> tuple[bool, str]:
    """Apply one phone decision through db.py. (ok, message). Never raises for a stale or missing row: that is a result the phone shows."""
    kind, item, action = ev.get("kind", "job"), ev.get("item"), ev.get("action")
    today = date.today().isoformat()
    note = (ev.get("note") or "").strip()
    try:
        if kind == "thesis":
            row = db.get_thesis(item)
            if row is None:
                return False, "no such thesis row on the PC"
            if action == "skip":
                if row["status"] in ("closed", "declined", "accepted"):
                    return True, f"already {row['status']}"
                db.update_thesis(item, {"status": "closed"})
                if note:
                    db.update_thesis(item, _append_note(row, note, "thesis"), source="owner")
                return True, "closed (not for me)"
            if action == "note" and note:
                db.update_thesis(item, _append_note(row, note, "thesis"), source="owner")
                return True, "note saved"
            return False, "action not supported for a thesis lead"
        row = db.get_job(item)
        if row is None:
            return False, "no such row on the PC"
        st, ap = row["status"], row["approval"]
        changes: dict = {}
        msg = ""
        if action == "approve":
            if st != "open":
                return False, f"already {st}"
            if ap in ("requested", "prepared"):
                return True, f"already {ap}"
            changes, msg = {"approval": "requested", "approved_at": today}, "approved: queued for the next build"
        elif action == "recheck":
            if st != "open":
                return False, f"already {st}"
            changes, msg = {"approval": "recheck", "recheck_at": today}, "queued for a recheck"
        elif action == "skip":
            if st in ("applied", "interview", "rejected"):
                return False, f"already {st}"
            changes, msg = {"status": "skip"}, "marked not for me"
        elif action == "applied":
            if st in ("applied", "interview"):
                return True, f"already {st}"
            changes, msg = {"status": "applied", "applied_at": ev.get("date") or today}, "marked applied"
        elif action == "reopen":
            changes, msg = {"status": "open", "approval": "none", "applied_at": None, "closed_at": None}, "reopened"
        elif action == "note":
            if not note:
                return False, "empty note"
            db.update_job(item, _append_note(row, note, "job"), source="owner")
            return True, "note saved"
        else:
            return False, "unknown action"
        db.update_job(item, changes)
        if note:
            db.update_job(item, _append_note(row, note, "job"), source="owner")
        return True, msg
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:120]}"


def pull(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    db.init_db()
    evs = sorted(_http(cfg, "GET", "/api/pc/events").get("events", []), key=lambda e: e.get("created", ""))
    results, applied = [], 0
    LOG.parent.mkdir(parents=True, exist_ok=True)
    for ev in evs:
        ok, msg = apply_event(ev)
        applied += ok
        results.append({"id": ev["id"], "ok": ok, "msg": msg})
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "event": ev, "ok": ok, "msg": msg}, ensure_ascii=False) + "\n")
    if results:
        _http(cfg, "POST", "/api/pc/ack", {"results": results})
    return {"events": len(evs), "applied": applied, "failed": len(evs) - applied, "details": [(r["ok"], r["msg"]) for r in results][:20]}


# ----------------------------------------------------------------------------- sync

def sync() -> dict:
    """Pull the phone's decisions, then push a fresh snapshot. Never raises: a failure is recorded in data/remote-state.json (audit C34 reports it)."""
    st = load_state()
    out: dict = {}
    try:
        cfg = load_config()
        if not cfg.get("url"):
            raise RuntimeError("config/remote.json has no url yet (deploy first, then `remote_sync.py init --url ...`)")
        out["pull"] = pull(cfg)
        out["push"] = push(cfg)
        st = load_state()   # push() saved its content hashes; keep them
        st.update({"last_ok": datetime.now().isoformat(timespec="seconds"), "last_error": None, "last_pull": out["pull"], "last_push": out["push"]})
        if out["pull"]["events"]:
            st["decisions_applied_total"] = st.get("decisions_applied_total", 0) + out["pull"]["applied"]
            st["last_decisions_at"] = st["last_ok"]
    except FileNotFoundError as exc:
        out["error"] = str(exc)
        st["last_error"] = str(exc)
    except Exception as exc:  # noqa: BLE001  (network down, Cloudflare error, bad key)
        out["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        st["last_error"] = out["error"]
    st["last_attempt"] = datetime.now().isoformat(timespec="seconds")
    save_state(st)
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["init", "sync", "push", "pull", "status", "snapshot"])
    ap.add_argument("--url")
    ap.add_argument("--reset-passphrase", action="store_true")
    a = ap.parse_args()
    if a.cmd == "init":
        r = init(a.url, a.reset_passphrase)
        print("Phone passphrase (shown once, store it in your phone's password manager):\n\n    " + r["passphrase"] + "\n")
        print("Secrets written to config/remote.json and remote/.dev.vars (both gitignored).")
        return 0
    if a.cmd == "status":
        print(json.dumps(load_state(), ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "snapshot":
        snap = build_snapshot()
        det = build_details(snap["items"])
        print(json.dumps({"items": len(snap["items"]), "bytes": len(json.dumps(snap)), "details_bytes": len(json.dumps(det)), "with_text": sum(1 for d in det.values() if d["text"]),
                          "mail": {k: len(v) for k, v in snap["mail"].items()}}, indent=1))
        return 0
    res = {"sync": sync, "push": lambda: push(force=True), "pull": lambda: pull()}[a.cmd]()
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return 1 if res.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())


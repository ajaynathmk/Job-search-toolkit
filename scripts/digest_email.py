#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/digest_email.py — the daily digest email: one structured, easy-to-scan page (rules/runbook.md Step 9, rules/digest.md).

The numbers and lists come from the tracker, the mail pass and the pipeline worklist, so the digest cannot disagree with the dashboard. A Claude session may add
a short prose note per section (`notes`), never new facts. It is sent to the owner's own address only (gmail_client.send_digest_email).

Layout, top to bottom (the ten fixed sections of the runbook, grouped so the first screen answers "what do I have to do today"):
  header + status chips            what ran, in one line each
  numbers strip                    new, best fits, ready to send, mail asking you to act, rejections
  1 ACT NOW                        mail that asks you to act, deadlines within a week, packages waiting to be sent
  2 Replies since last run         rejections, invitations, confirmations (from Gmail)
  3 Ready to send                  built packages, with channel and deadline
  4 Rechecked / 5 Blocked / 6 Closed since yesterday
  7 Top picks (max 8)              best fits with verdict, score, why
  8 Also new (max 15)              compact lines
  9 Still open, not yet applied (max 8)
  10 Coverage                      what ran, what did not, the counts

    python scripts/digest_email.py preview [--date YYYY-MM-DD]   writes digests/<date>.html and .txt, prints the path
    python scripts/digest_email.py send [--force]                sends it to the owner once a day (HTML with a plain-text part); the unattended run calls this last
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402
import definitions as D  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIGESTS = ROOT / "digests"
DASH = "http://127.0.0.1:5057"

TOP_MAX, NEW_MAX, OPEN_MAX = 5, 12, 4

# colours: inline on purpose (mail clients drop <style> in places); a dark-mode block is added in the head for clients that honour it
C = {"ink": "#111827", "dim": "#4b5563", "mute": "#6b7280", "line": "#e5e7eb", "bg": "#f3f4f6", "card": "#ffffff", "accent": "#4338ca", "accent_bg": "#eef2ff",
     "ok": "#166534", "ok_bg": "#dcfce7", "warn": "#92400e", "warn_bg": "#fef3c7", "bad": "#991b1b", "bad_bg": "#fee2e2", "info": "#1e40af", "info_bg": "#dbeafe",
     "plain": "#374151", "plain_bg": "#f3f4f6"}
TONE = {"success": ("ok", "ok_bg"), "accent": ("accent", "accent_bg"), "info": ("info", "info_bg"), "plain": ("plain", "plain_bg"), "danger": ("bad", "bad_bg"), "warning": ("warn", "warn_bg")}
MAIL_BADGE = {"rejection": ("Rejected", "danger"), "interview": ("Invitation", "success"), "offer": ("Offer", "success"), "info_request": ("Asks you to act", "warning"),
              "ack": ("Received", "plain"), "sent_application": ("You sent", "plain")}


def e(x) -> str:
    return html.escape(str(x if x is not None else ""), quote=True)


def clip(s, n: int) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def badge(text: str, tone: str = "plain") -> str:
    fg, bg = TONE.get(tone, TONE["plain"])
    return (f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;letter-spacing:.2px;color:{C[fg]};background:{C[bg]};white-space:nowrap">{e(text)}</span>')


def verdict_badge(v: str | None) -> str:
    m = D.VERDICT_META.get(v or "", None)
    return badge(m["label"], m["tone"]) if m else ""


def score_chip(s) -> str:
    if s is None:
        return ""
    tone = "success" if s >= 6 else "accent" if s >= 4 else "plain"
    return badge(f"{s}/10", tone)


def link(label: str, url: str | None) -> str:
    return f'<a href="{e(url)}" style="color:{C["accent"]};text-decoration:none;font-weight:600">{e(label)}</a>' if url else ""


# ----------------------------------------------------------------------------- 1. gather

def gather(day: date | None = None) -> dict:
    day = day or date.today()
    since = (day - timedelta(days=1)).isoformat()
    d0 = day.isoformat()
    jobs = db.list_jobs()
    th = db.list_thesis()
    for t in th:
        t["employer"] = t.get("institution")
        t["_kind"] = "thesis"
    open_jobs = [j for j in jobs if j["status"] == "open"]

    def shaped(j):
        return {"id": j["id"], "title": j.get("title"), "employer": j.get("employer") or j.get("institution"), "location": j.get("location"), "country": j.get("country"),
                "score": j.get("score") if j.get("score") is not None else j.get("fit_score"), "verdict": j.get("verdict"), "reason": (j.get("verdict_reason") or ""),
                "deadline": j.get("deadline"), "level": j.get("analysis_level"), "url": j.get("url") if j.get("url_verified") else j.get("posting_url") if j.get("url_verified") else None,
                "channel": j.get("apply_channel"), "category": j.get("category"), "kind": j.get("_kind", "job"), "created": (j.get("created_at") or "")[:10], "found": (j.get("date_found") or "")[:10],
                "approval": j.get("approval"), "package": j.get("package_path"), "blocked_reason": j.get("blocked_reason"), "status": j.get("status")}

    best = D.BEST_FIT_VERDICTS
    rank = lambda r: (D.VERDICT_META.get(r["verdict"], {"rank": 9})["rank"], -(r["score"] or 0))
    pool = [shaped(j) for j in open_jobs if j.get("verdict") in best] + [shaped(t) for t in th if t.get("status") == "lead" and t.get("verdict") in best]
    new_today = sorted([r for r in pool if r["created"] >= since or r["found"] >= since], key=rank)
    top = sorted(pool, key=rank)[:TOP_MAX]
    top_ids = {r["id"] for r in top}
    also_new = [r for r in new_today if r["id"] not in top_ids][:NEW_MAX]
    still_open = [r for r in sorted(pool, key=rank) if r["id"] not in top_ids and r["created"] < since][:OPEN_MAX]
    ready_all = [shaped(j) for j in open_jobs if j["approval"] == "prepared"]
    ready = [r for r in ready_all if r["verdict"] not in ("PASS", "BLOCKED", "EXPIRED")]
    ready_not_fit = len(ready_all) - len(ready)
    rechecked = [shaped(j) for j in jobs if str(j.get("last_checked") or "")[:10] == d0 and j["approval"] == "recheck"][:5]
    blocked = [shaped(j) for j in open_jobs if j["approval"] == "blocked" and (j.get("updated_at") or "")[:10] >= since][:5]
    closed = [shaped(j) for j in jobs if j["status"] in ("rejected", "skip") and str(j.get("closed_at") or "")[:10] >= since][:8]
    due = []
    for j in open_jobs:
        dl = (j.get("deadline") or "")[:10]
        try:
            n = (date.fromisoformat(dl) - day).days
        except ValueError:
            continue
        if 0 <= n <= D.DEADLINE_SOON_DAYS and j["approval"] != "blocked" and (j.get("verdict") in D.BEST_FIT_VERDICTS or j["approval"] in ("prepared", "requested")):
            r = shaped(j)
            r["days_left"] = n
            due.append(r)
    due.sort(key=lambda r: r["days_left"])

    mq = {}
    qp = ROOT / "data" / "mail" / "queue.json"
    if qp.exists():
        mq = json.loads(qp.read_text(encoding="utf-8"))
    ev_since = db.list_mail_events(since=since)
    replies = [x for x in ev_since if x["kind"] in MAIL_BADGE and x["kind"] != "sent_application" and x["state"] in ("applied", "already", "acted", "needs_read", "unmatched")]
    for x in replies:                       # name the employer and the role of the matched row, not the person who signed the mail
        row = (db.get_job(x["job_id"]) if x.get("job_id") else None) or (db.get_thesis(x["thesis_id"]) if x.get("thesis_id") else None) or {}
        x["employer_hint"] = row.get("employer") or row.get("institution") or x["employer_hint"]
        x["role"] = row.get("title")
    st = json.loads((ROOT / "data" / "pipeline-state.json").read_text(encoding="utf-8")) if (ROOT / "data" / "pipeline-state.json").exists() else {}
    ms = mq.get("state", {})
    return {"date": d0, "pool_size": len(pool), "new_today": new_today, "top": top, "also_new": also_new, "still_open": still_open, "ready": ready, "ready_not_fit": ready_not_fit, "rechecked": rechecked, "blocked": blocked,
            "closed": closed, "due": due, "act_mail": mq.get("act_now", []), "replies": replies, "mail_state": ms, "pipeline_state": st,
            "counts": {"tracked": len(jobs), "open": len(open_jobs), "thesis": len(th), "rejections_24h": sum(1 for x in ev_since if x["kind"] == "rejection"),
                       "to_read": len(mq.get("unresolved", []))}}


# ----------------------------------------------------------------------------- 2. render

def card(title: str, n, body: str, tone: str = "accent", sub: str = "") -> str:
    if not body:
        return ""
    fg, bg = TONE[tone]
    count = ""
    if n not in (None, ""):
        count = f'<span style="float:right;font-size:12px;font-weight:700;color:{C[fg]};background:{C[bg]};padding:2px 9px;border-radius:999px">{e(n)}</span>'
    subline = ""
    if sub:
        subline = '<div style="margin-top:2px;font-size:12px;color:' + C["mute"] + '">' + e(sub) + "</div>"
    return ('<tr><td style="padding:0 20px 14px 20px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:' + C["card"] + ";border:1px solid " + C["line"]
            + ";border-radius:12px;border-left:4px solid " + C[fg] + '"><tr><td style="padding:14px 16px 6px 16px"><div style="font-size:15px;font-weight:800;color:' + C["ink"] + '">' + count + e(title)
            + "</div>" + subline + '</td></tr><tr><td style="padding:0 16px 12px 16px">' + body + "</td></tr></table></td></tr>")


def row(left: str, main: str, sub: str = "", right: str = "") -> str:
    subline = ""
    if sub:
        subline = '<div style="margin-top:2px;font-size:12px;color:' + C["dim"] + ';line-height:1.4">' + sub + "</div>"
    return ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid ' + C["line"] + '"><tr>'
            '<td width="92" valign="top" style="padding:9px 10px 9px 0;font-size:12px">' + left + "</td>"
            '<td valign="top" style="padding:9px 0;font-size:14px;color:' + C["ink"] + ';line-height:1.35">' + main + subline + "</td>"
            '<td width="70" align="right" valign="top" style="padding:9px 0 9px 8px;font-size:12px;color:' + C["mute"] + '">' + right + "</td></tr></table>")


def role_main(r: dict) -> str:
    t = e(clip(r["title"], 78))
    t = f'<a href="{e(r["url"])}" style="color:{C["ink"]};text-decoration:none;font-weight:700">{t}</a>' if r.get("url") else f'<b>{t}</b>'
    return f'{t}<br><span style="color:{C["dim"]};font-size:13px">{e(clip(r["employer"], 44))}{" · " + e(clip(r["location"], 30)) if r.get("location") else ""}</span>'


def why(r: dict) -> str:
    """One short line: the reviewer's reason, or the field when the stored reason is only the boilerplate of an earlier hand review."""
    txt = (r.get("reason") or "").replace("REVIEWED: ", "").split(" | analyzer:")[0].strip()
    if not txt or "read in full when the lead was filed" in txt:
        cat = D.CATEGORY_LABELS.get(r.get("category") or "", "")
        txt = (cat + " · " if cat else "") + (r.get("kind") or "") + (f" · deadline {r['deadline']}" if r.get("deadline") else "")
    return e(clip(txt, 110))


def render(data: dict, notes: dict | None = None) -> tuple[str, str, str]:
    notes = notes or {}
    d = data
    day = date.fromisoformat(d["date"])
    ms, ps = d["mail_state"], d["pipeline_state"]
    n_act = len(d["act_mail"]) + len(d["due"])
    subject = f"Job digest {day.strftime('%a %-d %b') if sys.platform != 'win32' else day.strftime('%a ') + str(day.day) + day.strftime(' %b')} — {len(d['new_today'])} new best fits, {n_act} need action, {len(d['ready'])} ready to send"

    # --- chips: what ran
    def chip(label, ok, extra=""):
        return badge(("✓ " if ok else "! ") + label + (f" {extra}" if extra else ""), "success" if ok else "warning")
    gmail_ok = bool(ms.get("last_ok")) and not ms.get("last_error")
    rs = json.loads((ROOT / "data" / "remote-state.json").read_text(encoding="utf-8")) if (ROOT / "data" / "remote-state.json").exists() else {}
    phone_ok = bool(rs.get("last_ok")) and not rs.get("last_error")
    chips = " ".join([chip("Gmail", gmail_ok), chip("Phone", phone_ok, str((rs.get("last_pull") or {}).get("applied", "")) + " applied" if (rs.get("last_pull") or {}).get("applied") else ""), chip("Watches", ps.get("exit") == 0 and ps.get("last_success_date") == d["date"]), chip("Audit", not ps.get("audit_fail")), chip("Review queue", ps.get("review_queue", 0) == 0, str(ps.get("review_queue", 0)) if ps.get("review_queue") else "")])

    def stat(n, label, tone="plain"):
        fg, bg = TONE[tone]
        return (f'<td width="20%" align="center" style="padding:10px 4px"><div style="font-size:24px;font-weight:800;color:{C[fg]};line-height:1.1">{e(n)}</div>'
                f'<div style="font-size:11px;color:{C["mute"]};margin-top:3px;line-height:1.25">{e(label)}</div></td>')
    strip = ("<tr><td style=\"padding:0 20px 16px 20px\"><table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:" + C["card"] + ";border:1px solid " + C["line"] + ";border-radius:12px\"><tr>"
             + stat(len(d["new_today"]), "new best fits", "accent") + stat(len(d["ready"]), "ready to send", "success") + stat(n_act, "need action", "warning")
             + stat(d["counts"]["rejections_24h"], "rejections (24 h)", "danger") + stat(d["counts"]["open"], "open roles") + "</tr></table></td></tr>")

    def line(b, main, sub="", right=""):
        subline = ('<div style="font-size:12px;color:' + C["dim"] + ';margin:2px 0 0 0;line-height:1.35">' + sub + "</div>") if sub else ""
        return ('<div style="border-top:1px solid ' + C["line"] + ';padding:7px 0;font-size:13px;color:' + C["ink"] + ';line-height:1.35"><span style="float:right;margin-left:8px">' + right + "</span>"
                + b + " &nbsp;" + main + subline + '<div style="clear:both"></div></div>')

    def who(r, n=56):
        t = e(clip(r["title"], n))
        t = ('<a href="' + e(r["url"]) + '" style="color:' + C["ink"] + ';text-decoration:none;font-weight:700">' + t + "</a>") if r.get("url") else "<b>" + t + "</b>"
        return t + ' <span style="color:' + C["mute"] + '">· ' + e(clip(r["employer"], 26)) + "</span>"

    def more(total, shown):
        return ('<div style="font-size:12px;color:' + C["mute"] + ';padding-top:6px;border-top:1px solid ' + C["line"] + '">+ ' + str(total - shown) + " more on the dashboard</div>") if total > shown else ""

    # --- 1 act now
    act = ""
    for m in d["act_mail"][:4]:
        k = MAIL_BADGE.get(m["kind"], (m["kind"], "plain"))
        act += line(badge(*k), "<b>" + e(clip(m.get("employer") or m["from"], 30)) + "</b> · " + e(clip(m.get("role") or m["subject"], 52)), "", e(m["date"][5:]))
    for r in d["due"][:3]:
        act += line(badge("Deadline", "danger" if r["days_left"] <= 2 else "warning"), who(r, 48), "", e(r["deadline"][5:]) + " " + score_chip(r["score"]))
    out = [card("Act now", len(d["act_mail"]) + len(d["due"]), act + more(len(d["act_mail"]) + len(d["due"]), min(4, len(d["act_mail"])) + min(3, len(d["due"]))) +
                (f'<div style="font-size:13px;color:{C["dim"]};padding-top:8px">{e(notes["act"])}</div>' if notes.get("act") else ""), "danger")]

    # --- replies and closed, one card
    rep = ""
    for x in d["replies"][:6]:
        k = MAIL_BADGE.get(x["kind"], (x["kind"], "plain"))
        settled = x["state"] in ("applied", "already")
        rep += line(badge(*k), "<b>" + e(clip(x["employer_hint"] or x["sender"], 30)) + "</b> · " + e(clip(x.get("role") or x["subject"], 50)), "" if settled else '<span style="color:' + C["warn"] + '">to read</span>', e(x["mail_date"][5:]))
    out.append(card("Replies", len(d["replies"]), rep + more(len(d["replies"]), 6), "info"))

    # --- ready to send
    nf = d["ready_not_fit"]
    rd = "".join(line(verdict_badge(r["verdict"]) or badge("Ready", "success"), who(r, 46), "", (e(r["deadline"][5:]) + " " if r.get("deadline") else "") + score_chip(r["score"])) for r in d["ready"][:4])
    rd += more(len(d["ready"]), 4)
    if nf:
        rd += '<div style="font-size:12px;color:' + C["warn"] + ';padding-top:6px">' + str(nf) + " more packages are for roles the analysis calls not a fit: decide on the dashboard.</div>"
    out.append(card("Ready to send", len(d["ready"]), rd, "success"))

    # --- top picks
    tp = "".join(line(verdict_badge(r["verdict"]), who(r, 50), why(r), score_chip(r["score"])) for r in d["top"])
    out.append(card("Top picks", len(d["top"]), tp + more(d["pool_size"], len(d["top"])) + (f'<div style="font-size:13px;color:{C["dim"]};padding-top:8px">{e(notes["top"])}</div>' if notes.get("top") else ""), "accent"))

    # --- also new + still open, compact
    an = "".join(line(verdict_badge(r["verdict"]), who(r, 44), "", score_chip(r["score"])) for r in d["also_new"][:5]) + more(len(d["also_new"]), 5)
    out.append(card("Also new", len(d["also_new"]), an, "plain"))
    so = "".join(line(verdict_badge(r["verdict"]), who(r, 44), "", score_chip(r["score"])) for r in d["still_open"][:3])
    out.append(card("Still open", len(d["still_open"]), so, "plain"))

    # --- changes: rechecked, blocked, closed as one line each
    def names(rs):
        return e(", ".join(clip(r["employer"], 18) for r in rs[:4])) + (f" + {len(rs) - 4}" if len(rs) > 4 else "")
    ch = ""
    for label, rs in (("Rechecked", d["rechecked"]), ("Blocked", d["blocked"]), ("Closed", d["closed"])):
        if rs:
            ch += '<div style="border-top:1px solid ' + C["line"] + ';padding:6px 0;font-size:13px;color:' + C["dim"] + '"><b style="color:' + C["ink"] + '">' + label + " " + str(len(rs)) + "</b> · " + names(rs) + "</div>"
    out.append(card("Changes since yesterday", None, ch, "plain"))

    # --- coverage: one line
    cov_bits = [f'Gmail {str(ms.get("last_ok") or "never")[:16].replace("T", " ")} ({ms.get("alerts", 0)} alerts, {ms.get("filed", 0)} filed)' + (' <b style="color:' + C["bad"] + '">FAILED</b>' if ms.get("last_error") else ""),
                f'watches exit {ps.get("exit", "-")}', "audit clean" if not ps.get("audit_fail") else "audit FAIL " + ", ".join(ps["audit_fail"]),
                f'{d["counts"]["open"]} open / {d["pool_size"]} best fits', f'{d["counts"]["to_read"]} mails to read', "board and Europe sweeps need a session" + (". " + e(notes["coverage"]) if notes.get("coverage") else "")]
    out.append(card("Coverage", None, '<div style="font-size:12px;color:' + C["dim"] + ';line-height:1.6">' + " · ".join(cov_bits) + "</div>", "plain"))

    css = ("@media (prefers-color-scheme: dark){.wrap{background:#0b0f19!important}.card{background:#111827!important}}")
    body = (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark">'
            f'<title>{e(subject)}</title><style>{css}</style></head><body style="margin:0;padding:0;background:{C["bg"]};font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="wrap" style="background:{C["bg"]}"><tr><td align="center" style="padding:18px 8px">'
            f'<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%">'
            f'<tr><td style="padding:6px 20px 14px 20px"><div style="font-size:12px;font-weight:700;letter-spacing:1px;color:{C["accent"]};text-transform:uppercase">Job digest</div>'
            f'<div style="font-size:24px;font-weight:800;color:{C["ink"]};margin-top:2px">{e(day.strftime("%A, ") + str(day.day) + day.strftime(" %B %Y"))}</div>'
            f'<div style="margin-top:10px;line-height:2">{chips}</div></td></tr>{strip}'
            + "".join(out) +
            f'<tr><td align="center" style="padding:8px 20px 22px 20px;font-size:12px;color:{C["mute"]}">Open the dashboard: {link(DASH, DASH)} (on your PC) · tracker rows are the source of truth · '
            f'this mail only reads and reports, nothing was submitted.</td></tr></table></td></tr></table></body></html>')

    # --- plain-text part (same content, no styling)
    T = [f"JOB SEARCH DIGEST — {day.isoformat()}", f"{len(d['new_today'])} new best fits · {n_act} need action · {len(d['ready'])} ready to send · {d['counts']['rejections_24h']} rejections (24 h)", ""]

    def sect(t, lines):
        if lines:
            T.extend([t.upper(), *lines, ""])
    sect("1 Act now", [f"- {m['date']} {m['kind']}: {m.get('employer') or m['from']} — {clip(m['subject'], 80)}" for m in d["act_mail"][:6]] + [f"- {r['deadline']} ({r['days_left']} d): {r['title']} ({r['employer']})" for r in d["due"][:6]])
    sect("2 Replies since the last run", [f"- {x['mail_date']} {x['kind']}: {x['employer_hint'] or x['sender']} — {clip(x['subject'], 70)}" for x in d["replies"][:10]])
    sect("3 Ready to send", [f"- {r['title']} ({r['employer']}) via {r['channel'] or '?'}" for r in d["ready"][:8]])
    sect("7 Top picks", [f"- [{r['verdict']} {r['score']}] {r['title']} ({r['employer']}) — {html.unescape(why(r))}" for r in d["top"]])
    sect("8 Also new", [f"- [{r['verdict']} {r['score']}] {r['title']} ({r['employer']})" for r in d["also_new"]])
    sect("9 Still open", [f"- [{r['verdict']} {r['score']}] {r['title']} ({r['employer']})" for r in d["still_open"]])
    T.append("Dashboard: " + DASH)
    return subject, body, "\n".join(T)


def build(day: date | None = None, notes: dict | None = None) -> tuple[str, str, str]:
    return render(gather(day), notes)


STATE = ROOT / "data" / "digest-state.json"


def sent_today(day: date | None = None) -> bool:
    day = day or date.today()
    try:
        return json.loads(STATE.read_text(encoding="utf-8")).get("date") == day.isoformat()
    except (OSError, ValueError):
        return False


def send_once(force: bool = False, notes: dict | None = None) -> dict:
    """Build the digest from the current data and send it to the owner once per day (a second pipeline run the same day does not mail again unless force=True).
    Always writes digests/<date>.html and .txt. Returns {sent, id, skipped, error}."""
    day = date.today()
    subject, html_body, text = build(day, notes)
    DIGESTS.mkdir(exist_ok=True)
    (DIGESTS / f"{day.isoformat()}.html").write_text(html_body, encoding="utf-8")
    (DIGESTS / f"{day.isoformat()}.txt").write_text(text, encoding="utf-8")
    if sent_today(day) and not force:
        return {"sent": False, "skipped": "already sent today"}
    try:
        import gmail_client
        res = gmail_client.send_digest_email(subject, text, html_body=html_body)
    except Exception as exc:  # noqa: BLE001  (a dead Gmail token must not stop the run; it is reported)
        return {"sent": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    STATE.write_text(json.dumps({"date": day.isoformat(), "id": res.get("id"), "sent_at": datetime.now().isoformat(timespec="seconds"), "subject": subject}, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"sent": True, "id": res.get("id")}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["preview", "send"])
    ap.add_argument("--date")
    ap.add_argument("--force", action="store_true", help="send again even if today's digest already went out")
    a = ap.parse_args()
    day = date.fromisoformat(a.date) if a.date else date.today()
    subject, html_body, text = build(day)
    DIGESTS.mkdir(exist_ok=True)
    (DIGESTS / f"{day.isoformat()}.html").write_text(html_body, encoding="utf-8")
    (DIGESTS / f"{day.isoformat()}.txt").write_text(text, encoding="utf-8")
    if a.cmd == "preview":
        print(DIGESTS / f"{day.isoformat()}.html")
        print("subject:", subject)
        return 0
    res = send_once(force=a.force)
    print(res)
    return 0 if res.get("sent") or res.get("skipped") else 2


if __name__ == "__main__":
    sys.exit(main())

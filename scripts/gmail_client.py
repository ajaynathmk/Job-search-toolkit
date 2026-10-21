#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/gmail_client.py
========================

Gmail access for the toolkit through your own Google OAuth client. Standing rule 2 (CLAUDE.md, rules/runbook.md): an application/portal channel is
draft-only, NEVER sent automatically — that part is still enforced at the
OAuth-scope level for everything employer-facing: create_draft() is the only path
CV/cover-letter and portal-channel content can ever take, and nothing in this file
sends to an arbitrary address.

**The digest exception:** the daily digest is different —
it is the owner mailing themselves a status report, not an application. This module now
also requests `gmail.send`, but ONLY to power `send_digest_email()`, which is
hard-guarded to the owner's own address (`owner_email()` below) and refuses any other
recipient. There is still no general-purpose send_message() here and there must
never be one — `send_digest_email()` is the one narrow, self-addressed exception,
not a precedent for sending anything to an employer or portal.

One-time setup (do this yourself; this script cannot do it for you):
  1. Go to https://console.cloud.google.com/ , create a project (or reuse one).
  2. Enable the Gmail API for that project.
  3. Configure the OAuth consent screen (External is fine for personal use;
     add your own Google account as a test user).
  4. Create an OAuth 2.0 Client ID, type "Desktop app". Download the JSON and
     save it as config/gmail_credentials.json (gitignored — never commit this).
  5. Run `python scripts/gmail_client.py auth` once. It opens a browser window for
     you to sign in and consent; afterwards a refresh token is cached at
     config/gmail_token.json (also gitignored) and no further browser step is
     needed. **If you're upgrading from a token authorized before 2026-09-28**,
     delete config/gmail_token.json first and re-run `auth` — the old token was
     issued for a narrower scope set and Gmail will reject send attempts with it
     until you re-consent to the new `gmail.send` scope. This step needs a real
     browser and cannot be done from a non-interactive session.

Usage (also importable — see search_employer_replies() etc. below):
    python scripts/gmail_client.py auth
    python scripts/gmail_client.py search "(Bewerbung OR Absage) newer_than:21d"
    python scripts/gmail_client.py employer-replies
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any

# Read-only + draft-creation + (as of 2026-09-28) send — but send is only ever
# reachable through send_digest_email() below, which hard-guards the recipient
# to owner_email(). Never widen this to gmail.modify beyond labels, and never call
# the send scope from anywhere except that one guarded function.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CREDENTIALS_PATH = CONFIG_DIR / "gmail_credentials.json"
TOKEN_PATH = CONFIG_DIR / "gmail_token.json"

# The only address send_digest_email() will ever send to: the owner mailing themselves
# the daily digest, never an employer or a portal. It is the digest address in
# profile/profile.json (email.digest_to, default the owner's own email).
def owner_email() -> str:
    import config
    addr = config.get().digest_to
    if not addr:
        raise RuntimeError("profile/profile.json has no email address: run /start (or set email.address) before sending the digest")
    return addr

# The five fixed employer-reply searches (rules/runbook.md, Step 3b). Copied
# verbatim — do not paraphrase these; a reimplementation should run the actual
# strings, not a description of what they mean.
EMPLOYER_REPLY_QUERIES = [
    '(Bewerbung OR Bewerbungseingang OR Eingangsbestaetigung OR "Ihre Bewerbung")',
    '(Absage OR "leider" OR "nicht beruecksichtigen" OR "anderweitig vergeben")',
    '("your application" OR "application received" OR "application status" OR '
    '"we regret" OR "unfortunately")',
    '(Vorstellungsgespraech OR Interview OR "Einladung" OR "invite you")',
    '(Praktikum OR Werkstudent OR Masterarbeit) -from:jobs@mail.xing.com '
    "-from:jobalerts-noreply@linkedin.com",
]
EMPLOYER_REPLY_WINDOW = "newer_than:21d"

XING_ALERT_SENDER = "jobs@mail.xing.com"
LINKEDIN_ALERT_SENDER = "jobalerts-noreply@linkedin.com"


class GmailAuthError(RuntimeError):
    """The cached token is dead and a browser sign-in is needed (python scripts/gmail_client.py auth)."""


def _get_credentials(interactive: bool = False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        refreshed = False
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                refreshed = True
            except Exception as exc:  # RefreshError: expired/revoked (a Google app in 'Testing' mode expires tokens after 7 days)
                if not interactive:
                    raise GmailAuthError(f"Gmail token expired or revoked ({exc}). Run: python scripts/gmail_client.py auth") from exc
                creds = None
        if not refreshed:
            if not interactive:
                raise GmailAuthError("No valid Gmail token. Run: python scripts/gmail_client.py auth")
            if not CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"{CREDENTIALS_PATH} not found. See this file's module docstring "
                    f"for the one-time Google Cloud OAuth setup."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _service():
    from googleapiclient.discovery import build

    creds = _get_credentials()
    return build("gmail", "v1", credentials=creds)


MAIL_CACHE = Path(__file__).resolve().parent.parent / "data" / "mail" / "msg"


def _retry(call):
    """Run a Gmail API call, backing off when the per-minute quota (403 rateLimitExceeded / 429) or a transient 5xx answers."""
    import time
    from googleapiclient.errors import HttpError
    for attempt in range(8):
        try:
            return call()
        except HttpError as exc:
            if exc.resp.status in (403, 429, 500, 503) and attempt < 7:
                time.sleep(min(70, 10 * (attempt + 1)))
                continue
            raise


def _get_full(service, msg_id: str) -> dict[str, Any]:
    """One message, read-only. A message never changes, so it is cached on disk and fetched once; Gmail's per-minute quota is
    backed off from (403 rateLimitExceeded / 429), not hammered."""
    cache = MAIL_CACHE / f"{msg_id}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    msg = _retry(lambda: service.users().messages().get(userId="me", id=msg_id, format="full").execute())
    headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
    rec = {
        "id": msg["id"], "thread_id": msg.get("threadId"), "from": headers.get("from", ""), "to": headers.get("to", ""),
        "subject": headers.get("subject", ""), "date": headers.get("date", ""), "internal_ms": int(msg.get("internalDate", 0)),
        "labels": msg.get("labelIds", []), "snippet": msg.get("snippet", ""), "body_text": _extract_plain_text(msg["payload"]),
    }
    MAIL_CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return rec


def fetch_messages(query: str, max_results: int = 100) -> list[dict[str, Any]]:
    """Rich read-only records for every message matching `query` (pages through results, cached per message):
    {id, thread_id, from, to, subject, date, internal_ms, labels, snippet, body_text}. This is what scripts/mail_sync.py reads."""
    import time
    service = _service()
    refs: list[dict] = []
    page = None
    while len(refs) < max_results:
        resp = _retry(lambda: service.users().messages().list(userId="me", q=query, maxResults=min(100, max_results - len(refs)), pageToken=page).execute())
        refs += resp.get("messages", [])
        page = resp.get("nextPageToken")
        if not page:
            break
    out = []
    for ref in refs:
        fresh = not (MAIL_CACHE / f"{ref['id']}.json").exists()
        out.append(_get_full(service, ref["id"]))
        if fresh:
            time.sleep(0.12)
    return out


def search_threads(query: str, max_results: int = 25) -> list[dict[str, Any]]:
    """Returns [{id, threadId}] — read-only, matches the claude.ai
    mcp__Gmail__search_threads shape closely enough that Step 3b/4's logic ports
    over with minimal changes."""
    service = _service()
    resp = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    return resp.get("messages", [])


def get_message_plain_text(message_id: str) -> dict[str, Any]:
    """Returns {id, subject, from, date, body_text}. Read-only."""
    service = _service()
    msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()

    headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
    body_text = _extract_plain_text(msg["payload"])

    return {
        "id": message_id,
        "subject": headers.get("Subject", ""),
        "from": headers.get("From", ""),
        "date": headers.get("Date", ""),
        "body_text": body_text,
    }


def _walk_parts(payload: dict[str, Any], mime: str) -> str:
    if payload.get("mimeType") == mime and "data" in payload.get("body", {}):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        text = _walk_parts(part, mime)
        if text:
            return text
    return ""


def _html_to_text(html: str) -> str:
    import html as _h
    import re
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d|table)>", "\n", html)
    text = _h.unescape(re.sub(r"(?s)<[^>]+>", " ", html))
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def _extract_plain_text(payload: dict[str, Any]) -> str:
    """The plain-text part when there is one, else the HTML part turned into text (many employer and ATS mails are HTML only)."""
    return _walk_parts(payload, "text/plain") or _html_to_text(_walk_parts(payload, "text/html"))


def search_employer_replies(window: str = EMPLOYER_REPLY_WINDOW) -> list[dict[str, Any]]:
    """Step 3b: the five fixed searches, each with the 21-day window, results
    de-duplicated by message id. Never replies, forwards, labels, trashes or
    modifies anything — this function only reads."""
    seen_ids: set[str] = set()
    results: list[dict[str, Any]] = []
    for query in EMPLOYER_REPLY_QUERIES:
        full_query = f"{query} {window}"
        for msg_ref in search_threads(full_query):
            if msg_ref["id"] in seen_ids:
                continue
            seen_ids.add(msg_ref["id"])
            results.append(get_message_plain_text(msg_ref["id"]))
    return results


def search_xing_harvest(gap_days: int) -> list[dict[str, Any]]:
    """Step 4: from:jobs@mail.xing.com newer_than:<gap>d. Ignores mailrobot@ —
    not a job alert."""
    query = f"from:{XING_ALERT_SENDER} newer_than:{gap_days}d"
    return [
        get_message_plain_text(m["id"])
        for m in search_threads(query)
    ]


def search_linkedin_harvest(gap_days: int) -> list[dict[str, Any]]:
    """Step 4: from:jobalerts-noreply@linkedin.com newer_than:<gap>d."""
    query = f"from:{LINKEDIN_ALERT_SENDER} newer_than:{gap_days}d"
    return [get_message_plain_text(m["id"]) for m in search_threads(query)]


def search_linkedin_alert_death() -> list[dict[str, Any]]:
    """Step 4: the alert-disabled check."""
    query = f'from:{LINKEDIN_ALERT_SENDER} subject:("turned off") newer_than:2d'
    return [get_message_plain_text(m["id"]) for m in search_threads(query)]


def create_draft(to: str, subject: str, body_text: str) -> dict[str, Any]:
    """The application/portal-channel write path. Creates a Gmail draft — never
    sends. the owner attaches files and hits send by hand. This is what Step 8 uses
    for any employer-facing content, and it must stay draft-only."""
    import email.mime.text

    service = _service()
    message = email.mime.text.MIMEText(body_text)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    draft = service.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()
    return draft


def send_digest_email(subject: str, body_text: str, html_body: str | None = None) -> dict[str, Any]:
    """Sends the daily digest to the owner's own inbox — added 2026-09-28 at his
    explicit request ("send the mails to me, not only draft ... From now on,
    when you do the daily run, you need to send that to me"). Hard-guarded to
    owner_email(): this function cannot be used to send anything to an employer or
    a portal, by construction, not by convention. Step 8's application/portal
    content must keep going through create_draft() — never this function."""
    import email.mime.multipart
    import email.mime.text

    service = _service()
    if html_body:       # 7 Oct 2026: the structured HTML digest (scripts/digest_email.py), with the plain text as the fallback part
        message = email.mime.multipart.MIMEMultipart("alternative")
        message.attach(email.mime.text.MIMEText(body_text, "plain", "utf-8"))
        message.attach(email.mime.text.MIMEText(html_body, "html", "utf-8"))
    else:
        message = email.mime.text.MIMEText(body_text, "plain", "utf-8")
    message["to"] = owner_email()
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    sent = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
    return sent


def main() -> int:
    # Windows consoles default to cp1252, which can't encode arbitrary JD/email
    # text (umlauts, em dashes, etc.) that ensure_ascii=False prints below.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth")
    p_search = sub.add_parser("search")
    p_search.add_argument("query")
    sub.add_parser("employer-replies")

    args = parser.parse_args()

    if args.cmd == "auth":
        _get_credentials(interactive=True)
        print(f"Authorized. Token cached at {TOKEN_PATH}")
        return 0

    if args.cmd == "search":
        for ref in search_threads(args.query):
            msg = get_message_plain_text(ref["id"])
            print(json.dumps(msg, indent=2, ensure_ascii=False)[:1000])
        return 0

    if args.cmd == "employer-replies":
        for msg in search_employer_replies():
            print(json.dumps(msg, indent=2, ensure_ascii=False)[:1000])
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())

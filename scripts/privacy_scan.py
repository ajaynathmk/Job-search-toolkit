#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Privacy scan: confirm that nothing personal and no secret is in what would be published.

It looks at the files Git would publish (tracked files plus untracked files that are not ignored; every file when the folder is not a Git repository),
and fails (exit 1) on any of:

  forbidden paths   a file under profile/, jd/, applications/, data/, digests/, logs/, config/, a database, a key file, remote/.dev.vars, node_modules
  e-mail addresses  any address that is not an example address (example.com / .org / .net / .invalid / .test, or a name containing 'example') or a known
                    job-board or service sender (linkedin.com, indeed.com, ...); consumer mailboxes (gmail, outlook, yahoo, gmx, ...) are never allowed
  phone numbers     a number with 9 or more digits that is not obviously fake (all zeros, 1234567...)
  secrets           Google API keys and OAuth tokens and client secrets, private keys, JWTs, GitHub and Slack tokens, Cloudflare KV namespace ids in wrangler.toml,
                    phone-inbox passphrases (four words and four digits)
  your own words    any `--also WORD` you give it (your name, your university, your city, your employer), in any file's content or name

    python scripts/privacy_scan.py                         # the working tree
    python scripts/privacy_scan.py --also "Your Name" --also "Your City"
    python scripts/privacy_scan.py --history               # also every commit: added lines, author and committer e-mails
    python scripts/privacy_scan.py --json

Run it before your first push and before every pull request. It reads files; it never changes anything and never sends anything anywhere.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_DIRS = ("profile/", "jd/", "applications/", "data/", "digests/", "logs/", "config/", "node_modules/", "remote/.wrangler/")
FORBIDDEN_GLOBS = ("db/*.db", "db/*.db-journal", "*.sqlite", "*.sqlite3", "remote/.dev.vars", "*.pem", "*.key", "*token.json", "*credentials.json", ".env", ".env.*", "scripts/tests/_test_*.db")
SKIP_CONTENT = (".git/", "node_modules/", "__pycache__/")
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".docx", ".xlsx", ".zip", ".woff", ".woff2", ".ttf", ".db", ".pyc"}
# The scanner's own pattern tables and its test (which plants fake secrets) would match themselves.
SELF = ("scripts/privacy_scan.py", "scripts/tests/test_privacy.py")

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
OK_EMAIL_DOMAINS = re.compile(r"(?:^|\.)(example\.(?:com|org|net|de|fr|edu)|example|invalid|test|localhost)$|^(?:linkedin|xing|indeed|glassdoor|stepstone|jobvector|zenjob|greenhouse|lever|workday|myworkday|smartrecruiters|personio|"
                              r"recruitee|join|ashbyhq|workablemail|jobs2web|b-ite|softgarden|handshake|joinhandshake|successfactors|rexx-recruitment|teamtailor|abbvie-careers)\.[a-z.]+$|^(?:mail|email|jobs|alerts|careers?|notifications?)\.(?:xing|linkedin|indeed|glassdoor)\.com$"
                              r"|^googlemail\.invalid$|^users\.noreply\.github\.com$|^noreply\.github\.com$|^anthropic\.com$|^claude\.com$")
CONSUMER = re.compile(r"(?:^|\.)(?:gmail|googlemail|outlook|hotmail|live|msn|yahoo|ymail|gmx|web|icloud|me|mac|proton|protonmail|pm|aol|t-online|freenet|mail|qq|163|126|yandex|rediffmail|zoho)\.[a-z.]+$", re.I)
PHONE = re.compile(r"(?<![\w.])(?:\+|00)\d{1,3}[\s().-]*\d(?:[\s().-]*\d){7,13}(?!\d)|(?<![\w.])0\d{2,4}[\s/-]\d{4,9}(?!\d)")
SECRETS = [
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("Google OAuth access token", re.compile(r"ya29\.[0-9A-Za-z_-]{20,}")),
    ("Google OAuth client secret", re.compile(r"GOCSPX-[0-9A-Za-z_-]{20,}")),
    ("Google OAuth client id", re.compile(r"[0-9]{6,}-[0-9a-z]{20,}\.apps\.googleusercontent\.com")),
    ("Google refresh token", re.compile(r"1//[0-9A-Za-z_-]{40,}")),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY")),
    ("JWT", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Cloudflare KV namespace id", re.compile(r"""(?im)^\s*id\s*=\s*["'][0-9a-f]{32}["']""")),
    ("phone-inbox passphrase", re.compile(r"\b[a-z]{3,9}(?:-[a-z]{3,9}){3}-[0-9]{4}\b")),
    ("bearer token", re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]{30,}")),
]


def git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError:
        return None
    return r.stdout if r.returncode == 0 else None


def publishable_files() -> tuple[list[str], str]:
    """Files Git would publish, relative to the root with forward slashes, and how they were found."""
    if (ROOT / ".git").exists():
        tracked = git("ls-files")
        others = git("ls-files", "--others", "--exclude-standard")
        if tracked is not None and others is not None:
            files = [f for f in (tracked + others).splitlines() if f and (ROOT / f).exists()]
            return sorted(set(files)), "git (tracked files plus untracked files that are not ignored)"
    files = []
    gi = (ROOT / ".gitignore")
    patterns = [ln.strip() for ln in gi.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")] if gi.exists() else []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith(".git/") or any(rel.startswith(s) for s in SKIP_CONTENT):
            continue
        if any(fnmatch.fnmatch(rel, pat.lstrip("/").rstrip("/") + ("/*" if pat.endswith("/") else "")) or rel.startswith(pat.lstrip("/")) for pat in patterns if pat.endswith("/") or "/" in pat or "*" in pat):
            continue
        files.append(rel)
    return sorted(files), "folder walk with .gitignore (this is not a Git repository)"


def fake_number(raw: str) -> bool:
    d = re.sub(r"\D", "", raw)
    return len(d) < 9 or re.search(r"0{6}$", d) is not None or d.count("0") >= len(d) - 3 or "1234567" in d or d.count(d[-1]) >= len(d) - 3


def scan_text(label: str, text: str, also: list[str], findings: list[dict]) -> None:
    for m in EMAIL.finditer(text):
        dom = m.group(1).lower()
        if OK_EMAIL_DOMAINS.search(dom) or "example" in m.group(0).lower():
            continue
        kind = "consumer mailbox address" if CONSUMER.search(dom) else "e-mail address"
        findings.append({"file": label, "kind": kind, "match": m.group(0)})
    for m in PHONE.finditer(text):
        if not fake_number(m.group(0)):
            findings.append({"file": label, "kind": "phone number", "match": m.group(0).strip()})
    for name, rx in SECRETS:
        for m in rx.finditer(text):
            findings.append({"file": label, "kind": name, "match": m.group(0)[:12] + "..."})
    low = text.lower()
    for w in also:
        if w.lower() in low:
            findings.append({"file": label, "kind": "your own word", "match": w})


def scan_tree(also: list[str]) -> tuple[list[dict], int, str]:
    files, how = publishable_files()
    findings: list[dict] = []
    for rel in files:
        if any(rel.startswith(d) for d in FORBIDDEN_DIRS) or any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(Path(rel).name, g) for g in FORBIDDEN_GLOBS):
            findings.append({"file": rel, "kind": "forbidden path", "match": "this file must never be published (it is personal data or a secret)"})
            continue
        for w in also:
            if w.lower() in rel.lower():
                findings.append({"file": rel, "kind": "your own word (in the file name)", "match": w})
        if rel in SELF or Path(rel).suffix.lower() in BINARY_EXT:
            continue
        try:
            data = (ROOT / rel).read_bytes()
        except OSError:
            continue
        if b"\x00" in data[:4096]:
            continue
        scan_text(rel, data.decode("utf-8", errors="replace"), also, findings)
    return findings, len(files), how


def scan_history(also: list[str]) -> tuple[list[dict], int]:
    findings: list[dict] = []
    if not (ROOT / ".git").exists():
        return [{"file": "(history)", "kind": "git", "match": "no history to scan (not a Git repository, or git is not installed)"}], 0
    if git("rev-parse", "--verify", "HEAD") is None:
        return [], 0                    # a repository with no commits yet has no history to leak
    out = git("log", "--all", "--format=%H%x09%an%x09%ae%x09%cn%x09%ce") or ""
    commits = [ln for ln in out.splitlines() if ln]
    for ln in commits:
        h, an, ae, cn, ce = (ln.split("\t") + [""] * 5)[:5]
        for who, mail in ((an, ae), (cn, ce)):
            dom = mail.split("@")[-1].lower()
            if mail and not OK_EMAIL_DOMAINS.search(dom) and "noreply" not in mail.lower():
                findings.append({"file": f"commit {h[:8]}", "kind": "author or committer e-mail", "match": mail})
            for w in also:
                if w.lower() in f"{who} {mail}".lower():
                    findings.append({"file": f"commit {h[:8]}", "kind": "your own word (author)", "match": w})
    patch = git("log", "--all", "-p", "--format=", "--no-color") or ""
    added = "\n".join(ln[1:] for ln in patch.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    scan_text("(history: added lines)", added, also, findings)
    names = git("log", "--all", "--name-only", "--format=") or ""
    for rel in sorted(set(n for n in names.splitlines() if n)):
        if any(rel.startswith(d) for d in FORBIDDEN_DIRS) or any(fnmatch.fnmatch(rel, g) for g in FORBIDDEN_GLOBS):
            findings.append({"file": rel, "kind": "forbidden path in history", "match": "was committed at some point"})
    return findings, len(commits)


def check_gitignore(findings: list[dict]) -> None:
    gi = ROOT / ".gitignore"
    text = gi.read_text(encoding="utf-8") if gi.exists() else ""
    for need in ("/profile/", "/db/tracker.db", "/jd/", "/applications/", "/data/", "/config/", "/remote/.dev.vars"):
        if need not in text:
            findings.append({"file": ".gitignore", "kind": "missing ignore rule", "match": need})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--also", action="append", default=[], metavar="WORD", help="a word that must appear nowhere (your name, university, city, employer); repeatable")
    ap.add_argument("--history", action="store_true", help="also scan every commit")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    findings, n, how = scan_tree(a.also)
    check_gitignore(findings)
    commits = 0
    if a.history:
        hf, commits = scan_history(a.also)
        findings += hf
    if a.json:
        print(json.dumps({"files_scanned": n, "how": how, "commits_scanned": commits, "findings": findings}, indent=1, ensure_ascii=False))
    else:
        print(f"privacy scan: {n} files ({how})" + (f", {commits} commits" if a.history else ""))
        if a.also:
            print(f"also looked for: {', '.join(a.also)}")
        for f in findings:
            print(f"  FAIL {f['file']}: {f['kind']}: {f['match']}")
        print("\nCLEAN: no personal data or secrets found." if not findings else f"\n{len(findings)} finding(s). Fix them before publishing.")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

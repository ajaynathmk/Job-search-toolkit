#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The job-search application. Start it with one command:

    python app.py                 start, and open the page in your browser
    python app.py --port 8080     another port
    python app.py --no-browser    do not open a browser window
    python app.py --check         only report what is ready and what is missing

You give it your CV; it works out your field, searches, reads every posting in full, scores it against your CV and lists the jobs worth your time.
The judgment steps run through Claude Code on your Claude subscription (no API key). Everything else runs on this computer; your CV and your jobs stay in
profile/ and db/, which are never uploaded anywhere. See docs/APP.md.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

CORE = [("flask", "flask"), ("requests", "requests"), ("bs4", "beautifulsoup4"), ("lxml", "lxml"), ("dateutil", "python-dateutil"), ("pypdf", "pypdf")]
OPTIONAL = [("docx", "python-docx", "tailored CVs get their page layout checked"), ("playwright", "playwright", "LinkedIn and Xing postings and the job-board searches"),
            ("googleapiclient", "google-api-python-client", "Gmail: replies and alerts")]


def have(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def report() -> int:
    """Print what is ready. Returns 0 when the application can start."""
    problems = 0
    print(f"job-search application, version {(ROOT / 'VERSION').read_text(encoding='utf-8').strip()}")
    if sys.version_info < (3, 10):
        print(f"  [missing] Python 3.10 or newer (this is {sys.version.split()[0]})")
        problems += 1
    else:
        print(f"  [ok]      Python {sys.version.split()[0]}")
    missing = [pip for mod, pip in CORE if not have(mod)]
    if missing:
        print(f"  [missing] {', '.join(missing)}\n            install them with:  python -m pip install -r requirements.txt")
        problems += 1
    else:
        print("  [ok]      the core Python packages")
    if not problems:
        import claude_runner
        st = claude_runner.status()
        print(f"  [{'ok' if st.get('subscription') else 'missing'}] Claude Code: {st['message']}")
        if not st.get("subscription"):
            problems += 1
    for mod, pip, what in OPTIONAL:
        print(f"  [{'ok' if have(mod) else 'optional'}] {pip}: " + ("ready" if have(mod) else f"not installed; it switches on: {what}"))
    return 1 if problems else 0


def already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/app/engine", timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=5057)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rc = report()
    if a.check:
        return rc
    if any(not have(mod) for mod, _ in CORE) or sys.version_info < (3, 10):
        print("\nInstall what is missing, then run this again.")
        return 1
    if rc:
        print("\nClaude Code is not ready. The page will tell you how to fix it; the rest still opens.")
    url = f"http://127.0.0.1:{a.port}/"
    if already_running(a.port):
        print(f"\nIt is already running: {url}")
        if not a.no_browser:
            webbrowser.open(url)
        return 0
    import db
    import webapp
    db.init_db()
    webapp._phone_sync_loop()
    print(f"\nOpen {url}   (local only: nothing outside this computer can reach it). Press Ctrl+C to stop.")
    if not a.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    webapp.app.run(host="127.0.0.1", port=a.port, debug=False, use_reloader=False, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

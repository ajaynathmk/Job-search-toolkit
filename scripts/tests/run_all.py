#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run every test file and the privacy scan; exit 1 if any fails.   python scripts/tests/run_all.py"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TESTS = ["test_db.py", "test_analyze.py", "test_onboard.py", "test_pipeline_e2e.py", "test_webapp.py", "test_mail_sync.py", "test_remote_e2e.py", "test_app.py", "test_app_web.py", "test_app_ui.py", "test_privacy.py"]


def main() -> int:
    failed = []
    for t in TESTS:
        r = subprocess.run([sys.executable, str(HERE / t)], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
        tail = (r.stderr.strip().splitlines() or [""])[-1]
        print(f"{'ok  ' if r.returncode == 0 else 'FAIL'} {t:26} {tail}")
        if r.returncode != 0:
            failed.append(t)
            print(r.stdout[-1500:], r.stderr[-2500:])
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "privacy_scan.py")], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
    print(f"{'ok  ' if r.returncode == 0 else 'FAIL'} privacy_scan.py             {r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ''}")
    if r.returncode != 0:
        failed.append("privacy_scan.py")
        print(r.stdout[-2000:])
    print("\nALL GREEN" if not failed else f"\nFAILED: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

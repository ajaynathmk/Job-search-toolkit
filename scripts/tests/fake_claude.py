#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A stand-in for `claude` so the application can be tested without the network or a Claude subscription.

Point JOBKIT_CLAUDE_BIN at this file (see test_app.py). It understands the four prompts in onboarding/app/ and the two status calls:

  --version                  prints a version
  auth status --json         prints a logged-in subscription
  -p ... (prompt on stdin)   "set the toolkit up"    copies an example profile into JOBKIT_PROFILE_DIR and writes assumptions.json
                             "Fix exactly these"     does nothing (the example is valid)
                             "stage S23"             reads each id with analyze.py show and confirms the script's verdict with analyze.py review
                             "build the application" writes a package folder under applications/

FAKE_CLAUDE=limit makes every -p call answer like an exhausted plan; FAKE_CLAUDE=fail makes it an error.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
args = sys.argv[1:]


def out(result: str, error: bool = False, cost: float = 0.01):
    print(json.dumps({"type": "result", "subtype": "error" if error else "success", "is_error": error, "result": result, "total_cost_usd": cost, "num_turns": 3, "permission_denials": []}))
    sys.exit(0)


if "--version" in args:
    print("0.0.0 (fake claude)")
    sys.exit(0)
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "pro"}))
    sys.exit(0)

prompt = sys.stdin.read()
mode = os.environ.get("FAKE_CLAUDE", "")
if mode == "limit":
    out("You've reached your usage limit. It resets at 18:00.", error=True)
if mode == "fail":
    out("something broke", error=True)

pd = Path(os.environ.get("JOBKIT_PROFILE_DIR") or ROOT / "profile")
ex = ROOT / "examples" / os.environ.get("FAKE_CLAUDE_EXAMPLE", "de-bioinformatics-student")

if "set the toolkit up" in prompt:
    pd.mkdir(parents=True, exist_ok=True)
    for f in ("profile.json", "domain.json"):
        shutil.copy(ex / f, pd / f)
    (pd / "master-profile.md").write_text("# Master profile\n\n- EXP-1: example\n", encoding="utf-8")
    prof = json.loads((pd / "profile.json").read_text(encoding="utf-8"))
    (pd / "assumptions.json").write_text(json.dumps([
        {"key": "work_authorization.status", "label": "Right to work", "value": prof.get("work_authorization", {}).get("status"), "source": "default", "confidence": "low", "why": "The CV states no nationality."},
        {"key": "regions", "label": "Where to search", "value": prof.get("regions"), "source": "inferred", "confidence": "medium", "why": "Latest education is there."},
    ], indent=2), encoding="utf-8")
    out("Bioinformatics and genomics. Core: genomics, biostatistics. Countries: Germany.")
if "Fix exactly these problems" in prompt:
    out("Nothing needed fixing.")
if "stage S23" in prompt:
    ids = [i.strip() for i in re.search(r"in this order:\s*(.+)", prompt).group(1).split(",")]
    lines = []
    for i in ids:
        show = subprocess.run([sys.executable, str(ROOT / "scripts" / "analyze.py"), "show", i], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT))
        m = re.search(r"verdict (\w+)", show.stdout)
        sc = re.search(r"\| score (\d+) \|", show.stdout)
        if not m:
            lines.append(f"{i}: could not read")
            continue
        subprocess.run([sys.executable, str(ROOT / "scripts" / "analyze.py"), "review", i, "--verdict", m.group(1), "--reason", "Fake review: the posting was read in full and the script's reading holds."]
                       + (["--score", sc.group(1)] if sc else []), capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
        lines.append(f"{i}: {m.group(1)}, no big gap")
    out("\n".join(lines))
if "build the application package" in prompt:
    jid = re.search(r"role id `([^`]+)`", prompt).group(1)
    d = ROOT / "applications" / f"{date.today().isoformat()}_Fake_{re.sub(r'[^A-Za-z0-9]+', '-', jid)[:30]}"
    d.mkdir(parents=True, exist_ok=True)
    for f in ("cv.md", "cover-letter.md", "match-report.md", "submission-checklist.md", "posting.txt"):
        (d / f).write_text(f"# {f}\nfake\n", encoding="utf-8")
    out(f"{d.relative_to(ROOT)}\nNothing for you to decide.")
out("ok")

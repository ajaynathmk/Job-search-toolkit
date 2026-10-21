#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Schedule the unattended daily run on whatever system this is: Windows Task Scheduler, macOS launchd or Linux cron.

    python scripts/scheduler.py install [--time 07:30]      # register `python scripts/pipeline.py run` to run once a day (and at log-in)
    python scripts/scheduler.py remove
    python scripts/scheduler.py status

The run itself is idempotent: it does its work once per calendar day, so extra triggers (log-in, hourly on Windows) are harmless. It never
submits an application and never sends anything but the owner's own digest (rules/pipeline.md). The time is local time.
"""
from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
PIPELINE = ROOT / "scripts" / "pipeline.py"
TASK = "job-search-toolkit"
PLIST = Path.home() / "Library" / "LaunchAgents" / "com.job-search-toolkit.daily.plist"
MARK = "# job-search-toolkit"


def _hm(t: str) -> tuple[int, int]:
    h, m = t.split(":")
    return int(h), int(m)


def install_windows(t: str) -> int:
    ps = f'''
$a = New-ScheduledTaskAction -Execute "{PY}" -Argument '"{PIPELINE}" run' -WorkingDirectory "{ROOT}"
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\\$env:USERNAME"
$rep = (New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Hours 14)).Repetition
$logon.Repetition = $rep
$daily = New-ScheduledTaskTrigger -Daily -At {t}
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName "{TASK}" -Action $a -Trigger @($logon, $daily) -Settings $s -Force | Out-Null
Get-ScheduledTask -TaskName "{TASK}" | Select-Object TaskName, State | Format-List
'''
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    print(r.stdout, r.stderr)
    return r.returncode


def install_mac(t: str) -> int:
    h, m = _hm(t)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.job-search-toolkit.daily</string>
<key>ProgramArguments</key><array><string>{PY}</string><string>{PIPELINE}</string><string>run</string></array>
<key>WorkingDirectory</key><string>{ROOT}</string>
<key>StartCalendarInterval</key><dict><key>Hour</key><integer>{h}</integer><key>Minute</key><integer>{m}</integer></dict>
<key>RunAtLoad</key><true/>
<key>StandardOutPath</key><string>{ROOT / "logs" / "launchd.log"}</string>
<key>StandardErrorPath</key><string>{ROOT / "logs" / "launchd.log"}</string>
</dict></plist>
''', encoding="utf-8")
    (ROOT / "logs").mkdir(exist_ok=True)
    subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
    r = subprocess.run(["launchctl", "load", str(PLIST)], capture_output=True, text=True)
    print(r.stdout, r.stderr)
    return r.returncode


def _crontab() -> str:
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def install_linux(t: str) -> int:
    h, m = _hm(t)
    keep = [ln for ln in _crontab().splitlines() if MARK not in ln]
    (ROOT / "logs").mkdir(exist_ok=True)
    keep.append(f'{m} {h} * * * cd "{ROOT}" && "{PY}" "{PIPELINE}" run >> "{ROOT / "logs" / "cron.log"}" 2>&1 {MARK}')
    r = subprocess.run(["crontab", "-"], input="\n".join(keep) + "\n", text=True, capture_output=True)
    print(r.stdout, r.stderr)
    return r.returncode


def install(t: str) -> int:
    sysname = platform.system()
    return install_windows(t) if sysname == "Windows" else install_mac(t) if sysname == "Darwin" else install_linux(t)


def remove() -> int:
    sysname = platform.system()
    if sysname == "Windows":
        r = subprocess.run(["powershell", "-NoProfile", "-Command", f'Unregister-ScheduledTask -TaskName "{TASK}" -Confirm:$false'], capture_output=True, text=True)
    elif sysname == "Darwin":
        subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
        PLIST.unlink(missing_ok=True)
        return 0
    else:
        keep = [ln for ln in _crontab().splitlines() if MARK not in ln]
        r = subprocess.run(["crontab", "-"], input="\n".join(keep) + "\n", text=True, capture_output=True)
    print(r.stdout, r.stderr)
    return r.returncode


def status() -> int:
    sysname = platform.system()
    if sysname == "Windows":
        r = subprocess.run(["powershell", "-NoProfile", "-Command", f'Get-ScheduledTask -TaskName "{TASK}" -ErrorAction SilentlyContinue | Select-Object TaskName, State | Format-List'],
                           capture_output=True, text=True)
        print(r.stdout.strip() or "not scheduled")
    elif sysname == "Darwin":
        print("scheduled (launchd)" if PLIST.exists() else "not scheduled")
    else:
        print("\n".join(ln for ln in _crontab().splitlines() if MARK in ln) or "not scheduled")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["install", "remove", "status"])
    ap.add_argument("--time", default="07:30")
    a = ap.parse_args()
    return install(a.time) if a.cmd == "install" else remove() if a.cmd == "remove" else status()


if __name__ == "__main__":
    sys.exit(main())

---
description: Make the daily run happen by itself (Windows Task Scheduler, launchd or cron)
argument-hint: "[HH:MM, default 07:30] | remove | status"
---

Argument: $ARGUMENTS

1. `python scripts/onboard.py status` must say the configuration is valid; if not, run `/start` first.
2. Explain in two lines what the scheduled run does (the watches, Gmail read-only, intake, the analysis, the digest e-mail to the person's own address) and what it never does (submit, send to employers, write `my_notes`).
3. Install: `python scripts/scheduler.py install --time <HH:MM>` (default 07:30). Remove: `python scripts/scheduler.py remove`. Check: `python scripts/scheduler.py status`.
4. The run happens once per calendar day when the computer is on; extra triggers are harmless. On a laptop it waits for the charger unless the person wants `--ignore-power`. Logs go to `logs/`.

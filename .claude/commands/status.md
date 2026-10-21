---
description: Show where the search stands: configuration, stages, audit, what needs the person
---

Give the person a short, honest status.

1. `python scripts/onboard.py status` (is it configured, which region packs, the rule version).
2. `python scripts/pipeline.py status` (every stage with its last run) and `python scripts/pipeline.py check` (the audit; list FAIL and WARN items with their fix lines).
3. Counts from the tracker through `scripts/db.py` (do not open the database directly): open roles by verdict, packages ready, applied, interviews, rejections in the last 14 days, best fits waiting for review, scores that moved.
4. What needs the person now (mail that asks them to act, deadlines within 7 days, packages waiting to be sent), then what needs you (review queue, unmatched mail).
5. What is not set up and what it would unlock (`python scripts/onboard.py doctor`): Gmail, the schedule, Playwright, Node, the phone inbox. One line each, only the ones that matter.

Keep it to one screen. Do not paste raw JSON.

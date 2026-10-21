---
description: Run today's search end to end (mail, watches, intake, analysis), then work the brief
argument-hint: "[--force to run even if it already ran today]"
---

Run the daily search. Load `rules/pipeline.md` and `rules/runbook.md` first.

1. `python scripts/pipeline.py status` and `python scripts/pipeline.py check`: read the audit. A FAIL stops everything until fixed (fix it; most have a `fix:` line).
2. Run the unattended part: `python scripts/pipeline.py run --ignore-power $ARGUMENTS`. It does the Gmail pass (if set up), the institution and company watches, intake (stubs and full JDs), the analysis of every row, the worklist and the digest.
   If Gmail is not set up say so once and move on; if the digest cannot be sent say so.
3. Read the brief it wrote (`digests/pipeline-<date>.md`) and work it in this order, saying what you did and what you did not:
   - **Mail that asks the person to act** (an invitation, an assessment, documents with a date): tell them first.
   - **Mail the pipeline could not settle**: `python scripts/mail_sync.py show <id>`, decide, `judge`.
   - **Board sweep and wider-region sweep** (stages S12, S13) with the region's boards and the person's search terms, using the `Agent` tool with a fast model for the reading; file candidates through intake (`python scripts/intake.py run`).
     Never search LinkedIn with a keyword search unless the person is present; never use a logged-in context.
   - **Review the best fits** (`/review`) if any are waiting.
   - **Rechecks (max 3) then approvals (max 2)**: `/apply`, only for roles the person approved.
4. End with a short summary: what is new and worth their attention, what needs them, what failed or was skipped (name every source that did not run). Do not repeat the digest.

Never submit an application, never touch a portal with the person's data, never write `my_notes`.

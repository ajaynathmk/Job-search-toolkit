---
description: Build a tailored CV and cover letter for roles the person approved (rechecks first), without ever submitting anything
argument-hint: "[a role id, or leave empty for the approved queue]"
---

Stage S40 to S42 of `rules/pipeline.md`. Load `rules/applications.md`, `rules/cv-build.md`, `rules/language-quality.md`, `profile/master-profile.md` and `regions/<code>/cv-conventions.md` for the posting's country.

Role: $ARGUMENTS

1. **Queue.** `python scripts/pipeline.py queue`: rechecks first (max 3), then approvals (`approval = requested`, max 2 unless the person asks for more). Only build for a role the person approved.
2. **Read** the row's `my_notes` first (the person's briefing or the problem to investigate) and the cached JD (`jd/<Employer>_<slug>/description.md`). Do not re-fetch the JD (except a recheck). Re-check the walls from the full text.
3. **Build** in `applications/<date>_<Employer>_<role-slug>/`: `cv.md`, `cover-letter.md`, `match-report.md`, `submission-checklist.md`, `posting.txt`, following `rules/applications.md` exactly:
   tailoring **reorders, never cuts, never invents**; the Profile paragraph is written fresh for this role; the letter never repeats the CV, takes its themes from the posting, states real interest in this role, one page;
   the document language follows the posting; the country's conventions apply. Write every sentence in correct, professional language (`rules/language-quality.md`).
4. **Ship gate:** `bash scripts/ship-package.sh <folder> [--cv-only]`. Fix the markdown and run it again until it passes; never hand-build around it. Then open the .docx or PDF and read every page.
5. **Hand over** a Gmail draft (`gmail_client.create_draft`, never attached, never sent) for an e-mail channel, or the checklist for a portal channel; set `approval = prepared` through `scripts/db.py`. Tell the person exactly what to send or click, and
   what only they can decide (portal questions about their data, a signature).

**Never submit anything. Never touch a portal with the person's data. Never create an account. Never send mail to an employer.** An approval flag is not consent to submit. If the briefing asks for something untrue, say so in one line and offer the nearest true thing.

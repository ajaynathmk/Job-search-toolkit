---
description: Set up the job-search toolkit for you from your CV (field, languages, country, work rights), then run the first search
argument-hint: "[path to your CV: pdf, docx, md or txt]"
---

You are onboarding a new user of this toolkit. Follow `onboarding/README.md` exactly, step by step; it is the procedure. Read `CLAUDE.md` first if you have not this session.

The CV (or its path) is: $ARGUMENTS

If no path was given, check `profile/cv-source.txt`, then ask the user for their CV file or text (a PDF, a Word file, Markdown or plain text), or offer a short interview if they have none.

Rules for this command:

1. Work in this order: look at what exists (`python scripts/onboard.py status`), extract and read the CV, infer the field (`onboarding/domain-inference.md`), ask only the questions the CV cannot answer (`onboarding/questions.md`, use the question tool,
   up to four at a time, with defaults), choose or research the region packs (`rules/regions.md`), write `profile/profile.json`, `profile/domain.json`, `profile/master-profile.md` (and the master CV markdown if they want tailored CVs), validate
   (`python scripts/onboard.py check`: zero errors, read every warning), then test the configuration on real postings with the person and fix what surprises you.
2. Show the person what you inferred in plain language and get their corrections **before** you write `domain.json`.
3. Never invent a skill, level, degree or employer. Never put the person's data in a web search. Never create an account, a cloud project or an alert for them; never send an e-mail.
4. For a country with no shipped pack, research it from official sources and write the pack (`/region` has the same procedure); say what is unverified.
5. Offer the optional parts one at a time (dashboard, Gmail, alerts, schedule, phone inbox); do only what they accept. `python scripts/onboard.py doctor` tells you what is installed.
6. Finish with the first run (`python scripts/pipeline.py run --force --ignore-power`), a first look at the best fits (`/review`), and a short summary: what is set up, what is not and what it would unlock, where their data lives (`profile/`, git-ignored),
   and what to type next (`/daily`, `/review`, `/apply`, `/status`).
7. Log nothing personal in `CHANGELOG.md`; log a one-line entry only if you changed a rule, a script or the schema.

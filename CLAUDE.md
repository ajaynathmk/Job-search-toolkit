# Job-search toolkit: instructions for Claude Code

This repository automates a job search for one person: it reads Gmail for alerts and employer replies, sweeps job boards and employer career sites, scores and files every in-scope role in a local SQLite tracker, and, only on the
person's own approval, builds a tailored CV and cover-letter package. It works for any field and any country: **who, what and where come from configuration, not from code** (`docs/ARCHITECTURE.md`).

## First thing every session

1. `python scripts/onboard.py status`.
2. **If `profile/profile.json` or `profile/domain.json` is missing, or `check` reports errors, this person has not been set up: run `/start` (follow `onboarding/README.md`).** Do not search, score or build anything for an unconfigured profile.
3. Otherwise read what the task needs, not everything: `rules/pipeline.md` (the whole system, stage by stage; `python scripts/pipeline.py status` shows it live) and the rule file of the stage you are touching.

## The rules map (the `rules/` file wins if this file disagrees)

- `rules/pipeline.md`: the stages, verdicts, the strict scoring rule in code, the audit, the schedule. **Start here.**
- `rules/runbook.md`: the daily steps, budgets, the JD cache, THE LINK RULE, search mechanics.
- `rules/tracker-schema.md`: the database shape, ids, approval states.
- `rules/applications.md`: how a cached JD becomes a CV and letter (tailoring reorders, never cuts, never invents).
- `rules/cv-build.md`: visual spec, the anti-AI checker, the consistency checker, the ship gate.
- `rules/language-quality.md` (and `rules/languages/`): correct, professional prose in the posting's language.
- `rules/regions.md`: region packs, and how to research a country that does not ship one. `regions/<code>/` holds each pack, with its `legal.md`.
- `rules/mail.md`, `rules/digest.md`, `rules/remote.md`: Gmail in the pipeline, the digest e-mail, the phone inbox.
- `rules/job-watch.md`, `rules/institutions.md`, `rules/employers.md`, `rules/alerts.md`, `rules/search-terms.md`: finding roles.
- `rules/known-issues.md`: what is built, what needs a live setup, source health.
- `onboarding/`: how a CV becomes a configuration. `docs/`: setup and operation for people.

## Non-negotiables (repeated here because they must never be missed)

1. **The digest e-mail always goes out, even on zero hits, to the person's own address only** (`gmail_client.send_digest_email()`, hard-guarded to `profile.email`). It is the only mail the toolkit ever sends.
2. **Never submit an application.** Draft, never send. Never touch a portal with the person's data. Never create an account on their behalf. `scripts/gmail_client.py` enforces this for every employer-facing path:
   `create_draft()` is the only write Step 8 may call, and it only creates a draft. An approval flag is not consent to submit.
3. **THE STRICT SCORING RULE: read the full JD before scoring anything.** Every role is ranked from its own full description, never its title, snippet, summary or earlier note. `scripts/db.py` enforces the proof for jobs **and thesis rows**:
   a score, tier, verdict, category or fit score is refused (`ScoreWithoutJDError`) unless the full JD is cached (500+ characters), the write carries the hash of that cached text, the analysis level is `auto` (a script read the whole text) or `reviewed`
   (a Claude session did, with a read receipt from `analyze.py show`), and a score comes with its breakdown. `source="rollback"` restores an earlier value only.
4. **A JD is fetched exactly once, ever**: a recheck, and a cached JD found defective (`intake.py repair`), are the only exceptions.
5. **THE LINK RULE:** no unverified URL ever reaches the tracker (`rules/runbook.md`).
6. **Never write `my_notes` in `db/tracker.db`.** It is the owner's field. `scripts/db.py`'s `update_job()` raises `MyNotesGuardError` unless the call passes `source="owner"`. Do not bypass it with a raw SQL `UPDATE`, and do not add a code path that passes
   `source="owner"` from anywhere except code directly relaying the person's own typed input (the dashboard note box, the phone note).
7. **Tailoring reorders. It never cuts content and it never invents it** (`rules/applications.md`).
8. **Maximum range, every posting read in full, every verdict stored.** Intake files every in-scope posting as an unscored row and fetches its full JD; nothing is dropped for being off-topic. A script analyses the full text; a Claude session then reads the full JD of every
   best fit (APPLY, BACKUP, PLAN, LATER) against the CV and confirms or overrides (`analyze.py show`, then `review`). Scores are dynamic: every move is flagged.
9. **Never invent a skill, a level, a degree, an employer or a legal fact.** A figure in a region pack that was not read from the official page is marked unverified. When you do not know, say so and offer the nearest thing you are sure of.
10. **Personal data stays on the person's machine.** `profile/`, `db/tracker.db`, `jd/`, `applications/`, `data/` and `config/` are git-ignored; web searches use field and country words, never the person's name, e-mail, employers or CV text; run
    `python scripts/privacy_scan.py` before any commit you make for the person.

## The database

`db/tracker.db` (SQLite, git-ignored). Access it **only** through `scripts/db.py`: never open a raw `sqlite3` connection against it from other code. `python scripts/db.py` creates it from `db/schema.sql` if missing. Run
`python scripts/tests/test_db.py` after touching `scripts/db.py`; `test_my_notes_guard_blocks_automation` must never go red.

## Running things

- `python scripts/onboard.py status | check | doctor | demo` and `/start`: configuration.
- `python scripts/pipeline.py status | check [--tests] | queue | run [--force] [--ignore-power]`: the conductor; `/daily` and `/status`.
- `python scripts/intake.py run | repair | retry` and `python scripts/analyze.py run | show <id> | explain <id> | review <id> ...`: the heart of the system.
- `python scripts/job_watch.py`, `python scripts/uni_watch.py`: the watches (never write the tracker). `python scripts/mail_sync.py run`: Gmail.
- `python scripts/webapp.py`: the dashboard at `http://127.0.0.1:5057` (local only; never bind beyond localhost).
- `bash scripts/ship-package.sh <application-folder> [--cv-only]`: the CV and letter quality gate; never hand-build a package outside its order.
- `python scripts/aicheck.py`, `consistency_check.py`, `lang_check.py`: the checkers, standalone.
- Tests: `python scripts/tests/test_db.py`, `test_analyze.py`, `test_pipeline_e2e.py`, `test_onboard.py`, `test_webapp.py`, `test_mail_sync.py`, `test_remote_e2e.py`, and `python scripts/privacy_scan.py`.

## When the person asks a question about a role

Answer from `jd/<Employer>_<role-slug>/description.md` (the row's `jd_path`) and the tracker row (`scripts/db.py`'s `get_job()`). Do not re-fetch the posting: that violates rule 4.

## Versioning: log every change in `CHANGELOG.md`

The current version is in `VERSION`. In every session, any change to rules, scripts, configuration schema or behaviour gets a one-line entry in `CHANGELOG.md` under the open version, in the same turn it is made. Do not bump the version yourself: the open
version stays open until the maintainer says "this is version N+1" (or "start version N+1"); then close the section, set `VERSION` and open the next.

## Writing code and rules here

Match the surrounding code: comments explain why, not what; no personal data, no real names, no real employers in fixtures (use `example.org`, `Example University`, fictional people); the engine contains no knowledge of a country or a field (that belongs in a region pack or the
domain file); every new rule or script that changes behaviour gets a test, and the privacy scan must pass.

# Architecture

## Principles

1. **The engine knows no person, country or field.** Who, what and where are data (`profile/profile.json`, `profile/domain.json`, `regions/<code>/region.json`), read by one module (`scripts/config.py`).
2. **Scripts do what needs no judgment; Claude does what does.** Fetching, parsing, matching, scoring from rules, scheduling are scripts. Understanding a CV, confirming a verdict against it, writing a letter, researching a country are a Claude session.
3. **Every judgment carries its proof.** A score exists only with the cached full text, its hash and a breakdown. A reviewed verdict exists only with a read receipt.
4. **Nothing irreversible happens without the person.** No submission, no mail to employers, no account creation. `my_notes` belongs to the person.
5. **Personal data stays local and git-ignored**, and a privacy scan enforces it.

## The application layer (1.7)

`app.py` starts the dashboard server with one more page, `/start`. `scripts/app_routes.py` is its API; it starts `scripts/app_core.py` as a separate process (stages
understand, configure, search, collect, read, review; state in `profile/app/state.json`, written under a file lock that merges only the keys each writer owns). The three
judgment steps go through `scripts/claude_runner.py`, which starts Claude Code headless (`claude -p`) with the prompts in `onboarding/app/` on the person's own subscription:
an API key in the environment is removed from the child process, the connectors, memory, skills and saved session are switched off, and a plan limit pauses the run.
The application adds no new rule: it performs the procedures of `onboarding/README.md` and `.claude/commands/review.md` and `apply.md` without a person to answer questions,
records every guess as an assumption the person can correct, and goes through the same guarded `db.py`, so the strict-scoring proof, the read receipt and the never-submit
rules apply exactly as before. See `docs/APP.md`.

## Layers

```
 profile/ (yours, ignored)     regions/ (shipped or researched)     resources/ (shipped tables)
   profile.json  domain.json     de/ eu/ us/ _template/               languages.json  kinds.json  levels.json
   master-profile.md  sources    region.json sources.json legal.md    countries.json  country_languages.json
        │                              │                                cv_headers.json  employers.json  mail_patterns.json
        └──────────────┬───────────────┘                                        │
                  scripts/config.py  (merge; rule_version = hash of the merge) ─┘
                       │
   ┌───────────────────┼─────────────────────────────────────────────────────────────────────┐
   │ definitions.py    │  stages, categories, verdicts, windows: one source for every consumer │
   │ db.py + db/schema.sql  the only access to the tracker (guards live here)                 │
   │ intake.py   analyze.py   pipeline.py (conductor, audit, worklist)                        │
   │ job_watch.py  uni_watch.py  mail_sync.py  gmail_client.py  digest_email.py                │
   │ webapp.py + webapp_static/  remote_sync.py + remote/ (Cloudflare Worker)                  │
   │ build-cv.js  aicheck.py  consistency_check.py  fingerprint.py  keep_pass.py  ship-package.sh │
   └──────────────────────────────────────────────────────────────────────────────────────────┘
```

## The configuration

| | File | Key contents |
|---|---|---|
| WHO | `profile/profile.json` | `career_stage`, `levels_sought`, `regions`, `cities`, `languages` (level per language), `work_authorization.status`, `accept_unrelated_income`, `tiers`, `mail`, `walls`, `route_rules` |
| WHAT | `profile/domain.json` | `categories`, `subfields` (`role`, `weight`, `terms`, `aliases`), `penalty_subfields`, `priority_employers`, `industry_regex`, `cv_evidence`, `search_terms`, `thesis_pillars`, `walls` |
| WHERE | `regions/<code>/region.json` | `primary_countries`, `scope_countries`, `local_languages`, `routes`, `route_rules`, `walls`, `boards`, `mail`, `country_hints` |

Several packs merge, home market first (`config._extend_pack`). `profile/region.override.json` overrides any merged key. `JOBKIT_PROFILE_DIR` points the whole toolkit at another profile folder (the tests and `onboard.py demo` use it).

`config.rule_version()` is a hash of profile + domain + region + engine version. It is stored on every analysed row; when it changes, the next run re-analyses and flags every score that moves.

## The analysis (`scripts/analyze.py`)

For one row and its full cached text:

1. Detect the posting's language and kind (thesis, student assistant, working student, internship, trainee, entry, mid, senior) from `resources/kinds.json`, the title, and, for an unmarked title, the experience asked for.
2. **Language requirements** for every language the search is exposed to (the region's, the posting country's, the posting's own, English if yours is below C1): the required level (`resources/languages.json`: anchors and phrases in 21 languages, optional markers) against your level
   (`profile.languages`): wall if two or more steps above, cap at BACKUP for one step, penalty for an unquantified ask.
3. **Walls**: region + domain + profile (`when` conditions, `unless_re`), each quoting the sentence.
4. **Classification** by weighted terms (title counts triple, body up to 4 hits per term) into a sub-field, own vs other, with `classification_overrides`.
5. **CV comparison** against `domain.cv_evidence`: covered / partial / gap, required or nice-to-have by the term's own line.
6. **Score** from the components (core +4, bridge +2, priority +2, recency +2, location +1, language fit +1, language above -1, penalties -2, admin -2, evidence bonus +1) plus the **route adjustment** from the first matching route rule.
7. **Verdict** from field role, primary vs scope country, kinds sought, score tiers, walls and deadline; a reason in one paragraph.
8. Write with proof (`jd_sha`, level, breakdown); compare with the stored score; append `score_history`, set `score_flag` when it moved; never overwrite a `reviewed` verdict.

## The pipeline (`scripts/pipeline.py`)

A registry of stages (S00 to S52) with owner, command, inputs, outputs and gate; the audit (C01 to C34) of invariants; the worklist for the Claude stages; the unattended run (once a day). `python scripts/pipeline.py status` is the live map; `rules/pipeline.md` is the description.

## The tracker (`scripts/db.py`, `db/schema.sql`)

SQLite, one row per role (`jobs`), thesis leads (`thesis`), mail facts (`mail_events`), read receipts (`jd_reads`). `db.py` is the only access layer and holds the guards: `my_notes` only with `source="owner"`; judgment fields only with proof; closed vocabularies derived from your
configuration (`refresh_vocab`); optimistic concurrency on `version`; package folders follow `status`.

## Extending it

- **A new country**: a region pack (`/region`). No code.
- **A new field**: nothing; it is whatever `domain.json` says.
- **A new language**: add it to `resources/languages.json` (anchors and phrases), `country_languages.json`, `cv_headers.json`, and a checklist in `rules/languages/`.
- **A new job source**: an adapter in `job_watch.py` or `uni_watch.py` (a function returning items) plus an entry in `sources.json`; a new fetch route in `intake.py` for its postings.
- **A new check**: a function in `pipeline.check()` with an id, a severity and a fix line.

## Tests

`scripts/tests/`: the database guards, the analysis on two fictional profiles in two countries (including "the same text, a different person"), onboarding validation, an end-to-end analysis against a throwaway tracker, the dashboard API, the Gmail pass, the phone inbox's rules.
`python scripts/pipeline.py check --tests` runs them; `python scripts/privacy_scan.py` checks the tree.

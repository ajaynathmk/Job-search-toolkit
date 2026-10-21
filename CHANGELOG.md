# Changelog

Version numbers are a scheme, not strict semver: a whole number marks a point that was exported, the `.N` after it accumulates every edit made after
that export until the maintainer says the version has moved on. The current version also lives in the `VERSION` file.

Every change to the rules, the scripts, the configuration schema or the behaviour gets a one-line entry here under the open version, in the same
change. Do not bump the version yourself: say "this is version 1.7" (or "start version 1.7") and Claude closes the open section, sets `VERSION` and
opens the next one.

## [1.7] — in progress (the application)

**Added**
- README: requirements table, repository map, day-to-day commands, troubleshooting, and the real clone URL.
- **The application** (`app.py`, page `/start`): give it a CV and nothing else, and it works out the person's field, builds the search, collects postings, reads every
  posting in full, scores each against the CV, has the best fits read a second time, and shows the ranked jobs with the reason, the skills the CV shows and the gaps.
  One command (`python app.py`, or `start.bat` / `start.command`), local only, in the browser. See `docs/APP.md`.
- **Runs on the person's Claude subscription**, through Claude Code in the background (`scripts/claude_runner.py`): no API key is asked for or stored, and an API key set
  on the machine is never passed on (it would be billed instead of the subscription). Lean flags: a call costs about $0.035 of list-price usage instead of $0.68 (a
  bare `claude -p` loads every connected tool and memory). A plan limit pauses the run with a resume hint.
- **Engine** (`scripts/app_core.py`): stages understand, configure, search, collect, read, review; progress in `profile/app/state.json` (file lock, merge-on-save, so the
  engine, the page and a tailoring job never overwrite each other); resume after a stop, a crash or a closed tab; usage cap; correction of the assumptions with validation
  and an immediate re-score; tailored CV and cover letter for one approved role (never sends anything). Prompts in `onboarding/app/`.
- **Web page and API** (`scripts/app_routes.py`, `webapp_static/start.*`): upload or paste the CV, optional notes, live progress, "what I understood" with editable assumptions,
  ranked jobs with filters, approve-and-write, and the optional parts (daily schedule, e-mail summary, Gmail and phone status). Refuses requests whose Host or Origin is another site.
- **Board sweep** (`scripts/board_sweep.py`): LinkedIn and Xing searched with Boolean queries generated from the person's own sub-fields and role words
  (`profile/saved-queries.json`). Measured 20 Oct 2026: both boards treat the topic word as optional (a made-up word still returned 60 and 16 roles); only the Boolean form finds
  the roles whose titles carry the field word.
- Tests: `test_app.py` (engine end to end with a fake Claude), `test_app_web.py` (API and protections), `test_app_ui.py` (a real browser drives the page), `fake_claude.py`.

**Changed**
- The jobs list shows every best fit in steps of 30 (the filter counts were wrong when the list was cut), and a role no session has re-read gets a plain-language reason (field, kind of role,
  language asked, what counted in its favour) instead of the analyzer's shorthand; a re-read role shows the re-reader's own reasoning. The review prompt keeps score and verdict in agreement; the default is 30 roles re-read per run.
- `remote_sync.py push()` uploads only what changed (snapshot hourly heartbeat, details daily; hashes in `data/remote-state.json`; a manual `push` forces). The old code wrote two
  Cloudflare KV values every 5 minutes (up to about 576 of the 1,000 free writes a day) and exhausted the account's daily limit. Six offline regression tests.
- `analyze.py`: LinkedIn guest pages with a repeated login wall are cut at the wall, not at the privacy word inside it (a posting kept 9% of its text); `looks_like_posting`
  knows "Danach suchen wir", "Die Stelle im Überblick", "Unterstützung bei".
- `job_watch.py`: a SmartRecruiters source may carry `"country": "de"`. `db.py`: `JOBKIT_DB` redirects the tracker file (the tests use it for child processes).

**Fixed**
- **Every analysis failed for a person with no work-permit limit** (citizen, EU citizen, resident): the route is "unrestricted" and the database's list of allowed routes did not include
  it, so every write was refused (1,076 of 1,076 on the first live run). Found only by running the application for real on a fictional German citizen; no example profile had one.
  `db.py` now allows it; regression test `test_a_person_with_no_work_permit_limit_is_analysed_and_stored` (fails with the bug restored, passes with the fix).
- A fresh install had no tracker table when the engine ran before the page (`app_core` now initialises the database; idempotent).
- The understand step is verified, not trusted: an empty template file or an unwritten `assumptions.json` is an error that quotes what Claude said and how many actions it was refused.
  Claude Code only auto-approves edits inside its working directory, so a profile folder outside the toolkit is granted with `--add-dir` (long path, never a Windows 8.3 short name) and named in the prompt.
- Tailoring finds its package folder by modification time, so rebuilding a role on the same day is not reported as "nothing was built".
- A word-boundary escape (backslash and the letter b) in the "N years of experience" pattern of `analyze.py` had become a backspace character, so that check could never match.

## [1.6] — closed 2026-10-21 (first release of the toolkit, not yet published)

This release turns a personal job-search system (built over versions 1.0 to 1.5 for one person, one field and one country) into a toolkit anyone can
start from. The engine contains no knowledge of a person, a country or a field any more: it reads three small configuration documents that
`/start` writes from the person's CV and a few questions.

**Added**
- Onboarding. `/start` in Claude Code reads the CV, infers the person's field (categories, sub-fields, the words that identify them, what the CV proves),
  asks the questions only the person can answer (career stage, languages and levels, work authorization, where to search, who they would like to work
  for), researches the region when no pack ships, validates everything (`scripts/onboard.py check`) and starts the first search. See `docs/ONBOARDING.md`.
- Configuration layer (`scripts/config.py`): `profile/profile.json` (who), `profile/domain.json` (what), `regions/<code>/region.json` (where). Several
  region packs merge, home market first (`["de", "eu"]`). The rule version is a hash of the merged configuration: change the profile, the domain or the
  region and every analysed role is re-analysed and every score that moves is flagged.
- Region packs for Germany (`de`), Europe (`eu`) and the United States (`us`), each with route rules for work authorization, walls, boards, mail
  patterns, CV conventions and a legal note with sources; `regions/_template` and `rules/regions.md` for researching any other country.
- Generic analysis engine (`scripts/analyze.py`): language requirements checked against the person's own levels in 21 languages, walls from the region,
  domain and profile, classification by weighted terms, CV comparison, score with breakdown, verdict, dynamic re-scoring with flags.
- Three fictional example profiles with postings (`examples/`) that double as the test fixtures: a non-EU bioinformatics student in Germany, a new graduate
  on OPT in the United States, and an experienced EU citizen judging Dutch, French and German postings. `python scripts/onboard.py demo` shows the analysis
  without touching your data. Tests per behaviour in `scripts/tests/` (`run_all.py`), a CI workflow (`.github/workflows/tests.yml`) and shared Claude Code
  permissions (`.claude/settings.json`: the toolkit's own commands allowed, secrets unreadable, `git push` denied so nothing is published by accident).
- A guard: the analysis, intake and the unattended run refuse to judge postings for a person who has not been set up (`config.require_configured()`).
- The language ladder: a stated level two or more steps above the person's own is a wall, one step above caps the verdict at BACKUP (tested for B2 and C1
  asks against levels from A2 to native).
- Cross-platform scheduling (`scripts/scheduler.py`: Windows Task Scheduler, launchd, cron), `scripts/onboard.py doctor` (what each missing tool switches
  off), `scripts/privacy_scan.py` (checks that no personal data is in the tree or in a commit).
- Slash commands: `/start`, `/daily`, `/status`, `/review`, `/apply`, `/region`, `/mail`, `/phone`, `/schedule`, `/doctor`, `/digest`.

**Carried over from 1.0 to 1.5**
- 1.0: the tracker database (`scripts/db.py`) with the `my_notes` guard and version pinning, the daily scan, the CV and cover-letter toolchain
  (markdown to .docx, the anti-AI-tell checker, the structural checker, pagination, fingerprint, PDF render check) and the ship gate.
- 1.1: searching beyond the home market: country and route fields, language flags, an uncapped search.
- 1.2: the thesis table and pages, the institution watch (universities, institutes, hospitals through b-ite, RSS, SAP feeds and HTML lists),
  the role-word dictionary, the legal basis with route score adjustments, CV-only packages.
- 1.3: the redesigned dashboard (Today, Jobs, Thesis, Inbox, one stage model, drawer, themes, keyboard), the company and job-board watch
  (national board API, Workday, Greenhouse, Lever, SmartRecruiters, Recruitee), THE READING RULE and THE STRICT SCORING RULE (`ScoreWithoutJDError`).
- 1.4: maximum-range intake, the analysis stage with stored verdicts, the single definitions, the whole-system conductor (`scripts/pipeline.py`:
  stage registry, 30+ invariant checks, worklist, unattended run) and Gmail inside the pipeline (what was sent, acknowledged, rejected, invited,
  offered; alert mail; matched on employer and role).
- 1.5: the structured digest e-mail (HTML with a text part, sent once a day to the owner only), the phone inbox on Cloudflare (decide from a phone while
  the PC is off, decisions applied when it is back) with role details, a repair for defective cached postings.

**Changed when generalising**
- The owner of `my_notes` is now `source="owner"` (it was a person's name); the language column is `lang_bar` (it was a German-only column); the
  default country is `ZZ` (unknown) instead of a fixed one; the role kinds are `student_assistant`, `working_student`, `internship` (German words
  removed from the engine and kept in `resources/kinds.json` as one of many languages).
- `de_grammar_check.py` became `scripts/lang_check.py` (any LanguageTool language); `scripts/validate_blocks.py` reads the walls of the
  profile instead of one person's rules; CV headers, salutations and file-name words per language live in `resources/cv_headers.json`.
- Personal data and secrets never ship: `profile/`, `data/`, `jd/`, `applications/`, `db/tracker.db`, `config/` secrets and `remote/.dev.vars` are git-ignored
  and `scripts/privacy_scan.py` fails the build if one is found in the tree.

# job-watch.md: the company and job-board watch, and THE READING RULE

*Owns: how `scripts/job_watch.py` finds roles at employers, what it reads, how it classifies, and how a candidate becomes a tracker row. The institution side (universities, institutes, hospitals) is
`rules/institutions.md` / `scripts/uni_watch.py`; both feed the dashboard's Inbox.*

## What it reads (all without a browser or a login)

| Source | How | Coverage |
|---|---|---|
| National job board | the country's public job-search API where one exists: the region pack's `national_board` (shipped: the German Bundesagentur für Arbeit API, header `X-API-Key: jobboerse-jobsuche`, last 14 days). The queries are built from **your** field terms and the region's role words (`config.board_queries`) | every employer that posts there |
| Workday | `POST https://<tenant>.wd<n>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs` with 6 to 8 search terms | the employers in `profile/sources.json` |
| Greenhouse, Lever, SmartRecruiters, Recruitee | public JSON feeds | the employers in `profile/sources.json` |

`python scripts/onboard.py build-sources` fills `profile/sources.json` from `resources/employers.json` (verified endpoints, tagged by industry) for the industries in your `domain.json`. Employers not in that directory, or
whose portal is not one of these systems, stay in the normal board sweep (`rules/employers.md` says how to add one). Not every employer can be reached this way: own portals need the browser sweep.

## How it decides

1. **Level**, by title, with the role-word tables of `resources/levels.json` for the kinds you look for (`profile.levels_sought`: thesis, student_assistant, working_student, internship, trainee, entry, mid, senior). Titles
   with senior, director, manager, PhD or apprenticeship words are dropped unless they also carry a word of a level you want (the exclusion list is the same file; a profile that looks for senior roles loses the senior exclusions).
2. **On-topic** = one of your own fields (a `core` or `bridge` sub-field of `domain.json`, matched on the aliases), or an adjacent skill at an employer in your industry or on your priority list.
3. **Country** is read from the location text (`resources/countries.json`, the region's `country_hints`); roles outside the countries of your search are dropped from the Inbox (`--all-regions` keeps them); the route a role abroad
   would need is assessed when it is filed.
4. The provisional score reads **wording only**. The real 0-10 score comes from the opened posting.

## THE READING RULE

A watch hit is a title and a snippet. Nothing is ranked, filed or dropped from that. The flow is automatic up to the point that needs judgment:

1. **Intake files every posting at your levels** as an unscored row (a thesis as a thesis row), whatever its topic, and fetches the **full JD from the posting itself** into `jd/<Employer>_<slug>/description.md`
   (`scripts/intake.py`). A posting that cannot be read in full twice is kept as `unreadable` and never scored.
2. **The analysis reads the whole cached text** (`scripts/analyze.py run`): walls with the quoted sentence, the language levels, the deadline, category and sub-field, the comparison with the CV, the score with its breakdown,
   the **verdict** and its reason. All of it is stored on the row and shown on the dashboard.
3. **A Claude session reads the full JD of every best fit** (`analyze.py show <id>` prints it and records the read receipt), compares it with the CV and confirms or overrides (`analyze.py review`). Only then is the verdict
   `reviewed`. PASS, BLOCKED and EXPIRED verdicts from the script stand unless someone overrides them.
4. **Scores move, and say so.** Re-analysis each run compares with the stored score; every change (new JD text, new configuration, the 24-hour point expiring, a deadline passing) goes into `score_history` and sets
   `score_flag`. A reviewed verdict is never overwritten, only flagged.

## What it never does

It never writes the tracker. A role enters `db/tracker.db` through intake (a stub with the posting's own URL) and is judged only from its full text. Facts about a posting come from the posting page, never from the listing snippet.

## Running it

`python scripts/job_watch.py [--only workday] [--no-write] [--all-regions]` (a couple of minutes). Output: `data/jobwatch/<date>.json`, `data/jobwatch/seen.json`, `digests/job-watch-<date>.md`. The scheduled run calls it
once a day (`scripts/scheduler.py install`).

## Adding a source

Probe it first: a Workday site answers the POST above with a `total`; a Greenhouse board answers `boards-api.greenhouse.io/v1/boards/<slug>/jobs`. Add it to `profile/sources.json` only if it returned real data. Guessed slugs
mostly fail (about 2% of 730 guesses worked when this was measured), so check each one. `rules/employers.md` has the procedure.

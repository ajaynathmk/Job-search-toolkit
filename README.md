# Job-search toolkit

A job search that runs itself, set up for **you** by Claude Code from your CV.

Give it your CV and answer a few questions. It works out which field you are in, which country you are searching and what you are allowed to do there, then every day it reads your Gmail for replies and alerts, sweeps job boards and
employer career pages, **reads every posting in full**, scores it against *your* CV, and tells you what is worth your time. When you approve a role it builds a tailored CV and cover letter. It never submits anything: you do that.

It was built over several months by one person looking for work in Germany as a non-EU student, then generalised so that anyone, in any field and any country, can start from their own CV. Germany, Europe and the United States ship ready; for any other
country Claude researches the rules and writes the region pack with you.

> **What it will not do:** submit an application, send an e-mail to an employer, create an account for you, or invent a skill. The only mail it ever sends is a daily summary to your own address.

## The application (one command, only a CV)

```bash
python -m pip install -r requirements.txt
python app.py        # opens a page in your browser; or double-click start.bat / start.command
```

Give the page your CV. It works out your field, searches, reads every posting in full, scores it against your CV and shows you the jobs worth your time, with the reason for
each. It runs the judgment steps through **Claude Code on your Claude subscription** (no API key), everything stays on your computer, and nothing is ever sent to an employer.
Details, limits and troubleshooting: [docs/APP.md](docs/APP.md). The slash commands below do the same work from a Claude Code session, with more control.

## Requirements

| Needed | For | Check |
|---|---|---|
| Python 3.10+ and `pip install -r requirements.txt` | everything (core: flask, requests, beautifulsoup4, lxml, python-dateutil, pypdf) | `python app.py --check` |
| [Claude Code](https://claude.com/claude-code) on a Claude subscription | the judgment steps: reading your CV, reviewing best fits, tailoring CVs and letters | `python scripts/onboard.py doctor` |
| Node.js + `npm install` | building the `.docx` CV and cover letter (`scripts/build-cv.js`) | `doctor` |
| `python-docx` | page-layout checks on tailored CVs | `doctor` |
| Playwright (`playwright install chromium`) | LinkedIn / Xing postings and rendered job boards | `doctor` |
| Google API packages + your own OAuth client | read-only Gmail, the daily digest to yourself ([docs/GMAIL.md](docs/GMAIL.md)) | `doctor` |
| LibreOffice | rendering a package to PDF for the visual check | `doctor` |

Only Python and Claude Code are required; each other tool switches on one feature, and `doctor` tells you which.

## Quick start (in a Claude Code session)

You need [Claude Code](https://claude.com/claude-code), Python 3.10+ and Git. (Node.js, Gmail, LibreOffice and Playwright are optional; each switches one feature on.)

```bash
git clone https://github.com/ajaynathmk/Job-search-toolkit.git job-search
cd job-search
pip install -r requirements.txt
claude            # opens Claude Code in this folder
```

Then, inside Claude Code:

```
/start path/to/your-cv.pdf
```

Claude reads the CV, tells you what it understood, asks only what the CV cannot answer (career stage, languages and levels, your right to work, where to search, cities, employers you like), writes your configuration, tests it on real postings with you, and starts
the first search. A first run takes about 20 minutes, mostly your answers.

After that:

| Command | What it does |
|---|---|
| `/daily` | run the search now and work through what it found |
| `/review` | read the best fits in full against your CV and confirm or override each verdict |
| `/apply` | build a tailored CV and cover letter for roles you approved |
| `/status` | where things stand, and what needs you |
| `/mail` | settle job mail the script could not match |
| `/region <country>` | research a country and write its pack |
| `/schedule` | make the daily run happen by itself |
| `/phone` | approve roles from your phone when the computer is off |
| `/doctor` | which tools are installed and what each missing one would switch on |
| `/digest` | preview the daily summary e-mail (and send it to yourself) |

Try it without your own data first: `python scripts/onboard.py demo` analyses fictional postings for a bioinformatics student in Germany; `python scripts/onboard.py demo --example us-data-analyst` does the same for a data analyst on OPT in the United States.

## How it adapts to you

The engine knows no country, no field and no person. Everything comes from three small documents, written for you by `/start` and kept in the git-ignored `profile/` folder:

| Document | Says | Written from |
|---|---|---|
| `profile/profile.json` | **who** you are: career stage, kinds of role you want, languages and levels, work authorization, cities | your answers |
| `profile/domain.json` | **what** your field is: its sub-fields and the words that identify them, what your CV proves, priority employers, search terms | your CV |
| `regions/<code>/region.json` | **where** you search: boards, walls, how your right to work changes a score, mail patterns, CV conventions, with a legal note and its sources | a shipped pack, or one Claude researches |

The same posting is judged differently for different people: a posting that needs German at C1 is a wall for someone at A2 and a plain match for a native speaker; a role in Germany costs a non-EU student nothing at a university and a point elsewhere;
"no visa sponsorship" ends a search for someone who needs it and means little to a graduate with OPT left. If you change the configuration, every analysed role is re-analysed and every score that moves is flagged.

## What happens every day

```
mail (replies, rejections, invitations, alerts)  ┐
institution and employer watches, national board ├─► intake: every in-scope posting is filed, its FULL text fetched and cached
board sweeps in a Claude session                 ┘      │
                                                         ▼
        analysis: walls, language levels, deadline, field, CV comparison, score with its breakdown, verdict
                                                         │
        you or Claude: read the best fits in full  ─►  you approve on the dashboard (or your phone)
                                                         │
        Claude builds a tailored CV and letter, a quality gate checks them, you send them
```

- **Reads everything in full.** A title and a snippet tell you almost nothing. Every verdict comes from the whole posting, and the database refuses a score without the cached text, its hash and a score breakdown.
- **Honest about fit.** It lists what the posting asks that your CV covers, partly covers or lacks, and never upgrades "partly" to "covers".
- **Tailoring reorders; it never cuts and never invents.** Your CV's content is yours; a posting only changes the order and emphasis.
- **Links are verified.** A URL reaches your tracker only after the page was opened and named the employer and the role.
- **Gmail is read-only.** It sees what you sent and what came back, files rejections and invitations, and turns job-alert mail into rows. It never replies, labels or deletes.
- **Your dashboard** (`python scripts/webapp.py`, local only) and an optional **phone inbox** on Cloudflare's free tier.

## What is in this repository

```
app.py, start.bat, start.command   one-command web app (http://127.0.0.1:5057, local only)
scripts/                           the engine: intake, analyze, pipeline, db, job_watch, uni_watch, mail_sync,
                                   gmail_client, webapp, build-cv.js, the checkers (aicheck, consistency_check,
                                   lang_check, link_verify) and privacy_scan; scripts/tests/ holds the tests
rules/                             the written rules each stage follows; rules/pipeline.md is the entry point
regions/                           region packs: de, eu, us, and _template for a new country
onboarding/                        how a CV becomes a configuration (used by /start and the web app)
examples/                          fictional people for the demo (de-bioinformatics-student, eu-mechanical-engineer, us-data-analyst)
docs/                              setup and operation guides (APP, ONBOARDING, OPERATING, GMAIL, PHONE, PRIVACY, FAQ, ARCHITECTURE)
remote/                            optional phone inbox (Cloudflare Worker)
resources/                         CV header data and other static assets
db/schema.sql                      the SQLite tracker schema (the database itself is created locally, never committed)
.claude/commands/                  the slash commands: /start /daily /review /apply /status /mail /region /schedule /phone /doctor /digest
CLAUDE.md, AGENTS.md               instructions for Claude Code and other agents working in the repo
```

Created on your machine when you use it, and git-ignored: `profile/` (your configuration and CV), `db/tracker.db`, `jd/` (cached postings), `applications/` (CV and letter packages), `data/`, `digests/`, `logs/`, `config/` (tokens).

## Day-to-day commands

```bash
python scripts/onboard.py status | check | doctor | demo   # configuration and health
python scripts/pipeline.py status | queue | run            # the conductor: what is due, what ran
python scripts/intake.py run                                # file new postings and fetch their full text
python scripts/analyze.py run                               # score every unanalysed posting from its full text
python scripts/webapp.py                                    # the dashboard at http://127.0.0.1:5057
bash scripts/ship-package.sh <application-folder>           # CV + letter quality gate
python scripts/privacy_scan.py                              # run before any commit
```

## Troubleshooting

- **The page says nothing is configured:** give it your CV, or run `/start`. `python scripts/onboard.py check` lists what is missing.
- **Port 5057 is taken:** `python app.py --port 8080`.
- **A feature is switched off:** `python scripts/onboard.py doctor` names the missing tool.
- **Start over with a different CV:** delete `profile/` (and `db/tracker.db`, `jd/` if you want the old postings gone), then start again.

## Regions

| Pack | Covers | Notes |
|---|---|---|
| `de` | Germany | national job-board API, ~280 universities, hospitals and institutes, 140-day student work rules, post-study permits, CV conventions |
| `eu` | Europe beyond the home market | route rules for a non-EU student abroad (Erasmus+, Directive 2016/801), country notes with salary thresholds |
| `us` | United States | F-1 CPT and OPT, H-1B sponsorship, citizenship and clearance walls, resume conventions |
| anything else | Claude researches it | `/region <country>`: official sources only, dated, with what is unverified listed |

Use several together, home market first: `"regions": ["de", "eu"]`.

## Privacy

Your data never leaves your machine, with these exceptions that you choose: web searches Claude runs (field and country words only, never your name, e-mail, employers or CV text), Gmail (read-only, through your own Google OAuth client), and the phone inbox's snapshot (a list of
roles and their public text, behind your passphrase on your own Cloudflare account).

`profile/`, the tracker, cached postings, applications, `data/` and `config/` (tokens) are git-ignored. `python scripts/privacy_scan.py` checks that none of it, and no secret, is in the tree or in a commit. See [`docs/PRIVACY.md`](docs/PRIVACY.md).

## Documentation

[`docs/ONBOARDING.md`](docs/ONBOARDING.md) what `/start` does · [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) how it is built · [`docs/OPERATING.md`](docs/OPERATING.md) day to day · [`docs/GMAIL.md`](docs/GMAIL.md) · [`docs/PHONE.md`](docs/PHONE.md) ·
[`docs/PRIVACY.md`](docs/PRIVACY.md) · [`docs/FAQ.md`](docs/FAQ.md) · the rules in [`rules/`](rules/), starting with [`rules/pipeline.md`](rules/pipeline.md).

## Tests

```bash
python scripts/tests/run_all.py     # every test file and the privacy scan
```

## Contributing

A region pack for your country is the most useful contribution: `/region <country>`, then copy `profile/regions/<code>/` to `regions/<code>/`, check there is nothing personal in it, run the tests and open a pull request. Bug reports are welcome: include the
command, its output and `python scripts/onboard.py doctor`, and **never** paste your profile, tracker, mail or tokens. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Not legal or career advice

The region packs summarise public sources, dated and with their URLs, so that a score can reflect your right to work. They are orientation, not advice: verify every rule with the official authority before relying on it. A verdict is a recommendation from a script and an AI reading
a posting; you decide what to apply for.

## License

MIT. See [`LICENSE`](LICENSE).

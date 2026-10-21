# Operating the toolkit day to day

The whole flow, stage by stage, is `rules/pipeline.md`. This is the short version for the person at the keyboard.

## Once, to set it up

1. `pip install -r requirements.txt` (and `npm install` if you want CV and letter building).
2. `/start` in Claude Code (or `python scripts/onboard.py init` and edit the files by hand, then `python scripts/onboard.py check`).
3. `python scripts/onboard.py doctor` shows what is installed and what each missing tool would switch on.
4. Optional: `python scripts/scheduler.py install` (the daily run by itself), Gmail (`docs/GMAIL.md`), the phone inbox (`docs/PHONE.md`), job alerts (`rules/alerts.md`).

## What runs by itself

Once a day, when the computer is on: the audit, the Gmail pass (if set up), the institution and company watches, **intake** (every new posting filed as an unscored row, its full text fetched), the **analysis** of every row (walls, CV comparison, score, verdict; scores re-computed so moves are
flagged), the worklist, the phone sync (if set up) and the digest e-mail to your own address. `python scripts/pipeline.py run` does it by hand; it writes `digests/pipeline-<date>.md`, the brief for the next Claude session. It never submits anything and never mails anyone but you.

## What you do

Open the dashboard: `python scripts/webapp.py`, then http://127.0.0.1:5057 (local only; never bind it wider).

| Page | Use it for |
|---|---|
| Today | what needs you now: best fits, deadlines, packages ready, the pipeline bar |
| Jobs | the tracker, opening on **Best fits**; filters for verdict, category, tier, country, source; the detail panel shows the verdict, the CV match, how it scored, any score change; approve, recheck, not for me, applied, notes |
| Thesis | thesis leads and their status (students) |
| Review | best fits a Claude session still has to read against your CV, scores that moved, postings whose text could not be fetched |
| Mail | what Gmail says about your applications: mail that asks you to act, mail to settle, rejections and confirmations recorded, alert intake |
| Pipeline | every stage with live evidence, and the audit |

**Approving** a role asks the next Claude session to build its package (`/apply`). **Recheck** means something is wrong with the posting (read your note, fetch it again). **Not for me** closes it. Nothing is built or sent without your approval.

## What a Claude session does (the days the brief shows work)

`/daily` works the brief: mail first, then the board sweeps, then `/review` of the best fits (each one read in full), then `/apply` for approved roles, ending with a Gmail draft or a checklist: never a sent application.

## Commands

| Command | What it does |
|---|---|
| `python scripts/pipeline.py status` | every stage and when it last ran |
| `python scripts/pipeline.py check --tests` | the audit (C01 to C34) plus the unit tests |
| `python scripts/pipeline.py queue` | rebuild the worklist and the brief |
| `python scripts/pipeline.py run [--force] [--ignore-power]` | the unattended run now |
| `python scripts/intake.py run` | file every new watch posting, fetch its full text, analyse it |
| `python scripts/analyze.py run` | re-analyse every row (scores move and are flagged) |
| `python scripts/analyze.py show <id>` / `review <id> --verdict ...` | the Claude review with its read receipt |
| `python scripts/fetch_jd.py <id>` | verify the link and cache one posting (once) |
| `python scripts/link_verify.py --stale-days 30` | re-verify old links |
| `bash scripts/ship-package.sh <folder> [--cv-only]` | the CV and letter quality gate |
| `python scripts/scheduler.py install / remove / status` | the daily schedule |
| `python scripts/digest_email.py preview / send` | the digest e-mail |
| `python scripts/privacy_scan.py` | confirm nothing personal is in the tree |

## If the audit shows a FAIL

Fix it before more roles are scored or filed. Each result has a `fix:` line. The common ones: a role marked "read" with no JD file (re-run `fetch_jd.py`), a score with no cached JD (cache it and re-read), `VERSION` not matching the changelog.

## Backups

Your data is `profile/`, `db/tracker.db`, `jd/`, `applications/`, `data/` and `config/`: back those up (they are git-ignored, so Git will not). The rest of the repository you can re-clone.

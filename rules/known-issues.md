# known-issues.md: what is built, what is not, and what is untested

*Read this before assuming something runs unattended. Update it whenever a source breaks or a gap closes.*

## What is built and tested

- The tracker database and its guards (`scripts/db.py`; `scripts/tests/test_db.py`): `my_notes` ownership, the strict scoring proof, closed vocabularies, optimistic concurrency, the status-driven package folders.
- The configuration layer, the analysis engine and onboarding, on two fictional example profiles in two countries (`scripts/tests/test_analyze.py`, `test_onboard.py`, `test_pipeline_e2e.py`).
- The Gmail pass (`scripts/tests/test_mail_sync.py`), the dashboard API (`test_webapp.py`) and the phone inbox's offline rules (`test_remote_e2e.py`).
- The conductor and its audit (`python scripts/pipeline.py check --tests`).

## Needs a live setup on your machine (not verifiable from the repository)

| Piece | What it needs | Status until you do it |
|---|---|---|
| Gmail (replies, alerts, the digest e-mail) | a Google Cloud OAuth client and one browser click (`docs/GMAIL.md`) | the pass records "not set up", audit C28 warns; everything else runs |
| LinkedIn and Xing posting reads | Playwright with Chromium (`pip install playwright && playwright install chromium`) | those postings stay `unreadable` and are never scored |
| CV and letter building | Node.js and `npm install`, bash, optionally LibreOffice for PDF | no package can be built; scoring and review still work |
| The phone inbox | a free Cloudflare account and wrangler (`docs/PHONE.md`) | stage S31 shows "not set up"; nothing else depends on it |
| The daily schedule | `python scripts/scheduler.py install` | the run happens when you start it (`/daily`) |
| Master CV evidence | your own CV text, structured by `/start` | the analysis compares postings with the CV evidence in `domain.json`; an empty list means no comparison |

## Source health (things that change under you)

- **LinkedIn and Xing refuse plain fetches** (robots.txt) and may rate-limit or block a rendered browser; keyword searches there are attended-only. Alerts by e-mail are the dependable way in.
- **Indeed and Glassdoor** often refuse a plain fetch; use a browser or a connector. Glassdoor gives no per-posting URL.
- **A Google OAuth app in "Testing" mode loses its refresh token every 7 days.** Publish the consent screen to "In production" (personal use, only your own account) to stop that.
- **Cloudflare KV listing is eventually consistent** (up to a minute): a decision made seconds ago may wait for the next sync.
- **Applicant-system endpoints change.** A Workday site, a Greenhouse slug or a b-ite portal can move; the watch reports a source error in its summary and the audit flags a stale watch (C14, C15). Fix the entry in `profile/sources.json`.
- **Region packs age.** Salary thresholds, quotas and permit rules change every year. Each pack says when it was researched; refresh a country with `/region` before relying on a figure.

## Known gaps in the design

- **Autonomous sources are thinner outside Germany.** The shipped national-board API and the institution list cover Germany; `resources/employers.json` holds about 95 employer career feeds that answered with real postings when probed (life science, software, fintech, automotive, aerospace, health-tech), which cover a lot of
  entry-level and student hiring in the U.S. and Europe but not every employer. For other countries and employers, discovery comes from job-alert e-mail (`rules/alerts.md`), board sweeps in a Claude session and the employer procedure (`rules/employers.md`). `/start` adds feeds for the employers it finds in your field.

- The analysis reads text with patterns. It is conservative about walls (it quotes the sentence) but it can miss a requirement phrased in an unusual way and it can mis-read a negation. That is why every best fit is read in full by a session (S23) before anyone applies.
- Language-requirement detection covers 21 languages' anchors and the common level phrases; an unusual phrasing ("good command of") is treated as a soft requirement.
- Country detection uses city and region words: a location it cannot read becomes `ZZ` (unknown) and is judged on the text, not dropped. Add `country_hints` to your region pack for places it misses.
- The anti-AI checker's patterns are English. Other languages rely on the manual pass in `rules/language-quality.md`.
- Mojibake: a cached JD whose accents are garbled (UTF-8 read as Latin-1) is detected (audit C32) and re-fetched once.

## Reporting a problem

Open an issue on the repository with: the command, the output, `python scripts/onboard.py doctor`, and, if it is about a posting, the posting's URL. **Do not paste your profile, your tracker, your mail or any token.**

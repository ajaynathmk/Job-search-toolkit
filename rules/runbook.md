# runbook.md: the daily run's steps, budgets, THE LINK RULE, search mechanics

*Owns: the daily run's steps and budgets, the JD cache, the link rule, verification cadence, and the search mechanics. `rules/pipeline.md` owns the order and
ownership of the stages and wins on any disagreement about order. Where the search happens (which boards, URL templates, which employers) comes from the
owner's region pack (`regions/<code>/region.json` `boards`) and `profile/sources.json`; this file owns how.*

## The model split

If it is **reading** (fetching pages, scanning boards, extracting text), delegate it to a cheaper, faster model through the `Agent` tool and have it return
compact JSON: raw pages never enter the main context. If it is **judging or writing** (confirming a verdict against the CV, tailoring a CV, writing a cover
letter, the digest's prose), keep it in the main thread or give it to a stronger model. One browser context per subagent, never shared.

## Mechanical enforcement

- **`scripts/link_verify.py`**: opens a tracker row's `url` (or a candidate) right now, reads the page text and writes `url_verified` only if it names both the
  employer and the role. LinkedIn and Xing go through the Playwright context of `scripts/browser_jd_reader.py` (a plain fetch is refused by their robots.txt: never
  try one); every other host uses a plain GET. `--stale-days N` re-verifies every open row whose check is missing or older than N days.
- **`scripts/fetch_jd.py`**: the JD-first rule for one role: refuses if `jd_read=1` already (the one licensed exception is `--recheck`), verifies the link and saves
  the text to `jd/<Employer>_<role-slug>/description.md` in the same call, and writes `jd_read=1` only after the file demonstrably exists.
- **`scripts/intake.py`** does both for everything the watches find, and the analyser (`scripts/analyze.py`) scores from the saved text only.

## THE LINK RULE: no unverified URL ever reaches the owner

The `url` on a card opens the individual posting, for a human, in one click, and is written only after that exact page has been opened and read in this run.

**Never stored:** a search-results page, a careers landing page, an aggregator's copy when the employer's own posting can be found, a tracking or redirect link, or any
guessed URL. **Verification means:** open it, read the text, confirm it names both the employer **and** a matching role title. A 404, a login wall or a different role is not
verification. **Search order:** the employer's own careers site, then its applicant system (Workday, SuccessFactors, Greenhouse, Personio, ...), then the originating
board only if it exposes a per-posting URL. **On failure:** leave the old `url`, clear `url_verified`, name what was tried. **If demonstrably gone** (the employer's own
board does not list it): close the card (`status="rejected"`) rather than leaving a dead role in a slot. **Budget:** 3 page opens per role, one fallback host.
**One exception:** a card created from an inbox reply for a role that was never posted publicly may carry a careers landing page.

## The JD-first rule, unconditionally

A role is never tailored or recommended from its title. The JD is read exactly **once**, on the day the role is found, for every role added to the tracker, and cached in
full as `jd/<Employer>_<role-slug>/description.md`. Every later step (tailoring, rechecks, answering a question) reads that cache. Re-fetching a JD whose row says
`jd_read=1` is a bug. The licensed exceptions: a recheck, and a cached JD found to be **defective** (accents garbled, or a page whose text is mostly other postings),
which `python scripts/intake.py repair` fetches again (audit C32). A row may not reach `jd_read=1` without the raw text saved to that file.

## The daily run, step by step

Mapping to the stages of `rules/pipeline.md`: step 1-2 = S00/S20, 3b = S10, 4 = S11, 5-6 = S12, 5b = S13, 5c = S14 and S15, 6-7 = S20-S23, 8 = S40-S42, 9 = S50, 10-11 = S51.

| Step | Who | What happens |
|---|---|---|
| 1 | main thread | Load state: this file, `profile/profile.json`, `profile/domain.json`, `data/pipeline-state.json`. Nothing else up front. |
| 2 | main thread | Read the tracker through `scripts/db.py`'s filtered `list_jobs()`: never a full dump into context. |
| 3 | reading subagent | Liveness-only verification on a cadence (deadline within 7 days or past; 8 to 30 days and not checked in 3 days). Max 5. Never re-reads the description. |
| 3b | script | `python scripts/mail_sync.py run`: replies, rejections, invitations, what the owner sent. Read only. |
| 4 | script | The same pass files the alert mail (LinkedIn and the region's boards) as unscored stubs. |
| 5 | reading subagent | Board sweep with the region's boards and the owner's search terms (`profile/domain.json` `search_terms`, `rules/search-terms.md`); WebSearch for employer pages. |
| 5b | reading subagent | Wider-region sweep: the other countries in scope, in their local languages (`rules/regions.md`), with the route each role would need. |
| 5c | script | The watches: `uni_watch.py` (institutions) and `job_watch.py` (national board, Workday, ATS feeds). They never write the tracker. |
| 6-7 | script | `intake.py run` then `analyze.py run`: stubs, full JDs, walls, verdicts. |
| 7b | main thread | Review the best fits (`/review`): read the full JD against the CV, confirm or override. |
| 8 | writing subagent | Load `rules/applications.md`, `rules/cv-build.md`, `profile/master-profile.md`. Rechecks first (max 3), then approvals (max 2, liftable when the owner is present and asks): read `my_notes` first, re-check the walls, build the full package, a Gmail **draft** (never attached, never sent) for e-mail channels or a checklist for portal channels. **Never submits anything.** |
| 9 | script | The digest e-mail (`scripts/digest_email.py send`), always sent to the owner's own address, once a day. |
| 10-11 | script | Write back: tracker, JD cache, `data/jobs-master.csv` (append-only), state files. `my_notes` untouched. |

### Standing rules that are never traded away for cost

- The digest always goes out, even with zero hits.
- **Never submit anything.** Drafts, never sends. Never touch a portal with the owner's data. Never create an account. An approval flag is not consent to submit.
- Every role is ranked from its own JD, never its title. A JD is fetched once. The link rule, unconditionally.
- `my_notes` is never written or cleared by automation. An employer's e-mail is read and recorded, never replied to or acted on.
- The coverage line always states the truth: a source that did not run is named, not hidden.

## Budgets

| Budget | Value |
|---|---|
| Board page fetches, WebSearch queries, watch sources | uncapped (pace a single board politely: several seconds between fetches) |
| First-time JD reads and link verification | no cap (paid once per role, ever) |
| Re-reads of a cached JD | 0 (except a recheck or a defective cache) |
| Page opens verifying one link | 3, one fallback host |
| Liveness-only verifications | 5 |
| Rechecks | 3, oldest first |
| Approval packages | 2, oldest first (liftable when the owner is attended and asks) |
| Fetch attempts per JD | 2 (canonical route, then one fallback) |
| Roles named in the digest | 8 top picks, 15 compact, 8 carry-forward |

## Search mechanics

- **Gmail.** `python scripts/mail_sync.py run` runs the reply and alert queries (see `rules/mail.md`). The region pack adds its own boards' alert senders.
- **LinkedIn.** Reading a posting: `https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/<id>` in a rendered browser context (`scripts/browser_jd_reader.py`), selector
  `.description__text, .show-more-less-html__markup, section.description`. The stored `url` is the human-facing `https://www.linkedin.com/jobs/view/<id>` with every tracking parameter
  stripped. Keyword **searches** on LinkedIn run only when the owner is present and never from an unattended run, and never in a logged-in context. Alerts are better: see `rules/alerts.md`.
- **Other boards.** The URL templates are in the region pack (`boards`); `{kw}`, `{city}` and `{country}` are filled from the profile. Several boards give no per-posting URL (an
  aggregator): find the employer's own posting before filing anything (THE LINK RULE).
- **Employer career sites.** Prefer the applicant system's own feed (`profile/sources.json`; `rules/employers.md` for adding one) over scraping a careers page.
- **WebSearch.** Use it for employer pages and for roles that only exist on the employer's site. Never use it to find LinkedIn postings: results surfaced that way are months stale.
- **Rendered-browser budget.** One browser context per run for LinkedIn and Xing; if navigation is refused or a permission is demanded, try once more, then switch that source off for the run
  and say so in the coverage line: never fight a permission prompt repeatedly.

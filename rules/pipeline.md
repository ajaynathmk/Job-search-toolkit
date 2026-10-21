# pipeline.md: the whole system, start to end

*Owns: the order of the stages, who does each (a script, a Claude session, the owner), what each reads and writes, the gate between stages, the verdicts,
and the definitions every part must agree on. The conductor is `scripts/pipeline.py`; `python scripts/pipeline.py status` shows the stage table live.
If this file and `runbook.md` disagree about order, this file wins; the runbook owns the search mechanics and budgets.*

"The owner" is the person whose search this is (`profile/profile.json`). Nothing here is specific to a country or a field: those come from the
configuration (`profile/`, `regions/`, see `docs/ARCHITECTURE.md`).

## The flow

```
 P0 PREFLIGHT   S00 audit the invariants ---------------------------------> a FAIL stops intake and review
 P1 COLLECT     S10 GMAIL: replies, rejections, invitations, what I sent    S11 GMAIL: alert mail -> unscored rows    (script, every run)
                S12 board sweep   S13 wider-region sweep                      (Claude session)
                S14 institution watch   S15 company watch   S16 thesis sweeps (script, once a day; S16 on request, students only)
                     |  candidates only
 P2 INTAKE AND  S20 INTAKE: every in-scope posting becomes a tracker row, UNSCORED, and its FULL JD is fetched and cached
    ANALYSIS         (nothing is dropped for being off-topic; unreadable twice = kept, never scored)
                S22 ANALYSE: a script reads the whole cached JD: walls, language levels, deadline, field, CV comparison,
                     score with its breakdown, VERDICT and reason; re-run every day so scores move and every move is flagged
                     |  every row now carries a verdict, a reason, a CV match and a score breakdown
 P3 REVIEW AND  S23 REVIEW: a Claude session reads the full JD of every best fit (APPLY, BACKUP, PLAN, LATER) against the CV and confirms or overrides
    DECIDE           (a read receipt is required; the script never overwrites a reviewed verdict, it only flags a disagreement)
                S30 the owner on the dashboard: approve / recheck / not for me / applied
                S31 PHONE INBOX (optional, Cloudflare): the same decisions made on a phone, applied here at the next run
                     |  approval=requested|recheck
 P4 BUILD       S40 tailor (reorder only) --> S41 ship gate --> S42 draft or checklist (never send)
                     |  approval=prepared
 P5 REPORT      S50 digest e-mail (always sent, to the owner only)   S51 write back + CSV mirror   S52 version / export (on request)
                     ^                                                              |
                     +---- mail (S10) moves status; the package folder follows status ----+
```

Run `python scripts/pipeline.py status` for every stage with its owner, command, what it reads and writes, its gate, and live evidence of when it last ran.

## Intake (S20): `python scripts/intake.py run`

For every posting the watches (and the alert mail) found at the levels the owner looks for, in a country the search covers, and not yet in the tracker
(matched by URL and by `watch_id`):

1. **File a stub.** A job row (a thesis row for a thesis) with `analysis_level='stub'`, no score, no verdict, the watch id, the posting's date.
2. **Fetch the full JD from the posting itself**: the national job board's API, Workday, Greenhouse, Lever, SmartRecruiters and Recruitee APIs, PDF
   (decided by the file's own bytes), plain HTML, or the page's own structured data. It is saved to `jd/<Employer>_<slug>/description.md`. `jd_read=1` and
   `jd_path` are set only after the file exists with real text (500+ characters, readable, not binary). `url_verified` is set only when the fetched text
   carries the posting's title (THE LINK RULE).
3. **Two attempts.** A site that blocks or rate-limits the request is a deferral and does not use one up. A cached JD found to be defective (garbled accents,
   or a page full of other postings) is fetched again by `python scripts/intake.py repair`; audit C32 lists them. A posting that cannot be read in full twice
   becomes `unreadable`: it stays visible and is never scored.
4. **Analyse** the new rows (S22).

Nothing is filtered by topic: the topic is decided from the full text. Index pages, rules documents and topic lists are filed too and come out of the analysis
as PASS ("not a posting").

## Gmail (S10, S11): `python scripts/mail_sync.py run`

One read-only pass over the mailbox (rules/mail.md has the detail):

- **S10, what happened to my applications.** Mail the owner sent and mail received from employers and their applicant portals is classified
  (acknowledgement, rejection, invitation or assessment, offer, request for documents) and matched to a tracker row on **employer AND role** (a personal address or
  a reference number beats both). `applied` / `interview` / `rejected` are set with `status_source = "gmail <date>"`; a rejection always wins, a status the owner set
  by hand is never downgraded, `skip` is left alone. A weak match may confirm an application but never rejects or invites; an offer is never applied by the script.
- **S11, what is new.** LinkedIn and the region's job-board alert mail is parsed; every posting the tracker does not know is filed as an unscored stub and the next
  intake pass fetches its full JD. Nothing is scored from an email.
- If Gmail cannot be read the run does not skip silently: the error is recorded, audit C28 turns to WARN and the Mail page and the brief say so.

## Analysis (S22): what the script reads and decides

`python scripts/analyze.py run`. From the whole cached text, for every row, using the owner's configuration:

- **Walls** (quoting the sentence): the region pack's (security clearance, citizenship, "no visa sponsorship" for someone who needs it), the domain file's and
  the profile's own (a named degree the owner is not enrolled in, a credential they lack). A country outside the search is a wall too.
- **Languages**, checked against the levels in `profile.languages`: a stated level two or more steps above the owner's is a wall; one step above caps the verdict at
  BACKUP; an unquantified "very good X" costs a point; "native or at least B2" counts as B2; a language the search does not track is a flag (`language_bar`), not a wall.
- **Deadline** parsed from the text; a passed one is EXPIRED.
- **Category and sub-field** (`profile/domain.json`) by weighted terms in the title and body.
- **CV comparison** (`domain.cv_evidence`): what the posting asks for that the CV covers, covers only partly, or lacks, each marked *required* or *nice to have*.
- **Score**: core field +4, bridge field +2, priority employer +2, posted within 24 hours +2, preferred city or remote +1, language fit +1, a language level above the
  owner's -1, penalty sub-fields -2, unrelated industry -2, administrative tasks -2, evidence bonuses +1, then the **route adjustment** of the work-authorization
  rules of the region pack. The components are stored as `score_breakdown`.
- **Verdict** and a one-paragraph reason, shown on the dashboard.

### Verdicts

| Verdict | Meaning | Typical case |
|---|---|---|
| APPLY | In the owner's field, can be taken now, worth applying to first | core field, in a primary country, a kind of role the owner looks for, score at or above tier 2, no wall |
| BACKUP | A weaker fit or an income option | adjacent field or a stretch (required skills missing, a language one level up), or an unrelated role the owner accepts for income |
| PLAN | In the field but abroad or later: needs a plan | core field in a country that is in scope but not primary, with a route to arrange |
| LATER | In the field but not the kind of role sought now | a senior role for a student, or a thesis for someone who is no longer a student: a target for later |
| PASS | Read in full and not a fit | outside the field, or not a posting at all |
| BLOCKED | A wall in the posting | a language level, a credential, a clearance, a citizenship, no sponsorship |
| EXPIRED | The deadline has passed | |

`APPLY`, `BACKUP`, `PLAN` and `LATER` are the *best fits*: a Claude session must confirm them (S23).

## Review (S23): reading the best fits against the CV

`python scripts/analyze.py show <id>` prints the **full** JD, the CV comparison and the script's analysis, and records a read receipt (kind, id, JD hash,
reader, time). Then `python scripts/analyze.py review <id> --verdict APPLY|BACKUP|PLAN|LATER|PASS|BLOCKED --reason "..." [--score N --category c --subfield s]`
writes `analysis_level='reviewed'`. The database refuses a reviewed verdict without a receipt for that exact text. A reviewed verdict is never overwritten by the
script: if a re-analysis disagrees materially (a different verdict, a score that moves by 2 or more, or a changed JD) it sets `score_flag` and the row shows up
under Review, "Scores that moved".

## The strict scoring rule, in code (`scripts/db.py`)

Any write to a judgment field (`score`, `tier`, `verdict`, `verdict_reason`, `category`, `subfield`, `cv_match`, `score_breakdown`; for a thesis also
`fit_score`, `route_adjustment`) on a job **or a thesis row** must carry the proof of the read, or `ScoreWithoutJDError` is raised: the full JD cached (500+
characters); `jd_sha` equal to the hash of the cached file now; `analysis_level` `auto` or `reviewed`; a `score_breakdown` with any score; and, for `reviewed`, a Claude
read receipt. `source="rollback"` restores an earlier value; clearing a field needs no proof.

## Scores are dynamic

Every pipeline run re-analyses all analysed rows. A score can move because the JD changed (hash), because the configuration changed (`definitions.RULE_VERSION`
is a hash of profile + domain + region + engine), or because time passed (the 24-hour point goes, a deadline passes). Each move is appended to `score_history`
with its trigger and sets `score_flag`, which the dashboard shows on the row and under Review. The audit lists them (C22).

## Definitions (one source: `scripts/definitions.py`)

Stages (a data table: status, approval and analysis level give one stage), the owner's categories and sub-fields, verdicts and their colours, analysis levels, the
windows (watch freshness, link age, deadline soon), the caps (rechecks and approvals per run), the tier thresholds, and what intake takes. The pipeline, the analyzer,
intake and the dashboard (`/api/definitions`) all read it; nothing else defines them.

## The audit (S00): `python scripts/pipeline.py check [--tests]`

Read-only checks C01 to C34: scored without a JD or proof, JD changed after analysis, older rules, stubs, unreadable JDs, best fits not yet confirmed, scores that
moved, packages built for roles the analysis says are not a fit, `jd_read` with no file, unverified or dead links, prepared-but-blocked rows, missing package files,
deadlines, missing category, tier/score mismatch, thesis leads without text, stale watches, the review log vs the tracker, VERSION vs CHANGELOG, the unit tests, Gmail
health, the digest, the phone inbox. A FAIL stops intake and review until fixed; WARN and INFO go into the brief.

## The worklist and the brief: `python scripts/pipeline.py queue`

Writes `data/queue.json` and `digests/pipeline-<date>.md`: new watch postings not filed yet, stubs waiting for a JD, unreadable ones, the best fits to confirm,
flagged reviewed rows, packages ready (and how many the analysis says are not a fit), deadlines within 7 days, rechecks (max 3) and approvals (max 2).

## When it runs

| What | When | How |
|---|---|---|
| S00, S10, S11, S14, S15, S20, S22, worklist, S31, S50, S51 | once a day, when the computer is on | `python scripts/scheduler.py install` (Windows Task Scheduler, launchd or cron); `python scripts/pipeline.py run` skips if it already ran today or the computer is on battery (`--force`, `--ignore-power` override) |
| S12, S13, S16, S23, S40, S42 | in a Claude session, the day the brief shows work | `/daily`, `/review`, `/apply` |
| S30 | whenever the owner opens the dashboard | `python scripts/webapp.py` (127.0.0.1:5057) |
| S41 | per package, after S40 | `bash scripts/ship-package.sh <folder> [--cv-only]` |
| S52 | only when the owner says so | close the version in CHANGELOG, set VERSION |

## The non-negotiables that gate the stages

1. **Strict scoring rule** and **reading rule**, in code as above.
2. **THE LINK RULE** and **JD-first**: a URL counts as verified only when the fetched text carries the posting's title; a JD is fetched once.
3. **Never submit**, never touch a portal with the owner's data; `my_notes` is the owner's alone (`MyNotesGuardError`).
4. **Tailoring reorders**, never cuts or invents.

## Failure handling

A stage that cannot run says so in the brief and the coverage line; nothing is faked. An unreadable posting is retried once and then listed, never scored. A FAIL in the
audit is fixed before more rows are scored. A scheduled run that finds the computer on battery does nothing and is retried.

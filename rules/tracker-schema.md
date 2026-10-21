# tracker-schema.md: the database shape, ids, approval states

*Owns: the tracker's database shape, id scheme, note fields, approval states, the `keywords[]` schema. The state lives in `db/tracker.db`, a local SQLite
file, one row per role, accessed only through `scripts/db.py`. `db/schema.sql` has the literal column definitions this file describes in prose.*

## Where the state lives

Two tables you work with: `jobs` and `thesis`, plus `mail_events` (facts about job-related e-mail) and `jd_reads` (read receipts). Read and written only through
`scripts/db.py`'s functions, never a raw `UPDATE` or `INSERT` from other code. `python scripts/db.py` creates the database from `db/schema.sql` if it does not exist.
`db/tracker.db` is git-ignored: it is the owner's data.

## Id scheme

- `li-<id>`: LinkedIn job id. `xi-<id>`: Xing numeric id. `xm-<token12>`: last 12 characters of a Xing mail-redirect token, for roles that only ever arrived by e-mail.
- `w-<slug>`: slugified employer + title (watches, boards with no stable id), also used for applications found in the owner's inbox that no scan surfaced as a posting.
- `th-<institution>-<slug>`: a thesis row.

## Field groups on every card

- **Country and route**: `country` (ISO-2, `ZZ` = unknown until the location is read, validated in `scripts/db.py`), `work_route` (closed vocabulary: the route ids of the owner's
  region pack, plus `none_found` and `unknown`), `language_bar` (other languages the posting asks for: a flag shown on the card, never a block), `lang_bar` (the local-language
  requirement the analysis found, e.g. "C1 or above (or native): ..."). `list_jobs(country=...)` filters.
- **Classification**: `category` and `subfield`, both validated against the owner's `profile/domain.json`; `field` and `track` are legacy free fields.
- **The analysis record** (the same columns exist on `thesis`): `verdict` (APPLY, BACKUP, PLAN, LATER, PASS, BLOCKED, EXPIRED), `verdict_reason`, `cv_match` (JSON: what the CV covers,
  partly covers, lacks, each required or nice to have), `analysis_level` (stub = filed unscored, auto = a script read the full JD, reviewed = a Claude session did, legacy = scored before this
  record existed, unreadable = the JD could not be fetched in full), `analyzed_at`, `jd_sha`, `score_breakdown`, `score_history`, `score_flag`, `rule_version`, `posted_at`, `watch_id`.
- **Identity**: title, employer, location, tier, score, source, date_found, status. **A score, tier, verdict or category is written only with the proof of the read** (the full JD cached,
  its hash, the analysis level and the breakdown), otherwise `update_job()` / `create_job()` raise `ScoreWithoutJDError`. `source="rollback"` restores an earlier value only.
- **Link**: `url`, `url_verified`, `ref_number` (THE LINK RULE, `rules/runbook.md`).
- **Dates and urgency**: deadline, start_window, duration, action_by, urgency_reason, rolling, verify_needed, last_checked.
- **Workflow**: approval, approved_at, recheck_at, blocked_reason, package_path, apply_channel, apply_url.
- **Mail events**: table `mail_events` (one row per job-related message: id, direction, kind, confidence, sender, subject, date, matched `job_id` / `thesis_id`, `state`
  new|applied|already|unmatched|needs_read|acted|dismissed, `judged_by`). Facts about the mail, never its body. Written only by `scripts/mail_sync.py` (`rules/mail.md`).
- **Outcome**: applied_at, closed_at, status_source (`"gmail <date>"` when the run moved it, empty when the owner did).
- **JD cache**: jd_read, jd_fetched_at, jd_path, jd_lang, jd_summary (120 words at most), hard_reqs[], soft_reqs[], `keywords[]` (structured, below), constraints, contact_name.
- **Notes**: `notes` (the run's findings, freely overwritable) and **`my_notes` + `my_notes_at`** (the owner's field, and only theirs: never written, never cleared by automation; enforced
  by `scripts/db.py`'s `MyNotesGuardError`, which allows the write only with `source="owner"`).

`status` is one of open (default), applied, interview, rejected, skip.

## `package_path` folders sort themselves by status

A package's folder always lives under `applications/` in the subfolder matching its own `status`. `update_job()` enforces this in the same single write path that guards `my_notes`:
whenever a call changes `status` (the dashboard, a Gmail-detected rejection, a scan) it moves the folder and rewrites `package_path`.

| status | folder |
|---|---|
| `applied` | `applications/Applied/<folder>` |
| `rejected` | `applications/Rejected/<folder>` |
| `skip` | `applications/Skip/<folder>` |
| `open`, `interview` | `applications/<folder>` (top level: still active) |

The move is best-effort and silent on the edge cases (no `package_path`, the folder already moved by hand, something already at the destination: never overwritten).

## `keywords[]`: structured, not a flat list

```json
{"term": "differential expression", "category": "method", "tier": "must", "pillar": "genomics", "frequency": 3, "source": "hardReqs"}
```

`tier` is mechanical: **must** = in a required section, or 3+ occurrences anywhere; **preferred** = in a nice-to-have section, or once or twice without required placement; **context** = a
generic soft-skill term. Set once at discovery, read (never recomputed) at every later step.

## Approval states

| State | Set by | Means |
|---|---|---|
| `none` | default | Not actioned: shown in "Needs your call" |
| `requested` | **the owner** | They pressed Approve: build the package |
| `prepared` | the run | Package built; the card names the folder |
| `recheck` | **the owner** | Something is wrong: read their note, re-fetch (the one licensed re-read), come back on it |
| `blocked` | the run | A wall found at discovery, quoted in `blocked_reason` |

`status` moves independently of `approval` (hand actions, the mail pass, the run closing a proven-dead posting). **A status the owner set by hand is never downgraded by an incoming e-mail**
(interview beats a mere acknowledgement); a rejection always wins.

## The three actions, always in the same order

1. **Approve & prepare** sets `approval="requested"`. 2. **Recheck** sets `approval="recheck"`, served before approvals on the next run. 3. **Reject** sets `status="rejected"` and clears any pending
requested/recheck. On a blocked card, action 1 reads **Approve anyway** and overrides the block.

## Reading the one note box correctly

| Action taken | The note is... |
|---|---|
| Approve | a **briefing** for the drafting |
| Recheck | the **problem** to investigate |
| Reject | the owner's **reason**, kept for the record |
| (nothing) | standing context: honour it next time the role is touched; answer a question from the cache, never by reopening the posting; never build a package from this alone |

## Concurrency

The `version` integer column pins writes: `update_job(expected_version=...)` compares and swaps on it, so a write against a stale version raises `StaleWriteError` instead of overwriting a change made
since the read.

## CSV export

`scripts/db.py`'s `export_csv()` writes `data/jobs-master.csv`, an append-only mirror for spreadsheets, with a real quoting `csv.DictWriter` (an unquoted comma once shifted every column of a hand-written export).

## The `thesis` table (students)

One row per thesis opportunity, kept apart from `jobs` because a thesis needs a group and supervisor profile, the page's own wording and a reasoned fit. Written only through `scripts/db.py`
(`create_thesis`, `update_thesis`, `get_thesis`, `list_thesis`), with the same guards as `jobs`. Ignore it if you are not a student.

| Group | Columns |
|---|---|
| Posting as on the site | `title` (exact), `institution`, `department`, `group_name`, `location`, `country`, `source_type`, `posting_kind`, `posting_url`, `url_verified`, `posted_at`, `deadline`, `start_window`, `duration`, `posting_text` (verbatim), `requirements` (verbatim), `language_bar` |
| Supervisor and group | `pi_name`, `pi_title`, `pi_email`, `pi_page_url`, `contact_name`, `contact_email`, `group_url`, `group_summary`, `pi_work_summary`, `publications` (JSON) |
| Fit | `pillar` (an id from `domain.thesis_pillars`), `fit_score` (0-10 content), `route_adjustment`, `score` (= fit + route, clamped 0-10), `fit_reasoning` (tied to master-profile evidence ids), `gaps` |
| Legal | `work_route`, `route_note` |
| Workflow | `status`, `outreach_draft_path`, `outreach_sent_at`, `replied_at`, `jd_path`, `source_ref`, `last_checked`, `notes`, `my_notes`, `my_notes_at`, `version` |

`posting_kind`: `advertised`, `topic_list`, `open_call`, `lead`. `status`: `lead`, `outreach_drafted`, `outreach_sent`, `replied`, `interview`, `accepted`, `declined`, `closed`. Outreach is drafted only (never sent).

**What a thesis row must contain before it exists:** the page was opened and read; the quoted `posting_text` and `requirements` are what the page says; the group and supervisor text comes from their own
pages; publications come from PubMed or the group's page (cite the DOI); the fit reasoning names evidence ids and gaps. A supervisor's e-mail comes from the page itself, never from a search snippet.

# mail.md: Gmail inside the pipeline (stages S10 and S11)

*Owns: what the pipeline reads from Gmail, how each mail is classified and matched to a tracker row, which status moves and which never do, how alert mail becomes unscored rows, and what happens when Gmail cannot
be read. The code is `scripts/mail_sync.py`; Gmail access is `scripts/gmail_client.py`; setup is in `docs/GMAIL.md`.*

## What runs

`python scripts/mail_sync.py run`: one pass, read-only. It is called by the unattended run (`pipeline.py run`, stages S10/S11, before the watches) and by hand. The window is 45 days on the first run, then "since the last
read plus a margin". Fetched messages are cached once under `data/mail/msg/` (git-ignored: mail is personal) and never fetched twice.

**Gmail is only ever read.** The pass never replies, forwards, labels, trashes, marks or sends. The one write path in `gmail_client.py` for mail leaving the account is the digest to the owner's own address
(`profile.email`), and this stage does not touch it.

**Only job mail is kept.** The searches are targeted (sent mail about applications, applicant-portal and ATS senders, application subjects, alert senders) and classification drops the rest (banks, shops, newsletters,
account set-up, one-time passwords) before anything is stored. An event row in `mail_events` holds the Gmail id, sender, subject, date, the classification, the match and what was done: never the body.

**Languages.** The built-in patterns cover English and German. `resources/mail_patterns.json` adds French, Spanish, Italian, Dutch and Portuguese; your own wordings go in `profile/mail_patterns.json` (same
keys: `rejection`, `ack`, `interview`, `offer`, `info_request`; lists of regular expressions). The region pack adds its boards' alert senders (`region.mail`), and `profile.mail.ignore_senders` / `ignore_recipients`
silence senders that are not job mail. Keep a rejection pattern specific: one that also appears in an acknowledgement turns acknowledgements into rejections.

## S10: classification

| Kind | Meaning | Status effect |
|---|---|---|
| `sent_application` | the owner sent an application or an outreach mail | `open` to `applied` with `applied_at` = the mail date; thesis to `outreach_sent` |
| `ack` | the employer or its portal confirms receipt | `open` to `applied` (a confirmation proves it was sent) |
| `rejection` | "unfortunately ...", "not selected", "not moved forward", "language level required" | to `rejected`, `closed_at` = the mail date; thesis to `declined` |
| `interview` | an ACTIVE invitation: an interview, an assessment link, "schedule your interview" | to `interview`; listed under ACT NOW |
| `offer` | offer or contract wording | **never applied by the script**: always read by a session first; listed under ACT NOW |
| `info_request` | an explicit ask: upload a transcript, update the profile by a date, confirm the application | no status change; listed under ACT NOW with its date |
| `other_job` | job mail with no clear signal | read by a session |

A sentence that only describes the process ("if we receive positive feedback we will invite you to an interview") is not an invitation: conditional sentences are ignored. A footer that mentions transcripts or
permits is not a request.

## S10: matching a mail to a row

A mail names its role only sometimes, and the tracker holds look-alike rows (one posting filed from two boards, many roles at one employer). So a match needs evidence, in this order:

1. **A reference number** in the mail that is the row's.
2. **A personal address** (not a shared inbox such as `careers@`, `noreply@`, `recruiting@`): the professor or recruiter you wrote to.
3. **Employer and role**: a distinctive employer word in the subject, sender or start of the mail (a word few employers and few titles share; "life", "science", "medical", "data" are not employers), AND the mail repeating at
   least 60% and two words of the row's own title.
4. **Weak matches** (an employer with one row only, one role word, the only applied row among equals) may confirm an application but **never reject or invite**.

If the evidence does not single out one row the event is `unmatched` (the candidates are listed) or `needs_read`; a Claude session reads the whole mail (`python scripts/mail_sync.py show <msg_id>`; `explain <msg_id>` shows the
scoring) and decides with `python scripts/mail_sync.py judge <msg_id> --kind rejection --job <row id> --note "why"`. A judged event is final (`judged_by = claude`).

## S10: the status policy

- A rejection always wins. An acknowledgement never downgrades `interview` or `rejected`. An invitation arriving for a row already `rejected` is not applied; a session reads both mails.
- A status the owner set by hand is never downgraded (`interview` beats a mere acknowledgement). `skip` ("not for me") is left alone: the mail is recorded, nothing moves.
- `status_source` records `gmail <date> (<kind>, <how matched>)`. The package folder follows the status automatically (`tracker-schema.md`). `my_notes` is never written.
- Every mail is processed once; running the pass again changes nothing.

## S11: alert mail becomes unscored rows

LinkedIn (`jobalerts-noreply@`, `jobs-noreply@`, "is hiring"), the region's boards (`region.mail.alert_senders`) and employer career alerts. Each posting in the mail is parsed (title, employer, place, id). Every one at a level
the owner looks for that the tracker does not already hold (matched by URL, by `watch_id`, and by employer plus title) is filed as an unscored stub through `intake.make_stub` with `watch_id = mail-<source>-<key>`. The next
intake pass (S20) fetches the full JD and the analyser (S22) reads it: **nothing is scored from an e-mail**. Roles at other levels are counted and left out.

- LinkedIn: the canonical address is `https://www.linkedin.com/jobs/view/<id>` with every tracking parameter stripped; the JD is read through LinkedIn's own guest endpoint.
- Xing: the `/m/<token>` link is a harvest key only (THE LINK RULE). It is resolved once to the posting's own `xing.com/jobs/...` address; if it does not resolve, the candidate waits in `data/mail/pending.json` (audit C31).
- An alert that lists a role but carries no link cannot be filed under THE LINK RULE and is only counted.
- A site that blocks or rate-limits the JD fetch is a deferral, not one of the two attempts: the posting is tried again the next day.
- "We have turned off your job alert for ..." (LinkedIn disables an alert left unviewed for 90 days) is shown on the Mail page and in the coverage line.

## When Gmail cannot be read

- A Google app in "Testing" mode has a refresh token that dies after 7 days (`invalid_grant`). Renew it with `python scripts/gmail_client.py auth` (browser, one click). To stop the 7-day expiry, publish the OAuth consent
  screen to "In production" in the Google Cloud console (a personal-use app with only the account owner needs no verification).
- A failed read is never silent: `data/mail/state.json` keeps `last_error`, audit **C28** warns, the Mail page and the brief say so, and the unattended run records `mail_ok: false` and carries on with the watches.
- Fallback: a Claude session reads the mailbox through the Gmail connector and writes the messages as `data/mail/snapshot.json` (`{"messages": [{id, thread_id, from, to, subject, date, labels, snippet, body_text}]}`);
  `python scripts/mail_sync.py run --snapshot data/mail/snapshot.json` processes it exactly as the OAuth read would.

## Where it shows

The dashboard **Mail** page (`/mail`, `/api/mail`): what asks you to act, mail to settle, rejections recorded, applications confirmed, alert intake, a failed read. The digest's ACT NOW and Replies sections. The phone inbox
(mail that asks you to act). The audit (C28 to C31).

## Commands

`mail_sync.py run [--days N] [--snapshot FILE] [--dry] [--reprocess] [--reset-open]`, `status`, `queue`, `show <msg_id>`, `explain <msg_id>`, `judge <msg_id> --kind K [--job ID | --thesis ID] [--note ...]`.
Tests: `python scripts/tests/test_mail_sync.py`.

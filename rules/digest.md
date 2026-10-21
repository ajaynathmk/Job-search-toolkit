# digest.md: the daily digest e-mail (runbook step 9, stage S50)

*Owns: the layout, the data sources and the sending rule of the digest e-mail. The code is `scripts/digest_email.py`; it is sent through `gmail_client.send_digest_email()` to the owner's own address only
(`profile.email`; non-negotiables 1 and 2 in `CLAUDE.md`).*

## Rules

- It is sent every run, even on zero hits (the sections that are empty simply do not appear).
- Every number and list is read from the tracker, the mail pass (`data/mail/queue.json`, `mail_events`) and `data/pipeline-state.json`, so the digest cannot disagree with the dashboard. A Claude session may add one
  short prose note to a section (`notes={"act": ..., "top": ..., "coverage": ...}`), never a new fact.
- A role is linked only when its URL is verified (THE LINK RULE). Best fits shown were each read in full.
- HTML with a plain-text part; inline styles only (mail clients drop `<style>`), 640 px wide, a dark-mode block for clients that honour it.
- It goes to **one address only**: the owner's own. `send_digest_email()` takes no recipient argument; this is the single place the toolkit sends mail, and it is never used for an employer or a portal.

## Layout, top to bottom (about two screens)

| Block | Shows |
|---|---|
| Header + chips | the date; Gmail read, watches ran, audit clean, review queue empty |
| Numbers strip | new best fits, ready to send, need action, rejections in 24 h, open roles |
| **Act now** | up to 4 mails that ask you to act and 3 best-fit deadlines within 7 days |
| Replies | up to 6 rejections, invitations and confirmations from Gmail, by employer and role; "to read" where a session must still decide |
| Ready to send | up to 4 packages with deadline; packages for roles the analysis calls not a fit are only counted |
| Top picks | up to 5 best fits: verdict, score, one-line why |
| Also new / Still open | up to 5 and 3 compact lines, with "+ N more on the dashboard" |
| Changes since yesterday | Rechecked, Blocked, Closed as one line each (count and employers) |
| Coverage | one line: Gmail read, watches, audit, counts, what needs a session |

Empty blocks do not appear. Every list ends with "+ N more on the dashboard" instead of growing. Colour carries meaning: green = apply or done, indigo = backup income, blue = plan or information, amber = needs a look,
red = rejected, blocked or deadline.

## In the pipeline

Stage S50 runs last in the unattended run (after the state is written, so the chips show this run). `digest_email.send_once()` mails once per day (`data/digest-state.json`); a second run the same day only refreshes
`digests/<date>.html`. A failed send (for example a dead Gmail token) is recorded in `pipeline-state.json` under `digest`, audit **C33** warns, and the run carries on.

## Commands

```
python scripts/digest_email.py preview [--date YYYY-MM-DD]   # writes digests/<date>.html and .txt, sends nothing
python scripts/digest_email.py send [--force]                # sends the HTML digest to the owner only
```

# remote.md: the phone inbox (stage S31, optional)

*Owns: how the owner approves and rejects from a phone when the computer is off, what leaves the computer, how decisions come back, and the security of the page. The phone side is `remote/` (a Cloudflare Worker with KV, free
tier); the computer side is `scripts/remote_sync.py`. Setup is in `docs/PHONE.md`. Skip it entirely if you do not want a cloud component: nothing else depends on it.*

## How it works

```
 Computer (on)                             Cloudflare (always on)                     Phone
 push  snapshot of best fits, ready  --->  KV "snapshot"  --------------------->  Decide / Ready / Mail / Thesis / Sent
       packages, mail to act on                                                        |  Approve - Recheck - Not for me - I applied - Note
 pull  decisions  <------------------      KV "ev:..." events (pending)  <---------------+
 apply through db.py (same guards as the dashboard), then ack  --->  the phone shows "applied on the computer" or why not
```

- The computer reaches the cloud; the cloud never reaches the computer. A decision waits as an event (30 days) until the computer asks for it.
- **When the computer is off** the phone shows the last snapshot ("synced 9 h ago") and your decisions queue ("waiting for the computer"). Undo works until the computer has applied it.
- **When the computer is on**: `remote_sync.py sync` runs at the start of every scheduled pipeline run, every 5 minutes while the dashboard runs, and once more at the end of the run so the snapshot shows its results.
  Cloudflare KV lists new events with up to a minute of delay, so a decision made seconds ago may wait for the next sync.
- After the decisions are applied the normal flow continues: `approval = requested` rows are the S40 build queue; the CV and cover letter are built in a Claude session on the computer.

## How the phone page is laid out

- **One tap target per job.** A card is a single large tap area that opens the details; there are no small links on it. Each card has exactly three big buttons (52 px high, 10 px apart): **Skip**, **Recheck** and **Approve**
  (filled, widest). Labels and icons, not icons alone.
- **Swipe**: right approves, left skips; a short swipe springs back and decides nothing; vertical scrolling is never captured. Every decision shows an **Undo** toast for 8 seconds; there are no pop-up confirmations.
- **Thumb-reach navigation**: a bottom tab bar (Decide, Ready, Mail, Thesis, Sent) with counts; a frosted header with the sync pill (tap to refresh); filter chips for the verdicts.
- **Details as a bottom sheet**: facts, why, CV comparison, score, the posting. Its bar holds **Open the posting**, then Skip / Recheck / Approve, then the quieter **I applied** and **Add note**.
- Dark mode, safe-area padding, haptic taps where the phone allows, `prefers-reduced-motion` respected.

## Reading a role on the phone (the Details sheet)

"Read details" opens a full-screen sheet so a role can be read, checked on its own site and decided without going back to the computer: key facts, **why** the verdict was given, **against your CV**, **how it scored**,
and **the posting's own text** (the public job description, first 9,000 characters). A fixed bar holds **Open the posting** (marked "not verified yet" when THE LINK RULE has not checked it) and the decision buttons.
The details are uploaded with the snapshot as one KV value and fetched per role.

## What the phone can do (and what it cannot)

| Action | Effect on the computer | Refused when |
|---|---|---|
| Approve | `approval = requested`, `approved_at` | the role is no longer open |
| Recheck | `approval = recheck` | the role is no longer open |
| Not for me | `status = skip` (thesis: `closed`) | already applied, interview or rejected |
| I applied (+ date) | `status = applied`, `applied_at` | nothing (already applied is reported) |
| Note | appended to `my_notes` as `[phone <date>] text`, written with `source="owner"` because it is the owner's own input | empty note |

A decision on a row that changed on the computer in the meantime is reported to the phone ("already rejected"), never forced. Nothing on the phone builds, sends or submits anything.

## What leaves the computer

The snapshot and the details: for each best-fit open role and each ready package: id, title, employer, place, verdict, score, why, deadline, status, approval, channel, the posting link (flagged when not verified), the key
facts, the CV comparison, the score breakdown and **the posting's public text**; thesis leads the same way; mail that asks you to act and the last week's replies (employer, role, date). **Never**: CV or cover-letter
material, `my_notes`, contact data, documents, or any column not listed.

## Security

- The page asks for a **passphrase** (four words and four digits, issued by `remote_sync.py init`, shown once, never stored in clear). It is checked with PBKDF2-SHA256 (100,000 rounds) against a hash held as a Worker
  secret; 8 wrong attempts from one address lock it for an hour; a correct one starts a 60-day session cookie (HttpOnly, Secure, SameSite=Strict).
- The computer authenticates with its own long random key (`config/remote.json`, git-ignored), sent only over HTTPS; the phone page cannot use computer routes and the computer key cannot open the page.
- The static page contains no data. Responses are `no-store`; there is no third-party script; the page is not indexed.
- The phone can only decide on roles that are in the snapshot, with a fixed set of actions, and a note is capped at 1,000 characters.
- Trade-off: the snapshot (a list of roles you might apply for) sits in Cloudflare KV behind that login. To remove it: `cd remote && npx wrangler kv key delete snapshot --binding KV --remote`, or delete the Worker.

## Operating it

```
python scripts/remote_sync.py init                                       # one-time setup: passphrase, keys, config/remote.json (docs/PHONE.md)
python scripts/remote_sync.py sync | push | pull | status | snapshot     # snapshot = what would be uploaded, nothing sent
cd remote && npx wrangler deploy                                         # after changing the page or the Worker
python scripts/tests/test_remote_e2e.py [passphrase]                     # offline rules always; the end-to-end part needs a Worker and the passphrase
```

Audit **C34** warns when the phone inbox has not synced for two days or the last sync failed. Add the page to the phone's home screen for one-tap access.

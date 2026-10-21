# Privacy

## Where your data lives

| Data | Where | In git? |
|---|---|---|
| Your profile, field, CV text, evidence bank, master CVs | `profile/` | **no** (ignored) |
| Roles, notes, mail facts, read receipts | `db/tracker.db` | **no** |
| Cached job postings | `jd/` | **no** |
| Tailored CVs, letters, match reports | `applications/` | **no** |
| Watch results, caches of your mail, state | `data/`, `digests/`, `logs/` | **no** |
| Gmail OAuth client and token, the phone inbox's keys | `config/`, `remote/.dev.vars` | **no** |

Everything above stays on your machine. Back it up yourself.

## What leaves your machine, and only if you choose it

| What | To whom | When |
|---|---|---|
| Web searches Claude runs while researching your field or a country | the search provider | during `/start`, `/region`, `/daily`: **field and country words only, never your name, e-mail, employers or CV text** (a rule in `CLAUDE.md`) |
| Posting requests (the watches, intake, link checks) | the employers' and boards' own sites | every run |
| Gmail, read-only, through your own Google OAuth client | Google | if you set it up |
| The digest e-mail | your own address, through Gmail | if you set it up |
| The phone inbox snapshot | your own Cloudflare account, behind your passphrase | if you set it up |
| Text of a draft sent to LanguageTool by `scripts/lang_check.py` | languagetool.org | only when you run that checker by hand, on drafts |
| Claude Code itself | Anthropic, under your own account and its terms | whatever you put in a session |

The toolkit makes **no call to any server of its authors**; there is none.

## Before you publish a fork or open a pull request

```bash
python scripts/privacy_scan.py            # scans the tree (and, with --history, every commit) for personal data and secrets
```

It checks: no tracked file under `profile/`, `db/`, `jd/`, `applications/`, `data/`, `config/`; no database or key file; no e-mail address other than an `example.*` one; no phone number; no token or key patterns (Google, Cloudflare, bearer, private keys); and, if you give it
`--also <word>` terms (your name, your university, your city), none of those in any file. Run it with your own identifying words before the first push: `python scripts/privacy_scan.py --also "Your Name" --also "Your City"`.

## If something personal was committed

Do not just delete the file in a new commit: it stays in history. Rewrite the history (`git filter-repo`) or, if the repository is new, delete it and recreate it. Rotate any secret that was exposed (Google: revoke at myaccount.google.com/permissions and create a new client;
Cloudflare: rotate the Worker secrets, `init --reset-passphrase`).

## Fictional data only in the repository

The examples and tests use invented people (`Sam Example`, `Jordan Sample`), `example.org` addresses and made-up employers. Keep it that way in contributions.

# The phone inbox (optional)

Approve, recheck and skip roles from your phone when your computer is off. When the computer is back on, it applies your decisions and the normal flow continues (the CV and letter are built on the computer). It runs on **your own** Cloudflare account, free tier. What it
does, what leaves the computer and how it is secured: `rules/remote.md`. If you do not want a cloud component, skip it: nothing else depends on it.

## One-time setup (about 15 minutes)

You need Node.js 18+ and a free Cloudflare account (https://dash.cloudflare.com/sign-up). **You** create the account and do the browser sign-in; Claude does the rest with you.

1. `cd remote && npm install` (installs wrangler, Cloudflare's CLI).
2. `npx wrangler login`: a browser opens; approve.
3. Create the storage: `npx wrangler kv namespace create KV` prints an `id`. Put it in `remote/wrangler.toml` in place of `REPLACE_WITH_YOUR_KV_NAMESPACE_ID`.
4. Back in the repository root: `python scripts/remote_sync.py init`. It creates the three secrets and a **passphrase (four words and four digits), shown once**: save it in a password manager. It writes `config/remote.json` (git-ignored) and `remote/.dev.vars` (git-ignored).
5. Upload the secrets: put `PC_KEY`, `COOKIE_KEY` and `PASS_HASH` (from `config/remote.json`) in a temporary JSON file and run `cd remote && npx wrangler secret bulk <file>`; delete the file afterwards.
6. `cd remote && npx wrangler deploy`. The first deploy asks you to pick a `workers.dev` subdomain. It prints the page's address.
7. `python scripts/remote_sync.py init --url https://<your-worker-address>` (so the computer knows where to push), then `python scripts/remote_sync.py sync`.
8. Open the address on your phone, enter the passphrase, add the page to the home screen.

`python scripts/remote_sync.py status` shows the state; `/phone` walks Claude through all of this with you.

## Day to day

The computer pushes a snapshot (best fits, packages ready, mail that asks you to act) at the start of every scheduled run and every five minutes while the dashboard is open; your decisions wait in the cloud until the computer pulls them. The page shows "synced N hours ago" and "waiting for the
computer" so you always know the state.

## New passphrase, removal

- `python scripts/remote_sync.py init --reset-passphrase`, then re-upload `PASS_HASH` (step 5). Rotate `COOKIE_KEY` the same way to end every phone session.
- Remove all data: `cd remote && npx wrangler kv key delete snapshot --binding KV --remote`, or delete the Worker in the Cloudflare dashboard.

## What the cloud sees

A list of the roles you might apply for (title, employer, place, verdict, score, why, the posting's public text) and the decisions you made. Never your CV, your notes, your contact data or your documents. It is behind your passphrase on your own account.

# remote/ — the phone inbox (Cloudflare Worker)

See `rules/remote.md` for what it does and why. This folder is the Worker:

- `src/index.js` the API (login, snapshot, decisions, PC routes)
- `public/index.html` the phone page (no data inside)
- `wrangler.toml` the Worker `job-inbox`, one KV namespace, the static assets

## Deploy or redeploy

```
cd remote
npm install                    # once (wrangler)
npx wrangler login             # once, browser
npx wrangler deploy
```

Secrets (set once, from `config/remote.json`, which `scripts/remote_sync.py init` writes): `PC_KEY`, `COOKIE_KEY`, `PASS_HASH`.
To set them again: put the three values in a JSON file and run `npx wrangler secret bulk <file>`, then delete the file.

## New passphrase

`python scripts/remote_sync.py init --reset-passphrase` prints a new passphrase and rewrites `pass_hash` in `config/remote.json`; then upload the new hash
(`npx wrangler secret bulk` with just `PASS_HASH`). Sessions on the phone stay valid until their cookie expires; to end them all, rotate `COOKIE_KEY` the same way.

## Local test

`npx wrangler dev --local --port 8787` (reads `.dev.vars`, which `init` also writes), then `python scripts/tests/test_remote_e2e.py <passphrase>`.

---
description: Set up or check the phone inbox (approve and reject from a phone when the computer is off)
---

Load `rules/remote.md` and `docs/PHONE.md`. This part is optional and needs a free Cloudflare account that **the person** creates; you never create an account for them.

1. `python scripts/remote_sync.py status`. If it reports "not set up", walk the person through `docs/PHONE.md` one step at a time: Node.js and wrangler, `npx wrangler login` (the person does the browser sign-in), the KV namespace and its id in `remote/wrangler.toml`
   (the file ships with a placeholder), `python scripts/remote_sync.py init` (it prints the passphrase once: tell the person to save it in a password manager; never write it to a file you create), `cd remote && npx wrangler deploy`.
2. First sync: `python scripts/remote_sync.py sync`, then have the person open the page on their phone and log in.
3. Explain what leaves the computer (`rules/remote.md`, "What leaves the computer") before the first push and get a yes.
4. If it is already set up: `sync`, report the pending decisions it applied and any it refused (with the reason).

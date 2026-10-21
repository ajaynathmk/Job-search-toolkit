---
description: Check which tools are installed and what each missing one switches off
---

Run `python scripts/onboard.py doctor` and `python scripts/onboard.py check`. Explain the result in plain language: what works now, what is off and what turning it on would give the person, in order of usefulness. Offer to fix the cheap ones
(`pip install -r requirements.txt`, `npm install`); for anything that needs an account or a browser consent (Gmail, Cloudflare), explain the steps in `docs/GMAIL.md` or `docs/PHONE.md` and let the person do the consent themselves.

---
description: Preview today's digest e-mail, and send it to the person's own address if they say so
argument-hint: "[send]"
---

Argument: $ARGUMENTS

1. `python scripts/digest_email.py preview` writes `digests/<date>.html` and `.txt` and sends nothing. Open it with the person (read the text version aloud if there is no browser) and ask whether the layout and length are right; changes go in `scripts/digest_email.py`
   (and a one-line `CHANGELOG.md` entry).
2. Only if the argument is `send` or the person asks: `python scripts/digest_email.py send`. It goes to `profile.email` only, once a day (`--force` to resend). It needs Gmail set up (`docs/GMAIL.md`).

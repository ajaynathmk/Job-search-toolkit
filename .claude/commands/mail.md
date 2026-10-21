---
description: Read job mail in Gmail (replies, rejections, invitations, alerts) and settle what the script could not
---

Load `rules/mail.md`.

1. `python scripts/mail_sync.py run` (read-only). If Gmail is not set up or the token is dead, say so and point to `docs/GMAIL.md` (`python scripts/gmail_client.py auth`); do not work around it by sending or modifying anything.
2. `python scripts/mail_sync.py queue`: what asks the person to act, what is unmatched, what needs a read.
3. For each mail the script could not settle: `python scripts/mail_sync.py show <msg_id>` (read the whole mail), `python scripts/mail_sync.py explain <msg_id>` (the matching), decide, then
   `python scripts/mail_sync.py judge <msg_id> --kind <kind> --job <row id> --note "<why>"`. A rejection always wins; an offer is never applied by the script; a status the person set by hand is never downgraded.
4. Tell the person first about anything that asks them to act, with the date it must be done by.

Gmail is only read: never reply, forward, label or delete. The digest is the only mail the toolkit sends, to the person's own address.

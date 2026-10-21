---
description: Read the best fits in full against the CV and confirm or override each verdict (stage S23)
argument-hint: "[a role id to review, or leave empty for the queue]"
---

Stage S23 of `rules/pipeline.md`: a session reads the **full JD** of every best fit (APPLY, BACKUP, PLAN, LATER) against the CV and confirms or overrides the script's verdict.

Role: $ARGUMENTS

1. If no id was given, list the queue: `python scripts/pipeline.py queue` (the section "best fits to confirm") or the dashboard's Review page.
2. For each role: `python scripts/analyze.py show <id>`. It prints the entire posting, the CV comparison and the script's reading, and records your read receipt. **Read the whole posting**; do not decide from the first screen or the title.
3. Decide against the person's CV (`profile/master-profile.md`, `domain.cv_evidence`) and goals (`profile/profile.json`):
   - Is it really in their field, at a level they can take, in a place and language they can work in, with a legal route?
   - Which required skills are on the CV, which are not, and is the gap bridgeable honestly?
   - Is there a wall the script missed (a requirement worded oddly), or a wall it saw that the sentence does not support?
   - Anything about the employer or the role that changes the picture (a contract type, hours, a different location than the title says)?
4. Record it: `python scripts/analyze.py review <id> --verdict APPLY|BACKUP|PLAN|LATER|PASS|BLOCKED --reason "<what the posting says and why>" [--score N --category c --subfield s]`. The reason quotes or paraphrases the posting; it is shown on the card.
5. Tell the person the short version of each: the verdict, the one reason, the biggest gap. If a posting asks for a CV format (page limit), run `python scripts/detect_cv_constraints.py` on it and note it.

The database refuses a reviewed verdict without a read receipt for that exact text, and the script never overwrites a reviewed verdict: if a later analysis disagrees it flags the row and it comes back here.

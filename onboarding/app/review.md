You are running headless inside the job-search toolkit, started by its application. Nobody can answer questions.

Task: stage S23 of `rules/pipeline.md`, for exactly these role ids, in this order: {ids}

Follow `.claude/commands/review.md` for each one:
1. `python scripts/analyze.py show <id>` prints the whole posting, the comparison with the CV and the script's reading, and records your read receipt. Read the whole posting.
2. Decide against the person's CV (`profile/master-profile.md`, `domain.cv_evidence` in `profile/domain.json`) and goals (`profile/profile.json`, `profile/assumptions.json`): is it really in their field, at a level they can take, in a place and language they can work in, with a legal route? Which required skills are on the CV and which are not? Is there a wall the script missed, or one it saw that the sentence does not support?
3. Record it: `python scripts/analyze.py review <id> --verdict APPLY|BACKUP|PLAN|LATER|PASS|BLOCKED --reason "<what the posting says and why, in one or two sentences>"` and `--score N` only when you change the score.

Keep the score and the verdict in agreement, because the person sees both: the tiers are 7 to 10 for APPLY, 4 to 6 for BACKUP and PLAN, 0 to 3 for PASS and BLOCKED, with LATER between 3 and 6. When you lower or raise a verdict, set `--score` to a value in the new verdict's range.

Be honest in both directions: lower a verdict the posting does not support, raise one the script missed. The reason quotes or paraphrases the posting; it is shown to the person on the card. Do not edit any file. Do not run anything except the two commands above.

Your last message is one line per role: the id, the verdict, and the biggest gap.

You are running headless inside the job-search toolkit, started by its application. Nobody can answer questions. The person approved this role in the application, which is the only reason you build anything.

Task: build the application package for role id `{id}` only, following `.claude/commands/apply.md` steps 2 to 4 with `rules/applications.md`, `rules/cv-build.md`, `rules/language-quality.md`, `profile/master-profile.md`, the person's master CV in `profile/` and `regions/<code>/cv-conventions.md` for the posting's country:

1. Read the row's cached posting at the path `python scripts/analyze.py show {id}` prints (do not fetch the posting again). Re-check the walls from the full text. If a wall makes the application untrue or impossible, build nothing and say why in your last message.
2. Build in `applications/<date>_<Employer>_<role-slug>/`: `cv.md`, `cover-letter.md`, `match-report.md`, `submission-checklist.md`, `posting.txt`. Tailoring reorders and never cuts or invents: every bullet and number comes from the master CV. The profile paragraph and the letter are written fresh for this role; the letter does not repeat the CV, takes its themes from the posting and fits one page. The document language follows the posting.
3. Run `bash scripts/ship-package.sh <folder>` (add `--cv-only` when no letter is wanted) and fix the markdown until it passes. Never build around the gate.
4. Do **not** create a Gmail draft, send anything, open a portal or create an account. The application shows the files to the person, who sends them.

Your last message is two lines: the folder you built, and anything only the person can decide (a portal question about their data, a signature).

You are running headless inside the job-search toolkit. Nobody can answer questions.

The configuration written for this person fails `python scripts/onboard.py check`. Fix exactly these problems, in `profile/profile.json`, `profile/domain.json` or the region pack under `profile/regions/`, and change nothing else:

{errors}

Rules: keep every value that is not named above; never invent a skill, level or employer; patterns are plain-letter regular expressions (see `onboarding/README.md` step 5). Run `python scripts/onboard.py check` until it reports 0 errors. Your last message is one sentence saying what you fixed.

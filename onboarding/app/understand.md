You are running headless inside the job-search toolkit, started by its application. Nobody is there to answer questions: do not ask any.

Task: set the toolkit up for the person whose CV is in `profile/cv-source.txt`. `CLAUDE.md` is already loaded. Follow `onboarding/README.md` steps 0 to 6 and `onboarding/domain-inference.md`, with these overrides:

1. **No questions.** Wherever the procedure asks the person something, use the default in `onboarding/questions.md`, inferred from the CV. Record every answer you did not read directly off the CV in `profile/assumptions.json`: a JSON list of objects
   `{"key": "<dotted path in profile.json, for example work_authorization.status>", "label": "<the question in plain words>", "value": <the value you wrote>, "source": "cv" | "inferred" | "default", "confidence": "high" | "medium" | "low", "why": "<one sentence>"}`.
   Every field of `profile.json` that the CV does not state must appear there, so the person can correct it on one screen. At least: career stage, kinds of role sought, languages and levels, home country and other countries, right to work, cities and remote, document language.
2. If `profile/user-notes.txt` exists it is the person's own words about what they want. It overrides any inference from the CV.
3. Right to work: unless the CV states a nationality or a visa, set `work_authorization.status` to `unrestricted` for the home market and mark it `confidence: low` in `assumptions.json`. Never guess a visa.
4. Languages: take levels only from the CV (a certificate, a stated level). A language listed without a level gets the level the CV's context supports, marked `confidence: low`. Never claim a level the CV does not support.
5. Skip step 7 (optional parts) and step 8 (the first run). Do not run any watch or the pipeline. The only network use allowed is WebSearch/WebFetch to research a region pack that does not exist yet (`rules/regions.md`), with field and country words only: never the person's name, e-mail, address, employers or any text from the CV.
6. Never invent a skill, a degree, an employer, a level or a number. Every `cv_evidence` entry and every line of `profile/master-profile.md` traces to the CV.
7. Write only inside `profile/` (and `profile/regions/` for a new region pack): `profile.json`, `domain.json`, `master-profile.md`, `assumptions.json`, and `master-cv-<language>.md` if the CV can be converted without changing a bullet or a number.
8. You are finished when `python scripts/onboard.py check` reports 0 errors. Fix warnings that point at a real mistake.

Your last message is three plain sentences and nothing else: the field or fields you found, the core sub-fields, and the countries you will search.

# onboarding/README.md: how Claude sets the toolkit up for a person

*This is the procedure `/start` follows. It turns a CV and a short conversation into the three configuration documents the engine reads (`profile/profile.json`, `profile/domain.json`, a region pack), validates them, and
starts the first search. Read `docs/ARCHITECTURE.md` first if you have not; read `rules/regions.md` before step 6.*

**Principles**

1. **Everything comes from the person's own words and documents.** Never invent a skill, a language level, a degree or an employer. If you infer something, say it is inferred and ask.
2. **Ask few questions, and only the ones the CV cannot answer.** Offer a default with every question. Group questions (the question tool allows up to four at a time).
3. **Show your work.** After reading the CV, say in a few lines what field(s) you found, which you think are the person's strongest and which they want to work in, and what you will search for. They correct you; you write the files.
4. **Nothing personal leaves the machine.** `profile/` is git-ignored. Do not paste the CV into a web search or a third-party service. Web searches in this procedure use field and country words, never the person's name, e-mail or employers.
5. **Be honest about what is unverified.** A region pack that was researched from search results says so; a legal route that needs an authority's confirmation says so.

## The steps

### 0. Look at what exists
`python scripts/onboard.py status`. If `profile/profile.json` and `profile/domain.json` exist and `check` passes, this is not a first run: ask whether to update (a new CV, a new country, a new goal) rather than start over, and
keep what the person has not changed.

### 1. Get the CV
Ask for the CV file (PDF, DOCX, Markdown or plain text) or its text. `python scripts/onboard.py extract <file>` writes `profile/cv-source.txt`. Read it in full. If there is no text layer (a scanned PDF), ask the person to paste the text.
If they have no CV yet, say so and continue with a short interview (education, work, projects, skills) and offer to build one later (`/apply` builds CVs from `profile/master-profile.md`).
Detect the CV's language; the document language of the search (`profile.document_language`) defaults to it.

### 2. Understand the person and the field
Follow `onboarding/domain-inference.md`. Produce, in your head and then in one short message to the person: career stage; the field(s) the CV shows; the sub-fields (4 to 8) with which are **core** (what they are strongest in and
want), **bridge** (adjacent fields that use the same skills), **income** (skills usable in unrelated sectors) and **other**; the tools, methods and standards that are on the CV; the industries and the kinds of employer.

### 3. Ask the questions
Follow `onboarding/questions.md`. Ask only what is still open after steps 1 and 2: the goal (what kind of roles, and since when), career stage confirmation, languages and honest levels, nationality-driven work authorization,
where (home market, other countries, remote), cities, preferred or excluded employers, whether unrelated roles are acceptable for income, e-mail, whether to use Gmail and the phone inbox, and which language the documents are written in.
Correct yourself when an answer changes the picture (a different region pack, a different career stage).

### 4. Choose the region packs
From the answers: `profile.regions`, home market first. Shipped: `de`, `eu`, `us`. If the home market has no pack, run the procedure of `rules/regions.md` now (`scripts/onboard.py scaffold-region`, research, write, validate). A person
who wants Germany and the rest of Europe gets `["de", "eu"]`; a person in the U.S. gets `["us"]`; a person in France who wants France and Europe gets a researched `fr` pack and `["fr", "eu"]`.

### 5. Write the configuration
Copy the templates (`python scripts/onboard.py init`) and fill them:
- `profile/profile.json` (`onboarding/templates/profile.template.json`): every field from the answers. `work_authorization.status` from the person's situation (see `rules/regions.md`).
- `profile/domain.json` (`onboarding/templates/domain.template.json`): categories, sub-fields with terms and aliases, `cv_evidence` (one entry per skill, tool, method or credential on the CV, with the status **covered** (shown on the CV),
  **partial** (touched, not deep) or **gap** (a common ask the CV does not show), and `evidence` naming where the CV shows it), priority employers, `industry_regex`, `search_terms`, `locked_terms`, `penalty_subfields` (sub-fields
  that look related but are not for this person), `walls` the person cannot meet (a degree they are not enrolled in, a credential they lack), `thesis_pillars` for students.
- `profile/master-profile.md` (`onboarding/templates/master-profile.template.md`): the evidence bank every CV bullet traces back to. Every fact comes from the CV or the answers; give each an id (`EXP-1`, `PRJ-2`, `EDU-1`, `SKL-3`).
- `profile/master-cv-<language>.md`: the CV as markdown in the format `scripts/build-cv.js` reads (`rules/cv-build.md`), if the person wants the toolkit to build tailored CVs. Keep every bullet and every number exactly as on the CV.
- Contact data (phone, postal address) goes only in `profile/master-profile.md` and the master CV, never in `profile.json`, and never in a file outside `profile/`.

Patterns: write terms as plain-letter regular expressions (accents folded, `\b` for word edges, `.?` for optional separators): `rna.?seq`, `\bsql\b`, `pharmakovigil`. They are matched against the folded text of the full posting.

### 6. Validate
`python scripts/onboard.py check` must report 0 errors; read every warning. Then test the configuration against the person's world: run `python scripts/onboard.py build-sources` (employers by industry), run the watches once with `--no-write`
(`python scripts/job_watch.py --no-write`), and analyse two or three real postings the person sends or you find (`python scripts/analyze.py explain <id>` after intake, or paste a posting into `examples/`-style files and use
`onboard.py demo`-style analysis). Read the verdicts with the person: a wrong wall, a missing field or a bad route is fixed in the configuration, not worked around.

### 7. Set up the optional parts (only what the person wants)
`python scripts/onboard.py doctor` shows what is installed. Offer, in this order: the dashboard (`python scripts/webapp.py`), Gmail (`docs/GMAIL.md`: replies, alerts, the digest e-mail), alerts (`rules/alerts.md`: build the set, write
`profile/alerts.md`), the schedule (`python scripts/scheduler.py install`), the phone inbox (`docs/PHONE.md`). Never create an account, a cloud project or an alert on the person's behalf without them doing the consent step themselves.

### 8. First run
`python scripts/pipeline.py run --force --ignore-power` (or `/daily`): the watches, intake, the analysis. Then `/review`: read the best fits in full with the person. Finish by telling them in a short list what was set up, what is not (and
what it would unlock), where their data lives, and what to type next (`/daily`, `/review`, `/apply`, `/status`).

## What is never done during onboarding

No application is submitted, no mail is sent (the digest is the only mail the toolkit sends, to the person's own address, and only after they agree), no account is created on their behalf, no data leaves the machine except the public web
searches described above and, if they choose it, the phone inbox snapshot.

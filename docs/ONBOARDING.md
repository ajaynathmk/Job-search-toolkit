# Onboarding: what `/start` does

`/start` turns a CV and a short conversation into a working, personal configuration. You do not have to understand the files it writes, but you can read and edit them: they are plain JSON in `profile/`.

## What you provide

1. **Your CV** (PDF, Word, Markdown or text). If you have none, Claude interviews you instead (education, work, projects, skills) and can build one later.
2. **Answers to a handful of questions** that the CV cannot answer. Each has a default; you can say "default".

## What Claude does, step by step

| Step | What happens | You see |
|---|---|---|
| 1 | Extracts the CV text to `profile/cv-source.txt` (on your machine only) and reads all of it | "I read N pages" |
| 2 | Infers your field: the sub-fields, which are your strongest, which are adjacent, what is on your CV, what postings in your field ask that your CV does not show | a summary in plain language, for you to correct |
| 3 | Asks what is still open: goal and kinds of role, languages and honest levels, nationality and right to work, where, cities, employers, whether unrelated roles are acceptable for income | up to four questions at a time |
| 4 | Chooses the region packs (home market first) or researches the country if none ships | "Germany first, then Europe" |
| 5 | Writes `profile/profile.json`, `profile/domain.json`, `profile/master-profile.md` and, if you want tailored CVs, the master CV in markdown | the file names |
| 6 | Validates (`python scripts/onboard.py check`) and tests the configuration against real postings **with you** | three postings and their verdicts: does each look right? |
| 7 | Offers the optional parts one at a time: dashboard, Gmail, alerts, daily schedule, phone inbox | yes/no for each |
| 8 | Runs the first search and reads the best fits with you | your first list |

## The questions, and why they matter

- **Career stage and kinds of role**: a student looks for theses, student assistant jobs, working-student roles and internships; a new graduate for internships, trainee programmes and entry-level roles; an experienced person for entry to senior roles. This
  decides which postings are worth filing and what "later" means.
- **Languages and levels**: the analysis treats a stated level as a promise. A posting that needs a language two levels above yours is a wall; one level above lowers the verdict; a posting where it is "an advantage" is fine. Be honest: an inflated level
  produces verdicts that waste your time.
- **Right to work**: it changes scores (a route that costs nothing is +1; one that needs an employer-sponsored permit is -3) and creates walls (citizenship, "no sponsorship"). If you are a citizen or have unrestricted rights, none of it applies.
- **Where**: your home market comes first; other countries are in scope but become PLAN rather than APPLY.
- **Employers and exclusions**: employers you like get a point; roles you never want are excluded.
- **Income roles**: if you would take an unrelated job while you search, say so; it turns on the BACKUP verdict for adjacent skills at employers in your industry.

## What it writes (all in `profile/`, git-ignored)

| File | Contents |
|---|---|
| `profile.json` | who you are (see `onboarding/templates/profile.template.json`) |
| `domain.json` | your field (see `onboarding/domain-inference.md`) |
| `master-profile.md` | the evidence bank: every fact from your CV with an id; CV bullets and letter sentences trace back to it |
| `master-cv-<language>.md` | your CV as markdown, in the format the CV builder reads |
| `cv-source.txt` | the raw CV text |
| `sources.json` | employers whose career feeds are watched (picked by industry from `resources/employers.json`) |
| `regions/<code>/` | a region pack Claude researched for you (only if no shipped pack fits) |
| `alerts.md`, `search-terms.md` | your job-alert set and your search-term log |

## Changing your mind later

Run `/start` again, or edit the files and run `python scripts/onboard.py check`. When the profile, the domain or the region changes, the toolkit re-analyses every role on the next run and **flags every score that moved**, so nothing changes silently.
Common changes: you graduated (change `career_stage` and `levels_sought`), your right to work changed (`work_authorization.status`), your German improved (`languages`), you want another country (`regions`), you found a new sub-field (`domain.subfields`).

## Try it without your data

`python scripts/onboard.py demo` (the German student example) and `python scripts/onboard.py demo --example us-data-analyst` run the real analysis on fictional postings so you can see what a verdict, a wall and a route look like before you give it anything.

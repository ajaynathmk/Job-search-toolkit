# onboarding/questions.md: the question bank

*Ask only what the CV and your own reading have not already answered. Offer the default. Use the question tool for choices (up to four questions at a time); use plain conversation for open answers. Each answer says where it lands.*

## The goal

| Ask | Default | Lands in |
|---|---|---|
| "In one sentence, what are you looking for?" (roles, field, by when) | from the CV's most recent direction | `profile.goal` (free text, shown in the digest), `levels_sought`, the core sub-fields |
| "Where are you in your career?" student / new graduate / experienced / changing field | inferred from the CV (a current degree = student; a degree in the last two years = new graduate) | `career_stage`, which sets `levels_sought` unless the next question overrides |
| "Which kinds of roles do you want?" thesis, student assistant (research or teaching assistant), working student, internship, trainee or graduate programme, entry level, mid level, senior | the stage's defaults: student = thesis, student assistant, working student, internship; new graduate = internship, trainee, entry; experienced = entry, mid, senior | `levels_sought` |
| (students) "When can you start, and for how long? Is a thesis part of your degree?" | | `profile.availability`, whether `thesis` is sought |

## Languages (be honest: the analysis treats a stated level as a promise)

| Ask | Default | Lands in |
|---|---|---|
| "Which languages do you speak, and at what level (A1 to C2, or native)?" | English from the CV's language; others from the CV's language section | `profile.languages` |
| "Which language should your CV and letters be written in for most applications?" | the CV's language | `profile.document_language` |
| For any local language below C1: "Would you apply to a posting that asks for B2 in that language?" | no | whether a one-step-above requirement lowers the verdict (default) or is ignored (`profile.walls` override) |

## Where, and the right to work

| Ask | Default | Lands in |
|---|---|---|
| "Which country is your home market, the one you are searching first?" | the country of the CV's latest education or job | `profile.regions[0]` |
| "Do you also want other countries?" (a region: Europe, Gulf, ...; or specific countries) | no | further `profile.regions`, `scope_countries` |
| "What is your nationality, and what is your right to work in the home market?" citizen / permanent resident or equivalent / EU or EEA citizen (in an EU country) / student visa / work visa tied to an employer / no right yet, needs sponsorship (the U.S. adds F-1 on OPT) | | `profile.work_authorization.status` (see the statuses in `rules/regions.md`) and a note |
| (a student visa) "How many working days or hours does it allow, and does your university allow an external thesis?" | the pack's default | `work_authorization.note`; the region pack's `legal.md` is the reference |
| "Which cities, or is remote fine?" | remote fine, no cities | `profile.cities`, `remote_ok` |

## Employers and unwanted roles

| Ask | Default | Lands in |
|---|---|---|
| "Any employers you would especially like to work for?" | the field research's list (you propose, they edit) | `domain.priority_employers` |
| "Any kinds of roles you never want?" | none | `profile.exclude_titles`, `domain.walls` |
| "Would you take a job outside your field for income (for example analytics work at a health company)?" | no | `profile.accept_unrelated_income`, `domain.income_context_re` |
| "Is there a degree, licence or credential you do NOT have that postings often require (a state exam, a clearance)?" | | `domain.walls` or `profile.walls` |

## The tools (only if wanted)

| Ask | Default | Lands in |
|---|---|---|
| "What e-mail address should the daily summary go to? (Only you will ever receive it.)" | the address on the CV | `profile.email` |
| "Do you want the toolkit to read your Gmail for replies to your applications and for job alerts? It reads only; it never replies or deletes." | later | Gmail setup (`docs/GMAIL.md`), `profile.mail` |
| "Do you want to approve roles from your phone when your computer is off?" | no | the phone inbox (`docs/PHONE.md`) |
| "Should it run by itself every day?" | yes, 07:30 | `scripts/scheduler.py install --time 07:30` |
| "Do you want the toolkit to build tailored CVs and cover letters when you approve a role?" | yes | needs Node.js (`doctor`), a master CV and `profile/master-profile.md` |

## Confirming what you inferred (always, once, before writing the domain file)

Show the person in plain language: "I read your CV as: <field>. Your strongest areas look like <core sub-fields>; I will also watch <bridge fields>; I will treat <income skills> as a fallback if you say unrelated roles are fine. I will search
for <search terms> at <employer examples>. I found these skills on your CV: <list>. Gaps postings in this field often ask for that your CV does not show: <list>. What should I add, remove or change?"

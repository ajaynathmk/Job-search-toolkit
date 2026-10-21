# onboarding/domain-inference.md: from a CV to `profile/domain.json`

*How Claude reads a CV and writes the domain file: the document that tells the engine what "my field" means for this person. The engine only matches words, so the quality of this file decides the quality of every verdict.
Do this once, carefully, and show the result to the person before saving it.*

## What the file contains

| Key | What it is |
|---|---|
| `industries` | free tags for the industries of the person's field (`pharma`, `biotech`, `software`, `finance`, `health-tech`, `engineering`, ...). `onboard.py build-sources` uses them to pick employers from `resources/employers.json` |
| `categories` | 3 to 4 groups: the person's own field(s) (`fit: core`), adjacent ones (`fit: bridge`), everything else (`fit: none`). The dashboard filters on them |
| `subfields` | 4 to 10 specific areas, each with `id`, `label`, `category`, `role`, `weight`, `terms`, `aliases` |
| `penalty_subfields` | sub-fields that look related but are not for this person; each costs points |
| `priority_employers` | lower-case words of employer names: +2 on the score |
| `industry_regex` | words that make an employer "in the industry" (matched on the employer's name) |
| `income_context_re`, `income_context_min` | what makes an adjacent-skill role at an in-industry employer acceptable (only used if the person accepts income roles) |
| `search_terms` | 5 to 12 short phrases for board and API queries |
| `cv_evidence` | one entry per skill, tool, method or credential: `term`, `re`, `status` (covered / partial / gap), `evidence` |
| `evidence_bonus` | +1 when a posting asks for something the CV demonstrably shows (rare, high-value matches) |
| `thesis_pillars` | `{sub-field: pillar id}` for students looking for a thesis |
| `locked_terms` | tool and method names that rewording must never touch |
| `walls`, `classification_overrides` | credentials the person lacks; "this sub-field is not theirs unless the text also shows a computational part" style overrides |

## Step by step

1. **Read the CV in full and list the evidence.** Education (degree, field, thesis topic), work (employer, role, what was done, with what tools), projects, courses and certificates, tools and standards, languages. Number them (`EXP-1`, `PRJ-2`, ...).
2. **Name the field in the words employers use.** Look at how job titles in that field are written (search the web for a few current titles in the home market; never put the person's name in a search). A field has a name, 3 to 6 neighbouring names, and
   typical employer types.
3. **Cut the field into sub-fields.** A sub-field is something a posting can be about and the person can be good or bad at: "bioinformatics / genomics", "pharmacovigilance", "business intelligence", "backend engineering". Rules:
   - `role: core` for what the person is strongest in **and** wants to work in (usually 2 to 4); `bridge` for adjacent fields that use the same skills; `income` for skills usable in unrelated industries (data analysis, Python, project work) that
     the person would accept as a fallback; `other` for everything else the person does not want (wet-lab work for a computational person, sales for an engineer). Include a few `other` sub-fields on purpose: they are how the engine recognises a role that
     is *not* theirs.
   - `weight` 1 to 5: how strongly a hit in this sub-field's terms counts (3 is normal; 2 for generic skill words like `sql`, `python`; 4 or 5 for terms that only appear when the role is in that sub-field).
   - Every sub-field belongs to one of the categories.
4. **Write the terms.** For each sub-field, the words and short phrases that appear in titles and descriptions of postings in it, in the languages of the person's markets (English plus the home market's language): `bioinformat`, `rna.?seq`, `\bngs\b`,
   `pharmakovigil`, `drug safety`, `\bsql\b`, `dashboard`. Use stems (`pharmakovigil` matches both the German and the English word's stem), `.?` for optional separators, `\b` around short words so `ml` does not match `html`. 6 to 15 terms per sub-field.
   Do not put a term in two sub-fields unless it really belongs to both.
5. **Write the aliases** (core and bridge sub-fields): the short title words the watches use to recognise the field in a **title**: `Bioinformatik*`, `Computational Biology`, `Genomics`. A trailing `*` means "any ending". These are matched as whole words, so keep
   them specific.
6. **Write `cv_evidence`.** For every skill, tool, method, standard or credential a posting in this field might ask for: `term` ("Python (CV-3)": the id ties it to the master profile), `re` (what the posting would say), `status`:
   - **covered**: the CV shows it with a project, a job or a course. **Only claim this when the CV does.**
   - **partial**: touched but not deep (a course project, one use). Be conservative.
   - **gap**: a common ask in this field that the CV does not show. These are what the verdict calls "required skills not on the CV"; list 5 to 10, researched from real postings of the field.
   `evidence` says where the CV shows it. Never upgrade partial to covered.
7. **Employers and industry.** `priority_employers`: 10 to 25 lower-case name words of the field's best-known employers in the person's markets (research with web search: "largest <field> employers in <country>", the graduate-recruiting pages of the region's
   universities, professional bodies), plus any the person named. `industry_regex`: the words that identify the industry in an employer's name. `industries`: the tags.
8. **Search terms.** 5 to 12 short phrases a person would type into a job board for this field, each two to three words, the home market's language first.
9. **Penalties and overrides.** If a sub-field is a common false friend (wet-lab roles for a computational biologist, front-end roles for a data analyst, pharmacy-trainee roles for a pharmacologist who is not a pharmacist), add it to `penalty_subfields` and, where it
   helps, to `classification_overrides` ("lab work with no computational words is not mine").
10. **Walls.** Credentials or enrolments the person lacks that postings in the field often require (a licence, a state exam, a named degree in a different discipline). `label`, `re`, and an `unless_re` for the phrases that cancel it ("any natural-science degree").
11. **Thesis pillars** (students): map each core sub-field to a pillar id (a short word); the dashboard's Thesis page groups by it.
12. **Show the person, correct, save, validate** (`python scripts/onboard.py check`). Then sanity-test with three real postings: one that should be APPLY, one that should be PASS, one borderline. If a verdict surprises you, find the term or the weight that caused it and fix it.

## Quality bar

- A sub-field with fewer than 5 terms or terms that are all single common words will misclassify. A term that matches half of all postings (`team`, `data` alone) belongs nowhere.
- The core sub-fields' terms must be **specific**: the engine decides "core" only when the core score is at least 5 and at least 70% of the best non-core score.
- Weights of generic skill sub-fields (`income`) stay at 2 so they never beat a real field.
- Terms in the languages of **every market in the search**: the verdict of a French posting depends on French terms.
- Everything is derived from the person; none of the examples in `examples/` is a template for the *content*, only for the shape.

## Worked shape

See `examples/de-bioinformatics-student/domain.json` and `examples/us-data-analyst/domain.json`: two people, two fields, the same file format.

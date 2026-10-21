# applications.md: from a cached JD to a CV and cover letter

*Owns: how a cached JD becomes a CV and letter: the tailoring rules and the keyword ranking and placement. Read the boxed rule below before changing anything in this file.*

## The JD-first rule, unconditionally

A role is never tailored or recommended from its title. The JD is read exactly **once**, on the day the role is found, and cached in full as `jd/<Employer>_<role-slug>/description.md`
(`runbook.md`). Every later step (tailoring, rechecks, answering a question) reads that cache. Re-fetching a JD whose row says `jd_read=1` is a bug; the licensed exception is a recheck.

> ### THE CONTENT-REGULATION RULE
>
> **Tailoring REORDERS. It never cuts and it never invents.**
>
> Every section, every project, every skills category and every bullet that appears on the master CV appears on **every** tailored CV, every time, by default. A posting only changes
> **order and emphasis**: which section leads, which skills category comes first, which bullet of a project sits above the other, which terms are front-loaded in the profile summary.
> Something irrelevant to a posting moves to the bottom; it does not disappear.
>
> *Why:* a tailoring step that is allowed to select quietly deletes real information from the CV every time a package is built, with nothing in the posting asking for it.
>
> **Consequence:** there is no page cap on cutting content by default. A tailored CV runs as long as the master's own content takes to lay out. Separately, a two-page rendering target
> for the layout (`cv-build.md`: `keepNext` on headings so nothing is stranded) is hygiene, not a content limit, and never overrides this rule: if the real content does not fit the target,
> flag it in the match report; never cut to force it.
>
> The master CV's depth (two bullets per project, say) is the owner's own authoring choice; the deeper detail lives in `profile/master-profile.md` for letters and interviews.

## Permitted vs. forbidden

**Permitted:** reordering sections; promoting or demoting bullets and skill items within their category; rewording a real bullet in the posting's vocabulary; adjusting the profile summary's emphasis and front-loaded terms.

**Forbidden:** new tools, new responsibilities, inflated scope, invented metrics, implied seniority; any date or duration not in the master profile; cutting content of any kind, **except the named exclusions below**.

## The exclusions to the content-regulation rule

The only ways a tailored CV may differ from "every master bullet present, reworded or not". All are evidence-gated: none is available just because a package "seems like" it should qualify.

### Exclusion 1: the posting states its own CV format

Some postings say outright: a one-page CV, a CV covering "only relevant experience", a short or brief CV. That is the posting defining what it will accept, not tailoring choosing to cut.
**Detection is mechanical, the decision is not.** `scripts/detect_cv_constraints.py` scans a cached JD for candidate clauses (page-limit and content-restriction phrasing) when it is fetched and
logs any hit to the row's `constraints` column. That is a flag to read in context, never an automatic licence to cut. **Claiming the exclusion requires quoting the posting.** The match report
must record:

```
**Content-regulation exemption:** "<the exact quoted clause from the posting>" - <one line: what was cut as a result>
```

`scripts/consistency_check.py` relaxes `no_cut_completeness` and `locked_term_dropped` only for a package whose `match-report.md` contains this tag with an actual quoted string inside it.
An unquoted claim is not honoured: the bar for cutting real content is a real sentence from the real posting.

### Exclusion 2: the owner's own standing instruction (optional)

If the owner has written a standing instruction that allows a named section to be trimmed for roles outside their core field (for example: detail bullets of a research project on a role that does not
evaluate programming), record it in `profile/master-profile.md` under "Standing tailoring instructions" in their own words. Applying it requires the same tag, quoting that instruction. Without such an
instruction this exclusion does not exist. Apply it by judgment (does the posting evaluate that axis?), never by keyword.

### Exclusion 3: the Profile paragraph is never subject to this rule

The Profile paragraph is rewritten from scratch for every posting: a synthesis of what the posting needs and what the record shows, never a reorder of fixed master bullets. It is plain prose in the master,
so it was never counted by `no_cut_completeness`. It changing in every CV is expected, not a violation to explain.

> ### Locked terms: what rewording may never touch
>
> A tool name, a software package, a named method, a gene or variant identifier, a standard, or one of the master's own precise figures cannot be paraphrased without becoming untrue: a named tool
> is that tool, never "a data-analysis tool"; a p-value or a sample count is that exact number or it is not the same finding. `profile/locked_terms.json` is the maintained list (seeded by
> `scripts/extract_locked_terms.py` from the master CVs and `domain.locked_terms`, reviewed by hand before it is trusted). `scripts/consistency_check.py`'s `locked_term_dropped` check enforces it:
> for a reworded master bullet, every locked term it carries must still appear, unchanged, in the bullet the reword landed in. A miss is a hard stop, as severe as a cut.

## The five steps

### 1. The five lists
Read from the cache, never re-derived: hard requirements, soft requirements, domain vocabulary, tool and standard names (matched exactly: "MS Office" if that is what they wrote), practical constraints (hours,
on-site/hybrid/remote, pay, contract length, start window, named contact, reference number, application channel).

### 2. Match each requirement to evidence, ranked mechanically
Rate every keyword met / partial / gap against `profile/master-profile.md`. Never upgrade partial to met: a profile that is 70% met with two honest gaps is a *strong* application, one that claims 100% is a
weak one. Sort `keywords[]` by tier (must > preferred > context), then frequency (descending), then source (hardReqs > softReqs > body). This ranked list is computed, not eyeballed, and decides **order only**,
never inclusion. Log every must-tier gap with its pillar tag for the master profile's recurring-gaps tracking (`python scripts/rank_skills.py`).

### 3. Build the CV
The language follows the posting (a posting in German gets a German CV, one in English an English CV; never mixed); `regions/<code>/cv-conventions.md` has the host country's conventions (name of the document,
length, photo, personal details, dates). Order by relevance. Mirror the posting's vocabulary where truthful.

**The Profile paragraph is the one place that must read as genuinely written for this role, every time.** It names 2-3 concrete points of real overlap between the record and what this posting asks for,
in precise, polished language. Not "growing expertise in X" as a stock phrase: say *which* stated need it answers and *which* real experience answers it. It only rephrases real content from the master profile,
never invents a match, never names the posting, employer or site directly.

> **Standing rules for the Profile paragraph (defaults; the owner may change them in `profile/master-profile.md`):**
> 1. One short paragraph, 4-5 sentences.
> 2. Modern and direct, written for how hiring managers read today, still bound by the anti-AI checker (`cv-build.md`): real sentence rhythm and precise words.
> 3. No dates, no durations, no "X months/years of": the sections below carry the dates; the paragraph states the *relationship* between what the owner did and what the posting needs.
> 4. Read the title and the JD together and think about what the role means against the real background before writing a word: a fresh synthesis each time, not a fill-in-the-blank.

### 4. The cover letter

> **Standing rules for the letter (defaults), never traded away:**
> 1. **Never repeat the CV.** A fact, a project or a number that is on the CV is not restated in the letter. Refer to the CV only to add a detail it had no room for or to explain what it meant to the owner.
> 2. **Every theme comes from the job description**, not a template. A letter that would read the same for a different posting is wrong.
> 3. **State genuine interest and motivation for *this specific role*, with clear prominence.** Required in every letter; a reader skimming it can point to the sentence that says why *this* role at *this* employer.
> 4. **One page. Always.**

Four paragraphs, never more: (1) why this role at this employer, rooted in something true about the owner's path; (2) JD theme one, a real contact point in the record, what they want from it; (3) JD theme two,
same shape; (4) availability, hours, languages, close.

**Personalization beyond the requirement list:** where the posting or a quick look at the company (product, mission, a specific team or lab, something the posting says about why the role exists) gives a genuine,
specific reason for *this employer*, use it. If nothing specific is available, do not invent one: leave the letter on its requirement-matching structure rather than padding in filler enthusiasm. A gap stated honestly
("I have never seen that done, and I would like to") is stronger than a vague claim of enthusiasm. No metrics, no tool lists, no restated CV lines, no question marks. Formal register and salutation follow the
language and country (`regions/<code>/cv-conventions.md`, `language-quality.md`). Some postings ask for no letter ("upload only your CV"): honour that.

### 5. The match report
Honest, for the owner only, never sent: a requirement table (met / partial / gap), an overall read, how to frame each gap, anything to verify before applying, the briefing answered point by point, the JD's fetch date,
and a **mandatory tailoring diff**: specific ("promoted the sequencing-pipeline bullet above the reporting bullet because the posting names variant calling twice"), never "CV tailored to role", plus every must-tier gap
logged against its pillar. If anything was cut under Exclusion 1 or 2, the diff carries the standardized tag with the real quote; if nothing was cut, no such line is needed.

## Keyword placement (mechanical, not habit)

| Tier | Category | Placement |
|---|---|---|
| must | tool | Skills block (verbatim and the acronym) **and** the first bullet of the most relevant role |
| must | method/domain | Profile summary (top 3-5, front-loaded) **and** skills block |
| preferred | any | Skills block only, and only where real evidence already exists |
| context | soft skill | Never listed bare: only woven into a bullet with a real outcome |
| gap | anything | Never forced onto the CV: becomes an honest bridge in the letter |

## Applying the owner's own briefing (when they press Approve with a note)

Every point in the note gets answered as one of: **followed** (say in one clause how it changed the draft); **impossible against the posting** (follow the posting, say plainly why not); **would require an untrue
claim**: never write it, say so in one line, offer the nearest true thing. This is the one place the briefing does not win.

## Package outputs

Every shipped file carries the owner's name, never a generic filename (an employer cannot tell `CV.docx` from any other candidate's file):

```
applications/<date>_<Employer>_<role-slug>/
  <CV word>_<Name>_<Employer>.docx          the words follow the document language (CV, Lebenslauf, ...; resources/cv_headers.json)
  <letter word>_<Name>_<Employer>.docx      (CoverLetter, Anschreiben, ...)
  cv.md, cover-letter.md                    the markdown sources
  match-report.md                           honest, for the owner only, never sent
  posting.txt                               a copy of jd/<Employer>_<role-slug>/description.md
  submission-checklist.md                   channel, destination, files, subject, reference number, portal Q&A, and what only the owner can decide
```

`bash scripts/ship-package.sh <folder> [--cv-only]` is the only way a package is built (aicheck, consistency check, keyword coverage, build, pagination, fingerprint, PDF render, page dump).
`--cv-only` is for a posting that asks for a CV and no letter, or whose letter the owner must write personally.

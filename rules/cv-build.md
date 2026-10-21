# cv-build.md: visual spec, generator, anti-AI checker, pre-ship checks

*Owns: the visual spec, the markdown-to-docx generator, layout rules, the anti-AI checker and the pre-ship verification. The owner's master CV (`profile/master-cv-<language>.md`, plus their own
.docx if they have one) is the source of truth for content and style; everything here exists to reproduce its look every time and to catch drift before it reaches an employer.*

## Every rebuild produces all three formats

Whenever a CV is rebuilt from its markdown (the master or any application package, through `ship-package.sh` or a one-off `build-cv.js` call), the job is not done until all three exist and are current: the
**.md** (the edited source), the **.docx** (`build-cv.js`) and the **.pdf** (rendered from that docx, e.g. LibreOffice `--headless --convert-to pdf`). A real defect this fixes: after editing several files,
the .docx files were rebuilt but the .pdf files were left stale, so an employer's package carried a PDF of the previous CV. Never treat "I rebuilt the docx" as finishing.

## The default visual spec

Calibri throughout, 2 cm left/right and 1 cm top/bottom margins, name 17 pt bold all caps navy (`1F3864`) centred, a heavier rule (sz 8) under the contact line and a lighter rule (sz 6) under every section
heading (the two constants are named `CONTACT_RULE` and `SECTION_RULE` in `scripts/build-cv.js` because they were once swapped for weeks without anyone noticing), entry dates right-tabbed onto the same line
as the entry title, bullets with a real bullet glyph (●) at body size, not a dash.

| Element | Spec |
|---|---|
| font | Calibri throughout, no second typeface |
| page margins | 1134 twips (2 cm) left/right, 567 twips (1 cm) top/bottom |
| name | 17 pt (sz 34), bold, ALL CAPS, colour 1F3864, centred, after 40 |
| subtitle line | 10 pt, colour 333333, centred, after 60 |
| contact line | 9 pt (sz 18), centred, after 200, links in 1F3864 underlined, bottom border single sz 8 space 6 colour 1F3864 (**CONTACT_RULE**) |
| section heading | 10.5 pt (sz 21), bold, ALL CAPS, colour 1F3864, before 220 after 90, bottom border single sz 6 space 2 colour 1F3864 (**SECTION_RULE**) |
| entry title | 10.5 pt, bold, colour 333333, before 0, after 10 |
| entry date | 9.5 pt, bold, colour 1F3864, right tab stop at 9360, same line |
| sub-line | 9.5 pt, italic, colour 555555, after 80 |
| body paragraph | 10 pt, colour 333333, line 264, after 160 |
| bullets | 10 pt, colour 333333, line 258, after 60 |
| bullet glyph | ● at body size, numbering indent left 720 hanging 360 |

If the owner has their own master .docx with a different look, `python scripts/fingerprint.py learn <master.docx>` measures it into `profile/golden_spec.json`, and the fingerprint check compares every build to
that instead. Without a golden spec the check falls back to a margins-only comparison and says so: do not treat a clean result then as a full pass.

**Shapes, not just measurements:** every Skills line is a bullet, not a paragraph; the Languages line is a bullet; each internship or project is a full entry with its own right-aligned date and italic sub-line,
never a bold run with middle-dot separators. A tailored CV that flattens these measures correctly and still looks wrong.

**No meta-commentary on a skills line.** A category label states what the skill is, never how or where it was confirmed ("Also verified from project work: ..." reads like a disclaimer). Fold every real skill
into its proper category; where it was used already lives in that project's own bullets.

## Pagination: headings must never be orphaned

A section heading, and an entry's title/date line and its sub-line, must never be separated by a page break from at least the first line of content that follows them. `scripts/build-cv.js` sets `keepNext`
on section headings, entry titles and sub-lines (the pass `scripts/keep_pass.py` verifies), so a heading, its entry title and its first bullet always land on the same page. A later bullet may spill onto the next page;
a heading or entry title may never appear with none of its own content under it.

**Use page 1's remaining space before pushing a whole section to page 2.** If page 1 stops after a short section with a large blank area because the next section does not fit, Word and LibreOffice push the entire next
section down. The fix is section ordering, not new generator logic: put a long, bullet-heavy section where page 1 still has real room so its bullets are what split across the break, and save short low-content sections
for the leftover space. Check by rendering and looking at how full page 1 is, not just the page count.

**Merging bullets to save space is not allowed**, and neither is removing `keepNext` from the heading chain (that reopens the orphaned-heading defect). Reordering is the only lever. A single bullet may split across the page break.

**Every CV renders at a maximum of two pages.** This is layout hygiene, not a licence to cut: if the real content does not fit two pages after the layout fix, flag it in the match report and let the owner decide.
A posting's own hard page limit is different: that is Exclusion 1 of the content-regulation rule (`applications.md`) and is honoured.

## Cover-letter header and layout

Every cover letter opens with the identical `# ` / `@ ` markup the CV uses, so the name renders the same way and one visual identity runs across both documents:

```
# <Full name>
@ <City, country>
@ <email> | <phone>

<Employer name>
<Employer department or location, if known>

>> <City>, <date>

**<Role / subject line>**

<Salutation>,

<body paragraphs, per applications.md's four-paragraph shape>

<Closing>,
<Full name>
```

The employer block is plain left-aligned text. The "Place, date" line uses the `>> ` right-align marker, the one place in either document that is not left-aligned or centred. The subject line is bold. What goes in the
header (a postal address or not, a photo or not) follows `regions/<code>/cv-conventions.md`.

## Section order in the master

The owner's own (for example Profile, Work Experience, Projects, Education, Skills, Certifications, Languages). Reorder freely per posting, keep the names and shapes. Every section must be *present* on every tailored
CV; only its position changes (`applications.md`).

## The markdown source language `scripts/build-cv.js` reads

`# ` name · `@ ` centred header line · `## ` section · `### Title ||| Date` entry · `*italic*` sub-line · `- ` bullet · `>> ` right-aligned line · anything else is a body paragraph.

**Four gotchas that each cost a rebuild once:** (1) never hard-wrap a bullet line: the continuation becomes a separate body paragraph that page-breaks independently; (2) put a blank line between consecutive
`**Label:**` skill lines or they merge into one run-on paragraph; (3) single-asterisk italics inside a body line render literally; (4) a `**Label:**` line still needs its own leading `- ` or it silently loses its bullet.

## The anti-AI checker (`scripts/aicheck.py`)

Runs on the markdown sources before the docx is built. Ship condition: `TOTAL: 0`. It catches, among others: **em dashes** (the single strongest tell: never one, anywhere), curly quotes, a long list of AI-vocabulary words
("delve", "leverage", "robust", "holistic", "seamless", "pivotal", "crucial", "tapestry", "myriad", "passionate about", "cutting-edge", "unlock", "synergy", and more), "Additionally/Moreover/Furthermore" opening a sentence,
"not just X but Y", trailing "-ing" analysis clauses, an un-earned rule of three, enthusiasm filler ("excited to", "thrilled"), CV cliches, and, as a hard stop, **any question mark in a cover letter file**. Beyond the
mechanical rules: vary the sentence rhythm; an occasional hedge ("I suspect", "I have not done this part yet") reads as a real person; uniform polish is itself a tell.

## The consistency checker (`scripts/consistency_check.py`)

Covers what the anti-AI checker cannot: document structure and whether a CV and its own cover letter agree. Same `TOTAL: 0` ship condition:

- **header_structure**: `cv.md`'s `## ` headings are a clean set of one language's (`resources/cv_headers.json`), never mixed, never duplicated, with the Profile section present.
- **orphan_stray_line**: the paragraph under the Profile heading is not a suspiciously short fragment (the signature of a botched heading split).
- **cv_letter_language**: the cover letter's salutation and closing language match the CV's language.
- **no_cut_completeness**: every real bullet of the master CV (`profile/master-cv-<language>.md`, matched to the CV's language) survives into `cv.md`, reword-tolerant (a paraphrase found by word overlap counts).
  Relaxed to an informational finding only under a valid content-regulation exemption tag (`applications.md`). The Profile paragraph is never part of this check.
- **locked_term_dropped**: every locked term (`profile/locked_terms.json`) of a reworded master bullet still appears unchanged in the bullet it landed in.
- **encoding_corruption**: no Unicode replacement character in either file.
- **profile_date_leak**: no date or duration marker inside the Profile paragraph.
- **letter_metric_leak**: none of the CV's own multi-digit numbers or percentages is restated in the letter.

## The ship gate (`scripts/ship-package.sh`)

`bash scripts/ship-package.sh <application-folder> [--cv-only]`, in this order, stopping at the first failure: aicheck, consistency check, keyword coverage (`rank_skills.py check`), build (.docx), keep_pass, fingerprint,
PDF render (LibreOffice), verify_pdf (page-by-page dump). Never hand-build a package outside this order.

**Before anything goes to an employer, a person reads it:** open the .docx or PDF and read every page; check that the header follows the region's convention; point to the exact sentence in the letter that states interest in
*this* role; write `match-report.md` and `submission-checklist.md`.

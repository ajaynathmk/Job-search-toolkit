# regions.md: region packs, and how to research a country that does not ship one

*Owns: what a region pack contains, how several packs combine, and the procedure a Claude session follows to write a pack for a country the toolkit does not ship. Shipped packs: `de` (Germany), `eu` (Europe beyond the
home market), `us` (United States).*

## What a pack is

A folder `regions/<code>/` (or, for one the toolkit does not ship, `profile/regions/<code>/`, git-ignored) with:

| File | Holds |
|---|---|
| `region.json` | where the search happens and how it is judged: countries, languages, route rules, walls, boards, mail patterns (the schema below) |
| `sources.json` | what the watches poll in that region: `national_board`, `institutions` (optional, see `rules/institutions.md`) |
| `legal.md` | the legal basis, with sources, for a foreign student or graduate to work there; what the route rules apply |
| `cv-conventions.md` | name and length of the CV, cover letter, photo, personal details, dates, salary, portals |
| `countries.md` (optional) | country-by-country notes for a multi-country pack |

`profile.regions` lists the packs, **home market first**: `["de", "eu"]` means Germany is the home market (its primary countries, languages and defaults rule) and the `eu` pack widens the scope with its own route rules, walls and
boards for the other countries. A pack that is not the first only adds; it never changes the home market. `profile/region.override.json` overrides any key of the merged result (for example to narrow `scope_countries`).

## `region.json` schema

| Key | Meaning |
|---|---|
| `code`, `name`, `home_country` | the pack's id, its display name, the ISO code of the home market |
| `primary_countries` | countries a role can be applied to right away; roles in other in-scope countries are PLAN, not APPLY |
| `scope_countries` | countries searched at all; a posting elsewhere is a wall |
| `local_languages` | language codes of the home market (checked against the levels in the profile) |
| `date_order` | `dmy` or `mdy`, for ambiguous dates in postings |
| `local_sources` | watch sources whose postings count as home-country when no place is readable |
| `country_hints` | `{ISO: regex}` city and region words that identify a country in a location string |
| `routes` | `{route id: display name}`: the closed vocabulary of `work_route` |
| `route_rules` | the work-authorization scoring: the first rule whose `when` holds gives the `adj` (added to the score) and the `route` |
| `route_default` | when no rule matched |
| `walls` | things a posting can demand that the applicant cannot meet |
| `mail` | `alert_queries`, `alert_senders`, `query_words` for the Gmail pass |
| `boards` | the job boards to sweep, with URL templates (`{kw}`, `{city}`, `{country}`) and notes |
| `cv_conventions`, `legal_notes` | paths of the two documents |

**`when` keys** (all ANDed): `authorization` (list of profile statuses), `country`, `not_country` (ISO lists; `__home__` = the home market), `kind` (role kinds), `stage` (career stages), `employer_re`, `url_re`, `source_re`, `text_re`,
`not_text_re` (regular expressions on the folded text), `needs_authorization` (bool), `any` (a list of alternative `when` objects; one must hold). **A wall** has `label`, `re`, optional `unless_re`, `when`, `route_block` (true = "no legal
route": the role scores -4 and is stored `none_found`). Patterns are written in plain letters (umlauts and accents folded: `ae oe ue ss`, `e` for an accented e) and are matched against the folded text of the **full** posting.

Work-authorization statuses (`profile.work_authorization.status`): `citizen`, `permanent_resident`, `unrestricted`, `eu_citizen` (no rules apply); `student_visa`, `opt`, `work_visa`, `needs_sponsorship` (the rules apply).

## The procedure for a new country (`/region <country>`)

1. **Scaffold:** `python scripts/onboard.py scaffold-region <code> "<Country>"` copies `regions/_template/` to `profile/regions/<code>/`.
2. **Research the legal basis** from official sources only (the immigration authority, the education ministry, the university's international office; use WebSearch and WebFetch). For the owner's work-authorization status
   find: student work limits and what counts toward them; internship rules (mandatory vs voluntary); a thesis or research placement at a company; post-study permits (job search, skilled worker, the salary threshold); employer-sponsorship
   routes. Write `legal.md` with a table of rule, source (act, article, URL) and effect. **Do not state a figure you did not read on the official page; say "check the current threshold at <URL>"** and give the date researched.
3. **Write the route rules** so that each route the law allows is a rule: +1 when the route costs the applicant nothing, 0 for an ordinary route, -1 for a route that needs sign-off or an extra permit, -3 for a role that needs an employer
   permit with no named route, -4 for none found. Give every rule a `note` that names the reason in a sentence; the note is shown on the card.
4. **Walls:** the country's usual hard demands (citizenship for public-sector roles, security clearance, a regulated credential, a local-language level handled by the language checks, "no sponsorship" for someone who needs one).
5. **Boards:** the country's main general boards, the best student or graduate board, the academic job portal, whether LinkedIn is used, and which of them can be read without a login. Put URL templates and notes in `boards`. Test each
   (`WebFetch`) and say in the note if a plain fetch is refused.
6. **Mail:** the boards' alert senders (so the Gmail pass files their alerts) and the local words for application, rejection, invitation (`profile/mail_patterns.json`).
7. **CV conventions:** document name, length, photo, personal details, date format, cover-letter habits, salary, and the applicant systems common there. Add the language to `resources/cv_headers.json` if it is missing.
8. **Languages:** if the country's language has no checklist in `rules/languages/`, write `profile/language-<code>.md` (see `rules/language-quality.md`) and make sure it is in `resources/languages.json` (anchors and the phrases for "native",
   "fluent", "required", "advantage"); add the language's country entry to `resources/country_languages.json`.
9. **Validate:** `python scripts/onboard.py check`, then run `python scripts/onboard.py demo` or analyse two or three real postings from the region (`/daily`) and read the verdicts: a wrong wall or route is fixed in `region.json`, not worked around.
10. **Tell the owner what is unverified.** Every pack ends with the list of facts that came from a secondary source or that must be confirmed with an authority before an application is built around them.

## Contributing a pack

A pack for a country others could use belongs in `regions/<code>/` in the toolkit repository: copy it out of `profile/regions/`, remove anything personal (there should be nothing), run the tests, and open a pull request.

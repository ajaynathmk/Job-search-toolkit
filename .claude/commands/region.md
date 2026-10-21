---
description: Research a country and write its region pack (work rights, walls, boards, CV conventions), or refresh an old one
argument-hint: "<country name or ISO code>"
---

Country: $ARGUMENTS

Follow the procedure in `rules/regions.md` ("The procedure for a new country"). In short:

1. If a pack ships (`regions/<code>/`), say so and ask whether to refresh it or use it; a refresh re-reads the official sources and updates `legal.md` and the route rules with dates.
2. Otherwise `python scripts/onboard.py scaffold-region <code> "<Country>"` and fill `profile/regions/<code>/` from official sources only: the immigration authority, the education ministry, the university's international office. Use WebSearch and WebFetch;
   search with country and topic words, never with the person's name or data. Read the page before you cite it; give act or article and URL; state the date researched. **Do not state a figure you did not read.**
3. Write the route rules for the person's `work_authorization.status` (`+1` free route, `0` ordinary, `-1` needs sign-off or an extra permit, `-3` employer permit with no named route, `-4` none), the walls, the boards (test each with WebFetch and note
   whether a plain fetch works), the mail patterns and alert senders, the CV conventions, and, if the language has no checklist, `profile/language-<code>.md`.
4. Validate (`python scripts/onboard.py check`), add the pack to `profile.regions` (home market first), and analyse two or three real postings from that country with the person. Fix the pack, not the verdict.
5. End with the list of what is unverified or came from a secondary source, and what to confirm with an authority before building an application around it.

Offer to contribute the pack to the toolkit (`regions/<code>/`, nothing personal in it) if it would help others.

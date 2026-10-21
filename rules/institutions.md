# institutions.md: universities, research institutes and hospitals as an employer and thesis source

*Owns: how the institution watch (`scripts/uni_watch.py`) works, what each kind of institution can offer, and how to extend the list for a region. If you are not a student or an academic, you can leave this watch on (it is
free) or empty the `institutions` list in `profile/sources.json`.*

## What it polls

`regions/<code>/sources.json` lists institutions with an adapter each (the German pack ships about 280: universities, university hospitals, research institutes, public bodies). Your own additions go in `profile/sources.json`
under `institutions`. Adapters (cheapest and most reliable first), all read without a browser:

| Adapter | What it is |
|---|---|
| `bite_api` | the JSON API of the b-ite job-portal platform (about 30 German institutions): one POST per listing, exact title, start and end dates (= deadline), employer, address, category |
| `bite_site` | b-ite sites that expose only a host name: list page, then `/jobposting/<hash>` links |
| `adsapi` | b-ite `adsapi/jobads?apikey=` JSON |
| `rss` | job-specific RSS or Atom feeds |
| `sap_rss` | SAP SuccessFactors recruiting RSS (`/services/rss/category/?catid=`) |
| `html_list` | plain HTML list pages (anchors plus dates) for sites with no feed or API; `include` is a regex that keeps only anchors that look like postings |

Anything not reachable this way is covered by the browser sweep in a Claude session. The watch never writes the tracker: it writes `data/watch/<date>.json`, `data/watch/seen.json` and `digests/institution-watch-<date>.md`; intake files the postings.

## What each kind of institution can offer

| Want | Where it is usually posted | Notes |
|---|---|---|
| **Student or research assistant** (a few hours a week) | the institute's own page, the central job page, a student job board | Most never reach LinkedIn: this is the main blind spot of a board-only search. Check whether the hours count against your work-authorization allowance (`regions/<code>/legal.md`). |
| **Working student** at the institution | mostly university hospitals and research centres | hospitals post on their own career portals |
| **Internship** | institute pages, the internship section of a hospital's career portal | a voluntary internship may count against your allowance |
| **Thesis** | a direct letter to a professor or group leader; the group's "open positions / theses" page; your own supervisor route | the thesis is the mandatory element of a master's, so it may also unlock a thesis-abroad route |
| **Any other job** | the central job board | doctoral and postdoctoral positions are out of scope unless your profile says otherwise |

## Writing to a group (a thesis lead)

A thesis row is only created after the page was opened and read; the supervisor's name, role and e-mail come from the group's own page (never from a search snippet: a snippet's contact differed from the page once);
the group's work comes from its own pages; publications from PubMed or the group page with their DOI; the fit reasoning names evidence ids from the master profile and the gaps. Outreach is **drafted, never sent**.

## Extending the list for your region

1. Find the institutions' job pages (the university's HR or "work with us" page, the hospital's `karriere.*` portal).
2. Identify the platform: view source for `b-ite.com`, look for an RSS icon or `/rss`, look for SuccessFactors `/services/rss/`. Prefer a feed over scraping a list page.
3. Probe it (`python scripts/uni_watch.py --only rss --no-write`), and add it to `profile/sources.json` under `institutions` only if it returns real postings.
4. For another country, `/region` researches the national equivalents (a national academic job portal, the research-council's board, the university job platforms) and writes them to `profile/regions/<code>/sources.json`.

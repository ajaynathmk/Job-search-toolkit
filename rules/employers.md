# employers.md: adding an employer to the watch

*Owns: the procedure for finding an employer's postings in a form the company watch (`scripts/job_watch.py`) can read, and where the result is recorded. The employers the toolkit already knows (with verified endpoints) are
in `resources/employers.json`, tagged by industry; `python scripts/onboard.py build-sources` copies the ones matching your industries into `profile/sources.json`.*

## The procedure

1. **Find the careers site.** Search for `<employer> careers` and open the employer's own page (never an aggregator's copy).
2. **Identify the applicant system** from the address or the page source:
   - `*.myworkdayjobs.com` or `*.wd<N>.myworkdayjobs.com` is Workday: tenant = the first label, `wd` = the number, site = the path segment after `/en-US/` or the locale (for example `Careers`).
   - `boards.greenhouse.io/<slug>` or `job-boards.greenhouse.io/<slug>` is Greenhouse: slug.
   - `jobs.lever.co/<slug>` is Lever. `jobs.smartrecruiters.com/<Company>` is SmartRecruiters. `<slug>.recruitee.com` is Recruitee.
   - `*.successfactors.*`, `*.personio.*`, `*.softgarden.io`, `join.com`, `ashbyhq.com`, `teamtailor.com`: no public JSON feed the watch reads; they stay in the browser sweep (or an RSS feed if the page offers one).
3. **Probe it.** Workday: `POST https://<tenant>.wd<N>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs` with `{"appliedFacets":{},"limit":20,"offset":0,"searchText":"intern"}` must answer with a `total` and `jobPostings`.
   Greenhouse: `https://boards-api.greenhouse.io/v1/boards/<slug>/jobs`. Lever: `https://api.lever.co/v0/postings/<slug>?mode=json`. SmartRecruiters: `https://api.smartrecruiters.com/v1/companies/<slug>/postings`.
   Recruitee: `https://<slug>.recruitee.com/api/offers/`. A guessed identifier almost always fails: only keep one that returned real postings.
4. **Add it** to `profile/sources.json`: `workday` gets `{"institution", "tenant", "wd", "site"}`; `ats` gets `{"adapter", "institution", "slug"}` (SmartRecruiters also `terms`: the words to search).
5. **Check it:** `python scripts/job_watch.py --only workday --no-write` (or the adapter) and read what comes back. If it returns nothing for your levels, that is a fact about the employer, not a bug.
6. **Priority employers.** To give an employer the +2 score point add a lower-case word of its name to `domain.priority_employers`; to make it count as "your industry" for adjacent-skill roles add a word to `domain.industry_regex`.

## Where to find employers for your field

Ask `/start` (it researches them when it writes `domain.json`): the largest employers of your field in your region, the professional bodies' member lists, the graduate-recruiting pages of the region's universities, and the
companies that post your field's roles on the boards. List them in `domain.priority_employers`, then run the procedure above for the ones that matter.

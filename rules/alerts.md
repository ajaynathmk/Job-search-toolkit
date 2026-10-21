# alerts.md: job alerts on LinkedIn and every other board

*Owns: which alerts to create, how to build their search strings from your own configuration, and how the alert e-mails reach the pipeline. Alerts are created by **you** (or by a browser agent driving your own logged-in
browser, such as Claude in Chrome); the toolkit never logs in to a job board. Alerts are a **discovery source only**: every role still goes through the JD-first rule and THE LINK RULE before it reaches the tracker.*

## Why alerts at all

Alerts do the repetitive searching for free and arrive in Gmail, where `scripts/mail_sync.py` (`rules/mail.md`, stage S11) reads them every run and files every posting at your levels as an unscored row. Boards that cannot be read
without a login (LinkedIn, Xing) are best reached this way. An employer's own alert is the best kind, because its links already pass THE LINK RULE.

## Settings that apply everywhere

- Frequency daily (or "as soon as available"); delivery by e-mail to the address in `profile.email`.
- Use the experience-level filter that matches `profile.levels_sought` (Internship and Entry level for students and new graduates; Mid-Senior for experienced searchers). Leave the job-type filter unset where a role kind is tagged
  inconsistently (working-student roles are tagged part-time, internship or contract at random).
- A Gmail filter per source (label `JobAlerts/<Site>`, skip the inbox) keeps the inbox clean; the pipeline reads by sender, not by label.
- Review every 14 days: an alert with no relevant role in three weeks is replaced, not kept. Change one alert at a time and log it in `profile/alerts.md`.
- Alerts that go unviewed lapse (LinkedIn disables one left unviewed for 90 days; the pipeline reading the e-mail does not count as viewing). Open the alerts page about once a month.

## LinkedIn: a budget of 20

LinkedIn caps an account at 20 alerts. Boolean works in the keyword box (`AND`, `OR`, `NOT` in capitals, quotes for phrases, parentheses); if LinkedIn rejects a long string, drop the rarest synonyms first. LinkedIn does not let you
name an alert: it is identified by its keyword and location text, so keep the table below in `profile/alerts.md` to trace an alert e-mail back to its row.

**How to build the set** (Claude does this in `/start` and writes it to `profile/alerts.md`; ask `/daily` to refresh it):

1. **Home market, one alert per core sub-field.** Role words of the region for your kinds (from `config.board_queries`: for Germany "Werkstudent OR Praktikum OR Masterarbeit", for the U.S. "intern OR entry level") AND the
   terms of the sub-field (`domain.subfields[].aliases` and the labels), with `NOT` for the flood that does not fit you (a profession's trainee-year pattern, for instance).
2. **One catch-all for your priority employers** (`domain.priority_employers`) with the role words.
3. **One alert per other country in scope**, in that country's language and its role words (`rules/regions.md`, country notes), plus an English catch-all for the rest of the region.
4. **Keep two spare** for trying a new term.

Example shape (home market, a bioinformatics student in Germany):

| # | Location | Keywords |
|---|---|---|
| G1 | Germany | `(Werkstudent OR "Studentische Hilfskraft") AND (Bioinformatik OR Bioinformatics OR Genomik OR "Computational Biology")` |
| G2 | Germany | `(Masterarbeit OR "Master Thesis" OR Abschlussarbeit) AND (Bioinformatik OR Bioinformatics OR "Machine Learning")` |
| E1 | France | `(stage OR "stage de fin d'etudes") AND (bioinformatique OR genomique) NOT alternance` |
| E8 | European Union | `(internship OR "master thesis" OR trainee) AND (bioinformatics OR "computational biology" OR genomics)` |

## Other boards

Per board, one alert per core sub-field in the board's own search syntax. Indeed works best with broader two- or three-word phrases (narrow compounds can return nothing); Xing and StepStone-type boards take phrases or Boolean
depending on the board; employer-site alerts (careers pages that offer "notify me") are the best. The region pack's `mail.alert_senders` and `mail.alert_queries` make the Gmail pass recognise each board's sender; confirm a sender
address from the first alert that arrives and add it to `profile.mail.alert_senders` if it is not already covered.

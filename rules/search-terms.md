# search-terms.md: choosing the search words that actually work

*Owns: how the keyword list for board sweeps, the national-board queries and the alerts is built, how it is judged, and where your own evidence goes. The words themselves are yours: they live in `profile/domain.json`
(`search_terms`, the sub-fields' `aliases`) and in `profile/search-terms.md` (your yield log). Nothing in the toolkit ships a keyword list for a field.*

## Where the terms come from

1. `/start` writes `domain.search_terms` (short phrases, two or three words: the field's name and its common synonyms) and each sub-field's `aliases` (the words that appear in titles) from your CV and the field research.
2. The region pack's role words (`resources/levels.json` for the kinds you look for, in the region's languages) are put in front of those terms by `config.board_queries`: "Werkstudent Bioinformatik", "Praktikum Bioinformatics",
   "intern data analyst".
3. You add terms that proved themselves (below) and retire the ones that did not.

## Rules of thumb

- **Precision beats count.** A term returning 20 rows of which 15 are real is worth more than one returning 60 of which 3 are.
- **Language matters as much as the term.** Employers in a local-language market post in that language even for English-friendly roles; multinational teams and consultancies post in English. Run both forms of each term.
- **Two or three words.** Boards differ: some match phrases exactly, some break on long Boolean strings, some return nothing for a narrow compound. If a term returns zero, try the broader English form before concluding there are no roles.
- **Titles name roles; descriptions name skills.** Search on the title words, then let the analysis read the description. A skill word alone (a tool name) returns jobs that merely mention it.
- **Remove the flood.** Where a word drags in a profession's mandatory trainee-year or an unrelated trade, add a `NOT` term (alerts, Boolean boards) or an `exclude_titles` entry in the profile (the watches).
- **A zero is a fact about the board or the term, not about the market.** Say which.

## Keeping a yield log

`profile/search-terms.md` (git-ignored) is a table: term, board, date, results, relevant, what it found. Review it every two weeks (`/daily` prompts for it). A term with no relevant result in three weeks is retired; a term that found
something becomes a permanent alert or a `search_terms` entry. The scheduled watches track their own counts in `data/watch/` and `data/jobwatch/`.

## Terms for adjacent and income roles

If `profile.accept_unrelated_income` is true, `domain.income_context_re` says what makes an unrelated-industry role acceptable (for instance, analytics work on health data) and the verdict BACKUP applies. Add one or two broader
terms for those, kept narrow enough not to flood the list.

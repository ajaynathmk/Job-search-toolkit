# Contributing

Thank you. The most useful contributions, in order: **a region pack for your country**, a language (anchors and phrases in `resources/languages.json`, a checklist in `rules/languages/`), an employer-feed adapter, and bug reports with a reproduction.

## Ground rules

1. **No personal data, ever.** Fixtures use invented people (`Sam Example`), `example.org` addresses and made-up employers. Run `python scripts/privacy_scan.py --also "<your name>" --also "<your city>"` before every commit.
2. **The engine knows no country, field or person.** Anything specific to a place belongs in a region pack; anything specific to a field belongs in a domain file. A pull request that adds a country name or a profession to a script will be asked to move it.
3. **Every behaviour change has a test**, and `python scripts/tests/run_all.py` is green on your machine.
4. **Log the change** in `CHANGELOG.md` under the open version, one line.
5. **Respect the non-negotiables** in `CLAUDE.md`: nothing submits an application, the only mail sent is the owner's own digest, `my_notes` is the owner's, no score without the full text.
6. **Legal facts need a source.** A region pack states the act or article, the URL and the date it was read; a figure you did not read on the official page does not go in.

## A region pack

`/region <country>` in Claude Code produces `profile/regions/<code>/`. To contribute it: copy it to `regions/<code>/`, delete anything personal (there should be nothing), make sure `python scripts/onboard.py check` passes with a profile that lists it, add two fictional postings and a profile to `examples/` if it
exercises new rules, run the tests, and open a pull request that names the sources you used.

## Reporting a bug

Include the command, its full output and `python scripts/onboard.py doctor`. If it is about a posting, the posting's URL. **Never** paste your profile, your tracker, your mail or any token.

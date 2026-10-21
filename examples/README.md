# Examples

Three **fictional** people, in three situations and three fields, each with a profile, a domain file and a handful of invented postings. They exist to show what the configuration looks like, to let you try the analysis before you give the toolkit any real data, and as the fixtures of the tests.
Nothing in here is real: the people, the employers (`Example ...`), the addresses (`example.org`) and the postings are made up.

| Example | Person | Region | Field | Shows |
|---|---|---|---|---|
| `de-bioinformatics-student/` | Sam Example, a non-EU master's student in Germany | `["de", "eu"]` | bioinformatics, biostatistics, ML for biology | thesis and student-assistant routes, a language wall (German C1 vs A2), a clearance and citizenship wall, a role abroad, an information page that is not a posting, an expired deadline |
| `eu-mechanical-engineer/` | Chris Sample, an experienced EU citizen in the Netherlands | `["eu"]` with primary countries NL and BE | mechanical design, FEM and CFD simulation, manufacturing | no work-authorization rules (EU citizen), mid and senior roles, postings in Dutch, French and German judged against native Dutch, B2 French and no German; a role in another country is PLAN |
| `us-data-analyst/` | Jordan Sample, a new graduate on OPT in the United States | `["us"]` | analytics, statistics, data engineering | entry-level on OPT, a "no sponsorship" posting, a clearance wall, a senior role that is not sought, an off-field role |

## Try it

```bash
python scripts/onboard.py demo                              # the German student
python scripts/onboard.py demo --example us-data-analyst    # the American analyst
python scripts/onboard.py demo --example eu-mechanical-engineer   # the experienced engineer, postings in three languages
python scripts/onboard.py check --profile-dir examples/us-data-analyst
```

The demo reads each file in `postings/`: a few `key: value` lines (`title`, `employer`, `location`, `country`, `url`), a line `---`, then the posting text. It runs the same analysis the daily pipeline runs (walls, language levels, field, CV comparison, score, route, verdict) and prints the result.
It touches no database and none of your data.

## Make your own from these

`/start` writes the same three files for you from your CV. To see the shape: `profile.json` (who), `domain.json` (what; compare the two to see how a field is described) and the region pack (`regions/de/region.json`, `regions/us/region.json`) for where.

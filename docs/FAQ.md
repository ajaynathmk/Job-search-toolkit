# FAQ

**Does it apply for jobs for me?** No. It finds and judges roles, builds a tailored CV and letter when you approve one, and leaves a Gmail draft or a checklist. You submit. This is a rule enforced in code, not a setting.

**Does it work outside Germany?** Yes. Germany, Europe and the United States ship ready. For any other country `/region <country>` makes Claude research the rules from official sources and write a pack with you, with dates and the list of what is unverified.

**I am a citizen / permanent resident. Do I need the work-authorization parts?** No. Set `work_authorization.status` to `citizen`, `permanent_resident`, `eu_citizen` or `unrestricted` and no route rule applies: no point is added or removed for your right to work and no
"no sponsorship" wall can block you.

**I am not a student.** Set `career_stage` to `experienced`, `new_grad` or `career_change`; `levels_sought` follows (entry, mid, senior; or internship, trainee, entry). Student-only pieces (the thesis table, institution watch) stay quiet or can be removed from your sources.

**What field does it support?** Any. The field is whatever your CV and `domain.json` say: biology, software, finance, mechanical engineering, nursing, design. The quality depends on the terms in `domain.json`, which `/start` writes from your CV and checks with you on real postings. If verdicts
look wrong, the fix is in that file (`onboarding/domain-inference.md`), not in the code.

**Why does it read whole postings?** A title and a snippet tell you almost nothing: the language level, the right-to-work wall, the required tools and the deadline are in the body. Scores from titles are noise. The database refuses a score without the cached text.

**Can I trust a verdict?** It is a recommendation. The script quotes the sentence for every wall and lists what your CV covers and lacks; for every best fit a Claude session then reads the whole posting and confirms or overrides. You decide.

**It marked something BLOCKED that I could take.** Read the quoted sentence (`/review` shows it). If it is wrong, override it (`analyze.py review`) and tell Claude to fix the wall's pattern in `domain.json` or the region pack so it does not happen again.

**Is my CV sent anywhere?** No. It is read from disk by Claude Code in your session (under your Anthropic account) and written to `profile/`, which is git-ignored. Web searches use field and country words only. `docs/PRIVACY.md`.

**Do I need Gmail?** No. Without it you mark applied, interview and rejected by hand on the dashboard, and the digest is only written to `digests/`. With it, the pipeline sees what you sent and what came back, and turns alert mail into rows. It reads only.

**Can it run on a Mac or Linux?** Yes: `scripts/scheduler.py` uses launchd or cron there; `scripts/ship-package.sh` needs bash (Git Bash on Windows) and LibreOffice for PDFs.

**The daily run does nothing on my laptop.** By default it waits for the charger. `python scripts/pipeline.py run --ignore-power` ignores that, or edit the scheduled command.

**Google says "unverified app" / the token keeps expiring.** `docs/GMAIL.md`, "The 7-day expiry".

**How do I add an employer?** `rules/employers.md`. **A language?** `docs/ARCHITECTURE.md`, "Extending it". **A country?** `/region`.

**How do I move to a new version?** `git pull`. Your data is in ignored folders and is untouched. If a new version changes the analysis rules, the next run re-analyses every role and flags the scores that moved.

**Is this legal advice?** No. The region packs summarise public sources with dates and links; check with the authority before relying on any rule.

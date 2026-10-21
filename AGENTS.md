# AGENTS.md

This repository is a job-search toolkit driven by an AI coding agent. All instructions for agents are in [`CLAUDE.md`](CLAUDE.md): read it first. In short:

- If `profile/profile.json` does not exist, the person has not been set up: follow `onboarding/README.md`.
- Never submit an application, never send mail to an employer, never write `my_notes`, never score a posting you have not read in full, never invent a skill or a legal fact.
- Personal data lives in the git-ignored `profile/`, `db/`, `jd/`, `applications/`, `data/` and `config/` folders: never commit it, never put it in a web search. Run `python scripts/privacy_scan.py` before committing.
- The rules are in `rules/`; the system is described stage by stage in `rules/pipeline.md`.

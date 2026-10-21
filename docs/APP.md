# The application: a CV in, your jobs out

`python app.py` opens a page in your browser. You give it your CV and nothing else; it does the rest and shows you the jobs worth your time, with the reason for each.
It is the same toolkit as the slash commands (`/start`, `/daily`, `/review`, `/apply`), driven from a page instead of a terminal session.

## What you need

| | |
|---|---|
| Python 3.10 or newer, and `python -m pip install -r requirements.txt` | the engine and the page |
| **Claude Code**, signed in with your **Claude account** (a Pro or Max subscription) | the judgment steps. Install from claude.com/claude-code, type `claude` once in a terminal and sign in |
| Playwright (optional) | LinkedIn and Xing searches. `python -m pip install playwright playwright-stealth` then `python -m playwright install chromium` |
| Node.js (optional) | tailored CVs and cover letters as Word files |

`python app.py --check` says which of these are ready. The page says it too, in plain words, before you start.

## Start it

```
python app.py                  # opens http://127.0.0.1:5057
```
On Windows you can double-click `start.bat`; on macOS or Linux `start.command`.

1. **Your CV.** Choose a PDF, Word, Markdown or text file, or paste the text. Optionally add a few lines on what you want (roles, countries, a start date, things you will not do): what you write beats what is guessed from the CV.
2. **Find my jobs.** The steps run one after another and the page shows each:

| Step | Who does it | What happens |
|---|---|---|
| Understand your CV | Claude | works out your field, your strongest and adjacent sub-fields, what the CV proves, where to search; fills in everything the CV does not say with a default and lists it as an assumption |
| Check the configuration | script, Claude repairs | validates the three configuration documents; at most two repairs |
| Find the employers | script | employer feeds for your industries, and the Boolean board queries |
| Collect postings | scripts | employer feeds, universities, national boards, LinkedIn and Xing |
| Read every posting in full | scripts | files every student-level posting, fetches its **full text**, checks walls (language, work rights, enrolment), scores it against your CV |
| Confirm the best fits | Claude | reads each best fit in full again against your CV and confirms or overrides the verdict, with a read receipt the database requires |

3. **Correct what was guessed.** The page shows what it understood and the assumptions, with a "check this" marker on the uncertain ones (your right to work, languages, countries). Change them and press *Save and re-score*: every posting is judged again straight away.
4. **Your jobs.** Ranked by verdict and score. Each card gives the reason, what your CV shows, what it does not, the deadline and the posting's link. *Approve and write my application* builds a tailored CV and cover letter for that one role; you read them and send them yourself. *Not for me* removes a role.

A first run takes from ten minutes to a couple of hours, depending on how many postings there are to read. You can close the page: the run is its own process, progress is saved after every step, and starting again resumes at the first step that is not done.

## It runs on your Claude subscription

- No API key is asked for or stored. The application starts `claude -p` in the background, which uses the login you made in Claude Code.
- If an `ANTHROPIC_API_KEY` (or a Bedrock/Vertex setting) exists on your machine, it is **not** passed on: Claude Code would bill it instead of your subscription. `JOBKIT_ALLOW_API=1` lifts that for someone who wants it.
- The page shows the usage of a run as a dollar figure at list price. On a subscription that is not a charge; it is how much of your plan the run took. The **usage cap** (default 8) stops a run before it takes more; *Best fits to re-read in full* (default 30) limits the review step.
- A call is kept lean (about $0.035 for a trivial one): no connected tools, no memory, no skills, no saved session. A bare `claude -p` loads everything on your account and cost $0.68 for the word "OK".
- If your plan's own usage limit is reached, the run stops with a message and carries on when you press Start again (finished steps and finished reviews are kept).
- `JOBKIT_CLAUDE_MODEL=haiku` uses a cheaper model (weaker judgment); the default is `sonnet`.

## Where your data is

Everything stays on this computer. Your CV and the configuration written from it are in `profile/`; the tracker is `db/tracker.db`; postings are in `jd/`; packages in `applications/`; logs in `logs/`. All are git-ignored.
What leaves the machine: the searches (field and place words, never your name or CV), the postings it fetches, and the text Claude Code reads in the steps above (it is sent to Anthropic by Claude Code, as in any Claude Code session; the saved session is switched off). The page binds to `127.0.0.1` and refuses requests whose Host or Origin is another website.

It never submits an application, sends a message to an employer or creates an account. The only mail it can send is the daily summary to your own address, and only if you connect Gmail and press the button.

## The rest of the toolkit, from the same page

*More* at the bottom of the results: a daily run by itself (`scheduler.py`; it collects and re-scores without Claude), the daily summary e-mail (preview and send to yourself), Gmail status (`docs/GMAIL.md`), the phone inbox (`docs/PHONE.md`) and the tools on this computer. The full dashboard (Today, Jobs, Thesis, Inbox) is at `/today`.

## If something goes wrong

| You see | Do |
|---|---|
| "Claude Code is not installed" or "not logged in" | install it, run `claude` once in a terminal, sign in with your Claude account, reload the page |
| "logged in, but not with a Claude subscription" | `claude auth login` and choose the Claude account |
| "There is almost no text in this CV" | a scanned PDF has no text; paste the text or upload a Word/text version |
| "Your Claude plan's usage limit is reached" | wait for the reset, press Start again |
| "The run stopped before it finished" | the computer slept or the window was closed; press Start again |
| a country without a ready-made pack | the page lists the ready ones (de, eu, us); another country needs its rules researched first (`/region <country>` in Claude Code) |
| LinkedIn and Xing give nothing | Playwright is not installed (`onboard.py doctor`); the other sources still run |

Logs: `logs/app-run.log`, `logs/claude-*.json` (the answer and the numbers of every Claude call; never the CV text).

## For developers

`scripts/claude_runner.py` (the headless Claude), `scripts/app_core.py` (stages, state, results, corrections, tailoring), `scripts/app_routes.py` (API), `scripts/webapp_static/start.*` (page), `scripts/board_sweep.py` (board queries), `onboarding/app/*.md` (the four prompts).
Tests need no network and no subscription: `python scripts/tests/test_app.py`, `test_app_web.py`, and `test_app_ui.py` (a real browser; skipped without Playwright). `JOBKIT_CLAUDE_BIN` points the runner at `scripts/tests/fake_claude.py`.

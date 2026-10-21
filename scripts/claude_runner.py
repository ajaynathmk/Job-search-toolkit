#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/claude_runner.py: run Claude Code in the background for the steps that need judgment.

The application (`app.py`) takes only a CV. The steps that cannot be done by a script (understanding a CV in any field, confirming a
verdict after reading a posting in full, writing a tailored CV and letter) are done by Claude Code started headless (`claude -p`) in this
folder, following the same procedures a person would follow in a session (`onboarding/README.md`, `.claude/commands/*.md`). It uses the
person's own Claude Code login: no API key is needed and none is stored.

Lean by design. A bare `claude -p` loads the user's whole Claude setup (every connected tool, memory, skills): measured on 21 Oct 2026 at 169,000
input tokens and $0.68 for the word "OK". With the flags below the same call is 8,500 tokens and $0.035. Never remove them.

    python scripts/claude_runner.py status        is Claude Code installed and logged in (prints JSON)
    python scripts/claude_runner.py ask "text"    a one-line smoke test (costs a few cents)

JOBKIT_CLAUDE_BIN points at another executable (the tests use scripts/tests/fake_claude.py), so nothing here needs the network to be tested.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"

# Everything that keeps the call small and private. --strict-mcp-config with an empty server list drops every connector,
# --disable-slash-commands drops the skills list, --no-session-persistence keeps the CV out of Claude's saved sessions.
LEAN_FLAGS = ["--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands", "--no-session-persistence"]
LEAN_ENV = {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "PYTHONIOENCODING": "utf-8"}

# The application runs on the person's Claude subscription (the login of `claude`), never on an API key. If one of these is set on the machine, Claude Code would
# silently bill it (or another cloud) instead of the subscription, so the child process never sees them. JOBKIT_ALLOW_API=1 lifts this for someone who wants it.
BILLING_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
                "AWS_BEARER_TOKEN_BEDROCK", "CLAUDE_CODE_OAUTH_TOKEN_OVERRIDE")
LIMIT_WORDS = ("usage limit", "rate limit", "limit reached", "quota", "overloaded", "too many requests", "5-hour", "weekly limit", "resets at")


def child_env(extra: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if os.environ.get("JOBKIT_ALLOW_API") == "1" or k not in BILLING_VARS}
    env.update(LEAN_ENV)
    env.update(extra or {})
    return env

TOOLS_READ = ["Read", "Glob", "Grep"]
TOOLS_WRITE = ["Write", "Edit"]
TOOLS_WEB = ["WebSearch", "WebFetch"]

_lock = threading.Lock()          # one Claude run at a time inside this process: keeps the cost predictable


@dataclass
class Result:
    ok: bool
    text: str = ""
    cost_usd: float = 0.0
    turns: int = 0
    seconds: float = 0.0
    error: str = ""
    denials: list = field(default_factory=list)
    log: str = ""


def command() -> list[str] | None:
    """The claude executable as an argv prefix, or None when it is not installed."""
    env = os.environ.get("JOBKIT_CLAUDE_BIN")
    if env:
        return [t.strip('"') for t in shlex.split(env, posix=(os.name != "nt"))]
    found = shutil.which("claude")
    return [found] if found else None


def status() -> dict:
    """Is Claude Code installed and logged in? Never starts a model call (no cost)."""
    cmd = command()
    if not cmd:
        return {"installed": False, "logged_in": False, "message": "Claude Code is not installed. Install it from https://claude.com/claude-code, then run `claude` once and log in."}
    try:
        v = subprocess.run(cmd + ["--version"], capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace")
        version = (v.stdout or v.stderr).strip().splitlines()[0] if (v.stdout or v.stderr).strip() else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return {"installed": False, "logged_in": False, "message": "Claude Code did not start. Reinstall it, then run `claude` once."}
    logged_in, plan, method, provider = None, None, None, None
    try:
        a = subprocess.run(cmd + ["auth", "status", "--json"], capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace", env=child_env())
        d = json.loads(a.stdout[a.stdout.find("{"):]) if "{" in a.stdout else {}
        logged_in = bool(d.get("loggedIn"))
        plan, method, provider = d.get("subscriptionType"), d.get("authMethod"), d.get("apiProvider")   # never the e-mail or the organisation: the page does not need them
    except (OSError, ValueError, subprocess.TimeoutExpired):
        logged_in = None
    subscription = bool(logged_in) and method == "claude.ai" and provider in (None, "firstParty")
    if subscription:
        msg = "ready: runs on your Claude subscription" + (f" ({plan})" if plan else "")
    elif logged_in:
        msg = "logged in, but not with a Claude subscription: this application is built for the Claude login (run `claude auth login` and choose the Claude account)"
    elif logged_in is False:
        msg = "not logged in: run `claude` in a terminal once and sign in with your Claude account"
    else:
        msg = "could not tell whether you are logged in"
    return {"installed": True, "version": version, "logged_in": logged_in, "plan": plan, "auth_method": method, "subscription": subscription, "message": msg}


def run(prompt: str, *, label: str, tools: list[str], allowed: list[str] | None = None, max_turns: int = 40, budget_usd: float = 2.0,
        timeout_s: int = 1800, model: str | None = None, cwd: Path | None = None, extra_env: dict | None = None, add_dirs: list[str] | None = None) -> Result:
    """One headless Claude Code run. `tools` is the set of built-in tools it may see; `allowed` the permission rules that need no prompt
    (a Bash command is allowed one pattern at a time, e.g. "Bash(python scripts/analyze.py *)"). The prompt goes in on stdin."""
    cmd = command()
    if not cmd:
        return Result(False, error="Claude Code is not installed")
    argv = cmd + ["-p", "--output-format", "json", "--max-turns", str(max_turns), "--max-budget-usd", str(budget_usd),
                  "--tools", ",".join(tools), "--allowedTools", ",".join(allowed if allowed is not None else tools),
                  "--permission-mode", "acceptEdits"] + LEAN_FLAGS
    for d in add_dirs or []:                                # Claude Code only auto-approves edits inside its working directory; a profile folder elsewhere must be granted
        argv += ["--add-dir", str(d)]
    model = model or os.environ.get("JOBKIT_CLAUDE_MODEL") or "sonnet"
    argv += ["--model", model]
    env = child_env(extra_env)
    LOGS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log = LOGS / f"claude-{label}-{stamp}.json"
    t0 = time.time()
    with _lock:
        try:
            p = subprocess.run(argv, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s, cwd=str(cwd or ROOT), env=env)
        except subprocess.TimeoutExpired:
            return Result(False, error=f"timed out after {timeout_s}s", seconds=time.time() - t0)
        except OSError as exc:
            return Result(False, error=f"could not start Claude Code: {exc}", seconds=time.time() - t0)
    out = p.stdout or ""
    try:
        d = json.loads(out[out.find("{"):]) if "{" in out else {}
    except ValueError:
        d = {}
    res = Result(
        ok=(p.returncode == 0 and not d.get("is_error") and bool(d)),
        text=str(d.get("result") or ""), cost_usd=float(d.get("total_cost_usd") or 0), turns=int(d.get("num_turns") or 0),
        seconds=time.time() - t0, denials=list(d.get("permission_denials") or []), log=str(log.relative_to(ROOT)))
    if not res.ok:
        res.error = (d.get("result") or (p.stderr or "")[-400:] or f"exit {p.returncode}").strip()[:400]
        blob = (json.dumps(d) + " " + (p.stderr or "")).lower()
        if any(w in blob for w in LIMIT_WORDS):
            res.error = "PLAN LIMIT: your Claude plan's usage limit is reached. " + res.error[:200]       # app_core pauses with a resume hint
        elif "budget" in blob and str(d.get("subtype", "")).startswith("error"):
            res.error = "stopped at the usage cap for this step"
    # the log holds the answer and the numbers, never the prompt's CV text (the prompts only point at files)
    log.write_text(json.dumps({"label": label, "ok": res.ok, "cost_usd": res.cost_usd, "turns": res.turns, "seconds": round(res.seconds, 1),
                               "error": res.error, "denials": res.denials, "result": res.text[:4000]}, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(json.dumps(status(), indent=1))
        return 0
    if cmd == "ask":
        r = run(" ".join(sys.argv[2:]) or "Reply with exactly: OK", label="ask", tools=[], max_turns=1, budget_usd=0.2)
        print(json.dumps({"ok": r.ok, "text": r.text, "cost_usd": r.cost_usd, "error": r.error}, indent=1))
        return 0 if r.ok else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())

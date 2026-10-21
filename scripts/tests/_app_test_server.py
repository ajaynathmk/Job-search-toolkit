#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A test server for the application page: the real Flask app and the real engine, with Claude Code replaced by fake_claude.py and the network steps by the
fictional example postings. The processes the page would start run as threads inside this server. Used by test_app_ui.py; also handy to look at the page without
spending any Claude usage:   python scripts/tests/_app_test_server.py [port]
It uses a throwaway profile and tracker (printed on start) and never touches a real one."""
import os
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TMP = tempfile.mkdtemp(prefix="jobkit-ui-")
os.environ["JOBKIT_PROFILE_DIR"] = str(Path(TMP) / "profile")
os.environ["JOBKIT_DB"] = str(Path(TMP) / "tracker.db")
os.environ["JOBKIT_CLAUDE_BIN"] = f'"{sys.executable}" "{HERE / "fake_claude.py"}"'
os.environ.setdefault("FAKE_CLAUDE_EXAMPLE", "de-bioinformatics-student")
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(ROOT / "scripts"))

import app_core as A  # noqa: E402
import app_routes as R  # noqa: E402
import db  # noqa: E402
import webapp  # noqa: E402

real_script = A.script


def fake_script(args, timeout=3600):
    name = Path(args[0]).name
    if name == "intake.py":
        return real_script([str(HERE / "_fake_intake.py")], timeout)
    if name in ("job_watch.py", "uni_watch.py", "board_sweep.py"):
        import time
        time.sleep(float(os.environ.get("UI_TEST_STEP_SECONDS", "1.5")))              # long enough for a browser to see a step running
        return 0, "ok"
    return real_script(args, timeout)


def thread_spawn(args, log_name):
    def go():
        if args[0] == "run":
            opts = {"review_limit": int(args[args.index("--review-limit") + 1]) if "--review-limit" in args else 20}
            if "--budget" in args:
                opts["budget"] = float(args[args.index("--budget") + 1])
            A.run_all(opts)
        elif args[0] == "tailor":
            A.tailor(args[1])
        elif args[0] == "refresh":
            A.refresh()
    threading.Thread(target=go, daemon=True).start()
    return os.getpid()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5199
    db.init_db()
    A.script = fake_script
    R.spawn = thread_spawn
    print(f"test server on http://127.0.0.1:{port}  (profile {TMP})", flush=True)
    webapp.app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)

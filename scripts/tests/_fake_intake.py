#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stands in for scripts/intake.py in test_app.py: files the fictional postings of an example profile and analyses them, with no network.
A child process, like the real intake, so it reads the configuration the application has just written."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import analyze  # noqa: E402
import db  # noqa: E402

example = ROOT / "examples" / os.environ.get("FAKE_CLAUDE_EXAMPLE", "de-bioinformatics-student")
jd = Path(os.environ["JOBKIT_PROFILE_DIR"]).parent / "jd"
jd.mkdir(exist_ok=True)
db.init_db()
n = 0
for p in sorted((example / "postings").glob("*.md")):
    text = p.read_text(encoding="utf-8").split("\n---\n", 1)[1]
    ref = "w-" + p.name[:2]
    if db.get_job(ref):
        continue
    folder = jd / p.stem
    folder.mkdir(exist_ok=True)
    (folder / "description.md").write_text(text, encoding="utf-8")
    db.create_job({"id": ref, "title": text.splitlines()[0], "employer": "Example Employer", "country": "DE", "source": "demo", "date_found": "2026-10-01",
                   "url": "https://example.org/" + ref, "analysis_level": "stub", "jd_read": 1, "jd_path": str(folder)})
    analyze.analyze_row(ref)
    n += 1
print('{"jd_fetched": %d, "stubs_created": %d}' % (n, n))

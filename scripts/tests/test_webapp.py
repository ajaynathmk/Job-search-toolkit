#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for scripts/webapp.py, run with Flask's test client against a throwaway database (no server, no browser).
    python scripts/tests/test_webapp.py

What must hold: the pages and the definitions endpoint answer, a note typed on the dashboard is the owner's own input and is stored, an
automation-style write cannot reach my_notes, and an approve / reject / recheck moves the row through the same guards as everything else.
"""
import os
from pathlib import Path as _P

# The tests run against the fictional example profile, never against a real one (config.py reads this variable at import).
os.environ.setdefault("JOBKIT_PROFILE_DIR", str(_P(__file__).resolve().parent.parent.parent / "examples" / "de-bioinformatics-student"))
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db as jobdb  # noqa: E402
import webapp  # noqa: E402


class WebappTest(unittest.TestCase):
    def setUp(self):
        self._real = jobdb.DB_PATH
        jobdb.DB_PATH = Path(__file__).resolve().parent / "_test_webapp.db"
        if jobdb.DB_PATH.exists():
            jobdb.DB_PATH.unlink()
        jobdb.init_db()
        jobdb.create_job({"id": "w-test", "title": "Student Assistant NGS", "employer": "Example University", "source": "demo", "date_found": "2026-10-01"})
        self.c = webapp.app.test_client()

    def tearDown(self):
        if jobdb.DB_PATH.exists():
            jobdb.DB_PATH.unlink()
        jobdb.DB_PATH = self._real

    def test_pages_and_definitions(self):
        for path in ("/", "/jobs", "/today", "/review", "/mail", "/pipeline", "/inbox", "/thesis"):
            self.assertEqual(self.c.get(path).status_code, 200, path)
        self.assertEqual(self.c.get("/assets/app.js").status_code, 200)
        self.assertEqual(self.c.get("/assets/secret.txt").status_code, 404)
        d = self.c.get("/api/definitions").get_json()
        self.assertIn("verdict_meta", d)
        self.assertIn("genomics", d["subfield_labels"])           # the example profile's own field reaches the dashboard
        self.assertIn("de_student_permit", d["route_labels"])      # and the region pack's routes

    def test_note_is_the_owners_and_is_stored(self):
        r = self.c.post("/api/jobs/w-test/note", json={"note": "ask about hours"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(jobdb.get_job("w-test")["my_notes"], "ask about hours")

    def test_automation_cannot_write_my_notes_through_the_generic_endpoint(self):
        r = self.c.post("/api/jobs/w-test/set", json={"my_notes": "sneaky"})
        self.assertNotEqual(jobdb.get_job("w-test")["my_notes"], "sneaky")
        self.assertIn(r.status_code, (400, 403, 409, 422, 500))

    def test_approve_recheck_reject(self):
        self.assertEqual(self.c.post("/api/jobs/w-test/approve", json={}).status_code, 200)
        self.assertEqual(jobdb.get_job("w-test")["approval"], "requested")
        self.assertEqual(self.c.post("/api/jobs/w-test/recheck", json={}).status_code, 200)
        self.assertEqual(jobdb.get_job("w-test")["approval"], "recheck")
        self.assertEqual(self.c.post("/api/jobs/w-test/reject", json={}).status_code, 200)
        self.assertEqual(jobdb.get_job("w-test")["status"], "rejected")


if __name__ == "__main__":
    unittest.main(verbosity=1)

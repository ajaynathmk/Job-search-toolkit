#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for scripts/db.py — run with: python scripts/tests/test_db.py

Uses the stdlib only (no pytest dependency). The one test that must never go red is
test_my_notes_guard_blocks_automation: it is the enforcement of the single rule the
whole system depends on the owner trusting.
"""
import os
from pathlib import Path as _P

# The tests run against the fictional example profile, never against a real one (config.py reads this variable at import).
os.environ.setdefault("JOBKIT_PROFILE_DIR", str(_P(__file__).resolve().parent.parent.parent / "examples" / "de-bioinformatics-student"))
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db as jobdb  # noqa: E402


class DbTestCase(unittest.TestCase):
    def setUp(self):
        # Point the module at a throwaway file so tests never touch the real tracker.
        self._real_db_path = jobdb.DB_PATH
        jobdb.DB_PATH = Path(__file__).resolve().parent / "_test_tracker.db"
        if jobdb.DB_PATH.exists():
            jobdb.DB_PATH.unlink()
        jobdb.init_db()

    def tearDown(self):
        if jobdb.DB_PATH.exists():
            jobdb.DB_PATH.unlink()
        jobdb.DB_PATH = self._real_db_path

    def _proof(self, jd_dir, level="auto", breakdown=None):
        """What analyze.py writes with any judgment: the JD hash, the level and the score breakdown."""
        (Path(jd_dir) / "description.md").write_text("full description text " * 80, encoding="utf-8")
        row = {"jd_path": str(jd_dir)}
        return {"jd_path": str(jd_dir), "jd_sha": jobdb.current_jd_sha(row), "analysis_level": level, "score_breakdown": breakdown or {"core": 4}}

    def _make_role(self, job_id="w-test-role"):
        return jobdb.create_job({
            "id": job_id,
            "title": "Werkstudent Bioinformatik",
            "employer": "Test Employer GmbH",
            "location": "Munich",
            "source": "glassdoor",
            "date_found": "2026-09-23",
        })

    def test_create_and_get(self):
        row = self._make_role()
        self.assertEqual(row["status"], "open")
        self.assertEqual(row["approval"], "none")
        self.assertEqual(row["version"], 1)
        fetched = jobdb.get_job("w-test-role")
        self.assertEqual(fetched["employer"], "Test Employer GmbH")

    def test_country_defaults_to_unknown_and_is_validated(self):
        row = self._make_role()
        self.assertEqual(row["country"], "ZZ")          # unknown until the posting's location is read
        row = jobdb.update_job("w-test-role", {"country": "NL", "work_route": "employer_permit",
                                               "language_bar": "English only"})
        self.assertEqual(row["country"], "NL")
        with self.assertRaises(ValueError):
            jobdb.update_job("w-test-role", {"country": "Netherlands"})
        with self.assertRaises(ValueError):
            jobdb.update_job("w-test-role", {"country": "nl"})
        with self.assertRaises(ValueError):
            jobdb.update_job("w-test-role", {"work_route": "just_turn_up"})
        self.assertEqual([r["id"] for r in jobdb.list_jobs(country="NL")], ["w-test-role"])
        self.assertEqual(jobdb.list_jobs(country="DE"), [])
        self.assertEqual(jobdb.list_jobs(country="ZZ"), [])

    def test_migration_adds_columns_to_an_old_database(self):
        # Simulate a tracker.db created before 4 Oct 2026 (no country/work_route/language_bar).
        import sqlite3
        jobdb.DB_PATH.unlink()
        conn = sqlite3.connect(jobdb.DB_PATH)
        # Only the jobs table existed before 4 Oct 2026; the thesis table (7 Oct) comes after it.
        jobs_part = jobdb.SCHEMA_PATH.read_text(encoding="utf-8").split("CREATE TABLE IF NOT EXISTS thesis")[0]
        old_schema = "".join(
            line for line in jobs_part.splitlines(keepends=True)
            if not line.lstrip().startswith(("country ", "work_route ", "language_bar "))
        )
        conn.executescript(old_schema)
        conn.execute("INSERT INTO jobs (id, title, employer) VALUES ('old-1', 'Old role', 'Old GmbH')")
        conn.commit()
        conn.close()
        jobdb.init_db()
        row = jobdb.get_job("old-1")
        self.assertEqual(row["country"], "ZZ")
        jobdb.init_db()  # idempotent

    def test_thesis_roundtrip_guard_and_score(self):
        import tempfile
        td = tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup)
        proof = self._proof(td.name)
        with self.assertRaises(jobdb.ScoreWithoutJDError):
            jobdb.create_thesis({"id": "th-nojd", "title": "T", "institution": "U", "fit_score": 5})
        t = jobdb.create_thesis({"id": "th-test", "title": "Master thesis X", "institution": "Uni Y",
                                 "pillar": "genomics", "fit_score": 8, "route_adjustment": 1,
                                 "publications": [{"title": "P", "year": 2024}], **proof})
        self.assertEqual(t["score"], 9)
        self.assertEqual(t["publications"][0]["year"], 2024)
        with self.assertRaises(jobdb.MyNotesGuardError):
            jobdb.update_thesis("th-test", {"my_notes": "sneaky"})
        with self.assertRaises(jobdb.MyNotesGuardError):
            jobdb.create_thesis({"id": "th-test2", "title": "x", "institution": "y", "my_notes": "no"})
        with self.assertRaises(ValueError):
            jobdb.update_thesis("th-test", {"status": "maybe"})
        with self.assertRaises(ValueError):
            jobdb.update_thesis("th-test", {"pillar": "astrology"})
        row = jobdb.update_thesis("th-test", {"my_notes": "ask Prof about start"}, source="owner")
        self.assertEqual(row["my_notes"], "ask Prof about start")
        row = jobdb.update_thesis("th-test", {"route_adjustment": -1, **proof})
        self.assertEqual(row["score"], 7)
        with self.assertRaises(jobdb.StaleWriteError):
            jobdb.update_thesis("th-test", {"notes": "n"}, expected_version=1)
        self.assertEqual([x["id"] for x in jobdb.list_thesis(pillar="genomics")], ["th-test"])

    def test_my_notes_guard_blocks_automation(self):
        self._make_role()
        with self.assertRaises(jobdb.MyNotesGuardError):
            jobdb.update_job("w-test-role", {"my_notes": "sneaky overwrite"}, source="automation")
        # default source is "automation" too
        with self.assertRaises(jobdb.MyNotesGuardError):
            jobdb.update_job("w-test-role", {"my_notes": "sneaky overwrite"})
        # confirm nothing was written
        row = jobdb.get_job("w-test-role")
        self.assertIsNone(row["my_notes"])

    def test_my_notes_write_allowed_with_source_owner(self):
        self._make_role()
        row = jobdb.update_job(
            "w-test-role", {"my_notes": "please ask about the hours"}, source="owner"
        )
        self.assertEqual(row["my_notes"], "please ask about the hours")
        self.assertIsNotNone(row["my_notes_at"])

    def test_create_job_cannot_seed_my_notes(self):
        with self.assertRaises(jobdb.MyNotesGuardError):
            jobdb.create_job({
                "id": "w-seed-test", "title": "X", "employer": "Y",
                "my_notes": "should never be settable at creation",
            })

    def test_version_pinning_rejects_stale_write(self):
        row = self._make_role()
        # a concurrent write bumps the version
        jobdb.update_job("w-test-role", {"notes": "first update"})
        with self.assertRaises(jobdb.StaleWriteError):
            jobdb.update_job(
                "w-test-role", {"notes": "stale update"},
                expected_version=row["version"],  # stale: version 1, row is now 2
            )

    def test_closed_vocabulary_enforced(self):
        self._make_role()
        with self.assertRaises(ValueError):
            jobdb.update_job("w-test-role", {"status": "ghosted"})
        with self.assertRaises(ValueError):
            jobdb.update_job("w-test-role", {"approval": "maybe"})

    def test_keywords_json_roundtrip(self):
        self._make_role()
        kws = [{"term": "population PK modeling", "category": "method", "tier": "must",
                "pillar": "pkpd", "frequency": 3, "source": "hardReqs"}]
        jobdb.update_job("w-test-role", {"keywords": kws})
        row = jobdb.get_job("w-test-role")
        self.assertEqual(row["keywords"], kws)

    def test_list_jobs_filters(self):
        self._make_role("w-role-a")
        self._make_role("w-role-b")
        jobdb.update_job("w-role-b", {"status": "rejected"})
        open_roles = jobdb.list_jobs(status="open")
        self.assertEqual(len(open_roles), 1)
        self.assertEqual(open_roles[0]["id"], "w-role-a")

    def test_server_managed_fields_rejected(self):
        self._make_role()
        with self.assertRaises(ValueError):
            jobdb.update_job("w-test-role", {"version": 99})
        with self.assertRaises(ValueError):
            jobdb.update_job("w-test-role", {"id": "w-different-id"})

    def test_status_change_relocates_package_folder(self):
        # Real folders under the real applications/ dir (REPO_ROOT is fixed,
        # not swapped for tests like DB_PATH is) -- clean up in a finally so a
        # failed assertion never leaves stray folders behind.
        folder_name = "2099-01-01_TestEmployer_relocate-unit-test"
        top = jobdb.REPO_ROOT / "applications" / folder_name
        applied = jobdb.REPO_ROOT / "applications" / "Applied" / folder_name
        rejected = jobdb.REPO_ROOT / "applications" / "Rejected" / folder_name
        try:
            top.mkdir(parents=True)
            self._make_role()
            jobdb.update_job("w-test-role", {"package_path": f"applications/{folder_name}"})

            row = jobdb.update_job("w-test-role", {"status": "applied"})
            self.assertEqual(row["package_path"], f"applications/Applied/{folder_name}")
            self.assertTrue(applied.is_dir())
            self.assertFalse(top.exists())

            row = jobdb.update_job("w-test-role", {"status": "rejected"})
            self.assertEqual(row["package_path"], f"applications/Rejected/{folder_name}")
            self.assertTrue(rejected.is_dir())
            self.assertFalse(applied.exists())

            row = jobdb.update_job("w-test-role", {"status": "open"})
            self.assertEqual(row["package_path"], f"applications/{folder_name}")
            self.assertTrue(top.is_dir())
            self.assertFalse(rejected.exists())
        finally:
            for d in (top, applied, rejected):
                if d.exists():
                    shutil.rmtree(d)

    def test_status_change_without_package_path_does_not_raise(self):
        self._make_role()
        row = jobdb.update_job("w-test-role", {"status": "applied"})
        self.assertEqual(row["status"], "applied")
        self.assertIsNone(row["package_path"])

    def test_score_requires_cached_jd_and_proof_of_the_read(self):
        """THE STRICT SCORING RULE: no judgment without the full JD, its hash, the analysis level and a breakdown."""
        import tempfile
        self._make_role("t-nojd")
        with self.assertRaises(jobdb.ScoreWithoutJDError):            # no JD at all
            jobdb.update_job("t-nojd", {"score": 5})
        with self.assertRaises(jobdb.ScoreWithoutJDError):            # a verdict alone is a judgment too
            jobdb.update_job("t-nojd", {"verdict": "PASS"})
        with self.assertRaises(jobdb.ScoreWithoutJDError):
            jobdb.create_job({"id": "t-nojd2", "title": "T", "employer": "E", "score": 5})
        jobdb.update_job("t-nojd", {"score": 3}, source="rollback")   # restoring an old value is the one exception
        jobdb.update_job("t-nojd", {"score": None, "tier": None})     # clearing needs no proof
        with tempfile.TemporaryDirectory() as d:
            proof = self._proof(d)
            with self.assertRaises(jobdb.ScoreWithoutJDError):        # JD cached but the write carries no hash
                jobdb.update_job("t-nojd", {"jd_path": d, "score": 6})
            with self.assertRaises(jobdb.ScoreWithoutJDError):        # wrong hash: the text analysed is not the cached text
                jobdb.update_job("t-nojd", {**proof, "jd_sha": "0" * 16, "score": 6})
            with self.assertRaises(jobdb.ScoreWithoutJDError):        # a score with no breakdown
                jobdb.update_job("t-nojd", {**proof, "score_breakdown": None, "score": 6})
            self.assertEqual(jobdb.update_job("t-nojd", {**proof, "score": 6, "tier": 2, "verdict": "BACKUP"})["verdict"], "BACKUP")
            # 'reviewed' needs a read receipt from a Claude session
            rp = self._proof(d, level="reviewed")
            with self.assertRaises(jobdb.ScoreWithoutJDError):
                jobdb.update_job("t-nojd", {**rp, "verdict": "APPLY"})
            jobdb.record_jd_read("job", "t-nojd", rp["jd_sha"], "claude")
            self.assertEqual(jobdb.update_job("t-nojd", {**rp, "verdict": "APPLY"})["verdict"], "APPLY")
            # the cached JD changing after the analysis invalidates it
            (Path(d) / "description.md").write_text("a different description " * 80, encoding="utf-8")
            with self.assertRaises(jobdb.ScoreWithoutJDError):
                jobdb.update_job("t-nojd", {**rp, "score": 7})

if __name__ == "__main__":
    unittest.main(verbosity=2)

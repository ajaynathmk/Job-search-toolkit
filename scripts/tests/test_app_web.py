#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The application's web API with Flask's test client: upload a CV, see the status, the corrections, the results, and the protections against other websites.
Claude Code is the fake (scripts/tests/fake_claude.py); processes the API would start are replaced by recording stubs. No network, no subscription.
    python scripts/tests/test_app_web.py
"""
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TMP = tempfile.mkdtemp(prefix="jobkit-web-")
os.environ["JOBKIT_PROFILE_DIR"] = str(Path(TMP) / "profile")
os.environ["JOBKIT_DB"] = str(Path(TMP) / "tracker.db")
os.environ["JOBKIT_CLAUDE_BIN"] = f'"{sys.executable}" "{HERE / "fake_claude.py"}"'
os.environ.pop("FAKE_CLAUDE", None)

sys.path.insert(0, str(ROOT / "scripts"))
import app_core as A  # noqa: E402
import app_routes as R  # noqa: E402
import db  # noqa: E402
import webapp  # noqa: E402

CV = ("Alex Example\nExample City\n\nM.Sc. Bioinformatics. Python, R, Nextflow, RNA-seq, variant calling, Linux, Docker, statistics, machine learning. English C1, German B2.\n" * 12)
spawned = []


def fake_spawn(args, log_name):
    spawned.append(args)
    return 0


class AppWeb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        R.spawn = fake_spawn
        A.script = lambda args, timeout=3600: (0, "ok")                       # no network step runs in these tests
        cls.c = webapp.app.test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    # ------------------------------------------------------------------ the front door
    def test_01_the_front_door_is_the_start_page_until_there_is_a_profile(self):
        r = self.c.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Jobs from your CV", r.data)
        self.assertEqual(self.c.get("/start").status_code, 200)
        self.assertEqual(self.c.get("/assets/start.js").status_code, 200)
        self.assertEqual(self.c.get("/assets/start.css").status_code, 200)

    def test_02_the_engine_reports_the_subscription_and_no_account_details(self):
        d = self.c.get("/api/app/engine").get_json()
        self.assertTrue(d["claude"]["subscription"])
        self.assertNotIn("email", str(d).lower())
        self.assertIn("de", d["region_packs"])

    # ------------------------------------------------------------------ other websites cannot drive it
    def test_03_other_hosts_and_origins_are_refused(self):
        self.assertEqual(self.c.get("/api/app/status", headers={"Host": "evil.example"}).status_code, 403)
        self.assertEqual(self.c.post("/api/app/run", json={}, headers={"Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.c.post("/api/app/run", json={}, headers={"Origin": "http://127.0.0.1:5057"}).status_code, 400)       # allowed in, refused for having no CV yet

    # ------------------------------------------------------------------ the CV
    def test_04_upload_pasted_and_file_and_refusals(self):
        r = self.c.post("/api/app/cv", data={"file": (io.BytesIO(CV.encode()), "cv.txt"), "notes": "Munich please"}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertGreater(r.get_json()["chars"], 300)
        self.assertEqual((Path(os.environ["JOBKIT_PROFILE_DIR"]) / "user-notes.txt").read_text(encoding="utf-8").strip(), "Munich please")
        self.assertEqual(self.c.post("/api/app/cv", json={"text": CV}).status_code, 200)
        bad = self.c.post("/api/app/cv", json={"text": "tiny"})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("scanned", bad.get_json()["hint"].lower())
        self.assertEqual(self.c.post("/api/app/cv", data={"file": (io.BytesIO(b"MZ" * 500), "cv.exe")}, content_type="multipart/form-data").status_code, 400)

    def test_05_start_runs_the_engine_as_its_own_process_and_stop_sets_the_flag(self):
        r = self.c.post("/api/app/run", json={"budget": 6, "review_limit": 10})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(spawned[-1], ["run", "--review-limit", "10", "--budget", "6.0"])
        st = self.c.get("/api/app/status").get_json()
        self.assertEqual(st["status"], "error")                                  # the stub process is not alive: the page is told, not left spinning
        self.assertIn("Press Start again", st["hint"])
        self.c.post("/api/app/stop", json={})
        self.assertTrue(A.STOP_P.exists())
        A.STOP_P.unlink()

    # ------------------------------------------------------------------ a finished run
    def test_10_after_a_run_the_page_gets_the_understanding_and_the_jobs(self):
        st = A.run_all({"review_limit": 20, "budget": 5})
        self.assertNotEqual(st["status"], "running")
        u = self.c.get("/api/app/understood").get_json()
        self.assertTrue(u["configured"])
        self.assertTrue(u["assumptions"])

    def test_11_corrections_are_whitelisted_validated_and_start_a_rescore(self):
        r = self.c.post("/api/app/assumptions", json={"edits": {"cities": ["Example City"], "remote_ok": False}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(spawned[-1], ["refresh"])
        for edits in ({"name": "x"}, {"regions": ["zz-none"]}, {"remote_ok": "yes"}):
            bad = self.c.post("/api/app/assumptions", json={"edits": edits})
            self.assertEqual(bad.status_code, 400, edits)

    def test_12_tailoring_starts_one_at_a_time(self):
        r = self.c.post("/api/app/tailor/w-01", json={})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(spawned[-1], ["tailor", "w-01"])
        self.assertEqual(self.c.post("/api/app/tailor/w-02", json={}).status_code, 409)         # w-01 is "running" in the state file
        A.set_tailor("w-01", {"status": "done", "message": "", "folder": "applications/none", "files": []})

    def test_13_package_files_cannot_escape_the_applications_folder(self):
        A.set_tailor("w-01", {"status": "done", "message": "", "folder": "../db", "files": []})
        self.assertEqual(self.c.get("/api/app/package/w-01/schema.sql").status_code, 404)

    def test_14_schedule_input_is_checked(self):
        self.assertEqual(self.c.post("/api/app/schedule", json={"action": "install", "time": "25:99; calc"}).status_code, 400)
        self.assertEqual(self.c.post("/api/app/schedule", json={"action": "format"}).status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=1)

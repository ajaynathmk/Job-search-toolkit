#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The application's engine end to end, offline: a CV goes in, reviewed jobs come out.

Claude Code is replaced by scripts/tests/fake_claude.py (JOBKIT_CLAUDE_BIN) and the network steps by the fictional postings of an example profile, so the
test needs neither a Claude subscription nor the internet. It uses a throwaway profile folder and tracker, never a real one.
    python scripts/tests/test_app.py
"""
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TMP = tempfile.mkdtemp(prefix="jobkit-app-")
os.environ["JOBKIT_PROFILE_DIR"] = str(Path(TMP) / "profile")          # config.py and db.py read these at import: set them first
os.environ["JOBKIT_DB"] = str(Path(TMP) / "tracker.db")
os.environ["JOBKIT_CLAUDE_BIN"] = f'"{sys.executable}" "{HERE / "fake_claude.py"}"'
os.environ["ANTHROPIC_API_KEY"] = "sk-test-must-never-reach-claude"
os.environ.pop("FAKE_CLAUDE", None)

sys.path.insert(0, str(ROOT / "scripts"))
import app_core as A  # noqa: E402
import claude_runner as C  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402

EXAMPLE = ROOT / "examples" / "de-bioinformatics-student"
CV_TEXT = ("Alex Example\nExample City, Germany\n\nEDUCATION\nM.Sc. Bioinformatics, Example University (2024-2026)\nB.Sc. Biology, Example University (2021-2024)\n\n"
           "SKILLS\nPython, R, Nextflow, Snakemake, RNA-seq, variant calling, Linux, Docker, statistics, machine learning\n\nPROJECTS\nRNA-seq pipeline for differential expression with "
           "Nextflow and DESeq2; variant calling workflow with GATK; a classifier for tumour subtypes with scikit-learn.\n\nLANGUAGES\nEnglish (C1), German (B2)\n") * 2


def fake_script(args, timeout=3600):
    """The network steps, replaced: the watches do nothing, intake files the fictional example postings and analyses them (in a child process, like the real one)."""
    name = Path(args[0]).name
    if name == "intake.py":
        return real_script([str(HERE / "_fake_intake.py")], timeout)
    if name in ("job_watch.py", "uni_watch.py", "board_sweep.py"):
        return 0, "ok"
    return real_script(args, timeout)


real_script = A.script


class AppEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        A.script = fake_script

    @classmethod
    def tearDownClass(cls):
        A.script = real_script
        shutil.rmtree(TMP, ignore_errors=True)
        for d in (ROOT / "applications").glob("*_Fake_*"):
            shutil.rmtree(d, ignore_errors=True)

    # ------------------------------------------------------------------ the CV
    def test_01_pasted_cv_is_stored_and_its_language_guessed(self):
        info = A.accept_cv("cv.txt", text=CV_TEXT)
        self.assertGreater(info["chars"], 300)
        self.assertEqual(info["language"], "en")
        self.assertTrue((config.PROFILE_DIR / "cv-source.txt").exists())

    def test_02_a_docx_is_read(self):
        p = Path(TMP) / "cv.docx"
        body = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in CV_TEXT.splitlines())
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>")
        info = A.accept_cv("cv.docx", data=p.read_bytes())
        self.assertGreater(info["chars"], 300)

    def test_03_too_little_text_and_wrong_types_are_refused_with_a_hint(self):
        with self.assertRaises(A.Fail) as e:
            A.accept_cv("cv.txt", text="short")
        self.assertIn("scanned", e.exception.hint.lower())
        with self.assertRaises(A.Fail):
            A.accept_cv("cv.exe", data=b"x" * 1000)

    # ------------------------------------------------------------------ the subscription
    def test_04_an_api_key_never_reaches_claude_and_the_login_is_the_subscription(self):
        self.assertNotIn("ANTHROPIC_API_KEY", C.child_env())
        st = C.status()
        self.assertTrue(st["installed"] and st["logged_in"] and st["subscription"], st)

    # ------------------------------------------------------------------ the whole run
    def test_10_cv_in_reviewed_jobs_out(self):
        A.accept_cv("cv.txt", text=CV_TEXT)
        st = A.run_all({"review_limit": 20, "budget": 5})
        self.assertEqual(st["status"], "done", st.get("error"))
        self.assertEqual([s["status"] for s in st["stages"] if s["id"] in ("understand", "configure", "read", "review")], ["done", "done", "done", "done"])
        self.assertTrue((config.PROFILE_DIR / "profile.json").exists() and (config.PROFILE_DIR / "assumptions.json").exists())
        self.assertGreater(st["counts"]["best_fits"], 0)
        self.assertGreater(st["counts"]["confirmed"], 0)                      # the fake reviewer read them with analyze.py show and recorded a verdict
        self.assertGreater(st["cost_usd"], 0)
        res = A.results()
        self.assertTrue(res and all(r["verdict"] in A.BEST for r in res))
        self.assertTrue(any(r["confirmed"] for r in res))
        self.assertTrue(all(r["url"] for r in res))

    def test_11_a_second_start_resumes_and_does_nothing_twice(self):
        before = A.load_state()["cost_usd"]
        st = A.run_all({"review_limit": 20})
        self.assertEqual(st["status"], "done")
        self.assertEqual(st["cost_usd"], before)                              # no step ran again

    def test_12_what_was_understood_and_the_assumptions_are_shown(self):
        u = A.understood()
        self.assertTrue(u["configured"] and u["subfields"] and u["assumptions"])
        self.assertIn("work_authorization.status", [a["key"] for a in u["assumptions"]])

    def test_13_a_correction_is_validated_applied_and_marked_as_the_person_own(self):
        out = A.apply_edits({"remote_ok": False, "cities": ["Example City"]})
        self.assertTrue(out["ok"])
        self.assertEqual(A._json(config.PROFILE_DIR / "profile.json", {})["cities"], ["Example City"])
        self.assertTrue(A.load_state()["needs_rescore"])
        with self.assertRaises(A.Fail):
            A.apply_edits({"name": "Not Allowed Here"})                       # only whitelisted keys
        with self.assertRaises(A.Fail):
            A.apply_edits({"regions": ["zz-no-such-pack"]})                   # invalid: refused, the file is restored
        self.assertNotIn("zz-no-such-pack", A._json(config.PROFILE_DIR / "profile.json", {})["regions"])
        A.refresh()
        self.assertFalse(A.load_state()["needs_rescore"])

    # ------------------------------------------------------------------ tailoring
    def test_20_tailoring_builds_a_package_only_for_a_role_that_fits(self):
        good = next(r for r in A.results() if r["kind"] == "job")
        out = A.tailor(good["id"])
        self.assertEqual(out["status"], "done", out)
        self.assertIn("cv.md", out["files"])
        self.assertEqual(db.get_job(good["id"])["approval"], "prepared")
        blocked = db.get_job("w-02")                                           # the German C1 posting
        self.assertEqual(blocked["verdict"], "BLOCKED")
        self.assertEqual(A.tailor("w-02")["status"], "error")
        self.assertEqual(db.get_job("w-02")["approval"], blocked["approval"])  # nothing was approved or built

    # ------------------------------------------------------------------ failure modes
    def test_30_an_exhausted_plan_pauses_with_a_resume_hint(self):
        os.environ["FAKE_CLAUDE"] = "limit"
        try:
            for f in ("profile.json", "domain.json"):
                (config.PROFILE_DIR / f).unlink()
            st = A.run_all({"from": "understand", "force": True})
        finally:
            os.environ.pop("FAKE_CLAUDE", None)
        self.assertEqual(st["status"], "error")
        self.assertIn("limit", st["error"].lower())
        self.assertIn("press start again", st["hint"].lower())

    def test_31_stop_is_honoured_between_steps(self):
        A.APP_DIR.mkdir(parents=True, exist_ok=True)
        A.STOP_P.write_text("x")
        try:
            st = A.run_all({"from": "understand", "force": True, "keep_stop_flag": True})   # a real Start clears a stale flag; the test keeps it
        finally:
            if A.STOP_P.exists():
                A.STOP_P.unlink()
        self.assertEqual(st["status"], "stopped")


if __name__ == "__main__":
    unittest.main(verbosity=1)

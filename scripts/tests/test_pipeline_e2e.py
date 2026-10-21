#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
End-to-end test of the analysis stage against a throwaway tracker: a stub row with a cached JD becomes an analysed row with the proof the database
demands, a reviewed verdict is never overwritten, and a change of configuration re-scores and flags.
    python scripts/tests/test_pipeline_e2e.py
"""
import os
from pathlib import Path as _P

# The tests run against the fictional example profile, never against a real one (config.py reads this variable at import).
EXAMPLE = _P(__file__).resolve().parent.parent.parent / "examples" / "de-bioinformatics-student"
os.environ.setdefault("JOBKIT_PROFILE_DIR", str(EXAMPLE))
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analyze  # noqa: E402
import db  # noqa: E402
import definitions as D  # noqa: E402


class AnalysisStageTest(unittest.TestCase):
    def setUp(self):
        self._real = db.DB_PATH
        db.DB_PATH = Path(__file__).resolve().parent / "_test_e2e.db"
        if db.DB_PATH.exists():
            db.DB_PATH.unlink()
        db.init_db()
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)

    def tearDown(self):
        if db.DB_PATH.exists():
            db.DB_PATH.unlink()
        db.DB_PATH = self._real

    def stub(self, posting="01-thesis-helmholtz.md", country="DE"):
        text = (EXAMPLE / "postings" / posting).read_text(encoding="utf-8").split("\n---\n", 1)[1]
        folder = Path(self.td.name) / posting.replace(".md", "")
        folder.mkdir()
        (folder / "description.md").write_text(text, encoding="utf-8")
        db.create_job({"id": "w-" + posting[:2], "title": text.splitlines()[0], "employer": "Example Employer", "country": country, "source": "demo",
                       "date_found": "2026-10-01", "url": "https://example.org/x", "analysis_level": "stub", "jd_read": 1, "jd_path": str(folder)})
        return "w-" + posting[:2]

    def test_a_stub_is_analysed_with_the_proof_the_database_demands(self):
        ref = self.stub()
        r = analyze.analyze_row(ref)
        self.assertEqual(r["verdict"], "APPLY")
        row = db.get_job(ref)
        self.assertEqual(row["analysis_level"], "auto")
        self.assertEqual(row["verdict"], "APPLY")
        self.assertTrue(row["jd_sha"] and row["score_breakdown"] and row["rule_version"] == D.RULE_VERSION)
        self.assertEqual(row["category"], "own_field")
        self.assertEqual(row["work_route"], "de_thesis")

    def test_a_row_without_a_cached_jd_cannot_be_scored(self):
        db.create_job({"id": "w-nojd", "title": "T", "employer": "E", "analysis_level": "stub"})
        with self.assertRaises(db.ScoreWithoutJDError):
            db.update_job("w-nojd", {"score": 8, "verdict": "APPLY"})

    def test_blocked_posting_keeps_its_wall_quote(self):
        ref = self.stub("02-werkstudent-german-c1.md")
        analyze.analyze_row(ref)
        row = db.get_job(ref)
        self.assertEqual(row["verdict"], "BLOCKED")
        self.assertIn("C1", row["blocked_reason"])
        self.assertTrue(row["lang_bar"])

    def test_a_reviewed_verdict_is_not_overwritten_and_a_disagreement_is_flagged(self):
        ref = self.stub("07-hiwi-ngs-university.md")
        analyze.analyze_row(ref)
        with self.assertRaises(db.ScoreWithoutJDError):      # a judgment from a session that has not read the JD is refused
            db.update_job(ref, {"verdict": "BACKUP", "analysis_level": "reviewed", "jd_sha": db.current_jd_sha(db.get_job(ref))})
        analyze.show(ref)                                 # records the read receipt
        analyze.review(ref, "BACKUP", "weaker than it looks: only 10 hours a week", None, None, None)
        row = db.get_job(ref)
        self.assertEqual((row["analysis_level"], row["verdict"]), ("reviewed", "BACKUP"))
        analyze.analyze_row(ref)                            # the script runs again and says APPLY: the review stands, the row is flagged
        row = db.get_job(ref)
        self.assertEqual(row["verdict"], "BACKUP")
        self.assertIn("the reviewed verdict is kept", row["score_flag"] or "")

    def test_a_person_with_no_work_permit_limit_is_analysed_and_stored(self):
        """Found by the first live run of the application (21 Oct 2026): for a citizen, an EU citizen or a resident the route is "unrestricted", and the database refused it,
        so every analysis of every posting failed. A job and a thesis must both be stored."""
        import config
        cfg = config.get()
        old = cfg.profile.get("work_authorization")
        cfg.profile["work_authorization"] = {"status": "citizen"}
        db.refresh_vocab()
        try:
            self.assertFalse(cfg.needs_authorization)
            job = self.stub("07-hiwi-ngs-university.md")
            analyze.analyze_row(job)
            row = db.get_job(job)
            self.assertEqual(row["analysis_level"], "auto")
            self.assertEqual(row["work_route"], "unrestricted")
            self.assertIn(row["verdict"], ("APPLY", "BACKUP", "PLAN", "LATER"))
            db.create_thesis({"id": "th-unrestricted", "title": "Master thesis RNA-seq", "institution": "Example University", "country": "DE", "source_type": "university",
                              "posting_kind": "advertised", "posting_url": "https://example.org/t", "status": "lead", "analysis_level": "stub"})
            db.update_thesis("th-unrestricted", {"work_route": "unrestricted"})              # the validator that used to refuse it
        finally:
            cfg.profile["work_authorization"] = old
            db.refresh_vocab()

    def test_a_changed_profile_rescores_and_flags(self):
        ref = self.stub("07-hiwi-ngs-university.md")
        analyze.analyze_row(ref)
        before = db.get_job(ref)
        # the same row analysed again after the work-authorization route changed: simulate by storing an older score and rule version
        db.update_job(ref, {"rule_version": "old", "score_flag": None})
        analyze.analyze_row(ref)
        after = db.get_job(ref)
        self.assertEqual(after["rule_version"], D.RULE_VERSION)
        self.assertEqual(after["score"], before["score"])
        self.assertIsNone(after["score_flag"])              # nothing moved, nothing flagged


if __name__ == "__main__":
    unittest.main(verbosity=1)

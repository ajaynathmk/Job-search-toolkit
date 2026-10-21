#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for the analysis engine on the two fictional example profiles (examples/): the same engine, two people, two countries, two fields.
    python scripts/tests/test_analyze.py

The configuration is read at import time from JOBKIT_PROFILE_DIR, so every example runs in a child process (`onboard.py demo --json`).
What must hold is what the toolkit promises: the verdict follows from the full text, the person's own levels, their work-authorization route and the
region pack, and nothing of one example's country or field leaks into the other.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def demo(example: str) -> dict:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "onboard.py"), "demo", "--example", example, "--json"], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return {x["file"]: x for x in json.loads(r.stdout)}


class GermanStudentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = demo("de-bioinformatics-student")

    def test_thesis_in_the_field_is_apply_with_the_thesis_route(self):
        x = self.r["01-thesis-helmholtz.md"]
        self.assertEqual((x["verdict"], x["kind"], x["category"], x["subfield"], x["route"]), ("APPLY", "thesis", "own_field", "genomics", "de_thesis"))
        self.assertGreaterEqual(x["score"], 7)

    def test_university_assistant_job_gets_the_free_route(self):
        x = self.r["07-hiwi-ngs-university.md"]
        self.assertEqual((x["verdict"], x["kind"], x["route"]), ("APPLY", "student_assistant", "de_student_assistant"))

    def test_a_language_level_above_the_profiles_is_a_wall(self):
        x = self.r["02-werkstudent-german-c1.md"]
        self.assertEqual(x["verdict"], "BLOCKED")
        self.assertTrue(any("German" in w and "A2" in w for w in x["walls"]), x["walls"])

    def test_german_citizenship_and_clearance_are_walls_for_a_non_eu_applicant(self):
        x = self.r["09-clearance-required.md"]
        self.assertEqual(x["verdict"], "BLOCKED")
        self.assertTrue(any("Security clearance" in w for w in x["walls"]))
        self.assertTrue(any("citizenship" in w for w in x["walls"]))

    def test_off_topic_role_is_not_a_fit(self):
        x = self.r["03-working-student-marketing.md"]
        self.assertEqual((x["verdict"], x["category"]), ("PASS", "other"))

    def test_senior_role_is_later_not_apply(self):
        x = self.r["05-senior-bioinformatician.md"]
        self.assertEqual((x["verdict"], x["kind"]), ("LATER", "senior"))

    def test_a_posting_in_another_country_is_a_plan_with_a_route_penalty(self):
        x = self.r["04-internship-basel.md"]
        self.assertEqual((x["verdict"], x["country"], x["route"]), ("PLAN", "CH", "none_found"))

    def test_an_information_page_is_not_a_posting(self):
        x = self.r["06-information-page.md"]
        self.assertEqual(x["verdict"], "PASS")
        self.assertIn("not a posting", x["reason"])

    def test_a_passed_deadline_is_expired(self):
        self.assertEqual(self.r["08-expired-thesis.md"]["verdict"], "EXPIRED")


class AmericanAnalystTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = demo("us-data-analyst")

    def test_entry_role_is_apply_on_opt(self):
        for f in ("01-entry-data-analyst.md", "02-entry-no-sponsorship.md"):
            x = self.r[f]
            self.assertEqual((x["verdict"], x["kind"], x["route"]), ("APPLY", "entry", "us_opt"), f)

    def test_internship_is_apply(self):
        self.assertEqual(self.r["05-internship-analytics.md"]["verdict"], "APPLY")

    def test_citizenship_and_clearance_are_a_wall(self):
        x = self.r["03-clearance.md"]
        self.assertEqual(x["verdict"], "BLOCKED")

    def test_senior_and_off_field_roles_are_not_applied_to(self):
        self.assertEqual(self.r["04-senior-data-scientist.md"]["verdict"], "LATER")
        self.assertEqual(self.r["06-software-engineer.md"]["verdict"], "PASS")

    def test_no_german_rules_leak_in(self):
        for x in self.r.values():
            self.assertNotIn("de_", x["route"])
            self.assertFalse(any("German" in w for w in x["walls"]))


class EuropeanEngineerTest(unittest.TestCase):
    """An experienced EU citizen: no work-authorization rule applies, roles are mid and senior, postings come in Dutch, French and German."""

    @classmethod
    def setUpClass(cls):
        cls.r = demo("eu-mechanical-engineer")

    def test_no_route_rule_applies_to_an_eu_citizen(self):
        for x in cls_values(self.r):
            self.assertEqual(x["route"], "unrestricted", x["file"])

    def test_dutch_and_english_postings_in_the_home_country_are_apply(self):
        self.assertEqual(self.r["01-dutch-design-engineer.md"]["verdict"], "APPLY")
        self.assertEqual(self.r["04-english-remote-design.md"]["verdict"], "APPLY")

    def test_a_posting_in_another_country_is_plan_and_a_german_wall_blocks_a_person_with_no_german(self):
        self.assertEqual(self.r["02-french-constructeur.md"]["verdict"], "PLAN")
        x = self.r["03-german-senior-konstrukteur.md"]
        self.assertEqual(x["verdict"], "BLOCKED")
        self.assertTrue(any("German" in w for w in x["walls"]))

    def test_levels_not_sought_and_off_field_roles(self):
        self.assertEqual(self.r["05-internship-not-sought.md"]["verdict"], "LATER")
        self.assertEqual((self.r["06-sales-engineer.md"]["verdict"], self.r["06-sales-engineer.md"]["category"]), ("PASS", "other"))


def cls_values(d):
    return list(d.values())


class LanguageLadderTest(unittest.TestCase):
    """A required level against the person's own: two or more steps above is a wall, one step above caps the verdict, equal or below is fine."""

    def run_levels(self, ask, mine):
        import os
        import tempfile
        src = ROOT / "examples" / "de-bioinformatics-student"
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "domain.json").write_text((src / "domain.json").read_text(encoding="utf-8"), encoding="utf-8")
            prof = json.loads((src / "profile.json").read_text(encoding="utf-8"))
            prof["languages"] = [{"code": "en", "level": "c1"}, {"code": "de", "level": mine}]
            prof["work_authorization"] = {"status": "eu_citizen"}
            (td / "profile.json").write_text(json.dumps(prof), encoding="utf-8")
            text = ("Student Assistant NGS data pipelines\n\nYour tasks\n- Maintain Snakemake pipelines for RNA-seq and genomics data on a Linux cluster\n"
                    "- Run differential expression analyses in R and Python\n\nYour profile\n- Enrolled in a bioinformatics master's programme\n"
                    f"- {ask}\n\nWe offer 10 hours a week. Please apply with your CV. Contact: Prof. Example, office@uni-example.de.\n")
            code = ("import sys,json;sys.path.insert(0,r'%s');import analyze;a=analyze.analyze_text({'title':'Student Assistant (HiWi) NGS pipelines','employer':'Example University',"
                    "'country':'DE','location':'Heidelberg','url':'https://www.uni-example.de/x'},%r);print(json.dumps({'v':a['verdict'],'walls':[w['wall'] for w in a['walls']],'effects':[l['effect'] for l in a['langs']]}))" % (ROOT / "scripts", text))
            r = subprocess.run([sys.executable, "-c", code], env={**os.environ, "JOBKIT_PROFILE_DIR": str(td)}, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)

    def test_b2_asked(self):
        ask = "German at B2 level (Deutsch B2) is required"
        self.assertEqual(self.run_levels(ask, "a2")["v"], "BLOCKED")        # two steps above
        out = self.run_levels(ask, "b1")
        self.assertEqual(out["v"], "BACKUP")                                 # one step above: not a first choice
        self.assertIn("cap", out["effects"])
        self.assertEqual(self.run_levels(ask, "b2")["v"], "APPLY")
        self.assertEqual(self.run_levels(ask, "native")["v"], "APPLY")

    def test_c1_asked(self):
        ask = "Excellent German (C1) is required"
        self.assertEqual(self.run_levels(ask, "b1")["v"], "BLOCKED")
        self.assertEqual(self.run_levels(ask, "b2")["v"], "BACKUP")
        self.assertEqual(self.run_levels(ask, "c1")["v"], "APPLY")

    def test_german_only_an_advantage_blocks_nobody(self):
        ask = "German is an advantage"
        for mine in ("none", "a2", "b1"):
            self.assertEqual(self.run_levels(ask, mine)["v"], "APPLY", mine)


class SameTextDifferentPersonTest(unittest.TestCase):
    """The same posting must be judged differently for a person with different languages and authorization."""

    def test_the_german_c1_posting_is_not_a_wall_for_a_native_speaker_with_unrestricted_work_rights(self):
        import os
        import tempfile
        src = ROOT / "examples" / "de-bioinformatics-student"
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "domain.json").write_text((src / "domain.json").read_text(encoding="utf-8"), encoding="utf-8")
            prof = json.loads((src / "profile.json").read_text(encoding="utf-8"))
            prof["languages"] = [{"code": "en", "level": "c1"}, {"code": "de", "level": "native"}]
            prof["work_authorization"] = {"status": "eu_citizen"}
            (td / "profile.json").write_text(json.dumps(prof), encoding="utf-8")
            code = (
                "import sys,json,pathlib;sys.path.insert(0,r'%s');import analyze;"
                "t=pathlib.Path(r'%s').read_text(encoding='utf-8').split('\\n---\\n',1)[1];"
                "a=analyze.analyze_text({'title':'Werkstudent (m/w/d) Bioinformatik','employer':'Beispiel Pharma AG','country':'DE','location':'Berlin'},t);"
                "print(json.dumps({'v':a['verdict'],'route':a['work_route'],'walls':[w['wall'] for w in a['walls']]}))"
                % (ROOT / "scripts", src / "postings" / "02-werkstudent-german-c1.md"))
            r = subprocess.run([sys.executable, "-c", code], env={**os.environ, "JOBKIT_PROFILE_DIR": str(td)}, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
        self.assertEqual(out["walls"], [])
        self.assertEqual(out["route"], "unrestricted")
        self.assertEqual(out["v"], "APPLY")


if __name__ == "__main__":
    unittest.main(verbosity=1)

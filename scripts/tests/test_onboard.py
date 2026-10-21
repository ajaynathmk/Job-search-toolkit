#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for scripts/onboard.py and the configuration layer: the example profiles validate, a broken profile is explained, a CV is extracted, a new
region pack can be scaffolded and used, and several region packs merge (home market first, wider region behind it).
    python scripts/tests/test_onboard.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ONBOARD = [sys.executable, str(ROOT / "scripts" / "onboard.py")]
EXAMPLES = ROOT / "examples"


def run(args, env=None, profile_dir=None):
    e = {**os.environ}
    e.pop("JOBKIT_PROFILE_DIR", None)
    if profile_dir:
        e["JOBKIT_PROFILE_DIR"] = str(profile_dir)
    e.update(env or {})
    return subprocess.run(ONBOARD + args, capture_output=True, text=True, encoding="utf-8", env=e)


def copy_example(name, td):
    dst = Path(td) / "profile"
    shutil.copytree(EXAMPLES / name, dst, ignore=shutil.ignore_patterns("postings"))
    return dst


class ValidateTest(unittest.TestCase):
    def test_both_examples_validate_cleanly(self):
        for name in ("de-bioinformatics-student", "us-data-analyst", "eu-mechanical-engineer"):
            r = run(["check", "--profile-dir", str(EXAMPLES / name)])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("0 error(s)", r.stdout)

    def test_a_broken_profile_is_explained_not_crashed_on(self):
        with tempfile.TemporaryDirectory() as td:
            p = copy_example("de-bioinformatics-student", td)
            prof = json.loads((p / "profile.json").read_text(encoding="utf-8"))
            prof["email"] = "not-an-address"
            prof["career_stage"] = "wizard"
            prof["languages"] = [{"code": "de", "level": "fluentish"}]
            prof["regions"] = ["atlantis"]
            (p / "profile.json").write_text(json.dumps(prof), encoding="utf-8")
            dom = json.loads((p / "domain.json").read_text(encoding="utf-8"))
            dom["subfields"][0]["terms"].append("(unclosed")
            dom["subfields"][1]["category"] = "nonexistent"
            (p / "domain.json").write_text(json.dumps(dom), encoding="utf-8")
            r = run(["check", "--profile-dir", str(p)])
            self.assertEqual(r.returncode, 1)
            for needle in ("profile.email", "career_stage", "level 'fluentish'", "atlantis", "invalid regular expression", "nonexistent"):
                self.assertIn(needle, r.stdout, needle)

    def test_the_empty_templates_ask_for_what_is_missing(self):
        with tempfile.TemporaryDirectory() as td:
            r = run(["init"], profile_dir=Path(td) / "profile")
            self.assertEqual(r.returncode, 0, r.stderr)
            r = run(["check", "--profile-dir", str(Path(td) / "profile")])
            self.assertEqual(r.returncode, 1)
            self.assertIn("profile.name is empty", r.stdout)


class ExtractTest(unittest.TestCase):
    def test_a_markdown_cv_is_extracted_and_a_docx_too(self):
        with tempfile.TemporaryDirectory() as td:
            cv = Path(td) / "cv.md"
            cv.write_text("# Sam Example\n\nBioinformatics student. " + "Python, R, RNA-seq analysis, Linux. " * 20, encoding="utf-8")
            r = run(["extract", str(cv)], profile_dir=Path(td) / "profile")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("RNA-seq", (Path(td) / "profile" / "cv-source.txt").read_text(encoding="utf-8"))
            import zipfile
            docx = Path(td) / "cv.docx"
            body = "".join(f"<w:p><w:r><w:t>Line {i} Python and R pipelines for sequencing data analysis in a research group</w:t></w:r></w:p>" for i in range(8))
            with zipfile.ZipFile(docx, "w") as z:
                z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document xmlns:w="x"><w:body>{body}</w:body></w:document>')
            r = run(["extract", str(docx)], profile_dir=Path(td) / "profile2")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("Line 3 Python", (Path(td) / "profile2" / "cv-source.txt").read_text(encoding="utf-8"))


class RegionTest(unittest.TestCase):
    def test_a_scaffolded_pack_is_usable_by_a_profile(self):
        with tempfile.TemporaryDirectory() as td:
            p = copy_example("us-data-analyst", td)
            r = run(["scaffold-region", "xx", "Examplestan"], profile_dir=p)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue((p / "regions" / "xx" / "region.json").exists())
            prof = json.loads((p / "profile.json").read_text(encoding="utf-8"))
            prof["regions"] = ["xx"]
            (p / "profile.json").write_text(json.dumps(prof), encoding="utf-8")
            r = run(["check", "--profile-dir", str(p)])
            self.assertEqual(r.returncode, 0, r.stdout)

    def test_home_pack_first_and_the_wider_pack_behind_it(self):
        code = (
            "import sys,json;sys.path.insert(0,r'%s');import config;c=config.get();"
            "print(json.dumps({'home':c.region['home_country'],'primary':c.primary_countries,'scope_has_fr':'FR' in c.scope_countries,'langs':c.local_languages,"
            "'first_rule_country':c.route_rules[0]['when'].get('country'),'has_eu_rule':any(r['route']=='eu_erasmus' for r in c.route_rules),"
            "'codes':c.region_codes}))" % (ROOT / "scripts"))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
                           env={**os.environ, "JOBKIT_PROFILE_DIR": str(EXAMPLES / "de-bioinformatics-student")})
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["codes"], ["de", "eu"])
        self.assertEqual((out["home"], out["primary"], out["langs"]), ("DE", ["DE"], ["de"]))
        self.assertTrue(out["scope_has_fr"] and out["has_eu_rule"])
        self.assertEqual(out["first_rule_country"], ["DE"])

    def test_the_rule_version_changes_with_the_profile(self):
        code = "import sys;sys.path.insert(0,r'%s');import config;print(config.get().rule_version())" % (ROOT / "scripts")
        vs = []
        for name in ("de-bioinformatics-student", "us-data-analyst"):
            r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, "JOBKIT_PROFILE_DIR": str(EXAMPLES / name)})
            vs.append(r.stdout.strip())
        self.assertNotEqual(vs[0], vs[1])


class SourcesAndDoctorTest(unittest.TestCase):
    def test_build_sources_picks_employers_by_industry(self):
        with tempfile.TemporaryDirectory() as td:
            p = copy_example("de-bioinformatics-student", td)
            r = run(["build-sources"], profile_dir=p)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            src = json.loads((p / "sources.json").read_text(encoding="utf-8"))
            names = {w["institution"] for w in src["workday"]} | {a["institution"] for a in src["ats"]}
            self.assertIn("Roche", names)
            self.assertNotIn("Bosch", names)             # an engineering employer is not in a life-science profile's industries

    def test_doctor_runs_and_names_what_each_tool_switches_on(self):
        r = run(["doctor"], profile_dir=EXAMPLES / "de-bioinformatics-student")
        self.assertIn("what it switches on", r.stdout)
        self.assertIn("LibreOffice", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=1)

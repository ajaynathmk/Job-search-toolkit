#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A real browser drives the application page against the test server (_app_test_server.py): a CV goes in, the steps run, the corrections are saved, the jobs
appear and an application is written. Skipped when Playwright or its browser is not installed.
    python scripts/tests/test_app_ui.py [--shots DIR]      --shots saves screenshots (light, dark, phone width) into DIR
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHOTS = None
if "--shots" in sys.argv:
    i = sys.argv.index("--shots")
    SHOTS = Path(sys.argv[i + 1])
    del sys.argv[i:i + 2]

try:
    from playwright.sync_api import sync_playwright
    HAVE = True
except ImportError:
    HAVE = False

CV = ("Alex Example\nExample City, Germany\n\nEDUCATION\nM.Sc. Bioinformatics, Example University\n\nSKILLS\nPython, R, Nextflow, Snakemake, RNA-seq, variant calling, "
      "Linux, Docker, statistics, machine learning\n\nLANGUAGES\nEnglish (C1), German (B2)\n") * 4


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@unittest.skipUnless(HAVE, "playwright is not installed")
class AppUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.proc = subprocess.Popen([sys.executable, str(HERE / "_app_test_server.py"), str(cls.port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.5)
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.tmp = tempfile.mkdtemp()
        cls.cv = Path(cls.tmp) / "cv.txt"
        cls.cv.write_text(CV, encoding="utf-8")
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            cls.pw.stop()
            cls.proc.terminate()
            raise unittest.SkipTest(f"no browser: {exc}")

    @classmethod
    def tearDownClass(cls):
        import shutil
        for d in (HERE.parent.parent / "applications").glob("*_Fake_*"):                  # the fake Claude writes its package here
            shutil.rmtree(d, ignore_errors=True)
        cls.browser.close()
        cls.pw.stop()
        cls.proc.terminate()

    def shot(self, page, name):
        if SHOTS:
            SHOTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)

    def test_a_cv_in_and_jobs_out(self):
        errors = []
        page = self.browser.new_page(viewport={"width": 1100, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(self.base + "/")
        self.assertIn("Give it your CV", page.inner_text("h1"))
        self.assertTrue(page.is_disabled("#start"))                                   # nothing to start without a CV
        page.wait_for_function("!document.getElementById('engine').textContent.startsWith('Checking')", timeout=30000)
        self.assertIn("subscription", page.inner_text("#engine").lower())
        self.shot(page, "1-start")

        page.set_input_files("#file", str(self.cv))
        page.wait_for_selector("#cv-ok:not([hidden])")
        self.assertIn("characters", page.inner_text("#cv-ok"))
        page.click("summary:has-text('Anything to add')")                              # the optional box is collapsed until opened
        page.fill("#notes", "Working-student roles in bioinformatics")
        self.assertFalse(page.is_disabled("#start"))
        page.click("#start")

        page.wait_for_selector("#card-run:not([hidden])")
        self.shot(page, "2-running")
        page.wait_for_selector("#card-understood:not([hidden])", timeout=60000)       # the understanding appears as soon as the configuration is valid
        page.wait_for_selector(".st-job", timeout=120000)
        page.wait_for_function("document.querySelectorAll('#stages li.done, #stages li.skipped').length === 6", timeout=120000)
        self.assertIn("Finished", page.inner_text("#run-msg"))
        self.assertGreater(page.locator(".st-job").count(), 0)
        self.assertIn("read in full", page.inner_text("#res-counts"))
        self.shot(page, "3-results")

        # filters narrow the list; a posting's text is shown as text
        total = page.locator(".st-job").count()
        page.click("#filters button:has-text('Apply')")
        self.assertLessEqual(page.locator(".st-job").count(), total)
        page.click("#filters button:has-text('All')")

        # the understanding can be corrected, and a bad correction is refused with a reason
        page.fill("#e-cities", "Example City")
        page.uncheck("#e-remote")
        page.click("#save-edits")
        page.wait_for_function("document.getElementById('edit-msg').textContent.startsWith('Saved')", timeout=20000)
        page.fill("#e-regions", "zz-no-pack")
        page.click("#save-edits")
        page.wait_for_function("(() => { const t = document.getElementById('edit-msg').textContent; return t.length > 0 && !t.startsWith('Saved') && !t.startsWith('Checking'); })()", timeout=20000)
        self.assertIn("not valid", page.inner_text("#edit-msg"))
        page.fill("#e-regions", "de, eu")

        # approve one role: an application is written, and nothing is sent
        page.once("dialog", lambda d: d.accept())
        page.locator(".st-job button:has-text('Approve and write my application')").first.click()
        page.wait_for_selector(".st-files a", timeout=60000)
        self.assertIn("cv.md", page.inner_text(".st-files"))
        self.assertIn("never sends", page.inner_text(".st-job:has(.st-files)"))
        self.shot(page, "4-application")

        # dark and phone width
        page.evaluate("document.documentElement.setAttribute('data-theme','dark')")
        self.shot(page, "5-dark")
        page.set_viewport_size({"width": 390, "height": 800})
        self.shot(page, "6-phone")
        self.assertEqual([e for e in errors if "favicon" not in e.lower() and "400 (bad request)" not in e.lower()], [])   # the one 400 is the refused correction above
        page.close()


if __name__ == "__main__":
    unittest.main(verbosity=1)

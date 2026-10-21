#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for scripts/privacy_scan.py: the scanner catches what it claims to, and the repository itself is clean.
    python scripts/tests/test_privacy.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import privacy_scan as P  # noqa: E402


def scan(text, also=()):
    out = []
    P.scan_text("t.txt", text, list(also), out)
    return out


class ScannerTest(unittest.TestCase):
    def test_a_consumer_mailbox_is_a_finding_and_an_example_address_is_not(self):
        self.assertEqual([f["kind"] for f in scan("write to jane.doe@gmail.com")], ["consumer mailbox address"])
        self.assertEqual(scan("write to sam.example@example.com or careers@example.org"), [])
        self.assertEqual(scan("alerts: jobalerts-noreply@linkedin.com and jobs@mail.xing.com"), [])
        self.assertTrue(scan("hr@some-real-company.de"))

    def test_phone_numbers(self):
        self.assertTrue(scan("call +49 151 23456789 now") or scan("call +49 176 55512399 now"))
        self.assertEqual(scan("call +49 89 0000000"), [])
        self.assertEqual(scan("version 1.6.0 released 2026-10-07"), [])

    def test_secrets(self):
        self.assertTrue(scan("key = AIza" + "A" * 35))
        self.assertTrue(scan("token ya29." + "b" * 30))
        self.assertTrue(scan("-----BEGIN PRIVATE KEY-----"))
        self.assertTrue(scan('id = "' + "0123456789abcdef" * 2 + '"'))
        self.assertTrue(scan("passphrase: amber-anchor-apple-arrow-4821"))
        self.assertEqual(scan('id = "REPLACE_WITH_YOUR_KV_NAMESPACE_ID"'), [])

    def test_your_own_words(self):
        f = scan("I studied at Springfield University", also=["springfield"])
        self.assertEqual([x["kind"] for x in f], ["your own word"])
        self.assertEqual(scan("nothing here", also=["springfield"]), [])

    def test_forbidden_paths_are_recognised(self):
        import fnmatch
        for rel in ("profile/profile.json", "db/tracker.db", "jd/Acme_role/description.md", "config/gmail_token.json", "remote/.dev.vars", "data/mail/state.json"):
            self.assertTrue(any(rel.startswith(d) for d in P.FORBIDDEN_DIRS) or any(fnmatch.fnmatch(rel, g) for g in P.FORBIDDEN_GLOBS), rel)


class RepositoryTest(unittest.TestCase):
    def test_the_tree_is_clean(self):
        findings, n, how = P.scan_tree([])
        P.check_gitignore(findings)
        self.assertGreater(n, 50)
        self.assertEqual(findings, [], "\n".join(f"{f['file']}: {f['kind']}: {f['match']}" for f in findings))

    def test_gitignore_keeps_personal_folders_out(self):
        text = (P.ROOT / ".gitignore").read_text(encoding="utf-8")
        for need in ("/profile/", "/db/tracker.db", "/jd/", "/applications/", "/data/", "/config/", "/remote/.dev.vars"):
            self.assertIn(need, text)

    def test_the_shipped_kv_id_is_a_placeholder(self):
        toml = (P.ROOT / "remote" / "wrangler.toml").read_text(encoding="utf-8")
        self.assertIn("REPLACE_WITH_YOUR_KV_NAMESPACE_ID", toml)


if __name__ == "__main__":
    unittest.main(verbosity=1)

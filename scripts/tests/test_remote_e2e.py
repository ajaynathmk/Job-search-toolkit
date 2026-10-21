"""End-to-end test of the phone inbox against a LOCAL Worker (`cd remote && npx wrangler dev --local --port 8787`) and a COPY of the tracker.

Skipped unless the local Worker answers. Run: python scripts/tests/test_remote_e2e.py <passphrase>
The passphrase is the one `remote_sync.py init` printed (it is never stored); without it the login steps are skipped.
"""
import os
from pathlib import Path as _P

# The tests run against the fictional example profile, never against a real one (config.py reads this variable at import).
os.environ.setdefault("JOBKIT_PROFILE_DIR", str(_P(__file__).resolve().parent.parent.parent / "examples" / "de-bioinformatics-student"))
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402
import remote_sync as R  # noqa: E402

BASE = os.environ.get("REMOTE_BASE", "http://127.0.0.1:8787")
PASSPHRASE = sys.argv.pop(1) if len(sys.argv) > 1 else ""


def up() -> bool:
    try:
        return requests.get(BASE + "/api/snapshot", timeout=3).status_code in (200, 401)
    except requests.RequestException:
        return False


@unittest.skipUnless(up(), "local Worker not running (cd remote && npx wrangler dev --local --port 8787)")
class Phone(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.real = db.DB_PATH
        self.copy = Path(self.tmp.name) / "tracker.db"
        shutil.copy(self.real, self.copy)
        db.DB_PATH = self.copy
        self.cfg = R.load_config()
        self.cfg["url"] = BASE
        self.s = requests.Session()

    def tearDown(self):
        db.DB_PATH = self.real
        self.tmp.cleanup()

    def login(self):
        r = self.s.post(BASE + "/api/login", json={"passphrase": PASSPHRASE})
        self.assertEqual(r.status_code, 200)
        self.s.headers["Cookie"] = r.headers["Set-Cookie"].split(";")[0]      # the cookie is Secure: a plain-http local test must send it by hand

    def pull_wait(self, want=1, seconds=100):
        """Cloudflare KV lists new keys eventually (up to about a minute): wait for the decision to show up, as the hourly pull would."""
        import time
        end = time.time() + seconds
        while True:
            res = R.pull(self.cfg)
            if res["events"] >= want or time.time() > end:
                return res
            time.sleep(8)

    def test_the_phone_cannot_read_or_write_without_a_session_and_the_pc_needs_its_key(self):
        self.assertEqual(self.s.get(BASE + "/api/snapshot").status_code, 401)
        self.assertEqual(self.s.post(BASE + "/api/decision", json={"id": "x", "action": "approve"}).status_code, 401)
        self.assertEqual(requests.post(BASE + "/api/pc/snapshot", json={"items": []}).status_code, 401)
        self.assertEqual(requests.get(BASE + "/api/pc/events", headers={"Authorization": "Bearer wrong"}).status_code, 401)

    @unittest.skipUnless(PASSPHRASE, "pass the passphrase as an argument to test the login")
    def test_login_decide_pull_apply_ack(self):
        self.assertEqual(self.s.post(BASE + "/api/login", json={"passphrase": "wrong"}).status_code, 401)
        self.login()
        print("push:", R.push(self.cfg))
        snap = self.s.get(BASE + "/api/snapshot").json()["snapshot"]
        job = next(i for i in snap["items"] if i["kind"] == "job" and i["status"] == "open" and i["approval"] == "none")
        # a role the snapshot does not hold is refused
        self.assertEqual(self.s.post(BASE + "/api/decision", json={"id": "nope", "kind": "job", "action": "approve"}).status_code, 400)
        # an action that does not exist is refused
        self.assertEqual(self.s.post(BASE + "/api/decision", json={"id": job["id"], "kind": "job", "action": "delete"}).status_code, 400)
        ev = self.s.post(BASE + "/api/decision", json={"id": job["id"], "kind": "job", "action": "approve", "note": "from the phone"}).json()["event"]
        self.assertEqual(ev["status"], "pending")
        # undo works until the PC has handled it
        ev2 = self.s.post(BASE + "/api/decision", json={"id": job["id"], "kind": "job", "action": "recheck"}).json()["event"]
        self.assertEqual(self.s.delete(BASE + "/api/decision", params={"ev": ev2["id"]}).status_code, 200)
        before = db.get_job(job["id"])
        res = self.pull_wait(1)
        self.assertEqual((res["events"], res["applied"]), (1, 1))
        after = db.get_job(job["id"])
        self.assertEqual(after["approval"], "requested")
        self.assertIn("[phone", after["my_notes"] or "")                      # the note is the owner's own input, relayed with source=owner
        self.assertEqual(before["status"], after["status"])
        events = self.s.get(BASE + "/api/snapshot").json()["events"]
        self.assertEqual(next(e for e in events if e["id"] == ev["id"])["status"], "applied")
        # applying twice changes nothing and is reported, never an error
        ok, msg = R.apply_event(ev)
        self.assertTrue(ok)
        self.assertIn("already", msg)
        # an undo after the PC applied it is refused
        self.assertEqual(self.s.delete(BASE + "/api/decision", params={"ev": ev["id"]}).status_code, 409)

    @unittest.skipUnless(PASSPHRASE, "pass the passphrase as an argument to test the login")
    def test_a_stale_decision_is_reported_not_forced(self):
        self.login()
        R.push(self.cfg)
        snap = self.s.get(BASE + "/api/snapshot").json()["snapshot"]
        job = next(i for i in snap["items"] if i["kind"] == "job" and i["status"] == "open" and i["approval"] == "none")
        db.update_job(job["id"], {"status": "rejected", "closed_at": "2026-10-07"})          # changed on the PC after the snapshot
        self.s.post(BASE + "/api/decision", json={"id": job["id"], "kind": "job", "action": "approve"})
        res = self.pull_wait(1)
        self.assertEqual((res["applied"], res["failed"]), (0, 1))
        self.assertEqual(db.get_job(job["id"])["approval"], job["approval"])


class Offline(unittest.TestCase):
    """No Worker needed: the apply rules and the snapshot shape."""

    def setUp(self):
        self.real = db.DB_PATH
        db.DB_PATH = Path(__file__).resolve().parent / "_test_remote.db"
        if db.DB_PATH.exists():
            db.DB_PATH.unlink()
        db.init_db()
        db.create_job({"id": "j1", "title": "Werkstudent X", "employer": "Acme", "country": "DE", "source": "x", "date_found": "2026-10-01", "status": "open"})
        db.create_thesis({"id": "th1", "title": "Thesis Y", "institution": "Uni Z", "country": "DE", "status": "lead"})

    def tearDown(self):
        if db.DB_PATH.exists():
            db.DB_PATH.unlink()
        db.DB_PATH = self.real

    def test_approve_recheck_skip_applied_and_notes(self):
        self.assertEqual(R.apply_event({"item": "j1", "kind": "job", "action": "approve"}), (True, "approved: queued for the next build"))
        self.assertEqual(db.get_job("j1")["approval"], "requested")
        ok, msg = R.apply_event({"item": "j1", "kind": "job", "action": "approve"})
        self.assertTrue(ok and "already" in msg)
        self.assertTrue(R.apply_event({"item": "j1", "kind": "job", "action": "applied", "date": "2026-10-06"})[0])
        j = db.get_job("j1")
        self.assertEqual((j["status"], j["applied_at"]), ("applied", "2026-10-06"))
        ok, msg = R.apply_event({"item": "j1", "kind": "job", "action": "skip"})
        self.assertFalse(ok)                                                                # applied stays applied
        self.assertTrue(R.apply_event({"item": "j1", "kind": "job", "action": "note", "note": "call them"})[0])
        self.assertIn("[phone", db.get_job("j1")["my_notes"])

    def test_missing_rows_and_thesis(self):
        self.assertFalse(R.apply_event({"item": "nope", "kind": "job", "action": "approve"})[0])
        self.assertTrue(R.apply_event({"item": "th1", "kind": "thesis", "action": "skip"})[0])
        self.assertEqual(db.get_thesis("th1")["status"], "closed")
        self.assertFalse(R.apply_event({"item": "th1", "kind": "thesis", "action": "approve"})[0])

    def test_the_snapshot_carries_no_notes_and_no_description(self):
        db.update_job("j1", {"my_notes": "secret note", "verdict": "APPLY"}, source="owner") if False else None
        snap = R.build_snapshot()
        blob = json.dumps(snap)
        self.assertNotIn("my_notes", blob)
        self.assertNotIn("jd_path", blob)

    def test_the_details_carry_the_posting_text_and_never_my_notes(self):
        folder = Path(db.DB_PATH).parent / "jd_t"
        folder.mkdir(exist_ok=True)
        text = "Deine Aufgaben: Analyse von Sequenzdaten mit Python und R, Pharmakovigilanz, Statistik. Dein Profil: Pharmazie oder Bioinformatik. " * 12
        (folder / "description.md").write_text(text, encoding="utf-8")
        db.update_job("j1", {"my_notes": "private words", "jd_path": str(folder), "jd_read": 1}, source="owner")
        det = R.build_details([{"id": "j1", "kind": "job", "employer": "Acme", "deadline": None, "score": None}])
        blob = json.dumps(det, ensure_ascii=False)
        self.assertNotIn("private words", blob)
        self.assertIn("Sequenzdaten", det["j1"]["text"])
        self.assertTrue(any(k == "Employer" for k, _ in det["j1"]["facts"]))
        import shutil as _sh
        _sh.rmtree(folder, ignore_errors=True)

    def test_secrets_are_well_formed(self):
        s = R.make_secrets()
        it, salt, h = s["PASS_HASH"].split("$")
        self.assertEqual(it, "100000")
        self.assertGreater(len(s["PC_KEY"]), 30)
        self.assertRegex(s["passphrase"], r"^[a-z]+-[a-z]+-[a-z]+-[a-z]+-\d{4}$")


class PushOnlyWhatChanged(unittest.TestCase):
    """Cloudflare's free plan allows 1,000 KV writes a day for the whole account (21 Oct 2026: the phone page returned HTTP 500 after the limit was hit).
    `push()` must therefore write nothing when nothing changed. Offline: the upload layer and the state file are faked, so this never uses quota."""

    def setUp(self):
        from unittest import mock
        self.state: dict = {}
        self.calls: list[str] = []
        self.snap = {"generated": "t0", "items": [{"id": "a"}], "mail": {}, "stats": {}}
        self.det = {"a": {"text": "x"}}
        self.patches = [
            mock.patch.object(R, "load_config", lambda: {"url": "http://fake", "pc_key": "k"}),
            mock.patch.object(R, "load_state", lambda: dict(self.state)),
            mock.patch.object(R, "save_state", lambda st: self.state.update(st)),
            mock.patch.object(R, "build_snapshot", lambda: json.loads(json.dumps(self.snap))),
            mock.patch.object(R, "build_details", lambda items: json.loads(json.dumps(self.det))),
            mock.patch.object(R, "_http", lambda cfg, method, path, body=None: self.calls.append(path) or {"items": len(self.snap["items"])}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_first_push_uploads_both_then_an_unchanged_push_uploads_nothing(self):
        R.push()
        self.assertEqual(self.calls, ["/api/pc/snapshot", "/api/pc/details"])
        self.calls.clear()
        self.snap["generated"] = "t1"                     # only the timestamp moves
        out = R.push()
        self.assertEqual(self.calls, [])
        self.assertEqual(out["skipped"], ["snapshot unchanged", "details unchanged"])
        self.assertEqual(out["pushed"], 1)                # the phone count is still reported

    def test_a_changed_snapshot_uploads_the_snapshot_only(self):
        R.push()
        self.calls.clear()
        self.snap["items"].append({"id": "b"})
        R.push()
        self.assertEqual(self.calls, ["/api/pc/snapshot"])

    def test_a_changed_detail_uploads_the_details_only(self):
        R.push()
        self.calls.clear()
        self.det["a"]["text"] = "y"
        R.push()
        self.assertEqual(self.calls, ["/api/pc/details"])

    def test_the_heartbeats_resend_unchanged_content(self):
        from datetime import datetime, timedelta
        R.push()
        self.calls.clear()
        self.state["snap_at"] = (datetime.now() - timedelta(minutes=R.HEARTBEAT_SNAPSHOT_MIN + 1)).isoformat(timespec="seconds")
        R.push()
        self.assertEqual(self.calls, ["/api/pc/snapshot"])        # snapshot heartbeat only
        self.calls.clear()
        self.state["det_at"] = (datetime.now() - timedelta(hours=R.HEARTBEAT_DETAILS_H, minutes=1)).isoformat(timespec="seconds")
        R.push()
        self.assertEqual(self.calls, ["/api/pc/details"])         # details heartbeat only

    def test_a_manual_push_forces_both(self):
        R.push()
        self.calls.clear()
        R.push(force=True)
        self.assertEqual(self.calls, ["/api/pc/snapshot", "/api/pc/details"])

    def test_the_real_snapshot_and_details_are_stable_between_builds(self):
        """If a timestamp or counter sneaked into the hashed content, every sync would write again and the fix would do nothing."""
        for p in self.patches:
            p.stop()
        real, tmp = db.DB_PATH, tempfile.TemporaryDirectory()
        db.DB_PATH = Path(tmp.name) / "stable.db"                                   # a throwaway tracker with one best-fit role
        db.init_db()
        db.create_job({"id": "w-stable", "title": "Student Assistant NGS", "employer": "Example University", "source": "demo", "date_found": "2026-10-01",
                       "url": "https://example.org/x", "status": "open", "approval": "prepared"})          # a prepared package is in the snapshot without a score
        try:
            a, b = R.build_snapshot(), R.build_snapshot()
            strip = lambda s: R._digest({k: v for k, v in s.items() if k != "generated"})   # noqa: E731
            self.assertEqual(strip(a), strip(b))
            self.assertEqual(R._digest(R.build_details(a["items"])), R._digest(R.build_details(b["items"])))
        finally:
            db.DB_PATH = real
            tmp.cleanup()
            for p in self.patches:
                p.start()


if __name__ == "__main__":
    unittest.main(verbosity=1)



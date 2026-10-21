"""Tests for the Gmail stage (scripts/mail_sync.py, rules/mail.md): classification, matching, the status policy, alert parsing, privacy.

Run: python scripts/tests/test_mail_sync.py
"""
import os
from pathlib import Path as _P

# The tests run against the fictional example profile, never against a real one (config.py reads this variable at import).
os.environ.setdefault("JOBKIT_PROFILE_DIR", str(_P(__file__).resolve().parent.parent.parent / "examples" / "de-bioinformatics-student"))
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402
import mail_sync as M  # noqa: E402


def mail(subject, body="", sender="Recruiting <recruiting@example-corp.de>", to="sam.example@example.com", labels=None, mid="m1", date="Tue, 6 Oct 2026 10:00:00 +0000"):
    return {"id": mid, "thread_id": mid, "from": sender, "to": to, "subject": subject, "body_text": body, "snippet": body[:100], "labels": labels or ["INBOX"], "date": date}


class Classification(unittest.TestCase):
    def kind(self, m):
        c = M.classify(m)
        return c[0] if c else None

    def test_a_rejection_in_german_and_english(self):
        self.assertEqual(self.kind(mail("Ihre Bewerbung", "Leider müssen wir Ihnen mitteilen, dass wir Ihre Bewerbung nicht berücksichtigen können.")), "rejection")
        self.assertEqual(self.kind(mail("Your application with Doctolib", "Thank you for your interest in the Medical Data Intern position. We regret to inform you that we have decided not to move forward.")), "rejection")

    def test_a_language_requirement_mail_is_a_rejection(self):
        m = mail("Deine Bewerbung bei Alpha Pharma", "vielen Dank für deine Bewerbung. Für eine Tätigkeit bei Alpha Pharma sind deutsche Sprachkenntnisse auf einem Niveau von B2 erforderlich.")
        self.assertEqual(self.kind(m), "rejection")

    def test_an_acknowledgement_that_describes_the_process_is_not_an_invitation(self):
        body = ("Thank you for sending us your application documents. We will send your application to the department. If we receive positive feedback from our colleagues, "
                "we will invite you to an interview to get to know each other. Depending on the position you may also be invited to an assessment.")
        self.assertEqual(self.kind(mail("Your application at sovanta as Werkstudent* Data Science", body)), "ack")

    def test_an_active_invitation_is_an_interview(self):
        self.assertEqual(self.kind(mail("Einladung zum Vorstellungsgespräch", "wir laden Sie herzlich zu einem Vorstellungsgespräch am Montag ein.")), "interview")
        self.assertEqual(self.kind(mail("Your Application – Next Step! Sortation Associate", "Please complete the online assessment: https://x")), "interview")

    def test_an_offer_is_always_low_confidence_so_a_session_reads_it(self):
        c = M.classify(mail("Ihre Bewerbung", "wir freuen uns, Ihnen ein Vertragsangebot für die Werkstudentenstelle zu machen. Arbeitsvertrag anbei."))
        self.assertEqual(c[0], "offer")
        self.assertEqual(c[1], "low")

    def test_an_explicit_ask_is_an_info_request_but_a_footer_is_not(self):
        self.assertEqual(self.kind(mail("Your application", "we are still missing documents. Please upload a current transcript of records by 10.10.2026.")), "info_request")
        self.assertEqual(self.kind(mail("Danke für deine Bewerbung", "wir haben deine Bewerbung erhalten und melden uns. Datenschutz: wir speichern Zeugnis und Transcript nach DSGVO.")), "ack")

    def test_account_setup_and_noise_are_dropped_and_never_stored(self):
        self.assertIsNone(M.classify(mail("Passwort erstellen", "Bitte erstelle dein Passwort für das Bewerberportal", sender="x@softgarden.io")))
        self.assertIsNone(M.classify(mail("Sam Example, welcome to the Example Carmaker career portal", "We are pleased that you have created your applicant profile", sender="SuccessFactors@example-carmaker.example")))
        self.assertIsNone(M.classify(mail("Your annual statement", "balance", sender="alerts@example-bank.example")))
        self.assertIsNone(M.classify(mail("Prime Deal Days", "sale", sender="promotion@example-shop.example")))

    def test_mail_owner_sent(self):
        self.assertEqual(self.kind(mail("Bewerbung als Werkstudent Data Analytics", "Sehr geehrter Herr Beispiel", sender="Sam <sam.example@example.com>", to="hr.contact@example-company.example", labels=["SENT"])), "sent_application")
        self.assertIsNone(M.classify(mail("Termin", "bestätige", sender="sam.example@example.com", to="x@city-hall.example", labels=["SENT"])))
        self.assertIsNone(M.classify(mail("Job scan 6 Oct - 35 new", "digest", sender="sam.example@example.com", to="sam.example@example.com", labels=["SENT", "INBOX"])))

    def test_alert_senders(self):
        self.assertEqual(self.kind(mail("“pharmacometrics”: Novo posted", "x", sender="LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>")), "alert")
        self.assertEqual(self.kind(mail("9 new job ads for your search alert", "x", sender="XING Jobs <jobs@mail.xing.com>")), "alert")

    def test_css_in_a_mail_body_is_dropped(self):
        body = 'table {border-collapse: collapse !important;} @font-face { font-family: "X"; src: url(a) } leider müssen wir absagen'
        self.assertNotIn("border-collapse", M.clean_body(body))


class AlertParsing(unittest.TestCase):
    def test_linkedin_block(self):
        body = ("Your job alert for pharmacometrics\n1 new job matches.\nManage alerts: https://www.linkedin.com/comm/jobs/alerts?x=1\n\n"
                "PKPD Praktikum\nNovo Nordisk\nMåløv\n\nThis company is actively hiring\nView job: https://www.linkedin.com/comm/jobs/view/4473644712/?trackingId=abc\n\n------\n"
                "Werkstudent Data\nGamma Chemicals\nBerlin\nView job: https://www.linkedin.com/comm/jobs/view/4473644999/?trackingId=abc\n")
        items = M.parse_linkedin(mail("alert", body))
        self.assertEqual([i["key"] for i in items], ["4473644712", "4473644999"])
        self.assertEqual((items[0]["title"], items[0]["employer"], items[0]["location"]), ("PKPD Praktikum", "Novo Nordisk", "Måløv"))
        self.assertEqual(items[1]["url"], "https://de.linkedin.com/jobs/view/4473644999")     # canonical, every tracking parameter stripped

    def test_xing_block_keeps_the_m_link_as_a_key_only(self):
        body = "Be an early applicant\nWerkstudent:in Compliance\n=> https://www.xing.com/m/mpP6vcISSObTs5CNr_mRgK\nNTT DATA\nJena\nFor students\n-----\n"
        items = M.parse_xing(mail("9 new job ads", body, sender="XING Jobs <jobs@mail.xing.com>"))
        self.assertEqual(items[0]["token"], "mpP6vcISSObTs5CNr_mRgK")
        self.assertEqual((items[0]["title"], items[0]["employer"], items[0]["location"]), ("Werkstudent:in Compliance", "NTT DATA", "Jena"))
        self.assertNotIn("url", items[0])


class Throwaway(unittest.TestCase):
    def setUp(self):
        self._real = db.DB_PATH
        db.DB_PATH = Path(__file__).resolve().parent / "_test_mail.db"
        if db.DB_PATH.exists():
            db.DB_PATH.unlink()
        db.init_db()
        self.addCleanup(self._clean)

    def _clean(self):
        if db.DB_PATH.exists():
            db.DB_PATH.unlink()
        db.DB_PATH = self._real

    def job(self, jid, employer, title, status="open", **kw):
        return db.create_job({"id": jid, "title": title, "employer": employer, "country": "DE", "source": "linkedin", "date_found": "2026-09-01", "status": status, **kw})


class Matching(Throwaway):
    def test_employer_and_role_match(self):
        self.job("j1", "Zenith Instruments SE", "Werkstudent:in Procurement Excellence (w/m/d)", "applied")
        self.job("j2", "Zenith Instruments SE", "Praktikum Bioprocess Engineering", "applied")
        row, how, _ = M.Index().match(mail("Your application as Werkstudent:in Procurement Excellence (w/m/d) at Zenith Instruments", "We regret to inform you", sender="zenith@myworkday.com"), "rejection")
        self.assertEqual(row["id"], "j1")
        self.assertEqual(how, "employer and role")

    def test_a_mail_that_names_no_role_stays_unmatched_when_the_employer_has_several_rows(self):
        self.job("j1", "Alpha Pharma", "Praktikum Risk Management", "applied")
        self.job("j2", "Alpha Pharma", "Praktikum Information Security", "applied")
        row, how, near = M.Index().match(mail("Deine Bewerbung bei Alpha Pharma", "leider", sender="Alpha Pharma <system@successfactors.eu>"), "rejection")
        self.assertIsNone(row)
        self.assertEqual(len(near), 2)

    def test_generic_words_and_topic_words_do_not_make_an_employer(self):
        self.job("j1", "FERCHAU GmbH Wiesbaden Pharma & Life Science", "Werkstudent HR/Recruiting", "open")
        row, _, _ = M.Index().match(mail("Application: Student Assistant", "M.Sc. in Life Science Informatics, clinical pharmacy", sender="sam.example@example.com", to="prof.sample@example-institute.example", labels=["SENT"]), "sent_application")
        self.assertIsNone(row)

    def test_a_shared_inbox_address_never_identifies_a_row_but_a_personal_one_does(self):
        self.job("j1", "Example Institute", "HiWi Thesis Multimodal AI Antifibrotic", "open", apply_url="prof.example@uni-example.de")
        self.job("j2", "Example Hospital", "Studentische Hilfskraft BIH", "open", apply_url="meine.bewerbung@example-hospital.example")
        idx = M.Index()
        row, how, _ = idx.match(mail("Application: HiWi", "x", sender="sam.example@example.com", to="prof.example@uni-example.de", labels=["SENT"]), "sent_application")
        self.assertEqual((row["id"], how), ("j1", "address"))
        self.assertFalse(M.personal_address("meine.bewerbung@example-hospital.example"))

    def test_a_reference_number_beats_everything(self):
        self.job("j1", "Example Pharma", "Werkstudent Supply Chain", "applied", ref_number="R00150088")
        self.job("j2", "Example Pharma", "Werkstudent Medical Affairs", "applied", ref_number="R00149024")
        row, how, _ = M.Index().match(mail("Werkstudent Supply Chain - R00150088 Update from Example Pharma", "we have decided"), "rejection")
        self.assertEqual((row["id"], how), ("j1", "reference number"))


class Policy(Throwaway):
    def idx_row(self, jid):
        return next(r for r in M.Index().rows if r["id"] == jid)

    def test_acknowledgement_or_sent_mail_moves_open_to_applied_with_the_mail_date(self):
        self.job("j1", "Acme", "Werkstudent Data", "open")
        state, _ = M.act_job(self.idx_row("j1"), "ack", "2026-09-28", "employer and role", False)
        j = db.get_job("j1")
        self.assertEqual((state, j["status"], j["applied_at"]), ("applied", "applied", "2026-09-28"))
        self.assertTrue(j["status_source"].startswith("gmail 2026-09-28"))

    def test_an_acknowledgement_never_downgrades_a_later_status(self):
        self.job("j1", "Acme", "Werkstudent Data", "interview", applied_at="2026-09-20")
        state, _ = M.act_job(self.idx_row("j1"), "ack", "2026-09-28", "x", False)
        self.assertEqual((state, db.get_job("j1")["status"]), ("already", "interview"))

    def test_a_rejection_always_wins(self):
        self.job("j1", "Acme", "Werkstudent Data", "interview")
        state, _ = M.act_job(self.idx_row("j1"), "rejection", "2026-10-01", "address", False)
        j = db.get_job("j1")
        self.assertEqual((state, j["status"], j["closed_at"]), ("applied", "rejected", "2026-10-01"))

    def test_a_row_owner_marked_not_for_me_is_left_alone(self):
        self.job("j1", "Acme", "Werkstudent Data", "skip")
        state, _ = M.act_job(self.idx_row("j1"), "rejection", "2026-10-01", "address", False)
        self.assertEqual((state, db.get_job("j1")["status"]), ("already", "skip"))

    def test_an_invitation_after_a_rejection_is_not_applied_it_is_read(self):
        self.job("j1", "Acme", "Werkstudent Data", "rejected")
        state, _ = M.act_job(self.idx_row("j1"), "interview", "2026-10-02", "address", False)
        self.assertEqual((state, db.get_job("j1")["status"]), ("needs_read", "rejected"))

    def test_my_notes_is_never_touched(self):
        self.job("j1", "Acme", "Werkstudent Data", "open")
        db.update_job("j1", {"my_notes": "mine"}, source="owner")
        M.act_job(self.idx_row("j1"), "rejection", "2026-10-01", "address", False)
        self.assertEqual(db.get_job("j1")["my_notes"], "mine")

    def test_thesis_outreach_and_reply(self):
        db.create_thesis({"id": "th1", "title": "Agentic twins", "institution": "Example Institute", "country": "DE", "status": "lead", "pi_email": "a.b@example-institute.example"})
        row = next(r for r in M.Index().rows if r["id"] == "th1")
        self.assertEqual(M.act_thesis(row, "sent_application", "2026-09-27", "sent", False)[0], "applied")
        self.assertEqual(db.get_thesis("th1")["status"], "outreach_sent")
        row = next(r for r in M.Index().rows if r["id"] == "th1")
        M.act_thesis(row, "rejection", "2026-10-01", "received", False)
        self.assertEqual(db.get_thesis("th1")["status"], "declined")


class Process(Throwaway):
    def test_weak_match_does_not_reject_and_noise_is_not_stored(self):
        self.job("j1", "Example Software AG", "Werkstudent Digital Health", "applied")
        self.job("j2", "Example Software AG", "Werkstudent Medikationssoftware", "applied")
        msgs = [mail("Ihre Bewerbung bei der Example Software Unternehmensgruppe", "Leider müssen wir Ihnen mitteilen, dass wir Ihre Bewerbung nicht berücksichtigen können.",
                     sender="Karriere@example-software.example", mid="a"),
                mail("Prime Deal Days", "sale", sender="promotion@example-shop.example", mid="b")]
        res = M.process(msgs, False, False)
        self.assertEqual(db.get_job("j1")["status"], "applied")
        self.assertEqual(db.get_job("j2")["status"], "applied")
        self.assertEqual(len(db.list_mail_events()), 1)
        self.assertEqual(db.mail_event("a")["state"], "unmatched")
        self.assertEqual(res["dropped_noise"], 1)

    def test_the_event_log_keeps_facts_not_the_body_and_a_mail_is_processed_once(self):
        self.job("j1", "Zenith Instruments SE", "Werkstudent Procurement Excellence", "applied")
        m = mail("Your application as Werkstudent Procurement Excellence at Zenith Instruments", "SECRET BODY We regret to inform you.", sender="zenith@myworkday.com", mid="x")
        M.process([m], False, False)
        e = db.mail_event("x")
        self.assertEqual((e["kind"], e["state"], e["job_id"]), ("rejection", "applied", "j1"))
        self.assertNotIn("SECRET", str(e))
        M.process([m], False, False)                       # a second pass changes nothing and does not duplicate
        self.assertEqual(len(db.list_mail_events()), 1)
        self.assertEqual(db.get_job("j1")["status"], "rejected")

    def test_a_student_level_alert_posting_is_filed_as_an_unscored_stub_and_a_known_one_is_not(self):
        self.job("j9", "Gamma Chemicals", "Werkstudent Data", "open", url="https://de.linkedin.com/jobs/view/4473644999")
        body = ("PKPD Praktikum\nNovo Nordisk\nMåløv\nView job: https://www.linkedin.com/comm/jobs/view/4473644712/?x=1\n------\n"
                "Senior Director Pharmacometrics\nAllucent\nRemote\nView job: https://www.linkedin.com/comm/jobs/view/4473600000/?x=1\n------\n"
                "Werkstudent Data\nGamma Chemicals\nBerlin\nView job: https://www.linkedin.com/comm/jobs/view/4473644999/?x=1\n")
        res = M.process([mail("alert", body, sender="LinkedIn <jobalerts-noreply@linkedin.com>", mid="al")], False, False)
        self.assertEqual(res["filed"]["not_student_level"], 1)
        self.assertEqual(res["filed"]["known"], 1)
        self.assertEqual(len(res["filed"]["filed"]), 1)
        stub = db.get_job(res["filed"]["filed"][0])
        self.assertEqual((stub["analysis_level"], stub["score"], stub["url"]), ("stub", None, "https://de.linkedin.com/jobs/view/4473644712"))


class RealMailRegressions(Throwaway):
    """Mistakes the first pass over the real mailbox made, kept so they cannot come back."""

    def test_a_german_legal_footer_does_not_match_a_role(self):
        self.job("j1", "HanseWerk AG", "Werkstudent im Gremienmanagement für Vorstand & Aufsichtsrat (m/w/d)", "open")
        body = "Leider müssen wir Ihnen mitteilen, dass wir Ihre Bewerbung nicht berücksichtigen. Example Software AG, Vorstand: A. B., Aufsichtsrat: C. D., Amtsgericht München"
        row, _, _ = M.Index().match(mail("Ihre Bewerbung bei der Example Software Unternehmensgruppe", body, sender="Karriere@example-software.example"), "rejection")
        self.assertIsNone(row)

    def test_a_mail_that_names_a_role_never_matches_an_employer_only_row_of_another_role(self):
        self.job("j1", "Marketplace", "2026 Applied Scientist Intern, Marketplace University Talent", "open")
        row, how, _ = M.Index().match(mail("Your Application - Sortation Associate (m/f/d) - Nittenau", "thank you", sender="Marketplace Staffing <noreply@jobs.example-marketplace.example>"), "ack")
        self.assertIsNone(row)

    def test_a_weak_match_does_not_confirm_an_application_either(self):
        self.assertFalse(M.may_change_status("ack", "role words only"))
        self.assertFalse(M.may_change_status("rejection", "employer and one role word"))
        self.assertTrue(M.may_change_status("rejection", "reference number"))
        self.assertTrue(M.may_change_status("ack", "employer only (one role of this employer is in the tracker)"))
        self.assertFalse(M.may_change_status("rejection", "employer only (one role of this employer is in the tracker)"))

    def test_a_decision_a_session_made_is_not_recomputed(self):
        self.job("j1", "Example Software AG", "Werkstudent Digital Health", "applied")
        self.job("j2", "Other Corp", "Werkstudent Something", "applied")
        m = mail("Ihre Bewerbung bei der Example Software Unternehmensgruppe", "Leider müssen wir Ihnen mitteilen, dass wir nicht berücksichtigen.", sender="Karriere@example-software.example", mid="z")
        M.process([m], False, False)
        db.save_mail_event({"msg_id": "z", "kind": "rejection", "direction": "received", "job_id": "j2", "state": "already", "judged_by": "claude"})
        M.process([m], False, True)                                  # even a full re-read leaves the judged event alone
        self.assertEqual(db.mail_event("z")["job_id"], "j2")

    def test_html_entities_and_template_css_do_not_hide_a_rejection(self):
        self.assertEqual(M.classify(mail("Ihre Bewerbung (Example Labs)", "Leider m&uuml;ssen wir Ihnen mitteilen, dass wir uns f&uuml;r eine/n andere/n Bewerber/in entschieden haben.", sender="Example Labs <recruiting@example-labs.example>"))[0], "rejection")
        css = "@import url(https://x/y.css); body { margin:0 } #a { padding:0 } "
        m = mail("Your application", css, sender="Example Heating <careers-example@rexx-recruitment.com>")
        m["snippet"] = "Unfortunately we have decided not to move forward with your application."
        self.assertEqual(M.classify(m)[0], "rejection")


if __name__ == "__main__":
    unittest.main(verbosity=1)

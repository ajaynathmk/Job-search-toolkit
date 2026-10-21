#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/mail_sync.py — Gmail inside the pipeline (stages S10 and S11 of rules/pipeline.md).

Two jobs, one pass over the mailbox:

  S10  What happened to my applications.  Mail the owner SENT (applications, outreach to professors) and mail he RECEIVED from employers and
       their applicant portals (acknowledgements, rejections, interview and assessment invitations, offers, requests for documents).
       Each is classified, matched to a tracker row on employer AND role, and the row's status is moved:
         application sent / acknowledgement  -> applied (applied_at = the mail date)
         interview or assessment invitation  -> interview
         rejection                           -> rejected   (a rejection always wins)
         offer / request for documents       -> a line in ACT NOW (no status exists for them), the row moves to interview at most
       A status the owner set by hand is never downgraded (interview beats an acknowledgement); status_source records "gmail <date>".
  S11  What is new.  Job-alert mail (LinkedIn, Xing, jobvector, employer career alerts) is parsed for postings; every student-level one the
       tracker does not know is filed as an unscored stub (intake.make_stub) and the next intake pass fetches its full JD and analyses it
       (THE READING RULE: nothing is scored from an email). A Xing /m/ link is a harvest key only (rules/runbook.md): it is resolved to the
       posting's own address before anything is stored; if it cannot be resolved the candidate waits in data/mail/pending.json.

This module only READS Gmail (gmail.readonly scope in practice): it never replies, forwards, labels, trashes or sends (CLAUDE.md rule 2).
Only job-related mail is kept: an event stores sender, subject, date, the classification and the match, never the body, and noise
(banks, newsletters, shops) is dropped before anything is stored. Fetched messages are cached under data/mail/msg (gitignored).

Where the messages come from:
  - OAuth through scripts/gmail_client.py (unattended; needs a valid config/gmail_token.json; `python scripts/gmail_client.py auth` renews it)
  - a snapshot file (--snapshot data/mail/snapshot.json): the same message records, written by a Claude session that read the mailbox
    through the Gmail connector. This is the fallback when the token is dead, so the pipeline never skips mail silently.

    python scripts/mail_sync.py run [--days N] [--snapshot FILE] [--dry] [--reprocess]
    python scripts/mail_sync.py status | queue | show <msg_id> | judge <msg_id> --kind K [--job ID | --thesis ID] [--note TEXT]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MAIL = ROOT / "data" / "mail"
STATE_PATH = MAIL / "state.json"
PENDING_PATH = MAIL / "pending.json"
QUEUE_PATH = MAIL / "queue.json"
DIGESTS = ROOT / "digests"

SELF_ADDRESSES = {a.lower() for a in config.get().owner_emails}
FIRST_SYNC_DAYS = 45
RESOLVE_PENDING_DAYS = 14

# Gmail searches. Targeted on purpose: only job-related mail is fetched and cached, never the whole mailbox.
ATS_SENDERS = (
    "myworkday.com successfactors.eu successfactors.com softgarden.io concludis.de hrworks.de workablemail.com ashbyhq.com greenhouse.io lever.co "
    "smartrecruiters.com personio.de personio.com join.com recruitee.com teamtailor.com rexx-systems.com d-vinci.de onlyfy.jobs b-ite.com "
    "talentacquisition.abbvie.com talent.com bewerbermanagement.de umantis.com cvmanager.de rexx-recruitment.com jobs2web.com careers-noreply "
    "meine.bewerbung").split()
REPLY_QUERIES = [
    "in:sent (Bewerbung OR Application OR Praktikum OR Werkstudent OR Masterarbeit OR thesis OR HiWi OR \"student assistant\" OR Anfrage OR enquiry OR inquiry OR internship OR candidature OR solicitud OR candidatura)",
    "from:(" + " OR ".join(ATS_SENDERS) + ")",
    "subject:(Bewerbung OR application OR Absage OR Rückmeldung OR Rueckmeldung OR candidacy OR \"job application\" OR Einladung OR Interview OR assessment)",
    "(Bewerbung OR Bewerbungseingang OR Eingangsbestätigung OR \"Ihre Bewerbung\" OR Absage OR \"your application\" OR \"application received\" OR \"we regret\" "
    "OR Vorstellungsgespräch OR \"invite you\" OR \"nicht berücksichtigen\" OR \"anderweitig vergeben\")",
]
ALERT_QUERIES = [
    "from:jobalerts-noreply@linkedin.com",
    "from:jobs-noreply@linkedin.com",
    "from:messages-noreply@linkedin.com subject:hiring",
    "from:(jobs2web.com)",
]
# the region pack adds its own boards' alert mail (regions/<code>/region.json: mail.alert_queries, mail.alert_senders, mail.query_words)
_RM = config.get().region.get("mail") or {}
_PM = config.get().profile.get("mail") or {}
ALERT_QUERIES += list(_RM.get("alert_queries") or []) + list(_PM.get("alert_queries") or [])
if _RM.get("query_words") or _PM.get("query_words"):
    _w = " OR ".join(dict.fromkeys(list(_RM.get("query_words") or []) + list(_PM.get("query_words") or [])))
    REPLY_QUERIES.append(f"subject:({_w})")

# ----------------------------------------------------------------------------- text helpers


def fold(s: str) -> str:
    """Lower-case, umlauts/accents folded, damaged characters dropped: 'Charité' and 'Charit�' both become 'charite'/'charit'."""
    s = (s or "").lower().replace("�", "")
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(s))


def addr_of(header: str) -> str:
    return parseaddr(header or "")[1].lower()


def addrs_in(header: str) -> list[str]:
    return [a.lower() for a in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", header or "")]


def mail_day(m: dict) -> str:
    """ISO date of the message (its own Date header, else Gmail's internal timestamp)."""
    try:
        return parsedate_to_datetime(m.get("date", "")).astimezone(timezone.utc).date().isoformat()
    except Exception:  # noqa: BLE001
        pass
    if m.get("internal_ms"):
        return datetime.fromtimestamp(int(m["internal_ms"]) / 1000, timezone.utc).date().isoformat()
    return date.today().isoformat()


def one_line(s: str, n: int = 160) -> str:
    return " ".join((s or "").split())[:n]


# ----------------------------------------------------------------------------- 1. classify

JOB_WORDS = re.compile(r"bewerb|application|applying|candidat|werkstudent|praktik|intern\b|internship|masterarbeit|abschlussarbeit|thesis|hiwi|hilfskraft|student(?:ische)?\b|"
                       r"stelle\b|position\b|vacanc|recruit|talent|karriere|career|job\b|jobs\b", re.I)
ALERT_SENDER = re.compile(r"jobalerts-noreply@linkedin|jobs-noreply@linkedin|messages-noreply@linkedin|jobs2web\.com.*jobnotification|jobnotification@|"
                          r"alerts@indeed|noreply@glassdoor|stepstone|jobs@mail\.xing\.com" + "".join("|" + p for p in (_RM.get("alert_senders") or []) + (_PM.get("alert_senders") or [])), re.I)
NOT_JOB_SENDER = re.compile(r"mailrobot@|bank|instagram|github|google\.com|zapier|anthropic|telegram|newsletter|amazon\.|paypal|netflix|spotify|facebook|twitter"
                            + "".join("|" + p for p in (_PM.get("ignore_senders") or [])), re.I)
ATS_RX = re.compile("|".join(re.escape(d) for d in ATS_SENDERS if "." in d) + r"|karriere@|bewerbung@|recruiting@|recruitment@|careers?@|jobs@|talent|personal@|hr@", re.I)

REJECTION = re.compile(
    r"leider (?:müssen|muessen|können|koennen|konnten|haben|ist|sind|nicht|möchten|moechten|werden|fiel|fällt)|unfortunately|we regret|regret to inform|"
    r"not (?:been )?selected|nicht (?:weiter )?berücksichtig|nicht weiter berucksichtig|nicht ber(?:ü|ue)cksichtig|nicht in die engere|anderweitig (?:vergeben|besetzt)|"
    r"andere(?:n)? bewerber|other candidates|not (?:be )?(?:able to )?(?:move|proceed|continue) (?:forward|further|with)|not moving forward|decided not to (?:move|proceed)|"
    r"absage|nicht (?:weiter)?verfolgen|nicht fortsetzen|keine (?:weiteren )?(?:berücksichtigung|beruecksichtigung)|(?:declin|reject)(?:e|ed|ing)\b|"
    r"nicht (?:zum zuge|ausgew[aä]hlt)|decided to (?:pursue|move forward with) (?:other|another)|position has been filled|stelle (?:ist|wurde) (?:bereits )?(?:besetzt|vergeben)|"
    r"sprachkenntnisse[^.]{0,120}(?:erforderlich|vorausgesetzt|notwendig|verpflichtend)|sehr viele bewerbungen erhalten|viele qualifizierte bewerbungen|"
    r"not the right fit|nicht (?:in unser|zu unserem) profil|passt nicht|not able to offer you|can(?:no|')?t offer you",
    re.I)
INTERVIEW = re.compile(
    r"einladung zum (?:gespr|interview|vorstellungs|online|assessment|test|kennenlern)|einladung zu(?:r|m|einem) (?:vorstellungsgespr|interview|online|assessment|gespr|kennenlern)|"
    r"wir (?:laden|möchten|moechten|würden|wuerden)[^.]{0,60}(?:ein(?:laden)?\b|zu (?:einem|einer|unserem))[^.]{0,60}(?:gespr|interview|kennenlern|assessment|test)|"
    r"laden (?:dich|sie|euch) (?:gerne |herzlich |nun |daher )*(?:zu|ein)[^.]{0,80}(?:gespr|interview|kennenlern|assessment|test)|"
    r"(?:would like to|we(?:'d| would) like to|are happy to|pleased to) invite you|invite you to (?:an? |our |the )?(?:interview|call|assessment|online|video|meeting)|"
    r"(?:schedule|book|arrange|vereinbaren|buchen)[^.]{0,40}(?:your |ihr(?:en)? |dein(?:en)? |a |an |einen )?(?:interview|vorstellungsgespr|kennenlerngespr|gespr(?:ä|ae)ch|telefonat|call|slot|termin)|"
    r"online[- ]?(?:assessment|test)[^.]{0,120}(?:link|complete|start|absolvier|durchf|frist|deadline|bis zum|within)|your application [-–] next step|next step[^.]{0,60}assessment|"
    r"(?:video|telefon)(?:interview|gespr(?:ä|ae)ch)[^.]{0,80}(?:termin|date|datum|vorschl|slot)", re.I)
OFFER = re.compile(r"vertragsangebot|arbeitsvertrag (?:anbei|im anhang|zugesch|zur unterschrift)|we(?:'re| are) (?:pleased|delighted|happy|thrilled) to offer you|offer letter|job offer|"
                   r"(?:ein|das|unser) (?:vertrags|jobangebot|stellenangebot)|(?:zusage|zusagen)[^.]{0,40}(?:stelle|position|praktikum|werkstudent)|"
                   r"herzlichen gl(?:ü|ue)ckwunsch[^.]{0,80}(?:stelle|position|praktikum|werkstudent|zusage)|congratulations[^.]{0,80}(?:offer|position|role|selected)", re.I)
INFO_REQUEST = re.compile(
    r"bewerbung best(?:ä|ae)tigen|best(?:ä|ae)tigung (?:bzw\.? )?identifikation|(?:missing|fehlende)[^.]{0,30}(?:document|unterlagen|informationen)|"
    r"(?:please|can you please|could you please|kindly) (?:submit|upload|provide|send|update|complete|confirm|verify|finish)|bitte (?:senden|laden|reichen|reiche|übermitteln|uebermitteln|"
    r"nachreichen|aktualisieren|vervollst|erg(?:ä|ae)nzen|best(?:ä|ae)tigen)[^.]{0,60}|nachreichen|update your (?:career )?profile|complete your application|"
    r"(?:didn.t|did not|not) (?:yet )?(?:finish|complete)(?:ed)? your application|action required|r(?:ü|ue)ckmeldung bis zum|please (?:log in|click)[^.]{0,60}(?:upload|document|profile|confirm)", re.I)
ACK = re.compile(r"eingegangen|erhalten|received|thanks? for applying|thank you for applying|bedanken uns f(?:ü|ue)r die (?:zusendung|(?:ü|ue)bersendung)|danke(?:n)? (?:wir )?(?:dir|ihnen)? ?f(?:ü|ue)r (?:deine|ihre) "
                 r"bewerbung|vielen dank f(?:ü|ue)r die (?:zusendung|(?:ü|ue)bersendung)|angekommen|gesichtet|an den zust(?:ä|ae)ndigen fachbereich weitergeleitet|ihre bewerbung wurde weitergeleitet|"
                 r"wir freuen uns (?:(?:ü|ue)ber|dass)|um etwas geduld|bearbeitung ihrer bewerbung|thank you for (?:sending|submitting|your|applying)|we (?:will|are) (?:contact|looking at|review)|process your application|danke f(?:ü|ue)r (?:deine|ihre|ihr) (?:bewerbung|interesse)|"
                 r"vielen dank f(?:ü|ue)r (?:deine|ihre|ihr)|bewerbung (?:ist )?(?:bei uns )?eingegangen|eingangsbest(?:ä|ae)tigung|automatische antwort|auto-?reply|"
                 r"submitted successfully|wir haben (?:deine|ihre) bewerbung|we have (?:successfully )?received|application (?:has been )?(?:received|submitted)|"
                 r"bewerbung (?:wird|werden) gepr(?:ü|ue)ft|we will review|sichten|bearbeitungszeit|decision[^.]{0,40}(?:take|time)|entscheidungsfindung", re.I)
SENT_APPLICATION_SUBJECT = re.compile(r"bewerb|application|applying|praktik|werkstudent|working student|masterarbeit|thesis|hiwi|student assistant|studentische|intern\b|internship|"
                                      r"enquiry|inquiry|anfrage|interest in", re.I)
def _extend(rx: re.Pattern, key: str) -> re.Pattern:
    """Add the wordings of other languages (resources/mail_patterns.json, profile/mail_patterns.json) to a built-in pattern."""
    extra = list(config.resource("mail_patterns.json", {}).get(key) or [])
    extra += list(config._read(config.profile_path("mail_patterns.json"), {}).get(key) or [])
    return re.compile(rx.pattern + "".join("|" + e for e in extra), rx.flags) if extra else rx


REJECTION, INTERVIEW, OFFER, INFO_REQUEST, ACK = (_extend(REJECTION, "rejection"), _extend(INTERVIEW, "interview"), _extend(OFFER, "offer"),
                                                  _extend(INFO_REQUEST, "info_request"), _extend(ACK, "ack"))
OUR_OWN_DIGEST = re.compile(r"^(?:job scan|job digest|fwd: job scan)", re.I)
# Sent mail that is clearly not about a job
SENT_NOT_JOB_RECIPIENT = re.compile("|".join(_PM.get("ignore_recipients") or []) or r"(?!x)x", re.I)     # profile/profile.json: mail.ignore_recipients


CONDITIONAL = re.compile(r"\b(?:if|wenn|falls|sollte|sollten|should|sobald|once|depending|je nach|may|might|kann|können|koennen|werden wir|we will|we'll|will be|nächsten schritt|naechsten schritt|"
                         r"next steps?|usually|in der regel|normalerweise|typically|can be|could|würden|wuerden|would)\b", re.I)
CSS_BLOCK = re.compile(r"[^{}\n]{0,160}\{[^{}]*\}")
SETUP_MAIL = re.compile(r"created your (?:applicant )?profile|welcome to (?:the )?.{0,40}career portal|einmalpasswort|one[- ]time (?:password|code)|\botp\b|passwort (?:erstellen|zur(?:ü|ue)ck)|"
                        r"account (?:created|details)|konto (?:erstellt|aktivier)|verify your (?:email|account)|verifizierung (?:deines|ihres)|verifizierung deines benutzerkontos|"
                        r"candidate profile|bewerberkonto|zugangsdaten|set (?:up )?your password|activate your account", re.I)


def clean_body(body: str) -> str:
    """Mail bodies can be HTML entities ('&uuml;') or carry the CSS of the HTML template as text; both are normalised before anything is read."""
    import html as _html
    if re.search(r"&(?:[a-z]{2,8}|#\d{2,5});", body):
        body = _html.unescape(body)
    body = re.sub(r"@import[^;\n]*;?", " ", body)
    for _ in range(3):
        body = CSS_BLOCK.sub(" ", body)
    return re.sub(r"[ \t]{2,}", " ", body)


def invitation(subject: str, body: str) -> bool:
    """An active invitation: the invitation wording must appear in a sentence that is not a description of the process."""
    if re.search(r"your application [-–] next step|next steps?!", subject, re.I) and re.search(r"assessment|interview|test|gespr", subject + body[:800], re.I):
        return True
    for sent in re.split(r"(?<=[.!?])\s+|\n+", body):
        if INTERVIEW.search(sent) and not CONDITIONAL.search(sent):
            return True
    return INTERVIEW.search(subject) is not None and not CONDITIONAL.search(subject)


def classify(m: dict) -> tuple[str, str, str] | None:
    """(kind, confidence, why), or None when the message is not job mail (noise is dropped, never stored).
    kind: alert | sent_application | ack | rejection | interview | offer | info_request | reply | other_job"""
    sender = addr_of(m.get("from", ""))
    subject = m.get("subject", "") or ""
    snippet = clean_body(m.get("snippet") or "")
    body = clean_body(m.get("body_text") or "")
    if len(re.findall(r"[A-Za-zÄÖÜäöüß]{4,}", body[:1500])) < 12:      # nothing but markup survived: Gmail's snippet is the text
        body = snippet
    body = f"{snippet}\n{body}" if snippet and snippet[:60] not in body[:400] else body
    head = f"{subject}\n{body[:3500]}"
    labels = set(m.get("labels") or [])
    if OUR_OWN_DIGEST.search(subject) and sender in SELF_ADDRESSES:
        return None
    # ---- mail the owner sent
    if "SENT" in labels or sender in SELF_ADDRESSES:
        to = addrs_in(m.get("to", ""))
        if not to or all(a in SELF_ADDRESSES for a in to):
            return None
        if SENT_NOT_JOB_RECIPIENT.search(m.get("to", "")):
            return None
        if SENT_APPLICATION_SUBJECT.search(subject) or SENT_APPLICATION_SUBJECT.search(body[:600]):
            return ("sent_application", "high", "sent by the owner, application wording")
        return None
    # ---- alert mail
    if ALERT_SENDER.search(m.get("from", "")) and not re.search(r"bewerbung|your application", subject, re.I):
        return ("alert", "high", "job-alert sender")
    if NOT_JOB_SENDER.search(m.get("from", "")) and not ATS_RX.search(m.get("from", "")):
        return None
    ats = bool(ATS_RX.search(m.get("from", "")))
    if not (ats or JOB_WORDS.search(subject)):
        return None
    # ---- replies: the order is the policy. A rejection always wins; an invitation beats an acknowledgement.
    if SETUP_MAIL.search(subject) or (SETUP_MAIL.search(body[:400]) and not REJECTION.search(head)):
        return None                      # account set-up, one-time passwords: not about the application itself
    rej, off, inf, ack = (bool(rx.search(head)) for rx in (REJECTION, OFFER, INFO_REQUEST, ACK))
    itv = invitation(subject, body[:3500])
    if re.search(r"neue jobs|new jobs|job ?empfehlung|job recommendations|current career opportunities|job-?agent", head[:400], re.I) and not (rej or itv or off):
        return ("alert", "medium", "employer career alert")
    if rej and not itv:
        return ("rejection", "high" if re.search(r"leider|unfortunately|regret|not selected|absage|nicht berücksichtigt|nicht beruecksichtigt|not (?:be )?moving forward", head, re.I) else "medium", "rejection wording")
    if rej and itv:
        return ("rejection", "low", "both a rejection and an invitation wording: a session must read it")
    if off and not rej:
        return ("offer", "low", "offer wording: a session must read it before anything moves")
    if itv:
        return ("interview", "high", "an invitation to an interview or assessment")
    if inf:
        return ("info_request", "medium", "asks the owner to do, send or confirm something")
    if ack:
        return ("ack", "high", "acknowledgement wording")
    return ("other_job", "low", "job mail without a clear signal: a session must read it")


# ----------------------------------------------------------------------------- 2. match to the tracker

GENERIC = set("vorstand aufsichtsrat geschaeftsfuehrer geschaeftsfuehrung geschaeftsfuehrerin registergericht handelsregister amtsgericht steuernummer sitz vorsitzender vorsitzende datenschutz impressum "
              "bewerbung bewerbungen bewerben application applications applying apply stelle stellen ausschreibung studium studierende ermoeglicht moeglichkeit moeglichkeiten "
              "unterlagen unternehmen unternehmens abschluss angebote angebot jobs job karriere career careers talent recruiting "
              "werkstudent werkstudentin werkstudierende student studentische studentischer studentin hilfskraft working praktikum praktikant praktikantin internship intern "
              "masterarbeit abschlussarbeit thesis master bachelor mitarbeiter mitarbeiterin position stelle role mwd wmd mfd fmx genders all gender team bereich im in der die das "
              "und and for the fuer von zur zum bei als mit und oder".split())
EMP_STOP = set("gmbh ag se kg co ev e v mbh inc ltd sa group gruppe holding the und and universitaet university universitat uniklinikum universitaetsklinikum klinikum institut "
               "institute institution hochschule technische technical deutschland germany europe europa international pharma pharmaceuticals pharmaceutical".split())
REF_RX = re.compile(r"\b(?:R-?\d{5,9}|JR[_-]?\d{5,8}|REQ[-_ ]?\d{4,9}|\d{5,9})\b", re.I)


FUNCTION_WORDS = set("des die der das dem den dann damit wat machste fuer und oder mit von zur zum bei als ein eine einer eines im in am an auf aus nach ueber unter sowie wir sie ihr ihre "
                     "https http www com org net de eu fileadmin pdf html php aspx the of for and to a an at on by with our your their".split())


DOMAIN_TERMS = set("life science sciences lifescience medical health healthcare pharma pharmaceutical bio biotech biotechnology data digital medizin medizinische medicine klinik clinic "
                   "gesellschaft verein stiftung research forschung center centre technology technologies tech solutions services service consulting systems software engineering "
                   "labor laboratory labs diagnostics diagnostik care therapeutics analytics sales business management hospital krankenhaus zentrum".split())


def emp_tokens(name: str) -> list[str]:
    if len(name or "") > 70 or "http" in (name or "").lower():     # a page title or a URL parsed as an employer: not an employer name
        return []
    return [t for t in words(name) if len(t) >= 3 and t not in EMP_STOP and t not in GENERIC and t not in FUNCTION_WORDS and t not in DOMAIN_TERMS]


def role_tokens(title: str) -> list[str]:
    return [t for t in words(title) if len(t) >= 4 and t not in GENERIC and t not in FUNCTION_WORDS]


def _has_word(hay_words: set[str], hay_text: str, tok: str) -> bool:
    return tok in hay_words or (len(tok) >= 7 and tok in hay_text)


def _norm_ref(x: str) -> str:
    return x.upper().replace("_", "").replace("-", "").replace(" ", "")


SHARED_INBOX = re.compile(r"^(?:no-?reply|do-?not-?reply|donotreply|noreply\d*|bewerbung(?:en)?|karriere|career(?:s)?|recruit\w*|jobs?|hr|personal|talent\w*|notifications?|info|support|"
                          r"meine\.bewerbung|mailer|system|workday\w*|service|kontakt|contact|team|application\w*|bewerbermanagement|bewerberkommunikation|online-?bewerbung)$", re.I)


def personal_address(a: str) -> bool:
    return bool(a) and not SHARED_INBOX.match(a.split("@")[0])


ROLE_IN_SUBJECT = re.compile(r"werkstudent|praktik|intern\b|internship|working student|student(?:ische|ischer)?\b|trainee|thesis|abschlussarbeit|masterarbeit|hilfskraft|mitarbeiter|associate|"
                             r"engineer|analyst|manager|specialist|assistant|scientist|developer|consultant|stelle\b|position\b|initiativ", re.I)


class Index:
    """Everything a mail can be matched to: job rows and thesis rows, with their folded employer/role tokens. An employer word counts as
    distinctive only when few employers in the tracker share it ('charite', 'kws', 'dlr' do; 'life', 'science', 'medical', 'berlin' do not)."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        for j in db.list_jobs():
            emails = {a for a in addrs_in(f"{j.get('contact_email') or ''} {j.get('apply_url') or ''}") if personal_address(a)} - SELF_ADDRESSES
            self.rows.append({"kind": "job", "id": j["id"], "emp": emp_tokens(j["employer"] or ""), "title": j["title"] or "", "roles": role_tokens(j["title"] or ""),
                              "status": j["status"], "emails": emails, "refs": {_norm_ref(x) for x in [j.get("ref_number") or "", *re.findall(r"\d{5,9}", j["id"] or "")] if x}, "row": j})
        for t in db.list_thesis():
            emails = {a for a in addrs_in(f"{t.get('pi_email') or ''} {t.get('contact_email') or ''}") if personal_address(a)} - SELF_ADDRESSES
            self.rows.append({"kind": "thesis", "id": t["id"], "emp": emp_tokens(t["institution"] or ""), "title": t["title"] or "",
                              "roles": role_tokens(t["title"] or ""), "status": t["status"], "emails": emails, "refs": set(), "row": t})
        df: dict[str, set[str]] = {}
        for r in self.rows:
            for tok in set(r["emp"]):
                df.setdefault(tok, set()).add(" ".join(r["emp"]))
        self.df = {k: len(v) for k, v in df.items()}
        tdf: dict[str, int] = {}
        for r in self.rows:
            for tok in set(r["roles"]) | set(words(r["title"])):
                tdf[tok] = tdf.get(tok, 0) + 1
        self.tdf = tdf

    def distinctive(self, tok: str) -> bool:
        """An employer word: few employers share it and it is not a topic word that fills job titles ('datenmanagement', 'learning', 'informatik')."""
        return self.df.get(tok, 0) <= 2 and self.tdf.get(tok, 0) <= 3

    def weight(self, tok: str) -> float:
        """How much a role word says: a long rare word a lot, a word in many titles ('bioinformatics', 'assistant') little."""
        return min(len(tok), 10) * (1.0 if self.tdf.get(tok, 0) <= 6 else 0.3)

    def match(self, m: dict, kind: str) -> tuple[dict | None, str, list[dict]]:
        """(row | None, how, candidates). Employer AND role, or the exact address, or a reference number. A mail that names no role is matched on the
        employer only when exactly one distinct role of that employer is in the tracker. Anything else stays ambiguous: a session decides (`judge`)."""
        sender = addr_of(m.get("from", ""))
        sent = kind == "sent_application"
        peers = {a for a in (addrs_in(m.get("to", "")) if sent else [sender]) if personal_address(a)}
        subject = m.get("subject", "") or ""
        body = (m.get("body_text") or m.get("snippet") or "")
        hay_emp = (f"{subject}\n{sender.split('@')[-1].replace('.', ' ').replace('-', ' ')}" if sent
                   else f"{subject}\n{body[:1500]}\n{parseaddr(m.get('from', ''))[0]}\n{sender.split('@')[-1].replace('.', ' ').replace('-', ' ')}")
        if sent:
            hay_emp += "\n" + " ".join(a.split("@")[-1].replace(".", " ").replace("-", " ") for a in peers)
        hay_role = f"{subject}\n{body[:1500]}"
        ew, ef = set(words(hay_emp)), " ".join(words(hay_emp))
        head_txt = f"{subject} {parseaddr(m.get('from', ''))[0]} {sender.split('@')[-1].replace('.', ' ').replace('-', ' ')}" + (" " + " ".join(a.split("@")[-1].replace(".", " ").replace("-", " ") for a in peers) if sent else "")
        hw_, hf_ = set(words(head_txt)), " ".join(words(head_txt))
        rw, rf = set(words(hay_role)), " ".join(words(hay_role))
        refs_in_mail = {_norm_ref(r) for r in REF_RX.findall(f"{subject}\n{body[:2500]}")}
        scored = []
        for r in self.rows:
            by_addr = bool(r["emails"] & peers)
            disc = [t for t in r["emp"] if self.distinctive(t) and _has_word(ew, ef, t)]
            emp_ok = by_addr or bool(disc)
            emp_head = by_addr or any(_has_word(hw_, hf_, t) for t in disc)
            uniq_roles = list(dict.fromkeys(r["roles"]))
            role_hits = [t for t in uniq_roles if _has_word(rw, rf, t)]
            rscore = round(sum(self.weight(t) for t in role_hits))
            ratio = len(role_hits) / len(uniq_roles) if uniq_roles else 0.0
            ref_hit = bool(refs_in_mail & {x for x in r["refs"] if len(x) >= 5})
            if not (emp_ok or ref_hit or (len(role_hits) >= 2 and ratio >= 0.6)):
                continue
            scored.append({"ref": ref_hit, "addr": by_addr, "emp": emp_ok, "head": emp_head, "rscore": rscore, "nrole": len(role_hits), "ratio": ratio,
                           "applied": r["status"] in ("applied", "interview", "rejected"), "r": r})
        if not scored:
            return None, "no row of that employer or role in the tracker", []
        scored.sort(key=lambda x: (x["ref"], x["addr"], x["ratio"] >= 0.6 and x["nrole"] >= 2, x["ratio"], x["emp"], x["rscore"], x["applied"]), reverse=True)
        self.last_scored = scored
        cands = [x["r"] for x in scored]

        def same_post(items):
            return len({fold(x["r"]["title"]) for x in items}) == 1

        best = scored[0]
        if best["ref"]:
            return best["r"], "reference number", cands
        addr_rows = [x for x in scored if x["addr"]]
        if addr_rows:
            top = sorted(addr_rows, key=lambda x: (x["ratio"], x["rscore"]), reverse=True)
            if len(top) == 1 or top[0]["ratio"] > top[1]["ratio"] + 0.15 or same_post(top):
                return top[0]["r"], "address", cands
        # the mail repeats the row's own title: that is the strongest evidence a mail can give without an address or a number
        titled = [x for x in scored if x["nrole"] >= 2 and x["ratio"] >= 0.6]
        if titled:
            titled.sort(key=lambda x: (x["ratio"], x["emp"], x["rscore"], x["applied"]), reverse=True)
            t0 = titled[0]
            rivals = [x for x in titled[1:] if x["ratio"] >= t0["ratio"] - 0.15]
            if not rivals:
                return t0["r"], "employer and role" if t0["emp"] else "role words only", cands
            if same_post([t0] + rivals):
                pick = sorted([t0] + rivals, key=lambda x: (x["applied"], x["r"]["status"] != "open"), reverse=True)[0]
                return pick["r"], "employer and role (the posting is filed twice)", cands
            applied_rivals = [x for x in [t0] + rivals if x["applied"]]
            if len(applied_rivals) == 1:
                return applied_rivals[0]["r"], "employer and role (the only applied row among equals)", cands
            return None, "several rows fit the title words equally", cands
        # employer evidence only: weak
        emp_rows = [x for x in scored if x["head"]]
        if not emp_rows:
            return None, "no row of that employer in the tracker (or the employer is named only in the body)", cands
        top = sorted(emp_rows, key=lambda x: (x["rscore"], x["applied"]), reverse=True)
        t0 = top[0]
        if t0["nrole"] >= 1 and t0["rscore"] >= 8 and (len(top) == 1 or t0["rscore"] > top[1]["rscore"] + 3):
            return t0["r"], "employer and one role word", cands
        names_a_role = bool(ROLE_IN_SUBJECT.search(subject))
        if same_post(emp_rows) and len({x["r"]["id"] for x in emp_rows}) <= 2 and not (names_a_role and t0["nrole"] == 0):
            pick = sorted(emp_rows, key=lambda x: (x["applied"], x["r"]["status"] != "open"), reverse=True)[0]
            return pick["r"], "employer only (one role of this employer is in the tracker)", cands
        applied_rows = [x for x in emp_rows if x["applied"]]
        if len(applied_rows) == 1 and t0["nrole"] == 0 and not names_a_role:
            return applied_rows[0]["r"], "employer only (the mail names no role; one applied row)", cands
        return None, "the employer is in the tracker but the mail does not say which role (several rows)", cands


# ----------------------------------------------------------------------------- 3. act on a classified mail

STATUS_RANK = {"open": 0, "applied": 1, "interview": 2, "rejected": 3}
THESIS_RANK = {"lead": 0, "outreach_drafted": 1, "outreach_sent": 2, "replied": 3, "interview": 4, "accepted": 5, "declined": 5, "closed": 5}


STRONG_MATCH = ("reference number", "address", "employer and role", "employer and role (the posting is filed twice)", "employer and role (the only applied row among equals)")


# The only weak evidence that may still move a status, and only for an acknowledgement or a mail the owner sent (both are reversible facts): the employer has exactly one role in the tracker.
SAFE_WEAK = ("employer only (one role of this employer is in the tracker)",)


def may_change_status(kind: str, how: str) -> bool:
    return how in STRONG_MATCH or (kind in ("ack", "sent_application") and how in SAFE_WEAK)


def _src(day: str, kind: str, how: str = "") -> str:
    return f"gmail {day} ({kind}{', ' + how if how else ''})"


def act_job(row: dict, kind: str, day: str, how: str, dry: bool) -> tuple[str, str]:
    """Apply the policy to a job row. Returns (state, action text)."""
    cur = row["row"]["status"]
    changes: dict[str, Any] = {}
    if cur == "skip":
        return "already", f"row is 'skip' (Not for me); mail recorded, status left alone"
    if kind in ("sent_application", "ack"):
        if cur == "open":
            changes = {"status": "applied", "status_source": _src(day, kind, how)}
            if not row["row"].get("applied_at"):
                changes["applied_at"] = day
        elif row["row"].get("applied_at") is None and cur in ("applied", "interview"):
            changes = {"applied_at": day}
    elif kind == "interview":
        if cur in ("open", "applied"):
            changes = {"status": "interview", "status_source": _src(day, kind, how)}
            if not row["row"].get("applied_at"):
                changes["applied_at"] = day
        elif cur == "rejected":
            return "needs_read", "invitation arrived for a row already marked rejected: a session must read both mails"
    elif kind == "offer":
        if cur in ("open", "applied"):
            changes = {"status": "interview", "status_source": _src(day, "offer", how)}
            if not row["row"].get("applied_at"):
                changes["applied_at"] = day
    elif kind == "rejection":
        if cur != "rejected":
            changes = {"status": "rejected", "status_source": _src(day, kind, how), "closed_at": day}
    elif kind in ("info_request", "reply", "other_job"):
        return "acted", "needs the owner (see ACT NOW)" if kind == "info_request" else "recorded"
    if not changes:
        return "already", f"row already {cur}"
    if not dry:
        db.update_job(row["id"], changes, source="automation")
    return "applied", ", ".join(f"{k}={v}" for k, v in changes.items() if k in ("status", "applied_at", "closed_at"))


def act_thesis(row: dict, kind: str, day: str, direction: str, dry: bool) -> tuple[str, str]:
    cur = row["row"]["status"]
    target = None
    if direction == "sent":
        target = "outreach_sent" if THESIS_RANK.get(cur, 0) < THESIS_RANK["outreach_sent"] else None
    elif kind == "rejection":
        target = "declined" if cur not in ("declined", "closed", "accepted") else None
    elif kind in ("interview", "offer"):
        target = "interview" if THESIS_RANK.get(cur, 0) < THESIS_RANK["interview"] else None
    elif kind in ("ack", "reply", "info_request", "other_job"):
        target = "replied" if THESIS_RANK.get(cur, 0) < THESIS_RANK["replied"] else None
    if not target:
        return "already", f"thesis row already {cur}"
    ch: dict[str, Any] = {"status": target}
    if target == "outreach_sent":
        ch["outreach_sent_at"] = day
    if target in ("replied", "interview", "declined"):
        ch["replied_at"] = day
    if not dry:
        db.update_thesis(row["id"], ch, source="automation")
    return "applied", ", ".join(f"{k}={v}" for k, v in ch.items())


# ----------------------------------------------------------------------------- 4. alert harvest

STUDENT_RX = re.compile(r"werkstudent|working student|student(?:ische|ischer)?\b|praktik|intern\b|internship|masterarbeit|abschlussarbeit|thesis|trainee|hiwi|hilfskraft|"
                        r"\bshk\b|\bwhk\b|stage\b|stagiaire|pflichtpraktikum|diplomarbeit|duales studium|dual student", re.I)
NOISE_LINE = re.compile(r"actively hiring|easy apply|applicant|alumni|connection|early applicant|promoted|new$|be an early|for students|view job|see all jobs|manage alerts|"
                        r"this company|\bremote\b$|^\W*$|unsubscribe|^-+$|^=+$|^~+$|reactivated|reposted|just now|ago$|top applicant|prefer", re.I)


def _lines(text: str) -> list[str]:
    return [" ".join(x.split()) for x in re.sub(r"&amp;", "&", text or "").splitlines()]


def parse_linkedin(m: dict) -> list[dict]:
    """Blocks of: title / company / location / [noise] / 'View job: .../jobs/view/<id>/?...'. One mail may carry several sections."""
    out, seen = [], set()
    lines = _lines(m.get("body_text", ""))
    for i, ln in enumerate(lines):
        mm = re.search(r"linkedin\.com/(?:comm/)?jobs/view/(\d{6,})", ln)
        if not mm or mm.group(1) in seen:
            continue
        jid = mm.group(1)
        seen.add(jid)
        prev: list[str] = []
        k, steps = i - 1, 0
        while k >= 0 and len(prev) < 3 and steps < 10:
            if re.match(r"^-{5,}", lines[k]) or re.search(r"https?://", lines[k]):
                break
            if lines[k] and not NOISE_LINE.search(lines[k]):
                prev.append(lines[k])
            k, steps = k - 1, steps + 1
        prev.reverse()
        if not prev:
            continue
        title = prev[0]
        company = prev[1] if len(prev) > 1 else ""
        location = prev[2] if len(prev) > 2 else ""
        out.append({"source": "linkedin_alert", "key": jid, "url": f"https://de.linkedin.com/jobs/view/{jid}", "title": title, "employer": company, "location": location})
    return out


def parse_xing(m: dict) -> list[dict]:
    out = []
    lines = [x for x in _lines(m.get("body_text", ""))]
    for i, ln in enumerate(lines):
        mm = re.match(r"=>\s*(https?://www\.xing\.com/m/([\w-]+))", ln)
        if not mm:
            continue
        title = ""
        k = i - 1
        while k >= 0 and not title:
            if lines[k] and not NOISE_LINE.search(lines[k]) and not lines[k].startswith("="):
                title = lines[k]
            k -= 1
        nxt = [x for x in lines[i + 1: i + 5] if x and not NOISE_LINE.search(x) and not x.startswith("-")]
        out.append({"source": "xing_alert", "key": mm.group(2), "token": mm.group(2), "redirect": mm.group(1), "title": title, "employer": nxt[0] if nxt else "",
                    "location": nxt[1] if len(nxt) > 1 else ""})
    return out


def parse_generic(m: dict) -> list[dict]:
    """jobvector / employer career alerts: a title line, an employer line, a place line; a posting address only when the mail carries one."""
    out = []
    lines = _lines(m.get("body_text", ""))
    for i, ln in enumerate(lines):
        if STUDENT_RX.search(ln) and 12 < len(ln) < 160 and not ln.startswith("http") and "unsubscribe" not in ln.lower():
            url = ""
            for x in lines[i + 1: i + 6]:
                mu = re.search(r"https?://\S+", x)
                if mu and re.search(r"/job|/stelle|/position|careers|karriere|jobs\.", mu.group(0), re.I):
                    url = mu.group(0).strip("[]()<>,.")
                    break
            nxt = [x for x in lines[i + 1: i + 4] if x and not x.startswith("http") and not NOISE_LINE.search(x)]
            out.append({"source": "mail_alert", "key": re.sub(r"\W+", "-", fold(ln))[:40], "url": url, "title": ln, "employer": nxt[0] if nxt else "", "location": nxt[-1] if len(nxt) > 1 else ""})
    return out


def parse_alert(m: dict) -> list[dict]:
    f = m.get("from", "").lower()
    if "linkedin.com" in f:
        return parse_linkedin(m)
    if "xing.com" in f:
        return parse_xing(m)
    return parse_generic(m)


XING_CACHE = MAIL / "xing_resolved.json"


def resolve_many(tokens: list[str]) -> dict[str, str]:
    """token -> the posting's own address ('' when the redirect did not land on one). Each token is tried once and remembered."""
    from concurrent.futures import ThreadPoolExecutor
    cache = json.loads(XING_CACHE.read_text(encoding="utf-8")) if XING_CACHE.exists() else {}
    todo = [t for t in dict.fromkeys(tokens) if t not in cache]
    if todo:
        with ThreadPoolExecutor(8) as ex:
            for t, u in zip(todo, ex.map(lambda x: resolve_xing(x) or "", todo)):
                cache[t] = u
        MAIL.mkdir(parents=True, exist_ok=True)
        XING_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
    return cache


def resolve_xing(token: str) -> str | None:
    """Follow the mail redirect once, with a plain HTTP request; the posting's own address is returned only if it landed on one."""
    import requests
    try:
        r = requests.get(f"https://www.xing.com/m/{token}", timeout=12, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36"})
    except Exception:  # noqa: BLE001
        return None
    final = r.url.split("?")[0].split("#")[0]
    return final if re.search(r"xing\.com/jobs/[\w-]+-\d{6,}$", final) else None


def tracked_index() -> tuple[set[str], set[str], set[tuple[str, str]]]:
    import intake
    urls, wids = intake.existing_index()
    pairs = set()
    for j in db.list_jobs():
        pairs.add((fold(j["employer"] or ""), " ".join(words(j["title"] or ""))))
    for t in db.list_thesis():
        pairs.add((fold(t["institution"] or ""), " ".join(words(t["title"] or ""))))
    return urls, wids, pairs


def file_candidates(cands: list[dict], day_of: dict[str, str], dry: bool) -> dict:
    """Filed as unscored stubs through intake.make_stub; the pipeline's intake pass fetches the full JD and analyses it."""
    import intake
    res = {"seen": len(cands), "filed": [], "known": 0, "not_student_level": 0, "pending_url": 0}
    urls, wids, pairs = tracked_index()
    pending = json.loads(PENDING_PATH.read_text(encoding="utf-8")) if PENDING_PATH.exists() else {}
    batch_seen: set[str] = set()
    todo_tokens = [c["token"] for c in cands if c.get("token") and STUDENT_RX.search(c.get("title") or "")
                   and f"mail-{c['source']}-{c['key']}" not in wids and (fold(c.get("employer") or ""), " ".join(words(c.get("title") or ""))) not in pairs]
    resolved = resolve_many(todo_tokens) if todo_tokens else {}
    for c in cands:
        title = " ".join((c.get("title") or "").split())
        if not title or not STUDENT_RX.search(title):
            res["not_student_level"] += 1
            continue
        wid = f"mail-{c['source']}-{c['key']}"
        if wid in wids or wid in batch_seen:
            res["known"] += 1
            continue
        pair = (fold(c.get("employer") or ""), " ".join(words(title)))
        if pair in pairs and pair[0]:
            res["known"] += 1
            continue
        url = c.get("url") or ""
        if not url and c.get("token"):
            url = resolved.get(c["token"], "")
            if not url:
                pending[wid] = {**c, "first_seen": day_of.get(wid, date.today().isoformat())}
                res["pending_url"] += 1
                continue
        if not url:
            res["no_address"] = res.get("no_address", 0) + 1       # an alert that lists a role but no link to it (jobvector): nothing to file under THE LINK RULE
            continue
        if intake.norm_url(url) in urls:
            res["known"] += 1
            continue
        batch_seen.add(wid)
        urls.add(intake.norm_url(url))
        pending.pop(wid, None)
        low = fold(title)
        kind = "thesis" if re.search(r"masterarbeit|abschlussarbeit|thesis|diplomarbeit", low) else "job"
        item = {"id": wid, "url": url, "title": title, "employer": c.get("employer") or "", "location": c.get("location") or "", "source": c["source"], "origin": "mail",
                "first_seen": day_of.get(wid, date.today().isoformat()), "kind": kind}
        if not dry:
            ref = intake.make_stub(item, None)
            if ref:
                res["filed"].append(ref)
        else:
            res["filed"].append(wid)
    if not dry:
        MAIL.mkdir(parents=True, exist_ok=True)
        PENDING_PATH.write_text(json.dumps(pending, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


# ----------------------------------------------------------------------------- 5. fetch the mailbox

def fetch_oauth(days: int) -> list[dict]:
    import gmail_client as g
    seen: dict[str, dict] = {}
    for q in REPLY_QUERIES + ALERT_QUERIES:
        for m in g.fetch_messages(f"{q} newer_than:{days}d", 400):
            seen[m["id"]] = m
    return list(seen.values())


def load_state() -> dict:
    return json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}


def save_state(st: dict) -> None:
    MAIL.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def window_days(st: dict) -> int:
    last = st.get("last_ok")
    if not last:
        return FIRST_SYNC_DAYS
    try:
        gap = (date.today() - date.fromisoformat(last[:10])).days
    except ValueError:
        return FIRST_SYNC_DAYS
    return min(FIRST_SYNC_DAYS, max(5, gap + 3))


# ----------------------------------------------------------------------------- 6. run

def process(msgs: list[dict], dry: bool, reprocess: bool) -> dict:
    db.init_db()
    idx = Index()
    res: dict[str, Any] = {"messages": len(msgs), "events": [], "alerts": 0, "alert_candidates": [], "dropped_noise": 0, "death": []}
    day_of: dict[str, str] = {}
    cands: list[dict] = []
    for m in sorted(msgs, key=lambda x: int(x.get("internal_ms") or 0)):
        c = classify(m)
        if c is None:
            res["dropped_noise"] += 1
            continue
        kind, conf, why = c
        day = mail_day(m)
        if kind == "alert":
            res["alerts"] += 1
            if (date.today() - date.fromisoformat(day)).days <= 7 and re.search(r"turned off|has been (?:turned off|paused|disabled)|alert (?:has )?expired|deactivated", m.get("subject", ""), re.I):
                res["death"].append(one_line(m.get("subject", ""), 120))
            for it in parse_alert(m):
                wid = f"mail-{it['source']}-{it['key']}"
                day_of.setdefault(wid, day)
                cands.append(it)
            continue
        old = db.mail_event(m["id"])
        if old and (old.get("judged_by") or (not reprocess and old["state"] not in ("new",))):
            continue
        direction = "sent" if kind == "sent_application" else "received"
        row, how, near = idx.match(m, kind)
        ev: dict[str, Any] = {"msg_id": m["id"], "thread_id": m.get("thread_id"), "direction": direction, "kind": kind, "confidence": conf,
                              "sender": addr_of(m.get("from", "")), "recipient": ", ".join(addrs_in(m.get("to", ""))[:3]), "subject": one_line(m.get("subject", ""), 200),
                              "mail_date": day, "employer_hint": one_line(parseaddr(m.get("from", ""))[0], 80)}
        state, action = "unmatched", how
        if row is not None and conf == "low":
            state, action = "needs_read", f"{how}; low-confidence reading ({why})"
            ev["job_id" if row["kind"] == "job" else "thesis_id"] = row["id"]
        elif row is not None:
            ev["job_id" if row["kind"] == "job" else "thesis_id"] = row["id"]
            if kind in ("rejection", "interview", "ack", "sent_application") and not may_change_status(kind, how):
                state, action = "needs_read", f"{how}: a weak match, so a session confirms it before the status moves"
            elif kind in ("other_job", "offer"):
                state, action = "needs_read", f"{how}; " + ("an offer: a session reads it and decides" if kind == "offer" else "no clear signal in the mail")
            elif row["kind"] == "job":
                state, action = act_job(row, kind, day, how, dry)
            else:
                state, action = act_thesis(row, kind, day, direction, dry)
            if state in ("applied", "already") and kind in ("interview", "offer", "info_request"):
                state = "acted" if state == "already" else state
        elif conf == "low" or kind == "other_job":
            state, action = "needs_read", f"{how}; low-confidence reading ({why})"
        ev.update({"state": state, "action": action[:300], "note": ", ".join(f"{r['id']}" for r in near[:4])[:300] if row is None else None})
        if not dry:
            db.save_mail_event(ev)
        res["events"].append(ev)
        if row is not None:
            idx = Index() if state == "applied" else idx            # statuses moved: later mails see the new state
    res["filed"] = file_candidates(cands, day_of, dry)
    return res


def run(days: int | None, snapshot: str | None, dry: bool, reprocess: bool) -> dict:
    st = load_state()
    source, err, msgs = "oauth", None, []
    days = days or window_days(st)
    if snapshot:
        raw = json.loads(Path(snapshot).read_text(encoding="utf-8"))
        msgs, source = raw["messages"] if isinstance(raw, dict) else raw, "snapshot"
    else:
        try:
            msgs = fetch_oauth(days)
        except Exception as exc:  # noqa: BLE001  (GmailAuthError, FileNotFoundError, network)
            err = f"{type(exc).__name__}: {str(exc)[:200]}"
    if err:
        st.update({"last_attempt": datetime.now().isoformat(timespec="seconds"), "last_error": err, "source": source})
        save_state(st)
        print(f"mail sync could not read Gmail: {err}\n  fix: python scripts/gmail_client.py auth   (or --snapshot a file a Claude session wrote from the Gmail connector)", file=sys.stderr)
        return {"ok": False, "error": err}
    res = process(msgs, dry, reprocess)
    res["ok"], res["source"], res["days"] = True, source, days
    if not dry:
        now = datetime.now().isoformat(timespec="seconds")
        k = {}
        for e in res["events"]:
            k[e["kind"]] = k.get(e["kind"], 0) + 1
        st.update({"last_ok": now, "last_attempt": now, "last_error": None, "source": source, "window_days": days, "messages": res["messages"], "alerts": res["alerts"],
                   "events_by_kind": k, "filed": len(res["filed"]["filed"]), "pending_url": res["filed"]["pending_url"], "alert_death": res["death"]})
        save_state(st)
        write_queue()
    return res


# ----------------------------------------------------------------------------- 7. the queue and the report

def queue() -> dict:
    ev = db.list_mail_events()
    today = date.today()
    recent = (today - timedelta(days=RESOLVE_PENDING_DAYS)).isoformat()

    def line(e: dict) -> dict:
        row = (db.get_job(e["job_id"]) if e.get("job_id") else None) or (db.get_thesis(e["thesis_id"]) if e.get("thesis_id") else None) or {}
        return {"msg_id": e["msg_id"], "date": e["mail_date"], "kind": e["kind"], "from": e["employer_hint"] or e["sender"], "subject": e["subject"], "ref": e.get("job_id") or e.get("thesis_id"),
                "role": row.get("title"), "employer": row.get("employer") or row.get("institution"), "state": e["state"], "action": e["action"], "confidence": e["confidence"]}
    act_now = [line(e) for e in ev if e["kind"] in ("interview", "offer", "info_request") and e["mail_date"] >= recent and e["state"] != "dismissed"]
    unresolved = [line(e) for e in ev if e["state"] in ("unmatched", "needs_read") and e["mail_date"] >= (today - timedelta(days=30)).isoformat()]
    q = {"generated": datetime.now().isoformat(timespec="seconds"), "state": load_state(), "act_now": act_now, "unresolved": unresolved,
         "rejections": [line(e) for e in ev if e["kind"] == "rejection" and e["state"] in ("applied", "already")][:30],
         "confirmed": [line(e) for e in ev if e["kind"] in ("sent_application", "ack") and e["state"] in ("applied", "already")][:30],
         "pending_candidates": list((json.loads(PENDING_PATH.read_text(encoding="utf-8")) if PENDING_PATH.exists() else {}).values())[:30],
         "counts": {k: sum(1 for e in ev if e["kind"] == k) for k in db.MAIL_KINDS}}
    return q


def write_queue() -> Path:
    q = queue()
    MAIL.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
    DIGESTS.mkdir(exist_ok=True)
    p = DIGESTS / f"mail-{date.today().isoformat()}.md"
    st = q["state"]
    L = [f"# Mail sync — {date.today().isoformat()}", "",
         f"Last read: {st.get('last_ok') or 'never'} via {st.get('source') or '-'}" + (f" — **last attempt failed:** {st.get('last_error')}" if st.get("last_error") else ""), ""]
    if st.get("alert_death"):
        L += ["## Job alerts that stopped", ""] + [f"- {x}" for x in st["alert_death"]] + [""]
    L += ["## ACT NOW (interviews, offers, requests from employers)", ""]
    L += [f"- {e['date']} **{e['kind']}** — {e['employer'] or e['from']}: {e['role'] or e['subject']} ({e['ref'] or 'unmatched'}) — {e['action']}" for e in q["act_now"]] or ["- none"]
    L += ["", "## Mail I could not match to a row, or could not read with confidence (a Claude session reads these: `mail_sync.py show <id>`, then `judge`)", ""]
    L += [f"- {e['date']} {e['kind']} from {e['from']}: {e['subject']} — {e['action']} [{e['msg_id']}]" for e in q["unresolved"]] or ["- none"]
    L += ["", "## Rejections recorded from mail", ""] + ([f"- {e['date']} {e['employer']}: {e['role']} ({e['ref']}) — {e['action']}" for e in q["rejections"]] or ["- none"])
    L += ["", "## Applications confirmed by mail (sent by the owner, or acknowledged by the employer)", ""] + ([f"- {e['date']} {e['employer']}: {e['role']} ({e['ref']}) — {e['kind']}: {e['action']}" for e in q["confirmed"]] or ["- none"])
    L += ["", f"## New postings from alert mail", "", f"- alert mails read: {st.get('alerts', 0)}; filed as unscored stubs this run: {st.get('filed', 0)}; waiting for a posting address: {st.get('pending_url', 0)}", ""]
    p.write_text("\n".join(L), encoding="utf-8")
    return p


# ----------------------------------------------------------------------------- 8. judge (the Claude session's decision)

def cached(msg_id: str) -> dict | None:
    f = MAIL / "msg" / f"{msg_id}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def judge(msg_id: str, kind: str, job: str | None, thesis: str | None, note: str | None) -> dict:
    """A Claude session read the whole mail and decided. Applies the same status policy as the script; the decision is recorded as judged_by=claude."""
    if kind not in db.MAIL_KINDS:
        raise SystemExit(f"kind must be one of {db.MAIL_KINDS}")
    e = db.mail_event(msg_id)
    m = cached(msg_id) or {}
    ev = e or {"msg_id": msg_id, "thread_id": m.get("thread_id"), "direction": "sent" if kind == "sent_application" else "received", "sender": addr_of(m.get("from", "")),
               "recipient": ", ".join(addrs_in(m.get("to", ""))[:3]), "subject": one_line(m.get("subject", ""), 200), "mail_date": mail_day(m) if m else date.today().isoformat(),
               "employer_hint": one_line(parseaddr(m.get("from", ""))[0], 80)}
    ev = dict(ev)
    ev.update({"kind": kind, "confidence": "high", "judged_by": "claude", "note": note})
    idx = Index()
    target = next((r for r in idx.rows if r["id"] == (job or thesis)), None) if (job or thesis) else None
    if (job or thesis) and target is None:
        raise SystemExit(f"no such row: {job or thesis}")
    if target:
        ev["job_id" if target["kind"] == "job" else "thesis_id"] = target["id"]
        state, action = (act_job(target, kind, ev["mail_date"], "judged by a session", False) if target["kind"] == "job"
                         else act_thesis(target, kind, ev["mail_date"], ev["direction"], False))
    else:
        state, action = ("dismissed", "not about a tracked role") if kind in ("other_job", "reply") else ("unmatched", "no row given")
    ev.update({"state": state, "action": action[:300]})
    out = db.save_mail_event(ev)
    write_queue()
    return out


# ----------------------------------------------------------------------------- CLI

def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--days", type=int)
    r.add_argument("--snapshot")
    r.add_argument("--dry", action="store_true")
    r.add_argument("--reprocess", action="store_true")
    r.add_argument("--reset-open", action="store_true", help="forget events still unmatched / needs_read / acted before reading (a changed classifier re-reads them)")
    sub.add_parser("status")
    sub.add_parser("queue")
    x = sub.add_parser("explain")
    x.add_argument("msg_id")
    s = sub.add_parser("show")
    s.add_argument("msg_id")
    j = sub.add_parser("judge")
    j.add_argument("msg_id")
    j.add_argument("--kind", required=True)
    j.add_argument("--job")
    j.add_argument("--thesis")
    j.add_argument("--note")
    a = ap.parse_args()
    if a.cmd == "run":
        if a.reset_open and not a.dry:
            print(f"forgot {db.delete_mail_events(('unmatched', 'needs_read', 'acted', 'new'))} open mail events")
        res = run(a.days, a.snapshot, a.dry, a.reprocess)
        if not res.get("ok"):
            return 2
        k: dict[str, int] = {}
        for e in res["events"]:
            k[e["kind"]] = k.get(e["kind"], 0) + 1
        print(f"read {res['messages']} messages via {res['source']} (last {res['days']} days): {res['alerts']} alert mails, {res['dropped_noise']} not job mail, events {k}")
        by_state: dict[str, int] = {}
        for e in res["events"]:
            by_state[e["state"]] = by_state.get(e["state"], 0) + 1
        print(f"  states: {by_state}")
        f = res["filed"]
        print(f"  alert postings: {f['seen']} seen, {len(f['filed'])} filed as stubs, {f['known']} already tracked, {f['not_student_level']} not student-level, {f['pending_url']} Xing links waiting for their posting address, {f.get('no_address', 0)} listed without a link")
        for e in res["events"]:
            if e["state"] in ("applied", "unmatched", "needs_read") or e["kind"] in ("interview", "offer", "info_request"):
                print(f"  [{e['state']}] {e['mail_date']} {e['kind']:<16} {e['employer_hint'][:28]:<28} | {e['subject'][:60]} -> {e.get('job_id') or e.get('thesis_id') or '-'}: {(e['action'] or '')[:80]}")
        if res["death"]:
            print("  ALERTS STOPPED:", res["death"])
        return 0
    if a.cmd == "status":
        print(json.dumps(load_state(), ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "queue":
        p = write_queue()
        print(p.read_text(encoding="utf-8"))
        return 0
    if a.cmd == "explain":
        m = cached(a.msg_id)
        if not m:
            print("not in the cache")
            return 1
        c = classify(m)
        print(m["subject"])
        print("classified:", c)
        idx = Index()
        row, how, _ = idx.match(m, c[0] if c else "reply")
        print(f"match: {row['id'] if row else None} - {how}")
        for x in getattr(idx, "last_scored", [])[:6]:
            print(f"  {x['r']['id'][:60]:<60} emp={x['emp']} addr={x['addr']} role={x['rscore']} ({x['nrole']}) status={x['r']['status']} emp_tokens={x['r']['emp']} roles={x['r']['roles'][:6]}")
        return 0
    if a.cmd == "show":
        m = cached(a.msg_id)
        if not m:
            print("not in the cache; read it from Gmail first")
            return 1
        print(f"From: {m['from']}\nTo: {m['to']}\nDate: {m['date']}\nSubject: {m['subject']}\n\n{m['body_text']}")
        return 0
    if a.cmd == "judge":
        print(json.dumps(judge(a.msg_id, a.kind, a.job, a.thesis, a.note), ensure_ascii=False, indent=1))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

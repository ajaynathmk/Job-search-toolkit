#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/consistency_check.py
=============================

Structural/consistency checks that complement `aicheck.py`. `aicheck.py` reads
text content only — it has nothing to say about document *structure*, or about
whether two files that are supposed to agree (a CV and its own cover letter)
actually do. This script exists because of a real bug found on 2026-09-25: a
language-detection heuristic used elsewhere (`"## Profil" in content`) matched
even English files, since "Profil" is a literal substring of "Profile". That
silently rebuilt 26 English-language packages with German section headers,
stranding the original English Profile paragraph as an orphaned fragment with
a leftover "e" — the tail of "Profile" left behind by the mismatched split.
Nothing in the existing gate would have caught it; it was only found by
visually reading a rendered page. These checks make that class of bug
mechanical instead of relying on a human noticing.

Checks:
  1. header_structure      — cv.md's `## ` headers are exactly the canonical
                            German set or English set, never mixed, never
                            duplicated.
  2. orphan_stray_line     — the paragraph directly under the Profile/Profil
                            heading isn't a suspiciously short fragment (the
                            signature of a botched heading-boundary split).
  3. cv_letter_language    — if cover-letter.md exists, its salutation/closing
                            language must match cv.md's own language.
  4. no_cut_completeness   — every real bullet in the master CV
                            (profile/master-cv-<language>.md,
                            matched to cv.md's detected language) must survive
                            into cv.md, either verbatim or as a genuine reword
                            — applications.md's content-regulation rule (was
                            called "the no-cut rule" before 2026-09-27)
                            explicitly PERMITS "rewording a real bullet in the
                            posting's vocabulary", so this check no longer
                            demands a byte-for-byte match: a bullet with no
                            close paraphrase anywhere in cv.md (word-overlap
                            below REWORD_MATCH_THRESHOLD) is flagged as
                            actually missing, not merely reworded. Relaxed to
                            an informational, non-blocking finding when the
                            folder's match-report.md carries a valid
                            content-regulation exemption tag (see
                            EXEMPTION_TAG_RE below and applications.md's
                            27 Sep 2026 "exclusion 1", or its 28 Sep 2026
                            "exclusion 2" for a non-computational role's
                            trimmed Forschungsprojekt bullets).
  5. locked_term_dropped   — the owner's rule: a tool name, standard, gene/variant
                            id, or precise figure that cannot be paraphrased
                            (data/locked_terms.json — "ALDY should be ALDY
                            only") must appear verbatim in whichever cv.md
                            bullet matches the master bullet it came from,
                            even when that bullet has been legitimately
                            reworded. A hard stop, same severity as a cut —
                            subject to the same exemption as #4.
  6. encoding_corruption   — no Unicode replacement character (U+FFFD) in
                            either file.
  7. profile_date_leak     — no date/duration marker inside the Profile
                            paragraph (the owner's 25 Sep 2026 rule 3).
  8. letter_metric_leak    — none of the CV's own multi-digit numbers or
                            percentages are restated in the cover letter
                            (applications.md's cover-letter rule 1).

Usage:
    python scripts/consistency_check.py <application-folder>
    python scripts/consistency_check.py <application-folder> --json

Exit code is the total finding count (0 = clean), so ship-package.sh can gate
on it directly — same convention as aicheck.py.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCKED_TERMS_PATH = config.profile_path("locked_terms.json")

# A bullet with no verbatim survivor in cv.md is still fine if a paraphrase of
# it scores at least this well on word-overlap (Jaccard over lowercased word
# sets) — applications.md explicitly permits rewording a bullet in the
# posting's vocabulary. Below this, treat it as genuinely missing rather than
# reworded; picked empirically (a same-topic reworded bullet keeps most of its
# nouns, a bullet about something else shares almost none).
REWORD_MATCH_THRESHOLD = 0.35

_LANGS = config.resource("cv_headers.json", {}).get("languages", {})
_EXTRA = (config.get().profile.get("cv") or {}).get("headers") or {}


def master_path(lang: str) -> Path:
    """The user's master CV in one language: profile/master-cv-<code>.md (written during onboarding, never published)."""
    return config.profile_path(f"master-cv-{lang}.md")


def headers_of(lang: str) -> set[str]:
    return set(_LANGS.get(lang, {}).get("headers", [])) | set(_EXTRA.get(lang, []))


PROFILE_HEADS = "|".join(re.escape(v["profile"]) for v in _LANGS.values())
SALUTATION = {k: re.compile(v["salutation"]) for k, v in _LANGS.items()}
CLOSING = {k: re.compile(v["closing"]) for k, v in _LANGS.items()}

DATE_MARKERS = re.compile(
    r"\b(\d+\s*Monat[e]?|Monate lang|seit Okt|Oktober 20\d\d|sechsjährig|"
    r"sechs Jahre|Sechs Jahre|\d+\s*months?\b|months at|since Oct|"
    r"Jun 20\d\d|Jan 20\d\d|Aug 20\d\d)\b",
    re.IGNORECASE,
)

# rules/applications.md's content-regulation exemption (27 Sep 2026, exclusion
# 1): a package may only relax no_cut_completeness/locked_term_dropped if its
# own match-report.md carries this exact tag AND the value actually quotes
# the posting — an unquoted claim ("kept it short per the posting") is not
# honoured, on purpose: the bar for cutting real content is a real sentence
# from the real posting, never an assertion.
EXEMPTION_TAG_RE = re.compile(r"\*\*Content-regulation exemption:\*\*\s*(.+)")
QUOTE_CHARS = re.compile(r'["„“”«»]')


@dataclass
class Finding:
    file: str
    rule: str
    detail: str


def _profile_block(content: str) -> str | None:
    m = re.search(rf"## (?:{PROFILE_HEADS})\n\n(.+?)\n\n##", content, re.DOTALL)
    return m.group(1).strip() if m else None


def _cv_lang(content: str) -> str | None:
    """Best-effort language detection, deliberately decoupled from a clean
    header-set match. A real defect found 2026-09-27: this used to return
    None the moment header_structure would ALSO flag the file (e.g. a whole
    section like Clinical Internships cut) — which silently skipped
    no_cut_completeness and locked_term_dropped for exactly the CVs that were
    already known to be malformed and most needed them. header_structure
    still reports the header mismatch on its own; this function now falls
    back to whichever canonical set the file's headers overlap with more, so
    the no-cut/locked-term checks keep running against a broken header set
    instead of going dark on it."""
    headers = set(re.findall(r"^## (.+)$", content, re.MULTILINE))
    best, best_n = None, 0
    for code in _LANGS:
        n = len(headers & headers_of(code))
        if n > best_n:
            best, best_n = code, n
    return best     # None when the headings are not recognisably any language: nothing safe to compare against


def _bullets_of(text: str) -> set[str]:
    return {l.strip() for l in text.split("\n") if l.strip().startswith("- ")}


def _master_bullets(lang: str) -> set[str]:
    path = master_path(lang)
    if not path.exists():
        return set()
    return _bullets_of(path.read_text(encoding="utf-8"))


_WORD_RE = re.compile(r"[\w-]+", re.UNICODE)


def _word_set(line: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(line)}


def _best_match(bullet: str, candidates: set[str]) -> tuple[str | None, float]:
    """The candidate cv.md bullet with the highest word-overlap against a
    missing master bullet — the closest thing to "where did this get
    reworded to, if anywhere." Jaccard over lowercased word sets: cheap,
    order-independent (reordering a clause shouldn't tank the score), and
    good enough to tell "the same bullet, reworded" apart from "an unrelated
    bullet that happens to share a stopword or two.\""""
    b_words = _word_set(bullet)
    if not b_words:
        return None, 0.0
    best, best_score = None, 0.0
    for c in candidates:
        c_words = _word_set(c)
        if not c_words:
            continue
        overlap = len(b_words & c_words) / len(b_words | c_words)
        if overlap > best_score:
            best, best_score = c, overlap
    return best, best_score


def _load_locked_terms() -> list[str]:
    if not LOCKED_TERMS_PATH.exists():
        return []
    return json.loads(LOCKED_TERMS_PATH.read_text(encoding="utf-8"))


def _locked_terms_in(text: str, locked_terms: list[str]) -> set[str]:
    """Exact, word-boundary matches only — a locked term is either present
    unchanged or it isn't; a substring hit inside an unrelated longer word
    doesn't count (rules out e.g. a short acronym matching inside a normal
    word by accident)."""
    found = set()
    for term in locked_terms:
        pattern = r"(?<!\w)" + re.escape(term) + r"(?!\w)"
        if re.search(pattern, text):
            found.add(term)
    return found


def _read_exemption(folder: Path) -> str | None:
    """Returns the quoted clause if folder/match-report.md carries a valid
    content-regulation exemption tag, else None. A tag with no quote inside
    it is deliberately treated the same as no tag at all (see the module-level
    comment on EXEMPTION_TAG_RE)."""
    report_path = folder / "match-report.md"
    if not report_path.exists():
        return None
    text = report_path.read_text(encoding="utf-8")
    m = EXEMPTION_TAG_RE.search(text)
    if not m:
        return None
    value = m.group(1).strip()
    if not QUOTE_CHARS.search(value):
        return None
    return value


def check_folder(folder: Path) -> tuple[list[Finding], list[Finding]]:
    """Returns (findings, exempted). `findings` is what ship-package.sh gates
    on (len() is the exit code, same convention as before). `exempted` holds
    no_cut_completeness/locked_term_dropped hits that would otherwise be
    findings, but the folder's match-report.md carries a valid
    content-regulation exemption tag (rules/applications.md's exclusion 1) —
    still printed, for visibility, but never blocking."""
    findings: list[Finding] = []
    exempted: list[Finding] = []
    cv_path = folder / "cv.md"
    letter_path = folder / "cover-letter.md"

    if not cv_path.exists():
        return findings, exempted  # nothing to check yet

    cv_text = cv_path.read_text(encoding="utf-8")
    cv_name = str(cv_path.relative_to(REPO_ROOT))
    exemption = _read_exemption(folder)

    # 1. header_structure. A duplicate heading is corruption (the 25 Sep 2026
    # language-mismatch bug this whole script was built to catch) and is never
    # exemptable. A header set that's a clean SUBSET of one canonical
    # language's headers (nothing extra, nothing from the other language,
    # just fewer sections) is exactly what an authorized page-limit cut looks
    # like — e.g. dropping the whole Clinical Internships section — so that
    # case is exempted the same way a missing bullet is, never a mixed or
    # duplicated set.
    headers = re.findall(r"^## (.+)$", cv_text, re.MULTILINE)
    header_set = set(headers)
    if len(headers) != len(header_set):
        findings.append(Finding(cv_name, "header_structure", "duplicate section heading"))
    else:
        lang_ = _cv_lang(cv_text)
        allowed = headers_of(lang_) if lang_ else set()
        extra_h = sorted(header_set - allowed)
        if lang_ is None or extra_h:
            detail = (f"headings are not a clean set of one language's (resources/cv_headers.json): {sorted(header_set)}" if lang_ is None
                      else f"headings from outside the {lang_} set (a mixed or misspelt heading): {extra_h}")
            findings.append(Finding(cv_name, "header_structure", detail))
        elif _LANGS[lang_]["profile"] not in header_set and not exemption:
            findings.append(Finding(cv_name, "header_structure", f"no '{_LANGS[lang_]['profile']}' section"))

    cv_lang = _cv_lang(cv_text)

    # 2. orphan_stray_line
    profile = _profile_block(cv_text)
    if profile is not None and len(profile) < 30:
        findings.append(Finding(cv_name, "orphan_stray_line",
                                 f"Profile paragraph is suspiciously short ({len(profile)} chars): {profile!r}"))

    # 5. encoding_corruption (cv.md)
    if "�" in cv_text:
        findings.append(Finding(cv_name, "encoding_corruption", "U+FFFD replacement character present"))

    # 6. profile_date_leak
    if profile and DATE_MARKERS.search(profile):
        findings.append(Finding(cv_name, "profile_date_leak",
                                 "date/duration marker inside the Profile paragraph"))

    # 4. no_cut_completeness (reword-tolerant) + 5. locked_term_dropped
    # The Profile/Profil paragraph is never part of this: master_bullets only
    # ever contains lines starting with "- " (_bullets_of), and the master's
    # own Profile section is plain prose, never a bullet — so it was never one
    # of the "every bullet must survive" items to begin with (exclusion 3,
    # rules/applications.md). This is stated here, not just there, because
    # it's the reason this loop below needs no special case for it.
    if cv_lang:
        master_bullets = _master_bullets(cv_lang)
        cv_bullets = _bullets_of(cv_text)
        locked_terms = _load_locked_terms()

        for mb in sorted(master_bullets):
            if mb in cv_bullets:
                continue  # verbatim survivor — nothing more to check on it

            match, score = _best_match(mb, cv_bullets)
            target = exempted if exemption else findings
            if score < REWORD_MATCH_THRESHOLD:
                lost_terms = _locked_terms_in(mb, locked_terms)
                extra = f" (including locked term(s) {sorted(lost_terms)})" if lost_terms else ""
                suffix = f" [EXEMPT per match-report.md: {exemption}]" if exemption else ""
                target.append(Finding(cv_name, "no_cut_completeness",
                                       f"master bullet has no reworded equivalent anywhere in "
                                       f"this CV{extra}: {mb[:120]!r}{suffix}"))
                continue

            # a plausible reword was found — every locked/invariant term the
            # master bullet carries must still appear, unchanged, in it
            for term in _locked_terms_in(mb, locked_terms):
                if term not in _locked_terms_in(match, locked_terms):
                    suffix = f" [EXEMPT per match-report.md: {exemption}]" if exemption else ""
                    target.append(Finding(cv_name, "locked_term_dropped",
                                           f"{term!r} is missing from the reworded bullet "
                                           f"(master: {mb[:90]!r}... -> cv.md: {match[:90]!r}...)"
                                           f"{suffix}"))

    if letter_path.exists():
        letter_text = letter_path.read_text(encoding="utf-8")
        letter_name = str(letter_path.relative_to(REPO_ROOT))

        if "�" in letter_text:
            findings.append(Finding(letter_name, "encoding_corruption", "U+FFFD replacement character present"))

        # 3. cv_letter_language
        hit = {k: (bool(SALUTATION[k].search(letter_text)), bool(CLOSING[k].search(letter_text))) for k in _LANGS}
        langs_open = [k for k, (o, c) in hit.items() if o]
        langs_close = [k for k, (o, c) in hit.items() if c]
        found = set(langs_open) | set(langs_close)
        letter_lang = next(iter(found)) if len(found) == 1 else None
        if cv_lang and letter_lang and cv_lang != letter_lang:
            findings.append(Finding(letter_name, "cv_letter_language",
                                     f"cv.md is {cv_lang} but cover-letter.md reads as {letter_lang}"))
        if len(found) > 1 and langs_open and langs_close and not (set(langs_open) & set(langs_close)):
            findings.append(Finding(letter_name, "cv_letter_language",
                                     f"salutation in {langs_open[0]} with a closing in {langs_close[0]}"))

        # 7. letter_metric_leak — numbers from the CV's non-profile sections
        # that show up verbatim in the letter (applications.md cover-letter rule 1)
        body = cv_text[cv_text.index(headers[0]) + len(headers[0]):] if headers else cv_text
        # drop the profile block itself from the search
        if profile:
            body = body.replace(profile, "")
        # only real metrics: thousands-separated numbers (6,000 / 2.504) and
        # percentages — a bare 4-digit number is almost always a calendar year,
        # which belongs in a letter's availability sentence and isn't a "figure"
        # in applications.md's sense
        cv_numbers = set(re.findall(r"\b\d{1,3}(?:[.,]\d{3})+\+?\b|\b\d+%\b", body))
        for num in cv_numbers:
            if num in letter_text:
                findings.append(Finding(letter_name, "letter_metric_leak",
                                         f"CV figure {num!r} restated in the cover letter"))

    return findings, exempted


def main() -> int:
    # See aicheck.py's main() for why: Windows' console defaults to cp1252,
    # which can't encode every character a real finding might quote (a German
    # umlaut, or a locked term like "p = 1.2 x 10^-190") -- force UTF-8 so a
    # real finding never crashes the gate mid-print.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--words", action="store_true", help="print the file-name words for CV and cover letter in the document language")
    args = parser.parse_args()

    if not args.folder.is_dir():
        print(f"consistency_check: {args.folder} is not a directory", file=sys.stderr)
        return 2

    if args.words:
        cv = args.folder / "cv.md"
        lang_ = _cv_lang(cv.read_text(encoding="utf-8")) if cv.exists() else None
        w = _LANGS.get(lang_ or "en", {})
        print(w.get("cv_word", "CV"), w.get("letter_word", "CoverLetter"))
        return 0

    findings, exempted = check_folder(args.folder.resolve())

    if args.json:
        print(json.dumps({"findings": [asdict(f) for f in findings],
                           "exempted": [asdict(f) for f in exempted]},
                          indent=2, ensure_ascii=False))
    else:
        for f in findings:
            print(f"{f.file}  [{f.rule}]  {f.detail}")
        print(f"\nTOTAL: {len(findings)}")
        if exempted:
            print(f"\nEXEMPTED (per match-report.md's content-regulation exemption — "
                  f"not counted above, still worth reading):")
            for f in exempted:
                print(f"{f.file}  [{f.rule}]  {f.detail}")

    return len(findings)


if __name__ == "__main__":
    sys.exit(main())

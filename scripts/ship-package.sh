#!/usr/bin/env bash
# scripts/ship-package.sh
# ========================
# The actual quality gate for one application package. Order matches the real,
# proven pipeline (aicheck -> consistency -> build -> keep_pass -> fingerprint
# -> pdf convert -> verify_pdf). Stops at the first failure. Never call build-cv.js /
# keep_pass.py directly in place of this script for something that's actually
# going to be shipped to an employer — this is what enforces the order.
#
# scripts/lang_check.py (a LanguageTool grammar pass) is deliberately NOT wired in
# here: audited against 76 real packages, about 88% of its hits were proper-noun
# and domain-jargon noise. Kept as a standalone tool for a second opinion on one
# specific letter; run it by hand.
#
# Usage: scripts/ship-package.sh <application-folder>
#   expects <folder>/cv.md and <folder>/cover-letter.md to exist.
#   writes <folder>/<CV word>_<Name>_<Employer>.docx and <folder>/<cover-letter word>_<Name>_<Employer>.docx
#   (the words follow the document language, e.g. CV/CoverLetter or Lebenslauf/Anschreiben; the owner's name is on every shipped file so the
#   owner and an employer can identify it at a glance), and, if LibreOffice is available, the matching .pdf files.

set -euo pipefail

FOLDER="${1:-}"
# The owner's name as it appears in the output file names (profile/profile.json: name, spaces become underscores).
OWNER_TAG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && python -c "import config;print(config.get().owner_name.replace(' ','_'))" 2>/dev/null || echo Candidate)"
# --cv-only (added 7 Oct 2026): for a posting that asks for a CV and no letter, or whose letter
# the owner must write personally (some postings forbid AI-written letters). Every letter step is skipped; the CV gate is unchanged.
CV_ONLY=0
[[ "${2:-}" == "--cv-only" ]] && CV_ONLY=1
if [[ -z "$FOLDER" || ! -d "$FOLDER" ]]; then
  echo "Usage: scripts/ship-package.sh <application-folder> [--cv-only]" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CV_MD="$FOLDER/cv.md"
LETTER_MD="$FOLDER/cover-letter.md"

# Folder is named <date>_<Employer>_<role-slug> (date has no underscores, so
# field 2 is always the employer).
FOLDER_NAME="$(basename "$FOLDER")"
EMPLOYER="$(echo "$FOLDER_NAME" | cut -d'_' -f2)"

# The document language follows the CV's own section headings: consistency_check.py --words decides by exact heading match, never by substring
# ("## Profil" is a substring of "## Profile", a documented bug), and prints the file-name words for "CV" and "cover letter" in that language.
read -r CV_WORD LETTER_WORD < <(python "$REPO_ROOT/scripts/consistency_check.py" "$FOLDER" --words 2>/dev/null || echo "CV CoverLetter")
CV_DOCX="$FOLDER/${CV_WORD}_${OWNER_TAG}_${EMPLOYER}.docx"
LETTER_DOCX="$FOLDER/${LETTER_WORD}_${OWNER_TAG}_${EMPLOYER}.docx"

fail() { echo "SHIP-PACKAGE FAILED: $1" >&2; exit 1; }

[[ -f "$CV_MD" ]] || fail "$CV_MD not found"
[[ $CV_ONLY == 1 || -f "$LETTER_MD" ]] || fail "$LETTER_MD not found"

echo "== 1/8 aicheck (TOTAL must be 0) =="
if [[ $CV_ONLY == 1 ]]; then LETTER_ARG=(); else LETTER_ARG=("$LETTER_MD"); fi
python "$REPO_ROOT/scripts/aicheck.py" "$CV_MD" "${LETTER_ARG[@]}" || fail "aicheck found issues — fix the markdown sources, do not ship"

echo "== 2/8 consistency_check (structure, language, content-regulation, TOTAL must be 0) =="
python "$REPO_ROOT/scripts/consistency_check.py" "$FOLDER" || fail "consistency_check found issues — fix the markdown sources, do not ship"

echo "== 3/8 rank_skills must-tier coverage (hard stop if a supported must-tier keyword is missing) =="
python "$REPO_ROOT/scripts/rank_skills.py" check "$FOLDER" || fail "a must-tier keyword the profile supports is missing from cv.md — fix it, do not ship"

echo "== 4/8 build (markdown -> docx) =="
node "$REPO_ROOT/scripts/build-cv.js" "$CV_MD" "$CV_DOCX" || fail "build-cv.js failed on $CV_MD"
[[ $CV_ONLY == 1 ]] || node "$REPO_ROOT/scripts/build-cv.js" "$LETTER_MD" "$LETTER_DOCX" || fail "build-cv.js failed on $LETTER_MD"

echo "== 5/8 keep_pass (pagination: keep-with-next / keep-together) =="
python "$REPO_ROOT/scripts/keep_pass.py" "$CV_MD" "$CV_DOCX" || fail "keep_pass.py failed on $CV_DOCX"
[[ $CV_ONLY == 1 ]] || python "$REPO_ROOT/scripts/keep_pass.py" "$LETTER_MD" "$LETTER_DOCX" || fail "keep_pass.py failed on $LETTER_DOCX"

echo "== 6/8 fingerprint (style drift vs. the master) =="
python "$REPO_ROOT/scripts/fingerprint.py" check "$CV_DOCX" || fail "fingerprint drift on $CV_DOCX — do not ship"

echo "== 7/8 render to PDF =="
SOFFICE_BIN="$(command -v soffice || command -v libreoffice || true)"
if [[ -z "$SOFFICE_BIN" ]]; then
  for candidate in \
    "/c/Program Files/LibreOffice/program/soffice.exe" \
    "/c/Program Files (x86)/LibreOffice/program/soffice.exe" \
    "/Applications/LibreOffice.app/Contents/MacOS/soffice"; do
    if [[ -f "$candidate" ]]; then
      SOFFICE_BIN="$candidate"
      break
    fi
  done
fi
# soffice --headless writes a per-user profile lock (LibreOffice/4/.lock) while it
# runs; back-to-back invocations on Windows can race that lock (the previous
# process hasn't released it yet) and exit 1 with no output. Retry once after
# clearing a stale lock rather than failing the whole package on what is a
# rendering-tool flake, not a content problem — the .docx is still the real
# deliverable and step 6 already tolerates a missing PDF.
render_pdf() {
  local docx="$1" tries=0
  while (( tries < 3 )); do
    if "$SOFFICE_BIN" --headless --convert-to pdf --outdir "$FOLDER" "$docx" >/dev/null 2>&1; then
      return 0
    fi
    tries=$((tries + 1))
    rm -f "$HOME/AppData/Roaming/LibreOffice/4/.lock" "$HOME/.config/libreoffice/4/.lock" 2>/dev/null || true
    sleep 2
  done
  echo "warning: PDF render failed for $docx after retries — .docx is still valid, open it by hand" >&2
  return 0
}
if [[ -n "$SOFFICE_BIN" ]]; then
  render_pdf "$CV_DOCX"
  [[ $CV_ONLY == 1 ]] || render_pdf "$LETTER_DOCX"
else
  echo "no LibreOffice ('soffice') found (checked PATH and the default Windows install dir) — skipping automated PDF render. Open the .docx files by hand."
fi

echo "== 8/8 verify_pdf (page-by-page dump for review) =="
CV_PDF="${CV_DOCX%.docx}.pdf"
LETTER_PDF="${LETTER_DOCX%.docx}.pdf"
if [[ -f "$CV_PDF" ]]; then
  echo "--CV--"; python "$REPO_ROOT/scripts/verify_pdf.py" "$CV_PDF" || true
fi
if [[ -f "$LETTER_PDF" ]]; then
  echo "--LETTER--"; python "$REPO_ROOT/scripts/verify_pdf.py" "$LETTER_PDF" || true
fi

echo
echo "Mechanical gate passed (including must-tier keyword coverage, step 3/8). Before this goes to the owner:"
echo "  - open $CV_DOCX and $LETTER_DOCX (or their PDFs) and actually read them"
echo "  - confirm no employer, role or site is named that the profile does not support, and that the CV header follows the region's convention (regions/<code>/cv-conventions.md)"
echo "  - point to the exact sentence(s) in the letter stating genuine interest/motivation for THIS role — required, per rules/applications.md's cover-letter rule 3"
echo "  - write match-report.md and submission-checklist.md per rules/applications.md"

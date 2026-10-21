#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/aicheck.py
===================

The anti-AI-tell checker (rules/cv-build.md's "The anti-AI checker" section), ported
from the claude.ai toolchain. Runs on the markdown SOURCES before build-cv.js builds
the docx. Ship condition: TOTAL: 0.

Usage:
    python scripts/aicheck.py <file.md> [<file2.md> ...]
    python scripts/aicheck.py --json <file.md>

Exit code is the total finding count (0 = clean, nonzero = do not ship), so
ship-package.sh can gate on it directly.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Rule tables (rules/cv-build.md). Keep these as the single source of truth —
# don't duplicate a copy of this list into any other script.
# ---------------------------------------------------------------------------

AI_VOCABULARY = [
    "delve", "leverage", "utilise", "utilize", "robust", "holistic", "seamless", "vibrant",
    "pivotal", "crucial", "testament", "underscore", "showcase",
    "tapestry", "interplay", "intricate", "foster", "garnered", "garner",
    "realm", "myriad", "plethora",
    "embark", "passionate about", "deeply committed", "cutting-edge", "state-of-the-art",
    "game-changing", "game changing",
    "unlock", "empower", "elevate", "resonate", "align with",
    "synergy",
]
# "landscape" and "journey" are only AI-tells in their figurative sense; matched
# with a light heuristic below rather than a bare word match to avoid false
# positives on genuine uses ("the regulatory landscape" is borderline but common
# enough in this domain that it's still flagged — see LANDSCAPE_JOURNEY_PATTERN).

ENTHUSIASM_FILLER = ["excited to", "thrilled", "eager to", "passionate about"]

CV_CLICHES = ["proven track record", "results-driven", "team player", "hit the ground running"]

SELF_ASSESSMENT_CLICHE = re.compile(
    r"\bI believe I would be (?:a )?(?:great|perfect|strong|ideal)\b", re.IGNORECASE
)

# A comma-joined triple ending "and X" — an "un-earned rule of three" (rules/cv-build.md).
# A genuine triple (three real, distinct things) can still trip this; that's the
# documented tradeoff of a mechanical check, and it's why aicheck flags for review
# rather than auto-rewriting.
RULE_OF_THREE = re.compile(
    r"\b\w+[\w\s]{2,25}, [\w\s]{2,25}, and [\w\s]{2,25}\b", re.IGNORECASE
)

FILLER_PHRASES = {
    "in order to": "to",
    "due to the fact that": "because",
    "it is important to note that": "(delete)",
}

EM_DASH_CHARS = "—"  # —
EN_DASH_CHAR = "–"   # – (allowed in genuine date ranges, e.g. "Oct 2025 - present"
                          # is written with a hyphen in this system's own examples, but
                          # a stray en dash used as punctuation is still flagged)
CURLY_QUOTE_CHARS = "‘’“”"

ADDITIONALLY_OPENERS = re.compile(r"(?m)^\s*(Additionally|Moreover|Furthermore)\b")
NEGATIVE_PARALLELISM = re.compile(r"\bnot just\b.{0,60}\bbut\b", re.IGNORECASE)
# Only the specific gerunds AI writing leans on for a trailing "analysis clause"
# (", highlighting the importance of..."). A generic \w+ing\b match here would flag
# ordinary constructions ("...data, using X and Y.") that are not the tell described
# in rules/cv-build.md — so this is a curated verb list (matching the proven list
# from the real config/aicheck.py this was reconciled against), not every "-ing" word.
TRAILING_ING_CLAUSE = re.compile(
    r"\b(?:highlighting|underscoring|emphasizing|emphasising|showcasing|reflecting|"
    r"symbolizing|symbolising|ensuring|encompassing|contributing to|demonstrating)\b",
    re.IGNORECASE,
)
LANDSCAPE_JOURNEY_PATTERN = re.compile(r"\b(landscape|journey)\b", re.IGNORECASE)
QUESTION_MARK = "?"


@dataclass
class Finding:
    file: str
    line: int
    rule: str
    detail: str
    snippet: str


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _snippet(text: str, index: int, length: int, width: int = 60) -> str:
    start = max(0, index - width // 2)
    end = min(len(text), index + length + width // 2)
    return text[start:end].replace("\n", " ").strip()


def check_text(text: str, filename: str) -> list[Finding]:
    findings: list[Finding] = []
    is_letter = bool(re.search(r"(letter|anschreiben|motivation|cover)", filename, re.IGNORECASE))
    lower = text.lower()

    for ch in EM_DASH_CHARS:
        for m in re.finditer(re.escape(ch), text):
            findings.append(Finding(filename, _line_of(text, m.start()), "em_dash",
                                     "em dash — the strongest AI tell, never one",
                                     _snippet(text, m.start(), 1)))

    for ch in CURLY_QUOTE_CHARS:
        for m in re.finditer(re.escape(ch), text):
            findings.append(Finding(filename, _line_of(text, m.start()), "curly_quote",
                                     "curly quote/apostrophe — use straight quotes only",
                                     _snippet(text, m.start(), 1)))

    for word in AI_VOCABULARY:
        for m in re.finditer(r"\b" + re.escape(word) + r"\b", lower):
            findings.append(Finding(filename, _line_of(text, m.start()), "ai_vocabulary",
                                     f"AI-vocabulary word: {word!r}",
                                     _snippet(text, m.start(), len(word))))

    for m in LANDSCAPE_JOURNEY_PATTERN.finditer(text):
        findings.append(Finding(filename, _line_of(text, m.start()), "ai_vocabulary",
                                 f"figurative AI-vocabulary word: {m.group(0)!r}",
                                 _snippet(text, m.start(), len(m.group(0)))))

    for m in ADDITIONALLY_OPENERS.finditer(text):
        findings.append(Finding(filename, _line_of(text, m.start()), "sentence_opener",
                                 f"{m.group(1)!r} opening a sentence",
                                 _snippet(text, m.start(), len(m.group(0)))))

    for m in NEGATIVE_PARALLELISM.finditer(text):
        findings.append(Finding(filename, _line_of(text, m.start()), "negative_parallelism",
                                 "'not just X, but Y' construction — say the thing once",
                                 _snippet(text, m.start(), len(m.group(0)))))

    for m in TRAILING_ING_CLAUSE.finditer(text):
        findings.append(Finding(filename, _line_of(text, m.start()), "trailing_ing_clause",
                                 "trailing '-ing' analysis clause",
                                 _snippet(text, m.start(), len(m.group(0)))))

    for phrase in ENTHUSIASM_FILLER:
        for m in re.finditer(re.escape(phrase), lower):
            findings.append(Finding(filename, _line_of(text, m.start()), "enthusiasm_filler",
                                     f"enthusiasm filler: {phrase!r}",
                                     _snippet(text, m.start(), len(phrase))))

    for phrase in CV_CLICHES:
        for m in re.finditer(re.escape(phrase), lower):
            findings.append(Finding(filename, _line_of(text, m.start()), "cv_cliche",
                                     f"CV cliche: {phrase!r}",
                                     _snippet(text, m.start(), len(phrase))))

    for phrase, replacement in FILLER_PHRASES.items():
        for m in re.finditer(re.escape(phrase), lower):
            findings.append(Finding(filename, _line_of(text, m.start()), "filler_phrase",
                                     f"filler phrase: {phrase!r} -> {replacement}",
                                     _snippet(text, m.start(), len(phrase))))

    for m in SELF_ASSESSMENT_CLICHE.finditer(text):
        findings.append(Finding(filename, _line_of(text, m.start()), "self_assessment_cliche",
                                 "self-assessment cliche ('I believe I would be a great...')",
                                 _snippet(text, m.start(), len(m.group(0)))))

    for m in RULE_OF_THREE.finditer(text):
        findings.append(Finding(filename, _line_of(text, m.start()), "rule_of_three",
                                 "un-earned rule of three (comma, comma, and X)",
                                 _snippet(text, m.start(), len(m.group(0)))))

    if is_letter:
        for m in re.finditer(re.escape(QUESTION_MARK), text):
            findings.append(Finding(filename, _line_of(text, m.start()), "question_mark_in_letter",
                                     "HARD STOP: a '?' anywhere in a cover letter file",
                                     _snippet(text, m.start(), 1)))

    return findings


def check_file(path: Path) -> list[Finding]:
    text = path.read_text(encoding="utf-8")
    return check_text(text, path.name)


def main() -> int:
    # Windows' console defaults to cp1252, which can't encode every character
    # a real CV/letter (or a snippet quoted from one) might contain -- an
    # unhandled UnicodeEncodeError here would abort mid-print with a raw
    # traceback instead of the intended TOTAL/exit-code contract ship-package.sh
    # relies on. Force UTF-8 so a real finding never crashes the gate.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args()

    all_findings: list[Finding] = []
    for path in args.files:
        if not path.exists():
            print(f"aicheck: {path} does not exist", file=sys.stderr)
            return 2
        all_findings.extend(check_file(path))

    if args.json:
        print(json.dumps([asdict(f) for f in all_findings], indent=2, ensure_ascii=False))
    else:
        for f in all_findings:
            print(f"{f.file}:{f.line}  [{f.rule}]  {f.detail}\n    ...{f.snippet}...")
        print(f"\nTOTAL: {len(all_findings)}")
        if all_findings:
            print("\nBeyond these mechanical rules (rules/cv-build.md): vary sentence "
                  "rhythm, and let an honest hedge through ('I suspect', 'I haven't "
                  "done this part yet') — uniform polish is itself a tell.")

    return len(all_findings)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/fingerprint.py
=======================

Verifies a built .docx against the full visual spec (rules/cv-build.md's
"Visual spec (measured directly from the master docx)" table), not just page
margins and the name line. The spec numbers below are copied from
scripts/build-cv.js's own constants (NAME, SUBTITLE, CONTACT_RULE,
CONTACT_LINE, SECTION_RULE, SECTION_HEADING, ENTRY_TITLE, ENTRY_DATE,
SUB_LINE, BODY_PARA, BULLET_RUN, BULLET_GLYPH, BULLET_INDENT,
ENTRY_DATE_TAB_POS, MARGIN_TWIPS) — this script and that generator must be
kept in sync by hand if either one changes; this file's own docstring is the
place that says so.

Why this got rewritten (2026-09-27): the previous version only compared page
margins and the first paragraph's (the name line's) size/bold/color/alignment
against a golden_spec.json. a real defect once went unnoticed for weeks —
CONTACT_RULE and SECTION_RULE swapped in the generator for weeks, undetected —
that the old fingerprint.py could not have caught, because it never looked at
either border at all. This version specifically checks that the section
heading's border is the LIGHTER one (sz 6) and the contact line's is the
HEAVIER one (sz 8), and flags it by name if a future regression makes them
match or swap.

What this checks, section by section of the spec table:
  - font            every run's font is Calibri, no second typeface anywhere
  - margins         1134 twips (2cm) left/right, 567 twips (1cm) top/bottom
  - name line       size/bold/color/alignment/ALL CAPS/spacing-after
  - subtitle line   size/color/alignment/spacing-after
  - contact line    size/alignment/spacing-after + CONTACT_RULE border
                    (size 8, space 6, color 1F3864)
  - section headings (every one, not just the first) — size/bold/ALL CAPS/
                    color/spacing + SECTION_RULE border (size 6, space 2,
                    color 1F3864), and explicitly: not the same border as the
                    contact line
  - entry titles/dates — size/bold/color for both runs on the line, and the
                    right tab stop position (9360)
  - sub-lines       size/italic/color/spacing-after
  - bullets         size/color/spacing/line-spacing/indent (left 720,
                    hanging 360), plus the numbering part's own bullet glyph
                    (● — word/numbering.xml's lvlText)
  - keepNext        section headings, entry titles, and sub-lines all carry
                    keepNext (rules/cv-build.md's 25 Sep pagination fix,
                    normally set by keep_pass.py earlier in
                    scripts/ship-package.sh — this is a safety net, not a
                    substitute for running that step)

Requires python-docx for the full check (already a hard requirement of this
project's toolchain — see requirements.txt / keep_pass.py). Without it, `check`
falls back to a margins-only comparison against config/golden_spec.json and
says so loudly, rather than silently passing everything else.

Usage:
    python scripts/fingerprint.py check <built.docx>
    python scripts/fingerprint.py learn <master.docx>   # re-measures margins
                                                         # + name line into
                                                         # config/golden_spec.json
                                                         # (legacy minimal mode)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

GOLDEN_SPEC_PATH = Path(__file__).resolve().parent.parent / "profile" / "golden_spec.json"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _qn(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


# ---------------------------------------------------------------------------
# The spec, copied verbatim from scripts/build-cv.js's own constants —
# rules/cv-build.md's visual spec table, in code form.
# ---------------------------------------------------------------------------

COLOR_NAVY = "1F3864"
COLOR_BODY = "333333"
COLOR_SUBLINE = "555555"
FONT_NAME = "Calibri"
MARGIN_TWIPS = 1134  # left/right
MARGIN_TWIPS_V = 567  # top/bottom — tightened 28 Sep 2026 to fit more per page

SPEC = {
    "name": {"size_pt": 17, "bold": True, "color": COLOR_NAVY, "align": "center",
              "all_caps": True, "space_after": 40},
    "subtitle": {"size_pt": 10, "color": COLOR_BODY, "align": "center", "space_after": 60},
    "contact": {"size_pt": 9, "align": "center", "space_after": 200,
                "border_sz": 8, "border_space": 6, "border_color": COLOR_NAVY},
    "section_heading": {"size_pt": 10.5, "bold": True, "all_caps": True, "color": COLOR_NAVY,
                         "space_before": 220, "space_after": 90,
                         "border_sz": 6, "border_space": 2, "border_color": COLOR_NAVY,
                         "keep_next": True},
    "entry_title": {"size_pt": 10.5, "bold": True, "color": COLOR_BODY,
                     "space_before": 0, "space_after": 10, "keep_next": True},
    "entry_date": {"size_pt": 9.5, "bold": True, "color": COLOR_NAVY, "right_tab": 9360},
    "sub_line": {"size_pt": 9.5, "italic": True, "color": COLOR_SUBLINE, "space_after": 80,
                 "keep_next": True},
    "body": {"size_pt": 10, "color": COLOR_BODY, "line": 264, "space_after": 160},
    "bullet": {"size_pt": 10, "color": COLOR_BODY, "line": 258, "space_after": 60,
               "indent_left": 720, "indent_hanging": 360, "glyph": "●"},
}


# ---------------------------------------------------------------------------
# Legacy minimal (bare zip/XML, no python-docx) measurement — kept for `learn`
# and as a fallback if python-docx isn't installed.
# ---------------------------------------------------------------------------

def _read_document_xml(docx_path: Path) -> ET.Element:
    with zipfile.ZipFile(docx_path) as z:
        xml_bytes = z.read("word/document.xml")
    return ET.fromstring(xml_bytes)


def _read_section_margins(root: ET.Element) -> dict:
    pgMar = root.find(f".//{_qn('sectPr')}/{_qn('pgMar')}")
    if pgMar is None:
        return {}
    return {
        "top": pgMar.get(_qn("top")),
        "bottom": pgMar.get(_qn("bottom")),
        "left": pgMar.get(_qn("left")),
        "right": pgMar.get(_qn("right")),
    }


def _first_paragraph_style(root: ET.Element) -> dict:
    p = root.find(f".//{_qn('body')}/{_qn('p')}")
    if p is None:
        return {}
    rPr = p.find(f"{_qn('r')}/{_qn('rPr')}")
    style = {}
    if rPr is not None:
        sz = rPr.find(_qn("sz"))
        if sz is not None:
            style["size"] = sz.get(_qn("val"))
        b = rPr.find(_qn("b"))
        style["bold"] = b is not None
        color = rPr.find(_qn("color"))
        if color is not None:
            style["color"] = color.get(_qn("val"))
    pPr = p.find(_qn("pPr"))
    if pPr is not None:
        jc = pPr.find(_qn("jc"))
        if jc is not None:
            style["alignment"] = jc.get(_qn("val"))
    return style


def measure(docx_path: Path) -> dict:
    root = _read_document_xml(docx_path)
    all_paragraphs = root.findall(f".//{_qn('body')}/{_qn('p')}")
    return {
        "margins": _read_section_margins(root),
        "name_line": _first_paragraph_style(root),
        "paragraph_count": len(all_paragraphs),
    }


def learn(master_path: Path) -> dict:
    spec = measure(master_path)
    GOLDEN_SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_SPEC_PATH.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    print(f"golden spec re-measured from {master_path.name} -> {GOLDEN_SPEC_PATH}")
    return spec


def _read_numbering_xml(docx_path: Path) -> ET.Element | None:
    try:
        with zipfile.ZipFile(docx_path) as z:
            if "word/numbering.xml" not in z.namelist():
                return None
            xml = z.read("word/numbering.xml")
    except (KeyError, zipfile.BadZipFile):
        return None
    return ET.fromstring(xml)


def _bullet_glyph(docx_path: Path) -> str | None:
    root = _read_numbering_xml(docx_path)
    if root is None:
        return None
    lvl_text = root.find(f".//{_qn('lvl')}/{_qn('lvlText')}")
    return lvl_text.get(_qn("val")) if lvl_text is not None else None


def _numbering_level_indent(numbering_root: ET.Element | None) -> dict | None:
    """The indent build-cv.js's bullet numbering carries lives on the
    abstractNum's level definition (word/numbering.xml), not on each
    individual paragraph's own pPr — a paragraph that merely references
    numId/ilvl inherits it. Reads the first (and, for this generator, only)
    level-0 definition's own indent rather than assuming every paragraph
    overrides it locally."""
    if numbering_root is None:
        return None
    ind = numbering_root.find(f".//{_qn('lvl')}/{_qn('pPr')}/{_qn('ind')}")
    if ind is None:
        return None
    return {"left": _attr(ind, "left"), "hanging": _attr(ind, "hanging")}


# ---------------------------------------------------------------------------
# Raw pPr-level readers (spacing/border/indent/tabs/numbering/keepNext) — read
# straight off the paragraph's own XML element so the numbers match the raw
# twip/dxa values in the spec table exactly, with no unit-conversion ambiguity.
# ---------------------------------------------------------------------------

def _attr(el, name: str) -> str | None:
    return el.get(_qn(name)) if el is not None else None


def _raw_spacing(p_xml) -> dict:
    spacing = p_xml.find(f"{_qn('pPr')}/{_qn('spacing')}")
    if spacing is None:
        return {}
    return {k: _attr(spacing, k) for k in ("before", "after", "line", "lineRule")}


def _raw_border_bottom(p_xml) -> dict | None:
    border = p_xml.find(f"{_qn('pPr')}/{_qn('pBdr')}/{_qn('bottom')}")
    if border is None:
        return None
    return {"sz": _attr(border, "sz"), "space": _attr(border, "space"), "color": _attr(border, "color")}


def _raw_indent(p_xml) -> dict | None:
    ind = p_xml.find(f"{_qn('pPr')}/{_qn('ind')}")
    if ind is None:
        return None
    return {"left": _attr(ind, "left"), "hanging": _attr(ind, "hanging")}


def _raw_has_numbering(p_xml) -> bool:
    return p_xml.find(f"{_qn('pPr')}/{_qn('numPr')}") is not None


def _raw_has_keep_next(p_xml) -> bool:
    return p_xml.find(f"{_qn('pPr')}/{_qn('keepNext')}") is not None


def _raw_alignment(p_xml) -> str | None:
    jc = p_xml.find(f"{_qn('pPr')}/{_qn('jc')}")
    return _attr(jc, "val") if jc is not None else None


def _raw_right_tab(p_xml) -> int | None:
    for tab in p_xml.findall(f"{_qn('pPr')}/{_qn('tabs')}/{_qn('tab')}"):
        if _attr(tab, "val") == "right":
            pos = _attr(tab, "pos")
            return int(pos) if pos is not None else None
    return None


def _cmp(actual, expected) -> bool:
    return str(actual) == str(expected)


# ---------------------------------------------------------------------------
# Run/paragraph-level checks against SPEC, using python-docx for font
# properties (size/bold/italic/color/name) and the raw readers above for
# everything pPr owns.
# ---------------------------------------------------------------------------

def _check_run(label: str, i: int, run, spec: dict) -> list[str]:
    findings = []
    if run is None:
        return [f"{label} (paragraph {i}): no run found to check style"]
    if "size_pt" in spec and run.font.size is not None:
        actual = round(run.font.size.pt, 2)
        if abs(actual - spec["size_pt"]) > 0.05:
            findings.append(f"{label} (paragraph {i}): font size {actual}pt, expected {spec['size_pt']}pt")
    if "bold" in spec and bool(run.bold) != spec["bold"]:
        findings.append(f"{label} (paragraph {i}): bold={bool(run.bold)}, expected {spec['bold']}")
    if "italic" in spec and bool(run.italic) != spec["italic"]:
        findings.append(f"{label} (paragraph {i}): italic={bool(run.italic)}, expected {spec['italic']}")
    if "color" in spec and run.font.color and run.font.color.rgb:
        actual_color = str(run.font.color.rgb)
        if actual_color.upper() != spec["color"].upper():
            findings.append(f"{label} (paragraph {i}): color {actual_color}, expected {spec['color']}")
    if run.font.name and run.font.name != FONT_NAME:
        findings.append(f"{label} (paragraph {i}): run font is {run.font.name!r}, expected {FONT_NAME!r}")
    return findings


def _check_box(label: str, i: int, p, spec: dict) -> list[str]:
    """pPr-level checks: alignment, ALL CAPS, spacing, keepNext."""
    findings = []
    if "align" in spec:
        jc = _raw_alignment(p._p)
        if jc != spec["align"]:
            findings.append(f"{label} (paragraph {i}): alignment={jc!r}, expected {spec['align']!r}")
    if spec.get("all_caps") and p.text.strip() and p.text.strip() != p.text.strip().upper():
        findings.append(f"{label} (paragraph {i}): text is not ALL CAPS: {p.text!r}")
    spacing = _raw_spacing(p._p)
    for xml_key, spec_key in (("before", "space_before"), ("after", "space_after"), ("line", "line")):
        if spec_key in spec and not _cmp(spacing.get(xml_key), spec[spec_key]):
            findings.append(f"{label} (paragraph {i}): spacing {xml_key}={spacing.get(xml_key)}, "
                             f"expected {spec[spec_key]}")
    if spec.get("keep_next") and not _raw_has_keep_next(p._p):
        findings.append(f"{label} (paragraph {i}): missing keepNext (rules/cv-build.md's pagination "
                         f"fix — normally set by keep_pass.py; a miss here means it regressed)")
    return findings


def _check_border(label: str, i: int, border: dict | None, spec: dict) -> list[str]:
    findings = []
    if border is None:
        return [f"{label} (paragraph {i}): expected a bottom border, found none"]
    for xml_key, spec_key in (("sz", "border_sz"), ("space", "border_space"), ("color", "border_color")):
        if spec_key in spec and not _cmp(border.get(xml_key), spec[spec_key]):
            findings.append(f"{label} (paragraph {i}): border {xml_key}={border.get(xml_key)}, "
                             f"expected {spec[spec_key]}")
    return findings


def check_full(docx_path: Path) -> list[str]:
    """The comprehensive visual-spec check. Requires python-docx."""
    from docx import Document

    findings: list[str] = []
    doc = Document(str(docx_path))
    paras = doc.paragraphs
    if not paras:
        return ["document has no paragraphs"]

    # A cover letter shares the CV's header (name/subtitle/contact line) but
    # has no section headings and no bullets by design (rules/cv-build.md's
    # cover-letter layout section) — every docx this generator writes carries
    # a numbering part regardless of whether anything uses it, so "has a
    # numbering part" can't distinguish the two; a salutation line can.
    full_text = "\n".join(p.text for p in paras)
    is_letter = bool(re.search(r"Sehr geehrte|Dear \w|Damen und Herren", full_text))

    # margins
    root = _read_document_xml(docx_path)
    margins = _read_section_margins(root)
    for side in ("top", "bottom", "left", "right"):
        expected = MARGIN_TWIPS_V if side in ("top", "bottom") else MARGIN_TWIPS
        if not _cmp(margins.get(side), expected):
            findings.append(f"page margin {side}={margins.get(side)}, expected {expected} twips")

    # global font — no second typeface anywhere in the document
    for i, p in enumerate(paras):
        for r in p.runs:
            if r.font.name and r.font.name != FONT_NAME:
                findings.append(f"paragraph {i} ({p.text[:40]!r}): run font is {r.font.name!r}, "
                                 f"expected {FONT_NAME!r}")

    # name line — paragraph 0
    name_p = paras[0]
    findings += _check_run("name line", 0, name_p.runs[0] if name_p.runs else None, SPEC["name"])
    findings += _check_box("name line", 0, name_p, SPEC["name"])

    # subtitle — paragraph 1
    if len(paras) > 1:
        sub_p = paras[1]
        findings += _check_run("subtitle line", 1, sub_p.runs[0] if sub_p.runs else None, SPEC["subtitle"])
        findings += _check_box("subtitle line", 1, sub_p, SPEC["subtitle"])

    # contact line — first bordered paragraph in the first handful, after the
    # name/subtitle lines
    contact_idx, contact_p, contact_border = None, None, None
    for i, p in enumerate(paras[2:8], start=2):
        border = _raw_border_bottom(p._p)
        if border is not None:
            contact_idx, contact_p, contact_border = i, p, border
            break
    if contact_p is not None:
        findings += _check_run("contact line", contact_idx, contact_p.runs[0] if contact_p.runs else None,
                                SPEC["contact"])
        findings += _check_box("contact line", contact_idx, contact_p, SPEC["contact"])
        findings += _check_border("contact line (CONTACT_RULE)", contact_idx, contact_border, SPEC["contact"])
    else:
        findings.append("no contact-line border found in the first few paragraphs — CONTACT_RULE missing")

    # section headings — every ALL-CAPS, bold, bordered paragraph after the contact line
    section_headings = []
    start_at = (contact_idx + 1) if contact_idx is not None else 2
    for i, p in enumerate(paras):
        if i < start_at:
            continue
        text = p.text.strip()
        if not text or not text.isupper() or not p.runs or not p.runs[0].bold:
            continue
        border = _raw_border_bottom(p._p)
        if border is None:
            continue
        section_headings.append((i, p, border))

    if not section_headings and not is_letter:
        findings.append("no section headings detected (expected bold, ALL-CAPS, bordered paragraphs)")
    for i, p, border in section_headings:
        label = f"section heading {p.text!r}"
        findings += _check_run(label, i, p.runs[0], SPEC["section_heading"])
        findings += _check_box(label, i, p, SPEC["section_heading"])
        findings += _check_border(f"{label} (SECTION_RULE)", i, border, SPEC["section_heading"])
        # THE historic bug this whole check exists to catch (the real defect described at the top of this file):
        # CONTACT_RULE and SECTION_RULE swapped in the generator for weeks,
        # undetected, because nothing compared the two borders to each other.
        if contact_border is not None and border.get("sz") == contact_border.get("sz"):
            findings.append(
                f"{label} (paragraph {i}): border weight (sz={border.get('sz')}) matches the "
                f"contact line's border — CONTACT_RULE/SECTION_RULE may be swapped or "
                f"collapsed to one value (the documented regression)"
            )

    # entry title + date — paragraphs with a right tab stop and two runs
    for i, p in enumerate(paras):
        right_tab = _raw_right_tab(p._p)
        if right_tab is None or "\t" not in p.text:
            continue
        title_part, _, date_part = p.text.partition("\t")
        title_run = p.runs[0] if p.runs else None
        date_run = p.runs[-1] if len(p.runs) > 1 else None
        findings += _check_run(f"entry title {title_part!r}", i, title_run, SPEC["entry_title"])
        findings += _check_box(f"entry title {title_part!r}", i, p, SPEC["entry_title"])
        if date_run is not None:
            findings += _check_run(f"entry date {date_part!r}", i, date_run, SPEC["entry_date"])
        if not _cmp(right_tab, SPEC["entry_date"]["right_tab"]):
            findings.append(f"paragraph {i}: entry-date tab stop is {right_tab}, "
                             f"expected {SPEC['entry_date']['right_tab']}")

    # sub-lines — single-run, fully italic paragraphs
    for i, p in enumerate(paras):
        if p.text.strip() and len(p.runs) == 1 and p.runs[0].italic:
            label = f"sub-line {p.text!r}"
            findings += _check_run(label, i, p.runs[0], SPEC["sub_line"])
            findings += _check_box(label, i, p, SPEC["sub_line"])

    # bullets — numbered paragraphs. The indent is normally defined once on
    # the numbering level (word/numbering.xml), not per paragraph — check a
    # paragraph-local override if present, else fall back to the level's own
    # indent, and only flag a genuine miss if neither carries one.
    numbering_root = _read_numbering_xml(docx_path)
    level_indent = _numbering_level_indent(numbering_root)
    bullets = [(i, p) for i, p in enumerate(paras) if _raw_has_numbering(p._p)]
    if not bullets and not is_letter:
        findings.append("no bulleted paragraphs detected anywhere in the document")
    for i, p in bullets:
        label = f"bullet {p.text[:40]!r}"
        findings += _check_run(label, i, p.runs[0] if p.runs else None, SPEC["bullet"])
        findings += _check_box(label, i, p, SPEC["bullet"])
        ind = _raw_indent(p._p) or level_indent
        if ind is None:
            findings.append(f"{label} (paragraph {i}): no indent found (checked both the paragraph "
                             f"and its numbering level), expected left={SPEC['bullet']['indent_left']} "
                             f"hanging={SPEC['bullet']['indent_hanging']}")
        else:
            if not _cmp(ind.get("left"), SPEC["bullet"]["indent_left"]):
                findings.append(f"{label} (paragraph {i}): indent left={ind.get('left')}, "
                                 f"expected {SPEC['bullet']['indent_left']}")
            if not _cmp(ind.get("hanging"), SPEC["bullet"]["indent_hanging"]):
                findings.append(f"{label} (paragraph {i}): indent hanging={ind.get('hanging')}, "
                                 f"expected {SPEC['bullet']['indent_hanging']}")

    # bullet glyph — word/numbering.xml's own lvlText
    glyph = _bullet_glyph(docx_path)
    if glyph is None:
        findings.append("could not read a bullet glyph from word/numbering.xml")
    elif glyph != SPEC["bullet"]["glyph"]:
        findings.append(f"bullet glyph is {glyph!r}, expected {SPEC['bullet']['glyph']!r}")

    return findings


def check(built_path: Path) -> list[str]:
    findings: list[str] = []

    try:
        import docx  # noqa: F401
    except ImportError:
        # Legacy minimal fallback — margins + name line only, against
        # config/golden_spec.json, if it exists.
        if GOLDEN_SPEC_PATH.exists():
            golden = json.loads(GOLDEN_SPEC_PATH.read_text(encoding="utf-8"))
            built = measure(built_path)
            if built.get("margins") != golden.get("margins"):
                findings.append(f"margins drift: built={built.get('margins')} golden={golden.get('margins')}")
            if built.get("name_line") != golden.get("name_line"):
                findings.append(f"name_line style drift: built={built.get('name_line')} "
                                 f"golden={golden.get('name_line')}")
        findings.append(
            "python-docx not installed — only a minimal margins/name-line check ran. "
            "Install python-docx (see requirements.txt) for the full visual-spec fingerprint "
            "(rules/cv-build.md); do not treat a clean result here as a real pass."
        )
        return findings

    return check_full(built_path)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass  # older Python / non-reconfigurable stream — findings still return a real exit code
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_check = sub.add_parser("check")
    p_check.add_argument("docx_path", type=Path)
    p_learn = sub.add_parser("learn")
    p_learn.add_argument("docx_path", type=Path)
    args = parser.parse_args()

    if not args.docx_path.exists():
        print(f"fingerprint: {args.docx_path} does not exist", file=sys.stderr)
        return 2

    if args.cmd == "learn":
        learn(args.docx_path)
        return 0

    drift = check(args.docx_path)
    if drift:
        print("FINGERPRINT DRIFT (defect — do not ship):")
        for d in drift:
            print(f"  - {d}")
        return 1
    print("fingerprint OK: matches the visual spec (rules/cv-build.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

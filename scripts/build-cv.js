#!/usr/bin/env node
/**
 * scripts/build-cv.js
 * ====================
 * Markdown -> .docx generator for the JOB system, ported from cv-pipeline-toolchain.md.
 * The visual spec it implements lives in rules/cv-build.md — read that file before
 * changing any constant below, especially CONTACT_RULE / SECTION_RULE (see the
 * comment on those: they were swapped for weeks once, unnoticed, hence the names).
 *
 * Usage: node scripts/build-cv.js <input.md> <output.docx>
 *
 * Markdown source language (rules/cv-build.md):
 *   "# "              the person's name
 *   "@ "               a centred header line; the LAST consecutive "@ " line gets
 *                       the CONTACT_RULE border (so one "@ " line = just a subtitle,
 *                       two = subtitle then contact-with-rule)
 *   "## "              section heading
 *   "### Title ||| Date"  entry title with a right-tabbed date on the same line
 *   "*italic sub-line*"   a sub-line (must be the ENTIRE line, start to end)
 *   "- "               a bullet (a "- **Label:** ..." skills line is still just a
 *                       bullet; the **bold** is parsed inline)
 *   ">> "              a right-aligned line (cover letters: the "Place, Date" line)
 *   (anything else)    a body paragraph
 */

'use strict';

const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, AlignmentType, BorderStyle,
  TabStopType, LevelFormat, HeadingLevel, ExternalHyperlink,
} = require('docx');

// Real hyperlink hosts styled navy+underlined in the contact line (matches the
// proven config/build-cv.js this was reconciled against — a plain styled TextRun
// looks identical on the page but isn't clickable in the .docx).
const HYPERLINK_HOST_PATTERN = /\S*(?:linkedin\.com|github\.com)\S*/g;

// ---------------------------------------------------------------------------
// The visual spec (rules/cv-build.md). Do not hand-tune these per document —
// if the master CV's real look ever changes, re-measure and edit here once.
// ---------------------------------------------------------------------------
const COLOR_NAVY = '1F3864';
const COLOR_BODY = '333333';
const COLOR_SUBLINE = '555555';

const FONT = 'Calibri';
const MARGIN_TWIPS = 1134; // 2cm — left/right
const MARGIN_TWIPS_V = 567; // 1cm — top/bottom, tightened 28 Sep 2026 to fit more per page

const NAME = { size: 34, bold: true, color: COLOR_NAVY, after: 40 };
const SUBTITLE = { size: 20, color: COLOR_BODY, after: 60 };
// CONTACT_RULE: the HEAVIER rule (sz 8), under the contact line only.
const CONTACT_RULE = { size: 8, space: 6, color: COLOR_NAVY };
const CONTACT_LINE = { size: 18, color: COLOR_BODY, after: 200 };
// SECTION_RULE: the LIGHTER rule (sz 6), under every section heading.
const SECTION_RULE = { size: 6, space: 2, color: COLOR_NAVY };
const SECTION_HEADING = { size: 21, bold: true, color: COLOR_NAVY, before: 220, after: 90 };
const ENTRY_TITLE = { size: 21, bold: true, color: COLOR_BODY, before: 0, after: 10 };
const ENTRY_DATE = { size: 19, bold: true, color: COLOR_NAVY };
const ENTRY_DATE_TAB_POS = 9360;
const SUB_LINE = { size: 19, italic: true, color: COLOR_SUBLINE, after: 80 };
const BODY_PARA = { size: 20, color: COLOR_BODY, line: 264, after: 160 };
const BULLET_RUN = { size: 20, color: COLOR_BODY, line: 258, after: 60 };
const BULLET_GLYPH = '●'; // ●
const BULLET_INDENT = { left: 720, hanging: 360 };

const NUMBERING_REFERENCE = 'cv-bullets';

// ---------------------------------------------------------------------------
// Inline **bold** parsing (used on bullets and body paragraphs). Single-asterisk
// italics inside a body line are a documented gotcha (they render literally) so
// this parser intentionally does NOT treat lone "*" as italic markup.
// ---------------------------------------------------------------------------
function parseInlineRuns(text, baseProps) {
  const runs = [];
  const re = /\*\*(.+?)\*\*/g;
  let lastIndex = 0;
  let match;
  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIndex) {
      runs.push(new TextRun({ ...baseProps, text: text.slice(lastIndex, match.index) }));
    }
    runs.push(new TextRun({ ...baseProps, text: match[1], bold: true }));
    lastIndex = re.lastIndex;
  }
  if (lastIndex < text.length) {
    runs.push(new TextRun({ ...baseProps, text: text.slice(lastIndex) }));
  }
  if (runs.length === 0) runs.push(new TextRun({ ...baseProps, text: '' }));
  return runs;
}

// Contact line: style linkedin.com/github.com tokens as real, clickable hyperlinks
// (navy + underlined), not just styled text that looks like one.
function contactRuns(text, baseProps) {
  const out = [];
  const parts = text.split(HYPERLINK_HOST_PATTERN);
  const matches = text.match(HYPERLINK_HOST_PATTERN) || [];
  for (let i = 0; i < parts.length; i++) {
    if (parts[i]) out.push(new TextRun({ ...baseProps, text: parts[i] }));
    if (matches[i]) {
      out.push(new ExternalHyperlink({
        link: 'https://' + matches[i].replace(/^https?:\/\//, ''),
        children: [new TextRun({ ...baseProps, text: matches[i], color: baseProps.color, underline: {} })],
      }));
    }
  }
  return out.length ? out : [new TextRun({ ...baseProps, text: '' })];
}

// A gotcha documented in rules/cv-build.md: a hard-wrapped bullet/body line used to
// silently become a separate, independently-page-breaking paragraph. Joining
// continuation lines here (anything that isn't blank and isn't itself a markdown
// marker gets folded into the previous non-marker line) makes that non-fatal instead
// of a rule to remember by hand — matches the proven config/build-cv.js's approach.
function joinHardWrappedLines(mdText) {
  const rawLines = mdText.split(/\r?\n/);
  const isMarker = (t) => /^(#{1,3} |@ |>> |- )/.test(t) || /^\*[^*].*\*$/.test(t);
  const joined = [];
  let buffer = '';
  for (const raw of rawLines) {
    const t = raw.replace(/\s+$/, '');
    if (!t.trim()) {
      if (buffer) { joined.push(buffer); buffer = ''; }
      joined.push('');
      continue;
    }
    if (isMarker(t)) {
      if (buffer) { joined.push(buffer); buffer = ''; }
      joined.push(t);
      continue;
    }
    buffer = buffer ? buffer + ' ' + t.trim() : t;
  }
  if (buffer) joined.push(buffer);
  return joined.join('\n');
}

function parseMarkdown(mdText) {
  const lines = joinHardWrappedLines(mdText).split(/\r?\n/);
  const paragraphs = [];
  let sawName = false;
  const atLines = [];
  for (const raw of lines) {
    if (raw.startsWith('@ ')) atLines.push(raw);
  }
  let atLineIndex = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed === '') continue;

    if (trimmed.startsWith('# ')) {
      paragraphs.push(new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: NAME.after },
        children: [new TextRun({
          text: trimmed.slice(2).toUpperCase(), font: FONT,
          size: NAME.size, bold: NAME.bold, color: NAME.color,
        })],
      }));
      sawName = true;
      continue;
    }

    if (trimmed.startsWith('@ ')) {
      atLineIndex += 1;
      const isLast = atLineIndex === atLines.length;
      const text = trimmed.slice(2);
      if (isLast) {
        paragraphs.push(new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: CONTACT_LINE.after },
          border: { bottom: { style: BorderStyle.SINGLE, size: CONTACT_RULE.size, space: CONTACT_RULE.space, color: CONTACT_RULE.color } },
          children: contactRuns(text, { font: FONT, size: CONTACT_LINE.size, color: CONTACT_LINE.color }),
        }));
      } else {
        paragraphs.push(new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: SUBTITLE.after },
          children: parseInlineRuns(text, { font: FONT, size: SUBTITLE.size, color: SUBTITLE.color }),
        }));
      }
      continue;
    }

    if (trimmed.startsWith('## ')) {
      paragraphs.push(new Paragraph({
        spacing: { before: SECTION_HEADING.before, after: SECTION_HEADING.after },
        border: { bottom: { style: BorderStyle.SINGLE, size: SECTION_RULE.size, space: SECTION_RULE.space, color: SECTION_RULE.color } },
        // never let a page break separate a heading from what follows it — the
        // literal bug this was added for: "Education" stranded alone at the
        // bottom of page 1 (rules/cv-build.md's pagination rule).
        keepNext: true,
        children: [new TextRun({
          text: trimmed.slice(3).toUpperCase(), font: FONT,
          size: SECTION_HEADING.size, bold: SECTION_HEADING.bold, color: SECTION_HEADING.color,
        })],
      }));
      continue;
    }

    if (trimmed.startsWith('### ')) {
      const rest = trimmed.slice(4);
      const [titlePart, datePart] = rest.split('|||').map((s) => s.trim());
      const children = [new TextRun({
        text: titlePart, font: FONT, size: ENTRY_TITLE.size,
        bold: ENTRY_TITLE.bold, color: ENTRY_TITLE.color,
      })];
      if (datePart) {
        children.push(new TextRun({ text: '\t', font: FONT }));
        children.push(new TextRun({
          text: datePart, font: FONT, size: ENTRY_DATE.size,
          bold: ENTRY_DATE.bold, color: ENTRY_DATE.color,
        }));
      }
      paragraphs.push(new Paragraph({
        spacing: { before: ENTRY_TITLE.before, after: ENTRY_TITLE.after },
        tabStops: datePart ? [{ type: TabStopType.RIGHT, position: ENTRY_DATE_TAB_POS }] : [],
        // keep an entry's title+date glued to whatever follows it (a sub-line or
        // its first bullet) — same pagination rule as the section heading above.
        keepNext: true,
        children,
      }));
      continue;
    }

    if (trimmed.startsWith('*') && trimmed.endsWith('*') && trimmed.length > 1 && !trimmed.startsWith('**')) {
      const text = trimmed.slice(1, -1);
      paragraphs.push(new Paragraph({
        spacing: { after: SUB_LINE.after },
        // keep the sub-line glued to the first bullet that follows it, so an
        // entry's heading/date/sub-line never get separated from all its content.
        keepNext: true,
        children: [new TextRun({
          text, font: FONT, size: SUB_LINE.size,
          italics: SUB_LINE.italic, color: SUB_LINE.color,
        })],
      }));
      continue;
    }

    if (trimmed.startsWith('- ')) {
      const text = trimmed.slice(2);
      paragraphs.push(new Paragraph({
        numbering: { reference: NUMBERING_REFERENCE, level: 0 },
        spacing: { after: BULLET_RUN.after, line: BULLET_RUN.line },
        children: parseInlineRuns(text, { font: FONT, size: BULLET_RUN.size, color: BULLET_RUN.color }),
      }));
      continue;
    }

    if (trimmed.startsWith('>> ')) {
      const text = trimmed.slice(3);
      paragraphs.push(new Paragraph({
        alignment: AlignmentType.RIGHT,
        spacing: { after: BODY_PARA.after, line: BODY_PARA.line },
        children: parseInlineRuns(text, { font: FONT, size: BODY_PARA.size, color: BODY_PARA.color }),
      }));
      continue;
    }

    // body paragraph
    paragraphs.push(new Paragraph({
      spacing: { after: BODY_PARA.after, line: BODY_PARA.line },
      children: parseInlineRuns(trimmed, { font: FONT, size: BODY_PARA.size, color: BODY_PARA.color }),
    }));
  }

  // A cover letter has no "# Name" line (it's a plain body of paragraphs, per
  // applications.md's cover-letter shape) — that's valid, not an error. Only an
  // EMPTY document (no paragraphs produced at all) is a real problem.
  void sawName;
  if (paragraphs.length === 0) {
    throw new Error('markdown source produced no content — is the file empty?');
  }
  return paragraphs;
}

function buildDocument(paragraphs) {
  return new Document({
    numbering: {
      config: [{
        reference: NUMBERING_REFERENCE,
        levels: [{
          level: 0,
          format: LevelFormat.BULLET,
          text: BULLET_GLYPH,
          alignment: AlignmentType.LEFT,
          style: {
            run: { font: FONT, size: BULLET_RUN.size, color: BULLET_RUN.color },
            paragraph: { indent: BULLET_INDENT },
          },
        }],
      }],
    },
    sections: [{
      properties: {
        page: {
          margin: {
            top: MARGIN_TWIPS_V, bottom: MARGIN_TWIPS_V,
            left: MARGIN_TWIPS, right: MARGIN_TWIPS,
          },
        },
      },
      children: paragraphs,
    }],
  });
}

async function main() {
  const [, , inputPath, outputPath] = process.argv;
  if (!inputPath || !outputPath) {
    console.error('Usage: node scripts/build-cv.js <input.md> <output.docx>');
    process.exit(1);
  }
  const mdText = fs.readFileSync(inputPath, 'utf-8');
  const paragraphs = parseMarkdown(mdText);
  const doc = buildDocument(paragraphs);
  const buffer = await Packer.toBuffer(doc);
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, buffer);
  console.log(`Built ${outputPath} (${paragraphs.length} paragraphs)`);
}

if (require.main === module) {
  main().catch((err) => {
    console.error(err);
    process.exit(1);
  });
}

module.exports = { parseMarkdown, buildDocument, parseInlineRuns };

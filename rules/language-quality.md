# language-quality.md: writing correct prose in the language of the posting

*Owns: grammar, register and spelling correctness for every piece of prose this project writes in a language that is not the owner's strongest: cover letters, CV lines, portal answers, draft replies.
`applications.md` owns structure (four paragraphs, salutation choice, what a letter may say), `cv-build.md` owns layout; this file owns whether the language itself is correct.*

## What this file does not decide

- **Never claim a language level above the one in `profile/profile.json` as a stated skill, anywhere, on any document.** The Languages line is an honest fact about the owner.
- Letter structure and salutation choice (`applications.md`), layout and section names (`cv-build.md`), the convention of the host country (`regions/<code>/cv-conventions.md`).

## The standard: correct, exact, professional: no exception for a lower own level

The CV and cover-letter text itself is always written in flawless, professional-quality language, whatever the owner's own level is. The level on the Languages line is a separate fact; it does not mean the
*document* should be written down to that level or hedge toward simpler language "for consistency". A written application is a work product, not a live proficiency demonstration. Every sentence gets the
full pass below, every time, with the goal of zero errors, not "good enough for a speaker of that level".

If you are not confident that a sentence is correct in that language, say so to the owner and offer the nearest sentence you are sure of; never ship an unchecked guess.

## Formality and spelling, in any language

- Use the formal register of the language and country for an application (the formal "you" form where the language has one), no contractions or slang, no filler words.
- Use the proper letters of the language (accents, umlauts, cedillas, special characters). Never let an ASCII transliteration used in a tracker id or a filename (`Qualitaetskontrolle`) leak into document text.
- Follow the standard variety (for English: American spelling for the U.S., British for the UK and Ireland; for German: standard, not Swiss, unless the posting is Swiss).
- Compound words, capitalisation, number and date formats follow the language, not English habit.

## Per-language checklists

| Language | Checklist |
|---|---|
| German | `rules/languages/de.md` |
| any other | none shipped: when the owner's search needs documents in another language, `/region` writes `profile/language-<code>.md` with the same shape (noun/gender rules, verb position or agreement, case or particles, register, common non-native mistakes, a short list of correct stock phrases for a letter) from authoritative grammar sources, and this file points to it |

## Before shipping any paragraph

Two passes, neither replacing the other:

1. **Manual.** Walk the language's checklist line by line against the actual draft, not a general impression of whether it "sounds right". Check the mistakes that actually happen most often in that language first.
2. **Mechanical, standalone, optional.** `python scripts/lang_check.py <file.md>` sends the text to the public LanguageTool service and lists grammar and spelling hits. It sends the file's text to a third party: use it on
   drafts only, never on anything containing an employer's confidential material. Read every hit with skepticism: LanguageTool has false positives on names, jargon and job titles; it is a second opinion, not a gate
   (`ship-package.sh` deliberately does not call it).

The anti-AI checker (`scripts/aicheck.py`) runs in English-tuned patterns; for other languages rely on the manual pass and keep the same principles (no filler, no inflated vocabulary, varied rhythm, no question marks in a letter).

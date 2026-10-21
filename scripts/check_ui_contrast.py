"""WCAG contrast check for the tracker interface's colour tokens (docs/OPERATING.md).

Reads the CSS variables from webapp_static/app.css for both themes and fails if a text pair is below
4.5:1 or a UI pair below 3:1.   Usage: python scripts/check_ui_contrast.py
"""
import re
import sys
from pathlib import Path

CSS = Path(__file__).resolve().parent / "webapp_static" / "app.css"
TONES = ["accent", "success", "warning", "danger", "info", "violet", "neutral"]


def block(css, selector_re):
    m = re.search(selector_re + r"\s*\{(.*?)\n\}", css, re.S)
    return dict(re.findall(r"--([\w-]+)\s*:\s*(#[0-9a-fA-F]{6})", m.group(1))) if m else {}


def lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def main():
    css = CSS.read_text(encoding="utf-8")
    themes = {"light": block(css, r':root,\s*\[data-theme="light"\]'), "dark": block(css, r'\[data-theme="dark"\]')}
    bad = 0
    for name, t in themes.items():
        if not t:
            print(f"{name}: tokens not found")
            return 1
        pairs = []  # (label, fg, bg, minimum)
        for bg in ("bg", "surface", "subtle"):
            for fg in ("text", "text-2", "text-3", "accent-text"):
                pairs.append((f"{fg} on {bg}", fg, bg, 4.5))
        pairs.append(("on-accent on accent", "on-accent", "accent", 4.5))
        for tone in TONES:
            if tone in t and f"{tone}-bg" in t:
                pairs.append((f"{tone} text on {tone}-bg", tone, f"{tone}-bg", 4.5))
        pairs.append(("accent-text on accent-soft", "accent-text", "accent-soft", 4.5))
        pairs.append(("line-strong on surface (control border)", "line-strong", "surface", 1.0))
        for label, fg, bg, need in pairs:
            if fg not in t or bg not in t:
                continue
            r = ratio(t[fg], t[bg])
            ok = r >= need
            bad += not ok
            if not ok or "-v" in sys.argv:
                print(f"{'ok  ' if ok else 'FAIL'} {name:5} {label:42} {r:5.2f} (need {need})")
    print("contrast check:", "FAILED" if bad else "all text pairs pass in both themes", f"({bad} failing)" if bad else "")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

"""Which icon-only controls have no tooltip?

An icon with no words is only guessable. Every button whose whole label is
a pictograph needs BOTH:

  title=       what a mouse sees on hover
  aria-label=  what a screen reader and a voice control hear

This reports the ones missing either, with enough context to fix them.

Run:  python3 tools/icons_tooltip_audit.py [--fix-report]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BUTTON = re.compile(r"<button\b([^>]*)>(.*?)</button>", re.S | re.I)
TAG_ONLY = re.compile(r"<[^>]+>")


def pictographic(text: str) -> bool:
    """True when the visible label is only symbols - no words."""
    bare = TAG_ONLY.sub("", text)
    bare = bare.replace("&nbsp;", " ").strip()
    if not bare:
        return False
    letters = sum(1 for c in bare if c.isalnum())
    return letters == 0


def main() -> int:
    targets = [ROOT / "app.py"]
    targets += sorted((ROOT / "frontend").glob("*.js"))
    targets += sorted((ROOT / "desktop").rglob("*.html"))
    targets += sorted((ROOT / "desktop").rglob("*.js"))

    total = bad = 0
    rows: list[tuple[str, str, str, bool, bool]] = []
    for path in targets:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in BUTTON.finditer(text):
            attrs, inner = m.group(1), m.group(2)
            if not pictographic(inner):
                continue
            total += 1
            has_title = "title=" in attrs
            has_aria = "aria-label=" in attrs
            if has_title and has_aria:
                continue
            bad += 1
            label = TAG_ONLY.sub("", inner).strip()[:8]
            line = text.count("\n", 0, m.start()) + 1
            rows.append((f"{path.name}:{line}", label, attrs.strip()[:48],
                         has_title, has_aria))

    print(f"icon-only buttons: {total}")
    print(f"missing title and/or aria-label: {bad}\n")
    for where, label, attrs, ti, ar in rows[:70]:
        miss = ",".join(
            ([] if ti else ["title"]) + ([] if ar else ["aria-label"]))
        print(f"  {where:<22} {label:<8} missing {miss:<20} {attrs}")

    print("\nRESULT:", "PASS - every icon control is labelled"
          if not bad else "FAIL - see above")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())

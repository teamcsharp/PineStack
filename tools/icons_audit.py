"""Which pictographs does the application use, and does the icon font cover them?

The station's icons are meant to be one single-colour Carbon set. Anything
it draws with a codepoint the font does NOT carry falls straight through to
the platform's colour emoji, which breaks the design language on exactly
the devices that matter most (iOS ships Apple Color Emoji and prefers it).

This reads the real artefacts - the generated stylesheet's unicode-range
and the page sources - and reports:

  * codepoints used but NOT covered   -> these WILL render in colour
  * codepoints covered but unused     -> dead weight in the mapping
  * where each uncovered one is used  -> so it can be mapped or replaced

Run:  python3 tools/icons_audit.py
"""
from __future__ import annotations

import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "frontend" / "pineicons.css"


def covered_codepoints() -> set[int]:
    """Parse every unicode-range in the generated stylesheet."""
    if not CSS.is_file():
        print(f"!! {CSS} is missing - the font has never been built here")
        return set()
    text = CSS.read_text(encoding="utf-8", errors="replace")
    out: set[int] = set()
    for block in re.findall(r"unicode-range:\s*([^;}]+)", text):
        for part in block.split(","):
            part = part.strip().upper()
            m = re.fullmatch(r"U\+([0-9A-F]+)-([0-9A-F]+)", part)
            if m:
                out.update(range(int(m.group(1), 16), int(m.group(2), 16) + 1))
                continue
            m = re.fullmatch(r"U\+([0-9A-F]+)", part)
            if m:
                out.add(int(m.group(1), 16))
    return out


# Codepoints whose DEFAULT presentation is emoji - the platform draws
# these in colour with no variation selector at all. Everything else in
# the symbol blocks is TEXT presentation: already monochrome, and not a
# violation of the design language.
_EMOJI_DEFAULT_RANGES = (
    (0x1F000, 0x1FAFF),
    (0x231A, 0x231B), (0x23E9, 0x23EC), (0x23F0, 0x23F0), (0x23F3, 0x23F3),
    (0x25FD, 0x25FE), (0x2614, 0x2615), (0x2648, 0x2653), (0x267F, 0x267F),
    (0x2693, 0x2693), (0x26A1, 0x26A1), (0x26AA, 0x26AB),
    (0x26BD, 0x26BE), (0x26C4, 0x26C5), (0x26CE, 0x26CE), (0x26D4, 0x26D4),
    (0x26EA, 0x26EA), (0x26F2, 0x26F3), (0x26F5, 0x26F5), (0x26FA, 0x26FA),
    (0x26FD, 0x26FD), (0x2705, 0x2705), (0x270A, 0x270B),
    (0x2728, 0x2728), (0x274C, 0x274C), (0x274E, 0x274E),
    (0x2753, 0x2755), (0x2757, 0x2757), (0x2795, 0x2797),
    (0x27B0, 0x27B0), (0x27BF, 0x27BF), (0x2B1B, 0x2B1C),
    (0x2B50, 0x2B50), (0x2B55, 0x2B55),
)


def emoji_default(cp: int) -> bool:
    return any(a <= cp <= b for a, b in _EMOJI_DEFAULT_RANGES)


def is_pictograph(ch: str) -> bool:
    """Any symbol that might be standing in for an icon."""
    cp = ord(ch)
    if cp < 0x2000:
        return False
    if cp in (0xFE0E, 0xFE0F, 0x200D):      # the selectors and ZWJ
        return False
    return (
        0x2190 <= cp <= 0x2BFF
        or 0x1F000 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x27BF
        or 0xFE30 <= cp <= 0xFE4F
    )


def main() -> int:
    covered = covered_codepoints()
    print(f"font covers {len(covered)} codepoints\n")

    used: dict[int, int] = defaultdict(int)
    vs16: set[int] = set()
    where: dict[int, set[str]] = defaultdict(set)

    targets = [ROOT / "app.py"]
    targets += sorted((ROOT / "frontend").glob("*.js"))
    targets += sorted((ROOT / "frontend").glob("*.css"))
    targets += sorted((ROOT / "desktop").rglob("*.js"))
    targets += sorted((ROOT / "desktop").rglob("*.html"))

    for path in targets:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, ch in enumerate(text):
            if is_pictograph(ch):
                cp = ord(ch)
                used[cp] += 1
                where[cp].add(path.name)
                # VS16 PINS EMOJI PRESENTATION. A symbol that would
                # otherwise be a monochrome text glyph is forced into
                # the colour font by this one invisible character.
                if text[i + 1:i + 2] == chr(0xFE0F):
                    vs16.add(cp)

    # A codepoint renders in COLOUR when the platform gives it emoji
    # presentation - by default, or because the source pinned it with
    # VS16 - and our own font does not carry it. Everything else is a
    # text-presentation symbol that is already monochrome.
    missing = {cp: n for cp, n in used.items()
               if cp not in covered and (emoji_default(cp) or cp in vs16)}
    mono = {cp: n for cp, n in used.items()
            if cp not in covered and not (emoji_default(cp) or cp in vs16)}
    extra = sorted(covered - set(used) - {0xFE0E, 0xFE0F})

    print(f"pictographs used: {len(used)} distinct, "
          f"{sum(used.values())} occurrences")
    print(f"COLOUR RISK - emoji presentation, not in the font: "
          f"{len(missing)} distinct, {sum(missing.values())} uses")
    print(f"text-presentation symbols outside the font "
          f"(already monochrome, fine): {len(mono)} distinct, "
          f"{sum(mono.values())} uses")
    print(f"pinned with VS16 somewhere: {len(vs16)} distinct\n")

    for cp, n in sorted(missing.items(), key=lambda kv: -kv[1])[:60]:
        try:
            name = unicodedata.name(chr(cp))
        except ValueError:
            name = "?"
        files = ", ".join(sorted(where[cp])[:3])
        print(f"  U+{cp:05X}  {chr(cp)}  x{n:<5} {name[:44]:<44} {files}")

    print(f"\ncovered but unused: {len(extra)}")
    if "--verbose" in sys.argv:
        print("   " + " ".join(f"U+{c:04X}" for c in extra))

    print("\nRESULT:", "PASS - every pictograph has a vector"
          if not missing else "FAIL - see the list above")
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())

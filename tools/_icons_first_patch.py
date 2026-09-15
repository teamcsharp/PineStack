"""The Carbon icon font was declared LAST, so iOS never reached it.

The audit says every emoji-presentation codepoint the application uses is
already in the font - 0 colour-risk gaps. The glyphs have been there all
along. They were losing a font-fallback race:

  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif, PineIcons

For a codepoint like U+1F525 none of the first four families has a glyph,
so the browser falls back - and on iOS the fallback CoreText reaches for
is Apple Color Emoji, which it inserts ahead of the tail of the declared
list. The one family that WOULD have drawn a monochrome vector was behind
it. Hence colour emoji on a phone and correct icons on the desktop, from
identical markup.

Putting PineIcons FIRST is safe, and specifically because of how the font
was built: its @font-face carries a `unicode-range` covering only the
pictographs. A family with a unicode-range is never consulted for a
codepoint outside it, so Latin text falls straight through to system-ui
exactly as before. Only the icons change hands.

VS16 (U+FE0F) is stripped from icon strings at the same time. That one
invisible character PINS emoji presentation, which is a direct instruction
to the platform to use the colour font, and it can beat even a
first-position family. The font covers the base codepoints; it does not
need the selector, and the selector is the thing arguing against it.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Where a font-family list begins inside a `font:` shorthand: after the
# last size-ish token (12px, 15px/1.5, 700, italic, 1.65).
SIZEY = re.compile(r"^(?:normal|italic|oblique|small-caps|bold|bolder|"
                   r"lighter|[1-9]00|[\d.]+(?:px|pt|em|rem|%)?"
                   r"(?:/[\d.]+(?:px|pt|em|rem|%)?)?)$", re.I)

DECL = re.compile(r"(font(?:-family)?\s*:\s*)([^;}\n]*?PineIcons[^;}\n]*)",
                  re.I)


def reorder(value: str) -> str:
    """Move PineIcons to the head of the family list in one declaration."""
    parts = [p.strip() for p in value.split(",")]
    parts = [p for p in parts if p and p.lower() != "pineicons"]
    if not parts:
        return "PineIcons"
    # Find where the families start (a `font:` shorthand has size tokens
    # glued to the first family by the space, e.g. "15px/1.5 system-ui").
    head = parts[0]
    bits = head.split()
    cut = 0
    for i, tok in enumerate(bits):
        if not SIZEY.match(tok):
            cut = i
            break
    else:
        cut = len(bits)
    prefix = " ".join(bits[:cut])
    first_family = " ".join(bits[cut:])
    rebuilt = ([first_family] if first_family else []) + parts[1:]
    lead = (prefix + " ") if prefix else ""
    return lead + ", ".join(["PineIcons"] + rebuilt)


def fix_text(text: str) -> tuple[str, int]:
    n = 0

    def one(m):
        nonlocal n
        new = reorder(m.group(2))
        if new == m.group(2):
            return m.group(0)
        n += 1
        return m.group(1) + new

    return DECL.sub(one, text), n


def main() -> None:
    targets = [ROOT / "app.py"]
    targets += sorted((ROOT / "frontend").glob("*.css"))
    targets += sorted((ROOT / "frontend").glob("*.js"))
    targets += sorted((ROOT / "desktop").rglob("*.css"))
    targets += sorted((ROOT / "desktop").rglob("*.html"))
    targets += sorted((ROOT / "desktop").rglob("*.js"))

    total_decls = total_vs16 = 0
    for path in targets:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new, n = fix_text(text)
        # Strip the emoji-presentation selector. It only ever argues for
        # the colour font, and the icon font covers the base codepoints.
        vs = new.count("️")
        if vs:
            new = new.replace("️", "")
        if new != text:
            path.write_text(new, encoding="utf-8")
            total_decls += n
            total_vs16 += vs
            print(f"  {path.relative_to(ROOT)}: {n} stack(s), {vs} VS16")

    print(f"\nreordered {total_decls} font declarations, "
          f"stripped {total_vs16} VS16 selectors")


if __name__ == "__main__":
    main()

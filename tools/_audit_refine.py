"""Refine the icon audit to report REAL colour risk, not every symbol."""
import pathlib

p = pathlib.Path("tools/icons_audit.py")
s = p.read_text()
o = s

OLD_FN = (
    'def is_pictograph(ch: str) -> bool:\n'
    '    """A character the platform would draw as a colour emoji."""\n'
    '    cp = ord(ch)\n'
    '    if cp < 0x2000:\n'
    '        return False\n'
    '    if cp in (0xFE0E, 0xFE0F, 0x200D):      # the selectors and ZWJ\n'
    '        return False\n'
    '    return (\n'
    '        0x2190 <= cp <= 0x2BFF          # arrows, symbols, dingbats\n'
    '        or 0x1F000 <= cp <= 0x1FAFF     # the emoji planes\n'
    '        or 0x2600 <= cp <= 0x27BF\n'
    '        or 0xFE30 <= cp <= 0xFE4F\n'
    '    )'
)
assert s.count(OLD_FN) == 1, "is_pictograph anchor"

NEW_FN = '''# Codepoints whose DEFAULT presentation is emoji - the platform draws
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
    )'''
s = s.replace(OLD_FN, NEW_FN, 1)

s = s.replace(
    "    used: dict[int, int] = defaultdict(int)",
    "    used: dict[int, int] = defaultdict(int)\n    vs16: set[int] = set()", 1)

OLD_SCAN = (
    "        for ch in text:\n"
    "            if is_pictograph(ch):\n"
    "                used[ord(ch)] += 1\n"
    "                where[ord(ch)].add(path.name)"
)
assert s.count(OLD_SCAN) == 1, "scan anchor"
NEW_SCAN = (
    "        for i, ch in enumerate(text):\n"
    "            if is_pictograph(ch):\n"
    "                cp = ord(ch)\n"
    "                used[cp] += 1\n"
    "                where[cp].add(path.name)\n"
    "                # VS16 PINS EMOJI PRESENTATION. A symbol that would\n"
    "                # otherwise be a monochrome text glyph is forced into\n"
    "                # the colour font by this one invisible character.\n"
    "                if text[i + 1:i + 2] == chr(0xFE0F):\n"
    "                    vs16.add(cp)"
)
s = s.replace(OLD_SCAN, NEW_SCAN, 1)

OLD_MISS = ("    missing = {cp: n for cp, n in used.items() "
            "if cp not in covered}")
assert s.count(OLD_MISS) == 1, "missing anchor"
NEW_MISS = (
    "    # A codepoint renders in COLOUR when the platform gives it emoji\n"
    "    # presentation - by default, or because the source pinned it with\n"
    "    # VS16 - and our own font does not carry it. Everything else is a\n"
    "    # text-presentation symbol that is already monochrome.\n"
    "    missing = {cp: n for cp, n in used.items()\n"
    "               if cp not in covered and (emoji_default(cp) or cp in vs16)}\n"
    "    mono = {cp: n for cp, n in used.items()\n"
    "            if cp not in covered and not (emoji_default(cp) or cp in vs16)}"
)
s = s.replace(OLD_MISS, NEW_MISS, 1)

OLD_PRINT = ('    print(f"NOT COVERED (these render in colour): {len(missing)} distinct, "\n'
             '          f"{sum(missing.values())} occurrences\\n")')
assert s.count(OLD_PRINT) == 1, "print anchor"
NEW_PRINT = (
    '    print(f"COLOUR RISK - emoji presentation, not in the font: "\n'
    '          f"{len(missing)} distinct, {sum(missing.values())} uses")\n'
    '    print(f"text-presentation symbols outside the font "\n'
    '          f"(already monochrome, fine): {len(mono)} distinct, "\n'
    '          f"{sum(mono.values())} uses")\n'
    '    print(f"pinned with VS16 somewhere: {len(vs16)} distinct\\n")'
)
s = s.replace(OLD_PRINT, NEW_PRINT, 1)

assert s != o
p.write_text(s)
print("audit refined")

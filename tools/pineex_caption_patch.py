#!/usr/bin/env python3
"""[pineex-caption] The supercut version's caption reads SUPERCUT and the product the hour sold. 2026-10-06.

The operator, asked what the bottom of a pineEX render's supercut version should say: "SUPERCUT + the product".
The product is what the hour's {product} / {offer} roll put into the filled direction ('the product "Name" -
pitch'); an hour whose offer rolled a feature names the feature; an hour that sold nothing in words names the
station.

Edits: app.py h3_supercut_caption (+ h3_supercut_product, H3_SUPERCUT_CAPTION_WORD); the caption tests in
tests/test_pineex_supercut_2026_10_06.py read the new wording; tools/pineex_supercut_patch.py carries the new
caption in its own NEW text, so it reads the tree as applied again.

Usage:  pineex_caption_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        pineex_caption_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

CAPTION_OLD = '''def h3_supercut_caption(rec: Any) -> list[str]:
    """What the bottom of the copy says: the line the render sings (the hour's
    speech after filling, else the record it sings to) and the station - the
    station once, so a line that already ends on its name is not doubled."""
    words = rec.get("h3_prompts") if isinstance(rec, dict) and isinstance(rec.get("h3_prompts"), dict) else {}
    line = " ".join(str(words.get("speech") or (rec or {}).get("speech") or words.get("record") or "").split())
    out = [line[:160]] if line else []
    if not line or not line.rstrip(" .!?").lower().endswith(H3_SUPERCUT_STATION.lower()):
        out.append(H3_SUPERCUT_STATION)
    return out
'''
CAPTION_NEW = '''H3_SUPERCUT_CAPTION_WORD = "SUPERCUT"      # [pineex-caption] the first line - "SUPERCUT + the product" (the operator)


def h3_supercut_product(rec: Any) -> str:
    """[pineex-caption] What the hour sold, as the filled direction carries it: the {product} / {offer} roll
    ('the product "Name" - pitch'), else the rolled feature ('the Pine Box feature "Name"'), else the station."""
    words = rec.get("h3_prompts") if isinstance(rec, dict) and isinstance(rec.get("h3_prompts"), dict) else {}
    text = " ".join(str(words.get("direction") or words.get("goal") or (rec or {}).get("prompt") or "").split())
    for pattern in (r'the product "([^"]{1,80})"', r'the Pine Box feature "([^"]{1,80})"'):
        found = re.search(pattern, text)
        if found and found.group(1).strip():
            return found.group(1).strip()
    return H3_SUPERCUT_STATION


def h3_supercut_caption(rec: Any) -> list[str]:
    """[pineex-caption] What the bottom of the copy says: SUPERCUT, then the product the hour sold
    ("SUPERCUT + the product" - the operator, 2026-10-06)."""
    return [H3_SUPERCUT_CAPTION_WORD, h3_supercut_product(rec)[:80]]
'''

TEST_OLD = '''    def test_the_caption_is_the_sung_line_and_the_station_once(self):
        caption = self.ns["h3_supercut_caption"]
        self.assertEqual(caption(pineex_row()), ["Dance all night to the record. Pine Box FM."],
                         "a line that ends on the station is not doubled")
        self.assertEqual(caption(pineex_row(speech="Hello   there,\\nlisteners")), ["Hello there, listeners", "Pine Box FM"])
        row = pineex_row(speech="")
        row["h3_prompts"]["speech"] = ""
        self.assertEqual(caption(row), ["Blue Monday", "Pine Box FM"], "no line: the record it sings to")
        row["h3_prompts"]["record"] = ""
        self.assertEqual(caption(row), ["Pine Box FM"])
        self.assertEqual(caption({}), ["Pine Box FM"])
'''
TEST_NEW = '''    def test_the_caption_is_supercut_and_the_product(self):
        """[pineex-caption] "SUPERCUT + the product" (the operator)."""
        caption = self.ns["h3_supercut_caption"]
        row = pineex_row()
        row["h3_prompts"]["direction"] = ('A music video. What is sold tonight is the product "Pine Box FM Vinyl Record Holder" '
                                          '- it keeps the records upright. Sing it.')
        self.assertEqual(caption(row), ["SUPERCUT", "Pine Box FM Vinyl Record Holder"], "the product the hour sold")
        row["h3_prompts"]["direction"] = 'Tonight it is the Pine Box feature "One press builds the PineTab" [tablet-update-ask] - pitch it.'
        self.assertEqual(caption(row), ["SUPERCUT", "One press builds the PineTab"], "a feature when the offer rolled one")
        self.assertEqual(caption(pineex_row()), ["SUPERCUT", "Pine Box FM"], "nothing sold in the words: the station")
        self.assertEqual(caption({}), ["SUPERCUT", "Pine Box FM"])
'''
BURN_OLD = '''        self.assertEqual(self.burns[0][2], ["Dance all night to the record. Pine Box FM."])
'''
BURN_NEW = '''        self.assertEqual(self.burns[0][2], ["SUPERCUT", "Pine Box FM"])   # [pineex-caption]
'''

EDITS = {
    "app.py": [
        ("h3_supercut_caption: SUPERCUT + the product", CAPTION_OLD, CAPTION_NEW, 1),
    ],
    "tests/test_pineex_supercut_2026_10_06.py": [
        ("the caption test reads the new wording", TEST_OLD, TEST_NEW, 1),
        ("the burn expectation reads the new wording", BURN_OLD, BURN_NEW, 1),
    ],
    # the earlier tool's own NEW text carries the old caption: it must read the tree as applied again
    "tools/pineex_supercut_patch.py": [
        ("the supercut patch tool carries the new caption", CAPTION_OLD, CAPTION_NEW, 1),
    ],
}


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        if not path.exists():
            print("%-46s MISSING FILE" % name)
            missing = True
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, want in edits:
            if text.count(new) >= want:
                print("%-78s applied" % label[:78])
                continue
            n = text.count(old)
            if n == want:
                print("%-78s ready" % label[:78])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-78s MISSING (anchor count %d, wanted %d)" % (label[:78], n, want))
                missing = True
        if changed:
            plans.append((path, text, mode, bom))
    if missing:
        print("anchors missing - nothing applied")
        return 1
    if not ready:
        print("every edit reads applied")
        return 2
    if argv[1] == "--check":
        print("ready to apply")
        return 0
    for path, text, mode, bom in plans:
        out = text.replace("\n", "\r\n") if mode == "crlf" else text
        data = out.encode("utf-8")
        if bom:
            data = b"\xef\xbb\xbf" + data
        tmp = path.with_suffix(path.suffix + ".pineexcap.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

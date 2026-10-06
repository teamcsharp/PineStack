#!/usr/bin/env python3
"""[book-cover-box] A cover is a tall box, whatever the engine thinks of buttons. 2026-10-06.

Inbox #1587: "I'm not able to see the covers of the books... I want it formatted more like the second
image" (Apple Books: a grid of whole, tall covers, title and author beneath). The [book-shelf] grid
was built for that, yet every cover came out a 36 px strip. Measured with the desk's own stylesheets
(tests/probe_book_cover_2026_10_06.cjs): the cover face is a <button> with aspect-ratio 5/7, and
Chromium 138 ignores aspect-ratio on a button - the box takes the button's own line height. The box
is now sized by its bottom padding (140% of its width = 5:7), which no button quirk can shrink, and
the picture inside is fitted whole (object-fit: contain) on the shelf's own dark gradient, so no cover
is ever cut. The grid's tiles grow to at least 200 px, closer to the reference. Both copies of
book-mode.css.

Usage:  book_cover_box_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        book_cover_box_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_OLD = ".bm-card .bm-cover{position:relative;display:block;width:100%;aspect-ratio:5/7;flex-shrink:0;padding:0;overflow:hidden;"
BASE_NEW = ".bm-card .bm-cover{position:relative;display:block;width:100%;height:0;padding:0 0 140%;box-sizing:content-box;min-height:0;flex-shrink:0;overflow:hidden;"
GRID_OLD = ".bm-books{display:grid;grid-template-columns:repeat(auto-fill,minmax(176px,1fr));gap:30px 24px;"
GRID_NEW = ".bm-books{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:34px 28px;"
IMG_OLD = ".bm-cover img{object-fit:cover;background:#fff}"
IMG_NEW = "/* [book-cover-box] the whole cover, never cut; the gradient behind it is the shelf */\n.bm-cover img{object-fit:contain;background:transparent}"
CSS = [
    ("the cover box is sized by its padding, 5:7", BASE_OLD, BASE_NEW, "height:0;padding:0 0 140%;box-sizing:content-box;min-height:0;", 1),
    ("the grid's tiles grow to 200 px", GRID_OLD, GRID_NEW, "minmax(200px,1fr));gap:34px 28px;", 1),
    ("the picture is fitted whole", IMG_OLD, IMG_NEW, "/* [book-cover-box] the whole cover, never cut;", 1),
]
EDITS = {"desktop/renderer/book-mode.css": CSS, "app/src/main/assets/pine-views/book-mode.css": CSS}


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
            print("%-46s (not in this tree - skipped)" % name[-46:])
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, probe, count in edits:
            have = text.count(probe)
            have_old = text.count(old)
            if have == count and have_old == 0:
                state = "applied"
            elif have_old == count and have == 0:
                text = text.replace(old, new)
                state, changed = "ready", True
            else:
                state = "missing (anchor found %d, probe %d)" % (have_old, have)
            print("%-46s %-44s %s" % (name[-46:], label, state))
            if state == "ready":
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, bom, mode, changed))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, bom, mode, changed in plans:
        if not changed:
            continue
        body = (text.replace("\n", "\r\n") if mode == "crlf" else text).encode("utf-8")
        tmp = path.with_name(path.name + ".coverbox.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

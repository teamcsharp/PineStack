#!/usr/bin/env python3
"""[blocked-book] Install the blocked book beside the other runtimes. 2026-10-06.

One import and one install call in app.py; the module (blocked_book.py) answers
GET /api/blocked - every blocked case the station's ledgers hold, in one shape.

Usage:  blocked_book_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        blocked_book_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

OLD = '''import gazette_review_runtime
'''
NEW = '''import gazette_review_runtime
import blocked_book                                          # [blocked-book]
'''

INSTALL_OLD = '''gazette_review_runtime.install(app, globals())
'''
INSTALL_NEW = '''gazette_review_runtime.install(app, globals())
blocked_book.install(app, globals())                         # [blocked-book] GET /api/blocked
'''

EDITS = {"app.py": [
    ("the blocked book is imported", OLD, NEW, 1),
    ("...and installed beside the Gazette review", INSTALL_OLD, INSTALL_NEW, 1),
]}


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
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, want in edits:
            if text.count(new) >= want:
                print("%-72s applied" % label[:72])
                continue
            n = text.count(old)
            if n == want:
                print("%-72s ready" % label[:72])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-72s MISSING (anchor count %d, wanted %d)" % (label[:72], n, want))
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
        tmp = path.with_suffix(path.suffix + ".bbook.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

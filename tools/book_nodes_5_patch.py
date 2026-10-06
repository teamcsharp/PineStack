#!/usr/bin/env python3
"""[book-nodes-5] Stock-before-prose leaves a segment's window alone: its parts are stock already. 2026-10-06.

Measured at the 16:15 CST Book Time window, the first under [book-nodes-4]: the unheard sweep stood aside
26 times ("a segment's window owns the air"), and the window still went to a banked caller round (round
ytb2.md) - gap_kind_policy (#1022, stock before prose) swapped the sheet's book_time for a prepared call,
because Book Time is not on its list of prepared kinds, so the segment's door was never asked.

Edit (app.py): gap_kind_policy returns the kind untouched when it is a dynamic segment whose window owns the
air (dynamic_segment_window_owned: a part of its own not yet handed off, or a carry). The jam rule (#938)
keeps its power: a window stuck 1.5x past its minutes may still be displaced.

Usage:  book_nodes_5_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        book_nodes_5_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

GAP_OLD = '''    if (not kind or (kind in GAP_NOT_TALK
                     and not (kind == "track_talk"
                              and talk_is_incessant(dj)))):
        return kind, ""
    runway_left = max(0.0, float(_RADIO.get("resume_runway_until") or 0) - now)
'''
GAP_NEW = '''    if (not kind or (kind in GAP_NOT_TALK
                     and not (kind == "track_talk"
                              and talk_is_incessant(dj)))):
        return kind, ""
    # [book-nodes-5] A DYNAMIC SEGMENT'S WINDOW IS STOCK ALREADY. Book Time's parts and the supercut are
    # written and recorded ahead by their own writers; this policy knew only its own list of prepared
    # kinds, so on 10-06 at 16:15 CST it swapped the sheet's book_time for a banked call and the segment's
    # door was never asked. While the window holds a part of its own, the kind stands.
    if kind in ("book_time", "sfx_supercut"):
        _owned = globals().get("dynamic_segment_window_owned")
        if callable(_owned) and _owned():
            return kind, ""
    runway_left = max(0.0, float(_RADIO.get("resume_runway_until") or 0) - now)
'''

EDITS = {
    "app.py": [
        ("gap_kind_policy leaves an owned segment window alone", GAP_OLD, GAP_NEW, 1),
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
        tmp = path.with_suffix(path.suffix + ".booknodes5.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

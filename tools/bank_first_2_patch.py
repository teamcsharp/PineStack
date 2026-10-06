#!/usr/bin/env python3
"""[bank-first-2] The larder transport hands the round over as a READY round. 2026-10-06.

Measured after [bank-first] (restart 13:34): the sweep's first walk put a banked
banter round on the air - /api/debug/tasks showed its task in _banter_air ->
speak_turns -> _paged_settle for minutes - and the sweep's own account still read
"0 airings, waiting for a prior cupboard handoff". speak_turns fires on_handoff
only for a ready round (`ready_takes is not None`, app.py ~116493/~116610);
larder_round_air passed on_handoff and no ready_takes, so acceptance was never
credited, the pending handoff lasted the whole playout, and the 60 s handoff
timeout was armed against a round that was already airing. The shelf door
(_ready_shelf_air) passes ready_takes=_ready_round_takes(kind, row); the larder
transport now does the same, and marks the entry busy while it airs so no second
pick can take it.

Usage:  bank_first_2_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        bank_first_2_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

AIR_OLD = '''    _larder_save()
    pipeline_log("air", "a banked banter round goes out of turn off the larder "
                        "(%d left) [bank-first]" % len(_LARDER))
    gap_round_flag("banked")                                             # #1022
    return await _banter_air(entry, track, on_handoff=on_handoff)
'''
AIR_NEW = '''    _larder_save()
    pipeline_log("air", "a banked banter round goes out of turn off the larder "
                        "(%d left) [bank-first]" % len(_LARDER))
    gap_round_flag("banked")                                             # #1022
    # [bank-first-2] as a READY round: speak_turns credits on_handoff only when ready_takes is given
    # (the shelf door's road), and the entry is busy while it airs so no second pick takes it.
    _takes = _ready_round_takes("banter", entry)
    _READY_SHELF_BUSY.add(id(entry))
    try:
        return await _banter_air(entry, track, ready_takes=_takes or None, on_handoff=on_handoff)
    finally:
        _READY_SHELF_BUSY.discard(id(entry))
'''

EDITS = {
    "app.py": [
        ("the larder transport airs a ready round and holds it busy", AIR_OLD, AIR_NEW, 1),
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
        tmp = path.with_suffix(path.suffix + ".bankfirst2.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

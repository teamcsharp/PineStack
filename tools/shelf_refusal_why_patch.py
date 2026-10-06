#!/usr/bin/env python3
"""[shelf-why] A named row the shelf door refuses says WHICH test refused it. 2026-10-06.

After [bank-first] the sweep's own account read "gazette_review refused: the shelf
would not give up the row that was picked" and "a painting round refused: ..." -
four each in ten walks - and nothing said why: _ready_shelf_row's eligible() has
four tests (busy, a lifecycle lease, no takes, neither rescue nor the window) and
answered a bare False. The takes census could not tell either (its "the row
itself is not ready" is dominated by the routine shelf walks). So the refusal
now names the test, through the same _READY_SHELF_WHY the sweep already reads,
and the sweep's reason line carries it.

Usage:  shelf_refusal_why_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        shelf_refusal_why_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

ELIGIBLE_OLD = '''    def eligible(row: Any) -> bool:
        if id(row) in _READY_SHELF_BUSY:
            return False
        if (_pantry_lifecycle() and _pantry_lifecycle().enabled
                and float((row.get("pantry_lifecycle") or {}).get("lease_until") or 0) > time.time()):
            return False
        takes = _ready_round_takes(kind, row)
        if not takes:
            return False
        # #1260: finished radio nobody has heard is not held by a sheet
        # that is not standing on its road.
        return (rescue or unheard_free(kind, row)
                or _ready_round_fits(kind, takes, window))
'''
ELIGIBLE_NEW = '''    def eligible(row: Any) -> bool:
        if id(row) in _READY_SHELF_BUSY:
            _READY_SHELF_REFUSED[0] = "it is busy (another transport holds it)"    # [shelf-why]
            return False
        if (_pantry_lifecycle() and _pantry_lifecycle().enabled
                and float((row.get("pantry_lifecycle") or {}).get("lease_until") or 0) > time.time()):
            _READY_SHELF_REFUSED[0] = "the lifecycle holds a lease on it (%ds left)" % int(
                float((row.get("pantry_lifecycle") or {}).get("lease_until") or 0) - time.time())   # [shelf-why]
            return False
        takes = _ready_round_takes(kind, row)
        if not takes:
            _READY_SHELF_REFUSED[0] = "it has no takes the door accepts"             # [shelf-why]
            return False
        # #1260: finished radio nobody has heard is not held by a sheet
        # that is not standing on its road.
        if rescue or unheard_free(kind, row) or _ready_round_fits(kind, takes, window):
            return True
        _READY_SHELF_REFUSED[0] = "it does not fit the entry on air and may not go out of turn"   # [shelf-why]
        return False
'''

PICK_OLD = '''    if pick is not None:
        if not any(held is pick for held in shelf_rows(kind)):
            return None
        return pick if eligible(pick) else None
'''
PICK_NEW = '''    if pick is not None:
        if not any(held is pick for held in shelf_rows(kind)):
            _READY_SHELF_REFUSED[0] = "it is not on this road's shelf"               # [shelf-why]
            return None
        _READY_SHELF_REFUSED[0] = ""
        return pick if eligible(pick) else None
'''

WHY_OLD = '''_READY_SHELF_WHY: dict[str, Any] = {"at": 0.0, "kind": "", "why": ""}
'''
WHY_NEW = '''_READY_SHELF_WHY: dict[str, Any] = {"at": 0.0, "kind": "", "why": ""}
_READY_SHELF_REFUSED: list[str] = [""]           # [shelf-why] which test refused the last named row
'''

NO_OLD = '''    row = _ready_shelf_row(kind, rescue, pick)      # #1168/#1260
    if row is None:
        return _shelf_no(kind, "the shelf would not give up the row that "
                               "was picked")                      # #1304
'''
NO_NEW = '''    row = _ready_shelf_row(kind, rescue, pick)      # #1168/#1260
    if row is None:
        return _shelf_no(kind, "the shelf would not give up the row that "
                               "was picked"
                         + ((": " + _READY_SHELF_REFUSED[0]) if pick is not None and _READY_SHELF_REFUSED[0] else ""))   # #1304 [shelf-why]
'''

EDITS = {
    "app.py": [
        ("the refused-test slot", WHY_OLD, WHY_NEW, 1),
        ("eligible() names the test that refused", ELIGIBLE_OLD, ELIGIBLE_NEW, 1),
        ("a named row not on the shelf says so", PICK_OLD, PICK_NEW, 1),
        ("the door's refusal carries the test", NO_OLD, NO_NEW, 1),
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
        tmp = path.with_suffix(path.suffix + ".shelfwhy.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

#!/usr/bin/env python3
"""[kitchen-finish] The finishing rooms skip what is finished. 2026-10-06.

Measured with the kitchen open (the station off, nothing leaving the shelves):
the pantry's rounds block builds `_waiting` lap by lap (row 0 of every round
shelf, then row 1, ...), pools the first RECORDING_POOL_MOST (6) rows that are
not ready and visits at most WAITING_VISITS_MOST (3) more, one round at a time.
Its "already ready - skip" test was `dialogue_row_ready(_kind, _e)` with the
ENTRY, and that predicate is written for the shelf ROW: 53 rows on the station
read ready by row and unready by entry (gallery 46, manager 3, gazette review 2,
mixtape 2). So finished rounds at the head of every list filled the pool and
the visit budget on every pass, and the rows behind them - 48 gazette reviews
with no chunk plan at all, written two days earlier - were never reached. On
air the heads leave as they air and the lists churn; off air nothing leaves,
and the kitchen starved its own backlog.

Three edits: the two pantry tests hand over the row; larder_prepare's early
return asks the entry-shaped predicates (tint ready and audio ready) that mean
"nothing left to make here".

Usage:  kitchen_finish_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        kitchen_finish_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

POOL_OLD = '''                        if (_e.get("preparing")
                                or dialogue_row_ready(_kind, _e)):
                            continue
'''
POOL_NEW = '''                        if (_e.get("preparing")
                                or dialogue_row_ready(_kind, _row)):   # [kitchen-finish] the ROW the predicate is written for
                            continue
'''

VISIT_OLD = '''                    if (_shelved.get("preparing")
                            or dialogue_row_ready(_kind, _shelved)):
                        continue
'''
VISIT_NEW = '''                    if (_shelved.get("preparing")
                            or dialogue_row_ready(_kind, _row)):       # [kitchen-finish] the ROW the predicate is written for
                        continue
'''

PREPARE_OLD = '''    if entry.get("prepared") and dialogue_row_ready(_pkind, entry):
        return False
'''
PREPARE_NEW = '''    if (entry.get("prepared") and dialogue_tint_ready(_pkind, entry)
            and dialogue_audio_ready(_pkind, entry)):   # [kitchen-finish] nothing left to make here
        return False
'''

EDITS = {"app.py": [
    ("the recording pool skips rows that are ready", POOL_OLD, POOL_NEW, 1),
    ("the one-at-a-time visits skip rows that are ready", VISIT_OLD, VISIT_NEW, 1),
    ("larder_prepare leaves a finished round alone", PREPARE_OLD, PREPARE_NEW, 1),
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
        tmp = path.with_suffix(path.suffix + ".kfinish.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

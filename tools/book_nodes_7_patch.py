#!/usr/bin/env python3
"""[book-nodes-7] The Book Time door keeps its own ledger: every ask, what it did, and the shelf's reason when it refused.

The 17:15 CST window on 10-06: the opening was ready (12 of 12 takes in the pantry at 17:13), the sweep stood
aside, stock-before-prose left the kind alone - and the window still went to an ad, a banter round and a call.
The door's log lines live in a 120-row ring that empties in ~40 s, so nobody saw whether the door was asked,
and when the shelf refused, why. Now dispatch writes its ledger on the episode (self.last[key]['door']: asked,
at, part, said, why, carried) - which /api/dynamic-segments shows under preparation - and names the shelf's
reason (_READY_SHELF_REFUSED, [shelf-why]) in its log line.

Usage:  book_nodes_7_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        book_nodes_7_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

ASKED_OLD = '''        if kind == 'book_time':
            rows = self.book_rows(key)
            started = bool(self.last.get(key, {}).get('started'))
'''
ASKED_NEW = '''        if kind == 'book_time':
            rows = self.book_rows(key)
            started = bool(self.last.get(key, {}).get('started'))
            door = self.last.setdefault(key, {}).setdefault('door', {})          # [book-nodes-7] the door's own ledger
            door['asked'] = int(door.get('asked') or 0) + 1
            door['at'] = time.time()
'''
NOTHING_OLD = '''                elif not candidates:
                    self.log('Book Time window: nothing of the episode is airable yet and nothing can be carried',   # [book-nodes-4]
                             '%d part(s) on the shelf, %d waiting' % (len(rows), len(waiting)))
                    return False
                else:
                    self.log('Book Time window: the episode waits for its welcome - %s is the first part ready'      # [book-nodes-4]
                             % str(candidates[0].get('book_phase') or '?'))
                    return False                             # an episode opens with its welcome
'''
NOTHING_NEW = '''                elif not candidates:
                    self.log('Book Time window: nothing of the episode is airable yet and nothing can be carried',   # [book-nodes-4]
                             '%d part(s) on the shelf, %d waiting' % (len(rows), len(waiting)))
                    door.update(said=False, part='', why='nothing airable yet: %d on the shelf, %d waiting' % (len(rows), len(waiting)))
                    return False
                else:
                    self.log('Book Time window: the episode waits for its welcome - %s is the first part ready'      # [book-nodes-4]
                             % str(candidates[0].get('book_phase') or '?'))
                    door.update(said=False, part=str(candidates[0].get('book_phase') or '?'), why='waits for its welcome')
                    return False                             # an episode opens with its welcome
'''
SAID_OLD = '''            try:
                said = await self.g['_ready_shelf_air']('banter', track, pick=candidates[0], on_handoff=accepted)
            finally:
                self.carry_from = ''
            self.log('Book Time window: %s the %s part%s' % ('aired' if said else 'the door refused',   # [book-nodes-4]
                     str(candidates[0].get('book_phase') or '?'), (' carried from ' + carry_from) if carry_from else ''))
            return bool(said)
'''
SAID_NEW = '''            try:
                said = await self.g['_ready_shelf_air']('banter', track, pick=candidates[0], on_handoff=accepted)
            finally:
                self.carry_from = ''
            refused = '' if said else str((self.g.get('_READY_SHELF_REFUSED') or [''])[0] or '')   # [book-nodes-7] [shelf-why]
            door.update(said=bool(said), part=str(candidates[0].get('book_phase') or '?'), why=refused, carried=carry_from)
            self.log('Book Time window: %s the %s part%s%s' % ('aired' if said else 'the door refused',   # [book-nodes-4]
                     str(candidates[0].get('book_phase') or '?'), (' carried from ' + carry_from) if carry_from else '',
                     (' - ' + refused) if refused else ''))
            return bool(said)
'''

EDITS = {
    "dynamic_segments_runtime.py": [
        ("the door counts its asks", ASKED_OLD, ASKED_NEW, 1),
        ("the door writes why it had nothing", NOTHING_OLD, NOTHING_NEW, 1),
        ("the door writes what it did and the shelf's reason", SAID_OLD, SAID_NEW, 1),
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
        tmp = path.with_suffix(path.suffix + ".booknodes7.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

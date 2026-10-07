#!/usr/bin/env python3
"""[book-nodes-8] A dynamic window is its own road: System 2's clock publishes a Book Time or supercut window
under its prep road (banter, ad), so the legacy chain that serves the entry when System 2 has nothing staged
served banter - and the segment's door was never asked. 2026-10-06.

The door's ledger ([book-nodes-7]) read 0 asks at 17:45; /api/system2/hour shows every dynamic slot as
kind "banter" with dynamic_kind "book_time" and 0 allocations. Since [book-reads-on] (14:36) plugged the
banter road's leak (a part aired as a plain round), nothing of Book Time could reach the air at all.

Edits:
  app.py                        the chain takes the slot's dynamic_kind as the kind when it is a segment's.
  dynamic_segments_runtime.py   active() answers the window's own kind (dynamic_kind) over the published road,
                                so dispatch() and window_owned() see the window as theirs.

Usage:  book_nodes_8_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        book_nodes_8_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

CHAIN_OLD = '''                _slot = schedule_take()
                _sched_occurrence = _schedule_dispatch_occurrence() if _slot else ""
                kind = str(_slot.get("kind") or "")
'''
CHAIN_NEW = '''                _slot = schedule_take()
                _sched_occurrence = _schedule_dispatch_occurrence() if _slot else ""
                kind = str(_slot.get("kind") or "")
                # [book-nodes-8] A DYNAMIC WINDOW IS ITS OWN ROAD. System 2's clock publishes a Book Time or
                # supercut window under its prep road (banter, ad), so when System 2 had nothing staged and this
                # chain served the entry, it served banter - the segment's door was never asked (10-06: every
                # window after 14:36; the door's ledger read 0 asks). The window's own kind is the one
                # schedule_extra_round knows.
                _dyn = str(_slot.get("dynamic_kind") or "")
                if _dyn in ("book_time", "sfx_supercut"):
                    kind = _dyn
'''
ACTIVE_OLD = '''        return {'kind': slot.get('kind'), 'slot': slot,
                'slot_id': slot.get('id'), 'due_at': pos.get('started'),
                'occurrence': pos.get('occurrence')}
'''
ACTIVE_NEW = '''        # [book-nodes-8] System 2 publishes a window under its prep road (banter); the window's own kind is the
        # segment's, and dispatch() / window_owned() must see it as theirs
        kind = str(slot.get('dynamic_kind') or '') if str(slot.get('dynamic_kind') or '') in dynamic_segments.TEMPLATES else slot.get('kind')
        return {'kind': kind, 'slot': slot,
                'slot_id': slot.get('id'), 'due_at': pos.get('started'),
                'occurrence': pos.get('occurrence')}
'''

EDITS = {
    "app.py": [
        ("the chain serves a dynamic window as its own kind", CHAIN_OLD, CHAIN_NEW, 1),
    ],
    "dynamic_segments_runtime.py": [
        ("active() answers the window's own kind", ACTIVE_OLD, ACTIVE_NEW, 1),
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
        tmp = path.with_suffix(path.suffix + ".booknodes8.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

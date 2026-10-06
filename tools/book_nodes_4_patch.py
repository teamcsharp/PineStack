#!/usr/bin/env python3
"""[book-nodes-4] A segment's window owns the air: the cupboard's out-of-turn doors stand aside in it, and the
Book Time door says what it decided. 2026-10-06.

Measured at the 15:45 CST Book Time window: the episode's opening was prepared and on the shelf, and the
window went to two banked banter rounds (swath sources snl2.md and mgs3.md) the unheard sweep put out of
turn - the cupboard dial reads 15 minutes since [bank-first] - so the segment's own door found the floor
busy. Nothing of the episode aired, and the door logged nothing.

Edits:
  dynamic_segments_runtime.py   window_owned(): True while the entry on air is a dynamic segment that still has
                                a part of its own to put out (not handed off, or a carry); installed as
                                g['dynamic_segment_window_owned']; dispatch logs its decision (lookahead).
  app.py                        the unheard sweep and larder_oldest_ready() read it and stand aside.

Usage:  book_nodes_4_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        book_nodes_4_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

OWNED_OLD = '''    async def dispatch(self, kind, track=None, dj=None, occurrence=None):
'''
OWNED_NEW = '''    def window_owned(self):
        """[book-nodes-4] Does a segment's window own the air right now? True while the entry on air is a
        dynamic segment (Book Time, the supercut) that still has a part of its own to put out - a part not
        yet handed off (ready, or re-makeable at the door), or an earlier episode's carry. The cupboard's
        out-of-turn doors read this and stand aside: on 10-06 the 15:45 window went to two banked banter
        rounds the sweep put out of turn (the dial at 15 min), and the segment's own door found the floor
        busy."""
        try:
            due = self.active()
            kind = str(due.get('kind') or '')
            if kind not in dynamic_segments.TEMPLATES:
                return False
            key = self.occurrence(due)
            if not key:
                return False
            if kind == 'book_time':
                if any(not row.get('dynamic_handed_off') for row in self.book_rows(key)):
                    return True
                return bool(self.book_carry(key)[1])
            return any(str(row.get('dynamic_occurrence') or '') == key and not row.get('dynamic_handed_off')
                       for row in self.g.get('_SHELF', {}).get('sfx_supercut', []))
        except Exception:   # noqa: BLE001 - a window that cannot be read owns nothing
            return False

    async def dispatch(self, kind, track=None, dj=None, occurrence=None):
'''
INSTALL_OLD = '''    g['dynamic_segment_dispatch'] = runtime.dispatch
'''
INSTALL_NEW = '''    g['dynamic_segment_dispatch'] = runtime.dispatch
    g['dynamic_segment_window_owned'] = runtime.window_owned          # [book-nodes-4] the cupboard's doors ask it
'''
WHY_OLD = '''                if carry:
                    candidates = carry
                elif not candidates:
                    return False
                else:
                    return False                             # an episode opens with its welcome
'''
WHY_NEW = '''                if carry:
                    candidates = carry
                elif not candidates:
                    self.log('Book Time window: nothing of the episode is airable yet and nothing can be carried',   # [book-nodes-4]
                             '%d part(s) on the shelf, %d waiting' % (len(rows), len(waiting)))
                    return False
                else:
                    self.log('Book Time window: the episode waits for its welcome - %s is the first part ready'      # [book-nodes-4]
                             % str(candidates[0].get('book_phase') or '?'))
                    return False                             # an episode opens with its welcome
'''
SAID_OLD = '''            try:
                said = await self.g['_ready_shelf_air']('banter', track, pick=candidates[0], on_handoff=accepted)
            finally:
                self.carry_from = ''
            return bool(said)
'''
SAID_NEW = '''            try:
                said = await self.g['_ready_shelf_air']('banter', track, pick=candidates[0], on_handoff=accepted)
            finally:
                self.carry_from = ''
            self.log('Book Time window: %s the %s part%s' % ('aired' if said else 'the door refused',   # [book-nodes-4]
                     str(candidates[0].get('book_phase') or '?'), (' carried from ' + carry_from) if carry_from else ''))
            return bool(said)
'''

SWEEP_OLD = '''    if _UNHEARD_PENDING_HANDOFFS:
        return _unheard_no("waiting for a prior cupboard handoff")
'''
SWEEP_NEW = '''    if _UNHEARD_PENDING_HANDOFFS:
        return _unheard_no("waiting for a prior cupboard handoff")
    _owned = globals().get("dynamic_segment_window_owned")               # [book-nodes-4] Book Time / the supercut
    if callable(_owned) and _owned():
        return _unheard_no("a segment's window owns the air: nothing goes out of turn inside it")
'''
OLDEST_OLD = '''def larder_oldest_ready() -> dict[str, Any] | None:
    """[bank-first] The longest-waiting never-aired banter round that can air now."""
    best, age, now = None, -1.0, time.time()
'''
OLDEST_NEW = '''def larder_oldest_ready() -> dict[str, Any] | None:
    """[bank-first] The longest-waiting never-aired banter round that can air now."""
    _owned = globals().get("dynamic_segment_window_owned")               # [book-nodes-4] a segment's window owns the air
    if callable(_owned) and _owned():
        return None
    best, age, now = None, -1.0, time.time()
'''

EDITS = {
    "dynamic_segments_runtime.py": [
        ("window_owned(): a segment's window with a part of its own", OWNED_OLD, OWNED_NEW, 1),
        ("install(): g['dynamic_segment_window_owned']", INSTALL_OLD, INSTALL_NEW, 1),
        ("dispatch says why it returned nothing", WHY_OLD, WHY_NEW, 1),
        ("dispatch says what the door did", SAID_OLD, SAID_NEW, 1),
    ],
    "app.py": [
        ("the unheard sweep stands aside in a segment's window", SWEEP_OLD, SWEEP_NEW, 1),
        ("larder_oldest_ready stands aside in a segment's window", OLDEST_OLD, OLDEST_NEW, 1),
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
        tmp = path.with_suffix(path.suffix + ".booknodes4.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

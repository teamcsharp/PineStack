#!/usr/bin/env python3
"""[book-nodes-2] The shelf re-read was still a gate: prepare_book superseded every written part the old phase
rule disliked, and a part once turned away could only come back if it passed that rule. 2026-10-06.

Measured at the 14:45 CST Book Time window: the episode's three closings (book_close road, 14:43, 14:46,
14:47) each carried a note AND dynamic_superseded=True - note_phase wrote the note at write time, then the
next prepare_book pass re-read the shelf and struck them with reject_phase. Nothing of the episode aired.

Edits (dynamic_segments_runtime.py, LF):
  1. prepare_book: the re-read notes (note_phase) and keeps every part; nothing is superseded.
  2. readmit_phases: a part turned away by the phase rule comes back whether or not the rule still objects.

Usage:  book_nodes_2_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        book_nodes_2_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

LOOP_OLD = '''            kept = []
            for row in rows:
                why = self.phase_error(row, kept)
                if why:
                    self.reject_phase(row, why)
                else:
                    kept.append(row)
            if len(kept) != len(rows):
                self.call('_larder_save')
                self.coverage_cache.clear()
            rows = kept
'''
LOOP_NEW = '''            # [book-nodes-2] NO GATE ON THE SHELF EITHER. This re-read every written part under the old phase
            # rule and superseded the ones it disliked (10-06, 14:43-14:48: three closings written on the
            # book_close road, each struck, nothing of the episode aired). What the rule would have said is a
            # NOTE on the part (note_phase, kept once); the part stands, and the nodes do the book work.
            noted = 0
            for row in rows:
                why = self.phase_error(row, [r for r in rows if r is not row])
                if why and not self.source_entry(row).get('book_phase_note'):
                    self.note_phase(row, why)
                    noted += 1
            if noted:
                self.call('_larder_save')
'''
READMIT_OLD = '''            if self.phase_error(row, rows):
                continue
            entry.pop('dynamic_phase_rejected', None)
            entry.pop('dynamic_superseded', None)
'''
READMIT_NEW = '''            # [book-nodes-2] it comes back whatever the old rule still thinks; the rule's opinion is a note
            why_now = self.phase_error(row, rows)
            if why_now and not entry.get('book_phase_note'):
                self.note_phase(row, why_now)
            entry.pop('dynamic_phase_rejected', None)
            entry.pop('dynamic_superseded', None)
'''

EDITS = {
    "dynamic_segments_runtime.py": [
        ("prepare_book re-reads the shelf with notes, never a strike", LOOP_OLD, LOOP_NEW, 1),
        ("readmit_phases takes every turned-away part back", READMIT_OLD, READMIT_NEW, 1),
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
        tmp = path.with_suffix(path.suffix + ".booknodes2.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

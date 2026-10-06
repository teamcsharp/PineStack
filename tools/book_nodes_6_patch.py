#!/usr/bin/env python3
"""[book-nodes-6] The part with a take missing is the one that needs the voicing pass. 2026-10-06.

Measured at the 16:45 CST window: the episode's opening, written 15:48, stood at 3 of 10 takes an hour later;
the 17:15 opening at 5 of 12. The runtime's worker ran its pre-window pass (prepare_book, whose pending road
voices the first part that is not ready) only when EVERY part was already ready - the one case that needs no
voicing - and only while the larder's writer was idle, which under talk-always it seldom is.

Edits (dynamic_segments_runtime.py):
  unvoiced_parts(due): the occurrence's parts that are not ready to air (the live readiness rule).
  worker(): within 20 minutes of a Book Time window, a part not ready sends the pass in, writer or no writer;
            the coverage case keeps its writer guard.
  BOOK_REMAKE_SECONDS 45 -> 90: the door's own re-make gets a fairer room.

Usage:  book_nodes_6_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        book_nodes_6_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

LOOP_OLD = '''                for due in demand:
                    if (not getattr(self.call('_system2'), 'enabled', False)
                            and due.get('kind') == 'book_time'
                            and float(due.get('starts_in', due.get('in_seconds', 0)) or 0) <= 1200):
                        rows = self.book_rows(self.occurrence(due))
                        if rows and all(self.original['dialogue_row_ready']('banter', row) for row in rows) and not self.book_coverage(due, rows)['ready']:
                            if not self.g.get('_LARDER_WRITING', [False])[0]:
                                await self.prepare_book(due)
                                break
'''
LOOP_NEW = '''                for due in demand:
                    if (not getattr(self.call('_system2'), 'enabled', False)
                            and due.get('kind') == 'book_time'
                            and float(due.get('starts_in', due.get('in_seconds', 0)) or 0) <= 1200):
                        rows = self.book_rows(self.occurrence(due))
                        # [book-nodes-6] THE PART WITH A TAKE MISSING IS THE ONE THAT NEEDS THE PASS. This asked for
                        # every part to be ready before it would send the pass whose pending road voices the one
                        # that is not - so the 16:45 opening on 10-06 stood at 3 of 10 takes for an hour. A voicing
                        # pass is not a writing pass: the larder writer's flag does not hold it.
                        if rows and self.unvoiced_parts(due):
                            await self.prepare_book(due)
                            break
                        if rows and not self.book_coverage(due, rows)['ready']:
                            if not self.g.get('_LARDER_WRITING', [False])[0]:
                                await self.prepare_book(due)
                                break
'''
HELPER_OLD = '''    async def worker(self):
'''
HELPER_NEW = '''    def unvoiced_parts(self, due):
        """[book-nodes-6] The occurrence's parts that are not ready to air, by the station's own readiness rule -
        the ones prepare_book's pending road voices next (the opening first)."""
        ready = self.original.get('dialogue_row_ready') or (lambda kind, row: True)
        rows = [row for row in self.book_rows(self.occurrence(due)) if not row.get('dynamic_handed_off')]
        return sorted([row for row in rows if not ready('banter', row)], key=self.book_order)

    async def worker(self):
'''
ROOM_OLD = '''    BOOK_REMAKE_SECONDS = 45.0          # [book-nodes-3] the door's wait for a part's missing takes to be re-made
'''
ROOM_NEW = '''    BOOK_REMAKE_SECONDS = 90.0          # [book-nodes-3] the door's wait for a part's missing takes to be re-made ([book-nodes-6] 45 -> 90)
'''

EDITS = {
    "dynamic_segments_runtime.py": [
        ("unvoiced_parts(due)", HELPER_OLD, HELPER_NEW, 1),
        ("worker(): a part not ready sends the pre-window pass in", LOOP_OLD, LOOP_NEW, 1),
        ("BOOK_REMAKE_SECONDS 90", ROOM_OLD, ROOM_NEW, 1),
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
        tmp = path.with_suffix(path.suffix + ".booknodes6.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

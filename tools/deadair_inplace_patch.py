#!/usr/bin/env python3
"""[s3-deadair] A dead-air insert is said in place, never held for later. 2026-10-05, #1571.

Measured on the first hour of the node: five nodes rolled a spoken insert (a
response, a quote, a discussion topic) and none was heard. Every single line
on the aside road is admitted as the opener of a graph exchange, and an
exchange waits on the prepared shelf until all its replies are written and
voiced ("single line waits on the prepared shelf until its graph exchange is
ready"). A fill that waits for its replies arrives after the silence it was
for. The node's task now carries the mark the station already uses for a line
that is read on in place (_S3_CHAPTER_ROW "row", as the manager's page parts
do): the insert is one line, said now, and starts no exchange of its own.

Usage:  deadair_inplace_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        deadair_inplace_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

OLD = r'''    """One node: the rolls and the line, on this task, so the rolls ride the line's stamp."""
    dj = dj_settings()
'''
NEW = r'''    """One node: the rolls and the line, on this task, so the rolls ride the line's stamp."""
    # [s3-deadair] SAID IN PLACE, NEVER HELD FOR LATER. A single line on the aside
    # road is otherwise admitted as the opener of a graph exchange and waits on
    # the prepared shelf for its replies - the first five inserts this node
    # rolled were never heard. This task's own context carries the mark the
    # station uses for a line read on in place; it starts no exchange.
    _S3_CHAPTER_ROW.set("row")
    dj = dj_settings()
'''

EDITS = {"app.py": [("said in place", OLD, NEW, "# [s3-deadair] SAID IN PLACE, NEVER HELD FOR LATER", 1)]}


def _read(path: Path) -> tuple[str, bool]:
    text = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in text
    if crlf:
        if text.count("\r\n") != text.count("\n"):
            raise SystemExit("%s has mixed line endings; refusing to guess" % path)
        text = text.replace("\r\n", "\n")
    return text, crlf


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        text, crlf = _read(path)
        todo = []
        for edit in edits:
            _n, old, _new, probe, count = edit
            state = ("applied" if text.count(probe) == count else
                     "ready" if text.count(old) == count else
                     "missing (anchor found %d, expected %d)" % (text.count(old), count))
            print("%-10s %-20s %s" % (name, edit[0], state))
            if state == "ready":
                todo.append(edit)
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, crlf, todo))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, crlf, todo in plans:
        for _n, old, new, probe, count in todo:
            assert text.count(old) == count
            text = text.replace(old, new)
            assert text.count(probe) == count
        if todo:
            tmp = path.with_name(path.name + ".deadair2.tmp")
            tmp.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
            os.replace(tmp, path)
            print("wrote %s (%d edit(s), %s)" % (path.name, len(todo), "CRLF" if crlf else "LF"))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

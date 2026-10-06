#!/usr/bin/env python3
"""[book-title] A book's title is said the way a person says it. 2026-10-05, #1588.

The second half of why Book Time never aired (the first is
tools/book_time_opening_patch.py). An opening only counts when the hosts speak
the book's title, and "the title" was the library's whole catalogue string:

    McCarthy and His Enemies - Record and Its Meaning -- William F Buckley Jr,
    L Brent Bozell, William Schlamm -- 1954

Nobody says that. The hosts said "McCarthy and His Enemies - Record and Its
Meaning", and the opening was turned away for not naming its book. Read with
the station's own functions on 10-05, 9 of the 27 retained openings failed on
this alone or together with the welcome count, and for a book catalogued this
way EVERY opening fails, so its episode can never start.

The title now also counts as spoken when its LEADING title is: the part before
the subtitle, the authors and the year that the file names carry. A wrong book
is still a wrong book, and a leading title too short to mean anything ("It")
does not count - then the whole title is still asked for.

Usage:  book_time_title_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        book_time_title_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HELPER_OLD = '''def book_time_bookends(text: Any, *, title: str = "", station: str = ""
                      ) -> dict[str, dict[str, Any]]:
'''
HELPER_NEW = '''def book_title_said(title: Any, words: str) -> bool:
    """[book-title] Was this book named, the way a person names a book?

    The library's titles are catalogue strings - 'Main Title - Subtitle --
    Authors -- 1954'. A host says the main title. `words` is speech already
    put through _normal and single-spaced. The whole title always counts; so
    does its leading title, when that is long enough to mean one book."""
    whole = " ".join(_normal(title).split())
    if not whole:
        return True
    if whole in words:
        return True
    lead = re.split(r"\\s+--\\s+|\\s+-\\s+|:\\s+|;\\s+|\\s+[(\\[]", str(title or "").strip(), maxsplit=1)[0]
    lead = " ".join(_normal(lead).split()).strip(" .,;:-")
    if len(lead.split()) < 2 and len(lead) < 6:
        return False
    return re.search(r"(?<!\\w)" + re.escape(lead) + r"(?!\\w)", words) is not None


''' + HELPER_OLD

CHECK_OLD = '''    words = " ".join(_normal(text).split())
    title_ok = not title or _normal(title).strip() in words
'''
CHECK_NEW = '''    words = " ".join(_normal(text).split())
    title_ok = not title or book_title_said(title, words)      # [book-title]
'''

EDITS = {"segment_contract.py": [
    ("how a title is said aloud", HELPER_OLD, HELPER_NEW, "def book_title_said(title: Any, words: str) -> bool:", 1),
    ("the opening is asked that way", CHECK_OLD, CHECK_NEW, "    title_ok = not title or book_title_said(title, words)", 1),
]}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        text = path.read_bytes().decode("utf-8")
        crlf = "\r\n" in text
        if crlf:
            if text.count("\r\n") != text.count("\n"):
                raise SystemExit("%s has mixed line endings; refusing to guess" % path)
            text = text.replace("\r\n", "\n")
        todo = []
        for edit in edits:
            label, old, _new, probe, count = edit
            have = text.count(probe)
            state = ("applied" if have == count else
                     "ready" if not have and text.count(old) == count else
                     "missing (anchor found %d, probe %d)" % (text.count(old), have))
            print("%-22s %-34s %s" % (name, label, state))
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
        for label, old, new, probe, count in todo:
            assert text.count(old) == count, (path.name, label)
            text = text.replace(old, new)
            assert text.count(probe) == count, (path.name, label, "probe")
        if todo:
            tmp = path.with_name(path.name + ".booktitle.tmp")
            tmp.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
            os.replace(tmp, path)
            print("wrote %s (%d edit(s), %s)" % (path.name, len(todo), "CRLF" if crlf else "LF"))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

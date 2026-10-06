#!/usr/bin/env python3
"""[num-leak-verb] A person who turns 18 is not reading out a turn number. 2026-10-05.

Seen on the air log while checking other work on 10-05, three times in one minute:

    "Hey, just call me back when he turn 18, all right?"  ->  "... when he earlier, all right?"
    "Yes, I turn 75 tomorrow."                             ->  "Yes, I earlier tomorrow."

The last gate on every spoken line (bookkeeping_numbers.spoken_gate) cuts the
running order's turn numbering, and its rule for "Turn 1 is ..." was any
"turn" followed by one or two digits. An age is said exactly that way.

The rule now takes "turn N" only where it stands as a NAME: opening a sentence
or a clause, or after a word that takes a noun (the, that, this, of, per, see,
on). After a subject or a helper verb - he, I, will, to - it is somebody's
birthday and it is left alone. "in turn two" and the other running-order
references are cut exactly as before.

bookkeeping_numbers.py is loaded when the station starts; this takes effect at
its next restart.

Usage:  num_leak_verb_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        num_leak_verb_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

RULE_OLD = '''# "Turn 1 is ..." - a turn numbered in digits is never how a person says it.
_TURN_DIGIT = re.compile(r"\\bturns?\\s+\\d{1,2}\\b", re.I)
'''
RULE_NEW = '''# "Turn 1 is ..." - a turn numbered in digits, used as the NAME of a place in the running order.
# [num-leak-verb] 2026-10-05: "call me back when he turn 18" aired as "when he earlier", and
# "Yes, I turn 75 tomorrow" as "Yes, I earlier tomorrow". A person turns an age: that is a verb,
# and the number is theirs. The name form opens a sentence or a clause, or follows a word that
# takes a noun; after a subject or a helper verb it is left alone.
_TURN_DIGIT = re.compile(r"(^|[.!?:;,(\\[\\"]\\s*|\\b(?:the|that|this|of|per|see|on)\\s+)(turns?\\s+\\d{1,2})\\b", re.I)
'''

USE_OLD = '''        for m in list(_TURN_DIGIT.finditer(s)):
            hits.append("turn number %r" % m.group(0))
        s = _TURN_DIGIT.sub("earlier", s)
'''
USE_NEW = '''        for m in list(_TURN_DIGIT.finditer(s)):
            hits.append("turn number %r" % m.group(2))
        s = _TURN_DIGIT.sub(lambda m: m.group(1) + "earlier", s)      # [num-leak-verb] what stood before it stays
'''

EDITS = {"bookkeeping_numbers.py": [
    ("a turn number is a name, not a birthday", RULE_OLD, RULE_NEW, "# [num-leak-verb] 2026-10-05:", 1),
    ("what stood before it stays", USE_OLD, USE_NEW, 's = _TURN_DIGIT.sub(lambda m: m.group(1) + "earlier", s)', 1),
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
            print("%-24s %-40s %s" % (name, label, state))
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
            tmp = path.with_name(path.name + ".numleak.tmp")
            tmp.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
            os.replace(tmp, path)
            print("wrote %s (%d edit(s), %s)" % (path.name, len(todo), "CRLF" if crlf else "LF"))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

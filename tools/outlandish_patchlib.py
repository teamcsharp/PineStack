"""[outlandish] The edit engine the outlandish_*_patch.py tools share.

Each edit is (marker, how, anchor, text): how = after | before | replace.
--check: 0 every edit ready (or applied, some not yet), 2 all applied, 1 an
anchor is missing or not unique (named). --apply: idempotent - edits whose
marker is present are skipped; the file keeps its line endings (CRLF-aware),
written atomically.
"""
from pathlib import Path


def run(edits, argv):
    mode = argv[1] if len(argv) > 1 else "--check"
    if mode not in ("--check", "--apply") or len(argv) < 3:
        print(__doc__)
        return 1
    p = Path(argv[2])
    raw = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    states, missing = [], []
    for mark, how, anchor, new in edits:
        if mark in text:
            states.append((mark, "applied"))
        elif text.count(anchor) == 1:
            states.append((mark, "ready"))
        else:
            states.append((mark, "anchor x%d" % text.count(anchor)))
            missing.append(mark)
    for mark, st in states:
        print("  %-22s %s" % (mark, st))
    if missing:
        print("anchor missing:", ", ".join(missing))
        return 1
    if all(st == "applied" for _m, st in states):
        print("already applied")
        return 2
    if mode == "--check":
        print("ready")
        return 0
    for mark, how, anchor, new in edits:
        if mark in text:
            continue
        if how == "after":
            text = text.replace(anchor, anchor + new, 1)
        elif how == "before":
            text = text.replace(anchor, new + anchor, 1)
        else:
            text = text.replace(anchor, new, 1)
        assert mark in text, mark
    if crlf:
        text = text.replace("\n", "\r\n")
    tmp = p.with_name(p.name + ".outl-tmp")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(p)
    print("applied")
    return 2

#!/usr/bin/env python3
"""[filemgr] app.py: the boot hook (a cold clear runs before any store loads)
and the install (the five /api/filemgr routes).

    python3 filemgr_app_patch.py --check app.py   # 0 ready, 2 applied, 1 missing
    python3 filemgr_app_patch.py --apply app.py

Two one-line anchors, each an INSERT (the replacement never contains its own
anchor twice). LF only, atomic write, idempotent.
"""
from __future__ import annotations

import os
import shutil
import sys

MARK = "# [filemgr]"
EDITS = [
    # (anchor line, text, where)
    ("from station_flow import FlowJournal\n",
     "import filemgr as _filemgr                # [filemgr] the disk on the base bar: a pending COLD clear\n"
     "_filemgr.boot_run_pending()               # [filemgr] runs HERE, before any module loads a store\n",
     "before"),
    ("pinelive.install(app, globals())\n",
     "_filemgr.install(app, globals())          # [filemgr] /api/filemgr/groups|plan|run|jobs|restore\n",
     "after"),
]


def read(path: str) -> str:
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8").replace("\r\n", "\n")


def check(text: str) -> tuple[int, str]:
    have = [e[1] in text for e in EDITS]
    if all(have):
        return 2, "applied"
    if any(have):
        return 1, "half applied: %s" % [e[0].strip() for e, h in zip(EDITS, have) if not h]
    missing = [e[0].strip() for e in EDITS if text.count(e[0]) != 1]
    if missing:
        return 1, "anchor(s) not found exactly once: %s" % missing
    if MARK in text:
        return 1, "a foreign [filemgr] marker is already in the file"
    return 0, "ready"


def apply(text: str) -> str:
    for anchor, add, where in EDITS:
        if add in text:
            continue
        assert text.count(anchor) == 1, anchor
        text = text.replace(anchor, add + anchor if where == "before" else anchor + add, 1)
    return text


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    path = argv[2]
    text = read(path)
    code, why = check(text)
    if argv[1] == "--check" or code != 0:
        print("%s: %s" % (path, why))
        return code
    out = apply(text)
    tmp = path + ".filemgr-tmp"
    with open(tmp, "wb") as fh:
        fh.write(out.encode("utf-8"))
    shutil.copymode(path, tmp)
    os.replace(tmp, path)
    code, why = check(read(path))
    print("%s: %s" % (path, why))
    return 2 if code == 2 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

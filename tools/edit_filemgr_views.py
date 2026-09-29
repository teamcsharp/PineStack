#!/usr/bin/env python3
"""[filemgr] desktop/renderer/index.html: load filemgr.css and filemgr.js
beside the voice actor (the base bar's person), so the disk sits in the same
bar on the desk. The tablet loads them through ViewAssets.kt instead.

    python3 edit_filemgr_views.py --check <repo root>   # 0 ready, 2 applied, 1 missing
    python3 edit_filemgr_views.py --apply <repo root>

CRLF-aware: the file's own line ending is kept. Atomic, idempotent.
"""
from __future__ import annotations

import os
import shutil
import sys

REL = "desktop/renderer/index.html"
EDITS = [
    ('  <link rel="stylesheet" href="./voice-actor-extract.css">',
     '  <link rel="stylesheet" href="./filemgr.css">'),
    ('  <script src="./voice-actor.js"></script>',
     '  <script src="./filemgr.js"></script>'),
]


def load(path: str) -> tuple[list[str], str]:
    raw = open(path, "rb").read().decode("utf-8")
    eol = "\r\n" if "\r\n" in raw else "\n"
    return raw.split(eol), eol


def check(lines: list[str]) -> tuple[int, str]:
    have = [add in lines for _a, add in EDITS]
    if all(have):
        return 2, "applied"
    if any(have):
        return 1, "half applied"
    bad = [a.strip() for a, _ in EDITS if lines.count(a) != 1]
    if bad:
        return 1, "anchor(s) not found exactly once: %s" % bad
    return 0, "ready"


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    path = os.path.join(argv[2], REL)
    lines, eol = load(path)
    code, why = check(lines)
    if argv[1] == "--check" or code != 0:
        print("%s: %s" % (path, why))
        return code
    for anchor, add in EDITS:
        i = lines.index(anchor)
        lines.insert(i + 1, add)
    tmp = path + ".filemgr-tmp"
    with open(tmp, "wb") as fh:
        fh.write(eol.join(lines).encode("utf-8"))
    shutil.copymode(path, tmp)
    os.replace(tmp, path)
    code, why = check(load(path)[0])
    print("%s: %s" % (path, why))
    return 2 if code == 2 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

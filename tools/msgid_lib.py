"""[msgid] The patch contract shared by every edit_msgid_*.py tool.

  python edit_msgid_X.py --check path   exit 0 = ready, 2 = applied, 1 = anchors missing (named)
  python edit_msgid_X.py --apply path   idempotent; asserts every anchor's count; atomic

Each edit is an INSERT after (or before) one narrow anchor - never a span
across two statements, and the insert never re-creates its own anchor.
Matched on LF; a CRLF file is written back CRLF.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

MARKER = "[msgid]"


class Edit:
    def __init__(self, name: str, anchor: str, text: str, where: str = "after", replace: str | None = None):
        self.name, self.anchor, self.text, self.where, self.replace = name, anchor, text, where, replace

    def apply(self, s: str) -> str:
        if self.replace is not None:
            return s.replace(self.anchor, self.replace, 1)
        if self.where == "before":
            return s.replace(self.anchor, self.text + self.anchor, 1)
        return s.replace(self.anchor, self.anchor + self.text, 1)


def run(edits: list[Edit], argv: list[str] | None = None, marker: str = MARKER) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = "--check"
    if argv and argv[0] in ("--check", "--apply"):
        mode = argv.pop(0)
    if not argv:
        print("usage: [--check|--apply] <file>")
        return 1
    path = Path(argv[0])
    raw = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    s = raw.replace("\r\n", "\n")
    if marker in s:
        print("applied: %s already carries %s" % (path, marker))
        return 2
    missing = [e.name + " (x%d)" % s.count(e.anchor) for e in edits if s.count(e.anchor) != 1]
    if missing:
        print("anchors missing or not unique in %s: %s" % (path, ", ".join(missing)))
        return 1
    if mode == "--check":
        print("ready: %s (%d edits)" % (path, len(edits)))
        return 0
    for e in edits:
        s = e.apply(s)
    if marker not in s:
        print("refused: the edits did not leave the marker")
        return 1
    out = s.replace("\n", "\r\n") if crlf else s
    fd, tmp = tempfile.mkstemp(prefix=".msgid-", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(out.encode("utf-8"))
    try:
        os.chmod(tmp, os.stat(path).st_mode & 0o7777)
    except OSError:
        pass
    os.replace(tmp, path)
    print("applied: %s (%d edits)" % (path, len(edits)))
    return 0

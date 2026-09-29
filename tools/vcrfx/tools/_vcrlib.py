"""[vcrfx] the patch contract, shared by every vcr_*.py tool.

    python vcr_x.py --check <file>   exit 0 ready, 2 already applied, 1 anchors missing
    python vcr_x.py --apply <file>   idempotent; asserts each anchor's count; writes
                                     atomically, keeping the file's own line endings

An edit is (marker, anchor, replacement). The marker is a string that exists
only once the edit is in (it must be IN the replacement and NOT in the anchor
text), so a second run reports "applied" instead of doubling an insert.
Anchors are matched with LF; a CRLF file is normalised for matching and
written back CRLF.
"""
from __future__ import annotations

import os
import sys
import tempfile


class Edit:
    def __init__(self, name: str, marker: str, anchor: str, replacement: str, count: int = 1):
        assert marker in replacement, "%s: the marker must be in the replacement" % name
        assert marker not in anchor, "%s: the marker must not be in the anchor" % name
        self.name, self.marker, self.anchor, self.replacement, self.count = (
            name, marker, anchor, replacement, count)


def _read(path: str) -> tuple[str, bool]:
    with open(path, "rb") as fh:
        raw = fh.read().decode("utf-8")
    crlf = "\r\n" in raw
    return raw.replace("\r\n", "\n"), crlf


def _write(path: str, text: str, crlf: bool) -> None:
    data = (text.replace("\n", "\r\n") if crlf else text).encode("utf-8")
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".vcrfx-")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    try:
        st = os.stat(path)
        os.chmod(tmp, st.st_mode & 0o7777)
    except OSError:
        pass
    os.replace(tmp, path)


def status(text: str, edits: list[Edit]) -> tuple[list[str], list[str], list[str]]:
    done, ready, missing = [], [], []
    for e in edits:
        if e.marker in text:
            done.append(e.name)
        elif text.count(e.anchor) == e.count:
            ready.append(e.name)
        else:
            missing.append("%s (anchor x%d, want x%d)" % (e.name, text.count(e.anchor), e.count))
    return done, ready, missing


def main(edits: list[Edit], argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2 or argv[0] not in ("--check", "--apply"):
        print("usage: --check|--apply <file>")
        return 64
    mode, path = argv
    text, crlf = _read(path)
    done, ready, missing = status(text, edits)
    if missing:
        print("MISSING in %s: %s" % (path, "; ".join(missing)))
        return 1
    if not ready:
        print("APPLIED already: %s (%d edits)" % (path, len(done)))
        return 2
    if mode == "--check":
        print("READY: %s: %s%s" % (path, ", ".join(ready),
                                  (" (already: %s)" % ", ".join(done)) if done else ""))
        return 0
    for e in edits:
        if e.name in ready:
            text = text.replace(e.anchor, e.replacement, e.count)
    d2, r2, m2 = status(text, edits)
    if r2 or m2:
        print("FAILED to converge: ready=%s missing=%s" % (r2, m2))
        return 1
    _write(path, text, crlf)
    print("APPLIED: %s: %s" % (path, ", ".join(ready)))
    return 0

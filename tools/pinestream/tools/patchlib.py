"""patchlib - marker-idempotent, CRLF-aware text edits with the house contract.

    python edit_x.py --check <root>   exit 0 ready, 2 already applied, 1 anchor missing
    python edit_x.py --apply <root>   applies what is ready; exit 2 when all applied, 1 on a miss

Every edit names a MARKER: a string that is in its replacement and nowhere in
the original file. A file holding the marker counts as applied for that edit;
otherwise its ANCHOR must appear exactly `count` times. Line endings are read
per file (CRLF if the file is mostly CRLF), matched in LF, written back in the
file's own ending, atomically. A replacement never contains its own anchor
unless it is an Insert (the anchor is kept, the text goes beside it).
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Edit:
    path: str            # relative to the root
    marker: str
    anchor: str
    new: str             # replaces the anchor
    count: int = 1

    def apply(self, text: str) -> str:
        return text.replace(self.anchor, self.new)


@dataclass
class Insert:
    path: str
    marker: str
    anchor: str
    text: str
    where: str = "after"   # after | before the anchor
    count: int = 1

    def apply(self, text: str) -> str:
        if self.where == "before":
            return text.replace(self.anchor, self.text + self.anchor)
        return text.replace(self.anchor, self.anchor + self.text)


@dataclass
class NewFile:
    """Copies a new file into the tree. Applied = the target exists with the
    same content (EOL-insensitive); a different existing file is a miss."""
    path: str
    source: str          # absolute path of the payload
    eol: str = "keep"    # keep | crlf | lf


def _read(p: Path) -> tuple[str, str]:
    raw = p.read_bytes().decode("utf-8")
    crlf = raw.count("\r\n")
    eol = "\r\n" if crlf and crlf * 2 >= raw.count("\n") else "\n"
    return raw.replace("\r\n", "\n"), eol


def _write(p: Path, text: str, eol: str) -> None:
    data = text.replace("\n", eol) if eol != "\n" else text
    tmp = p.with_name("." + p.name + ".pinestream.part")
    tmp.write_bytes(data.encode("utf-8"))
    try:
        shutil.copymode(p, tmp)
    except Exception:  # noqa: BLE001
        pass
    os.replace(tmp, p)


def _payload(nf: NewFile) -> tuple[str, str]:
    text, eol = _read(Path(nf.source))
    if nf.eol == "crlf":
        eol = "\r\n"
    elif nf.eol == "lf":
        eol = "\n"
    return text, eol


def status(root: Path, edits: list) -> tuple[int, list[str]]:
    """0 ready (something to do, all anchors good), 2 all applied, 1 a miss."""
    notes: list[str] = []
    todo = 0
    miss = 0
    cache: dict[str, str] = {}
    for e in edits:
        p = root / e.path
        if isinstance(e, NewFile):
            want, _ = _payload(e)
            if not p.exists():
                todo += 1
                notes.append("ready    new file %s" % e.path)
            else:
                have, _ = _read(p)
                if have == want:
                    notes.append("applied  new file %s" % e.path)
                else:
                    miss += 1
                    notes.append("MISS     %s exists and differs from the payload" % e.path)
            continue
        if not p.exists():
            miss += 1
            notes.append("MISS     %s does not exist" % e.path)
            continue
        if e.path not in cache:
            cache[e.path] = _read(p)[0]
        text = cache[e.path]
        if e.marker in text:
            notes.append("applied  %s [%s]" % (e.path, e.marker[:50]))
            continue
        n = text.count(e.anchor)
        if n != e.count:
            miss += 1
            notes.append("MISS     %s anchor found %d time(s), want %d: %r"
                         % (e.path, n, e.count, e.anchor[:90]))
            continue
        todo += 1
        notes.append("ready    %s [%s]" % (e.path, e.marker[:50]))
    if miss:
        return 1, notes
    return (0 if todo else 2), notes


def apply(root: Path, edits: list) -> tuple[int, list[str]]:
    code, notes = status(root, edits)
    if code != 0:
        return code, notes
    texts: dict[str, tuple[str, str]] = {}
    for e in edits:
        p = root / e.path
        if isinstance(e, NewFile):
            if not p.exists():
                text, eol = _payload(e)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes((text.replace("\n", eol) if eol != "\n" else text).encode("utf-8"))
            continue
        if e.path not in texts:
            texts[e.path] = _read(p)
        text, eol = texts[e.path]
        if e.marker in text:
            continue
        new = e.apply(text)
        if e.marker not in new:
            return 1, notes + ["BROKEN   %s: the edit does not carry its marker %r" % (e.path, e.marker)]
        texts[e.path] = (new, eol)
    for rel, (text, eol) in texts.items():
        _write(root / rel, text, eol)
    code2, notes2 = status(root, edits)
    return (2 if code2 == 2 else 1), notes2


def main(edits: list, argv: list[str] | None = None, after_apply=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2 or argv[0] not in ("--check", "--apply"):
        print("usage: %s --check|--apply <root>" % os.path.basename(sys.argv[0]))
        return 1
    root = Path(argv[1])
    if argv[0] == "--check":
        code, notes = status(root, edits)
    else:
        code, notes = apply(root, edits)
        if code == 2 and after_apply is not None:
            ok, say = after_apply(root)
            notes.append(("verify   " if ok else "VERIFY FAILED ") + say)
            if not ok:
                code = 1
    for n in notes:
        print(n)
    print({0: "READY", 1: "ANCHOR MISSING / FAILED", 2: "APPLIED"}[code])
    return code

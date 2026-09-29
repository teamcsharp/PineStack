"""closex_patchlib - marker-idempotent, CRLF-aware edits for the closex wave.

Every edit tool in this wave is a list of patches plus::

    python closex_<group>.py --check <repo-root>   exit 0 ready / 2 applied / 1 missing
    python closex_<group>.py --apply <repo-root>   applies what is ready, idempotent

A patch is APPLIED when its marker is in the file, READY when its anchor is
found exactly the expected number of times (inside its scope, when it has
one), and MISSING otherwise - naming why. Anchors are matched on LF text;
a CRLF file is edited as CRLF and written back as CRLF (per file, not per
tree: this share mixes both). Writes are atomic (temp file + replace).

Kinds:
  Insert(file, marker, anchor, text, where="after"|"before", scope=None,
         within=400)   - text goes on its own lines next to the anchor LINE
                         (the whole line that contains `anchor`). With
                         `scope`, the anchor is the first one within
                         `within` lines after the unique `scope` line.
  Replace(file, marker, old, new, scope=None, within=400)
                       - exact substring replace; `new` must carry the
                         marker and must not contain `old`.
  NewFile(file, marker, source) - copy a whole file (marker in it).
"""
from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Insert:
    file: str
    marker: str
    anchor: str
    text: str
    where: str = "after"
    scope: str | None = None
    within: int = 400
    kind: str = field(default="insert", init=False)


@dataclass
class Replace:
    file: str
    marker: str
    old: str
    new: str
    scope: str | None = None
    within: int = 400
    kind: str = field(default="replace", init=False)


@dataclass
class NewFile:
    file: str
    marker: str
    source: str
    kind: str = field(default="newfile", init=False)


def _read(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes().decode("utf-8")
    crlf = raw.count("\r\n") > raw.count("\n") // 2 if "\n" in raw else False
    return raw.replace("\r\n", "\n"), crlf


def _write(path: Path, text: str, crlf: bool) -> None:
    data = text.replace("\n", "\r\n") if crlf else text
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".closex.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data.encode("utf-8"))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _scope_window(text: str, scope: str | None, within: int) -> tuple[int, int, str | None]:
    """(start, end) character window the anchor must be found in."""
    if scope is None:
        return 0, len(text), None
    n = text.count(scope)
    if n != 1:
        return 0, 0, f"scope found {n}x (want 1): {scope[:70]!r}"
    at = text.index(scope)
    end = at
    for _ in range(within):
        nxt = text.find("\n", end + 1)
        if nxt < 0:
            end = len(text)
            break
        end = nxt
    return at, end, None


def status(root: Path, p) -> tuple[str, str]:
    path = root / p.file
    if p.kind == "newfile":
        if not path.exists():
            return "READY", "new file"
        text, _ = _read(path)
        src, _ = _read(Path(p.source))
        if text == src:
            return "APPLIED", "identical"
        if p.marker in text:
            return "READY", "older copy: will be replaced"
        return "MISSING", "a different file already sits there"
    if not path.exists():
        return "MISSING", "no such file"
    text, _ = _read(path)
    if p.marker in text:
        return "APPLIED", "marker present"
    a, b, err = _scope_window(text, p.scope, p.within)
    if err:
        return "MISSING", err
    needle = p.anchor if p.kind == "insert" else p.old
    win = text[a:b]
    if p.scope is None:
        n = win.count(needle)
        if n != 1:
            return "MISSING", f"anchor found {n}x (want 1): {needle[:70]!r}"
    elif needle not in win:
        return "MISSING", f"anchor not within {p.within} lines of scope: {needle[:70]!r}"
    return "READY", ""


def apply_one(root: Path, p) -> None:
    path = root / p.file
    if p.kind == "newfile":
        src = Path(p.source).read_bytes()
        path.parent.mkdir(parents=True, exist_ok=True)
        text, crlf = _read(Path(p.source))
        _write(path, text, crlf)
        return
    text, crlf = _read(path)
    a, b, err = _scope_window(text, p.scope, p.within)
    assert not err, err
    if p.kind == "insert":
        at = text.index(p.anchor, a, b)
        line_start = text.rfind("\n", 0, at) + 1
        line_end = text.find("\n", at)
        line_end = len(text) if line_end < 0 else line_end
        block = p.text.rstrip("\n")
        if p.where == "after":
            text = text[:line_end] + "\n" + block + text[line_end:]
        else:
            text = text[:line_start] + block + "\n" + text[line_start:]
    else:
        assert p.marker in p.new and p.old not in p.new, "replacement must carry its marker, not its anchor"
        at = text.index(p.old, a, b)
        text = text[:at] + p.new + text[at + len(p.old):]
    assert p.marker in text
    _write(path, text, crlf)


def main(patches: list, argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = "--check"
    if argv and argv[0] in ("--check", "--apply"):
        mode = argv.pop(0)
    root = Path(argv[0] if argv else ".").resolve()
    states = []
    for p in patches:
        st, why = status(root, p)
        states.append(st)
        print(f"{st:8} {p.file}  [{p.marker}] {why}")
    missing = [p for p, s in zip(patches, states) if s == "MISSING"]
    if mode == "--check":
        if missing:
            return 1
        return 2 if all(s == "APPLIED" for s in states) else 0
    if missing:
        print(f"REFUSING: {len(missing)} patch(es) cannot find their anchors; nothing written.")
        return 1
    for p, s in zip(patches, states):
        if s == "READY":
            apply_one(root, p)
            st, why = status(root, p)
            print(f"{'APPLIED' if st == 'APPLIED' else 'FAILED'}  {p.file}  [{p.marker}]")
            if st != "APPLIED":
                return 1
    return 0

"""[no-repeat-24h] The small patch engine the p3 tools share.

Contract (docs: parallel-patch-integration): every tool is
    python3 tools/<tool>.py --check [--root DIR]   exit 0 ready / 2 applied / 1 anchor missing
    python3 tools/<tool>.py --apply [--root DIR]   idempotent; exit 0 applied now / 2 already / 1 refused
Each edit carries a unique TAG inside its new text; the tag's presence is what
"applied" means, so a replacement can never still contain its own anchor and
report "ready" for ever. Anchors must occur exactly once. Files keep their line
endings (CRLF files stay CRLF), are compile-checked before they are written
(.py), and are written atomically.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Edit:
    name: str
    file: str
    anchor: str
    new: str
    tag: str
    how: str = "replace"        # replace | before | after

    def text_for(self) -> str:
        if self.how == "before":
            return self.new + self.anchor
        if self.how == "after":
            return self.anchor + self.new
        return self.new


def _read(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes().decode("utf-8")
    crlf = raw.count("\r\n") > raw.count("\n") // 2 and "\r\n" in raw
    return raw.replace("\r\n", "\n"), crlf


def _write(path: Path, text: str, crlf: bool) -> None:
    out = text.replace("\n", "\r\n") if crlf else text
    tmp = path.with_name(path.name + ".p3tmp")
    tmp.write_bytes(out.encode("utf-8"))
    os.replace(tmp, path)


def state_of(edits: list[Edit], root: Path) -> list[tuple[Edit, str]]:
    cache: dict[str, str] = {}
    out = []
    for e in edits:
        p = root / e.file
        if e.file not in cache:
            try:
                cache[e.file] = _read(p)[0]
            except OSError:
                cache[e.file] = None  # type: ignore[assignment]
        text = cache[e.file]
        if text is None:
            out.append((e, "missing file"))
            continue
        assert e.tag in e.new, "edit %s: its tag is not in its own new text" % e.name
        if e.tag in text:
            out.append((e, "applied"))
            continue
        n = text.count(e.anchor)
        out.append((e, "ready" if n == 1 else ("anchor missing" if n == 0 else "anchor x%d" % n)))
    return out


def run(title: str, edits: list[Edit], argv: list[str] | None = None, requires: list[tuple[str, str]] = ()) -> int:
    ap = argparse.ArgumentParser(description=title)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    a = ap.parse_args(argv)
    root = Path(a.root)
    for f, needle in requires:
        try:
            if needle not in _read(root / f)[0]:
                print("REFUSED: %s needs %r in %s (apply the tool that installs it first)" % (title, needle, f))
                return 1
        except OSError:
            print("REFUSED: %s missing" % f)
            return 1
    st = state_of(edits, root)
    for e, s in st:
        print("  %-12s %-14s %s" % (s, e.file, e.name))
    applied = sum(1 for _e, s in st if s == "applied")
    bad = [(e, s) for e, s in st if s not in ("applied", "ready")]
    if not a.apply:
        if applied == len(st):
            print("%s: APPLIED (%d edits)" % (title, applied))
            return 2
        if bad:
            print("%s: ANCHOR MISSING - %s" % (title, ", ".join("%s (%s)" % (e.name, s) for e, s in bad)))
            return 1
        print("%s: READY (%d to apply, %d already)" % (title, len(st) - applied, applied))
        return 0
    if applied == len(st):
        print("%s: already applied" % title)
        return 2
    if bad:
        print("%s: REFUSED, nothing written - %s" % (title, ", ".join("%s (%s)" % (e.name, s) for e, s in bad)))
        return 1
    files: dict[str, tuple[str, bool]] = {}
    for e, s in st:
        if s != "ready":
            continue
        if e.file not in files:
            files[e.file] = _read(root / e.file)
        text, crlf = files[e.file]
        assert text.count(e.anchor) == 1, e.name
        files[e.file] = (text.replace(e.anchor, e.text_for(), 1), crlf)
    for f, (text, crlf) in files.items():
        if f.endswith(".py"):
            try:
                compile(text, f, "exec")
            except SyntaxError as exc:
                print("REFUSED, nothing written: %s would not compile: %s" % (f, exc))
                return 1
    for f, (text, crlf) in files.items():
        _write(root / f, text, crlf)
    print("%s: APPLIED %d edit(s) to %s" % (title, sum(1 for _e, s in st if s == "ready"), ", ".join(files)))
    return 0


if __name__ == "__main__":
    sys.exit(0)

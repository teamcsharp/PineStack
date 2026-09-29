"""[plquiet] The tiny patch contract the plquiet tools share.

tool.py --check ROOT   exit 0 = ready (something to apply), 2 = already applied,
                       1 = an anchor is missing (named on stderr)
tool.py --apply ROOT   applies every ready edit atomically per file; exit 2 when
                       everything is in, 1 when an anchor is missing (nothing
                       in that file is written)

Anchors are written with LF; a CRLF file is matched and written back as CRLF.
Every edit carries its own `done` token, which the replacement contains and the
original does not - an applied edit is never applied twice.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


class Replace:
    def __init__(self, anchor: str, new: str, done: str, name: str = "") -> None:
        assert done in new and done not in anchor, name or anchor[:40]
        self.anchor, self.new, self.done, self.name = anchor, new, done, name or anchor.strip()[:50]

    def status(self, text: str) -> str:
        if self.done in text:
            return "applied"
        return "ready" if text.count(self.anchor) == 1 else (
            "missing" if self.anchor not in text else "ambiguous")

    def apply(self, text: str) -> str:
        return text.replace(self.anchor, self.new, 1)


def InsertBefore(anchor: str, block: str, done: str, name: str = "") -> Replace:
    return Replace(anchor, block + anchor, done, name)


def InsertAfter(anchor: str, block: str, done: str, name: str = "") -> Replace:
    return Replace(anchor, anchor + block, done, name)


class NewFile:
    def __init__(self, content: str, done: str) -> None:
        self.content, self.done = content, done


def _read(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    return raw.replace("\r\n", "\n"), crlf


def _write(path: Path, text: str, crlf: bool) -> None:
    data = text.replace("\n", "\r\n") if crlf else text
    tmp = path.with_name("." + path.name + ".plquiet.part")
    tmp.write_bytes(data.encode("utf-8"))
    try:
        os.chmod(tmp, path.stat().st_mode & 0o777)
    except OSError:
        pass
    os.replace(tmp, path)


def main(plan: dict[str, list], argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2 or argv[0] not in ("--check", "--apply"):
        print("usage: %s --check|--apply ROOT" % Path(sys.argv[0]).name, file=sys.stderr)
        return 1
    mode, root = argv[0], Path(argv[1])
    missing = ready = 0
    for rel, edits in plan.items():
        path = root / rel
        if edits and isinstance(edits[0], NewFile):
            nf = edits[0]
            if path.exists() and nf.done in path.read_text(encoding="utf-8"):
                print("  applied  %s (new file)" % rel)
                continue
            if path.exists():
                print("  MISSING  %s exists without the %s marker" % (rel, nf.done), file=sys.stderr)
                missing += 1
                continue
            ready += 1
            print("  ready    %s (new file)" % rel)
            if mode == "--apply":
                path.parent.mkdir(parents=True, exist_ok=True)
                _write(path, nf.content, False)
                print("  wrote    %s" % rel)
            continue
        if not path.is_file():
            print("  MISSING  %s (no such file)" % rel, file=sys.stderr)
            missing += 1
            continue
        text, crlf = _read(path)
        bad = []
        todo = []
        for e in edits:
            st = e.status(text)
            print("  %-8s %s :: %s" % (st, rel, e.name))
            if st in ("missing", "ambiguous"):
                bad.append(e.name)
            elif st == "ready":
                todo.append(e)
        if bad:
            missing += 1
            print("  MISSING  %s: %s" % (rel, "; ".join(bad)), file=sys.stderr)
            continue
        ready += len(todo)
        if mode == "--apply" and todo:
            for e in todo:
                text = e.apply(text)
                if e.done not in text:
                    print("  FAILED   %s :: %s" % (rel, e.name), file=sys.stderr)
                    return 1
            _write(path, text, crlf)
            print("  wrote    %s (%d edit%s%s)" % (rel, len(todo), "" if len(todo) == 1 else "s",
                                                    ", CRLF" if crlf else ""))
    if missing:
        return 1
    if mode == "--check":
        return 0 if ready else 2
    return 2

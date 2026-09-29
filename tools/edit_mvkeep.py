#!/usr/bin/env python3
"""[mvkeep] Live Message-view bubbles trim to the operator's history preference.

Measured 2026-09-29 16:48 after the memory diet: the tablet's WebView grew
~180 MB in 2 minutes; the Message view held 64 -> 74 bubbles in 40 s because live
arrivals trimmed only past MV_KEEP = 120. They now trim past the preference
(pine.mem.history, default 50) - the pinned bubble is still never trimmed.

usage: edit_mvkeep.py --check|--apply <spark-agent root>   (0 ready, 2 applied, 1 missing)
"""
import sys
from pathlib import Path

MARK = "[mvkeep]"
OLD = "    for (var i = 0; i < kids.length - MV_KEEP; i += 1) {\n"
NEW = ("    var keep = Math.min(MV_KEEP, MV_HIST_MAX || MV_KEEP);   /* [mvkeep] the operator's history preference */\n"
       "    for (var i = 0; i < kids.length - keep; i += 1) {\n")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    root = Path(sys.argv[2] if len(sys.argv) > 2 else ".")
    todo = []
    for d in ("desktop/renderer", "app/src/main/assets/pine-views"):
        p = root / d / "script-page.js"
        raw = p.read_bytes().decode("utf-8")
        crlf = "\r\n" in raw
        t = raw.replace("\r\n", "\n")
        if MARK in t:
            continue
        if t.count(OLD) != 1:
            print(MARK, "anchor missing", p); return 1
        todo.append((p, t, crlf))
    if not todo:
        print(MARK, "already applied"); return 2
    if mode != "--apply":
        print(MARK, "ready"); return 0
    for p, t, crlf in todo:
        t = t.replace(OLD, NEW, 1)
        if crlf:
            t = t.replace("\n", "\r\n")
        p.write_bytes(t.encode("utf-8"))
    print(MARK, "applied"); return 2


if __name__ == "__main__":
    sys.exit(main())

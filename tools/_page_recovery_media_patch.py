#!/usr/bin/env python3
"""A preserved delivery whose audio is gone is not a delivery.

`page_recovery_start` restores the page's FIFO after a deploy, and
`page_recovery_read` accepts any row that has a delivery id and a url. It
never asks whether the audio is still there - and `/media` is pruned, so it
often is not.

Measured 2026-09-21: the preserved FIFO held exactly one row,
`/media/test.wav`, "The host's full opening." - a fixture whose file has
never existed on this station. It was replayed on every single restart,
failed silently, and after the admission gate went in it became the one
refusal standing between the speech lane and clean enforcement: 82 of the
gate's 4,991 historical "the final audio is not available" refusals are
this one row, once per restart, for as long as the ledger goes back.

Run from the repo root (or with --file pointing at the deployed copy):

    python tools/_page_recovery_media_patch.py --check
    python tools/_page_recovery_media_patch.py
    python tools/_page_recovery_media_patch.py --revert

REQUIRES `_admission_reach_patch.py`, whose `_admission_resolve` knows
every route this station names audio by.

WHY THE GATE'S OWN RESOLVER

Because then the two cannot disagree. What the gate can name is exactly
what can be replayed; a row the resolver cannot turn into a file is a row
the page would have failed on anyway, and dropping it here means the
failure is a quiet omission at startup instead of a refused dispatch and a
silent 404 in somebody's browser.

It is cheap: a stat per preserved row, at most 120 of them, once per
restart, on a road that is already reading a file off disk.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

TARGET = "app.py"
MARK = "#1342"
NEEDS = "def _admission_resolve("


ANCHOR = '''def page_recovery_read() -> list[dict[str, Any]]:
    try:
        return [r for r in json.loads(PAGE_RECOVERY_PATH.read_text(encoding="utf-8")).get("clips", [])
                if isinstance(r, dict) and r.get("delivery_id") and r.get("url")][:120]
'''

NEW = '''def page_recovery_read() -> list[dict[str, Any]]:
    # #1342: ...AND WHOSE AUDIO IS STILL THERE. /media is pruned, so a
    # preserved delivery can outlive its own file; this road then replayed
    # it on every restart, the browser 404ed, and nobody heard anything.
    # The gate's own resolver is the test, so what can be replayed and what
    # the gate can name cannot disagree - and a row it refuses is dropped
    # quietly at startup rather than becoming a refused dispatch.
    def _still_there(row: Any) -> bool:
        try:
            return _admission_resolve(str((row or {}).get("url") or "")) is not None
        except Exception:  # noqa: BLE001
            return False

    try:
        return [r for r in json.loads(PAGE_RECOVERY_PATH.read_text(encoding="utf-8")).get("clips", [])
                if isinstance(r, dict) and r.get("delivery_id") and r.get("url")
                and _still_there(r)][:120]
'''


EDITS = [("a preserved delivery must still have its audio", ANCHOR, NEW)]


def load(path: Path) -> str:
    raw = path.read_bytes()
    if b"\r\n" in raw:
        raise SystemExit(f"{path} contains CRLF; this file is LF-only "
                         "and the patch refuses to normalise it silently")
    return raw.decode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify anchors, write nothing")
    parser.add_argument("--revert", action="store_true")
    parser.add_argument("--file", default=TARGET)
    args = parser.parse_args()

    path = Path(args.file)
    if not path.is_file():
        print(f"no {path}; run this from the repo root", file=sys.stderr)
        return 2
    text = load(path)

    if args.revert:
        out, undone = text, 0
        for name, anchor, new in EDITS:
            if new in out:
                out = out.replace(new, anchor, 1)
                undone += 1
                print(f"  reverted: {name}")
        if not undone:
            print("nothing to revert")
            return 0
        compile(out, str(path), "exec")
        path.write_bytes(out.encode("utf-8"))
        print(f"reverted {undone} edit(s) in {path}")
        return 0

    if NEEDS not in text:
        print(f"{NEEDS} is not in app.py - apply "
              "tools/_admission_reach_patch.py first", file=sys.stderr)
        return 1

    already = [name for name, _a, new in EDITS if new in text]
    if len(already) == len(EDITS):
        print("already applied; nothing to do")
        return 0

    trouble = []
    for name, anchor, _new in EDITS:
        found = text.count(anchor)
        print(f"  anchor {found}x  {name}")
        if found != 1:
            trouble.append(f"{name}: anchor found {found} times, expected 1")
    if trouble:
        print("ANCHORS DO NOT MATCH - app.py has moved under this patch:",
              file=sys.stderr)
        for line in trouble:
            print("  " + line, file=sys.stderr)
        return 1
    if args.check:
        print("all anchors matched exactly once; --check wrote nothing")
        return 0

    out = text
    for _name, anchor, new in EDITS:
        out = out.replace(anchor, new, 1)
    try:
        compile(out, str(path), "exec")
    except SyntaxError as exc:
        print(f"the patched file does not parse ({exc}); nothing written",
              file=sys.stderr)
        return 1
    path.write_bytes(out.encode("utf-8"))
    print(f"applied {len(EDITS)} edits to {path}")
    print("the container must be restarted for this to take effect; this "
          "script does not restart anything")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""[pip-rec-order] The album recorder widget has an order. 2026-10-06.

[pip-rec] added "rec" to PIP_DEFAULTS["widgets"] and not to PIP_DEFAULTS["order"],
so normalize_pip_settings() raised KeyError: 'rec' on every read of the PiP
settings - and api_put_pip_config fell into the same KeyError on its fallback,
so the operator's PiP settings could not be saved (traceback in the station log
at 05:4x host time, 2026-10-06). One name in one tuple.

Usage:  pip_rec_order_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        pip_rec_order_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

OLD = '''    "order": {name: index for index, name in enumerate(("dialogue", "task", "audit", "production", "music", "chat", "messages", "cast", "voices", "roulette"))},
'''
NEW = '''    "order": {name: index for index, name in enumerate(("dialogue", "task", "audit", "production", "music", "chat", "messages", "cast", "voices", "roulette", "rec"))},   # [pip-rec-order] every widget has an order
'''

EDITS = {"app.py": [("the album recorder widget has an order", OLD, NEW, 1)]}


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        if not path.exists():
            print("%-46s (not in this tree - skipped)" % name[-46:])
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, want in edits:
            if text.count(new) >= want:
                print("%-72s applied" % label[:72])
                continue
            n = text.count(old)
            if n == want:
                print("%-72s ready" % label[:72])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-72s MISSING (anchor count %d, wanted %d)" % (label[:72], n, want))
                missing = True
        if changed:
            plans.append((path, text, mode, bom))
    if missing:
        print("anchors missing - nothing applied")
        return 1
    if not ready:
        print("every edit reads applied")
        return 2
    if argv[1] == "--check":
        print("ready to apply")
        return 0
    for path, text, mode, bom in plans:
        out = text.replace("\n", "\r\n") if mode == "crlf" else text
        data = out.encode("utf-8")
        if bom:
            data = b"\xef\xbb\xbf" + data
        tmp = path.with_suffix(path.suffix + ".piprec.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

#!/usr/bin/env python3
"""[pip-warm-rule] The warm copy is the PARKED element, not the marked one. 2026-10-06.

"I am still not seeing videos." [pip-tube-rules] refused any <video> carrying data-pine-warm as the
set's warm copy of the next clip - but sfx-tv.js removes that attribute only on the seamless
hand-over (slotSwap); a clip that reaches the tube through the ordinary build() keeps the
attribute for its whole life, so the live picture was refused and the tube stayed empty while
the sound played (receipts after the rebuild: not_shown, zero size, no tile). What marks the
warm copy for certain is its parked state: warmPark's inline style, opacity 0 and no pointer
events, which the promotion strips. Both copies of pine-pip.js.

Usage:  pip_warm_rule_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        pip_warm_rule_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

OLD = r'''      if (v.dataset && v.dataset.pineWarm === '1') return 'warm copy';   /* [pip-tube-rules] the set's next clip, warming off screen */
'''
NEW = r'''      /* [pip-warm-rule] the set's next clip warms PARKED: warmPark's inline style, opacity 0 and no pointer
         events, which the hand-over strips. Not the data-pine-warm attribute: sfx-tv.js removes that only on
         the seamless road, and a clip built the ordinary way keeps it for life - refusing on it emptied the tube. */
      if (v.style && v.style.opacity === '0' && v.style.pointerEvents === 'none') return 'warm copy';
'''
PIPJS = [("the warm copy is the parked element", OLD, NEW, "if (v.style && v.style.opacity === '0' && v.style.pointerEvents === 'none') return 'warm copy';", 1)]
EDITS = {"desktop/renderer/pine-pip.js": PIPJS, "app/src/main/assets/pine-views/pine-pip.js": PIPJS}


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
        for label, old, new, probe, count in edits:
            have = text.count(probe)
            have_old = text.count(old)
            if have == count and have_old == 0:
                state = "applied"
            elif have_old == count and have == 0:
                text = text.replace(old, new)
                state, changed = "ready", True
            else:
                state = "missing (anchor found %d, probe %d)" % (have_old, have)
            print("%-46s %-40s %s" % (name[-46:], label, state))
            if state == "ready":
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, bom, mode, changed))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, bom, mode, changed in plans:
        if not changed:
            continue
        body = (text.replace("\n", "\r\n") if mode == "crlf" else text).encode("utf-8")
        tmp = path.with_name(path.name + ".pipwarm.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

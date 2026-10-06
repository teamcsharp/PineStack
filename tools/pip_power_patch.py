#!/usr/bin/env python3
"""[pip-power] A painter nobody can see does not paint. 2026-10-06.

"I need pinePip able to delegate whatever services on the backend to making sure the front end
is performant... a panel... out of control... choking out the entire application." Measured with
tests/probe_pip_perf_2026_10_06.cjs on the live station: in Pine PiP the station page kept
60% of a core busy for a page nobody could see - boothGlassDraw 0.95 s, drawScope 0.93 s, the
three.js stages' ticks, djTalkRepaint, of every 20 s. The painters already gate on
`offsetParent` (null only for display:none) and `document.hidden`, but the PiP hides the
station's panels with visibility:hidden (body.pine-pip > main > :not(#control)), which leaves
offsetParent set, so every gate said "seen". One answer, pineSeen(el), reads the visibility
chain too (checkVisibility), and the nine gates ask it. Panels that are display:none, hidden
documents and engines without checkVisibility keep exactly the old answer.

Usage:  pip_power_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        pip_power_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HELPER_OLD = '''function boothGlassDraw() {
'''
HELPER_NEW = '''/* [pip-power] Whether a painter's surface can be seen at all. offsetParent is null only for
 * display:none; in Pine PiP the station's panels under <main> are hidden with visibility:hidden
 * (body.pine-pip > main > :not(#control)), so every canvas and three.js stage kept drawing at
 * 60 fps behind the PiP - measured 2026-10-06 with tests/probe_pip_perf_2026_10_06.cjs:
 * boothGlassDraw 0.95 s, drawScope 0.93 s and the stages' ticks of every 20 s, 60% of a core
 * for a page nobody could see. checkVisibility() reads the visibility chain too; a hidden
 * document is never seen; an engine without checkVisibility keeps the old answer. */
function pineSeen(el) {
  if (document.hidden || !el || !el.offsetParent) return false;
  try {
    if (typeof el.checkVisibility === "function") {
      return el.checkVisibility({checkVisibilityCSS: true, visibilityProperty: true});
    }
  } catch (e) { /* the old answer */ }
  return true;
}

function boothGlassDraw() {
'''
APP = [
    ("one answer to 'can this be seen'", HELPER_OLD, HELPER_NEW, "function pineSeen(el) {", 1),
    ("the canvas gates ask it", "if (!canvas.offsetParent) return;", "if (!pineSeen(canvas)) return;   /* [pip-power] */", "if (!pineSeen(canvas)) return;   /* [pip-power] */", 3),
    ("the booth glass asks it", "if (!canvas || !canvas.offsetParent || document.hidden) return;", "if (!pineSeen(canvas)) return;   /* [pip-power] */", None, 0),
    ("the three.js stages ask it", "if (document.hidden || !renderer.domElement.offsetParent) return;", "if (!pineSeen(renderer.domElement)) return;   /* [pip-power] */", "if (!pineSeen(renderer.domElement)) return;   /* [pip-power] */", 5),
    ("the host gate asks it", "if (document.hidden || !host.offsetParent) return;", "if (!pineSeen(host)) return;   /* [pip-power] */", "if (!pineSeen(host)) return;   /* [pip-power] */", 1),
]
EDITS = {"app.py": APP}


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
        # The booth-glass form and the plain canvas form both become the same line, so the plain
        # form's probe counts 3 (2 + 1) after both edits; the booth-glass edit itself is judged by
        # its own anchor only (probe None).
        for label, old, new, probe, count in edits:
            have_old = text.count(old)
            have = text.count(probe) if probe else 0
            if label == "one answer to 'can this be seen'":
                # the anchor line survives inside the new text: judged by the probe alone
                state = "applied" if have == 1 else ("ready" if have_old == 1 else "missing (anchor found %d, probe %d)" % (have_old, have))
            elif probe is None:
                state = "applied" if have_old == 0 else ("ready" if have_old == 1 else "missing (anchor found %d)" % have_old)
            elif label == "the canvas gates ask it":
                state = "applied" if (have_old == 0 and have == 3) else ("ready" if have_old == 2 else "missing (anchor found %d, probe %d)" % (have_old, have))
            else:
                state = "applied" if (have_old == 0 and have == count) else ("ready" if (have_old == count and have == 0) else "missing (anchor found %d, probe %d)" % (have_old, have))
            if state == "ready":
                text = text.replace(old, new)
                changed = True
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
        tmp = path.with_name(path.name + ".pippower.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

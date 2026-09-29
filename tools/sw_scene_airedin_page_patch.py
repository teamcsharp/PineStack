#!/usr/bin/env python3
"""[seg-aired-in] A SCENE HEADING NAMES THE ENTRY IT WENT OUT IN - the page.

TARGET: desktop/renderer/script-page.js
MIRROR: app/src/main/assets/pine-views/script-page.js (the tablet's identical copy)

Companion of sw_scene_airedin_app_patch.py (apply that first): when a scene's
slot carries `aired_in` (the running-order entry on air when it was heard, and
not the one it was written for), the heading prints "went out in <entry>"
under the title, so the Script view reads entry to entry in the operator's own
segment names.

    python3 sw_scene_airedin_page_patch.py --check [ROOT]   0 ready, 2 applied, 1 missing
    python3 sw_scene_airedin_page_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

TARGET = "desktop/renderer/script-page.js"
MARKER = "[seg-aired-in]"
NL = chr(10)

EDITS = [
    ("title",
     "    words.appendChild(title);" + NL + "    words.appendChild(make('small', 'sp-segment-place'," + NL,
     "    words.appendChild(title);" + NL
     + "    if (slot.aired_in && slot.aired_in.label) {                 /* [seg-aired-in] */" + NL
     + "      var airedIn = make('small', 'sp-segment-airedin', 'went out in ' + slot.aired_in.label);" + NL
     + "      airedIn.title = 'The running order had ' + slot.aired_in.label + ' on air when this was heard';" + NL
     + "      airedIn.style.cssText = 'display:block;opacity:.8;font-style:italic';" + NL
     + "      words.appendChild(airedIn);" + NL
     + "    }" + NL
     + "    words.appendChild(make('small', 'sp-segment-place'," + NL),
]


# The tablet serves a byte-identical copy (tests/test_scripted_line_voice_ad_2026_09_25.cjs
# holds them equal), so both are edited the same way, or neither.
TARGETS = (TARGET, "app/src/main/assets/pine-views/script-page.js")


def load(root: Path, target: str = TARGET):
    path = root / target
    raw = path.read_bytes().decode("utf-8")
    return path, raw.replace("\r\n", NL), "\r\n" in raw


def check(root: Path):
    codes, why = [], []
    for target in TARGETS:
        try:
            _p, text, _c = load(root, target)
        except OSError as exc:
            if target != TARGET:
                continue                     # a checkout without the tablet app
            return 1, ["cannot read %s: %s" % (target, exc)]
        if MARKER in text:
            codes.append(2)
            continue
        bad = ["%s anchor %s: found %d" % (target, n, text.count(a)) for n, a, _ in EDITS if text.count(a) != 1]
        codes.append(1 if bad else 0)
        why += bad
    if 1 in codes:
        return 1, why
    if codes and all(c == 2 for c in codes):
        return 2, ["already applied"]
    return 0, []


def apply(root: Path) -> int:
    code, _why = check(root)
    if code != 0:
        return code
    for target in TARGETS:
        try:
            path, text, crlf = load(root, target)
        except OSError:
            continue
        if MARKER in text:
            continue
        for _n, anchor, new in EDITS:
            text = text.replace(anchor, new, 1)
        if crlf:
            text = text.replace(NL, "\r\n")
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".sw_page.")
        with os.fdopen(fd, "wb") as fh:
            fh.write(text.encode("utf-8"))
        os.replace(tmp, path)
    return 0


def main(argv):
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print("usage: %s --check|--apply [ROOT]" % argv[0])
        return 1
    root = Path(argv[2] if len(argv) > 2 else ".").resolve()
    if argv[1] == "--check":
        code, why = check(root)
        print({0: "READY", 2: "APPLIED", 1: "MISSING"}[code], "; ".join(why))
        return code
    code = apply(root)
    print({0: "APPLIED", 2: "ALREADY APPLIED"}.get(code, "NOT APPLIED: " + "; ".join(check(root)[1])))
    return 0 if code in (0, 2) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

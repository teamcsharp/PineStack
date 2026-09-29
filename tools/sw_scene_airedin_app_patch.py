#!/usr/bin/env python3
"""[seg-aired-in] A SCENE HEADING NAMES THE ENTRY IT WENT OUT IN - app.py.

TARGET: app.py

Measured 09-29 by tools/script_watch.py: scene headings in the Script view
name the running-order entry a round was WRITTEN FOR ([seg-names]: reserved,
shelved, banked) - e.g. "Banter during recordings" (09:13) over a round that
went out at 09:47 while the running order had "Painting selling" on air. The
heading used the operator's own names, but not the one on air, so the reader
could not follow the hour entry to entry.

The written-for label stays (it is the round's own link, never the clock's).
The scene now also carries `slot.aired_in` = the entry segment_on_air() says
owned the air at the scene's moment, whenever that is a different entry; the
page prints it under the title. Unknown stays unknown: no slot, no aired_in.

    python3 sw_scene_airedin_app_patch.py --check [ROOT]   0 ready, 2 applied, 1 missing
    python3 sw_scene_airedin_app_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

TARGET = "app.py"
MARKER = "[seg-aired-in]"
NL = chr(10)

FN = '''def screenplay_scene_aired_in(got: dict[str, Any], at: float) -> dict[str, Any]:
    """[seg-aired-in] A heading's slot plus the entry that owned the air at its
    moment, when that is another entry: {"slot": {..., "aired_in": {label, id}}}.
    The written-for name is the round's own link and stays; this is where it
    WENT OUT, from the station's own schedule position. Never raises."""
    try:
        slot = got.get("slot") if isinstance(got, dict) else None
        if not isinstance(slot, dict) or not slot or not float(at or 0):
            return got
        seg = segment_on_air(float(at))
        sid = str((seg or {}).get("id") or "")
        if not sid or not (seg or {}).get("label") or sid == str(slot.get("id") or ""):
            return got
        return {"slot": dict(slot, aired_in={"label": str(seg.get("label") or "")[:80], "id": sid})}
    except Exception:  # noqa: BLE001
        return got


def screenplay_round_open(entry: dict[str, Any]) -> dict[str, Any]:'''

EDITS = [
    ("helper", "def screenplay_round_open(entry: dict[str, Any]) -> dict[str, Any]:", FN),
    ("call",
     '                 **screenplay_scene_slot(rnd, round_kind, at,        # [seg-names]' + NL
     + '                                         d.get("open_round")))' + NL,
     '                 **screenplay_scene_aired_in(                          # [seg-aired-in]' + NL
     + '                     screenplay_scene_slot(rnd, round_kind, at,        # [seg-names]' + NL
     + '                                           d.get("open_round")), at))' + NL),
]


def load(root: Path):
    path = root / TARGET
    raw = path.read_bytes().decode("utf-8")
    return path, raw.replace("\r\n", NL), "\r\n" in raw


def check(root: Path):
    try:
        _p, text, _c = load(root)
    except OSError as exc:
        return 1, ["cannot read %s: %s" % (TARGET, exc)]
    if MARKER in text:
        return 2, ["already applied"]
    bad = ["anchor %s: found %d" % (n, text.count(a)) for n, a, _ in EDITS if text.count(a) != 1]
    return (1, bad) if bad else (0, [])


def apply(root: Path) -> int:
    code, _why = check(root)
    if code != 0:
        return code
    path, text, crlf = load(root)
    for _n, anchor, new in EDITS:
        text = text.replace(anchor, new, 1)
    if crlf:
        text = text.replace(NL, "\r\n")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".airedin_app.")
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

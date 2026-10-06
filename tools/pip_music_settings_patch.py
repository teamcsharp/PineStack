#!/usr/bin/env python3
"""[pip-music] The station keeps where the PiP music player sits. 2026-10-05.

"Allow me to be able to freely drag and reposition the music player in pip
mode. have it look like the 2nd image but expanable to the third image."

The desk remembers the player's place and size as PiP preferences
(tools/pip_desk_patch.py). The station holds the shared copy of those
preferences (/api/pip/config, data/pine-pip.json) and normalises every field
it knows, dropping the rest - so it has to know these two, or the place is
lost on its way through the shared settings.

  musicPosition  {x, y}  the player's top-left as a share of the window, 0..1
  musicExpanded  bool    opened out to the artwork view

Usage:  pip_music_settings_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        pip_music_settings_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

DEFAULTS_OLD = '''    "roulettePosition": {"x": .04, "y": .18}, "theme": "pine", "transparency": 15,
'''
DEFAULTS_NEW = DEFAULTS_OLD + '''    # [pip-music] the mini player: where it sits (its top-left, as a share of the
    # window) and whether it is opened out to the artwork view
    "musicPosition": {"x": .03, "y": .6}, "musicExpanded": False,
'''

KEYS_OLD = '''    for key in ("widgets", "docks", "order", "voiceStyles", "cameraBounds", "messageBounds",
                "messageTile", "roulettePosition"):
        out[key] = {**PIP_DEFAULTS[key], **(raw.get(key) if isinstance(raw.get(key), dict) else {})}
'''
KEYS_NEW = '''    for key in ("widgets", "docks", "order", "voiceStyles", "cameraBounds", "messageBounds",
                "messageTile", "roulettePosition", "musicPosition"):
        out[key] = {**PIP_DEFAULTS[key], **(raw.get(key) if isinstance(raw.get(key), dict) else {})}
    out["musicExpanded"] = raw.get("musicExpanded") is True   # [pip-music]
'''

BOUNDS_OLD = '''                        ("roulettePosition", {"x": (0, 1), "y": (0, 1)})):
'''
BOUNDS_NEW = '''                        ("roulettePosition", {"x": (0, 1), "y": (0, 1)}),
                        ("musicPosition", {"x": (0, 1), "y": (0, 1)})):
'''

MERGE_OLD = '''    for key in ("widgets", "docks", "order", "voiceStyles", "cameraBounds", "messageBounds", "messageTile", "roulettePosition"):
'''
MERGE_NEW = '''    for key in ("widgets", "docks", "order", "voiceStyles", "cameraBounds", "messageBounds", "messageTile", "roulettePosition", "musicPosition"):
'''

EDITS = {"app.py": [
    ("the player's place has a default", DEFAULTS_OLD, DEFAULTS_NEW, '"musicPosition": {"x": .03, "y": .6}, "musicExpanded": False,', 1),
    ("it is read and its size kept", KEYS_OLD, KEYS_NEW, 'out["musicExpanded"] = raw.get("musicExpanded") is True', 1),
    ("it is held inside the window", BOUNDS_OLD, BOUNDS_NEW, '("musicPosition", {"x": (0, 1), "y": (0, 1)})):', 1),
    ("a partial save keeps the rest", MERGE_OLD, MERGE_NEW, '"messageTile", "roulettePosition", "musicPosition"):\n        if isinstance(payload.get(key), dict)', 1),
]}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        text = path.read_bytes().decode("utf-8")
        crlf = "\r\n" in text
        if crlf:
            if text.count("\r\n") != text.count("\n"):
                raise SystemExit("%s has mixed line endings; refusing to guess" % path)
            text = text.replace("\r\n", "\n")
        todo = []
        for edit in edits:
            label, old, _new, probe, count = edit
            have = text.count(probe)
            state = ("applied" if have == count else
                     "ready" if not have and text.count(old) == count else
                     "missing (anchor found %d, probe %d)" % (text.count(old), have))
            print("%-10s %-36s %s" % (name, label, state))
            if state == "ready":
                todo.append(edit)
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, crlf, todo))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, crlf, todo in plans:
        for label, old, new, probe, count in todo:
            assert text.count(old) == count, (path.name, label)
            text = text.replace(old, new)
            assert text.count(probe) == count, (path.name, label, "probe")
        if todo:
            tmp = path.with_name(path.name + ".pipmusic.tmp")
            tmp.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
            os.replace(tmp, path)
            print("wrote %s (%d edit(s), %s)" % (path.name, len(todo), "CRLF" if crlf else "LF"))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

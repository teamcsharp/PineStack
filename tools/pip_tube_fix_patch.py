#!/usr/bin/env python3
"""[pip-tube] The tube never goes blank. 2026-10-06.

"Why are the backgrounds blank?" Two faults in the panel's tube, both of my making last night:
  1. [pip-once] remembered a source as "left" by reading the element's CURRENT source when its tile
     left - the CRT set reuses one <video> for every clip, so the NEXT clip was recorded as already
     shown and never tiled; and a clip change (currentTime back to 0) was read as a rewind.
     The tile now remembers the source it was added for; a rewind counts only for the same source.
  2. A tile has an opaque surface from the moment it is added, and the logo and background hide
     whenever a tile exists - a tile that never draws a frame (a player with no picture yet) is a
     black square over a hidden background. A tile is transparent until it has drawn, and the
     background and logo step aside only for a tile that has drawn; the living background keeps
     running underneath.
Both copies of pine-pip.js.

Usage:  pip_tube_fix_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        pip_tube_fix_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

STYLE_OLD = r'''      + '#pine-pip-panel .pip-tile{position:absolute;overflow:hidden;background:rgb(var(--pip-surface,8 23 19));transform-origin:center}'
'''
STYLE_NEW = r'''      + '#pine-pip-panel .pip-tile{position:absolute;overflow:hidden;background:transparent;transform-origin:center}'
      + '#pine-pip-panel .pip-tile.painted{background:rgb(var(--pip-surface,8 23 19))}'
'''

ACTIVE_OLD = r'''      if (repeatOf(video)) return false;                                  /* [pip-once] */
      const it = tiles.get(video);
      if (it && it.lastTime != null && video.currentTime + 1 < it.lastTime && video.currentTime < 2) { it.rewound = true; }   /* [pip-once] it started over */
      if (it && it.rewound) return false;
'''
ACTIVE_NEW = r'''      const it = tiles.get(video);
      if (!it && repeatOf(video)) return false;                           /* [pip-once] a source already shown is not tiled again */
      /* [pip-tube] a rewind counts only for the SAME source: the set's one element moves on to the next clip with its clock at zero */
      if (it && it.lastTime != null && it.srcKey === srcOf(video) && video.currentTime + 1 < it.lastTime && video.currentTime < 2) { it.rewound = true; }
      if (it && it.rewound) return false;
'''

ADD_OLD = r'''        videos.forEach(v => { if (!tiles.has(v)) { add(v); noteShown(v); } else if (tiles.get(v).leaving) { tiles.get(v).leaving = false; transition(tiles.get(v).tile, true); } });
        tiles.forEach((it, v) => { if (!it.leaving) it.lastTime = v.currentTime; });   /* [pip-once] where each tube's picture stands */
'''
ADD_NEW = r'''        videos.forEach(v => { if (!tiles.has(v)) { add(v); noteShown(v); const made = tiles.get(v); if (made) made.srcKey = srcOf(v); } else if (tiles.get(v).leaving) { tiles.get(v).leaving = false; transition(tiles.get(v).tile, true); } });
        tiles.forEach((it, v) => {
          if (it.leaving) return;
          const key = srcOf(v);
          if (it.srcKey && key && key !== it.srcKey) { noteLeftKey(it.srcKey); it.srcKey = key; it.painted = false; it.tile.classList.remove('painted'); noteShown(v); it.lastTime = null; }   /* [pip-tube] the element moved on to another clip */
          it.lastTime = v.currentTime;
        });
'''

LEAVE_OLD = r'''            it.leaving = true; noteLeft(v);                               /* [pip-once] */
'''
LEAVE_NEW = r'''            it.leaving = true; noteLeftKey(it.srcKey || srcOf(v));         /* [pip-once] the source this tile was for, not whatever the element holds now */
'''

NOTE_OLD = r'''    function noteLeft(v) { const key = srcOf(v); const seen = key ? shownSrc.get(key) : null; if (seen) seen.left = Date.now(); }
'''
NOTE_NEW = r'''    function noteLeftKey(key) { const seen = key ? shownSrc.get(key) : null; if (seen) seen.left = Date.now(); }
'''

PAINT_OLD = r'''        try { it.ctx.drawImage(v, 0, 0, width, height);
'''
PAINT_NEW = r'''        try { it.ctx.drawImage(v, 0, 0, width, height);
          if (!it.painted) { it.painted = true; it.tile.classList.add('painted'); layout(); }   /* [pip-tube] a tile is opaque only once it has a picture */
'''

LAYOUT_OLD = r'''      logo.style.display = count || shell ? 'none' : ''; background.style.display = count || shell ? 'none' : '';
      if (viz) { if (count || shell) viz.stop(); else if (enabled) viz.start(); }   /* [pip-viz] a background under tiles is not drawn */
'''
LAYOUT_NEW = r'''      /* [pip-tube] the logo and the background step aside only for a tile that has drawn a picture; the
         living background keeps running underneath, so a tile without a picture never means a blank tube */
      const covered = items.some(it => it.painted && !it.leaving) || otherCount > 0;
      logo.style.display = covered || shell ? 'none' : ''; background.style.display = shell ? 'none' : '';
      if (viz) { if (shell) viz.stop(); else if (enabled) viz.start(); }
'''

PIPJS = [
    ("a tile is transparent until it has drawn", STYLE_OLD, STYLE_NEW, "#pine-pip-panel .pip-tile.painted{background:rgb(var(--pip-surface,8 23 19))}", 1),
    ("a rewind counts only for the same source", ACTIVE_OLD, ACTIVE_NEW, "if (!it && repeatOf(video)) return false;", 1),
    ("a tile remembers its source and notices a change", ADD_OLD, ADD_NEW, "const made = tiles.get(v); if (made) made.srcKey = srcOf(v);", 1),
    ("leaving remembers the right source", LEAVE_OLD, LEAVE_NEW, "it.leaving = true; noteLeftKey(it.srcKey || srcOf(v));", 1),
    ("noteLeft takes a key", NOTE_OLD, NOTE_NEW, "function noteLeftKey(key) {", 1),
    ("the first picture marks the tile painted", PAINT_OLD, PAINT_NEW, "if (!it.painted) { it.painted = true; it.tile.classList.add('painted'); layout(); }", 1),
    ("the background steps aside only for a picture", LAYOUT_OLD, LAYOUT_NEW, "const covered = items.some(it => it.painted && !it.leaving) || otherCount > 0;", 1),
]
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
            forms = [(old, new, probe)]
            if mode == "mixed":
                forms.append((old.replace("\n", "\r\n"), new.replace("\n", "\r\n"), probe.replace("\n", "\r\n")))
            state = ""
            for old_, new_, probe_ in forms:
                have = text.count(probe_)
                if have == count:
                    state = "applied"
                    break
                if not have and text.count(old_) == count:
                    text = text.replace(old_, new_)
                    assert text.count(probe_) == count, (name, label, "probe after the edit")
                    state, changed = "ready", True
                    break
            if not state:
                state = "missing (anchor found %d, probe %d)" % (text.count(old), text.count(probe))
            print("%-46s %-48s %s" % (name[-46:], label, state))
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
        tmp = path.with_name(path.name + ".piptube.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

#!/usr/bin/env python3
"""[pip-once] A picture the PiP has already shown is not shown again. 2026-10-06.

"Right now two videos are playing next to each other and the video on the left has just been
 playing over and over and over" / "it's still looping this same video while occasionally playing
 new videos". The PiP panel paints every <video> the station page plays as a tile. Whatever
 player on the page starts the same file again, the panel now shows a file ONCE: a video that
 jumps back to its start while on the tube leaves the tube, and the same source coming back
 within ten minutes is not tiled. A video that loops by its own attribute is never program.
 The station's 24 h no-repeat says a clip should not come round anyway; here the display keeps
 that promise whatever the page does. Both copies of pine-pip.js.

Usage:  pip_norepeat_tile_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        pip_norepeat_tile_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

VARS_OLD = r'''    const tiles = new Map();
    const previewSelector = 'video.pav-media,#lightboxVid,#lightboxRefVid,.film video,#galleryGrid video';
'''
VARS_NEW = r'''    const tiles = new Map();
    const previewSelector = 'video.pav-media,#lightboxVid,#lightboxRefVid,.film video,#galleryGrid video';
    /* [pip-once] every source the tube has shown: when, and whether it has left. A source that
       comes back inside SHOWN_ONCE_MS is a repeat and is not tiled; a jump back to the start is one too. */
    const shownSrc = new Map(); const SHOWN_ONCE_MS = 600000;
    function srcOf(v) { return String(v.currentSrc || v.src || (v.srcObject ? 'stream' : '')); }
    function repeatOf(v) {
      if (v.loop) return 'loops';                                        /* a looping element is never program */
      const key = srcOf(v); if (!key || key === 'stream') return '';
      const seen = shownSrc.get(key);
      if (seen && seen.left && Date.now() - seen.left < SHOWN_ONCE_MS) return 'already shown';
      return '';
    }
    function noteShown(v) { const key = srcOf(v); if (key && key !== 'stream') shownSrc.set(key, { at: Date.now(), left: 0 }); if (shownSrc.size > 200) shownSrc.delete(shownSrc.keys().next().value); }
    function noteLeft(v) { const key = srcOf(v); const seen = key ? shownSrc.get(key) : null; if (seen) seen.left = Date.now(); }
'''

ACTIVE_OLD = r'''      if (video.matches(previewSelector)) {
        stopPreview(video);
        return false;
      }
'''
ACTIVE_NEW = r'''      if (video.matches(previewSelector)) {
        stopPreview(video);
        return false;
      }
      if (repeatOf(video)) return false;                                  /* [pip-once] */
      const it = tiles.get(video);
      if (it && it.lastTime != null && video.currentTime + 1 < it.lastTime && video.currentTime < 2) { it.rewound = true; }   /* [pip-once] it started over */
      if (it && it.rewound) return false;
'''

ADD_OLD = r'''        videos.forEach(v => { if (!tiles.has(v)) add(v); else if (tiles.get(v).leaving) { tiles.get(v).leaving = false; transition(tiles.get(v).tile, true); } });
'''
ADD_NEW = r'''        videos.forEach(v => { if (!tiles.has(v)) { add(v); noteShown(v); } else if (tiles.get(v).leaving) { tiles.get(v).leaving = false; transition(tiles.get(v).tile, true); } });
        tiles.forEach((it, v) => { if (!it.leaving) it.lastTime = v.currentTime; });   /* [pip-once] where each tube's picture stands */
'''

LEAVE_OLD = r'''          if (!videos.has(v) && !it.leaving) {
            it.leaving = true;
'''
LEAVE_NEW = r'''          if (!videos.has(v) && !it.leaving) {
            it.leaving = true; noteLeft(v);                               /* [pip-once] */
'''

PIPJS = [
    ("what the tube has shown", VARS_OLD, VARS_NEW, "const shownSrc = new Map(); const SHOWN_ONCE_MS = 600000;", 1),
    ("a repeat is not tiled", ACTIVE_OLD, ACTIVE_NEW, "if (repeatOf(video)) return false;", 1),
    ("a tile notes its source and its clock", ADD_OLD, ADD_NEW, "{ add(v); noteShown(v); }", 1),
    ("a tile that leaves is remembered", LEAVE_OLD, LEAVE_NEW, "it.leaving = true; noteLeft(v);", 1),
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
            print("%-46s %-44s %s" % (name[-46:], label, state))
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
        tmp = path.with_name(path.name + ".piponce.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

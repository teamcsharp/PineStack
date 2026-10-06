#!/usr/bin/env python3
"""[pip-seen] A picture on a PiP tile is a picture seen. 2026-10-06.

In Pine PiP the set's host is hidden (body.pine-pip > :not(...) {display:none}) and the panel
draws the set's <video> on its own tile. The desk's seen-check (sfx-seen.js) measures the
element's own rectangle, so every picture in a PiP hour was receipted "not_shown / zero size":
on 2026-10-05/06, 0 shown of 1,700 on this desk from 21:00 on, while the operator was watching
them on the tile. The panel now answers PinePipPanel.showing(video) with the tile's rectangle
when that element is drawn (painted, not leaving), and measure() takes that answer first; the
receipt carries via:"pip". Both copies of pine-pip.js; sfx-seen.js wherever it exists.

Usage:  pip_seen_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        pip_seen_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

API_OLD = r'''    w.PinePipPanel = { appearance(next) {
'''
API_NEW = r'''    w.PinePipPanel = { showing(video) {
      /* [pip-seen] the tile's rectangle when this element is drawn on one (painted, not leaving), else null -
         the seen-check (sfx-seen.js) measures the element's own box, which is hidden in Pine PiP */
      try {
        const it = video ? tiles.get(video) : null;
        if (!it || !it.painted || it.leaving || host.style.display === 'none' || !host.isConnected) return null;
        const r = it.canvas.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) return null;
        return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) };
      } catch (_) { return null; }
    }, appearance(next) {
'''
MEASURE_OLD = r'''    var out = {rect: {x: 0, y: 0, w: 0, h: 0}, frac: 0, occluder: '', why: ''};
    if (!el || !el.isConnected) { out.why = 'the element left the page'; return out; }
    var r = el.getBoundingClientRect();
'''
MEASURE_NEW = r'''    var out = {rect: {x: 0, y: 0, w: 0, h: 0}, frac: 0, occluder: '', why: ''};
    if (!el || !el.isConnected) { out.why = 'the element left the page'; return out; }
    /* [pip-seen] in Pine PiP the set's host is hidden and the panel draws this element on a tile of its
       own: the tile's rectangle is where the picture is seen, fully, whatever the element's own box says */
    try {
      var pipPanel = root.PinePipPanel;
      var onTile = pipPanel && typeof pipPanel.showing === 'function' ? pipPanel.showing(el) : null;
      if (onTile && onTile.w >= 2 && onTile.h >= 2) { out.rect = onTile; out.frac = 1; out.via = 'pip'; return out; }
    } catch (e) { /* the element's own box, below */ }
    var r = el.getBoundingClientRect();
'''
FIRST_OLD = r'''    r.first_frame_lag_ms = r.first_frame_ms - from;
    var m = measure(o.el, o.own);
    r.rect = m.rect;
'''
FIRST_NEW = r'''    r.first_frame_lag_ms = r.first_frame_ms - from;
    var m = measure(o.el, o.own);
    r.rect = m.rect;
    if (m.via) r.via = m.via;                                /* [pip-seen] seen on a PiP tile */
'''
PIPJS = [("the panel says which elements it draws", API_OLD, API_NEW, "w.PinePipPanel = { showing(video) {", 1)]
SEEN = [
    ("a tile is where the picture is seen", MEASURE_OLD, MEASURE_NEW, "var onTile = pipPanel && typeof pipPanel.showing === 'function' ? pipPanel.showing(el) : null;", 1),
    ("the receipt says it was seen on a tile", FIRST_OLD, FIRST_NEW, "if (m.via) r.via = m.via;", 1),
]
EDITS = {
    "desktop/renderer/pine-pip.js": PIPJS,
    "app/src/main/assets/pine-views/pine-pip.js": PIPJS,
    "desktop/renderer/sfx-seen.js": SEEN,
    "app/src/main/assets/pine-views/sfx-seen.js": SEEN,
}


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
        tmp = path.with_name(path.name + ".pipseen.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

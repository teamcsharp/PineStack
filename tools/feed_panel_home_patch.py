#!/usr/bin/env python3
"""[feed-panel-home] The pause-banking panel lives inside the pane that is showing. 2026-10-06.

"These elements are overlapping on the tablet and the feed display." The
production feed's panel (THE PAUSE IS BANKING) was inserted before #spFeed in
the script page's left column - a six-row grid whose last row is the feed. The
Message view replaces the feed with its own pane (.sp-mv, a flex column) in
that same column, so the panel became a seventh grid child drawn over the
pane's bubbles. The panel now homes itself on every tick: first child of the
visible Message view pane (a flex column makes room for it), else before
#spFeed as before; and it is a normal block there, never an overlay.

desktop/renderer/production-feed.js and .css (the kiosk's copies follow the
share through deploy.sh's sync).

Usage:  feed_panel_home_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        feed_panel_home_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

BUILD_OLD = '''    ui.box.appendChild(ui.head);
    ui.box.appendChild(ui.list);
    feed.parentNode.insertBefore(ui.box, feed);
    return ui.box;
  }
'''
BUILD_NEW = '''    ui.box.appendChild(ui.head);
    ui.box.appendChild(ui.list);
    feed.parentNode.insertBefore(ui.box, feed);
    return ui.box;
  }
  /* [feed-panel-home] the panel sits inside whichever pane is showing: first child of the
     Message view pane (a flex column, so the bubbles move down), else before the feed */
  function home() {
    if (!ui.box) return;
    var feed = document.getElementById('spFeed');
    var pane = document.getElementById('spMsgView');
    var paneUp = !!(pane && pane.style.display !== 'none' && pane.offsetParent !== null);
    if (paneUp) {
      if (ui.box.parentNode !== pane || pane.firstChild !== ui.box) pane.insertBefore(ui.box, pane.firstChild);
    } else if (feed && feed.parentNode && (ui.box.parentNode !== feed.parentNode || ui.box.nextSibling !== feed)) {
      feed.parentNode.insertBefore(ui.box, feed);
    }
  }
'''

TICK_OLD = '''  function tick() {
    if (!ui.on || ui.busy) return;
    if (!build()) return;
'''
TICK_NEW = '''  function tick() {
    if (!ui.on || ui.busy) return;
    if (!build()) return;
    try { home(); } catch (e) { /* [feed-panel-home] a pane mid-rebuild */ }
'''

CSS_OLD = '''.pf-panel[hidden] { display: none; }
'''
CSS_NEW = '''.pf-panel[hidden] { display: none; }
/* [feed-panel-home] inside the Message view pane: a block of its own, never an overlay */
.sp-mv > .pf-panel { position: relative; z-index: 2; flex: none; margin: 8px 8px 0; max-height: 44%; overflow: auto; }
'''

EDITS = {
    "desktop/renderer/production-feed.js": [
        ("the panel knows where its home is", BUILD_OLD, BUILD_NEW, 1),
        ("...and goes there on every tick", TICK_OLD, TICK_NEW, 1),
    ],
    "desktop/renderer/production-feed.css": [
        ("inside the Message view it is a block", CSS_OLD, CSS_NEW, 1),
    ],
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
        tmp = path.with_suffix(path.suffix + ".pfhome.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

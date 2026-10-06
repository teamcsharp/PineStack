#!/usr/bin/env python3
"""[works-portable] [tools-view] The Works as a portable popup and a tablet view. 2026-10-06.

"Make 'the works' able to be used as a popup in PineApp and able to be used by the
pineTab."

New files (copied beside this tool by the deploy helper, both copies):
  desktop/renderer/the-works.js / .css          PineTheWorks: mount(host,{get}) / open() / close()
  desktop/renderer/pine-tools-view.js / .css    PineToolsView: the tablet's TOOLS tab, a list of
                                                 every portable tool loaded on the screen; open()
                                                 makes it a popup elsewhere
This tool wires them: the desk page loads them (index.html); the rail gets a TOOLS tab
(rail.js, both copies). The PiP's popup catalog lists PineTheWorks and PineToolsView on
its own, because they have open().

Usage:  works_portable_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        works_portable_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

CSS_OLD = '''  <link rel="stylesheet" href="./blocked-book.css">  <!-- [blocked-book] -->
'''
CSS_NEW = '''  <link rel="stylesheet" href="./blocked-book.css">  <!-- [blocked-book] -->
  <link rel="stylesheet" href="./the-works.css">  <!-- [works-portable] -->
  <link rel="stylesheet" href="./pine-tools-view.css">  <!-- [tools-view] -->
'''
JS_OLD = '''  <script src="./blocked-book.js"></script>  <!-- [blocked-book] the second tab of The Works -->
'''
JS_NEW = '''  <script src="./blocked-book.js"></script>  <!-- [blocked-book] the second tab of The Works -->
  <script src="./the-works.js"></script>  <!-- [works-portable] The Works as a popup and a view -->
  <script src="./pine-tools-view.js"></script>  <!-- [tools-view] the tablet's TOOLS tab -->
'''
RAIL_OLD = '''    {id: 'slideshow', cls: 'sl-host', label: 'SLIDES',
      mount: ['PineSlideshow']}
  ];
'''
RAIL_NEW = '''    {id: 'slideshow', cls: 'sl-host', label: 'SLIDES',
      mount: ['PineSlideshow']},
    /* [tools-view] the portable tools - The Works, the LLM command table, the
     * hour flow, the blocked book - behind one tab; the rail scrolls past
     * eight (#1345), so a ninth is no longer a tab nobody can reach. */
    {id: 'tools', cls: 'ptv-view', label: 'TOOLS', mount: ['PineToolsView']}
  ];
'''

EDITS = {
    "desktop/renderer/index.html": [
        ("the desk page loads the styles", CSS_OLD, CSS_NEW, 1),
        ("the desk page loads the modules", JS_OLD, JS_NEW, 1),
    ],
    "desktop/renderer/rail.js": [("the rail's TOOLS tab", RAIL_OLD, RAIL_NEW, 1)],
    "app/src/main/assets/pine-views/rail.js": [("the rail's TOOLS tab (tablet copy)", RAIL_OLD, RAIL_NEW, 1)],
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
        tmp = path.with_suffix(path.suffix + ".worksport.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

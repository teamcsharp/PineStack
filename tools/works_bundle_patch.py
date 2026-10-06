#!/usr/bin/env python3
"""[works-bundle] The tablet's view bundle lists The Works, the blocked book and the TOOLS tab. 2026-10-06.

The three modules were committed into app/src/main/assets/pine-views (6174e9a, 6a4205d) and the
bundle list was edited only in the build PC's checkout; mainline's ViewAssets.kt never learned
them, so a tablet built from mainline would carry the files and never inject them.

Edits (CRLF kept where the file has it):
  app/src/main/java/com/pinebox/kiosk/bridge/ViewAssets.kt
      SCRIPTS: blocked-book.js, the-works.js, pine-tools-view.js before rail.js (rail mounts them)
      STYLES:  blocked-book.css, the-works.css, pine-tools-view.css after view-chrome.css

Usage:  works_bundle_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        works_bundle_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

KT_JS_OLD = '''        "deaf-watch.js",
        "rail.js",                // it looks for the globals above
'''
KT_JS_NEW = '''        "deaf-watch.js",
        "blocked-book.js",        // [blocked-book] the blocked book (The Works' second tab)
        "the-works.js",           // [works-portable] The Works: the rooms and the blocked book
        "pine-tools-view.js",     // [tools-view] the TOOLS tab: every portable tool on this screen
        "rail.js",                // it looks for the globals above
'''
KT_CSS_OLD = '''        "view-chrome.css",
        "changelog.css",          // the Git task history panel
'''
KT_CSS_NEW = '''        "view-chrome.css",
        "blocked-book.css",       // [blocked-book]
        "the-works.css",          // [works-portable]
        "pine-tools-view.css",    // [tools-view]
        "changelog.css",          // the Git task history panel
'''

EDITS = {
    "app/src/main/java/com/pinebox/kiosk/bridge/ViewAssets.kt": [
        ("the tablet's view bundle carries the three Works scripts", KT_JS_OLD, KT_JS_NEW, 1),
        ("the tablet's view bundle carries the three Works stylesheets", KT_CSS_OLD, KT_CSS_NEW, 1),
    ],
}

COPIES: list = []


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def modules_dir() -> Path:
    env = os.environ.get("WORKS_BUNDLE_MODULES")
    return Path(env) if env else Path(__file__).resolve().parent.parent / "modules"


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
            print("%-46s MISSING FILE" % name)
            missing = True
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
                print("%-78s applied" % label[:78])
                continue
            n = text.count(old)
            if n == want:
                print("%-78s ready" % label[:78])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-78s MISSING (anchor count %d, wanted %d)" % (label[:78], n, want))
                missing = True
        if changed:
            plans.append((path, text, mode, bom))
    copies = []
    src_dir = modules_dir()
    for src_name, dest_rel in COPIES:
        src = src_dir / src_name
        dest = root / dest_rel
        label = "copy %s -> %s" % (src_name, dest_rel)
        if not src.exists():
            print("%-78s MISSING (no module at %s)" % (label[:78], src))
            missing = True
            continue
        if not dest.parent.exists():
            print("%-78s MISSING (no folder %s)" % (label[:78], dest.parent))
            missing = True
            continue
        data = src.read_bytes()
        if dest.exists() and dest.read_bytes() == data:
            print("%-78s applied" % label[:78])
            continue
        print("%-78s ready" % label[:78])
        ready = True
        copies.append((dest, data))
    if missing:
        print("anchors or files missing - nothing applied")
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
        tmp = path.with_suffix(path.suffix + ".worksbundle.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    for dest, data in copies:
        tmp = dest.with_suffix(dest.suffix + ".worksbundle.tmp")
        tmp.write_bytes(data)
        tmp.replace(dest)
        print("copied %s" % dest)
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

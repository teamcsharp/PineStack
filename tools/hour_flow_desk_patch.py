#!/usr/bin/env python3
"""[hour-flow] The desk and the tablet carry PineHourFlow; every hour entry gets a "flow" button. 2026-10-06.

"convert 'the hour' view for a segment into a vertical flowchart ... back button
... same style as the script view flowchart"       - the operator, 2026-10-06

Edits (CRLF kept where the file has it; renderer.js is LF):
  desktop/renderer/renderer.js      worksSchedule: a "flow" button on every entry row (after the
                                    minutes) opens PineHourFlow.open({road, kind, slot_id, label,
                                    hour, onBack}); the hour sheet steps aside and comes back on Back.
  desktop/renderer/index.html       <link hour-flow.css> after blocked-book.css; <script hour-flow.js>
                                    after blocked-book.js (the PiP tools catalog scans index.html
                                    and finds window.PineHourFlow.open on its own).
  app/src/main/java/com/pinebox/kiosk/bridge/ViewAssets.kt
                                    "hour-flow.js" after flow-chart.js, "hour-flow.css" after
                                    flow-chart.css: the tablet's view bundle carries the module.
Copies (the module itself, from ../modules beside this tool, or $HOUR_FLOW_MODULES):
  desktop/renderer/hour-flow.js, desktop/renderer/hour-flow.css
  app/src/main/assets/pine-views/hour-flow.js, app/src/main/assets/pine-views/hour-flow.css

Usage:  hour_flow_desk_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors or files missing
        hour_flow_desk_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

RENDERER_OLD = '''      const mins = mk("span", "wk-note", s.minutes + "m");
      mins.style.cssText = "font-size:10px;opacity:.7";
      top.appendChild(mins);
'''
RENDERER_NEW = '''      const mins = mk("span", "wk-note", s.minutes + "m");
      mins.style.cssText = "font-size:10px;opacity:.7";
      top.appendChild(mins);
      /* [hour-flow] this entry's conversation as a vertical flowchart: its
       * turns in order, to add, remove, insert, move, extend and deepen -
       * for THIS entry only or for every entry of its kind (the toggle is
       * inside). The hour sheet steps aside while it is open and comes
       * back on Back. A record has no conversation to shape. */
      if (window.PineHourFlow && s.kind !== "record") {
        const flow = mk("button", "wk-pill", "flow");
        flow.title = "Open this entry's conversation as a flowchart: add, "
          + "remove, move and extend its turns, and give any turn inner "
          + "exchanges - for this entry only, or for every "
          + String(s.kind || "such") + " entry";
        flow.style.cssText = "font-size:9.5px;padding:1px 6px";
        flow.onclick = (ev) => {
          ev.stopPropagation();
          pop.style.display = "none";
          window.PineHourFlow.open({
            road: s.kind === "banter_caller" ? "caller" : s.kind, kind: s.kind,
            slot_id: s.id, label: s.label || s.kind, hour: hour.key,
            onBack: () => { pop.style.display = ""; },
          });
        };
        top.appendChild(flow);
      }
'''

INDEX_CSS_OLD = '''  <link rel="stylesheet" href="./blocked-book.css">  <!-- [blocked-book] -->
'''
INDEX_CSS_NEW = '''  <link rel="stylesheet" href="./blocked-book.css">  <!-- [blocked-book] -->
  <link rel="stylesheet" href="./hour-flow.css">  <!-- [hour-flow] the hour's entry as a vertical flowchart -->
'''
INDEX_JS_OLD = '''  <script src="./blocked-book.js"></script>  <!-- [blocked-book] the second tab of The Works -->
'''
INDEX_JS_NEW = '''  <script src="./blocked-book.js"></script>  <!-- [blocked-book] the second tab of The Works -->
  <script src="./hour-flow.js"></script>  <!-- [hour-flow] PineHourFlow: the hour's entry as a vertical flowchart editor -->
'''

KT_JS_OLD = '''        "flow-chart.js",        // [flowchart] the conversation as a growing flowchart (script view toggle)
'''
KT_JS_NEW = '''        "flow-chart.js",        // [flowchart] the conversation as a growing flowchart (script view toggle)
        "hour-flow.js",         // [hour-flow] the hour's entry as a vertical flowchart editor
'''
KT_CSS_OLD = '''        "flow-chart.css",       // [flowchart] the conversation as a growing flowchart
'''
KT_CSS_NEW = '''        "flow-chart.css",       // [flowchart] the conversation as a growing flowchart
        "hour-flow.css",        // [hour-flow] the hour's entry as a vertical flowchart editor
'''

EDITS = {
    "desktop/renderer/renderer.js": [
        ("worksSchedule: a flow button on every entry row opens PineHourFlow", RENDERER_OLD, RENDERER_NEW, 1),
    ],
    "desktop/renderer/index.html": [
        ("index.html carries hour-flow.css", INDEX_CSS_OLD, INDEX_CSS_NEW, 1),
        ("index.html carries hour-flow.js", INDEX_JS_OLD, INDEX_JS_NEW, 1),
    ],
    "app/src/main/java/com/pinebox/kiosk/bridge/ViewAssets.kt": [
        ("the tablet's view bundle carries hour-flow.js", KT_JS_OLD, KT_JS_NEW, 1),
        ("the tablet's view bundle carries hour-flow.css", KT_CSS_OLD, KT_CSS_NEW, 1),
    ],
}

COPIES = [
    ("hour-flow.js", "desktop/renderer/hour-flow.js"),
    ("hour-flow.css", "desktop/renderer/hour-flow.css"),
    ("hour-flow.js", "app/src/main/assets/pine-views/hour-flow.js"),
    ("hour-flow.css", "app/src/main/assets/pine-views/hour-flow.css"),
]


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def modules_dir() -> Path:
    env = os.environ.get("HOUR_FLOW_MODULES")
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
        tmp = path.with_suffix(path.suffix + ".hourflow.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    for dest, data in copies:
        tmp = dest.with_suffix(dest.suffix + ".hourflow.tmp")
        tmp.write_bytes(data)
        tmp.replace(dest)
        print("copied %s" % dest)
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

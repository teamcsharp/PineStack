#!/usr/bin/env python3
"""[plquiet] The PineLive panel's status row: two silence sliders + a readout.

Desk (desktop/renderer) and kiosk (app/src/main/assets/pine-views) get the
same edits, so the two copies stay identical.
- pinelive.js: the say line moves into a .pl-sayrow with the sliders beside it
  (build), the slider code goes in before paintCountdown(), paint() calls
  paintQuiet(); the Album switch's tooltip names the live split; the Event
  settings "Silence for" box takes the slider's 10-180 s range.
- pinelive.css: the row's styles, after .pl-say[hidden].

    python3 edit_plquiet_renderer.py --check|--apply <repo root>
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from qpatch import InsertAfter, InsertBefore, Replace, main  # noqa: E402

BLOCK = (HERE / "quiet_block.js").read_text(encoding="utf-8")
CSS = (HERE / "quiet_block.css").read_text(encoding="utf-8")


def js_edits():
    return [
        Replace("    ui.sayLine.setAttribute('role', 'status');\n"
                "    pop.appendChild(ui.sayLine);\n",
                "    ui.sayLine.setAttribute('role', 'status');\n"
                "    /* [plquiet] the status row: the say line, then the two silence sliders */\n"
                "    var sayRow = make('div', 'pl-sayrow');\n"
                "    sayRow.appendChild(ui.sayLine);\n"
                "    sayRow.appendChild(buildQuiet());\n"
                "    pop.appendChild(sayRow);\n",
                "sayRow.appendChild(buildQuiet());", "build: the status row"),
        InsertBefore("  function paintCountdown() {\n", BLOCK,
                     "  function buildQuiet() {", "the slider code"),
        InsertBefore("    PANEL_ORDER.forEach(function (id) {\n"
                     "      var p = ui.panels[id];\n"
                     "      var open = !!ui.open[id];\n",
                     "    try { paintQuiet(); }                                          /* [plquiet] */\n"
                     "    catch (err) { if (root.console) root.console.error('[pinelive] silence sliders paint failed:', err); }\n",
                     "try { paintQuiet(); }", "paint() hook"),
        Replace("(split on 10 s of silence)",
                "(split on ' + quietSecs('split_seconds') + ' s of silence)",
                "(split on ' + quietSecs('split_seconds') + ' s of silence)", "album tooltip"),
        Replace("silence_seconds: numberRow({label: 'Silence for', caption: 'frames arrive but below the floor', min: 1, max: 600, step: 1, unit: 's'},",
                "silence_seconds: numberRow({label: 'Silence for', caption: 'frames arrive but below the floor - then the DJ gets the music back (the slider under the header)', min: 10, max: 180, step: 1, unit: 's'},",
                "(the slider under the header)', min: 10, max: 180,", "Event settings range"),
    ]


def css_edits():
    return [InsertAfter(".pl-say[hidden] { display: none; }\n", CSS,
                        "[plquiet] the status row", "status row styles")]


PLAN = {}
for base in ("desktop/renderer", "app/src/main/assets/pine-views"):
    PLAN[base + "/pinelive.js"] = js_edits()
    PLAN[base + "/pinelive.css"] = css_edits()

if __name__ == "__main__":
    sys.exit(main(PLAN))

#!/usr/bin/env python3
"""[memprefs] The tablet memory limits are preferences (operator 2026-09-29).

Defaults the operator chose: 50 bubbles of Message-view history, 2 playing muted
loops (plus a pinned one), and a 48 MB replay ring that may be raised back to
100 MB. Stored per device (localStorage; the ring also in the kiosk's own prefs
through the pineDesktop.memPrefs bridge verb). Set in the file manager (the disk
icon) under "Memory"; they take effect the next time the app starts (the ring:
the next time the tablet's screen wakes).

usage: edit_memprefs.py --check|--apply <spark-agent root>   (0 ready, 2 applied, 1 missing)
"""
import sys
from pathlib import Path

MARK = "[memprefs]"
DIRS = ["desktop/renderer", "app/src/main/assets/pine-views"]
EDITS = {
    "pine-memory.js": [(
        "  var CAP = 2, OFF_MS = 1500, DETACH_MS = 2000;\n",
        "  var CAP = (function () {   /* [memprefs] the operator's loop limit, default 2 */\n"
        "    try { var v = parseInt(root.localStorage.getItem('pine.mem.loops'), 10); return v >= 1 && v <= 6 ? v : 2; }\n"
        "    catch (e) { return 2; }\n"
        "  })(), OFF_MS = 1500, DETACH_MS = 2000;\n")],
    "script-page.js": [(
        "  var MV_HIST_MAX = 200;",
        "  var MV_HIST_MAX = (function () {   /* [memprefs] the operator's history limit, default 50 */\n"
        "    try { var v = parseInt(root.localStorage.getItem('pine.mem.history'), 10); return v >= 20 && v <= 300 ? v : 50; }\n"
        "    catch (e) { return 50; }\n"
        "  })();")],
    "filemgr.js": [(
        "    foot.appendChild(qs);\n    pop.appendChild(foot);\n",
        "    foot.appendChild(qs);\n"
        "    /* [memprefs] the tablet's memory limits, as preferences */\n"
        "    var ms = make('div', 'fm-restore fm-memprefs');\n"
        "    var mh = make('div', 'fm-restore-head');\n"
        "    mh.appendChild(ico('c:save', ''));\n"
        "    mh.appendChild(make('span', '', 'Memory (this device) - applies the next time the app starts'));\n"
        "    ms.appendChild(mh);\n"
        "    var memPref = function (key, def) {\n"
        "      try { var v = parseInt(root.localStorage.getItem(key), 10); return isNaN(v) ? def : v; } catch (e) { return def; }\n"
        "    };\n"
        "    var memRow = function (label, key, def, lo, hi, step, unit, after) {\n"
        "      var row = make('label', 'fm-memrow');\n"
        "      row.appendChild(make('span', 'fm-memlabel', label));\n"
        "      var inp = make('input', ''); inp.type = 'range'; inp.min = lo; inp.max = hi; inp.step = step;\n"
        "      inp.value = memPref(key, def); inp.title = label + ' (default ' + def + unit + ')';\n"
        "      var val = make('span', 'fm-memval', inp.value + unit);\n"
        "      inp.addEventListener('input', function () { val.textContent = inp.value + unit; });\n"
        "      inp.addEventListener('change', function () {\n"
        "        try { root.localStorage.setItem(key, String(inp.value)); } catch (e) { /* private window */ }\n"
        "        if (after) { try { after(parseInt(inp.value, 10)); } catch (e) { /* no bridge */ } }\n"
        "      });\n"
        "      row.appendChild(inp); row.appendChild(val);\n"
        "      ms.appendChild(row);\n"
        "    };\n"
        "    memRow('Message history', 'pine.mem.history', 50, 20, 300, 10, ' bubbles');\n"
        "    memRow('Playing muted loops (plus a pinned one)', 'pine.mem.loops', 2, 1, 6, 1, '');\n"
        "    memRow('Screen replay ring', 'pine.mem.replay', 48, 16, 100, 4, ' MB', function (mb) {\n"
        "      var b = root.pineDesktop;\n"
        "      if (b && typeof b.memPrefs === 'function') b.memPrefs({replayMb: mb});\n"
        "    });\n"
        "    foot.appendChild(ms);\n"
        "    pop.appendChild(foot);\n")],
}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    root = Path(sys.argv[2] if len(sys.argv) > 2 else ".")
    todo, rc = [], 0
    for d in DIRS:
        for name, edits in EDITS.items():
            p = root / d / name
            raw = p.read_bytes().decode("utf-8")
            crlf = "\r\n" in raw
            text = raw.replace("\r\n", "\n")
            if MARK in text:
                print("applied ", p); continue
            for old, _ in edits:
                if text.count(old) != 1:
                    print("MISSING ", p, repr(old[:50])); rc = 1
            todo.append((p, text, crlf, edits))
    if rc:
        return 1
    if mode != "--apply":
        print(MARK, "ready" if todo else "already applied"); return 0 if todo else 2
    for p, text, crlf, edits in todo:
        for old, new in edits:
            text = text.replace(old, new, 1)
        if crlf:
            text = text.replace("\n", "\r\n")
        p.write_bytes(text.encode("utf-8"))
        print("APPLIED ", p)
    return 2


if __name__ == "__main__":
    sys.exit(main())

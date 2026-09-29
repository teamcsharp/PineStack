#!/usr/bin/env python3
"""[cambattery2] the Pine Cam meter leads with time left (pine-cam.js / .css).

    python3 edit_cambattery2_ui.py --check <dir>   # 0 ready, 2 applied, 1 anchors missing
    python3 edit_cambattery2_ui.py --apply <dir>

Needs the wave-BB [cambattery] edit already in <dir>. Run it on desktop/renderer,
app/src/main/assets/pine-views (the repo's kiosk mirror) and the kiosk project's
app/src/main/assets/pine-views; the three come out identical. No new file.

  * the meter's text is the station's `label` ("~25 min left · estimate",
    "under 5 min left", "charging", "camera went dark – battery likely flat");
    the level word and the basis of the estimate move to the title;
  * went dark: greyed, never pulsing; a card (the existing toast's shape) on
    the poll that sees it, and a `battery` row + the row's brief on the desk;
  * the native badge takes the same text through pineCam('battery') - the
    kiosk needs only these assets, no Kotlin.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

MARK = "[cambattery2]"
V1 = "[cambattery]"

JS_EDITS = [
    ("battModel(): the text",
     "    var text = b.charging ? 'charging' : String(b.word || '?');\n"
     "    if (!b.charging && b.left_say && !stale) {\n"
     "      text += ' · ' + (Number(b.left_s) < 120 ? 'any minute' : '~' + b.left_say);\n"
     "    }\n"
     "    if (stale) text += ' · stale';\n",
     "    /* [cambattery2] TIME LEFT LEADS. \"Instead of saying last bar, I would\n"
     "     * like a time estimate of how much time is left in the battery.\" The\n"
     "     * station words it (`label`); the level word is in the title. */\n"
     "    var dark = !!b.dark;\n"
     "    var text = String(b.label || (b.charging ? 'charging' : (b.word || '?')));\n"
     "    if (stale && !dark) text += ' · stale';\n"),
    ("battModel(): tone and pulse",
     "            tone: stale ? 'stale' : String(b.tone || 'ok'),\n"
     "            pulse: !!b.pulse && !stale, stale: stale, charging: !!b.charging};\n",
     "            tone: (stale || dark) ? 'stale' : String(b.tone || 'ok'),   /* [cambattery2] */\n"
     "            pulse: !!b.pulse && !stale && !dark, stale: stale || dark,\n"
     "            charging: !!b.charging, dark: dark};\n"),
    ("paintBattery(): not live",
     "    var m = (isLive === false) ? null : battModel(batt);\n",
     "    /* [cambattery2] a camera that went dark keeps its greyed meter */\n"
     "    var m = (isLive === false && !(batt && batt.dark)) ? null : battModel(batt);\n"
     "    battDarkTell(batt);\n"),
    ("paintRow(): brief",
     "    paintBars(isLive, seen, stale, Number(got.signal || 0));\n",
     "    if (!isLive && got.battery && got.battery.dark) {       /* [cambattery2] */\n"
     "      brief.textContent = 'camera went dark – battery likely flat';\n"
     "    }\n"
     "    paintBars(isLive, seen, stale, Number(got.signal || 0));\n"),
    ("paintRow(): rows",
     "    stats.innerHTML = rows.map(function (r) {\n",
     "    if (got.battery && got.battery.ok) rows.splice(3, 0, ['battery', battRowSay(got.battery)]);   /* [cambattery2] */\n"
     "    stats.innerHTML = rows.map(function (r) {\n"),
]

JS_BLOCK_ANCHOR = "  function paintBatteryNative(m) {\n"
JS_BLOCK = r"""  /* [cambattery2] THE DESK'S ROW, AND THE CARD WHEN THE CAMERA GOES DARK.
   * The box closes when the link goes (#1387: no still of a gone camera),
   * so a flat battery is said where it can still be seen: the row reads
   * it with the last estimate and its age, and one card says it on the
   * poll that first sees it (never on a page load onto an old one). */
  var battDarkSeen = null;

  function battRowSay(b) {
    if (!b || !b.ok) return '—';
    if (b.dark) {
      return 'camera went dark – battery likely flat'
        + (b.dark_was ? ' · was ' + b.dark_was : '')
        + ', ' + battAgeSay(Number(b.dark_age_s || 0)) + ' ago';
    }
    var age = battAge(b);
    return String(b.label || b.word || '')
      + (b.charging ? '' : ' (' + String(b.word || '') + ')')
      + (age > BATT_STALE_S ? ' · stale, read ' + battAgeSay(age) + ' ago' : '');
  }

  function battDarkTell(b) {
    var at = (b && b.dark) ? Number(b.dark_at || 0) : 0;
    if (battDarkSeen === null) { battDarkSeen = at; return; }
    if (!at) { battDarkSeen = 0; return; }
    if (at === battDarkSeen) return;
    battDarkSeen = at;
    if (!document.body) return;
    hideToast();
    toast = document.createElement('div');
    toast.id = 'pineCamToast';
    toast.className = 'pine-cam-toast pine-cam-toast--dark';
    toast.setAttribute('role', 'status');
    toast.title = String(b.what || '');
    toast.innerHTML =
      '<i class="pine-cam-flag-dot"></i>'
      + '<div class="pine-cam-toast-text"><b>The Pine Cam went dark</b><span>'
      + 'battery likely flat' + (b.dark_was ? ' · the last estimate was ' + esc(b.dark_was) : '')
      + '</span></div>'
      + '<button type="button" class="pine-cam-x" aria-label="Dismiss" title="Dismiss">×</button>';
    toast.addEventListener('click', function (ev) { ev.stopPropagation(); hideToast(); });
    document.body.appendChild(toast);
    toastTimer = setTimeout(hideToast, TOAST_MS);
  }

"""

CSS_ANCHOR = ".pine-cam-pip .pine-cam-batt { font-size: 10px; left: 4px; top: 4px; }\n"
CSS_ADD = (".pine-cam-pip .pine-cam-batt { font-size: 10px; left: 4px; top: 4px; }\n"
           "/* [cambattery2] the camera went dark: a still, grey card */\n"
           ".pine-cam-toast--dark .pine-cam-flag-dot { background: #99a3a8; box-shadow: none; animation: none; }\n")


def patch_js(text: str) -> tuple[int, str, str]:
    if MARK in text:
        return 2, text, "already applied"
    if V1 not in text:
        return 1, text, "anchor missing: the wave-BB [cambattery] edit (apply edit_cambattery_ui.py first)"
    miss = [n for n, a, _ in JS_EDITS if text.count(a) != 1]
    if text.count(JS_BLOCK_ANCHOR) != 1:
        miss.append("paintBatteryNative()")
    if miss:
        return 1, text, "anchor missing or not unique: " + ", ".join(miss)
    for _, a, n in JS_EDITS:
        text = text.replace(a, n, 1)
    text = text.replace(JS_BLOCK_ANCHOR, JS_BLOCK + JS_BLOCK_ANCHOR, 1)
    return 0, text, "ok"


def patch_css(text: str) -> tuple[int, str, str]:
    if MARK in text:
        return 2, text, "already applied"
    if text.count(CSS_ANCHOR) != 1:
        return 1, text, "anchor missing: the wave-BB [cambattery] pip rule"
    return 0, text.replace(CSS_ANCHOR, CSS_ADD, 1), "ok"


def run(path: Path, fn, apply: bool) -> int:
    raw = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    code, out, say = fn(raw.replace("\r\n", "\n"))
    print("%s: %s" % (path, say))
    if code != 0 or not apply:
        return code
    if crlf:
        out = out.replace("\n", "\r\n")
    tmp = path.with_name(path.name + ".cambattery2.tmp")
    tmp.write_bytes(out.encode("utf-8"))
    os.replace(tmp, path)
    print("%s: APPLIED" % path)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    d = Path(argv[2])
    pairs = (("pine-cam.js", patch_js), ("pine-cam.css", patch_css))
    codes = [run(d / n, f, False) for n, f in pairs]
    if 1 in codes:
        return 1
    if 0 not in codes:
        return 2
    if argv[1] == "--apply":
        for (n, f), c in zip(pairs, codes):
            if c == 0:
                run(d / n, f, True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

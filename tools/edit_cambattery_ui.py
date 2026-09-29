#!/usr/bin/env python3
"""[cambattery] the battery meter on every Pine Cam picture (pine-cam.js / .css).

    python3 edit_cambattery_ui.py --check <dir>   # 0 ready, 2 applied, 1 anchors missing
    python3 edit_cambattery_ui.py --apply <dir>

<dir> holds pine-cam.js and pine-cam.css: run it on desktop/renderer AND on
app/src/main/assets/pine-views (the repo's kiosk mirror) AND on the kiosk
project's app/src/main/assets/pine-views - the three copies stay identical.
Marker-idempotent ([cambattery]); CRLF-aware; atomic. No new file, so no
ViewAssets.kt entry.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

MARK = "[cambattery]"

JS_EDITS = [
    # 1. the element, over the picture's top-left, inside the box
    ("build(): the <img>",
     "      + '<img id=\"pineCamImg\" alt=\"The Pine Cam, live\">';\n",
     "      + '<img id=\"pineCamImg\" alt=\"The Pine Cam, live\">'\n"
     "      /* [cambattery] the camera's battery, over the picture's top-left */\n"
     "      + '<div class=\"pine-cam-batt\" id=\"pineCamBatt\" hidden></div>';\n"),
    # 2. the header folds: the picture moves by one bar, so does the meter
    ("setBare(): the class",
     "    box.classList.toggle('pine-cam-bare', bare);\n",
     "    box.classList.toggle('pine-cam-bare', bare);\n"
     "    battPlace();                           /* [cambattery] */\n"),
    # 3. every poll paints it
    ("look(): paintRow",
     "      paintRow(got, live);\n",
     "      paintRow(got, live);\n"
     "      paintBattery(got && got.battery, live);   /* [cambattery] after the pip exists */\n"),
    # 4. a fresh native surface is told the reading at once
    ("nativeStart(): nativeBox",
     "      nativeBox();                         /* the box may have moved while asked */\n",
     "      nativeBox();                         /* the box may have moved while asked */\n"
     "      battNativeKey = '';                  /* [cambattery] a new surface: tell it again */\n"
     "      paintBatteryNative(battModel(batt));\n"),
    # 5. a console / harness door
    ("PineCam: announce",
     "    announce: function () { return post('/api/pinelink/announce', {}); }};\n",
     "    announce: function () { return post('/api/pinelink/announce', {}); },\n"
     "    /* [cambattery] paint a reading (a /api/pinelink/state `battery`), or read the last */\n"
     "    battery: function (b, isLive) { return b === undefined ? batt : paintBattery(b, isLive); }};\n"),
]

JS_BLOCK_ANCHOR = "  function look() {\n"
JS_BLOCK = r"""  /* [cambattery] THE CAMERA'S BATTERY, TOP-LEFT OF EVERY PICTURE.
   *
   * "display a battery meter indicating the battery amount in the top left
   * corner of the pine cam ... so I can see how much battery's in the
   * camera at all times and know how long I have left in the stream."
   *
   * The station asks the camera (Novatek cmd 3019) every 45 s while the
   * link is live and hands the reading on as /api/pinelink/state
   * `battery`. The camera reports a LEVEL - full, half, low, last bar,
   * empty, or charging - never a percentage, so the meter fills bars of
   * four and says the word; the time left appears only once the station
   * has watched a whole level go by, and is never guessed before that.
   * Amber at low (~30%), red on the last bar (~15%), a gentle pulse at
   * empty (10% and under). Older than three minutes it greys and says
   * "stale". The title carries the exact reading and its age.
   *
   * Three pictures carry it: the box (an element over the <img>'s top-
   * left), the card's pip on the desktop, and the tablet's NATIVE surface
   * - which no page element can paint over (the media-overlay SurfaceView
   * is composited ABOVE the WebView), so the same reading is handed to
   * the kiosk as pineCam('battery', ...) and PineCamWall draws it in the
   * surface's own top-left. A kiosk without the verb answers "no such
   * pineCam verb" and nothing else happens. Carbon has no battery glyph
   * in the vendored set, so the gauge is drawn (like the signal bars) and
   * charging wears c:lightning. */
  var BATT_STALE_S = 180;
  var batt = null;             /* the last reading, stamped with this page's clock */
  var battNativeKey = '';

  function battAge(b) {
    if (!b || !b.ok) return Infinity;
    var since = b._got ? Math.max(0, (Date.now() - b._got) / 1000) : 0;
    return Number(b.age_s || 0) + since;
  }

  function battAgeSay(s) {
    if (!isFinite(s)) return 'never';
    if (s < 90) return Math.round(s) + ' s';
    if (s < 5400) return Math.round(s / 60) + ' min';
    return (s / 3600).toFixed(1) + ' h';
  }

  function battModel(b) {
    if (!b || !b.ok) return null;
    var age = battAge(b);
    var stale = age > BATT_STALE_S;
    var text = b.charging ? 'charging' : String(b.word || '?');
    if (!b.charging && b.left_say && !stale) {
      text += ' · ' + (Number(b.left_s) < 120 ? 'any minute' : '~' + b.left_say);
    }
    if (stale) text += ' · stale';
    var title = String(b.what || b.say || 'Pine Cam battery')
      + '. Read ' + battAgeSay(age) + ' ago'
      + (stale ? ' - STALE: the camera has not answered since' + (b.error ? ' (' + b.error + ')' : '') : '')
      + '.';
    return {text: text, title: title,
            bars: b.charging ? -1 : Math.max(0, Math.min(4, Number(b.bars) || 0)),
            tone: stale ? 'stale' : String(b.tone || 'ok'),
            pulse: !!b.pulse && !stale, stale: stale, charging: !!b.charging};
  }

  function battHtml(m) {
    var cells = '';
    for (var i = 0; i < 4; i++) cells += '<i' + (i < m.bars ? ' class="on"' : '') + '></i>';
    return '<span class="pine-cam-batt-cell" aria-hidden="true">'
      + (m.charging ? icon('c:lightning', 'Charging', '') : cells) + '</span>'
      + '<span class="pine-cam-batt-text">' + esc(m.text) + '</span>';
  }

  function battPaintInto(el, m) {
    if (!el) return;
    if (!m) { el.hidden = true; return; }
    var key = m.text + '|' + m.bars + '|' + m.tone + '|' + m.pulse;
    if (el.__battKey !== key) {
      el.__battKey = key;
      el.innerHTML = battHtml(m);
      el.className = 'pine-cam-batt pine-cam-batt--' + m.tone
        + (m.pulse ? ' pine-cam-batt--pulse' : '')
        + (m.charging ? ' pine-cam-batt--charging' : '');
    }
    el.title = m.title;
    el.setAttribute('aria-label', m.title);
    el.hidden = false;
  }

  /* The picture's top-left moves when the header folds; the meter goes
   * with it. */
  function battPlace() {
    var el = document.getElementById('pineCamBatt');
    var img = document.getElementById('pineCamImg');
    if (!el || !img) return;
    el.style.left = (img.offsetLeft + 6) + 'px';
    el.style.top = (img.offsetTop + 6) + 'px';
  }

  function paintBatteryNative(m) {
    if (!nativeOn) return;
    var arg = m ? {on: true, text: m.text, bars: m.bars, tone: m.tone,
                   pulse: m.pulse, stale: m.stale, charging: m.charging}
                : {on: false};
    var key = JSON.stringify(arg);
    if (key === battNativeKey) return;
    battNativeKey = key;
    nativeAsk('battery', arg);
  }

  function paintBattery(b, isLive) {
    if (b && b.ok && !b._got) b._got = Date.now();
    batt = b || null;
    var m = (isLive === false) ? null : battModel(batt);
    battPaintInto(document.getElementById('pineCamBatt'), m);
    battPlace();
    if (pip) {
      var pe = pip.querySelector('.pine-cam-batt');
      if (!pe && m) { pe = document.createElement('div'); pip.appendChild(pe); }
      battPaintInto(pe, m);
    }
    paintBatteryNative(m);
    return m;
  }

"""

CSS_ANCHOR = ".pine-cam-pip img {\n"
CSS_BLOCK = r"""/* [cambattery] the camera's battery, top-left of every picture. A drawn
   gauge (Carbon has no battery glyph in the vendored set), the camera's
   word for its level, and the time left once it has been measured. */
.pine-cam-pip { position: relative; }
.pine-cam-batt {
  position: absolute;
  left: 6px;
  top: 6px;
  z-index: 3;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 7px 2px 5px;
  border-radius: 6px;
  background: rgba(5, 8, 10, .64);
  color: #e6eef1;
  font: 600 11px/16px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  letter-spacing: .02em;
  white-space: nowrap;
  cursor: default;
}
.pine-cam-batt[hidden] { display: none !important; }
.pine-cam-batt-cell {
  position: relative;
  display: inline-flex;
  gap: 1px;
  width: 21px;
  height: 11px;
  padding: 1.5px;
  margin-right: 2px;
  box-sizing: border-box;
  border: 1.5px solid currentColor;
  border-radius: 2.5px;
}
.pine-cam-batt-cell::after {
  content: '';
  position: absolute;
  right: -4.5px;
  top: 2.5px;
  width: 2.5px;
  height: 3.5px;
  border-radius: 0 1px 1px 0;
  background: currentColor;
}
.pine-cam-batt-cell i { flex: 1; border-radius: .5px; background: currentColor; opacity: .16; }
.pine-cam-batt-cell i.on { opacity: 1; }
.pine-cam-batt--charging .pine-cam-batt-cell { width: auto; height: auto; padding: 0; margin: 0; border: 0; }
.pine-cam-batt--charging .pine-cam-batt-cell::after { display: none; }
.pine-cam-batt-cell svg { width: 13px; height: 13px; display: block; fill: currentColor; }
.pine-cam-batt--charging { color: #8fe3b0; }
.pine-cam-batt--amber { color: #f5a524; }
.pine-cam-batt--red { color: #ff5a5f; }
.pine-cam-batt--stale { color: #99a3a8; background: rgba(5, 8, 10, .46); }
.pine-cam-batt--pulse { animation: pine-cam-batt-pulse 2.4s ease-in-out infinite; }
@keyframes pine-cam-batt-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .42; } }
@media (prefers-reduced-motion: reduce) { .pine-cam-batt--pulse { animation: none; } }
.pine-cam-box.pine-cam-round .pine-cam-batt { display: none !important; }
.pine-cam-pip .pine-cam-batt { font-size: 10px; left: 4px; top: 4px; }

"""


def patch_js(text: str) -> tuple[int, str, str]:
    if MARK in text:
        return 2, text, "already applied"
    miss = [n for n, a, _ in JS_EDITS if text.count(a) != 1]
    if text.count(JS_BLOCK_ANCHOR) != 1:
        miss.append("look()")
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
        return 1, text, "anchor missing or not unique: .pine-cam-pip img"
    # after the pip img rule's closing brace
    i = text.index(CSS_ANCHOR)
    j = text.index("}\n", i) + 2
    return 0, text[:j] + "\n" + CSS_BLOCK.rstrip("\n") + "\n" + text[j:], "ok"


def run(path: Path, fn, apply: bool) -> int:
    raw = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    code, out, say = fn(raw.replace("\r\n", "\n"))
    print("%s: %s" % (path, say))
    if code != 0 or not apply:
        return code
    if crlf:
        out = out.replace("\n", "\r\n")
    tmp = path.with_name(path.name + ".cambattery.tmp")
    tmp.write_bytes(out.encode("utf-8"))
    os.replace(tmp, path)
    print("%s: APPLIED" % path)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    d = Path(argv[2])
    apply = argv[1] == "--apply"
    # check both before touching either, so a half-applied pair cannot happen
    codes = [run(d / "pine-cam.js", patch_js, False), run(d / "pine-cam.css", patch_css, False)]
    if 1 in codes:
        return 1
    if not apply:
        return 2 if codes == [2, 2] else (0 if 0 in codes else 2)
    for name, fn, c in (("pine-cam.js", patch_js, codes[0]), ("pine-cam.css", patch_css, codes[1])):
        if c == 0:
            run(d / name, fn, True)
    return 0 if 0 in codes else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

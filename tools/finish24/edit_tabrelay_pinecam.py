#!/usr/bin/env python3
"""[tabrelay] the Pine Cam box says which road the camera comes by, and the
clips sheet carries "Relay through the PineTab: auto / always / never".

  * a path line over the picture's bottom-left: "via PineTab · camera signal
    78%" or "via the Spark's dongle" (title: the supervisor's why), read from
    /api/pinelink/state `source`. No `source` block: nothing drawn, as before.
  * the setting, three radio buttons under Carbon c:network--4, each with a
    title; a press POSTs /api/pinelink/relay at once.

Applied to BOTH copies (desktop/renderer and app/src/main/assets/pine-views),
which must be identical before and are identical after.

usage: edit_tabrelay_pinecam.py --check|--apply <repo root>
exit 0 ready, 2 already applied, 1 anchor missing
"""
import sys
from pathlib import Path

MARK = "[tabrelay]"
DIRS = ("desktop/renderer", "app/src/main/assets/pine-views")

JS_FUNCS = r"""  /* [tabrelay] THE CAMERA'S ROAD, IN ONE LINE. tools/pinelink.py reads the
   * camera through the Spark's dongle or through the PineTab (a local-only
   * second Wi-Fi link, relayed on TacoNet) and says which in state.json
   * `source`; this line says it back over the picture. No `source` (a
   * supervisor without the relay) draws nothing, exactly as before. */
  function pathSay(src) {
    if (!src || !src.use) return '';
    if (src.use === 'tablet') {
      var sig = Number(src.tablet_signal) || 0;
      return 'via PineTab' + (sig > 0 ? ' · camera signal ' + Math.round(sig) + '%' : '');
    }
    if (src.use === 'wait') return 'switching to the PineTab…';
    return 'via the Spark’s dongle';
  }

  function pathPaint(got) {
    var el = document.getElementById('pineCamPath');
    if (!el) return;
    var src = got && got.source;
    var text = live ? pathSay(src) : '';
    el.hidden = !text;
    el.textContent = text;
    el.title = text ? String((src && src.why) || text) : '';
  }

  /* [tabrelay] "Relay through the PineTab: auto / always / never". */
  function relayBtn(pref, tip) {
    return '<button type="button" role="radio" aria-checked="false" data-pref="'
      + pref + '" title="' + esc(tip) + '"><span>' + pref + '</span></button>';
  }

  function relayPaint(v) {
    var row = document.getElementById('pineCamRelay');
    if (!row || !v) return;
    [].forEach.call(row.querySelectorAll('button'), function (b) {
      var on = b.getAttribute('data-pref') === v.pref;
      b.classList.toggle('on', on);
      b.setAttribute('aria-checked', on ? 'true' : 'false');
    });
    var say = document.getElementById('pineCamRelaySay');
    if (!say) return;
    var bits = [];
    if (v.say) bits.push(String(v.say));
    if (v.source && v.source.why) bits.push('now: ' + String(v.source.why));
    else if (!v.report || !v.report.at) bits.push('the PineTab has not reported');
    say.textContent = bits.join(' - ');
  }

  function relayRead() {
    return Promise.resolve(ask('/api/pinelink/relay'))
      .then(function (v) { relayPaint(v); return v; }, function () { return null; });
  }

  function relaySet(pref) {
    var say = document.getElementById('pineCamRelaySay');
    if (say) say.textContent = 'saving…';
    Promise.resolve(post('/api/pinelink/relay', {pref: pref})).then(function (v) {
      if (!v) { if (say) say.textContent = 'the station did not answer'; return; }
      relayPaint(v);
    }, function () { if (say) say.textContent = 'the station did not answer'; });
  }

"""

JS = [
    ("      + '<div class=\"pine-cam-batt\" id=\"pineCamBatt\" hidden></div>';\n",
     "      + '<div class=\"pine-cam-batt\" id=\"pineCamBatt\" hidden></div>'\n"
     "      /* [tabrelay] the camera's road, over the picture's bottom-left */\n"
     "      + '<div class=\"pine-cam-path\" id=\"pineCamPath\" hidden></div>';\n"),
    ("      cropOn = !!(got && got.crop && got.crop.on);    /* [pincrop] */\n",
     "      cropOn = !!(got && got.crop && got.crop.on);    /* [pincrop] */\n"
     "      pathPaint(got);                                 /* [tabrelay] */\n"),
    ("      + '<div class=\"pcp-row pcp-foot\"><button type=\"button\" id=\"pineCamPrefSave\">'\n",
     "      /* [tabrelay] which road reaches the camera */\n"
     "      + '<div class=\"pcp-h pcp-relay-h\">' + icon('c:network--4', '', '')\n"
     "      + '<span>Relay through the PineTab</span></div>'\n"
     "      + '<div class=\"pcp-row pcp-relay\" id=\"pineCamRelay\" role=\"radiogroup\" '\n"
     "      + 'aria-label=\"Relay through the PineTab\" title=\"Relay through the PineTab: the tablet '\n"
     "      + 'joins the camera as a second, local-only Wi-Fi link and passes the picture on\">'\n"
     "      + relayBtn('auto', 'Auto: the PineTab carries the camera when it can join it; otherwise the Spark\\'s dongle')\n"
     "      + relayBtn('always', 'Always: read the camera through the PineTab only - the dongle stays off')\n"
     "      + relayBtn('never', 'Never: the Spark\\'s dongle only, as before')\n"
     "      + '</div>'\n"
     "      + '<div class=\"pcp-hint\" id=\"pineCamRelaySay\"></div>'\n"
     "      + '<div class=\"pcp-row pcp-foot\"><button type=\"button\" id=\"pineCamPrefSave\">'\n"),
    ("    document.getElementById('pineCamPrefSave').addEventListener('click', savePrefs);\n",
     "    document.getElementById('pineCamPrefSave').addEventListener('click', savePrefs);\n"
     "    [].forEach.call(prefsEl.querySelectorAll('.pcp-relay button'), function (b) {   /* [tabrelay] */\n"
     "      b.addEventListener('click', function (ev) { ev.stopPropagation(); relaySet(b.getAttribute('data-pref')); });\n"
     "    });\n"),
    ("    psay('reading…');\n    readPrefs().then(function (p) {\n",
     "    psay('reading…');\n    relayRead();                           /* [tabrelay] */\n"
     "    readPrefs().then(function (p) {\n"),
    ("  function openPrefs() {\n", JS_FUNCS + "  function openPrefs() {\n"),
]

CSS_ADD = """
/* [tabrelay] the camera's road, over the picture's bottom-left, and the
   "Relay through the PineTab" setting in the clips sheet */
.pine-cam-path {
  position: absolute;
  left: 6px;
  bottom: 6px;
  z-index: 3;
  max-width: calc(100% - 12px);
  padding: 1px 7px;
  border-radius: 9px;
  background: rgba(5, 8, 10, .56);
  color: #cfe0e6;
  font: 10.5px/16px Inter, Segoe UI, system-ui, sans-serif;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  pointer-events: none;
}
.pine-cam-path[hidden], .pine-cam-round .pine-cam-path { display: none !important; }
.pcp-relay-h { display: flex; align-items: center; gap: 6px; margin-top: 10px; }
.pcp-relay-h svg { width: 14px; height: 14px; fill: currentColor; }
.pcp-relay button { flex: 1 1 0; justify-content: center; text-transform: capitalize; }
.pcp-relay button.on { background: #1d4c58; border-color: #65c7da; color: #fff; }
"""


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    root = Path(sys.argv[2] if len(sys.argv) > 2 else ".")
    files = {}
    for d in DIRS:
        for name in ("pine-cam.js", "pine-cam.css"):
            p = root / d / name
            raw = p.read_bytes().decode("utf-8")
            files[p] = (raw, "\r\n" in raw, raw.replace("\r\n", "\n"))
    texts = [t for (_r, _c, t) in files.values()]
    js = [files[root / d / "pine-cam.js"][2] for d in DIRS]
    css = [files[root / d / "pine-cam.css"][2] for d in DIRS]
    done = [MARK in t for t in texts]
    if all(done):
        print("%s pine-cam already applied" % MARK)
        return 2
    if any(done):
        print("%s pine-cam half applied - the two copies differ" % MARK)
        return 1
    bad = []
    if js[0] != js[1] or css[0] != css[1]:
        bad.append("desktop/renderer and pine-views copies of pine-cam differ")
    for a, _n in JS:
        if js[0].count(a) != 1:
            bad.append("%d x (want 1): %s" % (js[0].count(a), a.strip()[:80]))
    if bad:
        print("%s pine-cam anchor missing:\n  %s" % (MARK, "\n  ".join(bad)))
        return 1
    if mode != "--apply":
        print("%s pine-cam ready" % MARK)
        return 0
    for p, (_raw, crlf, text) in files.items():
        if p.name.endswith(".js"):
            for a, n in JS:
                text = text.replace(a, n)
        else:
            text = text.rstrip("\n") + "\n" + CSS_ADD
        if crlf:
            text = text.replace("\n", "\r\n")
        tmp = p.with_name(p.name + ".tabrelay-tmp")
        tmp.write_bytes(text.encode("utf-8"))
        tmp.replace(p)
    print("%s pine-cam applied (both copies)" % MARK)
    return 2


if __name__ == "__main__":
    sys.exit(main())

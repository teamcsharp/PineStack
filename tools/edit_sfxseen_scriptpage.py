"""[sfxseen] script-page.js: the line popup says whether a sting's picture was
displayed; the script view's diagnostics get an "SFX seen" button; the
Message view bubble's muted copy writes its own display receipt.

Apply to desktop/renderer/script-page.js and its mirror
app/src/main/assets/pine-views/script-page.js.

Edits (single-line anchors - a parallel build adds a Roll tab and popup X's):
  strip    after `var tabs = lineTabsStrip(box, item);` in openLine: a strip
           under the tab strip, so it reads on System 3, Timing and Roll alike
  button   after the report pad's `wrap.appendChild(b);` in ensureCaution
  bubble   after `mv.video = m;` in mvVideoStart: surface 'bubble'
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sfxseen_lib import Edit, run  # noqa: E402

G = "if (root.PineSfxSeen) { try { %s } catch (e) { /* [sfxseen] the view stands without it */ } }"

EDITS = [
    Edit("strip", "    var tabs = lineTabsStrip(box, item);\n",
         "    " + G % "root.PineSfxSeen.lineStrip(box, item, tabs);" + "\n"),
    Edit("button", "      holdOpen(b, function () { reasonOpen(b); });\n      wrap.appendChild(b);\n",
         "      " + G % "wrap.appendChild(root.PineSfxSeen.button());" + "\n"),
    Edit("bubble", "    mv.video = m;\n",
         "    " + G % ("root.PineSfxSeen.track(v, {url: m.info.url, id: m.info.sid, sfx: m.info.sid, video: true, "
                     "line: String((m.item && (m.item.line || m.item.id)) || ''), "
                     "sting: String((m.item && (m.item.text || m.item.name)) || '')}, 'bubble');") + "\n"),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS))

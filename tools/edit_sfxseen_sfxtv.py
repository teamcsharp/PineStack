"""[sfxseen] sfx-tv.js hands every clip to PineSfxSeen (sfx-seen.js).

Apply to EACH copy (test_sfx_tv_native_wall #16 wants them identical):
  desktop/renderer/sfx-tv.js
  app/src/main/assets/pine-views/sfx-tv.js
  app/src/main/assets/pine-sampler/sfx-tv.js

Edits (each one line, guarded by `root.PineSfxSeen &&`, wrapped in try):
  play      the tube's <video>, once its receipt handlers are on
  floor     the clip refused because another surface owns playback (hushed)
  missed    the clip thrown away as missed (the vidmiss drop)
  wall      every native wall state() the set already fetches
  sheet     a tap's sheet on a clip           -> interaction 'sheet'
  radial    a hold's radial on a clip         -> interaction 'radial'
  parody    the parody / stinger sheet opened -> interaction 'parody'
  mounted   PineSfxTv.mounted(): the set is running (the TV is on) -
            on() only says a clip is on the tube at this instant
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sfxseen_lib import Edit, run  # noqa: E402

G = "if (root.PineSfxSeen) { try { %s } catch (e) { /* [sfxseen] never in the way of the picture */ } }"

EDITS = [
    Edit("play", "      screen.__pineReceiptClose = function () { reportVideo('error', 'Video player closed before completion'); };\n",
         "      " + G % "root.PineSfxSeen.track(screen, clip, 'tube');" + "\n"),
    Edit("floor", "      videoReceipt(clip, 'error', null, 'Another SFX surface owns playback');\n",
         "      " + G % "root.PineSfxSeen.drop(clip, 'tube', 'hushed: another SFX surface owns playback');" + "\n"),
    Edit("missed", "      videoReceipt(clip, 'error', null, 'Video missed its playback window');\n",
         "      " + G % "root.PineSfxSeen.drop(clip, 'tube', 'missed its playback window (vidmiss drop)');" + "\n"),
    Edit("wall", "      var st = wallState(got);\n",
         "      " + G % "if (st) root.PineSfxSeen.wall(st, ringSeen[String(st.playing || '')] || null);" + "\n"),
    Edit("sheet", "  function sheet(clip, at) {\n",
         "    " + G % "if (clip) root.PineSfxSeen.interact('sheet', clip);" + "\n"),
    Edit("radial", "  function radialOpen(clip, at) {\n",
         "    " + G % "if (clip) root.PineSfxSeen.interact('radial', clip);" + "\n"),
    Edit("parody", "  function parodyOpen(seed, keepSurfaceDown) {\n",
         "    " + G % "if (seed && typeof seed === 'object') root.PineSfxSeen.interact('parody', seed);" + "\n"),
    Edit("mounted", "    waiting: function () { return queue.length; },\n",
         "    mounted: function () { return !!mounted; },          /* [sfxseen] the set is running */\n"),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS))

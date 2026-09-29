"""[sfxseen] hot-corners.js: the replay hot corner is an operator reaction.

Apply to desktop/renderer/hot-corners.js and app/src/main/assets/pine-views/hot-corners.js.
One insert after the line that decides whether the replayed clip has a
picture: PineSfxSeen.interact('replay', clip). The receipt of the replay
itself is written by the set (it goes through cut(), then play()), and
sfx-seen.js marks it replay:true because it follows this interaction.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sfxseen_lib import Edit, run  # noqa: E402

EDITS = [
    Edit("replay", "      var video = source.video != null ? !!source.video : !!row.video;\n",
         "      if (root.PineSfxSeen) { try { root.PineSfxSeen.interact('replay', {id: replayKey, url: url, "
         "sting: replayName, video: video}); } catch (e) { /* [sfxseen] the replay goes on */ } }\n"),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS))

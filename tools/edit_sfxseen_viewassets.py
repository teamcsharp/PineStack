r"""[sfxseen] ViewAssets.kt: the tablet's panel loads pine-views/sfx-seen.js
right after pine-dismiss.js (before script-page.js and sfx-tv.js).

  app/src/main/java/com/pinebox/kiosk/bridge/ViewAssets.kt
(the kiosk repo C:\_tools\pinebox-android\PineBoxKiosk and the mainline copy)"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sfxseen_lib import Edit, run  # noqa: E402

EDITS = [
    Edit("script", '        "pine-dismiss.js",        // tap away and a panel closes - one rule\n',
         '        "sfx-seen.js",            // [sfxseen] display receipts, before sfx-tv.js + script-page.js\n'),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS))

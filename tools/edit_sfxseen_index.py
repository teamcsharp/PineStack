"""[sfxseen] desktop/renderer/index.html loads sfx-seen.js right after
pine-dismiss.js - before script-page.js and sfx-tv.js, whose hooks read it."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sfxseen_lib import Edit, run  # noqa: E402

EDITS = [
    Edit("script", '  <script src="./pine-dismiss.js"></script>\n',
         '  <!-- [sfxseen] display receipts: did each SFX picture reach the screen -->\n'
         '  <script src="./sfx-seen.js"></script>\n'),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS))

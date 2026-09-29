r"""[msgid] ViewAssets.kt: the tablet's panel loads pine-views/msg-id.js after
line-actions.js and msg-id.css after line-actions.css. The two files must also
be in app/src/main/assets/pine-views/ (deploy.sh syncs only files already
there) - then an APK rebuild (deploy.sh) carries them.

  app/src/main/java/com/pinebox/kiosk/bridge/ViewAssets.kt"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from msgid_lib import Edit, run  # noqa: E402

EDITS = [
    Edit("script", '        "line-actions.js",        // hold a line: pad, keep, or examine\n',
         '        "msg-id.js",              // [msgid] the message code chip, copy, find by code\n'),
    Edit("style", '        "line-actions.css",       // the hold sheet and the examination\n',
         '        "msg-id.css",             // [msgid] the code chip and its toast\n'),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS))

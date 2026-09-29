"""[msgid] desktop/renderer/index.html: load msg-id.css after line-actions.css
and msg-id.js after line-actions.js (PineMsgId is looked up at run time, so
the order only keeps the pair together)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from msgid_lib import Edit, run  # noqa: E402

EDITS = [
    Edit("css", '  <link rel="stylesheet" href="./line-actions.css">\n',
         '  <link rel="stylesheet" href="./msg-id.css"> <!-- [msgid] the message code chip -->\n'),
    Edit("js", '  <script src="./line-actions.js"></script>\n',
         '  <script src="./msg-id.js"></script> <!-- [msgid] code chip, copy, find by code -->\n'),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS))

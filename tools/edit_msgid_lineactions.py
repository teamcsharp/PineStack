"""[msgid] line-actions.js: the message code chip in the hold sheet's header,
in the empty space between "What would you like to do with this?" and the
trash / nodes / thumbs (the header row is space-between: the chip sits in the
middle). A tap copies "#3c4782" (msg-id.js).

Apply to desktop/renderer/line-actions.js and its mirror
app/src/main/assets/pine-views/line-actions.js (deploy.sh syncs the mirror
from the canonical copy anyway). One single-line anchor, an insert after it.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from msgid_lib import Edit, run  # noqa: E402

EDITS = [
    Edit("head", "    headRow.appendChild(make('b', '', 'What would you like to do with this?'));\n",
         "    if (root.PineMsgId && line.id) { try { headRow.appendChild(root.PineMsgId.chip(line.id, 'head')); }"
         " catch (e) { /* [msgid] the sheet stands without its code */ } }\n"),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS))

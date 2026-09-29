"""[msgid] script-page.js: the message code on the Script line popup's header,
faintly in the corner of each Digital feed bubble, and the find box's
"#3c4782" (or bare hex with a digit) jumping to that message and opening its
hold sheet (msg-id.js does the work; a word still searches as a word).

Apply to desktop/renderer/script-page.js and its mirror
app/src/main/assets/pine-views/script-page.js.

Edits (single-line anchors, inserts only - parallel builds add popup X's, a
Roll tab and bubble media in these functions):
  popup    after the popup's `sp-detail-who` name in openLine
  bubble   after `mvOriginWire(bubble, item);` in mvBubbleStart
  find     before the find box's Enter handler
  title    after the find box's title: it says codes work too
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from msgid_lib import Edit, run  # noqa: E402

G = "if (root.PineMsgId) { try { %s } catch (e) { /* [msgid] the view stands without it */ } }"

EDITS = [
    Edit("popup",
         "    box.appendChild(make('b', 'sp-detail-who', item.name || item.who || item.tag || 'the station'));\n",
         "    " + G % ("var msgId = String(item.line || String(item.id || '').replace(/^(ln|ac)-/, '') || ''); "
                     "if (msgId) box.appendChild(root.PineMsgId.chip(msgId, 'head'));") + "\n"),
    Edit("bubble",
         "    mvOriginWire(bubble, item);               /* [msgorigin] double tap: the origin; hold: the sheet */\n",
         "    " + G % "if (item.lid) bubble.appendChild(root.PineMsgId.chip(item.lid, 'corner'));" + "\n"),
    Edit("find",
         "      if (ev.key === 'Enter') { ev.preventDefault(); findOpen(find.value); }\n",
         "      if (ev.key === 'Enter' && root.PineMsgId && root.PineMsgId.find(find.value)) { ev.preventDefault(); return; }"
         "   /* [msgid] #3c4782 opens that message */\n", where="before"),
    Edit("title",
         "    find.title = 'Every time this word was said on the air in the last two days, and why it keeps being said';\n",
         "    find.title += ' - or a message code (#3c4782) to open that message';   /* [msgid] */\n"),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS))

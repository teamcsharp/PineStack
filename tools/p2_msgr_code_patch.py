"""[s3-account-code] frontend/system3.js: System 3's Messenger shows each
message's code.

"Anywhere it comes up": the Script view's Digital/Classic feed bubbles, the
line popup and the hold sheet wear the line's code (#3c4782, msg-id.js), but
System 3's own Messenger - the System 3 window, the Script tab's embedded
Messenger and the tune page's Messenger (tune-messenger.js mounts this same
renderer) - drew a message with its speaker, step and turn and NO line code,
so a line seen there could not be pointed at, why_line'd or looked up in the
origin ledger.

Fix: the message header carries the code of the turn's spoken line (the same
short form msg-id.js makes: 8 hex of a long id, `<8>-pN` for a welded cue);
a tap copies "#code" (PineMsgId.copy on the desk and tablet, the clipboard
elsewhere) and never plays the message. Upcoming cards (no words yet) stay
as they are.

  python tools/p2_msgr_code_patch.py --check frontend/system3.js   (0 ready, 2 applied, 1 anchor missing)
  python tools/p2_msgr_code_patch.py --apply frontend/system3.js
Deploy note: bump the module's ?v= where it is served (see memory system3-window).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s3_account_p2_lib import Edit, run  # noqa: E402

MARKER = "[s3-account-code]"

EDITS = [
    Edit("who-code",
         "        v.toggle(t, node);\n      }},\n      el('div', 'who', el('b', {text: t.name || t.speaker}),\n",
         "        msgCodeOf(v.linesOf(key, conv, t)),   /* [s3-account-code] the line's code, as every view shows it */\n"),
    Edit("code-fn",
         '/* [s3-account] THE ORIGIN LEDGER ON EVERY ITEM. "trace its origin for each and\n',
         "/* [s3-account-code] A Messenger message wears its line's code - the same\n"
         "   \"#3c4782\" the Script view's feed, the line popup and the hold sheet show\n"
         "   (msg-id.js) - so tools/why_line.py and /api/system3/origin/<id> answer for\n"
         "   what is on screen. The turn's spoken line (not a welded board clip); a tap\n"
         "   copies the code and never plays the message. */\n"
         "function msgCodeOf(lines) {\n"
         "  const all = (lines || []).filter(l => l && l.line_id);\n"
         "  const ln = all.find(l => l.who !== 'board') || all[0];\n"
         "  if (!ln) return null;\n"
         "  const id = String(ln.line_id).toLowerCase();\n"
         "  const short = s => (/^[0-9a-f]{9,}$/.test(s) ? s.slice(0, 8) : s);\n"
         "  const pm = /^(.*)-punct-(\\d+)$/.exec(id);\n"
         "  const code = '#' + (pm ? short(pm[1]) + '-p' + pm[2] : short(id));\n"
         "  return el('span', {class: 's3-msgcode', text: code, role: 'button', tabindex: '0',\n"
         "    style: 'font:11px ui-monospace,monospace;opacity:.6;margin:0 6px;cursor:copy',\n"
         "    title: 'this message\\'s code (' + ln.line_id + ') - tap to copy; tools/why_line.py ' + code.slice(1),\n"
         "    onclick: e => {\n"
         "      e.stopPropagation();\n"
         "      try {\n"
         "        const M = window.PineMsgId;\n"
         "        if (M && M.copy) M.copy(code);\n"
         "        else if (navigator.clipboard) navigator.clipboard.writeText(code);\n"
         "      } catch (err) { /* the code still shows */ }\n"
         "    }});\n"
         "}\n\n",
         where="before"),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS, MARKER))

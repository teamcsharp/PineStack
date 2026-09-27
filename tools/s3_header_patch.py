"""The Script page's header takes System 3's bar, and its now-playing card
jumps to the air in whatever view is up.

Operator, 2026-09-27, on the Messenger:
  "I want the item indicated at one [the bar's buttons] move to two [the
   right end of the toolbar], and I want the item indicated at three [the
   on-air pill] move to four [the middle of the toolbar], thus consolidating
   that to that line. And then the items at five [the caution button] and
   six [the round's facts], I want added to the top header in the section
   mark seven [the right of the title line]. So that way this can be
   consolidated and the messenger can just be a pure messenger view."
and on the RECORD card beside the tree:
  "If I tap on this, jump to the active message and whatever view I have
   up. Jump to the message in script view, jump up to it in messenger view.
   Whatever view that I have up, jump to the active message whenever I tap
   on that. Even if I'm looking at system prompt view."

frontend/system3.js mountEmbedded() takes `chrome: {tools, air, facts}` -
places in the host's header - and keeps no bar of its own when it gets
them; its `jumpToAir()` scrolls whichever of its views is up to the message
on air. This file gives it those places, moves the caution button from the
script pane's corner to the end of the title line, shows the places only
while a System 3 view is up, and sends the card's tap to every view.

Both copies of the page are patched - desktop/renderer (the desk, which
hot-reloads) and the kiosk's pine-views (the tablet, an APK build).
Idempotent: --check exits 0 when every edit can apply, 2 when already
applied, 1 when an anchor is missing; --apply writes the files.
"""
import sys
from pathlib import Path

COPIES = ["desktop/renderer", "app/src/main/assets/pine-views"]

JS = [
    ("    titleRow.appendChild(head);\n"
     "    titleRow.appendChild(promptDock);\n"
     "    top.appendChild(titleRow);\n",
     "    titleRow.appendChild(head);\n"
     "    titleRow.appendChild(promptDock);\n"
     "    /* [s3-header] The right of the title line: System 3's round facts\n"
     "       (while one of its views is up) and the caution button. */\n"
     "    var titleTools = make('div', 'sp-title-tools');\n"
     "    titleTools.id = 'spTitleTools';\n"
     "    var s3Facts = make('span', 'sp-s3-facts');\n"
     "    s3Facts.id = 'spS3Facts';\n"
     "    s3Facts.hidden = true;\n"
     "    titleTools.appendChild(s3Facts);\n"
     "    titleRow.appendChild(titleTools);\n"
     "    top.appendChild(titleRow);\n"),
    ("      s3Buttons[mode] = b;\n"
     "      restore.appendChild(b);\n"
     "    });\n"
     "    top.appendChild(bands);\n",
     "      s3Buttons[mode] = b;\n"
     "      restore.appendChild(b);\n"
     "    });\n"
     "    /* [s3-header] System 3's bar, on this toolbar: its on-air pill in the\n"
     "       middle and its buttons at the right end (mountEmbedded's chrome),\n"
     "       shown only while one of its views is up - see s3Chrome(). */\n"
     "    var s3Air = make('span', 'sp-s3-air');\n"
     "    s3Air.id = 'spS3Air';\n"
     "    s3Air.hidden = true;\n"
     "    var s3Tools = make('span', 'sp-s3-tools');\n"
     "    s3Tools.id = 'spS3Tools';\n"
     "    s3Tools.hidden = true;\n"
     "    restore.appendChild(s3Air);\n"
     "    restore.appendChild(s3Tools);\n"
     "    top.appendChild(bands);\n"),
    ("  function ensureCaution() {\n"
     "    var pane = el('spScript');\n"
     "    if (!pane) return;\n"
     "    var wrap = document.getElementById('spCautionWrap');\n"
     "    if (wrap && wrap.parentNode === pane && pane.firstChild === wrap) return;\n",
     "  function ensureCaution() {\n"
     "    /* [s3-header] At the right end of the title line. In the script\n"
     "       pane's corner it sat over the first line - and over System 3's\n"
     "       views, which cover that pane. The pane stays the fallback for a\n"
     "       page built without the title line's tools. */\n"
     "    var dock = el('spTitleTools');\n"
     "    var pane = dock || el('spScript');\n"
     "    if (!pane) return;\n"
     "    var wrap = document.getElementById('spCautionWrap');\n"
     "    if (wrap && wrap.parentNode === pane\n"
     "        && (dock ? pane.lastChild === wrap : pane.firstChild === wrap)) return;\n"),
    ("      wrap.appendChild(b);\n"
     "    }\n"
     "    pane.insertBefore(wrap, pane.firstChild);\n"
     "  }\n",
     "      wrap.appendChild(b);\n"
     "    }\n"
     "    if (dock) pane.appendChild(wrap);\n"
     "    else pane.insertBefore(wrap, pane.firstChild);\n"
     "  }\n"),
    ("  function s3SetMode(mode) {\n",
     "  /* [s3-header] System 3's pieces in this page's header, shown while one\n"
     "     of its views is up. */\n"
     "  function s3Chrome(on) {\n"
     "    ['spS3Air', 'spS3Tools', 'spS3Facts'].forEach(function (id) {\n"
     "      var node = el(id);\n"
     "      if (node) node.hidden = !on;\n"
     "    });\n"
     "  }\n"
     "\n"
     "  function s3SetMode(mode) {\n"),
    ("    s3Mode = mode;\n"
     "    var pane = el('spS3');\n",
     "    s3Mode = mode;\n"
     "    s3Chrome(mode !== 'script');\n"
     "    var pane = el('spS3');\n"),
    ("        s3View = await mod.mountEmbedded(box, {\n"
     "          request: s3Request,\n",
     "        s3View = await mod.mountEmbedded(box, {\n"
     "          request: s3Request,\n"
     "          /* [s3-header] its bar goes in this page's header */\n"
     "          chrome: {tools: el('spS3Tools'), air: el('spS3Air'), facts: el('spS3Facts')},\n"),
    ("    box.addEventListener('click', function () {\n"
     "      resumeAirFollow('live strip', sayingLineId);\n"
     "    });\n",
     "    box.addEventListener('click', function () {\n"
     "      airJump('live strip');\n"
     "    });\n"),
    ("        ev.preventDefault();\n"
     "        resumeAirFollow('live strip', sayingLineId);\n",
     "        ev.preventDefault();\n"
     "        airJump('live strip');\n"),
    ("  function buildSaying() {\n",
     "  /* [s3-header] THE CARD'S TAP GOES TO THE VIEW THAT IS UP. The script\n"
     "     always follows the air again - it is what the other views come back\n"
     "     to - and a System 3 view that is up scrolls to the message on air\n"
     "     too; the prompt history, when it is open and can say which request\n"
     "     wrote that line, goes to it (PinePromptHistory.jumpTo). */\n"
     "  function airJump(reason) {\n"
     "    var done = resumeAirFollow(reason);\n"
     "    if (s3Mode !== 'script' && s3View && typeof s3View.jumpToAir === 'function') {\n"
     "      try { done = s3View.jumpToAir() || done; } catch (e) { /* the view is closing */ }\n"
     "    }\n"
     "    var ph = root.PinePromptHistory;\n"
     "    var open = host && host.querySelector('.sp-right.ph-active');\n"
     "    if (open && ph && typeof ph.jumpTo === 'function') {\n"
     "      try { ph.jumpTo(open, String(sayingLineId || nowLineId || '')); } catch (e) { /* nothing to find */ }\n"
     "    }\n"
     "    return done;\n"
     "  }\n"
     "\n"
     "  function buildSaying() {\n"),
]

CSS_ADD = """
/* [s3-header] System 3's bar in this page's header: its round facts and the
   caution button at the right of the title line, its on-air pill in the
   middle of the toolbar and its buttons at the toolbar's right end. */
.sp-title-tools { flex: 0 1 auto; min-width: 0; max-width: 62%; display: flex; align-items: center; gap: 6px; margin-left: auto; }
.sp-s3-facts { flex: 0 1 auto; min-width: 0; display: flex; overflow: hidden; }
.sp-s3-facts[hidden], .sp-s3-air[hidden], .sp-s3-tools[hidden] { display: none; }
.sp-s3-facts > .s3-chrome { overflow: hidden; }
.sp-s3-facts .s3-embed-facts { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sp-title-tools .sp-caution-wrap { position: static; height: auto; flex: none; overflow: visible; }
.sp-title-tools .sp-caution { position: static; width: 30px; height: 30px; box-shadow: none; }
.sp-s3-air { flex: 1 1 auto; min-width: 0; display: flex; justify-content: center; align-items: center; overflow: hidden; }
.sp-s3-tools { flex: none; display: flex; align-items: center; margin-left: auto; }
.sp-s3 .s3-embed-body { padding-top: 4px; }
"""


def main(argv):
    apply = "--apply" in argv
    writes, todo, done = {}, 0, 0
    for base in COPIES:
        js_path = Path(base) / "script-page.js"
        text = js_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        for old, new in JS:
            if new in text:
                done += 1
                continue
            if text.count(old) != 1:
                print("MISSING (%d) in %s: %r" % (text.count(old), js_path, old[:70]))
                return 1
            text = text.replace(old, new)
            todo += 1
        writes[js_path] = text
        css_path = Path(base) / "script-page.css"
        css = css_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if ".sp-title-tools" in css:
            done += 1
        else:
            css = css.rstrip("\n") + "\n" + CSS_ADD
            todo += 1
        writes[css_path] = css
    if not todo:
        print("already applied")
        return 2
    if not apply:
        print("can apply: %d edit(s)" % todo)
        return 0
    for path, text in writes.items():
        path.write_text(text, encoding="utf-8", newline="\n")
    print("applied: %d edit(s)" % todo)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

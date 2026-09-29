"""[voice-actor] Mount the voice-actor subpanel on the tablet
(app/src/main/java/com/pinebox/kiosk/bridge/ViewAssets.kt).

Being present in assets/pine-views is not being loaded - ViewAssets.kt's
SCRIPTS and STYLES lists decide what the kiosk evaluates into the panel
page (the orchestrator-glass lesson is written right there in the file).
This hook adds voice-actor.js after pinelive.js (its badge mounts into
#pineConsoleLine exactly the way the mic does, so the same order serves)
and voice-actor.css to the style roster.

The FILES still have to reach app/src/main/assets/pine-views/ the way
every module's do - the kiosk build's pine-views sync (deploy.sh) copies
desktop/renderer/voice-actor.js and .css across; this tool only edits the
rosters and never writes assets.

  python edit_voice_actor_views.py [--check|--apply] path/to/ViewAssets.kt

Marker-idempotent: the marker is `"voice-actor.js"`. --check exits 0 =
ready, 2 = applied, 1 = anchors missing. Keeps LF endings.
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = '"voice-actor.js"'

JS_OLD = '        "pinelive.js",\n'
JS_NEW = (JS_OLD
          + '        // Voice Actor: the person badge beside that mic, and the\n'
          + '        // cast subpanel behind it - same bar, same mount pattern.\n'
          + '        "voice-actor.js",\n')

CSS_OLD = '        "pinelive.css",           // the mic badge and the MX Live popup\n'
CSS_NEW = (CSS_OLD
           + '        "voice-actor.css",        // the person badge and the cast subpanel\n')


def state_of(text: str) -> str:
    if MARKER in text:
        return "applied"
    if text.count(JS_OLD) == 1 and text.count(CSS_OLD) == 1:
        return "ready"
    return ("anchors: js x%d, css x%d (want 1 each)"
            % (text.count(JS_OLD), text.count(CSS_OLD)))


def main(argv: list[str]) -> int:
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")),
                  "app/src/main/java/com/pinebox/kiosk/bridge/ViewAssets.kt")
    path = Path(target)
    text = path.read_bytes().decode("utf-8")
    assert "\r" not in text, "ViewAssets.kt is expected LF-only"
    state = state_of(text)
    if state == "applied":
        print("already applied")
        return 2
    if state != "ready":
        print("missing:", state)
        return 1
    if not do_apply:
        print("ready")
        return 0
    text = text.replace(JS_OLD, JS_NEW).replace(CSS_OLD, CSS_NEW)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(path)
    print("APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

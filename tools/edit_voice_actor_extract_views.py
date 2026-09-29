"""[voice-actor-extract] Load the signature-making pane on the tablet
(app/src/main/java/com/pinebox/kiosk/bridge/ViewAssets.kt).

Being in assets/pine-views is not being loaded: the SCRIPTS and STYLES
rosters decide what the kiosk evaluates into the panel page. This hook adds
voice-actor-extract.js right after voice-actor.js and voice-actor-extract.css
right after voice-actor.css - the lines tools/edit_voice_actor_views.py puts
in (apply that first).

The FILES must reach app/src/main/assets/pine-views/ once (copy them from
desktop/renderer/ - deploy.sh only re-syncs files already there); this tool
edits the rosters only and never writes assets.

  python edit_voice_actor_extract_views.py [--check|--apply] path/to/ViewAssets.kt

Marker-idempotent: the marker is `"voice-actor-extract.js"`. --check exits
0 = ready, 2 = applied, 1 = anchors missing. Keeps LF endings.
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = '"voice-actor-extract.js"'

JS_OLD = '        "voice-actor.js",\n'
JS_NEW = (JS_OLD
          + '        // Voice Actor extraction: the signature-making pane behind\n'
          + '        // the panel\'s New actor button (registers with the shell).\n'
          + '        "voice-actor-extract.js",\n')

CSS_OLD = '        "voice-actor.css",        // the person badge and the cast subpanel\n'
CSS_NEW = (CSS_OLD
           + '        "voice-actor-extract.css", // the extraction pane: link, library, cart, jobs\n')


def state_of(text: str) -> str:
    if MARKER in text:
        return "applied"
    if text.count(JS_OLD) == 1 and text.count(CSS_OLD) == 1:
        return "ready"
    return ("anchors: js x%d, css x%d (want 1 each - is tools/edit_voice_actor_views.py applied?)"
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
    out = text.replace(JS_OLD, JS_NEW).replace(CSS_OLD, CSS_NEW)
    assert out.count(MARKER) == 1 and out.count(JS_NEW) == 1 and out.count(CSS_NEW) == 1
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(out.encode("utf-8"))
    tmp.replace(path)
    print("APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

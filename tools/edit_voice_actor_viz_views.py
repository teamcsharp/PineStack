"""[voice-actor viz] Mount the assimilation tiles on the tablet
(app/src/main/java/com/pinebox/kiosk/bridge/ViewAssets.kt).

ViewAssets.kt's SCRIPTS and STYLES decide what the kiosk evaluates into the
panel page. This hook adds voice-actor-viz.js after voice-actor.js and
voice-actor-viz.css after voice-actor.css (those lines are the anchors - run
tools/edit_voice_actor_views.py FIRST). The tiles load three.js from the
station's /vendor/ (or window.pineThreeUrl()) the first time one is shown.

The FILES still have to reach app/src/main/assets/pine-views/ once (deploy.sh
only re-syncs files already there): copy desktop/renderer/voice-actor-viz.js
and .css across. This tool only edits the rosters and never writes assets.

  python edit_voice_actor_viz_views.py [--check|--apply] path/to/ViewAssets.kt

Marker-idempotent: the marker is `"voice-actor-viz.js"`. --check exits 0 =
ready, 2 = applied, 1 = anchors missing. Keeps the file's line endings.
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = '"voice-actor-viz.js"'

JS_OLD = '        "voice-actor.js",\n'
JS_NEW = (JS_OLD
          + '        // Voice Actor viz: the icosphere-to-folder tiles on the\n'
          + '        // extraction rail (one shared renderer, DPR 1, 30 fps here).\n'
          + '        "voice-actor-viz.js",\n')

CSS_OLD = '        "voice-actor.css",        // the person badge and the cast subpanel\n'
CSS_NEW = (CSS_OLD
           + '        "voice-actor-viz.css",    // the extraction tiles and their 4-line readout\n')


def sub(text: str, old: str, new: str, eol: str) -> str:
    old, new = old.replace("\n", eol), new.replace("\n", eol)
    n = text.count(old)
    assert n == 1, "anchor count %d (want 1): %r" % (n, old)
    return text.replace(old, new)


def state_of(text: str, eol: str) -> str:
    if MARKER in text:
        return "applied"
    j = text.count(JS_OLD.replace("\n", eol))
    c = text.count(CSS_OLD.replace("\n", eol))
    if j == 1 and c == 1:
        return "ready"
    return ("anchors: js x%d, css x%d (want 1 each) - apply "
            "tools/edit_voice_actor_views.py first" % (j, c))


def main(argv: list[str]) -> int:
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")),
                  "app/src/main/java/com/pinebox/kiosk/bridge/ViewAssets.kt")
    path = Path(target)
    text = path.read_bytes().decode("utf-8")
    eol = "\r\n" if "\r\n" in text else "\n"
    state = state_of(text, eol)
    if state == "applied":
        print("already applied")
        return 2
    if state != "ready":
        print("missing:", state)
        return 1
    if not do_apply:
        print("ready")
        return 0
    text = sub(text, JS_OLD, JS_NEW, eol)
    text = sub(text, CSS_OLD, CSS_NEW, eol)
    assert text.count(MARKER) == 1
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(path)
    print("APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

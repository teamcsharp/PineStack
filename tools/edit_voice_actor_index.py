"""[voice-actor] Mount the voice-actor subpanel in the desktop chrome
(desktop/renderer/index.html).

The two new files (voice-actor.js, voice-actor.css) are new modules beside
the others in desktop/renderer/; this is their ONE hook. The person button
mounts itself into console-line.js's #pineConsoleLine bar beside PineLive's
mic once the bar exists (a MutationObserver waits for it), so the include
order only has to put the file after pine-icons.js, pine-dismiss.js and
pinelive.js - all three load in this page long before the bar is built.
The kiosk picks the same files up when the APK next syncs pine-views
(tools/edit_voice_actor_views.py adds them to ViewAssets.kt's rosters).

  python edit_voice_actor_index.py [--check|--apply] path/to/index.html

Marker-idempotent: the marker is `voice-actor.js`. --check exits 0 = ready,
2 = applied, 1 = anchors missing. Keeps LF endings.
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = 'src="./voice-actor.js"'

CSS_OLD = '  <link rel="stylesheet" href="./pinelive.css">\n'
CSS_NEW = (CSS_OLD
           + '  <link rel="stylesheet" href="./voice-actor.css">\n')

JS_OLD = '  <script src="./pinelive.js"></script>\n'
JS_NEW = (JS_OLD
          + '  <!-- Voice Actor: the person badge beside the mic, and the cast\n'
          + '       subpanel behind it. The button mounts into the console line\n'
          + '       above once that bar exists. -->\n'
          + '  <script src="./voice-actor.js"></script>\n')


def state_of(text: str) -> str:
    if MARKER in text:
        return "applied"
    if text.count(CSS_OLD) == 1 and text.count(JS_OLD) == 1:
        return "ready"
    return ("anchors: css x%d, js x%d (want 1 each)"
            % (text.count(CSS_OLD), text.count(JS_OLD)))


def main(argv: list[str]) -> int:
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")),
                  "desktop/renderer/index.html")
    path = Path(target)
    text = path.read_bytes().decode("utf-8")
    assert "\r" not in text, "index.html is expected LF-only"
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
    text = text.replace(CSS_OLD, CSS_NEW).replace(JS_OLD, JS_NEW)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(path)
    print("APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""[pinelive] Mount PineLive in the desktop chrome (desktop/renderer/index.html).

The three new modules (pinelive-scope.js, pinelive-guide.js, pinelive.js)
and their stylesheet are new files beside the others in desktop/renderer/;
this is their ONE hook. The mic button mounts itself into console-line.js's
#pineConsoleLine bar once the bar exists (a MutationObserver waits for it),
so the include order only has to put the three files after pine-icons.js
and pine-dismiss.js - both load in this page long before console-line.js.
The kiosk picks the same files up when the APK next syncs pine-views.

  python edit_pinelive_index.py [--check] path/to/index.html

Marker-idempotent: the marker is `pinelive.js`. --check exits 0 = ready,
2 = applied, 1 = anchors missing. Keeps LF endings.
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = 'src="./pinelive.js"'

CSS_OLD = '  <link rel="stylesheet" href="./console-trace.css">\n'
CSS_NEW = (CSS_OLD
           + '  <link rel="stylesheet" href="./pinelive.css">\n')

JS_OLD = '  <script src="./console-line.js"></script>\n'
JS_NEW = (JS_OLD
          + '  <!-- PineLive: the status-bar mic and the MX Live popup. The button\n'
          + '       mounts into the console line above once that bar exists. -->\n'
          + '  <script src="./pinelive-scope.js"></script>\n'
          + '  <script src="./pinelive-guide.js"></script>\n'
          + '  <script src="./pinelive.js"></script>\n')


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

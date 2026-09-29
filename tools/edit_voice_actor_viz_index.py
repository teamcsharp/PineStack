"""[voice-actor viz] Mount the assimilation tiles in the desktop chrome
(desktop/renderer/index.html).

voice-actor-viz.js / .css are new modules beside voice-actor.js; this is
their ONE hook. The tiles mount themselves into the shell's #vaTileRail on
'pine-voice-actor:extract-open' and consume 'pine-voice-actor:job' events,
so the file only has to load after voice-actor.js (whose lines are the
anchors here - run tools/edit_voice_actor_index.py FIRST). three.js is not
included here: the tiles load /vendor/three.min.js lazily, the first time a
tile is on screen.

  python edit_voice_actor_viz_index.py [--check|--apply] path/to/index.html

Marker-idempotent: the marker is `voice-actor-viz.js`. --check exits 0 =
ready, 2 = applied, 1 = anchors missing. Keeps the file's line endings.
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = 'src="./voice-actor-viz.js"'

CSS_OLD = '  <link rel="stylesheet" href="./voice-actor.css">\n'
CSS_NEW = (CSS_OLD
           + '  <link rel="stylesheet" href="./voice-actor-viz.css">\n')

JS_OLD = '  <script src="./voice-actor.js"></script>\n'
JS_NEW = (JS_OLD
          + '  <!-- Voice Actor viz: the icosphere-to-folder tiles on the extraction\n'
          + '       studio\'s rail, driven by the real voicelab job answers. -->\n'
          + '  <script src="./voice-actor-viz.js"></script>\n')


def sub(text: str, old: str, new: str, eol: str) -> str:
    old, new = old.replace("\n", eol), new.replace("\n", eol)
    n = text.count(old)
    assert n == 1, "anchor count %d (want 1): %r" % (n, old)
    return text.replace(old, new)


def state_of(text: str, eol: str) -> str:
    if MARKER in text:
        return "applied"
    c = text.count(CSS_OLD.replace("\n", eol))
    j = text.count(JS_OLD.replace("\n", eol))
    if c == 1 and j == 1:
        return "ready"
    return ("anchors: css x%d, js x%d (want 1 each) - apply "
            "tools/edit_voice_actor_index.py first" % (c, j))


def main(argv: list[str]) -> int:
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")),
                  "desktop/renderer/index.html")
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
    text = sub(text, CSS_OLD, CSS_NEW, eol)
    text = sub(text, JS_OLD, JS_NEW, eol)
    assert text.count(MARKER) == 1
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(path)
    print("APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

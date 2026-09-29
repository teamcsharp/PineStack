"""[va-strips] Mount the profile strips in the desktop chrome
(desktop/renderer/index.html).

voice-actor-strips.js / .css are a new module beside voice-actor.js; this is
their ONE hook on the desk. The module registers with the shell
(PineVoiceActor.registerStrips, added by tools/edit_voice_actor_strips_shell.py)
and draws one strip of the last eight voice profiles under the host, co-host,
third-chair and scheduled-caller rows. It loads after the extraction pane,
whose lines are the anchors (run tools/edit_voice_actor_extract_index.py
FIRST).

  python edit_voice_actor_strips_index.py [--check|--apply] path/to/index.html

Marker-idempotent: the marker is `voice-actor-strips.js`. --check exits 0 =
ready, 2 = applied, 1 = anchors missing. Keeps the file's line endings.
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = 'src="./voice-actor-strips.js"'

CSS_OLD = '  <link rel="stylesheet" href="./voice-actor-extract.css">\n'
CSS_NEW = (CSS_OLD
           + '  <link rel="stylesheet" href="./voice-actor-strips.css">\n')

JS_OLD = '  <script src="./voice-actor-extract.js"></script>\n'
JS_NEW = (JS_OLD
          + '  <!-- Voice Actor strips: the last eight profiles under each seat, each\n'
          + '       wearing an SFX clip\'s poster or a ComfyUI render. Tap assigns,\n'
          + '       hold auditions a sample (never aired) with a level meter. -->\n'
          + '  <script src="./voice-actor-strips.js"></script>\n')


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
            "tools/edit_voice_actor_extract_index.py first" % (c, j))


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

"""[voice-actor-extract] Load the signature-making pane in the desktop chrome
(desktop/renderer/index.html).

voice-actor-extract.js/.css are new modules beside voice-actor.js; this is
their ONE hook. They go right after the voice actor shell's own lines
(tools/edit_voice_actor_index.py puts those in - apply that first): the pane
registers with PineVoiceActor.registerExtraction(...) and waits for the shell
if it is not there yet, so after the shell is the only order it needs.

  python edit_voice_actor_extract_index.py [--check|--apply] path/to/index.html

Marker-idempotent: the marker is `voice-actor-extract.js`. --check exits
0 = ready, 2 = applied, 1 = anchors missing (e.g. the shell hook is not in
yet). Keeps LF endings; asserts every count.
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = 'src="./voice-actor-extract.js"'

CSS_OLD = '  <link rel="stylesheet" href="./voice-actor.css">\n'
CSS_NEW = (CSS_OLD
           + '  <link rel="stylesheet" href="./voice-actor-extract.css">\n')

JS_OLD = '  <script src="./voice-actor.js"></script>\n'
JS_NEW = (JS_OLD
          + '  <!-- Voice Actor extraction: the signature-making pane (link in/out,\n'
          + '       the SFX library and its bin cart, listener uploads, the jobs)\n'
          + '       behind the panel\'s New actor button. -->\n'
          + '  <script src="./voice-actor-extract.js"></script>\n')


def state_of(text: str) -> str:
    if MARKER in text:
        return "applied"
    if text.count(CSS_OLD) == 1 and text.count(JS_OLD) == 1:
        return "ready"
    return ("anchors: css x%d, js x%d (want 1 each - is tools/edit_voice_actor_index.py applied?)"
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
    out = text.replace(CSS_OLD, CSS_NEW).replace(JS_OLD, JS_NEW)
    assert out.count(MARKER) == 1 and out.count(CSS_NEW) == 1 and out.count(JS_NEW) == 1
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(out.encode("utf-8"))
    tmp.replace(path)
    print("APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

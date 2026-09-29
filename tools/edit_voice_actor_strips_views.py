"""[va-strips] Load the profile strips on the tablet
(app/src/main/java/com/pinebox/kiosk/bridge/ViewAssets.kt).

Being present in assets/pine-views is not being loaded - ViewAssets.kt's
SCRIPTS and STYLES lists decide what the kiosk evaluates into the panel page.
This adds voice-actor-strips.js after voice-actor-extract.js and
voice-actor-strips.css after voice-actor-extract.css (run
tools/edit_voice_actor_extract_views.py FIRST - its lines are the anchors).

voice-actor-strips.js/.css are NEW files: copy them into
app/src/main/assets/pine-views/ by hand once (deploy.sh only re-syncs files
that are already there). This tool edits only the rosters.

  python edit_voice_actor_strips_views.py [--check|--apply] path/to/ViewAssets.kt

Marker-idempotent: the marker is `"voice-actor-strips.js"`. --check exits
0 = ready, 2 = applied, 1 = anchors missing. CRLF-aware.
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = '"voice-actor-strips.js"'

JS_OLD = '        "voice-actor-extract.js",\n'
JS_NEW = (JS_OLD
          + '        // Voice Actor strips: the last eight profiles under each seat\n'
          + '        // (tap assigns, hold auditions a never-aired sample + meter).\n'
          + '        "voice-actor-strips.js",\n')

CSS_OLD = '        "voice-actor-extract.css", // the extraction pane: link, library, cart, jobs\n'
CSS_NEW = (CSS_OLD
           + '        "voice-actor-strips.css",  // the profile strips and the audition sheet\n')


def state_of(text: str, eol: str) -> str:
    if MARKER in text:
        return "applied"
    j = text.count(JS_OLD.replace("\n", eol))
    c = text.count(CSS_OLD.replace("\n", eol))
    if j == 1 and c == 1:
        return "ready"
    return ("anchors: js x%d, css x%d (want 1 each) - apply "
            "tools/edit_voice_actor_extract_views.py first" % (j, c))


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
    for old, new in ((JS_OLD, JS_NEW), (CSS_OLD, CSS_NEW)):
        o, n = old.replace("\n", eol), new.replace("\n", eol)
        assert text.count(o) == 1
        text = text.replace(o, n)
    assert text.count(MARKER) == 1
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(path)
    print("APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

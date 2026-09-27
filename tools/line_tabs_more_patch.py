"""The tapped line's strip gains Timing and Parameters ([s3-line-tabs] +).

Operator, 2026-09-27, on "examine it in depth": "how long the command took
and show a profiler snapshot of the performance of the system with that
line and also show a collapsed panel of all the parameters that painted it
and their values allowing me to click them and see what they pertain to and
to alter / change / toggle their values."

The panes are the served module's (frontend/system3.js mountLineTabs:
paintTiming, paintParams); this file only adds the two buttons to the
strip. Both repo copies are patched - desktop/renderer and the repo's
pine-views; the kiosk's own copy is patched by pointing COPIES at it (line
endings kept). Idempotent: --check exits 0 when every edit can apply, 2 when
already applied, 1 when an anchor is missing; --apply writes the files.
"""
import sys
from pathlib import Path

COPIES = ["desktop/renderer", "app/src/main/assets/pine-views"]

JS = [
    ("  var LINE_TABS = [['line', 'Line'], ['system3', 'System 3'], ['node', 'Node'], ['prompt', 'Prompt'], ['tables', 'Tables']];\n",
     "  var LINE_TABS = [['line', 'Line'], ['system3', 'System 3'], ['node', 'Node'], ['prompt', 'Prompt'], ['tables', 'Tables'],\n"
     "    ['timing', 'Timing'], ['params', 'Parameters']];   /* [s3-line-tabs] the clocks + profiler; every parameter, folded */\n"),
]


def main(argv):
    apply = "--apply" in argv
    writes, todo = {}, 0
    for base in COPIES:
        path = Path(base) / "script-page.js"
        raw = path.read_bytes().decode("utf-8")
        crlf = "\r\n" in raw[:4000]
        text = raw.replace("\r\n", "\n")
        for old, new in JS:
            if new in text:
                continue
            if text.count(old) != 1:
                print("MISSING (%d) in %s: %r" % (text.count(old), path, old[:70]))
                return 1
            text = text.replace(old, new)
            todo += 1
        writes[path] = (text, crlf)
    if not todo:
        print("already applied")
        return 2
    if not apply:
        print("can apply: %d edit(s)" % todo)
        return 0
    for path, (text, crlf) in writes.items():
        path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    print("applied: %d edit(s)" % todo)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

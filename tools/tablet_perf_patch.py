"""The Script page stops measuring a script nobody can see, and the
now-playing card hands System 3's views the line that is on air.

Measured on the PineTab 2026-09-27 08:44Z (CDP Profiler, 6 s, Messenger up):
elementFromPoint was 10.4% of all samples - 1.3 s in every 6 - every call
from sampleMotion (the #1189 motion recorder) on each tick. It hit-tests
the script pane's top-left corner to learn which script line is showing,
which forces a layout of the whole page (58k nodes then) - and while a
System 3 view covers that pane the answer is always "none": the probe hits
the Messenger. So it is not asked while one is up; the recorder's other
evidence (the lit line, the resolver's decision, the player) is unchanged.

The card: "whenever I tap it, it jumps me to the wrong line". The views
followed s3FocusLine(), which prefers a line tapped in the script while its
card is open over the air. airJump now passes the line the card is showing,
and mountEmbedded's jumpToAir(line) resolves and rebuilds exactly that one.

Both repo copies are patched - desktop/renderer and the repo's pine-views;
the kiosk's own copy is patched by pointing COPIES at it. Idempotent:
--check exits 0 when every edit can apply, 2 when already applied, 1 when
an anchor is missing; --apply writes the files.
"""
import sys
from pathlib import Path

COPIES = ["desktop/renderer", "app/src/main/assets/pine-views"]

JS = [
    ("    if (idx < 0 && !knownActive && document.elementFromPoint) {\n",
     "    /* [tablet-perf] not while a System 3 view covers the pane: the probe\n"
     "       can only hit the view, and each call lays out the whole page. */\n"
     "    if (idx < 0 && !knownActive && document.elementFromPoint && s3Mode === 'script') {\n"),
    ("    if (s3Mode !== 'script' && s3View && typeof s3View.jumpToAir === 'function') {\n"
     "      try { done = s3View.jumpToAir() || done; } catch (e) { /* the view is closing */ }\n"
     "    }\n",
     "    if (s3Mode !== 'script' && s3View && typeof s3View.jumpToAir === 'function') {\n"
     "      /* [tablet-perf] THE LINE ON THE CARD, not the views' focus line -\n"
     "         that follows a line tapped in the script while its card is open. */\n"
     "      try { done = s3View.jumpToAir(String(sayingLineId || nowLineId || '')) || done; }\n"
     "      catch (e) { /* the view is closing */ }\n"
     "    }\n"),
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

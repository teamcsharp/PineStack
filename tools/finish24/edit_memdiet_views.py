#!/usr/bin/env python3
"""[memdiet] the page's decoder budget, and a Message view history with an end.

  * pine-memory.js (new, beside this tool) into every view folder under
    <root> (desktop/renderer, app/src/main/assets/pine-views): muted loops off
    screen / over the cap of 2 / detached / on a hidden page let their
    decoders go; PineMemory.trim(level) for the kiosk's onTrimMemory.
  * desktop/renderer/index.html loads it first (the kiosk's ViewAssets list is
    edit_memdiet_kiosk.py's).
  * script-page.js: the history pages back MV_HIST_MAX (200) bubbles and no
    further, and a trimmed bubble is unobserved (it was kept alive by the
    IntersectionObserver).

usage: edit_memdiet_views.py --check|--apply <root>
exit 0 ready, 2 already applied, 1 anchor missing
"""
import sys
from pathlib import Path

MARK = "[memdiet-views]"
DIRS = ("desktop/renderer", "app/src/main/assets/pine-views")
HERE = Path(__file__).resolve().parent
NEWFILE = "pine-memory.js"

SP = [
    ("  var MV_PAGE = 20, MV_KEEP = 120, MV_PIN_HOLD = 3000;\n",
     "  var MV_PAGE = 20, MV_KEEP = 120, MV_PIN_HOLD = 3000;\n"
     "  var MV_HIST_MAX = 200;   /* [memdiet-views] the history pages back this far, and no further */\n"),
    ("    if (!stage || !rows || mv.histAt <= 0 || mv.histBusy) return;\n",
     "    if (!stage || !rows || mv.histAt <= 0 || mv.histBusy) return;\n"
     "    if (stage.querySelectorAll('.sp-mv-item').length >= MV_HIST_MAX) return;   /* [memdiet-views] */\n"),
    ("      if (mv.pin && mv.pin.cur.node === kids[i]) continue;\n      stage.removeChild(kids[i]);\n",
     "      if (mv.pin && mv.pin.cur.node === kids[i]) continue;\n"
     "      if (mv.io) { try { mv.io.unobserve(kids[i]); } catch (e) { /* gone */ } }   /* [memdiet-views] */\n"
     "      stage.removeChild(kids[i]);\n"),
]
IDX = ('  <script src="./pine-vcr.js"></script>\n',
       '  <script src="./pine-memory.js"></script> <!-- [memdiet-views] the decoder budget, first -->\n'
       '  <script src="./pine-vcr.js"></script>\n')


def load(p: Path):
    raw = p.read_bytes().decode("utf-8")
    return "\r\n" in raw, raw.replace("\r\n", "\n")


def save(p: Path, crlf: bool, text: str) -> None:
    if crlf:
        text = text.replace("\n", "\r\n")
    tmp = p.with_name(p.name + ".memdiet-tmp")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(p)


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    root = Path(sys.argv[2] if len(sys.argv) > 2 else ".")
    dirs = [root / d for d in DIRS if (root / d / "script-page.js").is_file()]
    if not dirs:
        print("%s no view folder under %s" % (MARK, root))
        return 1
    new = (HERE / NEWFILE).read_bytes()
    pages = {d: load(d / "script-page.js") for d in dirs}
    index = root / "desktop/renderer/index.html"
    idx = load(index) if index.is_file() else None
    done = [MARK in t for (_c, t) in pages.values()] + ([MARK in idx[1]] if idx else [])
    if all(done):
        print("%s already applied" % MARK)
        return 2
    if any(done):
        print("%s half applied" % MARK)
        return 1
    bad = []
    for d, (_c, t) in pages.items():
        bad += ["%s: %d x (want 1): %s" % (d.name, t.count(a), a.strip()[:70]) for a, _n in SP if t.count(a) != 1]
        f = d / NEWFILE
        if f.exists() and f.read_bytes() != new:
            bad.append("%s exists and differs" % f)
    if idx and idx[1].count(IDX[0]) != 1:
        bad.append("index.html: pine-vcr.js script tag not found once")
    if bad:
        print("%s anchor missing:\n  %s" % (MARK, "\n  ".join(bad)))
        return 1
    if mode != "--apply":
        print("%s ready (%d view folders%s)" % (MARK, len(dirs), " + index.html" if idx else ""))
        return 0
    for d, (crlf, t) in pages.items():
        (d / NEWFILE).write_bytes(new)
        for a, n in SP:
            t = t.replace(a, n)
        save(d / "script-page.js", crlf, t)
    if idx:
        save(index, idx[0], idx[1].replace(IDX[0], IDX[1]))
    print("%s applied" % MARK)
    return 2


if __name__ == "__main__":
    sys.exit(main())

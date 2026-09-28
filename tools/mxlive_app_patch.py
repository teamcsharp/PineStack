"""[s3-live-event] The event_facts block reaches the writer (app.py).

TARGET: app.py

Two edits, plus the cache bump:

  1. Where System 3's running order enters a ROUND's prompt (the sheet
     block), the event_facts block is marked right beside it: the words
     come from the runtime (system3_event_facts -> event_facts_text),
     which answers '' unless a roll in this round landed on a station
     event's row - the block is then never marked at all, and when it is,
     decide_blocks' kind "claimed" records the claim.
  2. The same beside the single-line writer's sheet block.
  3. /system3/system3.js?v= bumped (the Controls card and the Rolodex
     badge changed in frontend/system3.js).

  python tools/mxlive_app_patch.py [--check] app.py
  python tools/mxlive_app_patch.py --apply app.py

--check exits 0 ready, 2 applied, 1 anchors missing. --apply is
idempotent, atomic and LF-only. Apply edit_mxlive_runtime.py (which
installs system3_event_facts) with it; without it the lambda answers ''
and the block is simply never marked.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path


EDITS = [
    ("mx-line-facts",
     '    _s3_sheet = _pb("sheet", _s3_spoken_handle.sheet if _s3_spoken_handle is not None else "")   # [s3-blocks]\n',
     '    _s3_sheet = _pb("sheet", _s3_spoken_handle.sheet if _s3_spoken_handle is not None else "")   # [s3-blocks]\n'
     '    _s3_sheet += _pb("event_facts",                             # [s3-live-event]\n'
     '                     (globals().get("system3_event_facts") or (lambda: ""))())\n', 1),

    # Placed BEFORE the sheet line: the running order stays the prompt's last
    # instruction (#1197), and tools/system3_blocks2_patch.py's stored text
    # (which begins at the sheet line) stays contiguous - its --check holds.
    ("mx-round-facts",
     '            + (_pb("sheet", "\\n\\n" + _beat_sheet) if _beat_sheet else "")   # [s3-blocks]\n',
     '            + _pb("event_facts",                                # [s3-live-event]\n'
     '                  (globals().get("system3_event_facts") or (lambda: ""))())\n'
     '            + (_pb("sheet", "\\n\\n" + _beat_sheet) if _beat_sheet else "")   # [s3-blocks]\n', 1),

    ("mx-js-bump",
     '    const module = await import("/system3/system3.js?v=6");\n',
     # wave D already moved the page to v=7 (the banks-roll bump) and /system3/
     # serves no-cache + ETag, so this edit rides the line as wave D wrote it.
     '    const module = await import("/system3/system3.js?v=7");   // [s3-banks-roll] replay / gold / listening chips on the turn\n', 1),
]


def plan(text):
    return list(EDITS)


def state_of(text, old, new, count):
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(text):
    applied, missing = 0, []
    for name, old, new, count in plan(text):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s (%s)" % (name, state))
    return applied, missing


def apply(path):
    path = Path(path)
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    edits = plan(text)
    if applied == len(edits):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for name, old, new, count in edits:
        if state_of(text, old, new, count) == "applied":
            continue
        assert text.count(old) == count, "%s: anchor found %d times" % (name, text.count(old))
        text = text.replace(old, new)
    assert "\r" not in text
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    try:
        shutil.copymode(str(path), tmp)
    except OSError:
        pass
    os.replace(tmp, path)
    return 0


def main(argv):
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "app.py")
    if do_apply:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    total = len(plan(text))
    if missing:
        for m in missing:
            print("missing:", m)
        print("%d of %d applied" % (applied, total))
        return 1
    if applied == total:
        print("already applied (%d edits)" % total)
        return 2
    print("ready: %d edits, %d already in" % (total, applied))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

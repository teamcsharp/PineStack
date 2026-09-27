"""Every single line dj_speak speaks has a road System 3 knows ([s3-lines]).

The strict gate (2026-09-27, the other session's `_s3_active()` edits) sends
every single line through system3_direct_line and WITHHOLDS a line whose
road System 3 does not know. Its road map named "reply" and "single_line",
which were not on the register, so a reply to a listener, the request line,
the show open, an aside and a produced ad spoken without its own stamp were
all silenced. The four are roads now (system3.ROADS, the register, one-leg
structures) and the map sends "ad" to ad_spot and anything else to the
stock interjection's node - directed, never withheld.

--check exits 0 ready / 2 applied / 1 missing; --apply writes LF atomically.
ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("every-single-line-has-a-road",
     '        _s3_road = ("reply" if kind == "reply" else\n'
     '                    "station_id" if kind == "station_id" else\n'
     '                    "interject" if kind == "interject" else\n'
     '                    "track_talk" if kind in ("intro", "outro") else\n'
     '                    "single_line")\n',
     '        _s3_road = ("reply" if kind == "reply" else\n'
     '                    "station_id" if kind == "station_id" else\n'
     '                    "interject" if kind == "interject" else\n'
     '                    "track_talk" if kind in ("intro", "outro") else\n'
     '                    # [s3-lines] a produced spot without its own stamp is the ad book\'s\n'
     '                    # node; the request line, the show open and an aside are roads of\n'
     '                    # their own; anything else is a stock interjection\'s node. A road\n'
     '                    # System 3 does not know would be WITHHELD below, so none is unknown.\n'
     '                    "ad_spot" if kind == "ad" else\n'
     '                    "request" if kind == "request" else\n'
     '                    "open" if kind == "open" else\n'
     '                    "aside" if kind == "aside" else\n'
     '                    "interject")\n', 1),
]


def plan(text):
    return list(EDITS)


def state_of(text, old, new, count):
    n_new, n_old = text.count(new), text.count(old)
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
    if applied == len(plan(text)):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for name, old, new, count in plan(text):
        if state_of(text, old, new, count) == "applied":
            continue
        text = text.replace(old, new)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    os.replace(tmp, path)
    return 0


def main(argv):
    target = next((a for a in argv if not a.startswith("--")), "app.py")
    if "--apply" in argv:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    if applied == len(plan(text)):
        print("already applied")
        return 2
    print("ready")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

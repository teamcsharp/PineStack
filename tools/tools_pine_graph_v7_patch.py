"""[pine-graph] The panel's System 3 window imports system3.js?v=7 and
system3.css?v=5: the module gained the hand-drawn conversation graph
editor, and the old cached copies must fall away. ON THE HOST, after
tools/system3_module_v6_patch.py (this tool owns the ?v= lines now;
the v6 tool's --check will report its literal moved, as each bump
before it did to the one before).

--check exits 0 ready / 2 applied / 1 missing. --apply is idempotent and
atomic, LF only.
"""
# TARGET: app.py
import os
import shutil
import sys
import tempfile
from pathlib import Path

TARGET_DEFAULT = "app.py"

EDITS = [
    ('pg-panel-js-v7',
     '    const module = await import("/system3/system3.js?v=6");\n',
     '    const module = await import("/system3/system3.js?v=7");   // [s3-banks-roll] replay / gold / listening chips on the turn\n', 1),
    ('pg-panel-css-v5',
     '    style.href = "/system3/system3.css?v=4"; document.head.append(style);\n',
     '    style.href = "/system3/system3.css?v=5"; document.head.append(style);   /* [pine-graph] */\n', 1),
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
    target = next((a for a in argv if not a.startswith("--")), TARGET_DEFAULT)
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

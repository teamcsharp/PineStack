"""[icons-cache] The icon stylesheet reaches browsers that cached the broken one.

fe5e185 (2026-09-14) gave pineicons.css's @font-face a family LIST
("PineIcons, 'PineIcons'"); Chromium drops such a face, so every pictograph the
single-colour font should draw fell back to colour emoji (the review strip's
memo icons). Wave A (f94da34) fixed the file, but /icons/ served it with
max-age=86400: the tablet kept the broken copy for a day. The six page links
move to ?v=2 so every client fetches the fixed file now, and the route
revalidates from here on (a 25 KB file), so a rebuilt icon set is seen at the
next page load without anyone remembering to bump a version.

--check exits 0 ready / 2 applied / 1 missing. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("links-v2",
     '<link rel="stylesheet" href="/icons/pineicons.css">\n',
     '<link rel="stylesheet" href="/icons/pineicons.css?v=2">\n', 6),
    ("route-revalidates",
     '        headers={"Cache-Control": "public, max-age=86400",\n'
     '                 "X-Content-Type-Options": "nosniff"},\n'
     '    )\n'
     '\n'
     '\n'
     '@app.get("/vendor/{name}")\n',
     '        # [icons-cache] revalidate: a day-long max-age kept a broken icon\n'
     '        # font on the tablet after the file was fixed (2026-09-28).\n'
     '        headers={"Cache-Control": "no-cache",\n'
     '                 "X-Content-Type-Options": "nosniff"},\n'
     '    )\n'
     '\n'
     '\n'
     '@app.get("/vendor/{name}")\n', 1),
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

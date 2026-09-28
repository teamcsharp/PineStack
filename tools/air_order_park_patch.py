"""[air-order-park] A line in the waiting line is numbered where it JOINED it.

The waiting line is the air queue. [air-order] numbered a parked line only
when it left the line, so a station ID that arrived before a banter round was
written - and rightly aired first - read in the script as coming after it:
the one late block in the first 29 heard after [air-order] went live
(2026-09-28). The reservation is taken at park time now; page_waiting_after_
publish's reservation then finds it and keeps it.

tools/air_order_patch.py carries the same text, so on a fresh file the two
tools agree. --check exits 0 ready / 2 applied / 1 missing. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("park-reserve",
     '    _PAGE_WAITING.append(clip)\n    # A delivery that exists, waiting: whatever looks it up by id (the render\n',
     '    _PAGE_WAITING.append(clip)\n    # [air-order-park] THE WAITING LINE IS THE AIR QUEUE. The line\'s place in\n    # the script is taken now, where it joined the queue - behind the rounds it\n    # waits for, in front of any round committed after it. Numbered when it\n    # LEFT the line, a station ID that arrived before a banter round was\n    # written read, in the script, as having come after it (the one late block\n    # of the first 29 heard, 2026-09-28).\n    script_ledger_reserve([str(r.get("id") or "") for r in _page_delivery_rows(clip)])\n    # A delivery that exists, waiting: whatever looks it up by id (the render\n', 1),
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

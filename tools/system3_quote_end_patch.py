"""[s3-sb-end] The speakerbox prepend-or-append roulette, on the station's doors.

The operator (2026-09-28): "lets change the way append / prepend speakerbox
text works to also have a roulette now between either append or prepend if
they both happen to have won in the roulette. So instead of both winning
together, they now have a roulette that is part of the system."

System 3's engine does this for a round it runs (system3.py [s3-sb-end],
table SBEND1). These are dj_banter's own #1233 doors, which carry a round
only when System 3 has no running order for it: both doors now roll first,
and when both win, the dice door's `speakbox.quote_end` (POOLS1) picks one.
The line paperwork says "won, then the roulette chose the other" rather than
"the dice said no".

--check exits 0 ready / 2 applied / 1 missing. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ('doors-roll-first',
     '    if _quote_door("prepend", "speakbox_prepend_rate", lift=_lift):    # [#1233]\n        head = await _fresh_swath()\n',
     '    # [s3-sb-end] PREPEND OR APPEND. "Instead of both winning together, they\n    # now have a roulette that is part of the system" (operator, 2026-09-28).\n    # Both doors roll first; when both win, the prepend-or-append roulette\n    # (System 3\'s dice door: POOLS1 `speakbox.quote_end`) picks the one that\n    # is read, and the other is recorded as withdrawn on the round\'s quote\n    # ledger. Under a System 3 running order these doors stand aside and the\n    # engine\'s own roulette (SBEND1) decides instead.\n    _pre_hit = _quote_door("prepend", "speakbox_prepend_rate", lift=_lift)\n    _app_hit = _quote_door("append", "speakbox_append_rate", lift=_lift)\n    if _pre_hit and _app_hit:\n        _end = s3_choice("speakbox.quote_end", ["prepend", "append"],\n                         "a round\'s prepended and appended passages both won their rolls: "\n                         "which one is read (the other is withdrawn)")\n        _lost = "append" if _end == "prepend" else "prepend"\n        _quotes[_lost].update(hit=False, lost_to=_end,\n                              why="won its roll, but the prepend-or-append roulette chose the %s" % _end)\n        pipeline_log("speakbox", "the prepend and the append both won their rolls; "\n                                 "the prepend-or-append roulette chose the %s" % _end)\n        _pre_hit, _app_hit = _end == "prepend", _end == "append"\n    if _pre_hit:    # [#1233] [s3-sb-end]\n        head = await _fresh_swath()\n', 1),
    ('append-door-decided',
     '    if _quote_door("append", "speakbox_append_rate", lift=_lift):   # #867 [#1233]\n        tail = await _fresh_swath()\n',
     '    if _app_hit:   # #867 [#1233] [s3-sb-end] rolled above, with the prepend\n        tail = await _fresh_swath()\n', 1),
    ('paperwork-lost-roulette',
     '            if not rec.get("applies"):\n                value = pct + " · does not apply"\n                how = str(rec.get("why") or note or "no passage is stapled to this round")\n            elif rec.get("hit"):\n',
     '            if not rec.get("applies"):\n                value = pct + " · does not apply"\n                how = str(rec.get("why") or note or "no passage is stapled to this round")\n            elif rec.get("lost_to"):\n                # [s3-sb-end] it won its roll; the prepend-or-append roulette\n                # chose the other door - not "the dice said no"\n                applied = False\n                roll = rec.get("roll")\n                value = "%s · rolled %s → yes, then the roulette chose the %s" % (\n                    pct, ("%.2f" % float(roll)) if isinstance(roll, (int, float)) else "-", rec.get("lost_to"))\n                how = str(rec.get("why") or "")\n            elif rec.get("hit"):\n', 1),
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

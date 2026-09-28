"""[cadence-no-repeat] The board's cadence never plays the same clip twice in a
row - in a drop family smaller than its memory, too.

REAL BUG, found through tests/test_sfx_cadence_pool.py (whose seeding was
also stale - see there). #1224 (0399ec0, "every time the SFX guy plays a clip,
he's playing the same clip over and over and that just isn't good
broadcasting") gave _sfx_cadence_pick the sting roads' ring: `recent`, sized by
sting_keep() - an eighth of the pool, floored at 24. The filter "is skipped
when it would leave nothing, so a deep ring can never starve the draw - it
degrades to the full pool". In a family of 24 clips or fewer the ring holds the
whole family once each clip has played, so from then on EVERY draw is from the
full pool - the clip that just went out included. A two-clip family repeats
back to back half the time; a five-clip family one draw in five. The single-
clip memory #1224 replaced never allowed that.

So when the ring covers the whole pool, the draw is from the pool minus the
one clip of it that went out last. Never empty (the pool has two or more), the
weighted System 3 rolls below are untouched, and a family bigger than the ring
never reaches this line.

The same test found the twin: when the ring leaves only a HANDFUL outside it
and none of them can go out (over the cap, no length), those few became the
whole pool, the rolls refused each one, and the draw answered None - no sting
- for as long as the durable ring (#1225) held the playable ones. A remainder
of sixteen or fewer is therefore checked against the same cap the rolls use
(sfx_seconds is cached - no share walk), and an empty one degrades exactly as
above. A larger remainder is left to the rolls, as before.

The rolls' own block (the families, the 64 tries) belongs to
tools/system3_sfx_roll_patch.py and is not touched: this edits only the lines
above it that decide what the pool is.

--check exits 0 ready / 2 applied / 1 missing. --apply is idempotent and
atomic, LF only. ON THE HOST. Anchors are original code (no other tool's text).
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path


EDITS = [
    ("cadence-no-repeat",
     '''    keep = sting_keep(len(pool))
    fresh = [p for p in pool if str(p) not in recent]
    if fresh:
        pool = fresh
''',
     '''    keep = sting_keep(len(pool))
    fresh = [p for p in pool if str(p) not in recent]
    if 0 < len(fresh) <= 16:
        # [cadence-no-repeat] A handful left outside the ring: only the ones
        # that can go out count. A remainder of clips over the cap (or of no
        # length at all) would otherwise BE the pool, every roll below would
        # refuse it, and the draw would answer None for as long as the ring
        # (durable, #1225) holds the rest - no sting at all.
        _cap = min(12.0, sfx_cap_seconds())

        def _fits(p: Path) -> bool:
            try:
                return 0 < sfx_seconds(p) <= _cap
            except Exception:  # noqa: BLE001
                return False
        fresh = [p for p in fresh if _fits(p)]
    if not fresh and len(pool) > 1:
        # [cadence-no-repeat] A family no bigger than the ring: every clip
        # of it is "recent", and the full pool would include the one that
        # just went out. Never back to back - the pool minus its last.
        _in_pool = {str(p) for p in pool}
        _last = next((r for r in reversed(recent) if r in _in_pool), "")
        fresh = [p for p in pool if str(p) != _last]
    if fresh:
        pool = fresh
''', 1),
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

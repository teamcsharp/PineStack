"""[s3-mgrtopics] system3.py half of the manager's topic roulette.

  families       validate_table accepts the manager's two table families,
                 MGRTOPIC (his topics database) and MGRSUB (the sub messages by
                 approach) - edited in the Tables tab like any table; checked
                 by system3_mgrtopics.validate_table (inserted BEFORE the family
                 check edit_mxlive_engine.py stored, which stays whole).
  replay-skips-road-rolls   decision replay leaves out every event a road
                 rolled before its round was planned (meta.road_roll): the
                 STATION rolls as before, and now the manager's MGRTOPIC /
                 MGRAPPROACH / MGRSUB draws, which are recorded, not re-planned.

The tables themselves live in system3_mgrtopics.py (new module) and reach a
stored config once through the runtime's add_missing_default_tables - never
DEFAULT_TABLES, so default_config()'s pinned hash does not move.

Anchors cut from HEAD cd976c2 (re-verified on 713c1b1), each unique. --check exits 0 ready / 2 applied /
1 anchors missing; --apply is idempotent, asserts every anchor, writes LF
atomically.
TARGET: system3.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

EDITS = [
    ('families',
     '    if family not in ("CTS", "ES", "RS", "IRS", "FL", "TEMPER", "SHOCK", "INTERJECT", "FAV", "DIRECTIVE", "EVENT",\n',
     '    if family in ("MGRTOPIC", "MGRSUB"):                  # [s3-mgrtopics] the manager\'s topics, his sub messages\n'
     '        import system3_mgrtopics\n'
     '        return system3_mgrtopics.validate_table(table)\n'
     '    if family not in ("CTS", "ES", "RS", "IRS", "FL", "TEMPER", "SHOCK", "INTERJECT", "FAV", "DIRECTIVE", "EVENT",\n',
     1),
    ('replay-skips-road-rolls',
     '         if e["family"] != "STATION"]          # [s3-dice-door] drawn by the road before the plan: recorded, not replayed\n',
     '         if e["family"] != "STATION"          # [s3-dice-door] drawn by the road before the plan: recorded, not replayed\n'
     '         and not (e.get("meta") or {}).get("road_roll")]   # [s3-mgrtopics] the manager\'s topic draws, likewise\n',
     1),
]


def plan(text):
    return EDITS


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
    target = next((a for a in argv if not a.startswith("--")), "system3.py")
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

"""The script reads downwards, and stays put ([#1314][#1315]).

Measured from the captures after the trailing fix (2026-09-27):

  #1314  "2 line(s) standing between the first and last marked element were
          never put out (withdrawn x2); the mark steps over them and that
          step is the jump" - the pane moved 1317 px under `follow`.
  #1315  "The same highlighted line changed document position; this is a
          display reindex" - rows above the reader moved.

Two causes, two rules:

1. A ROW REFUSED AT HAND-OVER LEAVES THE SPINE. #1218 tiers by BLOCK so a
   live half-heard round stays whole - right for prepared rows, wrong for a
   withdrawn one: it sat at its ord inside a heard block, will never be
   heard, and the mark stepped over it. It sits under everything now, where
   a round that never happened belongs.

2. A HEARD ROW KEEPS THE SLOT IT WAS FIRST DRAWN AT until the ledger files
   it. Its air stamp is an estimate until the ear's stamp arrives (a median
   of 62.6 s later, #1218); moving it then reindexed every row above the
   reader. The ledger's own (block, ord) overrules the pin the moment the
   catch-up writes it, exactly as before.

--check exits 0 ready / 2 applied / 1 missing; --apply writes LF atomically.
ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("the-pin-book",
     'def screenplay_compose(since: float, until: float, d: dict[str, Any],\n',
     '# [#1315] the slot a heard row was first drawn at, by line id, until the ledger\n'
     '# files it (process memory: a restart re-draws, which the ledger absorbs)\n'
     '_HANGER_SLOT: dict[str, float] = {}\n'
     '\n'
     '\n'
     'def screenplay_compose(since: float, until: float, d: dict[str, Any],\n', 1),
    ("a-withdrawn-row-leaves-the-spine",
     '            _b0 = int(_got[0])\n'
     '            _tier = (0 if _b0 in _heard_blocks else\n'
     '                     2 if _b0 in _withdrawn_blocks else 1)\n'
     '            _spine.append((_tier, _b0, int(_got[1]), _ix))\n',
     '            _b0 = int(_got[0])\n'
     '            _tier = (0 if _b0 in _heard_blocks else\n'
     '                     2 if _b0 in _withdrawn_blocks else 1)\n'
     '            # [#1314] A ROW REFUSED AT HAND-OVER LEAVES THE SPINE. It sat at its\n'
     '            # ord inside a heard block and the mark stepped over it - two\n'
     '            # withdrawn rows were the 1317 px jump. It will never be heard,\n'
     '            # so it sits under everything, where a round that never happened\n'
     '            # belongs. The block still counts as heard for the rows around it.\n'
     '            if str(_row.get("aired") or "") == "withdrawn":\n'
     '                _tier = 2\n'
     '            _spine.append((_tier, _b0, int(_got[1]), _ix))\n', 1),
    ("a-heard-row-keeps-its-first-slot",
     '        _raw_of[_ix] = ((screenplay_when_heard(_row) if screenplay_was_heard(_row)\n'
     '                         else float(_e.get("at") or 0))\n'
     '                        or float(_e.get("at") or 0))\n',
     '        _raw = ((screenplay_when_heard(_row) if screenplay_was_heard(_row)\n'
     '                 else float(_e.get("at") or 0))\n'
     '                or float(_e.get("at") or 0))\n'
     '        # [#1315] A ROW THE EAR HAS PLACED KEEPS THAT SLOT until the ledger\n'
     '        # files it. Before the ear speaks, the estimate may still move the row\n'
     '        # (that is the region at or below the live line); a re-ack afterwards\n'
     '        # used to reindex every row above the reader. (block, ord) overrules.\n'
     '        _lid = str(_row.get("id") or "")\n'
     '        if _lid and line_heard_at(_row) > 0:            # the EAR has spoken\n'
     '            _raw = _HANGER_SLOT.setdefault(_lid, _raw)\n'
     '            if len(_HANGER_SLOT) > 6000:\n'
     '                for _k in list(_HANGER_SLOT)[:2000]:\n'
     '                    _HANGER_SLOT.pop(_k, None)\n'
     '        _raw_of[_ix] = _raw\n', 1),
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

"""[s3-own-dice] app.py: every aired line carries ITS OWN node's dice.

The disease (operator, 2026-09-28): two DIFFERENT aired lines wore the
IDENTICAL System 3 stamp - script_ledger block 35646 ord 2 (line
1efea24e...) and block 35649 ord 1 (line 7a977477...), both "turn :t01,
bundle :t01:b8732e023, dice 0.937025" - on the manager road's hour-18
"Message from upstairs".  Every line after the first wore a copy.

Root cause: _speak_turns_floorless builds each ledger row's `dice` with
_td_of(row) = turn_dice[turn_ix[row]].  `turn_ix` counts the AUDIO CHUNKS
this burst aired (turn_ix.append(len(aired_items))), while `turn_dice` is
keyed by the SCRIPT's turns.  Conversation 04cbacf906fa4445's t00 is one
long DJ turn that aired as chunks across bursts 35646/35649/35660, so its
2nd chunk (turn_ix 1) wore t01's dice, its 3rd (a new burst, turn_ix 1
again) wore t01's dice AGAIN, its 4th wore t02's - and t01's own two
chunks (turn_ix 4, 5) wore none.  The row's `system3` stamp was right all
along (t00 for every t00 chunk): _s3_row_bare links by the WORDS
(system3_turn_id_for), and the store's line link agrees.  Only the dice
were positional.

The cure: on a System 3 round (the turn dice carry node ids), a dialogue
row takes the dice of the node its words belong to - the same link its
system3 stamp carries, so dice.s3.turn_id == system3.turn_id by
construction - and a chunk that CONTINUES a node already begun is marked
honestly ("cont": true - the same node's roll, not a second one).  A row
whose words name no node carries no dice rather than a neighbour's.  A
round without System 3 dice (System 2 only) is untouched: positional, as
before.  Continuation: a live-written round names only a turn's FIRST
chunk with turn_text (#no-repeats); a prepared round's takes each carry
their own, so there the words decide (the chunk does not open its turn).

One EDIT, anchored on _td_of's own five lines (unique in app.py at
05917b1/dc1763e; absent from all 200 tools' stored text - the only tool
naming _td_of, system3_patch_app.py, stores the `**({"dice": _td_of(_r)}`
line, which this edit does not touch).  The replacement does not contain
its anchor.  --check exits 0 ready / 2 applied / 1 missing; --apply is
idempotent, atomic, LF only.  Apply ON THE HOST.  Order-independent of
cover_a_inject_patch.py, cover_b_s3_patch.py and the cover_c tools (no
shared ground).
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("own-dice",
     '                def _td_of(_row_at: int) -> dict[str, Any]:\n'
     '                    _t = (turn_ix[_row_at]\n'
     '                          if _row_at < len(turn_ix) else -1)\n'
     '                    _got = (turn_dice or {}).get(_t)\n'
     '                    return _got if isinstance(_got, dict) else {}\n',
     '                # [s3-own-dice] A System 3 round\'s dice belong to its NODES.\n'
     '                # `turn_ix` counts the audio chunks this burst aired, not the\n'
     '                # script\'s turns, so the dice looked up by it handed a turn\n'
     '                # aired in several chunks the NEXT turns\' dice: 2026-09-28,\n'
     '                # conversation 04cbacf906fa4445\'s t00 aired in four chunks\n'
     '                # over two bursts and two different chunks wore t01\'s stamp\n'
     '                # (dice 0.937025) while t01\'s own lines wore none. A row now\n'
     '                # takes the dice of the node its WORDS belong to - the very\n'
     '                # link its system3 stamp carries - and a chunk continuing a\n'
     '                # node already begun says so ("cont": the same node\'s roll,\n'
     '                # not a second one). A round without node dice is untouched.\n'
     '                _s3_dice_nodes = {\n'
     '                    str(_d["s3"]["turn_id"]): _d\n'
     '                    for _d in (turn_dice or {}).values()\n'
     '                    if isinstance(_d, dict) and isinstance(_d.get("s3"), dict)\n'
     '                    and _d["s3"].get("turn_id")}\n'
     '                _s3_said_of: dict[str, str] = {}\n'
     '\n'
     '                def _s3_cont_of(_row_at: int, _tid: str) -> bool:\n'
     '                    # a live-written round names only a turn\'s FIRST chunk\n'
     '                    # with turn_text; a prepared round\'s takes each carry\n'
     '                    # their own, so there the words decide: a chunk that\n'
     '                    # does not open its turn continues it\n'
     '                    try:\n'
     '                        _ti0 = (turn_ix[_row_at]\n'
     '                                if _row_at < len(turn_ix) else -1)\n'
     '                        if ready_takes is None:\n'
     '                            return bool(0 <= _ti0 < len(aired_items)\n'
     '                                        and not aired_items[_ti0].get("turn_text"))\n'
     '                        if not _s3_said_of:\n'
     '                            _ids = ((ready_meta.get("system3") or {}).get("turns") or {})\n'
     '                            for _i, (_m, _said) in enumerate(banter_turns(\n'
     '                                    str(ready_meta.get("script") or ""),\n'
     '                                    str(ready_meta.get("caller_name") or ""),\n'
     '                                    str(ready_meta.get("caller2_name") or ""))):\n'
     '                                if _ids.get(str(_i)):\n'
     '                                    _s3_said_of[str(_ids[str(_i)])] = " ".join(\n'
     '                                        str(_said or "").lower().split())\n'
     '                            _s3_said_of.setdefault("", "")\n'
     '                        _probe = " ".join(str(transcript[_row_at][1] or "")\n'
     '                                          .lower().split())[:400]\n'
     '                        return (len(_probe) >= 4\n'
     '                                and (_s3_said_of.get(_tid) or "").find(_probe) > 0)\n'
     '                    except Exception:  # noqa: BLE001\n'
     '                        return False\n'
     '\n'
     '                def _td_of(_row_at: int) -> dict[str, Any]:\n'
     '                    _t = (turn_ix[_row_at]\n'
     '                          if _row_at < len(turn_ix) else -1)\n'
     '                    _got = (turn_dice or {}).get(_t)\n'
     '                    if _t >= 0 and _s3_dice_nodes:            # [s3-own-dice]\n'
     '                        _st = _s3_row_bare(_row_at)\n'
     '                        if _st.get("conversation_id"):\n'
     '                            _tid = str(_st.get("turn_id") or "")\n'
     '                            _got = _s3_dice_nodes.get(_tid) if _tid else None\n'
     '                            if isinstance(_got, dict) and _s3_cont_of(_row_at, _tid):\n'
     '                                _got = dict(_got, cont=True)\n'
     '                    return _got if isinstance(_got, dict) else {}\n', 1),
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

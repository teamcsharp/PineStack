"""[boot-dj] After a reboot the DJs talk first: a banked, ready round opens the show.

2026-09-30, the operator, asked what should be heard first after a restart:
"DJs talk right away - the first thing on air is a banked, ready DJ round, then
the music continues. No minutes-long wait for the DJs."

Measured on the boot of 2026-09-30 06:58:37Z (process start) with 240 finished
rounds "ready" in the cupboard: the first DJ line was published 92 s later, and
it was a produced ad chapter, not a banked round. Two faults, each on the road
that owns it:

  1. THE BOOT ROAD NEVER ASKED THE CUPBOARD. resume_radio's #824 instant open
     ("a respin never opens with silence") called cover_the_gap, whose 100%-talk
     ladder asks only the banter larder (68 of its 70 rows already aired, the
     re-air gate refused them all), finds "no zero-work larder round" and then
     rolls a RECORD (gap.record). The cupboard of banked rounds on the other
     roads - manager, gallery, caller, news - is reached only by the silence
     rescues, and at boot nobody has been silent yet (talk_quiet_for() starts
     at 0 in dj_start), so nothing asked. Cure: the respin opens with
     dead_air_rescue(0) - the cupboard's own out-of-turn door (#1164: "quiet 0
     ... the cupboard answers before one opens") - and falls back to the old
     cover (record, then SFX) only when the cupboard has nothing that will air.
     It fires after dj_start, when the station is on and the larder, pantry and
     shelf are loaded (it used to be fired before them).

  2. "READY" COUNTED ROUNDS THE BOOTH WILL NEVER AIR. While System 3 is active,
     _speak_turns_floorless withholds any round whose bound roulette turns do
     not make a complete conversation ("incomplete conversation withheld after
     repair", "9 of 11 turns; limit 9"). dialogue_row_ready - "the one
     authoritative zero-work-to-air predicate" - never asked, so 107 of the 130
     unheard dialogue rounds on the open roads were counted ready, the rescue
     and the standing consumer picked them oldest-first, the booth refused each
     one, and the consumer aired NOTHING. s3_binding_withheld() reads the
     booth's gate ahead of the booth, from the same entry the booth is handed
     (the script, `lines`, `system3`, `turn_dice`); dialogue_row_ready and its
     explainer dialogue_row_ready_why ask it. A test runs the real booth on the
     same fixtures so the two cannot drift.

Heard-marking is untouched: the round goes through _ready_shelf_air, whose
commit stamps it aired and flushes the shelf, and the 24 h no-repeat leg of the
re-air gate refuses a round aired by the previous boot - so a restart loop
cannot open every boot with the same round.

Usage (app.py ON THE HOST - never across the share):
    python3 tools/boot_dj_patch.py --check app.py
    python3 tools/boot_dj_patch.py --apply app.py
--check exits 0 ready, 2 already applied, 1 anchors missing (named).
Every anchor is asserted unique; LF only; written atomically."""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

MARK = "[boot-dj]"

# ---------------------------------------------------------------- edit 1
# The predicate, inserted immediately before dialogue_row_ready.
PRED_AT = '''def dialogue_row_ready(kind: str, row: Any) -> bool:
    """One authoritative zero-work-to-air predicate for scheduled stock."""
'''
PRED_MARK = "def s3_binding_withheld(entry: Any) -> str:"
PRED = '''# [boot-dj] THE BOOTH'S SYSTEM 3 GATE, READ AHEAD OF THE BOOTH.
#
# While System 3 is active, _speak_turns_floorless withholds a round whose
# bound roulette turns do not make a complete conversation - and it is the
# LAST door, reached after the rescue or the standing consumer has already
# chosen the round, taken the floor and spent its turn. Measured 2026-09-30
# at boot: 107 of the 130 unheard dialogue rounds on the open roads failed
# it ("incomplete conversation withheld after repair", "9 of 11 turns;
# limit 9"), all of them counted READY, so the cupboard said 240 rounds
# stood ready while the consumer aired nothing and a reboot opened on a
# record. This asks exactly what the booth asks, of the entry the booth is
# handed (_ready_air_entry: `script`, `lines`, `system3`, `turn_dice`), so
# dialogue_row_ready stops calling a round ready that can never air.
# tests/test_boot_dj_2026_09_30.py runs the real booth on the same fixtures.
#
# banter_turns costs ~300 us a round and this rides every readiness walk,
# so the answer is kept per entry until its words, lines or binding change.
_S3_BIND_MEMO: dict[int, tuple[Any, str]] = {}


def s3_binding_withheld(entry: Any) -> str:
    """[boot-dj] "" when System 3 would let this round through the booth,
    else the booth's own words for why it withholds it."""
    try:
        if not isinstance(entry, dict):
            return ""
        _active = globals().get("_s3_active")
        if not (callable(_active) and _active()):
            return ""
        s3 = entry.get("system3")
        if not isinstance(s3, dict) or s3.get("mode") != "active":
            return "round withheld without an active System 3 conversation"
        ids = s3.get("turns") or {}
        dice_raw = entry.get("turn_dice")
        script = str(entry.get("script") or "")
        sig = (script, entry.get("caller_name"), entry.get("caller2_name"),
               entry.get("lines"), s3.get("planned_turns"),
               id(ids), len(ids) if isinstance(ids, dict) else -1,
               id(dice_raw), len(dice_raw) if isinstance(dice_raw, dict) else -1)
        held = _S3_BIND_MEMO.get(id(entry))
        if held is not None and held[0] == sig:
            return held[1]
        turns = banter_turns(script, str(entry.get("caller_name") or ""),
                             str(entry.get("caller2_name") or ""))
        dice = _turn_dice_map(entry)
        if not isinstance(ids, dict):
            ids = {}
        positions = [i for i in range(len(turns))
                     if str(ids.get(str(i)) or "")
                     and str((dice.get(i, {}).get("s3") or {}).get("turn_id") or "")
                     == str(ids.get(str(i)))]
        why = ""
        if not positions:
            why = "round withheld without bound roulette turns"
        else:
            planned = int(s3.get("planned_turns") or len(positions))
            try:
                limit = int(entry.get("lines"))
            except (TypeError, ValueError):
                limit = 0
            if (planned < 3 or len(positions) != planned or limit < planned
                    or len({str(turns[i][0]) for i in positions}) < 2):
                why = ("incomplete conversation withheld after repair "
                       "(%d of %d turns; limit %d)" % (len(positions), planned, limit))
        if len(_S3_BIND_MEMO) > 8192:
            _S3_BIND_MEMO.clear()
        _S3_BIND_MEMO[id(entry)] = (sig, why)
        return why
    except Exception:  # noqa: BLE001
        return ""


'''

# ---------------------------------------------------------------- edit 2
# dialogue_row_ready asks it, inside the conversation block, after the
# phone-call contract.
READY_AT = '''            if (content_gate_enabled("call_contract") and str(kind) == "caller"
                    and callable(_call_gate)
                    and not _call_gate(entry)):
                return False
        return (dialogue_tint_ready(kind, row)
                and dialogue_audio_ready(kind, row))
'''
READY_MARK = "# [boot-dj] ...and a round System 3's booth gate would withhold"
READY_NEW = '''            if (content_gate_enabled("call_contract") and str(kind) == "caller"
                    and callable(_call_gate)
                    and not _call_gate(entry)):
                return False
            # [boot-dj] ...and a round System 3's booth gate would withhold
            # is not zero-work-to-air either: it never reaches the air at all.
            if s3_binding_withheld(entry):
                return False
        return (dialogue_tint_ready(kind, row)
                and dialogue_audio_ready(kind, row))
'''

# ---------------------------------------------------------------- edit 3
# The explainer names it, in the same order.
WHY_AT = '''                return "the phone-call contract does not hold"
'''
WHY_MARK = "System 3 would withhold it at the booth: "
WHY_NEW = '''                return "the phone-call contract does not hold"
            _s3_withheld = s3_binding_withheld(entry)          # [boot-dj]
            if _s3_withheld:
                return "System 3 would withhold it at the booth: " + _s3_withheld
'''

# ---------------------------------------------------------------- edit 4
# dead_air_rescue says who asked, so the forced card is honest at boot.
RESCUE_SIG_AT = '''async def dead_air_rescue(quiet: float) -> str:
'''
RESCUE_SIG_NEW = '''async def dead_air_rescue(quiet: float, why: str = "") -> str:
'''
RESCUE_SIG_MARK = 'async def dead_air_rescue(quiet: float, why: str = "") -> str:'

RESCUE_NOTE_AT = '''                        % ("the show ran out of things to say" if quiet <= 0
                           else "dead air %ds" % int(quiet),
'''
RESCUE_NOTE_NEW = '''                        % (why or ("the show ran out of things to say" if quiet <= 0   # [boot-dj]
                                   else "dead air %ds" % int(quiet)),
'''
RESCUE_NOTE_MARK = 'why or ("the show ran out of things to say" if quiet <= 0   # [boot-dj]'

RESCUE_CARD_AT = '''                        why=("the show ran out of things to say"
                             if quiet <= 0 else
                             "the room was quiet %d s" % int(quiet))
'''
RESCUE_CARD_NEW = '''                        why=(why or ("the show ran out of things to say"   # [boot-dj]
                                     if quiet <= 0 else
                                     "the room was quiet %d s" % int(quiet)))
'''
RESCUE_CARD_MARK = 'why=(why or ("the show ran out of things to say"   # [boot-dj]'

# ---------------------------------------------------------------- edit 5
# The boot road: the respin opens with a banked round, after dj_start.
BOOT_AT = '''    await asyncio.sleep(5)            # let the music index load first
    # #824: a respin never opens with silence — an off-the-shelf line airs
    # NOW, before the first model write or long render.
    async def _instant_open() -> None:
        try:
            await cover_the_gap("dj", "the station is respinning (#824)")
        except Exception:
            pass
    fire_and_forget(_instant_open())
'''
BOOT_MARK = "# [boot-dj] THE FIRST THING ON AIR AFTER A REBOOT IS A BANKED DJ ROUND."
BOOT_NEW = '''    await asyncio.sleep(5)            # let the music index load first
    # #824: a respin never opens with silence — an off-the-shelf line airs
    # NOW, before the first model write or long render.
    #
    # [boot-dj] THE FIRST THING ON AIR AFTER A REBOOT IS A BANKED DJ ROUND.
    # The operator, 2026-09-30: "DJs talk right away - the first thing on
    # air is a banked, ready DJ round, then the music continues. No
    # minutes-long wait for the DJs." This called cover_the_gap alone, and
    # at 100% talk that ladder asks only the banter larder and then rolls a
    # record - so a reboot with 240 finished rounds in the cupboard opened on
    # a record and the first DJ line came 92 s later. The cupboard's own
    # out-of-turn door answers first now: dead_air_rescue(0) takes the
    # readiest finished round of the entry on air, else manager, gallery,
    # caller, news, through _ready_shelf_air - which stamps it heard at the
    # hand-off and keeps the repeat check, so no reboot can open on a round
    # an earlier one already aired. Only when the cupboard holds nothing
    # that will air does the old cover (a rolled record, then SFX) go.
    async def _instant_open() -> None:
        try:
            if await dead_air_rescue(
                    0.0, "the station came back on air after a restart - the "
                         "first thing it says is a banked round (#824)"):
                return
        except Exception:  # noqa: BLE001
            pass
        try:
            await cover_the_gap("dj", "the station is respinning (#824)")
        except Exception:
            pass
'''

START_AT = '''    try:
        dj_start(dj_best_station(str(want.get("station") or "")))
    except Exception:
        pass
'''
START_MARK = "fire_and_forget(_instant_open())       # [boot-dj] after dj_start"
START_NEW = '''    try:
        dj_start(dj_best_station(str(want.get("station") or "")))
    except Exception:
        pass
    # [boot-dj] ...and it opens once the station IS on: dj_start is what
    # turns the show on and loads the larder, the pantry and the shelf the
    # banked round is taken from. Fired above it, the open ran before them
    # whenever the satellite heal awaited, and found nothing to air.
    fire_and_forget(_instant_open())       # [boot-dj] after dj_start
'''

EDITS = [
    # (name, anchor, replacement, applied-marker)
    ("predicate", PRED_AT, PRED + PRED_AT, PRED_MARK),
    ("ready gate", READY_AT, READY_NEW, READY_MARK),
    ("ready why", WHY_AT, WHY_NEW, WHY_MARK),
    ("rescue signature", RESCUE_SIG_AT, RESCUE_SIG_NEW, RESCUE_SIG_MARK),
    ("rescue note", RESCUE_NOTE_AT, RESCUE_NOTE_NEW, RESCUE_NOTE_MARK),
    ("rescue card", RESCUE_CARD_AT, RESCUE_CARD_NEW, RESCUE_CARD_MARK),
    ("boot open", BOOT_AT, BOOT_NEW, BOOT_MARK),
    ("boot fire", START_AT, START_NEW, START_MARK),
]


def plan(text: str) -> tuple[list[str], list[str], list[str]]:
    """(ready, applied, missing) edit names."""
    ready, applied, missing = [], [], []
    for name, anchor, _new, mark in EDITS:
        if text.count(mark) == 1:
            applied.append(name)
            continue
        if text.count(mark) > 1:
            missing.append("%s (its marker appears %d times)" % (name, text.count(mark)))
            continue
        n = text.count(anchor)
        if n == 1:
            ready.append(name)
        else:
            missing.append("%s (anchor found %d times)" % (name, n))
    return ready, applied, missing


def apply(text: str) -> str:
    for name, anchor, new, mark in EDITS:
        if text.count(mark) == 1:
            continue
        assert text.count(anchor) == 1, "%s: anchor count %d" % (name, text.count(anchor))
        text = text.replace(anchor, new, 1)
        assert text.count(mark) == 1, "%s: marker count after apply" % name
    return text


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("--check", "--apply"):
        print(__doc__.split("Usage")[1] if "Usage" in __doc__ else __doc__)
        return 1
    path = Path(argv[2])
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    if "\r\n" in text:
        print("refusing: %s has CRLF line endings" % path)
        return 1
    ready, applied, missing = plan(text)
    if argv[1] == "--check":
        for n in applied:
            print("applied  " + n)
        for n in ready:
            print("ready    " + n)
        for n in missing:
            print("MISSING  " + n)
        if missing:
            return 1
        return 2 if not ready else 0
    if missing:
        for n in missing:
            print("MISSING  " + n)
        return 1
    if not ready:
        print("already applied")
        return 0
    out = apply(text)
    ast.parse(out)
    tmp = path.with_name(path.name + ".boot-dj.tmp")
    tmp.write_bytes(out.encode("utf-8"))
    os.replace(tmp, path)
    ready2, applied2, missing2 = plan(out)
    assert not ready2 and not missing2, (ready2, missing2)
    print("APPLIED  " + ", ".join(ready))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

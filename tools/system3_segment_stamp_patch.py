"""[s3-segment] Every line of the script names the scheduled segment it went out in.

The operator (2026-09-28): "every conversation should be chained as the
"segment" per the station that is scheduled with everything for that segment
occuring within the section of the messenger view ... be able to trace the
nodes of how the segments are constructed via roulette RNG and System 3".

The station's scheduled segment is the running order's OCCURRENCE - the id
_RADIO["sched_pos"] carries, System2's slot ("hour-<ms>:<entry>"), the key the
director's room is built on. Nothing on the record named it: measured over
four live hours, identity.schedule_occurrence_id was empty on 276 of 276
conversations and no script-ledger or air-log row carried an entry, and
segment_inspect (#1168) says so in words ("the ledger does not record which
one a finished round was written for").

  segment-on-air        segment_on_air(at), beside _schedule_dispatch_occurrence:
                        the segment that owned the air at a
                        moment - the engine's own published position (System2's
                        clock refreshed when its window has closed), and for a
                        moment already past the segments it handed out, then
                        System2's plan windows. Never raises; {} with no schedule.
  ledger-segment-at     script_ledger_commit takes the segment at the moment the
  ledger-row-segment    block took its place in the script (`at`: now, or the page
                        door's reservation time) and writes it on every row.
  ledger-segment-hook   ...and hands the block to System 3's segment register
                        (system3_segment_block), after the observe hook.
  inspect-segment       segment_inspect answers WHICH entry from the stamp.

Measured 2026-09-28 (6 h, 455 heard blocks): stamped at block allocation a
segment never reopens walking the script in order; stamped at hearing it would
reopen 17 times (the air stepped back a block 35 times).

--check exits 0 ready / 2 applied / 1 missing. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

SEGMENT_ON_AIR = '''# --- [s3-segment] THE SCHEDULED SEGMENT A LINE BELONGS TO ----------------------
#
# "every conversation should be chained as the "segment" per the station that
# is scheduled with everything for that segment occuring within the section of
# the messenger view" (the operator, 2026-09-28). The station's scheduled
# segment is the running order's OCCURRENCE: the id _RADIO["sched_pos"]
# carries, System2's slot ("hour-<ms>:<entry>") while System2 owns the clock,
# the legacy walk's otherwise - the key the director's room is built on.
# Nothing on the record named it (identity.schedule_occurrence_id empty on 276
# of 276 conversations; no ledger or air-log row carried an entry), so the
# director still attributes aired lines to its entries by their time window.
#
# It is taken when a line takes its PLACE in the script - its block, at commit
# or at the page door - because that is the order the document, the Messenger
# and the playout sequencer keep: measured over six live hours, stamped then a
# segment never reopens walking the script in order; stamped when each line was
# heard it would reopen 17 times (the air stepped back a block 35 times).
_SEGMENT_SEEN: list[dict[str, Any]] = []     # the segments handed out, oldest first
SEGMENT_SEEN_KEEP = 240


def _segment_brief(pos: Any, slot: Any) -> dict[str, Any]:
    """The published position as the ledger keeps it: the occurrence, its entry
    on the sheet, the kind of segment, its name and its window."""
    pos = pos if isinstance(pos, dict) else {}
    slot = slot if isinstance(slot, dict) else {}
    occ = str(pos.get("occurrence") or "")
    if not occ:
        return {}
    # the entry published beside the position must be the same one
    if slot and (str(slot.get("occurrence") or "") != occ if slot.get("occurrence")
                 else str(slot.get("id") or "") != str(pos.get("slot_id") or "")):
        slot = {}
    try:
        start = float(pos.get("started") or slot.get("start") or 0)
    except (TypeError, ValueError):
        start = 0.0
    try:
        ends = float(pos.get("deadline") or slot.get("deadline") or 0)
        if not ends and start and slot.get("minutes"):
            ends = start + max(0.25, float(slot.get("minutes") or 3)) * 60.0
    except (TypeError, ValueError):
        ends = 0.0
    kind = str(slot.get("kind") or "")
    try:
        index = int(pos.get("index") or 0)
    except (TypeError, ValueError):
        index = 0
    return {"id": occ[:120],
            "template": str(pos.get("slot_id") or slot.get("template_id") or "")[:80],
            "kind": kind[:40], "label": str(slot.get("label") or kind)[:80],
            "start": round(start, 3), "ends": round(ends, 3),
            "hour": str(pos.get("hour") or slot.get("hour_key") or "")[:40], "index": index,
            "engine": ("system2" if pos.get("preset") == "system2" or slot.get("engine") == "system2"
                       else "schedule")}


def _segment_brief_slot(slot: Any) -> dict[str, Any]:
    """One of System2's planned slots, as the ledger keeps a segment."""
    if not isinstance(slot, dict) or not slot.get("id"):
        return {}
    try:
        return {"id": str(slot["id"])[:120], "template": str(slot.get("template_id") or "")[:80],
                "kind": str(slot.get("kind") or "")[:40],
                "label": str(slot.get("label") or slot.get("kind") or "")[:80],
                "start": round(float(slot.get("start") or 0), 3),
                "ends": round(float(slot.get("deadline") or 0), 3),
                "hour": str(slot.get("hour_key") or "")[:40], "index": int(slot.get("ordinal") or 0),
                "engine": "system2"}
    except (TypeError, ValueError):
        return {}


def _segment_seen_note(brief: dict[str, Any]) -> None:
    if not brief or not brief.get("id"):
        return
    try:
        if _SEGMENT_SEEN and _SEGMENT_SEEN[-1].get("id") == brief["id"]:
            return
        _SEGMENT_SEEN.append(dict(brief, seen=round(time.time(), 3)))
        del _SEGMENT_SEEN[:-SEGMENT_SEEN_KEEP]
    except Exception:  # noqa: BLE001
        pass


def segment_on_air(at: float = 0.0) -> dict[str, Any]:
    """[s3-segment] The scheduled segment that owned the air at `at` (now when
    0): {id, template, kind, label, start, ends, hour, index, engine}, or {}
    when the station runs no schedule or the moment cannot be answered.

    Now is the engine's own published position (_RADIO["sched_pos"], which
    System2's clock and the legacy walk write), refreshed from System2's clock
    when its window has closed - current_slot_brief, the read made cheap for
    exactly this (#1224). A moment already past is the segment the air was in
    then: one this function handed out whose window holds it, else System2's
    planned window. It never guesses a moment it cannot place. Never raises."""
    try:
        now = time.time()
        t = float(at or 0.0) or now
        runtime = globals().get("_system2")
        try:
            live = runtime() if runtime else None
        except Exception:  # noqa: BLE001
            live = None
        s2 = live is not None and bool(getattr(live, "enabled", False))
        if t >= now - 2.0:
            pos = _RADIO.get("sched_pos") or {}
            try:
                ends = float((pos or {}).get("deadline") or 0)
            except (TypeError, ValueError):
                ends = 0.0
            if s2 and (not (pos or {}).get("occurrence") or (ends and now >= ends)):
                try:
                    live.current_slot_brief()          # republishes sched_pos when it moved
                except Exception:  # noqa: BLE001
                    pass
                pos = _RADIO.get("sched_pos") or {}
            brief = _segment_brief(pos, _RADIO.get("sched_slot") or {})
            _segment_seen_note(brief)
            return brief
        seen = list(_SEGMENT_SEEN)

        def holds(row: dict[str, Any]) -> bool:
            try:
                return float(row.get("start") or 0) <= t < float(row.get("ends") or 0)
            except (TypeError, ValueError):
                return False
        for row in reversed(seen):
            if float(row.get("seen") or 0) <= t + 1.0 and holds(row):
                return {k: v for k, v in row.items() if k != "seen"}
        for row in reversed(seen):
            if holds(row):
                return {k: v for k, v in row.items() if k != "seen"}
        if s2:
            for hour in list(getattr(live, "_plans", None) or []):
                for slot in (hour or {}).get("slots") or []:
                    if float(slot.get("start") or 0) <= t < float(slot.get("deadline") or 0):
                        return _segment_brief_slot(slot)
    except Exception:  # noqa: BLE001
        pass
    return {}


'''

LEDGER_AT_OLD = '    at = float(at or 0.0) or time.time()\n'
LEDGER_AT_NEW = LEDGER_AT_OLD + (
    '    # [s3-segment] the scheduled segment on air when this took its place in the\n'
    '    # script: now for a round, the page door\'s moment for a numbered line\n'
    '    _segment = segment_on_air(at)\n')

ROW_OLD = '            "block": block, "ord": int(row.get("_ord", ord_)), "at": at,  # [air-order] _ord\n'
ROW_NEW = ROW_OLD + '            **({"segment": _segment} if _segment else {}),   # [s3-segment]\n'

HOOK_OLD = '        globals()["system3_observe_ledger"](block, sid, rows, round_kind)\n'
HOOK_NEW = HOOK_OLD + (
    '    # [s3-segment] and to System 3\'s segment register: which scheduled segment\n'
    '    # this block of the script went out in, its lines and their conversations\n'
    '    if _segment and globals().get("system3_segment_block"):\n'
    '        try:\n'
    '            globals()["system3_segment_block"](block, at, sid, rows, _segment, round_kind)\n'
    '        except Exception:  # noqa: BLE001\n'
    '            pass\n')

INSPECT_OLD = '    # THE ADMITTED PLAYBACK OCCURRENCE, when the gate saw this segment go\n'
INSPECT_NEW = (
    '    # [s3-segment] ...AND THE ONE ENTRY IT WAS, when the ledger recorded it: a\n'
    '    # block written since the segment stamp names the scheduled segment that\n'
    '    # owned the air when it took its place in the script, so "one of these"\n'
    '    # above becomes that one.\n'
    '    try:\n'
    '        _seg = first.get("segment") if isinstance(first.get("segment"), dict) else None\n'
    '        out["segment"] = _seg\n'
    '        if _seg and isinstance(out.get("slot"), dict):\n'
    '            out["slot"]["slot_id"] = str(_seg.get("template") or out["slot"].get("slot_id") or "")\n'
    '            out["slot"]["occurrence"] = str(_seg.get("id") or "")\n'
    '            out["slot"]["say"] = ("the ledger recorded the scheduled segment on air when this "\n'
    '                                  "took its place in the script: %s (%s)"\n'
    '                                  % (_seg.get("label") or "?", _seg.get("kind") or "?"))\n'
    '    except Exception:  # noqa: BLE001\n'
    '        pass\n') + INSPECT_OLD

# beside the schedule's own occurrence, and clear of the ledger's [air-order]
# block (its reserve-helpers edit stores the text up to script_ledger_commit)
SCHED_DEF = 'def _schedule_dispatch_occurrence() -> str:\n'

EDITS = [
    ("segment-on-air", SCHED_DEF, SEGMENT_ON_AIR + SCHED_DEF, 1),
    ("ledger-segment-at", LEDGER_AT_OLD, LEDGER_AT_NEW, 1),
    ("ledger-row-segment", ROW_OLD, ROW_NEW, 1),
    ("ledger-segment-hook", HOOK_OLD, HOOK_NEW, 1),
    ("inspect-segment", INSPECT_OLD, INSPECT_NEW, 1),
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

"""[s3-memory] What the writer is reminded of is System 3's MEMORY roll.

The operator's guide (2026-09-28): memory context is given ONLY WHEN RELEVANT -
the clock, a synopsis of the last topic, the last segment and how it went, the
callers per hour against the quota, a synopsis of the last manager message.
Asked how: "Rules, then roulette" - the rules decide eligibility, then the
roulette decides among the eligible, each one a node.

Two edits here (the engine, the table and the runtime are system3.py,
system3_tables.py and system3_runtime.py [s3-memory]):

  host-memory-facts   system3_memory_facts(road, ctx): the station's facts for
                      each kind of memory, read from what it already keeps (the
                      schedule's entry on air, the air log's live index, the
                      calls' quota ring, the chat, the heard subjects) - never a
                      model call, never a disk walk: it runs on the planner's
                      clock. The schedule moving on files the entry before as
                      the last segment, with how it went (lines heard and
                      withdrawn in its window, calls taken), counted once -
                      unless something ran between the two that no round was
                      planned in (then it is filed as unseen, and nothing is
                      said about it). The calls: the rolling hour's count
                      (what quota_behind reads) and the clock hour's own.
                      s3_memory_block(): the items the round's MEMORY roll drew,
                      marked as their own prompt node ("memory"); "" when it drew
                      none; None when no MEMORY roll stands behind the prompt.
  show-memory-yields  _show_memory_raw: a prompt a MEMORY roll stands behind is
                      given exactly that block and nothing else of "Tonight so
                      far". System 3 off, a road it did not plan, the MEMORY
                      table switched off: the digest, as it always was.

(Inserted before art_sell_due and inside _show_memory_raw's own body: the
show_memory door and the _show_memory_raw def line are system3_blocks_patch's
stored text, and the three show_memory(...) call sites are system3_hygiene /
system3_rounds stored text - none of them is touched.)

--check exits 0 ready / 2 applied / 1 missing. --apply is idempotent and
atomic, LF only. ON THE HOST, on wave A's app.py (it needs no batch-7 tool
first: its anchors sit in none of their stored text), with system3.py,
system3_tables.py and system3_runtime.py edited by edit_memctx_*.py - a
station with this app.py and the old modules sends the digest as before.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

HOST = r'''# --- [s3-memory] what the writer is reminded of: System 3's MEMORY roll ---------
#
# The operator's guide (2026-09-28): memory context is given ONLY WHEN RELEVANT -
# the clock, a synopsis of the last topic, the last segment and how it went, the
# callers this hour against the quota, a synopsis of the manager's last message
# - "rules, then roulette". System 3 asks here for the station's facts; its
# MEMORY table's rules decide which kinds are relevant to the round being
# planned, the roulette draws among them, and the writer is handed exactly the
# items drawn, as one block (s3_memory_block, the "memory" node), in place of
# the "Tonight so far" digest. Everything is read from what the station already
# keeps in memory - never a disk walk, never a model call: this runs on the
# planner's clock. (The last topic is System 3's own record of its last round.)
_S3_MEMORY_SEGMENTS: dict[str, Any] = {}
# The running order walks on exactly: the next entry starts where the one
# before it was due to end. A longer gap means something ran in between that
# no round was planned in - System 3 never saw it and says nothing about it.
S3_MEMORY_GAP_S = 30.0


def _s3_segment_went(started: float, ended: float) -> dict[str, Any]:
    """How a segment went, from what the station logged in its window: the
    lines heard and the lines withdrawn (the air log's live index), and the
    calls taken (the quota ring). Counted once, when the schedule moves on."""
    heard = pulled = 0
    try:
        with _AIRLOG_LOCK:
            rows = list(_AIRLOG_INDEX.values())
        for row in rows:
            at = float(row.get("air_at") or row.get("at") or 0)
            if not started <= at < ended:
                continue
            if str(row.get("kind") or "") in AIRLOG_QUIET_KINDS or str(row.get("who") or "") in AIRLOG_QUIET_WHO:
                continue
            state = str(row.get("aired") or "")
            if state in AIRLOG_AIRED:
                heard += 1
            elif state in ("withdrawn", "never"):
                pulled += 1
    except Exception:  # noqa: BLE001
        pass
    try:
        calls = sum(1 for t in _quota_ring("caller") if started <= float(t or 0) < ended)
    except Exception:  # noqa: BLE001
        calls = 0
    return {"heard": heard, "withdrawn": pulled, "calls": calls}


def system3_memory_facts(road: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """The station's facts for System 3's MEMORY roll, one per kind of memory:
    the clock (with the segment on air), the last segment and how it went, the
    calls over the last hour against the quota, the manager's last word from
    upstairs - and `topic`, the last subject the station heard (the runtime
    prefers its own record of the last round). A fact the station does not
    hold is left out; the roll records why the kind was not eligible."""
    out: dict[str, Any] = {}
    now = time.time()
    lt = time.localtime(now)
    seg: dict[str, Any] = {}
    try:
        slot = _RADIO.get("sched_slot") or {}
        pos = _RADIO.get("sched_pos") or {}
        started = float(pos.get("started") or 0)
        if slot and started > 0 and str(slot.get("id") or "") == str(pos.get("slot_id") or ""):
            ends = float(pos.get("deadline") or 0) or started + max(0.25, float(slot.get("minutes") or 3)) * 60.0
            # the occurrence survives a pause (which moves `started`); without one, the start names it
            key = str(pos.get("occurrence") or "") or "%s|%.0f" % (slot.get("id") or "", started)
            seg = {"key": key, "label": " ".join(str(slot.get("label") or slot.get("kind") or "").split())[:80],
                   "kind": str(slot.get("kind") or ""), "started": started, "ends": ends}
    except Exception:  # noqa: BLE001
        seg = {}
    out["clock"] = {"at": now, "hour": lt.tm_hour, "minute": lt.tm_min, "second": lt.tm_sec,
                    "clock": time.strftime("%-I:%M %p", lt).lower(),
                    "segment": {k: seg[k] for k in ("label", "kind", "started", "ends") if k in seg}}
    try:
        # the schedule moving on files the entry before as the last segment -
        # and how it went is counted then, once
        book = _S3_MEMORY_SEGMENTS
        cur = book.get("current") or {}
        if seg and cur.get("key") == seg["key"]:
            # the same entry: a pause moves its end along; its start stays the one first seen
            cur["ends"] = max(float(cur.get("ends") or 0), float(seg["ends"]))
        elif seg:
            if cur and float(seg["started"]) > float(cur.get("started") or 0):
                ends = float(cur.get("ends") or 0)
                ended = min(float(seg["started"]), ends) if ends > 0 else float(seg["started"])
                if ends > 0 and float(seg["started"]) - ends > S3_MEMORY_GAP_S:
                    book["last"] = {"label": "", "kind": "", "unseen": True, "started": ends,
                                    "ended": float(seg["started"])}
                else:
                    book["last"] = dict(cur, ended=ended,
                                        **_s3_segment_went(float(cur.get("started") or 0), ended))
            book["current"] = dict(seg)
        last = book.get("last")
        if isinstance(last, dict) and last.get("ended"):
            out["last_segment"] = {k: last.get(k) for k in ("label", "kind", "started", "ended", "heard",
                                                            "withdrawn", "calls", "unseen") if k in last}
            out["last_segment"]["now"] = {"label": seg.get("label", ""), "started": seg.get("started", 0)}
    except Exception:  # noqa: BLE001
        pass
    try:
        # the rolling hour's count (the station's own quota_behind reads it) and
        # the clock hour's own - the last hour's tail never makes this one look ahead
        ring = [float(t or 0) for t in _quota_ring("caller")]
        top = now - (lt.tm_min * 60 + lt.tm_sec)
        out["callers_quota"] = {"count": len(ring), "this_hour": sum(1 for t in ring if t >= top),
                                "quota": int(quota_target("caller")),
                                "minute": round(lt.tm_min + lt.tm_sec / 60.0, 2), "paused": bool(radio_paused())}
    except Exception:  # noqa: BLE001
        pass
    try:
        for row in reversed(list(_RADIO.get("chat") or [])):
            if str(row.get("who") or "") == "manager" and str(row.get("text") or "").strip():
                out["manager_note"] = {"text": " ".join(str(row["text"]).split())[:500],
                                       "at": float(row.get("air_at") or row.get("ts") or 0),
                                       "ref": str(row.get("id") or "")}
                break
    except Exception:  # noqa: BLE001
        pass
    try:
        heard = list(_RADIO.get("topics") or [])
        if heard and str((heard[-1] or {}).get("text") or "").strip():
            out["topic"] = {"text": " ".join(str(heard[-1]["text"]).split())[:300],
                            "at": float(heard[-1].get("at") or 0), "ref": str(heard[-1].get("file") or "")}
    except Exception:  # noqa: BLE001
        pass
    # What the old digest also carried, handed in as facts so that a MEMORY
    # category of the same name (added on the desk; its item "{synopsis}")
    # brings it back as a rolled node: the pine box speaker's outage (#410)
    # and the machine's real temperature (#886). No default kind rolls them.
    try:
        if (_RADIO.get("voice_to") or "box") in ("box", "both"):
            out_min = (now - float(_BOX_LAST_OK[0])) / 60.0
            if out_min >= 2:
                out["speaker_outage"] = {"text": "the pine box speaker has carried nothing for %d minutes - "
                                                 "their words may be going into a void" % int(out_min),
                                         "minutes": round(out_min, 1)}
    except Exception:  # noqa: BLE001
        pass
    try:
        heat = gpu_temp_fact()
        if heat:
            out["machine_heat"] = {"text": heat, "at": now}
    except Exception:  # noqa: BLE001
        pass
    return out


def s3_memory_block() -> str | None:
    """[s3-memory] The memory block for the prompt being written on this task:
    the items its round's MEMORY roll drew, marked as their own node
    ("memory"); "" when the roll drew none; None when no MEMORY roll stands
    behind this prompt (System 3 off, a road it did not plan, the table off)."""
    fn = globals().get("system3_memory_block")
    if not fn:
        return None
    try:
        got = fn()
    except Exception:  # noqa: BLE001
        return None
    if got is None:
        return None
    return _pb("memory", got) if str(got).strip() else ""


'''

EDITS = [
    ("host-memory-facts",
     'def art_sell_due() -> bool:\n',
     HOST + 'def art_sell_due() -> bool:\n', 1),
    ("show-memory-yields",
     '    if not _RADIO.get("on"):\n        return ""\n    stats = _RADIO.get("session_stats") or {}\n',
     '    if not _RADIO.get("on"):\n        return ""\n'
     '    # [s3-memory] A ROUND SYSTEM 3 PLANNED IS REMINDED OF WHAT ITS MEMORY ROLL\n'
     '    # DREW, AND OF NOTHING ELSE: the rules decided which memories are relevant\n'
     '    # (the clock, the last topic, the last segment, the calls against the\n'
     '    # quota, the manager\'s last word), the roulette drew among them, and the\n'
     '    # items drawn are this block - "" when it drew none. Only a prompt no\n'
     '    # MEMORY roll stands behind (System 3 off, a road it did not plan, the\n'
     '    # table switched off) carries the digest below, as it always did.\n'
     '    _memory = s3_memory_block()\n'
     '    if _memory is not None:\n'
     '        return _memory\n'
     '    stats = _RADIO.get("session_stats") or {}\n', 1),
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

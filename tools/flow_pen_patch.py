#!/usr/bin/env python3
"""[flow-pen] The held rounds go back as the shelves have room, not all at once. 2026-10-05.

This morning's release ([s3-flow-open]) emptied the recovery queue onto the
shelves in twenty minutes: 869 rounds onto shelves built for eight to
twenty-four rows a kind. Nothing deletes an unaired row, so they all stayed -
and every walk the station makes over its stock on the event loop grew with
them. Measured an hour later: _row_clip_keys under dialogue_stock_items held
the loop 12.8 s, and dj_pending's booth_actor_name -> read_guests (a file read
and a JSON parse per row, per poll) 10.0 s and 6.7 s.

What this changes in app.py:
  - dialogue_recovery_release() releases a kind only while its shelf holds
    fewer unaired rows than its cap (shelf_cap(kind); the larder's ceiling
    for banter). The rest wait in the queue - a pen, now - and follow as rows
    air.
  - dialogue_recovery_repen(): the rows the first release put on a shelf
    beyond its cap go back to the pen (newest first; nothing is deleted, the
    first `cap` unaired rows of each kind stay). Runs once when the release
    clock starts.
  - read_guests() is read off the disk when guests.json changes, not on every
    call ([guests-memo]).

Usage:  flow_pen_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        flow_pen_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

GUESTS_OLD = r'''def read_guests() -> list[dict[str, Any]]:
    with _GUESTS_LOCK:
        try:
            rows = json.loads(GUESTS_PATH.read_text())
            return rows if isinstance(rows, list) else []
        except Exception:
            return []
'''
GUESTS_NEW = r'''# [guests-memo] booth_actor_name -> active_guest -> read_guests runs per row of
# every pending list, per poll: a file read and a JSON parse each time. Measured
# 2026-10-05 holding the event loop 10.0 s and 6.7 s under dj_pending. The file
# is read when it changes (mtime and size), looked at every two seconds at most.
_GUESTS_MEMO: dict[str, Any] = {"at": 0.0, "sig": None, "rows": []}


def read_guests() -> list[dict[str, Any]]:
    memo = _GUESTS_MEMO
    now = time.monotonic()
    if memo["sig"] is not None and now - float(memo["at"]) < 2.0:
        return list(memo["rows"])
    with _GUESTS_LOCK:
        try:
            st = GUESTS_PATH.stat()
            sig = (st.st_mtime_ns, st.st_size)
        except OSError:
            sig = (0, 0)
        if sig != memo["sig"]:
            try:
                rows = json.loads(GUESTS_PATH.read_text())
                rows = rows if isinstance(rows, list) else []
            except Exception:
                rows = []
            memo["rows"], memo["sig"] = rows, sig
        memo["at"] = now
        return list(memo["rows"])
'''

GUESTS_WRITE_OLD = r'''            tmp.write_text(json.dumps(rows[:200], indent=1))
            tmp.replace(GUESTS_PATH)
        except OSError:
            pass
'''
GUESTS_WRITE_NEW = r'''            tmp.write_text(json.dumps(rows[:200], indent=1))
            tmp.replace(GUESTS_PATH)
            _GUESTS_MEMO.update(at=0.0, sig=None)        # [guests-memo] the next read sees the change
        except OSError:
            pass
'''

PEN_OLD = r'''DIALOGUE_RECOVERY_PARKED_PATH = data_path("dialogue_recovery_parked.jsonl")
'''
PEN_NEW = r'''DIALOGUE_RECOVERY_PARKED_PATH = data_path("dialogue_recovery_parked.jsonl")


# --- [flow-pen] THE HELD ROUNDS GO BACK AS THE SHELVES HAVE ROOM -----------------
# The first release (2026-10-05) put 869 rounds onto shelves built for eight to
# twenty-four rows a kind. Nothing deletes an unaired row, so they stayed, and
# every walk the station makes over its stock on the event loop grew with them
# (_row_clip_keys 12.8 s, dj_pending 10.0 s). The queue is a pen now: a kind is
# released only while its shelf holds fewer unaired rows than its cap, and the
# rest follow as rows air.
def _flow_shelf_of(kind: str) -> tuple[list[Any], int]:
    """(the list this kind's rows live in, how many unaired rows it should hold)."""
    if str(kind) == "banter":
        return _LARDER, int(_LARDER_MAX)
    return _SHELF.setdefault(str(kind), []), max(1, int(shelf_cap(str(kind))))


def _flow_release_room(kind: str) -> int:
    """How many more unaired rows this kind's shelf has room for right now."""
    try:
        rows, cap = _flow_shelf_of(kind)
        have = sum(1 for r in list(rows)
                   if isinstance(r, dict) and row_unaired(dialogue_entry(r) or r))
        return max(0, cap - have)
    except Exception:  # noqa: BLE001
        return 0


async def dialogue_recovery_repen() -> dict[str, Any]:
    """[flow-pen] Rows the first release put on a shelf beyond its cap go back
    to the pen. The first `cap` unaired rows of each kind stay where they are
    (the earliest released, the likeliest to be recorded already); the rest -
    released rows only, newest first - return to the queue with everything
    they carried. Nothing is deleted."""
    out: dict[str, Any] = {"moved": 0, "by_kind": {}}
    with _DIALOGUE_RECOVERY_LOCK:
        queued = {str(it.get("id") or "") for it in _DIALOGUE_RECOVERY}
    back: list[dict[str, Any]] = []
    for n, kind in enumerate(["banter"] + [str(k) for k in list(_SHELF) if str(k) not in ("banter", "track_talk")]):
        rows, cap = _flow_shelf_of(kind)
        unaired = [r for r in list(rows) if isinstance(r, dict) and row_unaired(dialogue_entry(r) or r)]
        excess = len(unaired) - cap
        if excess <= 0:
            continue
        gone: set[int] = set()
        for row in reversed(unaired):
            if excess <= 0:
                break
            entry = dialogue_entry(row) or row
            if str((entry.get("handoff_flow") or {}).get("why") or "") != "released from the recovery queue":
                continue
            if entry.get("preparing") or entry.get("tinting"):
                continue                     # a recording has it right now; it stays
            cid = str((entry.get("system3") or {}).get("conversation_id")
                      or (entry.get("dialogue_recovery_handle") or {}).get("conversation_id") or "")
            if not cid or cid in queued:
                continue
            entry["dialogue_recovery_pending"] = True
            item = {"id": cid, "kind": kind, "queued_at": time.time(), "entry": entry, "ready_at": 0.0}
            if entry is not row:
                item["shelf_row"] = {k: copy.deepcopy(v) for k, v in row.items() if k != "entry"}
            back.append(item)
            queued.add(cid)
            gone.add(id(row))
            excess -= 1
        if gone:
            rows[:] = [r for r in rows if id(r) not in gone]
            out["by_kind"][kind] = len(gone)
            out["moved"] += len(gone)
        await asyncio.sleep(0)
    if back:
        with _DIALOGUE_RECOVERY_LOCK:
            _DIALOGUE_RECOVERY.extend(reversed(back))        # the order they were released in
        try:
            _UNHEARD_MEMO.update(at=0.0, value=None)
            _INVENTORY_PLAN["at"] = 0.0
            _COMMITS["at"] = 0.0
        except Exception:  # noqa: BLE001
            pass
        _larder_save()
        _pantry_save(True)
        _dialogue_recovery_save()
        pipeline_log("system3", ("[flow-pen] %d released round(s) went back to the pen - their shelves were "
                                 "past their caps; they follow as rows air" % out["moved"])[:200],
                     extra=json.dumps(out["by_kind"]))
    out["pen"] = len(_DIALOGUE_RECOVERY)
    return out
'''

ROOM_OLD = r'''    if limit and int(limit) > 0:
        items = items[:int(limit)]
    if not items:
        out["left"] = len(_DIALOGUE_RECOVERY)
        return out
    if not s3_flow("recovery_release", "%d held round(s) go back to their shelves" % len(items),
'''
ROOM_NEW = r'''    # [flow-pen] only as many of a kind as its shelf has room for; a row that is
    # only leaving the queue (it aired, it has no words) takes no room
    _room: dict[str, int] = {}
    _fits = []
    for _it in items:
        _entry = _it.get("entry") if isinstance(_it.get("entry"), dict) else None
        _kind = str(_it.get("kind") or (_entry or {}).get("prep_kind") or "banter")
        if _entry is None or not str(_entry.get("script") or "").strip() or not row_unaired(_entry):
            _fits.append(_it)
            continue
        if _kind not in _room:
            _room[_kind] = _flow_release_room(_kind)
        if _room[_kind] > 0:
            _room[_kind] -= 1
            _fits.append(_it)
    out["waiting"] = len(items) - len(_fits)
    items = _fits
    if limit and int(limit) > 0:
        items = items[:int(limit)]
    if not items:
        out["left"] = len(_DIALOGUE_RECOVERY)
        return out
    if not s3_flow("recovery_release", "%d held round(s) go back to their shelves" % len(items),
'''

CLOCK_OLD = r'''    """[s3-flow-open] Empty the recovery queue in small batches, the air first."""
    await asyncio.sleep(60)
    while True:
'''
CLOCK_NEW = r'''    """[s3-flow-open] Empty the recovery queue in small batches, the air first."""
    await asyncio.sleep(60)
    try:
        if s3_flow_is_open():
            await dialogue_recovery_repen()      # [flow-pen] once: what the first release left past the caps
    except Exception as exc:  # noqa: BLE001
        pipeline_log("system3", "[flow-pen] the shelves could not be brought back to their caps",
                     extra=("%s: %s" % (type(exc).__name__, exc))[:200])
    while True:
'''

RUNG_OLD = r'''            said.append("  reserve    %d held round(s) are going back to their shelves" % _queued)
'''
RUNG_NEW = r'''            said.append("  reserve    %d held round(s) are penned; they go back as their shelves have room" % _queued)   # [flow-pen]
'''

EDITS: dict[str, list[tuple[str, str, str, str, int]]] = {
    "app.py": [
        ("guests read on change", GUESTS_OLD, GUESTS_NEW, "_GUESTS_MEMO: dict[str, Any] = {", 1),
        ("a write is seen at once", GUESTS_WRITE_OLD, GUESTS_WRITE_NEW,
         "# [guests-memo] the next read sees the change", 1),
        ("the pen and the re-pen", PEN_OLD, PEN_NEW, "async def dialogue_recovery_repen(", 1),
        ("release by room", ROOM_OLD, ROOM_NEW, "# [flow-pen] only as many of a kind as its shelf has room for", 1),
        ("the clock re-pens once", CLOCK_OLD, CLOCK_NEW, "# [flow-pen] once: what the first release left past the caps", 1),
        ("the rung says so", RUNG_OLD, RUNG_NEW, "they go back as their shelves have room", 1),
    ],
}


def _read(path: Path) -> tuple[str, bool]:
    text = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in text
    if crlf:
        if text.count("\r\n") != text.count("\n"):
            raise SystemExit("%s has mixed line endings; refusing to guess" % path)
        text = text.replace("\r\n", "\n")
    if "\r" in text:
        raise SystemExit("%s has bare carriage returns; refusing to guess" % path)
    return text, crlf


def _state(text: str, edit: tuple[str, str, str, str, int]) -> str:
    _name, old, _new, probe, count = edit
    have = text.count(probe)
    if have == count:
        return "applied"
    if have:
        return "partial (%d of %d probes)" % (have, count)
    found = text.count(old)
    return "ready" if found == count else "missing (anchor found %d, expected %d)" % (found, count)


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    apply = argv[1] == "--apply"
    any_ready, any_missing = False, False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        text, crlf = _read(path)
        todo = []
        for edit in edits:
            state = _state(text, edit)
            print("%-10s %-28s %s" % (name, edit[0], state))
            if state == "ready":
                todo.append(edit)
                any_ready = True
            elif state != "applied":
                any_missing = True
        plans.append((path, text, crlf, todo))
    if any_missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not any_ready:
        print("already applied")
        return 2
    if not apply:
        print("ready")
        return 0
    for path, text, crlf, todo in plans:
        if not todo:
            continue
        for _name, old, new, probe, count in todo:
            assert text.count(old) == count, (path.name, _name)
            text = text.replace(old, new)
            assert text.count(probe) == count, (path.name, _name, "probe")
        out = text.replace("\n", "\r\n") if crlf else text
        tmp = path.with_name(path.name + ".flowpen.tmp")
        tmp.write_bytes(out.encode("utf-8"))
        os.replace(tmp, path)
        print("wrote %s (%d edit(s), %s)" % (path.name, len(todo), "CRLF" if crlf else "LF"))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

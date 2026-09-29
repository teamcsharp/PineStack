#!/usr/bin/env python3
"""[seg-names] THE SCRIPT'S ROUND CARDS CARRY THE OPERATOR'S SEGMENT NAMES - app.py.

"these should be named after the segment names I assigned to the station."

The Script's round cards are the scene headings of /api/screenplay, and the
page titled them by ROAD ("Studio Banter") because the round ledger
(screenplay_round_row -> data/screenplay_rounds.jsonl) never wrote down which
running-order entry a round filled. The link exists - System2's reservation
(`_system2.slot_id`), the shelf's window (`_ready_slot`), the slot a job banked
it for (`system2_slot`) - but only on the entry dict, which dies at air.

This carries it through the owning road:
  1. screenplay_round_slot(entry)   the link, strongest first, read as the
                                    round OPENS (stacked > shelf > the entry on
                                    air when it runs this road > banked); the
                                    label from System2's own plan, never the
                                    clock
  2. screenplay_round_open          puts it on the mark (and on
                                    _SCREENPLAY_STATE["open"] for the round on
                                    air, which has no ledger row yet)
  3. screenplay_round_row           writes it on the round: "slot"
  4. screenplay_round_write         (thread) names an unnamed occurrence from
                                    system2.sqlite3 or the sheet
  5. _screenplay_disk               hands the open round to the compose
  6. screenplay_compose             every scene heading carries "slot"
                                    {label,id,entry,how} or {none, why}

Usage: seg_names_app_patch.py --check|--apply [path/to/app.py]
  --check exits 0 ready, 2 already applied, 1 anchors missing (named).
CRLF-aware: the file's own newline style is kept.
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile

MARK = "[seg-names]"

HELPERS = '''# [seg-names] THE ENTRY A ROUND WAS MADE FOR, WRITTEN DOWN WITH IT.
#
# "these should be named after the segment names I assigned to the
#  station." The Script's round cards were titled by ROAD ("Studio Banter")
# because this ledger never recorded which running-order entry a round
# filled. The link exists - System2's reservation (`_system2.slot_id`), the
# shelf's window (`_ready_slot`), the slot a job banked it for
# (`system2_slot`) - but only on the entry dict, and it died at air.
# screenplay_round_open reads it off the entry as the round opens,
# screenplay_round_row writes it on the round, and the scene heading carries
# it to the page. The name comes from the occurrence itself (System2's plan,
# its store, then the sheet) - never from the clock: adherence to the
# running order was once measured at 4%, so time is no proxy.
SCREENPLAY_ENTRY_ROADS = frozenset(
    set(SCHED_PREP_KIND) | set(SCHED_PREP_KIND.values()) | {"recap", "record"})


def _screenplay_road(kind: str) -> str:
    """A sheet kind as the road that fills it (banter_caller -> caller)."""
    k = str(kind or "")
    return str(SCHED_PREP_KIND.get(k) or k)


def _screenplay_slot_named(slot: dict[str, Any]) -> dict[str, Any]:
    """Name an occurrence from System2's plan in memory. Pure dict reads."""
    try:
        runtime = globals().get("_system2")
        live = runtime() if runtime else None
        occ = str(slot.get("occurrence") or "")
        hours = (list(getattr(live, "_plans", None) or [])
                 + list(getattr(live, "_event_plans", None) or []))
        for hour in hours:
            for one in ((hour or {}).get("slots") or []):
                if str((one or {}).get("id") or "") == occ:
                    slot["label"] = " ".join(str(one.get("label") or "").split())[:80]
                    slot["kind"] = str(one.get("kind") or "")[:40]
                    slot["preset"] = str(one.get("preset") or "")[:60]
                    slot["start"] = one.get("start")
                    slot["label_from"] = "system2 plan"
                    return slot
    except Exception:  # noqa: BLE001
        pass
    return slot


def screenplay_round_slot(entry: dict[str, Any]) -> dict[str, Any]:
    """Which running-order entry this round fills, from the entry's own
    links, strongest first:

      stacked       System2 reserved it against this occurrence
      shelf         the ready shelf aired it inside this window
      on its entry  it aired while the engine's entry on air ran its road
      banked        a System2 job wrote it FOR this occurrence

    {"how": "none", "why": ...} when nothing links it - a fact the card
    shows as "(no slot)", not a failure. On the loop; never raises."""
    try:
        kind = _screenplay_road(str(entry.get("prep_kind") or ""))
        s2 = entry.get("_system2")
        if isinstance(s2, dict) and str(s2.get("slot_id") or ""):
            occ = str(s2.get("slot_id") or "")
            return _screenplay_slot_named({
                "occurrence": occ, "entry": occ.rsplit(":", 1)[-1],
                "how": "stacked",
                "reservation": str(s2.get("reservation_id") or "")[:40]})
        win = entry.get("_ready_slot")
        if (isinstance(win, dict) and str(win.get("occurrence") or "")
                and (not kind or _screenplay_road(
                    str(win.get("kind") or "")) == kind)):
            got = _screenplay_slot_named({
                "occurrence": str(win.get("occurrence") or ""),
                "entry": str(win.get("slot_id") or ""), "how": "shelf"})
            if not got.get("label"):
                seg = segment_on_air()
                if (isinstance(seg, dict)
                        and str(seg.get("id") or "") == got["occurrence"]):
                    got["label"] = str(seg.get("label") or "")[:80]
                    got["label_from"] = "segment on air"
            return got
        if kind and not entry.get("_ready_free"):
            seg = segment_on_air()
            if (isinstance(seg, dict) and str(seg.get("id") or "")
                    and _screenplay_road(str(seg.get("kind") or "")) == kind):
                return {"occurrence": str(seg.get("id") or ""),
                        "entry": str(seg.get("template") or ""),
                        "how": "on its entry",
                        "label": str(seg.get("label") or "")[:80],
                        "kind": str(seg.get("kind") or "")[:40],
                        "start": seg.get("start"),
                        "label_from": "segment on air"}
        banked = str(entry.get("system2_slot") or "")
        if banked:
            return _screenplay_slot_named({
                "occurrence": banked, "entry": banked.rsplit(":", 1)[-1],
                "how": "banked"})
        if entry.get("_ready_free"):
            why = "a rescue round, aired free of the running order"
        elif kind and kind not in SCREENPLAY_ENTRY_ROADS:
            why = "no entry on the running order runs this road"
        else:
            why = ("not reserved, not shelved in a window, not banked for an "
                   "entry, and the entry on air runs another road")
        return {"how": "none", "why": why}
    except Exception as exc:  # noqa: BLE001
        return {"how": "none", "why": "the link could not be read: %r" % (exc,)}


def screenplay_slot_label(slot: Any) -> Any:
    """Sync, for a thread: name an occurrence the plan in memory no longer
    holds - System2's own store (the slot as it was planned), else the
    running order's entry of that id. Never raises."""
    if (not isinstance(slot, dict) or not slot.get("occurrence")
            or slot.get("label")):
        return slot
    occ = str(slot.get("occurrence") or "")
    try:
        runtime = globals().get("_system2")
        live = runtime() if runtime else None
        path = getattr(getattr(live, "store", None), "path", None)
        if path and ":" in occ:
            import sqlite3
            db = sqlite3.connect("file:%s?mode=ro" % (path,), uri=True,
                                 timeout=2)
            try:
                got = db.execute("SELECT body FROM s2_slots WHERE id=?",
                                 (occ,)).fetchone()
            finally:
                db.close()
            if got:
                body = json.loads(got[0])
                slot["label"] = " ".join(str(body.get("label") or "").split())[:80]
                slot["kind"] = str(body.get("kind") or "")[:40]
                slot["preset"] = str(body.get("preset") or "")[:60]
                slot["start"] = body.get("start")
                slot["label_from"] = "system2 store"
                return slot
    except Exception:  # noqa: BLE001
        pass
    try:
        sheet = schedule_public() or {}
        for row in (sheet.get("slots") or []):
            if (isinstance(row, dict) and str(slot.get("entry") or "")
                    and str(row.get("id") or "") == str(slot.get("entry"))):
                slot["label"] = " ".join(str(row.get("label") or "").split())[:80]
                slot["kind"] = str(row.get("kind") or "")[:40]
                slot["preset"] = str(sheet.get("active") or "")[:60]
                slot["label_from"] = "running order"
                break
    except Exception:  # noqa: BLE001
        pass
    return slot


def screenplay_scene_slot(rnd: Any, round_kind: str, at: float,
                          open_round: Any = None) -> dict[str, Any]:
    """What a scene heading says about its entry: {"slot": {label, id,
    entry, how}} when its round names one, {"slot": {"none": True, why}}
    when its round is known to have none, and {} when the round is not
    written down (older than the stamp) - unknown is never shown as none."""
    slot = rnd.get("slot") if isinstance(rnd, dict) else None
    if not isinstance(slot, dict) or not slot:
        if isinstance(rnd, dict) and rnd:
            slot = None                  # a row older than the stamp
        elif (isinstance(open_round, dict)
              and isinstance(open_round.get("slot"), dict)
              and float(at or 0) >= float(open_round.get("at") or 0) - 1.0
              and _screenplay_road(round_kind)
              == _screenplay_road(str(open_round.get("kind") or ""))):
            slot = open_round.get("slot")     # the round on air right now
    if isinstance(slot, dict) and slot:
        if slot.get("label"):
            return {"slot": {"label": str(slot.get("label") or "")[:80],
                             "id": str(slot.get("occurrence") or ""),
                             "entry": str(slot.get("entry") or ""),
                             "how": str(slot.get("how") or "")}}
        if str(slot.get("how") or "") == "none":
            return {"slot": {"none": True,
                             "why": str(slot.get("why") or "")[:200]}}
        return {}
    if round_kind and _screenplay_road(round_kind) not in SCREENPLAY_ENTRY_ROADS:
        return {"slot": {"none": True,
                         "why": "no entry on the running order runs this road"}}
    return {}


'''

OPEN_OLD = '''        return {"at": time.time(),
                "had": {str(r.get("id") or "")
                        for r in (_RADIO.get("chat") or [])}}
'''
OPEN_NEW = '''        # [seg-names] the entry it fills, read while the entry still says
        _slot = screenplay_round_slot(entry)
        _now = time.time()
        _SCREENPLAY_STATE["open"] = {
            "at": _now, "slot": _slot,
            "kind": str(entry.get("prep_kind") or "")}
        return {"at": _now, "slot": _slot,
                "had": {str(r.get("id") or "")
                        for r in (_RADIO.get("chat") or [])}}
'''

ROW_OLD = '''        "profile": str(entry.get("profile") or "")[:60],
    }
'''
ROW_NEW = '''        "profile": str(entry.get("profile") or "")[:60],
        # [seg-names] the running-order entry it filled, or why none
        "slot": dict((mark or {}).get("slot") or {"how": "none",
                                                  "why": "no mark"}),
    }
'''

WRITE_OLD = '''        airlog_jsonl_append(SCREENPLAY_ROUNDS_PATH, row)
'''
WRITE_NEW = '''        row["slot"] = screenplay_slot_label(row.get("slot"))  # [seg-names]
        airlog_jsonl_append(SCREENPLAY_ROUNDS_PATH, row)
        _open = _SCREENPLAY_STATE.get("open") or {}              # [seg-names]
        if abs(float(_open.get("at") or 0) - float(row.get("at") or 0)) < 0.01:
            _SCREENPLAY_STATE["open"] = {}   # its row speaks for it now
'''

DISK_OLD = '''        d["rounds"] = screenplay_rounds_read(since, until)
'''
DISK_NEW = '''        d["rounds"] = screenplay_rounds_read(since, until)
        d["open_round"] = dict(_SCREENPLAY_STATE.get("open") or {})  # [seg-names]
'''

SCENE_OLD = '''            push("scene", slug,
                 f"sc-{_scene_key}", at=at,
                 round=round_kind, seg=seg_now[0])
'''
SCENE_NEW = '''            push("scene", slug,
                 f"sc-{_scene_key}", at=at,
                 round=round_kind, seg=seg_now[0],
                 **screenplay_scene_slot(rnd, round_kind, at,        # [seg-names]
                                         d.get("open_round")))
'''

INSERT_BEFORE = "def screenplay_round_open(entry: dict[str, Any]) -> dict[str, Any]:\n"

EDITS = [
    ("round_open", OPEN_OLD, OPEN_NEW),
    ("round_row", ROW_OLD, ROW_NEW),
    ("round_write", WRITE_OLD, WRITE_NEW),
    ("screenplay_disk", DISK_OLD, DISK_NEW),
    ("scene_push", SCENE_OLD, SCENE_NEW),
]


def load(path):
    raw = open(path, "rb").read().decode("utf-8")
    crlf = "\r\n" in raw
    return raw.replace("\r\n", "\n"), crlf


def state(text):
    """(applied, missing) - per edit, by its NEW text / OLD text."""
    applied, missing = [], []
    if "def screenplay_round_slot(" in text:
        applied.append("helpers")
    elif text.count(INSERT_BEFORE) != 1:
        missing.append("helpers (anchor %r x%d)" % (INSERT_BEFORE.strip(),
                                                    text.count(INSERT_BEFORE)))
    for name, old, new in EDITS:
        if new in text:
            applied.append(name)
        elif text.count(old) != 1:
            missing.append("%s (anchor x%d)" % (name, text.count(old)))
    return applied, missing


def main(argv):
    mode = argv[1] if len(argv) > 1 else "--check"
    path = argv[2] if len(argv) > 2 else "app.py"
    text, crlf = load(path)
    applied, missing = state(text)
    total = len(EDITS) + 1
    if mode == "--check":
        if len(applied) == total:
            print("APPLIED", path)
            return 2
        if missing:
            print("MISSING", path, "; ".join(missing))
            return 1
        print("READY", path, "(%d of %d already in)" % (len(applied), total))
        return 0
    if mode != "--apply":
        print(__doc__)
        return 1
    if len(applied) == total:
        print("already applied", path)
        return 0
    if missing:
        print("MISSING", path, "; ".join(missing))
        return 1
    if "helpers" not in applied:
        text = text.replace(INSERT_BEFORE, HELPERS + INSERT_BEFORE, 1)
    for name, old, new in EDITS:
        if name not in applied:
            assert text.count(old) == 1, name
            text = text.replace(old, new, 1)
    ast.parse(text)
    applied, missing = state(text)
    assert len(applied) == total and not missing, (applied, missing)
    out = text.replace("\n", "\r\n") if crlf else text
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)))
    with os.fdopen(fd, "wb") as fh:
        fh.write(out.encode("utf-8"))
    try:
        os.chmod(tmp, os.stat(path).st_mode & 0o777)
    except OSError:
        pass
    os.replace(tmp, path)
    print("applied", MARK, path, "crlf" if crlf else "lf")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

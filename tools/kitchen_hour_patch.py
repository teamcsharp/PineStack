#!/usr/bin/env python3
"""[kitchen-hour] One kitchen under the hour (wave H, 2026-10-06).

System 2's prepare jobs stand down under engine system3; the kitchen's board gains the upcoming Book Time and
supercut windows' unvoiced parts as needs (cost = chunks left x 10 s, deadline = the window's start minus 60 s,
ordered nearest deadline first, a part with no takes first); a window's part is made by the segment runtime's own
voicing pass under the task's own room (cost + 15 s); the writer lanes dial admits a second writer lane only while
every condition holds (kitchen_hour.writer_lanes), and /api/cupboard shows the lanes it holds.

Edits:
  app.py                        import, the kitchen_second_lane setting, the board's window needs, the window pass in
                                prep_one, the lanes dial at the request book, /api/cupboard.
  dynamic_segments_runtime.py   install exports the voicing pass and the supercut pass to the kitchen.
  system2_runtime.py            stood_down(): System 2's prepare loop and prepare spawn idle under system3.
  dynamic_segments_system2.py   claim, prepare_job, writer tickets idle under system3.
  kitchen_hour.py               NEW FILE: the pure rules (window needs, merge, writer lanes).

Usage:  kitchen_hour_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        kitchen_hour_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

NEW_FILES = {
    "kitchen_hour.py": '"""[kitchen-hour] One kitchen under the hour (wave H, 2026-10-06).\n\nThe rules the kitchen\'s board and the writer lanes follow, kept apart from app.py so they read on their own and\ncan be tested with a fake sheet and fake windows. app.py gathers the facts (the upcoming windows, a window\'s\nunvoiced parts, the box\'s readings) and acts on the answers. Nothing here touches a store, a model, a file or a\nclock it was not handed.\n\nWindow needs. Every upcoming Book Time or supercut window that still has a part not ready to air is one need on\nthe board:\n  kind      the window\'s prep road (banter for both windows today)\n  why       "Book Time at HH:MM needs its <phase> part voiced (N chunks left)"\n  cost      chunks_left * the seconds per chunk (10 s by default)\n  deadline  the window\'s start minus 60 s\nNeeds run nearest deadline first. Within one window a part with no takes at all comes first, then the book\'s own\norder (opening, discussion, closing).\n\nWriter lanes. A second writer lane is admitted only when every condition holds: the ceiling allows it (the env\nOLLAMA_LANES), the engine is system3 or kitchen.second_lane is on, no H3 or ComfyUI render is in flight, the box\nis under its render ceiling, and the pantry is short of its horizon or a window is within twenty minutes.\n"""\nfrom __future__ import annotations\n\nimport time\nfrom typing import Any, Callable, Iterable\n\nWINDOW_KINDS = ("book_time", "sfx_supercut")\nCHUNK_SECONDS = 10.0             # seconds per unvoiced chunk when nothing better is measured\nDEADLINE_LEAD_SECONDS = 60.0     # a window\'s deadline is its start minus this\nURGENT_SECONDS = 1200.0          # a window this close outranks every need that has no deadline\nLANE_CEILING = 2                 # the most writer lanes this dial ever opens\nPHASE_ORDER = {"opening": 0, "clip": 0, "discussion": 1, "closing": 2}\n\n\ndef window_kind(row: Any) -> str:\n    """The window\'s own kind (book_time or sfx_supercut), or "" when the row is not a window."""\n    if not isinstance(row, dict):\n        return ""\n    slot = row.get("slot") if isinstance(row.get("slot"), dict) else {}\n    for value in (row.get("kind"), row.get("dynamic_kind"), slot.get("dynamic_kind"),\n                  slot.get("dynamic_template"), slot.get("kind")):\n        if str(value or "") in WINDOW_KINDS:\n            return str(value)\n    return ""\n\n\ndef window_start(row: dict, now: float) -> float:\n    """When the window takes the air: its due moment, or now plus its starts_in."""\n    at = float(row.get("due_at") or 0)\n    if at > 0:\n        return at\n    return float(now) + float(row.get("starts_in") or 0)\n\n\ndef clock(at: float) -> str:\n    return time.strftime("%H:%M", time.localtime(float(at)))\n\n\ndef window_need_why(kind: str, at: float, phase: str, chunks: int) -> str:\n    if kind == "sfx_supercut":\n        return "Supercut at %s needs its clip made (%d chunks left)" % (clock(at), chunks)\n    return ("Book Time at %s needs its %s part voiced (%d chunks left)"\n            % (clock(at), phase, chunks))\n\n\ndef window_needs(rows: Iterable[dict], parts_of: Callable[[dict], Iterable[dict]], *,\n                 now: float | None = None, chunk_seconds: float = CHUNK_SECONDS) -> list[dict[str, Any]]:\n    """One need per window part that is not ready to air, nearest deadline first.\n\n    rows      the upcoming rows (coord_upcoming shape: kind or slot.dynamic_kind, road, slot_id, occurrence,\n              due_at or starts_in).\n    parts_of  row -> the parts still owed a voice: {"id", "phase", "chunks_left", "takes"}. A part with no\n              chunks left is not owed and is skipped here as well.\n    """\n    now = time.time() if now is None else float(now)\n    chunk = float(chunk_seconds)\n    out: list[dict[str, Any]] = []\n    for row in rows or []:\n        kind = window_kind(row)\n        if not kind:\n            continue\n        at = window_start(row, now)\n        road = str(row.get("road") or "banter")\n        for part in list(parts_of(row) or []):\n            chunks = int(part.get("chunks_left") or 0)\n            if chunks <= 0:\n                continue\n            phase = str(part.get("phase") or "discussion")\n            takes = int(part.get("takes") or 0)\n            why = window_need_why(kind, at, phase, chunks)\n            out.append({\n                "prep": road, "kind": road, "face": "the window", "verdict": "window",\n                "why": why, "window": dict(row), "window_kind": kind,\n                "part": str(part.get("id") or phase), "phase": phase, "takes": takes,\n                "chunks": chunks, "short": chunks, "each": chunk,\n                "cost": round(chunks * chunk, 1),\n                "deadline": round(at - DEADLINE_LEAD_SECONDS, 3),\n                "starts_in": round(at - now, 1), "at": round(at, 3),\n                "slot_id": str(row.get("slot_id") or ""),\n                "occurrence": str(row.get("occurrence") or ""),\n            })\n    out.sort(key=lambda n: (n["deadline"], 0 if n["takes"] == 0 else 1,\n                            PHASE_ORDER.get(n["phase"], 3), n["at"]))\n    return out\n\n\ndef merge_needs(needs: list[dict], window_items: list[dict]) -> list[dict]:\n    """Window needs placed against the board\'s own needs by time to the leg.\n\n    A window within URGENT_SECONDS goes ahead of every need (its deadline is nearer than any quota\'s).\n    A window further out goes after the board\'s needs, so the quota-only needs keep their order until the\n    window is close. Both groups keep the nearest-deadline order they arrived in.\n    """\n    urgent = [n for n in window_items if float(n.get("starts_in") or 0) <= URGENT_SECONDS]\n    later = [n for n in window_items if float(n.get("starts_in") or 0) > URGENT_SECONDS]\n    return urgent + list(needs or []) + later\n\n\ndef window_due_soon(window_items: Iterable[dict]) -> bool:\n    return any(float(n.get("starts_in") or 0) <= URGENT_SECONDS for n in window_items or [])\n\n\ndef writer_lanes(facts: dict[str, Any]) -> tuple[int, str]:\n    """(lanes, why): 1 unless every condition holds, then 2 (never past the ceiling)."""\n    ceiling = max(1, int(facts.get("ceiling") or 1))\n    if ceiling < 2:\n        return 1, "OLLAMA_LANES is one, and that is the ceiling"\n    if not (facts.get("system3") or facts.get("second_lane")):\n        return 1, "the engine is not system3 and kitchen.second_lane is off"\n    if facts.get("render_in_flight"):\n        return 1, "an H3 or ComfyUI render is in flight"\n    hot = facts.get("hot_c")\n    limit = facts.get("hot_ceiling_c")\n    if hot is None or limit is None:\n        return 1, "the box\'s thermal reading is missing"\n    if float(hot) >= float(limit):\n        return 1, "the box is at %.0f C, at or over its %.0f C ceiling" % (float(hot), float(limit))\n    short = bool(facts.get("pantry_short"))\n    soon = bool(facts.get("window_soon"))\n    if not (short or soon):\n        return 1, "the pantry is at its horizon and no window is within twenty minutes"\n    reasons = []\n    if short:\n        reasons.append("the pantry holds %d s of %d s" % (int(facts.get("pantry_seconds") or 0),\n                                                       int(facts.get("target_seconds") or 0)))\n    if soon:\n        reasons.append("a window is within twenty minutes")\n    return min(LANE_CEILING, ceiling), ("; ".join(reasons) + "; no render in flight and the box at %.0f C"\n                                       % float(hot))\n\n\ndef lane_admits(held: int, lanes: int) -> bool:\n    """May one more ask take a lane, given how many of this model\'s asks already hold one?"""\n    return int(held) < max(1, int(lanes))\n',
}

APP_BLOCK = r'''# --- [kitchen-hour] ONE KITCHEN UNDER THE HOUR (wave H, 2026-10-06) -----------------
# The board's needs gain the dynamic windows' unvoiced parts (the rules are in kitchen_hour.py). A window's part is
# made by the segment runtime's own voicing pass under the task's own room. The writer lanes dial lets a second
# writer lane in only while the box can take it. Measured before this: a Book Time part stood at 3 of 10 takes for
# an hour while the board owed other roads first.
KITCHEN_WINDOW_MEMO_SECONDS = 5.0
_KITCHEN_WINDOWS: dict[str, Any] = {"at": 0.0, "needs": []}
KITCHEN_LANE_MEMO_SECONDS = 5.0
_KITCHEN_LANES: dict[str, Any] = {"at": 0.0, "lanes": 1, "why": "", "facts": {}}


def _kitchen_window_parts(runtime: Any, row: dict[str, Any]) -> list[dict[str, Any]]:
    """A window's parts that are not ready to air, as the segment runtime reads them: a Book Time part is one of
    its book rows (chunks not yet taken); a supercut is one clip, owed until one is held on the shelf."""
    kind = kitchen_hour.window_kind(row)
    if kind == "sfx_supercut":
        occurrence = str(row.get("occurrence") or "")
        held = any(isinstance(item, dict) and str(item.get("dynamic_occurrence") or "") == occurrence
                   for item in list(_SHELF.get("sfx_supercut") or []))
        return [] if held else [{"id": "clip", "phase": "clip", "chunks_left": 1, "takes": 0}]
    if kind != "book_time" or runtime is None:
        return []
    parts = []
    for held in list(runtime.unvoiced_parts(row) or []):
        entry = runtime.source_entry(held)
        takes = list(entry.get("takes") or [])
        chunks = max(1, int(entry.get("chunks") or 0) - len(takes))
        parts.append({"id": str(entry.get("sid") or ""), "phase": str(entry.get("book_phase") or "discussion"),
                      "chunks_left": chunks, "takes": len(takes)})
    return parts


def kitchen_window_needs() -> list[dict[str, Any]]:
    """The upcoming windows' unvoiced parts as board needs, nearest deadline first (kitchen_hour.window_needs).
    Read over the coordinator's own horizon and memoised for five seconds, as the board itself is."""
    # [kitchen-gate] the window needs wait for the System 3 switch: under System 2 the board takes none
    _s2 = globals().get("_system2")
    if callable(_s2) and not _s2().stood_down():
        return []
    now = time.time()
    if now - float(_KITCHEN_WINDOWS.get("at") or 0) < KITCHEN_WINDOW_MEMO_SECONDS:
        return [dict(one) for one in _KITCHEN_WINDOWS.get("needs") or []]
    needs: list[dict[str, Any]] = []
    try:
        runtime = globals().get("DYNAMIC_SEGMENTS_RUNTIME")
        if runtime is not None:
            rows = [row for row in coord_upcoming(coord_ahead_seconds(), measure=False)
                    if not row.get("cannot") and kitchen_hour.window_kind(row)]
            needs = kitchen_hour.window_needs(
                rows, lambda row: _kitchen_window_parts(runtime, row), now=now,
                chunk_seconds=kitchen_hour.CHUNK_SECONDS)
    except Exception:  # noqa: BLE001
        needs = []                      # a window that cannot be read owes the board nothing
    _KITCHEN_WINDOWS.update(at=now, needs=needs)
    return [dict(one) for one in needs]


def kitchen_window_roads() -> set[str]:
    """The prep roads a window need is waiting on (banter for both windows today)."""
    try:
        return {str(one.get("prep") or "") for one in kitchen_window_needs()} - {""}
    except Exception:  # noqa: BLE001
        return set()


async def kitchen_window_pass(need: dict[str, Any]) -> bool:
    """The board picked a window's part for its road: the segment runtime makes it (the voicing pass for a Book
    Time part, its clip for a supercut) under the task's own room - the part's cost plus fifteen seconds, the way
    the recovery road holds its room."""
    row = dict(need.get("window") or {})
    run = globals().get("dynamic_segment_prepare_supercut" if kitchen_hour.window_kind(row) == "sfx_supercut"
                        else "dynamic_segment_prepare_pass")
    if not callable(run):
        return False
    prep_note(str(need.get("prep") or "banter"), "voicing the window: " + str(need.get("why") or "")[:160])
    scope = _PREP_TASK_DEADLINE.set(time.time() + float(need.get("cost") or 0) + 15.0)
    try:
        return bool(await run(row))
    except Exception as exc:  # noqa: BLE001
        pipeline_log("lookahead", ("the window's part fell over: " + type(exc).__name__ + ": " + str(exc))[:200])
        return False
    finally:
        _PREP_TASK_DEADLINE.reset(scope)


def kitchen_lane_facts() -> dict[str, Any]:
    """The readings the writer lanes dial takes, each read the way its owner reads it."""
    facts: dict[str, Any] = {"ceiling": int(OLLAMA_LANES)}
    engine = ""
    try:
        runtime = globals().get("_system2")
        engine = str((runtime().config or {}).get("engine") or "") if callable(runtime) else ""
    except Exception:  # noqa: BLE001
        engine = ""
    facts["system3"] = engine == "system3"
    try:
        facts["second_lane"] = bool(dj_settings().get("kitchen_second_lane", True))
    except Exception:  # noqa: BLE001
        facts["second_lane"] = True
    try:
        render = bool(_parody_stinger_queue().active())     # an H3 stinger that is working
    except Exception:  # noqa: BLE001
        render = True
    comfy = dict(_RESOURCE_STATE.get("comfy") or {})
    fresh = time.time() - float(_RESOURCE_STATE.get("at") or 0) < 120.0
    if not fresh or not comfy.get("observed") or comfy.get("busy"):
        render = True                    # ComfyUI busy, or unknown: no second lane on a guess
    facts["render_in_flight"] = render
    facts["hot_c"] = box_hottest_c()                         # the same reading the H3 governor refuses on
    facts["hot_ceiling_c"] = RENDER_TEMP_CEILING_C
    try:
        facts["pantry_seconds"] = round(float(pantry_seconds()), 1)
        facts["target_seconds"] = round(float(prepare_target_seconds()), 1)
    except Exception:  # noqa: BLE001
        facts["pantry_seconds"], facts["target_seconds"] = 0.0, 0.0
    facts["pantry_short"] = bool(facts["target_seconds"] > 0 and facts["pantry_seconds"] < facts["target_seconds"])
    facts["window_soon"] = kitchen_hour.window_due_soon(kitchen_window_needs())
    return facts


def writer_lanes() -> int:
    """How many writer lanes the request book admits now: one, or two when kitchen_hour.writer_lanes finds every
    condition true (never past OLLAMA_LANES). Memoised for five seconds; a change is logged once, when it happens."""
    now = time.time()
    if now - float(_KITCHEN_LANES.get("at") or 0) < KITCHEN_LANE_MEMO_SECONDS:
        return int(_KITCHEN_LANES.get("lanes") or 1)
    try:
        facts = kitchen_lane_facts()
        lanes, why = kitchen_hour.writer_lanes(facts)
    except Exception as exc:  # noqa: BLE001
        facts, lanes, why = {}, 1, "the lane readings failed: " + type(exc).__name__
    before = int(_KITCHEN_LANES.get("lanes") or 1)
    _KITCHEN_LANES.update(at=now, facts=facts, why=why, lanes=int(lanes))
    if int(lanes) != before:
        try:
            pipeline_log("lookahead", ("the kitchen opens a second writer lane: " + why) if int(lanes) > 1
                         else ("back to one lane: " + why))
        except Exception:  # noqa: BLE001
            pass
    return int(lanes)


def kitchen_lanes_state() -> dict[str, Any]:
    """The lanes the kitchen holds right now, for /api/cupboard."""
    lanes = writer_lanes()
    return {"lanes": lanes, "ceiling": int(OLLAMA_LANES), "why": str(_KITCHEN_LANES.get("why") or ""),
            "facts": dict(_KITCHEN_LANES.get("facts") or {}), "window_needs": len(kitchen_window_needs())}


async def kitchen_lane_enter(model: str, identity: str) -> None:
    """THE WRITER LANES DIAL, at the request book. An ask waits here while this model already holds as many lanes
    as writer_lanes() admits. The flag it sets is what the others count; call_ollama's finally takes the job row,
    and the flag with it, when the ask ends. Check and flag share one synchronous step, so two asks cannot both
    take the last lane."""
    while True:
        job = _OLLAMA_JOBS.get(identity)
        if job is None:
            return
        held = sum(1 for row in list(_OLLAMA_JOBS.values())
                   if row.get("model") == model and row.get("lane_held"))
        if kitchen_hour.lane_admits(held, writer_lanes()):
            job["lane_held"] = True
            return
        await asyncio.sleep(0.25)


'''

APP_PREP_ONE_BODY_OLD = r'''    _PREP_ROAD_ACTIVE[kind] = time.time()
    try:
        return await _prep_one_work(kind)
    finally:
        _PREP_ROAD_ACTIVE.pop(kind, None)
'''

APP_PREP_ONE_BODY_NEW = r'''    _PREP_ROAD_ACTIVE[kind] = time.time()
    try:
        # [kitchen-hour] the board picked a window's part for this road: the part is made, not a new round
        _win = _PREP_LAST.get("window_need") if _PREP_LAST.get("kind") == kind else None
        if _win:
            _PREP_LAST.pop("window_need", None)
            return await kitchen_window_pass(dict(_win))
        return await _prep_one_work(kind)
    finally:
        _PREP_ROAD_ACTIVE.pop(kind, None)
'''

APP_ASKED_OLD = r'''            _asked.append((_need, _slot_row))
            if float(_slot_row["cost"]) > room:
                continue
            _SLOT_STARVED[0] = 0
            out.update({
                "kind": _slot_row["kind"], "forced": True,
                "slot": _need["why"],
                "why": (_need["why"] + f" - building {_slot_row['label']}"
                        f" at about {int(_slot_row['cost'])}s against "
                        f"{int(room)}s of window (#1050)")})
            return out
'''

APP_ASKED_NEW = r'''            _asked.append((_need, _slot_row))
            # [kitchen-hour] a window's part is priced by its own chunks, not the road's average
            _cost = float(_need["cost"]) if _need.get("window") else float(_slot_row["cost"])
            if _cost > room:
                continue
            _SLOT_STARVED[0] = 0
            out.update({
                "kind": _slot_row["kind"], "forced": True,
                "slot": _need["why"],
                "window_need": (dict(_need) if _need.get("window") else None),   # [kitchen-hour]
                "why": (_need["why"] + f" - building {_slot_row['label']}"
                        f" at about {int(_cost)}s against "
                        f"{int(room)}s of window (#1050)")})
            return out
'''

APP_STARVED_OLD = r'''                out.update({
                    "kind": _slot_row["kind"], "forced": True,
                    "slot": _need["why"],
                    "why": (_need["why"] + " - the desk has asked "
'''

APP_STARVED_NEW = r'''                out.update({
                    "kind": _slot_row["kind"], "forced": True,
                    "slot": _need["why"],
                    "window_need": (dict(_need) if _need.get("window") else None),   # [kitchen-hour]
                    "why": (_need["why"] + " - the desk has asked "
'''

SYSTEM2_ENABLED_OLD = r'''    @property
    def enabled(self):
        return self.config.get("engine") == "system2"
'''

SYSTEM2_ENABLED_NEW = r'''    @property
    def enabled(self):
        return self.config.get("engine") == "system2"

    def stood_down(self):
        """[kitchen-hour] Under engine system3 the hour director owns the air and the kitchen: System 2's prepare
        jobs, writer tickets and spawns idle here, and its store stays readable."""
        return str(self.config.get("engine") or "") == "system3"
'''

EDITS = {
    "app.py": [
        ("the kitchen's module is imported", "import comfy_workshop\n",
         "import comfy_workshop\nimport kitchen_hour  # [kitchen-hour] the window needs and the writer lanes' rules\n", 1),
        ("the kitchen_second_lane setting is a default (on)",
         '    "cupboard_unheard_every": 420,\n',
         '    "cupboard_unheard_every": 420,\n'
         '    # [kitchen-hour] THE SECOND WRITER LANE. Off, a second lane is admitted only when engine system3 is on;\n'
         '    # on, it is also admitted when no render is in flight, the box is cool and the pantry is short.\n'
         '    "kitchen_second_lane": True,\n', 1),
        ("the kitchen_second_lane setting is read",
         '        "cupboard_unheard_every": max(60, min(7200, int(\n'
         '            raw_dj.get("cupboard_unheard_every",\n'
         '                       DEFAULT_DJ["cupboard_unheard_every"]) or 60))),\n',
         '        "cupboard_unheard_every": max(60, min(7200, int(\n'
         '            raw_dj.get("cupboard_unheard_every",\n'
         '                       DEFAULT_DJ["cupboard_unheard_every"]) or 60))),\n'
         '        "kitchen_second_lane": bool(raw_dj.get(\n'
         '            "kitchen_second_lane", DEFAULT_DJ["kitchen_second_lane"])),\n', 1),
        ("the kitchen block and its helpers (before prep_one)",
         "async def prep_one(kind: str) -> bool:\n",
         APP_BLOCK + "async def prep_one(kind: str) -> bool:\n", 1),
        ("the board's needs gain the windows' unvoiced parts",
         '        _SLOT_WANT.update({"at": time.time(), "needs": out,\n',
         '        # [kitchen-hour] THE WINDOWS\' UNVOICED PARTS ARE NEEDS TOO: a Book Time or supercut window inside the\n'
         '        # coordinator\'s horizon that still has a part not ready to air, placed by time to the leg\n'
         '        try:\n'
         '            out = kitchen_hour.merge_needs(out, kitchen_window_needs())\n'
         '        except Exception:  # noqa: BLE001\n'
         '            pass\n'
         '        _SLOT_WANT.update({"at": time.time(), "needs": out,\n', 1),
        ("the board keeps the window's road on the board",
         '        for kind in order:\n            if kind in skip:\n                _off[kind] = "already tried this pass"\n                continue\n',
         '        # [kitchen-hour] the roads a window part is waiting on stay on the board whatever the ledger says\n'
         '        _window_roads = kitchen_window_roads()\n'
         '        for kind in order:\n            if kind in skip:\n                _off[kind] = "already tried this pass"\n                continue\n', 1),
        ("a window road is owed a script",
         '                if kind in _short_now:\n                    _needs_script = True        # #1131: the hour says so\n',
         '                if kind in _short_now:\n                    _needs_script = True        # #1131: the hour says so\n'
         '                if kind in _window_roads:\n'
         '                    _needs_script = True        # [kitchen-hour] a window part is owed a voice\n', 1),
        ("a window road is not dropped as prerecorded",
         '                if _said == "prerecord":\n                    continue\n',
         '                if _said == "prerecord" and kind not in _window_roads:\n                    continue\n', 1),
        ("a window need is priced by its chunks and carried to prep_one",
         APP_ASKED_OLD, APP_ASKED_NEW, 1),
        ("the starvation escape carries a window need too", APP_STARVED_OLD, APP_STARVED_NEW, 1),
        ("prep_one makes a window's part under the task's room",
         APP_PREP_ONE_BODY_OLD, APP_PREP_ONE_BODY_NEW, 1),
        ("the writer lanes dial at the request book",
         "        async with _ollama_lane(model), _OLLAMA_GATE, \\\n                httpx.AsyncClient(timeout=180) as client:\n",
         "        await kitchen_lane_enter(model, identity)     # [kitchen-hour] the writer lanes dial\n"
         "        async with _ollama_lane(model), _OLLAMA_GATE, \\\n                httpx.AsyncClient(timeout=180) as client:\n", 1),
        ("/api/cupboard shows the lanes it holds",
         "    require_read_auth(authorization)\n    return cupboard_state()\n",
         "    require_read_auth(authorization)\n"
         "    return {**cupboard_state(), \"writer_lanes\": kitchen_lanes_state()}   # [kitchen-hour]\n", 1),
    ],
    "dynamic_segments_runtime.py": [
        ("install exports the window passes to the kitchen",
         "    g['dynamic_segment_window_owned'] = runtime.window_owned          # [book-nodes-4] the cupboard's doors ask it\n",
         "    g['dynamic_segment_window_owned'] = runtime.window_owned          # [book-nodes-4] the cupboard's doors ask it\n"
         "    g['dynamic_segment_prepare_pass'] = runtime.prepare_book          # [kitchen-hour] a window's voicing pass\n"
         "    g['dynamic_segment_prepare_supercut'] = runtime.prepare_supercut  # [kitchen-hour] a supercut's clip\n", 1),
    ],
    "system2_runtime.py": [
        ("System 2 knows it stands down under system3", SYSTEM2_ENABLED_OLD, SYSTEM2_ENABLED_NEW, 1),
        ("System 2's prepare loop idles under system3",
         '        if not self.enabled or self._prepare_lock.locked() or not self._rooms_open():   # [kitchen]\n            return\n',
         '        if self.stood_down() or not self.enabled or self._prepare_lock.locked() or not self._rooms_open():   # [kitchen]\n            return\n', 1),
        ("System 2's prepare spawn idles under system3",
         '        if not self.enabled or self._prepare_lock.locked():\n            return None\n',
         '        if self.stood_down() or not self.enabled or self._prepare_lock.locked():\n            return None\n', 1),
    ],
    "dynamic_segments_system2.py": [
        ("System 2's window claims idle under system3",
         "    async def claim(self, kinds, lookahead):\n",
         "    async def claim(self, kinds, lookahead):\n"
         "        if self.runtime.stood_down():\n"
         "            return None   # [kitchen-hour] System 3 owns the kitchen\n", 1),
        ("System 2's window jobs idle under system3",
         "    async def prepare_job(self, job):\n        rt, h = self.runtime, self.runtime.host\n",
         "    async def prepare_job(self, job):\n"
         "        if self.runtime.stood_down():\n"
         "            return None   # [kitchen-hour]\n"
         "        rt, h = self.runtime, self.runtime.host\n", 1),
        ("System 2 takes no writer ticket under system3",
         "    async def wait_for_book_writer(self, job, work, *, wait_seconds=30.0):\n",
         "    async def wait_for_book_writer(self, job, work, *, wait_seconds=30.0):\n"
         "        if self.runtime.stood_down():\n"
         "            return False   # [kitchen-hour] no ticket under System 3\n", 1),
        ("an open writer ticket ends under system3",
         "        if (not self.runtime.enabled or now >= ticket['expires_at']",
         "        if (not self.runtime.enabled or self.runtime.stood_down() or now >= ticket['expires_at']", 1),
    ],
}


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        if not path.exists():
            print("%-78s MISSING FILE" % name)
            missing = True
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, want in edits:
            if text.count(new) >= want:
                print("%-78s applied" % label[:78])
                continue
            n = text.count(old)
            if n == want:
                print("%-78s ready" % label[:78])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-78s MISSING (anchor count %d, wanted %d)" % (label[:78], n, want))
                missing = True
        if changed:
            plans.append((path, text, mode, bom))
    for name, body in NEW_FILES.items():
        path = root / name
        if path.exists():
            current = path.read_bytes().decode("utf-8")
            if current == body:
                print("%-78s applied" % ("new file " + name))
            else:
                print("%-78s MISSING (a different %s is already there)" % ("new file " + name, name))
                missing = True
        else:
            print("%-78s ready" % ("new file " + name))
            ready = True
            plans.append((path, body, "lf", False))
    if missing:
        print("anchors missing - nothing applied")
        return 1
    if not ready:
        print("every edit reads applied")
        return 2
    if argv[1] == "--check":
        print("ready to apply")
        return 0
    for path, text, mode, bom in plans:
        out = text.replace("\n", "\r\n") if mode == "crlf" else text
        data = out.encode("utf-8")
        if bom:
            data = b"\xef\xbb\xbf" + data
        tmp = path.with_suffix(path.suffix + ".kitchenhour.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

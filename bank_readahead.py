"""bank_readahead - the read-ahead ledger and the production queue.  [#1184/#1246]

WHAT THE OPERATOR ASKED (#1246): "i dont know why these lines arent recorded
and played in advance ... The point of a script is to read and execute every
line."  And (#1184): "Why are the DJs not playing right now?"

WHAT THIS MODULE IS.  Two things the station could not say before:

  1. THE READ-AHEAD, per line.  For every entry the running order commits in
     the next N minutes (commitment_inventory_plan binds concrete stock to
     those entries), every line of the stock bound to it, and whether that
     line is RENDERED (its clip is on the pantry shelf), WRITTEN only (text,
     no audio yet), LIVE by design (a caller's phone line is drawn at air
     time), or MISSING (nothing written at all).  `bank_state()` is the view;
     `GET /api/bank` serves it.  The headline number is
     `rendered_ahead_seconds` - finished audio bound to the coming hour -
     which is the figure to plot over time.

  2. THE PRODUCTION QUEUE.  `script_production_round` (app.py) freezes a
     prepared round, assembles it from the pantry clips it already has and
     measures a cue map (`body_frames`) - the unit the sequencer will require
     before it hands a block to the page.  Until now it ran only at the
     instant a round finished preparing, paced to one round per
     `every=180` seconds, and stood down whenever `prep_should_stop()` said
     the engine was busy - so of 985 rounds in its ledger only 16 were made
     with the switch at `on`, and every round banked before the switch was
     flipped will never be produced.  `production_queue()` lists, in AIR
     order, the ready rounds that still lack a measured cue map;
     `production_pass()` produces the head of it, URGENTLY (no pacing) when
     its entry is due inside the hour and paced beyond that; `bank_producer()`
     is the standing task that keeps doing so, on air and paused alike.
     Production renders nothing - the segmented road consumes the pantry
     files the station already made (script_production.py, "nothing here
     renders") - so the queue costs ffmpeg and disk, never the voice engine.

EVERY FUNCTION TAKES `app` - the app.py module - and reads its globals by
name at call time.  Nothing here imports app.py, so this can be tested with
a stub namespace, and app.py imports this lazily inside a try so a missing
or broken copy of it can never take the station off the air.

The pantry check is the PLANNER-FAST one (`key in app._PANTRY`), the same
predicate dialogue_stock_items._audio uses: `_pantry_key_ready` stats the
file, and the stall hunter has caught that walk on the loop
(`_pantry_file_present` <- pantry_get <- hour_needs, 5.4 s).  Playback keeps
the strict disk check; a ledger read many times a minute must not.
"""
from __future__ import annotations

import asyncio
import math
import time
from typing import Any

import segment_contract as segment_contracts

BANK_MEMO_S = 10.0            # the view is re-walked at most this often
PRODUCE_EVERY_S = 15.0        # the standing task's look interval
PRODUCE_REST_S = 1800.0       # a round the producer REFUSED rests this long
URGENT_WINDOW_S = 3600.0      # due inside this: produce now, no pacing
QUEUE_MOST = 40               # how many queue rows the view carries
LOG_MOST = 24                 # how many productions the view remembers

_MEMO: dict[str, Any] = {"at": 0.0, "minutes": 0, "value": None}
_REFUSED: dict[str, dict[str, Any]] = {}     # sid -> {"at", "why", "code"}
_LOG: list[dict[str, Any]] = []              # the last productions, newest last
_CONTRACTS: dict[str, dict[str, Any]] = {}   # commit id -> current scheduled obligation

STATE_RENDERED = "rendered"
STATE_WRITTEN = "written"
STATE_LIVE = "live"
STATE_MISSING = "missing"


# ---------------------------------------------------------------- lines

def _int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _float(value: Any, fallback: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return fallback
    return out if out == out else fallback


def _pantry_has(app: Any, key: str) -> bool:
    """Planner-fast: is this clip on the shelf?  No disk."""
    try:
        return bool(key) and key in app._PANTRY
    except Exception:  # noqa: BLE001
        return False


def _sid_of(app: Any, kind: str, row: Any, entry: Any) -> str:
    for source in (entry, row):
        if not isinstance(source, dict):
            continue
        for key in ("sid", "id", "round_id", "shelf_id"):
            got = str(source.get(key) or "")
            if got:
                return got
    try:
        return str(app.alt_sid(str(kind), row) or "")
    except Exception:  # noqa: BLE001
        return ""


def line_states(app: Any, kind: str, row: Any) -> list[dict[str, Any]]:
    """Every line of one stock row, each with its state.

    A single read (an advert, a station ID) is one line.  A round lists its
    takes in SCRIPT order (`i` is the script index larder_prepare stamped),
    then any line the plan still owes, then the caller's lines that are
    drawn live by design (`missing_voice_chunks`).  A round with no takes
    yet is read straight off its script."""
    out: list[dict[str, Any]] = []
    if not isinstance(row, dict):
        return out
    if kind == "track_talk":
        for part, who in (("intro", "dj"), ("outro", "cohost")):
            side = row.get(part)
            side = side if isinstance(side, dict) else {}
            written = bool(str(side.get("text") or "").strip())
            try:
                ready = bool(app.track_talk_part_ready(side))
            except Exception:  # noqa: BLE001
                ready = written and _pantry_has(app, str(side.get("key") or ""))
            out.append({"part": part, "who": who,
                        "text": str(side.get("text") or "")[:120],
                        "key": str(side.get("key") or ""),
                        "state": (STATE_RENDERED if ready else
                                  STATE_WRITTEN if written else STATE_MISSING),
                        "seconds": round(_float(side.get("seconds")), 1)
                                   if ready else 0.0})
        return out
    try:
        entry = app.dialogue_entry(row)
    except Exception:  # noqa: BLE001
        entry = None
    if entry is None:
        key = str(row.get("key") or "")
        text = str(row.get("text_plain") or row.get("text") or "")
        try:
            ready = bool(app.dialogue_audio_ready(kind, row))
        except Exception:  # noqa: BLE001
            ready = _pantry_has(app, key)
        state = (STATE_RENDERED if ready
                 else STATE_WRITTEN if text.strip() else STATE_MISSING)
        out.append({"who": str(row.get("who") or "dj"), "text": text[:120],
                    "key": key, "state": state,
                    "seconds": round(_float(row.get("seconds")), 1) if ready else 0.0})
        return out
    takes = [t for t in (entry.get("takes") or []) if isinstance(t, dict)]
    takes.sort(key=lambda t: _int(t.get("i"), 999))
    for take in takes:
        key = str(take.get("key") or "")
        ready = _pantry_has(app, key)
        out.append({"who": str(take.get("who") or ""),
                    "text": str(take.get("text") or "")[:120],
                    "key": key,
                    "state": STATE_RENDERED if ready else STATE_WRITTEN,
                    "seconds": round(_float(take.get("seconds")), 1) if ready else 0.0})
    if not takes:
        script = str(entry.get("script_plain") or entry.get("script") or "")
        turns: list[Any] = []
        try:
            turns = list(app.banter_turns(
                script, str(entry.get("caller_name") or ""),
                str(entry.get("caller2_name") or "")))
        except Exception:  # noqa: BLE001
            turns = []
        for marker, text in turns:
            text = str(text or "")
            out.append({"who": str(marker or ""), "text": text[:120], "key": "",
                        "state": STATE_WRITTEN if text.strip() else STATE_MISSING,
                        "seconds": 0.0})
        if not turns:
            out.append({"who": "", "text": "", "key": "",
                        "state": STATE_MISSING, "seconds": 0.0})
            return out
    # Lines the plan owes that no take has been made for yet.
    want = _int(entry.get("chunks"))
    live = _int(entry.get("missing_voice_chunks"))
    owed = max(0, want - live - len(takes)) if takes else 0
    for _ in range(owed):
        out.append({"who": "", "text": "(not yet recorded)", "key": "",
                    "state": STATE_WRITTEN, "seconds": 0.0})
    for _ in range(live):
        out.append({"who": "caller", "text": "(the phone line is drawn at air time)",
                    "key": "", "state": STATE_LIVE, "seconds": 0.0})
    return out


def _cue_map_measured(app: Any, entry: Any) -> bool:
    try:
        return bool(app.production_cue_map(entry))
    except Exception:  # noqa: BLE001
        got = dict((entry or {}).get("cue_map") or {}) if isinstance(entry, dict) else {}
        return bool(got.get("cues")) and str(got.get("derivation") or "") == "measured"


def _round_entry(app: Any, row: Any) -> dict[str, Any] | None:
    """Return only a real conversation entry, never a stock-row fallback.

    The commitment inventory deliberately exposes ``entry`` as
    ``dialogue_entry(row) or row`` so every kind has one inspectable payload.
    That is useful to the ledger, but it is not a type discriminator: a
    produced advert is a ready single read, not a dialogue round that needs a
    measured multi-line cue map.  Re-ask the station's canonical classifier
    at the production boundary.
    """
    try:
        got = app.dialogue_entry(row)
    except Exception:  # noqa: BLE001
        return None
    return got if isinstance(got, dict) else None


def item_view(app: Any, kind: str, item: dict[str, Any],
              public: dict[str, Any] | None = None) -> dict[str, Any]:
    """One bound stock item: its lines, its counts, its production state."""
    row = item.get("row")
    entry = _round_entry(app, row)
    lines = line_states(app, kind, row if isinstance(row, dict) else (entry or {}))
    counts = {STATE_RENDERED: 0, STATE_WRITTEN: 0, STATE_LIVE: 0, STATE_MISSING: 0}
    rendered_seconds = 0.0
    for line in lines:
        counts[line["state"]] = counts.get(line["state"], 0) + 1
        if line["state"] == STATE_RENDERED:
            rendered_seconds += _float(line.get("seconds"))
    is_round = isinstance(entry, dict)
    produced = _cue_map_measured(app, entry) if is_round else False
    production = dict((entry or {}).get("production") or {}) if is_round else {}
    ready = bool(item.get("ready"))
    if produced:
        state = "produced"
    elif ready or (lines and counts[STATE_WRITTEN] == 0 and counts[STATE_MISSING] == 0):
        state = STATE_RENDERED
    elif counts[STATE_MISSING] and (counts[STATE_RENDERED] or counts[STATE_WRITTEN]):
        state = "partial"
    elif counts[STATE_RENDERED] or counts[STATE_WRITTEN]:
        state = STATE_WRITTEN if counts[STATE_WRITTEN] else STATE_RENDERED
    else:
        state = STATE_MISSING
    public = public or {}
    sid = _sid_of(app, kind, row, entry)
    refused = _REFUSED.get(sid) or {}
    return {
        "id": str(item.get("id") or public.get("id") or ""),
        "sid": sid, "kind": str(kind or ""),
        "ready": ready, "state": state, "round": is_round,
        "produced": produced,
        "production_why": ("" if produced else str(
            production.get("why") or refused.get("why") or "")),
        "seconds": round(_float(item.get("seconds")), 1),
        "audio_seconds": round(_float(item.get("audio_seconds")
                                      if item.get("audio_seconds") is not None
                                      else item.get("seconds")), 1),
        "allocated_seconds": round(_float(public.get("allocated_seconds")), 1),
        "ready_seconds": round(_float(public.get("ready_seconds")), 1),
        "rendered_seconds": round(rendered_seconds, 1),
        "counts": counts, "lines": lines,
        "head": (lines[0]["text"] if lines else ""),
    }


def _contract_supply(app: Any, kind: str, item: dict[str, Any],
                     public: dict[str, Any]) -> dict[str, Any]:
    """Measure one assigned item without treating a forecast as finished audio."""
    row = item.get("row")
    entry = _round_entry(app, row)
    source = entry or (row if isinstance(row, dict) else {})
    allocated = max(0.0, _float(public.get("allocated_seconds")))
    playable = min(allocated, max(0.0, _float(public.get("ready_seconds"))))
    if kind == "track_talk":
        bookends: dict[str, dict[str, bool]] = {}
        roles: list[str] = []
        scripted = recorded = 0.0
        for part, who in (("intro", "dj"), ("outro", "cohost")):
            side = source.get(part)
            side = side if isinstance(side, dict) else {}
            written = bool(str(side.get("text") or "").strip())
            try:
                ready = bool(app.track_talk_part_ready(side))
            except Exception:  # noqa: BLE001
                ready = written and _pantry_has(app, str(side.get("key") or ""))
            bookends[part] = {"written": written, "recorded": ready}
            if written:
                roles.append(who)
                scripted += segment_contracts.estimated_speech_seconds(side.get("text"))
            if ready:
                recorded += max(0.0, _float(side.get("seconds")))
        turns = len(roles)
        return {"scripted_seconds": round(scripted, 3),
                "recorded_seconds": round(recorded, 3),
                "playable_seconds": playable, "turns": turns,
                "events": turns, "roles": roles, "bookends": bookends}
    script = str(source.get("script") or source.get("script_plain")
                 or source.get("text_plain") or source.get("text") or "")
    turns: list[Any] = []
    if entry is not None:
        try:
            turns = list(app.banter_turns(script, str(entry.get("caller_name") or ""),
                                          str(entry.get("caller2_name") or "")))
        except Exception:  # noqa: BLE001
            turns = []
    roles = [segment_contracts.normalize_role(marker)
             for marker, said in turns if str(said or "").strip()]
    if not turns and script.strip():
        turns = [(str(source.get("who") or "dj"), script)]
        roles = [segment_contracts.normalize_role(turns[0][0])]
    production = (entry or {}).get("production") or {}
    supply = production.get("supply") if isinstance(production, dict) else None
    if (bool(item.get("ready")) and isinstance(supply, dict)
            and supply.get("measured") and _cue_map_measured(app, entry)):
        return {"scripted_seconds": round(min(allocated,
                    max(0.0, _float(supply.get("scripted_seconds")))), 3),
                "recorded_seconds": round(min(allocated,
                    max(0.0, _float(supply.get("recorded_seconds")))), 3),
                "playable_seconds": round(min(playable,
                    max(0.0, _float(supply.get("playable_seconds")))), 3),
                "turns": max(0, _int(supply.get("turns"))),
                "events": max(0, _int(supply.get("events"))),
                "roles": list(supply.get("roles") or [])}
    recorded = sum(max(0.0, _float(take.get("seconds")))
                   for take in (entry or {}).get("takes", [])
                   if isinstance(take, dict) and _pantry_has(app, str(take.get("key") or "")))
    if entry is None or (item.get("ready") and not (entry.get("takes") or [])):
        recorded = playable
    return {"scripted_seconds": round(min(allocated,
                    segment_contracts.estimated_speech_seconds(script)), 3),
            "recorded_seconds": round(min(allocated, recorded), 3),
            "playable_seconds": playable,
            "turns": len(turns), "events": len(turns), "roles": roles}


def contract_write_needed(kind: str, max_age: float = 30.0) -> bool:
    """A recent bank walk found authored or measured airtime debt."""
    now = time.time()
    return any(str(row.get("road") or "") == kind
               and now - _float(row.get("at")) <= max_age
               and (_float((row.get("coverage") or {}).get("script_short_seconds")) > 1.0
                    and _float((row.get("coverage") or {}).get("playable_seconds"))
                        < _float((row.get("coverage") or {}).get("target_seconds")) - 1.0
                    or _float((row.get("coverage") or {}).get("writing_structure_short_seconds")) > 1.0
                    or (_float(row.get("speech_seconds")) > 0.0
                        and _float(row.get("ready_seconds")) >= _float(row.get("owns_seconds")) - 1.0
                        and _float((row.get("coverage") or {}).get("duration_short_seconds")) > 1.0))
               and _float(row.get("starts_in")) > 0.0
               for row in list(_CONTRACTS.values()))


# ---------------------------------------------------------------- the view

def _plan(app: Any, minutes: int) -> dict[str, Any]:
    hours = max(0.25, min(24.0, float(minutes) / 60.0))
    try:
        return dict(app.commitment_inventory_plan(hours) or {})
    except Exception:  # noqa: BLE001
        return {}


def bank_state(app: Any, minutes: int = 60) -> dict[str, Any]:
    """The next `minutes` of committed material, line by line.  Memoised."""
    minutes = max(5, min(360, int(minutes or 60)))
    now = time.time()
    if (_MEMO["value"] is not None and _MEMO["minutes"] == minutes
            and now - float(_MEMO["at"]) < BANK_MEMO_S):
        return dict(_MEMO["value"])
    got = _bank_state_fresh(app, minutes, now)
    _MEMO.update({"at": time.time(), "minutes": minutes, "value": got})
    return dict(got)


def _bank_state_fresh(app: Any, minutes: int, now: float) -> dict[str, Any]:
    global _CONTRACTS
    window = float(minutes) * 60.0
    plan = _plan(app, minutes)
    selected = {str(item.get("id") or ""): item
                for item in (plan.get("selected") or []) if isinstance(item, dict)}
    slots_out: list[dict[str, Any]] = []
    contracts: dict[str, dict[str, Any]] = {}
    totals = {"rendered_seconds": 0.0, "written_only_seconds": 0.0,
              "missing_seconds": 0.0, "live_lines": 0,
              "lines": {STATE_RENDERED: 0, STATE_WRITTEN: 0,
                        STATE_LIVE: 0, STATE_MISSING: 0},
              "items": 0, "rounds": 0, "produced_rounds": 0,
              "unproduced_rounds": 0, "entries": 0, "entries_bare": 0}
    for slot in plan.get("slots") or []:
        if not isinstance(slot, dict):
            continue
        starts = _float(slot.get("in_seconds"))
        if starts > window:
            continue
        kind = str(slot.get("road") or slot.get("kind") or "")
        items: list[dict[str, Any]] = []
        supplies: list[dict[str, Any]] = []
        for public in slot.get("stock") or []:
            if not isinstance(public, dict):
                continue
            item = selected.get(str(public.get("id") or ""))
            if item is None:
                continue
            view = item_view(app, kind, item, public)
            items.append(view)
            supplies.append(_contract_supply(app, kind, item, public))
            totals["items"] += 1
            for state, n in view["counts"].items():
                totals["lines"][state] = totals["lines"].get(state, 0) + n
            totals["live_lines"] += view["counts"].get(STATE_LIVE, 0)
            if view["round"]:
                totals["rounds"] += 1
                if view["produced"]:
                    totals["produced_rounds"] += 1
                else:
                    totals["unproduced_rounds"] += 1
        owns = _float(slot.get("owns_seconds"))
        ready = _float(slot.get("ready_seconds"))
        planned = _float(slot.get("planned_seconds"))
        short = _float(slot.get("short_seconds"), max(0.0, owns - planned))
        contract = segment_contracts.build_segment_contract(slot, now=now)
        coverage = segment_contracts.evaluate_segment_contract(contract, supplies)
        tasks = segment_contracts.preparation_tasks(contract, coverage)
        commit_id = str(slot.get("commit_id") or "")
        if commit_id:
            contracts[commit_id] = {"at": now, "road": kind,
                                    "starts_in": starts, "coverage": coverage,
                                    "ready_seconds": ready, "owns_seconds": owns,
                                    "speech_seconds": contract["speech_seconds"]}
        totals["rendered_seconds"] += ready
        totals["written_only_seconds"] += max(0.0, planned - ready)
        totals["missing_seconds"] += short
        totals["entries"] += 1
        if not items:
            totals["entries_bare"] += 1
        slots_out.append({
            "sequence": _int(slot.get("sequence")),
            "commit_id": str(slot.get("commit_id") or ""),
            "kind": str(slot.get("kind") or ""), "road": kind,
            "label": str(slot.get("label") or kind),
            "in_seconds": round(starts, 1), "current": bool(slot.get("current")),
            "owns_seconds": round(owns, 1), "ready_seconds": round(ready, 1),
            "written_only_seconds": round(max(0.0, planned - ready), 1),
            "short_seconds": round(short, 1),
            "contract": contract, "coverage": coverage, "tasks": tasks,
            "state": ("rendered" if short <= 1.0 and planned - ready <= 1.0 and items
                      else "written" if items and short <= 1.0
                      else "partial" if items else "missing"),
            "items": items,
        })
    for key in ("rendered_seconds", "written_only_seconds", "missing_seconds"):
        totals[key] = round(totals[key], 1)
    _CONTRACTS = contracts
    queue = production_queue(app, minutes=max(minutes, 60), plan=plan)
    say = ("%d min of finished audio is bound to the next %d min (%d min written "
           "only, %d min with nothing behind it); %d of %d bound rounds carry a "
           "measured cue map, %d await production"
           % (int(totals["rendered_seconds"] // 60), minutes,
              int(totals["written_only_seconds"] // 60),
              int(totals["missing_seconds"] // 60),
              totals["produced_rounds"], totals["rounds"], len(queue)))
    return {
        "at": now, "minutes": minutes, "available": True,
        "rendered_ahead_seconds": totals["rendered_seconds"],
        "written_only_seconds": totals["written_only_seconds"],
        "missing_seconds": totals["missing_seconds"],
        "owed_seconds": round(_float(plan.get("owed_seconds")), 1),
        "plan_say": str(plan.get("say") or ""),
        "totals": totals, "slots": slots_out,
        "production": {
            "queue": _public_queue(queue[:QUEUE_MOST]), "queued": len(queue),
            "log": list(_LOG)[-LOG_MOST:],
            "refused": {sid: dict(v) for sid, v in list(_REFUSED.items())[-QUEUE_MOST:]},
            "task": dict(getattr(app, "_BANK_PRODUCER", {}) or {}),
        },
        "say": say,
    }


# ---------------------------------------------------------------- the queue

def _production_settings(app: Any) -> Any:
    try:
        producer = app.script_producer()
        return producer.settings() if producer is not None else None
    except Exception:  # noqa: BLE001
        return None


def production_queue(app: Any, minutes: int = 60,
                     plan: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Ready rounds bound to the horizon that lack a measured cue map, in
    AIR order.  Each row says why it is still waiting when it is."""
    now = time.time()
    plan = plan if isinstance(plan, dict) else _plan(app, minutes)
    selected = {str(item.get("id") or ""): item
                for item in (plan.get("selected") or []) if isinstance(item, dict)}
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for slot in plan.get("slots") or []:
        if not isinstance(slot, dict):
            continue
        kind = str(slot.get("road") or slot.get("kind") or "")
        starts = _float(slot.get("in_seconds"))
        for public in slot.get("stock") or []:
            if not isinstance(public, dict):
                continue
            pid = str(public.get("id") or "")
            item = selected.get(pid)
            if item is None or pid in seen:
                continue
            seen.add(pid)
            row = item.get("row")
            entry = _round_entry(app, row)
            if entry is None:
                continue                      # a single read has no round
            if not item.get("ready"):
                continue                      # not finished: nothing to produce
            if _cue_map_measured(app, entry):
                continue
            sid = _sid_of(app, kind, row, entry)
            why = ""
            rest = _REFUSED.get(sid) or {}
            if rest and now - _float(rest.get("at")) < PRODUCE_REST_S:
                why = "refused %ds ago: %s" % (int(now - _float(rest.get("at"))),
                                              str(rest.get("why") or "")[:160])
            elif entry.get("preparing") or entry.get("tinting"):
                why = "the recording room is still on it"
            out.append({"id": pid, "sid": sid, "kind": kind,
                        "label": str(slot.get("label") or kind),
                        "in_seconds": round(starts, 1),
                        "urgent": starts <= URGENT_WINDOW_S,
                        "lines": len([t for t in (entry.get("takes") or [])
                                      if isinstance(t, dict)]),
                        "seconds": round(_float(item.get("seconds")), 1),
                        "why_waiting": why,
                        "_row": row, "_entry": entry})
    out.sort(key=lambda r: (_float(r.get("in_seconds")), r.get("id") or ""))
    return out


def _public_queue(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in r.items() if not str(k).startswith("_")}
            for r in rows]


async def production_pass(app: Any, urgent_window_s: float = URGENT_WINDOW_S,
                          minutes: int = 360, force: bool = False) -> dict[str, Any]:
    """Produce the head of the queue.  One round, then return.

    URGENT (its entry is due inside `urgent_window_s`) bypasses the
    producer's own pacing; anything further out keeps `every=`.  `force`
    (the console rung) treats the head as urgent whatever its distance."""
    now = time.time()
    settings = _production_settings(app)
    if settings is None:
        return {"ran": False, "why": "the producer is not installed"}
    if getattr(settings, "off", True):
        return {"ran": False, "why": "script production is off (%s)"
                % str(getattr(settings, "text", "") or "off")}
    rows = production_queue(app, minutes=minutes)
    if force:
        # A forced pass is the operator saying "try it anyway": the
        # refusal rest is a pacing device, not a verdict, and a rung that
        # answers "it is resting" to a button press is not a rung.
        for sid in [str(r.get("sid") or "") for r in rows]:
            _REFUSED.pop(sid, None)
        rows = [r for r in rows
                if "the recording room is still on it" not in str(r.get("why_waiting") or "")]
    else:
        rows = [r for r in rows if not r.get("why_waiting")]
    if not rows:
        return {"ran": False, "why": "nothing awaits production",
                "queued": 0}
    head = rows[0]
    urgent = bool(force or head.get("urgent")
                  or _float(head.get("in_seconds")) <= float(urgent_window_s))
    producer = app.script_producer()
    if producer is None:
        return {"ran": False, "why": "the producer is unusable"}
    if not urgent:
        try:
            if not producer.due(settings):
                wait = float(getattr(settings, "every_s", 180.0)) - (
                    now - float(getattr(producer, "_last_at", 0.0) or 0.0))
                return {"ran": False, "queued": len(rows),
                        "why": "paced: the next round is %ds off and the dial "
                               "allows one every %ds (%ds to go)"
                               % (int(_float(head.get("in_seconds"))),
                                  int(getattr(settings, "every_s", 180.0)),
                                  int(max(0.0, wait)))}
        except Exception:  # noqa: BLE001
            pass
    entry = head["_entry"]
    sid = str(head.get("sid") or "")
    session: dict[str, str] = {}
    try:
        got = app.session_voices()
        if asyncio.iscoroutine(got):
            got = await got
        session = {str(k): str(v) for k, v in dict(got or {}).items()}
    except Exception:  # noqa: BLE001
        session = {}
    plan, voices, line_plan, why = _rebuild_plan(app, entry, session)
    if why:
        _REFUSED[sid] = {"at": now, "why": why, "code": "plan_unbuildable"}
        _remember(sid, head, False, why, 0.0)
        return {"ran": True, "ok": False, "sid": sid, "why": why,
                "queued": len(rows) - 1}
    started = time.time()
    try:
        await app.script_production_round(entry, plan, voices, line_plan,
                                          urgent=urgent)
    except TypeError:
        # An app.py without the `urgent` keyword: the paced road, unchanged.
        await app.script_production_round(entry, plan, voices, line_plan)
    except Exception as exc:  # noqa: BLE001
        why = "production raised %s" % type(exc).__name__
        _REFUSED[sid] = {"at": now, "why": why, "code": "production_error"}
        _remember(sid, head, False, why, time.time() - started)
        return {"ran": True, "ok": False, "sid": sid, "why": why}
    cost = time.time() - started
    made = _cue_map_measured(app, entry)
    production = dict(entry.get("production") or {})
    if made:
        _REFUSED.pop(sid, None)
        _remember(sid, head, True, "", cost)
        return {"ran": True, "ok": True, "sid": sid, "cost_s": round(cost, 1),
                "urgent": urgent, "queued": len(rows) - 1,
                "assembly_id": str(production.get("assembly_id") or "")}
    why = str(production.get("why") or "the producer returned no measured cue map")
    code = str(production.get("refusal") or "")
    if code == "production_busy" or cost < 0.05 and not production:
        # Somebody else had the producer, or it declined to start (paced /
        # relief).  Not a refusal of THIS round: try again next pass.
        _remember(sid, head, False, why or "the producer was busy", cost)
        return {"ran": True, "ok": False, "sid": sid, "why": why or "busy",
                "retry": True}
    _REFUSED[sid] = {"at": now, "why": why, "code": code}
    _remember(sid, head, False, why, cost)
    return {"ran": True, "ok": False, "sid": sid, "why": why, "code": code,
            "cost_s": round(cost, 1), "queued": len(rows) - 1}


def _rebuild_plan(app: Any, entry: dict[str, Any],
                  session: dict[str, str] | None = None
                  ) -> tuple[Any, Any, Any, str]:
    """The (plan, voices, line_plan) larder_prepare handed the producer,
    rebuilt for a round that finished before the switch was on.

    `session` is the cast the CALLER already awaited out of
    `app.session_voices()` - this function is sync and must never try to
    await it itself (that was a TypeError at the only call site).

    The voices are the ones the TAKES were recorded in - the pantry is
    content-addressed by (text, voice, engine), so a cast that has changed
    since would make every line a miss and the producer refuses a round it
    cannot find the audio for."""
    try:
        script = str(entry.get("script") or entry.get("script_plain") or "")
        caller_name = str(entry.get("caller_name") or "")
        caller2_name = str(entry.get("caller2_name") or "")
        turns = list(app.banter_turns(script, caller_name, caller2_name))
        if not turns:
            return None, None, None, "the round's script has no turns to produce"
        voices: dict[str, str] = {}
        try:
            voices.update({str(k): str(v)
                           for k, v in dict(session or {}).items()})
        except Exception:  # noqa: BLE001
            pass
        for seat, key in (("caller", "caller_voice"), ("caller2", "caller2_voice"),
                          ("third", "third_voice")):
            value = str(entry.get(key) or "")
            if value:
                voices[seat] = value
        for take in (entry.get("takes") or []):
            if isinstance(take, dict) and take.get("who") and take.get("voice"):
                voices[str(take["who"])] = str(take["voice"])
        plan = list(app._round_chunks(turns, voices, caller_name))
        if not plan:
            return None, None, None, "the round's plan is empty - nothing the engine was asked for"
        line_plan = list(app.round_line_plan(turns, caller_name, voices))
        return plan, voices, line_plan, ""
    except Exception as exc:  # noqa: BLE001
        return None, None, None, "the plan could not be rebuilt: %s" % type(exc).__name__


def _remember(sid: str, head: dict[str, Any], ok: bool, why: str,
              cost: float) -> None:
    _LOG.append({"at": time.time(), "sid": sid, "id": str(head.get("id") or ""),
                 "kind": str(head.get("kind") or ""),
                 "in_seconds": _float(head.get("in_seconds")),
                 "ok": bool(ok), "why": str(why or "")[:200],
                 "cost_s": round(float(cost or 0.0), 1)})
    del _LOG[:-LOG_MOST]
    _MEMO["at"] = 0.0                 # the view changed


async def bank_producer(app: Any) -> None:
    """The standing task: produce ahead of the air, oldest-due first."""
    await asyncio.sleep(45)           # let a boot settle first
    # `while _RADIO["on"]` would have ENDED this task for good on a boot
    # with the station off - and the whole point of banking ahead is that
    # it happens while nothing is airing. It idles instead, and a paused
    # station is the best time of all to produce.
    while True:
        await asyncio.sleep(PRODUCE_EVERY_S)
        book = getattr(app, "_BANK_PRODUCER", None)
        try:
            try:
                if not app._RADIO.get("on"):
                    if isinstance(book, dict):
                        book.update(at=time.time(), last={
                            "ran": False, "why": "the station is off"})
                    continue
            except Exception:  # noqa: BLE001
                pass
            try:
                if app.prep_yielding():
                    if isinstance(book, dict):
                        book.update(at=time.time(), last={
                            "ran": False, "why": "the loop is wanted for the air (relief)"})
                    continue
            except Exception:  # noqa: BLE001
                pass
            got = await production_pass(app, URGENT_WINDOW_S)
            if isinstance(book, dict):
                book["at"] = time.time()
                book["last"] = got
                if got.get("ran"):
                    book["runs"] = int(book.get("runs") or 0) + 1
                    if got.get("ok"):
                        book["made"] = int(book.get("made") or 0) + 1
        except Exception as exc:  # noqa: BLE001
            if isinstance(book, dict):
                book["at"] = time.time()
                book["last"] = {"ran": False, "why": "the producer task raised %s"
                                % type(exc).__name__}


def queue_public(app: Any, minutes: int = 360) -> list[dict[str, Any]]:
    """The queue without its private row references - for a console line."""
    return _public_queue(production_queue(app, minutes=minutes))


# ------------------------------------------------- the sequencer's door

def round_body_frames(app: Any, entry: Any) -> tuple[float, int]:
    """(body_frames, cues) off a round's MEASURED cue map, or (0.0, 0).

    The pair `playout_sequencer.hold()` wants: a round that cannot answer
    with a positive `body_frames` is not held, it goes back on the making
    shelf with a reason, and nothing waits behind a file whose length
    nobody has measured."""
    try:
        got = app.production_cue_map(entry)
    except Exception:  # noqa: BLE001
        got = {}
    if not isinstance(got, dict) or not got.get("cues"):
        return 0.0, 0
    return _float(got.get("body_frames")), len(list(got.get("cues") or []))


async def ensure_produced(app: Any, entry: Any, why: str = "",
                          wait: bool = True) -> dict[str, Any]:
    """PRODUCE THIS ROUND NOW, and say whether its audio can be sequenced.

    THE FUNCTION THE SEQUENCER CALLS.  `playout_sequencer` may not hold a
    round until it can name `body_frames`; before this existed the only
    road to a measured cue map was the instant a round finished
    preparing, paced to one per `every=` seconds and stood down whenever
    the engine was busy - so 969 of the 991 rounds in the production
    ledger carry no map at all and could never be held.  Await this and
    the round is produced out of turn, ahead of its moment.

        got = await bank_readahead.ensure_produced(app, entry)
        seq.hold(key, audio_ready=got["ok"], body_frames=got["body_frames"],
                 cues=got["cues"], why_not_ready=got["why"], ...)

    Returns {ok, produced, body_frames, cues, why, cost_s}.  `ok` false is
    never an exception: a round the producer refuses is a round the
    sequencer must not hold, which is exactly what it needs to be told.
    Never raises."""
    out = {"ok": False, "produced": False, "body_frames": 0.0, "cues": 0,
           "why": "", "cost_s": 0.0}
    if not isinstance(entry, dict):
        out["why"] = "there is no round here to produce"
        return out
    frames, cues = round_body_frames(app, entry)
    if frames > 0.0:
        out.update(ok=True, produced=True, body_frames=frames, cues=cues)
        return out
    if not wait:
        out["why"] = "this round carries no measured cue map yet"
        return out
    started = time.time()
    try:
        session: dict[str, str] = {}
        try:
            got = app.session_voices()
            if asyncio.iscoroutine(got):
                got = await got
            session = {str(k): str(v) for k, v in dict(got or {}).items()}
        except Exception:  # noqa: BLE001
            session = {}
        plan, voices, line_plan, why_plan = _rebuild_plan(app, entry, session)
        if why_plan:
            out["why"] = why_plan
            return out
        try:
            await app.script_production_round(entry, plan, voices, line_plan,
                                              urgent=True)
        except TypeError:
            await app.script_production_round(entry, plan, voices, line_plan)
    except Exception as exc:  # noqa: BLE001
        out["why"] = "production raised %s" % type(exc).__name__
        out["cost_s"] = round(time.time() - started, 1)
        return out
    out["cost_s"] = round(time.time() - started, 1)
    frames, cues = round_body_frames(app, entry)
    if frames > 0.0:
        out.update(ok=True, produced=True, body_frames=frames, cues=cues)
        _MEMO["at"] = 0.0
        return out
    production = dict(entry.get("production") or {})
    out["why"] = (str(production.get("why") or "")
                  or "the producer returned no measured cue map"
                  ) + ((" (" + why + ")") if why else "")
    return out


def bank_say(app: Any, minutes: int = 60) -> str:
    """One line for a console rung."""
    try:
        return str(bank_state(app, minutes).get("say") or "")
    except Exception as exc:  # noqa: BLE001
        return "the bank could not be read (%s)" % type(exc).__name__

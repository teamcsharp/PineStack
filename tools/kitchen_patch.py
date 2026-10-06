#!/usr/bin/env python3
"""[kitchen] A stopped station keeps its kitchen open. 2026-10-06.

"Right now the station is offline. So during this time I want it banking up and
working through rolling rule and building up scripts and stacking the covers so
that the next time the broadcast comes up ... [it is not] having to rush and
create content."

Measured at 05:42 host time: the operator switched the station OFF (dj_stop), and
every one of the 34 show-owned worker rooms read `stopped` - the larder, the
pantry, the pen release, the tint repair, the ad studio, the SFX Guy's listener.
481 unheard rounds stood on the shelves, 37 gazette reviews and 11 mixtape rounds
were written but never recorded, and the hourly Gazette would not print. Every
banking bypass this station has built (#1108, #1121, #1131, #1134, #1155, #1261,
[bank-ahead], [call-prod], the parallel booths, the paused tint budget) reads
radio_paused() - the PAUSE - and the stop is a different switch.

The fix is on the road that owns the decision, not a wedge beside it:

  off_air()      paused OR the kitchen is open behind a stopped show; every
                 paused banking bypass asks this instead of radio_paused()
  rooms_open()   the show is on, or the kitchen is open - the loop condition of
                 every preparation room (the air rooms keep _RADIO["on"])
  kitchen_start  dj_stop opens it after radio_stop; a boot that finds the switch
                 off opens it too; dj_start's radio_stop closes it and the show's
                 own roster runs the same rooms
  kitchen_watch  hands the engines back (#1114, "OFF means OFF") once nothing is
                 left to bank for KITCHEN_IDLE_OFFLOAD_S, instead of at the switch

Also: the finishing rooms take every round-shaped shelf (ROUND_SHELF_KINDS adds
gazette_review and mixtape to manager/caller/gallery/news), the SFX listener does
not stand aside for the kitchen's own writing-room jobs, the Gazette prints its
hourly edition while the kitchen banks and gets two code-only desks for it (what
the roulette wrote, the SFX Guy's study), and System 2's preparation loop follows
the same two switches.

Usage:  kitchen_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        kitchen_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

# ----------------------------------------------------------------------------
# app.py
# ----------------------------------------------------------------------------

OFF_AIR_OLD = '''

def radio_pause_set(on: bool, why: str = "") -> bool:
'''

OFF_AIR_NEW = '''

def off_air() -> bool:
    """[kitchen] Is nobody listening - paused, or switched off with the kitchen open?

    Two switches take the station off the air: the pause (`_RADIO["paused"]`,
    the show still running underneath) and the stop (`_RADIO["on"]` false, the
    show over). Every banking bypass was written for the first - #1108, #1121,
    #1131, #1134, #1155, #1261, [bank-ahead], [call-prod] - and read
    radio_paused(), so an operator who switched the station OFF for the night
    got a kitchen that stood still. Measured 2026-10-06 05:42: every worker room
    `stopped` at the switch, 481 unheard rounds on the shelves, 37 gazette
    reviews and 11 mixtape rounds written but never recorded. The rooms ask this
    instead. The kitchen (not the bare switch) is the second condition so a
    station that was never started - every test, the first seconds of a boot -
    answers exactly as it always did."""
    try:
        return bool(radio_paused()) or kitchen_open()
    except Exception:  # noqa: BLE001
        return False


_KITCHEN: dict[str, Any] = {"on": False, "since": 0.0, "why": "",
                            "idle_since": 0.0, "offloaded": 0.0, "rooms": 0}

# [kitchen] the shelves whose rows are ROUNDS - written by dj_banter with a
# bank_to pile, finished by the recording rooms a line at a time. The ad and
# station_id shelves are reads with their own finishing road (prep_voice_pending).
ROUND_SHELF_KINDS = ("manager", "caller", "gallery", "news", "gazette_review", "mixtape")


def kitchen_open() -> bool:
    """[kitchen] Are the preparation rooms running behind a stopped show?"""
    try:
        return bool(_KITCHEN.get("on"))
    except Exception:  # noqa: BLE001
        return False


def rooms_open() -> bool:
    """[kitchen] May a preparation room keep its loop: the show is on, or the
    kitchen is open behind a stopped show. The air rooms keep _RADIO["on"]."""
    try:
        return bool(_RADIO.get("on")) or kitchen_open()
    except Exception:  # noqa: BLE001
        return False


def radio_pause_set(on: bool, why: str = "") -> bool:
'''

WORKER_SIG_OLD = '''async def _radio_worker(name: str, factory: Any, generation: int,
                        persistent: bool = True) -> None:
'''
WORKER_SIG_NEW = '''async def _radio_worker(name: str, factory: Any, generation: int,
                        persistent: bool = True, kitchen: bool = False) -> None:
'''

WORKER_LOOP_OLD = '''    row = _RADIO_WORKERS[name]
    while generation == _RADIO_RUN[0] and _RADIO.get("on"):
'''
WORKER_LOOP_NEW = '''    row = _RADIO_WORKERS[name]
    while generation == _RADIO_RUN[0] and (_RADIO.get("on") or kitchen):   # [kitchen]
'''

WORKER_EXIT_OLD = '''        if generation != _RADIO_RUN[0] or not _RADIO.get("on"):
            row["state"] = "stopped"
            return
'''
WORKER_EXIT_NEW = '''        if generation != _RADIO_RUN[0] or not (_RADIO.get("on") or kitchen):   # [kitchen]
            row["state"] = "stopped"
            return
'''

WORKER_START_OLD = '''def radio_worker_start(name: str, factory: Any, *,
                       persistent: bool = True) -> Any:
    """Launch and register one coroutine owned by the current show."""
    generation = int(_RADIO_RUN[0])
    _RADIO_WORKERS[name] = {
        "generation": generation, "state": "starting", "started": time.time(),
        "persistent": bool(persistent), "restarts": 0, "last_error": "",
        "last_exit": 0.0, "next_at": 0.0,
    }
    task = asyncio.create_task(
        _radio_worker(name, factory, generation, persistent),
        name=f"radio:{name}")
'''
WORKER_START_NEW = '''def radio_worker_start(name: str, factory: Any, *,
                       persistent: bool = True, kitchen: bool = False) -> Any:
    """Launch and register one coroutine owned by the current show - or, with
    `kitchen`, by the kitchen that stays open behind a stopped show."""
    generation = int(_RADIO_RUN[0])
    _RADIO_WORKERS[name] = {
        "generation": generation, "state": "starting", "started": time.time(),
        "persistent": bool(persistent), "restarts": 0, "last_error": "",
        "last_exit": 0.0, "next_at": 0.0, "kitchen": bool(kitchen),
    }
    task = asyncio.create_task(
        _radio_worker(name, factory, generation, persistent, kitchen),
        name=f"radio:{name}")
'''

CENSUS_OLD = '''    return {
        "generation": int(_RADIO_RUN[0]),
        "expected": len(live),
        "running": sum(row.get("state") == "running" for row in live),
        "degraded": sum(row.get("state") in ("failed", "restarting") for row in live),
        "workers": rows,
    }
'''
CENSUS_NEW = '''    return {
        "generation": int(_RADIO_RUN[0]),
        "expected": len(live),
        "running": sum(row.get("state") == "running" for row in live),
        "degraded": sum(row.get("state") in ("failed", "restarting") for row in live),
        "kitchen": bool((globals().get("_KITCHEN") or {}).get("on")),      # [kitchen]
        "kitchen_rooms": sum(1 for row in live if row.get("kitchen")),
        "workers": rows,
    }
'''

KITCHEN_BLOCK_OLD = '''    _RADIO_WORKERS[name]["task"] = task
    _RADIO_TASK.append(task)
    return task
VOICE_CLIP_FEED_KEEP = int(os.getenv("VOICE_CLIP_FEED_KEEP", "2000"))
'''
KITCHEN_BLOCK_NEW = '''    _RADIO_WORKERS[name]["task"] = task
    _RADIO_TASK.append(task)
    return task


# --- [kitchen] THE ROOMS THAT BUILD THE SHELVES ----------------------------
# Everything else on the roster is the show itself - the needle, the torrent,
# the watchdogs, the consumers, the clocks that AIR - and ends with it. These
# are the writer, the recording room, the pen, the tint repair, the ad studio,
# the disk allowance and the SFX Guy's study, and the operator's ask
# (2026-10-06) is that they keep working while the station is switched off:
# "banking up and working through rolling rule and building up scripts and
# stacking the covers so that the next time the broadcast comes up ... [it is
# not] having to rush and create content."
KITCHEN_IDLE_OFFLOAD_S = float(os.getenv("PINE_KITCHEN_IDLE_OFFLOAD_S", "900"))


def kitchen_roster() -> list[tuple[str, Any]]:
    """[kitchen] Name -> factory, the rooms the kitchen runs with the show off."""
    return [
        ("pantry", pantry_keeper),
        ("larder", larder_keeper),
        ("flow_release", flow_release_clock),
        ("tint_recovery", tint_recovery_clock),
        ("ad_studio", ad_studio_clock),
        ("sfx_speech", sfx_speech_clock),
        ("sfx_arrivals", sfx_arrivals_keeper),
        ("sfx_levels", sfx_levels_keeper),
        ("speakerbox_index", speakbox_index_clock),
        ("storage", storage_keeper),
        ("kitchen", kitchen_watch),
    ]


def kitchen_has_work() -> bool:
    """[kitchen] Is anything left to bank? Written rounds without their audio,
    roads the hours are short of, a larder under the pause floor, or the
    finished-audio target not yet met. Errs on the side of work."""
    try:
        if _pause_unfinished_rows():
            return True
        if hour_short_kinds():
            return True
        if float(prepared_seconds()) < float(prepare_work_target_seconds()):
            return True
        _floor = min(int(larder_cap()), int(gap_pause_bank_rounds(dj_settings())))
        if int(larder_stock_count()) < _floor:
            return True
    except Exception:  # noqa: BLE001
        return True
    return False


def kitchen_start(why: str = "") -> int:
    """[kitchen] Open the preparation rooms behind a stopped show. Idempotent: a
    kitchen already open, or a show that is on, is left as it is. radio_stop()
    closes it (dj_start's roster then runs the same rooms as the show's)."""
    if _RADIO.get("on") or kitchen_open():
        return 0
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return 0                        # no loop: nothing to run the rooms on
    # The shelves the rooms work. Every loader is idempotent (dj_start calls the
    # same set on every show start), and a kitchen that opened on a cold boot
    # without them would write a new larder OVER the banked one.
    for _load in (_larder_load, _dialogue_recovery_load, _pantry_load,
                  track_talk_load, track_talk_restore_queue, _box_hold_load,
                  render_backlog_load):
        try:
            _load()
        except Exception as exc:  # noqa: BLE001
            pipeline_log("drop", f"[kitchen] {getattr(_load, '__name__', 'a loader')} tripped: "
                                 f"{type(exc).__name__}: {exc}"[:200])
    _KITCHEN.update({"on": True, "since": time.time(), "why": str(why or ""),
                     "idle_since": 0.0, "offloaded": 0.0, "rooms": 0})
    started = 0
    for name, factory in kitchen_roster():
        try:
            radio_worker_start(name, factory, kitchen=True)
            started += 1
        except Exception as exc:  # noqa: BLE001
            pipeline_log("drop", f"[kitchen] {name} would not start: {type(exc).__name__}: {exc}"[:200])
    _KITCHEN["rooms"] = started
    if not started:
        _KITCHEN["on"] = False
        return 0
    try:
        pipeline_log(
            "lookahead",
            f"[kitchen] the station is off and the kitchen is open: {started} room(s) keep banking"
            + (f" - {why}" if why else ""),
            extra=("WHAT RUNS WITH THE SHOW OFF ([kitchen])\\n\\n"
                   + "\\n".join(n for n, _f in kitchen_roster())
                   + "\\n\\nEvery paused banking bypass (#1108/#1121/#1131/#1134/#1155/#1261/"
                     "[bank-ahead]/[call-prod]) reads off_air() now, so a stopped station banks "
                     "exactly as a paused one does. The air rooms stay down: nothing plays, "
                     "nothing is published. The engines are handed back (#1114) once the "
                     "kitchen has had nothing to do for %d minutes." % int(KITCHEN_IDLE_OFFLOAD_S // 60)))
    except Exception:  # noqa: BLE001
        pass
    return started


async def kitchen_watch() -> None:
    """[kitchen] Hands the engines back (#1114, OFF means OFF) once the kitchen
    has had nothing to bank for KITCHEN_IDLE_OFFLOAD_S. Work appearing again -
    a dial moved, a shelf aired down on the next show - reloads them on the
    first write, which is what a cold start costs."""
    while kitchen_open() and not _RADIO.get("on"):
        await asyncio.sleep(60)
        try:
            now = time.time()
            if kitchen_has_work():
                _KITCHEN["idle_since"] = 0.0
                _KITCHEN["offloaded"] = 0.0
                continue
            if not float(_KITCHEN.get("idle_since") or 0):
                _KITCHEN["idle_since"] = now
                continue
            if (now - float(_KITCHEN["idle_since"]) >= KITCHEN_IDLE_OFFLOAD_S
                    and not float(_KITCHEN.get("offloaded") or 0)):
                _KITCHEN["offloaded"] = now
                pipeline_log("lookahead",
                             "[kitchen] the shelves are full and the kitchen has been idle for "
                             "%d min - handing the engines back (#1114)" % int(KITCHEN_IDLE_OFFLOAD_S // 60))
                await _fm_off_offload()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            pipeline_log("drop", f"[kitchen] the watch tripped: {type(exc).__name__}: {exc}"[:200])


VOICE_CLIP_FEED_KEEP = int(os.getenv("VOICE_CLIP_FEED_KEEP", "2000"))
'''

RADIO_STOP_OLD = '''    _RADIO_RUN[0] += 1
    _stopped = time.time()
    for row in _RADIO_WORKERS.values():
'''
RADIO_STOP_NEW = '''    _RADIO_RUN[0] += 1
    try:
        _KITCHEN["on"] = False          # [kitchen] its rooms go with this generation
    except Exception:  # noqa: BLE001
        pass
    _stopped = time.time()
    for row in _RADIO_WORKERS.values():
'''

DJ_STOP_HEAD_OLD = '''def dj_stop(*, seal_episode: bool = True) -> None:
    _RADIO["on"] = False
    remember_radio(False)
    fire_and_forget(_fm_off_offload())
'''
DJ_STOP_HEAD_NEW = '''def dj_stop(*, seal_episode: bool = True) -> None:
    _RADIO["on"] = False
    remember_radio(False)
    # [kitchen] OFF means off AIR. #1114's hand-back of the engines waits until
    # nothing is left to bank (below, after the kitchen opens); kitchen_watch
    # does it once the shelves are full and quiet.
'''

DJ_STOP_TAIL_OLD = '''    dj_skip()
    radio_stop()
    _RADIO.update({"requests": [], "history": []})
'''
DJ_STOP_TAIL_NEW = '''    dj_skip()
    radio_stop()
    _RADIO.update({"requests": [], "history": []})
    try:
        kitchen_start("the show stopped")                       # [kitchen]
        if not kitchen_has_work():
            fire_and_forget(_fm_off_offload())
    except Exception:  # noqa: BLE001
        fire_and_forget(_fm_off_offload())
'''

RESUME_OLD = '''    try:
        want = json.loads(RADIO_ON_PATH.read_text())
    except Exception:
        return
    if not (isinstance(want, dict) and want.get("on")):
        return
    await asyncio.sleep(5)            # let the music index load first
'''
RESUME_NEW = '''    try:
        want = json.loads(RADIO_ON_PATH.read_text())
    except Exception:
        await asyncio.sleep(8)
        kitchen_start("the station boots with no switch written down")   # [kitchen]
        return
    if not (isinstance(want, dict) and want.get("on")):
        await asyncio.sleep(8)
        kitchen_start("the station boots switched off")                 # [kitchen]
        return
    await asyncio.sleep(5)            # let the music index load first
'''

PANTRY_GATE_OLD = '''            _PREP_DEADLINE[0] = 0.0
            if not _RADIO.get("on"):
                continue
            window = pantry_window()
'''
PANTRY_GATE_NEW = '''            _PREP_DEADLINE[0] = 0.0
            if not rooms_open():                                 # [kitchen]
                continue
            window = pantry_window()
'''

PANTRY_PIPER_OLD = '''            if radio_paused() and _hour_short:
                for _road in _hour_short[:2]:
'''
PANTRY_PIPER_NEW = '''            if off_air() and _hour_short:                        # [kitchen]
                for _road in _hour_short[:2]:
'''

PANTRY_FINISH_OLD = '''            _finish_all = bool(radio_paused() and _pause_unfinished_rows())
'''
PANTRY_FINISH_NEW = '''            _finish_all = bool(off_air() and _pause_unfinished_rows())   # [kitchen]
'''

PANTRY_ROUNDS_OLD = '''            _rounds = ("manager", "caller", "gallery", "news")
            _lead = [k for k in _hour_short if k in _rounds]
'''
PANTRY_ROUNDS_NEW = '''            _rounds = ROUND_SHELF_KINDS          # [kitchen] every round-shaped shelf
            _lead = [k for k in _hour_short if k in _rounds]
'''

PANTRY_SLICE_OLD = '''            if radio_paused():
                _slice = max(_slice, 120.0)
'''
PANTRY_SLICE_NEW = '''            if off_air():                                        # [kitchen]
                _slice = max(_slice, 120.0)
'''

PANTRY_BANTER_WAIT_OLD = '''            _banter_wait = (bool(_hour_short) and not radio_paused()
'''
PANTRY_BANTER_WAIT_NEW = '''            _banter_wait = (bool(_hour_short) and not off_air()   # [kitchen]
'''

LARDER_LOOP_OLD = '''    while _RADIO.get("on"):
        # Run promptly after a show starts and keep checking while a record or
'''
LARDER_LOOP_NEW = '''    while rooms_open():                                        # [kitchen]
        # Run promptly after a show starts and keep checking while a record or
'''

LARDER_HOLD_OLD = '''            _paused_hold = radio_paused()
'''
LARDER_HOLD_NEW = '''            _paused_hold = off_air()                               # [kitchen]
'''

LARDER_BOXDOWN_OLD = '''                        or len(_BOX_HOLD) >= 3
                        or radio_paused())
'''
LARDER_BOXDOWN_NEW = '''                        or len(_BOX_HOLD) >= 3
                        or off_air())                                  # [kitchen]
'''

LARDER_CAP_OLD = '''            cap = min(larder_cap(),
                      (12 if box_down and not radio_paused() else _want)
                      if not radio_paused() else larder_cap())
'''
LARDER_CAP_NEW = '''            cap = min(larder_cap(),
                      (12 if box_down and not off_air() else _want)
                      if not off_air() else larder_cap())              # [kitchen]
'''

LARDER_GATE_OLD = '''            if _OLLAMA_GATE.locked() and _stocked >= 2 and not radio_paused():
'''
LARDER_GATE_NEW = '''            if _OLLAMA_GATE.locked() and _stocked >= 2 and not off_air():   # [kitchen]
'''

UNFINISHED_GATE_OLD = '''    try:
        if not radio_paused():
            return 0
        _now = time.time()
        if _now - float(_PAUSE_UNFINISHED_MEMO.get("at") or 0) < 5.0:
'''
UNFINISHED_GATE_NEW = '''    try:
        if not off_air():                                         # [kitchen]
            return 0
        _now = time.time()
        if _now - float(_PAUSE_UNFINISHED_MEMO.get("at") or 0) < 5.0:
'''

UNFINISHED_KINDS_OLD = '''        for _k in ("manager", "caller", "gallery", "news"):
            for _r in list(_SHELF.get(_k) or []):
'''
UNFINISHED_KINDS_NEW = '''        for _k in ROUND_SHELF_KINDS:                              # [kitchen]
            for _r in list(_SHELF.get(_k) or []):
'''

WINDOW_OLD = '''    if radio_paused():
        return "the station is off air - everything is a window (#1108)"
'''
WINDOW_NEW = '''    if off_air():                                                 # [kitchen]
        return "the station is off air - everything is a window (#1108)"
'''

PREP_ONE_OLD = '''        if (not _new_script and radio_paused()
                and str(kind) in (hour_short_kinds() or [])):
'''
PREP_ONE_NEW = '''        if (not _new_script and off_air()                         # [kitchen]
                and str(kind) in (hour_short_kinds() or [])):
'''

PLAN_SORT_OLD = '''        if radio_paused():
            try:
                _needs = hour_needs_now() or {}
'''
PLAN_SORT_NEW = '''        if off_air():                                             # [kitchen]
            try:
                _needs = hour_needs_now() or {}
'''

PLAN_SHORT_OLD = '''            _short_now = (set(hour_short_kinds() or ())
                          if radio_paused() else set())
'''
PLAN_SHORT_NEW = '''            _short_now = (set(hour_short_kinds() or ())
                          if off_air() else set())                    # [kitchen]
'''

LIFT_OLD = '''    try:
        if radio_paused():
            return 3.0
        return 1.0 + 0.5 * float(surplus() or 0)
'''
LIFT_NEW = '''    try:
        if off_air():                                             # [kitchen]
            return 3.0
        return 1.0 + 0.5 * float(surplus() or 0)
'''

BANK_AHEAD_OLD = '''    try:
        if not radio_paused():
            return 0.0
        if road and str(road) not in bank_ahead_roads():
'''
BANK_AHEAD_NEW = '''    try:
        if not off_air():                                         # [kitchen]
            return 0.0
        if road and str(road) not in bank_ahead_roads():
'''

WORK_TARGET_OLD = '''        return base * (build_lift() if radio_paused() else 1.0)
'''
WORK_TARGET_NEW = '''        return base * (build_lift() if off_air() else 1.0)       # [kitchen]
'''

DEADLINE_OLD = '''scope = _PREP_TASK_DEADLINE.set(time.time() + (120.0 if radio_paused() else 45.0))'''
DEADLINE_NEW = '''scope = _PREP_TASK_DEADLINE.set(time.time() + (120.0 if off_air() else 45.0))   # [kitchen]'''

WORKSHOP_OLD = '''        if not radio_paused() or not _RADIO.get("on"):
            return
        if hour_short_kinds():
            return                      # bank first; polish after
'''
WORKSHOP_NEW = '''        if not off_air() or not rooms_open():                    # [kitchen]
            return
        if hour_short_kinds():
            return                      # bank first; polish after
'''

SPEECH_CLOCK_OLD = '''                if waiting:
                    _SFX_SPEECH["why"] = ("idle listening stands aside: %d job(s) waiting in the writing room"
                                          % waiting)
                else:
                    paused = bool(radio_paused())
'''
SPEECH_CLOCK_NEW = '''                # [kitchen] off air the writing room's jobs are the kitchen's own and the
                # transcriber is wyoming's (its own service): nothing to stand aside for
                if waiting and not off_air():
                    _SFX_SPEECH["why"] = ("idle listening stands aside: %d job(s) waiting in the writing room"
                                          % waiting)
                else:
                    paused = bool(off_air())
'''

SPEECH_BITE_OLD = '''    for (path,) in rows:
        if not _RADIO.get("on"):
            break
        try:
            said = clip_speech.transcribe_file(str(path))
'''
SPEECH_BITE_NEW = '''    for (path,) in rows:
        if not rooms_open():                                      # [kitchen]
            break
        try:
            said = clip_speech.transcribe_file(str(path))
'''

AD_STUDIO_OLD = '''    wait = 45.0
    while _RADIO.get("on"):
        await asyncio.sleep(wait)
        wait = AD_STUDIO_TICK
        try:
            if not _RADIO.get("on"):
                continue
            made = ads_produced_since(3600.0)
'''
AD_STUDIO_NEW = '''    wait = 45.0
    while rooms_open():                                           # [kitchen]
        await asyncio.sleep(wait)
        wait = AD_STUDIO_TICK
        try:
            if not rooms_open():                                 # [kitchen]
                continue
            made = ads_produced_since(3600.0)
'''

STORAGE_OLD = '''    while _RADIO.get("on"):
        await asyncio.sleep(STORAGE_SWEEP)
'''
STORAGE_NEW = '''    while rooms_open():                                           # [kitchen]
        await asyncio.sleep(STORAGE_SWEEP)
'''

SPEAKBOX_OLD = '''    await asyncio.sleep(5)
    while _RADIO.get("on"):
        # Every mind, not only the one in play (#627)'''
SPEAKBOX_NEW = '''    await asyncio.sleep(5)
    while rooms_open():                                           # [kitchen]
        # Every mind, not only the one in play (#627)'''

SFX_KEEPERS_OLD = '''            if not (_RADIO.get("on") and dj_settings().get("sfx")):
                continue
'''
SFX_KEEPERS_NEW = '''            if not (rooms_open() and dj_settings().get("sfx")):   # [kitchen]
                continue
'''

TINT_STEP_OLD = '''    if not _RADIO.get("on") or (not dialogue_tint_required()
                                and (not _DIALOGUE_RECOVERY or s3_flow_is_open())):
'''
TINT_STEP_NEW = '''    if not rooms_open() or (not dialogue_tint_required()          # [kitchen]
                            and (not _DIALOGUE_RECOVERY or s3_flow_is_open())):
'''

ROOM_LEFT_OLD = '''        if radio_paused():
            try:
                return max(900.0, float(prep_deep_seconds() or 0))
'''
ROOM_LEFT_NEW = '''        if off_air():                                             # [kitchen]
            try:
                return max(900.0, float(prep_deep_seconds() or 0))
'''

BOOTHS_OLD = '''    paused = bool(radio_paused())
    capacity = max(1, int(ENGINE_BUDGET))
'''
BOOTHS_NEW = '''    paused = bool(off_air())                                      # [kitchen]
    capacity = max(1, int(ENGINE_BUDGET))
'''

SITTING_OLD = '''    if (radio_paused() and len({voice_engine_for(v) for v in order}) > 1):
'''
SITTING_NEW = '''    if (off_air() and len({voice_engine_for(v) for v in order}) > 1):   # [kitchen]
'''

BOOTH_RETURN_OLD = '''                if not radio_paused():
                    return                 # live work owns its two slots again
'''
BOOTH_RETURN_NEW = '''                if not off_air():                                 # [kitchen]
                    return                 # live work owns its two slots again
'''

BOOTH_WHILE_OLD = '''                while pending and remaining > 0 and radio_paused():
'''
BOOTH_WHILE_NEW = '''                while pending and remaining > 0 and off_air():    # [kitchen]
'''

RETINT_SHELF_OLD = '''        if not free and surplus() <= 0 and not radio_paused():
            return ""
'''
RETINT_SHELF_NEW = '''        if not free and surplus() <= 0 and not off_air():         # [kitchen]
            return ""
'''

RETINT_ONE_OLD = '''            urgent = [] if radio_paused() else [
'''
RETINT_ONE_NEW = '''            urgent = [] if off_air() else [                       # [kitchen]
'''

TINT_BUDGET_OLD = '''        if radio_paused():
            try:
                _covered = not hour_short_kinds()
'''
TINT_BUDGET_NEW = '''        if off_air():                                             # [kitchen]
            try:
                _covered = not hour_short_kinds()
'''

TINT_STOP_OLD = '''    if critical and radio_paused():
        return ""
    return tint_pressure()'''
TINT_STOP_NEW = '''    if critical and off_air():                                    # [kitchen]
        return ""
    return tint_pressure()'''

CALL_PROD_OLD = '''        if not radio_paused() or not dj_settings().get("produced_calls", True):
'''
CALL_PROD_NEW = '''        if not off_air() or not dj_settings().get("produced_calls", True):   # [kitchen]
'''

PLOT_OLD = '''        if bool((row or {}).get("held")):
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        return bool(radio_paused())
'''
PLOT_NEW = '''        if bool((row or {}).get("held")):
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        return bool(off_air())      # [kitchen] the act holds while the station banks, whichever switch
'''

TOPIC_OLD = '''    if not _RADIO.get("on") or radio_paused():
        _TOPIC_COOK["why"] = "the station is off air"
        return 0
'''
TOPIC_NEW = '''    if not rooms_open():                                          # [kitchen]
        _TOPIC_COOK["why"] = "the station is off and the kitchen is closed"
        return 0
'''

RESPONSE_BANK_OLD = '''            if _RADIO.get("on") or radio_paused():
                await response_bank_prepare(8 if radio_paused() else 2)
        except Exception as exc:
            _RESPONSE_WARM_STATE.update(last_at=time.time(), made=0, why=str(exc)[:200])
        await asyncio.sleep(20 if radio_paused() else 60)
'''
RESPONSE_BANK_NEW = '''            if rooms_open():                                     # [kitchen]
                await response_bank_prepare(8 if off_air() else 2)
        except Exception as exc:
            _RESPONSE_WARM_STATE.update(last_at=time.time(), made=0, why=str(exc)[:200])
        await asyncio.sleep(20 if off_air() else 60)
'''

SFXGUY_READY_OLD = '''            if _RADIO.get("on"):
                await sfxguy_ready_prepare(1)
'''
SFXGUY_READY_NEW = '''            if rooms_open():                                     # [kitchen]
                await sfxguy_ready_prepare(1)
'''

SWITCHBOARD_OLD = '''            if _RADIO.get("on"):
                live = switchboard_live()
'''
SWITCHBOARD_NEW = '''            if rooms_open():                                     # [kitchen]
                live = switchboard_live()
'''

ENGINE_PROTECT_OLD = '''    return bool(keep_cast and _RADIO.get("on") and engine == host_clone_engine())
'''
ENGINE_PROTECT_NEW = '''    return bool(keep_cast and rooms_open() and engine == host_clone_engine())   # [kitchen]
'''

PAPER_ENABLED_OLD = '''    return bool(_RADIO.get("on") and not radio_paused()
                and dj_settings().get("paper_hourly", True))
'''
PAPER_ENABLED_NEW = '''    return bool(((_RADIO.get("on") and not radio_paused()) or kitchen_open())   # [kitchen]
                and dj_settings().get("paper_hourly", True))
'''

DESKS_OLD = '''def _desk_cloud(m: dict[str, Any]) -> dict[str, Any] | None:
    """#1044: the word-cloud data as a board.'''
DESKS_NEW = '''def _desk_rolled(m: dict[str, Any]) -> dict[str, Any] | None:
    """[kitchen] What the roulette wrote while nothing aired: the rounds System 3
    rolled and the rooms wrote in this edition's window, by road, with three of
    their openings and the directions their dice gave. Code only, memory only -
    the larder and the shelves as they stand."""
    if not (m.get("paused") or m.get("offline")):
        return None
    since = float(m.get("since") or 0)
    until = float(m.get("until") or time.time())
    rows: list[tuple[str, dict[str, Any]]] = []
    try:
        rows.extend(("banter", e) for e in list(_LARDER) if isinstance(e, dict))
        for kind, shelf in list(_SHELF.items()):
            for r in list(shelf or []):
                if isinstance(r, dict):
                    e = r.get("entry") if isinstance(r.get("entry"), dict) else r
                    rows.append((str(kind), e))
    except Exception:  # noqa: BLE001
        return None
    fresh: list[tuple[str, dict[str, Any]]] = []
    for kind, e in rows:
        try:
            at = float(e.get("at") or 0)
        except Exception:  # noqa: BLE001
            at = 0.0
        if since <= at <= until:
            fresh.append((str(e.get("road") or kind), e))
    if not fresh:
        return None
    by_road: dict[str, dict[str, Any]] = {}
    for road, e in fresh:
        row = by_road.setdefault(road, {"written": 0, "rolled": 0, "recorded": 0, "seconds": 0.0})
        row["written"] += 1
        if e.get("system3") or e.get("dice") or e.get("turn_dice"):
            row["rolled"] += 1
        try:
            secs = float(e.get("seconds") or 0)
        except Exception:  # noqa: BLE001
            secs = 0.0
        if secs > 0:
            row["recorded"] += 1
            row["seconds"] += secs
    roads = sorted(by_road.items(), key=lambda kv: (-kv[1]["written"], kv[0]))
    board = ["| Road | Written | Rolled | Recorded | Sec |", "| --- | --- | --- | --- | --- |"]
    for road, row in roads[:10]:
        board.append(f"| {_paper_shorten(str(road).replace('_', ' '), 22)} | {row['written']} | "
                     f"{row['rolled']} | {row['recorded']} | {int(row['seconds'])} |")
    fresh.sort(key=lambda kv: -float(kv[1].get("at") or 0))
    openings: list[str] = []
    for road, e in fresh:
        if len(openings) >= 3:
            break
        text = str(e.get("script_plain") or e.get("script") or "")
        first = next((ln.strip() for ln in text.split("\\n") if ln.strip()), "")
        if not first:
            continue
        dice = [str(d.get("text") or "") for d in (e.get("dice") or [])
                if isinstance(d, dict) and d.get("text")][:2]
        openings.append(f"- **{_paper_shorten(str(road).replace('_', ' '), 18)}**: "
                        f"\\"{_paper_shorten(first, 150)}\\""
                        + (f" - the dice said: {'; '.join(_paper_shorten(d, 70) for d in dice)}"
                           if dice else ""))
    total = sum(r["written"] for _k, r in roads)
    rolled = sum(r["rolled"] for _k, r in roads)
    recorded = sum(r["recorded"] for _k, r in roads)
    body = (
        ("The air is stopped, and the kitchen is not. " if m.get("paused") else
         "The station is switched off, and the kitchen stayed open. ")
        + f"In this edition's hour the roulette rolled and the rooms wrote {total} round"
        + ("s" if total != 1 else "")
        + f" on {len(roads)} road" + ("s" if len(roads) != 1 else "")
        + f"; {rolled} carry System 3's dice and {recorded} already have their audio. "
          "Nothing here has been heard yet - it is the stock the next show opens on.\\n\\n"
        + "\\n".join(board)
        + ("\\n\\nThree of the newest, as written:\\n\\n" + "\\n".join(openings) if openings else "")
    )
    meta: dict[str, Any] = {
        "headline": ("What the Roulette Wrote During the Pause" if m.get("paused")
                     else "What the Roulette Wrote With the Air Off"),
        "deck": f"{total} rounds rolled and written on {len(roads)} roads while nothing aired",
        "section": "report", "priority": 2, "page": 2,
        "byline": "The Orchestrator", "style_hint": "report",
        "kicker": "THE KITCHEN",
        "stats": [{"value": str(total), "label": "rounds written"},
                  {"value": str(rolled), "label": "with dice"},
                  {"value": str(recorded), "label": "recorded"},
                  {"value": str(len(roads)), "label": "roads"}],
    }
    bars = [(str(road).replace("_", " "), row["written"]) for road, row in roads][:8]
    if len(bars) >= 2:
        meta["chart"] = {"kind": "bars", "values": [int(v) for _, v in bars],
                         "labels": [_paper_shorten(k, 11) for k, _ in bars],
                         "show_values": True, "min": 0}
        meta["caption"] = "Rounds written per road in this hour, with the air off."
    return {"slug": "what-the-roulette-wrote", "meta": meta, "body": body}


def _desk_library(m: dict[str, Any]) -> dict[str, Any] | None:
    """[kitchen] The SFX Guy's study while the air is off: the clips he has
    listened to this session, the frames he has looked at, the size of the
    index he reaches into. Memory only - the counters the keepers already keep."""
    if not (m.get("paused") or m.get("offline")):
        return None
    sp = dict(_SFX_SPEECH or {})
    match = dict(_SFX_MATCH or {})
    vision: dict[str, Any] = {}
    try:
        import sys as _sys
        _mod = _sys.modules.get("sfx_vision_idle")
        vision = dict(getattr(_mod, "STATE", {}) or {}) if _mod else {}
    except Exception:  # noqa: BLE001
        vision = {}
    done = int(sp.get("done") or 0)
    heard = int(sp.get("heard") or 0)
    empty = int(sp.get("empty") or 0)
    looked = int(vision.get("looked") or 0)
    frames = int(vision.get("frames") or 0)
    indexed = int(match.get("rows") or 0)
    if not (done or looked or indexed):
        return None
    body = (
        "While nothing airs the SFX Guy studies his own library. "
        + (f"This session he has listened to {done} clip" + ("s" if done != 1 else "")
           + f"; {heard} said something he wrote down and {empty} were silent or noise. "
           if done else "He has not listened to a clip this session. ")
        + (f"He has looked at {frames} frame" + ("s" if frames != 1 else "")
           + f" across {looked} video clip" + ("s" if looked != 1 else "")
           + ", describing what is on the screen so a round can call for it by what it shows. "
           if looked else "")
        + (f"The index he reaches into holds {indexed} clips by name, word and picture. "
           if indexed else "")
        + ("He is listening right now. " if sp.get("running") else "")
        + ("He is studying frames right now. " if vision.get("running") else "")
        + (f"When he stands aside it is because: {sp.get('why')}. "
           if sp.get("why") and not sp.get("running") else "")
    )
    meta: dict[str, Any] = {
        "headline": "The SFX Guy Studies His Library",
        "deck": (f"{done} clips listened to, {frames} frames looked at, "
                 f"{indexed} clips in the index"),
        "section": "report", "priority": 3, "page": 3,
        "byline": "The Orchestrator", "style_hint": "report",
        "kicker": "THE KITCHEN",
        "stats": [{"value": str(done), "label": "clips listened"},
                  {"value": str(heard), "label": "said something"},
                  {"value": str(looked), "label": "videos studied"},
                  {"value": str(indexed), "label": "in the index"}],
    }
    return {"slug": "the-sfx-guy-studies", "meta": meta, "body": body}


def _desk_cloud(m: dict[str, Any]) -> dict[str, Any] | None:
    """#1044: the word-cloud data as a board.'''

DESK_RUN_OLD = '''        if paused or offline:
            await _run("banked", _desk_banked)
'''
DESK_RUN_NEW = '''        if paused or offline:
            await _run("banked", _desk_banked)
            await _run("rolled", _desk_rolled)                   # [kitchen]
            await _run("library", _desk_library)                 # [kitchen]
'''

# (label, old, new, probe, probe count once applied)
APP = [
    ("off_air, the kitchen's switches and the round shelves", OFF_AIR_OLD, OFF_AIR_NEW, "def off_air() -> bool:", 1),
    ("_radio_worker takes a kitchen flag", WORKER_SIG_OLD, WORKER_SIG_NEW, "persistent: bool = True, kitchen: bool = False) -> None:", 1),
    ("the worker loop runs kitchen rooms with the show off", WORKER_LOOP_OLD, WORKER_LOOP_NEW, 'while generation == _RADIO_RUN[0] and (_RADIO.get("on") or kitchen):', 1),
    ("...and leaves with the kitchen", WORKER_EXIT_OLD, WORKER_EXIT_NEW, 'if generation != _RADIO_RUN[0] or not (_RADIO.get("on") or kitchen):', 1),
    ("radio_worker_start registers kitchen rooms", WORKER_START_OLD, WORKER_START_NEW, '"kitchen": bool(kitchen),', 1),
    ("the census says whether the kitchen is open", CENSUS_OLD, CENSUS_NEW, '"kitchen_rooms": sum(1 for row in live if row.get("kitchen")),', 1),
    ("the roster, start, work and watch", KITCHEN_BLOCK_OLD, KITCHEN_BLOCK_NEW, "def kitchen_start(why: str = \"\") -> int:", 1),
    ("radio_stop closes the kitchen", RADIO_STOP_OLD, RADIO_STOP_NEW, '_KITCHEN["on"] = False          # [kitchen] its rooms go with this generation', 1),
    ("dj_stop: the engines wait for the kitchen", DJ_STOP_HEAD_OLD, DJ_STOP_HEAD_NEW, "# [kitchen] OFF means off AIR.", 1),
    ("dj_stop opens the kitchen", DJ_STOP_TAIL_OLD, DJ_STOP_TAIL_NEW, 'kitchen_start("the show stopped")', 1),
    ("a boot that finds the switch off opens the kitchen", RESUME_OLD, RESUME_NEW, 'kitchen_start("the station boots switched off")', 1),
    ("pantry_keeper works for the kitchen", PANTRY_GATE_OLD, PANTRY_GATE_NEW, "if not rooms_open():                                 # [kitchen]\n                continue\n            window = pantry_window()", 1),
    ("...piper joins the banking shift off air", PANTRY_PIPER_OLD, PANTRY_PIPER_NEW, "if off_air() and _hour_short:", 1),
    ("...finishes every written row off air", PANTRY_FINISH_OLD, PANTRY_FINISH_NEW, "_finish_all = bool(off_air() and _pause_unfinished_rows())", 1),
    ("...and every round-shaped shelf", PANTRY_ROUNDS_OLD, PANTRY_ROUNDS_NEW, "_rounds = ROUND_SHELF_KINDS", 1),
    ("...with the long slice", PANTRY_SLICE_OLD, PANTRY_SLICE_NEW, "if off_air():                                        # [kitchen]\n                _slice = max(_slice, 120.0)", 1),
    ("...and banter does not wait on the live road", PANTRY_BANTER_WAIT_OLD, PANTRY_BANTER_WAIT_NEW, "_banter_wait = (bool(_hour_short) and not off_air()", 1),
    ("larder_keeper runs for the kitchen", LARDER_LOOP_OLD, LARDER_LOOP_NEW, "while rooms_open():                                        # [kitchen]", 1),
    ("...holds unaired rounds off air", LARDER_HOLD_OLD, LARDER_HOLD_NEW, "_paused_hold = off_air()", 1),
    ("...goes deep off air", LARDER_BOXDOWN_OLD, LARDER_BOXDOWN_NEW, "or off_air())                                  # [kitchen]", 1),
    ("...to the larder cap", LARDER_CAP_OLD, LARDER_CAP_NEW, "(12 if box_down and not off_air() else _want)", 1),
    ("...and writes under a locked gate", LARDER_GATE_OLD, LARDER_GATE_NEW, "_stocked >= 2 and not off_air():", 1),
    ("_pause_unfinished_rows counts off air", UNFINISHED_GATE_OLD, UNFINISHED_GATE_NEW, "if not off_air():                                         # [kitchen]\n            return 0\n        _now = time.time()", 1),
    ("...across every round shelf", UNFINISHED_KINDS_OLD, UNFINISHED_KINDS_NEW, "for _k in ROUND_SHELF_KINDS:", 1),
    ("pantry_window: off air everything is a window", WINDOW_OLD, WINDOW_NEW, "if off_air():                                                 # [kitchen]\n        return \"the station is off air - everything is a window (#1108)\"", 1),
    ("prep_one: the hour's shortfall outranks the frozen sheet off air", PREP_ONE_OLD, PREP_ONE_NEW, "if (not _new_script and off_air()", 1),
    ("prep_plan sorts by shortfall off air", PLAN_SORT_OLD, PLAN_SORT_NEW, "if off_air():                                             # [kitchen]\n            try:\n                _needs = hour_needs_now() or {}", 1),
    ("...and names the short roads off air", PLAN_SHORT_OLD, PLAN_SHORT_NEW, "if off_air() else set())", 1),
    ("build_lift lifts off air", LIFT_OLD, LIFT_NEW, "if off_air():                                             # [kitchen]\n            return 3.0", 1),
    ("bank_ahead_hours counts off air", BANK_AHEAD_OLD, BANK_AHEAD_NEW, "if not off_air():                                         # [kitchen]\n            return 0.0", 1),
    ("prepare_work_target_seconds builds off air", WORK_TARGET_OLD, WORK_TARGET_NEW, "return base * (build_lift() if off_air() else 1.0)", 1),
    ("the preparation deadlines stretch off air (x2)", DEADLINE_OLD, DEADLINE_NEW, "(120.0 if off_air() else 45.0))   # [kitchen]", 2),
    ("the workshop polishes off air", WORKSHOP_OLD, WORKSHOP_NEW, "if not off_air() or not rooms_open():                    # [kitchen]", 1),
    ("the SFX listener bites off air and does not stand aside for the kitchen", SPEECH_CLOCK_OLD, SPEECH_CLOCK_NEW, "paused = bool(off_air())", 1),
    ("...and the bite runs for the kitchen", SPEECH_BITE_OLD, SPEECH_BITE_NEW, "if not rooms_open():                                      # [kitchen]\n            break\n        try:\n            said = clip_speech.transcribe_file", 1),
    ("the ad studio cuts for the kitchen", AD_STUDIO_OLD, AD_STUDIO_NEW, "if not rooms_open():                                 # [kitchen]\n                continue\n            made = ads_produced_since(3600.0)", 1),
    ("the disk allowance is kept for the kitchen", STORAGE_OLD, STORAGE_NEW, "while rooms_open():                                           # [kitchen]\n        await asyncio.sleep(STORAGE_SWEEP)", 1),
    ("the speaker box index follows the kitchen", SPEAKBOX_OLD, SPEAKBOX_NEW, "while rooms_open():                                           # [kitchen]\n        # Every mind, not only the one in play (#627)", 1),
    ("the SFX arrivals and levels keepers follow the kitchen (x2)", SFX_KEEPERS_OLD, SFX_KEEPERS_NEW, 'if not (rooms_open() and dj_settings().get("sfx")):   # [kitchen]', 2),
    ("tint repair runs for the kitchen", TINT_STEP_OLD, TINT_STEP_NEW, "if not rooms_open() or (not dialogue_tint_required()          # [kitchen]", 1),
    ("prep_room_left: the deep room off air", ROOM_LEFT_OLD, ROOM_LEFT_NEW, "if off_air():                                             # [kitchen]\n            try:\n                return max(900.0, float(prep_deep_seconds() or 0))", 1),
    ("recording_booths: every slot banks off air", BOOTHS_OLD, BOOTHS_NEW, "paused = bool(off_air())                                      # [kitchen]", 1),
    ("recording_sitting: parallel engines off air", SITTING_OLD, SITTING_NEW, "if (off_air() and len({voice_engine_for(v) for v in order}) > 1):", 1),
    ("the parallel booth stays off air", BOOTH_RETURN_OLD, BOOTH_RETURN_NEW, "if not off_air():                                 # [kitchen]\n                    return                 # live work owns its two slots again", 1),
    ("...and keeps working off air", BOOTH_WHILE_OLD, BOOTH_WHILE_NEW, "while pending and remaining > 0 and off_air():", 1),
    ("retint_shelf re-cuts off air", RETINT_SHELF_OLD, RETINT_SHELF_NEW, "if not free and surplus() <= 0 and not off_air():", 1),
    ("retint_one: nothing urgent off air", RETINT_ONE_OLD, RETINT_ONE_NEW, "urgent = [] if off_air() else [", 1),
    ("tint_budget: the pause bonus off air", TINT_BUDGET_OLD, TINT_BUDGET_NEW, "if off_air():                                             # [kitchen]\n            try:\n                _covered = not hour_short_kinds()", 1),
    ("tint_should_stop: critical work finishes off air", TINT_STOP_OLD, TINT_STOP_NEW, "if critical and off_air():", 1),
    ("[call-prod] produces calls off air", CALL_PROD_OLD, CALL_PROD_NEW, "if not off_air() or not dj_settings().get(\"produced_calls\", True):", 1),
    ("the plot act holds off air", PLOT_OLD, PLOT_NEW, "return bool(off_air())      # [kitchen]", 1),
    ("topics cook for the kitchen", TOPIC_OLD, TOPIC_NEW, 'if not rooms_open():                                          # [kitchen]\n        _TOPIC_COOK["why"]', 1),
    ("the response bank warms for the kitchen", RESPONSE_BANK_OLD, RESPONSE_BANK_NEW, "await response_bank_prepare(8 if off_air() else 2)", 1),
    ("the SFX Guy's ready lines bank for the kitchen", SFXGUY_READY_OLD, SFXGUY_READY_NEW, "if rooms_open():                                     # [kitchen]\n                await sfxguy_ready_prepare(1)", 1),
    ("the switchboard stands for the kitchen", SWITCHBOARD_OLD, SWITCHBOARD_NEW, "if rooms_open():                                     # [kitchen]\n                live = switchboard_live()", 1),
    ("the clone engine is protected while the kitchen renders", ENGINE_PROTECT_OLD, ENGINE_PROTECT_NEW, "return bool(keep_cast and rooms_open() and engine == host_clone_engine())", 1),
    ("the Gazette prints while the kitchen banks", PAPER_ENABLED_OLD, PAPER_ENABLED_NEW, '(_RADIO.get("on") and not radio_paused()) or kitchen_open())   # [kitchen]', 1),
    ("two kitchen desks for the Gazette", DESKS_OLD, DESKS_NEW, "def _desk_rolled(m: dict[str, Any]) -> dict[str, Any] | None:", 1),
    ("...which print beside the banked desk", DESK_RUN_OLD, DESK_RUN_NEW, 'await _run("rolled", _desk_rolled)', 1),
]

# ----------------------------------------------------------------------------
# system2_runtime.py
# ----------------------------------------------------------------------------

S2_HELPERS_OLD = '''        return self.enabled and not bool(self.config.get("legacy_keepers", True))
'''
S2_HELPERS_NEW = '''        return self.enabled and not bool(self.config.get("legacy_keepers", True))

    def _off_air(self):
        """[kitchen] paused OR switched off with the kitchen open - the host's
        off_air() when it has one, radio_paused() otherwise."""
        fn = getattr(self.host, "off_air", None)
        try:
            if callable(fn):
                return bool(fn())
        except Exception:
            pass
        return bool(self.host.radio_paused())

    def _rooms_open(self):
        """[kitchen] the show is on, or the kitchen is open behind a stopped show."""
        fn = getattr(self.host, "rooms_open", None)
        try:
            if callable(fn):
                return bool(fn())
        except Exception:
            pass
        return bool(self.host._RADIO.get("on"))
'''

S2_PREPARE_OLD = '''        if not self.enabled or self._prepare_lock.locked() or not self.host._RADIO.get("on"):
            return
        h = self.host
        async with self._prepare_lock:
'''
S2_PREPARE_NEW = '''        if not self.enabled or self._prepare_lock.locked() or not self._rooms_open():   # [kitchen]
            return
        h = self.host
        async with self._prepare_lock:
'''

S2_LOOKAHEAD_OLD = '''            lookahead = 3600
            if h.radio_paused():
                lookahead = int(self.config["horizon_hours"]) * 3600
'''
S2_LOOKAHEAD_NEW = '''            lookahead = 3600
            if self._off_air():                                  # [kitchen]
                lookahead = int(self.config["horizon_hours"]) * 3600
'''

S2_PREFER_OLD = '''        prefer = ("banter" in kinds and not self.host.radio_paused()
                  and ready < floor and not self._conversation_last_priority)
'''
S2_PREFER_NEW = '''        prefer = ("banter" in kinds and not self._off_air()          # [kitchen]
                  and ready < floor and not self._conversation_last_priority)
'''

S2_SECOND_OLD = '''        if not job and not self.host.radio_paused() and self.config["horizon_hours"] > 1:
'''
S2_SECOND_NEW = '''        if not job and not self._off_air() and self.config["horizon_hours"] > 1:   # [kitchen]
'''

SYSTEM2 = [
    ("System 2 asks the two switches", S2_HELPERS_OLD, S2_HELPERS_NEW, "def _rooms_open(self):", 1),
    ("...and prepares for the kitchen", S2_PREPARE_OLD, S2_PREPARE_NEW, "or not self._rooms_open():   # [kitchen]", 1),
    ("...over the whole horizon off air", S2_LOOKAHEAD_OLD, S2_LOOKAHEAD_NEW, "if self._off_air():                                  # [kitchen]", 1),
    ("...prefers the reserve as a pause would", S2_PREFER_OLD, S2_PREFER_NEW, "not self._off_air()          # [kitchen]", 1),
    ("...and does not reach past the hour off air", S2_SECOND_OLD, S2_SECOND_NEW, "if not job and not self._off_air()", 1),
]

EDITS = {"app.py": APP, "system2_runtime.py": SYSTEM2}


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
            print("%-46s (not in this tree - skipped)" % name[-46:])
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, _probe, want in edits:
            # Applied is judged by the NEW text itself (an insert whose anchor survives
            # inside its own new text is still applied); ready by the anchor's count.
            if text.count(new) >= want:
                print("%-72s applied" % label[:72])
                continue
            n = text.count(old)
            if n == want:
                print("%-72s ready" % label[:72])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-72s MISSING (anchor count %d, wanted %d)" % (label[:72], n, want))
                missing = True
        if changed:
            plans.append((path, text, mode, bom))
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
        tmp = path.with_suffix(path.suffix + ".kitchen.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

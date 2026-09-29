"""The hourly H3 door: GET/POST /api/h3/hourly ([h3-hourly]).

Measured 2026-09-27: the gallery's header (kiosk ad-viewer.js) and the
Script view's folder controls (script-page.js) both poll /api/h3/hourly for
the switch, the source mix and the seconds to the next hourly render - and
the station answered 404, so the meter read "err" and the toggle never
armed. The clock itself (h3_hourly_ad_clock) has always run: one H3 sponsor
sting at minute 3 of every live hour, from a speech-indexed clip.

This gives the clock its door and its switch: the state lives in
data/h3_hourly.json (enabled, gallery_share), the door reports the seconds
to the next fire from the clock's own marker, a disabled hour is marked so a
re-enable waits for the next hour (a second H3 render in one boot is what
cooks the box, #1285), and gallery_share percent of hours take a gallery
image as the reference through the durable parody queue - the same road the
gallery's own "Render H3 video" button takes.

--check exits 0 ready / 2 applied / 1 missing; --apply writes LF atomically.
ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("state-and-view",
     '_H3_HOURLY_LAST = [""]\n'
     '\n'
     '\n'
     'def h3_hourly_ad_prompt() -> str:\n',
     '_H3_HOURLY_LAST = [""]\n'
     '_H3_HOURLY_FILE = DATA_DIR / "h3_hourly.json"\n'
     '_H3_HOURLY_STATE: dict[str, Any] = {}\n'
     '_H3_HOURLY_PERIOD_S = 3600\n'
     '_H3_HOURLY_MINUTE = 3\n'
     '\n'
     '\n'
     'def h3_hourly_load() -> dict[str, Any]:\n'
     '    """[h3-hourly] The operator\'s hourly-H3 switch and source mix, read\n'
     '    once from disk. Defaults: on, 20% of hours from a gallery image (the\n'
     '    rest from a speech-indexed clip) - what the clock always did, made\n'
     '    visible and switchable."""\n'
     '    if not _H3_HOURLY_STATE:\n'
     '        state: dict[str, Any] = {"enabled": True, "gallery_share": 20,\n'
     '                                 "quality": dict(comfy_workshop.QUALITY),        # [h3-quality]\n'
     '                                 "brief": dict(comfy_workshop.BRIEF)}            # [h3-brief-config]\n'
     '        try:\n'
     '            got = json.loads(_H3_HOURLY_FILE.read_text(encoding="utf-8"))\n'
     '            if isinstance(got, dict):\n'
     '                state.update({k: got[k] for k in ("enabled", "gallery_share", "last_at", "last_message",\n'
     '                                                    "last_source", "last_marker", "quality", "brief",\n'
     '                                                    "cast", "host_share") if k in got})   # [h3-cast]\n'
     '        except FileNotFoundError:\n'
     '            pass\n'
     '        except Exception as exc:  # noqa: BLE001\n'
     '            pipeline_log("ads", "hourly H3 switch unreadable: %s" % type(exc).__name__)\n'
     '        state["quality"] = comfy_workshop.set_quality(state.get("quality"))     # [h3-quality] in force\n'
     '        state["brief"] = comfy_workshop.set_brief(state.get("brief"))           # [h3-brief-config]\n'
     '        state["cast"] = comfy_workshop.set_cast(state.get("cast"))              # [h3-cast]\n'
     '        _H3_HOURLY_STATE.update(state)\n'
     '    return _H3_HOURLY_STATE\n'
     '\n'
     '\n'
     'def h3_hourly_save(patch: dict[str, Any]) -> dict[str, Any]:\n'
     '    state = h3_hourly_load()\n'
     '    if "enabled" in patch:\n'
     '        state["enabled"] = bool(patch["enabled"])\n'
     '    if "gallery_share" in patch:\n'
     '        try:\n'
     '            state["gallery_share"] = max(0, min(100, int(round(float(patch["gallery_share"])))))\n'
     '        except (TypeError, ValueError):\n'
     '            pass\n'
     '    for key in ("last_at", "last_message", "last_source", "last_marker"):\n'
     '        if key in patch:\n'
     '            state[key] = patch[key]\n'
     '    if isinstance(patch.get("quality"), dict):                            # [h3-quality]\n'
     '        state["quality"] = comfy_workshop.set_quality(patch["quality"])\n'
     '    if isinstance(patch.get("brief"), dict):                              # [h3-brief-config]\n'
     '        state["brief"] = comfy_workshop.set_brief(patch["brief"])\n'
     '    if isinstance(patch.get("cast"), dict):                               # [h3-cast]\n'
     '        state["cast"] = comfy_workshop.set_cast(patch["cast"])\n'
     '    if "host_share" in patch:\n'
     '        try:\n'
     '            state["host_share"] = max(0, min(100, int(round(float(patch["host_share"])))))\n'
     '        except (TypeError, ValueError):\n'
     '            pass\n'
     '    try:\n'
     '        tmp = _H3_HOURLY_FILE.with_suffix(".json.tmp")\n'
     '        tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")\n'
     '        os.replace(tmp, _H3_HOURLY_FILE)\n'
     '    except Exception as exc:  # noqa: BLE001\n'
     '        pipeline_log("ads", "hourly H3 switch not saved: %s" % type(exc).__name__)\n'
     '    return state\n'
     '\n'
     '\n'
     'def h3_hourly_next_at(now_ts: float, last_marker: str) -> float:\n'
     '    """When the clock next fires: minute 3 of this hour if that has not\n'
     '    happened yet, else minute 3 of the next hour."""\n'
     '    now = time.localtime(now_ts)\n'
     '    this_hour = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, now.tm_hour, 0, 0, 0, 0, -1))\n'
     '    marker = time.strftime("%Y%m%d%H", now)\n'
     '    due = this_hour + _H3_HOURLY_MINUTE * 60\n'
     '    if now_ts < due and marker != last_marker:\n'
     '        return due\n'
     '    return this_hour + _H3_HOURLY_PERIOD_S + _H3_HOURLY_MINUTE * 60\n'
     '\n'
     '\n'
     'def h3_hourly_view() -> dict[str, Any]:\n'
     '    """What the gallery\'s meter and the Script view\'s controls read."""\n'
     '    state = h3_hourly_load()\n'
     '    now_ts = time.time()\n'
     '    next_at = h3_hourly_next_at(now_ts, _H3_HOURLY_LAST[0])\n'
     '    return {"enabled": state.get("enabled", True) is not False,\n'
     '            "gallery_share": int(state.get("gallery_share", 20)),\n'
     '            "period_seconds": _H3_HOURLY_PERIOD_S,\n'
     '            "seconds_remaining": max(0.0, round(next_at - now_ts, 1)),\n'
     '            "next_at": next_at, "radio_on": bool(_RADIO.get("on")),\n'
     '            "last_at": state.get("last_at"), "last_message": state.get("last_message"),\n'
     '            "last_source": state.get("last_source"),\n'
     '            # [h3-quality] the profile in force, the presets, and what the box can take\n'
     '            "quality": dict(comfy_workshop.QUALITY),\n'
     '            "presets": {k: dict(v) for k, v in comfy_workshop.PRESETS.items()},\n'
     '            "step_choices": list(comfy_workshop.STEP_CHOICES),\n'
     "            # [h3-brief-config] the brief's knobs and their choices\n"
     '            "brief": dict(comfy_workshop.BRIEF), "brief_defaults": dict(comfy_workshop.BRIEF_DEFAULTS),\n'
     '            "follow_choices": list(comfy_workshop.FOLLOW_CHOICES), "shot_choices": list(comfy_workshop.SHOT_CHOICES),\n'
     '            "sampler_choices": list(comfy_workshop.SAMPLER_CHOICES), "scheduler_choices": list(comfy_workshop.SCHEDULER_CHOICES),\n'
     '            "default_constraints": comfy_workshop.DEFAULT_CONSTRAINTS, "default_audio": comfy_workshop.DEFAULT_AUDIO,\n'
     '            "frame_choices": list(comfy_workshop.FRAME_CHOICES),\n'
     "            # [h3-cinematic] the base path's steps and heat line; [h3-cast] the host's LoRA\n"
     '            "base_step_choices": list(comfy_workshop.BASE_STEP_CHOICES),\n'
     '            "cinematic_heat_c": comfy_workshop.CINEMATIC_HEAT_C,\n'
     '            "cast": dict(comfy_workshop.CAST), "cast_status": h3_cast_status(),\n'
     '            "host_share": int(state.get("host_share", 0) or 0),\n'
     '            # [h3-budget] what each preset costs on this box for ten and five seconds\n'
     '            "estimates": comfy_workshop.estimates(243), "estimates_5s": comfy_workshop.estimates(124),\n'
     '            "budget_choices": list(comfy_workshop.BUDGET_CHOICES),\n'
     '            "box": {"hottest_c": box_hottest_c(), "available_gb": comfy_host_available_gb(),\n'
     '                    "ceiling_c": RENDER_TEMP_CEILING_C, "floor_gb": VIDEO_RENDER_FLOOR_GB}}\n'
     '\n'
     '\n'
     'def h3_hourly_ad_prompt() -> str:\n', 1),
    ("clock-honours-the-switch",
     '            if now.tm_min >= 3 and marker != _H3_HOURLY_LAST[0] and _RADIO.get("on"):\n'
     '                _H3_HOURLY_LAST[0] = marker\n'
     '                message, job = await voice_ad_render(h3_hourly_ad_prompt())\n'
     '                pipeline_log("ads", "hourly H3 ad: %s%s" %\n'
     '                             (message[:180], "" if job else " (not queued)"))\n',
     '            if now.tm_min >= _H3_HOURLY_MINUTE and marker != _H3_HOURLY_LAST[0] and _RADIO.get("on"):\n'
     '                _H3_HOURLY_LAST[0] = marker\n'
     '                state = h3_hourly_load()\n'
     '                if state.get("enabled", True) is False:\n'
     '                    # [h3-hourly] the operator\'s switch (the gallery\'s H3\n'
     '                    # toggle). This hour is marked, so a re-enable waits for\n'
     '                    # the next one: a second H3 render in one boot is what\n'
     '                    # cooks the box (#1285).\n'
     '                    pipeline_log("ads", "hourly H3 ad: off at the operator\'s switch")\n'
     '                else:\n'
     '                    message, job, source = await h3_hourly_render(state)\n'
     '                    pipeline_log("ads", "hourly H3 ad (%s): %s%s" %\n'
     '                                 (source, str(message)[:180], "" if job else " (not queued)"))\n'
     '                    h3_hourly_save({"last_at": time.time(), "last_message": str(message)[:200],\n'
     '                                    "last_source": source, "last_marker": marker})\n', 1),
    ("no-refire-after-restart",
     '    while True:\n'
     '        try:\n'
     '            now = time.localtime()\n'
     '            marker = time.strftime("%Y%m%d%H", now)\n'
     '            # Give the orchestrator time to establish the hour\'s topic.  The\n'
     '            # durable H3 queue handles the rest even when memory is tight.\n'
     '            if now.tm_min >= _H3_HOURLY_MINUTE and marker != _H3_HOURLY_LAST[0] and _RADIO.get("on"):\n',
     '    while True:\n'
     '        try:\n'
     '            now = time.localtime()\n'
     '            marker = time.strftime("%Y%m%d%H", now)\n'
     '            if not _H3_HOURLY_LAST[0]:\n'
     '                # [h3-hourly] A restart forgot the hour it had rendered, so the\n'
     '                # "hourly" ad fired again on every boot past minute 3 - and the\n'
     '                # station restarts about every twelve minutes (#1283). The hour\n'
     '                # that rendered is on disk; take it up.\n'
     '                _H3_HOURLY_LAST[0] = str(h3_hourly_load().get("last_marker") or "")\n'
     '            # Give the orchestrator time to establish the hour\'s topic.  The\n'
     '            # durable H3 queue handles the rest even when memory is tight.\n'
     '            if now.tm_min >= _H3_HOURLY_MINUTE and marker != _H3_HOURLY_LAST[0] and _RADIO.get("on"):\n', 1),
    ("render-and-door",
     'async def h3_capacity_keeper() -> None:\n',
     'async def h3_hourly_render(state: dict[str, Any]) -> tuple[str, Any, str]:\n'
     '    """[h3-hourly] One hourly stinger: from a gallery image for gallery_share\n'
     '    percent of hours (a frame stinger through the durable parody queue, the\n'
     '    road the gallery\'s own "Render H3 video" takes; newspaper pages\n'
     '    excluded), else from a speech-indexed clip through voice_ad_render."""\n'
     '    goal = h3_hourly_ad_prompt()\n'
     '    try:\n'
     '        share = max(0, min(100, int(state.get("gallery_share", 20) or 0)))\n'
     '    except (TypeError, ValueError):\n'
     '        share = 20\n'
     "    # [h3-cast] the host's own hours: the text road with the cast LoRA on the\n"
     '    # presenter - host_share percent of hours, once the LoRA is trained and on\n'
     '    if comfy_workshop.cast_applies("text"):\n'
     '        try:\n'
     '            host_share = max(0, min(100, int(state.get("host_share", 0) or 0)))\n'
     '        except (TypeError, ValueError):\n'
     '            host_share = 0\n'
     '        _h3_host_hit = bool(host_share) and s3_chance(\n'
     '            "h3.hourly_host", host_share / 100.0,\n'
     '            "whether the host\'s cast LoRA presents this hourly H3 stinger (host_share percent of hours)",\n'
     '            dial="host_share (the H3 door\'s own dial)")                      # [s3-visuals]\n'
     '        if host_share:\n'
     '            h3_hourly_roll_note("host", "h3.hourly_host")\n'
     '        if _h3_host_hit:\n'
     '            h3_hourly_rolls_bind(goal)                                       # [s3-visuals]\n'
     '            payload = {"mode": "text", "purpose": "parody_stinger", "source": "", "source_type": "",\n'
     '                       "speech": voice_ad_spoken_copy(goal),\n'
     '                       "prompt": ("The Pine Box host presents a Pine Box FM stinger at the station\'s desk, "\n'
     '                                  "direct to camera, in warm late-night studio light. " + goal),\n'
     '                       "duration_mode": "at_least", "air_it": False, "hourly": True}\n'
     '            queued = _parody_stinger_queue().add(payload)\n'
     '            _parody_stinger_wake.set()\n'
     '            return ("queued a host stinger (the cast LoRA, %s)" % comfy_workshop.CAST.get("lora"), queued, "host")\n'
     '    _h3_gallery = False\n'
     '    if share:\n'
     "        # [s3-visuals] which source road this hour takes is System 3's pick\n"
     '        # from the tabled pool (POOLS1 h3.hourly_source - the desk can retire\n'
     "        # a road), weighted by the operator's own gallery_share dial: the\n"
     '        # same share/100 odds randint(1, 100) <= share always rolled.\n'
     '        _h3_srcs = ["gallery picture", "dialogue clip"]\n'
     '        _h3_pool = [s for s in (s3_pool("h3.hourly_source", _h3_srcs, H3_HOURLY_SOURCE_LABEL) or _h3_srcs)\n'
     '                    if s in _h3_srcs] or _h3_srcs\n'
     '        _h3_w = {"gallery picture": float(share), "dialogue clip": float(100 - share)}\n'
     '        _h3_k = s3_weighted("h3.hourly_source", _h3_pool, [_h3_w[s] for s in _h3_pool], H3_HOURLY_SOURCE_LABEL)\n'
     '        _h3_gallery = _h3_pool[_h3_k if isinstance(_h3_k, int) and 0 <= _h3_k < len(_h3_pool) else 0] == "gallery picture"\n'
     '        h3_hourly_roll_note("source", "h3.hourly_source")\n'
     '    if _h3_gallery:\n'
     '        try:\n'
     '            # [h3-fresh] every picture on the wall, not only the last thirty renders\n'
     '            images = [p.name for p in await asyncio.to_thread(gallery_files, 600)\n'
     '                      if re.search(r"\\.(png|jpe?g|webp)$", p.name, re.I) and not gallery_paper_file(p.name)]\n'
     '        except Exception:  # noqa: BLE001\n'
     '            images = []\n'
     '        file = (await asyncio.to_thread(h3_hourly_fresh_image, images)) if images else ""\n'
     '        if file:\n'
     '            h3_hourly_roll_note("fresh", "h3.hourly_fresh", rec=h3_hourly_fresh_roll())   # [s3-visuals]\n'
     '            h3_hourly_rolls_bind(goal)\n'
     '            payload = {"mode": "reference", "purpose": "parody_stinger", "source": file,\n'
     '                       "source_type": "gallery", "speech": voice_ad_spoken_copy(goal),\n'
     '                       "prompt": "Create a Pine Box FM stinger using the supplied image. Natural motion and "\n'
     '                                 "synchronized spoken dialogue. No captions or logos. " + goal,\n'
     '                       "duration_mode": "at_least", "steps": 4, "air_it": False, "hourly": True}\n'
     '            queued = _parody_stinger_queue().add(payload)\n'
     '            _parody_stinger_wake.set()\n'
     '            return ("queued a gallery-image stinger from %s" % file, queued, "gallery image")\n'
     '    # [h3-fresh] a dialogue clip no hourly stinger has used, drawn at random,\n'
     '    # and a random ten-second window of it\n'
     '    fresh = await asyncio.to_thread(h3_hourly_fresh_clip)\n'
     '    if fresh.get("id"):\n'
     '        trim_in, trim_out = h3_hourly_window(fresh)\n'
     '        h3_hourly_roll_note("fresh", "h3.hourly_fresh", rec=h3_hourly_fresh_roll())       # [s3-visuals]\n'
     '        h3_hourly_roll_note("marker", "h3.hourly_marker")\n'
     '        h3_hourly_rolls_bind(goal)\n'
     '        message, job = await voice_ad_render(goal, reference_clip=fresh, hourly=True,\n'
     '                                             trim_in_s=trim_in, trim_out_s=trim_out)\n'
     '        return (message, job, "clip")\n'
     '    h3_hourly_roll_note("fresh", "h3.hourly_fresh", rec=h3_hourly_fresh_roll())          # [s3-visuals]\n'
     '    h3_hourly_rolls_bind(goal)\n'
     '    message, job = await voice_ad_render(goal, hourly=True)      # [h3-cinematic]\n'
     '    return (message, job, "clip")\n'
     '\n'
     '\n'
     '@app.get("/api/h3/hourly")\n'
     'async def h3_hourly_get(authorization: str | None = Header(default=None)) -> dict[str, Any]:\n'
     '    """[h3-hourly] The gallery\'s H3 meter and the Script view\'s hourly controls\n'
     '    read this: on/off, the source mix, the seconds to the next render."""\n'
     '    require_read_auth(authorization)\n'
     '    return h3_hourly_view()\n'
     '\n'
     '\n'
     "# --- [h3-cast] THE HOST'S FACE: THE TRAINER'S STATE AND ITS BUTTONS ------------\n"
     '#\n'
     '# tools/h3_cast_train.py - the pinebox-h3-cast service ON THE HOST, because the\n'
     '# trainer needs the GPU and the musubi-tuner venv the container has not - writes\n'
     "# data/h3_cast/status.json as it goes; the gallery's gear reads it through\n"
     '# /api/h3/hourly and presses train or stop here. The station only drops a\n'
     "# request file; the host's path unit starts the run, and the run's governor\n"
     '# pauses it whenever the box is hot, short of memory, or rendering.\n'
     '_H3_CAST_DIR = DATA_DIR / "h3_cast"\n'
     '_H3_CAST_BUSY = ("preparing", "portraits", "caching", "training", "paused", "installing", "testing")\n'
     '\n'
     '\n'
     'def h3_cast_status() -> dict[str, Any]:\n'
     '    """[h3-cast] Where the host\'s LoRA is: never trained, a run\'s stage and\n'
     '    step, or done with its file - and whether a request is waiting."""\n'
     '    waiting = (_H3_CAST_DIR / "kick.json").exists()\n'
     '    try:\n'
     '        got = json.loads((_H3_CAST_DIR / "status.json").read_text(encoding="utf-8"))\n'
     '        if isinstance(got, dict):\n'
     '            got["kick_waiting"] = waiting\n'
     '            return got\n'
     '    except FileNotFoundError:\n'
     '        pass\n'
     '    except Exception as exc:  # noqa: BLE001\n'
     '        return {"state": "unreadable", "why": type(exc).__name__, "kick_waiting": waiting}\n'
     '    return {"state": "never trained", "kick_waiting": waiting}\n'
     '\n'
     '\n'
     '@app.post("/api/h3/cast/train")\n'
     'async def h3_cast_train_api(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:\n'
     '    """[h3-cast] Ask the host to train (or retrain) the host\'s LoRA:\n'
     '    {look?: how the host looks, steps?: 100-2000, fresh?: new portraits}."""\n'
     '    require_auth(authorization)\n'
     '    try:\n'
     '        payload = await request.json()\n'
     '    except Exception:  # noqa: BLE001\n'
     '        payload = {}\n'
     '    payload = payload if isinstance(payload, dict) else {}\n'
     '    status = h3_cast_status()\n'
     '    if str(status.get("state") or "") in _H3_CAST_BUSY and time.time() - float(status.get("at") or 0) < 900:\n'
     '        raise HTTPException(status_code=409, detail="the host\'s LoRA is already training (%s)" % status.get("state"))\n'
     '    try:\n'
     '        steps = max(100, min(2000, int(payload.get("steps") or 600)))\n'
     '    except (TypeError, ValueError):\n'
     '        steps = 600\n'
     '    ask = {"at": time.time(), "look": " ".join(str(payload.get("look") or "").split())[:600],\n'
     '           "steps": steps, "fresh": bool(payload.get("fresh"))}\n'
     '    _H3_CAST_DIR.mkdir(parents=True, exist_ok=True)\n'
     '    tmp = _H3_CAST_DIR / "kick.json.tmp"\n'
     '    tmp.write_text(json.dumps(ask), encoding="utf-8")\n'
     '    tmp.replace(_H3_CAST_DIR / "kick.json")\n'
     '    pipeline_log("gpu", "the host\'s H3 LoRA was asked to train (%d steps%s)"\n'
     '                 % (steps, ", fresh portraits" if ask["fresh"] else ""))\n'
     '    return {"ok": True, "asked": ask, "status": h3_cast_status()}\n'
     '\n'
     '\n'
     '@app.post("/api/h3/cast/stop")\n'
     'async def h3_cast_stop_api(authorization: str | None = Header(default=None)) -> dict[str, Any]:\n'
     '    """[h3-cast] Stop a training run at its next step; it keeps its last save."""\n'
     '    require_auth(authorization)\n'
     '    _H3_CAST_DIR.mkdir(parents=True, exist_ok=True)\n'
     '    (_H3_CAST_DIR / "stop").write_text(str(time.time()), encoding="utf-8")\n'
     '    pipeline_log("gpu", "the host\'s H3 LoRA training was asked to stop")\n'
     '    return {"ok": True, "status": h3_cast_status()}\n'
     '\n'
     '\n'
     '@app.post("/api/h3/hourly")\n'
     'async def h3_hourly_set(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:\n'
     '    require_auth(authorization)\n'
     '    payload = await request.json()\n'
     '    if not isinstance(payload, dict):\n'
     '        raise HTTPException(status_code=400, detail="Expected an object")\n'
     '    state = h3_hourly_save({k: payload[k] for k in ("enabled", "gallery_share", "quality", "brief") if k in payload})\n'
     '    if "cast" in payload or "host_share" in payload:                      # [h3-cast]\n'
     '        state = h3_hourly_save({k: payload[k] for k in ("cast", "host_share") if k in payload})\n'
     '    pipeline_log("ads", "hourly H3 switch: %s, %d%% gallery images" %\n'
     '                 ("on" if state.get("enabled", True) is not False else "off", int(state.get("gallery_share", 20))))\n'
     '    return h3_hourly_view()\n'
     '\n'
     '\n'
     'async def h3_capacity_keeper() -> None:\n', 1),
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

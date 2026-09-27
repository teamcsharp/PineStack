"""[h3-cinematic][h3-cast] The station's side of the cinematic path and the
host's face.

  - the workshop door tells quality_for_box which road a render is on, so the
    hourly ad never takes the cinematic (base-model) path; voice_ad_render
    marks the hourly's clip ads the same way;
  - /api/h3/hourly carries the base path's step choices and heat line, the
    cast (the host's LoRA: on, file, trigger, strength), the trainer's status
    (data/h3_cast/status.json, written by tools/h3_cast_train.py on the host)
    and host_share - the share of hourly stingers the host presents on the
    text road with the LoRA on; POST takes cast and host_share;
  - POST /api/h3/cast/train and /api/h3/cast/stop drop a request file the
    host's pinebox-h3-cast path unit acts on (the container has neither the
    GPU trainer nor its venv).

--check exits 0 ready / 2 applied / 1 missing; --apply writes LF atomically.
ON THE HOST, from a fresh copy. Afterwards the older H3 tools whose blocks
this edits inside are re-anchored with tools/reconcile_patch_text.py.
"""
import os
import sys
import tempfile
from pathlib import Path

DOORS = r'''# --- [h3-cast] THE HOST'S FACE: THE TRAINER'S STATE AND ITS BUTTONS ------------
#
# tools/h3_cast_train.py - the pinebox-h3-cast service ON THE HOST, because the
# trainer needs the GPU and the musubi-tuner venv the container has not - writes
# data/h3_cast/status.json as it goes; the gallery's gear reads it through
# /api/h3/hourly and presses train or stop here. The station only drops a
# request file; the host's path unit starts the run, and the run's governor
# pauses it whenever the box is hot, short of memory, or rendering.
_H3_CAST_DIR = DATA_DIR / "h3_cast"
_H3_CAST_BUSY = ("preparing", "portraits", "caching", "training", "paused", "installing", "testing")


def h3_cast_status() -> dict[str, Any]:
    """[h3-cast] Where the host's LoRA is: never trained, a run's stage and
    step, or done with its file - and whether a request is waiting."""
    waiting = (_H3_CAST_DIR / "kick.json").exists()
    try:
        got = json.loads((_H3_CAST_DIR / "status.json").read_text(encoding="utf-8"))
        if isinstance(got, dict):
            got["kick_waiting"] = waiting
            return got
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001
        return {"state": "unreadable", "why": type(exc).__name__, "kick_waiting": waiting}
    return {"state": "never trained", "kick_waiting": waiting}


@app.post("/api/h3/cast/train")
async def h3_cast_train_api(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """[h3-cast] Ask the host to train (or retrain) the host's LoRA:
    {look?: how the host looks, steps?: 100-2000, fresh?: new portraits}."""
    require_auth(authorization)
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    status = h3_cast_status()
    if str(status.get("state") or "") in _H3_CAST_BUSY and time.time() - float(status.get("at") or 0) < 900:
        raise HTTPException(status_code=409, detail="the host's LoRA is already training (%s)" % status.get("state"))
    try:
        steps = max(100, min(2000, int(payload.get("steps") or 600)))
    except (TypeError, ValueError):
        steps = 600
    ask = {"at": time.time(), "look": " ".join(str(payload.get("look") or "").split())[:600],
           "steps": steps, "fresh": bool(payload.get("fresh"))}
    _H3_CAST_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _H3_CAST_DIR / "kick.json.tmp"
    tmp.write_text(json.dumps(ask), encoding="utf-8")
    tmp.replace(_H3_CAST_DIR / "kick.json")
    pipeline_log("gpu", "the host's H3 LoRA was asked to train (%d steps%s)"
                 % (steps, ", fresh portraits" if ask["fresh"] else ""))
    return {"ok": True, "asked": ask, "status": h3_cast_status()}


@app.post("/api/h3/cast/stop")
async def h3_cast_stop_api(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """[h3-cast] Stop a training run at its next step; it keeps its last save."""
    require_auth(authorization)
    _H3_CAST_DIR.mkdir(parents=True, exist_ok=True)
    (_H3_CAST_DIR / "stop").write_text(str(time.time()), encoding="utf-8")
    pipeline_log("gpu", "the host's H3 LoRA training was asked to stop")
    return {"ok": True, "status": h3_cast_status()}


'''

HOST_ROAD = r'''    # [h3-cast] the host's own hours: the text road with the cast LoRA on the
    # presenter - host_share percent of hours, once the LoRA is trained and on
    if comfy_workshop.cast_applies("text"):
        try:
            host_share = max(0, min(100, int(state.get("host_share", 0) or 0)))
        except (TypeError, ValueError):
            host_share = 0
        if host_share and random.randint(1, 100) <= host_share:
            payload = {"mode": "text", "purpose": "parody_stinger", "source": "", "source_type": "",
                       "speech": voice_ad_spoken_copy(goal),
                       "prompt": ("The Pine Box host presents a Pine Box FM stinger at the station's desk, "
                                  "direct to camera, in warm late-night studio light. " + goal),
                       "duration_mode": "at_least", "air_it": False, "hourly": True}
            queued = _parody_stinger_queue().add(payload)
            _parody_stinger_wake.set()
            return ("queued a host stinger (the cast LoRA, %s)" % comfy_workshop.CAST.get("lora"), queued, "host")
'''

EDITS = [
    ("the-workshop-door-names-its-road",
     '    _prof, _prof_note = comfy_workshop.quality_for_box(\n'
     '        box_hottest_c(), comfy_host_available_gb(), RENDER_TEMP_CEILING_C, VIDEO_RENDER_FLOOR_GB)\n',
     '    _prof, _prof_note = comfy_workshop.quality_for_box(\n'
     '        box_hottest_c(), comfy_host_available_gb(), RENDER_TEMP_CEILING_C, VIDEO_RENDER_FLOOR_GB,\n'
     '        purpose=("hourly" if payload.get("hourly") else purpose),       # [h3-cinematic]\n'
     '        frames=frame_count)                                              # [h3-budget]\n', 1),
    ("the-variant-door-fits-the-budget",
     '    _prof, _prof_note = comfy_workshop.quality_for_box(                  # [h3-quality]\n'
     '        box_hottest_c(), comfy_host_available_gb(), RENDER_TEMP_CEILING_C, VIDEO_RENDER_FLOOR_GB)\n',
     '    _prof, _prof_note = comfy_workshop.quality_for_box(                  # [h3-quality]\n'
     '        box_hottest_c(), comfy_host_available_gb(), RENDER_TEMP_CEILING_C, VIDEO_RENDER_FLOOR_GB,\n'
     '        frames=frames)                                                   # [h3-budget]\n', 1),
    ("h3-waits-while-the-host-trains",
     '    if kind == "video":\n'
     '        # Heat first: it is the reading that tracked the freezes.\n',
     '    if kind == "video":\n'
     '        # [h3-cast] the host\'s LoRA holds the box\'s memory while it trains\n'
     '        _cast = h3_cast_status()\n'
     '        if (str(_cast.get("state") or "") in ("caching", "training", "paused", "installing")\n'
     '                and time.time() - float(_cast.get("at") or 0) < 180):\n'
     '            return False, ("the host\'s H3 LoRA is training on this box and holds its memory; "\n'
     '                           "H3 waits until it finishes"), None\n'
     '        # Heat first: it is the reading that tracked the freezes.\n', 1),
    ("voice-ads-know-the-hourly",
     '    spoken_copy: str = "", trim_in_s: Any = None, trim_out_s: Any = None,\n'
     ') -> tuple[str, dict[str, Any]]:\n',
     '    spoken_copy: str = "", trim_in_s: Any = None, trim_out_s: Any = None,\n'
     '    hourly: bool = False,                                   # [h3-cinematic]\n'
     ') -> tuple[str, dict[str, Any]]:\n', 1),
    ("a-voice-ad-carries-the-mark",
     '            "speech": part["speech"], "purpose": "voice_ad",\n',
     '            "speech": part["speech"], "purpose": "voice_ad",\n'
     '            **({"hourly": True} if hourly else {}),          # [h3-cinematic] never the base path\n', 1),
    ("the-hourly-clip-ad-is-marked",
     '    message, job = await voice_ad_render(goal)\n'
     '    return (message, job, "clip")\n',
     '    message, job = await voice_ad_render(goal, hourly=True)      # [h3-cinematic]\n'
     '    return (message, job, "clip")\n', 1),
    ("the-host-has-hours",
     '    if share and random.randint(1, 100) <= share:\n',
     HOST_ROAD + '    if share and random.randint(1, 100) <= share:\n', 1),
    ("the-cast-loads-with-the-switch",
     '                                                    "last_source", "last_marker", "quality", "brief") if k in got})\n',
     '                                                    "last_source", "last_marker", "quality", "brief",\n'
     '                                                    "cast", "host_share") if k in got})   # [h3-cast]\n', 1),
    ("the-cast-is-in-force",
     '        state["brief"] = comfy_workshop.set_brief(state.get("brief"))           # [h3-brief-config]\n'
     '        _H3_HOURLY_STATE.update(state)\n',
     '        state["brief"] = comfy_workshop.set_brief(state.get("brief"))           # [h3-brief-config]\n'
     '        state["cast"] = comfy_workshop.set_cast(state.get("cast"))              # [h3-cast]\n'
     '        _H3_HOURLY_STATE.update(state)\n', 1),
    ("the-cast-saves-with-the-switch",
     '    if isinstance(patch.get("brief"), dict):                              # [h3-brief-config]\n'
     '        state["brief"] = comfy_workshop.set_brief(patch["brief"])\n',
     '    if isinstance(patch.get("brief"), dict):                              # [h3-brief-config]\n'
     '        state["brief"] = comfy_workshop.set_brief(patch["brief"])\n'
     '    if isinstance(patch.get("cast"), dict):                               # [h3-cast]\n'
     '        state["cast"] = comfy_workshop.set_cast(patch["cast"])\n'
     '    if "host_share" in patch:\n'
     '        try:\n'
     '            state["host_share"] = max(0, min(100, int(round(float(patch["host_share"])))))\n'
     '        except (TypeError, ValueError):\n'
     '            pass\n', 1),
    ("the-door-takes-the-cast",
     '    state = h3_hourly_save({k: payload[k] for k in ("enabled", "gallery_share", "quality", "brief") if k in payload})\n',
     '    state = h3_hourly_save({k: payload[k] for k in ("enabled", "gallery_share", "quality", "brief") if k in payload})\n'
     '    if "cast" in payload or "host_share" in payload:                      # [h3-cast]\n'
     '        state = h3_hourly_save({k: payload[k] for k in ("cast", "host_share") if k in payload})\n', 1),
    ("the-door-shows-the-cast",
     '            "frame_choices": list(comfy_workshop.FRAME_CHOICES),\n',
     '            "frame_choices": list(comfy_workshop.FRAME_CHOICES),\n'
     '            # [h3-cinematic] the base path\'s steps and heat line; [h3-cast] the host\'s LoRA\n'
     '            "base_step_choices": list(comfy_workshop.BASE_STEP_CHOICES),\n'
     '            "cinematic_heat_c": comfy_workshop.CINEMATIC_HEAT_C,\n'
     '            "cast": dict(comfy_workshop.CAST), "cast_status": h3_cast_status(),\n'
     '            "host_share": int(state.get("host_share", 0) or 0),\n'
     '            # [h3-budget] what each preset costs on this box for ten and five seconds\n'
     '            "estimates": comfy_workshop.estimates(243), "estimates_5s": comfy_workshop.estimates(124),\n'
     '            "budget_choices": list(comfy_workshop.BUDGET_CHOICES),\n', 1),
    ("the-cast-doors",
     '@app.post("/api/h3/hourly")\n',
     DOORS + '@app.post("/api/h3/hourly")\n', 1),
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

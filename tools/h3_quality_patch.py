"""H3's quality profile on the hourly door and in every render ([h3-quality]).

"for H3, double the quality settings. Also expose the quality settings for
H3 in the pine box gallery when i click the settings. I want to double the
quality and resolution at the moment unless it chokes the DGX to death."

The profile lives in comfy_workshop (PRESETS, QUALITY, set_quality,
quality_for_box) and is kept with the hourly switch in data/h3_hourly.json.
GET /api/h3/hourly carries `quality`, `presets` and the box's readings; POST
takes `quality`. Both H3 render roads (the workshop door and the parody
worker) render at the profile - stepped down for a hot or full box - and a
caller's `steps` only counts as `steps_override`, because every client
hardcoded the old default of four.

--check exits 0 ready / 2 applied / 1 missing; --apply writes LF atomically.
ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("profile-loads-with-the-switch",
     '        state: dict[str, Any] = {"enabled": True, "gallery_share": 20}\n'
     '        try:\n'
     '            got = json.loads(_H3_HOURLY_FILE.read_text(encoding="utf-8"))\n'
     '            if isinstance(got, dict):\n'
     '                state.update({k: got[k] for k in ("enabled", "gallery_share", "last_at", "last_message",\n'
     '                                                    "last_source", "last_marker") if k in got})\n'
     '        except FileNotFoundError:\n'
     '            pass\n'
     '        except Exception as exc:  # noqa: BLE001\n'
     '            pipeline_log("ads", "hourly H3 switch unreadable: %s" % type(exc).__name__)\n'
     '        _H3_HOURLY_STATE.update(state)\n',
     '        state: dict[str, Any] = {"enabled": True, "gallery_share": 20,\n'
     '                                 "quality": dict(comfy_workshop.QUALITY),        # [h3-quality]\n'
     '                                 "brief": dict(comfy_workshop.BRIEF)}            # [h3-brief-config]\n'
     '        try:\n'
     '            got = json.loads(_H3_HOURLY_FILE.read_text(encoding="utf-8"))\n'
     '            if isinstance(got, dict):\n'
     '                state.update({k: got[k] for k in ("enabled", "gallery_share", "last_at", "last_message",\n'
     '                                                    "last_source", "last_marker", "quality", "brief") if k in got})\n'
     '        except FileNotFoundError:\n'
     '            pass\n'
     '        except Exception as exc:  # noqa: BLE001\n'
     '            pipeline_log("ads", "hourly H3 switch unreadable: %s" % type(exc).__name__)\n'
     '        state["quality"] = comfy_workshop.set_quality(state.get("quality"))     # [h3-quality] in force\n'
     '        state["brief"] = comfy_workshop.set_brief(state.get("brief"))           # [h3-brief-config]\n'
     '        _H3_HOURLY_STATE.update(state)\n', 1),
    ("profile-saves-with-the-switch",
     '    for key in ("last_at", "last_message", "last_source", "last_marker"):\n'
     '        if key in patch:\n'
     '            state[key] = patch[key]\n',
     '    for key in ("last_at", "last_message", "last_source", "last_marker"):\n'
     '        if key in patch:\n'
     '            state[key] = patch[key]\n'
     '    if isinstance(patch.get("quality"), dict):                            # [h3-quality]\n'
     '        state["quality"] = comfy_workshop.set_quality(patch["quality"])\n', 1),
    ("the-door-shows-the-profile-and-the-box",
     '            "last_at": state.get("last_at"), "last_message": state.get("last_message"),\n'
     '            "last_source": state.get("last_source")}\n',
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
     '            "box": {"hottest_c": box_hottest_c(), "available_gb": comfy_host_available_gb(),\n'
     '                    "ceiling_c": RENDER_TEMP_CEILING_C, "floor_gb": VIDEO_RENDER_FLOOR_GB}}\n', 1),
    ("the-door-takes-the-profile",
     '    state = h3_hourly_save({k: payload[k] for k in ("enabled", "gallery_share") if k in payload})\n',
     '    state = h3_hourly_save({k: payload[k] for k in ("enabled", "gallery_share", "quality", "brief") if k in payload})\n', 1),
    ("the-workshop-door-renders-at-the-profile",
     '    step_count = comfy_workshop.clamp_steps(payload.get("steps"))\n'
     '    noise_seed = comfy_workshop.render_seed(payload.get("seed"))\n',
     '    # [h3-quality] the profile the box can take now; a caller\'s steps count\n'
     '    # only as steps_override (every client hardcoded the old default of four)\n'
     '    _prof, _prof_note = comfy_workshop.quality_for_box(\n'
     '        box_hottest_c(), comfy_host_available_gb(), RENDER_TEMP_CEILING_C, VIDEO_RENDER_FLOOR_GB)\n'
     '    if _prof_note:\n'
     '        pipeline_log("gpu", "H3 quality " + _prof_note)\n'
     '    step_count = (comfy_workshop.clamp_steps(payload.get("steps_override"))\n'
     '                  if payload.get("steps_override") is not None else int(_prof["steps"]))\n'
     '    noise_seed = comfy_workshop.render_seed(payload.get("seed"))\n', 1),
    ("the-workshop-door-builds-at-the-profile",
     '            media_kind=media_kind, frames=frame_count,\n'
     '            steps=step_count, seed=noise_seed)\n',
     '            media_kind=media_kind, frames=frame_count,\n'
     '            steps=step_count, seed=noise_seed,\n'
     '            width=_prof["width"], height=_prof["height"], max_frames=_prof["max_frames"])   # [h3-quality]\n', 1),
    ("the-workshop-door-records-the-profile",
     '                      "frames": frame_count, "steps": step_count,\n',
     '                      "frames": frame_count, "steps": step_count,\n'
     '                      "quality": _prof["preset"], "size": "%dx%d" % (_prof["width"], _prof["height"]),   # [h3-quality]\n', 1),
    ("the-parody-worker-renders-at-the-profile",
     '    steps = comfy_workshop.clamp_steps(\n'
     '        payload.get("steps", parent.get("steps")))\n'
     '    seed = comfy_workshop.render_seed(payload.get("seed"))\n',
     '    _prof, _prof_note = comfy_workshop.quality_for_box(                  # [h3-quality]\n'
     '        box_hottest_c(), comfy_host_available_gb(), RENDER_TEMP_CEILING_C, VIDEO_RENDER_FLOOR_GB)\n'
     '    if _prof_note:\n'
     '        pipeline_log("gpu", "H3 quality " + _prof_note)\n'
     '    steps = (comfy_workshop.clamp_steps(payload.get("steps_override"))\n'
     '             if payload.get("steps_override") is not None else int(_prof["steps"]))\n'
     '    seed = comfy_workshop.render_seed(payload.get("seed"))\n', 1),
    ("the-parody-worker-builds-at-the-profile",
     '            media_kind=media_kind, frames=frames, steps=steps, seed=seed)\n',
     '            media_kind=media_kind, frames=frames, steps=steps, seed=seed,\n'
     '            width=_prof["width"], height=_prof["height"], max_frames=_prof["max_frames"])   # [h3-quality]\n', 1),
    ("the-parody-worker-records-the-profile",
     '                      "frames": frames, "steps": steps, "seed": seed,\n',
     '                      "frames": frames, "steps": steps, "seed": seed,\n'
     '                      "quality": _prof["preset"], "size": "%dx%d" % (_prof["width"], _prof["height"]),   # [h3-quality]\n', 1),
    ("the-profile-is-in-force-before-the-first-render",
     '    fire_and_forget(h3_hourly_ad_clock())\n'
     '    fire_and_forget(h3_capacity_keeper())\n',
     '    h3_hourly_load()                        # [h3-quality] the profile in force before the first render\n'
     '    fire_and_forget(h3_hourly_ad_clock())\n'
     '    fire_and_forget(h3_capacity_keeper())\n', 1),
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

"""The brief's knobs ride the hourly door ([h3-brief-config]).

"Also want the configuration for these to be added to the H3 Pine box menu
so that I can utilize them in prompts and to expand on how I'm prompting."
The BRIEF profile (comfy_workshop: style term, shots follow the reference,
shot count, constraints, audio direction) is kept in data/h3_hourly.json
beside the quality profile; GET /api/h3/hourly carries `brief` and its
choices, POST takes `brief`.

--check exits 0 ready / 2 applied / 1 missing; --apply writes LF atomically.
ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("the-brief-loads-with-the-switch",
     '        state: dict[str, Any] = {"enabled": True, "gallery_share": 20,\n'
     '                                 "quality": dict(comfy_workshop.QUALITY)}        # [h3-quality]\n',
     '        state: dict[str, Any] = {"enabled": True, "gallery_share": 20,\n'
     '                                 "quality": dict(comfy_workshop.QUALITY),        # [h3-quality]\n'
     '                                 "brief": dict(comfy_workshop.BRIEF)}            # [h3-brief-config]\n', 1),
    ("the-brief-is-read-back",
     '                                                    "last_source", "last_marker", "quality") if k in got})\n',
     '                                                    "last_source", "last_marker", "quality", "brief",\n'
     '                                                    "cast", "host_share") if k in got})   # [h3-cast]\n', 1),
    ("the-brief-is-in-force-on-load",
     '        state["quality"] = comfy_workshop.set_quality(state.get("quality"))     # [h3-quality] in force\n',
     '        state["quality"] = comfy_workshop.set_quality(state.get("quality"))     # [h3-quality] in force\n'
     '        state["brief"] = comfy_workshop.set_brief(state.get("brief"))           # [h3-brief-config]\n', 1),
    ("the-brief-saves-with-the-switch",
     '    if isinstance(patch.get("quality"), dict):                            # [h3-quality]\n'
     '        state["quality"] = comfy_workshop.set_quality(patch["quality"])\n',
     '    if isinstance(patch.get("quality"), dict):                            # [h3-quality]\n'
     '        state["quality"] = comfy_workshop.set_quality(patch["quality"])\n'
     '    if isinstance(patch.get("brief"), dict):                              # [h3-brief-config]\n'
     '        state["brief"] = comfy_workshop.set_brief(patch["brief"])\n', 1),
    ("the-door-shows-the-brief",
     '            "step_choices": list(comfy_workshop.STEP_CHOICES),\n',
     '            "step_choices": list(comfy_workshop.STEP_CHOICES),\n'
     '            # [h3-brief-config] the brief\'s knobs and their choices\n'
     '            "brief": dict(comfy_workshop.BRIEF), "brief_defaults": dict(comfy_workshop.BRIEF_DEFAULTS),\n'
     '            "follow_choices": list(comfy_workshop.FOLLOW_CHOICES), "shot_choices": list(comfy_workshop.SHOT_CHOICES),\n'
     '            "sampler_choices": list(comfy_workshop.SAMPLER_CHOICES), "scheduler_choices": list(comfy_workshop.SCHEDULER_CHOICES),\n'
     '            "default_constraints": comfy_workshop.DEFAULT_CONSTRAINTS, "default_audio": comfy_workshop.DEFAULT_AUDIO,\n', 1),
    ("the-door-takes-the-brief",
     '    state = h3_hourly_save({k: payload[k] for k in ("enabled", "gallery_share", "quality") if k in payload})\n',
     '    state = h3_hourly_save({k: payload[k] for k in ("enabled", "gallery_share", "quality", "brief") if k in payload})\n', 1),
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

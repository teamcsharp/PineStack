"""The workshop door tells the prompt compiler how long the clip is
([h3-free-wins]), so the brief carries timecoded shots.

--check exits 0 ready / 2 applied / 1 missing; --apply writes LF atomically.
ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("timed-shots-in-the-brief",
     '    final_prompt = comfy_workshop.compose_prompt(\n'
     '        prompt, speech, media_kind, mode)\n',
     '    final_prompt = comfy_workshop.compose_prompt(\n'
     '        prompt, speech, media_kind, mode, seconds=frame_count / 24.0)   # [h3-free-wins] timed shots\n', 1),
    ("style-per-road",
     '        prompt, speech, media_kind, mode, seconds=frame_count / 24.0)   # [h3-free-wins] timed shots\n',
     '        prompt, speech, media_kind, mode, seconds=frame_count / 24.0,   # [h3-free-wins] timed shots\n'
     '        purpose=purpose, style=payload.get("style"))                   # [h3-brief] one style term per road\n', 1),
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
    """The edits are a chain: later edits consume the earlier ones' text, so
    an earlier edit counts as applied when any later edit's text is present."""
    applied, missing = 0, []
    edits = plan(text)
    for i, (name, old, new, count) in enumerate(edits):
        state = state_of(text, old, new, count)
        if state != "applied" and any(text.count(later[2]) >= 1 for later in edits[i + 1:]):
            state = "applied"
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
    edits = plan(text)
    for i, (name, old, new, count) in enumerate(edits):
        if state_of(text, old, new, count) == "applied" or any(text.count(later[2]) >= 1 for later in edits[i + 1:]):
            continue
        if text.count(old) == count:
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

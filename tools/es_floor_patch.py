"""[es-floor] The emotion engine's calibrated audibility floor, layered on
tools/es_roads_patch.py.

THE CAUSE. system3.voice_intent scales an ES row's voice block by the turn's
intensity, s = 0.35 + 0.65 i. es_probe --dsp at the live intensities (p10 0.3,
median 0.55, p90 0.77; es_coverage over the last 400 aired lines) measured the
high-arousal categories and interest/social under the listener's threshold:
at 0.55 joy +3.3 % rate and +0.67 dB brightness, surprise +1.3 % and +0.69 dB,
interest +0.10 st, +2.7 %, +0.27 dB; social -0.15 st, -3.5 %, -0.95 dB. The
engine was working and could not be heard.

THE CURE. A per-key minimum audible step, in voice_intent (the one place a row
becomes a turn's voice), for tempo 0.05, pitch 0.8 st, energy 0.25 (1.25 dB of
tilt) and pause 0.08:
  - only a key the row moves at full strength (|full - neutral| > 0.004);
  - its sign is kept;
  - its rise with intensity is kept: the step is floor + (full - floor) * i,
    so i = 0 is the floor and i = 1 is today's full send - and a value the old
    curve already made larger stays as it was;
  - never past the full send: a key whose whole send is under the floor gets
    its whole send at every intensity (the table's own ceiling).
range and temp are untouched. A block already stamped on a banked turn keeps
the numbers it was planned with; new turns get the floor.

Target: system3.py (relative to the repo root given, default "."). Needs
es_roads_patch applied first (it checks nothing of it, but it is one deploy set).
--check exits 0 ready / 2 applied / 1 missing. --apply is idempotent and atomic,
LF only. ON THE HOST.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

S3 = "system3.py"

EDITS = [
    (S3, "floor-const",
     'def voice_intent(block, intensity):\n',
     '# [es-floor] the smallest step a listener hears, per key, off neutral (es_probe\n'
     '# --dsp at the live intensities: under these the categories measured inaudible)\n'
     'ES_VOICE_FLOOR = {"tempo": 0.05, "pitch": 0.8, "energy": 0.25, "pause": 0.08}\n'
     'ES_VOICE_NEUTRAL = {"tempo": 1.0, "pitch": 0.0, "range": 1.0, "energy": 0.0, "pause": 1.0, "temp": 0.0}\n'
     '\n'
     '\n'
     'def voice_intent(block, intensity):\n', 1),
    (S3, "floor-apply",
     '    s = 0.35 + 0.65 * clamp(float(intensity or 0.0))\n'
     '    out = {}\n'
     '    for k, v in (clean_es_voice(block) or {}).items():\n'
     '        out[k] = round(v ** s if k in ES_VOICE_MULT else v * s, 4)\n'
     '    return out\n',
     '    i = clamp(float(intensity or 0.0))\n'
     '    s = 0.35 + 0.65 * i\n'
     '    out = {}\n'
     '    for k, v in (clean_es_voice(block) or {}).items():\n'
     '        out[k] = round(v ** s if k in ES_VOICE_MULT else v * s, 4)\n'
     '        # [es-floor] a key the row moves is heard: at least floor + (full - floor) i\n'
     '        # off neutral, its sign kept, never past the full send (i = 1, as before)\n'
     '        n, step = ES_VOICE_NEUTRAL[k], ES_VOICE_FLOOR.get(k)\n'
     '        full = abs(v - n)\n'
     '        if step is None or full <= 0.004:\n'
     '            continue\n'
     '        want = min(full, max(abs(out[k] - n), step + (full - step) * i))\n'
     '        out[k] = round(n + (want if v > n else -want), 4)\n'
     '    return out\n', 1),
]


def plan(files):
    return list(EDITS)


def state_of(text, old, new, count):
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_new == count and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def read(root, rel):
    return (Path(root) / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


def check(root):
    texts = {rel: read(root, rel) for rel in {e[0] for e in EDITS}}
    applied, missing = 0, []
    for rel, name, old, new, count in EDITS:
        state = state_of(texts[rel], old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s:%s (%s)" % (rel, name, state))
    return applied, missing, texts


def apply(root):
    applied, missing, texts = check(root)
    if applied == len(EDITS):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for rel, name, old, new, count in EDITS:
        if state_of(texts[rel], old, new, count) == "applied":
            continue
        assert texts[rel].count(old) == count, "%s: anchor found %d times" % (name, texts[rel].count(old))
        texts[rel] = texts[rel].replace(old, new)
    for rel, text in texts.items():            # every file's edits verified above: write all
        assert "\r" not in text
        path = Path(root) / rel
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        with os.fdopen(fd, "wb") as fh:
            fh.write(text.encode("utf-8"))
        try:
            shutil.copymode(str(path), tmp)
        except OSError:
            pass
        os.replace(tmp, path)
    return 0


def main(argv):
    do_apply = "--apply" in argv
    root = next((a for a in argv if not a.startswith("--")), ".")
    if do_apply:
        code = apply(root)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    applied, missing, _texts = check(root)
    if missing:
        for m in missing:
            print("missing:", m)
        print("%d of %d applied" % (applied, len(EDITS)))
        return 1
    if applied == len(EDITS):
        print("already applied (%d edits)" % len(EDITS))
        return 2
    print("ready: %d edits, %d already in" % (len(EDITS), applied))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

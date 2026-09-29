"""[plresume] A record a live set cut resumes where it was cut (app.py).

TARGET: app.py

Operator's original ask for MX Live: "music pauses". [plhold] (pinelive.py)
re-queued the interrupted record at the head of the queue, but it restarted
from the top. tools/plresume_pinelive_patch.py now stores the cut position on
the re-queued entry as `resume_s`; this tool makes the station honour it:

  1. dj_on_air() pops `resume_s` and back-dates _RADIO["started"] by it (and
     marks the track `resumed_from_s`). Every road that follows `started`
     then resumes by itself: the stream's _Decoder (offset = now - started),
     the served panel's djResync follower and the tune page's retime()
     (target = server_ms - started_ms), the tablet's PineListenModel
     playhead, /api/radio state `elapsed`. Popped, so it resumes ONCE.
  2. The fast_skip wait (the road a set hands the air back on) waits only
     what is left of a resumed record, not its whole length.
  3. The talk path's "wait for what is left" subtraction also runs for a
     resumed record when Records-first is off.
  4. The Nabu box road is dispatched with resume=True for a resumed record,
     so _nabu_music_dispatch() renders it from the same offset.

  python tools/plresume_app_patch.py [--check] app.py
  python tools/plresume_app_patch.py --apply app.py

--check exits 0 ready, 2 applied, 1 anchors missing. --apply is idempotent,
atomic and LF-only.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("on_air_backdate",
     '    _RADIO["now"] = track\n'
     '    _RADIO["started"] = time.time()\n'
     '    _RADIO["coming"] = None\n',
     '    _RADIO["now"] = track\n'
     '    _RADIO["started"] = time.time()\n'
     '    # [plresume] a record a live set cut comes back WHERE IT WAS CUT:\n'
     '    # `started` is back-dated by its position, so the loop waits only what\n'
     '    # is left and every road that follows `started` (the stream decoder,\n'
     '    # the panel and tablet followers, the Nabu resume) seeks there. Popped,\n'
     '    # so it resumes once; a record with under 5 s left plays from the top.\n'
     '    try:\n'
     '        _resume = float(track.pop("resume_s", 0) or 0)\n'
     '        _len = float(track.get("seconds") or 0)\n'
     '        if _resume > 0 and (not _len or _resume < _len - 5.0):\n'
     '            _RADIO["started"] -= _resume\n'
     '            track["resumed_from_s"] = round(_resume, 1)\n'
     '        else:\n'
     '            track.pop("resumed_from_s", None)\n'
     '    except (TypeError, ValueError, AttributeError):\n'
     '        pass\n'
     '    _RADIO["coming"] = None\n', 1),
    ("fast_skip_left",
     '                length = max(20.0, float(track.get("seconds") or 210))\n'
     '                try:\n'
     '                    await asyncio.wait_for(skip.wait(), timeout=length + 1.5)\n',
     '                length = max(20.0, float(track.get("seconds") or 210))\n'
     '                if track.get("resumed_from_s"):          # [plresume] what is left\n'
     '                    length = max(0.0, length - max(0.0, time.time() - float(\n'
     '                        _RADIO.get("started") or time.time())))\n'
     '                try:\n'
     '                    await asyncio.wait_for(skip.wait(), timeout=length + 1.5)\n', 1),
    ("talk_path_left",
     '            if spin_first:\n'
     '                spent = max(0.0, time.time()\n',
     '            if spin_first or track.get("resumed_from_s"):   # [plresume]\n'
     '                spent = max(0.0, time.time()\n', 1),
    ("nabu_resume",
     '        fire_and_forget_speech(_nabu_music_dispatch(dict(track), _NABU_MUSIC_EPOCH[0],\n'
     '            expected_started=float(_RADIO.get("started") or 0)))\n',
     '        fire_and_forget_speech(_nabu_music_dispatch(dict(track), _NABU_MUSIC_EPOCH[0],\n'
     '            resume=bool(track.get("resumed_from_s")),   # [plresume]\n'
     '            expected_started=float(_RADIO.get("started") or 0)))\n', 1),
]


def plan(text):
    return list(EDITS)


def state_of(text, old, new, count):
    n_new = text.count(new)
    n_old = text.count(old)
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
    edits = plan(text)
    if applied == len(edits):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for name, old, new, count in edits:
        if state_of(text, old, new, count) == "applied":
            continue
        assert text.count(old) == count, "%s: anchor found %d times" % (name, text.count(old))
        text = text.replace(old, new)
    assert "\r" not in text
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
    target = next((a for a in argv if not a.startswith("--")), "app.py")
    if do_apply:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    total = len(plan(text))
    if missing:
        for m in missing:
            print("missing:", m)
        print("%d of %d applied" % (applied, total))
        return 1
    if applied == total:
        print("already applied (%d edits)" % total)
        return 2
    print("ready: %d edits, %d already in" % (total, applied))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

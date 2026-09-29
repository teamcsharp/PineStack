"""[plresume] A record a live set cut resumes where it was cut (pinelive.py).

TARGET: pinelive.py

[plhold] in _take_air() re-queued the interrupted record "only if it had
barely started (it restarts from the top)". Two things were wrong with that:
the operator's ask was "music pauses", and the test read now_track["started"],
a key the station's track dicts never carry (dj_on_air() stamps
_RADIO["started"]), so `_in` was always 0 and every cut record came back from
the top whatever it had played.

Now the position is read from _RADIO["started"], and the re-queued entry is a
COPY carrying `resume_s` (tools/plresume_app_patch.py makes dj_on_air()
back-date `started` by it, so every road resumes there). A record with under
20 s left is not owed and is not re-queued. [plhold]'s never-twice-in-an-hour
memo is kept exactly.

  python tools/plresume_pinelive_patch.py [--check] pinelive.py
  python tools/plresume_pinelive_patch.py --apply pinelive.py

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
    ("plhold_resume",
     '                # [plhold] a cut record comes back only if it had barely started\n'
     '                # (it restarts from the top) and never twice in an hour: every\n'
     '                # handoff used to re-queue it, so a flapping input or two tests\n'
     '                # aired the same record from the top again and again.\n'
     '                _t = time.time()\n'
     '                _in = _t - float(now_track.get("started") or _t)\n'
     '                _memo = {k: v for k, v in getattr(self, "_held_memo", {}).items()\n'
     '                         if _t - v < 3600.0}\n'
     '                if _in < 60.0 and str(now_track.get("id")) not in _memo:\n'
     '                    _memo[str(now_track.get("id"))] = _t\n'
     '                    held = str(now_track.get("title") or "the record")\n'
     '                    q = radio.setdefault("queue", [])\n'
     '                    if not q or (q[0] or {}).get("id") != now_track.get("id"):\n'
     '                        q.insert(0, now_track)\n',
     '                # [plhold] a cut record comes back never twice in an hour: every\n'
     '                # handoff used to re-queue it, so a flapping input or two tests\n'
     '                # aired the same record from the top again and again.\n'
     '                # [plresume] and it comes back WHERE IT WAS CUT ("music\n'
     '                # pauses"): the re-queued copy carries resume_s and dj_on_air\n'
     "                # back-dates `started` by it. The position is the station's own\n"
     '                # _RADIO["started"] (a track dict never carries "started", so\n'
     '                # the old test read 0 and every record restarted from the top).\n'
     '                # A record with under 20 s left is not owed.\n'
     '                _t = time.time()\n'
     '                _in = max(0.0, _t - float(radio.get("started") or _t))\n'
     '                try:\n'
     '                    _len = float(now_track.get("seconds") or 0)\n'
     '                except (TypeError, ValueError):\n'
     '                    _len = 0.0\n'
     '                _memo = {k: v for k, v in getattr(self, "_held_memo", {}).items()\n'
     '                         if _t - v < 3600.0}\n'
     '                if ((not _len or _in < _len - 20.0)\n'
     '                        and str(now_track.get("id")) not in _memo):\n'
     '                    _memo[str(now_track.get("id"))] = _t\n'
     '                    _back = {k: v for k, v in now_track.items() if k != "resumed_from_s"}\n'
     '                    _back["resume_s"] = round(_in, 1) if _in >= 3.0 else 0.0\n'
     '                    held = str(now_track.get("title") or "the record")\n'
     '                    if _back["resume_s"]:\n'
     '                        held += " (from %d:%02d)" % (int(_in) // 60, int(_in) % 60)\n'
     '                    q = radio.setdefault("queue", [])\n'
     '                    if q and (q[0] or {}).get("id") == now_track.get("id"):\n'
     '                        q[0] = _back\n'
     '                    else:\n'
     '                        q.insert(0, _back)\n', 1),
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
    target = next((a for a in argv if not a.startswith("--")), "pinelive.py")
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

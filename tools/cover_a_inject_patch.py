"""[s3-inject] app.py: the non-roulette air doors write the honest forced card
(GAP 8), and the Pine Cam registers its standing fixed-surface node (GAP 11).

The operator's decision (2026-09-28 total-coverage audit): FORCED INJECTORS =
honest forced-node cards - "forced: no roll - injected by <system> because
<reason>" - at their timeline injection point, never fake dice; fixed
surfaces (Pine Cam) = stamped standing nodes only.  The one shared door is
system3_runtime's namespace["system3_injected_node"] (edits/
edit_system3_runtime.py); this tool wires app.py's two doors and the camera:

  1. rescue-card     dead_air_rescue: a finished round forced out of turn
                     to fill silence writes the card before `return kind`.
  2. boot-card       page_recovery_start: the preserved FIFO republished
                     after a restart writes one card naming the count.
  3. cam-standing    _s3_cam_standing(): the rising edge of "the Pine Cam
                     is on the air" writes the standing node ("fixed
                     surface: ... no roll by design"), deduped by the
                     helper for half an hour.
  4. cam-look        pinelink_look_api computes that edge on every look.
  5. cam-onair       the on-air switch recomputes it at once.

No ?v= bump is needed: /system3/{name} already serves Cache-Control:
no-cache with an ETag (system3_runtime.py's asset route), so every open
revalidates the module.

Anchors verified unique in app.py at 05917b1 and absent from all 200
tools/*.py stored texts (collision scan 2026-09-28).  --check exits
0 ready / 2 applied / 1 missing.  --apply is idempotent, atomic, LF only.
Apply ON THE HOST, after edit_system3_runtime.py (order-independent in
fact: every call goes through globals().get).
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("rescue-card",
     '            pipeline_log("air", "SILENCE FILLED: %d line(s) of a ready %s "\n'
     '                                "round, off the shelf, out of turn - the "\n'
     '                                "cupboard is for exactly this"\n'
     '                         % (len(said), kind))\n'
     '            return kind\n',
     '            pipeline_log("air", "SILENCE FILLED: %d line(s) of a ready %s "\n'
     '                                "round, off the shelf, out of turn - the "\n'
     '                                "cupboard is for exactly this"\n'
     '                         % (len(said), kind))\n'
     '            # [s3-inject] the honest forced card, on the tree it joined:\n'
     '            # nothing rolled this round in - the silence did.\n'
     '            _inject = globals().get("system3_injected_node")\n'
     '            if callable(_inject):\n'
     '                _inject(by="the dead-air rescue",\n'
     '                        why=("the show ran out of things to say"\n'
     '                             if quiet <= 0 else\n'
     '                             "the room was quiet %d s" % int(quiet))\n'
     '                        + " - a finished %s round went out off the shelf, "\n'
     '                          "out of turn (%d line(s))" % (kind, len(said)),\n'
     '                        kind="rescue", at=now,\n'
     '                        extra={"road": kind, "lines": len(said)})\n'
     '            return kind\n', 1),
    ("boot-card",
     '            page_recovery_chat_rows(clip, delivery)\n'
     '        await _paged_settle(float(_PAGE_AIR_UNTIL[0] or 0))\n',
     '            page_recovery_chat_rows(clip, delivery)\n'
     '        # [s3-inject] the honest forced card: a restart, not a roll, put\n'
     '        # these back on the air.\n'
     '        _inject = globals().get("system3_injected_node")\n'
     '        if callable(_inject) and saved:\n'
     '            _inject(by="boot recovery",\n'
     '                    why="the restart cut the page feed - %d preserved "\n'
     '                        "deliver%s republished in the queued order"\n'
     '                        % (len(saved), "y" if len(saved) == 1 else "ies"),\n'
     '                    kind="boot",\n'
     '                    line_id=str((saved[0] or {}).get("row_id")\n'
     '                                or (saved[0] or {}).get("delivery_id") or ""),\n'
     '                    extra={"deliveries": len(saved)})\n'
     '        await _paged_settle(float(_PAGE_AIR_UNTIL[0] or 0))\n', 1),
    ("cam-standing",
     '@app.post("/api/pinelink/on-air")\n',
     '_PINELINK_S3_STAND = {"was": False}\n'
     '\n'
     '\n'
     'def _s3_cam_standing(on_now: bool) -> None:\n'
     '    """[s3-inject] GAP 11: the Pine Cam is a fixed surface - the moment it\n'
     '    (re)takes the air is a standing node on the executed tree, honest about\n'
     '    having no dice ("fixed surface ... no roll by design").  Only the\n'
     '    rising edge writes, and the shared helper rests a standing card half\n'
     '    an hour, so the pollers cost nothing.  Never raises."""\n'
     '    was = bool(_PINELINK_S3_STAND.get("was"))\n'
     '    _PINELINK_S3_STAND["was"] = bool(on_now)\n'
     '    if not on_now or was:\n'
     '        return\n'
     '    _inject = globals().get("system3_injected_node")\n'
     '    if callable(_inject):\n'
     '        try:\n'
     '            _inject(by="Pine Cam",\n'
     '                    why="fixed surface: Pine Cam, live camera - no roll by "\n'
     '                        "design; the live picture takes the gallery\'s place "\n'
     '                        "on the air while the link is up",\n'
     '                    kind="surface", standing=True)\n'
     '        except Exception:  # noqa: BLE001\n'
     '            pass\n'
     '\n'
     '\n'
     '@app.post("/api/pinelink/on-air")\n', 1),
    ("cam-look",
     '    linked = bool(got.get("state") == "live" and got.get("fresh"))\n',
     '    linked = bool(got.get("state") == "live" and got.get("fresh"))\n'
     '    _s3_cam_standing(bool(linked and pinelink_on_air()))   # [s3-inject] GAP 11\n', 1),
    ("cam-onair",
     '    return {"ok": True, "on_air": want,\n',
     '    try:\n'
     '        _got_cam = pinelink_state()\n'
     '        _s3_cam_standing(bool(want and _got_cam.get("state") == "live"\n'
     '                              and _got_cam.get("fresh")))   # [s3-inject] GAP 11\n'
     '    except Exception:  # noqa: BLE001\n'
     '        pass\n'
     '    return {"ok": True, "on_air": want,\n', 1),
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

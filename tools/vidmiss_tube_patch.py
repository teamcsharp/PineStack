"""[vidmiss] ONE TUBE: the SFX guy does not ring a picture on top of a picture.

Measured 2026-09-28 on the ring /api/dj/video serves (SFX guy at 100% MP4,
endless off): the station booked a sting's picture while the one before it
was still on the tube - a7ea05d7 2379.8-2395.8 with e05c955d at 2391.9;
c2d58d05 3045.3-3076.4 (31 s) with b667d23c at 3061.5. Every set holds ONE
picture at a time (sfx-tv.js next() refuses while `showing`), so the second
waits for the first and a sting that waits more than LATE (8 s) is thrown
away - picture AND sound, since on the page the MP4 carries its own audio.

Why the booking overlaps: page_feed_append reserves a sting's length on
_PAGE_AIR_UNTIL, but page_reservation_repair - which every append runs
first - rebuilds the cursor from the voice clips and skips every video row
(a picture must never be RE-TIMED: that is the double-play its comment
names). So the reservation is gone by the next append.

#1417 already answered this for the endless set, in the operator's words:
"don't have the SFX guy play a clip during a clip he is already playing.
Have him do it after." This carries that rule to every picture: a video
sting is stamped after the tube frees (the latest SFX picture on the ring
whose span has not run, sting or board clip, plus SFX_TUBE_GAP_S for the
set's collapse and start), and if the tube is booked more than
SFX_TUBE_WAIT_MOST past its natural moment he lets the slot go, as an
audio-only sting waits in endless mode. Nothing else is re-timed; speech
is untouched.

  sfx-tube-free   SFX_TUBE_GAP_S, SFX_TUBE_WAIT_MOST, sfx_tube_free_at()
                  beside sfx_video_share()
  sting-waits     dj_sting: after the endless block, the tube check
  sting-row       the booth row's air_at is the moment it will air
  sting-stamp     the page feed row carries that broadcast_ms
  sting-aired     the success stamp (#1288) is that moment too

Anchors cut from HEAD e6fdb8d, each unique; no other tool's stored text holds
them (content-grep of tools/). --check exits 0 ready / 2 applied / 1 anchors
missing; --apply is idempotent, asserts every anchor, writes LF atomically.
TARGET: app.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

EDITS = [
    ('sfx-tube-free',
     '\n\ndef sfx_video_share() -> int:\n',
     '\n\n'
     '# [vidmiss] ONE TUBE. Every set shows one picture at a time; a sting\'s\n'
     '# picture booked on top of another waits behind it and, past the set\'s\n'
     '# LATE (8 s), is thrown away with its sound. GAP: the set\'s CRT collapse\n'
     '# (0.64 s) and the tablet\'s measured 1.5-2.5 s from hand-over to picture.\n'
     'SFX_TUBE_GAP_S = float(os.getenv("SFX_TUBE_GAP_S", "1.0"))\n'
     'SFX_TUBE_WAIT_MOST = float(os.getenv("SFX_TUBE_WAIT_MOST", "20.0"))\n'
     '\n'
     '\n'
     'def sfx_tube_free_at(now: float | None = None) -> float:\n'
     '    """[vidmiss] When the picture tube is free: the end of the latest SFX\n'
     '    picture on the ring (a sting\'s own MP4, a board clip\'s silent picture,\n'
     '    a pad\'s cut) whose span has not run out. 0.0 when nothing is on or\n'
     '    booked. The endless cycle keeps its own plan (#1417) and is not read.\n'
     '    A delivery the page reports ended, or refused, holds nothing."""\n'
     '    now = time.time() if now is None else float(now)\n'
     '    free = 0.0\n'
     '    cut_ms = int(_RADIO.get("voice_cut_ms") or 0)\n'
     '    for clip in list(_RADIO.get("voice_clips") or []):\n'
     '        if (not isinstance(clip, dict) or not clip.get("video")\n'
     '                or clip.get("endless")):\n'
     '            continue\n'
     '        try:\n'
     '            if cut_ms and clip.get("ts") and int(clip["ts"]) <= cut_ms:\n'
     '                continue\n'
     '            did = str(clip.get("delivery_id") or "")\n'
     '            if did and str((_PAGE_DELIVERIES.get(did) or {}).get("state")\n'
     '                           or "") in ("ended", "error"):\n'
     '                continue\n'
     '            start = float(clip.get("broadcast_ms") or 0) / 1000.0\n'
     '            span = float(clip.get("length") or clip.get("seconds") or 0)\n'
     '        except (TypeError, ValueError):\n'
     '            continue\n'
     '        if start > 0 and span > 0 and start + span > now:\n'
     '            free = max(free, start + span)\n'
     '    return free\n'
     '\n'
     '\n'
     'def sfx_video_share() -> int:\n',
     1),
    ('sting-waits',
     '        if time.time() < float(_SFX_CYCLE.get("until") or 0):\n'
     '            return ""\n'
     '    # The index already measured every playable clip.',
     '        if time.time() < float(_SFX_CYCLE.get("until") or 0):\n'
     '            return ""\n'
     '    # [vidmiss] ...AND OUTSIDE IT THE TUBE IS STILL ONE TUBE. A picture\n'
     '    # booked on top of the one showing waits behind it on every set and,\n'
     '    # past the set\'s LATE, is thrown away with its sound (measured\n'
     '    # 2026-09-28: c2d58d05 3045.3-3076.4 and b667d23c booked at 3061.5).\n'
     '    # So he does it after, as #1417 says; booked too far ahead, he lets the\n'
     '    # slot go rather than punctuate a line long gone.\n'
     '    _tube_at_ms = 0\n'
     '    if is_video:\n'
     '        try:\n'
     '            _tube_free = sfx_tube_free_at()\n'
     '            _tube_now = time.time() + VOICE_BROADCAST_LEAD_MS / 1000.0\n'
     '            _tube_natural = max(_tube_now, float(_PAGE_AIR_UNTIL[0] or 0))\n'
     '            _tube_want = _tube_free + SFX_TUBE_GAP_S if _tube_free else 0.0\n'
     '            if _tube_want > _tube_natural:\n'
     '                if _tube_want - _tube_natural > SFX_TUBE_WAIT_MOST:\n'
     '                    pipeline_log(\n'
     '                        "drop",\n'
     '                        "an SFX picture was not rung: the tube is booked "\n'
     '                        "%.0f s past its moment ([vidmiss])"\n'
     '                        % (_tube_want - _tube_natural),\n'
     '                        extra=str(sample)[:300])\n'
     '                    return ""\n'
     '                _tube_at_ms = int(_tube_want * 1000)\n'
     '        except Exception:  # noqa: BLE001 - the tube check never costs the sting\n'
     '            _tube_at_ms = 0\n'
     '    # The index already measured every playable clip.',
     1),
    ('sting-row',
     '        "ts": int(time.time()), "air_at": time.time(),\n'
     '        "who": "board", "kind": "sfx",\n'
     '        "text": sample.stem, "sfx": key,',
     '        "ts": int(time.time()),\n'
     '        "air_at": (_tube_at_ms / 1000.0 if _tube_at_ms   # [vidmiss]\n'
     '                   else time.time()),\n'
     '        "who": "board", "kind": "sfx",\n'
     '        "text": sample.stem, "sfx": key,',
     1),
    ('sting-stamp',
     '            "video": is_video,\n'
     '            "seconds": round(_sample_seconds, 2),\n'
     '        })',
     '            "video": is_video,\n'
     '            "seconds": round(_sample_seconds, 2),\n'
     '            # [vidmiss] after the picture already on the tube\n'
     '            **({"broadcast_ms": _tube_at_ms} if _tube_at_ms else {}),\n'
     '        })',
     1),
    ('sting-aired',
     '            _sting_row["aired"] = "box" if to_box else "page"\n'
     '            air_at_set(_sting_row, time.time())             # #1288\n',
     '            _sting_row["aired"] = "box" if to_box else "page"\n'
     '            air_at_set(_sting_row, max(time.time(),         # #1288\n'
     '                                       _tube_at_ms / 1000.0))   # [vidmiss]\n',
     1),
]


def plan(text):
    return EDITS


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

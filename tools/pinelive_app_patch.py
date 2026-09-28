"""[pinelive] MX Live wired into the station (app.py).

TARGET: app.py

pinelive.py holds the event; this tool gives it the station's own roads, and
nothing else - every road below is one the station already uses for a
record, taught that the record can be a live set:

  1. IMPORT + INSTALL. `import pinelive`, and pinelive.install(app,
     globals()) right after STATION_STREAM exists: the /api/pinelive/*
     routes (operator key; none of them on the listener door), the startup
     boot (a restart mid-set picks the event up), and the module's lazy view
     of this file's functions.
  2. THE SET IS THE RECORD. dj_next_track() answers pinelive.live_track()
     while the set has the air, so it goes on through dj_on_air like any
     record and every writer that reads "the record on air" sees it. Taking
     and giving back the air is fast_skip + dj_skip(), the resume needle's
     own lever; the interrupted record waits at the head of the queue.
  3. THE MIXER'S BED. _stream_snapshot() hands the mixer the live input and
     whether it has the air (the car stream, HLS, and the full-mix cuts).
  4. THE CLOCK. /api/radio/clock gains `live: true` for the live record (its
     url and art are already /music/<live id> - the record road) and a
     `pinelive` block; through the listener door the art is blanked while
     Tailscale video is off.
  5. THE RECORD ROAD. /music/<live id> is the input as an endless mp3 (the
     tablet's, the panel's and the tune page's record, and the monitor);
     /music/<live id>/art is the picture as a live MJPEG. Both keep the
     route's own shape check and signature.
  6. THE TAILSCALE-VIDEO SWITCH. pinelink_viewer_ok() and its five-second
     memo answer False while an event runs with tailscale_video off, so
     frame.jpg, the low lane and /api/pinelink/mine refuse every tune-in
     token at once. The house (no token) is untouched.
  7. THE PAGES NEVER SEEK A LIVE RECORD. The panel's djResync and the tune
     page's retime load a `live` record once and keep it playing; seeking an
     endless stream would re-request it every poll.

  python tools/pinelive_app_patch.py [--check] app.py
  python tools/pinelive_app_patch.py --apply app.py

--check exits 0 ready, 2 applied, 1 anchors missing. --apply is idempotent,
atomic and LF-only. Needs pinelive.py beside app.py and
tools/pinelive_stream_patch.py applied to station_stream.py (without it the
mixer has no tap: the cuts do not run and /api/pinelive/state says so).
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path


EDITS = [
    ("pl-import",
     'from station_stream import HLS_START_SEGMENTS, StationStream, icy_block\n',
     'from station_stream import HLS_START_SEGMENTS, StationStream, icy_block\n'
     'import pinelive                         # [pinelive] MX Live: the event, its roads, its doors\n', 1),

    ("pl-install",
     'STATION_STREAM = StationStream(_stream_snapshot, bitrate=STREAM_BITRATE)\n',
     'STATION_STREAM = StationStream(_stream_snapshot, bitrate=STREAM_BITRATE)\n'
     '# [pinelive] the /api/pinelive routes and the event\'s boot. Everything the\n'
     '# module needs from this file it looks up in globals() when it needs it.\n'
     'pinelive.install(app, globals())\n', 1),

    ("pl-snapshot",
     '        return {"on": bool(_RADIO.get("on")), "paused": radio_paused(),\n'
     '                "music": music, "clips": clips}\n',
     '        return {"on": bool(_RADIO.get("on")), "paused": radio_paused(),\n'
     '                "music": music, "clips": clips,\n'
     '                **pinelive.snapshot_extra()}     # [pinelive] the set, as the bed\n', 1),

    ("pl-next-track",
     '    air in dj_on_air, when the audio actually starts."""\n'
     '    dj = dj_settings()\n',
     '    air in dj_on_air, when the audio actually starts."""\n'
     '    # [pinelive] MX Live: while the set has the air, it IS the record.\n'
     '    _live_set = pinelive.live_track()\n'
     '    if _live_set:\n'
     '        return _live_set\n'
     '    dj = dj_settings()\n', 1),

    ("pl-clock",
     '        "audio_owner": "" if _away else audio_owner(),\n'
     '    }\n',
     '        "audio_owner": "" if _away else audio_owner(),\n'
     '        # [pinelive] `live` = play the url, never seek it; the picture, and\n'
     '        # through the door no art while Tailscale video is off.\n'
     '        **pinelive.clock_extra(track, _away),\n'
     '    }\n', 1),

    ("pl-music-route",
     '    type, nosniff, range support, signature or bearer."""\n'
     '    if not re.fullmatch(r"[a-f0-9]{16}", track_id):\n'
     '        return Response(status_code=404)\n'
     '\n'
     '    signature = media_sign(track_id)\n'
     '    if not (signature and hmac.compare_digest(\n'
     '            str(request.query_params.get("t") or ""), signature)):\n'
     '        require_auth(authorization)\n'
     '\n'
     '    track = music_track(track_id)\n',
     '    type, nosniff, range support, signature or bearer."""\n'
     '    if not re.fullmatch(r"[a-f0-9]{16}", track_id):\n'
     '        return Response(status_code=404)\n'
     '\n'
     '    signature = media_sign(track_id)\n'
     '    if not (signature and hmac.compare_digest(\n'
     '            str(request.query_params.get("t") or ""), signature)):\n'
     '        require_auth(authorization)\n'
     '\n'
     '    if pinelive.is_live_id(track_id):         # [pinelive] the live record\n'
     '        return await pinelive.music_response(track_id, request)\n'
     '\n'
     '    track = music_track(track_id)\n', 1),

    ("pl-art-route",
     '    draw its own placeholder rather than a broken image."""\n'
     '    if not re.fullmatch(r"[a-f0-9]{16}", track_id):\n'
     '        return Response(status_code=404)\n'
     '    signature = media_sign(track_id)\n'
     '    if not (signature and hmac.compare_digest(\n'
     '            str(request.query_params.get("t") or ""), signature)):\n'
     '        require_auth(authorization)\n',
     '    draw its own placeholder rather than a broken image."""\n'
     '    if not re.fullmatch(r"[a-f0-9]{16}", track_id):\n'
     '        return Response(status_code=404)\n'
     '    signature = media_sign(track_id)\n'
     '    if not (signature and hmac.compare_digest(\n'
     '            str(request.query_params.get("t") or ""), signature)):\n'
     '        require_auth(authorization)\n'
     '    if pinelive.is_live_id(track_id):         # [pinelive] the picture, live\n'
     '        return await pinelive.art_response(track_id, request)\n', 1),

    ("pl-viewer-gate",
     '    telling a viewer they may watch a thing that is not running.\n'
     '    """\n'
     '    mode = pinelink_public_mode()\n',
     '    telling a viewer they may watch a thing that is not running.\n'
     '    """\n'
     '    if pinelive.public_video_blocked():       # [pinelive] Tailscale video OFF\n'
     '        return False\n'
     '    mode = pinelink_public_mode()\n', 1),

    ("pl-low-gate",
     '    """#1475: pinelink_viewer_ok, memoised five seconds per token - a\n'
     '    player asks for a segment every two seconds."""\n'
     '    now = time.time()\n',
     '    """#1475: pinelink_viewer_ok, memoised five seconds per token - a\n'
     '    player asks for a segment every two seconds."""\n'
     '    if pinelive.public_video_blocked():       # [pinelive] before the memo: at once\n'
     '        return False\n'
     '    now = time.time()\n', 1),

    ("pl-panel-live",
     '  const age = djStateAt ? (Date.now() - djStateAt) / 1000 : 0;\n'
     '  let target = (clock.server_ms - clock.started_ms) / 1000 + age;\n',
     '  /* [pinelive] MX LIVE: the record is the live set - an endless stream\n'
     '   * with no position to keep. Load it once, keep it playing, never seek\n'
     '   * it (a seek on an endless stream re-requests it every poll). */\n'
     '  if (clock.live) {\n'
     '    if (clock.id !== djLastTrack || player.error) {\n'
     '      djLastTrack = clock.id;\n'
     '      djLastClockId = clock.id;\n'
     '      musicRadioOn = false;\n'
     '      radioFollowing = true;\n'
     '      player.src = clock.url;\n'
     '      player.playbackRate = 1;\n'
     '      playOrPrompt(player);\n'
     '      return;\n'
     '    }\n'
     '    radioFollowing = true;\n'
     '    if (player.paused && !player.ended) playOrPrompt(player);\n'
     '    if (player.playbackRate !== 1) player.playbackRate = 1;\n'
     '    return;\n'
     '  }\n'
     '  const age = djStateAt ? (Date.now() - djStateAt) / 1000 : 0;\n'
     '  let target = (clock.server_ms - clock.started_ms) / 1000 + age;\n', 1),

    ("pl-tune-retime",
     '  if (stationPaused) return;   // #1149: NO road restarts a paused record\n',
     '  if (stationPaused) return;   // #1149: NO road restarts a paused record\n'
     '  /* [pinelive] MX LIVE: a live record is played, never seeked. */\n'
     '  if (now.live) {\n'
     '    if (now.id !== trackId || audio.error) {\n'
     '      trackId = now.id;\n'
     '      trackUrl = now.url;\n'
     '      audio.src = now.url;\n'
     '      audio.playbackRate = 1;\n'
     '      audio.play().catch(() => {});\n'
     '      return;\n'
     '    }\n'
     '    if (audio.paused && !audio.ended) audio.play().catch(() => {});\n'
     '    if (audio.playbackRate !== 1) audio.playbackRate = 1;\n'
     '    return;\n'
     '  }\n', 1),

    ("pl-tune-call",
     '      retime({id: c.id, url: c.url}, c.server_ms, c.started_ms, c.seconds);\n',
     '      retime({id: c.id, url: c.url, live: !!c.live},   /* [pinelive] */\n'
     '             c.server_ms, c.started_ms, c.seconds);\n', 1),
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

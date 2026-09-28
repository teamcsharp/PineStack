"""[pinelive] MX Live in the station mixer (station_stream.py).

TARGET: station_stream.py

The mixer is where the station's full programme exists: records, DJs, SFX
and events, mixed once, at real time, for the car stream and every HLS lane.
MX Live needs three things from it, and this tool adds exactly those:

  1. A LIVE BED. The snapshot may carry `live` (an object with read_frame(),
     gain, duck_gain, duck_attack_ms, duck_release_ms) and `live_on_air`.
     The live frame is read EVERY frame while the object is there - so the
     input keeps flowing (and keeps being recorded) through arming and
     fallback - and it REPLACES the record as the bed only while
     `live_on_air` is true. The record decoder is closed while the set has
     the air, so the record cannot keep decoding underneath it.
  2. THE DUCK, per the operator (2026-09-28): the DJs talk over the set and
     the set dips under them like a record under a DJ. Depth, attack and
     release come from the live object; the ramp is per sample inside the
     frame. The live bed is NOT centred: it is a known stereo source, and
     _centered_pcm's reason (legacy one-sided files) does not apply to it.
     The bed then sits at MUSIC_LEVEL exactly where a record sits.
  3. A TAP for the recorder: every frame, on or off air, as
     tap(frame_bytes, live_bytes_or_None, info). The input cut and the mix
     cut are cut from these on ONE clock - the mixer's frame counter - so
     the two files of a cut hold the same samples of the input. A mixer
     with a tap never lingers out.

Nothing here changes the mix when no `live` object is in the snapshot.

  python tools/pinelive_stream_patch.py [--check] station_stream.py
  python tools/pinelive_stream_patch.py --apply station_stream.py

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
    ("pl-stream-taps-init",
     '        self._aired: "deque[str]" = deque(maxlen=512)\n'
     '        self._aired_set: set[str] = set()\n',
     '        self._aired: "deque[str]" = deque(maxlen=512)\n'
     '        self._aired_set: set[str] = set()\n'
     '        # [pinelive] the recorder\'s taps: fn(frame, live, info) per frame.\n'
     '        self._taps: list[Callable[..., Any]] = []\n', 1),

    ("pl-stream-tap-methods",
     '    # -- the engine --------------------------------------------------------\n'
     '    def ensure_running(self) -> None:\n',
     '    # -- [pinelive] the recorder\'s tap ------------------------------------\n'
     '    def add_tap(self, fn: Callable[..., Any]) -> None:\n'
     '        """Hear every frame the mixer makes, on or off air, as\n'
     '        fn(frame_bytes, live_bytes_or_None, info). Called on the mixer\n'
     '        thread: it must only hand the bytes on, never block. A mixer with\n'
     '        a tap never lingers out."""\n'
     '        with self._lock:\n'
     '            if fn not in self._taps:\n'
     '                self._taps.append(fn)\n'
     '        self.ensure_running()\n'
     '\n'
     '    def remove_tap(self, fn: Callable[..., Any]) -> None:\n'
     '        with self._lock:\n'
     '            if fn in self._taps:\n'
     '                self._taps.remove(fn)\n'
     '\n'
     '    # -- the engine --------------------------------------------------------\n'
     '    def ensure_running(self) -> None:\n', 1),

    ("pl-stream-linger",
     '                        and self._last_listener_at\n'
     '                        and not self._any_warm()):\n'
     '                    break\n',
     '                        and self._last_listener_at\n'
     '                        and not self._any_warm()\n'
     '                        and not self._taps):            # [pinelive]\n'
     '                    break\n', 1),

    ("pl-stream-lduck-init",
     '        duck = 0.0                      # 0 = bed up, 1 = fully ducked\n',
     '        duck = 0.0                      # 0 = bed up, 1 = fully ducked\n'
     '        lduck = 0.0                     # [pinelive] the live set\'s own duck\n', 1),

    ("pl-stream-live-state",
     '                paused = bool(state.get("paused"))\n'
     '                on_air = bool(state.get("on", True)) and not paused\n',
     '                paused = bool(state.get("paused"))\n'
     '                on_air = bool(state.get("on", True)) and not paused\n'
     '                # [pinelive] MX Live: the input, when the host hands it over,\n'
     '                # and whether it has the air. While it has, the record is\n'
     '                # closed rather than left decoding underneath the set.\n'
     '                live_src = state.get("live")\n'
     '                live_on = bool(live_src is not None and state.get("live_on_air"))\n'
     '                if live_on and music is not None:\n'
     '                    music.close()\n'
     '                    music, music_id = None, ""\n', 1),

    ("pl-stream-live-read",
     '                # -- assemble ----------------------------------------------\n'
     '                made_sound = False\n',
     '                # [pinelive] read the input EVERY frame it is there - arming\n'
     '                # and fallback included - so it keeps flowing into the\n'
     '                # recorder whether or not it has the air.\n'
     '                live_raw = None\n'
     '                if live_src is not None:\n'
     '                    try:\n'
     '                        live_raw, _live_ok = live_src.read_frame()\n'
     '                    except Exception as exc:  # noqa: BLE001\n'
     '                        live_raw = None\n'
     '                        self.stats["last_error"] = f"live: {exc}"\n'
     '                # -- assemble ----------------------------------------------\n'
     '                made_sound = False\n', 1),

    ("pl-stream-live-bed",
     '                    bed = bed * (bed_gain / max(MUSIC_LEVEL, 0.0001))\n',
     '                    bed = bed * (bed_gain / max(MUSIC_LEVEL, 0.0001))\n'
     '                    # [pinelive] the set IS the bed while it has the air,\n'
     '                    # ducked under every line and sting like a record.\n'
     '                    if live_on and live_raw is not None:\n'
     '                        bed, lduck = _live_bed(live_raw, live_src,\n'
     '                                               voice_pcm is not None, lduck)\n'
     '                        made_sound = True\n', 1),

    ("pl-stream-tap-call",
     '                if made_sound:\n'
     '                    self._pcm_burst.append(frame)\n',
     '                if made_sound:\n'
     '                    self._pcm_burst.append(frame)\n'
     '                # [pinelive] the recorder\'s tap: every frame, on air or\n'
     '                # off, with the input frame that went into it.\n'
     '                if self._taps:\n'
     '                    _tap_info = {"on_air": on_air, "live_on": live_on,\n'
     '                                 "made_sound": made_sound, "t": now}\n'
     '                    for _tap in list(self._taps):\n'
     '                        try:\n'
     '                            _tap(frame, live_raw, _tap_info)\n'
     '                        except Exception as exc:  # noqa: BLE001\n'
     '                            self.stats["last_error"] = f"tap: {exc}"\n', 1),

    ("pl-stream-state-taps",
     '            "join_burst_s": JOIN_BURST_SECONDS,\n',
     '            "join_burst_s": JOIN_BURST_SECONDS,\n'
     '            "taps": len(self._taps),                    # [pinelive]\n', 1),

    ("pl-stream-live-bed-fn",
     'class _Voice:\n'
     '    """A DJ clip waiting for, or sitting on, its air moment."""\n',
     'def _live_bed(raw: bytes, src: Any, talking: bool,\n'
     '              level: float) -> tuple[np.ndarray, float]:\n'
     '    """[pinelive] One frame of the live input as the programme bed.\n'
     '\n'
     '    Kept STEREO (it is a known two-channel source; the centring exists for\n'
     '    legacy one-sided files), trimmed by the operator\'s gain, and ducked\n'
     '    under a line or a sting with its own depth and attack/release, ramped\n'
     '    per sample across the frame so the dip never clicks. `level` is the\n'
     '    duck carried from the last frame (0 = up, 1 = fully ducked); the new\n'
     '    one is returned and published on the source as `duck_now`."""\n'
     '    values = _pcm(raw)\n'
     '    try:\n'
     '        gain = float(getattr(src, "gain", 1.0))\n'
     '        depth = float(getattr(src, "duck_gain", MUSIC_DUCK / MUSIC_LEVEL))\n'
     '        attack = float(getattr(src, "duck_attack_ms", DUCK_RAMP_MS))\n'
     '        release = float(getattr(src, "duck_release_ms", DUCK_RAMP_MS))\n'
     '    except Exception:  # noqa: BLE001\n'
     '        gain, depth = 1.0, MUSIC_DUCK / MUSIC_LEVEL\n'
     '        attack = release = float(DUCK_RAMP_MS)\n'
     '    depth = min(1.0, max(0.0, depth))\n'
     '    target = 1.0 if talking else 0.0\n'
     '    if target > level:\n'
     '        new = min(target, level + FRAME_MS / max(1.0, attack))\n'
     '    else:\n'
     '        new = max(target, level - FRAME_MS / max(1.0, release))\n'
     '    g0 = gain * (1.0 + (depth - 1.0) * level)\n'
     '    g1 = gain * (1.0 + (depth - 1.0) * new)\n'
     '    n = values.size // CHANNELS\n'
     '    ramp = np.repeat(np.linspace(g0, g1, n, endpoint=False), CHANNELS)\n'
     '    bed = values[:n * CHANNELS] * ramp\n'
     '    if bed.size < FRAME_SAMPLES * CHANNELS:\n'
     '        bed = np.concatenate([bed, np.zeros(FRAME_SAMPLES * CHANNELS - bed.size)])\n'
     '    try:\n'
     '        src.duck_now = new\n'
     '    except Exception:  # noqa: BLE001\n'
     '        pass\n'
     '    return bed, new\n'
     '\n'
     '\n'
     'class _Voice:\n'
     '    """A DJ clip waiting for, or sitting on, its air moment."""\n', 1),
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
    target = next((a for a in argv if not a.startswith("--")), "station_stream.py")
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

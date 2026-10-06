#!/usr/bin/env python3
"""[sfx-even] The SFX guy's clips at the DJs' level, every one of them. 2026-10-05.

"the volume across clips still seems unlevel. I want the SFX guy adjusting the gain of each and
 every clip based on the audio waveform to normalize the audio levels ... Some clips are whispers
 and others are leveled. The SFX guy should be reviewing and preparing the clips he is about to
 run ensuring the volume is adequate."

MEASURED ON THE AIR first (five minutes of /stream.mp3, momentary loudness laid over the air log,
2026-10-05 21:05): the DJs' lines sat at a median of -16.7 LUFS, the welded stings at -13 to -17,
and the clips with a picture - streamed with their measured gain towards SFX_TARGET_LUFS - at
-19 to -21. The clips were the quiet ones: their target was -20 while everything around them
played four to seven LU louder. Every clip was already measured (22,276 gains kept) and every one
went out through the gain stream; the number it was aimed at was the fault.

Two changes, one place each:
  1. SFX_TARGET_LUFS defaults to -16: the level the DJs are measured at, so a clip is as loud as
     the people talking around it. The box slider shifts a clip exactly as it shifts a sting.
  2. A clip the peak rule would leave SFX_GAIN_SQUEEZE_LU (3) or more under the target - a quiet
     clip with one bang in it, the "whisper" - is streamed through loudnorm's dynamic mode, which
     brings its body up while holding its peaks; the plain gain cannot do both. Counted as
     `squeezed` in /api/sfx/video/mode's levelled block.

Usage:  sfx_even_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        sfx_even_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

TARGET_OLD = '''SFX_TARGET_LUFS = float(os.getenv("SFX_TARGET_LUFS", "-20"))
SFX_TP_DB = float(os.getenv("SFX_TP_DB", "-6"))
'''
TARGET_NEW = '''# [sfx-even] -16, not -20: measured on the air (2026-10-05) the DJs' lines sit at a median of
# -16.7 LUFS and the welded stings at -13 to -17; a clip aimed at -20 was the quiet one in every
# round. One level for a clip with a picture, a sting and the people talking around them.
SFX_TARGET_LUFS = float(os.getenv("SFX_TARGET_LUFS", "-16"))
SFX_TP_DB = float(os.getenv("SFX_TP_DB", "-6"))
# [sfx-even] a clip the peak rule would leave this many LU under the target is streamed through
# loudnorm's dynamic mode instead of a plain gain (0 keeps the plain gain for every clip)
SFX_GAIN_SQUEEZE_LU = float(os.getenv("SFX_GAIN_SQUEEZE_LU", "3"))
'''

COMMAND_OLD = '''def sfx_gain_command(path: Path, db: float) -> list[str] | None:
    kind = SFX_GAIN_STREAM_TYPES.get(path.suffix.lower())
    if kind is None:
        return None
    fmt, acodec, _mime = kind
    limit = 10 ** ((float(SFX_TP_DB) - float(globals().get("SFX_TP_MARGIN_DB", 1.0))) / 20.0)
    # [talk-steady] the box's own ffmpeg (imageio): none is on PATH in the container, so
    # every gain stream forked the station, failed to exec and went out unlevelled
    cmd = [_sfx_ffmpeg() or shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
           "-i", str(path), "-map", "0:v?", "-map", "0:a?", "-c:v", "copy",
           "-af", "volume=%.2fdB,alimiter=limit=%.4f:level=disabled" % (db, max(0.0625, min(1.0, limit))),
           "-c:a", acodec, "-b:a", "160k"]
'''
COMMAND_NEW = '''def sfx_gain_chain(db: float, heard: dict[str, Any] | None = None) -> tuple[str, str]:
    """[sfx-even] The audio filter a clip with a picture streams through, and its name.
    "gain": one linear gain to the target (the measured number) with the limiter at the
    ceiling. "squeezed": the peak rule would have left this clip SFX_GAIN_SQUEEZE_LU or more
    under the target - a quiet clip with one bang in it, heard as a whisper beside the DJs -
    so loudnorm's dynamic mode brings its body up and holds its peaks, which no single gain
    can do. The box slider (box_gain, the knob the DJs and the stings track) shifts the
    target and the ceiling alike, so one knob moves every clip the same way."""
    import math as _math
    _box = globals().get("box_gain")
    try:
        vol = float(_box()) if callable(_box) else 1.0
    except Exception:  # noqa: BLE001
        vol = 1.0
    shift = 20.0 * _math.log10(max(0.05, vol))
    target = float(SFX_TARGET_LUFS) + shift
    ceiling = float(SFX_TP_DB) + shift
    limit = 10 ** ((ceiling - float(globals().get("SFX_TP_MARGIN_DB", 1.0))) / 20.0)
    squeeze = float(globals().get("SFX_GAIN_SQUEEZE_LU", 3.0))
    level = heard.get("i") if isinstance(heard, dict) else None
    held = (target - float(level)) - (float(db) + shift) if isinstance(level, (int, float)) else 0.0
    if squeeze > 0 and held >= squeeze:
        return "loudnorm=I=%.1f:TP=%.1f:LRA=11" % (max(-70.0, min(-5.0, target)), max(-9.0, min(0.0, ceiling))), "squeezed"
    return "volume=%.2fdB,alimiter=limit=%.4f:level=disabled" % (float(db) + shift, max(0.0625, min(1.0, limit))), "gain"


def sfx_gain_command(path: Path, db: float, heard: dict[str, Any] | None = None) -> list[str] | None:
    kind = SFX_GAIN_STREAM_TYPES.get(path.suffix.lower())
    if kind is None:
        return None
    fmt, acodec, _mime = kind
    chain, _how = sfx_gain_chain(db, heard)   # [sfx-even]
    # [talk-steady] the box's own ffmpeg (imageio): none is on PATH in the container, so
    # every gain stream forked the station, failed to exec and went out unlevelled
    cmd = [_sfx_ffmpeg() or shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
           "-i", str(path), "-map", "0:v?", "-map", "0:a?", "-c:v", "copy",
           "-af", chain,
           "-c:a", acodec, "-b:a", "160k"]
'''

STREAM_OLD = '''async def sfx_gain_stream(path: Path, db: float, headers: dict[str, str]) -> Response | None:
    """The original, read in place, with its gain applied as it streams - None
    when this container cannot be streamed that way (the caller sends it as is)."""
    cmd = sfx_gain_command(path, db)
    if cmd is None:
        return None
'''
STREAM_NEW = '''async def sfx_gain_stream(path: Path, db: float, headers: dict[str, str],
                          heard: dict[str, Any] | None = None) -> Response | None:
    """The original, read in place, with its gain applied as it streams - None
    when this container cannot be streamed that way (the caller sends it as is).
    [sfx-even] `heard` (the clip's measured {i, tp}) lets a peak-held clip take the
    squeezed road; the chain's name goes out as X-Pine-Gain-How and is counted."""
    cmd = sfx_gain_command(path, db, heard)
    if cmd is None:
        return None
    _how = sfx_gain_chain(db, heard)[1]
    if _how == "squeezed":
        _counts = globals().get("_SFX_VIDEO_LEVEL")
        if isinstance(_counts, dict):
            _counts["squeezed"] = int(_counts.get("squeezed") or 0) + 1
'''

HEADER_OLD = '''    out["X-Pine-Gain-Db"] = "%.2f" % db
'''
HEADER_NEW = '''    out["X-Pine-Gain-Db"] = "%.2f" % db
    out["X-Pine-Gain-How"] = _how   # [sfx-even]
'''

ROUTE_OLD = '''            _streamed = await sfx_gain_stream(raw, float(_gain["db"]), headers)
'''
ROUTE_NEW = '''            _streamed = await sfx_gain_stream(raw, float(_gain["db"]), headers, _gain)   # [sfx-even]
'''

READOUT_OLD = '''            "stings": int(_SFX_VIDEO_LEVEL.get("stings") or 0),
            "in_flight": busy,
'''
READOUT_NEW = '''            "stings": int(_SFX_VIDEO_LEVEL.get("stings") or 0),
            "squeezed": int(_SFX_VIDEO_LEVEL.get("squeezed") or 0),   # [sfx-even]
            "in_flight": busy,
'''

NAS_TEST_OLD = """                   "sfx_loudness": lambda p: {"i": -30.0, "tp": -12.0, "peak": -12.0}}
"""
NAS_TEST_NEW = """                   "sfx_loudness": lambda p: {"i": -30.0, "tp": -12.0, "peak": -12.0},
                   "_sfx_ffmpeg": lambda: "ffmpeg"}   # [sfx-even] the stream command names the box's ffmpeg ([talk-steady]); it lives outside this section
"""

EDITS = {
    "tests/test_nas_gain_2026_10_01.py": [
        ("the nas-gain test knows the box's ffmpeg", NAS_TEST_OLD, NAS_TEST_NEW, '"_sfx_ffmpeg": lambda: "ffmpeg"}', 1),
    ],
    "app.py": [
        ("the target is the DJs' level", TARGET_OLD, TARGET_NEW, 'SFX_TARGET_LUFS = float(os.getenv("SFX_TARGET_LUFS", "-16"))', 1),
        ("the chain: gain, or squeezed", COMMAND_OLD, COMMAND_NEW, "def sfx_gain_chain(db: float, heard: dict[str, Any] | None = None) -> tuple[str, str]:", 1),
        ("the stream knows what it heard", STREAM_OLD, STREAM_NEW, "_how = sfx_gain_chain(db, heard)[1]", 1),
        ("the chain's name goes out", HEADER_OLD, HEADER_NEW, 'out["X-Pine-Gain-How"] = _how', 1),
        ("the route hands over the measurement", ROUTE_OLD, ROUTE_NEW, "await sfx_gain_stream(raw, float(_gain[\"db\"]), headers, _gain)", 1),
        ("squeezed is counted", READOUT_OLD, READOUT_NEW, '"squeezed": int(_SFX_VIDEO_LEVEL.get("squeezed") or 0),', 1),
    ],
}


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        if not path.exists():
            print("%-20s (not in this tree - skipped)" % name)
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, probe, count in edits:
            forms = [(old, new, probe)]
            if mode == "mixed":
                forms.append((old.replace("\n", "\r\n"), new.replace("\n", "\r\n"), probe.replace("\n", "\r\n")))
            state = ""
            for old_, new_, probe_ in forms:
                have = text.count(probe_)
                if have == count:
                    state = "applied"
                    break
                if not have and text.count(old_) == count:
                    text = text.replace(old_, new_)
                    assert text.count(probe_) == count, (name, label, "probe after the edit")
                    state, changed = "ready", True
                    break
            if not state:
                state = "missing (anchor found %d, probe %d)" % (text.count(old), text.count(probe))
            print("%-20s %-44s %s" % (name, label, state))
            if state == "ready":
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, bom, mode, changed))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, bom, mode, changed in plans:
        if not changed:
            continue
        body = (text.replace("\n", "\r\n") if mode == "crlf" else text).encode("utf-8")
        tmp = path.with_name(path.name + ".sfxeven.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

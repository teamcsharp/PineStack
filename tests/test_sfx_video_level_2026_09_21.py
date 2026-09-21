# -*- coding: utf-8 -*-
"""#1420: a clip that carries a picture arrives at the same loudness as
the rest of them — and still carries the picture.

Runs the SHIPPED source of the leveller and of the measurement it depends
on against real clips built here with ffmpeg, because the two things that
can actually be wrong are (a) whether volumedetect's mean is parsed at all
and (b) whether `-c:v copy` really leaves a picture behind. Neither can be
proved by stubbing them.

    python3 tests/test_sfx_video_level_2026_09_21.py app.py
"""
import ast
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

SRC = sys.argv[1] if len(sys.argv) > 1 else "app.py"
s = io.open(SRC, encoding="utf-8").read()
tree = ast.parse(s)
lines = s.split("\n")


def fn(name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    raise SystemExit("no function " + name)


def const(name):
    """The shipped assignment, so the test cannot drift from the defaults
    it is checking."""
    for node in tree.body:
        # An annotated one (`_SFX_VIDEO_LEVEL: dict[str, Any] = {...}`) is an
        # AnnAssign, not an Assign — half the module's tables are written
        # that way and reading only Assign silently misses them.
        named = None
        if isinstance(node, ast.Assign) and node.targets:
            named = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            named = node.target
        if isinstance(named, ast.Name) and named.id == name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    raise SystemExit("no constant " + name)


try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception as exc:                                     # noqa: BLE001
    raise SystemExit("SKIP: no ffmpeg on this box (%s)" % exc)

ROOM = Path(tempfile.mkdtemp(prefix="sfx-video-level-"))
ns: dict[str, Any] = {
    "os": os, "math": math, "json": json, "subprocess": subprocess,
    "time": time,
    "Path": Path, "Any": Any,
    "SFX_LEVELLED": ROOM / "levelled",
    "SFX_LEVEL_PATH": ROOM / "sfx_levels.json",
    "_SFX_LEVEL": {}, "_SFX_LEVEL_DIRTY": [0],
    "SFX_SILENT_DB": -50.0,
    # sfx_id is a pure hash of the path in the shipped file; a shorter one
    # with the same contract keeps the test free of its memo tables.
    "sfx_id": lambda p: "%016x" % (abs(hash(str(p))) % (1 << 64)),
    "sfx_is_video": lambda p: Path(p).suffix.lower() in (
        ".mp4", ".m4v", ".webm", ".mov", ".mkv", ".ogv"),
}
for name in ("SFX_RMS", "SFX_VIDEO_MEAN_DB", "SFX_VIDEO_PEAK_DB",
             "SFX_VIDEO_BOOST_DB", "SFX_VIDEO_CUT_DB", "SFX_VIDEO_DEADBAND_DB",
             "SFX_VIDEO_LEVEL_SECS", "SFX_VIDEO_LEVEL_KEEP",
             "SFX_VIDEO_LEVEL_MB", "SFX_VIDEO_LEVEL_MARK",
             "SFX_VIDEO_ASIS_KEEP", "SFX_VIDEO_SQUASH_DB", "_SFX_VIDEO_LEVEL"):
    exec(const(name), ns)
for name in ("_sfx_level_load", "_sfx_level_save", "_sfx_level_parts",
             "sfx_mean_db", "sfx_level", "sfx_video_gain_db",
             "_sfx_video_level_want", "_sfx_video_level_flag",
             "_sfx_video_level_prune", "sfx_video_levelled",
             "_sfx_video_level_say"):
    exec(fn(name), ns)
exec(const("_SFX_LEVEL_MISS"), ns)

gain_db = ns["sfx_video_gain_db"]
levelled = ns["sfx_video_levelled"]
mean_db = ns["sfx_mean_db"]
TARGET = ns["SFX_VIDEO_MEAN_DB"]

fails = []


def check(label, got, want):
    ok = got == want
    print("%-58s %s" % (label, "ok" if ok else "FAIL got %r want %r"
                        % (got, want)))
    if not ok:
        fails.append(label)


def near(label, got, want, slack):
    ok = got is not None and abs(got - want) <= slack
    print("%-58s %s" % (label, "ok (%.2f)" % got if ok else
                        "FAIL got %r want %r +-%s" % (got, want, slack)))
    if not ok:
        fails.append(label)


SOURCES = {
    # A tone has a crest of 3 dB. SPEECH has twelve to eighteen, and the
    # peak guard exists precisely because those two clips are different
    # even when their means are identical — so a suite that built only
    # tones would be testing a signal the rule was never written for.
    "sine": "sine=frequency=440:duration=%s:sample_rate=44100",
    "noise": ("anoisesrc=color=white:duration=%s:sample_rate=44100"
              ":amplitude=0.5"),
}


def clip(name, db, seconds=2.0, with_sound=True, size="160x120",
         source="noise"):
    """A real clip: a moving picture, and a sound at a known level."""
    out = ROOM / name
    args = [FFMPEG, "-nostdin", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i",
            "testsrc=size=%s:rate=15:duration=%s" % (size, seconds)]
    if with_sound:
        args += ["-f", "lavfi", "-i", SOURCES[source] % seconds,
                 "-af", "volume=%.2fdB" % db, "-c:a", "aac", "-b:a", "128k"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", str(seconds),
             str(out)]
    subprocess.run(args, check=True, capture_output=True)
    return out


def clip_at(name, want_mean, source="noise", seconds=2.0):
    """A clip whose MEAN lands where we asked — measured off this build's
    own generator rather than computed from what a generator ought to
    produce. lavfi's sine comes out of this ffmpeg at -21 dBFS, not the
    -3 a full-scale one would, and the first draft of this suite asserted
    that arithmetic, which is to say it asserted my guess."""
    probe = clip("probe-" + name, 0.0, source=source, seconds=seconds)
    base = measured(probe)
    probe.unlink()
    if base is None:
        raise SystemExit("cannot measure this build's %s source" % source)
    return clip(name, want_mean - base, source=source, seconds=seconds)


def streams(path):
    """What ffmpeg says is inside — the picture is the half a levelling
    road is most likely to lose."""
    got = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-i", str(path)],
                         capture_output=True, text=True, errors="replace")
    kinds = []
    for line in (got.stderr or "").splitlines():
        if "Stream #" in line and ": Video:" in line:
            kinds.append("video")
        elif "Stream #" in line and ": Audio:" in line:
            kinds.append("audio")
    return kinds


def measured(path):
    """mean_volume of the finished file, read back with the same tool the
    station uses."""
    got = subprocess.run(
        [FFMPEG, "-hide_banner", "-nostats", "-i", str(path),
         "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, errors="replace")
    for line in (got.stderr or "").splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:")[1].split("dB")[0])
    return None


try:
    print("--- the rule, which is arithmetic on one number ---")
    check("a clip already at the target is not moved",
          round(gain_db(TARGET), 6), 0.0)
    check("six dB under the target is lifted six",
          round(gain_db(TARGET - 6.0), 6), 6.0)
    check("six dB over the target is dropped six",
          round(gain_db(TARGET + 6.0), 6), -6.0)
    check("room noise at -90 dBFS is lifted only to the bound",
          gain_db(-90.0), ns["SFX_VIDEO_BOOST_DB"])
    check("full scale is cut only to the bound",
          gain_db(0.0), ns["SFX_VIDEO_CUT_DB"])
    check("an unmeasured clip asks for no gain at all", gain_db(None), 0.0)
    check("the target matches the audio stings' own, in dB",
          round(TARGET, 2),
          round(20.0 * math.log10(ns["SFX_RMS"] / 32767.0), 2))

    print("\n--- and the peak, which says WHETHER a lift is allowed ---")
    check("a clip printed 30 dB quiet with a normal crest gets all of it",
          round(gain_db(TARGET - 30.0, TARGET - 30.0 + 14.0), 6), 30.0)
    check("silence with a hiss under it gets nothing - #1199 already "
          "calls it empty",
          gain_db(-70.0, ns["SFX_SILENT_DB"] - 1.0), 0.0)
    check("mostly-silence with three loud moments is lifted by its PEAK",
          round(gain_db(-60.0, -8.0), 6),
          round(ns["SFX_VIDEO_PEAK_DB"] + ns["SFX_VIDEO_SQUASH_DB"] + 8.0, 6))
    check("a cut never consults the peak", gain_db(0.0, -0.1),
          ns["SFX_VIDEO_CUT_DB"])
    check("and neither guard fires when there is no peak to read",
          round(gain_db(TARGET - 8.0), 6), 8.0)

    print("\n--- the two cache shapes, because sfx_levels.json is full of "
          "the old one ---")
    check("a pre-#1420 bare peak still reads as a peak",
          ns["_sfx_level_parts"](-6.5), (-6.5, None))
    check("null still means 'could not be measured at all'",
          ns["_sfx_level_parts"](None), (None, None))
    check("a #1420 entry carries both",
          ns["_sfx_level_parts"]({"p": -6.5, "m": -22.0}), (-6.5, -22.0))
    check("and a #1420 entry with no audio carries the peak alone",
          ns["_sfx_level_parts"]({"p": -6.5, "m": None}), (-6.5, None))

    print("\n--- measuring a real clip ---")
    # THE CLIP THE OPERATOR IS COMPLAINING ABOUT: thirty decibels under
    # everything else, with the crest of something somebody said.
    quiet = clip_at("quiet.mp4", TARGET - 30.0)
    # Against an INDEPENDENT read of the same file, not against arithmetic
    # about what a sine ought to measure — lavfi's sine comes out of this
    # build at -21 dBFS, not the -3 a full-scale one would, and a test
    # that asserted the arithmetic would have been asserting my guess.
    near("volumedetect's mean is parsed, not thrown away",
         mean_db(quiet), measured(quiet), 0.3)
    near("and the clip really is 30 dB under everything else",
         measured(quiet), TARGET - 30.0, 1.5)
    check("and the peak the old road kept still reads",
          ns["sfx_level"](quiet, measure=False) is not None, True)
    check("a pre-#1420 entry is re-measured once for its mean",
          (lambda: (ns["_SFX_LEVEL"].__setitem__(
              "%s:%s" % (quiet, quiet.stat().st_mtime_ns), -3.25),
              mean_db(quiet) is not None)[1])(), True)

    print("\n--- levelling a clip that is too quiet to hear ---")
    ns["_SFX_VIDEO_LEVEL"].update({"made": 0, "as_is": 0, "failed": 0,
                                   "want": [], "why": ""})
    out = levelled(quiet, make=True)
    check("a new file was made", out != quiet, True)
    check("the counter says so", ns["_SFX_VIDEO_LEVEL"]["made"], 1)
    check("THE PICTURE SURVIVED", streams(out), ["video", "audio"])
    check("and it is still served as the container it was",
          out.suffix, ".mp4")
    near("the sound now sits at the target", measured(out), TARGET, 2.5)
    check("the second ask is the cache, not a second ffmpeg",
          (levelled(quiet, make=True) == out
           and ns["_SFX_VIDEO_LEVEL"]["made"] == 1), True)

    print("\n--- and one that is far too loud ---")
    loud = clip_at("loud.mp4", TARGET + 12.0)
    hot = levelled(loud, make=True)
    check("it too was re-made", hot != loud, True)
    near("brought DOWN to the same place", measured(hot), TARGET, 2.5)
    check("the picture survived that as well", streams(hot),
          ["video", "audio"])

    print("\n--- a clip already at level is left exactly alone ---")
    ns["_SFX_VIDEO_LEVEL"]["as_is"] = 0
    fine = clip_at("fine.mp4", TARGET)
    same = levelled(fine, make=True)
    check("no second copy of a clip that needs no gain", same, fine)
    check("and it is recorded as looked-at, not as failed",
          (ns["_SFX_VIDEO_LEVEL"]["as_is"], ns["_SFX_VIDEO_LEVEL"]["failed"]),
          (1, 0))
    check("the reason is written down where a human can read it",
          any(p.name.endswith(".asis") and "already at level" in
              p.read_text() for p in (ROOM / "levelled").iterdir()), True)
    check("and it is never probed again",
          (levelled(fine, make=True) == fine
           and ns["_SFX_VIDEO_LEVEL"]["as_is"] == 1), True)

    print("\n--- a clip with nothing above the silence line ---")
    # Not the same clip as the quiet one, and that is the whole point of
    # the peak guard: this one's mean is lower AND its loudest moment is
    # under #1199's silence line, so there is nothing in it to make
    # louder. Thirty decibels of lift would deliver thirty of hiss.
    hiss = clip("hiss.mp4", -34.0, source="sine")
    check("it really is under the line",
          (measured(hiss) < TARGET - 30.0
           and ns["sfx_level"](hiss) <= ns["SFX_SILENT_DB"]), True)
    check("so it is served exactly as it was shot",
          levelled(hiss, make=True), hiss)
    check("and the note says WHICH rule refused it, not the wrong one",
          any(p.name.endswith(".asis") and "silence line" in p.read_text()
              for p in (ROOM / "levelled").iterdir()), True)

    print("--- a clip with no sound in it at all ---")
    silent = clip("silent.mp4", 0.0, with_sound=False)
    check("served as it was shot", levelled(silent, make=True), silent)
    check("and its picture is untouched", streams(silent), ["video"])

    print("\n--- the request path never waits on an ffmpeg ---")
    ns["_SFX_VIDEO_LEVEL"]["want"] = []
    fresh = clip("fresh.mp4", -40.0)
    check("a miss plays the clip as it is", levelled(fresh, make=False),
          fresh)
    check("AND asks for a copy, or nothing would ever level it",
          ns["_SFX_VIDEO_LEVEL"]["want"], [str(fresh)])
    levelled(fresh, make=False)
    check("asked once, however many times it airs",
          ns["_SFX_VIDEO_LEVEL"]["want"].count(str(fresh)), 1)
    levelled(fresh, make=True)
    ns["_SFX_VIDEO_LEVEL"]["want"] = []
    check("and once made, the request path serves the copy",
          levelled(fresh, make=False) != fresh, True)
    check("with nothing left to ask for", ns["_SFX_VIDEO_LEVEL"]["want"], [])

    print("\n--- the want list is bounded ---")
    ns["_SFX_VIDEO_LEVEL"]["want"] = []
    for at in range(200):
        ns["_sfx_video_level_want"](Path("/nowhere/%d.mp4" % at))
    check("a soundboard held down cannot grow it without end",
          len(ns["_SFX_VIDEO_LEVEL"]["want"]), 60)
    check("and what it kept is the newest",
          ns["_SFX_VIDEO_LEVEL"]["want"][-1], "/nowhere/199.mp4")

    print("\n--- the copies are pruned, because nothing else prunes them ---")
    ns["SFX_VIDEO_LEVEL_KEEP"] = 2
    ns["_sfx_video_level_prune"]()
    left = [p for p in (ROOM / "levelled").iterdir()
            if not p.name.endswith(".asis")]
    check("bounded by count", len(left) <= 2, True)
    check("the .asis markers are kept - they are what stops a re-probe",
          any(p.name.endswith(".asis") for p in (ROOM / "levelled").iterdir()),
          True)

    print("\n--- what the operator reads ---")
    say = ns["_sfx_video_level_say"]()
    check("the line names the target", "%.0f dB" % TARGET in say, True)
    check("and says how many were levelled", "levelled" in say, True)
    print("   %s" % say.strip(" —"))
finally:
    shutil.rmtree(ROOM, ignore_errors=True)

print("\n%d checks failed" % len(fails))
for line in fails:
    print("  " + line)
raise SystemExit(1 if fails else 0)

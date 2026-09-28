# -*- coding: utf-8 -*-
"""#1477 (was #1420): every clip arrives at the same LOUDNESS, and a clip
that carries a picture still carries the picture.

THE CONTRACT. A clip is measured by EBU R128 - integrated loudness, true
peak, sample peak (sfx_loudness, ffmpeg's ebur128) - and brought to
SFX_TARGET_LUFS with one linear gain, its TRUE peak held under SFX_TP_DB.
The file WRITTEN is measured and corrected (up to SFX_LEVEL_PASSES), the
lift is still bounded by the peak (#1420), and a clip whose loudest moment
is under the station's silence line is empty, not quiet, and is left
alone. Only a clip the peak rule would still leave well short - a bang in
a quiet clip - is offered the fallbacks (SFX_LEVEL_DYNAMIC), and each is
kept only if it is better. The wav sting road (sfx_levelled) is aimed at
the same target, so a sting and a clip with a picture arrive together by
construction.

WHY INTEGRATED LOUDNESS. #1420 aimed volumedetect's MEAN at a target, and
the mean counts the silence between the words: a clip with pauses in it
read quiet and was lifted past the rest, and one with a long quiet tail
read quieter still. On 2026-09-27 the last eleven clips /sfx/{key} handed
out spanned 18.6 LU. Integrated loudness gates the silence out and weights
the spectrum the way an ear does - it is the number "evenly" means - so it
is the number every clip here is read back by, and the long-tail clip is
checked to really be one the mean would have got wrong.

WHY A TRUE-PEAK CEILING. The old ceiling was -1 dBFS on the SAMPLES. A
lifted clip rode right up to it and went over BETWEEN them, and AAC puts
back peak a limiter took off. dBTP is the peak a DAC actually rebuilds,
and SFX_TP_DB sits far enough under full scale to leave room for the
codec - so what is asserted is the true peak of the file on disk, not the
leveller's account of what it asked for.

WHY THE PICTURE IS COPIED. `-c:v copy` is the whole reason levelling a
clip is affordable (#1420): not one frame re-encoded, a ten second clip
done in well under a second, once. The picture is also the half a
levelling road is most likely to lose, so it is compared PACKET BY PACKET
- same codec, same frame count, same bytes - not merely looked for.

Runs the SHIPPED source (lifted out of app.py by name with ast, run in the
order app.py itself runs it) against real clips built here with ffmpeg,
and reads every level back with this suite's OWN ebur128 run and parser,
never with sfx_loudness: a leveller that measured wrong and a check that
measured the same wrong way would agree with each other.

    python3 tests/test_sfx_video_level_2026_09_21.py app.py
    docker exec -w /app spark-agent python tests/test_sfx_video_level_2026_09_21.py app.py
"""
import ast
import builtins
import io
import json
import math
import os
import re
import shutil
import subprocess
import symtable
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from typing import Any

# Run as a script (the two command lines above) this exits with its verdict.
# IMPORTED - `python -m unittest test_sfx_video_level_2026_09_21`, which is
# how the station's runners call every module - the checks below still run
# at import, and SfxVideoLevelContract at the end hands their verdict to the
# runner. Before it existed the runner reported "Ran 0 tests" whatever the
# checks found. A box with no encoder is then a SKIP, and a stop is an
# error, rather than an exit that takes the whole runner down with it; and
# the runner's own argv (the module name) is never read as a path to app.py.
AS_SCRIPT = __name__ == "__main__"

# Before app.py is even read: a box with no encoder has nothing to say
# about levelling, and a SKIP must not depend on its parser either.
try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception as exc:                                     # noqa: BLE001
    raise (SystemExit if AS_SCRIPT else unittest.SkipTest)(
        "SKIP: no ffmpeg on this box (%s)" % exc)

_arg = Path(sys.argv[1]) if AS_SCRIPT and len(sys.argv) > 1 else None
SRC = str(_arg if _arg and _arg.is_file()
          else Path(__file__).resolve().parents[1] / "app.py")
s = io.open(SRC, encoding="utf-8").read()
tree = ast.parse(s)
lines = s.split("\n")


def shipped(name):
    """The shipped top-level definition of `name`: a function, or an
    assignment annotated or not (`_SFX_VIDEO_LEVEL: dict[str, Any] = ...`
    is an AnnAssign, and half the module's tables are written that way).
    The LAST one, because that is the one the running module holds - a
    name defined twice in a quarter-million-line file is not unheard of."""
    found = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                found = node
            continue
        named = None
        if isinstance(node, ast.Assign) and node.targets:
            named = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            named = node.target
        if isinstance(named, ast.Name) and named.id == name:
            found = node
    if found is None:
        raise (SystemExit if AS_SCRIPT else RuntimeError)(
            "no %s in %s" % (name, SRC))
    return found


def text_of(node):
    return "\n".join(lines[node.lineno - 1:node.end_lineno])


def globals_read(node):
    """Every module-level name a shipped function reads, its nested
    helpers included. _sfx_loud_make catches every exception its passes
    raise and reports a `failed` level - so a stub this suite forgot
    would surface three sections later as a clip that "could not be
    levelled", not as the NameError it is."""
    todo, names = [symtable.symtable(text_of(node), SRC, "exec")], set()
    while todo:
        table = todo.pop()
        todo.extend(table.get_children())
        if table.get_type() == "module":
            continue
        for sym in table.get_symbols():
            if sym.is_global() and sym.is_referenced():
                names.add(sym.get_name())
    return names


ROOM = Path(tempfile.mkdtemp(prefix="sfx-video-level-"))
LEVELLED = ROOM / "levelled"
ns: dict[str, Any] = {
    "os": os, "re": re, "json": json, "math": math, "time": time,
    "uuid": uuid, "subprocess": subprocess, "Path": Path, "Any": Any,
    # The station's is VOICE_MEDIA_DIR/sfx; everything the leveller
    # writes lands in here and goes when the suite does.
    "SFX_LEVELLED": LEVELLED,
    # sfx_id is a pure hash of the path in the shipped file; a shorter one
    # with the same contract keeps the test free of its memo tables.
    "sfx_id": lambda p: "%016x" % (abs(hash(str(p))) % (1 << 64)),
    "sfx_is_video": lambda p: Path(p).suffix.lower() in (
        ".mp4", ".m4v", ".webm", ".mov", ".mkv", ".ogv"),
    # The box slider (#573) at unity: a sting is levelled to the target
    # itself, not to wherever somebody left the knob.
    "box_gain": lambda: 1.0,
}
CONSTANTS = (
    "SFX_SILENT_DB", "SFX_STAT_TTL_S", "SFX_STAT_MEMO_MOST", "_SFX_STAT_MEMO",
    "SFX_RMS", "SFX_PEAK", "SFX_MAX_BOOST",
    "SFX_TARGET_LUFS", "SFX_TP_DB", "SFX_TP_MARGIN_DB", "SFX_LU_SLACK",
    "SFX_LEVEL_PASSES", "SFX_LEVEL_DYNAMIC", "SFX_LEVEL_DYNAMIC_LU",
    "SFX_LEVEL_TRANSIENT_LU", "SFX_VIDEO_MEAN_DB", "SFX_VIDEO_PEAK_DB",
    "SFX_VIDEO_BOOST_DB", "SFX_VIDEO_CUT_DB", "SFX_VIDEO_SQUASH_DB",
    "SFX_VIDEO_DEADBAND_DB", "SFX_VIDEO_LEVEL_SECS", "SFX_VIDEO_LEVEL_KEEP",
    "SFX_VIDEO_LEVEL_MB", "SFX_VIDEO_LEVEL_MARK", "SFX_VIDEO_LEVEL_OLD_MARKS",
    "SFX_VIDEO_ASIS_KEEP", "_SFX_VIDEO_LEVEL", "_SFX_LU_MEMO",
    "SFX_CYCLE_FLOOR", "SFX_CYCLE_SHORTEST", "SFX_CYCLE_AHEAD",
    "SFX_CYCLE_QUEUE")
FUNCTIONS = (
    "sfx_cycle_slot", "_sfx_level_parts", "sfx_stamp",
    "sfx_video_gain_db", "_sfx_video_level_want", "_sfx_video_level_flag",
    "_sfx_video_level_prune", "sfx_video_levelled",
    "_sfx_ffmpeg", "sfx_loudness_parse", "sfx_loudness", "_sfx_loud_chain",
    "_sfx_loud_encode", "_sfx_lu_remember", "_sfx_loud_make",
    "sfx_video_levelled_name", "sfx_level_cached", "_sfx_video_level_say",
    "sfx_levelled_name", "sfx_levelled", "_as_wav")
# [sfx-nosound] _as_wav names its wav (and the no-sound note beside it)
# through sfx_src_wav_name, where tools/sfx_nosound_patch.py is in.
if "\ndef sfx_src_wav_name(" in s:
    FUNCTIONS += ("sfx_src_wav_name",)
# In the order app.py runs them, which is the dependency order by
# definition: SFX_VIDEO_MEAN_DB is written as SFX_TARGET_LUFS, and a
# constant is evaluated where it is written. Compiled from the node under
# app.py's own name, so a traceback points at the shipped line.
NODES = {name: shipped(name) for name in CONSTANTS + FUNCTIONS}
for name in sorted(NODES, key=lambda n: NODES[n].lineno):
    exec(compile(ast.Module(body=[NODES[name]], type_ignores=[]), SRC,
                 "exec"), ns)

gain_db = ns["sfx_video_gain_db"]
levelled = ns["sfx_video_levelled"]
TARGET = ns["SFX_TARGET_LUFS"]
CEILING = ns["SFX_TP_DB"]
SILENT = ns["SFX_SILENT_DB"]
LU_SLACK = 1.5          # what "arrives at the same loudness" is held to
TP_SLACK = 0.5          # a true-peak reading's own spread between runs

fails = []


def check(label, got, want):
    ok = got == want
    print("%-62s %s" % (label, "ok" if ok else "FAIL got %r want %r"
                        % (got, want)))
    if not ok:
        fails.append(label)


def near(label, got, want, slack):
    ok = got is not None and abs(got - want) <= slack
    print("%-62s %s" % (label, "ok (%.2f)" % got if ok else
                        "FAIL got %r want %r +-%s" % (got, want, slack)))
    if not ok:
        fails.append(label)


def at_most(label, got, most):
    ok = got is not None and got <= most
    print("%-62s %s" % (label, "ok (%.2f <= %.2f)" % (got, most) if ok else
                        "FAIL got %r want <= %r" % (got, most)))
    if not ok:
        fails.append(label)


SOURCES = {
    # Seeded, so a probe and the clip built from it are the SAME noise and
    # only the volume differs - an unseeded source is a new realisation per
    # run, and a pink noise's true peak moves a decibel between them.
    "white": ("anoisesrc=color=white:amplitude=0.5:seed=1477"
              ":sample_rate=48000:duration={d}"),
    "pink": ("anoisesrc=color=pink:amplitude=0.5:seed=1477"
             ":sample_rate=48000:duration={d}"),
    # A tone has a crest of 3 dB and SPEECH has twelve to eighteen (the
    # #1477-squash note measured 10-18 on 28 pool clips), and the peak
    # rule and the limiter exist precisely for the second. Syllables: band
    # limited bursts of 170 ms every 370, the gaps 40 dB down.
    "speech": ("anoisesrc=color=pink:amplitude=0.5:seed=1477"
               ":sample_rate=48000:duration={d},lowpass=f=3500,"
               "volume=eval=frame:volume='if(lt(mod(t,0.37),0.17),1,0.01)'"),
    # The same words for a second and a half, then the room: 48 dB down
    # for the rest of it. The mean counts every second of that room.
    "tail": ("anoisesrc=color=pink:amplitude=0.5:seed=1477"
             ":sample_rate=48000:duration={d},lowpass=f=3500,"
             "volume=eval=frame:volume='if(lt(t,1.5),"
             "if(lt(mod(t,0.37),0.17),1,0.01),0.004)'"),
    # A bang in a quiet clip: a body 45 dB down and ONE click near full
    # scale. Its crest is past anything the peak rule lets a lift squash,
    # and the click carries almost none of the loudness - the clip the
    # transient pass (_sfx_loud_make 3a) was written for.
    "bang": ("aevalsrc='0.01*(2*random(0)-1)+0.9*eq(n,48000)'"
             ":s=48000:d={d}"),
    # A crackle: the same body with a click every 100 ms. Here the clicks
    # ARE the loudness, so no fallback lands nearer - and none may be kept.
    "crackle": ("aevalsrc='0.01*(2*random(0)-1)+0.7*eq(mod(n,4800),0)'"
                ":s=48000:d={d}"),
    "sine": "sine=frequency=440:sample_rate=48000:duration={d}",
}


def clip(name, db, seconds=2.0, with_sound=True, size="160x120",
         source="pink"):
    """A real clip: a moving picture, and a sound at a known offset."""
    out = ROOM / name
    args = [FFMPEG, "-nostdin", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i",
            "testsrc=size=%s:rate=15:duration=%s" % (size, seconds)]
    if with_sound:
        args += ["-f", "lavfi", "-i", SOURCES[source].format(d=seconds),
                 "-af", "volume=%.2fdB" % db, "-c:a", "aac", "-b:a", "128k"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", str(seconds),
             str(out)]
    subprocess.run(args, check=True, capture_output=True)
    return out


def sting(name, db, source="speech", seconds=3.0):
    """A wav the way the sting road holds one: mono 16-bit at 22050, which
    is exactly what _as_wav decodes a pack's mp3s and mp4s into."""
    out = ROOM / name
    subprocess.run([FFMPEG, "-nostdin", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", SOURCES[source].format(d=seconds),
                    "-af", "volume=%.2fdB" % db, "-ac", "1", "-ar", "22050",
                    "-c:a", "pcm_s16le", str(out)],
                   check=True, capture_output=True)
    return out


def clip_at(name, want_lufs, source="pink", seconds=2.0):
    """A clip whose LOUDNESS lands where we asked - read off this build's
    own generator rather than computed from what a generator ought to
    produce. lavfi's sine comes out of this ffmpeg at -21.8 LUFS, not the
    -3 dB a full-scale one would, and the first draft of #1420's suite
    asserted that arithmetic, which is to say it asserted a guess."""
    probe = clip("probe-" + name, 0.0, source=source, seconds=seconds)
    base = measured(probe)["i"]
    probe.unlink()
    if base is None:
        raise (SystemExit if AS_SCRIPT else RuntimeError)(
            "cannot measure this build's %s source" % source)
    return clip(name, want_lufs - base, source=source, seconds=seconds)


def measured(path):
    """Integrated loudness, true peak and sample peak of the finished
    file: this suite's own ebur128 run and its own parse of it. No apad
    and no shared regex - agreement with sfx_loudness has to be earned."""
    got = subprocess.run(
        [FFMPEG, "-nostdin", "-hide_banner", "-nostats", "-i", str(path),
         "-map", "0:a:0", "-af", "ebur128=peak=sample+true:framelog=quiet",
         "-f", "null", "-"],
        capture_output=True, text=True, errors="replace")
    log = got.stderr or ""
    row: dict[str, Any] = {"i": None, "tp": None, "peak": None}
    block = None
    for line in log[log.rfind("Summary:"):].splitlines():
        line = line.strip()
        if line.endswith(":") and not line.startswith(("I:", "Peak:")):
            block = line
        words = line.replace(":", " ").split()
        if len(words) >= 2 and words[0] in ("I", "Peak"):
            try:
                value = float(words[1])
            except ValueError:
                continue
            if words[0] == "I" and block == "Integrated loudness:":
                row["i"] = value
            elif block == "True peak:":
                row["tp"] = value
            elif block == "Sample peak:":
                row["peak"] = value
    return row


def mean_of(path):
    """volumedetect's mean - #1420's measure - for the one check that
    says why it was retired."""
    got = subprocess.run(
        [FFMPEG, "-nostdin", "-hide_banner", "-nostats", "-i", str(path),
         "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, errors="replace")
    for line in (got.stderr or "").splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:")[1].split("dB")[0])
    return None


def streams(path):
    """What ffmpeg says is inside - the picture is the half a levelling
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


def picture(path):
    """(codec, [(size, crc) per packet]) of the first video stream, copied
    out as it is stored - so "the picture survived" means the same bytes,
    frame for frame, not merely a video stream of some kind."""
    got = subprocess.run(
        [FFMPEG, "-nostdin", "-hide_banner", "-nostats", "-i", str(path),
         "-map", "0:v:0", "-c", "copy", "-f", "framecrc", "-"],
        capture_output=True, text=True, errors="replace")
    codec = None
    for line in (got.stderr or "").splitlines():
        if "Stream #" in line and ": Video:" in line:
            codec = line.split(": Video:")[1].split()[0].strip(",")
            break
    packets = [tuple(field.strip() for field in row.split(",")[4:6])
               for row in (got.stdout or "").splitlines()
               if row.strip() and not row.startswith("#")]
    return codec, packets


def lu_row(out):
    """What the leveller wrote beside its copy (.lu)."""
    try:
        return json.loads(out.with_name(out.name + ".lu").read_text())
    except (OSError, ValueError):
        return {}


def notes():
    return [p.read_text() for p in LEVELLED.iterdir()
            if p.name.endswith(".asis")]


def levels_like_the_rest(what, src, out):
    """The contract, on a real file: a new copy under the current mark,
    at the target by THIS suite's measure, under the ceiling, the sound
    still in it and the picture the very same packets."""
    check("%s: a new file was made" % what, out != src, True)
    check("%s: under the current mark, by the one spelling of it" % what,
          (out == ns["sfx_video_levelled_name"](src)
           and "-%s-" % ns["SFX_VIDEO_LEVEL_MARK"] in out.name), True)
    got = measured(out)
    near("%s: integrated loudness at the target" % what, got["i"], TARGET,
         LU_SLACK)
    at_most("%s: true peak under the ceiling" % what, got["tp"],
            CEILING + TP_SLACK)
    check("%s: still a picture and a sound" % what, streams(out),
          ["video", "audio"])
    was, now = picture(src), picture(out)
    check("%s: the picture's codec unchanged" % what, now[0], was[0])
    check("%s: every frame still there" % what, len(now[1]), len(was[1]))
    check("%s: and every frame the same bytes (-c:v copy)" % what,
          now[1] == was[1] and len(was[1]) > 0, True)
    row = lu_row(out)
    near("%s: the .lu beside it is the file's own reading" % what,
         row.get("i"), got["i"], 0.3)
    return got, row


try:
    print("--- the slot a clip is given: 'no intermission' is this ---")
    slot = ns["sfx_cycle_slot"]
    FLOOR = ns["SFX_CYCLE_FLOOR"]
    SHORT = ns["SFX_CYCLE_SHORTEST"]
    check("a long clip gets exactly its own length", slot(18.28), 18.28)
    check("and so does a short one", slot(2.02), 2.02)
    # The live ring said `slot 6.00  clip 0.72` after the first deploy:
    # the guard meant for an UNMEASURED clip was firing on a correctly
    # measured very short one and handing it 5.28 s of dark tube - the
    # intermission back again, on the clips where it is proportionally
    # worst.
    check("0.72s is a measurement, not a missing one", slot(0.72), SHORT)
    check("so it must not buy a six second slot", slot(0.72) < 1.0, True)
    # A length we genuinely do not have is the only thing the floor is
    # for; planning zero seconds would stack the queue onto one instant.
    for nothing in (0, None, -3, "nonsense", float("nan")):
        check("no length -> the floor (%r)" % (nothing,), slot(nothing), FLOOR)
    # And the runway is spent in SECONDS while the queue is counted in
    # CLIPS, so the cap has to be loose enough for short clips to reach
    # SFX_CYCLE_AHEAD - at 2 it governed instead, and 2 x 0.72s is 1.5s
    # of runway against a loop that sleeps a whole second.
    check("the clip cap cannot govern the runway any more",
          ns["SFX_CYCLE_QUEUE"] * SHORT >= ns["SFX_CYCLE_AHEAD"], True)

    print("\n--- this suite's namespace answers the shipped code ---")
    # A name the leveller reads that is in neither app.py's slice nor the
    # stubs above is named HERE, before a clip is built.
    missing = sorted(
        name for fn_name in FUNCTIONS
        for name in globals_read(NODES[fn_name])
        if name not in ns and not hasattr(builtins, name))
    check("every global the shipped leveller reads is present", missing, [])

    print("\n--- one target, spelled once ---")
    # #1420's names survive because the gain rule, the say line and
    # /api/sfx/video/mode read them - they must MEAN the loudness target
    # and the true-peak ceiling now, or two targets are back.
    check("SFX_VIDEO_MEAN_DB is the loudness target",
          ns["SFX_VIDEO_MEAN_DB"], TARGET)
    check("SFX_VIDEO_PEAK_DB is the true-peak ceiling",
          ns["SFX_VIDEO_PEAK_DB"], CEILING)
    check("the ceiling leaves the codec room under full scale",
          CEILING < -1.0, True)

    print("\n--- the rule, which is arithmetic on one number ---")
    check("a clip already at the target is not moved",
          round(gain_db(TARGET), 6), 0.0)
    check("six LU under the target is lifted six",
          round(gain_db(TARGET - 6.0), 6), 6.0)
    check("six LU over the target is dropped six",
          round(gain_db(TARGET + 6.0), 6), -6.0)
    check("room noise at -90 is lifted only to the bound",
          gain_db(-90.0), ns["SFX_VIDEO_BOOST_DB"])
    check("full scale is cut only to the bound",
          gain_db(0.0), ns["SFX_VIDEO_CUT_DB"])
    check("an unmeasured clip asks for no gain at all", gain_db(None), 0.0)

    print("\n--- and the peak, which says WHETHER a lift is allowed ---")
    check("a clip printed 30 LU quiet with a normal crest gets all of it",
          round(gain_db(TARGET - 30.0, TARGET - 30.0 + 14.0), 6), 30.0)
    check("silence with a hiss under it gets nothing - #1199 already "
          "calls it empty",
          gain_db(-70.0, SILENT - 1.0), 0.0)
    check("mostly-silence with three loud moments is lifted by its PEAK",
          round(gain_db(-60.0, -8.0), 6),
          round(ns["SFX_VIDEO_PEAK_DB"] + ns["SFX_VIDEO_SQUASH_DB"] + 8.0, 6))
    check("a cut never consults the peak", gain_db(0.0, -0.1),
          ns["SFX_VIDEO_CUT_DB"])
    check("and neither guard fires when there is no peak to read",
          round(gain_db(TARGET - 8.0), 6), 8.0)

    print("\n--- sfx_levels.json's two shapes, which #1199's silence gate "
          "still reads ---")
    check("a pre-#1420 bare peak still reads as a peak",
          ns["_sfx_level_parts"](-6.5), (-6.5, None))
    check("null still means 'could not be measured at all'",
          ns["_sfx_level_parts"](None), (None, None))
    check("a #1420 entry carries both",
          ns["_sfx_level_parts"]({"p": -6.5, "m": -22.0}), (-6.5, -22.0))
    check("and a #1420 entry with no audio carries the peak alone",
          ns["_sfx_level_parts"]({"p": -6.5, "m": None}), (-6.5, None))

    print("\n--- reading ebur128 ---")
    parse = ns["sfx_loudness_parse"]
    check("no summary is no answer, not a zero", parse("frame= 12"), None)
    check("the LAST summary answers, not a line of metadata before it",
          (parse("title: Summary: I: -3.0 LUFS\n[Parsed_ebur128_0] Summary:"
                 "\n  Integrated loudness:\n    I:  -23.4 LUFS\n"
                 "  True peak:\n    Peak:  -9.1 dBFS\n") or {}).get("i"),
          -23.4)
    check("a peak in digital silence parses as -inf, not as a failure",
          (parse("Summary:\n  Integrated loudness:\n    I:  -70.0 LUFS\n"
                 "  Sample peak:\n    Peak:   -inf dBFS\n  True peak:\n"
                 "    Peak:   -inf dBFS\n") or {}).get("tp"), -math.inf)
    probe = clip_at("probe.mp4", TARGET - 9.0, source="speech", seconds=3.0)
    heard, mine = ns["sfx_loudness"](probe), measured(probe)
    near("sfx_loudness reads the loudness this suite reads",
         (heard or {}).get("i"), mine["i"], 0.2)
    near("and the true peak", (heard or {}).get("tp"), mine["tp"], 0.2)
    near("and the sample peak", (heard or {}).get("peak"), mine["peak"], 0.2)
    check("a clip with no sound track answers 'none', not 'no answer'",
          ns["sfx_loudness"](clip("mute-probe.mp4", 0.0, with_sound=False)),
          {"none": True})

    ns["_SFX_VIDEO_LEVEL"].update({"made": 0, "as_is": 0, "failed": 0,
                                   "limited": 0, "dynamic": 0, "stings": 0,
                                   "want": [], "why": ""})

    print("\n--- a clip too quiet to hear: 30 LU under everything else ---")
    # THE CLIP THE OPERATOR COMPLAINED ABOUT in #1420, and still the
    # commonest: printed quiet, with an ordinary crest.
    quiet = clip_at("quiet.mp4", TARGET - 30.0, seconds=3.0)
    near("the fixture really is 30 LU down", measured(quiet)["i"],
         TARGET - 30.0, 0.5)
    check("it is not levelled yet", ns["sfx_level_cached"](quiet), None)
    out = levelled(quiet, make=True)
    levels_like_the_rest("quiet", quiet, out)
    check("the counter says so", ns["_SFX_VIDEO_LEVEL"]["made"], 1)
    check("and it is still served as the container it was",
          out.suffix, ".mp4")
    check("the second ask is the cache, not a second ffmpeg",
          (levelled(quiet, make=True) == out
           and ns["_SFX_VIDEO_LEVEL"]["made"] == 1), True)
    check("the request path's check now finds it settled",
          ns["sfx_level_cached"](quiet), out)
    # #1263: the sting door must never hand a page a wav where it asked
    # for a picture; it hands the levelled CLIP, cache-only.
    check("asked through the sting door, it is the same copy",
          ns["sfx_levelled"](quiet), out)

    print("\n--- one far too loud, and over full scale between samples ---")
    loud = clip_at("loud.mp4", TARGET + 12.0, source="white")
    check("the fixture's true peak really is over the ceiling",
          measured(loud)["tp"] > CEILING, True)
    hot = levelled(loud, make=True)
    levels_like_the_rest("loud", loud, hot)

    print("\n--- speech: a crest the limiter has to catch ---")
    words = clip_at("speech.mp4", TARGET - 12.0, source="speech",
                    seconds=4.0)
    src = measured(words)
    # Past this the linear gain alone would cross the limiter's line, so
    # a clip under it would test the linear road twice and call it speech.
    need = (CEILING - ns["SFX_TP_MARGIN_DB"]) - TARGET
    check("the fixture has the crest of speech (true peak - loudness "
          "> %.0f)" % need, src["tp"] - src["i"] > need + 1.0, True)
    said = levelled(words, make=True)
    _got, row = levels_like_the_rest("speech", words, said)
    check("speech: it went through the limiter, not round it",
          row.get("limited"), True)
    check("speech: and the pass that was kept was measured, not assumed",
          int(row.get("passes") or 0) >= 1, True)

    print("\n--- a long quiet tail: what the mean got wrong ---")
    tail = clip_at("tail.mp4", TARGET - 10.0, source="tail", seconds=10.0)
    t_src = measured(tail)
    # Relative to the same words WITHOUT the room after them, volumedetect
    # reads the tail clip this much quieter than the ear does - and #1420
    # would have lifted it that much past everything else.
    skew = (t_src["i"] - mean_of(tail)) - (src["i"] - mean_of(words))
    check("the fixture: the mean reads it >5 dB quieter than the ear "
          "(%.1f)" % skew, skew > 5.0, True)
    levels_like_the_rest("tail", tail, levelled(tail, make=True))

    print("\n--- a clip already at level is left exactly alone ---")
    ns["_SFX_VIDEO_LEVEL"]["as_is"] = 0
    fine = clip_at("fine.mp4", TARGET)
    same = levelled(fine, make=True)
    check("no second copy of a clip that needs no gain", same, fine)
    check("and it is recorded as looked-at, not as failed",
          (ns["_SFX_VIDEO_LEVEL"]["as_is"], ns["_SFX_VIDEO_LEVEL"]["failed"]),
          (1, 0))
    check("the reason is written down where a human can read it",
          any("already at level" in note and "LUFS" in note
              for note in notes()), True)
    check("and it is never probed again",
          (levelled(fine, make=True) == fine
           and ns["_SFX_VIDEO_LEVEL"]["as_is"] == 1), True)
    check("the request path's check calls it settled, as it is",
          ns["sfx_level_cached"](fine), fine)

    print("\n--- a clip with nothing above the silence line ---")
    # Not the quiet clip, and that is the whole point of the peak guard:
    # this one's loudest moment is under #1199's silence line, so there is
    # nothing in it to make louder. Thirty LU of lift would deliver thirty
    # of hiss.
    hiss = clip("hiss.mp4", -40.0, source="sine")
    check("it really is under the line",
          measured(hiss)["peak"] <= SILENT, True)
    check("so it is served exactly as it was shot",
          levelled(hiss, make=True), hiss)
    check("and the note says WHICH rule refused it, not the wrong one",
          any("silence line" in note for note in notes()), True)

    print("\n--- a clip with no sound in it at all ---")
    silent = clip("silent.mp4", 0.0, with_sound=False)
    check("served as it was shot", levelled(silent, make=True), silent)
    check("and its picture is untouched", streams(silent), ["video"])
    check("the note says there was nothing to measure",
          any("no measurable sound" in note for note in notes()), True)

    print("\n--- a bang in a quiet clip: the peak rule, and its fallback ---")
    shipped_dynamic = ns["SFX_LEVEL_DYNAMIC"]
    FALLBACKS = ("transient", "dynamic", "squeezed")
    bang = clip("bang.mp4", 0.0, source="bang", seconds=4.0)
    b_src = measured(bang)
    check("the fixture's crest is past what the peak rule lets a lift do",
          (TARGET - b_src["i"]) > (CEILING + ns["SFX_VIDEO_SQUASH_DB"]
                                   - b_src["tp"]), True)
    # SFX_LEVEL_DYNAMIC=0 keeps #1420's rule absolute: quieter than the
    # rest, never over the ceiling, never flattened.
    ns["SFX_LEVEL_DYNAMIC"] = False
    strict = levelled(bang, make=True)
    s_got, s_row = measured(strict), lu_row(strict)
    at_most("dynamic off: never over the ceiling", s_got["tp"],
            CEILING + TP_SLACK)
    check("dynamic off: it arrives quieter rather than flattened",
          s_got["i"] < TARGET - ns["SFX_LEVEL_DYNAMIC_LU"], True)
    check("dynamic off: by the linear road alone",
          s_row.get("how") in ("linear", "limited"), True)
    strict.unlink()
    strict.with_name(strict.name + ".lu").unlink(missing_ok=True)
    ns["SFX_LEVEL_DYNAMIC"] = True
    ns["_SFX_VIDEO_LEVEL"]["dynamic"] = 0
    loose = levelled(bang, make=True)
    l_got, l_row = measured(loose), lu_row(loose)
    near("dynamic on: the bang no longer holds the words down",
         l_got["i"], TARGET, LU_SLACK)
    at_most("dynamic on: and still never over the ceiling", l_got["tp"],
            CEILING + TP_SLACK)
    check("dynamic on: by a fallback, and the counter says so",
          (l_row.get("how") in FALLBACKS,
           ns["_SFX_VIDEO_LEVEL"]["dynamic"]), (True, 1))
    check("dynamic on: the picture is still the same bytes",
          picture(loose)[1] == picture(bang)[1], True)
    print("   bang: %.1f LUFS -> off %.1f (%s), on %.1f (%s)"
          % (b_src["i"], s_got["i"], s_row.get("how"), l_got["i"],
             l_row.get("how")))

    print("\n--- and one no fallback can help: none of them is kept ---")
    crackle = clip("crackle.mp4", 0.0, source="crackle", seconds=4.0)
    rough = levelled(crackle, make=True)
    r_got, r_row = measured(rough), lu_row(rough)
    check("the fallbacks were tried (more than one pass written)",
          int(r_row.get("passes") or 0) > 1, True)
    check("and thrown away, because none was better",
          r_row.get("how") in ("linear", "limited"), True)
    at_most("so it is under the ceiling where the peak rule left it",
            r_got["tp"], CEILING + TP_SLACK)
    ns["SFX_LEVEL_DYNAMIC"] = shipped_dynamic

    print("\n--- the request path never waits on an ffmpeg ---")
    ns["_SFX_VIDEO_LEVEL"]["want"] = []
    fresh = clip("fresh.mp4", -30.0)
    check("a miss plays the clip as it is", levelled(fresh, make=False),
          fresh)
    check("AND asks for a copy, or nothing would ever level it",
          ns["_SFX_VIDEO_LEVEL"]["want"], [fresh.as_posix()])
    levelled(fresh, make=False)
    check("asked once, however many times it airs",
          ns["_SFX_VIDEO_LEVEL"]["want"].count(fresh.as_posix()), 1)
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

    print("\n--- the sting road: a wav, to the same target ---")
    ns["_SFX_VIDEO_LEVEL"]["stings"] = 0
    wav = sting("sting.wav", -15.0)
    w_out = ns["sfx_levelled"](wav)
    check("a levelled copy under the v4 (loudness) name",
          (w_out != wav and "-v4-v20-" in w_out.name
           and w_out == ns["sfx_levelled_name"](wav)), True)
    check("by the loudness road, not the RMS fallback",
          ns["_SFX_VIDEO_LEVEL"]["stings"], 1)
    w_got = measured(w_out)
    near("the sting: integrated loudness at the target", w_got["i"], TARGET,
         LU_SLACK)
    at_most("the sting: true peak under the ceiling", w_got["tp"],
            CEILING + TP_SLACK)
    # The road the cadence welds an mp4's sound through: decoded by
    # _as_wav, then levelled as a sting - most of what the board plays.
    welded = ns["sfx_levelled"](ns["_as_wav"](words))
    near("an mp4's sound through _as_wav lands there too",
         measured(welded)["i"], TARGET, LU_SLACK)

    print("\n--- the copies are pruned; an old mark's are never served "
          "again ---")
    old = ns["SFX_VIDEO_LEVEL_OLD_MARKS"]
    check("#1420's mark is one of the retired ones", "lvl1" in old, True)
    # Spelled here, not read from the tuple: a tuple that lost "lvl1"
    # must fail this too, not quietly build no stale files to look for.
    stale = [LEVELLED / ("%s-lvl1-1.mp4" % ("0" * 16))]
    stale += [p.with_name(p.name + ".asis") for p in stale]
    for path in stale:
        path.write_text("made under a retired rule")
    ns["SFX_VIDEO_LEVEL_KEEP"] = 2
    ns["_sfx_video_level_prune"]()
    ns["SFX_VIDEO_LEVEL_KEEP"] = 400
    here = {p.name for p in LEVELLED.iterdir()}
    mark = "-%s-" % ns["SFX_VIDEO_LEVEL_MARK"]
    check("a copy (and its flag) under #1420's lvl1 mark is gone",
          [p.name for p in stale if p.name in here], [])
    copies = [n for n in here if mark in n and n.endswith(".mp4")]
    check("bounded by count", len(copies) <= 2, True)
    check("a pruned copy's .lu went with it",
          sorted(n for n in here if n.endswith(".lu")
                 and n[:-3] not in here), [])
    check("the .asis markers are kept - they are what stops a re-probe",
          any(mark in n and n.endswith(".asis") for n in here), True)
    check("and the sting road's wavs are not the prune's to touch",
          w_out.name in here, True)

    print("\n--- what the operator reads ---")
    say = ns["_sfx_video_level_say"]()
    check("the line names the target", "%.0f dB LUFS" % TARGET in say, True)
    check("and says how many were levelled", "levelled" in say, True)
    print("   %s" % say.strip(" —"))
finally:
    shutil.rmtree(ROOM, ignore_errors=True)

print("\n%d checks failed" % len(fails))
for line in fails:
    print("  " + line)


class SfxVideoLevelContract(unittest.TestCase):
    """The loudness contract above, as a runner sees it.

    Every check has already run - at import - by the time the runner
    collects this; this is their verdict, every failed check named."""

    def test_every_check_of_the_loudness_contract_passes(self):
        self.assertEqual(fails, [], "%d checks failed:\n  %s"
                         % (len(fails), "\n  ".join(fails)))


if __name__ == "__main__":
    raise SystemExit(1 if fails else 0)

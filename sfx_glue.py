"""sfx_glue — two short clips joined into one, and one clip edited in place.

TARGET (new file): sfx_glue.py  (repo root, next to app.py, imported by it)

#1243  "I want to add buttons on the left and right side of this window for
       glue ... glue the clip to the previous clip or the next clip where they
       basically become merged together. The issue that is coming up is some of
       the clips are too short, so I actually need to merge the clips with the
       clip next door."

#1223  "I had an option for edit that brings up a pop-up window where I can
       adjust the in and out points of the clip and have that overwrite and
       save and replace the original clip."

WHY THIS IS A MODULE AND NOT MORE OF app.py.  Everything here is either a
PURE COMMAND BUILDER or PURE BOOKKEEPING over a JSON ledger, and both are
things that must be tested without a station, a share or an ffmpeg.  app.py
keeps the four routes and the clip-book writes - the parts that need the
station - and hands the work down here.

THREE FACTS THIS FILE IS BUILT AROUND, none of them re-derived:

  * the samples share is mounted READ-ONLY in the container, so a clip on
    the share can never be overwritten in place.  A glued clip is therefore
    always a NEW file under data/sfx/glued, and an edit of a share clip is a
    new file under data/sfx/edited.  Nothing is ever unlinked by either road.
  * the endless set's slot IS the clip (#1423), so a 0.72 s clip is a
    0.72 s slot.  That is the whole reason for gluing: a joined clip is a
    longer slot, not merely a longer file.
  * the station bundles the imageio-ffmpeg STATIC BINARY and no ffprobe, so
    every probe here goes through PyAV (which the container has) and falls
    back to reading ffmpeg's own banner off stderr.

THE ORIGINALS ARE NEVER DELETED.  They are marked `superseded` in a ledger
(data/sfx_glue.json); app.py folds that set into the two places a clip is
judged drawable - the sting draw and the clip book's index - so the SFX guy
and the endless set draw the glued clip instead of the shorts, and a glue
can be undone by taking one line out of a JSON file.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

MARK = "[#1243]"

# The two folders this module owns, relative to the station's data root.
GLUED_UNDER = ("sfx", "glued")
EDITED_UNDER = ("sfx", "edited")

# What the joined file is written as.  One container, one codec pair, so a
# chain of glues (A+B, then (A+B)+C) can always take the cheap road on the
# second hop: the first hop already normalised the parts it wrote.
OUT_SUFFIX = ".mp4"
OUT_VCODEC = "libx264"
OUT_ACODEC = "aac"
OUT_RATE = 48000
OUT_CHANNELS = 2
OUT_FPS = 30

# A container ffmpeg can concatenate with `-c copy` and the station can serve.
COPY_CONTAINERS = {".mp4", ".m4v", ".mov"}
# What the station's video editor can open at all.  probe() in video_editor.py
# passes -format_whitelist mov,matroska,webm, so anything else has to be
# transcoded on the way in rather than refused.
EDITOR_CONTAINERS = {".mp4", ".m4v", ".mov", ".mkv", ".webm"}


# --------------------------------------------------------------------------
# Probing.  Everything below wants the same six facts about a file.
# --------------------------------------------------------------------------

def blank_probe() -> dict[str, Any]:
    return {"seconds": 0.0, "vcodec": "", "width": 0, "height": 0,
            "pix_fmt": "", "fps": 0.0, "has_audio": False, "acodec": "",
            "sample_rate": 0, "channels": 0, "why": ""}


def probe(path: Any, ffmpeg: str = "") -> dict[str, Any]:
    """What is in this file.  PyAV first; ffmpeg's banner as the fallback.

    Never raises: a file that will not open comes back as a blank probe with
    `why` set, and every caller treats "I could not read it" as "re-encode",
    which is the safe answer rather than the fast one.
    """
    out = blank_probe()
    try:
        import av                                   # noqa: PLC0415
        with av.open(str(path)) as container:
            video = container.streams.video[0] if container.streams.video else None
            audio = container.streams.audio[0] if container.streams.audio else None
            seconds = 0.0
            if container.duration:
                seconds = float(container.duration) / 1000000.0
            if not seconds and video is not None and video.duration:
                seconds = float(video.duration * video.time_base)
            out["seconds"] = round(max(0.0, seconds), 3)
            if video is not None:
                ctx = video.codec_context
                out["vcodec"] = str(getattr(ctx, "name", "") or "")
                out["width"] = int(getattr(ctx, "width", 0) or 0)
                out["height"] = int(getattr(ctx, "height", 0) or 0)
                out["pix_fmt"] = str(getattr(ctx, "pix_fmt", "") or "")
                try:
                    out["fps"] = round(float(video.average_rate or 0), 3)
                except Exception:               # noqa: BLE001
                    out["fps"] = 0.0
            if audio is not None:
                ctx = audio.codec_context
                out["has_audio"] = True
                out["acodec"] = str(getattr(ctx, "name", "") or "")
                out["sample_rate"] = int(getattr(ctx, "sample_rate", 0) or 0)
                try:
                    out["channels"] = int(getattr(audio, "channels", 0)
                                          or getattr(ctx, "channels", 0) or 0)
                except Exception:               # noqa: BLE001
                    out["channels"] = 0
        return out
    except Exception as err:                        # noqa: BLE001
        out["why"] = "%s: %s" % (type(err).__name__, str(err)[:120])
    if not ffmpeg:
        return out
    return probe_banner(path, ffmpeg, out)


def probe_banner(path: Any, ffmpeg: str, out: dict[str, Any] | None = None) -> dict[str, Any]:
    """ffmpeg -i, read off stderr.  Coarse, and only ever the fallback."""
    got = out if out is not None else blank_probe()
    try:
        proc = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", str(path)],
                              capture_output=True, timeout=30, check=False)
        text = proc.stderr.decode("utf-8", "replace")
    except Exception as err:                        # noqa: BLE001
        got["why"] = "%s: %s" % (type(err).__name__, str(err)[:120])
        return got
    got.update(parse_banner(text))
    return got


def parse_banner(text: str) -> dict[str, Any]:
    """The facts, out of ffmpeg's own words.  Pure, so it is testable."""
    found: dict[str, Any] = {}
    dur = re.search(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)", text)
    if dur:
        found["seconds"] = round(int(dur.group(1)) * 3600
                                 + int(dur.group(2)) * 60
                                 + float(dur.group(3)), 3)
    vid = re.search(r"Stream #\d+:\d+.*?:\s*Video:\s*([A-Za-z0-9_]+)[^\n]*", text)
    if vid:
        found["vcodec"] = vid.group(1)
        line = vid.group(0)
        size = re.search(r"\b(\d{2,5})x(\d{2,5})\b", line)
        if size:
            found["width"] = int(size.group(1))
            found["height"] = int(size.group(2))
        pix = re.search(r"Video:\s*[A-Za-z0-9_]+[^,]*,\s*([a-z0-9]+)", line)
        if pix:
            found["pix_fmt"] = pix.group(1)
        fps = re.search(r"([\d.]+)\s*fps", line)
        if fps:
            found["fps"] = round(float(fps.group(1)), 3)
    aud = re.search(r"Stream #\d+:\d+.*?:\s*Audio:\s*([A-Za-z0-9_]+)[^\n]*", text)
    if aud:
        found["has_audio"] = True
        found["acodec"] = aud.group(1)
        line = aud.group(0)
        rate = re.search(r"(\d+)\s*Hz", line)
        if rate:
            found["sample_rate"] = int(rate.group(1))
        if "stereo" in line:
            found["channels"] = 2
        elif "mono" in line:
            found["channels"] = 1
    return found


# --------------------------------------------------------------------------
# The join itself.
# --------------------------------------------------------------------------

def glue_mode(first: dict[str, Any], second: dict[str, Any],
              containers: tuple[str, str] = ("", "")) -> tuple[str, str]:
    """'copy' or 'encode', and the reason in the operator's own words.

    A stream copy is only honest when the two clips agree on EVERY field the
    concat demuxer refuses to bridge: codec, picture size, pixel format and
    the shape of the sound.  Anything less and the join produces a file that
    plays the first clip and then shows a frozen frame - which is worse than
    a slower join, because nothing says so.
    """
    a, b = first or {}, second or {}
    why: list[str] = []
    if containers[0] and containers[0].lower() not in COPY_CONTAINERS:
        why.append("the first clip is a %s" % containers[0].lower().lstrip("."))
    if containers[1] and containers[1].lower() not in COPY_CONTAINERS:
        why.append("the second clip is a %s" % containers[1].lower().lstrip("."))
    if not a.get("vcodec") or not b.get("vcodec"):
        why.append("one of them would not say what it is")
    elif a.get("vcodec") != b.get("vcodec"):
        why.append("%s against %s" % (a.get("vcodec"), b.get("vcodec")))
    if (a.get("width"), a.get("height")) != (b.get("width"), b.get("height")):
        why.append("%sx%s against %sx%s" % (a.get("width"), a.get("height"),
                                            b.get("width"), b.get("height")))
    elif not a.get("width"):
        why.append("neither has a picture size")
    if a.get("pix_fmt") != b.get("pix_fmt"):
        why.append("different colour formats")
    if bool(a.get("has_audio")) != bool(b.get("has_audio")):
        why.append("one has sound and the other does not")
    elif a.get("has_audio"):
        if a.get("acodec") != b.get("acodec"):
            why.append("%s against %s sound" % (a.get("acodec"), b.get("acodec")))
        if a.get("sample_rate") != b.get("sample_rate"):
            why.append("%s Hz against %s Hz" % (a.get("sample_rate"),
                                                b.get("sample_rate")))
        if a.get("channels") != b.get("channels"):
            why.append("different channel counts")
    if why:
        return "encode", "re-encoded: " + "; ".join(why)
    return "copy", "copied straight through: they already match"


def concat_list_text(paths: list[Any]) -> str:
    """The concat demuxer's own little file.  Single quotes are doubled,
    which is exactly the escaping that format defines."""
    out = []
    for one in paths:
        out.append("file '%s'" % str(one).replace("'", "'\\''"))
    return "\n".join(out) + "\n"


def copy_command(list_file: Any, target: Any, ffmpeg: str) -> list[str]:
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", "-movflags", "+faststart", str(target)]


def encode_command(parts: list[dict[str, Any]], target: Any, ffmpeg: str) -> list[str]:
    """One timeline out of N clips, normalised so the join cannot glitch.

    `parts` are {"path", "seconds", "has_audio", "width", "height"}.  Every
    picture is scaled into one frame and padded rather than stretched - a
    4:3 clip joined onto a 16:9 one keeps its shape with bars, which is what
    the set already does with a clip that does not fill the tube - and every
    clip that has no sound is given silence of its own length, because
    concat=a=1 refuses a timeline where the streams do not line up.
    """
    n = len(parts)
    if n < 2:
        raise ValueError("a join needs at least two clips")
    want_audio = any(bool(p.get("has_audio")) for p in parts)
    width = max(2, max(int(p.get("width") or 0) for p in parts)) // 2 * 2
    height = max(2, max(int(p.get("height") or 0) for p in parts)) // 2 * 2
    if width < 2 or height < 2:
        width, height = 640, 360
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-threads", "2", "-filter_threads", "1", "-filter_complex_threads", "1"]
    for part in parts:
        cmd += ["-i", str(part["path"])]
    silence: dict[int, int] = {}
    if want_audio:
        for ix, part in enumerate(parts):
            if part.get("has_audio"):
                continue
            silence[ix] = n + len(silence)
            cmd += ["-f", "lavfi", "-t", "%.3f" % max(0.05, float(part.get("seconds") or 0.1)),
                    "-i", "anullsrc=channel_layout=stereo:sample_rate=%d" % OUT_RATE]
    graph: list[str] = []
    for ix in range(n):
        graph.append(
            "[%d:v:0]scale=%d:%d:force_original_aspect_ratio=decrease,"
            "pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=%d,format=yuv420p[v%d]"
            % (ix, width, height, width, height, OUT_FPS, ix))
    if want_audio:
        for ix in range(n):
            src = silence.get(ix, ix)
            graph.append(
                "[%d:a:0]aresample=%d,aformat=sample_fmts=fltp:"
                "channel_layouts=stereo[a%d]" % (src, OUT_RATE, ix))
    join = "".join("[v%d][a%d]" % (i, i) if want_audio else "[v%d]" % i
                   for i in range(n))
    graph.append("%sconcat=n=%d:v=1:a=%d[v]%s"
                 % (join, n, 1 if want_audio else 0, "[a]" if want_audio else ""))
    cmd += ["-filter_complex", ";".join(graph), "-map", "[v]",
            "-c:v", OUT_VCODEC, "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p"]
    if want_audio:
        cmd += ["-map", "[a]", "-c:a", OUT_ACODEC, "-b:a", "160k",
                "-ar", str(OUT_RATE), "-ac", str(OUT_CHANNELS)]
    else:
        cmd += ["-an"]
    return cmd + ["-map_metadata", "-1", "-movflags", "+faststart", str(target)]


def glue_command(parts: list[dict[str, Any]], target: Any, mode: str,
                 ffmpeg: str, list_file: Any = None) -> list[str]:
    """The one door both roads go through, so a caller never picks flags."""
    if mode == "copy":
        if not list_file:
            raise ValueError("a copied join needs its list file")
        return copy_command(list_file, target, ffmpeg)
    return encode_command(parts, target, ffmpeg)


# --------------------------------------------------------------------------
# Naming.
# --------------------------------------------------------------------------

def glued_stem(first: str, second: str, cap: int = 90) -> str:
    """'2199 clip + 2200 out real', trimmed so a file name stays a name."""
    a = re.sub(r"\s+", " ", str(first or "clip")).strip()
    b = re.sub(r"\s+", " ", str(second or "clip")).strip()
    stem = "%s + %s" % (a[:cap // 2] or "clip", b[:cap // 2] or "clip")
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", stem).strip(" .")
    return stem[:cap] or "glued clip"


def free_path(folder: Any, stem: str, suffix: str = OUT_SUFFIX) -> Path:
    """A path nothing is using yet.  Never overwrites: a second glue of the
    same pair is caught by the ledger, and anything that reaches here is a
    different join that deserves a file of its own."""
    folder = Path(folder)
    candidate = folder / (stem + suffix)
    if not candidate.exists():
        return candidate
    for n in range(2, 500):
        candidate = folder / ("%s (%d)%s" % (stem, n, suffix))
        if not candidate.exists():
            return candidate
    return folder / ("%s-%d%s" % (stem, int(time.time()), suffix))


# --------------------------------------------------------------------------
# The ledger.  Pure functions over a plain dict, so the bookkeeping is
# testable without a disk.
# --------------------------------------------------------------------------

def ledger_empty() -> dict[str, Any]:
    return {"glued": [], "superseded": {}}


def ledger_clean(raw: Any) -> dict[str, Any]:
    """Whatever was on disk, shaped into the ledger this module expects."""
    if not isinstance(raw, dict):
        return ledger_empty()
    glued = raw.get("glued")
    sup = raw.get("superseded")
    return {"glued": [r for r in glued if isinstance(r, dict)] if isinstance(glued, list) else [],
            "superseded": {str(k): str(v) for k, v in sup.items()} if isinstance(sup, dict) else {}}


def ledger_rebuild(book: Any) -> dict[str, Any]:
    """The superseded map, DERIVED from the rows rather than stored beside
    them.

    It was stored, and that is a fault this module found in its own test:
    undoing the second join of a chain (A+B, then (A+B)+C) removed every
    mapping that pointed at the head, and A and B came back on the air
    even though A+B was still there standing in front of them.  A map that
    is re-derived every time a row moves cannot disagree with the rows.

    Rows are in the order they were made, so the LAST join to claim a clip
    wins - which is the newest head, which is the one that plays.
    """
    clean = ledger_clean(book)
    sup: dict[str, str] = {}
    for row in clean["glued"]:
        head = str(row.get("id") or "")
        if not head:
            continue
        for one in (row.get("supersedes") or []):
            one = str(one)
            if one and one != head:
                sup[one] = head
    return {"glued": clean["glued"], "superseded": sup}


def ledger_superseded(book: Any) -> set[str]:
    """Every clip id that a glue or an edit has replaced."""
    return set(ledger_rebuild(book)["superseded"].keys())


def ledger_find(book: Any, part_ids: list[str]) -> dict[str, Any] | None:
    """The glue that already joined exactly these clips, in this order.

    This is what makes the button IDEMPOTENT: pressing Glue twice on the
    same pair gives back the same clip rather than a second copy of it.
    """
    want = [str(p) for p in part_ids]
    for row in ledger_clean(book)["glued"]:
        if [str(p) for p in (row.get("part_ids") or [])] == want:
            return row
    return None


def ledger_by_id(book: Any, sid: str) -> dict[str, Any] | None:
    for row in ledger_clean(book)["glued"]:
        if str(row.get("id") or "") == str(sid):
            return row
    return None


def ledger_flatten(book: Any, sid: str, depth: int = 12) -> list[str]:
    """Every ORIGINAL underneath a clip, however many joins deep.

    The leaves only - the real files off the share - which is what a
    report wants to name.  For what the new clip must STAND IN FRONT OF,
    use ledger_stack: that one includes the joins in between.
    """
    row = ledger_by_id(book, sid)
    if row is None or depth <= 0:
        return [str(sid)]
    out: list[str] = []
    for part in (row.get("part_ids") or []):
        for one in ledger_flatten(book, str(part), depth - 1):
            if one not in out:
                out.append(one)
    return out or [str(sid)]


def ledger_stack(book: Any, sid: str, depth: int = 12) -> list[str]:
    """Everything underneath a clip INCLUDING the joins in between, and
    the clip itself.

    A+B glued to C must stand A, B, C AND the A+B join down.  Standing
    only the originals down leaves the intermediate join drawable, and the
    set then plays both A+B and A+B+C - the same sound twice, from two
    files, which is exactly the repeat the operator has complained about
    from the other direction.
    """
    out: list[str] = [str(sid)]
    row = ledger_by_id(book, sid)
    if row is None or depth <= 0:
        return out
    for part in (row.get("part_ids") or []):
        for one in ledger_stack(book, str(part), depth - 1):
            if one not in out:
                out.append(one)
    return out


def ledger_add(book: Any, record: dict[str, Any]) -> dict[str, Any]:
    """A new glued (or edited) clip, and the ids it stands in front of.

    Returns a NEW dict; the caller writes it.  Re-adding the same id is a
    replace rather than a second row, so a retry cannot double the book.
    """
    clean = ledger_clean(book)
    sid = str(record.get("id") or "")
    if not sid:
        raise ValueError("a ledger row needs an id")
    rows = [r for r in clean["glued"] if str(r.get("id") or "") != sid]
    rows.append(dict(record))
    return ledger_rebuild({"glued": rows[-4000:], "superseded": {}})


def ledger_drop(book: Any, sid: str) -> dict[str, Any]:
    """Undo one glue: the row goes, and the map is derived again from what
    is left - so a clip that a SURVIVING join still stands in front of
    stays down, and only the ones nothing covers any more come back."""
    clean = ledger_clean(book)
    rows = [r for r in clean["glued"] if str(r.get("id") or "") != str(sid)]
    return ledger_rebuild({"glued": rows, "superseded": {}})


# --------------------------------------------------------------------------
# #1223 - the edit, and where its answer is allowed to land.
# --------------------------------------------------------------------------

def under(path: Any, root: Any) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (ValueError, OSError):
        return False


def writable_here(path: Any) -> bool:
    """Whether this process could really rewrite this file.

    os.access on the FILE and on its folder both, because the share is
    mounted read-only: the file bit can look right while the mount refuses
    every write on it (EROFS is a property of the mount, not the inode).
    """
    try:
        p = Path(path)
        return bool(os.access(p, os.W_OK) and os.access(p.parent, os.W_OK))
    except OSError:
        return False


def edit_plan(source: Any, data_root: Any, edited_dir: Any,
              audio_only: bool = False) -> dict[str, Any]:
    """Where "Save over the original" is going to put the answer, and the
    sentence the editor prints BEFORE the operator presses it.

    Pure: it takes the two roots rather than reading the station's settings,
    so the decision can be tested on a temp directory.
    """
    src = Path(source)
    suffix = src.suffix.lower()
    keep_sound_only = bool(audio_only)
    in_place = under(src, data_root) and writable_here(src)
    if in_place and not keep_sound_only and suffix not in COPY_CONTAINERS:
        # An edit comes back as H.264 in MP4.  Writing those bytes over a
        # file still called .webm would leave a clip whose name lies about
        # what is inside it, and every reader of this library trusts the
        # suffix.  So that one goes beside it instead.
        in_place = False
    if in_place:
        target = src
        say = ("this clip lives in the station's own data folder, so saving "
               "writes over it in place")
    else:
        stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", src.stem).strip(" .") or "clip"
        out_suffix = suffix if keep_sound_only else OUT_SUFFIX
        target = free_path(edited_dir, stem, out_suffix)
        say = ("this clip is on the read-only samples share, so the station "
               "cannot write over it. Saving keeps the original exactly "
               "where it is and puts the edited copy in the station's own "
               "folder, and the edited one is what goes on the air from now on")
    return {"in_place": bool(in_place), "target": str(target),
            "suffix": target.suffix.lower(), "audio_only": keep_sound_only,
            "say": say}


def adopt_command(source: Any, target: Any, ffmpeg: str,
                  audio_only: bool = False, seconds: float = 0.0) -> list[str]:
    """Put a clip in front of the station's video editor.

    The editor opens mov/matroska/webm only and always wants a picture.  A
    video in one of those containers is copied byte for byte by the caller
    and never reaches here; anything else is transcoded, and a SOUND-ONLY
    clip is given a picture of its own waveform so the same timeline, the
    same in and out handles and the same scrubbing work on it.
    """
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-threads", "2", "-i", str(source)]
    if audio_only:
        length = max(0.2, float(seconds or 0))
        cmd += ["-filter_complex",
                "[0:a]showwaves=s=960x360:mode=cline:rate=%d:colors=0x65c7da,"
                "format=yuv420p[v]" % OUT_FPS,
                "-map", "[v]", "-map", "0:a:0", "-t", "%.3f" % length]
    else:
        cmd += ["-map", "0:v:0", "-map", "0:a?",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p"]
    cmd += ["-c:v", OUT_VCODEC, "-preset", "veryfast", "-crf", "20",
            "-c:a", OUT_ACODEC, "-b:a", "160k", "-ar", str(OUT_RATE)]
    return cmd + ["-movflags", "+faststart", str(target)]


def sound_back_command(source: Any, target: Any, ffmpeg: str) -> list[str]:
    """The edited waveform video, turned back into the sound it came from.

    A sound-only clip that goes into the editor must come out as a sound,
    not as a little film of a waveform: the sampler pads, the SFX guy and
    the satellite all expect the file they had.  The codec is chosen from
    the target's own suffix so a .wav stays a .wav and an .mp3 stays an mp3.
    """
    suffix = Path(target).suffix.lower()
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-i", str(source), "-vn", "-map", "0:a:0"]
    if suffix == ".wav":
        cmd += ["-c:a", "pcm_s16le", "-ar", "48000"]
    elif suffix in (".mp3",):
        cmd += ["-c:a", "libmp3lame", "-q:a", "2"]
    elif suffix in (".flac",):
        cmd += ["-c:a", "flac"]
    elif suffix in (".ogg", ".oga"):
        cmd += ["-c:a", "libvorbis", "-q:a", "5"]
    else:
        cmd += ["-c:a", OUT_ACODEC, "-b:a", "192k"]
    return cmd + [str(target)]


# --------------------------------------------------------------------------
# Running one command.  The only impure thing in this file besides probe().
# --------------------------------------------------------------------------

def run(cmd: list[str], timeout: float = 600.0) -> tuple[bool, str]:
    """(ok, what went wrong).  Never raises, and never blocks the loop -
    every caller in app.py is already on a thread."""
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return False, "it took longer than %d seconds and was stopped" % int(timeout)
    except OSError as err:
        return False, "ffmpeg would not start: %s" % str(err)[:160]
    if proc.returncode:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        return False, (tail[-1][:300] if tail else "ffmpeg failed with no message")
    return True, ""


def join(first: Any, second: Any, folder: Any, ffmpeg: str,
         names: tuple[str, str] = ("", ""), timeout: float = 600.0,
         progress: Any = None) -> dict[str, Any]:
    """Join two clips into one new file under `folder`.

    Returns {"ok", "path", "mode", "why", "seconds", "parts"}.  Nothing here
    touches the clip book, the ledger or the station: the caller owns all
    three, which is what lets this be run against two files in /tmp.
    """
    def note(text: str) -> None:
        if progress:
            try:
                progress(text)
            except Exception:                       # noqa: BLE001
                pass

    first, second = Path(first), Path(second)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    note("reading both clips...")
    a = probe(first, ffmpeg)
    b = probe(second, ffmpeg)
    mode, why = glue_mode(a, b, (first.suffix, second.suffix))
    stem = glued_stem(names[0] or first.stem, names[1] or second.stem)
    target = free_path(folder, stem)
    parts = [{"path": first, "seconds": a["seconds"], "has_audio": a["has_audio"],
              "width": a["width"], "height": a["height"]},
             {"path": second, "seconds": b["seconds"], "has_audio": b["has_audio"],
              "width": b["width"], "height": b["height"]}]
    list_file = None
    if mode == "copy":
        list_file = target.with_suffix(".concat.txt")
        list_file.write_text(concat_list_text([first, second]), encoding="utf-8")
    note("joining them - " + why)
    ok, err = run(glue_command(parts, target, mode, ffmpeg, list_file), timeout)
    if not ok and mode == "copy":
        # The copy road is the guess; the encode road is the answer.  A
        # concat demuxer that refuses is not a failure to report, it is a
        # reason to take the slower road, and the operator hears which.
        note("they would not join straight through - re-encoding...")
        mode, why = "encode", "re-encoded: the straight join was refused"
        ok, err = run(glue_command(parts, target, mode, ffmpeg, None), timeout)
    if list_file is not None:
        try:
            list_file.unlink()
        except OSError:
            pass
    if not ok:
        try:
            target.unlink()
        except OSError:
            pass
        return {"ok": False, "path": "", "mode": mode, "why": err,
                "seconds": 0.0, "parts": [a, b]}
    note("measuring the new clip...")
    made = probe(target, ffmpeg)
    seconds = made["seconds"]
    if seconds <= 0:
        seconds = round(float(a["seconds"]) + float(b["seconds"]), 3)
    return {"ok": True, "path": str(target), "mode": mode, "why": why,
            "seconds": round(float(seconds), 3), "parts": [a, b],
            "measured": made}


def read_book(path: Any) -> dict[str, Any]:
    try:
        return ledger_clean(json.loads(Path(path).read_text(encoding="utf-8")))
    except Exception:                               # noqa: BLE001
        return ledger_empty()


def write_book(path: Any, book: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger_clean(book), indent=1), encoding="utf-8")
    tmp.replace(path)

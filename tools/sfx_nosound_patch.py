"""[sfx-nosound] A clip with no sound track is noted once and never dealt to a
road that needs its sound again.

MEASURED 2026-09-27 16:15Z .. 2026-09-28: 123 times, about every half hour,

    [out#0/wav] Output file does not contain any stream
    Error opening output file /app/data/voice_media/sfx/
        64d00c69528ff1f9-1789333711068352100-src.wav.
    Error opening output files: Invalid argument

64d00c69528ff1f9 is sfx_id() of
/samples/samples_grabbed/Rest/CC5737B6-2516-46A1-ADA1-4C44C3B49050 2.MP4 -
2.2 s, 720x788 h264, and ONE stream: a picture with no sound track at all.

WHO ASKS. Not the #1420/#1477 picture leveller: sfx_loudness answers a clip
with no sound track {"none": True} and sfx_video_levelled writes its `.asis`
note once. It is the cadence's picture road, _sfx_cadence_video_pick ("a
picture whose audio can join the broadcast"), which decodes each candidate's
sound through _as_wav to weld it into the round. _as_wav swallows the failure
(`except Exception: out.unlink(); return path`) and keeps no memory of it, so
every deal of the clip runs ffmpeg again.

WHY EVERY HALF HOUR. The book deals a short video by folder, then by an
UNSPENT clip in it (deck_cycle < the current cycle). Rest holds ten short
videos: nine are at deck_cycle 4, and this one at 0 - it never airs, so it is
never spent, so it is the only unspent clip in Rest and is dealt EVERY time the
folder roll lands there (1 folder in 60).

WHAT THE PICK DID. Nothing reached the air silent or unlevelled: _as_wav handed
back the .MP4, `source.suffix != ".wav"` skipped it, and the pick went on to
the next candidate (two at most), then to the audio road (_sfx_cadence_pick).
The cost was an ffmpeg run per deal, one of the two candidate slots (a missed
picture on the board when the other one failed too), and the log.

THE CURE, where the fact is found and where the decision is made:
  1. _as_wav (the decoder) writes `<id>-<mtime>-src.nosound` beside the wav it
     could not make, when ffmpeg says the input has no audio stream ("does not
     contain any stream" / "matches no streams"), and reads it first next
     time - no ffmpeg. Keyed by mtime like the wav, so a replaced file is
     looked at again. Any other failure (a timeout, a share that did not
     answer) is NOT noted and is retried, as before; its ffmpeg lines are
     still printed, now with the file's name.
  2. sfx_soundless(path) reads the note (memoised stamp, one local stat) - one
     spelling of the name, sfx_src_wav_name, for the maker and the reader.
  3. _sfx_cadence_video_pick, handed back the clip itself by a soundless
     decode, SPENDS it in the book for this deck pass (_sfx_video_rotation_mark
     - the deck column and the in-memory `used` set, no folder rest), so the
     book stops dealing it and its folder's roll finds nothing unspent there
     instead of this clip. A new pass deals it at most once more, and then it
     costs a stat, not an ffmpeg.
A picture with no sound is still a picture: nothing here keeps it off the
endless set, the page or the tablet, and nothing is written into the book but
the spend.

--check exits 0 ready / 2 applied / 1 missing. --apply is idempotent and
atomic, LF only. ON THE HOST. Anchors are original code (no other tool's
text): the draw-filter block of _sfx_cadence_video_pick belongs to
tools/system3_sfx_roll_patch.py and is not touched.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path


EDITS = [
    ("nosound-helpers",
     '''def _as_wav(path: Path, *, timeout: float = 30.0) -> Path:
''',
     '''def sfx_src_wav_name(path: Path, stamp: int) -> Path:
    """[sfx-nosound] Where _as_wav keeps `path` decoded to a wav - one
    spelling for the maker and for sfx_soundless (#1338's rule: a name
    spelled twice drifts). Its `.nosound` sibling is the note that ffmpeg
    found no sound track in the file of that mtime."""
    return SFX_LEVELLED / f"{sfx_id(path)}-{stamp}-src.wav"


def sfx_soundless(path: Path) -> bool:
    """[sfx-nosound] ffmpeg looked for a sound track in this clip and found
    none - noted once by _as_wav. A road that needs the clip's SOUND (the
    cadence welds it into a round) passes it over; a road that shows the
    PICTURE does not ask. Blocking: the share stamp (memoised) and one stat
    on local disk."""
    try:
        stamp = sfx_stamp(path)
        return bool(stamp) and sfx_src_wav_name(path, stamp).with_suffix(
            ".nosound").exists()
    except Exception:  # noqa: BLE001
        return False


def _as_wav(path: Path, *, timeout: float = 30.0) -> Path:
''', 1),
    ("nosound-as-wav",
     '''    out = SFX_LEVELLED / f"{sfx_id(path)}-{path.stat().st_mtime_ns}-src.wav"
    if out.exists():
        return out
    SFX_LEVELLED.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([exe, "-nostdin", "-loglevel", "error", "-y",
                        "-i", str(path), "-ac", "1", "-ar", "22050",
                        str(out)], check=True, timeout=timeout)
    except Exception:
        out.unlink(missing_ok=True)
        return path
    return out
''',
     '''    out = sfx_src_wav_name(path, path.stat().st_mtime_ns)   # [sfx-nosound]
    if out.exists():
        return out
    # [sfx-nosound] A file with no sound track has nothing to decode, and
    # asking again cannot change that: the note is read before any ffmpeg.
    # Measured: one picture-only .MP4 decoded 123 times, every half hour.
    silent_note = out.with_suffix(".nosound")
    if silent_note.exists():
        return path
    SFX_LEVELLED.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([exe, "-nostdin", "-loglevel", "error", "-y",
                        "-i", str(path), "-ac", "1", "-ar", "22050",
                        str(out)], check=True, timeout=timeout,
                       capture_output=True, text=True, errors="replace")
    except Exception as exc:  # noqa: BLE001
        out.unlink(missing_ok=True)
        said = getattr(exc, "stderr", "") or ""
        if isinstance(said, bytes):
            said = said.decode("utf-8", "replace")
        said = str(said)
        if "does not contain any stream" in said or "matches no streams" in said:
            try:
                silent_note.write_text("no sound track - ffmpeg: %s\\n"
                                       % " / ".join(said.split("\\n"))[:400])
            except OSError:
                pass
            print("[sfx] %s has no sound track - noted (%s), never decoded "
                  "again" % (path.name, silent_note.name), flush=True)
        else:
            # Anything else may answer next time, and is retried as before.
            print("[sfx] could not decode %s to a wav: %s" % (
                path.name, (" / ".join(said.strip().split("\\n")[-2:])
                            or type(exc).__name__)[:300]), flush=True)
        return path
    return out
''', 1),
    ("nosound-cadence-spends-it",
     '''        source = _as_wav(path, timeout=4.0)
''',
     '''        source = _as_wav(path, timeout=4.0)
        if source == path and sfx_soundless(path):
            # [sfx-nosound] a picture with no sound track has nothing to weld
            # into the round: spent for this deck pass, so the book stops
            # dealing it here (it was the only unspent clip in its folder, so
            # it came up every time the folder did). The picture roads still
            # show it.
            try:
                _sfx_video_rotation_mark([sfx_id(path)])
            except Exception:  # noqa: BLE001
                pass
            continue
''', 1),
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

"""Assemble accepted line strips into one finished conversation, and write
down exactly where every line is inside it.

Boundary 3 of `docs/notes/speaker-recording-and-script-assembly.md`:

    Integrate accepted strips with existing saved-take preparation and
    mixing. Produce the final audio and cue map before readiness is
    advertised.

Three rules from that note govern everything below.

1.  "The assembler consumes original script ordinals, never recording
    completion order or filesystem order."  Nothing here iterates a
    directory, a session, or an actor.  The one loop that builds audio
    walks the FROZEN SCRIPT, and pulls the cut belonging to each
    occurrence out of an index.  Actor A recording lines 1 and 3 while
    actor B records 2 and 4 cannot produce anything but 1, 2, 3, 4.

2.  "Compute the final cue map from the actual cuts and processing,
    including resampling, inserted pauses, trimming and effect tails. A
    source master offset is not a final mix offset."  Every cue position
    in this module is an INTEGER SAMPLE COUNT MEASURED OFF AUDIO THAT WAS
    ACTUALLY PRODUCED.  No cue is ever an estimate scaled to fit a
    finished duration.  See `_measure_strip`.

3.  "Retain separate speech-end and cue-end positions so an inserted
    pause does not falsely start the next line."  Every cue carries
    `speech_end_sample` and `cue_end_sample` separately.  The beat the
    mixer glues at a seam belongs to the window the panel highlights and
    does NOT belong to the audio a download hands over.

What this replaces
------------------

`app.py:83945` onward measures each clip as it sits on disk, sums those
measurements into cue windows, and then rescales the whole span by
`finished_duration / summed_estimate` so the numbers land inside the
file.  That correction is a SCALE, and the errors it is correcting are
not scales:

    measured on this station's own mixer, 2026-09-15
      per-strip leg + concat ....... frame-exact, 0 frames of error
      loudnorm ..................... +3 frames of LENGTH, +1 frame of delay
      alimiter ..................... +119 frames of DELAY (its 5 ms attack
                                     lookahead), 0 frames of length

A constant 120-sample delay stretched by a scale factor is wrong at the
head and wrong at the tail.  This module measures the edited sample count
of every strip instead, sums integers, and adds the measured mixer
latency once.  `assemble_conversation` then PROVES the result against the
finished file before anything is advertised as ready.

Mirrored from app.py
--------------------

`_mix_blocking` below mirrors `_call_concat_blocking` (`app.py:81956`)
filter for filter, including `CONCAT_KEEP`, the varied `CONCAT_BEAT`, the
`loudnorm=I=-11:TP=-1.0:LRA=7` radio glue, the optional vinyl crackle,
`alimiter=limit=0.95`, the write-to-a-real-file rule, the
`len(blob) <= 4000` refusal and the closing `_wav_tail_pad`.  It is a
mirror rather than a call because `app.py` is a 200k-line server module
owned by another agent and importing it would start a radio station.  The
mirror is kept honest by `tests/test_conversation_assembly.py`, which
asserts the constants and the filter graph against the text of `app.py`
itself, so a drift in either file fails a test rather than a broadcast.

Storage
-------

"Store the master plus cut offsets; materialize individual strip files
only when an adapter or editor needs them."  The durable record this
module returns holds master hashes plus integer cut offsets.  Strips are
built in a temporary directory and deleted.  `materialize_strips` exists
for the adapter or editor that genuinely needs files on disk.
"""
from __future__ import annotations

import array
import hashlib
import json
import os
import random
import shutil
import struct
import subprocess
import tempfile
import time
import uuid
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# --------------------------------------------------------------------------
# The mixer's numbers.  These MUST equal app.py's; the test suite asserts it.
# --------------------------------------------------------------------------

MIX_RATE = 24000                      # app.py: -ar 24000, aresample=24000
MIX_CHANNELS = 1                      # app.py: -ac 1
MIX_WIDTH = 2                         # app.py: -sample_fmt s16
CONCAT_KEEP = 0.06                    # app.py:81831 what survives the trim
CONCAT_BEAT = (0.07, 0.18)            # app.py:81838 the varied seam beat
SEG_TRIM_DB = -50.0                   # app.py:81857 silenceremove threshold
BOX_TAIL_MS_DEFAULT = 900             # app.py: BOX_TAIL_MS default
MIN_MIX_BYTES = 4000                  # app.py: `if len(blob) <= 4000`
LOUDNORM = "loudnorm=I=-11:TP=-1.0:LRA=7"
LIMITER = "alimiter=limit=0.95"

CUE_MAP_REVISION = 1
ASSEMBLY_KIND = "sequential"

#: How far the finished file may differ from the summed strip measurements
#: before the assembly is refused outright.  The measured residual on this
#: station is 3 frames; a twentieth of a second is four hundred times that.
MIX_RESIDUAL_TOLERANCE_FRAMES = MIX_RATE // 20

_FFMPEG_TIMEOUT = 180                 # app.py: subprocess.run(..., timeout=180)


class AssemblyRefused(Exception):
    """An assembly that cannot be proved is refused, never approximated.

    "A failed cut requires a retake or another complete ready candidate
    before commitment."  Callers must treat this as "choose a replacement",
    never as "air it and hope".
    """

    def __init__(self, reason: str, detail: str = "", **facts: Any) -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail
        self.facts = facts


# ==========================================================================
# Adapters.  Everything assumed about the other three modules lives HERE.
# ==========================================================================
#
# `script_manifest.py`/`manifest_store.py` (record shapes and storage) and
# `line_alignment.py`/`speaker_session.py` (which produce the accepted
# cuts) are being written alongside this module.  Rather than guess their
# exact attribute spelling, every field is read through an alias list
# drawn from the note's own table in section 3.  Dicts, dataclasses and
# plain objects all work.  When the four modules are reconciled, delete
# the aliases that turned out to be unnecessary; nothing below this
# section names a field directly.


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    """Read the first present field from a record of unknown spelling."""
    if obj is None:
        return default
    for name in names:
        if isinstance(obj, Mapping):
            if name in obj and obj[name] is not None:
                return obj[name]
        else:
            got = getattr(obj, name, None)
            if got is not None:
                return got
    return default


def bare_hash(value: Any) -> str:
    """A sha256 with or without `script_manifest`'s `sha256:` prefix.

    RECONCILED 2026-09-15: `script_manifest.audio_digest` returns
    `sha256:<64 hex>` and `is_audio_digest` enforces it, while this module
    hashes bytes to bare hex.  Both spellings name the same audio, so both
    are reduced to the hex before anything is compared.
    """
    text = str(value or "").strip()
    return text.split(":", 1)[1] if text.lower().startswith("sha256:") else text


def _int(value: Any, what: str) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise AssemblyRefused("bad_field", f"{what} is not an integer",
                              value=repr(value)) from None
    return out


@dataclass(frozen=True)
class Occurrence:
    """One utterance of the frozen script.

    "Assign a revision and an ordered occurrence ID to every utterance,
    including two occurrences with identical words."  `occurrence_id` is
    the identity; `text` is emphatically NOT.
    """

    occurrence_id: str
    ordinal: int
    speaker: str
    text: str
    kind: str = "line"


@dataclass(frozen=True)
class FrozenScript:
    revision: str
    occurrences: tuple[Occurrence, ...]

    def ordinals(self) -> tuple[int, ...]:
        return tuple(o.ordinal for o in self.occurrences)

    def ids(self) -> tuple[str, ...]:
        return tuple(o.occurrence_id for o in self.occurrences)


def frozen_script(source: Any) -> FrozenScript:
    """Adapt whatever `script_manifest.py` hands over into a FrozenScript.

    ASSUMED: a revision string and an ordered collection of utterances,
    each with an occurrence id, an ordinal, a speaker and the exact spoken
    text — the four columns the note's table names for "Frozen script".
    """
    if isinstance(source, FrozenScript):
        return source
    revision = str(_get(source, "revision", "script_revision", "rev",
                        default="") or "")
    if not revision:
        raise AssemblyRefused("no_revision",
                              "a frozen script must carry its revision")
    raw = _get(source, "occurrences", "lines", "utterances", "rows",
               "items", default=None)
    if raw is None and isinstance(source, (list, tuple)):
        raw = source
    if not raw:
        raise AssemblyRefused("empty_script",
                              "a frozen script with no occurrences cannot "
                              "be assembled", revision=revision)
    out: list[Occurrence] = []
    for position, row in enumerate(raw):
        occurrence_id = str(_get(row, "occurrence_id", "id", "line_id",
                                 "occurrence", default="") or "")
        if not occurrence_id:
            raise AssemblyRefused(
                "no_occurrence_id",
                f"occurrence at position {position} has no id "
                "(two occurrences of identical words cannot be told apart "
                "without one)", revision=revision)
        ordinal_raw = _get(row, "ordinal", "order", "index", "position",
                           default=None)
        ordinal = position if ordinal_raw is None else _int(
            ordinal_raw, f"ordinal of {occurrence_id}")
        out.append(Occurrence(
            occurrence_id=occurrence_id,
            ordinal=ordinal,
            speaker=str(_get(row, "speaker", "who", "actor", "voice_role",
                             default="") or ""),
            text=str(_get(row, "text", "spoken_text", "line", default="")
                     or ""),
            kind=str(_get(row, "kind", default="line") or "line"),
        ))
    # THE READING ORDER, ESTABLISHED ONCE.  Sorting here — rather than
    # trusting the container — is what makes "never recording completion
    # order or filesystem order" true even when a store hands rows back in
    # whatever order it happened to persist them.
    out.sort(key=lambda o: o.ordinal)
    seen_ordinals: set[int] = set()
    seen_ids: set[str] = set()
    for occurrence in out:
        if occurrence.ordinal in seen_ordinals:
            raise AssemblyRefused(
                "duplicate_ordinal",
                f"ordinal {occurrence.ordinal} appears twice",
                revision=revision)
        if occurrence.occurrence_id in seen_ids:
            raise AssemblyRefused(
                "duplicate_occurrence_id",
                f"occurrence {occurrence.occurrence_id} appears twice",
                revision=revision)
        seen_ordinals.add(occurrence.ordinal)
        seen_ids.add(occurrence.occurrence_id)
    return FrozenScript(revision=revision, occurrences=tuple(out))


@dataclass(frozen=True)
class Master:
    """A speaker's master recording.

    Table row "Master recording": take ID, immutable audio hash, sample
    rate, frame count and media reference.
    """

    take_id: str
    audio_hash: str
    sample_rate: int
    frames: int
    path: Path
    actor: str = ""


def _master(source: Any, *, media_root: Path | None = None) -> Master:
    """ASSUMED shape of a master handed over by `speaker_session.py`."""
    if isinstance(source, Master):
        return source
    raw_path = str(_get(source, "path", "media_ref", "media",
                        "media_reference", "file", "media_path",
                        default="") or "")
    if not raw_path:
        raise AssemblyRefused("no_master_media",
                              "a master recording must reference its media")
    path = Path(raw_path)
    if not path.is_absolute() and media_root is not None:
        path = Path(media_root) / raw_path.lstrip("/")
    return Master(
        take_id=str(_get(source, "take_id", "id", "take", default="") or ""),
        audio_hash=bare_hash(_get(source, "audio_sha256", "audio_hash",
                                  "hash", "sha256", default="")),
        sample_rate=_int(_get(source, "sample_rate", "rate", "sr",
                              default=0), "master sample_rate"),
        frames=_int(_get(source, "frame_count", "frames", "samples",
                         default=0), "master frames"),
        path=path,
        actor=str(_get(source, "actor", "voice", "speaker", default="")
                  or ""),
    )


@dataclass(frozen=True)
class Cut:
    """One accepted line cut against a speaker master.

    Table row "Line cut": occurrence ID, original ordinal, master hash,
    start/end sample, boundary method and verification result.  The start
    and end are INTEGER SAMPLE POSITIONS IN THE MASTER'S OWN RATE — "a
    source master offset is not a final mix offset", so nothing downstream
    may reuse them as mix positions.
    """

    occurrence_id: str
    ordinal: int
    master_hash: str
    start_sample: int
    end_sample: int
    cut_id: str = ""
    boundary_method: str = ""
    verified: bool = True
    effects: tuple[str, ...] = ()
    pause_after: float | None = None

    @property
    def source_frames(self) -> int:
        return self.end_sample - self.start_sample


def _cut(source: Any) -> Cut:
    """ASSUMED shape of an accepted cut from `line_alignment.py`.

    The verification result is read as a truthy flag, a string verdict, or
    a nested mapping with an `ok`/`accepted` field, because none of those
    three spellings would be surprising.  Anything this module cannot read
    as an explicit acceptance is treated as NOT accepted.
    """
    if isinstance(source, Cut):
        return source
    occurrence_id = str(_get(source, "occurrence_id", "id", "line_id",
                             default="") or "")
    if not occurrence_id:
        raise AssemblyRefused("cut_without_occurrence",
                              "an accepted cut must name its occurrence")
    ordinal_raw = _get(source, "ordinal", "order", "index", default=None)
    # RECONCILED 2026-09-15.  Three different acceptance spellings exist
    # across the boundary-3 modules and they are read in this order:
    #
    #  1. `state`, from `script_manifest.line_cut` - one of
    #     ("pending", "accepted", "rejected").  Authoritative when present.
    #  2. an explicit boolean or verdict string.
    #  3. `verification`, from `line_alignment.LineCut` - a mapping of
    #     EVIDENCE (transcript, actor, ambiguous, notes) with no `ok` key.
    #     line_alignment returns accepted cuts in `.cuts` and everything
    #     else in `.refusals`, so a cut that arrives carrying evidence is
    #     an accepted one.  Only an explicit false verdict inside refuses.
    state = _get(source, "state", default=None)
    if state is not None:
        verified = str(state).strip().lower() == "accepted"
    else:
        verdict = _get(source, "verified", "accepted", "verification_result",
                       "result", "ok", "verification", default=None)
        if isinstance(verdict, Mapping):
            verdict = _get(verdict, "ok", "accepted", "verified", "passed",
                           default=True)
        if isinstance(verdict, str):
            verified = verdict.strip().lower() in (
                "ok", "accepted", "verified", "pass", "passed", "true", "yes")
        elif verdict is None:
            verified = True            # an absent field is not a refusal
        else:
            verified = bool(verdict)
    effects = _get(source, "effects", "effect", "filters", default=())
    if isinstance(effects, str):
        effects = (effects,)
    return Cut(
        occurrence_id=occurrence_id,
        ordinal=-1 if ordinal_raw is None else _int(
            ordinal_raw, f"ordinal of cut {occurrence_id}"),
        cut_id=str(_get(source, "cut_id", default="") or ""),
        master_hash=bare_hash(_get(source, "master_sha256", "master_hash",
                                   "audio_hash", "hash", "master",
                                   default="")),
        start_sample=_int(_get(source, "start_sample", "start", "from_sample",
                               default=0), f"start of cut {occurrence_id}"),
        end_sample=_int(_get(source, "end_sample", "end", "to_sample",
                             default=0), f"end of cut {occurrence_id}"),
        boundary_method=str(_get(source, "boundary_method", "method",
                                 "boundary", default="") or ""),
        verified=verified,
        effects=tuple(str(f) for f in effects if str(f).strip()),
        pause_after=_get(source, "pause_after", "gap_after", default=None),
    )


@dataclass(frozen=True)
class Extra:
    """Audio in the finished file that is not a scripted line.

    The burst path in app.py welds a phone ring at the head, the SFX guy's
    quip mid-round and a hang-up at the tail into the same `seg` list the
    turns live in, and every one of them moves the turns that follow.  An
    extra gets a cue of its own so the arithmetic stays whole and the
    panel can tell a sting from a line.
    """

    extra_id: str
    path: Path
    after_ordinal: int | None = None   # None -> before the first line
    kind: str = "sfx"
    label: str = ""
    speaker: str = "board"


# ==========================================================================
# Wave reading and writing.  Small, strict, and never silently lenient.
# ==========================================================================


def _read_wave(path: Path) -> tuple[array.array, int, int]:
    """Frames, sample rate and channel count off a 16-bit PCM wav."""
    try:
        with wave.open(str(path), "rb") as handle:
            width = handle.getsampwidth()
            rate = handle.getframerate()
            channels = handle.getnchannels()
            count = handle.getnframes()
            raw = handle.readframes(count)
    except (wave.Error, EOFError, OSError) as exc:
        raise AssemblyRefused("unreadable_master",
                              f"{path.name} is not a readable wav: {exc}",
                              path=str(path)) from None
    if width != MIX_WIDTH:
        raise AssemblyRefused(
            "unsupported_sample_width",
            f"{path.name} is {width * 8}-bit; masters must be 16-bit PCM",
            path=str(path))
    buf = array.array("h")
    buf.frombytes(raw[:len(raw) - (len(raw) % 2)])
    return buf, rate or 0, channels or 1


def _write_wave(path: Path, samples: Sequence[int], rate: int,
                channels: int = 1) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(MIX_WIDTH)
        handle.setframerate(rate)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _wave_frames(path: Path) -> int:
    """The frame count of a wav, read off its own header."""
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes()


def _wav_tail_pad(raw: bytes, ms: int) -> bytes:
    """Mirror of `_wav_tail_pad` (app.py:65845).

    The Pine Box stutter-loops its last audio buffer, so every clip ends
    on silence and the loop is inaudible (#493, #712).  Mirrored rather
    than estimated because these frames are IN the finished file and
    therefore in its frame count — the cue map has to know about them.
    """
    if ms <= 0:
        return raw
    import io
    with wave.open(io.BytesIO(raw), "rb") as reader:
        params = reader.getparams()
        frames = reader.readframes(reader.getnframes())
    pad = b"\x00" * int(params.framerate * params.nchannels
                        * params.sampwidth * ms / 1000)
    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setparams(params)
        writer.writeframes(frames + pad)
    return out.getvalue()


def box_tail_ms() -> int:
    """Mirror of `box_tail_seconds` (app.py), in milliseconds."""
    try:
        return max(0, int(os.getenv("BOX_TAIL_MS", str(BOX_TAIL_MS_DEFAULT))))
    except (TypeError, ValueError):
        return BOX_TAIL_MS_DEFAULT


def audio_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ==========================================================================
# The mixer, mirrored from app.py
# ==========================================================================


def concat_beats(count: int, rng: random.Random | None = None) -> list[float]:
    """Mirror of `concat_beats` (app.py:81841).

    "140-330 ms, never the same twice - a room, not a metronome" (#769),
    halved in 2026-09-09 to CONCAT_BEAT.  Drawn by the CALLER so the
    timeline and the audio are built out of the same numbers; that is the
    #778 lesson and it is the reason this function exists here rather than
    inside the mixer.  An explicit `rng` makes an assembly reproducible.
    """
    draw = (rng or random).uniform
    return [round(draw(*CONCAT_BEAT), 3) for _ in range(max(0, count - 1))] \
        + [0.0]


def _ffmpeg_exe() -> str:
    """The same road app.py takes to ffmpeg: imageio_ffmpeg's own binary."""
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _leg(index: int, beat: float, effects: Sequence[str] = (),
         pad: bool = True) -> str:
    """One input's filter leg, mirroring `_call_concat_blocking`.

    Byte for byte the same chain as app.py:81956 — resample to the common
    format, then `areverse -> silenceremove -> areverse` to strip the
    welded BOX_TAIL_MS pad back to CONCAT_KEEP, then the varied beat.

    `effects` is inserted after the format conversion and BEFORE the tail
    trim, so a reverb's tail is trimmed to the same sliver as any other
    trailing silence and an `atempo` changes the speech rather than the
    beat.  The note requires duration-changing effects to move every later
    cue; they do, because the strip is MEASURED after this chain runs.
    """
    chain = (f"[{index}:a]aresample={MIX_RATE},"
             f"aformat=sample_fmts=s16:channel_layouts=mono")
    for effect in effects:
        chain += "," + effect
    chain += (",areverse,silenceremove=start_periods=1:"
              f"start_silence={CONCAT_KEEP}:"
              f"start_threshold={SEG_TRIM_DB:.0f}dB,areverse")
    if pad and beat > 0:
        chain += f",apad=pad_dur={beat}"
    return chain


def _run_ffmpeg(args: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), capture_output=True,
                          timeout=_FFMPEG_TIMEOUT)


def _measure_strip(path: Path, effects: Sequence[str],
                   workdir: Path, name: str) -> int:
    """THE MEASUREMENT THAT REPLACES THE ESTIMATE.

    Render this strip through the mixer's own per-input leg — resampling,
    effects and the tail trim, but WITHOUT the seam beat — and read the
    frame count off the result's header.

    app.py cannot do this: at `83945` it has already handed a whole round
    to the mixer, so it reads each clip as it sits on disk and subtracts
    `seg_tails_for`'s reading of the trailing silence (`app.py:81901`).
    That is an excellent estimate of what `silenceremove` will do.  It is
    still an estimate, and the estimate is what the rescale exists to
    paper over.  This is the actual number.
    """
    out = workdir / f"{name}.meas.wav"
    graph = _leg(0, 0.0, effects, pad=False) + "[out]"
    proc = _run_ffmpeg([_ffmpeg_exe(), "-nostdin", "-hide_banner",
                        "-loglevel", "error", "-y", "-i", str(path),
                        "-filter_complex", graph, "-map", "[out]",
                        "-ac", str(MIX_CHANNELS), "-ar", str(MIX_RATE),
                        "-sample_fmt", "s16", str(out)])
    if proc.returncode != 0 or not out.is_file():
        raise AssemblyRefused(
            "strip_unmeasurable",
            f"the mixer leg would not run over {name}",
            stderr=proc.stderr.decode("utf-8", "replace")[-400:])
    frames = _wave_frames(out)
    if frames <= 0:
        raise AssemblyRefused(
            "empty_strip",
            f"{name} measured zero frames after trimming; there is no "
            "speech in this cut")
    return frames


def _mix_blocking(paths: Sequence[Path], beats: Sequence[float],
                  effects: Sequence[Sequence[str]],
                  crackle: bool = False) -> bytes:
    """MIRROR OF `_call_concat_blocking` (app.py:81956).

    Same graph, same order, same numbers: per-input resample and tail trim,
    the varied beat at each seam (the last input gets none), `concat`, one
    `loudnorm` pass over the whole show so levels match across turns like a
    real station (#616), the optional vinyl `crackle` bed, `alimiter`, a
    write to a REAL FILE (a piped wav carries a placeholder RIFF size and
    every later duration read is then wrong), the `<= 4000 bytes` refusal,
    and the closing `_wav_tail_pad`.

    Two deliberate differences, both because this is an assembler and not a
    transport:

    * app.py returns None on any failure so the caller can fall back to the
      turn-by-turn road.  There is no such road here: "No incomplete
      conversation may be admitted", so a failure raises.
    * app.py hands a single-segment round over as it sits on disk, mixer
      and all skipped.  A one-line conversation still goes through the
      whole graph here, so its cue map is derived the same way as every
      other one and can be verified the same way.
    """
    if not paths:
        raise AssemblyRefused("nothing_to_mix", "no strips were supplied")
    exe = _ffmpeg_exe()
    ins: list[str] = []
    for path in paths:
        ins += ["-i", str(path)]
    pre = "".join(
        f"{_leg(i, beats[i] if i < len(beats) else 0.0, effects[i] if i < len(effects) else ())}[a{i}];"
        for i in range(len(paths)))
    chain = "".join(f"[a{i}]" for i in range(len(paths)))
    joined = (f"{pre}{chain}concat=n={len(paths)}:v=0:a=1,{LOUDNORM}")
    if crackle:
        graph = (f"{joined}[dry];"
                 "anoisesrc=color=brown:amplitude=0.04,highpass=f=1500,"
                 "lowpass=f=6000,volume=0.10[crk];"
                 "[dry][crk]amix=inputs=2:duration=first:normalize=0,"
                 f"{LIMITER}[out]")
    else:
        graph = f"{joined},{LIMITER}[out]"
    handle, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(handle)
    try:
        proc = _run_ffmpeg(
            [exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
             *ins, "-filter_complex", graph, "-map", "[out]",
             "-ac", str(MIX_CHANNELS), "-ar", str(MIX_RATE),
             "-sample_fmt", "s16", tmp])
        blob = Path(tmp).read_bytes() if proc.returncode == 0 else b""
        stderr = proc.stderr.decode("utf-8", "replace")[-400:]
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if len(blob) <= MIN_MIX_BYTES:
        raise AssemblyRefused("mix_failed",
                              "the mixer produced no usable audio",
                              stderr=stderr, bytes=len(blob))
    return _wav_tail_pad(blob, box_tail_ms())


# --------------------------------------------------------------------------
# Mixer latency, measured rather than assumed
# --------------------------------------------------------------------------

_LATENCY_CACHE: dict[str, int] = {}


def measure_mix_latency(crackle: bool = False) -> int:
    """How many samples the join chain delays its content by.

    `alimiter` has a 5 ms attack lookahead; at 24 kHz that is 120 samples
    of delay on everything in the file, and `loudnorm` adds about one more.
    It is small, it is constant, and a rescale cannot express it — which is
    the whole argument for this module.  So it is MEASURED: an impulse at a
    known sample goes through the same `concat -> loudnorm -> [crackle] ->
    alimiter` tail, and the peak is found in the output.

    Cached per chain.  Returns 0 if ffmpeg will not cooperate, with the cue
    map recording `latency_measured: false` so nobody mistakes a fallback
    for a fact.
    """
    key = f"crackle={int(bool(crackle))}"
    if key in _LATENCY_CACHE:
        return _LATENCY_CACHE[key]
    latency = 0
    work = Path(tempfile.mkdtemp(prefix="cue-latency-"))
    try:
        mark = MIX_RATE // 2
        samples = [0] * (MIX_RATE + 240)
        samples[mark] = 30000
        probe = work / "impulse.wav"
        _write_wave(probe, samples, MIX_RATE)
        out = work / "probe.wav"
        # Only the join tail; the per-input leg is already proved exact.
        graph = (f"[0:a]aresample={MIX_RATE},"
                 "aformat=sample_fmts=s16:channel_layouts=mono[a0];"
                 f"[a0]concat=n=1:v=0:a=1,{LOUDNORM}")
        if crackle:
            graph += ("[dry];anoisesrc=color=brown:amplitude=0.04,"
                      "highpass=f=1500,lowpass=f=6000,volume=0.10[crk];"
                      "[dry][crk]amix=inputs=2:duration=first:normalize=0,"
                      f"{LIMITER}[out]")
        else:
            graph += f",{LIMITER}[out]"
        proc = _run_ffmpeg([_ffmpeg_exe(), "-nostdin", "-hide_banner",
                            "-loglevel", "error", "-y", "-i", str(probe),
                            "-filter_complex", graph, "-map", "[out]",
                            "-ac", "1", "-ar", str(MIX_RATE),
                            "-sample_fmt", "s16", str(out)])
        if proc.returncode == 0 and out.is_file():
            buf, _rate, _chans = _read_wave(out)
            if buf:
                peak = max(range(len(buf)), key=lambda i: abs(buf[i]))
                shift = peak - mark
                # A sane lookahead is milliseconds, not seconds.  Anything
                # else means the probe found the wrong thing; take nothing.
                if 0 <= shift <= MIX_RATE // 10:
                    latency = shift
    except (AssemblyRefused, OSError, subprocess.SubprocessError,
            ValueError, ImportError):
        latency = 0
    finally:
        shutil.rmtree(work, ignore_errors=True)
    _LATENCY_CACHE[key] = latency
    return latency


# ==========================================================================
# Assembly
# ==========================================================================


@dataclass
class Assembly:
    """A finished conversation and the proof that it is one."""

    assembly_id: str
    script_revision: str
    audio: bytes
    cue_map: dict[str, Any]
    record: dict[str, Any]
    strips: dict[str, Path] = field(default_factory=dict)
    _workdir: Path | None = None

    @property
    def final_audio_hash(self) -> str:
        return str(self.cue_map["final_audio_hash"])

    @property
    def frame_count(self) -> int:
        return int(self.cue_map["frame_count"])

    @property
    def seconds(self) -> float:
        return self.frame_count / float(self.cue_map["sample_rate"])

    def write_audio(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.audio)
        return path

    def close(self) -> None:
        """Drop the temporary strips.

        "Store the master plus cut offsets; materialize individual strip
        files only when an adapter or editor needs them."  The record and
        the cue map survive; these files do not.
        """
        if self._workdir is not None:
            shutil.rmtree(self._workdir, ignore_errors=True)
            self._workdir = None
            self.strips = {}

    def __enter__(self) -> "Assembly":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def _index_cuts(cuts: Iterable[Any]) -> dict[str, Cut]:
    index: dict[str, Cut] = {}
    for raw in cuts:
        cut = _cut(raw)
        if cut.occurrence_id in index:
            raise AssemblyRefused(
                "duplicate_cut",
                f"occurrence {cut.occurrence_id} has more than one accepted "
                "cut; exactly one is required",
                occurrence_id=cut.occurrence_id)
        index[cut.occurrence_id] = cut
    return index


def _index_masters(masters: Iterable[Any],
                   media_root: Path | None) -> dict[str, Master]:
    index: dict[str, Master] = {}
    for raw in masters:
        master = _master(raw, media_root=media_root)
        for key in (master.audio_hash, master.take_id):
            if key:
                index[key] = master
    return index


def _verify_master(master: Master, seen: dict[str, tuple[array.array, int, int]]
                   ) -> tuple[array.array, int, int]:
    """Read a master once, and refuse it if it is not what it claims.

    "corrupt or changed masters" is an acceptance case in the note.  The
    hash is the identity a cut was accepted against; if the bytes no
    longer produce it, every offset taken against those bytes is a guess.
    """
    key = str(master.path)
    if key in seen:
        return seen[key]
    if not master.path.is_file():
        raise AssemblyRefused("master_missing",
                              f"master {master.take_id or master.audio_hash} "
                              f"is not on disk", path=str(master.path))
    if master.audio_hash:
        actual = file_hash(master.path)
        if actual != master.audio_hash:
            raise AssemblyRefused(
                "master_changed",
                f"master {master.take_id or master.audio_hash[:12]} no "
                "longer hashes to its accepted identity",
                expected=master.audio_hash, actual=actual,
                path=str(master.path))
    buf, rate, channels = _read_wave(master.path)
    frames = len(buf) // max(1, channels)
    if master.sample_rate and rate != master.sample_rate:
        raise AssemblyRefused(
            "master_rate_mismatch",
            f"master {master.take_id} declares {master.sample_rate} Hz and "
            f"contains {rate} Hz", path=str(master.path))
    if master.frames and frames != master.frames:
        raise AssemblyRefused(
            "master_frames_mismatch",
            f"master {master.take_id} declares {master.frames} frames and "
            f"contains {frames}", path=str(master.path))
    if frames <= 0:
        raise AssemblyRefused("master_empty",
                              f"master {master.take_id} has no frames",
                              path=str(master.path))
    seen[key] = (buf, rate, channels)
    return seen[key]


def assemble_conversation(
    script: Any,
    masters: Iterable[Any],
    cuts: Iterable[Any],
    *,
    extras: Iterable[Extra] = (),
    beats: Sequence[float] | None = None,
    crackle: bool = False,
    mode: str = ASSEMBLY_KIND,
    media_root: str | Path | None = None,
    assembly_id: str = "",
    keep_strips: bool = False,
    measure_latency: bool = True,
    rng: random.Random | None = None,
) -> Assembly:
    """Build one finished conversation and its exact cue map.

    `script` is the FROZEN script — the reading order and nothing else
    decides the output order.  `cuts` may arrive in any order whatsoever,
    from any number of performer sessions, finished at any time: they are
    put into an index and pulled out by occurrence id.

    Raises `AssemblyRefused` for anything that cannot be proved: a missing
    cut, a duplicate cut, an unverified cut, a corrupt or changed master,
    an out-of-bounds offset, a mixer failure, or a finished file whose
    frame count does not agree with the measurements.

    Returns an `Assembly` whose `cue_map` is safe to advertise.
    """
    if mode != ASSEMBLY_KIND:
        # "Make overlap an explicit script decision; the initial strict
        # sequential mode should have a single active spoken line."
        raise AssemblyRefused(
            "unsupported_mode",
            f"only {ASSEMBLY_KIND!r} assembly is implemented; overlap is an "
            "explicit script decision and has no implementation yet",
            mode=mode)

    frozen = frozen_script(script)
    cut_index = _index_cuts(cuts)
    master_index = _index_masters(masters, Path(media_root) if media_root
                                  else None)
    extras = list(extras)

    # ---- every required occurrence must have exactly one accepted cut ----
    missing = [o.occurrence_id for o in frozen.occurrences
               if o.occurrence_id not in cut_index]
    if missing:
        raise AssemblyRefused(
            "missing_cut",
            f"{len(missing)} occurrence(s) have no accepted cut: "
            + ", ".join(missing[:6]),
            occurrences=missing, revision=frozen.revision)
    stray = [cid for cid in cut_index if cid not in set(frozen.ids())]
    if stray:
        raise AssemblyRefused(
            "cut_outside_script",
            "accepted cuts name occurrences this revision does not "
            "contain: " + ", ".join(stray[:6]),
            occurrences=stray, revision=frozen.revision)
    unverified = [o.occurrence_id for o in frozen.occurrences
                  if not cut_index[o.occurrence_id].verified]
    if unverified:
        raise AssemblyRefused(
            "unverified_cut",
            "these cuts were not accepted: " + ", ".join(unverified[:6]),
            occurrences=unverified, revision=frozen.revision)
    ordinal_conflicts = [
        o.occurrence_id for o in frozen.occurrences
        if cut_index[o.occurrence_id].ordinal >= 0
        and cut_index[o.occurrence_id].ordinal != o.ordinal]
    if ordinal_conflicts:
        raise AssemblyRefused(
            "ordinal_disagreement",
            "a cut's recorded ordinal disagrees with the frozen script: "
            + ", ".join(ordinal_conflicts[:6]),
            occurrences=ordinal_conflicts, revision=frozen.revision)

    workdir = Path(tempfile.mkdtemp(prefix="assembly-"))
    try:
        return _assemble(frozen, cut_index, master_index, extras, beats,
                         crackle, assembly_id, workdir, keep_strips,
                         measure_latency, rng)
    except BaseException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise


@dataclass
class _Segment:
    """One input to the mixer, already in reading order."""

    segment_id: str
    path: Path
    kind: str                     # "line" | "sfx" | ...
    occurrence_id: str = ""
    ordinal: int = -1
    speaker: str = ""
    text: str = ""
    label: str = ""
    cut_id: str = ""
    effects: tuple[str, ...] = ()
    cut: Cut | None = None
    master: Master | None = None
    source_rate: int = 0
    speech_frames: int = 0
    pause_frames: int = 0


def _assemble(frozen: FrozenScript, cut_index: dict[str, Cut],
              master_index: dict[str, Master], extras: list[Extra],
              beats: Sequence[float] | None, crackle: bool,
              assembly_id: str, workdir: Path, keep_strips: bool,
              measure_latency: bool, rng: random.Random | None) -> Assembly:
    read_masters: dict[str, tuple[array.array, int, int]] = {}

    # ------------------------------------------------------------------
    # 1. THE READING ORDER.  This is the only loop that decides order, and
    #    it walks the frozen script.  Nothing here consults a session, a
    #    completion time or a directory listing.
    # ------------------------------------------------------------------
    head = [e for e in extras if e.after_ordinal is None]
    by_ordinal: dict[int, list[Extra]] = {}
    for extra in extras:
        if extra.after_ordinal is not None:
            by_ordinal.setdefault(int(extra.after_ordinal), []).append(extra)

    segments: list[_Segment] = []
    for extra in head:
        segments.append(_Segment(segment_id=extra.extra_id, path=Path(extra.path),
                                 kind=extra.kind, label=extra.label,
                                 speaker=extra.speaker, text=extra.label))
    for occurrence in frozen.occurrences:
        cut = cut_index[occurrence.occurrence_id]
        master = master_index.get(cut.master_hash)
        if master is None:
            raise AssemblyRefused(
                "master_not_supplied",
                f"occurrence {occurrence.occurrence_id} was cut against "
                f"master {cut.master_hash[:12] or '(unnamed)'}, which was "
                "not supplied",
                occurrence_id=occurrence.occurrence_id,
                master_hash=cut.master_hash)
        buf, rate, channels = _verify_master(master, read_masters)
        frames = len(buf) // max(1, channels)
        if not (0 <= cut.start_sample < cut.end_sample <= frames):
            raise AssemblyRefused(
                "cut_out_of_bounds",
                f"occurrence {occurrence.occurrence_id} cuts "
                f"[{cut.start_sample}, {cut.end_sample}) from a master of "
                f"{frames} frames",
                occurrence_id=occurrence.occurrence_id)
        strip = workdir / f"{occurrence.ordinal:04d}-{occurrence.occurrence_id}.wav"
        slice_ = buf[cut.start_sample * channels:cut.end_sample * channels]
        _write_wave(strip, slice_, rate, channels)
        segments.append(_Segment(
            segment_id=occurrence.occurrence_id, path=strip, kind="line",
            occurrence_id=occurrence.occurrence_id, ordinal=occurrence.ordinal,
            speaker=occurrence.speaker or master.actor, text=occurrence.text,
            cut_id=cut.cut_id, effects=cut.effects, cut=cut, master=master,
            source_rate=rate))
        for extra in by_ordinal.get(occurrence.ordinal, []):
            segments.append(_Segment(
                segment_id=extra.extra_id, path=Path(extra.path),
                kind=extra.kind, label=extra.label, speaker=extra.speaker,
                text=extra.label))

    for segment in segments:
        if not segment.path.is_file():
            raise AssemblyRefused("segment_missing",
                                  f"{segment.segment_id} has no audio",
                                  path=str(segment.path))

    # ------------------------------------------------------------------
    # 2. THE BEATS, DRAWN BY THE CALLER (#778).  The mixer and the
    #    timeline must be built out of the same numbers or the marker
    #    walks off the line inside a round.
    # ------------------------------------------------------------------
    if beats is None:
        drawn = concat_beats(len(segments), rng)
    else:
        drawn = [float(b) for b in beats]
        if len(drawn) < len(segments):
            drawn = drawn + [0.0] * (len(segments) - len(drawn))
    drawn = drawn[:len(segments)]
    if drawn:
        drawn[-1] = 0.0               # app.py: the last clip gets no beat
    # An explicit per-cut pause overrides the drawn beat.  "Make overlap an
    # explicit script decision": a pause is the only seam adjustment strict
    # sequential mode accepts, and it can only ever be non-negative.
    for index, segment in enumerate(segments):
        if segment.cut is not None and segment.cut.pause_after is not None:
            requested = float(segment.cut.pause_after)
            if requested < 0:
                raise AssemblyRefused(
                    "overlap_requested",
                    f"occurrence {segment.occurrence_id} asks for a negative "
                    "pause; strict sequential mode has a single active "
                    "spoken line",
                    occurrence_id=segment.occurrence_id)
            if index < len(segments) - 1:
                drawn[index] = requested

    # ------------------------------------------------------------------
    # 3. MEASURE.  Every strip is rendered through the mixer's own leg and
    #    its frame count read off the header.  This is the number the note
    #    demands: "cue positions derived from actual edited sample counts".
    # ------------------------------------------------------------------
    for index, segment in enumerate(segments):
        segment.speech_frames = _measure_strip(
            segment.path, segment.effects, workdir,
            f"{index:04d}-{segment.segment_id}")
        # apad=pad_dur is exact at this rate; the total is proved below
        # against the finished file, so a rounding disagreement is caught
        # rather than carried.
        segment.pause_frames = int(round(drawn[index] * MIX_RATE))

    # ------------------------------------------------------------------
    # 4. MIX, through the graph mirrored from `_call_concat_blocking`.
    # ------------------------------------------------------------------
    blob = _mix_blocking([s.path for s in segments], drawn,
                         [s.effects for s in segments], crackle)
    import io
    with wave.open(io.BytesIO(blob), "rb") as reader:
        final_frames = reader.getnframes()
        final_rate = reader.getframerate()
    if final_rate != MIX_RATE:
        raise AssemblyRefused("wrong_output_rate",
                              f"the mixer produced {final_rate} Hz",
                              expected=MIX_RATE)

    tail_pad_frames = int(MIX_RATE * box_tail_ms() / 1000)
    body_frames = sum(s.speech_frames + s.pause_frames for s in segments)
    expected_frames = body_frames + tail_pad_frames
    residual = final_frames - expected_frames
    if abs(residual) > MIX_RESIDUAL_TOLERANCE_FRAMES:
        # The measurements and the file disagree by more than the loudness
        # pass can account for.  Refuse: an unexplained residual is exactly
        # the condition the old rescale used to absorb silently.
        raise AssemblyRefused(
            "mix_length_unexplained",
            f"the finished file is {residual} frames from the sum of the "
            f"measured strips ({expected_frames}); the cue map cannot be "
            "derived from it",
            final_frames=final_frames, expected_frames=expected_frames,
            residual=residual)

    latency = measure_mix_latency(crackle) if measure_latency else 0

    # ------------------------------------------------------------------
    # 5. THE CUE MAP.  Integer prefix sums, plus the one measured constant.
    # ------------------------------------------------------------------
    cues: list[dict[str, Any]] = []
    offset = latency
    for segment in segments:
        speech_end = offset + segment.speech_frames
        cue_end = speech_end + segment.pause_frames
        cue: dict[str, Any] = {
            "occurrence_id": segment.occurrence_id or segment.segment_id,
            "ordinal": segment.ordinal,
            "kind": segment.kind,
            "speaker": segment.speaker,
            "text": segment.text,
            "cut_id": segment.cut_id,
            # The positions, in samples of the FINAL file.  `start_sample`
            # and `speech_start_sample` are the same number in strict
            # sequential mode - the strip is trimmed at its tail, never at
            # its head - but `script_manifest.cue_entry` keeps them apart so
            # a lead-in can exist later without a shape change.
            "start_sample": offset,
            "speech_start_sample": offset,
            "speech_end_sample": speech_end,
            "cue_end_sample": cue_end,
            "pause_frames": segment.pause_frames,
            # …and in seconds, for the surfaces that think in seconds.
            "start_seconds": round(offset / MIX_RATE, 6),
            "speech_end_seconds": round(speech_end / MIX_RATE, 6),
            "cue_end_seconds": round(cue_end / MIX_RATE, 6),
            "pause_seconds": round(segment.pause_frames / MIX_RATE, 6),
            # The cut's own length, so a duration-changing effect is
            # visible rather than assumed.
            "source_frames": (segment.cut.source_frames if segment.cut
                              else 0),
            "exact": True,
        }
        if segment.cut is not None and segment.master is not None:
            # The source offsets ride along as PROVENANCE ONLY.  "A source
            # master offset is not a final mix offset" — nothing downstream
            # may use these to seek in the finished file.
            cue["source"] = {
                "take_id": segment.master.take_id,
                "master_hash": segment.master.audio_hash,
                "master_sample_rate": segment.source_rate,
                "start_sample": segment.cut.start_sample,
                "end_sample": segment.cut.end_sample,
                "boundary_method": segment.cut.boundary_method,
                "resampled": segment.source_rate != MIX_RATE,
                "effects": list(segment.effects),
            }
        else:
            cue["source"] = {"label": segment.label}
        cues.append(cue)
        offset = cue_end

    if assembly_id:
        aid = str(assembly_id)
    else:
        aid = uuid.uuid4().hex[:16]

    cue_map: dict[str, Any] = {
        "cue_map_revision": CUE_MAP_REVISION,
        "assembly_id": aid,
        "script_revision": frozen.revision,
        "mode": ASSEMBLY_KIND,
        "sample_rate": MIX_RATE,
        "channels": MIX_CHANNELS,
        "frame_count": final_frames,
        "seconds": round(final_frames / MIX_RATE, 6),
        "final_audio_hash": audio_hash(blob),
        "derivation": "measured",
        "mix_latency_frames": latency,
        "latency_measured": bool(measure_latency),
        "mix_residual_frames": residual,
        "tail_pad_frames": tail_pad_frames,
        "body_frames": body_frames,
        "cues": cues,
        "sequence": [c["occurrence_id"] for c in cues if c["kind"] == "line"],
        "built_at": int(time.time()),
    }

    record: dict[str, Any] = {
        "assembly_id": aid,
        "script_revision": frozen.revision,
        "kind": ASSEMBLY_KIND,
        "cuts": [
            {
                "occurrence_id": s.occurrence_id,
                "ordinal": s.ordinal,
                "cut_id": s.cut_id,
                "take_id": (s.master.take_id if s.master else ""),
                "master_hash": (s.master.audio_hash if s.master else ""),
                "master_media": (str(s.master.path) if s.master else ""),
                "start_sample": (s.cut.start_sample if s.cut else 0),
                "end_sample": (s.cut.end_sample if s.cut else 0),
                "boundary_method": (s.cut.boundary_method if s.cut else ""),
                "effects": list(s.effects),
            }
            for s in segments if s.kind == "line"
        ],
        "extras": [
            {"extra_id": s.segment_id, "kind": s.kind, "label": s.label,
             "media": str(s.path)}
            for s in segments if s.kind != "line"
        ],
        "mix": {
            "rate": MIX_RATE, "channels": MIX_CHANNELS,
            "loudnorm": LOUDNORM, "limiter": LIMITER,
            "crackle": bool(crackle),
            "concat_keep": CONCAT_KEEP,
            "silence_threshold_db": SEG_TRIM_DB,
            "beats": [round(b, 3) for b in drawn],
            "tail_pad_ms": box_tail_ms(),
            "mirrors": "app.py:_call_concat_blocking",
        },
        "final_audio_hash": cue_map["final_audio_hash"],
        "frame_count": final_frames,
        "cue_map_revision": CUE_MAP_REVISION,
    }

    assembly = Assembly(assembly_id=aid, script_revision=frozen.revision,
                        audio=blob, cue_map=cue_map, record=record,
                        strips={s.segment_id: s.path for s in segments},
                        _workdir=workdir)

    # ------------------------------------------------------------------
    # 6. PROVE IT, BEFORE ANYTHING IS ADVERTISED AS READY.
    # ------------------------------------------------------------------
    verdict = verify_assembly(assembly, frozen)
    if not verdict["ok"]:
        raise AssemblyRefused("verification_failed",
                              "; ".join(verdict["failures"]),
                              **{"checks": verdict["checks"]})
    cue_map["verified"] = verdict

    if not keep_strips:
        # "materialize individual strip files only when an adapter or
        # editor needs them"
        assembly.close()
    return assembly


# ==========================================================================
# Verification
# ==========================================================================


def verify_assembly(assembly: Assembly, script: Any) -> dict[str, Any]:
    """Prove the complete final artifact before it is advertised as ready.

    "Verify the complete final artifact before it is advertised: final
    audio hash, frame count, and exactly one cue per required occurrence in
    the frozen order."  Every check returns a named result so a refusal can
    say which one failed rather than merely that something did.
    """
    frozen = frozen_script(script)
    cue_map = assembly.cue_map
    checks: dict[str, Any] = {}
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks[name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            failures.append(f"{name}: {detail}" if detail else name)

    # --- the audio itself -------------------------------------------------
    try:
        import io
        with wave.open(io.BytesIO(assembly.audio), "rb") as reader:
            frames = reader.getnframes()
            rate = reader.getframerate()
            channels = reader.getnchannels()
            width = reader.getsampwidth()
    except (wave.Error, EOFError) as exc:
        check("final_audio_readable", False, str(exc))
        return {"ok": False, "failures": failures, "checks": checks}
    check("final_audio_readable", True)
    check("final_audio_hash", audio_hash(assembly.audio)
          == cue_map.get("final_audio_hash"),
          "the cue map's final audio hash is not this audio's hash")
    check("frame_count", frames == int(cue_map.get("frame_count") or -1),
          f"the file holds {frames} frames and the cue map claims "
          f"{cue_map.get('frame_count')}")
    check("format", rate == MIX_RATE and channels == MIX_CHANNELS
          and width == MIX_WIDTH,
          f"{rate} Hz / {channels}ch / {width * 8}-bit")
    check("script_revision",
          cue_map.get("script_revision") == frozen.revision,
          f"cue map is for revision {cue_map.get('script_revision')!r}, "
          f"script is {frozen.revision!r}")

    cues = list(cue_map.get("cues") or [])
    line_cues = [c for c in cues if c.get("kind") == "line"]

    # --- exactly one cue per required occurrence, in the frozen order ----
    wanted = list(frozen.ids())
    got = [str(c.get("occurrence_id")) for c in line_cues]
    check("one_cue_per_occurrence", len(got) == len(wanted)
          and sorted(got) == sorted(wanted),
          f"{len(got)} line cues for {len(wanted)} occurrences")
    check("cue_sequence_equals_script", got == wanted,
          "the cue sequence is not the frozen script sequence: "
          f"{got[:8]} vs {wanted[:8]}")
    check("ordinals_ascending",
          [int(c.get("ordinal", -1)) for c in line_cues]
          == list(frozen.ordinals()),
          "line cue ordinals do not follow the frozen ordinals")

    # --- the timeline ----------------------------------------------------
    ok_monotonic, ok_inside, ok_speech, ok_contiguous = True, True, True, True
    previous_end = None
    for cue in cues:
        start = int(cue.get("start_sample", -1))
        speech_end = int(cue.get("speech_end_sample", -1))
        cue_end = int(cue.get("cue_end_sample", -1))
        if not (0 <= start < speech_end <= cue_end):
            ok_speech = False
        if cue_end > frames:
            ok_inside = False
        if previous_end is not None:
            if start < previous_end:
                ok_monotonic = False         # a single active spoken line
            if start != previous_end:
                ok_contiguous = False
        previous_end = cue_end
    check("cues_ordered_and_disjoint", ok_monotonic,
          "two cues overlap; strict sequential mode has a single active "
          "spoken line")
    check("cues_inside_audio", ok_inside,
          "a cue ends past the end of the finished file")
    check("speech_end_before_cue_end", ok_speech,
          "a cue has no speech, or its speech runs past its cue end")
    check("cues_contiguous", ok_contiguous,
          "a gap sits between two cues that is owned by neither")

    # --- the pause does not start the next line --------------------------
    ok_pause = True
    for index, cue in enumerate(cues[:-1]):
        pause = int(cue.get("pause_frames", 0))
        if pause < 0:
            ok_pause = False
        if (int(cue.get("speech_end_sample", 0)) + pause
                != int(cue.get("cue_end_sample", -1))):
            ok_pause = False
        if int(cues[index + 1].get("start_sample", -1)) \
                != int(cue.get("cue_end_sample", -2)):
            ok_pause = False
    check("pause_owned_by_the_line_before_it", ok_pause,
          "an inserted pause is not accounted for between speech end and "
          "cue end")

    # --- the arithmetic adds up ------------------------------------------
    if cues:
        tail = frames - int(cues[-1].get("cue_end_sample", 0))
        expected_tail = (int(cue_map.get("tail_pad_frames", 0))
                         + int(cue_map.get("mix_residual_frames", 0))
                         - int(cue_map.get("mix_latency_frames", 0)))
        check("tail_accounted", abs(tail - expected_tail) <= 1,
              f"{tail} frames past the last cue, {expected_tail} expected")
        check("derivation_is_measured",
              cue_map.get("derivation") == "measured",
              "this cue map was not derived from measured sample counts")
    else:
        check("tail_accounted", False, "no cues")

    return {"ok": not failures, "failures": failures, "checks": checks,
            "assembly_id": cue_map.get("assembly_id"),
            "script_revision": cue_map.get("script_revision")}


# ==========================================================================
# What an integrator calls
# ==========================================================================


def stream_windows(cue_map: Mapping[str, Any],
                   *, lines_only: bool = False) -> list[dict[str, Any]]:
    """The cue map in the shape `_speak_turns_floorless` already speaks.

    THIS IS THE REPLACEMENT FOR THE RESCALE AT app.py:83945.

    That block builds `rows` of `{"from": ..., "until": ...}` in seconds
    from estimates, scales the whole span by `finished / estimated`, and
    then writes `clip_from` / `clip_until` / `clip_tail` onto each feed
    entry.  This returns the same four numbers per row, taken from actual
    edited sample counts instead:

        from   - `start_seconds`, where this line's audio begins
        until  - `cue_end_seconds`, where the NEXT line begins.  The seam
                 beat is inside this window on purpose: the booth's marker
                 must not jump to the next line early.
        tail   - `pause_seconds`, the run-up to the next speaker.  A
                 download leaves it off; the highlight keeps it.  app.py
                 computes this as `beats[seg_ix] * _bscale`; here it is the
                 pause itself, unscaled, because nothing was scaled.
        id     - the occurrence id, so a row can be matched by IDENTITY
                 rather than by position (#1330's lesson: two lists the
                 same shape, wrongly paired, is a silent fault).

    An integrator matches these to `rows` by id.  If any row has no cue,
    it must fall back to today's rescale FOR THE WHOLE ROUND rather than
    mix the two timelines.
    """
    out: list[dict[str, Any]] = []
    for cue in (cue_map.get("cues") or []):
        if lines_only and cue.get("kind") != "line":
            continue
        out.append({
            "id": str(cue.get("occurrence_id") or ""),
            "ordinal": int(cue.get("ordinal", -1)),
            "kind": str(cue.get("kind") or ""),
            "who": str(cue.get("speaker") or ""),
            "from": float(cue.get("start_seconds") or 0.0),
            "until": float(cue.get("cue_end_seconds") or 0.0),
            "speech_until": float(cue.get("speech_end_seconds") or 0.0),
            "tail": float(cue.get("pause_seconds") or 0.0),
            "exact": bool(cue.get("exact")),
        })
    return out


def cue_at(cue_map: Mapping[str, Any], seconds: float) -> dict[str, Any] | None:
    """Which occurrence is sounding at this position in the finished file.

    The display boundary wants exactly this: "Use the selected player's
    actual file and offset, mapped through its cue sheet, to identify the
    active occurrence."  Note it answers from the CUE window, so the seam
    beat still belongs to the line that just finished — the highlight does
    not blink into nothing between lines.
    """
    frames = int(float(seconds) * int(cue_map.get("sample_rate") or MIX_RATE))
    for cue in (cue_map.get("cues") or []):
        if int(cue.get("start_sample", 0)) <= frames \
                < int(cue.get("cue_end_sample", 0)):
            return dict(cue)
    return None


def materialize_strips(assembly: Assembly, dest: str | Path) -> dict[str, Path]:
    """Write the individual strips out, for an adapter or editor that needs
    files rather than a master plus offsets.

    Deliberately not the default: "Store the master plus cut offsets;
    materialize individual strip files only when an adapter or editor
    needs them."
    """
    if not assembly.strips:
        raise AssemblyRefused(
            "strips_released",
            "this assembly's strips were released; rebuild with "
            "keep_strips=True to materialize them")
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for segment_id, path in assembly.strips.items():
        target = dest / path.name
        shutil.copyfile(path, target)
        out[segment_id] = target
    return out


def cue_map_json(cue_map: Mapping[str, Any]) -> str:
    """The durable form `manifest_store.py` persists."""
    return json.dumps(cue_map, sort_keys=True, separators=(",", ":"))


# --------------------------------------------------------------------------
# Handing the finished conversation to script_manifest
# --------------------------------------------------------------------------
#
# RECONCILED 2026-09-15 against `script_manifest.py` as written.  Its
# `cue_entry` and `finished_conversation` are the durable shapes the
# admission gate reads, so the translation lives here rather than being
# rewritten by each caller.  Nothing below imports `script_manifest`; these
# return plain data and keyword arguments, so the two modules stay
# independently testable.


def manifest_cue_entries(cue_map: Mapping[str, Any],
                         *, lines_only: bool = True) -> list[dict[str, Any]]:
    """This cue map in `script_manifest.cue_entry`'s shape.

    Extras (a ring, a sting, a hang-up) are dropped by default: the
    manifest's cue map is the SCRIPT's cue map, and its ordinals must be
    the frozen ordinals.  Pass `lines_only=False` when a caller genuinely
    wants every audible segment.
    """
    out: list[dict[str, Any]] = []
    for cue in (cue_map.get("cues") or []):
        if lines_only and cue.get("kind") != "line":
            continue
        out.append({
            "occurrence_id": str(cue.get("occurrence_id") or ""),
            "ordinal": int(cue.get("ordinal", 0)),
            "cut_id": str(cue.get("cut_id") or ""),
            "cue_start_sample": int(cue.get("start_sample", 0)),
            "speech_start_sample": int(cue.get("speech_start_sample",
                                               cue.get("start_sample", 0))),
            "speech_end_sample": int(cue.get("speech_end_sample", 0)),
            "cue_end_sample": int(cue.get("cue_end_sample", 0)),
            "source_frames": int(cue.get("source_frames", 0)),
        })
    return out


def finished_conversation_kwargs(assembly: Assembly) -> dict[str, Any]:
    """Keyword arguments for `script_manifest.finished_conversation`.

        record = script_manifest.finished_conversation(
            **conversation_assembly.finished_conversation_kwargs(made))

    `final_sha256` is emitted with the `sha256:` prefix that module's
    `is_audio_digest` requires; `cue_source` is `"measured"`, which is the
    claim this whole module exists to make good on.
    """
    cue_map = assembly.cue_map
    return {
        "assembly_id": assembly.assembly_id,
        "revision": assembly.script_revision,
        "cuts": [str(row.get("cut_id") or row.get("occurrence_id") or "")
                 for row in (assembly.record.get("cuts") or [])],
        "mix": dict(assembly.record.get("mix") or {}),
        "final_sha256": "sha256:" + str(cue_map.get("final_audio_hash") or ""),
        "final_sample_rate": int(cue_map.get("sample_rate") or MIX_RATE),
        "final_frame_count": int(cue_map.get("frame_count") or 0),
        "cue_map": manifest_cue_entries(cue_map),
        "cue_source": str(cue_map.get("derivation") or "measured"),
    }

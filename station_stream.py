"""A real broadcast stream: one URL, one socket, the mix made on the box.

WHY THIS EXISTS (measured 2026-09-12, listening from a car)
-----------------------------------------------------------
The tune page is not a stream. It is a CLOCK-CHASER: it seeks a record
file to a position the server dictates, and plays every DJ line as its
own HTTP fetch against a deadline. On the house LAN that works. On a
cellular link it cannot, and the reasons are structural rather than
tunable:

  * THE LOOP STALLS. 121 of the 144 dead-air gaps in one six-hour window
    were logged `cause: event-loop stall`, 5,530 of 5,945 dead seconds;
    over 24 hours the station spent 7,276 seconds - two hours - with its
    event loop blocked in a synchronous read. The public listener door
    is a second uvicorn IN THE SAME PROCESS, so the clock, the voice
    feed and the record's byte-ranges all freeze together. A clock-chaser
    turns a 30-second stall into 30 seconds of broken audio. A stream
    with a buffer in front of it turns the same stall into NOTHING AT
    ALL - the listener is simply half a minute behind, which on a radio
    is not a fault, it is what radio is.

  * A LATE LINE IS THROWN AWAY. voiceNext() drops any clip past its
    deadline as `hopeless`, so a bad link does not make the show late,
    it makes the show THINNER - the music survives and the talk you
    tuned in for disappears.

  * A SLEEPING PHONE STOPS POLLING. The page drains its queue on
    setInterval; a screen-locked phone throttles those to minutes or
    freezes them, so the queue stops draining and the backlog ages out
    under the deadline rule above.

A stream has none of these properties. The mix is made once, here, at
exactly real time, and each listener holds one long response open and
buffers ahead of it. That is the whole cure: BUFFER AHEAD IS LEGAL when
there is no clock to chase.

WHAT IT DOES NOT DO
-------------------
It does not try to hold the shared on-air instant. It cannot, and that
is the point - the house players stay sample-synchronised with each
other on the old road, and this one carries the same show to the road a
few seconds behind. Nothing here writes to station state; it only reads
a snapshot the host hands it, so a fault in the mixer can never take the
station off the air.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import shutil
import statistics
import subprocess
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Iterator

import numpy as np

# ---------------------------------------------------------------------------
# The shape of the timeline. Everything inside the mixer is s16le stereo at
# this rate; the encoder is the only thing that knows about mp3.
# ---------------------------------------------------------------------------
RATE = 44100
CHANNELS = 2
SAMPLE_BYTES = 2
FRAME_MS = 100
FRAME_SAMPLES = RATE * FRAME_MS // 1000          # 4410
FRAME_BYTES = FRAME_SAMPLES * CHANNELS * SAMPLE_BYTES

SILENCE = b"\0" * FRAME_BYTES

# How much decoded audio a source may run ahead. This is the slack that
# absorbs the CIFS music share (#1156 measured 38s for 2MB) and any stall
# in the box itself - the decoder fills it whenever the box is free.
SOURCE_BUFFER_BYTES = 8 * 1024 * 1024            # ~47 s of stereo PCM

# What a joining listener is handed before the live edge. A car radio that
# starts instantly and is eight seconds behind beats one that buffers in
# silence for eight seconds, and it means the FIRST tower handoff already
# has something to eat.
JOIN_BURST_SECONDS = float(os.getenv("STREAM_JOIN_BURST", "30"))

# The bitrates a listener may ask for. Anything else is snapped to the
# nearest of these, so a junk query cannot make the box spawn encoders.
STREAM_RATES = (32, 48, 64, 96, 128, 192)
DEFAULT_RATE = int(os.getenv("STREAM_BITRATE", "128"))


def snap_rate(want: Any) -> int:
    """A listener number becomes one of the rates we encode, or the
    default. This is the only place that decision is made."""
    try:
        n = int(float(str(want).strip() or 0))
    except Exception:  # noqa: BLE001
        return DEFAULT_RATE
    if n <= 0:
        return DEFAULT_RATE
    return min(STREAM_RATES, key=lambda r: abs(r - n))

# How far a single listener may fall behind before we stop holding their
# backlog. Sixty seconds of mp3 is about a megabyte; past that the socket
# is not coming back and the memory is better spent elsewhere.
LISTENER_QUEUE_SECONDS = float(os.getenv("STREAM_LISTENER_QUEUE", "60"))

# The mixer runs while anyone is listening, and lingers after the last one
# leaves so that a tunnel, a tower handoff or a car park does not cost a
# cold start on the way back.
LINGER_SECONDS = float(os.getenv("STREAM_LINGER", "180"))

# The bed, and how far it drops under a voice. The page defaults to 20%
# music because a phone speaker buries the talk; a car does not have that
# problem, so the bed sits higher here and ducks harder.
MUSIC_LEVEL = float(os.getenv("STREAM_MUSIC_LEVEL", "0.38"))
MUSIC_DUCK = float(os.getenv("STREAM_MUSIC_DUCK", "0.11"))
VOICE_LEVEL = float(os.getenv("STREAM_VOICE_LEVEL", "1.0"))
DUCK_RAMP_MS = 180

# A clip this far past its air moment at PRODUCTION time is genuinely
# historical - the mixer was not running when it was due. It is generous
# on purpose: unlike the page, this road has no reason to be tidy about
# lateness, and a whole banter round is worth hearing late.
CLIP_GRACE_SECONDS = float(os.getenv("STREAM_CLIP_GRACE", "45"))

# How far behind real time the mixer will chase before giving up on
# the difference. Everything short of this is caught up in full, which
# is what keeps the average at 1x through a stall.
CATCHUP_LIMIT = float(os.getenv("STREAM_CATCHUP_LIMIT", "60"))

# How long the mixer will wait for a starved decoder before giving up
# and emitting a hole. The sources read from local disk, so a wait
# this long is only ever the GIL, and the burst covers the lateness.
STARVE_WAIT_MAX = float(os.getenv("STREAM_STARVE_WAIT", "0.25"))

# HLS. Four-second segments with fifteen in the playlist leave a one-minute
# recovery window on a mobile tailnet route. A dropped connection still costs
# one small segment rather than the broadcast, while Safari can stay behind
# the moving live edge through a tower handoff or a brief box stall.
HLS_SEGMENT_SECONDS = float(os.getenv("STREAM_HLS_SEGMENT", "4"))
# #1473: the ABR brief asked for 12 (a 48 s window, enough for a 30 s
# start offset). It stays 15: tests/test_listener_h3_2026_09_25.py pins
# `>= 15`, and 60 s holds the 30 s offset with a whole extra tower
# handoff of room. The cost is 3 more segments x 4 variants on /tmp.
HLS_LIST_SIZE = int(os.getenv("STREAM_HLS_LIST", "15"))
# A phone should not begin its first moving-car session on a single segment.
# Three completed four-second chunks are enough for a tower handoff while
# keeping the initial tune-in delay bounded.
HLS_START_SEGMENTS = int(os.getenv("STREAM_HLS_START_SEGMENTS", "3"))
HLS_ROOT = os.getenv("STREAM_HLS_DIR", "")

# #1473: ADAPTIVE VARIANTS IN ONE ENCODER.
#
# MEASURED 2026-09-27: a new HLS lane waited for three finished segments
# before its first playlist answered - 12.5 to 13.4 s of silence on every
# join, every slider move (a new lane) and every restart. Two things fix
# that and both live here: the lane is PRIMED with the mixer's 30 s PCM
# backlog (so it holds half a minute of segments within a second or two
# of starting), and there is ONE lane carrying every rate rather than a
# lane per rate, so a player that changes quality steps between folders
# of one process instead of waking a cold encoder. The four rates are
# AAC-LC; the master playlist lists them by bandwidth, and the segments
# are numbered identically across the four folders because one process
# cuts them from one clock.
HLS_VARIANT_RATES = (48, 64, 96, 128)
# The mix every lane is keyed under when a listener has not moved a
# slider. The warm lane is this one.
HLS_DEFAULT_MIX = (100, 100, 100)
# The per-token ledger's rules. A healthy player asks for a segment
# every HLS_SEGMENT_SECONDS; a gap past six seconds between two segment
# requests is a missed beat. It is a STALL when the player stayed
# ACTIVE through it (never twenty seconds without asking for anything -
# it was there, polling, and did not get or take its next segment), and
# a DROPOUT when it went quiet for twenty seconds or more (a dead zone,
# a locked phone, a new session). The two are counted apart so the car
# diagnostics can tell our fault from the road's. A token is ACTIVE
# while its last request is under twenty seconds old, and one idle for
# an hour is forgotten so the table cannot grow for ever.
HLS_STALL_GAP_S = float(os.getenv("STREAM_HLS_STALL_GAP", "6"))
HLS_ACTIVE_S = 20.0
HLS_TOKEN_IDLE_S = 3600.0
HLS_LEDGER_ROTATE_BYTES = 5 * 1024 * 1024
HLS_LEDGER_QUEUE = 5000
# A lane whose ffmpeg will not start must not be retried ten times a
# second by the mixer - that is a Popen storm on a box that is already
# unhappy. One try every five seconds is enough to come back.
HLS_RESTART_BACKOFF_S = 5.0


def hls_snap_rate(want: Any) -> int:
    """A requested HLS rate becomes one of the four variants.

    #1473: the lane encodes every variant at once, so 'the rate' is only
    which sub-folder a single-rate caller is pointed at. Junk, zero, and
    the mp3 road's 32k/192k all land on the nearest variant rather than
    on a folder that does not exist."""
    try:
        n = int(float(str(want).strip() or 0))
    except Exception:  # noqa: BLE001
        n = 0
    if n <= 0:
        n = DEFAULT_RATE
    return min(HLS_VARIANT_RATES, key=lambda r: abs(r - n))


def hls_ffmpeg_argv(lane_dir: Path | str,
                    rates: tuple[int, ...] = HLS_VARIANT_RATES,
                    start_number: int = 0,
                    exe: str | None = None,
                    discontinuity: bool = False) -> list[str]:
    """The one ffmpeg that writes every variant of one lane.

    #1473: FOUR VARIANTS, ONE PROCESS, ONE CLOCK. Each `-map 0:a` is the
    same PCM again; the aac encoder cuts every variant into 1024-sample
    frames from the same timestamps, and the hls muxer opens a new
    segment on the first frame past `hls_time` in EACH variant, so the
    boundaries and the numbers line up across the four folders and a
    player may step between them mid-stream without a hole. `%v` is the
    `name:` from the map, which is how `<lane>/48/seg00007.ts` and
    `<lane>/48/index.m3u8` find their folder; the master lands one level
    up, because hlsenc walks up one dirname when the folder pattern
    itself carries the `%v`. The folders must exist first - hlsenc only
    mkdirs for strftime names - and start() makes them.

    Kept as a plain function so a dry run can print it and run it against
    a file without a mixer.
    """
    lane = str(lane_dir)
    argv = [exe or _ffmpeg_exe(), "-nostdin", "-hide_banner",
            "-loglevel", "error",
            # The same demuxer note as _Encoder.start: five seconds of
            # analyzeduration spent on a pipe whose format is declared on
            # the very next line, and a 4.6 s first byte for nothing.
            "-analyzeduration", "0", "-probesize", "32",
            "-fflags", "+nobuffer",
            "-f", "s16le", "-ar", str(RATE), "-ac", str(CHANNELS),
            "-i", "pipe:0"]
    for _ in rates:
        argv += ["-map", "0:a"]
    argv += ["-c:a", "aac"]                 # the native encoder is AAC-LC
    for i, r in enumerate(rates):
        argv += [f"-b:a:{i}", f"{int(r)}k"]
    argv += ["-f", "hls",
             "-hls_time", str(HLS_SEGMENT_SECONDS),
             "-hls_list_size", str(HLS_LIST_SIZE),
             # delete_segments bounds the folder; omit_endlist keeps the
             # playlist LIVE so a player never decides the show is over;
             # program_date_time lets a player place itself in time;
             # independent_segments is kept for the day a video variant
             # joins the lane - for audio-only hlsenc ignores it, and
             # hls_dress_playlist() supplies the tag instead; temp_file
             # means a reader never meets a half-written playlist or a
             # segment still being written - the seg*.ts glob in ready()
             # therefore counts only finished ones.
             "-hls_flags",
             "independent_segments+program_date_time+delete_segments"
             "+omit_endlist+temp_file"
             # A RESTARTED process begins its timestamps again; the
             # first segment it writes says so, or a player that
             # carries on across the seam decodes it against the old
             # clock and drops it.
             + ("+discont_start" if discontinuity else ""),
             "-hls_segment_type", "mpegts",
             "-hls_allow_cache", "0",
             # After an ffmpeg restart the sequence CONTINUES from where
             # the folder left off. A player that sees the media
             # sequence go backwards treats the stream as broken; one
             # that sees it jump forward treats it as a gap and carries
             # on, which is the truth of the matter.
             "-start_number", str(max(0, int(start_number))),
             "-var_stream_map",
             " ".join(f"a:{i},name:{int(r)}" for i, r in enumerate(rates)),
             "-master_pl_name", "master.m3u8",
             "-hls_segment_filename", os.path.join(lane, "%v", "seg%05d.ts"),
             os.path.join(lane, "%v", "index.m3u8")]
    return argv


def hls_dress_playlist(text: str,
                       start_offset_s: float | None = None) -> str:
    """Add what hlsenc leaves out of an audio-only lane. Pure; app.py
    calls it on a master or variant playlist before rewriting URIs.

    MEASURED #1473 (host 6.1.1 and container 7.0.2): with
    `independent_segments` in -hls_flags, hlsenc still writes no
    #EXT-X-INDEPENDENT-SEGMENTS - it only writes the tag for a variant
    that carries VIDEO. Every AAC frame is a sync point, so for this lane
    the tag is simply true, and it is what lets a player switch variant
    at any segment boundary without fetching a neighbour first.

    `start_offset_s` (hls_start_offset_s()) becomes
    #EXT-X-START:TIME-OFFSET=-N - where a joining player should begin,
    measured back from the end of the playlist. That is the 30 s
    cushion. PRECISE=NO lets the player start on the segment boundary
    rather than decode into the middle of one.
    """
    lines = str(text or "").splitlines()
    if not lines or not lines[0].startswith("#EXTM3U"):
        return str(text or "")
    add: list[str] = []
    if "#EXT-X-INDEPENDENT-SEGMENTS" not in text:
        add.append("#EXT-X-INDEPENDENT-SEGMENTS")
    if start_offset_s and start_offset_s > 0 and "#EXT-X-START:" not in text:
        add.append("#EXT-X-START:TIME-OFFSET=-%.1f,PRECISE=NO"
                   % float(start_offset_s))
    if not add:
        return str(text)
    at = 1
    if len(lines) > 1 and lines[1].startswith("#EXT-X-VERSION"):
        at = 2
    out = lines[:at] + add + lines[at:]
    return "\n".join(out) + "\n"


def _client_ip(addr: Any, xff: Any) -> str:
    """The address that identifies the LISTENER, not the last hop.

    Through the funnel every request arrives from tailscaled itself
    (a 100.x or loopback address) with the real client in
    X-Forwarded-For; a tailnet or LAN client arrives directly with no
    such header. So the first forwarded hop wins when there is one, and
    the socket address otherwise."""
    first = str(xff or "").split(",")[0].strip()
    ip = first or str(addr or "").strip()
    if ip.lower().startswith("::ffff:"):
        ip = ip[7:]
    return ip


def hls_road(addr: Any, xff: Any) -> str:
    """Which door this listener came through: tailnet, lan or funnel."""
    ip = _client_ip(addr, xff).lower()
    if ip.startswith("100.") or ip.startswith("fd7a:"):
        return "tailnet"
    if ip.startswith(("10.", "192.168.", "127.", "::1")):
        return "lan"
    if ip.startswith("172."):
        try:
            if 16 <= int(ip.split(".")[1]) <= 31:
                return "lan"
        except (IndexError, ValueError):
            pass
    return "funnel"


def _hls_ledger_path() -> Path:
    """data/hls_ledger.jsonl, resolved the way app.py resolves data/.

    In the container both roads are /app/data; on the host it is the
    repo's data/. STREAM_HLS_LEDGER points a test somewhere harmless."""
    explicit = os.getenv("STREAM_HLS_LEDGER", "")
    if explicit:
        return Path(explicit).expanduser()
    data = os.getenv("SPARK_AGENT_DATA_DIR", "")
    base = (Path(data).expanduser() if data
            else Path(__file__).resolve().parent / "data")
    return base / "hls_ledger.jsonl"


def _ffmpeg_exe() -> str:
    """The one ffmpeg this box has. imageio's binary first, PATH second."""
    try:
        import imageio_ffmpeg

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:  # noqa: BLE001
        return shutil.which("ffmpeg") or "ffmpeg"


class _Decoder:
    """One audio file, decoded to the timeline's PCM shape, read ahead.

    ffmpeg does the decoding and the resampling; a pump thread keeps the
    buffer as full as the box will allow. read() never blocks the mixer:
    a starved decoder returns silence for that frame and catches up on
    the next one, which is what keeps a slow share off the broadcast.
    """

    def __init__(self, path: str | Path, offset: float = 0.0,
                 gain: float = 1.0) -> None:
        self.path = str(path)
        self.gain = float(gain)
        self._buf = deque()                 # bytes chunks
        self._held = 0
        self._lock = threading.Lock()
        self._room = threading.Condition(self._lock)
        self._eof = False
        self._dead = False
        self._proc: subprocess.Popen | None = None
        self._started = False
        self._offset = max(0.0, float(offset))
        self._pump: threading.Thread | None = None
        self.padded = 0                 # frames we had to zero-fill

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> bool:
        if self._started:
            return self._proc is not None
        self._started = True
        cmd = [_ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error"]
        if self._offset > 0.05:
            # Before -i, so ffmpeg seeks rather than decodes and discards.
            cmd += ["-ss", f"{self._offset:.3f}"]
        cmd += ["-i", self.path,
                "-vn",
                "-f", "s16le", "-acodec", "pcm_s16le",
                "-ar", str(RATE), "-ac", str(CHANNELS),
                "pipe:1"]
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, bufsize=0)
        except Exception:  # noqa: BLE001
            self._proc = None
            self._eof = True
            return False
        self._pump = threading.Thread(target=self._fill, name="pcm-pump",
                                      daemon=True)
        self._pump.start()
        return True

    def _fill(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            while not self._dead:
                with self._room:
                    while (self._held >= SOURCE_BUFFER_BYTES
                           and not self._dead):
                        self._room.wait(0.25)
                    if self._dead:
                        return
                chunk = proc.stdout.read(FRAME_BYTES * 4)
                if not chunk:
                    break
                with self._room:
                    self._buf.append(chunk)
                    self._held += len(chunk)
        except Exception:  # noqa: BLE001
            pass
        finally:
            with self._room:
                self._eof = True
                self._room.notify_all()

    def close(self) -> None:
        self._dead = True
        with self._room:
            self._room.notify_all()
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:  # noqa: BLE001
                pass

    # -- reading -----------------------------------------------------------
    @property
    def finished(self) -> bool:
        with self._lock:
            return self._eof and self._held <= 0

    @property
    def ready_bytes(self) -> int:
        with self._lock:
            return self._held

    def has_frame(self) -> bool:
        """A COMPLETE frame, right now, without padding.

        The mixer asks this before it consumes. Without it, a short read
        is silently zero-filled and the hole never appears in any
        counter - which is how 687 ms of digital silence got onto the
        air with `underruns` reading zero."""
        with self._lock:
            return self._held >= FRAME_BYTES or self._eof

    def read_frame(self) -> tuple[bytes, bool]:
        """One frame of PCM, and whether it is real audio.

        A starved-but-not-finished decoder yields silence rather than
        stalling the mix; the frame it could not give is not skipped in
        the file, only in time, which for a music bed is inaudible and
        for a voice clip is a hole rather than a garble.
        """
        want = FRAME_BYTES
        out = bytearray()
        with self._room:
            while want > 0 and self._buf:
                chunk = self._buf[0]
                if len(chunk) <= want:
                    out += chunk
                    want -= len(chunk)
                    self._buf.popleft()
                    self._held -= len(chunk)
                else:
                    out += chunk[:want]
                    self._buf[0] = chunk[want:]
                    self._held -= want
                    want = 0
            eof = self._eof
            self._room.notify_all()
        if not out:
            if not eof:
                self.padded += 1
            return SILENCE, (not eof)
        if want:
            # The tail of a file (legitimate), or a starved decoder (a
            # hole). Only the second is a fault, so only it is counted.
            if not eof:
                self.padded += 1
            out += b"\0" * want
        return bytes(out), True


def _pcm(buf: bytes) -> np.ndarray:
    return np.frombuffer(buf, dtype="<i2").astype(np.int32)


def _centered_pcm(buf: bytes) -> np.ndarray:
    """Return a two-channel programme signal with every source in both ears.

    A few legacy video and SFX files have useful audio on only one side.  The
    listener stream used to preserve that mistake, and an experimental
    split-bus mode made it worse by putting music left and dialogue right.
    Fold each decoded source before it reaches the programme mixer, then
    duplicate that centred programme into the two-channel encoder input.
    """
    values = _pcm(buf)
    if values.size < CHANNELS:
        return values
    frames = values[:(values.size // CHANNELS) * CHANNELS].reshape(-1, CHANNELS)
    centre = (frames[:, 0] + frames[:, 1]) // 2
    frames[:, 0] = centre
    frames[:, 1] = centre
    return values


def listener_mix(raw: Any = None) -> tuple[int, int, int]:
    """A bounded personal (music, DJ, SFX) mix for one HLS listener."""
    if isinstance(raw, (tuple, list)):
        parts = list(raw)
    else:
        parts = str(raw or "").split(",")
    if len(parts) != 3:
        return (100, 100, 100)
    try:
        return tuple(max(0, min(200, int(float(value)))) for value in parts)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return (100, 100, 100)


def _mixed_program(bed: np.ndarray, voice: np.ndarray | None,
                   voice_is_sfx: bool, mix: Any = None) -> bytes:
    """Mix one centred stereo programme frame for one listener's settings."""
    music_pct, dj_pct, sfx_pct = listener_mix(mix)
    music_gain = MUSIC_LEVEL * music_pct / 100.0
    voice_gain = VOICE_LEVEL * (sfx_pct if voice_is_sfx else dj_pct) / 100.0
    combined = bed * music_gain
    if voice is not None:
        combined[:min(combined.size, voice.size)] += (
            voice[:min(combined.size, voice.size)] * voice_gain)
    np.clip(combined, -32768, 32767, out=combined)
    return combined.astype("<i2").tobytes()


def _split_program(bed: np.ndarray, voice: np.ndarray | None,
                   voice_is_sfx: bool, mix: Any = None) -> bytes:
    """#1265 by way of #1473: L = the record, R = the DJ, unmixed.

    For the listener who wants to balance the two at their own knob.
    It cannot be the programme mix (see _centered_pcm), so it is its
    own HLS lane, keyed by `split`, fed this frame instead. The duck
    is still in `bed` when it arrives here, so the record still dips
    under a line; the listener's own knob only decides how far apart
    the two sit."""
    music_pct, dj_pct, sfx_pct = listener_mix(mix)
    n = (bed.size // CHANNELS) * CHANNELS
    out = np.zeros((n // CHANNELS, CHANNELS), dtype=np.float64)
    out[:, 0] = bed[:n].reshape(-1, CHANNELS)[:, 0] * (
        MUSIC_LEVEL * music_pct / 100.0)
    if voice is not None and voice.size >= CHANNELS:
        m = (min(voice.size, n) // CHANNELS) * CHANNELS
        out[:m // CHANNELS, 1] = voice[:m].reshape(-1, CHANNELS)[:, 0] * (
            VOICE_LEVEL * (sfx_pct if voice_is_sfx else dj_pct) / 100.0)
    np.clip(out, -32768, 32767, out=out)
    return out.astype("<i2").tobytes()


class _Voice:
    """A DJ clip waiting for, or sitting on, its air moment."""

    __slots__ = ("key", "air_at", "path", "length", "sfx", "decoder", "started")

    def __init__(self, key: str, air_at: float, path: str,
                 length: float, sfx: bool = False) -> None:
        self.key = key
        self.air_at = float(air_at)
        self.path = path
        self.length = float(length or 0)
        self.sfx = bool(sfx)
        self.decoder: _Decoder | None = None
        self.started = False


class _Encoder:
    """One mp3 encoder at one bitrate, its burst ring, and its listeners.

    The mix is made once by the mixer thread and handed to every live
    encoder, so a second listener at a different quality costs one lame
    process and nothing else - not a second decode of the record, and
    certainly not a second set of DJ clips.
    """

    def __init__(self, bitrate: int, split: bool = False) -> None:
        self.bitrate = int(bitrate)
        # #1265: L=record, R=DJs, for a listener who wants to balance the
        # two for themselves. See the module note on why this cannot be
        # done in the mixer.
        self.split = bool(split)
        self.proc: subprocess.Popen | None = None
        self.sinks: dict[int, "_Sink"] = {}
        self.burst: deque[bytes] = deque()
        self.burst_bytes = 0
        self.burst_max = int(self.bitrate * 1000 / 8 * JOIN_BURST_SECONDS)
        self.idle_since = time.time()
        self.restarts = 0
        # Frames handed over by attach(), to be written by the MIXER
        # thread before any live frame. Never written by anyone else:
        # two writers on one stdin interleave into noise.
        self.prime: list[bytes] = []
        self.lock = threading.Lock()
        self._drain: threading.Thread | None = None

    def start(self) -> bool:
        cmd = [_ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error",
               # MEASURED: without these the encoder emitted NOTHING for
               # 4.60s and then dumped the lot in one go. It is not output
               # buffering, which is where anyone would look first and
               # where four flags made no difference at all. It is the
               # DEMUXER analyzeduration, five seconds by default, spent
               # studying a raw PCM pipe whose format is declared on the
               # very next line. These take first-byte from 4.60s to
               # 0.01s, and a car radio that makes a sound immediately is
               # the difference between tuned in and broken.
               "-analyzeduration", "0", "-probesize", "32",
               "-fflags", "+nobuffer",
               "-f", "s16le", "-ar", str(RATE), "-ac", str(CHANNELS),
               "-i", "pipe:0",
               "-c:a", "libmp3lame", "-b:a", f"{self.bitrate}k",
               "-reservoir", "0",
               "-write_xing", "0",
               "-flush_packets", "1",
               "-avioflags", "direct",
               "-f", "mp3", "pipe:1"]
        try:
            self.proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=0)
        except Exception:  # noqa: BLE001
            self.proc = None
            return False
        self._drain = threading.Thread(target=self._pump, args=(self.proc,),
                                       name=f"enc-{self.bitrate}", daemon=True)
        self._drain.start()
        return True

    def _pump(self, proc: subprocess.Popen) -> None:
        """Encoded bytes out to this rate's listeners. This thread must
        never stop reading: an undrained stdout blocks the encoder, a
        blocked encoder blocks the mixer write, and then every listener
        on every rate goes quiet together."""
        out = proc.stdout
        if out is None:
            return
        try:
            while True:
                chunk = out.read(2048)
                if not chunk:
                    return
                with self.lock:
                    self.burst.append(chunk)
                    self.burst_bytes += len(chunk)
                    while self.burst_bytes > self.burst_max and self.burst:
                        self.burst_bytes -= len(self.burst.popleft())
                    sinks = list(self.sinks.values())
                for sink in sinks:
                    sink.offer(chunk)
        except Exception:  # noqa: BLE001
            return

    def feed(self, frame: bytes) -> bool:
        proc = self.proc
        if proc is None or proc.poll() is not None or proc.stdin is None:
            self.restarts += 1
            self.stop()
            if not self.start():
                return False
            proc = self.proc
        try:
            if proc is not None and proc.stdin is not None:
                proc.stdin.write(frame)
            return True
        except Exception:  # noqa: BLE001
            self.stop()
            return False

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


class _HlsVariant:
    """One rate of an ABR lane, wearing the old single-rate encoder's face.

    #1473: `hls(br)` used to hand back the encoder for that one rate, and
    app.py reads `.playlist`, `.dir`, `.bitrate`, `.mix` and calls
    `.ready()` on it. All of that still works: this is a view onto one
    folder of the lane. One handle per rate per lane, so two calls for
    the same rate return the same object (the test relies on `is`)."""

    def __init__(self, lane: "_HlsEncoder", rate: int) -> None:
        self.lane = lane
        self.bitrate = int(rate)
        self.dir = lane.variant_dir(self.bitrate)
        self.playlist = lane.variant_playlist(self.bitrate)

    @property
    def mix(self) -> tuple[int, int, int]:
        return self.lane.mix

    @property
    def split(self) -> bool:
        return self.lane.split

    @property
    def master(self) -> Path:
        return self.lane.master

    @property
    def prime(self) -> list[bytes]:
        return self.lane.prime

    @property
    def proc(self) -> subprocess.Popen | None:
        return self.lane.proc

    @property
    def restarts(self) -> int:
        return self.lane.restarts

    @property
    def asked_at(self) -> float:
        return self.lane.asked_at

    @asked_at.setter
    def asked_at(self, when: float) -> None:
        self.lane.asked_at = float(when)

    def ready(self, minimum_segments: int = 1) -> bool:
        return self.lane.ready(minimum_segments, self.bitrate)

    def feed(self, frame: bytes) -> bool:
        return self.lane.feed(frame)

    def start(self) -> bool:
        return self.lane.start()

    def stop(self) -> None:
        self.lane.stop()


class _HlsEncoder:
    """One HLS LANE: one ffmpeg, four AAC variants, one folder tree.

    #1473: the lane is keyed by (split, mix), not by rate - every rate
    comes out of this one process, aligned, under one master playlist:

        <root>/hlsabr-m100-100-100/master.m3u8
        <root>/hlsabr-m100-100-100/48/index.m3u8, seg00007.ts ...
        <root>/hlsabr-m100-100-100/64/...   96/...   128/...

    ffmpeg owns the segmenting and the playlist rolling; this class feeds
    it PCM, remembers when somebody last asked (`asked_at`, the reaper's
    heartbeat), whether it is WARM (kept by policy rather than by a
    player), and what it was primed with, so `hls_start_offset_s()` can
    tell a player how far behind live it may safely begin.
    """

    def __init__(self, root: Path,
                 mix: tuple[int, int, int] = HLS_DEFAULT_MIX,
                 split: bool = False, bitrate: Any = None) -> None:
        self.mix = listener_mix(mix)
        self.split = bool(split)
        self.rates: tuple[int, ...] = tuple(HLS_VARIANT_RATES)
        # The single-rate face, for a caller that still thinks in one.
        self.bitrate = hls_snap_rate(
            bitrate if bitrate is not None else DEFAULT_RATE)
        name = "hlsabr-m%d-%d-%d" % self.mix + ("-split" if self.split else "")
        self.dir = root / name
        self.master = self.dir / "master.m3u8"
        self.playlist = self.variant_playlist(self.bitrate)
        self.proc: subprocess.Popen | None = None
        # Frames handed over at creation, written by the MIXER thread
        # before any live frame - never by a second writer.
        self.prime: list[bytes] = []
        self.primed_frames = 0
        self.fed_frames = 0
        self.asked_at = time.time()
        self.started_at = 0.0
        self.restarts = 0
        self.warm = False
        self.next_number = 0
        self.last_error = ""
        # Where a restart gets its cushion from: the stream's PCM backlog.
        # Set by StationStream; None in a bare test harness.
        self.backlog: Callable[[], list[bytes]] | None = None
        self.lock = threading.Lock()
        self._retry_at = 0.0
        self._handles: dict[int, _HlsVariant] = {}
        self._disk_at = 0.0
        self._disk: tuple[int, float] = (0, 0.0)

    # -- the folder tree ---------------------------------------------------
    def variant_dir(self, rate: Any) -> Path:
        return self.dir / str(hls_snap_rate(rate))

    def variant_playlist(self, rate: Any) -> Path:
        return self.variant_dir(rate) / "index.m3u8"

    def handle(self, rate: Any) -> _HlsVariant:
        r = hls_snap_rate(rate)
        h = self._handles.get(r)
        if h is None:
            h = self._handles[r] = _HlsVariant(self, r)
        return h

    @property
    def alive(self) -> bool:
        proc = self.proc
        return proc is not None and proc.poll() is None

    @property
    def label(self) -> str:
        return ("%d-%dk (%d/%d/%d)" % ((self.rates[0], self.rates[-1]) + self.mix)
                + (" split" if self.split else "")
                + (" warm" if self.warm else ""))

    def _highest_segment(self) -> int:
        """The last number on disk, so a restart continues the sequence."""
        top = -1
        try:
            for path in self.dir.glob("*/seg*.ts"):
                digits = "".join(ch for ch in path.stem if ch.isdigit())
                if digits:
                    top = max(top, int(digits))
        except OSError:
            pass
        return top

    def disk(self) -> tuple[int, float]:
        """(finished segments across the variants, newest mtime), cached
        for a second: state() may be polled by several panels at once and
        a glob per poll per panel is how a spool becomes a load."""
        now = time.time()
        if now - self._disk_at < 1.0:
            return self._disk
        count, newest = 0, 0.0
        try:
            for path in self.dir.glob("*/seg*.ts"):
                count += 1
                try:
                    newest = max(newest, path.stat().st_mtime)
                except OSError:
                    pass
        except OSError:
            pass
        self._disk = (count, newest)
        self._disk_at = now
        return self._disk

    def _sweep_below(self, number: int) -> None:
        """Delete segments numbered below `number`. After a restart the
        dead process's segments are nobody's to delete - the new ffmpeg
        only deletes its own - so each restart sweeps what is now older
        than two whole windows, and the folder stays bounded."""
        try:
            for path in self.dir.glob("*/seg*.ts"):
                digits = "".join(ch for ch in path.stem if ch.isdigit())
                if digits and int(digits) < number:
                    try:
                        path.unlink()
                    except OSError:
                        pass
        except OSError:
            pass

    def lost_frames(self) -> int | None:
        """How much audio a dead ffmpeg took with it: the frames since
        its newest FINISHED segment (the unfinished one, plus the pipe
        and the encoder's lookahead - half a second covers both). None
        when it never finished one, which means 'all of it'.

        This is what a restart re-primes with. Re-priming the whole
        thirty seconds would hand a listener who carries on across the
        seam half a minute they have already heard."""
        newest = 0.0
        try:
            for path in self.dir.glob("*/seg*.ts"):
                try:
                    newest = max(newest, path.stat().st_mtime)
                except OSError:
                    pass
        except OSError:
            return None
        if not newest:
            return None
        return int((max(0.0, time.time() - newest) + 0.5)
                   * 1000.0 / FRAME_MS) + 1

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> bool:
        now = time.time()
        if now < self._retry_at:
            return False
        restart = bool(self.started_at)
        try:
            # The sequence CONTINUES from what the folder held: a player
            # that sees the media sequence go backwards reads a broken
            # stream, one that sees it step forward carries on.
            top = self._highest_segment()
            self.next_number = max(self.next_number, top + 1)
            if restart and top >= 0:
                # A restart KEEPS the dead process's segments. A player
                # thirty seconds behind live has them listed and has not
                # fetched them all yet; deleting them turns one dead
                # ffmpeg into a 404 run and a hole in the car.
                self._sweep_below(self.next_number - 2 * HLS_LIST_SIZE)
            elif self.dir.exists():
                # A NEW lane starts fresh: a stale playlist from a
                # previous run names segments that belong to nobody.
                shutil.rmtree(self.dir, ignore_errors=True)
            for r in self.rates:
                self.variant_dir(r).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.last_error = f"spool: {exc}"
            self._retry_at = now + HLS_RESTART_BACKOFF_S
            return False
        cmd = hls_ffmpeg_argv(self.dir, self.rates, self.next_number,
                              discontinuity=restart and top >= 0)
        try:
            self.proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, bufsize=0)
        except Exception as exc:  # noqa: BLE001
            self.proc = None
            self.last_error = f"spawn: {exc}"
            self._retry_at = now + HLS_RESTART_BACKOFF_S
            return False
        # ffmpeg's last words, kept: a lane that dies with its stderr in
        # DEVNULL is a lane that dies for no reason anyone can read, and
        # a bad argv would otherwise be invisible for days.
        threading.Thread(target=self._last_words, args=(self.proc,),
                         name="hls-stderr", daemon=True).start()
        self.started_at = now
        self.fed_frames = 0
        return True

    def _last_words(self, proc: subprocess.Popen) -> None:
        err = proc.stderr
        if err is None:
            return
        tail: deque[str] = deque(maxlen=3)
        try:
            for raw in iter(err.readline, b""):
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    tail.append(line[:200])
        except Exception:  # noqa: BLE001
            pass
        if tail:
            self.last_error = " | ".join(tail)

    def feed(self, frame: bytes) -> bool:
        """One live frame, preceded by the prime if one is waiting.

        Called by the MIXER thread only. The prime is written here,
        under the lane lock and before the frame, so the lane's timeline
        is always backlog-then-live: a prime written after even one live
        frame puts 100 ms of the present in front of 30 s of the past,
        which a listener hears as a skip. A dead ffmpeg is restarted here
        and re-primed from `backlog()` for the same reason - a lane that
        comes back without its cushion is the 12-second cold start this
        batch (#1473) exists to remove."""
        with self.lock:
            proc = self.proc
            if proc is None or proc.poll() is not None or proc.stdin is None:
                self.stop()
                if time.time() < self._retry_at:
                    return False
                was_started = bool(self.started_at)
                # Measured BEFORE start(), which may sweep the folder.
                lost = self.lost_frames() if was_started else None
                if not self.start():
                    return False
                if was_started:
                    self.restarts += 1
                backlog = self.backlog() if self.backlog else []
                if lost is not None:
                    backlog = backlog[-lost:] if lost > 0 else []
                self.prime = backlog
                self.primed_frames = len(backlog)
                proc = self.proc
            try:
                if proc is not None and proc.stdin is not None:
                    if self.prime:
                        backlog, self.prime = self.prime, []
                        proc.stdin.write(b"".join(backlog))
                    proc.stdin.write(frame)
                    self.fed_frames += 1
                return True
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"write: {exc}"
                self._retry_at = time.time() + HLS_RESTART_BACKOFF_S
                self.stop()
                return False

    def ready(self, minimum_segments: int = 1, rate: Any = None) -> bool:
        """The master and, for the asked rate (or every rate), a playlist
        and at least `minimum_segments` FINISHED segments. temp_file in
        the argv is what makes the glob mean finished."""
        needed = max(1, int(minimum_segments))
        try:
            if not self.master.is_file():
                return False
            rates = (hls_snap_rate(rate),) if rate is not None else self.rates
            for r in rates:
                pl = self.variant_playlist(r)
                if not pl.is_file() or pl.stat().st_size <= 0:
                    return False
                if sum(1 for _ in self.variant_dir(r).glob("seg*.ts")) < needed:
                    return False
            return True
        except OSError:
            return False

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _median(values: Any) -> float:
    seq = list(values)
    return round(statistics.median(seq), 1) if seq else 0.0


class _HlsLedger:
    """Who is on the HLS road, from the requests app.py serves (#1473).

    An mp3 listener is a socket, so the stream can see them. An HLS
    listener is a series of small GETs with a token in each, so until
    now `state()` said 0 listeners while a car was plainly on air. app.py
    calls `note()` after every playlist or segment it serves; this keeps
    one row per token (by its last twelve characters - never the token)
    and a ring of the last 200 requests, and writes one JSON line per
    request to data/hls_ledger.jsonl.

    THE CALLER NEVER WAITS ON DISK: note() is a dict update and a
    queue put, both under a microsecond; one daemon thread drains the
    queue to the file and rotates it at 5 MB (one .1 kept).
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self.tokens: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.q: "queue.Queue[dict[str, Any]]" = queue.Queue(
            maxsize=HLS_LEDGER_QUEUE)
        self.dropped = 0
        self.written = 0
        self.last_write_error = ""
        self._thread: threading.Thread | None = None
        self._swept = 0.0

    @property
    def path(self) -> Path:
        if self._path is None:
            self._path = _hls_ledger_path()
        return self._path

    def note(self, token: str, kind: str, rate: int, name: str, nbytes: int,
             served_ms: float, addr: str, xff: str,
             **extra: Any) -> dict[str, Any]:
        now = time.time()
        tail = str(token or "")[-12:] or "-"
        kind = str(kind or "segment")
        client = _client_ip(addr, xff)
        road = hls_road(addr, xff)
        stall = dropout = False
        with self.lock:
            row = self.tokens.get(tail)
            if row is None:
                row = self.tokens[tail] = {
                    "first": now, "last": now, "addr": client, "road": road,
                    "rate": int(rate or 0), "segments": 0, "bytes": 0,
                    "stalls": 0, "dropouts": 0, "worst_gap_s": 0.0,
                    "last_segment_at": 0.0, "quiet_max": 0.0,
                    "kinds": {"master": 0, "playlist": 0, "segment": 0},
                    "served_ms": deque(maxlen=50),
                    "playlist_ms": deque(maxlen=50),
                    "ring": deque(maxlen=200),
                }
            # The longest silence (no request of any kind) since the last
            # segment: what tells a stall from a dropout below.
            row["quiet_max"] = max(row["quiet_max"], now - row["last"])
            row["last"] = now
            row["addr"] = client
            row["road"] = road
            row["rate"] = int(rate or row["rate"])
            row["bytes"] += int(nbytes or 0)
            row["kinds"][kind] = row["kinds"].get(kind, 0) + 1
            if kind == "segment":
                prev = row["last_segment_at"]
                if prev:
                    gap = now - prev
                    if gap > HLS_STALL_GAP_S:
                        if row["quiet_max"] < HLS_ACTIVE_S:
                            row["stalls"] += 1
                            stall = True
                        else:
                            row["dropouts"] += 1
                            dropout = True
                    row["worst_gap_s"] = max(row["worst_gap_s"], gap)
                row["last_segment_at"] = now
                row["quiet_max"] = 0.0
                row["segments"] += 1
                row["served_ms"].append(float(served_ms or 0))
            else:
                row["playlist_ms"].append(float(served_ms or 0))
            line: dict[str, Any] = {
                "ts": round(now, 3), "tail": tail, "kind": kind,
                "rate": int(rate or 0), "name": str(name or "")[:64],
                "bytes": int(nbytes or 0), "ms": round(float(served_ms or 0), 1),
                "addr": client, "road": road,
            }
            if stall:
                line["stall"] = True
            if dropout:
                line["dropout"] = True
            if extra:
                line.update(extra)
            row["ring"].append(line)
            if now - self._swept > 60.0:
                self._swept = now
                self._retire(now)
        try:
            self.q.put_nowait(line)
        except queue.Full:
            self.dropped += 1
        self._ensure_thread()
        return line

    def _retire(self, now: float) -> None:
        """Under the lock. A token idle for an hour is not a listener."""
        for tail in [t for t, r in self.tokens.items()
                     if now - r["last"] > HLS_TOKEN_IDLE_S]:
            self.tokens.pop(tail, None)

    def rows(self) -> list[dict[str, Any]]:
        now = time.time()
        out: list[dict[str, Any]] = []
        with self.lock:
            self._retire(now)
            for tail, r in self.tokens.items():
                out.append({
                    "token_tail": tail, "addr": r["addr"], "road": r["road"],
                    "since": round(r["first"], 1), "last": round(r["last"], 1),
                    "idle_s": round(now - r["last"], 1),
                    "rate": r["rate"], "segments": r["segments"],
                    "playlists": r["kinds"].get("playlist", 0)
                    + r["kinds"].get("master", 0),
                    "bytes": r["bytes"],
                    "served_ms_med": _median(r["served_ms"]),
                    "playlist_ms_med": _median(r["playlist_ms"]),
                    "stalls": r["stalls"], "dropouts": r["dropouts"],
                    "worst_gap_s": round(r["worst_gap_s"], 1),
                    "active": (now - r["last"]) < HLS_ACTIVE_S,
                })
        out.sort(key=lambda x: -x["last"])
        return out

    def ledger(self, token_tail: str, limit: int = 200) -> list[dict[str, Any]]:
        tail = str(token_tail or "")[-12:]
        with self.lock:
            row = self.tokens.get(tail)
            rows = list(row["ring"]) if row else []
        n = max(1, int(limit or 200))
        return rows[-n:]

    def status(self) -> dict[str, Any]:
        return {"path": str(self.path), "queued": self.q.qsize(),
                "written": self.written, "dropped": self.dropped,
                "tokens": len(self.tokens),
                "error": self.last_write_error}

    def _ensure_thread(self) -> None:
        th = self._thread
        if th is not None and th.is_alive():
            return
        with self.lock:
            th = self._thread
            if th is not None and th.is_alive():
                return
            self._thread = threading.Thread(
                target=self._drain, name="hls-ledger", daemon=True)
            self._thread.start()

    def _drain(self) -> None:
        while True:
            batch = [self.q.get()]
            try:
                while len(batch) < 200:
                    batch.append(self.q.get_nowait())
            except queue.Empty:
                pass
            try:
                path = self.path
                path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    if path.stat().st_size > HLS_LEDGER_ROTATE_BYTES:
                        path.replace(path.with_name(path.name + ".1"))
                except FileNotFoundError:
                    pass
                with path.open("a", encoding="utf-8") as fh:
                    for line in batch:
                        fh.write(json.dumps(line, separators=(",", ":")) + "\n")
                self.written += len(batch)
            except Exception as exc:  # noqa: BLE001
                self.last_write_error = str(exc)[:160]


class StationStream:
    """The mixer, the encoder and the fan-out, behind one URL.

    `snapshot()` is supplied by the host and must return, cheaply and
    without raising:

        {"on": bool, "paused": bool,
         "music": {"id": str, "path": str, "started": float,
                   "title": str, "artist": str} | None,
         "clips": [{"key": str, "air_at": float, "path": str,
                    "length": float}, ...]}

    Everything app-specific - signing, hot-file resolution, which clips
    belong to this schedule - stays on the host side of that call. This
    class only ever reads.
    """

    def __init__(self, snapshot: Callable[[], dict[str, Any]],
                 bitrate: int = 128) -> None:
        self._snapshot = snapshot
        self.bitrate = int(bitrate)

        self._lock = threading.Lock()
        self._encoders: dict[tuple[int, bool], _Encoder] = {}
        # #1473: HLS lanes are keyed by (split, mix), one ABR lane each,
        # every rate inside. The default lane is (False, HLS_DEFAULT_MIX).
        self._hls: dict[tuple[bool, tuple[int, int, int]], _HlsEncoder] = {}
        self._hls_root = Path(HLS_ROOT) if HLS_ROOT else Path(
            tempfile.mkdtemp(prefix="pinebox-hls-"))
        self._ledger = _HlsLedger()
        self._next_id = 1

        self._run = False
        self._thread: threading.Thread | None = None
        self._last_listener_at = 0.0

        # The last JOIN_BURST_SECONDS of the mix, as PCM. Rate-independent,
        # so ONE copy primes an encoder at any bitrate. At 44.1k stereo
        # this is about 5 MB for thirty seconds.
        # #1253: the last few sessions, so a RECONNECT LOOP is visible.
        # A car that reconnects every twenty seconds and one that holds a
        # single socket for an hour look identical in a live snapshot and
        # completely different here.
        self.sessions: deque = deque(maxlen=40)

        self._pcm_burst: deque[bytes] = deque(
            maxlen=max(1, int(JOIN_BURST_SECONDS * 1000 / FRAME_MS)))

        # What is on, for ICY metadata and /api/stream/state.
        self.now_title = ""
        self.now_artist = ""
        self._meta_seq = 0

        self.stats: dict[str, Any] = {
            "frames": 0, "started_at": 0.0, "music_id": "",
            "voice_airing": "", "clips_aired": 0, "underruns": 0,
            "encoder_restarts": 0, "last_error": "",
            "reanchors": 0, "behind_worst": 0.0, "primed": 0,
            "starve_waits": 0, "starve_wait_ms": 0, "holes": 0,
            "swaps": 0,
            "padded_music": 0, "padded_voice": 0,
        }
        self._aired: "deque[str]" = deque(maxlen=512)
        self._aired_set: set[str] = set()

    # -- listeners ---------------------------------------------------------
    @property
    def listeners(self) -> int:
        with self._lock:
            return sum(len(e.sinks) for e in self._encoders.values())

    def rates(self) -> dict[int, int]:
        with self._lock:
            return {f"{r}k": len(e.sinks)
                    for (r, sp), e in self._encoders.items()}

    def listener_rows(self) -> list[dict[str, Any]]:
        """What each listener is ACTUALLY receiving.

        `delivered_x` is the number that matters: 1.0 means this socket
        is keeping up with real time. Below 1.0 for any length of time
        and that listener is draining their buffer toward a stutter,
        whatever the mixer thinks it is producing."""
        with self._lock:
            sinks = [sk for e in self._encoders.values()
                     for sk in e.sinks.values()]
        return [sk.row() for sk in sinks]

    def attach(self, bitrate: Any = None, split: bool = False) -> "_Sink":
        """A listener at one quality on the centred stereo programme."""
        rate = snap_rate(bitrate if bitrate is not None else self.bitrate)
        key = (rate, False)
        sink = _Sink(rate, False)
        # Bind first: offer() is a no-op until the sink knows which loop
        # to hand chunks to, and the burst is offered a few lines below.
        try:
            sink.bind(asyncio.get_running_loop())
        except RuntimeError:
            pass                    # not on a loop - a test harness

        with self._lock:
            enc = self._encoders.get(key)
            if enc is None:
                enc = _Encoder(rate, False)
                if not enc.start():
                    self.stats["last_error"] = f"encoder {rate}k would not start"
                # The burst this rate has never had. The mixer writes it
                # on its next turn, ahead of any live frame, so the
                # listener attached below receives a full read-ahead
                # instead of the nothing a cold encoder would give them.
                enc.prime = list(self._pcm_burst)
                self._encoders[key] = enc
            sink.ident = self._next_id
            self._next_id += 1
            with enc.lock:
                enc.sinks[sink.ident] = sink
                enc.idle_since = 0.0
                primed = list(enc.burst)
            self._last_listener_at = time.time()
        # Prime OUTSIDE the lock: thirty seconds of mp3 is half a megabyte
        # and the mixer must not wait behind it.
        for chunk in primed:
            sink.offer(chunk)
        self.ensure_running()
        return sink

    # -- HLS: the ABR lanes (#1473) ----------------------------------------
    @staticmethod
    def _hls_key(split: Any, mix: Any) -> tuple[bool, tuple[int, int, int]]:
        return (bool(split), listener_mix(mix))

    def _burst_copy(self) -> list[bytes]:
        """The PCM backlog, copied. The mixer appends without our lock;
        CPython will not switch threads inside list(), but a RuntimeError
        on a mutated deque is cheaper to retry than to reason about."""
        try:
            return list(self._pcm_burst)
        except RuntimeError:
            return list(self._pcm_burst)

    def hls_lane(self, split: bool = False, mix: Any = None,
                 bitrate: Any = None) -> "_HlsEncoder":
        """The ABR lane for this (split, mix): started and PRIMED if new,
        restarted and re-primed if its ffmpeg has died.

        Unlike an mp3 listener there is no socket to hold: a player just
        keeps asking for the playlist. `asked_at` is that heartbeat, and
        the mixer reaps a lane nobody has asked about - unless it is warm.

        #1473 THE PRIME: a new lane is handed the same thirty seconds of
        PCM the mp3 road hands a new encoder (`_pcm_burst`, banked by the
        mixer only while real programme was airing). The mixer writes it
        before the first live frame, ffmpeg cuts it into segments at
        several hundred times real time, and the lane holds half a
        minute of playlist within a second or two - so a player can begin
        thirty seconds behind live with a full cushion instead of waiting
        12-13 s for three segments to exist. The backlog is the DEFAULT
        programme mix: a personal-mix or split lane hears its own balance
        from the first live frame, not through the primed half-minute,
        which is the price of starting at once rather than in silence.
        """
        key = self._hls_key(split, mix)
        now = time.time()
        with self._lock:
            lane = self._hls.get(key)
            if lane is None:
                lane = _HlsEncoder(self._hls_root, key[1], key[0], bitrate)
                lane.backlog = self._burst_copy
                # Started here so the first playlist poll finds a folder;
                # primed here, under the stream lock, so the mixer cannot
                # see this lane before its prime is in place (it takes
                # the lane list under the same lock). A DEAD lane is not
                # restarted here: the mixer's feed() does that within a
                # frame and re-primes it in the right order, and a
                # restart racing it from the event loop could not.
                if lane.start():
                    lane.prime = self._burst_copy()
                    lane.primed_frames = len(lane.prime)
                else:
                    self.stats["last_error"] = (
                        f"hls lane {lane.dir.name} would not start: "
                        f"{lane.last_error or 'no reason given'}")
                self._hls[key] = lane
            lane.asked_at = now
            self._last_listener_at = now
        # A warm lane's mixer may have exited (an exception, or stop());
        # this is what brings it back, and with it a dead lane's restart.
        self.ensure_running()
        return lane

    def hls(self, bitrate: Any = None, mix: Any = None,
            split: bool = False) -> "_HlsVariant":
        """The single-rate face of the lane at this rate: the object the
        old route reads `.playlist` and `.dir` from and calls `.ready()`
        on. A rate outside the four variants rounds to the nearest."""
        lane = self.hls_lane(split, mix, bitrate)
        return lane.handle(bitrate if bitrate is not None else self.bitrate)

    def hls_existing(self, bitrate: Any, mix: Any = None,
                     split: bool = False) -> "_HlsVariant | None":
        """The variant at this rate if its lane already exists.

        Segment requests must never be able to SPAWN a lane: a player
        asking for a segment of a stream nobody is listening to is a
        stale playlist, and answering it by starting an encoder is how
        one abandoned tab keeps the box busy for ever."""
        with self._lock:
            lane = self._hls.get(self._hls_key(split, mix))
            if lane is None:
                return None
            lane.asked_at = time.time()
        return lane.handle(bitrate)

    def _hls_lane_if_running(self, split: bool,
                             mix: Any) -> "_HlsEncoder | None":
        with self._lock:
            lane = self._hls.get(self._hls_key(split, mix))
            if lane is None or not lane.alive:
                return None
            lane.asked_at = time.time()
            return lane

    def hls_master(self, split: bool = False, mix: Any = None) -> Path | None:
        """The master playlist of the RUNNING lane, else None. Its URIs
        are relative (`48/index.m3u8`); app.py rewrites them with the
        token. It does not start a lane - hls()/hls_lane() do that."""
        lane = self._hls_lane_if_running(split, mix)
        if lane is None:
            return None
        return lane.master if lane.master.is_file() else None

    def hls_variant_playlist(self, rate: Any, split: bool = False,
                             mix: Any = None) -> Path | None:
        lane = self._hls_lane_if_running(split, mix)
        if lane is None:
            return None
        path = lane.variant_playlist(rate)
        return path if path.is_file() else None

    @staticmethod
    def hls_rates() -> list[int]:
        return list(HLS_VARIANT_RATES)

    def hls_start_offset_s(self, split: bool = False, mix: Any = None) -> float:
        """How far behind the live edge a joining player should start.

        JOIN_BURST_SECONDS (30) once the backlog was banked and primed;
        before that, what was actually primed plus what the lane has
        encoded since, so a player is never pointed at audio that does
        not exist. A lane that is not running reports what one started
        now would be primed with. Capped inside the playlist window; a
        player clamps to the playlist head if a segment is still being
        cut, which is the right thing for it to do."""
        with self._lock:
            lane = self._hls.get(self._hls_key(split, mix))
            if lane is not None and lane.alive:
                have = (lane.primed_frames + lane.fed_frames) * FRAME_MS / 1000.0
            else:
                have = len(self._pcm_burst) * FRAME_MS / 1000.0
        window = max(HLS_SEGMENT_SECONDS,
                     (HLS_LIST_SIZE - 2) * HLS_SEGMENT_SECONDS)
        return round(max(0.0, min(JOIN_BURST_SECONDS, have, window)), 1)

    def hls_keep_warm(self) -> dict[str, Any]:
        """Start the default lane if it is not running and keep it.

        A warm lane is exempt from the reaper and pins the mixer past its
        linger, so a car that tunes in at 03:00 finds a playlist with a
        thirty-second cushion rather than a cold ffmpeg. Safe to call
        every minute: a live lane costs one poll() and two timestamps.
        A lane whose ffmpeg has died is restarted and re-primed here
        (and, sooner, by the mixer's next frame)."""
        lane = self.hls_lane(False, None, None)
        with self._lock:
            lane.warm = True
        return self.hls_state()

    def _any_warm(self) -> bool:
        with self._lock:
            return any(lane.warm for lane in self._hls.values())

    def hls_note(self, token: str, kind: str, rate: int, name: str,
                 nbytes: int, served_ms: float, addr: str, xff: str,
                 **extra: Any) -> None:
        """app.py calls this after every playlist or segment it serves.
        Never blocks; see _HlsLedger."""
        try:
            self._ledger.note(token, kind, rate, name, nbytes, served_ms,
                              addr, xff, **extra)
        except Exception as exc:  # noqa: BLE001
            self.stats["last_error"] = f"hls_note: {exc}"

    def hls_ledger(self, token_tail: str,
                   limit: int = 200) -> list[dict[str, Any]]:
        return self._ledger.ledger(token_tail, limit)

    def hls_listeners(self) -> list[dict[str, Any]]:
        return self._ledger.rows()

    def hls_state(self) -> dict[str, Any]:
        """The `hls` block of state(): what the car diagnostics read."""
        with self._lock:
            lanes = list(self._hls.items())
        default = next((lane for key, lane in lanes
                        if key == (False, HLS_DEFAULT_MIX)), None)
        segs, newest = default.disk() if default is not None else (0, 0.0)
        now = time.time()
        return {
            "running": bool(default is not None and default.alive),
            "warm": bool(default is not None and default.warm
                         and default.alive),
            "warm_wanted": bool(default is not None and default.warm),
            "variants": list(HLS_VARIANT_RATES),
            "lane_dir": str(default.dir) if default is not None else "",
            "segments_on_disk": segs,
            "start_offset_s": self.hls_start_offset_s(),
            "primed_s": (round(default.primed_frames * FRAME_MS / 1000.0, 1)
                         if default is not None else 0.0),
            "last_segment_at": round(newest, 3),
            "last_segment_ago_s": round(now - newest, 1) if newest else None,
            "restarts": sum(lane.restarts for _, lane in lanes),
            "segment_s": HLS_SEGMENT_SECONDS,
            "list_size": HLS_LIST_SIZE,
            "lanes": [{"lane": lane.label, "dir": lane.dir.name,
                       "alive": lane.alive, "warm": lane.warm,
                       "restarts": lane.restarts,
                       "primed_s": round(
                           lane.primed_frames * FRAME_MS / 1000.0, 1),
                       "asked_ago_s": round(now - lane.asked_at, 1),
                       "error": lane.last_error}
                      for _, lane in lanes],
            "ledger": self._ledger.status(),
        }

    def detach(self, sink: "_Sink") -> None:
        try:
            row = sink.row()
            row["ended"] = time.strftime("%H:%M:%S")
            self.sessions.append(row)
        except Exception:  # noqa: BLE001
            pass
        with self._lock:
            enc = self._encoders.get((getattr(sink, "bitrate", 0),
                                      bool(getattr(sink, "split", False))))
            if enc is not None:
                with enc.lock:
                    enc.sinks.pop(getattr(sink, "ident", -1), None)
                    if not enc.sinks:
                        enc.idle_since = time.time()
            self._last_listener_at = time.time()
        sink.close()

    # -- the engine --------------------------------------------------------
    def ensure_running(self) -> None:
        with self._lock:
            if self._run and self._thread and self._thread.is_alive():
                return
            self._run = True
            self._thread = threading.Thread(target=self._serve,
                                            name="station-mixer", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._run = False

    # -- the mix -----------------------------------------------------------
    def _serve(self) -> None:
        music: _Decoder | None = None
        music_id = ""
        pending: list[_Voice] = []
        airing: _Voice | None = None
        duck = 0.0                      # 0 = bed up, 1 = fully ducked
        duck_step = FRAME_MS / max(1.0, DUCK_RAMP_MS)

        self.stats["started_at"] = time.time()
        next_tick = time.monotonic()
        poll_at = 0.0
        state: dict[str, Any] = {}

        try:
            while self._run:
                now = time.time()

                # Nobody on, and the linger is spent: shut the box down.
                # #1473: unless a lane is WARM - a warm lane with no
                # mixer feeding it is a playlist going stale, and the
                # whole point of keeping it is a joiner at 03:00.
                if (not self.listeners
                        and now - self._last_listener_at > LINGER_SECONDS
                        and self._last_listener_at
                        and not self._any_warm()):
                    break

                # An encoder nobody is listening at is a lame process for
                # nothing. It keeps its burst ring for the linger so that
                # coming back at the same quality is still instant.
                with self._lock:
                    for ekey, enc in list(self._encoders.items()):
                        if (enc.idle_since
                                and now - enc.idle_since > LINGER_SECONDS):
                            enc.stop()
                            self._encoders.pop(ekey, None)
                    for hkey, hls in list(self._hls.items()):
                        # A warm lane is kept by policy, not by a player.
                        if hls.warm:
                            continue
                        if now - hls.asked_at > LINGER_SECONDS:
                            hls.stop()
                            self._hls.pop(hkey, None)

                # Station state, four times a second. Cheap on the host
                # side by contract, and never on the event loop.
                if now >= poll_at:
                    poll_at = now + 0.25
                    try:
                        state = self._snapshot() or {}
                    except Exception as exc:  # noqa: BLE001
                        self.stats["last_error"] = f"snapshot: {exc}"
                        state = {}

                    track = state.get("music") or {}
                    tid = str(track.get("id") or "")
                    self.now_title = str(track.get("title") or "")
                    self.now_artist = str(track.get("artist") or "")
                    # #1253: DOUBLE-BUFFERED SWAP.
                    #
                    # This used to close the playing decoder BEFORE
                    # building its replacement, so every record change
                    # aired the gap between them. And an empty `tid` -
                    # the station mid-turnover, a blip in _RADIO - tore
                    # down a working decoder to replace it with nothing,
                    # which is a far longer hole for no reason at all.
                    #
                    # So: an empty tid means "not said yet", and keeps
                    # what is playing. A real change builds the new
                    # decoder, waits for it to genuinely have audio, and
                    # only then retires the old one.
                    if not tid:
                        pass                    # keep the current record
                    elif tid != music_id:
                        path = str(track.get("path") or "")
                        cand = None
                        if path:
                            offset = max(0.0, now - float(
                                track.get("started") or now))
                            cand = _Decoder(path, offset)
                            if cand.start():
                                # Give it a moment to fill. It reads off
                                # the local shelf, where first frame was
                                # measured at 21-41 ms.
                                _spin = 0.0
                                while (_spin < 0.5 and not cand.has_frame()
                                       and not cand.finished):
                                    time.sleep(0.005)
                                    _spin += 0.005
                            else:
                                self.stats["last_error"] = (
                                    f"record would not open: {path}")
                                cand = None
                        if cand is not None:
                            if music is not None:
                                music.close()
                            music = cand
                            music_id = tid
                            self.stats["music_id"] = music_id
                            self.stats["swaps"] = int(
                                self.stats.get("swaps") or 0) + 1
                            self._meta_seq += 1
                        # A replacement that would not open leaves the
                        # current record playing rather than cutting to
                        # silence; the next poll tries again.

                    # New clips: take them at announce time, which is the
                    # whole point of the seven-second lead - the decode
                    # happens while the line is still in the future.
                    for row in (state.get("clips") or []):
                        key = str(row.get("key") or "")
                        if not key or key in self._aired_set:
                            continue
                        if any(v.key == key for v in pending):
                            continue
                        air_at = float(row.get("air_at") or 0)
                        if not air_at:
                            continue
                        if now - air_at > CLIP_GRACE_SECONDS:
                            continue        # genuinely historical
                        path = str(row.get("path") or "")
                        if not path or not Path(path).is_file():
                            continue
                        voice = _Voice(key, air_at, path,
                                       float(row.get("length") or 0),
                                       bool(row.get("sfx")))
                        # Decode AHEAD of the air moment, not at it.
                        voice.decoder = _Decoder(path)
                        voice.decoder.start()
                        pending.append(voice)
                    pending.sort(key=lambda v: v.air_at)

                paused = bool(state.get("paused"))
                on_air = bool(state.get("on", True)) and not paused
                # #1253: DO NOT OUTRUN THE DECODERS.
                #
                # Catch-up after a stall is only free when the audio is
                # already in RAM. When it is not - because the pump
                # thread is fighting the same GIL that caused the stall -
                # racing ahead turns one stall into a burst of zero-
                # padded frames, which is a hole in the broadcast. Wait
                # for the bytes instead. Being a few milliseconds later
                # is what the burst is for; a hole is not recoverable.
                if on_air:
                    _waited = 0.0
                    while _waited < STARVE_WAIT_MAX:
                        _short = False
                        if (music is not None and not music.finished
                                and not music.has_frame()):
                            _short = True
                        _vd = airing.decoder if airing is not None else None
                        if (_vd is not None and not _vd.finished
                                and not _vd.has_frame()):
                            _short = True
                        if not _short:
                            break
                        time.sleep(0.004)
                        _waited += 0.004
                    if _waited:
                        self.stats["starve_waits"] += 1
                        self.stats["starve_wait_ms"] += int(_waited * 1000)
                        if _waited >= STARVE_WAIT_MAX:
                            self.stats["holes"] += 1

                # -- pick the voice for this frame -------------------------
                if airing is not None and airing.decoder is not None:
                    if airing.decoder.finished:
                        airing.decoder.close()
                        airing = None
                if airing is None and on_air and pending:
                    head = pending[0]
                    if now >= head.air_at:
                        pending.pop(0)
                        airing = head
                        airing.started = True
                        self._remember(head.key)
                        self.stats["clips_aired"] += 1
                        self.stats["voice_airing"] = head.key
                        self._meta_seq += 1

                # Drop anything that went stale while it waited.
                if pending:
                    pending = [v for v in pending
                               if now - v.air_at <= CLIP_GRACE_SECONDS
                               or not self._forget(v)]

                # -- assemble ----------------------------------------------
                made_sound = False
                # #1473: what a split lane needs to re-mix this frame.
                bed = None
                voice_pcm = None
                if not on_air:
                    # Off air, or paused: the socket is HELD OPEN and fed
                    # silence. Persistence is the point - a car must not
                    # have to re-tune because the booth took a break.
                    frame = SILENCE
                    if airing is not None:
                        airing.decoder and airing.decoder.close()
                        airing = None
                    duck = 0.0
                else:
                    voice_pcm = None
                    if airing is not None and airing.decoder is not None:
                        raw, live = airing.decoder.read_frame()
                        if live:
                            voice_pcm = _centered_pcm(raw)
                        else:
                            airing.decoder.close()
                            airing = None

                    target = 1.0 if voice_pcm is not None else 0.0
                    if duck < target:
                        duck = min(target, duck + duck_step)
                    elif duck > target:
                        duck = max(target, duck - duck_step)

                    bed_gain = MUSIC_LEVEL + (MUSIC_DUCK - MUSIC_LEVEL) * duck
                    if music is not None:
                        raw, live = music.read_frame()
                        if not live and music.finished:
                            # The record ran out before the station said
                            # so. Hold silence rather than loop it; the
                            # next snapshot brings the next track.
                            music.close()
                            music, music_id = None, ""
                            bed = np.zeros(FRAME_SAMPLES * CHANNELS,
                                           dtype=np.int32)
                        else:
                            if not live:
                                self.stats["underruns"] += 1
                            self.stats["padded_music"] = music.padded
                            bed = _centered_pcm(raw)
                    else:
                        bed = np.zeros(FRAME_SAMPLES * CHANNELS,
                                       dtype=np.int32)

                    made_sound = (music is not None) or (voice_pcm is not None)
                    # Preserve the existing ducking curve, then apply the
                    # listener's own controls to the centred stereo buses.
                    bed = bed * (bed_gain / max(MUSIC_LEVEL, 0.0001))
                    frame = _mixed_program(bed, voice_pcm,
                                           bool(airing is not None and airing.sfx))

                # -- hand it to every encoder ------------------------------
                # One mix, several rates. A listener on 48k and one on
                # 128k share this frame and everything that made it.
                # #1253: BANK ONLY REAL PROGRAMME. The backlog is what a
                # joining listener is handed as their read-ahead, and the
                # mixer is kept warm from boot - so without this test the
                # first half-minute after a restart banks pure silence and
                # the next person to tune in is handed thirty seconds of
                # nothing, which reads as broken. Off air, or on air with
                # no record open yet, simply does not go in the bank.
                if made_sound:
                    self._pcm_burst.append(frame)
                with self._lock:
                    encoders = list(self._encoders.values())
                    hlses = list(self._hls.values())
                if not encoders:
                    # Nobody yet, but the linger has not run out. Keep the
                    # mixer turning so the first listener starts instantly.
                    pass
                for enc in encoders:
                    before = enc.restarts
                    shaped = frame
                    if enc.prime:
                        backlog, enc.prime = enc.prime, []
                        for past in backlog:
                            if not enc.feed(past):
                                break
                        self.stats["primed"] += 1
                    if not enc.feed(shaped):
                        self.stats["last_error"] = (
                            f"encoder {enc.bitrate}k stopped")
                    if enc.restarts != before:
                        self.stats["encoder_restarts"] += 1
                is_sfx = bool(airing is not None and airing.sfx)
                for hls in hlses:
                    if not on_air or bed is None:
                        hshaped = frame
                    elif hls.split:
                        hshaped = _split_program(bed, voice_pcm, is_sfx,
                                                 hls.mix)
                    elif hls.mix == HLS_DEFAULT_MIX:
                        hshaped = frame
                    else:
                        hshaped = _mixed_program(bed, voice_pcm, is_sfx,
                                                 hls.mix)
                    # #1473: feed() writes any waiting prime FIRST, and
                    # restarts + re-primes a dead ffmpeg itself.
                    if not hls.feed(hshaped):
                        self.stats["last_error"] = (
                            f"hls lane {hls.dir.name} stopped: "
                            f"{hls.last_error or 'no reason given'}")

                self.stats["frames"] += 1

                # -- real time, by construction ----------------------------
                next_tick += FRAME_MS / 1000.0
                slack = next_tick - time.monotonic()
                if slack > 0:
                    time.sleep(slack)
                elif slack < -CATCHUP_LIMIT:
                    # Past a minute behind, something has genuinely gone
                    # wrong and a minute-long burst of catch-up helps
                    # nobody. Re-anchor and take the loss.
                    self.stats["reanchors"] += 1
                    self.stats["behind_worst"] = max(
                        float(self.stats.get("behind_worst") or 0), -slack)
                    next_tick = time.monotonic()
                else:
                    # BEHIND, BUT CATCHING UP. No sleep, so the loop runs
                    # flat out until it is level again. This is what keeps
                    # the AVERAGE at exactly real time across a stall, and
                    # a listener consuming at 1x needs the average, not
                    # the instant. The frames cost almost nothing: the
                    # record is already decoded ahead in RAM and lame runs
                    # at several hundred times real time.
                    self.stats["behind_worst"] = max(
                        float(self.stats.get("behind_worst") or 0), -slack)
        except Exception as exc:  # noqa: BLE001
            self.stats["last_error"] = f"mixer: {exc}"
        finally:
            self._run = False
            if music is not None:
                music.close()
            if airing is not None and airing.decoder is not None:
                airing.decoder.close()
            for voice in pending:
                if voice.decoder is not None:
                    voice.decoder.close()
            with self._lock:
                for enc in self._encoders.values():
                    enc.stop()
                self._encoders.clear()
                # #1473: a WARM lane outlives this mixer. Its ffmpeg is
                # left running (it just sees no input until the next
                # mixer starts), and hls_keep_warm() restarts the mixer
                # through hls_lane(). Everything else goes, as before.
                for hkey, hls in list(self._hls.items()):
                    if hls.warm:
                        continue
                    hls.stop()
                    self._hls.pop(hkey, None)

    def _remember(self, key: str) -> None:
        if len(self._aired) == self._aired.maxlen and self._aired:
            self._aired_set.discard(self._aired[0])
        self._aired.append(key)
        self._aired_set.add(key)

    def _forget(self, voice: _Voice) -> bool:
        if voice.decoder is not None:
            voice.decoder.close()
        self._remember(voice.key)
        return True

    # -- what a car's display shows ---------------------------------------
    def icy_title(self) -> str:
        if self.now_artist and self.now_title:
            return f"{self.now_artist} - {self.now_title}"
        return self.now_title or "Pine Box FM"

    def state(self) -> dict[str, Any]:
        up = (time.time() - float(self.stats.get("started_at") or 0)
              if self.stats.get("started_at") else 0.0)
        mp3_listeners = self.listeners
        hls_rows = self.hls_listeners()
        hls_active = sum(1 for row in hls_rows if row["active"])
        with self._lock:
            lanes = list(self._hls.values())
        return {
            "running": bool(self._run),
            # #1473: this used to count mp3 sockets only, so it read 0
            # while a car was plainly listening over HLS. It is now both
            # roads; the two parts are alongside it.
            "listeners": mp3_listeners + hls_active,
            "mp3_listeners": mp3_listeners,
            "hls_active": hls_active,
            "bitrate": self.bitrate,
            "rates": self.rates(),
            "hls_rates": [lane.label for lane in lanes],
            "hls": self.hls_state(),
            "hls_listeners": hls_rows,
            "listener_rows": self.listener_rows(),
            "recent_sessions": list(self.sessions)[-12:],
            "join_burst_s": JOIN_BURST_SECONDS,
            "title": self.now_title,
            "artist": self.now_artist,
            "up_seconds": round(up, 1),
            "produced_seconds": round(
                float(self.stats.get("frames") or 0) * FRAME_MS / 1000.0, 1),
            **{k: v for k, v in self.stats.items() if k != "frames"},
        }


class _Sink:
    """One listener socket, fed by the event loop rather than by a pool.

    THE POINT OF THIS CLASS IS WHAT IT DOES NOT DO. It does not park a
    thread. The encoder thread calls offer() and returns immediately;
    the chunk is handed to the event loop, and the route awaits a plain
    asyncio.Queue. Nothing here touches the default ThreadPoolExecutor,
    which app.py shares across 407 to_thread call sites - the pool whose
    saturation used to stop delivery dead while the loop itself was fine.

    A listener that cannot keep up is dropped back toward the live edge
    rather than allowed to grow without bound: a car in a dead zone must
    not be able to cost the box memory, and when it comes back it wants
    NOW, not the minute it missed.
    """

    def __init__(self, bitrate: int, split: bool = False) -> None:
        self.ident = 0
        self.bitrate = int(bitrate)
        self.split = bool(split)
        self._max_bytes = int(bitrate * 1000 / 8 * LISTENER_QUEUE_SECONDS)
        self._loop: Any = None
        self._q: Any = None
        self._held = 0
        self._open = True
        self.dropped = 0
        self.sent = 0
        self.stalls = 0
        self.started = time.time()

    def bind(self, loop: Any) -> None:
        """Attach to the loop that will do the writing. Called from the
        route, before any chunk is offered."""
        self._loop = loop
        self._q = asyncio.Queue()

    # -- producer side (encoder thread) --------------------------------
    def offer(self, chunk: bytes) -> None:
        if not self._open:
            return
        loop, queue = self._loop, self._q
        if loop is None or queue is None:
            return
        try:
            loop.call_soon_threadsafe(self._push, chunk)
        except RuntimeError:
            # The loop is gone; so is this listener.
            self._open = False

    def _push(self, chunk: bytes) -> None:
        """Runs ON the loop, so the deque below needs no lock."""
        if not self._open or self._q is None:
            return
        self._q.put_nowait(chunk)
        self._held += len(chunk)
        # Too far behind: shed from the OLDEST end, toward the live edge.
        while self._held > self._max_bytes:
            try:
                old = self._q.get_nowait()
            except Exception:  # noqa: BLE001
                break
            self._held -= len(old)
            self.dropped += len(old)

    # -- consumer side (the route) -------------------------------------
    async def aget(self, timeout: float = 1.0) -> bytes:
        """Everything waiting, as one write. b"" on a timeout, which the
        route treats as a keep-alive tick rather than a close."""
        if self._q is None:
            return b""
        try:
            first = await asyncio.wait_for(self._q.get(), timeout)
        except asyncio.TimeoutError:
            self.stalls += 1
            return b""
        except Exception:  # noqa: BLE001
            return b""
        parts = [first]
        self._held -= len(first)
        while True:
            try:
                more = self._q.get_nowait()
            except Exception:  # noqa: BLE001
                break
            self._held -= len(more)
            parts.append(more)
        out = b"".join(parts)
        self.sent += len(out)
        return out

    def close(self) -> None:
        self._open = False

    @property
    def open(self) -> bool:
        return self._open

    def row(self) -> dict[str, Any]:
        up = max(0.001, time.time() - self.started)
        return {
            "id": self.ident,
            "bitrate": self.bitrate,
            "seconds": round(up, 1),
            "sent_kb": round(self.sent / 1024, 1),
            # The honest pace check for ONE listener: what they actually
            # received, against what the stream produced in that time.
            "delivered_x": round((self.sent * 8 / (self.bitrate * 1000)) / up, 3),
            "behind_kb": round(self._held / 1024, 1),
            "dropped_kb": round(self.dropped / 1024, 1),
            "quiet_ticks": self.stalls,
        }


def icy_block(title: str) -> bytes:
    """One ICY metadata block: a length byte then padded StreamTitle.

    This is what puts the record's name on a car head unit. Empty (a
    single zero byte) means "unchanged", which is what most of them are.
    """
    if not title:
        return b"\0"
    payload = ("StreamTitle='" + title.replace("'", "") + "';").encode(
        "utf-8", "ignore")
    pad = (16 - len(payload) % 16) % 16
    payload += b"\0" * pad
    blocks = len(payload) // 16
    if blocks > 255:
        return b"\0"
    return bytes([blocks]) + payload


def icy_wrap(chunks: Iterator[bytes], interval: int,
             title_of: Callable[[], str]) -> Iterator[bytes]:
    """Interleave ICY metadata every `interval` bytes of audio."""
    since = 0
    last = None
    for chunk in chunks:
        while chunk:
            room = interval - since
            if len(chunk) < room:
                yield chunk
                since += len(chunk)
                break
            yield chunk[:room]
            chunk = chunk[room:]
            since = 0
            title = title_of()
            if title != last:
                last = title
                yield icy_block(title)
            else:
                yield b"\0"

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
import os
import shutil
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
HLS_LIST_SIZE = int(os.getenv("STREAM_HLS_LIST", "15"))
# A phone should not begin its first moving-car session on a single segment.
# Three completed four-second chunks are enough for a tower handoff while
# keeping the initial tune-in delay bounded.
HLS_START_SEGMENTS = int(os.getenv("STREAM_HLS_START_SEGMENTS", "3"))
HLS_ROOT = os.getenv("STREAM_HLS_DIR", "")


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


class _HlsEncoder:
    """One AAC/HLS encoder at one bitrate, writing segments to a folder.

    ffmpeg owns the segmenting and the playlist rolling; this class only
    feeds it PCM and remembers when somebody last asked for the playlist,
    so an abandoned one can be reaped.
    """

    def __init__(self, bitrate: int, root: Path,
                 mix: tuple[int, int, int] = (100, 100, 100)) -> None:
        self.bitrate = int(bitrate)
        self.mix = listener_mix(mix)
        self.dir = root / ("hls%d-m%d-%d-%d" % ((self.bitrate,) + self.mix))
        self.playlist = self.dir / "live.m3u8"
        self.proc: subprocess.Popen | None = None
        self.prime: list[bytes] = []
        self.asked_at = time.time()
        self.restarts = 0

    def start(self) -> bool:
        try:
            # A fresh folder: a stale playlist from a previous run would
            # name segments that no longer exist, and a player reads that
            # as a broken stream rather than an old one.
            if self.dir.exists():
                for old in self.dir.iterdir():
                    try:
                        old.unlink()
                    except OSError:
                        pass
            self.dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        cmd = [_ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error",
               "-analyzeduration", "0", "-probesize", "32",
               "-fflags", "+nobuffer",
               "-f", "s16le", "-ar", str(RATE), "-ac", str(CHANNELS),
               "-i", "pipe:0",
               "-c:a", "aac", "-b:a", f"{self.bitrate}k",
               "-f", "hls",
               "-hls_time", str(HLS_SEGMENT_SECONDS),
               "-hls_list_size", str(HLS_LIST_SIZE),
               # delete_segments keeps the folder bounded; omit_endlist
               # keeps the playlist LIVE, so a player never decides the
               # broadcast has finished and stops asking.
               "-hls_flags", "delete_segments+omit_endlist+independent_segments",
               "-hls_segment_type", "mpegts",
               "-hls_allow_cache", "0",
               "-hls_segment_filename", str(self.dir / "seg%05d.ts"),
               str(self.playlist)]
        try:
            self.proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, bufsize=0)
        except Exception:  # noqa: BLE001
            self.proc = None
            return False
        return True

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

    def ready(self, minimum_segments: int = 1) -> bool:
        try:
            if not self.playlist.is_file() or self.playlist.stat().st_size <= 0:
                return False
            needed = max(1, int(minimum_segments))
            return sum(1 for path in self.dir.glob("seg*.ts")
                       if path.is_file()) >= needed
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
        self._hls: dict[tuple[int, tuple[int, int, int]], _HlsEncoder] = {}
        self._hls_root = Path(HLS_ROOT) if HLS_ROOT else Path(
            tempfile.mkdtemp(prefix="pinebox-hls-"))
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

    def hls(self, bitrate: Any = None,
            mix: Any = None) -> "_HlsEncoder":
        """The HLS encoder at this rate, started and primed if it is new.

        Unlike an mp3 listener there is no socket to hold: a player just
        keeps asking for the playlist. `asked_at` is that heartbeat, and
        the mixer reaps an encoder nobody has asked about.
        """
        rate = snap_rate(bitrate if bitrate is not None else self.bitrate)
        personal_mix = listener_mix(mix)
        key = (rate, personal_mix)
        with self._lock:
            enc = self._hls.get(key)
            if enc is None:
                enc = _HlsEncoder(rate, self._hls_root, personal_mix)
                if not enc.start():
                    self.stats["last_error"] = f"hls {rate}k would not start"
                # HLS has its own small rolling buffer.  Giving it the MP3
                # join burst put a new iPhone half a minute behind the
                # programme, while a slider-created mix had no burst at all.
                # Start every HLS lane at its live edge so the audio and its
                # companion video share one predictable clock.
                enc.prime = []
                self._hls[key] = enc
            enc.asked_at = time.time()
            self._last_listener_at = time.time()
        self.ensure_running()
        return enc

    def hls_existing(self, bitrate: int,
                     mix: Any = None) -> "_HlsEncoder | None":
        """The HLS encoder at this rate if one is already running.

        Segment requests must never be able to SPAWN an encoder: a player
        asking for a segment of a stream nobody is listening to is a stale
        playlist, and answering it by starting a lame process is how one
        abandoned tab keeps the box busy for ever."""
        with self._lock:
            enc = self._hls.get((int(bitrate), listener_mix(mix)))
            if enc is not None:
                enc.asked_at = time.time()
            return enc

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
                if (not self.listeners
                        and now - self._last_listener_at > LINGER_SECONDS
                        and self._last_listener_at):
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
                for hls in hlses:
                    hshaped = (frame if not on_air or hls.mix == (100, 100, 100)
                               else _mixed_program(
                                   bed, voice_pcm,
                                   bool(airing is not None and airing.sfx),
                                   hls.mix))
                    if hls.prime:
                        backlog, hls.prime = hls.prime, []
                        for past in backlog:
                            if not hls.feed(past):
                                break
                    if not hls.feed(hshaped):
                        self.stats["last_error"] = (
                            f"hls {hls.bitrate}k stopped")

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
                for hls in self._hls.values():
                    hls.stop()
                self._hls.clear()

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
        return {
            "running": bool(self._run),
            "listeners": self.listeners,
            "bitrate": self.bitrate,
            "rates": self.rates(),
            "hls_rates": ["%dk (%d/%d/%d)" % ((r,) + mix)
                          for (r, mix) in sorted(self._hls)],
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

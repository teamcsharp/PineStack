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

import os
import shutil
import subprocess
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
            return SILENCE, (not eof)
        if want:
            # The tail of a file, or a starved decoder: pad the frame.
            out += b"\0" * want
        return bytes(out), True


def _pcm(buf: bytes) -> np.ndarray:
    return np.frombuffer(buf, dtype="<i2").astype(np.int32)


class _Voice:
    """A DJ clip waiting for, or sitting on, its air moment."""

    __slots__ = ("key", "air_at", "path", "length", "decoder", "started")

    def __init__(self, key: str, air_at: float, path: str,
                 length: float) -> None:
        self.key = key
        self.air_at = float(air_at)
        self.path = path
        self.length = float(length or 0)
        self.decoder: _Decoder | None = None
        self.started = False


class _Encoder:
    """One mp3 encoder at one bitrate, its burst ring, and its listeners.

    The mix is made once by the mixer thread and handed to every live
    encoder, so a second listener at a different quality costs one lame
    process and nothing else - not a second decode of the record, and
    certainly not a second set of DJ clips.
    """

    def __init__(self, bitrate: int) -> None:
        self.bitrate = int(bitrate)
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
        self._encoders: dict[int, _Encoder] = {}
        self._next_id = 1

        self._run = False
        self._thread: threading.Thread | None = None
        self._last_listener_at = 0.0

        # The last JOIN_BURST_SECONDS of the mix, as PCM. Rate-independent,
        # so ONE copy primes an encoder at any bitrate. At 44.1k stereo
        # this is about 5 MB for thirty seconds.
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
            return {r: len(e.sinks) for r, e in self._encoders.items()}

    def attach(self, bitrate: Any = None) -> "_Sink":
        """A listener at one quality. The mix is shared; the encode is not."""
        rate = snap_rate(bitrate if bitrate is not None else self.bitrate)
        sink = _Sink(rate)
        with self._lock:
            enc = self._encoders.get(rate)
            if enc is None:
                enc = _Encoder(rate)
                if not enc.start():
                    self.stats["last_error"] = f"encoder {rate}k would not start"
                # The burst this rate has never had. The mixer writes it
                # on its next turn, ahead of any live frame, so the
                # listener attached below receives a full read-ahead
                # instead of the nothing a cold encoder would give them.
                enc.prime = list(self._pcm_burst)
                self._encoders[rate] = enc
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

    def detach(self, sink: "_Sink") -> None:
        with self._lock:
            enc = self._encoders.get(getattr(sink, "bitrate", 0))
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
                    for rate, enc in list(self._encoders.items()):
                        if (enc.idle_since
                                and now - enc.idle_since > LINGER_SECONDS):
                            enc.stop()
                            self._encoders.pop(rate, None)

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
                    if tid != music_id:
                        if music is not None:
                            music.close()
                        music, music_id = None, tid
                        path = str(track.get("path") or "")
                        if path:
                            offset = max(0.0, now - float(
                                track.get("started") or now))
                            cand = _Decoder(path, offset)
                            if cand.start():
                                music = cand
                            else:
                                self.stats["last_error"] = (
                                    f"record would not open: {path}")
                        self.stats["music_id"] = music_id
                        self._meta_seq += 1

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
                                       float(row.get("length") or 0))
                        # Decode AHEAD of the air moment, not at it.
                        voice.decoder = _Decoder(path)
                        voice.decoder.start()
                        pending.append(voice)
                    pending.sort(key=lambda v: v.air_at)

                paused = bool(state.get("paused"))
                on_air = bool(state.get("on", True)) and not paused

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
                            voice_pcm = _pcm(raw)
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
                            bed = _pcm(raw)
                    else:
                        bed = np.zeros(FRAME_SAMPLES * CHANNELS,
                                       dtype=np.int32)

                    mixed = bed * bed_gain
                    if voice_pcm is not None:
                        n = min(mixed.size, voice_pcm.size)
                        mixed[:n] += voice_pcm[:n] * VOICE_LEVEL
                    np.clip(mixed, -32768, 32767, out=mixed)
                    frame = mixed.astype("<i2").tobytes()

                # -- hand it to every encoder ------------------------------
                # One mix, several rates. A listener on 48k and one on
                # 128k share this frame and everything that made it.
                self._pcm_burst.append(frame)
                with self._lock:
                    encoders = list(self._encoders.values())
                if not encoders:
                    # Nobody yet, but the linger has not run out. Keep the
                    # mixer turning so the first listener starts instantly.
                    pass
                for enc in encoders:
                    before = enc.restarts
                    if enc.prime:
                        backlog, enc.prime = enc.prime, []
                        for past in backlog:
                            if not enc.feed(past):
                                break
                        self.stats["primed"] += 1
                    if not enc.feed(frame):
                        self.stats["last_error"] = (
                            f"encoder {enc.bitrate}k stopped")
                    if enc.restarts != before:
                        self.stats["encoder_restarts"] += 1

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
            "join_burst_s": JOIN_BURST_SECONDS,
            "title": self.now_title,
            "artist": self.now_artist,
            "up_seconds": round(up, 1),
            "produced_seconds": round(
                float(self.stats.get("frames") or 0) * FRAME_MS / 1000.0, 1),
            **{k: v for k, v in self.stats.items() if k != "frames"},
        }


class _Sink:
    """One listener's socket, and the backlog it is allowed to hold.

    A listener that cannot keep up is dropped back to the live edge
    rather than allowed to grow without bound - a stalled car radio must
    not be able to cost the box memory, and when it comes back it wants
    NOW, not the minute it missed.
    """

    def __init__(self, bitrate: int) -> None:
        self.ident = 0
        self.bitrate = int(bitrate)
        self._q: deque[bytes] = deque()
        self._held = 0
        self._max = int(bitrate * 1000 / 8 * LISTENER_QUEUE_SECONDS)
        self._cv = threading.Condition()
        self._open = True
        self.dropped = 0

    def offer(self, chunk: bytes) -> None:
        with self._cv:
            if not self._open:
                return
            self._q.append(chunk)
            self._held += len(chunk)
            while self._held > self._max and self._q:
                self._held -= len(self._q.popleft())
                self.dropped += 1
            self._cv.notify()

    def take(self, timeout: float = 1.0) -> bytes:
        """Whatever has piled up, as one write. Returns b"" on a timeout,
        which the route turns into a keep-alive tick rather than a close."""
        with self._cv:
            if not self._q and self._open:
                self._cv.wait(timeout)
            if not self._q:
                return b""
            out = b"".join(self._q)
            self._q.clear()
            self._held = 0
            return out

    def close(self) -> None:
        with self._cv:
            self._open = False
            self._cv.notify_all()

    @property
    def open(self) -> bool:
        return self._open


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

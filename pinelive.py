"""PineLive: the MX Live event - the operator's instrument on the air.

"I would like to add a feature called PineLive. It will be a special event
 for the station that will allow me to usb connect to the computer and play
 audio through an interface to the DGX Spark (or wirelessly) and be able to
 pause music playback and be able to play music live on the station."
                                                        - the operator

HOW THE PIECES FIT (contract: pinelive/CONTRACT.md, v2)
---------------------------------------------------------
* THE INPUT lives on the HOST (tools/pinelive_host.py, a systemd service):
  the K.O. II over ALSA, or a network sender. It hands the station one
  normalised stream (s16le / 44.1k / stereo) on 127.0.0.1:18095, and its
  state in data/pinelive/host_state.json. This module tells it what to do in
  data/pinelive/control.json. Why the host and not the container is written
  at the top of that file.
* ON THE AIR the set IS the record: while `live`, dj_next_track() returns a
  pseudo-record (live_track()) that goes on air through dj_on_air like any
  other, so every road that follows "the record on air" follows the set:
    - the car stream / HLS: the mixer takes LiveSource as its bed
      (station_stream.py, tools/pinelive_stream_patch.py), ducked under the
      DJs by the operator's depth/attack/release;
    - the tablet, the panel and the tune page: the clock names the record
      `/music/<live id>`, which this module serves as a live mp3 (LiveMp3),
      and `live: true` tells their followers never to seek it;
    - the album-art slot: `/music/<live id>/art` is a live MJPEG (Picture).
  The record that was playing is put back at the head of the queue, and it
  drops the moment the set ends or the input drops out.
* A DROPOUT NEVER BECOMES DEAD AIR. No frames for `dropout_seconds`, or
  silence for `silence_seconds`, and the station takes the air back (the
  queued record drops at once); the input takes it back by itself after
  `return_seconds` of signal. Every hand-over is written down: errors[],
  data/pinelive/events.jsonl, the pipeline log and the gap ledger.
* THE CUTS come off the mixer's tap: every frame carries the mix and the
  input frame that went into it, so a cut pair is cut on ONE clock on the
  same boundaries. Written under data/pinelive/cuts/<event>/ and handed to
  the desk's courier for \\\\10.89.1.125\\QuickSwap\\...\\Live Events.

Nothing in this module runs on a request that could block the event loop:
the host's state is a memoised stat+read, every stream is fed by a thread,
and every hand-over to the station's own state runs on the loop through
call_soon_threadsafe.
"""
from __future__ import annotations

# [pinelive-req] With string annotations (the future import above), FastAPI
# resolves 'Request'/'Header' against THIS module's globals - so the names
# must live here, not only inside install(). Guarded: the pure tests
# import this module without fastapi installed.
try:
    from fastapi import Header, HTTPException, Request
    from fastapi.responses import HTMLResponse, StreamingResponse
except ImportError:                                       # pragma: no cover
    Header = HTTPException = Request = None  # type: ignore[assignment]
    HTMLResponse = StreamingResponse = None  # type: ignore[assignment]

import asyncio
import base64
import hashlib
import hmac
import json
import os
import queue
import re
import secrets
import shutil
import socket
import struct
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

try:
    import numpy as np
except Exception:  # noqa: BLE001
    np = None

CONTRACT_VERSION = 2
EVENT_NAME = "MX Live"
EVENT_SLUG = "MX-Live"

RATE = 44100
CHANNELS = 2
FRAME_MS = 100
FRAME_SAMPLES = RATE * FRAME_MS // 1000                  # 4410
FRAME_BYTES = FRAME_SAMPLES * CHANNELS * 2               # 17640
BYTES_PER_S = RATE * CHANNELS * 2
SILENCE = b"\0" * FRAME_BYTES

DOOR = (os.environ.get("PINELIVE_DOOR_HOST", "127.0.0.1"),
        int(os.environ.get("PINELIVE_DOOR_PORT", "18095")))
INGEST_PORT = int(os.environ.get("PINELIVE_INGEST_PORT", "8095"))
HOST_STALE_S = 3.0
LIVE_TARGET_MS = 300.0          # the station-side cushion the drift trim holds
LIVE_MAX_MS = 3000.0            # past this, and not catching up, skip to the target
MP3_RATE_K = 192
MP3_LINGER_S = 30.0
PICTURE_TICK_S = 0.25
ADS_EVERY_S = 8.0
ADS_REFRESH_S = 120.0
CAM_FRESH_S = 5.0
ERRORS_KEEP = 20
DISK_LOW_BYTES = 5 * 1024 ** 3
PSEUDO_SECONDS = 6 * 3600.0

# A 160x90 dark frame: what a public viewer sees when video is switched off,
# and what the art slot shows before there is anything better.
PLACEHOLDER_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAgAAAQABAAD//gAPTGF2YzYxLjMuMTAwAP/bAEMACBAQExATFhYWFhYWGhga"
    "GxsbGhoaGhsbGx0dHSIiIh0dHRsbHR0gICIiJSYlIyMiIyYmKCgoMDAuLjg4OkVFU//EAEwAAQEA"
    "AAAAAAAAAAAAAAAAAAAHAQEBAAAAAAAAAAAAAAAAAAAAAxABAAAAAAAAAAAAAAAAAAAAABEBAAAA"
    "AAAAAAAAAAAAAAAAAP/AABEIAFoAoAMBIgACEQADEQD/2gAMAwEAAhEDEQA/AImAuiAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/9k=")

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "cut_seconds": 210,
    "record": True,
    "format": "wav",
    "dest": "\\\\10.89.1.125\\QuickSwap\\PineBoxRecordings\\Live Events",
    "picture_mode": "cam",
    "tailscale_video": False,
    "device": "",
    "device_label": "",
    "channel_pair": [1, 2],
    "channel_mode": "auto",
    "live_gain_db": 0.0,
    "duck_db": -10.8,
    "duck_attack_ms": 180,
    "duck_release_ms": 180,
    "dropout_seconds": 3.0,
    "silence_seconds": 15.0,
    "silence_db": -60.0,
    "return_seconds": 2.0,
    "arm_timeout": 20.0,
    "performer": "",
}

_RANGES: dict[str, tuple[float, float]] = {
    "cut_seconds": (30, 3600), "live_gain_db": (-24.0, 12.0),
    "duck_db": (-30.0, 0.0), "duck_attack_ms": (10, 2000),
    "duck_release_ms": (10, 5000), "dropout_seconds": (0.5, 30.0),
    "silence_seconds": (2.0, 300.0), "silence_db": (-90.0, -20.0),
    "return_seconds": (0.2, 30.0), "arm_timeout": (3.0, 300.0),
}


# ---------------------------------------------------------------------------
# The app's own functions, resolved when they are needed (install() hands
# over the module's globals, so nothing here depends on definition order).
# ---------------------------------------------------------------------------
_G: dict[str, Any] = {}


def _app(name: str, default: Any = None) -> Any:
    return _G.get(name, default)


def _log(text: str) -> None:
    fn = _app("pipeline_log")
    try:
        if callable(fn):
            fn("air", "[MX Live] " + text)
        else:
            print("[pinelive] " + text, flush=True)
    except Exception:  # noqa: BLE001
        pass


def _db(x: float) -> float:
    import math
    return round(20.0 * math.log10(max(float(x), 1e-10)), 1)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".%d.part" % os.getpid())
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:  # noqa: BLE001
        return shutil.which("ffmpeg") or "ffmpeg"


def clean_settings(raw: Any, base: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[str]]:
    """Merge `raw` onto `base` (or the defaults), clamping every number and
    refusing unknown enums. Returns (settings, what was refused)."""
    out = dict(DEFAULTS)
    out.update(base or {})
    refused: list[str] = []
    if not isinstance(raw, dict):
        return out, refused
    for key, value in raw.items():
        if key not in DEFAULTS:
            refused.append("%s (unknown)" % key)
            continue
        try:
            if key in ("enabled", "record", "tailscale_video"):
                out[key] = bool(value)
            elif key in _RANGES:
                lo, hi = _RANGES[key]
                num = float(value)
                if num != num:                       # NaN
                    raise ValueError
                num = min(hi, max(lo, num))
                out[key] = int(round(num)) if isinstance(DEFAULTS[key], int) else round(num, 2)
            elif key == "format":
                if str(value) not in ("wav", "flac"):
                    raise ValueError
                out[key] = str(value)
            elif key == "picture_mode":
                if str(value) not in ("cam", "ads"):
                    raise ValueError
                out[key] = str(value)
            elif key == "channel_mode":
                if str(value) not in ("auto", "stereo", "left", "right", "mix"):
                    raise ValueError
                out[key] = str(value)
            elif key == "channel_pair":
                a, b = int(value[0]), int(value[1])
                if not (1 <= a <= 32 and 1 <= b <= 32):
                    raise ValueError
                out[key] = [a, b]
            elif key == "dest":
                s = str(value or "").strip()
                if not re.match(r"^(\\\\|//)[^\\/]+[\\/][^\\/]+|^[A-Za-z]:[\\/]", s):
                    raise ValueError
                out[key] = s[:300]
            elif key in ("device", "device_label", "performer"):
                out[key] = str(value or "").strip()[:120]
        except Exception:  # noqa: BLE001
            refused.append(key)
    return out, refused


# ---------------------------------------------------------------------------
# LiveSource: the host's normalised stream, as the mixer's live bed.
# read_frame() never blocks: a starved read pads (and is counted), and a
# gentle drift trim holds the cushion near LIVE_TARGET_MS - the instrument's
# clock and the mixer's clock are not the same clock.
# ---------------------------------------------------------------------------
class LiveSource:
    def __init__(self, addr: tuple[str, int] = DOOR, cushion_ms: float = LIVE_TARGET_MS,
                 silence_db: float = -60.0, connect: bool = True) -> None:
        self.addr = addr
        self.cushion_ms = float(cushion_ms)
        self.silence_db = float(silence_db)
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.gain = 1.0
        self.duck_gain = 10 ** (-10.8 / 20.0)
        self.duck_attack_ms = 180.0
        self.duck_release_ms = 180.0
        self.duck_now = 0.0
        self.connected = False
        self.rx_at = 0.0
        self.rx_bytes = 0
        self.signal_at = 0.0
        self.signal_since = 0.0
        self.level_db: float | None = None
        self.peak_db: float | None = None
        self.frames_read = 0
        self.short_frames = 0
        self.trims = 0
        self.skipped_bytes = 0
        self.connects = 0
        self.why = ""
        self._reads: deque = deque(maxlen=40)
        self._ema: float | None = None
        self._stop = False
        self._thread: threading.Thread | None = None
        if connect:
            self._thread = threading.Thread(target=self._run, name="pinelive-live",
                                            daemon=True)
            self._thread.start()

    # -- the socket ---------------------------------------------------------
    def _run(self) -> None:
        rest = 0.5
        while not self._stop:
            sock = None
            try:
                sock = socket.create_connection(self.addr, timeout=3.0)
                sock.sendall(("GET /pcm?cushion_ms=%d HTTP/1.0\r\nHost: pinelive\r\n\r\n"
                              % int(self.cushion_ms)).encode())
                head = b""
                while b"\r\n\r\n" not in head:
                    got = sock.recv(4096)
                    if not got:
                        raise OSError("the door closed before answering")
                    head += got
                    if len(head) > 16384:
                        raise OSError("the door's answer has no end")
                header, _, body = head.partition(b"\r\n\r\n")
                if b" 200 " not in header.split(b"\r\n", 1)[0] + b" ":
                    raise OSError("the door said " + header.split(b"\r\n", 1)[0].decode("latin-1"))
                self.connected = True
                self.connects += 1
                self.why = ""
                rest = 0.5
                if body:
                    self._take(body)
                sock.settimeout(1.0)
                while not self._stop:
                    try:
                        chunk = sock.recv(65536)
                    except socket.timeout:
                        continue
                    if not chunk:
                        raise OSError("the door closed the stream")
                    self._take(chunk)
            except OSError as exc:
                self.why = str(exc)[:200]
            finally:
                self.connected = False
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
            if self._stop:
                break
            time.sleep(rest)
            rest = min(2.0, rest * 2)

    def _take(self, chunk: bytes) -> None:
        now = time.time()
        with self.lock:
            self.buf += chunk
            self.rx_at = now
            self.rx_bytes += len(chunk)
            over = len(self.buf) - int(LIVE_MAX_MS / 1000.0 * BYTES_PER_S)
            if over > 0 and not self._catching_up(now):
                drop = len(self.buf) - int(self.cushion_ms / 1000.0 * BYTES_PER_S)
                drop -= drop % 4
                if drop > 0:
                    del self.buf[:drop]
                    self.skipped_bytes += drop
        self._measure(chunk, now)

    def _measure(self, chunk: bytes, now: float) -> None:
        if np is None or len(chunk) < 64:
            return
        x = np.frombuffer(chunk[:len(chunk) - len(chunk) % 4], dtype="<i2").astype(np.float32)
        if not x.size:
            return
        x /= 32768.0
        rms = float(np.sqrt(np.mean(x * x)))
        peak = float(np.max(np.abs(x)))
        self.level_db, self.peak_db = _db(rms), _db(peak)
        if self.level_db > self.silence_db:
            if not self.signal_since or now - self.signal_at > 0.5:
                self.signal_since = now
            self.signal_at = now

    def _catching_up(self, now: float) -> bool:
        """More than ~12 reads in the last second: the mixer is running flat
        out after a stall, and the backlog is exactly what it needs."""
        return sum(1 for t in self._reads if now - t < 1.0) > 12

    # -- the mixer's side ---------------------------------------------------
    def buffered_ms(self) -> float:
        return len(self.buf) * 1000.0 / BYTES_PER_S

    def has_frame(self) -> bool:
        return len(self.buf) >= FRAME_BYTES

    def read_frame(self) -> tuple[bytes, bool]:
        now = time.time()
        self._reads.append(now)
        with self.lock:
            have_ms = len(self.buf) * 1000.0 / BYTES_PER_S
            # The cushion breathes by a chunk every time the host's pump
            # delivers, so the trim follows a two-second average of it, with
            # a deadband wider than one delivery: it answers clock drift,
            # never the arrival pattern.
            self._ema = have_ms if self._ema is None else self._ema * 0.95 + have_ms * 0.05
            want = FRAME_SAMPLES
            if self._ema > self.cushion_ms + 120.0:
                want = FRAME_SAMPLES + 1           # slightly fast: drain
            elif self._ema < self.cushion_ms - 120.0 and have_ms > 0:
                want = FRAME_SAMPLES - 1           # slightly slow: fill
            need = want * 4
            if len(self.buf) < need:
                got = bytes(self.buf[:len(self.buf) - len(self.buf) % 4])
                del self.buf[:len(got)]
                self.short_frames += 1
                self.frames_read += 1
                return got + b"\0" * (FRAME_BYTES - len(got)), False
            raw = bytes(self.buf[:need])
            del self.buf[:need]
            self.frames_read += 1
        if want == FRAME_SAMPLES or np is None:
            if want != FRAME_SAMPLES:              # no numpy: pad or cut
                raw = (raw + b"\0\0\0\0")[:FRAME_BYTES]
            return raw, True
        self.trims += 1
        return resample_frame(raw, want), True

    def signal_run(self, now: float | None = None) -> float:
        """How long the signal has been continuously present (0 = not now)."""
        now = time.time() if now is None else now
        if not self.signal_since or now - self.signal_at > 0.5:
            return 0.0
        return now - self.signal_since

    def close(self) -> None:
        self._stop = True

    def summary(self) -> dict[str, Any]:
        now = time.time()
        return {"connected": self.connected, "why": self.why,
                "rx_ago": round(now - self.rx_at, 2) if self.rx_at else None,
                "signal_ago": round(now - self.signal_at, 2) if self.signal_at else None,
                "buffered_ms": round(self.buffered_ms(), 1),
                "level_db": self.level_db, "peak_db": self.peak_db,
                "frames": self.frames_read, "short_frames": self.short_frames,
                "trims": self.trims, "skipped_ms": round(self.skipped_bytes * 1000.0 / BYTES_PER_S, 1),
                "connects": self.connects, "duck_now": round(self.duck_now, 3)}


def resample_frame(raw: bytes, n_in: int) -> bytes:
    """n_in stereo samples -> exactly FRAME_SAMPLES, by linear interpolation
    (a one-sample trim per 100 ms: 0.023 %, 0.4 cents)."""
    x = np.frombuffer(raw, dtype="<i2").reshape(-1, 2).astype(np.float64)
    src = np.arange(x.shape[0])
    dst = np.linspace(0, x.shape[0] - 1, FRAME_SAMPLES)
    y = np.empty((FRAME_SAMPLES, 2))
    y[:, 0] = np.interp(dst, src, x[:, 0])
    y[:, 1] = np.interp(dst, src, x[:, 1])
    return np.clip(np.round(y), -32768, 32767).astype("<i2").tobytes()


# ---------------------------------------------------------------------------
# The recorder: the mixer's tap -> cut pairs -> the courier.
# ---------------------------------------------------------------------------
def wav_header(data_bytes: int) -> bytes:
    block = CHANNELS * 2
    size = min(int(data_bytes), 0xFFFFFFFF - 36)
    return (b"RIFF" + struct.pack("<I", 36 + size) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, CHANNELS, RATE,
                                    RATE * block, block, 16)
            + b"data" + struct.pack("<I", size))


# [plair] the on-air test ends itself after this long (seconds).
REHEARSE_MAX_S = 600


def cut_names(start: float, index: int) -> tuple[str, str]:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(start))
    base = "%s_%s_c%03d" % (stamp, EVENT_SLUG, index)
    return base + "_input.wav", base + "_mix.wav"


class _Wav:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.fh = open(path, "w+b")
        self.fh.write(wav_header(0))
        self.bytes = 0
        self.fixed_at = time.time()

    def write(self, data: bytes) -> None:
        self.fh.write(data)
        self.bytes += len(data)
        if time.time() - self.fixed_at > 30.0:
            self.fix()

    def fix(self) -> None:
        here = self.fh.tell()
        self.fh.seek(0)
        self.fh.write(wav_header(self.bytes))
        self.fh.seek(here)
        self.fh.flush()
        self.fixed_at = time.time()

    def close(self) -> None:
        try:
            self.fix()
        finally:
            self.fh.close()


class Recorder:
    """Cut pairs on the mixer's clock. tap() runs on the mixer thread and
    only queues; everything else is this recorder's own thread."""

    def __init__(self, owner: "PineLive") -> None:
        self.owner = owner
        self.q: "queue.SimpleQueue[Any]" = queue.SimpleQueue()
        self.active = False
        self.folder: Path | None = None
        self.folder_name = ""
        self.frames_per_cut = 2100
        self.fmt = "wav"
        self.index = 0
        self.frames = 0
        self.start_t = 0.0
        self.inp: _Wav | None = None
        self.mix: _Wav | None = None
        self.cuts: list[dict[str, Any]] = []
        self.last_frame_at = 0.0
        self.frames_total = 0
        self.why = ""
        self._thread = threading.Thread(target=self._run, name="pinelive-cuts", daemon=True)
        self._thread.start()

    # -- the mixer side -----------------------------------------------------
    def tap(self, frame: bytes, live: bytes | None, info: dict[str, Any]) -> None:
        if self.active:
            self.q.put((frame, live, float(info.get("t") or time.time())))

    # -- control ------------------------------------------------------------
    def begin(self, folder: Path, folder_name: str, cut_seconds: float, fmt: str,
              first_index: int = 1) -> None:
        self.q.put(("begin", folder, folder_name, cut_seconds, fmt, first_index))
        self.active = True

    def end(self) -> None:
        self.active = False
        done = threading.Event()
        self.q.put(("end", done))
        done.wait(20.0)

    def set_cut_seconds(self, seconds: float) -> None:
        self.q.put(("cut_seconds", seconds))

    # -- the thread ---------------------------------------------------------
    def _run(self) -> None:
        while True:
            item = self.q.get()
            try:
                if item and item[0] == "begin":
                    _, folder, name, secs, fmt, first = item
                    self._close_pair(final=True)
                    self.folder, self.folder_name = folder, name
                    self.folder.mkdir(parents=True, exist_ok=True)
                    self.frames_per_cut = max(10, int(round(float(secs) * 1000 / FRAME_MS)))
                    self.fmt = fmt
                    self.index = int(first) - 1
                    self.frames = 0
                    continue
                if item and item[0] == "end":
                    self._close_pair(final=True)
                    item[1].set()
                    continue
                if item and item[0] == "cut_seconds":
                    self.frames_per_cut = max(10, int(round(float(item[1]) * 1000 / FRAME_MS)))
                    continue
                frame, live, t = item
                if self.folder is None:
                    continue
                if self.inp is None:
                    self._open_pair(t)
                self.inp.write(live if live else SILENCE)
                self.mix.write(frame if frame else SILENCE)
                self.frames += 1
                self.frames_total += 1
                self.last_frame_at = time.time()
                if self.frames >= self.frames_per_cut:
                    self._close_pair(final=False)
            except Exception as exc:  # noqa: BLE001
                self.why = "cut_write: %s" % exc
                self.owner.error("cut_write", "a cut could not be written: %s" % exc)
                self.inp = self.mix = None

    def _open_pair(self, t: float) -> None:
        self.index += 1
        self.start_t = t
        a, b = cut_names(t, self.index)
        self.inp = _Wav(self.folder / a)
        self.mix = _Wav(self.folder / b)
        self.frames = 0

    def _close_pair(self, final: bool) -> None:
        if self.inp is None or self.mix is None:
            self.inp = self.mix = None
            return
        inp, mix, frames = self.inp, self.mix, self.frames
        self.inp = self.mix = None
        inp.close()
        mix.close()
        if final and frames < 10:              # under a second: not a cut
            for w in (inp, mix):
                try:
                    w.path.unlink()
                except OSError:
                    pass
            self.index -= 1
            return
        paths = [inp.path, mix.path]
        if self.fmt == "flac":
            paths = [to_flac(p) or p for p in paths]
        row = {"event": self.owner.event_id(), "index": self.index,
               "start": round(self.start_t, 3), "seconds": frames * FRAME_MS / 1000.0,
               "input": paths[0].name, "mix": paths[1].name,
               "folder": self.folder_name, "final": bool(final), "at": time.time()}
        row["courier"] = self.owner.courier_hand(paths, self.folder_name)
        self.cuts.append(row)
        del self.cuts[:-400]
        self.owner.cut_closed(row)


def to_flac(path: Path) -> Path | None:
    out = path.with_suffix(".flac")
    try:
        subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-y", "-i", str(path), "-c:a", "flac", str(out)],
                       check=True, timeout=300, capture_output=True)
        path.unlink()
        return out
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# LiveMp3: the input alone as an endless mp3 - the record road's live
# record, and the popup's monitor. ffmpeg reads the host's door itself, so
# no byte of it waits on this process's GIL on the way in.
# ---------------------------------------------------------------------------
class LiveMp3:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.listeners: dict[int, tuple[Any, Any]] = {}
        self.burst: deque = deque(maxlen=48)          # ~2 s at 192k in 1 KB-ish chunks
        self.proc: subprocess.Popen | None = None
        self.next_id = 1
        self.last_listener_at = 0.0
        self.why = ""
        self.bytes_out = 0

    def cmd(self) -> list[str]:
        return [_ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error",
                "-fflags", "+nobuffer", "-probesize", "32", "-analyzeduration", "0",
                "-f", "s16le", "-ar", str(RATE), "-ac", str(CHANNELS),
                "-i", "http://%s:%d/pcm?cushion_ms=200" % DOOR,
                "-c:a", "libmp3lame", "-b:a", "%dk" % MP3_RATE_K,
                "-flush_packets", "1", "-f", "mp3", "pipe:1"]

    def ensure(self) -> None:
        with self.lock:
            if self.proc is not None and self.proc.poll() is None:
                return
            try:
                self.proc = subprocess.Popen(self.cmd(), stdout=subprocess.PIPE,
                                             stderr=subprocess.DEVNULL,
                                             stdin=subprocess.DEVNULL)
            except Exception as exc:  # noqa: BLE001
                self.why = "the mp3 encoder would not start: %s" % exc
                self.proc = None
                return
            threading.Thread(target=self._pump, args=(self.proc,), daemon=True,
                             name="pinelive-mp3").start()

    def _pump(self, proc: subprocess.Popen) -> None:
        try:
            fd = proc.stdout.fileno()
            while True:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                self.burst.append(chunk)
                self.bytes_out += len(chunk)
                with self.lock:
                    rows = list(self.listeners.values())
                for loop, q in rows:
                    try:
                        loop.call_soon_threadsafe(_offer, q, chunk)
                    except RuntimeError:
                        pass
        except Exception as exc:  # noqa: BLE001
            self.why = "mp3 pump: %s" % exc

    def attach(self, loop: Any) -> tuple[int, Any]:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        with self.lock:
            ident = self.next_id
            self.next_id += 1
            self.listeners[ident] = (loop, q)
            self.last_listener_at = time.time()
        for chunk in list(self.burst):
            _offer(q, chunk)
        self.ensure()
        return ident, q

    def detach(self, ident: int) -> None:
        with self.lock:
            self.listeners.pop(ident, None)
            self.last_listener_at = time.time()

    def reap(self, force: bool = False) -> None:
        with self.lock:
            idle = not self.listeners and time.time() - self.last_listener_at > MP3_LINGER_S
            proc = self.proc if (force or idle) else None
            if proc is not None:
                self.proc = None
                self.burst.clear()
        if proc is not None:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass


def _offer(q: Any, item: Any) -> None:
    """Drop-oldest: a listener that cannot keep up loses the past, never the
    present."""
    try:
        q.put_nowait(item)
    except asyncio.QueueFull:
        try:
            q.get_nowait()
            q.put_nowait(item)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# The picture: one JPEG at a time, published by a thread; every MJPEG viewer
# reads the same bytes from memory.
# ---------------------------------------------------------------------------
class Picture:
    def __init__(self, owner: "PineLive") -> None:
        self.owner = owner
        self.jpeg = PLACEHOLDER_JPEG
        self.kind = "none"
        self.seq = 0
        self.viewers = 0
        self.public_viewers = 0
        self._cam_mtime = 0.0
        self._ads: list[dict[str, Any]] = []
        self._ads_at = 0.0
        self._ad_i = 0
        self._ad_at = 0.0
        self._thread: threading.Thread | None = None
        self.why = ""

    def ensure(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="pinelive-picture",
                                            daemon=True)
            self._thread.start()

    def _publish(self, jpeg: bytes, kind: str) -> None:
        if jpeg and (jpeg is not self.jpeg):
            self.jpeg = jpeg
            self.kind = kind
            self.seq += 1

    def _cam(self) -> bytes | None:
        path = _app("PINELINK_FRAME")
        if path is None:
            return None
        try:
            st = Path(path).stat()
        except OSError:
            return None
        if time.time() - st.st_mtime > CAM_FRESH_S:
            return None
        if st.st_mtime == self._cam_mtime:
            return self.jpeg if self.kind == "cam" else None
        try:
            raw = Path(path).read_bytes()
        except OSError:
            return None
        if len(raw) < 1024 or raw[-2:] != b"\xff\xd9":
            return self.jpeg if self.kind == "cam" else None    # caught mid-write
        self._cam_mtime = st.st_mtime
        return raw

    def _ads_refresh(self) -> None:
        if time.time() - self._ads_at < ADS_REFRESH_S and self._ads:
            return
        self._ads_at = time.time()
        rows: list[dict[str, Any]] = []
        try:
            catalog = _app("gen_ads_catalog")
            poster_dir = _app("SFX_POSTER_DIR")
            for row in (catalog() if callable(catalog) else [])[:40]:
                sid = str(row.get("id") or "")
                if re.fullmatch(r"[a-f0-9]{16}", sid) and poster_dir is not None:
                    rows.append({"id": sid, "poster": Path(poster_dir) / (sid + ".jpg"),
                                 "name": str(row.get("name") or "")})
        except Exception as exc:  # noqa: BLE001
            self.why = "ads: %s" % exc
        self._ads = rows

    def _ad(self) -> bytes | None:
        self._ads_refresh()
        if not self._ads:
            return None
        if self.kind == "ads" and time.time() - self._ad_at < ADS_EVERY_S:
            return self.jpeg
        for _ in range(len(self._ads)):
            row = self._ads[self._ad_i % len(self._ads)]
            self._ad_i += 1
            path: Path = row["poster"]
            if not path.is_file():
                try:                                    # the station's own renderer
                    sample = _app("sfx_by_id")(row["id"])
                    if sample is not None:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        _app("_render_poster")(sample, path)
                except Exception:  # noqa: BLE001
                    pass
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            if len(raw) > 512:
                self._ad_at = time.time()
                return raw
        return None

    def _run(self) -> None:
        while True:
            try:
                pl = self.owner
                busy = pl.armed() or self.viewers > 0
                if not busy:
                    time.sleep(1.0)
                    continue
                mode = pl.settings.get("picture_mode", "cam")
                got, kind = None, "none"
                if mode == "cam":
                    got = self._cam()
                    kind = "cam"
                    if got is None:
                        got, kind = self._ad(), "ads"
                else:
                    got, kind = self._ad(), "ads"
                    if got is None:
                        got, kind = self._cam(), "cam"
                if got is None:
                    got, kind = PLACEHOLDER_JPEG, "none"
                self._publish(got, kind)
            except Exception as exc:  # noqa: BLE001
                self.why = str(exc)[:200]
            time.sleep(PICTURE_TICK_S)


# ---------------------------------------------------------------------------
# Levels: the host's frames, fanned out by one reader thread.
# ---------------------------------------------------------------------------
class LevelsHub:
    def __init__(self, owner: "PineLive") -> None:
        self.owner = owner
        self.lock = threading.Lock()
        self.subs: dict[int, tuple[Any, Any]] = {}
        self.next_id = 1
        self._thread: threading.Thread | None = None
        self.frames = 0
        self.why = ""

    def attach(self, loop: Any) -> tuple[int, Any]:
        q: asyncio.Queue = asyncio.Queue(maxsize=40)
        with self.lock:
            ident = self.next_id
            self.next_id += 1
            self.subs[ident] = (loop, q)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="pinelive-levels",
                                                daemon=True)
                self._thread.start()
        return ident, q

    def detach(self, ident: int) -> None:
        with self.lock:
            self.subs.pop(ident, None)

    def push(self, kind: str, data: str) -> None:
        with self.lock:
            rows = list(self.subs.values())
        for loop, q in rows:
            try:
                loop.call_soon_threadsafe(_offer, q, (kind, data))
            except RuntimeError:
                pass

    def _run(self) -> None:
        while True:
            with self.lock:
                if not self.subs:
                    self._thread = None
                    return
            sock = None
            try:
                sock = socket.create_connection(DOOR, timeout=3.0)
                sock.sendall(b"GET /levels HTTP/1.0\r\nHost: pinelive\r\n\r\n")
                sock.settimeout(8.0)
                buf = b""
                header_done = False
                while True:
                    with self.lock:
                        if not self.subs:
                            return
                    chunk = sock.recv(8192)
                    if not chunk:
                        break
                    buf += chunk
                    if not header_done:
                        if b"\r\n\r\n" not in buf:
                            continue
                        buf = buf.split(b"\r\n\r\n", 1)[1]
                        header_done = True
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            frame = json.loads(line)
                            frame["duck"] = round(float(self.owner.duck_now()), 3)
                            self.frames += 1
                            self.push("frame", json.dumps(frame, separators=(",", ":")))
                        except Exception:  # noqa: BLE001
                            continue
            except OSError as exc:
                self.why = str(exc)[:200]
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
            time.sleep(1.0)


# ---------------------------------------------------------------------------
# The event.
# ---------------------------------------------------------------------------
class PineLive:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data = Path(data_dir) if data_dir else Path("data") / "pinelive"
        self.lock = threading.RLock()
        self.loop: Any = None
        self.settings: dict[str, Any] = dict(DEFAULTS)
        self.phase = "idle"
        self.phase_at = time.time()
        self.event: dict[str, Any] | None = None
        self.source_kind: str | None = None
        self.device = ""
        self.token = ""
        self.errors: deque = deque(maxlen=ERRORS_KEEP)
        self.held_record: dict[str, Any] | None = None
        self.live: LiveSource | None = None
        self.recorder: Recorder | None = None
        self.mp3 = LiveMp3()
        self.picture = Picture(self)
        self.levels = LevelsHub(self)
        self.listeners: list[Callable[[dict, dict], Any]] = []
        self.control: dict[str, Any] = {}
        self._host_memo: tuple[float, dict[str, Any]] = (0.0, {})
        self._host_read_at = 0.0
        self._sup: threading.Thread | None = None
        self._last_courier_check = 0.0
        self._courier_memo: tuple[float, dict[str, Any]] = (0.0, {})
        self._tapped = False
        self.live_since = 0.0
        self.live_total = 0.0
        self._disk_warned = 0.0
        self._saved_at = 0.0

    # -- paths -----------------------------------------------------------------
    @property
    def settings_path(self) -> Path:
        return self.data / "settings.json"

    @property
    def control_path(self) -> Path:
        return self.data / "control.json"

    @property
    def host_path(self) -> Path:
        return self.data / "host_state.json"

    @property
    def event_path(self) -> Path:
        return self.data / "event.json"

    @property
    def log_path(self) -> Path:
        return self.data / "events.jsonl"

    @property
    def cuts_root(self) -> Path:
        return self.data / "cuts"

    # -- boot ------------------------------------------------------------------
    def boot(self) -> None:
        self.data.mkdir(parents=True, exist_ok=True)
        try:
            got = json.loads(self.settings_path.read_text())
            self.settings, _ = clean_settings(got)
        except Exception:  # noqa: BLE001
            self.settings = dict(DEFAULTS)
        try:
            self.control = json.loads(self.control_path.read_text())
        except Exception:  # noqa: BLE001
            self.control = {}
        self.recorder = Recorder(self)
        # A restart mid-set: the host kept capturing (control.json still says
        # armed) and its safety master kept recording. Pick the event up.
        try:
            ev = json.loads(self.event_path.read_text())
            if isinstance(ev, dict) and ev.get("id") and ev.get("armed"):
                self.event = ev
                self.source_kind = ev.get("source") or "usb"
                self.device = ev.get("device") or ""
                self.token = str(self.control.get("token") or "")
                self.live_total = float(ev.get("live_seconds") or 0)
                self._arm_runtime(resume=True)
                self.note("resumed", "the station restarted mid-set; MX Live picks up "
                          "where it was (the host kept the input and its master)")
        except FileNotFoundError:
            pass
        except Exception as exc:  # noqa: BLE001
            self.error("resume", "could not resume the event: %s" % exc)
        if self._sup is None:
            self._sup = threading.Thread(target=self._supervise, name="pinelive-sup",
                                         daemon=True)
            self._sup.start()
        self.picture.ensure()

    # -- small helpers ------------------------------------------------------------
    def armed(self) -> bool:
        return self.event is not None and self.phase in ("arming", "live", "fallback")

    def event_id(self) -> str:
        return str((self.event or {}).get("id") or "")

    def live_id(self) -> str:
        eid = self.event_id()
        return hashlib.sha1(("pinelive:" + eid).encode()).hexdigest()[:16] if eid else ""

    def is_live_id(self, track_id: str) -> bool:
        lid = self.live_id()
        return bool(lid) and hmac.compare_digest(str(track_id or ""), lid)

    def duck_now(self) -> float:
        return float(self.live.duck_now) if self.live is not None else 0.0

    def sign(self, key: str) -> str:
        fn = _app("media_sign")
        try:
            return str(fn(key)) if callable(fn) else ""
        except Exception:  # noqa: BLE001
            return ""

    def sig_ok(self, key: str, given: str) -> bool:
        want = self.sign(key)
        return bool(want) and hmac.compare_digest(str(given or ""), want)

    def on_loop(self, fn: Callable[[], Any]) -> None:
        loop = self.loop
        if loop is None:
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass
            return
        try:
            loop.call_soon_threadsafe(fn)
        except RuntimeError:
            pass

    def note(self, code: str, say: str, **extra: Any) -> None:
        row = {"at": round(time.time(), 3), "event": self.event_id(), "code": code,
               "say": say, "phase": self.phase, **extra}
        try:
            self.data.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
        except Exception:  # noqa: BLE001
            pass
        _log(say)

    def error(self, code: str, say: str) -> None:
        self.errors.appendleft({"at": round(time.time(), 3), "code": code, "say": say})
        self.note(code, say)

    # -- settings ------------------------------------------------------------------
    def set_settings(self, raw: Any) -> tuple[dict[str, Any], list[str]]:
        with self.lock:
            new, refused = clean_settings(raw, self.settings)
            old = self.settings
            self.settings = new
            _atomic_write(self.settings_path, json.dumps(new, indent=1))
        if self.live is not None:
            self._live_params()
        if self.recorder is not None and new["cut_seconds"] != old.get("cut_seconds"):
            self.recorder.set_cut_seconds(new["cut_seconds"])
        if self.armed():
            self.write_control()
        if old.get("tailscale_video") != new.get("tailscale_video"):
            self.note("tailscale_video", "public video %s" % (
                "ON: listeners on the tailnet see the picture" if new["tailscale_video"]
                else "OFF: the public side stops showing video now"))
        return new, refused

    def _live_params(self) -> None:
        s, live = self.settings, self.live
        if live is None:
            return
        live.gain = 10 ** (float(s["live_gain_db"]) / 20.0)
        live.duck_gain = 10 ** (float(s["duck_db"]) / 20.0)
        live.duck_attack_ms = float(s["duck_attack_ms"])
        live.duck_release_ms = float(s["duck_release_ms"])
        live.silence_db = float(s["silence_db"])

    # -- the host ---------------------------------------------------------------------
    def write_control(self, **extra: Any) -> None:
        s = self.settings
        c = dict(self.control)
        c.update({"v": 1, "at": time.time(), "armed": self.armed(),
                  "event_id": self.event_id(), "source": self.source_kind or "",
                  "device": self.device or s.get("device") or "",
                  "channel_pair": list(s["channel_pair"]),
                  "channel_mode": s["channel_mode"], "silence_db": s["silence_db"],
                  "token": self.token,
                  "master": not bool((self.event or {}).get("rehearse"))})   # [plair]
        c.update(extra)
        self.control = c
        try:
            _atomic_write(self.control_path, json.dumps(c, indent=1))
        except Exception as exc:  # noqa: BLE001
            self.error("no_host", "could not write the host's control file: %s" % exc)

    def host(self) -> dict[str, Any]:
        """host_state.json, memoised half a second; `age` and `up` added."""
        now = time.time()
        at, got = self._host_memo
        if now - at > 0.5:
            try:
                got = json.loads(self.host_path.read_text())
                if not isinstance(got, dict):
                    got = {}
            except Exception:  # noqa: BLE001
                got = {}
            self._host_memo = (now, got)
        age = now - float(got.get("at") or 0) if got.get("at") else None
        out = dict(got)
        out["age"] = round(age, 2) if age is not None else None
        out["up"] = bool(age is not None and age < HOST_STALE_S)
        if not got:
            out["why"] = ("the PineLive host service has never run - install "
                          "tools/pinelive.service on the host")
        elif not out["up"]:
            out["why"] = ("the PineLive host service stopped answering %ds ago"
                          % int(age or 0))
        else:
            out["why"] = ""
        return out

    # -- the phase machine ------------------------------------------------------------
    def _set_phase(self, phase: str) -> None:
        old = self.event_state()
        if phase == self.phase:
            return
        if self.phase == "live" and self.live_since:
            self.live_total += time.time() - self.live_since
            self.live_since = 0.0
        if phase == "live":
            self.live_since = time.time()
        self.phase = phase
        self.phase_at = time.time()
        self._save_event()
        new = self.event_state()
        self.levels.push("state", json.dumps({"phase": phase, "live": phase == "live"}))
        for fn in list(self.listeners):
            try:
                fn(old, new)
            except Exception:  # noqa: BLE001
                pass

    def _save_event(self) -> None:
        if self.event is None:
            return
        ev = dict(self.event)
        ev.update({"armed": self.armed(), "phase": self.phase, "source": self.source_kind,
                   "device": self.device, "live_seconds": round(self.live_seconds(), 1)})
        try:
            _atomic_write(self.event_path, json.dumps(ev, indent=1))
        except Exception:  # noqa: BLE001
            pass

    def live_seconds(self) -> float:
        return self.live_total + ((time.time() - self.live_since) if self.live_since else 0.0)

    def refuse(self, code: str, say: str) -> dict[str, Any]:
        return {"ok": False, "code": code, "say": say}

    def start(self, body: dict[str, Any]) -> dict[str, Any]:
        s = self.settings
        radio = _app("_RADIO") or {}
        # [plair] the on-air TEST rides the set's own road - the record steps
        # aside, the DJs duck over the interface, SFX run - but it is never
        # recorded, it is allowed with the switch off, and it ends itself.
        rehearse = bool(body.get("rehearse"))
        with self.lock:
            if not rehearse and not s.get("enabled", True):
                return self.refuse("disabled", "MX Live is switched off - turn the event on first")
            if self.armed():
                return self.refuse("already_live", "MX Live is already running")
            if not radio.get("on"):
                return self.refuse("station_off", "the station's power is off - "
                                   "turn Pine Box FM on first; the set rides the show")
            paused = _app("radio_paused")
            if callable(paused) and paused():
                if not body.get("unpause"):
                    return self.refuse("station_paused", "the station is paused (off air) - "
                                       "un-pause it, or start with unpause")
                try:
                    _app("radio_pause_set")(False, why="MX Live started (unpause asked)")
                except Exception:  # noqa: BLE001
                    pass
            source = str(body.get("source") or "usb")
            if source not in ("usb", "network"):
                return self.refuse("bad_source", "source must be usb or network")
            h = self.host()
            if not h.get("up"):
                return self.refuse("no_host", h.get("why") or "the host service is not running")
            device = str(body.get("device") or s.get("device") or "")
            if source == "usb":
                rows = [d for d in ((h.get("devices") or {}).get("usb") or []) if d.get("capture")]
                pick = None
                for d in rows:
                    if device and device in (d.get("id"), d.get("card_id")):
                        pick = d
                if pick is None and not device:
                    ready = [d for d in rows if d.get("status") == "ready"]
                    # [plair] the instrument first, as the host ranks it ([plpick]):
                    # card order put a keyboard dongle's 8 kHz mic ahead of the K.O. II.
                    def _rank(d: dict[str, Any]) -> tuple[int, int, int]:
                        te = 0 if str(d.get("usb_id") or "").startswith("2367:") else 1
                        try:
                            top = max(int(r) for r in (d.get("rates") or [0]))
                        except Exception:  # noqa: BLE001
                            top = 0
                        real = 0 if int(d.get("channels") or 0) >= 2 and top >= 44100 else 1
                        try:
                            card = int(d.get("card") or 0)
                        except Exception:  # noqa: BLE001
                            card = 0
                        return (te, real, card)
                    pick = (sorted(ready, key=_rank) or sorted(rows, key=_rank) or [None])[0]
                if pick is None:
                    return self.refuse("no_device", "no USB capture device %s- plug the "
                                       "K.O. II in, then look at Devices" %
                                       (("named %s " % device) if device else ""))
                if pick.get("status") == "busy":
                    return self.refuse("device_busy", pick.get("hint") or "the device is busy")
                device = str(pick.get("id"))
            now = time.time()
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
            self.event = {"id": ("mxlive-test-" if rehearse else "mxlive-") + stamp,
                          "name": EVENT_NAME, "started_at": now,
                          "folder": "%s_%s" % (stamp, EVENT_SLUG), "armed": True,
                          "fallbacks": 0, "rehearse": rehearse}
            self.source_kind = source
            self.device = device
            self.token = secrets.token_hex(16)
            self.live_total = 0.0
            self.live_since = 0.0
            self.errors.clear()
            self.held_record = None
            self._arm_runtime(resume=False)
        if rehearse:                                                # [plair]
            self.note("start", "on-air test armed (%s%s) - the interface takes the broadcast "
                      "as soon as it sounds; not recorded, %d minutes at most"
                      % (source, (" " + device) if device else "", REHEARSE_MAX_S // 60))
            return {"ok": True, "code": "", "say": "on-air test - the %s replaces the record "
                    "as soon as it sounds, DJs and all; tap End test to stop" %
                    ("K.O. II" if source == "usb" else "sender")}
        self.note("start", "MX Live armed (%s%s) - the music keeps playing until the "
                  "input is heard" % (source, (" " + device) if device else ""))
        return {"ok": True, "code": "", "say": "MX Live is armed - waiting for the "
                "first sound from the %s" % ("K.O. II" if source == "usb" else "sender")}

    def _arm_runtime(self, resume: bool) -> None:
        """Everything an armed event runs: the host told, the input opened,
        the recorder begun, the mixer tapped. The phase starts at arming - the
        air is only taken once real audio arrives."""
        self.phase = "arming"
        self.phase_at = time.time()
        self.write_control(test_until=0)
        if self.live is not None:
            self.live.close()
        self.live = LiveSource(silence_db=float(self.settings["silence_db"]))
        self._live_params()
        folder_name = str(self.event.get("folder") or self.event_id())
        folder = self.cuts_root / folder_name
        first = 1
        if resume:
            try:
                got = [int(m.group(1)) for p in folder.glob("*_c*_mix.*")
                       for m in [re.search(r"_c(\d+)_mix\.", p.name)] if m]
                first = max(got) + 1 if got else 1
            except Exception:  # noqa: BLE001
                first = 1
        rehearse = bool((self.event or {}).get("rehearse"))       # [plair] a test is not recorded
        if self.settings.get("record", True) and self.recorder is not None and not rehearse:
            self.recorder.begin(folder, folder_name, float(self.settings["cut_seconds"]),
                                str(self.settings["format"]), first)
        if not rehearse:
            self._tap(True)
        self._save_event()
        self.picture.ensure()

    def _tap(self, on: bool) -> None:
        stream = _app("STATION_STREAM")
        if stream is None or self.recorder is None:
            return
        try:
            if on:
                if hasattr(stream, "add_tap"):
                    stream.add_tap(self.recorder.tap)
                    self._tapped = True
                else:
                    self.error("mixer_down", "the stream mixer has no tap - "
                               "tools/pinelive_stream_patch.py is not applied")
            elif hasattr(stream, "remove_tap"):
                stream.remove_tap(self.recorder.tap)
                self._tapped = False
        except Exception as exc:  # noqa: BLE001
            self.error("mixer_down", "the mixer tap failed: %s" % exc)

    def stop(self, why: str = "the stop control") -> dict[str, Any]:
        with self.lock:
            if self.event is None:
                return {"ok": True, "code": "", "say": "MX Live was not running"}
            was_live = self.phase == "live"
            rehearse = bool((self.event or {}).get("rehearse"))    # [plair]
            self._set_phase("stopping")
        if was_live:
            self._give_air("stop")
        if self.recorder is not None and not rehearse:
            self.recorder.end()
        if not rehearse:
            self._tap(False)
        with self.lock:
            ev = dict(self.event or {})
            ev["ended_at"] = time.time()
            ev["live_seconds"] = round(self.live_seconds(), 1)
            self.live_since = 0.0
            self.event = None
            self.token = ""
            self.write_control(test_until=0)
            if self.live is not None:
                self.live.close()
                self.live = None
            self.held_record = None
            try:
                self.event_path.unlink()
            except OSError:
                pass
            self._set_phase("idle")
        self.mp3.reap(force=True)
        cuts = len([c for c in (self.recorder.cuts if self.recorder else [])
                    if c.get("event") == ev.get("id")])
        if rehearse:                                                # [plair]
            self.note("stop", "the on-air test ended (%s): %.0f s on air" % (
                why, ev.get("live_seconds", 0)), event_row=ev)
            return {"ok": True, "code": "", "say": "the test is over - the music is back"}
        self.note("stop", "MX Live ended (%s): %.0f s live, %d cut pair%s" % (
            why, ev.get("live_seconds", 0), cuts, "" if cuts == 1 else "s"),
            event_row=ev)
        return {"ok": True, "code": "", "say": "MX Live ended - the music is back"}

    def test(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.armed():
            return self.refuse("already_live", "MX Live is running - the test is for before the set")
        h = self.host()
        if not h.get("up"):
            return self.refuse("no_host", h.get("why") or "the host service is not running")
        source = str(body.get("source") or "usb")
        seconds = 4.0 if source == "usb" else 60.0
        self.source_kind = source
        self.device = str(body.get("device") or self.settings.get("device") or "")
        if source == "network":
            self.token = secrets.token_hex(16)
        self.write_control(test_until=time.time() + seconds)
        return {"ok": True, "code": "", "say": "listening to the %s for %d seconds - "
                "nothing goes on air" % ("K.O. II" if source == "usb" else "sender",
                                          seconds)}

    # -- the air -------------------------------------------------------------------------
    def live_track(self) -> dict[str, Any] | None:
        """dj_next_track()'s answer while the set has the air."""
        if self.phase != "live" or self.event is None:
            return None
        return {"id": self.live_id(), "title": EVENT_NAME,
                "artist": self.settings.get("performer") or "live in the studio",
                "album": "PineLive", "seconds": PSEUDO_SECONDS, "live": True,
                "pinelive": True, "path": "", "ext": "mp3"}

    def _take_air(self, why: str) -> None:
        """Arming/fallback -> live: the record goes back to the head of the
        queue and the loop drops the set in its place, at once."""
        with self.lock:
            if self.event is None:
                return
            self._set_phase("live")

        def _on_loop() -> None:
            radio = _app("_RADIO")
            if radio is None:
                return
            now_track = radio.get("now") or {}
            held = ""
            if now_track.get("id") and not now_track.get("pinelive"):
                self.held_record = {k: now_track.get(k) for k in ("id", "title", "artist")}
                held = str(now_track.get("title") or "the record")
                q = radio.setdefault("queue", [])
                if not q or (q[0] or {}).get("id") != now_track.get("id"):
                    q.insert(0, now_track)
            radio["fast_skip"] = True
            skip = _app("dj_skip")
            if callable(skip):
                skip()
            self.note("live", "the set has the air (%s)%s" % (
                why, (" - %s waits at the head of the queue" % held) if held else ""))
        self.on_loop(_on_loop)

    def _give_air(self, why: str) -> None:
        """live -> fallback/stop: the station's own playout comes back now."""

        def _on_loop() -> None:
            radio = _app("_RADIO")
            if radio is None:
                return
            radio["fast_skip"] = True
            skip = _app("dj_skip")
            if callable(skip):
                skip()
        self.on_loop(_on_loop)
        try:
            mark = _app("gap_mark")
            if callable(mark):
                self.on_loop(lambda: mark("pinelive_%s" % why, "MX Live gave the air back: " + why))
        except Exception:  # noqa: BLE001
            pass

    def _fallback(self, code: str, say: str) -> None:
        with self.lock:
            if self.phase != "live":
                return
            self._set_phase("fallback")
            if self.event is not None:
                self.event["fallbacks"] = int(self.event.get("fallbacks") or 0) + 1
        self._give_air(code)
        self.error(code, say)

    # -- the supervisor (a thread: a stalled loop cannot stall the decision) --------------
    def tick(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        _rev = self.event or {}                                     # [plair]
        if (self.armed() and _rev.get("rehearse")
                and now - float(_rev.get("started_at") or now) > REHEARSE_MAX_S):
            self.stop("the on-air test ran its %d minutes" % (REHEARSE_MAX_S // 60))
            return
        if not self.armed() or self.live is None:
            if not self.armed():
                self.mp3.reap()
            return
        s = self.settings
        live = self.live
        stream = _app("STATION_STREAM")
        try:
            if stream is not None:
                stream.ensure_running()
        except Exception:  # noqa: BLE001
            pass
        rx_ago = now - live.rx_at if live.rx_at else None
        run = live.signal_run(now)
        signal_ago = now - live.signal_at if live.signal_at else None
        if self.phase == "arming":
            if run >= min(0.3, float(s["return_seconds"])):
                self._take_air("the input is heard")
            elif now - self.phase_at > float(s["arm_timeout"]):
                with self.lock:
                    self._set_phase("fallback")
                self.error("no_signal", "no sound from the %s in %d s - the station keeps "
                           "the air; the set takes it the moment it is heard" % (
                               "K.O. II" if self.source_kind == "usb" else "sender",
                               int(s["arm_timeout"])))
        elif self.phase == "live":
            if rx_ago is None or rx_ago > float(s["dropout_seconds"]):
                self._fallback("dropout", "the input stopped arriving for %.1f s; the "
                               "station took the air back" % float(s["dropout_seconds"]))
            elif signal_ago is None or signal_ago > float(s["silence_seconds"]):
                self._fallback("silence", "the input was silent for %d s; the station "
                               "took the air back" % int(s["silence_seconds"]))
        elif self.phase == "fallback":
            if run >= float(s["return_seconds"]) and rx_ago is not None and rx_ago < 1.0:
                self._take_air("the input is back")
        if now - self._last_courier_check > 60.0:
            self._last_courier_check = now
            self.courier_reoffer()
            self._disk_check()
        if now - self._saved_at > 5.0:
            self._saved_at = now
            self._save_event()

    def _supervise(self) -> None:
        while True:
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001
                print("[pinelive] supervisor: %s" % exc, flush=True)
            time.sleep(0.25)

    def _disk_check(self) -> None:
        try:
            free = shutil.disk_usage(str(self.data)).free
        except Exception:  # noqa: BLE001
            return
        if free < DISK_LOW_BYTES and time.time() - self._disk_warned > 900:
            self._disk_warned = time.time()
            self.error("disk_low", "only %.1f GB free where the cuts are written" % (free / 1e9))

    # -- the courier -------------------------------------------------------------------
    def dest_folder(self, folder_name: str) -> str:
        fn = _app("export_dir_windows")
        base = fn(self.settings["dest"]) if callable(fn) else str(self.settings["dest"])
        return (base.rstrip("\\") + "\\" + folder_name) if base else ""

    def courier_hand(self, paths: list[Path], folder_name: str) -> list[str]:
        add = _app("courier_add")
        dest = self.dest_folder(folder_name)
        if not callable(add) or not dest:
            self.error("courier_stale", "the courier cannot take the cut (%s)" % (
                "no courier in this build" if not callable(add) else "the destination is not a Windows folder"))
            return []
        ids = []
        for p in paths:
            try:
                row = add(Path(p), dest, "pinelive", name=Path(p).name)
                ids.append(str(row.get("id") or ""))
            except Exception as exc:  # noqa: BLE001
                self.error("courier_stale", "the courier refused %s: %s" % (Path(p).name, exc))
        return ids

    def cut_closed(self, row: dict[str, Any]) -> None:
        try:
            with (self.data / "cuts.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
        except Exception:  # noqa: BLE001
            pass
        self.note("cut", "cut %d closed: %s + %s (%.1f s)" % (
            row["index"], row["input"], row["mix"], row["seconds"]))

    def courier_stats(self) -> dict[str, Any]:
        now = time.time()
        at, memo = self._courier_memo
        if now - at < 2.0 and memo:
            return memo
        out = {"pending": 0, "carried": 0, "failed": 0, "desk_seen_ago": None}
        read = _app("courier_read")
        folder = str((self.event or {}).get("folder") or "")
        try:
            rows = read() if callable(read) else []
            seen = max((float(r.get("done_at") or 0) for r in rows), default=0.0)
            out["desk_seen_ago"] = round(now - seen, 1) if seen else None
            for r in rows:
                if r.get("what") != "pinelive" or (folder and folder not in str(r.get("dest") or "")):
                    continue
                st = r.get("state")
                if st == "pending":
                    out["pending"] += 1
                elif st == "delivered":
                    out["carried"] += 1
                elif st == "failed":
                    out["failed"] += 1
        except Exception:  # noqa: BLE001
            pass
        self._courier_memo = (now, out)
        return out

    def courier_reoffer(self) -> int:
        """The courier ledger keeps its last 200 rows; a long set with the desk
        closed could push a cut off the end before it was carried. Any cut of
        this event whose row has vanished is offered again."""
        read = _app("courier_read")
        if not callable(read) or self.recorder is None or self.event is None:
            return 0
        try:
            known = {str(r.get("id")) for r in read()}
        except Exception:  # noqa: BLE001
            return 0
        again = 0
        for cut in list(self.recorder.cuts):
            if cut.get("event") != self.event_id():
                continue
            ids = list(cut.get("courier") or [])
            if ids and all(i in known for i in ids):
                continue
            folder = self.cuts_root / str(cut.get("folder") or "")
            paths = [folder / cut["input"], folder / cut["mix"]]
            if all(p.is_file() for p in paths):
                cut["courier"] = self.courier_hand(paths, str(cut.get("folder") or ""))
                again += 1
        return again

    # -- reads --------------------------------------------------------------------------
    def event_state(self) -> dict[str, Any]:
        """The System 3 read: cheap, never raises."""
        try:
            ev = None
            if self.event is not None:
                ev = {"id": self.event_id(), "name": EVENT_NAME,
                      "started_at": float(self.event.get("started_at") or 0),
                      "live_seconds": round(self.live_seconds(), 1),
                      "fallbacks": int(self.event.get("fallbacks") or 0)}
            rec = None
            if self.recorder is not None and self.armed():
                rec = {"cut_index": self.recorder.index, "cuts": len(self.recorder.cuts)}
            return {"enabled": bool(self.settings.get("enabled", True)),
                    "armed": self.armed(), "live": self.phase == "live",
                    "phase": self.phase, "event": ev, "source_kind": self.source_kind
                    if self.armed() else None, "since": self.phase_at, "record": rec}
        except Exception:  # noqa: BLE001
            return {"enabled": False, "armed": False, "live": False, "phase": "idle",
                    "event": None, "source_kind": None, "since": 0.0, "record": None}

    def public_video_blocked(self) -> bool:
        return self.armed() and not bool(self.settings.get("tailscale_video"))

    def state(self) -> dict[str, Any]:
        s = self.settings
        h = self.host()
        lv = h.get("level") or {}
        cap = h.get("capture") or {}
        live = self.live
        armed = self.armed()
        dev_rows = ((h.get("devices") or {}).get("usb") or [])
        dev = next((d for d in dev_rows if d.get("id") == self.device), None)
        net = h.get("network") or {}
        if self.source_kind == "network":
            snd = net.get("sender") or {}
            src = {"kind": "network", "device": snd.get("label") or "",
                   "label": snd.get("label") or "a network sender",
                   "rate": snd.get("rate"), "channels": snd.get("channels"),
                   "connected": bool(snd)}
        elif self.source_kind == "usb" or dev is not None:
            src = {"kind": "usb", "device": self.device,
                   "label": s.get("device_label") or (dev or {}).get("name") or self.device,
                   "rate": cap.get("rate") or ((dev or {}).get("rates") or [None])[0],
                   "channels": cap.get("channels") or (dev or {}).get("channels"),
                   "connected": cap.get("state") == "running"}
        else:
            src = {"kind": None, "device": "", "label": "", "rate": None,
                   "channels": None, "connected": False}
        signal_ago = lv.get("signal_ago")
        src.update({"channel_pair": list(s["channel_pair"]),
                    "channel_mode": s["channel_mode"],
                    "channel_applied": h.get("channel_applied"),
                    "level_db": lv.get("level_db"), "peak_db": lv.get("peak_db"),
                    "clipping": bool(lv.get("clipping")),
                    "last_frame_ago": lv.get("last_frame_ago"),
                    "signal": bool(signal_ago is not None and signal_ago < 3.0)})
        rec = self.recorder
        last = rec.cuts[-1] if rec is not None and rec.cuts else None
        folder = str((self.event or {}).get("folder") or "")
        lid = self.live_id()
        art = ("/music/%s/art?t=%s" % (lid, self.sign(lid))) if lid else ""
        radio = _app("_RADIO") or {}
        pl_state = _app("pinelink_state")
        cam_live = False
        try:
            got = pl_state() if callable(pl_state) else {}
            cam_live = bool(got.get("state") == "live" and got.get("fresh"))
        except Exception:  # noqa: BLE001
            pass
        host_addr = (net.get("bound") or ["10.89.1.246"])[0]
        ingest = ""
        if self.source_kind == "network" and self.token:
            ingest = "ws://%s:%d/ingest?t=%s" % (host_addr, INGEST_PORT, self.token)
        why_not = ""
        if armed and not radio.get("on"):
            why_not = "the station's power is off"
        elif armed and callable(_app("radio_paused")) and _app("radio_paused")():
            why_not = "the station is paused - a paused radio is silent, the set included"
        stream = _app("STATION_STREAM")
        return {
            "v": CONTRACT_VERSION,
            "enabled": bool(s.get("enabled", True)),
            "phase": self.phase, "live": self.phase == "live", "armed": armed,
            "event": ({"id": self.event_id(), "name": EVENT_NAME,
                       "started_at": float(self.event.get("started_at") or 0),
                       "live_seconds": round(self.live_seconds(), 1),
                       "fallbacks": int(self.event.get("fallbacks") or 0),
                       "rehearse": bool(self.event.get("rehearse")),      # [plair]
                       "folder": folder} if self.event is not None else None),
            "source": src,
            "recording": {
                "on": bool(armed and s.get("record", True)),
                "cut_seconds": s["cut_seconds"], "format": s["format"],
                "dir": ("data/pinelive/cuts/" + folder) if folder else "",
                "dest": self.dest_folder(folder) if folder else self.dest_folder("").rstrip("\\"),
                "cut_index": rec.index if (rec is not None and armed) else 0,
                "cut_elapsed": round(rec.frames * FRAME_MS / 1000.0, 1) if (rec is not None and armed) else 0.0,
                "last_cut": ({k: last.get(k) for k in ("index", "start", "seconds", "input", "mix")}
                             if last else None),
                "cuts": len([c for c in (rec.cuts if rec else []) if c.get("event") == self.event_id()]),
                "courier": self.courier_stats(),
                "why": rec.why if rec is not None else ""},
            "picture": {"mode": s["picture_mode"], "tailscale_video": bool(s["tailscale_video"]),
                        "cam_live": cam_live,
                        "showing": self.picture.kind if armed else "none",
                        "ads": len(self.picture._ads)},
            "music_paused": self.phase == "live",
            "held_record": self.held_record if self.phase == "live" else None,
            "duck": {"db": s["duck_db"], "attack_ms": s["duck_attack_ms"],
                     "release_ms": s["duck_release_ms"],
                     "now_db": round(_db(1.0 + (10 ** (s["duck_db"] / 20.0) - 1.0) * self.duck_now()), 1)},
            "air": {"stream": bool(self.phase == "live" and self._tapped and stream is not None),
                    "pages": self.phase == "live",
                    "box": bool(self.phase == "live" and (radio.get("music_to") or "here") in ("box", "both")),
                    "why_not": why_not},
            "live_input": live.summary() if live is not None else None,
            "host": {"up": bool(h.get("up")), "age": h.get("age"),
                     "version": h.get("version"), "why": h.get("why") or ""},
            "levels_url": "/api/pinelive/levels?t=" + self.sign("pinelive-levels"),
            "monitor_url": ("/music/%s?t=%s" % (lid, self.sign(lid))) if lid else "",
            "art_url": art,
            "ingest_url": ingest,
            "sender_url": "/api/pinelive/sender?t=" + self.sign("pinelive-sender"),
            "errors": list(self.errors),
        }

    def devices(self) -> dict[str, Any]:
        h = self.host()
        d = h.get("devices") or {}
        net = h.get("network") or {}
        bound = list(net.get("bound") or [])
        lan = next((a for a in bound if not a.startswith("100.")), "10.89.1.246")
        tail = next((a for a in bound if a.startswith("100.")), "")
        return {
            "scanned_at": d.get("scanned_at"),
            "usb": list(d.get("usb") or []),
            "alsa_other": list(d.get("alsa_other") or []),
            "network": {"status": net.get("status") or ("off" if not h.get("up") else "error"),
                        "url": "ws://%s:%d/ingest" % (lan, INGEST_PORT),
                        "tailnet_url": ("ws://%s:%d/ingest" % (tail, INGEST_PORT)) if tail else "",
                        "http_url": "http://%s:%d/ingest.pcm" % (lan, INGEST_PORT),
                        "sender": net.get("sender"), "why": net.get("why") or ""},
            "host": {"up": bool(h.get("up")), "why": h.get("why") or ""},
        }

    def troubleshoot(self, device: str = "") -> dict[str, Any]:
        return troubleshoot(self, device)

    # -- the station's roads ----------------------------------------------------------------
    def snapshot_extra(self) -> dict[str, Any]:
        """What the mixer needs, four times a second. Cheap by contract."""
        live = self.live
        if live is None or not self.armed():
            return {}
        return {"live": live, "live_on_air": self.phase == "live"}

    def clock_extra(self, track: dict[str, Any] | None, away: bool) -> dict[str, Any]:
        if not self.armed():
            return {}
        show = (not away) or bool(self.settings.get("tailscale_video"))
        lid = self.live_id()
        art = ("/music/%s/art?t=%s" % (lid, self.sign(lid))) if lid else ""
        out: dict[str, Any] = {"pinelive": {
            "phase": self.phase, "event": EVENT_NAME,
            "picture": {"kind": (self.picture.kind if show else "none"),
                        "art": art if show else ""}}}
        if (track or {}).get("pinelive"):
            out["live"] = True
            if not show:
                out["art"] = ""
        return out


# ---------------------------------------------------------------------------
# The troubleshooter: an ordered flowchart, graded from what is known.
# ---------------------------------------------------------------------------
def _check(cid: str, label: str, result: str, evidence: str = "", fix: str = "") -> dict[str, Any]:
    return {"id": cid, "label": label, "result": result, "evidence": evidence, "fix": fix}


def troubleshoot(pl: PineLive, device: str = "") -> dict[str, Any]:
    h = pl.host()
    now = time.time()
    source = pl.source_kind if pl.armed() else ("network" if device == "network" else "usb")
    checks: list[dict[str, Any]] = []
    up = bool(h.get("up"))
    checks.append(_check("host", "PineLive host service running",
                         "pass" if up else "fail",
                         ("host_state.json %.1f s old" % h["age"]) if h.get("age") is not None
                         else "no host_state.json", "" if up else
                         "on the DGX: sudo systemctl enable --now pinelive"))
    lv = h.get("level") or {}
    cap = h.get("capture") or {}
    test = h.get("test") or {}
    if source == "usb":
        rows = [d for d in ((h.get("devices") or {}).get("usb") or [])]
        want = device or pl.device or pl.settings.get("device") or ""
        dev = next((d for d in rows if want and want in (d.get("id"), d.get("card_id"))), None)
        if dev is None and not want:
            dev = next((d for d in rows if d.get("capture")), None)
        lsusb = (h.get("devices") or {}).get("lsusb") or {}
        if not up:
            usb_r, ev = "unknown", "the host service is not reporting"
        elif dev is not None:
            usb_r, ev = "pass", "USB %s %s" % (dev.get("usb_id"), dev.get("usb_name"))
        else:
            usb_r, ev = "fail", "no USB audio device (lsusb sees %d devices)" % len(lsusb)
        checks.append(_check("usb", "USB device enumerated", usb_r, ev,
                             "" if usb_r != "fail" else "plug the K.O. II straight into the DGX "
                             "with a data cable, and switch it on"))
        if dev is None:
            for cid, label in (("alsa", "ALSA capture device present"),
                               ("class", "Class compliant (snd-usb-audio)"),
                               ("free", "Not held by another program")):
                checks.append(_check(cid, label, "unknown", "no device yet"))
        else:
            checks.append(_check("alsa", "ALSA capture device present",
                                 "pass" if dev.get("capture") else "fail",
                                 "card %s (%s): %s x%s @ %s" % (dev.get("card"), dev.get("card_id"),
                                                                ",".join(dev.get("formats") or []),
                                                                dev.get("channels"),
                                                                "/".join(str(r) for r in dev.get("rates") or [])),
                                 "" if dev.get("capture") else "this card has no capture side"))
            checks.append(_check("class", "Class compliant (snd-usb-audio)",
                                 "pass" if dev.get("class_compliant") else "fail",
                                 "driver %s" % ("snd-usb-audio" if dev.get("class_compliant") else "not USB-Audio"),
                                 "" if dev.get("class_compliant") else "set the device's USB mode to class-compliant audio"))
            checks.append(_check("free", "Not held by another program",
                                 "fail" if dev.get("status") == "busy" else "pass",
                                 dev.get("hint") or ("pcm %s" % (dev.get("state") or "closed")),
                                 dev.get("hint") if dev.get("status") == "busy" else ""))
        running = cap.get("state") == "running" and cap.get("kind") == "usb"
        if running or test.get("opened"):
            cap_r, ev = "pass", "capture running (%s)" % (cap.get("device") or "")
        elif cap.get("state") == "failed" or (test and test.get("why")):
            cap_r, ev = "fail", str(cap.get("why") or test.get("why") or "")
        else:
            cap_r, ev = "unknown", "not tried yet"
        checks.append(_check("capture", "Capture opens", cap_r, ev,
                             {"fail": "unplug and replug the K.O. II; if it persists, "
                                      "check `arecord -l` on the DGX",
                              "unknown": "press Test"}.get(cap_r, "")))
    else:
        for cid, label in (("usb", "USB device enumerated"), ("alsa", "ALSA capture device present"),
                           ("class", "Class compliant (snd-usb-audio)"),
                           ("free", "Not held by another program")):
            checks.append(_check(cid, label, "skip", "network road"))
        net = h.get("network") or {}
        checks.append(_check("network", "Network ingest listening",
                             "pass" if net.get("bound") else ("unknown" if not up else "fail"),
                             ", ".join("%s:%s" % (a, net.get("port")) for a in net.get("bound") or [])
                             or (net.get("why") or ""),
                             "" if net.get("bound") else "the host could not bind port %d" % INGEST_PORT))
        snd = net.get("sender")
        checks.append(_check("sender", "A sender is connected",
                             "pass" if snd else ("fail" if pl.armed() else "unknown"),
                             ("%s from %s" % (snd.get("label"), snd.get("addr"))) if snd else "nobody connected",
                             "" if snd else "open the sender page on the machine with the interface, "
                             "or run the ffmpeg line it shows"))
        running = bool(snd)
    frame_ago = lv.get("last_frame_ago")
    signal_ago = lv.get("signal_ago")
    level = lv.get("level_db")
    peak = lv.get("peak_db")
    if frame_ago is not None and frame_ago < 2.0:
        if signal_ago is not None and signal_ago < 3.0:
            sig_r, ev = "pass", "%.1f dBFS" % (level if level is not None else -120)
        else:
            sig_r, ev = "fail", "audio arrives but it is silent (%s dBFS)" % level
    elif test.get("max_db") is not None and float(test.get("max_db") or -120) > pl.settings["silence_db"]:
        sig_r, ev = "pass", "test heard %.1f dBFS" % float(test["max_db"])
    elif running:
        sig_r, ev = "fail", "no audio frames for %s s" % frame_ago
    else:
        sig_r, ev = "unknown", "not listening yet"
    checks.append(_check("signal", "Signal present", sig_r, ev,
                         "turn the K.O. II's master volume up and play something; check its "
                         "USB audio output is on" if sig_r == "fail" else ""))
    if peak is None and test.get("max_peak_db") is not None:
        peak = float(test["max_peak_db"])
    if lv.get("clipping") or test.get("clipped"):
        lvl_r, ev, fix = "fail", "clipping (peak %s dBFS)" % peak, "turn the K.O. II down a little"
    elif peak is not None and float(peak) > -120 and float(peak) < -30:
        lvl_r, ev, fix = "fail", "very quiet (peak %.1f dBFS)" % float(peak), \
            "turn the K.O. II up, or raise live gain in PineLive settings"
    elif peak is not None and float(peak) > -120:
        lvl_r, ev, fix = "pass", "peak %.1f dBFS" % float(peak), ""
    else:
        lvl_r, ev, fix = "unknown", "", ""
    checks.append(_check("level", "Level healthy (not too low, not clipping)", lvl_r, ev, fix))
    live = pl.live
    if pl.phase == "live" and live is not None:
        ok = bool(live.rx_at and now - live.rx_at < 1.0)
        checks.append(_check("routed", "Routed to air", "pass" if ok else "fail",
                             "the mixer holds %.0f ms of the set" % live.buffered_ms() if ok
                             else "the station is not receiving the input: %s" % (live.why or "no frames"),
                             "" if ok else "check the host service log: journalctl -u pinelive"))
    elif pl.phase == "fallback":
        last = pl.errors[0] if pl.errors else {}
        checks.append(_check("routed", "Routed to air", "fail",
                             "fallback: %s" % last.get("say", "the input dropped out"),
                             "the set takes the air back by itself once it is heard"))
    elif pl.phase == "arming":
        checks.append(_check("routed", "Routed to air", "unknown", "waiting for the first sound"))
    else:
        checks.append(_check("routed", "Routed to air", "unknown", "MX Live is not running"))
    rec = pl.recorder
    if pl.armed() and rec is not None and pl.settings.get("record", True):
        fresh = bool(rec.last_frame_at and now - rec.last_frame_at < 2.0)
        checks.append(_check("recording", "Cuts being written", "pass" if fresh else "fail",
                             "cut %d, %.0f s in" % (rec.index, rec.frames * FRAME_MS / 1000.0)
                             if fresh else (rec.why or "the mixer is not delivering frames"),
                             "" if fresh else "the stream mixer tap is missing or the mixer "
                             "stopped: GET /api/stream/state"))
    else:
        checks.append(_check("recording", "Cuts being written", "unknown", "not recording"))
    cs = pl.courier_stats()
    seen = cs.get("desk_seen_ago")
    if cs.get("carried") and not cs.get("failed"):
        cr, ev, fix = "pass", "%d carried, %d waiting" % (cs["carried"], cs["pending"]), ""
    elif cs.get("failed"):
        cr, ev, fix = "fail", "%d failed to copy" % cs["failed"], "check the desk can write to %s" % pl.settings["dest"]
    elif cs.get("pending") and (seen is None or seen > 90):
        cr, ev, fix = "fail", "%d waiting; the desk has not taken a job for %s" % (
            cs["pending"], ("%.0f s" % seen) if seen is not None else "ever"), "open Pine Box Desktop"
    else:
        cr, ev, fix = "unknown", "no cut has closed yet", ""
    checks.append(_check("courier", "Desk carrying cuts to QuickSwap", cr, ev, fix))
    first = next((c for c in checks if c["result"] == "fail"), None)
    return {"device": device or pl.device or pl.settings.get("device") or "",
            "source": source, "checks": checks,
            "first_fail": first["id"] if first else "",
            "say": (first["evidence"] if first else
                    "everything that can be checked right now is fine")}


# ---------------------------------------------------------------------------
# The sender page (the network road from a browser).
# ---------------------------------------------------------------------------
SENDER_HTML = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PineLive sender</title>
<style>
:root{--bg:#0b1520;--fg:#dbe6f0;--mut:#8aa0b4;--ok:#5fd38d;--bad:#ff7a7a;--line:#2a4257}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif}
main{max-width:720px;margin:0 auto;padding:16px}
h1{font-size:18px;margin:0 0 12px}
.card{border:1px solid var(--line);border-radius:8px;padding:12px;margin:0 0 12px}
button,select{font:inherit;padding:6px 12px;border-radius:6px;border:1px solid var(--line);background:#132232;color:var(--fg)}
code{display:block;white-space:pre-wrap;word-break:break-all;background:#07101a;padding:8px;border-radius:6px;font-size:12px}
.mut{color:var(--mut)} .ok{color:var(--ok)} .bad{color:var(--bad)}
meter{width:100%;height:14px}
</style></head><body><main>
<h1>PineLive sender - MX Live over the network</h1>
<div class="card" id="secure"></div>
<div class="card"><div>Input: <select id="dev"></select> <button id="go">Send</button> <button id="halt" disabled>Stop</button></div>
<div class="mut" id="say">not sending</div><meter id="lvl" min="-60" max="0" value="-60"></meter></div>
<div class="card"><div class="mut">A native sender (Windows, any machine with ffmpeg) - no browser needed:</div>
<code id="ff"></code></div>
</main><script>
const INGEST = __INGEST__;
const HTTP_URL = __HTTP__;
const $ = (id) => document.getElementById(id);
$("ff").textContent = INGEST ? ('ffmpeg -f dshow -i audio="<your interface>" -ac 2 -ar 48000 -f s16le -method POST "'
  + HTTP_URL + '&rate=48000&channels=2&format=s16le"') : "start MX Live with the network source first";
const secure = window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia;
$("secure").innerHTML = secure ? '<span class="ok">This page may capture audio.</span>'
  : '<span class="bad">This browser will not capture audio on a plain http address.</span> '
  + '<span class="mut">Use the ffmpeg line below, or open this page where the station origin is treated as secure.</span>';
let ws = null, ctx = null, node = null, stream = null;
async function listDevices() {
  if (!secure) return;
  try { await navigator.mediaDevices.getUserMedia({audio: true}).then(s => s.getTracks().forEach(t => t.stop())); } catch (e) {}
  const all = await navigator.mediaDevices.enumerateDevices();
  $("dev").innerHTML = "";
  all.filter(d => d.kind === "audioinput").forEach(d => {
    const o = document.createElement("option"); o.value = d.deviceId; o.textContent = d.label || d.deviceId; $("dev").appendChild(o);
  });
}
const WORKLET = `class P extends AudioWorkletProcessor{process(i){const c=i[0];if(c&&c.length){const n=c[0].length,k=c.length>1?2:1,o=new Int16Array(n*2);
for(let j=0;j<n;j++){const l=c[0][j],r=k>1?c[1][j]:l;o[2*j]=Math.max(-1,Math.min(1,l))*32767;o[2*j+1]=Math.max(-1,Math.min(1,r))*32767;}
this.port.postMessage(o.buffer,[o.buffer]);}return true;}}registerProcessor("pl",P);`;
async function go() {
  if (!secure || !INGEST) return;
  stream = await navigator.mediaDevices.getUserMedia({audio: {deviceId: $("dev").value ? {exact: $("dev").value} : undefined,
    channelCount: 2, echoCancellation: false, noiseSuppression: false, autoGainControl: false}});
  ctx = new AudioContext({latencyHint: "interactive"});
  await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], {type: "text/javascript"})));
  const src = ctx.createMediaStreamSource(stream);
  node = new AudioWorkletNode(ctx, "pl", {channelCount: 2, channelCountMode: "explicit"});
  src.connect(node);
  ws = new WebSocket(INGEST); ws.binaryType = "arraybuffer";
  let pend = [];
  ws.onopen = () => ws.send(JSON.stringify({type: "hello", rate: ctx.sampleRate, channels: 2, format: "s16le",
    label: navigator.platform + " - " + ($("dev").selectedOptions[0] || {}).textContent}));
  ws.onmessage = (m) => { try { const j = JSON.parse(m.data);
    if (j.type === "stat") { $("lvl").value = j.level_db == null ? -60 : j.level_db; $("say").textContent = "sending - " + (j.level_db == null ? "silent" : j.level_db + " dBFS"); }
    if (j.type === "error") { $("say").innerHTML = '<span class="bad">' + j.say + "</span>"; halt(); }
  } catch (e) {} };
  ws.onclose = () => { $("say").textContent = "not sending"; $("go").disabled = false; $("halt").disabled = true; };
  node.port.onmessage = (e) => { pend.push(e.data); if (pend.length >= 8 && ws.readyState === 1) {
    const n = pend.reduce((a, b) => a + b.byteLength, 0), out = new Uint8Array(n); let at = 0;
    pend.forEach(b => { out.set(new Uint8Array(b), at); at += b.byteLength; }); pend = []; ws.send(out.buffer); } };
  $("go").disabled = true; $("halt").disabled = false;
}
function halt() {
  try { ws && ws.close(); } catch (e) {} try { ctx && ctx.close(); } catch (e) {}
  try { stream && stream.getTracks().forEach(t => t.stop()); } catch (e) {}
  ws = ctx = node = stream = null;
}
$("go").onclick = () => go().catch(e => { $("say").innerHTML = '<span class="bad">' + e.message + "</span>"; });
$("halt").onclick = halt;
listDevices();
</script></body></html>"""


def sender_page(pl: PineLive) -> str:
    h = pl.host()
    net = h.get("network") or {}
    lan = next((a for a in (net.get("bound") or []) if not a.startswith("100.")), "10.89.1.246")
    ingest = ""
    http = ""
    if pl.token and pl.source_kind == "network":
        ingest = "ws://%s:%d/ingest?t=%s" % (lan, INGEST_PORT, pl.token)
        http = "http://%s:%d/ingest.pcm?t=%s" % (lan, INGEST_PORT, pl.token)
    return (SENDER_HTML.replace("__INGEST__", json.dumps(ingest))
            .replace("__HTTP__", json.dumps(http)))


# ---------------------------------------------------------------------------
# The one instance, and the doors.
# ---------------------------------------------------------------------------
PL = PineLive()


def event_state() -> dict[str, Any]:
    """System 3's read. Cheap, never raises, never blocks."""
    return PL.event_state()


def on_change(fn: Callable[[dict, dict], Any]) -> None:
    """fn(old, new) on every phase change, from a worker thread."""
    if callable(fn) and fn not in PL.listeners:
        PL.listeners.append(fn)


def live_track() -> dict[str, Any] | None:
    return PL.live_track()


def snapshot_extra() -> dict[str, Any]:
    try:
        return PL.snapshot_extra()
    except Exception:  # noqa: BLE001
        return {}


def clock_extra(track: Any, away: bool) -> dict[str, Any]:
    try:
        return PL.clock_extra(track if isinstance(track, dict) else {}, bool(away))
    except Exception:  # noqa: BLE001
        return {}


def public_video_blocked() -> bool:
    try:
        return PL.public_video_blocked()
    except Exception:  # noqa: BLE001
        return False


def is_live_id(track_id: str) -> bool:
    try:
        return PL.is_live_id(track_id)
    except Exception:  # noqa: BLE001
        return False


async def music_response(track_id: str, request: Any) -> Any:
    """/music/<live id>: the input alone, as an endless mp3 (the signature was
    checked by the /music route before it called this)."""
    from fastapi.responses import Response, StreamingResponse
    if not PL.is_live_id(track_id) or not PL.armed():
        return Response(status_code=404)
    loop = asyncio.get_running_loop()
    ident, q = PL.mp3.attach(loop)

    async def body():
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(q.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    if not PL.armed():
                        return
                    continue
                yield chunk
        finally:
            PL.mp3.detach(ident)

    return StreamingResponse(body(), media_type="audio/mpeg", headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Accept-Ranges": "none", "icy-name": EVENT_NAME})


# [plart] the Album Art folder, through the station's read-only QuickSwap mount.
PLART_DIR = Path(os.environ.get("PINELIVE_ART_DIR")
                 or "/samples/PineBoxRecordings/Live Events/Album Art")
_PLART_MEMO: dict[str, tuple[str, bytes]] = {}


def _plart_cover(event_key: str) -> tuple[str, bytes] | None:
    """(media type, bytes) of this event's cover, or None (then the camera)."""
    got = _PLART_MEMO.get(event_key)
    if got:
        return got
    try:
        files = sorted(p for p in PLART_DIR.iterdir() if p.is_file()
                       and p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
    except OSError:
        return None
    if not files:
        return None
    import random as _random
    pick = _random.Random(event_key).choice(files)
    try:
        data = pick.read_bytes()
    except OSError:
        return None
    kind = {".png": "image/png", ".webp": "image/webp"}.get(pick.suffix.lower(), "image/jpeg")
    _PLART_MEMO.clear()                  # one set at a time; keep only its cover
    _PLART_MEMO[event_key] = (kind, data)
    return _PLART_MEMO[event_key]


async def art_response(track_id: str, request: Any) -> Any:
    """/music/<live id>/art: the picture as a live MJPEG. A public viewer
    (the listener door) gets it only while tailscale_video is on, and an
    open public stream ends within a tick of it being switched off."""
    from fastapi.responses import Response, StreamingResponse
    if not PL.is_live_id(track_id):
        return Response(status_code=404)
    away = request.headers.get("x-pinebox-public") == "1"
    if away and not PL.settings.get("tailscale_video"):
        return Response(PLACEHOLDER_JPEG, media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})
    # [plart] the set's cover: one image from the Album Art folder, picked at
    # random per event (seeded by its id, so it holds for the whole set).
    cover = await asyncio.to_thread(_plart_cover, str(PL.event_id() or track_id))
    if cover:
        return Response(cover[1], media_type=cover[0],
                        headers={"Cache-Control": "no-store"})
    PL.picture.ensure()
    boundary = "pinelivepicture"

    def part(jpeg: bytes) -> bytes:
        return (b"--" + boundary.encode() + b"\r\nContent-Type: image/jpeg\r\n"
                + b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")

    async def body():
        pic = PL.picture
        pic.viewers += 1
        if away:
            pic.public_viewers += 1
        try:
            seq = -1
            while True:
                if away and (not PL.settings.get("tailscale_video") or not PL.armed()):
                    yield part(PLACEHOLDER_JPEG)
                    return
                if not PL.armed():
                    yield part(pic.jpeg)
                    return
                if pic.seq != seq:
                    seq = pic.seq
                    yield part(pic.jpeg)
                await asyncio.sleep(PICTURE_TICK_S)
        finally:
            pic.viewers -= 1
            if away:
                pic.public_viewers -= 1

    return StreamingResponse(body(), media_type="multipart/x-mixed-replace; boundary=" + boundary,
                             headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


def install(app: Any, app_globals: dict[str, Any]) -> None:
    """Register the /api/pinelive routes and boot the event machinery.
    `app_globals` is app.py's globals(): every station function this module
    uses is looked up there when it is needed."""
    global _G
    from fastapi import Header, HTTPException, Request
    from fastapi.responses import HTMLResponse, StreamingResponse

    _G = app_globals                 # live: names defined later are found too
    data_dir = app_globals.get("DATA_DIR")
    if data_dir is not None:
        PL.data = Path(data_dir) / "pinelive"

    def auth(authorization: str | None) -> None:
        app_globals["require_auth"](authorization)

    def answer(got: dict[str, Any]) -> dict[str, Any]:
        out = {"ok": bool(got.get("ok")), "say": str(got.get("say") or ""),
               "code": str(got.get("code") or "")}
        out.update({k: v for k, v in got.items() if k not in out})
        out["state"] = PL.state()
        return out

    async def body_of(request: Request) -> dict[str, Any]:
        try:
            got = await request.json()
        except Exception:  # noqa: BLE001
            return {}
        if not isinstance(got, dict):
            raise HTTPException(status_code=400, detail="a JSON object is expected")
        return got

    @app.on_event("startup")
    async def _pinelive_boot() -> None:
        PL.loop = asyncio.get_running_loop()
        await asyncio.to_thread(PL.boot)

    @app.get("/api/pinelive/state")
    async def pinelive_state_api(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        auth(authorization)
        return PL.state()

    @app.get("/api/pinelive/devices")
    async def pinelive_devices_api(fresh: int = 0,
                                   authorization: str | None = Header(default=None)) -> dict[str, Any]:
        auth(authorization)
        if fresh:
            PL.write_control(scan_at=time.time())
            for _ in range(10):
                await asyncio.sleep(0.25)
                d = PL.devices()
                if float(d.get("scanned_at") or 0) >= float(PL.control.get("scan_at") or 0):
                    break
        return PL.devices()

    @app.get("/api/pinelive/troubleshoot")
    async def pinelive_troubleshoot_api(device: str = "",
                                        authorization: str | None = Header(default=None)) -> dict[str, Any]:
        auth(authorization)
        return PL.troubleshoot(device)

    @app.get("/api/pinelive/settings")
    async def pinelive_settings_get(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        auth(authorization)
        return {"settings": dict(PL.settings), "defaults": dict(DEFAULTS)}

    @app.post("/api/pinelive/settings")
    async def pinelive_settings_post(request: Request,
                                     authorization: str | None = Header(default=None)) -> dict[str, Any]:
        auth(authorization)
        body = await body_of(request)
        new, refused = await asyncio.to_thread(PL.set_settings, body)
        out = answer({"ok": not refused, "code": "" if not refused else "refused",
                      "say": ("saved" if not refused else
                              "saved, except: " + ", ".join(refused))})
        out["settings"] = new
        return out

    @app.post("/api/pinelive/event")
    async def pinelive_event_post(request: Request,
                                  authorization: str | None = Header(default=None)) -> dict[str, Any]:
        auth(authorization)
        body = await body_of(request)
        want = bool(body.get("enabled", True))
        if want and PL.event is not None and PL.event.get("rehearse"):     # [plair]
            return answer({"ok": False, "code": "testing",
                           "say": "an on-air test has the air - end the test first"})
        if not want and PL.event is not None:
            await asyncio.to_thread(PL.stop, "MX Live was switched off")
        await asyncio.to_thread(PL.set_settings, {"enabled": want})
        # [plair] the switch IS the set: on arms it now - the interface takes the
        # broadcast as soon as it sounds, the records come back when it goes
        # quiet or the switch goes off.
        if want and PL.event is None:
            got = await asyncio.to_thread(PL.start, {
                "source": str(body.get("source") or "usb"),
                "device": str(body.get("device") or ""),
                "unpause": bool(body.get("unpause"))})
            return answer(got)
        return answer({"ok": True, "say": "MX Live is %s" % ("on" if want else "off")})

    @app.post("/api/pinelive/start")
    async def pinelive_start_api(request: Request,
                                 authorization: str | None = Header(default=None)) -> dict[str, Any]:
        auth(authorization)
        body = await body_of(request)
        return answer(await asyncio.to_thread(PL.start, body))

    @app.post("/api/pinelive/stop")
    async def pinelive_stop_api(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        auth(authorization)
        return answer(await asyncio.to_thread(PL.stop))

    @app.post("/api/pinelive/test")
    async def pinelive_test_api(request: Request,
                                authorization: str | None = Header(default=None)) -> dict[str, Any]:
        auth(authorization)
        body = await body_of(request)
        return answer(await asyncio.to_thread(PL.test, body))

    @app.get("/api/pinelive/levels")
    async def pinelive_levels_api(request: Request, t: str = "",
                                  authorization: str | None = Header(default=None)) -> Any:
        if not PL.sig_ok("pinelive-levels", t):
            auth(authorization)
        loop = asyncio.get_running_loop()
        ident, q = PL.levels.attach(loop)

        async def body():
            try:
                yield "retry: 2000\n\n"
                yield "event: state\ndata: %s\n\n" % json.dumps(
                    {"phase": PL.phase, "live": PL.phase == "live"})
                while True:
                    try:
                        kind, data = await asyncio.wait_for(q.get(), timeout=5.0)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    yield "event: %s\ndata: %s\n\n" % (kind, data)
            finally:
                PL.levels.detach(ident)

        return StreamingResponse(body(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.get("/api/pinelive/sender")
    async def pinelive_sender_api(t: str = "",
                                  authorization: str | None = Header(default=None)) -> Any:
        if not PL.sig_ok("pinelive-sender", t):
            auth(authorization)
        return HTMLResponse(sender_page(PL), headers={"Cache-Control": "no-store"})

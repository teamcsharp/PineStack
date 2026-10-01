#!/usr/bin/env python3
"""PineLive host: the live input, held on the host and handed to the station.

MX Live puts the operator's instrument on the air. The instrument is a
Teenage Engineering K.O. Sidekick (USB id 2367:9420, ALSA card "EP136") plugged
straight into the DGX; the secondary road is a sender on another machine
streaming PCM over the LAN or the tailnet. Either way the audio arrives HERE,
on the host, and not inside the station's container, for four measured
reasons:

  * THE STATION RESTARTS SEVERAL TIMES A DAY. A capture inside the container
    dies with every restart; this one does not, and its safety master keeps
    recording through the restart (data/pinelive/master/).
  * THE STATION'S GIL STALLS FOR SECONDS (the stream mixer's `behind_worst`
    read 61 s in 80 minutes on 2026-09-28). A real-time ALSA capture that
    has to take that lock to drain its buffer overruns; this process has
    nothing else to do.
  * THE STATION'S EVENT LOOP STALLS (7,276 s in one day, 2026-09-12). The
    network ingest listens here, on its own threads, so a stalled loop can
    never starve the input.
  * NO CONTAINER RECREATE. /dev/snd is bind-mounted into spark-agent, but a
    recreate is the only way to change its device rules, and the host is
    where PipeWire (which may hold the card) is visible.

One normalised stream comes out: s16le, 44100 Hz, 2 channels (a mono or
one-sided input is put in both ears). It feeds:

    ring (120 s) -> http://127.0.0.1:18095/pcm      the station's live bed
                 -> http://127.0.0.1:18095/levels   20 level frames a second
                 -> data/pinelive/master/<event>/   the lossless safety copy

The station tells this process what to do through data/pinelive/control.json
and reads data/pinelive/host_state.json (written every half second - a stale
file is the only way the station can see this process is gone).

    python3 tools/pinelive_host.py            # the service
    python3 tools/pinelive_host.py --status   # print host_state.json
    python3 tools/pinelive_host.py --scan     # print the device scan
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import select
import socket
import struct
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import numpy as np
except Exception:  # noqa: BLE001 - levels and channel repair need it; audio does not
    np = None

VERSION = "1"
ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("PINELIVE_DATA") or (ROOT / "data" / "pinelive"))
CONTROL = DATA / "control.json"
STATE = DATA / "host_state.json"
MASTER = DATA / "master"
LOG_PREFIX = "[pinelive-host] "

RATE = 44100
CHANNELS = 2
SAMPLE_BYTES = 2
FRAME_BYTES = CHANNELS * SAMPLE_BYTES                  # one sample frame
BYTES_PER_S = RATE * FRAME_BYTES                       # 176,400
RING_SECONDS = float(os.environ.get("PINELIVE_RING_SECONDS", "120"))
LEVEL_BLOCK = RATE // 20                               # 50 ms -> 20 frames/s
LEVEL_BANDS = 48
LEVEL_FFT = 4096

DOOR_ADDR = (os.environ.get("PINELIVE_DOOR_HOST", "127.0.0.1"),
             int(os.environ.get("PINELIVE_DOOR_PORT", "18095")))
INGEST_PORT = int(os.environ.get("PINELIVE_INGEST_PORT", "8095"))
# LAN and tailnet, never 0.0.0.0 - the same rule as the Pine Cam's TS door.
INGEST_ADDRS = tuple(a for a in os.environ.get(
    "PINELIVE_INGEST_ADDRS", "10.89.1.246,100.74.95.59").split(",") if a)
INGEST_MAX_MESSAGE = 4 * 1024 * 1024

MASTER_SEGMENT_S = 600.0
MASTER_KEEP_H = 48.0
CAPTURE_REST_S = 3.0
SCAN_EVERY_S = 10.0
STATE_EVERY_S = 0.5
SILENCE_DB = -60.0
KNOWN_NAMES = {"2367:9420": "EP-136 K.O. Sidekick"}   # the operator's interface [plsidekick]; not the EP-133 sampler
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

ALSA_TO_FFMPEG = {"S16_LE": "s16le", "S24_3LE": "s24le", "S32_LE": "s32le",
                  "FLOAT_LE": "f32le", "S16_BE": "s16be", "S32_BE": "s32be"}
INGEST_FORMATS = {"s16le": 2, "f32le": 4, "s32le": 4}


def log(text: str) -> None:
    print(time.strftime("%H:%M:%S ") + LOG_PREFIX + text, flush=True)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".part")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def db(x: float) -> float:
    import math
    return round(20.0 * math.log10(max(float(x), 1e-10)), 1)


# ---------------------------------------------------------------------------
# The ring: absolute byte positions over a circular buffer. Every append is
# a whole number of sample frames, so every position a reader holds is
# frame-aligned.
# ---------------------------------------------------------------------------
class Ring:
    def __init__(self, seconds: float = RING_SECONDS) -> None:
        cap = int(seconds * BYTES_PER_S)
        self.cap = cap - (cap % FRAME_BYTES)
        self.buf = bytearray(self.cap)
        self.end = 0
        self.cond = threading.Condition()

    def append(self, data: bytes) -> None:
        if not data:
            return
        with self.cond:
            if len(data) > self.cap:
                skip = len(data) - self.cap
                self.end += skip
                data = data[skip:]
            n = len(data)
            pos = self.end % self.cap
            first = min(n, self.cap - pos)
            self.buf[pos:pos + first] = data[:first]
            if first < n:
                self.buf[0:n - first] = data[first:]
            self.end += n
            self.cond.notify_all()

    def start(self, cushion_bytes: int) -> int:
        with self.cond:
            cushion_bytes -= cushion_bytes % FRAME_BYTES
            return max(0, self.end - min(cushion_bytes, self.cap // 2))

    def read(self, pos: int, timeout: float, most: int = BYTES_PER_S // 4
             ) -> tuple[bytes, int, int]:
        """(data, next position, bytes lost to the ring turning over)."""
        with self.cond:
            if pos >= self.end:
                self.cond.wait(timeout)
            lost = 0
            floor = self.end - self.cap
            if pos < floor:
                lost = floor - pos
                pos = floor
            n = min(self.end - pos, most)
            n -= n % FRAME_BYTES
            if n <= 0:
                return b"", pos, lost
            at = pos % self.cap
            first = min(n, self.cap - at)
            out = bytes(self.buf[at:at + first])
            if first < n:
                out += bytes(self.buf[0:n - first])
            return out, pos + n, lost


# ---------------------------------------------------------------------------
# Levels: one frame per 50 ms, computed once here, fanned out by the station.
# ---------------------------------------------------------------------------
class Levels:
    def __init__(self) -> None:
        self.cond = threading.Condition()
        self.lines: deque = deque(maxlen=200)
        self.seq = 0
        self.last: dict = {}
        self._window = None
        self._bins: list[tuple[int, int]] = []
        self.clip_at = 0.0
        self.signal_at = 0.0
        self.frame_at = 0.0
        self.recent: deque = deque(maxlen=5)          # the last 250 ms
        self.silence_db = SILENCE_DB
        if np is not None:
            self._window = np.hanning(LEVEL_BLOCK).astype(np.float32)
            self._norm = float(self._window.sum()) / 2.0
            edges = np.logspace(np.log10(30.0), np.log10(16000.0),
                                LEVEL_BANDS + 1)
            hz_per_bin = RATE / float(LEVEL_FFT)
            for i in range(LEVEL_BANDS):
                a = int(np.floor(edges[i] / hz_per_bin))
                b = int(np.ceil(edges[i + 1] / hz_per_bin))
                self._bins.append((max(1, a), max(a + 1, b)))

    def feed(self, block: bytes) -> dict | None:
        """One 50 ms block of normalised stereo PCM -> the frame dict."""
        if np is None or not block:
            return None
        x = np.frombuffer(block, dtype="<i2").astype(np.float32) / 32768.0
        x = x[:(x.size // 2) * 2].reshape(-1, 2)
        if x.shape[0] < 16:
            return None
        left, right = x[:, 0], x[:, 1]
        rms_l = float(np.sqrt(np.mean(left * left)))
        rms_r = float(np.sqrt(np.mean(right * right)))
        rms = float(np.sqrt((rms_l * rms_l + rms_r * rms_r) / 2.0))
        peak = float(np.max(np.abs(x)))
        clip = peak >= 0.9999
        mono = (left + right) * 0.5
        win = self._window if mono.size == LEVEL_BLOCK else np.hanning(mono.size)
        norm = self._norm if mono.size == LEVEL_BLOCK else float(win.sum()) / 2.0
        spec = np.abs(np.fft.rfft(mono * win, n=LEVEL_FFT)) / max(norm, 1e-9)
        bands = bytearray(LEVEL_BANDS)
        for i, (a, b) in enumerate(self._bins):
            seg = spec[a:min(b, spec.size)]
            v = float(seg.max()) if seg.size else 0.0
            bands[i] = int(max(0, min(100, round(db(v) + 100.0))))
        now = time.time()
        self.frame_at = now
        if clip:
            self.clip_at = now
        if db(rms) > self.silence_db:
            self.signal_at = now
        frame = {"t": round(now, 3), "rms": db(rms), "peak": db(peak),
                 "clip": bool(clip), "l": db(rms_l), "r": db(rms_r),
                 "bands": base64.b64encode(bytes(bands)).decode("ascii")}
        self.recent.append((rms, peak))
        with self.cond:
            self.seq += 1
            self.last = frame
            self.lines.append((self.seq, json.dumps(frame, separators=(",", ":"))))
            self.cond.notify_all()
        return frame

    def summary(self) -> dict:
        now = time.time()
        rows = list(self.recent)
        rms = max((r for r, _ in rows), default=0.0)
        peak = max((p for _, p in rows), default=0.0)
        fresh = bool(self.frame_at and now - self.frame_at < 1.0)
        return {"level_db": db(rms) if fresh else None,
                "peak_db": db(peak) if fresh else None,
                "clipping": bool(self.clip_at and now - self.clip_at < 2.0),
                "last_frame_ago": (round(now - self.frame_at, 2)
                                   if self.frame_at else None),
                "signal_ago": (round(now - self.signal_at, 2)
                               if self.signal_at else None),
                "clip_at": self.clip_at, "frame_at": self.frame_at,
                "signal_at": self.signal_at}

    def wait_lines(self, after: int, timeout: float) -> tuple[list[str], int]:
        with self.cond:
            if self.seq <= after:
                self.cond.wait(timeout)
            out = [line for seq, line in self.lines if seq > after]
            return out, self.seq


# ---------------------------------------------------------------------------
# The channel repair: the air is ALWAYS stereo, and a one-sided input is put
# in both ears. `auto` decides from a second of evidence, with hysteresis,
# so a quiet passage on one side never flips it.
# ---------------------------------------------------------------------------
class ChannelMode:
    DEAD_DB = -70.0
    ALIVE_DB = -55.0
    HOLD_S = 1.0

    def __init__(self) -> None:
        self.mode = "auto"
        self.applied = "stereo"
        self._cand = "stereo"
        self._cand_since = 0.0

    def set(self, mode: str) -> None:
        mode = str(mode or "auto")
        self.mode = mode if mode in ("auto", "stereo", "left", "right", "mix") else "auto"

    def apply(self, block: bytes) -> bytes:
        if np is None or not block:
            return block
        mode = self.mode
        if mode == "stereo":
            self.applied = "stereo"
            return block
        x = np.frombuffer(block, dtype="<i2").reshape(-1, 2)
        if mode == "auto":
            f = x.astype(np.float32) / 32768.0
            l_db = db(float(np.sqrt(np.mean(f[:, 0] ** 2))) if f.size else 0.0)
            r_db = db(float(np.sqrt(np.mean(f[:, 1] ** 2))) if f.size else 0.0)
            want = self.applied
            if l_db < self.DEAD_DB and r_db > self.ALIVE_DB:
                want = "right"
            elif r_db < self.DEAD_DB and l_db > self.ALIVE_DB:
                want = "left"
            elif l_db > self.ALIVE_DB and r_db > self.ALIVE_DB:
                want = "stereo"
            now = time.time()
            if want != self._cand:
                self._cand, self._cand_since = want, now
            if want != self.applied and now - self._cand_since >= self.HOLD_S:
                self.applied = want
            mode = self.applied
            if mode == "stereo":
                return block
        self.applied = mode if self.mode != "auto" else self.applied
        y = x.copy()
        if mode == "left":
            y[:, 1] = y[:, 0]
        elif mode == "right":
            y[:, 0] = y[:, 1]
        elif mode == "mix":
            m = ((x[:, 0].astype(np.int32) + x[:, 1].astype(np.int32)) // 2).astype("<i2")
            y[:, 0] = m
            y[:, 1] = m
        return y.tobytes()


# ---------------------------------------------------------------------------
# The safety master: every normalised byte, while armed, in 10-minute WAVs.
# ---------------------------------------------------------------------------
class Master:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.event = ""
        self.fh = None
        self.path: Path | None = None
        self.bytes = 0
        self.opened_at = 0.0
        self.header_at = 0.0
        self.why = ""

    def _open(self, event: str) -> None:
        folder = MASTER / re.sub(r"[^A-Za-z0-9_.-]", "_", event or "unnamed")
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / (time.strftime("%Y%m%d-%H%M%S") + "_input_master.wav")
        self.fh = open(self.path, "w+b")
        self.fh.write(wav_header(0))
        self.bytes = 0
        self.opened_at = time.time()
        self.header_at = self.opened_at
        self.event = event

    def _fix_header(self) -> None:
        if self.fh is None:
            return
        here = self.fh.tell()
        self.fh.seek(0)
        self.fh.write(wav_header(self.bytes))
        self.fh.seek(here)
        self.fh.flush()
        self.header_at = time.time()

    def close(self) -> None:
        with self.lock:
            if self.fh is not None:
                try:
                    self._fix_header()
                    self.fh.close()
                except Exception as exc:  # noqa: BLE001
                    self.why = "close: %s" % exc
            self.fh = None

    def write(self, event: str, data: bytes) -> None:
        with self.lock:
            try:
                if self.fh is not None and (event != self.event or time.time()
                                            - self.opened_at >= MASTER_SEGMENT_S):
                    self._fix_header()
                    self.fh.close()
                    self.fh = None
                if self.fh is None:
                    self._open(event)
                self.fh.write(data)
                self.bytes += len(data)
                if time.time() - self.header_at > 30.0:
                    self._fix_header()
            except Exception as exc:  # noqa: BLE001
                self.why = "write: %s" % exc

    def summary(self) -> dict:
        return {"file": str(self.path.relative_to(ROOT)) if self.path and
                str(self.path).startswith(str(ROOT)) else str(self.path or ""),
                "bytes": self.bytes, "open": self.fh is not None, "why": self.why}


def wav_header(data_bytes: int, rate: int = RATE, channels: int = CHANNELS,
               bits: int = 16) -> bytes:
    block = channels * bits // 8
    size = min(int(data_bytes), 0xFFFFFFFF - 36)
    return (b"RIFF" + struct.pack("<I", 36 + size) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, rate,
                                    rate * block, block, bits)
            + b"data" + struct.pack("<I", size))


def master_trim(keep_hours: float = MASTER_KEEP_H) -> int:
    gone = 0
    floor = time.time() - keep_hours * 3600.0
    try:
        for folder in MASTER.iterdir():
            if not folder.is_dir():
                continue
            files = list(folder.glob("*.wav"))
            if files and max(f.stat().st_mtime for f in files) >= floor:
                continue
            for f in files:
                f.unlink()
                gone += 1
            try:
                folder.rmdir()
            except OSError:
                pass
    except FileNotFoundError:
        pass
    return gone


# ---------------------------------------------------------------------------
# The hub: whichever road is active feeds normalised PCM here.
# ---------------------------------------------------------------------------
class Hub:
    def __init__(self) -> None:
        self.ring = Ring()
        self.levels = Levels()
        self.channels = ChannelMode()
        self.master = Master()
        self.lock = threading.Lock()
        self.generation = 0
        self._carry = b""
        self._level_carry = b""
        self.event = ""
        self.record_master = False
        self.fed_bytes = 0

    def new_generation(self) -> int:
        with self.lock:
            self.generation += 1
            self._carry = b""
            self._level_carry = b""
            return self.generation

    def feed(self, generation: int, data: bytes) -> None:
        with self.lock:
            if generation != self.generation or not data:
                return
            data = self._carry + data
            cut = len(data) - (len(data) % FRAME_BYTES)
            self._carry = data[cut:]
            data = data[:cut]
            if not data:
                return
            data = self.channels.apply(data)
            self.fed_bytes += len(data)
            self.ring.append(data)
            if self.record_master and self.event:
                self.master.write(self.event, data)
            lv = self._level_carry + data
            step = LEVEL_BLOCK * FRAME_BYTES
            while len(lv) >= step:
                self.levels.feed(lv[:step])
                lv = lv[step:]
            self._level_carry = lv


# ---------------------------------------------------------------------------
# Device scan: /proc/asound and lsusb, nothing that opens a device.
# ---------------------------------------------------------------------------
def parse_cards(text: str) -> list[dict]:
    cards = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^\s*(\d+)\s+\[(\S+)\s*\]:\s+(\S+)\s+-\s+(.*)$", line)
        if not m:
            continue
        long = lines[i + 1].strip() if i + 1 < len(lines) else ""
        cards.append({"card": int(m.group(1)), "card_id": m.group(2),
                      "driver": m.group(3), "short": m.group(4).strip(),
                      "long": long})
    return cards


def parse_stream(text: str) -> dict:
    """/proc/asound/cardN/stream0 -> {'capture': {...}, 'playback': {...}}."""
    out: dict = {}
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if line in ("Playback:", "Capture:"):
            section = line[:-1].lower()
            out.setdefault(section, {"formats": [], "channels": 0, "rates": []})
            continue
        if section is None:
            continue
        m = re.match(r"^Format:\s+(\S+)", line)
        if m and m.group(1) not in out[section]["formats"]:
            out[section]["formats"].append(m.group(1))
        m = re.match(r"^Channels:\s+(\d+)", line)
        if m:
            out[section]["channels"] = max(out[section]["channels"], int(m.group(1)))
        m = re.match(r"^Rates:\s+(.*)$", line)
        if m:
            for r in re.findall(r"\d+", m.group(1)):
                if int(r) not in out[section]["rates"] and int(r) >= 8000:
                    out[section]["rates"].append(int(r))
    return out


def parse_pcm(text: str) -> dict[tuple[int, int], dict]:
    out = {}
    for line in text.splitlines():
        m = re.match(r"^(\d+)-(\d+):\s*(.*)$", line.strip())
        if not m:
            continue
        rest = m.group(3)
        out[(int(m.group(1)), int(m.group(2)))] = {
            "name": rest.split(":")[0].strip(),
            "capture": "capture" in rest, "playback": "playback" in rest}
    return out


def parse_lsusb(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        m = re.search(r"ID\s+([0-9a-f]{4}:[0-9a-f]{4})\s+(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def read_text(path: Path | str) -> str:
    try:
        return Path(path).read_text(errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def pcm_status(card: int, device: int, root: Path = Path("/proc/asound")) -> dict:
    text = read_text(root / ("card%d" % card) / ("pcm%dc" % device) / "sub0" / "status")
    if not text:
        return {"busy": False, "state": "unknown"}
    if text.strip() == "closed":
        return {"busy": False, "state": "closed"}
    state = re.search(r"state:\s*(\S+)", text)
    owner = re.search(r"owner_pid\s*:\s*(\d+)", text)
    return {"busy": True, "state": state.group(1) if state else "open",
            "owner_pid": int(owner.group(1)) if owner else 0}


def process_name(pid: int) -> str:
    return read_text("/proc/%d/comm" % pid).strip() if pid else ""


def scan_devices(root: Path = Path("/proc/asound"), lsusb_text: str | None = None,
                 own_pids: tuple[int, ...] = ()) -> dict:
    cards = parse_cards(read_text(root / "cards"))
    pcms = parse_pcm(read_text(root / "pcm"))
    if lsusb_text is None:
        try:
            lsusb_text = subprocess.run(["lsusb"], capture_output=True, text=True,
                                        timeout=5).stdout
        except Exception:  # noqa: BLE001
            lsusb_text = ""
    names = parse_lsusb(lsusb_text)
    usb, other = [], []
    for c in cards:
        n = c["card"]
        usbid = read_text(root / ("card%d" % n) / "usbid").strip()
        stream = parse_stream(read_text(root / ("card%d" % n) / "stream0"))
        cap = stream.get("capture") or {}
        for (card, dev), row in sorted(pcms.items()):
            if card != n:
                continue
            st = pcm_status(n, dev, root) if row["capture"] else {"busy": False}
            busy = bool(st.get("busy")) and int(st.get("owner_pid") or 0) not in own_pids
            is_usb = c["driver"] == "USB-Audio" or bool(usbid)
            status, hint = "ready", ""
            if not row["capture"]:
                status, hint = "no_capture", "this device only plays; it has nothing to record from"
            elif busy:
                owner = process_name(int(st.get("owner_pid") or 0))
                status = "busy"
                hint = ("held by %s (pid %s) - close it, or stop PipeWire from "
                        "using this card" % (owner or "another program",
                                             st.get("owner_pid") or "?"))
            dev_row = {
                "id": "hw:CARD=%s,DEV=%d" % (c["card_id"], dev),
                "card": n, "card_id": c["card_id"], "device": dev,
                "name": KNOWN_NAMES.get(usbid) or c["short"],
                "usb_name": names.get(usbid, c["long"].split(" at ")[0]),
                "usb_id": usbid, "capture": row["capture"],
                "playback": row["playback"],
                "formats": list(cap.get("formats") or []),
                "rates": list(cap.get("rates") or []),
                "channels": int(cap.get("channels") or 0),
                "class_compliant": c["driver"] == "USB-Audio",
                "busy": busy, "state": st.get("state", ""),
                "status": status, "hint": hint}
            (usb if is_usb else other).append(dev_row)
    return {"scanned_at": time.time(), "usb": usb, "alsa_other": other,
            "lsusb": names}


# ---------------------------------------------------------------------------
# The two roads.
# ---------------------------------------------------------------------------
def pair_filter(channels: int, pair: list[int] | tuple[int, ...]) -> str:
    """The ffmpeg pan that takes the operator's pair (1-based) as L/R; a mono
    source goes to both ears."""
    if channels <= 1:
        return "pan=stereo|c0=c0|c1=c0"
    try:
        a, b = int(pair[0]) - 1, int(pair[1]) - 1
    except Exception:  # noqa: BLE001
        a, b = 0, 1
    a = min(max(0, a), channels - 1)
    b = min(max(0, b), channels - 1)
    return "pan=stereo|c0=c%d|c1=c%d" % (a, b)


def normaliser_cmd(ffmpeg: str, fmt: str, rate: int, channels: int,
                   pair: list[int] | tuple[int, ...]) -> list[str]:
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-fflags", "nobuffer", "-probesize", "32", "-analyzeduration", "0",
            "-f", fmt, "-ar", str(int(rate)), "-ac", str(int(channels)),
            "-i", "pipe:0",
            "-af", pair_filter(int(channels), pair) + ",aresample=%d" % RATE,
            "-f", "s16le", "-ar", str(RATE), "-ac", str(CHANNELS),
            "-flush_packets", "1", "pipe:1"]


def ffmpeg_exe() -> str:
    return os.environ.get("PINELIVE_FFMPEG") or "ffmpeg"


class Runner:
    """A normaliser (ffmpeg) whose stdout feeds the hub; subclasses decide
    what feeds its stdin."""

    kind = "none"

    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.gen = hub.new_generation()
        self.proc: subprocess.Popen | None = None
        self.state = "starting"
        self.why = ""
        self.since = time.time()
        self.stopped = False
        self.err_tail: deque = deque(maxlen=6)
        self.bytes_in = 0

    def _pump(self, proc: subprocess.Popen) -> None:
        try:
            fd = proc.stdout.fileno()
            while not self.stopped:
                chunk = os.read(fd, 16384)
                if not chunk:
                    break
                if self.state != "running":
                    self.state = "running"
                self.hub.feed(self.gen, chunk)
        except Exception as exc:  # noqa: BLE001
            self.why = "pump: %s" % exc
        finally:
            if not self.stopped:
                self.state = "failed"
                if not self.why:
                    self.why = self.last_error() or "the capture ended"

    def _errs(self, stream) -> None:
        try:
            for line in iter(stream.readline, b""):
                text = line.decode("utf-8", "replace").strip()
                if text:
                    self.err_tail.append(text[:300])
        except Exception:  # noqa: BLE001
            pass

    def last_error(self) -> str:
        return self.err_tail[-1] if self.err_tail else ""

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None and not self.stopped

    def stop(self) -> None:
        self.stopped = True
        self.state = "stopped"
        for p in self._procs():
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass

    def _procs(self) -> list:
        return [p for p in (self.proc,) if p is not None]

    def summary(self) -> dict:
        return {"kind": self.kind, "state": self.state, "why": self.why,
                "since": self.since,
                "pid": self.proc.pid if self.proc is not None else 0,
                "errors": list(self.err_tail)}


class UsbRunner(Runner):
    """arecord (exact hardware parameters, through plughw only for the sample
    format) into the normaliser. arecord rather than ffmpeg's alsa input:
    its hardware negotiation is explicit, and the K.O. Sidekick offers exactly one
    shape (S32_LE, 8 channels, 48 kHz)."""

    kind = "usb"

    def __init__(self, hub: Hub, device: dict, pair: list[int]) -> None:
        super().__init__(hub)
        self.device = device
        self.pair = list(pair or [1, 2])
        self.rec: subprocess.Popen | None = None
        rates = list(device.get("rates") or [48000])
        self.rate = 48000 if 48000 in rates else (44100 if 44100 in rates else int(rates[0]))
        self.channels = max(1, int(device.get("channels") or 2))
        fmts = list(device.get("formats") or ["S16_LE"])
        # plughw converts the container format only; channels and rate stay
        # the device's own, so the plug layer never resamples or remixes.
        self.alsa_fmt = "S32_LE" if "S32_LE" in fmts or "S24_LE" in fmts or \
            "S24_3LE" in fmts else "S16_LE"
        self.ff_fmt = ALSA_TO_FFMPEG[self.alsa_fmt]
        self.pcm = "plughw:CARD=%s,DEV=%d" % (device.get("card_id"),
                                              int(device.get("device") or 0))

    def cmd(self) -> tuple[list[str], list[str]]:
        rec = ["arecord", "-q", "-D", self.pcm, "-f", self.alsa_fmt,
               "-c", str(self.channels), "-r", str(self.rate), "-t", "raw",
               "--buffer-time=400000", "--period-time=20000"]
        return rec, normaliser_cmd(ffmpeg_exe(), self.ff_fmt, self.rate,
                                   self.channels, self.pair)

    def start(self) -> bool:
        rec_cmd, ff_cmd = self.cmd()
        try:
            self.rec = subprocess.Popen(rec_cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
            self.proc = subprocess.Popen(ff_cmd, stdin=self.rec.stdout,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.rec.stdout.close()          # ffmpeg owns the read end now
        except Exception as exc:  # noqa: BLE001
            self.state, self.why = "failed", "could not start the capture: %s" % exc
            self.stop()
            return False
        for stream in (self.rec.stderr, self.proc.stderr):
            threading.Thread(target=self._errs, args=(stream,), daemon=True).start()
        threading.Thread(target=self._pump, args=(self.proc,), daemon=True,
                         name="pinelive-usb").start()
        log("capture %s: %s | %s" % (self.pcm, " ".join(rec_cmd), " ".join(ff_cmd[-8:])))
        return True

    def alive(self) -> bool:
        return (super().alive() and self.rec is not None
                and self.rec.poll() is None)

    def _procs(self) -> list:
        return [p for p in (self.rec, self.proc) if p is not None]

    def summary(self) -> dict:
        out = super().summary()
        out.update({"device": self.pcm, "rate": self.rate,
                    "channels": self.channels, "format": self.alsa_fmt,
                    "pair": self.pair})
        return out


class NetRunner(Runner):
    """One network sender: its PCM goes into the normaliser's stdin."""

    kind = "network"

    def __init__(self, hub: Hub, fmt: str, rate: int, channels: int,
                 pair: list[int], label: str, addr: str) -> None:
        super().__init__(hub)
        self.fmt, self.rate, self.channels = fmt, int(rate), int(channels)
        self.pair = list(pair or [1, 2])
        self.label, self.addr = label, addr
        self.wlock = threading.Lock()
        self.rx_at = 0.0

    def start(self) -> bool:
        cmd = normaliser_cmd(ffmpeg_exe(), self.fmt, self.rate, self.channels,
                             self.pair if self.channels > 2 else [1, 2])
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception as exc:  # noqa: BLE001
            self.state, self.why = "failed", "could not start the normaliser: %s" % exc
            return False
        threading.Thread(target=self._errs, args=(self.proc.stderr,), daemon=True).start()
        threading.Thread(target=self._pump, args=(self.proc,), daemon=True,
                         name="pinelive-net").start()
        return True

    def push(self, data: bytes) -> bool:
        if self.stopped or self.proc is None or not data:
            return not self.stopped
        try:
            with self.wlock:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
            self.bytes_in += len(data)
            self.rx_at = time.time()
            return True
        except Exception as exc:  # noqa: BLE001
            self.why = "normaliser: %s" % exc
            return False

    def stop(self) -> None:
        try:
            if self.proc is not None and self.proc.stdin:
                self.proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        super().stop()

    def summary(self) -> dict:
        out = super().summary()
        out.update({"label": self.label, "addr": self.addr, "rate": self.rate,
                    "channels": self.channels, "format": self.fmt,
                    "rx_ago": round(time.time() - self.rx_at, 2) if self.rx_at else None,
                    "bytes_in": self.bytes_in})
        return out


# ---------------------------------------------------------------------------
# The supervisor: control.json in, host_state.json out.
# ---------------------------------------------------------------------------
class Host:
    def __init__(self) -> None:
        self.hub = Hub()
        self.lock = threading.RLock()
        self.control: dict = {}
        self.control_mtime = 0.0
        self.runner: Runner | None = None
        self.runner_key = ""
        self.fail_at = 0.0
        self.devices: dict = {"scanned_at": 0.0, "usb": [], "alsa_other": []}
        self.scan_asked = 0.0
        self.door_clients = 0
        self.door_lost = 0
        self.ingest_bound: list[str] = []
        self.ingest_error = ""
        self.net_sender: NetRunner | None = None
        self.test: dict = {}
        self.trimmed_at = 0.0
        self.started = time.time()

    # -- control -----------------------------------------------------------
    def read_control(self) -> dict:
        try:
            m = CONTROL.stat().st_mtime
        except OSError:
            return self.control
        if m != self.control_mtime:
            try:
                got = json.loads(CONTROL.read_text())
                if isinstance(got, dict):
                    self.control = got
                    self.control_mtime = m
            except Exception:  # noqa: BLE001
                pass
        return self.control

    def armed(self, c: dict | None = None) -> bool:
        c = self.control if c is None else c
        return bool(c.get("armed"))

    def testing(self, c: dict | None = None) -> bool:
        c = self.control if c is None else c
        return float(c.get("test_until") or 0) > time.time()

    def token_ok(self, token: str) -> bool:
        want = str(self.control.get("token") or "")
        return bool(want) and hmac.compare_digest(str(token or ""), want)

    def pair(self) -> list[int]:
        got = self.control.get("channel_pair") or [1, 2]
        try:
            return [int(got[0]), int(got[1])]
        except Exception:  # noqa: BLE001
            return [1, 2]

    def pick_device(self) -> dict | None:
        want = str(self.control.get("device") or "")
        rows = [d for d in self.devices.get("usb") or [] if d.get("capture")]
        if want:
            for d in rows + list(self.devices.get("alsa_other") or []):
                if d.get("id") == want or d.get("card_id") == want:
                    return d
            return None
        ready = [d for d in rows if d.get("status") == "ready"]
        # [plpick] Card order is enumeration luck: the operator's K.O. Sidekick
        # sat at card 2 behind a keyboard dongle's 8 kHz mono endpoint at
        # card 1, and first-ready-card armed the dongle. Rank instead:
        # the known interface (KNOWN_NAMES) first, then real audio
        # (stereo, >=44.1 kHz), then the rest; ties keep card order.
        def _rank(d: dict) -> tuple:
            known = 0 if str(d.get("usb_id") or "") in KNOWN_NAMES else 1
            try:
                top = max(int(r) for r in (d.get("rates") or [0]))
            except Exception:  # noqa: BLE001
                top = 0
            real = 0 if (int(d.get("channels") or 0) >= 2
                         and top >= 44100) else 1
            try:
                card = int(d.get("card") or 0)
            except Exception:  # noqa: BLE001
                card = 0
            return (known, real, card)
        return (sorted(ready, key=_rank) or sorted(rows, key=_rank)
                or [None])[0]

    def own_pids(self) -> tuple[int, ...]:
        r = self.runner
        pids = []
        if isinstance(r, UsbRunner) and r.rec is not None:
            pids.append(r.rec.pid)
        return tuple(pids)

    def rescan(self) -> None:
        try:
            self.devices = scan_devices(own_pids=self.own_pids())
        except Exception as exc:  # noqa: BLE001
            self.devices = {"scanned_at": time.time(), "usb": [], "alsa_other": [],
                            "why": "scan failed: %s" % exc}

    def reconcile(self) -> None:
        c = self.read_control()
        self.hub.channels.set(str(c.get("channel_mode") or "auto"))
        try:
            self.hub.levels.silence_db = float(c.get("silence_db") or SILENCE_DB)
        except Exception:  # noqa: BLE001
            pass
        want_on = self.armed(c) or self.testing(c)
        self.hub.event = str(c.get("event_id") or "")
        self.hub.record_master = bool(self.armed(c) and c.get("master", True))
        if not self.hub.record_master:
            self.hub.master.close()
        source = str(c.get("source") or "")
        if float(c.get("scan_at") or 0) > self.scan_asked:
            self.scan_asked = float(c.get("scan_at") or 0)
            self.rescan()
        with self.lock:
            if not want_on or source != "usb":
                if isinstance(self.runner, UsbRunner):
                    self.runner.stop()
                    self.runner = None
                    self.runner_key = ""
                    log("capture stopped (%s)" % ("not armed" if not want_on
                                                  else "source is " + (source or "none")))
                if self.net_sender is not None and (not want_on or source != "network"):
                    self.net_close(self.net_sender)
                if want_on and source == "network":
                    self.runner = self.net_sender
                return
            dev = self.pick_device()
            if dev is None:
                self.test_note(opened=False, why="no capture device")
                if self.runner is not None and self.runner.kind == "usb":
                    self.runner.stop()
                self.runner = None
                self.runner_key = ""
                return
            if self.net_sender is not None:
                self.net_close(self.net_sender)     # the road is USB now
            key = json.dumps([dev.get("id"), self.pair()])
            r = self.runner
            if r is not None and r.kind == "usb":
                if self.runner_key == key and r.alive():
                    return
                died = self.runner_key == key
                r.stop()
                self.runner = None
                if died:
                    self.fail_at = time.time()
                    log("capture ended: %s" % (r.why or r.last_error() or "no reason"))
            elif r is not None:
                self.runner = None
            # A capture that just died rests before the next try: an unplugged
            # device fails at once, and a hot retry loop helps nobody.
            if self.runner_key == key and time.time() - self.fail_at < CAPTURE_REST_S:
                return
            if dev.get("status") == "busy":
                self.runner = None
                self.runner_key = key
                self.fail_at = time.time()
                self.test_note(opened=False, why=dev.get("hint") or "the device is busy")
                return
            runner = UsbRunner(self.hub, dev, self.pair())
            self.runner = runner
            self.runner_key = key
            if not runner.start():
                self.fail_at = time.time()

    def test_note(self, **fields) -> None:
        if self.testing():
            self.test.update(fields)

    # -- the network road ---------------------------------------------------
    def net_open(self, fmt: str, rate: int, channels: int, label: str,
                 addr: str) -> tuple[NetRunner | None, str, str]:
        c = self.control
        if not (self.armed(c) or self.testing(c)):
            return None, "not_armed", "MX Live is not running - start it with the network source first"
        if str(c.get("source") or "") != "network":
            return None, "not_network", "the event is on the USB road; switch the source to network first"
        with self.lock:
            if self.net_sender is not None and not self.net_sender.stopped:
                return None, "ingest_busy", "another sender is already connected (%s)" % (
                    self.net_sender.label or self.net_sender.addr)
            runner = NetRunner(self.hub, fmt, rate, channels, self.pair(), label, addr)
            if not runner.start():
                return None, "ingest_format", runner.why
            self.net_sender = runner
            self.runner = runner
            self.runner_key = "network"
        log("network sender %s (%s) %s %d Hz x%d" % (label, addr, fmt, rate, channels))
        return runner, "", ""

    def net_close(self, runner: NetRunner) -> None:
        runner.stop()
        with self.lock:
            if self.net_sender is runner:
                self.net_sender = None
            if self.runner is runner:
                self.runner = None
                self.runner_key = ""
        log("network sender %s left" % (runner.label or runner.addr))

    # -- state ---------------------------------------------------------------
    def state(self) -> dict:
        c = self.control
        r = self.runner
        lv = self.hub.levels.summary()
        net = self.net_sender
        return {
            "at": time.time(), "version": VERSION, "pid": os.getpid(),
            "up_since": self.started,
            "armed": self.armed(c), "testing": self.testing(c),
            "event_id": str(c.get("event_id") or ""),
            "source": str(c.get("source") or ""),
            "device": str(c.get("device") or ""),
            "channel_pair": self.pair(),
            "channel_mode": self.hub.channels.mode,
            "channel_applied": self.hub.channels.applied,
            "capture": r.summary() if r is not None else {"kind": "none", "state": "idle"},
            "level": lv,
            "ring": {"end": self.hub.ring.end,
                     "seconds": round(self.hub.ring.end / float(BYTES_PER_S), 1),
                     "fed_bytes": self.hub.fed_bytes},
            "door": {"addr": "%s:%d" % DOOR_ADDR, "clients": self.door_clients,
                     "lost_bytes": self.door_lost},
            "network": {"port": INGEST_PORT, "bound": list(self.ingest_bound),
                        "why": self.ingest_error,
                        "status": ("connected" if net is not None and not net.stopped
                                   else "listening" if self.ingest_bound else "error"),
                        "sender": net.summary() if net is not None and not net.stopped else None},
            "devices": self.devices,
            "master": self.hub.master.summary(),
            "test": dict(self.test),
        }

    def write_state(self) -> None:
        try:
            atomic_write(STATE, json.dumps(self.state(), indent=1))
        except Exception as exc:  # noqa: BLE001
            log("state write failed: %s" % exc)

    def loop(self) -> None:
        last_state = 0.0
        last_scan = 0.0
        was_testing = False
        while True:
            now = time.time()
            try:
                if now - last_scan >= SCAN_EVERY_S:
                    last_scan = now
                    self.rescan()
                testing = self.testing(self.read_control())
                if testing and not was_testing:
                    self.test = {"since": now, "until": float(self.control.get("test_until") or 0),
                                 "device": str(self.control.get("device") or "")}
                was_testing = testing
                self.reconcile()
                if testing:
                    lv = self.hub.levels.summary()
                    r = self.runner
                    self.test.update({
                        "opened": bool(r is not None and r.state == "running") or bool(self.test.get("opened")),
                        "why": (r.why or r.last_error()) if r is not None else self.test.get("why", ""),
                        "max_db": max(float(self.test.get("max_db") or -120.0),
                                      float(lv.get("level_db") or -120.0)),
                        "max_peak_db": max(float(self.test.get("max_peak_db") or -120.0),
                                           float(lv.get("peak_db") or -120.0)),
                        "clipped": bool(self.test.get("clipped")) or bool(lv.get("clipping"))})
                if now - self.trimmed_at > 600:
                    self.trimmed_at = now
                    master_trim()
                if now - last_state >= STATE_EVERY_S:
                    last_state = now
                    self.write_state()
            except Exception as exc:  # noqa: BLE001
                log("loop: %s" % exc)
            time.sleep(0.2)


HOST: list[Host] = []


# ---------------------------------------------------------------------------
# WebSocket, the minimum: RFC 6455 frames, text + binary + close + ping.
# ---------------------------------------------------------------------------
def ws_accept(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()


def ws_unmask(payload: bytes, mask: bytes) -> bytes:
    if not payload:
        return payload
    n = len(payload)
    reps = (mask * (n // 4 + 1))[:n]
    return (int.from_bytes(payload, "little") ^ int.from_bytes(reps, "little")
            ).to_bytes(n, "little")


def ws_read_frame(read) -> tuple[int, bytes, bool]:
    """-> (opcode, payload, fin). `read(n)` must return exactly n bytes or
    raise/return short at EOF."""
    head = read(2)
    if len(head) < 2:
        raise EOFError("closed")
    b1, b2 = head[0], head[1]
    fin = bool(b1 & 0x80)
    opcode = b1 & 0x0F
    masked = bool(b2 & 0x80)
    n = b2 & 0x7F
    if n == 126:
        n = struct.unpack(">H", read(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", read(8))[0]
    if n > INGEST_MAX_MESSAGE:
        raise ValueError("message too large (%d bytes)" % n)
    mask = read(4) if masked else b""
    payload = read(n) if n else b""
    if len(payload) < n:
        raise EOFError("short frame")
    if masked:
        payload = ws_unmask(payload, mask)
    return opcode, payload, fin


def ws_frame(opcode: int, payload: bytes = b"") -> bytes:
    n = len(payload)
    if n < 126:
        head = struct.pack(">BB", 0x80 | opcode, n)
    elif n < 65536:
        head = struct.pack(">BBH", 0x80 | opcode, 126, n)
    else:
        head = struct.pack(">BBQ", 0x80 | opcode, 127, n)
    return head + payload


class _Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        if not isinstance(sys.exc_info()[1], OSError):
            super().handle_error(request, client_address)


def _json(handler: BaseHTTPRequestHandler, code: int, body: dict) -> None:
    raw = json.dumps(body).encode() + b"\n"
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(raw)


class DoorHandler(BaseHTTPRequestHandler):
    """127.0.0.1 only: the station's side. No token - the loopback IS the
    permission (the container shares the host's network namespace)."""
    protocol_version = "HTTP/1.0"
    timeout = 30.0

    def log_message(self, *_a) -> None:
        pass

    def do_GET(self) -> None:
        host = HOST[0] if HOST else None
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if host is None:
            _json(self, 503, {"error": "starting"})
        elif url.path == "/pcm":
            self._pcm(host, q)
        elif url.path == "/levels":
            self._levels(host)
        elif url.path == "/state":
            _json(self, 200, host.state())
        elif url.path == "/health":
            _json(self, 200, {"ok": True, "version": VERSION})
        else:
            _json(self, 404, {"error": "GET /pcm, /levels, /state, /health"})

    def _pcm(self, host: Host, q: dict) -> None:
        try:
            cushion_ms = max(0.0, min(5000.0, float((q.get("cushion_ms") or ["300"])[0])))
        except ValueError:
            cushion_ms = 300.0
        ring = host.hub.ring
        pos = ring.start(int(cushion_ms / 1000.0 * BYTES_PER_S))
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("X-PineLive-Format", "s16le")
        self.send_header("X-PineLive-Rate", str(RATE))
        self.send_header("X-PineLive-Channels", str(CHANNELS))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        host.door_clients += 1
        idle = 0.0
        try:
            while True:
                data, pos, lost = ring.read(pos, 1.0)
                if lost:
                    host.door_lost += lost
                if data:
                    idle = 0.0
                    self.wfile.write(data)
                    continue
                idle += 1.0
                # Nothing to send cannot notice a reader that left; ask the
                # socket directly every few quiet seconds.
                if idle >= 3.0:
                    idle = 0.0
                    ready, _, _ = select.select([self.connection], [], [], 0)
                    if ready and not self.connection.recv(1, socket.MSG_PEEK):
                        break
        except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
            pass
        finally:
            host.door_clients -= 1

    def _levels(self, host: Host) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        seq = host.hub.levels.seq
        try:
            while True:
                lines, seq = host.hub.levels.wait_lines(seq, 5.0)
                if lines:
                    self.wfile.write(("\n".join(lines) + "\n").encode())
                else:
                    self.wfile.write(b"\n")           # keep-alive
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


class IngestHandler(BaseHTTPRequestHandler):
    """LAN + tailnet: the network road. Token-guarded; one sender at a time."""
    protocol_version = "HTTP/1.1"
    timeout = 20.0

    def log_message(self, *_a) -> None:
        pass

    def _host(self) -> Host | None:
        return HOST[0] if HOST else None

    def do_GET(self) -> None:
        url = urlparse(self.path)
        host = self._host()
        if url.path == "/health":
            _json(self, 200, {"ok": True, "version": VERSION})
            return
        if url.path != "/ingest" or host is None:
            _json(self, 404, {"error": "GET /ingest (WebSocket) or POST /ingest.pcm"})
            return
        host.read_control()
        q = parse_qs(url.query)
        if not host.token_ok((q.get("t") or [""])[0]):
            _json(self, 403, {"type": "error", "code": "ingest_auth",
                              "say": "the ingest token is wrong or has rotated"})
            return
        key = self.headers.get("Sec-WebSocket-Key") or ""
        if "websocket" not in (self.headers.get("Upgrade") or "").lower() or not key:
            _json(self, 400, {"error": "a WebSocket upgrade is required"})
            return
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", ws_accept(key))
        self.end_headers()
        self.wfile.flush()
        self.close_connection = True
        self._ws(host)

    def _send(self, obj: dict) -> None:
        self.wfile.write(ws_frame(0x1, json.dumps(obj).encode()))
        self.wfile.flush()

    def _ws(self, host: Host) -> None:
        runner: NetRunner | None = None
        addr = self.client_address[0]
        self.connection.settimeout(30.0)
        read = self.rfile.read
        parts: list[bytes] = []
        part_op = 0
        last_stat = time.time()
        try:
            while True:
                opcode, payload, fin = ws_read_frame(read)
                if opcode == 0x0:
                    parts.append(payload)
                    if not fin:
                        continue
                    payload, opcode = b"".join(parts), part_op
                    parts = []
                elif opcode in (0x1, 0x2) and not fin:
                    parts, part_op = [payload], opcode
                    continue
                if opcode == 0x8:
                    try:
                        self.wfile.write(ws_frame(0x8, payload[:2]))
                    except OSError:
                        pass
                    return
                if opcode == 0x9:
                    self.wfile.write(ws_frame(0xA, payload))
                    continue
                if opcode == 0xA:
                    continue
                if opcode == 0x1:
                    try:
                        hello = json.loads(payload.decode("utf-8"))
                    except Exception:  # noqa: BLE001
                        hello = {}
                    if hello.get("type") != "hello":
                        continue
                    if runner is not None:
                        self._send({"type": "error", "code": "ingest_format",
                                    "say": "one hello per connection"})
                        continue
                    fmt, rate, ch, why = ingest_params(hello)
                    if why:
                        self._send({"type": "error", "code": "ingest_format", "say": why})
                        return
                    runner, code, say = host.net_open(
                        fmt, rate, ch, str(hello.get("label") or "a sender")[:80], addr)
                    if runner is None:
                        self._send({"type": "error", "code": code, "say": say})
                        return
                    self._send({"type": "ok", "rate": RATE, "channels": CHANNELS})
                elif opcode == 0x2:
                    if runner is None:
                        self._send({"type": "error", "code": "ingest_format",
                                    "say": "send the hello first"})
                        return
                    if not runner.push(payload):
                        self._send({"type": "error", "code": "ingest_format",
                                    "say": runner.why or "the normaliser stopped"})
                        return
                if time.time() - last_stat >= 1.0 and runner is not None:
                    last_stat = time.time()
                    lv = host.hub.levels.summary()
                    self._send({"type": "stat", "level_db": lv.get("level_db"),
                                "peak_db": lv.get("peak_db"),
                                "rx_ms": int(runner.bytes_in * 1000.0 / max(
                                    1, runner.rate * runner.channels *
                                    INGEST_FORMATS.get(runner.fmt, 2)))})
        except (EOFError, ConnectionResetError, BrokenPipeError, OSError, ValueError):
            pass
        finally:
            if runner is not None:
                host.net_close(runner)

    def do_POST(self) -> None:
        self._http_ingest()

    def do_PUT(self) -> None:
        self._http_ingest()

    def _http_ingest(self) -> None:
        url = urlparse(self.path)
        host = self._host()
        if url.path != "/ingest.pcm" or host is None:
            _json(self, 404, {"error": "POST /ingest.pcm?t=&rate=&channels=&format="})
            return
        host.read_control()
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if not host.token_ok(q.get("t", "")):
            _json(self, 403, {"code": "ingest_auth", "say": "the ingest token is wrong"})
            return
        fmt, rate, ch, why = ingest_params(q)
        if why:
            _json(self, 400, {"code": "ingest_format", "say": why})
            return
        runner, code, say = host.net_open(fmt, rate, ch, q.get("label", "http sender")[:80],
                                          self.client_address[0])
        if runner is None:
            _json(self, 409, {"code": code, "say": say})
            return
        self.connection.settimeout(30.0)
        try:
            if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
                while True:
                    size_line = self.rfile.readline(64)
                    if not size_line:
                        break
                    size = int(size_line.split(b";")[0].strip() or b"0", 16)
                    if size == 0:
                        self.rfile.readline(8)
                        break
                    data = self.rfile.read(size)
                    self.rfile.readline(8)
                    if not runner.push(data):
                        break
            else:
                left = int(self.headers.get("Content-Length") or 0) or (1 << 62)
                while left > 0:
                    data = self.rfile.read1(min(65536, left)) if hasattr(
                        self.rfile, "read1") else self.rfile.read(min(65536, left))
                    if not data:
                        break
                    left -= len(data)
                    if not runner.push(data):
                        break
            _json(self, 200, {"ok": True, "bytes": runner.bytes_in})
        except (ConnectionResetError, BrokenPipeError, OSError, ValueError):
            pass
        finally:
            host.net_close(runner)


def ingest_params(src: dict) -> tuple[str, int, int, str]:
    fmt = str(src.get("format") or "s16le").lower()
    if fmt not in INGEST_FORMATS:
        return "", 0, 0, "format must be one of %s" % ", ".join(sorted(INGEST_FORMATS))
    try:
        rate = int(float(src.get("rate") or 48000))
        ch = int(float(src.get("channels") or 2))
    except (TypeError, ValueError):
        return "", 0, 0, "rate and channels must be numbers"
    if not 8000 <= rate <= 96000:
        return "", 0, 0, "rate must be 8000..96000"
    if not 1 <= ch <= 8:
        return "", 0, 0, "channels must be 1..8"
    return fmt, rate, ch, ""


def serve(addr: tuple[str, int], handler, name: str) -> _Server | None:
    try:
        srv = _Server(addr, handler)
    except OSError as exc:
        log("cannot bind %s %s:%d (%s)" % (name, addr[0], addr[1], exc))
        return None
    threading.Thread(target=srv.serve_forever, daemon=True, name=name).start()
    log("serving %s on %s:%d" % (name, addr[0], addr[1]))
    return srv


def bind_ingest(host: Host) -> None:
    """The LAN and tailnet addresses, retried every 30 s - tailscale can come
    up after this service does."""
    want = list(INGEST_ADDRS)
    while want:
        for a in list(want):
            if serve((a, INGEST_PORT), IngestHandler, "ingest") is not None:
                host.ingest_bound.append(a)
                want.remove(a)
        host.ingest_error = ("not bound on %s yet" % ", ".join(want)) if want else ""
        if want:
            time.sleep(30.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--scan", action="store_true")
    args = ap.parse_args()
    if args.status:
        print(read_text(STATE) or '{"state": "never-run"}')
        return
    if args.scan:
        print(json.dumps(scan_devices(), indent=1))
        return
    DATA.mkdir(parents=True, exist_ok=True)
    host = Host()
    HOST.append(host)
    if serve(DOOR_ADDR, DoorHandler, "door") is None:
        log("the station door would not open - exiting so systemd retries")
        sys.exit(2)
    threading.Thread(target=bind_ingest, args=(host,), daemon=True,
                     name="ingest-bind").start()
    log("PineLive host %s up (data %s)" % (VERSION, DATA))
    host.loop()


if __name__ == "__main__":
    main()

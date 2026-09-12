"""Device-format audio gain for Nabu, independent of its physical master dial."""
from __future__ import annotations

import hashlib
import base64
import json
import math
from pathlib import Path
import subprocess
import threading
import time
import uuid

# Generated and decoded in the native-format regression: 9,600 zero samples,
# mono PCM16 at 48 kHz. Keep emergency channel silence independent of a long
# music conversion or the availability of a model/encoder at button-press time.
_SILENCE_FLAC = base64.b64decode(
    "ZkxhQwAAACISABIAAAALAAANC7gA8AAAJYAoHR32pMrimxJ91hf+RhzkBAAAFAwAAABMYXZmNjEuMS4xMDAAAAAAgQAAAP/4WggAgQAAACuI//haCAGGAAAAR/D/+HoIAgF/fgAAADuk")
_SILENCE_KEY = hashlib.sha256(_SILENCE_FLAC).hexdigest()[:32] + ".flac"


def level(settings, stream):
    """Music is 0..1 amplitude; speech's midpoint is unity, top is +6 dB."""
    if stream == "music":
        raw, fallback = settings.get("nabu_music_level", settings.get("music_box_level", .35)), .35
    elif stream in ("voice", "reply"):
        raw, fallback = settings.get("nabu_" + stream + "_level", .5), .5
    else:
        raise ValueError("Unknown Nabu audio stream")
    try:
        value = float(raw)
        if not math.isfinite(value):
            value = fallback
    except (TypeError, ValueError):
        value = fallback
    return max(0.0, min(1.0, value))


def gain(settings, stream):
    return level(settings, stream) * (1.0 if stream == "music" else 2.0)


class NabuAudioCache:
    """Atomic FLAC derivatives; original recordings are never modified."""
    def __init__(self, directory, *, max_files=96, max_bytes=256 * 1024 * 1024,
                 runner=subprocess.run, clock=time.time):
        self.directory = Path(directory)
        self.max_files, self.max_bytes = max_files, max_bytes
        self.runner, self.clock = runner, clock
        self.lock = threading.Lock()
        self.silence_lock = threading.Lock()

    def prepare(self, source, amplitude, *, channels=1, offset=0.0, valid=lambda: True):
        source = Path(source).resolve()
        amplitude, offset = float(amplitude), float(offset)
        if (not math.isfinite(amplitude) or not 0 <= amplitude <= 2
                or not math.isfinite(offset) or offset < 0 or channels not in (1, 2)):
            raise ValueError("Invalid device audio parameters")
        stat = source.stat()
        if not source.is_file() or stat.st_size <= 0:
            raise ValueError("Source recording is missing or empty")
        signature = [str(source), stat.st_size, stat.st_mtime_ns,
                     round(amplitude, 4), channels, round(offset, 3), "flac48-s16-v1"]
        key = hashlib.sha256(json.dumps(signature).encode()).hexdigest()[:32] + ".flac"
        target = self.directory / key
        with self.lock:
            if not valid():
                raise ValueError("Audio setting was superseded")
            if target.is_file() and target.stat().st_size > 42:
                target.touch()
                return target
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = self.directory / (key + "." + uuid.uuid4().hex + ".part")
            import imageio_ffmpeg
            import mutagen
            source_info = mutagen.File(source)
            source_channels = getattr(getattr(source_info, "info", None), "channels", 0)
            # Limit at the final sample rate: resampling after the limiter can
            # otherwise create small peaks above its requested ceiling.
            filters = f"aresample=48000,volume={amplitude:.4f},alimiter=limit=0.98:level=false:latency=true"
            if channels == 2 and source_channels == 1:
                # Default mono-to-stereo rematrixing attenuates each channel
                # by 3 dB. Duplicating mono preserves the requested gain.
                filters += ",pan=stereo|c0=c0|c1=c0"
            command = [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error",
                       "-threads", "1", "-ss", f"{offset:.3f}", "-i", str(source),
                       "-map", "0:a:0", "-vn", "-map_metadata", "-1",
                       "-ac", str(channels), "-ar", "48000", "-sample_fmt", "s16",
                       "-af", filters,
                       "-c:a", "flac", "-compression_level", "0", "-threads", "1",
                       "-f", "flac", "-y", str(temporary)]
            try:
                result = self.runner(command, capture_output=True, timeout=45, check=False)
                if result.returncode != 0:
                    raise ValueError("Device audio conversion failed")
                from mutagen.flac import FLAC
                info = FLAC(temporary).info
                if not (info.sample_rate == 48000 and info.channels == channels
                        and info.bits_per_sample == 16 and info.length > 0):
                    raise ValueError("Device audio conversion returned an invalid format")
                fresh = source.stat()
                if (fresh.st_size, fresh.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns) or not valid():
                    raise ValueError("Source or setting changed during device conversion")
                temporary.replace(target)
                self._sweep(target)
                return target
            finally:
                temporary.unlink(missing_ok=True)

    def silence(self):
        """A short silent replacement clears an owned announcement pipeline."""
        target = self.directory / _SILENCE_KEY
        with self.silence_lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            if not target.is_file() or target.read_bytes() != _SILENCE_FLAC:
                temporary = target.with_suffix("." + uuid.uuid4().hex + ".part")
                try:
                    temporary.write_bytes(_SILENCE_FLAC)
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
        return target

    def _sweep(self, current):
        """Bound disposable derivatives without deleting original audio."""
        files = sorted((p for p in self.directory.glob("*.flac") if p.name != _SILENCE_KEY), key=lambda p: p.stat().st_mtime,
                       reverse=True)
        total = 0
        for i, path in enumerate(files):
            size = path.stat().st_size
            total += size
            if path != current and (i >= self.max_files or total > self.max_bytes):
                # Active device readers have already opened these files; on
                # Linux their descriptor remains valid through cache eviction.
                path.unlink(missing_ok=True)

"""Tablet recording edits: retained originals, bounded analysis and copied exports.

This module never imports the station runtime or touches its playback state.
Heavy media work runs on one worker with a bounded queue.
"""
from __future__ import annotations

import base64
import concurrent.futures
import hashlib                                              # [#1242]
import hmac                                                 # [#1242]
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

IDENTIFIER = re.compile(r"[0-9a-f]{32}\Z")
MAX_UPLOAD = 256 * 1024 * 1024
MAX_DURATION = 20 * 60 + 5
MAX_PIXELS = 4096 * 2160
MAX_OVERLAY = 12 * 1024 * 1024
ASSETS = {"video-editor.html", "video-editor.js", "video-editor.css", "video-edit-model.js"}


# --- [#1242] A SAVE THAT CANNOT END IN THE WORD "UNAUTHORIZED" -------------
#
# WHERE THE EDITOR RUNS WITHOUT THE KEY. hot-corners.js openVideoEditor()
# loads this station's /video-editor/?source=<32 hex> in an IFRAME. On the
# PineTab the panel is the parent and is served from this same origin, so the
# editor walks up to window.parent.pineDesktop and posts through the native
# bridge, which carries the key. On the DESK the parent is a file:// Electron
# document: the iframe is cross-origin, the preload is not injected into
# subframes (no nodeIntegrationInSubFrames anywhere in main.js), and
# window.__PINE_VIDEO_EDITOR_KEY — the last resort the page reaches for — is
# never assigned in the whole tree. So the POST went out with no Authorization
# header at all and this module answered 401 "Unauthorized", which the footer
# printed verbatim. Same for any plain browser opening the page over the LAN.
#
# A SOURCE IDENTITY IS ALREADY A CAPABILITY. It is a uuid4 minted by an
# authenticated upload, and everything READ about that source — the video, the
# filmstrip, the waveform, the record — is already open on this station. The
# permit therefore buys exactly one thing the open reads do not: the right to
# spend a render slot on THAT source. It is bound to one source id, it expires,
# and turning the API key over invalidates every one of them at once.
SAVE_TOKEN_TTL = 6 * 3600
SAVE_TOKEN_HEADER = "x-pine-save-token"


def _save_secret() -> bytes:
    return (os.environ.get("SPARK_AGENT_API_KEY") or "").encode()


def _save_sign(source_id: str, expires: int) -> str:
    secret = _save_secret()
    if not secret:
        return ""
    body = f"ve1:{source_id}:{expires}".encode()
    return hmac.new(secret, body, hashlib.sha256).hexdigest()[:32]


def mint_save_token(source_id: str, ttl: int = SAVE_TOKEN_TTL) -> str:
    """A short-lived permit to render ONE source. "" when nothing can sign."""
    if not IDENTIFIER.fullmatch(str(source_id or "")):
        return ""
    expires = int(time.time() + max(60, int(ttl)))
    sig = _save_sign(str(source_id), expires)
    return f"ve1.{expires}.{sig}" if sig else ""


def save_token_ok(token: str, source_id: str) -> bool:
    """True when `token` is a live permit for exactly this source."""
    raw = str(token or "")
    if not raw.startswith("ve1.") or not IDENTIFIER.fullmatch(str(source_id or "")):
        return False
    try:
        _, expires, sig = raw.split(".", 2)
        if int(expires) < time.time():
            return False
        want = _save_sign(str(source_id), int(expires))
        return bool(want) and hmac.compare_digest(want, sig)
    except (ValueError, TypeError):
        return False


def number(value, name, low, high):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return result


def normalize_edit(body, source):
    """Validate user edits; coordinates are on the original displayed frame."""
    if not isinstance(body, dict):
        raise ValueError("An edit object is required")
    duration = source["duration"]
    start = number(body.get("in_s", 0), "In point", 0, duration)
    end = number(body.get("out_s", duration), "Out point", 0, duration)
    if end - start < 0.1 - 1e-6:
        raise ValueError("Keep at least 0.1 seconds")
    rotation = number(body.get("rotation", 0), "Rotation", 0, 270)
    if rotation not in (0, 90, 180, 270):
        raise ValueError("Rotation must be 0, 90, 180 or 270 degrees")
    crop = body.get("crop") or {"x": 0, "y": 0, "w": 1, "h": 1}
    if not isinstance(crop, dict):
        raise ValueError("Crop must be a rectangle")
    crop = {k: number(crop.get(k, default), "Crop " + k, 0, 1)
            for k, default in (("x", 0), ("y", 0), ("w", 1), ("h", 1))}
    if crop["x"] + crop["w"] > 1.000001 or crop["y"] + crop["h"] > 1.000001:
        raise ValueError("Crop must stay inside the picture")
    # H.264 requires even dimensions; round the selected region inward.
    width, height = source["width"], source["height"]
    x, y = int(crop["x"] * width), int(crop["y"] * height)
    w = min(width - x, int(round(crop["w"] * width))) // 2 * 2
    h = min(height - y, int(round(crop["h"] * height))) // 2 * 2
    if min(w, h) < 2:
        raise ValueError("Crop is too small")
    audio = body.get("include_audio", True)
    if not isinstance(audio, bool):
        raise ValueError("Include audio must be true or false")
    if audio and not source.get("has_audio"):
        raise ValueError("This recording has no captured audio track")
    return {"in_s": start, "out_s": end, "rotation": int(rotation), "crop": crop,
            "crop_pixels": {"x": x, "y": y, "w": w, "h": h},
            "brightness": number(body.get("brightness", 1), "Brightness", 0.5, 1.5),
            "contrast": number(body.get("contrast", 1), "Contrast", 0.5, 1.5),
            "saturation": number(body.get("saturation", 1), "Saturation", 0, 2),
            "include_audio": audio}


def export_command(source, target, edit, overlay=None, ffmpeg="ffmpeg"):
    """One timeline for video and audio; every export is decoded and re-encoded."""
    start, length = edit["in_s"], edit["out_s"] - edit["in_s"]
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-threads", "2", "-filter_threads", "1", "-filter_complex_threads", "1",
           "-ss", str(start), "-format_whitelist", "mov,matroska,webm", "-i", str(source)]
    if overlay:
        cmd += ["-loop", "1", "-i", str(overlay)]
    b, c, s = (edit[k] for k in ("brightness", "contrast", "saturation"))
    expr = f"clip((val*{b:.9f}-127.5)*{c:.9f}+127.5,0,255)"
    # CSS brightness -> contrast -> saturate, in RGB. The overlay is added
    # afterwards so color correction never changes the operator's ink.
    coeff = []
    for row in range(3):
        for col, weight in enumerate((.213, .715, .072)):
            coeff.append((1 - s) * weight + (s if row == col else 0))
    names = ("rr", "rg", "rb", "gr", "gg", "gb", "br", "bg", "bb")
    matrix = ":".join(f"{key}={value:.9f}" for key, value in zip(names, coeff))
    filters = [f"[0:v:0]format=rgb24,lutrgb=r='{expr}':g='{expr}':b='{expr}',"
               f"colorchannelmixer={matrix}[color]"]
    label = "color"
    if overlay:
        filters.append("[color][1:v:0]overlay=0:0:format=auto:shortest=1[ink]")
        label = "ink"
    box = edit["crop_pixels"]
    transforms = [f"crop={box['w']}:{box['h']}:{box['x']}:{box['y']}"]
    if edit["rotation"] == 90:
        transforms.append("transpose=clock")
    elif edit["rotation"] == 180:
        transforms += ["hflip", "vflip"]
    elif edit["rotation"] == 270:
        transforms.append("transpose=cclock")
    transforms += ["setsar=1", "format=yuv420p"]
    filters.append(f"[{label}]" + ",".join(transforms) + "[video]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "[video]", "-t", str(length),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", "2"]
    if edit["include_audio"]:
        cmd += ["-map", "0:a:0", "-af", "aresample=async=1:first_pts=0",
                "-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-an"]
    return cmd + ["-map_metadata", "-1", "-movflags", "+faststart", str(target)]


class VideoEditor:
    def __init__(self, root, assets, ffmpeg=None, ffprobe=None):
        self.root, self.assets = Path(root), Path(assets)
        if not ffmpeg:
            import imageio_ffmpeg
            ffmpeg = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
        self.ffmpeg, self.ffprobe = ffmpeg, ffprobe or shutil.which("ffprobe")
        self.worker = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="video-edit")
        self.slots = threading.BoundedSemaphore(8)
        self.lock = threading.RLock()
        self.active = set()
        self.processes = set()
        self.closed = False

    def close(self):
        """A station restart must not wait for a twenty-minute render."""
        with self.lock:
            self.closed = True
            processes = list(self.processes)
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
        self.worker.shutdown(wait=False, cancel_futures=True)

    def folder(self, kind, identifier):
        if kind not in ("sources", "exports") or not IDENTIFIER.fullmatch(str(identifier)):
            raise ValueError("Invalid recording identity")
        return self.root / kind / identifier

    def read(self, kind, identifier):
        path = self.folder(kind, identifier) / "record.json"
        with self.lock:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                raise ValueError("Recording not found") from None
            if data.get("status") in ("queued", "processing", "working") and identifier not in self.active:
                data.update(status="failed", error="Processing was interrupted. Capture again or retry the edit.")
                self.write(kind, identifier, data)
            return data

    def write(self, kind, identifier, record):
        folder = self.folder(kind, identifier)
        folder.mkdir(parents=True, exist_ok=True)
        with self.lock:
            temp = folder / "record.tmp"
            temp.write_text(json.dumps(record, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            os.replace(temp, folder / "record.json")

    def discard_new(self, kind, identifier):
        target = self.folder(kind, identifier).resolve()
        parent = (self.root / kind).resolve()
        if target.parent != parent or not IDENTIFIER.fullmatch(target.name):
            raise ValueError("Refusing to remove an unowned edit directory")
        shutil.rmtree(target)

    def submit(self, kind, identifier, work):
        if self.closed:
            raise ValueError("The video editor is restarting. Try again shortly.")
        if not self.slots.acquire(blocking=False):
            raise ValueError("The video editor is busy. Try again shortly.")
        with self.lock:
            self.active.add(identifier)

        def run():
            try:
                work()
            except Exception as exc:
                try:
                    record = self.read(kind, identifier)
                    record.update(status="failed", error=str(exc)[:600])
                    self.write(kind, identifier, record)
                except Exception:
                    pass
            finally:
                with self.lock:
                    self.active.discard(identifier)
                self.slots.release()
        try:
            with self.lock:
                if self.closed:
                    raise ValueError("The video editor is restarting. Try again shortly.")
                self.worker.submit(run)
        except (RuntimeError, ValueError) as exc:
            with self.lock:
                self.active.discard(identifier)
            self.slots.release()
            raise ValueError("The video editor is restarting. Try again shortly.") from exc

    def run(self, command, timeout=180):
        # Keep editing off the broadcast's event loop and below its CPU priority.
        if os.name != "nt" and shutil.which("nice"):
            command = ["nice", "-n", "10"] + command
        with self.lock:
            if self.closed:
                raise ValueError("Video processing was interrupted by a restart")
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.processes.add(process)
        try:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise ValueError("Media processing took too long. Try a shorter clip.") from None
            if process.returncode:
                raise ValueError("Media processing failed: " + stderr.decode("utf-8", "replace")[-500:])
            return stdout
        finally:
            with self.lock:
                self.processes.discard(process)

    @staticmethod
    def _tail(log) -> str:                                      # [#1207]
        try:
            return Path(log).read_text(encoding="utf-8", errors="replace")[-500:]
        except OSError:
            return "no detail was written"

    def run_progress(self, command, seconds, report, timeout=1800, log=None):
        """[#1207] The encoder's own clock, read off `-progress pipe:1`.

        The operator asked for a bar that sweeps the footage in step with the
        export. A bar has to be told the truth by something, and the only
        thing that knows is ffmpeg: `out_time_us` counts microseconds of
        OUTPUT written, so it is already measured against the trim rather than
        against the whole recording. (`out_time_ms` is the same number in
        microseconds — a long-standing ffmpeg misnomer — so both divide by
        1e6.) stderr goes to a FILE, not a pipe: at -loglevel error it is
        normally empty, and a pipe nobody drains is how a render deadlocks at
        64 kB with the bar frozen and no reason on the wire."""
        command = list(command)
        command[1:1] = ["-progress", "pipe:1", "-nostats"]
        if os.name != "nt" and shutil.which("nice"):
            command = ["nice", "-n", "10"] + command
        errors = open(log, "wb") if log else subprocess.DEVNULL
        with self.lock:
            if self.closed:
                raise ValueError("Video processing was interrupted by a restart")
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
            self.processes.add(process)
        overran = []

        def stop():
            overran.append(True)
            try:
                process.kill()
            except OSError:
                pass

        killer = threading.Timer(max(30, timeout), stop)
        killer.daemon = True
        killer.start()
        last = 0.0
        try:
            for raw in process.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if not (line.startswith("out_time_us=")
                        or line.startswith("out_time_ms=")):
                    continue
                try:
                    done = int(line.split("=", 1)[1]) / 1e6
                except ValueError:
                    continue
                share = done / seconds if seconds > 0 else 0.0
                share = max(0.0, min(0.999, share))
                now = time.monotonic()
                if now - last >= 0.4:
                    last = now
                    try:
                        report(share, done)
                    except Exception:  # a bar is never worth a failed render
                        pass
            process.wait()
        finally:
            killer.cancel()
            try:
                process.stdout.close()
            except OSError:
                pass
            if errors is not subprocess.DEVNULL:
                errors.close()
            with self.lock:
                self.processes.discard(process)
        if overran:
            raise ValueError("Media processing took too long. Try a shorter clip.")
        if process.returncode:
            raise ValueError("Media processing failed: " + self._tail(log))
        try:
            report(1.0, seconds)
        except Exception:
            pass

    def probe(self, path):
        if not self.ffprobe:
            return self.probe_av(path)
        info = json.loads(self.run([self.ffprobe, "-v", "error", "-format_whitelist", "mov,matroska,webm",
                                    "-show_streams", "-show_format",
                                    "-of", "json", str(path)], timeout=30))
        video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
        if not video:
            raise ValueError("The recording has no video track")
        duration = number(video.get("duration") or info.get("format", {}).get("duration"),
                          "Recording duration", .1, MAX_DURATION)
        width, height = int(video.get("width", 0)), int(video.get("height", 0))
        if min(width, height) < 2 or max(width, height) > 4096 or width * height > MAX_PIXELS:
            raise ValueError("Recording dimensions are unsupported")
        rotation = next((float(d.get("rotation", 0)) for d in video.get("side_data_list", [])
                         if "rotation" in d), 0)
        if abs(rotation) % 180 == 90:
            width, height = height, width
        audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
        return {"duration": duration, "width": width, "height": height, "has_audio": bool(audio),
                "audio_channels": int((audio or {}).get("channels", 0)),
                "audio_sample_rate": int((audio or {}).get("sample_rate", 0)),
                "audio_start_s": float((audio or {}).get("start_time", 0) or 0),
                "video_start_s": float(video.get("start_time", 0) or 0)}

    def probe_av(self, path):
        """The station bundles FFmpeg but not ffprobe; read real container times."""
        import av

        with av.open(str(path), options={"format_whitelist": "mov,matroska,webm"}) as container:
            if not container.streams.video:
                raise ValueError("The recording has no video track")
            video = container.streams.video[0]
            duration = (float(video.duration * video.time_base) if video.duration is not None
                        else float(container.duration or 0) / av.time_base)
            duration = number(duration, "Recording duration", .1, MAX_DURATION)
            width, height = video.codec_context.width, video.codec_context.height
            if min(width, height) < 2 or max(width, height) > 4096 or width * height > MAX_PIXELS:
                raise ValueError("Recording dimensions are unsupported")
            # Capture files have no display transform. Decode one frame to
            # inspect any transform on imported MP4s without estimating it.
            video.codec_context.thread_count = 1
            first = next(container.decode(video), None)
            if first is None:
                raise ValueError("The recording contains no decodable picture")
            rotation = float(getattr(first, "rotation", 0) or 0)
            if abs(rotation) % 180 == 90:
                width, height = height, width
            audio = container.streams.audio[0] if container.streams.audio else None
            return {"duration": duration, "width": width, "height": height, "has_audio": audio is not None,
                    "audio_channels": audio.codec_context.channels if audio is not None else 0,
                    "audio_sample_rate": audio.codec_context.sample_rate if audio is not None else 0,
                    "audio_start_s": float((audio.start_time or 0) * audio.time_base) if audio is not None else 0,
                    "video_start_s": float((video.start_time or 0) * video.time_base)}

    def analyze_audio(self, path, target, duration):
        import numpy as np
        from PIL import Image

        raw = self.run([self.ffmpeg, "-v", "error", "-nostdin", "-threads", "2", "-i", str(path),
                        "-map", "0:a:0", "-af", "aresample=8000:async=1:first_pts=0",
                        "-ac", "1", "-t", str(duration), "-f", "f32le", "pipe:1"])
        signal = np.frombuffer(raw, dtype="<f4")
        frames = max(1, int(math.ceil(duration * 8000)))
        signal = np.nan_to_num(signal[:frames], nan=0.0, posinf=0.0, neginf=0.0)
        if len(signal) < frames:
            signal = np.pad(signal, (0, frames - len(signal)))
        peak = float(np.max(np.abs(signal)))
        count = min(2048, len(signal))
        edges = np.linspace(0, len(signal), count + 1, dtype=int)
        peaks = np.maximum.reduceat(np.abs(signal), edges[:-1])
        # The spectrogram includes all windows, aggregated by time column.
        columns, bands, size, hop = 1024, 96, 512, 256
        spectrum = np.zeros((bands, columns), dtype=np.float32)
        window = np.hanning(size)
        freq_positions = np.geomspace(1, size // 2, bands).astype(int)
        for first in range(0, len(signal), hop * 256):
            starts = np.arange(first, min(len(signal), first + hop * 256), hop)
            indices = starts[:, None] + np.arange(size)[None, :]
            block = signal[np.minimum(indices, len(signal) - 1)]
            block[indices >= len(signal)] = 0
            magnitudes = np.abs(np.fft.rfft(block * window, axis=1)) / (size / 2)
            levels = magnitudes[:, freq_positions]
            positions = np.minimum(columns - 1, starts * columns // len(signal))
            for j, pos in enumerate(positions):
                spectrum[:, pos] = np.maximum(spectrum[:, pos], levels[j])
        level = np.clip((20 * np.log10(spectrum + 1e-8) + 80) / 80, 0, 1)[::-1]
        rgb = np.stack((np.clip((level - .5) * 2, 0, 1), np.clip(level * 1.6, 0, 1),
                        np.clip(level * 2 - level ** 3, 0, 1)), axis=-1)
        Image.fromarray((rgb * 255).astype("uint8")).save(target)
        return {"waveform": np.clip(peaks, 0, 1).round(5).tolist(), "audio_peak": round(peak, 6),
                "audio_rms": round(float(np.sqrt(np.mean(signal * signal))), 6),
                "audio_signal": "silent" if peak < 0.0001 else "present"}

    def analyze(self, identifier):
        folder = self.folder("sources", identifier)
        record = self.read("sources", identifier)
        media = folder / "original.mp4"
        record.update(self.probe(media))
        record["url"] = f"/api/video-editor/sources/{identifier}/file"
        record["waveform"] = []
        if record["has_audio"]:
            record.update(self.analyze_audio(media, folder / "spectrum.png", record["duration"]))
            record["spectrogram_url"] = f"/api/video-editor/sources/{identifier}/spectrum.png"
        else:
            record["audio_signal"] = "unavailable"
        # Twelve tiny frames from the whole source form one bounded image.
        thumb_scale = min(160 / record["width"], 160 / record["height"])
        thumb_width = max(2, int(round(record["width"] * thumb_scale)))
        thumb_height = max(2, int(round(record["height"] * thumb_scale)))
        self.run([self.ffmpeg, "-v", "error", "-nostdin", "-y", "-threads", "2", "-filter_threads", "1",
                  "-i", str(media), "-vf", f"fps=12/{record['duration']},scale={thumb_width}:{thumb_height},tile=6x2",
                  "-frames:v", "1", str(folder / "thumbnails.jpg")])
        record.update(status="ready", thumbnail_sprite={
            "url": f"/api/video-editor/sources/{identifier}/thumbnails.jpg", "count": 12,
            "width": thumb_width, "height": thumb_height, "columns": 6})
        self.write("sources", identifier, record)

    def save_overlay(self, data, source, folder):
        from PIL import Image

        if not data:
            return None
        if not isinstance(data, str) or not data.startswith("data:image/png;base64,") or len(data) > MAX_OVERLAY * 4 // 3 + 100:
            raise ValueError("Drawing must be a PNG image")
        try:
            raw = base64.b64decode(data.split(",", 1)[1], validate=True)
            if len(raw) > MAX_OVERLAY:
                raise ValueError("Drawing is too large")
            with Image.open(io.BytesIO(raw)) as ink:
                if ink.format != "PNG" or ink.size != (source["width"], source["height"]):
                    raise ValueError("Drawing dimensions do not match the original recording")
                ink.load()
                path = folder / "overlay.png"
                ink.convert("RGBA").save(path)
                return path
        except (OSError, base64.binascii.Error) as exc:
            raise ValueError("Drawing could not be read") from exc

    def start_export(self, body):
        source_id = str(body.get("source_id", ""))
        source = self.read("sources", source_id)
        if source.get("status") != "ready":
            raise ValueError("The recording is still being prepared")
        edit = normalize_edit(body, source)
        identifier = uuid.uuid4().hex
        folder = self.folder("exports", identifier)
        folder.mkdir(parents=True)
        try:
            overlay = self.save_overlay(body.get("overlay_png"), source, folder)
            record = {"id": identifier, "status": "queued", "source_id": source_id,
                      "created_at_ms": int(time.time() * 1000), "edit": edit,
                      "name": "Pine-" + time.strftime("%Y%m%d-%H%M%S") + "-edited.mp4",
                      "poll_url": f"/api/video-editor/exports/{identifier}"}
            self.write("exports", identifier, record)

            def render():
                # [#1207] The record now carries a real reading of the render
                # so the editor's scan bar can sweep to it. Every field here
                # is written by the throttled reporter below, not guessed.
                target = max(0.001, float(edit["out_s"] - edit["in_s"]))
                began = time.time()
                record.update(status="working", progress=0.0, progress_pct=0,
                              rendered_s=0.0, target_s=round(target, 3),
                              eta_s=0.0, started_at_ms=int(began * 1000))
                self.write("exports", identifier, record)
                temp = folder / "rendering.mp4"

                def seen(share, done):
                    spent = max(0.001, time.time() - began)
                    record.update(progress=round(share, 4),
                                  progress_pct=int(share * 100),
                                  rendered_s=round(done, 3),
                                  eta_s=round(max(0.0, spent / share - spent), 1)
                                  if share > 0.02 else 0.0)
                    self.write("exports", identifier, record)

                self.run_progress(export_command(self.folder("sources", source_id) / "original.mp4", temp,
                                                 edit, overlay, self.ffmpeg),
                                  target, seen, timeout=1800, log=folder / "render.log")
                verified = self.probe(temp)
                if verified["has_audio"] != edit["include_audio"]:
                    raise ValueError("The exported audio track does not match the selection")
                expected = edit["out_s"] - edit["in_s"]
                if abs(verified["duration"] - expected) > .25:
                    raise ValueError("The exported duration does not match the selected trim")
                os.replace(temp, folder / "edited.mp4")
                record.update(status="complete", progress=1.0, progress_pct=100,  # [#1207]
                              url=f"/api/video-editor/exports/{identifier}/file", **verified)
                self.write("exports", identifier, record)
            self.submit("exports", identifier, render)
            return record.copy()
        except Exception:
            # Only this newly allocated export directory is disposable.
            self.discard_new("exports", identifier)
            raise


def create_video_editor_router(root, assets, require_auth, require_read_auth):
    editor = VideoEditor(root, assets)
    router = APIRouter()
    router.add_event_handler("shutdown", editor.close)

    def checked_read(kind, identifier):
        try:
            return editor.read(kind, identifier)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    def save_permit(request, source_id, body=None):
        """[#1242] The key, or a live permit for THIS source — and when it is
        neither, a refusal the operator can act on rather than the bare word
        "Unauthorized" the editor used to print."""
        try:
            require_auth(request.headers.get("authorization"))
            return
        except HTTPException as exc:
            if exc.status_code != 401:
                raise            # a missing API key is a 500 and stays one
        token = (request.headers.get(SAVE_TOKEN_HEADER)
                 or request.query_params.get("save")
                 or str((body or {}).get("save_token") or ""))
        if save_token_ok(token, str(source_id or "")):
            return
        raise HTTPException(
            401,
            "This editor window has no live save permit, so the station will "
            "not start the render. Reopen the recording from the panel to get "
            "a fresh one, or keep the clip straight to this device instead.")

    @router.get("/video-editor/")
    async def page():
        return FileResponse(editor.assets / "video-editor.html", headers={"Cache-Control": "no-store"})

    @router.get("/video-editor/{asset}")
    async def asset(asset: str):
        if asset not in ASSETS:
            raise HTTPException(404, "Unknown editor asset")
        return FileResponse(editor.assets / asset, headers={"Cache-Control": "no-cache"})

    @router.post("/api/video-editor/sources")
    async def upload(request: Request):
        require_auth(request.headers.get("authorization"))
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > MAX_UPLOAD):
            raise HTTPException(413, "Recordings must be smaller than 256 MB")
        identifier = uuid.uuid4().hex
        folder = editor.folder("sources", identifier)
        folder.mkdir(parents=True)
        total = 0
        try:
            # Stream disk writes off the event loop; do not retain the entire
            # twenty-minute replay in the station process's request heap.
            import asyncio
            with (folder / "original.mp4").open("wb") as target:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > MAX_UPLOAD:
                        raise HTTPException(413, "Recordings must be smaller than 256 MB")
                    await asyncio.to_thread(target.write, chunk)
            if total < 64:
                raise HTTPException(400, "The recording is empty")
            audio_raw = request.headers.get("x-capture-audio", "{}")
            try:
                audio = json.loads(audio_raw) if len(audio_raw) <= 8192 else {}
            except ValueError:
                audio = {}
            if not isinstance(audio, dict):
                audio = {}
            record = {"id": identifier, "source_id": identifier, "status": "processing",
                      "name": (request.headers.get("x-capture-name") or "Tablet recording")[:160],
                      "created_at_ms": int(time.time() * 1000), "bytes": total,
                      "audio_capture": audio, "editor_url": f"/video-editor/?source={identifier}"}
            editor.write("sources", identifier, record)
            try:
                editor.submit("sources", identifier, lambda: editor.analyze(identifier))
            except ValueError as exc:
                raise HTTPException(429, str(exc)) from exc
            return record
        except BaseException:
            editor.discard_new("sources", identifier)
            raise

    @router.post("/api/video-editor/sources/{identifier}/retry")
    async def retry_source(identifier: str, request: Request):
        save_permit(request, identifier)                            # [#1242]
        record = checked_read("sources", identifier)
        if record.get("status") != "failed":
            return record
        record.update(status="processing", error="")
        editor.write("sources", identifier, record)
        try:
            editor.submit("sources", identifier, lambda: editor.analyze(identifier))
        except ValueError as exc:
            record.update(status="failed", error=str(exc))
            editor.write("sources", identifier, record)
            raise HTTPException(429, str(exc)) from exc
        return record

    @router.get("/api/video-editor/sources/{identifier}")
    async def source(identifier: str, request: Request):
        require_read_auth(request.headers.get("authorization"))
        record = dict(checked_read("sources", identifier))
        # [#1242] The permit rides WITH the record, because the record is the
        # one thing every surface already fetches on open — the desk's
        # cross-origin iframe, the tablet, a phone on the LAN. Reads are open
        # on this station, and the permit is worth no more than the reads it
        # sits beside: it renders this source and nothing else.
        token = mint_save_token(identifier)
        if token:
            record["save_token"] = token
            record["save_token_ttl_s"] = SAVE_TOKEN_TTL
        return record

    @router.post("/api/video-editor/sources/{identifier}/save-token")
    async def source_save_token(identifier: str, request: Request):
        """[#1242] Minted by the page that OPENED the editor, which holds the
        key, for the surface where the reads are locked and the iframe can
        prove nothing for itself. hot-corners.js answers the editor's ask on
        this road and posts the permit through."""
        require_auth(request.headers.get("authorization"))
        checked_read("sources", identifier)
        token = mint_save_token(identifier)
        if not token:
            raise HTTPException(500, "No API key is configured, so nothing can be signed.")
        return {"ok": True, "save_token": token, "ttl_s": SAVE_TOKEN_TTL,
                "expires_ms": int(token.split(".")[1]) * 1000}

    @router.get("/api/video-editor/sources/{identifier}/{asset}")
    async def source_file(identifier: str, asset: str, request: Request):
        require_read_auth(request.headers.get("authorization"))
        checked_read("sources", identifier)
        names = {"file": "original.mp4", "spectrum.png": "spectrum.png", "thumbnails.jpg": "thumbnails.jpg"}
        if asset not in names:
            raise HTTPException(404, "Unknown recording asset")
        path = editor.folder("sources", identifier) / names[asset]
        if not path.is_file():
            raise HTTPException(404, "Recording asset is not ready")
        return FileResponse(path, media_type="video/mp4" if asset == "file" else None,
                            headers={"Cache-Control": "private, max-age=86400"})

    @router.post("/api/video-editor/exports")
    async def export(request: Request):
        # [#1242] The body is read BEFORE the permit is checked, because the
        # permit names a source and the source id is in the body. The same
        # size bound guards it either way, so an unauthenticated caller can
        # push no more bytes at this route than an authenticated one could.
        import asyncio
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_OVERLAY * 4 // 3 + 65536:
                raise HTTPException(413, "The drawing is too large")
        try:
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError("An edit object is required")
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        save_permit(request, str(body.get("source_id", "")), body)  # [#1242]
        try:
            return await asyncio.to_thread(editor.start_export, body)
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/api/video-editor/exports/{identifier}")
    async def exported(identifier: str, request: Request):
        require_read_auth(request.headers.get("authorization"))
        return checked_read("exports", identifier)

    @router.get("/api/video-editor/exports/{identifier}/file")
    async def exported_file(identifier: str, request: Request):
        require_read_auth(request.headers.get("authorization"))
        record = checked_read("exports", identifier)
        if record.get("status") != "complete":
            raise HTTPException(409, "The edited recording is not ready")
        return FileResponse(editor.folder("exports", identifier) / "edited.mp4", media_type="video/mp4",
                            filename=record["name"], headers={"Cache-Control": "private, max-age=86400"})

    # [#1223] The editor travels with its router, so the station can hand it
    # a file that is already on its own disk instead of uploading one to
    # itself. app.py's /api/sfx/edit/open uses only the public methods the
    # upload route above uses: folder(), write(), submit() and analyze().
    router.pine_editor = editor
    return router

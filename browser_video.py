"""Seekable browser pictures, prepared once rather than streamed on every seek.

The ordinary SFX loudness pipe ignores Range and copies the source video codec.
A delayed listener must seek into a clip, and an MP4 container alone does not
make HEVC, ten-bit H264 or an old MPEG stream browser compatible. This separate
URL always serves a completed H264/yuv420p/AAC file with a fast-start index.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
import hashlib
import math
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from starlette.responses import Response, StreamingResponse

_ENCODERS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser-video")
_JOBS: dict[str, Future] = {}
_LOCK = threading.Lock()
_WARM_TASKS: dict[str, asyncio.Task] = {}
CACHE_MAX_BYTES = 2 * 1024 ** 3
CACHE_IDLE_SECONDS = 600
_LAST_PRUNE = 0.0


def browser_video_url(url: str) -> str:
    """Keep the signed capability; its signature covers the clip ID only."""
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return str(url or "")
    if parts.scheme or parts.netloc or not re.fullmatch(r"/sfx/[a-f0-9]{16}", parts.path):
        return str(url or "")
    pairs = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if key != "video"]
    pairs.append(("video", "browser"))
    return urlunsplit(("", "", parts.path, urlencode(pairs), parts.fragment))


def _number(value: Any, default: float = 0.0) -> float:
    try:
        got = float(value)
        return got if math.isfinite(got) else default
    except (TypeError, ValueError, OverflowError):
        return default


def listener_video_rows(clips: list[dict], now_ms: int, lag_ms: int = 0,
                        cut_ms: int = 0) -> list[dict]:
    """All retained cues, including short clips between polls and future cues.

    A 12-row tail discarded a delayed listener's next pictures during bursts.
    The durable ring already has a bound; use its complete three-minute window
    and let the browser schedule it. Seek offsets refer to the original media,
    while seconds remains the scheduled display duration.
    """
    out = []
    for clip in clips:
        if not isinstance(clip, dict) or not clip.get("video"):
            continue
        stamp = int(_number(clip.get("ts")))
        if stamp <= int(_number(cut_ms)):
            continue
        air = int(_number(clip.get("broadcast_ms"), stamp))
        seconds = max(0.0, min(86400.0, _number(clip.get("seconds"))))
        start = max(0.0, _number(clip.get("seek"), _number(clip.get("from"))))
        end = _number(clip.get("to"))
        if seconds <= 0 and end > start:
            seconds = end - start
        if now_ms - (air + int(seconds * 1000)) > 190000:
            continue
        # A joining player does not know its 30/45-second audio cushion until
        # this response supplies burst_s. Keep the entire recovery window even
        # when its first request says lag=0; the browser chooses the heard cue.
        url = str(clip.get("url") or "")
        if not url:
            continue
        # A repeated URL is a new cue when its broadcast stamp changes.
        identity = str(clip.get("delivery_id") or "%d:%d:%s" % (air, stamp, url.split("?")[0]))
        row = {"id": identity, "ts": stamp, "url": browser_video_url(url),
               "name": str(clip.get("sting") or clip.get("text") or ""),
               "broadcast_ms": air, "seconds": round(seconds, 3), "seek": start}
        for key in ("from", "to", "picture_only"):
            if key in clip:
                row[key] = clip[key]
        sid = re.fullmatch(r"/sfx/([a-f0-9]{16})", url.split("?", 1)[0].split("#", 1)[0])
        if sid:
            row["sfx_id"] = sid.group(1)
        out.append(row)
    return sorted(out, key=lambda row: (row["broadcast_ms"], row["ts"]))


def _probe(source: Path, executable: str) -> str:
    result = subprocess.run([executable, "-nostdin", "-hide_banner", "-i", str(source)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            timeout=30, text=True, errors="replace")
    log = result.stderr or ""
    if not re.search(r"Stream .*Video:", log):
        raise ValueError("The clip contains no readable video stream")
    return log


def encode_command(source: Path, target: Path, executable: str, metadata: str,
                   gain_db: float = 0.0) -> list[str]:
    video_line = next((line for line in metadata.splitlines() if "Video:" in line), "")
    # Ten-bit and 4:2:2 H264 are frequent sources of audio with a black picture.
    compatible = bool(re.search(r"Video: h264(?:\s|\(|,)", video_line)
                      and re.search(r"\byuv420p(?:\(|,|\s)", video_line)
                      and not re.search(r"High 10|High 4:2:2|High 4:4:4", video_line))
    argv = [executable, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
            "-sn", "-dn"]
    if compatible:
        argv += ["-c:v", "copy"]
    else:
        argv += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                 "-pix_fmt", "yuv420p", "-vf",
                 "scale=w='min(1920,iw)':h='min(1080,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                 "-profile:v", "main", "-threads", "2"]
    argv += ["-c:a", "aac", "-b:a", "160k", "-ac", "2"]
    if abs(_number(gain_db)) >= 0.05:
        argv += ["-af", "volume=%.2fdB,alimiter=limit=0.8913:level=disabled:latency=1"
                 % max(-30.0, min(24.0, _number(gain_db)))]
    argv += ["-max_muxing_queue_size", "2048", "-movflags", "+faststart",
             "-f", "mp4", str(target)]
    return argv


def _prune(cache: Path, keep: Path) -> None:
    global _LAST_PRUNE
    now = time.time()
    if now - _LAST_PRUNE < 60:
        return
    _LAST_PRUNE = now
    files = []
    for path in cache.glob("*.mp4"):
        try:
            stat = path.stat()
            files.append((stat.st_mtime, stat.st_size, path))
        except OSError:
            pass
    total = sum(size for _, size, _ in files)
    for touched, size, path in sorted(files):
        if total <= CACHE_MAX_BYTES:
            break
        if path == keep or now - touched < CACHE_IDLE_SECONDS:
            continue
        try:
            path.unlink()
            total -= size
        except OSError:
            pass


def _prepare(source: Path, output: Path, executable: str, gain_db: float) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.is_file():
        metadata = _probe(source, executable)
        temporary = output.with_suffix(".part.mp4")
        try:
            result = subprocess.run(encode_command(source, temporary, executable, metadata, gain_db),
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, timeout=300)
            if result.returncode or not temporary.is_file() or temporary.stat().st_size < 64:
                raise ValueError("The video could not be converted for browser playback")
            # A copy should work for compatible H264, but a broken bitstream is
            # not admitted merely because ffmpeg produced a container header.
            _probe(temporary, executable)
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    output.touch()
    _prune(output.parent, output)
    return output


async def prepare_browser_video(source: Path, cache_dir: Path, executable: str,
                                gain_db: float = 0.0) -> Path:
    stat = await asyncio.to_thread(source.stat)
    # Gain changes cannot change bytes in the middle of a Range session: it is
    # settled when this source revision is first prepared, then cached as-is.
    fingerprint = "%s|%d|%d|v1" % (source.resolve(), stat.st_size, stat.st_mtime_ns)
    key = hashlib.sha256(fingerprint.encode()).hexdigest()
    output = cache_dir / (key + ".mp4")
    if await asyncio.to_thread(output.is_file):
        await asyncio.to_thread(output.touch)
        return output
    with _LOCK:
        for finished in [item for item, job in _JOBS.items() if job.done()]:
            _JOBS.pop(finished, None)
        future = _JOBS.get(key)
        if future is None:
            if len(_JOBS) >= 16:
                raise TimeoutError("Video preparation is busy")
            future = _ENCODERS.submit(_prepare, source, output, executable, gain_db)
            _JOBS[key] = future
    try:
        return await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)), timeout=60)
    finally:
        if future.done():
            with _LOCK:
                if _JOBS.get(key) is future:
                    _JOBS.pop(key, None)


def warm_browser_video(source: Path, cache_dir: Path, executable: str,
                       gain_db: float = 0.0) -> bool:
    """Warm upcoming pictures without delaying the feed or growing an idle queue.

    The caller resolves only its next two signed SFX IDs. A preparation still
    runs after a warming coroutine times out; a following request joins it.
    """
    key = str(source)
    if key in _WARM_TASKS or len(_WARM_TASKS) >= 4:
        return False

    async def work():
        try:
            await prepare_browser_video(source, cache_dir, executable, gain_db)
        except (OSError, subprocess.SubprocessError, ValueError, TimeoutError):
            pass
        finally:
            _WARM_TASKS.pop(key, None)

    try:
        _WARM_TASKS[key] = asyncio.get_running_loop().create_task(work())
    except RuntimeError:
        return False
    return True


def byte_range(raw: str, size: int) -> tuple[int, int] | None:
    if not raw:
        return None
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", raw.strip())
    if not match or size <= 0 or not any(match.groups()):
        raise ValueError("Invalid byte range")
    left, right = match.groups()
    if not left:
        count = int(right)
        if count <= 0:
            raise ValueError("Invalid suffix range")
        return max(0, size - count), size - 1
    start = int(left)
    end = min(size - 1, int(right)) if right else size - 1
    if start >= size or end < start:
        raise ValueError("Unsatisfiable byte range")
    return start, end


def _file_chunks(path: Path, start: int, end: int):
    with path.open("rb") as stream:
        stream.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = stream.read(min(262144, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


async def browser_video_response(source: Path, request: Any, cache_dir: Path,
                                 executable: str, gain_db: float = 0.0) -> Response:
    """Call only after the existing SFX ID/signature authorization checks."""
    try:
        output = await prepare_browser_video(source, cache_dir, executable, gain_db)
        size = (await asyncio.to_thread(output.stat)).st_size
    except (TimeoutError, asyncio.TimeoutError):
        return Response("Preparing this video for playback", status_code=503,
                        headers={"Retry-After": "1", "Cache-Control": "no-store"})
    except (OSError, subprocess.SubprocessError, ValueError):
        return Response("This clip could not be prepared for browser playback", status_code=422,
                        headers={"Cache-Control": "no-store"})
    headers = {"Accept-Ranges": "bytes", "Content-Type": "video/mp4",
               "X-Content-Type-Options": "nosniff", "Access-Control-Allow-Origin": "*",
               "Cache-Control": "private, max-age=3600", "ETag": '"%s"' % output.stem}
    try:
        raw_range = str(request.headers.get("range") or "")
        if_range = str(request.headers.get("if-range") or "")
        if if_range and if_range != headers["ETag"]:
            raw_range = ""
        window = byte_range(raw_range, size)
    except ValueError:
        headers["Content-Range"] = "bytes */%d" % size
        return Response(status_code=416, headers=headers)
    start, end = window if window else (0, size - 1)
    headers["Content-Length"] = str(end - start + 1)
    if window:
        headers["Content-Range"] = "bytes %d-%d/%d" % (start, end, size)
    return StreamingResponse(_file_chunks(output, start, end), status_code=206 if window else 200,
                             headers=headers, media_type="video/mp4")

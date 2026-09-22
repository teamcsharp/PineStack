"""clip_speech - what a clip actually SAYS, so the SFX guy can find it.

[#1386] "for the sfx guy to be able to play clips appropriate to dialogue
at times and to try and make jokes about the situations, he has to have
access to the full library and vectorize and understand how and when to
find and use clips."

He already reaches all 324,551 clips, and he already matches them to the
line - but only on their FILENAMES. 62,658 of them carry words in the
name; the other ~262,000 are "1965 clip" and cannot be found by anything
they say. This is the half that opens them.

TWO PIECES, both pure enough to test without a station:

  the wire     wyoming is newline-delimited JSON, optionally followed by a
               binary payload. `frame()` writes one event, `read_event()`
               reads one back. That is the whole protocol.
  the audio    PyAV decodes and resamples in-process. No subprocess, no
               temp file, no ffmpeg on the PATH - the station image has
               none, and shelling out per clip across 262,000 clips would
               be its own outage.

WHY IT IS BOUNDED AND IDLE-ONLY. Transcribing the library is hours of GPU
the writing room also wants, and this station's failure mode is dead air,
not a thin index. So the caller decides how many to take and when; nothing
in here loops, sleeps or schedules.
"""
from __future__ import annotations

import io
import json
import socket
from typing import Any, Iterator

WYOMING_HOST = "127.0.0.1"
WYOMING_PORT = 10300

# Whisper wants 16 kHz mono signed-16 PCM, and asking PyAV for exactly that
# means no resampling anywhere else.
RATE = 16000
WIDTH = 2
CHANNELS = 1

# A sting is punctuation, not a lecture. Past this the clip is not what the
# SFX guy reaches for and the transcription is not worth the GPU.
MOST_SECONDS = 30.0
CHUNK_FRAMES = 4096


def frame(kind: str, data: dict[str, Any] | None = None,
          payload: bytes = b"") -> bytes:
    """One wyoming event on the wire.

    THE DATA IS NOT IN THE HEADER. Measured against the live service
    (wyoming 1.10.0, faster-whisper base-int8): a header announces
    `data_length` and `payload_length`, and the JSON data follows the
    newline as its own block, with the binary payload after that.

        {"type": "info", "version": "1.10.0", "data_length": 1258}\n
        {"asr": [...]}                       <- exactly 1258 bytes
        <payload_length bytes>

    The first cut of this wrote `{"type": ..., "data": {...}}` inline,
    which is how the protocol is usually DESCRIBED. The service accepted
    every event and answered with an empty transcript for each one, which
    is the worst way to be wrong: nothing errored, nothing logged, and
    three clips in a row came back saying nothing at all."""
    body = json.dumps(data or {}).encode("utf-8") if data else b""
    head: dict[str, Any] = {"type": str(kind), "version": "1.10.0"}
    if body:
        head["data_length"] = len(body)
    if payload:
        head["payload_length"] = len(payload)
    return json.dumps(head).encode("utf-8") + b"\n" + body + payload


def _take(sock: socket.socket, buf: bytearray, size: int) -> bytes | None:
    while len(buf) < size:
        chunk = sock.recv(65536)
        if not chunk:
            return None
        buf.extend(chunk)
    got = bytes(buf[:size])
    del buf[:size]
    return got


def read_event(sock: socket.socket, buf: bytearray) -> tuple[str, dict, bytes] | None:
    """The next event, or None when the far end goes away.

    `buf` carries whatever arrived past the end of the last event, so a
    reply that lands in the same packet as its data is not lost."""
    while b"\n" not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            return None
        buf.extend(chunk)
    line, _, rest = bytes(buf).partition(b"\n")
    buf.clear()
    buf.extend(rest)
    try:
        head = json.loads(line.decode("utf-8", "replace"))
    except ValueError:
        return None
    data: dict[str, Any] = dict(head.get("data") or {})
    size = int(head.get("data_length") or 0)
    if size:
        got = _take(sock, buf, size)
        if got is None:
            return None
        try:
            parsed = json.loads(got.decode("utf-8", "replace"))
            if isinstance(parsed, dict):
                data = parsed
        except ValueError:
            pass
    plen = int(head.get("payload_length") or 0)
    payload = b""
    if plen:
        got = _take(sock, buf, plen)
        if got is None:
            return None
        payload = got
    return str(head.get("type") or ""), data, payload


def pcm_of(path: str, most_seconds: float = MOST_SECONDS) -> bytes:
    """The clip as 16 kHz mono s16, or b"" when it cannot be decoded.

    Never raises: a clip that will not open is a clip with no transcript,
    which is exactly what it was before this existed."""
    try:
        import av                                    # type: ignore
    except Exception:                                # noqa: BLE001
        return b""
    out = bytearray()
    want = int(RATE * WIDTH * CHANNELS * max(1.0, float(most_seconds)))
    try:
        with av.open(str(path)) as container:
            stream = next((s for s in container.streams if s.type == "audio"),
                          None)
            if stream is None:
                return b""
            stream.thread_type = "AUTO"
            resampler = av.audio.resampler.AudioResampler(
                format="s16", layout="mono", rate=RATE)
            for packet in container.demux(stream):
                for raw in packet.decode():
                    for got in (resampler.resample(raw) or []):
                        out.extend(bytes(got.planes[0]))
                        if len(out) >= want:
                            return bytes(out[:want])
    except Exception:                                # noqa: BLE001
        return bytes(out[:want]) if out else b""
    return bytes(out[:want])


def frame_of(path: str, at_share: float = 0.45, most_px: int = 512) -> bytes:
    """One representative frame of a video clip, as JPEG bytes.

    [#1386] "I want him using thumbnail recognition to find good clips
    fitting for the moment."

    NOT the first frame. A grabbed clip opens on a fade, a slate or a
    black field more often than not, and a thumbnail of black tells the
    model nothing and the index less. `at_share` lands it just past the
    middle, where the clip is actually showing whatever it is about.

    Scaled down on the way out: the vision model does not see more with
    1080 lines than with 512, and the difference is the whole picture
    travelling through a base64 string on every call.

    Returns b"" for anything that will not open, has no video stream, or
    decodes to nothing - all of which are ordinary in a library this size
    and none of which are worth an exception."""
    try:
        import av                                    # type: ignore
    except Exception:                                # noqa: BLE001
        return b""
    try:
        with av.open(str(path)) as container:
            stream = next((x for x in container.streams if x.type == "video"),
                          None)
            if stream is None:
                return b""
            stream.thread_type = "AUTO"
            # Seek to the share, when the clip knows its own length.
            try:
                dur = float(container.duration or 0) / 1_000_000.0
                if dur > 0.6:
                    where = int(max(0.0, dur * float(at_share)) * 1_000_000)
                    container.seek(where, any_frame=False, backward=True)
            except Exception:                        # noqa: BLE001
                pass
            for packet in container.demux(stream):
                for got in packet.decode():
                    img = got.to_image()
                    w, h = img.size
                    if max(w, h) > most_px:
                        scale = most_px / float(max(w, h))
                        img = img.resize((max(1, int(w * scale)),
                                          max(1, int(h * scale))))
                    out = io.BytesIO()
                    img.convert("RGB").save(out, format="JPEG", quality=78)
                    return out.getvalue()
    except Exception:                                # noqa: BLE001
        return b""
    return b""


def transcribe_pcm(pcm: bytes, host: str = WYOMING_HOST,
                   port: int = WYOMING_PORT, timeout: float = 45.0,
                   language: str = "en") -> str:
    """One clip's words, through wyoming. "" when it said nothing."""
    if not pcm:
        return ""
    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout)
    except OSError:
        return ""
    try:
        sock.settimeout(timeout)
        sock.sendall(frame("transcribe", {"language": language} if language else {}))
        sock.sendall(frame("audio-start", {"rate": RATE, "width": WIDTH,
                                           "channels": CHANNELS,
                                           "timestamp": 0}))
        step = CHUNK_FRAMES * WIDTH * CHANNELS
        for at in range(0, len(pcm), step):
            sock.sendall(frame("audio-chunk",
                               {"rate": RATE, "width": WIDTH,
                                "channels": CHANNELS,
                                "timestamp": int(at / (RATE * WIDTH) * 1000)},
                               pcm[at:at + step]))
        sock.sendall(frame("audio-stop", {"timestamp": 0}))
        buf = bytearray()
        while True:
            got = read_event(sock, buf)
            if got is None:
                return ""
            kind, data, _payload = got
            if kind == "transcript":
                return " ".join(str(data.get("text") or "").split())
            if kind in ("error", "audio-stop"):
                return ""
    except (OSError, socket.timeout):
        return ""
    finally:
        try:
            sock.close()
        except OSError:
            pass


def transcribe_file(path: str, **kw: Any) -> str:
    return transcribe_pcm(pcm_of(path), **kw)


def words_of(text: Any) -> list[str]:
    """The sayable words of a transcript, for the index. Cheap and dumb on
    purpose: sfx_match owns the stemming and the stop list, and this must
    not grow a second opinion about either."""
    body = " ".join(str(text or "").lower().split())
    return [w for w in body.replace("'", "").split() if w.isalpha()]

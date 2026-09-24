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
import secrets
import socket
import time
from contextlib import nullcontext
from typing import Any, Callable, Iterator

import sfx_match

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


class IncrementalClipIndexer:
    """Durable, bounded speech/vision work over the existing clip book.

    The `clips` completion columns remain the source of coverage truth and
    `sfx_meta` stores which lane gets the next tick. `sfx_index_work` only
    owns leases and retry evidence. No loop or service call lives here: a
    supervisor supplies processors and invokes `run_next` whenever resources
    permit, so playback is never queued behind indexing.
    """

    LANES = {
        "speech": {
            "value": "said", "done": "said_at", "total": "playable",
            "complete": "listened", "productive": "with_words",
            "where": "c.playable = 1 AND c.seconds > 0 AND c.seconds <= ?",
        },
        "vision": {
            "value": "seen_desc", "done": "seen_desc_at", "total": "video",
            "complete": "looked_at", "productive": "described",
            "where": "c.playable = 1 AND c.video = 1 AND c.seconds > 0",
        },
    }

    def __init__(self, connection: Any, *, clock: Callable[[], float] = time.time,
                 lock: Any = None, lease_seconds: float = 180.0,
                 retry_base_seconds: float = sfx_match.INDEX_RETRY_BASE_SECONDS,
                 retry_max_seconds: float = sfx_match.INDEX_RETRY_MAX_SECONDS):
        self.connection = connection
        self.clock = clock
        self.lock = lock
        self.lease_seconds = max(5.0, float(lease_seconds))
        self.retry_base_seconds = max(1.0, float(retry_base_seconds))
        self.retry_max_seconds = max(self.retry_base_seconds,
                                     float(retry_max_seconds))
        self._ensure_schema()

    def _guard(self) -> Any:
        return self.lock if self.lock is not None else nullcontext()

    def _ensure_schema(self) -> None:
        with self._guard():
            columns = {str(row[1]) for row in
                       self.connection.execute("PRAGMA table_info(clips)")}
            for name, declaration in (
                    ("said", "TEXT"), ("said_at", "REAL"),
                    ("seen_desc", "TEXT"), ("seen_desc_at", "REAL")):
                if name not in columns:
                    self.connection.execute(
                        "ALTER TABLE clips ADD COLUMN %s %s" % (name, declaration))
            self.connection.execute("""CREATE TABLE IF NOT EXISTS sfx_meta (
                name TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )""")
            self.connection.execute("""CREATE TABLE IF NOT EXISTS sfx_index_work (
                kind TEXT NOT NULL,
                path TEXT NOT NULL,
                claims INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0,
                completed INTEGER NOT NULL DEFAULT 0,
                productive INTEGER NOT NULL DEFAULT 0,
                started INTEGER NOT NULL DEFAULT 0,
                claimed_at REAL NOT NULL DEFAULT 0,
                claimed_until REAL NOT NULL DEFAULT 0,
                claim_token TEXT NOT NULL DEFAULT '',
                last_attempt_at REAL NOT NULL DEFAULT 0,
                retry_at REAL NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (kind, path)
            )""")
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS sfx_index_ready "
                "ON sfx_index_work(kind, retry_at, claimed_until)")
            self.connection.commit()

    def _lane(self, kind: Any) -> tuple[str, dict[str, str]]:
        key = str(kind or "").lower()
        if key not in self.LANES:
            raise ValueError("index kind must be speech or vision")
        return key, self.LANES[key]

    def claim(self, kind: str, limit: int = 0) -> list[dict[str, Any]]:
        """Lease one bounded batch; overlapping workers cannot share a row."""
        key, lane = self._lane(kind)
        wanted = sfx_match.index_batch_size(limit)
        now = float(self.clock())
        params: list[Any] = [key]
        duration = ""
        if key == "speech":
            duration = lane["where"]
            params.append(float(MOST_SECONDS))
        else:
            duration = lane["where"]
        params.extend((now, now, wanted))
        with self._guard():
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                rows = self.connection.execute(
                    "SELECT c.rowid, c.path, c.seconds, c.video, "
                    "COALESCE(w.attempts, 0), COALESCE(w.failures, 0) "
                    "FROM clips c LEFT JOIN sfx_index_work w "
                    "ON w.kind = ? AND w.path = c.path WHERE " + duration +
                    " AND c.%s IS NULL " % lane["done"] +
                    "AND COALESCE(w.retry_at, 0) <= ? "
                    "AND COALESCE(w.claimed_until, 0) <= ? "
                    "ORDER BY COALESCE(w.attempts, 0), c.seconds, c.rowid "
                    "LIMIT ?", tuple(params)).fetchall()
                jobs: list[dict[str, Any]] = []
                for row in rows:
                    token = secrets.token_hex(12)
                    path = str(row[1])
                    self.connection.execute(
                        "INSERT INTO sfx_index_work "
                        "(kind,path,claims,claimed_at,claimed_until,claim_token,updated_at) "
                        "VALUES (?,?,1,?,?,?,?) ON CONFLICT(kind,path) DO UPDATE SET "
                        "claims=claims+1, claimed_at=excluded.claimed_at, "
                        "claimed_until=excluded.claimed_until, "
                        "claim_token=excluded.claim_token, started=0, "
                        "updated_at=excluded.updated_at",
                        (key, path, now, now + self.lease_seconds, token, now))
                    jobs.append({"kind": key, "rowid": int(row[0]), "path": path,
                                 "seconds": float(row[2] or 0),
                                 "video": bool(row[3]), "token": token,
                                 "attempts": int(row[4]), "failures": int(row[5])})
                self.connection.commit()
                return jobs
            except Exception:
                self.connection.rollback()
                raise

    def start(self, job: dict[str, Any]) -> bool:
        now = float(self.clock())
        with self._guard():
            cur = self.connection.execute(
                "UPDATE sfx_index_work SET attempts=attempts+1, started=1, "
                "last_attempt_at=?, updated_at=? WHERE kind=? AND path=? "
                "AND claim_token=? AND claimed_until>=? AND started=0",
                (now, now, job["kind"], job["path"], job["token"], now))
            self.connection.commit()
            return bool(cur.rowcount)

    def release(self, job: dict[str, Any]) -> bool:
        """Return an unstarted lease without spending an attempt."""
        now = float(self.clock())
        with self._guard():
            cur = self.connection.execute(
                "UPDATE sfx_index_work SET claim_token='', claimed_until=0, "
                "updated_at=? WHERE kind=? AND path=? AND claim_token=? AND started=0",
                (now, job["kind"], job["path"], job["token"]))
            self.connection.commit()
            return bool(cur.rowcount)

    def finish(self, job: dict[str, Any], value: Any = "", *,
               error: Any = None) -> bool:
        """Commit one result, or persist a cooled-down retry after failure."""
        key, lane = self._lane(job.get("kind"))
        now = float(self.clock())
        with self._guard():
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                current = self.connection.execute(
                    "SELECT failures FROM sfx_index_work WHERE kind=? AND path=? "
                    "AND claim_token=? AND claimed_until>=? AND started=1",
                    (key, job["path"], job["token"], now)).fetchone()
                if current is None:
                    self.connection.rollback()
                    return False
                if error is None:
                    text = " ".join(str(value or "").split())[:1200]
                    cur = self.connection.execute(
                        "UPDATE clips SET %s=?, %s=? WHERE path=? AND %s IS NULL"
                        % (lane["value"], lane["done"], lane["done"]),
                        (text, now, job["path"]))
                    if not cur.rowcount:
                        self.connection.rollback()
                        return False
                    self.connection.execute(
                        "UPDATE sfx_index_work SET completed=1, productive=?, "
                        "started=0, claim_token='', claimed_until=0, retry_at=0, last_error='', "
                        "updated_at=? WHERE kind=? AND path=?",
                        (1 if text else 0, now, key, job["path"]))
                else:
                    failures = int(current[0] or 0) + 1
                    delay = sfx_match.index_retry_seconds(
                        failures, self.retry_base_seconds, self.retry_max_seconds)
                    self.connection.execute(
                        "UPDATE sfx_index_work SET failures=?, retry_at=?, "
                        "last_error=?, started=0, claim_token='', claimed_until=0, updated_at=? "
                        "WHERE kind=? AND path=?",
                        (failures, now + delay, str(error)[:240], now,
                         key, job["path"]))
                self.connection.commit()
                return True
            except Exception:
                self.connection.rollback()
                raise

    def run_batch(self, kind: str, processor: Callable[[dict[str, Any]], Any],
                  limit: int = 0, *, should_stop: Callable[[], Any] | None = None,
                  on_indexed: Callable[[dict[str, Any], str], Any] | None = None,
                  yield_hook: Callable[[], Any] | None = None) -> dict[str, Any]:
        """Run at most one batch, yielding between items when requested."""
        jobs = self.claim(kind, limit)
        result = {"kind": str(kind), "selected": len(jobs), "attempted": 0,
                  "completed": 0, "productive": 0, "failed": 0, "released": 0}
        for offset, job in enumerate(jobs):
            if should_stop is not None and should_stop():
                for pending in jobs[offset:]:
                    result["released"] += int(self.release(pending))
                break
            if not self.start(job):
                continue
            result["attempted"] += 1
            try:
                value = " ".join(str(processor(job) or "").split())
                if self.finish(job, value):
                    result["completed"] += 1
                    result["productive"] += int(bool(value))
                    if on_indexed is not None and value:
                        on_indexed(job, value)
            except Exception as exc:  # noqa: BLE001
                if self.finish(job, error=exc):
                    result["failed"] += 1
            if yield_hook is not None:
                yield_hook()
        result["progress"] = self.progress(kind)
        return result

    def _meta(self, name: str, default: str = "") -> str:
        row = self.connection.execute(
            "SELECT value FROM sfx_meta WHERE name=?", (name,)).fetchone()
        return str(row[0]) if row is not None else default

    def _set_meta(self, name: str, value: str) -> None:
        with self._guard():
            self.connection.execute(
                "INSERT INTO sfx_meta(name,value) VALUES (?,?) "
                "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                (name, value))
            self.connection.commit()

    def run_next(self, processors: dict[str, Callable[[dict[str, Any]], Any]],
                 limits: dict[str, int] | None = None, **kwargs: Any) -> dict[str, Any]:
        """Advance one persistent lane per scheduler tick, then rotate."""
        lane = self._meta("incremental_index_next_lane", "speech")
        if lane not in self.LANES or lane not in processors:
            lane = next((name for name in sfx_match.INDEX_LANES
                         if name in processors), "")
        if not lane:
            raise ValueError("at least one speech or vision processor is required")
        result = self.run_batch(lane, processors[lane],
                                int((limits or {}).get(lane) or 0), **kwargs)
        other = sfx_match.index_lane_after(lane)
        self._set_meta("incremental_index_next_lane",
                       other if other in processors else lane)
        result["next_kind"] = self._meta("incremental_index_next_lane", lane)
        return result

    def progress(self, kind: str) -> dict[str, Any]:
        """Aggregate coverage plus durable attempt/retry counters."""
        key, lane = self._lane(kind)
        total_where = "playable=1" if key == "speech" else "playable=1 AND video=1"
        row = self.connection.execute(
            "SELECT COUNT(*), SUM(CASE WHEN %s IS NOT NULL THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN COALESCE(%s, '') <> '' THEN 1 ELSE 0 END) "
            "FROM clips WHERE %s" % (lane["done"], lane["value"], total_where)).fetchone()
        now = float(self.clock())
        work = self.connection.execute(
            "SELECT COALESCE(SUM(claims),0), COALESCE(SUM(attempts),0), "
            "COALESCE(SUM(failures),0), "
            "SUM(CASE WHEN retry_at>? THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN claimed_until>? AND claim_token<>'' THEN 1 ELSE 0 END), "
            "MIN(CASE WHEN retry_at>? THEN retry_at END) "
            "FROM sfx_index_work WHERE kind=?", (now, now, now, key)).fetchone()
        total, completed, productive = (int(row[0] or 0), int(row[1] or 0),
                                        int(row[2] or 0))
        out = {lane["total"]: total, lane["complete"]: completed,
               lane["productive"]: productive, "left": max(0, total - completed),
               "claims": int(work[0] or 0), "attempts": int(work[1] or 0),
               "failures": int(work[2] or 0), "retrying": int(work[3] or 0),
               "claimed": int(work[4] or 0),
               "next_retry_at": float(work[5] or 0)}
        return out

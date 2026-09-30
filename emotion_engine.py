"""[emotion-engine] the emotion engine's own window: queue, tasks, audit, before/after.

2026-09-30, the operator: "offer a tab for showing the popup about the emotion
engine, I want to see the queue of it, tasks performed, audit log, before and
after player of clips, prompt history, resource monitor and roulette interaction
indented result log." Chosen: a tab in the Voice actors popup with sub-tabs;
before/after = the engine's RAW take vs the emotion-SHAPED final; the queue =
every line waiting for voice; resources = voice-engine GPU/VRAM, per-clip
timings, box temperature + CPU + RAM, queue depth over time.

Every voiced line passes one door - app.voice_generate - and this module is
told three things there: a line entered (begin), the engine answered with the
raw take (synthed), and the shaped take was stored (shaped). It keeps the raw
take as its own media file (the same signed /media/<key>?t= road as every clip),
so the page can play the two side by side. The roulette log and the direction
the writer was given are System 3's record of the line (/api/system3/line),
which the page reads per task; this module does not copy them.

Bounded everywhere: TASKS_KEPT tasks, RAW_KEPT raw takes on disk, AUDIT_KEPT
audit rows, one sample every SAMPLE_S for HISTORY_S.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from collections import deque
from typing import Any

TASKS_KEPT = 120
RAW_KEPT = 60
AUDIT_KEPT = 300
SAMPLE_S = 10.0
HISTORY_S = 3600.0
LOST_S = 240.0           # a task that never finished is marked lost

_LOCK = threading.RLock()
_TASKS: "deque[dict[str, Any]]" = deque(maxlen=TASKS_KEPT)
_BY_ID: dict[str, dict[str, Any]] = {}
_AUDIT: "deque[dict[str, Any]]" = deque(maxlen=AUDIT_KEPT)
_HISTORY: "deque[dict[str, Any]]" = deque(maxlen=int(HISTORY_S / SAMPLE_S) + 1)
_RAW_KEYS: "deque[str]" = deque()
_NS: dict[str, Any] = {}
_CPU_LAST: list[float] = [0.0, 0.0]


def _audit(tid: str, what: str, **extra: Any) -> None:
    row = {"at": time.time(), "task": tid, "what": what}
    row.update({k: v for k, v in extra.items() if v is not None})
    _AUDIT.append(row)


def _es_numbers(es: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    if isinstance(es, dict):
        for k in ("tempo", "pitch", "range", "energy", "pause", "temp"):
            try:
                if k in es:
                    out[k] = round(float(es[k]), 3)
            except (TypeError, ValueError):
                pass
    return out


def begin(line: str, speaker: str, engine: str, voice: str, text: str, es: Any) -> str:
    """A line entered the voice door: it waits for the engine, then renders."""
    tid = uuid.uuid4().hex[:10]
    row = {"id": tid, "line": str(line or ""), "speaker": str(speaker or ""),
           "engine": str(engine or ""), "voice": str(voice or "")[:60],
           "text": str(text or "")[:400], "es": _es_numbers(es),
           "shaped_by_es": bool(_es_numbers(es)), "state": "queued",
           "at": time.time(), "synth_ms": None, "dsp_ms": None, "total_ms": None,
           "seconds": None, "raw": None, "final": None, "why": ""}
    with _LOCK:
        _TASKS.append(row)
        _BY_ID[tid] = row
        while len(_BY_ID) > TASKS_KEPT * 2:
            _BY_ID.pop(next(iter(_BY_ID)))
    _audit(tid, "entered the voice door", engine=row["engine"], speaker=row["speaker"],
           es=row["es"] or None)
    return tid


def rendering(tid: str) -> None:
    with _LOCK:
        row = _BY_ID.get(tid)
        if row and row["state"] == "queued":
            row["state"] = "rendering"
            row["render_at"] = time.time()


def synthed(tid: str, raw: bytes, ext: str) -> None:
    """The engine answered: keep its raw take for the before/after player."""
    with _LOCK:
        row = _BY_ID.get(tid)
    if not row:
        return
    row["synth_ms"] = int((time.time() - float(row.get("render_at") or row["at"])) * 1000)
    row["state"] = "shaping"
    media_dir = _NS.get("VOICE_MEDIA_DIR")
    if media_dir is not None and raw and str(ext or "").lower() in ("wav", "mp3"):
        try:
            key = uuid.uuid4().hex + "." + str(ext).lower()
            media_dir.mkdir(parents=True, exist_ok=True)
            (media_dir / key).write_bytes(raw)
            row["raw"] = key
            _RAW_KEYS.append(key)
            while len(_RAW_KEYS) > RAW_KEPT:
                old = _RAW_KEYS.popleft()
                try:
                    (media_dir / old).unlink()
                except OSError:
                    pass
        except Exception as exc:  # noqa: BLE001
            _audit(tid, "the raw take could not be kept", why=str(exc)[:120])
    _audit(tid, "the engine answered", ms=row["synth_ms"], bytes=len(raw or b""))


def shaped(tid: str, key: str, dsp_ms: int, seconds: float | None) -> None:
    with _LOCK:
        row = _BY_ID.get(tid)
    if not row:
        return
    row["final"] = str(key or "")
    row["dsp_ms"] = int(dsp_ms)
    row["seconds"] = round(float(seconds or 0), 2) if seconds else None
    row["total_ms"] = int((time.time() - row["at"]) * 1000)
    row["state"] = "done"
    _audit(tid, "shaped and stored" if row["shaped_by_es"] else "stored (no emotion shaping on this line)",
           dsp_ms=row["dsp_ms"], es=row["es"] or None)


def failed(tid: str, why: str) -> None:
    with _LOCK:
        row = _BY_ID.get(tid)
    if not row:
        return
    row["state"] = "failed"
    row["why"] = str(why or "")[:200]
    row["total_ms"] = int((time.time() - row["at"]) * 1000)
    _audit(tid, "failed", why=row["why"])


def _lost_sweep(now: float) -> None:
    for row in list(_TASKS):
        if row["state"] in ("queued", "rendering", "shaping") and now - row["at"] > LOST_S:
            row["state"] = "lost"
            row["why"] = row["why"] or "no answer from the voice door within %d s" % LOST_S
            _audit(row["id"], "lost", why=row["why"])


def _gpu() -> dict[str, Any]:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=6)
        row = (out.stdout or "").strip().splitlines()[0].split(",")
        vals = [v.strip() for v in row]

        def num(v: str) -> float | None:
            try:
                return float(v)
            except ValueError:
                return None
        return {"util": num(vals[0]), "vram_used_mb": num(vals[1]), "vram_total_mb": num(vals[2]),
                "temp_c": num(vals[3])}
    except Exception:  # noqa: BLE001
        return {}


def _cpu_pct() -> float | None:
    try:
        with open("/proc/stat", encoding="utf-8") as fh:
            parts = [float(x) for x in fh.readline().split()[1:]]
        idle, total = parts[3] + (parts[4] if len(parts) > 4 else 0), sum(parts)
        d_idle, d_total = idle - _CPU_LAST[0], total - _CPU_LAST[1]
        _CPU_LAST[0], _CPU_LAST[1] = idle, total
        return round(100.0 * (1 - d_idle / d_total), 1) if d_total > 0 else None
    except Exception:  # noqa: BLE001
        return None


def _mem() -> dict[str, Any]:
    try:
        info: dict[str, int] = {}
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                k, v = line.split(":", 1)
                info[k] = int(v.strip().split()[0])
        total, avail = info.get("MemTotal", 0), info.get("MemAvailable", 0)
        return {"ram_used_gb": round((total - avail) / 1048576, 1), "ram_total_gb": round(total / 1048576, 1)}
    except Exception:  # noqa: BLE001
        return {}


def _box_temp() -> float | None:
    best = None
    try:
        base = "/sys/class/thermal"
        for zone in os.listdir(base):
            try:
                with open(os.path.join(base, zone, "temp"), encoding="utf-8") as fh:
                    c = int(fh.read().strip()) / 1000.0
                best = c if best is None else max(best, c)
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return round(best, 1) if best is not None else None


def queue_rows() -> list[dict[str, Any]]:
    with _LOCK:
        rows = [dict(r) for r in _TASKS if r["state"] in ("queued", "rendering", "shaping")]
    rows.sort(key=lambda r: r["at"])
    for i, r in enumerate(rows):
        r["place"] = i + 1
        r["waited_s"] = round(time.time() - r["at"], 1)
    return rows


def _sampler() -> None:
    _cpu_pct()
    while True:
        try:
            now = time.time()
            _lost_sweep(now)
            sample = {"at": now, "depth": len(queue_rows()), "cpu": _cpu_pct(), "box_c": _box_temp()}
            sample.update(_gpu())
            sample.update(_mem())
            _HISTORY.append(sample)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(SAMPLE_S)


def _signed(key: str | None) -> str | None:
    if not key:
        return None
    sign = _NS.get("media_sign")
    try:
        return "/media/%s?t=%s" % (key, sign(key)) if sign else "/media/" + key
    except Exception:  # noqa: BLE001
        return "/media/" + key


def state(limit: int = 60) -> dict[str, Any]:
    with _LOCK:
        tasks = [dict(r) for r in list(_TASKS)[-max(1, min(limit, TASKS_KEPT)):]]
        audit = list(_AUDIT)[-200:]
        hist = list(_HISTORY)
    for t in tasks:
        t["raw_url"] = _signed(t.get("raw"))
        t["final_url"] = _signed(t.get("final"))
    done = [t for t in tasks if t["state"] == "done"]
    timing = {}
    if done:
        for k in ("synth_ms", "dsp_ms", "total_ms"):
            vals = [t[k] for t in done if isinstance(t.get(k), (int, float))]
            if vals:
                timing[k] = {"mean": int(sum(vals) / len(vals)), "max": int(max(vals)), "n": len(vals)}
    return {"ok": True, "at": time.time(), "queue": queue_rows(), "tasks": list(reversed(tasks)),
            "audit": list(reversed(audit)), "history": hist, "now": hist[-1] if hist else {},
            "timing": timing, "kept": {"tasks": TASKS_KEPT, "raw": RAW_KEPT, "audit": AUDIT_KEPT}}


def install(app: Any, ns: dict[str, Any]) -> None:
    _NS.update({k: ns.get(k) for k in ("VOICE_MEDIA_DIR", "media_sign")})
    require = ns.get("require_read_auth")
    Header = ns.get("Header")

    @app.get("/api/emotion/state")
    async def emotion_state_api(limit: int = 60, authorization: str | None = Header(default=None)):
        if require:
            require(authorization)
        return state(limit)

    threading.Thread(target=_sampler, name="emotion-engine-sampler", daemon=True).start()

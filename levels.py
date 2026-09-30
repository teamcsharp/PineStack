"""[levels-one] THE ONE SET OF LEVELS, ON THE STATION.

"the goal with the audio is to unify and have it all controlled by a single
unified system." The operator's answers (2026-09-30): one set, station-wide
(move a slider on the tablet and the desk follows); a MASTER everything follows;
the native sampler pads as their own row; the Pine Box speaker as a Box route in
the same system.

The bus (desktop/renderer/audio-law.js, window.pineLevels) stays the only thing
that turns a level into sound on a surface; this is where its numbers live now,
instead of each browser's localStorage. Every surface reads it (GET, polled) and
writes it (POST); `rev` orders the writes.

Seeding - "I just don't want the audio to go louder than the level that I have
it set at": the first surface to arrive seeds the store with its own levels, and
every surface after that ADOPTS: a kind it had lower than the station's pulls the
station down to it (the quieter wins), so no surface ever gets louder than it was
set when the one store takes over. Nothing is ever raised by a merge.

Pure: no station imports, so its tests stay fast.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

KINDS = ("master", "voice", "music", "sfx", "video", "pads")
CEIL = {"master": 1.0, "voice": 2.0, "music": 2.0, "sfx": 2.0, "video": 2.0, "pads": 2.0}
NEUTRAL = 1.0

_LOCK = threading.Lock()
_MEMO: dict[str, Any] = {"at": 0.0, "got": None, "path": ""}


def clamp(kind: str, value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n:                      # NaN
        return None
    return round(max(0.0, min(CEIL.get(kind, 1.0), n)), 4)


def _read(path: Path) -> dict[str, Any]:
    now = time.time()
    if _MEMO["path"] == str(path) and now - float(_MEMO["at"]) < 0.5 and _MEMO["got"] is not None:
        return dict(_MEMO["got"])
    try:
        got = json.loads(path.read_text())
        got = got if isinstance(got, dict) else {}
    except Exception:  # noqa: BLE001
        got = {}
    _MEMO.update({"at": now, "got": dict(got), "path": str(path)})
    return got


def _write(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc))
    tmp.replace(path)
    _MEMO.update({"at": time.time(), "got": dict(doc), "path": str(path)})


def state(path: Path) -> dict[str, Any]:
    """{"levels": {kind: value} | None (never seeded), "rev", "at", "by"}."""
    doc = _read(path)
    lv = doc.get("levels") if isinstance(doc.get("levels"), dict) else None
    out = None
    if lv is not None:
        out = {k: (clamp(k, lv.get(k)) if clamp(k, lv.get(k)) is not None else NEUTRAL) for k in KINDS}
    return {"levels": out, "rev": int(doc.get("rev") or 0), "at": float(doc.get("at") or 0),
            "by": str(doc.get("by") or "")}


def _clean(values: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in (values or {}).items() if isinstance(values, dict) else ():
        if k in KINDS:
            c = clamp(k, v)
            if c is not None:
                out[k] = c
    return out


def write(path: Path, values: Any, by: str = "") -> dict[str, Any]:
    """An operator's move: the named kinds, as given. Unseeded kinds stay 1."""
    want = _clean(values)
    with _LOCK:
        cur = state(path)
        lv = dict(cur["levels"] or {k: NEUTRAL for k in KINDS})
        if not want:
            return dict(cur, changed=[])
        changed = [k for k, v in want.items() if abs(lv.get(k, NEUTRAL) - v) > 1e-6]
        lv.update(want)
        doc = {"levels": lv, "rev": cur["rev"] + (1 if changed else 0), "at": time.time(),
               "by": str(by or "")[:60] if changed else cur["by"]}
        if changed or cur["levels"] is None:
            _write(path, doc)
        return dict(state(path), changed=changed)


def adopt(path: Path, values: Any, by: str = "") -> dict[str, Any]:
    """A surface joining the one store with the levels it had: the first seeds
    it; later ones pull a kind DOWN to theirs when theirs was quieter. Never up."""
    have = _clean(values)
    with _LOCK:
        cur = state(path)
        if cur["levels"] is None:
            lv = {k: have.get(k, NEUTRAL) for k in KINDS}
            _write(path, {"levels": lv, "rev": cur["rev"] + 1, "at": time.time(),
                          "by": ("seeded by " + str(by or "a surface"))[:60]})
            return dict(state(path), seeded=True, lowered=[])
        lv = dict(cur["levels"])
        lowered = [k for k, v in have.items() if v < lv.get(k, NEUTRAL) - 1e-6]
        for k in lowered:
            lv[k] = have[k]
        if lowered:
            _write(path, {"levels": lv, "rev": cur["rev"] + 1, "at": time.time(),
                          "by": ("adopted by " + str(by or "a surface"))[:60]})
        return dict(state(path), seeded=False, lowered=lowered)

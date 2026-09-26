"""Repeat diagnosis helpers for dialogue lines."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


def normalize(text: Any) -> str:
    return " ".join(re.findall(r"\w+", str(text or "").casefold()))


def fingerprint(text: Any) -> str:
    key = normalize(text)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] if key else ""


def script_contains(script: Any, text: Any) -> bool:
    needle = normalize(text)
    return bool(needle and needle in normalize(script))


def read_calls(path: str | Path, since: float = 0.0) -> tuple[list[dict[str, Any]], bool]:
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError:
        return [], False
    clipped = False
    limit = 32 * 1024 * 1024
    if len(data) > limit:
        data = data[-limit:]
        clipped = True
        nl = data.find(b"\n")
        if nl >= 0:
            data = data[nl + 1:]
    rows: list[dict[str, Any]] = []
    for raw in data.decode("utf-8", "replace").splitlines():
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        try:
            at = float(row.get("at") or row.get("ts") or 0)
        except (TypeError, ValueError):
            at = 0.0
        if at >= float(since or 0):
            rows.append(row)
    return rows, clipped


def _text_of(row: dict[str, Any]) -> str:
    for key in ("text", "line", "script", "prompt", "response", "content"):
        got = row.get(key)
        if got:
            return str(got)
    return ""


def analyze(text: Any, rows: list[dict[str, Any]], calls: list[dict[str, Any]],
            now: float = 0.0) -> dict[str, Any]:
    key = normalize(text)
    air_hits = [row for row in rows if normalize(_text_of(row)) == key]
    loose_air = [row for row in rows if key and key in normalize(_text_of(row))]
    writing_hits = [row for row in calls if key and key in normalize(_text_of(row))]
    causes: list[str] = []
    if len(air_hits) > 1:
        causes.append("The exact line appears %d times in recent air." % len(air_hits))
    elif loose_air:
        causes.append("A close recent air row contains this line.")
    if writing_hits:
        causes.append("Recent writing/model evidence contains the line.")
    if not causes:
        causes.append("No recent repeat cause was found in retained logs.")
    return {
        "text": str(text or ""),
        "repeat_key": fingerprint(text),
        "airings": len(air_hits),
        "near_airings": len(loose_air),
        "writing_hits": len(writing_hits),
        "causes": causes,
        "coverage": "Checked retained air rows and recent model-call records.",
        "examples": [
            {"at": row.get("at") or row.get("ts"), "who": row.get("who"),
             "kind": row.get("kind"), "text": _text_of(row)[:300]}
            for row in (air_hits or loose_air)[:8]
        ],
    }

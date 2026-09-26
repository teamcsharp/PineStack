"""Durable exact-line blacklist used by the broadcast writer."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from threading import RLock
from typing import Any


def _norm(text: str) -> str:
    return " ".join(re.findall(r"\w+", str(text or "").casefold()))


class Blacklist:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = RLock()
        self._rows: list[dict[str, Any]] | None = None

    def _load(self) -> list[dict[str, Any]]:
        if self._rows is not None:
            return self._rows
        try:
            raw = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError, TypeError):
            raw = []
        if isinstance(raw, dict):
            rows = list(raw.get("rows") or raw.get("lines") or [])
        elif isinstance(raw, list):
            rows = raw
        else:
            rows = []
        clean: list[dict[str, Any]] = []
        for row in rows:
            if isinstance(row, str):
                text, line_id = row, ""
            elif isinstance(row, dict):
                text, line_id = str(row.get("text") or ""), str(row.get("line_id") or "")
            else:
                continue
            key = _norm(text)
            if key:
                clean.append({"text": text, "line_id": line_id, "key": key,
                              "at": float((row if isinstance(row, dict) else {}).get("at") or 0)})
        self._rows = clean
        return self._rows

    @property
    def has_entries(self) -> bool:
        return bool(self._load())

    def contains(self, text: str) -> bool:
        key = _norm(text)
        return bool(key and any(row.get("key") == key for row in self._load()))

    def add(self, text: str, line_id: str = "") -> dict[str, Any]:
        key = _norm(text)
        if not key:
            raise ValueError("A non-empty dialogue line is required")
        with self._lock:
            rows = self._load()
            for row in rows:
                if row.get("key") == key:
                    return dict(row)
            row = {"text": str(text), "line_id": str(line_id or ""),
                   "key": key, "at": time.time()}
            rows.append(row)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=1), "utf-8")
            tmp.replace(self.path)
            return dict(row)

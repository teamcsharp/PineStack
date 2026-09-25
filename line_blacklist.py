"""Persistent operator blacklist for complete spoken lines."""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
import time


_LOCK = RLock()
_CACHE: dict[Path, tuple[float, dict[str, dict]]] = {}
_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_INNER_APOSTROPHE = re.compile(r"(?<=[^\W_])['\u2019](?=[^\W_])", re.UNICODE)


def _key(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    folded = _INNER_APOSTROPHE.sub("", folded)
    return " ".join(_WORDS.findall(folded))


class Blacklist:
    """Atomic JSON store keyed by normalized whole lines."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read(self) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict) or any(
            not isinstance(key, str) or not isinstance(row, dict)
            or not isinstance(row.get("text"), str)
            or not isinstance(row.get("line_id"), str)
            or not isinstance(row.get("timestamp"), str)
            for key, row in data.items()
        ):
            raise ValueError("invalid line blacklist JSON")
        return data

    def _cached_read(self) -> dict[str, dict]:
        cached = _CACHE.get(self.path)
        if cached is None or time.monotonic() - cached[0] > 2.0:
            cached = (time.monotonic(), self._read())
            _CACHE[self.path] = cached
        return cached[1]

    def _write(self, data: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=f".{self.path.name}.", suffix=".tmp", delete=False,
            ) as handle:
                name = handle.name
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
        finally:
            if name is not None:
                Path(name).unlink(missing_ok=True)

    def add(self, text: str, line_id: str) -> dict:
        if not isinstance(text, str) or not (key := _key(text)):
            raise ValueError("line text must contain a word or number")
        with _LOCK:
            data = self._read()
            if key not in data:
                data[key] = {
                    "text": text,
                    "line_id": str(line_id),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                self._write(data)
                _CACHE[self.path] = (time.monotonic(), data)
            return {"normalized": key, **data[key]}

    def contains(self, text: str) -> bool:
        if not isinstance(text, str):
            raise TypeError("line text must be a string")
        key = _key(text)
        if not key:
            return False
        with _LOCK:
            return key in self._cached_read()

    @property
    def has_entries(self) -> bool:
        with _LOCK:
            return bool(self._cached_read())

    @property
    def rows(self) -> list[dict]:
        with _LOCK:
            data = self._read()
            _CACHE[self.path] = (time.monotonic(), data)
            return [{"normalized": key, **row} for key, row in data.items()]

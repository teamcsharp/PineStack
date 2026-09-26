"""Lightweight Git changelog reader with task annotations."""
from __future__ import annotations

from datetime import datetime
import json
import subprocess
import time
from pathlib import Path
from threading import RLock
from typing import Any


class ChangeLog:
    def __init__(
        self,
        repo: str | Path,
        task_path: str | Path,
        cache_path: str | Path | None = None,
    ):
        self.repo = Path(repo)
        self.task_path = Path(task_path)
        self.cache_path = Path(cache_path) if cache_path else self.task_path.with_name("changelog_git_cache.json")
        self._lock = RLock()
        self._cache = self._load_cache()

    def _load_cache(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.cache_path.read_text("utf-8"))
            entries = raw.get("entries") if isinstance(raw, dict) else None
            if isinstance(entries, list):
                raw["entries"] = [row for row in entries if isinstance(row, dict)]
                return raw
        except (OSError, ValueError, TypeError):
            pass
        return {"entries": [], "refreshed_at": 0.0}

    def _write_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._cache, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self.cache_path)

    def _tasks(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.task_path.read_text("utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _git_entries(self, limit: int, before: str = "") -> list[dict[str, Any]]:
        count = max(1, min(200, int(limit or 60)))
        args = ["git", "-C", str(self.repo), "log", "--date=iso-strict",
                f"--max-count={count}", "--pretty=format:%H%x1f%h%x1f%ad%x1f%s"]
        if before:
            args.insert(-1, f"--before={before}")
        proc = subprocess.run(args, capture_output=True, text=True, timeout=8)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or "git log failed").strip()[:300])
        tasks = self._tasks()
        rows = []
        for line in proc.stdout.splitlines():
            full, short, date, subject = (line.split("\x1f", 3) + ["", "", "", ""])[:4]
            rows.append({"commit": full, "short": short, "date": date,
                         "subject": subject, "task": tasks.get(full) or tasks.get(short) or {}})
        return rows

    def refresh(self, limit: int = 200) -> dict[str, Any]:
        """Refresh the durable snapshot explicitly; readers never invoke Git."""
        entries = self._git_entries(limit)
        with self._lock:
            existing = {row.get("commit"): row for row in self._cache.get("entries", [])}
            merged = []
            for row in entries:
                # Retain the detailed build snapshot when Git only supplies a title.
                entry = dict(row, **existing.pop(row.get("commit"), {}))
                entry.setdefault("short_commit", row.get("short", ""))
                entry.setdefault("task_name", row.get("subject", ""))
                if "completed_at" not in entry:
                    entry["completed_at"] = datetime.fromisoformat(row["date"]).timestamp()
                entry.setdefault("completed_label", row.get("date", ""))
                merged.append(entry)
            merged.extend(existing.values())
            self._cache = dict(self._cache, entries=merged, refreshed_at=time.time(),
                               head=merged[0].get("commit", "") if merged else "")
            self._write_cache()
        return self.page()

    def page(self, limit: int = 60, before: str = "") -> dict[str, Any]:
        count = max(1, min(200, int(limit or 60)))
        with self._lock:
            cached = dict(self._cache)
            entries = [dict(row) for row in cached.get("entries", [])]
        full_total = len(entries)
        if before:
            try:
                cursor = float(before)
            except (TypeError, ValueError):
                entries = [row for row in entries if str(row.get("date") or "") < before]
            else:
                entries = [row for row in entries if float(row.get("completed_at") or 0.0) < cursor]
        has_more = len(entries) > count
        entries = entries[:count]
        last = entries[-1] if entries else {}
        out = {"entries": entries, "total": full_total,
               "head": str(cached.get("head") or (entries[0].get("commit") if entries else "")),
               "has_more": has_more,
               "next_before": str(last.get("completed_at") or last.get("date") or ""),
               "retroactive": True, "timezone": "America/Chicago",
               "stale": not bool(cached.get("entries")), "warming": False,
               "refreshed_at": float(cached.get("refreshed_at") or 0.0)}
        return out

    def cached_page(self, limit: int = 60, before: str = "") -> dict[str, Any] | None:
        return self.page(limit, before)

    def record(self, commit: str, body: dict[str, Any]) -> dict[str, Any]:
        key = str(commit or "").strip()
        if not key:
            raise ValueError("A Git commit is required")
        with self._lock:
            tasks = self._tasks()
            row = dict(body or {})
            row["commit"] = key
            row["recorded_at"] = time.time()
            tasks[key] = row
            self.task_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.task_path.with_suffix(self.task_path.suffix + ".tmp")
            tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=1), "utf-8")
            tmp.replace(self.task_path)
            for entry in self._cache.get("entries", []):
                if entry.get("commit") == key or entry.get("short") == key or entry.get("short_commit") == key:
                    entry["task"] = row
            self._write_cache()
        return {"ok": True, "commit": key, "task": row}

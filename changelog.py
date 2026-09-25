"""A truthful, Git-backed task history for the Pine Box operator changelog.

Git can answer which source files changed and when a commit landed.  It cannot
recover a prompt, model token count, or elapsed agent time that was never
written down.  ``ChangeLog`` keeps those facts in a tiny sidecar ledger for
new work and makes the absence explicit for older commits.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from zoneinfo import ZoneInfo


_FIELD = "\x1f"
_RECORD = "\x1e"
_END = "\x1d"
_TRAILER = re.compile(r"^Pine-([A-Za-z-]+):\s*(.+?)\s*$", re.M)
try:
    _CHICAGO = ZoneInfo("America/Chicago")
except Exception:  # Windows test hosts may not ship the IANA zone database.
    _CHICAGO = timezone(timedelta(hours=-6), "CST")


def _text(value: Any, limit: int = 4000) -> str:
    return " ".join(str(value or "").split())[:limit]


def _number(value: Any, label: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        answer = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(label + " must be a whole number") from exc
    if answer < 0:
        raise ValueError(label + " cannot be negative")
    return answer


def cst_label(epoch: float | int | None) -> str:
    """The operator's requested fixed-layout date label in station time."""
    if not epoch:
        return "not recorded"
    moment = datetime.fromtimestamp(float(epoch), tz=timezone.utc).astimezone(_CHICAGO)
    hour = str(int(moment.strftime("%I")))
    return moment.strftime("%m-%d-%y / ") + hour + moment.strftime(":%M %p CST")


class ChangeLog:
    """Merge the committed graph with optional, explicitly captured task facts."""

    def __init__(self, repo: str | Path, ledger_path: str | Path):
        self.repo = Path(repo)
        self.ledger_path = Path(ledger_path)
        self.cache_path = self.ledger_path.with_name("changelog_git_cache.json")
        self._lock = RLock()
        self._cache_key: tuple[str, int] | None = None
        self._cache: list[dict[str, Any]] = []

    def _git(self, *args: str, timeout: float = 25) -> str:
        try:
            result = subprocess.run(
                ["git", "-c", "safe.directory=" + str(self.repo), "-C", str(self.repo), *args],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("Git history is unavailable: " + str(exc)[:160]) from exc
        return result.stdout

    def _head(self) -> str:
        return self._git("rev-parse", "HEAD").strip()

    def _ledger_stamp(self) -> int:
        try:
            return self.ledger_path.stat().st_mtime_ns
        except OSError:
            return 0

    def _ledger(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        rows = payload.get("tasks") if isinstance(payload, dict) else {}
        return rows if isinstance(rows, dict) else {}

    def _disk_cache(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
            return {}
        return payload

    def _save_disk_cache(self, head: str, ledger_stamp: int, rows: list[dict[str, Any]]) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False,
                                             dir=str(self.cache_path.parent), suffix=".tmp") as handle:
                json.dump({"head": head, "ledger_stamp": ledger_stamp, "entries": rows}, handle,
                          separators=(",", ":"))
                temporary = Path(handle.name)
            os.replace(temporary, self.cache_path)
        except OSError:
            pass

    def _is_ancestor(self, older: str, newer: str) -> bool:
        try:
            result = subprocess.run(
                ["git", "-c", "safe.directory=" + str(self.repo), "-C", str(self.repo),
                 "merge-base", "--is-ancestor", older, newer],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    @staticmethod
    def _trailers(body: str) -> dict[str, str]:
        return {match.group(1).lower().replace("-", "_"): _text(match.group(2))
                for match in _TRAILER.finditer(body or "")}

    @staticmethod
    def _files(raw: str) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        for line in raw.splitlines():
            fields = line.split("\t", 2)
            if len(fields) != 3:
                continue
            added, deleted, path = fields
            binary = added == "-" or deleted == "-"
            try:
                plus = int(added) if not binary else 0
                minus = int(deleted) if not binary else 0
            except ValueError:
                continue
            files.append({"path": path, "added": plus, "deleted": minus,
                          "binary": binary})
        return files

    def _read(self) -> list[dict[str, Any]]:
        head = self._head()
        stamp = self._ledger_stamp()
        cache_key = (head, stamp)
        with self._lock:
            if self._cache_key == cache_key:
                return [dict(row) for row in self._cache]
            disk = self._disk_cache()
            if disk.get("head") == head and disk.get("ledger_stamp") == stamp:
                self._cache_key = cache_key
                self._cache = disk["entries"]
                return [dict(row) for row in self._cache]
            ledger = self._ledger()
            cached_head = str(disk.get("head") or "")
            incremental = (cached_head and int(disk.get("ledger_stamp") or -1) == stamp
                           and self._is_ancestor(cached_head, head))
            raw = self._git(
                "log", *( [] if incremental else ["--all"] ), "--no-renames", "--numstat",
                "--format=%x1e%H%x1f%P%x1f%ct%x1f%an%x1f%s%x1f%b%x1d",
                cached_head + "..HEAD" if incremental else "HEAD",
                timeout=180,
            )
            rows: list[dict[str, Any]] = []
            for record in raw.split(_RECORD):
                if not record.strip() or _END not in record:
                    continue
                meta, changed = record.split(_END, 1)
                fields = meta.lstrip("\n").split(_FIELD, 5)
                if len(fields) != 6:
                    continue
                commit, parents, committed, author, subject, body = fields
                try:
                    at = int(committed)
                except ValueError:
                    continue
                commit = commit.strip()
                details = ledger.get(commit) or ledger.get(commit[:12]) or {}
                details = details if isinstance(details, dict) else {}
                trailers = self._trailers(body)
                files = self._files(changed)
                prompt = _text(details.get("prompt") or trailers.get("prompt"))
                task_name = _text(details.get("task_name") or trailers.get("task") or subject, 240)
                goal = _text(details.get("goal") or trailers.get("goal") or subject, 1200)
                result = _text(details.get("result") or trailers.get("result") or body or subject, 1600)
                input_tokens = _number(details.get("input_tokens", trailers.get("token_in")), "input_tokens")
                output_tokens = _number(details.get("output_tokens", trailers.get("token_out")), "output_tokens")
                elapsed_ms = _number(details.get("elapsed_ms", trailers.get("elapsed_ms")), "elapsed_ms")
                completed_at = details.get("completed_at") or at
                try:
                    completed_at = float(completed_at)
                except (TypeError, ValueError):
                    completed_at = float(at)
                rows.append({
                    "commit": commit,
                    "short_commit": commit[:12],
                    "parents": [part[:12] for part in parents.split() if part],
                    "author": _text(author, 160),
                    "task_name": task_name,
                    "prompt": prompt or None,
                    "prompt_source": "task ledger" if details.get("prompt") else
                                     "commit trailer" if trailers.get("prompt") else "unrecorded",
                    "goal": goal,
                    "result": result,
                    "tokens": {"input": input_tokens, "output": output_tokens,
                               "source": "task ledger" if any(key in details for key in
                               ("input_tokens", "output_tokens")) else "commit trailer" if
                               (trailers.get("token_in") or trailers.get("token_out")) else "unrecorded"},
                    "elapsed_ms": elapsed_ms,
                    "elapsed_source": "task ledger" if "elapsed_ms" in details else
                                      "commit trailer" if trailers.get("elapsed_ms") else "unrecorded",
                    "completed_at": completed_at,
                    "completed_label": cst_label(completed_at),
                    "files": files,
                    "file_count": len(files),
                    "insertions": sum(row["added"] for row in files),
                    "deletions": sum(row["deleted"] for row in files),
                    "major": len(files) > 3,
                    "git": {"subject": _text(subject, 600), "body": _text(body, 5000),
                            "committed_at": at, "committed_label": cst_label(at)},
                })
            if incremental:
                seen = {str(row.get("commit") or "") for row in rows}
                rows.extend(row for row in disk["entries"] if str(row.get("commit") or "") not in seen)
            self._cache_key = cache_key
            self._cache = rows
            self._save_disk_cache(head, stamp, rows)
            return [dict(row) for row in rows]

    def page(self, limit: int = 60, before: str = "") -> dict[str, Any]:
        limit = max(1, min(200, int(limit)))
        rows = self._read()
        start = 0
        if before:
            needle = str(before).strip()
            for index, row in enumerate(rows):
                if row["commit"] == needle or row["short_commit"] == needle:
                    start = index + 1
                    break
            else:
                raise ValueError("That changelog cursor is no longer in this Git history")
        entries = rows[start:start + limit]
        return {"entries": entries, "total": len(rows), "head": self._head() if rows else "",
                "has_more": start + len(entries) < len(rows),
                "next_before": entries[-1]["commit"] if entries else "",
                "retroactive": True,
                "timezone": "America/Chicago"}

    def record(self, commit: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Attach task telemetry to an existing commit without editing Git history."""
        if not isinstance(payload, dict):
            raise ValueError("Task telemetry must be an object")
        resolved = self._git("rev-parse", "--verify", str(commit).strip() + "^{commit}").strip()
        row = {
            "task_name": _text(payload.get("task_name"), 240),
            "prompt": _text(payload.get("prompt"), 4000),
            "goal": _text(payload.get("goal"), 1200),
            "result": _text(payload.get("result"), 1600),
            "input_tokens": _number(payload.get("input_tokens"), "input_tokens"),
            "output_tokens": _number(payload.get("output_tokens"), "output_tokens"),
            "elapsed_ms": _number(payload.get("elapsed_ms"), "elapsed_ms"),
            "completed_at": payload.get("completed_at") or None,
        }
        row = {key: value for key, value in row.items() if value not in (None, "")}
        with self._lock:
            current = self._ledger()
            prior = current.get(resolved) if isinstance(current.get(resolved), dict) else {}
            current[resolved] = {**prior, **row}
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False,
                                             dir=str(self.ledger_path.parent), suffix=".tmp") as handle:
                json.dump({"tasks": current}, handle, indent=2, sort_keys=True)
                temporary = Path(handle.name)
            os.replace(temporary, self.ledger_path)
            self._cache_key = None
        return {"commit": resolved, "recorded": sorted(row)}

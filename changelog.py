"""A truthful, Git-backed task history for the Pine Box operator changelog.

Git can answer which source files changed and when a commit landed.  It cannot
recover a prompt, model token count, or elapsed agent time that was never
written down.  ``ChangeLog`` keeps those facts in a tiny sidecar ledger for
new work and makes the absence explicit for older commits.

The popup never waits on Git, and never depends on a ``git`` binary.  It is
served from a durable cache, ``data/changelog_cache.json``: every commit on
HEAD with its author, date, subject, body and ``--numstat`` files.  That
cache is refreshed off the request path:

* by a background thread in the station (at startup, and whenever HEAD
  moves), which runs ``python3 changelog.py refresh`` in a child process;
* by the host's commit hooks (``tools/changelog_hooks.py`` installs them),
  which run the same refresh right after every commit.

A refresh reads history with the ``git`` binary when one exists and with the
pure-Python ``git_log_reader`` when it does not (the station's container has
no git).  A failed refresh leaves the last good cache in place: the page
says "as of <time>" and carries on.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from git_log_reader import GitReadError, GitRepo


_FIELD = "\x1f"
_RECORD = "\x1e"
_END = "\x1d"
_TRAILER = re.compile(r"^Pine-([A-Za-z-]+):\s*(.+?)\s*$", re.M)
_HEXISH = re.compile(r"^[0-9a-f]{4,40}$")
_LOG_FORMAT = "--format=%x1e%H%x1f%P%x1f%ct%x1f%an%x1f%s%x1f%b%x1d"
try:
    _CHICAGO = ZoneInfo("America/Chicago")
except Exception:  # Windows test hosts may not ship the IANA zone database.
    _CHICAGO = timezone(timedelta(hours=-6), "CST")

CACHE_NAME = "changelog_cache.json"
LEGACY_CACHE_NAME = "changelog_git_cache.json"
CACHE_VERSION = 2
MAX_COMMITS = 5000           # history kept in the cache (the popup pages it)
POLL_SECONDS = 20.0          # how often the station looks at HEAD
REFRESH_TIMEOUT = 1800.0     # a first full build by the pure reader fits well inside
CHECKPOINT_SECONDS = 20.0    # a long build publishes what it has this often


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


def _shown_number(value: Any, label: str) -> int | None:
    """A number for display: a malformed trailer shows as unrecorded."""
    try:
        return _number(value, label)
    except ValueError:
        return None


def cst_label(epoch: float | int | None) -> str:
    """The operator's requested fixed-layout date label in station time."""
    if not epoch:
        return "not recorded"
    moment = datetime.fromtimestamp(float(epoch), tz=timezone.utc).astimezone(_CHICAGO)
    hour = str(int(moment.strftime("%I")))
    return moment.strftime("%m-%d-%y / ") + hour + moment.strftime(":%M %p CST")


# ---------------------------------------------------------------------------
# The durable cache and how it is refreshed (no station imports: the host's
# commit hook runs this file directly with the system python3).
# ---------------------------------------------------------------------------
class ChangelogRefreshError(RuntimeError):
    """A refresh could not bring the cache up to HEAD (the old one stands)."""


def default_data_dir(repo: str | Path) -> Path:
    configured = os.getenv("SPARK_AGENT_DATA_DIR")
    return Path(configured).expanduser() if configured else Path(repo) / "data"


def git_available() -> bool:
    return shutil.which("git") is not None


def _git(repo: Path, *args: str, timeout: float = 120, stdin: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", "-c", "safe.directory=" + str(repo), "-C", str(repo), *args],
            check=True, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ChangelogRefreshError("git " + args[0] + " failed: " + str(exc)[:160]) from exc
    return result.stdout


def load_cache(path: str | Path) -> dict[str, Any]:
    """The cache file, or {} when it is missing, unreadable or foreign."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if (not isinstance(payload, dict) or payload.get("version") != CACHE_VERSION
            or not isinstance(payload.get("commits"), list)):
        return {}
    return payload


def load_legacy(path: str | Path) -> dict[str, Any]:
    """The pre-2026-09-28 cache of finished rows (git numstat included)."""
    try:
        path = Path(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        stamp = path.stat().st_mtime
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        return {}
    rows = [row for row in payload["entries"] if isinstance(row, dict) and row.get("commit")]
    return {"legacy": True, "head": str(payload.get("head") or ""), "rows": rows,
            "as_of": stamp, "source": "saved"}


def _write_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), ensure_ascii=False)
        try:
            os.chmod(temporary, 0o644)  # the host's hook and the container share it
        except OSError:
            pass
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


@contextmanager
def _refresh_lock(cache_path: Path, wait: float = 600.0) -> Iterator[None]:
    """One refresher at a time across the container and the host (flock)."""
    try:
        import fcntl
    except ImportError:  # Windows: best effort, the writes are atomic anyway
        yield
        return
    lock_path = cache_path.with_name(cache_path.name + ".lock")
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_RDONLY | os.O_CREAT, 0o644)
    except OSError:
        yield
        return
    try:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    break  # a wedged holder must not stop the history forever
                time.sleep(0.5)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def _parse_git_log(raw: str) -> list[dict[str, Any]]:
    facts = []
    for record in raw.split(_RECORD):
        if not record.strip() or _END not in record:
            continue
        meta = record.split(_END, 1)[0]
        fields = meta.lstrip("\n").split(_FIELD, 5)
        if len(fields) != 6:
            continue
        commit, parents, committed, author, subject, body = fields
        try:
            at = int(committed)
        except ValueError:
            continue
        facts.append({"commit": commit.strip(), "parents": parents.split(),
                      "committed_at": at, "author": author, "subject": subject,
                      "body": body})
    return facts


def _git_numstat(repo: Path, shas: list[str]) -> dict[str, list[dict[str, Any]]]:
    raw = _git(repo, "log", "--no-walk=unsorted", "--stdin", "--no-renames", "--numstat",
               "--format=%x1e%H%x1d", timeout=900, stdin="\n".join(shas) + "\n")
    found: dict[str, list[dict[str, Any]]] = {}
    for record in raw.split(_RECORD):
        if _END not in record:
            continue
        sha, changed = record.split(_END, 1)
        found[sha.strip()] = ChangeLog._files(changed)
    return found


def _live_head(repo: Path, use_git: bool) -> str:
    try:
        with GitRepo(repo) as reader:
            head = reader.head()
        if head:
            return head
    except (GitReadError, OSError):
        pass
    if use_git:
        try:
            return _git(repo, "rev-parse", "HEAD", timeout=20).strip()
        except ChangelogRefreshError:
            return ""
    return ""


def _writer_name() -> str:
    if Path("/.dockerenv").exists():
        return "container"
    try:
        return os.uname().nodename or "host"
    except AttributeError:
        return os.environ.get("COMPUTERNAME", "host")


def _refresh_once(repo: Path, cache_path: Path, legacy_path: Path | None, use_git: bool,
                  limit: int, force: bool, log: Any) -> dict[str, Any]:
    previous = load_cache(cache_path)
    known = {row["commit"]: row for row in previous.get("commits", [])
             if isinstance(row, dict) and isinstance(row.get("commit"), str)}
    notes: list[str] = []
    reader: GitRepo | None = None
    try:
        reader = GitRepo(repo)
    except (GitReadError, OSError) as exc:
        notes.append("reader: " + str(exc)[:160])
    try:
        head = ""
        if reader is not None:
            try:
                head = reader.head() or ""
            except (GitReadError, OSError) as exc:
                notes.append("reader HEAD: " + str(exc)[:160])
        if not head and use_git:
            try:
                head = _git(repo, "rev-parse", "HEAD", timeout=20).strip()
            except ChangelogRefreshError as exc:
                notes.append(str(exc))
        if not head:
            raise ChangelogRefreshError("HEAD could not be read (" + "; ".join(notes) + ")")
        upgrade = use_git and any(row.get("numstat") in ("reader", "error") for row in known.values())
        if (not force and previous.get("head") == head and previous.get("complete")
                and not upgrade):
            return {"head": head, "changed": False, "commits": len(known)}

        try:
            branch = reader.symbolic_head() if reader is not None else ""
        except (GitReadError, OSError):
            branch = ""

        # 1. The walk: commit ids in git log order, with their messages.
        facts: list[dict[str, Any]] | None = None
        walk_source = ""
        if use_git:
            try:
                facts = _parse_git_log(_git(repo, "log", head, "-n", str(limit), _LOG_FORMAT,
                                            timeout=300))
                walk_source = "git"
            except ChangelogRefreshError as exc:
                notes.append(str(exc))
        if facts is None:
            if reader is None:
                raise ChangelogRefreshError("history could not be read (" + "; ".join(notes) + ")")
            cached = {sha: (row.get("parents") or [], int(row.get("committed_at") or 0))
                      for sha, row in known.items()}
            try:
                facts = []
                for sha in reader.walk([head], limit=limit, known=cached):
                    row = known.get(sha)
                    if row is None:
                        parsed = reader.commit(sha)
                        row = {"commit": sha, "parents": parsed["parents"],
                               "committed_at": parsed["committer_time"],
                               "author": parsed["author"], "subject": parsed["subject"],
                               "body": parsed["body"]}
                    facts.append({key: row[key] for key in
                                  ("commit", "parents", "committed_at", "author", "subject", "body")})
                walk_source = "reader"
            except (GitReadError, OSError, ValueError, KeyError) as exc:
                raise ChangelogRefreshError("history could not be read: " + str(exc)[:200]) from exc

        # 2. The files: reuse what is cached, then git, then the reader.
        legacy_files: dict[str, list[dict[str, Any]]] = {}
        if legacy_path is not None:
            for row in load_legacy(legacy_path).get("rows", []):
                if isinstance(row.get("files"), list):
                    legacy_files[str(row["commit"])] = row["files"]
        todo: list[dict[str, Any]] = []
        for row in facts:
            prior = known.get(row["commit"])
            if (prior is not None and isinstance(prior.get("files"), list)
                    and prior.get("numstat") not in ("pending", "error")
                    and not (use_git and prior.get("numstat") == "reader")):
                row["files"], row["numstat"] = prior["files"], prior.get("numstat") or "git"
            elif row["commit"] in legacy_files:
                row["files"], row["numstat"] = legacy_files[row["commit"]], "git"
            else:
                row["files"], row["numstat"] = [], "pending"
                todo.append(row)

        def payload(complete: bool) -> dict[str, Any]:
            counts: dict[str, int] = {}
            for row in facts:
                counts[row["numstat"]] = counts.get(row["numstat"], 0) + 1
            return {"version": CACHE_VERSION, "head": head, "branch": branch,
                    "as_of": time.time(), "complete": complete, "walk": walk_source,
                    "numstat": counts, "writer": _writer_name(), "commits": facts}

        if todo and use_git:
            try:
                found = _git_numstat(repo, [row["commit"] for row in todo])
                for row in todo:
                    if row["commit"] in found:
                        row["files"], row["numstat"] = found[row["commit"]], "git"
                todo = [row for row in todo if row["numstat"] == "pending"]
            except ChangelogRefreshError as exc:
                notes.append(str(exc))
        if todo and reader is None:
            raise ChangelogRefreshError("file changes could not be read (" + "; ".join(notes) + ")")
        last_write = time.monotonic()
        for index, row in enumerate(todo):
            try:
                row["files"], row["numstat"] = reader.numstat(row["commit"]), "reader"
            except (GitReadError, OSError, ValueError, KeyError, MemoryError) as exc:
                row["files"], row["numstat"] = [], "error"
                notes.append("%s: %s" % (row["commit"][:12], str(exc)[:120]))
            if (time.monotonic() - last_write > CHECKPOINT_SECONDS
                    and index + 1 < len(todo)):
                _write_cache(cache_path, payload(False))  # a long first build shows progress
                last_write = time.monotonic()
                if log:
                    log("checkpoint: %d of %d commits counted" % (index + 1, len(todo)))
        _write_cache(cache_path, payload(True))
        return {"head": head, "changed": True, "commits": len(facts), "walk": walk_source,
                "counted": len(todo), "notes": notes[:8]}
    finally:
        if reader is not None:
            reader.close()


def refresh_cache(repo: str | Path, cache_path: str | Path | None = None,
                  legacy_path: str | Path | None = None, *, use_git: bool | None = None,
                  limit: int = MAX_COMMITS, force: bool = False, log: Any = None) -> dict[str, Any]:
    """Bring the durable changelog cache up to HEAD.

    Uses the ``git`` binary when it exists and the pure-Python reader
    otherwise (or when git fails).  Raises ChangelogRefreshError when nothing
    usable could be read; the previous cache file is then left untouched.
    """
    repo = Path(repo)
    cache = Path(cache_path) if cache_path else default_data_dir(repo) / CACHE_NAME
    legacy = Path(legacy_path) if legacy_path else cache.with_name(LEGACY_CACHE_NAME)
    with_git = git_available() if use_git is None else bool(use_git)
    with _refresh_lock(cache):
        summary: dict[str, Any] = {}
        for _ in range(3):
            summary = _refresh_once(repo, cache, legacy, with_git, limit, force, log)
            force = False
            # HEAD moved while this ran (another commit): go again so the
            # cache ends on the newest commit rather than one behind it.
            if _live_head(repo, with_git) in ("", summary["head"]):
                break
        return summary


# ---------------------------------------------------------------------------
# The station side: serve the cache, refresh it in the background.
# ---------------------------------------------------------------------------
class ChangeLog:
    """Merge the committed graph with optional, explicitly captured task facts."""

    def __init__(self, repo: str | Path, ledger_path: str | Path, *,
                 cache_path: str | Path | None = None,
                 legacy_path: str | Path | None = None,
                 poll_seconds: float = POLL_SECONDS,
                 refresh_in_subprocess: bool = True,
                 background: bool = True):
        self.repo = Path(repo)
        self.ledger_path = Path(ledger_path)
        self.cache_path = Path(cache_path) if cache_path else self.ledger_path.with_name(CACHE_NAME)
        self.legacy_path = (Path(legacy_path) if legacy_path
                            else self.ledger_path.with_name(LEGACY_CACHE_NAME))
        self.poll_seconds = float(poll_seconds)
        self.refresh_in_subprocess = refresh_in_subprocess
        self.background = background
        self._lock = RLock()
        self._snapshot: dict[str, Any] | None = None
        self._snapshot_stamp: Any = None
        self._snapshot_serial = 0
        self._rows_key: Any = None
        self._rows: list[dict[str, Any]] = []
        self._live = ""
        self._git_seen: bool | None = None
        self._status: dict[str, Any] = {
            "refreshing": False, "error": "", "error_at": 0.0, "failed_head": "",
            "failures": 0, "next_try": 0.0, "last_refresh": 0.0, "last_summary": {}}
        self._wake = threading.Event()
        self._stopping = False
        self._thread: threading.Thread | None = None

    # -- facts -----------------------------------------------------------
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

    @staticmethod
    def _with_ledger(row: dict[str, Any], details: Any) -> dict[str, Any]:
        """Overlay new task telemetry without re-reading Git history.

        Recording a prompt or duration changes only the sidecar ledger. The
        commit graph and file list have not moved, so replaying a full history
        scan just to update one small card makes the live panel needlessly
        slow. Keep the Git facts and replace only facts supplied by the
        ledger.
        """
        details = details if isinstance(details, dict) else {}
        if not details:
            return dict(row)
        out = dict(row)
        if details.get("task_name"):
            out["task_name"] = _text(details["task_name"], 240)
        if details.get("prompt"):
            out["prompt"] = _text(details["prompt"])
            out["prompt_source"] = "task ledger"
        if details.get("goal"):
            out["goal"] = _text(details["goal"], 1200)
        if details.get("result"):
            out["result"] = _text(details["result"], 1600)
        tokens = dict(out.get("tokens") or {})
        changed_tokens = False
        for field, key in (("input_tokens", "input"), ("output_tokens", "output")):
            if field in details:
                tokens[key] = _shown_number(details.get(field), field)
                changed_tokens = True
        if changed_tokens:
            tokens["source"] = "task ledger"
            out["tokens"] = tokens
        if "elapsed_ms" in details:
            out["elapsed_ms"] = _shown_number(details.get("elapsed_ms"), "elapsed_ms")
            out["elapsed_source"] = "task ledger"
        if details.get("completed_at"):
            try:
                completed_at = float(details["completed_at"])
            except (TypeError, ValueError):
                completed_at = float((out.get("git") or {}).get("committed_at") or 0)
            out["completed_at"] = completed_at
            out["completed_label"] = cst_label(completed_at)
        return out

    def _row(self, facts: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
        """One changelog card from a cached commit plus its ledger facts."""
        commit = str(facts.get("commit") or "").strip()
        details = ledger.get(commit) or ledger.get(commit[:12]) or {}
        details = details if isinstance(details, dict) else {}
        subject = str(facts.get("subject") or "")
        body = str(facts.get("body") or "")
        try:
            at = int(facts.get("committed_at") or 0)
        except (TypeError, ValueError):
            at = 0
        trailers = self._trailers(body)
        files = [item for item in (facts.get("files") or []) if isinstance(item, dict)]
        prompt = _text(details.get("prompt") or trailers.get("prompt"))
        task_name = _text(details.get("task_name") or trailers.get("task") or subject, 240)
        goal = _text(details.get("goal") or trailers.get("goal") or subject, 1200)
        result = _text(details.get("result") or trailers.get("result") or body or subject, 1600)
        input_tokens = _shown_number(details.get("input_tokens", trailers.get("token_in")), "input_tokens")
        output_tokens = _shown_number(details.get("output_tokens", trailers.get("token_out")), "output_tokens")
        elapsed_ms = _shown_number(details.get("elapsed_ms", trailers.get("elapsed_ms")), "elapsed_ms")
        completed_at: Any = details.get("completed_at") or at
        try:
            completed_at = float(completed_at)
        except (TypeError, ValueError):
            completed_at = float(at)
        row = {
            "commit": commit,
            "short_commit": commit[:12],
            "parents": [str(part)[:12] for part in (facts.get("parents") or []) if part],
            "author": _text(facts.get("author"), 160),
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
            "insertions": sum(int(item.get("added") or 0) for item in files),
            "deletions": sum(int(item.get("deleted") or 0) for item in files),
            "major": len(files) > 3,
            "git": {"subject": _text(subject, 600), "body": _text(body, 5000),
                    "committed_at": at, "committed_label": cst_label(at)},
        }
        if facts.get("numstat") in ("pending", "error"):
            row["files_pending"] = True
        return self._with_ledger(row, details)

    # -- the cache on disk -------------------------------------------------
    def _file_stamp(self) -> Any:
        try:
            info = self.cache_path.stat()
        except OSError:
            return None
        return (info.st_mtime_ns, info.st_size)

    def _load_snapshot(self) -> dict[str, Any] | None:
        """The newest durable cache; reloaded only when its file changed.

        A missing or unreadable file never discards the snapshot already in
        memory, and before the first refresh the older row cache is served.
        """
        stamp = self._file_stamp()
        with self._lock:
            if stamp is not None and stamp == self._snapshot_stamp:
                return self._snapshot
        if stamp is not None:
            payload = load_cache(self.cache_path)
            if payload:
                with self._lock:
                    self._snapshot, self._snapshot_stamp = payload, stamp
                    self._snapshot_serial += 1
                    return payload
        with self._lock:
            if self._snapshot is not None:
                return self._snapshot
        legacy = load_legacy(self.legacy_path)
        if legacy:
            with self._lock:
                if self._snapshot is None:
                    self._snapshot, self._snapshot_stamp = legacy, None
                    self._snapshot_serial += 1
                return self._snapshot
        return None

    def _rows_now(self) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        snapshot = self._load_snapshot()
        stamp = self._ledger_stamp()
        with self._lock:
            key = (self._snapshot_serial, stamp)
            if key == self._rows_key:
                return self._rows, snapshot
        ledger = self._ledger()
        rows: list[dict[str, Any]] = []
        if snapshot is not None and snapshot.get("legacy"):
            for row in snapshot.get("rows", []):
                rows.append(self._with_ledger(dict(row), ledger.get(str(row.get("commit") or ""))
                                              or ledger.get(str(row.get("short_commit") or ""))))
        elif snapshot is not None:
            for facts in snapshot.get("commits", []):
                if isinstance(facts, dict) and facts.get("commit"):
                    rows.append(self._row(facts, ledger))
        with self._lock:
            self._rows_key, self._rows = key, rows
        return rows, snapshot

    # -- HEAD and the refresher ------------------------------------------------
    def _git_present(self) -> bool:
        if self._git_seen is None:
            self._git_seen = git_available()
        return self._git_seen

    def _live_head(self, fresh: bool = False) -> str:
        """HEAD's commit id, read from the ref files (two small reads, no git).

        ``fresh`` (the refresher's own look) may also ask the git binary
        when the files cannot answer; the popup's path never runs git.
        """
        head = ""
        try:
            with GitRepo(self.repo) as reader:
                head = reader.head() or ""
        except Exception:  # noqa: BLE001 - a HEAD read never fails the page
            head = ""
        if not head and fresh and self._git_present():
            head = _live_head(self.repo, True)
        self._live = head
        return head

    def start(self) -> None:
        """Run the background refresher (idempotent; the popup calls it too)."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping = False
            self._thread = threading.Thread(target=self._run, name="changelog-cache", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """End the background refresher after its current pass (tests, shutdown)."""
        self._stopping = True
        self._wake.set()

    def _run(self) -> None:
        while not self._stopping:
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001 - the thread must outlive any fault
                self._failed(str(exc) or type(exc).__name__, self._live)
            self._wake.wait(self.poll_seconds)
            self._wake.clear()

    def _due(self, snapshot: dict[str, Any] | None, live: str) -> bool:
        if snapshot is None or snapshot.get("legacy"):
            return True
        if not snapshot.get("complete"):
            return True
        if live and snapshot.get("head") != live:
            return True
        counts = snapshot.get("numstat") or {}
        return bool(self._git_present() and (counts.get("reader") or counts.get("error")))

    def _tick(self, force: bool = False) -> bool:
        snapshot = self._load_snapshot()
        live = self._live_head(fresh=True)
        if not force and not self._due(snapshot, live):
            return False
        with self._lock:
            status = self._status
            if (not force and status["failures"] and time.time() < status["next_try"]
                    and status["failed_head"] == live):
                return False
            status["refreshing"] = True
        try:
            summary = self._refresh(force)
        except Exception as exc:  # noqa: BLE001 - recorded, the old cache stands
            self._failed(str(exc) or type(exc).__name__, live)
            return False
        finally:
            with self._lock:
                self._status["refreshing"] = False
            self._load_snapshot()
        with self._lock:
            self._status.update(error="", failed_head="", failures=0, next_try=0.0,
                                last_refresh=time.time(), last_summary=summary)
        return True

    def _failed(self, message: str, head: str) -> None:
        with self._lock:
            status = self._status
            status["failures"] += 1
            status["error"] = _text(message, 300)
            status["error_at"] = time.time()
            status["failed_head"] = head
            status["next_try"] = time.time() + min(1800.0, 30.0 * 2 ** min(status["failures"], 6))

    def _refresh(self, force: bool = False) -> dict[str, Any]:
        if self.refresh_in_subprocess and sys.executable:
            command = [sys.executable, str(Path(__file__).resolve()), "refresh",
                       "--repo", str(self.repo), "--cache", str(self.cache_path),
                       "--legacy", str(self.legacy_path), "--nice", "10", "--json"]
            if force:
                command.append("--force")
            try:
                done = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, encoding="utf-8", errors="replace",
                                      timeout=REFRESH_TIMEOUT,
                                      cwd=str(Path(__file__).resolve().parent))
            except OSError:
                done = None  # no interpreter to spawn: refresh in this thread instead
            except subprocess.TimeoutExpired as exc:
                raise ChangelogRefreshError("the refresh ran past %d s" % REFRESH_TIMEOUT) from exc
            if done is not None:
                if done.returncode != 0:
                    lines = [line for line in (done.stderr or done.stdout or "").splitlines()
                             if line.strip()]
                    raise ChangelogRefreshError(lines[-1] if lines else
                                                "refresh exited %d" % done.returncode)
                try:
                    return json.loads((done.stdout or "{}").strip().splitlines()[-1])
                except (ValueError, IndexError):
                    return {}
        return refresh_cache(self.repo, self.cache_path, self.legacy_path, force=force)

    def refresh_now(self, force: bool = False) -> bool:
        """Refresh synchronously (tests, tools). Never raises; True if it ran clean."""
        try:
            return self._tick(force=force)
        except Exception as exc:  # noqa: BLE001
            self._failed(str(exc) or type(exc).__name__, self._live)
            return False

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    # -- pages -------------------------------------------------------------------
    def _freshness(self, snapshot: dict[str, Any] | None, rows: list[dict[str, Any]],
                   live: str) -> dict[str, Any]:
        with self._lock:
            status = dict(self._status)
        head = str((snapshot or {}).get("head") or "")
        as_of = float((snapshot or {}).get("as_of") or 0.0)
        legacy = bool(snapshot and snapshot.get("legacy"))
        behind = bool(snapshot is None or legacy or not snapshot.get("complete")
                      or (live and head != live))
        failed = bool(status["error"]) and behind
        stale = bool(status["refreshing"] or (behind and not failed))
        return {"as_of": as_of, "as_of_label": cst_label(as_of) if as_of else "",
                "source": "saved" if legacy else str((snapshot or {}).get("walk") or ""),
                "live_head": live, "behind": behind, "refreshing": bool(status["refreshing"]),
                "stale": stale, "warming": bool(stale and not rows),
                "refresh_error": status["error"] if failed else ""}

    def page(self, limit: int = 60, before: str = "") -> dict[str, Any]:
        """A page of history from the durable cache.

        Never runs Git and never fails for want of it: a stale cache is
        served with its as-of time while the refresher catches up.
        """
        if self.background:
            self.start()
        try:
            rows, snapshot = self._rows_now()
        except Exception as exc:  # noqa: BLE001 - a broken cache file must not blank the popup
            with self._lock:
                rows, snapshot = list(self._rows), self._snapshot
                self._status["error"] = _text("cache: " + str(exc), 300)
        live = self._live_head()
        if not snapshot or live != str(snapshot.get("head") or "") or not snapshot.get("complete"):
            self._wake.set()  # HEAD moved (or nothing cached yet): refresh now, not in 20 s
        page = self._page_rows(rows, limit, before, str((snapshot or {}).get("head") or ""))
        page.update(self._freshness(snapshot, rows, live))
        return page

    def memory_page(self, limit: int = 60, before: str = "") -> dict[str, Any]:
        """What is already in memory: no disk, no Git, no exceptions."""
        try:
            with self._lock:
                rows, snapshot = list(self._rows), self._snapshot
            page = self._page_rows(rows, limit, before, str((snapshot or {}).get("head") or ""))
            page.update(self._freshness(snapshot, rows, self._live))
            page["stale"] = True
            return page
        except Exception:  # noqa: BLE001
            return {"entries": [], "total": 0, "head": "", "has_more": False,
                    "next_before": "", "retroactive": True, "timezone": "America/Chicago",
                    "stale": True, "warming": True, "as_of": 0.0, "as_of_label": ""}

    @staticmethod
    def _page_rows(rows: list[dict[str, Any]], limit: int, before: str,
                   head: str = "") -> dict[str, Any]:
        """Paginate the cached history."""
        limit = max(1, min(200, int(limit)))
        start = 0
        lost = False
        if before:
            needle = str(before).strip()
            for index, row in enumerate(rows):
                if row["commit"] == needle or row["short_commit"] == needle:
                    start = index + 1
                    break
            else:
                start, lost = len(rows), True  # history was rewritten under the cursor
        entries = [dict(row) for row in rows[start:start + limit]]
        page = {"entries": entries, "total": len(rows), "head": head if rows else "",
                "has_more": start + len(entries) < len(rows),
                "next_before": entries[-1]["commit"] if entries else "",
                "retroactive": True,
                "timezone": "America/Chicago"}
        if lost:
            page["cursor_lost"] = True
        return page

    def cached_page(self, limit: int = 60, before: str = "") -> dict[str, Any] | None:
        """Return the last durable snapshot without invoking Git (or None)."""
        try:
            rows, snapshot = self._rows_now()
        except Exception:  # noqa: BLE001
            return None
        if not rows:
            return None
        page = self._page_rows(rows, limit, before, str((snapshot or {}).get("head") or ""))
        page.update(self._freshness(snapshot, rows, self._live))
        page["stale"] = True
        return page

    # -- task telemetry -------------------------------------------------------------
    def _resolve_commit(self, commit: str) -> str:
        text = str(commit or "").strip()
        if text.upper() == "HEAD":
            head = self._live_head(fresh=True)
            if head:
                return head
        text = text.lower()
        if not _HEXISH.match(text):
            raise ValueError("A Git commit id (4-40 hex characters) is required")
        try:
            rows, _ = self._rows_now()
        except Exception:  # noqa: BLE001
            rows = []
        matches = {row["commit"] for row in rows if str(row.get("commit") or "").startswith(text)}
        if len(matches) == 1:
            return matches.pop()
        if len(matches) > 1:
            raise ValueError("Commit %s is ambiguous" % text)
        try:  # a commit seconds old may not be cached yet: ask the object store
            with GitRepo(self.repo) as reader:
                found = reader.resolve_prefix(text)
            if found:
                return found
        except (GitReadError, OSError):
            pass
        if self._git_present():
            try:
                return _git(self.repo, "rev-parse", "--verify", text + "^{commit}",
                            timeout=20).strip()
            except ChangelogRefreshError:
                pass
        raise ValueError("Commit %s is not in this repository" % text)

    def record(self, commit: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Attach task telemetry to an existing commit without editing Git history."""
        if not isinstance(payload, dict):
            raise ValueError("Task telemetry must be an object")
        resolved = self._resolve_commit(commit)
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
            self._rows_key = None
        return {"commit": resolved, "recorded": sorted(row)}


# ---------------------------------------------------------------------------
# python3 changelog.py refresh|show  (the station's child process, the hooks)
# ---------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    import argparse
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Pine Box changelog cache")
    sub = parser.add_subparsers(dest="command", required=True)
    refresh = sub.add_parser("refresh", help="bring data/changelog_cache.json up to HEAD")
    show = sub.add_parser("show", help="print the cached history")
    for command in (refresh, show):
        command.add_argument("--repo", default=str(here))
        command.add_argument("--cache", default="")
    refresh.add_argument("--legacy", default="")
    refresh.add_argument("--nice", type=int, default=0)
    refresh.add_argument("--force", action="store_true")
    refresh.add_argument("--no-git", action="store_true", help="read with the pure-Python reader only")
    refresh.add_argument("--json", action="store_true", help="print the summary as one JSON line")
    refresh.add_argument("--quiet", action="store_true")
    show.add_argument("-n", type=int, default=10)
    args = parser.parse_args(argv)
    repo = Path(args.repo)
    cache = Path(args.cache) if args.cache else default_data_dir(repo) / CACHE_NAME
    if args.command == "show":
        payload = load_cache(cache)
        print("cache %s head %s as of %s (walk %s, numstat %s)" % (
            cache, str(payload.get("head") or "-")[:12], cst_label(payload.get("as_of")),
            payload.get("walk") or "-", payload.get("numstat") or {}))
        for row in payload.get("commits", [])[:args.n]:
            files = row.get("files") or []
            print("%s %s %3d files +%-5d -%-5d %s" % (
                row["commit"][:12], row.get("committed_at"), len(files),
                sum(int(f.get("added") or 0) for f in files),
                sum(int(f.get("deleted") or 0) for f in files), str(row.get("subject", ""))[:70]))
        return 0 if payload else 1
    if args.nice:
        try:
            os.nice(args.nice)
        except (AttributeError, OSError):
            pass
    log = None if (args.quiet or args.json) else (lambda message: print(message, flush=True))
    try:
        summary = refresh_cache(repo, cache, args.legacy or None,
                                use_git=False if args.no_git else None,
                                force=args.force, log=log)
    except ChangelogRefreshError as exc:
        print("changelog refresh failed: %s" % exc, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(summary, separators=(",", ":")))
    elif not args.quiet:
        print("changelog cache at %s: %d commits, %s" % (
            str(summary.get("head"))[:12], summary.get("commits", 0),
            "updated" if summary.get("changed") else "already current"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

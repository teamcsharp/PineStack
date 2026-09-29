"""[filemgr] THE DISK ON THE BASE BAR: CLEAR THE STATION'S FILES, CLEANLY.

"i also want an icon of a disk here that is a file management icon that
 brings up a popup where i can adjust a slider to clear the various caches of
 pine-box and even clear settings, lists, stored configs, and be able to
 reinitilize the station cleanly."                     - the operator, 2026-09-29

WHAT IS CLEARED is not decided here. tools/filemgr_groups.json (the shipped
copy of the clean-slate wipe manifest) names every GROUP: its tier, the globs
under data/ it owns, the empty form a store is left holding, and whether it
may be cleared while the station runs (hot) or only across a stop (cold).

    cache, lines, history, backups | lists, settings, configs, system3
    (the right-hand four are destructive; settings/configs/system3 also need
     the typed word)

HOT groups clear in-process through their owner (OWNERS below): the owner's
in-memory copy is reset under the owner's own lock, then the empty form is
written. A hot group with a path no owner is wired for is NOT cleared live -
it is demoted to the restart, and the plan says so.

COLD groups clear across a controlled restart through the station's own door
(the /api/service/restart road: dj_stop, then os._exit(3), docker's
unless-stopped brings it back). Before the exit a job is written to
data/filemgr/pending.json; the next process runs it from boot_run_pending(),
which app.py calls BEFORE it imports anything that loads a store - so no
process is holding a copy that could write the old contents back.
Refused while PineLive is live or a ComfyUI (H3) render is in flight.

SNAPSHOT FIRST (default on): every selected file is packed into one dated
tar under data/filemgr/snapshots/ (a KEEP path) before anything is deleted,
and the desk's export courier (#1114) owes a copy to the QuickSwap folder
named by export_desk_dir - the container cannot write QuickSwap itself.
"Restore from snapshot" unpacks one across the same controlled restart.

Every run is appended to data/filemgr/audit.jsonl (KEEP) and, when the
System 3 origin ledger is installed, stamped there as a named FORCED event
(road "operator", by "filemgr").

data/filemgr/ and data/speakbox/ are never touched by any glob.
"""
from __future__ import annotations

import copy
import glob as _glob
import io
import json
import os
import re
import shutil
import tarfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

# at module level: FastAPI reads the route annotations (from __future__ makes
# them strings) out of THIS module's globals
from fastapi import Header, HTTPException, Request

TIERS = ("cache", "lines", "history", "backups", "lists", "settings", "configs", "system3")
DESTRUCTIVE = frozenset({"lists", "settings", "configs", "system3"})
TYPED_TIERS = frozenset({"settings", "configs", "system3"})
TYPED_WORD = "RESET"
# The courier's download door is a READ road (open on the LAN by default), so
# a snapshot holding the configs tier (credentials, share links, tokens) is
# kept on the box and never handed to it.
SECRET_TIERS = frozenset({"configs"})
PRESETS = [
    # suggested_only: a preset skips the groups the manifest keeps out of
    # its own clean slate (in_this_wipe false); the operator can still tick them
    {"id": "caches", "label": "Clear caches", "tiers": ["cache"], "suggested_only": True},
    {"id": "clean", "label": "Clean slate",
     "hint": "lines + caches + history, keep System 3",
     "tiers": ["cache", "lines", "history"], "suggested_only": True},
    {"id": "reinit", "label": "Reinitialize station",
     "hint": "everything back to defaults", "tiers": list(TIERS)},
]
KEEP_TOP = frozenset({"filemgr", "speakbox"})     # never matched, never restored over
SIZE_TTL_S = 60.0             # the live walk measured 4.5 s over ~156k files
JOBS_KEEP = 60
ACTIVE_STATES = ("queued", "snapshot", "clearing", "restarting")
STALE_ACTIVE_S = 1800.0
GROUPS_FILE = Path(__file__).resolve().parent / "tools" / "filemgr_groups.json"
META_NAME = "__filemgr__.json"
ABSENT = "absent"                 # the manifest's empty form for "no file at all"

# The owners of the HOT stores, keyed by the path under data/. Each spec is
# resolved against the station's globals at clear time:
#   call   - the owner's own reset function, called as fn(empty) (preferred),
#            or as fn(deepcopy(<arg>)) when `arg` names a station value
#   lock   - the owner's lock, held while its memory is reset and written
#   memory - the owner's in-memory container (dict/list/deque), emptied in place
# A HOT group's path with no entry here is one the manifest found is read
# fresh from disk on every call (its `reason` says so), so deleting it and
# writing the empty form IS the owner's view of it. A group may also name its
# owner's HTTP road (`hot_road`, e.g. POST /api/cache/purge {...}); that road
# is called in-process with the key first, the way the station calls its own
# doors. A path whose OWNERS entry cannot be resolved goes to the restart.
OWNERS: dict[str, dict[str, str]] = {
    # settings.json has a stat-keyed memo under SETTINGS_LOCK; save_settings
    # swaps file + memo together, and DEFAULT_SETTINGS is exactly what
    # load_settings() itself writes when the file is missing or unreadable
    "settings.json": {"call": "save_settings", "arg": "DEFAULT_SETTINGS"},
}

# Its own threads: a walk or a snapshot never takes a worker from the shared
# default executor (cifs-walk-ate-the-thread-pool). Reads and the one job apart,
# so the popup can poll while a snapshot is being packed.
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="filemgr")
_WORK = ThreadPoolExecutor(max_workers=1, thread_name_prefix="filemgr-job")


# ------------------------------------------------------------------ the manifest

def _clean_rel(p: Any) -> str:
    # the manifest annotates some paths: "ads_audio/**  (contents; folder kept)",
    # "box_hold.json (if present)" - a data name never holds a space, so the
    # path is the first word
    s = str(p or "").replace("\\", "/").strip()
    s = s.split()[0] if s else ""
    while s.startswith("./"):
        s = s[2:]
    return s


def _rel_ok(rel: str) -> bool:
    if not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        return False
    parts = [x for x in rel.split("/") if x]
    if not parts or any(x == ".." for x in parts):
        return False
    return parts[0] not in KEEP_TOP


def load_groups(path: Path | str | None = None) -> dict[str, Any]:
    """The shipped manifest, validated. Never reads the scratchpad."""
    p = Path(path) if path else GROUPS_FILE
    out: dict[str, Any] = {"groups": [], "kept": [], "problems": [], "source": str(p)}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        out["problems"].append("the wipe manifest %s is not installed" % p.name)
        return out
    except Exception as exc:  # noqa: BLE001
        out["problems"].append("the wipe manifest could not be read: %s" % exc)
        return out
    seen: set[str] = set()
    for g in (raw.get("groups") if isinstance(raw, dict) else None) or []:
        if not isinstance(g, dict) or not str(g.get("id") or "").strip():
            continue
        gid = str(g["id"]).strip()
        if gid in seen:
            out["problems"].append("group %s is named twice" % gid)
            continue
        seen.add(gid)
        paths, bad = [], []
        for x in g.get("paths") or []:
            rel = _clean_rel(x)
            (paths if _rel_ok(rel) else bad).append(rel)
        empty = []
        for e in (g.get("empty") if g.get("empty") is not None else g.get("empty_forms")) or []:
            if isinstance(e, dict) and _rel_ok(_clean_rel(e.get("path"))) \
                    and "*" not in str(e.get("path")):
                val = next((e[k] for k in ("empty", "form", "value") if k in e), None)
                if val == ABSENT:
                    # the empty form IS no file: make sure the path is deleted
                    rel = _clean_rel(e["path"])
                    if rel not in paths:
                        paths.append(rel)
                    continue
                empty.append({"path": _clean_rel(e["path"]), "empty": val})
        mode = str(g.get("mode") or g.get("clear") or "").lower()
        row = {"id": gid, "label": str(g.get("label") or gid),
               "description": str(g.get("description") or g.get("desc") or ""),
               "tier": str(g.get("tier") or "").strip().lower(),
               "paths": paths, "empty": empty,
               "mode": "hot" if mode == "hot" else "cold",
               "reason": str(g.get("reason") or g.get("clear_why") or ""),
               "hot_road": str(g.get("hot_road") or ""),
               "suggested": g.get("in_this_wipe", True) is not False}
        if row["tier"] in TIERS and (paths or empty):
            out["groups"].append(row)
            if bad:          # a KEEP group naming speakbox/ is not a problem; an offered one is
                out["problems"].append("group %s: refused path(s) %s" % (gid, ", ".join(bad)))
        else:
            out["kept"].append(row)
    out["groups"].sort(key=lambda r: TIERS.index(r["tier"]))
    return out


# ------------------------------------------------------------------ disk helpers

def _walk(root: str, rel_root: str, acc: dict[str, int]) -> None:
    """Every regular file under root (scandir, never following links)."""
    try:
        it = os.scandir(root)
    except OSError:
        return
    with it:
        for ent in it:
            rel = rel_root + "/" + ent.name
            try:
                if ent.is_symlink():
                    continue
                if ent.is_dir(follow_symlinks=False):
                    _walk(ent.path, rel, acc)
                elif ent.is_file(follow_symlinks=False):
                    acc[rel] = int(ent.stat(follow_symlinks=False).st_size)
            except OSError:
                continue


def expand(data_dir: Path, group: dict[str, Any]) -> tuple[dict[str, int], list[str]]:
    """(files {rel: bytes}, matched directories) for one group's globs."""
    base = str(data_dir)
    files: dict[str, int] = {}
    dirs: list[str] = []
    for pat in group.get("paths") or []:
        for hit in sorted(_glob.glob(os.path.join(base, pat), recursive=True)):
            rel = os.path.relpath(hit, base).replace(os.sep, "/")
            if not _rel_ok(rel):
                continue
            try:
                if os.path.islink(hit):
                    continue
                if os.path.isdir(hit):
                    dirs.append(rel)
                    _walk(hit, rel, files)
                elif os.path.isfile(hit):
                    files[rel] = int(os.stat(hit).st_size)
            except OSError:
                continue
    for rel in list(files):
        if not _rel_ok(rel):
            files.pop(rel, None)
    return files, sorted(set(dirs))


def _empty_bytes(value: Any) -> bytes:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    if value is None:
        return b""
    return (json.dumps(value, indent=1) + "\n").encode("utf-8")


def write_atomic(path: Path, blob: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".fm-tmp")
    with open(tmp, "wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _subgroup(group: dict[str, Any], rels: list[str]) -> dict[str, Any]:
    keep = set(rels)
    return dict(group, paths=[p for p in group.get("paths") or [] if p in keep],
                empty=[e for e in group.get("empty") or [] if e["path"] in keep])


def _free(path: str) -> int | None:
    try:
        return int(shutil.disk_usage(path).free)
    except Exception:  # noqa: BLE001
        return None


def delete_group(data_dir: Path, group: dict[str, Any]) -> dict[str, int]:
    """Delete the FILES a group's globs match (every directory is kept),
    then write its empty forms. Returns counts. Idempotent."""
    files, dirs = expand(data_dir, group)
    empties = {e["path"]: e.get("empty") for e in group.get("empty") or []}
    gone = freed = failed = 0
    for rel, size in files.items():
        if rel in empties:
            continue
        try:
            os.unlink(data_dir / rel)
            gone += 1
            freed += size
        except FileNotFoundError:
            pass
        except OSError:
            failed += 1
    # directories are never removed: "contents; folder kept" - the station's
    # writers expect their folders (and radio_cache its skeleton) to exist
    del dirs
    written = 0
    for rel, value in empties.items():
        try:
            write_atomic(data_dir / rel, _empty_bytes(value))
            written += 1
        except OSError:
            failed += 1
    return {"files": gone, "bytes": freed, "written": written, "failed": failed}


# ------------------------------------------------------------------ the manager

def _now() -> float:
    return time.time()


def _stamp(at: float | None = None) -> str:
    return time.strftime("%Y-%m-%d_%H%M%S", time.localtime(at or _now()))


class FileManager:
    def __init__(self, data_dir: Path | str, groups_path: Path | str | None = None,
                 ns: dict[str, Any] | None = None) -> None:
        self.data = Path(data_dir)
        self.groups_path = groups_path
        self.ns = ns if ns is not None else {}
        self.home = self.data / "filemgr"
        self.jobs_path = self.home / "jobs.json"
        self.audit_path = self.home / "audit.jsonl"
        self.pending_path = self.home / "pending.json"
        self.snaps = self.home / "snapshots"
        self._lock = threading.RLock()
        self._size_lock = threading.Lock()
        self._size_memo: tuple[float, dict[str, Any]] | None = None
        # injectable for tests; the station's are wired by install()
        self.live_probe: Callable[[], str] = self._live_probe
        self.restart: Callable[[], None] = lambda: None

    # ---------------------------------------------------------- manifest
    def manifest(self) -> dict[str, Any]:
        return load_groups(self.groups_path)

    def _by_id(self) -> dict[str, dict[str, Any]]:
        return {g["id"]: g for g in self.manifest()["groups"]}

    # ---------------------------------------------------------- sizes
    def sizes(self, fresh: bool = False) -> dict[str, Any]:
        """Every group's live size. Single flight + a short memo: the walk
        runs once however many panels ask at the same moment."""
        memo = self._size_memo
        if not fresh and memo and _now() - memo[0] < SIZE_TTL_S:
            return memo[1]
        with self._size_lock:
            memo = self._size_memo
            if not fresh and memo and _now() - memo[0] < SIZE_TTL_S:
                return memo[1]
            t0 = _now()
            man = self.manifest()
            rows = []
            for g in man["groups"]:
                files, _dirs = expand(self.data, g)
                owned, unowned = self.owner_split(g)
                rows.append({
                    "id": g["id"], "label": g["label"], "description": g["description"],
                    "tier": g["tier"], "mode": g["mode"], "reason": g["reason"],
                    "effective_mode": "hot" if g["mode"] == "hot" and not unowned else "cold",
                    "unowned": unowned,
                    "destructive": g["tier"] in DESTRUCTIVE, "typed": g["tier"] in TYPED_TIERS,
                    "suggested": g.get("suggested", True),
                    "files": len(files), "bytes": sum(files.values())})
            out = {"at": _now(), "took_s": round(_now() - t0, 3), "groups": rows,
                   "kept": [{"id": k["id"], "label": k["label"], "tier": k["tier"],
                             "description": k["description"]} for k in man["kept"]],
                   "problems": man["problems"], "tiers": list(TIERS),
                   "destructive": sorted(DESTRUCTIVE), "typed_tiers": sorted(TYPED_TIERS),
                   "typed_word": TYPED_WORD, "presets": PRESETS}
            self._size_memo = (_now(), out)
            return out

    # ---------------------------------------------------------- owners
    def owner_split(self, group: dict[str, Any]) -> tuple[list[str], list[str]]:
        """(owned, unowned) paths of a HOT group: a path OWNERS names whose
        owner does not resolve in the station is unowned (and the group then
        clears in the restart). Paths OWNERS does not name are disk-fresh."""
        if group.get("mode") != "hot":
            return [], []
        owned, unowned = [], []
        rels = list(group.get("paths") or []) + [e["path"] for e in group.get("empty") or []]
        for rel in dict.fromkeys(rels):
            spec = OWNERS.get(rel)
            if spec is None:
                continue
            (owned if self._resolve(spec) else unowned).append(rel)
        if group.get("hot_road") and not self._road_ready():
            unowned.append(group["hot_road"])
        return owned, unowned

    def _road_ready(self) -> bool:
        return bool(self.ns.get("SPARK_AGENT_API_KEY")) or callable(self.ns.get("_filemgr_road"))

    def call_road(self, road: str) -> Any:
        """The owner's own HTTP door, called in-process with the key."""
        m = re.match(r"^\s*(GET|POST|PUT|DELETE)\s+(/\S+)\s*(.*)$", road or "", re.S)
        if not m:
            raise ValueError("unreadable hot road: %r" % road)
        method, path, body = m.group(1), m.group(2), m.group(3).strip()
        payload = json.loads(body) if body else None
        hook = self.ns.get("_filemgr_road")
        if callable(hook):
            return hook(method, path, payload)
        import httpx
        port = int(os.getenv("PORT", "8096") or 8096)
        r = httpx.request(method, "http://127.0.0.1:%d%s" % (port, path), json=payload, timeout=60,
                          headers={"Authorization": "Bearer %s" % self.ns.get("SPARK_AGENT_API_KEY")})
        r.raise_for_status()
        return r.json()

    def _resolve(self, spec: dict[str, str]) -> dict[str, Any] | None:
        if spec.get("fresh"):
            return {"fresh": True}
        got: dict[str, Any] = {}
        for key in ("call", "lock", "memory", "arg"):
            name = spec.get(key)
            if not name:
                continue
            obj = self.ns.get(name)
            if obj is None:
                return None
            got[key] = obj
        return got or None

    def clear_hot(self, group: dict[str, Any]) -> dict[str, int]:
        """Reset each owner's memory under its own lock, then clear the disk
        (inside that lock, so no save can land between the two)."""
        total = {"files": 0, "bytes": 0, "written": 0, "failed": 0}
        if group.get("hot_road"):
            self.call_road(group["hot_road"])
        rest: list[str] = []
        for rel in dict.fromkeys(list(group.get("paths") or [])
                                 + [e["path"] for e in group.get("empty") or []]):
            got = self._resolve(OWNERS.get(rel) or {}) or {}
            empty = next((e.get("empty") for e in group.get("empty") or []
                          if e["path"] == rel), None)
            part = _subgroup(group, [rel])
            if "call" in got:
                # the owner writes its own file (and its memo) - leave it be;
                # only other files its glob matched are deleted
                got["call"](copy.deepcopy(got["arg"]) if "arg" in got
                            else empty if empty is not None else {})
                counts = delete_group(self.data, dict(part, empty=[], paths=[
                    x for x in part["paths"] if x != rel]))
                counts["written"] = counts.get("written", 0) + 1
            elif got.get("memory") is not None:
                mem, lock = got["memory"], got.get("lock")
                with (lock if lock is not None else threading.Lock()):
                    if hasattr(mem, "clear"):
                        mem.clear()
                    if isinstance(empty, dict) and hasattr(mem, "update"):
                        mem.update(empty)
                    elif isinstance(empty, list) and hasattr(mem, "extend"):
                        mem.extend(empty)
                    counts = delete_group(self.data, part)
            else:
                rest.append(rel)
                continue
            for k in total:
                total[k] += counts.get(k, 0)
        if rest:
            counts = delete_group(self.data, _subgroup(group, rest))
            for k in total:
                total[k] += counts.get(k, 0)
        return total

    # ---------------------------------------------------------- refusals
    def _live_probe(self) -> str:
        """Why a restart must not happen now, or ''."""
        try:
            pl = getattr(self.ns.get("pinelive"), "PL", None)
            if pl is not None and str(getattr(pl, "phase", "")) == "live":
                return "PineLive is live - a restart would cut the set"
        except Exception:  # noqa: BLE001
            pass
        url = str(self.ns.get("COMFYUI_URL") or "")
        if url:
            try:
                import httpx
                q = httpx.get(url.rstrip("/") + "/queue", timeout=3).json() or {}
                if q.get("queue_running"):
                    return ("a ComfyUI render (H3) is in flight - a restart would orphan it; "
                            "wait for it to land")
            except Exception:  # noqa: BLE001
                pass
        return ""

    # ---------------------------------------------------------- plan
    def plan(self, ids: list[str], snapshot: bool = True) -> dict[str, Any]:
        by_id = self._by_id()
        want = [i for i in dict.fromkeys(str(x) for x in ids or []) if i in by_id]
        unknown = [str(x) for x in ids or [] if str(x) not in by_id]
        rows, total_f, total_b, snap_b = [], 0, 0, 0
        hot, cold = [], []
        for gid in want:
            g = by_id[gid]
            files, _dirs = expand(self.data, g)
            _owned, unowned = self.owner_split(g)
            eff = "hot" if g["mode"] == "hot" and not unowned else "cold"
            (hot if eff == "hot" else cold).append(gid)
            n, b = len(files), sum(files.values())
            total_f += n
            total_b += b
            snap_b += b + 512 * (n + 1)
            rows.append({"id": gid, "label": g["label"], "tier": g["tier"], "mode": g["mode"],
                         "effective_mode": eff, "unowned": unowned,
                         "files": n, "bytes": b, "empty": len(g["empty"])})
        tiers = {r["tier"] for r in rows}
        desk = "" if tiers & SECRET_TIERS else self._desk_dir()
        plan = {
            "groups": rows, "unknown": unknown, "files": total_f, "bytes": total_b,
            "hot": hot, "cold": cold, "restart": bool(cold),
            "destructive": bool(tiers & DESTRUCTIVE),
            "typed_word": TYPED_WORD if tiers & TYPED_TIERS else "",
            "snapshot": {"on": bool(snapshot) and total_f > 0, "bytes": snap_b + 1024,
                         "name": "pinebox-snapshot-%s.tar" % _stamp(),
                         "local_free": _free(str(self.data)),
                         "quickswap_dest": desk,
                         "kept_local_why": ("it holds the configs tier (credentials, links), so the "
                                            "desk's courier does not carry it") if tiers & SECRET_TIERS else "",
                         "quickswap_free": _free("/samples") if desk else None},
            "refusal": "",
        }
        if cold:
            plan["refusal"] = self.live_probe() or ""
        if plan["snapshot"]["on"] and plan["snapshot"]["local_free"] is not None \
                and plan["snapshot"]["local_free"] < plan["snapshot"]["bytes"] + (2 << 30):
            plan["refusal"] = plan["refusal"] or "not enough free disk for the snapshot"
        return plan

    def _desk_dir(self) -> str:
        fn = self.ns.get("export_desk_dir")
        try:
            return str(fn() or "") if callable(fn) else ""
        except Exception:  # noqa: BLE001
            return ""

    # ---------------------------------------------------------- jobs
    def _jobs_read(self) -> list[dict[str, Any]]:
        try:
            rows = json.loads(self.jobs_path.read_text(encoding="utf-8"))
            return [r for r in rows if isinstance(r, dict)]
        except Exception:  # noqa: BLE001
            return []

    def _jobs_write(self, rows: list[dict[str, Any]]) -> None:
        write_atomic(self.jobs_path, json.dumps(rows[-JOBS_KEEP:], indent=1).encode("utf-8"))

    def job_update(self, job_id: str, **fields: Any) -> dict[str, Any] | None:
        with self._lock:
            rows = self._jobs_read()
            for r in rows:
                if r.get("id") == job_id:
                    r.update(fields)
                    r["updated"] = _now()
                    self._jobs_write(rows)
                    return dict(r)
        return None

    def jobs(self) -> dict[str, Any]:
        rows = self._jobs_read()
        return {"jobs": list(reversed(rows)), "active": self.active(rows),
                "snapshots": self.snapshots()}

    def active(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
        for r in reversed(rows if rows is not None else self._jobs_read()):
            if r.get("state") in ACTIVE_STATES \
                    and _now() - float(r.get("updated") or r.get("at") or 0) < STALE_ACTIVE_S:
                return r
        return None

    def audit(self, row: dict[str, Any]) -> None:
        try:
            self.home.mkdir(parents=True, exist_ok=True)
            with open(self.audit_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(dict(row, at=row.get("at") or _now())) + "\n")
        except Exception:  # noqa: BLE001
            pass

    def stamp_forced(self, job: dict[str, Any], what: str) -> None:
        """A named FORCED System 3 event, when the origin ledger is installed."""
        note = self.ns.get("origin_side_note")
        if not callable(note):
            return
        try:
            note({"id": "filemgr-%s-%s" % (job["id"], what), "kind": "filemgr",
                  "who": "station", "aired": "published", "air_at": _now(),
                  "text": "File management: %s (%s)" % (what, ", ".join(job.get("groups") or [])),
                  "origin_forced": {"road": "operator", "by": "filemgr",
                                    "trigger": "the operator ran %s from the disk on the base bar "
                                               "(%s)" % (what, ", ".join(job.get("groups") or []))}})
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------- run
    def start(self, ids: list[str], snapshot: bool = True, typed: str = "",
              who: str = "operator") -> dict[str, Any]:
        """Validate and enqueue; the work runs in this module's own thread."""
        plan = self.plan(ids, snapshot)
        if not plan["groups"]:
            return {"ok": False, "error": "nothing selected"}
        if plan["typed_word"] and str(typed or "").strip().upper() != plan["typed_word"]:
            return {"ok": False, "error": "type %s to clear settings, configs or System 3"
                                          % plan["typed_word"], "plan": plan}
        if plan["refusal"]:
            return {"ok": False, "error": plan["refusal"], "plan": plan}
        with self._lock:
            if self.active():
                return {"ok": False, "error": "a file-management job is already running"}
            job = {"id": uuid.uuid4().hex[:10], "kind": "clear", "at": _now(), "who": who,
                   "groups": [r["id"] for r in plan["groups"]], "hot": plan["hot"],
                   "cold": plan["cold"], "snapshot": plan["snapshot"]["on"],
                   "state": "queued", "progress": {"done": 0, "total": plan["files"]},
                   "planned": {"files": plan["files"], "bytes": plan["bytes"]},
                   "steps": [], "result": {}}
            rows = self._jobs_read()
            rows.append(job)
            self._jobs_write(rows)
        self._size_memo = None
        _WORK.submit(self._run_safe, job["id"])
        return {"ok": True, "job": job, "plan": plan}

    def _run_safe(self, job_id: str) -> None:
        try:
            self.run_job(job_id)
        except Exception as exc:  # noqa: BLE001
            self.job_update(job_id, state="failed", error=str(exc)[:400])
            self.audit({"job": job_id, "event": "failed", "error": str(exc)[:400]})

    def run_job(self, job_id: str) -> dict[str, Any]:
        job = next((r for r in self._jobs_read() if r.get("id") == job_id), None)
        if not job:
            raise RuntimeError("no such job")
        by_id = self._by_id()
        groups = [by_id[g] for g in job["groups"] if g in by_id]
        steps: list[str] = []
        snap = None
        if job.get("snapshot"):
            self.job_update(job_id, state="snapshot")
            snap = self.snapshot(groups, job_id)
            steps.append("snapshot %s (%d files, %d bytes)" % (snap["name"], snap["files"], snap["bytes"]))
            self.job_update(job_id, snapshot_name=snap["name"], steps=list(steps))
        self.job_update(job_id, state="clearing")
        result: dict[str, Any] = {"groups": {}}
        for g in groups:
            if g["id"] in job.get("hot") or []:
                counts = self.clear_hot(g)
                result["groups"][g["id"]] = dict(counts, mode="hot")
                steps.append("cleared %s live (%d files)" % (g["label"], counts["files"]))
                self.job_update(job_id, steps=list(steps), result=result)
        cold = [g for g in groups if g["id"] in (job.get("cold") or [])]
        audit = {"job": job_id, "event": "clear", "who": job.get("who"), "groups": job["groups"],
                 "hot": job.get("hot"), "cold": job.get("cold"),
                 "snapshot": snap["name"] if snap else "", "result": result}
        if cold:
            write_atomic(self.pending_path, json.dumps({
                "job": job_id, "kind": "clear", "at": _now(),
                "groups": cold}, indent=1).encode("utf-8"))
            steps.append("restarting to clear %d cold group(s)" % len(cold))
            self.job_update(job_id, state="restarting", steps=list(steps), result=result)
            self.audit(dict(audit, event="clear-hot+restart"))
            self.stamp_forced(job, "clear")
            self.restart()
            return result
        self.job_update(job_id, state="done", steps=list(steps), result=result, finished=_now())
        self.audit(audit)
        self.stamp_forced(job, "clear")
        self._size_memo = None
        return result

    # ---------------------------------------------------------- snapshots
    def snapshot(self, groups: list[dict[str, Any]], job_id: str) -> dict[str, Any]:
        self.snaps.mkdir(parents=True, exist_ok=True)
        name = "pinebox-snapshot-%s.tar" % _stamp()
        final = self.snaps / name
        part = self.snaps / (name + ".part")
        members: dict[str, int] = {}
        for g in groups:
            files, _ = expand(self.data, g)
            members.update(files)
            for e in g.get("empty") or []:
                p = self.data / e["path"]
                if p.is_file() and _rel_ok(e["path"]):
                    members[e["path"]] = p.stat().st_size
        meta = {"schema": "filemgr.snapshot/1", "job": job_id, "at": _now(),
                "groups": [g["id"] for g in groups], "files": len(members),
                "bytes": sum(members.values())}
        done = 0
        with tarfile.open(part, "w") as tar:
            blob = json.dumps(meta, indent=1).encode("utf-8")
            info = tarfile.TarInfo(META_NAME)
            info.size = len(blob)
            info.mtime = int(_now())
            tar.addfile(info, io.BytesIO(blob))
            for rel in sorted(members):
                try:
                    tar.add(str(self.data / rel), arcname=rel, recursive=False)
                except OSError:
                    continue
                done += 1
                if done % 200 == 0:
                    self.job_update(job_id, progress={"done": done, "total": len(members)})
        os.replace(part, final)
        size = final.stat().st_size
        carried = ""
        desk = "" if any(g.get("tier") in SECRET_TIERS for g in groups) else self._desk_dir()
        add = self.ns.get("courier_add")
        if desk and callable(add):
            try:
                carried = str(add(final, desk, "snapshot").get("id") or "")
            except Exception:  # noqa: BLE001
                carried = ""
        return {"name": name, "files": len(members), "bytes": size, "courier": carried,
                "dest": desk}

    def snapshots(self) -> list[dict[str, Any]]:
        out = []
        try:
            with os.scandir(self.snaps) as it:
                for ent in it:
                    if ent.name.endswith(".tar") and ent.is_file():
                        st = ent.stat()
                        out.append({"name": ent.name, "bytes": st.st_size, "at": st.st_mtime})
        except OSError:
            return []
        out.sort(key=lambda r: r["at"], reverse=True)
        return out

    def restore(self, name: str, who: str = "operator") -> dict[str, Any]:
        name = os.path.basename(str(name or ""))
        if not name.endswith(".tar") or not (self.snaps / name).is_file():
            return {"ok": False, "error": "no snapshot called %s" % (name or "(none)")}
        why = self.live_probe() or ""
        if why:
            return {"ok": False, "error": why}
        with self._lock:
            if self.active():
                return {"ok": False, "error": "a file-management job is already running"}
            job = {"id": uuid.uuid4().hex[:10], "kind": "restore", "at": _now(), "who": who,
                   "groups": [], "snapshot_name": name, "state": "restarting",
                   "steps": ["restarting to restore %s" % name], "result": {}}
            rows = self._jobs_read()
            rows.append(job)
            self._jobs_write(rows)
            write_atomic(self.pending_path, json.dumps({
                "job": job["id"], "kind": "restore", "at": _now(),
                "archive": name}, indent=1).encode("utf-8"))
        self.audit({"job": job["id"], "event": "restore+restart", "who": who, "snapshot": name})
        self.stamp_forced(job, "restore")
        self.restart()
        return {"ok": True, "job": job}

    # ---------------------------------------------------------- the boot half
    def boot(self) -> dict[str, Any] | None:
        """Run a pending cold job. Called before any store is loaded. A job
        found half-run (the process died inside it) is marked failed, not
        retried - a boot must never loop."""
        running = self.home / "pending.running.json"
        if running.exists():
            try:
                old = json.loads(running.read_text(encoding="utf-8"))
                self.job_update(str(old.get("job") or ""), state="failed",
                                error="the process ended inside the cold step; not retried")
                self.audit({"job": old.get("job"), "event": "boot-interrupted"})
            except Exception:  # noqa: BLE001
                pass
            try:
                running.unlink()
            except OSError:
                pass
        if not self.pending_path.exists():
            return None
        try:
            job = json.loads(self.pending_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            job = {}
        os.replace(self.pending_path, running)
        jid = str(job.get("job") or "")
        t0 = _now()
        try:
            if job.get("kind") == "restore":
                result = self.extract(str(job.get("archive") or ""))
                what = "restored %s (%d files)" % (job.get("archive"), result["files"])
            else:
                result = {"groups": {}}
                for g in job.get("groups") or []:
                    result["groups"][g["id"]] = dict(delete_group(self.data, g), mode="cold")
                what = "cleared %d cold group(s) across the restart" % len(job.get("groups") or [])
            prev = next((r for r in self._jobs_read() if r.get("id") == jid), {}) or {}
            merged = dict(prev.get("result") or {})
            if "groups" in result and isinstance(merged.get("groups"), dict):
                merged["groups"] = dict(merged["groups"], **result["groups"])
            else:
                merged.update(result)
            self.job_update(jid, state="done", finished=_now(), result=merged,
                            steps=list(prev.get("steps") or []) + [what],
                            boot_s=round(_now() - t0, 2))
            self.audit({"job": jid, "event": "boot-" + str(job.get("kind") or "clear"),
                        "result": result, "took_s": round(_now() - t0, 2)})
            return result
        except Exception as exc:  # noqa: BLE001
            self.job_update(jid, state="failed", error=str(exc)[:400])
            self.audit({"job": jid, "event": "boot-failed", "error": str(exc)[:400]})
            return None
        finally:
            try:
                running.unlink()
            except OSError:
                pass

    def extract(self, name: str) -> dict[str, Any]:
        path = self.snaps / os.path.basename(name)
        n = b = 0
        with tarfile.open(path, "r") as tar:
            for m in tar:
                rel = _clean_rel(m.name)
                if rel == META_NAME or not m.isfile() or not _rel_ok(rel):
                    continue
                src = tar.extractfile(m)
                if src is None:
                    continue
                dest = self.data / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name(dest.name + ".fm-tmp")
                with open(tmp, "wb") as fh:
                    shutil.copyfileobj(src, fh, 1 << 20)
                os.replace(tmp, dest)
                try:
                    os.utime(dest, (m.mtime, m.mtime))
                except OSError:
                    pass
                n += 1
                b += m.size
        return {"files": n, "bytes": b}


# ------------------------------------------------------------------ the station

def boot_run_pending(data_dir: Path | str | None = None) -> dict[str, Any] | None:
    """app.py calls this first thing, before any module that loads a store."""
    try:
        d = Path(data_dir or os.getenv("SPARK_AGENT_DATA_DIR", "/app/data")).expanduser()
        fm = FileManager(d)
        got = fm.boot()
        if got is not None:
            print("[filemgr] boot: ran the pending cold job: %s" % json.dumps(got)[:400], flush=True)
        return got
    except Exception as exc:  # noqa: BLE001
        print("[filemgr] boot: the pending job could not run: %s" % exc, flush=True)
        return None


def install(app: Any, namespace: dict[str, Any]) -> FileManager:
    """Routes on `app`; the station's own doors resolved from `namespace`."""
    import asyncio

    fm = FileManager(namespace.get("DATA_DIR") or "/app/data", None, namespace)
    auth = namespace["require_auth"]
    state: dict[str, Any] = {"loop": None}

    def _restart_on_loop() -> None:
        stop = namespace.get("dj_stop")
        try:
            if callable(stop):
                stop(seal_episode=False)
        except Exception:  # noqa: BLE001
            pass
        log = namespace.get("pipeline_log")
        if callable(log):
            try:
                log("air", "[filemgr] restarting through the station's own door for a cold clear")
            except Exception:  # noqa: BLE001
                pass

        async def _die() -> None:
            await asyncio.sleep(0.8)
            os._exit(3)          # the /api/service/restart road: unless-stopped revives us
        asyncio.ensure_future(_die())

    def _restart() -> None:
        loop = state.get("loop")
        if loop is not None:
            loop.call_soon_threadsafe(_restart_on_loop)

    fm.restart = _restart

    async def _off(fn: Callable[..., Any], *a: Any) -> Any:
        state["loop"] = asyncio.get_running_loop()
        return await state["loop"].run_in_executor(_POOL, fn, *a)

    async def _body(request: Request) -> dict[str, Any]:
        try:
            got = await request.json()
            return got if isinstance(got, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    @app.get("/api/filemgr/groups")
    async def filemgr_groups(fresh: int = 0, authorization: str | None = Header(default=None)):
        """[filemgr] every wipe group with its live size (walked off the loop)."""
        auth(authorization)
        return await _off(fm.sizes, bool(fresh))

    @app.post("/api/filemgr/plan")
    async def filemgr_plan(request: Request, authorization: str | None = Header(default=None)):
        """[filemgr] exactly what a run would take: files, bytes, snapshot, free space."""
        auth(authorization)
        b = await _body(request)
        return await _off(fm.plan, list(b.get("groups") or []), bool(b.get("snapshot", True)))

    @app.post("/api/filemgr/run")
    async def filemgr_run(request: Request, authorization: str | None = Header(default=None)):
        """[filemgr] snapshot, clear the hot groups live, restart for the cold."""
        auth(authorization)
        b = await _body(request)
        state["loop"] = asyncio.get_running_loop()
        got = await _off(fm.start, list(b.get("groups") or []), bool(b.get("snapshot", True)),
                         str(b.get("typed") or ""))
        if not got.get("ok"):
            raise HTTPException(status_code=409, detail=got.get("error") or "refused")
        return got

    @app.get("/api/filemgr/jobs")
    async def filemgr_jobs(authorization: str | None = Header(default=None)):
        """[filemgr] the jobs (they survive the restart), the active one, the snapshots."""
        auth(authorization)
        return await _off(fm.jobs)

    @app.post("/api/filemgr/restore")
    async def filemgr_restore(request: Request, authorization: str | None = Header(default=None)):
        """[filemgr] the undo road: unpack a snapshot across a controlled restart."""
        auth(authorization)
        b = await _body(request)
        if not b.get("confirm"):
            raise HTTPException(status_code=400, detail="confirm the restore")
        state["loop"] = asyncio.get_running_loop()
        got = await _off(fm.restore, str(b.get("name") or ""))
        if not got.get("ok"):
            raise HTTPException(status_code=409, detail=got.get("error") or "refused")
        return got

    namespace["_FILEMGR"] = fm
    return fm

"""[qrelease] THE QUARANTINE GETS A RELEASE - per clip and per folder.

The operator, 2026-09-29: "Quarantine: ADD A RELEASE ... per clip and per
folder (e.g. after a folder is restored to the share) ... A released clip is
re-checked (exists + decodes with ffmpeg, nice'd, one at a time) before it can
air again. It stays quarantined if the check fails, with the reason shown.
Log every release. The orchestrator may PROPOSE a release, but it is
operator-confirm only."

  python3 tools/qrelease_app_patch.py --check app.py   exit 0 ready, 2 applied, 1 anchors missing (named)
  python3 tools/qrelease_app_patch.py --apply app.py   idempotent, atomic; CRLF kept CRLF

Three inserts, each on one anchor line (the msgid_lib contract):
  load    - _sfx_quarantine_load honours a `released` row, so a release
            survives the restart (the list is append-only; nothing is erased)
  helpers - sfx_release_check / sfx_quarantine_list / sfx_quarantine_release
  routes  - GET /api/sfx/quarantine, POST /api/sfx/quarantine/release

Patch app.py ON THE HOST (the share is too slow for the 10 MB file).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from msgid_lib import Edit, run  # noqa: E402

MARKER = "[qrelease]"

HELPERS = r'''# [qrelease] THE RELEASE. The quarantine list stays append-only: a release is a
# row of its own ({"released": true, "sid"|"folder"}), read by
# _sfx_quarantine_load, so nothing is erased and a restart keeps the answer.
# Every attempt - passed or kept - also goes to data/sfx_quarantine_releases.jsonl
# with who asked and why. A clip is released only after the file is on the
# share AND ffmpeg decodes it end to end (nice'd, one clip at a time, whoever
# asks). Its book row then gets back the playable value the book's own walk
# would give it (a length inside the dials, and sound unless it is a picture) -
# never 1 for a clip that is banned or glued under a join.
SFX_RELEASE_LOG = data_path("sfx_quarantine_releases.jsonl")
SFX_RELEASE_FOLDER_MOST = int(os.getenv("SFX_RELEASE_FOLDER_MOST", "200"))
_SFX_RELEASE_ONE = RLock()              # one ffmpeg check at a time
_SFX_RELEASE_JOB: dict[str, Any] = {"running": False, "folder": "", "done": 0,
                                    "total": 0, "say": "", "at": 0.0}


def _sfx_ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return shutil.which("ffmpeg") or "ffmpeg"


def sfx_release_check(path: Any, timeout: float = 180.0) -> str:
    """[qrelease] "" when the file is on the share and ffmpeg decodes it end to
    end; else the reason, in words. Blocking: call it off the loop."""
    raw = str(path or "")
    if not raw:
        return "no path is on record for it"
    try:
        if not Path(raw).is_file():
            return "the file is not on the share"
    except OSError as exc:
        return "the share did not answer (%s)" % type(exc).__name__
    cmd = [_sfx_ffmpeg_exe(), "-nostdin", "-v", "error", "-i", raw, "-f", "null", "-"]
    if shutil.which("nice"):
        cmd = ["nice", "-n", "10"] + cmd
    try:
        got = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                             timeout=timeout)
    except subprocess.TimeoutExpired:
        return "ffmpeg did not finish decoding it in %ds" % int(timeout)
    except OSError as exc:
        return "ffmpeg could not run (%s)" % type(exc).__name__
    said = str(got.stderr or "").strip()
    if got.returncode != 0 or _SFX_UNDECODABLE_RE.search(said):
        return ("ffmpeg: %s" % (" / ".join(said.split("\n")[-2:])
                                or "exit %d" % got.returncode))[:240]
    return ""


def _sfx_jsonl(path: Path, most: int = 0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in (lines[-most:] if most else lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _sfx_release_write(row: dict[str, Any], also_list: bool = False) -> None:
    try:
        with _SFX_QUARANTINE_LOCK:
            SFX_RELEASE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with SFX_RELEASE_LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            if also_list:
                with _sfx_quarantine_path().open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({k: row.get(k) for k in (
                        "at", "sid", "folder", "path", "by", "why")
                        if row.get(k) not in (None, "")} | {"released": True},
                        ensure_ascii=False) + "\n")
    except OSError:
        pass


def _sfx_book_restore(sid: str, path: Any) -> int:
    """The book walk's own playable rule for one clip, written back."""
    p = Path(str(path))
    glued: set[str] = set()
    try:
        for g in (sfx_glue_book() or {}).get("glued") or []:
            glued.update(str(x) for x in (g.get("part_ids") or []))
    except Exception:  # noqa: BLE001
        pass
    playable = 0
    try:
        if sid not in sfx_bans() and sid not in glued:
            secs = sfx_seconds_held(p)
            if secs is not None and sfx_floor_seconds() <= secs <= sfx_cap_seconds():
                playable = 1 if sfx_is_video(p) else (0 if sfx_is_silent(p) else 1)
    except Exception:  # noqa: BLE001
        playable = 0
    try:
        with _SFX_DB_LOCK:
            con = sfx_db()
            con.execute("UPDATE clips SET playable = ? WHERE sid = ?", (playable, sid))
            con.commit()
    except Exception:  # noqa: BLE001
        pass
    return playable


def sfx_quarantine_list() -> dict[str, Any]:
    """[qrelease] What is held, by clip and by folder, with the last failed
    check's reason. Blocking (reads two files, one stat per folder)."""
    _sfx_quarantine_load()
    latest: dict[str, dict[str, Any]] = {}
    for r in _sfx_jsonl(_sfx_quarantine_path()):
        sid = str(r.get("sid") or "")
        if r.get("released"):
            latest.pop(sid, None)
        elif sid:
            latest[sid] = r
    kept: dict[str, str] = {}
    releases = _sfx_jsonl(SFX_RELEASE_LOG, 2000)
    for r in releases:
        if r.get("sid"):
            if r.get("ok"):
                kept.pop(str(r["sid"]), None)
            else:
                kept[str(r["sid"])] = str(r.get("reason") or "")
    clips = []
    for sid in sorted(set(_SFX_QUARANTINED)):
        r = latest.get(sid) or {}
        path = str(r.get("path") or "")
        clips.append({"sid": sid, "name": Path(path).name if path else sid, "path": path,
                      "folder": str(Path(path).parent) if path else "",
                      "why": r.get("why"), "by": r.get("by"), "at": r.get("at"),
                      "last_check": kept.get(sid)})
    clips.sort(key=lambda c: -float(c.get("at") or 0))
    per: dict[str, int] = {}
    for c in clips:
        if c["folder"]:
            per[c["folder"]] = per.get(c["folder"], 0) + 1
    gone = set(_SFX_GONE_FOLDERS)
    folders = []
    for f in sorted(set(per) | gone):
        try:
            here = Path(f).is_dir()
        except OSError:
            here = False
        folders.append({"folder": f, "clips": per.get(f, 0), "gone": f in gone,
                        "back": f in gone and here})
    return {"clips": clips, "folders": folders, "releases": releases[-20:],
            "job": dict(_SFX_RELEASE_JOB), "log": str(SFX_RELEASE_LOG)}


def _sfx_release_one(sid: str, path: Any, by: str, why: str, folder: str = "") -> dict[str, Any]:
    with _SFX_RELEASE_ONE:
        reason = sfx_release_check(path)
        row = {"at": round(time.time(), 3), "sid": sid, "path": str(path or "")[:400],
               "folder": folder, "by": str(by or "")[:80], "why": str(why or "")[:200],
               "ok": not reason, "reason": reason}
        if reason:
            _sfx_release_write(row)
            return row
        with _SFX_QUARANTINE_LOCK:
            _SFX_QUARANTINED.discard(sid)
            _SFX_RECEIPT_STRIKES.pop(sid, None)
        row["playable"] = _sfx_book_restore(sid, path)
        _sfx_release_write(row, also_list=True)
        return row


def _sfx_release_folder(folder: str, targets: list[tuple[str, str]], by: str, why: str) -> None:
    """Worker thread: a folder back on the share, one clip at a time."""
    ok = kept = 0
    try:
        for sid, path in targets:
            got = _sfx_release_one(sid, path, by, why, folder)
            ok += int(bool(got.get("ok")))
            kept += int(not got.get("ok"))
            _SFX_RELEASE_JOB["done"] = ok + kept
        say = ("folder %s: %d clip(s) passed the check and may air again, %d stay "
               "quarantined with the reason shown" % (folder, ok, kept))
    except Exception as exc:  # noqa: BLE001
        say = "folder %s: the release stopped - %s" % (folder, type(exc).__name__)
    _SFX_RELEASE_JOB.update(running=False, say=say, at=time.time())
    try:
        pipeline_log("air", "[qrelease] " + say)
    except Exception:  # noqa: BLE001
        pass


def sfx_quarantine_release(sid: str = "", folder: str = "", by: str = "",
                           why: str = "") -> dict[str, Any]:
    """[qrelease] Release one clip (checked now) or a folder (checked on a
    worker thread, one clip at a time; the list shows the progress).
    Blocking for a clip: call it off the loop."""
    _sfx_quarantine_load()
    sid, folder = str(sid or "").strip(), str(folder or "").strip().rstrip("/")
    by = str(by or "the operator")
    if sid:
        if sid not in _SFX_QUARANTINED:
            return {"ok": False, "say": "clip %s is not quarantined" % sid, "results": []}
        held = {c["sid"]: c for c in sfx_quarantine_list()["clips"]}
        path = str((held.get(sid) or {}).get("path") or "") or str(sfx_by_id(sid) or "")
        row = _sfx_release_one(sid, path, by, why)
        say = (("%s passed the check and may air again" % (Path(path).name or sid))
               if row["ok"] else ("%s stays quarantined: %s" % (Path(path).name or sid, row["reason"])))
        try:
            pipeline_log("air", "[qrelease] " + say + " (asked by %s)" % by)
        except Exception:  # noqa: BLE001
            pass
        return {"ok": bool(row["ok"]), "say": say, "results": [row]}
    if not folder:
        return {"ok": False, "say": "name a clip (sid) or a folder", "results": []}
    if _SFX_RELEASE_JOB.get("running"):
        return {"ok": False, "say": "a folder release is already running (%s)"
                % _SFX_RELEASE_JOB.get("folder"), "results": [], "job": dict(_SFX_RELEASE_JOB)}
    try:
        here = Path(folder).is_dir()
    except OSError:
        here = False
    if not here:
        _sfx_release_write({"at": round(time.time(), 3), "folder": folder, "by": by,
                            "why": str(why or "")[:200], "ok": False,
                            "reason": "the folder is not on the share"})
        return {"ok": False, "say": "folder %s is not on the share - it stays quarantined" % folder,
                "results": []}
    lifted = False
    with _SFX_QUARANTINE_LOCK:
        if folder in _SFX_GONE_FOLDERS:
            _SFX_GONE_FOLDERS.discard(folder)
            lifted = True
    if lifted:
        _sfx_release_write({"at": round(time.time(), 3), "folder": folder, "by": by,
                            "why": str(why or "")[:200], "ok": True,
                            "reason": "the folder is back on the share"}, also_list=True)
    targets = [(c["sid"], c["path"]) for c in sfx_quarantine_list()["clips"]
               if c["folder"] == folder or c["folder"].startswith(folder + "/")]
    if lifted:
        # the folder stand-down zeroed every book row under it; those rows
        # are checked the same way (their clips were never judged undecodable)
        try:
            with _SFX_DB_LOCK:
                con = sfx_db()
                rows = con.execute("SELECT sid, path FROM clips WHERE path >= ? AND path < ? "
                                   "AND playable = 0", (folder + "/", folder + "0")).fetchall()
            seen = {s for s, _ in targets}
            targets += [(str(s), str(p)) for s, p in rows if str(s) not in seen]
        except Exception:  # noqa: BLE001
            pass
    more = max(0, len(targets) - SFX_RELEASE_FOLDER_MOST)
    targets = targets[:SFX_RELEASE_FOLDER_MOST]
    _SFX_RELEASE_JOB.update(running=True, folder=folder, done=0, total=len(targets),
                            say="checking %d clip(s) in %s one at a time" % (len(targets), folder),
                            at=time.time())
    Thread(target=_sfx_release_folder, args=(folder, targets, by, why),
           daemon=True, name="qrelease").start()
    return {"ok": True, "started": True, "results": [], "job": dict(_SFX_RELEASE_JOB),
            "say": ("%s%d clip(s) are being checked one at a time; the list shows each result%s"
                    % ("the folder is back on the share. " if lifted else "", len(targets),
                       ("; %d more wait for another release" % more) if more else ""))}


'''

ROUTES = r'''@app.get("/api/sfx/quarantine")
async def sfx_quarantine_list_api(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[qrelease] every quarantined clip, by folder, with the last check."""
    require_read_auth(authorization)
    return await asyncio.to_thread(sfx_quarantine_list)


@app.post("/api/sfx/quarantine/release")
async def sfx_quarantine_release_api(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[qrelease] {"sid": id} or {"folder": path} [, "why": text]. The clip is
    re-checked (on the share, decodes with ffmpeg) before it may air again;
    a folder is checked clip by clip on a worker thread. Logged, every one."""
    require_auth(authorization)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    body = body if isinstance(body, dict) else {}
    sid = str(body.get("sid") or "")[:40]
    folder = str(body.get("folder") or "")[:400]
    if not sid and not folder:
        raise HTTPException(status_code=400, detail="name a clip (sid) or a folder")
    got = await asyncio.to_thread(sfx_quarantine_release, sid, folder,
                                  str(body.get("by") or "the operator")[:80],
                                  str(body.get("why") or "")[:200])
    try:
        note_action("you released %s from the SFX quarantine" % (sid or folder))
    except Exception:  # noqa: BLE001
        pass
    return got


'''

EDITS = [
    Edit("load",
         '                if row.get("sid"):\n                    _SFX_QUARANTINED.add(str(row["sid"]))\n',
         '                if row.get("released"):     # [qrelease] a release row\n'
         '                    if row.get("sid"):\n'
         '                        _SFX_QUARANTINED.discard(str(row["sid"]))\n'
         '                    if row.get("folder"):\n'
         '                        _SFX_GONE_FOLDERS.discard(str(row["folder"]))\n'
         '                    continue\n',
         where="before"),
    Edit("helpers", "def sfx_clip_refusal(path: Any, check_file: bool = False) -> str:\n", HELPERS, where="before"),
    Edit("routes", '@app.get("/api/sfx/video/mode")\n', ROUTES, where="before"),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS, marker=MARKER))

#!/usr/bin/env python3
"""[video-folders-live] The Video menu names every folder on the share and reads new ones into the book. 2026-10-14.

"for some reason, 'user' isnt listed. When a new path is detected added to the list and I want it
to rescan and add to the list anytime I expand the drop down" - the PiP's Video submenu.

The menu listed the clip book, and the book only learned the folders the boot walk visits: the
first SFX_DROP_SUBS (60) of samples_grabbed, alphabetically, one level down, user/ skipped.
Measured that day: 185 folders on the share, 73 of them (about 240,000 files) never in the book,
user/gBox among them, and nothing re-read the book between restarts.

  the LOOK    one scandir per drop root and per folder under it whose mtime moved (two levels),
              on its own thread: the list names every folder on disk, read or not, a nested one
              under its parent (user above user/gBox, counting everything below it).
  the READER  one folder at a time - the pin first, then the never-read, smallest first - writes
              each new clip into the book with a length measured off the file (the length ledger
              is left alone, #1251c), 500 files a visit, a breath between files.
  the MENU    every open asks for the book again (?fresh=1, grouped in sqlite) and kicks the look;
              the station's sfx keeper kicks it too, so a folder dropped on the share is found
              with the menu shut.

user/ stays out of the sting pool (SFX_DROP_SKIP, the listener lane): its subfolders are read for
VIDEO only, so a listener's song never becomes a sting. Off switch: dj setting sfx_book_reader.

Patched: app.py, desktop/pip-window.cjs (next relaunch), both copies of pine-pip.js.

Usage:  video_folders_live_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        video_folders_live_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BS = chr(92)

# --------------------------------------------------------------------------- app.py
APP_MEASURE_OLD = r'''    secs = 0.0
    if path.suffix.lower() == ".wav":
        import wave
        try:
            with wave.open(str(path), "rb") as handle:
                secs = handle.getnframes() / float(handle.getframerate() or 1)
        except Exception:
            secs = 0.0
    if secs <= 0:
        try:
            import mutagen
            info = mutagen.File(str(path))
            secs = float(getattr(getattr(info, "info", None), "length", 0) or 0)
        except Exception:
            secs = 0.0
    if secs <= 0 and sfx_is_video(path):
        secs = _media_duration_probe(path)      # #1263
'''
APP_MEASURE_NEW = r'''    secs = sfx_measure(path)                    # [video-folders-live] the measuring, shared with the book reader
'''

APP_MEASURE_FN_OLD = r'''def sfx_seconds(path: Path) -> float:
    """How long a sample actually runs. 0.0 means we could not tell.
'''
APP_MEASURE_FN_NEW = r'''def sfx_measure(path: Path) -> float:
    """[video-folders-live] How long the file runs, read off the file itself: a wav header, then
    mutagen, then (a video) the media probe. 0.0 = could not tell. No cache and no ledger - that
    is sfx_seconds' business; the book reader keeps its lengths in the book."""
    secs = 0.0
    if path.suffix.lower() == ".wav":
        import wave
        try:
            with wave.open(str(path), "rb") as handle:
                secs = handle.getnframes() / float(handle.getframerate() or 1)
        except Exception:
            secs = 0.0
    if secs <= 0:
        try:
            import mutagen
            info = mutagen.File(str(path))
            secs = float(getattr(getattr(info, "info", None), "length", 0) or 0)
        except Exception:
            secs = 0.0
    if secs <= 0 and sfx_is_video(path):
        secs = _media_duration_probe(path)      # #1263
    return secs


def sfx_seconds(path: Path) -> float:
    """How long a sample actually runs. 0.0 means we could not tell.
'''

APP_VIEW_OLD = r'''def sfx_folders_view() -> dict[str, Any]:
    """[sfx-folders-cache] The folder list, kept: the first call walks the book (slow, the database
    is on the share); later calls answer from the kept list and renew it in the background once it
    is five minutes old. The pin is read fresh every time."""
    now = time.time()
    memo = _SFX_FOLDERS_MEMO
    folders = memo.get("folders")
    if folders is None or now - float(memo.get("at") or 0) > SFX_FOLDERS_KEEP_S:
'''
APP_VIEW_NEW = r'''def sfx_folders_view(fresh: bool = False) -> dict[str, Any]:
    """[sfx-folders-cache] The folder list, kept: the first call walks the book (slow, the database
    is on the share); later calls answer from the kept list and renew it in the background once it
    is five minutes old. The pin is read fresh every time.
    [video-folders-live] `fresh` (the PiP menu, every time it opens) reads the book now and asks
    the look for folders the share has grown since."""
    now = time.time()
    memo = _SFX_FOLDERS_MEMO
    folders = memo.get("folders")
    if fresh:
        sfx_book_kick()
    if fresh or folders is None or now - float(memo.get("at") or 0) > SFX_FOLDERS_KEEP_S:
'''

APP_VIEW_RET_OLD = r'''    return {"ok": True, "folders": folders, "pin": pin, "kept_s": round(time.time() - float(memo.get("at") or 0), 1),
'''
APP_VIEW_RET_NEW = r'''    return {"ok": True, "folders": folders, "pin": pin, "kept_s": round(time.time() - float(memo.get("at") or 0), 1),
            "reader": sfx_book_state(),             # [video-folders-live]
'''

APP_SCAN_OLD = r'''def _sfx_folders_scan() -> list[dict[str, Any]]:
    """Every folder the book knows, with counts and a few samples to
    preview - one read of the book, grouped here."""
    out: dict[str, dict[str, Any]] = {}
    try:
        con = sfx_db_reader()
        rows = con.execute(
            "SELECT path, sid, name, video, seconds FROM clips WHERE playable = 1").fetchall()
    except Exception:  # noqa: BLE001
        rows = []
    for r in rows:
        p = str(r["path"] or "")
        d = p.rsplit("/", 1)[0] if "/" in p else ""
        if not d:
            continue
        f = out.setdefault(d, {"path": d, "name": d.rsplit("/", 1)[-1], "audio": 0, "video": 0, "samples": []})
        is_v = bool(r["video"])
        f["video" if is_v else "audio"] += 1
        want = 3
        have = sum(1 for x in f["samples"] if x["video"] == is_v)
        if have < want:
            sid = str(r["sid"] or "")
            f["samples"].append({"id": sid, "name": str(r["name"] or "")[:60], "video": is_v,
                                 "url": f"/sfx/{sid}?t={media_sign(sid)}",
                                 "seconds": round(float(r["seconds"] or 0), 1)})
    return sorted(out.values(), key=lambda f: f["path"])[:300]
'''
APP_SCAN_NEW = r'''def _sfx_folders_scan() -> list[dict[str, Any]]:
    """Every folder the book knows, with counts and a few samples to
    preview - one read of the book, grouped here.

    [video-folders-live] Grouped by sqlite, not by a Python loop over 368,000 rows (0.8 s with the
    GIL let go), then merged with the look: every folder on the share, read or not ("unread"), and
    each parent of a nested folder (user above user/gBox) counting everything under it."""
    out: dict[str, dict[str, Any]] = {}
    con = None
    try:
        con = sfx_db_reader()
        rows = con.execute(
            "SELECT rtrim(path, replace(path, '/', '')) AS d,"
            " SUM(playable = 1 AND video = 1) AS v, SUM(playable = 1 AND video = 0) AS a,"
            " SUM(playable = 0) AS held FROM clips GROUP BY d").fetchall()
    except Exception:  # noqa: BLE001
        rows = []
    for r in rows:
        d = str(r[0] or "").rstrip("/")
        if not d:
            continue
        out[d] = {"path": d, "name": d.rsplit("/", 1)[-1], "video": int(r[1] or 0),
                  "audio": int(r[2] or 0), "held": int(r[3] or 0), "samples": []}
    for d, f in out.items():
        for is_v in (1, 0):
            if con is None or not f["video" if is_v else "audio"]:
                continue
            try:
                got = con.execute(
                    "SELECT sid, name, seconds FROM clips WHERE path >= ? AND path < ? AND playable = 1"
                    " AND video = ? LIMIT 3", (d + "/", d + "0", is_v)).fetchall()
            except Exception:  # noqa: BLE001
                got = []
            for s in got:
                sid = str(s[0] or "")
                f["samples"].append({"id": sid, "name": str(s[1] or "")[:60], "video": bool(is_v),
                                     "url": f"/sfx/{sid}?t={media_sign(sid)}",
                                     "seconds": round(float(s[2] or 0), 1)})
    for d, info in dict(_SFX_BOOK.get("disk") or {}).items():
        if d not in out and int(info.get("files") or 0) > 0:
            out[d] = {"path": d, "name": d.rsplit("/", 1)[-1], "video": 0, "audio": 0, "held": 0,
                      "samples": [], "unread": True, "files": int(info.get("files") or 0)}
    roots = _sfx_book_roots()
    own = [(d, f["video"], f["audio"]) for d, f in out.items()]
    for d, v, a in own:
        root = next((r for r in roots if d.startswith(r + "/")), "")
        rel = d[len(root) + 1:] if root else ""
        if "/" not in rel:
            continue
        parts = rel.split("/")
        out[d]["name"] = rel
        out[d]["parent"] = root + "/" + "/".join(parts[:-1])
        for i in range(1, len(parts)):
            anc = root + "/" + "/".join(parts[:i])
            p = out.get(anc)
            if p is None:
                p = out[anc] = {"path": anc, "name": "/".join(parts[:i]), "video": 0, "audio": 0,
                                "held": 0, "samples": []}
                if i > 1:
                    p["parent"] = root + "/" + "/".join(parts[:i - 1])
            p["video"] += v
            p["audio"] += a
    return sorted(out.values(), key=lambda f: f["path"])[:1000]
'''

APP_API_OLD = r'''@app.get("/api/sfx/folders")
async def sfx_folders_api(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_read_auth(authorization)
    return await asyncio.to_thread(sfx_folders_view)
'''
APP_API_NEW = r'''@app.get("/api/sfx/folders")
async def sfx_folders_api(fresh: int = 0, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_read_auth(authorization)
    return await asyncio.to_thread(sfx_folders_view, bool(fresh))     # [video-folders-live]


# --- [video-folders-live] THE LOOK AND THE READER ---------------------------------------
SFX_BOOK_LOOK_EVERY_S = 20.0            # a menu opened twice in a breath looks once
SFX_BOOK_READ_GAP_S = 0.05              # between two files measured off the share
SFX_BOOK_SLICE = 500                    # files a visit; a big folder yields to the next look
SFX_BOOK_MATCH_EVERY_S = 1800.0         # the keyword index is rebuilt at most this often mid-read
SFX_BOOK_READ_PATH = data_path("sfx_book_read.json")
_SFX_BOOK: dict[str, Any] = {"busy": False, "at": 0.0, "again": False, "first": "", "disk": {},
                             "read": None, "now": "", "left": 0, "added": 0, "folders": 0,
                             "why": "", "finished": 0.0}
_SFX_BOOK_GATE = RLock()
_SFX_BOOK_UPSERT = (
    "INSERT INTO clips (path, sid, name, folder, video, bytes, mtime, seconds, playable, seen_at) "
    "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET "
    " sid=excluded.sid, name=excluded.name, folder=excluded.folder, video=excluded.video,"
    " bytes=excluded.bytes, mtime=excluded.mtime,"
    " seconds=COALESCE(excluded.seconds, clips.seconds),"
    " playable=MAX(excluded.playable, clips.playable), seen_at=excluded.seen_at")


def _sfx_book_roots() -> list[str]:
    """The drop roots (samples_grabbed), spelled the way the book spells its paths. No stat."""
    try:
        drops = dj_settings().get("sfx_drop_folders")
        if drops is None:
            drops = list(SFX_DROP_FOLDERS)
    except Exception:  # noqa: BLE001
        drops = list(SFX_DROP_FOLDERS)
    out = []
    for name in drops:
        wanted = str(name or "").strip().strip("/")
        if wanted and ".." not in wanted:
            out.extend(str(base / wanted) for base in (SFX_ROOT, SFX_LOCAL_ROOT))
    return out


def _sfx_book_on() -> bool:
    try:
        return dj_settings().get("sfx_book_reader", True) is not False
    except Exception:  # noqa: BLE001
        return True


def sfx_book_state() -> dict[str, Any]:
    b = _SFX_BOOK
    say = ""
    if b.get("busy") and b.get("now"):
        say = "Reading %s into the clip book (%d folder%s waiting) - open the menu again to see it" % (
            Path(str(b["now"])).name, int(b.get("left") or 0), "" if int(b.get("left") or 0) == 1 else "s")
    return {"busy": bool(b.get("busy")), "now": b.get("now") or "", "left": int(b.get("left") or 0),
            "added": int(b.get("added") or 0), "folders": int(b.get("folders") or 0),
            "why": b.get("why") or "", "finished": b.get("finished") or 0.0, "say": say,
            "on": _sfx_book_on()}


def _sfx_book_look_one(path: str, video_only: bool, depth: int, disk: dict, was: dict) -> None:
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return
    old = was.get(path)
    if old and old.get("mtime") == mtime:
        files, kids = int(old.get("files") or 0), list(old.get("kids") or [])
    else:
        files, kids = 0, []
        types = SFX_VIDEO_TYPES if video_only else SFX_TYPES
        own_files = not (video_only and depth == 1)      # user/ itself is the listener courier's
        try:
            with os.scandir(path) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        if depth < 2:
                            kids.append(e.path)
                    elif own_files and os.path.splitext(e.name)[1].lower() in types:
                        files += 1
        except OSError:
            return
    disk[path] = {"mtime": mtime, "files": files, "kids": kids, "video_only": video_only}
    for kid in kids:
        _sfx_book_look_one(kid, video_only, depth + 1, disk, was)


def _sfx_book_look() -> dict[str, Any]:
    """One scandir per drop root and per folder whose mtime moved; a stat for the rest."""
    was = dict(_SFX_BOOK.get("disk") or {})
    disk: dict[str, Any] = {}
    for root in _sfx_book_roots():
        if not sfx_reach_ok(root):
            sfx_reach_stood_down("book-look")
            continue
        try:
            with os.scandir(root) as it:
                subs = [e for e in it if e.is_dir(follow_symlinks=False)]
        except OSError:
            continue
        for e in subs:
            _sfx_book_look_one(e.path, e.name.lower() in SFX_DROP_SKIP, 1, disk, was)
    _SFX_BOOK["disk"] = disk
    _SFX_FOLDERS_MEMO["at"] = 0.0
    return disk


def _sfx_book_ledger() -> dict[str, float]:
    if _SFX_BOOK.get("read") is None:
        try:
            got = json.loads(SFX_BOOK_READ_PATH.read_text())
            _SFX_BOOK["read"] = {str(k): float(v) for k, v in got.items()} if isinstance(got, dict) else {}
        except Exception:  # noqa: BLE001
            _SFX_BOOK["read"] = {}
    return _SFX_BOOK["read"]


def _sfx_book_queue(disk: dict) -> list[str]:
    """Folders with files the reader has not read at their current mtime: the pin (or the folder
    just asked for) first, then folders the book has never held, smallest first."""
    read = _sfx_book_ledger()
    first = str(_SFX_BOOK.get("first") or "") or sfx_pin_prefix().rstrip("/")
    _SFX_BOOK["first"] = ""
    try:
        booked = {str(r[0]).rstrip("/") for r in sfx_db_reader().execute(
            "SELECT DISTINCT rtrim(path, replace(path, '/', '')) FROM clips").fetchall()}
    except Exception:  # noqa: BLE001
        booked = set()
    want = [(p, info) for p, info in disk.items()
            if int(info.get("files") or 0) > 0 and read.get(p) != info.get("mtime")]

    def rank(item: tuple) -> tuple:
        p, info = item
        pinned = 0 if first and (p == first or p.startswith(first + "/")) else 1
        return (pinned, 1 if p in booked else 0, int(info.get("files") or 0), p)

    return [p for p, _ in sorted(want, key=rank)]


def _sfx_book_read(folder: str, info: dict) -> tuple[int, bool]:
    """One visit to one folder: up to SFX_BOOK_SLICE clips the book lacks, measured and written.
    Returns (added, finished)."""
    types = SFX_VIDEO_TYPES if info.get("video_only") else SFX_TYPES
    con = sfx_db()
    with _SFX_DB_LOCK:
        known = {str(r[0]) for r in con.execute(
            "SELECT path FROM clips WHERE path >= ? AND path < ?", (folder + "/", folder + "0")).fetchall()}
    try:
        with os.scandir(folder) as it:
            names = sorted(e.path for e in it if not e.is_dir(follow_symlinks=False)
                           and os.path.splitext(e.name)[1].lower() in types and e.path not in known)
    except OSError as err:
        _SFX_BOOK["why"] = str(err)[:160]
        return 0, True
    banned = sfx_bans() | sfx_superseded()
    names = [one for one in names if sfx_id(Path(one)) not in banned]
    added, rows, tried = 0, [], 0

    def write() -> None:
        with _SFX_DB_LOCK:
            con.executemany(_SFX_BOOK_UPSERT, rows)
            con.commit()

    for one in names:
        if tried >= SFX_BOOK_SLICE or not _sfx_book_on() or not sfx_reach_ok(one):
            break
        tried += 1
        path = Path(one)
        sid = sfx_id(path)
        try:
            st = path.stat()
        except OSError:
            continue
        secs = sfx_seconds_held(path)
        if secs is None:
            secs = sfx_measure(path)
        is_video = 1 if sfx_is_video(path) else 0
        playable = 0
        if secs and sfx_floor_seconds() <= secs <= sfx_cap_seconds():
            playable = 1 if is_video else (0 if sfx_is_silent(path) else 1)
        rows.append((one, sid, path.stem, path.parent.name, is_video, int(st.st_size), float(st.st_mtime),
                     float(secs) if secs else None, playable, time.time()))
        if len(rows) >= 100:
            write()
            added += len(rows)
            rows = []
        time.sleep(SFX_BOOK_READ_GAP_S)
    if rows:
        write()
        added += len(rows)
    return added, tried == len(names)


def _sfx_book_run() -> None:
    b = _SFX_BOOK
    matched_at = time.time()
    added_since = 0
    try:
        disk = _sfx_book_look()
        queue = _sfx_book_queue(disk) if _sfx_book_on() else []
        while queue and _sfx_book_on():
            if b.get("again") and time.time() - float(b.get("at") or 0) >= SFX_BOOK_LOOK_EVERY_S:
                b.update(again=False, at=time.time())
                disk = _sfx_book_look()
                queue = _sfx_book_queue(disk)
                if not queue:
                    break
            folder = queue[0]
            b.update(now=folder, left=len(queue) - 1)
            info = disk.get(folder) or {}
            got, finished = _sfx_book_read(folder, info)
            b["added"] = int(b.get("added") or 0) + got
            added_since += got
            if got:
                _SFX_FOLDERS_MEMO["at"] = 0.0
            if finished:
                queue.pop(0)
                b["folders"] = int(b.get("folders") or 0) + 1
                read = _sfx_book_ledger()
                read[folder] = info.get("mtime")
                try:
                    tmp = SFX_BOOK_READ_PATH.with_suffix(".tmp")
                    tmp.write_text(json.dumps(read))
                    tmp.replace(SFX_BOOK_READ_PATH)
                except OSError:
                    pass
                if got:
                    pipeline_log("air", "clip book: read %s - %d new clip(s) (%d folder(s) waiting)"
                                 % (folder, got, len(queue)))
            if added_since and time.time() - matched_at > SFX_BOOK_MATCH_EVERY_S:
                matched_at, added_since = time.time(), 0
                sfx_match_kick()
    except Exception as err:  # noqa: BLE001
        b["why"] = str(err)[:200]
        print("[sfx-book] reader failed: %s" % err, flush=True)
    finally:
        b.update(busy=False, now="", left=0, finished=time.time())
        if added_since:
            try:
                sfx_match_kick()
            except Exception:  # noqa: BLE001
                pass


def sfx_book_kick(first: str = "") -> bool:
    """Look (and read what is new) on its own thread, one at a time. A kick while it runs asks it to
    look again between folders; `first` puts that folder at the front of the queue."""
    with _SFX_BOOK_GATE:
        if first:
            _SFX_BOOK["first"] = str(first).rstrip("/")
        if _SFX_BOOK.get("busy"):
            _SFX_BOOK["again"] = True
            return False
        if not first and time.time() - float(_SFX_BOOK.get("at") or 0) < SFX_BOOK_LOOK_EVERY_S:
            return False
        _SFX_BOOK.update(busy=True, at=time.time(), again=False, why="")
    Thread(target=_sfx_book_run, name="sfx-book", daemon=True).start()
    return True


@app.get("/api/sfx/book-reader")
async def sfx_book_reader_api(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_read_auth(authorization)
    return {"ok": True, **sfx_book_state()}
'''

APP_PIN_OLD = r'''    got = sfx_pin_set(path, hours)
    pin = sfx_pin_view()
'''
APP_PIN_NEW = r'''    got = sfx_pin_set(path, hours)
    sfx_book_kick(first=path)                   # [video-folders-live] a pinned folder is read first
    pin = sfx_pin_view()
'''

APP_KEEPER_OLD = r'''            await _sfx_pool_refresh()
        except Exception:  # noqa: BLE001
            pass                    # a missed rescan is not a dead show
'''
APP_KEEPER_NEW = r'''            await _sfx_pool_refresh()
        except Exception:  # noqa: BLE001
            pass                    # a missed rescan is not a dead show
        try:
            sfx_book_kick()         # [video-folders-live] new folders reach the book with the menu shut
        except Exception:  # noqa: BLE001
            pass
'''

APP = [
    ("sfx_seconds measures through it", APP_MEASURE_OLD, APP_MEASURE_NEW, "secs = sfx_measure(path)                    # [video-folders-live]", 1),
    ("sfx_measure, the measuring off the file", APP_MEASURE_FN_OLD, APP_MEASURE_FN_NEW, "def sfx_measure(path: Path) -> float:", 1),
    ("the folder view reads fresh on ask", APP_VIEW_OLD, APP_VIEW_NEW, "def sfx_folders_view(fresh: bool = False)", 1),
    ("the folder view says the reader", APP_VIEW_RET_OLD, APP_VIEW_RET_NEW, '"reader": sfx_book_state(),             # [video-folders-live]', 1),
    ("the scan is grouped and merged", APP_SCAN_OLD, APP_SCAN_NEW, "[video-folders-live] Grouped by sqlite", 1),
    ("the look, the reader, the api", APP_API_OLD, APP_API_NEW, "def sfx_book_kick(first: str = \"\") -> bool:", 1),
    ("a pin reads its folder first", APP_PIN_OLD, APP_PIN_NEW, "sfx_book_kick(first=path)", 1),
    ("the keeper kicks the look", APP_KEEPER_OLD, APP_KEEPER_NEW, "sfx_book_kick()         # [video-folders-live]", 1),
]

# --------------------------------------------------------------------------- pip-window.cjs
WIN_FN_OLD = r'''  function menu(playback = {}) {
'''
WIN_FN_NEW = r'''  /* [video-folders-live] the Video submenu: every folder on the share, read or not; a folder with
     folders inside opens to them, and its first row pins the whole of it */
  function videoFolderMenu(playback, send) {
    const folders = (Array.isArray(playback?.folders) ? playback.folders : []).filter(f => f && typeof f.path === 'string');
    const pinned = playback?.pin?.path || '';
    const words = f => f.unread ? '  (new - ' + (f.files ? f.files + ' file' + (f.files === 1 ? '' : 's') + ', ' : '') + 'reading)'
      : '  (' + (f.video || 0) + ' video, ' + (f.audio || 0) + ' audio)';
    const kids = new Map(), known = new Set(folders.map(f => f.path));
    for (const f of folders) if (f.parent && known.has(f.parent)) { if (!kids.has(f.parent)) kids.set(f.parent, []); kids.get(f.parent).push(f); }
    const item = f => {
      const name = String(f.name || f.path).split('/').pop();
      const pin = { label: name + words(f), type: 'radio', checked: pinned === f.path, click: () => send({ type: 'video-folder', path: f.path }) };
      const under = kids.get(f.path);
      return under?.length ? { label: name + words(f), submenu: [{ ...pin, label: 'All of ' + name + words(f) }, { type: 'separator' }, ...under.map(item)] } : pin;
    };
    const reader = playback?.foldersReader;
    return [
      { label: playback?.pin ? ('Every folder (clear: ' + playback.pin.name + ', ' + playback.pin.minutes_left + ' min left)') : 'Every folder (no pin)', type: 'radio', checked: !playback?.pin, click: () => send({ type: 'video-folder', clear: true }) },
      ...(reader?.busy && reader.say ? [{ label: reader.say, enabled: false }] : []),
      { type: 'separator' },
      ...(!folders.length ? [{ label: playback?.foldersLoading ? 'Reading the folders - open the menu again in a moment' : 'The station has not listed its folders yet - open the menu again', enabled: false }] : []),
      ...folders.filter(f => !f.parent || !known.has(f.parent)).slice(0, 400).map(item)
    ];
  }
  function menu(playback = {}) {
'''
WIN_VIDEO_OLD = r'''      { label: 'Video', submenu: [
        { label: playback?.pin ? ('Every folder (clear: ' + playback.pin.name + ', ' + playback.pin.minutes_left + ' min left)') : 'Every folder (no pin)', type: 'radio', checked: !playback?.pin, click: () => getWindow()?.webContents.send('pip:action', { type: 'video-folder', clear: true }) },
        { type: 'separator' },
        ...(!(Array.isArray(playback?.folders) && playback.folders.length) ? [{ label: playback?.foldersLoading ? 'Reading the SFX catalog<BS>u2019s folders - open the menu again in a moment' : 'The station has not listed its folders yet - open the menu again', enabled: false }] : []),
        ...(Array.isArray(playback?.folders) ? playback.folders : []).filter(f => f && typeof f.path === 'string').slice(0, 300)
          .map(f => ({ label: (f.name || f.path) + '  (' + (f.video || 0) + ' video, ' + (f.audio || 0) + ' audio)', type: 'radio', checked: !!playback?.pin && playback.pin.path === f.path,
            click: () => getWindow()?.webContents.send('pip:action', { type: 'video-folder', path: f.path }) }))
      ] },
'''.replace("<BS>", BS)
WIN_VIDEO_NEW = r'''      { label: 'Video', submenu: videoFolderMenu(playback, action => getWindow()?.webContents.send('pip:action', action)) },   /* [video-folders-live] */
'''
WINDOW = [
    ("the folder tree builder", WIN_FN_OLD, WIN_FN_NEW, "function videoFolderMenu(playback, send) {", 1),
    ("the Video submenu uses it", WIN_VIDEO_OLD, WIN_VIDEO_NEW, "submenu: videoFolderMenu(playback,", 1),
]

# --------------------------------------------------------------------------- pine-pip.js (both copies)
PIP_OPEN_OLD = r'''      if (!foldersCache.folders.length) await Promise.race([refreshFolders(), new Promise(resolve => setTimeout(resolve, 2500))]);
      const opening = api().pipMenu({...playbackCache,favorites,folders:foldersCache.folders,pin:foldersCache.pin,foldersLoading:!foldersCache.folders.length&&!!foldersPending});
'''
PIP_OPEN_NEW = r'''      /* [video-folders-live] every open reads the folders again (and the station looks for new ones) */
      await Promise.race([refreshFolders(true), new Promise(resolve => setTimeout(resolve, foldersCache.folders.length ? 1200 : 2500))]);
      const opening = api().pipMenu({...playbackCache,favorites,folders:foldersCache.folders,pin:foldersCache.pin,foldersReader:foldersCache.reader,foldersLoading:!foldersCache.folders.length&&!!foldersPending});
'''
PIP_FETCH_OLD = r'''    foldersPending = Promise.resolve().then(() => api().get('/api/sfx/folders')).then(got => {
      const rows = Array.isArray(got?.folders) ? got.folders : [];
      foldersCache = { folders: rows.map(f => ({ path: String(f.path || ''), name: String(f.name || f.path || ''), video: Number(f.video) || 0, audio: Number(f.audio) || 0 })).sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base', numeric: true })), pin: got?.pin || null };
'''
PIP_FETCH_NEW = r'''    foldersPending = Promise.resolve().then(() => api().get('/api/sfx/folders' + (force ? '?fresh=1' : ''))).then(got => {   /* [video-folders-live] */
      const rows = Array.isArray(got?.folders) ? got.folders : [];
      foldersCache = { folders: rows.map(f => ({ path: String(f.path || ''), name: String(f.name || f.path || ''), video: Number(f.video) || 0, audio: Number(f.audio) || 0,
        parent: f.parent ? String(f.parent) : '', unread: !!f.unread, files: Number(f.files) || 0 })).sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base', numeric: true })), pin: got?.pin || null, reader: got?.reader || null };
'''
PIPJS = [
    ("every open reads the folders", PIP_OPEN_OLD, PIP_OPEN_NEW, "foldersReader:foldersCache.reader", 1),
    ("fresh fetch with the tree fields", PIP_FETCH_OLD, PIP_FETCH_NEW, "'/api/sfx/folders' + (force ? '?fresh=1' : '')", 1),
]

EDITS = {
    "app.py": APP,
    "desktop/pip-window.cjs": WINDOW,
    "desktop/renderer/pine-pip.js": PIPJS,
    "app/src/main/assets/pine-views/pine-pip.js": PIPJS,
}


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        if not path.exists():
            print("%-46s (not in this tree - skipped)" % name[-46:])
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, probe, count in edits:
            forms = [(old, new, probe)]
            if mode == "mixed":
                forms.append((old.replace("\n", "\r\n"), new.replace("\n", "\r\n"), probe.replace("\n", "\r\n")))
            state = ""
            for old_, new_, probe_ in forms:
                have = text.count(probe_)
                if have == count:
                    state = "applied"
                    break
                if not have and text.count(old_) == count:
                    text = text.replace(old_, new_)
                    assert text.count(probe_) == count, (name, label, "probe after the edit")
                    state, changed = "ready", True
                    break
            if not state:
                state = "missing (anchor found %d, probe %d)" % (text.count(old), text.count(probe))
            print("%-46s %-40s %s" % (name[-46:], label[:40], state))
            if state == "ready":
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, bom, mode, changed))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, bom, mode, changed in plans:
        if not changed:
            continue
        body = (text.replace("\n", "\r\n") if mode == "crlf" else text).encode("utf-8")
        tmp = path.with_name(path.name + ".vfl.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

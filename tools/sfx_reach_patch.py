#!/usr/bin/env python3
"""[sfx-reach] The SFX collection may be away: the station says so once, never stats a dead share,
plays the intermission (H3 renders, saved supercuts, gallery videos) on the endless set, and comes
back to the book on its own.

"When I plug it up to the spark, I want the database work to continue and for it to plug back up
seamlessly into the system ... In the intermission, I want it playing H3 / Supercuts if it finds it
has issues getting to the clips or accessing the SFX collection."      - the operator, 2026-10-06

The module sfx_reach.py (new, beside app.py) owns the one probe: a stat + listdir of
<SFX_ROOT>/samples_grabbed on its own daemon thread, 3 s, one in flight, memoised 20 s, logged once
each way. app.py reads the memo through sfx_reachable() at every place a decision about the share
is made - the inherent systems, not a wedge:

  app.py
    sfx_reach wiring        after SFX_LOCAL_ROOT: import, configure, sfx_reachable / sfx_reach_ok /
                            sfx_reach_bases / sfx_reach_hint / sfx_reach_blocks / sfx_reach_narrow /
                            sfx_reach_dress / sfx_reach_state / sfx_reach_stood_down
    sfx_folders             the share root is a base only while it answers (its own docstring:
                            "a dead SMB path must never take the show down with it")
    sfx_stamp               no stat on the share while away (0, and NOT memoised, so the first ask
                            after the share returns pays normally)
    sfx_by_id, sfx_db_path_of, sfx_deck_take
                            the is_file() on a share path waits for the share
    _sfx_db_pick_any, sfx_db_pick_rotation_row, sfx_db_pick_short_video
                            the book's draws add "AND path NOT LIKE '/samples/%'" while away:
                            every pick road narrows to the station's own rows (H3 clips, glued, edited)
    sting_due               the sting draw sets are narrowed the same way (the SFX guy's H3 clips
                            in sfx_ads ARE the shelf); nothing left -> stands down quietly
    _sfx_any_video          the walked video pool is narrowed too
    sfx_video_cycle         THE INTERMISSION: while away the set rings from sfx_intermission_shelf()
                            through the same door (page_picture_append), the same cooldown and
                            no-repeat, System 3's die sfx.intermission_pick (norepeat_roll_clip),
                            the same leveller and origin record; the SFX guy's requests wait in the
                            list (deferred, not dropped); the share runway rung ahead is withdrawn
                            on entry (the hourly rebuild's own move); back to the book on its own
    sfx_quarantine, _sfx_gone_from_book, sfx_quarantine_receipts, _sfx_reconcile_scan,
    sfx_db_index, sfx_vision_bite, sfx_study_clip
                            the keepers do not quarantine, forget or mark anything while away;
                            each stands down (counted, said once) and resumes on its own clock
    /sfx/{key}              a clip of the collection (or an id nobody knows) is answered 503 at once
                            while away - no stat, no walk; the station's own clips keep serving
    /api/sfx/reach          GET (fresh=1 forces a probe off the loop): the state, the say line, the
                            intermission's counters
    /api/sfx/video/mode     GET carries "reach" and leads its say line with the intermission
    /api/sfx/db, /api/sfx/doctor
                            carry "reach"; the doctor's verdict names the intermission first and
                            never stats a dead share for its share facts
  sfx_library.py            dress() does not look for gone files while the share is away
  sfx_vision_idle.py        the idle vision keeper rests while the share is away

Usage:  sfx_reach_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        sfx_reach_patch.py --apply [ROOT]
ROOT defaults to the repo root (the parent of tools/). The files are rewritten atomically with their
own line endings (app.py is CRLF) and BOM kept. ASCII only.
"""
from __future__ import annotations

import sys
from pathlib import Path

# ----------------------------------------------------------------------------- app.py

WIRING_OLD = '''SFX_LOCAL_ROOT = data_path("samples")
'''
WIRING_NEW = '''SFX_LOCAL_ROOT = data_path("samples")

# --- [sfx-reach] IS THE COLLECTION THERE? ---------------------------------------
# "When I plug it up to the spark, I want the database work to continue and for
#  it to plug back up seamlessly into the system ... In the intermission, I want
#  it playing H3 / Supercuts if it finds it has issues getting to the clips or
#  accessing the SFX collection."                     (operator, 2026-10-06)
#
# sfx_reach.py asks the one question - stat + listdir of SFX_ROOT/samples_grabbed
# on a daemon thread, 3 s, one in flight, memoised 20 s, said once each way. The
# roads below read the memo and never stat a share that is away: the book's
# draws narrow to the station's own rows, the endless set plays the
# intermission shelf, the keepers stand down and resume on their own clocks.
import sfx_reach as _sfx_reach                                          # [sfx-reach]

_sfx_reach.configure(root=SFX_ROOT, log=lambda text: pipeline_log("air", text))
SFX_REACH_LIKE = str(SFX_ROOT).rstrip("/") + "/%"      # the book's rows of the collection


def sfx_reachable() -> bool:
    """The collection, as of the last probe (at most 20 s old; a stale memo
    starts the next probe on its own thread). Never blocks, never raises."""
    try:
        return _sfx_reach.reachable()
    except Exception:  # noqa: BLE001 - a broken probe must never stand the library down
        return True


def sfx_reach_under(path: Any) -> bool:
    """Is this path the collection's? A string test - never a stat."""
    return _sfx_reach.under(path)


def sfx_reach_ok(path: Any) -> bool:
    """May this path be stat-ed or read right now? The station's own roots
    always; the collection only while it answers."""
    return sfx_reachable() or not _sfx_reach.under(path)


def sfx_reach_bases() -> tuple:
    """The roots a folder name resolves against: the share only while it answers."""
    return (SFX_ROOT, SFX_LOCAL_ROOT) if sfx_reachable() else (SFX_LOCAL_ROOT,)


def sfx_reach_hint(sid: str) -> str | None:
    """The path a clip id stands for, from memory and the book only - no stat."""
    try:
        back = _SFX_ID_REVERSE.get(str(sid or ""))
        if back:
            return str(back)
    except Exception:  # noqa: BLE001
        pass
    try:
        con = sfx_db_reader()
        with _SFX_DB_LOCK:
            row = con.execute("SELECT path FROM clips WHERE sid = ? LIMIT 1", (str(sid or ""),)).fetchone()
        return str(row[0]) if row is not None else None
    except Exception:  # noqa: BLE001
        return None


def sfx_reach_blocks(sid: str) -> bool:
    """503 material: the collection is away and this id is one of its clips -
    or an id nobody knows, whose lookup would end in a walk of the share."""
    if sfx_reachable():
        return False
    hint = sfx_reach_hint(sid)
    return hint is None or _sfx_reach.under(hint)


def sfx_reach_narrow(pool: Any, names_pool: Any, fresh: Any) -> tuple:
    """The sting draw sets without the collection: the station's own clips
    (the SFX guy's H3 renders in sfx_ads, the glued and edited clips, the cuts)."""
    return ([p for p in (pool or []) if not _sfx_reach.under(p)],
            [n for n in (names_pool or []) if not _sfx_reach.under(n)],
            {n for n in (fresh or ()) if not _sfx_reach.under(n)})


def sfx_reach_stood_down(road: str) -> None:
    try:
        _sfx_reach.stood_down(road)
    except Exception:  # noqa: BLE001
        pass


def sfx_reach_state() -> dict[str, Any]:
    try:
        return _sfx_reach.state()
    except Exception:  # noqa: BLE001
        return {"reachable": True, "known": False}


def sfx_reach_dress(state: dict[str, Any]) -> dict[str, Any]:
    """A desk reading (/api/sfx/video/mode) carries the reach, and while the
    collection is away its say line leads with the intermission."""
    try:
        reach = sfx_reach_state()
        state["reach"] = reach
        state["intermission"] = globals().get("sfx_intermission_state", lambda: {})()
        if not reach.get("reachable", True):
            state["say"] = "%s - %s" % (_sfx_reach.say(), str(state.get("say") or ""))
    except Exception:  # noqa: BLE001
        pass
    return state
'''

BASES_OLD = '''        for base in (SFX_ROOT, SFX_LOCAL_ROOT):
'''
BASES_NEW = '''        for base in sfx_reach_bases():                 # [sfx-reach] the share only while it answers
'''

STAMP_OLD = '''    try:
        info = path.stat()
        stamp = int(info.st_mtime_ns) if (info.st_mode & 0o170000) == 0o100000 else 0
'''
STAMP_NEW = '''    if not sfx_reach_ok(path):
        # [sfx-reach] the share is away: 0 is the honest answer (see above) and
        # it is NOT remembered, so the first ask after the share returns pays
        return 0
    try:
        info = path.stat()
        stamp = int(info.st_mtime_ns) if (info.st_mode & 0o170000) == 0o100000 else 0
'''

BY_ID_OLD = '''            known = Path(back)
            if known.is_file():
                return known
'''
BY_ID_NEW = '''            known = Path(back)
            if sfx_reach_ok(known) and known.is_file():      # [sfx-reach] no stat on a dead share
                return known
'''

PATH_OF_OLD = '''        found = Path(str(row[0]))
        return found if found.is_file() else None
'''
PATH_OF_NEW = '''        found = Path(str(row[0]))
        if not sfx_reach_ok(found):
            return None                      # [sfx-reach] the share is away: not a stat, not a verdict
        return found if found.is_file() else None
'''

DECK_OLD = '''    if got is not None and got.is_file():
        return got
    return None
'''
DECK_NEW = '''    if got is not None and sfx_reach_ok(got) and got.is_file():   # [sfx-reach]
        return got
    return None
'''

PICK_ANY_OLD = '''            where = "playable = 1 AND video = ?"
            args: tuple = (want,)
'''
PICK_ANY_NEW = '''            where = "playable = 1 AND video = ?"
            args: tuple = (want,)
            if not sfx_reachable():          # [sfx-reach] the station's own rows while the share is away
                where += " AND path NOT LIKE ?"
                args = args + (SFX_REACH_LIKE,)
'''

ROTATION_OLD = '''                where = "playable = 1 AND video = ? AND deck_cycle < ?"
                args: tuple[Any, ...] = (want, cycle)
'''
ROTATION_NEW = '''                where = "playable = 1 AND video = ? AND deck_cycle < ?"
                args: tuple[Any, ...] = (want, cycle)
                if not sfx_reachable():      # [sfx-reach] the station's own rows while the share is away
                    where += " AND path NOT LIKE ?"
                    args += (SFX_REACH_LIKE,)
'''

SHORT_OLD = '''        where = "playable = 1 AND video = 1 AND seconds BETWEEN 0.5 AND ? AND deck_cycle < ?"
        args: tuple[Any, ...] = (ceiling, sfx_video_rotation_cycle())
'''
SHORT_NEW = '''        where = "playable = 1 AND video = 1 AND seconds BETWEEN 0.5 AND ? AND deck_cycle < ?"
        args: tuple[Any, ...] = (ceiling, sfx_video_rotation_cycle())
        if not sfx_reachable():              # [sfx-reach] the station's own rows while the share is away
            where += " AND path NOT LIKE ?"
            args += (SFX_REACH_LIKE,)
'''

STING_OLD = '''    pool, names_pool, fresh = _sting_draw_sets()
    if not pool:
        return None
'''
STING_NEW = '''    pool, names_pool, fresh = _sting_draw_sets()
    if not pool:
        return None
    if not sfx_reachable():
        # [sfx-reach] THE STINGS DRAW FROM THE SAME SHELF OR STAND DOWN. The walked
        # pool still lists the collection for the length of its memo; while the
        # share is away the draw is the station's own clips - the SFX guy's H3
        # renders in sfx_ads, the glued and edited clips, the cuts - and when
        # none is left he is quiet rather than a 503 on the tube.
        pool, names_pool, fresh = sfx_reach_narrow(pool, names_pool, fresh)
        if not pool:
            sfx_reach_stood_down("sting")
            return None
'''

ANY_VIDEO_OLD = '''    pool = [path for path in _sfx_video_pool()
            if not sfx_video_on_cooldown(sfx_id(path))]
'''
ANY_VIDEO_NEW = '''    pool = [path for path in _sfx_video_pool()
            if sfx_reach_ok(path) and not sfx_video_on_cooldown(sfx_id(path))]   # [sfx-reach]
'''

CYCLE_DEF_OLD = '''async def sfx_video_cycle() -> None:
    """Keep the set's queue topped up for as long as the mode is on."""
'''
CYCLE_DEF_NEW = '''# --- [sfx-reach] THE INTERMISSION ------------------------------------------------
# "In the intermission, I want it playing H3 / Supercuts if it finds it has
#  issues getting to the clips or accessing the SFX collection."
#
# While the collection is away the endless set rings from a SHELF that does not
# live on the share - H3 renders and everything else ComfyUI rendered on this
# box (COMFY_OUTPUT: the hourly videos, the SFX guy's H3 clips in sfx_ads), the
# saved supercuts (sfx_ads/supercut-*.mp4) and the gallery's reused supercut
# videos (PRODUCED_ADS_DIR) - through the SAME door (page_picture_append), the
# same cooldown and no-repeat notes, the same leveller and origin record. The
# pick is System 3's (sfx.intermission_pick, through norepeat_roll_clip: the
# day's heard clips struck first, then the die, through the sting ring). The
# policy, in order: a clip not heard inside the day; else one off its hour
# cooldown; else any - the intermission never goes dark while the shelf holds
# a file. The SFX guy's requests stay in their list until the share is back.
SFX_INTERMISSION_MEMO_S = 120.0
SFX_INTERMISSION_MOST = 600
SFX_INTERMISSION_MIN_BYTES = 10000          # a torn render is not a picture
SFX_INTERMISSION_WHY = "intermission: the SFX collection is unreachable"
_SFX_INTERMISSION: dict[str, Any] = {"at": 0.0, "shelf": [], "rung": 0, "last": "",
                                      "how": "", "why": "", "on": False, "entered": 0.0,
                                      "entries": 0}


def _sfx_intermission_kind(path: Path) -> str:
    low = path.name.lower()
    if low.startswith("supercut-") or path.parent.name == "supercuts":
        return "supercut"
    if path.parent == SFX_ADS_DIR or "h3" in low:
        return "h3"
    return "gallery"


def sfx_intermission_shelf(fresh: bool = False) -> list[dict[str, Any]]:
    """The station's own pictures, newest first. Blocking (a stat per file,
    local disk): a worker's. Memoised SFX_INTERMISSION_MEMO_S."""
    now = time.time()
    if (not fresh and _SFX_INTERMISSION.get("shelf")
            and now - float(_SFX_INTERMISSION.get("at") or 0) < SFX_INTERMISSION_MEMO_S):
        return list(_SFX_INTERMISSION["shelf"])
    found: list[dict[str, Any]] = []
    for base in (COMFY_OUTPUT, PRODUCED_ADS_DIR):
        try:
            for dirpath, dirnames, filenames in os.walk(str(base)):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for name in filenames:
                    if not name.lower().endswith((".mp4", ".webm", ".m4v", ".mov")):
                        continue
                    p = Path(dirpath) / name
                    try:
                        st = p.stat()
                    except OSError:
                        continue
                    if st.st_size < SFX_INTERMISSION_MIN_BYTES:
                        continue
                    found.append({"path": p, "kind": _sfx_intermission_kind(p),
                                  "mtime": float(st.st_mtime), "bytes": int(st.st_size)})
        except OSError:
            continue
    found.sort(key=lambda r: -float(r["mtime"]))
    shelf = found[:SFX_INTERMISSION_MOST]
    _SFX_INTERMISSION.update({"at": now, "shelf": shelf})
    return list(shelf)


def sfx_intermission_pick(shelf: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The policy, explicit: fresh (not heard inside the day, System 3's die
    through the sting ring), else rested (off the hour cooldown), else any."""
    if not shelf:
        return None
    by_path = {str(r["path"]): r for r in shelf}
    paths = [Path(str(r["path"])) for r in shelf]
    question = "which of the station's own pictures the intermission shows (H3 renders, supercuts, gallery videos)"
    pick, how = None, "fresh"
    try:
        pick = norepeat_roll_clip(paths, "sfx.intermission_pick", question, road="intermission")
        if pick is not None and sfx_video_on_cooldown(sfx_id(pick)):
            pick = None
    except Exception:  # noqa: BLE001 - a die that fails is not a dark tube
        pick = None
    if pick is None:
        try:
            rested = [p for p in paths if not sfx_video_on_cooldown(sfx_id(p))]
        except Exception:  # noqa: BLE001
            rested = []
        if rested:
            pick, how = s3_choice("sfx.intermission_pick", rested, question, tabled=False), "rested"
    if pick is None:
        pick, how = s3_choice("sfx.intermission_pick", paths, question, tabled=False), "any"
    row = dict(by_path.get(str(pick)) or {"path": Path(str(pick)), "kind": _sfx_intermission_kind(Path(str(pick)))})
    row["how"] = how
    return row


def sfx_intermission_enter() -> None:
    """The set goes over to the shelf. The collection's clips rung ahead are
    withdrawn from the ring (the hourly rebuild's own move: future endless
    rows go, the epoch turns) so the tube is not dark for a runway it cannot
    fetch; the SFX guy's requests stay in their list for when the share is back."""
    now_ms = int(time.time() * 1000)
    ring = _RADIO.setdefault("voice_clips", [])
    ring[:] = [row for row in ring if not (
        isinstance(row, dict) and row.get("endless")
        and int(row.get("broadcast_ms") or row.get("ts") or 0) >= now_ms)]
    _SFX_CYCLE["shuffle_epoch"] = int(_SFX_CYCLE.get("shuffle_epoch") or 0) + 1
    _SFX_INTERMISSION.update({"on": True, "entered": time.time(),
                              "entries": int(_SFX_INTERMISSION.get("entries") or 0) + 1})
    waiting = len(_SFX_CYCLE.get("requests") or [])
    for _ in range(waiting):
        _sfx_reach.defer()
    pipeline_log("air", "the endless set is in intermission: the station's own pictures (H3 renders, "
                        "supercuts, gallery videos) until the collection is back%s"
                        % ((" - %d of the SFX guy's requests wait" % waiting) if waiting else ""))


def sfx_intermission_leave() -> None:
    _SFX_INTERMISSION["on"] = False
    pipeline_log("air", "the endless set is back on the book - the intermission rang %d clip(s)"
                 % int(_SFX_INTERMISSION.get("rung") or 0))


def sfx_intermission_state() -> dict[str, Any]:
    return {"on": bool(_SFX_INTERMISSION.get("on")), "rung": int(_SFX_INTERMISSION.get("rung") or 0),
            "last": str(_SFX_INTERMISSION.get("last") or ""), "how": str(_SFX_INTERMISSION.get("how") or ""),
            "why": str(_SFX_INTERMISSION.get("why") or ""), "entered": float(_SFX_INTERMISSION.get("entered") or 0),
            "entries": int(_SFX_INTERMISSION.get("entries") or 0),
            "shelf": len(_SFX_INTERMISSION.get("shelf") or []),
            "shelf_at": float(_SFX_INTERMISSION.get("at") or 0),
            "deferred_requests": len(_SFX_CYCLE.get("requests") or []),
            "policy": "fresh (not heard inside the day, System 3's die sfx.intermission_pick), "
                      "else rested (off the hour cooldown), else any - never dark while the shelf has a file"}


async def sfx_intermission_turn(now: float, last_end: float) -> dict[str, Any] | None:
    """One clip of the intermission onto the set's ring: the same door, the
    same notes, the same leveller - only the shelf differs. The plan entry,
    or None when nothing has been rendered on this box."""
    shelf = await asyncio.to_thread(sfx_intermission_shelf)
    row = (await asyncio.to_thread(sfx_intermission_pick, shelf)) if shelf else None
    if not row:
        _SFX_INTERMISSION["why"] = "the shelf is empty - nothing rendered on this box yet"
        return None
    pick = Path(str(row["path"]))
    real = round(float((await asyncio.to_thread(sfx_seconds, pick)) or 0), 2)
    seconds = sfx_cycle_slot(real)
    room = max(0.0, last_end - time.time()) - 1.0
    _lv_path = pick
    try:
        _lv_path, _lv_how = await sfx_level_for_air(pick, max(1.5, min(SFX_LEVEL_WAIT, room)))
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        _lv_path = pick
    key = sfx_id(pick)                    # and the way back: /sfx/<key> serves this file
    start = max(now, last_end + SFX_CYCLE_GAP)
    why = "%s - %s" % (SFX_INTERMISSION_WHY, {"h3": "an H3 render", "supercut": "a saved supercut",
                                             "gallery": "a gallery video"}.get(str(row.get("kind")), "a picture of the station's own"))
    page_picture_append({
        "url": "/sfx/%s?t=%s" % (key, media_sign(key)),
        "sting": pick.stem, "id": key, "seconds": seconds, "length": real,
        "why": why, "intermission": True, "endless": True},
        at_ms=int(start * 1000))
    _set_air = _SFX_CYCLE.setdefault("air", [])
    _set_air.append({"key": "set|%s|%d" % (key, int(start * 1000)), "air_at": start,
                     "slot": seconds, "length": real, "path": str(_lv_path)})
    del _set_air[:-12]
    sfx_video_note_played(key, pick.parent.name)
    _origin_wall_note(pick, key, seconds, start, why)
    _SFX_INTERMISSION.update({"rung": int(_SFX_INTERMISSION.get("rung") or 0) + 1, "last": pick.name,
                              "how": str(row.get("how") or ""), "why": ""})
    return {"sting": pick.stem, "start": start, "end": start + seconds, "id": key, "intermission": True}


async def sfx_video_cycle() -> None:
    """Keep the set's queue topped up for as long as the mode is on."""
'''

CYCLE_BRANCH_OLD = '''                await asyncio.sleep(1.0)
                continue
            # #1417: the SFX guy's own clip first, if he has handed one in.
'''
CYCLE_BRANCH_NEW = '''                await asyncio.sleep(1.0)
                continue
            # [sfx-reach] THE INTERMISSION: while the collection is away the set
            # rings the station's own pictures (see sfx_intermission_turn) and the
            # SFX guy's requests wait in their list. The book returns on its own.
            if not sfx_reachable():
                if not _SFX_INTERMISSION.get("on"):
                    sfx_intermission_enter()
                    plan = []
                    plan_epoch = int(_SFX_CYCLE.get("shuffle_epoch") or 0)
                    last_end = now
                _turn = await sfx_intermission_turn(now, last_end)
                if _turn is None:
                    _SFX_CYCLE.update({"why": SFX_INTERMISSION_WHY + " and the shelf is empty",
                                       "queued": len(plan)})
                    await asyncio.sleep(10.0)
                    continue
                plan.append(_turn)
                _SFX_CYCLE.update({"at": now, "until": plan[-1]["end"],
                                   "rung": int(_SFX_CYCLE.get("rung") or 0) + 1,
                                   "clip": plan[0]["sting"], "queued": len(plan),
                                   "why": SFX_INTERMISSION_WHY})
                continue
            if _SFX_INTERMISSION.get("on"):
                sfx_intermission_leave()
            # #1417: the SFX guy's own clip first, if he has handed one in.
'''

MODE_ROUTE_OLD = '''    return await asyncio.to_thread(sfx_video_mode_state)
'''
MODE_ROUTE_NEW = '''    return sfx_reach_dress(await asyncio.to_thread(sfx_video_mode_state))   # [sfx-reach]
'''

SFX_ROUTE_OLD = '''    path = await asyncio.to_thread(sfx_by_id, sfx_key)
    if path is None:
        # [sfx-gone] sfx_by_id skips a book row whose file is gone, so the
'''
SFX_ROUTE_NEW = '''    # [sfx-reach] NEVER A STAT ON A DEAD SHARE. A clip of the collection - or an
    # id nobody knows, whose lookup ends in a walk of it - is answered 503 at
    # once while the collection is away; the station's own clips keep serving.
    # The surface asks for another on a load error, and the receipt says why.
    if await asyncio.to_thread(sfx_reach_blocks, sfx_key):
        sfx_reach_stood_down("sfx-route")
        return Response(content=_sfx_reach.say().encode("utf-8", "replace"), status_code=503,
                        media_type="text/plain",
                        headers={"Retry-After": "20", "Cache-Control": "no-store",
                                 "X-Pine-Why": "the SFX collection is unreachable"})
    path = await asyncio.to_thread(sfx_by_id, sfx_key)
    if path is None:
        # [sfx-gone] sfx_by_id skips a book row whose file is gone, so the
'''

QUARANTINE_OLD = '''    except Exception:  # noqa: BLE001
        return False
    _sfx_quarantine_load()
    folder, folder_gone = "", False
'''
QUARANTINE_NEW = '''    except Exception:  # noqa: BLE001
        return False
    if not sfx_reach_ok(path):
        # [sfx-reach] nothing is quarantined while the collection is away: a
        # 503 on the tube is not a gone file. The keeper resumes with the share.
        sfx_reach_stood_down("quarantine")
        return False
    _sfx_quarantine_load()
    folder, folder_gone = "", False
'''

GONE_OLD = '''    from sfx_library import file_state
    if file_state(row[0], (SFX_ROOT, SFX_LOCAL_ROOT)) != "gone":
'''
GONE_NEW = '''    if not sfx_reach_ok(row[0]):
        sfx_reach_stood_down("sfx-gone")     # [sfx-reach] no verdict on a share that is away
        return False
    from sfx_library import file_state
    if file_state(row[0], (SFX_ROOT, SFX_LOCAL_ROOT)) != "gone":
'''

RECEIPTS_OLD = '''        path = sfx_by_id(sid)
        who = str((row or {}).get("player") or player or "a player")
'''
RECEIPTS_NEW = '''        if sfx_reach_blocks(sid):
            sfx_reach_stood_down("receipts")  # [sfx-reach] a 503 is not an undecodable clip
            continue
        path = sfx_by_id(sid)
        who = str((row or {}).get("player") or player or "a player")
'''

RECONCILE_OLD = '''    out: dict[str, Any] = {"checked": 0, "gone": [], "arrived": [],
                           "moved": [], "folders_gone": []}
'''
RECONCILE_NEW = '''    out: dict[str, Any] = {"checked": 0, "gone": [], "arrived": [],
                           "moved": [], "folders_gone": []}
    if not sfx_reachable():
        # [sfx-reach] a sweep over a share that is away would call every row
        # gone. It waits; the operator asks again when the share is back.
        sfx_reach_stood_down("reconcile")
        out["why"] = "the SFX collection is unreachable - nothing checked, nothing called gone"
        return out
'''

INDEX_OLD = '''            _SFX_DB_SCAN.update({"folder": folder.name, "done": ix})
            if limit_seconds and time.time() - started > limit_seconds:
'''
INDEX_NEW = '''            _SFX_DB_SCAN.update({"folder": folder.name, "done": ix})
            if not sfx_reach_ok(folder):
                # [sfx-reach] the walk skips the collection while it is away
                # (nothing is deleted by a walk; the rows stay as they were)
                sfx_reach_stood_down("walk")
                _SFX_DB_SCAN["why"] = "the SFX collection is unreachable - its folders wait for the next walk"
                continue
            if limit_seconds and time.time() - started > limit_seconds:
'''

VISION_OLD = '''    want = int(most or SFX_VISION_BITE)
'''
VISION_NEW = '''    if not sfx_reachable():
        sfx_reach_stood_down("vision")      # [sfx-reach] the frames live on the share
        _SFX_VISION["why"] = "the SFX collection is unreachable - the vision pass waits"
        return dict(_SFX_VISION)
    want = int(most or SFX_VISION_BITE)
'''

STUDY_OLD = '''    out: dict[str, Any] = {"path": str(pick), "heard": False, "seen": False}
'''
STUDY_NEW = '''    out: dict[str, Any] = {"path": str(pick), "heard": False, "seen": False}
    if not sfx_reach_ok(pick):
        sfx_reach_stood_down("study")       # [sfx-reach] the clip is on a share that is away
        out["why"] = "the SFX collection is unreachable"
        return out
'''

DB_ROUTE_OLD = '''    return {"counts": counts, "scan": scan,
            "path": str(SFX_DB_PATH),
'''
DB_ROUTE_NEW = '''    return {"counts": counts, "scan": scan,
            "path": str(SFX_DB_PATH),
            "reach": sfx_reach_state(),                               # [sfx-reach]
'''

REBUILD_ROUTE_OLD = '''@app.post("/api/sfx/db/rebuild")
async def sfx_db_rebuild_api(
'''
REBUILD_ROUTE_NEW = '''@app.get("/api/sfx/reach")
async def sfx_reach_api(
    fresh: int = 0,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[sfx-reach] Is the SFX collection there? The memo's answer; `fresh=1`
    runs a probe now (off the loop, bounded by the probe's own timeout)."""
    require_read_auth(authorization)
    if fresh:
        await asyncio.to_thread(_sfx_reach.probe, True)
    got = sfx_reach_state()
    got["intermission"] = sfx_intermission_state()
    got["policy"] = ("one stat + listdir of %s/samples_grabbed on its own thread, %.0f s, one in flight, "
                     "memoised %.0f s; late or failed = unreachable; said once each way"
                     % (SFX_ROOT, float(got.get("timeout_s") or 0), float(got.get("memo_s") or 0)))
    return got


@app.post("/api/sfx/db/rebuild")
async def sfx_db_rebuild_api(
'''

DOCTOR_SHARE_OLD = '''    share = _sfx_share_facts()
'''
DOCTOR_SHARE_NEW = '''    share = (_sfx_share_facts() if sfx_reachable()                      # [sfx-reach] no stat on a dead share
             else {"root": str(SFX_ROOT), "present": None, "unreachable": True, "reach": sfx_reach_state()})
'''

DOCTOR_BOOK_OLD = '''        "book": sfx_db_counts(),
'''
DOCTOR_BOOK_NEW = '''        "book": sfx_db_counts(),
        "reach": sfx_reach_state(),                                         # [sfx-reach]
'''

DOCTOR_VERDICT_OLD = '''    if out["book"].get("video_playable"):
        out["verdict"] = ("the clip book holds %d video clip(s) - taps are instant"
'''
DOCTOR_VERDICT_NEW = '''    if not sfx_reachable():                                                 # [sfx-reach]
        out["verdict"] = _sfx_reach.say()
        out["steps"] = [
            "the clip book is kept as it is - nothing is forgotten, quarantined or re-walked while the collection is away",
            "the endless set rings the station's own pictures (H3 renders, saved supercuts, gallery videos); "
            "the stings draw from the SFX guy's own clips or stand down",
            "on the host: mount | grep samples ; findmnt /home/ehm_eckx/samples ; ls /home/ehm_eckx/samples/samples_grabbed | head",
            "a mount made under the bind after the container started is not seen inside it: "
            "docker compose up -d --force-recreate spark-agent (see docs/sfx-migration.md)",
            "the set returns to the book on its own when the share answers; GET /api/sfx/reach?fresh=1 probes now"]
        out["cure"] = "mount"
        return out
    if out["book"].get("video_playable"):
        out["verdict"] = ("the clip book holds %d video clip(s) - taps are instant"
'''

# ------------------------------------------------------------------------ sfx_library.py

LIBRARY_OLD = '''        book = book_rows([r["sid"] for r in rows])
        for r in rows:
'''
LIBRARY_NEW = '''        book = book_rows([r["sid"] for r in rows])
        reach = ns("sfx_reachable")
        if look and callable(reach) and not reach():
            look = False                    # [sfx-reach] no look for gone files on a share that is away
        for r in rows:
'''

# --------------------------------------------------------------------- sfx_vision_idle.py

IDLE_OLD = '''        gate = ns("_OLLAMA_GATE")
        if gate is not None and gate.locked():
            return "the model is busy"
        return ""
'''
IDLE_NEW = '''        gate = ns("_OLLAMA_GATE")
        if gate is not None and gate.locked():
            return "the model is busy"
        reach = ns("sfx_reachable")
        if callable(reach) and not reach():
            return "the SFX collection is unreachable"    # [sfx-reach] the frames live on the share
        return ""
'''

EDITS = {
    "app.py": [
        ("sfx_reach wiring after SFX_LOCAL_ROOT", WIRING_OLD, WIRING_NEW, 1),
        ("sfx_folders: the share root is a base only while it answers (x2)", BASES_OLD, BASES_NEW, 2),
        ("sfx_stamp: no stat on the share while away, nothing memoised", STAMP_OLD, STAMP_NEW, 1),
        ("sfx_by_id: the reverse map's is_file waits for the share", BY_ID_OLD, BY_ID_NEW, 1),
        ("sfx_db_path_of: no is_file on the share while away", PATH_OF_OLD, PATH_OF_NEW, 1),
        ("sfx_deck_take: no is_file on the share while away", DECK_OLD, DECK_NEW, 1),
        ("_sfx_db_pick_any: the book draw narrows to the station's own rows", PICK_ANY_OLD, PICK_ANY_NEW, 1),
        ("sfx_db_pick_rotation_row: the deck draw narrows too", ROTATION_OLD, ROTATION_NEW, 1),
        ("sfx_db_pick_short_video: the cadence draw narrows too", SHORT_OLD, SHORT_NEW, 1),
        ("sting_due: the sting sets narrow to the shelf or stand down", STING_OLD, STING_NEW, 1),
        ("_sfx_any_video: the walked video pool narrows", ANY_VIDEO_OLD, ANY_VIDEO_NEW, 1),
        ("the intermission shelf, pick, enter/leave, state and turn", CYCLE_DEF_OLD, CYCLE_DEF_NEW, 1),
        ("sfx_video_cycle: the intermission branch", CYCLE_BRANCH_OLD, CYCLE_BRANCH_NEW, 1),
        ("/api/sfx/video/mode GET carries the reach and the intermission", MODE_ROUTE_OLD, MODE_ROUTE_NEW, 1),
        ("/sfx/{key}: 503 at once for the collection's clips while away", SFX_ROUTE_OLD, SFX_ROUTE_NEW, 1),
        ("sfx_quarantine: nothing quarantined while away", QUARANTINE_OLD, QUARANTINE_NEW, 1),
        ("_sfx_gone_from_book: no verdict while away", GONE_OLD, GONE_NEW, 1),
        ("sfx_quarantine_receipts: a 503 is not an undecodable clip", RECEIPTS_OLD, RECEIPTS_NEW, 1),
        ("_sfx_reconcile_scan: the sweep waits", RECONCILE_OLD, RECONCILE_NEW, 1),
        ("sfx_db_index: the walk skips the collection while away", INDEX_OLD, INDEX_NEW, 1),
        ("sfx_vision_bite: the vision pass waits", VISION_OLD, VISION_NEW, 1),
        ("sfx_study_clip: the study waits", STUDY_OLD, STUDY_NEW, 1),
        ("/api/sfx/db carries the reach", DB_ROUTE_OLD, DB_ROUTE_NEW, 1),
        ("/api/sfx/reach route", REBUILD_ROUTE_OLD, REBUILD_ROUTE_NEW, 1),
        ("doctor: no share facts off a dead share", DOCTOR_SHARE_OLD, DOCTOR_SHARE_NEW, 1),
        ("doctor: carries the reach", DOCTOR_BOOK_OLD, DOCTOR_BOOK_NEW, 1),
        ("doctor: the verdict names the intermission first", DOCTOR_VERDICT_OLD, DOCTOR_VERDICT_NEW, 1),
    ],
    "sfx_library.py": [
        ("dress(): no look for gone files while away", LIBRARY_OLD, LIBRARY_NEW, 1),
    ],
    "sfx_vision_idle.py": [
        ("the idle vision keeper rests while away", IDLE_OLD, IDLE_NEW, 1),
    ],
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
            print("%-46s MISSING FILE" % name)
            missing = True
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, want in edits:
            if text.count(new) >= want:
                print("%-78s applied" % label[:78])
                continue
            n = text.count(old)
            if n == want:
                print("%-78s ready" % label[:78])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-78s MISSING (anchor count %d, wanted %d)" % (label[:78], n, want))
                missing = True
        if changed:
            plans.append((path, text, mode, bom))
    if not (root / "sfx_reach.py").exists():
        # the module is a new file, not an anchor: a --check reads ready without it, an --apply refuses
        print("%-78s not beside app.py yet (copy it before --apply)" % "sfx_reach.py, the module")
        if argv[1] == "--apply":
            missing = True
    else:
        print("%-78s present" % "sfx_reach.py, the module")
    if missing:
        print("anchors missing - nothing applied")
        return 1
    if not ready:
        print("every edit reads applied")
        return 2
    if argv[1] == "--check":
        print("ready to apply")
        return 0
    for path, text, mode, bom in plans:
        out = text.replace("\n", "\r\n") if mode == "crlf" else text
        data = out.encode("utf-8")
        if bom:
            data = b"\xef\xbb\xbf" + data
        tmp = path.with_suffix(path.suffix + ".sfxreach.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

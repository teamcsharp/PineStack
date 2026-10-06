#!/usr/bin/env python3
"""[unseen-video] Endless video becomes UNSEEN video mode. 2026-10-06.

"The purpose of endless video is to allow the SFX guy to categorize clips that
he did not play previously or ever and to explore and internalize the data
from them ... I need endless video to become 'unseen video mode' where I see
only clips that have never gotten categorized as we calibrate the gain, gather
the tags, and internalize the data of the clip to be able to recall it when
pertinent."

Measured 2026-10-06: 227,872 playable video clips, 219,634 of them never
categorised (208,985 without a transcript, 218,932 without studied frames).

- The endless set's pick asks the book for an UNCATEGORISED clip first
  (said_at or seen_desc_at still empty) - the same rotation query with one
  more clause - and falls back to the ordinary deck only when none is left.
  The dj dial `sfx_video_unseen` (default on) is the switch.
- Every clip the set rings is studied as it plays: its words are transcribed
  (clip_speech, the listener's own road) and its frames looked at and
  described (the vision keeper's own look/write), so it is categorised by the
  time the next one starts; the gain was already levelled at the ring.
  sfx_match_kick after every tenth, so what he can hear changes.
- GET /api/sfx/video/mode says how deep the unseen pool is and what this
  session studied; the desk's menu calls the mode by its new name.

Usage:  unseen_video_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        unseen_video_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------- app.py
SIG_OLD = '''def sfx_db_pick_rotation_row(video: bool = True, _unrolled: bool = False,
                             _tried: tuple = ()) -> tuple[Path, float] | None:   # [s3-wall-folder:def]
'''
SIG_NEW = '''def sfx_db_pick_rotation_row(video: bool = True, _unrolled: bool = False,
                             _tried: tuple = (), unseen: bool = False) -> tuple[Path, float] | None:   # [s3-wall-folder:def] [unseen-video]
'''

WHERE_OLD = '''                where = "playable = 1 AND video = ? AND deck_cycle < ?"
                args: tuple[Any, ...] = (want, cycle)
'''
WHERE_NEW = '''                where = "playable = 1 AND video = ? AND deck_cycle < ?"
                args: tuple[Any, ...] = (want, cycle)
                if unseen:                                                # [unseen-video] never categorised
                    where += " AND (said_at IS NULL OR seen_desc_at IS NULL)"
'''

RETRY1_OLD = '''            if len(_tried) < 2:
                return sfx_db_pick_rotation_row(video, False, tuple(_tried) + (_fold,))
            return sfx_db_pick_rotation_row(video, True)
'''
RETRY1_NEW = '''            if len(_tried) < 2:
                return sfx_db_pick_rotation_row(video, False, tuple(_tried) + (_fold,), unseen=unseen)   # [unseen-video]
            return sfx_db_pick_rotation_row(video, True, unseen=unseen)
'''

ASYNC_OLD = '''async def sfx_db_pick_rotation_async(
        video: bool = True) -> tuple[Path, float] | None:
    """The generation-aware pick on the clip book's private worker."""
    try:
        return await asyncio.get_running_loop().run_in_executor(
            _SFX_DB_EXEC, sfx_db_pick_rotation_row, video)
'''
ASYNC_NEW = '''async def sfx_db_pick_rotation_async(
        video: bool = True, unseen: bool = False) -> tuple[Path, float] | None:   # [unseen-video]
    """The generation-aware pick on the clip book's private worker."""
    try:
        return await asyncio.get_running_loop().run_in_executor(
            _SFX_DB_EXEC, sfx_db_pick_rotation_row, video, False, (), unseen)
'''

FRESH_OLD = '''    del tries  # kept for callers/tests from the former rejection sampler
    got = await sfx_db_pick_rotation_async(True)
    if got is not None:
        return got
'''
FRESH_NEW = '''    del tries  # kept for callers/tests from the former rejection sampler
    if sfx_video_unseen_on():                                             # [unseen-video] the uncategorised first
        got = await sfx_db_pick_rotation_async(True, unseen=True)
        if got is not None:
            return got
    got = await sfx_db_pick_rotation_async(True)
    if got is not None:
        return got
'''

HELPERS_OLD = '''async def sfx_video_fresh_pick(tries: int = 40) -> Any:
'''
HELPERS_NEW = '''# --- [unseen-video] THE SET STUDIES WHAT IT SHOWS --------------------------------
# "I need endless video to become 'unseen video mode' where I see only clips that
# have never gotten categorized as we calibrate the gain, gather the tags, and
# internalize the data of the clip" (operator, 2026-10-06). The pick prefers a
# clip with no transcript or no studied frames; the ring studies it as it plays.
_SFX_UNSEEN: dict[str, Any] = {"studied": 0, "heard": 0, "seen": 0, "failed": 0, "at": 0.0,
                               "last": "", "pool": -1, "pool_at": 0.0, "busy": 0}
SFX_UNSEEN_STUDY_MOST = 2            # clips studied at once; the set rings faster than vision looks


def sfx_video_unseen_on() -> bool:
    try:
        return bool((dj_settings() or {}).get("sfx_video_unseen", True))
    except Exception:  # noqa: BLE001
        return True


def sfx_unseen_pool() -> int:
    """How many playable video clips are still uncategorised (30 s memo, reader)."""
    now = time.time()
    if now - float(_SFX_UNSEEN.get("pool_at") or 0) < 30.0 and int(_SFX_UNSEEN.get("pool") or -1) >= 0:
        return int(_SFX_UNSEEN["pool"])
    try:
        con = sfx_db_reader()
        n = int(con.execute("SELECT COUNT(*) FROM clips WHERE playable = 1 AND video = 1 "
                            "AND (said_at IS NULL OR seen_desc_at IS NULL)").fetchone()[0])
    except Exception:  # noqa: BLE001
        n = int(_SFX_UNSEEN.get("pool") or 0)
    _SFX_UNSEEN.update({"pool": n, "pool_at": now})
    return n


def sfx_unseen_state() -> dict[str, Any]:
    return {"on": sfx_video_unseen_on(), "pool": sfx_unseen_pool(),
            "studied": int(_SFX_UNSEEN.get("studied") or 0), "heard": int(_SFX_UNSEEN.get("heard") or 0),
            "seen": int(_SFX_UNSEEN.get("seen") or 0), "failed": int(_SFX_UNSEEN.get("failed") or 0),
            "last": str(_SFX_UNSEEN.get("last") or ""), "at": float(_SFX_UNSEEN.get("at") or 0),
            "say": ("unseen video: %d clip(s) still uncategorised; %d studied this session (%d heard, %d seen)"
                    % (sfx_unseen_pool(), int(_SFX_UNSEEN.get("studied") or 0),
                       int(_SFX_UNSEEN.get("heard") or 0), int(_SFX_UNSEEN.get("seen") or 0)))}


async def sfx_study_clip(pick: Any, seconds: float = 0.0) -> dict[str, Any]:
    """Categorise one clip the set just rang: transcribe its words if it has none,
    look at its frames if they were never studied. Each on its own road's worker;
    nothing here touches the event loop for long."""
    out: dict[str, Any] = {"path": str(pick), "heard": False, "seen": False}
    if int(_SFX_UNSEEN.get("busy") or 0) >= SFX_UNSEEN_STUDY_MOST:
        out["why"] = "the study room is full"
        return out
    _SFX_UNSEEN["busy"] = int(_SFX_UNSEEN.get("busy") or 0) + 1
    try:
        path = str(pick)
        try:
            row = await asyncio.to_thread(
                lambda: sfx_db_reader().execute(
                    "SELECT said_at, seen_desc_at, seen_desc, sid, seconds FROM clips WHERE path = ?", (path,)).fetchone())
        except Exception:  # noqa: BLE001
            row = None
        if row is None:
            out["why"] = "not in the book"
            return out
        said_at, seen_at, old_desc, sid, secs = row[0], row[1], row[2], row[3], float(row[4] or seconds or 0)
        if not said_at and clip_speech is not None:
            try:
                said = await asyncio.to_thread(clip_speech.transcribe_file, path)
            except Exception:  # noqa: BLE001
                said = ""
            try:
                def _write_said() -> None:
                    with _SFX_DB_LOCK:
                        sfx_db().execute("UPDATE clips SET said = ?, said_at = ? WHERE path = ?",
                                         (str(said or "")[:600], time.time(), path))
                        sfx_db().commit()
                await asyncio.to_thread(_write_said)
                out["heard"] = bool(said)
                if said:
                    _SFX_UNSEEN["heard"] = int(_SFX_UNSEEN.get("heard") or 0) + 1
            except Exception:  # noqa: BLE001
                _SFX_UNSEEN["failed"] = int(_SFX_UNSEEN.get("failed") or 0) + 1
        if not seen_at:
            look = globals().get("sfx_vision_look")
            write = globals().get("sfx_vision_write")
            if callable(look) and callable(write):
                try:
                    frames = await look(path, secs)
                    await asyncio.to_thread(write, path, frames, str(old_desc or ""))
                    out["seen"] = bool(frames)
                    if frames:
                        _SFX_UNSEEN["seen"] = int(_SFX_UNSEEN.get("seen") or 0) + 1
                except Exception:  # noqa: BLE001
                    _SFX_UNSEEN["failed"] = int(_SFX_UNSEEN.get("failed") or 0) + 1
        _SFX_UNSEEN["studied"] = int(_SFX_UNSEEN.get("studied") or 0) + 1
        _SFX_UNSEEN.update({"at": time.time(), "last": str(sid or Path(path).stem)[:80], "pool_at": 0.0})
        if _SFX_UNSEEN["studied"] % 10 == 0:
            try:
                sfx_match_kick()                                    # what he can hear has changed
            except Exception:  # noqa: BLE001
                pass
        return out
    finally:
        _SFX_UNSEEN["busy"] = max(0, int(_SFX_UNSEEN.get("busy") or 1) - 1)


async def sfx_video_fresh_pick(tries: int = 40) -> Any:
'''

RING_OLD = '''                at_ms=int(start * 1000))
            plan.append({"sting": pick.stem, "start": start,
'''
RING_NEW = '''                at_ms=int(start * 1000))
            if sfx_video_unseen_on():                                 # [unseen-video] studied as it plays
                fire_and_forget(sfx_study_clip(pick, seconds))
            plan.append({"sting": pick.stem, "start": start,
'''

STATE_OLD = '''    return {"on": sfx_video_mode_on(),
            "banking": bool(sfx_video_mode_on() and radio_paused()),
'''
STATE_NEW = '''    return {"on": sfx_video_mode_on(),
            "unseen": sfx_unseen_state(),                       # [unseen-video] the pool and the session's study
            "banking": bool(sfx_video_mode_on() and radio_paused()),
'''

# ---------------------------------------------------------------- sfx_vision_idle.py
VISION_OLD = '''    holder: dict[str, Any] = {}

    @app.on_event("startup")
    async def start_sfx_vision_idle():
'''
VISION_NEW = '''    namespace["sfx_vision_look"] = look                 # [unseen-video] the set studies what it rings
    namespace["sfx_vision_write"] = write

    holder: dict[str, Any] = {}

    @app.on_event("startup")
    async def start_sfx_vision_idle():
'''

# ---------------------------------------------------------------- desktop/pip-window.cjs
MENU_OLD = '''      { label: 'Endless video', type: 'checkbox', checked: playback?.on === true,
'''
MENU_NEW = '''      { label: 'Unseen video (endless - clips he has never categorised)', type: 'checkbox', checked: playback?.on === true,   /* [unseen-video] */
'''

EDITS = {
    "app.py": [
        ("the rotation pick takes an unseen flag", SIG_OLD, SIG_NEW, 1),
        ("...and asks for the uncategorised", WHERE_OLD, WHERE_NEW, 1),
        ("...through its folder retries", RETRY1_OLD, RETRY1_NEW, 1),
        ("the async pick carries it", ASYNC_OLD, ASYNC_NEW, 1),
        ("the set's study room and the unseen dial", HELPERS_OLD, HELPERS_NEW, 1),
        ("the fresh pick prefers the unseen", FRESH_OLD, FRESH_NEW, 1),
        ("every rung clip is studied as it plays", RING_OLD, RING_NEW, 1),
        ("the mode says how deep the unseen pool is", STATE_OLD, STATE_NEW, 1),
    ],
    "sfx_vision_idle.py": [
        ("the vision keeper lends its look and write", VISION_OLD, VISION_NEW, 1),
    ],
    "desktop/pip-window.cjs": [
        ("the desk calls the mode by its name", MENU_OLD, MENU_NEW, 1),
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
            print("%-46s (not in this tree - skipped)" % name[-46:])
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
                print("%-72s applied" % label[:72])
                continue
            n = text.count(old)
            if n == want:
                print("%-72s ready" % label[:72])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-72s MISSING (anchor count %d, wanted %d)" % (label[:72], n, want))
                missing = True
        if changed:
            plans.append((path, text, mode, bom))
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
        tmp = path.with_suffix(path.suffix + ".unseen.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

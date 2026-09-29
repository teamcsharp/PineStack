#!/usr/bin/env python3
"""[s3-wall-folder] The endless set's FOLDER is rolled on a System 3 table, then its clip.

"The FOLDER must be rolled on a System 3 table, not just labelled, as well as
the clip" (operator, 2026-09-29). Today sfx_db_pick_rotation_row rolls the clip
(sfxtv.deck_clip) over the whole unspent deck and the folder is only a label.

After this:
  1. the folder is a desk row, POOLS1 `sfxtv.wall_folder` - every folder with
     unspent clips, weighted and switchable in the Tables editor (tabled the
     first time it is rolled; a folder the row never listed joins at even odds);
  2. System 3 rolls the folder among those the desk offers (recently used
     folders held back while others remain), then the clip inside it
     (sfxtv.deck_clip, as before); a clip heard inside the day is refused;
  3. both rolls ride the clip: right after _sfx_wall_roll_note the folder roll
     becomes the clip's noted category (_wall_folder_carry), so the set's origin record (_origin_wall_note ->
     _sfx_roll_carry) and why_line wall:<id> show "folder: <name>, d100 .., k of n".
A rolled folder with nothing left in any window falls back to the whole deck,
honestly unrolled (the clip roll still stands).

Also installs s3_offer() (app.py) and Runtime.pool_items (system3_runtime.py):
what the desk offers of a list right now, so a changing list (folders) stays
on the table without losing new members.

REQUIRES norepeat_24h_patch.py (norepeat_sfx_used).

    python3 tools/wall_folder_roll_patch.py --check | --apply
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p3_patchlib import Edit, run  # noqa: E402

A = "app.py"
R = "system3_runtime.py"

RT_METHOD_ANCHOR = '    def pick(self, key, candidates, label="", weights=None, media=None):\n'
RT_METHOD = '''    def pool_items(self, key):
        """[s3-offer] The desk's POOLS1 category for `key` as the desk holds it -
        every item, switched on or off, with its weight - or None (not tabled)."""
        try:
            cat = self._find("POOL", str(key)[:60])
            if not cat:
                return None
            return [dict(i) for i in cat.get("items") or [] if isinstance(i, dict)]
        except Exception as exc:  # noqa: BLE001
            self.fail("station pool items", exc)
            return None

'''
RT_NS_ANCHOR = '    namespace["system3_pool"] = rt.pool\n'
RT_NS = '    namespace["system3_pool_items"] = rt.pool_items                    # [s3-offer]\n'

OFFER_ANCHOR = "def sfx_db_pick_rotation_row(video: bool = True) -> tuple[Path, float] | None:\n"
OFFER_NEW = '''def s3_offer(key: str, options: Any, label: str = "") -> list[str]:
    """[s3-offer] What the desk offers of `options` right now: the ones its
    POOLS1 row keeps switched on (weight above 0), plus any the row has never
    listed - a new member joins at even odds until the desk says otherwise.
    The row is tabled the first time (s3_pool). Dice off: every option."""
    opts = [" ".join(str(o).split()) for o in (options or []) if str(o or "").strip()]
    if not opts:
        return []
    try:
        s3_pool(key, opts, label)
    except Exception:  # noqa: BLE001
        pass
    fn = globals().get("system3_pool_items")
    try:
        items = fn(key) if fn else None
    except Exception:  # noqa: BLE001
        items = None
    if not items:
        return opts
    listed: dict[str, bool] = {}
    for it in items:
        text = " ".join(str(it.get("text") or "").split())
        if text:
            try:
                listed[text] = bool(it.get("enabled") is not False and float(it.get("weight", 1.0) or 0) > 0)
            except (TypeError, ValueError):
                listed[text] = True
    return [o for o in opts if listed.get(o, True)]


# --- [s3-wall-folder] THE ENDLESS SET'S FOLDER IS ROLLED, THEN ITS CLIP -----------
# "the FOLDER must be rolled on a System 3 table, not just labelled, as well as
# the clip" (operator, 2026-09-29). The desk row sfxtv.wall_folder (POOLS1)
# holds the folders and their weights; the roll is among the folders with
# unspent clips (recently used ones held back while others remain), then the
# clip roll (sfxtv.deck_clip) is made inside the folder, and both ride the
# clip's origin record.
_WALL_FOLDER_ROLL: dict[str, Any] = {}
WALL_FOLDER_LABEL = "which folder the endless set's next clip comes from"


def _wall_folder_roll(con: Any, cycle: int, want: int, pin: str, recent: Any, exclude: Any = ()) -> str:
    """The folder, rolled (or "" - the whole deck, as before). `exclude`:
    folders already rolled this pick that gave no clip."""
    _WALL_FOLDER_ROLL.clear()
    try:
        where = "playable = 1 AND video = ? AND deck_cycle < ?"
        args: tuple[Any, ...] = (want, cycle)
        if pin:
            where += " AND path LIKE ?"
            args += (pin.replace("%", "%%") + "%",)
        rows = con.execute("SELECT folder, COUNT(*) AS n FROM clips WHERE " + where
                           + " GROUP BY folder", args).fetchall()
        gone = set(str(x) for x in (exclude or ()))
        have = {str(r[0] or ""): int(r[1] or 0) for r in rows
                if str(r[0] or "") and int(r[1] or 0) > 0 and str(r[0] or "") not in gone}
        if not have:
            return ""
        offered = s3_offer("sfxtv.wall_folder", sorted(have), WALL_FOLDER_LABEL)
        held = set(str(x) for x in (recent or []))
        fresh = [f for f in offered if f not in held] or offered
        if not fresh:
            return ""
        k = _S3Dice("sfxtv.wall_folder", WALL_FOLDER_LABEL).pick("sfxtv.wall_folder", fresh)
        k = k if 0 <= k < len(fresh) else 0
        folder = fresh[k]
        rec = _s3_sfx_rolled("sfxtv.wall_folder", folder, k)
        # System 3's own record, or nothing: the station's own draw (dice off)
        # notes no dice, as the clip roll does not
        _WALL_FOLDER_ROLL.update(folder=folder, roll=dict(rec), rolled=bool(rec), at=time.time(),
                                 clips=have.get(folder, 0), offered=len(fresh))
        return folder
    except Exception:  # noqa: BLE001 - a folder roll never costs the set its clip
        _WALL_FOLDER_ROLL.clear()
        return ""


def _wall_folder_carry(path: Any) -> None:
    """The folder roll joins the clip's noted roll (_SFX_ROLLED, which the
    set's origin record carries): its category is the folder, rolled. Only
    when System 3 rolled the folder - its own draw notes nothing."""
    try:
        if not _WALL_FOLDER_ROLL.get("rolled"):
            return
        with _SFX_ROLLED_LOCK:
            got = _SFX_ROLLED.get(str(path))
            if isinstance(got, dict):
                got["category"] = _wall_folder_category(path)
    except Exception:  # noqa: BLE001
        pass


def _wall_folder_category(path: Any) -> dict[str, Any]:
    """The clip's category for its origin record: the folder roll that chose
    it (fresh, and this clip's), else the plain folder label."""
    got = dict(_WALL_FOLDER_ROLL)
    if got.get("folder") and got.get("rolled") and time.time() - float(got.get("at") or 0) < 60:
        return dict(got.get("roll") or {}, label=str(got["folder"]), key="sfxtv.wall_folder",
                    clips=got.get("clips"), offered=got.get("offered"))
    return {"label": Path(str(path)).parent.name}


def sfx_db_pick_rotation_row(video: bool = True, _unrolled: bool = False,
                             _tried: tuple = ()) -> tuple[Path, float] | None:   # [s3-wall-folder:def]
'''

# Every new name the pick reaches for is looked up with globals().get and
# guarded: a helper that is missing (a test that execs the function alone) or
# fails leaves the pick exactly as it was before this wave - never without a
# clip while the deck holds a playable one it may air.
ROLL_ANCHOR = "        recent = sfx_video_recent_folders() if video else []\n"
ROLL_NEW = '''        _fold = ""                                                        # [s3-wall-folder:roll]
        if video and not _unrolled:
            try:
                _fold = str((globals().get("_wall_folder_roll") or (lambda *a, **k: ""))(
                    con, cycle, want, pin, recent, exclude=_tried) or "")
            except Exception:  # noqa: BLE001 - a folder roll never costs the set its clip
                _fold = ""
'''

WHERE_ANCHOR = "                args: tuple[Any, ...] = (want, cycle)\n"
WHERE_NEW = '''                if _fold:                                                 # [s3-wall-folder:where]
                    where += " AND folder = ?"
                    args += (_fold,)
'''

# A clip heard inside the day is refused (recorded) and the clip is rolled
# AGAIN in the same window - at most six times - instead of giving the window up.
NOREP_ANCHOR = "                _sfx_wall_roll_note(row, _wall_u, count)"
NOREP_NEW = '''                _nr_used = globals().get("norepeat_sfx_used")               # [s3-wall-folder:norepeat]
                _nr_sid = globals().get("sfx_id")
                _nr_try = 0
                while (row is not None and _nr_used and _nr_sid
                       and _nr_used(_nr_sid(Path(str(row["path"]))))):
                    _nr_ref = globals().get("norepeat_select_refuse")
                    if _nr_ref:
                        _nr_ref("sfx", _nr_sid(Path(str(row["path"]))), "wall", ref=Path(str(row["path"])).name)
                    _nr_try += 1
                    if _nr_try > 6:
                        row = None
                        break
                    _wall_u = s3_roll("sfxtv.deck_clip", "which unspent clip of the video deck comes next")
                    row = con.execute(
                        "SELECT path, seconds FROM clips WHERE " + where + " LIMIT 1 OFFSET ?",
                        args + (min(count - 1, int(_wall_u * count)),)).fetchone()
                if row is None:
                    continue
'''

FALL_ANCHOR = '''        with _SFX_VIDEO_ROTATION_LOCK:
            _SFX_VIDEO_ROTATION["why"] = "exhausted"
'''
# a rolled folder that gave nothing: another rolled folder (two more), then the
# whole deck unrolled - the set is never left without a clip it may air
FALL_NEW = '''        if _fold:                                                         # [s3-wall-folder:fallback]
            (globals().get("_WALL_FOLDER_ROLL") or {}).clear()
            if len(_tried) < 2:
                return sfx_db_pick_rotation_row(video, False, tuple(_tried) + (_fold,))
            return sfx_db_pick_rotation_row(video, True)
'''

# _sfx_wall_roll_note is p2_wall_roll_patch's text: the folder roll is put on the
# clip's noted roll right after it is called, not inside it.
NOTE_ANCHOR = "                _sfx_wall_roll_note(row, _wall_u, count)   # [s3-account-wall] the clip carries its dice\n"
NOTE_NEW = '''                if _fold and globals().get("_wall_folder_carry"):          # [s3-wall-folder:carry]
                    globals()["_wall_folder_carry"](Path(str(row["path"])))
'''

EDITS = [
    Edit("runtime pool_items", R, RT_METHOD_ANCHOR, RT_METHOD, "[s3-offer] The desk's POOLS1 category", "before"),
    Edit("runtime install", R, RT_NS_ANCHOR, RT_NS, 'namespace["system3_pool_items"]', "after"),
    Edit("s3_offer + folder roll", A, OFFER_ANCHOR, OFFER_NEW, "[s3-wall-folder:def]", "replace"),
    Edit("roll", A, ROLL_ANCHOR, ROLL_NEW, "[s3-wall-folder:roll]", "after"),
    Edit("where", A, WHERE_ANCHOR, WHERE_NEW, "[s3-wall-folder:where]", "after"),
    Edit("norepeat", A, NOREP_ANCHOR, NOREP_NEW, "[s3-wall-folder:norepeat]", "before"),
    Edit("fallback", A, FALL_ANCHOR, FALL_NEW, "[s3-wall-folder:fallback]", "before"),
    Edit("carry", A, NOTE_ANCHOR, NOTE_NEW, "[s3-wall-folder:carry]", "after"),
]

if __name__ == "__main__":
    sys.exit(run("wall_folder_roll_patch", EDITS, requires=[("app.py", "[no-repeat-24h:helpers]")]))

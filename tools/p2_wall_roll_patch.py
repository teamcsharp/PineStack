"""[s3-account-wall] app.py: the endless set's clip carries the dice that drew it.

The previous audit counted the endless video set as the biggest rogue road
(77 items). The set is off since 2026-09-28, so none aired in the last 6 h,
but the road was still open: its clip IS drawn through the dice door
(sfx_db_pick_rotation_row: s3_roll("sfxtv.deck_clip") picks the OFFSET into
the unspent video deck), yet the roll was never noted on the clip, so
_origin_wall_note -> _sfx_roll_carry found no sfx_roll and the origin ledger
filed every set clip as rogue ("no System 3 stamp", producer sfx_video_cycle).

Fix at the road that owns the draw: the rotation pick reads its own roll back
off System 3's record (system3_last_roll - never re-derived; only when it is
THIS draw's number) and notes it on the clip with _sfx_roll_note(..., "wall"),
the same door the board's cadence uses. The set's origin record then carries
"SFX clip (wall)" with the die, index and of-how-many. The matcher's picks
already note theirs ("match"). System 3 off = the station's own random: no
note, and the item stays what it honestly is.

  python tools/p2_wall_roll_patch.py --check app.py   (0 ready, 2 applied, 1 anchor missing)
  python tools/p2_wall_roll_patch.py --apply app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s3_account_p2_lib import Edit, run  # noqa: E402

MARKER = "[s3-account-wall]"

EDITS = [
    Edit("rotation-roll-kept",
         '                    args + (min(count - 1, int(s3_roll("sfxtv.deck_clip", "which unspent clip of the video deck comes next") * count)),)).fetchone()   # [s3-dice-door]\n',
         replace=('                    args + (min(count - 1, int((_wall_u := s3_roll("sfxtv.deck_clip", "which unspent clip of the video deck comes next")) * count)),)).fetchone()   # [s3-dice-door] [s3-account-wall] the number is kept\n')),
    Edit("rotation-roll-noted",
         '                with _SFX_VIDEO_ROTATION_LOCK:\n'
         '                    _SFX_VIDEO_ROTATION["why"] = ""\n'
         '                return (Path(str(row["path"])), float(row["seconds"] or 0.0))\n',
         '                _sfx_wall_roll_note(row, _wall_u, count)   # [s3-account-wall] the clip carries its dice\n',
         where="before"),
    Edit("wall-roll-note-fn",
         "def _sfx_roll_take(path: Any) -> dict[str, Any]:\n",
         '''def _sfx_wall_roll_note(row: Any, u: Any, count: Any) -> None:
    """[s3-account-wall] The endless set's clip is the dice door's draw
    (sfxtv.deck_clip: which unspent clip of the video deck comes next). Read
    the roll back off System 3's record - never re-derived, and only when it
    is this draw's number - and note it on the clip, so the set's origin
    record (_origin_wall_note -> _sfx_roll_carry) carries its dice. System 3
    off (the station's own random): nothing is noted. Never costs the clip."""
    try:
        fn = globals().get("system3_last_roll")
        rec = fn("sfxtv.deck_clip") if fn else None
        if (not isinstance(rec, dict) or u is None or rec.get("u") is None
                or abs(float(rec.get("u")) - float(u)) > 1e-9):
            return
        path = Path(str(row["path"]))
        n = max(1, int(count or 1))
        _sfx_roll_note(path, "wall", {"label": path.parent.name},
                       {"label": path.stem[:160], "dice": rec.get("dice"), "u": rec.get("u"),
                        "index": min(n - 1, int(float(u) * n)) + 1, "of": n}, 1)
    except Exception:  # noqa: BLE001
        pass


''',
         where="before"),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS, MARKER))

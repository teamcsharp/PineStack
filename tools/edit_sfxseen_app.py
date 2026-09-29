"""[sfxseen] app.py: install the SFX display receipts (sfx_display.py) and put
the script's line id on every picture the sets are handed.

  install   after the origin ledger's install: POST /api/sfx/display-receipts,
            GET /api/sfx/display-audit?hours=N | ?line=ID (sfx_display.install)
  rung      page_picture_append carries the caller's `line` onto the rung
  cadence   _sfx_cadence_pictures hands the board row's id as `line` - the
            welded "punct" rows are the script's own rows
  sting     dj_sting's picture clip carries its booth row's id (assigned now,
            the same 6-hex shape _ensure_chat_ids would give it later)

Patch app.py ON THE HOST (the share is too slow for a 10 MB file):
  cat edit_sfxseen_app.py sfxseen_lib.py | ...   (or scp both, then)
  python3 edit_sfxseen_app.py --check app.py ; python3 edit_sfxseen_app.py --apply app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sfxseen_lib import Edit, run  # noqa: E402

EDITS = [
    Edit("install",
         '    print("the origin ledger did not install: %s: %s" % (type(_origin_exc).__name__, _origin_exc))\n',
         '# [sfxseen] SFX DISPLAY RECEIPTS (sfx_display.py): each player says whether a\n'
         '# clip\'s picture reached its screen (surface, first frame, rect, seconds, the\n'
         '# operator\'s reaction); joined to the script\'s SFX rows. A KEEP store, 7 days.\n'
         'try:\n'
         '    import sfx_display as _sfx_display\n'
         '    _SFX_DISPLAY_RUNTIME = _sfx_display.install(app, globals())\n'
         'except Exception as _sfxd_exc:  # noqa: BLE001\n'
         '    _SFX_DISPLAY_RUNTIME = None\n'
         '    print("the SFX display receipts did not install: %s: %s" % (type(_sfxd_exc).__name__, _sfxd_exc))\n'),
    Edit("rung",
         '        rung["endless"] = True             # 2026-09-14: the set may drop it\n',
         '    if clip.get("line"):                   # [sfxseen] the script row this picture is\n'
         '        rung["line"] = str(clip.get("line"))[:80]\n'),
    Edit("cadence",
         '            "why": str(row.get("sfx_match_why") or ""),\n',
         '            "line": str(row.get("id") or ""),     # [sfxseen] the script row it pictures\n'),
    Edit("sting-id",
         '    await _s3_loose_board_stamp(_sting_row, sample)        # [s3-cover-b] GAP 10\n',
         '    _sting_row.setdefault("id", uuid.uuid4().hex[:6])      # [sfxseen] its line id, now\n'),
    Edit("sting-line",
         '            **({"broadcast_ms": _tube_at_ms} if _tube_at_ms else {}),\n',
         '            "line": str(_sting_row.get("id") or ""),   # [sfxseen] the script row\n'),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS))

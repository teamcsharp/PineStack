"""[msgid] app.py: every NEW feed row's code is 8 hex, unique in the window,
and GET /api/why/{code} tells one message's life story (line_story.py).

  mint       a helper before _ensure_chat_ids: _mint_line_id() - 8 hex,
             re-rolled while it collides with the ring or the 48 h air-log
             index (6 hex had ~14 colliding pairs per 48 h; the origin
             ledger's PRIMARY KEY and the air-log compaction kept one of two)
  lazy       _ensure_chat_ids gives an id-less row _mint_line_id()
  ad         ad_booth_row's row id
  song/image the analysis rows' ids
  news x2    the news marker rows (_nm_id, #1036 G1)
  banter     the concat banter rows; call  the call transcript rows
  sting      dj_sting's booth row (the [sfxseen] setdefault)
  live       the held-clip replay's fallback id
  install    after the SFX display receipts: line_story.install (GET /api/why/{code})

Existing ids are never renamed: 6-hex and 32-hex rows keep their ids; only
rows minted after the restart get 8 hex. Single-line anchors throughout.

Patch app.py ON THE HOST (the share is too slow for a 10 MB file):
  python3 tools/edit_msgid_app.py --check app.py ; python3 tools/edit_msgid_app.py --apply app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from msgid_lib import Edit, run  # noqa: E402

MINT = '_mint_line_id()'
T = "  # [msgid] 8 hex, unique in the window"

HELPER = '''def _mint_line_id() -> str:
    """[msgid] A NEW message's code: 8 hex, re-rolled while it collides with a
    row still in the ring or in the 48 h air-log index. 6 hex (16.7 M) gave
    about 14 colliding pairs in every 48 h at ~450 ids an hour, and a
    collision is not cosmetic: the air-log index, its hourly compaction and
    the origin ledger (PRIMARY KEY line_id, kept forever) each keep only one
    of the two. Old 6-hex and 32-hex ids stay exactly as they are."""
    held = globals().get("_AIRLOG_INDEX") or {}
    ring = _RADIO.get("chat") or []
    for _ in range(12):
        code = uuid.uuid4().hex[:8]
        if code in held or any(isinstance(m, dict) and m.get("id") == code for m in ring):
            continue
        return code
    return uuid.uuid4().hex[:12]


'''

EDITS = [
    Edit("mint", "def _ensure_chat_ids() -> None:\n", HELPER, where="before"),
    Edit("lazy", '            _m["id"] = uuid.uuid4().hex[:6]\n', None,
         replace='            _m["id"] = %s%s\n' % (MINT, T)),
    Edit("ad", '\n            "id": uuid.uuid4().hex[:6],\n            "ts": int(time.time()),\n', None,
         replace='\n            "id": %s,%s\n            "ts": int(time.time()),\n' % (MINT, T)),
    Edit("song", '        "id": uuid.uuid4().hex[:6], "ts": int(time.time()),\n', None,
         replace='        "id": %s, "ts": int(time.time()),%s\n' % (MINT, T)),
    Edit("image", '        "id": uuid.uuid4().hex[:6], "ts": int(now),\n', None,
         replace='        "id": %s, "ts": int(now),%s\n' % (MINT, T)),
    Edit("news-1", '\n                        _nm_id = uuid.uuid4().hex[:6]      # #1036 (G1)\n', None,
         replace='\n                        _nm_id = %s      # #1036 (G1)%s\n' % (MINT, T)),
    Edit("news-2", '\n        _nm_id = uuid.uuid4().hex[:6]                      # #1036 (G1)\n', None,
         replace='\n        _nm_id = %s                      # #1036 (G1)%s\n' % (MINT, T)),
    Edit("banter", '\n                rows.append({"id": uuid.uuid4().hex[:6],\n', None,
         replace='\n                rows.append({"id": %s,%s\n' % (MINT, T)),
    Edit("call", '\n            rows.append({"id": uuid.uuid4().hex[:6],\n', None,
         replace='\n            rows.append({"id": %s,%s\n' % (MINT, T)),
    Edit("sting", '    _sting_row.setdefault("id", uuid.uuid4().hex[:6])      # [sfxseen] its line id, now\n', None,
         replace='    _sting_row.setdefault("id", %s)      # [sfxseen] its line id, now [msgid] 8 hex\n' % MINT),
    Edit("live", '    live_id = line_id or uuid.uuid4().hex[:6]\n', None,
         replace='    live_id = line_id or %s%s\n' % (MINT, T)),
    Edit("install",
         '    print("the SFX display receipts did not install: %s: %s" % (type(_sfxd_exc).__name__, _sfxd_exc))\n',
         '# [msgid] WHY THIS LINE: GET /api/why/{code} - one message\'s life story\n'
         '# across every store, read-only (line_story.py; tools/why_line.py is the\n'
         '# same reader on the command line). ?brief=1 is the find box\'s resolver.\n'
         'try:\n'
         '    import line_story as _line_story\n'
         '    _line_story.install(app, globals())\n'
         'except Exception as _ls_exc:  # noqa: BLE001\n'
         '    print("the line story door did not install: %s: %s" % (type(_ls_exc).__name__, _ls_exc))\n'),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS))

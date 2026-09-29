#!/usr/bin/env python3
"""[outlandish] line_story.py (why_line, GET /api/why): the meter's reading and the
SFX Guy's reaction are on the line's story.

  W1 [outl-why-read]  _s3(): the line's MEASURE / SFXREACT / HOLD records off the ledger
  W2 [outl-why-life]  story(): a "measured" event - "OUTLANDISH 82 · conspiracy, slur",
                      its cues, and the reaction he rolled

usage: outlandish_why_patch.py --check|--apply line_story.py   (0 ready, 2 applied, 1 missing)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outlandish_patchlib import run  # noqa: E402

EDITS = [
    ("[outl-why-read]", "after",
     '                                       "turns": summ.get("turns"), "events": summ.get("events")}\n',
     '            try:                                                              # [outl-why-read] the meter\n'
     '                import zlib\n'
     '                meas = []\n'
     '                for fam, blob in c.execute("SELECT family, body FROM events WHERE conversation_id=? AND "\n'
     '                                           "kind=\'observation\' AND family IN (\'MEASURE\',\'SFXREACT\',\'HOLD\')",\n'
     '                                           (r[0],)).fetchall():\n'
     '                    try:\n'
     '                        b = json.loads(zlib.decompress(blob).decode("utf-8"))\n'
     '                    except Exception:  # noqa: BLE001\n'
     '                        continue\n'
     '                    if lid in (b.get("lines") or []) or (not b.get("lines") and b.get("turn_id") == r[1]):\n'
     '                        sel = b.get("selected") or {}\n'
     '                        cues = [str(x.get("label")) + ": " + str(x.get("match"))\n'
     '                                for x in ((b.get("measure") or {}).get("cues") or [])][:6]\n'
     '                        meas.append({"family": fam, "at": b.get("at"), "label": sel.get("label"),\n'
     '                                     "score": sel.get("score"), "tags": sel.get("tags"), "cues": cues,\n'
     '                                     "clip": sel.get("clip")})\n'
     '                if meas:\n'
     '                    out["outlandish"] = meas\n'
     '            except sqlite3.Error:\n'
     '                pass\n'),
    ("[outl-why-life]", "after",
     '    s3db = _s3(data, lid)\n'
     '    out["system3"] = s3db\n',
     '    for _m in s3db.get("outlandish") or []:                                  # [outl-why-life]\n'
     '        add(_m.get("at"), "measured" if _m.get("family") == "MEASURE" else "reacted",\n'
     '            str(_m.get("label") or _m.get("family")),\n'
     '            **{k: v for k, v in (("cues", _m.get("cues")), ("clip", _m.get("clip"))) if v})\n'),
]

if __name__ == "__main__":
    sys.exit(run(EDITS, sys.argv))

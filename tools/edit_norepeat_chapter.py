#!/usr/bin/env python3
"""[norepeat-chapter] The chapter keeper never airs an opening that already sounded.

Measured 2026-09-29 after wave BE: a manager page round (7 lines) and a station-ID
round (3 lines) each aired twice, about 2 minutes apart, under new ids. Both second
airings came from `_s3_chapter_replay` (called by `_s3_chapter_keep_once`): the
keeper airs a "prepared" exchange that waited - but that exchange's opening had
already gone out through its own road, and the keeper never learned it. The 24 h
book knew. Now the keeper asks the book first; a sounded opening retires the
exchange (recorded as a no-repeat refusal and a chapter state), never re-airs it.

usage: edit_norepeat_chapter.py --check|--apply app.py   (0 ready, 2 applied, 1 missing)
"""
import sys
from pathlib import Path

MARK = "[norepeat-chapter]"
A = ('    """[s3-chain] A prepared exchange that waited airs through its own road."""\n'
     '    fn = str(e.get("road_fn") or "dj_speak")\n')
N = ('    """[s3-chain] A prepared exchange that waited airs through its own road."""\n'
     '    fn = str(e.get("road_fn") or "dj_speak")\n'
     '    # [norepeat-chapter] an opening that already sounded inside the day is retired,\n'
     '    # never re-aired: the keeper can hold an exchange its own road already played.\n'
     '    try:\n'
     '        _nr_on, _nr_used = globals().get("norepeat_on"), globals().get("norepeat_text_used")\n'
     '        _nr_txt = str(e.get("opening") or "")\n'
     '        if callable(_nr_on) and callable(_nr_used) and _nr_on() and _nr_txt and _nr_used(_nr_txt):\n'
     '            _nr_ref = globals().get("norepeat_refuse")\n'
     '            if callable(_nr_ref):\n'
     '                _nr_ref("line", str(e.get("key") or ""), "chapter:" + fn, _nr_txt,\n'
     '                        why="the prepared exchange\'s opening already sounded inside the day",\n'
     '                        stage="air", ref=str(e.get("key") or ""))\n'
     '            _s3_chapter_note(e, "expired", "its opening already sounded inside the day - '
     'retired, not re-aired (no repeats)", drop=True)\n'
     '            return True\n'
     '    except Exception:  # noqa: BLE001\n'
     '        pass\n')


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    p = Path(sys.argv[2])
    raw = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    if MARK in text:
        print(MARK, "already applied"); return 2
    if text.count(A) != 1:
        print(MARK, "anchor missing (%d)" % text.count(A)); return 1
    if mode != "--apply":
        print(MARK, "ready"); return 0
    text = text.replace(A, N, 1)
    if crlf:
        text = text.replace("\n", "\r\n")
    p.write_bytes(text.encode("utf-8"))
    print(MARK, "applied"); return 2


if __name__ == "__main__":
    sys.exit(main())

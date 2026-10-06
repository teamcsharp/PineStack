#!/usr/bin/env python3
"""[match-coalesce] The clip matcher rebuilds its index at most once a quarter hour. 2026-10-06.

Measured on the live station (docker logs): 161 "[sfx-match] indexed 366k clip(s)"
rebuilds in three hours and 234 in the three before - about one a minute - each
4 to 123 s of Python on the "sfx-match-index" thread. py-spy --gil during the
endless cycle's stalls (the tube dark for 50-200 s, the API answering nothing
for 5 s at a time): the GIL held ~85% of the time, sfx_match_build among the
top holders beside the pantry flush and the director room. Eleven call sites
kick a rebuild - the SFX guy's listener after every clip it hears, the unseen
study every ten clips, folder pins, the API - and each kick rebuilt the whole
index at once.

sfx_match_kick keeps its contract (build in the background, one at a time,
never on the loop) and adds one rest: a rebuild that finished less than
SFX_MATCH_REBUILD_EVERY (900 s, env PINE_SFX_MATCH_REBUILD_EVERY) ago makes a
kick COALESCE - counted, and one daemon timer rebuilds once when the rest ends,
so nothing a kick asked for is lost, it is just batched. force=True still
rebuilds now (the operator's button).

Usage:  match_coalesce_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        match_coalesce_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

CONST_OLD = '''_SFX_MATCH_THREAD: list[Any] = [None]
'''
CONST_NEW = '''_SFX_MATCH_THREAD: list[Any] = [None]
_SFX_MATCH_TIMER: list[Any] = [None]                           # [match-coalesce] the one deferred rebuild
SFX_MATCH_REBUILD_EVERY = float(os.getenv("PINE_SFX_MATCH_REBUILD_EVERY", "900"))   # [match-coalesce]
'''

KICK_OLD = '''    thread = _SFX_MATCH_THREAD[0]
    if thread is not None and thread.is_alive():
        return False
    thread = Thread(target=sfx_match_build, name="sfx-match-index", daemon=True)
'''
KICK_NEW = '''    thread = _SFX_MATCH_THREAD[0]
    if thread is not None and thread.is_alive():
        return False
    if not force:
        # [match-coalesce] at most one rebuild a quarter hour: 161 rebuilds in three hours, 4-123 s
        # of Python each, held the GIL from the loop (the endless cycle froze, the API timed out).
        # A kick inside the rest is counted and ONE daemon timer rebuilds when the rest ends.
        _since = time.time() - float(_SFX_MATCH.get("at") or 0)
        if _since < SFX_MATCH_REBUILD_EVERY:
            _SFX_MATCH["coalesced"] = int(_SFX_MATCH.get("coalesced") or 0) + 1
            _SFX_MATCH["wanted_at"] = time.time()
            _timer = _SFX_MATCH_TIMER[0]
            if _timer is None or not _timer.is_alive():
                from threading import Timer as _Timer
                _timer = _Timer(max(1.0, SFX_MATCH_REBUILD_EVERY - _since), sfx_match_kick)
                _timer.daemon = True
                _SFX_MATCH_TIMER[0] = _timer
                _timer.start()
            return False
    thread = Thread(target=sfx_match_build, name="sfx-match-index", daemon=True)
'''

STATE_OLD = '''        "picks": int(_SFX_MATCH.get("picks") or 0),
'''
STATE_NEW = '''        "picks": int(_SFX_MATCH.get("picks") or 0),
        "coalesced": int(_SFX_MATCH.get("coalesced") or 0),   # [match-coalesce] kicks batched into the next rebuild
        "rebuild_every_s": SFX_MATCH_REBUILD_EVERY,
'''

EDITS = {
    "app.py": [
        ("the timer slot and the rest", CONST_OLD, CONST_NEW, 1),
        ("a kick inside the rest coalesces", KICK_OLD, KICK_NEW, 1),
        ("the state says how many were batched", STATE_OLD, STATE_NEW, 1),
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
        tmp = path.with_suffix(path.suffix + ".matchco.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

#!/usr/bin/env python3
"""[flow-ledger] [s3-deadair] An approved line is said in place; a banked response finds a seat that has one. 2026-10-05.

Found testing the approve door on the live station: POST /api/flow-ledger/approve
answered "The booth did not put it out". A single line on the aside road is
admitted as the opener of a graph exchange and waits on the prepared shelf for
its replies - by hand or not. The request's own context now carries the mark
for a line said in place (as the dead-air node's inserts do).

And the dead-air node's "banked response" for the third seat found nothing,
because the response bank records the host and the co-host: the roll now goes
to the next seat that has a response banked.

Usage:  approve_in_place_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        approve_in_place_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APPROVE_OLD = r'''    said = await dj_speak("aside", None, line=text, who=who, by_hand=True, sting=False)
    FLOW_LEDGER.mark(int(row["n"]), approved=bool(said), approved_at=round(time.time(), 3))
'''
APPROVE_NEW = r'''    _S3_CHAPTER_ROW.set("row")      # [flow-ledger] said in place: an approved line does not wait on the shelf for an exchange
    said = await dj_speak("aside", None, line=text, who=who, by_hand=True, sting=False)
    FLOW_LEDGER.mark(int(row["n"]), approved=bool(said), approved_at=round(time.time(), 3))
'''

BANK_OLD = r'''        if kind == "banked response":
            voice = str((await session_voices()).get(who) or "")
            engine = voice_engine_for(voice) if voice else ""
            ready = await asyncio.to_thread(_RESPONSES.ready, voice, engine) if voice else []
            fresh = [str(r.get("text") or "") for r in ready
                     if str(r.get("text") or "").strip() and not norepeat_text_used(r.get("text"))]
            if fresh:
'''
BANK_NEW = r'''        if kind == "banked response":
            # [s3-deadair] the bank records the host and the co-host: a roll that lands on a
            # seat with nothing banked goes to the next seat that has, not to nothing
            voices = dict(await session_voices())
            fresh = []
            for seat in [who] + [w for w in seats if w != who]:
                voice = str(voices.get(seat) or "")
                engine = voice_engine_for(voice) if voice else ""
                ready = await asyncio.to_thread(_RESPONSES.ready, voice, engine) if voice else []
                fresh = [str(r.get("text") or "") for r in ready
                         if str(r.get("text") or "").strip() and not norepeat_text_used(r.get("text"))]
                if fresh:
                    who = seat
                    break
            if fresh:
'''

EDITS = {"app.py": [
    ("an approved line is said in place", APPROVE_OLD, APPROVE_NEW,
     "# [flow-ledger] said in place: an approved line does not wait", 1),
    ("a banked response finds a seat", BANK_OLD, BANK_NEW,
     "# [s3-deadair] the bank records the host and the co-host: a roll that lands", 1),
]}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        text = path.read_bytes().decode("utf-8")
        crlf = "\r\n" in text
        if crlf:
            if text.count("\r\n") != text.count("\n"):
                raise SystemExit("%s has mixed line endings; refusing to guess" % path)
            text = text.replace("\r\n", "\n")
        todo = []
        for edit in edits:
            _n, old, _new, probe, count = edit
            have = text.count(probe)
            state = ("applied" if have == count else
                     "ready" if not have and text.count(old) == count else
                     "missing (anchor found %d, probe %d)" % (text.count(old), have))
            print("%-8s %-36s %s" % (name, edit[0], state))
            if state == "ready":
                todo.append(edit)
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, crlf, todo))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, crlf, todo in plans:
        for _n, old, new, probe, count in todo:
            assert text.count(old) == count, (path.name, _n)
            text = text.replace(old, new)
            assert text.count(probe) == count, (path.name, _n, "probe")
        if todo:
            tmp = path.with_name(path.name + ".approve.tmp")
            tmp.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
            os.replace(tmp, path)
            print("wrote %s (%d edit(s), %s)" % (path.name, len(todo), "CRLF" if crlf else "LF"))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

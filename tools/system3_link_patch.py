"""A ledger row finds its System 3 turn by its WORDS ([s3-link]).

Measured 2026-09-27 on a call: the station spliced three rows in front of
the round at air, the ledger numbered rows by spoken order, the link looked
the turn up by that number - every row linked three turns off, the last
three to none, and the inspector showed the caller's story as the host's
greeting. The words are the one thing the bind and the air share, so the
row asks system3_turn_id_for(meta, words, who) first and falls back to the
number only when the words find nothing. The SFX Guy's row links to the
host turn it followed, flagged, so the inspector can show his node and the
draw that chose his line.

--check exits 0 ready / 2 applied / 1 missing; --apply writes LF atomically.
ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("row-by-words",
     '                    _t = (turn_ix[_row_at] if _row_at < len(turn_ix) else -1)\n'
     '                    return {"conversation_id": str(_s3m.get("conversation_id") or ""),\n'
     '                            "mode": str(_s3m.get("mode") or ""),\n'
     '                            "turn_id": str((_s3m.get("turns") or {}).get(str(_t)) or "")}\n',
     '                    # [s3-link] BY ITS WORDS FIRST. The number below is the\n'
     '                    # spoken-row order, which a splice at air shifts; the words\n'
     '                    # are what the bind and the air share.\n'
     '                    _w_here = str(transcript[_row_at][0]) if _row_at < len(transcript) else ""\n'
     '                    _c_here = str(transcript[_row_at][1]) if _row_at < len(transcript) else ""\n'
     '                    _tid = ""\n'
     '                    if _w_here == "drop":\n'
     '                        # the SFX Guy\'s row: the host turn it followed\n'
     '                        for _back in range(_row_at - 1, -1, -1):\n'
     '                            if str(transcript[_back][0]) in ("dj", "cohost", "third", "host"):\n'
     '                                _tid = str(globals()["system3_turn_id_for"](ready_meta, str(transcript[_back][1]), str(transcript[_back][0]))\n'
     '                                           if globals().get("system3_turn_id_for") else "")\n'
     '                                break\n'
     '                        return {"conversation_id": str(_s3m.get("conversation_id") or ""),\n'
     '                                "mode": str(_s3m.get("mode") or ""), "turn_id": _tid, "sfxguy": True}\n'
     '                    if globals().get("system3_turn_id_for") and _c_here:\n'
     '                        try:\n'
     '                            _tid = str(globals()["system3_turn_id_for"](ready_meta, _c_here, _w_here) or "")\n'
     '                        except Exception:  # noqa: BLE001\n'
     '                            _tid = ""\n'
     '                    if not _tid:\n'
     '                        _t = (turn_ix[_row_at] if _row_at < len(turn_ix) else -1)\n'
     '                        _tid = str((_s3m.get("turns") or {}).get(str(_t)) or "")\n'
     '                    return {"conversation_id": str(_s3m.get("conversation_id") or ""),\n'
     '                            "mode": str(_s3m.get("mode") or ""),\n'
     '                            "turn_id": _tid}\n', 1),
]


def plan(text):
    return list(EDITS)


def state_of(text, old, new, count):
    n_new, n_old = text.count(new), text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(text):
    applied, missing = 0, []
    for name, old, new, count in plan(text):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s (%s)" % (name, state))
    return applied, missing


def apply(path):
    path = Path(path)
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    if applied == len(plan(text)):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for name, old, new, count in plan(text):
        if state_of(text, old, new, count) == "applied":
            continue
        text = text.replace(old, new)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    os.replace(tmp, path)
    return 0


def main(argv):
    target = next((a for a in argv if not a.startswith("--")), "app.py")
    if "--apply" in argv:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    if applied == len(plan(text)):
        print("already applied")
        return 2
    print("ready")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

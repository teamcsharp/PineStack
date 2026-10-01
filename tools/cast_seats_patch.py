"""[cast-seats] footage is stale only when a voice it SPEAKS IN has changed.

2026-09-30, the operator: "If I have banked up information in the cupboard,
then I would expect that I should be able to have seamless playback with a
repeat ratio of zero. Like right now, I'm not actually hearing anyone."

Measured: 414 of 427 stamped shelf rows - 13,958 s, 3.9 hours of finished
recordings - were refused as "recorded by a cast that has since changed".
The DJ and co-host had not changed all day. The THIRD seat had: the rotating
studio guest took twenty different voices on 2026-09-30, and #1057's stamp is
one string of every seat, so each rotation turned every round on the shelf
stale - the manager's memo, the adverts and the news included, though the
guest says nothing in any of them. Banking while paused could never help:
the bank was thrown away at the next guest.

It also contradicted the recast desk (#1215), which re-records a changed seat
BESIDE the takes precisely so that "every one of those rounds is still airable
in the old voice while this runs; that is the point of the road".

Now: a round is stale only when a seat its takes speak in has changed hands
and the desk is not already re-recording it. A flat read (an advert, an ID)
with no takes is judged on every seat but the guest's - the guest never reads
one. Replayed on the shelf: 413 rows stale -> 8; 13,364 s freed.

Usage (ON THE HOST): python3 tools/cast_seats_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[cast-seats]"

OLD = '''    try:
        was = str(row.get("cast") or "")
        if not was:
            return False                # made before the stamp existed
        return was != cast_signature()
    except Exception:  # noqa: BLE001
        return False
'''
NEW = '''    try:
        was = str(row.get("cast") or "")
        if not was:
            return False                # made before the stamp existed
        now = cast_signature()
        if was == now:
            return False
        # [cast-seats] only a seat the footage SPEAKS IN can make it stale,
        # and never while the recast desk is re-recording it (#1215: it airs
        # as recorded until its replacement is whole)
        old = dict(p.split("=", 1) for p in was.split("|") if "=" in p)
        new = dict(p.split("=", 1) for p in str(now).split("|") if "=" in p)
        changed = {s for s in set(old) | set(new) if old.get(s) != new.get(s)}
        entry = row.get("entry") if isinstance(row.get("entry"), dict) else row
        if row.get("recast_needed") or entry.get("recast_needed"):
            return False
        takes = [t for t in (entry.get("takes") or []) if isinstance(t, dict)]
        if takes:
            seat_of = {"drop": "drop_voice", "manager": "manager_voice",
                       "news": "news_voice"}
            used = {seat_of.get(str(t.get("who") or ""), str(t.get("who") or ""))
                    for t in takes}
        else:
            used = set(old) - {"third"}     # a flat read is never the guest's
        return bool(changed & used)
    except Exception:  # noqa: BLE001
        return False
'''


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    assert src.count(OLD) == 1, "anchor %d" % src.count(OLD)
    out = src.replace(OLD, NEW)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (1 edit)")
        return
    shutil.copy(path, "/tmp/app.py.bak-cast-seats")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()

"""[pic-retime] a resumed clip MOVES its queued sting pictures; it does not add twins.

2026-09-30, after [resume-heard]: a relaunched tablet resumed a clip ~30 s
later than its first page had it, and two stings showed their picture twice
- once ~30 s before the sound, once on it. At its first `playing` a page has
every sting picture of the delivery rung, stamped for the timeline it was
playing; the relaunched page's re-ring stamped the rest again for the new
one, and the tube held both.

The tube already re-times what it has queued: /api/dj/video carries
`reservation_updates` (delivery id -> broadcast_ms) and sfx-tv.js moves any
queued clip whose delivery_id is in it. A silent picture is never acknowledged
by the tube (sfx-tv.js: `|| clip.silent_picture) return`), so it can carry an
id of its own: `pic:<line id>`. A re-ring now moves the queued picture -
the ring entry and a reservation update - and appends only a picture that was
never rung.

Usage (ON THE HOST): python3 tools/picture_retime_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[pic-retime]"

EDITS = [
    ("carry-id",
     '''    if clip.get("line"):                   # [sfxseen] the script row this picture is
        rung["line"] = str(clip.get("line"))[:80]
''',
     '''    if clip.get("line"):                   # [sfxseen] the script row this picture is
        rung["line"] = str(clip.get("line"))[:80]
    if clip.get("delivery_id"):            # [pic-retime] so a re-timing can move it
        rung["delivery_id"] = str(clip.get("delivery_id"))[:80]
''', 1),
    ("ring",
     '''def _sfx_cadence_pictures(rows, starts_at: float) -> None:
    """Ring a silent picture at the audible board row's measured offset."""
    for row in rows:
        key = str(row.get("sfx_video_id") or "")
        if not key:
            continue
        page_picture_append({''',
     '''def _sfx_cadence_pictures(rows, starts_at: float, retime: bool = False) -> None:
    """Ring a silent picture at the audible board row's measured offset.
    [pic-retime] `retime`: a picture already rung for the row is MOVED (its
    ring entry and a reservation update the sets apply to what they hold)."""
    for row in rows:
        key = str(row.get("sfx_video_id") or "")
        if not key:
            continue
        pic_id = "pic:" + str(row.get("id") or key)
        at_ms = int((starts_at + float(row.get("from") or 0)) * 1000)
        if retime:
            moved = False
            for held in list(_RADIO.get("voice_clips") or []):
                if held.get("delivery_id") == pic_id:
                    held["broadcast_ms"] = at_ms
                    moved = True
            if moved:
                _PAGE_RESERVATION_UPDATES[pic_id] = at_ms
                try:
                    floor = (time.time() - 120.0) * 1000
                    for old in [k for k, v in _PAGE_RESERVATION_UPDATES.items()
                                if str(k).startswith("pic:") and float(v or 0) < floor]:
                        _PAGE_RESERVATION_UPDATES.pop(old, None)
                except Exception:  # noqa: BLE001
                    pass
                continue
        page_picture_append({
            "delivery_id": pic_id,                # [pic-retime]''', 1),
    ("re-ring",
     '''                    if delivery.get("sfx_pictures_rung") != listener:   # [resume-heard] per page
                        pending = [row for row in stream["rows"]
                                   if float(row.get("until") or 0) > position]
                        _sfx_cadence_pictures(pending, now - position)
                        delivery["sfx_pictures_rung"] = listener
''',
     '''                    if delivery.get("sfx_pictures_rung") != listener:   # [resume-heard] per page
                        pending = [row for row in stream["rows"]
                                   if float(row.get("until") or 0) > position]
                        _sfx_cadence_pictures(pending, now - position,      # [pic-retime] move, not twin
                                              retime=bool(delivery.get("sfx_pictures_rung")))
                        delivery["sfx_pictures_rung"] = listener
''', 1),
]


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    out = src
    for name, old, new, count in EDITS:
        assert out.count(old) == count, "%s: anchor found %d times" % (name, out.count(old))
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (%d edits)" % len(EDITS))
        return
    shutil.copy(path, "/tmp/app.py.bak-pic-retime")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()

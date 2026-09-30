"""[seg-tz] a kept Pine Cam segment's start is read in the HOST's clock.

The supervisor (tools/pinelink.py, root on the host) names the five-minute
footage with strftime in the host's local time - CST, UTC-6 all year - and this
container keeps CDT (UTC-5). Parsed here as local time, every segment started an
hour off: measured 2026-09-30 05:32 host / 06:32 container, the segment being
written was named 05-28-12. A cut asked for "now" (the box's record button, and
the album cut's mp4) covered the wrong hour or came out empty.

pinelink.py writes its UTC offset into state.json (`tz_offset`, seconds east of
UTC); the station reads names with it. Until the supervisor has written one, the
offset is inferred from the newest closed segment (its mtime is its end).

Usage (ON THE HOST): python3 tools/seg_tz_patch.py --check|--apply
"""
import ast
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = "[seg-tz]"

HELPER_AT = '''PINELINK_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
'''
HELPER = '''PINELINK_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_PINELINK_TZ_MEMO: dict[str, Any] = {"at": 0.0, "off": None}


def _pinelink_host_offset() -> int | None:
    """[seg-tz] the host's UTC offset (seconds east): state.json's `tz_offset`,
    else inferred from the newest closed segment, else None (read as local)."""
    now = time.time()
    if now - float(_PINELINK_TZ_MEMO["at"]) < 60:
        return _PINELINK_TZ_MEMO["off"]
    off = None
    try:
        got = json.loads(PINELINK_STATE.read_text())
        if isinstance(got, dict) and isinstance(got.get("tz_offset"), (int, float)):
            off = int(got["tz_offset"])
    except Exception:  # noqa: BLE001
        off = None
    if off is None:
        try:
            import calendar
            from datetime import datetime as _dt
            segs = sorted(p for p in pinelink_clips_dir().glob("*.mp4")
                          if re.match(r"^\\d{4}-\\d\\d-\\d\\d_\\d\\d-\\d\\d-\\d\\d$", p.stem))
            if len(segs) >= 2:
                p = segs[-2]                      # closed: its mtime is its end
                naive = _dt.strptime(p.stem, "%Y-%m-%d_%H-%M-%S")
                start = p.stat().st_mtime - 300.0
                off = int(round((calendar.timegm(naive.timetuple()) - start) / 900.0) * 900)
        except Exception:  # noqa: BLE001
            off = None
    _PINELINK_TZ_MEMO.update({"at": now, "off": off})
    return off


def pinelink_segment_epoch(stem: str) -> float | None:
    """[seg-tz] a kept segment's start (epoch), from its name, in the host's clock."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    try:
        naive = _dt.strptime(str(stem), "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return None
    off = _pinelink_host_offset()
    if off is None:
        return naive.timestamp()
    return naive.replace(tzinfo=_tz(_td(seconds=off))).timestamp()
'''

APP = [
    (HELPER_AT, HELPER, 1),
    ('''        try:
            at = _dt.strptime(
                f.stem, "%Y-%m-%d_%H-%M-%S").timestamp()
        except Exception:  # noqa: BLE001
            continue
        want.append((at, f))
''', '''        at = pinelink_segment_epoch(f.stem)             # [seg-tz] the host's clock
        if at is None:
            continue
        want.append((at, f))
''', 1),
    ('''        try:
            from datetime import datetime as _dt
            return _dt.strptime(m.group(1), "%Y-%m-%d_%H-%M-%S").timestamp()
        except Exception:  # noqa: BLE001
            pass
''', '''        got = pinelink_segment_epoch(m.group(1))       # [seg-tz]
        if got is not None:
            return got
''', 1),
]

LINK = [
    ('''            "crop": crop,                                   # [pincrop]
''', '''            "crop": crop,                                   # [pincrop]
            # [seg-tz] the clock the segment names are written in
            "tz_offset": int(time.localtime().tm_gmtoff),
''', 1),
]


def patch(path, edits, mode):
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    out = src
    for old, new, n in edits:
        got = out.count(old)
        assert got == n, "%s: %r found %d, want %d" % (path, old[:60], got, n)
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready")
        return
    shutil.copy(path, "/tmp/%s.bak-seg-tz" % os.path.basename(path))
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    mode = sys.argv[1]
    patch(ROOT + "/app.py", APP, mode)
    patch(ROOT + "/tools/pinelink.py", LINK, mode)

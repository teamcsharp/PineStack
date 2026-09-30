"""[station-pulse] GET /api/station/pulse - the pressure bar and the marquee.

Usage (ON THE HOST): python3 tools/station_pulse_patch.py --check|--apply
"""
import ast
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = "[station-pulse]"
EDITS = [
    ('''import levels as _levels                   # [levels-one] the one set of levels, on the station
''', '''import levels as _levels                   # [levels-one] the one set of levels, on the station
import station_pulse as _pulse             # [station-pulse] the pressure bar and the marquee
''', 1),
    ('''@app.get("/api/slideshow/media/{filename}")
''', '''# --- [station-pulse] THE STATION'S PRESSURE AND WHAT IT IS DOING, ONE READ ---------
# The bank's read-ahead ledger, the writers' rooms and the voice queue, folded by
# station_pulse.pulse(); memoised two seconds (every screen reads it every five).
_PULSE_MEMO: dict[str, Any] = {"at": 0.0, "got": None}


@app.get("/api/station/pulse")
async def station_pulse_api(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_read_auth(authorization)
    now = time.time()
    if now - float(_PULSE_MEMO["at"]) < 2.0 and _PULSE_MEMO["got"]:
        return _PULSE_MEMO["got"]
    try:
        bank = await api_bank(minutes=60, authorization=authorization)
    except Exception:  # noqa: BLE001
        bank = {}
    try:
        cup = cupboard_state()
    except Exception:  # noqa: BLE001
        cup = {}
    try:
        vq = _emotion.queue_rows()
    except Exception:  # noqa: BLE001
        vq = []
    got = _pulse.pulse(bank, cup, vq, now)
    _PULSE_MEMO.update({"at": now, "got": got})
    return got


@app.get("/api/slideshow/media/{filename}")
''', 1),
]

if __name__ == "__main__":
    mode = sys.argv[1]
    path = ROOT + "/app.py"
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        sys.exit(0)
    out = src
    for old, new, n in EDITS:
        got = out.count(old)
        assert got == n, "%r found %d, want %d" % (old[:60], got, n)
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready")
        sys.exit(0)
    shutil.copy(path, "/tmp/app.py.bak-station-pulse")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")

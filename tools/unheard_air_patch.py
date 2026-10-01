"""[unheard-air] lines go out and nobody hears them: the orchestrator says so,
and gives the air back to the device that plays out loud.

2026-09-30, the operator: "Check into why there's no dialogue being spoken on
the broadcast right now. The orchestrator doesnt even appear to care about
this." Measured: nobody owned the air. The PineTab (play=true) reloaded under
a new listener id; #1241 moved the air to it; the fresh page confirmed no
clip, so #1332 took the air away and #1332c barred it from asking again. With
the desk's play off and routing "here", every line was published to no one -
10.6 min of silence at 18:16, 22.4 min at 14:26 - while the station counted
"published" as done. "Build it" - "yes."

unheard_air_watch (every 15 s): while the station is on air and routed to the
pages, when at least three people's lines were due in the last two minutes and
NOT ONE was confirmed heard (a page's heard ack, or the box's own "box"/"both"),
it is a fault:
  - it is said on the orchestrator's line (pipeline "air" -> the marquee) and
    kept on /api/dj as `unheard`;
  - the air goes to the live listener at the device whose play switch is on
    (the PineTab first), and that device's #1332c rest is lifted: the rest
    exists so a broken page cannot grab the air again and again, and it must
    never be the thing that leaves the whole house silent.
At most one rescue per UNHEARD_REST_S; a rescue that does not bring a heard
line is said again at the next rest, never looped.

Usage (ON THE HOST): python3 tools/unheard_air_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[unheard-air]"

EDITS = [
    ("watch",
     '''async def gap_keeper() -> None:
''',
     '''UNHEARD_AIR_S = 120.0
UNHEARD_REST_S = 180.0
UNHEARD_TICK_S = 15.0
UNHEARD_WHO = ("dj", "cohost", "third", "caller", "manager", "guest")
_UNHEARD: dict[str, Any] = {"rescued_at": 0.0, "since": 0.0, "last": None}


def unheard_air_check(now: float | None = None) -> dict[str, Any] | None:
    """[unheard-air] people's lines were due and none was heard - or None."""
    now = float(now or time.time())
    if not _RADIO.get("on") or radio_paused():
        return None
    if str(_RADIO.get("voice_to") or "") not in ("here", "both"):
        return None
    rows = [r for r in list(_RADIO.get("chat") or [])[-240:]
            if isinstance(r, dict) and str(r.get("who") or "") in UNHEARD_WHO]

    def at(r: dict[str, Any]) -> float:
        return float(r.get("air_at") or r.get("ts") or 0)

    due = [r for r in rows if now - UNHEARD_AIR_S - 90 <= at(r) <= now - 20
           and str(r.get("aired") or "") in AIR_PUBLICATION_STATES]
    if len(due) < 3 or now - min(at(r) for r in due) < UNHEARD_AIR_S:
        return None
    heard = [r for r in rows if now - at(r) <= UNHEARD_AIR_S + 90
             and (r.get("heard_ack_at") or str(r.get("aired") or "") in ("box", "both"))]
    if heard:
        return None
    return {"lines": len(due), "since": min(at(r) for r in due), "owner": audio_owner()}


def unheard_air_rescue(check: dict[str, Any]) -> str:
    """[unheard-air] the air to the device that plays out loud, its rest lifted."""
    try:
        rows = terminal_rows()
    except Exception:  # noqa: BLE001
        rows = {}
    for key in ("pinetab", "desktop"):
        row = rows.get(key) if isinstance(rows, dict) else None
        if not isinstance(row, dict) or not row.get("play"):
            continue
        live = _listener_for_terminal(row, key)
        if not live:
            continue
        try:
            if air_hushed(live):
                continue
        except Exception:  # noqa: BLE001
            pass
        _OWNER_DEAF.pop(_owner_deaf_key(live), None)
        _AUDIO_OWNER.clear()
        _AUDIO_OWNER.update({"who": live, "at": time.time()})
        return "%s (%s)" % (str(row.get("name") or key), live)
    return ""


async def unheard_air_watch() -> None:
    """[unheard-air] every UNHEARD_TICK_S: nobody hearing the show is a fault."""
    await asyncio.sleep(45)
    while True:
        await asyncio.sleep(UNHEARD_TICK_S)
        try:
            now = time.time()
            got = unheard_air_check(now)
            if not got:
                if _UNHEARD.get("since"):
                    pipeline_log("air", "the show is being heard again after %d s unheard [unheard-air]"
                                 % int(now - float(_UNHEARD["since"])))
                _UNHEARD.update(since=0.0, last=None)
                continue
            if not _UNHEARD.get("since"):
                _UNHEARD["since"] = float(got["since"])
            _UNHEARD["last"] = dict(got, at=now)
            if now - float(_UNHEARD.get("rescued_at") or 0) < UNHEARD_REST_S:
                continue
            _UNHEARD["rescued_at"] = now
            orch_turn("unheard_air", "lines are going out and nobody is hearing them")
            gave = unheard_air_rescue(got)
            pipeline_log("air", "NOBODY IS HEARING THE SHOW: %d lines went out in the last %d s and not one was "
                         "heard (the air was %s). %s [unheard-air]"
                         % (got["lines"], int(now - float(got["since"])),
                            ("with " + got["owner"]) if got.get("owner") else "owned by no one",
                            ("The air goes to " + gave + ".") if gave
                            else "No device set to play out loud is here to take it."))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            pipeline_log("air", "the unheard-air watch faulted (%s) [unheard-air]" % type(exc).__name__)


async def gap_keeper() -> None:
'''),
    ("start",
     '''    radio_worker_start("gap", gap_keeper)
''',
     '''    radio_worker_start("gap", gap_keeper)
    radio_worker_start("unheard", unheard_air_watch)              # [unheard-air]
'''),
    ("registry",
     '''    ("gap_keeper", "records and closes measured holes in the air",
     "every 60s"),
''',
     '''    ("gap_keeper", "records and closes measured holes in the air",
     "every 60s"),
    ("unheard_air", "notices lines going out that nobody hears, and gives the air back",
     "every 15s"),                                                          # [unheard-air]
'''),
]


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    out = src
    for label, old, new in EDITS:
        n = out.count(old)
        assert n == 1, "%s: anchor found %d times" % (label, n)
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (%d edits)" % len(EDITS))
        return
    shutil.copy(path, "/tmp/app.py.bak-unheard-air")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()

"""[smart-reinit] "Get the broadcast back": diagnose first, the smallest cure, then ask.

The operator, 2026-09-30: "Whenever I bring up the broadcast and I can't hear
the music or the DJs, I just click this button. So I need this button to
intelligently be able to tell what's needing to be done so it does that and
doesn't reinitialize things that don't need to be reinitialized ... then query
me and ask me if the broadcast is working suitably and then from there into
troubleshooting before advancing to more advanced and intense of steps."

  app.py  GET  /api/broadcast/diagnose?listener=&device=&hint=
               what the station knows, named (broadcast_doctor.station_findings)
               with how many earlier runs turned up the same fault
          POST /api/broadcast/reinit/log   one step of a run (symptoms,
               diagnosis, cure, answer) into data/air_fixes.jsonl, event
               "reinit" - the file the air watchdog already keeps
          GET  /api/broadcast/reinit/log   the recent runs and the repeats

The cures are the station's existing roads: POST /api/broadcast/fix/{step}
(onair, relieve, stock, bank, flush, ... - the 13-rung ladder, unchanged) and
POST /api/radio/solo. Nothing here changes a level, a volume or a setting.

Usage (ON THE HOST): python3 tools/smart_reinit_patch.py --check|--apply app.py
--check exits 0 ready, 2 applied, 1 broken. Anchors asserted unique; LF; atomic."""
from __future__ import annotations

import ast
import os
import shutil
import sys
from pathlib import Path

MARK = "# [smart-reinit] THE DIAGNOSIS BEFORE THE CURE"

ANCHOR = '''    """#1208: fire one troubleshooting step and hand back its transcript."""
    require_auth(authorization)
    return await broadcast_step(str(step or "")[:32])
'''

INSERT = '''

''' + MARK + '''
#
# "I need this button to intelligently be able to tell what's needing to be
#  done so it does that and doesn't reinitialize things that don't need to be
#  reinitialized" (the operator, 2026-09-30). The station's half: what it
# knows about THIS listener, named, by broadcast_doctor.station_findings. The
# tablet adds what only it can measure and picks the smallest cure; the
# ladder above (broadcast_step) is unchanged and is where the cures live.
try:
    import broadcast_doctor as _broadcast_doctor
except Exception:  # noqa: BLE001
    _broadcast_doctor = None


def broadcast_doctor_snapshot(listener: str = "",
                              device: str = "") -> dict[str, Any]:
    """[smart-reinit] Everything the station knows about why THIS listener
    may be silent. Reads state only - no lock, no write, nothing aired -
    and every read is its own try, so one broken road never hides the rest."""
    snap: dict[str, Any] = {"at": time.time(), "listener": listener,
                            "device": device}

    def _take(key: str, fn: Any, default: Any = None) -> None:
        try:
            snap[key] = fn()
        except Exception:  # noqa: BLE001
            snap[key] = default

    snap["on"] = bool(_RADIO.get("on"))
    _take("paused", lambda: bool(radio_paused()), False)
    _take("paused_for_s", lambda: (float(radio_paused_for() or 0)
                                   if snap.get("paused") else 0.0), 0.0)
    _track = _RADIO.get("now") or {}
    snap["playing"] = bool(_track) and not snap.get("paused")
    snap["title"] = str((_track or {}).get("title") or "")[:120]
    _take("music_here", lambda: bool(page_carries_music()), None)
    snap["routing"] = {"music": str(_RADIO.get("music_to") or "here"),
                       "voice": str(_RADIO.get("voice_to") or "box"),
                       "reply": str(_RADIO.get("reply_to") or "box")}

    def _pulse() -> dict[str, Any]:
        got = pulse_report(600)
        _open = _PULSE.get("open") or {}
        return {"stalls": int(got.get("stalls") or 0),
                "worst_s": float(got.get("worst_s") or 0),
                "stalling_now": bool(_open) and float(
                    (_open or {}).get("seconds") or 0) >= 3.0,
                "reading": str(got.get("reading") or "")[:200]}
    _take("pulse", _pulse, {})
    _take("talk_quiet_s", lambda: round(float(talk_quiet_for() or 0), 1), 0.0)
    _wq: dict[str, Any] = {}
    try:
        _wq = why_quiet() or {}
    except Exception:  # noqa: BLE001
        _wq = {}
    snap["rounds_ready"] = int(((_wq.get("banked") or {}).get("rounds_ready"))
                               or 0)
    snap["consumer_why"] = str(((_wq.get("consumer") or {}).get("last_why"))
                               or "")[:120]
    snap["why_quiet"] = str(_wq.get("why") or "")[:300]
    _take("up_s", lambda: round(time.time() - _BUILD_MS / 1000.0, 1), 0.0)

    _roster: list[dict[str, Any]] = []
    try:
        for _r in listener_roster():
            _ids = [str(x) for x in (_r.get("ids") or [])]
            _roster.append({
                "listener": str(_r.get("listener") or ""),
                "ids": _ids, "what": str(_r.get("what") or ""),
                "device": str(_r.get("device") or ""),
                "owns_air": bool(_r.get("owns_air")),
                "hushed": bool(air_hushed(str(_r.get("listener") or "")))})
    except Exception:  # noqa: BLE001
        pass
    snap["roster"] = _roster
    if listener and not device:
        for _r in _roster:
            if listener == _r["listener"] or listener in _r["ids"]:
                device = _r["device"]
                snap["device"] = device
                break
    _row: dict[str, Any] = {}
    try:
        if device:
            _row = dict(terminal_rows().get(device) or {})
        if not _row and listener:
            _row = terminal_for_listener(listener)
    except Exception:  # noqa: BLE001
        _row = {}
    snap["terminal"] = ({"name": str(_row.get("name") or device or ""),
                         "play": bool(_row.get("play"))} if _row else {})
    _take("owner", lambda: str(audio_owner() or ""), "")
    snap["owner_what"] = next(
        (r["what"] for r in _roster
         if snap["owner"] and (snap["owner"] == r["listener"]
                               or snap["owner"] in r["ids"])), "")
    _take("hushed", lambda: bool(air_hushed(listener)) if listener else False,
          False)

    def _triage() -> dict[str, Any]:
        got = broadcast_triangulate() or {}
        return {"cause": str(got.get("cause") or ""),
                "why": str(got.get("why") or "")[:300],
                "listener": str(got.get("listener") or "")}
    _take("triage", _triage, {})
    return snap


@app.get("/api/broadcast/diagnose")
async def broadcast_diagnose_api(
    listener: str = "", device: str = "", hint: str = "",
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[smart-reinit] Name the fault before touching anything.

    `listener` is the asking page's own id, `device` its terminals key and
    `hint` the operator's answer to "Is the broadcast working now?"
    (no_music, no_djs, nothing, other). Read-only."""
    require_read_auth(authorization)
    if _broadcast_doctor is None:
        raise HTTPException(status_code=503,
                            detail="broadcast_doctor.py is not importable")
    snap = broadcast_doctor_snapshot(str(listener or "")[:64],
                                     str(device or "")[:32])
    found = _broadcast_doctor.station_findings(snap, hint)
    try:
        _rows = await asyncio.to_thread(
            _broadcast_doctor.read_runs, AIR_FIXES_PATH,
            time.time() - _broadcast_doctor.REPEAT_WINDOW_S)
        _seen = _broadcast_doctor.repeats(_rows)
    except Exception:  # noqa: BLE001
        _seen = {}
    for _f in found:
        _f["seen_before"] = int(_seen.get(_f["key"], 0))
    return {"ok": True, "at": time.time(), "hint": _broadcast_doctor.hint_of(hint),
            "findings": found, "say": _broadcast_doctor.say_all(found),
            "snapshot": snap}


@app.post("/api/broadcast/reinit/log")
async def broadcast_reinit_log_api(
    payload: dict[str, Any] | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[smart-reinit] One step of one run: the symptoms (hint), what was
    found, the cure and the operator's answer. Appended to air_fixes.jsonl
    beside the watchdog's own rows, so a repeated fault is countable."""
    require_auth(authorization)
    if _broadcast_doctor is None:
        raise HTTPException(status_code=503,
                            detail="broadcast_doctor.py is not importable")
    row = _broadcast_doctor.log_row(payload or {})

    def _write() -> None:
        AIR_FIXES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AIR_FIXES_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\\n")
    try:
        await asyncio.to_thread(_write)
    except Exception as err:  # noqa: BLE001
        return {"ok": False, "why": "could not write the run log: %s" % err}
    try:
        pipeline_log("air", "[smart-reinit] %s: found %s; %s%s" % (
            row["device"] or "a terminal",
            ", ".join(row["findings"]) or "nothing",
            row["did"][:160] or row["cure"] or "no cure",
            ("; answer: " + row["answer"]) if row["answer"] else ""))
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "row": row}


@app.get("/api/broadcast/reinit/log")
async def broadcast_reinit_runs_api(
    days: float = 7.0,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[smart-reinit] The recent runs of the button and which faults keep
    coming back."""
    require_read_auth(authorization)
    if _broadcast_doctor is None:
        raise HTTPException(status_code=503,
                            detail="broadcast_doctor.py is not importable")
    rows = await asyncio.to_thread(
        _broadcast_doctor.read_runs, AIR_FIXES_PATH,
        time.time() - max(0.1, min(60.0, float(days or 7))) * 86400.0)
    return {"ok": True, **_broadcast_doctor.summary(rows)}
'''


def check(text: str) -> tuple[int, list[str]]:
    if MARK in text:
        return 2, []
    missing = []
    if text.count(ANCHOR) != 1:
        missing.append("anchor broadcast_fix_api x%d" % text.count(ANCHOR))
    for name in ("def broadcast_triangulate(", "def why_quiet(",
                 "def pulse_report(", "def listener_roster(",
                 "def air_hushed(", "def terminal_for_listener(",
                 "AIR_FIXES_PATH = data_path(", "def page_carries_music(",
                 "def talk_quiet_for(", "_BUILD_MS = "):
        if name not in text:
            missing.append(name)
    return (1 if missing else 0), missing


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("--check", "--apply"):
        print(__doc__.strip().splitlines()[-2])
        return 1
    path = Path(argv[2])
    raw = path.read_bytes().decode("utf-8")
    text = raw.replace("\r\n", "\n")
    code, missing = check(text)
    if argv[1] == "--check":
        print({0: "ready", 2: "applied", 1: "BROKEN: " + "; ".join(missing)}[code])
        return code
    if code == 2:
        print("already applied")
        return 2
    if code == 1:
        print("BROKEN: " + "; ".join(missing))
        return 1
    new = text.replace(ANCHOR, ANCHOR + INSERT, 1)
    ast.parse(new)
    assert "\r" not in new
    tmp = path.with_name(path.name + ".smart-reinit.tmp")
    tmp.write_bytes(new.encode("utf-8"))
    shutil.copymode(path, tmp)
    os.replace(tmp, path)
    code, _ = check(new)
    print("applied" if code == 2 else "APPLY DID NOT TAKE")
    return 0 if code == 2 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

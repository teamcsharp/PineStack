#!/usr/bin/env python3
"""[cambattery] the Pine Cam's battery, read by the station.

    python3 edit_cambattery_station.py --check app.py   # 0 ready, 2 applied, 1 anchors missing
    python3 edit_cambattery_station.py --apply app.py

Two edits to app.py, both marker-idempotent ([cambattery]):
  1. a block after pinelink_state(): the poller, the ledger, the view;
  2. one line inside pinelink_state(): `got["battery"] = pinelink_battery(got)`,
     so the existing GET /api/pinelink/state carries the reading.
CRLF-aware (writes the file's own newline back), atomic.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

MARK = "[cambattery]"

# ---------------------------------------------------------------- edit 1
A1 = ('    got["playlist"] = "/api/pinelink/live/index.m3u8"\n'
      '    return got\n')
N1 = ('    got["playlist"] = "/api/pinelink/live/index.m3u8"\n'
      '    # [cambattery] the camera\'s own battery level, polled only while\n'
      '    # the link is live and fresh; see pinelink_battery().\n'
      '    got["battery"] = pinelink_battery(got)\n'
      '    return got\n')

# ---------------------------------------------------------------- edit 2
A2 = '\n\nPINELINK_IFACE = "wlx984827b6b478"'

BLOCK = r'''

# ------------------------------------------------------------ [cambattery]
# "If we are able to query the battery on the pine cam and get the battery
# level, display a battery meter ... in the top left corner of the pine cam.
# So that way I can see how much battery's in the camera at all times and
# know how long I have left in the stream."
#
# MEASURED 2026-09-29 against the camera itself (firmware PFXC_V4.28, "Nvt
# RTSP" on :554, `hfs/1.00.000` on :80 - a Novatek body cam). Its web API
# answers a READ:
#     GET http://192.168.1.254/?custom=1&cmd=3019
#     -> <Function><Cmd>3019</Cmd><Status>0</Status><Value>3</Value></Function>
# That is the only battery fact it gives, and it is a LEVEL, not a percent
# (cmd 3014, the whole status dump, carries no battery at all). Novatek's
# table: 0 full, 1 med, 2 low, 3 empty, 4 exhausted, 5 charging.
#
# So nothing here invents a percentage. The meter shows the camera's own
# level as a word and as bars of four; `pct` is only the level's nominal
# share, used for the fill and for the thresholds the operator asked for
# (amber at 30 = "low", red at 15 = "last bar", pulsing at 10 or under =
# "empty"). Time left is measured, not guessed: it needs one whole level
# seen from its first reading to its last (a level drop to a level drop),
# and until then it is absent rather than made up.
#
# It asks the camera once every 45 s, on its own thread, and only while
# the link is live and fresh - the station is host-networked and the
# camera's 192.168.1.0/24 is routed out of the spare radio. The reading and
# its ledger live in data/pinelink_battery.json, so a restart keeps the
# clock of the level it is on and never repeats the low-battery notice.
from threading import Lock as _CambattLock, Thread as _CambattThread

PINELINK_BATTERY_FILE = data_path("pinelink_battery.json")
PINELINK_BATTERY_URL = "http://192.168.1.254/?custom=1&cmd=3019"
PINELINK_BATTERY_EVERY = 45.0     # the brief: every 30-60 s, only while live
PINELINK_BATTERY_STALE = 180.0    # older than three minutes reads "stale"
PINELINK_BATTERY_GAP = 300.0      # blind this long: that level's clock is void
PINELINK_BATTERY_CHARGING = 5
# code -> (Novatek name, the word shown, bars of 4, nominal %, tone)
PINELINK_BATTERY_LEVELS: dict[int, tuple[str, str, int, int, str]] = {
    0: ("full", "full", 4, 100, "ok"),
    1: ("med", "half", 3, 60, "ok"),
    2: ("low", "low", 2, 30, "amber"),
    3: ("empty", "last bar", 1, 15, "red"),
    4: ("exhausted", "empty", 0, 5, "red"),
}
PINELINK_BATTERY_LOW = 3          # the level that posts the one notice
_PINELINK_BATT: dict[str, Any] = {"loaded": False, "busy": False,
                                  "tried_at": 0.0}
_PINELINK_BATT_LOCK = _CambattLock()
_PINELINK_BATT_KEEP = ("code", "at", "ok_at", "hist", "noted", "error")


def _pinelink_battery_load() -> None:
    if _PINELINK_BATT.get("loaded"):
        return
    _PINELINK_BATT["loaded"] = True
    try:
        got = json.loads(PINELINK_BATTERY_FILE.read_text())
    except Exception:  # noqa: BLE001 - never read yet is not a fault
        return
    if isinstance(got, dict):
        for k in _PINELINK_BATT_KEEP:
            if k in got:
                _PINELINK_BATT[k] = got[k]


def _pinelink_battery_save() -> None:
    try:
        doc = {k: _PINELINK_BATT.get(k) for k in _PINELINK_BATT_KEEP}
        tmp = PINELINK_BATTERY_FILE.with_name(PINELINK_BATTERY_FILE.name + ".tmp")
        tmp.write_text(json.dumps(doc))
        os.replace(tmp, PINELINK_BATTERY_FILE)
    except Exception as err:  # noqa: BLE001
        _PINELINK_BATT["error"] = "the reading was not saved: %s" % str(err)[:120]


def pinelink_battery_parse(body: str) -> int | None:
    """The level out of a cmd=3019 answer, or None for anything else -
    a refused command (Status not 0) or a value off the table is not a
    battery reading and is never painted as one."""
    st = re.search(r"<Status>\s*(-?\d+)\s*</Status>", body or "")
    val = re.search(r"<Value>\s*(-?\d+)\s*</Value>", body or "")
    if not st or not val or int(st.group(1)) != 0:
        return None
    code = int(val.group(1))
    if code == PINELINK_BATTERY_CHARGING or code in PINELINK_BATTERY_LEVELS:
        return code
    return None


def _pinelink_battery_left(hist: list, now: float) -> tuple[float | None, int]:
    """Seconds left on the battery, from the levels this ledger watched
    whole. A step counts only when it began at a seen drop (`edge`) and
    was not blind for part of it; the estimate is the mean of the last
    two such steps times the levels still to go, less the time already
    spent on this one. (None, 0) until one whole level has been seen."""
    steps: list[float] = []
    for a, b in zip(hist, hist[1:]):
        try:
            ca, cb = int(a["code"]), int(b["code"])
            if a.get("edge") and not a.get("blind") and cb > ca:
                steps.append((float(b["at"]) - float(a["at"])) / (cb - ca))
        except Exception:  # noqa: BLE001
            continue
    steps = [s for s in steps if s > 0]
    if not steps or not hist:
        return None, 0
    recent = steps[-2:]
    step = sum(recent) / len(recent)
    cur = hist[-1]
    togo = max(0, 4 - int(cur["code"]))
    return max(0.0, togo * step - (now - float(cur["at"]))), len(steps)


def _pinelink_battery_say_left(s: float) -> str:
    m = int(round(s / 60.0))
    if m < 2:
        return "a minute or two"
    h, m = divmod(m, 60)
    return ("%d h %d m" % (h, m)) if h else ("%d m" % m)


def pinelink_battery_view(now: float | None = None) -> dict[str, Any]:
    """What every surface paints. Read-only; safe without the lock."""
    now = float(now or time.time())
    B = _PINELINK_BATT
    code, at = B.get("code"), float(B.get("at") or 0)
    base = {"source": "camera cmd 3019 (Novatek level)", "every_s": PINELINK_BATTERY_EVERY,
            "error": str(B.get("error") or "")}
    if code is None or not at:
        base.update(ok=False, say="Pine Cam battery: not read yet"
                    + (" - " + base["error"] if base["error"] else ""))
        return base
    code = int(code)
    age = max(0.0, now - at)
    stale = age > PINELINK_BATTERY_STALE
    if code == PINELINK_BATTERY_CHARGING:
        doc = {"key": "charging", "word": "charging", "bars": None, "pct": None,
               "tone": "ok", "charging": True, "pulse": False}
        left, steps = None, 0
    else:
        key, word, bars, pct, tone = PINELINK_BATTERY_LEVELS[code]
        doc = {"key": key, "word": word, "bars": bars, "pct": pct, "tone": tone,
               "charging": False, "pulse": pct <= 10}
        left, steps = _pinelink_battery_left(list(B.get("hist") or []), now)
    doc.update(base)
    doc.update(ok=True, code=code, at=at, age_s=round(age, 1), stale=stale,
               approx=True, left_s=(round(left) if left is not None else None),
               left_say=(_pinelink_battery_say_left(left) if left is not None else ""),
               steps=steps, low=bool(not doc["charging"] and code >= PINELINK_BATTERY_LOW))
    ago = ("%d s" % age) if age < 90 else ("%d min" % round(age / 60.0))
    if doc["charging"]:
        say = "Pine Cam battery: charging (camera level 5)"
    else:
        say = ("Pine Cam battery: %s - the camera's level %d of 0-4 (it reports "
               "levels, not a percentage)" % (doc["word"], code))
        say += (". About %s left, from %d whole level%s watched" % (
            doc["left_say"], steps, "" if steps == 1 else "s")) if left is not None \
            else ". Time left: not measured yet (needs one whole level watched)"
    doc["what"] = say              # the reading without its age, for a page's own clock
    say += ". Read %s ago%s." % (ago, " - STALE" if stale else "")
    if base["error"] and stale:
        say += " Last try: " + base["error"]
    doc["say"] = say
    return doc


def pinelink_battery_note(code: int, now: float) -> None:
    """Fold one reading into the ledger. Caller holds the lock.

    hist is the levels seen this discharge, one row per level: a rise
    (a fresh battery) or charging starts a new one and re-arms the notice;
    a level reached across a blind gap is not an edge; a level we were
    blind on for a while is `blind`, so its length is never a step."""
    B = _PINELINK_BATT
    hist = [dict(h) for h in (B.get("hist") or []) if isinstance(h, dict)]
    ok_at = float(B.get("ok_at") or 0)
    gap = bool(ok_at) and (now - ok_at) > PINELINK_BATTERY_GAP
    if code == PINELINK_BATTERY_CHARGING:
        hist = []
        B["noted"] = False
    elif hist and code < int(hist[-1]["code"]):
        hist = [{"code": code, "at": now, "edge": False}]
        B["noted"] = False
    elif not hist or code != int(hist[-1]["code"]):
        hist.append({"code": code, "at": now, "edge": bool(hist) and not gap})
        hist = hist[-8:]
    elif gap:
        hist[-1]["blind"] = True
    B.update(code=code, at=now, ok_at=now, error="", hist=hist)
    if (code != PINELINK_BATTERY_CHARGING and code >= PINELINK_BATTERY_LOW
            and not B.get("noted")):
        B["noted"] = True
        v = pinelink_battery_view(now)
        left = (", about %s left" % v["left_say"]) if v.get("left_s") is not None else ""
        try:
            note_action("Pine Cam battery on its %s%s - swap the battery or plug the "
                        "camera in before the stream drops" % (v.get("word"), left))
        except Exception:  # noqa: BLE001
            pass


def _pinelink_battery_poll() -> None:
    import urllib.request
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(PINELINK_BATTERY_URL, timeout=4.0) as r:
            body = r.read(4096).decode("utf-8", "replace")
        code = pinelink_battery_parse(body)
        with _PINELINK_BATT_LOCK:
            if code is None:
                _PINELINK_BATT["error"] = "the camera answered without a battery level"
            else:
                pinelink_battery_note(code, time.time())
            _pinelink_battery_save()
    except Exception as err:  # noqa: BLE001
        with _PINELINK_BATT_LOCK:
            _PINELINK_BATT["error"] = "the camera did not answer: %s" % str(err)[:120]
            _pinelink_battery_save()
    finally:
        _PINELINK_BATT["busy"] = False


def pinelink_battery(link: dict[str, Any] | None = None) -> dict[str, Any]:
    """The reading for /api/pinelink/state, and the kick for the next one.
    Costs a dict read and a clock compare; the camera is asked on a
    daemon thread at most once every PINELINK_BATTERY_EVERY seconds and
    only while `link` (the state this is folded into) is live and fresh."""
    _pinelink_battery_load()
    now = time.time()
    live = bool(link and link.get("state") == "live" and link.get("fresh"))
    if (live and not _PINELINK_BATT.get("busy")
            and now - float(_PINELINK_BATT.get("tried_at") or 0) >= PINELINK_BATTERY_EVERY):
        _PINELINK_BATT["busy"] = True
        _PINELINK_BATT["tried_at"] = now
        try:
            _CambattThread(target=_pinelink_battery_poll, name="pinelink-battery",
                           daemon=True).start()
        except Exception:  # noqa: BLE001
            _PINELINK_BATT["busy"] = False
    view = pinelink_battery_view(now)
    view["polling"] = live
    return view
'''


def patch(text: str) -> tuple[int, str, str]:
    """(code, new_text, say): 0 ready/applied, 2 already, 1 anchors missing."""
    if MARK in text:
        return 2, text, "already applied"
    miss = [n for n, a in (("pinelink_state return", A1), ("PINELINK_IFACE", A2))
            if text.count(a) != 1]
    if miss:
        return 1, text, "anchor missing or not unique: " + ", ".join(miss)
    out = text.replace(A1, N1, 1)
    out = out.replace(A2, BLOCK.rstrip("\n") + "\n" + A2, 1)
    return 0, out, "ok"


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    path = Path(argv[2])
    raw = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    code, out, say = patch(text)
    print("%s: %s" % (path, say))
    if code != 0 or argv[1] == "--check":
        return code
    if crlf:
        out = out.replace("\n", "\r\n")
    tmp = path.with_name(path.name + ".cambattery.tmp")
    tmp.write_bytes(out.encode("utf-8"))
    os.replace(tmp, path)
    print("%s: APPLIED" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

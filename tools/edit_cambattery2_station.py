#!/usr/bin/env python3
"""[cambattery2] the Pine Cam battery leads with TIME LEFT, learned per level.

    python3 edit_cambattery2_station.py --check app.py   # 0 ready, 2 applied, 1 anchors missing
    python3 edit_cambattery2_station.py --apply app.py

Needs the wave-BB [cambattery] block in app.py (07407f4). Replaces that block,
from its `# ---- [cambattery]` rule to the blank lines before `PINELINK_IFACE`,
with the one below. pinelink_state()'s `got["battery"] = pinelink_battery(got)`
line is kept as it is (same name, same signature). The ledger file
data/pinelink_battery.json is read as it stands and grows new keys.
CRLF-aware, atomic, marker-idempotent.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

MARK = "[cambattery2]"
V1_START = "\n# ------------------------------------------------------------ [cambattery]\n"
V1_END = "\n\n\nPINELINK_IFACE = "
V1_MUST = "def pinelink_battery(link"

BLOCK = r'''
# ------------------------------------------------------------ [cambattery]
# [cambattery2] THE PINE CAM BATTERY, AS TIME LEFT.
#
# "If we are able to query the battery on the pine cam ... display a battery
# meter ... know how long I have left in the stream." (wave BB) and then:
# "Instead of saying last bar, I would like a time estimate of how much time
# is left in the battery." The operator does not know the camera's runtime.
#
# WHAT THE CAMERA GIVES. Measured 2026-09-29 (firmware PFXC_V4.28, Novatek):
#     GET http://192.168.1.254/?custom=1&cmd=3019 -> <Status>0</Status><Value>N</Value>
# a LEVEL: 0 full, 1 med, 2 low, 3 empty, 4 exhausted, 5 charging. Never a
# percent, and while plugged in only "5" - no level, so time-to-full cannot
# be learned from it. On real hardware (wave BB): charging read 5; unplugged,
# the next reading was 3; about a minute later the camera dropped its own
# hotspot (auth to 5c:8e:8b:dd:fa:b1 timed out, pinelink went no-link). So on
# this firmware level 3 IS the end, and the camera goes dark rather than
# ever reporting 4.
#
# THE MODEL. How long the camera stays on each level while discharging:
#   * a cautious default, 90 min from full - full 30, half 27, low 20,
#     last bar 10, empty 3 (PINELINK_BATTERY_DEFAULT_S);
#   * learned from real discharges: a level watched from the reading that
#     first saw it drop in (`edge`) to the reading that saw the next level,
#     never blind for part of it, is that level's duration; and the level the
#     camera went DARK on is learned from its first reading to the last moment
#     the link was live (and becomes `dies_at`, the last level counted).
#     Each level keeps an exponentially smoothed mean (alpha 0.4) in
#     data/pinelink_battery.json, so restarts keep what was learned;
#   * time left = what is left of this level (its duration minus the time
#     already spent on it; first seen mid-level, half of it is assumed gone)
#     plus the whole of every level after it, down to `dies_at`. Under five
#     minutes it says "under 5 min" and never counts lower.
#   * "estimate" is shown until every level in that sum has real data.
#
# CAMERA WENT DARK. The link dropping while the last reading (from the
# live stretch that just ended) was on battery at level 3 or below reads
# "camera went dark - battery likely flat", keeps the last estimate and its
# age for the tooltip, and posts one notice.
#
# Polled every 45 s on its own thread, only while the link is live and
# fresh; the station is host-networked and the camera's 192.168.1.0/24
# leaves by the spare radio.
from threading import Lock as _CambattLock, Thread as _CambattThread

PINELINK_BATTERY_FILE = data_path("pinelink_battery.json")
PINELINK_BATTERY_URL = "http://192.168.1.254/?custom=1&cmd=3019"
PINELINK_BATTERY_EVERY = 45.0     # the brief: every 30-60 s, only while live
PINELINK_BATTERY_STALE = 180.0    # older than three minutes reads "stale"
PINELINK_BATTERY_GAP = 300.0      # blind this long: that level's clock is void
PINELINK_BATTERY_CHARGING = 5
# code -> (Novatek name, the word, bars of 4, nominal %, tone)
PINELINK_BATTERY_LEVELS: dict[int, tuple[str, str, int, int, str]] = {
    0: ("full", "full", 4, 100, "ok"),
    1: ("med", "half", 3, 60, "ok"),
    2: ("low", "low", 2, 30, "amber"),
    3: ("empty", "last bar", 1, 15, "red"),
    4: ("exhausted", "empty", 0, 5, "red"),
}
PINELINK_BATTERY_LOW = 3          # the level that posts the one notice
# [cambattery2] the cautious default: 90 minutes from full, by level
PINELINK_BATTERY_DEFAULT_S: dict[int, float] = {
    0: 30 * 60.0, 1: 27 * 60.0, 2: 20 * 60.0, 3: 10 * 60.0, 4: 3 * 60.0}
PINELINK_BATTERY_ALPHA = 0.4      # weight of the newest discharge in the mean
PINELINK_BATTERY_LEARN_MIN_S = 60.0
PINELINK_BATTERY_LEARN_MAX_S = 4 * 3600.0
PINELINK_BATTERY_FLOOR_S = 300.0  # "under 5 min", never lower
PINELINK_BATTERY_DARK_FRESH = 180.0   # the reading must belong to the stretch that ended
PINELINK_BATTERY_DARK_TELL_S = 900.0  # a darkness found later than this is not announced
_PINELINK_BATT: dict[str, Any] = {"loaded": False, "busy": False,
                                  "tried_at": 0.0}
_PINELINK_BATT_LOCK = _CambattLock()
_PINELINK_BATT_KEEP = ("code", "at", "ok_at", "hist", "noted", "error",
                       "learned", "dies_at", "live_seen_at", "dark",
                       "dark_noted", "charge_since")


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
    """The level out of a cmd=3019 answer, or None for anything else."""
    st = re.search(r"<Status>\s*(-?\d+)\s*</Status>", body or "")
    val = re.search(r"<Value>\s*(-?\d+)\s*</Value>", body or "")
    if not st or not val or int(st.group(1)) != 0:
        return None
    code = int(val.group(1))
    if code == PINELINK_BATTERY_CHARGING or code in PINELINK_BATTERY_LEVELS:
        return code
    return None


def _pinelink_battery_dur(code: int) -> tuple[float, bool, int]:
    """(seconds on this level, learned?, discharges it was learned from)."""
    got = (_PINELINK_BATT.get("learned") or {}).get(str(int(code))) or {}
    try:
        if int(got.get("n") or 0) > 0 and float(got.get("avg_s") or 0) > 0:
            return float(got["avg_s"]), True, int(got["n"])
    except Exception:  # noqa: BLE001
        pass
    return PINELINK_BATTERY_DEFAULT_S.get(int(code), 0.0), False, 0


def _pinelink_battery_learn(code: int, secs: float, now: float) -> bool:
    """One real duration for one level, folded into its smoothed mean."""
    if not (PINELINK_BATTERY_LEARN_MIN_S <= secs <= PINELINK_BATTERY_LEARN_MAX_S):
        return False
    learned = dict(_PINELINK_BATT.get("learned") or {})
    row = dict(learned.get(str(int(code))) or {})
    n = int(row.get("n") or 0)
    avg = float(row.get("avg_s") or 0)
    avg = secs if n <= 0 or avg <= 0 else (
        PINELINK_BATTERY_ALPHA * secs + (1 - PINELINK_BATTERY_ALPHA) * avg)
    learned[str(int(code))] = {"avg_s": round(avg, 1), "n": n + 1,
                               "last_s": round(secs, 1), "at": now}
    _PINELINK_BATT["learned"] = learned
    return True


def _pinelink_battery_say(s: float) -> str:
    """'under 5 min', '25 min', '1 h 5 min' - no tilde, no 'left'."""
    if s < PINELINK_BATTERY_FLOOR_S:
        return "under 5 min"
    m = int(round(s / 60.0))
    h, m = divmod(m, 60)
    return ("%d h %d min" % (h, m)) if h else ("%d min" % m)


def _pinelink_battery_estimate(now: float) -> dict[str, Any]:
    """Time left from the level the camera is on, by the table."""
    B = _PINELINK_BATT
    cur = int(B.get("code"))
    hist = [h for h in (B.get("hist") or []) if isinstance(h, dict)]
    entry = hist[-1] if hist and int(hist[-1].get("code", -1)) == cur else None
    dies = B.get("dies_at")
    last = max(cur, int(dies) if dies is not None else max(PINELINK_BATTERY_LEVELS))
    d_cur = _pinelink_battery_dur(cur)[0]
    if entry and entry.get("edge") and not entry.get("blind"):
        spent, whole = now - float(entry["at"]), True
    else:
        since = now - float((entry or {}).get("at") or B.get("at") or now)
        spent, whole = since + d_cur / 2.0, False
    left = max(0.0, d_cur - spent)
    basis = []
    for k in range(cur, last + 1):
        d, learned, n = _pinelink_battery_dur(k)
        if k > cur:
            left += d
        basis.append({"code": k, "word": PINELINK_BATTERY_LEVELS[k][1],
                      "s": round(d), "learned": learned, "n": n})
    return {"left_s": round(left), "estimate": not all(b["learned"] for b in basis),
            "spent_s": round(max(0.0, spent)), "entry_seen": whole, "basis": basis,
            "dies_at": last}


def pinelink_battery_view(now: float | None = None,
                          live: bool | None = None) -> dict[str, Any]:
    """What every surface paints. Read-only; safe without the lock.
    `label` leads (time left); the level word is for the tooltip."""
    now = float(now or time.time())
    B = _PINELINK_BATT
    code, at = B.get("code"), float(B.get("at") or 0)
    base = {"source": "camera cmd 3019 (Novatek level)", "every_s": PINELINK_BATTERY_EVERY,
            "error": str(B.get("error") or "")}
    if code is None or not at:
        base.update(ok=False, label="", say="Pine Cam battery: not read yet"
                    + (" - " + base["error"] if base["error"] else ""))
        return base
    code = int(code)
    age = max(0.0, now - at)
    stale = age > PINELINK_BATTERY_STALE
    doc: dict[str, Any] = dict(base)
    if code == PINELINK_BATTERY_CHARGING:
        since = float(B.get("charge_since") or at)
        doc.update(key="charging", word="charging", bars=None, pct=None, tone="ok",
                   charging=True, pulse=False, left_s=None, left_say="", estimate=False,
                   label="charging")
        what = ("Pine Cam battery: charging, for %s so far. While plugged in the camera "
                "reports only 'charging', never a level, so time to full cannot be "
                "learned" % _pinelink_battery_say(max(0.0, now - since)))
    else:
        key, word, bars, pct, tone = PINELINK_BATTERY_LEVELS[code]
        est = _pinelink_battery_estimate(now)
        left = float(est["left_s"])
        say = _pinelink_battery_say(left)
        label = ("under 5 min left" if left < PINELINK_BATTERY_FLOOR_S
                 else "~%s left" % say) + (" · estimate" if est["estimate"] else "")
        doc.update(key=key, word=word, bars=bars, pct=pct, tone=tone, charging=False,
                   pulse=pct <= 10, left_s=round(left), left_say=say,
                   estimate=est["estimate"], label=label, basis=est["basis"],
                   dies_at=est["dies_at"])
        parts = ", ".join("%s %d min (%s)" % (
            b["word"], round(b["s"] / 60.0),
            ("learned from %d discharge%s" % (b["n"], "" if b["n"] == 1 else "s"))
            if b["learned"] else "default") for b in est["basis"])
        what = ("Pine Cam battery: %s left%s. The camera says %s (level %d of 0-4; it "
                "reports levels, not a percentage). Counted from: %s%s" % (
                    say, " - an estimate" if est["estimate"] else "", word, code, parts,
                    "" if est["entry_seen"] else
                    "; this level was first seen part-way, so half of it is taken as gone"))
    dark = B.get("dark") if isinstance(B.get("dark"), dict) and not live else None
    doc.update(ok=True, code=code, at=at, age_s=round(age, 1), stale=stale,
               approx=True, low=bool(not doc["charging"] and code >= PINELINK_BATTERY_LOW),
               dark=bool(dark))
    if dark:
        d_at = float(dark.get("at") or at)
        d_age = max(0.0, now - d_at)
        was = dark.get("label") or ""
        doc.update(label="camera went dark – battery likely flat", dark_at=d_at,
                   dark_age_s=round(d_age), dark_was=was, tone="stale", pulse=False)
        what = ("Pine Cam went dark %s ago with its battery on the %s - likely flat. "
                "Last estimate then: %s" % (_pinelink_battery_say(d_age), dark.get("word") or "last bar",
                    was or "none"))
    doc["what"] = what
    ago = ("%d s" % age) if age < 90 else ("%d min" % round(age / 60.0))
    doc["say"] = what + ". Read %s ago%s." % (ago, " - STALE" if stale and not dark else "")
    if base["error"] and stale and not dark:
        doc["say"] += " Last try: " + base["error"]
    return doc


def pinelink_battery_note(code: int, now: float) -> None:
    """Fold one reading into the ledger, learning a level's duration when a
    whole one was watched. Caller holds the lock."""
    B = _PINELINK_BATT
    hist = [dict(h) for h in (B.get("hist") or []) if isinstance(h, dict)]
    ok_at = float(B.get("ok_at") or 0)
    gap = bool(ok_at) and (now - ok_at) > PINELINK_BATTERY_GAP
    if code == PINELINK_BATTERY_CHARGING:
        if B.get("code") != PINELINK_BATTERY_CHARGING or not B.get("charge_since"):
            B["charge_since"] = now
        hist = []
        B["noted"] = False
    elif hist and code < int(hist[-1]["code"]):
        hist = [{"code": code, "at": now, "edge": False}]
        B["noted"] = False
    elif not hist or code != int(hist[-1]["code"]):
        prev = hist[-1] if hist else None
        if (prev and not gap and prev.get("edge") and not prev.get("blind")
                and code == int(prev["code"]) + 1):
            _pinelink_battery_learn(int(prev["code"]), now - float(prev["at"]), now)
        hist.append({"code": code, "at": now, "edge": bool(hist) and not gap})
        hist = hist[-8:]
    elif gap:
        hist[-1]["blind"] = True
    if code != PINELINK_BATTERY_CHARGING:
        B["charge_since"] = None
    B.update(code=code, at=now, ok_at=now, error="", hist=hist, dark=None)
    if (code != PINELINK_BATTERY_CHARGING and code >= PINELINK_BATTERY_LOW
            and not B.get("noted")):
        B["noted"] = True
        v = pinelink_battery_view(now, live=True)
        try:
            note_action("Pine Cam: about %s of battery left" % v.get("left_say"))
        except Exception:  # noqa: BLE001
            pass


def _pinelink_battery_dark_check(now: float) -> None:
    """The link is not live. Did the camera just go dark on a flat battery?"""
    B = _PINELINK_BATT
    if B.get("dark") or B.get("code") is None:
        return
    code = int(B["code"])
    seen = float(B.get("live_seen_at") or 0)
    ok_at = float(B.get("ok_at") or 0)
    if code == PINELINK_BATTERY_CHARGING or code < PINELINK_BATTERY_LOW:
        return
    if not seen or ok_at < seen - PINELINK_BATTERY_DARK_FRESH:
        return            # that reading is not from the stretch that just ended
    with _PINELINK_BATT_LOCK:
        if B.get("dark"):
            return
        before = pinelink_battery_view(seen, live=True)
        hist = [h for h in (B.get("hist") or []) if isinstance(h, dict)]
        entry = hist[-1] if hist and int(hist[-1].get("code", -1)) == code else None
        learned = False
        if entry and entry.get("edge") and not entry.get("blind"):
            learned = _pinelink_battery_learn(code, seen - float(entry["at"]), now)
        B["dies_at"] = code
        B["dark"] = {"at": seen, "code": code, "word": before.get("word"),
                     "label": before.get("label"), "left_s": before.get("left_s"),
                     "learned": learned, "found_at": now}
        tell = (now - seen) <= PINELINK_BATTERY_DARK_TELL_S and B.get("dark_noted") != seen
        if tell:
            B["dark_noted"] = seen
        _pinelink_battery_save()
    if tell:
        try:
            note_action("Pine Cam went dark - battery likely flat (it was on its %s; "
                        "the last estimate said %s)" % (
                            before.get("word"), before.get("label") or "nothing"))
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
    A dict read and a clock compare on the caller's thread; the camera is
    asked on a daemon thread at most every PINELINK_BATTERY_EVERY seconds
    and only while `link` is live and fresh. A link that is not live is
    checked once for the camera having gone dark on a flat battery."""
    _pinelink_battery_load()
    now = time.time()
    live = bool(link and link.get("state") == "live" and link.get("fresh"))
    if live:
        _PINELINK_BATT["live_seen_at"] = now      # saved with the next poll
        if (not _PINELINK_BATT.get("busy")
                and now - float(_PINELINK_BATT.get("tried_at") or 0) >= PINELINK_BATTERY_EVERY):
            _PINELINK_BATT["busy"] = True
            _PINELINK_BATT["tried_at"] = now
            try:
                _CambattThread(target=_pinelink_battery_poll, name="pinelink-battery",
                               daemon=True).start()
            except Exception:  # noqa: BLE001
                _PINELINK_BATT["busy"] = False
    elif link is not None:
        try:
            _pinelink_battery_dark_check(now)
        except Exception:  # noqa: BLE001
            pass
    view = pinelink_battery_view(now, live=live)
    view["polling"] = live
    return view
'''


def patch(text: str) -> tuple[int, str, str]:
    if MARK in text:
        return 2, text, "already applied"
    if text.count(V1_START) != 1:
        return 1, text, "anchor missing: the wave-BB [cambattery] block (apply edit_cambattery_station.py first)"
    s = text.index(V1_START)
    e = text.find(V1_END, s)
    if e < 0 or V1_MUST not in text[s:e]:
        return 1, text, "anchor missing: the end of the [cambattery] block before PINELINK_IFACE"
    return 0, text[:s] + "\n" + BLOCK.strip("\n") + text[e:], "ok"


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    path = Path(argv[2])
    raw = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    code, out, say = patch(raw.replace("\r\n", "\n"))
    print("%s: %s" % (path, say))
    if code != 0 or argv[1] == "--check":
        return code
    if crlf:
        out = out.replace("\n", "\r\n")
    tmp = path.with_name(path.name + ".cambattery2.tmp")
    tmp.write_bytes(out.encode("utf-8"))
    os.replace(tmp, path)
    print("%s: APPLIED" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

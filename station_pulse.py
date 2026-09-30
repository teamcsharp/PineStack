"""[station-pulse] THE STATION'S PRESSURE, AND WHAT IT IS DOING, IN ONE READ.

"I want a small loading bar above the base status bar showing the health of the
station and how much of it is being grabbed out of the bank database versus being
rendered in real time. So the more that the station is being alleviated of
pressure, I want it to show the bar relaxing. But if it's having to render it in
real time and generate everything at real time and everything's locked up, then I
want it to show it being more full. I also want a single line scrolling marquee
giving up to date status information on the current status of the station and how
the orchestrator is handing the rooms and the tasks with the broadcast."

Pure: handed what /api/bank (the read-ahead ledger), cupboard_state() (the
writers' rooms, what is being recorded, the orchestrator's own feed) and the
emotion engine's voice queue already measure, it answers:

  pressure   0..1   0 = relaxed (the hour is in the bank), 1 = locked up
  parts      the four terms, so the bar's tooltip can say why:
               bank     what of the next hour is NOT yet rendered (missing, and
                        written-but-unvoiced at half weight), over what is owed
               live     the share of the hour's lines that will be made live
               voice    lines waiting for a voice, over 6
               writers  writers waiting, and the deferred backlog, over 4
  marquee    the status lines, in the order the eye wants them
"""
from __future__ import annotations

import time
from typing import Any

WEIGHTS = {"bank": 0.45, "live": 0.20, "voice": 0.20, "writers": 0.15}


def _f(v: Any) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 0.0
    return n if n == n else 0.0


def _mins(s: float) -> str:
    m = s / 60.0
    return ("%.0f min" % m) if m >= 1 or m == 0 else ("%.0f s" % s)


def _clock(s: float) -> str:
    s = max(0, int(s))
    return "%d:%02d" % (s // 60, s % 60)


def word(pressure: float) -> str:
    return ("relaxed" if pressure < 0.25 else "steady" if pressure < 0.5
            else "working hard" if pressure < 0.75 else "locked up")


def pulse(bank: dict[str, Any] | None, cup: dict[str, Any] | None, voice_queue: Any,
          now: float | None = None) -> dict[str, Any]:
    bank = bank if isinstance(bank, dict) else {}
    cup = cup if isinstance(cup, dict) else {}
    t = bank.get("totals") if isinstance(bank.get("totals"), dict) else {}
    owed = _f(bank.get("owed_seconds")) or 3600.0
    rendered = _f(bank.get("rendered_ahead_seconds") or t.get("rendered_seconds"))
    written = _f(bank.get("written_only_seconds") or t.get("written_only_seconds"))
    missing = _f(bank.get("missing_seconds") or t.get("missing_seconds"))
    lines = t.get("lines") if isinstance(t.get("lines"), dict) else {}
    live_l, ren_l = _f(lines.get("live")), _f(lines.get("rendered"))
    wr = cup.get("writers") if isinstance(cup.get("writers"), dict) else {}
    active, waiting = int(_f(wr.get("active"))), int(_f(wr.get("waiting")))
    deferred = int(sum(_f(v) for v in (wr.get("deferred") or {}).values())) if isinstance(wr.get("deferred"), dict) else 0
    voiceq = len(voice_queue) if isinstance(voice_queue, (list, tuple)) else int(_f(voice_queue))
    parts = {
        "bank": round(min(1.0, (missing + 0.5 * written) / owed), 3),
        "live": round(live_l / (live_l + ren_l), 3) if (live_l + ren_l) > 0 else 0.0,
        "voice": round(min(1.0, voiceq / 6.0), 3),
        "writers": round(min(1.0, (waiting + deferred / 60.0) / 4.0), 3),
    }
    pressure = round(min(1.0, sum(WEIGHTS[k] * parts[k] for k in WEIGHTS)), 3)
    banked = round(min(1.0, rendered / owed), 3) if owed else 0.0

    slots = [s for s in (bank.get("slots") or []) if isinstance(s, dict)]
    cur = next((s for s in slots if s.get("current")), slots[0] if slots else {})
    nxt = next((s for s in slots if s is not cur and _f(s.get("in_seconds")) > 0), {})
    prep = cup.get("preparing") if isinstance(cup.get("preparing"), dict) else {}
    feed = [f for f in (cup.get("feed") or []) if isinstance(f, dict) and f.get("text")]
    latest = max(feed, key=lambda f: _f(f.get("at"))) if feed else {}

    marquee = []
    if cur:
        marquee.append("ON AIR - %s (%s)%s" % (
            cur.get("label") or cur.get("road") or "the booth", cur.get("kind") or cur.get("road") or "segment",
            (" - %s of it ready" % _mins(_f(cur.get("ready_seconds")))) if cur.get("ready_seconds") is not None else ""))
    marquee.append("BANK - %s of the next %s rendered ahead, %s written only, %s still to make" % (
        _mins(rendered), _mins(owed), _mins(written), _mins(missing)))
    rooms = "ROOMS - %d writer%s at work, %d waiting, %d deferred" % (
        active, "" if active == 1 else "s", waiting, deferred)
    if prep.get("kind"):
        rooms += " - recording %s%s" % (prep.get("kind"),
                                        (" %d of %d lines" % (int(_f(prep.get("made"))), int(_f(prep.get("lines")))))
                                        if prep.get("lines") else "")
    marquee.append(rooms)
    marquee.append("VOICE - %d line%s waiting for a voice" % (voiceq, "" if voiceq == 1 else "s"))
    if nxt:
        marquee.append("NEXT - %s in %s" % (nxt.get("label") or nxt.get("road") or "the next segment",
                                            _clock(_f(nxt.get("in_seconds")))))
    if latest:
        marquee.append("ORCHESTRATOR - " + " ".join(str(latest["text"]).split()))
    return {"ok": True, "at": float(now if now is not None else time.time()),
            "pressure": pressure, "state": word(pressure), "banked": banked, "parts": parts,
            "numbers": {"owed_s": owed, "rendered_s": rendered, "written_s": written, "missing_s": missing,
                        "live_lines": live_l, "rendered_lines": ren_l, "writers_active": active,
                        "writers_waiting": waiting, "deferred": deferred, "voice_queue": voiceq},
            "marquee": marquee}

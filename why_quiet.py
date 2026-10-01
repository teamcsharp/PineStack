"""[why-quiet] "Right now I'm not hearing any DJs. What can I do in order to tell
you why and to get that resolved?" (the operator, 2026-10-01).

The station answers it itself: GET /api/dj/why-quiet gathers what it knows
(app.py) and these rules - each one a cause of silence measured on the live
station this week - read it into plain findings, the likeliest first, each with
what to do. Pure: facts in, findings out.
"""
from __future__ import annotations

import re
import time
from typing import Any

DJ_KINDS_NOT = ("request", "played", "marker", "sfx", "hangup", "image_analysis", "song_analysis", "chat")
# [why-quiet-heard] only these SPEAK. A "drop" row ("☎ Deacon Fry ... NEVER MADE
# AIR") and the "host" call card counted as the last DJ line, so a station whose
# calls all died read "nothing obviously wrong: a DJ line aired 55 s ago".
DJ_WHO = ("dj", "cohost", "third", "caller", "manager", "guest")
QUIET_AFTER_S = 240.0
UNHEARD_AFTER_S = 150.0
ROAD_WINDOW_S = 300.0
# what the roads say when they refuse to talk, counted over ROAD_WINDOW_S
ROAD_SIGNS = (
    ("refused", "live writing is refused"),
    ("no_audio", "produced no audio"),
    ("incomplete", "incomplete conversation withheld"),
    ("gate_held", "round withheld by the copy gate"),
    ("deferred", "admitted station writers"),
    ("reserve_dry", "[reserve-dry]"),
)


def last_dj_line(chat: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in reversed(chat or []):
        if (isinstance(row, dict) and str(row.get("who") or "") in DJ_WHO
                and str(row.get("kind") or "") not in DJ_KINDS_NOT and str(row.get("text") or "").strip()):
            return row
    return None


def last_heard(chat: list[dict[str, Any]]) -> float:
    """[why-quiet-heard] when a listening page last acknowledged PLAYING a DJ line
    (heard_ack_at) - 0.0 when none in the ring has been heard."""
    best = 0.0
    for row in chat or []:
        if isinstance(row, dict) and str(row.get("who") or "") in DJ_WHO:
            try:
                best = max(best, float(row.get("heard_ack_at") or 0))
            except (TypeError, ValueError):
                continue
    return best


def calls_lost(chat: list[dict[str, Any]], now: float, window: float = 3600.0) -> dict[str, Any]:
    """[why-quiet-heard] phone calls in the last hour that NEVER MADE AIR, against
    the calls that did (a call that aired has caller lines in the ring)."""
    lost, names = 0, []
    aired = set()
    for row in chat or []:
        if not isinstance(row, dict):
            continue
        try:
            ts = float(row.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        ts = ts / 1000.0 if ts > 1e11 else ts
        if now - ts > window:
            continue
        if str(row.get("who") or "") == "drop" and "NEVER MADE AIR" in str(row.get("text") or ""):
            lost += 1
            names.append(str(row.get("name") or "?"))
        elif str(row.get("who") or "") == "caller":
            aired.add(str(row.get("name") or ""))
    return {"lost": lost, "aired": len(aired), "names": names[-6:]}


def road_counts(events: list[dict[str, Any]], now: float, window: float = ROAD_WINDOW_S) -> dict[str, int]:
    """[why-quiet-heard] how often each refusal sign appeared in the last `window` s."""
    out = {k: 0 for k, _sign in ROAD_SIGNS}
    for e in events or []:
        try:
            ts = float((e or {}).get("ts") or 0) / 1000.0
        except (TypeError, ValueError):
            continue
        if now - ts > window:
            continue
        t = str((e or {}).get("text") or "")
        for k, sign in ROAD_SIGNS:
            if sign in t:
                out[k] += 1
    return out


def findings(f: dict[str, Any], now: float | None = None) -> list[dict[str, str]]:
    """[{level: stop|warn|info, what, do}] - the likeliest cause first."""
    now = time.time() if now is None else now
    out: list[dict[str, str]] = []

    def add(level: str, what: str, do: str = "") -> None:
        out.append({"level": level, "what": what, "do": do})

    if not f.get("on"):
        add("stop", "The radio is off.", "Turn it on from the desk.")
    if f.get("paused"):
        mins = int(float(f.get("paused_for") or 0) // 60)
        add("stop", "The broadcast is paused%s - while paused the station banks, it does not air."
            % (" (%d min)" % mins if mins else ""), "Unpause it.")
    mode = str(f.get("playout_mode") or "")
    verdict = str(f.get("playout_verdict") or "")
    queued = re.search(r"queued asks: (\d+)", verdict)
    if mode == "linear":
        add("stop" if queued and int(queued.group(1)) > 20 else "warn",
            "Playout is LINEAR%s: last time this pushed every finished round past its slot's deadline."
            % (" with %s queued asks" % queued.group(1) if queued else ""),
            "Write shadow: docker exec spark-agent sh -c 'echo shadow > /app/data/playout/mode'")
    if "STALLED" in verdict:
        add("stop", "The playout clock says the clip on air has STALLED: " + verdict[:200],
            "Reload the desk (the player that reports the clip), or restart the station at the radio gap.")
    eng = f.get("engines") or {}
    if eng and not eng.get("xtts") and not eng.get("voxtral"):
        add("stop", "Neither voice engine (XTTS, Voxtral) is ready - only Piper can speak.",
            "Check the TTS containers (docker ps) and their logs.")
    for road, until in sorted((f.get("roads_out") or {}).items()):
        left = int(max(0.0, float(until) - now) // 60)
        add("warn", "The %s road is sitting out of the silence rescue for %d more min - the booth refused it "
            "twice in a row." % (road, left), "Its reason is in the [road-backoff] line below.")
    last = f.get("last_dj") or None
    age = now - float(last.get("ts") or 0) if isinstance(last, dict) else None
    if age is None or age > QUIET_AFTER_S:
        add("warn" if out else "stop",
            "No DJ line has aired %s." % ("since this boot" if age is None else "for %d min" % int(age // 60)),
            "The reasons the roads gave are below ([door-why] and refusals).")
    # [why-quiet-heard] PUBLISHED IS NOT HEARD: the lines can be going out while no
    # page plays them (nobody owns the air, a page that stopped acking).
    heard = float(f.get("heard_at") or 0)
    heard_age = now - heard if heard else None
    if ("heard_at" in f and age is not None and age <= QUIET_AFTER_S
            and (heard_age is None or heard_age > max(UNHEARD_AFTER_S, age + UNHEARD_AFTER_S))):
        add("stop", "DJ lines are going out but no page has played one %s (the air is %s)."
            % ("in the chat ring" if heard_age is None else "for %d min" % int(heard_age // 60),
               ("with " + str(f.get("owner"))) if f.get("owner") else "owned by nobody"),
            "Give the tablet the air (its Air card), or press Get the broadcast back on it.")
    lost = f.get("calls_lost") or {}
    if int(lost.get("lost") or 0) >= 2 and int(lost.get("lost") or 0) > int(lost.get("aired") or 0):
        add("warn", "%d phone call(s) in the last hour NEVER MADE AIR (%d did): %s - each held the line and left "
            "a hole." % (int(lost["lost"]), int(lost.get("aired") or 0), ", ".join(lost.get("names") or [])),
            "Their reasons are the [s3-turnchain] copy gate and 'incomplete conversation' lines below.")
    roads = f.get("roads") or {}
    reserve = f.get("reserve") or {}
    if int(roads.get("refused") or 0) >= 6 and not int(roads.get("reserve_dry") or 0):
        add("warn", "The 100%% talk road refused to write live %d times in %d min while the reserve 'catches up' "
            "(%s unaired round(s) on their way, %s that never will air)."
            % (int(roads["refused"]), int(ROAD_WINDOW_S // 60), reserve.get("coming", "?"), reserve.get("never", "?")),
            "If nothing is on its way the [reserve-dry] rule writes live; otherwise the recorder is behind.")
    if int(roads.get("incomplete") or 0) + int(roads.get("gate_held") or 0) >= 3:
        add("warn", "System 3 withheld %d finished round(s) in %d min (%d incomplete, %d held by the copy gate)."
            % (int(roads.get("incomplete") or 0) + int(roads.get("gate_held") or 0), int(ROAD_WINDOW_S // 60),
               int(roads.get("incomplete") or 0), int(roads.get("gate_held") or 0)),
            "The rounds are written and then refused - see the system3 lines below.")
    sweep = f.get("sweep") or {}
    if sweep.get("why") and (age is None or age > QUIET_AFTER_S):
        add("info", "The silence rescue's last pass: %s (%s walks, %s aired)."
            % (sweep.get("why"), sweep.get("walks", 0), sweep.get("aired", 0)))
    if f.get("talk") is not None and float(f.get("talk") or 0) <= 0:
        add("stop", "The talk dial is at 0% - the DJs are told not to talk.", "Raise the talk dial.")
    changed = f.get("gates_changed") or []
    if changed:
        add("info", "Speech gates changed from the station's values: " + ", ".join(changed[:8]) + ".",
            "Reset them in the Speech gates panel if lines are being refused.")
    if not out:
        add("info", "Nothing obviously wrong: the radio is on, unpaused, a DJ line went out %d s ago%s."
            % (int(age or 0), "" if heard_age is None else " and a page played one %d s ago" % int(heard_age)))
    order = {"stop": 0, "warn": 1, "info": 2}
    return sorted(out, key=lambda r: order.get(r["level"], 3))


def text(f: dict[str, Any], found: list[dict[str, str]], reasons: list[str]) -> str:
    lines = ["WHY ARE THE DJS QUIET - %s" % time.strftime("%Y-%m-%d %H:%M:%S"), ""]
    for r in found:
        lines.append("[%s] %s" % (r["level"].upper(), r["what"]))
        if r.get("do"):
            lines.append("        do: " + r["do"])
    lines += ["", "playout: " + str(f.get("playout_verdict") or f.get("playout_mode") or "?")]
    last = f.get("last_dj")
    if isinstance(last, dict):
        lines.append("last DJ line: %s %s: %s" % (time.strftime("%H:%M:%S", time.localtime(float(last.get("ts") or 0))),
                                                 last.get("name") or last.get("who") or "?",
                                                 str(last.get("text") or "")[:120]))
    if f.get("heard_at"):
        lines.append("last line a page PLAYED: %s" % time.strftime("%H:%M:%S", time.localtime(float(f["heard_at"]))))
    if f.get("roads"):
        lines.append("roads, last %d min: %s" % (int(ROAD_WINDOW_S // 60),
                                                 ", ".join("%s %d" % kv for kv in sorted(f["roads"].items()) if kv[1])
                                                 or "no refusals"))
    if reasons:
        lines += ["", "what the roads said lately (newest last):"] + ["  " + r for r in reasons[-25:]]
    return "\n".join(lines)


def reasons(events: list[dict[str, Any]]) -> list[str]:
    """The pipeline lines that say why something did not air."""
    pat = re.compile(r"door-why|road-backoff|refus|withheld|dropped|did not air|no takes|not ready|Traceback|Error",
                     re.I)
    out = []
    for e in events or []:
        t = str((e or {}).get("text") or "")
        if pat.search(t) or str((e or {}).get("kind") or "") == "drop":
            ts = float((e or {}).get("ts") or 0) / 1000.0
            out.append("%s %s: %s" % (time.strftime("%H:%M:%S", time.localtime(ts)) if ts else "--",
                                      (e or {}).get("kind") or "", t[:220]))
    return out

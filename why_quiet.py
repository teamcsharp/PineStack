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
QUIET_AFTER_S = 240.0


def last_dj_line(chat: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in reversed(chat or []):
        if isinstance(row, dict) and str(row.get("kind") or "") not in DJ_KINDS_NOT and str(row.get("text") or "").strip():
            return row
    return None


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
        add("info", "Nothing obviously wrong: the radio is on, unpaused and a DJ line aired %d s ago."
            % int(age or 0))
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

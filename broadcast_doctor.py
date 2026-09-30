"""[smart-reinit] THE STATION'S HALF OF "GET THE BROADCAST BACK".

The operator, 2026-09-30: "Whenever I bring up the broadcast and I can't hear
the music or the DJs, I just click this button. So I need this button to
intelligently be able to tell what's needing to be done so it does that and
doesn't reinitialize things that don't need to be reinitialized ... then query
me and ask me if the broadcast is working suitably and then from there into
troubleshooting before advancing to more advanced and intense of steps."

The button used to walk every rung whatever the symptom. This module names
the fault first. It is pure: app.py builds a snapshot of what the station
knows (`snapshot` below lists every key) and this turns it into findings,
most specific first. The tablet adds what only it can measure (its own
playback routing, its players, its levels and volume) and picks the cure.

A finding is {key, kind, say, cure, where, consent, evidence}:
  kind     "fault" - something that stops sound; "note" - reported, never
           touched (the operator's levels, volume and routing are his)
  cure     a POST /api/broadcast/fix/{step} key, "solo" (hand this device
           the air through POST /api/radio/solo), "make_radio" (the Playing
           it switch - only on the operator's own tap), or "" for none
  where    who performs the cure: "station", "tablet" or "you"
  consent  True when the cure changes something the operator set, so the
           drawer offers it as a button and never does it on its own

The run log is data/air_fixes.jsonl, the file the air watchdog already
writes "what was tried and whether it worked" into; these rows carry
event "reinit" so a repeated fault is countable next to the watchdog's own.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable

HINTS = ("", "no_music", "no_djs", "nothing", "other")

# How long the pair may be quiet before "no DJs" is a fault on its own. Two
# minutes is longer than any ordinary gap between rounds; when the operator
# has SAID the DJs are missing, half a minute is enough to believe him.
DJ_QUIET_S = 120.0
DJ_QUIET_HINTED_S = 30.0
# A loop stall this long is heard: every clip due in it arrives late.
STALL_HEARD_S = 8.0
# The run log is read back this far for "seen before".
REPEAT_WINDOW_S = 7 * 24 * 3600.0
LOG_EVENT = "reinit"
LOG_TAIL_BYTES = 512 * 1024


ANSWERS = ("yes", "no_music", "no_djs", "nothing", "other", "stopped")


def answer_of(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return text if text in ANSWERS else ""


def hint_of(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return text if text in HINTS else ""


def finding(key: str, kind: str, say: str, cure: str = "",
            where: str = "station", consent: bool = False,
            evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"key": key, "kind": kind, "say": say, "cure": cure,
            "where": where, "consent": bool(consent),
            "evidence": dict(evidence or {})}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _hears(route: Any) -> bool:
    return str(route or "").lower() in ("here", "both")


def _mins(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return "%d s" % int(seconds)
    return "%.1f min" % (seconds / 60.0)


def owner_is_device(snap: dict[str, Any]) -> bool:
    """Does the air belong to THIS device - under this id or another of its
    ids (the desktop is two tabs; a reload mints a new id)?"""
    owner = str(snap.get("owner") or "")
    if not owner:
        return False
    me = str(snap.get("listener") or "")
    if owner == me:
        return True
    device = str(snap.get("device") or "")
    for row in snap.get("roster") or []:
        ids = [str(x) for x in (row.get("ids") or [])] + [str(row.get("listener") or "")]
        if owner in ids:
            same_device = bool(device) and str(row.get("device") or "") == device
            return same_device or bool(me and me in ids)
    return False


def station_findings(snap: dict[str, Any], hint: str = "") -> list[dict[str, Any]]:
    """Every station-side reason this device may be silent, most specific
    first. Only what the snapshot proves; nothing here guesses."""
    hint = hint_of(hint)
    out: list[dict[str, Any]] = []
    name = str((snap.get("terminal") or {}).get("name") or "this tablet")

    # --- the door ---------------------------------------------------------
    if not snap.get("on"):
        out.append(finding(
            "off_air", "fault",
            "The station is switched off, so nothing is being sent.",
            "onair"))
        return out
    if snap.get("paused"):
        out.append(finding(
            "paused", "fault",
            "The station is paused (off air for %s), so nothing is being sent."
            % _mins(_num(snap.get("paused_for_s"))), "onair",
            evidence={"paused_for_s": _num(snap.get("paused_for_s"))}))
        return out

    # --- the loop ---------------------------------------------------------
    pulse = snap.get("pulse") or {}
    if pulse.get("stalling_now") or _num(pulse.get("worst_s")) >= STALL_HEARD_S:
        out.append(finding(
            "air_stalled", "fault",
            "The station's own loop is stalling (%s), so clips reach the air "
            "late or not at all." % (str(pulse.get("reading") or "stalls"))[:160],
            "relieve", evidence={"worst_s": _num(pulse.get("worst_s")),
                                 "stalls": int(_num(pulse.get("stalls")))}))

    # --- who may sound ----------------------------------------------------
    terminal = snap.get("terminal") or {}
    if terminal and terminal.get("play") is False:
        out.append(finding(
            "play_off", "fault",
            "%s is set not to play out loud (its out-loud switch in Playing it "
            "is off), so the station will not let it sound." % name,
            "make_radio", where="you", consent=True))
    elif snap.get("hushed"):
        out.append(finding(
            "hushed", "fault",
            "%s is switched off in Playing it, so its page mutes itself." % name,
            "make_radio", where="you", consent=True))
    owner = str(snap.get("owner") or "")
    if owner and not owner_is_device(snap) and not any(
            f["key"] in ("play_off", "hushed") for f in out):
        what = str(snap.get("owner_what") or owner)
        out.append(finding(
            "gagged", "fault",
            "%s holds the air, so the solo gate mutes every player on %s."
            % (what, name), "solo", evidence={"owner": owner}))
    if not owner:
        audible = [r for r in (snap.get("roster") or [])
                   if not r.get("hushed", False)]
        if len(audible) > 1:
            out.append(finding(
                "overlap", "fault",
                "Nobody holds the air and %d surfaces are on the broadcast - "
                "they will be playing over each other." % len(audible),
                "solo", evidence={"surfaces": len(audible)}))

    # --- where the streams go (the operator's routing: reported only) -----
    routing = snap.get("routing") or {}
    if routing and not _hears(routing.get("music")) and hint in ("", "no_music", "nothing", "other"):
        out.append(finding(
            "music_routed_away", "note",
            "The station sends the records to '%s', not to this page "
            "(Streams: Music). Left as you set it." % routing.get("music"),
            where="you"))
    elif snap.get("music_here") is False and hint in ("", "no_music", "nothing", "other"):
        out.append(finding(
            "music_on_box", "note",
            "The box is carrying the record, so this page does not play it. "
            "Left as you set it.", where="you"))
    if routing and not _hears(routing.get("voice")) and hint in ("", "no_djs", "nothing", "other"):
        out.append(finding(
            "voice_routed_away", "note",
            "The station sends the DJs to '%s', not to this page "
            "(Streams: DJs). Left as you set it." % routing.get("voice"),
            where="you"))

    # --- the record -------------------------------------------------------
    if hint == "no_music" and not snap.get("playing"):
        out.append(finding(
            "no_record", "fault",
            "No record is on the station's clock right now, so there is no "
            "music to hear.", ""))

    # --- the DJs ----------------------------------------------------------
    quiet = _num(snap.get("talk_quiet_s"))
    ready = int(_num(snap.get("rounds_ready")))
    limit = DJ_QUIET_HINTED_S if hint in ("no_djs", "nothing") else DJ_QUIET_S
    if quiet >= limit and hint != "no_music":
        if ready > 0:
            out.append(finding(
                "dj_silent", "fault",
                "The station has not spoken for %s although %d round(s) are "
                "ready." % (_mins(quiet), ready), "stock",
                evidence={"quiet_s": round(quiet, 1), "rounds_ready": ready,
                          "consumer": str(snap.get("consumer_why") or "")}))
        else:
            out.append(finding(
                "dj_nothing_ready", "fault",
                "The station has not spoken for %s and has no finished round "
                "ready to air." % _mins(quiet), "bank",
                evidence={"quiet_s": round(quiet, 1)}))

    # --- this page's acknowledgements ------------------------------------
    triage = snap.get("triage") or {}
    cause = str(triage.get("cause") or "")
    mine = str(triage.get("listener") or "") in ("", str(snap.get("listener") or ""))
    if cause == "not_started" and mine:
        out.append(finding(
            "page_not_starting", "fault",
            str(triage.get("why") or "clips are handed over and not started")[:220],
            "flush"))
    elif cause in ("never_starts", "play_interrupted") and mine and triage.get("listener"):
        out.append(finding(
            "page_not_starting", "fault",
            str(triage.get("why") or "this page takes clips and starts none")[:220],
            "reload_page", where="tablet"))
    return out


def say_all(found: Iterable[dict[str, Any]]) -> str:
    rows = [f for f in found]
    if not rows:
        return "the station is on air, sending, and nothing it can see is in the way"
    return " ".join(str(f.get("say") or "") for f in rows)


# --- the run log -----------------------------------------------------------

def log_row(body: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    """One step of one run, as written to air_fixes.jsonl."""
    body = body if isinstance(body, dict) else {}

    def keys(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(v)[:40] for v in value[:24] if str(v or "").strip()]

    return {
        "at": float(now if now is not None else time.time()),
        "event": LOG_EVENT,
        "run": str(body.get("run") or "")[:40],
        "step": int(_num(body.get("step"))),
        "device": str(body.get("device") or "")[:32],
        "listener": str(body.get("listener") or "")[:64],
        "hint": hint_of(body.get("hint")),
        "findings": keys(body.get("findings")),
        "notes": keys(body.get("notes")),
        "cure": str(body.get("cure") or "")[:48],
        "did": str(body.get("did") or "")[:400],
        "answer": answer_of(body.get("answer")),
    }


def read_runs(path: Path, since: float = 0.0,
              tail_bytes: int = LOG_TAIL_BYTES) -> list[dict[str, Any]]:
    """The reinit rows at the end of the log, oldest first."""
    try:
        with Path(path).open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - tail_bytes))
            blob = handle.read().decode("utf-8", "replace")
    except OSError:
        return []
    rows = []
    for line in blob.splitlines():
        if '"%s"' % LOG_EVENT not in line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("event") == LOG_EVENT \
                and _num(row.get("at")) >= since:
            rows.append(row)
    return rows


def repeats(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    """How many RUNS each fault has turned up in (one run may re-diagnose
    several times; it counts once)."""
    seen: dict[str, set[str]] = {}
    for row in rows:
        run = str(row.get("run") or row.get("at"))
        for key in row.get("findings") or []:
            seen.setdefault(str(key), set()).add(run)
    return {k: len(v) for k, v in seen.items()}


def summary(rows: list[dict[str, Any]], limit: int = 12) -> dict[str, Any]:
    runs: dict[str, dict[str, Any]] = {}
    for row in rows:
        run = str(row.get("run") or "")
        got = runs.setdefault(run, {"run": run, "at": row.get("at"),
                                    "device": row.get("device"),
                                    "steps": [], "answer": ""})
        got["steps"].append({k: row.get(k) for k in
                             ("step", "hint", "findings", "cure", "did", "answer")})
        if row.get("answer"):
            got["answer"] = row.get("answer")
    ordered = sorted(runs.values(), key=lambda r: -_num(r.get("at")))
    count = repeats(rows)
    worst = sorted(count.items(), key=lambda kv: -kv[1])[:8]
    return {"runs": ordered[:limit], "repeats": count,
            "say": ("no runs recorded" if not rows else
                    "%d run(s); most repeated: %s" % (
                        len(runs), ", ".join("%s x%d" % kv for kv in worst)
                        or "nothing found in any"))}

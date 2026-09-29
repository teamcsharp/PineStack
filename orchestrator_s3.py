"""[orch-s3] THE ORCHESTRATOR'S SYSTEM 3 DESK.

WHY THIS EXISTS. "double check the orchestrator ... making sure that he is
fully understanding of all of the systems encompassed by system three and is
able to deal with the cupboard and manage items for system three and store and
interact with the tables and keep track of all of the elements that have been
added with system three and be able to manage track identify triage resolve and
basically orchestrate for any situations that come up" - the operator,
2026-09-29.

Measured on the live station that morning (host 81ce2fd): orch_scan() read
the hour, the slots, the shelves, the judgment book and the cupboard - and
NOTHING System 3 had grown in the last days. The origin ledger held 26 rogue
lines in 24 h (every one from page_recovery_chat_rows), the config had moved
twelve times in eight hours (the station tabling its own rolls), and not one
orchestrator ask in 24 h named System 3. Every door he needed already
existed; none of them was his.

WHAT THIS MODULE ADDS, AND WHAT IT DOES NOT.
  - READ faculties: the origin ledger's Untraced/rogue alarm and coverage,
    /api/why/{code}'s life story, a segment's decision tree, the MP4-only
    counters and quarantine, the SFX display receipts, the Playing-it
    receivers, the gap ledger, the script ledger's age, System 3's tables and
    every config version (what was added, by whom), the cupboard by road with
    how much of it System 3 stamped, and the file manager's groups. Every one
    goes through the door that already exists; nothing here reads a store its
    owner does not already expose.
  - KNOWLEDGE: ELEMENTS (what each System 3 part is, where he reads it, where
    he may act) and PLAYBOOK (the known failure classes: identify, triage,
    resolve, and what never to do).
  - A SURVEY that turns the readings into findings, one per failure, with the
    evidence, the codes to ask `why` about, the triage sentence and the
    proposals that would resolve it.
  - ACT faculties with the Sys3 scene inspector's discipline: a PROPOSAL shows
    what will change (the diff and the live config hash), waits for a CONFIRM,
    reports what it wrote, and keeps an UNDO (the previous version's part).
    The station answering its own ask (orch_decide_alone) may confirm ONLY a
    proposal marked station_may (reversible, nothing lost: a cue, a
    nomination to the retirement desk). Tables, sections, rungs are the
    operator's confirm. Destructive doors (remove from the cupboard,
    quarantine, file-manager runs, reinitialise, config reset, table delete)
    are never the station's, and the last four are not offered at all - the
    desk points at the operator's own page for them.

NOTHING ON THE LOOP. The survey runs on a worker thread every SURVEY_EVERY_S,
started from orch_scan's own tick; orch_scan reads only the memo. A table or
section write goes to a thread; a cupboard door runs where the cupboard's own
route runs it.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = "orch.system3/1"
MARK = "[orch-s3]"
LEDGER_NAME = "orchestrator_s3_desk.json"
SURVEY_EVERY_S = 300.0
ASK_RECENT_S = 43200.0          # the orchestrator's own half-day topic rule
UNTRACED_HOURS = 24.0
DEAD_S = 30.0                   # a heard gap this long is dead air
DEAD_WINDOW_S = 3600.0
STALE_S = 900.0                 # no new script row for this long, on air
NOMINATE_MOST = 5               # cupboard rows one finding may send to the desk
PROPOSALS_KEEP = 200
NOTES_KEEP = 300
SEVERITY = {"high": 3, "medium": 2, "low": 1, "info": 0}
RECOVERY = ("page_recovery", "resume", "replay", "recover", "reel")
UNDECODABLE = re.compile(r"decod|unsupported|media_err|src_not|codec|format", re.I)
SECTIONS = ("speakerbox", "sfx", "personalities", "sfxguy", "blocks", "split")

# --------------------------------------------------------------- knowledge

ELEMENTS: tuple[dict[str, str], ...] = (
    {"key": "origin", "name": "Origin ledger and the Untraced alarm",
     "what": "every aired item traced to a table roll, a named forced node, or flagged rogue with the code path "
             "that aired it (system3_origin.py, data/system3_origin.sqlite3, 7 days full then compact)",
     "see": "GET /api/system3/untraced, /api/system3/coverage, /api/system3/origin/{line}",
     "act": "none on the ledger; a rogue path is resolved at its producer (file it) and its waiting stock",
     "classes": "rogue, untraced"},
    {"key": "why", "name": "Message ids and the life story",
     "what": "every line has a short code (#3c4782); its life across every store: written, rolled, voiced, aired, heard",
     "see": "GET /api/why/{code} (line_story.py); command `why #code`", "act": "none - read only",
     "classes": "every class starts here"},
    {"key": "tree", "name": "The segment decision tree",
     "what": "a segment's rounds as System 3's graph walked them: stages, roll receipts, roulette diamonds",
     "see": "GET /api/script/segment/{id}/decision-tree; command `s3 tree <segment>`", "act": "none - read only",
     "classes": "stale script, rogue"},
    {"key": "tables", "name": "System 3 tables and config",
     "what": "the families (ES, RS, IRS, FL, CTS, TEMPER, SHOCK, FAV, DIRECTIVE, EVENT, POOL, ...), their odds, "
             "the config sections, and every saved version with its note - including rolls the station tabled itself",
     "see": "GET /api/system3/config (versions), command `s3 tables`",
     "act": "PUT /api/system3/tables/{id}, PUT /api/system3/config/section/{name} - proposed here, the operator confirms, undo writes the previous part back",
     "classes": "tables added"},
    {"key": "es1", "name": "ES1 emotion table v2 with audibility floors",
     "what": "the emotion roll and its per-voice floors (es_voice.py); ES1 v2 moved 101 rows to recalibrated voices",
     "see": "`s3 table ES1`", "act": "a table proposal like any other", "classes": "tables added"},
    {"key": "h3speak", "name": "H3SPEAK rolls",
     "what": "the H3 speaking rolls (h3.speak_lean, h3.speak_count) tabled 2026-09-29",
     "see": "`s3 tables` (changes)", "act": "a table proposal", "classes": "tables added"},
    {"key": "actors", "name": "Voice actor strips",
     "what": "the per-line actor direction strip carried with a line's System 3 stamp",
     "see": "`why #code` (the voiced stage)", "act": "none here", "classes": "untraced"},
    {"key": "cupboard", "name": "The cupboard, by road and by System 3 stamp",
     "what": "finished and unfinished rounds on every shelf; which are System 3 stamped and which are legacy",
     "see": "GET /api/cupboard/unheard, /api/cupboard/why; command `s3 cupboard [road]`",
     "act": "cue/uncue and nominate to the retirement desk (reversible); finish (send back to the recording room); "
            "remove (operator only) - the /api/cupboard/act and retirement-desk doors",
     "classes": "rogue, dead air"},
    {"key": "filemgr", "name": "The file manager",
     "what": "stores by group, snapshots, reinitialise (filemgr.py)",
     "see": "GET /api/filemgr/groups, /api/filemgr/jobs; command `s3 files`",
     "act": "NEVER from here: a run or a restore is the operator's, typed, on the file manager's own page",
     "classes": "none - housekeeping"},
    {"key": "display", "name": "SFX display receipts",
     "what": "whether each clip's PICTURE reached each screen (sfx_display.py)",
     "see": "GET /api/sfx/display-audit; command `s3 display`", "act": "none - evidence for mp3 leak / undecodable",
     "classes": "mp3 leak, undecodable"},
    {"key": "mp4", "name": "The MP4-only switch and the quarantine",
     "what": "picture share at 100 = MP4 only; what the filter refused, swapped, left empty; clips no player decodes",
     "see": "GET /api/sfx/mp4-only; command `s3 mp4`",
     "act": "quarantine is ONE-WAY (the book row goes playable=0) - operator only", "classes": "mp3 leak, undecodable"},
    {"key": "receivers", "name": "Playing it - the receivers",
     "what": "every receiver of the broadcast and its out-loud switch (pinetab, desktop, web, car, nabu, box)",
     "see": "GET /api/air/receivers; command `s3 receivers`",
     "act": "the operator's Playing-it switch (POST /api/air/receivers) - never the station's",
     "classes": "overlap, dead air"},
    {"key": "roll", "name": "The roll replay (PineRollTag)",
     "what": "every roll shown and replayable where a line is shown", "see": "the Rolodex / line tags",
     "act": "none here", "classes": "every class"},
)

PLAYBOOK: dict[str, dict[str, Any]] = {
    "rogue": {
        "signal": "the origin ledger settled a line as rogue from a producer that WRITES lines, on a road System 3 directs",
        "identify": ["`why #code` on two of its lines - which stage has no System 3 stamp",
                     "the producer and its code path from the Untraced list",
                     "the road's System 3 mode (active/shadow/off)",
                     "the road's cupboard stock with no System 3 stamp - it is what airs rogue next"],
        "triage": "high when the road is active under System 3 (the operator's rule: nothing on air System 3 did "
                  "not decide); medium when the road has not moved yet (it keeps airing, labelled)",
        "resolve": ["file the code path to the inbox once (the fix is at the producer, not a gate)",
                    "nominate that road's unstamped waiting stock to the retirement desk (reversible; the desk asks)",
                    "if the road is not under System 3 yet, say so - moving a road is the operator's"],
        "never": "never add a gate that silences the road; never delete stock"},
    "untraced": {
        "signal": "a rogue line whose producer RE-PUBLISHES (page recovery, resume reel, replay)",
        "identify": ["`why #code` - the same words usually aired earlier WITH a stamp",
                     "which re-publisher dropped it (the path)"],
        "triage": "low-medium: System 3 probably wrote it; the stamp fell off on the way back to the page",
        "resolve": ["note it and keep watching", "file the path once so the re-publisher carries the stamp"],
        "never": "never re-air it to 'fix' it; never count it as a writer fault"},
    "mp3_leak": {
        "signal": "MP4 only is on, yet the display audit counts audio-only SFX rows, or a player drew an audio_only surface",
        "identify": ["`s3 display` - which rows had no picture", "`s3 mp4` - refused / swapped / left empty per road"],
        "triage": "high while the switch is on (the operator asked for pictures only)",
        "resolve": ["file the road that drew it (the MP4 filter missed a door)", "note it"],
        "never": "never turn the switch off to hide it"},
    "overlap": {
        "signal": "more than one house receiver sounding at once",
        "identify": ["`s3 receivers` - which are sounding and which owns the air"],
        "triage": "high: the room hears the station twice",
        "resolve": ["tell the operator which switch on Playing it to turn off - receivers are the operator's"],
        "never": "never switch a receiver from the station"},
    "dead_air": {
        "signal": "heard gaps of 30 s or more in the last hour (data/gap_log.jsonl, by cause), or no receiver sounding on air",
        "identify": ["the gap's cause (event-loop stall, round turnover, ...) and its prev/next codes"],
        "triage": "high over 120 s in one gap or 180 s in the hour; a stall is the loop, not stock",
        "resolve": ["cause 'round turnover': the cupboard's ready stock and the unheard sweep (existing verbs unheard:on)",
                    "cause 'event-loop stall': the triangulate rung, then py-spy - not a knob",
                    "no receiver sounding: the operator's handover rung"],
        "never": "never add a filler road; the named frame first"},
    "stale_script": {
        "signal": "no new script-ledger row for 15 min while on air and not paused",
        "identify": ["the last block/ord written and its segment", "`s3 tree <segment>` for where the graph stopped"],
        "triage": "medium; high past 45 min",
        "resolve": ["the triangulate rung (read what is wrong)", "the produce rung (bank the next round now)"],
        "never": "never wipe the script ledger"},
    "undecodable": {
        "signal": "a player could not decode a clip (display receipts), or the quarantine grew",
        "identify": ["`s3 mp4` - the quarantine list and folders gone", "`s3 display` - not-shown reasons"],
        "triage": "low when already quarantined (the receipt hook does it); medium when still drawn",
        "resolve": ["the quarantine list is the transcode job's work list - file it once",
                    "quarantine a named clip only with the operator's confirm (one-way)"],
        "never": "never delete the file; quarantine is the door"},
    "tables_added": {
        "signal": "System 3's config moved - tables added, changed or removed, sections saved",
        "identify": ["`s3 tables` - each version's note, who tabled it, the table ids added"],
        "triage": "info: the operator should know what the station tabled on its own",
        "resolve": ["review; a change is a proposal with an undo"],
        "never": "never delete a table from here"},
}

# ------------------------------------------------------------- pure helpers


def _f(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return v if v == v else 0.0


def _h(*parts: Any) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:10]


def code_of(line_id: Any) -> str:
    try:
        import line_story
        return line_story.code_of(line_id)
    except Exception:  # noqa: BLE001
        s = str(line_id or "").lower()
        return s[:8] if re.fullmatch(r"[0-9a-f]{9,}", s) else s


def road_key(road: Any) -> str:
    """An origin-ledger road label -> the System 3 road it belongs to."""
    r = str(road or "").lower().strip()
    if r.startswith("round: "):
        r = r[7:]
    m = re.match(r"^(.+?)\s*\((.+)\)$", r)
    if m:
        r = m.group(1).strip()
    return {"board clip": "sfx", "sfx guy": "sfxguy", "call": "caller", "desk marker": "marker",
            "emergency host": "emergency", "station id": "station_id", "advert": "ad",
            "painting": "gallery"}.get(r, r.replace(" ", "_"))


def flat_diff(a: Any, b: Any, path: str = "", out: list | None = None) -> list[list[Any]]:
    """The inspector's flatDiff, in Python: [path, before, after] per leaf."""
    out = [] if out is None else out
    if len(out) > 60:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in list(dict.fromkeys(list(a) + list(b))):
            flat_diff(a.get(k), b.get(k), (path + "." + str(k)) if path else str(k), out)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            key = str(x.get("id")) if isinstance(x, dict) and x.get("id") is not None else str(i)
            flat_diff(x, y, (path + "." + key) if path else key, out)
    elif json.dumps(a, sort_keys=True, default=str) != json.dumps(b, sort_keys=True, default=str):
        out.append([path or "(all)", a, b])
    return out


def set_path(obj: Any, path: str, value: Any) -> None:
    """`categories.anger.items.shout.odds` - a list segment is matched by `id`."""
    parts = [p for p in str(path or "").split(".") if p]
    if not parts:
        raise ValueError("an empty path")
    cur = obj
    for i, p in enumerate(parts):
        last = i == len(parts) - 1
        if isinstance(cur, list):
            hit = next((x for x in cur if isinstance(x, dict) and str(x.get("id")) == p), None)
            if hit is None:
                if p.isdigit() and int(p) < len(cur):
                    if last:
                        cur[int(p)] = value
                        return
                    cur = cur[int(p)]
                    continue
                raise ValueError("no item %s under %s" % (p, ".".join(parts[:i]) or "the top"))
            if last:
                raise ValueError("%s is an item, not a value" % p)
            cur = hit
        elif isinstance(cur, dict):
            if last:
                cur[p] = value
                return
            if p not in cur:
                raise ValueError("no key %s under %s" % (p, ".".join(parts[:i]) or "the top"))
            cur = cur[p]
        else:
            raise ValueError("%s is not an object" % ".".join(parts[:i]))


def parse_value(raw: str) -> Any:
    raw = str(raw).strip()
    try:
        return json.loads(raw)
    except ValueError:
        return raw


# ------------------------------------------------------------------ sensors
# Each takes what its door returned and gives findings. Pure: the tests feed
# them the same shapes the doors serve.


def _finding(cls: str, severity: str, title: str, key: str, **kw: Any) -> dict[str, Any]:
    book = PLAYBOOK.get(cls, {})
    out = {"id": _h(cls, key), "class": cls, "severity": severity, "title": title,
           "triage": book.get("triage", ""), "resolve": list(book.get("resolve") or []),
           "never": book.get("never", ""), "identify": [], "evidence": {}, "proposals": [], "at": time.time()}
    out.update(kw)
    return out


def sense_origin(untraced: dict[str, Any], road_modes: dict[str, str]) -> list[dict[str, Any]]:
    """The Untraced alarm, split by what kind of path aired it."""
    items = list((untraced or {}).get("items") or [])
    out: list[dict[str, Any]] = []
    for grp in (untraced or {}).get("by_path") or []:
        prod, road, n = str(grp.get("producer") or "unknown"), str(grp.get("road") or ""), int(grp.get("count") or 0)
        if n <= 0:
            continue
        rk = road_key(road)
        mode = str(road_modes.get(rk) or "")
        samples = [r for r in items if str(r.get("producer") or "unknown") == prod and str(r.get("road") or "") == road][:3]
        codes = [code_of(r.get("line_id")) for r in samples]
        paths = sorted({str(r.get("path") or "") for r in samples if r.get("path")})
        recovery = any(prod.startswith(p) or ("<" + p) in (paths[0] if paths else "") for p in RECOVERY)
        if recovery:
            # on a road System 3 directs, even a lost stamp is air it cannot
            # account for - the operator's rule - so it is worth one ask
            cls, sev = "untraced", ("medium" if n >= 10 or mode == "active" else "low")
            title = "%d line(s) on %s aired without their System 3 stamp - re-published by %s" % (n, road, prod)
        else:
            cls = "rogue"
            sev = "high" if mode == "active" else "medium"
            title = "%d line(s) on %s were put on the air by %s, outside System 3" % (n, road, prod)
        out.append(_finding(
            cls, sev, title, "%s|%s" % (prod, road), road=rk, road_label=road, producer=prod, mode=mode or "not a System 3 road",
            identify=["why #%s" % c for c in codes[:2]] + ["path: %s" % p for p in paths[:2]],
            evidence={"count": n, "last": grp.get("last"), "codes": codes,
                      "sample": [str(r.get("text") or "")[:120] for r in samples[:2]],
                      "items_total": (untraced or {}).get("items_total")}))
    return out


def sense_mp4(mp4: dict[str, Any], display_summary: dict[str, Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    mp4 = mp4 or {}
    s = display_summary or {}
    audio_rows = int(s.get("audio_only_rows") or 0)
    surf_audio = sum(int(((p or {}).get("surfaces") or {}).get("audio_only") or 0)
                     for p in (s.get("players") or {}).values())
    if mp4.get("mp4_only") and (audio_rows or surf_audio):
        out.append(_finding("mp3_leak", "high",
                            "MP4 only is on and %d SFX row(s) in the last hour had no picture" % (audio_rows or surf_audio),
                            "leak", identify=["s3 display", "s3 mp4"],
                            evidence={"audio_only_rows": audio_rows, "audio_only_surfaces": surf_audio,
                                      "by_road": mp4.get("by_road"), "swapped": mp4.get("swapped")}))
    if mp4.get("mp4_only") and int(mp4.get("left_empty") or 0):
        out.append(_finding("dead_air", "medium",
                            "the MP4 filter left %d SFX pick(s) empty - a road with no picture clip to draw"
                            % int(mp4.get("left_empty") or 0), "mp4-empty", identify=["s3 mp4"],
                            evidence={"left_empty": mp4.get("left_empty"), "by_road": mp4.get("by_road")}))
    bad: dict[str, int] = {}
    for p, v in (s.get("players") or {}).items():
        for why, n in ((v or {}).get("not_displayed_by_reason") or {}).items():
            if UNDECODABLE.search(str(why)):
                bad["%s: %s" % (p, why)] = int(n)
    q = (mp4.get("quarantine") or {})
    recent_q = list(mp4.get("quarantine_recent") or [])
    if bad or recent_q:
        out.append(_finding("undecodable", "medium" if bad else "low",
                            ("%d clip(s) a player could not decode in the last hour" % sum(bad.values())) if bad else
                            ("%d clip(s) went to the quarantine in the last day" % len(recent_q)),
                            "undecodable", identify=["s3 mp4", "s3 display"],
                            evidence={"not_shown": bad, "quarantined_total": q.get("clips"),
                                      "recent": recent_q[:5], "list": q.get("list")}))
    return out


def sense_receivers(rx: dict[str, Any], on_air: bool) -> list[dict[str, Any]]:
    rows = [r for r in (rx or {}).get("receivers") or [] if isinstance(r, dict)]
    house = [r for r in rows if r.get("id") != "car" and r.get("sounding")]
    out: list[dict[str, Any]] = []
    if len(house) > 1:
        out.append(_finding("overlap", "high", "%d receivers are sounding in the house at once: %s"
                            % (len(house), ", ".join(str(r.get("label") or r.get("id")) for r in house)),
                            "rx|" + ",".join(sorted(str(r.get("id")) for r in house)),
                            identify=["s3 receivers"],
                            evidence={"sounding": [r.get("id") for r in house],
                                      "owner": next((r.get("id") for r in rows if r.get("owns_air")), None)}))
    if on_air and rows and not any(r.get("sounding") for r in rows):
        out.append(_finding("dead_air", "high", "on air, and no receiver is sounding - nobody can hear the station",
                            "rx-silent", identify=["s3 receivers"],
                            evidence={"present": [r.get("id") for r in rows if r.get("present")]}))
    return out


def sense_gaps(rows: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
    recent = [r for r in rows or [] if _f(r.get("until")) >= now - DEAD_WINDOW_S
              and _f(r.get("seconds")) - _f(r.get("paused_seconds")) >= DEAD_S]
    if not recent:
        return []
    by: dict[str, list[dict[str, Any]]] = {}
    for r in recent:
        by.setdefault(str(r.get("cause") or "unnamed"), []).append(r)
    total = sum(_f(r.get("seconds")) for r in recent)
    worst = max(recent, key=lambda r: _f(r.get("seconds")))
    sev = "high" if _f(worst.get("seconds")) >= 120 or total >= 180 else "medium"
    codes = [code_of((worst.get("prev") or {}).get("id")), code_of((worst.get("next") or {}).get("id"))]
    return [_finding("dead_air", sev, "%d gap(s) of %ds+ in the last hour, %ds in all; the worst %ds (%s)"
                     % (len(recent), int(DEAD_S), int(total), int(_f(worst.get("seconds"))),
                        worst.get("cause") or "unnamed"),
                     "gaps|" + str(worst.get("cause") or ""),
                     identify=["why #%s" % c for c in codes if c],
                     evidence={"by_cause": {k: {"n": len(v), "seconds": int(sum(_f(x.get("seconds")) for x in v))}
                                            for k, v in by.items()},
                               "worst": {"seconds": worst.get("seconds"), "cause": worst.get("cause"),
                                         "boundary": worst.get("boundary"), "codes": codes}})]


def sense_script(last_at: float, last_row: dict[str, Any] | None, on_air: bool, paused: bool,
                 now: float) -> list[dict[str, Any]]:
    if not on_air or paused or last_at <= 0:
        return []
    age = now - last_at
    if age < STALE_S:
        return []
    seg = ((last_row or {}).get("segment") or {})
    return [_finding("stale_script", "high" if age >= 3 * STALE_S else "medium",
                     "the script has not moved for %d min while on air" % int(age / 60), "stale",
                     identify=(["s3 tree %s" % seg.get("id")] if seg.get("id") else [])
                     + (["why #%s" % code_of((last_row or {}).get("line_id"))] if (last_row or {}).get("line_id") else []),
                     evidence={"age_s": int(age), "block": (last_row or {}).get("block"),
                               "ord": (last_row or {}).get("ord"), "segment": seg.get("label") or seg.get("id")})]


def table_changes(versions: list[dict[str, Any]], bodies: dict[str, Any], since: float) -> list[dict[str, Any]]:
    """Each config version since `since`, newest first, with the table ids it
    added, removed or re-versioned against the one before it."""
    vs = sorted([v for v in versions or [] if isinstance(v, dict)], key=lambda v: _f(v.get("created")))
    out = []
    for i, v in enumerate(vs):
        if _f(v.get("created")) < since:
            continue
        cur = bodies.get(v.get("hash")) or {}
        prev = bodies.get(vs[i - 1].get("hash")) if i else None
        row = {"hash": v.get("hash"), "at": v.get("created"), "note": v.get("note"),
               "by": "the station" if str(v.get("note") or "").startswith("station rolls tabled") else "an edit"}
        if isinstance(cur, dict) and isinstance(prev, dict):
            a = {t.get("id"): t for t in prev.get("tables") or []}
            b = {t.get("id"): t for t in cur.get("tables") or []}
            row["added"] = sorted(k for k in b if k not in a)
            row["removed"] = sorted(k for k in a if k not in b)
            row["changed"] = sorted(k for k in b if k in a and json.dumps(a[k], sort_keys=True, default=str)
                                    != json.dumps(b[k], sort_keys=True, default=str))
            row["sections"] = sorted(k for k in set(cur) | set(prev) if k != "tables"
                                     and json.dumps(cur.get(k), sort_keys=True, default=str)
                                     != json.dumps(prev.get(k), sort_keys=True, default=str))
        out.append(row)
    return list(reversed(out))


# --------------------------------------------------------------------- desk


class Desk:
    """The orchestrator's System 3 desk. `ns` is the station's namespace (the
    app's globals, or a test's dict)."""

    def __init__(self, ns: dict[str, Any], path: Any):
        self.ns = ns
        self.path = Path(path)
        self.lock = threading.RLock()
        self.book: dict[str, Any] = {"proposals": [], "notes": [], "filed": {}, "asked": {}}
        self.loaded = False
        self.memo: dict[str, Any] = {"at": 0.0, "value": None, "running": False}
        self.fac: dict[str, dict[str, Any]] = {}

    # ---- plumbing
    def _get(self, name: str, fallback: Any = None) -> Any:
        return self.ns.get(name, fallback)

    def rt(self) -> Any:
        got = self.ns.get("_SYSTEM3_RUNTIME")
        try:
            return got() if callable(got) else got
        except Exception:  # noqa: BLE001
            return None

    def load(self) -> None:
        with self.lock:
            if self.loaded:
                return
            try:
                got = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(got, dict):
                    for k in self.book:
                        if isinstance(got.get(k), type(self.book[k])):
                            self.book[k] = got[k]
            except (OSError, ValueError):
                pass
            self.loaded = True

    def save(self) -> None:
        with self.lock:
            self.book["proposals"] = self.book["proposals"][-PROPOSALS_KEEP:]
            self.book["notes"] = self.book["notes"][-NOTES_KEEP:]
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_bytes(json.dumps(self.book, default=str).encode("utf-8"))
                tmp.replace(self.path)
            except OSError:
                pass

    def mark(self, name: str, ok: bool, changed: bool = False, error: str = "") -> None:
        """called / runs / changes anything - per faculty, the orchestrator's own meter."""
        now = time.time()
        with self.lock:
            row = self.fac.setdefault(name, {"calls": 0, "ok": 0, "changes": 0})
            row["calls"] += 1
            row["called_at"] = now
            if ok:
                row["ok"] += 1
                row["ok_at"] = now
            else:
                row["error"] = str(error)[:200]
                row["error_at"] = now
            if changed:
                row["changes"] += 1
                row["changed_at"] = now

    def _read(self, name: str, fn: Any, *a: Any, **kw: Any) -> Any:
        try:
            got = fn(*a, **kw)
            self.mark(name, True)
            return got
        except Exception as exc:  # noqa: BLE001
            self.mark(name, False, error="%s: %s" % (type(exc).__name__, exc))
            return None

    def note(self, text: str, finding: str = "", who: str = "station") -> dict[str, Any]:
        self.load()
        row = {"at": time.time(), "text": str(text)[:400], "finding": finding, "who": who}
        with self.lock:
            self.book["notes"].append(row)
        self.save()
        return row

    # ---- read faculties (worker thread)
    def road_modes(self) -> dict[str, str]:
        rt = self.rt()
        try:
            import system3
            return {r: str(system3.road_mode(rt.settings, r)) for r in system3.ROADS}
        except Exception:  # noqa: BLE001
            return {}

    def read_origin(self, hours: float = UNTRACED_HOURS) -> dict[str, Any]:
        led = self._get("_ORIGIN_LEDGER")
        if led is None:
            raise RuntimeError("the origin ledger is not installed")
        now = time.time()
        return {"untraced": led.untraced(now - hours * 3600.0, 200),
                "coverage": led.coverage(now - hours * 3600.0, now)}

    def read_mp4(self) -> dict[str, Any]:
        load = self._get("_sfx_quarantine_load")
        if callable(load):
            load()
        out = {"mp4_only": bool(self._get("sfx_mp4_only", lambda: False)()),
               "share": self._get("sfx_video_share", lambda: None)(),
               **dict(self._get("_MP4ONLY") or {}),
               "quarantine": {"clips": len(self._get("_SFX_QUARANTINED") or ()),
                              "folders_gone": sorted(self._get("_SFX_GONE_FOLDERS") or ())[:20]}}
        qp = self._get("_sfx_quarantine_path")
        recent = []
        if callable(qp):
            p = Path(qp())
            out["quarantine"]["list"] = str(p)
            floor = time.time() - 86400.0
            try:
                for line in p.read_text(encoding="utf-8").splitlines()[-400:]:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if _f(r.get("at")) >= floor:
                        recent.append({k: r.get(k) for k in ("sid", "why", "at", "path", "by")})
            except OSError:
                pass
        out["quarantine_recent"] = recent[-20:]
        return out

    def read_display(self, hours: float = 1.0) -> dict[str, Any]:
        store = self._get("_SFX_DISPLAY_STORE")
        if store is None:
            raise RuntimeError("the SFX display receipts are not installed")
        import sfx_display as sd
        now = time.time()
        since = now - hours * 3600.0
        air_log = self._get("AIR_LOG_PATH") or self._get("data_path")("air_log.jsonl")
        board = tuple(self._get("SCREENPLAY_BOARD") or ("board",))
        rows = sorted(sd.script_rows(air_log, since, now, board),
                      key=lambda r: _f(r.get("air_at") or r.get("ts")))
        rep = sd.audit(rows, store.read(since, now), since, now)
        return rep.get("summary") or {}

    def read_receivers(self) -> dict[str, Any]:
        return self._get("air_receivers_state")()

    def read_gaps(self) -> list[dict[str, Any]]:
        return list(self._get("_gap_log_read")() or [])

    def read_script(self) -> tuple[float, dict[str, Any] | None]:
        rows = list(self._get("script_ledger_rows")() or [])[-80:]
        if not rows:
            return 0.0, None
        last = max(rows, key=lambda r: _f(r.get("at")))
        return _f(last.get("at")), last

    def read_tables(self, hours: float = 24.0) -> dict[str, Any]:
        rt = self.rt()
        if rt is None or getattr(rt, "store", None) is None:
            raise RuntimeError("System 3 is not installed")
        import system3
        cfg = rt.config or {}
        versions = rt.store.config_versions(80)
        since = time.time() - hours * 3600.0
        wanted = []
        vs = sorted(versions, key=lambda v: _f(v.get("created")))
        for i, v in enumerate(vs):
            if _f(v.get("created")) >= since:
                wanted.append(v.get("hash"))
                if i:
                    wanted.append(vs[i - 1].get("hash"))
        bodies = {h: rt.store.config_by_hash(h) for h in dict.fromkeys(wanted) if h}
        fams: dict[str, list[str]] = {}
        for t in cfg.get("tables") or []:
            fams.setdefault(str(t.get("family")), []).append(
                "%s v%s%s" % (t.get("id"), t.get("version") or 1, "" if t.get("enabled", True) else " (off)"))
        return {"hash": system3.config_hash(cfg), "families": fams, "tables": len(cfg.get("tables") or []),
                "sections": [k for k in cfg if k not in ("tables", "schema")],
                "changes": table_changes(versions, bodies, since), "versions": len(versions)}

    def read_cupboard(self) -> dict[str, Any]:
        """Per road: rows, never-aired, System 3 stamped - the cupboard as System 3 sees it."""
        shelf = self._get("_SHELF") or {}
        larder = self._get("_LARDER") or []
        stamp = self._get("bank_s3_of", lambda r: {})
        unaired = self._get("row_unaired", lambda r: not int((r or {}).get("aired") or 0))
        roads: dict[str, dict[str, int]] = {}
        for kind, rows in [("banter", list(larder))] + [(str(k), list(v or [])) for k, v in list(shelf.items())]:
            d = roads.setdefault(kind, {"rows": 0, "unaired": 0, "stamped": 0, "unstamped_unaired": 0})
            for r in rows:
                if not isinstance(r, dict):
                    continue
                d["rows"] += 1
                s = bool(stamp(r))
                u = bool(unaired(r))
                d["stamped"] += int(s)
                d["unaired"] += int(u)
                d["unstamped_unaired"] += int(u and not s)
        un = self._get("unheard_state")
        return {"roads": roads, "unheard": (un() if callable(un) else {}) or {}}

    def cupboard_rows(self, kind: str, most: int = 12) -> list[dict[str, Any]]:
        find_rows = self._get("shelf_rows")
        rows = list(self._get("_LARDER") or []) if kind == "banter" else list(
            (find_rows(kind) if callable(find_rows) else (self._get("_SHELF") or {}).get(kind)) or [])
        why = self._get("cupboard_why_row")
        stamp = self._get("bank_s3_of", lambda r: {})
        out = []
        for r in rows[:most]:
            if not isinstance(r, dict):
                continue
            w = why(kind, r) if callable(why) else {"id": r.get("id"), "reasons": []}
            s = stamp(r)
            out.append({"id": w.get("id"), "kind": kind, "ready": w.get("ready"), "blocked": w.get("blocked"),
                        "aired": w.get("aired"), "age": w.get("age"),
                        "first": (w.get("reasons") or [{}])[0].get("say"),
                        "system3": ({"conversation": s.get("conversation_id"), "road": s.get("road")} if s else None),
                        "text": str(w.get("text") or r.get("text") or "")[:100]})
        return out

    # ---- the survey
    def survey(self) -> dict[str, Any]:
        """Worker thread. Every read faculty once, findings from each, and the
        proposals that would resolve them."""
        self.load()
        with self.lock:
            if self.memo.get("running"):
                return self.memo.get("value") or {}
            self.memo["running"] = True
        try:
            now = time.time()
            radio = self._get("_RADIO") or {}
            on_air = bool(radio.get("on"))
            paused_fn = self._get("radio_paused")
            paused = bool(paused_fn()) if callable(paused_fn) else False
            modes = self._read("road_modes", self.road_modes) or {}
            origin = self._read("origin", self.read_origin) or {}
            mp4 = self._read("mp4", self.read_mp4) or {}
            display = self._read("display", self.read_display)
            rx = self._read("receivers", self.read_receivers) or {}
            gaps = self._read("gaps", self.read_gaps) or []
            script = self._read("script", self.read_script) or (0.0, None)
            tables = self._read("tables", self.read_tables) or {}
            cup = self._read("cupboard", self.read_cupboard) or {}
            findings: list[dict[str, Any]] = []
            findings += sense_origin(origin.get("untraced") or {}, modes)
            findings += sense_mp4(mp4, display)
            findings += sense_receivers(rx, on_air and not paused)
            findings += sense_gaps(gaps, now)
            findings += sense_script(script[0], script[1], on_air, paused, now)
            station_tabled = [c for c in tables.get("changes") or [] if c.get("by") == "the station"]
            if station_tabled:
                findings.append(_finding(
                    "tables_added", "info", "the station tabled %d roll(s) of its own in the last day"
                    % len(station_tabled), "tabled|" + str(station_tabled[0].get("hash")),
                    identify=["s3 tables"], evidence={"latest": station_tabled[:6]}))
            for f in findings:
                f["proposals"] = self.proposals_for(f, cup)
            findings.sort(key=lambda f: -SEVERITY.get(f["severity"], 0))
            value = {"schema": SCHEMA, "at": now, "on_air": on_air, "paused": paused,
                     "findings": findings, "modes": modes,
                     "coverage": {k: (origin.get("coverage") or {}).get(k) for k in ("totals", "roads")},
                     "mp4": {k: mp4.get(k) for k in ("mp4_only", "share", "refused", "swapped", "left_empty",
                                                     "quarantined", "by_road", "quarantine")},
                     "display": ({k: display.get(k) for k in ("script_sfx_rows", "picture_rows", "audio_only_rows",
                                                             "displayed_anywhere", "played_rate")}
                                 if isinstance(display, dict) else None),
                     "receivers": [{k: r.get(k) for k in ("id", "sounding", "audible", "owns_air", "present")}
                                   for r in (rx.get("receivers") or [])],
                     "script_age_s": int(now - script[0]) if script[0] else None,
                     "tables": tables, "cupboard": cup.get("roads") or {},
                     "faculties": self.faculties()}
            with self.lock:
                self.memo.update(at=now, value=value)
                self.book["last_survey"] = {"at": now, "findings": [
                    {k: f.get(k) for k in ("id", "class", "severity", "title")} for f in findings]}
            self.save()
            return value
        finally:
            with self.lock:
                self.memo["running"] = False

    # ---- proposals: review -> confirm -> undo
    def _proposal(self, door: str, target: str, title: str, *, finding: str = "", before: Any = None,
                  after: Any = None, extra: dict[str, Any] | None = None, reversible: bool = True,
                  needs_operator: bool = True, station_may: bool = False, by: str = "orchestrator") -> dict[str, Any]:
        self.load()
        key = _h(door, target, json.dumps(after, sort_keys=True, default=str))
        with self.lock:
            same = next((p for p in self.book["proposals"] if p.get("key") == key and p.get("state") == "proposed"), None)
            if same:
                return same
            rt = self.rt()
            h = ""
            try:
                import system3
                h = system3.config_hash(rt.config) if rt is not None else ""
            except Exception:  # noqa: BLE001
                pass
            p = {"id": "p" + _h(key, time.time())[:7], "key": key, "at": time.time(), "by": by, "finding": finding,
                 "door": door, "target": target, "title": title, "before": before, "after": after,
                 "changes": flat_diff(before, after) if isinstance(before, (dict, list)) else
                 [[target, before, after]], "hash_before": h, "reversible": reversible,
                 "needs_operator": needs_operator, "station_may": bool(station_may and reversible and not needs_operator),
                 "state": "proposed", **(extra or {})}
            self.book["proposals"].append(p)
        self.save()
        return p

    def find_proposal(self, pid: str) -> dict[str, Any] | None:
        self.load()
        with self.lock:
            return next((p for p in self.book["proposals"] if p.get("id") == str(pid).lstrip("#")), None)

    def proposals_for(self, f: dict[str, Any], cup: dict[str, Any]) -> list[str]:
        """What would resolve a finding, as proposals (never applied here)."""
        out: list[str] = []
        if f["class"] == "rogue" and f.get("mode") == "active":
            kind = f.get("road") or ""
            rows = self._read("cupboard_rows", self.cupboard_rows, kind, 60) or []
            legacy = [r for r in rows if not r.get("system3") and not r.get("aired")][:NOMINATE_MOST]
            for r in legacy:
                p = self._proposal("nominate", str(r.get("id")),
                                   "send %s %s (no System 3 stamp) to the retirement desk" % (kind, r.get("id")),
                                   finding=f["id"], before="in the cupboard", after="asked about at the retirement desk",
                                   extra={"kind": kind, "why": f["title"]}, needs_operator=False, station_may=True)
                out.append(p["id"])
        if f["class"] in ("dead_air", "stale_script"):
            rung = "triangulate"
            p = self._proposal("rung", rung, "run the '%s' rung of the broadcast ladder" % rung, finding=f["id"],
                               before=None, after=rung, reversible=False, needs_operator=True)
            out.append(p["id"])
        return out

    def propose_table(self, table_id: str, sets: dict[str, Any], by: str = "operator") -> dict[str, Any]:
        rt = self.rt()
        if rt is None:
            raise ValueError("System 3 is not installed")
        old = next((t for t in (rt.config or {}).get("tables") or [] if t.get("id") == table_id), None)
        if old is None:
            raise ValueError("no table %s (s3 tables lists them)" % table_id)
        new = copy.deepcopy(old)
        for path, value in sets.items():
            set_path(new, path, value)
        import system3
        system3.validate_table(copy.deepcopy(new))       # refused here, not at confirm
        return self._proposal("table", table_id, "table %s" % table_id, before=old, after=new, by=by)

    def propose_section(self, name: str, sets: dict[str, Any], by: str = "operator") -> dict[str, Any]:
        if name not in SECTIONS:
            raise ValueError("no section %s (%s)" % (name, ", ".join(SECTIONS)))
        rt = self.rt()
        old = copy.deepcopy((rt.config or {}).get(name) or {})
        new = copy.deepcopy(old)
        for path, value in sets.items():
            set_path(new, path, value)
        return self._proposal("section", name, "%s section" % name, before=old, after=new, by=by)

    def propose_cupboard(self, rid: str, action: str, by: str = "operator") -> dict[str, Any]:
        kind, row = self._get("cupboard_find")(rid)
        if row is None:
            raise ValueError("no round %s is in the cupboard - it may have aired or been retired" % rid)
        spec = {"cue": ("cue", "cued for the next gap", True, False, True),
                "uncue": ("uncue", "un-cued", True, False, True),
                "finish": ("finish", "sent back to the recording room", False, True, False),
                "retire": ("nominate", "asked about at the retirement desk", True, False, True),
                "remove": ("remove", "REMOVED from the cupboard (not undoable)", False, True, False)}.get(action)
        if spec is None:
            raise ValueError("a cupboard action is cue, uncue, finish, retire or remove")
        door, after, reversible, needs_op, station_may = spec
        return self._proposal(door, rid, "%s %s: %s" % (kind, rid, after), before="as it is", after=after,
                              extra={"kind": kind}, reversible=reversible, needs_operator=needs_op,
                              station_may=station_may, by=by)

    def propose_quarantine(self, sid: str, path: str, why: str, by: str = "operator") -> dict[str, Any]:
        return self._proposal("quarantine", sid, "quarantine clip %s (one-way: its book row goes playable=0)" % sid,
                              before="drawable", after="quarantined", extra={"path": path, "why": why},
                              reversible=False, needs_operator=True, by=by)

    def _live_hash(self) -> str:
        try:
            import system3
            return system3.config_hash(self.rt().config)
        except Exception:  # noqa: BLE001
            return ""

    def _save_config(self, config: dict[str, Any], note: str) -> str:
        """The same door PUT /api/system3/tables and /config/section use: the
        store's versioned save, then the runtime's live config."""
        rt = self.rt()
        import system3
        system3.config_hash(config)
        h = rt.store.save_config(config, note)
        rt.config = config
        try:
            rt.log("System 3 config is now %s (%s)" % (h, note))
        except Exception:  # noqa: BLE001
            pass
        return h

    def _write_table(self, table: dict[str, Any], note: str) -> str:
        import system3
        rt = self.rt()
        tid = table["id"]
        t = system3.validate_table(copy.deepcopy(table))
        config = copy.deepcopy(rt.config)
        old = next((x for x in config["tables"] if x["id"] == tid), None)
        tables = [x for x in config["tables"] if x["id"] != tid]
        if old:
            t["version"] = int(old.get("version") or 1) + 1
            tables.insert(config["tables"].index(old), t)
        else:
            tables.append(t)
        config["tables"] = tables
        return self._save_config(config, note)

    def _write_section(self, name: str, body: Any, note: str) -> str:
        import system3
        if name == "split":
            body = system3.validate_split(body)
        elif name == "blocks":
            body = system3.validate_blocks(body)
        config = copy.deepcopy(self.rt().config)
        config[name] = body
        return self._save_config(config, note)

    def confirm(self, pid: str, who: str = "operator") -> dict[str, Any]:
        p = self.find_proposal(pid)
        if p is None:
            return {"ok": False, "say": "no proposal %s" % pid}
        if p.get("state") != "proposed":
            return {"ok": False, "say": "proposal %s is %s already" % (p["id"], p.get("state"))}
        if who != "operator" and not p.get("station_may"):
            return {"ok": False, "say": "proposal %s waits for the operator: %s" % (
                p["id"], "it cannot be undone" if not p.get("reversible") else "a System 3 change is the operator's to confirm")}
        door, target = p["door"], p["target"]
        say, changed = "", True
        try:
            if door in ("table", "section"):
                live = self._live_hash()
                if p.get("hash_before") and live and live != p["hash_before"]:
                    p["state"] = "stale"
                    self.save()
                    return {"ok": False, "say": "the config moved since this was reviewed (%s, now %s) - review it again"
                                                 % (p["hash_before"], live)}
                h = (self._write_table(p["after"], "table %s by the orchestrator (%s)" % (target, p["id"]))
                     if door == "table" else
                     self._write_section(target, p["after"], "%s section by the orchestrator (%s)" % (target, p["id"])))
                p["hash_after"] = h
                say = "saved %s - live config %s (was %s)" % (p["title"], h, p.get("hash_before"))
            elif door in ("cue", "uncue", "finish", "nominate", "remove"):
                kind, row = self._get("cupboard_find")(target)
                if row is None:
                    raise ValueError("it is no longer in the cupboard")
                if door in ("cue", "uncue"):
                    if door == "cue":
                        row["cue_at"] = time.time()
                    else:
                        row.pop("cue_at", None)
                    saver = self._get("_pantry_save")
                    if callable(saver):
                        saver(True)
                    say = "%s %s" % (target, "is cued for the next gap" if door == "cue" else "is un-cued")
                elif door == "finish":
                    got = self._get("cupboard_finish_add")(kind, row, "sent back by the orchestrator (%s)" % p["id"])
                    say = str(got.get("say") or "sent back to the recording room")
                elif door == "nominate":
                    may = self._get("retire_may")(kind, row, "%s (orchestrator %s)" % (p.get("why") or "", p["id"]))
                    say = ("the retirement desk has it; its rule for %s does not ask, so it stays until you remove it"
                           % kind) if may else "the retirement desk is asking you about %s" % target
                else:
                    got = self._get("retire_decide")([target], "remove", None)
                    say = str(got.get("say") or "it is out of the cupboard")
            elif door == "quarantine":
                ok = self._get("sfx_quarantine")(target, str(p.get("why") or "orchestrator"), p.get("path"),
                                                 by="orchestrator")
                changed = bool(ok)
                say = "clip %s is quarantined" % target if ok else "the quarantine refused it (outside the library, or already in)"
            elif door == "rung":
                return {"ok": False, "say": "a rung runs on the loop: type `run %s`" % target, "rung": target}
            else:
                raise ValueError("no door %s" % door)
        except Exception as exc:  # noqa: BLE001
            p["state"] = "refused"
            p["result"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
            self.mark("act:" + door, False, error=p["result"])
            self.save()
            return {"ok": False, "say": "not done - %s" % p["result"]}
        p.update(state="applied", applied_at=time.time(), applied_by=who, result=say)
        self.mark("act:" + door, True, changed=changed)
        self.note("%s confirmed %s: %s" % (who, p["id"], say), p.get("finding") or "", who)
        self.save()
        return {"ok": True, "say": say, "proposal": p}

    def undo(self, pid: str, who: str = "operator") -> dict[str, Any]:
        p = self.find_proposal(pid)
        if p is None or p.get("state") != "applied":
            return {"ok": False, "say": "nothing to undo for %s" % pid}
        if not p.get("reversible"):
            return {"ok": False, "say": "%s cannot be undone (%s)" % (p["id"], p["title"])}
        door, target = p["door"], p["target"]
        try:
            if door == "table":
                h = self._write_table(p["before"], "table %s undo of %s" % (target, p["id"]))
                say = "put back table %s - live config %s" % (target, h)
            elif door == "section":
                h = self._write_section(target, p["before"], "%s section undo of %s" % (target, p["id"]))
                say = "put back the %s section - live config %s" % (target, h)
            elif door in ("cue", "uncue"):
                kind, row = self._get("cupboard_find")(target)
                if row is None:
                    raise ValueError("it is no longer in the cupboard")
                if door == "cue":
                    row.pop("cue_at", None)
                else:
                    row["cue_at"] = time.time()
                saver = self._get("_pantry_save")
                if callable(saver):
                    saver(True)
                say = "%s is back as it was" % target
            elif door == "nominate":
                got = self._get("retire_decide")([target], "keep", None)
                say = "the retirement desk keeps %s (%s)" % (target, got.get("say") or "kept")
            else:
                raise ValueError("no undo for %s" % door)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "say": "undo failed - %s: %s" % (type(exc).__name__, str(exc)[:200])}
        p.update(state="undone", undo_at=time.time(), undo_by=who, undo_result=say)
        self.mark("undo:" + door, True, changed=True)
        self.note("%s undid %s: %s" % (who, p["id"], say), p.get("finding") or "", who)
        self.save()
        return {"ok": True, "say": say, "proposal": p}

    # ---- the inbox road (the fix at a producer is code, not a dial)
    def file_text(self, f: dict[str, Any]) -> str:
        ev = json.dumps(f.get("evidence") or {}, default=str)[:900]
        return ("[orch-s3] %s\n\nClass: %s (%s). %s\n\nIdentify: %s\n\nResolve: %s\n\nNever: %s\n\nEvidence: %s"
                % (f.get("title"), f.get("class"), f.get("severity"), f.get("triage"),
                   "; ".join(f.get("identify") or []), "; ".join(f.get("resolve") or []), f.get("never"), ev))

    def finding(self, fid: str) -> dict[str, Any] | None:
        v = self.memo.get("value") or {}
        return next((f for f in v.get("findings") or [] if f.get("id") == fid), None)

    # ---- the orchestrator's hooks (sync, memo only)
    def verb(self, verb: str, arg: str, alone: bool = False) -> str:
        who = "station" if alone else "operator"
        arg = str(arg or "").strip()
        if verb == "s3note":
            f = self.finding(arg) or {"title": arg}
            self.note("watching: %s" % f.get("title"), arg, who)
            self.mark("act:note", True)
            return "noted on the System 3 desk and still watching: %s" % str(f.get("title"))[:120]
        if verb == "s3file":
            self.load()
            f = self.finding(arg)
            if f is None:
                return "that finding is no longer on the desk"
            day = time.strftime("%Y-%m-%d")
            with self.lock:
                if self.book["filed"].get(arg) == day:
                    return "already filed today: %s" % str(f.get("title"))[:120]
                self.book["filed"][arg] = day
            self.save()
            append = self._get("pine_append")
            ff = self._get("fire_and_forget")
            if callable(append) and callable(ff):
                ff(append(self.file_text(f)))
                self.mark("act:file", True, changed=True)
                return "filed to the inbox for a fix at the source: %s" % str(f.get("title"))[:120]
            self.mark("act:file", False, error="no inbox door")
            return "the inbox door is not here; noted instead"
        if verb == "s3hold":
            p = self.find_proposal(arg)
            if p and p.get("state") == "proposed":
                p["held_at"] = time.time()
                self.save()
            return "left as it is - %s waits on the desk" % arg
        if verb in ("s3fix", "s3undo"):
            p = self.find_proposal(arg)
            if p is None:
                return "no proposal %s" % arg
            fn = self.confirm if verb == "s3fix" else self.undo
            if p.get("door") in ("table", "section"):
                ff = self._get("fire_and_forget")
                if callable(ff):
                    try:
                        asyncio.get_running_loop()
                        ff(asyncio.to_thread(fn, arg, who))
                        return "%s %s - the result lands on the System 3 desk" % (
                            "confirming" if verb == "s3fix" else "undoing", p.get("title"))
                    except RuntimeError:
                        pass
            return str(fn(arg, who).get("say"))
        return "noted"

    def face(self) -> dict[str, Any]:
        v = self.memo.get("value") or {}
        fs = v.get("findings") or []
        return {"at": v.get("at"), "findings": [{k: f.get(k) for k in ("id", "class", "severity", "title")}
                                                for f in fs[:6]],
                "open_proposals": sum(1 for p in self.book.get("proposals") or [] if p.get("state") == "proposed"),
                "traced_pct": ((v.get("coverage") or {}).get("totals") or {}).get("traced_pct"),
                "mp4_only": (v.get("mp4") or {}).get("mp4_only"), "script_age_s": v.get("script_age_s")}

    def faculties(self) -> dict[str, Any]:
        with self.lock:
            return {k: dict(v) for k, v in self.fac.items()}

    def maybe_survey(self) -> None:
        """From orch_scan's own tick: start the survey on a worker thread when
        the memo is old. Never waits for it."""
        if self.memo.get("running") or time.time() - _f(self.memo.get("at")) < SURVEY_EVERY_S:
            return
        ff = self._get("fire_and_forget")
        try:
            asyncio.get_running_loop()
            if callable(ff):
                ff(asyncio.to_thread(self.survey))
                return
        except RuntimeError:
            pass
        self.survey()

    def ask(self) -> dict[str, Any]:
        """orch_scan's System 3 question: the worst finding he has not asked
        about in half a day, with the playbook's answers as options. The first
        option is always one the station may take alone."""
        self.maybe_survey()
        v = self.memo.get("value") or {}
        recent = self._get("_orch_recent", lambda t, w=ASK_RECENT_S: False)
        raise_ = self._get("orch_raise")
        opt = self._get("_opt", lambda face, does, note="": {"face": face, "does": does, "note": note})
        if not callable(raise_):
            return {}
        self.load()
        for f in v.get("findings") or []:
            if SEVERITY.get(f.get("severity"), 0) < 2:
                continue
            topic = "s3_" + f["class"]
            if recent(topic, ASK_RECENT_S) or _f(self.book["asked"].get(f["id"])) > time.time() - ASK_RECENT_S:
                continue
            filed = self.book["filed"].get(f["id"]) == time.strftime("%Y-%m-%d")
            first = (opt("File it for a fix at the source, and keep watching", "s3file:" + f["id"],
                         "The fix is at the code path; the inbox is where that goes. Filed once a day at most.")
                     if f["severity"] == "high" and not filed else
                     opt("Keep watching - note it on the desk", "s3note:" + f["id"], "Nothing changes."))
            options = [first]
            if first["does"].startswith("s3file"):
                options.append(opt("Only note it", "s3note:" + f["id"], "Nothing changes."))
            elif not filed:
                options.append(opt("File it to the inbox", "s3file:" + f["id"], "Once a day at most."))
            for pid in (f.get("proposals") or [])[:2]:
                p = self.find_proposal(pid)
                if p and p.get("state") == "proposed":
                    options.append(opt(p["title"][:90], "s3fix:" + pid,
                                       ("reversible - s3 undo %s" % pid) if p.get("reversible") else "cannot be undone"))
            why = ("%s. Triage: %s. Identify: %s. Resolve: %s. Never: %s."
                   % (f["title"], f.get("triage") or "", "; ".join(f.get("identify") or [])[:200],
                      "; ".join(f.get("resolve") or [])[:260], f.get("never") or ""))
            row = raise_(topic, why, "now" if f["severity"] == "high" else "soon",
                         [{"ask": "System 3: %s. What should I do?" % f["class"].replace("_", " "),
                           "options": options[:4]}])
            with self.lock:
                self.book["asked"][f["id"]] = time.time()
            self.save()
            self.mark("ask", True, changed=True)
            return row or {}
        return {}

    def judge_note(self, kind: str, row: Any) -> str:
        """For cupboard_judge's prompt: what System 3 says about this round."""
        s = self._get("bank_s3_of", lambda r: {})(row) or {}
        modes = (self.memo.get("value") or {}).get("modes") or {}
        mode = modes.get(kind) or ""
        if s:
            return ("System 3 scripted it (conversation %s, road %s); it is traced when it airs."
                    % (s.get("conversation_id"), s.get("road") or kind))
        if mode == "active":
            return ("It carries NO System 3 stamp, and System 3 directs the %s road now: aired, it would be an "
                    "Untraced (rogue) line. Prefer replace over air unless its words are exceptional." % kind)
        return ("It carries no System 3 stamp; the %s road is %s under System 3, so it would air labelled "
                "'not directed by System 3'." % (kind, mode or "not yet"))

    # ---- the command line: `s3 ...` and `why #code`
    async def command(self, text: str) -> tuple[bool, str, list[str]]:
        parts = str(text or "").split()
        head = (parts[0].lower() if parts else "know")
        rest = parts[1:]
        loop_off = asyncio.to_thread
        try:
            if head in ("know", "help"):
                lines = ["%s - %s | see: %s | act: %s" % (e["name"], e["what"][:90], e["see"], e["act"][:80])
                         for e in ELEMENTS]
                return True, "what System 3 is made of, where I read it and where I may act:", lines
            if head == "playbook":
                keys = [rest[0]] if rest and rest[0] in PLAYBOOK else list(PLAYBOOK)
                lines = []
                for k in keys:
                    b = PLAYBOOK[k]
                    lines.append("%s: %s | triage: %s | resolve: %s | never: %s"
                                 % (k, b["signal"], b["triage"], "; ".join(b["resolve"]), b["never"]))
                return True, "the triage playbook:", lines
            if head in ("survey", "findings", "status"):
                v = (await loop_off(self.survey)) if head == "survey" else (self.memo.get("value") or {})
                fs = v.get("findings") or []
                lines = ["[%s] %s %s - %s | proposals: %s" % (f["severity"], f["class"], f["id"], f["title"],
                                                             ",".join(f.get("proposals") or []) or "none")
                         for f in fs]
                return True, "%d finding(s) on the System 3 desk" % len(fs), lines or ["nothing is wrong that I can see"]
            if head == "why" and rest:
                import line_story
                data = Path(self._get("data_path")("air_log.jsonl")).parent
                ring = [dict(e) for e in list((self._get("_RADIO") or {}).get("chat") or [])[-400:] if isinstance(e, dict)]
                s = await loop_off(line_story.story, data, rest[0], ring)
                self.mark("why", True)
                stages = s.get("stages") or {}
                lines = ["%s: %s" % (k, json.dumps(v, default=str)[:150]) for k, v in list(stages.items())[:8]]
                return True, str(s.get("verdict") or "no verdict"), lines
            if head == "untraced":
                o = await loop_off(self.read_origin, float(rest[0]) if rest else UNTRACED_HOURS)
                u = o["untraced"]
                lines = ["%s x%d on %s" % (g["producer"], g["count"], g["road"]) for g in u.get("by_path") or []]
                lines += ["#%s %s: %s" % (code_of(i["line_id"]), i.get("road"), str(i.get("text"))[:80])
                          for i in (u.get("items") or [])[:5]]
                return True, "%d untraced of %s aired" % (u.get("count") or 0, u.get("items_total")), lines
            if head == "coverage":
                o = await loop_off(self.read_origin)
                c = o["coverage"]
                return True, "traced %s%%" % (c.get("totals") or {}).get("traced_pct"), [
                    "%s: %s%% (rolled %s, forced %s, rogue %s)" % (r["road"], r["traced_pct"], r["rolled"],
                                                                 r["forced"], r["rogue"]) for r in c.get("roads") or []]
            if head == "mp4":
                m = await loop_off(self.read_mp4)
                return True, "MP4 only is %s" % ("ON" if m.get("mp4_only") else "off"), [
                    "refused %s, swapped %s, left empty %s" % (m.get("refused"), m.get("swapped"), m.get("left_empty")),
                    "quarantine: %s clip(s), %d in the last day" % ((m.get("quarantine") or {}).get("clips"),
                                                                    len(m.get("quarantine_recent") or []))]
            if head == "display":
                d = await loop_off(self.read_display, float(rest[0]) if rest else 1.0)
                return True, "SFX display, last hour", [json.dumps(d, default=str)[:600]]
            if head == "receivers":
                r = await loop_off(self.read_receivers)
                return True, "the receivers", ["%s: %s%s%s" % (x.get("id"), "sounding" if x.get("sounding") else "quiet",
                                                               ", audible" if x.get("audible") else "",
                                                               ", owns the air" if x.get("owns_air") else "")
                                               for x in r.get("receivers") or []]
            if head == "tables":
                if rest:
                    rt = self.rt()
                    t = next((x for x in (rt.config or {}).get("tables") or [] if x.get("id") == rest[0]), None)
                    if t is None:
                        return False, "no table %s" % rest[0], []
                    return True, "table %s v%s (%s)" % (t["id"], t.get("version"), t.get("family")), [
                        "%s: weight %s, %d option(s)" % (c.get("id"), c.get("weight", c.get("odds")),
                                                          len(c.get("items") or [])) for c in t.get("categories") or []][:20]
                t = await loop_off(self.read_tables)
                lines = ["%s: %s" % (k, ", ".join(v)) for k, v in sorted(t["families"].items())]
                lines += ["%s %s - %s%s" % (time.strftime("%H:%M", time.localtime(_f(c["at"]))), c["hash"], c["note"],
                                            (" (+%s)" % ",".join(c["added"])) if c.get("added") else "")
                          for c in t["changes"][:10]]
                return True, "config %s: %d table(s), %d change(s) in a day" % (t["hash"], t["tables"],
                                                                                len(t["changes"])), lines
            if head in ("table", "section") and len(rest) >= 3 and rest[1] == "set":
                sets = {}
                for kv in rest[2:]:
                    k, _, v = kv.partition("=")
                    sets[k] = parse_value(v)
                p = (self.propose_table(rest[0], sets) if head == "table" else self.propose_section(rest[0], sets))
                return True, "proposal %s - nothing is saved yet. This will change:" % p["id"], [
                    "%s: %s -> %s" % (c[0], json.dumps(c[1], default=str)[:60], json.dumps(c[2], default=str)[:60])
                    for c in p["changes"][:12]] + ["confirm: s3 confirm %s   (undo afterwards: s3 undo %s)" % (p["id"], p["id"])]
            if head == "cupboard":
                if len(rest) >= 2:
                    p = self.propose_cupboard(rest[0], rest[1].lower())
                    return True, "proposal %s: %s" % (p["id"], p["title"]), [
                        "confirm: s3 confirm %s%s" % (p["id"], "" if p["reversible"] else "  (cannot be undone)")]
                if rest:
                    rows = self.cupboard_rows(rest[0])
                    return True, "%s: %d row(s) shown" % (rest[0], len(rows)), [
                        "%s %s %s%s - %s" % (r["id"], "ready" if r.get("ready") else "blocked" if r.get("blocked") else "-",
                                            "S3" if r.get("system3") else "legacy",
                                            " aired" if r.get("aired") else "", str(r.get("first") or "")[:90])
                        for r in rows]
                c = await loop_off(self.read_cupboard)
                return True, "the cupboard by road (System 3 stamped / unaired / legacy unaired)", [
                    "%s: %d rows, %d stamped, %d unaired, %d legacy unaired" % (
                        k, v["rows"], v["stamped"], v["unaired"], v["unstamped_unaired"])
                    for k, v in sorted(c["roads"].items())]
            if head == "files":
                fm = self._get("_FILEMGR")
                if fm is None:
                    return False, "the file manager is not installed", []
                g = await loop_off(fm.sizes, False)
                return True, "file manager groups (read only here; a run is yours, typed, on its page)", [
                    "%s: %s files, %.1f MB%s" % (x.get("id"), x.get("files"), _f(x.get("bytes")) / 1e6,
                                                 " (destructive)" if x.get("destructive") else "")
                    for x in (g or {}).get("groups") or []]
            if head == "tree" and rest:
                collect = self._get("_ROUNDS_TREE")
                rt = self.rt()
                if not callable(collect) or rt is None:
                    return False, "the decision tree is not installed", []
                origin = Path(self._get("data_path")("system3_origin.sqlite3"))
                got = await loop_off(collect, rt.store, rest[0], None, origin)
                self.mark("tree", True)
                rounds = got.get("rounds") or []
                return True, "segment %s: %d round(s)" % (rest[0], len(rounds)), [
                    json.dumps(r, default=str)[:200] for r in rounds[:6]]
            if head == "proposals":
                ps = list(self.book.get("proposals") or [])[-12:]
                return True, "the last %d proposal(s)" % len(ps), [
                    "%s [%s] %s%s" % (p["id"], p["state"], p["title"],
                                      "" if p.get("reversible") else " (one-way)") for p in reversed(ps)]
            if head in ("confirm", "undo", "hold") and rest:
                if head == "hold":
                    return True, self.verb("s3hold", rest[0]), []
                fn = self.confirm if head == "confirm" else self.undo
                got = await loop_off(fn, rest[0], "operator")
                return bool(got.get("ok")), str(got.get("say")), []
            if head == "faculties":
                return True, "called / runs / changes anything, per faculty", [
                    "%s: called %d, ran %d, changed %d%s" % (k, v["calls"], v["ok"], v["changes"],
                                                             (" - last error " + v["error"]) if v.get("error") else "")
                    for k, v in sorted(self.faculties().items())]
        except Exception as exc:  # noqa: BLE001
            return False, "%s: %s" % (type(exc).__name__, str(exc)[:200]), []
        return False, ("s3 knows: know, playbook, survey, findings, why <code>, untraced, coverage, mp4, display, "
                       "receivers, tables [id], table <id> set k=v, section <name> set k=v, cupboard [road|<id> "
                       "cue|uncue|finish|retire|remove], files, tree <segment>, proposals, confirm/undo/hold <id>, "
                       "faculties"), []


# ------------------------------------------------------------------ install


def install(app: Any, namespace: dict[str, Any]) -> Desk:
    from fastapi import Header, HTTPException, Request

    desk = Desk(namespace, namespace["data_path"](LEDGER_NAME))
    namespace["_ORCH_S3_DESK"] = desk
    namespace["orch_s3_ask"] = desk.ask
    namespace["orch_s3_verb"] = desk.verb
    namespace["orch_s3_face"] = desk.face
    namespace["orch_s3_judge_note"] = desk.judge_note
    namespace["orch_s3_command"] = desk.command
    read_auth, auth = namespace["require_read_auth"], namespace["require_auth"]

    @app.get("/api/orchestrator/system3")
    async def orch_s3_api(authorization: str | None = Header(default=None)):
        """[orch-s3] the orchestrator's System 3 desk: what he knows, what he
        found, what he proposes, and each faculty's called/runs/changes."""
        read_auth(authorization)
        v = desk.memo.get("value") or {}
        return {"schema": SCHEMA, "knowledge": list(ELEMENTS), "playbook": PLAYBOOK, "survey": v,
                "faculties": desk.faculties(), "proposals": list(desk.book.get("proposals") or [])[-40:],
                "notes": list(desk.book.get("notes") or [])[-40:]}

    @app.post("/api/orchestrator/system3/survey")
    async def orch_s3_survey_api(authorization: str | None = Header(default=None)):
        auth(authorization)
        return await asyncio.to_thread(desk.survey)

    @app.post("/api/orchestrator/system3/{action}/{pid}")
    async def orch_s3_act_api(action: str, pid: str, authorization: str | None = Header(default=None)):
        """[orch-s3] confirm or undo one proposal - the operator's press."""
        auth(authorization)
        if action not in ("confirm", "undo"):
            raise HTTPException(404, "confirm or undo")
        fn = desk.confirm if action == "confirm" else desk.undo
        return await asyncio.to_thread(fn, pid, "operator")

    @app.post("/api/orchestrator/system3/propose")
    async def orch_s3_propose_api(request: Request, authorization: str | None = Header(default=None)):
        """[orch-s3] {"table": id | "section": name, "set": {path: value}} or
        {"cupboard": id, "action": cue|uncue|finish|retire|remove} -> a proposal."""
        auth(authorization)
        try:
            b = await request.json()
        except Exception:  # noqa: BLE001
            b = {}
        b = b if isinstance(b, dict) else {}
        try:
            if b.get("table"):
                return desk.propose_table(str(b["table"]), dict(b.get("set") or {}))
            if b.get("section"):
                return desk.propose_section(str(b["section"]), dict(b.get("set") or {}))
            if b.get("cupboard"):
                return desk.propose_cupboard(str(b["cupboard"]), str(b.get("action") or ""))
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        raise HTTPException(400, "table, section or cupboard")

    return desk

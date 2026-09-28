"""[tune-messenger] System 3's Messenger on the public listener page.

"on the tailscale radio station, I want the conversation feed animation like
 we have the messenger tab. It is showing progress. I want users on the
 tailscale using the same version with the most current line assembling the
 same way" (operator, 2026-09-28)

The tune page mounts the desk's own Messenger (frontend/system3.js
mountEmbedded) and hands it a request() that answers every path it asks for
out of ONE small public snapshot polled from here:

    GET /api/system3/public/messenger?t=<tune-in token>&have=<cid:rev,...>

It is the listener door's projection of System 3, built by an allow list,
never by deleting fields from the operator's record:

  * the rounds the air is on (the page feed's recent lines) and the newest
    rounds planned after them, at most MAX_ROUNDS;
  * each message: seat, name, step label, phase, status, emotion and, on a
    turn's first message, its dice - family, what it landed on, the d100 and
    the candidates it rolled through (labels and shares of the wheel only);
  * a message is one run of a turn's ledger lines, by one voice, inside one
    clip, not broken by a sting (a turn split across clips, or answered by
    the other seat's "Mm-hmm.", is several messages, in the air's order);
  * the WORDS of a message only once the clip carrying it has been handed to
    the listener feed AND has reached the station's air (RELEASE_LEAD_MS
    early). A message not yet on the air is its roulette card and nothing in
    the payload carries its words; the writer's whole turn text never
    travels, only the aired lines' own words;
  * each line's id, message, block and order; a board line's clip label, its
    two dice and its poster through a strict public poster road;
  * per line the air state (published / withdrawn) and, for a published line,
    when the station put it on the air and how long it runs, so a phone on the
    car stream can find the line it is hearing behind its own lag.

Never: prompts, sheets, system prompts, directions, subjects/topics, inputs,
settings, seeds, config hashes, weights' reasons, state, material, operator
notes, file paths, or the BLOCK / STATION / DIRECTIVE / PROMPT records.

Everything here is pure: the station hands in its store, its voice ring, its
chat ring and its line stamps, so the trimming and the cache are tested
without importing app.py (tests/test_tune_messenger.py)."""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import re
import time
from typing import Any, Callable, Iterable

SCHEMA = 1
MAX_ROUNDS = 6            # rounds in one snapshot
AIRING_ROUNDS = 3         # of them, found through the lines on the air
AIR_BACK_S = 600          # a line on the air this long ago still places its round
AIR_AHEAD_S = 300         # ... and one published this far ahead of its moment
ORDER_TTL = 2.5           # the snapshot is rebuilt at most this often
TTL_AIRING = 2.5          # a round on the air is re-read this often
TTL_OTHER = 8.0           # any other round
LABEL_MAX = 60
CAND_MAX = 16
TEXT_MAX = 2000
GZIP_MIN = 900
# A line's words are released when the clip that carries it is this close to
# the station's air: enough for the snapshot, the page's poll and the
# Messenger's own look to carry them before the first word sounds, and never
# the words of a clip still waiting its turn.
RELEASE_LEAD_MS = 8000
SEAT_OF = {"dj": "A", "host": "A", "cohost": "B", "third": "D", "caller": "C", "caller2": "E"}

# Decisions a listener may see. A turn's own dice, and the round's.
TURN_FAMILIES = frozenset({"CTS", "ES", "RS", "IRS", "FL", "SPEAKERBOX", "SFX", "SFXGUY", "TOPIC",
                           "TRACK_TALK", "FAV", "TEMPER", "INTERJECT", "MENTION", "SHOCK", "LINE"})
ROUND_FAMILIES = frozenset({"TOPIC", "TEMPER", "SHOCK", "MENTION", "TRACK_TALK", "REPAIR", "ROOM",
                            "TINT", "CARRY", "LENGTH", "VARIANT", "FAV", "INTERJECT"})
# A favourite is the operator's own words: the chip says one landed, not which.
HIDDEN_PICK = {"FAV": "a favourite"}
NO_CANDIDATES = frozenset({"FAV"})
SKIP_STATUS = frozenset({"withheld", "abandoned", "dropped", "simulated", "preview", "failed"})
BOARD_WHO = frozenset({"board"})
QUIET_WHO = frozenset({"board", "drop"})
OFF_STATES = frozenset({"withdrawn", "never", "cut", "dropped"})
POSTER_RE = re.compile(r"^/api/sfx/poster/([a-f0-9]{16})\?t=([a-f0-9]{32})$")
CID_RE = re.compile(r"^[0-9A-Za-z_-]{6,64}$")
REV_RE = re.compile(r"^[0-9a-f]{6,24}$")


# --- small pieces -----------------------------------------------------------
def _txt(value: Any, limit: int) -> str:
    return " ".join(str(value if value is not None else "").split())[:limit]


def _num(value: Any, digits: int | None = None) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        got = float(value)
    except (TypeError, ValueError):
        return None
    if got != got or got in (float("inf"), float("-inf")):
        return None
    return round(got, digits) if digits is not None else got


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _draw(draw: Any) -> dict[str, Any] | None:
    """A recorded draw as a listener sees it: the d100 and where u fell -
    never the seed or the draw number."""
    if not isinstance(draw, dict):
        return None
    out: dict[str, Any] = {}
    dice = _int(draw.get("dice"))
    if dice is not None:
        out["dice"] = dice
    u = _num(draw.get("u"), 4)
    if u is not None:
        out["u"] = u
    return out or None


def _pick_label(ev: dict[str, Any], sel: dict[str, Any]) -> str:
    fam = str(ev.get("family") or "")
    sid = str(sel.get("id") or "")
    if fam in HIDDEN_PICK and sid not in ("", "NONE"):
        return HIDDEN_PICK[fam]
    # An obligated CTS row is the running order's own direction to the
    # writer - a prompt. Only a CTS drawn off its table names the item.
    if fam == "CTS" and not any(isinstance(st, dict) and st.get("stage") in ("item", "mode")
                                for st in ev.get("stages") or []):
        return "the step as planned"
    return _txt(sel.get("label") or sid, LABEL_MAX)


def _stage(st: Any, fam: str) -> dict[str, Any] | None:
    if not isinstance(st, dict):
        return None
    out: dict[str, Any] = {"stage": _txt(st.get("stage"), 24)}
    sel = st.get("selected")
    if isinstance(sel, (int, float)) and not isinstance(sel, bool):
        out["selected"] = _num(sel, 3)
    elif sel is not None:
        out["selected"] = _txt(sel, LABEL_MAX)
    for key in ("selected_index", "of"):
        got = _int(st.get(key))
        if got is not None:
            out[key] = got
    threshold = _num(st.get("threshold"), 3)
    if threshold is not None:
        out["threshold"] = threshold
    if st.get("rule"):
        out["rule"] = _txt(st.get("rule"), 120)
    drawn = _draw(st.get("draw"))
    if drawn:
        out["draw"] = drawn
    cands = st.get("candidates")
    if isinstance(cands, list) and cands and fam not in NO_CANDIDATES:
        rows = [c for c in cands if isinstance(c, dict)]
        keep = rows[:CAND_MAX]
        hit = next((c for c in rows if c.get("id") == st.get("selected")), None)
        if hit is not None and hit not in keep:
            keep = keep[:CAND_MAX - 1] + [hit]
        shaped = []
        for c in keep:
            p = _num(c.get("p"), 3)
            # the wheel's slices as SHARES: enough to draw the roulette and
            # land it where u fell (the page reads p as the slice's weight),
            # never the table weights or the reasons they moved
            shaped.append({"id": _txt(c.get("id"), LABEL_MAX),
                           "label": _txt(c.get("label") or c.get("id"), LABEL_MAX),
                           "p": p if p is not None else 0.0})
        out["candidates"] = shaped
    return out


def trim_event(ev: Any) -> dict[str, Any] | None:
    """One recorded decision, or None when a listener may not see it."""
    if not isinstance(ev, dict) or ev.get("kind") == "observation" or ev.get("stage"):
        return None
    fam = str(ev.get("family") or "")
    turn_id = str(ev.get("turn_id") or "")
    if fam not in (TURN_FAMILIES if turn_id else ROUND_FAMILIES):
        return None
    sel = ev.get("selected") if isinstance(ev.get("selected"), dict) else {}
    pick: dict[str, Any] = {"id": _txt(sel.get("id"), 40), "label": _pick_label(ev, sel)}
    if fam in HIDDEN_PICK and pick["id"] not in ("", "NONE"):
        pick["id"] = "PICKED"
    for key in ("category", "category_label"):
        if sel.get(key) and fam not in HIDDEN_PICK:
            pick[key] = _txt(sel.get(key), 40)
    for key in ("index", "of"):
        got = _int(sel.get(key))
        if got is not None:
            pick[key] = got
    intensity = _num(sel.get("intensity"), 3)
    if intensity is not None:
        pick["intensity"] = intensity
    for key in ("mark", "kind", "placement"):
        if isinstance(sel.get(key), str) and sel.get(key):
            pick[key] = _txt(sel.get(key), 24)
    out: dict[str, Any] = {"event_id": _txt(ev.get("event_id"), 64), "family": fam,
                           "turn_id": turn_id, "selected": pick,
                           "stages": [s for s in (_stage(st, fam) for st in ev.get("stages") or []) if s]}
    turn_index = _int(ev.get("turn_index"))
    if turn_index is not None:
        out["turn_index"] = turn_index
    rng = _draw(ev.get("rng"))
    if rng:
        out["rng"] = rng
    meta = ev.get("meta") if isinstance(ev.get("meta"), dict) else {}
    kept: dict[str, Any] = {}
    for key in ("mark", "door", "act"):
        if isinstance(meta.get(key), str) and meta.get(key):
            kept[key] = _txt(meta.get(key), 24)
    if isinstance(meta.get("applies"), bool):
        kept["applies"] = meta["applies"]
    rate = _num(meta.get("rate"), 3)
    if rate is not None:
        kept["rate"] = rate
    got = _int(meta.get("turn_index"))
    if got is not None:
        kept["turn_index"] = got
    if kept:
        out["meta"] = kept
    return out


def trim_observation(o: Any) -> dict[str, Any] | None:
    """What the station did at air for the SFX Guy - the clip it played and
    his own line - and nothing else (no prompts, no door outcomes, no paths)."""
    if not isinstance(o, dict):
        return None
    fam = str(o.get("family") or "")
    at = _int(o.get("turn_index"))
    if fam == "SFX":
        played = []
        for p in (o.get("played") or [])[:3]:
            if not isinstance(p, dict):
                continue
            roll = p.get("sfx_roll") if isinstance(p.get("sfx_roll"), dict) else {}
            clip = roll.get("clip") if isinstance(roll.get("clip"), dict) else {}
            name = clip.get("label") or re.sub(r"\.[a-z0-9]{2,4}$", "", str(p.get("clip") or ""), flags=re.I)
            played.append({"clip": _txt(name, 80), "why": _txt(p.get("why"), 80),
                           "seconds": _num(p.get("seconds"), 2)})
        matcher = o.get("matcher") if isinstance(o.get("matcher"), dict) else {}
        return {"kind": "observation", "family": "SFX", "turn_index": at, "due": _txt(o.get("due"), 16),
                "played": played,
                "sfx_guy": [{"text": _txt(q.get("text"), 200)} for q in (o.get("sfx_guy") or [])[:3]
                            if isinstance(q, dict) and q.get("text")],
                "matcher": {"cands": _int(matcher.get("cands")), "eligible": _int(matcher.get("eligible"))}}
    if fam == "SFXGUY":
        draws = [{"dice": _int(d.get("dice")), "index": _int(d.get("index")), "of": _int(d.get("of")),
                  "pool": _txt(d.get("pool"), 24)} for d in (o.get("draws") or [])[:4] if isinstance(d, dict)]
        return {"kind": "observation", "family": "SFXGUY", "turn_index": at,
                "planned": _txt(o.get("planned"), 16), "line": _txt(o.get("line"), 400),
                "how": _txt(o.get("how"), 160), "draws": draws,
                "fell_through": [_txt(x, 16) for x in (o.get("fell_through") or [])[:3]]}
    return None


def public_poster(url: Any, sign: Callable[[str], str] | None) -> str:
    """A board line's poster, moved onto the listener door's own strict
    poster road - or "" when it is not one of ours."""
    got = POSTER_RE.match(str(url or ""))
    if not got or sign is None:
        return ""
    sid, sig = got.group(1), got.group(2)
    try:
        if sign(sid) != sig:
            return ""
    except Exception:  # noqa: BLE001
        return ""
    return "/api/system3/public/poster/%s?t=%s" % (sid, sig)


def _roll_face(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    out: dict[str, Any] = {"label": _txt(value.get("label"), 48)}
    for key in ("dice", "of", "index"):
        got = _int(value.get(key))
        if got is not None:
            out[key] = got
    return out


def _attach_media(conv: dict[str, Any]) -> None:
    """[s3-sfx-roll] a board line's rolls and poster ride its COMMIT
    observation; put them on the line (the runtime's line_media, restated so
    this module needs nothing from it)."""
    media: dict[str, Any] = {}
    for o in conv.get("observations_air") or []:
        if isinstance(o, dict) and o.get("family") == "COMMIT" and isinstance(o.get("media"), dict):
            media.update(o["media"])
    for line in conv.get("lines") or []:
        got = media.get(line.get("line_id")) if isinstance(line, dict) else None
        if isinstance(got, dict):
            for key in ("sfx_roll", "poster"):
                if got.get(key) and not line.get(key):
                    line[key] = got[key]


# --- the air, from the station's own rings -----------------------------------
def air_index(clips: Iterable[Any], lead_ms: int = 7000) -> dict[str, dict[str, Any]]:
    """line id -> {"on": the station's on-air ms, "len": seconds, "clip_on":
    the on-air ms of the clip that carries it} for every line the page feed
    has been handed (the voice ring): each row of a welded round at its own
    window, a single clip at its own moment."""
    out: dict[str, dict[str, Any]] = {}
    for clip in clips or []:
        if not isinstance(clip, dict) or clip.get("video") or clip.get("picture_only"):
            continue
        ts = _int(clip.get("ts")) or 0
        on = _int(clip.get("broadcast_ms")) or (ts + int(lead_ms) if ts else 0)
        if not on:
            continue
        stream = clip.get("stream") if isinstance(clip.get("stream"), dict) else {}
        rows = stream.get("rows") if isinstance(stream.get("rows"), list) else None
        if rows:
            for row in rows:
                if not isinstance(row, dict) or not row.get("id"):
                    continue
                a, b = _num(row.get("from")), _num(row.get("until"))
                if a is None or b is None or b < a:
                    continue
                out[str(row["id"])] = {"on": on + int(a * 1000), "len": round(b - a, 2), "clip_on": on}
            continue
        lid = str(clip.get("row_id") or "")
        if lid:
            secs = _num(clip.get("seconds")) or _num(stream.get("length"))
            if not secs:
                secs = max(1.5, min(40.0, len(str(clip.get("text") or "")) / 14.0))
            out[lid] = {"on": on, "len": round(float(secs), 2), "clip_on": on}
    return out


def chat_index(rows: Iterable[Any], publication_states: Iterable[str],
               heard_at: Callable[[Any], float] | None = None) -> dict[str, dict[str, Any]]:
    """line id -> {"state": "published" | "withdrawn" | "", "who", "text"}
    from the chat ring (the booth's own record of every line it wrote)."""
    pub = set(publication_states or ())
    out: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        aired = str(row.get("aired") or "")
        heard = False
        if heard_at is not None:
            try:
                heard = heard_at(row) > 0
            except Exception:  # noqa: BLE001
                heard = False
        if row.get("cut_why") or aired in OFF_STATES or row.get("deleted"):
            state = "withdrawn"
        elif heard or aired in pub:
            state = "published"
        else:
            state = ""
        out[str(row["id"])] = {"state": state, "who": str(row.get("who") or ""),
                               "text": str(row.get("text") or "")}
    return out


# --- one round, trimmed --------------------------------------------------------
def trim_conversation(conv: Any, air: dict[str, dict[str, Any]] | None = None,
                      chat: dict[str, dict[str, Any]] | None = None,
                      stamps: dict[str, Any] | None = None,
                      sign: Callable[[str], str] | None = None,
                      now_ms: int | None = None) -> dict[str, Any] | None:
    """The round as the listener's Messenger reads it, or None when it is not
    a listener's (a shadow plan, a simulation, a preview). `now_ms` is the
    station's clock: the words of a clip are released as it reaches the air."""
    if not isinstance(conv, dict) or not isinstance(conv.get("identity"), dict):
        return None
    if conv.get("mode") != "active":
        return None
    air, chat, stamps = air or {}, chat or {}, stamps or {}
    ident = conv["identity"]
    cid = str(ident.get("conversation_id") or "")
    if not cid:
        return None
    _attach_media(conv)
    turns_in = [t for t in conv.get("turns") or [] if isinstance(t, dict) and t.get("turn_id")]
    turn_ids = {str(t["turn_id"]) for t in turns_in}

    lines_in = [dict(line) for line in conv.get("lines") or [] if isinstance(line, dict) and line.get("line_id")]
    held = {str(line["line_id"]) for line in lines_in}
    # A published line the ledger has not filed under the round yet (its
    # stamp says whose it is): the round still gets its row.
    for lid, stamp in stamps.items():
        if lid in held or not isinstance(stamp, dict) or stamp.get("conversation_id") != cid:
            continue
        if lid not in air:
            continue
        seen = chat.get(lid) or {}
        lines_in.append({"line_id": lid, "turn_id": stamp.get("turn_id") or None,
                         "block": None, "ord": None, "who": seen.get("who") or stamp.get("who") or "",
                         "text": seen.get("text") or ""})
        held.add(lid)

    def state_of(lid: str) -> str:
        seen = (chat.get(lid) or {}).get("state") or ""
        if seen:
            return seen
        return "published" if lid in air else ""

    def released(lid: str, who: str) -> bool:
        """A line's words may travel: a board line is its clip's name; any
        other line once it has been handed to the listener feed AND the clip
        carrying it has reached the air (RELEASE_LEAD_MS early). A line the
        ring no longer remembers but the booth says was published is history."""
        if who in BOARD_WHO:
            return True
        if state_of(lid) != "published":
            return False
        timing = air.get(lid) or {}
        on = _int(timing.get("clip_on")) or _int(timing.get("on"))
        return on is None or on <= now_ms + RELEASE_LEAD_MS

    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    turns_in = [t for t in turns_in if str(t.get("status") or "") != "dropped"]   # never airs
    turn_ids = {str(t["turn_id"]) for t in turns_in}
    by_turn = {str(t["turn_id"]): t for t in turns_in}
    names: dict[str, str] = {}
    for t in turns_in:
        names.setdefault(str(t.get("speaker") or ""), _txt(t.get("name"), 40))

    # THE MESSAGES ARE THE AIR'S. A turn is written whole, but it goes to
    # the air as ledger lines - split across clips, a sting between two of
    # them, the other seat's "Mm-hmm." linked to it. The Messenger shows a
    # turn's words whole once it moves past it, so a whole turn here would
    # put the words of a clip still waiting its turn on the glass. So each
    # run of one turn's lines, by one voice, inside one clip and not broken
    # by a sting, is its own message, in ledger order: the first run of the
    # turn's own seat keeps the turn's id and its dice; the others follow as
    # "continues" / "interjects".
    ordered = sorted(lines_in, key=lambda x: (_int(x.get("block")) or 0, _int(x.get("ord")) or 0))
    runs: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in ordered:
        tid = str(line.get("turn_id") or "")
        who = str(line.get("who") or "")
        if tid not in turn_ids or who in QUIET_WHO:
            cur = None                     # a sting, the SFX Guy's row, a line of no turn
            continue
        block = _int(line.get("block"))
        if cur is not None and cur["tid"] == tid and cur["who"] == who and cur["block"] == block:
            cur["lines"].append(line)
            continue
        cur = {"tid": tid, "who": who, "block": block, "lines": [line]}
        runs.append(cur)
    primary: dict[str, dict[str, Any]] = {}
    for run in runs:
        t = by_turn[run["tid"]]
        own = SEAT_OF.get(run["who"], "") == str(t.get("speaker") or "")
        if run["tid"] not in primary or (own and not primary[run["tid"]]["own"]):
            primary[run["tid"]] = {"run": run, "own": own}
    counter: dict[str, int] = {}
    seg_of: dict[str, str] = {}
    for run in runs:
        tid = run["tid"]
        if primary[tid]["run"] is run:
            run["id"] = tid
        else:
            counter[tid] = counter.get(tid, 0) + 1
            run["id"] = "%s.%d" % (tid, counter[tid])
        for line in run["lines"]:
            seg_of[str(line["line_id"])] = run["id"]

    lines_out: list[dict[str, Any]] = []
    air_out: dict[str, dict[str, Any]] = {}
    for line in lines_in:
        lid = str(line["line_id"])
        who = str(line.get("who") or "")
        tid = str(line.get("turn_id") or "")
        row: dict[str, Any] = {"line_id": lid, "turn_id": seg_of.get(lid) or (tid or None),
                               "block": _int(line.get("block")), "ord": _int(line.get("ord")), "who": _txt(who, 16)}
        if who in BOARD_WHO:
            row["text"] = _txt(line.get("text"), 120)      # the clip's own name on the board
        elif released(lid, who):
            row["text"] = _txt(line.get("text"), 600)
        roll = line.get("sfx_roll") if isinstance(line.get("sfx_roll"), dict) else None
        if roll:
            faces = {k: _roll_face(roll.get(k)) for k in ("category", "clip")}
            faces = {k: v for k, v in faces.items() if v}
            if faces:
                row["sfx_roll"] = faces
        poster = public_poster(line.get("poster"), sign)
        if poster:
            row["poster"] = poster
        lines_out.append(row)
        state = state_of(lid)
        timing = air.get(lid) or {}
        if state or timing:
            entry: dict[str, Any] = {"line_id": lid, "aired": state or "published",
                                     "published": state != "withdrawn", "heard": False}
            if timing:
                entry["on"] = _int(timing.get("on"))
                entry["clip_on"] = _int(timing.get("clip_on")) or entry["on"]
                entry["seconds"] = _num(timing.get("len"), 2)
            air_out[lid] = entry

    events = []
    keep_ids: set[str] = set()
    for ev in conv.get("decision_events") or []:
        got = trim_event(ev)
        if got is None:
            continue
        if got["turn_id"] and got["turn_id"] not in turn_ids:
            continue
        events.append(got)
        keep_ids.add(got["event_id"])

    def turn_row(t: dict[str, Any], run: dict[str, Any] | None) -> dict[str, Any]:
        tid = str(t["turn_id"])
        first = run is None or run["id"] == tid
        perf = t.get("performance") if isinstance(t.get("performance"), dict) else {}
        seat = str(t.get("speaker") or "")
        if run is not None and SEAT_OF.get(run["who"]):
            seat = SEAT_OF[run["who"]]
        own = seat == str(t.get("speaker") or "")
        row: dict[str, Any] = {
            "turn_id": run["id"] if run is not None else tid, "index": _int(t.get("index")) or 0,
            "speaker": _txt(seat, 4),
            "name": (_txt(t.get("name"), 40) if own
                     else (names.get(seat) or _txt(run["who"] if run else "", 40).title())),
            "step_label": (_txt(t.get("step_label"), LABEL_MAX) if first
                           else ("continues" if own else "interjects")),
            "phase": _txt(t.get("phase"), 16), "status": _txt(t.get("status"), 16),
            "estimated_seconds": _num(t.get("estimated_seconds"), 1) if first else None,
            "script_index": _int(t.get("script_index")) if first else None,
            "performance": ({"emotion": _txt(perf.get("emotion"), 32), "intensity": _num(perf.get("intensity"), 3)}
                            if own else {}),
            "decisions": [], "speakerbox": [], "directions": [], "sfx": None, "sfxguy": None}
        if run is not None:
            secs = [_num((air.get(str(x["line_id"])) or {}).get("len")) for x in run["lines"]]
            if not first and secs and all(v is not None for v in secs):
                row["estimated_seconds"] = round(sum(secs), 1)
            if all(released(str(x["line_id"]), run["who"]) for x in run["lines"]):
                words = " ".join(_txt(x.get("text"), 600) for x in run["lines"] if x.get("text"))
                if words:
                    row["text"] = words[:TEXT_MAX]
        if not first:
            return row
        row["decisions"] = [{"event_id": str(d.get("event_id")), "family": _txt(d.get("family"), 16)}
                            for d in t.get("decisions") or []
                            if isinstance(d, dict) and str(d.get("event_id")) in keep_ids]
        # A speaker-box roll rides the turn's decisions: its die shows, and
        # there is no passage to open on the listener's page.
        row["decisions"] += [{"event_id": str(sb.get("event_id")), "family": "SPEAKERBOX"}
                             for sb in t.get("speakerbox") or []
                             if isinstance(sb, dict) and str(sb.get("event_id")) in keep_ids]
        sfx = t.get("sfx") if isinstance(t.get("sfx"), dict) else None
        guy = t.get("sfxguy") if isinstance(t.get("sfxguy"), dict) else None
        if sfx:
            row["sfx"] = {"play": bool(sfx.get("play")), "placement": _txt(sfx.get("placement"), 12),
                          "event_id": str(sfx.get("event_id")) if str(sfx.get("event_id")) in keep_ids else None}
        if guy:
            row["sfxguy"] = {"speak": bool(guy.get("speak")), "kind": _txt(guy.get("kind"), 16),
                             "event_id": str(guy.get("event_id")) if str(guy.get("event_id")) in keep_ids else None}
        return row

    # the air's order: every run where the ledger puts it, then the turns the
    # ledger has not reached yet in the order they were planned
    turns_out = [turn_row(by_turn[run["tid"]], run) for run in runs]
    turns_out += [turn_row(t, None) for t in sorted(turns_in, key=lambda x: _int(x.get("index")) or 0)
                  if str(t["turn_id"]) not in primary]

    observations = [o for o in (trim_observation(x) for x in conv.get("observations_air") or []) if o]
    return {"schema": "tune-messenger/%d" % SCHEMA,
            "identity": {"conversation_id": cid, "road_kind": _txt(ident.get("road_kind"), 24),
                         "revision": _int(ident.get("revision")) or 1},
            "mode": "active", "status": _txt(conv.get("status"), 16),
            "created": _num(conv.get("created"), 3), "subject": {},
            "turns": turns_out, "decision_events": events, "observations_air": observations,
            "lines": lines_out, "public_air": air_out}


def revision(trimmed: dict[str, Any]) -> str:
    blob = json.dumps(trimmed, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def parse_have(have: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in str(have or "").split(",")[:24]:
        cid, _sep, rev = part.strip().partition(":")
        if CID_RE.match(cid) and REV_RE.match(rev):
            out[cid] = rev
    return out


# --- which rounds, and the shared cache ---------------------------------------
def pick_rounds(store: Any, air: dict[str, dict[str, Any]], stamps: dict[str, Any],
                now_ms: int) -> tuple[list[dict[str, Any]], set[str]]:
    """The rounds the air is on (newest line first: what is queued, what is
    sounding, what just ended), then the newest planned rounds. Reader
    thread: `store` is System 3's own."""
    recent = sorted(((int(a.get("on") or 0), lid) for lid, a in air.items()
                     if now_ms - AIR_BACK_S * 1000 <= int(a.get("on") or 0) <= now_ms + AIR_AHEAD_S * 1000),
                    reverse=True)
    airing: list[str] = []
    missed: set[str] = set()
    for _on, lid in recent:
        stamp = stamps.get(lid) if isinstance(stamps.get(lid), dict) else {}
        cid = str(stamp.get("conversation_id") or "")
        if not cid and lid not in missed:
            try:
                row = store.line(lid)
            except Exception:  # noqa: BLE001
                row = None
            cid = str((row or {}).get("conversation_id") or "")
            if not cid:
                missed.add(lid)
        if cid and cid not in airing:
            airing.append(cid)
            if len(airing) >= AIRING_ROUNDS:
                break
    order: list[dict[str, Any]] = []
    rows: list[Any] = []
    try:
        rows = store.conversations(limit=16) or []
    except Exception:  # noqa: BLE001
        rows = []
    meta = {str(r.get("conversation_id") or ""): r for r in rows if isinstance(r, dict)}
    wanted = list(airing)
    for r in rows:
        if not isinstance(r, dict):
            continue
        cid = str(r.get("conversation_id") or "")
        if (cid and cid not in wanted and r.get("mode") == "active"
                and str(r.get("status") or "") not in SKIP_STATUS):
            wanted.append(cid)
        if len(wanted) >= MAX_ROUNDS:
            break
    for cid in wanted[:MAX_ROUNDS]:
        r = meta.get(cid) or {}
        order.append({"conversation_id": cid, "mode": "active",
                      "road": _txt(r.get("road"), 24), "status": _txt(r.get("status"), 16),
                      "created": _num(r.get("created"), 3)})
    return order, set(airing)


class PublicMessenger:
    """One snapshot for every listener: rebuilt at most every ORDER_TTL, each
    round re-read only when its own TTL has run out, and answered per
    listener with only the rounds whose revision it does not hold."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self.at = 0.0
        self.order: list[dict[str, Any]] = []
        self.rounds: dict[str, dict[str, Any]] = {}    # cid -> {at, rev, body(bytes)}
        self.seq = 0
        self.builds = 0
        self.lock: asyncio.Lock | None = None

    def stale(self) -> bool:
        return self.clock() - self.at >= ORDER_TTL

    def build(self, store: Any, air: dict[str, dict[str, Any]], chat: dict[str, dict[str, Any]],
              stamps: dict[str, Any], sign: Callable[[str], str] | None = None) -> None:
        """Runs on System 3's reader thread (the store is only ever read
        there). `air` and `chat` are air_index() and chat_index() of the
        station's rings and `stamps` a copy of its line stamps, all taken on
        the event loop, so nothing here walks a list the station appends to."""
        now = self.clock()
        order, airing = pick_rounds(store, air, stamps, int(now * 1000))
        changed = [o["conversation_id"] for o in order] != [o["conversation_id"] for o in self.order]
        kept_order = []
        for o in order:
            cid = o["conversation_id"]
            held = self.rounds.get(cid)
            ttl = TTL_AIRING if cid in airing else TTL_OTHER
            if held is None or now - held["at"] >= ttl:
                try:
                    conv = store.conversation(cid)
                except Exception:  # noqa: BLE001
                    conv = None
                trimmed = trim_conversation(conv, air, chat, stamps, sign, int(now * 1000))
                self.builds += 1
                if trimmed is None:
                    self.rounds.pop(cid, None)
                    changed = True
                    continue
                rev = revision(trimmed)
                if held is None or held["rev"] != rev:
                    changed = True
                self.rounds[cid] = {"at": now, "rev": rev,
                                    "body": json.dumps(trimmed, separators=(",", ":"), default=str).encode("utf-8")}
            kept_order.append(o)
        for cid in [c for c in self.rounds if c not in {o["conversation_id"] for o in kept_order}]:
            if now - self.rounds[cid]["at"] > 120:
                self.rounds.pop(cid, None)
        self.order = kept_order
        self.at = now
        if changed:
            self.seq += 1

    async def refresh(self, run: Callable[..., Any], *args: Any) -> None:
        """Single flight: every listener that finds the snapshot stale waits
        on the same build. `run(fn, *args)` puts it on the reader thread."""
        if self.lock is None:
            self.lock = asyncio.Lock()
        async with self.lock:
            if not self.stale():
                return
            await run(self.build, *args)

    def answer(self, have: Any = "", gzip_ok: bool = False, now_ms: int | None = None,
               off: bool = False) -> tuple[bytes, dict[str, str]]:
        held = parse_have(have)
        now_ms = int(self.clock() * 1000) if now_ms is None else int(now_ms)
        order = [] if off else self.order
        parts = [b'{"v":', str(SCHEMA).encode(), b',"server_ms":', str(now_ms).encode(),
                 b',"seq":', str(self.seq).encode(), b',"off":', b"true" if off else b"false",
                 b',"order":', json.dumps(order, separators=(",", ":")).encode("utf-8"), b',"convs":{']
        first = True
        for o in order:
            cid = o["conversation_id"]
            got = self.rounds.get(cid)
            if not got:
                continue
            parts.append(b"" if first else b",")
            first = False
            parts.append(json.dumps(cid).encode("utf-8") + b":")
            if held.get(cid) == got["rev"]:
                parts.append(b'{"rev":"' + got["rev"].encode() + b'"}')
            else:
                parts.append(b'{"rev":"' + got["rev"].encode() + b'","conv":' + got["body"] + b"}")
        parts.append(b"}}")
        body = b"".join(parts)
        headers = {"Cache-Control": "no-store", "Vary": "Accept-Encoding",
                   "X-Content-Type-Options": "nosniff"}
        if gzip_ok and len(body) >= GZIP_MIN:
            body = gzip.compress(body, 6)
            headers["Content-Encoding"] = "gzip"
        return body, headers


# --- static files for the page, compressed and revalidated --------------------
class StaticFiles:
    """[tune-messenger] the Messenger's three files for the listener door:
    ETag + 304 (FileResponse has neither, so /system3/system3.js is 441 kB
    on every page load) and gzip when the phone accepts it (130 kB)."""

    def __init__(self, files: dict[str, Any]) -> None:
        self.files = dict(files)
        self.held: dict[str, dict[str, Any]] = {}

    def load(self, name: str) -> dict[str, Any] | None:
        path = self.files.get(name)
        if path is None:
            return None
        try:
            st = path.stat()
        except OSError:
            return None
        key = (st.st_mtime_ns, st.st_size)
        got = self.held.get(name)
        if got and got["key"] == key:
            return got
        raw = path.read_bytes()
        tag = hashlib.sha1(raw).hexdigest()[:20]
        got = {"key": key, "raw": raw, "gz": gzip.compress(raw, 6), "etag": '"%s"' % tag,
               "etag_gz": '"%s-gz"' % tag,
               "type": ("text/css; charset=utf-8" if name.endswith(".css")
                        else "application/javascript; charset=utf-8")}
        self.held[name] = got
        return got

    @staticmethod
    def matches(if_none_match: str, got: dict[str, Any]) -> bool:
        wanted = {x.strip().removeprefix("W/") for x in str(if_none_match or "").split(",") if x.strip()}
        return bool(wanted & {got["etag"], got["etag_gz"], "*"})

    def respond(self, name: str, if_none_match: str = "", gzip_ok: bool = False
                ) -> tuple[int, bytes, dict[str, str]]:
        got = self.load(name)
        if got is None:
            return 404, b"", {}
        use_gz = gzip_ok and len(got["gz"]) < len(got["raw"])
        headers = {"Cache-Control": "no-cache", "Vary": "Accept-Encoding",
                   "ETag": got["etag_gz"] if use_gz else got["etag"],
                   "X-Content-Type-Options": "nosniff", "Content-Type": got["type"]}
        if self.matches(if_none_match, got):
            return 304, b"", headers
        if use_gz:
            headers["Content-Encoding"] = "gzip"
            return 200, got["gz"], headers
        return 200, got["raw"], headers

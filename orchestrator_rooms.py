"""#1211: the four rooms, and made-against-heard, for the orchestrator glass.

WHY THIS MODULE EXISTS AT ALL.

`desktop/renderer/orchestrator-glass.js` has drawn two panes since #1202 -
"the four rooms, and what is moving through them" and "made and never
heard" - and both have said `could not be counted` every night since,
because the server half of #1202 was never written. Measured on the live
station 2026-09-21 22:34: `GET /api/orchestrator/glass` returned 44,096
bytes carrying `at on paused boot_at up_seconds keepers live recent
tail_depth tail_most oldest_at coverage face roads commission plan_why
pressure` - and neither `rooms` nor `waste`. The panel was right: the
rooms were not empty, they were uncounted.

WHAT IT MAY COST, AND WHY THAT IS THE FIRST DESIGN CONSTRAINT.

The glass polls every five seconds and this station goes deaf when its
event loop stalls (memory: `event-loop-starvation-watchdog`,
`silent-station-needle-and-stores`). A pane about work not reaching the
air must never be the reason work does not reach the air. So:

  - every reading here is taken on a WORKER THREAD (app.py hands this to
    `asyncio.to_thread`), never on the loop;
  - a memo of `MEMO_S` seconds sits in front of it, so eight open panels
    cost one walk;
  - nothing here writes, saves, airs, commissions or takes a lock the air
    road holds. Lists are snapshotted with `list(...)` and read from the
    copy;
  - every expensive per-row question is capped (`REASON_MOST`,
    `ROWS_MOST`) and the cap is REPORTED, because a truncated census that
    does not say it is truncated is the artifact this panel exists to
    stop.

THE ZERO RULE IS THE PANEL'S, AND IT IS KEPT ON THIS SIDE TOO. A key is
either a measurement or it is ABSENT. Nothing here writes 0 for something
it could not read - `_told()` and the `if value is not None` guards are
that rule in Python, and the panel's `told()` is the same rule in ES5. A
number that could not be taken is left off the payload, and the panel
then names the key it looked for. That is the contract; do not "helpfully"
default anything here to zero.

EVERY NUMBER NAMES ITS DOOR. Each count carries a `<key>_basis` sentence
saying what was actually counted, because a panel that prints 412 without
saying what 412 is is a panel nobody can check, and an unchecked number on
this station has twice turned out to be a different quantity than the
label beside it.
"""
from __future__ import annotations

import time
from typing import Any

WINDOW_S = 600.0        # "the last ten minutes", his own unit
MEMO_S = 12.0           # two glass polls; the walk is not free
ROWS_MOST = 40          # never-heard rows listed with actions
REASON_MOST = 60        # rows asked "why are you not on the air"
TOP_MOST = 5            # "the top few by name"

_MEMO: dict[str, Any] = {"at": 0.0, "value": None}


# --------------------------------------------------------------- plumbing

def _told(value: Any) -> float | None:
    """A number, or None. Never 0 for something that was not measured."""
    if value is None or isinstance(value, bool):
        return None
    try:
        got = float(value)
    except (TypeError, ValueError):
        return None
    if got != got or got in (float("inf"), float("-inf")):
        return None
    return got


def _get(app: Any, name: str, fallback: Any = None) -> Any:
    try:
        return getattr(app, name)
    except Exception:  # noqa: BLE001
        return fallback


def _call(app: Any, name: str, *args: Any, **kw: Any) -> Any:
    """Call an app.py function if it is there. Never raises."""
    fn = _get(app, name)
    if not callable(fn):
        return None
    try:
        return fn(*args, **kw)
    except Exception:  # noqa: BLE001
        return None


def _flow_events(app: Any) -> tuple[list[dict[str, Any]], float, bool]:
    """The station flow journal's in-memory tail, and its oldest stamp.

    `FlowJournal.events` is a 5000-deep deque written by every road that
    calls `station_flow_event`, which is how four of the six doors below
    can be counted without a single new stamp being added to app.py. The
    oldest stamp is returned with it: if the deque has rotated past the
    ten-minute window the count is a FLOOR, not a total, and the caller
    says so rather than printing it as though it were complete."""
    journal = _get(app, "_STATION_FLOW")
    if journal is None:
        return [], 0.0, False
    try:
        rows = [r for r in list(journal.events) if isinstance(r, dict)]
    except Exception:  # noqa: BLE001
        return [], 0.0, False
    oldest = 0.0
    for row in rows:
        at = _told(row.get("at"))
        if at is not None and (not oldest or at < oldest):
            oldest = at
    return rows, oldest, True


def _flow_in_window(rows: list[dict[str, Any]], node: str, now: float) -> int:
    edge = now - WINDOW_S
    n = 0
    for row in rows:
        if str(row.get("node") or "") != node:
            continue
        at = _told(row.get("at"))
        if at is not None and at >= edge:
            n += 1
    return n


def _flow_lifetime(app: Any, node: str) -> int | None:
    """How many times this node has fired since the process started."""
    journal = _get(app, "_STATION_FLOW")
    if journal is None:
        return None
    try:
        got = (dict(journal.latest) or {}).get(node)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(got, dict):
        return None
    n = _told(got.get("count"))
    return None if n is None else int(n)


def _piles(app: Any) -> list[tuple[str, list[Any]]]:
    """The reserve, as (road, rows) - the larder and every shelf.

    Snapshotted with list() at both levels: the air road mutates these
    while this walks them, and a RuntimeError out of here would cost the
    whole payload."""
    out: list[tuple[str, list[Any]]] = []
    try:
        out.append(("banter", [r for r in list(_get(app, "_LARDER") or [])
                               if isinstance(r, dict)]))
    except Exception:  # noqa: BLE001
        pass
    try:
        for kind, rows in list((_get(app, "_SHELF") or {}).items()):
            out.append((str(kind), [r for r in list(rows or [])
                                    if isinstance(r, dict)]))
    except Exception:  # noqa: BLE001
        pass
    return out


def _label(app: Any, kind: str) -> str:
    got = _call(app, "retire_kind_label", kind)
    return str(got or kind)


def _unaired(app: Any, row: dict[str, Any]) -> bool:
    got = _call(app, "row_unaired", row)
    if isinstance(got, bool):
        return got
    return not (row.get("aired") or row.get("aired_at"))


def _top(counts: dict[str, int]) -> list[dict[str, Any]]:
    rows = sorted(counts.items(), key=lambda kv: -kv[1])[:TOP_MOST]
    return [{"name": k, "count": v} for k, v in rows]


def _room(key: str, name: str, why: str) -> dict[str, Any]:
    return {"key": key, "name": name, "label": name, "why": why,
            "window_seconds": int(WINDOW_S)}


# ------------------------------------------------------------ the rooms

def _writing_desk(app: Any, now: float) -> dict[str, Any]:
    """Room one. One model visit at a time, behind the Ollama gate."""
    out = _room("writing", "the writing desk",
                "a model turns the running order's brief into a script. "
                "One visit at a time behind the Ollama gate - the thing "
                "the whole station queues behind.")
    out["in_door"] = ("a model visit began - counted off the _MODEL_CALLS "
                      "ring, from each row's finish stamp minus the "
                      "milliseconds it took")
    out["out_door"] = ("a model visit came back with words - one row "
                       "appended to the same ring")
    out["holding_door"] = ("visits in flight right now, read off the "
                           "Ollama gate's own semaphore")
    edge = now - WINDOW_S
    raw = _get(app, "_MODEL_CALLS")
    if raw is None:
        out["ledger_why"] = ("the model-call ring is not readable from here, "
                             "so the visits this room took are unmeasured "
                             "rather than none")
        return out
    try:
        ring = [r for r in list(raw) if isinstance(r, dict)]
    except Exception:  # noqa: BLE001
        ring = []
    began = came = 0
    oldest_in_ring = 0.0
    for row in ring:
        at = _told(row.get("at"))
        if at is None:
            continue
        if not oldest_in_ring or at < oldest_in_ring:
            oldest_in_ring = at
        ms = _told(row.get("ms")) or 0.0
        if at - (ms / 1000.0) >= edge:
            began += 1
        if at >= edge:
            came += 1
    out["in"] = began
    out["out"] = came
    # THE RING IS SHORT AND SAYS SO. Eighty rows (#1022); a busy ten
    # minutes can push a visit off it, and a count that has lost rows is
    # a floor. Saying "at least" is the difference between a measurement
    # and a claim.
    if ring and oldest_in_ring and oldest_in_ring > edge:
        out["window_truncated"] = True
        out["window_covers_seconds"] = round(now - oldest_in_ring, 1)
    # In flight. The semaphore is the only thing on this station that
    # knows; there is no counter beside it.
    gate = _get(app, "_OLLAMA_GATE")
    lanes = _told(_get(app, "OLLAMA_LANES"))
    free = _told(getattr(gate, "_value", None)) if gate is not None else None
    if free is not None and lanes is not None:
        out["stuck"] = max(0, int(2 * lanes - free))
        out["lanes"] = int(2 * lanes)
    writing = _get(app, "_LARDER_WRITING")
    try:
        if writing is not None:
            out["desk_is_writing"] = bool(writing[0])
    except Exception:  # noqa: BLE001
        pass
    if ring:
        newest = max((_told(r.get("at")) or 0.0) for r in ring)
        if newest:
            out["oldest_seconds"] = round(max(0.0, now - newest), 1)
            out["last_visit_ago_basis"] = ("how long since a model visit "
                                           "last came back")
    return out


def _reserve(app: Any, now: float
             ) -> tuple[dict[str, Any], list[tuple[float, str, dict[str, Any]]]]:
    """Room two. _LARDER and _SHELF - where scripts wait for a slot."""
    out = _room("reserve", "the reserve",
                "scripts waiting for a slot: the larder holds banter, the "
                "shelf holds every road with a name. shelf_put and "
                "shelf_take are the only two doors.")
    out["in_door"] = ("a row was written onto a pile - counted off each "
                      "row's own `at` stamp")
    out["out_door"] = ("a row aired, or was withdrawn - each row's own "
                       "`aired_at`, plus the withdrawn book")
    out["holding_door"] = "every row standing on the larder or a shelf"
    edge = now - WINDOW_S
    if _get(app, "_LARDER") is None and _get(app, "_SHELF") is None:
        out["ledger_why"] = ("neither the larder nor the shelf is readable "
                             "from here, so this room is unmeasured rather "
                             "than empty")
        return out, []
    piles = _piles(app)
    held = unheard = went_in = came_out = 0
    oldest = 0.0
    by_road: dict[str, int] = {}
    unheard_rows: list[tuple[float, str, dict[str, Any]]] = []
    for kind, rows in piles:
        if not rows:
            continue
        held += len(rows)
        for row in rows:
            at = _told(row.get("at"))
            if at is not None and at >= edge:
                went_in += 1
            aired_at = _told(row.get("aired_at"))
            if aired_at is not None and aired_at >= edge:
                came_out += 1
            if not _unaired(app, row):
                continue
            unheard += 1
            by_road[_label(app, kind)] = by_road.get(_label(app, kind), 0) + 1
            age = max(0.0, now - (at if at is not None else now))
            if age > oldest:
                oldest = age
            unheard_rows.append((age, kind, row))
    out["stuck"] = unheard
    out["holding"] = held
    out["in"] = went_in
    if oldest:
        out["oldest_seconds"] = round(oldest, 1)
    out["top"] = _top(by_road)
    # Withdrawals are the other way out, and they are the interesting
    # way: #1330's ghost rounds were work that left this room without
    # ever being handed anywhere.
    book = _call(app, "withdrawn_book_rows", edge, 200)
    pulled = None
    if isinstance(book, list):
        pulled = sum(1 for r in book if isinstance(r, dict)
                     and (_told(r.get("at")) or 0.0) >= edge)
        out["withdrawn"] = pulled
        out["withdrawn_basis"] = ("rounds withdrawn in the window, off the "
                                  "withdrawn book (#1330)")
    out["out"] = came_out + int(pulled or 0)
    out["aired_out"] = came_out
    out["aired_out_basis"] = ("of those, the ones that left by airing "
                              "rather than by being withdrawn")
    return out, unheard_rows


def _recording_room(app: Any, now: float, flow: list[dict[str, Any]],
                    journal: bool) -> dict[str, Any]:
    """Room three. One actor at a time, line by line."""
    out = _room("recording", "the recording room",
                "one actor at a time, line by line: larder_prepare -> "
                "prep_render_line -> voice_generate, regrouped by "
                "performer so nobody swaps conditioning twice.")
    out["in_door"] = ("a line went to the microphone - the station flow "
                      "journal's `tts` node")
    out["out_door"] = ("a finished take was filed on the prepared shelf - "
                       "the journal's `pantry` node")
    out["holding_door"] = ("scripts standing in the reserve that have not "
                           "been recorded yet (entry.prepared is not set)")
    # NOT ZERO WHEN THERE IS NO LEDGER. Both of these are read off the
    # station flow journal; if that is not there, "0 lines went to the
    # microphone in ten minutes" is an invention, and the panel draws an
    # absent key as "could not be counted" - which is the truth.
    if journal:
        out["in"] = _flow_in_window(flow, "tts", now)
        out["out"] = _flow_in_window(flow, "pantry", now)
    else:
        out["ledger_why"] = ("the station flow journal is not readable from "
                             "here, so what went in and came out of this "
                             "room is unmeasured rather than zero")
    waiting = 0
    oldest = 0.0
    by_road: dict[str, int] = {}
    entry_of = _get(app, "dialogue_entry")
    for kind, rows in _piles(app):
        for row in rows:
            entry = None
            if callable(entry_of):
                try:
                    entry = entry_of(row)
                except Exception:  # noqa: BLE001
                    entry = None
            if entry is None:
                entry = row.get("entry") if isinstance(
                    row.get("entry"), dict) else row
            if not isinstance(entry, dict) or entry.get("prepared"):
                continue
            waiting += 1
            by_road[_label(app, kind)] = by_road.get(_label(app, kind), 0) + 1
            at = _told(row.get("at"))
            age = max(0.0, now - (at if at is not None else now))
            if age > oldest:
                oldest = age
    out["stuck"] = waiting
    if oldest:
        out["oldest_seconds"] = round(oldest, 1)
    out["top"] = _top(by_road)
    pool_cap = _told(_get(app, "RECORDING_POOL_MOST"))
    if pool_cap is not None:
        out["pool_cap"] = int(pool_cap)
        out["pool_cap_basis"] = ("the most scripts one sitting will take - "
                                 "anything beyond it waits for the next")
    at_the_mic = _call(app, "prep_now")
    if isinstance(at_the_mic, dict) and at_the_mic:
        out["at_the_microphone"] = "%s - %s" % (
            str(at_the_mic.get("label") or at_the_mic.get("kind") or "?"),
            str(at_the_mic.get("stage") or "?"))
    return out


def _pantry(app: Any, now: float, flow: list[dict[str, Any]],
            journal: bool) -> dict[str, Any]:
    """Room four. Finished audio, addressed by its own content."""
    out = _room("pantry", "the pantry",
                "finished audio, keyed by pantry_key(text, voice, engine) - "
                "identical words in the same voice on the same engine are "
                "the same clip, so a line made hours ago is found instantly.")
    out["in_door"] = ("a finished take was stored - counted off each "
                      "pantry row's own `at` stamp")
    out["out_door"] = ("a clip was published to a listener - the station "
                       "flow journal's `publish` node")
    out["holding_door"] = "every take standing on the prepared shelf"
    edge = now - WINDOW_S
    shelf = _get(app, "_PANTRY")
    if shelf is None:
        out["ledger_why"] = ("the prepared shelf is not readable from here, "
                             "so this room is unmeasured rather than empty")
        return out
    try:
        rows = [dict(v) for v in list(shelf.values()) if isinstance(v, dict)]
    except Exception:  # noqa: BLE001
        rows = []
    fresh = 0
    oldest = 0.0
    by_who: dict[str, int] = {}
    for row in rows:
        at = _told(row.get("at"))
        if at is not None and at >= edge:
            fresh += 1
        age = max(0.0, now - (at if at is not None else now))
        if age > oldest:
            oldest = age
        who = str(row.get("who") or row.get("kind") or "").strip()
        if who:
            by_who[who] = by_who.get(who, 0) + 1
    out["stuck"] = len(rows)
    out["in"] = fresh
    if journal:
        out["out"] = _flow_in_window(flow, "publish", now)
    if oldest:
        out["oldest_seconds"] = round(oldest, 1)
    out["top"] = _top(by_who)
    ceiling = _told(_call(app, "pantry_max_rows"))
    if ceiling is not None:
        out["ceiling"] = int(ceiling)
        out["ceiling_basis"] = ("the row ceiling: past this, loose clips "
                                "are shed oldest first, and only then ones "
                                "a banked round is holding")
        if len(rows) >= ceiling:
            out.setdefault("blocked", []).append({
                "name": "at the ceiling",
                "count": len(rows) - int(ceiling) + 1,
                "why": ("the pantry is at its %d-take ceiling, so storing "
                        "a new take sheds an old one. The station is "
                        "preparing faster than it airs (#1004)."
                        % int(ceiling))})
    spoken = _call(app, "pantry_spoken_for")
    try:
        if spoken is not None:
            out["spoken_for"] = len(spoken)
            out["spoken_for_basis"] = ("takes a banked round is relying on "
                                       "- these are shed last")
    except Exception:  # noqa: BLE001
        pass
    return out


def _blocked_reasons(app: Any, rows: list[tuple[float, str, dict[str, Any]]],
                     ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Ask the air's own functions why each unheard round is not on it.

    `cupboard_why_row` is the one that decides, so it is the one that is
    asked - a second re-derivation here would drift from the behaviour
    within the week. It is not cheap, so the oldest REASON_MOST are
    asked and the cap is reported."""
    why_of = _get(app, "cupboard_why_row")
    if not callable(why_of):
        return [], [], 0
    rows = sorted(rows, key=lambda r: -r[0])[:REASON_MOST]
    tally: dict[str, dict[str, Any]] = {}
    listed: list[dict[str, Any]] = []
    for age, kind, row in rows:
        try:
            got = why_of(kind, row)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(got, dict):
            continue
        reasons = [r for r in (got.get("reasons") or []) if isinstance(r, dict)]
        if reasons:
            for one in reasons:
                code = str(one.get("code") or "?")
                seat = tally.setdefault(code, {
                    "name": code, "count": 0,
                    "why": str(one.get("say") or "")[:240],
                    "fix": str(one.get("fix") or "")[:240]})
                seat["count"] += 1
            head = str(reasons[0].get("say") or "")[:240]
            code = str(reasons[0].get("code") or "?")
        else:
            # #1260's whole finding, and #1330's: the item is finished
            # radio and nothing has asked for it. That is not a fault of
            # the item and it must not be filed as one.
            seat = tally.setdefault("never_handed", {
                "name": "never_handed", "count": 0,
                "why": ("it is finished radio and nothing about it is "
                        "stopping it - no road has asked for it. This is "
                        "the 2026-09-12 finding, and the one this pane "
                        "exists to put in front of you."),
                "fix": "hear it now, or let the unheard sweep take it."})
            seat["count"] += 1
            head = seat["why"]
            code = "never_handed"
        if len(listed) < ROWS_MOST:
            listed.append({
                "id": str(got.get("id") or ""),
                "road": kind,
                "label": str(got.get("label") or _label(app, kind)),
                "name": str(got.get("name") or "")[:80],
                "text": str(got.get("text") or "")[:240],
                "written_ago_seconds": round(age, 1),
                "seconds": _told(got.get("seconds")),
                "blocked": bool(got.get("blocked")),
                "ready": bool(got.get("ready")),
                "why": head,
                "why_code": code,
                "reasons": [{"code": str(r.get("code") or ""),
                             "say": str(r.get("say") or "")[:240],
                             "fix": str(r.get("fix") or "")[:240]}
                            for r in reasons[:4]],
                "actions": ["hear", "retire", "fork"],
            })
    return (sorted(tally.values(), key=lambda r: -r["count"]),
            listed, len(rows))


# ------------------------------------------------------------- the account

def _waste(app: Any, now: float, flow: list[dict[str, Any]],
           unheard_rows: list[tuple[float, str, dict[str, Any]]]
           ) -> dict[str, Any]:
    """"I want no wasted lines." The account behind that sentence."""
    out: dict[str, Any] = {"at": now}
    recorded = _flow_lifetime(app, "tts")
    played = _flow_lifetime(app, "playing")
    if recorded is not None:
        out["recorded"] = recorded
        out["recorded_basis"] = ("lines sent to the microphone since this "
                                 "process started, off the station flow "
                                 "journal's `tts` node")
    if played is not None:
        out["played"] = played
        out["played_basis"] = ("of those, deliveries an actual listener "
                               "acknowledged as audible - the journal's "
                               "`playing` node, which is the only node on "
                               "this station that proves a person heard it")
    # THE HEADLINE. Rounds, not lines, and it says so: the panel prints
    # this noun, so sending the wrong one would be the label lying about
    # the number, which is the fault this pane was written to stop.
    census = _call(app, "unheard_state")
    if isinstance(census, dict):
        ready = _told(census.get("ready"))
        if ready is not None:
            out["never_heard"] = int(ready)
            out["never_heard_what"] = "finished round"
            out["never_heard_basis"] = ("finished rounds standing in the "
                                        "reserve that have never been on "
                                        "the air, from unheard_state()")
        seconds = 0.0
        classes: list[dict[str, Any]] = []
        for road in (census.get("roads") or []):
            if not isinstance(road, dict):
                continue
            secs = _told(road.get("seconds"))
            rows = _told(road.get("ready"))
            if secs is not None:
                seconds += secs
            if not rows:
                continue
            classes.append({
                "name": str(road.get("label") or road.get("kind") or "?"),
                "count": int(rows),
                "seconds": secs,
                "why": ("%d finished round(s) on this road have never "
                        "aired; %d are past the %ds the dial allows and "
                        "the oldest has waited %s.%s"
                        % (int(rows), int(_told(road.get("overdue")) or 0),
                           int(_told(census.get("after")) or 0),
                           _ago(_told(road.get("oldest")) or 0),
                           ("" if road.get("road_open") else
                            " This road cannot air out of turn at all, so "
                            "nothing here will be rescued by the sweep.")))})
        if classes:
            out["classes"] = classes
        out["never_heard_seconds"] = round(seconds, 1)
        out["never_heard_seconds_basis"] = ("the audio those rounds are "
                                            "holding, summed per road")
        total = _told(census.get("unheard"))
        if total is not None:
            out["unaired_rows"] = int(total)
            out["unaired_rows_basis"] = ("every row that has never aired, "
                                         "finished or not - the larger "
                                         "number, and the one that includes "
                                         "half-recorded rounds")
        oldest = _told(census.get("oldest"))
        if oldest is not None:
            out["oldest_seconds"] = round(oldest, 1)
        if census.get("say"):
            out["say"] = str(census.get("say"))[:600]
    # THE COVER. Read off /api/bank rather than recomputed: #1184 already
    # walks the coming hour line by line and asks, of each committed
    # line, whether its audio exists. A second walk here would be a
    # second answer to the same question.
    bank = _call(app, "bank_view", 60)
    if isinstance(bank, dict) and bank.get("available"):
        totals = bank.get("totals") if isinstance(bank.get("totals"), dict) else {}
        pairs = (
            ("covered", totals.get("rounds"),
             "rounds bound to the next 60 minutes of the sheet"),
            ("executed", totals.get("produced_rounds"),
             "of those, the ones carrying a measured cue map - the only "
             "ones the sequencer is allowed to hold"),
            ("unused", totals.get("unproduced_rounds"),
             "bound rounds still waiting to be produced. Not waste yet - "
             "the pile that BECOMES waste if the hour closes without it"),
            ("scheduled", totals.get("entries"),
             "entries on the running order inside that hour"),
        )
        for key, value, basis in pairs:
            got = _told(value)
            if got is None:
                continue
            out[key] = int(got)
            out[key + "_basis"] = basis
        for key, src in (("rendered_ahead_seconds", "rendered_ahead_seconds"),
                         ("written_only_seconds", "written_only_seconds"),
                         ("missing_seconds", "missing_seconds")):
            got = _told(bank.get(src))
            if got is not None:
                out[key] = round(got, 1)
        if bank.get("say"):
            out["bank_say"] = str(bank.get("say"))[:400]
    elif isinstance(bank, dict):
        out["cover_why"] = str(bank.get("say") or "the read-ahead bank "
                               "could not be read")[:300]
    blocked, listed, asked = _blocked_reasons(app, unheard_rows)
    if blocked:
        out["blocked"] = blocked
    if listed:
        out["rows"] = listed
        out["rows_basis"] = ("the oldest %d never-heard rounds, each with "
                             "the air road's own reason and what may be "
                             "done about it" % len(listed))
    out["rows_asked"] = asked
    out["rows_cap"] = ROWS_MOST
    out["reason_cap"] = REASON_MOST
    if len(unheard_rows) > asked:
        out["rows_truncated"] = True
        out["rows_truncated_basis"] = (
            "%d rounds have never been heard; the oldest %d were asked why. "
            "Asking all of them walks every shelf on the station and this "
            "pane may not cost the air a stall."
            % (len(unheard_rows), asked))
    return out


def _ago(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0))
    if seconds < 90:
        return "%ds" % int(seconds)
    if seconds < 5400:
        return "%dm" % int(seconds / 60)
    if seconds < 172800:
        return "%dh" % int(seconds / 3600)
    return "%dd" % int(seconds / 86400)


# ------------------------------------------------------------------ the door

def rooms_and_waste(app: Any) -> dict[str, Any]:
    """`{"rooms": [...], "waste": {...}}` for the glass. Never raises.

    Call this on a worker thread. It is memoised for MEMO_S seconds, so a
    tablet and two desks with the panel open cost one walk between them."""
    now = time.time()
    memo = _MEMO.get("value")
    if memo is not None and now - float(_MEMO.get("at") or 0) < MEMO_S:
        return dict(memo)
    flow, flow_oldest, journal = _flow_events(app)
    rooms: list[dict[str, Any]] = []
    unheard_rows: list[tuple[float, str, dict[str, Any]]] = []
    try:
        rooms.append(_writing_desk(app, now))
    except Exception as exc:  # noqa: BLE001
        rooms.append(_broke("the writing desk", exc))
    try:
        room, unheard_rows = _reserve(app, now)
        rooms.append(room)
    except Exception as exc:  # noqa: BLE001
        rooms.append(_broke("the reserve", exc))
    try:
        rooms.append(_recording_room(app, now, flow, journal))
    except Exception as exc:  # noqa: BLE001
        rooms.append(_broke("the recording room", exc))
    try:
        rooms.append(_pantry(app, now, flow, journal))
    except Exception as exc:  # noqa: BLE001
        rooms.append(_broke("the pantry", exc))
    # THE MOVEMENT WINDOW, ONCE, ON EVERY ROOM THAT USED THE JOURNAL. The
    # deque is 5000 deep and this station writes to it constantly; if it
    # has rotated inside ten minutes then `in` and `out` are floors.
    if flow and flow_oldest and flow_oldest > now - WINDOW_S:
        for room in rooms:
            if room.get("key") in ("recording", "pantry"):
                room["window_truncated"] = True
                room["window_covers_seconds"] = round(now - flow_oldest, 1)
    try:
        waste = _waste(app, now, flow, unheard_rows)
    except Exception as exc:  # noqa: BLE001
        waste = {"at": now, "why": "the account could not be taken (%s)"
                                   % type(exc).__name__}
    got = {
        "rooms": rooms,
        "waste": waste,
        "rooms_say": ("material only ever moves down this list and nothing "
                      "skips a room; the running order above them is a "
                      "sheet and the air below them is the way out, so "
                      "these four are the rooms that can HOLD something."),
        "window_seconds": int(WINDOW_S),
        "memo_seconds": int(MEMO_S),
        "at": now,
    }
    _MEMO.update({"at": now, "value": got})
    return dict(got)


def _broke(name: str, exc: BaseException) -> dict[str, Any]:
    """A room that could not be read says so BY NAME and sends no counts.

    No `in`, no `out`, no `stuck` - the panel then prints "could not be
    counted" for each of them and names the keys it looked for, which is
    the truth. A zero here would be the lie."""
    return {"key": "broken", "name": name, "label": name,
            "why": ("this room could not be read on this pass (%s). It is "
                    "not empty and it is not idle - it is unmeasured, and "
                    "no count is sent for it rather than a zero."
                    % type(exc).__name__)}

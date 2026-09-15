#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#1169/#1170 — the modifier desk: identity, the ride, and the trace.

Idempotent.  `--check` says what it would do and touches nothing; no flag
applies; `--revert` takes it back out.  Byte-IO throughout and LF-only:
app.py has no CRLF in it and must not gain one.  Every anchor below was
verified unique in the file this was built against, and the script refuses
to write if an anchor is missing, ambiguous, or if the result does not
compile.

    --target PATH   patch a copy instead of the live tree (default: the
                    repo root next to this script's --repo)
    --repo PATH     where app.py and station_modifiers.py live

WHAT IT DOES

  1. installs `station_modifiers.py` beside app.py (the durable book, the
     switch, the trace - all pure, all unit-tested);
  2. imports it, and adds a small facade: where the stores are, when the
     clock ticks, and what airs;
  3. rides the standing modifier ids onto the round at the moment its sid
     is minted, and writes them into the script ledger row and the air log
     row so a segment can name what shaped it;
  4. gives `segment_inspect` a `modifiers` key (the reverse direction);
  5. adds GET /api/modifiers, GET /api/modifier/trace, POST
     /api/modifier/raise, POST /api/modifier/drop;
  6. hands the standing modifiers to the writing prompt and to the SFX
     guy's dead-air fill (#1170), and gives that fill a sid so what it
     says is recorded against the modifier like anything else;
  7. seats a guest when one is raised, which is the measured reason the
     third seat spoke three times in a day.

Items 6 and 7 change what airs and are behind `<data>/modifiers/mode`,
which DEFAULTS OFF - the same shape as <data>/manager_calls_in and
<data>/script_production/mode, re-read every three seconds, no restart.
Item 3's ledger columns only appear once the switch is at least `trace`.
"""
import argparse
import hashlib
import io
import os
import py_compile
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REPO = r"\\10.89.1.246\ehm_eckx\pinevoice-stack\spark-agent"
def module_source(repo):
    """Where station_modifiers.py is read FROM.

    The build copy next to this script when it is run out of the scratchpad
    it was written in; otherwise the copy already beside app.py, which is
    what the repo looks like once this has been installed once."""
    for candidate in (os.path.join(HERE, "build", "station_modifiers.py"),
                      os.path.join(HERE, "station_modifiers.py"),
                      os.path.join(os.path.dirname(HERE),
                                   "station_modifiers.py"),
                      os.path.join(repo, "station_modifiers.py")):
        if os.path.exists(candidate):
            return candidate
    raise SystemExit("cannot find station_modifiers.py to install")

MARK = "#1169/#1170"


# --------------------------------------------------------------------------
# The facade.  Everything the station side of the desk needs, in one place.
# --------------------------------------------------------------------------
FACADE = '''
# --- #1169/#1170: the modifier desk ---------------------------------------
# The operator, inbox #1169: "give IDs and identifiers to these things and
# make sure that they are traceable throughout segments and through
# dialogue in order to make sure that these systems are taking place
# whenever they're activated ... I want to be able to trace these things
# across the segments happening to the segments as modifiers for their
# events when they are occurring."  And #1170: "whenever there's dead air
# ... these are things that are said on the station that also get codes and
# IDs and are followed throughout the system."
#
# MEASURED FIRST, 2026-09-15.  A guest (data/guests.json), a topic
# (data/banter_topics.json) and a plotline (data/plotlines.json) already
# HAD an id.  An event did not exist at all - the nearest thing, a theme in
# data/caller_themes.json, is a bare name with no id, so renaming one
# orphans every record that pointed at it.  And not one of the four was
# ever recorded against a segment: data/plot_beats.jsonl carried the plot
# id on 2475 beats in twenty-four hours and a segment id on NONE of them,
# while air_log.jsonl and script_ledger.jsonl carried the sid on every line
# and named no modifier at all.  The two halves of the answer were both on
# disk and shared no join key.
#
# So this is a JOIN and a SWITCH, not a fifth book.  guests.json,
# banter_topics.json, plotlines.json and caller_themes.json stay the truth
# and keep their own ids; station_modifiers holds only what is standing,
# which segment each standing thing rode, and the logic - all of it pure,
# all of it unit-tested off a temp directory.  This block is the station's
# side: where the stores are, when the clock ticks, and what airs.
MODIFIERS_DIR = data_path("modifiers")
MODIFIERS_SWITCH = station_modifiers.ModifierSwitch(MODIFIERS_DIR)
_MODIFIER_BOOK = station_modifiers.ModifierBook(DATA_DIR)
_MODIFIER_LOCK = RLock()
_MODIFIER_FOLLOW: dict[str, Any] = {"at": 0.0, "said": None}
# How often the desk re-reads the station's own stores.  A guest sent home
# must stop riding within a tick, or the next hour of segments is traced to
# somebody who is not in the building.
MODIFIER_FOLLOW_EVERY = 10.0


def modifiers_mode() -> str:
    """off | trace | ride.  Never raises; an unreadable switch is off."""
    try:
        return MODIFIERS_SWITCH.mode()
    except Exception:  # noqa: BLE001
        return station_modifiers.MODE_OFF


def modifiers_trace_on() -> bool:
    """Are ids being recorded against segments?  Changes nothing that airs."""
    return modifiers_mode() in (station_modifiers.MODE_TRACE,
                                station_modifiers.MODE_RIDE)


def modifiers_air_on() -> bool:
    """Do the standing modifiers reach the prompt and the gap fillers?"""
    return modifiers_mode() == station_modifiers.MODE_RIDE


def modifiers_follow(force: bool = False) -> dict[str, Any]:
    """Put up what the station's own stores say is up, take down what they
    no longer say.

    Called off the round path rather than off a scheduler, throttled to
    MODIFIER_FOLLOW_EVERY: a desk that needs its own loop is a desk that
    can starve one, and this station has paid for that twice (#1142,
    #1146).  Never raises - colour may not take the station off the air."""
    now = time.time()
    if not force and now - float(_MODIFIER_FOLLOW["at"]) < MODIFIER_FOLLOW_EVERY:
        return {}
    _MODIFIER_FOLLOW["at"] = now
    try:
        with _MODIFIER_LOCK:
            _MODIFIER_BOOK.reload()
            raises = station_modifiers.from_stores(
                guests=read_guests(), dj=dj_settings(),
                topics=read_bombshells(), plotlines=plot_read(),
                themes=themes_read(), now=now)
            out = station_modifiers.follow_stores(_MODIFIER_BOOK, raises,
                                                  now=now)
    except Exception:  # noqa: BLE001
        return {}
    said = ",".join(out.get("standing") or [])
    if said != _MODIFIER_FOLLOW["said"]:
        _MODIFIER_FOLLOW["said"] = said
        try:
            pipeline_log("model", "#1169: standing now - "
                         + (said or "nothing"))
        except Exception:  # noqa: BLE001
            pass
    return out


def modifiers_standing() -> list[dict[str, Any]]:
    """What is up.  [] when the switch is off, so nothing downstream has to
    ask twice."""
    if not modifiers_trace_on():
        return []
    try:
        modifiers_follow()
        with _MODIFIER_LOCK:
            return _MODIFIER_BOOK.standing()
    except Exception:  # noqa: BLE001
        return []


def modifiers_ride_round(sid: str, round_kind: str = "",
                         source: str = "") -> list[str]:
    """Record that whatever is standing shaped the round called `sid`.

    One call, where the sid is minted - BEFORE the round is written, so a
    round that is written and never heard is still traceable.  "Written and
    never aired" is an answer #1169 asks for and #1239 is why it has to be
    a different answer from "heard"."""
    if not sid or not modifiers_trace_on():
        return []
    try:
        modifiers_follow()
        with _MODIFIER_LOCK:
            return _MODIFIER_BOOK.ride(str(sid), None, round_kind=round_kind,
                                       source=source)
    except Exception:  # noqa: BLE001
        return []           # a failed trace never stops a round going out


def modifiers_for_sid(sid: str) -> list[str]:
    """The modifiers that shaped this segment.  A dict lookup: this is asked
    once per ledger row and once per air-log row, and a share read per line
    would be a share read per line."""
    if not sid or not modifiers_trace_on():
        return []
    try:
        with _MODIFIER_LOCK:
            return _MODIFIER_BOOK.ids_for(str(sid))
    except Exception:  # noqa: BLE001
        return []


def modifiers_named(ids: list[str]) -> list[dict[str, Any]]:
    """Ids to {id, kind, name} - what the inspector shows.  An id whose
    record has aged out of the book still comes back, named for what it is,
    because a trace that silently drops a row is worse than one that says
    "this rode here and the book no longer remembers it"."""
    out: list[dict[str, Any]] = []
    for one in ids or []:
        row = {}
        try:
            with _MODIFIER_LOCK:
                row = _MODIFIER_BOOK.get(str(one))
        except Exception:  # noqa: BLE001
            row = {}
        kind, key = station_modifiers.split_id(one)
        out.append({"id": str(one), "kind": row.get("kind") or kind,
                    "key": row.get("key") or key,
                    "name": row.get("name") or "",
                    "raised": row.get("raised") or 0,
                    "until": row.get("until") or 0,
                    "known": bool(row)})
    return out


def modifiers_clause() -> str:
    """What the writing prompt hears.  "" unless the switch is at `ride`.

    Hung on the same layer as plot_clause() and for the reason its comment
    gives - "every round the station writes assembles that one" - so a
    standing guest, topic, event or plotline reaches the booth talk, the
    calls, the memos, the ad reads and the gallery without being wired into
    each of them separately."""
    if not modifiers_air_on():
        return ""
    try:
        rows = modifiers_standing()
        return station_modifiers.standing_clause(
            rows[:station_modifiers.CLAUSE_CAP])
    except Exception:  # noqa: BLE001
        return ""


def modifiers_gap_context() -> str:
    """#1170: what the SFX guy should be thinking about while he fills a
    hole.

    His bank is already picked by CONTEXT, not by text - pick() ranks a
    prepared line by how many terms it shares with whatever it is handed -
    so handing it what is standing is the whole of the change.  Nothing
    renders, nothing new is written, and a station with nothing standing
    gets exactly the topic line it got before."""
    if not modifiers_air_on():
        return ""
    try:
        rows = modifiers_standing()
        said = [station_modifiers.record_says(r) for r in rows[:3]]
        return " ".join(s for s in said if s).strip()
    except Exception:  # noqa: BLE001
        return ""


def modifiers_gap_sid() -> str:
    """A sid for a line said into dead air, with the standing modifiers
    ridden onto it.

    The gap fills have never had one: sfxguy_gap_talk goes out through
    dj_speak, whose ring entry has no `sid` key, so airlog_row_from writes
    "" and script_ledger_catch_up (#1339) commits it as an unscripted
    one-row block belonging to nothing.  #1170 asks for the opposite - what
    is said into a gap is "followed throughout the system" - and a segment
    id is what following means here."""
    if not modifiers_trace_on():
        return ""
    try:
        rows = modifiers_standing()
        if not rows:
            return ""
        sid = uuid.uuid4().hex[:12]
        modifiers_ride_round(sid, round_kind="sfxguy", source="dead air")
        return sid
    except Exception:  # noqa: BLE001
        return ""


def modifiers_seat_guest(mid: str) -> bool:
    """Put the raised guest in the third chair.

    THE MEASURED REASON THE THIRD SEAT SPOKE THREE TIMES IN A DAY.  Every
    door into that seat is behind `if dj["third_name"]` - the voice draw
    (session_voices), the macro rotation, the persona clause, and above all
    the ONE string in the whole file that tells the model the letter D
    exists:  ", 'D: ...' for {third_name}".  With third_name empty the
    writer is told "strictly alternating" between A and B and nothing
    anywhere asks for a D, so the three lines a day are the noise floor of
    a model emitting a stray D: that banter_turns then maps to the seat.
    third_name has exactly two writers - an operator typing it into the
    panel, and set_guest() - and nothing in the running station calls
    set_guest by itself.  Raising a guest here calls it, which is the
    difference between a guest who is on the books and a guest who is in
    the room.

    Behind the switch: this changes what airs."""
    if not modifiers_air_on():
        return False
    kind, key = station_modifiers.split_id(mid)
    if kind != station_modifiers.KIND_GUEST or not key:
        return False
    try:
        guest = next((g for g in read_guests()
                      if str(g.get("id") or "") == key), None)
        if not guest:
            return False
        if str(dj_settings().get("guest_id") or "") == key \\
                and dj_settings().get("guest_mode"):
            return False                # already in the chair
        set_guest(guest)
        pipeline_log("air", "#1169: %s takes the third chair (%s)"
                     % (str(guest.get("name") or "the guest"), mid))
        return True
    except Exception:  # noqa: BLE001
        return False


def modifier_trace(mid: str, hours: float = 24.0) -> dict[str, Any]:
    """Every segment this modifier touched, with times and whether those
    segments were actually HEARD."""
    now = time.time()
    span = max(0.1, min(48.0, float(hours or 24.0))) * 3600.0
    try:
        with _MODIFIER_LOCK:
            record = _MODIFIER_BOOK.get(str(mid))
            rides = _MODIFIER_BOOK.rides_for(str(mid))
    except Exception as exc:  # noqa: BLE001
        return {"schema": 1, "id": str(mid), "available": False,
                "why": "the modifier book could not be read: %r" % (exc,),
                "modifier": None, "segments": [], "summary": None}
    rides = [r for r in rides if float(r.get("at") or 0) >= now - span]
    rows: list[dict[str, Any]] = []
    if rides:
        first = min(float(r.get("at") or now) for r in rides)
        try:
            rows = airlog_rows(first - 60.0, now + 7200.0, quiet=True)
        except Exception:  # noqa: BLE001
            rows = []
    segments = station_modifiers.trace_segments(rides, rows)
    return {"schema": 1, "id": str(mid), "available": True, "why": "",
            "mode": modifiers_mode(),
            "modifier": (record or None),
            "standing": station_modifiers.record_standing(record, now)
                        if record else False,
            "segments": segments,
            "summary": station_modifiers.trace_summary(record or {"name": mid},
                                                       segments)}

'''


# --------------------------------------------------------------------------
# The routes.
# --------------------------------------------------------------------------
ROUTES = '''

# --- #1169/#1170: the modifier desk, both directions ----------------------
@app.get("/api/modifiers")
async def modifiers_api(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """2026-09-15 (#1169): every modifier on the book, and which of them are
    standing right now."""
    require_read_auth(authorization)

    def _read() -> dict[str, Any]:
        modifiers_follow(force=True)
        now = time.time()
        with _MODIFIER_LOCK:
            rows = _MODIFIER_BOOK.all()
        standing = [r for r in rows
                    if station_modifiers.record_standing(r, now)]
        return {"schema": 1, "at": now, "mode": modifiers_mode(),
                "switch": str(MODIFIERS_SWITCH.path),
                "traces": modifiers_trace_on(), "airs": modifiers_air_on(),
                "standing": standing, "all": rows,
                "clause": modifiers_clause(),
                "say": ("%d standing of %d on the book; the switch says %s"
                        % (len(standing), len(rows), modifiers_mode()))}

    return await asyncio.to_thread(_read)


@app.get("/api/modifier/trace")
async def modifier_trace_api(
    id: str = "",
    hours: float = Query(default=24.0, ge=0.1, le=48.0),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """2026-09-15 (#1169): every segment this modifier touched, when, and
    whether it was heard."""
    require_read_auth(authorization)
    if not station_modifiers.is_modifier_id(id):
        raise HTTPException(status_code=400,
                            detail="name a modifier id, like guest:4f959ea0")
    return await asyncio.to_thread(modifier_trace, str(id), float(hours))


@app.post("/api/modifier/raise")
async def modifier_raise_api(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """2026-09-15 (#1169): put a modifier up by hand.

    `kind` is guest, topic, event or plot.  `key` is the id it already has
    in its own store - a guest id out of guests.json, a topic id out of
    banter_topics.json, a plot id out of plotlines.json - because this desk
    does not mint a second identity for anything that has one.  An EVENT is
    the exception and the only one: the station holds those as bare names,
    so `key` may be left out and one is derived from the name.

    Raising a GUEST also seats them, which is the whole of #1169's second
    half - but only when the switch is at `ride`, because that changes what
    airs."""
    require_auth(authorization)
    payload = await request.json()
    kind = str(payload.get("kind") or "").strip().lower()
    if kind not in station_modifiers.KINDS:
        raise HTTPException(status_code=400,
                            detail="kind must be one of %s"
                                   % (", ".join(station_modifiers.KINDS),))
    name = str(payload.get("name") or "").strip()
    key = str(payload.get("key") or payload.get("id") or "").strip()
    if not key and kind == station_modifiers.KIND_EVENT:
        key = station_modifiers.name_key(name)
    if not key:
        raise HTTPException(status_code=400,
                            detail="name the key this thing already has in "
                                   "its own store")
    stands = payload.get("stands_s")

    def _raise() -> dict[str, Any]:
        with _MODIFIER_LOCK:
            _MODIFIER_BOOK.reload()
            return _MODIFIER_BOOK.raise_(
                kind, key, name or key,
                stands_s=(None if stands is None else float(stands)),
                note=str(payload.get("note") or ""), source="by hand")

    row = await asyncio.to_thread(_raise)
    if not row:
        raise HTTPException(status_code=400, detail="that is not a modifier")
    seated = await asyncio.to_thread(modifiers_seat_guest, str(row.get("id")))
    return {"ok": True, "modifier": row, "seated": bool(seated),
            "mode": modifiers_mode(),
            "say": ("the switch is off - this is on the book and will not "
                    "ride anything until <data>/modifiers/mode says trace "
                    "or ride" if not modifiers_trace_on() else
                    "standing, and riding every round written from now")}


@app.post("/api/modifier/drop")
async def modifier_drop_api(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """2026-09-15 (#1169): take a modifier down.

    The record stays.  A trace of a guest who has left is still a trace,
    and #1169 asks for the segments the guest touched, not for the guest to
    be forgotten the moment they go home."""
    require_auth(authorization)
    payload = await request.json()
    mid = str(payload.get("id") or "").strip()
    if not station_modifiers.is_modifier_id(mid):
        raise HTTPException(status_code=400, detail="name a modifier id")

    def _drop() -> bool:
        with _MODIFIER_LOCK:
            _MODIFIER_BOOK.reload()
            return _MODIFIER_BOOK.drop(mid)

    ok = await asyncio.to_thread(_drop)
    if not ok:
        raise HTTPException(status_code=404, detail="no such modifier")
    kind, _key = station_modifiers.split_id(mid)
    if kind == station_modifiers.KIND_GUEST and modifiers_air_on():
        try:
            if str(dj_settings().get("guest_id") or "") == _key:
                await asyncio.to_thread(set_guest, None)
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "id": mid, "mode": modifiers_mode()}
'''


# --------------------------------------------------------------------------
# The hunks.  (name, old, new) — every `old` verified unique.
# --------------------------------------------------------------------------
def hunks():
    out = []

    out.append(("import", "from store_retention import retention_sweep, store_sizes\n",
                "from store_retention import retention_sweep, store_sizes\n"
                "import station_modifiers                 # #1169/#1170: the modifier desk\n"))

    out.append(("facade",
                "\n\n# --- The plotline desk: hand-written storylines the pair"
                " play out on air ---\n",
                "\n" + FACADE
                + "\n# --- The plotline desk: hand-written storylines the pair"
                  " play out on air ---\n"))

    # The writing prompt.  Same layer as plot_clause, same reason.
    out.append(("prompt",
                "    if slot == \"host\":\n"
                "        try:\n"
                "            lead += plot_clause()\n"
                "        except Exception:  # noqa: BLE001\n"
                "            pass            # a broken plotline never silences the booth\n",
                "    if slot == \"host\":\n"
                "        try:\n"
                "            lead += plot_clause()\n"
                "        except Exception:  # noqa: BLE001\n"
                "            pass            # a broken plotline never silences the booth\n"
                "        # #1169: and what is STANDING - the guest in the room, the\n"
                "        # topic on the table, the event going on, the story running.\n"
                "        # Here for the reason above: a modifier that only reached\n"
                "        # dj_banter would be a modifier the calls, the memos, the ad\n"
                "        # reads and the gallery never heard of, which is exactly the\n"
                "        # complaint. Behind <data>/modifiers/mode, default off.\n"
                "        try:\n"
                "            lead += modifiers_clause()\n"
                "        except Exception:  # noqa: BLE001\n"
                "            pass            # colour never silences the booth either\n"))

    # A single line may name the segment it belongs to.
    out.append(("speak-sig",
                "                   round_as: str = \"\") -> str:\n"
                "    \"\"\"#1146: the floor door for single lines.",
                "                   round_as: str = \"\", sid: str = \"\") -> str:\n"
                "    \"\"\"#1146: the floor door for single lines."))

    out.append(("speak-fwd-1",
                "            checked=checked, remember_text=remember_text, round_as=round_as)\n"
                "    _owned = await _floor_take",
                "            checked=checked, remember_text=remember_text, round_as=round_as,\n"
                "            sid=sid)\n"
                "    _owned = await _floor_take"))

    out.append(("speak-fwd-2",
                "            checked=checked, remember_text=remember_text, round_as=round_as)\n"
                "    finally:\n"
                "        _floor_drop(_owned)\n",
                "            checked=checked, remember_text=remember_text, round_as=round_as,\n"
                "            sid=sid)\n"
                "    finally:\n"
                "        _floor_drop(_owned)\n"))

    out.append(("floorless-sig",
                "                   round_as: str = \"\") -> str:\n"
                "    \"\"\"Say it, log it to the chat channel",
                "                   round_as: str = \"\", sid: str = \"\") -> str:\n"
                "    \"\"\"Say it, log it to the chat channel"))

    out.append(("entry-sid",
                "        \"voice\": forced or \"\",\n"
                "        \"engine\": engine,\n"
                "        \"model\": str(load_settings().get(\"model\") or \"\"),\n"
                "    }\n",
                "        \"voice\": forced or \"\",\n"
                "        \"engine\": engine,\n"
                "        \"model\": str(load_settings().get(\"model\") or \"\"),\n"
                "        # #1170: a single line may name the segment it belongs to.\n"
                "        # Only the gap fills pass one today - they have never had a\n"
                "        # sid, so airlog_row_from writes \"\" and script_ledger_catch_up\n"
                "        # commits them as an unscripted block belonging to nothing.\n"
                "        # Absent by default: an entry without a sid is what every\n"
                "        # other caller of this road has always produced.\n"
                "        **({\"sid\": str(sid)} if sid else {}),\n"
                "    }\n"))

    # The SFX guy's dead-air fill: picked against what is standing, and
    # recorded against it.
    out.append(("gap-talk",
                "        take = sfxguy_ready_pick(sfx_topic_line(), voice)\n"
                "        if not take:\n"
                "            return _no(\"nothing in his bank is recorded, rested and free\")\n",
                "        # #1170: \"whenever there's dead air ... these are things that\n"
                "        # are said on the station\". The topic is the PICK CONTEXT, not\n"
                "        # the words - so handing him what is STANDING is the whole of\n"
                "        # the change, and a station with nothing standing gets exactly\n"
                "        # the topic line it got before.\n"
                "        _mod_ctx = modifiers_gap_context()\n"
                "        take = sfxguy_ready_pick(_mod_ctx or sfx_topic_line(), voice)\n"
                "        if not take:\n"
                "            return _no(\"nothing in his bank is recorded, rested and free\")\n"))

    out.append(("gap-sid",
                "        door = _dj_speak_floorless if floorless else dj_speak\n"
                "        try:\n"
                "            out = await door(\"interject\", None, line=text, who=\"drop\",\n"
                "                             voice=voice, name=\"The SFX Guy\",\n"
                "                             checked=True, sting=False, clip=clip,\n"
                "                             round_as=\"sfxguy\")          # #1237\n",
                "        door = _dj_speak_floorless if floorless else dj_speak\n"
                "        # #1170: and what he says into the hole is recorded against the\n"
                "        # modifier's id like anything else - which needs a segment id,\n"
                "        # which this road has never had.\n"
                "        _mod_sid = modifiers_gap_sid()\n"
                "        try:\n"
                "            out = await door(\"interject\", None, line=text, who=\"drop\",\n"
                "                             voice=voice, name=\"The SFX Guy\",\n"
                "                             checked=True, sting=False, clip=clip,\n"
                "                             round_as=\"sfxguy\", sid=_mod_sid)  # #1237/#1170\n"))

    # The ride, at the moment the sid is minted.
    out.append(("ride",
                "    _round_sid = uuid.uuid4().hex[:12]\n"
                "    dj = dj_settings()\n",
                "    _round_sid = uuid.uuid4().hex[:12]\n"
                "    # #1169: whatever is standing rides this round. Here and not at\n"
                "    # commit time, because a round that is written and never heard is\n"
                "    # still a round a modifier shaped, and \"written and never aired\"\n"
                "    # is an answer the trace has to be able to give (#1239).\n"
                "    try:\n"
                "        modifiers_ride_round(_round_sid)\n"
                "    except Exception:  # noqa: BLE001\n"
                "        pass\n"
                "    dj = dj_settings()\n"))

    # The ledger row.
    out.append(("ledger",
                "            \"cue\": str(row.get(\"cue\") or \"\"),\n"
                "            \"scripted\": bool(row.get(\"scripted\", True)),\n"
                "        }))\n",
                "            \"cue\": str(row.get(\"cue\") or \"\"),\n"
                "            \"scripted\": bool(row.get(\"scripted\", True)),\n"
                "            # #1169: the modifiers that shaped this round. An id list,\n"
                "            # never a copy of the thing - guests.json, banter_topics.json,\n"
                "            # plotlines.json and caller_themes.json stay the truth.\n"
                "            **({\"mods\": _mods} if _mods else {}),\n"
                "        }))\n"))

    out.append(("ledger-lookup",
                "    block = _script_block_next()\n"
                "    at = time.time()\n"
                "    out: list[str] = []\n",
                "    block = _script_block_next()\n"
                "    at = time.time()\n"
                "    try:\n"
                "        _mods = modifiers_for_sid(str(sid or \"\"))\n"
                "    except Exception:  # noqa: BLE001\n"
                "        _mods = []\n"
                "    out: list[str] = []\n"))

    # The air log row.
    out.append(("airlog",
                "        \"clip_tail\": round(float(entry.get(\"clip_tail\") or 0), 3),\n"
                "        \"seconds\": round(seconds, 2),\n"
                "    }\n"
                "    if entry.get(\"ad_audio\"):\n",
                "        \"clip_tail\": round(float(entry.get(\"clip_tail\") or 0), 3),\n"
                "        \"seconds\": round(seconds, 2),\n"
                "    }\n"
                "    # #1169: the modifiers that shaped the segment this line belongs\n"
                "    # to, so a heard line can name what was going on when it went out.\n"
                "    # Absent when nothing was standing, which is the normal state and\n"
                "    # must cost the row nothing.\n"
                "    try:\n"
                "        _mods = modifiers_for_sid(str(row.get(\"sid\") or \"\"))\n"
                "        if _mods:\n"
                "            row[\"mods\"] = _mods\n"
                "    except Exception:  # noqa: BLE001\n"
                "        pass\n"
                "    if entry.get(\"ad_audio\"):\n"))

    # The inspector, the other way round.
    #
    # segment_inspect belongs to another writer and moved under this patch
    # once already tonight (it gained "hour", "slot" and "admission" between
    # the first --check and the last).  Both hunks below are anchored on the
    # CLOSING line of the skeleton and on the function's single terminal
    # `return out`, which is the most stable text in it: a field added after
    # these will still leave both anchors intact.  If it moves again,
    # --check names the hunk rather than guessing.
    out.append(("inspect-skel",
                "                           \"hour\": \"\", \"slot\": None, \"admission\": None}\n",
                "                           \"hour\": \"\", \"slot\": None, \"admission\": None,\n"
                "                           # #1169: the guest, topic, event and\n"
                "                           # plotline that shaped THIS segment.\n"
                "                           \"modifiers\": []}\n"))

    out.append(("inspect-fill",
                "        out[\"admission\"] = {\"occurrences\": [],\n"
                "                            \"say\": \"the gate could not be read: %r\" % (exc,)}\n"
                "    return out\n",
                "        out[\"admission\"] = {\"occurrences\": [],\n"
                "                            \"say\": \"the gate could not be read: %r\" % (exc,)}\n"
                "    # #1169, the reverse of /api/modifier/trace: the guest, topic,\n"
                "    # event and plotline that were standing when this round was\n"
                "    # written. [] when nothing was, and [] when the switch is off.\n"
                "    try:\n"
                "        out[\"modifiers\"] = modifiers_named(\n"
                "            modifiers_for_sid(str((out.get(\"round\") or {}).get(\"sid\") or \"\")))\n"
                "    except Exception:  # noqa: BLE001\n"
                "        out[\"modifiers\"] = []\n"
                "    return out\n"))

    # The routes.
    out.append(("routes",
                "@app.get(\"/api/segment/inspect\")\n",
                ROUTES.lstrip("\n") + "\n\n@app.get(\"/api/segment/inspect\")\n"))

    # The one-line bug: the workflow that seats a guest does not seat them.
    out.append(("caller-to-guest",
                "    write_guests([g for g in read_guests()\n"
                "                  if g.get(\"name\") != guest[\"name\"]] + [guest])\n"
                "    return {\"ok\": True, \"guest\": guest, \"guests\": read_guests()}\n",
                "    # #1169: dedupe by ID, not by name. Promoting the same caller\n"
                "    # twice minted a fresh id and orphaned the old one, and\n"
                "    # active_guest()'s `g.get(\"id\") == gid` lookup then silently\n"
                "    # returned {} - a guest on the books and nobody in the chair.\n"
                "    _old = next((g for g in read_guests()\n"
                "                 if str(g.get(\"name\") or \"\") == guest[\"name\"]), None)\n"
                "    if _old and _old.get(\"id\"):\n"
                "        guest[\"id\"] = str(_old[\"id\"])\n"
                "    write_guests([g for g in read_guests()\n"
                "                  if g.get(\"id\") != guest[\"id\"]\n"
                "                  and g.get(\"name\") != guest[\"name\"]] + [guest])\n"
                "    # #1169: and SEAT them. This route's own docstring says \"same\n"
                "    # person, now in the room being interviewed instead of on the\n"
                "    # phone\" - and it wrote the row and never called set_guest, so the\n"
                "    # one workflow that would put somebody in the third chair during a\n"
                "    # show was a no-op for the seat. Behind the switch: it changes\n"
                "    # what airs.\n"
                "    _seated = False\n"
                "    if modifiers_air_on():\n"
                "        try:\n"
                "            set_guest(guest)\n"
                "            modifiers_follow(force=True)\n"
                "            _seated = True\n"
                "        except Exception:  # noqa: BLE001\n"
                "            _seated = False\n"
                "    return {\"ok\": True, \"guest\": guest, \"guests\": read_guests(),\n"
                "            \"seated\": _seated}\n"))

    return out


# --------------------------------------------------------------------------
def read_bytes(path):
    with io.open(path, "rb") as handle:
        return handle.read()


def write_bytes(path, blob):
    tmp = path + ".modpatch.tmp"
    with io.open(tmp, "wb") as handle:
        handle.write(blob)
    os.replace(tmp, path)


def sha1(blob):
    return hashlib.sha1(blob).hexdigest()


def compiles(blob, label):
    fd, name = tempfile.mkstemp(suffix=".py")
    os.close(fd)
    try:
        with io.open(name, "wb") as handle:
            handle.write(blob)
        py_compile.compile(name, cfile=name + "c", doraise=True)
        return True, ""
    except py_compile.PyCompileError as exc:
        return False, "%s does not compile: %s" % (label, exc)
    finally:
        for one in (name, name + "c"):
            try:
                os.unlink(one)
            except OSError:
                pass


def plan(blob):
    """(applied, pending, problems) for the current bytes."""
    applied, pending, problems = [], [], []
    for name, old, new in hunks():
        old_b = old.encode("utf-8")
        new_b = new.encode("utf-8")
        n_new = blob.count(new_b)
        n_old = blob.count(old_b)
        if n_new == 1:
            applied.append(name)
        elif n_old == 1:
            pending.append(name)
        elif n_new > 1:
            problems.append("%s: the patched text appears %d times" % (name, n_new))
        elif n_old == 0:
            problems.append("%s: anchor not found - the file has moved under us"
                            % name)
        else:
            problems.append("%s: anchor appears %d times, not once" % (name, n_old))
    return applied, pending, problems


def apply_all(blob, forward=True):
    for name, old, new in hunks():
        a, b = (old, new) if forward else (new, old)
        a_b, b_b = a.encode("utf-8"), b.encode("utf-8")
        if blob.count(b_b) == 1 and blob.count(a_b) == 0:
            continue                        # already where we want it
        if blob.count(a_b) != 1:
            raise SystemExit("refusing: %s anchor is not unique (%d)"
                             % (name, blob.count(a_b)))
        blob = blob.replace(a_b, b_b, 1)
    return blob


def module_state(repo):
    dst = os.path.join(repo, "station_modifiers.py")
    want = read_bytes(module_source(repo)).replace(b"\r\n", b"\n")
    if not os.path.exists(dst):
        return "missing", want
    got = read_bytes(dst)
    return ("same" if got == want else "different"), want


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--target", default="",
                    help="patch this app.py instead of <repo>/app.py")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--no-module", action="store_true",
                    help="leave station_modifiers.py alone")
    args = ap.parse_args()

    app_path = args.target or os.path.join(args.repo, "app.py")
    if not os.path.exists(app_path):
        raise SystemExit("no app.py at %s" % app_path)
    blob = read_bytes(app_path)
    print("app.py      %s" % app_path)
    print("sha1        %s  (%d bytes)" % (sha1(blob), len(blob)))
    if b"\r\n" in blob:
        raise SystemExit("refusing: app.py already contains CRLF")

    mod_state, mod_want = module_state(args.repo)
    print("module      station_modifiers.py: %s" % mod_state)

    applied, pending, problems = plan(blob)
    print("hunks       %d applied, %d pending, %d problem(s) of %d"
          % (len(applied), len(pending), len(problems), len(hunks())))
    for one in problems:
        print("  PROBLEM   %s" % one)
    if pending:
        print("  pending   %s" % ", ".join(pending))
    if applied:
        print("  applied   %s" % ", ".join(applied))

    if args.check:
        if problems:
            print("\nCHECK: cannot apply cleanly - see the problems above.")
            return 2
        if args.revert:
            print("\nCHECK: --revert would take out %d hunk(s)." % len(applied))
        elif pending:
            print("\nCHECK: would apply %d hunk(s)%s."
                  % (len(pending),
                     "" if args.no_module or mod_state == "same"
                     else " and write station_modifiers.py"))
        else:
            print("\nCHECK: already applied; nothing to do.")
        return 0

    if problems:
        raise SystemExit("refusing to write: %s" % "; ".join(problems))

    want = apply_all(blob, forward=not args.revert)
    if want == blob:
        print("\nnothing to do.")
    else:
        ok, why = compiles(want, "the patched app.py")
        if not ok:
            raise SystemExit("refusing to write: " + why)
        shutil.copyfile(app_path, app_path + ".bak-1169")
        write_bytes(app_path, want)
        print("\nwrote %s  sha1 %s  (backup: app.py.bak-1169)"
              % (app_path, sha1(want)))

    if not args.no_module and not args.revert and mod_state != "same":
        ok, why = compiles(mod_want, "station_modifiers.py")
        if not ok:
            raise SystemExit("refusing to write the module: " + why)
        write_bytes(os.path.join(args.repo, "station_modifiers.py"), mod_want)
        print("wrote %s" % os.path.join(args.repo, "station_modifiers.py"))
    if args.revert:
        print("note: station_modifiers.py is left in place. Nothing imports "
              "it once app.py is reverted, so it is inert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

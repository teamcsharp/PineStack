"""[voice-actor] The voice actor subpanel's store and roads.

TARGET: app.py

"put an icon of a person in the basebar that allows me to bring up the voice
actor subpanel. In this subpanel, I want to be able to set the voice actor for
everyone on the set, enabled guest stars in the studio, select / create /
dispatch / execute callers from the List to have them create nodegraph
segments and call in the RNG exchange and participate in the broadcast ...
load and setup host - cohost combos and individually set who the host /
co-host / in-station guest / scheduled caller / random caller" (2026-09-28).

The panel (desktop/renderer/voice-actor.js) drives the stores that already
exist - the guests, the caller list, the Host menu's engine switch - and
this tool adds only what did not exist:

  1. THE STORE, data/voice_actor.json: named combos (host + co-host, and a
     guest star or a third voice), each actor's recorded PREFERRED engine
     (xtts|f5 - the air always speaks through the ONE active engine, #1476),
     the Scheduled caller and Random caller seats (each armed ONCE), and the
     dispatch ledger with where each call stands.
  2. SEATS THROUGH THE VOICE DESK'S OWN ROAD. A seat or a combo is written by
     api_put_settings itself, read-modify-write on the server in one step, so
     #820's cast-change cut fires exactly as it does from the voice desk and
     no stale browser copy of the settings can put an old level back.
  3. TWO DISPATCH ROADS (the operator's decision):
     "call in now" arms a call interjection; System 3's graph takes it at the
     NEXT diamond of the round planned in the CURRENT segment
     (tools/voice_actor_runtime_patch.py writes ctx["call_interjection"],
     tools/voice_actor_graph_patch.py sets that diamond's recorded wheel) and
     dj_banter tells the writer who C is and puts C's rows in the caller's
     voice. The round stays its road's own (no call contract, no caller
     prep kind). A segment that ends first retires it as "missed".
     "queue next" plans a full call chapter as soon as the line is free and
     the station is on air, through dj_call_generated - the caller road
     System 3 directs, every step a recorded roll.
  4. THE SEATS ANSWER THE STATION'S OWN PHONES. The Scheduled caller takes the
     next scheduled call entry (_torrent_talk's caller kind and
     schedule_extra_round's banter_caller) instead of the shelf; the Random
     caller answers the phone clock's next ring instead of the shelf. Once,
     then the seat clears; a busy line or a pause leaves it armed.
  5. THE LEDGER READS THE AIR. queued -> writing | planned -> aired (the air
     log's caller rows under that name since the call was planned; the panel
     says "on air" while they are recent, "done" after), or an honest
     refusal: held (paused), missed, lost (planned, never heard in 15
     minutes), failed, cancelled.

Routes: GET /api/voice-actor/state; POST /api/voice-actor/seat, /combos,
/combos/{id}/apply, /prefs, /scheduled, /random-pin, /dispatch,
/dispatch/{id}/cancel; DELETE /api/voice-actor/combos/{id}. None renders
speech, none changes a level, none moves the engine (the Host menu's
POST /api/voice/engine-switch stays the one switch; the panel calls it).

--check exits 0 ready / 2 applied / 1 missing. --apply is idempotent and
atomic, LF only. ON THE HOST, with tools/voice_actor_runtime_patch.py
(system3_runtime.py) and tools/voice_actor_graph_patch.py (system3.py).
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path


# --- 1-5: the store, the helpers and the routes, before the callers' ring route
_ROUTES_OLD = '@app.post("/api/dj/callers/ring")\n'
_ROUTES_NEW = r'''# --- [voice-actor] THE VOICE ACTOR SUBPANEL: COMBOS, PREFERENCES, SEATS, DISPATCH ---
# The person on the status bar (desktop/renderer/voice-actor.js) opens the cast:
# every seat's voice actor, the guest star, the callers, the one engine. What
# existed is driven as it is (api_put_settings for seat voices - #820's cut
# included - set_guest, the caller list, the Host menu's engine switch); this
# is the one new store: named combos, each actor's recorded preferred engine,
# the Scheduled / Random caller seats, and the dispatch ledger. The whole
# account is in tools/voice_actor_backend_patch.py.
VOICE_ACTOR_PATH = data_path("voice_actor.json")
VOICE_ACTOR_LOCK = RLock()
VOICE_ACTOR_MEMO: dict[str, Any] = {"state": None, "heard_at": 0.0}
VOICE_ACTOR_TOPICS: dict[str, str] = {}          # caller id -> a dispatched call's own subject
VOICE_ACTOR_COMBOS_MAX = 40
VOICE_ACTOR_DISPATCH_KEEP = 60
VOICE_ACTOR_ARM_TTL = 1800.0          # an armed interjection waits half an hour for a diamond
VOICE_ACTOR_HEARD_TTL = 900.0         # planned, and not one line heard in 15 min: lost
VOICE_ACTOR_QUEUE_TTL = 1800.0        # "queue next" waits this long for the line and the air
VOICE_ACTOR_ENGINES = ("xtts", "f5")
VOICE_ACTOR_SEAT_KEYS = {"host": "voice", "cohost": "cohost_voice", "third": "third_voice"}
_VOICE_ACTOR_NAME = re.compile(r"^[\w .:+-]{1,100}\Z")


def voice_actor_blank() -> dict[str, Any]:
    return {"combos": [], "prefs": {}, "seats": {"scheduled": {}, "random": {}},
            "dispatch": []}


def voice_actor_read() -> dict[str, Any]:
    """[voice-actor] The store, loaded once and kept in memory (the file is
    written through). Anything that changes it holds VOICE_ACTOR_LOCK."""
    with VOICE_ACTOR_LOCK:
        if VOICE_ACTOR_MEMO["state"] is None:
            state = voice_actor_blank()
            try:
                raw = json.loads(VOICE_ACTOR_PATH.read_text("utf-8"))
                if isinstance(raw, dict):
                    for key, blank in voice_actor_blank().items():
                        if isinstance(raw.get(key), type(blank)):
                            state[key] = raw[key]
            except (OSError, ValueError, TypeError):
                pass
            for seat in ("scheduled", "random"):
                if not isinstance(state["seats"].get(seat), dict):
                    state["seats"][seat] = {}
            VOICE_ACTOR_MEMO["state"] = state
        return VOICE_ACTOR_MEMO["state"]


def voice_actor_save() -> None:
    with VOICE_ACTOR_LOCK:
        state = voice_actor_read()
        state["dispatch"] = list(state.get("dispatch") or [])[-VOICE_ACTOR_DISPATCH_KEEP:]
        state["combos"] = list(state.get("combos") or [])[:VOICE_ACTOR_COMBOS_MAX]
        try:
            VOICE_ACTOR_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = VOICE_ACTOR_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")
            tmp.replace(VOICE_ACTOR_PATH)
        except OSError as exc:
            pipeline_log("drop", "the voice actor store could not be written",
                         extra=f"{type(exc).__name__}: {exc}"[:200])


def voice_actor_voice_ok(vid: Any) -> bool:
    """A seat may hold a library voice that exists, a stock voice name, or
    nothing (the station draws)."""
    vid = str(vid or "")
    if not vid:
        return True
    if VOICE_ID_SHAPE.match(vid):
        return voice_meta(vid) is not None
    return bool(_VOICE_ACTOR_NAME.match(vid)) and ".." not in vid


def voice_actor_caller(caller_id: Any) -> dict[str, Any] | None:
    cid = str(caller_id or "")
    if not cid:
        return None
    return next((dict(r) for r in read_callers() if str(r.get("id") or "") == cid), None)


def voice_actor_row(did: str) -> dict[str, Any] | None:
    with VOICE_ACTOR_LOCK:
        return next((r for r in voice_actor_read()["dispatch"] if r.get("id") == did), None)


def voice_actor_update(did: str, **fields: Any) -> None:
    with VOICE_ACTOR_LOCK:
        row = voice_actor_row(did)
        if row is None:
            return
        row.update(fields)
        row["changed_at"] = time.time()
        voice_actor_save()


def voice_actor_new_dispatch(caller: dict[str, Any], road: str, topic: str = "") -> dict[str, Any]:
    """[voice-actor] One dispatched call on the ledger. The caller's persona and
    goal are copied in: the round that takes it reads the row, not the list."""
    try:
        seg = segment_on_air() or {}
    except Exception:  # noqa: BLE001
        seg = {}
    row = {"id": "d_" + uuid.uuid4().hex[:10], "caller_id": str(caller.get("id") or "")[:40],
           "caller": " ".join(str(caller.get("name") or "a caller").split())[:80],
           "persona": " ".join(str(caller.get("persona") or "").split())[:400],
           "goal": " ".join(str(caller.get("goal") or "").split())[:300],
           "voice_id": str(caller.get("voice_id") or "")[:40],
           "road": road, "topic": " ".join(str(topic or "").split())[:300],
           "state": "queued", "why": "", "at": time.time(),
           "segment_id": str(seg.get("id") or "")[:80], "segment": str(seg.get("label") or "")[:120],
           "conversation_id": "", "planned_at": 0.0, "aired_at": 0.0, "last_air_at": 0.0}
    with VOICE_ACTOR_LOCK:
        voice_actor_read()["dispatch"].append(row)
        voice_actor_save()
    return dict(row)


# --- the runtime's hooks ("call in now") -------------------------------------
def voice_actor_interjection_pending(road: str = "", segment_id: str = "") -> dict[str, Any] | None:
    """[voice-actor] The armed "call in now" interjection, for the round System 3
    plans next (system3_runtime _voice_actor_arm) - or None. ONE TREE PER
    SEGMENT: a call armed in a segment that has since ended is retired as
    missed, never carried into the next one."""
    now = time.time()
    with VOICE_ACTOR_LOCK:
        row = next((r for r in voice_actor_read()["dispatch"]
                    if r.get("road") == "now" and r.get("state") == "queued"), None)
        if row is None:
            return None
        if now - float(row.get("at") or 0) > VOICE_ACTOR_ARM_TTL:
            row.update(state="missed", changed_at=now,
                       why="no diamond took the call within %d minutes" % int(VOICE_ACTOR_ARM_TTL / 60))
            voice_actor_save()
            return None
        seg = str(row.get("segment_id") or "")
        if seg and segment_id and seg != str(segment_id):
            row.update(state="missed", changed_at=now,
                       why="the segment it was dispatched into ended before a diamond took the call")
            voice_actor_save()
            return None
        return {"id": row["id"], "caller_id": row.get("caller_id", ""), "name": row.get("caller", ""),
                "persona": row.get("persona", ""), "goal": row.get("goal", ""),
                "topic": row.get("topic", ""), "voice_id": row.get("voice_id", ""),
                "segment_id": seg}


def voice_actor_interjection_taken(did: str, conversation_id: str, turn_ids: Any = None,
                                   node: str = "") -> None:
    """[voice-actor] System 3's graph took the armed call at a diamond: the
    dispatch is planned into that conversation (its C turns named)."""
    voice_actor_update(str(did or ""), state="planned", planned_at=time.time(),
                       conversation_id=str(conversation_id or "")[:40],
                       turns=[str(t)[:40] for t in (turn_ids or [])][:12], node=str(node or "")[:60],
                       why="taken at the diamond %s of conversation %s" % (node or "?", conversation_id))
    pipeline_log("call", "voice actor: a dispatched caller was taken at a diamond (call in now)",
                 extra="%s -> %s" % (did, conversation_id))


def voice_actor_round_interjection(handle: Any, caller_name: str = "") -> dict[str, Any] | None:
    """[voice-actor] dj_banter's question: did THIS round's plan take the
    dispatched caller? Their name and held voice, or None."""
    if caller_name or handle is None or not getattr(handle, "active", False):
        return None
    got = getattr(handle, "interjection", None)
    if not isinstance(got, dict) or not str(got.get("name") or "").strip():
        return None
    return dict(got)


def voice_actor_format_clause(handle: Any, caller_name: str = "") -> str:
    """[voice-actor] The writer's FORMAT line names C when this round's plan
    took the dispatched caller at a diamond; "" otherwise (every other round
    reads exactly as before)."""
    got = voice_actor_round_interjection(handle, caller_name)
    if not got:
        return ""
    return (", and 'C: ...' for %s, a caller who rings in where the running order puts them"
            % " ".join(str(got.get("name") or "the caller").split())[:80])


def voice_actor_topic_take(caller: dict[str, Any] | None) -> str:
    """[voice-actor] A dispatched call's own subject, once (dj_call_generated)."""
    cid = str((caller or {}).get("id") or "")
    return VOICE_ACTOR_TOPICS.pop(cid, "") if cid else ""


# --- the seats and the rings --------------------------------------------------
def voice_actor_pin_take(seat: str) -> dict[str, Any] | None:
    """[voice-actor] The caller armed in the Scheduled / Random seat, taken ONCE
    - or None. A busy line or a paused station leaves it armed for the next
    ring; a caller since deleted from the list clears the seat."""
    with VOICE_ACTOR_LOCK:
        pin = dict((voice_actor_read()["seats"].get(seat) or {}))
    if not pin.get("caller_id"):
        return None
    try:
        if radio_paused() or call_line_busy():
            return None
    except Exception:  # noqa: BLE001
        return None
    caller = voice_actor_caller(pin.get("caller_id"))
    with VOICE_ACTOR_LOCK:
        voice_actor_read()["seats"][seat] = {}
        voice_actor_save()
    if caller is None:
        pipeline_log("call", "voice actor: the %s caller seat named a caller no longer on the list" % seat)
        return None
    return caller


async def voice_actor_ring(caller: dict[str, Any] | None, road: str, did: str = "") -> bool:
    """[voice-actor] Put ONE listed caller on the line - dj_call_generated with
    force (the operator asked for this caller, so the 25-minute rest is theirs
    to waive) - and keep the ledger honest. True when the call went to air."""
    if not caller:
        return False
    if not did:
        did = voice_actor_new_dispatch(caller, road)["id"]
    voice_actor_update(did, state="writing", why="the call is being written and recorded")
    try:
        got = await dj_call_generated(caller, force=True)
    except Exception as exc:  # noqa: BLE001
        voice_actor_update(did, state="failed", why=f"{type(exc).__name__}: {exc}"[:200])
        pipeline_log("drop", "voice actor: a dispatched call failed",
                     extra=f"{type(exc).__name__}: {exc}"[:300])
        return False
    got = got if isinstance(got, dict) else {}
    if got.get("lines"):
        now = time.time()
        voice_actor_update(did, state="aired", aired_at=now, last_air_at=now, planned_at=now,
                           why="the call went to the air")
        pipeline_log("call", "voice actor: %s rang (%s)" % (caller.get("name") or "a caller", road))
        return True
    if str(got.get("state") or "") in ("deferred", "banking"):
        voice_actor_update(did, state="queued", why=str(got.get("why") or got.get("state"))[:200])
        return False
    voice_actor_update(did, state="failed",
                       why=str(got.get("why") or "the call road came back with no lines")[:200])
    return False


async def voice_actor_queue_runner(did: str) -> None:
    """[voice-actor] "Queue next": the call chapter is planned as soon as the
    line is free and the station is on air - never over another caller, never
    into a pause - for up to half an hour."""
    deadline = time.time() + VOICE_ACTOR_QUEUE_TTL
    while time.time() < deadline:
        row = voice_actor_row(did)
        if not row or row.get("state") not in ("queued", "held"):
            return
        try:
            if radio_paused():
                voice_actor_update(did, state="held", why="the station is paused - the call waits for the air")
                await asyncio.sleep(20)
                continue
            busy = call_line_busy()
        except Exception:  # noqa: BLE001
            busy = ""
        if busy:
            voice_actor_update(did, state="queued", why=f"{busy} is on the line - this call is next")
            await asyncio.sleep(15)
            continue
        caller = voice_actor_caller(row.get("caller_id"))
        if caller is None:
            voice_actor_update(did, state="failed", why="the caller is no longer on the list")
            return
        if row.get("topic"):
            VOICE_ACTOR_TOPICS[str(caller.get("id") or "")] = str(row["topic"])
        if await voice_actor_ring(caller, "next", did):
            return
        VOICE_ACTOR_TOPICS.pop(str(caller.get("id") or ""), None)
        if (voice_actor_row(did) or {}).get("state") != "queued":
            return
        await asyncio.sleep(15)
    if (voice_actor_row(did) or {}).get("state") in ("queued", "held"):
        voice_actor_update(did, state="missed", why="waited %d minutes for the line and the air"
                           % int(VOICE_ACTOR_QUEUE_TTL / 60))


def voice_actor_heard() -> None:
    """[voice-actor] What the air says about the open dispatches: a caller row
    under that name heard since the call was planned is 'aired' (the latest
    one dates it); planned and never heard within 15 minutes is 'lost'. Reads
    the air log's in-memory index, at most every 5 s."""
    now = time.time()
    if now - float(VOICE_ACTOR_MEMO.get("heard_at") or 0) < 5.0:
        return
    VOICE_ACTOR_MEMO["heard_at"] = now
    with VOICE_ACTOR_LOCK:
        want = [r for r in voice_actor_read()["dispatch"]
                if r.get("state") in ("planned", "aired") and now - float(r.get("at") or 0) < 7200]
    if not want:
        return
    index = globals().get("_AIRLOG_INDEX")
    lock = globals().get("_AIRLOG_LOCK")
    if not isinstance(index, dict):
        return
    try:
        if lock is not None:
            with lock:
                aired = list(index.values())
        else:
            aired = list(index.values())
    except Exception:  # noqa: BLE001
        return
    aired_kinds = set(globals().get("AIRLOG_AIRED") or ("box", "stream", "both"))
    changed = False
    with VOICE_ACTOR_LOCK:
        for row in want:
            since = float(row.get("planned_at") or row.get("at") or 0) - 5.0
            name = " ".join(str(row.get("caller") or "").split()).lower()
            heard = [float(a.get("air_at") or 0) for a in aired
                     if isinstance(a, dict) and str(a.get("who") or "") in ("caller", "caller2")
                     and " ".join(str(a.get("name") or "").split()).lower() == name
                     and str(a.get("aired") or "") in aired_kinds
                     and float(a.get("air_at") or 0) >= since]
            if heard:
                last = max(heard)
                if row.get("state") != "aired" or float(row.get("last_air_at") or 0) < last:
                    row["state"] = "aired"
                    row["aired_at"] = float(row.get("aired_at") or 0) or min(heard)
                    row["last_air_at"] = last
                    row["why"] = "heard on the air"
                    changed = True
            elif row.get("state") == "planned" and now - since > VOICE_ACTOR_HEARD_TTL:
                row["state"] = "lost"
                row["why"] = ("planned into conversation %s, but no line of theirs was heard within %d minutes"
                              % (row.get("conversation_id") or "?", int(VOICE_ACTOR_HEARD_TTL / 60)))
                changed = True
        if changed:
            voice_actor_save()


def voice_actor_state_view() -> dict[str, Any]:
    """[voice-actor] GET /api/voice-actor/state: the store as the panel reads it."""
    try:
        voice_actor_heard()
    except Exception:  # noqa: BLE001
        pass
    try:
        voice_actor_interjection_pending("", "")     # retires an armed call past its half hour
    except Exception:  # noqa: BLE001
        pass
    with VOICE_ACTOR_LOCK:
        state = copy.deepcopy(voice_actor_read())
    armed = next((r for r in state["dispatch"] if r.get("road") == "now" and r.get("state") == "queued"), None)
    return {"combos": state["combos"], "prefs": state["prefs"],
            "scheduled": state["seats"].get("scheduled") or {},
            "random_pin": state["seats"].get("random") or {},
            "dispatch": state["dispatch"], "interjection": armed,
            "engines": list(VOICE_ACTOR_ENGINES), "now": time.time()}


class _VoiceActorBody:
    """api_put_settings reads its body with `await request.json()`; the seat
    road hands it the stored settings with the one change made."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    async def json(self) -> dict[str, Any]:
        return self._payload


async def voice_actor_put_seats(changes: dict[str, str], authorization: str | None) -> dict[str, Any]:
    """[voice-actor] Seat voices through the voice desk's own road: the STORED
    settings (never a browser's copy, so no level is put back) with these dj
    keys changed, through api_put_settings - #820's cut included."""
    payload = copy.deepcopy(load_settings())
    payload.setdefault("dj", {}).update({k: str(v or "")[:100] for k, v in changes.items()})
    return await api_put_settings(_VoiceActorBody(payload), authorization=authorization)


def _voice_actor_body_dict(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="expected a JSON object")
    return payload


@app.get("/api/voice-actor/state")
async def voice_actor_state_api(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_read_auth(authorization)
    return await asyncio.to_thread(voice_actor_state_view)


@app.post("/api/voice-actor/seat")
async def voice_actor_seat_api(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """{seat: host|cohost|third, voice_id} - one seat's voice actor."""
    require_auth(authorization)
    body = _voice_actor_body_dict(await request.json())
    key = VOICE_ACTOR_SEAT_KEYS.get(str(body.get("seat") or ""))
    vid = str(body.get("voice_id") or "")
    if not key:
        raise HTTPException(status_code=400, detail="seat is host, cohost or third")
    if not voice_actor_voice_ok(vid):
        raise HTTPException(status_code=400, detail="no such voice in the library")
    await voice_actor_put_seats({key: vid}, authorization)
    return {"ok": True, "seat": body.get("seat"), "voice_id": vid,
            "say": "Saved - the cast change cuts to the new voice at the next turn boundary (#820)."}


@app.post("/api/voice-actor/combos")
async def voice_actor_combo_save_api(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """{name, seats: {host, cohost, guest_id | third_voice}} - a named pairing."""
    require_auth(authorization)
    body = _voice_actor_body_dict(await request.json())
    name = " ".join(str(body.get("name") or "").split())[:60]
    raw = body.get("seats") if isinstance(body.get("seats"), dict) else {}
    seats = {k: str(raw.get(k) or "")[:100] for k in ("host", "cohost", "third_voice", "guest_id")
             if str(raw.get(k) or "")}
    if not name:
        raise HTTPException(status_code=400, detail="a combo needs a name")
    if not (seats.get("host") or seats.get("cohost")):
        raise HTTPException(status_code=400, detail="a combo seats at least the host or the co-host")
    for k in ("host", "cohost", "third_voice"):
        if not voice_actor_voice_ok(seats.get(k)):
            raise HTTPException(status_code=400, detail="no such voice in the library: " + seats[k])
    if seats.get("guest_id") and not any(g.get("id") == seats["guest_id"] for g in read_guests()):
        raise HTTPException(status_code=400, detail="no such guest")
    if seats.get("guest_id"):
        seats.pop("third_voice", None)          # a guest brings their own voice
    with VOICE_ACTOR_LOCK:
        combos = voice_actor_read()["combos"]
        row = next((c for c in combos if c.get("id") == str(body.get("id") or "")), None)
        if row is None:
            if len(combos) >= VOICE_ACTOR_COMBOS_MAX:
                raise HTTPException(status_code=400,
                                    detail="%d combos is the most kept" % VOICE_ACTOR_COMBOS_MAX)
            row = {"id": "c_" + uuid.uuid4().hex[:8], "created": time.time()}
            combos.append(row)
        row.update(name=name, seats=seats, at=time.time())
        voice_actor_save()
        out = dict(row)
    return {"ok": True, "combo": out, "say": "Saved \"%s\"." % name}


@app.delete("/api/voice-actor/combos/{combo_id}")
async def voice_actor_combo_delete_api(
    combo_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_auth(authorization)
    with VOICE_ACTOR_LOCK:
        state = voice_actor_read()
        before = len(state["combos"])
        state["combos"] = [c for c in state["combos"] if c.get("id") != combo_id]
        if len(state["combos"]) == before:
            raise HTTPException(status_code=404, detail="no such combo")
        voice_actor_save()
    return {"ok": True}


@app.post("/api/voice-actor/combos/{combo_id}/apply")
async def voice_actor_combo_apply_api(
    combo_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Seat a saved pairing in one tap: the voices through api_put_settings
    (#820's cut), then the guest star through set_guest (the activate road)."""
    require_auth(authorization)
    with VOICE_ACTOR_LOCK:
        combo = copy.deepcopy(next((c for c in voice_actor_read()["combos"]
                                    if c.get("id") == combo_id), None))
    if combo is None:
        raise HTTPException(status_code=404, detail="no such combo")
    seats = combo.get("seats") or {}
    guest = None
    if seats.get("guest_id"):
        guest = next((g for g in read_guests() if g.get("id") == seats["guest_id"]), None)
        if guest is None:
            raise HTTPException(status_code=409, detail="the combo's guest star is no longer on the guest list")
    changes = {}
    if seats.get("host"):
        changes["voice"] = seats["host"]
    if seats.get("cohost"):
        changes["cohost_voice"] = seats["cohost"]
    if seats.get("third_voice") and not guest:
        changes["third_voice"] = seats["third_voice"]
    for vid in changes.values():
        if not voice_actor_voice_ok(vid):
            raise HTTPException(status_code=409, detail="the combo's voice is no longer in the library: " + vid)
    if changes:
        await voice_actor_put_seats(changes, authorization)
    if guest is not None:
        set_guest(guest)
    return {"ok": True, "combo": combo.get("name") or combo_id,
            "say": "\"%s\" is seated - the cast change cuts in at the next turn boundary (#820)."
                   % (combo.get("name") or "combo")}


@app.post("/api/voice-actor/prefs")
async def voice_actor_prefs_api(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """{voice_id, preferred: xtts|f5|""} - the actor's RECORDED preferred engine.
    The air always speaks through the one active engine (#1476); this never
    touches a seat, a pin or a level."""
    require_auth(authorization)
    body = _voice_actor_body_dict(await request.json())
    vid = str(body.get("voice_id") or "")
    pref = str(body.get("preferred") or "").lower()
    if not VOICE_ID_SHAPE.match(vid) or voice_meta(vid) is None:
        raise HTTPException(status_code=400, detail="no such voice in the library")
    if pref and pref not in VOICE_ACTOR_ENGINES:
        raise HTTPException(status_code=400, detail="preferred is xtts or f5")
    with VOICE_ACTOR_LOCK:
        prefs = voice_actor_read()["prefs"]
        if pref:
            prefs[vid] = {"preferred": pref, "at": time.time()}
        else:
            prefs.pop(vid, None)
        voice_actor_save()
    return {"ok": True, "voice_id": vid, "preferred": pref}


async def _voice_actor_seat_pin(seat: str, request: Request, authorization: str | None) -> dict[str, Any]:
    require_auth(authorization)
    body = _voice_actor_body_dict(await request.json())
    cid = str(body.get("caller_id") or "")
    caller = voice_actor_caller(cid) if cid else None
    if cid and caller is None:
        raise HTTPException(status_code=404, detail="no such caller")
    with VOICE_ACTOR_LOCK:
        voice_actor_read()["seats"][seat] = ({"caller_id": cid, "caller": str(caller.get("name") or ""),
                                              "at": time.time()} if caller else {})
        voice_actor_save()
    word = "the next scheduled call" if seat == "scheduled" else "the phone clock's next ring"
    return {"ok": True, "seat": seat, "caller_id": cid,
            "say": ("%s takes %s, once." % (caller.get("name"), word)) if caller
                   else "The %s caller seat is back to the station's own draw." % seat}


@app.post("/api/voice-actor/scheduled")
async def voice_actor_scheduled_api(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """{caller_id} - who takes the next scheduled call entry ("" clears)."""
    return await _voice_actor_seat_pin("scheduled", request, authorization)


@app.post("/api/voice-actor/random-pin")
async def voice_actor_random_api(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """{caller_id} - who answers the phone clock's next ring ("" clears)."""
    return await _voice_actor_seat_pin("random", request, authorization)


@app.post("/api/voice-actor/dispatch")
async def voice_actor_dispatch_api(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """{caller_id, road: now|next, topic} - put a listed caller through.

    now:  armed for the NEXT diamond of the round System 3 plans in the
          current segment - a call node in that segment's tree.
    next: a full call chapter, planned as soon as the line is free."""
    require_auth(authorization)
    body = _voice_actor_body_dict(await request.json())
    road = str(body.get("road") or "")
    if road not in ("now", "next"):
        raise HTTPException(status_code=400, detail="road is now or next")
    caller = voice_actor_caller(body.get("caller_id"))
    if caller is None:
        raise HTTPException(status_code=404, detail="no such caller")
    topic = " ".join(str(body.get("topic") or "").split())[:300]
    if road == "now":
        if not _s3_active():
            return {"ok": False, "say": "System 3 is not directing rounds right now, so no diamond can "
                                        "take a call - use Queue next."}
        with VOICE_ACTOR_LOCK:
            armed = next((dict(r) for r in voice_actor_read()["dispatch"]
                          if r.get("road") == "now" and r.get("state") == "queued"), None)
        if armed:
            return {"ok": False, "row": armed,
                    "say": "%s is already waiting for the next diamond - cancel that first."
                           % (armed.get("caller") or "A caller")}
    row = voice_actor_new_dispatch(caller, road, topic)
    pipeline_log("call", "voice actor: %s dispatched (%s)" % (
        row["caller"], "call in now - the next diamond" if road == "now"
        else "queue next - a full call chapter"))
    if road == "next":
        fire_and_forget(voice_actor_queue_runner(row["id"]))
        return {"ok": True, "row": row,
                "say": "%s is queued - a full call chapter plans as soon as the line is free." % row["caller"]}
    return {"ok": True, "row": row,
            "say": "%s is armed - the next diamond System 3 reaches in this segment takes the call."
                   % row["caller"]}


@app.post("/api/voice-actor/dispatch/{dispatch_id}/cancel")
async def voice_actor_dispatch_cancel_api(
    dispatch_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_auth(authorization)
    with VOICE_ACTOR_LOCK:
        row = voice_actor_row(dispatch_id)
        if row is None:
            raise HTTPException(status_code=404, detail="no such dispatch")
        if row.get("state") not in ("queued", "held"):
            return {"ok": False, "row": dict(row),
                    "say": "Too late to cancel - the call is already %s." % row.get("state")}
        row.update(state="cancelled", why="cancelled from the voice actor panel", changed_at=time.time())
        voice_actor_save()
        return {"ok": True, "row": dict(row)}


@app.post("/api/dj/callers/ring")
'''

# --- 3 (next): a dispatched call's own subject ----------------------------------
_TOPIC_OLD = ('    if _tkey:\n'
              '        _recent_t.append(_tkey)\n'
              '        del _recent_t[:-8]\n')
_TOPIC_NEW = ('    _va_topic = voice_actor_topic_take(caller)   # [voice-actor] a dispatched call\'s own subject\n'
              '    if _va_topic:\n'
              '        topic, seed = _va_topic, {}\n'
              '        _tkey = " ".join(topic.split()).lower()\n'
              '    if _tkey:\n'
              '        _recent_t.append(_tkey)\n'
              '        del _recent_t[:-8]\n')

# --- 4a: the Random caller seat answers the phone clock's next ring ----------
_CLOCK_OLD = ('                _banked: list[str] = []\n'
              '                try:\n'
              '                    _banked = list(await dj_caller(_RADIO.get("now"),\n'
              '                                                   shelf_only=True,\n'
              '                                                   fresh_only=True) or [])\n'
              '                except Exception:  # noqa: BLE001\n'
              '                    _banked = []\n'
              '                if _banked:\n')
_CLOCK_NEW = ('                _banked: list[str] = []\n'
              '                # [voice-actor] THE RANDOM CALLER SEAT: the caller the operator\n'
              '                # pinned answers this ring instead of the shelf - once.\n'
              '                _va_rang = False\n'
              '                try:\n'
              '                    _va_pin = voice_actor_pin_take("random")\n'
              '                    if _va_pin:\n'
              '                        _va_rang = await voice_actor_ring(_va_pin, "random")\n'
              '                except Exception:  # noqa: BLE001\n'
              '                    _va_rang = False\n'
              '                try:\n'
              '                    _banked = ([] if _va_rang else list(await dj_caller(_RADIO.get("now"),\n'
              '                                                   shelf_only=True,\n'
              '                                                   fresh_only=True) or []))\n'
              '                except Exception:  # noqa: BLE001\n'
              '                    _banked = []\n'
              '                if _va_rang:\n'
              '                    pipeline_log("call", "the phone clock rang and the caller the "\n'
              '                                 "operator pinned answered (voice actor)")\n'
              '                elif _banked:\n')

# --- 4b: the Scheduled caller seat takes the next scheduled call entry -------
_TORRENT_OLD = ('                    _max_talk = talk_is_incessant(dj)\n'
                '                    aired = bool(await dj_caller(\n'
                '                        track, shelf_only=_max_talk))\n')
_TORRENT_NEW = ('                    _max_talk = talk_is_incessant(dj)\n'
                '                    _va_row = voice_actor_pin_take("scheduled")   # [voice-actor] the Scheduled caller seat\n'
                '                    aired = (await voice_actor_ring(_va_row, "scheduled") if _va_row\n'
                '                             else bool(await dj_caller(track, shelf_only=_max_talk)))\n')
_EXTRA_OLD = ('            held = await dj_caller(track, shelf_only=True)\n'
              '            if held:\n')
_EXTRA_NEW = ('            _va_row = voice_actor_pin_take("scheduled")   # [voice-actor] the Scheduled caller seat\n'
              '            held = (await voice_actor_ring(_va_row, "scheduled") if _va_row\n'
              '                    else await dj_caller(track, shelf_only=True))\n'
              '            if held:\n')

# --- 3 (now): the round that took the call carries the caller ----------------
# "call in now": System 3's graph took the operator's dispatched caller at a
# diamond of THIS round (the runtime hands the handle the interjection). The
# round stays its road's own - no call contract, no caller prep kind - the
# writer's format names C, and C's rows speak in the caller's voice.
_FORMAT_OLD = ("            + (f\", and 'C: ...' for {caller_name} on the phone\"\n"
               "               if caller_name else \"\")\n")
_FORMAT_NEW = ("            + (f\", and 'C: ...' for {caller_name} on the phone\"\n"
               "               if caller_name else \"\")\n"
               "            + voice_actor_format_clause(_s3, caller_name)   # [voice-actor] C, when a diamond took a call\n")
_ENTRY_OLD = ('    if globals().get("system2_stamp_entry"):\n'
              '        system2_stamp_entry(entry)\n')
_ENTRY_NEW = ('    _va_round = voice_actor_round_interjection(_s3, caller_name)   # [voice-actor] C speaks as the caller\n'
              '    if _va_round and not caller_name:\n'
              '        entry["caller_name"] = str(_va_round.get("name") or "")[:80]\n'
              '        entry["caller_voice"] = str(_va_round.get("voice_id") or "")   # _banter_air redraws a dead one (#913)\n'
              '        entry["voice_actor"] = {"dispatch": str(_va_round.get("id") or ""), "road": "now",\n'
              '                                "node": str(_va_round.get("node") or "")}\n'
              '    if globals().get("system2_stamp_entry"):\n'
              '        system2_stamp_entry(entry)\n')

EDITS = [
    ("va-store-routes", _ROUTES_OLD, _ROUTES_NEW, 1),
    ("va-call-topic", _TOPIC_OLD, _TOPIC_NEW, 1),
    ("va-random-seat", _CLOCK_OLD, _CLOCK_NEW, 1),
    ("va-scheduled-torrent", _TORRENT_OLD, _TORRENT_NEW, 1),
    ("va-scheduled-extra", _EXTRA_OLD, _EXTRA_NEW, 1),
    ("va-round-format", _FORMAT_OLD, _FORMAT_NEW, 1),
    ("va-round-entry", _ENTRY_OLD, _ENTRY_NEW, 1),
]


def plan(text):
    return list(EDITS)


def state_of(text, old, new, count):
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(text):
    applied, missing = 0, []
    for name, old, new, count in plan(text):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s (%s)" % (name, state))
    return applied, missing


def apply(path):
    path = Path(path)
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    edits = plan(text)
    if applied == len(edits):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for name, old, new, count in edits:
        if state_of(text, old, new, count) == "applied":
            continue
        assert text.count(old) == count, "%s: anchor found %d times" % (name, text.count(old))
        text = text.replace(old, new)
    assert "\r" not in text
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    try:
        shutil.copymode(str(path), tmp)
    except OSError:
        pass
    os.replace(tmp, path)
    return 0


def main(argv):
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "app.py")
    if do_apply:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    total = len(plan(text))
    if missing:
        for m in missing:
            print("missing:", m)
        print("%d of %d applied" % (applied, total))
        return 1
    if applied == total:
        print("already applied (%d edits)" % total)
        return 2
    print("ready: %d edits, %d already in" % (total, applied))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

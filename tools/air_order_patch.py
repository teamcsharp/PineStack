"""[air-order] Everything waits its turn, and the script numbers a line where
it entered the air queue.

Operator, 2026-09-27, choosing between three answers: "Nothing airs before
something committed earlier. Interjections, clips and ads join the queue
behind the rounds already waiting. Anything time-bound that goes stale while
it waits (an intro for a record already playing) is dropped and recorded,
never aired late." And earlier: "a correct system would have no out of order
messages happening on the broadcast."

Measured over 14 h of heard air (tools-free: air_log x script_ledger x
playout/events.jsonl): 210 of 1,620 script blocks were heard AFTER a block the
ledger numbered later.
  - 200 were NUMBERING only. A round takes its (block, ord) when it is written
    down; a single line took its number only once it had been HEARD (#1339's
    catch-up). An interjection already on the page before a round was even
    written therefore read, in the script, as having jumped it.
  - The rest were real. Of the lines the sequencer QUEUED behind a held round,
    65 were heard before it and 28 after: a queued line was published at once
    with a later stamp, and the page's gap repair pulled it forward in front of
    the round (or the round, chained behind _PAGE_AIR_UNTIL, was pushed behind
    it). Adverts asked with priority and never queued; a line with a welded
    punctuation clip has two cue rows and was read as a committed round, so it
    never asked at all; and the boot recovery re-published in file order.

So:
  reserve-*        script_ledger_reserve: a line is numbered at the PAGE DOOR,
                   the moment it joins the air queue (persisted, one line per
                   clip, kept by a restart's republish); #1339's catch-up
                   writes it under that number once heard. Never heard = a gap
                   in the numbers and nothing in the document, as before.
  commit-*         script_ledger_commit(block=, at=) and a row's `_ord`; the
                   memo stays sorted when a reserved number lands late
  catch-reserved   the catch-up commits reserved rows under their numbers
  waiting-*        THE WAITING LINE: a line that arrives while committed rounds
                   wait is parked OFF the page - reserving nothing, stamping
                   nothing - and published the moment every round it waited
                   behind has gone out, in the order the lines arrived. A line
                   whose record left, or that waited PAGE_WAIT_MAX_S, or whose
                   programme a pause cut, is withdrawn and recorded (feed row
                   `withdrawn`, the drop log, the record-binding desk, the
                   admission gate). The operator's own hands and the call's ring
                   do not wait (a person outranks the show, #206).
                   orch policy `air_order_strict` (default on) is the switch;
                   it only rules while the sequencer is `linear`.
  round-is-held    only a HELD round (its playout_key / ready_round) is a
                   committed round at the door
  door-*           the page door parks, and after a publish either frees the
                   line behind a round or numbers the line
  flush-*          the page's own poll and the air-log keeper free the line
                   when a round leaves by the box or is dropped
  recovery-order   a restart re-publishes in the order the clips were queued
  state            /api/playout shows the waiting line

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes LF
atomically. ON THE HOST. (playout_sequencer.py gains held_keys() separately;
app.py falls back to the book when it is absent.)
"""
import os
import sys
import tempfile
from pathlib import Path

HELPERS_LEDGER = r'''# --- [air-order] A LINE IS NUMBERED WHEN IT ENTERS THE AIR QUEUE ------------
#
# A round takes its (block, ord) when it is written down, just before it waits
# its turn. A single line took its number only once it had been HEARD (#1339's
# catch-up below), so an interjection already on the page before a round was
# even written read, in the script, as having jumped it: 200 of the 210 "late"
# blocks in 14 measured hours (2026-09-27). The number is now taken at the
# page door, the moment the line joins the air queue, and the line is written
# under it once heard. A line never heard leaves a gap in the numbers and
# nothing in the document - #1339's rule, kept.
SCRIPT_RESERVED_PATH = data_path("script_ledger_reserved.jsonl")
SCRIPT_RESERVED_KEEP_S = float(os.getenv("SCRIPT_RESERVED_KEEP_S", "21600"))
SCRIPT_RESERVED_MAX_BYTES = 2 * 1024 * 1024
_SCRIPT_RESERVED: dict[str, tuple[int, float, int]] = {}
_SCRIPT_RESERVED_STATE: dict[str, Any] = {"loaded": False}


def _script_reserved_load() -> None:
    if _SCRIPT_RESERVED_STATE["loaded"]:
        return
    _SCRIPT_RESERVED_STATE["loaded"] = True
    floor = time.time() - SCRIPT_RESERVED_KEEP_S
    try:
        with SCRIPT_RESERVED_PATH.open("rb") as handle:
            for raw in handle:
                try:
                    rec = json.loads(raw)
                    at = float(rec.get("at") or 0)
                    if at < floor:
                        continue
                    ids = [str(x) for x in (rec.get("ids") or [])]
                    ords = list(rec.get("ords") or range(len(ids)))
                    for rid, ord_ in zip(ids, ords):
                        _SCRIPT_RESERVED.setdefault(rid, (int(rec["block"]), at, int(ord_)))
                except Exception:  # noqa: BLE001
                    continue
    except Exception:  # noqa: BLE001
        pass


def _script_reserved_trim() -> None:
    """Forget numbers older than the keep; rewrite the file when it grows."""
    floor = time.time() - SCRIPT_RESERVED_KEEP_S
    if len(_SCRIPT_RESERVED) > 4000:
        for rid, got in list(_SCRIPT_RESERVED.items()):
            if got[1] < floor:
                _SCRIPT_RESERVED.pop(rid, None)
    try:
        if SCRIPT_RESERVED_PATH.stat().st_size <= SCRIPT_RESERVED_MAX_BYTES:
            return
        blocks: dict[int, list[Any]] = {}
        for rid, (block, at, ord_) in sorted(_SCRIPT_RESERVED.items(),
                                             key=lambda kv: (kv[1][0], kv[1][2])):
            got = blocks.setdefault(block, [at, [], []])
            got[1].append(rid)
            got[2].append(ord_)
        tmp = SCRIPT_RESERVED_PATH.with_suffix(".tmp")
        tmp.write_text("".join(
            json.dumps({"block": b, "at": round(v[0], 3), "ids": v[1], "ords": v[2]}) + "\n"
            for b, v in sorted(blocks.items())))
        os.replace(tmp, SCRIPT_RESERVED_PATH)
    except Exception:  # noqa: BLE001
        pass


def script_ledger_reserve(ids: Any, at: float = 0.0) -> int:
    """Number a line - its cue rows, in order - for the script at the moment it
    joins the air queue. A line already numbered keeps its number: a restart
    republishing it is not a new place in the order. Returns the block, or 0."""
    ids = [str(x) for x in (ids or []) if x]
    if not ids:
        return 0
    try:
        with _SCRIPT_LEDGER_LOCK:
            _script_reserved_load()
            had = _SCRIPT_RESERVED.get(ids[0])
            if had:
                return int(had[0])
            block = _script_block_next()
            at = float(at or time.time())
            for ord_, rid in enumerate(ids):
                _SCRIPT_RESERVED.setdefault(rid, (block, at, ord_))
            SCRIPT_RESERVED_PATH.parent.mkdir(parents=True, exist_ok=True)
            with SCRIPT_RESERVED_PATH.open("a") as handle:
                handle.write(json.dumps({"block": block, "at": round(at, 3), "ids": ids,
                                         "ords": list(range(len(ids)))}) + "\n")
            _script_reserved_trim()
            return block
    except Exception:  # noqa: BLE001
        return 0


def script_ledger_reserved(line_id: str) -> tuple[int, float, int] | None:
    """(block, at, ord) the line was numbered with at the page door, or None."""
    if not line_id:
        return None
    _script_reserved_load()
    return _SCRIPT_RESERVED.get(str(line_id))


def _ledger_catch_row(one: dict[str, Any], ord_: int) -> dict[str, Any]:
    """A heard line as #1339 writes it, under the ord it was given at the door."""
    row: dict[str, Any] = {
        "line_id": str(one.get("id") or ""), "who": str(one.get("who") or ""),
        "text": str(one.get("text") or ""), "seconds": float(one.get("seconds") or 0),
        "turn": one.get("turn"), "kind": str(one.get("kind") or ""), "cue": "",
        # NOT scripted: nothing wrote this down in advance
        "scripted": False, "_ord": int(ord_)}
    if isinstance(one.get("bound"), dict):
        row["bound"] = dict(one["bound"])
    try:
        stamp = _s3_line_stamp_of(one)          # asked ONCE: the stamp is popped on read
    except Exception:  # noqa: BLE001
        stamp = None
    if stamp:
        row["system3"] = stamp
    return row


'''

HELPERS_WAITING = r'''# --- [air-order] EVERYTHING WAITS ITS TURN (2026-09-27) ---------------------
#
# "Nothing airs before something committed earlier. Interjections, clips and
#  ads join the queue behind the rounds already waiting. Anything time-bound
#  that goes stale while it waits (an intro for a record already playing) is
#  dropped and recorded, never aired late."
#
# Measured before this: of the lines the sequencer QUEUED behind a held round,
# 65 were heard before it and 28 after. A queued line was published at once
# with a later stamp; page_reservation_repair then closed the "gap" in front of
# it, or the round - stamped behind _PAGE_AIR_UNTIL, which the queued line had
# already pushed out - went after it. Adverts asked with priority and a line
# with a welded punctuation clip never asked at all.
#
# So a line that arrives while committed rounds wait is PARKED here, off the
# page - it reserves no air and stamps nothing, so it cannot push the round
# either - and is published the moment every round it waited behind has gone
# out, in the order the lines arrived.
_PAGE_WAITING: list[dict[str, Any]] = []
_PAGE_WAITING_BUSY = [False]
_AIR_ORDER: dict[str, Any] = {"parked": 0, "flushed": 0, "dropped": 0,
                              "exempt": 0, "last_park": "", "last_drop": ""}
PAGE_WAIT_MAX_S = float(os.getenv("PAGE_WAIT_MAX_S", "900"))
# The operator's own hands, and the call's own ring (it would otherwise ring
# after the call it announces): a person outranks the show (#206).
AIR_ORDER_EXEMPT = frozenset({
    "pine_speak_ack", "script_line_replay", "response_bank_play_api",
    "dj_sfx_play", "_broadcast_replay", "sfx_video_cue_api", "gen_ads_send",
    "play_phone_ring"})


def air_order_strict() -> bool:
    """Does everything wait its turn? Only while the sequencer rules (linear),
    and the operator can turn it off by name (orch policy air_order_strict)."""
    try:
        return (playout_mode() == "linear"
                and orch_policy("air_order_strict", True) is not False)
    except Exception:  # noqa: BLE001
        return False


def playout_held_keys() -> list[str]:
    """The committed rounds waiting their turn right now, by key."""
    seq = playout()
    if seq is None:
        return []
    try:
        keys = getattr(seq, "held_keys", None)
        if callable(keys):
            return [str(k) for k in keys()]
        with seq.lock:
            return [str(k) for k in (getattr(seq, "_held", None) or {})]
    except Exception:  # noqa: BLE001
        return []


def _air_caller_by_hand(depth: int = 2) -> bool:
    """Was the producer asked to say this by a person? Its own `by_hand`,
    read off its frame the way _admission_producer reads its name."""
    try:
        import sys as _sys
        return bool(_sys._getframe(depth).f_locals.get("by_hand"))  # noqa: SLF001
    except Exception:  # noqa: BLE001
        return False


def page_waiting_park(clip: dict[str, Any], ask: dict[str, Any] | None = None,
                      producer: str = "", by_hand: bool = False) -> str:
    """Park a line behind the committed rounds waiting ahead of it. Returns
    its delivery id when parked, "" when it may go now."""
    if not isinstance(clip, dict) or clip.get("air_waited") or not air_order_strict():
        return ""
    if (by_hand or clip.get("by_hand")
            or str(producer or "").split(":", 1)[0] in AIR_ORDER_EXEMPT):
        _AIR_ORDER["exempt"] = int(_AIR_ORDER["exempt"]) + 1
        return ""
    if _PAGE_WAITING:
        page_waiting_flush("a new line arrived")
    ahead = playout_held_keys()
    if not ahead and not _PAGE_WAITING:
        return ""
    did = str(clip.get("delivery_id") or uuid.uuid4().hex[:16])
    clip["delivery_id"] = did
    why = (str((ask or {}).get("why") or "")
           or ("%d committed round(s) wait ahead of it" % len(ahead) if ahead
               else "the lines ahead of it are still waiting"))
    clip["air_waiting"] = {"since": time.time(), "ahead": ahead,
                           "producer": str(producer or "")[:80], "why": why[:200]}
    _PAGE_WAITING.append(clip)
    # [air-order-park] THE WAITING LINE IS THE AIR QUEUE. The line's place in
    # the script is taken now, where it joined the queue - behind the rounds it
    # waits for, in front of any round committed after it. Numbered when it
    # LEFT the line, a station ID that arrived before a banter round was
    # written read, in the script, as having come after it (the one late block
    # of the first 29 heard, 2026-09-28).
    script_ledger_reserve([str(r.get("id") or "") for r in _page_delivery_rows(clip)])
    # A delivery that exists, waiting: whatever looks it up by id (the render
    # backlog's "its tail cannot overtake an uncompleted head") sees a line in
    # flight rather than one that was never published and publishes it twice.
    # Not "received" (the wedge count) and not speech (the triage count) until
    # its turn comes and the page door writes the real one over it.
    _PAGE_DELIVERIES[did] = {"delivery_id": did, "at": time.time(), "state": "waiting",
                             "waiting": True, "clip": clip, "listeners": {},
                             "speech": False}
    _AIR_ORDER["parked"] = int(_AIR_ORDER["parked"]) + 1
    _AIR_ORDER["last_park"] = ("%s: %s" % (clip.get("kind") or "clip", why))[:200]
    return did


def _page_waiting_stale(clip: dict[str, Any], since: float, cut_ms: int) -> str:
    """Why a parked line may no longer air, or ""."""
    now = time.time()
    if cut_ms and since * 1000.0 <= cut_ms:
        return "a pause cut the programme it was waiting in"
    if now - since > PAGE_WAIT_MAX_S:
        return ("it waited %ds for the rounds ahead of it - too long to still "
                "belong where it was written" % int(now - since))
    for row in _page_delivery_rows(clip):
        bound = _RECORD_BOUND_LINES.get(str(row.get("id") or ""))
        if not bound:
            continue
        if bound.get("cut_at"):
            return "its record left the deck while it waited"
        try:
            ok, why = record_binding.check(bound, bound.get("part"), record_bound_deck())
        except Exception:  # noqa: BLE001
            ok, why = True, ""
        if not ok:
            return "its record moved on while it waited: %s" % why
    return ""


def _page_waiting_drop(clip: dict[str, Any], why: str) -> None:
    """Withdrawn, never aired late - and recorded everywhere a line's fate is."""
    _AIR_ORDER["dropped"] = int(_AIR_ORDER["dropped"]) + 1
    _AIR_ORDER["last_drop"] = ("%s: %s" % (clip.get("kind") or "clip", why))[:200]
    who = str(clip.get("who") or "dj")
    text = str(clip.get("remember_text") or clip.get("text") or "")
    ids = {str(r.get("id") or "") for r in _page_delivery_rows(clip)}
    ids.discard("")
    did = str(clip.get("delivery_id") or "")
    if did:
        got = _PAGE_DELIVERIES.get(did)
        if isinstance(got, dict) and got.get("waiting"):
            got["state"] = "withdrawn"
        # and the render backlog lets go of it: a withdrawn head would hold
        # every line behind it for ever
        try:
            kept = [h for h in _RENDER_BACKLOG if str(h.get("delivery_id") or "") != did]
            if len(kept) != len(_RENDER_BACKLOG):
                _RENDER_BACKLOG[:] = kept
                render_backlog_save()
        except Exception:  # noqa: BLE001
            pass
    for entry in (_RADIO.get("chat") or []):
        try:
            if str(entry.get("id") or "") in ids and not screenplay_was_heard(entry):
                entry["aired"] = "withdrawn"
                entry["withdrawn_why"] = ("[air-order] " + why)[:240]
        except Exception:  # noqa: BLE001
            continue
    for rid in ids:
        bound = _RECORD_BOUND_LINES.get(rid)
        if bound:
            record_bound_note(rid, bound, bound.get("part"), False, why,
                              "waiting its turn", who, text)
    try:
        note_drop(who, text, "[air-order] withdrawn while it waited its turn: " + why)
    except Exception:  # noqa: BLE001
        pass
    try:
        controller = admission_controller()
        url = str(clip.get("url") or "")
        if controller is not None and url:
            oid = str((controller.reconcile(media=url) or {}).get("occurrence_id") or "")
            if oid:
                admission_withdraw(oid, "[air-order] " + why)
    except Exception:  # noqa: BLE001
        pass


def page_waiting_flush(why: str = "") -> int:
    """Publish every parked line whose rounds have all gone out, in the order
    the lines arrived; withdraw the ones that went stale. Returns how many
    went. Never while the broadcast is paused - they keep their place."""
    if not _PAGE_WAITING or _PAGE_WAITING_BUSY[0]:
        return 0
    try:
        if radio_paused():
            return 0
    except Exception:  # noqa: BLE001
        pass
    _PAGE_WAITING_BUSY[0] = True
    went = 0
    try:
        strict = air_order_strict()
        held = set(playout_held_keys()) if strict else set()
        cut_ms = int(_RADIO.get("voice_cut_ms") or 0)
        while _PAGE_WAITING:
            clip = _PAGE_WAITING[0]
            wait = clip.get("air_waiting") or {}
            since = float(wait.get("since") or time.time())
            stale = _page_waiting_stale(clip, since, cut_ms)
            if not stale and any(k in held for k in (wait.get("ahead") or [])):
                break                              # its round has not gone yet
            _PAGE_WAITING.pop(0)
            if stale:
                _page_waiting_drop(clip, stale)
                continue
            clip.pop("air_waiting", None)
            clip["air_waited"] = {"s": round(time.time() - since, 1),
                                  "why": str(wait.get("why") or "")[:160]}
            # it joins the air queue NOW: a fresh place for the page's cursor
            # and a fresh stamp behind what the page has been sold
            clip.pop("broadcast_ms", None)
            clip["ts"] = max(int(time.time() * 1000), cut_ms + 1)
            clip["delivery_state"] = "published"
            try:
                if page_feed_append(clip):
                    went += 1
                    _AIR_ORDER["flushed"] = int(_AIR_ORDER["flushed"]) + 1
            except Exception:  # noqa: BLE001
                continue
    finally:
        _PAGE_WAITING_BUSY[0] = False
    return went


def page_waiting_after_publish(clip: dict[str, Any]) -> None:
    """What the door does once a clip is on the page: a committed round that
    went out frees the lines waiting behind it; any other clip takes its
    number in the script now, where it entered the air queue."""
    try:
        if clip.get("playout_key") or clip.get("ready_round"):
            if _PAGE_WAITING:
                page_waiting_flush("a committed round went out")
            return
        script_ledger_reserve([str(r.get("id") or "") for r in _page_delivery_rows(clip)])
    except Exception:  # noqa: BLE001
        pass


def air_order_state() -> dict[str, Any]:
    """The waiting line, for /api/playout."""
    now = time.time()
    line = []
    for clip in list(_PAGE_WAITING)[:12]:
        wait = clip.get("air_waiting") or {}
        line.append({"kind": str(clip.get("kind") or ""),
                     "text": str(clip.get("text") or "")[:80],
                     "waited_s": round(now - float(wait.get("since") or now), 1),
                     "ahead": list(wait.get("ahead") or [])[:6],
                     "producer": str(wait.get("producer") or ""),
                     "why": str(wait.get("why") or "")})
    return {"strict": air_order_strict(), "waiting": len(_PAGE_WAITING),
            "line": line, "wait_max_s": PAGE_WAIT_MAX_S,
            "reserved_numbers": len(_SCRIPT_RESERVED),
            **{k: _AIR_ORDER[k] for k in ("parked", "flushed", "dropped", "exempt",
                                          "last_park", "last_drop")}}


'''

EDITS = [
    ("reserve-helpers",
     '''def script_ledger_commit(sid: str, rows: list[dict[str, Any]],
                         round_kind: str = "", source: str = "") -> int:  # [#1245] source=
''',
     HELPERS_LEDGER + '''def script_ledger_commit(sid: str, rows: list[dict[str, Any]],
                         round_kind: str = "", source: str = "",  # [#1245] source=
                         block: int = 0, at: float = 0.0) -> int:  # [air-order] block=, at=
''', 1),
    ("commit-block",
     '''    if not rows:
        return 0
    block = _script_block_next()
    at = time.time()
''',
     '''    if not rows:
        return 0
    # [air-order] a line numbered when it entered the air queue keeps its number
    block = int(block or 0) or _script_block_next()
    at = float(at or 0.0) or time.time()
''', 1),
    ("commit-ord",
     '''"block": block, "ord": ord_, "at": at,''',
     '''"block": block, "ord": int(row.get("_ord", ord_)), "at": at,  # [air-order] _ord''', 1),
    ("commit-memo",
     '''            if float(_SCRIPT_LEDGER_MEMO.get("at") or 0) > 0:
                held = list(_SCRIPT_LEDGER_MEMO.get("rows") or [])
                held.extend(json.loads(line) for line in out)
                _SCRIPT_LEDGER_MEMO.update({"at": time.time(), "rows": held})
''',
     '''            if float(_SCRIPT_LEDGER_MEMO.get("at") or 0) > 0:
                held = list(_SCRIPT_LEDGER_MEMO.get("rows") or [])
                _late = bool(held) and block < int(held[-1].get("block") or 0)
                held.extend(json.loads(line) for line in out)
                if _late:       # [air-order] a reserved number lands behind later rounds
                    held.sort(key=lambda r: (int(r.get("block") or 0),
                                             int(r.get("ord") or 0)))
                _SCRIPT_LEDGER_MEMO.update({"at": time.time(), "rows": held})
''', 1),
    ("catch-reserved",
     '''    groups: list[list[dict[str, Any]]] = []
    for row in want[:200]:            # a bounded bite per tick
''',
     '''    # [air-order] A LINE NUMBERED AT THE PAGE DOOR is written under that
    # number: where it joined the air queue, not where the ear caught it.
    _caught_reserved = 0
    _by_block: dict[int, list[tuple[dict[str, Any], tuple[int, float, int]]]] = {}
    _unreserved: list[dict[str, Any]] = []
    for row in want:
        _res = script_ledger_reserved(str(row.get("id") or ""))
        if _res:
            _by_block.setdefault(int(_res[0]), []).append((row, _res))
        else:
            _unreserved.append(row)
    for _blk, _pairs in sorted(_by_block.items()):
        _pairs.sort(key=lambda p: int(p[1][2]))
        _first = _pairs[0][0]
        if script_ledger_commit(
                str(_first.get("sid") or ""),
                [_ledger_catch_row(one, res[2]) for one, res in _pairs],
                str(_first.get("round") or ""),
                source=str(_first.get("source") or ""),
                block=_blk, at=float(_pairs[0][1][1])):
            _caught_reserved += len(_pairs)
            for one, _res in _pairs:
                _SCRIPT_RESERVED.pop(str(one.get("id") or ""), None)
    want = _unreserved
    groups: list[list[dict[str, Any]]] = []
    for row in want[:200]:            # a bounded bite per tick
''', 1),
    ("catch-return",
     '''            caught += len(group)
    return caught
''',
     '''            caught += len(group)
    return caught + _caught_reserved    # [air-order]
''', 1),
    ("waiting-helpers",
     '''_page_feed_append_admitted = page_feed_append
''',
     HELPERS_WAITING + '''_page_feed_append_admitted = page_feed_append
''', 1),
    ("round-is-held",
     '''    try:
        stream = (clip or {}).get("stream")
        if isinstance(stream, dict) and len(list(stream.get("rows") or [])) >= 2:
            return True
        return bool((clip or {}).get("ready_round"))
''',
     '''    try:
        # [air-order] a HELD round names its reservation. A single line with a
        # welded punctuation clip has two cue rows too, and is not a round.
        if (clip or {}).get("playout_key") or (clip or {}).get("ready_round"):
            return True
        if air_order_strict():
            return False
        stream = (clip or {}).get("stream")
        if isinstance(stream, dict) and len(list(stream.get("rows") or [])) >= 2:
            return True
        return bool((clip or {}).get("ready_round"))
''', 1),
    ("door-ask",
     '''    if not reply and not playout_is_committed_round(clip):
        _pl_road, _pl_priority = playout_clip_road(clip)
''',
     '''    if (not reply and not playout_is_committed_round(clip)
            and not (clip or {}).get("air_waited")):      # [air-order] its turn came
        _pl_road, _pl_priority = playout_clip_road(clip)
''', 1),
    ("door-park",
     '''        _pl = playout_ask(_pl_road, kind=kind, priority=_pl_priority,
                          seconds=float((clip or {}).get("seconds") or 0.0))
''',
     '''        _pl = playout_ask(_pl_road, kind=kind, priority=_pl_priority,
                          seconds=float((clip or {}).get("seconds") or 0.0))
        # [air-order] EVERYTHING WAITS ITS TURN: while committed rounds wait,
        # the line waits off the page, and goes the moment they have gone
        _pl_parked = page_waiting_park(clip, _pl, producer=_admission_producer(2),
                                       by_hand=_air_caller_by_hand(2))
        if _pl_parked:
            return _pl_parked
''', 1),
    ("door-after",
     '''    if delivery and ticket.get("occurrence_id") and isinstance(clip, dict):
        # The page's own rows can now be joined to the committed occurrence
''',
     '''    if delivery and isinstance(clip, dict):                  # [air-order]
        page_waiting_after_publish(clip)
    if delivery and ticket.get("occurrence_id") and isinstance(clip, dict):
        # The page's own rows can now be joined to the committed occurrence
''', 1),
    ("flush-poll",
     '''    reservation_updates = await asyncio.to_thread(page_reservation_repair)
''',
     '''    if _PAGE_WAITING:                                        # [air-order]
        page_waiting_flush("a page asked for the feed")
    reservation_updates = await asyncio.to_thread(page_reservation_repair)
''', 1),
    ("flush-keeper",
     '''            _ensure_chat_ids()
            # #1339: anything that reached the air without a written
''',
     '''            _ensure_chat_ids()
            if _PAGE_WAITING:                              # [air-order]
                page_waiting_flush("the air-log keeper's tick")
            # #1339: anything that reached the air without a written
''', 1),
    ("recovery-order",
     '''    owned = await _floor_take("preserved page deliveries after reservation repair")
    try:
        for original in saved:
''',
     '''    owned = await _floor_take("preserved page deliveries after reservation repair")
    # [air-order] re-published in the order they were queued for the air
    saved = sorted(saved, key=lambda r: int(r.get("broadcast_ms") or r.get("ts") or 0))
    try:
        for original in saved:
''', 1),
    ("state",
     '''        got = _playout_with_exact_line(dict(seq.state(limit=limit)))
        got["available"] = True
        return got
''',
     '''        got = _playout_with_exact_line(dict(seq.state(limit=limit)))
        got["available"] = True
        got["waiting_line"] = air_order_state()              # [air-order]
        return got
''', 1),
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

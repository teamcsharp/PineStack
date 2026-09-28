"""[s3-banks-roll] What the banks put on the air is the roulette's.

Operator, 2026-09-28: "the point of making everything go on system 3 is to have
no dialogue hit the station unless it is scripted via the RNG roulette system";
"i dont want these banked lines unless they come up in a roulette"; "a
discussion will need to be had on anything forced onto the air. To make sure it
is accountable as a node and part of the system3 design". His three decisions,
built here through the dice door (s3_chance / s3_pool / _S3Dice - rows table
themselves into STATION1 / POOLS1 on their first roll):

  BANKED-ROUND RE-AIRS - "a roulette decision". A banked round that has already
      aired goes out again only when bank.reair says so; the pick among the
      rested, eligible replays is bank.reair_pick (POOLS1, by airings - weight
      a class or switch it off); the airing is stamped on its ledger rows as a
      replay ("replay, first aired <time>, airing N"). The caps stay as the
      station keeps them: the rest (reuse_rest 3 h - the 1 h floor while the
      operator's repeats_hard answer stands, as it does live) and the innings
      (3, calls 2, evergreen/rhymed 12, each + the innings_bonus dial, live +6).
      Gated on every road that re-airs: the larder's serve (dj_banter - the
      torrent's floor included), every shelf_take, the cupboard's door
      (_ready_shelf_air - dead-air rescue, the sweeps, the memo breaking in; a
      refused replay gives way to a first airing the plot preference passed
      over), System2's slot (edit_system2_runtime.py), a call re-air
      (call_rerun_take, which also only re-airs a call whose System 3 round is
      found) and the emergency host's recorded pairs (continuity_air: a LINE
      draw on a node of its own). The operator's Play now (`named`) is his
      decision: never rolled, stamped a replay. A first airing is never
      rolled; the resume reel (first airings only) is cut from System 3 rounds
      alone and each of its lines names its node.
  THE RE-AIR GATE - asked before any of it, dice on or off, on every road
      above (bank_reair_refusal, reair_gate.py): a round with copied turns
      (> 0.9 like an earlier turn), an echo loop, a non_compliant verdict, the
      copy gate's flags, or the one-time sweep's mark (tools/reair_sweep.py
      --apply -> data/reair_ineligible.json) never goes out again - not even
      on Play now - and no die is cast for it.
  GOLD - "roulette for the run". gold_fill_gap lays a run only when gold.run
      says so; gold.pick rolls the whole order (the tier's bare shuffle is the
      dice-off path only); only bars minted from System 3 turns are eligible
      (gold_note records its {conversation_id, turn_id}); each bar that airs -
      in a gap or inside a round - is stamped with the turn it was minted from.
  LISTENING RESPONSES - "a roll per seam". Each seam rolls listen.seam on the
      round's node, the response is a listen.pick roll among the eligible ones
      (response_bank.py's chooser - not least-recently-used), and the response
      is stamped to the turn it answers.

The odds ship at 1.0 (BANK_REAIR_ODDS, GOLD_RUN_ODDS, LISTEN_SEAM_ODDS): what
each road did before, every time. Rolls that shape a round already planned are
recorded ON that round (system3_roll_to, system3_runtime.py - same batch); a
runtime without it still rolls and stamps, the roll then only on the desk's
station record. With System 3's dice off every road is as it was - except that
the re-air gate still holds.

Needs, in the same deploy: reair_gate.py (new, repo root - without it the gate
refuses nothing and says so once), response_bank.py's `chooser`
(edit_response_bank.py) and system3_runtime.py's roll_to + line keeps
(edit_system3_runtime.py); System2's road is edit_system2_runtime.py.

--check exits 0 ready / 2 applied / 1 missing. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ('helpers',
     r'''# --- [#1386] GOLD IS A RESERVE, NOT PROGRAMMING --------------------------
''',
     r'''# --- [s3-banks-roll] WHAT THE BANKS PUT ON THE AIR IS THE ROULETTE'S ----------
# "the point of making everything go on system 3 is to have no dialogue hit the
# station unless it is scripted via the RNG roulette system"; "i dont want
# these banked lines unless they come up in a roulette" (operator, 2026-09-28).
# Three roads put stock on the air without a roll. Each is now a decision on
# the desk, through the dice door above (STATION1 / POOLS1):
#
#   bank.reair      a banked round that has ALREADY aired goes out again only
#                   when this row says so - the larder's serve, every shelf
#                   take, the cupboard's door (dead-air rescue, the torrent's
#                   floor, a road asking before it writes, the memo breaking
#                   in), a call re-air and the emergency host's recorded pairs.
#                   bank.reair_pick rolls among the rested, eligible replays
#                   (POOLS1: weight a class of replay, or switch one off), and
#                   the airing is stamped on its ledger rows as a replay -
#                   "replay, first aired <time>, airing N". The caps are the
#                   station's own and unchanged: shelf_rest_now() (reuse_rest,
#                   3 h - the 1 h floor under repeats_hard) and row_innings()
#                   (3, calls 2, evergreen/rhymed 12, + innings_bonus).
#   gold.run        a run of gold bars fills a gap only when this row says so;
#                   gold.pick rolls every bar of the order (the tier's order is
#                   no longer a shuffle), only bars minted from System 3 turns
#                   are eligible, and each bar that airs is stamped with the
#                   conversation/turn it was minted from - a node on the air.
#   listen.seam     each seam where a listening response could go rolls on the
#                   round's node; listen.pick rolls the response among the
#                   eligible ones (not the least-recently-used), and it is
#                   stamped to the turn it answers.
#
# THE RE-AIR GATE comes before all of it (reair_gate.py, bank_reair_refusal):
# a round with copied turns, an echo loop, a non_compliant verdict or turns
# the copy gate flagged - or one the one-time sweep (tools/reair_sweep.py)
# marked - never goes out again, dice on or off, on any road; no roll is made
# for it. Measured 2026-09-28: banter round ef39853f9fa54974 (turns copying
# each other, one with a slur) aired seven times in 17 h off the larder serve.
#
# A FIRST airing of a banked System 3 round is the bank doing its job and is
# never rolled. A roll that shapes a round already planned is recorded on
# THAT round (a STATION observation under its turn, system3_roll_to) instead
# of waiting in the task's buffer for the next plan to absorb as its own. The
# odds ship at 1.0 - what each road did before, every time - so this alone
# moves nothing on the air; the desk walks them down. System 3's dice off:
# every road exactly as it was.
BANK_REAIR_ODDS = float(os.getenv("BANK_REAIR_ODDS", "1.0"))
GOLD_RUN_ODDS = float(os.getenv("GOLD_RUN_ODDS", "1.0"))
LISTEN_SEAM_ODDS = float(os.getenv("LISTEN_SEAM_ODDS", "1.0"))
# A road the roulette just refused asks again after this long, not on its next
# five-second pass: one decision per window, or the odds would only decide how
# many seconds a replay waits.
BANK_REAIR_MISS_REST = float(os.getenv("BANK_REAIR_MISS_REST", "120"))
GOLD_RUN_MISS_REST = float(os.getenv("GOLD_RUN_MISS_REST", "60"))
BANK_REAIR_LABEL = ("a banked round that has already aired goes out again "
                    "(otherwise something heard for the first time, or the next rung)")
# The classes the replay pick weighs (POOLS1 bank.reair_pick) - by the meter
# the station counts its stock in, airings. They start even; the desk may
# weight one, or switch it off.
BANK_REAIR_CLASSES = ("a replay heard once before", "a replay heard twice before",
                      "a replay heard three or more times before")
_BANK_REAIR_MISS: dict[str, float] = {}
# line id -> the node a line the AIR spliced in by a roll belongs to (a
# listening response: the turn it answers; a gold bar in a round: the turn it
# was minted from). Read when the round's rows are committed.
_S3_AIR_OWN: dict[str, dict[str, Any]] = {}
_RERUN_S3: dict[str, dict[str, Any]] = {}
_RERUN_S3_INDEX: dict[str, Any] = {"at": 0.0, "index": {}}
# the one-time sweep's marks (tools/reair_sweep.py --apply): {mark key: why}
REAIR_MARKS_PATH = data_path("reair_ineligible.json")
_REAIR_MARKS: dict[str, Any] = {"at": 0.0, "mtime": -1.0, "marks": {}}
_REAIR_GATE_SAID: dict[str, float] = {}


def _reair_marks() -> dict[str, Any]:
    """The sweep's marks, read again when the file changes (its mtime is
    looked at twice a minute at most)."""
    now = time.time()
    if now - float(_REAIR_MARKS["at"]) < 30:
        return _REAIR_MARKS["marks"]
    _REAIR_MARKS["at"] = now
    try:
        mtime = REAIR_MARKS_PATH.stat().st_mtime
    except OSError:
        _REAIR_MARKS.update(mtime=-1.0, marks={})
        return _REAIR_MARKS["marks"]
    if mtime != _REAIR_MARKS["mtime"]:
        try:
            import reair_gate
            _REAIR_MARKS.update(mtime=mtime, marks=reair_gate.load_marks(REAIR_MARKS_PATH))
        except Exception:  # noqa: BLE001
            _REAIR_MARKS.update(mtime=mtime, marks={})
    return _REAIR_MARKS["marks"]


def bank_reair_refusal(road: str, row: Any, cid: str = "") -> str:
    """THE RE-AIR GATE: why this banked round may NEVER go out again, or ""
    when it may (the roulette then decides whether it does). reair_gate.py's
    rule - copied turns, an echo loop, a non_compliant verdict, the copy
    gate's flags, the sweep's mark - asked of every replay before any roll,
    dice on or off. `cid`: a finished call's System 3 round, found by its
    words. A gate whose module is missing refuses nothing, and says so once."""
    try:
        import reair_gate
    except Exception as exc:  # noqa: BLE001
        if not _REAIR_GATE_SAID.get("__missing__"):
            _REAIR_GATE_SAID["__missing__"] = time.time()
            pipeline_log("air", "the re-air gate is not installed (reair_gate.py) - replays go "
                                "to the roulette unchecked", extra="%s: %s" % (type(exc).__name__, exc))
        return ""
    try:
        why = str(reair_gate.refusal(row, _reair_marks(), cid) or "")
    except Exception:  # noqa: BLE001
        return ""
    if why:
        try:
            key = (reair_gate.mark_keys(row, cid) or [str(id(row))])[0]
        except Exception:  # noqa: BLE001
            key = str(id(row))
        if time.time() - float(_REAIR_GATE_SAID.get(key) or 0) > 3600:
            _REAIR_GATE_SAID[key] = time.time()
            while len(_REAIR_GATE_SAID) > 500:
                _REAIR_GATE_SAID.pop(next(iter(_REAIR_GATE_SAID)))
            pipeline_log("air", ("a banked %s round never goes out again - the re-air gate: %s"
                                 % (road, why))[:200], extra=key)
    return why


def _s3_roll_on(key: str, cid: str = "", turn_id: str = "", stage: str = "",
                since: float = 0.0) -> dict[str, Any]:
    """The roll the dice door just made under `key`, as a line's stamp carries
    it. With `cid` it is also recorded on the round it shaped - a STATION
    observation under `turn_id`, in the Rolodex - and taken out of this task's
    buffer, so the next plan does not absorb it as its own. {} when System 3
    did not roll it (its dice off: the station's own random)."""
    fn = globals().get("system3_last_roll")
    try:
        rec = fn(key) if fn else None
    except Exception:  # noqa: BLE001
        rec = None
    if (not isinstance(rec, dict) or time.time() - float(rec.get("at") or 0) > 60
            or float(rec.get("at") or 0) < float(since or 0)):
        return {}
    out = {k: rec.get(k) for k in ("kind", "key", "label", "odds", "hit", "dice", "u",
                                   "index", "of", "picked") if rec.get(k) is not None}
    words = str(stage or "")
    if "{" in words:
        try:
            words = words.format(dice=rec.get("dice"), odds=int(round(float(rec.get("odds") or 0) * 100)),
                                 index=rec.get("index"), of=rec.get("of"),
                                 picked=str(rec.get("picked") or "")[:80],
                                 hit="yes" if rec.get("hit") else "no")
        except Exception:  # noqa: BLE001
            pass
    claim = globals().get("system3_roll_to")
    if cid and claim:
        try:
            got = claim(key, str(cid), str(turn_id or ""), words)
            if isinstance(got, dict) and got:
                out = dict(got)
        except Exception:  # noqa: BLE001
            pass
    return out


def _s3_air_own(line_id: Any, stamp: Any) -> None:
    """Name the node of a line the air spliced into a round (see _S3_AIR_OWN)."""
    if line_id and isinstance(stamp, dict) and stamp.get("conversation_id"):
        _S3_AIR_OWN[str(line_id)] = dict(stamp)
        while len(_S3_AIR_OWN) > 600:
            _S3_AIR_OWN.pop(next(iter(_S3_AIR_OWN)))


def _s3_air_rows(rows: Any, meta: Any) -> None:
    """A round's ledger rows, the moment before they are committed: a line the
    air spliced in by a roll names its own node, and every spoken line of a
    banked round going out again carries its replay stamp."""
    rep = meta.get("_s3_replay") if isinstance(meta, dict) else None
    if not (isinstance(rep, dict) and time.time() - float(rep.get("at") or 0) < 1800):
        rep = None
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        own = _S3_AIR_OWN.get(str(row.get("line_id") or ""))
        if isinstance(own, dict) and own.get("conversation_id"):
            row["system3"] = dict(own)
            row.pop("dice", None)           # the round's turn dice are not its
            continue
        st = row.get("system3")
        if (rep and isinstance(st, dict) and st.get("conversation_id")
                and str(row.get("who") or "") not in ("board", "drop")):
            row["system3"] = dict(st, replay=dict(rep))


def bank_s3_of(entry: Any) -> dict[str, Any]:
    """The System 3 conversation a banked round (or its shelf row) was scripted
    as - its stamp, active and with a conversation - else {}."""
    try:
        got = entry.get("system3") if isinstance(entry, dict) else None
        if not isinstance(got, dict) and isinstance(entry, dict) and isinstance(entry.get("entry"), dict):
            got = entry["entry"].get("system3")
        if isinstance(got, dict) and got.get("conversation_id") and got.get("mode") == "active":
            return got
    except Exception:  # noqa: BLE001
        pass
    return {}


def _s3_turn_of_words(meta: Any, text: str) -> str:
    """The planned turn whose words hold most of `text` (a chunk the air
    injected stumbles into), by share of words - "" under 60%."""
    try:
        s3 = bank_s3_of(meta)
        ids = s3.get("turns") if isinstance(s3.get("turns"), dict) else {}
        words = re.findall(r"[a-z']+", str(text or "").lower())
        if not ids or len(words) < 3:
            return ""
        best, at = 0.0, None
        for i, (_m, said) in enumerate(banter_turns(str(meta.get("script") or ""),
                                                     str(meta.get("caller_name") or ""),
                                                     str(meta.get("caller2_name") or ""))):
            have = set(re.findall(r"[a-z']+", str(said or "").lower()))
            if not have:
                continue
            share = sum(1 for w in words if w in have) / len(words)
            if share > best:
                best, at = share, i
        return str(ids.get(str(at)) or "") if at is not None and best >= 0.6 else ""
    except Exception:  # noqa: BLE001
        return ""


def bank_line_stamp(entry: Any, text: str, who: str = "") -> dict[str, Any]:
    """The node one banked line belongs to: its round's conversation and the
    turn whose words it is ({} when the round is not System 3's, or the words
    are not one of its turns)."""
    s3 = bank_s3_of(entry)
    if not s3:
        return {}
    tid = ""
    fn = globals().get("system3_turn_id_for")
    if fn:
        try:
            tid = str(fn(entry, str(text or ""), str(who or "")) or "")
        except Exception:  # noqa: BLE001
            tid = ""
    tid = tid or _s3_turn_of_words(entry, text)
    if not tid:
        return {}
    return {"conversation_id": str(s3["conversation_id"]), "mode": "active", "turn_id": tid}


def _bank_clock(at: Any) -> str:
    try:
        return time.strftime("%H:%M", time.localtime(float(at)))
    except Exception:  # noqa: BLE001
        return "?"


def bank_replay_stamp(road: str, row: Any, chance: Any = None, pick: Any = None,
                      decided_by: str = "") -> dict[str, Any]:
    """What a banked round's lines carry the time it goes out again: when it
    was first heard, which airing this is, and the rolls that let it out."""
    row = row if isinstance(row, dict) else {}
    try:
        before = int(round_airings_now(str(road), row))
    except Exception:  # noqa: BLE001
        before = int(row.get("aired") or 0)
    last = float(row.get("aired_at") or 0)
    first = float(row.get("first_aired_at") or 0)
    if not first and last and before <= 1:
        first = last                    # one airing before this: that WAS the first
        try:
            row["first_aired_at"] = first
        except Exception:  # noqa: BLE001
            pass
    airing = max(2, before + 1)
    if first:
        label = "replay, first aired %s, airing %d" % (_bank_clock(first), airing)
    elif last:
        label = "replay, first aired at or before %s, airing %d" % (_bank_clock(last), airing)
    else:
        label = "replay, airing %d" % airing
    out: dict[str, Any] = {"at": time.time(), "road": str(road), "airing": airing, "label": label,
                           "first_aired": first or None, "last_aired": last or None}
    if chance:
        out["chance"] = dict(chance)
    if pick:
        out["pick"] = dict(pick)
    if decided_by:
        out["decided_by"] = str(decided_by)[:160]
    return out


def bank_replay_attach(row: Any, stamp: Any) -> None:
    """A replay taken off a shelf carries its stamp to the air: on the round's
    entry (its ledger rows read it) or on a single line's own node."""
    if not isinstance(row, dict) or not isinstance(stamp, dict):
        return
    entry = row.get("entry")
    if isinstance(entry, dict):
        entry["_s3_replay"] = dict(stamp)
    elif isinstance(row.get("system3"), dict) and row["system3"].get("conversation_id"):
        row["system3"] = dict(row["system3"], replay=dict(stamp))


def _bank_reair_class(road: str, row: Any) -> str:
    try:
        heard = int(round_airings_now(str(road), row))
    except Exception:  # noqa: BLE001
        heard = 1
    return BANK_REAIR_CLASSES[max(0, min(len(BANK_REAIR_CLASSES) - 1, heard - 1))]


def bank_reair_pick(road: str, rows: Any, where: str = "") -> tuple[Any, dict[str, Any] | None]:
    """Whether a banked round that has already aired goes out again, and which:
    (row, replay stamp), or (None, None) when the roulette keeps the replays
    off. `rows` are the rested replays in the order the road would have taken
    them; the re-air gate strikes out any it retired before a die is cast.
    System 3's dice off: the first the gate lets through, as before."""
    road = str(road or "")
    # the re-air gate first: a round it retired is never rolled for
    rows = [r for r in (rows or []) if isinstance(r, dict) and not bank_reair_refusal(road, r)]
    if not rows:
        return None, None
    if not _s3_dice_live():
        return rows[0], None
    if time.time() - float(_BANK_REAIR_MISS.get(road) or 0) < BANK_REAIR_MISS_REST:
        return None, None               # the roulette said no a moment ago
    t0 = time.time()
    if not s3_chance("bank.reair", BANK_REAIR_ODDS, BANK_REAIR_LABEL):
        _BANK_REAIR_MISS[road] = time.time()
        pipeline_log("air", "the roulette kept the %s replays off (bank.reair) - %s"
                     % (road, where or "nothing heard for the first time was ready"))
        return None, None
    _BANK_REAIR_MISS.pop(road, None)
    live = set(s3_pool("bank.reair_pick", list(BANK_REAIR_CLASSES),
                       "which replay goes out - weight a class, or switch it off"))
    cands = [(r, _bank_reair_class(road, r)) for r in rows]
    cands = [(r, c) for r, c in cands if c in live]
    if not cands:
        pipeline_log("air", "every %s replay standing by is in a class the desk "
                            "switched off (bank.reair_pick)" % road)
        return None, None
    t1 = time.time()
    k = _S3Dice("bank.reair_pick", "which replay goes out").pick(
        "bank.reair_pick", [c for _r, c in cands])
    row = cands[k if 0 <= k < len(cands) else 0][0]
    cid = str(bank_s3_of(row).get("conversation_id") or "")
    chance = _s3_roll_on("bank.reair", cid, "",
                         "a banked round goes out again: rolled {dice} under {odds}% - {hit}", since=t0)
    pick = _s3_roll_on("bank.reair_pick", cid, "",
                       "which replay: {index} of {of} ({picked})", since=t1)
    return row, bank_replay_stamp(road, row, chance, pick, where)


def larder_reair_gate(at: int) -> tuple[int, dict[str, Any] | None]:
    """dj_banter's larder serve chose _LARDER[at]. A first airing stands (no
    roll). A replay the re-air gate retired never goes out again - dice on or
    off, the serve passes on to the next round it could take in its own order,
    or writes fresh. Otherwise, under System 3's dice, a replay goes to the
    roulette - after any first airing the larder could serve instead, which
    always goes first: (index, replay stamp), or (-1, None) when nothing may
    go. Nothing is stamped or moved here; the serve does that, as before."""
    try:
        entry = _LARDER[at]
    except Exception:  # noqa: BLE001
        return -1, None
    if not isinstance(entry, dict) or not entry.get("aired_at"):
        return at, None                     # heard for the first time: the bank's job
    now = time.time()

    def _servable(e: Any) -> bool:
        try:
            return bool(isinstance(e, dict) and dialogue_row_ready("banter", e) and _larder_current(e))
        except Exception:  # noqa: BLE001
            return False

    def _first_airing(e: Any) -> bool:
        return (_servable(e) and not e.get("aired_at")
                and now - float(e.get("at") or 0) < larder_fresh())

    def _replay(e: Any) -> bool:
        return (_servable(e) and bool(e.get("aired_at")) and shelf_repeat_ready("banter", e)
                and (now - float(e.get("at") or 0) < larder_fresh()
                     or (shelf_is_repeat("banter", e)
                         and now - float(e.get("at") or 0) <= REPEAT_KEEP_SECONDS)))

    if not _s3_dice_live():
        if not bank_reair_refusal("banter", entry):
            return at, None                 # the station's own order, as before
        for i, e in enumerate(_LARDER):
            if _first_airing(e) or (_replay(e) and not bank_reair_refusal("banter", e)):
                return i, None
        return -1, None
    for i, e in enumerate(_LARDER):
        if _first_airing(e):
            return i, None                  # heard for the first time: the bank's job
    rows = [e for e in _LARDER if _replay(e)]
    if not rows:
        # the serve's own tests decide, as before - they will not air a
        # replay that is neither fresh nor kept; one the gate retired, never
        return (-1, None) if bank_reair_refusal("banter", entry) else (at, None)
    got, stamp = bank_reair_pick("banter", rows, "the larder's serve")
    if got is None:
        return -1, None
    for i, e in enumerate(_LARDER):
        if e is got:
            return i, stamp
    return -1, None


def listening_seam_take(listener: str, context: str, used: Any, voices: Any,
                        meta: Any) -> dict[str, Any] | None:
    """add_listening_responses' chooser at one seam of a round. The seam rolls
    on the round's node (listen.seam) and the response is a roll among the
    eligible ones (listen.pick) - both recorded on the round under the turn
    being answered - and the response is stamped to that turn. System 3's
    dice off: the bank's own least-recently-used take, as before."""
    voice = str((voices or {}).get(listener) or "")
    engine = voice_engine_for(voice)
    crystal = continuity_crystal()
    if not _s3_dice_live():
        return _RESPONSES.take(voice, engine, context, used, crystal=crystal)
    s3 = bank_s3_of(meta)
    cid = str(s3.get("conversation_id") or "")
    tid = ""
    fn = globals().get("system3_turn_id_for")
    if cid and fn:
        try:
            tid = str(fn(meta, str(context or ""), "") or "")
        except Exception:  # noqa: BLE001
            tid = ""
    if cid and not tid:
        tid = _s3_turn_of_words(meta, context)
    rolled: dict[str, Any] = {}

    def chooser(rows: list[dict[str, Any]]) -> int:
        t0 = time.time()
        hit = s3_chance("listen.seam", LISTEN_SEAM_ODDS,
                        "a listening response at a seam in a long turn (otherwise the turn runs on)")
        rolled["seam"] = _s3_roll_on("listen.seam", cid, tid,
                                     "a listening response at this seam: rolled {dice} under {odds}% - {hit}",
                                     since=t0)
        if not hit:
            return -1
        t1 = time.time()
        k = _S3Dice("listen.pick", "which listening response (the eligible ones)").pick(
            "listen.pick", [str(r.get("said") or r.get("text") or "")[:80] for r in rows])
        rolled["pick"] = _s3_roll_on("listen.pick", cid, tid,
                                     "which listening response: {index} of {of} ({picked})", since=t1)
        return k

    try:
        got = _RESPONSES.take(voice, engine, context, used, crystal=crystal, chooser=chooser)
    except TypeError:
        return None                         # a bank that cannot take the roll airs none
    if not got:
        return None
    out = dict(got)
    if cid:
        stamp = {"conversation_id": cid, "mode": "active", "turn_id": tid,
                 "listening": dict({"who": str(listener or ""),
                                    "text": str(got.get("said") or got.get("text") or "")[:120],
                                    "label": "a listening response at a seam of this turn, rolled"},
                                   **{k: v for k, v in rolled.items() if v})}
        out["line_id"] = uuid.uuid4().hex
        out["system3"] = stamp              # the item's own node: named at the round's door
        _s3_air_own(out["line_id"], stamp)
    return out


def gold_source(row: Any) -> dict[str, Any]:
    """The System 3 turn a gold bar was minted from ({} for a bar minted before
    bars carried one, or off a round no node made)."""
    src = row.get("source") if isinstance(row, dict) else None
    if isinstance(src, dict) and src.get("conversation_id") and src.get("turn_id"):
        return {"conversation_id": str(src["conversation_id"]), "turn_id": str(src["turn_id"]),
                "mode": "active"}
    return {}


def gold_tier_pick(tier: Any) -> dict[str, Any] | None:
    """The whole order of a least-fired tier is the dice door's: each next bar
    is one more roll among the ones left, made only when the bar before it has
    lost its take - one file checked per roll (#1412)."""
    left = [r for r in (tier or []) if isinstance(r, dict)]
    while left:
        k = _S3Dice("gold.pick", "which banked gold bar fires (the least-fired tier)").pick(
            "gold", [str(r.get("text") or "")[:160] for r in left])
        r = left.pop(k if 0 <= k < len(left) else 0)
        if (VOICE_MEDIA_DIR / str(r.get("path") or "")).is_file():
            return r
    return None


def gold_run_ready(exclude_who: str = "", min_rest: float | None = None) -> bool:
    """Could gold_pick fire a bar at all (by its rest and eligibility rules -
    the takes are checked when one is picked)? A run is rolled only then."""
    try:
        now = time.time()
        rest = GOLD_REST if min_rest is None else float(min_rest)
        window = repeat_window()
        if window > 0:
            rest = max(rest, window / 2.0)
        return any(str(r.get("who") or "") != str(exclude_who or "")
                   and now - float(r.get("last") or 0) >= rest
                   and not cast_names_line_stale(r)
                   and (not _s3_active() or bool(gold_source(r)))
                   for r in _gold_rows())
    except Exception:  # noqa: BLE001
        return False


def gold_air_stamp(bar: Any, run_key: str = "", run_since: float = 0.0,
                   pick_since: float = 0.0) -> dict[str, Any] | None:
    """A gold bar on the air is a node: the System 3 turn it was minted from,
    with the rolls that let it out (the run - or the round's in-round roll -
    and the bar) recorded on that conversation, under that turn. None for a
    bar with no System 3 turn behind it."""
    src = gold_source(bar)
    if not src:
        return None
    cid, tid = src["conversation_id"], src["turn_id"]
    firing = int((bar or {}).get("fired") or 0) + 1
    gold: dict[str, Any] = {"bar": str((bar or {}).get("key") or ""), "minted": (bar or {}).get("at"),
                            "firing": firing,
                            "label": "gold bar minted %s from this turn, firing %d"
                                     % (_bank_clock((bar or {}).get("at") or 0), firing)}
    if run_key:
        run = _s3_roll_on(run_key, cid, tid,
                          ("a gold run fills the gap: rolled {dice} under {odds}% - {hit}"
                           if run_key == "gold.run" else
                           "a gold bar fires inside the round: rolled {dice} under {odds}% - {hit}"),
                          since=run_since)
        if run:
            gold["run"] = run
    pick = _s3_roll_on("gold.pick", cid, tid, "which gold bar: {index} of {of} ({picked})",
                       since=pick_since)
    if pick:
        gold["pick"] = pick
    return {"conversation_id": cid, "turn_id": tid, "mode": "active", "gold": gold}


def _rerun_norm(text: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower()).split())[:60]


def _rerun_text_index() -> dict[str, list[tuple[str, str]]]:
    """The script ledger's System 3 lines of the last day and a bit, by their
    words: {words: [(conversation, turn)]}. Rebuilt at most once a minute, in
    the rerun's pick thread - one walk for every candidate call."""
    now = time.time()
    if now - float(_RERUN_S3_INDEX.get("at") or 0) < 60:
        return _RERUN_S3_INDEX["index"]
    index: dict[str, list[tuple[str, str]]] = {}
    for led in reversed(script_ledger_rows()):
        at = float(led.get("at") or 0)
        if at and at < now - 26 * 3600:
            break
        s3 = led.get("system3")
        if (not isinstance(s3, dict) or not s3.get("conversation_id")
                or not s3.get("turn_id") or s3.get("replay")):
            continue
        n = _rerun_norm(led.get("text"))
        if len(n) >= 12:
            index.setdefault(n, []).append((str(s3["conversation_id"]), str(s3["turn_id"])))
    _RERUN_S3_INDEX.update(at=now, index=index)
    return index


def rerun_s3_source(row: Any) -> dict[str, Any]:
    """The System 3 round a finished call was, found by its words in the script
    ledger (the call log keeps no conversation id): {"conversation_id", "turns":
    {words: turn_id}} or {}. The round most of the call's lines belong to (a
    stock greeting belongs to every call). Cached per call."""
    key = str((row or {}).get("id") or "")
    if not key:
        return {}
    if key in _RERUN_S3:
        return _RERUN_S3[key]
    want = {_rerun_norm(t.get("text")) for t in (row.get("transcript") or [])
            if isinstance(t, dict) and len(_rerun_norm(t.get("text"))) >= 12}
    got: dict[str, Any] = {}
    if want:
        index = _rerun_text_index()
        votes: collections.Counter = collections.Counter()
        turns: dict[str, dict[str, str]] = {}
        for n in want:
            for cid, tid in index.get(n) or []:
                votes[cid] += 1
                turns.setdefault(cid, {}).setdefault(n, tid)
        if votes:
            cid, n = votes.most_common(1)[0]
            if n >= min(3, len(want)):
                got = {"conversation_id": cid, "turns": dict(turns.get(cid) or {})}
    _RERUN_S3[key] = got
    while len(_RERUN_S3) > 200:
        _RERUN_S3.pop(next(iter(_RERUN_S3)))
    return got


def rerun_replay_s3(row: Any) -> dict[str, Any] | None:
    """A finished call going out again: the roulette's word (bank.reair) and the
    stamp its rows carry - the round it replays, and the replay. None when the
    roulette keeps it off; {} when no System 3 round is behind it."""
    road = "caller"
    if time.time() - float(_BANK_REAIR_MISS.get("rerun") or 0) < BANK_REAIR_MISS_REST:
        return None
    t0 = time.time()
    if not s3_chance("bank.reair", BANK_REAIR_ODDS, BANK_REAIR_LABEL):
        _BANK_REAIR_MISS["rerun"] = time.time()
        pipeline_log("call", "the roulette kept a call re-air off (bank.reair)")
        return None
    src = rerun_s3_source(row) if isinstance(row, dict) else {}
    cid = str(src.get("conversation_id") or "")
    chance = _s3_roll_on("bank.reair", cid, "",
                         "a finished call goes out again: rolled {dice} under {odds}% - {hit}", since=t0)
    if not cid:
        return {}
    try:
        uses = int((_rerun_ledger_rows().get(str(row.get("id") or "")) or {}).get("uses") or 0)
    except Exception:  # noqa: BLE001
        uses = 0
    first = float(row.get("ts") or 0)
    replay = {"at": time.time(), "road": road, "airing": uses + 2,
              "label": "replay, first aired %s, airing %d" % (_bank_clock(first), uses + 2),
              "first_aired": first or None, "decided_by": "a call re-air (the pick: call.rerun_take)",
              **({"chance": chance} if chance else {})}
    return {"conversation_id": cid, "mode": "active", "turns": dict(src.get("turns") or {}),
            "replay": replay}


def rerun_row_s3(base: Any, row: Any) -> dict[str, Any]:
    """One re-aired call line's node: the round it replays, its turn by words."""
    if not isinstance(base, dict) or not base.get("conversation_id"):
        return {}
    return {"conversation_id": str(base["conversation_id"]), "mode": "active",
            "turn_id": str((base.get("turns") or {}).get(_rerun_norm((row or {}).get("text"))) or ""),
            "replay": dict(base.get("replay") or {})}


async def continuity_roulette(voices: Any, said_at: Any) -> tuple[list[Any], int, dict[str, Any] | None]:
    """The emergency host's recorded pairs under System 3's dice: every one has
    aired before, so a pair goes out again only on the roulette (bank.reair),
    and which rested pair is a LINE draw on a node of its own, which also takes
    the chance roll in as its STATION event. (picks, resting, stamp)."""
    rested: list[tuple[int, list[Any], Any]] = []
    resting = 0
    now = time.time()
    for number, pair in enumerate(CONTINUITY_PAIRS):
        if any(now - float((said_at or {}).get(text) or 0) < CONTINUITY_REST_SECONDS for text in pair):
            resting += 1
            continue
        picks = [continuity_pick(who, str((voices or {}).get(who) or ""), text)
                 for who, text in zip(("dj", "cohost"), pair)]
        if all(picks):
            rested.append((number, picks, pair))
    if not rested:
        return [], resting, None
    if time.time() - float(_BANK_REAIR_MISS.get("continuity") or 0) < BANK_REAIR_MISS_REST:
        return [], resting, None
    t0 = time.time()
    if not s3_chance("bank.reair", BANK_REAIR_ODDS, BANK_REAIR_LABEL):
        _BANK_REAIR_MISS["continuity"] = time.time()
        pipeline_log("air", "the roulette kept the emergency host's recorded pairs off (bank.reair)")
        return [], resting, None
    chance = _s3_roll_on("bank.reair", "", "", "", since=t0)
    direct = globals().get("system3_direct_line")
    handle = None
    if direct:
        try:
            handle = await direct(road="interject", who="dj", dj=dj_settings(),
                                  context="the emergency host's continuity - a recorded pair goes out again",
                                  candidates=[" / ".join(p) for _n, _p, p in rested],
                                  candidates_from="the emergency host's recorded pairs (the rested ones)",
                                  bank=True)
        except Exception as exc:  # noqa: BLE001
            pipeline_log("system3", "the emergency host's pair was withheld after its draw failed",
                         extra=("%s: %s" % (type(exc).__name__, exc))[:200])
            handle = None
    if handle is None or not handle.active or handle.choice is None or not 0 <= handle.choice < len(rested):
        return [], resting, None
    number, picks, pair = rested[handle.choice]
    bind = globals().get("system3_bind_line")
    if bind:
        try:
            bind(handle, " / ".join(pair))
        except Exception:  # noqa: BLE001
            pass
    _CONTINUITY_STATE["next_pair"] = number + 1
    last = max(float((said_at or {}).get(text) or 0) for text in pair)
    replay = {"at": time.time(), "road": "continuity",
              "label": ("replay, the emergency host's recorded pair, last aired %s" % _bank_clock(last)
                        if last else "replay, the emergency host's recorded pair"),
              "last_aired": last or None, "decided_by": "the emergency host's reserve",
              **({"chance": chance} if chance else {}),
              "pick": {"kind": "line", "index": handle.choice + 1, "of": len(rested)}}
    return picks, resting, dict(handle.stamp, replay=replay)


# --- [#1386] GOLD IS A RESERVE, NOT PROGRAMMING --------------------------
''', 1),
    ('shelf-take-signature',
     r'''def shelf_take(kind: str, voice: str = "",
               fresh_only: bool = False, *, peek: bool = False,
               predicate: Any = None) -> dict[str, Any] | None:
''',
     r'''def shelf_take(kind: str, voice: str = "",
               fresh_only: bool = False, *, peek: bool = False,
               predicate: Any = None,
               reair_out: list[Any] | None = None,            # [s3-banks-roll]
               _reair_grant: Any = None) -> dict[str, Any] | None:
''', 1),
    ('shelf-take-collect-open',
     r'''        _order = airings_ghost_last(str(kind), _order)
        for row in _order:
''',
     r'''        _order = airings_ghost_last(str(kind), _order)
        # [s3-banks-roll] A ROUND THAT HAS AIRED BEFORE IS NOT TAKEN ON THE WALK.
        # While System 3's dice are live every rested replay the walk passes is
        # set aside instead, so a first airing anywhere on the shelf always goes
        # first; only when none stood ready does the roulette decide, after the
        # walk, whether one goes out again and which (bank_reair_pick).
        _reair: list[dict[str, Any]] | None = (
            [] if (reair_out is not None or _s3_dice_live()) else None)
        for row in _order:
''', 1),
    ('shelf-take-collect',
     r'''            if peek:
                return row
''',
     r'''            if _out_at and bank_reair_refusal(str(kind), row):
                _why.append("retired by the re-air gate")   # [s3-banks-roll] never goes out again
                continue
            if _reair is not None and _out_at and row is not _reair_grant:
                _reair.append(row)          # [s3-banks-roll] a replay waits for the roulette
                continue
            if peek:
                return row
''', 1),
    ('shelf-take-roulette',
     r'''        if peek:
            return None
''',
     r'''        # [s3-banks-roll] nothing heard for the first time stood ready: a replay,
        # if the roulette brings one up. A peek names the first without rolling
        # (its question is whether the door could); a take rolls, then walks
        # again for the row it landed on - granted, so every test still holds.
        if _reair and _reair_grant is None:
            if reair_out is not None:
                reair_out.extend(_reair)
            if peek:
                return _reair[0]
            _again, _replay = bank_reair_pick(str(kind), _reair, "the %s shelf"
                                              % SHELF_LABEL.get(str(kind), str(kind)))
            if _again is not None:
                _got = shelf_take(kind, voice, fresh_only, predicate=predicate,
                                  _reair_grant=_again)
                if _got is not None:
                    bank_replay_attach(_got, _replay)
                    return _got
            _why.append("the roulette kept the replay off")
        if peek:
            return None
''', 1),
    ('ready-row-signature',
     r'''def _ready_shelf_row(kind: str, rescue: bool = False,
                     pick: dict[str, Any] | None = None
                     ) -> dict[str, Any] | None:
''',
     r'''def _ready_shelf_row(kind: str, rescue: bool = False,
                     pick: dict[str, Any] | None = None,
                     reair_out: list[Any] | None = None   # [s3-banks-roll]
                     ) -> dict[str, Any] | None:
''', 1),
    ('ready-row-collect',
     r'''    # #1260: a named row answers for itself. It is still checked against
''',
     r'''    # [s3-banks-roll] every replay this door could air (the re-air gate's
    # rejects struck out), for the roulette to choose among - the plot
    # preference below is a first airing's question - and back, the first
    # airing it could air instead (None when none stood ready)
    if reair_out is not None:
        shelf_take(kind, peek=True, reair_out=reair_out,
                   predicate=lambda r: bool(eligible(r) and float(r.get("aired_at") or 0)))
        _first = shelf_take(kind, peek=True, predicate=eligible)
        return _first if (_first is not None and not float(_first.get("aired_at") or 0)) else None
    # #1260: a named row answers for itself. It is still checked against
''', 1),
    ('ready-air-signature',
     r'''                           force: bool = False,
                           on_handoff: Any = None) -> list[str]:
''',
     r'''                           force: bool = False,
                           on_handoff: Any = None,
                           named: bool = False) -> list[str]:    # [s3-banks-roll] the operator's Play now
''', 1),
    ('ready-air-gate',
     r'''    row = _ready_shelf_row(kind, rescue, pick)      # #1168/#1260
    if row is None:
        return _shelf_no(kind, "the shelf would not give up the row that "
                               "was picked")                      # #1304
''',
     r'''    row = _ready_shelf_row(kind, rescue, pick)      # #1168/#1260
    if row is None:
        return _shelf_no(kind, "the shelf would not give up the row that "
                               "was picked")                      # #1304
    # [s3-banks-roll] A ROUND THAT HAS AIRED BEFORE GOES OUT AGAIN ONLY ON THE
    # ROULETTE - and never once the re-air gate has retired it. Every road
    # that reaches the cupboard through this door - the dead-air rescue, the
    # torrent's floor, a road asking before it writes, the memo breaking in -
    # rolls bank.reair here, and bank.reair_pick among every rested replay the
    # door could air; refused, the first airing the plot preference passed
    # over goes instead, when one stood ready. A round another road named
    # rolls on its own. The operator's Play now (`named`) is his decision:
    # never rolled, stamped as a replay - but refused if the gate retired it.
    _s3_replay_now = None
    if not row_unaired(row):
        if named:
            _gate_why = bank_reair_refusal(kind, row)
            if _gate_why:
                return _shelf_no(kind, "the re-air gate retired this round - " + _gate_why)
            _s3_replay_now = bank_replay_stamp(kind, row, None, None,
                                               "the operator named this round (Play now)")
        elif pick is not None:
            row, _s3_replay_now = bank_reair_pick(
                kind, [row], "a round named at the %s cupboard" % SHELF_LABEL.get(kind, kind))
            if row is None:
                return _shelf_no(kind, "a replay goes out again only on the roulette - the "
                                       "re-air gate or bank.reair kept this one off")
        elif _s3_dice_live():
            _again_rows: list[Any] = []
            _first_airing = _ready_shelf_row(kind, rescue, None, reair_out=_again_rows)
            _again, _s3_replay_now = bank_reair_pick(
                kind, _again_rows or [row],
                "the %s cupboard" % SHELF_LABEL.get(kind, kind))
            if _again is not None:
                row = _again
            elif _first_airing is not None:
                row = _first_airing     # heard for the first time: the bank's job, no roll
            else:
                return _shelf_no(kind, "the roulette did not bring a replay up (bank.reair) "
                                       "and nothing heard for the first time was ready")
''', 1),
    ('ready-air-entry',
     r'''        entry["_ready_free"] = bool(free)
''',
     r'''        entry["_ready_free"] = bool(free)
        if _s3_replay_now:
            entry["_s3_replay"] = _s3_replay_now    # [s3-banks-roll] rides its ledger rows
''', 1),
    ('orch-play-named',
     r'''            said = await _ready_shelf_air(
                kind, _RADIO.get("now"), rescue=True, pick=row,
                force=talk_quiet_for() >= SILENCE_LOSES_AFTER)
''',
     r'''            said = await _ready_shelf_air(
                kind, _RADIO.get("now"), rescue=True, pick=row,
                force=talk_quiet_for() >= SILENCE_LOSES_AFTER,
                named=True)             # [s3-banks-roll] the operator named it (Play now)
''', 1),
    ('cupboard-play-named',
     r'''            said = await _ready_shelf_air(kind, _RADIO.get("now"),
                                          rescue=True, pick=row)
''',
     r'''            said = await _ready_shelf_air(kind, _RADIO.get("now"),
                                          rescue=True, pick=row,
                                          named=True)   # [s3-banks-roll] the operator named it (Play now)
''', 1),
    ('larder-serve-gate',
     r'''        entry = _LARDER[_take_at]
        if repeat_safe("banter", entry):
''',
     r'''        entry = _LARDER[_take_at]
        # [s3-banks-roll] a first airing stands; a banked round that has aired
        # before goes out again only on the roulette (larder_reair_gate). A
        # refused replay leaves the larder as it was and the road writes fresh.
        _take_at, _larder_replay = larder_reair_gate(_take_at)
        entry = _LARDER[_take_at] if _take_at >= 0 else None
        if isinstance(entry, dict):
            if _larder_replay:
                entry["_s3_replay"] = _larder_replay
            else:
                entry.pop("_s3_replay", None)
        if entry is None:
            pass
        elif repeat_safe("banter", entry):
''', 1),
    ('larder-serve-air',
     r'''        if ((time.time() - float(entry["at"]) < larder_fresh()
''',
     r'''        if (entry is not None and (time.time() - float(entry["at"]) < larder_fresh()   # [s3-banks-roll]
''', 1),
    ('gold-note-signature',
     r'''def gold_note(who: str, text: str, path: str, seconds: float) -> bool:
    """A rhymed line that just aired with its take - kept as gold."""
''',
     r'''def gold_note(who: str, text: str, path: str, seconds: float,
              source: dict[str, Any] | None = None) -> bool:
    """A rhymed line that just aired with its take - kept as gold.

    [s3-banks-roll] `source` is the System 3 turn it was minted from
    ({conversation_id, turn_id}); only such a bar fires while System 3 owns
    the station's dialogue, and it airs stamped with that turn."""
''', 1),
    ('gold-note-update',
     r'''                row.update({"path": name, "seconds": float(seconds or 0), "who": who,
                            "at": time.time()})
''',
     r'''                row.update({"path": name, "seconds": float(seconds or 0), "who": who,
                            "at": time.time()})
                if gold_source({"source": source}):                  # [s3-banks-roll]
                    row["source"] = gold_source({"source": source})
''', 1),
    ('gold-note-new',
     r'''        rows.append({"key": key, "who": str(who or "dj"), "text": text[:400], "path": name,
                     "seconds": float(seconds or 0), "at": time.time(), "fired": 0,
                     "last": 0.0})
''',
     r'''        rows.append({"key": key, "who": str(who or "dj"), "text": text[:400], "path": name,
                     "seconds": float(seconds or 0), "at": time.time(), "fired": 0,
                     "last": 0.0,
                     **({"source": gold_source({"source": source})}     # [s3-banks-roll]
                        if gold_source({"source": source}) else {})})
''', 1),
    ('gold-harvest-source',
     r'''            if gold_note(who, text, path, seconds):
''',
     r'''            if gold_note(who, text, path, seconds,
                         source=bank_line_stamp(entry, text, who)):   # [s3-banks-roll]
''', 1),
    ('gold-air-mint-source',
     r'''                            gold_note(item["who"], str(item.get("turn_text") or item["chunk"]),
                                      str(clip.get("path") or key), await _clip_seconds_async(clip["path"]))
''',
     r'''                            gold_note(item["who"], str(item.get("turn_text") or item["chunk"]),
                                      str(clip.get("path") or key), await _clip_seconds_async(clip["path"]),
                                      source=bank_line_stamp(                    # [s3-banks-roll]
                                          ready_meta, str(item.get("turn_text") or item["chunk"]),
                                          item["who"]))
''', 1),
    ('gold-pick-eligible',
     r'''        while pool:
            least = min(int(r.get("fired") or 0) for r in pool)
''',
     r'''        # [s3-banks-roll] ONLY BARS MINTED FROM SYSTEM 3 TURNS: while System 3
        # owns the dialogue a bar with no turn behind it is stock made outside
        # the roulette, and it stays in the bank (gold_source)
        if _s3_active():
            pool = [r for r in pool if gold_source(r)]
        while pool:
            least = min(int(r.get("fired") or 0) for r in pool)
''', 1),
    ('gold-pick-order',
     r'''            tier = [r for r in pool if int(r.get("fired") or 0) == least]
''',
     r'''            tier = [r for r in pool if int(r.get("fired") or 0) == least]
            # [s3-banks-roll] THE WHOLE ORDER IS THE DICE DOOR'S. The first bar
            # was System 3's and the rest a bare shuffle; now each next bar is
            # one more roll among the ones left, made only when the bar before
            # it lost its take (one file checked per roll, #1412). The shuffle
            # below is the station's own order with System 3's dice off.
            if _s3_dice_live():
                _bar = gold_tier_pick(tier)
                if _bar is not None:
                    return _bar
                pool = [r for r in pool if int(r.get("fired") or 0) != least]
                continue
''', 1),
    ('gold-run-roll',
     r'''    while bars < GOLD_RUN_MOST and sold() < want:
''',
     r'''    # [s3-banks-roll] GOLD IS A ROULETTE FOR THE RUN. The run goes only when
    # the desk's row says so (gold.run) - rolled once per run and only when a
    # bar could go (an empty bank rolls nothing); a refused run rests this
    # road GOLD_RUN_MISS_REST and leaves the gap to the next rung. Every bar
    # airs stamped with the System 3 turn it was minted from (gold_air_stamp).
    _t_run = time.time()
    if _s3_dice_live() and sold() < want:
        if (time.time() - float(_BANK_REAIR_MISS.get("gold") or 0) < GOLD_RUN_MISS_REST
                or not gold_run_ready(min_rest=GOLD_GAP_REST)):
            return ""
        if not s3_chance("gold.run", GOLD_RUN_ODDS,
                         "a run of banked gold bars fills the gap (otherwise the next rung does)"):
            _BANK_REAIR_MISS["gold"] = time.time()
            pipeline_log("air", "the roulette kept the gold bank off the air (gold.run) - "
                         + (why or "dead air"))
            return ""
    while bars < GOLD_RUN_MOST and sold() < want:
''', 1),
    ('gold-run-pick-clock',
     r'''        try:
            bar = gold_pick(exclude_who=last_who, min_rest=GOLD_GAP_REST)
''',
     r'''        _t_pick = time.time()                                   # [s3-banks-roll]
        try:
            bar = gold_pick(exclude_who=last_who, min_rest=GOLD_GAP_REST)
''', 1),
    ('gold-run-bar-node',
     r'''                              round_as="gold")
''',
     r'''                              round_as="gold",
                              # [s3-banks-roll] the bar is its source turn's node on the air
                              system3=(gold_air_stamp(bar, "" if bars else "gold.run",
                                                      _t_run, _t_pick)
                                       if _s3_dice_live() else None))
''', 1),
    ('gold-in-round-node',
     r'''                            line_ids.append(uuid.uuid4().hex)           # #1277
                            gold_fired(_gold)
''',
     r'''                            line_ids.append(uuid.uuid4().hex)           # #1277
                            _s3_air_own(line_ids[-1], gold_air_stamp(   # [s3-banks-roll]
                                _gold, "gold.in_round"))
                            gold_fired(_gold)
''', 1),
    ('round-rows-stamps',
     r'''                    _pl_block = await asyncio.to_thread(
                        script_ledger_commit,
''',
     r'''                    _s3_air_rows(_script_rows, ready_meta)          # [s3-banks-roll]
                    _pl_block = await asyncio.to_thread(
                        script_ledger_commit,
''', 1),
    ('listening-seam',
     r'''        playlist = add_listening_responses(
            playlist, voices,
            lambda who, context, used: _RESPONSES.take(
                voices.get(who, ""), voice_engine_for(voices.get(who, "")),
                context, used, crystal=continuity_crystal()), away=seat_away_who())
''',
     r'''        playlist = add_listening_responses(
            playlist, voices,
            # [s3-banks-roll] each seam rolls on the round's node (listen.seam),
            # the response is a roll among the eligible ones (listen.pick), and
            # it is stamped to the turn it answers. System 3's dice off: as before.
            lambda who, context, used: listening_seam_take(
                who, context, used, voices, ready_meta), away=seat_away_who())
''', 1),
    ('reel-s3-only',
     r'''                if not row_unaired(entry):
                    continue
                picked = entry
''',
     r'''                if not row_unaired(entry):
                    continue
                # [s3-banks-roll] the reel is cut from System 3's banked rounds:
                # a round no node scripted is stock made outside the roulette
                if _s3_active() and not bank_s3_of(entry):
                    continue
                # ...and never one the re-air gate retired: welded, it would
                # pass by the copy gate at the turn
                if bank_reair_refusal("banter", entry):
                    continue
                picked = entry
''', 1),
    ('reel-row-node',
     r'''                             "until": round(offset + real, 2)})
                offset += real
''',
     r'''                             "until": round(offset + real, 2)})
                _reel_s3 = bank_line_stamp(picked, ln["text"], ln["who"])   # [s3-banks-roll]
                if _reel_s3:
                    rows[-1]["system3"] = _reel_s3
                offset += real
''', 1),
    ('reel-open-node',
     r'''                    "round": "banter", "replay": True,       # #1023 (G1)
''',
     r'''                    "round": "banter", "replay": True,       # #1023 (G1)
                    # [s3-banks-roll] the node each reel line was scripted as
                    **({"system3": dict(r["system3"])}
                       if isinstance(r.get("system3"), dict) else {}),
''', 1),
    ('continuity-roulette',
     r'''    for step in range(len(CONTINUITY_PAIRS)):
''',
     r'''    # [s3-banks-roll] the emergency host's recorded pairs have all aired before:
    # under System 3's dice a pair goes out again only on the roulette
    # (bank.reair), and which rested pair is a LINE draw on a node of its own
    # (continuity_roulette) - never the rotation below.
    _cont_rolled = _s3_dice_live()
    _cont_s3 = None
    if _cont_rolled:
        chosen, resting, _cont_s3 = await continuity_roulette(voices, said_at)
    for step in (range(len(CONTINUITY_PAIRS)) if not _cont_rolled else ()):
''', 1),
    ('continuity-rows-node',
     r'''        _RADIO.setdefault("chat", []).extend(rows)
        del _RADIO["chat"][:-RADIO_CHAT_KEEP]
        _CONTINUITY_STATE.update(last_air=time.time(), why=reason or "Emergency host continuity")
''',
     r'''        if _cont_s3:                        # [s3-banks-roll] the pair's node, and the replay
            for _cont_row in rows:
                if _cont_row.get("who") in ("dj", "cohost"):
                    _cont_row["system3"] = dict(_cont_s3)
        _RADIO.setdefault("chat", []).extend(rows)
        del _RADIO["chat"][:-RADIO_CHAT_KEEP]
        _CONTINUITY_STATE.update(last_air=time.time(), why=reason or "Emergency host continuity")
''', 1),
    ('rerun-s3-eligible',
     r'''            if _hold_rerun and not _rerun_rhymes(r):
                continue                # a plain take may not re-air (#1064)
''',
     r'''            if _hold_rerun and not _rerun_rhymes(r):
                continue                # a plain take may not re-air (#1064)
            if _s3_active() and not rerun_s3_source(r):
                continue                # [s3-banks-roll] a replay names the System 3 round it replays
            if bank_reair_refusal("caller", r, str((rerun_s3_source(r) if _s3_active() else {})
                                                  .get("conversation_id") or "")):
                continue                # [s3-banks-roll] the re-air gate retired this call
''', 1),
    ('rerun-roulette',
     r'''        pick = await asyncio.to_thread(_call_rerun_pick_blocking, low, high)
        if not pick:
            return []
''',
     r'''        pick = await asyncio.to_thread(_call_rerun_pick_blocking, low, high)
        if not pick:
            return []
        # [s3-banks-roll] a call that already aired goes out again only on the
        # roulette (bank.reair); the pick among the rested calls was the pick
        # thread's roll (call.rerun_take). Its rows carry the round it replays.
        _rerun_s3 = None
        if _s3_dice_live():
            _rerun_s3 = rerun_replay_s3(dict(pick.get("row") or {}))
            if _rerun_s3 is None:
                return []
''', 1),
    ('rerun-rows-node',
     r'''                        "source": "rerun",
''',
     r'''                        "source": "rerun",
                        **({"system3": rerun_row_s3(_rerun_s3, r)}      # [s3-banks-roll]
                           if _rerun_s3 else {}),
''', 1),
    ('s3js-vbump',
     r'''    const module = await import("/system3/system3.js?v=6");
''',
     r'''    const module = await import("/system3/system3.js?v=7");   // [s3-banks-roll] replay / gold / listening chips on the turn
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

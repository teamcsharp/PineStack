#!/usr/bin/env python3
"""[no-repeat-24h] Nothing airs twice inside a day; the gap is a rolled record, then rolled SFX.

The operator, 2026-09-29: no dialogue line (any seat, a banked turn re-aired
under a NEW id included), SFX clip or music record airs twice inside 24 hours.
A banked round may still air its first time; its lines just cannot replay.
When nothing new is ready: a ROLLED record first, then ROLLED SFX - never a
re-aired line.

Needs air_norepeat.py beside app.py (the book: data/norepeat_book.json, the
refusals: data/norepeat_refusals.jsonl, GET /api/norepeat).

    python3 tools/norepeat_24h_patch.py --check     0 ready / 2 applied / 1 anchor missing
    python3 tools/norepeat_24h_patch.py --apply

What each edit does (app.py):
  helpers        the book, the gates, the refusal record, the gap's record roll, GET /api/norepeat
  airlog         every published spoken line is noted (its words and each sentence)
  turns          speak_turns: THE LAST GATE for rounds - every seat, replays and recorded takes too
  dj_speak       _dj_speak_floorless: the last gate for single lines (not chunks speak_turns gated)
  reair          bank_reair_refusal (wrapped after system3_banks_roll's block): a banked round
                 heard inside the day is struck BEFORE any roll
                 (the larder serve, every shelf take, the cupboard door, call re-airs, the reserve)
  gold-pick      gold_pick: a bar heard inside the day is not a candidate
  rotation/solo  dj_next_track / radio_next_track: a record heard inside the day is skipped
  played         remember_played notes the record
  sfx-hist/video sfx_history_add / sfx_video_note_played note the clip; sfx_video_on_cooldown asks
  cadence        _sfx_cadence_pick strikes 24 h clips before its two rolls
  book-roll      sfx_db_pick_short_video (wrapped after system3_sfx_roll's block): a heard clip is
                 refused and both rolls are made again (at most six times)
  gap-record     sfx_fill_gap: with no record turning and the floor free, a ROLLED record first
  gold-gap       gold_fill_gap stands down (gold is a re-air; it airs now only as a rolled reply)
  continuity     continuity_air: the reserve's recorded pairs are not re-aired; the gap filler answers
  cover-held     cover_the_gap under a held floor: rolled clips, not a gold run
                 (the gap's record roll goes to the origin ledger as gap:<track>:<t> and rides the
                 queue row as s3_gap)
  sting          dj_sting: THE LAST GATE for a clip (every road but the operator's button)
  produced-ad    _air_produced_ad_floorless: a produced spot's words heard inside the day do not re-air
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p3_patchlib import Edit, run  # noqa: E402

A = "app.py"

HELPERS_ANCHOR = "# --- [s3-sfx-roll] THE BOARD'S CLIP IS TWO OF SYSTEM 3'S ROLLS ----------------\n"
HELPERS = '''# --- [no-repeat-24h] NOTHING AIRS TWICE INSIDE A DAY ------------------------------
# "No repeats within 24 hours" of dialogue lines (any seat, a banked turn
# re-aired under a NEW id included), SFX clips and music records; "when nothing
# new is ready, a ROLLED music record first, then ROLLED SFX ... never a
# re-aired line" (operator, 2026-09-29). air_norepeat.Book is the one memory,
# keyed by fingerprint: a line's normalised words and each of its sentences, a
# clip's id, a track's id - a new id cannot escape it. The selectors ask it
# BEFORE they roll, so a refusal at the last gate is rare; the last gate before
# air asks again; every refusal is recorded - why, which road, which stage -
# in data/norepeat_refusals.jsonl and GET /api/norepeat. NOREPEAT_HOURS=0
# switches the rule off; NOREPEAT_EXEMPT_KINDS (comma list) names spoken kinds
# the operator exempts (none by default).
import air_norepeat as _air_norepeat                                  # [no-repeat-24h:helpers]

NOREPEAT_HOURS = float(os.getenv("NOREPEAT_HOURS", "24"))
NOREPEAT_EXEMPT_KINDS = frozenset(k.strip() for k in os.getenv("NOREPEAT_EXEMPT_KINDS", "").split(",") if k.strip())
NOREPEAT_QUIET_KINDS = frozenset({"marker", "chat", "image_analysis", "song_analysis", "hangup", "sfx"})
NOREPEAT_SOUNDED = ("stream", "box", "both", "page")    # publication is not playback
GAP_RECORD_SHORTLIST = int(os.getenv("GAP_RECORD_SHORTLIST", "8"))
_NOREPEAT_SAID: dict[str, float] = {}
_GAP_RECORD_ROLL: dict[str, dict[str, Any]] = {}


def _norepeat_seed():
    """The book's first memory, when it has no file: what the ledgers say
    went out inside the window (the air log, the spins, the clip history)."""
    since = time.time() - max(1.0, NOREPEAT_HOURS * 3600.0)
    return _air_norepeat.seed_rows(globals().get("AIR_LOG_PATH"), globals().get("MUSIC_LOG_PATH"),
                                   globals().get("SFX_HISTORY_ARCHIVE_PATH"), since,
                                   register_db=data_path("system3.sqlite3"))


NOREPEAT = _air_norepeat.Book(data_path("norepeat_book.json"), data_path("norepeat_refusals.jsonl"),
                              window=max(1.0, NOREPEAT_HOURS * 3600.0), seed=_norepeat_seed)


def norepeat_on() -> bool:
    return NOREPEAT_HOURS > 0


def _norepeat_save_soon() -> None:
    try:
        if not NOREPEAT.save_due():
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            NOREPEAT.save()
            return
        fire_and_forget(asyncio.to_thread(NOREPEAT.save))
    except Exception:  # noqa: BLE001 - a book that will not write is still a memory
        pass


def norepeat_note_line(text: Any, road: str = "", ref: str = "", at: Any = None) -> None:
    if not norepeat_on():
        return
    try:
        NOREPEAT.note_text(text, road, ref, float(at) if at else None)
        _norepeat_save_soon()
    except Exception:  # noqa: BLE001
        pass


def norepeat_note_sfx(ident: Any, road: str = "", ref: str = "") -> None:
    if not norepeat_on() or not ident:
        return
    try:
        NOREPEAT.note("sfx", _air_norepeat.sfx_key(ident), road, ref)
        _norepeat_save_soon()
    except Exception:  # noqa: BLE001
        pass


def norepeat_note_record(track_id: Any, road: str = "", ref: str = "") -> None:
    if not norepeat_on() or not track_id:
        return
    try:
        NOREPEAT.note("record", _air_norepeat.record_key(track_id), road, ref)
        _norepeat_save_soon()
    except Exception:  # noqa: BLE001
        pass


def norepeat_text_used(text: Any) -> bool:
    try:
        return bool(norepeat_on() and NOREPEAT.used_text(text))
    except Exception:  # noqa: BLE001
        return False


def norepeat_sfx_used(ident: Any) -> bool:
    try:
        return bool(norepeat_on() and ident and NOREPEAT.used("sfx", _air_norepeat.sfx_key(ident)))
    except Exception:  # noqa: BLE001
        return False


def norepeat_record_used(track_id: Any) -> bool:
    try:
        return bool(norepeat_on() and track_id and NOREPEAT.used("record", _air_norepeat.record_key(track_id)))
    except Exception:  # noqa: BLE001
        return False


def norepeat_refuse(kind: str, key: str, road: str, text: Any = "", why: str = "",
                    stage: str = "air", ref: str = "", say: bool = True) -> dict[str, Any]:
    """A refusal, recorded (the ring, the ledger) and said in the pipeline log."""
    try:
        row = NOREPEAT.refuse(kind, key, road, why, text, ref, stage)
    except Exception:  # noqa: BLE001
        row = {"why": why or "heard inside the day"}
    if say:
        pipeline_log("air", ("no repeats inside a day - a %s refused on the %s road (%s): %s"
                             % (kind, road or "?", stage, row.get("why") or ""))[:220],
                     extra=" ".join(str(text or ref or key).split())[:160])
    return row


def norepeat_select_refuse(kind: str, key: str, road: str, text: Any = "", ref: str = "") -> None:
    """A selector struck a candidate BEFORE it rolled: recorded once an hour
    per candidate and road, so a scan does not flood the ring."""
    k = "%s|%s|%s" % (kind, key or ref, road)
    now = time.time()
    if now - float(_NOREPEAT_SAID.get(k) or 0) < 3600:
        return
    _NOREPEAT_SAID[k] = now
    while len(_NOREPEAT_SAID) > 4000:
        _NOREPEAT_SAID.pop(next(iter(_NOREPEAT_SAID)))
    norepeat_refuse(kind, key, road, text=text, ref=ref, stage="select", say=False)


def _norepeat_road(who: str = "", kind: str = "") -> str:
    try:
        return str(airlog_round_now(who, kind) or kind or "round")
    except Exception:  # noqa: BLE001
        return str(kind or "round")


def norepeat_line_gate(text: Any, who: str = "", kind: str = "", road: str = "",
                       by_hand: bool = False) -> str:
    """THE LAST GATE BEFORE AIR for a spoken line: "" when it may air, else
    why it may not (recorded). Only a line the operator typed is exempt, and a
    kind the operator named in NOREPEAT_EXEMPT_KINDS."""
    if not norepeat_on() or by_hand or not str(text or "").strip():
        return ""
    if str(kind or "") in NOREPEAT_EXEMPT_KINDS:
        return ""
    try:
        seen = NOREPEAT.text_seen(text)
    except Exception:  # noqa: BLE001
        return ""
    if not seen:
        return ""
    return str(norepeat_refuse("line", str(seen.get("key") or ""), road or kind or who,
                               text=text).get("why") or "heard inside the day")


def _norepeat_row_texts(row: Any) -> list[str]:
    """The spoken lines of a banked round (its script's turns), else its text."""
    out: list[str] = []
    try:
        entry = row.get("entry") if isinstance(row.get("entry"), dict) else row
        script = str(entry.get("script") or row.get("script") or "")
        for ln in script.splitlines():
            m = re.match(r"^\\s*[A-Za-z][A-Za-z0-9 ._'-]{0,39}?\\s*:\\s+(.*\\S)\\s*$", ln)
            if m:
                out.append(m.group(1))
        if not out and (row.get("text") or entry.get("text")):
            out.append(str(row.get("text") or entry.get("text")))
    except Exception:  # noqa: BLE001
        pass
    return out


def norepeat_round_refusal(road: str, row: Any) -> str:
    """[bank_reair_refusal's 24-hour leg] A banked round that went out inside
    the day, or half of whose lines did, is not a candidate - struck before any
    roll is made, on every replay road."""
    if not norepeat_on() or not isinstance(row, dict):
        return ""
    try:
        entry = row.get("entry") if isinstance(row.get("entry"), dict) else {}
        last = max(float(row.get("aired_at") or 0), float(entry.get("aired_at") or 0),
                   float(row.get("heard_at") or 0), float(row.get("last") or 0))
        texts = _norepeat_row_texts(row)
        why = ""
        if last and time.time() - last < NOREPEAT.window:
            why = "it went out %d min ago - no repeats inside a day" % int((time.time() - last) / 60)
        else:
            keyed = [t for t in texts if _air_norepeat.line_key(t, NOREPEAT.min_words)]
            heard = [t for t in keyed if NOREPEAT.used_text(t)]
            if keyed and len(heard) * 2 >= len(keyed):
                why = "%d of its %d lines were on air inside the day" % (len(heard), len(keyed))
        if why:
            norepeat_select_refuse("line", _air_norepeat.line_key((texts or [""])[0], 1), str(road or "bank"),
                                   text=(texts or [""])[0], ref=str(row.get("sid") or row.get("id") or ""))
        return why
    except Exception:  # noqa: BLE001
        return ""


def norepeat_fresh_clips(paths: Any, road: str) -> list[Any]:
    """The clips not heard inside the day - asked before a pick rolls. A pool
    with nothing fresh is empty: the road's next option answers, never a repeat."""
    paths = list(paths or [])
    if not norepeat_on() or not paths:
        return paths
    out = []
    for p in paths:
        try:
            sid = sfx_id(Path(str(p)))
        except Exception:  # noqa: BLE001
            sid = ""
        if sid and NOREPEAT.used("sfx", sid):
            norepeat_select_refuse("sfx", sid, road, ref=Path(str(p)).name)
            continue
        out.append(p)
    return out


def norepeat_roll_clip(paths: Any, key: str, question: str, road: str = "gap") -> Path | None:
    """A gap clip: the day's heard clips struck first, then System 3 rolls
    among the rest (`key` on the desk; through the sting ring, so a clip does
    not come straight back either), and the roll rides the clip to its row
    (_sfx_roll_note -> the sting's _sfx_roll_carry -> the origin ledger)."""
    fresh = norepeat_fresh_clips(paths, road)
    if not fresh:
        return None
    name = unrepeated([str(p) for p in fresh], "sting", keep=sting_keep(len(fresh)),
                      director=_S3ClipDice(key, question))
    if not name:
        return None
    path = Path(name)
    try:
        _sfx_roll_note(path, road, {"label": path.parent.name}, _s3_sfx_rolled(key, path.stem), 1)
    except Exception:  # noqa: BLE001
        pass
    return path


def norepeat_record_take(queue: Any, start: int = 0, owned_skip: bool = False,
                         road: str = "rotation") -> int:
    """The first place at or after `start` whose record was not heard inside
    the day (and, with `owned_skip`, owns no banked talk), or -1."""
    q = list(queue or [])
    for i in range(max(0, int(start)), len(q)):
        row = q[i] if isinstance(q[i], dict) else {}
        tid = str(row.get("id") or "")
        if owned_skip and tid in _TRACK_TALK:
            continue
        if tid and norepeat_record_used(tid):
            norepeat_select_refuse("record", tid, road, text=str(row.get("title") or ""))
            continue
        return i
    return -1


def norepeat_gap_record(why: str = "") -> dict[str, Any] | None:
    """THE GAP'S FIRST ANSWER: a record, ROLLED. System 3 picks among the next
    fresh records of the rotation (gap.record: never one heard inside the day,
    never one that owns banked talk), the pick goes to the head of the queue
    and the needle drops - the road the dead-air watch's needle drop already
    takes. The roll rides the spin (s3_spin.gap -> the music log -> rec: in
    why_line). None when no record can answer (music off, paused, nothing fresh)."""
    try:
        if not (_RADIO.get("on") and _RADIO.get("station")) or radio_paused():
            return None
        q = _RADIO.get("queue")
        if not isinstance(q, list) or not q:
            return None
        cands: list[tuple[int, dict[str, Any]]] = []
        for i, t in enumerate(q):
            if len(cands) >= max(1, GAP_RECORD_SHORTLIST):
                break
            tid = str((t or {}).get("id") or "") if isinstance(t, dict) else ""
            if not tid or tid in _TRACK_TALK:
                continue
            if norepeat_record_used(tid):
                norepeat_select_refuse("record", tid, "gap", text=str(t.get("title") or ""))
                continue
            cands.append((i, t))
        if not cands:
            return None
        # the operator's order is a desk row (STATION1 gap.record, odds 1.0): walk
        # it down and the gap goes straight to its rolled SFX
        if not s3_chance("gap.record", 1.0, "the gap's first answer is a rolled record "
                                            "(otherwise straight to rolled SFX)"):
            return None
        labels = [("%s - %s" % (t.get("title") or "a record", t.get("artist") or "?"))[:120] for _i, t in cands]
        k = _S3Dice("gap.record_pick", "which record fills the gap (the next fresh records in the rotation)").pick(
            "gap.record_pick", labels)
        k = k if 0 <= k < len(cands) else 0
        at, track = cands[k]
        q.insert(0, q.pop(at))
        roll = _s3_spin_roll("gap.record_pick") or {"key": "gap.record_pick", "index": k + 1, "of": len(cands),
                                                    "picked": labels[k], "own": "the station's own draw (dice off)"}
        roll = dict(roll, why=str(why or "dead air")[:120], at=round(time.time(), 3))
        _GAP_RECORD_ROLL[str(track.get("id") or "")] = roll
        while len(_GAP_RECORD_ROLL) > 16:
            _GAP_RECORD_ROLL.pop(next(iter(_GAP_RECORD_ROLL)))
        track["s3_gap"] = dict(roll)    # rides the queue row into its spin copy
        # the roll, into the origin ledger now - the record's own rec: note follows when it airs
        _origin_note({"id": "gap:%s:%d" % (str(track.get("id") or "")[:40], int(time.time())),
                      "kind": "gap_record", "who": "deck", "aired": "rolled", "air_at": time.time(),
                      "track_id": str(track.get("id") or "")[:80], "text": labels[k][:200],
                      "s3_roll": dict(roll), "origin_path": "norepeat_gap_record"})
        _RADIO["now"] = None            # a pinned needle is let go, as the needle drop does
        dj_skip()
        pipeline_log("air", ("the gap is a rolled record: %s (%s of %s, gap.record)%s"
                             % (labels[k], k + 1, len(cands), (" - " + why) if why else ""))[:220])
        return track
    except Exception as exc:  # noqa: BLE001
        pipeline_log("air", "the gap's record roll failed: %s: %s" % (type(exc).__name__, str(exc)[:120]))
        return None


@app.on_event("startup")
async def _norepeat_warm() -> None:
    """Read (or, the first time, seed) the book off the loop."""
    if norepeat_on():
        fire_and_forget(asyncio.to_thread(NOREPEAT.load))


@app.get("/api/norepeat")
async def norepeat_api(most: int = 40, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """[no-repeat-24h] The day's memory: how much it holds, and every refusal -
    kind, road, stage (select = struck before a roll, air = the last gate), why."""
    require_read_auth(authorization)
    got = await asyncio.to_thread(NOREPEAT.state, max(1, min(400, int(most or 40))))
    return dict(got, on=norepeat_on(), exempt=sorted(NOREPEAT_EXEMPT_KINDS))


'''

AIRLOG_ANCHOR = '''                _AIRLOG_INDEX[row["id"]] = row
                wrote += 1
'''
# Noted when it SOUNDED (stream/box/both/page, or a hearing stamp) - a line
# published and then flushed (a pause, a stale page) was never heard and may
# still have its first airing.
AIRLOG_NEW = '''                if ((row.get("aired") in NOREPEAT_SOUNDED or row.get(HEARD_STAMP))   # [no-repeat-24h:airlog]
                        and str(row.get("kind") or "") not in NOREPEAT_QUIET_KINDS
                        and row.get("who") not in ("board", "analysis")):
                    norepeat_note_line(row.get("text"), str(row.get("kind") or row.get("round") or ""),
                                       str(row.get("id") or ""), row.get("air_at"))
'''

TURNS_ANCHOR = "        # [s3-turnchain] not a line just said - this round's or the one before it\n"
TURNS_NEW = '''        # [no-repeat-24h:turns] THE LAST GATE BEFORE AIR for rounds: every seat,
        # every road through here, banked replays and recorded takes included -
        # a turn re-aired under a new id is the same words. Only a line the
        # operator typed is exempt. A refused turn is dropped (never swapped for
        # shelf material) and the refusal is recorded with its road.
        if not by_hand:
            _nr_why = norepeat_line_gate(text, who, "call" if caller_name else "",
                                         road=_norepeat_road(who))
            if _nr_why:
                note_drop(who, text, "no repeats inside a day - " + _nr_why)
                continue
'''

DJSPEAK_ANCHOR = '''    if not by_hand and not checked \\
            and kind not in ("station_id", "ad", "reply", "call"):
        _win = air_repeat_check(spoken, who, kind)
'''
DJSPEAK_NEW = '''    # [no-repeat-24h:dj_speak] the last gate for a single line - every kind,
    # the advert and the station ID too: no line twice inside a day. A chunk
    # speak_turns hands over (`checked`) was gated there, as its whole turn.
    if not by_hand and not checked and norepeat_line_gate(spoken, who, kind, road=kind or "line"):
        return ""
'''

# The re-air gate's function sits inside system3_banks_roll_patch's block, so
# its 24-hour leg is added by wrapping the name AFTER that block: every caller
# (bank_reair_pick, larder_reair_gate, shelf_take, the cupboard, call re-airs)
# looks the name up when it asks, and gets both answers.
REAIR_ANCHOR = "def gold_in_round_rate() -> float:\n"
REAIR_NEW = '''# [no-repeat-24h:reair] THE RE-AIR GATE'S 24-HOUR LEG. A banked round heard
# inside the day - or half of whose lines were - is struck before any roll, on
# every replay road, dice on or off. (A wrapper, so the gate's own text stands.)
_bank_reair_refusal_gate = bank_reair_refusal


def bank_reair_refusal(road: str, row: Any, cid: str = "") -> str:
    return _bank_reair_refusal_gate(road, row, cid) or norepeat_round_refusal(road, row)


'''

# gold_pick's pool comprehension is cast_names2_patch's text: the filter is its own statement after it.
GOLDPICK_ANCHOR = "        # [s3-banks-roll] ONLY BARS MINTED FROM SYSTEM 3 TURNS: while System 3\n"
GOLDPICK_NEW = "        pool = [r for r in pool if not norepeat_text_used(r.get(\"text\"))]   # [no-repeat-24h:gold-pick]\n"

ROTATION_ANCHOR = '        track = _spin_stamp(_RADIO["queue"].pop(take_at), "rotation",   # [s3-cover-b]\n'
ROTATION_NEW = '''        if norepeat_on():                                               # [no-repeat-24h:rotation]
            _nr_owned = bool(radio_paused() and _TRACK_TALK)
            _nr_at = norepeat_record_take(_RADIO["queue"], take_at, _nr_owned)
            if _nr_at < 0:
                _RADIO["queue"] = radio_fill(_RADIO["station"])
                track_talk_restore_queue()
                _nr_at = norepeat_record_take(_RADIO["queue"], 0, _nr_owned)
            if _nr_at < 0:
                norepeat_refuse("record", "", "rotation", why="every record the rotation holds was heard "
                                "inside the day - the needle waits rather than repeat one")
                return None
            take_at = _nr_at
'''

SOLO_ANCHOR = '    track = _spin_stamp(_RADIO["queue"].pop(0), "rotation",   # [s3-cover-b]\n'
SOLO_NEW = '''    if norepeat_on():                                                   # [no-repeat-24h:solo]
        _nr_at = norepeat_record_take(_RADIO["queue"], 0, road="solo")
        if _nr_at < 0:
            _RADIO["queue"] = radio_fill(_RADIO["station"])
            _nr_at = norepeat_record_take(_RADIO["queue"], 0, road="solo")
        if _nr_at < 0:
            return None
        if _nr_at:
            _RADIO["queue"].insert(0, _RADIO["queue"].pop(_nr_at))
'''

PLAYED_ANCHOR = '''    row = {k: track.get(k) for k in
           ("id", "title", "artist", "album", "seconds")}
'''
PLAYED_NEW = '''    norepeat_note_record(track.get("id"), str((track.get("s3_spin") or {}).get("lane") or "record"),   # [no-repeat-24h:played]
                         str(track.get("title") or ""))
'''

SFXHIST_ANCHOR = '''            row = {"ts": int(time.time()), "id": sfx_id(path),
                   "name": path.name, "who": who[:24]}
'''
SFXHIST_NEW = '''            norepeat_note_sfx(row["id"], who[:24] or "sfx", path.name)   # [no-repeat-24h:sfx-hist]
'''

VIDNOTE_ANCHOR = '''    """This clip is on the air now; spend it in the durable deck."""
    if not key:
        return
'''
VIDNOTE_NEW = '''    norepeat_note_sfx(key, "video", folder)                            # [no-repeat-24h:video-note]
'''

VIDCOOL_ANCHOR = '''    """Has this clip already been spent in the current shuffled book?"""
    if not key:
        return False
'''
VIDCOOL_NEW = '''    if norepeat_sfx_used(key):                                          # [no-repeat-24h:video-cool]
        return True
'''

CADENCE_ANCHOR = "            and weights.get(sfx_id(Path(p)), 1.0) > 0.05]\n"
CADENCE_NEW = '''    pool = norepeat_fresh_clips(pool, "board")                           # [no-repeat-24h:cadence]
'''

# sfx_db_pick_short_video is system3_sfx_roll_patch's text; its clip roll is
# wrapped AFTER it: a clip heard inside the day is refused (recorded) and the
# two rolls are made again - up to six times, then no clip rather than a repeat.
BOOKROLL_ANCHOR = "def sfx_db_pick_rotation_row(video: bool = True) -> tuple[Path, float] | None:\n"
BOOKROLL_NEW = '''# [no-repeat-24h:book-roll] the clip book's short-video draw, never a clip
# heard inside the day: refused, recorded, rolled again (at most six times).
_sfx_db_pick_short_video_rolls = sfx_db_pick_short_video


def sfx_db_pick_short_video(max_seconds: float,
                            rolled: dict | None = None) -> tuple[Path, float] | None:
    for _try in range(6):
        got = _sfx_db_pick_short_video_rolls(max_seconds, rolled)
        if not got or not norepeat_sfx_used(sfx_id(got[0])):
            return got
        norepeat_select_refuse("sfx", sfx_id(got[0]), "clip book", ref=got[0].name)
    return None


'''

GAPREC_ANCHOR = '        went = "" if clips_only else await gold_fill_gap(\n'
GAPREC_NEW = '''        # [no-repeat-24h:gap-record] THE GAP IS A ROLLED RECORD, THEN ROLLED SFX.
        # With no record turning and the floor free, the first answer is a
        # record System 3 rolls among the next fresh ones (gap.record); the
        # clips below are the second. Gold stands down (gold_fill_gap): a bar
        # is a re-aired line, and gold now airs only as a rolled reply.
        if norepeat_on() and not clips_only and not floor_held and not now_really_playing():
            if norepeat_gap_record(why):
                _SFX_GAP["went"] = "record"
                _SFX_GAP["why"] = str(why)[:120]
                return "record"
'''

GOLDGAP_ANCHOR = '''    want = float(ahead) if ahead else GOLD_RUN_AHEAD
    # [s3-account] the gap this run fills: the gold bar's forced node names it
'''
GOLDGAP_NEW = '''    # [no-repeat-24h:gold-gap] A GOLD RUN IS A RE-AIR: "never a re-aired line"
    # in a gap. The gap is a rolled record, then rolled SFX (sfx_fill_gap); gold
    # reaches the air as System 3's rolled reply (the GOLD roll), not forced here.
    if norepeat_on():
        return ""
'''

CONT_ANCHOR = "    # #1175: THE GOLD GOES FIRST. There are twenty-eight continuity lines\n"
CONT_NEW = '''    # [no-repeat-24h:continuity] THE RESERVE IS NOT RE-AIRED ANY MORE. Its
    # recorded pairs are the same lines every time; under the 24-hour rule the
    # emergency answer is the gap filler's: a rolled record, then rolled SFX.
    if norepeat_on():
        _went = await sfx_fill_gap(reason or "the emergency reserve was reached")
        if _went:
            _CONTINUITY_STATE.update(last_air=time.time(),
                                     why="the gap filler covered it (%s) - no recorded pair re-aired "
                                         "[no-repeat-24h]" % _went)
        return bool(_went)
'''

COVER_ANCHOR = '''        if await gold_fill_gap(why or "the floor is held for a render and "
                                      "nobody has spoken", floorless=True):
'''
COVER_NEW = '''        if await (sfx_fill_gap(why or "the floor is held for a render and nobody has spoken",
                               under_floor=True, clips_only=True)      # [no-repeat-24h:cover-held]
                  if norepeat_on() else
                  gold_fill_gap(why or "the floor is held for a render and "
                                       "nobody has spoken", floorless=True)):
'''

STING_ANCHOR = "    _sample_seconds = await sfx_db_seconds_async(sample)\n"
STING_NEW = '''    # [no-repeat-24h:sting] THE LAST GATE for a clip: never one heard inside the
    # day (the operator's own button excepted). The road that asked moves on.
    if str(who or "") != "operator" and norepeat_sfx_used(sfx_id(sample)):
        norepeat_refuse("sfx", sfx_id(sample), str(who or "sting"), ref=sample.name)
        return ""
'''

# (the "prepared = None" block after it is system3_exchange_chain_patch's text: the gate sits above it)
PRODAD_ANCHOR = '''    name = str(entry.get("audio") or "")
    if not name or not (PRODUCED_ADS_DIR / name).is_file():
        return False
'''

# _s3_ad_pick is system3_roads_patch's text: the stored spot it rolled is
# refused right after, when its words were heard inside the day (the break then
# writes a fresh one - its next option - instead of rerunning).
ADPICK_ANCHOR = "    stored = await _s3_ad_pick()                              # [s3-roads]\n"
ADPICK_NEW = '''    if stored and norepeat_text_used(stored.get("text")):              # [no-repeat-24h:ad-pick]
        norepeat_select_refuse("line", "", "ad", text=stored.get("text"), ref=str(stored.get("id") or ""))
        stored = None
'''
PRODAD_NEW = '''    if norepeat_line_gate(entry.get("text"), "dj", "ad", road="ad_spot"):   # [no-repeat-24h:produced-ad]
        return False
'''

EDITS = [
    Edit("helpers", A, HELPERS_ANCHOR, HELPERS, "[no-repeat-24h:helpers]", "before"),
    Edit("airlog", A, AIRLOG_ANCHOR, AIRLOG_NEW, "[no-repeat-24h:airlog]", "after"),
    Edit("turns", A, TURNS_ANCHOR, TURNS_NEW, "[no-repeat-24h:turns]", "before"),
    Edit("dj_speak", A, DJSPEAK_ANCHOR, DJSPEAK_NEW, "[no-repeat-24h:dj_speak]", "before"),
    Edit("reair", A, REAIR_ANCHOR, REAIR_NEW, "[no-repeat-24h:reair]", "before"),
    Edit("gold-pick", A, GOLDPICK_ANCHOR, GOLDPICK_NEW, "[no-repeat-24h:gold-pick]", "before"),
    Edit("rotation", A, ROTATION_ANCHOR, ROTATION_NEW, "[no-repeat-24h:rotation]", "before"),
    Edit("solo", A, SOLO_ANCHOR, SOLO_NEW, "[no-repeat-24h:solo]", "before"),
    Edit("played", A, PLAYED_ANCHOR, PLAYED_NEW, "[no-repeat-24h:played]", "after"),
    Edit("sfx-hist", A, SFXHIST_ANCHOR, SFXHIST_NEW, "[no-repeat-24h:sfx-hist]", "after"),
    Edit("video-note", A, VIDNOTE_ANCHOR, VIDNOTE_NEW, "[no-repeat-24h:video-note]", "after"),
    Edit("video-cool", A, VIDCOOL_ANCHOR, VIDCOOL_NEW, "[no-repeat-24h:video-cool]", "after"),
    Edit("cadence", A, CADENCE_ANCHOR, CADENCE_NEW, "[no-repeat-24h:cadence]", "after"),
    Edit("book-roll", A, BOOKROLL_ANCHOR, BOOKROLL_NEW, "[no-repeat-24h:book-roll]", "before"),
    Edit("gap-record", A, GAPREC_ANCHOR, GAPREC_NEW, "[no-repeat-24h:gap-record]", "before"),
    Edit("gold-gap", A, GOLDGAP_ANCHOR, GOLDGAP_NEW, "[no-repeat-24h:gold-gap]", "before"),
    Edit("continuity", A, CONT_ANCHOR, CONT_NEW, "[no-repeat-24h:continuity]", "before"),
    Edit("cover-held", A, COVER_ANCHOR, COVER_NEW, "[no-repeat-24h:cover-held]", "replace"),
    Edit("sting", A, STING_ANCHOR, STING_NEW, "[no-repeat-24h:sting]", "before"),
    Edit("ad-pick", A, ADPICK_ANCHOR, ADPICK_NEW, "[no-repeat-24h:ad-pick]", "after"),
    Edit("produced-ad", A, PRODAD_ANCHOR, PRODAD_NEW, "[no-repeat-24h:produced-ad]", "after"),
]

if __name__ == "__main__":
    sys.exit(run("norepeat_24h_patch", EDITS, requires=[("air_norepeat.py", "class Book")]))

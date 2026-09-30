"""[reply-gap] THE PAUSE BETWEEN REPLIES, AND THE ROLL THAT CAN PICK IT.

"put a slider here for adjusting the space between dj replies and the sfx guy
 replies. I want each person taking 1 second between replies. And I want to
 increase it up to possibly 10 seconds ... as low as .2 seconds ... and a 2nd
 slider for a roulette RNG roll after each reply ... next to the 2nd slider i
 want a toggle to enable roulette rolls after each reply to decide the time to
 next reply. Show the rolling dice here ..."           - the operator, 2026-09-30

WHAT AIRS. A round is welded into one file by `_call_concat_blocking`, and the
silence between two segments of it is the BEAT the caller draws (#778: drawn
once, handed to the mixer AND to the timeline, so both are built out of the
same numbers). That is the one place the pause between two replies is decided,
so that is where this enters: at every seam that ends a REPLY - a DJ line, the
SFX Guy's answer, a sting off the board - the beat becomes the operator's gap.
Two chunks of ONE speaker's turn (#1275's one-line-one-clip split) and a
listening response keep the short varied beat: that is a breath inside a
reply, not the space between two of them.

THE SETTINGS (station-wide, `data/reply_gap.json`, GET/POST /api/reply-gap):
  gap    0.2 - 10 s, default 1.0   the pause after every reply
  range  0.1 - 10 s, default 1.0   how far a roll may move it, either way
  roll   off by default            on: each pause is ROLLED

THE ROLL. With `roll` on, each reply's pause is uniform in
  [max(0.2, gap - range), min(10, gap + range)]
and it is a System 3 roll (`s3_roll("reply.gap")`, the station's dice door),
recorded on the round it shaped under the turn that just ended (`_s3_roll_on`
-> roll_to -> a STATION observation in the Rolodex, the receipt the roulette
cards read). A pause outside any System 3 round is filed on the station's hour
(`station:YYYYMMDDHH`, where the manager's topic rolls go). System 3's dice
off: the station's own random, as every s3_* door falls back - and the receipt
is still written here (`data/reply_gap_rolls.jsonl`, the last ROLLS_KEPT in
memory for the panel).

THE PLANNER. `expected_gap()` is what one seam between two replies costs the
air: the gap, or the middle of the roll's window when it rolls. app.py's
segment budget, the fit checks and the stock pricing ask it.

Nothing here may stop the air: every entry point the station calls swallows
its own failure and hands back what it was given.
"""
from __future__ import annotations

import json
import queue
import random
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Iterable

try:    # module level: FastAPI resolves the routes' string annotations here
    from fastapi import Header, HTTPException, Request
except ImportError:  # the pure tests need none of it
    Header = HTTPException = Request = None  # type: ignore[assignment,misc]

GAP_MIN = 0.2
GAP_MAX = 10.0
GAP_DEFAULT = 1.0
RANGE_MIN = 0.1
RANGE_MAX = 10.0
RANGE_DEFAULT = 1.0
STEP = 0.1                       # the sliders' step; a rolled pause lands on it too
ROLL_KEY = "reply.gap"
SETTINGS_NAME = "reply_gap.json"
ROLLS_NAME = "reply_gap_rolls.jsonl"
ROLLS_KEPT = 200                 # receipts in memory, for the panel
ROLLS_FILE_MOST = 4 * 1024 * 1024
HOST_SEATS = ("dj", "cohost", "third", "host", "caller", "caller2", "guest")
# [reply-gap:door] the pause into a paged round's next page is the page door's,
# like the pause before every other clip; the burst no longer carries its own.
CARRY_BY_DOOR = True

_NS: dict[str, Any] = {"ns": {}}       # the station's namespace, read at call time
_LOCK = threading.RLock()
_STATE: dict[str, Any] = {"path": None, "settings": None, "rolls_path": None}
_ROLLS: deque = deque(maxlen=ROLLS_KEPT)
_WRITES: "queue.Queue[dict[str, Any]]" = queue.Queue(maxsize=2000)
_WRITER: dict[str, Any] = {"thread": None}
_SEQ = [0]


# ------------------------------------------------------------- the numbers

def _num(value: Any, default: float) -> float:
    try:
        got = float(value)
    except (TypeError, ValueError):
        return float(default)
    if got != got or got in (float("inf"), float("-inf")):
        return float(default)
    return got


def _step(value: float) -> float:
    return round(round(float(value) / STEP) * STEP, 1)


def clamp_gap(value: Any) -> float:
    """The pause, on the slider's step, inside 0.2 - 10 s."""
    return min(GAP_MAX, max(GAP_MIN, _step(_num(value, GAP_DEFAULT))))


def clamp_range(value: Any) -> float:
    """How far a roll may move it, on the step, inside 0.1 - 10 s."""
    return min(RANGE_MAX, max(RANGE_MIN, _step(_num(value, RANGE_DEFAULT))))


def normalise(raw: Any) -> dict[str, Any]:
    """Any stored or posted shape -> the settings, every number in bounds."""
    raw = raw if isinstance(raw, dict) else {}
    roll = raw.get("roll", False)
    if isinstance(roll, str):
        roll = roll.strip().lower() in ("1", "true", "on", "yes")
    return {"gap": clamp_gap(raw.get("gap", GAP_DEFAULT)),
            "range": clamp_range(raw.get("range", RANGE_DEFAULT)),
            "roll": bool(roll),
            "at": _num(raw.get("at", 0), 0.0),
            "by": str(raw.get("by") or "")[:40]}


def window(settings: Any) -> tuple[float, float]:
    """Where a roll may land: gap +/- range, kept inside 0.2 - 10 s."""
    s = normalise(settings)
    lo = max(GAP_MIN, round(s["gap"] - s["range"], 1))
    hi = min(GAP_MAX, round(s["gap"] + s["range"], 1))
    return lo, max(lo, hi)


def expected(settings: Any) -> float:
    """What one pause costs the air on average: the gap, or - rolling - the
    middle of the window (uniform), which moves off the gap only where a
    bound clips it (gap 0.5, range 2 -> 0.2..2.5 -> 1.35)."""
    s = normalise(settings)
    if not s["roll"]:
        return s["gap"]
    lo, hi = window(s)
    return round((lo + hi) / 2.0, 3)


def gap_from_u(u: Any, lo: float, hi: float) -> float:
    """The number a die in [0, 1) lands the pause on, on the step."""
    u = min(0.999999, max(0.0, _num(u, 0.0)))
    got = _step(float(lo) + u * (float(hi) - float(lo)))
    return min(float(hi), max(float(lo), got))


def dice_of(u: Any) -> int:
    """The d100 face, as System 3's DrawStream prints it."""
    return min(100, int(min(0.999999, max(0.0, _num(u, 0.0))) * 100) + 1)


# ------------------------------------------------------------- the store

def _settings_path() -> Path | None:
    got = _STATE.get("path")
    return Path(got) if got else None


def settings() -> dict[str, Any]:
    """The station's settings now (read once, then held; POST rewrites)."""
    with _LOCK:
        got = _STATE.get("settings")
        if got is None:
            got = normalise({})
            path = _settings_path()
            if path is not None:
                try:
                    got = normalise(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    got = normalise({})
            _STATE["settings"] = got
        return dict(got)


def save(changes: Any, by: str = "") -> dict[str, Any]:
    """Merge `changes` (any of gap / range / roll), clamp, write atomically."""
    changes = changes if isinstance(changes, dict) else {}
    with _LOCK:
        cur = settings()
        merged = dict(cur)
        for key in ("gap", "range", "roll"):
            if key in changes:
                merged[key] = changes[key]
        merged["at"] = time.time()
        merged["by"] = str(by or changes.get("by") or "")[:40]
        got = normalise(merged)
        path = _settings_path()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(got, indent=1), encoding="utf-8")
            tmp.replace(path)
        _STATE["settings"] = got
        return dict(got)


def expected_gap() -> float:
    """[the planner's number] one seam between two replies, on air."""
    try:
        return expected(settings())
    except Exception:  # noqa: BLE001
        return GAP_DEFAULT


def state(recent: int = 12) -> dict[str, Any]:
    """What GET answers: the settings, their window, the planner's number,
    the bounds the sliders are built from, and the newest receipts."""
    s = settings()
    lo, hi = window(s)
    return {"ok": True, "gap": s["gap"], "range": s["range"], "roll": s["roll"],
            "lo": lo, "hi": hi, "expected": expected(s),
            "updated_at": s["at"], "by": s["by"],
            "bounds": {"gap": [GAP_MIN, GAP_MAX], "range": [RANGE_MIN, RANGE_MAX],
                       "step": STEP, "gap_default": GAP_DEFAULT,
                       "range_default": RANGE_DEFAULT},
            "rule": "rolling: uniform in [max(0.2, gap - range), min(10, gap + range)]",
            "key": ROLL_KEY,
            "recent": list(_ROLLS)[-max(0, int(recent)):] if recent else []}


# ------------------------------------------------------------- receipts

def _writer_loop() -> None:
    while True:
        row = _WRITES.get()
        path = _STATE.get("rolls_path")
        if not path:
            continue
        try:
            p = Path(path)
            try:
                if p.stat().st_size > ROLLS_FILE_MOST:
                    keep = p.read_bytes()[-ROLLS_FILE_MOST // 2:]
                    cut = keep.find(b"\n")
                    p.write_bytes(keep[cut + 1:] if cut >= 0 else b"")
            except OSError:
                pass
            with p.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        except Exception:  # noqa: BLE001 - a receipt that will not write is still in memory
            pass


def _remember(receipt: dict[str, Any]) -> None:
    _ROLLS.append(receipt)
    if not _STATE.get("rolls_path"):
        return
    if _WRITER.get("thread") is None:
        t = threading.Thread(target=_writer_loop, name="reply-gap-receipts", daemon=True)
        _WRITER["thread"] = t
        t.start()
    try:
        _WRITES.put_nowait(receipt)
    except queue.Full:
        pass


def recent(limit: int = 12) -> list[dict[str, Any]]:
    return list(_ROLLS)[-max(0, int(limit)):]


def _door(name: str) -> Any:
    """One of the station's doors (s3_roll, _s3_roll_on, bank_s3_of, ...), looked
    up when it is used: they are defined further down app.py than the import."""
    try:
        return (_NS.get("ns") or {}).get(name)
    except Exception:  # noqa: BLE001
        return None


def _node_of(meta: Any, who: str, text: str) -> tuple[str, str]:
    """The System 3 round and turn a pause after `who`'s words belongs to, or
    the station's hour when the round has none."""
    cid, tid = "", ""
    try:
        fn = _door("bank_s3_of")
        s3 = fn(meta) if fn else {}
        cid = str((s3 or {}).get("conversation_id") or "")
        if cid and text and str(who or "") in HOST_SEATS:
            find = _door("system3_turn_id_for")
            if find:
                tid = str(find(meta, str(text), str(who)) or "")
    except Exception:  # noqa: BLE001
        cid = cid or ""
    if not cid:
        cid = "station:" + time.strftime("%Y%m%d%H", time.gmtime())
    return cid, tid


def draw(meta: Any = None, who: str = "", text: str = "", next_who: str = "",
         road: str = "round", rng: Any = None) -> dict[str, Any]:
    """The pause after one reply: the fixed gap, or a roll on System 3's dice
    with its receipt. Never raises."""
    try:
        s = settings()
    except Exception:  # noqa: BLE001
        s = normalise({})
    if not s["roll"]:
        return {"s": s["gap"], "rolled": False}
    lo, hi = window(s)
    t0 = time.time()
    u = None
    if rng is None:
        fn = _door("s3_roll")
        if fn:
            try:
                got = fn(ROLL_KEY, "the pause after a reply (%.1f-%.1f s)" % (lo, hi))
                u = float(got) if got is not None else None
            except Exception:  # noqa: BLE001
                u = None
    if u is None or not 0.0 <= u < 1.0:
        u = (rng or random).random()
    gap = gap_from_u(u, lo, hi)
    cid, tid = _node_of(meta, who, text)
    rec: dict[str, Any] = {}
    on = _door("_s3_roll_on") if rng is None else None
    if on:
        try:
            rec = on(ROLL_KEY, cid, tid,
                     "the pause after this reply: rolled {dice} - %.1f s in %.1f-%.1f s"
                     % (gap, lo, hi), since=t0) or {}
        except Exception:  # noqa: BLE001
            rec = {}
    dice = rec.get("dice") if isinstance(rec.get("dice"), int) else dice_of(u)
    _SEQ[0] += 1
    receipt = {"id": "%d-%d" % (int(t0 * 1000), _SEQ[0]), "at": round(t0, 3),
               "s": gap, "lo": lo, "hi": hi, "gap": s["gap"], "range": s["range"],
               "u": round(float(u), 6), "dice": int(dice),
               "by": "system3" if rec else "station", "key": ROLL_KEY,
               "who": str(who or "")[:24], "next": str(next_who or "")[:24],
               "road": str(road or "")[:24], "conversation_id": cid, "turn_id": tid,
               "recorded_on": str(rec.get("recorded_on") or "")}
    _remember(receipt)
    return {"s": gap, "rolled": True, "dice": int(dice), "lo": lo, "hi": hi,
            "by": receipt["by"], "id": receipt["id"]}


# ------------------------------------------------------------- the seams

def _item(items: list, turn_ix: list, r: int) -> Any:
    try:
        t = int(turn_ix[r])
    except (IndexError, TypeError, ValueError):
        return None
    return items[t] if 0 <= t < len(items) else None


def _reply_seam(a: Any, b: Any) -> bool:
    """Does the seam between row a and row b end a REPLY? None is a row that
    is not a turn of the script: the board's sting, the SFX Guy, a gold bar."""
    if a is None or b is None:
        return True
    if a.get("listening_response") or b.get("listening_response"):
        return False                        # an "mm-hm" rides inside a reply
    if not a.get("turn_end") and str(a.get("who") or "") == str(b.get("who") or ""):
        return False                        # one speaker, one turn, two clips
    return True


def reply_seams(count: int, seg_ix: Iterable[int], turn_ix: list, items: list) -> dict[int, bool]:
    """seg slot -> True when the seam AFTER that slot ends a reply. A slot
    with no row (the ring) is absent; the hang-up after the last line makes
    it a reply seam; the burst's own last slot answers whether the reply is
    over (for the seam into the next burst)."""
    seg_ix = [int(x) for x in seg_ix]
    row_at = {slot: r for r, slot in enumerate(seg_ix)}
    out: dict[int, bool] = {}
    for r, slot in enumerate(seg_ix):
        if not 0 <= slot < count:
            continue
        a = _item(items, turn_ix, r)
        if slot >= count - 1:
            out[slot] = a is None or (bool(a.get("turn_end"))
                                      and not a.get("listening_response"))
            continue
        nr = row_at.get(slot + 1)
        out[slot] = True if nr is None else _reply_seam(a, _item(items, turn_ix, nr))
    return out


def burst(beats: list, seg_ix: list, turn_ix: list, transcript: list, items: list,
          meta: Any = None, carry: bool = False, road: str = "round",
          rng: Any = None) -> tuple[list[float], dict[Any, dict[str, Any]]]:
    """The burst's beats with every reply seam set to its pause (drawn, or
    rolled, once each). `notes` is slot -> the pause, plus "carry": the pause
    into the NEXT burst when `carry` (a paged round; app.py waits it out on
    the page ledger, since no beat can sit after a file's last segment)."""
    out = [float(b or 0) for b in (beats or [])]
    notes: dict[Any, dict[str, Any]] = {}
    count = len(out)
    if CARRY_BY_DOOR:
        carry = False          # [reply-gap:door] the page door seams every clip, pages included
    flags = reply_seams(count, seg_ix, list(turn_ix or []), list(items or []))
    for r, slot in enumerate(list(seg_ix or [])):
        slot = int(slot)
        if not flags.get(slot):
            continue
        last = slot >= count - 1
        if last and not carry:
            continue
        try:
            who, text = str(transcript[r][0] or ""), str(transcript[r][1] or "")
        except (IndexError, TypeError):
            who, text = "", ""
        try:
            nxt = str(transcript[r + 1][0] or "") if r + 1 < len(transcript) else ""
        except (IndexError, TypeError):
            nxt = ""
        on_who, on_text = who, text
        if who in ("board", "drop"):
            # the SFX Guy's answer (or a sting) is filed on the host turn it followed
            on_who, on_text = "", ""
            for back in range(r - 1, -1, -1):
                try:
                    if str(transcript[back][0]) in HOST_SEATS:
                        on_who, on_text = str(transcript[back][0]), str(transcript[back][1] or "")
                        break
                except (IndexError, TypeError):
                    break
        note = draw(meta, on_who, on_text, nxt, road, rng=rng)
        note["who"] = who
        if last:
            notes["carry"] = dict(note, carry=True)
        else:
            out[slot] = float(note["s"])
            notes[slot] = note
    return out, notes


def plain(count: int, meta: Any = None, road: str = "", base: list | None = None,
          rng: Any = None) -> list[float]:
    """Beats for a join where every seam is a reply (a line and the stings
    answering it; the resume reel of whole lines). The last gets none."""
    n = max(0, int(count))
    out = [float(b or 0) for b in (base or [])][:n]
    out += [0.0] * (n - len(out))
    for i in range(max(0, n - 1)):
        out[i] = float(draw(meta, "", "", "", road, rng=rng)["s"])
    if out:
        out[-1] = 0.0
    return out


def stamp_rows(rows: list, seg_ix: list, notes: dict) -> None:
    """Each row whose reply a pause follows carries it ("gap"), for the panel's
    dice: `s` the pause, `inside` how much of it is in this file (the carry
    into the next burst is waited out on the ledger, so none of it is)."""
    if not notes or not rows:
        return
    for r, row in enumerate(rows):
        try:
            slot = int(seg_ix[r])
        except (IndexError, TypeError, ValueError):
            continue
        note = notes.get(slot)
        inside = True
        if note is None and r == len(rows) - 1 and notes.get("carry"):
            note, inside = notes["carry"], False
        if not isinstance(note, dict) or not isinstance(row, dict):
            continue
        row["gap"] = {k: note[k] for k in ("s", "rolled", "dice", "lo", "hi", "by", "id")
                      if k in note}
        row["gap"]["inside"] = float(note["s"]) if inside else 0.0


def carry_seconds(notes: dict, length: Any, rows: list) -> float:
    """How much longer the page must hold before the next burst, so the pause
    into it is the pause the roll picked: its size less the silence already
    at the end of this file (the last row's `until` to the file's end)."""
    note = (notes or {}).get("carry")
    if not isinstance(note, dict):
        return 0.0
    try:
        tail = max(0.0, float(length or 0) - float((rows or [{}])[-1].get("until") or 0))
    except (TypeError, ValueError, AttributeError):
        tail = 0.0
    return round(max(0.0, float(note.get("s") or 0) - tail), 3)


# ------------------------------------------------------------- the page door
#
# [reply-gap:door] EVERY MESSAGE, NOT ONLY A ROUND'S. Most of the air is not a
# welded round: a caller's line, an aside, a station id, an ad's lines, the
# SFX Guy's stings and dj_speak's single lines each go out as their own clip,
# and every one of them passes page_feed_append (#1147's one door). The pause
# between two of them is decided THERE: the clip is stamped to start the
# operator's pause (or the roll) after the last message's WORDS ended - the
# measured silent tail of that clip (tail_s) is given up to a shorter pause,
# and the players hand over at the words' end when the next is due.

_BOOKED: dict[str, float] = {"until": 0.0, "tail": 0.0}
_LAST_DOOR: dict[str, Any] = {"rows": None, "start": 0.0}
BOOKED_MATCH_S = 0.25            # the air cursor must be THAT clip's end to trust its tail


def is_message(clip: Any) -> bool:
    """A clip on the page feed that is a message: sounds, and is not a
    person's reply (#206: a person outranks the show) or a picture."""
    if not isinstance(clip, dict) or not clip.get("url"):
        return False
    if str(clip.get("kind") or "") == "reply":
        return False
    if clip.get("picture_only") or clip.get("silent_picture") or clip.get("endless"):
        return False
    return bool(str(clip.get("text") or "").strip() or clip.get("speech") or clip.get("sting"))


def door(clip: Any, air_until: float, earliest: float, tail_of: Any = None,
         rng: Any = None) -> float | None:
    """When this message may start (seconds), with its pause stamped on it
    (`gap_before`) - or None: not a message, or already seamed (a recovered
    clip keeps what it had), and the door's old rule stands.

    `air_until` is the page's sold air (_PAGE_AIR_UNTIL); `earliest` is now
    plus the publication lead. The last message's words end its measured
    tail before `air_until`. When the air has been quiet longer than any
    pause could be, there is no seam and nothing is rolled."""
    try:
        if not is_message(clip):
            return None
        try:
            clip["tail_s"] = round(max(0.0, float(tail_of(clip) if tail_of else 0.0)), 3)
        except Exception:  # noqa: BLE001
            clip["tail_s"] = 0.0
        if isinstance(clip.get("gap_before"), dict):
            return None
        own = float(clip.get("broadcast_ms") or 0) / 1000.0
        air = float(air_until or 0)
        mine = abs(float(_BOOKED.get("until") or 0) - air) <= BOOKED_MATCH_S
        prev_tail = float(_BOOKED.get("tail") or 0) if mine else 0.0
        words_end = air - prev_tail
        s = settings()
        reach = window(s)[1] if s["roll"] else s["gap"]
        # A seam needs a message that ends there: the cursor is the end of the
        # clip booked last, or clips are booked past the earliest start. The
        # page's own floor (now + lead, nothing booked) is free air.
        booked_ahead = mine or air > float(earliest) + 0.01
        if not booked_ahead or words_end + reach <= float(earliest):
            return max(own, air)                 # the air is quiet: no seam
        _LAST_DOOR.update(rows=id(((clip.get("stream") or {}).get("rows")) or clip), start=0.0)
        note = draw(clip.get("ready_round") if isinstance(clip.get("ready_round"), dict) else None,
                    str(clip.get("who") or ""), str(clip.get("text") or "")[:200], "",
                    "page", rng=rng)
        floor = words_end + float(note["s"])
        if own <= air + 0.05:
            # it was only waiting for the air: the pause decides, into the
            # last clip's silent tail when the pause is shorter than it
            start = max(float(earliest), floor)
        else:
            start = max(own, floor)              # held later by its own maker: never earlier
        clip["gap_before"] = dict({k: note[k] for k in ("s", "rolled", "dice", "lo", "hi", "by", "id")
                                   if k in note},
                                  after=round(words_end, 3), tail=round(prev_tail, 3),
                                  overlap=round(max(0.0, air - start), 3))
        _LAST_DOOR["start"] = float(start)
        return start
    except Exception:  # noqa: BLE001
        return None


def started(rows: Any, default: float) -> float:
    """Where the door started the clip carrying `rows` (a paged round asks
    right after publishing it, to book its own end from the same moment),
    or `default` when the door did not seam it."""
    try:
        if rows is not None and _LAST_DOOR.get("rows") == id(rows) and _LAST_DOOR.get("start"):
            return float(_LAST_DOOR["start"])
    except Exception:  # noqa: BLE001
        pass
    return float(default)


def booked(clip: Any, until: float) -> None:
    """The air now ends at `until`: remember whose end it is, and its tail."""
    try:
        if float(until) >= float(_BOOKED.get("until") or 0) - 1e-6:
            _BOOKED["until"] = float(until)
            _BOOKED["tail"] = float((clip or {}).get("tail_s") or 0) if isinstance(clip, dict) else 0.0
    except Exception:  # noqa: BLE001
        pass


def overlap(clip: Any) -> float:
    """How far this clip was stamped into the last one's silent tail (for
    the page's own cursor, which would otherwise chain the whole tail)."""
    try:
        return max(0.0, float(((clip or {}).get("gap_before") or {}).get("overlap") or 0))
    except Exception:  # noqa: BLE001
        return 0.0


# ------------------------------------------------------------- a produced round

def retime_cue_map(cue_map: Any, pauses: dict[str, float]) -> bool:
    """[#1337 kept honest] A round the producer assembled carries its seam
    beats and a MEASURED cue map, and the air re-mixes it with those beats.
    When the air sets a seam to the operator's pause instead, the map is
    moved by exactly what changed - integer samples, every cue after the
    seam shifted by the difference, the body by the sum - so it still
    describes the file the mixer builds and the air still adopts it (a
    pause is pure silence: apad at the mixer's own rate, sample-exact).
    `pauses`: occurrence id -> the new pause after that line, in seconds.
    Returns True when anything moved."""
    if not isinstance(cue_map, dict) or not pauses:
        return False
    cues = cue_map.get("cues")
    if not isinstance(cues, list) or not cues:
        return False
    rate = int(_num(cue_map.get("sample_rate"), 24000)) or 24000
    mix = cue_map.get("mix") if isinstance(cue_map.get("mix"), dict) else None
    beats = list(mix.get("beats") or []) if mix is not None else []
    shift = 0
    for k, cue in enumerate(cues):
        if not isinstance(cue, dict):
            return False
        oid = str(cue.get("occurrence_id") or "")
        old = int(_num(cue.get("pause_frames"), 0))
        new = old
        if oid in pauses:
            new = max(0, int(round(float(pauses[oid]) * rate)))
        start = int(_num(cue.get("start_sample"), 0)) + shift
        speech_end = int(_num(cue.get("speech_end_sample"), 0)) + shift
        cue["start_sample"] = start
        if "speech_start_sample" in cue:
            cue["speech_start_sample"] = int(_num(cue.get("speech_start_sample"), 0)) + shift
        cue["speech_end_sample"] = speech_end
        cue["pause_frames"] = new
        cue["cue_end_sample"] = speech_end + new
        cue["start_seconds"] = round(start / rate, 6)
        cue["speech_end_seconds"] = round(speech_end / rate, 6)
        cue["cue_end_seconds"] = round((speech_end + new) / rate, 6)
        cue["pause_seconds"] = round(new / rate, 6)
        if k < len(beats):
            beats[k] = round(new / rate, 6)
        shift += new - old
    if mix is not None and beats:
        mix["beats"] = beats
    if shift:
        for key in ("body_frames", "frame_count"):
            if key in cue_map:
                cue_map[key] = int(_num(cue_map.get(key), 0)) + shift
        if "frame_count" in cue_map:
            cue_map["seconds"] = round(int(cue_map["frame_count"]) / rate, 6)
    cue_map["reply_gap"] = {"at": round(time.time(), 3), "shift_frames": shift}
    return True


def retime_for_burst(meta: Any, beats: list, seg_ix: list, turn_ix: list,
                     items: list) -> bool:
    """The produced round's map, moved to the beats this burst will mix with:
    each line's pause is the beat at its own slot."""
    try:
        cue_map = meta.get("cue_map") if isinstance(meta, dict) else None
        if not isinstance(cue_map, dict) or not cue_map.get("cues"):
            return False
        pauses: dict[str, float] = {}
        for r, slot in enumerate(list(seg_ix or [])):
            item = _item(list(items or []), list(turn_ix or []), r)
            if not isinstance(item, dict):
                continue
            oid = str(dict(item.get("production") or {}).get("occurrence_id") or "")
            if oid and 0 <= int(slot) < len(beats):
                pauses[oid] = float(beats[int(slot)] or 0)
        return retime_cue_map(cue_map, pauses)
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------- wiring

def bind(namespace: dict[str, Any]) -> None:
    """Hold the station's namespace (its dice doors and data_path), read the
    settings. Called where app.py imports this, before any road runs."""
    _NS["ns"] = namespace
    try:
        data_path = namespace["data_path"]
        _STATE["path"] = str(data_path(SETTINGS_NAME))
        _STATE["rolls_path"] = str(data_path(ROLLS_NAME))
    except Exception:  # noqa: BLE001
        pass
    _STATE["settings"] = None
    settings()


def use_path(path: Any, rolls: Any = None) -> None:
    """For the tests (and tools): a settings file of their own."""
    _STATE["path"] = str(path) if path else None
    _STATE["rolls_path"] = str(rolls) if rolls else None
    _STATE["settings"] = None


def install(app: Any, namespace: dict[str, Any]) -> None:
    """GET /api/reply-gap and POST /api/reply-gap {gap?, range?, roll?}."""

    def _auth(fn_name: str, authorization: Any) -> None:
        fn = namespace.get(fn_name)
        if callable(fn):
            fn(authorization)

    @app.get("/api/reply-gap")
    async def reply_gap_get_api(recent: int = 12,
                                authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _auth("require_read_auth", authorization)
        return state(max(0, min(ROLLS_KEPT, int(recent or 0))))

    @app.post("/api/reply-gap")
    async def reply_gap_post_api(request: Request,
                                 authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _auth("require_auth", authorization)      # a write: the station key
        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="a JSON body is required") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="a JSON object is required")
        import asyncio
        got = await asyncio.to_thread(save, body, str(body.get("by") or "panel"))
        try:
            log = namespace.get("pipeline_log")
            if callable(log):
                lo, hi = window(got)
                log("air", ("the pause between replies is now %.1f s%s"
                            % (got["gap"], (" - rolled after each reply in %.1f-%.1f s"
                                            % (lo, hi)) if got["roll"] else ""))[:200])
        except Exception:  # noqa: BLE001
            pass
        return state(12)

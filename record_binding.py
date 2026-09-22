# -*- coding: utf-8 -*-
"""#1237: a line bound to a record airs with that record.

The operator (2026-09-19 23:42, at the Script view):

    "Let's make sure that when a song is associated with a particular
    dialogue, that that song is playing whenever that basic dialogue is
    playing.  So that way, whenever that dialogue is playing, the right
    song is playing."

What he photographed: the host's introduction to DEATH DEVOIR -
見えないハプティクス ("two minutes and twenty-four seconds on the clock" -
that record is 144.1 s long) ON AIR while the deck read Philip Glass -
6-I'm Going To Make A Cake at 2:02 of 4:05.

MEASURED BEFORE ANY OF THIS WAS WRITTEN - data/air_log.jsonl (every line
the station put out) joined to data/radio_cache/music_log.jsonl (every
record start, #633) by the record an introduction names:

  * that introduction: its record started 04:37:35 UTC, ran its full
    144 s, Philip Glass started 04:40:01, the introduction went out at
    04:41:27 - 232 s after its record started, 88 s after it ended,
    87 s into the wrong one.

  * 48 hours: 84 introductions; 79 name a record the log can find; 39
    went out over the record they name and 40 over a different one.
    Of the 39, NONE went out before its record started; the median was
    128 s into it.  24 hours: 41 / 40 / 22 / 18.  Twelve of the 84 say
    "next" or "coming up" about a record already turning or gone.

  * data/track_talk_queue.json is two bytes.  Not one introduction was
    prepared ahead; every one took the live road: the needle drops
    (talk_radio_mode forces records-first, #1155), THEN a model visit,
    a tint round and a render, THEN the wait for the floor - and the
    first place anything looked at the deck again was nowhere.  The
    words were written about record A and spoken over record B.

THE RULE.  A line the station writes about a record carries that record
as its `bound`, and the one door every single line passes through
(app.py `_dj_speak_floorless`) asks - at the last moment before the clip
is offered to a speaker, and once more before a live write is even
started - whether the record is where the line says it is:

    intro   on the deck, with enough of it left for the introduction to
            end before the record does; or next (`coming`, talk-first)
    outro   the record just gone (history[-1]), or ending now
    round   on the deck, or next

A line whose record is elsewhere is WITHDRAWN: a `withdrawn` row in the
feed carrying the reason, the words filed on the record's library seat
(#1061) so the next time it is cued the introduction is already written,
and nothing heard.  And when the record LEAVES the deck (a skip, or its
own end) every introduction still queued or sounding for it is cut with
it - the page is told which clips by id, not by epoch, so the queue
behind them stands.

THIS MODULE IS PURE, in the shape of track_talk_segment.py: no app.py,
no clock it is not handed, no store it is not given.  app.py holds the
wrappers that read _RADIO and the rings (`record_bound_*`).
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable, Mapping, Sequence

PART_INTRO = "intro"
PART_OUTRO = "outro"
PART_ROUND = "round"            # a dialogue round written about the record
PARTS = (PART_INTRO, PART_OUTRO, PART_ROUND)

# An introduction must END this long before its record does; an intro
# that outlives its record is the screenshot with a shorter delay.
INTRO_TAIL_S = float(os.getenv("PINE_RECORD_BOUND_TAIL_S", "15"))
# Measured (48 h): the median introduction that DID land on its record
# landed 128 s after the needle.  A live introduction started with less
# than this left is not started - the words would be spoken over the
# next record, which is the fault itself, and the model visit is the
# station's scarcest resource.
LIVE_INTRO_COST_S = float(os.getenv("PINE_RECORD_BOUND_LIVE_S", "120"))
# How long a cut id is offered to pages after the cut.
CUT_WINDOW_S = 120.0
# A published binding is only worth cutting for this long after it was
# offered; anything older has long finished sounding.
CUT_LOOKBACK_S = 600.0
RECENT_KEEP = 60
LINES_KEEP = 400


# --- identity -----------------------------------------------------------
def snapshot(track: Any) -> dict[str, Any]:
    """The stable identity a bound line carries: id, title, artist, seconds.

    {} for anything without an id, so `if bound:` is the whole guard."""
    row = track if isinstance(track, Mapping) else {}
    tid = str(row.get("id") or "").strip()
    if not tid:
        return {}
    out: dict[str, Any] = {"id": tid}
    for key in ("title", "artist"):
        val = " ".join(str(row.get(key) or "").split())[:160]
        if val:
            out[key] = val
    try:
        secs = float(row.get("seconds") or 0)
    except (TypeError, ValueError):
        secs = 0.0
    if secs > 0:
        out["seconds"] = round(secs, 1)
    return out


def label(bound: Any) -> str:
    """`Philip Glass - 6-I'm Going To Make A Cake`, as a person names it."""
    row = bound if isinstance(bound, Mapping) else {}
    title = " ".join(str(row.get("title") or "").split())
    artist = " ".join(str(row.get("artist") or "").split())
    if title and artist:
        return "%s - %s" % (artist, title)
    return title or artist or ("a record" if row.get("id") else "")


# --- the deck -----------------------------------------------------------
def deck(now: Any, started: float, coming: Any, history: Any, queue: Any,
         at: float) -> dict[str, Any]:
    """The deck as plain facts: what is on it and how far in, what is
    next, what has gone (oldest first, newest last - the order
    _RADIO["history"] is appended in), what is queued."""
    now_row = now if isinstance(now, Mapping) else {}
    now_id = str(now_row.get("id") or "")
    try:
        length = float(now_row.get("seconds") or 0)
    except (TypeError, ValueError):
        length = 0.0
    try:
        began = float(started or 0)
    except (TypeError, ValueError):
        began = 0.0
    elapsed = max(0.0, float(at) - began) if (now_id and began > 0) else 0.0
    coming_row = coming if isinstance(coming, Mapping) else {}
    hist: list[str] = []
    for row in (history if isinstance(history, Sequence) else []):
        if isinstance(row, Mapping) and str(row.get("id") or ""):
            hist.append(str(row.get("id")))
    line: list[str] = []
    for row in (queue if isinstance(queue, Sequence) else []):
        if isinstance(row, Mapping) and str(row.get("id") or ""):
            line.append(str(row.get("id")))
        if len(line) >= 60:
            break
    return {
        "at": float(at),
        "now_id": now_id, "now": snapshot(now_row),
        "elapsed": round(elapsed, 1), "length": round(length, 1),
        "coming_id": str(coming_row.get("id") or ""),
        "coming": snapshot(coming_row),
        "history_ids": hist, "queue_ids": line,
    }


# --- the rule -----------------------------------------------------------
def check(bound: Any, part: Any, deck_view: Mapping[str, Any],
          clip_seconds: float = 0.0, live: bool = False
          ) -> tuple[bool, str]:
    """May a line bound to this record go out NOW?  (ok, why).

    `clip_seconds` is the rendered length when it is known; `live` says
    the words have not been written yet, so the whole live road's cost
    stands between now and the first word."""
    row = bound if isinstance(bound, Mapping) else {}
    tid = str(row.get("id") or "")
    if not tid:
        return True, ""                     # nothing bound: the old station
    d = deck_view or {}
    now_id = str(d.get("now_id") or "")
    on_deck = bool(now_id) and now_id == tid
    is_next = str(d.get("coming_id") or "") == tid
    hist = [str(x) for x in (d.get("history_ids") or [])]
    gone = tid in hist
    on = label(d.get("now")) or "nothing"
    part = str(part or "").strip().lower() or PART_ROUND
    try:
        clip_s = max(0.0, float(clip_seconds or 0))
    except (TypeError, ValueError):
        clip_s = 0.0

    if part == PART_INTRO:
        if is_next:
            return True, "its record is next on the deck"
        if on_deck:
            length = float(d.get("length") or 0)
            elapsed = float(d.get("elapsed") or 0)
            if length > 0:
                left = length - elapsed
                need = (LIVE_INTRO_COST_S if live else clip_s) + INTRO_TAIL_S
                if left < need:
                    if live:
                        return False, ("its record has %.0fs left and a live "
                                       "introduction takes about %.0fs"
                                       % (left, LIVE_INTRO_COST_S))
                    return False, ("its record has %.0fs left - the "
                                   "introduction (%.0fs) would outlive it"
                                   % (left, clip_s))
            return True, "its record is on the deck, %.0fs in" % elapsed
        if gone:
            return False, ("its record has already played - the deck is on "
                           + on)
        queue_ids = [str(x) for x in (d.get("queue_ids") or [])]
        if tid in queue_ids:
            return False, ("its record is queued at %d but the deck is on %s"
                           % (queue_ids.index(tid) + 1, on))
        return False, "its record is not on the deck - %s is" % on

    if part == PART_OUTRO:
        just_gone = hist[-1] if hist else ""
        if just_gone == tid:
            return True, "its record has just gone"
        if on_deck:
            return True, "its record is ending"
        if gone:
            return False, ("its record went more than one record ago - "
                           "the send-off is stale")
        return False, "its record has not played - there is nothing to send off"

    # a round written about the record
    if on_deck:
        return True, "its record is on the deck"
    if is_next:
        return True, "its record is next"
    if gone:
        return False, "its record has already played - the deck is on " + on
    return False, "its record is not on the deck - %s is" % on


# --- the paperwork ------------------------------------------------------
def verdict_row(at: float, line_id: str, bound: Any, part: Any, ok: bool,
                why: str, stage: str, who: str = "", text: str = ""
                ) -> dict[str, Any]:
    """One verdict, as the desk and the log keep it."""
    name = label(bound)
    part = str(part or "line")
    return {
        "at": round(float(at), 3),
        "clock": time.strftime("%H:%M:%S", time.gmtime(float(at))),
        "line_id": str(line_id or ""),
        "bound": snapshot(bound), "part": part,
        "ok": bool(ok), "why": str(why or "")[:240],
        "stage": str(stage or ""), "who": str(who or ""),
        "text": " ".join(str(text or "").split())[:200],
        "say": "%s for %s: %s - %s" % (
            part, name or "a record",
            "airs" if ok else ("cut" if stage == "cut" else "withdrawn"),
            str(why or "")[:160]),
    }


def cut_ids(bound_lines: Mapping[str, Mapping[str, Any]], track_id: str,
            at: float, parts: Sequence[str] = (PART_INTRO, PART_ROUND)
            ) -> list[str]:
    """Which published line ids die with this record: the introductions
    and rounds bound to it, published recently, not already cut.  A
    send-off is meant to follow its record and is never cut by it."""
    tid = str(track_id or "")
    if not tid:
        return []
    out: list[str] = []
    for line_id, row in (bound_lines or {}).items():
        if not isinstance(row, Mapping):
            continue
        if str(row.get("id") or "") != tid:
            continue
        if str(row.get("part") or PART_ROUND) not in parts:
            continue
        if row.get("cut_at"):
            continue
        try:
            when = float(row.get("at") or 0)
        except (TypeError, ValueError):
            when = 0.0
        if when and float(at) - when > CUT_LOOKBACK_S:
            continue
        out.append(str(line_id))
    return out


def fresh_cuts(cuts: Sequence[Mapping[str, Any]], at: float) -> list[str]:
    """The row ids a page should still be told about."""
    out: list[str] = []
    for row in cuts or []:
        if not isinstance(row, Mapping):
            continue
        try:
            when = float(row.get("at") or 0)
        except (TypeError, ValueError):
            when = 0.0
        rid = str(row.get("row_id") or "")
        if rid and float(at) - when <= CUT_WINDOW_S and rid not in out:
            out.append(rid)
    return out


# --- the sequencer's hook (c) ---------------------------------------------
def _line_ids_of(block: Any, ledger: Callable[[], Sequence[Mapping[str, Any]]]
                 ) -> list[str]:
    """Line ids of one script-ledger block number, in ledger order."""
    try:
        want = int(block)
    except (TypeError, ValueError):
        return []
    rows = [r for r in (ledger() or [])
            if isinstance(r, Mapping) and int(r.get("block") or -1) == want]
    rows.sort(key=lambda r: int(r.get("ord") or 0))
    return [str(r.get("line_id") or "") for r in rows if r.get("line_id")]


def resolve(block: Any, ledger: Callable[[], Sequence[Mapping[str, Any]]],
            lookup: Callable[[str], Mapping[str, Any] | None],
            track_of: Callable[[str], Mapping[str, Any] | None] | None = None
            ) -> dict[str, Any] | None:
    """The record a script block must play with, or None.

    `block` may be a block number, a ledger/inspector row, a screenplay
    element, or a dict carrying `bound`, `line_ids`, `lines`, `rows`,
    `id` or `block`.  `lookup(line_id)` answers with the binding the
    station published for that line; `track_of(track_id)` answers a
    library row for a record named by id (an `ac-rec-<id>` action).

    The answer carries `part`, `line_id` and `why` beside the record."""
    if block is None:
        return None
    line_ids: list[str] = []
    record_ids: list[str] = []
    direct: Mapping[str, Any] | None = None

    def _take_id(value: Any) -> None:
        sid = str(value or "")
        if not sid:
            return
        if sid.startswith("ac-rec-"):
            record_ids.append(sid[len("ac-rec-"):])
        elif sid.startswith("ln-"):
            line_ids.append(sid[len("ln-"):])
        else:
            line_ids.append(sid)

    if isinstance(block, Mapping):
        if isinstance(block.get("bound"), Mapping) and block["bound"].get("id"):
            direct = block["bound"]
        for key in ("line_id", "id", "element_id"):
            if block.get(key):
                _take_id(block.get(key))
        for key in ("line_ids", "ids"):
            for value in (block.get(key) or []):
                _take_id(value)
        for key in ("lines", "rows", "elements"):
            for row in (block.get(key) or []):
                if isinstance(row, Mapping):
                    if isinstance(row.get("bound"), Mapping) and row["bound"].get("id"):
                        direct = direct or row["bound"]
                    _take_id(row.get("line_id") or row.get("id"))
        if block.get("block") is not None:
            line_ids.extend(_line_ids_of(block.get("block"), ledger))
    else:
        text = str(block)
        if text.isdigit():
            line_ids.extend(_line_ids_of(text, ledger))
        else:
            _take_id(text)

    if direct:
        out = snapshot(direct)
        out.update({"part": str(direct.get("part") or ""),
                    "line_id": "", "why": "the block carries its binding"})
        return out
    seen: set[str] = set()
    for line_id in line_ids:
        if not line_id or line_id in seen:
            continue
        seen.add(line_id)
        try:
            got = lookup(line_id)
        except Exception:  # noqa: BLE001
            got = None
        if isinstance(got, Mapping) and got.get("id"):
            out = snapshot(got)
            out.update({"part": str(got.get("part") or ""),
                        "line_id": line_id,
                        "why": "line %s was published bound to it" % line_id})
            return out
    for rid in record_ids:
        row = None
        if track_of is not None:
            try:
                row = track_of(rid)
            except Exception:  # noqa: BLE001
                row = None
        out = snapshot(row if isinstance(row, Mapping) else {"id": rid})
        out.update({"part": "record", "line_id": "",
                    "why": "the block's record action names it"})
        return out
    return None


def say(mode_line: str, counts: Mapping[str, Any]) -> str:
    """One sentence for the desk."""
    return ("%s - %d aired with their record, %d withdrawn, %d cut with a "
            "record that left the deck" % (
                mode_line, int(counts.get("aired") or 0),
                int(counts.get("withdrawn") or 0),
                int(counts.get("cut") or 0)))

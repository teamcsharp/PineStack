# -*- coding: utf-8 -*-
"""#1179: a record's talk, on the hour's sheet, made, identified and played.

The operator, at the production board, twice, photographing the same row:

    "make sure that this is scheduled to be resolved by the orchestrator.
    Make sure this is put in an hourly segment and it is made, id'd and
    given play."

"This" is `track_talk` - the host's introduction BEFORE a record and the
co-host's send-off AFTER it - reading `0w . 0/0L . 0 ready` on the board
while every other road produces.

WHAT #1177 ALREADY SETTLED, so this does not re-derive it.  Wanting is
expressed in one currency, `commitment_write_needed`, fed by the RUNNING
ORDER; `track_talk` rides a `record` entry; a `record` entry is in
CANNOT_PREPARE and is skipped before a road is derived from it; so the
sheet never named the road and its writer was never called.  #1177 gave
the road a second way to ask - its own shelf - behind
`data/event_roads_prepare`, which is ON.  Station IDs began producing
immediately.  Record talk did not.

WHAT WAS MEASURED ON THE LIVE STATION, 2026-09-15, BEFORE ANY OF THIS WAS
WRITTEN.  Four facts, each of which decided one line below.

1. THE SHEET DOES NOT NAME IT, AND THE SHEET COULD.  `track_talk` has
   been a first-class schedule kind since #1089 - it is in SCHEDULE_KINDS
   ("Talk over the record"), in SCHED_PREP_KIND, in ALT_PREP_KINDS, out of
   CANNOT_PREPARE, and coord_upcoming has carried a `road == "track_talk"`
   branch that measures one queued record with two bookends as ONE
   covered entry.  All of it works.  It is simply never reached, because
   `data/schedule.json` has `active: "canonical hour (fits the engine)"`,
   and that preset - unlike the plain "canonical hour" beside it, which
   carries one - has NO track_talk entry at all.  What it does carry is
   two `record` entries an hour: "Spin record (start)" and "Repeat (end)".
   So the road the operator is looking at is the road his own sheet drops.

   Hence: A RECORD ENTRY OWES ITS BOOKENDS.  Not a new schedule kind - a
   new kind would have to be typed into every preset by hand, and "have
   the orchestrator resolve it" is the opposite of that.  The `record`
   entry is exactly the entry a record's talk rides, it is already on
   every sheet, and the road it derives to is already fully plumbed.  The
   record itself is still not written ahead; it is still the needle
   dropping.  The TALK OVER IT is what the entry owes.

2. THE WINDOW IS NOT THE LEVER; THE RESERVE IS.  The station's own
   explanation of the refusal was "it measures about 160s on this box and
   the window open right now allows 22s".  Both numbers are real and
   neither can be fixed by writing a shorter line:

       the 160s is task_cost("track_talk"), the p90 of the last sixty
       samples in data/task_costs.json - a ledger whose newest track_talk
       sample is SEVENTY-SIX HOURS old and in which 1,728 of 1,964
       lifetime attempts failed.  It is a stale price taken off a road
       that was mostly failing.

       priced instead by its parts, from the same ledger: one model visit
       (`write`, mean 49.6s), one tint round (`tint:round`, mean 81.3s),
       one rendered line (`render_line`, mean 58.7s) = about 190s.  The
       p90s sum to 311s.  So 160s is, if anything, generous.

       of that, only the RENDER scales with words.  Measured over 19,208
       air-log rows carrying both text and audio, a line runs
       4.06 + 0.2621 x words seconds.  The intros this station has
       written run 39 words median - 14.3s of audio.  Cutting a send-off
       to twelve-to-thirty-two words saves about six seconds of audio and
       leaves the model visit and the tint round exactly where they were.

   So a part cannot be made to fit an 82s window by being smaller, and the
   station already knows what to do about that: prep_deadline_pick, whose
   docstring says it in as many words - "the budget exists to stop long
   work crowding out short work, and it has no business refusing the one
   piece of work the clock has already ordered" - measures a deadline
   pick against the RESERVE (23,516s banked tonight) and against a real
   window merely being OPEN, not against the budget.  The gallery road,
   at 256s, is carried by exactly this.

   Which means NAMING IT ON THE SHEET IS WHAT GIVES IT ROOM.  There is no
   second mechanism to build.  An uncovered entry with a road is a
   deadline; a deadline outranks the ledger.  The one thing this module
   adds on top is a smaller brief for the send-off, because the render is
   the step that fails when the engine is full and a ten-second clip
   clears a window a twenty-second clip does not.

3. NOTHING THE PAIR SAY ABOUT A RECORD HAS EVER HAD AN IDENTITY.  Over
   48.6 hours of data/air_log.jsonl: 140 rows of kind `intro`, of which
   140 carry NO sid; 3,386 rows of kind `interject`, of which 3,354 carry
   no sid (the 32 that do are #1170's dead-air fills, landed tonight).  A
   record's introduction belongs to no segment, names no record, and
   cannot be joined to the send-off that answers it.  So the modifier road
   this station gained tonight is reused exactly as it stands: the part
   gets `talk:<track>.<intro|outro>` through station_modifiers.KIND_TALK,
   the part gets a sid, the id RIDES that sid through ModifierBook.ride,
   and airlog_row_from and script_ledger_commit already stamp
   modifiers_for_sid(sid) onto every row they write.  One book, one join,
   no second ledger.

4. THE SEND-OFF'S ABSENCE IS THE SHELF - AND THE METER COULD NEVER HAVE
   SEEN IT ANYWAY.  The air path DOES ask: _record_talk_body calls
   track_talk_get(_gone, "outro", take=True) on the record just gone, and
   speaks it in the co-host's voice.  That road is live and correct.  What
   is under it is empty - the last prepared part on this station is 76
   hours old and data/track_talk_queue.json is two bytes.  But "not one
   send-off has ever aired" was never provable either way, because the
   send-off goes out through dj_speak("interject", ...) with no kind of
   its own, no sid and no track: it is 1 row in a bucket of 3,386.  A
   claim that cannot fail is not a measurement (see
   docs/notes/a-meter-that-cannot-fail.md).  Giving the part an id is what
   makes the claim answerable, in either direction, from tomorrow.

   Two things do keep the shelf empty for send-offs specifically, and both
   are here:

   (a) prep_track_talk takes parts in the order ("intro", "outro"), and
       the intro is the half that ALREADY has a live fallback - an
       expensive one, 50.4s of dead air per airing, but a fallback.  The
       send-off has none at all.  Whichever part the one affordable visit
       goes to is the part that exists, so it should be the one that
       cannot otherwise happen.  THE SEND-OFF IS WRITTEN FIRST.

   (b) _track_talk_prune keeps the record that is `now` - "its send-off
       has not aired yet" - and the record that is `coming`, and the
       queue.  The record whose send-off is actually about to be asked
       for is none of those three: by the time _record_talk_body asks,
       the needle is down on the NEXT record and the one being sent off
       is in _RADIO["history"].  So the row holding a finished send-off
       can be swept in the seconds between it being owed and it being
       asked for.  THE RECORD JUST GONE IS KEPT.

THIS MODULE IS PURE.  No app.py, no FastAPI, no clock it is not handed, no
store it is not given.  Everything that touches the live station lives in
the caller, which is how station_modifiers is built and for the same
reason: this is testable off a temp directory and the station is on air.

BEHIND A SWITCH, DEFAULTING OFF.  `<data>/record_talk/mode`, one word,
re-read every few seconds, no restart - the shape of
`data/modifiers/mode`, `data/event_roads_prepare` and
`data/manager_calls_in`.  With it off, every derivation here is the
identity function and the station is exactly what it is tonight.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import station_modifiers

# --- the switch -----------------------------------------------------------
# Three words, so "give it an identity" and "change the running order" are
# separate decisions.  An operator who wants to watch before he commits can
# sit at `trace` for a day and lose nothing.
MODE_OFF = "off"        # nothing at all: the station of 2026-09-15
MODE_TRACE = "trace"    # the parts get ids and the ids ride the ledger and
                        # the air log.  THE SHEET AND THE AIR ARE UNCHANGED.
MODE_AIR = "air"        # trace, and: a record entry owes its bookends, the
                        # send-off is written first, the send-off's record
                        # survives long enough to be asked for, and the
                        # send-off brief is cut to one or two lines.
MODES = (MODE_OFF, MODE_TRACE, MODE_AIR)

ENV_NAME = "SPARK_AGENT_RECORD_TALK"

PART_INTRO = "intro"
PART_OUTRO = "outro"
PARTS = (PART_INTRO, PART_OUTRO)

# The schedule entry kinds that carry a record and therefore owe a talk.
# `record` is the only one today; it is a tuple so a station that grows a
# second record-shaped entry does not need this reasoning repeated.
RECORD_ENTRY_KINDS = ("record",)

# The road a record entry's talk derives to.  Not a new road - the one that
# has been in SCHED_PREP_KIND since #1089 and that coord_upcoming already
# knows how to measure.
TALK_ROAD = "track_talk"

# What a record entry says on the board once it owes its bookends.  It
# replaces CANNOT_PREPARE["record"], which is still true of the RECORD and
# is no longer true of the entry.
OWES_TALK_SAYS = ("the needle still just drops - but the pair talk it in "
                  "and out, and those two links are written ahead")

# --- what a part costs, measured ------------------------------------------
# Least squares over 19,208 rows of data/air_log.jsonl carrying both text
# and a measured duration, 2026-09-15.  Used to SIZE a brief, never to
# promise a duration: the engine owns that.
AUDIO_BASE_S = 4.06
AUDIO_PER_WORD_S = 0.2621

# The writer's brief, in words.  The intro is what this station has always
# written and is left alone at 12-70 (track_talk_text_report refuses under
# twelve and over ninety, so both ends stay inside its contract).  The
# send-off is the operator's "one or two lines".
BRIEF_WORDS = {
    PART_INTRO: (12, 70),
    PART_OUTRO: (12, 32),
}

# One part, priced by the steps it really runs, from data/task_costs.json
# on this box: one model visit + one tint round + one rendered line.
# Means, not p90s - the p90s sum to 311s and describe the bad night, and
# this number's only job is to be an honest expectation.
PART_STEP_COST_S = {
    "write": 49.6,
    "tint": 81.3,
    "render": 58.7,
}

# What the deadline planner insists on before it starts anything at all
# (app.py PREP_DEADLINE_FLOOR).  Mirrored, not imported: this module does
# not import app.py, and a test that cannot state the rule cannot check it.
DEADLINE_FLOOR_S = 20.0

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def parse_mode(text: Any) -> str:
    """One word into a mode.  Anything else at all is OFF.

    An operator's typo must never read as permission, and ONE WORD MEANS
    ONE WORD: a file holding a sentence is off, however promising a word
    inside it looks.  station_modifiers.parse_mode scans for a word it
    knows anywhere in the text, and under that rule a switch file reading
    "ON AIR PLEASE" turns the running order on - which is a switch an
    operator can throw by leaving himself a note.  This one changes what
    the hour's sheet owes, so it is the strict version.

    "on" is read as `air`, because that is plainly what somebody typing it
    meant and because the two switches beside this one are spelled exactly
    that way."""
    words = str(text or "").replace(",", " ").split()
    if len(words) != 1:
        return MODE_OFF
    low = words[0].strip().lower()
    if low in MODES:
        return low
    return MODE_AIR if low == "on" else MODE_OFF


class TalkSwitch:
    """`<data>/record_talk/mode`, re-read at most every `ttl` seconds.

    DEFAULTS OFF.  Missing file, empty file, unreadable file, a word this
    does not know, a file being rewritten underneath us: off, every time.
    A station that reads a half-written switch as "on" is a station that
    changed its running order because somebody's editor flushed early."""

    def __init__(self, root: str | Path,
                 env: Mapping[str, str] | None = None,
                 ttl: float = 3.0,
                 clock: Callable[[], float] = time.time):
        self.root = Path(root)
        self.path = self.root / "mode"
        self.ttl = float(ttl)
        self.clock = clock
        self._env = dict(os.environ if env is None else env)
        self._read_at = 0.0
        self._cached = MODE_OFF

    def _text(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8", errors="replace").strip()
        except (OSError, ValueError):
            return ""

    def mode(self) -> str:
        now = float(self.clock())
        if self._read_at and (now - self._read_at) < self.ttl:
            return self._cached
        text = self._text()
        if not text:
            text = str(self._env.get(ENV_NAME, "")).strip()
        self._read_at = now
        self._cached = parse_mode(text)
        return self._cached

    def traces(self) -> bool:
        """Do the parts get ids that ride?  Changes nothing that airs."""
        return self.mode() in (MODE_TRACE, MODE_AIR)

    def airs(self) -> bool:
        """Does the sheet owe a talk, and does the send-off come first?"""
        return self.mode() == MODE_AIR

    def write(self, text: str) -> None:
        """Tests and operator tools only; never the station itself."""
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + "." + uuid.uuid4().hex + ".tmp")
        tmp.write_text(str(text).strip() + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
        self._read_at = 0.0


# --- 1. THE SHEET: a record entry owes its bookends -----------------------
def entry_owes_talk(kind: Any, mode: str) -> bool:
    """Is this schedule entry one that carries a record and owes a talk?"""
    return bool(mode == MODE_AIR
                and str(kind or "") in RECORD_ENTRY_KINDS)


def entry_demand(kind: Any, road: Any, cannot: Any,
                 mode: str) -> tuple[str, str]:
    """(road, cannot) for one schedule entry, after the switch has spoken.

    THE WHOLE OF THE SHEET CHANGE, and deliberately a two-line function:
    every reader that decides whether an entry expresses demand -
    coord_upcoming, schedule_demand_entries, commitment_inventory_plan
    through them, and the hour view the operator is looking at - reads the
    entry's ROAD and its CANNOT, and nothing else.  Give a record entry the
    road its talk already has and clear the refusal that was about the
    record rather than about the talk, and every one of them names it,
    prices it and owes seconds for it with no further wiring.

    Off, or for any entry that is not a record: the arguments back
    unchanged, which is what "the switch off changes nothing" means here."""
    road_s = str(road or "")
    cannot_s = str(cannot or "")
    if not entry_owes_talk(kind, mode):
        return (road_s, cannot_s)
    return (TALK_ROAD, "")


def entry_note(kind: Any, mode: str) -> str:
    """What the board should say about a record entry that owes a talk.

    Empty when nothing changed, so a caller can append it without asking
    whether it applies."""
    return OWES_TALK_SAYS if entry_owes_talk(kind, mode) else ""


# --- 2. THE SIZE: what one part really costs ------------------------------
def brief_words(part: Any, mode: str) -> tuple[int, int]:
    """The word range the writer is given for this part.

    Off, both parts get the brief this station has always written to, so
    the prompt is byte-identical to today's."""
    if mode != MODE_AIR:
        return BRIEF_WORDS[PART_INTRO]
    return BRIEF_WORDS.get(str(part or ""), BRIEF_WORDS[PART_INTRO])


def brief_sentence(part: Any, mode: str) -> str:
    """The brief as the one clause that goes into the writing prompt."""
    low, high = brief_words(part, mode)
    if str(part or "") == PART_OUTRO and mode == MODE_AIR:
        return ("Use 1 to 2 natural spoken sentences and %d to %d words."
                % (low, high))
    return ("Use 2 to 4 natural spoken sentences and %d to %d words."
            % (low, high))


def expected_audio_s(words: float) -> float:
    """How long that many words runs on this box, measured (see the head)."""
    try:
        return round(AUDIO_BASE_S + AUDIO_PER_WORD_S * max(0.0, float(words)), 2)
    except (TypeError, ValueError):
        return AUDIO_BASE_S


def part_cost_s(part: Any, mode: str, tinted: bool = True) -> float:
    """What ONE part is expected to cost the room, priced by its steps.

    Not the road's ledger p90: that number is 160.2s taken off sixty
    samples whose newest is seventy-six hours old and among which the
    lifetime failure rate is 88%.  This is write + tint + render, with the
    render scaled to the part's own brief against the measured
    seconds-per-word - which is the only one of the three steps that a
    shorter line makes cheaper, and the reason a smaller send-off saves
    single-figure seconds rather than the hundred it would need to fit a
    record's window."""
    low, high = brief_words(part, mode)
    words = (low + high) / 2.0
    render = PART_STEP_COST_S["render"] * (
        expected_audio_s(words) / max(1.0, expected_audio_s(
            sum(BRIEF_WORDS[PART_INTRO]) / 2.0)))
    cost = PART_STEP_COST_S["write"] + render
    if tinted:
        cost += PART_STEP_COST_S["tint"]
    return round(cost, 1)


def fits_window(cost: float, room: float) -> bool:
    """The ledger's own rule: one task may not outlast the window it starts
    in.  True is the ordinary, efficient path."""
    try:
        return float(cost) <= float(room)
    except (TypeError, ValueError):
        return False


def reachable_on_deadline(cost: float, cover: float, room: float) -> bool:
    """prep_deadline_pick's rule, stated where a test can reach it.

    A deadline pick is measured against the RESERVE and against a window
    merely being OPEN - never against the budget - because a round is not
    lost when its window closes: prep_render_line keeps every line it
    finished and the next pass comes back for the rest (#904).  This is how
    the gallery road, at 256s, is built at all, and it is how a record's
    talk is built now that the sheet names it."""
    try:
        return (float(room) >= DEADLINE_FLOOR_S
                and float(cost) <= max(0.0, float(cover)))
    except (TypeError, ValueError):
        return False


def sizing(part: Any, mode: str, room: float, cover: float,
           tinted: bool = True) -> dict[str, Any]:
    """One part, priced and placed, as the board would read it."""
    low, high = brief_words(part, mode)
    cost = part_cost_s(part, mode, tinted)
    return {
        "part": str(part or ""),
        "words": [low, high],
        "audio_seconds": expected_audio_s((low + high) / 2.0),
        "cost_seconds": cost,
        "room_seconds": round(float(room or 0), 1),
        "cover_seconds": round(float(cover or 0), 1),
        "fits_window": fits_window(cost, room),
        "reachable": reachable_on_deadline(cost, cover, room),
        "why": ("it fits the window that is open"
                if fits_window(cost, room) else
                "it does not fit this window and does not need to - the "
                "entry that owes it is a deadline, and a deadline is "
                "measured against the reserve (#957)"
                if reachable_on_deadline(cost, cover, room) else
                "no window is open wide enough to start anything, or the "
                "reserve would run dry before it finished"),
    }


# --- 3. THE ID ------------------------------------------------------------
def part_key(track_id: Any, part: Any) -> str:
    """`2628d48b9a11e3fd.outro` - the record's own id and the half.

    DERIVED, so the same record's send-off is the same key every time it
    is written, filed, taken and aired.  Nothing is minted: the music
    store's track id stays the truth about which record this is, exactly
    as guests.json stays the truth about a guest (#1169)."""
    tid = _SAFE.sub("-", str(track_id or "").strip())[:40]
    low = str(part or "").strip().lower()
    if not tid or low not in PARTS:
        return ""
    return "%s.%s" % (tid, low)


def part_id(track_id: Any, part: Any) -> str:
    """`talk:2628d48b9a11e3fd.outro`.

    A station_modifiers id, through station_modifiers.modifier_id, so it
    passes is_modifier_id() and therefore rides through the book, the
    rides file, modifiers_for_sid(), the air-log row's `mods` and the
    script ledger row's `mods` with no new plumbing anywhere."""
    key = part_key(track_id, part)
    if not key:
        return ""
    return station_modifiers.modifier_id(station_modifiers.KIND_TALK, key)


def split_part_id(pid: Any) -> tuple[str, str]:
    """`talk:2628d48b.outro` -> ("2628d48b", "outro").  ("","") if it is not
    one - so a reader can join the air log back to the record without
    trusting the string it was handed."""
    kind, key = station_modifiers.split_id(pid)
    if kind != station_modifiers.KIND_TALK or "." not in key:
        return ("", "")
    tid, _, low = key.rpartition(".")
    if low not in PARTS or not tid:
        return ("", "")
    return (tid, low)


def part_name(track: Mapping[str, Any] | None, part: Any) -> str:
    """The part as a person would name it, for the book and the inspector.

    No id in it - #1169's standing rule, and the reason record_says has the
    same one: a presenter who reads `talk: 2628d48b.outro` out loud has
    said the quiet part."""
    row = track or {}
    title = " ".join(str(row.get("title") or "").split())[:80]
    artist = " ".join(str(row.get("artist") or "").split())[:60]
    if title and artist:
        what = "%s by %s" % (title, artist)
    else:
        what = title or artist or "a record"
    return ("the send-off after %s" if str(part or "") == PART_OUTRO
            else "the introduction to %s") % what


def part_sid(track_id: Any, part: Any, at: float) -> str:
    """The segment id this part airs under.

    Derived from the record, the half and the second it went out, so the
    same airing is the same sid however many times the ride is recorded -
    ModifierBook.ride is idempotent per sid and this is what makes that
    property reachable.  A different airing of the same record is a
    different segment, which is correct: the trace is of what was HEARD,
    and #1239 is the reason those are different questions."""
    key = part_key(track_id, part)
    if not key:
        return ""
    try:
        stamp = int(float(at))
    except (TypeError, ValueError):
        stamp = 0
    seed = "%s|%d" % (key, stamp)
    return "tt-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]


def part_stamp(track: Mapping[str, Any] | None, part: Any, at: float,
               mode: str) -> dict[str, Any]:
    """What gets written onto the prepared part when it is made.

    Empty off, so a side dict written with the switch off is byte-identical
    to one written today and nothing downstream has to know this module
    exists.  The stamp persists for free: track_talk_save writes the whole
    side to data/track_talk_queue.json, and track_read_keep files the whole
    side into data/track_reads.json, so the id survives a deploy and
    survives the record coming round again."""
    if mode == MODE_OFF:
        return {}
    tid = str((track or {}).get("id") or "")
    pid = part_id(tid, part)
    if not pid:
        return {}
    return {"talk_id": pid,
            "talk_key": part_key(tid, part),
            "talk_track": tid,
            "talk_part": str(part or ""),
            "talk_at": round(float(at), 3)}


def ride_plan(track: Mapping[str, Any] | None, part: Any, at: float,
              mode: str, held: Mapping[str, Any] | None = None
              ) -> dict[str, Any]:
    """Everything the air path needs to identify one part it is about to
    say, in one call: the id, the sid, the name and the stand.

    `held` is the prepared side, if there is one - a part that was written
    ahead carries its own id from part_stamp and that id is used, so the
    thing that was made and the thing that aired are provably the same
    thing.  A part written live has no stamp and gets the derived id, which
    is the same string anyway: that is the point of deriving it.

    {} when the switch is off, so the caller's `if not plan:` is the whole
    of its guard."""
    if mode == MODE_OFF:
        return {}
    tid = str((track or {}).get("id") or "")
    pid = str((held or {}).get("talk_id") or "") or part_id(tid, part)
    if not pid:
        return {}
    sid = part_sid(tid, part, at)
    if not sid:
        return {}
    return {
        "id": pid,
        "sid": sid,
        "kind": station_modifiers.KIND_TALK,
        "key": part_key(tid, part),
        "track": tid,
        "part": str(part or ""),
        "name": part_name(track, part),
        "prepared": bool((held or {}).get("talk_id")),
        # A record on the deck is "what is going on" for as long as it is
        # turning and no longer.  Its own length when the store knows it,
        # a short default when it does not.  The stand is what stops a
        # record from colouring an hour it has left.
        "stands_s": _stands_for(track),
        "source": "track_talk",
    }


def _stands_for(track: Mapping[str, Any] | None) -> float:
    try:
        secs = float((track or {}).get("seconds") or 0)
    except (TypeError, ValueError):
        secs = 0.0
    if secs <= 0:
        return 240.0
    return round(min(900.0, max(60.0, secs + 60.0)), 1)


# --- 4. THE SEND-OFF ------------------------------------------------------
def part_order(mode: str) -> tuple[str, ...]:
    """Which half the one affordable visit should go to.

    Off: ("intro", "outro"), the order prep_track_talk has always used.

    On: THE SEND-OFF FIRST.  The intro has a live fallback on the air path
    and the send-off has none, so whichever half the visit reaches is the
    half that exists - and it should be the half that cannot otherwise
    happen.  The cost of being wrong about this is exactly the station of
    tonight: an introduction written live over the record's opening, which
    is what the 50.4s-per-airing dead-air figure is made of, and which
    still happens either way until both halves are banked."""
    return (PART_OUTRO, PART_INTRO) if mode == MODE_AIR else PARTS


def keep_just_gone(mode: str) -> bool:
    """Should the sweep keep the record whose send-off has not aired yet?

    _track_talk_prune keeps `now` and `coming` and the queue.  By the time
    the air path asks for a send-off the needle is down on the NEXT record,
    so the record being sent off is in none of those three and a sweep
    landing in that gap destroys a finished, paid-for part one moment
    before it is owed.  Behind the switch because it changes what is on the
    shelf, and a shelf is a thing that airs."""
    return mode == MODE_AIR


def prune_allow(allowed: Sequence[str] | set[str], history: Sequence[Any],
                mode: str) -> set[str]:
    """`allowed` plus the record just gone, when the switch says so.

    `history` is _RADIO["history"], oldest first - dj_on_air appends the
    record being replaced, so the LAST entry is the one whose send-off is
    owed.  Two are kept, not one: under records-first the needle is down on
    the new record before its segment task runs, and a skip can put a third
    record's worth of history between the two."""
    out = {str(x) for x in (allowed or ()) if str(x)}
    if not keep_just_gone(mode):
        return out
    for row in list(history or ())[-2:]:
        tid = str((row or {}).get("id") or "") if isinstance(row, Mapping) else ""
        if tid:
            out.add(tid)
    return out


# --- what the board says --------------------------------------------------
def board_say(mode: str, road_report: Mapping[str, Any] | None = None
              ) -> str:
    """One sentence for the road report, so the operator can read the state
    of this from the same panel he photographed."""
    rep = road_report or {}
    if mode == MODE_OFF:
        return ("A record's talk is not on the hour's sheet: a record entry "
                "is live-only, so nothing owes it seconds and its writer is "
                "never called (#1179 is off).")
    owed = float(rep.get("owed_seconds") or 0)
    rows = int(rep.get("rows") or 0)
    if mode == MODE_TRACE:
        return ("A record's talk is being IDENTIFIED but not yet scheduled: "
                "every part written or said gets an id that rides the ledger "
                "and the air log, and the running order is unchanged.")
    return ("A record's talk is on the hour's sheet: every record entry owes "
            "its two bookends, the send-off is written first because it has "
            "no live fallback, and each part carries an id into the ledger "
            "and the air log. The sheet owes it %ds with %d prepared."
            % (int(owed), rows))


# ==========================================================================
# #1179b: THE SAME PRINCIPLE, STATED GENERALLY - WORK THE RECORDING ROOM
# FINISHES IS SCHEDULED INTO AN HOUR AND REACHES THE AIR, OR THE STATION
# SAYS WHICH STEP IT IS STUCK AT.
#
# The operator, at the retirement desk ("0 waiting, 459 in the cupboard,
# larder cap 84 + repertoire 160" and a button reading "Resume recording
# the incomplete ones - 134 incomplete, 6 in the room, 10 line(s) owed"):
#
#     "When I resume the recording room for these clips, that means that I
#     also want them to be scheduled by the orchestrator into hourly
#     segments and be ran. So make sure that the orchestrator is keeping
#     track of these elements behind the scenes and making sure that they
#     make it to the air."
#
# A record's intro and send-off are one instance of this.  The 134
# incomplete rounds are another.  The 131 finished rounds in the cupboard
# that have never been heard - 42 of them past the two hours the dial
# allows, the oldest waiting over two days - are a third.
#
# WHAT "RESUME RECORDING" ACTUALLY DOES TODAY, read rather than assumed.
# POST /api/cupboard/finish walks cupboard_incomplete_rows() and calls
# cupboard_finish_add() for each, which clears `off_brief` and `yielded`
# and appends the row's id to a bounded list in data/cupboard_finish.json.
# It queues an id; it moves nothing.  pantry_keeper unions those ids into
# its unready-commitment set so the recording room is ALLOWED to see rows
# the four-hour desk has stopped naming, works through them, and
# cupboard_finish_sweep() drops each id the moment cupboard_row_complete()
# goes true - logging "a round the operator sent back to the recording
# room is finished".
#
# And that is the end of the road.  The row was never anywhere but its own
# shelf; the only change is that it now has audio.  From that moment it is
# indistinguishable from the other 458 rows in the cupboard.  The one
# selector that reaches air, _ready_shelf_row(), takes the head of its
# road's queue and reads no commitment id at all - commitment_inventory_plan
# does carry the row's id in `selected_ids`, but the plan is an accounting
# simulation and no playout function has ever read it.
#
# THE MISSING LINK, NAMED.  cupboard_finish_sweep() already detects the
# completion and already logs it, and does not set `cue_at`.  `cue_at` is
# the one durable per-row mark meaning A PERSON ASKED FOR THIS: written
# onto the row so it survives a save, a restart and a reorder, and read
# FIRST and WITH NO DIAL by unheard_pick(), on every road - not only the
# four in RESCUE_ROADS_OPEN, and not only after the two-hour wait.  The
# finish road and the cue road have simply never been connected.  So:
# FINISHING A ROUND THE OPERATOR RESUMED CUES IT.  That is the whole of
# the change, it is one assignment, and it is the operator's own sentence
# turned into code - "resume recording" and "and be ran" are one action.
#
# WHAT THIS CANNOT HONESTLY CLOSE TONIGHT, said plainly rather than
# half-built.  An aired line cannot be joined back to the cupboard row it
# came from.  The row carries `sid` = alt_sid = retire_id
# ("gallery-ea62b25956"); _speak_turns mints a FRESH uuid4().hex[:12] at
# app.py:84188 and that is what lands in data/script_ledger.jsonl and
# data/air_log.jsonl.  Checked: not one road-prefixed cupboard id occurs
# anywhere in four thousand rows of the air log.  The only breadcrumb is
# `row["used_by"]`, written onto the cupboard row at hand-over and naming
# the slot and the hour - which runs the wrong way and survives only for
# the four SHELF_REUSABLE roads.  So follow_row() answers from the
# CUPBOARD side, where the facts actually are, and says which join it is
# using; the one-line cure that would make the air log answer it too is
# named in the report and is not shipped unmeasured on a live station.
# ==========================================================================

# The follow road's own switch: `<data>/finished_work/mode`, same three
# words, same default.  Separate from the record-talk switch on purpose -
# reading a desk and changing a running order are different risks, and an
# operator should be able to take the first without the second.
FOLLOW_ENV_NAME = "SPARK_AGENT_FINISHED_WORK"

# The steps a finished item passes through on its way to the air, in
# order.  The step it is STUCK at is the first one it has not passed.
FOLLOW_STEPS = ("written", "recorded", "resumed", "cued", "owed", "aired")

FOLLOW_SAYS = {
    "written": "it is written and the recording room has not finished it",
    "recorded": "it is finished radio and nothing has asked for it",
    "resumed": "the operator sent it back to the recording room and it is "
               "still being made",
    "cued": "it is finished and cued, waiting for the next gap the standing "
            "consumer walks into",
    "owed": "the running order owes its road seconds and it is bound to an "
            "entry that has not come round yet",
    "aired": "it went out",
}


class FollowSwitch(TalkSwitch):
    """`<data>/finished_work/mode`.  off | trace | air.

    off   - nothing; the retirement desk is what it is today.
    trace - the desk answers "made at X, owed by Y, aired at W - or the
            step it is stuck at".  A READ.  Nothing airs differently.
    air   - trace, and finishing a round the operator resumed CUES it, so
            it is in the queue for an hour rather than back on a shelf.
    """

    def __init__(self, root: str | Path,
                 env: Mapping[str, str] | None = None,
                 ttl: float = 3.0,
                 clock: Callable[[], float] = time.time):
        super().__init__(root, env=env, ttl=ttl, clock=clock)
        # Its own environment name, so the two switches cannot be turned on
        # by each other's variable.
        self._env = dict(self._env)
        self._env[ENV_NAME] = str(self._env.get(FOLLOW_ENV_NAME, ""))

    def cues(self) -> bool:
        """Does finishing a resumed round put it in the queue for an hour?"""
        return self.mode() == MODE_AIR


def follow_row(facts: Mapping[str, Any], now: float) -> dict[str, Any]:
    """One item of finished work, followed to air - or the step it is
    stuck at.

    PURE.  The caller reads the stores and hands the facts in, which is
    what lets this be asserted on in a unit test off a temp directory
    while the station is on air.

    `facts` are all things that already exist somewhere on this station:
        id, road, label, seconds    - retire_id and the shelf row
        made_at                     - the row's own `at`
        complete                    - cupboard_row_complete
        resumed                     - the id is in data/cupboard_finish.json
        cued_at                     - row["cue_at"] (#1364)
        owed                        - the id is in the four-hour plan's
                                      selected_ids
        entry                       - which entry, when the plan named one
        aired, aired_at, used_by    - written onto the row at hand-over
        blocked                     - the door's own last refusal, if any

    The answer names the FIRST step not passed, because that is the step
    somebody has to do something about.  An item that aired is finished
    business and says so with the entry and the hour it went out in."""
    at = float(now)
    rid = str(facts.get("id") or "")
    road = str(facts.get("road") or "")
    made_at = float(facts.get("made_at") or 0)
    aired = int(facts.get("aired") or 0)
    aired_at = float(facts.get("aired_at") or 0)
    used = facts.get("used_by") or {}
    cued_at = float(facts.get("cued_at") or 0)
    complete = bool(facts.get("complete"))
    resumed = bool(facts.get("resumed"))
    owed = bool(facts.get("owed"))
    blocked = " ".join(str(facts.get("blocked") or "").split())[:200]

    if aired > 0 or aired_at > 0:
        step = "aired"
    elif not complete:
        step = "resumed" if resumed else "written"
    elif cued_at > 0:
        step = "cued"
    elif owed:
        step = "owed"
    else:
        step = "recorded"

    waited = max(0.0, at - made_at) if made_at else 0.0
    out: dict[str, Any] = {
        "id": rid,
        "road": road,
        "label": str(facts.get("label") or road),
        "seconds": round(float(facts.get("seconds") or 0), 1),
        "made_at": round(made_at, 3) if made_at else 0.0,
        "waited_seconds": round(waited, 1),
        "step": step,
        "steps": {name: _passed(name, step) for name in FOLLOW_STEPS},
        "resumed": resumed,
        "cued_at": round(cued_at, 3) if cued_at else 0.0,
        "owed": owed,
        "entry": str(facts.get("entry") or ""),
        "aired_at": round(aired_at, 3) if aired_at else 0.0,
        "aired": aired,
        # The only join that exists today, and it runs cupboard -> hour.
        "hour": str((used or {}).get("hour") or ""),
        "slot": str((used or {}).get("slot_id")
                    or (used or {}).get("slot") or ""),
        "blocked": blocked,
    }
    out["say"] = follow_say(out)
    return out


def _passed(name: str, step: str) -> bool:
    try:
        return FOLLOW_STEPS.index(name) <= FOLLOW_STEPS.index(step)
    except ValueError:
        return False


def follow_say(row: Mapping[str, Any]) -> str:
    """The one sentence the operator reads off the desk."""
    step = str(row.get("step") or "")
    label = str(row.get("label") or row.get("road") or "a round")
    waited = float(row.get("waited_seconds") or 0)
    if step == "aired":
        where = str(row.get("slot") or "")
        hour = str(row.get("hour") or "")
        return ("%s went out%s%s."
                % (label,
                   (" in the %s entry" % where) if where else "",
                   (" of hour %s" % hour) if hour else ""))
    said = FOLLOW_SAYS.get(step,
                           "it is somewhere between the room and the air")
    entry = str(row.get("entry") or "")
    if step == "owed" and entry:
        said += " (%s)" % entry
    tail = ""
    if str(row.get("blocked") or ""):
        tail = " The last door to refuse it said: %s." % row["blocked"]
    return "%s, made %.1f hour(s) ago: %s.%s" % (label, waited / 3600.0,
                                                 said, tail)


def follow_summary(rows: Sequence[Mapping[str, Any]],
                   now: float) -> dict[str, Any]:
    """The desk's headline: how many are at each step, and the worst case.

    This is the answer to "is the orchestrator keeping track of these
    behind the scenes" - one number per step, and the oldest thing that
    has not reached the air named in a sentence."""
    counts = {name: 0 for name in FOLLOW_STEPS}
    worst: dict[str, Any] | None = None
    for row in rows or ():
        step = str((row or {}).get("step") or "")
        if step in counts:
            counts[step] += 1
        if step == "aired":
            continue
        if worst is None or float((row or {}).get("waited_seconds") or 0) > float(
                worst.get("waited_seconds") or 0):
            worst = dict(row or {})
    stuck = sum(value for name, value in counts.items() if name != "aired")
    say = ("nothing the recording room has finished is waiting"
           if not stuck else
           "%d finished or half-finished item(s) have not reached the air; "
           "the oldest is %s" % (stuck, str((worst or {}).get("say") or "")))
    return {"at": round(float(now), 3), "counts": counts, "stuck": stuck,
            "worst": worst or {}, "say": say}

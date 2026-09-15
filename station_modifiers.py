# -*- coding: utf-8 -*-
"""#1169/#1170: the things that modify a segment, given an identity.

The operator's words, inbox #1169:

    "give IDs and identifiers to these things and make sure that they are
    traceable throughout segments and through dialogue in order to make
    sure that these systems are taking place whenever they're activated.
    Whenever a guest is present in the studio, I want to see the guests
    get a code and the guest also take place in the studio and be present
    in the dialogue and the rhetoric and be a participant just like it's
    supposed to be with the way that the guest system is supposed to be.
    Same with topics. Same thing with any sort of events. Same thing with
    plot line. I want to be able to trace these things across the segments
    happening to the segments as modifiers for their events when they are
    occurring."

and #1170:

    "Make sure that these are used often with the station and said for the
    segments for whenever there's dead air that these are things that are
    said on the station that also get codes and IDs and are followed
    throughout the system."

WHAT WAS ACTUALLY MISSING.  Measured on the live station 2026-09-15, three
of the four already had an identity and none of the four was traceable:

    guest   data/guests.json        id "4f959ea0"      YES
    topic   data/banter_topics.json id "2a2919f9"      YES
    plot    data/plotlines.json     id "04fb434bf97a"  YES
    event   data/caller_themes.json name only          NO

    data/plot_beats.jsonl carries the plot id on every beat and, in 2475
    beats over twenty-four hours, carried a segment id on ZERO of them.
    data/air_log.jsonl and data/script_ledger.jsonl carry the segment id
    (sid) on every line and name no modifier at all.

So the complaint is not that the ids are absent.  It is that nothing ever
joined an id to a sid, in either direction.  This module is that join, and
nothing else:

  * it does NOT mint a second identity for anything that already has one -
    a guest is `guest:4f959ea0`, the id is the store's own id, and
    guests.json stays the only book of guests.  Only an EVENT, which the
    station holds as a bare name in caller_themes.json, is given a key
    here, derived from the name so it is the same key every time;
  * it keeps one durable book of what is STANDING (raised when, for how
    long) - `<data>/modifiers.json`, written the way courier_write writes,
    tmp then replace;
  * it keeps one durable reverse index of which modifiers rode which
    segment - `<data>/modifier_rides.jsonl`, one small row per round,
    an id list and never a copy of the thing;
  * it is pure.  No app.py, no FastAPI, no clock it does not take as an
    argument, no store it is not handed.  Everything that touches the live
    station lives in the caller.

A modifier that has expired stops riding.  That is the whole of its
authority: colour may not take the station off the air, and a modifier is
colour.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

# --- the four kinds -------------------------------------------------------
KIND_GUEST = "guest"
KIND_TOPIC = "topic"
KIND_EVENT = "event"
KIND_PLOT = "plot"
# #1179: THE RECORD ON THE DECK, and the half of its talk this is.  A
# record's introduction and its send-off had no identity of any kind -
# measured over 48.6 hours of air_log.jsonl, 140 of 140 `intro` rows and
# 3,354 of 3,386 `interject` rows carry no sid at all - so a link could
# not be joined to the record it was about, to the segment it aired in,
# or to the other half of its own pair.  It is a fifth KIND here rather
# than a second book for the reason the head of this file gives about the
# other four: the music store keeps the truth about the record, this keeps
# only the id, the clock and the join.  The key is `<track id>.<part>`,
# minted by track_talk_segment.part_key.
KIND_TALK = "talk"
KINDS = (KIND_GUEST, KIND_TOPIC, KIND_EVENT, KIND_PLOT, KIND_TALK)

# How each kind reads in a sentence a presenter could hear.
KIND_SAYS = {
    KIND_GUEST: "in the studio",
    KIND_TOPIC: "on the table",
    KIND_EVENT: "what is going on",
    KIND_PLOT: "the story running",
    KIND_TALK: "the record on the deck",
}

# Kinds that are TRACED and never SPOKEN.  A modifier is colour the pair
# may use; a record's own link is not colour, it is the thing they are
# about to read out, and handing it back to them as "standing now" would
# have the pair discussing the introduction instead of introducing the
# record.  So it rides every ledger and reaches no prompt and no gap
# filler - which also keeps the #1170 dead-air road from announcing a
# send-off that has not happened yet.
SILENT_KINDS = (KIND_TALK,)

# --- the switch -----------------------------------------------------------
# `<data>/modifiers/mode`, one word, re-read every few seconds, no restart.
# A missing, empty or unreadable file means OFF, and so does a word this
# does not recognise: an operator's typo must never be read as permission.
MODE_OFF = "off"        # nothing at all: no ids recorded, no clause written
MODE_TRACE = "trace"    # ids ride the ledger and the air log; AIR UNCHANGED
MODE_RIDE = "ride"      # trace, and the standing modifiers reach the writing
                        # prompt and the dead-air fillers (#1170)
MODES = (MODE_OFF, MODE_TRACE, MODE_RIDE)

# How long a raise stands for when nobody says.  A guest sits until sent
# home, a plot until its span runs out; a topic and an event are colour and
# go stale fast, because a station still talking about last hour's thing is
# worse than a station talking about nothing.
DEFAULT_STANDS_S = {
    KIND_GUEST: 0.0,            # 0 == until dropped
    KIND_PLOT: 0.0,             # the plot desk's own span governs it
    KIND_TOPIC: 1800.0,
    KIND_EVENT: 5400.0,
    # #1179: a record is on the deck for as long as it is turning.  The
    # caller passes the record's own length; this is only the answer for a
    # record whose length the store does not know.
    KIND_TALK: 240.0,
}

# Ceilings.  A ride row names at most this many ids, and the book holds at
# most this many records: a modifier list is a hint, not an archive.
RIDE_IDS_MAX = 8
BOOK_KEEP = 400
RIDES_KEEP_S = 48 * 3600.0      # the air log's own window (AIRLOG_KEEP_S)
CLAUSE_CAP = 4                  # how many standing modifiers a prompt hears

# What `aired` states mean the line actually left the building.  Mirrors
# app.py AIRLOG_AIRED plus the inspector's "published".
HEARD_STATES = ("box", "stream", "both", "published")

_SAFE_KEY = re.compile(r"[^A-Za-z0-9_.-]+")


# --- identity -------------------------------------------------------------
def clean_key(key: Any) -> str:
    """A store's own id, made safe to put in an id without changing it."""
    return _SAFE_KEY.sub("-", str(key or "").strip())[:48]


def name_key(name: Any) -> str:
    """The key for a thing the station holds as a bare NAME.

    Only events need this.  Derived from the name so the same event raised
    on Tuesday and again on Friday is the same event, and so an operator
    who renames a theme gets a new one - which is correct: it is a new
    thing that happened."""
    text = " ".join(str(name or "").split()).strip().lower()
    if not text:
        return ""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def modifier_id(kind: str, key: Any) -> str:
    """`guest:4f959ea0`.  Namespaced so two stores cannot collide, short
    enough to sit in every ledger row without being noticed."""
    kind = str(kind or "").strip().lower()
    if kind not in KINDS:
        return ""
    safe = clean_key(key)
    return ("%s:%s" % (kind, safe)) if safe else ""


def split_id(mid: Any) -> tuple[str, str]:
    """`guest:4f959ea0` -> ("guest", "4f959ea0"). ("", "") if it is not one."""
    text = str(mid or "").strip()
    if ":" not in text:
        return ("", "")
    kind, _, key = text.partition(":")
    kind = kind.strip().lower()
    if kind not in KINDS:
        return ("", "")
    return (kind, clean_key(key))


def is_modifier_id(mid: Any) -> bool:
    return bool(split_id(mid)[0])


# --- the record -----------------------------------------------------------
def make_record(kind: str, key: Any, name: Any, now: float,
                stands_s: float | None = None, note: Any = "",
                source: Any = "") -> dict[str, Any]:
    """One modifier, as the book holds it.

    `until` 0.0 means "stands until dropped" - a guest in the chair, a plot
    the desk is still running.  Anything else is a wall clock."""
    kind = str(kind or "").strip().lower()
    stands = (DEFAULT_STANDS_S.get(kind, 1800.0)
              if stands_s is None else max(0.0, float(stands_s)))
    return {
        "id": modifier_id(kind, key),
        "kind": kind,
        "key": clean_key(key),
        "name": " ".join(str(name or "").split())[:120],
        "raised": round(float(now), 3),
        "stands": round(float(stands), 1),
        "until": (0.0 if stands <= 0 else round(float(now) + stands, 3)),
        "note": " ".join(str(note or "").split())[:240],
        "source": str(source or "")[:40],
        "rode": 0,
    }


def record_standing(record: Mapping[str, Any], now: float) -> bool:
    """Is this modifier still standing at `now`?

    A record with no id never stands - it cannot be traced, so it must not
    be allowed to colour anything."""
    if not record or not str(record.get("id") or ""):
        return False
    until = float(record.get("until") or 0.0)
    if until <= 0:
        return True                     # until dropped
    return float(now) < until


def record_says(record: Mapping[str, Any]) -> str:
    """The modifier as one line a writer can use.  NO ID IN IT.

    The id is a ledger fact, not a line: a presenter who reads `guest:
    e40ad093` out loud has said the quiet part, and the station has a
    standing rule that a prompt is never read aloud."""
    name = str(record.get("name") or "").strip()
    if not name:
        return ""
    note = str(record.get("note") or "").strip()
    says = KIND_SAYS.get(str(record.get("kind") or ""), "standing")
    return "%s (%s)%s" % (name, says, (" - " + note) if note else "")


# --- the book -------------------------------------------------------------
class ModifierBook:
    """`<data>/modifiers.json` and `<data>/modifier_rides.jsonl`.

    The book is what is standing.  The rides are which segment each
    standing thing rode into.  Neither holds a copy of a guest, a topic, a
    theme or a plotline: those stores stay where they are and stay the
    truth.  This holds the id, the clock and the join."""

    def __init__(self, root: str | Path,
                 clock: Callable[[], float] = time.time,
                 keep: int = BOOK_KEEP,
                 rides_keep_s: float = RIDES_KEEP_S):
        self.root = Path(root)
        self.book_path = self.root / "modifiers.json"
        self.rides_path = self.root / "modifier_rides.jsonl"
        self.clock = clock
        self.keep = int(keep)
        self.rides_keep_s = float(rides_keep_s)
        self._book: dict[str, dict[str, Any]] | None = None
        self._by_sid: dict[str, list[str]] | None = None

    # -- durability --------------------------------------------------------
    def _load(self) -> dict[str, dict[str, Any]]:
        if self._book is not None:
            return self._book
        rows: list[Any] = []
        try:
            rows = json.loads(self.book_path.read_text(encoding="utf-8"))
        except Exception:               # noqa: BLE001  missing, mid-write, junk
            rows = []
        book: dict[str, dict[str, Any]] = {}
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                mid = str(row.get("id") or "")
                if is_modifier_id(mid):
                    book[mid] = dict(row)
        self._book = book
        return book

    def _save(self) -> None:
        """courier_write's pattern: mkdir, tmp, replace.  A half-written
        book is a book the station cannot read, and this one is read on the
        path that writes every round."""
        book = self._load()
        rows = sorted(book.values(), key=lambda r: float(r.get("raised") or 0))
        rows = rows[-self.keep:]
        self._book = {str(r["id"]): r for r in rows}
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.book_path.with_name(
            self.book_path.name + "." + uuid.uuid4().hex + ".tmp")
        tmp.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        os.replace(tmp, self.book_path)

    def reload(self) -> None:
        """Forget what was read.  Another writer may own the file."""
        self._book = None
        self._by_sid = None

    # -- raising and dropping ---------------------------------------------
    def raise_(self, kind: str, key: Any, name: Any,
               stands_s: float | None = None, note: Any = "",
               source: Any = "", now: float | None = None) -> dict[str, Any]:
        """Put a modifier up, or keep one that is already up.

        Idempotent on purpose: the station will call this every few seconds
        off the live stores, and `raised` must keep meaning WHEN IT WAS
        RAISED, not when it was last noticed.  A modifier that has already
        expired and is raised again is a NEW raise of the same id - the
        thing came back, and the trace should say so."""
        at = float(self.clock() if now is None else now)
        fresh = make_record(kind, key, name, at, stands_s, note, source)
        mid = fresh["id"]
        if not mid:
            return {}
        book = self._load()
        old = book.get(mid)
        if old and record_standing(old, at):
            old["name"] = fresh["name"] or old.get("name") or ""
            if note:
                old["note"] = fresh["note"]
            old["stands"] = fresh["stands"]
            old["until"] = (0.0 if fresh["stands"] <= 0
                            else round(at + fresh["stands"], 3))
            self._save()
            return dict(old)
        fresh["rode"] = int((old or {}).get("rode") or 0)
        book[mid] = fresh
        self._save()
        return dict(fresh)

    def drop(self, mid: str, now: float | None = None) -> bool:
        """Send it home.  The record stays - a trace of a guest who has
        left is still a trace, and #1169 asks for the segments it touched,
        not for the guest to be forgotten when he goes."""
        at = float(self.clock() if now is None else now)
        book = self._load()
        row = book.get(str(mid or ""))
        if not row:
            return False
        row["until"] = round(at, 3)
        row["stands"] = round(max(0.0, at - float(row.get("raised") or at)), 1)
        self._save()
        return True

    def get(self, mid: str) -> dict[str, Any]:
        return dict(self._load().get(str(mid or "")) or {})

    def all(self) -> list[dict[str, Any]]:
        return [dict(r) for r in sorted(
            self._load().values(),
            key=lambda r: -float(r.get("raised") or 0))]

    def standing(self, now: float | None = None) -> list[dict[str, Any]]:
        """What is up, newest raise first.  This is what rides."""
        at = float(self.clock() if now is None else now)
        rows = [dict(r) for r in self._load().values()
                if record_standing(r, at)]
        rows.sort(key=lambda r: -float(r.get("raised") or 0))
        return rows

    def standing_ids(self, now: float | None = None,
                     cap: int = RIDE_IDS_MAX) -> list[str]:
        return [str(r["id"]) for r in self.standing(now)][:max(0, int(cap))]

    # -- the ride ----------------------------------------------------------
    def _rides(self) -> dict[str, list[str]]:
        if self._by_sid is not None:
            return self._by_sid
        by_sid: dict[str, list[str]] = {}
        try:
            text = self.rides_path.read_text(encoding="utf-8", errors="replace")
        except Exception:               # noqa: BLE001
            text = ""
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:           # noqa: BLE001  a torn tail is not fatal
                continue
            sid = str((row or {}).get("sid") or "")
            if not sid:
                continue
            ids = [str(i) for i in (row.get("ids") or []) if is_modifier_id(i)]
            by_sid[sid] = ids           # last row for a sid wins
        self._by_sid = by_sid
        return by_sid

    def ride(self, sid: str, ids: Sequence[str] | None = None,
             now: float | None = None,
             round_kind: Any = "", source: Any = "") -> list[str]:
        """Record that these modifiers shaped the round called `sid`.

        Called once, where the sid is minted.  Writing it here rather than
        at commit time is deliberate: a round that is written and then
        never heard still has to be traceable, because "written and never
        aired" is an answer #1169 asks for."""
        sid = str(sid or "").strip()
        if not sid:
            return []
        at = float(self.clock() if now is None else now)
        if ids is None:
            ids = self.standing_ids(at)
        clean = []
        for one in ids:
            one = str(one or "")
            if is_modifier_id(one) and one not in clean:
                clean.append(one)
        clean = clean[:RIDE_IDS_MAX]
        if not clean:
            return []
        rides = self._rides()
        if rides.get(sid) == clean:
            return list(clean)          # idempotent: one round rides once
        rides[sid] = list(clean)
        row = {"at": round(at, 3), "sid": sid, "ids": clean}
        if round_kind:
            row["round"] = str(round_kind)[:40]
        if source:
            row["source"] = str(source)[:60]
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with self.rides_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
        except Exception:               # noqa: BLE001  a failed trace never
            return list(clean)          # stops a round going out
        book = self._load()
        touched = False
        for one in clean:
            if one in book:
                book[one]["rode"] = int(book[one].get("rode") or 0) + 1
                touched = True
        if touched:
            self._save()
        return list(clean)

    def ids_for(self, sid: str) -> list[str]:
        """The modifiers that shaped this segment.  A dict lookup: this is
        asked once per ledger row and once per air-log row."""
        return list(self._rides().get(str(sid or "").strip()) or [])

    def rides_for(self, mid: str) -> list[dict[str, Any]]:
        """Every segment this modifier touched, oldest first."""
        mid = str(mid or "").strip()
        if not mid:
            return []
        out: list[dict[str, Any]] = []
        try:
            text = self.rides_path.read_text(encoding="utf-8", errors="replace")
        except Exception:               # noqa: BLE001
            return []
        seen: set[str] = set()
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:           # noqa: BLE001
                continue
            sid = str((row or {}).get("sid") or "")
            if not sid or sid in seen:
                continue
            if mid in [str(i) for i in (row.get("ids") or [])]:
                seen.add(sid)
                out.append({"sid": sid, "at": float(row.get("at") or 0),
                            "round": str(row.get("round") or ""),
                            "source": str(row.get("source") or "")})
        out.sort(key=lambda r: r["at"])
        return out

    def prune(self, now: float | None = None) -> int:
        """Drop ride rows older than the air log's own window - past that
        the segments they name cannot be shown as heard anyway."""
        at = float(self.clock() if now is None else now)
        cut = at - self.rides_keep_s
        try:
            text = self.rides_path.read_text(encoding="utf-8", errors="replace")
        except Exception:               # noqa: BLE001
            return 0
        keep: list[str] = []
        dropped = 0
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:           # noqa: BLE001
                dropped += 1
                continue
            if float((row or {}).get("at") or 0) < cut:
                dropped += 1
                continue
            keep.append(line)
        if not dropped:
            return 0
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self.rides_path.with_name(
                self.rides_path.name + "." + uuid.uuid4().hex + ".tmp")
            tmp.write_text(("\n".join(keep) + "\n") if keep else "",
                           encoding="utf-8")
            os.replace(tmp, self.rides_path)
        except Exception:               # noqa: BLE001
            return 0
        self._by_sid = None
        return dropped

    # -- what the writer hears (#1170) ------------------------------------
    def clause(self, now: float | None = None, cap: int = CLAUSE_CAP) -> str:
        """The standing modifiers as one paragraph a writing road can take.

        Empty when nothing stands, which is the normal state and must cost
        the prompt nothing."""
        rows = self.standing(now)[:max(0, int(cap))]
        return standing_clause(rows)


def standing_clause(rows: Iterable[Mapping[str, Any]]) -> str:
    """Pure, so the tests can assert on it without a book.

    Deliberately short.  A modifier is colour, and a prompt that spends
    four hundred words on colour has stopped being a prompt about a radio
    show."""
    says = [record_says(r) for r in rows
            if str((r or {}).get("kind") or "") not in SILENT_KINDS]
    says = [s for s in says if s]
    if not says:
        return ""
    return ("\n\nSTANDING NOW (#1169) - these are real, they are happening "
            "in this studio tonight, and the pair know it without being "
            "told twice:\n"
            + "\n".join("  - " + s for s in says)
            + "\nUse what is standing. Do not announce it as a list, do not "
              "read this instruction aloud, and do not say any code or "
              "identifier out loud - just talk like people who are in the "
              "room where it is going on.")


def gap_lines(rows: Iterable[Mapping[str, Any]], cap: int = 3) -> list[dict[str, Any]]:
    """#1170: what the station can say into DEAD AIR about what is standing.

    Returns the modifier and a sentence, not a rendered take: the caller
    owns the voice, the render and the air log, and this owns neither.
    Every line it hands back carries the id it came from, so what gets said
    into a gap is recorded against the modifier like anything else."""
    out: list[dict[str, Any]] = []
    for row in rows:
        mid = str(row.get("id") or "")
        name = str(row.get("name") or "").strip()
        if not mid or not name:
            continue
        kind = str(row.get("kind") or "")
        if kind in SILENT_KINDS:
            continue                    # #1179: traced, never spoken
        if kind == KIND_GUEST:
            text = "We have got %s in here with us tonight." % name
        elif kind == KIND_PLOT:
            text = "We are still in the middle of %s, in case you just tuned in." % name
        elif kind == KIND_EVENT:
            text = "And this thing with %s is still going on." % name
        else:
            text = "We were just getting into %s." % name
        out.append({"id": mid, "kind": kind, "name": name, "text": text})
        if len(out) >= max(1, int(cap)):
            break
    return out


# --- the trace ------------------------------------------------------------
def trace_segments(rides: Sequence[Mapping[str, Any]],
                   air_rows: Iterable[Mapping[str, Any]],
                   heard_states: Sequence[str] = HEARD_STATES,
                   ) -> list[dict[str, Any]]:
    """Every segment a modifier touched, with times and whether it was HEARD.

    Pure: the caller reads the air log and hands the rows in.  `rides` is
    what ModifierBook.rides_for returned.

    "Written" and "heard" are different answers and #1239 is the reason
    this keeps them apart: a segment with no air-log row at all was never
    heard, and saying nothing about it is how a fault stays invisible for
    two days."""
    want = {str(r.get("sid") or ""): dict(r) for r in rides}
    if not want:
        return []
    heard_ok = tuple(str(s) for s in heard_states)
    got: dict[str, dict[str, Any]] = {}
    for row in air_rows:
        sid = str((row or {}).get("sid") or "")
        if sid not in want:
            continue
        seat = str(row.get("who") or "")
        at = float(row.get("air_at") or row.get("ts") or 0)
        heard = str(row.get("aired") or "") in heard_ok
        slot = got.setdefault(sid, {"lines": 0, "heard": 0, "first": 0.0,
                                    "last": 0.0, "seats": {}, "seconds": 0.0,
                                    "round": "", "source": ""})
        slot["lines"] += 1
        slot["seconds"] += float(row.get("seconds") or 0)
        slot["seats"][seat] = int(slot["seats"].get(seat) or 0) + 1
        slot["round"] = slot["round"] or str(row.get("round") or "")
        slot["source"] = slot["source"] or str(row.get("source") or "")
        if heard:
            slot["heard"] += 1
            if at and (not slot["first"] or at < slot["first"]):
                slot["first"] = at
            if at > slot["last"]:
                slot["last"] = at
    out: list[dict[str, Any]] = []
    for sid, ride in want.items():
        slot = got.get(sid) or {}
        lines = int(slot.get("lines") or 0)
        heard = int(slot.get("heard") or 0)
        out.append({
            "sid": sid,
            "at": round(float(ride.get("at") or 0), 3),
            "round": str(slot.get("round") or ride.get("round") or ""),
            "source": str(slot.get("source") or ride.get("source") or ""),
            "lines": lines,
            "heard_lines": heard,
            "seconds": round(float(slot.get("seconds") or 0), 1),
            "seats": sorted((slot.get("seats") or {}).keys()),
            "first_heard": round(float(slot.get("first") or 0), 3) or None,
            "last_heard": round(float(slot.get("last") or 0), 3) or None,
            "heard": bool(heard),
            "say": ("heard" if heard else
                    ("written, and every line of it refused or withdrawn"
                     if lines else
                     "written, and not one line of it reached the air log")),
        })
    out.sort(key=lambda r: r["at"])
    return out


def trace_summary(record: Mapping[str, Any],
                  segments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The one-sentence answer, so a reader does not have to count rows."""
    heard = [s for s in segments if s.get("heard")]
    name = str(record.get("name") or "") or str(record.get("id") or "")
    if not segments:
        say = ("%s has not ridden a single segment - it is on the book and "
               "nothing has been written under it" % name)
    elif not heard:
        say = ("%s rode %d segment(s) and NOT ONE of them was heard"
               % (name, len(segments)))
    else:
        say = ("%s rode %d segment(s), %d of them heard, %s to %s"
               % (name, len(segments), len(heard),
                  time.strftime("%H:%M:%S",
                                time.localtime(heard[0]["first_heard"] or 0)),
                  time.strftime("%H:%M:%S",
                                time.localtime(heard[-1]["last_heard"] or 0))))
    return {
        "segments": len(segments),
        "heard": len(heard),
        "written_never_heard": len(segments) - len(heard),
        "lines": sum(int(s.get("lines") or 0) for s in segments),
        "heard_lines": sum(int(s.get("heard_lines") or 0) for s in segments),
        "seconds": round(sum(float(s.get("seconds") or 0)
                             for s in segments), 1),
        "say": say,
    }


# --- following the live stores -------------------------------------------
def from_stores(guests: Any = None, dj: Mapping[str, Any] | None = None,
                topics: Any = None, plotlines: Any = None,
                themes: Mapping[str, Any] | None = None,
                now: float | None = None,
                topic_fresh_s: float = 1800.0) -> list[dict[str, Any]]:
    """What the station's OWN stores say is standing, right now.

    This is the whole reason there is no second book of guests, topics,
    themes or plotlines: those four files stay the truth and this reads
    them.  Returns raise instructions - (kind, key, name, stands_s, note) -
    for the caller to hand to ModifierBook.raise_.

    Never raises.  A store that is missing, mid-write or the wrong shape
    contributes nothing, because a modifier desk that can take the station
    down has misunderstood what it is for."""
    at = float(time.time() if now is None else now)
    out: list[dict[str, Any]] = []

    # A guest, if one is in the chair.  dj.guest_mode + dj.guest_id is how
    # app.py's active_guest() decides, and this must agree with it or the
    # trace will name a guest who is not there.
    try:
        settings = dict(dj or {})
        gid = str(settings.get("guest_id") or "")
        if settings.get("guest_mode") and gid:
            for row in (guests or []):
                if str((row or {}).get("id") or "") == gid:
                    out.append({"kind": KIND_GUEST, "key": gid,
                                "name": str(row.get("name") or "the guest"),
                                "stands_s": 0.0,
                                "note": str(row.get("who") or "")[:120],
                                "source": "guests.json"})
                    break
    except Exception:                   # noqa: BLE001
        pass

    # The plotline colouring the air.  plotlines.json, active and not done.
    try:
        for row in (plotlines or []):
            row = dict(row or {})
            if not row.get("active") or row.get("done"):
                continue
            pid = str(row.get("id") or "")
            if not pid:
                continue
            span = float(row.get("span_minutes") or 0) * 60.0
            started = float(row.get("started_at") or at)
            stands = max(0.0, (started + span) - at) if span > 0 else 0.0
            acts = list(row.get("acts") or [])
            live = int(row.get("act_live") or 0)
            note = ""
            if 1 <= live <= len(acts):
                note = str(acts[live - 1])[:120]
            out.append({"kind": KIND_PLOT, "key": pid,
                        "name": str(row.get("title") or "the story"),
                        "stands_s": stands, "note": note,
                        "source": "plotlines.json"})
            break                       # one storyline owns the air (#907)
    except Exception:                   # noqa: BLE001
        pass

    # The theme the station is on.  caller_themes.json holds these as bare
    # NAMES - this is the one kind that gets a key minted here, and it is
    # minted from the name so it is stable across restarts.
    try:
        book = dict(themes or {})
        active = str(book.get("active") or "").strip()
        if active:
            text = ""
            for row in (book.get("themes") or []):
                if str((row or {}).get("name") or "") == active:
                    text = str(row.get("text") or "")
                    break
            key = name_key(active)
            if key:
                out.append({"kind": KIND_EVENT, "key": key, "name": active,
                            "stands_s": DEFAULT_STANDS_S[KIND_EVENT],
                            "note": text[:120],
                            "source": "caller_themes.json"})
    except Exception:                   # noqa: BLE001
        pass

    # Topics that have actually been sprung recently.  A topic the station
    # has never said is not standing - it is stock.
    try:
        fresh: list[tuple[float, dict[str, Any]]] = []
        for row in (topics or []):
            row = dict(row or {})
            tid = str(row.get("id") or "")
            last = float(row.get("last") or 0)
            if not tid or not last:
                continue
            if at - last > float(topic_fresh_s):
                continue
            fresh.append((last, row))
        fresh.sort(key=lambda pair: -pair[0])
        for last, row in fresh[:2]:
            out.append({"kind": KIND_TOPIC, "key": str(row.get("id")),
                        "name": str(row.get("text") or "")[:120],
                        "stands_s": max(60.0, float(topic_fresh_s)
                                        - (at - last)),
                        "note": "", "source": "banter_topics.json"})
    except Exception:                   # noqa: BLE001
        pass
    return out


def follow_stores(book: ModifierBook, raises: Iterable[Mapping[str, Any]],
                  now: float | None = None,
                  drop_missing: bool = True) -> dict[str, Any]:
    """Put up what the stores say is up, and take down what they no longer
    say - but only the kinds the stores govern, and never a hand raise.

    A guest sent home by `/api/dj/guest/send-home` must stop riding within
    a tick, or the next hour of segments will be traced to a guest who is
    not in the building."""
    at = float(book.clock() if now is None else now)
    want: dict[str, Mapping[str, Any]] = {}
    for one in raises:
        mid = modifier_id(str(one.get("kind") or ""), one.get("key"))
        if mid:
            want[mid] = one
    up: list[str] = []
    for mid, one in want.items():
        book.raise_(str(one.get("kind")), one.get("key"), one.get("name"),
                    stands_s=one.get("stands_s"), note=one.get("note") or "",
                    source=one.get("source") or "", now=at)
        up.append(mid)
    down: list[str] = []
    if drop_missing:
        governed = {KIND_GUEST, KIND_PLOT, KIND_EVENT}
        for row in book.standing(at):
            mid = str(row.get("id") or "")
            if mid in want:
                continue
            if str(row.get("kind") or "") not in governed:
                continue
            if not str(row.get("source") or ""):
                continue                # raised by hand; the stores do not
            if book.drop(mid, at):      # own it and must not take it down
                down.append(mid)
    return {"up": sorted(up), "down": sorted(down),
            "standing": [r["id"] for r in book.standing(at)]}


# --- the switch -----------------------------------------------------------
class ModifierSwitch:
    """`<data>/modifiers/mode`, re-read at most every `ttl` seconds.

    Built the way ProductionSwitch and the admission gate are built, and
    for the same reason: the station is on air, and turning a new road off
    has to be a one-word write that takes effect in seconds.

    DEFAULTS OFF.  Missing file, empty file, unreadable file, or a word
    this does not know: off."""

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
            return self.path.read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            return ""

    def mode(self) -> str:
        now = float(self.clock())
        if self._read_at and (now - self._read_at) < self.ttl:
            return self._cached
        text = self._text()
        if not text:
            text = str(self._env.get("SPARK_AGENT_MODIFIERS", "")).strip()
        self._read_at = now
        self._cached = parse_mode(text)
        return self._cached

    def traces(self) -> bool:
        """Are ids recorded against segments?  Changes nothing that airs."""
        return self.mode() in (MODE_TRACE, MODE_RIDE)

    def airs(self) -> bool:
        """Do the standing modifiers reach the prompt and the gap fillers?"""
        return self.mode() == MODE_RIDE

    def write(self, text: str) -> None:
        """Tests and operator tools only; never the station itself."""
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + "." + uuid.uuid4().hex + ".tmp")
        tmp.write_text(str(text).strip() + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
        self._read_at = 0.0


def parse_mode(text: Any) -> str:
    """One word into a mode.  Anything unrecognised is OFF."""
    for word in str(text or "").replace(",", " ").split():
        low = word.strip().lower()
        if low in MODES:
            return low
        if low == "on":                 # the kindest reading of "on" is the
            return MODE_RIDE            # one the operator meant
    return MODE_OFF

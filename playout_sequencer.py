"""playout_sequencer - the LINEAR PLAYOUT CONTROLLER (#1218, #1246).

    "For each investigation task, get to the bottom of why the script
     jumped out of queue and let's make the orchestrator more capable of
     scheduling, orchestrating and executing the script on the air in a
     linear fashion fully controlled by the system."

One sequencer owns the air. It is told three kinds of thing by the station
and it answers two questions.

It is told:

  * a round is being MADE (`making`): the writer/renderer has it, with an
    estimate of how long until every one of its lines has audio;
  * a round is READY and waiting its turn (`hold`): every line of it has
    audio, the file is welded, the cue sheet is measured - it is HELD at the
    end of the sequence and nothing may go in front of it;
  * an occurrence was DISPATCHED to a transport (`dispatched`), and what the
    LISTENER then reported about it (`heard`, `ended`).

It answers:

  * `air_free_at()` - the moment the air will be free, on the LISTENER's
    clock, not the server's estimate. A page that stalled for a hundred
    seconds and then resumed (block 6404, 2026-09-21) sounded two committed
    calls at once because the next one was stamped off the server's idea
    of when the first would end. The listener's acknowledgements say where
    the sounding clip actually is, and this walks the line out from there.
  * `ask_fill(road)` - may a filler road (a gold bar, a sting, the SFX guy's
    join, the emergency host, the cupboard rescue) put something on the air
    NOW? The answer is NO while a committed round is ready and waiting,
    and NO for a competing dialogue road while a round is being made and is
    nearly ready. Measured on the listener's clock over six hours: 19
    scripted rounds re-entered the reading order behind 171 rows of
    interjections, intros and SFX-guy quips that fired during the median
    61-second wait between a round being committed and its first line
    being heard. Those are the asks this refuses.

What it deliberately does NOT do:

  * It does not number the script. `(block, ord)` is the script ledger's
    and positions are the admission gate's; this module only decides WHEN
    the round that owns them is committed - at dispatch, so the number a
    round is given is the number of the moment it actually goes out.
  * It does not refuse a committed round. A round that reached `hold` has
    every line rendered; the only thing that can stop it is the operator's
    pause or the sheet's own fit check, both of which speak before it is
    committed.
  * It does not undo a pause, and it does not open a socket, import
    app.py, or touch a live store. It is given a clock and told things.

MODE. Three words in `<data>/playout/mode`, re-read within three seconds,
no restart, and a file holding a SENTENCE reads as off:

  off      the default, and INERT. No ask is evaluated, no verdict is
           counted, and `page_floor()` returns 0.0 - so the switch being
           off is provably free of behaviour rather than believed to be.
  shadow   everything is evaluated and counted (`would_queue`,
           `would_be_after`) and NOTHING is enforced. /api/playout is a
           census before it is a rule; this is the setting to read for an
           hour before trusting it.
  linear   the two answers above rule.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterable

SCHEMA_VERSION = 1

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_LINEAR = "linear"
MODES = (MODE_OFF, MODE_SHADOW, MODE_LINEAR)
ENV_NAME = "SPARK_AGENT_PLAYOUT"

ROUTE_PAGE = "page"
ROUTE_BOX = "box"

# Timing defaults. The page needs a clip ANNOUNCED this far ahead of its
# moment (#998's download window) plus the feed's own lead; a held round is
# "about to go" when the air frees inside that window.
PAGE_LEAD_S = 7.0
ANNOUNCE_EARLY_S = 38.0
END_GRACE_S = 4.0          # a beat past a planned end before the air is free
STALL_S = 45.0             # no listener progress for this long = stalled (reported)
MAKING_SOON_S = 90.0       # a round this close to ready keeps dialogue fillers out
HELD_STALE_S = 240.0       # a held round nobody released for this long is dropped
# How long a RESERVATION for a rendered round that has not been dispatched
# holds the page floor. Deliberately short: a wedged maker must never push
# the air forward for minutes. Past it the round keeps its place in the
# sequence but stops reserving air, and the census says so.
HOLD_RESERVE_S = 100.0
MAKING_STALE_S = 1500.0    # matches FLOOR_STALE_SECONDS: a wedged maker is forgotten
KEEP_EVENTS = 400
KEEP_RECENT = 24

# Roads that are a competing CONVERSATION rather than a clip. While a round
# is being made and is nearly ready these wait; a clip or a record may fill.
DIALOGUE_ROADS = frozenset({"rescue", "continuity", "cover", "torrent",
                            "unheard", "manager_break_in", "round", "banter"})
# Rows the SHEET put there (an advert entry): they ask with priority, so the
# replay does not count them as jumpers.
SHEET_KINDS = frozenset({"ad"})


def parse_mode(text: Any) -> str:
    """ONE token, or off. A file holding a sentence is off - the record-talk
    switch's rule, kept for the same reason: a half-written switch must
    never turn a live station's running order over."""
    words = str(text or "").strip().lower().split()
    if len(words) != 1:
        return MODE_OFF
    word = words[0]
    if word in ("linear", "on", "enforce"):
        return MODE_LINEAR
    if word in ("shadow", "observe", "trace", "watch"):
        return MODE_SHADOW
    return MODE_OFF


class PlayoutSwitch:
    """`<data>/playout/mode`, re-read at most every `ttl` seconds. Defaults off."""

    def __init__(self, root: str | Path, env: dict[str, str] | None = None,
                 ttl: float = 3.0, clock: Callable[[], float] = time.time):
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

    def write(self, text: str) -> str:
        """Operator tools and the broadcast fixer only."""
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + "." + uuid.uuid4().hex + ".tmp")
        tmp.write_text(str(text).strip() + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
        self._read_at = 0.0
        return self.mode()


class LinearSequencer:
    """ONE sequencer owns the air. See the module docstring."""

    def __init__(self, *, clock: Callable[[], float] = time.time,
                 mode_reader: Callable[[], str] | None = None,
                 page_lead_s: float = PAGE_LEAD_S,
                 announce_early_s: float = ANNOUNCE_EARLY_S,
                 end_grace_s: float = END_GRACE_S,
                 stall_s: float = STALL_S,
                 making_soon_s: float = MAKING_SOON_S,
                 held_stale_s: float = HELD_STALE_S,
                 hold_reserve_s: float = HOLD_RESERVE_S,
                 making_stale_s: float = MAKING_STALE_S,
                 events_path: str | Path | None = None,
                 keep_events: int = KEEP_EVENTS,
                 log: Callable[[str, dict[str, Any]], None] | None = None):
        self.clock = clock
        self.mode_reader = mode_reader or (lambda: MODE_OFF)
        self.page_lead_s = float(page_lead_s)
        self.announce_early_s = float(announce_early_s)
        self.end_grace_s = float(end_grace_s)
        self.stall_s = float(stall_s)
        self.making_soon_s = float(making_soon_s)
        self.held_stale_s = float(held_stale_s)
        self.hold_reserve_s = float(hold_reserve_s)
        self.making_stale_s = float(making_stale_s)
        self.events_path = Path(events_path) if events_path else None
        self.keep_events = max(50, int(keep_events))
        self.log = log
        self.lock = RLock()
        self._making: dict[str, dict[str, Any]] = {}
        self._held: dict[str, dict[str, Any]] = {}
        self._line: list[dict[str, Any]] = []      # dispatched, not over: (oid, route)
        self._recent: list[dict[str, Any]] = []
        self._by_delivery: dict[str, tuple[str, str]] = {}
        self._asks: dict[str, dict[str, Any]] = {}
        self._counts: dict[str, int] = {}
        self._events: list[dict[str, Any]] = []
        self._started = float(clock())
        self._linear_since = 0.0
        self._last_mode = MODE_OFF

    # ------------------------------------------------------------- mode

    def mode(self) -> str:
        try:
            mode = str(self.mode_reader() or MODE_OFF)
        except Exception:  # noqa: BLE001
            mode = MODE_OFF
        mode = mode if mode in MODES else MODE_OFF
        if mode != self._last_mode:
            self._last_mode = mode
            self._linear_since = float(self.clock()) if mode == MODE_LINEAR else 0.0
            self._event("mode", mode=mode)
        return mode

    def linear(self) -> bool:
        """Is the sequencer RULING? Only `linear` changes any behaviour."""
        return self.mode() == MODE_LINEAR

    def active(self) -> bool:
        """Is it even looking? `off` is inert - no counting, no floor, no
        verdict beyond its own name - so a switch nobody has thrown costs
        the station nothing at all."""
        return self.mode() in (MODE_SHADOW, MODE_LINEAR)

    # ---------------------------------------------- what the station says

    def making(self, key: str, *, road: str = "", kind: str = "", lines: int = 0,
               eta_s: float = 0.0, sid: str = "", label: str = "",
               block: int = 0) -> str:
        """A round is being produced. `eta_s` is the maker's own estimate of
        the seconds until every line has audio."""
        with self.lock:
            key = str(key or uuid.uuid4().hex[:12])
            now = float(self.clock())
            self._making[key] = {"key": key, "road": str(road or ""), "kind": str(kind or ""),
                                 "lines": int(lines or 0), "eta_s": max(0.0, float(eta_s or 0.0)),
                                 "since": now, "sid": str(sid or ""), "label": str(label or "")[:80],
                                 "block": int(block or 0), "audio_ready": False}
            self._count("making")
            self._event("making", key=key, road=road, kind=kind, lines=lines, eta_s=round(float(eta_s or 0), 1))
            return key

    def hold(self, key: str, *, seconds: float = 0.0, lines: int = 0, media: str = "",
             sid: str = "", road: str = "", kind: str = "", label: str = "",
             block: int = 0, ord0: int = 0, occurrence: str = "",
             audio_ready: bool = True, body_frames: float = 0.0,
             cues: int = 0, why_not_ready: str = "") -> dict[str, Any]:
        """Every line of this round has audio; it waits its turn at the END
        of the sequence. From here on nothing may go in front of it.

        THE AUDIO GATE. `audio_ready` is the caller's answer to the one
        precondition the whole note is built on: "verify that its final
        audio is available and its ordered line/cue offsets are known
        BEFORE committing". A round that cannot answer yes is NOT held -
        it goes back on the making shelf with the reason, so it reserves
        no air and nothing waits behind a file that does not exist. On
        this station the answer comes from the admission gate's own
        `verify` (audio present, cues ordered) and, where the measured
        production road made the round, from the cue map's `body_frames`
        matching what the mixer produced."""
        with self.lock:
            key = str(key or uuid.uuid4().hex[:12])
            now = float(self.clock())
            made = self._making.get(key) or {}
            if not audio_ready:
                # Not a hold. A round whose audio is not finished cannot
                # be next, and saying so here is what stops a half-made
                # round holding the fillers off the air.
                row = dict(made)
                row.update({"key": key, "road": str(road or made.get("road") or ""),
                            "kind": str(kind or made.get("kind") or ""),
                            "lines": int(lines or made.get("lines") or 0),
                            "sid": str(sid or made.get("sid") or ""),
                            "label": str(label or made.get("label") or "")[:80],
                            "block": int(block or made.get("block") or 0),
                            "since": float(made.get("since") or now),
                            "eta_s": float(made.get("eta_s") or 0.0),
                            "audio_ready": False,
                            "why_not_ready": str(why_not_ready or "its audio is not finished")[:160]})
                self._making[key] = row
                self._count("not_ready")
                self._event("not_ready", key=key, road=row["road"],
                            why=row["why_not_ready"])
                return dict(row)
            self._making.pop(key, None)
            row = {"key": key, "road": str(road or made.get("road") or ""),
                   "kind": str(kind or made.get("kind") or ""),
                   "lines": int(lines or made.get("lines") or 0),
                   "seconds": max(0.0, float(seconds or 0.0)),
                   "media": str(media or "").rsplit("/", 1)[-1].split("?")[0],
                   "sid": str(sid or made.get("sid") or ""),
                   "label": str(label or made.get("label") or "")[:80],
                   "block": int(block or made.get("block") or 0),
                   "ord": int(ord0 or 0),
                   "occurrence": str(occurrence or "")[:64],
                   "audio_ready": True, "body_frames": float(body_frames or 0.0),
                   "cues": int(cues or 0),
                   "ready_at": now, "made_for_s": round(now - float(made.get("since") or now), 1)}
            self._held[key] = row
            self._count("held")
            self._event("held", key=key, road=row["road"], lines=row["lines"],
                        block=row["block"],
                        seconds=round(row["seconds"], 1), made_for_s=row["made_for_s"])
            return dict(row)

    def forget(self, key: str, why: str = "") -> bool:
        """The round is not coming (refused, withdrawn, its task ended)."""
        with self.lock:
            key = str(key or "")
            was = self._making.pop(key, None) or self._held.pop(key, None)
            if not was:
                return False
            self._count("forgotten")
            self._event("forgotten", key=key, road=was.get("road"), why=str(why)[:160])
            return True

    def dispatched(self, oid: str, *, route: str, starts_at: float, seconds: float,
                   key: str = "", producer: str = "", lane: str = "", label: str = "",
                   media: str = "", delivery_id: str = "", sid: str = "",
                   lines: int = 0, block: int = 0, ord0: int = 0) -> dict[str, Any]:
        """An occurrence was handed to a transport. On the page route
        `starts_at` is its broadcast moment (which may be ahead of now); on
        the box it is now. A held round that this belongs to is released."""
        with self.lock:
            now = float(self.clock())
            oid = str(oid or "")
            route = str(route or ROUTE_PAGE)
            held = self._held.pop(str(key or ""), None) if key else None
            if key:
                self._making.pop(str(key), None)
            if held is not None:
                self._count("released")
                self._event("released", key=key, oid=oid, route=route,
                            waited_s=round(now - float(held.get("ready_at") or now), 1))
            seconds = max(0.0, float(seconds or 0.0))
            if seconds <= 0 and held is not None:
                seconds = float(held.get("seconds") or 0.0)
            starts_at = float(starts_at or now)
            # Was it stamped INSIDE air already sold on this route? The chain
            # is supposed to make that impossible; when it happens it is the
            # fault this module exists for and it is counted by name.
            free_at = self._air_free_at(now, route)
            if oid and starts_at + 0.5 < free_at and not any(
                    r["oid"] == oid and r["route"] == route for r in self._line):
                self._count("stamped_inside_sold_air")
                self._event("inside_sold_air", oid=oid, route=route,
                            by_s=round(free_at - starts_at, 1))
            row = None
            for held_row in self._line:
                if held_row["oid"] == oid and held_row["route"] == route and oid:
                    row = held_row
                    break
            if row is None:
                row = {"oid": oid, "route": route, "starts_at": starts_at,
                       "seconds": seconds, "dispatched_at": now,
                       "producer": str(producer or "")[:60], "lane": str(lane or ""),
                       "label": str(label or (held or {}).get("label") or "")[:80],
                       "media": str(media or (held or {}).get("media") or "").rsplit("/", 1)[-1].split("?")[0],
                       "sid": str(sid or (held or {}).get("sid") or ""),
                       "lines": int(lines or (held or {}).get("lines") or 0),
                       "block": int(block or (held or {}).get("block") or 0),
                       "ord": int(ord0 or (held or {}).get("ord") or 0),
                       "key": str(key or ""), "delivery_id": str(delivery_id or ""),
                       "heard_by": "", "last_position_s": None, "last_heard_at": 0.0,
                       "progressed_at": 0.0, "corrected_end": 0.0, "ended_at": 0.0,
                       "ended_why": "", "acks": 0, "stalled": False}
                self._line.append(row)
                self._line.sort(key=lambda r: (float(r["starts_at"]), float(r["dispatched_at"])))
                self._count("dispatched")
                self._count("dispatched:" + route)
            else:
                row["starts_at"] = min(float(row["starts_at"]), starts_at)
                row["seconds"] = max(float(row["seconds"]), seconds)
                if delivery_id:
                    row["delivery_id"] = str(delivery_id)
            if delivery_id:
                self._by_delivery[str(delivery_id)] = (oid, route)
                if len(self._by_delivery) > 600:
                    for old in list(self._by_delivery)[:300]:
                        self._by_delivery.pop(old, None)
            self._event("dispatched", oid=oid, route=route, starts_in_s=round(starts_at - now, 1),
                        seconds=round(seconds, 1), producer=producer, label=row["label"])
            self._prune(now)
            return dict(row)

    def heard(self, *, delivery_id: str = "", oid: str = "", route: str = ROUTE_PAGE,
              event: str = "", position_s: float | None = None,
              audible: float | None = None, listener: str = "",
              at: float | None = None) -> dict[str, Any] | None:
        """A listener's receipt. `playing` with a PROGRESSING position moves
        the end of the sounding clip onto the listener's clock; `ended`
        finishes it. A muted or silent receipt is a receipt of nothing."""
        with self.lock:
            now = float(at if at is not None else self.clock())
            found = None
            if delivery_id and str(delivery_id) in self._by_delivery:
                oid, route = self._by_delivery[str(delivery_id)]
            for row in self._line:
                if oid and row["oid"] == oid and row["route"] == route:
                    found = row
                    break
                if delivery_id and row.get("delivery_id") == str(delivery_id):
                    found = row
                    break
            if found is None:
                self._count("ack_unknown")
                return None
            event = str(event or "").lower()
            found["acks"] = int(found.get("acks") or 0) + 1
            if audible is not None and float(audible) <= 0:
                self._count("ack_silent")
                return dict(found)
            if event not in ("playing", "ended"):
                return dict(found)
            if position_s is not None:
                position = max(0.0, float(position_s))
                previous = found.get("last_position_s")
                progressed = previous is None or position > float(previous) + 0.02
                found["last_position_s"] = position
                found["last_heard_at"] = now
                found["heard_by"] = str(listener or "")[:40]
                if progressed:
                    found["progressed_at"] = now
                    found["stalled"] = False
                    remaining = max(0.0, float(found["seconds"]) - position)
                    found["corrected_end"] = now + remaining
                    # The first audible receipt of a clip announced ahead of
                    # its moment says when it REALLY started.
                    if float(found["starts_at"]) > now:
                        found["starts_at"] = now - position
                self._count("ack_heard")
            if event == "ended":
                found["ended_at"] = now
                found["ended_why"] = "the listener reported the end"
                self._count("ended:listener")
                self._event("ended", oid=found["oid"], route=found["route"], why="listener",
                            late_by_s=round(now - (float(found["starts_at"]) + float(found["seconds"])), 1))
            self._prune(now)
            return dict(found)

    def ended(self, oid: str = "", *, route: str = "", delivery_id: str = "",
              why: str = "") -> bool:
        """The transport says it is over (the box announce returned; the
        page delivery was dropped)."""
        with self.lock:
            now = float(self.clock())
            if delivery_id and str(delivery_id) in self._by_delivery:
                oid, route = self._by_delivery[str(delivery_id)]
            done = False
            for row in self._line:
                if oid and row["oid"] == str(oid) and (not route or row["route"] == route):
                    if not row.get("ended_at"):
                        row["ended_at"] = now
                        row["ended_why"] = str(why or "the transport reported the end")[:120]
                        self._count("ended:transport")
                        done = True
            self._prune(now)
            return done

    def force_end(self, why: str = "") -> int:
        """THE LADDER'S RUNG. Declare everything on the line over, so the next
        committed round is released. Only ever called when nothing has been
        heard for longer than any clip could run."""
        with self.lock:
            now = float(self.clock())
            n = 0
            for row in self._line:
                if not row.get("ended_at"):
                    row["ended_at"] = now
                    row["ended_why"] = "forced: " + str(why or "")[:100]
                    n += 1
            self._count("forced")
            self._event("forced", why=str(why)[:160], ended=n)
            self._prune(now)
            n += self.evict_stale(now)
            return n

    # ------------------------------------------------------- the answers

    def ask_fill(self, road: str, *, dialogue: bool | None = None,
                 priority: bool = False) -> dict[str, Any]:
        """May a filler road put something on the air NOW?

        NO while a committed round is ready and waiting (it goes next).
        NO for a dialogue road while a round is being made and nearly
        ready (a clip or a record may fill that wait; a second conversation
        may not). `priority` is a road the SHEET is owed - the memo from
        upstairs breaking in (#1261) - and it may go in front of a held
        round, never in front of a sounding one (the floor sees to that).
        In `off` mode every ask is allowed and the verdict is counted as
        `would_queue`, which is the census."""
        with self.lock:
            now = float(self.clock())
            self.evict_stale(now)
            road = str(road or "filler")
            if dialogue is None:
                dialogue = road in DIALOGUE_ROADS
            mode = self.mode()
            if mode == MODE_OFF:
                # Inert. Not counted, not judged, nothing to explain.
                return {"allow": True, "why": "", "enforced": False,
                        "after": 0.0, "queued": False, "mode": mode, "road": road}
            linear = mode == MODE_LINEAR
            why = ""
            head = self.head()
            if head is not None and not priority:
                wait = max(0.0, self._air_free_at(now, ROUTE_PAGE) - now)
                why = ("a committed %s round (%d lines, %ds) is ready and goes next%s"
                       % (head.get("road") or head.get("kind") or "?", int(head.get("lines") or 0),
                          int(head.get("seconds") or 0),
                          (" - the air frees in %ds" % int(wait)) if wait > 0 else ""))
            elif dialogue and not priority:
                soon = self._making_soon(now)
                if soon is not None:
                    left = max(0.0, float(soon.get("since") or now) + float(soon.get("eta_s") or 0) - now)
                    why = ("a %s round is being made (%d lines, about %ds left) - only a "
                           "clip or a record may fill the wait, not a second conversation"
                           % (soon.get("road") or soon.get("kind") or "?", int(soon.get("lines") or 0), int(left)))
            allow = not why or not linear
            after = self.reserve_until(now) if why else 0.0
            slot = self._asks.setdefault(road, {"allowed": 0, "queued": 0, "would_queue": 0,
                                                "last_why": "", "last_at": 0.0,
                                                "pushed_s": 0.0})
            slot["last_at"] = now
            if why:
                slot["last_why"] = why
                if linear:
                    slot["queued"] = int(slot["queued"]) + 1
                    slot["pushed_s"] = round(float(slot.get("pushed_s") or 0)
                                             + max(0.0, after - now), 1)
                    self._count("queued")
                    self._count("queued:" + road)
                else:
                    slot["would_queue"] = int(slot["would_queue"]) + 1
                    self._count("would_queue")
                    self._count("would_queue:" + road)
                self._event("queued" if linear else "would_queue", road=road,
                            why=why[:160], after_s=round(max(0.0, after - now), 1))
            else:
                slot["allowed"] = int(slot["allowed"]) + 1
            return {"allow": bool(allow), "why": why, "enforced": bool(linear and why),
                    "after": float(after if linear else 0.0),
                    "would_be_after": float(after),
                    "queued": bool(why and linear),
                    "mode": mode, "road": road}

    def air_free_at(self, route: str = ROUTE_PAGE) -> float:
        """When the air on `route` is free, on the listener's clock where a
        listener has spoken. `now` when nothing is on the line."""
        with self.lock:
            now = float(self.clock())
            self._prune(now)
            return self._air_free_at(now, route)

    def page_floor(self, exclude_key: str = "") -> float:
        """The earliest moment a new page clip may be stamped - 0.0 unless
        the switch actually says `linear`. A floor nobody threw a switch
        for is not a floor, and returning 0 is what makes `off` and
        `shadow` provably free of behaviour."""
        if not self.linear():
            return 0.0
        return self.reserve_until(exclude_key=exclude_key)

    def release_check(self, key: str) -> dict[str, Any]:
        """For the maker of a held round: are you the head, and when may
        you go? The page road announces `announce_early + lead` ahead."""
        with self.lock:
            now = float(self.clock())
            self._prune(now)
            head = self.head()
            free = self._air_free_at(now, ROUTE_PAGE)
            mine = head is not None and str(head.get("key")) == str(key)
            waits_on = ""
            sounding = self._sounding(now, ROUTE_PAGE)
            if sounding is not None:
                waits_on = str(sounding.get("label") or sounding.get("media") or sounding.get("oid") or "")
            return {"head": bool(mine or head is None), "air_free_at": free,
                    "wait_s": round(max(0.0, free - now), 1), "waits_on": waits_on,
                    "announce_at": max(now, free - self.page_lead_s - self.announce_early_s),
                    "go": bool((mine or head is None) and free - now <= self.page_lead_s + self.announce_early_s)}

    def head(self) -> dict[str, Any] | None:
        """THE NEXT THING ON THE AIR: the script ledger's next committed
        occurrence.

        Ordered by (block, ord) - the number the ledger gave the round when
        it was written down, which is the one thing on this station that is
        never rewritten - and by the moment it became ready only for rounds
        the ledger never saw. A round with no finished audio is not here at
        all: `hold` refused it and it is on the making shelf."""
        with self.lock:
            if not self._held:
                return None
            row = min(self._held.values(), key=self._rank)
            return dict(row)

    @staticmethod
    def _rank(row: dict[str, Any]) -> tuple:
        block = int(row.get("block") or 0)
        return (0 if block else 1, block, int(row.get("ord") or 0),
                float(row.get("ready_at") or 0))

    def reserve_until(self, now: float | None = None,
                      exclude_key: str = "") -> float:
        """THE PAGE FLOOR A FILLER MUST NOT GO IN FRONT OF.

        The air already sold on the page route, PLUS the slot the head
        held round is owed. That second half is the whole of #1246: a
        round reaches `hold` with its file welded and then waits - on
        this station a median of 52 seconds and a p90 of 136 - for the
        paced page road to reach its moment. Nothing was reserving that
        wait, so every sting, quip, station id and intro minted during it
        was stamped at the same instant the round was, and 416 of them in
        one day were heard INSIDE 111 rounds' waits. They are not
        refused: they are stamped after the round, which is the whole of
        "append to the end rather than cut in".

        Bounded by `hold_reserve_s`: a maker that died must never push
        the air forward for ever. Past it the round keeps its place in
        the sequence and stops reserving, and `state()` says so."""
        with self.lock:
            now = float(now if now is not None else self.clock())
            self._prune(now)
            free = self._air_free_at(now, ROUTE_PAGE)
            head = self.head()
            if head is None:
                return free
            if exclude_key and str(head.get("key")) == str(exclude_key):
                # THE ROUND DOES NOT WAIT FOR ITSELF. The head's own
                # producer asks for the floor when it stamps its air
                # moment; adding its own length to it would push every
                # round a round-length into the future, for ever.
                return free
            ready_for = now - float(head.get("ready_at") or now)
            if ready_for > self.hold_reserve_s:
                return free
            return free + max(0.0, float(head.get("seconds") or 0.0))

    def evict_stale(self, now: float | None = None) -> int:
        """A held round nobody released for `held_stale_s` was never handed
        to a transport - its task died or is wedged - and it must not hold
        every filler off the air for ever. Dropped, counted, named."""
        with self.lock:
            now = float(now if now is not None else self.clock())
            n = 0
            for key, row in list(self._held.items()):
                if now - float(row.get("ready_at") or now) > self.held_stale_s:
                    self._held.pop(key, None)
                    n += 1
                    self._count("held_stale")
                    self._event("held_stale", key=key, road=row.get("road"),
                                held_for_s=round(now - float(row.get("ready_at") or now), 1))
            for key, row in list(self._making.items()):
                if now - float(row.get("since") or now) > self.making_stale_s:
                    self._making.pop(key, None)
                    n += 1
                    self._count("making_stale")
                    self._event("making_stale", key=key, road=row.get("road"))
            return n

    # ------------------------------------------------------------ reading

    def sounding(self, route: str = "") -> dict[str, Any] | None:
        with self.lock:
            now = float(self.clock())
            self._prune(now)
            row = self._sounding(now, route)
            return self._public_row(row, now) if row else None

    def verdict(self) -> str:
        """One line for the Script view's header."""
        with self.lock:
            now = float(self.clock())
            self._prune(now)
            mode = self.mode()
            parts = [{MODE_LINEAR: "LINEAR (enforcing)",
                      MODE_SHADOW: "shadow (watching, enforcing nothing)",
                      MODE_OFF: "off"}.get(mode, mode)]
            sounding = self._sounding(now, "")
            if sounding is not None:
                pos = sounding.get("last_position_s")
                elapsed = (float(pos) + (now - float(sounding.get("last_heard_at") or now))
                           if pos is not None else now - float(sounding["starts_at"]))
                ends = self._effective_end(sounding)
                parts.append("sounding: %s (%s, %ds in, ends in %ds%s)"
                             % (sounding.get("label") or sounding.get("media") or sounding.get("oid")[:8],
                                sounding["route"], int(max(0.0, elapsed)), int(max(0.0, ends - now)),
                                ", STALLED" if sounding.get("stalled") else
                                ("" if pos is not None else ", estimated")))
            else:
                scheduled = [r for r in self._line if not r.get("ended_at") and float(r.get("eff_start", r["starts_at"])) > now]
                if scheduled:
                    nxt = scheduled[0]
                    parts.append("air free; %s starts in %ds"
                                 % (nxt.get("label") or nxt.get("media") or "a clip",
                                    int(float(nxt.get("eff_start", nxt["starts_at"])) - now)))
                else:
                    parts.append("air free")
            head = self.head()
            if head is not None:
                parts.append("next: %s round%s (%d lines, %ds, audio ready, waiting %ds)"
                             % (head.get("road") or head.get("kind") or "?",
                                (" block %d" % int(head["block"])) if head.get("block") else "",
                                int(head.get("lines") or 0),
                                int(head.get("seconds") or 0), int(now - float(head.get("ready_at") or now))))
                if len(self._held) > 1:
                    parts.append("+%d held" % (len(self._held) - 1))
            if self._making:
                soon = min(self._making.values(), key=lambda r: float(r.get("since") or 0) + float(r.get("eta_s") or 0))
                left = max(0.0, float(soon.get("since") or now) + float(soon.get("eta_s") or 0) - now)
                parts.append("making: %s (%d lines, about %ds left)"
                             % (soon.get("road") or soon.get("kind") or "?", int(soon.get("lines") or 0), int(left)))
            queued = int(self._counts.get("queued") or 0)
            would = int(self._counts.get("would_queue") or 0)
            if mode == MODE_LINEAR and queued:
                parts.append("queued asks: %d" % queued)
            elif mode != MODE_LINEAR and would:
                parts.append("would have queued: %d" % would)
            inside = int(self._counts.get("stamped_inside_sold_air") or 0)
            if inside:
                parts.append("stamped inside sold air: %d" % inside)
            notready = int(self._counts.get("not_ready") or 0)
            if notready:
                parts.append("rounds sent back for unfinished audio: %d" % notready)
            return " · ".join(parts)

    def state(self, limit: int = 12) -> dict[str, Any]:
        with self.lock:
            now = float(self.clock())
            self._prune(now)
            self.evict_stale(now)
            mode = self.mode()
            line = [self._public_row(r, now) for r in self._line]
            held = sorted(self._held.values(), key=lambda r: float(r.get("ready_at") or 0))
            making = sorted(self._making.values(), key=lambda r: float(r.get("since") or 0))
            free = self._air_free_at(now, ROUTE_PAGE)
            reserve = self.reserve_until(now)
            head = self.head()
            sounding = self.sounding("")
            # WHAT IS WAITING, AND WHY - one plain sentence per row, which
            # is the answer the operator asked for and not a table he has
            # to join in his head.
            waiting = []
            for row in held:
                mine = head is not None and str(head.get("key")) == str(row.get("key"))
                waiting.append({
                    "key": row.get("key"), "road": row.get("road"),
                    "kind": row.get("kind"), "block": row.get("block"),
                    "ord": row.get("ord"), "lines": row.get("lines"),
                    "seconds": round(float(row.get("seconds") or 0), 1),
                    "audio_ready": True, "media": row.get("media"),
                    "occurrence": row.get("occurrence"),
                    "waiting_s": round(now - float(row.get("ready_at") or now), 1),
                    "reserving": bool(mode == MODE_LINEAR and mine and
                                      now - float(row.get("ready_at") or now) <= self.hold_reserve_s),
                    "why": ("it is next and the air frees in %ds"
                            % int(max(0.0, free - now))) if mine else
                           ("block %s goes first" % (head or {}).get("block")
                            if (head or {}).get("block") else
                            "another committed round goes first")})
            for row in making:
                left = max(0.0, float(row.get("since") or now) + float(row.get("eta_s") or 0) - now)
                waiting.append({
                    "key": row.get("key"), "road": row.get("road"),
                    "kind": row.get("kind"), "block": row.get("block"),
                    "lines": row.get("lines"), "seconds": 0.0,
                    "audio_ready": False,
                    "waiting_s": round(now - float(row.get("since") or now), 1),
                    "reserving": False,
                    "why": str(row.get("why_not_ready")
                               or ("its audio is still being made, about %ds left" % int(left)))})
            jumpers = {k: dict(v) for k, v in self._asks.items()
                       if int(v.get("queued") or 0) or int(v.get("would_queue") or 0)}
            return {"schema_version": SCHEMA_VERSION, "mode": mode,
                    "linear": mode == MODE_LINEAR,
                    "active": mode in (MODE_SHADOW, MODE_LINEAR),
                    "linear_since": self._linear_since,
                    "verdict": self.verdict(),
                    "sounding": sounding,
                    "line": line,
                    "air_free_at": free,
                    "air_free_in_s": round(max(0.0, free - now), 1),
                    "page_floor": self.page_floor(),
                    "would_floor": reserve,
                    "reserved_for_head_s": round(max(0.0, reserve - free), 1),
                    "next": head,
                    "next_audio_ready": bool(head is not None),
                    "waiting": waiting,
                    "held": [dict(r, waiting_s=round(now - float(r.get("ready_at") or now), 1)) for r in held],
                    "making": [dict(r, for_s=round(now - float(r.get("since") or now), 1),
                                    left_s=round(max(0.0, float(r.get("since") or now) + float(r.get("eta_s") or 0) - now), 1))
                               for r in making],
                    "asks": {k: dict(v) for k, v in self._asks.items()},
                    "jumpers": jumpers,
                    "jumped_total": int(self._counts.get("queued") or 0),
                    "would_have_jumped_total": int(self._counts.get("would_queue") or 0),
                    "counts": dict(self._counts),
                    "recent": [dict(r) for r in self._recent[-max(1, int(limit)):]],
                    "events": [dict(e) for e in self._events[-max(1, int(limit)):]],
                    "now": now,
                    "started_at": self._started}

    # ---------------------------------------------------------- internals

    def _effective_end(self, row: dict[str, Any]) -> float:
        return float(row.get("eff_end") or (float(row["starts_at"]) + float(row["seconds"])))

    def _walk(self, now: float, route: str = "") -> list[dict[str, Any]]:
        """Lay the line out one after another per route: a clip starts no
        earlier than the previous one on its route ends, and the sounding
        one ends where the LISTENER says it does."""
        cursor: dict[str, float] = {}
        out = []
        for row in self._line:
            if route and row["route"] != route:
                continue
            start = max(float(row["starts_at"]), cursor.get(row["route"], 0.0))
            if row.get("ended_at"):
                end = float(row["ended_at"])
                start = min(start, end)
            elif row.get("corrected_end"):
                end = max(float(row["corrected_end"]), start)
            else:
                end = start + float(row["seconds"])
            row["eff_start"] = start
            row["eff_end"] = end
            if not row.get("ended_at"):
                cursor[row["route"]] = max(cursor.get(row["route"], 0.0), end)
            out.append(row)
        return out

    def _prune(self, now: float) -> None:
        self._walk(now)
        keep = []
        for row in self._line:
            over = bool(row.get("ended_at")) or (float(row.get("eff_end") or 0) + self.end_grace_s < now)
            if over:
                if not row.get("ended_at"):
                    row["ended_at"] = float(row.get("eff_end") or now)
                    row["ended_why"] = row.get("ended_why") or "its planned end passed"
                    self._count("ended:planned")
                self._recent.append(self._public_row(row, now))
                del self._recent[:-KEEP_RECENT]
                if row.get("delivery_id"):
                    self._by_delivery.pop(str(row["delivery_id"]), None)
                continue
            if (row.get("last_heard_at") and float(row.get("eff_start") or 0) <= now
                    and now - float(row.get("progressed_at") or row.get("last_heard_at") or now) > self.stall_s):
                if not row.get("stalled"):
                    row["stalled"] = True
                    self._count("stalled")
                    self._event("stalled", oid=row["oid"], route=row["route"],
                                at_s=row.get("last_position_s"))
            keep.append(row)
        self._line = keep

    def _sounding(self, now: float, route: str = "") -> dict[str, Any] | None:
        for row in self._walk(now, route):
            if row.get("ended_at"):
                continue
            if float(row.get("eff_start") or 0) <= now < float(row.get("eff_end") or 0):
                return row
        return None

    def _air_free_at(self, now: float, route: str = "") -> float:
        free = now
        for row in self._walk(now, route):
            if row.get("ended_at"):
                continue
            free = max(free, float(row.get("eff_end") or 0))
        return free

    def _making_soon(self, now: float) -> dict[str, Any] | None:
        best = None
        for row in self._making.values():
            left = float(row.get("since") or now) + float(row.get("eta_s") or 0) - now
            if left <= self.making_soon_s:
                if best is None or left < (float(best.get("since") or now) + float(best.get("eta_s") or 0) - now):
                    best = row
        return best

    def _public_row(self, row: dict[str, Any], now: float) -> dict[str, Any]:
        out = {k: row.get(k) for k in ("oid", "route", "starts_at", "seconds", "dispatched_at", "producer",
                                       "lane", "label", "media", "sid", "lines", "key", "delivery_id",
                                       "block", "ord",
                                       "heard_by", "last_position_s", "last_heard_at", "corrected_end",
                                       "ended_at", "ended_why", "acks", "stalled")}
        out["occurrence_id"] = row.get("oid")
        out["file"] = row.get("media")
        out["eff_start"] = row.get("eff_start", row.get("starts_at"))
        out["eff_end"] = row.get("eff_end", float(row.get("starts_at") or 0) + float(row.get("seconds") or 0))
        pos = row.get("last_position_s")
        if pos is not None and not row.get("ended_at"):
            out["position_s"] = round(float(pos) + max(0.0, now - float(row.get("last_heard_at") or now)), 1)
            out["position_basis"] = "listener"
        elif not row.get("ended_at"):
            out["position_s"] = round(max(0.0, now - float(out["eff_start"] or now)), 1)
            out["position_basis"] = "estimate"
        return out

    def _count(self, key: str) -> None:
        self._counts[key] = int(self._counts.get(key, 0)) + 1

    def _event(self, what: str, **fields: Any) -> None:
        row = {"at": float(self.clock()), "type": str(what)}
        row.update(fields)
        self._events.append(row)
        del self._events[:-self.keep_events]
        if self.log:
            try:
                self.log(what, row)
            except Exception:  # noqa: BLE001
                pass
        if self.events_path is not None:
            try:
                self.events_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.events_path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                if self.events_path.stat().st_size > 1_500_000:
                    lines = self.events_path.read_text(encoding="utf-8", errors="replace").splitlines()[-3000:]
                    self.events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            except OSError:
                pass


# ------------------------------------------------------------- the replay
#
# The dry run: given the station's own ledgers, what would the sequencer have
# done differently? It is a READING of records, so it can only answer the
# questions the records can - which is stated on every number it prints.


def replay(air_rows: Iterable[dict[str, Any]], ledger_rows: Iterable[dict[str, Any]], *,
           since: float, until: float) -> dict[str, Any]:
    """Replay a window of `air_log.jsonl` (upserted rows) and
    `script_ledger.jsonl` on the LISTENER's clock (`heard_ack_at`).

    Counts, per scripted block (a round the booth committed before it was
    heard):
      * `held_s`   - the wait between its commit and its first heard row;
      * `jumpers`  - unscripted rows heard INSIDE that wait: the fillers the
                     sequencer would have queued (by road);
      * `reentered` - whether the block's rows read as re-entering the order
                     (a later-numbered block was heard before them);
    and over the window:
      * `withdrawn_after_hold` - rounds refused at hand-over for no longer
                                 fitting, whose hold was eaten by jumpers;
      * `overlaps` - pairs of scripted blocks whose heard rows interleave on
                     the listener clock (the corrected page floor's case).
    """
    latest: dict[str, dict[str, Any]] = {}
    for row in air_rows:
        rid = str(row.get("id") or "")
        if rid:
            latest[rid] = row
    pos: dict[str, dict[str, Any]] = {}
    blocks: dict[int, dict[str, Any]] = {}
    for row in ledger_rows:
        lid = str(row.get("line_id") or "")
        pos[lid] = row
        b = int(row.get("block") or 0)
        blk = blocks.setdefault(b, {"block": b, "commit_at": float(row.get("at") or 0),
                                    "scripted": bool(row.get("scripted", True)),
                                    "kind": str(row.get("round") or row.get("kind") or ""),
                                    "rows": 0, "heard": []})
        blk["commit_at"] = min(blk["commit_at"], float(row.get("at") or 0))
        blk["rows"] += 1
        blk["scripted"] = blk["scripted"] and bool(row.get("scripted", True))
    heard: list[tuple[float, str, dict[str, Any], dict[str, Any] | None]] = []
    for rid, row in latest.items():
        t = float(row.get("heard_ack_at") or 0)
        if not t or not (since <= t < until):
            continue
        heard.append((t, rid, row, pos.get(rid)))
    heard.sort(key=lambda x: x[0])
    for t, rid, row, p in heard:
        if p:
            blocks[int(p["block"])]["heard"].append(t)
    out: dict[str, Any] = {"window": [since, until], "heard_rows": len(heard),
                           "scripted_blocks_heard": 0, "held_s": [], "jumpers": 0,
                           "jumpers_by_kind": {}, "blocks_with_jumpers": 0,
                           "reentered_blocks": 0, "reentered_rows": 0, "sheet_items_in_holds": 0,
                           "withdrawn_after_hold": 0, "overlaps": 0, "overlap_pairs": []}
    # re-entries on the listener clock, as the station numbers today
    maxb = -1
    reentered: set[int] = set()
    for t, rid, row, p in heard:
        if not p:
            continue
        b = int(p["block"])
        if b < maxb and blocks[b]["scripted"]:
            reentered.add(b)
            out["reentered_rows"] += 1
        maxb = max(maxb, b)
    out["reentered_blocks"] = len(reentered)
    # holds and jumpers
    for b, blk in blocks.items():
        if not blk["scripted"] or not blk["heard"]:
            continue
        first = min(blk["heard"])
        if not (since <= first < until):
            continue
        out["scripted_blocks_heard"] += 1
        held = max(0.0, first - blk["commit_at"])
        out["held_s"].append(round(held, 1))
        inside = [(t, row) for t, rid, row, p in heard
                  if blk["commit_at"] <= t < first and (not p or int(p["block"]) != b)
                  and (not p or not blocks[int(p["block"])]["scripted"])]
        # a sheet item (an advert entry) asks with priority and is allowed;
        # everything else heard inside the hold is a filler the sequencer
        # would have queued behind the round
        sheet = [(t, row) for t, row in inside if str(row.get("kind") or "") in SHEET_KINDS]
        jumped = [(t, row) for t, row in inside if str(row.get("kind") or "") not in SHEET_KINDS]
        out["sheet_items_in_holds"] += len(sheet)
        if jumped:
            out["blocks_with_jumpers"] += 1
            out["jumpers"] += len(jumped)
            for t, row in jumped:
                k = str(row.get("kind") or "?")
                out["jumpers_by_kind"][k] = int(out["jumpers_by_kind"].get(k, 0)) + 1
    # withdrawn rounds whose refusal says "no longer fits"
    seen_sids: set[str] = set()
    for rid, row in latest.items():
        if str(row.get("aired") or "") != "withdrawn":
            continue
        if not (since <= float(row.get("ts") or 0) < until):
            continue
        sid = str(row.get("sid") or "")
        if sid in seen_sids:
            continue
        seen_sids.add(sid)
        why = str(row.get("withdrawn_why") or "")
        if "longer than the time" in why or "left (" in why:
            out["withdrawn_after_hold"] += 1
    # overlaps: two scripted blocks whose heard rows interleave
    spans = [(min(blk["heard"]), max(blk["heard"]), b) for b, blk in blocks.items()
             if blk["scripted"] and len(blk["heard"]) >= 2 and since <= min(blk["heard"]) < until]
    spans.sort()
    for i in range(len(spans)):
        for j in range(i + 1, len(spans)):
            a0, a1, ab = spans[i]
            b0, b1, bb = spans[j]
            if b0 >= a1:
                break
            if b0 < a1 and b1 > a0:
                out["overlaps"] += 1
                out["overlap_pairs"].append([ab, bb, round(min(a1, b1) - b0, 1)])
    out["held_s"] = sorted(out["held_s"])
    held = out["held_s"]
    out["held_median_s"] = (held[len(held) // 2] if held else 0.0)
    out["held_p90_s"] = (held[int(len(held) * 0.9)] if held else 0.0)
    return out

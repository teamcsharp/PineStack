"""System 3's host adapter: the station hooks, the APIs and the ledger.

system3.py decides; this module connects those decisions to the station's
existing roads without replacing any of them (blueprint section 2):

    dj_banter  -> system3_direct_banter()   plans the scene before the
                                            write; ACTIVE replaces the #1386
                                            running order, SHADOW only records
               -> system3_door_roll()       the #1233 speakerbox doors roll
                                            System 3's seeded, logged draw
               -> system3_repair_*()        bounded repair of a banked round
               -> system3_bind_entry()      aligns the written script to the
                                            plan and stamps every turn's chain
                                            onto entry["turn_dice"], which the
                                            air already copies to each line
    _banter_beats -> handle.director        Mode B: observe, re-decide, write
    larder_prepare -> system3_perf_state()  ES -> performance_vector(state=)
    _sfx_cadence_additions ->
                  system3_sfx_direction()   intent terms + planned extra clips
                  system3_sfx_observe()     what the station actually played
    script_ledger_commit ->
                  system3_observe_ledger()  line id -> conversation/turn

Every hook returns quickly, never raises into the air path, and returns
None when System 3 is off or failed - which is the legacy station exactly.
All disk work happens on this module's own single-thread executors.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import collections
import copy
import hashlib
import json
from pathlib import Path
import re
import threading
import time


import system3
import system3_tables                     # [s3-calls] road structures
from system3_store import System3Store

# One writer and one reader of the ledger, never the default executor:
# #1311c / #1320 are the standing lesson that a long job on the shared pool
# starves every other to_thread in the process.
_STORE_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="system3-store")
_READ_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="system3-read")
_IO_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="system3-io")

MATERIAL_TIMEOUT = 8.0          # one speakbox draw; #1250 measured 6.5 s worst
CANDIDATE_TIMEOUT = 3.0
WRITE_BACKLOG = 400
RECENT = 80
# The station's seat names -> the script markers banter_turns returns.
_SEAT_OF = {"dj": "A", "host": "A", "cohost": "B", "third": "D", "caller": "C",
            "caller2": "E"}


class Handle:
    """One road call's System 3 conversation, carried through dj_banter."""

    def __init__(self, runtime, conv, config, active):
        self.runtime = runtime
        self.conv = conv
        self.config = config
        self.active = bool(active)
        self.sheet = ""
        self.rolls = []
        self.topic_at = 0
        self.topic_new = {}
        self.plan_ms = 0.0
        self.bank = False
        self.turns = 0            # [s3-glass] the LENGTH roll's turn count, when the round's length was a roll

    @property
    def id(self):
        return self.conv["identity"]["conversation_id"]


class LineHandle:
    """[s3-roads] One single-voice road call's System 3 conversation: the
    running-order clause for its writer, the line the LINE draw chose (when
    the road handed over candidates), the stamp its ledger row carries and
    the ES dims for its voice."""

    def __init__(self, runtime, conv, active):
        self.runtime = runtime
        self.conv = conv
        self.active = bool(active)
        self.sheet = ""
        self.line = None
        self.choice = None
        self.stamp = {}
        self.perf = None
        self.plan_ms = 0.0
        self._stream = None

    @property
    def id(self):
        return self.conv["identity"]["conversation_id"]

    def pick(self, label, candidates):
        """A draw the road makes at air over its own pool (the liner stack,
        a rotation): System 3's number, recorded on the conversation with
        the candidates. -1 when there is nothing to draw from."""
        n = len(candidates or [])
        if n <= 0:
            return -1
        if self._stream is None:
            self._stream = system3.DrawStream(str(self.conv["seed"]) + "|air")
        draw = self._stream.next("LINE:" + str(label))
        i = min(int(draw["u"] * n), n - 1)
        self.conv.setdefault("line_draws", []).append({
            "pool": str(label), "of": n, "index": i + 1, "u": draw["u"], "dice": draw["dice"],
            "candidates": [" ".join(str(c or "").split())[:80] for c in list(candidates)[:12]]})
        return i


class SfxGuyChooser:
    """[s3-roads] System 3's numbers for the SFX Guy's line at air: the plan's
    kind order, and one recorded draw per pool it picks from. Nothing here
    is the station's random; the observation says what was on offer."""

    def __init__(self, runtime, direction):
        self.runtime = runtime
        self.direction = direction
        self.stream = system3.DrawStream("%s|air|%s" % (direction.get("seed") or direction.get("conversation_id"),
                                                       direction.get("turn_id") or direction.get("turn")))
        self.order = [k for k in (direction.get("order") or []) if k in system3.SFXGUY_KINDS] or ["quip"]
        self.unavailable = []
        self.draws = []

    def takes(self, kind, available):
        """Does the plan's order put `kind` first among the kinds that have
        anything to say right now? A pool with nothing in it is recorded
        as fallen through, and the next kind in the order is his."""
        if not available:
            if kind not in self.unavailable:
                self.unavailable.append(kind)
            return False
        first = next((k for k in self.order if k not in self.unavailable), None)
        return first == kind

    def pick(self, label, candidates):
        n = len(candidates or [])
        if n <= 0:
            return -1
        draw = self.stream.next("SFXGUY:" + str(label))
        i = min(int(draw["u"] * n), n - 1)
        self.draws.append({"pool": str(label), "of": n, "index": i + 1, "u": draw["u"], "dice": draw["dice"],
                           "candidates": [" ".join(str(c or "").split())[:80] for c in list(candidates)[:12]]})
        return i

    def done(self, line, kind):
        self.runtime.sfxguy_spoke(self.direction, line, kind, chooser=self)


def _num(x):
    try:
        return int(float(x or 0))
    except (TypeError, ValueError):
        return 0


def _exchange_of(ctx):
    """The operator's numbered exchange ("1. ... 2. ..." on the topic desk):
    the line a round opens on and the answer to it, both word for word."""
    ex = ctx.get("exchange") if isinstance(ctx.get("exchange"), dict) else {}
    opener = " ".join(str(ex.get("opener") or "").split())[:400]
    reply = " ".join(str(ex.get("reply") or "").split())[:400]
    return {"opener": opener, "reply": reply} if opener and reply else {}


class System3Runtime:
    def __init__(self, host):
        self.host = host
        self.store = System3Store(host.data_path("system3.sqlite3"))
        self.settings = system3.normalise_settings({})
        self.config = system3.default_config()
        self.ready = False
        self.recent = collections.OrderedDict()
        self.turns_cache = {}
        self.pending = 0
        self.lock = threading.Lock()
        self.metrics = {
            "planned": 0, "active": 0, "shadow": 0, "failures": 0, "fallbacks": 0,
            "last_failure": "", "plan_ms_ema": 0.0, "plan_ms_max": 0.0,
            "material_ms_ema": 0.0, "material_timeouts": 0, "material_resolved": 0,
            "bound": 0, "repairs": 0, "verdicts": {}, "writes_dropped": 0,
            "doors": 0, "perf_applied": 0, "sfx_directed": 0, "sfx_extra": 0,
            "sfx_observed": 0, "lines_linked": 0, "mode_b_beats": 0, "started": time.time(),
            # [s3-roads] the SFX Guy's node at air, and single-voice lines
            "sfxguy_directed": 0, "sfxguy_spoke": 0, "lines_planned": 0, "lines_bound": 0,
        }

    # --- lifecycle ---------------------------------------------------------
    def load(self):
        self.settings = self.store.settings()
        self.config = self.store.config()
        self.ready = True

    def log(self, text, extra=""):
        try:
            self.host.pipeline_log("system3", str(text)[:400], extra=str(extra)[:1500])
        except Exception:  # noqa: BLE001
            pass

    def fail(self, where, exc):
        with self.lock:
            self.metrics["failures"] += 1
            self.metrics["fallbacks"] += 1
            self.metrics["last_failure"] = "%s: %s: %s" % (where, type(exc).__name__, str(exc)[:200])
        self.log("System 3 stood aside at %s - the legacy road carries this round" % where,
                 extra="%s: %s" % (type(exc).__name__, exc))

    def _ema(self, key, value, alpha=0.2):
        with self.lock:
            self.metrics[key] = round((1 - alpha) * float(self.metrics[key] or value) + alpha * value, 2)

    # --- persistence (never on the loop) -------------------------------------
    def persist(self, conv):
        """Queue a snapshot of the aggregate for the ledger. Bounded: a
        backlog past WRITE_BACKLOG drops the write and counts it rather
        than growing without end (the station's store lesson)."""
        with self.lock:
            if self.pending >= WRITE_BACKLOG:
                self.metrics["writes_dropped"] += 1
                return
            self.pending += 1
        snap = json.loads(json.dumps(conv, default=str))

        def job():
            try:
                self.store.save_conversation(snap)
            finally:
                with self.lock:
                    self.pending -= 1
        _STORE_POOL.submit(job)

    def observe_later(self, cid, family, body, turn_id=""):
        with self.lock:
            if self.pending >= WRITE_BACKLOG:
                self.metrics["writes_dropped"] += 1
                return
            self.pending += 1
        body = json.loads(json.dumps(body, default=str))

        def job():
            try:
                self.store.add_observation(cid, family, body, turn_id)
            finally:
                with self.lock:
                    self.pending -= 1
        _STORE_POOL.submit(job)

    def remember(self, conv):
        cid = conv["identity"]["conversation_id"]
        self.recent[cid] = conv
        self.recent.move_to_end(cid)
        while len(self.recent) > RECENT:
            self.recent.popitem(last=False)

    async def read(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(_READ_POOL, lambda: fn(*args))

    # --- inputs ------------------------------------------------------------
    def _inputs(self, ctx):
        dj = ctx.get("dj") or {}
        road = str(ctx.get("road") or "")               # [s3-roads] the road names itself
        if road not in system3.ROADS:
            road = "caller" if ctx.get("caller_name") else "banter"
        seats = list(ctx.get("seats") or ["A", "B"])
        names = {"A": str(dj.get("host_name") or "Host"), "B": str(dj.get("cohost_name") or "Co-host"),
                 "D": str(dj.get("third_name") or "Third seat"), "C": str(ctx.get("caller_name") or "Caller"),
                 "E": str(ctx.get("caller2_name") or "Second caller")}
        roles = {"A": "dj", "B": "cohost", "D": "third", "C": str(ctx.get("caller_seat") or "caller"), "E": "caller2"}
        weather = ctx.get("weather") if isinstance(ctx.get("weather"), dict) else {}
        moods = {}
        for seat, role in roles.items():
            dims = (weather.get("seats") or {}).get(role)
            if isinstance(dims, dict):
                moods[seat] = dims
        seed_text = str(ctx.get("seed_text") or "")
        angle = str(ctx.get("angle") or "")
        news = str(ctx.get("news_titles") or "")
        own = bool(ctx.get("own_material"))
        category = ("speakerbox" if seed_text else "internet_news" if news else
                    "own_material" if own else "angle" if angle else "free")
        topic = (angle or seed_text or news)[:400]
        words = [w for w in re.findall(r"[a-z]{5,}", (angle + " " + seed_text[:600]).lower())
                 if w not in system3._STOP]
        keywords = [w for w, _ in collections.Counter(words).most_common(8)]
        s2 = ctx.get("system2_job") if isinstance(ctx.get("system2_job"), dict) else {}
        budget = ctx.get("system2_budget") if isinstance(ctx.get("system2_budget"), dict) else {}
        target = float(budget.get("seconds") or 0)
        if not target:
            try:
                target = float((self.host.segment_budget_now(road) or {}).get("seconds") or 0)
            except Exception:  # noqa: BLE001
                target = 0.0
        try:
            turn_seconds = float(self.host.mean_turn_seconds(road) or 0)
        except Exception:  # noqa: BLE001
            turn_seconds = 0.0
        words_per_turn = float(budget.get("words_high") or (85 if ctx.get("bank") else 70))
        availability = {
            "speakbox": not own and road == "banter",
            "news": bool(news),
            "gazette": bool(ctx.get("gazette")),
            "manager": False, "gallery": False, "research": False,
        }
        # [rng-topics] the operator's topics board, for the TOPIC roll
        topic_bank = self._topic_bank(ctx)
        availability["topics"] = bool(topic_bank)
        return {
            "road": road, "at": time.time(), "seats": seats, "names": names, "roles": roles,
            "initial_emotions": moods, "turns": int(ctx.get("lines") or 8),
            "target_seconds": target, "turn_seconds": turn_seconds,
            "words_per_turn": words_per_turn, "deadline": float(s2.get("deadline") or 0),
            "trace_id": str(s2.get("trace_id") or ""), "system2_slot_id": str(s2.get("slot_id") or ""),
            "system2_job_id": str(s2.get("job_id") or ""),
            "schedule_occurrence_id": str(ctx.get("sid") or ""),
            "subject": {"topic": topic, "category": category, "seeded": bool(seed_text),
                        "authority": "obligated" if (seed_text or angle or news or own or s2) else "free",
                        "sources": [x for x in [str(ctx.get("seed_file") or "")] if x],
                        "keywords": keywords, "angle": angle[:300],
                        "exchange": _exchange_of(ctx)},
            "availability": availability,
            "speakerbox_rates": {"full": float(dj.get("speakbox_full_swath_rate") or 0),
                                 "prepend": float(dj.get("speakbox_prepend_rate") or 0),
                                 "append": float(dj.get("speakbox_append_rate") or 0)},
            "bank": bool(ctx.get("bank")), "approach": str((ctx.get("approach") or {}).get("id") or ""),
            "seed_file": str(ctx.get("seed_file") or ""),
            # The seed passage itself, so an opened line can show which of
            # its words the opening turn read out (frontend composeLine).
            "seed_text": " ".join(seed_text.split())[:1500],
            "topic_bank": topic_bank,
            # [s3-calls] what a call needs to be built from System 3's structure
            "call": self._call_of(ctx),
            # [s3-roads] a message, not a conversation (never cut on the air)
            "whole": bool(ctx.get("whole")),
            # [s3-glass] the round's length: the dial's random stood here (a
            # free round) - System 3 rolls it over the same range instead
            "lines_rolled": bool(ctx.get("lines_rolled")),
            "lines_min": _num(ctx.get("lines_min")), "lines_max": _num(ctx.get("lines_max")),
            "lines_base": _num(ctx.get("lines_base")),
            # [s3-roads] the SFX Guy's dials, for his node on every host turn
            "sfxguy": {"rate": _num(dj.get("sfxguy_rate")), "warp": _num(dj.get("sfxguy_warp")),
                       "voice": bool(dj.get("drop_voice")), "every_units": _num(dj.get("sfxguy_every_units"))},
        }

    def _call_of(self, ctx):
        """[s3-calls] Who is ringing (first name), who else is in the booth,
        the call's own passage (the one call_speakerbox_report looks for),
        whether it is a story call-back, and the scenario direction."""
        name = " ".join(str(ctx.get("caller_name") or "").split())
        if not name:
            return {}
        meta = ctx.get("call_meta") if isinstance(ctx.get("call_meta"), dict) else {}
        dj = ctx.get("dj") or {}
        clause = ""
        if isinstance(meta.get("scenario"), dict):
            try:
                clause = str(self.host.call_scenario_clause(meta["scenario"]) or "")
            except Exception:  # noqa: BLE001
                clause = ""
        return {"name": name, "first": name.split()[0], "other": str(dj.get("cohost_name") or ""),
                "topic": str(meta.get("topic") or "")[:400],
                # [s3-cut] at a sentence end, never where a count fell
                "speakerbox": system3.sentence_cut(str(meta.get("speakerbox_text") or ctx.get("seed_text") or ""), 600),
                "story": bool(meta.get("story")), "scenario_clause": clause[:1500]}

    def _topic_bank(self, ctx):
        """[rng-topics] The board, least-sprung first, as System 3's TOPIC
        roll draws from it - the only road a topic takes into a round now.
        Empty when the round carries the operator's own exchange, or on a
        host with no board."""
        if _exchange_of(ctx).get("opener"):
            return []
        try:
            rows = self.host.read_bombshells() or []
        except Exception:  # noqa: BLE001
            return []
        out = []
        for r in rows:
            if not isinstance(r, dict) or not r.get("id"):
                continue
            text = " ".join(str(r.get("text") or "").split())
            if not 12 <= len(text) <= 400:
                continue
            out.append({"id": str(r["id"]), "text": text, "used": int(r.get("used") or 0),
                        "reply": " ".join(str(r.get("reply") or "").split())[:400]})
        out.sort(key=lambda r: r["used"])
        return out[:60]

    # --- planning --------------------------------------------------------------
    async def direct(self, ctx):
        """Plan the round (Mode A). ACTIVE hands the running order back;
        SHADOW records what System 3 would have done and hands back a
        handle the road never reads for its words."""
        if not self.ready:
            return None
        road = str(ctx.get("road") or "")               # [s3-roads]
        if road not in system3.ROADS or road in system3_tables.LINE_ROADS:
            road = "caller" if ctx.get("caller_name") else "banter"
        mode = system3.road_mode(self.settings, road)
        if mode == "off":
            return None
        try:
            inputs = self._inputs(ctx)
            config = self.config
            started = time.perf_counter()
            conv = system3.new_conversation(inputs, config, self.settings)
            conv["mode"] = mode
            handle = Handle(self, conv, config, mode == "active")
            handle.bank = bool(ctx.get("bank"))
            call = inputs.get("call") or {}
            if road == "caller" and call.get("first") and not call.get("story"):
                # [s3-calls] the call is built by System 3's own call structure
                system3.plan_call(conv, config, inputs)
                handle.sheet = system3.render_call_sheet(conv) if handle.active else ""
            elif road == "caller":
                rows = [(int(n), seat, work) for n, seat, work in
                        re.findall(r"(?m)^\s*(\d+)\s+([ABCDE])\s+[-–—]\s*(.+?)\s*$", ctx.get("call_sheet") or "")]
                system3.plan_protocol(conv, config, rows)
                handle.sheet = system3.annotate_protocol(conv, ctx.get("call_sheet") or "") if handle.active else ""
            elif road != "banter" and (system3.road_structure(config, road) or {}).get("legs"):
                # [s3-roads] a segment built from its own legs (recap, ad,
                # news, manager, memo, gallery, mixtape, open_show, fan_mail,
                # guest - and any road the operator gives a structure)
                system3.plan_legs(conv, config, inputs, road)
            else:
                system3.plan_more(conv, config)
            handle.plan_ms = round((time.perf_counter() - started) * 1000, 2)
            if conv.get("length_roll"):
                handle.turns = int(conv["length_roll"].get("turns") or 0)     # [s3-glass]
            self._ema("plan_ms_ema", handle.plan_ms)
            with self.lock:
                self.metrics["planned"] += 1
                self.metrics[mode] += 1
                self.metrics["plan_ms_max"] = max(self.metrics["plan_ms_max"], handle.plan_ms)
            if handle.active and road != "caller":
                await self._resolve_material(handle, ctx)
                handle.sheet = (system3.render_legs_sheet(conv) if conv.get("road_structure")
                                else system3.render_sheet(conv))
                handle.rolls = system3.legacy_rolls(conv)
                for t in conv["turns"]:
                    if t.get("topic_change") and (t.get("topic_material") or {}).get("text"):
                        handle.topic_at = t["index"] + 1
                        handle.topic_new = dict(t["topic_material"])
                        break
            # [rng-topics] a topic the roulette raised on a round that airs is
            # a use of it (the TOPIC roll or CTS1's topics database): the
            # least-sprung weigh most at the next draw.
            if handle.active:
                for _tid in dict.fromkeys(conv.get("topics_used") or []):
                    try:
                        self.host.use_bombshell(_tid, "")
                    except Exception:  # noqa: BLE001
                        pass
            conv["plan"] = {"sheet": handle.sheet, "plan_ms": handle.plan_ms, "active": handle.active}
            self.remember(conv)
            self.persist(conv)
            self._flow(conv, "planned %d turns, %d decisions (%s, %.1f ms)"
                       % (len(conv["turns"]), len(conv["decision_events"]), mode, handle.plan_ms))
            return handle
        except Exception as exc:  # noqa: BLE001
            self.fail("planning", exc)
            return None

    async def direct_line(self, ctx):
        """[s3-roads] A single-voice road asks: a record link, a station ID,
        the manager's own page, a stock interjection, a produced spot. One
        seat, the legs of the road's structure, ES rolled on each - and,
        when the road hands over candidate lines, a LINE draw among them
        with every candidate and its weight recorded (the Rolodex where
        the station used to call random.choice()). ACTIVE: the writer gets
        the running-order clause and the chosen line is System 3's. SHADOW:
        recorded only. None: off, or a fault - the road as it always was."""
        if not self.ready:
            return None
        road = str(ctx.get("road") or "")
        if road not in system3.ROADS:
            return None
        mode = system3.road_mode(self.settings, road)
        if mode == "off":
            return None
        try:
            started = time.perf_counter()
            dj = ctx.get("dj") if isinstance(ctx.get("dj"), dict) else {}
            who = str(ctx.get("who") or "dj")
            seat = str(ctx.get("seat") or _SEAT_OF.get(who) or ("D" if who == "drop" else "A"))
            if seat not in ("A", "B", "C", "D", "E"):
                seat = "A"
            name = str(ctx.get("name") or {"dj": dj.get("host_name"), "cohost": dj.get("cohost_name"),
                                           "third": dj.get("third_name")}.get(who) or who)
            cands = []
            for i, c in enumerate(ctx.get("candidates") or []):
                if isinstance(c, dict) and str(c.get("text") or "").strip():
                    cands.append({"id": str(c.get("id") or i), "text": " ".join(str(c["text"]).split())[:400],
                                  "weight": float(c.get("weight", 1.0) or 0), "why": list(c.get("why") or [])})
                elif isinstance(c, str) and c.strip():
                    cands.append({"id": str(i), "text": " ".join(c.split())[:400], "weight": 1.0, "why": []})
            context = " ".join(str(ctx.get("context") or ctx.get("text") or "").split())
            inputs = {
                "road": road, "at": time.time(), "seats": [seat], "names": {seat: name}, "roles": {seat: who},
                "turns": 1, "target_seconds": 0.0, "words_per_turn": 40.0,
                "schedule_occurrence_id": str(ctx.get("sid") or ""),
                "subject": {"topic": context[:400], "category": "own_material", "seeded": False,
                            "authority": "obligated", "sources": [], "keywords": [], "angle": ""},
                "availability": {}, "speakerbox_rates": {}, "bank": bool(ctx.get("bank")),
                "candidates": cands, "candidates_from": str(ctx.get("candidates_from") or ""),
                "line_text": " ".join(str(ctx.get("text") or "").split())[:600],
                "sfxguy": {"voice": False},
            }
            config = self.config
            conv = system3.new_conversation(inputs, config, self.settings)
            conv["mode"] = mode
            system3.plan_line(conv, config, inputs)
            handle = LineHandle(self, conv, mode == "active")
            handle.plan_ms = round((time.perf_counter() - started) * 1000, 2)
            choice = conv.get("line_choice") or {}
            if cands and choice.get("id") is not None:
                for i, c in enumerate(cands):
                    if c["id"] == str(choice["id"]):
                        handle.choice, handle.line = i, c["text"]
                        break
            first = conv["turns"][0] if conv["turns"] else {}
            handle.sheet = system3.render_legs_sheet(conv) if handle.active else ""
            handle.stamp = {"conversation_id": conv["identity"]["conversation_id"], "mode": mode,
                            "turn_id": str(first.get("turn_id") or ""), "road": road,
                            "seed": conv["seed"], "config_hash": conv["config_hash"]}
            perf = first.get("performance") or {}
            dims = perf.get("dims") if isinstance(perf.get("dims"), dict) else None
            handle.perf = ({d: float(dims.get(d) or 0) for d in system3.EMOTION_DIMS}
                           if dims and handle.active else None)
            conv["plan"] = {"sheet": handle.sheet, "plan_ms": handle.plan_ms, "active": handle.active,
                            "line": handle.line, "choice": handle.choice}
            self._ema("plan_ms_ema", handle.plan_ms)
            with self.lock:
                self.metrics["planned"] += 1
                self.metrics[mode] += 1
                self.metrics["lines_planned"] += 1
                self.metrics["plan_ms_max"] = max(self.metrics["plan_ms_max"], handle.plan_ms)
            self.remember(conv)
            self.persist(conv)
            self._flow(conv, "planned a %s line: %d decisions (%s, %.1f ms)%s"
                       % (road, len(conv["decision_events"]), mode, handle.plan_ms,
                          (", drew %d of %d" % (handle.choice + 1, len(cands))) if handle.choice is not None else ""))
            return handle
        except Exception as exc:  # noqa: BLE001
            self.fail("line planning", exc)
            return None

    def bind_line(self, handle, text):
        """[s3-roads] The single-voice line is written (or chosen): the
        words join the conversation, and the row the road commits carries
        handle.stamp so the ledger links the line to its node."""
        try:
            if not handle or not isinstance(handle, LineHandle):
                return
            conv = handle.conv
            words = " ".join(str(text or "").split())
            if conv["turns"]:
                t = conv["turns"][-1]
                t["text"] = words[:1500]
                t["script_index"] = 0 if words else None
                t["status"] = "generated" if words else "dropped"
            conv["actual"] = [{"speaker": (conv["turns"][-1]["speaker"] if conv["turns"] else "A"),
                               "text": words[:600]}]
            conv["identity"]["script_digest"] = hashlib.sha256(words.encode("utf-8")).hexdigest()[:16]
            conv["bindings"] = [{"turn_id": t["turn_id"], "script_index": 0} for t in conv["turns"][-1:]]
            conv["status"] = ("bound" if handle.active else "shadowed") if words else "dropped"
            with self.lock:
                self.metrics["lines_bound"] += 1
            self.remember(conv)
            self.persist(conv)
        except Exception as exc:  # noqa: BLE001
            self.fail("line bind", exc)

    def _flow(self, conv, summary):
        try:
            self.host.station_flow_event(
                "draft", "system3", "System 3 " + summary,
                {"conversation_id": conv["identity"]["conversation_id"], "mode": conv["mode"],
                 "seed": conv["seed"], "config": conv["config_hash"]},
                trace_id=conv["identity"]["trace_id"])
        except Exception:  # noqa: BLE001
            pass

    async def _resolve_material(self, handle, ctx):
        """Fetch the speakerbox passages the plan asked for, through the
        station's own speakbox_quote (locks, themes, cooldowns, rotation all
        intact), each bounded. A request that cannot be met in time is
        recorded as unmet and its mark falls back to NONE - never a wait
        the air can hear."""
        conv = handle.conv
        exclude = str(ctx.get("seed_file") or "")
        for req in conv["material_requests"]:
            if req.get("resolved") is not None:
                continue
            started = time.perf_counter()
            try:
                # [s3-cut] ask for a little more than the budget and cut it
                # back to a sentence end: a passage read out word for word
                # must not stop where a character count fell
                _chars = int(req.get("chars") or 420)
                got = await asyncio.wait_for(
                    self.host.speakbox_quote(exclude=exclude, most=8 if req["mode"] == "FULL_SWATH" else 6 if req["mode"] == "TOPIC" else 4,
                                             cap=_chars + 240),
                    timeout=MATERIAL_TIMEOUT)
            except asyncio.TimeoutError:
                got = None
                with self.lock:
                    self.metrics["material_timeouts"] += 1
                req["resolved"] = {"ok": False, "why": "timed out after %.0fs" % MATERIAL_TIMEOUT}
            except Exception as exc:  # noqa: BLE001
                got = None
                req["resolved"] = {"ok": False, "why": "%s: %s" % (type(exc).__name__, str(exc)[:120])}
            ms = round((time.perf_counter() - started) * 1000, 1)
            self._ema("material_ms_ema", ms)
            if got and got.get("text"):
                material = {"file": str(got.get("file") or ""), "text": system3.sentence_cut(got["text"], _chars),
                            "mind": str(got.get("mind") or ""), "lines": list(got.get("lines") or [])[:12]}
                req["resolved"] = {"ok": True, "file": material["file"], "ms": ms}
                with self.lock:
                    self.metrics["material_resolved"] += 1
                pos = await self._passage_position(material)
                cands = await self._doc_candidates(material.get("mind", ""))
                self._attach(conv, req, material)
                system3_event = {
                    "event_id": "%s:m:%s" % (conv["identity"]["conversation_id"], req["request_id"]),
                    "turn_id": req["turn_id"], "request_id": req["request_id"], "mode": req["mode"],
                    "selected": {"file": material["file"], "passage": pos},
                    "candidates": cands, "ms": ms,
                    "draw": "the station's speakbox_quote: weighted, unrepeated rotation with locks and cooldowns; "
                            "no System 3 random number chose this document",
                    "decided_by": req.get("event_id")}
                conv.setdefault("material", []).append(system3_event)
                if exclude == "":
                    exclude = material["file"]
            else:
                req.setdefault("resolved", {"ok": False, "why": "the speakbox returned nothing"})
                self._attach(conv, req, None)

    def _attach(self, conv, req, material):
        for t in conv["turns"]:
            if t["turn_id"] != req["turn_id"]:
                continue
            if req["mode"] == "TOPIC":
                if material:
                    t["topic_material"] = material
                continue
            for sb in t.get("speakerbox") or []:
                if sb.get("request_id") == req["request_id"]:
                    if material:
                        sb["material"] = material
                    else:
                        sb["unmet"] = (req.get("resolved") or {}).get("why", "unmet")

    async def _passage_position(self, material):
        """"passage 18/43": where in its document the drawn passage sits -
        counted in the lines the draw was cut from (the station's harvest
        of the document, or its sentences when none is kept; GET
        /api/speakbox/{name}?lines=1 serves the same list), so the number
        is the line the Messenger's line reel lands on. [line-reel]"""
        def work():
            try:
                mind = material.get("mind", "")
                files = [p for p in self.host.speakbox_all(mind) if p.name == material["file"]]
                if not files:
                    return None
                gems = getattr(self.host, "speakbox_gems", None)
                split = getattr(self.host, "speakbox_lines", None)
                body = getattr(self.host, "speakbox_body", None)
                lines = list(gems(files[0], mind) or []) if gems else []
                if not lines and split and body:
                    lines = list(split(body(files[0])) or [])
                if not lines:
                    text = files[0].read_text(errors="replace")
                    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                first = str((material.get("lines") or [material["text"]])[0]).strip()
                for i, ln in enumerate(lines):
                    if first and str(ln).strip() == first:
                        return {"index": i + 1, "of": len(lines)}
                probe = first[:60].strip()[:40]
                for i, ln in enumerate(lines):
                    if probe and probe in str(ln):
                        return {"index": i + 1, "of": len(lines)}
                return {"index": None, "of": len(lines)}
            except Exception:  # noqa: BLE001
                return None
        try:
            return await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(_IO_POOL, work),
                                          timeout=CANDIDATE_TIMEOUT)
        except Exception:  # noqa: BLE001
            return None

    async def _doc_candidates(self, mind):
        """The documents the draw was made from, with the weight the
        station gave each - the real candidate set for the Rolodex."""
        def work():
            try:
                weights = self.host.mind_weights(mind)
                files = self.host.speakbox_files(mind)
                return [{"id": p.name, "weight": int(self.host.speakbox_weight(p.name, weights, mind))}
                        for p in files[:400]]
            except Exception as exc:  # noqa: BLE001
                return {"unavailable": "%s: %s" % (type(exc).__name__, str(exc)[:100])}
        try:
            return await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(_IO_POOL, work),
                                          timeout=CANDIDATE_TIMEOUT)
        except Exception:  # noqa: BLE001
            return {"unavailable": "the document list did not come back in %.0fs" % CANDIDATE_TIMEOUT}

    # --- the doors -----------------------------------------------------------
    def door_roll(self, handle, door):
        if not handle or not handle.active:
            return None
        try:
            got = (handle.conv.get("doors") or {}).get(door)
            if not got:
                return None
            with self.lock:
                self.metrics["doors"] += 1
            return float(got["u"])
        except Exception as exc:  # noqa: BLE001
            self.fail("door", exc)
            return None

    # --- repair ------------------------------------------------------------------
    def repair_wanted(self, handle, script):
        """Only a banked (or System 2 prepared) round is repaired: a live
        round has nobody waiting for a second model visit except the
        listener, and dead air outranks compliance."""
        if not handle or not handle.active or not self.settings.get("repair", True):
            return False
        if not handle.bank and not handle.conv["identity"].get("system2_job_id"):
            return False
        try:
            turns = self.host.banter_turns(script or "")
            val = system3.validate(handle.conv, turns)
            handle.conv["pre_repair"] = {k: val[k] for k in ("score", "verdict", "seat_order", "turn_ratio")}
            if val["repair_wanted"]:
                with self.lock:
                    self.metrics["repairs"] += 1
                self.observe_later(handle.id, "REPAIR", {"why": "seat order %.2f, turns %.2f" % (
                    val["seat_order"], val["turn_ratio"]), "validation": handle.conv["pre_repair"]})
            return bool(val["repair_wanted"])
        except Exception as exc:  # noqa: BLE001
            self.fail("repair check", exc)
            return False

    def repair_clause(self, handle):
        if not handle or not handle.active or not handle.sheet:
            return ""
        return ("\n\nFOLLOW THIS RUNNING ORDER - the draft skipped it:" + handle.sheet)

    # --- Mode B ------------------------------------------------------------------
    def director(self, handle):
        """The turn-by-turn director for the banked beat chain, or None.

        Called before each beat with the turns written so far: they are
        observed (validated against their intent, the state moved by what
        was actually said), the rest of the plan is decided again from
        there, and the beat writer is handed the new rows."""
        if (not handle or not handle.active or self.settings.get("generation_mode") != "turn"
                or handle.conv["identity"]["road_kind"] != "banter"):
            return None
        conv = handle.conv
        seen = {"n": 0}

        async def step(made, cursor, rows):
            try:
                if cursor <= 0 or cursor >= len(conv["turns"]):
                    return rows
                for i in range(seen["n"], min(len(made), len(conv["turns"]))):
                    system3.observe(conv, i, made[i][1])
                seen["n"] = len(made)
                system3.replan(conv, handle.config, cursor, until=len(conv["turns"]) or None)
                await self._resolve_material(handle, {"seed_file": conv["inputs"].get("seed_file")})
                with self.lock:
                    self.metrics["mode_b_beats"] += 1
                self.persist(conv)
                out = [{"turn": t["index"] + 1, "seat": t["speaker"], "work": system3._row_work(t, conv)}
                       for t in conv["turns"][cursor:]]
                return out or rows
            except Exception as exc:  # noqa: BLE001
                self.fail("turn-by-turn", exc)
                return rows
        return step

    # --- bind (script freeze) ------------------------------------------------------
    def bind_entry(self, entry, handle):
        """The script is written: align it with the plan, validate it, and
        stamp each turn's decision chain where the air already carries dice
        (entry["turn_dice"] -> every script-ledger line's `dice`)."""
        if not handle or not isinstance(entry, dict):
            return
        conv = handle.conv
        try:
            turns = self.host.banter_turns(str(entry.get("script") or ""),
                                           str(entry.get("caller_name") or ""),
                                           str(entry.get("caller2_name") or ""))
            conv["identity"]["script_digest"] = hashlib.sha256(
                str(entry.get("script") or "").encode("utf-8")).hexdigest()[:16]
            for door, rec in (entry.get("quotes") or {}).items():
                got = (conv.get("doors") or {}).get(door) or {}
                self.observe_later(conv["identity"]["conversation_id"], "SPEAKERBOX", {
                    "stage": "door-outcome", "door": door, "applies": rec.get("applies"),
                    "why": rec.get("why"), "rate": rec.get("rate"), "lift": rec.get("lift"),
                    "roll": rec.get("roll"), "hit": rec.get("hit"), "file": rec.get("file"),
                    "turns": rec.get("turns"), "system3_roll": got.get("u"),
                    "rolled_by": "system3" if handle.active and got else "station",
                    "decided_by": got.get("event_id")})
            if handle.active:
                mapping, val = system3.bind(conv, turns)
                conv["shadow_bindings"] = []
                dice = {}
                legacy = {r["turn"] - 1: r for r in handle.rolls}
                for t in conv["turns"]:
                    at = mapping.get(t["index"])
                    if at is None:
                        continue
                    row = legacy.get(t["index"]) or {}
                    dice[str(at)] = {
                        "roll": row.get("roll"), "hard": row.get("hard"), "axis": row.get("axis") or "emotion",
                        "lean": row.get("lean"), "text": row.get("text") or (t.get("performance") or {}).get("emotion"),
                        "answers": row.get("answers"), "band": [0.0, 1.0],
                        "s3": system3.turn_stamp(conv, t)}
                entry["turn_dice"] = dice
                if handle.rolls:
                    entry["dice"] = handle.rolls
                # The passages System 3 dealt, filed against their own
                # documents (#1386 F3) and held from the rewrite (#838).
                for t in conv["turns"]:
                    for sb in t.get("speakerbox") or []:
                        mat = sb.get("material") or {}
                        if not mat.get("text"):
                            continue
                        entry.setdefault("passage_source", []).append(
                            {"file": mat["file"], "text": mat["text"][:600], "door": "system3:" + sb["mode"].lower()})
                        if sb["mode"] in ("PREPEND", "APPEND", "FULL_SWATH") and t.get("script_index") is not None:
                            entry.setdefault("dealt", []).append(["system3", t["speaker"], mat["text"]])
                        try:
                            self.host.speakbox_remember(dict(mat))
                        except Exception:  # noqa: BLE001
                            pass
                with self.lock:
                    self.metrics["bound"] += 1
                    v = val["verdict"]
                    self.metrics["verdicts"][v] = self.metrics["verdicts"].get(v, 0) + 1
            else:
                mapping = system3.align(conv, turns)
                conv["comparison"] = system3.compare_shadow(conv, turns)
                conv["actual"] = [{"speaker": m, "text": str(x)[:600]} for m, x in turns]
                # Which written line each planned turn lines up with, so the
                # Script page can show a shadow plan beside the words that
                # actually aired on that seat.
                conv["shadow_bindings"] = [{"turn_id": t["turn_id"], "script_index": mapping.get(t["index"])}
                                           for t in conv["turns"]]
                conv["status"] = "shadowed"
            entry["system3"] = {"conversation_id": conv["identity"]["conversation_id"],
                                "trace_id": conv["identity"]["trace_id"], "mode": conv["mode"],
                                "revision": conv["identity"]["revision"], "seed": conv["seed"],
                                "config_hash": conv["config_hash"],
                                "verdict": (conv.get("validation") or {}).get("verdict"),
                                # script turn index -> planned turn, which the
                                # air copies onto every script-ledger line.
                                "turns": {str(i): t["turn_id"] for t in conv["turns"]
                                          for i in [mapping.get(t["index"])] if i is not None}}
            self.remember(conv)
            self.persist(conv)
            self._flow(conv, "%s: %s" % ("bound" if handle.active else "shadow compared",
                                         (conv.get("validation") or conv.get("comparison") or {}).get(
                                             "verdict", (conv.get("comparison") or {}).get("seat_similarity"))))
        except Exception as exc:  # noqa: BLE001
            self.fail("bind", exc)

    # --- the air ---------------------------------------------------------------
    def _turn_of(self, meta, text, who=""):
        """(conversation id, turn index) of a spoken chunk, by its words in
        the round's CURRENT script - the same parse the bind indexed."""
        s3 = (meta or {}).get("system3") or {}
        cid = s3.get("conversation_id")
        if not cid:
            return None, None
        script = str(meta.get("script") or "")
        key = cid + ":" + hashlib.md5(script.encode("utf-8")).hexdigest()[:10]
        turns = self.turns_cache.get(key)
        if turns is None:
            turns = self.host.banter_turns(script, str(meta.get("caller_name") or ""),
                                           str(meta.get("caller2_name") or ""))
            self.turns_cache[key] = turns
            if len(self.turns_cache) > RECENT:
                self.turns_cache.pop(next(iter(self.turns_cache)))
        # The WHOLE chunk, not its opening: two turns can start alike, and
        # the one that starts alike is not the one being rendered.
        probe = " ".join(str(text or "").lower().split())[:400]
        if len(probe) < 4:
            return cid, None
        seat = _SEAT_OF.get(str(who or ""), "")
        hits = [i for i, (_m, said) in enumerate(turns)
                if probe in " ".join(str(said or "").lower().split())]
        mine = [i for i in hits if seat and str(turns[i][0])[:1] == seat]
        if len(mine) == 1 or (mine and len(set(mine)) == len(mine)):
            return cid, mine[0]
        return cid, (hits[0] if len(hits) == 1 else (mine or hits or [None])[0])

    def turn_id_for(self, meta, text, who=""):
        """[s3-link] The planned turn a spoken chunk belongs to, BY ITS WORDS.
        The ledger numbered rows by spoken order and looked the turn up by
        that number - so a round the air path spliced into (a passage dealt
        in front, a caller's hello) linked every row to the wrong turn, and
        the rows past the plan's length to none (measured 2026-09-27 on a
        call: three rows in front, every link three off). The words are the
        one thing the bind and the air share. "" when the chunk is not one of
        the round's planned turns."""
        try:
            s3 = (meta or {}).get("system3") or {}
            if not s3.get("conversation_id"):
                return ""
            _cid, i = self._turn_of(meta, text, who)
            if i is None:
                return ""
            return str((s3.get("turns") or {}).get(str(i)) or "")
        except Exception as exc:  # noqa: BLE001
            self.fail("turn link", exc)
            return ""

    def perf_state(self, entry, turns, text, who=""):
        """ES -> the voice: the turn's own emotional state for
        performance_vector(state=...), or None to keep the round's weather."""
        try:
            if ((entry or {}).get("system3") or {}).get("mode") != "active":
                return None
            _cid, i = self._turn_of(entry, text, who)
            if i is None:
                return None
            stamp = (((entry.get("turn_dice") or {}).get(str(i)) or {}).get("s3") or {})
            dims = (stamp.get("perf") or {}).get("dims")
            if not isinstance(dims, dict) or not dims:
                return None
            with self.lock:
                self.metrics["perf_applied"] += 1
            return {d: float(dims.get(d) or 0) for d in system3.EMOTION_DIMS}
        except Exception as exc:  # noqa: BLE001
            self.fail("performance", exc)
            return None

    def sfx_direction(self, meta, who, text):
        """What System 3 wants of the SFX Guy at this line: extra dues it
        planned (never fewer than the cadence) and intent words for the
        station's own matcher. Shadow rounds get an observer only."""
        try:
            s3 = (meta or {}).get("system3") or {}
            if not s3.get("conversation_id"):
                return None
            cid, i = self._turn_of(meta, text, who)
            if i is None:
                return {"conversation_id": cid, "turn": None, "extra": False, "query": "", "mode": s3.get("mode")}
            dice = meta.get("turn_dice") or {}
            here = ((dice.get(str(i)) or {}).get("s3") or {}).get("sfx") or {}
            nxt = ((dice.get(str(i + 1)) or {}).get("s3") or {}).get("sfx") or {}
            cued = meta.setdefault("_system3_sfx_cued", [])
            extra = False
            source = None
            if s3.get("mode") == "active" and i not in cued:
                if here.get("play") and here.get("placement") == "after":
                    extra, source = True, here
                elif nxt.get("play") and nxt.get("placement") == "before":
                    extra, source = True, nxt
                if extra:
                    cued.append(i)
            intent = list((source or here).get("intent") or [])
            with self.lock:
                self.metrics["sfx_directed"] += 1
                self.metrics["sfx_extra"] += 1 if extra else 0
            return {"conversation_id": cid, "turn": i, "extra": extra, "mode": s3.get("mode"),
                    "query": (" ".join(intent) if s3.get("mode") == "active" else ""),
                    "decided_by": (source or here).get("event_id"), "intent": intent}
        except Exception as exc:  # noqa: BLE001
            self.fail("sfx direction", exc)
            return None

    def sfxguy_direction(self, meta, who, text):
        """[s3-roads] The SFX Guy's node for this line: does he pipe up after
        it, and in what order of kinds. None when the round is not System
        3's (the dial's own random stands, as ever), when the line is not one
        of the round's turns, or when the round was planned before he had a
        node. One line per node: a second site asking about the same turn
        hears PASS with the reason."""
        try:
            s3 = (meta or {}).get("system3") or {}
            if not s3.get("conversation_id") or s3.get("mode") != "active":
                return None
            cid, i = self._turn_of(meta, text, who)
            if i is None:
                return None
            stamp = (((meta.get("turn_dice") or {}).get(str(i)) or {}).get("s3") or {})
            node = stamp.get("sfxguy")
            if not isinstance(node, dict) or not node.get("event_id"):
                return None
            spoken = meta.setdefault("_system3_sfxguy_spoken", [])
            with self.lock:
                self.metrics["sfxguy_directed"] += 1
            return {"conversation_id": cid, "turn": i, "turn_id": str(stamp.get("turn_id") or ""),
                    "seed": s3.get("seed"), "speak": bool(node.get("speak")) and i not in spoken,
                    "kind": node.get("kind"), "order": list(node.get("order") or []),
                    "decided_by": node.get("event_id"),
                    "why": "already spoke on this turn" if i in spoken else "", "_meta": meta}
        except Exception as exc:  # noqa: BLE001
            self.fail("sfx guy direction", exc)
            return None

    def sfxguy_chooser(self, direction):
        """[s3-roads] His numbers for the line itself, at air."""
        try:
            if not direction or not direction.get("conversation_id"):
                return None
            return SfxGuyChooser(self, direction)
        except Exception as exc:  # noqa: BLE001
            self.fail("sfx guy chooser", exc)
            return None

    def sfxguy_spoke(self, direction, line, kind, chooser=None, how=""):
        """[s3-roads] He spoke: the turn is his no more this round, and the
        observation records the line, the kind, what was on offer and every
        draw that chose it."""
        try:
            if not direction or not direction.get("conversation_id"):
                return
            meta = direction.get("_meta")
            if isinstance(meta, dict):
                meta.setdefault("_system3_sfxguy_spoken", []).append(direction.get("turn"))
            with self.lock:
                self.metrics["sfxguy_spoke"] += 1
            self.observe_later(direction["conversation_id"], "SFXGUY", {
                "stage": "line", "turn_index": direction.get("turn"), "decided_by": direction.get("decided_by"),
                "planned": direction.get("kind"), "order": list(direction.get("order") or []),
                "kind": str(kind or ""), "line": " ".join(str(line or "").split())[:300],
                "how": how or "System 3's own draw among the pool's candidates",
                "draws": list(getattr(chooser, "draws", None) or []),
                "fell_through": list(getattr(chooser, "unavailable", None) or [])},
                turn_id=str(direction.get("turn_id") or ""))
        except Exception as exc:  # noqa: BLE001
            self.fail("sfx guy line", exc)

    def sfx_observe(self, meta, direction, due_cadence, additions, match_last=None):
        try:
            if not direction or not direction.get("conversation_id"):
                return
            board = [a for a in additions or [] if a.get("who") == "board"]
            guy = [a for a in additions or [] if a.get("who") == "drop"]
            if not (board or guy or direction.get("extra")):
                return
            with self.lock:
                self.metrics["sfx_observed"] += 1
            stats = {}
            if isinstance(match_last, dict) and time.time() - float(match_last.get("at") or 0) < 20:
                stats = {k: match_last.get(k) for k in ("path", "why", "score", "cands", "tied", "eligible")}
            self.observe_later(direction["conversation_id"], "SFX", {
                "stage": "air", "turn_index": direction.get("turn"),
                "due": "cadence" if due_cadence and not direction.get("extra") else
                       "system3" if direction.get("extra") and not due_cadence else
                       "both" if due_cadence else "none",
                "decided_by": direction.get("decided_by"), "intent": direction.get("intent"),
                "played": [{"clip": Path(str(a.get("path") or "")).name,
                            "sample_id": a.get("sfx_sample_id") or a.get("sfx_video_id"),
                            "seconds": a.get("seconds"), "why": a.get("sfx_match_why") or ""} for a in board],
                "sfx_guy": [{"text": a.get("text"), "voice": a.get("voice")} for a in guy],
                "matcher": stats, "chosen_by": "the station's matcher, bans, weights and rotation"})
        except Exception as exc:  # noqa: BLE001
            self.fail("sfx observe", exc)

    def observe_ledger(self, block, sid, rows, round_kind=""):
        """A round was committed to the script ledger - the script is frozen
        and ordered. Record which ledger line each planned turn became."""
        try:
            links = {}
            for ord_, row in enumerate(rows or []):
                s3 = row.get("system3") if isinstance(row.get("system3"), dict) else {}
                if not s3.get("conversation_id"):
                    s3 = ((row.get("dice") or {}) if isinstance(row.get("dice"), dict) else {}).get("s3") or {}
                cid = s3.get("conversation_id")
                if not cid or not row.get("line_id"):
                    continue
                links.setdefault(cid, []).append({
                    "line_id": str(row["line_id"]), "conversation_id": cid, "turn_id": s3.get("turn_id") or None,
                    "block": int(block), "ord": ord_, "sid": str(sid or ""), "who": str(row.get("who") or ""),
                    "text": str(row.get("text") or ""), "at": time.time()})
            if not links:
                return
            for cid, lines in links.items():
                with self.lock:
                    self.metrics["lines_linked"] += len(lines)

                def job(lines=lines, cid=cid):
                    self.store.add_lines(lines)
                    self.store.add_observation(cid, "COMMIT", {
                        "stage": "script-ledger", "block": int(block), "sid": str(sid or ""),
                        "round": str(round_kind or ""), "lines": [x["line_id"] for x in lines],
                        "turns": [x["turn_id"] for x in lines]})
                _STORE_POOL.submit(job)
        except Exception as exc:  # noqa: BLE001
            self.fail("ledger link", exc)

    # --- the listener's feed ------------------------------------------------------
    PUBLIC_TTL = 20.0

    @staticmethod
    def _compact_roll(ev):
        """One recorded decision as a listener sees it: the family, the d100
        it rolled, the candidates it rolled through and where it landed."""
        sel = ev.get("selected") or {}
        stages = ev.get("stages") or []
        item = next((st for st in stages if st.get("stage") in ("item", "mode")), None)
        dice = next((st for st in stages if st.get("stage") == "dice"), None)
        draw = (item or {}).get("draw") or (dice or {}).get("draw") or ev.get("rng") or {}
        reel = [str(c.get("label") or c.get("id") or "") for c in (item or {}).get("candidates") or []][:10]
        if not reel and dice:
            reel = [str(dice.get("selected") or "")]
        return {"family": ev.get("family"), "dice": draw.get("dice"), "event_id": ev.get("event_id"),   # [s3-dice]
                "table": str(sel.get("table") or "")[:40],
                "label": str(sel.get("label") or sel.get("id") or "")[:80],
                "category": str(sel.get("category_label") or "")[:60],
                "index": (item or {}).get("selected_index"), "of": (item or {}).get("of"),
                "reel": reel, "intensity": sel.get("intensity"),
                "rule": str((dice or {}).get("rule") or "")[:120] or None}

    def _compact(self, conv):
        """A conversation as the listener feed needs it, and nothing about
        the station's configuration, seeds or settings."""
        events = {e.get("event_id"): e for e in conv.get("decision_events") or []}
        turns = {}
        for t in conv.get("turns") or []:
            ids = [d.get("event_id") for d in t.get("decisions") or []]
            ids += [sb.get("event_id") for sb in t.get("speakerbox") or []]
            ids.append((t.get("sfx") or {}).get("event_id"))
            ids.append((t.get("sfxguy") or {}).get("event_id"))       # [s3-roads]
            perf = t.get("performance") or {}
            turns[t["turn_id"]] = {
                "turn": t["index"] + 1, "of": len(conv["turns"]), "speaker": t.get("speaker"),
                "name": t.get("name"), "step": t.get("step_label"), "phase": t.get("phase"),
                "emotion": perf.get("emotion"), "intensity": perf.get("intensity"),
                "pace": perf.get("pace"), "pause_style": perf.get("pause_style"),
                "rolls": [self._compact_roll(events[i]) for i in ids if i in events],
                "speakerbox": [{"mode": sb.get("mode"), "file": (sb.get("material") or {}).get("file", "")}
                               for sb in t.get("speakerbox") or [] if sb.get("mode") not in (None, "NONE")],
                "sfx": {k: (t.get("sfx") or {}).get(k) for k in ("play", "placement", "intent")}}
        return {"conversation_id": conv["identity"]["conversation_id"], "mode": conv.get("mode"),
                "road": conv["identity"].get("road_kind"), "topic": str(conv["subject"].get("topic") or "")[:160],
                "turns": turns}

    def public_lines(self, ids):
        """[{line_id, system3, ...}] for the tune page's feed. Runs on the
        reader thread only; the cache is that thread's alone."""
        cache = self.__dict__.setdefault("_public_cache", collections.OrderedDict())
        out = []
        for lid in ids:
            got = self.store.line(lid)
            if not got:
                out.append({"line_id": lid, "system3": False})
                continue
            cid = got["conversation_id"]
            hit = cache.get(cid)
            if not hit or time.time() - hit[0] > self.PUBLIC_TTL:
                conv = self.store.conversation(cid)
                hit = (time.time(), self._compact(conv) if conv else None)
                cache[cid] = hit
                cache.move_to_end(cid)
                while len(cache) > 40:
                    cache.popitem(last=False)
            comp = hit[1]
            if not comp:
                out.append({"line_id": lid, "system3": False})
                continue
            out.append({"line_id": lid, "system3": True, "conversation_id": cid, "mode": comp["mode"],
                        "road": comp["road"], "topic": comp["topic"],
                        "turn": comp["turns"].get(str(got.get("turn_id") or ""))})
        return out

    def _compact_cached(self, cid):
        """The compact conversation, from the reader thread's cache (20 s)."""
        cache = self.__dict__.setdefault("_public_cache", collections.OrderedDict())
        hit = cache.get(cid)
        if not hit or len(hit) < 3 or time.time() - hit[0] > self.PUBLIC_TTL:
            conv = self.store.conversation(cid)
            hit = (time.time(), self._compact(conv) if conv else None, conv)
            cache[cid] = hit
            cache.move_to_end(cid)
            while len(cache) > 40:
                cache.popitem(last=False)
        return hit[1], (hit[2] if len(hit) > 2 else None)

    def feed_lines(self, ids, hints=None):
        """[s3-dice] "for these entries that are created via the roulette
        system, I want to have a series of dice icons rolling and landing on
        their final numbers as the entries appear on screen." For each line
        id: the turn it came from and that turn's recorded rolls, compact.
        The link is the ledger's (store.line), else the station's line-hook
        stamp (_S3_LINE_BY_ID), else the hint the feed row itself carried
        ("lid:cid:tid:who"). The SFX Guy's row adds the draw that chose his
        line at air. Reader thread only. `system3` is False for a line no
        node made - the feed then shows no dice, and asks again later for a
        young row the ledger has not linked yet."""
        hints = hints or {}
        held = getattr(self.host, "_S3_LINE_BY_ID", None)
        out = {}
        for lid in ids:
            lid = str(lid or "")
            if not lid:
                continue
            got = None
            try:
                got = self.store.line(lid)
            except Exception:  # noqa: BLE001
                got = None
            who, text = str((got or {}).get("who") or ""), str((got or {}).get("text") or "")
            cid, tid = str((got or {}).get("conversation_id") or ""), str((got or {}).get("turn_id") or "")
            if not cid:
                stamp = held.get(lid) if isinstance(held, dict) else None
                if isinstance(stamp, dict) and stamp.get("conversation_id"):
                    cid, tid = str(stamp.get("conversation_id") or ""), str(stamp.get("turn_id") or "")
            if not cid and hints.get(lid):
                h = hints[lid]
                cid, tid, who = str(h.get("cid") or ""), str(h.get("tid") or ""), who or str(h.get("who") or "")
            if not cid:
                out[lid] = {"system3": False}
                continue
            try:
                comp, conv = self._compact_cached(cid)
            except Exception:  # noqa: BLE001
                comp, conv = None, None
            if not comp:
                out[lid] = {"system3": False, "why": "its round is past retention"}
                continue
            turn = comp["turns"].get(tid) if tid else None
            air = []
            if who == "drop" and conv is not None:
                words = " ".join(text.lower().split())[:400]
                for o in conv.get("observations_air") or []:
                    if o.get("family") != "SFXGUY":
                        continue
                    if words and " ".join(str(o.get("line") or "").lower().split())[:400] != words:
                        continue
                    for d in o.get("draws") or []:
                        air.append({"family": "LINE", "dice": d.get("dice"), "index": d.get("index"), "of": d.get("of"),
                                    "label": str(o.get("kind") or "") + " pool: " + str(d.get("pool") or ""),
                                    "reel": [str(c) for c in (d.get("candidates") or [])][:10]})
                    if turn is None and o.get("turn_index") is not None and conv.get("turns"):
                        host_turn = next((t for t in conv["turns"] if t.get("script_index") == o.get("turn_index")), None)
                        if host_turn:
                            turn = comp["turns"].get(host_turn["turn_id"])
                            tid = host_turn["turn_id"]
                    break
            if turn is None and not tid and conv and len(conv.get("turns") or []) == 1:
                tid = conv["turns"][0]["turn_id"]
                turn = comp["turns"].get(tid)
            out[lid] = {"system3": True, "conversation_id": cid, "turn_id": tid, "who": who,
                        "road": comp["road"], "mode": comp["mode"], "topic": comp["topic"],
                        "turn": turn, "air": air}
        return out

    # --- the line on air, for the glass and Glyphy ---------------------------------
    async def now(self):
        """[s3-glass] "I want the popup orchestrator windows showing RNG and
        rolodex information and I want glyphy reactive to the dice / roulette
        results ... rolling dice in the popup for the currently spoken segment
        showing numbers for the values being obtained for the actively spoken
        line." The station's own record of the line going out right now
        (_SPEAKING_NOW), resolved to its System 3 turn: the road, the turn's
        place in the round, its recorded rolls (each with the d100 and the
        candidates it rolled through), the SFX Guy's node, the round's
        budget and its length roll. `system3` is False for a line no node
        made - which the glass says in words, never hides."""
        speaking = getattr(self.host, "_SPEAKING_NOW", None)
        sp = dict(speaking) if isinstance(speaking, dict) else {}
        lid = str(sp.get("id") or "")
        roads = self.roads()
        out = {"at": time.time(),
               "line": ({k: sp.get(k) for k in ("id", "who", "name", "kind", "text", "at")} if lid else None),
               "system3": None,
               "register": {"roads": len(roads), "directed": sum(1 for r in roads if r.get("mode") == "active"),
                            "mode": self.settings.get("mode")}}
        if not lid:
            return out
        try:
            link = await self.read(self.store.line, lid)
        except Exception:  # noqa: BLE001
            link = None
        cid = str((link or {}).get("conversation_id") or "")
        tid = str((link or {}).get("turn_id") or "")
        if not cid:
            held = getattr(self.host, "_S3_LINE_BY_ID", None)
            stamp = held.get(lid) if isinstance(held, dict) else None
            if isinstance(stamp, dict):
                cid, tid = str(stamp.get("conversation_id") or ""), str(stamp.get("turn_id") or "")
        if not cid:
            out["system3"] = False
            return out
        conv = self.recent.get(cid)
        if not conv:
            try:
                conv = await self.read(self.store.conversation, cid)
            except Exception:  # noqa: BLE001
                conv = None
        if not conv:
            out["system3"] = False
            return out
        comp = self._compact(conv)
        turn = comp["turns"].get(tid) if tid else None
        if turn is None and not tid and conv.get("turns") and len(conv["turns"]) == 1:
            turn = comp["turns"].get(conv["turns"][0]["turn_id"])
        events = {e.get("event_id"): e for e in conv.get("decision_events") or []}
        length = conv.get("length_roll") or {}
        lev = events.get(length.get("event_id")) if length else None
        timing = conv.get("timing") or {}
        out["system3"] = {
            "conversation_id": cid, "turn_id": tid, "road": comp["road"], "mode": comp["mode"],
            "topic": comp["topic"], "turns": len(conv.get("turns") or []), "turn": turn,
            "structure": (conv.get("road_structure") or conv.get("call_structure") or {}).get("id") or "banter_cycle",
            "budget": {"turn_budget": timing.get("turn_budget"), "target_seconds": timing.get("target_duration"),
                       "estimated_seconds": timing.get("elapsed_estimated"), "turn_seconds": timing.get("turn_seconds"),
                       "length_roll": ({"rolled": length.get("rolled"), "turns": length.get("turns"),
                                        "lo": length.get("lo"), "hi": length.get("hi"),
                                        "dice": ((lev or {}).get("rng") or {}).get("dice")} if length else None)},
            "verdict": (conv.get("validation") or {}).get("verdict"),
            "line_choice": conv.get("line_choice"),
        }
        return out

    # --- operator surface ---------------------------------------------------------
    def status(self):
        with self.lock:
            m = copy.deepcopy(self.metrics)
        m["pending_writes"] = self.pending
        return {"ready": self.ready, "engine": system3.ENGINE_VERSION, "schema": system3.EVENT_SCHEMA,
                "settings": self.settings, "config_hash": system3.config_hash(self.config),
                "road_modes": {r: system3.road_mode(self.settings, r) for r in system3.ROADS},
                "roads": self.roads(),                                           # [s3-roads]
                "metrics": m,
                "capabilities": {
                    "performance": "ES maps to the station's six emotion dimensions; performance_vector "
                                   "and perf_apply (tempo, pitch drift, energy, pause length) apply them to "
                                   "every engine's take as DSP. No adapter is known to take a native emotion "
                                   "field, so none is sent.",
                    "sfx": "System 3 adds planned clips and intent words; the station's matcher, bans, "
                           "weights, rotation and hourly recency choose every real file.",
                    "speakerbox": "passages are drawn by the station's speakbox_quote (locks, themes, "
                                  "cooldowns, rotation); System 3 rolls the doors and marks."}}

    def config_view(self):
        """[s3-roads] The config as the desk sees it: every road's structure
        present (the saved one, else the default), his section defaulted.
        Nothing here is written back until the desk saves it."""
        view = copy.deepcopy(self.config)
        structures = dict(system3_tables.default_structures())
        structures.update({k: v for k, v in (view.get("structures") or {}).items() if isinstance(v, dict)})
        view["structures"] = structures
        view.setdefault("sfxguy", copy.deepcopy(system3.DEFAULT_SFXGUY))
        return view

    def roads(self):
        """[s3-roads] The register, with what System 3 is for each road right
        now. Every road that puts words on air is here; a road standing aside
        (mode off) is labelled "not directed by System 3"."""
        out = []
        for r in system3_tables.road_register():
            row = dict(r)
            mode = system3.road_mode(self.settings, r["id"] if r["id"] in system3.ROADS else "banter")
            row["mode"] = mode
            row["label_air"] = "" if mode == "active" else "not directed by System 3"
            row["structure"] = ("structure" if r.get("shape") == "cycle"
                                else "" if r.get("shape") == "node" else "structures/%s" % r["id"])
            out.append(row)
        return out

    def apply_settings(self, raw):
        merged = dict(self.settings)
        if isinstance(raw, dict):
            for k, v in raw.items():
                if k == "controls" and isinstance(v, dict):
                    merged["controls"] = dict(merged.get("controls") or {}, **v)
                elif k in system3.DEFAULT_SETTINGS:
                    merged[k] = v
        mode = str(merged.get("mode") or "").lower()
        if mode not in system3.MODES:
            raise ValueError("mode must be one of " + ", ".join(system3.MODES))
        return system3.normalise_settings(merged)


class _Host:
    def __init__(self, namespace):
        object.__setattr__(self, "namespace", namespace)

    def __getattr__(self, name):
        try:
            return self.namespace[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def install(app, namespace):
    from fastapi import Header, HTTPException, Request
    from fastapi.responses import FileResponse, HTMLResponse, Response

    globals()["Request"] = Request
    host = _Host(namespace)
    rt = System3Runtime(host)
    holder = {"runtime": rt}

    # The hooks the station calls. Each is a no-op returning None until the
    # ledger has loaded, and whenever System 3 is off.
    async def system3_direct_banter(**ctx):
        return await rt.direct(ctx)

    namespace["system3_direct_banter"] = system3_direct_banter
    namespace["system3_door_roll"] = rt.door_roll
    namespace["system3_repair_wanted"] = rt.repair_wanted
    namespace["system3_repair_clause"] = rt.repair_clause
    namespace["system3_director"] = rt.director
    namespace["system3_bind_entry"] = rt.bind_entry
    namespace["system3_perf_state"] = rt.perf_state
    namespace["system3_sfx_direction"] = rt.sfx_direction
    namespace["system3_sfx_observe"] = rt.sfx_observe
    # [s3-roads] the SFX Guy's node at air, and the single-voice roads

    async def system3_direct_line(**ctx):
        return await rt.direct_line(ctx)

    namespace["system3_turn_id_for"] = rt.turn_id_for               # [s3-link]
    namespace["system3_sfxguy_direction"] = rt.sfxguy_direction
    namespace["system3_sfxguy_chooser"] = rt.sfxguy_chooser
    namespace["system3_sfxguy_spoke"] = rt.sfxguy_spoke
    namespace["system3_direct_line"] = system3_direct_line
    namespace["system3_bind_line"] = rt.bind_line
    namespace["system3_observe_ledger"] = rt.observe_ledger
    namespace["_system3"] = lambda: rt

    @app.on_event("startup")
    async def start_system3():
        try:
            await asyncio.get_running_loop().run_in_executor(_STORE_POOL, rt.load)
            rt.log("System 3 loaded: mode %s, roads %s, config %s"
                   % (rt.settings["mode"], ",".join(rt.settings["roads"]) or "none",
                      system3.config_hash(rt.config)))
        except Exception as exc:  # noqa: BLE001
            rt.fail("startup", exc)

        async def retention():
            await asyncio.sleep(300)
            while True:
                try:
                    gone = await asyncio.get_running_loop().run_in_executor(_STORE_POOL, rt.store.retention)
                    if gone:
                        rt.log("System 3 retention removed %d old conversation(s)" % gone)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    rt.fail("retention", exc)
                await asyncio.sleep(3600)
        holder["task"] = asyncio.create_task(retention(), name="system3:retention")

    @app.on_event("shutdown")
    async def stop_system3():
        task = holder.get("task")
        if task:
            task.cancel()

    def body_json(raw):
        try:
            return json.loads(raw or b"{}")
        except ValueError as exc:
            raise HTTPException(400, "not JSON: %s" % exc) from exc

    @app.get("/api/system3/status")
    async def status(authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        out = rt.status()
        out["store"] = await rt.read(rt.store.counts)
        return out

    @app.get("/api/system3/now")
    async def now(authorization: str | None = Header(default=None)):
        """[s3-glass] the line on air and the dice behind it (the glass polls this)."""
        host.require_read_auth(authorization)
        return await rt.now()

    @app.get("/api/system3/settings")
    async def get_settings(authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        return {"settings": rt.settings, "defaults": system3.DEFAULT_SETTINGS, "modes": system3.MODES,
                "roads": system3.ROADS, "generation_modes": system3.GENERATION_MODES,
                "register": rt.roads()}                                          # [s3-roads]

    @app.post("/api/system3/settings")
    async def set_settings(request: Request, authorization: str | None = Header(default=None)):
        host.require_auth(authorization)
        raw = body_json(await request.body())
        try:
            new = rt.apply_settings({} if raw.get("reset") else raw)
            if raw.get("reset"):
                new = system3.normalise_settings({"mode": rt.settings["mode"], "roads": rt.settings["roads"]})
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        saved = await asyncio.get_running_loop().run_in_executor(_STORE_POOL, rt.store.save_settings, new)
        before = rt.settings
        rt.settings = saved
        if before.get("mode") != saved.get("mode") or before.get("roads") != saved.get("roads"):
            rt.log("System 3 mode %s -> %s (roads %s)" % (before.get("mode"), saved["mode"],
                                                           ",".join(saved["roads"]) or "none"))
        return {"settings": saved}

    @app.get("/api/system3/config")
    async def get_config(hash: str = "", authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        if hash:
            got = await rt.read(rt.store.config_by_hash, hash)
            if not got:
                raise HTTPException(404, "no config %s" % hash)
            return {"hash": hash, "config": got}
        return {"hash": system3.config_hash(rt.config), "config": rt.config_view(),   # [s3-roads]
                "versions": await rt.read(rt.store.config_versions)}

    async def save_config(config, note):
        system3.config_hash(config)
        h = await asyncio.get_running_loop().run_in_executor(_STORE_POOL, rt.store.save_config, config, note)
        rt.config = config
        rt.log("System 3 config is now %s (%s)" % (h, note))
        return h

    @app.put("/api/system3/tables/{table_id}")
    async def put_table(table_id: str, request: Request, authorization: str | None = Header(default=None)):
        """Create or edit one table - "make an ES2 based on ES1"."""
        host.require_auth(authorization)
        raw = body_json(await request.body())
        raw["id"] = table_id
        try:
            table = system3.validate_table(raw)
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        config = copy.deepcopy(rt.config)
        tables = [t for t in config["tables"] if t["id"] != table_id]
        old = next((t for t in config["tables"] if t["id"] == table_id), None)
        if old:
            table["version"] = int(old.get("version") or 1) + 1
            tables.insert(config["tables"].index(old), table)
        else:
            tables.append(table)
        config["tables"] = tables
        h = await save_config(config, "table %s %s" % (table_id, "v%d" % table["version"]))
        return {"hash": h, "table": table}

    @app.delete("/api/system3/tables/{table_id}")
    async def delete_table(table_id: str, authorization: str | None = Header(default=None)):
        host.require_auth(authorization)
        config = copy.deepcopy(rt.config)
        if not any(t["id"] == table_id for t in config["tables"]):
            raise HTTPException(404, "no table %s" % table_id)
        config["tables"] = [t for t in config["tables"] if t["id"] != table_id]
        fams = {t["family"] for t in config["tables"] if t.get("enabled", True)}
        missing = [f for f in ("ES", "RS", "IRS", "FL", "CTS") if f not in fams]
        if missing:
            raise HTTPException(400, "that would leave no enabled table for " + ", ".join(missing))
        return {"hash": await save_config(config, "removed table %s" % table_id)}

    @app.put("/api/system3/structure")
    async def put_structure(request: Request, authorization: str | None = Header(default=None)):
        """The banter cycle and its prepend/append marks (the node view)."""
        host.require_auth(authorization)
        raw = body_json(await request.body())
        steps = raw.get("steps")
        if not isinstance(steps, list) or not steps:
            raise HTTPException(400, "the structure needs steps")
        for st in steps:
            if not isinstance(st, dict) or not st.get("id") or not isinstance(st.get("draws"), list):
                raise HTTPException(400, "every step needs an id and a list of draws")
            st["speakerbox"] = [m for m in (st.get("speakerbox") or []) if m in ("prepend", "append")]
            for d in st["draws"]:
                if d.get("family") not in ("CTS", "ES", "RS", "IRS", "FL"):
                    raise HTTPException(400, "unknown family %r" % d.get("family"))
        config = copy.deepcopy(rt.config)
        structure = dict(config["structure"])
        structure.update({k: raw[k] for k in ("steps", "closing", "handoff", "label") if k in raw})
        structure["version"] = int(structure.get("version") or 1) + 1
        config["structure"] = structure
        return {"hash": await save_config(config, "structure v%d" % structure["version"]),
                "structure": structure}

    @app.put("/api/system3/structures/{road}")
    async def put_road_structure(road: str, request: Request, authorization: str | None = Header(default=None)):
        """[s3-calls] A road's structure - its legs, their acts, places, seats and
        draws - customised, expanded or altered from the desk."""
        host.require_auth(authorization)
        raw = body_json(await request.body())
        problems = system3_tables.validate_structure(road, raw)
        if problems:
            raise HTTPException(400, "; ".join(problems[:6]))
        config = copy.deepcopy(rt.config)
        mine = dict(system3.road_structure(config, road) or {})
        mine.update({k: raw[k] for k in ("legs", "label", "head", "tail", "material",
                                         "min_turns", "max_turns", "caller_share") if k in raw})
        mine["version"] = int(mine.get("version") or 1) + 1
        config.setdefault("structures", system3_tables.default_structures())[road] = mine
        return {"hash": await save_config(config, "%s structure v%d" % (road, mine["version"])),
                "structure": mine}

    @app.put("/api/system3/config/section/{name}")
    async def put_section(name: str, request: Request, authorization: str | None = Header(default=None)):
        host.require_auth(authorization)
        if name not in ("speakerbox", "sfx", "personalities"):
            raise HTTPException(404, "no section %s" % name)
        raw = body_json(await request.body())
        if not isinstance(raw, dict):
            raise HTTPException(400, "a section is an object")
        config = copy.deepcopy(rt.config)
        config[name] = raw
        return {"hash": await save_config(config, "%s section" % name)}

    @app.post("/api/system3/config/reset")
    async def reset_config(authorization: str | None = Header(default=None)):
        host.require_auth(authorization)
        return {"hash": await save_config(system3.default_config(), "reset to defaults")}

    @app.get("/api/system3/conversations")
    async def conversations(limit: int = 40, road: str = "", before: float = 0.0, mode: str = "",
                            authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        return {"conversations": await rt.read(rt.store.conversations, limit, road, before, mode)}

    @app.get("/api/system3/conversation/{cid}")
    async def conversation(cid: str, authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        got = await rt.read(rt.store.conversation, cid)
        if not got:
            live = rt.recent.get(cid)
            if not live:
                raise HTTPException(404, "no conversation %s (retention keeps seven days)" % cid)
            got = json.loads(json.dumps(live, default=str))
            got["observations_air"], got["lines"] = [], []
        body = await asyncio.get_running_loop().run_in_executor(
            _READ_POOL, lambda: json.dumps(got, default=str))
        return Response(content=body, media_type="application/json")

    @app.get("/api/system3/events")
    async def events(after: int = 0, limit: int = 200, conversation: str = "",
                     authorization: str | None = Header(default=None)):
        """The live Rolodex feed: every recorded decision and observation
        after a cursor. Poll with the returned cursor."""
        host.require_read_auth(authorization)
        return await rt.read(rt.store.events_after, after, limit, conversation)

    @app.get("/api/system3/dice")
    async def dice(ids: str = "", hints: str = "", authorization: str | None = Header(default=None)):
        """[s3-dice] The feed's dice: for up to 80 line ids, each line's turn
        and its recorded rolls. `hints` is "lid:cid:tid:who,..." from rows
        that carry their own stamp."""
        host.require_read_auth(authorization)
        wanted = [x.strip() for x in str(ids or "").split(",") if x.strip()][:80]
        hint_of = {}
        for part in str(hints or "").split(","):
            bits = part.strip().split(":")
            if len(bits) >= 3 and bits[0] and bits[1]:
                hint_of[bits[0]] = {"cid": bits[1], "tid": (bits[1] + ":" + bits[2]) if bits[2] else "",
                                    "who": bits[3] if len(bits) > 3 else ""}
        if not wanted:
            return {"lines": {}}
        return {"lines": await rt.read(rt.feed_lines, wanted, hint_of)}

    @app.get("/api/system3/line")
    async def line(line_id: str, authorization: str | None = Header(default=None)):
        """A spoken line -> the turn and the decision chain that made it."""
        host.require_read_auth(authorization)
        got = await rt.read(rt.store.line, line_id)
        if not got:
            raise HTTPException(404, "line %s was not directed by System 3" % line_id)
        conv = await rt.read(rt.store.conversation, got["conversation_id"])
        if not conv:
            raise HTTPException(404, "its conversation is past retention")
        turn = (next((t for t in conv["turns"] if t["turn_id"] == got["turn_id"]), None)
                if got.get("turn_id") else None)
        healed = ""
        words = " ".join(str(got.get("text") or "").lower().split())[:400]
        if turn is None and str(got.get("who") or "") != "drop" and len(words) >= 8:
            # [s3-link] a row linked before rows were matched by their words:
            # the turn whose bound words hold this line, if one does
            for t in conv["turns"]:
                said = " ".join(str(t.get("text") or "").lower().split())
                if said and (words in said or said in words):
                    turn, healed = t, "matched by its words; the row's own link was made by spoken-row order"
                    break
        sfxguy = None
        if str(got.get("who") or "") == "drop":
            # [s3-link] the SFX Guy's row: the node it followed and the draw
            for o in conv.get("observations_air") or []:
                if o.get("family") == "SFXGUY" and " ".join(str(o.get("line") or "").lower().split())[:400] == words:
                    at = o.get("turn_index")
                    host_turn = next((t for t in conv["turns"] if t.get("script_index") == at), None)
                    node = (host_turn or {}).get("sfxguy") or {}
                    sfxguy = {"line": o, "turn": host_turn,
                              "node": next((e for e in conv["decision_events"] if e["event_id"] == node.get("event_id")), None)}
                    if host_turn and turn is None:
                        turn = host_turn
                    break
            if sfxguy is None and turn is None and got.get("turn_id"):
                turn = next((t for t in conv["turns"] if t["turn_id"] == got["turn_id"]), None)
        ids = set()
        if turn:
            ids = {d.get("event_id") for d in turn["decisions"]}
            ids |= {sb.get("event_id") for sb in turn.get("speakerbox") or []}
            ids.add((turn.get("sfx") or {}).get("event_id"))
            ids.add(((turn.get("sfxguy") or {}).get("event_id")))
        return {"line": got, "turn": turn, "healed": healed, "sfxguy": sfxguy,
                "engine": conv.get("engine"), "planned_at": conv.get("created"),
                "decisions": [e for e in conv["decision_events"] if e["event_id"] in ids],
                "observations": [o for o in conv.get("observations_air") or []
                                 if (turn and o.get("turn_id") == turn.get("turn_id"))
                                 or (got.get("turn_id") and o.get("turn_id") == got["turn_id"])
                                 or got["line_id"] in (o.get("lines") or [])],
                "conversation": system3.summary(conv)}

    @app.get("/api/system3/public/lines")
    async def public_lines(ids: str = "", t: str = "", authorization: str | None = Header(default=None)):
        """The tune page's feed: how each line a listener heard was composed.
        Listener-authenticated (the tune-in token), a compact projection,
        and on the public door's allowlist by exact path."""
        host.require_listen_auth(t, authorization)
        wanted = [x for x in str(ids or "").split(",") if re.fullmatch(r"[0-9A-Za-z_-]{6,64}", x)][:24]
        if not wanted:
            return {"lines": []}
        return {"lines": await rt.read(rt.public_lines, wanted)}

    @app.post("/api/system3/simulate")
    async def simulate(request: Request, authorization: str | None = Header(default=None)):
        """Plan a conversation that can never reach air - for the tables
        editor, the golden seeds and the operator's own curiosity."""
        host.require_read_auth(authorization)
        raw = body_json(await request.body())
        if raw.get("keep"):
            host.require_auth(authorization)
        settings = system3.normalise_settings(dict(rt.settings, **{k: v for k, v in raw.items()
                                                                  if k in ("controls", "test_seed", "generation_mode")},
                                                   mode="active"))
        inputs = {"road": "banter", "seats": raw.get("seats") or ["A", "B"],
                  "names": raw.get("names") or {"A": "Host", "B": "Co-host", "D": "Third"},
                  "turns": max(2, min(40, int(raw.get("turns") or 10))),
                  "subject": {"topic": str(raw.get("topic") or "a simulated subject")[:300],
                              "seeded": bool(raw.get("seeded")), "category": "simulated",
                              "keywords": re.findall(r"[a-z]{5,}", str(raw.get("topic") or "").lower())[:6]},
                  "availability": dict({"speakbox": True}, **(raw.get("availability") or {})),
                  "speakerbox_rates": raw.get("speakerbox_rates") or {"prepend": 0.49, "append": 0.68},
                  "target_seconds": float(raw.get("target_seconds") or 0)}
        conv = await asyncio.get_running_loop().run_in_executor(
            _READ_POOL, lambda: system3.plan_scene(inputs, rt.config, settings, seed=raw.get("seed") or None))
        conv["mode"] = "simulation"
        conv["status"] = "simulated"
        conv["plan"] = {"sheet": system3.render_sheet(conv)}
        if raw.get("keep"):
            rt.persist(conv)
        return conv

    @app.post("/api/system3/replay/{cid}")
    async def replay(cid: str, authorization: str | None = Header(default=None)):
        """Decision replay at the declared scope (blueprint section 16)."""
        host.require_read_auth(authorization)
        conv = await rt.read(rt.store.conversation, cid)
        if not conv:
            raise HTTPException(404, "no conversation %s" % cid)
        config = await rt.read(rt.store.config_by_hash, conv["config_hash"])
        if not config:
            raise HTTPException(409, "config %s is no longer held" % conv["config_hash"])
        result = await asyncio.get_running_loop().run_in_executor(_READ_POOL, system3.replay, conv, config)
        result.pop("conversation", None)
        result["scopes"] = {
            "decision": "reproduced from inputs, seed and config %s" % conv["config_hash"],
            "script": "the frozen script is the one captured in the script ledger (see lines)",
            "audio": "render and media identities are the ones captured by the pantry and playout",
            "playout": "occurrence and delivery semantics are the sequencer's and are not re-run"}
        return result

    @app.post("/api/system3/turn/{cid}")
    async def turn_step(cid: str, request: Request, authorization: str | None = Header(default=None)):
        """Mode B by hand: report what a turn actually said and get the rest
        of the plan decided again from there. Only on a simulation or a
        conversation that is still in memory - never on the air path."""
        host.require_auth(authorization)
        raw = body_json(await request.body())
        conv = rt.recent.get(cid)
        if not conv:
            raise HTTPException(404, "only a recent conversation can be stepped")
        try:
            idx = int(raw.get("turn_index"))
            obs = system3.observe(conv, idx, str(raw.get("text") or ""), raw.get("seconds"))
            system3.replan(conv, rt.config, idx + 1, until=len(conv["turns"]) or None)
        except (ValueError, IndexError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        rt.persist(conv)
        return {"observation": obs, "conversation": conv}

    @app.get("/system3/{name}")
    async def asset(name: str):
        if name not in ("system3.js", "system3.css"):
            raise HTTPException(404, "Unknown asset")
        # Revalidated on every load (the ETag makes that a 304): the Script
        # tab imports these under a fixed ?v= that lives in the APK, so a
        # heuristically cached copy would outlive a station-side change.
        return FileResponse(Path(__file__).parent / "frontend" / name, headers={"Cache-Control": "no-cache"})

    @app.get("/system3")
    async def page():
        return HTMLResponse('''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Pine Box System 3</title>
<link rel="stylesheet" href="/system3/system3.css"><body class="s3-page"><main id="system3"></main>
<script type="module">import {mount} from '/system3/system3.js'; mount(document.querySelector('#system3'));</script></body></html>''')

    return lambda: rt

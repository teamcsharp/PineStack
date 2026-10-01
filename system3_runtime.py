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
import contextvars
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
try:                                      # [s3-mgrtopics] the manager's topic roulette
    import system3_mgrtopics
except ImportError:  # pragma: no cover - a host without the module runs as before
    system3_mgrtopics = None
try:                                      # [s3-gold] gold lines as a rolled reply
    import system3_gold
except ImportError:  # pragma: no cover - a host without the module rolls no gold
    system3_gold = None

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
# [s3-carry] a round's ending carries into the next for this long (linear decay)
CARRY_WINDOW = float(system3.CARRY_WINDOW)
# [s3-withhold] a planned round nobody bound within this long is recorded as abandoned
ABANDON_AFTER = 1800.0
ABANDON_SWEEP = 300.0
# [s3-dice-door] the station's rolls made on this task since its last planned
# round: {"seed", "stream", "rolls": [...]}. A road rolls its dice (a caller's
# prize, their state) and then asks System 3 to plan the round; the plan takes
# these in as STATION events, so the round shows every roll that shaped it.
_S3_ROLLS = contextvars.ContextVar("system3_station_rolls", default=None)
# [s3-sfx-roll] the last roll recorded on this thread, by key: a road reads
# back the dice it has just rolled (the board's clip carries its d100 to the
# line it makes). Per thread and not on the roll buffer: the pick and the
# read are one call apart on the same thread, while the buffer is the task's
# and a plan on it absorbs (and empties) it.
_S3_LAST = threading.local()
# [s3-blocks] the System 3 handle of the round (or line) whose words are being
# written on this task right now - the station sets it around its writer call,
# so the prompt's block decisions are recorded on that conversation
_S3_WRITE = contextvars.ContextVar("system3_writing_for", default=None)
ROLLS_KEPT = 60              # a road that rolls and never plans keeps only the last ones
ROLLS_FRESH = 600.0          # ...and only the last ten minutes' of them reach a plan
DICE_FLUSH_AFTER = 12.0      # rows first seen are written as one config version
# [s3-sfx-roll] [s3-banks-roll] what a line's stamp carries past the lines table,
# on the COMMIT and back onto the conversation's lines: a board line's rolls and
# poster, a banked line's replay, a gold bar's source and a listening response
_LINE_KEEPS = ("sfx_roll", "poster", "replay", "gold", "listening")

# The station's seat names -> the script markers banter_turns returns.
_SEAT_OF = {"dj": "A", "host": "A", "cohost": "B", "third": "D", "caller": "C",
            "caller2": "E"}



def _s3_lines(o):
    """[s3-lines] the line ids an observation covers. `lines` is a list of ids;
    a writer that put a count there (the dead-air rescue's INJECT card did) must
    not turn one card into a 500 for every line of its conversation."""
    got = o.get("lines") if isinstance(o, dict) else None
    return got if isinstance(got, (list, tuple, set)) else ()

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
        self.gate = None          # [s3-turnchain] the copy gate's walk over the written round, while it runs

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
        self.voice = None               # [s3-es-voice] the ES pick's voice block, for performance_vector(es=)
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
    opener = system3.sentence_cut(ex.get("opener"), 400)
    reply = system3.sentence_cut(ex.get("reply"), 400)
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
            # [s3-carry] rounds that handed their ending on / started from one / carried it in the voice only
            "carried": 0, "carry_in": 0, "carry_delivery": 0,
            # [s3-withhold] planned rounds that said why they never reached the air
            "withheld": 0, "abandoned": 0,
            # [s3-turnchain] the copy gate: rounds walked, turns caught / re-written / dropped /
            # written past the end, rounds held, re-write visits, Mode B catches, lines refused at air
            "gate_rounds": 0, "gate_caught": 0, "gate_rewritten": 0, "gate_dropped": 0, "gate_trimmed": 0,
            "gate_held": 0, "gate_visits": 0, "gate_in_chain": 0, "gate_air_dropped": 0,
        }
        # [s3-carry] what the last round left on the air: {at, from, road, seats, dynamics,
        # unresolved, landing, tempers}. Read under self.lock; written at the ledger commit.
        self.carry = {}
        self._carry_noted = set()
        # [s3-withhold] active rounds planned and not yet bound: cid -> {at, road, bank}
        self.open = {}
        # [s3-dice-door] rows the station rolled before the desk had them, and the ring
        self.dice_pending = {"chance": {}, "pool": {}}
        self._dice_timer = None
        self.station_rolls = collections.deque(maxlen=400)
        # [s3-blocks] each prompt's block decisions, by the digest of the words sent
        self.prompt_blocks = collections.OrderedDict()
        # [s3-flow] the items recent rounds used (FAMILY:item), and what went to air lately
        self.recent_items = collections.deque(maxlen=80)
        self.recent_air = collections.deque(maxlen=300)
        # [link-now] a committed round's line links, known the moment it commits;
        # the store's single writer can be a minute behind the roll events
        self.pending_links = collections.OrderedDict()
        # [s3-cast] the favourites that came up lately (they weigh a quarter at the
        # next draw) and each directive's airings; kept in data/system3_cast.json
        self.cast = {"fav_recent": [], "directive_spent": {}, "counted": []}

    # --- lifecycle ---------------------------------------------------------
    def load(self):
        self.settings = self.store.settings()
        self.config = self.store.config()
        self.add_missing_conversation_graphs()
        added = self.add_missing_default_tables()
        if added:
            self.log("System 3 config gained the default tables it predates: " + ", ".join(added))
        gained = self.add_missing_station_events()                       # [s3-live-event]
        if gained:
            self.log("System 3 config gained the station-events register: " + ", ".join(gained))
        split_on = self.add_split_defaults()                                   # [s3-split]
        if split_on:
            self.log("System 3's SPLIT node is switched on by default on: " + ", ".join(split_on))
        badges = self.add_missing_es_emoji()                                 # [s3-es-emoji]
        if badges:
            self.log("System 3's ES tables gained their emoji badges (once): %d on %s"
                     % (len(badges), ", ".join(sorted({b.split(":", 1)[0] for b in badges}))))
        told = self.add_missing_es_text()                                    # [s3-es-dir]
        if told:
            self.log("System 3's ES items gained the default writer direction (once): %d on %s"
                     % (len(told), ", ".join(sorted({b.split(":", 1)[0] for b in told}))))
        voiced = self.add_missing_es_voice()                                 # [s3-es-voice]
        if voiced:
            self.log("System 3's ES rows gained the default voices (once): %d on %s"
                     % (len(voiced), ", ".join(sorted({b.split(":", 1)[0] for b in voiced}))))
        legs = self.add_missing_call_legs()                                  # [s3-callend]
        if legs:
            self.log("System 3: " + legs)
        self._cast_load()                                                   # [s3-cast]
        adopted = self.adopt_mind_notes()
        if adopted:
            self.log("System 3 adopted the Mind desk's notes as table rows: " + "; ".join(adopted)[:380])
        self.ready = True

    def add_missing_conversation_graphs(self):
        """Version older System 3 books into visible graph surfaces.

        A custom banter cycle keeps its existing steps until its operator
        chooses the talk template. Protocol wrappers keep their existing
        internal planners intact.
        """
        import conversation_graph
        config = copy.deepcopy(self.config)
        changed = False
        structure = config.get("structure") or {}
        baseline = system3_tables.default_structure()
        if not (structure.get("graph") or {}).get("nodes") and structure.get("steps") == baseline.get("steps"):
            structure["graph"] = conversation_graph.default_graph()
            structure["graph"]["enabled"] = True
            changed = True
        for road, item in (config.get("structures") or {}).items():
            if not isinstance(item, dict):
                continue
            got = item.get("graph") or {}
            base_road = str(road).partition("~")[0]
            if not got.get("nodes"):
                item["graph"] = (conversation_graph.protocol_graph(road) if base_road == "caller"
                                 else conversation_graph.road_graph(base_road, item))
                changed = True
            elif (base_road != "caller" and len(got.get("nodes") or []) == 1
                    and (got["nodes"][0] or {}).get("type") == "protocol"):
                # [nodeplan] the untouched protocol macro becomes the road's own
                # talk chapter, OFF until the operator enables it: the config
                # hash prunes a disabled graph, so this fill moves nothing
                item["graph"] = conversation_graph.road_graph(base_road, item)
                changed = True
        if changed:
            self._save_config_now(config, "conversation graphs added to existing System 3 structures")
        return changed

    # --- [s3-cast] favourites and directives ----------------------------------
    def _cast_path(self):
        return self.host.data_path("system3_cast.json")

    def _cast_load(self):
        try:
            got = json.loads(Path(self._cast_path()).read_text(encoding="utf-8"))
            if isinstance(got, dict):
                self.cast = {"fav_recent": [str(x) for x in (got.get("fav_recent") or [])][-8:],
                             "directive_spent": {str(k): int(v) for k, v in (got.get("directive_spent") or {}).items()},
                             "counted": [str(x) for x in (got.get("counted") or [])][-400:]}
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def _cast_save(self):
        """Written on the store's own thread (a caller already on it writes inline)."""
        with self.lock:
            snap = json.loads(json.dumps(self.cast))

        def job():
            try:
                path = Path(self._cast_path())
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(snap), encoding="utf-8")
                tmp.replace(path)
            except Exception as exc:  # noqa: BLE001
                self.fail("cast state", exc)
        if threading.current_thread().name.startswith("system3-store"):
            job()
        else:
            _STORE_POOL.submit(job)

    # --- [s3-dice-door] the station's own rolls ---------------------------------
    def _dice_live(self):
        return bool(self.ready and self.settings.get("mode") in ("active", "active_selected_roads"))

    @staticmethod
    def _roll_buffer():
        buf = _S3_ROLLS.get()
        if buf is None:
            seed = hashlib.sha1(("%s|%s" % (time.time(), id(asyncio))).encode("utf-8")).hexdigest()[:16]
            buf = {"seed": seed, "stream": system3.DrawStream("station|" + seed), "rolls": []}
            _S3_ROLLS.set(buf)
        return buf

    def _find(self, family, key):
        """CHANCE: the item whose id is `key`; POOL: the category whose id is `key`."""
        for t in (self.config.get("tables") or []):
            if not isinstance(t, dict) or t.get("family") != family or t.get("enabled") is False:
                continue
            for c in t.get("categories") or []:
                if family == "POOL" and c.get("id") == key:
                    return c
                if family == "CHANCE":
                    for it in c.get("items") or []:
                        if isinstance(it, dict) and it.get("id") == key:
                            return it
        return None

    def _queue_row(self, kind, key, row):
        with self.lock:
            if key in self.dice_pending[kind]:
                return
            self.dice_pending[kind][key] = row
            if self._dice_timer is None:
                self._dice_timer = threading.Timer(DICE_FLUSH_AFTER, lambda: _STORE_POOL.submit(self.dice_flush))
                self._dice_timer.daemon = True
                self._dice_timer.start()

    def dice_flush(self):
        """Write the rows the station rolled before the desk had them, as one
        config version ("station rolls tabled: ..."). On the store's thread."""
        with self.lock:
            pend = {"chance": dict(self.dice_pending["chance"]), "pool": dict(self.dice_pending["pool"])}
            self.dice_pending = {"chance": {}, "pool": {}}
            self._dice_timer = None
        if not pend["chance"] and not pend["pool"]:
            return []
        config = copy.deepcopy(self.config)
        added = []
        st = self._pool_table(config, "STATION1", system3_tables.STATION1)
        for key, row in pend["chance"].items():
            if self._find_in(config, "CHANCE", key) is not None:
                continue
            dom = key.split(".", 1)[0] or "station"
            cat = next((c for c in st.setdefault("categories", []) if c.get("id") == dom), None)
            if cat is None:
                cat = {"id": dom, "label": dom.capitalize(), "weight": 1.0, "items": []}
                st["categories"].append(cat)
            cat.setdefault("items", []).append(row)
            added.append(key)
        pl = self._pool_table(config, "POOLS1", system3_tables.POOLS1)
        for key, cat in pend["pool"].items():
            if self._find_in(config, "POOL", key) is not None:
                continue
            pl.setdefault("categories", []).append(cat)
            added.append(key)
        if not added:
            return []
        try:
            self._save_config_now(config, "station rolls tabled: " + ", ".join(added)[:300])
        except Exception as exc:  # noqa: BLE001
            self.fail("dice rows", exc)
            return []
        return added

    @staticmethod
    def _find_in(config, family, key):
        for t in (config.get("tables") or []):
            if not isinstance(t, dict) or t.get("family") != family:
                continue
            for c in t.get("categories") or []:
                if family == "POOL" and c.get("id") == key:
                    return c
                if family == "CHANCE":
                    for it in c.get("items") or []:
                        if isinstance(it, dict) and it.get("id") == key:
                            return it
        return None

    def _record_roll(self, rec):
        rec["at"] = time.time()
        buf = self._roll_buffer()
        buf["rolls"] = (buf["rolls"] + [rec])[-ROLLS_KEPT:]
        self.station_rolls.append(rec)
        by_key = getattr(_S3_LAST, "by_key", None)                          # [s3-sfx-roll]
        if by_key is None:
            by_key = _S3_LAST.by_key = {}
        by_key[str(rec.get("key") or "")] = rec
        self.observe_later("station:" + time.strftime("%Y%m%d%H", time.gmtime()), "STATION", rec)

    def chance(self, key, odds, label="", dial=""):
        """[s3-dice-door] One of the station's `random() < odds` rolls, as System 3's
        die. A row that follows a desk dial rolls at the dial's value (the dial is
        where the operator sets it); otherwise the row's own odds. None when System
        3 is off: the station rolls its own."""
        if not self._dice_live():
            return None
        try:
            key = str(key)[:60]
            station_odds = round(system3.clamp(odds), 4)
            row = self._find("CHANCE", key)
            if row is None:
                self._queue_row("chance", key, {"id": key, "label": system3.label_cut(label or key), "text": system3.label_cut(label or key),
                                                "odds": station_odds, "dial": str(dial or ""), "weight": 1.0})
                use, why = station_odds, "the station's own odds (the row is being added to STATION1)"
            elif row.get("enabled") is False:
                use, why = 0.0, "switched off on the desk (STATION1)"
            elif row.get("dial"):
                use, why = station_odds, "follows the desk dial %s" % row.get("dial")
            else:
                use, why = round(system3.clamp(row.get("odds", station_odds)), 4), "the desk's odds (STATION1)"
            d = self._roll_buffer()["stream"].next("CHANCE:" + key)
            hit = bool(d["u"] < use)
            self._record_roll({"kind": "chance", "key": key, "label": system3.label_cut((row or {}).get("label") or label or key),
                               "odds": use, "u": d["u"], "dice": d["dice"], "hit": hit, "why": why})
            return hit
        except Exception as exc:  # noqa: BLE001
            self.fail("station chance", exc)
            return None

    def pool(self, key, defaults, label=""):
        """[s3-dice-door] The options a station roll draws from: the desk's POOLS1
        category (enabled, weighted), or the station's own list - which becomes
        that category the first time it is drawn. None when System 3 is off."""
        if not self._dice_live():
            return None
        try:
            key = str(key)[:60]
            opts = [" ".join(str(x).split()) for x in (defaults or []) if str(x or "").strip()]
            cat = self._find("POOL", key)
            if cat is None:
                if opts:
                    self._queue_row("pool", key, {"id": key, "label": system3.label_cut(label or key), "weight": 1.0,
                                                  "items": [{"id": "o%d" % i, "label": o[:60], "text": o, "weight": 1.0}
                                                            for i, o in enumerate(opts[:200])]})
                return opts + self._pool_event_rows(key)         # [s3-live-event]
            live = [str(i.get("text")) for i in cat.get("items") or []
                    if isinstance(i, dict) and i.get("enabled") is not False and float(i.get("weight", 1.0) or 0) > 0
                    and str(i.get("text") or "").strip()]
            return (live or opts) + self._pool_event_rows(key)   # [s3-live-event]
        except Exception as exc:  # noqa: BLE001
            self.fail("station pool", exc)
            return None

    def pool_items(self, key):
        """[s3-offer] The desk's POOLS1 category for `key` as the desk holds it -
        every item, switched on or off, with its weight - or None (not tabled)."""
        try:
            cat = self._find("POOL", str(key)[:60])
            if not cat:
                return None
            return [dict(i) for i in cat.get("items") or [] if isinstance(i, dict)]
        except Exception as exc:  # noqa: BLE001
            self.fail("station pool items", exc)
            return None

    def pick(self, key, candidates, label="", weights=None, media=None):
        """[s3-dice-door] Which of `candidates` (the options still eligible - a
        no-repeat ring may have held some back): a weighted draw, the weights
        the desk gave those options in POOLS1 - or, for a list the station
        keeps its own weights for (the ending shelf, the behaviour deck), the
        `weights` it hands in. Returns the index, or None.
        [s3-sfx-roll] `media` - a list by candidate, or a callable of the
        index - is the picture of what it lands on ({"poster", "thumb", ...});
        only the picked one is asked for and it rides the record."""
        if not self._dice_live():
            return None
        try:
            cands = [" ".join(str(c).split()) for c in (candidates or [])]
            if not cands:
                return None
            key = str(key)[:60]
            cat = self._find("POOL", key) or {}
            if weights is not None and len(list(weights)) == len(cands):
                w = [max(0.0, float(x or 0)) for x in weights]
            else:
                desk = {" ".join(str(i.get("text") or "").split()): float(i.get("weight", 1.0) or 0)
                        for i in cat.get("items") or [] if isinstance(i, dict)}
                w = [max(0.0, desk.get(c, 1.0)) for c in cands]
            if sum(w) <= 0:
                w = [1.0] * len(cands)
            d = self._roll_buffer()["stream"].next("PICK:" + key)
            k = system3.pick_index(w, d["u"])
            k = k if 0 <= k < len(cands) else 0
            rec = {"kind": "pick", "key": key, "label": system3.label_cut(cat.get("label") or label or key),
                   "of": len(cands), "index": k + 1, "picked": cands[k][:160], "u": d["u"], "dice": d["dice"],
                   "candidates": [c[:80] for c in cands[:12]]}
            if media is not None:                                                # [s3-sfx-roll]
                try:
                    m = media(k) if callable(media) else list(media)[k]
                except Exception:  # noqa: BLE001 - a picture never costs the roll
                    m = None
                if isinstance(m, dict) and m:
                    rec["media"] = {str(a): b for a, b in m.items()}
                    if m.get("poster"):
                        rec["poster"] = str(m["poster"])
            self._record_roll(rec)
            return k
        except Exception as exc:  # noqa: BLE001
            self.fail("station pick", exc)
            return None

    def roll(self, key, label=""):
        """[s3-dice-door] A plain number in [0, 1) off System 3's dice, recorded -
        for a station draw that is a band or a scale rather than a yes/no or a
        pick (which kind of subject a caller rings about, a pitch nudge)."""
        if not self._dice_live():
            return None
        try:
            key = str(key)[:60]
            d = self._roll_buffer()["stream"].next("ROLL:" + key)
            self._record_roll({"kind": "roll", "key": key, "label": system3.label_cut(label or key), "u": d["u"], "dice": d["dice"]})
            return float(d["u"])
        except Exception as exc:  # noqa: BLE001
            self.fail("station roll", exc)
            return None

    def last_roll(self, key):
        """[s3-sfx-roll] The roll this thread last recorded under `key` (a copy),
        or None. The road that rolled reads its own dice back - never re-derives
        them - to carry them to the line it makes."""
        rec = (getattr(_S3_LAST, "by_key", None) or {}).get(str(key)[:60])
        return dict(rec) if isinstance(rec, dict) else None

    def roll_to(self, key, cid, turn_id="", stage=""):
        """[s3-banks-roll] The roll this thread just made under `key` shaped a
        round that is ALREADY planned (a listening response at one of its seams,
        a banked round or a gold bar going out again). It is taken out of this
        task's buffer - the next plan must not absorb it as its own - and
        recorded on that round, conversation `cid`, as a STATION observation
        under `turn_id` (the Rolodex shows it there). Returns the roll as a
        line's stamp carries it, or {} (no fresh roll under `key`)."""
        try:
            key = str(key)[:60]
            rec = (getattr(_S3_LAST, "by_key", None) or {}).get(key)
            if not isinstance(rec, dict) or time.time() - float(rec.get("at") or 0) > 60:
                return {}
            buf = _S3_ROLLS.get()
            if buf and buf.get("rolls"):
                buf["rolls"] = [r for r in buf["rolls"] if r is not rec]
            out = {k: rec[k] for k in ("kind", "key", "label", "odds", "hit", "dice", "u",
                                       "index", "of", "picked", "at") if rec.get(k) is not None}
            if cid:
                # the turn rides the body too: the Rolodex files an observation
                # under the turn whose id it carries
                body = dict(out, stage=str(stage or "a station roll at air")[:240],
                            turn_id=str(turn_id or "") or None,
                            why=str(rec.get("why") or "")[:200] or None,
                            candidates=list(rec.get("candidates") or [])[:12] or None)
                self.observe_later(str(cid), "STATION", {k: v for k, v in body.items() if v is not None},
                                   turn_id=str(turn_id or ""))
                out["recorded_on"] = str(cid)
            return out
        except Exception as exc:  # noqa: BLE001
            self.fail("station roll on a round", exc)
            return {}

    # --- [s3-mgrtopics] the station manager's topic roulette ------------------------
    def _mgr_path(self):
        return self.host.data_path("system3_mgrtopics.json")

    def _mgr_hist(self):
        """His history, newest first: {topics, subs, approaches} (read once)."""
        hist = self.__dict__.get("mgr_hist")
        if hist is None:
            got = {}
            try:
                got = json.loads(Path(self._mgr_path()).read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError, AttributeError):
                got = {}
            hist = system3_mgrtopics.history_note(got if isinstance(got, dict) else {}, None)
            self.__dict__["mgr_hist"] = hist
        return hist

    def _mgr_save(self, hist):
        snap = json.loads(json.dumps(hist))

        def job():
            try:
                path = Path(self._mgr_path())
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(snap), encoding="utf-8")
                tmp.replace(path)
            except Exception as exc:  # noqa: BLE001
                self.fail("manager topics history", exc)
        if threading.current_thread().name.startswith("system3-store"):
            job()
        else:
            _STORE_POOL.submit(job)

    def _mgr_board(self):
        """The station's topics board (the Topics board list), as the manager's
        roll sees it: id, words, times sprung."""
        try:
            rows = self.host.read_bombshells() or []
        except Exception:  # noqa: BLE001
            return []
        out = []
        for r in rows:
            if not isinstance(r, dict) or not r.get("id"):
                continue
            text = " ".join(str(r.get("text") or "").split())
            if 12 <= len(text) <= 400:
                out.append({"id": str(r["id"]), "text": text, "used": int(r.get("used") or 0)})
        out.sort(key=lambda r: r["used"])
        return out[:system3_mgrtopics.BOARD_MOST]

    def manager_topic(self, road="upstairs"):
        """[s3-mgrtopics] The manager is writing a message downstairs: System 3
        rolls its main topic (his MGRTOPIC tables and the station's topics
        board, his recent topics held out or rested), his approach and the
        sub message (MGRSUB). Rolled on the task's dice and recorded: the
        round planned next on this task takes the three draws as its events.
        Returns what the writer is told, or None (System 3 off, nothing to
        draw, a fault - the road as it was)."""
        if system3_mgrtopics is None or not self._dice_live():
            return None
        try:
            with self.lock:
                hist = copy.deepcopy(self._mgr_hist())
            buf = self._roll_buffer()
            res = system3_mgrtopics.roll(self.config, buf["stream"], self._mgr_board(), hist["topics"],
                                         hist["subs"], hist["approaches"][0] if hist["approaches"] else "")
            if not res:
                return None
            new = system3_mgrtopics.history_note(hist, res)
            with self.lock:
                self.__dict__["mgr_hist"] = new
            self._mgr_save(new)
            last = dict(res["events"][-1]["rng"])
            small = {"kind": "mgrtopic", "key": system3_mgrtopics.ROLL_KEY, "road": str(road or ""),
                     "label": system3.label_cut("the manager's message: " + res["topic_text"]),
                     "u": last["u"], "dice": last["dice"], "at": time.time(),
                     "picked": " / ".join(x for x in (res["topic_text"], (res.get("approach") or {}).get("id", ""),
                                                      (res.get("sub") or {}).get("text", "")) if x)[:160],
                     "draws": [{"family": e["family"], "selected": (e.get("selected") or {}).get("id"),
                                "dice": (e.get("rng") or {}).get("dice"), "u": (e.get("rng") or {}).get("u"),
                                "of": (e.get("selected") or {}).get("of")} for e in res["events"]]}
            buf["rolls"] = (buf["rolls"] + [dict(small, result=res)])[-ROLLS_KEPT:]
            self.station_rolls.append(small)
            by_key = getattr(_S3_LAST, "by_key", None)
            if by_key is None:
                by_key = _S3_LAST.by_key = {}
            by_key[small["key"]] = small
            self.observe_later("station:" + time.strftime("%Y%m%d%H", time.gmtime()), "STATION", small)
            out = system3_mgrtopics.public(res)
            out["dice"] = [d["dice"] for d in small["draws"]]
            return out
        except Exception as exc:  # noqa: BLE001
            self.fail("manager topic", exc)
            return None

    def _absorb_rolls(self, conv):
        """The rolls the road made before asking for this round become its first
        events (STATION): recorded with their odds and dice, not replayed."""
        buf = _S3_ROLLS.get()
        if not buf or not buf.get("rolls"):
            return 0
        now = time.time()
        rolls = [r for r in buf["rolls"] if now - float(r.get("at") or 0) <= ROLLS_FRESH]
        buf["rolls"] = []
        ctx0 = {"turn_id": "", "turn_index": -1}
        for r in rolls:
            before = system3._snapshot(conv, (conv.get("cursor") or {}).get("initiator"))
            if r.get("kind") == "mgrtopic" and system3_mgrtopics is not None:   # [s3-mgrtopics] three draws
                system3_mgrtopics.absorb(conv, r, before, ctx0)
                continue
            if r.get("kind") == "roll":
                stages = [{"stage": "roll", "draw": {"u": r["u"], "dice": r["dice"]}, "selected": r["u"],
                           "rule": "a number in [0, 1) the road reads against its own bands"}]
                sel = {"id": str(r["dice"]), "label": "%s: %.3f" % (r["label"], r["u"]), "key": r["key"]}
            elif r.get("kind") == "chance":
                stages = [{"stage": "dice", "draw": {"u": r["u"], "dice": r["dice"]}, "threshold": r["odds"],
                           "rule": "a hit when the die lands under %.0f%% (%s)" % (r["odds"] * 100, r.get("why", "")),
                           "selected": "HIT" if r["hit"] else "MISS"}]
                sel = {"id": "HIT" if r["hit"] else "MISS", "label": "%s: %s" % (r["label"], "yes" if r["hit"] else "no"),
                       "key": r["key"]}
            else:
                stages = [{"stage": "item", "draw": {"u": r["u"], "dice": r["dice"]}, "selected": r.get("picked"),
                           "selected_index": r.get("index"), "of": r.get("of"), "candidates": [
                               {"id": str(i), "label": c, "base": 1.0, "weight": 1.0, "p": round(1.0 / max(1, r.get("of") or 1), 4),
                                "why": []} for i, c in enumerate(r.get("candidates") or [])]}]
                sel = {"id": str(r.get("index")), "label": "%s: %s" % (r["label"], system3.label_cut(r.get("picked") or "")),
                       "key": r["key"], "index": r.get("index"), "of": r.get("of")}
            meta = {"key": r["key"], "road_roll": True,
                    "why": "the station road rolled this before the round was planned; "
                           "its odds and options are on the desk (STATION1 / POOLS1)"}
            if r.get("media"):                                                   # [s3-sfx-roll]
                meta["media"] = r["media"]
            if r.get("poster"):
                meta["poster"] = r["poster"]
            ev = system3._event(conv, ctx0, "STATION", stages, sel, before, meta=meta,
                                rng={"u": r["u"], "dice": r["dice"], "label": r["key"]})
            ev["state_after"] = before
        return len(rolls)

    def station_view(self, limit=120):
        return list(self.station_rolls)[-int(limit):]

    # --- [s3-blocks] every block of a writer prompt is a node --------------------
    def blocks(self, names, mark=None, tint=False, dial=None):
        """Decide each marked block of one prompt (in order). Recorded as BLOCK
        events on the conversation the station is writing for (_S3_WRITE), and
        returned for the prompt's own record. None when System 3 is off: the
        station sends every block, as it always did."""
        if not self._dice_live():
            return None
        try:
            handle = _S3_WRITE.get()
            conv = handle.conv if handle is not None and getattr(handle, "active", False) else None
            if conv is not None and time.time() - float(conv.get("created") or 0) > 900:
                conv = None                # a handle left over from a round long written: not this prompt's
            if conv is not None:
                conv["prompts"] = int(conv.get("prompts") or 0) + 1
                seed = "%s|prompt%d" % (conv["seed"], conv["prompts"])
            else:
                seed = "prompt|" + hashlib.sha1(("%s|%s" % (time.time(), id(names))).encode("utf-8")).hexdigest()[:16]
            out = system3.decide_blocks(list(names or []), self.config, seed, conv=conv, tint_on=bool(tint), dial=dial)
            with self.lock:
                self.metrics["blocks_decided"] = self.metrics.get("blocks_decided", 0) + len(out)
                self.metrics["blocks_stripped"] = self.metrics.get("blocks_stripped", 0) + sum(1 for x in out if not x["keep"])
            return out
        except Exception as exc:  # noqa: BLE001
            self.fail("prompt blocks", exc)
            return None

    def note_prompt(self, digest, decisions, mark=None):
        """What System 3 decided for the prompt whose words hash to `digest` -
        the Prompt tab asks for it by the same digest of the request it holds."""
        try:
            handle = _S3_WRITE.get()
            rec = {"digest": str(digest), "at": time.time(), "mark": dict(mark or {}),
                   "conversation_id": (handle.conv["identity"]["conversation_id"]
                                       if handle is not None and getattr(handle, "conv", None) else ""),
                   "blocks": list(decisions or [])}
            with self.lock:
                self.prompt_blocks[str(digest)] = rec
                self.prompt_blocks.move_to_end(str(digest))
                while len(self.prompt_blocks) > 600:
                    self.prompt_blocks.popitem(last=False)
            self.observe_later(rec["conversation_id"] or ("station:" + time.strftime("%Y%m%d%H", time.gmtime())),
                               "PROMPT", {"digest": rec["digest"], "mark": rec["mark"],
                                          "stripped": [b.get("name") for b in rec["blocks"] if not b.get("keep")],
                                          "blocks": [{k: b.get(k) for k in ("name", "kind", "keep", "why", "odds", "u", "chars")}
                                                     for b in rec["blocks"]]})
        except Exception as exc:  # noqa: BLE001
            self.fail("prompt note", exc)

    # --- [s3-flow] uniqueness ------------------------------------------------------
    def recent_used(self):
        with self.lock:
            return list(dict.fromkeys(self.recent_items))

    def _note_used(self, conv):
        """The items an active round rolled (CTS/RS/IRS/FL/EVENT) rest for the next rounds."""
        keys = [("%s:%s" % (d.get("family"), d.get("item")))
                for t in conv.get("turns") or [] for d in t.get("decisions") or []
                if d.get("family") in ("CTS", "RS", "IRS", "FL", "EVENT") and d.get("item")
                and d.get("item") not in ("OBLIGATED", "CONTINUE")]
        with self.lock:
            for k in keys:
                if k in self.recent_items:
                    self.recent_items.remove(k)
                self.recent_items.append(k)

    @staticmethod
    def _words(text):
        return re.findall(r"[a-z0-9']+", str(text or "").lower())

    def near_repeats(self, turns):
        """Script indices whose words nearly repeat a line already on air: ten
        words running in common, or 85% the same line."""
        import difflib
        with self.lock:
            aired = [self._words(x) for x in self.recent_air]
        out = []
        for i, (_who, text) in enumerate(turns or []):
            w = self._words(text)
            if len(w) < 8:
                continue
            for a in aired:
                if len(a) < 8:
                    continue
                sm = difflib.SequenceMatcher(None, w, a, autojunk=False)
                run = sm.find_longest_match(0, len(w), 0, len(a)).size
                if run >= 10 or (min(len(w), len(a)) >= 8 and sm.ratio() >= 0.85):
                    out.append(i)
                    break
        return out

    def cast_inputs(self):
        """What the FAV and DIRECTIVE rolls read beyond the tables."""
        with self.lock:
            return {"cast_rolls": True, "fav_recent": list(self.cast.get("fav_recent") or []),
                    "directive_spent": dict(self.cast.get("directive_spent") or {})}

    def _cast_note(self, conv):
        """An active plan that surfaced a favourite: it rests for the next draws."""
        fav = conv.get("fav_plan")
        if not isinstance(fav, dict) or not fav.get("id"):
            return
        with self.lock:
            recent = [x for x in self.cast.get("fav_recent") or [] if x != fav["id"]] + [str(fav["id"])]
            self.cast["fav_recent"] = recent[-6:]
        self._cast_save()

    def _cast_aired(self, conv):
        """A round reached the script ledger: each directive it carried aired once."""
        cid = str((conv.get("identity") or {}).get("conversation_id") or "")
        plans = [p for p in (conv.get("directive_plans") or []) if isinstance(p, dict) and p.get("id")]
        if not cid or not plans:
            return
        with self.lock:
            if cid in self.cast["counted"]:
                return
            self.cast["counted"] = (self.cast["counted"] + [cid])[-400:]
            for p in plans:
                self.cast["directive_spent"][str(p["id"])] = int(self.cast["directive_spent"].get(str(p["id"])) or 0) + 1
        self._cast_save()

    def _save_config_now(self, config, note):
        """Save a config version from any thread: inline on the store's own
        thread, through it from anywhere else."""
        if threading.current_thread().name.startswith("system3-store"):
            h = self.store.save_config(config, note)
        else:
            h = _STORE_POOL.submit(self.store.save_config, config, note).result(timeout=20)
        self.config = config
        self.log("System 3 config is now %s (%s)" % (h, note))
        return h

    @staticmethod
    def _norm_words(text):
        return " ".join(re.findall(r"[a-z0-9']+", str(text or "").lower()))

    @staticmethod
    def _pool_table(config, table_id, default):
        tables = config.setdefault("tables", [])
        got = next((t for t in tables if isinstance(t, dict) and t.get("id") == table_id), None)
        if got is None:
            got = copy.deepcopy(default)
            tables.append(got)
            config["defaults_added"] = sorted({str(x) for x in (config.get("defaults_added") or [])} | {table_id})
        return got

    def favorite_set(self, line_id, text, who="", name="", liked=True):
        """[s3-cast] A thumbs-up puts the line in FAV1 - the whole cast's
        favourites, drawn by the FAV roll, never stapled to a prompt; a
        thumbs-down (or a cleared vote) takes it out. Saved as a config
        version with a note, like any edit from the desk."""
        words = system3.sentence_cut(text, 400)
        lid = str(line_id or "")
        key = self._norm_words(words)
        config = copy.deepcopy(self.config)
        has = any(isinstance(t, dict) and t.get("id") == "FAV1" for t in config.get("tables") or [])
        if not liked and not has:
            return {"changed": False}
        fav = self._pool_table(config, "FAV1", system3_tables.FAV1)
        cat = next((c for c in fav.setdefault("categories", []) if c.get("id") == "liked"), None)
        if cat is None:
            cat = {"id": "liked", "label": "Liked lines", "weight": 1.0, "items": []}
            fav["categories"].append(cat)
        items = cat.setdefault("items", [])

        def same(it):
            return bool((lid and str(it.get("line_id") or "") == lid) or (key and self._norm_words(it.get("text")) == key))
        if liked:
            if not key:
                return {"changed": False, "why": "the line has no words"}
            if any(same(it) for it in items):
                return {"changed": False, "why": "already one of the favourites"}
            iid = "fav_" + hashlib.sha1((lid or key).encode("utf-8")).hexdigest()[:10]
            items.append({"id": iid, "label": words[:60], "text": words, "weight": 1.0,
                          "seat": _SEAT_OF.get(str(who or ""), ""), "who": str(who or ""), "name": str(name or ""),
                          "line_id": lid, "at": round(time.time(), 1)})
            note = "favourite added (%s): %s" % (name or who or "the cast", words[:60])
        else:
            keep = [it for it in items if not same(it)]
            if len(keep) == len(items):
                return {"changed": False}
            cat["items"] = keep
            iid = ""
            note = "favourite removed: %s" % words[:60]
        fav["version"] = int(fav.get("version") or 1) + 1
        try:
            h = self._save_config_now(config, note)
        except Exception as exc:  # noqa: BLE001
            self.fail("favourite", exc)
            return {"changed": False, "why": "%s: %s" % (type(exc).__name__, str(exc)[:80])}
        return {"changed": True, "hash": h, "table": "FAV1", "id": iid, "count": len(cat["items"])}

    _LIKED_NOTE = re.compile(r'^The operator liked this line of yours: "(?P<line>.+)" - say things like it', re.S)

    def adopt_mind_notes(self):
        """[s3-cast] Once: the Mind desk's note book (settings.dj.mind_adjustments,
        which reached every host prompt as "LIVE MIND ADJUSTMENTS") becomes table
        rows - a liked line a FAV1 favourite, anything the operator wrote a
        DIRECTIVE1 row for its seat at odds 100%, exactly as it stood. Marked
        `mind_notes_adopted`, so nothing is adopted twice."""
        config = self.config if isinstance(self.config, dict) else {}
        if config.get("mind_notes_adopted"):
            return []
        try:
            dj = self.host.dj_settings() or {}
        except Exception:  # noqa: BLE001
            return []                       # a host with no desk (tests): nothing to adopt
        notes = dj.get("mind_adjustments") if isinstance(dj.get("mind_adjustments"), dict) else {}
        new = copy.deepcopy(config)
        fav = self._pool_table(new, "FAV1", system3_tables.FAV1)
        liked = next((c for c in fav.setdefault("categories", []) if c.get("id") == "liked"), None)
        if liked is None:
            liked = {"id": "liked", "label": "Liked lines", "weight": 1.0, "items": []}
            fav["categories"].append(liked)
        drt = self._pool_table(new, "DIRECTIVE1", system3_tables.DIRECTIVE1)
        cats = {c.get("id"): c for c in drt.setdefault("categories", []) if isinstance(c, dict)}
        names = {"dj": dj.get("host_name"), "cohost": dj.get("cohost_name"), "third": dj.get("third_name")}
        seat_cat = {"dj": "host", "cohost": "cohost", "third": "third"}
        done = []
        for who, rows in notes.items():
            for row in rows if isinstance(rows, list) else []:
                text = " ".join(str((row or {}).get("text") or "").split()) if isinstance(row, dict) else ""
                if not text:
                    continue
                m = self._LIKED_NOTE.match(text)
                if m:
                    line = system3.sentence_cut(m.group("line"), 400)
                    if any(self._norm_words(it.get("text")) == self._norm_words(line) for it in liked["items"]):
                        continue
                    liked["items"].append({"id": "fav_" + hashlib.sha1(self._norm_words(line).encode("utf-8")).hexdigest()[:10],
                                           "label": system3.label_cut(line), "text": line, "weight": 1.0,
                                           "seat": _SEAT_OF.get(who, ""), "who": who, "name": str(names.get(who) or ""),
                                           "line_id": str(row.get("liked_line") or ""), "at": float(row.get("at") or 0),
                                           "source": "the Mind desk's note book"})
                    done.append("favourite (%s): %s" % (who, line[:40]))
                elif who in seat_cat and seat_cat[who] in cats:
                    cat = cats[seat_cat[who]]
                    cat.setdefault("items", []).append({
                        "id": "dir_" + hashlib.sha1((who + text).encode("utf-8")).hexdigest()[:10],
                        "label": system3.label_cut(text), "text": system3.whole_cut(text, 500), "weight": 1.0, "odds": 1.0, "until": 0, "airings": 0,
                        "source": "the Mind desk's note book"})
                    done.append("directive (%s): %s" % (who, text[:40]))
                else:
                    done.append("left on the Mind desk (%s is not a host seat): %s" % (who, text[:40]))
        new["mind_notes_adopted"] = True
        try:
            self._save_config_now(new, "the Mind desk's notes adopted: %d row(s)" % len(done))
        except Exception as exc:  # noqa: BLE001
            self.fail("adopt mind notes", exc)
            return []
        return done

    def add_missing_default_tables(self):
        """[s3-rounds] The store is the authority and it was saved before some
        default tables existed (TEMPER1, SHOCK1, INTERJECT1 on 2026-09-27: the
        station restarted on the new engine and rolled nothing, because the
        live config had eight tables). Each default table the config has
        never held is added once and remembered in `defaults_added`, so a
        table the operator later deletes stays deleted. Saved as a version
        with a note, like any edit from the desk."""
        config = self.config if isinstance(self.config, dict) else {}
        have = {str(t.get("id")) for t in (config.get("tables") or []) if isinstance(t, dict)}
        seen = {str(x) for x in (config.get("defaults_added") or [])}
        missing = [t for t in system3_tables.default_tables()
                   + system3_tables.default_event_tables()      # [s3-live-event]
                   if t["id"] not in have and t["id"] not in seen]
        if system3_mgrtopics is not None:                                   # [s3-mgrtopics] his two tables, once
            missing += [t for t in system3_mgrtopics.default_tables() if t["id"] not in have and t["id"] not in seen]
        if system3_gold is not None:                                        # [s3-gold:tables] GOLD1, once
            missing += [t for t in system3_gold.default_tables() if t["id"] not in have and t["id"] not in seen]
        try:                                                                # [outl-tables] the meter's six, once
            import outlandish as _outl
            missing += [t for t in _outl.default_tables() if t["id"] not in have and t["id"] not in seen]
        except Exception as exc:  # noqa: BLE001
            self.fail("outlandish tables", exc)
        if not missing:
            return []
        new = copy.deepcopy(config)
        new.setdefault("tables", []).extend(copy.deepcopy(missing))
        new["defaults_added"] = sorted(seen | {t["id"] for t in missing})
        ids = [t["id"] for t in missing]
        try:
            self.store.save_config(new, "tables added from the defaults: " + ", ".join(ids))
        except Exception as exc:  # noqa: BLE001
            self.fail("default tables", exc)
            return []
        self.config = new
        return ids

    # --- [s3-live-event] station events ------------------------------------
    EVENTS_MARK = "STATION_EVENTS"     # in defaults_added: register + block, once
    EVENT_AFTER_DEFAULT = 1800.0

    def add_missing_station_events(self):
        """[s3-live-event] Once: the station-events register (MX Live) and the
        event_facts block onto a stored config that predates them. Remembered
        in defaults_added, so an event or the block the operator later
        removes stays removed. Saved as a version with a note."""
        config = self.config if isinstance(self.config, dict) else {}
        seen = {str(x) for x in (config.get("defaults_added") or [])}
        if self.EVENTS_MARK in seen:
            return []
        new = copy.deepcopy(config)
        added = []
        reg = new.setdefault("events", {})
        for eid, ev in system3_tables.default_events().items():
            if eid not in reg:
                reg[eid] = ev
                added.append("event " + eid)
        blocks = new.setdefault("blocks", system3_tables.default_blocks())
        for name, rule in system3_tables.default_event_blocks().items():
            if name not in blocks:
                blocks[name] = rule
                added.append("block " + name)
        new["defaults_added"] = sorted(seen | {self.EVENTS_MARK})
        try:
            self.store.save_config(new, "station events: " + (", ".join(added) or "marker only"))
        except Exception as exc:  # noqa: BLE001
            self.fail("station events register", exc)
            return []
        self.config = new
        return added

    def _pinelive_state(self):
        """PineLive's in-process read (never raises, never blocks); tests
        stub `event_probe`."""
        probe = getattr(self, "event_probe", None)
        if callable(probe):
            try:
                return probe() or {}
            except Exception:  # noqa: BLE001
                return {}
        try:
            import pinelive
            return pinelive.event_state() or {}
        except Exception:  # noqa: BLE001
            return {}

    def station_events(self):
        """{id: {stage, name, source}} for every station event that is ON
        right now - what event_view filters the wheels by. An event that is
        off is absent, and every draw is then today's draw."""
        out = {}
        try:
            reg = (self.config.get("events") or {}) if isinstance(self.config, dict) else {}
            if not reg:
                return out
            now = time.time()
            mem = getattr(self, "_event_mem", None)
            if mem is None:
                mem = self._event_mem = {}
            for eid, ev in reg.items():
                if not isinstance(ev, dict) or ev.get("enabled") is False:
                    continue
                eid = str(eid)
                src = str(ev.get("source") or "manual")
                window = float(ev.get("after_window") or self.EVENT_AFTER_DEFAULT)
                stage = ""
                if src == "pinelive":
                    st = self._pinelive_state()
                    if st.get("enabled") is not False and st.get("armed"):
                        stage = {"arming": "upcoming", "live": "live",
                                 "fallback": "fallback"}.get(str(st.get("phase") or ""), "live")
                        mem[eid] = {"seen_at": now}
                    else:
                        seen = mem.get(eid) or {}
                        if seen.get("seen_at") and now - float(seen["seen_at"]) <= window:
                            stage = "after"
                else:
                    if ev.get("active"):
                        starts = float(ev.get("starts_at") or 0)
                        ends = float(ev.get("ends_at") or 0)
                        stage = ("upcoming" if (starts and now < starts)
                                 else "after" if (ends and now > ends) else "live")
                        if stage == "after" and ends and now - ends > window:
                            stage = ""
                        if stage == "live":
                            mem[eid] = {"seen_at": now}
                if stage:
                    out[eid] = {"stage": stage, "name": str(ev.get("name") or eid), "source": src}
            return out
        except Exception as exc:  # noqa: BLE001
            self.fail("station events", exc)
            return {}

    def events_view(self):
        """The register with each event's stage right now, for Controls."""
        out = []
        try:
            live = self.station_events()
            for eid, ev in ((self.config.get("events") or {}) if isinstance(self.config, dict) else {}).items():
                if not isinstance(ev, dict):
                    continue
                got = live.get(str(eid)) or {}
                out.append({"id": str(eid), "name": str(ev.get("name") or eid),
                            "source": str(ev.get("source") or "manual"),
                            "what": str(ev.get("what") or "")[:200],
                            "stage": str(got.get("stage") or ""), "on": bool(got),
                            "tables": [str(t.get("id")) for t in (self.config.get("tables") or [])
                                       if isinstance(t, dict) and str(t.get("event") or "") == str(eid)]})
        except Exception as exc:  # noqa: BLE001
            self.fail("events view", exc)
        return out

    def record_event_of(self, ctx):
        """The id of the pinelive-sourced event whose live set IS the record
        on air (the pseudo-record carries `pinelive`; its title is the
        event's name), or ''."""
        try:
            rec = ctx.get("record") if isinstance(ctx.get("record"), dict) else {}
            if not rec:
                return ""
            for eid, ev in (self.station_events() or {}).items():
                if ev.get("source") != "pinelive" or ev.get("stage") != "live":
                    continue
                if rec.get("pinelive") or str(rec.get("title") or "") == str(ev.get("name") or ""):
                    return str(eid)
            return ""
        except Exception:  # noqa: BLE001
            return ""

    def _pool_event_rows(self, key):
        """Rows a station event lends a station wheel while it is on (family
        ANGLE, the table's `pool` names the wheel), stage-filtered; [] while
        every event is off - the wheel then draws exactly as it always did."""
        try:
            events = self.station_events()
            if not events:
                return []
            out = []
            for t in (self.config.get("tables") or []):
                if not (isinstance(t, dict) and t.get("family") == "ANGLE" and t.get("enabled", True)
                        and str(t.get("pool") or "") == str(key) and str(t.get("event") or "") in events):
                    continue
                stage = events[str(t["event"])]["stage"]
                for c in t.get("categories") or []:
                    if not isinstance(c, dict) or c.get("enabled") is False:
                        continue
                    stages = [str(s) for s in (c.get("event_stages") or [])]
                    if stages and stage not in stages:
                        continue
                    for i in c.get("items") or []:
                        if (isinstance(i, dict) and i.get("enabled") is not False
                                and str(i.get("text") or "").strip()
                                and float(i.get("weight", 1.0) or 0) > 0):
                            out.append(" ".join(str(i["text"]).split()))
            return out
        except Exception as exc:  # noqa: BLE001
            self.fail("event pool", exc)
            return []

    def _event_line_candidates(self, road, dj):
        """Rows a station event lends a single-voice road's LINE wheel while
        it is on (EVENT tables carrying this road, stage-filtered): each item
        a candidate beside the road's own stock, weighted, its why naming the
        event. [] while every event is off."""
        try:
            events = self.station_events()
            if not events:
                return []
            station = " ".join(str((dj or {}).get("station_name") or "").split()) or "the station"
            out = []
            for t in (self.config.get("tables") or []):
                if not (isinstance(t, dict) and t.get("family") == "EVENT" and t.get("enabled", True)
                        and str(t.get("event") or "") in events
                        and road in [str(r) for r in (t.get("roads") or [])]):
                    continue
                ev = events[str(t["event"])]
                for c in t.get("categories") or []:
                    if not isinstance(c, dict) or c.get("enabled") is False:
                        continue
                    stages = [str(s) for s in (c.get("event_stages") or [])]
                    if stages and ev["stage"] not in stages:
                        continue
                    for i in c.get("items") or []:
                        if not (isinstance(i, dict) and i.get("enabled") is not False
                                and str(i.get("text") or "").strip()
                                and float(i.get("weight", 1.0) or 0) > 0):
                            continue
                        out.append({"id": "%s:%s:%s" % (t["id"], c["id"], i.get("id")),
                                    "text": " ".join(str(i["text"]).split()).replace("{station}", station)[:400],
                                    "weight": float(i.get("weight", 1.0) or 0) * float(c.get("weight", 1.0) or 0),
                                    "why": ["station event %s (%s)" % (ev["name"], ev["stage"])]})
            return out
        except Exception as exc:  # noqa: BLE001
            self.fail("event line rows", exc)
            return []

    def event_facts_text(self):
        """[s3-live-event] The words of the event_facts block for the prompt
        being written on this task - only when a roll in its round landed on
        one of the event's rows; '' otherwise (the block is then never
        marked, and decide_blocks' kind "claimed" records why)."""
        if not self.ready:
            return ""
        try:
            handle = _S3_WRITE.get()
            conv = handle.conv if handle is not None and getattr(handle, "active", False) else None
            if not isinstance(conv, dict):
                return ""
            claims = system3.event_claims(conv)
            if not claims:
                return ""
            ids = set()
            for t in (self.config.get("tables") or []):
                if (isinstance(t, dict) and t.get("event")
                        and any(c.startswith(str(t.get("id")) + ":") for c in claims)):
                    ids.add(str(t["event"]))
            live = self.station_events()
            parts = []
            for eid in sorted(ids):
                ev = ((self.config.get("events") or {}).get(eid) or {})
                facts = ev.get("facts") or {}
                stage = str((live.get(eid) or {}).get("stage") or "")
                bits = ["THE STATION EVENT ON THIS ORDER (%s): %s."
                        % (str(ev.get("name") or eid),
                           str(facts.get("what") or ev.get("what") or eid).rstrip("."))]
                if facts.get("who"):
                    bits.append("Who: %s." % str(facts["who"]).rstrip("."))
                if facts.get("device"):
                    bits.append("The instrument: %s." % str(facts["device"]).rstrip("."))
                bits.append("Right now it is %s." % {
                    "upcoming": "armed - it has not started",
                    "live": "LIVE on the air underneath you",
                    "fallback": "live, but the input has dropped out for a moment",
                    "after": "just finished"}.get(stage, "over"))
                for n in (facts.get("notes") or [])[:4]:
                    bits.append(str(n))
                parts.append(" ".join(bits))
            with self.lock:
                self.metrics["event_facts_blocks"] = self.metrics.get("event_facts_blocks", 0) + 1
            return ("\n\n" + "\n".join(parts)) if parts else ""
        except Exception as exc:  # noqa: BLE001
            self.fail("event facts", exc)
            return ""

    ES_EMOJI_MARK = "ES_EMOJI"         # [s3-es-emoji] in defaults_added: the badges were given once

    def add_missing_es_emoji(self):
        """[s3-es-emoji] Once: the ES badges (an emoji per category and per
        item, system3_tables.ES1) onto the stored config, which predates them.
        On every ES-family table, a category or item whose id matches the
        defaults gets the default emoji ONLY where it has no `emoji` key at
        all. Remembered in `defaults_added` (ES_EMOJI_MARK), so it never runs
        again: an emoji the operator later clears ("") stays cleared. Saved as
        one version with a note. Returns what was filled ("ES1:anger", ...)."""
        config = self.config if isinstance(self.config, dict) else {}
        seen = {str(x) for x in (config.get("defaults_added") or [])}
        if self.ES_EMOJI_MARK in seen:
            return []
        es1 = system3_tables.ES1
        cat_emoji = {c["id"]: c["emoji"] for c in es1["categories"] if c.get("emoji")}
        item_emoji = {i["id"]: i["emoji"] for c in es1["categories"] for i in c["items"] if i.get("emoji")}
        new = copy.deepcopy(config)
        filled, tables = [], []
        for t in new.get("tables") or []:
            if not isinstance(t, dict) or t.get("family") != "ES":
                continue
            before = len(filled)
            for c in t.get("categories") or []:
                if not isinstance(c, dict):
                    continue
                if "emoji" not in c and cat_emoji.get(str(c.get("id") or "")):
                    c["emoji"] = cat_emoji[str(c["id"])]
                    filled.append("%s:%s" % (t.get("id"), c["id"]))
                for it in c.get("items") or []:
                    if isinstance(it, dict) and "emoji" not in it and item_emoji.get(str(it.get("id") or "")):
                        it["emoji"] = item_emoji[str(it["id"])]
                        filled.append("%s:%s" % (t.get("id"), it["id"]))
            if len(filled) > before:
                tables.append(str(t.get("id")))
        if not filled:
            return []
        new["defaults_added"] = sorted(seen | {self.ES_EMOJI_MARK})
        try:
            self.store.save_config(new, "ES emoji badges added from the defaults (once): %d on %s"
                                   % (len(filled), ", ".join(tables)))
        except Exception as exc:  # noqa: BLE001
            self.fail("ES emoji", exc)
            return []
        self.config = new
        return filled

    ES_VOICE_MARK = "ES_VOICE"         # [s3-es-voice] in defaults_added: the voices were given once

    def add_missing_es_voice(self):
        """[s3-es-voice] Once: the default voices (system3_tables.ES1: a `voice`
        block per category, and on the items that sound unlike theirs) onto the
        stored config, which predates them. On every ES-family table, a category
        or item whose id matches the defaults gets the default block ONLY where
        it has no `voice` key. Remembered in `defaults_added` (ES_VOICE_MARK):
        a voice the operator clears or removes later stays that way, and a
        category of their own gets none. Saved as one version with a note."""
        config = self.config if isinstance(self.config, dict) else {}
        seen = {str(x) for x in (config.get("defaults_added") or [])}
        if self.ES_VOICE_MARK in seen:
            return []
        es1 = system3_tables.ES1
        cat_voice = {c["id"]: c["voice"] for c in es1["categories"] if isinstance(c.get("voice"), dict)}
        item_voice = {i["id"]: i["voice"] for c in es1["categories"] for i in c["items"]
                      if isinstance(i.get("voice"), dict)}
        new = copy.deepcopy(config)
        filled, tables = [], []
        for t in new.get("tables") or []:
            if not isinstance(t, dict) or t.get("family") != "ES":
                continue
            before = len(filled)
            for c in t.get("categories") or []:
                if not isinstance(c, dict):
                    continue
                if "voice" not in c and str(c.get("id") or "") in cat_voice:
                    c["voice"] = copy.deepcopy(cat_voice[str(c["id"])])
                    filled.append("%s:%s" % (t.get("id"), c["id"]))
                for it in c.get("items") or []:
                    if isinstance(it, dict) and "voice" not in it and str(it.get("id") or "") in item_voice:
                        it["voice"] = copy.deepcopy(item_voice[str(it["id"])])
                        filled.append("%s:%s" % (t.get("id"), it["id"]))
            if len(filled) > before:
                tables.append(str(t.get("id")))
        if not filled:
            return []
        new["defaults_added"] = sorted(seen | {self.ES_VOICE_MARK})
        try:
            self.store.save_config(new, "ES voices added from the defaults (once): %d on %s"
                                   % (len(filled), ", ".join(tables)))
        except Exception as exc:  # noqa: BLE001
            self.fail("ES voices", exc)
            return []
        self.config = new
        return filled

    ES_V2_MARK = "ES_V2"               # [es-v2] in defaults_added: ES1's second edition was taken once

    @staticmethod
    def es_v2_changes(config):
        """[es-v2] (new config, moved, kept): `config` with every ES row that still
        holds its v1 default moved to system3_tables.ES1_V2 - the voice of a
        category or item, the direction of an item. `kept` lists the rows the
        operator made their own (edited, cleared or removed), left as they are."""
        v1, v2 = system3_tables.ES1, system3_tables.ES1_V2
        clean = system3.clean_es_voice
        v1_cat = {c["id"]: c.get("voice") for c in v1["categories"]}
        v2_cat = {c["id"]: c.get("voice") for c in v2["categories"]}
        v1_item = {i["id"]: i for c in v1["categories"] for i in c["items"]}
        v2_item = {i["id"]: i for c in v2["categories"] for i in c["items"]}
        new = copy.deepcopy(config if isinstance(config, dict) else {})
        moved, kept = [], []

        def voice(row, was, now, where):
            if was is None:                                  # v1 had none: absent is the default
                if "voice" not in row and now is not None:
                    row["voice"] = copy.deepcopy(now)
                    moved.append(where + " voice")
                elif "voice" in row and clean(row["voice"]) != clean(now):
                    kept.append(where + " voice")
                return
            if "voice" not in row or clean(row["voice"]) != clean(was):
                if clean(row.get("voice")) != clean(now):
                    kept.append(where + " voice")
                return
            if clean(now) != clean(was):
                row["voice"] = copy.deepcopy(now)
                moved.append(where + " voice")

        for t in new.get("tables") or []:
            if not isinstance(t, dict) or t.get("family") != "ES":
                continue
            for c in t.get("categories") or []:
                if not isinstance(c, dict):
                    continue
                cid = str(c.get("id") or "")
                if cid in v1_cat:
                    voice(c, v1_cat[cid], v2_cat[cid], "%s:%s" % (t.get("id"), cid))
                for it in c.get("items") or []:
                    iid = str((it or {}).get("id") or "") if isinstance(it, dict) else ""
                    if iid not in v1_item:
                        continue
                    where = "%s:%s" % (t.get("id"), iid)
                    voice(it, v1_item[iid].get("voice"), v2_item[iid].get("voice"), where)
                    if it.get("text") == v1_item[iid].get("text"):
                        if v2_item[iid].get("text") != it.get("text"):
                            it["text"] = v2_item[iid]["text"]
                            moved.append(where + " direction")
                    elif it.get("text") != v2_item[iid].get("text"):
                        kept.append(where + " direction")
        return new, moved, kept

    def upgrade_es_v2(self, apply=True):
        """[es-v2] ES1's second edition onto the stored config, once (ES_V2_MARK).
        apply=False only reports. Returns {moved, kept, done, hash}."""
        config = self.config if isinstance(self.config, dict) else {}
        seen = {str(x) for x in (config.get("defaults_added") or [])}
        new, moved, kept = self.es_v2_changes(config)
        out = {"moved": moved, "kept": kept, "done": self.ES_V2_MARK in seen,
               "hash": system3.config_hash(config)}
        if not apply or out["done"]:
            return out
        new["defaults_added"] = sorted(seen | {self.ES_V2_MARK})
        try:
            out["hash"] = self.store.save_config(
                new, "ES1 second edition (es-v2): %d rows moved to the recalibrated voices and actor "
                     "directions, %d kept as the operator left them" % (len(moved), len(kept)))
        except Exception as exc:  # noqa: BLE001
            self.fail("ES v2", exc)
            return dict(out, error=str(exc))
        self.config = new
        out["done"] = True
        self.log("System 3's ES tables took their second edition (es-v2): %d moved, %d kept"
                 % (len(moved), len(kept)))
        return out

    ES_TEXT_MARK = "ES_TEXT"           # [s3-es-dir] in defaults_added: the directions were given once

    def add_missing_es_text(self):
        """[s3-es-dir] Once: the default writer direction ("Write {name}'s message
        with {feeling}, reflecting the mood.") onto every ES-family item whose
        `text` key is absent. Remembered in `defaults_added` (ES_TEXT_MARK), so
        it never runs again: a direction the operator later clears stays
        cleared. Saved as one version with a note. Returns what was filled."""
        config = self.config if isinstance(self.config, dict) else {}
        seen = {str(x) for x in (config.get("defaults_added") or [])}
        if self.ES_TEXT_MARK in seen:
            return []
        new = copy.deepcopy(config)
        filled, tables = [], []
        for t in new.get("tables") or []:
            if not isinstance(t, dict) or t.get("family") != "ES":
                continue
            before = len(filled)
            for c in t.get("categories") or []:
                for it in (c.get("items") or []) if isinstance(c, dict) else []:
                    if isinstance(it, dict) and "text" not in it and it.get("id"):
                        it["text"] = system3_tables.ES_DIRECTION
                        filled.append("%s:%s" % (t.get("id"), it["id"]))
            if len(filled) > before:
                tables.append(str(t.get("id")))
        if not filled:
            return []
        new["defaults_added"] = sorted(seen | {self.ES_TEXT_MARK})
        try:
            self.store.save_config(new, "ES writer directions added from the defaults (once): %d on %s"
                                   % (len(filled), ", ".join(tables)))
        except Exception as exc:  # noqa: BLE001
            self.fail("ES directions", exc)
            return []
        self.config = new
        return filled

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
        seed_text = _unmark(ctx.get("seed_text"))                               # [s3-unmark]
        angle = _unmark(ctx.get("angle"))
        news = _unmark(ctx.get("news_titles"))
        own = bool(ctx.get("own_material"))
        category = ("speakerbox" if seed_text else "internet_news" if news else
                    "own_material" if own else "angle" if angle else "free")
        topic = system3.whole_cut(angle or seed_text or news, 400)
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
        # [s3-material] what the manager/gallery/research rows would bring up
        material = self._cts_material(road, ctx, topic)
        availability = {
            "speakbox": not own and road == "banter",
            "news": bool(news),
            "gazette": bool(ctx.get("gazette")),
            "manager": bool(material.get("manager")), "gallery": bool(material.get("gallery")),
            "research": bool(material.get("research")),
        }
        # [rng-topics] the operator's topics board, for the TOPIC roll
        topic_bank = self._topic_bank(ctx)
        availability["topics"] = bool(topic_bank)
        # [s3-events] a call's own passage - what a caller's speakerbox tangent wanders into
        call_of = self._call_of(ctx)
        # [s3-segment] the scheduled segment on air while this round is planned
        segment = self.segment_now()
        availability["call_passage"] = bool(call_of.get("speakerbox"))
        return {
            "road": road, "at": time.time(), "seats": seats, "names": names, "roles": roles,
            "initial_emotions": moods, "turns": int(ctx.get("lines") or 8),
            "target_seconds": target, "turn_seconds": turn_seconds,
            "budget_roll": bool(target > 0 and turn_seconds > 0),            # [s3-window]
            "words_per_turn": words_per_turn, "deadline": float(s2.get("deadline") or 0),
            "trace_id": str(s2.get("trace_id") or ""), "system2_slot_id": str(s2.get("slot_id") or ""),
            "system2_job_id": str(s2.get("job_id") or ""),
            # [s3-segment] the occurrence on air when it was planned (the station
            # never handed one in: this was empty on every conversation)
            "schedule_occurrence_id": str(ctx.get("sid") or segment.get("id") or ""),
            "segment": segment,
            "subject": {"topic": topic, "category": category, "seeded": bool(seed_text),
                        "authority": "obligated" if (seed_text or angle or news or own or s2) else "free",
                        "sources": [x for x in [str(ctx.get("seed_file") or "")] if x],
                        "keywords": keywords, "angle": system3.whole_cut(angle, 300),
                        "exchange": _exchange_of(ctx)},
            "availability": availability,
            "material": material,                                             # [s3-material]
            "speakerbox_rates": {"full": float(dj.get("speakbox_full_swath_rate") or 0),
                                 "prepend": float(dj.get("speakbox_prepend_rate") or 0),
                                 "append": float(dj.get("speakbox_append_rate") or 0)},
            "bank": bool(ctx.get("bank")), "approach": str((ctx.get("approach") or {}).get("id") or ""),
            "seed_file": str(ctx.get("seed_file") or ""),
            # The seed passage itself, so an opened line can show which of
            # its words the opening turn read out (frontend composeLine).
            "seed_text": system3.sentence_cut(seed_text, 1500),
            "topic_bank": topic_bank,
            "gold_bank": self._gold_bank(ctx, road),                          # [s3-gold:input]
            # [s3-calls] what a call needs to be built from System 3's structure
            "call": call_of,
            "graph_caller_available": bool(ctx.get("caller_name") or ctx.get("graph_caller_available")
                                           or ctx.get("call_interjection")),
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
            # [s3-rounds] dj_banter's prompt randoms are the round's own rolls now: the
            # tempers (still behind the desk's dice_hosts switch), the shock beat, the
            # interjections forced in edgewise (the desk's own list; never on a call) and
            # the station-name mention
            "round_rolls": True,
            # [s3-rewrite] TINT per turn, REPAIR and ROOM per round
            "rewrite_rolls": True,
            "tint": self._tint_state(),
            "dice_hosts": bool(dj.get("dice_hosts")),
            "interjections": ([] if ctx.get("caller_name") else
                              [" ".join(str(x).split()) for x in (dj.get("diatribe_interjections") or [])
                               if str(x or "").strip()][:60]),
            "record": ({k: str((ctx.get("record") or {}).get(k) or "")[:180]
                        for k in ("id", "title", "artist")}
                       if road == "banter" and not ctx.get("bank") and isinstance(ctx.get("record"), dict) else {}),
            "station_name": " ".join(str(dj.get("station_name") or "").split())[:80],
            "live": not bool(ctx.get("bank")),
            # [s3-carry] what the last round left on the air, for a round that airs as written
            "carry": self._carry_for(ctx),
            # [s3-cast] the favourites and directives rolls
            **self.cast_inputs(),
            # [s3-events] what can happen in the segment (EVENT tables)
            "event_rolls": True,
            # [s3-live-event] the station events that are ON (stage per event):
            # event-tagged rows are in the wheels only while listed here
            "events": self.station_events(),
            "record_event": self.record_event_of(ctx),
            # [s3-flow] what recent rounds used weighs a quarter
            "recent_items": self.recent_used(),
            # [s3-memory] what the writer may be reminded of: the facts MEMORY rolls over
            **self.memory_inputs(road, ctx, topic),
        }

    def _voice_actor_arm(self, ctx, inputs, road, mode):
        """[voice-actor] The write side of ctx["call_interjection"]: the caller
        the operator dispatched with "call in now", for a live active round
        planned in the segment it was dispatched into. Never raises."""
        if (mode != "active" or ctx.get("bank") or ctx.get("caller_name")
                or ctx.get("whole") or road == "caller"):
            return
        try:
            pending = self.host.voice_actor_interjection_pending(
                road, str((inputs.get("segment") or {}).get("id") or ""))
        except AttributeError:
            return                          # the station has no voice actor store
        except Exception as exc:  # noqa: BLE001
            self.fail("voice actor arm", exc)
            return
        if not isinstance(pending, dict) or not str(pending.get("name") or "").strip():
            return
        ij = {k: " ".join(str(pending.get(k) or "").split())[:400]
              for k in ("id", "caller_id", "name", "persona", "goal", "topic", "voice_id", "segment_id")}
        ij["name"] = ij["name"][:80]
        ctx["call_interjection"] = dict(ij)
        inputs["call_interjection"] = dict(ij)
        inputs["graph_caller_available"] = True
        inputs.setdefault("names", {})["C"] = ij["name"]

    def _voice_actor_taken(self, handle, inputs):
        """[voice-actor] Did this plan take the armed call at a diamond? Then the
        dispatch is planned (its conversation and C turns recorded) and the
        handle carries the caller for dj_banter. Never raises."""
        ij = inputs.get("call_interjection") if isinstance(inputs, dict) else None
        if not isinstance(ij, dict) or not handle or not handle.active:
            return
        conv = handle.conv
        took = conv.get("call_interjection")
        c_turns = [t for t in conv.get("turns") or [] if t.get("speaker") == "C"]
        if not isinstance(took, dict) or took.get("id") != ij.get("id") or not c_turns:
            return
        handle.interjection = dict(ij, node=str(took.get("node") or ""))
        try:
            self.host.voice_actor_interjection_taken(
                ij["id"], handle.id, [str(t.get("turn_id") or "") for t in c_turns],
                str(took.get("node") or ""))
        except Exception as exc:  # noqa: BLE001
            self.fail("voice actor taken", exc)

    def _carry_for(self, ctx):
        """[s3-carry] The previous round's ending state, aged, for THIS round's
        inputs. Only a round whose words are written for the air it will get -
        live, or System 2's slot - takes it into the words; a banked round's
        words are frozen long before they air, so it carries the delivery
        only, at air (perf_state). None when nothing has aired within the
        window."""
        s2 = ctx.get("system2_job") if isinstance(ctx.get("system2_job"), dict) else {}
        if ctx.get("bank") and not s2:
            return None
        return self.carry_now()

    def carry_now(self):
        """The carry as it stands, with its age and decay factor, or None."""
        with self.lock:
            carry = copy.deepcopy(self.carry) if self.carry else None
        if not carry or not carry.get("at"):
            return None
        age = max(0.0, time.time() - float(carry["at"]))
        factor = max(0.0, 1.0 - age / CARRY_WINDOW)
        if factor <= 0:
            return None
        carry["age"], carry["factor"] = round(age, 1), round(factor, 3)
        return carry

    def _hand_on(self, conv, rows):
        """[s3-carry] What a round that just reached the ledger leaves for the
        next one: each host seat's ending emotion (the roulette's, not a
        guess), position and energy, the dynamics, the unresolved points, the
        line it landed on and the tempers it wore. Rounds only - a single
        line hands nothing on."""
        try:
            road = str((conv.get("identity") or {}).get("road_kind") or "")
            if ((road in system3_tables.LINE_ROADS and not conv.get("graph_structure"))
                    or len(conv.get("turns") or []) < 2):
                return None
            names = ((conv.get("inputs") or {}).get("names") or {})
            seats = {}
            for p in conv.get("participants") or []:
                emo = p.get("emotion") or {}
                if p.get("actor_id") in system3.HOST_SEATS and emo.get("category"):
                    seats[p["actor_id"]] = {"table": emo.get("table"), "category": emo["category"], "id": emo.get("id"),
                                            "label": emo.get("label"), "intensity": emo.get("intensity"),
                                            "dims": dict(emo.get("dims") or {}), "position": p.get("position"),
                                            "energy": p.get("energy")}
            landing = {}
            for row in reversed(list(rows or [])):
                who = str(row.get("who") or "")
                text = " ".join(str(row.get("text") or "").split())
                if who in ("dj", "host", "cohost", "third") and text:
                    landing = {"who": who, "name": str(names.get(_SEAT_OF.get(who, ""), "") or who), "text": system3.whole_cut(text, 400)}
                    break
            tempers = [str(t.get("id")) for t in (conv.get("tempers") or {}).values() if t.get("id")]
            dyn = conv.get("dynamics") or {}
            with self.lock:
                worn = list(self.carry.get("tempers") or []) if self.carry else []
                carry = {"at": time.time(), "from": conv["identity"]["conversation_id"], "road": road,
                         "seats": seats, "dynamics": {k: dyn.get(k) for k in ("tension", "agreement", "energy") if k in dyn},
                         "unresolved": [dict(x) for x in ((conv.get("subject") or {}).get("unresolved_points") or [])[-3:]
                                        if isinstance(x, dict)],
                         "landing": landing, "tempers": (worn + tempers)[-6:]}
                self.carry = carry
                self.metrics["carried"] += 1
            return {"stage": "handed on", "seats": sorted(seats), "landing": landing, "tempers": tempers,
                    "dynamics": carry["dynamics"], "unresolved": len(carry["unresolved"])}
        except Exception as exc:  # noqa: BLE001
            self.fail("carry", exc)
            return None

    # --- [s3-withhold] a planned round that never reaches the air says why --------
    def withhold(self, handle, why, stage="writing"):
        """The round was planned (its dice were rolled, the running order written)
        and the station will not air it: the writer was deferred, came back
        empty, the draft was refused. Recorded on the conversation as a
        WITHHELD observation with the reason, so the Rolodex never spins for
        a round the ledger cannot account for (247 of them in 8 h before this)."""
        if handle is None:
            return
        try:
            conv = handle.conv
            cid = conv["identity"]["conversation_id"]
            conv["status"] = "withheld"
            conv["withheld"] = {"why": str(why)[:300], "stage": str(stage)[:40], "at": time.time()}
            with self.lock:
                self.metrics["withheld"] += 1
                self.open.pop(cid, None)
            self.observe_later(cid, "WITHHELD", {"stage": str(stage)[:40], "why": str(why)[:300]})
            self.remember(conv)
            self.persist(conv)
            self._flow(conv, "withheld at %s: %s" % (stage, str(why)[:120]))
        except Exception as exc:  # noqa: BLE001
            self.fail("withhold", exc)

    def sweep_open(self, now=None):
        """Rounds planned more than ABANDON_AFTER ago and never bound or withheld
        are recorded as abandoned - the exits dj_banter takes without telling
        System 3 (a refused draft, a keeper that gave up). Runs in the store
        pool; returns how many it filed."""
        now = float(now or time.time())
        with self.lock:
            old = [(cid, dict(meta)) for cid, meta in self.open.items() if now - float(meta.get("at") or 0) >= ABANDON_AFTER]
        filed = 0
        for cid, meta in old:
            conv = self.recent.get(cid)
            try:
                if conv is None:
                    conv = self.store.conversation(cid, with_events=False)
                if conv is None or conv.get("status") not in ("planned", None):
                    with self.lock:
                        self.open.pop(cid, None)
                    continue
                why = ("planned %.0f min ago and never bound: the writer never returned a script, or the draft "
                       "was refused before System 3 saw it" % ((now - float(meta.get("at") or now)) / 60))
                conv["status"] = "abandoned"
                conv["withheld"] = {"why": why, "stage": "abandoned", "at": now}
                self.store.add_observation(cid, "ABANDONED", {"stage": "abandoned", "why": why, "road": meta.get("road"),
                                                              "bank": bool(meta.get("bank"))})
                self.store.save_conversation(json.loads(json.dumps(conv, default=str)))
                filed += 1
            except Exception as exc:  # noqa: BLE001
                self.fail("abandon sweep", exc)
            with self.lock:
                self.open.pop(cid, None)
                if filed:
                    self.metrics["abandoned"] = self.metrics.get("abandoned", 0)
        with self.lock:
            self.metrics["abandoned"] += filed
        return filed

    # --- [s3-memory] what the writer may be reminded of -----------------------------
    def memory_inputs(self, road, ctx, topic=""):
        """[s3-memory] What the MEMORY roll reads, handed to the plan whole so it
        replays: the station's facts for each kind of memory from its one hook
        (app.py system3_memory_facts - the clock and the segment on air, the
        last segment and how it went, the calls against the quota, the
        manager's last word; read from what the station already keeps, never a
        model call), and the last topic from System 3's own record of the last
        round that reached the air. A host without the hook hands in nothing:
        every kind is then recorded as holding nothing."""
        try:
            got = self.host.system3_memory_facts(road, ctx)
        except AttributeError:
            got = {}
        except Exception as exc:  # noqa: BLE001
            self.fail("memory facts", exc)
            got = {}
        got = got if isinstance(got, dict) else {}
        facts = {str(k): self._memory_clean(v) for k, v in got.items()
                 if isinstance(v, dict) and str(k) not in ("topic", "last_topic")}
        last = self._last_topic_fact(got.get("topic"))
        if last:
            facts["last_topic"] = last
        return {"memory_rolls": True, "memory": facts}

    @staticmethod
    def _memory_clean(val, depth=0):
        """A fact as the plan keeps it: plain JSON, short words, small lists."""
        if isinstance(val, dict):
            return ({str(k)[:40]: System3Runtime._memory_clean(v, depth + 1) for k, v in list(val.items())[:32]}
                    if depth < 3 else {})
        if isinstance(val, (list, tuple)):
            return [System3Runtime._memory_clean(v, depth + 1) for v in list(val)[:40]] if depth < 3 else []
        if val is None or isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return val if val == val and val not in (float("inf"), float("-inf")) else 0
        return " ".join(str(val).split())[:600]

    @staticmethod
    def _topic_of(conv):
        """What a round was about, in the words that best say it: a topic the
        roulette raised in it (the later one), the operator's exchange, the
        round's own subject when it is a subject and not a brief, else its
        most frequent words."""
        subj = conv.get("subject") or {}
        for t in reversed(conv.get("turns") or []):
            for key in ("topic_material", "bank_topic"):
                got = t.get(key)
                if isinstance(got, dict) and str(got.get("text") or "").strip():
                    return " ".join(str(got["text"]).split())
        plan = conv.get("topic_plan") if isinstance(conv.get("topic_plan"), dict) else {}
        if str(plan.get("text") or "").strip():
            return " ".join(str(plan["text"]).split())
        ex = subj.get("exchange") if isinstance(subj.get("exchange"), dict) else {}
        if str(ex.get("opener") or "").strip():
            return " ".join(str(ex["opener"]).split())
        topic = " ".join(str(subj.get("topic") or "").split())
        if topic and len(topic) <= 300 and not re.search(r"[A-Z]{3,}[\s\-:]+[A-Z]{3,}", topic):
            return topic
        words = [str(w) for w in (subj.get("keywords") or []) if str(w).strip()][:5]
        return ("talk of " + ", ".join(words)) if words else ""

    def _last_topic_fact(self, station=None):
        """[s3-memory] The last subject that went out: the round the carry names
        (the one that reached the script ledger last) - the topic the roulette
        raised in it, else its own subject - and the line it landed on. When
        System 3 holds no such round (a restart), the last subject the station
        heard (its heard-subjects ring, handed in by the station)."""
        with self.lock:
            carry = copy.deepcopy(self.carry) if self.carry else None
        conv = self.recent.get(str(carry.get("from") or "")) if carry else None
        if isinstance(conv, dict):
            topic = self._topic_of(conv)
            if topic:
                landing = carry.get("landing") if isinstance(carry.get("landing"), dict) else {}
                return {"topic": topic[:400], "keywords": sorted(system3._memory_keywords(topic))[:12],
                        "at": float(carry.get("at") or 0), "road": str(carry.get("road") or ""),
                        "from": str(carry.get("from") or ""),
                        "landing": system3.sentence_cut(landing.get("text"), 400),
                        "landing_who": str(landing.get("name") or landing.get("who") or "")[:60],
                        "source": "System 3's record of the last round on air"}
        st = station if isinstance(station, dict) else {}
        text = " ".join(str(st.get("text") or "").split())
        if text:
            return {"topic": text[:400], "keywords": sorted(system3._memory_keywords(text))[:12],
                    "at": float(st.get("at") or 0), "road": "", "from": "", "landing": "", "landing_who": "",
                    "source": "the last subject the station heard"}
        return None

    def memory_block(self):
        """[s3-memory] The words of the memory block for the prompt being written
        on this task: exactly the items its round's MEMORY roll drew ("" when it
        drew none), or None when no MEMORY roll stands behind this prompt -
        System 3 off or not directing the road, no active round planned on this
        task in the last fifteen minutes, the round withheld, no MEMORY table -
        and the station then sends its show memory as it always did."""
        if not self.ready:
            return None
        try:
            handle = _S3_WRITE.get()
            conv = handle.conv if handle is not None and getattr(handle, "active", False) else None
            if not isinstance(conv, dict) or not isinstance(conv.get("memory"), dict):
                return None
            if time.time() - float(conv.get("created") or 0) > 900 or conv.get("status") in ("withheld", "abandoned"):
                return None
            if system3.road_mode(self.settings, str((conv.get("identity") or {}).get("road_kind") or "")) != "active":
                return None
            text = system3.memory_text(conv)
            with self.lock:
                self.metrics["memory_blocks"] = self.metrics.get("memory_blocks", 0) + 1
                if text:
                    self.metrics["memory_items"] = (self.metrics.get("memory_items", 0)
                                                    + len(conv["memory"].get("items") or []))
            return text
        except Exception as exc:  # noqa: BLE001
            self.fail("memory block", exc)
            return None

    def pinned_source(self, road="banter"):
        """[s3-source] The speakbox document the operator pinned on this road's
        initiator node (its first step's `source`, else the structure's own),
        or "" - nothing pinned, System 3 not active on the road, not loaded."""
        try:
            if not self.ready or system3.road_mode(self.settings, road) != "active":
                return ""
            config = self.config if isinstance(self.config, dict) else {}
            st = (config.get("structure") or {}) if road == "banter" else (system3.road_structure(config, road) or {})
            first = ((st.get("steps") or st.get("legs") or [{}])[0]) or {}
            return " ".join(str(first.get("source") or st.get("source") or "").split())[:200]
        except Exception as exc:  # noqa: BLE001
            self.fail("pinned source", exc)
            return ""

    def _cts_material(self, road, ctx, topic):
        """[s3-material] The host's material for the rows that name it: each a
        {"text", "label", "ref"}. Nothing (and those rows stay ineligible) on a
        host without the hook, or when it fails."""
        try:
            got = self.host.system3_cts_material(road, ctx, topic)
        except AttributeError:
            return {}
        except Exception as exc:  # noqa: BLE001
            self.fail("cts material", exc)
            return {}
        out = {}
        for kind, val in (got or {}).items():
            if isinstance(val, dict) and str(val.get("text") or "").strip():
                out[str(kind)] = {"text": system3.sentence_cut(val["text"], 1200), "label": system3.label_cut(val.get("label") or kind),
                                  "ref": str(val.get("ref") or "")[:160]}
        return out

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
        out = {"name": name, "first": name.split()[0], "other": str(dj.get("cohost_name") or ""),
               "topic": system3.whole_cut(meta.get("topic"), 400),
               # [s3-cut] at a sentence end, never where a count fell
               "speakerbox": system3.sentence_cut(str(meta.get("speakerbox_text") or ctx.get("seed_text") or ""), 600),
               "story": bool(meta.get("story")), "scenario_clause": clause[:1500],
               "painting": self._painting_of(ctx)}                              # [s3-callend] the caller's wheel
        # [s3-callarc] the station's own business, for the detour and the result wheel
        fn = getattr(self.host, "system3_call_background", None)
        if callable(fn):
            try:
                bg = fn() or {}
                for k in ("memo", "memo_id", "news", "unsold", "manager"):
                    if bg.get(k):
                        out[k] = bg[k]
            except Exception as exc:  # noqa: BLE001
                self.log("System 3 could not read the station's background for a call", extra=str(exc)[:300])
        return out

    # --- [s3-callend] how a call ends: the painting in play, the passage, the mark, the effect ---
    CALLEND_MARK = "caller:callend"    # in defaults_added: the end legs were put on the stored structure

    def _painting_of(self, ctx):
        """[s3-callend] The painting the last segment sold, for the caller's wheel: the
        station's own record of what it put on offer (the sales floor, a painting spot,
        the gallery press), no older than the painting wheel's `within` - or {}."""
        fn = getattr(self.host, "system3_painting_on_offer", None)
        if not callable(fn):
            return {}
        within = system3.CALLEND_WITHIN
        for t in (self.config or {}).get("tables") or []:
            if not isinstance(t, dict) or t.get("family") != "RESOLVE" or t.get("enabled") is False:
                continue
            cat = next((c for c in t.get("categories") or []
                        if isinstance(c, dict) and "painting" in (c.get("requires") or [])), None)
            if cat is not None:
                try:
                    within = float(cat.get("within") or within)
                except (TypeError, ValueError):
                    pass
                break
        try:
            got = fn(within)
        except Exception as exc:  # noqa: BLE001
            self.log("System 3 could not read the painting on offer for a call", extra=str(exc)[:300])
            return {}
        return dict(got) if isinstance(got, dict) and got.get("image") else {}

    async def _callend_after_plan(self, handle, ctx):
        """[s3-callend] After a call is planned: fetch the passage a speakerbox rejection is
        said in (only that request - the station's own rotation, bounded), re-render the
        sheet with it, and put the plan's end on the call's meta and, when the call is on
        the line now, on the live call's record."""
        conv = handle.conv
        ce = conv.get("callend") if isinstance(conv.get("callend"), dict) else {}
        if not handle.active or not ce.get("planned"):
            return
        mine = [r for r in conv.get("material_requests") or [] if r.get("callend") and r.get("resolved") is None]
        if mine:
            every = conv["material_requests"]
            try:
                conv["material_requests"] = mine
                await self._resolve_material(handle, ctx)
            finally:
                conv["material_requests"] = every
            handle.sheet = system3.render_call_sheet(conv)
        mark = system3.callend_mark(conv)
        meta = ctx.get("call_meta") if isinstance(ctx.get("call_meta"), dict) else None
        if not mark:
            return
        if meta is not None:
            meta["callend"] = mark
        if not ctx.get("bank"):
            fn = getattr(self.host, "call_line_context", None)
            if callable(fn):
                try:
                    fn(callend=mark, **({"ended": meta["ended"]} if meta and meta.get("ended") else {}))
                except Exception:  # noqa: BLE001
                    pass
        self.log("System 3 rolled how this call ends: " + str(mark.get("says") or "")[:360])

    def _callend_aired(self, conv):
        """[s3-callend] A call whose end was rolled reached the script ledger: what the
        caller's wheel landed on acts on the gallery where the station keeps state (sold,
        awarded or burnt: off the pile by the desk; unsold: on it, still for sale) - once
        per conversation, and never for an outcome the line went dead before."""
        try:
            ce = conv.get("callend") if isinstance(conv.get("callend"), dict) else {}
            res = ce.get("resolve") if isinstance(ce.get("resolve"), dict) else {}
            painting = res.get("painting") if isinstance(res.get("painting"), dict) else {}
            if not res.get("effect") or not painting.get("image") or res.get("cut"):
                return
            cid = str((conv.get("identity") or {}).get("conversation_id") or "")
            done = self.__dict__.setdefault("_callend_done", collections.OrderedDict())
            with self.lock:
                if not cid or cid in done:
                    return
                done[cid] = time.time()
                while len(done) > 400:
                    done.popitem(last=False)
            fn = getattr(self.host, "system3_gallery_outcome", None)
            got = (fn(str(res["effect"]), dict(painting, outcome=str(res.get("label") or "")), cid) if callable(fn)
                   else {"applied": False, "why": "the station has no gallery hook"})
            self.store.add_observation(cid, "CALLEND", {"stage": "air", "effect": res["effect"],
                                                        "outcome": res.get("id"), "painting": painting.get("image"),
                                                        "done": got if isinstance(got, dict) else {"result": str(got)}})
        except Exception as exc:  # noqa: BLE001
            self.log("System 3 could not act on a call's rolled end at air", extra=str(exc)[:300])

    def add_missing_call_legs(self):
        """[s3-callend] Once: the call's end legs (resolution, reaction, response chain,
        rebuttal, wrap call) onto a stored caller structure that predates them. One that
        still ends on the old default's two legs (lands, sign_off) has them replaced by
        the five; one the operator reshaped is left as it is (the legs are in the
        Segments tab's defaults) and the log says so. Remembered in `defaults_added`
        (CALLEND_MARK), so legs the operator later removes stay removed. Saved as one
        version with a note. Returns the note, or ""."""
        config = self.config if isinstance(self.config, dict) else {}
        seen = {str(x) for x in (config.get("defaults_added") or [])}
        if self.CALLEND_MARK in seen:
            return ""
        st = (config.get("structures") or {}).get("caller")
        if not isinstance(st, dict) or not isinstance(st.get("legs"), list) or not st["legs"]:
            return ""                 # no stored structure: the default, which ends on the legs, applies
        legs = [leg for leg in st["legs"] if isinstance(leg, dict)]
        if any(leg.get("end") for leg in legs):
            return ""
        if [str(leg.get("id")) for leg in legs[-2:]] != ["lands", "sign_off"]:
            self.log("System 3: the caller structure was reshaped on the desk, so the call's end legs were not "
                     "added - add them from the Segments tab (resolution, reaction, response, rebuttal, wrap call)")
            return ""
        new = copy.deepcopy(config)
        nst = new["structures"]["caller"]
        nst["legs"] = copy.deepcopy(legs[:-2]) + copy.deepcopy(system3_tables.CALLEND_LEGS)
        nst["version"] = int(nst.get("version") or 1) + 1
        new["defaults_added"] = sorted(seen | {self.CALLEND_MARK})
        note = ("the call's end legs (resolution, reaction, response chain, rebuttal, wrap call) replace "
                "lands / sign_off on the caller structure (once)")
        try:
            self.store.save_config(new, note)
        except Exception as exc:  # noqa: BLE001
            self.fail("call end legs", exc)
            return ""
        self.config = new
        return note

    def _gold_bank(self, ctx, road):
        """[s3-gold:bank] The kept lines a host may roll as a reply this round -
        the station's (system3_gold_bank): minted from System 3 turns, none heard
        inside the day. Empty (nothing is rolled) on the operator's own exchange,
        a road the station keeps gold off, or a host without the module."""
        if system3_gold is None or _exchange_of(ctx).get("opener"):
            return []
        fn = getattr(self.host, "system3_gold_bank", None)
        try:
            rows = fn(road, ctx) if callable(fn) else []
        except Exception as exc:  # noqa: BLE001
            self.fail("gold bank", exc)
            return []
        return [dict(r) for r in rows or [] if isinstance(r, dict)][:system3_gold.BANK_MOST]

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
                        "reply": system3.sentence_cut(r.get("reply"), 400)})
        out.sort(key=lambda r: r["used"])
        return out[:60]

    def _tint_state(self):
        """[s3-rewrite] Is the station's crystal tint pass on (dialogue_tint_wanted),
        and at what coverage - the TINT roll only rolls when it is."""
        wanted, coverage, why = False, None, ""
        try:
            fn = getattr(self.host, "dialogue_tint_wanted", None)
            wanted = bool(fn()) if callable(fn) else False
        except Exception as exc:  # noqa: BLE001
            why = "%s: %s" % (type(exc).__name__, str(exc)[:80])
        try:
            fn = getattr(self.host, "crystal_coverage_target", None)
            coverage = int(fn()) if callable(fn) else None
        except Exception:  # noqa: BLE001
            coverage = None
        return {"wanted": wanted, "coverage": coverage, "why": why}

    # --- the rewrite rolls, for the station ------------------------------------
    def tint_turns(self, handle, script):
        """[s3-rewrite] The script indices whose turn rolled a rhyme - the
        lines the crystal tint may touch. None when the round is not System
        3's or nothing was rolled (the station keeps its own selection)."""
        if not handle or not handle.active:
            return None
        conv = handle.conv
        if not any(t.get("tint") for t in conv.get("turns") or []):
            return None
        try:
            turns = self.host.banter_turns(str(script or ""))
            mapping = system3.align(conv, turns)
        except Exception as exc:  # noqa: BLE001
            self.fail("tint alignment", exc)
            return None
        out = set()
        for t in conv["turns"]:
            if (t.get("tint") or {}).get("rhyme") and mapping.get(t["index"]) is not None:
                out.add(int(mapping[t["index"]]))
        return out

    def repair_roll(self, handle):
        """[s3-rewrite] True: a round that misses its target goes back; False:
        it stands as written; None: nothing was rolled (the old rules)."""
        if not handle or not handle.active:
            return None
        got = handle.conv.get("repair_roll")
        return bool(got.get("repair")) if isinstance(got, dict) else None

    @staticmethod
    def room_allowed(entry):
        """[s3-rewrite] May the Writers' Room touch this stored round? False only
        when System 3 bound a ROOM roll that said no."""
        s3 = entry.get("system3") if isinstance(entry, dict) else None
        return not (isinstance(s3, dict) and s3.get("room") is False)

    @staticmethod
    def tint_turns_entry(entry):
        """[s3-rewrite] The tint selection bound onto a stored entry, for the
        passes that run after binding (larder, retint, recovery)."""
        s3 = entry.get("system3") if isinstance(entry, dict) else None
        got = s3.get("tint_turns") if isinstance(s3, dict) else None
        return set(int(i) for i in got) if isinstance(got, list) else None

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
            self._voice_actor_arm(ctx, inputs, road, mode)       # [voice-actor] "call in now"
            config = self.config
            started = time.perf_counter()
            conv = system3.new_conversation(inputs, config, self.settings)
            conv["mode"] = mode
            self._absorb_rolls(conv)                                            # [s3-dice-door]
            conv["identity"]["segment"] = dict((conv.get("inputs") or {}).get("segment") or {})   # [s3-segment]
            handle = Handle(self, conv, config, mode == "active")
            handle.bank = bool(ctx.get("bank"))
            call = inputs.get("call") or {}
            # [s3-story] a story call-back the station hands its own protocol keeps
            # it (annotated); one handed none - an EMPTY sheet, which is what the
            # station hands a sequel today - is built from System 3's call legs
            _story_protocol = bool(call.get("story")) and bool(
                re.search(r"(?m)^\s*\d+\s+[ABCDE]\s+[-–—]", ctx.get("call_sheet") or ""))
            _st = system3.road_structure(config, road)
            if road not in ("banter", "caller"):
                # [nodeplan] the airing elects its structure first (base or a
                # variant, one recorded VARIANT draw - the same draw plan_legs
                # made, moved before the planner choice) so a variant's own
                # graph, a segment's override, runs for the round that
                # elected it. With no variants nothing is drawn.
                _st, _stev = system3._structure_roll(conv, config, road)
            _graph = (_st or {}).get("graph") or {}
            if (road != "banter" and _graph.get("enabled") and _graph.get("nodes")
                    and not any(node.get("type") == "protocol" for node in _graph["nodes"])):
                system3.plan_graph(conv, config, _graph, inputs=inputs, road=road)
            elif road == "caller" and call.get("first") and not _story_protocol:
                # [s3-calls] the call is built by System 3's own call structure
                system3.plan_call(conv, config, inputs)
                handle.sheet = system3.render_call_sheet(conv) if handle.active else ""
                # [s3-events] the roulette ended this call early (the line lost, the
                # caller pulled away): the station's call contract waives its
                # sign-off and landing (call_flow_report ended=). dj_banter hands
                # System 3 its own call_meta dict and the entry copies it, so every
                # later regrade sees the mark.
                if handle.active and conv.get("event_end") is not None and isinstance(ctx.get("call_meta"), dict):
                    end = next((x for x in conv.get("event_plans") or [] if x.get("ends")), {})
                    ctx["call_meta"]["ended"] = ("%s: %s" % (end.get("kind_label") or "ended",
                                                             end.get("label") or ""))[:200]
                await self._callend_after_plan(handle, ctx)                        # [s3-callend] how it ends
            elif road == "caller":
                rows = [(int(n), seat, work) for n, seat, work in
                        re.findall(r"(?m)^\s*(\d+)\s+([ABCDE])\s+[-–—]\s*(.+?)\s*$", ctx.get("call_sheet") or "")]
                system3.plan_protocol(conv, config, rows)
                handle.sheet = system3.annotate_protocol(conv, ctx.get("call_sheet") or "") if handle.active else ""
            elif road != "banter" and (_st or {}).get("legs"):
                # [s3-roads] a segment built from its own legs (recap, ad,
                # news, manager, memo, gallery, mixtape, open_show, fan_mail,
                # guest - and any road the operator gives a structure)
                system3.plan_legs(conv, config, inputs, road, structure=_st)
            else:
                system3.plan_more(conv, config)
            self._voice_actor_taken(handle, inputs)             # [voice-actor] the diamond took it
            handle.plan_ms = round((time.perf_counter() - started) * 1000, 2)
            if conv.get("length_roll"):
                handle.turns = int(conv["length_roll"].get("turns") or 0)     # [s3-glass]
            elif handle.active and conv.get("turns"):
                # [s3-rounds] the sheet's row count IS the round's size: a legs road
                # whose parity mended the count by one, a round two interjection
                # turns were planned into - dj_banter's `lines` follows the rows
                handle.turns = len(conv["turns"])
            if handle.active and conv.get("carry"):
                with self.lock:
                    self.metrics["carry_in"] += 1
            if handle.active:
                self._cast_note(conv)                                          # [s3-cast]
                self._note_used(conv)                                          # [s3-flow]
            if handle.active:
                with self.lock:
                    self.open[conv["identity"]["conversation_id"]] = {"at": time.time(), "road": road,
                                                                     "bank": bool(ctx.get("bank"))}
            self._ema("plan_ms_ema", handle.plan_ms)
            with self.lock:
                self.metrics["planned"] += 1
                self.metrics[mode] += 1
                self.metrics["plan_ms_max"] = max(self.metrics["plan_ms_max"], handle.plan_ms)
            if handle.active and road != "caller":
                await self._resolve_material(handle, ctx)
                self._split_passages(handle)                                    # [s3-split] a long monologue shared out
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
            _S3_WRITE.set(handle)          # [s3-blocks] the writer call that follows on this task writes for it
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
            if not ctx.get("bank"):                              # [s3-live-event]
                cands.extend(self._event_line_candidates(road, dj))
            context = " ".join(str(ctx.get("context") or ctx.get("text") or "").split())
            segment = self.segment_now()                                   # [s3-segment]
            inputs = {
                "road": road, "at": time.time(), "seats": [seat], "names": {seat: name}, "roles": {seat: who},
                "turns": 1, "target_seconds": 0.0, "words_per_turn": 40.0,
                "schedule_occurrence_id": str(ctx.get("sid") or segment.get("id") or ""),   # [s3-segment]
                "segment": segment,
                "subject": {"topic": system3.whole_cut(context, 400), "category": "own_material", "seeded": False,
                            "authority": "obligated", "sources": [], "keywords": [], "angle": ""},
                "availability": {}, "speakerbox_rates": {}, "bank": bool(ctx.get("bank")),
                "candidates": cands, "candidates_from": str(ctx.get("candidates_from") or ""),
                "line_text": system3.sentence_cut(ctx.get("text"), 600),
                "sfxguy": {"voice": False},
                **self.cast_inputs(),                                        # [s3-cast]
                **self.memory_inputs(road, ctx, context),                    # [s3-memory]
            }
            config = self.config
            _graph = ((system3.road_structure(config, road) or {}).get("graph") or {})   # [nodeplan]
            _chapter = bool(_graph.get("enabled") and _graph.get("nodes")
                            and not any(n.get("type") == "protocol" for n in _graph["nodes"]))
            if _chapter and (who == "board" or ctx.get("one_line")):             # [outl-oneline]
                # a board clip is a sound and a bumper or a holding line is a one-liner:
                # no exchange is planned on it (the one-turn interject "rounds" were these)
                _chapter = False
                inputs["one_line"] = ("a board clip is a sound, not a line" if who == "board"
                                      else str(ctx.get("one_line")))
            if _chapter:
                # [nodeplan] no one-line segments: the studio answers the line,
                # the chapter graph plans the exchange (the operator turned it on)
                inputs["line_seat"] = seat
                for s, n in (("A", dj.get("host_name") or "Host"), ("B", dj.get("cohost_name") or "Co-host"),
                             ("D", dj.get("third_name") or "Third seat")):
                    if s not in inputs["seats"]:
                        inputs["seats"].append(s)
                        inputs["names"][s] = str(n)
                        inputs["roles"][s] = {"A": "dj", "B": "cohost", "D": "third"}[s]
                inputs["turns"] = max(4, min(12, int(ctx.get("lines") or 0) or 7))
            conv = system3.new_conversation(inputs, config, self.settings)
            conv["mode"] = mode
            self._absorb_rolls(conv)                                            # [s3-dice-door]
            conv["identity"]["segment"] = dict((conv.get("inputs") or {}).get("segment") or {})   # [s3-segment]
            if _chapter:
                _mini = None
                if road == "interject":                                     # [outl-mini] reply, rebuttal, exit roll
                    try:
                        import outlandish as _outl
                        _mini = _outl.miniround_until(conv, config)
                    except Exception as _mexc:  # noqa: BLE001
                        self.fail("mini-round", _mexc)
                system3.plan_graph(conv, config, _graph, inputs=inputs, road=road, until=_mini)   # [nodeplan]
            else:
                system3.plan_line(conv, config, inputs)
            self._mark_split_nodes(conv, config, road)                          # [s3-split]
            handle = LineHandle(self, conv, mode == "active")
            if handle.active:
                self._cast_note(conv)                                          # [s3-cast]
            handle.plan_ms = round((time.perf_counter() - started) * 1000, 2)
            choice = conv.get("line_choice") or {}
            if cands and choice.get("id") is not None:
                for i, c in enumerate(cands):
                    if c["id"] == str(choice["id"]):
                        handle.choice, handle.line = i, c["text"]
                        break
            first = conv["turns"][0] if conv["turns"] else {}
            handle.sheet = system3.render_legs_sheet(conv) if handle.active else ""
            if system3_mgrtopics is not None and conv.get("mgr_topic"):     # [s3-mgrtopics]
                system3_mgrtopics.attach(conv)                            # his turn wears the draws
                if handle.active:                                          # the replies answer the topic
                    handle.sheet += system3_mgrtopics.sheet_line(conv)
            handle.stamp = {"conversation_id": conv["identity"]["conversation_id"], "mode": mode,
                            "turn_id": str(first.get("turn_id") or ""), "road": road,
                            "seed": conv["seed"], "config_hash": conv["config_hash"]}
            perf = first.get("performance") or {}
            dims = perf.get("dims") if isinstance(perf.get("dims"), dict) else None
            handle.perf = ({d: float(dims.get(d) or 0) for d in system3.EMOTION_DIMS}
                           if dims and handle.active else None)
            # [s3-es-voice] and how the feeling sounds
            handle.voice = (dict(perf["voice"], row=system3.es_row(first) or {})   # [es-roads] and which row
                            if isinstance(perf.get("voice"), dict) and handle.active else None)
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
            _S3_WRITE.set(handle)          # [s3-blocks]
            return handle
        except Exception as exc:  # noqa: BLE001
            self.fail("line planning", exc)
            return None

    def link_spoken(self, line_id, stamp, who="", text=""):
        """[s3-line-link] A line spoken with a System 3 stamp is linked in the
        lines table the moment it is spoken - not only when the script ledger
        commits it seconds later, and not never, as for a line the deck
        withdrew before it aired. The ledger's own row, when it comes, replaces
        this one with its block and order; this never overwrites it."""
        try:
            if not line_id or not isinstance(stamp, dict) or not stamp.get("conversation_id"):
                return
            row = {"line_id": str(line_id), "conversation_id": str(stamp["conversation_id"]),
                   "turn_id": str(stamp.get("turn_id") or "") or None, "block": None, "ord": None,
                   "sid": "", "who": str(who or ""), "text": str(text or "")[:2000], "at": time.time()}
            with self.lock:
                if self.pending >= WRITE_BACKLOG:
                    self.metrics["writes_dropped"] += 1
                    return
                self.pending += 1
                self.metrics["lines_linked_live"] = self.metrics.get("lines_linked_live", 0) + 1

            def job():
                try:
                    if not self.store.line(row["line_id"]):
                        self.store.add_lines([row])
                finally:
                    with self.lock:
                        self.pending -= 1
            _STORE_POOL.submit(job)
        except Exception as exc:  # noqa: BLE001
            self.fail("line link", exc)

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
                # The line is the graph's initiator. Binding it to the last
                # turn silently made a seven-turn chapter look complete while
                # leaving its six replies unwritten.
                t = next((x for x in conv["turns"] if not x.get("split_of")), conv["turns"][0])
                t["text"] = words
                t["script_index"] = 0 if words else None
                t["status"] = "generated" if words else "dropped"
            conv["actual"] = [{"speaker": (conv["turns"][0]["speaker"] if conv["turns"] else "A"),
                               "text": words}]                                  # [s3-split] whole
            conv["identity"]["script_digest"] = hashlib.sha256(words.encode("utf-8")).hexdigest()[:16]
            conv["bindings"] = [{"turn_id": conv["turns"][0]["turn_id"], "script_index": 0}] if conv["turns"] else []
            conv["status"] = ("opening_ready" if handle.active and len(conv["turns"]) > 1
                              else "bound" if handle.active else "shadowed") if words else "dropped"
            fav = (conv["turns"][0].get("favorite") or {}) if conv["turns"] else {}      # [s3-cast]
            if words and fav.get("text"):
                copied = bool(system3.favorite_copied(fav["text"], words))
                conv["validation"] = {"method": "deterministic/lexical", "favorite_copies": int(copied),
                                      "verdict": "non_compliant" if copied else "compliant"}
                self.observe_later(conv["identity"]["conversation_id"], "FAV", {
                    "stage": "copied" if copied else "in its spirit", "favorite": fav.get("id"),
                    "run": system3.favorite_run(fav["text"], words)})
            with self.lock:
                self.metrics["lines_bound"] += 1
            self.remember(conv)
            self.persist(conv)
        except Exception as exc:  # noqa: BLE001
            self.fail("line bind", exc)

    def line_chapter(self, stamp, written=None):
        """Return a line road's graph plan, or bind a complete spoken exchange.

        A plan is not a broadcast script. Only a written exchange with its
        planned seats, at least three turns and two voices can be committed.
        """
        if not isinstance(stamp, dict) or not stamp.get("conversation_id"):
            return None
        conv = self.recent.get(str(stamp["conversation_id"]))
        if not conv or conv.get("mode") != "active":
            return None
        planned = conv.get("turns") or []
        road = str((conv.get("identity") or {}).get("road_kind") or "")
        if (road not in system3_tables.LINE_ROADS or not conv.get("graph_structure")
                or len(planned) < 3):
            # [s3-chain] known, and not a chapter: a round's own turn, a line road
            # whose graph the operator switched off, or a plan under three turns
            return ({"chapter": False, "road": road, "turns": len(planned)}
                    if written is None else None)
        if written is None:
            return {"chapter": True, "road": road,                                   # [s3-chain]
                    "turn_ids": [t["turn_id"] for t in planned],
                    "seconds": [float(t.get("planned_seconds") or 0) for t in planned],
                    "estimated_seconds": float((conv.get("graph_profile") or {}).get("estimated_seconds") or 0),
                    "sheet": str((conv.get("plan") or {}).get("sheet") or ""),
                    "turns": len(planned), "seats": [t["speaker"] for t in planned],
                    "roles": dict((conv.get("inputs") or {}).get("roles") or {}),
                    "names": dict((conv.get("inputs") or {}).get("names") or {})}
        rows = [(str(m), str(s or "").strip()) for m, s in written]
        if (len(rows) != len(planned) or len({m for m, _s in rows}) < 2
                or any(not s or m != t["speaker"] for (m, s), t in zip(rows, planned))):
            return None
        mapping, verdict = system3.bind(conv, rows)
        if len(mapping) != len(planned) or verdict.get("verdict") == "non_compliant":
            return None
        conv["actual"] = [{"speaker": m, "text": s} for m, s in rows]
        conv["identity"]["script_digest"] = hashlib.sha256(
            "\n".join("%s: %s" % row for row in rows).encode("utf-8")).hexdigest()[:16]
        conv["status"] = "chapter_ready"
        self.remember(conv)
        self.persist(conv)
        return [{"who": (conv.get("inputs") or {}).get("roles", {}).get(t["speaker"], "dj"),
                 "name": (conv.get("inputs") or {}).get("names", {}).get(t["speaker"], ""),
                 "text": rows[i][1],
                 # [s3-chain] each turn's own stamp: its node and its place
                 "stamp": dict(stamp, turn_id=t["turn_id"], chapter_turn=i, chapter_of=len(planned))}
                for i, t in enumerate(planned)]

    def line_chapter_state(self, stamp, state, why="", extra=None):
        """[s3-chain] Where a line road's exchange stands on the prepared shelf
        (waiting, prepared, aired, partial, expired), recorded on the
        conversation: a planned chapter that has not aired says why."""
        try:
            conv = self.recent.get(str((stamp or {}).get("conversation_id") or ""))
            if not conv:
                return
            conv["chapter_state"] = dict(extra or {}, state=str(state), why=str(why or "")[:300],
                                         at=time.time())
            if state in ("aired", "partial", "expired", "stale"):
                conv["status"] = "chapter_" + str(state)
            self.remember(conv)
            self.persist(conv)
            self._flow(conv, "chapter %s%s" % (state, (": " + str(why)[:160]) if why else ""))
        except Exception as exc:  # noqa: BLE001
            self.fail("chapter state", exc)

    # --- [s3-split] THE SPLIT NODE AT THE STATION'S DOORS ---------------------------
    @staticmethod
    def _studio(dj, away=""):
        """[s3-split] Who is in the studio now, as the split's roulette sees
        them: the host, the co-host, the third seat when someone is seated in
        it, and the SFX guy - a full booth member - when his voice is set;
        less whoever has stepped out."""
        dj = dj if isinstance(dj, dict) else {}
        people = [{"who": "dj", "seat": "A", "name": str(dj.get("host_name") or "Dill"), "voice": ""},
                  {"who": "cohost", "seat": "B", "name": str(dj.get("cohost_name") or "Skip"), "voice": ""}]
        if str(dj.get("third_name") or "").strip():
            people.append({"who": "third", "seat": "D", "name": str(dj.get("third_name")), "voice": ""})
        if str(dj.get("drop_voice") or "").strip():
            people.append({"who": "drop", "seat": "S", "name": str(dj.get("sfxguy_name") or "Sam"),
                           "voice": str(dj.get("drop_voice"))})
        return [p for p in people if p["who"] != str(away or "")]

    def _pace_book(self):
        """[s3-split] Each voice's measured pace: {who: {cps, n}} (memory only)."""
        book = self.__dict__.get("paces")
        if book is None:
            book = self.__dict__.setdefault("paces", {})
        return book

    def note_pace(self, who, chars, seconds):
        """[s3-split] A rendered line's length and its words: the voice's pace,
        a running average the split's rule reads once it has eight lines. A
        take far from speech (under 8 or over 30 characters a second) teaches
        nothing and is not counted."""
        try:
            chars, seconds = int(chars or 0), float(seconds or 0)
            if chars < 40 or seconds < 2.0:
                return
            cps = chars / seconds
            if not 8.0 <= cps <= 30.0:
                return
            with self.lock:
                got = self._pace_book().setdefault(str(who or ""), {"cps": round(cps, 3), "n": 0})
                if got["n"]:
                    got["cps"] = round(0.9 * float(got["cps"]) + 0.1 * cps, 3)
                got["n"] = int(got["n"]) + 1
        except Exception:  # noqa: BLE001
            pass

    def _paces_from(self, rows):
        """[s3-split] The ledger's own rows, where a round's lines carry their
        rendered seconds, measure each voice's pace."""
        for row in rows or []:
            try:
                if isinstance(row, dict) and row.get("who") != "board" and float(row.get("seconds") or 0) > 0:
                    self.note_pace(row.get("who"), len(" ".join(str(row.get("text") or "").split())),
                                   row.get("seconds"))
            except (TypeError, ValueError):
                continue

    def _pace_for(self, who):
        """[s3-split] (characters a second, why) for a voice."""
        cfg = system3.split_config(self.config)
        if who in cfg["paces"]:
            return float(cfg["paces"][who]), "the split section's pace for %s" % who
        with self.lock:
            got = dict(self._pace_book().get(str(who or "")) or {})
        if int(got.get("n") or 0) >= 8:
            return round(float(got["cps"]), 2), "measured over %s's last %d lines" % (who, int(got["n"]))
        return float(cfg["pace"]), "the default pace (no measured pace for %s yet)" % (who or "this voice")

    def _mark_split_nodes(self, conv, config, road):
        """[s3-split] Each planned turn learns whether its node splits, from
        the structure it was planned from: a line road's leg, the banter
        cycle's step."""
        try:
            if road in system3_tables.LINE_ROADS:
                nodes = {str(x.get("id")): x for x in (system3.road_structure(config, road) or {}).get("legs") or []
                         if isinstance(x, dict)}
                key = "leg"
            elif road == "banter":
                nodes = {str(x.get("id")): x for x in (config.get("structure") or {}).get("steps") or []
                         if isinstance(x, dict)}
                key = "step"
            else:
                return
            graph_nodes = {}
            if conv.get("graph_structure"):
                # [nodeplan] a chapter-planned round: its turns carry the graph's
                # node ids, so the split switch is read off the graph's nodes
                graph = (((config.get("structure") or {}).get("graph") if road == "banter"
                          else (system3.road_structure(config, road) or {}).get("graph")) or {})
                graph_nodes = {str(n.get("id")): n for n in graph.get("nodes") or []
                               if isinstance(n, dict)}
            for t in conv.get("turns") or []:
                node = graph_nodes.get(str(t.get("graph_node") or "")) if graph_nodes else None
                got = system3.split_node(node if node is not None else nodes.get(str(t.get(key) or "")))
                if got:
                    t["split_node"] = got
        except Exception as exc:  # noqa: BLE001
            self.fail("split nodes", exc)

    def _note_split_used(self, conv, turn_id):
        """[s3-split] The ways in (IL) a split read drew rest for the next reads:
        a way used lately weighs a quarter at the next split's IL draw."""
        keys = ["IL:%s" % d.get("item") for t in conv.get("turns") or [] if t.get("split_of") == turn_id
                for d in t.get("decisions") or [] if d.get("family") == "IL" and d.get("item")]
        with self.lock:
            for k in keys:
                if k in self.recent_items:
                    self.recent_items.remove(k)
                self.recent_items.append(k)

    def split_line(self, stamp, text, who="dj", dj=None, handle=None, kind="", away="", prepared=False):
        """[s3-split] A single-voice line's words are final (dj_speak, after
        every rewrite, before the render; the manager's page, before its
        recording). When its node splits and the read runs past the
        threshold, the parts come back in order - each with who reads it,
        their voice when it is not a seat's own (the SFX guy's), the words to
        say (the lead-in, then the part) and the stamp its ledger row
        carries: the node's conversation, and the part's own turn. None when
        there is nothing to split (the node does not split, System 3 is not
        active for it, a fault); {"split": False, ...} when the rule read it
        whole - recorded on the node as a SPLIT event that says why."""
        try:
            if not self.ready or not isinstance(stamp, dict) or not stamp.get("conversation_id"):
                return None
            conv = handle.conv if isinstance(handle, LineHandle) else None
            if conv is None or conv["identity"]["conversation_id"] != str(stamp["conversation_id"]):
                conv = self.recent.get(str(stamp["conversation_id"]))
            if not conv or conv.get("mode") != "active":
                return None
            tid = str(stamp.get("turn_id") or "")
            turn = next((t for t in conv.get("turns") or [] if t.get("turn_id") == tid), None) if tid else None
            if turn is None or not turn.get("split_node") or turn.get("split") or turn.get("split_of"):
                return None
            speaker_who = str(who or "dj")
            pace, why = self._pace_for(speaker_who)
            got = system3.split_turn(conv, self.config, turn, text, self._studio(dj, away), speaker_who=speaker_who,
                                     pace=pace, pace_why=why, recent=self.recent_used(), mode="line",
                                     prepared=bool(prepared))
            self.remember(conv)
            self.persist(conv)
            if not got.get("split"):
                return {"split": False, "why": got.get("why", ""), "event_id": got.get("event_id")}
            self._note_split_used(conv, turn["turn_id"])
            base = {k: v for k, v in stamp.items() if k != "split"}
            parts = []
            for p in got["parts"]:
                parts.append(dict(p, stamp=dict(base, turn_id=p["turn_id"], split={
                    "part": p["part"], "of": p["of"], "of_turn": turn["turn_id"], "who": p["who"],
                    "event_id": p.get("event_id"), **({"il_event": p["il_event"]} if p.get("il_event") else {})})))
            with self.lock:
                self.metrics["splits"] = self.metrics.get("splits", 0) + 1
                self.metrics["split_parts"] = self.metrics.get("split_parts", 0) + len(parts)
            self.log("System 3 split a %s read in %d: %s" % (kind or conv["identity"].get("road_kind") or "long",
                                                              len(parts), " / ".join(p["name"] for p in parts)))
            self._flow(conv, "split a %s read into %d parts" % (conv["identity"].get("road_kind") or "", len(parts)))
            return {"split": True, "parts": parts, "whole": got.get("whole") or "", "event_id": got.get("event_id")}
        except Exception as exc:  # noqa: BLE001
            self.fail("split", exc)
            return None

    def _split_passages(self, handle):
        """[s3-split] A round's speaker-box monologue on a node that splits: its
        passage is known now (fetched, cut to the monologue budget) and the
        running order is not yet written. Past the threshold the passage is
        shared out - part 1 stays with the one who opens, each later part is a
        turn of its own right after it (who and how rolled), reading its part
        word for word - and the round grows by those turns. Only the round's
        own booth seats take a part over: the script names A, B and D."""
        try:
            conv = handle.conv
            self._mark_split_nodes(conv, handle.config, conv["identity"].get("road_kind") or "")
            roles = (conv.get("inputs") or {}).get("roles") or {}
            names = (conv.get("inputs") or {}).get("names") or {}
            added = 0
            for turn in list(conv.get("turns") or []):
                if not turn.get("split_node") or turn.get("split") or turn.get("split_of"):
                    continue
                sb = next((x for x in turn.get("speakerbox") or []
                           if x.get("mode") == "FULL_SWATH" and (x.get("material") or {}).get("text")), None)
                if sb is None:
                    continue
                people = [{"who": str(roles.get(p["actor_id"]) or p["actor_id"]), "seat": p["actor_id"],
                           "name": str(names.get(p["actor_id"]) or p.get("name") or p["actor_id"]), "voice": ""}
                          for p in conv.get("participants") or [] if p.get("actor_id") in ("A", "B", "D")]
                speaker_who = str(roles.get(turn["speaker"]) or turn["speaker"])
                nxt = next((t for t in conv["turns"] if t["index"] == turn["index"] + 1), None)
                next_who = str(roles.get(nxt["speaker"]) or nxt["speaker"]) if nxt else ""
                pace, why = self._pace_for(speaker_who)
                got = system3.split_turn(conv, handle.config, turn, sb["material"]["text"], people,
                                         speaker_who=speaker_who, pace=pace, pace_why=why, next_who=next_who,
                                         recent=self.recent_used(), mode="passage")
                if not got.get("split"):
                    continue
                parts = got["parts"]
                self._note_split_used(conv, turn["turn_id"])
                sb["material"] = dict(sb["material"], text=parts[0]["body"])
                for p in parts[1:]:
                    t = next((x for x in conv["turns"] if x["turn_id"] == p["turn_id"]), None)
                    if t is not None:
                        t["speakerbox"] = [{"mark": "split", "mode": "FULL_SWATH", "applies": True,
                                            "rate": sb.get("rate"), "request_id": "%s:split" % t["turn_id"],
                                            "why": "part %d of %d of the monologue %s opened" % (p["part"], p["of"], turn["name"]),
                                            "material": dict(sb["material"], text=p["body"])}]
                added += len(parts) - 1
                with self.lock:
                    self.metrics["splits"] = self.metrics.get("splits", 0) + 1
                    self.metrics["split_parts"] = self.metrics.get("split_parts", 0) + len(parts)
            if added:
                conv["timing"]["turn_budget"] = int(conv["timing"].get("turn_budget") or 0) + added
                if handle.turns:
                    handle.turns = int(handle.turns) + added
                self._flow(conv, "shared a speaker-box monologue out over %d more turn(s)" % added)
        except Exception as exc:  # noqa: BLE001
            self.fail("split passages", exc)

    SPLIT_MARK = "SPLIT_NODES"       # [s3-split] in defaults_added: the switch was put on once

    def add_split_defaults(self):
        """[s3-split] The SPLIT node's switch on its default nodes - the
        produced advert, the manager's own page, the banter cycle's opening
        step (the speaker-box monologue) - for a config saved before the switch
        existed. Only a node that has no `splits` key is switched on, and once
        it has been done the mark in `defaults_added` stops it for good, so a
        box the operator unticks stays unticked. Saved as a version with a note."""
        config = self.config if isinstance(self.config, dict) else {}
        seen = {str(x) for x in (config.get("defaults_added") or [])}
        if self.SPLIT_MARK in seen:
            return []
        new = copy.deepcopy(config)
        done = []
        for road, node_id in system3_tables.SPLIT_DEFAULT_NODES:
            if road == "banter":
                holder = new.get("structure") if isinstance(new.get("structure"), dict) else None
                nodes = list((holder or {}).get("steps") or [])
                # [nodeplan] the chapter plans banter now: its start node is the
                # same opening-monologue node the cycle's `initial` step is
                nodes += [n for n in ((holder or {}).get("graph") or {}).get("nodes") or []
                          if isinstance(n, dict) and n.get("id") == "start"]
            else:
                holder = (new.get("structures") or {}).get(road)
                nodes = holder.get("legs") if isinstance(holder, dict) else None
            for n in nodes or []:
                if (isinstance(n, dict) and "splits" not in n
                        and n.get("id") in ((node_id, "start") if road == "banter" else (node_id,))):
                    n["splits"] = True
                    n.setdefault("max_splits", system3_tables.SPLIT_MAX_SPLITS)
                    holder["version"] = int(holder.get("version") or 1) + 1
                    if "%s/%s" % (road, node_id) not in done:
                        done.append("%s/%s" % (road, node_id))
        if not done:
            return []
        new["defaults_added"] = sorted(seen | {self.SPLIT_MARK})
        try:
            self.store.save_config(new, "the SPLIT node's switch on by default (once): " + ", ".join(done))
        except Exception as exc:  # noqa: BLE001
            self.fail("split defaults", exc)
            return []
        self.config = new
        return done

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
            # [s3-flow] UNIQUENESS: a written turn that nearly repeats a line already
            # on air sends the round to the REPAIR roll - a rewrite, not a rerun
            _rep = self.near_repeats(turns)
            if _rep:
                val["repair_wanted"] = True
                val["near_repeats"] = _rep
                self.observe_later(handle.id, "REPEAT", {"turns": _rep, "why": "these written turns nearly repeat "
                                                         "lines already on air"})
            # [s3-scaffold] a draft that echoed a prompt header goes back too: the parser
            # cuts it from the air, but the writer did not write the round it was asked for
            _echo = system3.find_scaffold(script or "", self.scaffold_kit())
            if _echo:
                val["repair_wanted"] = True
                val["scaffold"] = max(1, int(val.get("scaffold") or 0))
                self.observe_later(handle.id, "SCAFFOLD", {"header": _echo[:80], "why": "the draft echoed a prompt "
                                                           "header into the dialogue"})
            # [s3-echo] ...and so does one whose turns say a direction of its running order
            # (validate flagged it): the last gate would cut those turns before the air
            _said = [c["what"][len("direction:"):] for r in (val.get("turns") or []) + (val.get("unplanned") or [])
                     for c in r.get("checks") or [] if str(c.get("what") or "").startswith("direction:")]
            if _said:
                self.observe_later(handle.id, "DIRECTION", {"directions": _said[:8], "why": "written turns said a "
                                                            "running-order direction as dialogue"})
            handle.conv["pre_repair"] = {k: val[k] for k in ("score", "verdict", "seat_order", "turn_ratio")}
            # [s3-rewrite] the REPAIR roll decides: a round that rolled "stands"
            # is not sent back, whatever the checks say - and says so
            roll = handle.conv.get("repair_roll")
            if val["repair_wanted"] and isinstance(roll, dict) and roll.get("repair") is False:
                self.observe_later(handle.id, "REPAIR", {"why": "missed: seat order %.2f, turns %.2f - but the REPAIR "
                                                        "roll said it stands as written" % (val["seat_order"], val["turn_ratio"]),
                                                        "validation": handle.conv["pre_repair"], "rolled": False})
                return False
            if val["repair_wanted"]:
                with self.lock:
                    self.metrics["repairs"] += 1
                self.observe_later(handle.id, "REPAIR", {"why": "seat order %.2f, turns %.2f" % (
                    val["seat_order"], val["turn_ratio"]), "validation": handle.conv["pre_repair"]})
            return bool(val["repair_wanted"])
        except Exception as exc:  # noqa: BLE001
            self.fail("repair check", exc)
            return False

    def scaffold_kit(self):
        """[s3-scaffold] The labels System 3 writes into a writer's prompt, for the
        live config: its sheets, every structure's head and legs, every prompt block."""
        cfg = self.config if isinstance(self.config, dict) else {}
        got = getattr(self, "_scaffold_cache", None)
        if not got or got[0] is not cfg:
            got = (cfg, system3.scaffold_kit(cfg))
            self._scaffold_cache = got
        return got[1]

    def strip_scaffold(self, text):
        """[s3-scaffold] The station's cut: an echoed prompt header, to the end of
        its paragraph, never reaches a voice. Never raises."""
        try:
            return system3.strip_scaffold(text, self.scaffold_kit())
        except Exception as exc:  # noqa: BLE001
            self.fail("scaffold", exc)
            return str(text or "")

    def direction_echo(self, text, work):
        """[s3-echo] The station's door to the direction matcher: the running-order
        direction `text` says aloud, or "". `work` is one row's work or a whole
        sheet. Never raises."""
        try:
            return system3.direction_echo(text, system3.direction_kit(work))
        except Exception as exc:  # noqa: BLE001
            self.fail("direction echo", exc)
            return ""

    def echo_cut(self, entry, handle):
        """[s3-echo] THE LAST GATE. A written turn that still says a direction of
        its running order - the REPAIR roll and the rewrite have had their chance,
        and a live round gets neither - is cut from the round before the bind,
        from every version of its words the station keeps (the script, the plain
        and the tinted), so no later pass can bring it back. It never airs:
        recorded as an ECHO observation and on the drop log. Returns what the
        script lost ([] when nothing)."""
        cut = []
        try:
            if not handle or not handle.active or not isinstance(entry, dict):
                return cut
            kit = system3.conv_direction_kit(handle.conv)
            names = (str(entry.get("caller_name") or ""), str(entry.get("caller2_name") or ""))
            for key in ("script", "script_plain", "script_tinted"):
                text = str(entry.get(key) or "")
                if not text.strip():
                    continue
                turns = self.host.banter_turns(text, *names)
                bad = [(i, system3.direction_echo(said, kit)) for i, (_m, said) in enumerate(turns)]
                bad = [(i, p) for i, p in bad if p]
                if not bad:
                    continue
                gone = {i for i, _p in bad}
                entry[key] = "\n".join("%s: %s" % (m, said) for i, (m, said) in enumerate(turns) if i not in gone)
                if key == "script":
                    cut = [{"script_index": i, "direction": p, "said": str(turns[i][1])[:200]} for i, p in bad]
            if cut:
                handle.conv["echo_cut"] = cut
                self.observe_later(handle.id, "ECHO", {"cut": cut, "why": "a written turn said a direction of its "
                                                       "running order as dialogue - cut before the bind, never aired"})
                with self.lock:
                    self.metrics["echo_cut"] = self.metrics.get("echo_cut", 0) + len(cut)
                try:
                    self.host.pipeline_log("drop", "%d written turn(s) said a running-order direction as dialogue - "
                                                   "cut before the round was bound" % len(cut),
                                           extra="; ".join("%s: %s" % (c["direction"], c["said"][:80]) for c in cut)[:1200])
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            self.fail("echo cut", exc)
        return cut

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

    # --- [s3-turnchain] the copy gate, where the written lines are bound -------------
    def turn_gate(self, handle, turns, spoken=None, prepared=False):
        """Open the copy gate over a written round: `turns` [(marker, text)] as the
        station parsed and cleaned them, `spoken` their words as they will be said,
        `prepared` a banked or System 2 round (only those are re-written). True
        when there is a walk to drive; False when the round is not System 3's."""
        if not handle or not getattr(handle, "active", False) or not isinstance(turns, (list, tuple)) or not turns:
            return False
        try:
            rewrites = system3.GATE_REWRITES if (prepared and self.settings.get("repair", True)) else 0
            handle.gate = system3.gate_open(handle.conv, [(str(m or ""), str(x or "")) for m, x in turns],
                                            None if spoken is None else [str(x or "") for x in spoken],
                                            rewrites=rewrites, visits=system3.GATE_VISITS if rewrites else 0)
            handle.gate["prepared"] = bool(prepared)
            self._gate_flush(handle)
            return True
        except Exception as exc:  # noqa: BLE001
            handle.gate = None
            self.fail("copy gate", exc)
            return False

    def turn_gate_next(self, handle):
        """The next one-line re-write the station should ask for, or None."""
        run = getattr(handle, "gate", None)
        if not run:
            return None
        try:
            ask = system3.gate_next(handle.conv, run)
            self._gate_flush(handle)
            return dict(ask) if ask else None
        except Exception as exc:  # noqa: BLE001
            handle.gate = None
            self.fail("copy gate", exc)
            return None

    def turn_gate_reply(self, handle, text, spoken=None):
        """The writer's answer to the re-write asked for ("" when it failed)."""
        run = getattr(handle, "gate", None)
        if not run:
            return
        try:
            system3.gate_take(handle.conv, run, text, spoken)
            with self.lock:
                self.metrics["gate_visits"] += 1
        except Exception as exc:  # noqa: BLE001
            self.fail("copy gate", exc)

    def turn_gate_done(self, handle):
        """Close the walk: {script, changed, held, counts} - {} when there was
        no walk (the round goes on as written)."""
        run = getattr(handle, "gate", None)
        if not run:
            return {}
        try:
            out = system3.gate_close(handle.conv, run)
            self._gate_flush(handle)
            c = out["counts"]
            with self.lock:
                self.metrics["gate_rounds"] += 1
                for k in ("caught", "rewritten", "dropped", "trimmed"):
                    self.metrics["gate_" + k] += int(c.get(k) or 0)
                self.metrics["gate_held"] += 1 if out.get("held") else 0
            if c.get("caught") or c.get("trimmed"):
                self._flow(handle.conv, "copy gate: %d caught, %d re-written, %d dropped%s%s" % (
                    c["caught"], c["rewritten"], c["dropped"],
                    (", %d written past the end" % c["trimmed"]) if c.get("trimmed") else "",
                    (" - held: " + out["held"][:100]) if out.get("held") else ""))
            self.remember(handle.conv)
            return out
        except Exception as exc:  # noqa: BLE001
            self.fail("copy gate", exc)
            return {}
        finally:
            handle.gate = None

    def _gate_flush(self, handle):
        """The walk's events, each a GATE observation on its node."""
        run = getattr(handle, "gate", None) or {}
        events, run["events"] = list(run.get("events") or []), []
        cid = handle.conv["identity"]["conversation_id"]
        for body in events:
            self.observe_later(cid, system3.GATE_FAMILY, body, body.get("turn_id") or "")

    def beat_gate(self, handle):
        """Mode B: the beat chain's check on each line it is about to seat - a
        function (made, row, text) -> "" or what the line copies. A catch ends the
        beat's accepted lines there, so the retry (or the next beat) writes that
        turn again, told what its draft repeated. None: not a System 3 round."""
        if not handle or not getattr(handle, "active", False):
            return None
        conv = handle.conv
        cid = conv["identity"]["conversation_id"]

        def check(made, row, text):
            try:
                idx = int((row or {}).get("turn") or 0) - 1
                idx = idx if 0 <= idx < len(conv["turns"]) else None
                earlier = [("%s's line (turn %d)" % (system3._gate_name(conv, str(m)[:1]), i + 1), str(x or ""))
                           for i, (m, x) in enumerate(made or [])]
                got = system3.gate_check(conv, idx, text, earlier)
                if not got:
                    return ""
                rec = conv.setdefault("turn_gate", {}).setdefault("in_chain", {"caught": 0, "turns": []})
                rec["caught"] += 1
                rec["turns"].append({"turn": idx, "rule": got["rule"], "of": got["what"]})
                t = conv["turns"][idx] if idx is not None else {}
                body = {"stage": "caught in the beat chain", "rule": got["rule"], "why": got["why"],
                        "of": got["what"], "copied": got.get("text", ""), "how": got.get("how", ""),
                        "turn_index": idx if idx is not None else -1, "seat": str((row or {}).get("seat") or ""),
                        "line": system3._gate_excerpt(text, 200), "planned": idx is not None,
                        "then": "the beat is written again from this turn"}
                if t:
                    body["turn_id"] = t["turn_id"]
                    body["dice"] = system3.gate_dice(conv, idx)
                self.observe_later(cid, system3.GATE_FAMILY, body, t.get("turn_id", "") if t else "")
                with self.lock:
                    self.metrics["gate_in_chain"] += 1
                return "%s (%s)" % (got["what"], system3._gate_excerpt(got.get("text") or "", 160))
            except Exception as exc:  # noqa: BLE001
                self.fail("copy gate (beats)", exc)
                return ""
        return check

    @staticmethod
    def line_copies(text, earlier):
        """Does `text` copy one of the lines just said (`earlier`, oldest first)?
        {"of": index, "how", "text"} for the latest it copies, else None. Never raises."""
        try:
            words = system3.gate_words(text)
            for i in range(len(earlier or ()) - 1, -1, -1):
                how = system3.gate_copies(words, system3.gate_words(earlier[i]))
                if how:
                    return {"of": i, "how": how, "text": system3._gate_excerpt(earlier[i], 160)}
        except Exception:  # noqa: BLE001
            pass
        return None

    def line_gate(self, ref, text, got):
        """A line the microphone refused as a copy of a line just said: a GATE
        observation on its node (a LineHandle, or a stamp {conversation_id,
        turn_id}); a single-voice line's node is marked dropped."""
        try:
            got = dict(got or {})
            if isinstance(ref, LineHandle):
                cid, tid, conv = ref.id, str((ref.stamp or {}).get("turn_id") or ""), ref.conv
            elif isinstance(ref, dict):
                cid, tid = str(ref.get("conversation_id") or ""), str(ref.get("turn_id") or "")
                conv = self.recent.get(cid)
            else:
                return
            if not cid:
                return
            self.observe_later(cid, system3.GATE_FAMILY, {
                "stage": "dropped at the microphone", "rule": "copy", "why": str(got.get("why") or "")[:300],
                "of": "the line just said", "copied": str(got.get("text") or "")[:200],
                "how": str(got.get("how") or ""), "kind": str(got.get("kind") or ""),
                "line": system3._gate_excerpt(text, 200), "turn_id": tid}, tid)
            with self.lock:
                self.metrics["gate_air_dropped"] += 1
            if isinstance(conv, dict) and len(conv.get("turns") or []) == 1 and conv.get("status") != "bound":
                conv["turns"][0]["status"] = "dropped"
                conv["status"] = "dropped"
                conv["turn_gate"] = {"at": time.time(), "caught": 1, "rewritten": 0, "dropped": 1, "trimmed": 0,
                                     "visits": 0, "held": "", "air": str(got.get("why") or "")[:300]}
                self.remember(conv)
                self.persist(conv)
        except Exception as exc:  # noqa: BLE001
            self.fail("copy gate (air)", exc)

    # --- bind (script freeze) ------------------------------------------------------
    def bind_entry(self, entry, handle):
        """The script is written: align it with the plan, validate it, and
        stamp each turn's decision chain where the air already carries dice
        (entry["turn_dice"] -> every script-ledger line's `dice`)."""
        if not handle or not isinstance(entry, dict):
            return
        conv = handle.conv
        try:
            self.echo_cut(entry, handle)                                   # [s3-echo] the last gate
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
                            {"file": mat["file"], "text": system3.whole_cut(mat["text"], 600), "door": "system3:" + sb["mode"].lower()})
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
                conv["actual"] = [{"speaker": m, "text": system3.whole_cut(x, 600)} for m, x in turns]
                # Which written line each planned turn lines up with, so the
                # Script page can show a shadow plan beside the words that
                # actually aired on that seat.
                conv["shadow_bindings"] = [{"turn_id": t["turn_id"], "script_index": mapping.get(t["index"])}
                                           for t in conv["turns"]]
                conv["status"] = "shadowed"
            with self.lock:
                self.open.pop(conv["identity"]["conversation_id"], None)
            entry["system3"] = {"conversation_id": conv["identity"]["conversation_id"],
                                "trace_id": conv["identity"]["trace_id"], "mode": conv["mode"],
                                "revision": conv["identity"]["revision"], "seed": conv["seed"],
                                "config_hash": conv["config_hash"],
                                "verdict": (conv.get("validation") or {}).get("verdict"),
                                # [s3-rounds] how many turns the running order dealt: the air's
                                # "incomplete conversation" gate read this and it was never set
                                "planned_turns": len(conv["turns"]),
                                # [s3-turnchain] the copy gate's count for this round
                                "gate": system3.gate_counts(conv),
                                # [s3-carry] a banked round carries the last round's state in
                                # the voice only, at air
                                "bank": bool((conv.get("inputs") or {}).get("bank")),
                                "carry": (conv.get("carry") or {}).get("from") or "",
                                # script turn index -> planned turn, which the
                                # air copies onto every script-ledger line.
                                "turns": {str(i): t["turn_id"] for t in conv["turns"]
                                          for i in [mapping.get(t["index"])] if i is not None}}
            # [s3-rewrite] the rolls the passes after the bind read (the
            # larder / retint tint, the Writers' Room), on the same record
            if handle.active and isinstance(entry.get("system3"), dict):
                if any(t.get("tint") for t in conv["turns"]):
                    entry["system3"]["tint_turns"] = sorted(
                        int(mapping[t["index"]]) for t in conv["turns"]
                        if (t.get("tint") or {}).get("rhyme") and mapping.get(t["index"]) is not None)
                for key in ("repair", "room"):
                    got = conv.get(key + "_roll")
                    if isinstance(got, dict):
                        entry["system3"][key] = bool(got.get(key))
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

    def _turn_of_loose(self, meta, text, who=""):
        """[s3-direction] The script index of a chunk whose exact words are not in
        the round's script (the air path reworded it): the seat's turn whose words
        it shares most, at least 60% of the chunk's words, else None. For the
        voice only - the ledger link keeps the exact match."""
        try:
            s3 = (meta or {}).get("system3") or {}
            cid = s3.get("conversation_id")
            if not cid:
                return None
            script = str(meta.get("script") or "")
            key = cid + ":" + hashlib.md5(script.encode("utf-8")).hexdigest()[:10]
            if self.turns_cache.get(key) is None:
                self._turn_of(meta, text, who)                                # it fills the cache
            turns = self.turns_cache.get(key) or []
            words = re.findall(r"[a-z0-9']+", str(text or "").lower())
            if len(words) < 3:
                return None
            seat = _SEAT_OF.get(str(who or ""), "")
            best, best_i = 0.0, None
            for i, (m, said) in enumerate(turns):
                if seat and str(m)[:1] != seat:
                    continue
                have = set(re.findall(r"[a-z0-9']+", str(said or "").lower()))
                share = sum(1 for w in words if w in have) / float(len(words))
                if share > best:
                    best, best_i = share, i
            return best_i if best >= 0.6 else None
        except Exception as exc:  # noqa: BLE001
            self.fail("loose turn", exc)
            return None

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
                i = self._turn_of_loose(entry, text, who)                     # [s3-direction] reworded on the way
            dims = None
            if i is not None:
                stamp = (((entry.get("turn_dice") or {}).get(str(i)) or {}).get("s3") or {})
                dims = (stamp.get("perf") or {}).get("dims")
            if not isinstance(dims, dict) or not dims:
                # [es-every-turn] the seat's current feeling, as perf_voice does
                if _cid is None:
                    _cid = ((entry or {}).get("system3") or {}).get("conversation_id")
                feel = self._seat_feel(_cid, who)
                dims = (feel or {}).get("dims")
                if not isinstance(dims, dict) or not dims:
                    return None
            with self.lock:
                self.metrics["perf_applied"] += 1
            out = {d: float(dims.get(d) or 0) for d in system3.EMOTION_DIMS}
            if (entry.get("system3") or {}).get("bank"):
                # [s3-carry] a banked round's words were frozen before the round that
                # just aired existed; its delivery still starts from where that round
                # left the seat, fading over the carry window
                carry = self.carry_now()
                seat = _SEAT_OF.get(str(who or ""), "")
                got = ((carry or {}).get("seats") or {}).get(seat) if carry else None
                if isinstance(got, dict) and isinstance(got.get("dims"), dict):
                    f = 0.4 * float(carry.get("factor") or 0)
                    out = {d: round((1 - f) * out[d] + f * float(got["dims"].get(d) or 0), 3) for d in out}
                    cid = str(_cid or "")
                    if cid and cid not in self._carry_noted:
                        self._carry_noted.add(cid)
                        if len(self._carry_noted) > RECENT:
                            self._carry_noted.pop()
                        with self.lock:
                            self.metrics["carry_delivery"] += 1
                        self.observe_later(cid, "CARRY", {"stage": "delivery", "from": carry.get("from"),
                                                          "factor": carry.get("factor"), "blend": round(f, 3),
                                                          "why": "a banked round: the words were written in advance, "
                                                                 "so only the voice starts from the last round's ending"})
            return out
        except Exception as exc:  # noqa: BLE001
            self.fail("performance", exc)
            return None

    def perf_of_stamp(self, stamp, who="", disk=False):
        """[es-roads] ES -> the voice for a road that holds a STAMP, not the round
        entry or the line handle: the turn it names, as {"dims": the state for
        performance_vector(state=), "voice": the ES row's voice block with its
        "row"}. A split part inherits the turn it was cut from. The conversation
        is read from memory; `disk` reads the store when it has aged out (a
        banked shelf row) - call that off the event loop. None: no such active
        turn, or no feeling on it."""
        try:
            if not isinstance(stamp, dict) or not stamp.get("conversation_id") or not stamp.get("turn_id"):
                return None
            cid = str(stamp["conversation_id"])
            conv = self.recent.get(cid)
            if conv is None and disk:
                conv = self.store.conversation(cid, with_events=False)
            if not conv or (conv.get("mode") or stamp.get("mode")) != "active":
                return None
            turns = {str(t.get("turn_id")): t for t in conv.get("turns") or []}
            t = turns.get(str(stamp["turn_id"]))
            perf = (t or {}).get("performance") or {}
            if not perf.get("dims") and not perf.get("voice"):
                t = turns.get(str(((stamp.get("split") or {}).get("of_turn")) or (t or {}).get("split_of") or ""))
                perf = (t or {}).get("performance") or {}
            dims = perf.get("dims") if isinstance(perf.get("dims"), dict) else None
            voice = perf.get("voice") if isinstance(perf.get("voice"), dict) else None
            if not dims and voice is None:
                return None
            with self.lock:
                self.metrics["stamp_perf"] = int(self.metrics.get("stamp_perf") or 0) + 1
            return {"dims": ({d: float(dims.get(d) or 0) for d in system3.EMOTION_DIMS} if dims else None),
                    "voice": (dict(voice, row=system3.es_row(t) or {}) if voice is not None else None)}
        except Exception as exc:  # noqa: BLE001
            self.fail("stamp performance", exc)
            return None

    def _seat_feel(self, cid, who):
        """[es-every-turn] the seat's current feeling as System 3 holds it:
        {"voice", "dims", "row"} or None. Nothing is drawn."""
        seat = _SEAT_OF.get(str(who or ""), "")
        if not cid or not seat:
            return None
        conv = self.recent.get(str(cid))
        if conv is None:
            try:
                conv = self.store.conversation(str(cid))
            except Exception:  # noqa: BLE001
                conv = None
        if not isinstance(conv, dict) or not isinstance(conv.get("participants"), list):
            return None
        p = system3.participant(conv, seat) or {}
        emo = p.get("emotion") if isinstance(p.get("emotion"), dict) else {}
        if not emo.get("table") or not emo.get("category"):
            return None
        spec = {"table": emo["table"], "category": emo["category"], "id": emo.get("id"),
                "label": emo.get("label")}
        block = system3.es_voice(self.config, spec)
        intensity = float(emo.get("intensity") or 0.5)
        return {"voice": system3.voice_intent(block, intensity) if block else None,
                "dims": emo.get("dims") if isinstance(emo.get("dims"), dict) else {},
                "row": {"table": emo["table"], "category": emo["category"], "item": emo.get("id"),
                        "label": emo.get("label"), "intensity": round(intensity, 3),
                        "source": "the seat's current feeling"}}

    def _voice_miss(self, why):
        with self.lock:
            self.metrics[why] = int(self.metrics.get(why) or 0) + 1

    def perf_voice(self, entry, turns, text, who=""):
        """[s3-es-voice] ES -> the recording: the voice block this turn's stamp
        carries (the ES row's `voice` at the turn's intensity), for
        performance_vector(es=...). None when the round is not active, the chunk
        is not one of its turns, or the turn has no voice of its own."""
        try:
            if ((entry or {}).get("system3") or {}).get("mode") != "active":
                return None
            _cid, i = self._turn_of(entry, text, who)
            if i is None:
                i = self._turn_of_loose(entry, text, who)                     # [s3-direction] its voice too
            got = None
            stamp = {}
            if i is not None:
                stamp = (((entry.get("turn_dice") or {}).get(str(i)) or {}).get("s3") or {})
                got = (stamp.get("perf") or {}).get("voice")
            if not isinstance(got, dict):
                # [es-every-turn] no voice of its own: the seat's current feeling
                self._voice_miss("voice_miss_noturn" if i is None else "voice_miss_novoice")
                if _cid is None:
                    _cid = ((entry or {}).get("system3") or {}).get("conversation_id")
                feel = self._seat_feel(_cid, who)
                if not feel or not isinstance(feel.get("voice"), dict):
                    return None
                self._voice_miss("voice_seat")
                return dict(feel["voice"], row=dict(feel["row"]))
            with self.lock:
                self.metrics["voice_applied"] = int(self.metrics.get("voice_applied") or 0) + 1
            # [es-roads] and which ES row it is, for the air record (a stamp from
            # before the row rode it names the feeling and its intensity only)
            row = (stamp.get("perf") or {}).get("row")
            if not isinstance(row, dict):
                row = {k: v for k, v in (("label", stamp.get("es")), ("intensity", stamp.get("intensity")))
                       if v is not None}
            return dict(got, row=dict(row))
        except Exception as exc:  # noqa: BLE001
            self.fail("voice", exc)
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
                "played": [dict({"clip": Path(str(a.get("path") or "")).name,
                                 "sample_id": a.get("sfx_sample_id") or a.get("sfx_video_id"),
                                 "seconds": a.get("seconds"), "why": a.get("sfx_match_why") or ""},
                                **{k: a[k] for k in ("sfx_roll", "poster") if a.get(k)})   # [s3-sfx-roll]
                           for a in board],
                "sfx_guy": [{"text": a.get("text"), "voice": a.get("voice")} for a in guy],
                "matcher": stats,
                "chosen_by": ("System 3's rolls - the family, then the clip - among the survivors of the "
                              "station's matcher, bans, weights and rotation"
                              if any(a.get("sfx_roll") for a in board)                 # [s3-sfx-roll]
                              else "the station's matcher, bans, weights and rotation")})
        except Exception as exc:  # noqa: BLE001
            self.fail("sfx observe", exc)

    def observe_ledger(self, block, sid, rows, round_kind=""):
        """A round was committed to the script ledger - the script is frozen
        and ordered. Record which ledger line each planned turn became."""
        try:
            with self.lock:                                                    # [s3-flow]
                for row in rows or []:
                    if isinstance(row, dict) and len(str(row.get("text") or "")) > 30:
                        self.recent_air.append(" ".join(str(row["text"]).split())[:600])
            self._paces_from(rows)                                             # [s3-split] each voice's pace
            links = {}
            for ord_, row in enumerate(rows or []):
                s3 = row.get("system3") if isinstance(row.get("system3"), dict) else {}
                if not s3.get("conversation_id"):
                    s3 = ((row.get("dice") or {}) if isinstance(row.get("dice"), dict) else {}).get("s3") or {}
                cid = s3.get("conversation_id")
                if not cid or not row.get("line_id"):
                    continue
                links.setdefault(cid, []).append(dict({
                    "line_id": str(row["line_id"]), "conversation_id": cid, "turn_id": s3.get("turn_id") or None,
                    "block": int(block), "ord": ord_, "sid": str(sid or ""), "who": str(row.get("who") or ""),
                    "text": str(row.get("text") or ""), "at": time.time()},
                    **{k: s3[k] for k in _LINE_KEEPS if s3.get(k)}))        # [s3-sfx-roll] [s3-banks-roll]
            if not links:
                return
            # [link-now] 2026-09-30, the operator: "Why was no system three table
            # roll for this item?" The manager's line was committed at :23 and
            # linked at 1:11 - 48 s behind ~15 roll events a second on the one
            # store thread - and a card that asked in between was told "not
            # directed by System 3". The links are known now; the store catches up.
            with self.lock:
                for lines in links.values():
                    for x in lines:
                        self.pending_links[x["line_id"]] = x
                while len(self.pending_links) > 600:
                    self.pending_links.popitem(last=False)
            for cid, lines in links.items():
                with self.lock:
                    self.metrics["lines_linked"] += len(lines)

                def job(lines=lines, cid=cid):
                    self.store.add_lines(lines)
                    # [s3-sfx-roll] the lines table keeps words and order; a board
                    # line's rolls and poster ride the COMMIT, keyed by line id
                    media = {x["line_id"]: {k: x[k] for k in _LINE_KEEPS if x.get(k)}
                             for x in lines if any(x.get(k) for k in _LINE_KEEPS)}   # [s3-banks-roll]
                    self.store.add_observation(cid, "COMMIT", dict({
                        "stage": "script-ledger", "block": int(block), "sid": str(sid or ""),
                        "round": str(round_kind or ""), "lines": [x["line_id"] for x in lines],
                        "turns": [x["turn_id"] for x in lines]}, **({"media": media} if media else {})))
                    # [s3-carry] the round is on the air in this order: what it leaves
                    # behind is the next round's start
                    conv = self.recent.get(cid) or self.store.conversation(cid, with_events=False)
                    # [s3-banks-roll] a gold bar replayed off an older round is not
                    # that round airing: its ending is not the next round's start
                    if conv and all(x.get("gold") for x in lines):
                        conv = None
                    if conv:
                        handed = self._hand_on(conv, [r for r in (rows or []) if isinstance(r, dict)])
                        if handed:
                            self.store.add_observation(cid, "CARRY", handed)
                        self._cast_aired(conv)                                  # [s3-cast]
                        self._callend_aired(conv)                               # [s3-callend] the gallery, at air
                _STORE_POOL.submit(job)
        except Exception as exc:  # noqa: BLE001
            self.fail("ledger link", exc)

    # --- [s3-inject] THE HONEST FORCED CARD ------------------------------------------
    #
    # "FORCED INJECTORS (dead-air rescue, boot recovery, level-gate cover) =
    #  honest forced-node cards ("forced: no roll - injected by <system>
    #  because <reason>") with the timeline injection point; never fake
    #  dice" - and the ONE TREE rule: "any interjections are just additional
    #  nodes being added in there ... injected as part of that same broadcast
    #  node tree for that segment" (the operator, 2026-09-28).  One door for
    #  everything the station forces onto the air without a roll: the
    #  injection is recorded as an INJECT observation event (no rng, no
    #  stages) ON the conversation executing at that point of the timeline,
    #  so every view of the segment renders it inside the executed tree,
    #  never as an orphan - and no view ever has to invent dice for it.
    INJECT_STANDING_REST = 1800.0    # a standing surface (Pine Cam) says so once per spell

    def injected_node(self, by, why, kind="", line_id="", text="", at=None,
                      conversation_id="", turn_id="", standing=False, extra=None):
        """Record one forced (no-roll) injection on the executed tree.

        Files "forced: no roll - injected by <by> because <why>" as an
        INJECT observation on `conversation_id` when given, else on the
        conversation of `line_id` (the ledger link), else of the line on
        air (_SPEAKING_NOW -> the ledger link / the line hook's stamp),
        else the newest conversation the runtime holds - the tree the
        injection lands in.  `standing=True` is a fixed surface's card
        (GAP 11): written once per spell, deduped for
        INJECT_STANDING_REST seconds.  Returns True when the write was
        queued.  Never raises into an air path; never rolls anything."""
        try:
            if self.store is None:
                return False
            by = " ".join(str(by or "the station").split())[:120]
            why = " ".join(str(why or "").split())[:400] or "no reason was recorded"
            when = float(at or time.time())
            if standing:
                with self.lock:
                    stood = self.__dict__.setdefault("_inject_stood", {})
                    key = (by, str(kind or ""))
                    if when - float(stood.get(key) or 0.0) < self.INJECT_STANDING_REST:
                        return False
                    stood[key] = when
            sp = getattr(self.host, "_SPEAKING_NOW", None)
            sp = dict(sp) if isinstance(sp, dict) else {}
            held = getattr(self.host, "_S3_LINE_BY_ID", None)
            held = dict(held) if isinstance(held, dict) else {}
            body = {"stage": "injected", "by": by, "why": why,
                    "card": "forced: no roll - injected by %s because %s" % (by, why),
                    "kind": str(kind or ""), "line_id": str(line_id or ""),
                    "text": " ".join(str(text or "").split())[:300],
                    "authority": "forced", "at": when}
            if standing:
                body["standing"] = True
            if isinstance(extra, dict):
                for k, v in list(extra.items())[:8]:
                    body.setdefault(str(k)[:40], v)
            want_cid, want_tid = str(conversation_id or ""), str(turn_id or "")

            def job():
                cid, tid, how = want_cid, want_tid, "the caller named the round"
                try:
                    def link_of(lid):
                        if not lid:
                            return None
                        got = held.get(lid)
                        if not (isinstance(got, dict) and got.get("conversation_id")):
                            try:
                                got = self.store.line(lid)
                            except Exception:  # noqa: BLE001
                                got = None
                        return got if isinstance(got, dict) and got.get("conversation_id") else None
                    if not cid:
                        stamp = link_of(str(line_id or ""))
                        if stamp:
                            cid = str(stamp["conversation_id"])
                            tid = str(stamp.get("turn_id") or "")
                            how = "its own line's link"
                    if not cid:
                        stamp = link_of(str(sp.get("id") or ""))
                        if stamp:
                            cid = str(stamp["conversation_id"])
                            tid = str(stamp.get("turn_id") or "")
                            how = "the line on air"
                    if not cid:
                        with self.lock:
                            cid = next(reversed(self.recent), "") if self.recent else ""
                        how = "the newest round the runtime holds"
                    if not cid:
                        rows = self.store.conversations(limit=1)
                        cid = str(((rows or [{}])[0] or {}).get("conversation_id") or "")
                        how = "the newest round in the store"
                    if not cid:
                        with self.lock:
                            self.metrics["inject_dropped"] = self.metrics.get("inject_dropped", 0) + 1
                        return
                    body["anchored"] = how
                    if tid:
                        body["turn_id"] = tid   # the card sits ON its turn in every view
                    self.store.add_observation(cid, "INJECT", body, tid)
                    with self.lock:
                        self.metrics["injected"] = self.metrics.get("injected", 0) + 1
                except Exception as exc:  # noqa: BLE001
                    self.fail("injected node", exc)
            _STORE_POOL.submit(job)
            return True
        except Exception as exc:  # noqa: BLE001
            self.fail("injected node", exc)
            return False

    # --- [s3-segment] the scheduled segments the air goes through ----------------------
    #
    # "every conversation should be chained as the "segment" per the station that is
    #  scheduled with everything for that segment occuring within the section of the
    #  messenger view. I also want to be able to expand and select and investigate
    #  and inspect other segments via the right click menu and be able to trace the
    #  nodes of how the segments are constructed via roulette RNG and System 3"
    #  (the operator, 2026-09-28).
    #
    # A segment is the running order's OCCURRENCE: one entry of the hour as the
    # station's clock put it on air (System2's slot "hour-<ms>:<entry>", else the
    # legacy walk's). app.py stamps it on every script-ledger row when the row takes
    # its place in the script and hands each block here: the register keeps, per
    # segment, its blocks in the script's order, their lines and the System 3
    # conversations those lines belong to - a round, or a single line (an
    # interjection, a station ID, an ad spot), which is a one-turn conversation of
    # its own and never a segment of its own.
    SEGMENT_KEYS = ("id", "template", "kind", "label", "start", "ends", "hour", "index", "engine")

    def segment_now(self):
        """The scheduled segment on air right now, as the station publishes it
        (app.py segment_on_air), or {} - a station without the stamp, or running
        no schedule. Never raises."""
        try:
            got = self.host.segment_on_air()
        except Exception:  # noqa: BLE001
            return {}
        if not isinstance(got, dict) or not got.get("id"):
            return {}
        return {k: got[k] for k in self.SEGMENT_KEYS if k in got}

    def segment_block(self, block, at, sid, rows, segment, round_kind=""):
        """A block of the script was written while `segment` owned the air: file it
        in the register with its lines and, by conversation, the lines each System 3
        conversation has in it. On the store's own thread, bounded like every write
        here. Never raises into the ledger."""
        try:
            if not isinstance(segment, dict) or not segment.get("id"):
                return
            line_ids, convs = [], {}
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                lid = str(row.get("line_id") or "")
                if lid:
                    line_ids.append(lid)
                s3 = row.get("system3") if isinstance(row.get("system3"), dict) else {}
                if not s3.get("conversation_id"):
                    s3 = ((row.get("dice") or {}) if isinstance(row.get("dice"), dict) else {}).get("s3") or {}
                cid = str(s3.get("conversation_id") or "")
                if cid:
                    convs.setdefault(cid, [])
                    if lid:
                        convs[cid].append(lid)
            seg = {k: segment[k] for k in self.SEGMENT_KEYS if k in segment}
            with self.lock:
                if self.pending >= WRITE_BACKLOG:
                    self.metrics["writes_dropped"] += 1
                    return
                self.pending += 1
                self.metrics["segment_blocks"] = self.metrics.get("segment_blocks", 0) + 1

            def job():
                try:
                    self.store.note_segment_block(seg, int(block), float(at or time.time()), str(sid or ""),
                                                  str(round_kind or ""), line_ids, convs)
                finally:
                    with self.lock:
                        self.pending -= 1
            _STORE_POOL.submit(job)
        except Exception as exc:  # noqa: BLE001
            self.fail("segment register", exc)

    @staticmethod
    def _single(road):
        return str(road or "") in system3_tables.LINE_ROADS

    def segments_view(self, since=0.0, limit=40, until=0.0):
        """The segments the script went through, in its own order, each with the
        conversations that went out in it: their road, whether a round or a single
        line, their times and line counts. Reader thread only."""
        rows = self.store.segments_since(since, limit, until)
        summ = self.store.summaries([c["conversation_id"] for r in rows for c in r["conversations"]])
        for r in rows:
            for c in r["conversations"]:
                s = summ.get(c["conversation_id"]) or {}
                c.update({"road": s.get("road"), "mode": s.get("mode"), "status": s.get("status"),
                          "created": s.get("created"), "turns": s.get("turns"), "verdict": s.get("verdict"),
                          "topic": system3.label_cut(s.get("topic") or "", 120), "single": self._single(s.get("road")),
                          "lines": len(c.get("line_ids") or []), "held": bool(s)})
                c.pop("line_ids", None)
            r["rounds"] = sum(1 for c in r["conversations"] if c.get("held") and not c["single"])
            r["singles"] = sum(1 for c in r["conversations"] if c.get("held") and c["single"])
        return rows

    def _segment_conv(self, conv, mine, full=False):
        """One conversation as the segment's trace needs it: what planned it and
        when, the structure it was built from, its round-level rolls (the length,
        the variant, the tempers, the shock beat, the events, the station's own
        rolls...), each turn with its rolls, and the lines it has in this segment."""
        ident = conv.get("identity") or {}
        road = str(ident.get("road_kind") or "")
        comp = self._compact(conv)
        events = conv.get("decision_events") or []
        pre = [e for e in events if not e.get("turn_id") and not e.get("stage") and e.get("kind") != "observation"]
        st = conv.get("road_structure") or conv.get("call_structure") or {}
        inputs = conv.get("inputs") or {}
        length = conv.get("length_roll") or {}
        lines_here = set(mine.get("line_ids") or [])
        by_turn = {}
        for ln in conv.get("lines") or []:
            if ln.get("line_id") in lines_here and ln.get("turn_id"):
                by_turn.setdefault(ln["turn_id"], []).append(ln["line_id"])
        turns = []
        for t in conv.get("turns") or []:
            ct = dict(comp["turns"].get(t["turn_id"]) or {})
            ct.update({"turn_id": t["turn_id"], "index": t.get("index"), "leg": t.get("leg") or t.get("step"),
                       "text": str(t.get("text") or "")[:400], "status": t.get("status"),
                       "lines": by_turn.get(t["turn_id"], [])})
            turns.append(ct)
        out = {"conversation_id": ident.get("conversation_id"), "road": road, "mode": conv.get("mode"),
               "status": conv.get("status"), "created": conv.get("created"), "single": self._single(road),
               "topic": system3.label_cut((conv.get("subject") or {}).get("topic") or "", 240),
               "planned_in": ident.get("segment") or {}, "prepared_for": ident.get("system2_slot_id") or "",
               "bank": bool(inputs.get("bank")),
               "structure": {"id": st.get("id") or ("banter_cycle" if road == "banter" else road),
                             "version": st.get("version"), "variant": (conv.get("variant_roll") or {}).get("structure")},
               "length": ({k: length.get(k) for k in ("turns", "lo", "hi", "rolled")} if length else None),
               "rolls": [self._compact_roll(e) for e in pre], "events": len(events),
               "turns": turns, "verdict": (conv.get("validation") or {}).get("verdict"),
               "first_block": mine.get("first_block"), "blocks": mine.get("blocks") or [],
               "line_ids": sorted(lines_here), "lines": len(lines_here),
               "line_choice": conv.get("line_choice"), "sheet": str((conv.get("plan") or {}).get("sheet") or "")[:6000]}
        if full:
            out["conversation"] = self.line_media(json.loads(json.dumps(conv, default=str)))
        return out

    def segment_view(self, seg_id, full=False):
        """Everything the register holds to trace one segment: its entry and
        window, its blocks in the script's order, each conversation that went out
        in it (with `full`, the whole conversation as /api/system3/conversation
        serves it), what System2 had written for it, and the segments either side.
        None when the register has never seen it. Reader thread only."""
        rec = self.store.segment_record(seg_id)
        if not rec:
            return None
        seg = rec["segment"]
        convs = []
        for mine in rec["conversations"][:60]:
            conv = self.store.conversation(mine["conversation_id"])
            if not conv:
                convs.append({"conversation_id": mine["conversation_id"], "gone": True,
                              "why": "past retention (System 3 keeps seven days)",
                              "first_block": mine.get("first_block"), "lines": len(mine.get("line_ids") or [])})
                continue
            convs.append(self._segment_conv(conv, mine, full=full and len(convs) < 24))
        prepared = []
        if seg.get("engine") == "system2" or ":" in str(seg.get("id") or ""):
            prepared = [{k: s.get(k) for k in ("conversation_id", "road", "mode", "status", "created", "turns",
                                               "topic", "verdict")}
                        for s in self.store.prepared_for(seg["id"], float(seg.get("start") or 0) - 86400)]
        return {"segment": seg, "registered": True, "blocks": rec["blocks"], "conversations": convs,
                "rounds": sum(1 for c in convs if not c.get("gone") and not c.get("single")),
                "singles": sum(1 for c in convs if not c.get("gone") and c.get("single")),
                "prepared_for": prepared, "previous": rec["previous"], "next": rec["next"]}

    @staticmethod
    def _trim_entry(e):
        """A director's room entry, without the bulk: what the plan bound to it,
        its state, the direction and review in force, its orchestration."""
        if not isinstance(e, dict):
            return None
        out = {k: e.get(k) for k in ("ordinal", "kind", "label", "slot_id", "occurrence", "minutes", "start",
                                     "deadline", "state", "own_seconds", "aired_seconds", "notes", "prompt_id",
                                     "flow", "flow_prompt", "direction", "review", "orchestration")}
        out["prompt"] = str(e.get("prompt") or "")[:1600]
        script = e.get("script") if isinstance(e.get("script"), dict) else {}
        out["script"] = {k: v for k, v in script.items() if k not in ("turns", "beats")}
        out["script"]["turns"] = [{k: (str(v)[:240] if isinstance(v, str) else v) for k, v in t.items()}
                                  for t in (script.get("turns") or [])[:40] if isinstance(t, dict)]
        aired = e.get("aired") or []
        out["aired"] = {"count": len(aired), "first": [
            {k: r.get(k) for k in ("at", "who", "kind", "round", "line", "seconds")} for r in aired[:12]]}
        out["beats"] = len(e.get("beats") or [])
        return out

    async def segment_scheduling(self, seg):
        """The segment's own scheduling decision, as the station's director holds
        it: the entry in the hour's room (what the plan bound to it, its state -
        aired, went by with another road's material, planned - the direction and
        review in force, its orchestration) and the census of its road (the first
        test each held row fails). Both are read NOW - a room keeps the hours
        System2 still plans, and a census is today's shelf - and the answer says
        so. Bounded; a road that cannot answer says why, never raises."""
        seg = seg or {}
        out = {"entry": None, "census": None, "why": [],
               "read_at": time.time(), "note": "the director's room and census as they stand now"}
        room_of = getattr(self.host, "director_room", None)
        why_of = getattr(self.host, "director_why", None)
        occ = str(seg.get("id") or "")
        hour = occ.split(":", 1)[0] if occ.startswith("hour-") else ""

        async def read(fn, *args):
            return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout=15.0)

        if callable(room_of):
            try:
                room = await read(room_of, 0)
                tried = {0}
                if hour and str(room.get("hour") or "") != hour and str(room.get("hour") or "").startswith("hour-"):
                    try:
                        here = int(str(room["hour"]).split("-", 1)[1]) / 1000.0
                        mine = int(hour.split("-", 1)[1]) / 1000.0
                        which = int(round((mine - here) / 3600.0))
                    except (TypeError, ValueError, IndexError):
                        which = 0
                    if which and which not in tried:
                        room = await read(room_of, which)
                for e in room.get("entries") or []:
                    if occ and str(e.get("occurrence") or "") == occ:
                        out["entry"] = self._trim_entry(e)
                        break
                    if (not occ.startswith("hour-") and seg.get("template")
                            and str(e.get("slot_id") or "") == str(seg.get("template"))):
                        out["entry"] = self._trim_entry(e)
                if out["entry"] is None:
                    out["why"].append("the director's room no longer holds this entry (it keeps the hours "
                                      "System2 is still planning) - its hour was %s" % (room.get("hour") or "?"))
                out["hour"] = room.get("hour")
            except Exception as exc:  # noqa: BLE001
                out["why"].append("the director's room could not be read: %s: %s" % (type(exc).__name__, str(exc)[:160]))
        else:
            out["why"].append("this station has no director's room")
        kind = str(seg.get("kind") or "")
        if callable(why_of) and kind:
            try:
                got = await read(why_of, kind)
                if isinstance(got, dict):
                    out["census"] = {k: got.get(k) for k in ("kind", "stock", "pool", "census", "say")}
                    out["census"]["entries"] = list(got.get("entries") or [])[:30]
            except Exception as exc:  # noqa: BLE001
                out["why"].append("the %s census could not be read: %s: %s" % (kind, type(exc).__name__, str(exc)[:160]))
        return out

    @staticmethod
    def line_media(conv):
        """[s3-sfx-roll] The conversation's lines with each board line's rolls
        and poster put back on it (from the COMMIT observations)."""
        if not isinstance(conv, dict) or not conv.get("lines"):
            return conv
        media = {}
        for o in conv.get("observations_air") or []:
            if o.get("family") == "COMMIT" and isinstance(o.get("media"), dict):
                media.update(o["media"])
        for ln in conv["lines"]:
            got = media.get(ln.get("line_id"))
            if isinstance(got, dict):
                ln.update({k: got[k] for k in _LINE_KEEPS if got.get(k)})   # [s3-banks-roll]
        return conv

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
                "label": system3.label_cut(sel.get("label") or sel.get("id") or ""),
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
                "road": conv["identity"].get("road_kind"), "topic": system3.label_cut(conv["subject"].get("topic") or "", 160),
                "turns": turns}

    # [public-door] THE LISTENER DOOR'S CUT OF A ROUND. /api/system3/public/lines
    # answers anybody holding a tune-in link, and _compact() is the DESK's
    # reading (feed_lines, the glass). Measured 2026-09-28, it carried the
    # round's `topic` - for most roads the road's own prompt ("A news moment
    # between records, and it runs like a late-night podcast: ...", the
    # SCHEDULE (#843) entry, the memo's brief, the caller's scene) - an
    # obligated CTS step's label, which is the running order's direction to
    # the writer, a FAV pick's label and reel, which are the operator's own
    # favourites, the speaker box's material file names and the SFX node's
    # intent words. The listener keeps the dice - family, d100, where it
    # landed, the reel it rolled through, the rule - and the turn's shape, cut
    # the way tune_messenger.py cuts the same record for the Messenger.
    LISTENER_FAMILIES = frozenset({"CTS", "ES", "RS", "IRS", "FL", "SPEAKERBOX", "SFX", "SFXGUY",
                                   "TOPIC", "TRACK_TALK", "FAV", "TEMPER", "INTERJECT", "MENTION",
                                   "SHOCK", "LINE"})

    def _listener_compact(self, conv):
        """[public-door] _compact() as the listener door may carry it."""
        comp = self._compact(conv)
        events = {e.get("event_id"): e for e in conv.get("decision_events") or [] if isinstance(e, dict)}
        turns = {}
        for tid, turn in (comp.get("turns") or {}).items():
            rolls = []
            for roll in turn.get("rolls") or []:
                fam = str(roll.get("family") or "")
                if fam not in self.LISTENER_FAMILIES:
                    continue
                ev = events.get(roll.get("event_id")) or {}
                sel = ev.get("selected") if isinstance(ev.get("selected"), dict) else {}
                roll = dict(roll)
                if fam == "FAV" and str(sel.get("id") or "") not in ("", "NONE"):
                    roll.update(label="a favourite", category="", reel=[])
                elif fam == "CTS" and not any(isinstance(st, dict) and st.get("stage") in ("item", "mode")
                                              for st in ev.get("stages") or []):
                    roll.update(label="the step as planned", category="", reel=[])
                rolls.append(roll)
            turns[tid] = dict(turn, rolls=rolls,
                              speakerbox=[{"mode": sb.get("mode")} for sb in turn.get("speakerbox") or []],
                              sfx={k: (turn.get("sfx") or {}).get(k) for k in ("play", "placement")})
        return {"conversation_id": comp.get("conversation_id"), "mode": comp.get("mode"),
                "road": comp.get("road"), "turns": turns}

    def public_lines(self, ids):
        """[{line_id, system3, ...}] for the tune page's feed. Runs on the
        reader thread only; the cache is that thread's alone. [public-door]
        Its own cache: _compact_cached() keeps the desk's reading in
        _public_cache, and a listener must never be answered out of it."""
        cache = self.__dict__.setdefault("_listener_cache", collections.OrderedDict())
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
                hit = (time.time(), self._listener_compact(conv) if conv else None)   # [public-door]
                cache[cid] = hit
                cache.move_to_end(cid)
                while len(cache) > 40:
                    cache.popitem(last=False)
            comp = hit[1]
            if not comp:
                out.append({"line_id": lid, "system3": False})
                continue
            out.append({"line_id": lid, "system3": True, "conversation_id": cid, "mode": comp["mode"],
                        "road": comp["road"],   # [public-door] no topic: the road's prompt
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
            if conv is not None:                                             # [outl-feed] the meter, the reaction
                for o in conv.get("observations_air") or []:
                    if o.get("family") in ("MEASURE", "SFXREACT", "HOLD") and lid in _s3_lines(o):   # [s3-lines]
                        air.append(self._compact_roll(o))
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
        carry = self.carry_now()
        with self.lock:
            open_rounds = len(self.open)
        return {"ready": self.ready, "engine": system3.ENGINE_VERSION, "schema": system3.EVENT_SCHEMA,
                "settings": self.settings, "config_hash": system3.config_hash(self.config),
                # [s3-carry] what the next live round starts from
                "carry": ({"from": carry.get("from"), "road": carry.get("road"), "age": carry.get("age"),
                           "factor": carry.get("factor"), "seats": sorted((carry.get("seats") or {}).keys()),
                           "landing": system3.label_cut((carry.get("landing") or {}).get("text", "")),
                           "tempers": carry.get("tempers")} if carry else None),
                "open_rounds": open_rounds,                                    # [s3-withhold]
                "cast": self.cast_view(),                                       # [s3-cast]
                "road_modes": {r: system3.road_mode(self.settings, r) for r in system3.ROADS},
                "roads": self.roads(),                                           # [s3-roads]
                "events": self.events_view(),                                    # [s3-live-event]
                "metrics": m,
                "capabilities": {
                    "performance": "ES maps to the station's six emotion dimensions, and an ES row's `voice` "
                                   "(tempo, pitch, range, energy, pause, temp) is the station's "
                                   "performance for the line: XTTS takes the tempo as its native speed and the "
                                   "temp as its sampling temperature, F5 the tempo as its speed; perf_apply "
                                   "moves the melody (pitch middle and range, TD-PSOLA), the tempo, the "
                                   "vocal effort (spectral tilt, levelled) and the pauses on every engine's take.",
                    "sfx": "System 3 adds planned clips and intent words; the station's matcher, bans, "
                           "weights, rotation and hourly recency choose every real file.",
                    "speakerbox": "passages are drawn by the station's speakbox_quote (locks, themes, "
                                  "cooldowns, rotation); System 3 rolls the doors and marks."}}

    def cast_view(self):
        """[s3-cast] The two pools as the desk reads them: how many favourites
        and directives, which rest, which directives are spent or expired."""
        now = time.time()
        favs, dirs = 0, []
        for t in (self.config.get("tables") or []):
            if not isinstance(t, dict):
                continue
            for c in t.get("categories") or []:
                for it in c.get("items") or []:
                    if not isinstance(it, dict):
                        continue
                    if t.get("family") == "FAV":
                        favs += 1
                    elif t.get("family") == "DIRECTIVE":
                        with self.lock:
                            aired = int(self.cast["directive_spent"].get(str(it.get("id"))) or 0)
                        until, budget = float(it.get("until") or 0), int(float(it.get("airings") or 0))
                        state = ("expired" if until and until < now else "spent" if budget and aired >= budget
                                 else "off" if it.get("enabled") is False else "live")
                        dirs.append({"id": it.get("id"), "table": t.get("id"), "category": c.get("id"),
                                     "odds": it.get("odds", 1.0), "aired": aired, "state": state})
        with self.lock:
            recent = list(self.cast.get("fav_recent") or [])
        return {"favorites": favs, "fav_recent": recent, "directives": dirs}

    def config_view(self):
        """[s3-roads] The config as the desk sees it: every road's structure
        present (the saved one, else the default), his section defaulted.
        Nothing here is written back until the desk saves it."""
        view = copy.deepcopy(self.config)
        structures = system3.default_config()["structures"]
        structures.update({k: v for k, v in (view.get("structures") or {}).items() if isinstance(v, dict)})
        view["structures"] = structures
        view.setdefault("sfxguy", copy.deepcopy(system3.DEFAULT_SFXGUY))
        view["split"] = system3.split_config(self.config)                        # [s3-split] the section in force
        view["blocks"] = system3.block_rules(self.config)                  # [s3-blocks] every rule, defaults included
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


# [s3-unmark] the station's prompt-block markers (app.py _pb): a block's name
# between U+E000 and U+E001, and U+E002 closing it
_MARKS = re.compile("\ue000[a-z0-9_]{1,40}\ue001|\ue002")


def _unmark(text):
    return _MARKS.sub("", str(text or ""))


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
    namespace["system3_tint_turns"] = rt.tint_turns              # [s3-rewrite]
    namespace["system3_tint_turns_entry"] = rt.tint_turns_entry
    namespace["system3_repair_roll"] = rt.repair_roll
    namespace["system3_room_allowed"] = rt.room_allowed
    namespace["system3_repair_clause"] = rt.repair_clause
    namespace["system3_director"] = rt.director
    namespace["system3_bind_entry"] = rt.bind_entry
    namespace["system3_perf_state"] = rt.perf_state
    namespace["system3_perf_voice"] = rt.perf_voice                  # [s3-es-voice]
    namespace["system3_perf_of_stamp"] = rt.perf_of_stamp            # [es-roads]
    namespace["system3_sfx_direction"] = rt.sfx_direction
    namespace["system3_sfx_observe"] = rt.sfx_observe
    # [s3-roads] the SFX Guy's node at air, and the single-voice roads

    async def system3_direct_line(**ctx):
        return await rt.direct_line(ctx)

    namespace["system3_turn_id_for"] = rt.turn_id_for               # [s3-link]
    namespace["system3_sfxguy_direction"] = rt.sfxguy_direction
    namespace["system3_sfxguy_chooser"] = rt.sfxguy_chooser
    namespace["system3_sfxguy_spoke"] = rt.sfxguy_spoke
    namespace["system3_scaffold_strip"] = rt.strip_scaffold                 # [s3-scaffold]
    namespace["system3_direction_echo"] = rt.direction_echo                 # [s3-echo]
    namespace["system3_direct_line"] = system3_direct_line
    namespace["system3_bind_line"] = rt.bind_line
    namespace["system3_link_line"] = rt.link_spoken                  # [s3-line-link]
    namespace["system3_line_chapter"] = rt.line_chapter
    namespace["system3_line_chapter_state"] = rt.line_chapter_state      # [s3-chain]
    namespace["system3_observe_ledger"] = rt.observe_ledger
    namespace["system3_segment_block"] = rt.segment_block              # [s3-segment]
    namespace["system3_withhold"] = rt.withhold                        # [s3-withhold]
    namespace["system3_turn_gate"] = rt.turn_gate                      # [s3-turnchain]
    namespace["system3_turn_gate_next"] = rt.turn_gate_next
    namespace["system3_turn_gate_reply"] = rt.turn_gate_reply
    namespace["system3_turn_gate_done"] = rt.turn_gate_done
    namespace["system3_beat_gate"] = rt.beat_gate
    namespace["system3_line_copies"] = rt.line_copies
    namespace["system3_line_gate"] = rt.line_gate
    namespace["system3_favorite"] = rt.favorite_set                    # [s3-cast]
    namespace["system3_pinned_source"] = rt.pinned_source              # [s3-source]
    namespace["system3_chance"] = rt.chance                            # [s3-dice-door]
    namespace["system3_pool"] = rt.pool
    namespace["system3_pool_items"] = rt.pool_items                    # [s3-offer]
    namespace["system3_pick"] = rt.pick
    namespace["system3_roll"] = rt.roll
    namespace["system3_last_roll"] = rt.last_roll                      # [s3-sfx-roll]
    namespace["system3_roll_to"] = rt.roll_to                          # [s3-banks-roll]
    namespace["system3_dice_live"] = rt._dice_live
    namespace["system3_blocks"] = rt.blocks                            # [s3-blocks]
    namespace["system3_note_prompt"] = rt.note_prompt
    namespace["system3_memory_block"] = rt.memory_block                # [s3-memory]
    namespace["system3_event_facts"] = rt.event_facts_text             # [s3-live-event]
    namespace["system3_manager_topic"] = rt.manager_topic              # [s3-mgrtopics]
    namespace["system3_writing_for"] = _S3_WRITE
    namespace["system3_split_line"] = rt.split_line                    # [s3-split]
    namespace["system3_note_pace"] = rt.note_pace
    namespace["system3_injected_node"] = rt.injected_node          # [s3-inject] the honest forced card
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

        async def sweep():
            # [s3-withhold] planned rounds nobody bound are filed as abandoned
            await asyncio.sleep(120)
            while True:
                try:
                    filed = await asyncio.get_running_loop().run_in_executor(_STORE_POOL, rt.sweep_open)
                    if filed:
                        rt.log("System 3 filed %d planned round(s) as abandoned - never bound" % filed)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    rt.fail("abandon sweep", exc)
                await asyncio.sleep(ABANDON_SWEEP)
        holder["sweep"] = asyncio.create_task(sweep(), name="system3:sweep")

    @app.on_event("shutdown")
    async def stop_system3():
        for key in ("task", "sweep"):
            task = holder.get(key)
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

    @app.get("/api/system3/prompt-blocks")
    async def prompt_blocks(digest: str = "", authorization: str | None = Header(default=None)):
        """[s3-blocks] What System 3 decided for each block of one prompt (by the
        digest of the words sent), and the rules every block is decided by."""
        host.require_read_auth(authorization)
        with rt.lock:
            got = rt.prompt_blocks.get(str(digest)) if digest else None
        return {"prompt": got, "rules": system3.block_rules(rt.config)}

    @app.post("/api/system3/prompt-blocks")
    async def prompt_blocks_for_text(request: Request, authorization: str | None = Header(default=None)):
        """[s3-blocks] The same, found by the words of the prompt itself (the page
        holds the request; the digest is taken here, as the writer's door took it)."""
        host.require_read_auth(authorization)
        raw = body_json(await request.body())
        text = str((raw or {}).get("text") or "")
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16] if text else ""
        with rt.lock:
            got = rt.prompt_blocks.get(digest) if digest else None
        return {"digest": digest, "prompt": got, "rules": system3.block_rules(rt.config)}

    @app.get("/api/system3/station")
    async def station_rolls(limit: int = 120, authorization: str | None = Header(default=None)):
        """[s3-dice-door] the station's own rolls, newest last, and the rows still being added."""
        host.require_read_auth(authorization)
        with rt.lock:
            pending = {k: sorted(v) for k, v in rt.dice_pending.items()}
        return {"rolls": rt.station_view(max(1, min(400, int(limit)))), "pending": pending}

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
        fams = {t["family"] for t in config["tables"]
                if t.get("enabled", True) and not t.get("event")}   # [s3-live-event]
        missing = [f for f in ("ES", "RS", "IRS", "FL", "CTS") if f not in fams]
        if missing:
            raise HTTPException(400, "that would leave no enabled table for " + ", ".join(missing))
        return {"hash": await save_config(config, "removed table %s" % table_id)}

    @app.get("/api/system3/graph/template")
    async def conversation_graph_template(road: str = "", authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        import conversation_graph
        if road:
            # [nodeplan] "start from this road's own segment": the chapter
            # derived from the road's CURRENT structure, never the stored graph
            st = system3.road_structure(rt.config, str(road).partition("~")[0])
            if not st:
                raise HTTPException(404, "no road called %s" % road)
            return {"graph": conversation_graph.road_graph(road, st)}
        return {"graph": conversation_graph.default_graph()}

    @app.get("/api/system3/graph/presets")
    async def conversation_graph_presets(authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        return {"presets": await rt.read(rt.store.graph_presets)}

    @app.put("/api/system3/graph/presets/{name}")
    async def save_conversation_graph_preset(name: str, request: Request,
                                             authorization: str | None = Header(default=None)):
        host.require_auth(authorization)
        import conversation_graph
        name = " ".join(name.split())[:64]
        if not name:
            raise HTTPException(400, "the preset needs a name")
        raw = body_json(await request.body())
        graph = conversation_graph.normalize(raw.get("graph"))
        if not graph["nodes"]:
            raise HTTPException(400, "the preset needs nodes")
        problems = conversation_graph.validate(graph)
        if problems:
            raise HTTPException(400, "; ".join(problems))
        await asyncio.get_running_loop().run_in_executor(_STORE_POOL, rt.store.save_graph_preset, name, graph)
        return {"name": name, "graph": graph}

    @app.delete("/api/system3/graph/presets/{name}")
    async def delete_conversation_graph_preset(name: str,
                                               authorization: str | None = Header(default=None)):
        host.require_auth(authorization)
        deleted = await asyncio.get_running_loop().run_in_executor(_STORE_POOL, rt.store.delete_graph_preset, name)
        if not deleted:
            raise HTTPException(404, "no graph preset %s" % name)
        return {"deleted": name}

    @app.post("/api/system3/graph/preview")
    async def conversation_graph_preview(request: Request, authorization: str | None = Header(default=None)):
        """Dry run a graph with System 3's real decision tables and dice."""
        host.require_auth(authorization)
        import conversation_graph
        raw = body_json(await request.body())
        graph = conversation_graph.normalize(raw.get("graph"))
        if not graph["nodes"]:
            raise HTTPException(400, "the graph needs at least one node")
        problems = conversation_graph.validate(graph)
        if problems:
            raise HTTPException(400, "; ".join(problems))
        if graph["nodes"][0]["type"] == "protocol":
            return {"turns": [], "rolls": [], "protocol": graph["nodes"][0].get("protocol_road") or raw.get("road"),
                    "estimated_seconds": 0, "budget_seconds": raw.get("seconds") or 180}
        seconds = max(20, min(3600, float(raw.get("seconds") or 180)))
        turns = max(2, min(60, int(raw.get("turns") or round(seconds / 15))))
        road = str(raw.get("road") or "banter")
        config = copy.deepcopy(rt.config)
        config["structure"]["graph"] = graph
        inputs = {"road": road, "seats": ["A", "B", "D"],
                  "names": {"A": "Host", "B": "Co-host", "D": "Third chair", "C": "Caller"},
                  "turns": turns, "target_seconds": seconds,
                  "subject": {"topic": str(raw.get("topic") or "")[:300]},
                  "availability": {}, "speakerbox_rates": {}, "sfxguy": {"voice": False},
                  "graph_caller_available": bool(raw.get("caller_available"))}
        conv = system3.new_conversation(inputs, config, rt.settings,
                                        seed=str(raw.get("seed") or "graph-preview")[:80])
        system3.plan_graph(conv, config, graph, until=turns, road=road)
        return {"turns": [{"node": t.get("graph_node"), "type": t.get("graph_type"),
                           "speaker": t.get("speaker"), "name": t.get("name"),
                           "work": t.get("protocol"), "emotion": (t.get("performance") or {}).get("emotion")}
                          for t in conv["turns"]],
                "rolls": [{"node": (e.get("meta") or {}).get("node"),
                           "kind": (e.get("stages") or [{}])[0].get("stage"),
                           "selected": (e.get("selected") or {}).get("id"),
                           "dice": (e.get("rng") or {}).get("dice"),
                           "candidates": (e.get("stages") or [{}])[0].get("candidates")}
                          for e in conv["decision_events"] if e.get("family") == "GRAPH"],
                "estimated_seconds": conv.get("graph_profile", {}).get("estimated_seconds", 0),
                "budget_seconds": seconds}

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
            _split_bad = system3_tables.split_problems(st, "step %s" % st.get("id"))   # [s3-split]
            if _split_bad:
                raise HTTPException(400, "; ".join(_split_bad))
            st["speakerbox"] = [m for m in (st.get("speakerbox") or []) if m in ("prepend", "append")]
            for d in st["draws"]:
                if d.get("family") not in ("CTS", "ES", "RS", "IRS", "FL"):
                    raise HTTPException(400, "unknown family %r" % d.get("family"))
        config = copy.deepcopy(rt.config)
        structure = dict(config["structure"])
        structure.update({k: raw[k] for k in ("steps", "closing", "handoff", "label", "initiator", "source")   # [s3-flow] [s3-source]
                          if k in raw})
        if "graph" in raw:
            import conversation_graph
            structure["graph"] = conversation_graph.normalize(raw["graph"])
            problems = conversation_graph.validate(structure["graph"])
            if any(n["type"] == "protocol" for n in structure["graph"]["nodes"]):
                problems.append("the banter cycle needs dialogue nodes, not a protocol wrapper")
            if problems:
                raise HTTPException(400, "; ".join(problems))
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
        # [s3-window] a variant is "<road>~v<n>": a copy of the road's segment with
        # its own legs, a weight against the base and an on/off switch; the
        # engine rolls which one runs (VARIANT) each time the road goes to air.
        base, sep, _tail = road.partition("~")
        problems = system3_tables.validate_structure(base, raw)
        if problems:
            raise HTTPException(400, "; ".join(problems[:6]))
        config = copy.deepcopy(rt.config)
        held = config.setdefault("structures", system3_tables.default_structures())
        if sep:
            if base not in held and base not in system3.ROADS:
                raise HTTPException(400, "no road called %s to make a variant of" % base)
            mine = dict(held.get(road) or system3.road_structure(config, base) or {})
            mine.update({"id": road, "variant_of": base})
        else:
            mine = dict(system3.road_structure(config, road) or {})
        mine.update({k: raw[k] for k in ("legs", "label", "head", "tail", "material",
                                         "min_turns", "max_turns", "caller_share") if k in raw})
        if "graph" in raw:
            import conversation_graph
            mine["graph"] = conversation_graph.normalize(raw["graph"])
            problems = conversation_graph.validate(mine["graph"])
            if problems:
                raise HTTPException(400, "; ".join(problems))
        if "weight" in raw:
            try:
                mine["weight"] = max(0.0, float(raw.get("weight") or 0))
            except (TypeError, ValueError):
                raise HTTPException(400, "weight must be a number")
        if "enabled" in raw:
            mine["enabled"] = bool(raw.get("enabled"))
        mine["version"] = int(mine.get("version") or 1) + 1
        held[road] = mine
        return {"hash": await save_config(config, "%s structure v%d" % (road, mine["version"])),
                "structure": mine}

    @app.delete("/api/system3/structures/{road}")
    async def delete_road_structure(road: str, authorization: str | None = Header(default=None)):
        """[s3-window] Drop a variant. A road's own structure cannot be deleted
        (reset it from the defaults instead)."""
        host.require_auth(authorization)
        if "~" not in road:
            raise HTTPException(400, "only a variant (road~vN) can be deleted")
        config = copy.deepcopy(rt.config)
        held = config.get("structures") or {}
        if road not in held:
            raise HTTPException(404, "no variant called %s" % road)
        held.pop(road)
        return {"hash": await save_config(config, "%s variant dropped" % road), "deleted": road}

    @app.put("/api/system3/config/section/{name}")
    async def put_section(name: str, request: Request, authorization: str | None = Header(default=None)):
        host.require_auth(authorization)
        if name == "split":                                                    # [s3-split] the split section
            try:
                split = system3.validate_split(body_json(await request.body()))
            except (ValueError, TypeError) as exc:
                raise HTTPException(400, str(exc)) from exc
            config = copy.deepcopy(rt.config)
            config["split"] = split
            return {"hash": await save_config(config, "split section"), "split": split}
        if name not in ("speakerbox", "sfx", "personalities", "sfxguy", "blocks"):   # [s3-blocks]
            raise HTTPException(404, "no section %s" % name)
        raw = body_json(await request.body())
        if not isinstance(raw, dict):
            raise HTTPException(400, "a section is an object")
        if name == "blocks":
            try:
                raw = system3.validate_blocks(raw)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        config = copy.deepcopy(rt.config)
        config[name] = raw
        return {"hash": await save_config(config, "%s section" % name)}

    @app.post("/api/system3/config/reset")
    async def reset_config(authorization: str | None = Header(default=None)):
        host.require_auth(authorization)
        return {"hash": await save_config(system3.default_config(), "reset to defaults")}

    @app.post("/api/system3/es-v2")
    async def es_v2(dry: int = 0, authorization: str | None = Header(default=None)):
        """[es-v2] ES1's second edition, once: ?dry=1 lists what would move and
        what stays as the operator left it; without it, it is done."""
        host.require_auth(authorization)
        return await asyncio.get_running_loop().run_in_executor(_STORE_POOL, rt.upgrade_es_v2, not dry)

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
            _READ_POOL, lambda: json.dumps(rt.line_media(got), default=str))   # [s3-sfx-roll]
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
            with rt.lock:                                                      # [link-now]
                held = rt.pending_links.get(line_id)
            got = dict(held) if held else None
        if not got:
            # [link-now] the station's own record, made the moment the line was
            # spoken (_s3_line_remember) - the store's copy may still be queued
            stamp = (namespace.get("_S3_LINE_BY_ID") or {}).get(str(line_id))
            if isinstance(stamp, dict) and stamp.get("conversation_id"):
                got = {"line_id": str(line_id), "conversation_id": stamp["conversation_id"],
                       "turn_id": stamp.get("turn_id") or None, "who": "", "text": ""}
        if not got:
            raise HTTPException(404, "line %s was not directed by System 3" % line_id)
        conv = await rt.read(rt.store.conversation, got["conversation_id"])
        if not conv:
            with rt.lock:                                                      # [link-now] not written yet
                conv = rt.recent.get(got["conversation_id"])
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
                "decisions": [e for e in conv["decision_events"] if e["event_id"] in ids]
                + [o for o in conv.get("observations_air") or []                  # [outl-tile]
                   if o.get("family") in ("MEASURE", "SFXREACT", "HOLD") and o.get("stages")
                   and (got["line_id"] in _s3_lines(o)   # [s3-lines]
                        or (turn is not None and not o.get("lines") and o.get("turn_id") == turn.get("turn_id")))
                   and not (o.get("family") == "MEASURE" and any(
                       e.get("family") == "MEASURE" and e["event_id"] in ids for e in conv["decision_events"]))],
                "observations": [o for o in conv.get("observations_air") or []
                                 if (turn and o.get("turn_id") == turn.get("turn_id"))
                                 or (got.get("turn_id") and o.get("turn_id") == got["turn_id"])
                                 or got["line_id"] in _s3_lines(o)],   # [s3-lines]
                "conversation": system3.summary(conv)}

    @app.get("/api/system3/segments")
    async def segments(since: float = 0.0, limit: int = 40, until: float = 0.0, plan: int = 0,
                       authorization: str | None = Header(default=None)):
        """[s3-segment] The station's scheduled segments in the script's order (the
        last three hours unless `since` says otherwise), each with the System 3
        conversations that went out in it - rounds and single lines alike - their
        road, times and line counts; the segment on air now; and with `plan=1` the
        hour's entries as the director's room holds them (the ones still to come
        included), for a picker."""
        host.require_read_auth(authorization)
        since = float(since or 0) or (time.time() - 3 * 3600)
        rows = await rt.read(rt.segments_view, since, max(1, min(200, int(limit or 40))), float(until or 0))
        out = {"segments": rows, "now": rt.segment_now(), "since": since, "at": time.time()}
        room_of = getattr(host, "director_room", None)
        if plan and callable(room_of):
            try:
                room = await asyncio.wait_for(asyncio.to_thread(room_of, 0), timeout=15.0)
                out["plan"] = {"hour": room.get("hour"), "entries": [
                    {k: e.get(k) for k in ("ordinal", "kind", "label", "slot_id", "occurrence", "start",
                                           "deadline", "state")} for e in room.get("entries") or []]}
            except Exception as exc:  # noqa: BLE001
                out["plan"] = {"why": "the director's room could not be read: %s" % type(exc).__name__}
        return out

    @app.get("/api/system3/segment/{segment_id}")
    async def segment_trace(segment_id: str, full: int = 0, scheduling: int = 1,
                            authorization: str | None = Header(default=None)):
        """[s3-segment] Everything to trace one scheduled segment: its entry and
        window, its blocks, every conversation that went out in it (`full=1`: each
        whole, decision events and all), what System2 had written for it, the
        segments either side, and its own scheduling decision - the director's
        entry and its road's census. A segment the script has not reached yet (the
        one on air before its first line, one still to come in the director's
        room) answers with no conversations."""
        host.require_read_auth(authorization)
        got = await rt.read(rt.segment_view, segment_id, bool(full))
        if not got and segment_id[:3] in ("sc-", "sh-"):
            # [s3-scene-seg] A script band's id is its SCENE, `sc-<opening
            # line_id>` (#1281/#1284): answer for the segment holding that line.
            _ln = await rt.read(rt.store.line, segment_id[3:])
            if _ln and _ln.get("segment"):
                segment_id = str(_ln["segment"])
                got = await rt.read(rt.segment_view, segment_id, bool(full))
        if not got:
            now = rt.segment_now()
            seg = now if now.get("id") == segment_id else None
            if seg is None:
                room_of = getattr(host, "director_room", None)
                if callable(room_of):
                    for which in (0, 1):
                        try:
                            room = await asyncio.wait_for(asyncio.to_thread(room_of, which), timeout=15.0)
                        except Exception:  # noqa: BLE001
                            break
                        e = next((x for x in room.get("entries") or []
                                  if str(x.get("occurrence") or "") == segment_id), None)
                        if e:
                            seg = {"id": segment_id, "template": str(e.get("slot_id") or ""),
                                   "kind": str(e.get("kind") or ""), "label": str(e.get("label") or ""),
                                   "start": e.get("start"), "ends": e.get("deadline"),
                                   "hour": str(room.get("hour") or ""), "index": e.get("ordinal"),
                                   "engine": "system2"}
                            break
            if seg is None:
                raise HTTPException(404, "no segment %s: System 3's register keeps the segments the script "
                                         "went through for seven days, and the director's room holds this hour "
                                         "and the next" % segment_id)
            got = {"segment": seg, "registered": False, "blocks": [], "conversations": [], "rounds": 0,
                   "singles": 0, "prepared_for": [], "previous": None, "next": None,
                   "why": "nothing of this segment has reached the script yet"}
        if scheduling:
            got["scheduling"] = await rt.segment_scheduling(got["segment"])
        body = await asyncio.get_running_loop().run_in_executor(_READ_POOL, lambda: json.dumps(got, default=str))
        return Response(content=body, media_type="application/json")

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

    @app.post("/api/system3/preview")
    async def preview_conversation(request: Request, authorization: str | None = Header(default=None)):
        """Replan a recorded banter round with current settings and draft it off air.

        The result is returned to the operator only. It never binds a line,
        enters the script ledger, or joins the broadcast queue.
        """
        host.require_auth(authorization)
        raw = body_json(await request.body())
        cid = str(raw.get("conversation_id") or "")[:100]
        source = await rt.read(rt.store.conversation, cid) if cid else None
        if not source:
            raise HTTPException(404, "the source conversation is not in the System 3 ledger")
        if (source.get("identity") or {}).get("road_kind") != "banter":
            raise HTTPException(400, "dialogue preview currently supports banter rounds")
        if not callable(namespace.get("ask_model")):
            raise HTTPException(503, "the station writer is unavailable")
        settings = system3.normalise_settings(dict(rt.settings, mode="active"))
        inputs = copy.deepcopy(source.get("inputs") or {})
        plan = await asyncio.get_running_loop().run_in_executor(
            _READ_POOL, lambda: system3.plan_scene(inputs, rt.config, settings, seed=source.get("seed")))
        plan["mode"] = "simulation"
        plan["status"] = "preview"
        plan["preview_source"] = cid
        plan["plan"] = {"sheet": system3.render_sheet(plan), "active": False}
        dj = namespace["dj_settings"]() if callable(namespace.get("dj_settings")) else {}
        station = namespace["dj_disposition"]() if callable(namespace.get("dj_disposition")) else ""
        persona_fields = {"A": ("host", "persona"), "B": ("cohost", "cohost_persona"),
                          "D": ("third", "third_persona")}
        personas = []
        for seat in inputs.get("seats") or []:
            if seat not in persona_fields:
                continue
            slot, field = persona_fields[seat]
            value = str(dj.get(field) or "").strip()
            if callable(namespace.get("radio_persona")):
                value = namespace["radio_persona"](slot, value)
            if value:
                personas.append("%s persona: %s" % (seat, value[:4000]))
        subject = str((plan.get("subject") or {}).get("topic") or "")[:400]
        prompt = ("Write a draft radio conversation about: %s\n" % subject
                  + "Use the A:/B:/D: speaker labels in the running order. "
                    "Write only the dialogue lines. Each reply must respond to the preceding line.\n"
                  + ("\nStation instructions:\n%s\n" % station if station else "")
                  + ("\n".join(personas) + "\n" if personas else "")
                  + plan["plan"]["sheet"])
        try:
            draft = await asyncio.wait_for(namespace["ask_model"](
                prompt, limit=min(6500, max(1200, len(plan["turns"]) * 320)),
                spice=0.3, mark={"kind": "system3 visual preview"},
                result_contract="structured_turns"), timeout=210)
        except asyncio.TimeoutError as exc:
            raise HTTPException(504, "the preview writer timed out") from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(503, "the preview writer could not complete: %s" % exc) from exc
        rows = namespace["banter_turns"](draft) if callable(namespace.get("banter_turns")) else []
        matched = 0
        for turn, row in zip(plan["turns"], rows):
            if str(row[0]) != str(turn["speaker"]):
                break
            turn["text"] = str(row[1])[:1500]
            turn["status"] = "preview"
            matched += 1
        model_settings = namespace["load_settings"]() if callable(namespace.get("load_settings")) else {}
        plan["preview_call"] = {
            "at": time.time(), "model": str(model_settings.get("model") or ""),
            "purpose": "system3 visual preview", "state": "done", "wire_exact": False,
            "layers": {"station": station, "personas": personas},
            "request": {"model": str(model_settings.get("model") or ""),
                        "messages": [{"role": "user", "content": prompt}]},
            "response": {"message": {"content": str(draft or "")}},
            "matched_turns": matched, "planned_turns": len(plan["turns"])}
        return plan

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

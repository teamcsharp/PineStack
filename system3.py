"""System 3: the conversation director.

"The LLM writes the words. System 3 decides what kind of conversational
action should happen." (docs/system3_blueprint.md section 1)

This module is the pure engine and knows nothing about the station. It
holds the one thing the architecture snapshot found missing - an
authoritative conversation aggregate with a state machine - plus the
seeded RNG and decision ledger that make every choice inspectable:

    new_conversation()  -> the System3Conversation aggregate (section 3)
    plan_more()         -> Mode A, the planned scene: every turn's
                           CTS/ES/RS/IRS/FL, Speakerbox and SFX decision,
                           drawn from the versioned tables (section 7)
    observe()/replan()  -> Mode B, turn by turn: validate what was
                           written, update the state, decide the next turn
    render_sheet()      -> the structured intent, as the running order the
                           existing writer already follows (#1386 format)
    validate()          -> deterministic compliance of a written script
    replay()            -> decision replay from state/config/version/seed

Every weighted draw writes a System3DecisionEvent holding the candidate
set, each candidate's effective weight and why, the raw random value, the
selection and the state before and after. Nothing here reads a clock for
a decision, touches a file or awaits anything: the planner is CPU-only and
bounded, so the host can call it on the event loop.
"""
from __future__ import annotations

import copy
import difflib
import hashlib
import json
import math
import re
import time
import uuid

import system3_tables

ENGINE_VERSION = "system3-engine/3"
EVENT_SCHEMA = "system3.decision-event/1"
CONVERSATION_SCHEMA = "system3.conversation/1"
CONFIG_SCHEMA = "system3.config/1"

MODES = ("off", "shadow", "active_selected_roads", "active")
# [s3-roads] every conversation road System 3 directs. The register of ALL
# roads, directed or queued, is system3_tables.ROAD_REGISTER.
ROADS = ("banter", "caller", "recap", "ad", "news", "manager", "memo", "gallery",
         "mixtape", "open_show", "fan_mail", "guest",
         # single-voice roads planned as one-seat legs (system3_direct_line)
         "track_talk", "station_id", "upstairs", "interject", "ad_spot",
         # [s3-lines] the single lines dj_speak still spoke outside a road
         "reply", "request", "open", "aside")
FAMILIES = ("CTS", "ES", "RS", "IRS", "FL", "SPEAKERBOX", "SFX", "TOPIC", "SFXGUY", "LINE", "LENGTH", "TRACK_TALK",
            "TEMPER", "SHOCK", "INTERJECT", "MENTION", "CARRY",          # [s3-rounds] [s3-carry]
            "TINT", "REPAIR", "ROOM",                                    # [s3-rewrite]
            "FAV", "DIRECTIVE",                                          # [s3-cast]
            "EVENT",                                                     # [s3-events]
            "STATION",                                                   # [s3-dice-door]
            "BLOCK")                                                     # [s3-blocks]
PHASES = ("OPEN", "ESTABLISH", "DEVELOP", "ESCALATE", "EXPLORE", "WILDCARD",
          "RESOLVE", "WRAP", "SEGUE")
SPEAKERBOX_MODES = ("NONE", "PREPEND", "APPEND", "FULL_SWATH", "REFERENCE",
                    "CALLBACK_TO_PRIOR")
GENERATION_MODES = ("batch", "turn")
# The station's six performance dimensions (app.py EMOTION_DIMS). Kept
# here, not imported, so the engine stays free of the host.
EMOTION_DIMS = ("amusement", "excitement", "confusion", "irritation",
                "fatigue", "nervousness")
DYNAMICS = ("tension", "agreement", "energy", "novelty", "repetition_risk",
            "closure_pressure", "topic_exhaustion")

# Operator controls (blueprint section 14). 0.5 is neutral: a control
# multiplies the weight of every outcome carrying its tag by 4**(c-0.5),
# i.e. between x0.5 and x2, so it moves documented weights, never prose.
DEFAULT_CONTROLS = {
    "emotional_volatility": 0.5,
    "disagreement": 0.5,
    "escalation": 0.5,
    "tangent": 0.5,
    "callback": 0.5,
    "speakerbox_density": 0.5,
    "sfx_aggression": 0.5,
    "novelty": 0.5,
    "closure_aggressiveness": 0.5,
    # [rng-topics] how often something off the operator's topics board
    # comes up: rate = TOPIC_RATE_AT_FULL x this (0.5 -> 40% of rounds).
    "topics": 0.5,
    # [s3-rounds] the shock beat, the interjections forced in edgewise and the
    # station-name mention: rate = <FAMILY>_RATE_AT_FULL x this
    "shock_beat": 0.5,
    "interjections": 0.5,
    "track_talk": 0.5,
    "mention": 0.5,
    # [s3-rewrite] the passes after the write, as odds: which lines the
    # crystal tint may rhyme, whether a round that missed its target is
    # sent back, whether the Writers' Room may touch it later
    "tint": 0.5,
    "repair": 0.5,
    "room": 0.5,
    # [s3-cast] how often a line the operator liked comes up (FAV1): the
    # dice's own odds, per round and per single line - 0.25 is one in four
    "favorites": 0.25,
}
TAG_CONTROLS = {"disagreement": "disagreement", "escalation": "escalation",
                "tangent": "tangent", "callback": "callback",
                "novelty": "novelty", "closure": "closure_aggressiveness"}
# Tags pulled the other way by a control ("agreement" falls as the
# disagreement dial rises).
TAG_INVERSE = {"agreement": "disagreement"}

DEFAULT_SETTINGS = {
    "mode": "shadow",
    "roads": ["banter"],
    "test_seed": "",
    "generation_mode": "batch",
    "debug_verbosity": "normal",
    "repair": True,
    "controls": dict(DEFAULT_CONTROLS),
}

DEFAULT_SPEAKERBOX = {
    # Mode weights for a hit on a marked turn. A verbatim hit becomes
    # PREPEND or APPEND according to the mark that rolled it.
    "modes": {"verbatim": 1.0, "reference": 1.0, "callback": 0.6},
    "max_inline": 2,
    "passage_chars": 420,
    # The full-swath dial under System 3: an opening speaker-box monologue
    # (CTS1 "Speaker-box Quote / Monologue") read by the initiator.
    "monologue_chars": 700,
}
DEFAULT_SFX = {
    # Probability of a planned clip at aggression 0 and at 1; the
    # station's own two-line cadence (sfx_every_units) is the floor and is
    # never reduced by anything here.
    "p_low": 0.08, "p_high": 0.7,
    "first_exchange": True,
    "arousal_boost": 0.3,
    "humor_boost": 0.15,
}
DEFAULT_SFXGUY = {
    # [s3-roads] THE SFX GUY'S MOUTH AS A NODE. On every host turn he rolls
    # whether he pipes up, at the desk's own dial (sfxguy_rate, per host
    # statement - the number is System 3's now, and recorded), then what
    # kind of line: a story off the wire, a reaction fired back at this very
    # line (the shed, at the sfxguy_warp dial), or a saying off his shelf.
    # The line itself is drawn at air from the first kind that has one, in
    # the order the roll set, with the real candidates recorded.
    "news_share": 0.15,
    "reaction_by_warp": True,       # reaction weight = sfxguy_warp / 100
    "reaction_share": 0.35,         # used when reaction_by_warp is false
    "rate_by_dial": True,           # the SPEAK threshold = sfxguy_rate / 100
    "rate": 0.4,                    # used when rate_by_dial is false
    "never_over_callers": True,     # the station's rule: he heckles the hosts
}
SECONDS_PER_WORD = 0.4          # 150 wpm; recalibrated from rendered audio
TOPIC_RATE_AT_FULL = 0.8        # [rng-topics] the TOPIC dice at topics = 1.0
# [s3-rounds] the round-level rolls that replaced dj_banter's prompt randoms:
# the odds at a control of 1.0 (0.5, the default, halves them - which is the
# legacy 30% for the station-name mention and one shock beat in two rounds).
SHOCK_RATE_AT_FULL = 1.0
INTERJECT_RATE_AT_FULL = 1.0
MENTION_RATE_AT_FULL = 0.6
TINT_RATE_AT_FULL = 1.0          # [s3-rewrite] control 1.0 = every turn may be rhymed
REPAIR_RATE_AT_FULL = 1.0
ROOM_RATE_AT_FULL = 1.0
HOST_SEATS = ("A", "B", "D")
# [s3-carry] how long a round's ending state carries into the next round's
# start (linear decay to nothing at the window)
CARRY_WINDOW = 1200.0


def clamp(value, low=0.0, high=1.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return low
    if math.isnan(value):
        return low
    return max(low, min(high, value))


_SENTENCE_END = re.compile(r"[.!?\u2026][\"\u201d')\]]*\s")


def sentence_cut(text, cap):
    """[s3-cut] `text` cut to at most `cap` characters at a sentence end;
    failing a sentence end past a quarter of the cap, at a clause break; failing
    that, at a word. A passage the writer is told to read out word for word
    must not stop where a character count fell - that is what a line
    "stopping short of saying the full phrase" is. Whitespace is folded."""
    words = " ".join(str(text or "").split())
    cap = int(cap or 0)
    if cap <= 0 or len(words) <= cap:
        return words
    head = words[:cap + 1]
    floor = int(cap * 0.25)
    best = -1
    for m in _SENTENCE_END.finditer(head):
        if m.end() - 1 <= cap:
            best = m.end() - 1
    if best >= floor:
        return head[:best].rstrip()
    clause = max(head.rfind(", ", 0, cap), head.rfind("; ", 0, cap), head.rfind(": ", 0, cap))
    if clause >= floor:
        return head[:clause].rstrip(",;: ")
    space = head.rfind(" ", 0, cap)
    return head[:space if space > 0 else cap].rstrip()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest(value, size=16):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()[:size]


# --- configuration ---------------------------------------------------------

BLOCK_KINDS = ("obligation", "roll", "tint", "off")


def default_config():
    return {"schema": CONFIG_SCHEMA,
            "tables": system3_tables.default_tables(),
            "structure": system3_tables.default_structure(),
            # [s3-calls] one structure per road System 3 builds from its own nodes
            "structures": system3_tables.default_structures(),
            "speakerbox": copy.deepcopy(DEFAULT_SPEAKERBOX),
            "sfx": copy.deepcopy(DEFAULT_SFX),
            # [s3-roads] the SFX Guy's mouth
            "sfxguy": copy.deepcopy(DEFAULT_SFXGUY),
            # [s3-blocks] every block a writer prompt may carry, and what it is
            "blocks": system3_tables.default_blocks(),
            "personalities": {}}


def config_hash(config):
    keys = ("schema", "tables", "structure", "speakerbox", "sfx", "personalities")
    # [s3-calls] a config saved before road structures keeps its hash
    if "structures" in config:
        keys += ("structures",)
    if "sfxguy" in config:                       # [s3-roads]
        keys += ("sfxguy",)
    if "blocks" in config:                       # [s3-blocks]
        keys += ("blocks",)
    return digest({k: config.get(k) for k in keys})


def normalise_settings(raw):
    raw = raw if isinstance(raw, dict) else {}
    out = copy.deepcopy(DEFAULT_SETTINGS)
    mode = str(raw.get("mode") or out["mode"]).lower()
    out["mode"] = mode if mode in MODES else out["mode"]
    roads = raw.get("roads", out["roads"])
    out["roads"] = [r for r in (roads if isinstance(roads, list) else []) if r in ROADS]
    out["test_seed"] = str(raw.get("test_seed") or "")[:64]
    gen = str(raw.get("generation_mode") or "batch").lower()
    out["generation_mode"] = gen if gen in GENERATION_MODES else "batch"
    verb = str(raw.get("debug_verbosity") or "normal").lower()
    out["debug_verbosity"] = verb if verb in ("quiet", "normal", "full") else "normal"
    out["repair"] = bool(raw.get("repair", True))
    controls = raw.get("controls") if isinstance(raw.get("controls"), dict) else {}
    out["controls"] = {k: round(clamp(controls.get(k, v)), 3) for k, v in DEFAULT_CONTROLS.items()}
    return out


def road_mode(settings, road):
    """What System 3 is for this road right now: off, shadow or active."""
    mode = settings.get("mode")
    if mode == "off" or road not in ROADS:
        return "off"
    if mode == "active":
        return "active"
    if mode == "active_selected_roads":
        return "active" if road in (settings.get("roads") or []) else "shadow"
    return "shadow"


def validate_table(table):
    """Refuse a table that cannot be drawn from; returns the cleaned copy."""
    if not isinstance(table, dict):
        raise ValueError("a table is an object")
    tid = str(table.get("id") or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,23}", tid):
        raise ValueError("table id must be a short name such as ES2")
    family = str(table.get("family") or "")
    if family not in ("CTS", "ES", "RS", "IRS", "FL", "TEMPER", "SHOCK", "INTERJECT", "FAV", "DIRECTIVE", "EVENT",
                      "CHANCE", "POOL"):
        raise ValueError("table family must be one of CTS, ES, RS, IRS, FL, TEMPER, SHOCK, INTERJECT, FAV, DIRECTIVE, "
                         "EVENT, CHANCE, POOL")
    pool = family in system3_tables.POOL_FAMILIES          # [s3-cast] may stand empty
    cats = table.get("categories")
    if not isinstance(cats, list) or (not cats and family not in ("CHANCE", "POOL")):   # [s3-dice-door] filled as the station rolls
        raise ValueError("a table needs at least one category")
    seen = set()
    out = copy.deepcopy(table)
    out["id"], out["family"] = tid, family
    out["weight"] = max(0.0, float(table.get("weight", 1.0) or 0))
    out["enabled"] = bool(table.get("enabled", True))
    out["version"] = int(table.get("version") or 1)
    if family == "EVENT":                                    # [s3-events] where it rolls, how many at most
        out["roads"] = [str(r) for r in (table.get("roads") or []) if str(r) in ROADS]
        out["max_events"] = max(0, min(8, int(float(table.get("max_events", 2) or 0))))
    for cat in out["categories"]:
        if not isinstance(cat, dict) or not str(cat.get("id") or "").strip():
            raise ValueError("every category needs an id")
        cat["weight"] = max(0.0, float(cat.get("weight", 1.0) or 0))
        if family == "EVENT":                                # [s3-events] one kind of happening
            cat["odds"] = round(clamp(cat.get("odds", 0.1)), 4)
            cat["seat"] = str(cat.get("seat") or "any") if str(cat.get("seat") or "any") in EVENT_SEATS else "any"
            cat["place"] = str(cat.get("place") or "middle") if str(cat.get("place") or "middle") in EVENT_PLACES else "middle"
            cat["ends"] = bool(cat.get("ends", False))
        items = cat.get("items")
        if not isinstance(items, list) or (not items and not pool):
            raise ValueError("category %s has no items" % cat["id"])
        for item in items:
            if not isinstance(item, dict) or not str(item.get("id") or "").strip():
                raise ValueError("every item needs an id")
            key = (cat["id"], item["id"])
            if key in seen:
                raise ValueError("duplicate item %s/%s" % key)
            seen.add(key)
            item["weight"] = max(0.0, float(item.get("weight", 1.0) or 0))
            item.setdefault("label", item["id"])
            if family == "DIRECTIVE":                       # [s3-cast] the row's own odds and lifetime
                item["odds"] = round(clamp(item.get("odds", 1.0)), 4)
                item["until"] = max(0.0, float(item.get("until") or 0))
                item["airings"] = max(0, int(float(item.get("airings") or 0)))
                if not str(item.get("text") or "").strip():
                    raise ValueError("directive %s says nothing" % item["id"])
            if family == "FAV" and not str(item.get("text") or "").strip():
                raise ValueError("favourite %s has no words" % item["id"])
            if family == "CHANCE":                           # [s3-dice-door] a station roll's odds
                item["odds"] = round(clamp(item.get("odds", 0.5)), 4)
            if family == "POOL" and not str(item.get("text") or "").strip():
                raise ValueError("option %s of pool %s says nothing" % (item["id"], cat["id"]))
    return out


# --- the RNG ---------------------------------------------------------------

class DrawStream:
    """One conversation's random numbers, reproducible from its root seed.

    Draw n is sha256(root|n|label), so the same seed, the same config and
    the same sequence of questions give the same answers - that is the
    whole of decision replay. Nothing here is the station's `random`, and
    no draw is ever made without being written down by the caller."""

    def __init__(self, root_seed, start=0):
        self.root = str(root_seed)
        self.n = int(start)

    def next(self, label):
        n = self.n
        self.n += 1
        h = hashlib.sha256(("%s|%d|%s" % (self.root, n, label)).encode("utf-8")).digest()
        u = int.from_bytes(h[:8], "big") / float(1 << 64)
        return {"seed": self.root, "n": n, "label": label, "u": round(u, 6),
                "dice": int(u * 100) + 1, "sides": 100}


def pick_index(weights, u):
    total = sum(w for w in weights if w > 0)
    if total <= 0:
        return -1
    target = u * total
    acc = 0.0
    last = -1
    for i, w in enumerate(weights):
        if w <= 0:
            continue
        acc += w
        last = i
        if target < acc:
            return i
    return last


# --- the aggregate ---------------------------------------------------------

def new_conversation(inputs, config, settings, seed=None, conversation_id=None):
    """The System3Conversation aggregate (blueprint section 3).

    `inputs` is everything the road knows when it asks: identity (road,
    trace, System 2 slot/job, schedule occurrence), participants (seat ->
    role/name/emotion), subject (the obligation and its source), timing
    (target/deadline/turn budget) and availability of material. It is kept
    whole on the aggregate so the decisions can be replayed."""
    inputs = copy.deepcopy(inputs if isinstance(inputs, dict) else {})
    cid = conversation_id or uuid.uuid4().hex[:16]
    seed = str(seed or settings.get("test_seed") or uuid.uuid4().hex)
    seats = [s for s in (inputs.get("seats") or ["A", "B"]) if s in ("A", "B", "C", "D", "E")]
    seats = seats or ["A", "B"]
    names = inputs.get("names") or {}
    roles = inputs.get("roles") or {}
    moods = inputs.get("initial_emotions") or {}
    target = max(0.0, float(inputs.get("target_seconds") or 0))
    want = max(2, min(40, int(inputs.get("turns") or 8)))
    participants = []
    for seat in seats:
        start = moods.get(seat) if isinstance(moods.get(seat), dict) else {}
        participants.append({
            "actor_id": seat, "role": str(roles.get(seat) or ""),
            "name": str(names.get(seat) or seat), "position": 0.0,
            "emotion": {"table": "", "category": "", "id": "", "label": "level",
                        "intensity": 0.0, "source": "initial",
                        "dims": {d: round(clamp(start.get(d)), 3) for d in EMOTION_DIMS}},
            "intensity": 0.0, "energy": 0.5, "recent_actions": [], "callbacks": []})
    identity = {
        "conversation_id": cid,
        "trace_id": str(inputs.get("trace_id") or ("s3-" + cid)),
        "schedule_occurrence_id": str(inputs.get("schedule_occurrence_id") or ""),
        "system2_slot_id": str(inputs.get("system2_slot_id") or ""),
        "system2_job_id": str(inputs.get("system2_job_id") or ""),
        "road_kind": str(inputs.get("road") or "banter"),
        "revision": 1,
    }
    subject = inputs.get("subject") if isinstance(inputs.get("subject"), dict) else {}
    conv = {
        "schema": CONVERSATION_SCHEMA, "engine": ENGINE_VERSION,
        "identity": identity,
        "mode": road_mode(settings, identity["road_kind"]),
        "generation_mode": settings.get("generation_mode", "batch"),
        "seed": seed, "draws": 0,
        "config_hash": config_hash(config),
        "settings": copy.deepcopy(settings),
        "inputs": inputs,
        "created": float(inputs.get("at") or time.time()),
        "timing": {"target_duration": target, "turn_budget": want,
                   "deadline": float(inputs.get("deadline") or 0),
                   "seconds_per_word": float(inputs.get("seconds_per_word") or SECONDS_PER_WORD),
                   "words_per_turn": float(inputs.get("words_per_turn") or 60),
                   # The host's own measure of a rendered turn (mean_turn_seconds),
                   # when it has one; otherwise words x seconds-per-word.
                   "turn_seconds": float(inputs.get("turn_seconds") or 0),
                   "elapsed_estimated": 0.0, "elapsed_rendered": 0.0,
                   "remaining": target},
        "subject": {"topic": str(subject.get("topic") or "")[:400],
                    "authority": str(subject.get("authority") or "obligated"),
                    "category": str(subject.get("category") or ""),
                    "sources": list(subject.get("sources") or []),
                    "seeded": bool(subject.get("seeded")),
                    "keywords": list(subject.get("keywords") or [])[:12],
                    "active_angle": str(subject.get("angle") or "")[:300],
                    # the operator's numbered exchange, word for word (row 1, row 2)
                    "exchange": dict(subject.get("exchange") or {}),
                    "topic_exhaustion": 0.0, "unresolved_points": []},
        "participants": participants,
        "dynamics": {"phase": "OPEN", "tension": 0.35, "agreement": 0.5,
                     "energy": 0.5, "novelty": 0.5, "repetition_risk": 0.0,
                     "closure_pressure": 0.0, "topic_exhaustion": 0.0},
        "cursor": {"cycle": 0, "step": 0, "initiator": seats[0], "last": "",
                   "pending_topic": False, "topic_count": 1},
        "turns": [], "decision_events": [], "doors": {}, "observations": [],
        "observed_delta": {}, "material_requests": [], "validation": None,
        "comparison": None, "bindings": [], "status": "planned",
    }
    _apply_carry(conv, inputs.get("carry"))                             # [s3-carry]
    return conv


def _apply_carry(conv, carry):
    """[s3-carry] THE LAST ROUND'S ENDING IS THIS ROUND'S START. Every
    conversation used to begin cold - tension 0.35, every seat level,
    position 0, nothing unresolved - so the roulette directed each segment
    in isolation and the station heard segments that did not know each
    other (measured 2026-09-27: initial emotions handed in on 0 of 1,308
    rounds). The runtime hands in what the previous round left behind on
    the air, decayed by its age; the seats present start there, the
    unresolved points carry, and the landing line is what turn 1 picks up
    from. Nothing here draws a number: it is state, recorded as a CARRY
    event when the round is planned."""
    if not isinstance(carry, dict) or not (carry.get("seats") or carry.get("landing")):
        conv["carry"] = None
        return
    f = clamp(float(carry.get("factor") or 0))
    seats = carry.get("seats") if isinstance(carry.get("seats"), dict) else {}
    carried = []
    for p in conv["participants"]:
        got = seats.get(p["actor_id"])
        if not isinstance(got, dict) or not got.get("category") or f <= 0:
            continue
        inten = round(clamp(float(got.get("intensity") or 0) * f), 3)
        dims = got.get("dims") if isinstance(got.get("dims"), dict) else {}
        p["emotion"] = {"table": str(got.get("table") or ""), "category": str(got["category"]),
                        "id": str(got.get("id") or ""), "label": str(got.get("label") or got["category"]),
                        "intensity": inten, "source": "carried", "since_turn": -1,
                        "dims": {d: round(clamp(float(dims.get(d) or 0) * f), 3) for d in EMOTION_DIMS}}
        p["intensity"] = inten
        p["position"] = round(clamp(float(got.get("position") or 0) * f, -1, 1), 3)
        p["energy"] = round(clamp(0.5 + (float(got.get("energy") or 0.5) - 0.5) * f), 3)
        carried.append(p["actor_id"])
    dyn = carry.get("dynamics") if isinstance(carry.get("dynamics"), dict) else {}
    for k in ("tension", "agreement", "energy"):
        if k in dyn:
            base = float(conv["dynamics"][k])
            conv["dynamics"][k] = round(clamp(base + (float(dyn[k]) - base) * f), 4)
    if f > 0:
        conv["subject"]["unresolved_points"] = [dict(x) for x in (carry.get("unresolved") or [])[-3:]
                                               if isinstance(x, dict)]
    landing = carry.get("landing") if isinstance(carry.get("landing"), dict) else {}
    conv["carry"] = {"from": str(carry.get("from") or ""), "road": str(carry.get("road") or ""),
                     "age": round(float(carry.get("age") or 0), 1), "factor": round(f, 3),
                     "seats": carried,
                     "landing": {"who": str(landing.get("who") or ""), "name": str(landing.get("name") or ""),
                                 "text": " ".join(str(landing.get("text") or "").split())[:400]},
                     "tempers": [str(x) for x in (carry.get("tempers") or [])][-6:],
                     "unresolved": len(conv["subject"]["unresolved_points"])}


def participant(conv, seat):
    for p in conv["participants"]:
        if p["actor_id"] == seat:
            return p
    return None


def _snapshot(conv, seat=None):
    d = conv["dynamics"]
    out = {k: round(float(d.get(k) or 0), 3) for k in DYNAMICS}
    out["phase"] = d.get("phase")
    out["initiator"] = conv["cursor"].get("initiator")
    out["unresolved"] = len(conv["subject"]["unresolved_points"])
    if seat:
        p = participant(conv, seat)
        if p:
            out["speaker"] = seat
            out["speaker_emotion"] = p["emotion"].get("label")
            out["speaker_intensity"] = round(float(p["emotion"].get("intensity") or 0), 3)
            out["speaker_position"] = round(float(p.get("position") or 0), 3)
    return out


def _phase_for(conv, turn_index, want):
    """Where in the scene this turn sits (blueprint section 11)."""
    frac_turns = turn_index / float(max(1, want - 1))
    t = conv["timing"]
    frac_time = 0.0
    if t["target_duration"] > 0:
        frac_time = t["elapsed_estimated"] / t["target_duration"]
    frac = max(frac_turns, frac_time)
    if turn_index == want - 1:
        return "SEGUE", frac
    if frac < 0.08:
        return "OPEN", frac
    if frac < 0.25:
        return "ESTABLISH", frac
    if frac < 0.5:
        return "DEVELOP", frac
    if frac < 0.68:
        return ("ESCALATE" if conv["dynamics"]["tension"] >= 0.55 else "EXPLORE"), frac
    if frac < 0.78:
        return "WILDCARD", frac
    if frac < 0.88:
        return "RESOLVE", frac
    return "WRAP", frac


# --- effective weights -----------------------------------------------------

_INHERIT = ("requires", "requires_state", "phases", "not_phases", "min_turns_left",
            "max_turns_left", "modifiers", "emotions", "tags", "lean", "effects",
            "cue", "speaker", "new_topic", "keep_initiator", "closes", "resolves",
            "keeps_unresolved", "resolver", "valence", "arousal", "dims",
            "speakerbox", "cooldown_turns", "after_lean", "callback_source",
            "after")                                                       # [s3-flow] follow-on odds


def _spec(table, cat, item):
    spec = {k: copy.deepcopy(cat[k]) for k in _INHERIT if k in cat}
    for k, v in item.items():
        if k in ("modifiers", "effects", "emotions") and isinstance(v, dict):
            merged = dict(spec.get(k) or {})
            merged.update(v)
            spec[k] = merged
        elif k == "tags" and isinstance(v, list):
            spec[k] = list(dict.fromkeys(list(spec.get("tags") or []) + v))
        else:
            spec[k] = copy.deepcopy(v)
    spec["table"], spec["category"] = table["id"], cat["id"]
    spec["category_label"] = cat.get("label") or cat["id"]
    spec["family"] = table["family"]
    spec.setdefault("label", item.get("id"))
    spec.setdefault("text", str(spec.get("label") or "").lower())
    return spec


def _recent_items(conv, family, turns=6):
    out = []
    for turn in conv["turns"][-turns:]:
        for d in turn.get("decisions", []):
            if d.get("family") == family and d.get("item"):
                out.append(d["item"])
    return out


def _item_factor(spec, ctx):
    """(multiplier, reasons, excluded_why) for one candidate.

    Every term is recorded with its reason, so "why was this weighted
    0.84" has an answer in the ledger rather than in this function."""
    conv = ctx["conv"]
    reasons = []
    if spec.get("enabled") is False:
        return 0.0, reasons, "disabled in its table"
    if ctx.get("closes") and not spec.get("closes"):
        return 0.0, reasons, "the closing turn only draws closing moves"
    phase = ctx["phase"]
    if spec.get("phases") and phase not in spec["phases"]:
        return 0.0, reasons, "not allowed in phase %s" % phase
    if spec.get("not_phases") and phase in spec["not_phases"]:
        return 0.0, reasons, "not allowed in phase %s" % phase
    left = ctx["turns_left"]
    if spec.get("min_turns_left") and left < int(spec["min_turns_left"]):
        return 0.0, reasons, "needs %d turns left, %d remain" % (int(spec["min_turns_left"]), left)
    if spec.get("max_turns_left") is not None and left > int(spec["max_turns_left"]):
        return 0.0, reasons, "only in the last %d turns" % int(spec["max_turns_left"])
    avail = ctx.get("availability") or {}
    for need in spec.get("requires") or []:
        if not avail.get(need):
            return 0.0, reasons, "no %s material on this road" % need
    for need in spec.get("requires_state") or []:
        if need == "callbacks" and not any(p["callbacks"] for p in conv["participants"]):
            return 0.0, reasons, "nothing to call back to yet"
        if need == "unresolved" and not conv["subject"]["unresolved_points"]:
            return 0.0, reasons, "no unresolved point"
    cool = int(spec.get("cooldown_turns") or (2 if spec["family"] in ("RS", "IRS", "FL") else 0))
    if cool and spec.get("id") in _recent_items(conv, spec["family"], cool):
        return 0.0, reasons, "cooling down (%d turns)" % cool
    f = 1.0
    for key, coef in (spec.get("modifiers") or {}).items():
        x = float(conv["dynamics"].get(key) or 0) if key in conv["dynamics"] else None
        if x is None:
            continue
        m = clamp(1 + float(coef) * (2 * x - 1), 0.05, 4.0)
        if abs(m - 1) > 0.005:
            reasons.append("%s %.2f x%.2f" % (key, x, m))
            f *= m
    cat = ctx.get("speaker_emotion_cat")
    emo = spec.get("emotions") or {}
    if cat and cat in emo:
        m = float(emo[cat])
        reasons.append("speaker in %s x%.2f" % (cat, m))
        f *= m
    controls = ctx.get("controls") or {}
    for tag in spec.get("tags") or []:
        if tag in TAG_CONTROLS:
            c = clamp(controls.get(TAG_CONTROLS[tag], 0.5))
            m = 4 ** (c - 0.5)
        elif tag in TAG_INVERSE:
            c = clamp(controls.get(TAG_INVERSE[tag], 0.5))
            m = 4 ** (0.5 - c)
        else:
            continue
        if abs(m - 1) > 0.005:
            reasons.append("%s dial x%.2f" % (tag, m))
            f *= m
    person = (ctx.get("personalities") or {}).get(ctx.get("speaker")) or {}
    for tag in spec.get("tags") or []:
        if tag in person:
            m = max(0.0, float(person[tag]))
            reasons.append("%s's %s x%.2f" % (ctx.get("speaker"), tag, m))
            f *= m
    ev_emo = ctx.get("event_emotions") or {}                                 # [s3-events]
    if spec["family"] == "ES" and spec.get("category") in ev_emo:
        m = float(ev_emo[spec["category"]])
        reasons.append("what happens on this turn x%.2f" % m)
        f *= m
    if spec["family"] == "ES":
        # Emotion is state: the speaker's current category is stickier the
        # lower the volatility dial (blueprint: persistence/decay).
        now = ctx.get("speaker_emotion_cat")
        if now and spec.get("category") == now:
            vol = clamp(controls.get("emotional_volatility", 0.5))
            m = 1 + 3 * (1 - vol)
            reasons.append("persisting emotion x%.2f" % m)
            f *= m
        lean = ctx.get("prev_lean")
        after = spec.get("after_lean") or {}
        if lean is not None and str(int(lean)) in after:
            m = float(after[str(int(lean))])
            reasons.append("reacting to %s x%.2f" % ("pushback" if lean < 0 else "support" if lean > 0 else "neutral", m))
            f *= m
    if spec["family"] == "FL" and spec.get("speaker") in ("initiator", "responder"):
        is_init = ctx.get("speaker") == conv["cursor"].get("initiator")
        match = (spec["speaker"] == "initiator") == is_init
        if not match:
            reasons.append("said by the %s, preferred %s x0.35" % (
                "initiator" if is_init else "responder", spec["speaker"]))
            f *= 0.35
    # [s3-flow] FOLLOW-ON ODDS: what the turn before rolled tilts this wheel
    after = spec.get("after") if isinstance(spec.get("after"), dict) else {}
    prev_keys = ctx.get("prev_keys") or ()
    for key, mult in after.items():
        if key in prev_keys:
            try:
                m = max(0.0, float(mult))
            except (TypeError, ValueError):
                continue
            reasons.append("after %s x%.2f" % (key, m))
            f *= m
    recent = _recent_items(conv, spec["family"], 6)
    if spec.get("id") in recent:
        reasons.append("used recently x0.4")
        f *= 0.4
    # [s3-flow] UNIQUENESS: an item a recent round used weighs a quarter
    if spec.get("id") and ("%s:%s" % (spec["family"], spec["id"])) in (ctx.get("recent_rounds") or ()):
        reasons.append("used in a recent round x0.25")
        f *= 0.25
    return f, reasons, ""


def _tables_for(config, family, only=None):
    out = []
    for t in config.get("tables") or []:
        if t.get("family") != family or not t.get("enabled", True):
            continue
        if only and t.get("id") not in only:
            continue
        if float(t.get("weight", 1) or 0) <= 0:
            continue
        out.append(t)
    return out


def _event(conv, ctx, family, stages, selected, before, meta=None, rng=None):
    seq = len(conv["decision_events"])
    ev = {
        "schema": EVENT_SCHEMA,
        "event_id": "%s:%04d" % (conv["identity"]["conversation_id"], seq),
        "seq": seq,
        "conversation_id": conv["identity"]["conversation_id"],
        "trace_id": conv["identity"]["trace_id"],
        "turn_id": ctx.get("turn_id", ""),
        "turn_index": ctx.get("turn_index", -1),
        "at": time.time(),
        "family": family,
        "stages": stages,
        "rng": rng,
        "selected": selected,
        "state_before": before,
        "state_after": None,
        "links": {"prompt_id": "", "script_id": "", "render_id": "", "delivery_id": ""},
        "meta": meta or {},
        "config_hash": conv["config_hash"],
        "engine": ENGINE_VERSION,
    }
    conv["decision_events"].append(ev)
    return ev


def _stage(name, rows, pick, draw, excluded=None):
    total = sum(r["weight"] for r in rows)
    return {"stage": name,
            "candidates": [{"id": r["id"], "label": r["label"], "base": round(r["base"], 4),
                            "weight": round(r["weight"], 4),
                            "p": round(r["weight"] / total, 4) if total > 0 else 0.0,
                            "why": r.get("why", [])} for r in rows],
            "excluded": excluded or [],
            "total": round(total, 4),
            "draw": draw,
            "selected": rows[pick]["id"] if pick >= 0 else None,
            "selected_index": pick + 1 if pick >= 0 else 0,
            "of": len(rows)}


def weighted_decision(conv, config, ctx, stream, family, tables=None, closes=False, fixed=None, category=None):
    """Draw one outcome from a family: table -> category -> item.

    "When a category is initialized, a Rolodex will scroll the category
    options then land on one randomly via RNG and then cycle randomly via
    the subcategories inside." Each stage is its own recorded draw.
    Returns (spec or None, event).

    [s3-window] `fixed`: the operator turned this draw's roulette off in the
    segment editor and pinned an item (an item id, or table:item). It is
    recorded like any decision - one stage, one candidate, no random number
    - so the audit still shows what stood here and why."""
    ctx = dict(ctx)
    ctx["closes"] = closes
    before = _snapshot(conv, ctx.get("speaker"))
    stages = []
    if fixed:
        want = str(fixed)
        for table in _tables_for(config, family, None):
            for cat in table.get("categories") or []:
                for k, item in enumerate(cat.get("items") or []):
                    if str(item.get("id")) != want and "%s:%s" % (table["id"], item.get("id")) != want:
                        continue
                    spec = _spec(table, cat, item)
                    row = {"id": item["id"], "label": spec["label"], "base": 1.0, "weight": 1.0, "p": 1.0,
                           "why": ["pinned by the operator in the segment editor - the roulette is off for this draw"]}
                    stages.append({"stage": "fixed", "candidates": [row], "excluded": [], "total": 1.0,
                                   "selected": item["id"], "selected_index": 1, "of": 1, "draw": None})
                    selected = {"table": table["id"], "category": cat["id"],
                                "category_label": cat.get("label") or cat["id"], "id": spec["id"],
                                "label": spec["label"], "text": spec.get("text", ""), "index": k + 1,
                                "of": len(cat.get("items") or []), "authority": "fixed"}
                    ev = _event(conv, ctx, family, stages, selected, before,
                                meta={"authority": "fixed", "why": "pinned to %s in the segment editor: not a draw" % want})
                    return spec, ev
        # a pin that names nothing on the tables falls through to the roll, and says so
        ctx["fixed_missing"] = want
    # [s3-flow] a category pin: the node is static, the item inside still rolls
    if category and not any(c.get("id") == category for t in _tables_for(config, family, tables)
                            for c in t.get("categories") or []):
        ctx["category_missing"] = category
        category = None
    # Every candidate's effective weight, with its reasons.
    pool = []
    for table in _tables_for(config, family, tables):
        cats = []
        for cat in table.get("categories") or []:
            if category and cat.get("id") != category:
                continue
            items, excl = [], []
            for item in cat.get("items") or []:
                spec = _spec(table, cat, item)
                f, why, out = _item_factor(spec, ctx)
                base = float(item.get("weight", 1.0) or 0)
                if out or base * f <= 0:
                    excl.append({"id": item["id"], "label": spec["label"], "why": out or "weight 0"})
                    continue
                items.append({"id": item["id"], "label": spec["label"], "base": base,
                              "weight": base * f, "why": why, "spec": spec})
            mean = (sum(i["weight"] for i in items) / len(items)) if items else 0.0
            cw = float(cat.get("weight", 1.0) or 0) * mean
            cats.append({"id": cat["id"], "label": cat.get("label") or cat["id"],
                         "base": float(cat.get("weight", 1.0) or 0), "weight": cw,
                         "why": ["mean eligible item weight %.3f" % mean] if items else [],
                         "items": items, "excluded": excl})
        live = [c for c in cats if c["weight"] > 0]
        pool.append({"id": table["id"], "label": table.get("label") or table["id"],
                     "base": float(table.get("weight", 1.0) or 0),
                     "weight": float(table.get("weight", 1.0) or 0) if live else 0.0,
                     "why": [] if live else ["no eligible outcome"], "cats": cats})
    live_tables = [t for t in pool if t["weight"] > 0]
    if not live_tables:
        ev = _event(conv, ctx, family, [], None, before,
                    meta={"empty": "no eligible outcome in any %s table" % family})
        return None, ev
    if len(live_tables) > 1:
        draw = stream.next("%s:table" % family)
        i = pick_index([t["weight"] for t in live_tables], draw["u"])
        stages.append(_stage("table", live_tables, i, draw))
    else:
        i = 0
        stages.append(_stage("table", live_tables, 0, None))
    table = live_tables[i]
    cats = [c for c in table["cats"] if c["weight"] > 0]
    draw = stream.next("%s:category" % family)
    j = pick_index([c["weight"] for c in cats], draw["u"])
    stages.append(_stage("category", cats, j, draw,
                         [{"id": c["id"], "label": c["label"], "why": "no eligible item"}
                          for c in table["cats"] if c["weight"] <= 0]))
    cat = cats[j]
    draw = stream.next("%s:item" % family)
    k = pick_index([x["weight"] for x in cat["items"]], draw["u"])
    stages.append(_stage("item", cat["items"], k, draw, cat["excluded"]))
    spec = cat["items"][k]["spec"]
    selected = {"table": table["id"], "category": cat["id"], "category_label": cat["label"],
                "id": spec["id"], "label": spec["label"], "text": spec.get("text", ""),
                "index": k + 1, "of": len(cat["items"])}
    meta = {}
    if category:
        meta = {"authority": "category", "why": "the node is pinned to %s in the segment editor: "
                                                "the category is static, the item rolled" % category}
    elif ctx.get("category_missing"):
        meta = {"why": "pinned to category %s, which no table holds - rolled over the whole family"
                       % ctx.pop("category_missing")}
    ev = _event(conv, ctx, family, stages, selected, before, meta=meta or None, rng=draw)
    return spec, ev


# --- decisions for one turn --------------------------------------------------

def _intensity_word(x):
    return "hard" if x >= 0.72 else "plainly" if x >= 0.4 else "mildly"


def performance_intent(spec, intensity, dynamics):
    """ES -> the engine-neutral PerformanceIntent (blueprint section 12).

    `dims` is the station's six-dimension emotional state, which the host
    feeds to performance_vector(state=...) and so to perf_apply on every
    engine's take. The rest are descriptors for adapters that can honour
    them; an adapter that cannot simply ignores them."""
    arousal = clamp(spec.get("arousal", 0.5))
    valence = clamp(spec.get("valence", 0.0), -1.0, 1.0)
    dims = {d: round(clamp(float((spec.get("dims") or {}).get(d) or 0) * (0.35 + 0.65 * intensity)), 3)
            for d in EMOTION_DIMS}
    return {
        "emotion": spec.get("label"), "family": spec.get("category"),
        "table": spec.get("table"), "intensity": round(intensity, 3),
        "energy": round(clamp(0.3 + 0.7 * arousal * (0.5 + 0.5 * intensity)), 3),
        "pace": round(clamp(1.0 + 0.16 * (arousal - 0.5) * (0.5 + intensity), 0.8, 1.25), 3),
        "emphasis": round(clamp(0.2 + 0.8 * intensity * arousal), 3),
        "warmth": round((valence + 1) / 2, 3),
        "tension": round(clamp(dynamics.get("tension", 0.35)), 3),
        "pause_style": "clipped" if arousal >= 0.7 else "spacious" if arousal <= 0.3 else "natural",
        "valence": round(valence, 3), "arousal": round(arousal, 3),
        "dims": dims,
        "engine_hints": {"dsp": {"pace": True, "pitch_var": True, "energy": True, "pause_scale": True},
                         "native_emotion": None},
    }


def _apply_effects(conv, spec):
    d = conv["dynamics"]
    for key, delta in (spec.get("effects") or {}).items():
        if key in d and key != "phase":
            d[key] = round(clamp(float(d[key]) + float(delta)), 4)


def _speaker_for(conv, step_speaker, seats):
    cur = conv["cursor"]
    init = cur["initiator"]
    order = seats[seats.index(init):] + seats[:seats.index(init)] if init in seats else seats
    responders = [s for s in order if s != init]
    if step_speaker == "initiator":
        return init
    if step_speaker == "responder_a":
        return responders[0] if responders else None
    if step_speaker == "responder_b":
        return responders[1] if len(responders) > 1 else None
    if step_speaker == "frame":
        # The seat that did not just speak, initiator first.
        return init if cur["last"] != init else (responders[0] if responders else init)
    return step_speaker if step_speaker in seats else None


def _speakerbox_marks(conv, config, settings, ctx, stream, step, turn, inputs):
    """The per-line prepend/append roulette (PDF p.7).

    "From 0 to 100 ... the possibility that a dice roll will occur before
    and after certain response points ... The slider for prepend / append
    determines the odds." Each mark is one d100 against the slider (scaled
    by the Speakerbox density dial); a hit then draws its mode. Where the
    dial does not apply the event says why rather than rolling."""
    out = []
    marks = [m for m in (step.get("speakerbox") or []) if m in ("prepend", "append")]
    rates = inputs.get("speakerbox_rates") or {}
    # The station's full-swath dial, as System 3 reads it (engine v2): not a
    # reading dealt across the seats after the writing - which is a
    # monologue split between two voices, the pair talking through each
    # other - but an opening speaker-box monologue the initiator reads,
    # which the next turn then answers. A seeded round already opens on a
    # passage, so it is not given a second.
    if (turn["index"] == 0 and "prepend" in marks and float(rates.get("full") or 0) > 0
            and not conv["subject"].get("seeded")):
        marks = ["full"] + marks
    if not marks:
        return out
    avail = inputs.get("availability") or {}
    sb = config.get("speakerbox") or DEFAULT_SPEAKERBOX
    density = clamp(settings["controls"].get("speakerbox_density", 0.5))
    used = sum(1 for t in conv["turns"] for x in t.get("speakerbox", []) if x.get("mode") != "NONE")
    prior = [x for t in conv["turns"] for x in t.get("speakerbox", [])
             if x.get("mode") in ("PREPEND", "APPEND", "FULL_SWATH")]
    opened = False
    for mark in marks:
        if mark == "prepend" and opened:
            continue                     # the monologue already opens this turn
        before = _snapshot(conv, turn["speaker"])
        rate = clamp(float(rates.get(mark) or 0) * 4 ** (density - 0.5))
        rec = {"mark": mark, "rate": round(rate, 3), "mode": "NONE", "applies": True, "why": ""}
        if not avail.get("speakbox"):
            rec.update(applies=False, why="this road carries its own material; nothing is stapled to it")
        elif rate <= 0:
            rec.update(why="the %s dial is at 0%%" % mark)
        rng = None
        stages = []
        if rec["applies"] and rate > 0:
            rng = stream.next("SPEAKERBOX:%s" % mark)
            threshold = int(round(100 - rate * 100))
            hit = rng["dice"] > threshold
            rec.update(dice=rng["dice"], threshold=threshold, hit=hit)
            stages.append({"stage": "dice", "draw": rng, "threshold": threshold,
                           "rule": "hit when the d100 lands above %d (%.0f%% slider)" % (threshold, rate * 100),
                           "selected": "PASS" if hit else "MISS"})
            if hit and used >= int(sb.get("max_inline", 2)):
                rec.update(why="a hit, but this round already carries %d inline passages" % used)
            elif hit and mark == "full":
                rec["mode"] = "FULL_SWATH"
                used += 1
                opened = True
                stages.append({"stage": "mode", "draw": None, "selected": "FULL_SWATH",
                               "rule": "the full-swath dial opens the round with a speaker-box monologue the "
                                       "initiator reads out; the next turn answers it"})
            elif hit:
                modes = dict(sb.get("modes") or {})
                rows = [{"id": "PREPEND" if mark == "prepend" else "APPEND",
                         "label": "word for word " + ("before" if mark == "prepend" else "after") + " the line",
                         "base": float(modes.get("verbatim", 1.0)), "weight": float(modes.get("verbatim", 1.0))},
                        {"id": "REFERENCE", "label": "in their own words",
                         "base": float(modes.get("reference", 1.0)), "weight": float(modes.get("reference", 1.0))}]
                if prior:
                    rows.append({"id": "CALLBACK_TO_PRIOR", "label": "a callback to an earlier passage",
                                 "base": float(modes.get("callback", 0.6)), "weight": float(modes.get("callback", 0.6))})
                rows = [r for r in rows if r["weight"] > 0]
                if rows:
                    mdraw = stream.next("SPEAKERBOX:mode")
                    k = pick_index([r["weight"] for r in rows], mdraw["u"])
                    stages.append(_stage("mode", rows, k, mdraw))
                    rec["mode"] = rows[k]["id"]
                    used += 1
                    if rec["mode"] == "CALLBACK_TO_PRIOR":
                        rec["callback_to"] = prior[-1].get("request_id", "")
        sel = {"id": rec["mode"], "label": rec["mode"].replace("_", " ").lower(), "mark": mark}
        ev = _event(conv, dict(ctx, turn_id=turn["turn_id"], turn_index=turn["index"]),
                    "SPEAKERBOX", stages, sel, before,
                    meta={"mark": mark, "rate": rec["rate"], "applies": rec["applies"],
                          "why": rec["why"], "insertion_point": "%s turn %d" % (mark, turn["index"] + 1)},
                    rng=rng)
        rec["event_id"] = ev["event_id"]
        if rec["mode"] in ("PREPEND", "APPEND", "REFERENCE", "FULL_SWATH"):
            rec["request_id"] = "%s:sb%d" % (turn["turn_id"], len(out))
            conv["material_requests"].append({
                "request_id": rec["request_id"], "kind": "speakbox", "turn_id": turn["turn_id"],
                "turn_index": turn["index"], "mode": rec["mode"], "event_id": ev["event_id"],
                "chars": int(sb.get("monologue_chars", 700) if rec["mode"] == "FULL_SWATH"
                             else sb.get("passage_chars", 420)), "resolved": None})
        out.append(rec)
    return out


def _speakerbox_acts(conv, config, ctx, turn, acts, inputs):
    """An act that is itself a quote ("speaker-box quote used in rebuttal",
    "more speaker-box") asks for a passage without a dice of its own - the
    act was the draw. Still bounded by the round's inline budget."""
    out = []
    sb = config.get("speakerbox") or DEFAULT_SPEAKERBOX
    for spec in acts:
        mode = spec.get("speakerbox")
        if mode not in SPEAKERBOX_MODES or mode == "NONE":
            continue
        before = _snapshot(conv, turn["speaker"])
        used = sum(1 for t in conv["turns"] for x in t.get("speakerbox", []) if x.get("mode") != "NONE")
        used += sum(1 for x in turn.get("speakerbox") or [] if x.get("mode") != "NONE")
        rec = {"mark": "act", "mode": mode, "applies": True, "act": spec["id"],
               "why": "the %s act is a speakerbox quote" % spec["id"]}
        if used >= int(sb.get("max_inline", 2)):
            rec.update(mode="NONE", why="the %s act asked for a quote, but the round's inline budget is spent" % spec["id"])
        ev = _event(conv, dict(ctx, turn_id=turn["turn_id"], turn_index=turn["index"]), "SPEAKERBOX", [],
                    {"id": rec["mode"], "label": rec["mode"].replace("_", " ").lower(), "mark": "act"}, before,
                    meta={"mark": "act", "act": spec["id"], "why": rec["why"], "drawn": False,
                          "insertion_point": "inside turn %d" % (turn["index"] + 1)})
        rec["event_id"] = ev["event_id"]
        if rec["mode"] != "NONE":
            rec["request_id"] = "%s:sba%d" % (turn["turn_id"], len(out))
            conv["material_requests"].append({
                "request_id": rec["request_id"], "kind": "speakbox", "turn_id": turn["turn_id"],
                "turn_index": turn["index"], "mode": rec["mode"], "event_id": ev["event_id"],
                "chars": int(sb.get("passage_chars", 420)), "resolved": None})
        out.append(rec)
    return out


def _sfx_decision(conv, config, settings, ctx, stream, turn, es_spec, acts):
    """The SFX Guy's intent for this turn (PDF p.6, blueprint section 10).

    Decides only WHETHER a clip is wanted here, where, and what it should
    be about. The station's matcher and rotation pick the actual file from
    the indexed book at air, and its two-line cadence stays the floor, so
    nothing here can invent a path or reduce his minimum."""
    sfx = config.get("sfx") or DEFAULT_SFX
    aggr = clamp(settings["controls"].get("sfx_aggression", 0.5))
    before = _snapshot(conv, turn["speaker"])
    p = float(sfx.get("p_low", 0.08)) + (float(sfx.get("p_high", 0.7)) - float(sfx.get("p_low", 0.08))) * aggr
    why = ["aggression %.2f -> %.2f" % (aggr, p)]
    arousal = clamp((es_spec or {}).get("arousal", 0.5))
    boost = float(sfx.get("arousal_boost", 0.3)) * (arousal - 0.5)
    if abs(boost) > 0.005:
        p += boost
        why.append("arousal %.2f %+.2f" % (arousal, boost))
    if any("humor" in (a.get("tags") or []) for a in acts):
        p += float(sfx.get("humor_boost", 0.15))
        why.append("comic turn %+.2f" % float(sfx.get("humor_boost", 0.15)))
    last = conv["turns"][-1] if conv["turns"] else None
    reason = "dice"
    forced = False
    if sfx.get("first_exchange", True) and turn["index"] == 2 and conv["cursor"]["cycle"] == 0:
        # "With the initial sentence, the clip is played via RNG (dice
        # roll) before sentence C or after."
        forced, reason = True, "first_exchange"
    elif last and (last.get("sfx") or {}).get("play") and aggr < 0.85:
        p *= 0.35
        why.append("just had one x0.35")
    p = clamp(p, 0.0, 1.0)
    rng = stream.next("SFX:play")
    play = forced or rng["u"] < p
    stages = [{"stage": "dice", "draw": rng, "threshold": round(p, 3),
               "rule": "a clip when u < %.2f" % p if not forced else "the first exchange always carries one",
               "selected": "PLAY" if play else "PASS", "why": why}]
    placement = "after"
    if play:
        pdraw = stream.next("SFX:placement")
        placement = "before" if pdraw["u"] < 0.5 else "after"
        stages.append({"stage": "placement", "draw": pdraw,
                       "rule": "before the line when u < 0.50", "selected": placement.upper()})
    terms = []
    for word in [(es_spec or {}).get("label", "")] + [a.get("label", "") for a in acts] + conv["subject"]["keywords"][:4]:
        for w in re.findall(r"[a-z]{4,}", str(word).lower()):
            if w not in terms and w not in _STOP:
                terms.append(w)
    rec = {"play": play, "placement": placement, "p": round(p, 3), "reason": reason if play else "dice",
           "intent": terms[:8], "gain": "duck_under_voice" if placement == "before" else "punctuate",
           "semantic": ", ".join(terms[:3])}
    ev = _event(conv, dict(ctx, turn_id=turn["turn_id"], turn_index=turn["index"]), "SFX", stages,
                {"id": "PLAY" if play else "PASS", "label": ("play %s the line" % placement) if play else "no clip",
                 "intent": rec["intent"]}, before,
                meta={"reason": rec["reason"], "resolved_at": "air, by the station's matcher and rotation",
                      "cadence_floor": "sfx_every_units (unchanged)"}, rng=rng)
    rec["event_id"] = ev["event_id"]
    return rec


_STOP = set("that this with from what they them their there have been were will would about just into your "
            "said says then than when which while also only very much more most some such been being".split())


SFXGUY_KINDS = {"news": "breaks a story off the wire", "reaction": "fires back at this very line",
                "quip": "a saying off his shelf"}


def _tint_decision(conv, settings, ctx, turn, inputs):
    """[s3-rewrite] "Rhyme this line": whether the crystal tint may touch
    this turn. Its own stream (seed|tint), so the round's other draws are
    what they were. Nothing is rolled unless the round opted in
    (rewrite_rolls); when the station's tint pass is off, one event on the
    round says so and no turn rolls."""
    if not inputs.get("rewrite_rolls"):
        return None
    tint = inputs.get("tint") if isinstance(inputs.get("tint"), dict) else {}
    if not tint.get("wanted"):
        if not conv.get("tint_off_noted"):
            conv["tint_off_noted"] = True
            before = _snapshot(conv, turn["speaker"])
            ev = _event(conv, {"turn_id": "", "turn_index": -1}, "TINT", [],
                        {"id": "OFF", "label": "the crystal tint pass is off on the station"}, before,
                        meta={"applies": False, "why": str(tint.get("why") or "the station's crystal tint pass is off "
                              "(crystal_tint_pass, a crystal switched on, and the tint gate are all needed)")})
            ev["state_after"] = before
        return None
    controls = settings.get("controls") or {}
    control = clamp(controls.get("tint", DEFAULT_CONTROLS["tint"]))
    rate = round(clamp(TINT_RATE_AT_FULL * control), 4)
    own = DrawStream(str(conv["seed"]) + "|tint", int(conv.get("tint_draws") or 0))
    before = _snapshot(conv, turn["speaker"])
    d = own.next("TINT:rhyme")
    st, hit = _dice_stage("RHYME", "the crystal tint may rhyme this line", rate, d,
                          "tint control %.2f x %.1f" % (control, TINT_RATE_AT_FULL))
    conv["tint_draws"] = own.n
    ev = _event(conv, dict(ctx, turn_id=turn["turn_id"], turn_index=turn["index"]), "TINT", [st],
                {"id": "RHYME" if hit else "PLAIN", "label": "the tint may rhyme this line" if hit else "read plain, as written"},
                before, meta={"rate": rate, "control": round(control, 3),
                              "coverage_target": tint.get("coverage"),
                              "why": "the station's own selection took the first N eligible lines for its coverage; "
                                     "under System 3 the dice choose the lines"}, rng=d)
    ev["state_after"] = before
    turn["decisions"].append({"family": "TINT", "event_id": ev["event_id"], "item": "RHYME" if hit else "PLAIN",
                              "label": ev["selected"]["label"], "u": d["u"]})
    return {"rhyme": bool(hit), "event_id": ev["event_id"]}


def _rewrite_rolls(conv, config, settings, inputs):
    """[s3-rewrite] The round's two rolls about what may happen to it after
    the write: REPAIR (a round that misses its target goes back to the
    writer, or stands as written) and ROOM (the Writers' Room may add to or
    rewrite it later, or may not). Each on its own stream, recorded once,
    opt-in like the round rolls."""
    if not inputs.get("rewrite_rolls") or conv.get("repair_roll") is not None:
        return
    controls = settings.get("controls") or {}
    ctx0 = {"turn_id": "", "turn_index": -1}
    for family, key, at_full, yes, no, why in (
            ("REPAIR", "repair", REPAIR_RATE_AT_FULL, "a round that misses its target goes back to the writer",
             "it stands as written, whatever the checks say",
             "the richness rewrite and System 3's own repair used to run - or be cancelled by a review gate - "
             "on their own; this roll decides, and the gates do not"),
            ("ROOM", "room", ROOM_RATE_AT_FULL, "the Writers' Room may add to or rewrite this round later",
             "the Writers' Room leaves this round alone",
             "the Room's two tickets (add turns / rewrite whole) chose bound rounds by their quality debt; "
             "this roll is asked first")):
        control = clamp(controls.get(key, DEFAULT_CONTROLS[key]))
        rate = round(clamp(at_full * control), 4)
        stream = DrawStream(str(conv["seed"]) + "|round:" + family)
        d = stream.next(family + ":dice")
        st, hit = _dice_stage(family, yes, rate, d, "%s control %.2f x %.1f" % (key, control, at_full))
        st["candidates"][1]["label"] = no
        before = _snapshot(conv, conv["cursor"].get("initiator"))
        ev = _event(conv, ctx0, family, [st], {"id": family if hit else "NONE", "label": yes if hit else no},
                    before, meta={"rate": rate, "control": round(control, 3), "why": why}, rng=d)
        ev["state_after"] = before
        conv[key + "_roll"] = {key: bool(hit), "event_id": ev["event_id"], "rate": rate}


def _sfxguy_decision(conv, config, ctx, turn, inputs):
    """[s3-roads] The SFX Guy's node on this turn: does he pipe up after it,
    and with what kind of line. His numbers come off their own stream
    (seed|sfxguy), so the round's draws are exactly what they were before
    he had a node. None when the station has no drop voice; PASS without
    a roll on a caller's turn (the station's rule, kept)."""
    guy = inputs.get("sfxguy") if isinstance(inputs.get("sfxguy"), dict) else {}
    if not guy or not guy.get("voice"):
        return None
    cfg = dict(DEFAULT_SFXGUY, **(config.get("sfxguy") or {}))
    seat = turn["speaker"]
    if cfg.get("never_over_callers", True) and seat in ("C", "E"):
        return {"speak": False, "kind": None, "order": [], "why": "never over a caller", "event_id": None}
    if cfg.get("rate_by_dial", True):
        rate = clamp(float(guy.get("rate") or 0) / 100.0)
        rate_why = "the SFX Guy interjections dial (%s)" % guy.get("rate")
    else:
        rate = clamp(float(cfg.get("rate") or 0))
        rate_why = "config sfxguy.rate"
    if cfg.get("reaction_by_warp", True):
        warp = clamp(float(guy.get("warp") or 0) / 100.0)
        warp_why = "the invention dial sfxguy_warp (%s)" % guy.get("warp")
    else:
        warp = clamp(float(cfg.get("reaction_share") or 0))
        warp_why = "config sfxguy.reaction_share"
    own = DrawStream(str(conv["seed"]) + "|sfxguy", int(conv.get("sfxguy_draws") or 0))
    before = _snapshot(conv, seat)
    rng = own.next("SFXGUY:speak")
    speak = rng["u"] < rate
    stages = [{"stage": "dice", "draw": rng, "threshold": round(rate, 3),
               "rule": "he pipes up when u < %.2f: %s" % (rate, rate_why),
               "selected": "SPEAK" if speak else "PASS"}]
    kind, order = None, []
    if speak:
        rows = [{"id": "news", "label": SFXGUY_KINDS["news"], "base": float(cfg.get("news_share") or 0),
                 "weight": clamp(float(cfg.get("news_share") or 0)), "why": ["config sfxguy.news_share"]},
                {"id": "reaction", "label": SFXGUY_KINDS["reaction"], "base": warp, "weight": warp, "why": [warp_why]},
                {"id": "quip", "label": SFXGUY_KINDS["quip"], "base": round(1 - warp, 3),
                 "weight": round(max(0.0, 1 - warp), 3), "why": ["what the invention dial leaves"]}]
        rows = [r for r in rows if r["weight"] > 0]
        if rows:
            kdraw = own.next("SFXGUY:kind")
            k = pick_index([r["weight"] for r in rows], kdraw["u"])
            stages.append(_stage("item", rows, k, kdraw))
            kind = rows[k]["id"] if k >= 0 else None
            order = ([kind] if kind else []) + [r["id"] for r in sorted(rows, key=lambda r: -r["weight"])
                                                if r["id"] != kind]
    conv["sfxguy_draws"] = own.n
    selected = {"id": "SPEAK" if speak else "PASS", "kind": kind, "order": order,
                "label": ("pipes up: " + SFXGUY_KINDS.get(kind, kind or "")) if speak else "keeps quiet"}
    ev = _event(conv, dict(ctx, turn_id=turn["turn_id"], turn_index=turn["index"]), "SFXGUY", stages,
                selected, before,
                meta={"resolved_at": "air: the line is drawn then, from the first kind that has one, "
                                     "with the candidates recorded",
                      "dial": guy.get("rate"), "warp": guy.get("warp"),
                      "stream": "his own (seed|sfxguy): the round's draws are untouched"},
                rng=rng)
    return {"speak": bool(speak), "kind": kind, "order": order, "p": round(rate, 3), "event_id": ev["event_id"]}


def _decide_turn(conv, config, settings, stream, step, speaker, want, inputs, closing=False):
    idx = len(conv["turns"])
    turn_id = "%s:t%02d" % (conv["identity"]["conversation_id"], idx)
    phase, frac = _phase_for(conv, idx, want)
    d = conv["dynamics"]
    d["phase"] = phase
    d["closure_pressure"] = round(clamp(frac ** 2 * (0.5 + clamp(settings["controls"].get("closure_aggressiveness", 0.5)))), 4)
    who = participant(conv, speaker)
    cursor_before = copy.deepcopy(conv["cursor"])
    state_before = {"dynamics": copy.deepcopy(conv["dynamics"]),
                    "participants": copy.deepcopy(conv["participants"]),
                    "subject": copy.deepcopy(conv["subject"])}
    prev = conv["turns"][-1] if conv["turns"] else None
    prev_lean = None
    if prev:
        leans = [x.get("lean") for x in prev.get("decisions", []) if x.get("family") in ("RS", "IRS") and x.get("lean") is not None]
        prev_lean = leans[-1] if leans else None
    turn = {"turn_id": turn_id, "index": idx, "speaker": speaker,
            "name": who["name"] if who else speaker, "step": step["id"], "step_label": step.get("label", step["id"]),
            "cycle": conv["cursor"]["cycle"], "phase": phase, "decisions": [], "directions": [],
            "speakerbox": [], "sfx": None, "sfxguy": None, "performance": None, "text": "", "script_index": None,
            "status": "planned", "cursor_before": cursor_before, "state_before": state_before}
    prev_keys = set()                                                         # [s3-flow]
    for _d in (prev or {}).get("decisions") or []:
        if _d.get("family") and _d.get("item"):
            prev_keys.add("%s:%s" % (_d["family"], _d["item"]))
        if _d.get("family") and _d.get("category"):
            prev_keys.add("%s:%s" % (_d["family"], _d["category"]))
    ctx = {"conv": conv, "turn_id": turn_id, "turn_index": idx, "speaker": speaker, "phase": phase,
           "prev_keys": prev_keys, "recent_rounds": set(str(x) for x in (inputs.get("recent_items") or [])),
           "turns_left": want - idx - 1, "controls": settings["controls"],
           "availability": inputs.get("availability") or {},
           "personalities": config.get("personalities") or {},
           "speaker_emotion_cat": (who["emotion"].get("category") if who else ""),
           "prev_lean": prev_lean,
           "event_emotions": _event_emotions(conv, idx)}                     # [s3-events]
    tp = conv.get("topic_plan") or {}                                    # [rng-topics]
    if tp.get("id") and tp.get("turn_index") == idx:
        turn["bank_topic"] = {"id": tp["id"], "text": tp.get("text", ""), "reply": tp.get("reply", "")}
        turn["decisions"].append({"family": "TOPIC", "event_id": tp.get("event_id", ""),
                                  "item": tp["id"], "label": tp.get("text", "")[:90]})
        for _ev in conv["decision_events"]:
            if _ev["event_id"] == tp.get("event_id"):
                _ev["turn_id"], _ev["turn_index"] = turn_id, idx
    elif tp.get("id") and tp.get("reply") and tp.get("turn_index") == idx - 1:
        turn["bank_topic_reply"] = tp["reply"]
    _attach_round_plans(conv, turn, idx, want, speaker)                      # [s3-rounds]
    if str(step.get("topic") or "").strip():                                  # [s3-flow] the operator's own topic
        turn["topic_override"] = " ".join(str(step["topic"]).split())[:400]
        if idx == 0:
            conv["subject"]["topic"] = turn["topic_override"]
            conv["subject"]["authority"] = "operator"
    draws = (config["structure"].get("closing") or {}).get("draws") if closing else step.get("draws")
    es_spec = None
    acts = []
    for spec_draw in draws or []:
        family = spec_draw.get("family")
        if family == "CTS":
            _cts(conv, config, ctx, stream, turn, idx)
            continue
        spec, ev = weighted_decision(conv, config, ctx, stream, family,
                                     tables=spec_draw.get("tables"), closes=bool(spec_draw.get("closes")),
                                     fixed=spec_draw.get("fixed"),                     # [s3-window]
                                     category=spec_draw.get("category"))               # [s3-flow]
        if not spec:
            turn["decisions"].append({"family": family, "event_id": ev["event_id"], "item": None,
                                      "empty": ev["meta"].get("empty")})
            continue
        dec = {"family": family, "event_id": ev["event_id"], "table": spec["table"],
               "category": spec["category"], "item": spec["id"], "label": spec["label"],
               "text": spec.get("text", ""), "lean": spec.get("lean"), "tags": spec.get("tags") or [],
               "cue": spec.get("cue"), "u": (ev.get("rng") or {}).get("u")}
        if family == "ES":
            vdraw = stream.next("ES:intensity")
            arousal = clamp(spec.get("arousal", 0.5))
            intensity = clamp(0.2 + 0.6 * vdraw["u"] + 0.25 * (d["tension"] - 0.5) + 0.2 * (arousal - 0.5), 0.1, 1.0)
            ev["stages"].append({"stage": "intensity", "draw": vdraw,
                                 "rule": "0.2 + 0.6u + tension and arousal terms",
                                 "selected": round(intensity, 3)})
            ev["selected"]["intensity"] = round(intensity, 3)
            dec["intensity"] = round(intensity, 3)
            es_spec = spec
            ctx["speaker_emotion_cat"] = spec["category"]
            if who:
                persisted = who["emotion"].get("category") == spec["category"]
                who["emotion"] = {"table": spec["table"], "category": spec["category"], "id": spec["id"],
                                  "label": spec["label"], "intensity": round(intensity, 3),
                                  "source": "persisted" if persisted else ("reaction" if prev_lean is not None else "rolled"),
                                  "since_turn": idx if not persisted else who["emotion"].get("since_turn", idx),
                                  "dims": {}}
                who["intensity"] = round(intensity, 3)
                who["energy"] = round(clamp(0.7 * who["energy"] + 0.3 * arousal * intensity * 2), 3)
            turn["performance"] = performance_intent(spec, intensity, d)
            if who:
                who["emotion"]["dims"] = turn["performance"]["dims"]
            d["energy"] = round(clamp(0.8 * d["energy"] + 0.2 * turn["performance"]["energy"]), 4)
        else:
            acts.append(spec)
            if who:
                who["recent_actions"] = (who["recent_actions"] + [spec["id"]])[-6:]
                if spec.get("lean") in (1, -1) and prev:
                    other = participant(conv, prev["speaker"])
                    if other:
                        target = other["position"] if spec["lean"] > 0 else -other["position"] - 0.3
                        who["position"] = round(clamp(0.6 * who["position"] + 0.4 * target, -1, 1), 3)
            if spec.get("callback_source") and who:
                who["callbacks"] = (who["callbacks"] + [{"turn": idx, "act": spec["id"]}])[-4:]
            if spec.get("keeps_unresolved") and family in ("RS", "IRS") and spec.get("lean") == -1:
                conv["subject"]["unresolved_points"].append({"turn": idx, "by": speaker, "act": spec["id"]})
                conv["subject"]["unresolved_points"] = conv["subject"]["unresolved_points"][-5:]
            if spec.get("resolves") and conv["subject"]["unresolved_points"]:
                conv["subject"]["unresolved_points"].pop(0)
            if family == "FL" and spec.get("new_topic"):
                conv["cursor"]["pending_topic"] = True
            if family == "FL" and spec.get("keep_initiator"):
                conv["cursor"]["keep_initiator"] = True
        _apply_effects(conv, spec)
        ev["state_after"] = _snapshot(conv, speaker)
        turn["decisions"].append(dec)
        if family != "ES":
            turn["directions"].append({"family": family, "text": spec.get("text", ""), "label": spec["label"]})
    turn["speakerbox"] = _speakerbox_marks(conv, config, settings, ctx, stream, step, turn, inputs)
    turn["speakerbox"] += _speakerbox_acts(conv, config, ctx, turn, acts, inputs)
    turn["sfx"] = _sfx_decision(conv, config, settings, ctx, stream, turn, es_spec, acts)
    turn["sfxguy"] = _sfxguy_decision(conv, config, ctx, turn, inputs)      # [s3-roads]
    turn["tint"] = _tint_decision(conv, settings, ctx, turn, inputs)         # [s3-rewrite]
    # Dynamics that are functions of history rather than of one act.
    recent = [x.get("item") for t in conv["turns"][-6:] for x in t.get("decisions", []) if x.get("family") != "ES"]
    now = [a["id"] for a in acts]
    rep = sum(1 for a in now if a in recent) / float(max(1, len(now)))
    d["repetition_risk"] = round(clamp(0.7 * d["repetition_risk"] + 0.3 * rep), 4)
    d["novelty"] = round(clamp(d["novelty"] * 0.92 + 0.04), 4)
    d["topic_exhaustion"] = round(clamp(d["topic_exhaustion"] + 1.0 / max(4.0, want / max(1, conv["cursor"]["topic_count"]))), 4)
    conv["subject"]["topic_exhaustion"] = d["topic_exhaustion"]
    t = conv["timing"]
    est = t.get("turn_seconds") or t["words_per_turn"] * t["seconds_per_word"]
    turn["estimated_seconds"] = round(est, 2)
    t["elapsed_estimated"] = round(t["elapsed_estimated"] + est, 2)
    if t["target_duration"] > 0:
        t["remaining"] = round(max(0.0, t["target_duration"] - t["elapsed_estimated"]), 2)
    bundle_src = [x["event_id"] for x in turn["decisions"]] + [x["event_id"] for x in turn["speakerbox"]] + [turn["sfx"]["event_id"]]
    if (turn.get("sfxguy") or {}).get("event_id"):
        bundle_src.append(turn["sfxguy"]["event_id"])
    turn["decision_bundle_id"] = "%s:b%s" % (turn_id, digest(bundle_src, 8))
    turn["state_after"] = _snapshot(conv, speaker)
    conv["turns"].append(turn)
    conv["cursor"]["last"] = speaker
    conv["draws"] = stream.n
    return turn


def _cts(conv, config, ctx, stream, turn, idx):
    """CTS: the subject, where System 3 has authority over it.

    Turn 0 speaks the road's own subject - an obligation, recorded as such
    and never drawn over. A later cycle opens on a drawn subject only when
    the previous frame cancelled the topic."""
    before = _snapshot(conv, turn["speaker"])
    if idx == 0 or not conv["cursor"].get("pending_topic"):
        why = ("the road's own subject: %s" % (conv["subject"]["category"] or "the round's material")) if idx == 0 \
            else "the subject carries on (no frame cancelled it)"
        ev = _event(conv, ctx, "CTS", [], {"id": "OBLIGATED" if idx == 0 else "CONTINUE",
                                          "label": conv["subject"]["topic"][:120] or why,
                                          "authority": conv["subject"]["authority"] if idx == 0 else "continuing"},
                    before, meta={"why": why, "drawn": False})
        ev["state_after"] = before
        turn["decisions"].append({"family": "CTS", "event_id": ev["event_id"],
                                  "item": "OBLIGATED" if idx == 0 else "CONTINUE", "label": why})
        return None
    spec, ev = weighted_decision(conv, config, ctx, stream, "CTS")
    conv["cursor"]["pending_topic"] = False
    if not spec:
        turn["decisions"].append({"family": "CTS", "event_id": ev["event_id"], "item": None,
                                  "empty": ev["meta"].get("empty")})
        return None
    conv["cursor"]["topic_count"] += 1
    conv["dynamics"]["topic_exhaustion"] = 0.0
    conv["dynamics"]["novelty"] = round(clamp(conv["dynamics"]["novelty"] + 0.3), 4)
    ev["state_after"] = _snapshot(conv, turn["speaker"])
    dec = {"family": "CTS", "event_id": ev["event_id"], "table": spec["table"], "category": spec["category"],
           "item": spec["id"], "label": spec["label"], "text": spec.get("text", ""),
           "resolver": spec.get("resolver", "direction"), "topic_change": True}
    turn["decisions"].append(dec)
    turn["directions"].append({"family": "CTS", "text": spec.get("text", ""), "label": spec["label"]})
    turn["topic_change"] = True
    if spec.get("category") == "topic":
        # [rng-topics] THE TOPICS DATABASE, RESOLVED. CTS1's "From Topics
        # Database" used to reach the writer as a bare direction - "raises
        # the next subject from the station's topic book" - with no entry,
        # so the writer invented one. It names a real one now, drawn here
        # off the board (the least-sprung weigh most, none twice in a
        # round) and recorded as this event's own stage.
        _used = set(conv.get("topics_used") or [])
        _bank = [t for t in (conv["inputs"].get("topic_bank") or [])
                 if isinstance(t, dict) and t.get("id") and str(t["id"]) not in _used]
        if _bank:
            _d = stream.next("CTS:topic")
            _rows = [{"id": str(t["id"]), "label": " ".join(str(t["text"]).split())[:90], "base": 1.0,
                      "weight": round(1.0 / (1 + max(0, int(t.get("used") or 0))), 4),
                      "why": ["sprung %d time(s)" % int(t.get("used") or 0)]} for t in _bank]
            _k = pick_index([r["weight"] for r in _rows], _d["u"])
            ev["stages"].append(_stage("topic", _rows, _k, _d))
            _t = _bank[_k]
            # no "file": the station stamps turns with a document's name and
            # remembers it as a heard passage, and a board entry is neither
            turn["topic_material"] = {"text": " ".join(str(_t["text"]).split())[:400],
                                      "file": "", "source": "the topics board", "topic_id": str(_t["id"])}
            ev["selected"]["topic"] = {"id": str(_t["id"]), "text": turn["topic_material"]["text"][:120]}
            conv.setdefault("topics_used", []).append(str(_t["id"]))
    if spec.get("resolver") == "speakbox":
        req = {"request_id": "%s:topic" % turn["turn_id"], "kind": "speakbox", "turn_id": turn["turn_id"],
               "turn_index": idx, "mode": "TOPIC", "event_id": ev["event_id"],
               "chars": 700, "resolved": None}
        conv["material_requests"].append(req)
        turn["topic_request"] = req["request_id"]
    return spec


# --- planning ----------------------------------------------------------------

def _topic_decision(conv, settings, stream, inputs, want, open_turns=None, replies=True):
    """[rng-topics] THE OPERATOR'S TOPICS BOARD, THROUGH THE ROULETTE.

    Three recorded draws: whether something off the board comes up in
    this round (the `topics` control), which one (the least-sprung weigh
    most) and on which turn (never the opener or the close; on a call,
    only a turn the protocol leaves open). The plan is kept on the
    aggregate and the turn takes it when it is planned. No board in the
    inputs: nothing is drawn, so older conversations replay unchanged."""
    if conv.get("topic_plan") is not None:
        return None
    bank = [t for t in (inputs.get("topic_bank") or [])
            if isinstance(t, dict) and t.get("id") and str(t.get("text") or "").strip()]
    if not bank:
        return None
    ctx = {"turn_id": "", "turn_index": -1}
    before = _snapshot(conv)
    control = clamp((settings.get("controls") or {}).get("topics", DEFAULT_CONTROLS["topics"]))
    rate = round(TOPIC_RATE_AT_FULL * control, 4)
    meta = {"rate": rate, "control": round(control, 3), "bank": len(bank)}
    if (conv["subject"].get("exchange") or {}).get("opener"):
        conv["topic_plan"] = {}
        return _event(conv, ctx, "TOPIC", [], {"id": "NONE", "label": "the round carries the operator's own exchange"},
                      before, meta=dict(meta, applies=False, why="the operator's own exchange is this round's subject"))
    slots = [i for i in (open_turns if open_turns is not None else range(want))
             if 0 < i < want - 1]
    d = stream.next("TOPIC:dice")
    rows = [{"id": "RAISE", "label": "something off the board comes up", "base": rate, "weight": rate,
             "why": ["topics control %.2f x %.1f" % (control, TOPIC_RATE_AT_FULL)]},
            {"id": "NONE", "label": "nothing off the board this round", "base": round(1 - rate, 4),
             "weight": round(1 - rate, 4), "why": []}]
    pick = pick_index([r["weight"] for r in rows], d["u"])
    stages = [_stage("dice", rows, pick, d)]
    if pick < 0 or rows[pick]["id"] != "RAISE" or not slots:
        conv["topic_plan"] = {}
        why = "" if slots else "no turn in the middle of this round to raise it on"
        return _event(conv, ctx, "TOPIC", stages, {"id": "NONE", "label": "nothing off the board this round"},
                      before, meta=dict(meta, why=why) if why else meta, rng=d)
    d2 = stream.next("TOPIC:item")
    trows = [{"id": str(t["id"]), "label": " ".join(str(t["text"]).split())[:90], "base": 1.0,
              "weight": round(1.0 / (1 + max(0, int(t.get("used") or 0))), 4),
              "why": ["sprung %d time(s)" % int(t.get("used") or 0)]} for t in bank]
    tpick = pick_index([r["weight"] for r in trows], d2["u"])
    stages.append(_stage("item", trows, tpick, d2))
    chosen = bank[tpick]
    reply = " ".join(str(chosen.get("reply") or "").split())[:400] if replies else ""
    if reply:
        slots = [i for i in slots if i + 1 < want] or slots
    d3 = stream.next("TOPIC:turn")
    srows = [{"id": "t%d" % i, "label": "turn %d" % (i + 1), "base": 1.0, "weight": 1.0, "why": []}
             for i in slots]
    spick = pick_index([r["weight"] for r in srows], d3["u"])
    stages.append(_stage("turn", srows, spick, d3))
    plan = {"id": str(chosen["id"]), "text": " ".join(str(chosen["text"]).split())[:400],
            "reply": reply, "turn_index": slots[spick]}
    ev = _event(conv, ctx, "TOPIC", stages, {"id": plan["id"], "label": plan["text"][:90]}, before,
                meta=dict(meta, turn_index=plan["turn_index"], reply=bool(reply)), rng=d2)
    plan["event_id"] = ev["event_id"]
    conv["topic_plan"] = plan
    conv.setdefault("topics_used", []).append(plan["id"])
    return ev


def _length_decision(conv, settings, stream, inputs):
    """[s3-glass] THE ROUND'S LENGTH IS A ROLL. A free round (no slot on
    air, no System 2 budget) had its turn count drawn by the station's own
    random.randint between the desk's banter_min_lines and banter_max_lines.
    That number is System 3's now: one recorded draw over the same range,
    and the station's later sizing (a banked round's extra turns) rides on
    top of it exactly as it rode on the random. A round the slot or System
    2 sized keeps that size: the budget is an obligation, not a roll."""
    if not inputs.get("lines_rolled"):
        # [s3-window] A SLOT-SIZED ROUND FILLS ITS SEGMENT. "making sure dialogue
        # length and banter exchanges are long ... enough to encompass the time
        # segments allocated to meet the talk radio budget goals." The slot's
        # seconds and the road's measured seconds a turn say how many turns
        # fill it; System 3 rolls the count in a band around that fit and the
        # station writes that many. Only when the runtime says the slot gave a
        # budget (budget_roll), so a round sized by hand keeps its size.
        target = float(inputs.get("target_seconds") or 0)
        per = float(inputs.get("turn_seconds") or 0)
        if not (inputs.get("budget_roll") and target > 0 and per > 0):
            return None
        asked = max(2, int(conv["timing"]["turn_budget"]))
        fit = max(2, int(round(target / per)))
        # never shorter than the slot sized it; up to a quarter longer, or up to
        # the segment's fit when the slot underfills it - at most 1.5x the slot
        lo = min(40, asked)
        hi = max(lo, min(40, max(asked + max(1, (asked + 3) // 4), min(fit, int(asked * 1.5)))))
        draw = stream.next("LENGTH:turns")
        n = lo + min(hi - lo, int(draw["u"] * (hi - lo + 1)))
        turns = max(2, min(40, n))
        before = _snapshot(conv, conv["cursor"].get("initiator"))
        ev = _event(conv, {"turn_id": "", "turn_index": -1}, "LENGTH",
                    [{"stage": "dice", "draw": draw,
                      "rule": "fills the segment: the slot asked %d turns; %.0f s at %.1f s a turn fits %d; rolled %d..%d" % (asked, target, per, fit, lo, hi),
                      "selected": n}],
                    {"id": str(n), "label": "%d turns" % n, "rolled": n, "turns": turns},
                    before, meta={"fit": fit, "asked": int(conv["timing"]["turn_budget"]), "final": turns,
                                  "why": "the slot's budget was an obligation; the turns that fill it are now a roll"},
                    rng=draw)
        conv["timing"]["turn_budget"] = turns
        conv["length_roll"] = {"rolled": n, "turns": turns, "event_id": ev["event_id"], "lo": lo, "hi": hi}
        return conv["length_roll"]
    lo = max(2, int(inputs.get("lines_min") or 2))
    hi = max(lo, int(inputs.get("lines_max") or lo))
    base = int(inputs.get("lines_base") or 0) or int(conv["timing"]["turn_budget"])
    draw = stream.next("LENGTH:turns")
    n = lo + min(hi - lo, int(draw["u"] * (hi - lo + 1)))
    turns = max(2, min(40, int(conv["timing"]["turn_budget"]) + (n - base)))
    before = _snapshot(conv, conv["cursor"].get("initiator"))
    ev = _event(conv, {"turn_id": "", "turn_index": -1}, "LENGTH",
                [{"stage": "dice", "draw": draw, "rule": "uniform over %d..%d turns (the desk's banter_min_lines..banter_max_lines)" % (lo, hi),
                  "selected": n}],
                {"id": str(n), "label": "%d turns" % n, "rolled": n, "turns": turns},
                before, meta={"base": base, "asked": int(conv["timing"]["turn_budget"]), "final": turns,
                              "why": "the station's random.randint stood here; the extra turns a banked round "
                                     "adds ride on the roll as they rode on the random"},
                rng=draw)
    conv["timing"]["turn_budget"] = turns
    conv["length_roll"] = {"rolled": n, "turns": turns, "event_id": ev["event_id"], "lo": lo, "hi": hi}
    return conv["length_roll"]


def _round_rows(config, family, spec_filter=None):
    """Every item of a family's enabled tables as candidate rows."""
    rows = []
    for table in _tables_for(config, family):
        for cat in table.get("categories") or []:
            if float(cat.get("weight", 1.0) or 0) <= 0:
                continue
            for item in cat.get("items") or []:
                spec = _spec(table, cat, item)
                if spec.get("enabled") is False:
                    continue
                w = float(item.get("weight", 1.0) or 0) * float(cat.get("weight", 1.0) or 0) * float(table.get("weight", 1.0) or 0)
                if w <= 0:
                    continue
                rows.append({"id": spec["id"], "label": spec.get("label") or spec["id"], "text": spec.get("text", ""),
                             "table": table["id"], "base": round(w, 4), "weight": round(w, 4), "why": []})
    return rows


def _dice_stage(rows_id, rows_label, rate, draw, why):
    rows = [{"id": rows_id, "label": rows_label, "base": round(rate, 4), "weight": round(rate, 4), "why": [why]},
            {"id": "NONE", "label": "not this round", "base": round(1 - rate, 4), "weight": round(1 - rate, 4), "why": []}]
    pick = pick_index([r["weight"] for r in rows], draw["u"])
    return _stage("dice", rows, pick, draw), (pick == 0)


def _round_rolls(conv, config, settings, inputs, want, banter=True):
    """[s3-rounds] THE ROUND'S OWN ROLLS, where dj_banter's prompt randoms stood.

    Four station-side random() calls shaped every one-call round outside the
    Rolodex and against the per-turn ES the running order carried: the hosts'
    tempers (dice_hosts), "at least once X is openly shocked at what the other
    has JUST said", the interjections forced in edgewise while one goes on a
    roll, and whether the station's name is worked in. Each is a recorded
    draw here, on the round's own stream (seed|round) so the turn trajectory
    is unchanged, and each reaches the writer through the running order: the
    tempers in its head, the rest on the turn they landed on. The CARRY the
    runtime handed in is recorded first, so the audit shows what this round
    started from."""
    # one stream per family, so switching a family on or off (the desk's
    # dice_hosts, an empty interjections list) never moves another's dice
    streams = {f: DrawStream(str(conv["seed"]) + "|round:" + f) for f in ("TEMPER", "SHOCK", "INTERJECT", "MENTION", "TRACK_TALK")}
    ctx0 = {"turn_id": "", "turn_index": -1}
    controls = settings.get("controls") or {}
    hosts = [p["actor_id"] for p in conv["participants"] if p["actor_id"] in HOST_SEATS]
    if conv.get("carry"):
        c = conv["carry"]
        before = _snapshot(conv, conv["cursor"].get("initiator"))
        ev = _event(conv, ctx0, "CARRY", [], {"id": "CARRIED", "label": "picks up from the last round (%s, %.0f s ago, x%.2f)"
                                              % (c.get("road") or "a round", c.get("age") or 0, c.get("factor") or 0)},
                    before, meta={"from": c.get("from"), "road": c.get("road"), "age": c.get("age"), "factor": c.get("factor"),
                                  "seats": c.get("seats"), "landing": c.get("landing"), "unresolved": c.get("unresolved"),
                                  "why": "the previous round's ending state, decayed by its age, is this round's start; "
                                         "nothing was drawn"})
        ev["state_after"] = before
        c["event_id"] = ev["event_id"]
    _rewrite_rolls(conv, config, settings, inputs)                         # [s3-rewrite]
    if not inputs.get("round_rolls"):
        # a caller's protocol, a test plan, a conversation stored before these
        # rolls existed: nothing is drawn and the trajectory is the old one
        return
    # TEMPER: one per host seat, the desk's dice_hosts switch still the gate
    rows = _round_rows(config, "TEMPER") if inputs.get("dice_hosts") else []
    if rows and hosts:
        recent = set(str(x) for x in ((conv.get("carry") or {}).get("tempers") or []))
        taken = set()
        for seat in hosts:
            cands = []
            for r in rows:
                row = dict(r, why=list(r["why"]))
                if row["id"] in taken:
                    row["weight"] = 0.0
                    row["why"].append("the other seat has it tonight")
                elif row["id"] in recent:
                    row["weight"] = round(row["weight"] * 0.25, 4)
                    row["why"].append("worn in the last rounds x0.25")
                cands.append(row)
            live = [r for r in cands if r["weight"] > 0] or cands
            draw = streams["TEMPER"].next("TEMPER:%s" % seat)
            k = pick_index([r["weight"] for r in live], draw["u"])
            if k < 0:
                continue
            picked = live[k]
            taken.add(picked["id"])
            before = _snapshot(conv, seat)
            ev = _event(conv, dict(ctx0, speaker=seat), "TEMPER", [_stage("item", live, k, draw)],
                        {"id": picked["id"], "label": picked["label"], "text": picked["text"], "seat": seat,
                         "table": picked["table"], "index": k + 1, "of": len(live)},
                        before, meta={"seat": seat, "why": "the desk's dice_hosts switch is on: the temper %s is caught in "
                                                            "tonight, colouring every turn underneath its own feeling" % seat},
                        rng=draw)
            ev["state_after"] = before
            conv.setdefault("tempers", {})[seat] = {"id": picked["id"], "text": picked["text"], "event_id": ev["event_id"]}
    # SHOCK: whether, which reaction, on which turn
    rows = _round_rows(config, "SHOCK") if want >= 3 else []
    if rows:
        rate = round(clamp(SHOCK_RATE_AT_FULL * clamp(controls.get("shock_beat", DEFAULT_CONTROLS["shock_beat"]))), 4)
        before = _snapshot(conv, conv["cursor"].get("initiator"))
        d1 = streams["SHOCK"].next("SHOCK:dice")
        st1, hit = _dice_stage("BEAT", "one open reaction turns the round", rate, d1,
                               "shock_beat control %.2f x %.1f" % (clamp(controls.get("shock_beat", 0.5)), SHOCK_RATE_AT_FULL))
        stages = [st1]
        sel = {"id": "NONE", "label": "no shock beat this round"}
        meta = {"rate": rate}
        if hit:
            d2 = streams["SHOCK"].next("SHOCK:item")
            k = pick_index([r["weight"] for r in rows], d2["u"])
            stages.append(_stage("item", rows, k, d2))
            slots = list(range(1, max(2, want - 1)))
            srows = [{"id": "t%d" % i, "label": "turn %d" % (i + 1), "base": 1.0, "weight": 1.0, "why": []} for i in slots]
            d3 = streams["SHOCK"].next("SHOCK:turn")
            sp = pick_index([r["weight"] for r in srows], d3["u"])
            stages.append(_stage("turn", srows, sp, d3))
            picked = rows[k]
            sel = {"id": picked["id"], "label": "openly %s on turn %d" % (picked["text"], slots[sp] + 1), "text": picked["text"],
                   "table": picked["table"], "turn_index": slots[sp]}
            meta["turn_index"] = slots[sp]
            conv["shock_plan"] = {"id": picked["id"], "text": picked["text"], "turn_index": slots[sp], "done": False}
        ev = _event(conv, ctx0, "SHOCK", stages, sel, before, meta=meta, rng=d1)
        ev["state_after"] = before
        if conv.get("shock_plan"):
            conv["shock_plan"]["event_id"] = ev["event_id"]
    # INTERJECT: the banter cycle only, hosts only, a round long enough to hold it
    phrases = [" ".join(str(x).split()) for x in (inputs.get("interjections") or []) if str(x or "").strip()]
    table_rows = _round_rows(config, "INTERJECT")
    if banter and want >= 6 and len(hosts) >= 2 and not any(p["actor_id"] in ("C", "E") for p in conv["participants"]) \
            and (phrases or table_rows):
        rate = round(clamp(INTERJECT_RATE_AT_FULL * clamp(controls.get("interjections", DEFAULT_CONTROLS["interjections"]))), 4)
        before = _snapshot(conv, conv["cursor"].get("initiator"))
        d1 = streams["INTERJECT"].next("INTERJECT:dice")
        st1, hit = _dice_stage("ROLL", "one of them goes on a roll and the other gets a word in edgewise", rate, d1,
                               "interjections control %.2f x %.1f" % (clamp(controls.get("interjections", 0.5)), INTERJECT_RATE_AT_FULL))
        stages = [st1]
        sel = {"id": "NONE", "label": "nobody goes on a roll this round"}
        meta = {"rate": rate, "source": "the desk's diatribe_interjections" if phrases else "INTERJECT1"}
        if hit:
            slots = list(range(1, max(2, want - 3)))
            srows = [{"id": "t%d" % i, "label": "turn %d" % (i + 1), "base": 1.0, "weight": 1.0, "why": []} for i in slots]
            d2 = streams["INTERJECT"].next("INTERJECT:turn")
            sp = pick_index([r["weight"] for r in srows], d2["u"])
            stages.append(_stage("turn", srows, sp, d2))
            pool = ([{"id": "p%d" % i, "label": t[:60], "text": t, "base": 1.0, "weight": 1.0, "why": []} for i, t in enumerate(phrases[:60])]
                    if phrases else [dict(r) for r in table_rows])
            chosen = []
            for n in range(min(3, len(pool))):
                live = [r for r in pool if r["id"] not in {c["id"] for c in chosen}]
                d = streams["INTERJECT"].next("INTERJECT:phrase%d" % (n + 1))
                k = pick_index([r["weight"] for r in live], d["u"])
                if k < 0:
                    break
                stages.append(_stage("phrase-%d" % (n + 1), live, k, d))
                chosen.append(live[k])
            sel = {"id": "ROLL", "label": "turn %d runs long; %s" % (slots[sp] + 1, " / ".join(c["text"] for c in chosen)),
                   "turn_index": slots[sp], "phrases": [c["text"] for c in chosen]}
            meta["turn_index"] = slots[sp]
            conv["interject_plan"] = {"turn_index": slots[sp], "phrases": [c["text"] for c in chosen], "done": False}
        ev = _event(conv, ctx0, "INTERJECT", stages, sel, before, meta=meta, rng=d1)
        ev["state_after"] = before
        if conv.get("interject_plan"):
            conv["interject_plan"]["event_id"] = ev["event_id"]
    # A live banter round may briefly talk about the record actually playing.
    # Banked rounds have no reliable record identity and never take this draw.
    record = inputs.get("record") if isinstance(inputs.get("record"), dict) else {}
    if banter and conv["identity"]["road_kind"] == "banter" and not inputs.get("bank") \
            and record.get("id") and record.get("title") and want >= 3 and hosts:
        rate = round(clamp(controls.get("track_talk", DEFAULT_CONTROLS["track_talk"])), 4)
        before = _snapshot(conv, conv["cursor"].get("initiator"))
        d1 = streams["TRACK_TALK"].next("TRACK_TALK:dice")
        st1, hit = _dice_stage("TRACK_TALK", "a passing comment on the record under the banter", rate, d1,
                               "track_talk control %.2f" % rate)
        stages = [st1]
        sel = {"id": "NONE", "label": "no record comment in this round"}
        meta = {"rate": rate, "record": {k: record.get(k) for k in ("id", "title", "artist")}}
        if hit:
            slots = list(range(1, max(2, want - 1)))
            srows = [{"id": "t%d" % i, "label": "turn %d" % (i + 1), "base": 1.0,
                      "weight": 1.0, "why": []} for i in slots]
            d2 = streams["TRACK_TALK"].next("TRACK_TALK:turn")
            sp = pick_index([r["weight"] for r in srows], d2["u"])
            stages.append(_stage("turn", srows, sp, d2))
            sel = {"id": "TRACK_TALK", "label": "%s by %s on turn %d" %
                   (record["title"], record.get("artist") or "unknown artist", slots[sp] + 1),
                   "turn_index": slots[sp], "record": meta["record"]}
            meta["turn_index"] = slots[sp]
            conv["track_talk_plan"] = {"turn_index": slots[sp], "record": meta["record"], "done": False}
        ev = _event(conv, ctx0, "TRACK_TALK", stages, sel, before, meta=meta, rng=d1)
        ev["state_after"] = before
        if conv.get("track_talk_plan"):
            conv["track_talk_plan"]["event_id"] = ev["event_id"]
    # MENTION: the station's name, worked in once
    name = " ".join(str(inputs.get("station_name") or "").split())
    if name and hosts and want >= 3:
        rate = round(clamp(MENTION_RATE_AT_FULL * clamp(controls.get("mention", DEFAULT_CONTROLS["mention"]))), 4)
        before = _snapshot(conv, conv["cursor"].get("initiator"))
        d1 = streams["MENTION"].next("MENTION:dice")
        st1, hit = _dice_stage("MENTION", "the station's name is worked in once", rate, d1,
                               "mention control %.2f x %.1f" % (clamp(controls.get("mention", 0.5)), MENTION_RATE_AT_FULL))
        stages = [st1]
        sel = {"id": "NONE", "label": "the station IDs carry the name this round"}
        meta = {"rate": rate, "name": name}
        if hit:
            slots = list(range(1, max(2, want - 1)))
            srows = [{"id": "t%d" % i, "label": "turn %d" % (i + 1), "base": 1.0, "weight": 1.0, "why": []} for i in slots]
            d2 = streams["MENTION"].next("MENTION:turn")
            sp = pick_index([r["weight"] for r in srows], d2["u"])
            stages.append(_stage("turn", srows, sp, d2))
            sel = {"id": "MENTION", "label": "%s, on turn %d" % (name, slots[sp] + 1), "turn_index": slots[sp]}
            meta["turn_index"] = slots[sp]
            conv["mention_plan"] = {"turn_index": slots[sp], "name": name, "done": False}
        ev = _event(conv, ctx0, "MENTION", stages, sel, before, meta=meta, rng=d1)
        ev["state_after"] = before
        if conv.get("mention_plan"):
            conv["mention_plan"]["event_id"] = ev["event_id"]
    conv["round_rolls"] = {"draws": {f: st.n for f, st in streams.items()}}


def _attach_round_plans(conv, turn, idx, want, speaker):
    """[s3-rounds] The shock beat and the mention land on the first host turn at
    or after the turn they were rolled for (a caller's turn is skipped)."""
    for key, family in (("shock_plan", "SHOCK"), ("mention_plan", "MENTION"),
                        ("track_talk_plan", "TRACK_TALK")):
        plan = conv.get(key)
        if (not isinstance(plan, dict) or plan.get("done") or plan.get("turn_index") is None
                or idx < max(1, int(plan["turn_index"])) or idx >= want - 1 or speaker not in HOST_SEATS
                or turn.get("step") in ("interject", "carry_on")):
            continue
        plan["done"] = True
        plan["attached_index"] = idx
        if family == "SHOCK":
            turn["shock"] = {"id": plan.get("id"), "text": plan.get("text"), "event_id": plan.get("event_id")}
            turn["decisions"].append({"family": "SHOCK", "event_id": plan.get("event_id", ""), "item": plan.get("id"),
                                      "label": "openly %s" % plan.get("text")})
        elif family == "MENTION":
            turn["mention"] = plan.get("name")
            turn["decisions"].append({"family": "MENTION", "event_id": plan.get("event_id", ""), "item": "MENTION",
                                      "label": plan.get("name")})
        else:
            turn["track_talk"] = dict(plan.get("record") or {})
            turn["decisions"].append({"family": "TRACK_TALK", "event_id": plan.get("event_id", ""),
                                      "item": "TRACK_TALK", "label": str((plan.get("record") or {}).get("title") or "record")})
        for _ev in conv["decision_events"]:
            if _ev["event_id"] == plan.get("event_id"):
                _ev["turn_id"], _ev["turn_index"] = turn["turn_id"], idx


def _interject_after(conv, config, settings, stream, want, inputs, seats):
    """[s3-rounds] The turn just planned is the one that runs long: the other
    host gets a word in edgewise as a turn of its own, and the first carries
    straight on over it - two planned turns, alternating, inside the budget,
    so the seat order the bind aligns on is exactly what the writer is told."""
    plan = conv.get("interject_plan")
    if not isinstance(plan, dict) or plan.get("done") or plan.get("turn_index") is None or not conv["turns"]:
        return
    long_turn = conv["turns"][-1]
    if long_turn["index"] < int(plan["turn_index"]) or len(conv["turns"]) + 3 > want:
        return
    if long_turn["speaker"] not in HOST_SEATS or long_turn["step"] in ("interject", "carry_on"):
        return
    other = next((s for s in seats if s in HOST_SEATS and s != long_turn["speaker"]), None)
    if not other:
        return
    plan["done"] = True
    plan["attached_index"] = long_turn["index"]
    long_turn["long_roll"] = True
    t1 = _decide_turn(conv, config, settings, stream, {"id": "interject", "label": "Gets a word in edgewise",
                                                      "draws": [{"family": "ES"}]}, other, want, inputs)
    t1["interject"] = list(plan.get("phrases") or [])
    # the decision rides the turn that runs long - the one the event points at
    long_turn["decisions"].append({"family": "INTERJECT", "event_id": plan.get("event_id", ""), "item": "edgewise",
                                   "label": " / ".join(t1["interject"])})
    t2 = _decide_turn(conv, config, settings, stream, {"id": "carry_on", "label": "Carries on over it",
                                                      "draws": [{"family": "ES"}]}, long_turn["speaker"], want, inputs)
    t2["carry_on"] = True
    for _ev in conv["decision_events"]:
        if _ev["event_id"] == plan.get("event_id"):
            _ev["turn_id"], _ev["turn_index"] = long_turn["turn_id"], long_turn["index"]


# --- [s3-cast] the cast's favourites and the operator's directives ----------

FAV_REST = 0.25          # a favourite that came up lately weighs a quarter
FAV_COPY_RUN = 6         # six words running out of the favourite = it was copied


def _cast_turns(conv):
    """The turns a favourite or a directive may land on: a host seat's own
    turn - never a caller's, never the word in edgewise or the carry-on over
    it, never the SFX Guy's."""
    roles = (conv.get("inputs") or {}).get("roles") or {}
    return [t for t in conv["turns"] if t["speaker"] in HOST_SEATS
            and t.get("step") not in ("interject", "carry_on") and roles.get(t["speaker"]) != "drop"]


def _pool_rows(config, family):
    """Every enabled row with words in a pool family's enabled tables."""
    out = []
    for table in _tables_for(config, family):
        for cat in table.get("categories") or []:
            if float(cat.get("weight", 1.0) or 0) <= 0:
                continue
            for item in cat.get("items") or []:
                if not isinstance(item, dict) or item.get("enabled") is False or not item.get("id"):
                    continue
                text = " ".join(str(item.get("text") or "").split())
                if not text:
                    continue
                w = (float(item.get("weight", 1.0) or 0) * float(cat.get("weight", 1.0) or 0)
                     * float(table.get("weight", 1.0) or 0))
                if w <= 0:
                    continue
                out.append({"item": item, "cat": cat, "table": table["id"], "text": text, "weight": round(w, 4)})
    return out


def _cast_rolls(conv, config, settings, inputs):
    """[s3-cast] Once the turns are planned: does a line the operator liked
    come up (FAV), and which of the operator's directives land, on which turn
    (DIRECTIVE). Everything that used to be stapled to every host prompt as
    "LIVE MIND ADJUSTMENTS" - with no odds and no record - is a recorded
    draw here. Each family on its own stream (each directive on its own), so
    no other draw moves and adding a row never shifts another row's dice.
    Opt-in (inputs.cast_rolls): a conversation stored before replays as it
    was. A re-plan (Mode B) keeps what was rolled and lands it again."""
    if not inputs.get("cast_rolls") or not conv["turns"]:
        return
    if conv.get("cast_rolled"):
        _cast_attach(conv)
        return
    conv["cast_rolled"] = True
    turns = _cast_turns(conv)
    if not turns:
        return
    ctx0 = {"turn_id": "", "turn_index": -1}
    controls = settings.get("controls") or {}
    names = {p["actor_id"]: p.get("name") or p["actor_id"] for p in conv["participants"]}
    at = float(inputs.get("at") or conv.get("created") or 0)

    def turn_rows(ts):
        return [{"id": t["turn_id"], "label": "turn %d (%s)" % (t["index"] + 1, names.get(t["speaker"], t["speaker"])),
                 "base": 1.0, "weight": 1.0, "why": []} for t in ts]

    # FAV: whether one comes up, which, and on which turn
    rows = _pool_rows(config, "FAV")
    if rows:
        stream = DrawStream(str(conv["seed"]) + "|round:FAV")
        rate = round(clamp(controls.get("favorites", DEFAULT_CONTROLS["favorites"])), 4)
        before = _snapshot(conv, conv["cursor"].get("initiator"))
        d1 = stream.next("FAV:dice")
        st1, hit = _dice_stage("FAV", "a line the operator liked comes up", rate, d1, "favorites control %.2f" % rate)
        stages = [st1]
        sel = {"id": "NONE", "label": "no favourite this time"}
        meta = {"rate": rate, "pool": len(rows)}
        if hit:
            recent = set(str(x) for x in (inputs.get("fav_recent") or []))
            cands = []
            for r in rows:
                rid = str(r["item"]["id"])
                w, why = r["weight"], []
                if rid in recent:
                    w = round(w * FAV_REST, 4)
                    why.append("came up lately x%.2f" % FAV_REST)
                cands.append({"id": rid, "label": r["text"][:90], "base": r["weight"], "weight": w, "why": why, "row": r})
            d2 = stream.next("FAV:item")
            k = pick_index([c["weight"] for c in cands], d2["u"])
            if k >= 0:
                stages.append(_stage("item", cands, k, d2))
                trows = turn_rows(turns)
                d3 = stream.next("FAV:turn")
                j = pick_index([r["weight"] for r in trows], d3["u"])
                stages.append(_stage("turn", trows, j, d3))
                row, t = cands[k]["row"], turns[j]
                said = str(row["item"].get("seat") or "")
                plan = {"id": cands[k]["id"], "text": row["text"][:400], "table": row["table"], "seat": said,
                        "said_by": str(row["item"].get("name") or names.get(said) or row["item"].get("who") or ""),
                        "line_id": str(row["item"].get("line_id") or ""), "turn_index": t["index"]}
                conv["fav_plan"] = plan
                sel = {"id": plan["id"], "label": plan["text"][:90], "table": plan["table"], "turn_index": t["index"],
                       "said_by": plan["said_by"], "index": k + 1, "of": len(cands)}
                meta["turn_index"] = t["index"]
        ev = _event(conv, ctx0, "FAV", stages, sel, before, meta=meta, rng=d1)
        ev["state_after"] = before
        if conv.get("fav_plan"):
            conv["fav_plan"]["event_id"] = ev["event_id"]
    # DIRECTIVE: every row its own odds; a hit lands on one of its seat's turns
    spent = inputs.get("directive_spent") if isinstance(inputs.get("directive_spent"), dict) else {}
    plans = []
    for r in _pool_rows(config, "DIRECTIVE"):
        item, cat = r["item"], r["cat"]
        seat = str(item.get("seat") or cat.get("seat") or "*")
        mine = [t for t in turns if seat == "*" or t["speaker"] == seat]
        if not mine:
            continue                   # that seat has no turn here: nothing to roll
        rid = str(item["id"])
        until = float(item.get("until") or 0)
        budget = int(float(item.get("airings") or 0))
        used = int(float(spent.get(rid) or 0))
        if (until and at and until < at) or (budget and used >= budget):
            continue                   # its lifetime is over; the Tables tab shows it expired
        odds = round(clamp(item.get("odds", 1.0)), 4)
        who = "the whole cast" if seat == "*" else names.get(seat, seat)
        before = _snapshot(conv, mine[0]["speaker"])
        stream = DrawStream(str(conv["seed"]) + "|round:DIRECTIVE:" + rid)
        rng, stages = None, []
        if odds >= 1.0:
            hit = True
            stages.append({"stage": "standing", "draw": None, "selected": "IN",
                           "rule": "odds 100%: a standing directive - recorded, not drawn"})
        elif odds <= 0:
            hit = False
            stages.append({"stage": "off", "draw": None, "selected": "OUT", "rule": "odds 0%: never"})
        else:
            rng = stream.next("DIRECTIVE:dice")
            st, hit = _dice_stage("IN", "the directive comes up", odds, rng, "its own odds, %.0f%%" % (odds * 100))
            stages.append(st)
        sel = {"id": "NONE", "label": "not this time: " + r["text"][:80], "row": rid, "seat": seat}
        plan = None
        if hit:
            j = 0
            if len(mine) > 1:
                trows = turn_rows(mine)
                d = stream.next("DIRECTIVE:turn")
                j = pick_index([x["weight"] for x in trows], d["u"])
                stages.append(_stage("turn", trows, j, d))
            t = mine[j]
            plan = {"id": rid, "text": r["text"][:400], "table": r["table"], "seat": seat, "for": who,
                    "turn_index": t["index"]}
            sel = {"id": rid, "label": r["text"][:90], "table": r["table"], "turn_index": t["index"], "seat": seat}
            plans.append(plan)
        ev = _event(conv, ctx0, "DIRECTIVE", stages, sel, before,
                    meta={"seat": seat, "for": who, "odds": odds, "until": until, "airings": budget, "aired": used},
                    rng=rng)
        ev["state_after"] = before
        if plan:
            plan["event_id"] = ev["event_id"]
    if plans:
        conv["directive_plans"] = plans
    _cast_attach(conv)


def _cast_landing(turns, idx, seat=None):
    mine = [t for t in turns if seat in (None, "*") or t["speaker"] == seat]
    if not mine:
        return None
    return next((t for t in mine if t["index"] >= int(idx)), mine[-1])


def _cast_attach(conv):
    """[s3-cast] Land the FAV and DIRECTIVE plans on their turns - again,
    after a re-plan, on the turn now standing at the rolled place."""
    turns = _cast_turns(conv)
    events = {e["event_id"]: e for e in conv["decision_events"]}
    for t in conv["turns"]:
        t.pop("favorite", None)
        t.pop("directives", None)
        t["decisions"] = [d for d in t["decisions"] if d.get("family") not in ("FAV", "DIRECTIVE")]
    fav = conv.get("fav_plan")
    if isinstance(fav, dict):
        t = _cast_landing(turns, fav.get("turn_index", 0))
        if t:
            t["favorite"] = {k: fav.get(k) for k in ("id", "text", "seat", "said_by", "line_id", "event_id")}
            t["decisions"].append({"family": "FAV", "event_id": fav.get("event_id", ""), "item": fav.get("id"),
                                   "label": str(fav.get("text") or "")[:90]})
            ev = events.get(fav.get("event_id"))
            if ev:
                ev["turn_id"], ev["turn_index"] = t["turn_id"], t["index"]
    for plan in conv.get("directive_plans") or []:
        t = _cast_landing(turns, plan.get("turn_index", 0), plan.get("seat"))
        if not t:
            continue
        t.setdefault("directives", []).append({k: plan.get(k) for k in ("id", "text", "seat", "event_id")})
        t["decisions"].append({"family": "DIRECTIVE", "event_id": plan.get("event_id", ""), "item": plan.get("id"),
                               "label": str(plan.get("text") or "")[:90]})
        ev = events.get(plan.get("event_id"))
        if ev:
            ev["turn_id"], ev["turn_index"] = t["turn_id"], t["index"]


def _words(text):
    return re.findall(r"[a-z0-9']+", str(text or "").lower())


def favorite_run(favorite, text):
    """[s3-cast] The longest run of the favourite's words said word for word."""
    a, b = _words(favorite), _words(text)
    if not a or not b:
        return 0
    m = difflib.SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b))
    return int(m.size)


def favorite_copied(favorite, text):
    """[s3-cast] Did the written line repeat its favourite instead of
    answering in its spirit? Six words running, or most of a short one."""
    run = favorite_run(favorite, text)
    n = len(_words(favorite))
    return run >= FAV_COPY_RUN or (n and run >= 3 and run >= 0.8 * n)


# --- [s3-events] what can happen in a segment --------------------------------

EVENT_SEATS = ("caller", "host", "any")
EVENT_PLACES = ("open", "middle", "close", "any")
# call legs the station's contract grades word for word: nothing happens on them
EVENT_FIXED_LEGS = ("answer", "introduce", "greet")
EVENT_AFTER = ("reacts to what just happened on the line - it has gone dead - and takes it back to the "
               "music, in a line or two")


def _event_slot_ok(cat, seat, place, index, want):
    """May a happening of this kind land on this turn? Its seat (the caller,
    a host, anyone), its place in the segment, never the very first turn,
    and an ending never on the last one (someone has to react to it)."""
    kind = str(cat.get("seat") or "any")
    if kind == "caller" and seat not in ("C", "E"):
        return False
    if kind == "host" and seat not in HOST_SEATS:
        return False
    if index <= 0 or place == "fixed":
        return False                  # never the opening, never a leg the call contract checks word by word
    if index < int(cat.get("min_turn") or 1):
        return False
    if cat.get("ends") and index >= want - 1:
        return False
    where = str(cat.get("place") or "middle")
    if where == "any":
        return True
    if place in ("open", "middle", "close"):
        return place == where
    frac = index / float(max(1, want - 1))                  # a cycle round: by position
    return (frac < 0.3) if where == "open" else (frac > 0.75) if where == "close" else (0.2 <= frac <= 0.85)


def _event_rolls(conv, config, settings, inputs, road, slots, allow_end=True):
    """[s3-events] THE SEGMENT'S HAPPENINGS. Every EVENT table that rolls on
    this road offers its kinds of happening (a caller who gets emotional,
    wins a prize, loses the line, is pulled away by what is going on around
    them ...). Each kind is a die at its own odds; a hit draws which variant
    and on which turn (its seat and place allow). At most the table's
    `max_events` land; at most one ENDS the segment, and the plan is cut
    there. Every kind on its own stream, so adding one never moves another.
    `slots` = [(index, seat, place)] of the planned turns (or the turns the
    plan will have). Opt-in (inputs.event_rolls): an older conversation
    replays as it was. Returns {"plans": [...], "ends_at": index or None}."""
    out = {"plans": [], "ends_at": None}
    if not inputs.get("event_rolls") or not slots:
        return out
    want = len(slots)
    ctx0 = {"turn_id": "", "turn_index": -1}
    names = {p["actor_id"]: p.get("name") or p["actor_id"] for p in conv["participants"]}
    avail = inputs.get("availability") or {}
    for table in _tables_for(config, "EVENT"):
        roads = [str(r) for r in (table.get("roads") or [])]
        if roads and road not in roads:
            continue
        cap = int(table.get("max_events", 2) if table.get("max_events") is not None else 2)
        landed = 0
        for cat in table.get("categories") or []:
            if not isinstance(cat, dict) or cat.get("enabled") is False:
                continue
            items = [i for i in (cat.get("items") or []) if isinstance(i, dict) and i.get("enabled") is not False
                     and str(i.get("text") or "").strip() and float(i.get("weight", 1.0) or 0) > 0]
            if not items:
                continue
            key = "%s:%s" % (table["id"], cat["id"])
            odds = round(clamp(cat.get("odds", 0.1)), 4)
            before = _snapshot(conv, conv["cursor"].get("initiator"))
            meta = {"table": table["id"], "kind": cat["id"], "odds": odds, "seat": cat.get("seat", "any"),
                    "place": cat.get("place", "middle"), "ends": bool(cat.get("ends"))}
            missing = [n for n in (cat.get("requires") or []) if not avail.get(n)]
            why = ("no %s material on this road" % missing[0] if missing
                   else "the segment already holds %d happening(s)" % landed if cap and landed >= cap
                   else "the segment already ends on an earlier happening" if cat.get("ends") and out["ends_at"] is not None
                   else "an ending cannot be rolled here" if cat.get("ends") and not allow_end
                   else "")
            if why or odds <= 0:
                ev = _event(conv, ctx0, "EVENT", [], {"id": "NONE", "label": "%s: not rolled" % (cat.get("label") or cat["id"])},
                            before, meta=dict(meta, applies=False, why=why or "odds 0%"))
                ev["state_after"] = before
                continue
            stream = DrawStream(str(conv["seed"]) + "|round:EVENT:" + key)
            d1 = stream.next("EVENT:dice")
            st1, hit = _dice_stage("HAPPENS", "%s happens" % (cat.get("label") or cat["id"]), odds, d1,
                                   "its own odds, %.0f%%" % (odds * 100))
            stages = [st1]
            sel = {"id": "NONE", "label": "%s: not this time" % (cat.get("label") or cat["id"])}
            plan = None
            if hit:
                limit = out["ends_at"] if out["ends_at"] is not None else want
                ok = [(i, seat, place) for (i, seat, place) in slots
                      if i < limit and _event_slot_ok(cat, seat, place, i, want)]
                if not ok:
                    meta["why"] = "it came up, but no turn here is its seat's in its place"
                else:
                    rows = [{"id": str(i.get("id")), "label": str(i.get("label") or i.get("id")),
                             "base": float(i.get("weight", 1.0) or 0), "weight": float(i.get("weight", 1.0) or 0),
                             "why": []} for i in items]
                    d2 = stream.next("EVENT:item")
                    k = pick_index([r["weight"] for r in rows], d2["u"])
                    stages.append(_stage("item", rows, k, d2))
                    trows = [{"id": "t%d" % i, "label": "turn %d (%s)" % (i + 1, names.get(seat, seat)), "base": 1.0,
                              "weight": 1.0, "why": []} for (i, seat, place) in ok]
                    d3 = stream.next("EVENT:turn")
                    j = pick_index([r["weight"] for r in trows], d3["u"])
                    stages.append(_stage("turn", trows, j, d3))
                    item = items[k]
                    at, seat, _place = ok[j]
                    plan = {"table": table["id"], "kind": cat["id"], "kind_label": str(cat.get("label") or cat["id"]),
                            "id": str(item.get("id")), "label": str(item.get("label") or item.get("id")),
                            "text": _legs_words(item.get("text"), inputs)[:400],
                            "after": _legs_words(item.get("after") or cat.get("after") or "", inputs)[:300],
                            "ends": bool(cat.get("ends")), "turn_index": at, "seat": seat,
                            "emotions": dict(item.get("emotions") or cat.get("emotions") or {}),
                            "effects": dict(item.get("effects") or cat.get("effects") or {})}
                    sel = {"id": plan["id"], "label": "%s - %s, turn %d" % (plan["kind_label"], plan["label"], at + 1),
                           "table": table["id"], "category": cat["id"], "turn_index": at, "ends": plan["ends"]}
                    landed += 1
                    if plan["ends"]:
                        out["ends_at"] = at
            ev = _event(conv, ctx0, "EVENT", stages, sel, before, meta=meta, rng=d1)
            ev["state_after"] = before
            if plan:
                plan["event_id"] = ev["event_id"]
                out["plans"].append(plan)
    if out["ends_at"] is not None:
        # a happening rolled for after the line went dead never happens; say so
        for plan in [x for x in out["plans"] if x["turn_index"] > out["ends_at"]]:
            out["plans"].remove(plan)
            for ev in conv["decision_events"]:
                if ev["event_id"] == plan.get("event_id"):
                    ev["meta"]["cut"] = "the segment ended on turn %d, before this could happen" % (out["ends_at"] + 1)
    conv["event_plans"] = out["plans"]
    conv["event_end"] = out["ends_at"]
    return out


def _events_attach(conv):
    """[s3-events] Land the happenings on their turns (again, after a re-plan)."""
    plans = conv.get("event_plans") or []
    events = {e["event_id"]: e for e in conv["decision_events"]}
    by_index = {t["index"]: t for t in conv["turns"]}
    for t in conv["turns"]:
        t.pop("events", None)
        t["decisions"] = [d for d in t["decisions"] if d.get("family") != "EVENT"]
    for plan in plans:
        t = by_index.get(int(plan.get("turn_index", -1)))
        if not t:
            continue
        t.setdefault("events", []).append({k: plan.get(k) for k in ("table", "kind", "kind_label", "id", "label",
                                                                    "text", "ends", "event_id")})
        t["decisions"].append({"family": "EVENT", "event_id": plan.get("event_id", ""), "item": plan.get("id"),
                               "label": "%s - %s" % (plan.get("kind_label"), plan.get("label"))})
        ev = events.get(plan.get("event_id"))
        if ev:
            ev["turn_id"], ev["turn_index"] = t["turn_id"], t["index"]
        if plan.get("ends"):
            t["ends_here"] = True
            nxt = by_index.get(t["index"] + 1)
            if nxt is not None:
                nxt["after_end"] = str(plan.get("after") or EVENT_AFTER)


def _event_emotions(conv, idx):
    """The happening planned for this turn leans its feeling (a caller who
    wins a prize is more likely delighted than bored)."""
    out = {}
    for plan in conv.get("event_plans") or []:
        if int(plan.get("turn_index", -1)) == idx:
            for k, v in (plan.get("emotions") or {}).items():
                try:
                    out[str(k)] = out.get(str(k), 1.0) * float(v)
                except (TypeError, ValueError):
                    pass
    return out


# --- [s3-blocks] every block of a writer prompt is a node ------------------------

def block_rules(config):
    """The config's block section over the defaults (a block the operator
    has never touched keeps its default node)."""
    rules = system3_tables.default_blocks()
    for name, rule in ((config or {}).get("blocks") or {}).items():
        if isinstance(rule, dict):
            rules[str(name)] = dict(rules.get(str(name)) or {}, **rule)
    return rules


def validate_blocks(raw):
    """Refuse a block section that cannot be decided; returns the cleaned copy."""
    if not isinstance(raw, dict):
        raise ValueError("the blocks section is an object: block name -> rule")
    out = {}
    for name, rule in raw.items():
        name = str(name)
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", name):
            raise ValueError("block name %r must be lower_snake_case" % name)
        if not isinstance(rule, dict):
            raise ValueError("block %s: the rule is an object" % name)
        kind = str(rule.get("kind") or "obligation")
        if kind not in BLOCK_KINDS:
            raise ValueError("block %s: kind must be one of %s" % (name, ", ".join(BLOCK_KINDS)))
        clean = dict(rule, kind=kind)
        clean["odds"] = round(clamp(rule.get("odds", 1.0)), 4)
        out[name] = clean
    return out


def decide_blocks(names, config, seed, conv=None, tint_on=False, dial=None, at=None):
    """[s3-blocks] System 3's decision on each marked block of one prompt, in
    order: [{"name", "kind", "keep", "why", "u"?, "event_id"?}]. A roll's die
    is on the prompt's own stream (seed|block), so it never moves a round's
    other draws. With `conv`, each decision is a recorded BLOCK event on the
    conversation; without one (a road System 3 does not plan), the list is the
    record and rides the prompt's history. `dial` may carry a station dial for
    a roll whose odds follow it (rule odds_from: "personality" -> dial value)."""
    rules = block_rules(config)
    stream = DrawStream(str(seed) + "|block")
    out = []
    seen = {}
    for name in names:
        name = str(name)
        seen[name] = seen.get(name, 0) + 1
        rule = rules.get(name)
        rec = {"name": name, "label": str((rule or {}).get("label") or name)}
        if rule is None:
            rec.update(kind="wedge", keep=False, why="no System 3 node claims this block - stripped (a wedge)")
        else:
            kind = str(rule.get("kind") or "obligation")
            rec["kind"] = kind
            if kind == "off":
                rec.update(keep=False, why="switched off in System 3's blocks")
            elif kind == "tint":
                rec.update(keep=bool(tint_on), why=("the crystal tint pass is on" if tint_on
                                                   else "only while a crystal is on and the tint pass is wanted"))
            elif kind == "roll":
                odds = rule.get("odds", 1.0)
                src = str(rule.get("odds_from") or "")
                if src and isinstance(dial, dict) and src in dial:
                    odds = dial[src]
                odds = round(clamp(odds), 4)
                d = stream.next("BLOCK:%s:%d" % (name, seen[name]))
                rec.update(keep=bool(d["u"] < odds), odds=odds, u=d["u"], dice=d["dice"],
                           why="rolled %d against %.0f%%%s" % (d["dice"], odds * 100,
                                                                (" (the %s dial)" % src) if src else ""))
            else:
                rec.update(keep=True, why="an obligation: always sent, recorded, switchable in System 3")
        if conv is not None:
            before = _snapshot(conv, (conv.get("cursor") or {}).get("initiator"))
            ev = _event(conv, {"turn_id": "", "turn_index": -1}, "BLOCK", [],
                        {"id": "KEEP" if rec["keep"] else "STRIP", "label": "%s: %s" % (rec["label"], "sent" if rec["keep"] else "stripped"),
                         "block": name, "kind": rec["kind"]},
                        before, meta={"why": rec["why"], "odds": rec.get("odds"), "u": rec.get("u")},
                        rng=({"u": rec["u"], "dice": rec["dice"], "label": "BLOCK:" + name} if "u" in rec else None))
            ev["state_after"] = before
            rec["event_id"] = ev["event_id"]
        out.append(rec)
    return out


def plan_more(conv, config, until=None, inputs=None):
    """Mode A: plan turns from the cursor up to `until` (the turn budget).

    The PDF's cycle, looped for the segment: Initial -> Response A ->
    Response B -> Initiator's Response -> Response A -> Response B ->
    Frame -> hand the initiator role on. The last turn draws a closing
    move. Resumable: Mode B truncates and calls this again."""
    inputs = inputs if inputs is not None else conv["inputs"]
    settings = conv["settings"]
    stream = DrawStream(conv["seed"], conv.get("draws", 0))
    want = int(until or conv["timing"]["turn_budget"])
    seats = [p["actor_id"] for p in conv["participants"]]
    steps = config["structure"].get("steps") or []
    if not steps:
        raise ValueError("the structure has no steps")
    if not conv["turns"]:
        # [s3-flow] the structure (or the road) may name who opens
        _init = str(config["structure"].get("initiator") or inputs.get("initiator") or "")
        if _init in seats:
            conv["cursor"]["initiator"] = _init
        # [s3-glass] the length first: a free round's turn count is a roll
        if until is None and _length_decision(conv, settings, stream, inputs):
            want = int(conv["timing"]["turn_budget"])
        # [rng-topics] once per round, before its first turn, against the
        # whole budget (Mode B plans a turn at a time).
        _topic_decision(conv, settings, stream, inputs, int(conv["timing"]["turn_budget"] or want))
        # [s3-rounds] tempers, the shock beat, the interjections, the mention -
        # and the CARRY - on the round's own stream
        _round_rolls(conv, config, settings, inputs, int(conv["timing"]["turn_budget"] or want), banter=True)
    guard = 0
    while len(conv["turns"]) < want and guard < 400:
        guard += 1
        cur = conv["cursor"]
        if cur["step"] >= len(steps):
            _handoff(conv, seats, config)
            continue
        step = steps[cur["step"]]
        cur["step"] += 1
        speaker = _speaker_for(conv, step.get("speaker"), seats)
        if speaker is None:
            continue
        if speaker == cur["last"]:
            # Nobody speaks twice in a row (banter_turns' contract). The
            # frame already opened the next cycle when the initiator kept
            # the floor; any other collision skips the step.
            continue
        closing = len(conv["turns"]) == want - 1 and want >= 3
        _decide_turn(conv, config, settings, stream, step, speaker, want, inputs, closing=closing)
        _interject_after(conv, config, settings, stream, want, inputs, seats)      # [s3-rounds]
    conv["draws"] = stream.n
    if not conv.get("event_rolled") and conv["turns"] and inputs.get("event_rolls"):       # [s3-events]
        conv["event_rolled"] = True
        _event_rolls(conv, config, settings, inputs, conv["identity"]["road_kind"],
                     [(t["index"], t["speaker"], "") for t in conv["turns"]], allow_end=False)
    _events_attach(conv)
    _cast_rolls(conv, config, settings, inputs)                                 # [s3-cast]
    return conv


def _handoff(conv, seats, config):
    cur = conv["cursor"]
    cur["cycle"] += 1
    cur["step"] = 0
    if cur.pop("keep_initiator", False) or not config["structure"].get("handoff", True):
        return
    if cur["initiator"] in seats:
        cur["initiator"] = seats[(seats.index(cur["initiator"]) + 1) % len(seats)]
    if cur["initiator"] == cur["last"]:
        # The new initiator spoke the frame: let it open the next cycle too
        # by moving the role one further.
        cur["initiator"] = seats[(seats.index(cur["initiator"]) + 1) % len(seats)]


def plan_scene(inputs, config, settings, seed=None, conversation_id=None):
    conv = new_conversation(inputs, config, settings, seed=seed, conversation_id=conversation_id)
    return plan_more(conv, config, inputs=conv["inputs"])


_PROTOCOL_OPEN = re.compile(r"keeps it going|answers|react", re.I)


def plan_protocol(conv, config, rows, inputs=None):
    """A road whose SHAPE is a contract (the request-line call protocol,
    #1392) keeps it: System 3 adds the emotion to every turn and a response
    act only to the turns the protocol leaves open, never touching a leg
    call_flow_report checks. `rows` are (number, seat, work)."""
    inputs = inputs if inputs is not None else conv["inputs"]
    stream = DrawStream(conv["seed"], conv.get("draws", 0))
    want = len(rows)
    # [rng-topics] a call keeps its legs: only a turn the protocol leaves
    # open may raise something off the board, and in its own words.
    _topic_decision(conv, conv["settings"], stream, inputs, want, replies=False,
                    open_turns=[i for i, (_n, _s, _w) in enumerate(rows) if _PROTOCOL_OPEN.search(_w or "")])
    for number, seat, work in rows:
        seats = [p["actor_id"] for p in conv["participants"]]
        if seat not in seats:
            conv["participants"].append(new_conversation({"seats": [seat]}, config, conv["settings"])["participants"][0])
        open_turn = bool(_PROTOCOL_OPEN.search(work or ""))
        draws = [{"family": "ES"}]
        if open_turn:
            draws.append({"family": "RS"})
        step = {"id": "protocol", "label": "Protocol turn %s" % number, "draws": draws}
        turn = _decide_turn(conv, config, conv["settings"], stream, step, seat, want, inputs)
        turn["protocol"] = str(work or "")[:300]
    conv["draws"] = stream.n
    _cast_rolls(conv, config, conv["settings"], inputs)                         # [s3-cast]
    return conv


def annotate_protocol(conv, sheet):
    """The protocol sheet with each turn's System 3 delivery appended."""
    by_no = {t["index"] + 1: t for t in conv["turns"]}

    def row(match):
        t = by_no.get(int(match.group(1)))
        if not t:
            return match.group(0)
        perf = t.get("performance") or {}
        add = ""
        if perf.get("emotion"):
            add = " [Say it in %s, %s" % (perf["emotion"], _intensity_word(float(perf.get("intensity") or 0)))
            acts = [x["text"] for x in t["directions"] if x["family"] == "RS"]
            if acts:
                add += "; while doing it, " + acts[0]
            add += ".]"
        topic = t.get("bank_topic") or {}                                 # [rng-topics]
        if topic.get("text"):
            add += (" [It puts them in mind of something off the operator's topics board, and "
                    "they bring it up in their own words: %s.]" % json.dumps(sentence_cut(topic["text"], 300)))
        return match.group(0) + add
    return re.sub(r"(?m)^\s*(\d+)\s+[ABCDE]\s+[-–—].*$", row, sheet)


def road_structure(config, road):
    """[s3-calls] The structure System 3 builds `road` from: the config's own,
    else the default (a config saved before road structures has none)."""
    got = (config.get("structures") or {}).get(road)
    return got if isinstance(got, dict) and got.get("legs") else system3_tables.default_structures().get(road)


def _call_words(text, call, extra=None):
    first = str(call.get("first") or "the caller")
    values = {"first": first, "FIRST": first.upper(), "other": str(call.get("other") or "the co-host")}
    values.update(extra or {})
    out = str(text or "")
    for key, val in values.items():
        out = out.replace("{%s}" % key, str(val))
    return out


def plan_call(conv, config, inputs=None):
    """[s3-calls] A request-line call, planned from System 3's own call
    structure: the open legs in order, the middle leg repeated to the turn
    budget (seats alternating back from the landing, so a host speaks just
    before it), then the closing legs - every leg a turn with its own rolls.
    The TOPIC roll may raise something off the board on a middle leg."""
    inputs = inputs if inputs is not None else conv["inputs"]
    call = inputs.get("call") or {}
    st = road_structure(config, "caller") or {}
    legs = [dict(x) for x in st.get("legs") or [] if isinstance(x, dict)]
    opening = [x for x in legs if x.get("place") == "open"]
    middle = [x for x in legs if x.get("place") == "middle"]
    closing = [x for x in legs if x.get("place") == "close"]
    lo, hi = int(st.get("min_turns") or 9), int(st.get("max_turns") or 22)
    want = max(lo, min(int(inputs.get("turns") or 0) or 10, hi))
    fill_n = max(0, want - len(opening) - len(closing)) if middle else 0
    seq = [(leg, leg.get("seat")) for leg in opening]
    for k in range(fill_n):
        leg = middle[k % len(middle)]
        seat = leg.get("seat")
        if seat == "alternate":
            seat = "A" if (fill_n - 1 - k) % 2 == 0 else "C"
        seq.append((leg, seat))
    seq += [(leg, leg.get("seat")) for leg in closing]
    # [s3-events] what happens on this call - before its turns, so a call the
    # roulette ends (the line lost, the caller pulled away) is planned short:
    # up to the turn it ends on, then a host reacting to the dead line
    _ev = _event_rolls(conv, config, conv["settings"], inputs, "caller",
                       [(i, str(seat or "A"), "fixed" if (leg.get("fixed") or leg.get("id") in EVENT_FIXED_LEGS)
                         else str(leg.get("place") or "")) for i, (leg, seat) in enumerate(seq)])
    if _ev["ends_at"] is not None:
        _host_close = [(leg, seat) for leg, seat in seq[_ev["ends_at"] + 1:]
                       if str(seat or "A") in HOST_SEATS and leg.get("place") == "close"]
        seq = seq[:_ev["ends_at"] + 1] + (_host_close[-1:] or [(
            {"id": "after_end", "label": "After the line drops", "place": "close", "seat": "A",
             "act": EVENT_AFTER, "draws": [{"family": "ES"}]}, "A")])
    want = len(seq)
    conv["timing"]["turn_budget"] = want
    conv["call_structure"] = {"id": st.get("id"), "version": st.get("version"), "head": st.get("head", ""),
                              "tail": st.get("tail", ""), "material": st.get("material", ""),
                              "caller_share": st.get("caller_share", 0.38)}
    stream = DrawStream(conv["seed"], conv.get("draws", 0))
    _topic_decision(conv, conv["settings"], stream, inputs, want, replies=False,
                    open_turns=[i for i, (leg, _s) in enumerate(seq) if leg.get("place") == "middle"])
    _round_rolls(conv, config, conv["settings"], inputs, want, banter=False)      # [s3-rounds] tempers, shock, mention
    seats = [p["actor_id"] for p in conv["participants"]]
    for leg, seat in seq:
        seat = str(seat or "A")
        if seat == "B" and "B" not in seats and not call.get("other"):
            seat = "A"
        if seat not in seats:
            conv["participants"].append(new_conversation({"seats": [seat]}, config, conv["settings"])["participants"][0])
            seats.append(seat)
        step = {"id": leg.get("id"), "label": leg.get("label") or leg.get("id"), "draws": leg.get("draws") or [{"family": "ES"}]}
        turn = _decide_turn(conv, config, conv["settings"], stream, step, seat, want, inputs)
        turn["protocol"] = _call_words(leg.get("act"), call)[:400]
        turn["leg"] = leg.get("id")
        turn["place"] = leg.get("place")
    conv["draws"] = stream.n
    _events_attach(conv)                                                        # [s3-events]
    _cast_rolls(conv, config, conv["settings"], inputs)                         # [s3-cast]
    return conv


def render_call_sheet(conv):
    """[s3-calls] THE RUNNING ORDER OF THIS CALL, from System 3's plan: the
    legs call_flow_report reads, each row with the delivery its dice chose,
    the call's own passage where the contract wants it, and the scenario."""
    call = (conv.get("inputs") or {}).get("call") or {}
    st = conv.get("call_structure") or {}
    turns = conv.get("turns") or []
    if not turns:
        return ""
    share = float(st.get("caller_share") or 0.38)
    rows = []
    material_at = max([i for i, t in enumerate(turns) if t.get("place") == "open"] or [0])
    for i, t in enumerate(turns):
        add = _leg_row_add(t)
        rows.append("%2d  %s  - %s%s" % (t["index"] + 1, t["speaker"], t.get("protocol") or "keeps it going.", add))
        if i == material_at and call.get("speakerbox") and st.get("material"):
            rows.append(_call_words(st["material"], call, {"passage": json.dumps(sentence_cut(call["speakerbox"], 300))}))
    head = _call_words(st.get("head") or "", call, {"caller_turns": max(3, int(len(turns) * share))})
    tail = st.get("tail") or ""
    if conv.get("event_end") is not None:                                   # [s3-events]
        tail = ("This call ENDS EARLY, on the turn the running order says: the line goes dead partway through "
                "it, and a host reacts to that on the last turn. The caller does not land their story and nobody "
                "signs them off - they are gone.")
    text = "\n\n" + head + _tempers_line(conv) + "\n" + "\n".join(rows) + "\n" + tail   # [s3-rounds] [s3-events]
    if call.get("scenario_clause"):
        text += "\n" + str(call["scenario_clause"])
    return text


def _leg_row_add(t):
    """The delivery its dice chose, as a running-order row says it: the
    feeling and its strength, the act while doing it, the flow, and a
    board topic the roulette raised on this turn."""
    perf = t.get("performance") or {}
    add = ""
    if perf.get("emotion"):
        add = " [Say it in %s, %s" % (perf["emotion"], _intensity_word(float(perf.get("intensity") or 0)))
        acts = [x["text"] for x in t.get("directions") or [] if x["family"] in ("RS", "IRS")]
        if acts:
            add += "; while doing it, " + acts[0]
        flow = [x["text"] for x in t.get("directions") or [] if x["family"] == "FL"]
        if flow:
            add += "; and " + flow[-1]
        add += ".]"
    topic = t.get("bank_topic") or {}
    if topic.get("text"):
        add += (" [It puts them in mind of something off the operator's topics board, and they "
                "bring it up in their own words: %s.]" % json.dumps(sentence_cut(topic["text"], 300)))
    if any(t.get(k) for k in ("shock", "mention", "favorite", "directives", "events", "after_end")):   # [s3-rounds] [s3-cast] [s3-events]
        add += " [" + _round_adds(t, "the other").lstrip(". ") + ".]"
    return add


def _legs_words(text, inputs):
    """[s3-roads] A leg's act with the round's own names filled in."""
    names = (inputs or {}).get("names") or {}
    call = (inputs or {}).get("call") or {}
    first = str(call.get("first") or names.get("C") or "the caller")
    values = {"host": str(names.get("A") or "the host"), "cohost": str(names.get("B") or "the co-host"),
              "third": str(names.get("D") or "the third seat"), "caller": first, "first": first,
              "FIRST": first.upper(), "other": str(names.get("B") or "the co-host")}
    out = str(text or "")
    for key, val in values.items():
        out = out.replace("{%s}" % key, val)
    return out


def _structure_roll(conv, config, road):
    """[s3-window] WHICH STRUCTURE THIS ROAD RUNS: the road's own, or one of
    its variants - a segment duplicated in the editor and given a weight
    ("duplicate a segment into a variant runnable on the station with
    unique parameters"). One recorded VARIANT draw over the weights. A road
    with no variants draws nothing, so the default trajectory is unchanged."""
    base = road_structure(config, road)
    cands = [(road, base)] if isinstance(base, dict) and base.get("legs") else []
    for key, st in sorted((config.get("structures") or {}).items()):
        if (isinstance(st, dict) and st.get("variant_of") == road and st.get("legs")
                and st.get("enabled", True) is not False):
            cands.append((key, st))
    if len(cands) <= 1:
        return (cands[0][1] if cands else None), None
    weights = [max(0.0, float(st.get("weight") or 1.0)) for _k, st in cands]
    if sum(weights) <= 0:
        weights = [1.0] * len(cands)
    stream = DrawStream(conv["seed"], conv.get("draws", 0))
    draw = stream.next("VARIANT:structure")
    i = pick_index(weights, draw["u"])
    conv["draws"] = stream.n
    total = sum(weights)
    rows = [{"id": k, "label": str(st.get("label") or k), "base": w, "weight": w, "p": round(w / total, 4),
             "why": ["weight %.2f of %.2f" % (w, total)]} for (k, st), w in zip(cands, weights)]
    before = _snapshot(conv, (conv.get("cursor") or {}).get("initiator"))
    ev = _event(conv, {"turn_id": "", "turn_index": -1}, "VARIANT",
                [{"stage": "item", "candidates": rows, "excluded": [], "total": total, "selected": cands[i][0],
                  "selected_index": i + 1, "of": len(cands), "draw": draw}],
                {"table": "structures", "category": road, "category_label": road + " structures",
                 "id": cands[i][0], "label": rows[i]["label"], "index": i + 1, "of": len(cands)},
                before, meta={"why": "the %s road has %d structures on the desk; one weighted draw picks the one "
                                     "this round runs" % (road, len(cands))}, rng=draw)
    conv["variant_roll"] = {"structure": cands[i][0], "event_id": ev["event_id"], "of": len(cands)}
    return cands[i][1], ev


def plan_legs(conv, config, inputs=None, road=None):
    """[s3-roads] A segment planned from its own structure: the open legs
    in order, the middle leg(s) repeated to the turn budget with the seats
    alternating, then the landing - every leg a turn with its own rolls.
    The road's subject stays the road's (CTS OBLIGATED at turn 0). A road
    with no legs structure falls back to the banter cycle."""
    inputs = inputs if inputs is not None else conv["inputs"]
    road = road or conv["identity"]["road_kind"]
    st, _variant = _structure_roll(conv, config, road)                  # [s3-window]
    st = st or {}
    legs = [dict(x) for x in st.get("legs") or [] if isinstance(x, dict)]
    if not legs:
        return plan_more(conv, config, inputs=inputs)
    opening = [x for x in legs if x.get("place") == "open"]
    middle = [x for x in legs if x.get("place") == "middle"]
    closing = [x for x in legs if x.get("place") == "close"]
    lo, hi = max(1, int(st.get("min_turns") or 3)), max(1, int(st.get("max_turns") or 12))
    want = max(lo, min(int(inputs.get("turns") or 0) or lo, hi))
    seats_in = [p["actor_id"] for p in conv["participants"]]
    alt = [str(x) for x in (st.get("alternate_seats") or []) if str(x) in seats_in]
    if not alt:
        alt = ["A", "C"] if "C" in seats_in else [x for x in ("A", "B") if x in seats_in] or seats_in[:2]
    if not alt:
        alt = ["A"]

    def build(fill_n):
        seq = [(leg, str(leg.get("seat") or "A")) for leg in opening]
        last = seq[-1][1] if seq else ""
        for k in range(fill_n):
            leg = middle[k % len(middle)]
            seat = str(leg.get("seat") or "alternate")
            if seat == "alternate":
                i = alt.index(last) if last in alt else -1
                seat = alt[(i + 1) % len(alt)]
            seq.append((leg, seat))
            last = seat
        for leg in closing:
            seat = str(leg.get("seat") or "alternate")
            if seat == "alternate":
                i = alt.index(last) if last in alt else -1
                seat = alt[(i + 1) % len(alt)]
            seq.append((leg, seat))
            last = seat
        return seq

    fill_n = max(0, want - len(opening) - len(closing)) if middle else 0
    seq = build(fill_n)
    # nobody speaks twice in a row (banter_turns' contract): when the
    # alternation lands the last middle turn on the closing seat, one
    # middle turn fewer (or, at the floor, one more) mends the parity.
    def collides(sq):
        return any(sq[i][1] == sq[i + 1][1] for i in range(len(sq) - 1))
    if middle and collides(seq):
        if fill_n > 0 and len(seq) - 1 >= lo:
            seq = build(fill_n - 1)
        elif len(seq) + 1 <= hi:
            seq = build(fill_n + 1)
    # [s3-events] what happens in this segment, before its turns
    _ev = _event_rolls(conv, config, conv["settings"], inputs, road,
                       [(i, str(seat or "A"), "fixed" if leg.get("fixed") else str(leg.get("place") or ""))
                        for i, (leg, seat) in enumerate(seq)])
    if _ev["ends_at"] is not None:
        _host_close = [(leg, seat) for leg, seat in seq[_ev["ends_at"] + 1:]
                       if str(seat or "A") in HOST_SEATS and leg.get("place") == "close"]
        seq = seq[:_ev["ends_at"] + 1] + (_host_close[-1:] or [(
            {"id": "after_end", "label": "After it ends", "place": "close", "seat": "A",
             "act": EVENT_AFTER, "draws": [{"family": "ES"}]}, "A")])
    want = len(seq)
    conv["timing"]["turn_budget"] = want
    conv["road_structure"] = {"id": st.get("id"), "version": st.get("version"), "road": road,
                              "head": st.get("head", ""), "tail": st.get("tail", "")}
    stream = DrawStream(conv["seed"], conv.get("draws", 0))
    if st.get("topics"):
        _topic_decision(conv, conv["settings"], stream, inputs, want, replies=False,
                        open_turns=[i for i, (leg, _s) in enumerate(seq) if leg.get("place") == "middle"])
    _round_rolls(conv, config, conv["settings"], inputs, want, banter=False)      # [s3-rounds]
    seats = [p["actor_id"] for p in conv["participants"]]
    for leg, seat in seq:
        if seat not in seats:
            conv["participants"].append(new_conversation({"seats": [seat]}, config, conv["settings"])["participants"][0])
            seats.append(seat)
        step = {"id": leg.get("id"), "label": leg.get("label") or leg.get("id"),
                "draws": leg.get("draws") or [{"family": "ES"}]}
        turn = _decide_turn(conv, config, conv["settings"], stream, step, seat, want, inputs)
        turn["protocol"] = _legs_words(leg.get("act"), inputs)[:400]
        turn["leg"] = leg.get("id")
        turn["place"] = leg.get("place")
    conv["draws"] = stream.n
    _events_attach(conv)                                                        # [s3-events]
    _cast_rolls(conv, config, conv["settings"], inputs)                         # [s3-cast]
    return conv


def render_legs_sheet(conv):
    """[s3-roads] THE RUNNING ORDER OF THIS SEGMENT, from System 3's plan:
    the legs in the order they were rolled, each row with the delivery its
    dice chose. Same row grammar as the banter and call sheets."""
    st = conv.get("road_structure") or {}
    turns = conv.get("turns") or []
    if not turns:
        return ""
    rows = ["%2d  %s  - %s%s" % (t["index"] + 1, t["speaker"], t.get("protocol") or "keeps it going.",
                                 _leg_row_add(t)) for t in turns]
    who, quoted = _carry_landing(conv)                                        # [s3-carry]
    carry_line = ("\nIt follows straight on from the last exchange, which landed on %s's words: %s - turn 1 picks up "
                  "from there." % (who, quoted)) if quoted else ""
    return ("\n\n" + str(st.get("head") or "") + _tempers_line(conv) + carry_line + "\n" + "\n".join(rows)
            + "\n" + str(st.get("tail") or ""))


def plan_line(conv, config, inputs=None):
    """[s3-roads] A single-voice road (a record link, a station ID, the
    manager's own page, a stock interjection, a produced spot) as System 3
    nodes: one seat, one or more legs from its structure, ES on each - and,
    when the road hands over a list of candidate lines, a LINE draw among
    them with every candidate and its weight recorded. That draw is the
    Rolodex where the station used to call random.choice()."""
    inputs = inputs if inputs is not None else conv["inputs"]
    road = conv["identity"]["road_kind"]
    st = road_structure(config, road) or {}
    legs = [dict(x) for x in st.get("legs") or [] if isinstance(x, dict)] or [
        {"id": "line", "label": "The line", "place": "close", "seat": "A", "act": "says it.",
         "draws": [{"family": "ES"}]}]
    want = max(1, min(len(legs), 8))
    conv["timing"]["turn_budget"] = want
    conv["road_structure"] = {"id": st.get("id"), "version": st.get("version"), "road": road,
                              "head": st.get("head", ""), "tail": st.get("tail", "")}
    stream = DrawStream(conv["seed"], conv.get("draws", 0))
    seats = [p["actor_id"] for p in conv["participants"]]
    for leg in legs[:want]:
        # [s3-line-fix] the speaker the door passed in is the node's seat;
        # the leg's seat is the default for a road that names none. (This
        # read `(leg or seats[0]) if seats else "A"`: the dj's station ID
        # was planned as seat D and its sheet said so - on air, four times.)
        seat = str((seats[0] if seats else "") or leg.get("seat") or "A")
        if seat not in ("A", "B", "C", "D", "E"):
            seat = seats[0] if seats else "A"
        if seat not in seats:
            conv["participants"].append(new_conversation({"seats": [seat]}, config, conv["settings"])["participants"][0])
            seats.append(seat)
        step = {"id": leg.get("id"), "label": leg.get("label") or leg.get("id"),
                "draws": leg.get("draws") or [{"family": "ES"}]}
        turn = _decide_turn(conv, config, conv["settings"], stream, step, seat, want, inputs)
        turn["protocol"] = _legs_words(leg.get("act"), inputs)[:400]
        turn["leg"] = leg.get("id")
        turn["place"] = leg.get("place")
    cands = [c for c in (inputs.get("candidates") or []) if isinstance(c, dict) and c.get("text")]
    if cands:
        rows = []
        for i, c in enumerate(cands[:200]):
            w = float(c.get("weight", 1.0) or 0)
            rows.append({"id": str(c.get("id") or i), "label": str(c.get("text") or "")[:90], "base": w,
                         "weight": max(0.0, w), "why": list(c.get("why") or [])})
        live = [r for r in rows if r["weight"] > 0] or rows
        draw = stream.next("LINE:item")
        k = pick_index([r["weight"] for r in live], draw["u"])
        stage = _stage("item", live, k, draw, [{"id": r["id"], "label": r["label"], "why": "weight 0"}
                                              for r in rows if r["weight"] <= 0])
        t0 = conv["turns"][-1]
        picked = live[k] if k >= 0 else None
        ev = _event(conv, {"turn_id": t0["turn_id"], "turn_index": t0["index"], "speaker": t0["speaker"]},
                    "LINE", [stage], {"id": picked["id"] if picked else None,
                                      "label": picked["label"] if picked else "", "index": k + 1, "of": len(live)},
                    _snapshot(conv, t0["speaker"]),
                    meta={"road": road, "source": str(inputs.get("candidates_from") or "the road's own list")},
                    rng=draw)
        conv["line_choice"] = {"index": (k if k >= 0 else None), "id": picked["id"] if picked else None,
                               "event_id": ev["event_id"], "of": len(live)}
        t0["decisions"].append({"family": "LINE", "event_id": ev["event_id"], "item": conv["line_choice"]["id"],
                                "label": picked["label"] if picked else "", "u": draw["u"]})
    conv["draws"] = stream.n
    if not cands:
        # [s3-cast] a line whose words the writer writes; a drawn stock line is fixed words
        _cast_rolls(conv, config, conv["settings"], inputs)
    return conv


# --- the running order ----------------------------------------------------

def _feel_words(turn):
    perf = turn.get("performance") or {}
    emo = perf.get("emotion") or ""
    return ("%s (%s)" % (emo, _intensity_word(float(perf.get("intensity") or 0)))) if emo else ""


def _carry_landing(conv):
    """[s3-carry] (who, the words) the last round landed on, or ("", "")."""
    landing = ((conv.get("carry") or {}).get("landing") or {})
    text = " ".join(str(landing.get("text") or "").split())
    if not text:
        return "", ""
    who = str(landing.get("name") or landing.get("who") or "the last voice on air")
    return who, json.dumps(sentence_cut(text, 200))


def _carry_lead(conv):
    """[s3-carry] The landing of the last round, for turn 1 to pick up from."""
    who, quoted = _carry_landing(conv)
    if not quoted:
        return ""
    return "picks straight up from where the last exchange landed - %s said: %s - and" % (who, quoted)


def _row_work(turn, conv):
    perf = turn.get("performance") or {}
    emo = perf.get("emotion") or ""
    lead = ""
    exchange = conv["subject"].get("exchange") or {}
    prev0 = conv["turns"][turn["index"] - 1] if turn["index"] and turn["index"] - 1 < len(conv["turns"]) else None
    prev0_name = str((prev0 or {}).get("name") or (prev0 or {}).get("speaker") or "")
    if turn["step"] == "interject":                                           # [s3-rounds]
        feel = _feel_words(turn)
        phrases = ", ".join(json.dumps(x) for x in (turn.get("interject") or [])[:3])
        return ("gets a word in edgewise while %s is still going - only a word or a handful, %s or anything in "
                "that spirit%s. A reaction, not a reply: %s does not stop for it."
                % (prev0_name, phrases or "a bare reaction", (", said in %s" % feel) if feel else "", prev0_name))
    if turn["step"] == "carry_on":                                            # [s3-rounds]
        feel = _feel_words(turn)
        return ("carries straight on over the interruption and finishes the thought they were on - does not "
                "answer %s, does not restart, keeps the head of steam%s." % (prev0_name, (", in %s" % feel) if feel else ""))
    if turn["index"] == 0 and exchange.get("opener"):
        lead = "opens with these exact words, as written: %s" % json.dumps(exchange["opener"])
    elif turn["index"] == 0 and conv["subject"].get("seeded"):
        who, quoted = _carry_landing(conv)                                   # [s3-carry]
        lead = ("opens with the passage above, word for word, as their own speech"
                + (" - as their answer to where the last exchange landed (%s said: %s)" % (who, quoted) if quoted else ""))
    elif turn["index"] == 0:
        carry = _carry_lead(conv)                                            # [s3-carry]
        lead = (carry + " opens the subject") if carry else "opens the subject"
    elif turn.get("topic_change"):
        mat = turn.get("topic_material") or {}
        if mat.get("text"):
            lead = "THE SUBJECT CHANGES HERE: brings up, in their own words: %s" % json.dumps(sentence_cut(mat["text"], 220))
        else:
            dirs = [x["text"] for x in turn["directions"] if x["family"] == "CTS"]
            lead = "THE SUBJECT CHANGES HERE: " + (dirs[0] if dirs else "moves to a new subject")
    elif turn["step"] == "initial":
        lead = "takes the lead and pushes the subject on"
    # "Every line should be a response to the previous statement that was
    # said ... the RNG system is dictating how they feel about the reply
    # that they are replying to." (operator, 2026-09-27) - so a reply names
    # the line it answers, and the rolled emotion is the feeling ABOUT that
    # line, not a mood worn over whatever comes next.
    prev = conv["turns"][turn["index"] - 1] if turn["index"] and turn["index"] - 1 < len(conv["turns"]) else None
    prev_name = str((prev or {}).get("name") or (prev or {}).get("speaker") or "")
    replying = bool(prev) and not turn.get("topic_change")
    feel = ("%s (%s)" % (emo, _intensity_word(float(perf.get("intensity") or 0)))) if emo else ""
    # the operator's answer line: the words are fixed, so no rolled act or
    # flow is laid over them - only the feeling it is said with.
    # [rng-topics] ...and the answer to a "1. / 2." board entry the roulette
    # raised on the turn before, said the same way.
    answer_text = (exchange.get("reply") if turn["index"] == 1 and exchange.get("reply")
                   else turn.get("bank_topic_reply") or "")
    answer_line = replying and bool(answer_text)
    if answer_line:
        desc = ("answers %s with these exact words, as written: %s" % (prev_name, json.dumps(answer_text))
                + (" - feeling %s about it" % feel if feel else ""))
    elif replying:
        # [s3-flow] told what it answers: the act the turn before rolled, and its feeling
        _pa = next((x.get("text") for x in (prev or {}).get("directions") or [] if x.get("family") in ("RS", "IRS")), "")
        _pe = ((prev or {}).get("performance") or {}).get("emotion") or ""
        _what = (" (%s %s%s)" % (prev_name, _pa, (", in %s" % _pe) if _pe else "")) if _pa else ""
        desc = "answers what %s just said%s" % (prev_name, _what) + (", feeling %s about it" % feel if feel else "")
    else:
        desc = ("in %s" % feel) if feel else ""
    acts = "; then ".join(x["text"] for x in turn["directions"] if x["family"] in ("RS", "IRS"))
    if acts and not answer_line:
        desc = (desc + ": " if desc else "") + acts
    flow = [x["text"] for x in turn["directions"] if x["family"] == "FL"]
    if flow and not answer_line:
        desc = (desc + ", and " if desc else "") + flow[-1]
    if turn.get("topic_override"):                                            # [s3-flow]
        lead = ("%s - on this subject, in their own words: %s" % (lead, json.dumps(turn["topic_override"]))
                if lead else "brings up this subject, in their own words: %s" % json.dumps(turn["topic_override"]))
    body = " - ".join(x for x in (lead, desc) if x)
    for sb in turn.get("speakerbox") or []:
        mat = sb.get("material") or {}
        if not mat.get("text"):
            continue
        quoted = json.dumps(sentence_cut(mat["text"], 420))            # [s3-cut]
        if sb["mode"] == "FULL_SWATH":
            body += (". Opens with a speaker-box monologue, reading this out word for word as their "
                     "own words: %s" % json.dumps(sentence_cut(mat["text"], 720)))
        elif sb["mode"] == "PREPEND":
            body += ". Begins by reading this out word for word as their own words: %s" % quoted
        elif sb["mode"] == "APPEND":
            body += ". Ends by reading this out word for word as their own words: %s" % quoted
        elif sb["mode"] == "REFERENCE":
            body += ". Works this in, in their own words: %s" % quoted
    if any(sb["mode"] == "CALLBACK_TO_PRIOR" for sb in turn.get("speakerbox") or []):
        body += ". Calls back to the passage read earlier"
    if replying and not answer_line:
        body += (". Picks up a word or claim from %s's line and takes it somewhere new - "
                 "never hands that line back as the whole turn" % prev_name)
    body += _round_adds(turn, prev_name)                                      # [s3-rounds]
    topic = turn.get("bank_topic") or {}                                  # [rng-topics]
    if topic.get("reply"):
        body += (". Then, as though it has just come to mind, says these exact words, as written: %s"
                 % json.dumps(topic["text"]))
    elif topic.get("text"):
        body += (". It puts them in mind of something off the operator's topics board, and they "
                 "bring it up in their own words: %s" % json.dumps(sentence_cut(topic["text"], 300)))
    return body.strip().rstrip(".") + "."


def _round_adds(turn, prev_name):
    """[s3-rounds] What the round's rolls put on this turn: the shock beat,
    the roll it goes on, the station's name."""
    add = ""
    if turn.get("shock"):
        add += (". HERE %s IS OPENLY %s at what %s just said - says so in as many words - and everything "
                "after this turn is driven by that" % (str(turn.get("name") or turn["speaker"]),
                                                        str(turn["shock"].get("text") or "taken aback").upper(), prev_name or "the other"))
    if turn.get("long_roll"):
        add += (". Goes on a roll here: a rant, a diatribe, a story with a head of steam - well past the length of "
                "the other turns, and it carries on over the interruption that follows")
    if turn.get("mention"):
        add += ". Works the station's name, %s, in naturally here - once, proud of where they work" % turn["mention"]
    for e in turn.get("events") or []:                                        # [s3-events]
        if e.get("ends"):
            add += (". THIS IS WHERE IT ENDS - %s: %s. The line goes dead partway through this turn; "
                    "nothing more is heard from them" % (str(e.get("kind_label") or "it happens").upper(),
                                                         str(e.get("text") or "").strip().rstrip(".")))
        else:
            add += ". WHAT HAPPENS ON THIS TURN (%s): %s" % (str(e.get("kind_label") or "the roulette"),
                                                             str(e.get("text") or "").strip().rstrip("."))
    if turn.get("after_end"):
        add += ". The line has just gone dead: %s" % str(turn["after_end"]).strip().rstrip(".")
    fav = turn.get("favorite") or {}                                          # [s3-cast]
    if fav.get("text"):
        said = ("A LINE OF YOURS" if fav.get("seat") == turn.get("speaker")
                else "A LINE %s SAID" % str(fav.get("said_by") or "ONE OF THE CAST").upper())
        add += (". %s THAT THE OPERATOR LIKED, for its spirit and attitude only: %s - here they say something "
                "NEW in that spirit; they never repeat it and never quote it" % (said, json.dumps(sentence_cut(fav["text"], 300))))
    for d in turn.get("directives") or []:                                    # [s3-cast]
        add += (". THE OPERATOR'S DIRECTIVE FOR %s ON THIS TURN: %s"
                % (str(turn.get("name") or turn.get("speaker") or "").upper(), str(d.get("text") or "").strip().rstrip(".")))
    if turn.get("track_talk"):
        record = turn["track_talk"]
        add += (". Briefly connects the thought just exchanged to the record playing underneath, %s by %s. "
                "This is one passing moment inside the conversation, not a separate introduction or send-off" %
                (json.dumps(str(record.get("title") or "the record")),
                 json.dumps(str(record.get("artist") or "the artist"))))
    return add


def _tempers_line(conv):
    tempers = conv.get("tempers") or {}
    if not tempers:
        return ""
    names = {p["actor_id"]: p.get("name") or p["actor_id"] for p in conv["participants"]}
    parts = ["%s (%s) is %s" % (seat, names.get(seat, seat), t.get("text")) for seat, t in sorted(tempers.items())]
    return ("\nTONIGHT'S TEMPERS (rolled): " + "; ".join(parts) + ". They colour the phrasing, the pacing and what "
            "each of them chooses to react to, underneath each turn's own feeling. Never named out loud.")


def render_sheet(conv):
    """The plan as the numbered running order the writer already follows.

    Same row grammar as #1386's banter_beat_sheet ("%2d  X  - work"), so
    the one-call writer, the banked beat chain (_banter_beat_plan) and the
    rewrite all read it without a second parser."""
    rows = ["%2d  %s  - %s" % (t["index"] + 1, t["speaker"], _row_work(t, conv)) for t in conv["turns"]]
    if not rows:
        return ""
    return ("\n\nTHE RUNNING ORDER OF THIS EXCHANGE. Write exactly these turns, in this order, one line "
            "each, and nothing else. Each line says the feeling to speak in and what the turn does - "
            "perform both, never name them:" + _tempers_line(conv) + "\n" + "\n".join(rows) +
            "\nEvery numbered turn answers the turn above it by name or by quoting a word out of it, and "
            "then says something of its own: no turn repeats or echoes a line already said, "
            "not the other seat's and not its own. The feeling on a row is how that speaker feels "
            "about the line they are answering. "
            "A turn that could be moved three places without anyone noticing is the wrong turn.")


def legacy_rolls(conv):
    """The plan in #1386's roll shape, so the existing paperwork (dice on
    each script line, the inspector) reads System 3 without a new reader."""
    out = []
    for t in conv["turns"]:
        acts = [d for d in t["decisions"] if d.get("family") in ("RS", "IRS") and d.get("item")]
        if not acts:
            continue
        a = acts[-1]
        out.append({"turn": t["index"] + 1, "seat": t["speaker"],
                    "axis": "rebuttal" if a["family"] == "IRS" else "stance",
                    "id": a["item"], "roll": a.get("u"),
                    "hard": (t.get("performance") or {}).get("intensity"),
                    "lean": a.get("lean"), "text": a.get("text"), "answers": t["index"],
                    "s3": turn_ref(conv, t)})
    return out


def turn_ref(conv, t):
    return {"conversation_id": conv["identity"]["conversation_id"], "turn_id": t["turn_id"],
            "bundle_id": t.get("decision_bundle_id"), "revision": conv["identity"]["revision"]}


def turn_stamp(conv, t):
    """What rides a script line: the chain that produced it, compactly."""
    acts = [d for d in t["decisions"] if d.get("item")]
    perf = t.get("performance") or {}
    return {**turn_ref(conv, t), "phase": t["phase"], "step": t["step"],
            "es": perf.get("emotion"), "intensity": perf.get("intensity"),
            "acts": [{"family": d["family"], "id": d["item"], "label": d.get("label")} for d in acts
                     if d["family"] != "ES"],
            "perf": {"dims": perf.get("dims") or {}, "pace": perf.get("pace"),
                     "pause_style": perf.get("pause_style")},
            "speakerbox": [sb["mode"] for sb in t.get("speakerbox") or [] if sb["mode"] != "NONE"],
            "sfx": {k: (t.get("sfx") or {}).get(k) for k in ("play", "placement", "intent", "event_id")},
            # [s3-roads] his node: whether he speaks after this line and how
            "sfxguy": {k: (t.get("sfxguy") or {}).get(k) for k in ("speak", "kind", "order", "event_id")},
            # [s3-rewrite] whether the crystal tint may rhyme this line
            "tint": {k: (t.get("tint") or {}).get(k) for k in ("rhyme", "event_id")},
            # [s3-rounds] what the round's own rolls put on this turn
            "round": {k: True for k in ("shock", "long_roll", "interject", "carry_on", "mention", "track_talk",
                                        "favorite", "directives", "events", "ends_here", "after_end") if t.get(k)}}


# --- validation ---------------------------------------------------------------

CUES = {
    "agree": r"\b(yes|yeah|yep|right|exactly|true|agree|fair|absolutely|good point|you're right|totally)\b",
    "disagree": r"\b(no|nope|nah|wrong|but|not|nonsense|come on|disagree|hardly|isn't|doesn't|don't|can't|won't|never|ridiculous)\b",
    "question": r"\?",
    "humor": r"\b(ha|haha|joke|kidding|funny|laugh|lol|clown|imagine|hilarious)\b|!",
    "concede": r"\b(fine|okay|ok|alright|fair enough|point taken|you win|i'll give you|you're right|touch[eé])\b",
    "insult": r"\b(idiot|dumb|stupid|moron|clown|silly|confused|misinformed|fool|genius)\b",
    "close": r"\b(thanks|thank you|that's it|back to|music|stay with|we'll|next|anyway|moving on|goodnight|up next|leave it there|enough)\b",
}
_PROHIBITED = {
    "markdown": r"(\*\*|__|^#{1,6}\s|```)",
    "url": r"https?://|www\.",
    "stage_direction": r"\*[^*]{1,40}\*|\((?:laughs|sighs|pause|beat|chuckles)[^)]*\)|\[[^\]]{1,40}\]",
    "emoji": "[\U0001F300-\U0001FAFF☀-➿]",
}


def _content_words(text):
    return {w for w in re.findall(r"[a-z']{4,}", str(text or "").lower()) if w not in _STOP}


def _echoes(final_turns):
    """Script indexes of turns that parrot one of the four turns before
    them: the same words, or a short line (8 words or fewer) made mostly
    (80%) of that turn's words. Measured 2026-09-27: one banked round was
    "Shave it." answered by "Shave it? What do you mean by that?" eleven
    times - one line said twenty-two times, aired six times in four hours.
    A long turn that quotes a word back is an answer, not an echo."""
    seen, out = [], []
    for i, (_who, text) in enumerate(final_turns):
        words = re.findall(r"[a-z0-9']+", str(text or "").lower())
        here = set(words)
        key = " ".join(words)
        if words:
            for prev, prev_key in seen[-4:]:
                if not prev:
                    continue
                small = min(len(here), len(prev))
                if key == prev_key or (small <= 8 and len(here & prev) >= 0.8 * small):
                    out.append(i)
                    break
        seen.append((here, key))
    return out


def align(conv, final_turns):
    """Planned turn -> index in the written script, by seat sequence.

    A door can prepend turns and a writer can drop one; a sequence match
    finds the planned turns in what was written without assuming the two
    line up from the top."""
    plan = [t["speaker"] for t in conv["turns"]]
    got = [str(m or "")[:1] for m, _ in final_turns]
    sm = difflib.SequenceMatcher(None, plan, got, autojunk=False)
    mapping = {}
    for block in sm.get_matching_blocks():
        for k in range(block.size):
            mapping[block.a + k] = block.b + k
    return mapping


def validate(conv, final_turns, mapping=None):
    """Deterministic compliance of a written script with the plan.

    Lexical cues only - every judgement says "lexical" so nobody reads it
    as a model's opinion, and an act with no cue is "unchecked"."""
    mapping = align(conv, final_turns) if mapping is None else mapping
    n_plan = len(conv["turns"])
    rows = []
    met = missed = unchecked = 0
    fav_copies = 0                                                            # [s3-cast]
    for t in conv["turns"]:
        at = mapping.get(t["index"])
        row = {"turn_id": t["turn_id"], "planned": t["index"], "script_index": at,
               "speaker": t["speaker"], "checks": []}
        if at is None:
            row["checks"].append({"what": "turn", "result": "missing"})
            rows.append(row)
            continue
        text = str(final_turns[at][1] or "")
        for dec in t["decisions"]:
            if dec.get("family") in ("ES", "CTS") or not dec.get("item"):
                continue
            cue = dec.get("cue")
            if not cue or cue not in CUES:
                row["checks"].append({"what": "%s %s" % (dec["family"], dec["item"]), "result": "unchecked",
                                      "how": "no deterministic test for this act"})
                unchecked += 1
                continue
            hit = bool(re.search(CUES[cue], text, re.I))
            row["checks"].append({"what": "%s %s" % (dec["family"], dec["item"]),
                                  "result": "met" if hit else "missed", "how": "lexical:%s" % cue})
            met += hit
            missed += (not hit)
        for sb in t.get("speakerbox") or []:
            mat = sb.get("material") or {}
            if sb["mode"] in ("PREPEND", "APPEND", "FULL_SWATH") and mat.get("text"):
                want = _content_words(mat["text"])
                have = _content_words(text)
                cover = len(want & have) / float(max(1, len(want)))
                row["checks"].append({"what": "speakerbox %s" % sb["mode"].lower(),
                                      "result": "met" if cover >= 0.5 else "missed",
                                      "how": "content-word coverage %.2f" % cover})
                if cover >= 0.5:
                    met += 1
                else:
                    missed += 1
        for name, pattern in _PROHIBITED.items():
            if re.search(pattern, text, re.I | re.M):
                row["checks"].append({"what": "prohibited:%s" % name, "result": "violated"})
        fav = t.get("favorite") or {}                                         # [s3-cast]
        if fav.get("text"):
            run = favorite_run(fav["text"], text)
            copied = favorite_copied(fav["text"], text)
            fav_copies += bool(copied)
            row["checks"].append({"what": "FAV %s" % fav.get("id"), "result": "violated" if copied else "met",
                                  "how": "the favourite's longest run said word for word: %d words" % run})
        rows.append(row)
    matched = len(mapping)
    turn_ratio = len(final_turns) / float(max(1, n_plan))
    seat_order = matched / float(max(1, n_plan))
    act_rate = met / float(max(1, met + missed)) if (met + missed) else None
    closing_ok = None
    if conv["turns"] and any(d.get("family") == "FL" for d in conv["turns"][-1]["decisions"]) and final_turns:
        closing_ok = bool(re.search(CUES["close"], str(final_turns[-1][1] or ""), re.I))
    violations = sum(1 for r in rows for c in r["checks"] if c["result"] == "violated")
    echo = _echoes(final_turns)
    loop = len(echo) >= 3 and len(echo) >= 0.25 * max(1, len(final_turns))
    if loop:
        violations += 1
    score = (0.4 * seat_order + 0.2 * min(1.0, turn_ratio) +
             0.3 * (act_rate if act_rate is not None else 0.5) +
             0.1 * (1.0 if closing_ok in (True, None) else 0.0))
    score -= min(0.3, 0.05 * violations)
    verdict = "compliant" if score >= 0.7 else "partial" if score >= 0.45 else "non_compliant"
    if loop or fav_copies:
        verdict = "non_compliant"          # an echo loop is not a conversation at any score;
                                           # [s3-cast] a favourite repeated is not its spirit
    return {"at": time.time(), "method": "deterministic/lexical", "planned": n_plan,
            "written": len(final_turns), "matched": matched,
            "turn_ratio": round(turn_ratio, 3), "seat_order": round(seat_order, 3),
            "acts": {"met": met, "missed": missed, "unchecked": unchecked,
                     "rate": None if act_rate is None else round(act_rate, 3)},
            "closing": closing_ok, "violations": violations, "score": round(score, 3),
            "verdict": verdict, "repair_wanted": bool(seat_order < 0.5 or turn_ratio < 0.5 or loop or fav_copies),
            "echo": {"turns": echo, "loop": loop}, "favorite_copies": fav_copies,
            "turns": rows}


def bind(conv, final_turns):
    """Attach the written script to the plan: each planned turn learns its
    script index and words, and the conversation records the validation."""
    mapping = align(conv, final_turns)
    val = validate(conv, final_turns, mapping)
    conv["bindings"] = [{"turn_id": t["turn_id"], "script_index": mapping.get(t["index"])} for t in conv["turns"]]
    for t in conv["turns"]:
        at = mapping.get(t["index"])
        t["script_index"] = at
        if at is not None:
            t["text"] = str(final_turns[at][1] or "")[:2000]
            t["status"] = "generated"
        else:
            t["status"] = "dropped"
    conv["validation"] = val
    conv["status"] = "generated"
    return mapping, val


def compare_shadow(conv, final_turns):
    """Shadow mode: what System 3 would have done against what the legacy
    writer actually did (blueprint section 15). Nothing here reaches air."""
    mapping = align(conv, final_turns)
    val = validate(conv, final_turns, mapping)
    plan_seats = "".join(t["speaker"] for t in conv["turns"])
    got_seats = "".join(str(m or "")[:1] for m, _ in final_turns)
    return {"at": time.time(), "planned_turns": len(conv["turns"]), "actual_turns": len(final_turns),
            "planned_seats": plan_seats, "actual_seats": got_seats,
            "seat_similarity": round(difflib.SequenceMatcher(None, plan_seats, got_seats).ratio(), 3),
            "actual_met_planned_acts": val["acts"], "score_if_planned": val["score"],
            "verdict_if_planned": val["verdict"]}


# --- Mode B: turn by turn --------------------------------------------------

_HEAT = r"\b(furious|outrage|ridiculous|shut up|how dare|liar|hate|insane|unbelievable)\b|!{2,}"


def observe(conv, turn_index, text, seconds=None):
    """Mode B: one written (or rendered) turn comes back. Validate it
    against its intent and move the state by what was actually said."""
    if not (0 <= turn_index < len(conv["turns"])):
        raise IndexError("no planned turn %d" % turn_index)
    t = conv["turns"][turn_index]
    t["text"] = str(text or "")[:2000]
    t["status"] = "generated"
    checks = []
    for dec in t["decisions"]:
        cue = dec.get("cue")
        if dec.get("family") in ("RS", "IRS", "FL") and cue in CUES:
            checks.append({"act": dec["item"], "met": bool(re.search(CUES[cue], t["text"], re.I))})
    delta = {}
    if re.search(CUES["agree"], t["text"], re.I):
        delta["agreement"] = delta.get("agreement", 0) + 0.05
    if re.search(CUES["disagree"], t["text"], re.I):
        delta["agreement"] = delta.get("agreement", 0) - 0.05
    if re.search(_HEAT, t["text"], re.I):
        delta["tension"] = delta.get("tension", 0) + 0.08
    words = len(t["text"].split())
    tim = conv["timing"]
    planned = tim.get("turn_seconds") or tim["words_per_turn"] * tim["seconds_per_word"]
    actual = float(seconds) if seconds else words * tim["seconds_per_word"]
    tim["elapsed_estimated"] = round(tim["elapsed_estimated"] - planned + actual, 2)
    if seconds:
        tim["elapsed_rendered"] = round(tim["elapsed_rendered"] + float(seconds), 2)
    for k, v in delta.items():
        conv["observed_delta"][k] = round(conv["observed_delta"].get(k, 0) + v, 4)
    rec = {"turn_index": turn_index, "turn_id": t["turn_id"], "text": t["text"], "seconds": seconds,
           "words": words, "checks": checks, "delta": delta, "at": time.time()}
    conv["observations"].append(rec)
    return rec


def replan(conv, config, from_index, until=None):
    """Mode B: throw away the plan from `from_index` on and decide it again
    from the state the written turns actually left behind. The RNG stream
    carries on (it is never rewound), so the new draws are new and
    recorded; decision replay re-applies the same observations."""
    if from_index >= len(conv["turns"]):
        return conv
    anchor = conv["turns"][from_index]
    sb = anchor["state_before"]
    conv["dynamics"] = copy.deepcopy(sb["dynamics"])
    conv["participants"] = copy.deepcopy(sb["participants"])
    conv["subject"] = copy.deepcopy(sb["subject"])
    for k, v in conv["observed_delta"].items():
        if k in conv["dynamics"]:
            conv["dynamics"][k] = round(clamp(conv["dynamics"][k] + v), 4)
    conv["cursor"] = copy.deepcopy(anchor["cursor_before"])
    dropped = [t["turn_id"] for t in conv["turns"][from_index:]]
    conv["turns"] = conv["turns"][:from_index]
    conv["material_requests"] = [r for r in conv["material_requests"] if r["turn_id"] not in dropped]
    conv["identity"]["revision"] += 1
    conv.setdefault("replans", []).append({"from": from_index, "dropped": dropped, "at": time.time(),
                                           "revision": conv["identity"]["revision"]})
    for key in ("shock_plan", "mention_plan", "interject_plan"):                # [s3-rounds]
        plan = conv.get(key)
        if isinstance(plan, dict) and plan.get("done") and int(plan.get("attached_index", -1)) >= from_index:
            plan["done"] = False
            plan.pop("attached_index", None)
    return plan_more(conv, config, until=until)


# --- replay -----------------------------------------------------------------

def replay(stored, config):
    """Decision replay: rebuild a conversation from its inputs, seed and
    config and check every draw lands where it did. Material resolution,
    the LLM and TTS are not replayed - their captured outputs are what the
    stored conversation already holds (blueprint section 16)."""
    if stored.get("engine") and stored.get("engine") != ENGINE_VERSION:
        return {"ok": False, "scope": "decision",
                "why": "planned by %s; this station now runs %s, whose draws are made in a different "
                       "order - decision replay holds within one engine version"
                       % (stored.get("engine"), ENGINE_VERSION)}
    if config_hash(config) != stored.get("config_hash"):
        return {"ok": False, "scope": "decision",
                "why": "the config this conversation was planned under is %s; the one supplied is %s"
                       % (stored.get("config_hash"), config_hash(config))}
    conv = new_conversation(stored["inputs"], config, stored["settings"], seed=stored["seed"],
                            conversation_id=stored["identity"]["conversation_id"])
    obs = sorted(stored.get("observations") or [], key=lambda o: o["turn_index"])
    replans = stored.get("replans") or []
    road = str(stored["identity"].get("road_kind") or "banter")
    # [s3-roads] the same planner the road was planned by: a single-voice
    # line, a call from its structure, a segment from its legs, or the cycle
    if road in system3_tables.LINE_ROADS:
        plan_line(conv, config)
    elif road == "caller" and stored.get("call_structure"):
        conv["inputs"]["call"] = dict((stored.get("inputs") or {}).get("call") or {})
        plan_call(conv, config)
    elif stored.get("road_structure"):
        plan_legs(conv, config, road=road)
    elif not replans:
        plan_more(conv, config)
    else:
        until = stored["timing"]["turn_budget"]
        plan_more(conv, config, until=until)
        for rp in replans:
            for o in obs:
                if o["turn_index"] < rp["from"] and not any(x["turn_index"] == o["turn_index"] for x in conv["observations"]):
                    observe(conv, o["turn_index"], o["text"], o.get("seconds"))
            replan(conv, config, rp["from"], until=until)
    a = [(e["family"], (e.get("selected") or {}).get("id"), (e.get("rng") or {}).get("u")) for e in stored["decision_events"]
         if e["family"] != "STATION"]          # [s3-dice-door] drawn by the road before the plan: recorded, not replayed
    b = [(e["family"], (e.get("selected") or {}).get("id"), (e.get("rng") or {}).get("u")) for e in conv["decision_events"]]
    first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None)
    same = a == b
    return {"ok": same, "scope": "decision", "events": len(a), "replayed": len(b),
            "first_difference": None if same else (first if first is not None else min(len(a), len(b))),
            "why": "every draw reproduced" if same else "the replay diverged",
            "conversation": conv if not same else None}


def summary(conv):
    """The list row for a conversation."""
    val = conv.get("validation") or {}
    return {"conversation_id": conv["identity"]["conversation_id"], "trace_id": conv["identity"]["trace_id"],
            "road": conv["identity"]["road_kind"], "mode": conv["mode"], "status": conv.get("status"),
            "created": conv.get("created"), "turns": len(conv["turns"]),
            "events": len(conv["decision_events"]), "seed": conv["seed"],
            "revision": conv["identity"]["revision"], "topic": conv["subject"]["topic"][:120],
            "verdict": val.get("verdict"), "score": val.get("score"),
            "shadow": (conv.get("comparison") or {}).get("seat_similarity"),
            "system2_slot_id": conv["identity"]["system2_slot_id"],
            "generation_mode": conv.get("generation_mode")}

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
FAMILIES = ("CTS", "ES", "RS", "IRS", "FL", "SPEAKERBOX", "SFX", "TOPIC", "SFXGUY", "LINE", "LENGTH")
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
            "personalities": {}}


def config_hash(config):
    keys = ("schema", "tables", "structure", "speakerbox", "sfx", "personalities")
    # [s3-calls] a config saved before road structures keeps its hash
    if "structures" in config:
        keys += ("structures",)
    if "sfxguy" in config:                       # [s3-roads]
        keys += ("sfxguy",)
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
    if family not in ("CTS", "ES", "RS", "IRS", "FL"):
        raise ValueError("table family must be one of CTS, ES, RS, IRS, FL")
    cats = table.get("categories")
    if not isinstance(cats, list) or not cats:
        raise ValueError("a table needs at least one category")
    seen = set()
    out = copy.deepcopy(table)
    out["id"], out["family"] = tid, family
    out["weight"] = max(0.0, float(table.get("weight", 1.0) or 0))
    out["enabled"] = bool(table.get("enabled", True))
    out["version"] = int(table.get("version") or 1)
    for cat in out["categories"]:
        if not isinstance(cat, dict) or not str(cat.get("id") or "").strip():
            raise ValueError("every category needs an id")
        cat["weight"] = max(0.0, float(cat.get("weight", 1.0) or 0))
        items = cat.get("items")
        if not isinstance(items, list) or not items:
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
    return {
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
            "speakerbox", "cooldown_turns", "after_lean", "callback_source")


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
    recent = _recent_items(conv, spec["family"], 6)
    if spec.get("id") in recent:
        reasons.append("used recently x0.4")
        f *= 0.4
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


def weighted_decision(conv, config, ctx, stream, family, tables=None, closes=False, fixed=None):
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
    # Every candidate's effective weight, with its reasons.
    pool = []
    for table in _tables_for(config, family, tables):
        cats = []
        for cat in table.get("categories") or []:
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
    ev = _event(conv, ctx, family, stages, selected, before, rng=draw)
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
    ctx = {"conv": conv, "turn_id": turn_id, "turn_index": idx, "speaker": speaker, "phase": phase,
           "turns_left": want - idx - 1, "controls": settings["controls"],
           "availability": inputs.get("availability") or {},
           "personalities": config.get("personalities") or {},
           "speaker_emotion_cat": (who["emotion"].get("category") if who else ""),
           "prev_lean": prev_lean}
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
                                     fixed=spec_draw.get("fixed"))                     # [s3-window]
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
        # [s3-glass] the length first: a free round's turn count is a roll
        if until is None and _length_decision(conv, settings, stream, inputs):
            want = int(conv["timing"]["turn_budget"])
        # [rng-topics] once per round, before its first turn, against the
        # whole budget (Mode B plans a turn at a time).
        _topic_decision(conv, settings, stream, inputs, int(conv["timing"]["turn_budget"] or want))
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
    conv["draws"] = stream.n
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
    want = len(seq)
    conv["timing"]["turn_budget"] = want
    conv["call_structure"] = {"id": st.get("id"), "version": st.get("version"), "head": st.get("head", ""),
                              "tail": st.get("tail", ""), "material": st.get("material", ""),
                              "caller_share": st.get("caller_share", 0.38)}
    stream = DrawStream(conv["seed"], conv.get("draws", 0))
    _topic_decision(conv, conv["settings"], stream, inputs, want, replies=False,
                    open_turns=[i for i, (leg, _s) in enumerate(seq) if leg.get("place") == "middle"])
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
    text = "\n\n" + head + "\n" + "\n".join(rows) + "\n" + (st.get("tail") or "")
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
    want = len(seq)
    conv["timing"]["turn_budget"] = want
    conv["road_structure"] = {"id": st.get("id"), "version": st.get("version"), "road": road,
                              "head": st.get("head", ""), "tail": st.get("tail", "")}
    stream = DrawStream(conv["seed"], conv.get("draws", 0))
    if st.get("topics"):
        _topic_decision(conv, conv["settings"], stream, inputs, want, replies=False,
                        open_turns=[i for i, (leg, _s) in enumerate(seq) if leg.get("place") == "middle"])
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
    return "\n\n" + str(st.get("head") or "") + "\n" + "\n".join(rows) + "\n" + str(st.get("tail") or "")


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
        seat = str(leg.get("seat") or seats[0] if seats else "A")
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
    return conv


# --- the running order ----------------------------------------------------

def _row_work(turn, conv):
    perf = turn.get("performance") or {}
    emo = perf.get("emotion") or ""
    lead = ""
    exchange = conv["subject"].get("exchange") or {}
    if turn["index"] == 0 and exchange.get("opener"):
        lead = "opens with these exact words, as written: %s" % json.dumps(exchange["opener"])
    elif turn["index"] == 0 and conv["subject"].get("seeded"):
        lead = "opens with the passage above, word for word, as their own speech"
    elif turn["index"] == 0:
        lead = "opens the subject"
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
        desc = "answers what %s just said" % prev_name + (", feeling %s about it" % feel if feel else "")
    else:
        desc = ("in %s" % feel) if feel else ""
    acts = "; then ".join(x["text"] for x in turn["directions"] if x["family"] in ("RS", "IRS"))
    if acts and not answer_line:
        desc = (desc + ": " if desc else "") + acts
    flow = [x["text"] for x in turn["directions"] if x["family"] == "FL"]
    if flow and not answer_line:
        desc = (desc + ", and " if desc else "") + flow[-1]
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
    topic = turn.get("bank_topic") or {}                                  # [rng-topics]
    if topic.get("reply"):
        body += (". Then, as though it has just come to mind, says these exact words, as written: %s"
                 % json.dumps(topic["text"]))
    elif topic.get("text"):
        body += (". It puts them in mind of something off the operator's topics board, and they "
                 "bring it up in their own words: %s" % json.dumps(sentence_cut(topic["text"], 300)))
    return body.strip().rstrip(".") + "."


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
            "perform both, never name them:\n" + "\n".join(rows) +
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
            "sfxguy": {k: (t.get("sfxguy") or {}).get(k) for k in ("speak", "kind", "order", "event_id")}}


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
    if loop:
        verdict = "non_compliant"          # an echo loop is not a conversation at any score
    return {"at": time.time(), "method": "deterministic/lexical", "planned": n_plan,
            "written": len(final_turns), "matched": matched,
            "turn_ratio": round(turn_ratio, 3), "seat_order": round(seat_order, 3),
            "acts": {"met": met, "missed": missed, "unchecked": unchecked,
                     "rate": None if act_rate is None else round(act_rate, 3)},
            "closing": closing_ok, "violations": violations, "score": round(score, 3),
            "verdict": verdict, "repair_wanted": bool(seat_order < 0.5 or turn_ratio < 0.5 or loop),
            "echo": {"turns": echo, "loop": loop},
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
    a = [(e["family"], (e.get("selected") or {}).get("id"), (e.get("rng") or {}).get("u")) for e in stored["decision_events"]]
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

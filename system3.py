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
import conversation_graph

# /4 (2026-09-28, [s3-sb-end]): the prepend-or-append roulette withdraws one of two
# winning passages, so rounds where both win draw differently from /3.
ENGINE_VERSION = "system3-engine/4"
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
FAMILIES = FAMILIES + ("MEMORY",)                                    # [s3-memory] rules, then roulette
FAMILIES = FAMILIES + ("GRAPH",)
FAMILIES = FAMILIES + ("GOLD",)                                      # [s3-gold] a kept line, rolled as a reply
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


LABEL_CHARS = 400                                                    # [whole-words]


def label_cut(text, cap=LABEL_CHARS):
    """[whole-words] a roll's label as the cards and popups show it: whole
    sentences (sentence_cut), never stopped where a character count fell -
    "its important people never get cut off in the middle of sentences"."""
    return sentence_cut(text, cap)


def whole_cut(text, cap):
    """[whole-words:hosts] `text` as it is when it fits in `cap`; past it, cut
    where a sentence ends (failing that a clause, failing that a word). Unlike
    sentence_cut it keeps the text's own line breaks - for prompts laid out."""
    s = str(text or "")
    cap = int(cap or 0)
    if cap <= 0 or len(s) <= cap:
        return s
    head = s[:cap + 1]
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
    space = max(head.rfind(" ", 0, cap), head.rfind("\n", 0, cap))
    return head[:space if space > 0 else cap].rstrip()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest(value, size=16):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()[:size]


# --- configuration ---------------------------------------------------------

BLOCK_KINDS = ("obligation", "roll", "tint", "off")


def default_config():
    structure = system3_tables.default_structure()
    structure["graph"] = conversation_graph.default_graph()
    structures = system3_tables.default_structures()
    for road, item in structures.items():
        # [nodeplan] every road carries its own talk chapter, off until the
        # operator enables it; the caller keeps its protocol macro (plan_call
        # owns the call machinery). A disabled graph is pruned from the hash.
        item["graph"] = (conversation_graph.protocol_graph(road) if road == "caller"
                         else conversation_graph.road_graph(road, item))
    return {"schema": CONFIG_SCHEMA,
            "tables": system3_tables.default_tables(),
            "structure": structure,
            # [s3-calls] one structure per road System 3 builds from its own nodes
            "structures": structures,
            "speakerbox": copy.deepcopy(DEFAULT_SPEAKERBOX),
            "sfx": copy.deepcopy(DEFAULT_SFX),
            # [s3-roads] the SFX Guy's mouth
            "sfxguy": copy.deepcopy(DEFAULT_SFXGUY),
            # [s3-blocks] every block a writer prompt may carry, and what it is
            "blocks": system3_tables.default_blocks(),
            # [s3-split] the SPLIT node: the threshold, the pace, who may take over
            "split": copy.deepcopy(DEFAULT_SPLIT),
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
    if "split" in config:                        # [s3-split]
        keys += ("split",)
    payload = {k: copy.deepcopy(config.get(k)) for k in keys}
    # Dormant editing surfaces do not alter the decision contract. Old
    # conversations keep their original config hash until a graph is enabled.
    structure = payload.get("structure")
    if isinstance(structure, dict) and not (structure.get("graph") or {}).get("enabled"):
        structure.pop("graph", None)
    for item in (payload.get("structures") or {}).values():
        if not isinstance(item, dict):
            continue
        graph = item.get("graph") or {}
        if not graph.get("enabled") or (len(graph.get("nodes") or []) == 1
                                        and (graph["nodes"][0] or {}).get("type") == "protocol"):
            item.pop("graph", None)
    return digest(payload)


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


# [s3-es-emoji] THE BADGE A MESSAGE WEARS for the emotion it was rolled in (the
# Messenger shows it at the bubble's bottom right): the ES category's emoji, and
# the item's own where it has a more specific one (system3_tables._ES_EMOJI).
# Real colour emoji - the one exception to the station's Carbon-icons-only rule.
EMOJI_MAX_POINTS = 8             # code points: a ZWJ sequence or two emoji fit
EMOJI_MAX_UNITS = 16             # UTF-16 units: what the desk's input counts


def clean_emoji(value):
    """[s3-es-emoji] A row's `emoji`, trimmed. Not a string, or longer than
    EMOJI_MAX_POINTS code points / EMOJI_MAX_UNITS UTF-16 units: dropped to ""
    (no badge) - kept as "", so the once-only fill never puts it back."""
    if not isinstance(value, str):
        return ""
    got = value.strip()
    if len(got) > EMOJI_MAX_POINTS or len(got.encode("utf-16-le")) // 2 > EMOJI_MAX_UNITS:
        return ""
    return got


def es_emoji(config, spec):
    """[s3-es-emoji] [category emoji, item emoji] for an ES pick: the item's
    only when it has its own and it differs from its category's; [] when
    neither has one. Read off the table the pick was drawn from - nothing is
    drawn here, so no draw moves."""
    cat = ""
    for t in (config or {}).get("tables") or []:
        if isinstance(t, dict) and t.get("id") == spec.get("table"):
            for c in t.get("categories") or []:
                if isinstance(c, dict) and c.get("id") == spec.get("category"):
                    cat = clean_emoji(c.get("emoji"))
                    break
            break
    own = clean_emoji(spec.get("emoji"))
    return ([cat] if cat else []) + ([own] if own and own != cat else [])


# [s3-es-dir] How far an item's own arousal off its category's moves the voice's
# dims (excitement above, fatigue below), times the turn's intensity scale.
ES_ITEM_VOICE = 1.0


def _es_row(config, spec):
    """[s3-es-dir] (category, item) of an ES pick, as the table holds them."""
    for t in (config or {}).get("tables") or []:
        if isinstance(t, dict) and t.get("id") == spec.get("table"):
            for c in t.get("categories") or []:
                if isinstance(c, dict) and c.get("id") == spec.get("category"):
                    item = next((i for i in c.get("items") or []
                                 if isinstance(i, dict) and i.get("id") == spec.get("id")), None)
                    return c, item
            break
    return None, None


def es_direction(config, spec, name=""):
    """[s3-es-dir] What the writer is told for an ES pick: the item's own words
    (the Tables tab's "what the writer is told this turn does"), else the
    default (system3_tables.ES_DIRECTION), with {feeling} = the item rolled and
    {name} = the seat speaking. Nothing is drawn."""
    _cat, item = _es_row(config, spec)
    text = " ".join(str((item or {}).get("text") or "").split()) or system3_tables.ES_DIRECTION
    feeling = str(spec.get("label") or spec.get("id") or "").strip()
    who = " ".join(str(name or "").split()) or "the speaker"
    return text.replace("{feeling}", feeling).replace("{name}", who)[:400]


# --- [s3-direction] DIRECTION FOR THIS LINE ----------------------------------------
# The operator, 2026-09-29: "the roulette results are used as direction for the
# prompt ... the characters lists then categories and grabbing advanced randomized
# direction" and "I want the emotional acting to be over the top and exaggerated".
# An ES row may carry `acting` - act (the playable verb, in writing terms), blurts
# (first words out, quoted), says (its lexicon), wants (intention and goal) - on
# the category, with the item's own keys over it (the Tables tab).
DIRECTION_LABEL = "DIRECTION FOR THIS LINE"
ACTING_KEYS = ("act", "blurts", "says", "wants")


def es_acting(config, spec):
    """[s3-direction] The acting of an ES pick: the item's `acting` over its
    category's, cleaned ({act, blurts, says, wants}); {} when neither row has
    one. Nothing is drawn."""
    cat, item = _es_row(config, spec)
    out = {}
    for row in (cat, item):
        got = (row or {}).get("acting")
        if not isinstance(got, dict):
            continue
        for k in ACTING_KEYS:
            v = got.get(k)
            if k in ("blurts", "says"):
                v = [" ".join(str(x).split())[:60] for x in (v if isinstance(v, list) else [])
                     if str(x).strip()][:5]
                if v:
                    out[k] = v
            elif str(v or "").strip():
                out[k] = " ".join(str(v).split())[:240]
    return out


def acting_scale(intensity):
    """[s3-direction] How big a line is played, by its ES intensity."""
    x = float(intensity or 0)
    return ("ALL THE WAY UP, over the top and bigger than life" if x >= 0.72
            else "BIG, broad and unmistakable" if x >= 0.4
            else "OUT LOUD, it shows in every word")


def _es_base_arousal(config, spec):
    """[s3-es-dir] The arousal of the category an ES pick was drawn from, or None."""
    cat, _item = _es_row(config, spec)
    if not cat or cat.get("arousal") is None:
        return None
    try:
        return float(cat.get("arousal"))
    except (TypeError, ValueError):
        return None


def _es_line(turn):
    """[s3-es-dir] The ES item's direction stamped on this turn, or "" (a turn
    planned before directions reached the row, or no feeling rolled)."""
    for d in turn.get("decisions") or []:
        if d.get("family") == "ES" and d.get("item"):
            return " ".join(str(d.get("direction") or "").split())
    return ""


def _es_sentence(turn):
    """[s3-es-dir] The direction as a closing sentence, with its leading space."""
    got = _es_line(turn)
    return (" " + (got if got.endswith((".", "!", "?")) else got + ".")) if got else ""


def _speaks_direction(text, direction):
    """[s3-es-dir] Whether written words say a direction aloud: the direction's
    first clause (twelve characters of words or more) inside them - the same
    test as the station's #1462 beat check."""
    def words(value):
        return " ".join(re.findall(r"[a-z0-9']+", str(value or "").lower()))
    core = words(re.split(r"[,.;]", str(direction or ""), 1)[0])
    return len(core) >= 12 and core in words(text)


# [s3-es-voice] HOW A FEELING SOUNDS. The roll "is fed to the intonation engine to
# take place affecting the way the recording is made so they emotionally reflect
# the dialogue" (the operator, 2026-09-28). An ES row's `voice` (the Tables tab;
# defaults in system3_tables._ES_VOICE / _ES_ITEM_VOICE) is the full send; the
# turn's intensity scales it; the station makes it sound (es_voice.py).
ES_VOICE_MULT = ("tempo", "range", "pause")


def clean_es_voice(block):
    """[s3-es-voice] A row's `voice`: numbers only, inside ES_VOICE_BOUNDS,
    unknown keys dropped. None when it is not a block at all."""
    if not isinstance(block, dict):
        return None
    out = {}
    for k in system3_tables.ES_VOICE_KEYS:
        if k not in block:
            continue
        try:
            v = float(block[k])
        except (TypeError, ValueError):
            continue
        if v != v or v in (float("inf"), float("-inf")):
            continue
        lo, hi = system3_tables.ES_VOICE_BOUNDS[k]
        out[k] = round(min(hi, max(lo, v)), 3)
    return out


def es_voice(config, spec):
    """[s3-es-voice] The voice of an ES pick, as the table it came from holds it:
    the category's block with the item's own keys over it. None when neither
    row carries one - the station then reads the feeling's dims alone, as it
    always did. Nothing is drawn."""
    cat, item = _es_row(config, spec)
    base = clean_es_voice((cat or {}).get("voice"))
    own = clean_es_voice((item or {}).get("voice"))
    if base is None and own is None:
        return None
    out = dict(base or {})
    out.update(own or {})
    return out


# [es-floor] the smallest step a listener hears, per key, off neutral (es_probe
# --dsp at the live intensities: under these the categories measured inaudible)
ES_VOICE_FLOOR = {"tempo": 0.05, "pitch": 0.8, "energy": 0.25, "pause": 0.08}
ES_VOICE_NEUTRAL = {"tempo": 1.0, "pitch": 0.0, "range": 1.0, "energy": 0.0, "pause": 1.0, "temp": 0.0}


def voice_intent(block, intensity):
    """[s3-es-voice] A voice block at a turn's intensity. The table is the full
    send; intensity i gets s = 0.35 + 0.65 i of it (the dims' own curve):
    tempo, range and pause as v ** s, pitch, energy and temp as v * s."""
    i = clamp(float(intensity or 0.0))
    s = 0.35 + 0.65 * i
    out = {}
    for k, v in (clean_es_voice(block) or {}).items():
        out[k] = round(v ** s if k in ES_VOICE_MULT else v * s, 4)
        # [es-floor] a key the row moves is heard: at least floor + (full - floor) i
        # off neutral, its sign kept, never past the full send (i = 1, as before)
        n, step = ES_VOICE_NEUTRAL[k], ES_VOICE_FLOOR.get(k)
        full = abs(v - n)
        if step is None or full <= 0.004:
            continue
        want = min(full, max(abs(out[k] - n), step + (full - step) * i))
        out[k] = round(n + (want if v > n else -want), 4)
    return out


def validate_table(table):
    """Refuse a table that cannot be drawn from; returns the cleaned copy."""
    if not isinstance(table, dict):
        raise ValueError("a table is an object")
    tid = str(table.get("id") or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,23}", tid):
        raise ValueError("table id must be a short name such as ES2")
    family = str(table.get("family") or "")
    if family == "MEMORY":                                   # [s3-memory] kinds with rules, how many a round
        return _validate_memory_table(table, tid)
    if family in ("MGRTOPIC", "MGRSUB"):                  # [s3-mgrtopics] the manager's topics, his sub messages
        import system3_mgrtopics
        return system3_mgrtopics.validate_table(table)
    if family in ("MEASURE", "SFXREACT", "CUTIN", "MINIROUND", "HOLD"):      # [outl-families] the meter's tables
        import outlandish
        return outlandish.validate_table(table)
    if family not in ("CTS", "ES", "RS", "IRS", "FL", "TEMPER", "SHOCK", "INTERJECT", "FAV", "DIRECTIVE", "EVENT",
                      "CHANCE", "POOL", "SPEAKERBOX", "RESOLVE", "WRAP", "IL",
                      "TRACK_TALK", "ANGLE", "CALLARC", "CALLSHIFT"):     # [s3-live-event] [s3-callarc]
        raise ValueError("table family must be one of CTS, ES, RS, IRS, FL, TEMPER, SHOCK, INTERJECT, FAV, DIRECTIVE, "
                         "EVENT, CHANCE, POOL, SPEAKERBOX, RESOLVE, WRAP, IL, TRACK_TALK, ANGLE, CALLARC, CALLSHIFT")
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
        if "emoji" in cat:                                   # [s3-es-emoji] the badge, trimmed
            cat["emoji"] = clean_emoji(cat["emoji"])
        if family == "ES" and "voice" in cat:                # [s3-es-voice] how it sounds, in bounds
            _v = clean_es_voice(cat["voice"])
            if _v is None:
                cat.pop("voice")
            else:
                cat["voice"] = _v
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
            if "emoji" in item:                              # [s3-es-emoji] its own badge, trimmed
                item["emoji"] = clean_emoji(item["emoji"])
            if family == "ES" and "voice" in item:           # [s3-es-voice] its own sound, in bounds
                _v = clean_es_voice(item["voice"])
                if _v is None:
                    item.pop("voice")
                else:
                    item["voice"] = _v
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
        "subject": {"topic": whole_cut(subject.get("topic"), 400),
                    "authority": str(subject.get("authority") or "obligated"),
                    "category": str(subject.get("category") or ""),
                    "sources": list(subject.get("sources") or []),
                    "seeded": bool(subject.get("seeded")),
                    "keywords": list(subject.get("keywords") or [])[:12],
                    "active_angle": whole_cut(subject.get("angle"), 300),
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
                                 "text": sentence_cut(landing.get("text"), 400)},
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
    if table.get("event"):                                   # [s3-live-event]
        spec["event"] = str(table["event"])
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
    _ob = (ctx.get("outlandish") or {}).get("boost")                         # [outl-dispute-odds]
    if _ob and spec["family"] in ("RS", "IRS"):
        _om, _ok = _outlandish_mult(spec, _ob)
        if _ok and abs(_om - 1) > 0.005:
            reasons.append("after an outlandish line (%d) %s x%.2f"
                           % (int(ctx["outlandish"].get("score") or 0), _ok, _om))
            f *= _om
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
                         "why": ((["mean eligible item weight %.3f" % mean] if items else [])   # [outl-dispute-why]
                                 + sorted({w for i in items for w in i["why"]
                                           if w.startswith("after an outlandish")})[:2]),
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
    if spec.get("event"):                                    # [s3-live-event]
        selected["event"] = str(spec["event"])
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


def performance_intent(spec, intensity, dynamics, base_arousal=None):
    """ES -> the engine-neutral PerformanceIntent (blueprint section 12).

    `dims` is the station's six-dimension emotional state, which the host
    feeds to performance_vector(state=...) and so to perf_apply on every
    engine's take. The rest are descriptors for adapters that can honour
    them; an adapter that cannot simply ignores them."""
    arousal = clamp(spec.get("arousal", 0.5))
    valence = clamp(spec.get("valence", 0.0), -1.0, 1.0)
    dims = {d: round(clamp(float((spec.get("dims") or {}).get(d) or 0) * (0.35 + 0.65 * intensity)), 3)
            for d in EMOTION_DIMS}
    # [s3-es-dir] THE ITEM REACHES THE VOICE. The dims are the category's; an item
    # whose own arousal sits off its category's (a fury is not an annoyance) moves
    # them: above, more excitement; below, more fatigue - what the station's
    # performance_vector turns into pace, energy and pauses. None: unchanged.
    shift = 0.0 if base_arousal is None else round(arousal - clamp(base_arousal), 3)
    if shift > 0.02:
        dims["excitement"] = round(clamp(dims["excitement"] + ES_ITEM_VOICE * shift * (0.35 + 0.65 * intensity)), 3)
    elif shift < -0.02:
        dims["fatigue"] = round(clamp(dims["fatigue"] - ES_ITEM_VOICE * shift * (0.35 + 0.65 * intensity)), 3)
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
        "dims": dims, "item_shift": shift,                                   # [s3-es-dir]
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
    # [s3-sb-end] PREPEND OR APPEND. "Instead of both winning together, they
    # now have a roulette that is part of the system" (operator, 2026-09-28).
    # Each mark still throws its own d100 against its slider; when the
    # prepend AND the append both win on one line, the SPEAKERBOX table
    # (SBEND1) picks the one that is read and the other is withdrawn, saying
    # why. A config without the table (switched off, deleted, or planned
    # before it existed) reads both, as before - so its replay holds.
    ends = [r for r in _round_rows(config, "SPEAKERBOX") if r["id"] in ("prepend", "append")]
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
            place = hit
            won = (next((x for x in out if x.get("mark") == "prepend" and x.get("mode") not in (None, "NONE")), None)
                   if hit and mark == "append" and ends else None)
            if won is not None:                                           # [s3-sb-end]
                # its own stream (like the tint's and the SFX Guy's), so the
                # roulette never moves another family's dice
                own = DrawStream(str(conv["seed"]) + "|sbend", int(conv.get("sbend_draws") or 0))
                edraw = own.next("SPEAKERBOX:end")
                conv["sbend_draws"] = own.n
                erows = [dict(r, why=[]) for r in ends]
                ek = pick_index([r["weight"] for r in erows], edraw["u"])
                if ek >= 0:
                    chose = erows[ek]["id"]
                    estage = _stage("end", erows, ek, edraw)
                    estage["rule"] = ("both the prepend and the append won their dice on this line; the prepend-or-append "
                                      "roulette (%s) picks the one that is read" % erows[ek]["table"])
                    stages.append(estage)
                    rec["end"] = {"chose": chose, "dice": edraw["dice"], "table": erows[ek]["table"]}
                    if chose == "prepend":
                        place = False
                        rec.update(lost_to="prepend", why="won its dice, but the prepend-or-append roulette chose the "
                                                          "prepend (d100 %d)" % edraw["dice"])
                    else:
                        was = won["mode"]
                        won.update(mode="NONE", lost_to="append", end=dict(rec["end"]),
                                   why="won its dice, but the prepend-or-append roulette chose the append (d100 %d)"
                                       % edraw["dice"])
                        conv["material_requests"][:] = [m for m in conv["material_requests"]
                                                        if m.get("request_id") != won.get("request_id")]
                        won.pop("request_id", None)
                        used -= 1
                        pev = next((e for e in conv["decision_events"] if e["event_id"] == won.get("event_id")), None)
                        if pev is not None:
                            pev["stages"].append({"stage": "end", "draw": None, "selected": "APPEND",
                                                  "rule": "withdrawn: this line's append won its dice too, and the "
                                                          "prepend-or-append roulette (%s, d100 %d) chose the append"
                                                          % (erows[ek]["table"], edraw["dice"])})
                            pev["selected"] = {"id": "NONE", "label": "withdrawn: the roulette chose the append",
                                               "mark": "prepend", "was": was}
                            pev.setdefault("meta", {})["why"] = won["why"]
                        rec["_withdrew"] = pev
            if place and used >= int(sb.get("max_inline", 2)):
                rec.update(why="a hit, but this round already carries %d inline passages" % used)
            elif place and mark == "full":
                rec["mode"] = "FULL_SWATH"
                used += 1
                opened = True
                stages.append({"stage": "mode", "draw": None, "selected": "FULL_SWATH",
                               "rule": "the full-swath dial opens the round with a speaker-box monologue the "
                                       "initiator reads out; the next turn answers it"})
            elif place:
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
        if rec.get("lost_to"):                                            # [s3-sb-end]
            sel["label"] = "withdrawn: the roulette chose the %s" % rec["lost_to"]
        ev = _event(conv, dict(ctx, turn_id=turn["turn_id"], turn_index=turn["index"]),
                    "SPEAKERBOX", stages, sel, before,
                    meta={"mark": mark, "rate": rec["rate"], "applies": rec["applies"],
                          "why": rec["why"], "insertion_point": "%s turn %d" % (mark, turn["index"] + 1),
                          **({"end": rec["end"]} if rec.get("end") else {})},
                    rng=rng)
        rec["event_id"] = ev["event_id"]
        _pev = rec.pop("_withdrew", None)                                 # [s3-sb-end]
        if _pev is not None:
            _pev["stages"][-1]["decided_in"] = ev["event_id"]
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
    _outl = _outlandish_ctx(conv, config, prev, inputs, idx)                  # [outl-dispute] the line before, measured
    if _outl:
        ctx["outlandish"] = _outl
    tp = conv.get("topic_plan") or {}                                    # [rng-topics]
    if tp.get("id") and tp.get("turn_index") == idx:
        turn["bank_topic"] = {"id": tp["id"], "text": tp.get("text", ""), "reply": tp.get("reply", "")}
        turn["decisions"].append({"family": "TOPIC", "event_id": tp.get("event_id", ""),
                                  "item": tp["id"], "label": label_cut(tp.get("text", ""))})
        for _ev in conv["decision_events"]:
            if _ev["event_id"] == tp.get("event_id"):
                _ev["turn_id"], _ev["turn_index"] = turn_id, idx
    elif tp.get("id") and tp.get("reply") and tp.get("turn_index") == idx - 1:
        turn["bank_topic_reply"] = tp["reply"]
    _attach_round_plans(conv, turn, idx, want, speaker)                      # [s3-rounds]
    try:                                                                      # [s3-gold:decide]
        import sys as _sys
        import system3_gold
        system3_gold.decide(_sys.modules[__name__], conv, config, turn, idx, want, inputs, closing)
    except ImportError:
        pass
    except Exception as _gexc:  # noqa: BLE001 - a gold fault never costs the round; it is kept on it
        conv.setdefault("faults", []).append({"where": "gold roll", "error": repr(_gexc)[:200]})
    if str(step.get("topic") or "").strip():                                  # [s3-flow] the operator's own topic
        turn["topic_override"] = sentence_cut(step["topic"], 400)
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
            # [s3-es-emoji] the badge the message wears (the Messenger, bottom right):
            # [category, item] off the table the pick came from - nothing is drawn
            dec["emoji"] = es_emoji(config, spec)
            # [s3-es-dir] what the writer is told for this feeling: the item's own words
            dec["direction"] = es_direction(config, spec, turn["name"])
            dec["acting"] = es_acting(config, spec)                           # [s3-direction] how it is played
            dec["text"] = ev["selected"]["text"] = dec["direction"]
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
            turn["performance"] = performance_intent(spec, intensity, d,
                                                     base_arousal=_es_base_arousal(config, spec))   # [s3-es-dir]
            _voice = es_voice(config, spec)                                  # [s3-es-voice] how it sounds
            if _voice is not None:
                turn["performance"]["voice"] = voice_intent(_voice, intensity)
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
        _material_mark(ev, spec, inputs)                                      # [s3-material]
        if family != "ES":
            _said = _direction_text(spec, inputs)
            ev["selected"]["prompt"] = _said                                  # [prompt-share] its words for the writer
            turn["directions"].append({"family": family, "text": _said, "label": spec["label"]})
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


# [s3-material] The rows that name something the station holds - the last
# thing the manager said from upstairs, a piece off the gallery wall, what
# people online are saying - were switched off for good (availability False)
# because a bare direction ("brings up the last thing the manager said")
# made the writer invent it. The runtime hands the material in now; a row
# that needs it is eligible only when it is there, and carries it.
MATERIAL_KINDS = ("manager", "gallery", "research")


def _material_for(spec, inputs):
    """(kind, material) the row needs and the road holds, else (None, None)."""
    mat = (inputs or {}).get("material") or {}
    for need in spec.get("requires") or []:
        got = mat.get(need)
        if need in MATERIAL_KINDS and isinstance(got, dict) and str(got.get("text") or "").strip():
            return need, got
    return None, None


def _direction_text(spec, inputs):
    """The row's direction, with the material it names when it names one."""
    text = spec.get("text", "")
    kind, got = _material_for(spec, inputs)
    if got:
        text = "%s - %s: %s" % (text, got.get("label") or kind,
                                json.dumps(sentence_cut(str(got["text"]), 320)))
    return text


def _material_mark(ev, spec, inputs):
    kind, got = _material_for(spec, inputs)
    if got:
        ev["selected"]["material"] = {"kind": kind, "label": label_cut(got.get("label") or kind),
                                      "text": label_cut(got["text"]), "ref": str(got.get("ref") or "")[:120],
                                      "key": str(got.get("key") or "")[:140]}   # [research-pop] the search it used


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
                                          "label": label_cut(conv["subject"]["topic"]) or why,
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
    if spec.get("event"):                                    # [s3-live-event]
        dec["event"] = str(spec["event"])
    turn["decisions"].append(dec)
    _material_mark(ev, spec, conv["inputs"])                                  # [s3-material]
    _said = _direction_text(spec, conv["inputs"])
    ev["selected"]["prompt"] = _said                                          # [prompt-share]
    turn["directions"].append({"family": "CTS", "text": _said, "label": spec["label"]})
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
            _rows = [{"id": str(t["id"]), "label": label_cut(t["text"]), "base": 1.0,
                      "weight": round(1.0 / (1 + max(0, int(t.get("used") or 0))), 4),
                      "why": ["sprung %d time(s)" % int(t.get("used") or 0)]} for t in _bank]
            _k = pick_index([r["weight"] for r in _rows], _d["u"])
            ev["stages"].append(_stage("topic", _rows, _k, _d))
            _t = _bank[_k]
            # no "file": the station stamps turns with a document's name and
            # remembers it as a heard passage, and a board entry is neither
            turn["topic_material"] = {"text": sentence_cut(_t["text"], 400),
                                      "file": "", "source": "the topics board", "topic_id": str(_t["id"])}
            ev["selected"]["topic"] = {"id": str(_t["id"]), "text": label_cut(turn["topic_material"]["text"])}
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
    trows = [{"id": str(t["id"]), "label": label_cut(t["text"]), "base": 1.0,
              "weight": round(1.0 / (1 + max(0, int(t.get("used") or 0))), 4),
              "why": ["sprung %d time(s)" % int(t.get("used") or 0)]} for t in bank]
    tpick = pick_index([r["weight"] for r in trows], d2["u"])
    stages.append(_stage("item", trows, tpick, d2))
    chosen = bank[tpick]
    reply = sentence_cut(chosen.get("reply") or "", 400) if replies else ""
    if reply:
        slots = [i for i in slots if i + 1 < want] or slots
    d3 = stream.next("TOPIC:turn")
    srows = [{"id": "t%d" % i, "label": "turn %d" % (i + 1), "base": 1.0, "weight": 1.0, "why": []}
             for i in slots]
    spick = pick_index([r["weight"] for r in srows], d3["u"])
    stages.append(_stage("turn", srows, spick, d3))
    plan = {"id": str(chosen["id"]), "text": sentence_cut(chosen["text"], 400),
            "reply": reply, "turn_index": slots[spick]}
    ev = _event(conv, ctx, "TOPIC", stages, {"id": plan["id"], "label": label_cut(plan["text"])}, before,
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
    if _cutin_setup(conv, config, inputs, phrases, table_rows, banter, hosts):    # [outl-cutin] CUTIN1 per long turn
        phrases, table_rows = [], []
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
            # [s3-live-event] while the record on air IS a station event's
            # live set, the comment's direction is one of the event's own
            # rows, drawn on its own stream - the die above is untouched.
            _ev_id = str(inputs.get("record_event") or "")
            _erows = ([(t, c, i) for t in _tables_for(config, "TRACK_TALK")
                       if str(t.get("event") or "") == _ev_id
                       for c in t.get("categories") or [] if isinstance(c, dict) and c.get("enabled") is not False
                       for i in c.get("items") or [] if isinstance(i, dict) and i.get("enabled") is not False
                       and str(i.get("text") or "").strip() and float(i.get("weight", 1.0) or 0) > 0]
                      if _ev_id else [])
            if _erows:
                _estream = DrawStream(str(conv["seed"]) + "|round:TRACK_TALK:event")
                _ed = _estream.next("TRACK_TALK:event")
                _ecands = [{"id": "%s:%s" % (c["id"], i.get("id")), "label": str(i.get("label") or i.get("id")),
                            "base": float(i.get("weight", 1.0) or 0),
                            "weight": float(i.get("weight", 1.0) or 0) * float(c.get("weight", 1.0) or 0),
                            "why": []} for (t, c, i) in _erows]
                _ek = pick_index([r["weight"] for r in _ecands], _ed["u"])
                if _ek >= 0:
                    _et, _ec, _ei = _erows[_ek]
                    stages.append(_stage("event-row", _ecands, _ek, _ed))
                    conv["track_talk_plan"]["record"] = dict(
                        meta["record"], event=_ev_id, table=str(_et["id"]), category=str(_ec["id"]),
                        item=str(_ei.get("id")), direction=str(_ei.get("text") or "")[:400])
                    meta["event"] = _ev_id
                    sel["event"] = _ev_id
                    sel["label"] += " - about the live set (%s)" % _et["id"]
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


# --- [outl-fns] THE OUTLANDISH METER'S STRUCTURE (outlandish.py) ------------------------
# The meter never touches a word. It reads the line BEFORE a turn is decided (a
# written turn in Mode B, a line road's own words) and, at or above its dispute
# threshold, the next seat's RS/IRS rows weigh up (OUTDISPUTE1). The reading is
# recorded once, as a MEASURE decision on the measured turn - no number is drawn
# from any stream for it. Without OUTLANDISH1 in the config nothing happens.

def _outlandish_ctx(conv, config, prev, inputs, idx):
    if not prev:
        return None
    try:
        import outlandish
    except ImportError:
        return None
    if not outlandish.has_table(config, "OUTLANDISH1"):
        return None
    text = str(prev.get("text") or "")
    if not text.strip() and idx == 1:
        text = str((inputs or {}).get("line_text") or "")
    if not text.strip():
        return None
    meter = outlandish.table_of(config, "OUTLANDISH1")
    key = outlandish.text_key(text)
    book = conv.setdefault("outlandish", {})
    got = book.get(prev["turn_id"])
    if not isinstance(got, dict) or got.get("key") != key:
        res = outlandish.score(text, meter)
        th = outlandish.thresholds(meter)
        boost = (outlandish.dispute_boost(res["score"], outlandish.table_of(config, "OUTDISPUTE1"))
                 if res["score"] >= th["dispute"] else {})
        m = outlandish.measure_event(res, conv["identity"]["conversation_id"], prev["turn_id"])
        ev = _event(conv, {"turn_id": prev["turn_id"], "turn_index": prev["index"], "speaker": prev["speaker"]},
                    "MEASURE", m["stages"], m["selected"], _snapshot(conv, prev["speaker"]),
                    meta=dict(m["meta"], measure=m["measure"], boost=boost), rng=m["rng"])
        prev["decisions"].append({"family": "MEASURE", "event_id": ev["event_id"], "item": res["level"],
                                  "label": outlandish.headline(res)})
        got = {"key": key, "score": res["score"], "tags": res["tags"], "boost": boost, "event_id": ev["event_id"]}
        book[prev["turn_id"]] = got
    return got if got.get("boost") else None


def _outlandish_mult(spec, boost):
    import outlandish
    return outlandish.boost_for(spec, boost)


def _cutin_setup(conv, config, inputs, phrases, table_rows, banter, hosts):
    """[outl-fns] CUTIN1 in the config: the round's single INTERJECT roll gives
    way to a chance die on every long host turn (_cutin_after). The Rolodex the
    words come off is the same one: the desk's diatribe list, else INTERJECT1."""
    if not banter or len(hosts) < 2 or any(p["actor_id"] in ("C", "E") for p in conv["participants"]):
        return None
    if not (phrases or table_rows):
        return None
    try:
        import outlandish
    except ImportError:
        return None
    table = outlandish.table_of(config, "CUTIN1", fallback=False)
    if table is None:
        return None
    pool = ([{"id": "p%d" % i, "label": t[:60], "text": t, "base": 1.0, "weight": 1.0,
              "why": ["the desk's diatribe_interjections"]} for i, t in enumerate(phrases[:60])]
            if phrases else [dict(r) for r in table_rows])
    conv["cutin"] = {"table": table["id"], "pool": pool, "rolled": {},
                     "max": max(0, int(outlandish.dial(table, "per_round", 2, "raw"))),
                     "source": "the desk's diatribe_interjections" if phrases else "INTERJECT1"}
    return conv["cutin"]


def _cutin_after(conv, config, settings, stream, want, inputs, seats):
    """[outl-fns] THE CUT-IN NODE. The turn just planned is a host's: a chance
    die on its own stream (seed|cutin) decides whether another seat cuts in
    edgewise, at odds that rise with the turn's planned length (CUTIN1, times
    the desk's interjections control). A hit is a real turn in the round - its
    own ES and RS - its words drawn off the Rolodex, and the first speaker
    carries on over it. Every roll, hit or pass, is a CUTIN decision on the long
    turn; the decision tree draws a hit as a diamond before the cut-in."""
    import outlandish
    ci = conv["cutin"]
    if not conv["turns"]:
        return
    long_turn = conv["turns"][-1]
    if long_turn["speaker"] not in HOST_SEATS or long_turn["step"] in ("interject", "carry_on"):
        return
    rev = int(conv["identity"].get("revision") or 1)
    rolled = ci.setdefault("rolled", {})
    if rolled.get(long_turn["turn_id"]) == rev:
        return
    if sum(1 for t in conv["turns"] if t.get("cutin")) >= int(ci.get("max") or 0) or len(conv["turns"]) + 2 > want:
        return
    rolled[long_turn["turn_id"]] = rev
    table = outlandish.table_of(config, ci.get("table") or "CUTIN1")
    words = float(long_turn.get("planned_seconds") or 0) * 2.5 or float(conv["timing"].get("words_per_turn") or 40)
    odds, why = outlandish.cutin_odds(words, table)
    ctl = clamp(settings["controls"].get("interjections", DEFAULT_CONTROLS["interjections"]))
    odds = round(clamp(odds * 2 * ctl), 4)
    own = DrawStream(str(conv["seed"]) + "|cutin", int(conv.get("cutin_draws") or 0))
    before = _snapshot(conv, long_turn["speaker"])
    d1 = own.next("CUTIN:dice")
    st1, hit = _dice_stage("CUT_IN", "another seat cuts in edgewise", odds, d1,
                           "%s; x%.2f the desk's interjections control" % (why, 2 * ctl))
    stages = [st1]
    sel = {"id": "PASS", "label": "nobody cuts in on turn %d" % (long_turn["index"] + 1), "table": ci.get("table")}
    other, phrase = None, ""
    if hit:
        rows = []
        for r in outlandish.cutin_seat_rows(table):
            if r["text"] == "third":
                seat = "D" if "D" in seats and long_turn["speaker"] != "D" else None
            else:
                seat = next((s for s in seats if s in ("A", "B") and s != long_turn["speaker"]), None)
            if seat and r["weight"] > 0 and all(x["seat"] != seat for x in rows):
                rows.append({"id": r["id"], "label": r["label"], "base": r["weight"], "weight": r["weight"],
                             "why": [], "seat": seat})
        pool = [r for r in ci.get("pool") or [] if float(r.get("weight") or 0) > 0]
        if rows and pool:
            d2 = own.next("CUTIN:seat")
            k = pick_index([r["weight"] for r in rows], d2["u"])
            stages.append(_stage("seat", rows, k, d2))
            d3 = own.next("CUTIN:phrase")
            j = pick_index([r["weight"] for r in pool], d3["u"])
            stages.append(_stage("phrase", pool, j, d3))
            other, phrase = rows[k]["seat"], str(pool[j].get("text") or pool[j].get("label") or "")
            sel = {"id": "CUT_IN", "label": "%s cuts in on turn %d: %s" % (rows[k]["label"], long_turn["index"] + 1,
                                                                          phrase),
                   "table": ci.get("table"), "seat": other, "phrase": phrase}
    conv["cutin_draws"] = own.n
    ev = _event(conv, {"turn_id": long_turn["turn_id"], "turn_index": long_turn["index"],
                       "speaker": long_turn["speaker"]}, "CUTIN", stages, sel, before, rng=d1,
                meta={"odds": odds, "words": int(words), "source": ci.get("source"),
                      "stream": "its own (seed|cutin)"})
    ev["state_after"] = before
    long_turn["decisions"].append({"family": "CUTIN", "event_id": ev["event_id"], "item": sel["id"],
                                   "label": sel["label"]})
    if not other:
        return
    long_turn["long_roll"] = True
    t1 = _decide_turn(conv, config, settings, stream, {"id": "interject", "label": "Cuts in edgewise",
                                                      "draws": [{"family": "ES"}, {"family": "RS"}]},
                      other, want, inputs)
    t1["interject"] = [phrase]
    t1["cutin"] = ev["event_id"]
    ev["meta"]["cutin_turn"] = t1["turn_id"]
    t2 = _decide_turn(conv, config, settings, stream, {"id": "carry_on", "label": "Carries on over it",
                                                      "draws": [{"family": "ES"}]}, long_turn["speaker"], want, inputs)
    t2["carry_on"] = True


def _interject_after(conv, config, settings, stream, want, inputs, seats):
    """[s3-rounds] The turn just planned is the one that runs long: the other
    host gets a word in edgewise as a turn of its own, and the first carries
    straight on over it - two planned turns, alternating, inside the budget,
    so the seat order the bind aligns on is exactly what the writer is told."""
    if isinstance(conv.get("cutin"), dict):                                   # [outl-cutin-turn]
        return _cutin_after(conv, config, settings, stream, want, inputs, seats)
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
    memory_rolls(conv, config, settings, inputs)          # [s3-memory] every planner rolls the memory here
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
                cands.append({"id": rid, "label": label_cut(r["text"]), "base": r["weight"], "weight": w, "why": why, "row": r})
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
                sel = {"id": plan["id"], "label": label_cut(plan["text"]), "table": plan["table"], "turn_index": t["index"],
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
        sel = {"id": "NONE", "label": "not this time: " + label_cut(r["text"]), "row": rid, "seat": seat}
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
            sel = {"id": rid, "label": label_cut(r["text"]), "table": r["table"], "turn_index": t["index"], "seat": seat}
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
                                   "label": label_cut(fav.get("text") or "")})
            ev = events.get(fav.get("event_id"))
            if ev:
                ev["turn_id"], ev["turn_index"] = t["turn_id"], t["index"]
    for plan in conv.get("directive_plans") or []:
        t = _cast_landing(turns, plan.get("turn_index", 0), plan.get("seat"))
        if not t:
            continue
        t.setdefault("directives", []).append({k: plan.get(k) for k in ("id", "text", "seat", "event_id")})
        t["decisions"].append({"family": "DIRECTIVE", "event_id": plan.get("event_id", ""), "item": plan.get("id"),
                               "label": label_cut(plan.get("text") or "")})
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
            if table.get("event"):                            # [s3-live-event]
                meta["event"] = str(table["event"])
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
                            "event": str(table.get("event") or ""),      # [s3-live-event]
                            "id": str(item.get("id")), "label": str(item.get("label") or item.get("id")),
                            "text": whole_cut(_legs_words(item.get("text"), inputs), 400),
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
                                                                    "text", "ends", "event_id",
                                                                    "event")})   # [s3-live-event]
        t["decisions"].append({"family": "EVENT", "event_id": plan.get("event_id", ""), "item": plan.get("id"),
                               "table": plan.get("table"), "event": plan.get("event", ""),   # [s3-live-event]
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
    out = dict(_callend_emotions(conv, idx))                                  # [s3-callend] the caller's wheel
    for plan in conv.get("event_plans") or []:
        if int(plan.get("turn_index", -1)) == idx:
            for k, v in (plan.get("emotions") or {}).items():
                try:
                    out[str(k)] = out.get(str(k), 1.0) * float(v)
                except (TypeError, ValueError):
                    pass
    return out


# --- [s3-memory] what the writer is reminded of: rules, then roulette ---------------
#
# The operator's guide, 2026-09-28: memory context is given ONLY WHEN RELEVANT -
# the clock, a synopsis of the last topic, the last segment and how it went, the
# callers this hour against the quota, a synopsis of the manager's last message.
# Asked how: "Rules, then roulette." Each MEMORY category is one kind of memory;
# its rule (the numbers on the category, edited in Tables) decides whether it is
# relevant to this round right now and says why either way; the roulette then
# draws among the relevant kinds by weight - at least `least`, at most `most` a
# round, how many itself a die when those differ - and a die picks which of a
# drawn kind's items (the ways it can be put) when more than one fits. One
# MEMORY event holds all of it: every kind's verdict, every candidate and its
# weight, every die. It is drawn on the round's own stream (seed|round:MEMORY),
# so no other draw moves; the items drawn are the only memory the writer is
# given (memory_text -> the station's "memory" block). Opt-in
# (inputs.memory_rolls): a conversation stored before replays as it was.
MEMORY_KINDS = ("clock", "last_topic", "last_segment", "callers_quota", "manager_note")
MEMORY_HEAD = ("\nWHAT THE BOOTH HAS IN MIND RIGHT NOW (drawn for this round - work each one in only where it "
               "fits, in your own words; never recite it): ")
_MEMORY_HOURS = ("twelve", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven")


def _memory_num(rule, key, default):
    try:
        return max(0.0, float(rule.get(key, default)))
    except (TypeError, ValueError):
        return float(default)


def _memory_minutes(x):
    n = max(0, int(round(float(x or 0))))
    return "%d minute%s" % (n, "" if n == 1 else "s")


def _memory_hour(h):
    h = int(h or 0) % 24
    return "midnight" if h == 0 else "noon" if h == 12 else "%s o'clock" % _MEMORY_HOURS[h % 12]


def _memory_stem(word):
    w = str(word or "").lower()
    return w[:-1] if len(w) > 5 and w.endswith("s") and not w.endswith("ss") else w


def _memory_keywords(text):
    """The content words of a subject (five letters or more, not the stop
    list), a plural's s dropped - what "carries it on" is measured in."""
    return {_memory_stem(w) for w in re.findall(r"[a-z]{5,}", str(text or "").lower()) if w not in _STOP}


def _memory_words(text, fill):
    """An item's words with the station's facts filled in ({clock}, {synopsis}
    ...); a {word} the station holds nothing for is dropped, never left in."""
    out = re.sub(r"\{([a-z_]+)\}", lambda m: str(fill.get(m.group(1), "") or ""), str(text or ""))
    return " ".join(out.split()).strip(" ;,-")


def _memory_rule(cat, facts, conv, inputs):
    """(state or None, why, fill) for one kind of memory: whether it is relevant
    to this round right now by the numbers on its rule, why either way, and the
    words its items fill in. A kind the engine has no rule for (a category the
    operator added) is eligible whenever the station holds its fact - the
    category's `fact`, else its id - and, with `within_minutes`, a fresh one."""
    rule = cat.get("rule") if isinstance(cat.get("rule"), dict) else {}
    kind = str(cat.get("kind") or cat.get("id") or "")
    fact = facts.get(str(cat.get("fact") or kind))
    fact = fact if isinstance(fact, dict) else {}
    at = float(inputs.get("at") or conv.get("created") or 0)
    road = str(conv["identity"].get("road_kind") or "")
    line_road = road in system3_tables.LINE_ROADS

    def num(key, default):
        return _memory_num(rule, key, default)

    def off(switch, why, fill):
        return None, "%s - but its rule's %s switch is off" % (why, switch), fill

    roads = [str(r) for r in (cat.get("roads") or []) if str(r)]
    if roads and road not in roads:
        return None, "not on the %s road (its roads: %s)" % (road or "this", ", ".join(roads)), {}
    if inputs.get("bank") and not str(inputs.get("system2_job_id") or "") and rule.get("on_banked") is not True:
        return None, ("a banked round is written now and heard later - by then this would be stale "
                      "(its rule's on_banked switch is off)"), {}
    if kind == "clock":
        if fact.get("minute") is None:
            return None, "the station handed in no clock", {}
        minute = float(fact.get("minute") or 0) + float(fact.get("second") or 0) / 60.0
        to_top = 60.0 - minute
        seg = fact.get("segment") if isinstance(fact.get("segment"), dict) else {}
        ends = float(seg.get("ends") or 0)
        left = (ends - at) / 60.0 if ends > 0 else None
        name = " ".join(str(seg.get("label") or "").split()) or "this segment"
        fill = {"clock": " ".join(str(fact.get("clock") or "").split()),
                "to_top": _memory_minutes(math.ceil(to_top)), "past_top": _memory_minutes(minute),
                "hour": _memory_hour(fact.get("hour")), "next_hour": _memory_hour(int(fact.get("hour") or 0) + 1),
                "segment": name, "segment_left": _memory_minutes(math.ceil(left)) if left is not None else ""}
        before, after, seg_n = num("before_top", 5), num("after_top", 3), num("segment_left", 2)
        if to_top <= before:
            return "top", "%.0f min to the top of the hour (the rule: within %g)" % (to_top, before), fill
        if minute < after:
            return "past", "%.0f min past the hour (the rule: within %g)" % (minute, after), fill
        if left is not None and 0 < left <= seg_n:
            return "segment", "%s ends in %.1f min (the rule: within %g)" % (name, left, seg_n), fill
        return None, ("%.0f min past the hour - not within %g min of the top or %g after it, %s"
                      % (minute, before, after,
                         ("and %s has %.0f min left (the rule: %g)" % (name, left, seg_n)) if left is not None
                         else "and no segment end in view")), fill

    if kind == "last_topic":
        topic = " ".join(str(fact.get("topic") or fact.get("text") or "").split())
        if not topic:
            return None, "nothing has gone out yet that System 3 holds a subject for", {}
        age = max(0.0, (at - float(fact.get("at") or 0)) / 60.0)
        landing = " ".join(str(fact.get("landing") or "").split())
        who = " ".join(str(fact.get("landing_who") or "").split()) or "the last voice"
        synopsis = "%s (%s ago%s)" % (sentence_cut(topic, 200), _memory_minutes(age),
                                      (", ending on %s saying %s" % (who, json.dumps(sentence_cut(landing, 140))))
                                      if landing else "")
        fill = {"synopsis": synopsis, "topic": sentence_cut(topic, 200), "ago": _memory_minutes(age),
                "landing": json.dumps(sentence_cut(landing, 140)) if landing else "", "who": who}
        within = num("within_minutes", 30)
        if age > within:
            return None, "the last subject went out %.0f min ago (the rule: within %g)" % (age, within), fill
        subj = conv.get("subject") or {}
        mine = {_memory_stem(w) for w in subj.get("keywords") or []} | _memory_keywords(subj.get("topic"))
        theirs = {_memory_stem(w) for w in fact.get("keywords") or []} | _memory_keywords(topic)
        shared = sorted(mine & theirs)
        need = max(1, int(num("continues_overlap", 2)))
        own = bool(str(subj.get("topic") or "").strip()) and subj.get("authority") != "free"
        if not own:
            state, why = "continues", "this round brings no subject of its own, so it carries on from the last one"
        elif len(shared) >= need:
            state, why = "continues", "it shares %d word%s with the last subject (%s; the rule: %d)" % (
                len(shared), "" if len(shared) == 1 else "s", ", ".join(shared[:5]), need)
        elif line_road:
            return None, ("a single line on another subject has nothing to turn from (%d shared word%s; "
                          "the rule: %d to carry it on)" % (len(shared), "" if len(shared) == 1 else "s", need)), fill
        else:
            state, why = "contrasts", "a different subject: %d shared word%s (the rule: %d to carry it on)" % (
                len(shared), "" if len(shared) == 1 else "s", need)
        why += "; it went out %.0f min ago (the rule: within %g)" % (age, within)
        if rule.get(state) is False:
            return off(state, why, fill)
        return state, why, fill

    if kind == "last_segment":
        ended = float(fact.get("ended") or 0)
        if not ended:
            return None, "no segment has ended since the station started (the schedule has not moved on yet)", {}
        if fact.get("unseen"):
            return None, ("the segment before this one ran with no round planned in it - System 3 did not see "
                          "it, so it cannot say how it went"), {}
        name =" ".join(str(fact.get("label") or fact.get("kind") or "the last segment").split())
        now = fact.get("now") if isinstance(fact.get("now"), dict) else {}
        now_name = " ".join(str(now.get("label") or "").split()) or "this segment"
        heard, pulled, calls = int(fact.get("heard") or 0), int(fact.get("withdrawn") or 0), int(fact.get("calls") or 0)
        if heard:
            parts = ["%d line%s heard" % (heard, "" if heard == 1 else "s")]
            if pulled:
                parts.append("%d withdrawn" % pulled)
            if calls:
                parts.append("%d call%s taken" % (calls, "" if calls == 1 else "s"))
            went = ", ".join(parts)
        else:
            went = "nothing it planned was heard" + ((" (%d line%s withdrawn)" % (pulled, "" if pulled == 1 else "s"))
                                                     if pulled else "")
        since = max(0.0, (at - ended) / 60.0)
        fill = {"segment": name, "went": went, "ago": _memory_minutes(since), "now": now_name}
        if line_road:
            return None, "a single line does not open a segment", fill
        within, first = num("within_minutes", 15), num("first_minutes", 4)
        if since > within:
            return None, "%s ended %.0f min ago (the rule: within %g)" % (name, since, within), fill
        into = (at - float(now.get("started") or 0)) / 60.0 if float(now.get("started") or 0) > 0 else None
        if into is not None and into > first:
            return None, ("%.0f min into %s - past the hand-over from %s (the rule: its first %g min)"
                          % (into, now_name, name, first)), fill
        share = pulled / float(max(1, heard + pulled))
        state = "rough" if (not heard or share >= num("rough_share", 0.34)) else "smooth"
        why = "%s ended %.0f min ago and %s has just begun: %s (the rule: within %g, its first %g min)" % (
            name, since, now_name, went, within, first)
        if rule.get(state) is False:
            return off(state, why, fill)
        return state, why, fill

    if kind == "callers_quota":
        if not fact:
            return None, "the station handed in no call count", {}
        quota, count = int(float(fact.get("quota") or 0)), int(float(fact.get("count") or 0))
        # behind is read off the rolling hour (the station's own quota_behind: it can only
        # under-report a deficit); ahead off the clock hour's own calls, so the last hour's
        # tail never makes this one look ahead
        hour_n = int(float(fact.get("this_hour", count) or 0))
        fill = {"calls": "%d call%s" % (count, "" if count == 1 else "s"), "quota": str(quota), "count": str(count),
                "hour_calls": "%d call%s" % (hour_n, "" if hour_n == 1 else "s")}
        if quota <= 0:
            return None, "the calls-per-hour dial is off: there is no quota", fill
        if fact.get("paused"):
            return None, "the station is off air - nobody is behind", fill
        minute = float(fact.get("minute") or 0)
        after = num("after_minutes", 15)
        if minute < after:
            return None, "%.0f min into the hour - too early to judge the pace (the rule: from minute %g)" % (
                minute, after), fill
        expected = quota * min(1.0, minute / 60.0)
        margin = max(0.5, num("margin", 1))
        fill["expected"] = "%.0f" % expected
        why = ("%d call%s in the last hour, %d since the top of it, against %d an hour - about %.1f due by minute "
               "%.0f (the rule: %g either way)" % (count, "" if count == 1 else "s", hour_n, quota, expected, minute,
                                                    margin))
        if expected - count >= margin:
            state = "behind"
        elif hour_n - expected >= margin or hour_n >= quota:
            state = "ahead"
        else:
            return None, "on pace: " + why, fill
        if rule.get(state) is False:
            return off(state, why, fill)
        return state, why, fill

    if kind == "manager_note":
        said = " ".join(str(fact.get("text") or "").split())
        if not said:
            return None, "the manager has said nothing from upstairs yet", {}
        age = max(0.0, (at - float(fact.get("at") or 0)) / 60.0)
        fill = {"said": json.dumps(sentence_cut(said, 220)), "ago": _memory_minutes(age)}
        if road in ("manager", "memo", "upstairs"):
            return None, "this is the manager's own road - his words are its material, not a memory", fill
        within = num("within_minutes", 20)
        if age > within:
            return None, "he last spoke from upstairs %.0f min ago (the rule: within %g)" % (age, within), fill
        return "fresh", "he spoke from upstairs %.0f min ago (the rule: within %g)" % (age, within), fill

    text = " ".join(str(fact.get("text") or "").split())
    if not text:
        return None, "the station holds nothing for %s" % (kind or "this kind"), {}
    fill = dict({k: v for k, v in fact.items() if isinstance(v, (str, int, float)) and not isinstance(v, bool)},
                synopsis=text)
    if "within_minutes" in rule and float(fact.get("at") or 0) > 0:
        age = max(0.0, (at - float(fact["at"])) / 60.0)
        fill["ago"] = _memory_minutes(age)
        if age > num("within_minutes", 30):
            return None, "%.0f min old (the rule: within %g)" % (age, num("within_minutes", 30)), fill
    return "fresh", "the station holds it", fill


def _memory_count(table, key, default):
    try:
        return max(0, min(5, int(float(table.get(key, default) if table.get(key) is not None else default))))
    except (TypeError, ValueError):
        return default


def memory_rolls(conv, config, settings=None, inputs=None):
    """[s3-memory] THE ROUND'S MEMORY: rules, then roulette. Every kind in the
    enabled MEMORY tables is put to its rule (eligible or not, and why); the
    roulette draws how many (between the tables' least and most, never more
    than are eligible), which kinds (by weight, none twice) and, where more
    than one item fits a drawn kind's state, which way it is put. One MEMORY
    event records it all, on the round's own stream. The items drawn land on
    the round's first turn and are the writer's memory block (memory_text).
    A re-plan keeps what was rolled. Returns conv["memory"], or None when
    nothing was rolled (not opted in, no MEMORY table)."""
    inputs = inputs if inputs is not None else conv["inputs"]
    config = event_view(config, inputs)                          # [s3-live-event]
    if not inputs.get("memory_rolls"):
        return None
    if isinstance(conv.get("memory"), dict):
        _memory_attach(conv)
        return conv["memory"]
    tables = _tables_for(config, "MEMORY")
    if not tables:
        return None
    facts = inputs.get("memory") if isinstance(inputs.get("memory"), dict) else {}
    rows = []
    for table in tables:
        for cat in table.get("categories") or []:
            if not isinstance(cat, dict) or not cat.get("id") or cat.get("enabled") is False:
                continue
            rid = str(cat["id"]) if len(tables) == 1 else "%s:%s" % (table["id"], cat["id"])
            weight = round(float(table.get("weight", 1.0) or 0) * float(cat.get("weight", 1.0) or 0), 4)
            state, why, fill = _memory_rule(cat, facts, conv, inputs)
            fits = []
            if state:
                for it in cat.get("items") or []:
                    if not isinstance(it, dict) or not it.get("id") or it.get("enabled") is False \
                            or float(it.get("weight", 1.0) or 0) <= 0 or not str(it.get("text") or "").strip():
                        continue
                    when = it.get("when")
                    whens = [str(x) for x in when] if isinstance(when, list) else ([str(when)] if when else [])
                    if not whens or state in whens:
                        fits.append(it)
                if not fits:
                    why += " - but no item of it fits %s" % state
                elif weight <= 0:
                    why += " - but its weight is 0"
            rows.append({"id": rid, "label": str(cat.get("label") or cat["id"]), "table": table["id"],
                         "category": str(cat["id"]), "state": state, "why": why, "fill": fill, "fits": fits,
                         "weight": weight, "eligible": bool(state and fits and weight > 0)})
    least = min(_memory_count(t, "least", 1) for t in tables)
    most = max(_memory_count(t, "most", 2) for t in tables)
    live = [r for r in rows if r["eligible"]]
    lo, hi = min(least, len(live)), min(max(least, most), len(live))
    stream = DrawStream(str(conv["seed"]) + "|round:MEMORY")
    ctx0 = {"turn_id": "", "turn_index": -1}
    before = _snapshot(conv, conv["cursor"].get("initiator"))
    verdicts = [{"id": r["id"], "label": r["label"], "eligible": r["eligible"], "state": r["state"], "why": r["why"]}
                for r in rows]
    stages = [{"stage": "rules", "draw": None, "verdicts": verdicts,
               "selected": "%d of %d relevant" % (len(live), len(rows)),
               "rule": "The rules, kind by kind: " + "; ".join(
                   "%s - %s (%s)" % (r["label"], ("eligible: " + str(r["state"])) if r["eligible"] else "not eligible",
                                     r["why"]) for r in rows) + "."}]
    n, rng = lo, None
    if hi > lo:
        d = stream.next("MEMORY:count")
        crows = [{"id": str(k), "label": "%d memor%s" % (k, "y" if k == 1 else "ies"), "base": 1.0, "weight": 1.0,
                  "why": ["between the table's least (%d) and most (%d), no more than are relevant (%d)"
                          % (least, most, len(live))]} for k in range(lo, hi + 1)]
        ci = pick_index([r["weight"] for r in crows], d["u"])
        stages.append(_stage("how many", crows, ci, d))
        n, rng = lo + ci, d
    pool, picked = list(live), []
    for k in range(n):
        d = stream.next("MEMORY:pick%d" % (k + 1))
        cands = [{"id": r["id"], "label": r["label"], "base": r["weight"], "weight": r["weight"], "why": [r["why"]]}
                 for r in pool]
        excluded = ([{"id": r["id"], "label": r["label"], "why": r["why"]} for r in rows if not r["eligible"]] if k == 0
                    else [{"id": r["id"], "label": r["label"], "why": "drawn already"} for r in picked])
        i = pick_index([c["weight"] for c in cands], d["u"])
        if i < 0:
            break
        stages.append(_stage("item" if k == 0 else "pick %d" % (k + 1), cands, i, d, excluded))
        picked.append(pool.pop(i))
        if k == 0:
            rng = d
    items = []
    for r in picked:
        fits, j = r["fits"], 0
        if len(fits) > 1:
            d = stream.next("MEMORY:way:" + r["id"])
            wrows = [{"id": str(it["id"]), "label": str(it.get("label") or it["id"]),
                      "base": float(it.get("weight", 1.0) or 0), "weight": float(it.get("weight", 1.0) or 0),
                      "why": ["fits %s" % r["state"]]} for it in fits]
            j = pick_index([x["weight"] for x in wrows], d["u"])
            stages.append(_stage("the way: " + r["label"], wrows, j, d))
        it = fits[max(0, j)]
        words = _memory_words(it.get("text"), r["fill"]).rstrip(". ")
        if words:
            items.append({"kind": r["id"], "kind_label": r["label"], "table": r["table"], "category": r["category"],
                          "item": str(it["id"]), "label": str(it.get("label") or it["id"]), "state": r["state"],
                          "text": words})
    text = (MEMORY_HEAD + "; ".join(x["text"] for x in items) + ".") if items else ""
    tabs = sorted({x["table"] for x in items}) or [tables[0]["id"]]
    if items:
        sel = {"table": tabs[0] if len(tabs) == 1 else "MEMORY",
               "category": "+".join(x["category"] for x in items),
               "category_label": " + ".join(x["kind_label"] for x in items),
               "id": "+".join(x["kind"] for x in items), "label": "; ".join(x["label"] for x in items),
               "text": text.strip(), "items": [{k: x[k] for k in ("kind", "item", "state", "text")} for x in items]}
    else:
        sel = {"table": tabs[0], "id": "NONE", "items": [], "text": "",
               "label": "no memory this round" if live else "nothing relevant to remind the writer of"}
    meta = {"eligible": len(live), "kinds": len(rows), "drawn": len(items), "least": least, "most": most,
            "verdicts": verdicts,
            "why": ("the rules found %d of %d kinds of memory relevant; the roulette drew %d - the writer is "
                    "given exactly those" % (len(live), len(rows), len(items))) if live else
                   ("no kind of memory is relevant to this round right now: the writer is reminded of nothing")}
    ev = _event(conv, ctx0, "MEMORY", stages, sel, before, meta=meta, rng=rng)
    ev["state_after"] = before
    conv["memory"] = {"event_id": ev["event_id"], "items": items, "text": text, "draws": stream.n}
    _memory_attach(conv)
    return conv["memory"]


def _memory_attach(conv):
    """[s3-memory] The memory drawn rides the round's first turn - the writer
    holds it from there - so the Messenger shows it on the turn and the
    Rolodex on the round; again after a re-plan."""
    mem = conv.get("memory") if isinstance(conv.get("memory"), dict) else {}
    for t in conv["turns"]:
        t["decisions"] = [d for d in t["decisions"] if d.get("family") != "MEMORY"]
    items = mem.get("items") or []
    if not items or not conv["turns"]:
        return
    conv["turns"][0]["decisions"].append({
        "family": "MEMORY", "event_id": mem.get("event_id", ""), "item": "+".join(str(x.get("kind")) for x in items),
        "label": "; ".join(str(x.get("label") or x.get("kind")) for x in items)[:160]})


def memory_text(conv):
    """[s3-memory] The writer's memory block for this round: exactly the items
    its MEMORY roll drew, "" when it drew none."""
    return str(((conv or {}).get("memory") or {}).get("text") or "")


def _validate_memory_table(table, tid):
    """[s3-memory] A MEMORY table the desk may save: kinds of memory (categories)
    whose rule is numbers and switches, items with words (`when` = the rule's
    state it fits), and how many a round (`least` .. `most`, 0 to 5)."""
    cats = table.get("categories")
    if not isinstance(cats, list) or not cats:
        raise ValueError("a table needs at least one category")
    out = copy.deepcopy(table)
    out["id"], out["family"] = tid, "MEMORY"
    out["weight"] = max(0.0, float(table.get("weight", 1.0) or 0))
    out["enabled"] = bool(table.get("enabled", True))
    out["version"] = int(table.get("version") or 1)
    out["least"] = _memory_count(table, "least", 1)
    out["most"] = max(out["least"], _memory_count(table, "most", 2))
    seen = set()
    for cat in out["categories"]:
        if not isinstance(cat, dict) or not str(cat.get("id") or "").strip():
            raise ValueError("every category needs an id")
        cat["weight"] = max(0.0, float(cat.get("weight", 1.0) or 0))
        rule = cat.get("rule", {})
        if not isinstance(rule, dict):
            raise ValueError("memory kind %s: its rule is an object of numbers and switches" % cat["id"])
        clean = {}
        for key, val in rule.items():
            if isinstance(val, bool):
                clean[str(key)] = val
            elif isinstance(val, (int, float)) and not math.isnan(float(val)) and not math.isinf(float(val)):
                clean[str(key)] = max(0, val) if isinstance(val, int) else max(0.0, float(val))
            else:
                raise ValueError("memory kind %s: rule %s must be a number or true/false" % (cat["id"], key))
        cat["rule"] = clean
        if "roads" in cat:                   # optional: the roads this kind may be told on (none = every road)
            cat["roads"] = [str(r) for r in (cat.get("roads") or []) if str(r) in ROADS]
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
            when = item.get("when")
            if when is not None and not (isinstance(when, str) or
                                         (isinstance(when, list) and all(isinstance(x, str) for x in when))):
                raise ValueError("item %s/%s: `when` names the state of the rule it fits" % key)
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
            elif kind == "claimed":                              # [s3-live-event]
                _claims = event_claims(conv) if isinstance(conv, dict) else []
                rec.update(keep=bool(_claims),
                           why=("claimed by " + ", ".join(_claims[:4]) if _claims
                                else "no roll in this round landed on a station event's row - never sent"))
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


def voice_actor_diamond(conv, inputs, outgoing, by_id, current):
    """[voice-actor] "Call in now": the operator dispatched a caller into this
    segment's tree, and the FIRST diamond with an edge into a call node takes
    the call. Returns the reason the wheel was set (it is recorded on the
    draw), or "" when this diamond rolls as the graph says. The conversation
    is marked where the call was taken, so it is taken once."""
    ij = inputs.get("call_interjection") if isinstance(inputs, dict) else None
    if not isinstance(ij, dict) or not ij.get("id") or conv.get("call_interjection"):
        return ""
    if not any((by_id.get(edge["to"]) or {}).get("type") == "call" for edge in outgoing):
        return ""
    name = " ".join(str(ij.get("name") or "a caller").split())[:80]
    conv["call_interjection"] = {"id": str(ij.get("id") or "")[:40], "node": str(current),
                                 "caller": name, "at_turn": len(conv.get("turns") or [])}
    return "operator dispatch - call in now: %s joins at this diamond" % name


def voice_actor_call_brief(conv, inputs):
    """[voice-actor] Who the dispatched caller is, for the writer, on the call
    nodes of the conversation that took them; "" anywhere else."""
    took = conv.get("call_interjection")
    ij = inputs.get("call_interjection") if isinstance(inputs, dict) else None
    if (not isinstance(took, dict) or not isinstance(ij, dict)
            or str(ij.get("id") or "")[:40] != took.get("id")):
        return ""
    said = lambda key, most: " ".join(str(ij.get(key) or "").split())[:most].rstrip(". ")
    out = " This caller is %s, put through by the operator." % json.dumps(said("name", 80) or "the caller")
    if said("persona", 300):
        out += " Who they are: %s." % said("persona", 300)
    if said("goal", 300):
        out += " What they want: %s." % said("goal", 300)
    if said("topic", 300):
        out += " They ring about: %s." % said("topic", 300)
    return out


def plan_graph(conv, config, graph_raw, until=None, inputs=None, road="banter"):
    """Follow an editable conversation graph through System 3's own dice ledger.

    Nodes decide who gets a turn and how they answer.  The existing table
    engine still makes every CTS/ES/RS/IRS/FL decision on that turn.
    """
    graph = conversation_graph.normalize(graph_raw)
    if not graph["nodes"]:
        raise ValueError("the conversation graph has no nodes")
    inputs = inputs if inputs is not None else conv["inputs"]
    config = event_view(config, inputs)                          # [s3-live-event]
    by_id = {node["id"]: node for node in graph["nodes"]}
    stream = DrawStream(conv["seed"], conv.get("draws", 0))
    want = int(until or conv["timing"]["turn_budget"])
    # [s3-booth] "anyone from the booth can initiate": when the round hands
    # the booth in (chapter_seats - Sam's seat, a guest on the wheel), the
    # raffles draw from it; without it, the host seats as before.
    booth_pool = [str(s) for s in (inputs.get("chapter_seats") or []) if str(s)]
    seats = [p["actor_id"] for p in conv["participants"]
             if p["actor_id"] in (booth_pool or HOST_SEATS)]
    if not seats:
        seats = [p["actor_id"] for p in conv["participants"]]
    cur = conv["cursor"]
    pinned_initiator = (str(graph_raw.get("initiator") or inputs.get("initiator") or "")
                        if isinstance(graph_raw, dict) else str(inputs.get("initiator") or ""))
    if not conv["turns"]:
        if pinned_initiator in seats:
            cur["initiator"] = pinned_initiator
        if until is None and _length_decision(conv, conv["settings"], stream, inputs):
            want = int(conv["timing"]["turn_budget"])
        _topic_decision(conv, conv["settings"], stream, inputs, want)
        _round_rolls(conv, config, conv["settings"], inputs, want, banter=road == "banter")
        cur["graph_node"] = graph["start"]
        cur["graph_visits"] = {}
        cur["graph_topic"] = str(conv.get("subject", {}).get("topic") or "")
        conv["graph_structure"] = {"road": road, "start": graph["start"],
                                   "nodes": len(graph["nodes"]), "edges": len(graph["edges"])}
    current = str(cur.get("graph_node") or graph["start"])

    def record(label, rows, selected, draw, meta=None):
        before = _snapshot(conv, cur.get("initiator"))
        ev = _event(conv, {"turn_id": "", "turn_index": len(conv["turns"])}, "GRAPH",
                    [_stage(label, rows, selected, draw)],
                    {"id": rows[selected]["id"], "label": rows[selected]["label"]},
                    before, meta=meta or {}, rng=draw)
        ev["state_after"] = _snapshot(conv, cur.get("initiator"))
        return ev

    guard = 0
    while len(conv["turns"]) < want and guard < min(240, graph["max_steps"] * 4):
        guard += 1
        node = by_id.get(current)
        if not node:
            break
        visits = cur.setdefault("graph_visits", {})
        visits[current] = visits.get(current, 0) + 1
        if visits[current] > max(4, graph["max_steps"] // 4):
            break
        kind = node["type"]
        if kind == "end":
            # End is a real closing turn.  A chapter may end early by design.
            if len(conv["turns"]) >= want:
                break
        execute = kind != "call" or bool(inputs.get("graph_caller_available"))
        if execute and node["chance"] < 1:
            draw = stream.next("GRAPH:%s:chance:%d" % (current, visits[current]))
            choices = [{"id": "speak", "label": "speak", "base": node["chance"],
                        "weight": node["chance"], "why": ["node probability"]},
                       {"id": "skip", "label": "skip", "base": 1 - node["chance"],
                        "weight": 1 - node["chance"], "why": ["node probability"]}]
            execute = execute and draw["u"] < node["chance"]
            record("chance", choices, 0 if execute else 1, draw, {"node": current})
        if execute and kind != "decision":
            speaker = node["speaker"]
            if kind == "initiator":
                cur["graph_reply_speakers"] = {}
                if node.get("protocol_road"):
                    # [nodeplan] a single-voice road's own voice opens: the
                    # door's seat, no raffle - the LINE draw stays the Rolodex
                    speaker = str(inputs.get("line_seat") or node["speaker"]
                                  or (seats[0] if seats else "A"))
                    cur["initiator"] = speaker
                elif speaker in seats:
                    cur["initiator"] = speaker
                elif pinned_initiator in seats:
                    cur["initiator"] = pinned_initiator
                else:
                    candidates = [s for s in seats if s != cur.get("initiator") or visits[current] == 1]
                    if len(candidates) > 1:
                        candidates = [s for s in candidates if s != cur.get("last")] or candidates
                    if not candidates:
                        candidates = seats
                    draw = stream.next("GRAPH:%s:initiator:%d" % (current, visits[current]))
                    pick = min(int(draw["u"] * len(candidates)), len(candidates) - 1)
                    rows = [{"id": s, "label": participant(conv, s)["name"] if participant(conv, s) else s,
                             "base": 1, "weight": 1, "why": ["cast initiator election"]} for s in candidates]
                    event = record("initiator", rows, pick, draw, {"node": current})
                    cur["initiator"] = candidates[pick]
                    event["state_after"] = _snapshot(conv, cur["initiator"])
            if kind == "reply" and node.get("respond_to"):
                speaker = (cur.get("graph_reply_speakers") or {}).get(node["respond_to"])
                if not speaker:
                    execute = False
            if execute and speaker not in seats and speaker != "C":
                if kind in ("initiator", "rebuttal"):
                    speaker = cur["initiator"]
                elif kind == "call":
                    speaker = "C"
                elif kind == "reply":
                    eligible = [s for s in seats if s != cur["initiator"] and s != cur.get("last")]
                    if eligible:
                        draw = stream.next("GRAPH:%s:speaker:%d" % (current, visits[current]))
                        pick = min(int(draw["u"] * len(eligible)), len(eligible) - 1)
                        rows = [{"id": s, "label": participant(conv, s)["name"] if participant(conv, s) else s,
                                 "base": 1, "weight": 1, "why": ["cast member; not the initiator or previous speaker"]}
                                for s in eligible]
                        record("speaker", rows, pick, draw, {"node": current})
                        speaker = eligible[pick]
                    else:
                        speaker = None
                else:
                    speaker = next((s for s in seats if s != cur.get("last")), None)
            if speaker == "C" and not participant(conv, "C"):
                caller_name = str((inputs.get("names") or {}).get("C") or "Caller")[:80]
                conv["participants"].append(new_conversation({"seats": ["C"], "names": {"C": caller_name}},
                                                             config, conv["settings"])["participants"][0])
            if speaker and (speaker != cur.get("last") or kind == "initiator"):
                draws = node["draws"] or {
                    "initiator": [{"family": "CTS"}, {"family": "ES"}],
                    "reply": [{"family": "ES"}, {"family": "RS"}],
                    "rebuttal": [{"family": "ES"}, {"family": "IRS"}],
                    "topic_change": [{"family": "ES"}, {"family": "FL"}],
                    "call": [{"family": "ES"}, {"family": "RS"}],
                    "end": [{"family": "ES"}, {"family": "FL", "closes": True}],
                }.get(kind, [{"family": "ES"}])
                last_turn = len(conv["turns"]) == want - 1
                if last_turn or kind == "end":
                    draws = list(draws)
                    if not any(d.get("family") == "FL" and d.get("closes") for d in draws):
                        draws.append({"family": "FL", "tables": ["FL2"], "closes": True})
                step = {"id": current, "label": node["label"], "draws": draws,
                        "speakerbox": node["speakerbox"], "topic": node["topic"]}
                turn = _decide_turn(conv, config, conv["settings"], stream, step, speaker,
                                    want, inputs, closing=False)
                turn["graph_node"] = current
                turn["graph_type"] = kind
                turn["planned_seconds"] = node["seconds"]
                if inputs.get("candidates") and not conv.get("line_choice"):
                    # [nodeplan] the stock line is still System 3's recorded
                    # Rolodex draw when the chapter plans the exchange around it
                    _line_draw(conv, stream, inputs, road, turn)
                if kind == "initiator" and visits[current] > 1 and not node["topic"] and cur.get("graph_topic"):
                    turn["topic_override"] = cur["graph_topic"]
                if kind == "rebuttal" or (kind == "reply" and node.get("respond_to")):
                    for field, choices in (("handling", node["moods"]),
                                           ("intonation", node["intonations"])):
                        if not choices:
                            continue
                        draw = stream.next("GRAPH:%s:%s:%d" % (current, field, visits[current]))
                        pick = min(int(draw["u"] * len(choices)), len(choices) - 1)
                        rows = [{"id": str(i), "label": choice, "base": 1, "weight": 1,
                                 "why": ["node delivery table"]} for i, choice in enumerate(choices)]
                        record(field, rows, pick, draw, {"node": current})
                        turn["graph_" + field] = choices[pick]
                if kind == "reply":
                    cur.setdefault("graph_reply_speakers", {})[current] = speaker
                turn["protocol"] = (whole_cut(_legs_words(node["prompt"], inputs), 600) if node["prompt"] else {
                    "initiator": "Opens this chapter with a concrete point.",
                    "reply": "Answers the preceding point and the replies already made in this chain.",
                    "rebuttal": "Answers the replies to their opening point, including each speaker's argument.",
                    "topic_change": "Segues from this exchange into the next discussion point.",
                    "call": "A caller who heard this conversation joins with its context and gets a direct response.",
                    "end": "Closes the segment with an amiable ending.",
                }.get(kind, ""))
                prev = conv["turns"][-2] if len(conv["turns"]) > 1 else None
                if kind in ("reply", "call") and prev is not None and not node.get("respond_to"):
                    # [nodeplan] the writer is told BY NAME what this turn answers
                    turn["protocol"] += (" It answers what %s just said."
                                         % str(prev.get("name") or prev.get("speaker") or "the last voice"))
                if kind == "rebuttal":
                    repliers = list(dict.fromkeys((cur.get("graph_reply_speakers") or {}).values()))
                    named = []
                    for s in repliers:
                        p = participant(conv, s)
                        named.append(str((p or {}).get("name") or s))
                    if named:
                        # [nodeplan] "replying to each other and to the replies
                        # inside of the chain" - the repliers, by name
                        turn["protocol"] += (" The repliers were %s: answer each of them by argument, and "
                                             "the way they answered each other inside the chain."
                                             % ", ".join(named))
                    if node.get("target") == "rolled" and len(repliers) > 1:
                        # [s3-booth] the lead comes back on ONE answer: the
                        # roulette over the chain's repliers, and a spicier
                        # answer (the intensity its ES roll landed) draws the
                        # rebuttal more often
                        spice = []
                        for s in repliers:
                            answered = next((t for t in reversed(conv["turns"][:-1])
                                             if t["speaker"] == s and t.get("graph_type") == "reply"), None)
                            perf = (answered or {}).get("performance") or {}
                            spice.append(1.0 + clamp(float(perf.get("intensity") or 0)))
                        draw = stream.next("GRAPH:%s:target:%d" % (current, visits[current]))
                        pick = pick_index(spice, draw["u"])
                        rows = [{"id": s, "label": named[i], "base": 1.0, "weight": spice[i],
                                 "why": ["base 1 + the answer's rolled intensity %.2f" % (spice[i] - 1)]}
                                for i, s in enumerate(repliers)]
                        record("target", rows, pick, draw, {"node": current})
                        turn["graph_target"] = repliers[pick]
                        turn["protocol"] += (" Take on %s's answer first and come back on it directly."
                                             % named[pick])
                if kind == "reply" and node.get("respond_to"):
                    original = next((old for old in reversed(conv["turns"][:-1])
                                     if old.get("graph_node") == node["respond_to"]), None)
                    rebuttal = next((old for old in reversed(conv["turns"][:-1])
                                     if old.get("graph_type") == "rebuttal"), None)
                    if original and rebuttal:
                        # [s3-direction] never a turn number: the writer said "the point I made in turn two"
                        turn["protocol"] += (" Return to the point you made earlier and answer %s's rebuttal"
                                             " directly." % str(rebuttal.get("name") or rebuttal.get("speaker")
                                                                or "the initiator"))
                if kind == "topic_change":
                    turn["topic_change"] = True
                    if node["topic"]:
                        cur["graph_topic"] = node["topic"]
                    options = graph["topic_options"] or [sentence_cut(item.get("text") or "", 400)
                        for item in (inputs.get("topic_bank") or []) if isinstance(item, dict) and item.get("text")]
                    if options and not node["topic"]:
                        draw = stream.next("GRAPH:%s:topic:%d" % (current, visits[current]))
                        weights = ([1 / (1 + max(0, int(item.get("used") or 0)))
                                    for item in (inputs.get("topic_bank") or []) if isinstance(item, dict) and item.get("text")]
                                   if not graph["topic_options"] else [1] * len(options))
                        choice = pick_index(weights, draw["u"])
                        rows = [{"id": str(i), "label": text, "base": weights[i], "weight": weights[i],
                                 "why": ["operator topic option"]} for i, text in enumerate(options)]
                        record("topic", rows, choice, draw, {"node": current})
                        turn["topic_override"] = options[choice]
                        cur["graph_topic"] = options[choice]
                if kind == "call":
                    topic = str(cur.get("graph_topic") or conv.get("subject", {}).get("topic")
                                or "the current subject")[:200]
                    heard = [str(old.get("name") or old.get("speaker") or "")
                             for old in conv["turns"][:-1] if old.get("speaker") != "C"][-3:]
                    turn["protocol"] += (" The caller joins a live discussion of %s after hearing %s."
                                         " Their point must connect to that discussion."
                                         % (json.dumps(topic), ", ".join(heard) or "the hosts"))
                    turn["protocol"] += voice_actor_call_brief(conv, inputs)   # [voice-actor] who rang
                    if node.get("call_leg") == "open" and not conv.get("callend"):
                        # [nodeplan] a call nested at a diamond ends like a real
                        # call: the caller's wheel (RESOLVE), its own stream,
                        # every candidate and the winner recorded
                        ce = {"planned": False, "events": [],
                              "names": {p["actor_id"]: p.get("name") or p["actor_id"]
                                        for p in conv["participants"]}}
                        conv["callend"] = ce
                        tables = _callend_tables(config, "RESOLVE")
                        recent = set(str(x) for x in (inputs.get("recent_items") or []))
                        if tables:
                            spec, ev = _callend_wheel(conv, tables, "RESOLVE", {"painting": False},
                                                      (), recent, None, "outcome")
                            ce["events"].append({"event_id": ev["event_id"], "role": "resolution",
                                                 "family": "RESOLVE"})
                            if spec:
                                ce["resolve"] = {"table": spec["table"], "category": spec["category"],
                                                 "category_label": spec["category_label"], "id": spec["id"],
                                                 "label": spec["label"],
                                                 "tags": [str(x) for x in spec.get("tags") or []],
                                                 "effect": "", "offer": str(spec.get("offer") or ""),
                                                 "text": str(spec.get("text") or ""),
                                                 "respond": str(spec.get("respond") or ""),
                                                 "rebuttal": str(spec.get("rebuttal") or ""),
                                                 "emotions": {}, "event_id": ev["event_id"]}
                                ce["planned"] = True
                    if node.get("call_leg") == "close" and (conv.get("callend") or {}).get("planned"):
                        w = _callend_words(conv, "rebuttal", speaker)
                        turn["protocol"] += (" The call ends the way the wheel rolled it - %s. Their last "
                                             "word is %s." % (w["outcome"], w["rebuttal"]))
                        turn["callend"] = {"role": "resolution"}
                if last_turn and kind != "end":
                    turn["protocol"] += " Land this segment with a brief, amiable ending."
                _interject_after(conv, config, conv["settings"], stream, want, inputs, seats)
                if kind == "end":
                    break
        outgoing = [edge for edge in graph["edges"] if edge["from"] == current and edge["weight"] > 0
                    and (by_id[edge["to"]]["type"] != "call" or inputs.get("graph_caller_available"))]
        if not outgoing:
            break
        ending = next((edge for edge in outgoing if by_id[edge["to"]]["type"] == "end"), None)
        if ending and len(conv["turns"]) >= want - 1:
            chosen = ending
        elif len(outgoing) == 1:
            chosen = outgoing[0]
        else:
            # The segment clock keeps a chapter open until there is room for
            # the closing turn. An early wrap would waste the allocated slot.
            if ending:
                outgoing = [edge for edge in outgoing if edge is not ending]
            draw = stream.next("GRAPH:%s:branch:%d" % (current, visits[current]))
            weights = [edge["weight"] for edge in outgoing]
            # [voice-actor] "call in now": a caller the operator dispatched into
            # this segment takes the first diamond with a way into a call. Still
            # ONE recorded draw - every edge on the wheel, its flow weight the base,
            # the dispatch the effective weight, and the reason on the draw.
            _va_why = voice_actor_diamond(conv, inputs, outgoing, by_id, current)
            if _va_why:
                weights = [1.0 if by_id[edge["to"]]["type"] == "call" else 0.0 for edge in outgoing]
            pick = pick_index(weights, draw["u"])
            rows = [{"id": edge["to"], "label": edge["label"] or by_id[edge["to"]]["label"],
                     "base": edge["weight"], "weight": weights[i],
                     "why": ["outgoing flow weight"] + ([_va_why] if _va_why else [])}
                    for i, edge in enumerate(outgoing)]
            record("branch", rows, pick, draw, {"node": current, **({"dispatch": conv["call_interjection"]["id"]}
                                                                   if _va_why else {})})
            chosen = outgoing[pick]
        current = chosen["to"]
        cur["graph_node"] = current
    conv["draws"] = stream.n
    # Replanning may call this function repeatedly. Always scale the node's
    # original estimate so repeated calls cannot compound an earlier scale.
    raw_seconds = sum(float(by_id.get(t.get("graph_node"), {}).get("seconds") or 0)
                      for t in conv["turns"] if t.get("graph_node"))
    target_seconds = float(conv["timing"].get("target_duration") or 0)
    # [nodeplan] the station's own measured pace (mean_turn_seconds, handed in
    # as timing.turn_seconds) calibrates the absolute per-turn estimate; the
    # node seconds keep the designed shape. Nothing here draws a number.
    graph_turns = [t for t in conv["turns"] if t.get("graph_node")]
    pace = float(conv["timing"].get("turn_seconds") or 0)
    unit = (pace * len(graph_turns) / raw_seconds) if pace > 0 and raw_seconds else 1.0
    fitted = raw_seconds * unit
    scale = min(1.5, max(.6, target_seconds / fitted)) if fitted and target_seconds else 1.0
    for turn in conv["turns"]:
        if turn.get("graph_node"):
            turn["planned_seconds"] = round(float(by_id.get(turn["graph_node"], {}).get("seconds") or 0)
                                            * unit * scale, 1)
    conv["graph_profile"] = {"estimated_seconds": round(sum(float(t.get("planned_seconds") or 0)
                                                             for t in conv["turns"]), 1),
                             "raw_seconds": round(raw_seconds, 1), "budget_seconds": target_seconds,
                             "turns": len(conv["turns"]),
                             # [nodeplan] the recorded fit: what the clock asked,
                             # what the chapters cost, how the walk padded/closed
                             "pace_seconds_per_turn": round(pace, 2),
                             "chapters": sum(1 for t in graph_turns if t.get("graph_type") == "initiator"),
                             "replies": sum(1 for t in graph_turns if t.get("graph_type") == "reply"),
                             "closed": bool(graph_turns and graph_turns[-1].get("graph_type") == "end"),
                             "fit": (round(sum(float(t.get("planned_seconds") or 0) for t in graph_turns)
                                           / target_seconds, 3) if target_seconds else None)}
    _events_attach(conv)
    if not (inputs.get("candidates") or []):
        # [nodeplan] a drawn stock line is fixed words (plan_line's own rule)
        _cast_rolls(conv, config, conv["settings"], inputs)
    if isinstance(conv.get("callend"), dict) and conv["callend"].get("events"):
        _callend_attach(conv, config)              # [nodeplan] the wheel lands on its turn
    return conv


def plan_more(conv, config, until=None, inputs=None):
    """Mode A: plan turns from the cursor up to `until` (the turn budget).

    The PDF's cycle, looped for the segment: Initial -> Response A ->
    Response B -> Initiator's Response -> Response A -> Response B ->
    Frame -> hand the initiator role on. The last turn draws a closing
    move. Resumable: Mode B truncates and calls this again."""
    inputs = inputs if inputs is not None else conv["inputs"]
    config = event_view(config, inputs)                          # [s3-live-event]
    if (config.get("structure") or {}).get("graph", {}).get("enabled") and (config.get("structure") or {}).get("graph", {}).get("nodes"):
        return plan_graph(conv, config, config["structure"]["graph"], until=until,
                          inputs=inputs, road="banter")
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
    config = event_view(config, inputs)                          # [s3-live-event]
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
            _d = direction_block(t, conv) or _es_line(t)                      # [s3-direction] protocol sheets
            if _d:                                                            # [s3-es-dir]
                add += ". " + _d.rstrip(".")
            add += ".]"
        topic = t.get("bank_topic") or {}                                 # [rng-topics]
        if topic.get("text"):
            add += (" [It puts them in mind of something off the operator's topics board, and "
                    "they bring it up in their own words: %s.]" % json.dumps(sentence_cut(topic["text"], 400)))
        return match.group(0) + add
    return re.sub(r"(?m)^\s*(\d+)\s+[ABCDE]\s+[-–—].*$", row, sheet)


# --- [s3-callend] HOW A CALL ENDS: RESOLUTION -> RESPONSE CHAIN -> REBUTTAL -> WRAP CALL --------
#
# The operator, 2026-09-28: "for phone calls. At the end of the node tree. I want to put a
# resolution node with an RNG for setting up how a phone call is wrapped up so we can have
# a roulette and table for how phone calls end and customers roll a wheel for how their call
# is ended ... these should have a response chain that follows + a rebuttal from the caller
# before the call ends by somone one the station ending the call in response to the customer
# "wrap call" roulette node".
#
# The call's end is the caller structure's `end` legs (system3_tables.CALLEND_LEGS):
#   resolution  a station seat (rolled) sets up the outcome the caller's wheel landed on
#               (RESOLVE1: the offer, the raffle, the price) - the RESOLVE node
#   reaction    the caller plays it out (buys it, turns it down, sets it on fire ...)
#   response    the response chain: one or two station turns (how many, and who, rolled)
#   rebuttal    the caller's last word, second to last (it replaces "lands")
#   wrap        WRAP CALL: who on the station ends the call and how (WRAP1), the last turn
# Every roll draws on its OWN stream (seed|callend:<what>), so no other family's dice move,
# and is recorded as an event with every candidate, its weight and why, and why each one
# that could not be drawn was excluded. A structure without the legs, or a config with the
# tables switched off, plans the call it always planned (the rebuttal leg lands the story,
# the wrap leg signs off with the words the station's checker listens for) - same dice.
FAMILIES = FAMILIES + system3_tables.CALLEND_FAMILIES                        # [s3-callend] RESOLVE, WRAP
FAMILIES = FAMILIES + system3_tables.CALLARC_FAMILIES                        # [s3-callarc] CALLARC, CALLSHIFT
CALLEND_STATION = ("A", "B", "D", "S")     # the booth: host, co-host, third seat, Sam (where a call has his seat)
CALLEND_WITHIN = 1200.0                    # a painting on offer this recently is "the last segment"
CALLEND_SIGN_OFF = ("a spoken sign-off - it must contain one of these words out loud: thanks, thank you, "
                    "goodbye, goodnight, take care, appreciate")
CALLEND_LANDS = ("the last word of their own story - what changed, what they decided, or why they are ready "
                 "to leave it there")
CALLEND_REBUTTAL = ("a rebuttal to what the station just said about it - pushes back, doubles down or has a "
                    "final dig, in their own words")
CALLEND_RESPOND = "answers what {first} just did, and what it means"
CALLEND_TAIL = ("Every one of those is checked after you write it, and a call that misses one is thrown away "
                "unheard - so the two questions that repeat the caller's own words, the caller's last word "
                "second to last, and the call wrapped on the last turn exactly as the running order rolled it "
                "(a polite goodbye only where that is what was rolled) are not style notes. They are the call.")
CALLEND_NEEDS = {"painting": "the last segment did not sell a painting (nothing on offer in the window)",
                 "dead_line": "the call ran its course - nothing ended it early",
                 # [s3-callarc] the station's own business, read when the call was planned
                 "memo": "the manager has no memo on the book",
                 "news": "no headline is in hand",
                 "unsold": "the unsold pile is empty",
                 "gallery": "no painting is on the wall's unsold pile",
                 "passage": "the call has no speakerbox passage"}
CALLEND_UNLESS = {"painting": "the last segment was selling a painting - the painting wheel stands",
                  "dead_line": "the line went dead - the dead-line wheel stands"}
_CALLEND_AT = {"turn_id": "", "turn_index": -1}


def _callend_role(leg):
    """A leg's part in the call's end (its `end`), or ""."""
    role = str((leg or {}).get("end") or "")
    return role if role in system3_tables.CALLEND_ROLES else ""


def _callend_tables(config, family):
    """The switched-on tables of a call-end family that roll on a call."""
    return [t for t in _tables_for(config, family)
            if not t.get("roads") or "caller" in [str(r) for r in t.get("roads") or []]]


def _callend_why_not(row, avail, prev_keys):
    """Why a call-end category or item cannot come up on this call, or ""."""
    if row.get("enabled") is False:
        return "switched off"
    for need in row.get("requires") or []:
        if not avail.get(need):
            return CALLEND_NEEDS.get(need, "needs %s" % need)
    for bar in row.get("unless") or []:
        if avail.get(bar):
            return CALLEND_UNLESS.get(bar, "not while %s" % bar)
    only = [str(x) for x in (row.get("only_after") or [])]
    if only and not set(only) & set(prev_keys or ()):
        return "only after %s" % " or ".join(only)
    return ""


def _callend_spec(table, cat, item):
    """An item with what its category says and it does not (a default offer, `within`)."""
    spec = {k: copy.deepcopy(v) for k, v in cat.items()
            if k not in ("items", "id", "label", "weight", "enabled", "requires", "unless", "only_after", "emoji")}
    spec.update(copy.deepcopy(item))
    spec["table"], spec["category"] = table["id"], cat["id"]
    spec["category_label"] = cat.get("label") or cat["id"]
    spec["family"] = table["family"]
    if table.get("event"):                                   # [s3-live-event]
        spec["event"] = str(table["event"])
    spec["id"] = str(item.get("id"))
    spec["label"] = str(item.get("label") or item.get("id"))
    spec["needs"] = sorted({str(x) for x in list(cat.get("requires") or []) + list(item.get("requires") or [])})
    return spec


def _callend_wheel(conv, tables, family, avail, prev_keys=(), recent=(), pin=None, key="outcome"):
    """[s3-callend] One weighted draw over a call-end table: table -> category -> item, on
    the family's own stream. `pin` is the leg's draw as the Segments editor left it: a
    `fixed` item (the roulette off - recorded as a pin, no number) or a static `category`
    (the item inside still rolls). Returns (spec, event); spec None when nothing could come
    up - the event says why, category by category."""
    before = _snapshot(conv, (conv.get("cursor") or {}).get("initiator"))
    pin = pin if isinstance(pin, dict) else {}
    fixed = str(pin.get("fixed") or "")
    if fixed:
        for table in tables:
            for cat in table.get("categories") or []:
                for k, item in enumerate(cat.get("items") or [] if isinstance(cat, dict) else []):
                    if not isinstance(item, dict) or fixed not in (str(item.get("id")), "%s:%s" % (table["id"], item.get("id"))):
                        continue
                    spec = _callend_spec(table, cat, item)
                    row = {"id": spec["id"], "label": spec["label"], "base": 1.0, "weight": 1.0, "p": 1.0,
                           "why": ["pinned by the operator in the segment editor - the roulette is off for this draw"]}
                    stages = [{"stage": "fixed", "candidates": [row], "excluded": [], "total": 1.0, "draw": None,
                               "selected": spec["id"], "selected_index": 1, "of": 1}]
                    sel = {"table": table["id"], "category": cat["id"], "category_label": spec["category_label"],
                           "id": spec["id"], "label": spec["label"], "text": str(spec.get("text") or ""),
                           "index": k + 1, "of": len(cat.get("items") or []), "authority": "fixed", "kind": key}
                    ev = _event(conv, _CALLEND_AT, family, stages, sel, before,
                                meta={"authority": "fixed", "kind": key,
                                      "why": "pinned to %s in the segment editor: not a draw" % fixed})
                    ev["state_after"] = before
                    return spec, ev
    only_cat = str(pin.get("category") or "")
    stream = DrawStream(str(conv["seed"]) + "|callend:" + family)
    recent = set(recent or ())
    pool = []
    for table in tables:
        cats = []
        for cat in table.get("categories") or []:
            if not isinstance(cat, dict) or not str(cat.get("id") or "").strip():
                continue
            cwhy = _callend_why_not(cat, avail, prev_keys)
            if not cwhy and only_cat and cat["id"] != only_cat:
                cwhy = "the node is pinned to category %s" % only_cat
            items, excl = [], []
            for item in cat.get("items") or []:
                if not isinstance(item, dict) or not str(item.get("id") or "").strip():
                    continue
                spec = _callend_spec(table, cat, item)
                why = cwhy or _callend_why_not(item, avail, prev_keys)
                try:
                    base = max(0.0, float(item.get("weight", 1.0) or 0))
                except (TypeError, ValueError):
                    base = 0.0
                f, reasons = 1.0, []
                for k2, mult in (spec.get("after") if isinstance(spec.get("after"), dict) else {}).items():
                    if k2 in prev_keys:
                        try:
                            m = max(0.0, float(mult))
                        except (TypeError, ValueError):
                            continue
                        reasons.append("after %s x%.2f" % (k2, m))
                        f *= m
                if "%s:%s" % (family, spec["id"]) in recent:
                    reasons.append("came up in a recent call x0.25")
                    f *= 0.25
                if why or base * f <= 0:
                    excl.append({"id": spec["id"], "label": spec["label"], "why": why or "weight 0"})
                    continue
                items.append({"id": spec["id"], "label": spec["label"], "base": base, "weight": base * f,
                              "why": reasons, "spec": spec})
            mean = (sum(i["weight"] for i in items) / len(items)) if items else 0.0
            try:
                cbase = max(0.0, float(cat.get("weight", 1.0) or 0))
            except (TypeError, ValueError):
                cbase = 0.0
            cats.append({"id": str(cat["id"]), "label": str(cat.get("label") or cat["id"]), "base": cbase,
                         "weight": cbase * mean,
                         "why": ["mean eligible item weight %.3f" % mean] if items else [cwhy or "no eligible item"],
                         "items": items, "excluded": excl})
        live = [c for c in cats if c["weight"] > 0]
        try:
            tbase = max(0.0, float(table.get("weight", 1.0) or 0))
        except (TypeError, ValueError):
            tbase = 0.0
        pool.append({"id": table["id"], "label": str(table.get("label") or table["id"]), "base": tbase,
                     "weight": tbase if live else 0.0, "why": [] if live else ["no eligible outcome"], "cats": cats})
    live_tables = [t for t in pool if t["weight"] > 0]
    if not live_tables:
        why = "; ".join("%s - %s" % (c["label"], (c["why"] or ["no eligible item"])[0])
                        for t in pool for c in t["cats"])[:500]
        ev = _event(conv, _CALLEND_AT, family, [], {"id": "NONE", "label": "nothing on the wheel could come up",
                                                    "kind": key}, before,
                    meta={"empty": "no eligible outcome in any %s table" % family, "kind": key, "why": why})
        ev["state_after"] = before
        return None, ev
    stages = []
    if len(live_tables) > 1:
        d0 = stream.next("%s:table" % family)
        i = pick_index([t["weight"] for t in live_tables], d0["u"])
        stages.append(_stage("table", live_tables, i, d0))
    else:
        i = 0
        stages.append(_stage("table", live_tables, 0, None))
    table = live_tables[i]
    cats = [c for c in table["cats"] if c["weight"] > 0]
    d1 = stream.next("%s:category" % family)
    j = pick_index([c["weight"] for c in cats], d1["u"])
    stages.append(_stage("category", cats, j, d1, [{"id": c["id"], "label": c["label"], "why": (c["why"] or ["-"])[0]}
                                                   for c in table["cats"] if c["weight"] <= 0]))
    cat = cats[j]
    d2 = stream.next("%s:item" % family)
    k = pick_index([x["weight"] for x in cat["items"]], d2["u"])
    stages.append(_stage("item", cat["items"], k, d2, cat["excluded"]))
    spec = cat["items"][k]["spec"]
    sel = {"table": table["id"], "category": cat["id"], "category_label": cat["label"], "id": spec["id"],
           "label": spec["label"], "text": str(spec.get("text") or ""), "index": k + 1, "of": len(cat["items"]),
           "kind": key}
    ev = _event(conv, _CALLEND_AT, family, stages, sel, before,
                meta={"kind": key, "why": ("%s: the wheel over what can come up on this call - %d categor%s in "
                                           "play, %d outcome(s) on the wheel"
                                           % (key, len(cats), "y" if len(cats) == 1 else "ies", len(cat["items"])))},
                rng=d2)
    ev["state_after"] = before
    return spec, ev


def _callend_seat(conv, what, weights, present, exclude, names, family, label):
    """Who on the station takes a call-end turn: a weighted draw over the booth seats on
    this call (its own stream, seed|callend:<family>:<what>). A seat not on the call, the
    one who spoke the turn before, or a seat at weight 0 is excluded, and says so."""
    before = _snapshot(conv, (conv.get("cursor") or {}).get("initiator"))
    weights = weights if isinstance(weights, dict) else {}
    rows, excl = [], []
    for seat in CALLEND_STATION:
        name = str(names.get(seat) or seat)
        lab = "%s (seat %s)" % (name, seat)
        try:
            w = max(0.0, float(weights.get(seat, 1.0 if seat in ("A", "B") else 0.0) or 0))
        except (TypeError, ValueError):
            w = 0.0
        if seat not in present:
            excl.append({"id": seat, "label": lab,
                         "why": ("Sam has no seat on this call - the SFX guy speaks through his own node"
                                 if seat == "S" else "not in the booth on this call")})
        elif seat in exclude:
            excl.append({"id": seat, "label": lab, "why": "spoke the turn before - nobody speaks twice in a row"})
        elif w <= 0:
            excl.append({"id": seat, "label": lab, "why": "weight 0 on the desk"})
        else:
            rows.append({"id": seat, "label": lab, "base": w, "weight": w, "why": []})
    if not rows:
        seat = next((s for s in CALLEND_STATION if s in present and s not in exclude),
                    next((s for s in CALLEND_STATION if s in present), "A"))
        ev = _event(conv, _CALLEND_AT, family,
                    [{"stage": "who", "candidates": [], "excluded": excl, "total": 0.0, "draw": None,
                      "selected": seat, "selected_index": 0, "of": 0,
                      "rule": "no seat on the wheel could be drawn - %s, the first one free, takes it"
                              % str(names.get(seat) or seat)}],
                    {"id": seat, "label": label % str(names.get(seat) or seat), "kind": what}, before,
                    meta={"kind": what, "why": "no seat on the wheel could be drawn; the first one free takes it"})
        ev["state_after"] = before
        return seat, ev
    d = DrawStream(str(conv["seed"]) + "|callend:%s:%s" % (family, what)).next("%s:%s" % (family, what))
    i = pick_index([r["weight"] for r in rows], d["u"])
    seat = rows[i]["id"]
    ev = _event(conv, _CALLEND_AT, family, [_stage("who", rows, i, d, excl)],
                {"id": seat, "label": label % str(names.get(seat) or seat), "kind": what}, before,
                meta={"kind": what, "why": "who on the station takes this turn: the desk's weights by seat, over "
                                           "the seats on this call"}, rng=d)
    ev["state_after"] = before
    return seat, ev


def _callend_count(conv, weights, label="the response chain"):
    """How many station turns the response chain runs (its own stream)."""
    before = _snapshot(conv, (conv.get("cursor") or {}).get("initiator"))
    rows = []
    for k, w in sorted((weights if isinstance(weights, dict) else {}).items(), key=lambda kv: str(kv[0])):
        try:
            n, w = int(k), max(0.0, float(w or 0))
        except (TypeError, ValueError):
            continue
        if 1 <= n <= 3 and w > 0:
            rows.append({"id": str(n), "label": "%d station turn%s" % (n, "" if n == 1 else "s"), "base": w,
                         "weight": w, "why": []})
    if not rows:
        rows = [{"id": "1", "label": "1 station turn", "base": 1.0, "weight": 1.0, "why": ["no weights on the desk"]}]
    d = DrawStream(str(conv["seed"]) + "|callend:RESOLVE:responses").next("RESOLVE:responses")
    i = pick_index([r["weight"] for r in rows], d["u"])
    ev = _event(conv, _CALLEND_AT, "RESOLVE", [_stage("count", rows, i, d)],
                {"id": rows[i]["id"], "label": "%s: %s" % (label, rows[i]["label"]), "kind": "responses"}, before,
                meta={"kind": "responses", "why": "how many station turns answer the outcome before the caller's "
                                                  "rebuttal (the RESOLVE table's `responses`)"}, rng=d)
    ev["state_after"] = before
    return int(rows[i]["id"]), ev


def _callend_number(conv, raffle):
    """[RNG] caller: the raffle's caller number, one die over low..high (its own stream)."""
    before = _snapshot(conv, (conv.get("cursor") or {}).get("initiator"))
    raffle = raffle if isinstance(raffle, dict) else {}
    try:
        low = max(1, int(raffle.get("low") or 2))
        high = max(low, int(raffle.get("high") or 99))
    except (TypeError, ValueError):
        low, high = 2, 99
    d = DrawStream(str(conv["seed"]) + "|callend:RESOLVE:number").next("RESOLVE:caller_number")
    n = low + min(high - low, int(d["u"] * (high - low + 1)))
    ev = _event(conv, _CALLEND_AT, "RESOLVE",
                [{"stage": "number", "draw": d, "selected": n,
                  "rule": "caller number = %d + floor(u %.4f x %d) = %d" % (low, d["u"], high - low + 1, n)}],
                {"id": str(n), "label": "caller number %d" % n, "kind": "raffle"}, before,
                meta={"kind": "raffle", "low": low, "high": high,
                      "why": "the raffle's number: the caller who wins it is caller number N, one die over %d to %d"
                             % (low, high)}, rng=d)
    ev["state_after"] = before
    return n, ev


def _callend_prize_pool(config, prize):
    """The station's own prize list: the desk's POOLS1 category (e.g. call.prizes - the list
    the station's prize roll draws from), or the list that roll starts from until tabled."""
    prize = prize if isinstance(prize, dict) else {}
    key = str(prize.get("pool") or "call.prizes")
    for t in config.get("tables") or []:
        if not isinstance(t, dict) or t.get("family") != "POOL" or t.get("enabled") is False:
            continue
        for c in t.get("categories") or []:
            if isinstance(c, dict) and c.get("id") == key:
                rows = []
                for i, it in enumerate(c.get("items") or []):
                    if not isinstance(it, dict) or it.get("enabled") is False or not str(it.get("text") or "").strip():
                        continue
                    try:
                        w = max(0.0, float(it.get("weight", 1.0) or 0))
                    except (TypeError, ValueError):
                        w = 0.0
                    if w > 0:
                        rows.append({"id": str(it.get("id") or "o%d" % i), "label": " ".join(str(it["text"]).split()),
                                     "base": w, "weight": w, "why": []})
                if rows:
                    return rows, "%s %s (the desk's list)" % (t.get("id"), key)
    rows = [{"id": "o%d" % i, "label": " ".join(str(x).split()), "base": 1.0, "weight": 1.0, "why": []}
            for i, x in enumerate(prize.get("defaults") or system3_tables.CALL_PRIZES) if str(x or "").strip()]
    return rows, "the station's own prize list (%s is not on the desk yet)" % key


def _callend_prize(conv, config, prize):
    """Which of the station's prizes (its own stream)."""
    before = _snapshot(conv, (conv.get("cursor") or {}).get("initiator"))
    rows, source = _callend_prize_pool(config, prize)
    if not rows:
        return "", None
    d = DrawStream(str(conv["seed"]) + "|callend:RESOLVE:prize").next("RESOLVE:prize")
    i = pick_index([r["weight"] for r in rows], d["u"])
    ev = _event(conv, _CALLEND_AT, "RESOLVE", [_stage("prize", rows, i, d)],
                {"id": rows[i]["id"], "label": "wins %s" % rows[i]["label"], "kind": "prize"}, before,
                meta={"kind": "prize", "why": "which prize: %s - no prize outside it" % source}, rng=d)
    ev["state_after"] = before
    return rows[i]["label"], ev


def _callend_title(name):
    """A gallery file's name as something a person can say ("harbour at dawn")."""
    stem = re.sub(r"\.(png|jpe?g|webp|gif|mp4|webm)$", "", str(name or ""), flags=re.I)
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = " ".join(re.sub(r"\b\d{3,}\b", "", stem).split())
    return stem[:80]


def _callend_painting_words(painting):
    """{painting}, {price} and {terms} for the writer, from what the station put on offer."""
    p = painting if isinstance(painting, dict) else {}
    title = str(p.get("title") or "").strip()
    if not title or re.search(r"\.(png|jpe?g|webp|gif)$", title, re.I) or "_" in title:
        title = _callend_title(title or p.get("image"))
    if re.search(r"\b(turbo|comfyui|comfy|flux|sdxl|ernie|image)\b", title, re.I):
        title = ""                     # a generator's name is not a title
    desc = " ".join(str(p.get("desc") or "").split())
    words = ('"%s"' % title) if title else "the painting"
    if desc:
        words += " (%s)" % sentence_cut(desc, 160).rstrip(".")
    try:
        price = int(float(p.get("price") or 0))
    except (TypeError, ValueError):
        price = 0
    return {"painting": words, "price": ("%d dollars" % price) if price > 0 else "the price it was going for",
            "terms": " ".join(str(p.get("terms") or "").split())[:120]}


def _call_mid_seat(leg, k, fill_n, last_mid):
    """The seat of the k-th middle turn: alternating back from the closing, so the last
    middle turn is `last_mid` (a host before a caller who lands it; the caller before a
    station seat that opens the call's end)."""
    seat = leg.get("seat")
    if seat == "alternate":
        seat = last_mid if (fill_n - 1 - k) % 2 == 0 else ("C" if last_mid == "A" else "A")
    return seat


def _callend_close(conv, config, inputs, opening, middle, closing, want):
    """[s3-callend] The call's closing legs, rolled before its turns: the caller's wheel
    (RESOLVE: the outcome, its caller number or prize), the response chain's length, who
    sets the outcome up and who answers it. Returns ([(leg, seat)], last_mid) - the closing
    in the structure's order and the seat the middle must end on. A closing with no `end`
    legs is returned as it was, and nothing is rolled."""
    call = inputs.get("call") or {}
    roles = [(leg, _callend_role(leg)) for leg in closing]
    ce = {"planned": False, "events": []}
    conv["callend"] = ce
    if not any(r for _leg, r in roles):
        return [(leg, leg.get("seat")) for leg in closing], "A"
    names = {p["actor_id"]: p.get("name") or p["actor_id"] for p in conv["participants"]}
    seats_in = [p["actor_id"] for p in conv["participants"]]
    present = [s for s in CALLEND_STATION if s in seats_in or (s == "B" and call.get("other"))]
    if "B" in present and "B" not in names and call.get("other"):
        names["B"] = str(call.get("other"))
    ce.update(present=present, names={s: names.get(s, s) for s in present})
    painting = call.get("painting") if isinstance(call.get("painting"), dict) and call["painting"].get("image") else None
    avail = {"painting": bool(painting)}
    avail.update(_callarc_avail(call))                                          # [s3-callarc]
    recent = set(str(x) for x in (inputs.get("recent_items") or []))
    spec, table = None, None
    res_leg = next((leg for leg, r in roles if r == "resolution"), None)
    if res_leg is not None:
        tables = _callend_tables(config, "RESOLVE")
        if tables:
            pin = next((d for d in res_leg.get("draws") or [] if isinstance(d, dict) and d.get("family") == "RESOLVE"),
                       None)
            spec, ev = _callend_wheel(conv, tables, "RESOLVE", avail, (), recent, pin, "outcome")
            ce["events"].append({"event_id": ev["event_id"], "role": "resolution", "family": "RESOLVE"})
            table = next((t for t in tables if spec and t["id"] == spec["table"]), None)
        else:
            ce["why"] = "no RESOLVE table is switched on for calls - the caller lands it as before"
    n_resp = 0
    if spec:
        res = {"table": spec["table"], "category": spec["category"], "category_label": spec["category_label"],
               "id": spec["id"], "label": spec["label"], "tags": [str(x) for x in spec.get("tags") or []],
               "effect": str(spec.get("effect") or "") if str(spec.get("effect") or "") in (
                   "sold", "awarded", "burnt", "unsold", "claimed", "destroyed") else "",   # [paint-roulette]
               "offer": str(spec.get("offer") or ""), "text": str(spec.get("text") or ""),
               "respond": str(spec.get("respond") or ""), "rebuttal": str(spec.get("rebuttal") or ""),
               "emotions": dict(spec.get("emotions") or {}) if isinstance(spec.get("emotions"), dict) else {},
               "event_id": ce["events"][-1]["event_id"]}
        if painting and "painting" in (spec.get("needs") or []):
            res["painting"] = {k: painting.get(k) for k in ("image", "title", "desc", "price", "terms", "kind",
                                                            "at", "age", "why") if painting.get(k) not in (None, "")}
        if isinstance(spec.get("raffle"), dict):
            res["number"], ev = _callend_number(conv, spec["raffle"])
            ce["events"].append({"event_id": ev["event_id"], "role": "resolution", "family": "RESOLVE"})
        if isinstance(spec.get("prize"), dict):
            res["prize"], ev = _callend_prize(conv, config, spec["prize"])
            if ev is not None:
                ce["events"].append({"event_id": ev["event_id"], "role": "resolution", "family": "RESOLVE"})
        if spec.get("speakerbox"):
            res["speakerbox"] = str(spec.get("speakerbox"))
        # [s3-callarc] the manager cuts in on his own seat; a painting off the unsold pile
        if spec.get("manager"):
            res["manager_act"] = str(spec.get("manager") or "")
            res["seat_in"] = str(spec.get("seat_in") or "E")
        unsold = call.get("unsold") if isinstance(call.get("unsold"), dict) else {}
        if "unsold" in (spec.get("needs") or []) and unsold.get("name"):
            res["painting"] = {"image": str(unsold.get("name")), "title": str(unsold.get("title") or unsold.get("name")),
                               "price": unsold.get("price"), "desc": str(unsold.get("desc") or "")[:200],
                               "kind": "unsold"}
        ce["resolve"] = res
        if any(r == "response" for _leg, r in roles):
            n_resp, ev = _callend_count(conv, spec.get("responses") if isinstance(spec.get("responses"), dict)
                                        else (table or {}).get("responses") or {"1": 1.0})
            ce["events"].append({"event_id": ev["event_id"], "role": "resolution", "family": "RESOLVE"})
    # the closing in the structure's order: no outcome, no resolution, reaction or chain
    plan = []
    for leg, role in roles:
        if role in ("resolution", "reaction", "response") and not spec:
            continue
        plan += [(leg, role)] * (n_resp if role == "response" else 1)
    if not plan:
        return [], "A"
    first = plan[0]
    opens_station = (first[1] in ("resolution", "response", "wrap")
                     or (not first[1] and str(first[0].get("seat") or "A") not in ("C", "E")))
    last_mid = "C" if opens_station else "A"
    fill_n = max(0, want - len(opening) - len(plan)) if middle else 0
    prev = (_call_mid_seat(middle[(fill_n - 1) % len(middle)], fill_n - 1, fill_n, last_mid) if fill_n
            else (str(opening[-1].get("seat") or "") if opening else ""))
    weights = (spec or {}).get("responders") if isinstance((spec or {}).get("responders"), dict) \
        else (table or {}).get("responders") or {}
    out = []
    n_seen = 0
    for leg, role in plan:
        if role == "resolution":
            seat, ev = _callend_seat(conv, "setup", weights, present, {prev}, names, "RESOLVE",
                                     "%s sets up the outcome")
            ce["setup"] = {"seat": seat, "event_id": ev["event_id"]}
            ce["events"].append({"event_id": ev["event_id"], "role": "resolution", "family": "RESOLVE"})
        elif role == "response":
            n_seen += 1
            seat, ev = _callend_seat(conv, "responder%d" % n_seen, weights, present, {prev}, names, "RESOLVE",
                                     "%s answers it (response " + str(n_seen) + ")")
            ce.setdefault("responses", []).append({"seat": seat, "event_id": ev["event_id"]})
            ce["events"].append({"event_id": ev["event_id"], "role": "response", "n": n_seen, "family": "RESOLVE"})
        else:
            seat = str(leg.get("seat") or "A")
        out.append((leg, seat))
        prev = seat
        if role == "resolution" and (ce.get("resolve") or {}).get("manager_act"):
            # [s3-callarc] "he cuts into the call": the manager's own turn, on his own seat,
            # straight after the setup - the caller then plays the outcome out to HIM
            mseat = str(ce["resolve"].get("seat_in") or "E")
            out.append(({"id": "manager_cuts_in", "label": "The manager cuts into the call", "place": "close",
                         "seat": mseat, "act": _callend_words(conv, "", mseat).get("manager_act") or "",
                         "draws": [{"family": "ES"}]}, mseat))
            ce["manager"] = {"seat": mseat, "at": len(out) - 1}
            prev = mseat
    ce["planned"] = bool(spec) or ce.get("planned", False)
    return out, last_mid


def _callend_wrap(conv, config, inputs, seq, ends_at):
    """[s3-callend] WRAP CALL, rolled once the call's length is known: the dead-line wheel
    for a call a CALLEVENT1 ending cut short, the way a finished call is wrapped otherwise,
    tilted by what the caller's wheel landed on (`only_after`, `after`); then who on the
    station says it. Returns seq with the wrap turn's seat set. Also marks the outcome CUT
    when the line went dead before the caller played it out, and where each end turn sits."""
    ce = conv.get("callend")
    if not isinstance(ce, dict):
        return seq
    at = {"responses": []}
    for i, (leg, _seat) in enumerate(seq):
        role = _callend_role(leg)
        if role == "response":
            at["responses"].append(i)
        elif role:
            at[role] = i
    ce["at"] = at
    res = ce.get("resolve") or {}
    if res and ends_at is not None and not (at.get("reaction") is not None and at["reaction"] < ends_at):
        res["cut"] = ("the line went dead on turn %d, before %s played it out"
                      % (int(ends_at) + 1, str((conv["inputs"].get("call") or {}).get("first") or "the caller")))
        for e in conv["decision_events"]:
            if e["event_id"] in [x["event_id"] for x in ce.get("events") or []]:
                e.setdefault("meta", {})["cut"] = res["cut"]
    w = at.get("wrap")
    if w is None or w != len(seq) - 1:
        return seq
    tables = _callend_tables(config, "WRAP")
    if not tables:
        ce["wrap"] = {"planned": False, "why": "no WRAP table is switched on for calls - a spoken sign-off"}
        return seq
    leg = seq[w][0]
    pin = next((d for d in leg.get("draws") or [] if isinstance(d, dict) and d.get("family") == "WRAP"), None)
    avail = {"dead_line": ends_at is not None}
    prev_keys = set()
    if res and not res.get("cut"):
        prev_keys |= {"RESOLVE:%s" % res.get("id"), "RESOLVE:%s" % res.get("category")}
        prev_keys |= {"tag:%s" % t for t in res.get("tags") or []}
    recent = set(str(x) for x in (inputs.get("recent_items") or []))
    spec, ev = _callend_wheel(conv, tables, "WRAP", avail, prev_keys, recent, pin, "how")
    ce["events"].append({"event_id": ev["event_id"], "role": "wrap", "family": "WRAP"})
    if not spec:
        ce["wrap"] = {"planned": False, "why": (ev.get("meta") or {}).get("why") or "nothing on the wheel",
                      "event_id": ev["event_id"]}
        return seq
    table = next((t for t in tables if t["id"] == spec["table"]), {})
    names = dict(ce.get("names") or {})
    before_seat = str(seq[w - 1][1]) if w > 0 else ""
    who, wev = _callend_seat(conv, "who", table.get("who") if isinstance(table.get("who"), dict) else {},
                             ce.get("present") or ["A"], {before_seat}, names, "WRAP", "%s wraps the call")
    ce["events"].append({"event_id": wev["event_id"], "role": "wrap", "family": "WRAP"})
    ce["wrap"] = {"planned": True, "table": spec["table"], "category": spec["category"], "id": spec["id"],
                  "label": spec["label"], "text": str(spec.get("text") or ""), "polite": bool(spec.get("polite")),
                  "rebuttal": str(spec.get("rebuttal") or ""), "seat": who, "who": str(names.get(who) or who),
                  "dead_line": ends_at is not None, "event_id": ev["event_id"], "who_event_id": wev["event_id"]}
    ce["planned"] = True
    seq = list(seq)
    seq[w] = (leg, who)
    return seq


def _callend_words(conv, role, seat):
    """The words a call-end leg's act is filled with ({offer}, {outcome}, {respond},
    {rebuttal}, {wrap}, {wrapper} ...), every one of them out of a roll - or, with
    nothing rolled, the protocol the station's checker has always listened for."""
    ce = conv.get("callend") or {}
    call = (conv.get("inputs") or {}).get("call") or {}
    res = ce.get("resolve") or {}
    wrap = ce.get("wrap") or {}
    pw = _callend_painting_words(res.get("painting"))
    base = {"resolution": res.get("label") or "", "painting": pw["painting"], "price": pw["price"],
            "terms": pw["terms"], "number": str(res.get("number") or ""), "prize": str(res.get("prize") or "")}
    base.update(_callarc_words(call))                                           # [s3-callarc]

    def fill(text):
        return " ".join(_call_words(text, call, base).split()).rstrip(" .")

    words = dict(base)
    words["offer"] = fill(res.get("offer") or ("sets up how it ends for {first}: %s" % (res.get("label") or "")))
    words["outcome"] = fill(res.get("text") or "{FIRST} plays it out")
    words["respond"] = fill(res.get("respond") or CALLEND_RESPOND)
    rebuttal = fill(res.get("rebuttal") or (CALLEND_REBUTTAL if res and not res.get("cut") else CALLEND_LANDS))
    if wrap.get("planned") and wrap.get("rebuttal"):
        rebuttal += " - " + fill(wrap["rebuttal"])
    words["rebuttal"] = rebuttal
    words["wrap"] = fill(wrap["text"]) if wrap.get("planned") and wrap.get("text") else CALLEND_SIGN_OFF
    names = dict(ce.get("names") or {})
    words["wrapper"] = str(names.get(seat) or ("the host" if seat == "A" else "one of the hosts"))
    if res.get("manager_act"):
        words["manager_act"] = fill(res["manager_act"])                         # [s3-callarc]
    return words


def _callend_emotions(conv, idx):
    """[s3-callend] The caller's wheel leans the feeling the caller plays it out in."""
    ce = conv.get("callend") or {}
    res = ce.get("resolve") or {}
    if res.get("emotions") and (ce.get("at") or {}).get("reaction") == idx:
        out = {}
        for k, v in res["emotions"].items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                pass
        return out
    return {}


def _callend_attach(conv, config):
    """[s3-callend] Land the call-end rolls on their turns (the Rolodex pairs them with the
    legs' draws), put the outcome and the wrap on the turns' decisions, ask for the
    passage a speakerbox rejection is said in (on the caller's turn; the station's own
    rotation picks the document), and write the call's end in one line (`says`)."""
    ce = conv.get("callend")
    if not isinstance(ce, dict) or not ce.get("events"):
        return
    turns = conv["turns"]
    by_role = {}
    for t in turns:
        role = (t.get("callend") or {}).get("role")
        if role:
            by_role.setdefault(role, []).append(t)
    events = {e["event_id"]: e for e in conv["decision_events"]}
    for x in ce.get("events") or []:
        pool = by_role.get(x["role"]) or []
        t = pool[x["n"] - 1] if x.get("n") and len(pool) >= x["n"] else (pool[0] if pool else None)
        ev = events.get(x["event_id"])
        if t is not None and ev is not None:
            ev["turn_id"], ev["turn_index"] = t["turn_id"], t["index"]
    res = ce.get("resolve") or {}
    wrap = ce.get("wrap") or {}
    rt = (by_role.get("resolution") or [None])[0]
    if rt is not None and res.get("event_id"):
        rt["decisions"].append({"family": "RESOLVE", "event_id": res["event_id"], "table": res.get("table"),
                                "category": res.get("category"), "item": res.get("id"), "label": res.get("label"),
                                "text": res.get("text", "")})
    wt = (by_role.get("wrap") or [None])[0]
    if wt is not None and wrap.get("planned"):
        wt["decisions"].append({"family": "WRAP", "event_id": wrap["event_id"], "table": wrap.get("table"),
                                "category": wrap.get("category"), "item": wrap.get("id"), "label": wrap.get("label"),
                                "text": wrap.get("text", "")})
        wt["callend"]["wrap"] = {"seat": wrap.get("seat"), "polite": bool(wrap.get("polite"))}
    reaction = (by_role.get("reaction") or [None])[0]
    if reaction is not None and res.get("speakerbox") and not res.get("cut"):
        before = _snapshot(conv, reaction["speaker"])
        sb = config.get("speakerbox") or DEFAULT_SPEAKERBOX
        ev = _event(conv, {"turn_id": reaction["turn_id"], "turn_index": reaction["index"]}, "SPEAKERBOX", [],
                    {"id": "APPEND", "label": "the caller turns it down in a speakerbox passage, word for word",
                     "mark": "callend"}, before,
                    meta={"mark": "callend", "applies": True, "drawn": False,
                          "why": "the caller's wheel landed on %s: the passage is their answer, word for word - the "
                                 "station's own rotation picks the document" % json.dumps(res.get("label") or ""),
                          "insertion_point": "the whole of turn %d" % (reaction["index"] + 1),
                          "decided_by": res.get("event_id")})
        ev["state_after"] = before
        rec = {"mark": "callend", "mode": "APPEND", "applies": True, "event_id": ev["event_id"],
               "request_id": "%s:sbc" % reaction["turn_id"],
               "why": "the rejection the caller's wheel rolled is a speakerbox passage said word for word"}
        reaction.setdefault("speakerbox", []).append(rec)
        conv["material_requests"].append({
            "request_id": rec["request_id"], "kind": "speakbox", "turn_id": reaction["turn_id"],
            "turn_index": reaction["index"], "mode": "APPEND", "event_id": ev["event_id"], "callend": True,
            "chars": int(sb.get("passage_chars", 420)), "resolved": None})
    for t in turns:
        if (t.get("callend") or {}).get("role"):
            src = [x["event_id"] for x in t["decisions"]] + [x["event_id"] for x in t.get("speakerbox") or []] + \
                  [(t.get("sfx") or {}).get("event_id")]
            if (t.get("sfxguy") or {}).get("event_id"):
                src.append(t["sfxguy"]["event_id"])
            t["decision_bundle_id"] = "%s:b%s" % (t["turn_id"], digest(src, 8))
    ce["says"] = callend_says(conv)


def callend_says(conv):
    """The call's end in one line, as it was rolled."""
    ce = conv.get("callend") or {}
    call = (conv.get("inputs") or {}).get("call") or {}
    first = str(call.get("first") or "the caller")
    names = dict(ce.get("names") or {})
    res = ce.get("resolve") or {}
    wrap = ce.get("wrap") or {}
    bits = []
    if res:
        what = "the caller's wheel landed on %s" % json.dumps(res.get("label") or "")
        extra = []
        if res.get("painting"):
            extra.append("the painting: %s" % _callend_painting_words(res["painting"])["painting"])
        if res.get("number"):
            extra.append("caller number %s" % res["number"])
        if res.get("prize"):
            extra.append("the prize: %s" % res["prize"])
        if extra:
            what += " (%s)" % "; ".join(extra)
        if res.get("cut"):
            what += " - but %s" % res["cut"]
        bits.append(what)
        chain = [str(names.get(r.get("seat")) or r.get("seat")) for r in ce.get("responses") or []]
        if chain and not res.get("cut"):
            bits.append("%s answer%s it" % (" then ".join(chain), "" if len(chain) > 1 else "s"))
            bits.append("%s gets the last word" % first)
    if wrap.get("planned"):
        bits.append("%s wraps the call: %s" % (wrap.get("who") or wrap.get("seat") or "the host",
                                               _call_words(wrap.get("text") or wrap.get("label") or "", call).rstrip(".")))
    return "; ".join(bits)[:600]


def callend_mark(conv):
    """[s3-callend] What the station keeps of a planned call's end, on the call's meta:
    the checker keys on it (the WRAP CALL node is the sign-off, whatever its words), the
    booth and the call log say it, and the topic contract leaves the call's end out.
    None when nothing was rolled."""
    ce = conv.get("callend") or {}
    if not ce.get("planned"):
        return None
    res = ce.get("resolve") or {}
    wrap = ce.get("wrap") or {}
    at = ce.get("at") or {}
    turns = conv.get("turns") or []
    start = min([i for i in [at.get("resolution"), at.get("reaction"), at.get("rebuttal"), at.get("wrap")]
                 + list(at.get("responses") or []) if isinstance(i, int)] or [len(turns)])
    wt = next((t for t in turns if (t.get("callend") or {}).get("role") == "wrap"), None)
    painting = res.get("painting") or {}
    return {
        "planned": True, "by": "system3", "conversation_id": conv["identity"]["conversation_id"],
        "resolve": ({"id": res.get("id"), "label": res.get("label"), "category": res.get("category"),
                     "table": res.get("table"), "effect": res.get("effect") or "", "tags": list(res.get("tags") or []),
                     "number": res.get("number"), "prize": res.get("prize") or "",
                     "speakerbox": bool(res.get("speakerbox")), "cut": str(res.get("cut") or ""),
                     "manager_act": str(res.get("manager_act") or ""), "seat_in": str(res.get("seat_in") or ""),  # [s3-callarc]
                     "painting": ({k: painting.get(k) for k in ("image", "title", "price", "kind")
                                   if painting.get(k) not in (None, "")} if painting else {})}
                    if res else {}),
        "wrap": ({"planned": True, "id": wrap.get("id"), "label": wrap.get("label"), "polite": bool(wrap.get("polite")),
                  "seat": wrap.get("seat"), "who": wrap.get("who"), "dead_line": bool(wrap.get("dead_line")),
                  "turn_id": (wt or {}).get("turn_id", "")}
                 if wrap.get("planned") else {"planned": False}),
        "turns": len(turns), "end_turns": max(0, len(turns) - start), "says": ce.get("says") or callend_says(conv),
        "arc": dict(conv.get("callarc") or {}), "detour": dict(conv.get("callshift") or {}),     # [s3-callarc]
        # the detour's turns, by index: off topic on purpose, so the topic contract leaves them out
        "detour_turns": [i for i, t in enumerate(turns) if _is_detour_leg(t.get("leg"))],
        # [call-prod] every turn's leg and seat, so a banked call can be produced take by take
        "legs": [str(t.get("leg") or "") for t in turns], "seats": [str(t.get("speaker") or "") for t in turns],
    }


def _callend_row(t):
    """What a call-end row adds on the running order: the passage a rejection is said in,
    word for word, and a wrap that is no goodbye said as such."""
    ce = t.get("callend") or {}
    if not ce.get("role"):
        return ""
    add = ""
    for sb in t.get("speakerbox") or []:
        if sb.get("mark") != "callend":
            continue
        mat = sb.get("material") or {}
        if mat.get("text"):
            add += " [THE PASSAGE, said word for word as their whole answer: %s]" % json.dumps(
                sentence_cut(mat["text"], 420))
        else:
            add += " [No passage came back for it: they turn it down in words of their own, flat as a quotation.]"
    if ce.get("role") == "wrap" and (ce.get("wrap") or {}).get("seat") and not (ce.get("wrap") or {}).get("polite"):
        add += " [It ends the way it was rolled - this need not be a polite goodbye.]"
    return add


def _callend_tail(conv, tail):
    """The call sheet's closing words, when a WRAP CALL was rolled."""
    return CALLEND_TAIL if ((conv.get("callend") or {}).get("wrap") or {}).get("planned") else tail


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


# --- [s3-callarc] THE CALL AS RADIO: its arc, its detour (system3_tables CALLARC1, CALLSHIFT1) ---

def _callarc_avail(call):
    """What the station has in play for a call, as the wheels' `requires` read it."""
    unsold = call.get("unsold") if isinstance(call.get("unsold"), dict) else {}
    return {"memo": bool(str(call.get("memo") or "").strip()), "news": bool(str(call.get("news") or "").strip()),
            "unsold": bool(unsold.get("name")), "gallery": bool(unsold.get("name")),
            "passage": bool(str(call.get("speakerbox") or "").strip())}


def _callarc_words(call):
    unsold = call.get("unsold") if isinstance(call.get("unsold"), dict) else {}
    manager = str(call.get("manager") or "the manager")
    return {"memo": whole_cut(str(call.get("memo") or "his latest memo"), 260).rstrip(" ."),
            "news": whole_cut(str(call.get("news") or "the news"), 200).rstrip(" ."),
            "unsold": str(unsold.get("title") or unsold.get("name") or "a painting off the pile"),
            "manager": manager, "MANAGER": manager.upper(),
            "topic": whole_cut(str(call.get("topic") or "what they rang about"), 140).rstrip(" .")}


def _callarc_chance(conv, family, what, odds, yes, no):
    """One recorded yes/no roll on its own stream (seed|callarc:<family>:<what>): the
    odds are the candidates' weights, so the ledger shows the chance it was taken at."""
    before = _snapshot(conv, (conv.get("cursor") or {}).get("initiator"))
    p = max(0.0, min(1.0, float(odds)))
    rows = [{"id": "yes", "label": yes, "base": p, "weight": p, "why": ["%d%% chance" % round(p * 100)]},
            {"id": "no", "label": no, "base": 1.0 - p, "weight": 1.0 - p, "why": []}]
    d = DrawStream(str(conv["seed"]) + "|callarc:%s:%s" % (family, what)).next("%s:%s" % (family, what))
    i = pick_index([r["weight"] for r in rows], d["u"])
    i = i if i in (0, 1) else 1
    sel = {"id": rows[i]["id"], "label": rows[i]["label"], "kind": what, "odds": round(p, 4)}
    ev = _event(conv, dict(_CALLEND_AT), family, [_stage(what, rows, i, d)], sel, before,
                meta={"kind": what, "odds": round(p, 4)})
    ev["state_after"] = before
    return i == 0, ev


def _call_detour(conv, config, inputs, call, recent):
    """The caller's detour: whether they change the subject (first_odds), to what (the
    source and the bridge, rolled), then the GRADUATING steer-back rolls - each one more
    likely than the last, a miss taking them further off topic. Legs from a host-ended
    opening to a host-ended close: C, A, then C / host pairs, the last a host."""
    tables = _callend_tables(config, "CALLSHIFT")
    info = {"rolled": False, "events": []}
    conv["callshift"] = info
    if not tables:
        info["why"] = "no CALLSHIFT table is switched on for calls"
        return []
    t0 = tables[0]
    try:
        first = float(t0.get("first_odds", 0.8))
        start, step = float(t0.get("back_start", 0.35)), float(t0.get("back_step", 0.2))
        most = max(1, min(5, int(t0.get("most", 3))))
    except (TypeError, ValueError):
        first, start, step, most = 0.8, 0.35, 0.2, 3
    words = _callarc_words(call)
    hit, ev = _callarc_chance(conv, "CALLSHIFT", "detour", first, "changes the subject", "stays on topic")
    info.update(rolled=True, detour=hit, events=[{"event_id": ev["event_id"], "leg": "topic_shift"}])
    if not hit:
        return []
    spec, ev2 = _callend_wheel(conv, tables, "CALLSHIFT", _callarc_avail(call), (), recent, None, "subject")
    info["events"].append({"event_id": ev2["event_id"], "leg": "topic_shift"})
    if not spec:
        info["why"] = "nothing to change the subject to"
        return []
    src = str(spec.get("source") or "life")
    subject = {"memo": "the manager's memo - " + words["memo"], "news": "the news - " + words["news"],
               "gallery": "the painting " + words["unsold"],
               "passage": "something they read - " + whole_cut(str(call.get("speakerbox") or ""), 200)
               }.get(src) or str(spec.get("subject") or "something from their own life")
    bridge = str(spec.get("bridge") or "\"anyway - \"")
    info.update(source=src, subject=subject, bridge=bridge, category=spec.get("category_label"))
    w = dict(words, subject=subject, bridge=bridge)

    def leg(lid, label, seat, act):
        return {"id": lid, "label": label, "place": "middle", "seat": seat, "callshift": True,
                "act": _call_words(act, call, w), "draws": [{"family": "ES"}, {"family": "RS"}]}

    legs = [leg("topic_shift", "The caller changes the subject", "C",
                "{FIRST} CHANGES THE SUBJECT - crosses on a bridge line, {bridge} - and starts on {subject}; "
                "what they rang about ({topic}) is left behind for now."),
            leg("steer_1", "A host goes with it, then steers back", "A",
                "goes with the new subject for one beat, then TRIES TO STEER {first} BACK to {topic}.")]
    came_back = False
    rolls = []
    for k in range(most):
        p = min(0.95, start + step * k)
        back, evk = _callarc_chance(conv, "CALLSHIFT", "back_%d" % (k + 1), p,
                                    "steered back on topic", "goes further off topic")
        rolls.append({"n": k + 1, "odds": round(p, 4), "back": back})
        if back:
            legs.append(leg("back_on_topic", "Back on topic (roll %d at %d%%)" % (k + 1, round(p * 100)), "C",
                            "{FIRST} COMES BACK TO {topic} - with one thing the detour made them realise."))
            info["events"].append({"event_id": evk["event_id"], "leg": "back_on_topic"})
            came_back = True
            break
        legs.append(leg("further_%d" % (k + 1), "Further off topic (roll %d at %d%%)" % (k + 1, round(p * 100)), "C",
                        "{FIRST} GOES EVEN FURTHER OFF TOPIC - from {subject} on to whatever it reminds them of "
                        "next, and does not notice."))
        info["events"].append({"event_id": evk["event_id"], "leg": "further_%d" % (k + 1)})
        if k < most - 1:
            legs.append(leg("steer_%d" % (k + 2), "Steers again", "B" if k % 2 == 0 else "A",
                            "TRIES AGAIN to steer {first} back to {topic} - firmer this time."))
    legs.append(leg("detour_lands", "Back on track" if came_back else "Goes along with it",
                    "B" if legs[-2]["seat"] == "A" else "A",
                    "picks up {first}'s point and takes it on" if came_back else
                    "GIVES UP STEERING - goes along with wherever {first} has ended up."))
    info.update(came_back=came_back, rolls=rolls)
    return legs


def _is_detour_leg(leg_id):
    leg_id = str(leg_id or "")
    return (leg_id in ("topic_shift", "back_on_topic", "detour_lands") or leg_id.startswith("steer_")
            or leg_id.startswith("further_"))


def _call_arc(conv, config, inputs, call, recent):
    """The call's arc, one roll per call: the category's beats are its legs."""
    tables = _callend_tables(config, "CALLARC")
    info = {"rolled": False}
    conv["callarc"] = info
    if not tables:
        info["why"] = "no CALLARC table is switched on for calls"
        return []
    spec, ev = _callend_wheel(conv, tables, "CALLARC", _callarc_avail(call), (), recent, None, "arc")
    info.update(rolled=True, event_id=ev["event_id"])
    if not spec:
        info["why"] = "no arc could come up"
        return []
    w = dict(_callarc_words(call), tone=str(spec.get("tone") or spec.get("label") or ""))
    legs = []
    for b in spec.get("beats") or []:
        if not isinstance(b, dict) or not b.get("act"):
            continue
        legs.append({"id": str(b.get("id") or "arc"), "label": "%s (%s)" % (b.get("label") or b.get("id"),
                                                                           spec.get("category_label")),
                     "place": "middle", "seat": str(b.get("seat") or "C"), "arc": spec.get("category"),
                     "act": _call_words(b["act"], call, w), "draws": [{"family": "ES"}, {"family": "RS"}]})
    info.update(arc=spec.get("category"), label=spec.get("category_label"), tone=spec.get("label"),
                beats=[x["id"] for x in legs])
    return legs


def _call_spine(conv, config, inputs, call, last_mid):
    """[s3-callarc] The middle of a call: the detour after the opening, then the arc - or
    [] (no tables on), when the middle leg fills the budget as before. The spine ends on
    `last_mid`, the seat the call's end wants before it."""
    recent = set(str(x) for x in (inputs.get("recent_items") or []))
    detour = _call_detour(conv, config, inputs, call, recent)
    arc = _call_arc(conv, config, inputs, call, recent)
    spine = detour + arc
    if spine and str(spine[-1].get("seat") or "") != str(last_mid):
        spine.append({"id": "arc_turn", "label": "Turns it toward the end", "place": "middle", "seat": last_mid,
                      "act": "answers the last thing said and turns the call toward how it ends.",
                      "draws": [{"family": "ES"}, {"family": "RS"}]})
    return spine


def _callarc_attach(conv):
    """Put the arc's and the detour's events on the turns they made (the Rolodex and the
    flowchart read turn_index)."""
    turns = conv.get("turns") or []
    by_id = {}
    for t in turns:
        by_id.setdefault(str(t.get("leg") or ""), t)
    evs = {e.get("event_id"): e for e in conv.get("decision_events") or []}
    pairs = list((conv.get("callshift") or {}).get("events") or [])
    arc = conv.get("callarc") or {}
    if arc.get("event_id") and arc.get("beats"):
        pairs.append({"event_id": arc["event_id"], "leg": arc["beats"][0]})
    for pr in pairs:
        ev, t = evs.get(pr.get("event_id")), by_id.get(str(pr.get("leg") or ""))
        if ev is not None and t is not None:
            ev["turn_index"], ev["turn_id"] = t.get("index"), t.get("turn_id", "")


def plan_call(conv, config, inputs=None):
    """[s3-calls] A request-line call, planned from System 3's own call
    structure: the open legs in order, the middle leg repeated to the turn
    budget (seats alternating back from the landing, so a host speaks just
    before it), then the closing legs - every leg a turn with its own rolls.
    The TOPIC roll may raise something off the board on a middle leg."""
    inputs = inputs if inputs is not None else conv["inputs"]
    config = event_view(config, inputs)                          # [s3-live-event]
    call = inputs.get("call") or {}
    st = road_structure(config, "caller") or {}
    legs = [dict(x) for x in st.get("legs") or [] if isinstance(x, dict)]
    if call.get("story"):                                                       # [s3-story]
        swap = dict(st.get("story_acts") or system3_tables.STORY_ACTS)
        for leg in legs:
            if leg.get("id") in swap:
                leg["act"] = swap[leg["id"]]
                leg["label"] = "%s (a call-back)" % (leg.get("label") or leg["id"])
    opening = [x for x in legs if x.get("place") == "open"]
    middle = [x for x in legs if x.get("place") == "middle"]
    closing = [x for x in legs if x.get("place") == "close"]
    lo, hi = int(st.get("min_turns") or 9), int(st.get("max_turns") or 22)
    want = max(lo, min(int(inputs.get("turns") or 0) or 10, hi))
    # [s3-callend] the call's end is rolled first, on its own streams: how many turns it takes
    closing, _last_mid = _callend_close(conv, config, inputs, opening, middle, closing, want)
    # [s3-callarc] the middle is the call's own arc and detour, rolled; the old middle leg
    # fills the budget only when neither table is on
    spine = _call_spine(conv, config, inputs, call, _last_mid)
    fill_n = 0 if spine else (max(0, want - len(opening) - len(closing)) if middle else 0)
    seq = [(leg, leg.get("seat")) for leg in opening]
    seq += [(leg, leg.get("seat")) for leg in spine]
    for k in range(fill_n):
        leg = middle[k % len(middle)]
        seq.append((leg, _call_mid_seat(leg, k, fill_n, _last_mid)))
    seq += list(closing)
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
    seq = _callend_wrap(conv, config, inputs, seq, _ev["ends_at"])                  # [s3-callend] WRAP CALL
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
        step = {"id": leg.get("id"), "label": leg.get("label") or leg.get("id"),
                "draws": [d for d in (leg.get("draws") or []) if (d or {}).get("family")   # [s3-callend] own streams
                          not in system3_tables.CALLEND_FAMILIES] or [{"family": "ES"}]}
        turn = _decide_turn(conv, config, conv["settings"], stream, step, seat, want, inputs)
        _end = _callend_role(leg)
        turn["protocol"] = (whole_cut(_call_words(leg.get("act"), call, _callend_words(conv, _end, seat)), 700) if _end
                            else whole_cut(_call_words(leg.get("act"), call), 400))
        if _end:
            turn["callend"] = {"role": _end}
        turn["leg"] = leg.get("id")
        turn["place"] = leg.get("place")
    conv["draws"] = stream.n
    _events_attach(conv)                                                        # [s3-events]
    _cast_rolls(conv, config, conv["settings"], inputs)                         # [s3-cast]
    _callend_attach(conv, config)                                               # [s3-callend]
    _callarc_attach(conv)                                                       # [s3-callarc]
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
        add = _leg_row_add(t) + _callend_row(t)                               # [s3-callend]
        rows.append("%2d  %s  - %s%s" % (t["index"] + 1, t["speaker"], t.get("protocol") or "keeps it going.", add))
        if i == material_at and call.get("speakerbox") and st.get("material"):
            rows.append(_call_words(st["material"], call, {"passage": json.dumps(sentence_cut(call["speakerbox"], 300))}))
    head = _call_words(st.get("head") or "", call, {"caller_turns": max(3, int(len(turns) * share))})
    tail = st.get("tail") or ""
    tail = _callend_tail(conv, tail)                                          # [s3-callend] the rolled ending
    if conv.get("event_end") is not None:                                   # [s3-events]
        tail = ("This call ENDS EARLY, on the turn the running order says: the line goes dead partway through "
                "it, and a host reacts to that on the last turn. The caller does not land their story and nobody "
                "signs them off - they are gone.")
    text = "\n\n" + head + _tempers_line(conv) + "\n" + "\n".join(rows) + "\n" + tail   # [s3-rounds] [s3-events]
    if call.get("scenario_clause"):
        text += "\n" + str(call["scenario_clause"])
        if any(direction_block(t) for t in turns):                           # [s3-direction] the roll outranks it
            text += (" Where a turn's DIRECTION FOR THIS LINE rolls a feeling, that feeling outranks the "
                     "register and the heat named here.")
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
        # [s3-es-dir] the feeling's own words - not on a drawn stock line (its words are fixed)
        _es = "" if any(x.get("family") == "LINE" for x in t.get("decisions") or []) \
            else (direction_block(t) or _es_line(t))                          # [s3-direction] legs, calls, lines
        if _es:
            add += ". " + _es.rstrip(".")
        add += ".]"
    topic = t.get("bank_topic") or {}
    if topic.get("text"):
        add += (" [It puts them in mind of something off the operator's topics board, and they "
                "bring it up in their own words: %s.]" % json.dumps(sentence_cut(topic["text"], 400)))
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


def plan_legs(conv, config, inputs=None, road=None, structure=None):
    """[s3-roads] A segment planned from its own structure: the open legs
    in order, the middle leg(s) repeated to the turn budget with the seats
    alternating, then the landing - every leg a turn with its own rolls.
    The road's subject stays the road's (CTS OBLIGATED at turn 0). A road
    with no legs structure falls back to the banter cycle."""
    inputs = inputs if inputs is not None else conv["inputs"]
    config = event_view(config, inputs)                          # [s3-live-event]
    road = road or conv["identity"]["road_kind"]
    if isinstance(structure, dict) and structure.get("legs"):
        st, _variant = structure, None   # [nodeplan] elected by the caller: one VARIANT draw, not two
    else:
        st, _variant = _structure_roll(conv, config, road)              # [s3-window]
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
        turn["protocol"] = whole_cut(_legs_words(leg.get("act"), inputs), 400)
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
    try:
        prompt_mark(conv, rows)                                               # [prompt-share]
    except Exception:  # noqa: BLE001
        pass
    who, quoted = _carry_landing(conv)                                        # [s3-carry]
    carry_line = ("\nIt follows straight on from the last exchange, which landed on %s's words: %s - turn 1 picks up "
                  "from there." % (who, quoted)) if quoted else ""
    return ("\n\n" + str(st.get("head") or "") + _tempers_line(conv) + carry_line + "\n" + "\n".join(rows)
            + "\n" + str(st.get("tail") or ""))


def _line_draw(conv, stream, inputs, road, turn):
    """[nodeplan] The LINE draw among the road's candidate lines, every
    candidate and its weight recorded - the Rolodex where the station used
    to call random.choice(). Attached to `turn`. Returns the candidates."""
    cands = [c for c in (inputs.get("candidates") or []) if isinstance(c, dict) and c.get("text")]
    if not cands or turn is None:
        return cands
    rows = []
    for i, c in enumerate(cands[:200]):
        w = float(c.get("weight", 1.0) or 0)
        rows.append({"id": str(c.get("id") or i), "label": label_cut(c.get("text") or ""), "base": w,
                     "weight": max(0.0, w), "why": list(c.get("why") or [])})
    live = [r for r in rows if r["weight"] > 0] or rows
    draw = stream.next("LINE:item")
    k = pick_index([r["weight"] for r in live], draw["u"])
    stage = _stage("item", live, k, draw, [{"id": r["id"], "label": r["label"], "why": "weight 0"}
                                          for r in rows if r["weight"] <= 0])
    picked = live[k] if k >= 0 else None
    ev = _event(conv, {"turn_id": turn["turn_id"], "turn_index": turn["index"], "speaker": turn["speaker"]},
                "LINE", [stage], {"id": picked["id"] if picked else None,
                                  "label": picked["label"] if picked else "", "index": k + 1, "of": len(live)},
                _snapshot(conv, turn["speaker"]),
                meta={"road": road, "source": str(inputs.get("candidates_from") or "the road's own list")},
                rng=draw)
    conv["line_choice"] = {"index": (k if k >= 0 else None), "id": picked["id"] if picked else None,
                           "event_id": ev["event_id"], "of": len(live)}
    turn["decisions"].append({"family": "LINE", "event_id": ev["event_id"], "item": conv["line_choice"]["id"],
                              "label": picked["label"] if picked else "", "u": draw["u"]})
    return cands


def plan_line(conv, config, inputs=None):
    """[s3-roads] A single-voice road (a record link, a station ID, the
    manager's own page, a stock interjection, a produced spot) as System 3
    nodes: one seat, one or more legs from its structure, ES on each - and,
    when the road hands over a list of candidate lines, a LINE draw among
    them with every candidate and its weight recorded. That draw is the
    Rolodex where the station used to call random.choice()."""
    inputs = inputs if inputs is not None else conv["inputs"]
    config = event_view(config, inputs)                          # [s3-live-event]
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
        turn["protocol"] = whole_cut(_legs_words(leg.get("act"), inputs), 400)
        turn["leg"] = leg.get("id")
        turn["place"] = leg.get("place")
    cands = _line_draw(conv, stream, inputs, road, conv["turns"][-1] if conv["turns"] else None)
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


def direction_block(turn, conv=None):
    """[s3-direction] The rolls on this turn as the writer's DIRECTION FOR THIS
    LINE, in roll order: the character, the ES family, the feeling and how hard,
    how big to play it, the item's direction, then its acting - the first words
    (quoted: saying one is never a direction's echo), the lexicon, what they
    want - the temper under it and the shock beat over it. "" when no feeling
    was rolled."""
    es = next((d for d in turn.get("decisions") or [] if d.get("family") == "ES" and d.get("item")), None)
    if not es:
        return ""
    name = " ".join(str(turn.get("name") or turn.get("speaker") or "the speaker").split())
    perf = turn.get("performance") or {}
    inten = float(perf.get("intensity") if perf.get("intensity") is not None else (es.get("intensity") or 0))
    feeling = str(es.get("label") or perf.get("emotion") or es.get("item"))
    fam = str(es.get("category") or perf.get("family") or "").replace("_", " ").upper()
    turns = (conv or {}).get("turns") or []
    i = int(turn.get("index") or 0)
    prev = turns[i - 1] if 0 < i <= len(turns) else None
    prev_name = str((prev or {}).get("name") or (prev or {}).get("speaker") or "")
    out = "%s (%s): %sfeeling %s (%s)%s - PLAY IT %s." % (
        DIRECTION_LABEL, name, (fam + " > ") if fam else "", feeling, _intensity_word(inten),
        (" about %s's line" % prev_name) if prev_name else "", acting_scale(inten))
    said = " ".join(str(es.get("direction") or "").split())
    if said:
        out += " " + (said if said.endswith((".", "!", "?")) else said + ".")
    acting = es.get("acting") if isinstance(es.get("acting"), dict) else {}
    if acting.get("act") and acting["act"].lower() not in said.lower():
        out += " " + acting["act"].rstrip(".") + "."
    if acting.get("blurts"):
        out += (" First words out, something LIKE %s - a fresh one, never the same twice."
                % " / ".join(json.dumps(x) for x in acting["blurts"]))
    if acting.get("says"):
        out += (" Words they reach for, inside their own sentences and never read out as a list: %s."
                % ", ".join(json.dumps(x) for x in acting["says"][:3]))
    if acting.get("wants"):
        out += " What %s wants: %s." % (name, acting["wants"].rstrip("."))
    temper = ((conv or {}).get("tempers") or {}).get(turn.get("speaker")) or {}
    if temper.get("text"):
        out += " Under it all tonight: %s." % str(temper["text"]).rstrip(".")
    if (turn.get("shock") or {}).get("text"):
        out += " Then it BOILS OVER: openly %s." % str(turn["shock"]["text"]).upper()
    return out


def _row_work(turn, conv):
    if turn.get("split_of"):                                                  # [s3-split] a part taken over
        return _split_row_work(turn, conv)
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
                % (prev0_name, phrases or "a bare reaction", (", said in %s" % feel) if feel else "", prev0_name)
                + _es_sentence(turn))                                         # [s3-es-dir]
    if turn["step"] == "carry_on":                                            # [s3-rounds]
        feel = _feel_words(turn)
        return ("carries straight on over the interruption and finishes the thought they were on - does not "
                "answer %s, does not restart, keeps the head of steam%s." % (prev0_name, (", in %s" % feel) if feel else "")
                + _es_sentence(turn))                                         # [s3-es-dir]
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
    # [s3-direction] the rolls close the row; a line whose words are fixed keeps its feeling word only
    _dir = "" if (answer_line or (turn["index"] == 0 and bool(exchange.get("opener") or conv["subject"].get("seeded")))) \
        else direction_block(turn, conv)
    if _dir:
        feel = ""
    # [s3-gold:sheet] a gold reply the roulette landed on: the words are the kept
    # line, fixed; the direction rolled above still governs how it is delivered
    _gold_txt = str((turn.get("gold") or {}).get("text") or "") if (replying and not answer_text) else ""
    if _gold_txt:
        answer_text, answer_line = _gold_txt, True
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
    if _gold_txt:                                                             # [s3-gold:desc]
        desc = ("answers %s with a line the station kept - a callback, these exact words, as written: %s"
                % (prev_name, json.dumps(_gold_txt)))
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
    if _dir:                                                                  # [s3-direction] right after what the turn does
        body = (body.rstrip(".") + ". " if body else "") + _dir.rstrip(".")
    if turn.get("graph_node") and turn.get("protocol"):
        body += (". " if body else "") + str(turn["protocol"])
    if turn.get("graph_handling"):
        body += (". " if body else "") + "Internally %s" % turn["graph_handling"]
    if turn.get("graph_intonation") and not _dir:                            # [s3-direction] the roll is the intonation
        body += (". " if body else "") + "Deliver this in a %s intonation" % turn["graph_intonation"]
    if turn.get("graph_node") and turn.get("planned_seconds"):
        body += ". Allow about %d seconds for this turn" % round(float(turn["planned_seconds"]))
    # [s3-es-dir] the feeling's own words for this line - not on a line whose words are fixed
    _fixed = answer_line or (turn["index"] == 0 and bool(exchange.get("opener") or conv["subject"].get("seeded")))
    _es = "" if (_fixed or _dir) else _es_line(turn)                        # [s3-direction] the block says it
    if _es:
        body = (body + ". " if body else "") + _es.rstrip(".")
    for sb in turn.get("speakerbox") or []:
        mat = sb.get("material") or {}
        if not mat.get("text"):
            continue
        quoted = json.dumps(sentence_cut(mat["text"], 420))            # [s3-cut]
        if sb["mode"] == "FULL_SWATH":
            # [s3-split] the passage whole - it is already cut to the monologue budget
            # at a sentence end; a second cap here stopped the monologue short
            body += (". Opens with a speaker-box monologue, reading this out word for word as their "
                     "own words: %s" % json.dumps(" ".join(str(mat["text"]).split())))
            body += _split_hand_on(turn, conv)                                # [s3-split]
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
                 "bring it up in their own words: %s" % json.dumps(sentence_cut(topic["text"], 400)))
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
        if record.get("direction"):                                   # [s3-live-event]
            add += (". Briefly connects the thought just exchanged to what is playing underneath - not a "
                    "record but %s, LIVE: %s. One passing moment inside the conversation; never invent a "
                    "title or an artist for a live set" %
                    (json.dumps(str(record.get("title") or "the live set")),
                     str(record["direction"]).strip().rstrip(".")))
        else:
            add += (". Briefly connects the thought just exchanged to the record playing underneath, %s by %s. "
                    "This is one passing moment inside the conversation, not a separate introduction or send-off" %
                    (json.dumps(str(record.get("title") or "the record")),
                     json.dumps(str(record.get("artist") or "the artist"))))
    return add


# --- [s3-scaffold] a prompt's own headers never reach the air --------------------
#
# 2026-09-28: lines AIRED ending "... TONIGHT'S TEMPERS : 1" and "... TONIGHT'S TEMPERS
# : A is deadly serious, ...; B is bored to the back teeth and barely hiding it." -
# the writer echoed the running order's own header into the last turn - and others
# opening on a row's own label: "The subject changes here: I was in the kitchen.",
# "LANDS IT: back to the station, glowing. ...", "BACK TO THE MUSIC: one line that
# closes the bulletin and hands over." (the ledger since 2026-09-27: 2 + 5 + 4). The
# labels are the ones System 3 writes into a writer's prompt, read off its own texts:
#   sections  its sheets' headers, every structure's head, tail and material, every
#             prompt block's name and label. What follows one is prompt, not speech:
#             cut to the end of its paragraph. Two words or more match in any case
#             before a colon and in capitals before a full stop; one word only in
#             capitals, before a colon.
#   rows      a running-order row's own label - every leg's act opens on one ("LANDS
#             IT: ...") - and the sheet's THE SUBJECT CHANGES HERE, TAKES OVER THE LEAD
#             (from ...) and WHAT HAPPENS ON THIS TURN (...). The line may follow
#             one, so only the label goes, with the row's own direction words when
#             they were echoed after it. In capitals (the subject change in any case).
# A header starts a line or a sentence. find_scaffold is the validator's check.
TEMPERS_LABEL = "TONIGHT'S TEMPERS"
BOOTH_LABEL = "IN THE BOOTH"
EXCHANGE_LABEL = "THE RUNNING ORDER OF THIS EXCHANGE"
SUBJECT_LABEL = "THE SUBJECT CHANGES HERE"
LEAD_LABEL = "TAKES OVER THE LEAD"                  # [s3-booth] a row where the lead changes hands
LEAD_WHY = "their take won the room, so from here they drive the conversation and the others answer them"
EVENT_LABEL = "WHAT HAPPENS ON THIS TURN"          # [s3-events] a row's happening
SHEET_LABELS = (EXCHANGE_LABEL, TEMPERS_LABEL, BOOTH_LABEL)
_CAPS_HEAD = re.compile(r"^[^A-Za-z{]*([A-Z][A-Z'\u2019-]*(?:[ \t]+[A-Z][A-Z'\u2019-]*)*)(?![a-z])")
_PARAGRAPH_END = re.compile(r"\n[ \t]*\n")
_HEAD_AT = r"(?:^|(?<=\n)|(?<=[.!?\u2026\"\u201d')\]])[ \t]+)[ \t]*"
_PAREN = r"[ \t]*(?:\([^)\n]{0,40}\))?[ \t]*"
_SCAFFOLD_RX = {}


def _caps_label(text, words=1):
    m = _CAPS_HEAD.match(str(text or ""))
    lab = " ".join(m.group(1).split()).strip(" -'") if m else ""
    return lab if len(lab.replace(" ", "")) >= 3 and len(lab.split()) >= words else ""


def scaffold_kit(config=None, conv=None):
    """(sections, rows): every label System 3 writes into a writer's prompt,
    longest first; rows carry the direction words that follow them."""
    cfg = config if isinstance(config, dict) else {}
    sts = list(system3_tables.default_structures().values()) + [system3_tables.default_structure()]
    sts += [v for v in (cfg.get("structures") or {}).values() if isinstance(v, dict)]
    if isinstance(cfg.get("structure"), dict):
        sts.append(cfg["structure"])
    if isinstance(conv, dict):
        sts += [conv.get("road_structure") or {}, conv.get("call_structure") or {}]
    sections = list(SHEET_LABELS)
    rows = {SUBJECT_LABEL: set(), LEAD_LABEL: {LEAD_WHY}, EVENT_LABEL: set(),
            DIRECTION_LABEL: set()}                                          # [s3-direction]
    for st in sts:
        for key in ("head", "tail", "material"):
            sections.append(_caps_label(st.get(key)))
        for leg in st.get("legs") or []:
            act = str((leg or {}).get("act") or "") if isinstance(leg, dict) else ""
            lab = _caps_label(act, words=2)
            if lab:
                rest = act[act.find(lab.split()[-1]) + len(lab.split()[-1]):].lstrip(" :.-")
                rows.setdefault(lab, set()).add(" ".join(rest.split())[:300])
    for name, rule in block_rules(cfg).items():
        sections.append(str(name).replace("_", " ").upper())
        sections.append(_caps_label((rule or {}).get("label")))
    keep = sorted({x for x in sections if x and x == x.upper() and x not in rows}, key=lambda x: (-len(x), x))
    return (tuple(keep), tuple(sorted(((k, tuple(sorted(v))) for k, v in rows.items()),
                                      key=lambda kv: (-len(kv[0]), kv[0]))))


def scaffold_labels(config=None, conv=None):
    """Every label on the kit, sections and rows, longest first."""
    sections, rows = scaffold_kit(config, conv)
    return tuple(sorted(set(sections) | {k for k, _v in rows}, key=lambda x: (-len(x), x)))


def _label_rx(label):
    return r"\s+".join(re.escape(w) for w in label.split()).replace("'", "['\u2019]")


def _scaffold_rx(kit):
    got = _SCAFFOLD_RX.get(kit)
    if got is not None:
        return got
    sections, rows = kit
    multi = "|".join(_label_rx(x) for x in sections if " " in x)
    single = "|".join(_label_rx(x) for x in sections if " " not in x)
    alts = []
    if multi:
        alts += [r"(?i:%s)%s:" % (multi, _PAREN), r"(?:%s)%s[:.]" % (multi, _PAREN)]
    if single:
        alts.append(r"(?:%s)%s:" % (single, _PAREN))
    sec = re.compile(_HEAD_AT + r"(%s)" % "|".join(alts)) if alts else None
    caps = "|".join(_label_rx(k) for k, _v in rows if k != SUBJECT_LABEL)
    row_alts = [r"(?i:%s)%s:" % (_label_rx(SUBJECT_LABEL), _PAREN)]
    if caps:
        row_alts.append(r"(?:%s)%s[:.]" % (caps, _PAREN))
    row = re.compile(_HEAD_AT + r"(%s)" % "|".join(row_alts))
    tails = {k: [re.compile(r"[ \t]*" + r"\W*".join(re.escape(w) for w in c.split()) + r"[^\w\s]*", re.I)
                 for c in sorted(v, key=len, reverse=True) if c.split()] for k, v in rows}
    if len(_SCAFFOLD_RX) > 16:
        _SCAFFOLD_RX.clear()
    _SCAFFOLD_RX[kit] = got = (sec, row, tails)
    return got


def _row_label_of(found, rows):
    words = " ".join(re.sub(r"\([^)]*\)", " ", found).replace("\u2019", "'").strip(" :.").split()).upper()
    return next((k for k, _v in rows if " ".join(k.split()) == words), SUBJECT_LABEL)


def find_scaffold(text, kit=None):
    """The prompt header or row label echoed in `text`, or ""."""
    sec, row, _t = _scaffold_rx(kit if kit is not None else scaffold_kit())
    s = str(text or "")
    for rx in (sec, row):
        m = rx.search(s) if rx is not None else None
        if m:
            return " ".join(m.group(1).split())
    return ""


# [s3-direction] a rolled feeling said as a label - "Suspicion: ...", "Disbelief: ...",
# "In fury, hard: ..." (aired 2026-09-29) - is the direction, not a word: the label goes.
_FEEL_RX = []


def _feel_prefix_rx():
    """[s3-direction] A line (or a line of a turn) that opens on an ES label with a colon or a dash."""
    if not _FEEL_RX:
        labels = set()
        for table in (getattr(system3_tables, "ES1", None), getattr(system3_tables, "ES1_V2", None)):
            for cat in (table or {}).get("categories") or []:
                labels.update((str(cat.get("id") or "").replace("_", " "), str(cat.get("label") or "")))
                labels.update(str(i.get("label") or "") for i in cat.get("items") or [])
        alts = sorted({r"[ \t]+".join(re.escape(w) for w in x.split()) for x in labels if x.strip()},
                      key=len, reverse=True)
        _FEEL_RX.append(re.compile(
            r"(?im)^([ \t\x22\u201c']*)(?:(?:in|feeling)[ \t]+)?(?:%s)"
            r"(?:[ \t]*\((?:mildly|plainly|hard)\)|,[ \t]*(?:mildly|plainly|hard))?"
            r"[ \t]*(?::|[ \t][-\u2013\u2014])[ \t]*" % "|".join(alts)))
    return _FEEL_RX[0]


def strip_scaffold(text, kit=None):
    """`text` with every echoed prompt header cut to the end of its paragraph,
    and every echoed row label cut with its own direction words."""
    kit = kit if kit is not None else scaffold_kit()
    sec, row, tails = _scaffold_rx(kit)
    s = str(text or "")
    cut = False
    for _guard in range(64):
        ms = [m for m in ((sec.search(s) if sec is not None else None), row.search(s)) if m]
        if not ms:
            break
        m = min(ms, key=lambda x: x.start())
        if m.re is sec:
            end = _PARAGRAPH_END.search(s, m.end())
            s = s[:m.start()] + (s[end.start():] if end else "")
        else:
            stop = m.end()
            for rx in tails.get(_row_label_of(m.group(1), kit[1])) or []:
                t = rx.match(s, stop)
                if t:
                    stop = t.end()
                    break
            s = s[:m.start()] + (" " if m.start() and not s[m.start() - 1].isspace() else "") + s[stop:].lstrip(" \t")
        cut = True
    _fs = _feel_prefix_rx().sub(lambda m: m.group(1), s)                      # [s3-direction] the label goes
    if _fs != s:
        s = re.sub(r"(?m)^([ \t\x22\u201c']*)([a-z])", lambda m: m.group(1) + m.group(2).upper(), _fs)
        cut = True
    if cut:
        # the row number that rode in with it is not a word either
        s = re.sub(r"(?m)^[ \t]*\d{1,3}[.)]?[ \t]*$", "", s)
    return s.strip() if cut else s


# --- [s3-echo] a running-order direction said as dialogue never airs --------------
#
# 2026-09-28, AIRED (line cb38bcc8, a banter round): "I can't believe it and says so,
# and widens it out to the bigger picture." - its sheet's row read "... feeling
# repulsion (plainly) about it: cannot believe it and says so, and widens it out to
# the bigger picture.", an RS2 and an FL2 row's own words. The beat writer's check
# (#1462) and the single line's (s3-line-fix) read a row's FIRST clause only
# ("answers what Skip just said (...") and neither saw it. Here a direction is read
# at the row grammar's joints (": ", "; then ", ", and ", " - ", "(...)", "[...]",
# "while doing it,"), the words meant to be said left out (a quoted passage, "exact
# words", the operator's directive); a clause of ECHO_MIN_WORDS words or more inside
# a line - contractions folded, a stumble read once - is the direction said aloud,
# and so is a row's own feeling read out as one ("In distaste, plainly: ..."). An
# item keeps its own commas: "tells them flatly that no, bro, that isn't gonna work"
# is one direction, and "No, bro, that isn't gonna work." is that direction
# PERFORMED, not said. find: direction_echo(); the validator flags it on every
# written turn; the runtime cuts a turn that still carries one before the bind.
ECHO_MIN_WORDS = 4
ECHO_MIN_CHARS = 16
_ECHO_ROW = re.compile(r"(?m)^\s*\d+\s+[A-ES]\s+[-\u2013\u2014]\s*(.+?)\s*$")
_ECHO_QUOTED = re.compile(r'"(?:[^"\\\n]|\\.)*"|\u201c[^\u201d\n]*\u201d')
_ECHO_DIRECTIVE = re.compile(r"THE OPERATOR['\u2019]S DIRECTIVE FOR [^:\n]{0,60}:.*?(?=\.\s+[A-Z]|\.?\s*$)", re.S)
_ECHO_PAREN = re.compile(r"\(([^()]*)\)")
_ECHO_JOINT = re.compile(r"\s*(?:[:;]\s+(?:then\s+|and\s+)?|\s[-\u2013\u2014]+\s|\u2014|(?<=[a-z0-9])\.\s+|[\[\]]"
                         r"|,\s+(?:and|then)\s+|,\s+(?=(?:feeling|in|while)\b)|\bwhile doing it,\s*)\s*", re.I)
_ECHO_FEEL = re.compile(r"\b(?:in|feeling)\s+([a-z]+)\s*[(,]\s*(mildly|plainly|hard)\b", re.I)
_ECHO_FOLD = ((re.compile(r"\bcan['\u2019]?t\b|\bcan not\b"), "cannot"), (re.compile(r"\bwon['\u2019]t\b"), "will not"),
              (re.compile(r"n['\u2019]t\b"), " not"), (re.compile(r"['\u2019]re\b"), " are"),
              (re.compile(r"['\u2019]ve\b"), " have"), (re.compile(r"['\u2019]ll\b"), " will"),
              (re.compile(r"\bi['\u2019]m\b"), "i am"),
              (re.compile(r"\b(it|that|what|there|here|he|she|who)['\u2019]s\b"), r"\1 is"),
              (re.compile(r"['\u2019]"), ""))
_ECHO_FILLERS = frozenset(("uh", "um", "er", "erm", "uhh", "umm", "hmm", "ah", "mm"))
# a clause holding a label in capitals ("BACK TO THE MUSIC", "HERE SKIP IS OPENLY
# SHOCKED") is the scaffold's to cut, and its words are often the ones performed
# ("Back to the music."); a short clause that only names a thing ("the next story
# off the page") is how a line may well begin - neither is a direction's echo
_ECHO_CAPS = re.compile(r"\b[A-Z][A-Z'\u2019]+(?:[ \t]+[A-Z][A-Z'\u2019]+)+\b")
_ECHO_NAMING = frozenset(("the", "a", "an", "one", "this", "that", "these", "those", "his", "her", "their", "its",
                          "some"))
_ECHO_KITS = {}


def _echo_tokens(text):
    """The words of `text` as the matcher compares them: contractions folded, the
    fillers and a restart or a doubled word ("I- I know", "So what I- So what I
    mean") read once, so a stumble dropped into a line cannot hide an echo."""
    s = str(text or "").casefold()
    for rx, sub in _ECHO_FOLD:
        s = rx.sub(sub, s)
    out = []
    for tok in re.findall(r"[a-z0-9]+", s):
        if tok in _ECHO_FILLERS:
            continue
        out.append(tok)
        for n in (3, 2, 1):
            if len(out) >= 2 * n and out[-n:] == out[-2 * n:-n]:
                del out[-n:]
                break
    return out


def direction_kit(*sources):
    """(phrases, feelings): the directions in `sources` as the matcher reads them.
    A source is running-order text - a whole sheet (its numbered rows) or one
    row's work - or a plain direction. Longest phrase first."""
    key = tuple(re.sub(r"[\ue000-\uf8ff]", " ", str(s or "")) for s in sources)
    got = _ECHO_KITS.get(key)
    if got is not None:
        return got
    phrases, feels = set(), set()
    for src in key:
        for row in (_ECHO_ROW.findall(src) or ([src] if src.strip() else [])):
            row = _ECHO_DIRECTIVE.sub(" ", _ECHO_QUOTED.sub(" ", row))
            feels.update((m.group(1).lower(), m.group(2).lower()) for m in _ECHO_FEEL.finditer(row))
            for piece in [_ECHO_PAREN.sub(" ", row)] + _ECHO_PAREN.findall(row):
                for clause in _ECHO_JOINT.split(piece):
                    if _ECHO_CAPS.search(clause):
                        continue
                    toks = _echo_tokens(clause)
                    phrase = " ".join(toks)
                    if (len(toks) >= ECHO_MIN_WORDS and len(phrase) >= ECHO_MIN_CHARS
                            and not (toks[0] in _ECHO_NAMING and len(toks) < 7)):
                        phrases.add(phrase)
    got = (tuple(sorted(phrases, key=lambda p: (-len(p), p))), tuple(sorted(feels)))
    if len(_ECHO_KITS) > 64:
        _ECHO_KITS.clear()
    _ECHO_KITS[key] = got
    return got


def conv_direction_kit(conv):
    """The directions a conversation's writer was handed: the sheet it was given,
    the rows as they stand now (Mode B writes the rest again) and the tempers."""
    sources = [str((conv.get("plan") or {}).get("sheet") or "")]
    for t in conv.get("turns") or []:
        try:
            sources.append("%2d  %s  - %s" % (t["index"] + 1, t["speaker"], _row_work(t, conv)))
        except Exception:  # noqa: BLE001 - a row that cannot be rendered has no words to echo
            pass
    sources += [str((x or {}).get("text") or "") for x in (conv.get("tempers") or {}).values()]
    return direction_kit(*sources)


def direction_echo(text, kit):
    """The direction `text` says aloud, or "": one of the kit's phrases inside its
    words, or a row's own feeling read out as one ("In distaste, plainly:"). `kit`
    is a direction_kit(), or running-order text to make one from."""
    if not (isinstance(kit, tuple) and len(kit) == 2 and isinstance(kit[0], tuple)):
        kit = direction_kit(kit)
    phrases, feels = kit
    said = " %s " % " ".join(_echo_tokens(text))
    if len(said) <= 2:
        return ""
    for phrase in phrases:
        if " %s " % phrase in said:
            return phrase
    low = str(text or "").casefold()
    for emo, inten in feels:
        if re.search(r"(?:^|[.!?:;\"\u201c\[(]\s*|\s[-\u2013\u2014]\s*)(?:say it\s+)?in\s+%s\s*[,(]\s*%s\b"
                     % (re.escape(emo), inten), low):
            return "in %s, %s" % (emo, inten)
    return ""


def _tempers_line(conv):
    tempers = conv.get("tempers") or {}
    if not tempers:
        return ""
    names = {p["actor_id"]: p.get("name") or p["actor_id"] for p in conv["participants"]}
    parts = ["%s (%s) is %s" % (seat, names.get(seat, seat), t.get("text")) for seat, t in sorted(tempers.items())]
    return ("\n" + TEMPERS_LABEL + " (rolled): " + "; ".join(parts) + ". They colour the phrasing, the pacing and what "
            "each of them chooses to react to, underneath each turn's own feeling. Never named out loud.")


def _prompt_needle(text):
    return " ".join(str(text or "").lower().split())[:48].rstrip(" .,;:")


def prompt_mark(conv, rows):
    """[prompt-share] what each roll put into the writer's prompt.

    2026-09-30, the operator: "For any of these pop up windows, the first entry
    should show what this result in the roulette contributed to the system
    prompt." Every roll event on a turn is stamped with the row the writer was
    handed for that turn (`prompt_row`), its own words (`prompt`), and whether
    those words are in the row (`in_prompt`) - a line whose words are fixed, or
    a roll that decides something other than words (a clip, a length), is
    honestly marked as adding nothing."""
    by_turn = {}
    for t, row in zip(conv.get("turns") or [], rows):
        by_turn[t.get("index")] = row
    for ev in conv.get("decision_events") or []:
        row = by_turn.get(ev.get("turn_index"))
        if row is None:
            continue
        sel = ev.setdefault("selected", {})
        words = str(sel.get("prompt") or "")
        if not words and ev.get("family") == "ES":
            words = str(sel.get("text") or "")
        needle = _prompt_needle(words)
        label = _prompt_needle(sel.get("label") or "")
        low = " ".join(str(row).lower().split())
        sel["prompt_row"] = row
        sel["prompt"] = words
        sel["in_prompt"] = bool((needle and needle in low)
                                or (ev.get("family") == "ES" and label and ("feeling " + label) in low))


def render_sheet(conv):
    """The plan as the numbered running order the writer already follows.

    Same row grammar as #1386's banter_beat_sheet ("%2d  X  - work"), so
    the one-call writer, the banked beat chain (_banter_beat_plan) and the
    rewrite all read it without a second parser."""
    rows = ["%2d  %s  - %s" % (t["index"] + 1, t["speaker"], _row_work(t, conv)) for t in conv["turns"]]
    if not rows:
        return ""
    try:
        prompt_mark(conv, rows)                                               # [prompt-share]
    except Exception:  # noqa: BLE001 - a note about the prompt never costs the prompt
        pass
    return ("\n\nTHE RUNNING ORDER OF THIS EXCHANGE. Write exactly these turns, in this order, one line "
            "each, and nothing else. Each row says what the turn does, then gives its DIRECTION FOR THIS "
            "LINE - who speaks, the feeling family, the feeling and how hard. ACT IT OVER THE TOP: the "
            "feeling is in the first words out of their mouth, in every word they pick, in the punctuation "
            "(! and ?! and one word in CAPS when it is big) and in what they are after; a rolled feeling "
            "outranks anyone's usual manner and any calm, dry or measured register above. Perform both, "
            "never name them and never read a direction out:"                  # [s3-direction]
            + _tempers_line(conv) + "\n" + "\n".join(rows) +
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


def es_row(turn):
    """[es-roads] Which ES row shaped a turn - table, category, item, label and
    the intensity it was rolled at - for the air record. None: no feeling rolled."""
    for d in (turn or {}).get("decisions") or []:
        if d.get("family") == "ES" and d.get("item"):
            return {k: d.get(k) for k in ("table", "category", "item", "label", "intensity")
                    if d.get(k) is not None}
    return None


def turn_stamp(conv, t):
    """What rides a script line: the chain that produced it, compactly."""
    acts = [d for d in t["decisions"] if d.get("item")]
    perf = t.get("performance") or {}
    return {**turn_ref(conv, t), "phase": t["phase"], "step": t["step"],
            "es": perf.get("emotion"), "intensity": perf.get("intensity"),
            "acts": [{"family": d["family"], "id": d["item"], "label": d.get("label")} for d in acts
                     if d["family"] != "ES"],
            "perf": {"dims": perf.get("dims") or {}, "pace": perf.get("pace"),
                     "pause_style": perf.get("pause_style"),
                     **({"voice": perf["voice"]} if perf.get("voice") is not None else {}),   # [s3-es-voice]
                     **({"row": es_row(t)} if es_row(t) else {})},   # [es-roads] which row, how hard
            "speakerbox": [sb["mode"] for sb in t.get("speakerbox") or [] if sb["mode"] != "NONE"],
            "sfx": {k: (t.get("sfx") or {}).get(k) for k in ("play", "placement", "intent", "event_id")},
            # [s3-roads] his node: whether he speaks after this line and how
            "sfxguy": {k: (t.get("sfxguy") or {}).get(k) for k in ("speak", "kind", "order", "event_id")},
            # [s3-rewrite] whether the crystal tint may rhyme this line
            "tint": {k: (t.get("tint") or {}).get(k) for k in ("rhyme", "event_id")},
            # [s3-rounds] what the round's own rolls put on this turn
            "round": {k: True for k in ("shock", "long_roll", "interject", "carry_on", "mention", "track_talk",
                                        "favorite", "directives", "events", "ends_here", "after_end") if t.get(k)}}


# --- [s3-split] THE SPLIT NODE ----------------------------------------------------
#
# The operator, 2026-09-28: "for a message like this that exceeds a certain
# amount of characters, we need to introduce the roulette of a split node,
# which basically allows a particular message to be split and who says it,
# and it rolls a roulette with an R and G deciding between what other person
# in the studio says the rest of the message ... ad spots ... monologues ...
# if the person's about to say something that's going to exceed a minute or
# approach forty-five seconds, then that should be split with another person
# in the studio ... an [IL] "insertion list" table ... to dictate how the
# person who takes over for the long message takes over to finish the
# statement. A long statement or ad read or manager read can have up to 3
# splits with splits being a checkbox we can enable to a particular message
# node."
#
# A node (a step of the banter cycle, a leg of a road) opts in with
# `splits: true` and `max_splits` (1-3); the runtime marks the planned turn
# (turn["split_node"]). Once the words of the read are known - a single line
# after its writer, a speaker-box monologue once its passage is fetched - one
# RULE decides, with no draw: the read's spoken length is its characters over
# the voice's pace; past the threshold it is cut into the fewest parts that
# keep each under it (at most max_splits + 1), at the sentence ends nearest
# an even division - never inside a sentence, and never so near an end that
# a part is a scrap. For each part after the first, two draws: WHO takes over
# (the studio as it is now, never the one reading, nor - on the last part -
# the one who speaks next; the split section's weights) and HOW (the
# Insertion list, IL1: the way they take over and the words they say doing
# it). WHO rolls on seed|split and HOW on seed|split:IL, so no other family's
# dice move; every call's inputs are kept (conv["splits"]) so decision replay
# rolls them again. Each part after the first is a turn of its own, placed
# right after the one it continues, so the Messenger shows it as a message of
# its own and the ledger links its line to it.
FAMILIES = FAMILIES + ("SPLIT", "IL")                                        # [s3-split]
SPLIT_MAX = int(getattr(system3_tables, "SPLIT_MAX_SPLITS", 3))
DEFAULT_SPLIT = {
    # a read longer than this many seconds is split ("exceed a minute or
    # approach forty-five seconds")
    "threshold_seconds": 45.0,
    # characters a second when the voice has no measured pace (the median of
    # 5,541 rendered lines, 2026-09-28)
    "pace": 18.9,
    # the operator's own pace for a voice, by role (dj, cohost, third, drop,
    # manager ...): outranks the pace the station measured
    "paces": {},
    # the most any node may ask for
    "max_splits": SPLIT_MAX,
    # the roulette's weight for each member of the studio, by role
    "who": {"dj": 1.0, "cohost": 1.0, "third": 1.0, "drop": 1.0},
    # someone who already read a part of this read weighs this much again
    "again": 0.5,
    # a cut must leave at least this share of an even part on each side
    "min_share": 0.25,
}


def validate_split(raw):
    """[s3-split] The split section as the desk may save it (raises
    ValueError); keys it does not know are dropped."""
    if not isinstance(raw, dict):
        raise ValueError("the split section is an object")
    out = copy.deepcopy(DEFAULT_SPLIT)

    def number(key, low, high):
        if key not in raw:
            return
        try:
            val = float(raw[key])
        except (TypeError, ValueError):
            raise ValueError("%s must be a number" % key)
        if isinstance(raw[key], bool) or math.isnan(val) or not low <= val <= high:
            raise ValueError("%s must be between %s and %s" % (key, low, high))
        out[key] = round(val, 3)

    number("threshold_seconds", 10, 600)
    number("pace", 5, 40)
    number("again", 0, 1)
    number("min_share", 0, 0.5)
    if "max_splits" in raw:
        n = raw["max_splits"]
        if isinstance(n, bool) or not isinstance(n, (int, float)) or int(n) != n or not 1 <= int(n) <= SPLIT_MAX:
            raise ValueError("max_splits must be a whole number from 1 to %d" % SPLIT_MAX)
        out["max_splits"] = int(n)
    for key, low, high in (("paces", 5, 40), ("who", 0, 10)):
        if key not in raw:
            continue
        got = raw[key]
        if not isinstance(got, dict):
            raise ValueError("%s is an object of role: number" % key)
        clean = {} if key == "paces" else dict(out[key])
        for role, val in got.items():
            role = str(role).strip()
            if not re.fullmatch(r"[a-z0-9_]{1,24}", role):
                raise ValueError("%s: %r is not a role (dj, cohost, third, drop, manager ...)" % (key, role))
            try:
                v = float(val)
            except (TypeError, ValueError):
                raise ValueError("%s.%s must be a number" % (key, role))
            if isinstance(val, bool) or math.isnan(v) or not low <= v <= high:
                raise ValueError("%s.%s must be between %s and %s" % (key, role, low, high))
            clean[role] = round(v, 3)
        out[key] = clean
    return out


def split_config(config):
    """[s3-split] The split section in force: the config's own, else the
    defaults (a config saved before [s3-split] has none)."""
    raw = config.get("split") if isinstance(config, dict) else None
    if isinstance(raw, dict):
        try:
            return validate_split(raw)
        except ValueError:
            pass
    return copy.deepcopy(DEFAULT_SPLIT)


def split_node(node):
    """[s3-split] {"max": n} when a step or leg has its splits box ticked."""
    if not isinstance(node, dict) or node.get("splits") not in (True, 1):
        return None
    try:
        n = int(node.get("max_splits") or SPLIT_MAX)
    except (TypeError, ValueError):
        n = SPLIT_MAX
    return {"max": max(1, min(SPLIT_MAX, n))}


# a sentence ends at . ! ? or an ellipsis, with any closing quote or bracket,
# followed by a space - never at a dash (an interruption is mid-sentence),
# and never at the stop after a title or a lone initial ("Mr. Pine", "a.m.")
_SPLIT_END = re.compile(r"[.!?…][\"”’')\]]*(?=\s)")
_SPLIT_NOT_END = re.compile(r"(?:^|\s)(?:mr|mrs|ms|dr|st|jr|sr|vs|mt|ft|no)\.$|(?:^|[\s.])[a-z]\.$", re.I)


def sentence_ends(text):
    """Offsets just past each sentence end inside `text` (its own end is not a cut)."""
    out = []
    for m in _SPLIT_END.finditer(text):
        end = m.end()
        if not 0 < end < len(text):
            continue
        if text[m.start()] == "." and _SPLIT_NOT_END.search(text[max(0, m.start() - 4):m.start() + 1]):
            continue
        out.append(end)
    return out


def split_cuts(text, parts, min_share=0.25, floor=None):
    """[s3-split] Where a read is cut into `parts`: at the sentence ends
    nearest each even division, in order - never inside a sentence, so a
    sentence longer than a part stays whole. A cut that would leave less than
    `floor` characters (default: `min_share` of an even part) on either side
    is not made. May return fewer than parts - 1 cuts (then the read has
    fewer parts)."""
    size = len(text)
    if parts < 2 or size <= 0:
        return []
    ends = sentence_ends(text)
    even = size / float(parts)
    floor = even * max(0.0, float(min_share)) if floor is None else float(floor)
    cuts, prev = [], 0
    for k in range(1, parts):
        target = even * k
        options = [e for e in ends if e > prev and e - prev >= floor and size - e >= floor]
        if not options:
            break
        best = min(options, key=lambda e: (abs(e - target), e))
        cuts.append(best)
        prev = best
    return cuts


def _split_pieces(words, cuts):
    bounds = [0] + list(cuts) + [len(words)]
    return [p for p in (words[bounds[i]:bounds[i + 1]].strip() for i in range(len(bounds) - 1)) if p]


def split_rule(text, pace, threshold, max_splits, min_share=0.25):
    """[s3-split] The rule alone - no draw: {words, seconds, want, cuts}.
    Under (or at) the threshold a read is never split. Over it: the fewest
    parts that keep every part under the threshold, cut at the sentence ends
    nearest an even division, at most max_splits + 1 parts. When no count
    can keep every part under it (a sentence longer than a part stays
    whole), the count whose longest part is the shortest - the fewer parts
    on a tie. No cut leaves a scrap: min_share of the first even part."""
    words = " ".join(str(text or "").split())
    pace = float(pace or 0) or DEFAULT_SPLIT["pace"]
    threshold = float(threshold)
    seconds = len(words) / pace
    if seconds <= threshold:
        return {"words": words, "seconds": seconds, "want": 1, "cuts": []}
    most = max(2, int(max_splits) + 1)
    first = max(2, min(most, int(math.ceil(seconds / threshold))))
    floor = len(words) / float(first) * max(0.0, float(min_share))
    best = None
    for want in range(first, most + 1):
        cuts = split_cuts(words, want, min_share, floor=floor)
        if not cuts:
            continue
        longest = max(len(p) for p in _split_pieces(words, cuts)) / pace
        if best is None or longest < best[0] - 1e-9:
            best = (longest, want, cuts)
        if longest <= threshold:
            break
    if best is None:
        return {"words": words, "seconds": seconds, "want": first, "cuts": []}
    return {"words": words, "seconds": seconds, "want": best[1], "cuts": list(best[2])}


def _il_words(text, prev_name, name):
    out = " ".join(str(text or "").split())
    return out.replace("{prev}", prev_name or "them").replace("{name}", name or "")


def _il_direction(config, spec):
    """The delivery the IL category asks for (its `direction`), if it has one."""
    if not spec:
        return ""
    if spec.get("direction"):
        return str(spec["direction"])
    for table in config.get("tables") or []:
        if table.get("id") != spec.get("table"):
            continue
        for cat in table.get("categories") or []:
            if cat.get("id") == spec.get("category"):
                return str(cat.get("direction") or "")
    return ""


def _split_participant(conv, person):
    """The seat taking over, as a participant, if the conversation had none."""
    seat = str(person.get("seat") or "")
    if not seat or participant(conv, seat):
        return
    conv["participants"].append({
        "actor_id": seat, "role": str(person.get("who") or ""), "name": str(person.get("name") or seat),
        "position": 0.0, "emotion": {"table": "", "category": "", "id": "", "label": "level", "intensity": 0.0,
                                     "source": "initial", "dims": {d: 0.0 for d in EMOTION_DIMS}},
        "intensity": 0.0, "energy": 0.5, "recent_actions": [], "callbacks": []})


def split_turn(conv, config, turn, text, candidates, speaker_who="", pace=None, pace_why="",
               next_who="", recent=None, mode="line", node=None, prepared=False, replaying=False):
    """[s3-split] The SPLIT node on one read. `text` is the read (a written
    line, or a monologue's passage when mode is "passage"); `candidates` the
    studio now ([{who, seat, name, voice}]); `speaker_who` the one reading it;
    `next_who` the one who speaks straight after it (a round: the last part is
    never theirs). Records the RULE (one SPLIT event on the turn, no draw)
    and, when it splits, for each part after the first a WHO draw (SPLIT) and
    a HOW draw (IL). Each later part becomes a turn of its own, right after
    `turn` (the turns after it are renumbered; their ids stand). Line mode:
    the turn's words become part 1 and each new turn's words are its lead-in
    and its part. Passage mode: the parts are recorded on the turns
    (split.passage) for the running order. Returns {split, parts, why,
    event_id, whole}; nothing is recorded when the node does not split."""
    node = node or (turn.get("split_node") if isinstance(turn, dict) else None)
    if not isinstance(node, dict) or not node.get("max"):
        return {"split": False, "why": "this node does not split (its splits box is not ticked)"}
    cfg = split_config(config)
    max_splits = max(1, min(int(node.get("max") or SPLIT_MAX), int(cfg["max_splits"])))
    threshold = float(cfg["threshold_seconds"])
    who0 = str(speaker_who or "")
    if not pace or float(pace) <= 0:
        pace = float(cfg["paces"].get(who0) or cfg["pace"])
        pace_why = pace_why or ("the split section's pace for %s" % who0 if who0 in cfg["paces"] else "the default pace")
    pace = float(pace)
    rule = split_rule(text, pace, threshold, max_splits, cfg.get("min_share", 0.25))
    words, seconds = rule["words"], rule["seconds"]
    src_seat = str(turn.get("speaker") or "")
    src_name = str(turn.get("name") or src_seat or who0)
    people, seen_who = [], set()
    for c in candidates or []:
        w = str((c or {}).get("who") or "") if isinstance(c, dict) else ""
        if w and w not in seen_who:
            seen_who.add(w)
            people.append(dict(c))
    if not replaying:
        conv.setdefault("splits", []).append({
            "turn_id": turn["turn_id"], "text": words, "candidates": people, "speaker_who": who0,
            "pace": round(pace, 3), "pace_why": str(pace_why or ""), "next_who": str(next_who or ""),
            "recent": sorted(str(x) for x in (recent or ())), "mode": mode, "node": dict(node),
            "prepared": bool(prepared), "at": time.time()})
    facts = {"chars": len(words), "pace": round(pace, 2), "pace_why": str(pace_why or ""),
             "seconds": round(seconds, 1), "threshold": threshold, "max_splits": max_splits,
             "wanted": rule["want"], "sentences": len(sentence_ends(words)) + (1 if words else 0),
             "mode": mode, "reader": who0, "prepared": bool(prepared)}
    pieces, why = [], ""
    if rule["want"] <= 1:
        why = ("%.0f s at %.1f characters a second is not over the %.0f s threshold: read whole"
               % (seconds, pace, threshold))
    elif not rule["cuts"]:
        why = ("%.0f s is over the %.0f s threshold, but no sentence ends far enough from both ends to cut at "
               "- a sentence is never split: read whole" % (seconds, threshold))
    else:
        pieces = _split_pieces(words, rule["cuts"])
    rule_text = ("%d characters at %.1f a second (%s) is %.0f s against the %.0f s threshold; this node may split "
                 "%d time%s" % (len(words), pace, pace_why or "pace", seconds, threshold, max_splits,
                                "" if max_splits == 1 else "s"))
    if prepared and pieces:
        # a whole take made ahead is not a reason to read it whole: the parts are voiced now
        rule_text += "; a whole take had been made ahead - the parts are voiced now, each in its reader's voice"
    before = _snapshot(conv, src_seat)
    rule_ev = _event(conv, {"turn_id": turn["turn_id"], "turn_index": turn["index"], "speaker": src_seat}, "SPLIT",
                     [{"stage": "rule", "draw": None, "rule": rule_text, "selected": 1, "cuts": list(rule["cuts"])}],
                     {"id": "WHOLE", "label": "read whole", "parts": 1},
                     before, meta=dict(facts, why=why or "", rule=rule_text))
    rule_ev["state_after"] = before
    turn["decisions"].append({"family": "SPLIT", "event_id": rule_ev["event_id"], "item": "WHOLE",
                              "label": "read whole"})
    if len(pieces) < 2:
        rule_ev["selected"]["label"] = "read whole: " + why
        turn["split"] = {"part": 1, "of": 1, "event_id": rule_ev["event_id"], "why": why}
        return {"split": False, "why": why, "event_id": rule_ev["event_id"], "whole": words}
    stream = DrawStream(str(conv["seed"]) + "|split", int(conv.get("split_draws") or 0))
    il_stream = DrawStream(str(conv["seed"]) + "|split:IL", int(conv.get("il_draws") or 0))
    names = {str(c.get("who")): str(c.get("name") or c.get("who")) for c in people}
    readers = [who0]
    made = [pieces[0]]
    parts_out = [{"part": 1, "turn_id": turn["turn_id"], "who": who0, "seat": src_seat, "name": src_name,
                  "voice": "", "lead_in": "", "body": pieces[0], "event_id": rule_ev["event_id"]}]
    stopped = ""
    used_il = set()
    at = conv["turns"].index(turn)
    perf = copy.deepcopy(turn.get("performance")) if turn.get("performance") else None
    for k in range(1, len(pieces)):
        prev_who = readers[-1]
        last = k == len(pieces) - 1
        rows, excl = [], []
        for c in people:
            w = str(c["who"])
            label = "%s (%s)" % (c.get("name") or w, c.get("seat") or w)
            if w == prev_who:
                excl.append({"id": w, "label": label, "why": "reading now - a part never goes back to the one reading it"})
                continue
            if last and next_who and w == str(next_who):
                excl.append({"id": w, "label": label, "why": "speaks the very next line - nobody speaks twice in a row"})
                continue
            base = float(cfg["who"].get(w, 1.0))
            weight = base
            reasons = ["the split section's weight for %s: %.2f" % (w, base)]
            if w in readers:
                weight *= float(cfg["again"])
                reasons.append("already read part %d x%.2f" % (readers.index(w) + 1, float(cfg["again"])))
            if weight <= 0:
                excl.append({"id": w, "label": label, "why": "weight 0"})
                continue
            rows.append({"id": w, "label": label, "base": base, "weight": weight, "why": reasons, "c": c})
        if not rows:
            stopped = ("nobody else in the studio could take part %d over (%s), so %s reads on to the end"
                       % (k + 1, "; ".join("%s: %s" % (x["label"], x["why"]) for x in excl) or "nobody else is in",
                          names.get(prev_who) or (src_name if prev_who == who0 else prev_who)))
            made[-1] = (made[-1] + " " + " ".join(pieces[k:])).strip()
            parts_out[-1]["body"] = made[-1]
            break
        draw = stream.next("SPLIT:who%d" % (k + 1))
        i = pick_index([r["weight"] for r in rows], draw["u"])
        c = rows[i]["c"]
        seat, w, name = str(c.get("seat") or c["who"]), str(c["who"]), str(c.get("name") or c["who"])
        prev_name = names.get(prev_who) or (src_name if prev_who == who0 else prev_who)
        tid = "%ss%d" % (turn["turn_id"], k + 1)
        new = {"turn_id": tid, "index": at + k, "speaker": seat, "name": name, "who": w,
               "step": "split", "step_label": "%s takes over" % name,
               "cycle": turn.get("cycle", 0), "phase": turn.get("phase", "OPEN"), "decisions": [], "directions": [],
               "speakerbox": [], "sfx": None, "sfxguy": None, "tint": None, "performance": copy.deepcopy(perf),
               "text": "", "script_index": None, "status": "planned" if mode == "passage" else "generated",
               "cursor_before": turn.get("cursor_before"), "state_before": turn.get("state_before"),
               "state_after": turn.get("state_after"), "split_of": turn["turn_id"],
               "estimated_seconds": round(len(pieces[k]) / pace, 2)}
        for key in ("leg", "place", "protocol"):
            if key in turn:
                new[key] = turn[key]
        conv["turns"].insert(at + k, new)
        for j, t in enumerate(conv["turns"]):
            t["index"] = j
        _split_participant(conv, c)
        who_ev = _event(conv, {"turn_id": tid, "turn_index": new["index"], "speaker": seat}, "SPLIT",
                        [_stage("item", rows, i, draw, excl)],
                        {"id": w, "label": "%s takes over" % name, "who": w, "seat": seat, "name": name,
                         "part": k + 1, "index": i + 1, "of": len(rows)},
                        before, meta={"part": k + 1, "from": prev_who, "rule": "who takes part %d over: the studio "
                                      "but the one reading%s, at the split section's weights"
                                      % (k + 1, " and the next voice" if last and next_who else "")},
                        rng=draw)
        who_ev["state_after"] = before
        # a way in used on this read already weighs a quarter again (as a recent round's does)
        il_ctx = {"conv": conv, "turn_id": tid, "turn_index": new["index"], "speaker": seat,
                  "phase": turn.get("phase") or "OPEN", "prev_keys": set(),
                  "recent_rounds": set(str(x) for x in (recent or ())) | {"IL:%s" % x for x in used_il},
                  "turns_left": 0,
                  "controls": (conv.get("settings") or {}).get("controls") or {}, "availability": {},
                  "personalities": config.get("personalities") or {}, "speaker_emotion_cat": "",
                  "prev_lean": None, "event_emotions": {}}
        spec, il_ev = weighted_decision(conv, config, il_ctx, il_stream, "IL")
        if spec:
            used_il.add(str(spec.get("id")))
        lead = _il_words(spec.get("text"), prev_name, name) if spec else ""
        how = str((spec or {}).get("category_label") or "")
        direction = _il_direction(config, spec)
        new["decisions"] = [{"family": "SPLIT", "event_id": who_ev["event_id"], "item": w,
                             "label": "%s takes over" % name, "u": draw["u"]}]
        if spec:
            new["decisions"].append({"family": "IL", "event_id": il_ev["event_id"], "table": spec["table"],
                                     "category": spec["category"], "item": spec["id"], "label": spec["label"],
                                     "text": lead, "u": (il_ev.get("rng") or {}).get("u")})
            new["directions"].append({"family": "IL", "text": direction or how.lower(), "label": how})
            new["step_label"] = "%s takes over - %s" % (name, how.lower())
        else:
            new["decisions"].append({"family": "IL", "event_id": il_ev["event_id"], "item": None,
                                     "empty": (il_ev.get("meta") or {}).get("empty")})
        new["split"] = {"part": k + 1, "of_turn": turn["turn_id"], "who": w, "from": prev_who,
                        "event_id": who_ev["event_id"], "il_event": il_ev["event_id"], "lead_in": lead,
                        "how": how, "direction": direction}
        new["decision_bundle_id"] = "%s:b%s" % (tid, digest([who_ev["event_id"], il_ev["event_id"]], 8))
        readers.append(w)
        made.append(pieces[k])
        parts_out.append({"part": k + 1, "turn_id": tid, "who": w, "seat": seat, "name": name,
                          "voice": str(c.get("voice") or ""), "lead_in": lead, "body": pieces[k],
                          "how": how, "direction": direction, "event_id": who_ev["event_id"],
                          "il_event": il_ev["event_id"]})
    conv["split_draws"] = stream.n
    conv["il_draws"] = il_stream.n
    n = len(parts_out)
    for p in parts_out:
        p["of"] = n
        p["text"] = ((p["lead_in"] + " " + p["body"]).strip() if p["lead_in"] else p["body"])
    turn["split"] = {"part": 1, "of": n, "event_id": rule_ev["event_id"],
                     "parts": [p["turn_id"] for p in parts_out], "why": stopped}
    for p in parts_out[1:]:
        t = next((x for x in conv["turns"] if x["turn_id"] == p["turn_id"]), None)
        if t is None:
            continue
        t["split"]["of"] = n
        t["estimated_seconds"] = round(len(p["body"]) / pace, 2)
        if mode == "passage":
            t["split"]["passage"] = p["body"]
        else:
            t["text"] = p["text"]
    if mode == "passage":
        turn["split"]["passage"] = made[0]
    else:
        turn["text"] = made[0]
    label = ("split into %d parts: %.0f s at %.1f characters a second is over the %.0f s threshold"
             % (n, seconds, pace, threshold)) if n > 1 else "read whole: " + stopped
    rule_ev["selected"] = {"id": "SPLIT" if n > 1 else "WHOLE", "label": label, "parts": n}
    rule_ev["stages"][0]["selected"] = n
    rule_ev["meta"]["why"] = stopped or rule_ev["meta"].get("why") or ""
    rule_ev["meta"]["parts"] = [len(p["body"]) for p in parts_out]
    for d in turn["decisions"]:
        if d.get("event_id") == rule_ev["event_id"]:
            d["item"], d["label"] = rule_ev["selected"]["id"], label
    return {"split": n > 1, "parts": parts_out, "why": stopped, "event_id": rule_ev["event_id"], "whole": words}


def _replay_split(conv, config, sp):
    """[s3-split] Decision replay: a split decided after the words were
    known, rolled again from the inputs it kept."""
    t = next((x for x in conv["turns"] if x.get("turn_id") == sp.get("turn_id")), None)
    if t is None:
        return
    split_turn(conv, config, t, sp.get("text") or "", sp.get("candidates") or [],
               speaker_who=sp.get("speaker_who") or "", pace=sp.get("pace"), pace_why=sp.get("pace_why") or "",
               next_who=sp.get("next_who") or "", recent=sp.get("recent") or [], mode=sp.get("mode") or "line",
               node=sp.get("node"), prepared=bool(sp.get("prepared")), replaying=True)


def _split_hand_on(turn, conv):
    """[s3-split] The monologue's first reader stops where the next takes over."""
    sp = turn.get("split") or {}
    if sp.get("part") != 1 or int(sp.get("of") or 1) < 2:
        return ""
    nxt = next((t for t in conv["turns"] if t.get("split_of") == turn["turn_id"]), None)
    return (" - and stops there, mid-read: %s takes the passage over on the next line"
            % str((nxt or {}).get("name") or (nxt or {}).get("speaker") or "the next voice"))


def _split_row_work(turn, conv):
    """[s3-split] The running-order row of a part taken over: who it comes
    from, how they take it (IL), the words on the way in, and the part of the
    passage they carry on with, word for word."""
    sp = turn.get("split") or {}
    prev = conv["turns"][turn["index"] - 1] if turn["index"] and turn["index"] - 1 < len(conv["turns"]) else None
    prev_name = str((prev or {}).get("name") or (prev or {}).get("speaker") or "the one reading")
    feel = _feel_words(turn)
    out = "TAKES THE PASSAGE OVER from %s mid-read" % prev_name
    if sp.get("direction") or sp.get("how"):
        out += " - %s" % (sp.get("direction") or str(sp.get("how")).lower())
    if sp.get("lead_in"):
        out += ". Says first, in their own voice: %s" % json.dumps(sp["lead_in"])
    passage = " ".join(str(sp.get("passage") or "").split())
    if passage:
        out += (". Then reads this out word for word as their own words, carrying straight on from where %s "
                "stopped: %s" % (prev_name, json.dumps(passage)))
    if feel:
        out += " - in %s" % feel
    part_of = next((t for t in conv["turns"] if t["turn_id"] == sp.get("of_turn")), None)
    if part_of and (part_of.get("split") or {}).get("of") == sp.get("part"):
        out += ". The passage ends there; the next line answers it"
    return out.rstrip(".") + "."


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
    # [s3-scaffold] [s3-echo] what no written turn may carry - checked on EVERY one, an
    # unplanned turn airs too: a prompt's own header, or a direction said as dialogue
    _heads, _dirs = scaffold_kit(None, conv), conv_direction_kit(conv)
    _said = {}
    scaffolds = echoes = 0
    for _i, (_m, _words) in enumerate(final_turns):
        _got = []
        _lab = find_scaffold(_words, _heads)
        if _lab:
            scaffolds += 1
            _got.append({"what": "scaffold:%s" % _lab, "result": "violated",
                         "how": "a prompt header echoed into the spoken words"})
        _dir = direction_echo(_words, _dirs)
        if _dir:
            echoes += 1
            _got.append({"what": "direction:%s" % _dir[:80], "result": "violated",
                         "how": "a running-order direction said as dialogue"})
        if _got:
            _said[_i] = _got
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
        row["checks"].extend(_said.get(at) or [])                              # [s3-scaffold] [s3-echo]
        if _es_line(t) and _speaks_direction(text, _es_line(t)):              # [s3-es-dir]
            row["checks"].append({"what": "echo:feeling direction", "result": "violated",
                                  "how": "the line says its row's feeling direction aloud"})
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
    _held = set(mapping.values())                                             # [s3-scaffold] [s3-echo]
    unplanned = [{"script_index": i, "checks": c} for i, c in sorted(_said.items()) if i not in _held]
    violations += sum(len(u["checks"]) for u in unplanned)
    echo = _echoes(final_turns)
    loop = len(echo) >= 3 and len(echo) >= 0.25 * max(1, len(final_turns))
    if loop:
        violations += 1
    score = (0.4 * seat_order + 0.2 * min(1.0, turn_ratio) +
             0.3 * (act_rate if act_rate is not None else 0.5) +
             0.1 * (1.0 if closing_ok in (True, None) else 0.0))
    score -= min(0.3, 0.05 * violations)
    verdict = "compliant" if score >= 0.7 else "partial" if score >= 0.45 else "non_compliant"
    if loop or fav_copies or scaffolds or echoes:
        verdict = "non_compliant"          # an echo loop is not a conversation at any score;
                                           # [s3-cast] a favourite repeated is not its spirit;
                                           # [s3-scaffold] [s3-echo] nor a prompt's header or a
                                           # row's direction said out loud
    return {"at": time.time(), "method": "deterministic/lexical", "planned": n_plan,
            "written": len(final_turns), "matched": matched,
            "turn_ratio": round(turn_ratio, 3), "seat_order": round(seat_order, 3),
            "acts": {"met": met, "missed": missed, "unchecked": unchecked,
                     "rate": None if act_rate is None else round(act_rate, 3)},
            "closing": closing_ok, "violations": violations, "score": round(score, 3),
            "verdict": verdict, "repair_wanted": bool(seat_order < 0.5 or turn_ratio < 0.5 or loop or fav_copies
                                                      or scaffolds or echoes),
            "scaffold": scaffolds, "direction_echo": echoes, "unplanned": unplanned,   # [s3-scaffold] [s3-echo]
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
            t["text"] = str(final_turns[at][1] or "")                   # [s3-split] whole, never cut mid-word
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


# --- [s3-turnchain] every message answers the one before it; no copy airs ---------
#
# The operator, 2026-09-28: "the dialogue is duplicate ... they're not responding
# to each other with this dialogue" and "in my eyes every message is rolling dice
# against the next message." Measured that morning (data/system3.sqlite3): 7.4% of
# the turns written in 24 h copied an earlier turn of their own round; a request-
# line call (cc672e24) aired its caller's subject sentence four times and the
# host's question five. The writer (gemma4:e2b) had run past the running order and
# looped until its token budget ran out - 43 turns for 15 rows - and validate()
# saw the loop (non_compliant, repair_wanted) and nothing stopped it airing.
#
# THE GATE reads a written round turn by turn, in order, after the station's own
# cleaning, where its lines are bound to the plan's turns. A turn that copies a
# line already said in the round, reads the round's subject, theme or a topic row
# back word for word, reads a speaker-box passage off the turn whose door placed
# it, or is empty once cleaned is CAUGHT. A caught turn the plan rolled is written
# again - once or twice, one line at a time, told the line it answers and its own
# dice ("answer <previous line> by <RS>, <ES>, <FL/IRS>"; "your draft repeated
# <X>; write a new line"). Still a copy - or a turn the writer added that no node
# rolled - and it is DROPPED with the round's shape kept: nobody speaks twice in a
# row where a drop would make them (the turn that answered the dropped line goes
# with it), turns written past a closing leg go, and a protocol leg (a call's or a
# segment's open and close legs) is never dropped out from under its round: the
# round is held instead. Nothing here draws a number. Every catch, re-write and
# drop is an observation on its node (family GATE).

GATE_FAMILY = "GATE"
GATE_SIMILAR = 0.9          # difflib ratio: this close to a line already said is that line again
GATE_ECHO_RUN = 12          # ...or this many of its words in a row (a question that repeats the
                            # caller's detail back - the call's ask legs - quotes about ten)
GATE_ECHO_SHARE = 0.6       # ...or a run of six or more that is this much of the turn
GATE_SHORT = 12             # two short lines of nearly the same words are one line
GATE_MIN_WORDS = 3          # shorter than this, a repeat is an interjection ("Yeah.")
GATE_SOURCE_RUN = 14        # words in a row out of the subject or a topic row: read out
GATE_SOURCE_MIN = 8         # ...or a run of eight that is most of the turn or of the row
GATE_SOURCE_SHARE = 0.6
GATE_PASSAGE_RUN = 8        # words in a row out of a speaker-box passage, off its door
GATE_REWRITES = 2           # new tries a caught planned turn gets before it is dropped
GATE_VISITS = 10            # re-write visits one round may spend; protocol legs are served first
GATE_LIVE_REWRITES = 1      # [live-legs] a LIVE round re-writes its protocol legs only, once each
GATE_LIVE_VISITS = 3        # [live-legs] ...and spends at most this many visits doing it
GATE_CONTEXT = 6            # lines of the conversation so far a re-write is shown
GATE_FIXED_PLACES = ("open", "close")
_GATE_ROW_TAIL = re.compile(r"\s+\d{1,3}[.)]?\s*$")


def gate_words(text):
    """A line's words as the gate compares them: lower case, with a running-order
    row number left on its end ("... in here. 11") cut."""
    s = _GATE_ROW_TAIL.sub("", str(text or "").replace("’", "'"))
    return re.findall(r"[a-z0-9']+", s.lower())


def _gate_run(a, b):
    """The longest run of words `a` and `b` say in the same order."""
    if not a or not b:
        return 0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b)).size


def _gate_excerpt(text, cap=160):
    s = " ".join(str(text or "").split())
    return s if len(s) <= cap else s[:cap - 1].rstrip() + "…"


def gate_copies(a, b):
    """How the words `a` (a turn) copy the words `b` (a line already said), or ""."""
    if len(a) < GATE_MIN_WORDS or len(b) < GATE_MIN_WORDS:
        return ""
    ka, kb = " ".join(a), " ".join(b)
    if ka == kb:
        return "word for word"
    sm = difflib.SequenceMatcher(None, ka, kb, autojunk=False)
    if sm.real_quick_ratio() >= GATE_SIMILAR and sm.quick_ratio() >= GATE_SIMILAR and sm.ratio() >= GATE_SIMILAR:
        return "nearly word for word"
    run = _gate_run(a, b)
    if run >= GATE_ECHO_RUN:
        return "%d of its words in a row" % run
    if run >= 6 and run >= GATE_ECHO_SHARE * len(a):
        return "%d of this line's %d words in a row" % (run, len(a))
    if len(a) <= GATE_SHORT and len(b) <= GATE_SHORT:
        sa, sb = set(a), set(b)
        if len(sa & sb) >= 0.8 * max(len(sa), len(sb)):
            return "the same words"
    return ""


def gate_sources(conv):
    """What a turn may not read back word for word, and the planned turns whose
    door places it there: [{kind, label, text, words, door}]. `kind` is subject
    (the caller's subject - the #1249 theme - the round's subject and angle, the
    operator's exchange), topic (a topics-board row, a new subject) or passage
    (the opening passage, the call's speaker-box passage, a passage a turn's mark
    carries)."""
    inputs = conv.get("inputs") or {}
    call = inputs.get("call") if isinstance(inputs.get("call"), dict) else {}
    subject = conv.get("subject") or {}
    out, seen = [], set()

    def add(kind, label, text, door=()):
        words = gate_words(text)
        key = " ".join(words)
        if len(words) < GATE_SOURCE_MIN or key in seen:
            return
        seen.add(key)
        out.append({"kind": kind, "label": label, "text": _gate_excerpt(text, 240), "words": words,
                    "door": sorted({int(i) for i in door})})

    seeded = [0] if subject.get("seeded") else []
    # the round's own subject is stated where the plan opens on it - the caller telling
    # why they rang (the #1249 contract wants it said), the memo read out, the lead off
    # the wire, the painting named: a legs road's opening legs. Anywhere else, and a
    # second time anywhere, it is read back.
    opening = [int(t.get("index") or 0) for t in conv.get("turns") or [] if t.get("place") == "open"]
    add("passage", "the opening passage", inputs.get("seed_text"), seeded)
    add("subject", "the caller's subject", call.get("topic"), opening)
    add("passage", "the call's speaker-box passage", call.get("speakerbox"))
    exchange = subject.get("exchange") or {}
    add("subject", "the operator's opening line", exchange.get("opener"), [0])
    add("subject", "the operator's answer line", exchange.get("reply"), [1])
    add("subject", "the round's subject", subject.get("topic"), seeded + opening)
    add("subject", "the round's angle", subject.get("active_angle"), seeded + opening)
    for t in conv.get("turns") or []:
        i = int(t.get("index") or 0)
        for sb in t.get("speakerbox") or []:
            mat = sb.get("material") or {}
            if mat.get("text"):
                add("passage", "the passage marked on turn %d" % (i + 1), mat["text"],
                    [i] if sb.get("mode") in ("PREPEND", "APPEND", "FULL_SWATH") else [])
        mat = t.get("topic_material") or {}
        if mat.get("text"):
            add("topic", "the subject brought up on turn %d" % (i + 1), mat["text"])
        bank = t.get("bank_topic") or {}
        if bank.get("text"):
            add("topic", "the topics-board row on turn %d" % (i + 1), bank["text"], [i] if bank.get("reply") else [])
        if t.get("topic_override"):
            add("topic", "the subject handed to turn %d" % (i + 1), t["topic_override"])
    plan = conv.get("topic_plan") or {}
    if plan.get("text"):
        add("topic", "the topics-board row", plan["text"],
            [int(plan.get("turn_index") or 0)] if plan.get("reply") else [])
    return out


def gate_check(conv, index, text, earlier=(), sources=None, spoken=None):
    """Why a written turn is not a new line, or None. `index` is the planned turn
    it stands for (None: a turn the writer added), `earlier` the lines already
    said in this round as (label, text), `spoken` the words the station will say
    (the turn after its cleaning; the text itself when not given)."""
    words = gate_words(text if spoken is None else spoken)
    if not words:
        return {"rule": "empty", "what": "nothing", "text": "", "how": "",
                "why": "nothing is left of it once it is cleaned"}
    for label, other in earlier or ():
        how = gate_copies(words, gate_words(other))
        if how:
            return {"rule": "copy", "what": label, "text": _gate_excerpt(other), "how": how,
                    "why": "it repeats %s - %s" % (label, how)}
    for src in (gate_sources(conv) if sources is None else sources):
        if index is not None and index in src["door"]:
            continue
        run = _gate_run(words, src["words"])
        if src["kind"] == "passage":
            hit = run >= GATE_PASSAGE_RUN
        else:
            hit = run >= GATE_SOURCE_RUN or (run >= GATE_SOURCE_MIN and (
                run >= GATE_SOURCE_SHARE * len(words) or run >= GATE_SOURCE_SHARE * len(src["words"])))
        if hit:
            return {"rule": src["kind"], "what": src["label"], "text": src["text"],
                    "how": "%d of its words in a row" % run,
                    "why": "it reads %s back word for word (%d words in a row)%s" % (
                        src["label"], run, ", off the turn whose door places it" if src["kind"] == "passage" else "")}
    return None


def gate_map(conv, markers):
    """Planned turn -> index in the written script, IN ORDER: the writer was told
    to write the rows in order, one line each, so planned turn k is the first line
    of its seat after planned turn k-1's. A seat-sequence match (align) can pair
    the plan with a looped second pass and leave the first unmatched; this does
    not. A planned turn whose seat never comes again is not written."""
    out, j = {}, 0
    for t in conv.get("turns") or []:
        k = j
        while k < len(markers) and markers[k] != t["speaker"]:
            k += 1
        if k < len(markers):
            out[t["index"]] = k
            j = k + 1
    return out


def gate_dice(conv, index):
    """The dice a planned turn rolled, as its re-write is told them."""
    t = conv["turns"][index]
    perf = t.get("performance") or {}
    es = next((d for d in t.get("decisions") or [] if d.get("family") == "ES" and d.get("item")), {})
    out = {"turn": index, "seat": t.get("speaker"), "name": str(t.get("name") or t.get("speaker") or ""),
           "leg": t.get("leg") or t.get("step"), "place": t.get("place"),
           "es": {"id": es.get("item"), "label": es.get("label") or perf.get("emotion") or "",
                  "strength": _intensity_word(float(perf.get("intensity") or 0)),
                  "direction": str(es.get("direction") or "")},
           "acts": [], "flow": []}
    for x in t.get("directions") or []:
        if x.get("family") in ("RS", "IRS"):
            out["acts"].append({"family": x["family"], "label": str(x.get("label") or ""), "text": str(x.get("text") or "")})
        elif x.get("family") == "FL":
            out["flow"].append({"label": str(x.get("label") or ""), "text": str(x.get("text") or "")})
    return out


def gate_answer(conv, index, previous=None, quote=True):
    """The turn's dice against the line it answers, in one sentence:
    "answer <previous line> by <RS act>, <ES item>, <FL/IRS>"."""
    d = gate_dice(conv, index)
    parts = ["%s (%s %s)" % (a["text"], a["family"], a["label"]) for a in d["acts"] if a["text"]]
    if d["es"]["label"]:
        parts.append("feeling %s, %s (ES %s)" % (d["es"]["label"], d["es"]["strength"], d["es"]["id"] or d["es"]["label"]))
    parts += ["%s (FL %s)" % (f["text"], f["label"]) for f in d["flow"] if f["text"]]
    how = ", ".join(parts) or "in your own words"
    if previous and str(previous[1] or "").strip():
        said = json.dumps(_gate_excerpt(previous[1], 300), ensure_ascii=False) if quote else "line"
        return "answer %s's %s by: %s" % (previous[0], said, how)
    return "open the conversation: %s" % how


def gate_row(conv, index):
    """What the running order told the writer this turn does."""
    t = conv["turns"][index]
    if conv.get("call_structure") or conv.get("road_structure") or t.get("protocol"):
        return (str(t.get("protocol") or "keeps it going.").strip() + _leg_row_add(t)).strip()
    return _row_work(t, conv)


def gate_ask(conv, index, previous, context, catch, tries=()):
    """The one-line re-write prompt for planned turn `index`: the cast, the
    conversation so far, the line it answers and its dice, what its row does,
    and what its draft repeated. Plain text; the station sends it as a writer
    call and reads the first line back."""
    t = conv["turns"][index]
    seat = str(t["speaker"])
    name = str(t.get("name") or seat)
    cast = "; ".join("%s is %s%s" % (p["actor_id"], p.get("name") or p["actor_id"],
                                     (" (%s)" % p["role"]) if p.get("role") else "")
                     for p in conv.get("participants") or [])
    said = ["%s: %s" % (m, _gate_excerpt(x, 400)) for m, x in list(context)[-GATE_CONTEXT:]]
    lines = ["You are writing ONE line of a conversation on the radio: the next thing %s says. %s." % (name, cast),
             "", "THE CONVERSATION SO FAR, in order:"] + (said or ["(nothing has been said yet)"]) + [
             "", "WRITE TURN %d - %s (%s)." % (index + 1, seat, name)]
    if previous and str(previous[1] or "").strip():
        lines.append("THE LINE YOU ANSWER - %s just said: %s" % (
            previous[0], json.dumps(_gate_excerpt(previous[1], 400), ensure_ascii=False)))
    lines.append("YOUR DICE FOR THIS LINE: " + gate_answer(conv, index, previous, quote=False) + ".")
    lines.append("WHAT THIS TURN DOES: " + gate_row(conv, index))
    if catch:
        lines.append("YOUR DRAFT REPEATED %s: %s. Write a NEW line." % (
            str(catch.get("what") or "a line already said").upper(),
            json.dumps(_gate_excerpt(catch.get("text") or catch.get("draft") or "", 240), ensure_ascii=False)))
    for tr in tries or ():
        c = tr.get("catch") or {}
        lines.append("YOUR NEXT TRY REPEATED %s TOO: %s." % (str(c.get("what") or "it").upper(),
                                                             json.dumps(_gate_excerpt(tr.get("text"), 200),
                                                                        ensure_ascii=False)))
    lines += ["Say something nobody has said yet in this conversation. Never read the subject, a topic or a "
              "passage back word for word, and never say these directions out loud.",
              "Output exactly one line and nothing else: %s: <the words>" % seat]
    return "\n".join(lines)


def _gate_name(conv, seat):
    for p in conv.get("participants") or []:
        if p.get("actor_id") == seat:
            return str(p.get("name") or seat)
    return str(((conv.get("inputs") or {}).get("names") or {}).get(seat) or seat)


def _gate_label(conv, row):
    return "%s's line (turn %d)" % (_gate_name(conv, row["seat"]), row["at"] + 1)


def gate_open(conv, turns, spoken=None, rewrites=GATE_REWRITES, visits=GATE_VISITS, legs_only=False):
    """Start the gate over a written round: `turns` [(marker, text)] as the station
    parsed and cleaned them, `spoken` their words as they will be said. Returns
    the run - a plain dict the station drives with gate_next / gate_take and
    closes with gate_close."""
    markers = [str(m or "")[:1].upper() for m, _x in turns]
    mapping = gate_map(conv, markers)
    of = {s: p for p, s in mapping.items()}
    legs = bool(conv.get("call_structure") or conv.get("road_structure"))
    rows = []
    for i, (m, x) in enumerate(turns):
        p = of.get(i)
        t = conv["turns"][p] if p is not None else None
        rows.append({"at": i, "seat": markers[i], "turn": p, "turn_id": t["turn_id"] if t else "",
                     "leg": (t.get("leg") or t.get("step")) if t else "", "place": (t or {}).get("place") or "",
                     "fixed": bool(t is not None and legs and t.get("place") in GATE_FIXED_PLACES),
                     "orig": str(x or ""), "text": str(x or ""),
                     "spoken": (str(spoken[i]) if spoken is not None and i < len(spoken) else None),
                     "state": "open", "catch": None, "tries": [], "why": ""})
    run = {"rows": rows, "cursor": 0, "rewrites": max(0, int(rewrites)), "visits": max(0, int(visits)),
           "spent": 0, "ask": None, "sources": gate_sources(conv), "events": [], "held": "",
           "counts": {"caught": 0, "rewritten": 0, "dropped": 0, "trimmed": 0}, "reserve": set()}
    run["legs_only"] = bool(legs_only)     # [live-legs] only the protocol legs are re-written
    # turns written past the running order's closing leg are not the round's
    last = max(mapping) if mapping else None
    if last is not None and last == len(conv["turns"]) - 1 and conv["turns"][last].get("place") == "close":
        for r in rows[mapping[last] + 1:]:
            r["state"], r["why"] = "dropped", "written past the running order's last turn (%s)" % (
                conv["turns"][last].get("leg") or "the close")
            run["counts"]["trimmed"] += 1
            _gate_event(conv, run, r, "trimmed", why=r["why"])
    # the protocol legs are served first: a dry pass over the draft as written
    for r in rows:
        if r["fixed"] and r["state"] == "open" and gate_check(
                conv, r["turn"], r["orig"], [(_gate_label(conv, q), q["orig"]) for q in rows[:r["at"]]],
                run["sources"], r["spoken"]):
            run["reserve"].add(r["at"])
    return run


def _gate_event(conv, run, row, stage, **extra):
    t = conv["turns"][row["turn"]] if row.get("turn") is not None else None
    body = {"stage": stage, "turn_index": row.get("turn") if row.get("turn") is not None else -1,
            "script_index": row["at"], "seat": row["seat"], "leg": row.get("leg") or "",
            "planned": row.get("turn") is not None, "line": _gate_excerpt(row.get("text"), 200),
            "at": time.time()}
    if t is not None:
        body["turn_id"] = t["turn_id"]
        body["dice"] = gate_dice(conv, row["turn"])
    body.update(extra)
    run["events"].append(body)
    return body


def _gate_earlier(conv, run, row):
    """The lines a turn may not repeat: every line said before it (as written and
    as re-written) - and, for a re-write, its own draft and the lines the writer
    already put after it."""
    out = []
    for q in run["rows"][:row["at"]]:
        out.append((_gate_label(conv, q), q["orig"]))
        if q["text"] != q["orig"] and q["state"] in ("kept", "rewritten"):
            out.append((_gate_label(conv, q), q["text"]))
    if row["tries"]:
        out.append(("its own draft", row["orig"]))
        out += [(_gate_label(conv, q), q["orig"]) for q in run["rows"][row["at"] + 1:] if q["state"] == "open"]
    return out


def _gate_kept_before(run, row):
    return [q for q in run["rows"][:row["at"]] if q["state"] in ("kept", "rewritten")]


def _gate_budget(run, row):
    left = run["visits"] - run["spent"]
    if run.get("legs_only") and not row["fixed"]:     # [live-legs] a live round re-writes its legs only
        return False
    if left <= 0 or row["turn"] is None or len(row["tries"]) >= run["rewrites"]:
        return False
    if row["fixed"]:
        return True
    owed = sum(1 for q in run["rows"][row["at"] + 1:] if q["at"] in run["reserve"] and not q["tries"])
    return left - owed > 0


def _gate_drop(conv, run, row, why):
    row["state"], row["why"] = "dropped", why
    run["counts"]["dropped"] += 1
    if row["fixed"] and not run["held"]:
        run["held"] = "turn %d (%s) could not be written without copying: %s" % (
            (row["turn"] or 0) + 1, row["leg"] or "a protocol leg", (row.get("catch") or {}).get("why") or why)
    _gate_event(conv, run, row, "dropped", why=why, rule=(row.get("catch") or {}).get("rule"),
                tries=len(row["tries"]))
    # THE SHAPE: nobody speaks twice in a row where the drop would make them. The
    # later of the pair answered the dropped line and goes with it; a protocol leg
    # stays, and then the earlier one goes (when it may).
    kept = _gate_kept_before(run, row)
    nxt = next((q for q in run["rows"][row["at"] + 1:] if q["state"] == "open"), None)
    if not kept or nxt is None or kept[-1]["seat"] != nxt["seat"]:
        return
    for pair in (nxt, kept[-1]):
        if not pair["fixed"]:
            was = pair["state"]
            pair["state"] = "dropped"
            pair["why"] = ("it answered a dropped line, and %s would speak twice in a row"
                           % _gate_name(conv, pair["seat"]))
            if was == "rewritten":
                run["counts"]["rewritten"] -= 1
            run["counts"]["dropped"] += 1
            _gate_event(conv, run, pair, "dropped with its pair", why=pair["why"])
            return


def gate_next(conv, run):
    """The next re-write the station should ask for, or None when the walk is over.
    From the cursor on: a turn that passes is kept (or counted re-written); a
    caught turn the plan rolled is asked for again while its tries and the
    round's visits last, protocol legs first; any other catch is dropped."""
    if run.get("ask"):
        return run["ask"]
    rows = run["rows"]
    while run["cursor"] < len(rows):
        r = rows[run["cursor"]]
        if r["state"] != "open":
            run["cursor"] += 1
            continue
        catch = gate_check(conv, r["turn"], r["text"], _gate_earlier(conv, run, r), run["sources"], r["spoken"])
        if catch is None:
            if r["tries"]:
                r["state"] = "rewritten"
                run["counts"]["rewritten"] += 1
                _gate_event(conv, run, r, "re-written", attempt=len(r["tries"]), was=_gate_excerpt(r["orig"], 200),
                            prompt=r["tries"][-1].get("prompt", ""))
            else:
                r["state"] = "kept"
            run["cursor"] += 1
            continue
        if not r["tries"]:
            r["catch"] = catch
            run["counts"]["caught"] += 1
            _gate_event(conv, run, r, "caught", rule=catch["rule"], why=catch["why"], of=catch["what"],
                        copied=catch.get("text", ""), how=catch.get("how", ""))
        else:
            r["tries"][-1]["catch"] = catch
            _gate_event(conv, run, r, "re-write still copies", attempt=len(r["tries"]), rule=catch["rule"],
                        why=catch["why"], of=catch["what"], prompt=r["tries"][-1].get("prompt", ""))
        if _gate_budget(run, r):
            kept = _gate_kept_before(run, r)
            prev = (_gate_name(conv, kept[-1]["seat"]), kept[-1]["text"]) if kept else None
            context = [(q["seat"], q["text"]) for q in kept]
            first = dict(r["catch"], draft=r["orig"])
            prompt = gate_ask(conv, r["turn"], prev, context, first, r["tries"])
            run["spent"] += 1
            run["ask"] = {"at": r["at"], "turn": r["turn"], "turn_id": r["turn_id"], "seat": r["seat"],
                          "attempt": len(r["tries"]) + 1, "prompt": prompt,
                          "limit": 700 if r["seat"] not in ("A", "B", "D") else 900}
            return run["ask"]
        why = (catch["why"] if r["turn"] is not None else
               "%s - and no node rolled it (the writer added it), so there are no dice to write it again with"
               % catch["why"])
        if r["turn"] is not None and r["tries"]:
            why = "still a copy after %d re-write(s): %s" % (len(r["tries"]), catch["why"])
        elif r["turn"] is not None and (not run["rewrites"] or (run.get("legs_only") and not r["fixed"])):
            why = "%s - this round is not re-written (a live round, or repair is off)" % catch["why"]
        elif r["turn"] is not None:
            why = "%s - the round's re-write visits are spent" % catch["why"]
        _gate_drop(conv, run, r, why)
        run["cursor"] += 1
    return None


def gate_take(conv, run, text, spoken=None):
    """The writer's answer to the ask outstanding: it becomes the turn's words,
    checked on the walk's next step."""
    ask = run.get("ask")
    if not ask:
        return None
    r = run["rows"][ask["at"]]
    r["tries"].append({"attempt": ask["attempt"], "text": _gate_excerpt(text, 600),
                       "prompt": ask["prompt"][-4000:]})
    r["text"] = " ".join(str(text or "").split())
    r["spoken"] = None if spoken is None else str(spoken)
    run["ask"] = None
    return r


def gate_close(conv, run):
    """The walk is over: the round as it airs, and its record on the aggregate
    (conv["turn_gate"]: caught / re-written / dropped / trimmed / visits / held)."""
    rows = run["rows"]
    while gate_next(conv, run) is not None:     # an unanswered ask counts as a failed try
        gate_take(conv, run, "")
    kept = [r for r in rows if r["state"] in ("kept", "rewritten")]
    if len(kept) < 2 and not run["held"]:
        run["held"] = "fewer than two turns are left once the copies are out"
    changed = any(r["state"] in ("dropped", "rewritten") for r in rows)
    record = {"at": time.time(), "written": len(rows), "kept": len(kept),
              "caught": run["counts"]["caught"], "rewritten": run["counts"]["rewritten"],
              "dropped": run["counts"]["dropped"], "trimmed": run["counts"]["trimmed"],
              "visits": run["spent"], "held": run["held"],
              "turns": [{"at": r["at"], "turn": r["turn"], "turn_id": r["turn_id"], "seat": r["seat"],
                         "leg": r["leg"], "state": r["state"], "rule": (r.get("catch") or {}).get("rule"),
                         "of": (r.get("catch") or {}).get("what"), "tries": len(r["tries"]), "why": r["why"]}
                        for r in rows if r["state"] in ("dropped", "rewritten") or r.get("catch")]}
    prior = conv.get("turn_gate") or {}
    if prior.get("in_chain"):
        record["in_chain"] = prior["in_chain"]
    conv["turn_gate"] = record
    body = {"stage": "gate", "turn_index": -1, "caught": record["caught"], "rewritten": record["rewritten"],
            "dropped": record["dropped"], "trimmed": record["trimmed"], "visits": record["visits"],
            "held": record["held"], "line": "%d caught, %d re-written, %d dropped%s" % (
                record["caught"], record["rewritten"], record["dropped"],
                (", %d past the end" % record["trimmed"]) if record["trimmed"] else ""), "at": time.time()}
    run["events"].append(body)
    return {"script": "\n".join("%s: %s" % (r["seat"], r["text"]) for r in kept), "changed": changed,
            "held": run["held"], "counts": dict(run["counts"], visits=run["spent"], kept=len(kept)),
            "record": record}


def gate_counts(conv):
    """The round's gate record, for the list row: caught / re-written / dropped."""
    g = conv.get("turn_gate") or {}
    if not g:
        return None
    out = {k: g.get(k) for k in ("caught", "rewritten", "dropped", "trimmed", "visits", "held")}
    out["in_chain"] = (g.get("in_chain") or {}).get("caught", 0)
    # [gate-accounted] the planned turns the gate dropped ON PURPOSE: the booth
    # counts them as decided, not as missing
    out["dropped_ids"] = [str(t.get("turn_id")) for t in (g.get("turns") or [])
                          if t.get("state") == "dropped" and t.get("turn") is not None and t.get("turn_id")]
    return out


# --- Mode B: turn by turn --------------------------------------------------

_HEAT = r"\b(furious|outrage|ridiculous|shut up|how dare|liar|hate|insane|unbelievable)\b|!{2,}"


def observe(conv, turn_index, text, seconds=None):
    """Mode B: one written (or rendered) turn comes back. Validate it
    against its intent and move the state by what was actually said."""
    if not (0 <= turn_index < len(conv["turns"])):
        raise IndexError("no planned turn %d" % turn_index)
    t = conv["turns"][turn_index]
    t["text"] = str(text or "")                                              # [s3-split] whole
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
    # [s3-turnchain] a turn that is not a new line says so on its observation (the
    # state still moves by what was said: a replay re-applies the same deltas)
    _copy = gate_check(conv, turn_index, t["text"],
                       [("turn %d" % (x["index"] + 1), x["text"]) for x in conv["turns"][:turn_index]
                        if x.get("text")])
    if _copy:
        rec["copy"] = _copy
    conv["observations"].append(rec)
    return rec


def replan(conv, config, from_index, until=None):
    """Mode B: throw away the plan from `from_index` on and decide it again
    from the state the written turns actually left behind. The RNG stream
    carries on (it is never rewound), so the new draws are new and
    recorded; decision replay re-applies the same observations."""
    config = event_view(config, conv.get("inputs") or {})        # [s3-live-event]
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
    graph_road = str((conv.get("graph_structure") or {}).get("road") or "")
    if graph_road and graph_road != "banter":
        return plan_graph(conv, config, (road_structure(config, graph_road) or {}).get("graph"),
                          until=until, road=graph_road)
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
    if road in system3_tables.LINE_ROADS and not stored.get("graph_structure"):
        plan_line(conv, config)
    elif stored.get("graph_structure"):
        graph = ((config.get("structure") or {}).get("graph") if road == "banter"
                 else (road_structure(config, road) or {}).get("graph"))
        plan_graph(conv, config, graph, road=road)
        for rp in replans:
            for o in obs:
                if o["turn_index"] < rp["from"] and not any(x["turn_index"] == o["turn_index"]
                                                            for x in conv["observations"]):
                    observe(conv, o["turn_index"], o["text"], o.get("seconds"))
            replan(conv, config, rp["from"], until=stored["timing"]["turn_budget"])
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
    for _sp in stored.get("splits") or []:                                     # [s3-split] after the words
        _replay_split(conv, config, _sp)
    a = [(e["family"], (e.get("selected") or {}).get("id"), (e.get("rng") or {}).get("u")) for e in stored["decision_events"]
         if e["family"] != "STATION"          # [s3-dice-door] drawn by the road before the plan: recorded, not replayed
         and not (e.get("meta") or {}).get("road_roll")]   # [s3-mgrtopics] the manager's topic draws, likewise
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
            "revision": conv["identity"]["revision"], "topic": label_cut(conv["subject"]["topic"], 120),
            "verdict": val.get("verdict"), "score": val.get("score"),
            "shadow": (conv.get("comparison") or {}).get("seat_similarity"),
            "system2_slot_id": conv["identity"]["system2_slot_id"],
            "generation_mode": conv.get("generation_mode"),
            "gate": gate_counts(conv)}                                           # [s3-turnchain]


# --- [s3-live-event] THE EVENT VIEW -----------------------------------------------
#
# A station event (MX Live) is a register entry the runtime keeps in
# config["events"]; its rows are ordinary table rows tagged "event". The
# planners see the config through event_view: while the event is off (or on a
# banked round, or the category's stage does not match) the tagged rows are
# taken out BEFORE any weight is computed, so no draw moves. inputs["events"]
# is {"<id>": {"stage": upcoming|live|fallback|after, ...}}, decided by the
# runtime at plan time and stored on the conversation's inputs - replay sees
# the same view the plan did.


def event_view(config, inputs):
    """The config as this plan may see it. The same object back when nothing
    is tagged (the common case costs one scan and no copy)."""
    tables = (config.get("tables") or []) if isinstance(config, dict) else []
    if not any(isinstance(t, dict) and t.get("event") for t in tables):
        return config
    events = (inputs or {}).get("events") or {}
    banked = bool((inputs or {}).get("bank"))
    out = []
    changed = False
    for t in tables:
        eid = t.get("event") if isinstance(t, dict) else None
        if not eid:
            out.append(t)
            continue
        ev = events.get(str(eid)) if isinstance(events, dict) else None
        stage = str((ev or {}).get("stage") or "")
        if not stage or (banked and not t.get("event_banked")):
            changed = True
            continue
        cats, cut = [], False
        for c in t.get("categories") or []:
            stages = [str(s) for s in ((c or {}).get("event_stages") or [])]
            if stages and stage not in stages:
                cut = True
                continue
            cats.append(c)
        if not cats:
            changed = True
            continue
        if cut:
            t = dict(t)
            t["categories"] = cats
            changed = True
        out.append(t)
    if not changed:
        return config
    view = dict(config)
    view["tables"] = out
    return view


def event_claims(conv):
    """The event rows this round's rolls landed on, as "table:item" - what
    claims the event_facts block (decide_blocks kind "claimed")."""
    out = []

    def _add(tag, tid, item):
        if tag:
            key = "%s:%s" % (tid, item)
            if key not in out:
                out.append(key)

    for p in conv.get("event_plans") or []:
        _add(p.get("event"), p.get("table"), p.get("id"))
    for t in conv.get("turns") or []:
        for d in t.get("decisions") or []:
            _add(d.get("event"), d.get("table"), d.get("item"))
        tt = t.get("track_talk") or {}
        _add(tt.get("event"), tt.get("table"), tt.get("item"))
    return out

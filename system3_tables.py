"""System 3's behavioural tables, as versioned data.

The operator's System 3 document draws five lists - CST1 (conversation /
segment topics), ES1 (emotional set), RS1 (response set), IRS1 (initiator
response set) and FL1 (frame list) - and asks for each to be customisable,
weighted by sliders, expandable, and supplemented ("make an ES2 based on
ES1"). The blueprint adds the conversational acts it names (agree, qualify,
challenge premise, ...) and the flow moves (continue, deepen, tangent, ...).

Nothing in here is code that decides anything. It is the seed a fresh
station starts from; the live copy is edited through /api/system3/tables
and stored, versioned, in data/system3.sqlite3. Every field is documented
in docs/SYSTEM3_CONFIG_REFERENCE.md.

Shape of one table:

    {"id": "ES1", "family": "ES", "label": ..., "version": 1,
     "enabled": True, "weight": 1.0,
     "categories": [{"id", "label", "weight", <item defaults>,
                     "items": [{"id", "label", "text", "weight", ...}]}]}

An item inherits any field its category sets and does not override.
"""
from __future__ import annotations

import copy

TABLES_VERSION = 1

# Lexical cue kinds the deterministic validator knows (system3.CUES).
# An item names one with "cue"; an item with no cue is recorded as
# "unchecked" rather than guessed at.


def _items(rows, **common):
    out = []
    for row in rows:
        item = dict(common)
        if isinstance(row, str):
            item.update(id=row.lower().replace(" ", "_").replace("-", "_"), label=row)
        else:
            item.update(row)
        out.append(item)
    return out


# --- CTS1: Conversation / Segment Topics ----------------------------------
#
# "Selected at random and based on segment." System 3 has authority over
# a subject only where nothing else owns it: the round's own material
# (a seed passage, a wire story, the manager's memo, a painting) is an
# OBLIGATION and is recorded as such, never re-drawn. CTS is drawn when a
# frame cancels the topic mid-round. `requires` names the material the
# road must actually hold for the category to be eligible - a category
# with nothing real behind it is excluded, so the writer is never told to
# discuss a headline that does not exist.
CTS1 = {
    "id": "CTS1", "family": "CTS", "label": "Conversation / Segment Topics",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "What the conversation is about. Drawn only where System 3 has authority over the subject.",
    "categories": [
        {"id": "speakerbox", "label": "Speaker-box Quote / Monologue", "weight": 3.0,
         "requires": ["speakbox"], "resolver": "speakbox",
         "items": _items([
             {"id": "quote_1_2", "label": "1 - 2 sentence quote", "sentences": [1, 2],
              "text": "brings up a one-or-two-sentence quote from the speakerbox in their own voice"},
             {"id": "quote_2_3", "label": "2 - 3 sentences", "sentences": [2, 3],
              "text": "reads two or three sentences out of the speakerbox and reacts to them"},
         ])},
        {"id": "topic", "label": "Topic", "weight": 1.0, "requires": ["topics"],
         "resolver": "direction",
         "items": _items([{"id": "topics_db", "label": "From Topics Database",
                           "text": "raises the next subject from the station's topic book"}])},
        {"id": "internet_news", "label": "Internet News", "weight": 1.5, "requires": ["news"],
         "resolver": "direction",
         "items": _items([
             {"id": "searxng", "label": "searXNG", "text": "brings up a story from the wire search"},
             {"id": "drudge", "label": "Drudge Report (preferred)", "weight": 2.0,
              "text": "brings up a Drudge Report headline from the wire"},
             {"id": "networks", "label": "CNN / MSNOW / FOX News / OANN",
              "text": "brings up how the networks are covering a story on the wire"},
         ])},
        {"id": "manager_message", "label": "Manager Message", "weight": 1.0, "requires": ["manager"],
         "resolver": "direction",
         "items": _items([{"id": "last_statement", "label": "Discussion on the last statement said by the manager from upstairs",
                           "text": "brings up the last thing the manager said from upstairs"}])},
        {"id": "ad_pitch", "label": "Ad Pitch", "weight": 0.8, "resolver": "direction",
         "items": _items([
             {"id": "gallery_item", "label": "Gallery item", "requires": ["gallery"],
              "text": "pitches a piece from the Pine Box gallery"},
             {"id": "video_snuff", "label": "Video from gallery sold as: Snuff film", "requires": ["gallery"],
              "text": "pitches a gallery video, sold as a snuff film"},
             {"id": "video_lost", "label": "Video from gallery sold as: Lost found footage", "requires": ["gallery"],
              "text": "pitches a gallery video, sold as lost found footage"},
             {"id": "video_hidden", "label": "Video from gallery sold as: Hidden footage", "requires": ["gallery"],
              "text": "pitches a gallery video, sold as hidden footage"},
             {"id": "video_backstage", "label": "Video from gallery sold as: Backstage access", "requires": ["gallery"],
              "text": "pitches a gallery video, sold as backstage access"},
             {"id": "mugs", "label": "Products: Mugs",
              "text": "pitches Pine Box mugs adorned with graphics from the Pine Box gallery"},
             {"id": "sweaters", "label": "Products: Sweaters",
              "text": "pitches Pine Box sweaters adorned with graphics from the Pine Box gallery"},
         ])},
        {"id": "gazette", "label": "Products from Pine Box Gazette", "weight": 1.0, "requires": ["gazette"],
         "resolver": "direction",
         "items": _items([
             {"id": "lost_pets", "label": "Lost pets", "text": "brings up a lost pet notice from the Pine Box Gazette"},
             {"id": "found_items", "label": "Found items", "text": "brings up a found item from the Pine Box Gazette"},
             {"id": "for_sale", "label": "Things for sale", "text": "brings up something for sale in the Pine Box Gazette"},
             {"id": "stories", "label": "Stories from the paper", "text": "brings up a story from the Pine Box Gazette"},
         ])},
    ],
}

# --- ES1: Emotional Set 1 --------------------------------------------------
#
# "Every response needs to have an ES1 signature to tell the intonation
# engine how to guide the speech generation." Each category carries a
# valence/arousal pair and its weight on the station's six performance
# dimensions (app.py EMOTION_DIMS), which is how an emotion reaches the
# voice: ES -> PerformanceIntent.dims -> performance_vector(state=...) ->
# perf_apply on the rendered take, for every engine.
_ES_CATS = [
    ("surprise", "SURPRISE", 0.15, 0.75, {"excitement": 0.7, "confusion": 0.35},
     {"tension": 0.2}, ["surprise", "shock", "astonishment", "amazement", "disbelief",
                        "bewilderment", "confusion", "curiosity", "intrigue"]),
    ("anger", "ANGER", -0.7, 0.85, {"irritation": 0.95, "excitement": 0.3},
     {"tension": 1.4, "agreement": -1.2}, ["annoyance", "irritation", "frustration", "indignation",
                                           "anger", "outrage", "fury", "resentment", "contempt", "disgust"]),
    ("fear", "FEAR", -0.6, 0.7, {"nervousness": 0.95, "confusion": 0.2},
     {"tension": 0.6}, ["unease", "apprehension", "anxiety", "alarm", "fear", "dread", "panic", "horror"]),
    ("sadness", "SADNESS", -0.6, 0.25, {"fatigue": 0.7, "nervousness": 0.15},
     {"energy": -0.8}, ["disappointment", "discouragement", "sadness", "grief", "despair",
                        "melancholy", "sympathy", "pity"]),
    ("joy", "JOY", 0.8, 0.65, {"amusement": 0.75, "excitement": 0.6},
     {"agreement": 0.9, "tension": -0.8}, ["pleasure", "happiness", "delight", "excitement", "enthusiasm",
                                           "amusement", "relief", "satisfaction"]),
    ("disgust", "DISGUST", -0.6, 0.55, {"irritation": 0.7},
     {"tension": 0.8, "agreement": -0.6}, ["distaste", "aversion", "disgust", "revulsion", "repulsion",
                                           "moral disgust"]),
    ("interest", "INTEREST", 0.3, 0.5, {"excitement": 0.45, "confusion": 0.1},
     {"novelty": 0.6}, ["curiosity", "fascination", "intrigue", "attentiveness", "skepticism",
                        "suspicion", "uncertainty"]),
    ("social", "SOCIAL / SELF-CONSCIOUS", -0.15, 0.5, {"nervousness": 0.7, "amusement": 0.1},
     {}, ["embarrassment", "awkwardness", "shame", "guilt", "pride", "admiration", "envy",
          "jealousy", "defensiveness"]),
    ("low_arousal", "LOW-AROUSAL / DETACHED", 0.0, 0.15, {"fatigue": 0.85},
     {"energy": -1.2, "closure_pressure": 0.8}, ["indifference", "boredom", "apathy", "resignation",
                                                 "exhaustion", "calm", "acceptance"]),
]
# Items whose arousal sits well off their category's (a fury is not an
# annoyance). Anything unlisted inherits the category.
_ES_AROUSAL = {"fury": 0.98, "outrage": 0.92, "annoyance": 0.45, "irritation": 0.55,
               "panic": 0.97, "horror": 0.92, "unease": 0.4, "apprehension": 0.5,
               "shock": 0.9, "curiosity": 0.45, "intrigue": 0.45, "calm": 0.08,
               "exhaustion": 0.1, "excitement": 0.85, "enthusiasm": 0.8, "relief": 0.35,
               "satisfaction": 0.35, "grief": 0.35, "despair": 0.3, "pride": 0.6,
               "defensiveness": 0.65, "contempt": 0.6, "resentment": 0.55}
_ES_VALENCE = {"pride": 0.5, "admiration": 0.6, "curiosity": 0.4, "amazement": 0.4,
               "skepticism": -0.1, "suspicion": -0.3, "acceptance": 0.3, "calm": 0.3,
               "sympathy": 0.1, "relief": 0.6}

# How a speaker's emotion leans after the turn before them pushed back
# (-1), went along (1) or did neither (0): a multiplier on the category.
_ES_AFTER = {"anger": {"-1": 1.5, "1": 0.7}, "disgust": {"-1": 1.25},
             "joy": {"1": 1.4, "-1": 0.7}, "social": {"-1": 1.3},
             "surprise": {"-1": 1.1, "0": 1.1}, "interest": {"0": 1.2},
             "low_arousal": {"1": 1.2}}

# [s3-es-emoji] THE BADGE A MESSAGE WEARS. 2026-09-28, the operator: "for
# messages that get an ES result from the roulette, have them display relevant
# emojis for each category in the bottom right of each message." Real colour
# emoji - the one exception to the station's Carbon-icons-only rule, and only
# for this badge. One per category; an item carries its own only where a more
# specific one exists (fury, panic, grief ...) - a word unlisted here, or one
# whose emoji is its category's, wears the category's. The engine stamps the
# pair on the turn's ES decision as `emoji`: [category, item] (system3.es_emoji).
# Edited per row in the Tables tab; the live config was given these once
# (System3Runtime.add_missing_es_emoji), so a badge the operator clears stays clear.
_ES_EMOJI = {"surprise": "\U0001F62E", "anger": "\U0001F620", "fear": "\U0001F628",   # 😮 😠 😨
             "sadness": "\U0001F622", "joy": "\U0001F604", "disgust": "\U0001F922",  # 😢 😄 🤢
             "interest": "\U0001F914", "social": "\U0001F633",                       # 🤔 😳
             "low_arousal": "\U0001F610"}                                            # 😐
_ES_ITEM_EMOJI = {
    # surprise: ⚡ 😲 🤯 ⁉️ 😵‍💫 😕 🧐 👀
    "shock": "\U000026A1", "astonishment": "\U0001F632", "amazement": "\U0001F92F",
    "disbelief": "\U00002049\U0000FE0F", "bewilderment": "\U0001F635\U0000200D\U0001F4AB",
    "confusion": "\U0001F615", "curiosity": "\U0001F9D0", "intrigue": "\U0001F440",
    # anger: 🙄 💢 😖 😤 🤬 😡 😒 😏 🤢
    "annoyance": "\U0001F644", "irritation": "\U0001F4A2", "frustration": "\U0001F616",
    "indignation": "\U0001F624", "outrage": "\U0001F92C", "fury": "\U0001F621",
    "resentment": "\U0001F612", "contempt": "\U0001F60F", "disgust": "\U0001F922",
    # fear: 😟 😬 😰 🚨 😧 😱 💀
    "unease": "\U0001F61F", "apprehension": "\U0001F62C", "anxiety": "\U0001F630",
    "alarm": "\U0001F6A8", "dread": "\U0001F627", "panic": "\U0001F631", "horror": "\U0001F480",
    # sadness: 😞 😔 😭 😩 🥀 🫂 🥺
    "disappointment": "\U0001F61E", "discouragement": "\U0001F614", "grief": "\U0001F62D",
    "despair": "\U0001F629", "melancholy": "\U0001F940", "sympathy": "\U0001FAC2", "pity": "\U0001F97A",
    # joy: 😊 😁 🎉 🙌 😂 😌 👌
    "pleasure": "\U0001F60A", "delight": "\U0001F601", "excitement": "\U0001F389",
    "enthusiasm": "\U0001F64C", "amusement": "\U0001F602", "relief": "\U0001F60C",
    "satisfaction": "\U0001F44C",
    # disgust: 🙁 🙅 🤮 ✋ 👎
    "distaste": "\U0001F641", "aversion": "\U0001F645", "revulsion": "\U0001F92E",
    "repulsion": "\U0000270B", "moral disgust": "\U0001F44E",
    # interest: 🤩 👂 🤨 🕵️ 🤷 (curiosity and intrigue as under surprise)
    "fascination": "\U0001F929", "attentiveness": "\U0001F442", "skepticism": "\U0001F928",
    "suspicion": "\U0001F575\U0000FE0F", "uncertainty": "\U0001F937",
    # social: 😅 🙈 😓 😎 😍 💚 😾 🛡️
    "awkwardness": "\U0001F605", "shame": "\U0001F648", "guilt": "\U0001F613", "pride": "\U0001F60E",
    "admiration": "\U0001F60D", "envy": "\U0001F49A", "jealousy": "\U0001F63E",
    "defensiveness": "\U0001F6E1\U0000FE0F",
    # low_arousal: 😑 🥱 😶 😮‍💨 😫 🧘 🙂
    "indifference": "\U0001F611", "boredom": "\U0001F971", "apathy": "\U0001F636",
    "resignation": "\U0001F62E\U0000200D\U0001F4A8", "exhaustion": "\U0001F62B", "calm": "\U0001F9D8",
    "acceptance": "\U0001F642",
}

# [s3-es-dir] WHAT THE WRITER IS TOLD FOR A FEELING. 2026-09-28, the operator:
# "By default have the writer told to "write the message with this feeling
# reflecting the mood" for the actor". The ES roll lands on a category (by the
# category's weight) and then on an item inside it (by the items' weights); the
# item's `text` is what its turn's row in the running order tells the writer.
# {feeling} is the item, {name} the seat speaking the line - filled in when the
# turn is planned (system3.es_direction). A blank text reads as this default.
ES_DIRECTION = "Write {name}'s message with {feeling}, reflecting the mood."

# [s3-es-voice] HOW A FEELING SOUNDS. 2026-09-28, the operator: the roll "is fed
# to the intonation engine to take place affecting the way the recording is made
# so they emotionally reflect the dialogue". Each category's `voice`, at FULL
# intensity (the turn's intensity scales it: system3.voice_intent):
#   tempo   x   how fast the line is spoken            (1.08 = 8% faster)
#   pitch   st  where the voice's middle sits          (formants kept)
#   range   x   how far the melody swings around it    (1.3 = wider)
#   energy  +-  vocal effort: brighter/pressed (+), softer/darker (-); heard as
#               colour, never as volume - every clip is still levelled
#   pause   x   the gaps between phrases               (1.3 = longer)
#   temp    +-  XTTS sampling temperature (livelier + / steadier -)
# An item listed in _ES_ITEM_VOICE sounds unlike its category (a fury is not an
# annoyance); its block names only what differs. Keyed by the word, or by
# "category.word" where the word sits in two categories (disgust). The station holds every value
# inside ES_VOICE_BOUNDS whatever the table says (es_voice.py).
ES_VOICE_KEYS = ("tempo", "pitch", "range", "energy", "pause", "temp")
ES_VOICE_BOUNDS = {"tempo": (0.85, 1.15), "pitch": (-2.0, 2.0), "range": (0.6, 1.5),
                   "energy": (-0.8, 0.8), "pause": (0.7, 1.5), "temp": (-0.1, 0.1)}
_ES_VOICE = {
    #               tempo          pitch          range          energy          pause          temp
    "surprise":    {"tempo": 1.05, "pitch": 1.6,  "range": 1.40, "energy": 0.30,  "pause": 0.85, "temp": 0.06},
    "anger":       {"tempo": 1.08, "pitch": 0.8,  "range": 1.30, "energy": 0.60,  "pause": 0.78, "temp": 0.05},
    "fear":        {"tempo": 1.10, "pitch": 1.2,  "range": 0.90, "energy": 0.25,  "pause": 0.88, "temp": 0.05},
    "sadness":     {"tempo": 0.88, "pitch": -1.0, "range": 0.70, "energy": -0.50, "pause": 1.35, "temp": -0.05},
    "joy":         {"tempo": 1.06, "pitch": 1.2,  "range": 1.35, "energy": 0.40,  "pause": 0.90, "temp": 0.05},
    "disgust":     {"tempo": 0.92, "pitch": -0.8, "range": 1.15, "energy": 0.10,  "pause": 1.15, "temp": -0.02},
    "interest":    {"tempo": 1.03, "pitch": 0.6,  "range": 1.20, "energy": 0.15,  "pause": 0.95, "temp": 0.03},
    "social":      {"tempo": 0.96, "pitch": 0.3,  "range": 0.85, "energy": -0.20, "pause": 1.15, "temp": 0.0},
    "low_arousal": {"tempo": 0.88, "pitch": -0.8, "range": 0.65, "energy": -0.55, "pause": 1.35, "temp": -0.07},
}
_ES_ITEM_VOICE = {
    # surprise
    "shock":          {"tempo": 1.08, "pitch": 1.8, "range": 1.45, "energy": 0.45, "pause": 0.80},
    "astonishment":   {"pitch": 1.8, "range": 1.45},
    "amazement":      {"pitch": 1.4, "energy": 0.35},
    "disbelief":      {"tempo": 0.98, "pitch": 1.0, "pause": 1.05},
    "bewilderment":   {"tempo": 0.95, "pitch": 0.6, "range": 1.20, "energy": 0.05, "pause": 1.15},
    "confusion":      {"tempo": 0.94, "pitch": 0.4, "range": 1.15, "energy": 0.0, "pause": 1.20, "temp": 0.02},
    "curiosity":      {"tempo": 1.0, "pitch": 0.6, "range": 1.20, "energy": 0.10, "pause": 0.95, "temp": 0.03},
    "intrigue":       {"tempo": 0.98, "pitch": 0.4, "range": 1.15, "energy": 0.05, "pause": 1.0, "temp": 0.02},
    # anger
    "annoyance":      {"tempo": 1.02, "pitch": 0.2, "range": 1.10, "energy": 0.25, "pause": 0.95, "temp": 0.02},
    "irritation":     {"tempo": 1.04, "pitch": 0.3, "range": 1.15, "energy": 0.35, "pause": 0.90},
    "frustration":    {"tempo": 1.04, "pitch": 0.5, "range": 1.20, "energy": 0.40, "pause": 0.92},
    "indignation":    {"range": 1.30, "energy": 0.50},
    "outrage":        {"tempo": 1.10, "pitch": 1.2, "range": 1.40, "energy": 0.70, "pause": 0.75, "temp": 0.06},
    "fury":           {"tempo": 1.12, "pitch": 1.4, "range": 1.45, "energy": 0.80, "pause": 0.72, "temp": 0.07},
    "resentment":     {"tempo": 0.96, "pitch": -0.3, "range": 1.05, "energy": 0.30, "pause": 1.05, "temp": 0.0},
    "contempt":       {"tempo": 0.94, "pitch": -0.6, "range": 1.20, "energy": 0.20, "pause": 1.10, "temp": 0.0},
    "anger.disgust":  {"tempo": 0.95, "pitch": -0.5, "range": 1.15, "energy": 0.25, "pause": 1.05},
    # fear
    "unease":         {"tempo": 1.02, "pitch": 0.4, "energy": 0.0, "pause": 1.05, "temp": 0.02},
    "apprehension":   {"tempo": 1.04, "pitch": 0.6, "energy": 0.10, "pause": 1.0},
    "anxiety":        {"tempo": 1.08, "pitch": 0.9, "range": 0.85, "energy": 0.15, "pause": 0.92},
    "alarm":          {"pitch": 1.4, "range": 1.25, "energy": 0.40, "pause": 0.85},
    "dread":          {"tempo": 0.92, "pitch": -0.3, "range": 0.75, "energy": -0.20, "pause": 1.25, "temp": -0.02},
    "panic":          {"tempo": 1.14, "pitch": 1.8, "range": 1.30, "energy": 0.50, "pause": 0.75, "temp": 0.07},
    "horror":         {"tempo": 1.0, "pitch": 1.2, "range": 1.30, "energy": 0.35, "pause": 1.0},
    # sadness
    "disappointment": {"tempo": 0.92, "pitch": -0.6, "range": 0.80, "energy": -0.30, "pause": 1.20},
    "discouragement": {"tempo": 0.90, "pitch": -0.8, "range": 0.75, "energy": -0.40, "pause": 1.25},
    "grief":          {"tempo": 0.86, "pitch": -0.6, "range": 0.85, "energy": -0.40, "pause": 1.45, "temp": 0.02},
    "despair":        {"tempo": 0.85, "pitch": -1.2, "range": 0.65, "energy": -0.60, "pause": 1.45},
    "melancholy":     {"pitch": -0.8, "energy": -0.45},
    "sympathy":       {"tempo": 0.94, "pitch": -0.3, "range": 0.90, "energy": -0.30, "pause": 1.15, "temp": -0.02},
    "pity":           {"tempo": 0.94, "pitch": -0.2, "range": 0.95, "energy": -0.25, "pause": 1.15},
    # joy
    "pleasure":       {"tempo": 1.02, "pitch": 0.6, "range": 1.20, "energy": 0.20, "pause": 0.95},
    "delight":        {"pitch": 1.4, "range": 1.40, "energy": 0.45},
    "excitement":     {"tempo": 1.10, "pitch": 1.6, "range": 1.40, "energy": 0.60, "pause": 0.82, "temp": 0.06},
    "enthusiasm":     {"tempo": 1.08, "range": 1.35, "energy": 0.55, "pause": 0.85},
    "amusement":      {"tempo": 1.04, "pitch": 1.0, "range": 1.40, "energy": 0.30, "pause": 0.95},
    "relief":         {"tempo": 0.94, "pitch": -0.2, "range": 1.10, "energy": -0.10, "pause": 1.15, "temp": 0.0},
    "satisfaction":   {"tempo": 0.96, "pitch": 0.0, "range": 1.05, "energy": 0.0, "pause": 1.10, "temp": 0.0},
    # disgust
    "distaste":       {"tempo": 0.95, "pitch": -0.5, "range": 1.05, "energy": 0.0, "pause": 1.10},
    "revulsion":      {"tempo": 0.90, "pitch": -1.0, "range": 1.25, "energy": 0.25, "pause": 1.20},
    "repulsion":      {"tempo": 0.91, "pitch": -0.9, "range": 1.20, "energy": 0.20, "pause": 1.18},
    "moral disgust":  {"tempo": 0.94, "pitch": -0.6, "range": 1.20, "energy": 0.30, "pause": 1.10},
    # interest (curiosity and intrigue as under surprise)
    "fascination":    {"tempo": 1.0, "pitch": 0.8, "range": 1.30, "energy": 0.20},
    "attentiveness":  {"tempo": 1.0, "pitch": 0.2, "range": 1.05, "energy": 0.05, "pause": 1.0},
    "skepticism":     {"tempo": 0.96, "pitch": -0.2, "range": 1.25, "energy": 0.05, "pause": 1.10, "temp": 0.0},
    "suspicion":      {"tempo": 0.95, "pitch": -0.4, "range": 1.10, "energy": 0.0, "pause": 1.15, "temp": 0.0},
    "uncertainty":    {"tempo": 0.95, "pitch": 0.2, "range": 0.95, "energy": -0.10, "pause": 1.20, "temp": 0.0},
    # social / self-conscious
    "awkwardness":    {"tempo": 0.98, "pitch": 0.4, "range": 0.95, "energy": -0.10, "pause": 1.20, "temp": 0.02},
    "shame":          {"tempo": 0.90, "pitch": -0.6, "range": 0.75, "energy": -0.40, "pause": 1.25},
    "guilt":          {"tempo": 0.92, "pitch": -0.5, "range": 0.80, "energy": -0.30, "pause": 1.20},
    "pride":          {"tempo": 0.98, "pitch": -0.2, "range": 1.15, "energy": 0.30, "pause": 1.05, "temp": 0.01},
    "admiration":     {"tempo": 1.0, "pitch": 0.6, "range": 1.20, "energy": 0.15, "pause": 1.0, "temp": 0.02},
    "envy":           {"pitch": -0.2, "range": 1.0, "energy": 0.10, "pause": 1.10},
    "jealousy":       {"tempo": 1.02, "pitch": 0.2, "range": 1.10, "energy": 0.25, "pause": 1.0, "temp": 0.02},
    "defensiveness":  {"tempo": 1.06, "pitch": 0.6, "range": 1.15, "energy": 0.40, "pause": 0.88, "temp": 0.03},
    # low arousal / detached
    "indifference":   {"tempo": 0.92, "pitch": -0.6, "energy": -0.45, "pause": 1.20},
    "boredom":        {"range": 0.60},
    "apathy":         {"pitch": -1.0, "range": 0.60, "energy": -0.60},
    "resignation":    {"tempo": 0.90, "range": 0.70, "energy": -0.45, "pause": 1.30},
    "exhaustion":     {"tempo": 0.85, "pitch": -1.0, "energy": -0.65, "pause": 1.45, "temp": -0.08},
    "calm":           {"tempo": 0.94, "pitch": -0.4, "range": 0.85, "energy": -0.30, "pause": 1.15, "temp": -0.05},
    "acceptance":     {"tempo": 0.95, "pitch": -0.2, "range": 0.90, "energy": -0.20, "pause": 1.10, "temp": -0.03},
}


def _es_item_voice(cid, word):
    """[s3-es-voice] An item's own voice block: "category.word" first (the same
    word can sit in two categories), then the word; None when it has none."""
    got = _ES_ITEM_VOICE.get("%s.%s" % (cid, word), _ES_ITEM_VOICE.get(word))
    return dict(got) if got else None

ES1 = {
    "id": "ES1", "family": "ES", "label": "Emotional Set 1", "version": 1,
    "enabled": True, "weight": 1.0,
    "description": "The emotion each turn is spoken in: guides the wording and the voice.",
    "categories": [
        {"id": cid, "label": label, "weight": 1.0, "valence": val, "arousal": ar,
         "dims": dims, "modifiers": mods, "after_lean": _ES_AFTER.get(cid, {}),
         "emoji": _ES_EMOJI[cid],                                          # [s3-es-emoji] the badge
         "voice": dict(_ES_VOICE[cid]),                                    # [s3-es-voice] how it sounds
         "items": _items([{"id": f"{cid}.{w.replace(' ', '_')}", "label": w,
                           "text": ES_DIRECTION,                           # [s3-es-dir] what the writer is told
                           **({"arousal": _ES_AROUSAL[w]} if w in _ES_AROUSAL else {}),
                           **({"valence": _ES_VALENCE[w]} if w in _ES_VALENCE else {}),
                           **({"voice": _es_item_voice(cid, w)} if _es_item_voice(cid, w) else {}),   # [s3-es-voice]
                           # [s3-es-emoji] its own, only where it is more specific than the category's
                           **({"emoji": _ES_ITEM_EMOJI[w]}
                              if _ES_ITEM_EMOJI.get(w, _ES_EMOJI[cid]) != _ES_EMOJI[cid] else {})}
                          for w in words])}
        for cid, label, val, ar, dims, mods, words in _ES_CATS
    ],
}

# --- RS1: Response Set 1 ---------------------------------------------------
RS1 = {
    "id": "RS1", "family": "RS", "label": "Response Set 1", "version": 1,
    "enabled": True, "weight": 1.0,
    "description": "How a responder takes what was just said (the operator's original list).",
    "categories": [
        {"id": "comedic", "label": "Comedic", "weight": 1.0, "lean": -1, "tags": ["humor"],
         "emotions": {"joy": 1.8, "disgust": 1.3, "sadness": 0.5},
         "effects": {"tension": 0.05, "agreement": -0.05, "novelty": 0.05},
         "items": _items([
             {"id": "make_fun", "label": "Making fun of the previous statement", "cue": "humor",
              "text": "makes fun of the previous statement"},
             {"id": "insult", "label": "Insulting the person who said it", "cue": "insult",
              "text": "insults the person who said it"},
             {"id": "disparage", "label": "Disparaging response", "cue": "disagree",
              "text": "answers with something disparaging"},
         ])},
        {"id": "argue", "label": "Argue", "weight": 1.0, "lean": -1, "tags": ["disagreement"],
         "emotions": {"anger": 1.6, "interest": 1.4, "joy": 0.6},
         "modifiers": {"tension": 0.6},
         "effects": {"tension": 0.12, "agreement": -0.15},
         "items": _items([
             {"id": "debunk", "label": "Debunk or argue the statement", "cue": "disagree",
              "text": "debunks it, arguing the statement point by point"},
             {"id": "online_search", "label": "Online search with searxng (Reddit, Twitter, Facebook groups, message boards)",
              "cue": "disagree", "requires": ["research"],
              "text": "argues back with what people online are saying about it"},
             {"id": "llm_rebuttal", "label": "Response based on online research / LLM query for rebuttal",
              "cue": "disagree", "requires": ["research"],   # [research-pop] it said research and did none
              "text": "rebuts it with the facts as they know them, from what the research turned up"},
         ])},
        {"id": "push_back", "label": "Push back", "weight": 1.0, "lean": -1, "tags": ["disagreement"],
         "emotions": {"interest": 1.4, "anger": 1.3},
         "effects": {"tension": 0.1, "agreement": -0.1},
         "items": _items([
             {"id": "no_bro", "label": "Express that no bro that isn't gonna work", "cue": "disagree",
              "text": "tells them flatly that no, bro, that isn't gonna work"},
             {"id": "you_sure", "label": "You sure about that?", "cue": "question",
              "text": "asks, pointedly, if they are sure about that"},
             {"id": "speakerbox_rebuttal", "label": "Speaker-box quote used in rebuttal, spoken indignantly",
              "cue": "disagree", "requires": ["speakbox"], "speakerbox": "REFERENCE",
              "text": "rebuts it indignantly with a speakerbox quote"},
         ])},
    ],
}

# --- RS2: the blueprint's conversational acts -------------------------------
RS2 = {
    "id": "RS2", "family": "RS", "label": "Response Set 2 (conversational acts)", "version": 1,
    "enabled": True, "weight": 1.0,
    "description": "Supplemental response acts from the System 3 blueprint.",
    "categories": [
        {"id": "supportive", "label": "Supportive", "weight": 1.0, "lean": 1, "tags": ["agreement"],
         "emotions": {"joy": 1.6, "interest": 1.2, "anger": 0.4},
         "modifiers": {"agreement": 0.8, "tension": -0.4},
         "effects": {"agreement": 0.12, "tension": -0.08},
         "items": _items([
             {"id": "agree", "label": "Agree", "cue": "agree", "text": "agrees and adds a reason of their own"},
             {"id": "qualify", "label": "Qualify", "cue": "disagree", "text": "agrees, but qualifies it with a 'but'"},
             {"id": "concede", "label": "Concede", "cue": "concede", "text": "concedes the point out loud"},
             {"id": "synthesize", "label": "Synthesize", "text": "pulls both sides together into one point",
              "phases": ["DEVELOP", "EXPLORE", "RESOLVE", "WRAP"], "resolves": True},
             {"id": "soften", "label": "Soften", "text": "softens it and takes the heat out",
              "effects": {"tension": -0.15}},
             {"id": "answer", "label": "Answer", "text": "answers the question that was put to them"},
         ])},
        {"id": "oppositional", "label": "Oppositional", "weight": 1.0, "lean": -1, "tags": ["disagreement"],
         "emotions": {"anger": 1.6, "disgust": 1.4, "interest": 1.2, "joy": 0.6},
         "modifiers": {"tension": 0.5, "agreement": -0.5},
         "effects": {"tension": 0.12, "agreement": -0.15},
         "items": _items([
             {"id": "disagree", "label": "Disagree", "cue": "disagree", "text": "disagrees, plainly"},
             {"id": "challenge_premise", "label": "Challenge premise", "cue": "disagree",
              "text": "challenges the premise of what was just said"},
             {"id": "reject_premise", "label": "Reject premise", "cue": "disagree",
              "text": "rejects the premise outright"},
             {"id": "correct", "label": "Correct", "cue": "disagree", "text": "corrects a detail they got wrong"},
             {"id": "request_evidence", "label": "Request evidence", "cue": "question",
              "text": "demands evidence for it"},
             {"id": "disbelief", "label": "Disbelief", "cue": "question", "text": "cannot believe it and says so"},
         ])},
        {"id": "playful", "label": "Playful", "weight": 1.0, "after": {'IRS:comedic': 1.3}, "lean": 0, "tags": ["humor"],
         "emotions": {"joy": 1.7, "surprise": 1.2},
         "effects": {"novelty": 0.05},
         "items": _items([
             {"id": "tease", "label": "Tease", "cue": "humor", "text": "teases them about it"},
             {"id": "joke", "label": "Joke", "cue": "humor", "text": "turns it into a joke"},
             {"id": "misunderstand", "label": "Misunderstand", "text": "misunderstands it, badly, and runs with that"},
             {"id": "deflect", "label": "Deflect", "text": "deflects it onto something else"},
         ])},
        {"id": "movement", "label": "Movement", "weight": 0.8, "lean": 0,
         "items": _items([
             {"id": "anecdote", "label": "Anecdote", "text": "answers with a short story of their own",
              "tags": ["tangent"], "callback_source": True},
             {"id": "redirect", "label": "Redirect", "text": "redirects it to a sharper angle", "tags": ["tangent"]},
             {"id": "callback", "label": "Callback", "text": "calls back to something said earlier",
              "requires_state": ["callbacks"], "tags": ["callback"]},
             {"id": "intensify", "label": "Intensify", "text": "takes it further than they did",
              "tags": ["escalation"], "effects": {"tension": 0.1}},
             {"id": "clarify", "label": "Clarify", "cue": "question", "text": "asks what they actually meant"},
         ])},
    ],
}

# --- IRS1: Initiator's Response Set 1 --------------------------------------
#
# "This prevents automatic LLM conciliation unless selected." The initiator
# answers the responders; conceding is one outcome among many, not the
# default a small model drifts to.
IRS1 = {
    "id": "IRS1", "family": "IRS", "label": "Initiator's Response Set 1", "version": 1,
    "enabled": True, "weight": 1.0,
    "description": "How the initiator reacts to the responses (the operator's original list).",
    "categories": [
        {"id": "opposite", "label": "Opposite", "weight": 1.0, "lean": -1, "tags": ["disagreement"],
         "effects": {"tension": 0.1, "agreement": -0.12}, "keeps_unresolved": True,
         "items": _items([{"id": "maintain", "label": "Push back against the responses maintaining the argument position",
                           "cue": "disagree", "text": "pushes back against the responses and holds the argument position"}])},
        {"id": "comedic", "label": "Comedic (making fun of the response)", "weight": 1.0, "after": {'RS:playful': 1.5}, "lean": -1,
         "tags": ["humor"], "emotions": {"joy": 1.6, "disgust": 1.2},
         "effects": {"tension": 0.06}, "keeps_unresolved": True,
         "items": _items([
             {"id": "calling_dumb", "label": "Making fun of the responder: calling them dumb", "cue": "insult",
              "text": "makes fun of the responder, calling them dumb"},
             {"id": "calling_silly", "label": "Calling them silly", "cue": "insult",
              "text": "makes fun of the responder, calling them silly"},
             {"id": "calling_confused", "label": "Calling them confused", "cue": "insult",
              "text": "makes fun of the responder, calling them confused"},
             {"id": "calling_misunderstood", "label": "Calling them misunderstood",
              "text": "makes fun of the responder for completely misunderstanding"},
             {"id": "calling_misinformed", "label": "Calling them misinformed", "cue": "insult",
              "text": "makes fun of the responder, calling them misinformed"},
             # Kept from the operator's list, switched off by default: it is a
             # slur, and a table row is the place to decide that, not code.
             {"id": "calling_slur", "label": "Calling them retarded", "enabled": False,
              "text": "makes fun of the responder with a crude insult"},
         ])},
        {"id": "refutation", "label": "Refutation / Dispute arguing", "weight": 1.0, "lean": -1,
         "tags": ["disagreement"], "modifiers": {"tension": 0.5},
         "effects": {"tension": 0.12, "agreement": -0.12}, "keeps_unresolved": True,
         "items": _items([{"id": "dispute", "label": "Refutation / Dispute arguing", "cue": "disagree",
                           "text": "refutes them and disputes the argument"}])},
        {"id": "expansive", "label": "Expansive (expanding on original point)", "weight": 1.0, "lean": 0,
         "effects": {"novelty": 0.05},
         "items": _items([
             {"id": "more_speakerbox", "label": "More speaker-box", "requires": ["speakbox"],
              "speakerbox": "REFERENCE", "text": "expands the original point with more from the speakerbox"},
             {"id": "more_news", "label": "More of the news story", "requires": ["news"],
              "text": "expands the original point with more of the news story"},
             {"id": "detail", "label": "Going into detail on original point",
              "text": "goes into detail on the original point"},
         ])},
        {"id": "confrontational", "label": "Confrontational", "weight": 1.0, "after": {'RS:argue': 1.6, 'RS:oppositional': 1.4}, "lean": -1,
         "tags": ["disagreement", "escalation"], "emotions": {"anger": 1.8, "disgust": 1.3, "joy": 0.5},
         "modifiers": {"tension": 0.7}, "effects": {"tension": 0.18, "agreement": -0.15},
         "keeps_unresolved": True,
         "items": _items([{"id": "double_down", "label": "Doubling down on original point", "cue": "disagree",
                           "text": "doubles down on the original point"}])},
    ],
}

IRS2 = {
    "id": "IRS2", "family": "IRS", "label": "Initiator's Response Set 2 (pushback acts)", "version": 1,
    "enabled": True, "weight": 0.8,
    "description": "Supplemental initiator reactions from the System 3 blueprint.",
    "categories": [
        {"id": "hold", "label": "Hold", "weight": 1.0, "lean": -1, "tags": ["disagreement"],
         "effects": {"tension": 0.1}, "keeps_unresolved": True,
         "items": _items([
             {"id": "defensive", "label": "Defensive response", "cue": "disagree", "text": "gets defensive about it"},
             {"id": "counter", "label": "Counter", "cue": "disagree", "text": "counters with a point of their own"},
             {"id": "challenge_detail", "label": "Challenge detail", "cue": "question",
              "text": "challenges one specific detail of the response"},
             {"id": "escalate", "label": "Escalate", "cue": "disagree", "tags": ["escalation"],
              "effects": {"tension": 0.2}, "text": "escalates, treating the objection as proof of the point"},
         ])},
        {"id": "yield", "label": "Yield", "weight": 0.8, "after": {'RS:supportive': 1.4, 'RS:argue': 0.6}, "lean": 1, "tags": ["agreement"],
         "modifiers": {"closure_pressure": 0.8, "tension": -0.3},
         "effects": {"tension": -0.15, "agreement": 0.2}, "resolves": True,
         "items": _items([
             {"id": "accept", "label": "Accept", "cue": "agree", "text": "accepts the response"},
             {"id": "concede", "label": "Concede", "cue": "concede", "text": "concedes the point, out loud, and is changed by it"},
             {"id": "retreat", "label": "Retreat", "cue": "concede", "text": "retreats from the original claim"},
         ])},
        {"id": "turn", "label": "Turn", "weight": 1.0, "lean": 0,
         "items": _items([
             {"id": "clarify", "label": "Clarify", "text": "clarifies what they actually meant"},
             {"id": "laugh_off", "label": "Laugh off", "cue": "humor", "text": "laughs it off and moves on",
              "effects": {"tension": -0.1}},
             {"id": "reframe", "label": "Reframe", "text": "reframes the whole thing"},
             {"id": "emotional_transition", "label": "Emotional transition",
              "text": "is visibly moved by the response and changes their tone"},
         ])},
    ],
}

# --- FL1: Frame Response List 1 --------------------------------------------
FL1 = {
    "id": "FL1", "family": "FL", "label": "Frame Response List 1", "version": 1,
    "enabled": True, "weight": 1.0,
    "description": "The frame at the end of each banter cycle: decides whether the topic goes on and who initiates next.",
    "categories": [
        {"id": "reframe", "label": "Reframe", "weight": 1.0, "speaker": "responder",
         "items": _items([{"id": "reframe", "label": "Reframe the situation",
                           "text": "reframes it, explaining the views are those of the initiator and not the studio or everyone involved"}])},
        {"id": "cancel_topic", "label": "Cancel Topic", "weight": 1.0, "speaker": "any",
         "new_topic": True, "min_turns_left": 4, "not_phases": ["WRAP", "SEGUE"], "resolves": True,
         "tags": ["novelty"], "effects": {"tension": -0.15, "novelty": 0.3},
         "items": _items([{"id": "agree_to_disagree", "label": "Agree to disagree and grab a new topic",
                           "cue": "close", "text": "agrees to disagree and moves past the topic to a new one"}])},
        {"id": "acquiesce", "label": "Acquiesce", "weight": 1.0, "speaker": "responder", "resolves": True,
         "effects": {"tension": -0.2, "agreement": 0.25},
         "items": _items([{"id": "concede_move_on", "label": "Give up on topic and concede to the instigator",
                           "cue": "concede", "text": "gives up on the topic, concedes the instigator is right and asks to move on"}])},
        {"id": "anger", "label": "Anger", "weight": 0.7, "after": {'IRS:confrontational': 1.6, 'IRS:hold': 1.2}, "speaker": "any", "new_topic": True,
         "min_turns_left": 4, "not_phases": ["SEGUE"], "tags": ["escalation"],
         "emotions": {"anger": 2.0, "disgust": 1.4, "joy": 0.4},
         "effects": {"tension": 0.25, "energy": 0.15},
         "items": _items([{"id": "parking_lot", "label": "Request to fight outside",
                           "text": "decides the topic is not worth discussing and invites them out to the parking lot for a battle"}])},
        {"id": "enjoyment", "label": "Enjoyment", "weight": 1.0, "after": {'RS:playful': 1.3, 'IRS:comedic': 1.3}, "speaker": "initiator",
         "keep_initiator": True, "effects": {"agreement": 0.1, "energy": 0.1},
         "items": _items([{"id": "go_deeper", "label": "Request to continue in more depth",
                           "cue": "question", "text": "asks to keep going deeper with a follow-up question about the original point"}])},
    ],
}

# --- FL2: flow moves (blueprint section 4) ----------------------------------
FL2 = {
    "id": "FL2", "family": "FL", "label": "Flow / Conversational Movement", "version": 1,
    "enabled": True, "weight": 1.0,
    "description": "Where a response takes the conversation. Increasingly radio-clock aware.",
    "categories": [
        {"id": "stay", "label": "Stay", "weight": 1.2,
         "items": _items([
             {"id": "continue", "label": "Continue", "text": "keeps on the point"},
             {"id": "deepen", "label": "Deepen", "text": "digs one level deeper into it"},
             {"id": "contradiction", "label": "Contradiction", "text": "contradicts something said earlier",
              "tags": ["disagreement"], "effects": {"tension": 0.1}},
             {"id": "unresolved_return", "label": "Unresolved-point return",
              "requires_state": ["unresolved"], "text": "drags the conversation back to the point nobody settled"},
         ])},
        {"id": "wander", "label": "Wander", "weight": 1.0, "tags": ["tangent", "novelty"],
         "phases": ["ESTABLISH", "DEVELOP", "EXPLORE", "WILDCARD"], "min_turns_left": 3,
         "modifiers": {"closure_pressure": -1.5, "topic_exhaustion": 0.8},
         "effects": {"novelty": 0.2},
         "items": _items([
             {"id": "broaden", "label": "Broaden", "text": "widens it out to the bigger picture"},
             {"id": "tangent", "label": "Tangent", "text": "goes off on a tangent"},
             {"id": "anecdotal_reframe", "label": "Anecdotal reframe", "text": "reframes it through a story",
              "callback_source": True},
             {"id": "bridge", "label": "Bridge", "text": "bridges it to something related"},
         ])},
        {"id": "heat", "label": "Heat", "weight": 1.0,
         "items": _items([
             {"id": "escalation", "label": "Escalation", "tags": ["escalation"],
              "not_phases": ["WRAP", "SEGUE"], "modifiers": {"tension": 0.6},
              "effects": {"tension": 0.2}, "text": "turns the heat up"},
             {"id": "de_escalation", "label": "De-escalation", "modifiers": {"tension": 1.2},
              "effects": {"tension": -0.2}, "text": "takes the heat back out"},
             {"id": "callback", "label": "Callback", "requires_state": ["callbacks"], "tags": ["callback"],
              "text": "calls back to something from earlier"},
         ])},
        {"id": "land", "label": "Land", "weight": 0.6, "tags": ["closure"], "closes": True,
         "phases": ["RESOLVE", "WRAP", "SEGUE"], "max_turns_left": 1,
         "modifiers": {"closure_pressure": 2.5},
         "items": _items([
             {"id": "closure", "label": "Closure", "cue": "close", "text": "brings it to a close", "resolves": True},
             {"id": "final_callback", "label": "Final callback", "requires_state": ["callbacks"],
              "tags": ["callback"], "text": "lands it on a callback to the top of the conversation"},
             {"id": "segue", "label": "Segue", "cue": "close", "max_turns_left": 0,
              "text": "segues out, back to the music"},
         ])},
    ],
}

# --- TEMPER1 / SHOCK1 / INTERJECT1: the station's prompt randoms, as tables ---
#
# [s3-rounds] 2026-09-27. Four draws lived in dj_banter's one-call prompt as
# station-side random(): the hosts' tempers for the round (dice_hosts, one
# of HOST_TEMPERS per seat), "at least once X is openly <shocked> at what the
# other has JUST said", the interjections forced in edgewise while one of them
# goes on a roll (the desk's diatribe_interjections), and whether the
# station's name is worked in (30%). Each contradicted the per-turn ES the
# running order carried and none was in the Rolodex. They are System 3 rolls
# now, on the round's own stream (seed|round), recorded, replayable and
# editable here. The desk's dice_hosts switch still gates TEMPER; the odds of
# the other three are controls (shock_beat, interjections, mention).
TEMPER1 = {
    "id": "TEMPER1", "family": "TEMPER", "label": "Tempers (the round's register per seat)",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "The temper a host is caught in tonight, rolled once per round per seat when the desk's "
                   "dice_hosts switch is on. It colours phrasing and pacing underneath each turn's rolled feeling.",
    "categories": [
        {"id": "temper", "label": "Temper", "weight": 1.0,
         "items": _items([
             {"id": "short_fused", "label": "Short-fused", "text": "angry and short-fused, snapping at things that would normally slide"},
             {"id": "openly_sad", "label": "Openly sad", "text": "openly sad tonight, and it keeps leaking into the jokes"},
             {"id": "appalled", "label": "Appalled", "text": "appalled - genuinely scandalised by what they are hearing"},
             {"id": "giddy", "label": "Giddy", "text": "giddy and overcaffeinated, talking too fast and laughing too easily"},
             {"id": "deadly_serious", "label": "Deadly serious", "text": "deadly serious, refusing to let the other one turn it into a bit"},
             {"id": "bored", "label": "Bored", "text": "bored to the back teeth and barely hiding it"},
             {"id": "wounded", "label": "Wounded", "text": "wounded and a bit defensive, taking things personally"},
             {"id": "smug", "label": "Smug", "text": "smug, insufferably pleased with themselves"},
             {"id": "conspiratorial", "label": "Conspiratorial", "text": "conspiratorial, dropping to a mutter like the mic is off"},
             {"id": "tender", "label": "Tender", "text": "tender and unusually gentle, which the other finds suspicious"},
             {"id": "combative", "label": "Combative", "text": "punchy and combative, spoiling for an argument about anything"},
             {"id": "distracted", "label": "Distracted", "text": "distracted, half-somewhere-else, coming back mid-sentence"},
         ])},
    ],
}

SHOCK1 = {
    "id": "SHOCK1", "family": "SHOCK", "label": "The shock beat (one open reaction that turns the round)",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "Once in a round, one speaker is openly taken aback by what the other has JUST said, says so, "
                   "and the rest of the exchange is driven by it. Whether (the shock_beat control), which reaction, "
                   "and on which turn are three recorded draws.",
    "categories": [
        {"id": "reaction", "label": "Reaction", "weight": 1.0,
         "items": _items([
             {"id": "shocked", "label": "Shocked", "text": "shocked"},
             {"id": "surprised", "label": "Surprised", "text": "surprised"},
             {"id": "furious", "label": "Furious", "text": "furious"},
             {"id": "in_disbelief", "label": "In disbelief", "text": "in disbelief"},
             {"id": "delighted", "label": "Delighted", "text": "delighted"},
             {"id": "appalled", "label": "Appalled", "text": "appalled"},
         ])},
    ],
}

INTERJECT1 = {
    "id": "INTERJECT1", "family": "INTERJECT", "label": "Interjections forced in edgewise",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "When one host goes on a roll, the other gets a word in edgewise. The desk's own "
                   "diatribe_interjections list is the Rolodex when it has entries; these are the fallback. "
                   "Three are drawn per hit, no repeats.",
    "categories": [
        {"id": "edgewise", "label": "Edgewise", "weight": 1.0,
         "items": _items([
             {"id": "oh_come_on", "label": "Oh come on", "text": "Oh, come on."},
             {"id": "no", "label": "No", "text": "No."},
             {"id": "what", "label": "What", "text": "What?"},
             {"id": "stop", "label": "Stop", "text": "Stop."},
             {"id": "here_we_go", "label": "Here we go", "text": "Here we go."},
             {"id": "says_you", "label": "Says you", "text": "Says you."},
             {"id": "wow", "label": "Wow", "text": "Wow."},
             {"id": "right", "label": "Right", "text": "Right."},
         ])},
    ],
}

# --- FAV1 / DIRECTIVE1: the cast's favourites and the operator's directives ---
#
# [s3-cast] 2026-09-27. Two things reached every host prompt as a wedge -
# "LIVE MIND ADJUSTMENTS FOR THIS CHARACTER" (app.py mind_adjustment_prompt):
# the Mind desk's hand-written notes, and every line the operator thumbed up,
# stapled on with "say things like it, and you may repeat it". No roll, no
# odds, no Rolodex record, and an invitation to repeat. They are tables now.
#
# FAV1 is the whole cast's liked lines in one pool (a thumbs-up adds a row, a
# thumbs-down removes it). One roll per round or single line at the
# `favorites` control decides whether one comes up; a second draws which (a
# line that just came up weighs a quarter); a third lands it on one host turn,
# where the writer is told to say something NEW in its spirit - never to
# repeat or quote it. A written turn that copies it fails validation.
#
# DIRECTIVE1 holds the operator's directives, one category per seat (and
# "cast" for every host seat). Each row carries its own odds: 1.0 is a
# standing rule (recorded, not drawn), 0.3 comes up three rounds in ten. A
# hit lands on ONE of that seat's turns. A row may expire: `until` (epoch
# seconds, 0 = never) or `airings` (hits on air, 0 = unlimited).
FAV1 = {
    "id": "FAV1", "family": "FAV", "label": "Favourites (lines the operator liked)", "version": 1,
    "enabled": True, "weight": 1.0,
    "description": "Every line the operator thumbed up, from any seat. The favorites control sets how often one "
                   "comes up; the writer is told to say something new in its spirit, never to repeat it.",
    "categories": [{"id": "liked", "label": "Liked lines", "weight": 1.0, "items": []}],
}

DIRECTIVE1 = {
    "id": "DIRECTIVE1", "family": "DIRECTIVE", "label": "Directives (the operator's, per seat)", "version": 1,
    "enabled": True, "weight": 1.0,
    "description": "The operator's directives for the cast. Each row has its own odds (100% is a standing rule) "
                   "and lands on one of its seat's turns; a row may expire by date or by airings.",
    "categories": [
        {"id": "host", "label": "Host", "seat": "A", "weight": 1.0, "items": []},
        {"id": "cohost", "label": "Co-host", "seat": "B", "weight": 1.0, "items": []},
        {"id": "third", "label": "Third seat", "seat": "D", "weight": 1.0, "items": []},
        {"id": "cast", "label": "Whole cast", "seat": "*", "weight": 1.0, "items": []},
    ],
}

# --- CALLEVENT1: what can happen on a call ----------------------------------
#
# [s3-events] 2026-09-27, the operator: "I want to see people get emotional
# randomly, excited, win prizes, get angry, deal with messages from upstairs,
# lose the call, go on a tangent from the speakerbox ... customers get
# interrupted by random background activities and I want that ... as a thing
# that can happen to end the call." Each category is one KIND of happening:
# its own odds per call (a die), the seat it happens to (the caller, a host,
# anyone), where in the call it may land, and whether it ENDS the call - the
# plan is then cut on that turn and a host reacts to the dead line. A hit
# draws one of its items (the variant) and a turn. At most `max_events`
# land on one call. Text: {caller}/{first} the caller's first name, {host},
# {cohost}. Prizes and the hostile turn are the station's own call rolls
# (richer: paintings, tickets, a seven-beat arc) - tabled through the dice
# door, not repeated here.
CALLEVENT1 = {
    "id": "CALLEVENT1", "family": "EVENT", "label": "Call events (what can happen on a call)", "version": 1,
    "enabled": True, "weight": 1.0, "roads": ["caller"], "max_events": 2,
    "description": "Things that happen on a request-line call. Each kind has its own odds per call; a hit lands "
                   "on one turn of its seat, and an ending cuts the call there.",
    "categories": [
        {"id": "outburst", "label": "The caller gets emotional", "odds": 0.3, "seat": "caller", "place": "any",
         "items": _items([
             {"id": "tears", "label": "Breaks down",
              "text": "{first} breaks down partway through - voice cracking - it matters far more to them than they let on",
              "emotions": {"sadness": 4.0}},
             {"id": "temper", "label": "Loses their temper",
              "text": "{first} suddenly loses their temper over something small the hosts just said",
              "emotions": {"anger": 4.0}},
             {"id": "giddy", "label": "Giddy",
              "text": "{first} gets giddy and overexcited, talking over the hosts and laughing at their own story",
              "emotions": {"joy": 4.0}},
             {"id": "panic", "label": "Panics",
              "text": "{first} gets flustered and frightened, as though someone might be listening in on the call",
              "emotions": {"fear": 3.5}},
         ])},
        {"id": "upstairs", "label": "A message from upstairs", "odds": 0.15, "seat": "host", "place": "any",
         "items": _items([
             {"id": "intercom", "label": "The intercom",
              "text": "is interrupted by the manager upstairs coming over the intercom with an opinion about this very call, and has to relay it to {first}",
              "emotions": {"surprise": 2.0, "social": 1.5}},
             {"id": "note", "label": "A note under the door",
              "text": "reads out a note just slid under the booth door from the manager upstairs, about this caller",
              "emotions": {"surprise": 2.0}},
         ])},
        {"id": "tangent", "label": "The caller goes off on a tangent", "odds": 0.15, "seat": "caller", "place": "any",
         "requires": ["call_passage"],
         "items": _items([
             {"id": "passage", "label": "Into the speakerbox passage",
              "text": "{first} wanders off onto the speakerbox passage this call carries, as if it were their own life, and has to be dragged back",
              "emotions": {"interest": 2.5}},
         ])},
        {"id": "background", "label": "Something happens in the background", "odds": 0.2, "seat": "caller",
         "place": "any",
         "items": _items([
             {"id": "dog", "label": "The dog", "text": "a dog starts going off behind {first}; they shout at it and carry on"},
             {"id": "kettle", "label": "The kettle", "text": "a kettle screams behind {first}, and they talk over it"},
             {"id": "someone", "label": "Someone in the room",
              "text": "someone in the room with {first} keeps chiming in, and {first} answers them as well as the hosts"},
         ])},
        {"id": "pulled_away", "label": "Pulled away by the background (ends the call)", "odds": 0.1, "seat": "caller",
         "place": "any", "min_turn": 6, "ends": True,
         "items": _items([
             {"id": "baby", "label": "The baby",
              "text": "a baby starts screaming behind {first}; they say they have to go and the line drops mid-sentence"},
             {"id": "door", "label": "Someone at the door",
              "text": "someone starts hammering on {first}'s door; they panic, say they have to go, and the line cuts out"},
             {"id": "boss", "label": "The boss walks in",
              "text": "{first}'s boss walks in on them; they hang up in a hurry, mid-word"},
             {"id": "pot", "label": "Something boiling over",
              "text": "something boils over on {first}'s stove, there is a crash, and the line goes dead"},
             {"id": "fire_alarm", "label": "The smoke alarm",
              "text": "a smoke alarm goes off behind {first}; they yell and the call drops"},
         ])},
        {"id": "lost", "label": "The call is lost", "odds": 0.07, "seat": "caller", "place": "any", "min_turn": 6, "ends": True,
         "items": _items([
             {"id": "tunnel", "label": "Into a tunnel", "text": "{first} drives into a tunnel and breaks up, then the line goes dead"},
             {"id": "battery", "label": "The battery dies", "text": "{first}'s phone battery dies in the middle of a sentence"},
             {"id": "crossed", "label": "A crossed line",
              "text": "the line crosses with a stranger's call for a moment, then {first} is gone"},
         ])},
        {"id": "hangs_up", "label": "The caller hangs up", "odds": 0.05, "seat": "caller", "place": "any", "min_turn": 6, "ends": True,
         "items": _items([
             {"id": "huff", "label": "In a huff", "text": "{first} takes offence at the last thing said and hangs up on them",
              "emotions": {"anger": 3.0}},
         ])},
    ],
}

# --- SBEND1: prepend or append, when both win --------------------------------
#
# [s3-sb-end] 2026-09-28, the operator: "a roulette between either append or
# prepend if they both happen to have won in the roulette. So instead of both
# winning together, they now have a roulette that is part of the system. A
# speakerbox 'prepend/append' roulette." A marked line still rolls its own dice
# against the prepend and the append sliders; only when BOTH win does this table
# pick the one that is read, by these weights, and the other is withdrawn. With
# the table switched off (or deleted) both are read, as before.
SBEND1 = {
    "id": "SBEND1", "family": "SPEAKERBOX", "label": "Speakerbox: prepend or append (when both win)", "version": 1,
    "enabled": True, "weight": 1.0,
    "description": "When a line's prepend and append both win their dice, this roulette picks the one that is read; "
                   "the other is withdrawn and the Rolodex says why. Re-weight a row to favour it; switch the table "
                   "off and both are read.",
    "categories": [{"id": "end", "label": "Where the passage goes", "weight": 1.0, "items": _items([
        {"id": "prepend", "label": "Prepend", "text": "the passage is read before the line"},
        {"id": "append", "label": "Append", "text": "the passage is read after the line"},
    ])}],
}

# --- STATION1 / POOLS1: the station's own rolls, tabled ------------------------
#
# [s3-dice-door] 2026-09-27, the operator: "all of the requests for randomness
# on the station to be broken down and tabled and made into a roulette rolodex
# entry that dice is rolling a chance of hitting". Every `random()` the station
# rolls on the air's behalf goes through System 3's dice door: a CHANCE row
# (STATION1, one per roll: its odds - or the desk dial it follows - and what it
# does) and, where it picks among options, a POOL category (POOLS1: the options
# themselves, weighted and editable). Rows are added the first time the station
# makes the roll, carrying the station's own odds and options, so nothing starts
# anywhere but where it was; from then on the desk's numbers are rolled.
STATION1 = {
    "id": "STATION1", "family": "CHANCE", "label": "Station rolls (every chance the station takes)", "version": 1,
    "enabled": True, "weight": 1.0,
    "description": "Each row is one roll a station road makes - a caller preferring a host, a prize, a hostile turn, "
                   "a second person on the line ... Its odds are the dice's; a row that follows a desk dial says so.",
    "categories": [],
}
POOLS1 = {
    "id": "POOLS1", "family": "POOL", "label": "Station pools (the options those rolls draw from)", "version": 1,
    "enabled": True, "weight": 1.0,
    "description": "Each category is one list a station roll draws from - a caller's state, the prizes, how a call "
                   "turns. Add, remove, re-weight or switch off options; the roll draws from what is here.",
    "categories": [],
}

# --- BLOCKS: every block a writer prompt may carry ---------------------------------
#
# [s3-blocks] 2026-09-27, the operator: every block in every prompt is a node -
# "fixed context (persona, day, schedule, show memory, avoid-reruns) OBLIGATIONS,
# always sent, each switchable"; the station's randoms ROLLS; a block no node
# claims STRIPPED and logged. The station marks each block of a prompt with its
# name; System 3 decides it at the writer's door by the rule here (the config's
# `blocks` section overrides any of them). kind:
#   obligation  always sent, recorded; switch it off with kind "off"
#   roll        a die at `odds` (or the desk dial named in `odds_from`)
#   tint        only while a crystal is on and the tint pass is wanted
#   off         never sent (recorded as stripped)
# A block whose name is not here is a wedge and is stripped.
DEFAULT_BLOCKS = {
    "system_prompt": {"kind": "obligation", "label": "The station's system prompt", "helper": "active_system"},
    "persona": {"kind": "obligation", "label": "The seat's persona", "helper": "radio_persona"},
    "desk_instruction": {"kind": "obligation", "label": "The desk's instruction for this slot",
                         "helper": "radio_prompt_instruction"},
    "schedule": {"kind": "obligation", "label": "SCHEDULE (#843): the entry on air", "helper": "_schedule_clause"},
    "plot": {"kind": "obligation", "label": "The storyline's act", "helper": "plot_clause"},
    "modifiers": {"kind": "obligation", "label": "Standing guest / topic / event", "helper": "modifiers_clause"},
    "lessons": {"kind": "obligation", "label": "The operator's standing orders", "helper": "operator_lesson_clause"},
    "manager_cut_in": {"kind": "off", "label": "The manager cutting in (the station's old roll)",
                       "helper": "manager_cut_in_clause",
                       "what": "System 3's EVENT tables and the station rolls carry upstairs now"},
    "battle": {"kind": "tint", "label": "THE BATTLE (#1090)", "helper": "rap_battle_clause"},
    # its gate is the station roll banter.personality / line.personality (STATION1, at
    # the personality dial) - the block itself is not rolled a second time
    "disposition": {"kind": "obligation", "label": "The station's disposition", "helper": "dj_disposition"},
    "flavor": {"kind": "obligation", "label": "Loose in your mind (a stray speakerbox swath)", "helper": "speakbox_flavor"},
    "day": {"kind": "obligation", "label": "The day, the date, the part of the day", "helper": "day_context"},
    "accent": {"kind": "obligation", "label": "The accent directive", "helper": "accent_directive"},
    "context": {"kind": "obligation", "label": "The record's facts", "helper": "dj_line context"},
    "aside": {"kind": "obligation", "label": "A speakerbox passage to work in", "helper": "speakbox_aside"},
    # [s3-memory] on a round a MEMORY roll stands behind, show_memory carries only the
    # memory block below - exactly the items the roll drew (nothing drawn: nothing sent).
    # The old "Tonight so far" digest rides only a prompt no MEMORY roll stands behind:
    # System 3 off, a road it did not plan, the MEMORY table switched off.
    "show_memory": {"kind": "obligation", "label": "Tonight so far (show memory) - on a System 3 round, only the memory block",
                    "helper": "show_memory"},
    "memory": {"kind": "obligation", "label": "What the writer is reminded of (the MEMORY roll's items)",
               "helper": "system3_memory_block",
               "what": "exactly the items the MEMORY roll drew: each kind's rule decides whether it is relevant, "
                       "the roulette which of the relevant ones are sent"},
    "avoid_reruns": {"kind": "obligation", "label": "Words and lines not to repeat", "helper": "avoid_reruns"},
    "crystal": {"kind": "tint", "label": "The crystal's lines", "helper": "crystal_tint_note / crystal_clause"},
    "paper": {"kind": "obligation", "label": "The Gazette's discussion", "helper": "paper_discussion_context"},
    "cohost": {"kind": "obligation", "label": "The co-host's persona", "helper": "radio_persona('cohost')"},
    "third": {"kind": "obligation", "label": "The third seat's persona", "helper": "radio_persona('third')"},
    "turn_rules": {"kind": "obligation", "label": "How long a turn is (System 2's slot)", "helper": "system2_turn_instruction"},
    "pace": {"kind": "obligation", "label": "Overlap and pace", "helper": "banter_pace"},
    "seat_away": {"kind": "obligation", "label": "The empty chair", "helper": "seat_away_clause"},
    "playing": {"kind": "obligation", "label": "What is playing", "helper": "playing / only_song"},
    "call_flow": {"kind": "obligation", "label": "The call's flow and novelty", "helper": "call_flow"},
    "approach": {"kind": "off", "label": "The station's approach roll (#752)", "helper": "approach_clause",
                 "what": "FL frames the round under System 3"},
    "weather": {"kind": "off", "label": "The station's emotional weather roll", "helper": "weather_clause",
                "what": "ES rolls the feeling of every turn under System 3"},
    "tail_lists": {"kind": "obligation", "label": "Requests and pictures on the desk", "helper": "tail_lists_clause"},
    "sheet": {"kind": "obligation", "label": "System 3's running order", "helper": "the S3 sheet"},
    "angle": {"kind": "obligation", "label": "The round's own subject and material (its angle)", "helper": "dj_banter angle"},
    "theme": {"kind": "obligation", "label": "The operator's theme", "helper": "theme_air_clause"},
    "brief_lesson": {"kind": "obligation", "label": "The lesson from the last attempt", "helper": "brief_lesson_clause"},
    "heat": {"kind": "obligation", "label": "A machine-heat aside", "helper": "heat_reference"},
    "topic_contract": {"kind": "obligation", "label": "The subject the caller rang about", "helper": "topic_contract_clause"},
    "perf": {"kind": "obligation", "label": "How to say it (performance)", "helper": "perf_directive"},
    "review_guidance": {"kind": "obligation", "label": "Operator wording preferences", "helper": "line_review_guidance"},
}


def default_blocks():
    return copy.deepcopy(DEFAULT_BLOCKS)


# families whose tables may stand empty: their rows are added from the desk,
# by the operator's votes or by the station's first roll; an empty pool draws nothing
POOL_FAMILIES = ("FAV", "DIRECTIVE", "CHANCE", "POOL")

DEFAULT_TABLES = [CTS1, ES1, RS1, RS2, IRS1, IRS2, FL1, FL2, TEMPER1, SHOCK1, INTERJECT1, FAV1, DIRECTIVE1, CALLEVENT1,
                  STATION1, POOLS1, SBEND1]

# --- MEMORY1: what the writer is reminded of - rules, then roulette -------------------
#
# [s3-memory] 2026-09-28, the operator's guide: memory context is given ONLY WHEN
# RELEVANT - the clock, a synopsis of the last topic, the last segment and how it
# went, the callers this hour against the quota, a synopsis of the manager's last
# message. Asked how: "Rules, then roulette." Each category is one kind of memory.
# Its `rule` holds the numbers (minutes, margins) and switches that decide whether
# it is relevant to the round being planned right now - a kind that is not is
# recorded with why - and the roulette then draws among the relevant ones by
# weight: at least `least`, at most `most` a round (how many is itself a die when
# the two differ). An item is one way of putting that memory to the writer:
# `when` names the state of the rule it fits (the top of the hour, a subject
# carried on or turned from, behind or ahead of the quota ...) and a die picks
# among the items that fit. {words} in its text are the station's facts. The
# items drawn reach the writer as ONE prompt block ("memory") and nothing else of
# the old "Tonight so far" rides a round a MEMORY roll stands behind. A round
# written now to air later (banked) is told none of it unless a rule's
# `on_banked` switch says otherwise: by the time it is heard, it would be stale.
# A kind may be kept to some roads (`roads` on its category; none = every road).
MEMORY1 = {
    "id": "MEMORY1", "family": "MEMORY", "label": "Memory context (what the writer is reminded of)",
    "version": 1, "enabled": True, "weight": 1.0, "least": 1, "most": 2,
    "description": "What the writer is reminded of, only when it is relevant. Each kind's rule decides whether it "
                   "is eligible for the round being planned (its numbers are below); the roulette then draws among "
                   "the eligible kinds - at least `least`, at most `most` a round - and the items drawn are the "
                   "round's memory block, word for word.",
    "categories": [
        {"id": "clock", "label": "The clock", "weight": 1.0,
         "rule": {"before_top": 5, "after_top": 3, "segment_left": 2, "on_banked": False},
         "items": _items([
             {"id": "top", "label": "The top of the hour is near", "when": "top",
              "text": "it is {clock}, {to_top} to the top of the hour"},
             {"id": "past", "label": "The hour has just turned", "when": "past",
              "text": "it is {clock} - the {hour} hour has only just begun"},
             {"id": "segment_end", "label": "The segment is nearly up", "when": "segment",
              "text": "it is {clock}, and {segment} has about {segment_left} left to run"},
         ])},
        {"id": "last_topic", "label": "The last topic", "weight": 1.0,
         "rule": {"within_minutes": 30, "continues_overlap": 2, "continues": True, "contrasts": True,
                  "on_banked": False},
         "items": _items([
             {"id": "carry_on", "label": "This round carries it on", "when": "continues",
              "text": "this carries on from the last subject on air - {synopsis}"},
             {"id": "turn_away", "label": "This round turns away from it", "when": "contrasts",
              "text": "the last subject on air was {synopsis} - this round is on something else, and they can "
                      "say as much as they turn to it"},
         ])},
        {"id": "last_segment", "label": "The last segment and how it went", "weight": 1.0,
         "rule": {"within_minutes": 15, "first_minutes": 4, "rough_share": 0.34, "smooth": True, "rough": True,
                  "on_banked": False},
         "items": _items([
             {"id": "went_off", "label": "It went off as planned", "when": "smooth",
              "text": "the segment before this one, {segment}, went off as planned - {went}"},
             {"id": "went_wrong", "label": "It did not go to plan", "when": "rough",
              "text": "the segment before this one, {segment}, did not go to plan - {went}"},
         ])},
        {"id": "callers_quota", "label": "Callers this hour against the quota", "weight": 1.0,
         "rule": {"after_minutes": 15, "margin": 1, "behind": True, "ahead": True, "on_banked": False},
         "items": _items([
             {"id": "behind", "label": "Behind - and it shows", "when": "behind",
              "text": "the phones: {calls} in the last hour against {quota} an hour - they are behind on callers "
                      "and it is starting to show"},
             {"id": "behind_plea", "label": "Behind - the line needs ringing", "when": "behind",
              "text": "the phones: {calls} in the last hour against {quota} an hour - the request line needs "
                      "ringing, and they can say so"},
             {"id": "ahead", "label": "Ahead of it", "when": "ahead",
              "text": "the phones: {hour_calls} since the top of the hour against {quota} an hour - the callers are "
                      "ahead of the quota tonight"},
         ])},
        {"id": "manager_note", "label": "The manager's last word", "weight": 1.0,
         "rule": {"within_minutes": 20, "on_banked": False},
         "items": _items([
             {"id": "word", "label": "His last word", "when": "fresh",
              "text": "the manager's last word from upstairs, {ago} ago: {said}"},
             {"id": "hanging", "label": "Still hanging over the booth", "when": "fresh",
              "text": "the manager's last word from upstairs ({ago} ago) is still hanging over the booth: {said}"},
         ])},
    ],
}
DEFAULT_TABLES.append(MEMORY1)          # [s3-memory] added to a stored config once (add_missing_default_tables)


# --- [s3-callend] HOW A CALL ENDS: RESOLVE1 (the caller's wheel) and WRAP1 -----------
#
# 2026-09-28, the operator: "a resolution node with an RNG for setting up how a phone
# call is wrapped up ... customers roll a wheel for how their call is ended. If the
# last segment was selling a painting than in the roulette we want to offer options
# for the caller ... these should have a response chain that follows + a rebuttal
# from the caller before the call ends by somone one the station ending the call in
# response to the customer "wrap call" roulette node".
#
# The call's end is five legs of the caller structure (CALLEND_LEGS, each with an
# `end` role): the RESOLUTION (a station seat sets it up - the offer, the raffle, the
# price - and the caller plays it out on the REACTION), the RESPONSE CHAIN (one or
# two station turns: how many and who answers are rolled), the caller's REBUTTAL
# (their last word, second to last) and WRAP CALL (who on the station ends the call
# and how, rolled). Every roll draws on its own stream and is a recorded node.
#
# RESOLVE1 - the caller's wheel. A category is eligible by what is in play:
# `requires` / `unless` name it ("painting" = the last segment sold a painting,
# within the category's `within` seconds). An item's `offer` is what the station
# seat does to set it up (a category may carry a default), `text` what the caller
# does, `respond` what the response chain answers, `rebuttal` the caller's last
# word; `effect` is what the outcome does to the gallery when the call airs (sold /
# awarded / burnt take the painting off the pile; unsold leaves it for sale);
# `raffle` rolls the caller number (low..high); `speakerbox` has the caller say a
# passage out of the speakerbox word for word (the station's own rotation picks the
# document); `prize` draws from the station's own prize list (POOLS1 call.prizes,
# or the list that roll starts from until it is tabled). The table's `responses`
# weighs the chain's length and `responders` who answers (A the host, B the
# co-host, D the third seat, S Sam - a seat only a call that carries his has).
# Text: {first}/{FIRST} the caller, {painting} the piece, {price}, {terms} (the
# offer's terms, "first caller takes it"), {number} the raffle's caller number,
# {prize} the prize.
#
# WRAP1 - who ends the call (`who`, weighted by seat) and how. `ends` is how a call
# that ran its course is wrapped; `dead_line` a call a CALLEVENT1 ending cut short
# (the line lost, the caller pulled away) - a host reacting to the dead line. An
# item's `polite` says whether it is a spoken goodbye (the station's checker keys on
# the planned WRAP node, not on the words); `only_after` ties it to resolutions
# ("RESOLVE:<item>" or "tag:<tag>") and `after` weighs it by them; `rebuttal` is
# what it does to the caller's last word (cut off mid-word).
CALLEND_FAMILIES = ("RESOLVE", "WRAP")
CALLEND_ROLES = ("resolution", "reaction", "response", "rebuttal", "wrap")
# the station's own prize list - the options dj_call_generated's prize roll (the dice
# door's call.prizes) starts from; the desk's POOLS1 call.prizes list governs once tabled
CALL_PRIZES = (
    "the station's second-best microphone",
    "a year of the station's coffee, which has been cancelled",
    "a tour of the building, conducted by whoever is free",
    "the pick of whatever is in the prize cupboard, sight unseen",
    "a signed photograph of the two of them, unsigned as yet",
)
RESOLVE1 = {
    "id": "RESOLVE1", "family": "RESOLVE", "label": "Resolution (the caller's wheel: how the call resolves)",
    "version": 1, "enabled": True, "weight": 1.0, "roads": ["caller"],
    "responses": {"1": 2.0, "2": 1.0},
    "responders": {"A": 1.0, "B": 1.0, "D": 0.6, "S": 0.8},
    "description": "The wheel the caller rolls at the end of a call: how it resolves. The painting wheel only when "
                   "the last segment sold a painting (within `within` seconds), the general wheel otherwise. A "
                   "station seat sets it up (offer), the caller plays it out (text), then the response chain "
                   "(`responses` weighs how many station turns, `responders` who), the caller's rebuttal and the "
                   "wrap call. {first} is the caller; {painting}, {price}, {terms}, {number} and {prize} come "
                   "from the roll.",
    "categories": [
        {"id": "painting", "label": "The painting the last segment was selling", "weight": 1.0,
         "requires": ["painting"], "within": 1200,
         "offer": "offers {first} the painting the last segment was selling - {painting} - at {price}",
         "items": _items([
             {"id": "buys", "label": "Buys the painting", "tags": ["sale"], "effect": "sold",
              "text": "{FIRST} BUYS IT - takes it at {price}, and says where it is going to hang",
              "respond": "is delighted to have sold it, and says so to the listeners",
              "emotions": {"joy": 2.5}},
             {"id": "raffle", "label": "Wins it in the raffle, as caller number [RNG]", "tags": ["won", "raffle"],
              "effect": "awarded", "raffle": {"low": 2, "high": 99},
              "offer": "announces that {first} is caller number {number} - the station's raffle number - and has "
                       "WON the painting the last segment was selling, {painting}, outright",
              "text": "{FIRST} reacts to winning it as caller number {number}",
              "respond": "makes far too much of the win, and of caller number {number}",
              "emotions": {"joy": 3.0, "surprise": 2.0}},
             {"id": "rejects", "label": "Is offered it, and rejects it", "tags": ["refused"], "effect": "unsold",
              "text": "{FIRST} TURNS IT DOWN - flat, and says why",
              "respond": "takes the rejection personally, and defends the painting"},
             {"id": "rejects_quote", "label": "Is offered it, and rejects it by saying [RNG] [speakerbox]",
              "tags": ["refused", "quote"], "effect": "unsold", "speakerbox": "verbatim",
              "text": "{FIRST} TURNS IT DOWN BY SAYING a passage out of the speakerbox, rolled for them, word for "
                      "word as their whole answer",
              "respond": "tries to work out what that answer meant, and whether it was a no"},
             {"id": "buys_burns", "label": "Buys it, then decides to set it on fire", "tags": ["sale", "fire"],
              "effect": "burnt",
              "text": "{FIRST} BUYS IT at {price} - and then says they are setting it on fire, right now, while "
                      "they are still on the line",
              "respond": "reacts to {first} setting the painting on fire, live on the phone",
              "emotions": {"joy": 1.5, "anger": 1.5}},
             {"id": "ignores", "label": "Ignores it, and says they don't want it", "tags": ["refused"],
              "effect": "unsold",
              "offer": "tries to interest {first} in the painting the last segment was selling - {painting} - at "
                       "{price}",
              "text": "{FIRST} IGNORES THE PITCH ENTIRELY and just says they do not want it",
              "respond": "cannot believe the pitch was ignored"},
             {"id": "short", "label": "Buys it, but hasn't enough money", "tags": ["short"], "effect": "unsold",
              "text": "{FIRST} WANTS IT and tries to buy it - and does not have the money: comes up short, and "
                      "says exactly how short",
              "respond": "tries to haggle, or does the sums out loud",
              "emotions": {"sadness": 1.8}},
         ])},
        {"id": "general", "label": "Any call (no painting in play)", "weight": 1.0, "unless": ["painting"],
         "items": _items([
             {"id": "gets_it", "label": "Gets what they rang for", "tags": ["granted"],
              "offer": "gives {first} what they rang for - the record, the answer, the thing they asked for",
              "text": "{FIRST} takes it, and says what it means to them"},
             {"id": "agree_to_disagree", "label": "Agrees to disagree", "tags": ["disagree"],
              "offer": "makes one last case against {first}'s point",
              "text": "{FIRST} AGREES TO DISAGREE - holds their ground, and says so"},
             {"id": "look_into_it", "label": "The hosts promise to look into it", "tags": ["promise"],
              "offer": "promises {first}, out loud and with a time attached, that the station will look into it",
              "text": "{FIRST} holds them to it"},
             {"id": "dedication", "label": "A song dedicated", "tags": ["dedication"],
              "offer": "offers {first} a dedication - the next record, for whoever they like",
              "text": "{FIRST} names who it is for, and why"},
             {"id": "prize", "label": "Wins one of the station's prizes", "tags": ["won", "prize"],
              "prize": {"pool": "call.prizes", "defaults": list(CALL_PRIZES)},
              "offer": "tells {first} they have won {prize} - one of the station's prizes",
              "text": "{FIRST} reacts to winning {prize}",
              "emotions": {"joy": 2.0, "surprise": 1.5}},
             {"id": "comes_round", "label": "Comes round to the hosts' view", "tags": ["agree"],
              "offer": "makes the case to {first} one more time, properly",
              "text": "{FIRST} COMES ROUND - admits the hosts have a point"},
             {"id": "trivia", "label": "A trivia question before they go", "tags": ["trivia"],
              "offer": "puts a trivia question to {first} - something absurd about this station, this town or "
                       "the last record",
              "text": "{FIRST} answers it, right or gloriously wrong"},
             {"id": "honorary", "label": "Made an honorary member of the station", "tags": ["honour"],
              "offer": "makes {first} an honorary something of the station on the spot, and invents the title",
              "text": "{FIRST} accepts the honour extremely seriously, with a short speech"},
         ])},
    ],
}
WRAP1 = {
    "id": "WRAP1", "family": "WRAP", "label": "Wrap call (who on the station ends it, and how)", "version": 1,
    "enabled": True, "weight": 1.0, "roads": ["caller"],
    "who": {"A": 1.0, "B": 1.0, "D": 0.6, "S": 0.8},
    "description": "The last turn of a call: who on the station ends it (`who`, weighted by seat - A the host, B "
                   "the co-host, D the third seat, S Sam where the call has his seat) and how, in answer to the "
                   "caller's last word. It need not be a polite goodbye: the station's checker keys on this node, "
                   "not on the words. `dead_line` is for a call a CALLEVENT1 ending cut short. `only_after` ties a "
                   "way of ending to a resolution (RESOLVE:<item> or tag:<tag>).",
    "categories": [
        {"id": "ends", "label": "How the station ends the call", "weight": 1.0, "unless": ["dead_line"],
         "items": _items([
             {"id": "thanks_hangs_up", "label": "Thanks them and hangs up", "polite": True, "weight": 1.5,
              "text": "thanks {first} for calling - properly, out loud - and hangs up"},
             {"id": "goodnight", "label": "Wishes them goodnight", "polite": True,
              "text": "wishes {first} a good night, warmly, and lets them go"},
             {"id": "cuts_off", "label": "Cuts them off mid-sentence",
              "rebuttal": "they never get to finish it - the next turn cuts them off mid-word",
              "text": "cuts {first} off mid-sentence - hits the button while they are still going, and says so to "
                      "the listeners"},
             {"id": "hold_forever", "label": "Puts them on hold forever",
              "text": "puts {first} on hold - forever - and goes straight on to something else; the hold music is "
                      "the last anyone hears of them"},
             {"id": "dial_tone", "label": "That's the dial tone",
              "text": "hangs up on {first} mid-thought, and tells the listeners that sound was the dial tone"},
             {"id": "next_caller", "label": "Next caller!",
              "text": "shouts 'next caller' while {first} is still talking, and moves on"},
             {"id": "over_the_record", "label": "Talks over them into the record",
              "text": "talks straight over {first} into the next record"},
             {"id": "enjoy_the_ashes", "label": "Tells them to enjoy the ashes", "weight": 3.0,
              "only_after": ["tag:fire"],
              "text": "tells {first} to enjoy the ashes, and hangs up"},
             {"id": "enjoy_the_painting", "label": "Tells them to enjoy the painting", "polite": True, "weight": 2.0,
              "only_after": ["RESOLVE:buys", "RESOLVE:raffle"],
              "text": "tells {first} to enjoy the painting and to hang it where the light is kind to it, then "
                      "thanks them and lets them go"},
             {"id": "call_back_with_money", "label": "Call back when you have the money", "weight": 3.0,
              "only_after": ["RESOLVE:short"],
              "text": "tells {first} to call back when they have the money, and hangs up on them"},
             {"id": "offer_stands", "label": "The offer stands", "weight": 1.5, "only_after": ["tag:refused"],
              "text": "tells {first} the offer stands, forever, and hangs up before they can refuse it again"},
         ])},
        {"id": "dead_line", "label": "The line went dead (a CALLEVENT1 ending)", "weight": 1.0,
         "requires": ["dead_line"],
         "items": _items([
             {"id": "hello_hello", "label": "Hello? Hello?",
              "text": "says hello into the dead line two or three times, then gives up on {first}"},
             {"id": "phone_company", "label": "Blames the phone company",
              "text": "blames the phone company, the weather and the building for losing {first}"},
             {"id": "defends_self", "label": "Defends themselves to the empty line",
              "text": "defends themselves to the empty line, as though {first} could still hear it"},
             {"id": "hopes_ok", "label": "Hopes they are all right",
              "text": "wonders out loud whether {first} is all right, and means it"},
             {"id": "moves_on", "label": "Shrugs it off",
              "text": "shrugs it off and takes it straight back to the music"},
         ])},
    ],
}
DEFAULT_TABLES += [RESOLVE1, WRAP1]                                              # [s3-callend]

# --- [s3-callarc] THE CALL AS RADIO: ITS ARC, ITS DETOUR, ITS RESULT -------------------
#
# 2026-10-01, the operator: "whenever they call the calls need to have a resolution or
# an escalation or an argument or a confrontation and then lead to a result. Like they
# win a prize, like they get one of the paintings and are enthusiastic about it ...
# trigger the manager to say something, or say something about the manager or his
# message or have something to say about the news. Customers should call in and talk
# about one thing and then change topics to talk about another thing ... a roulette to
# roll for a topic change ... 80% they should change topic and subsequent rolls should
# have a graduating chance of rolling a change to say something to drive the customer
# back on topic and if the roll fails the customer goes even further into their tangent."
#
# CALLARC1 - the shape of the call's middle, one roll per call. The category is the arc;
# its `beats` are the legs it plays between the caller's second detail and the result
# (C the caller, A the host, B the co-host - a call with no co-host gives B's beats to A).
# Every arc opens and closes on the caller, so the topic detour fits after its first beat
# and the result's station seat answers its last. The item is the arc's temperature, said
# on every beat as `{tone}`. {topic} is what they rang about.
CALLARC1 = {
    "id": "CALLARC1", "family": "CALLARC", "label": "Call arc (the shape of the call's middle)", "version": 1,
    "enabled": True, "weight": 1.0, "roads": ["caller"],
    "description": "Rolled once per call: how its middle plays out between the caller's story and the result. "
                   "The category is the arc and its `beats` are the turns it plays (C caller, A host, B co-host); "
                   "the item is the temperature, said on every beat as {tone}. {topic} is what they rang about.",
    "categories": [
        {"id": "resolution", "label": "Resolution - they work it out", "weight": 1.0,
         "beats": [
             {"id": "arc_problem", "seat": "C", "label": "Lays out the problem",
              "act": "{FIRST} LAYS OUT EXACTLY WHAT IS WRONG about {topic} - the real problem, specifically ({tone})."},
             {"id": "arc_works", "seat": "A", "label": "Works it with them",
              "act": "WORKS THE PROBLEM WITH {FIRST}: one practical idea, said plainly ({tone})."},
             {"id": "arc_settles", "seat": "C", "label": "It settles",
              "act": "{FIRST} TAKES THE IDEA AND IT SETTLES - says what they will do now ({tone})."}],
         "items": _items([
             {"id": "warm", "label": "Warm", "tone": "warm, and a little relieved"},
             {"id": "practical", "label": "Practical", "tone": "brisk and practical"},
             {"id": "sheepish", "label": "Sheepish", "tone": "sheepish - they knew the answer all along"}])},
        {"id": "escalation", "label": "Escalation - it gets worse", "weight": 1.0,
         "beats": [
             {"id": "arc_raises", "seat": "C", "label": "Raises the stakes",
              "act": "{FIRST} RAISES THE STAKES on {topic}: it is worse than they first said, and here is how ({tone})."},
             {"id": "arc_fuels", "seat": "B", "label": "Says the wrong thing",
              "act": "SAYS THE ONE THING THAT MAKES IT WORSE - an aside that lands badly ({tone})."},
             {"id": "arc_boils", "seat": "C", "label": "Boils over",
              "act": "{FIRST} BOILS OVER - louder, faster, and the real grievance under all of it comes out ({tone})."}],
         "items": _items([
             {"id": "slow_burn", "label": "Slow burn", "tone": "a slow burn that finally catches"},
             {"id": "hot", "label": "Hot from the start", "tone": "hot from the first word"},
             {"id": "comic", "label": "Comic", "tone": "comically out of proportion"}])},
        {"id": "argument", "label": "Argument - they disagree", "weight": 1.0,
         "beats": [
             {"id": "arc_claim", "seat": "C", "label": "Makes a claim",
              "act": "{FIRST} MAKES A CLAIM about {topic} and stands on it ({tone})."},
             {"id": "arc_push", "seat": "A", "label": "Pushes back",
              "act": "PUSHES BACK on that exact claim with a counter of your own ({tone})."},
             {"id": "arc_digs", "seat": "C", "label": "Digs in",
              "act": "{FIRST} DIGS IN - says it again, harder, with a new reason ({tone})."},
             {"id": "arc_counter", "seat": "B", "label": "Joins the fight",
              "act": "JOINS THE ARGUMENT - takes a side, and it may not be the host's ({tone})."},
             {"id": "arc_holds", "seat": "C", "label": "Holds the line",
              "act": "{FIRST} HOLDS THE LINE - or gives one inch and makes a show of it ({tone})."}],
         "items": _items([
             {"id": "civil", "label": "Civil", "tone": "civil, but neither will give"},
             {"id": "petty", "label": "Petty", "tone": "petty, over something small"},
             {"id": "heated", "label": "Heated", "tone": "heated, talking over each other"}])},
        {"id": "confrontation", "label": "Confrontation - they come for the station", "weight": 0.8,
         "beats": [
             {"id": "arc_accuses", "seat": "C", "label": "Accuses the station",
              "act": "{FIRST} ACCUSES THE STATION - or one of you by name - of something specific about {topic} ({tone})."},
             {"id": "arc_deflects", "seat": "A", "label": "Deflects",
              "act": "DENIES IT OR DEFLECTS, badly ({tone})."},
             {"id": "arc_corners", "seat": "C", "label": "Corners them",
              "act": "{FIRST} CORNERS YOU with a detail you cannot dodge ({tone})."},
             {"id": "arc_owns", "seat": "B", "label": "Faces it",
              "act": "FACES IT - owns it, or fires straight back ({tone})."},
             {"id": "arc_demands", "seat": "C", "label": "Makes a demand",
              "act": "{FIRST} MAKES A DEMAND - what they want done about it, now ({tone})."}],
         "items": _items([
             {"id": "icy", "label": "Icy", "tone": "icy and precise"},
             {"id": "furious", "label": "Furious", "tone": "furious"},
             {"id": "wounded", "label": "Wounded", "tone": "wounded - they expected better of you"}])},
    ],
}

# CALLSHIFT1 - the caller's detour. `first_odds` is the chance a call changes topic at
# all; after it does, each steer-back roll comes up `back_start` + `back_step` x (the
# number of rolls before it) - a GRADUATING chance - and a roll that misses sends the
# caller further down the tangent, at most `most` times. The category is where the new
# subject comes from: the station's real material where it is in play (`requires`:
# memo - the manager's latest memo, news - a headline, gallery - a painting on the
# wall's unsold pile, passage - the call's own speakerbox passage) or the caller's own
# life; the item is the bridge they cross it on, said as {bridge}. {subject} is the new
# subject, {topic} what they rang about.
CALLSHIFT1 = {
    "id": "CALLSHIFT1", "family": "CALLSHIFT", "label": "Call detour (the caller changes the subject)",
    "version": 1, "enabled": True, "weight": 1.0, "roads": ["caller"],
    "first_odds": 0.8, "back_start": 0.35, "back_step": 0.2, "most": 3,
    "description": "Whether the caller changes the subject (first_odds), where the new subject comes from (the "
                   "category - the manager's memo, the news, the gallery, the call's passage or their own life) "
                   "and the bridge they cross it on (the item). After a detour, each steer-back roll's chance "
                   "rises by back_step from back_start; a miss takes the caller further off topic, at most `most` "
                   "times.",
    "categories": [
        {"id": "memo", "label": "The manager's latest memo", "weight": 1.2, "requires": ["memo"], "source": "memo",
         "items": _items([
             {"id": "speaking_of", "label": "Speaking of which", "bridge": "\"speaking of which - that memo\""},
             {"id": "heard_upstairs", "label": "I heard what upstairs said", "bridge": "\"and while I've got you, I heard what your boss put out\""}])},
        {"id": "news", "label": "Something in the news", "weight": 1.0, "requires": ["news"], "source": "news",
         "items": _items([
             {"id": "did_you_see", "label": "Did you see", "bridge": "\"did you see the news, though?\""},
             {"id": "reminds_me", "label": "That reminds me", "bridge": "\"that reminds me of this thing I read\""}])},
        {"id": "gallery", "label": "A painting on the wall", "weight": 0.8, "requires": ["gallery"], "source": "gallery",
         "items": _items([
             {"id": "that_painting", "label": "About that painting", "bridge": "\"totally unrelated - that painting you've been on about\""}])},
        {"id": "passage", "label": "The call's own passage", "weight": 0.6, "requires": ["passage"], "source": "passage",
         "items": _items([
             {"id": "read_this", "label": "I read this thing", "bridge": "\"okay, I have to tell you what I read\""}])},
        {"id": "life", "label": "Their own life", "weight": 1.0, "source": "life",
         "items": _items([
             {"id": "neighbour", "label": "The neighbour", "bridge": "\"oh - and my neighbour\"", "subject": "their neighbour, who has done something"},
             {"id": "car", "label": "The car", "bridge": "\"which, by the way, my car\"", "subject": "what is wrong with their car"},
             {"id": "cousin", "label": "The cousin", "bridge": "\"this is like my cousin\"", "subject": "a cousin with a scheme"},
             {"id": "job", "label": "Work", "bridge": "\"you know what this is like? my job\"", "subject": "their boss at work"}])},
    ],
}

# RESOLVE2 - the station's own business as the caller's result: the manager cuts into the
# call in his own voice (seat E, his latest memo in hand), the caller has their say on
# that memo or on the news, or wins a painting off the unsold pile. A second table so a
# stored RESOLVE1 is left as the operator edited it; the wheel rolls across both by
# weight. requires: memo - a memo on the book, news - a headline, unsold - a painting on
# the pile. {memo}, {news} and {unsold} are those; {manager} his name.
RESOLVE2 = {
    "id": "RESOLVE2", "family": "RESOLVE", "label": "Resolution (the station's business: the manager, the news, the pile)",
    "version": 1, "enabled": True, "weight": 1.0, "roads": ["caller"],
    "responses": {"1": 2.0, "2": 1.0},
    "responders": {"A": 1.0, "B": 1.0, "D": 0.6, "S": 0.8},
    "description": "Results that come out of what the station is doing: the manager cutting into the call in his "
                   "own voice (seat E) with his latest memo, the caller's say on that memo or on the news, a "
                   "painting off the unsold pile won outright. Rolled with RESOLVE1 by weight.",
    "categories": [
        {"id": "manager", "label": "The manager cuts into the call", "weight": 1.0, "requires": ["memo"],
         "seat_in": "E", "offer": "hears the line click - the manager is on it",
         "items": _items([
             {"id": "scolds", "label": "He scolds the caller", "tags": ["manager"],
              "manager": "{MANAGER} CUTS INTO THE CALL in his own voice and SCOLDS {first} - by the book, quoting his own memo: {memo}",
              "text": "{FIRST} ANSWERS THE MANAGER BACK, directly",
              "respond": "tries to smooth it over with the manager still on the line",
              "emotions": {"surprise": 2.0, "anger": 1.2}},
             {"id": "sides", "label": "He sides with the caller", "tags": ["manager"],
              "manager": "{MANAGER} CUTS INTO THE CALL in his own voice and SIDES WITH {first} against the booth, waving his memo: {memo}",
              "text": "{FIRST} IS DELIGHTED to have the boss on their side, and rubs it in",
              "respond": "cannot believe the manager took the caller's side",
              "emotions": {"joy": 2.0, "surprise": 1.5}},
             {"id": "offers", "label": "He offers the caller something", "tags": ["manager", "won"],
              "prize": {"pool": "call.prizes", "defaults": list(CALL_PRIZES)},
              "manager": "{MANAGER} CUTS INTO THE CALL in his own voice and, grudgingly, OFFERS {first} {prize} - as long as they stop mentioning the memo: {memo}",
              "text": "{FIRST} TAKES {prize}, and mentions the memo anyway",
              "respond": "makes the most of the manager giving something away",
              "emotions": {"joy": 2.2}}])},
        {"id": "memo_remark", "label": "The caller's say on the manager's memo", "weight": 0.8, "requires": ["memo"],
         "offer": "asks {first} what they made of the manager's latest memo",
         "items": _items([
             {"id": "mocks", "label": "Mocks the memo", "tags": ["memo"],
              "text": "{FIRST} TAKES THE MEMO APART, line by line: {memo}", "respond": "cannot defend it"},
             {"id": "agrees", "label": "Agrees with the memo", "tags": ["memo"],
              "text": "{FIRST} AGREES WITH THE MANAGER, to the hosts' horror: {memo}", "respond": "is betrayed"},
             {"id": "demands_read", "label": "Demands it be read out", "tags": ["memo"],
              "text": "{FIRST} DEMANDS THE MEMO BE READ OUT, and reacts to every line of it: {memo}",
              "respond": "reads one more line of it than they should"}])},
        {"id": "news_remark", "label": "The caller's take on the news", "weight": 0.8, "requires": ["news"],
         "offer": "asks {first} what they make of the news",
         "items": _items([
             {"id": "hot_take", "label": "A hot take", "tags": ["news"],
              "text": "{FIRST} GIVES A HOT TAKE on the news - {news} - and will not be moved"},
             {"id": "conspiracy", "label": "A theory", "tags": ["news"],
              "text": "{FIRST} HAS A THEORY about the news - {news} - and it connects to the station somehow"},
             {"id": "personal", "label": "It happened to them", "tags": ["news"],
              "text": "{FIRST} SAYS THE NEWS HAPPENED TO THEM - {news} - and tells you how"}])},
        {"id": "unsold", "label": "A painting off the unsold pile", "weight": 1.0, "requires": ["unsold"],
         "offer": "tells {first} they have WON one of the paintings off the unsold pile - {unsold}",
         "items": _items([
             {"id": "wins_painting", "label": "Wins a painting, thrilled", "tags": ["won", "painting"],
              "effect": "awarded",
              "text": "{FIRST} IS THRILLED - genuinely, wildly enthusiastic about winning {unsold}, and says where it will hang",
              "respond": "is moved by how much {first} wanted it",
              "emotions": {"joy": 3.0, "surprise": 2.0}},
             {"id": "wins_wrong", "label": "Wins it, wanted the other one", "tags": ["won", "painting"],
              "effect": "awarded",
              "text": "{FIRST} IS THRILLED, then asks whether they could have the OTHER one instead",
              "respond": "explains that is not how winning works",
              "emotions": {"joy": 2.0}}])},
    ],
}
DEFAULT_TABLES += [CALLARC1, CALLSHIFT1, RESOLVE2]                                # [s3-callarc]
CALLARC_FAMILIES = ("CALLARC", "CALLSHIFT")

# The call's end as the caller structure's closing legs (DEFAULT_CALL_STRUCTURE ends on
# them; the runtime puts them on a stored structure that still ends on lands/sign_off,
# once). {resolution}, {offer}, {outcome}, {respond}, {rebuttal}, {wrapper} and {wrap}
# are filled from the rolls. With the tables switched off the resolution, reaction and
# response legs are not planned, the rebuttal lands the caller's story and the wrap
# call is a spoken sign-off - the call the station planned before (same dice).
CALLEND_LEGS = [
    {"id": "resolution", "label": "Resolution - the caller's wheel", "place": "close", "seat": "A",
     "end": "resolution",
     "act": "THE RESOLUTION, as the caller's wheel rolled it ({resolution}): {offer}.",
     "draws": [{"family": "RESOLVE"}, {"family": "ES"}]},
    {"id": "reaction", "label": "The caller plays it out", "place": "close", "seat": "C", "end": "reaction",
     "act": "{outcome}.",
     "draws": [{"family": "ES"}]},
    {"id": "response", "label": "Response chain", "place": "close", "seat": "A", "end": "response",
     "act": "RESPONDS to how it went ({resolution}): {respond}.",
     "draws": [{"family": "ES"}, {"family": "RS"}]},
    {"id": "rebuttal", "label": "The caller's rebuttal", "place": "close", "seat": "C", "end": "rebuttal",
     "act": "{FIRST} GETS THE LAST WORD: {rebuttal}. This must be the SECOND TO LAST turn of the whole call.",
     "draws": [{"family": "ES"}]},
    {"id": "wrap_call", "label": "Wrap call", "place": "close", "seat": "A", "end": "wrap",
     "act": "WRAP CALL - {wrapper} ENDS THE CALL, in answer to {first}'s last word: {wrap}. This is the LAST "
            "turn of the call.",
     "draws": [{"family": "WRAP"}, {"family": "ES"}]},
]

# --- IL1: the Insertion list - how the next voice takes over a long read -------
#
# [s3-split] 2026-09-28. When a long read on a node with `splits` ticked (the
# produced advert, the manager's page, a speaker-box monologue) is shared out
# by the SPLIT node's roulette, each voice that takes over draws here HOW:
# the category is the way they take over (its `direction` is how it is
# played), the item is what they say on the way in - short, spoken, then the
# read carries straight on. {prev} is the name of the one who was reading,
# {name} the one taking over. Editable in the Tables tab like any table.
IL1 = {
    "id": "IL1", "family": "IL", "label": "Insertion list (how the next voice takes over a long read)",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "When a long read is split, whoever the roulette picks to carry it on draws here how they take "
                   "over: the way (the category, with how it is played) and the few words they say on the way in "
                   "before the read continues. {prev} is the one who was reading, {name} the one taking over.",
    "categories": [
        {"id": "grabs_sheet", "label": "Grabs the sheet and reads on", "weight": 1.2,
         "direction": "takes the page out of the other's hands and carries straight on without missing a beat",
         "items": _items([
             {"id": "give_me_that", "label": "Give me that", "text": "Give me that."},
             {"id": "hand_it_over", "label": "Hand it over", "text": "Hand it over, {prev}."},
             {"id": "my_turn", "label": "My turn", "text": "My turn."},
             {"id": "let_me_have_it", "label": "Let me have it", "text": "Here, let me have it."},
         ])},
        {"id": "finishes_sentence", "label": "Finishes their sentence for them", "weight": 1.0,
         "direction": "jumps in on the other's breath, as if they were always going to say the next bit",
         "items": _items([
             {"id": "and_what", "label": "What they mean is", "text": "What {prev} is trying to say is this."},
             {"id": "as_they_were_saying", "label": "As they were about to say", "text": "As {prev} was about to say:"},
             {"id": "which_brings_us", "label": "Which brings us to", "text": "Which brings us to this."},
         ])},
        {"id": "cuts_in", "label": "Cuts in, impatient", "weight": 0.9,
         "direction": "impatient, talking over the tail of the last line to get on with it",
         "items": _items([
             {"id": "just_let_me", "label": "Just let me read it", "text": "Oh, just let me read it."},
             {"id": "all_night", "label": "We'll be here all night", "text": "We'll be here all night. Faster."},
             {"id": "come_on", "label": "Come on", "text": "Come on, come on."},
         ])},
        {"id": "picks_up", "label": "Picks up where they trailed off", "weight": 1.0,
         "direction": "gently picks up the thread where the other voice trailed off",
         "items": _items([
             {"id": "picking_up", "label": "Picking it up from there", "text": "Picking it up from there."},
             {"id": "where_were_we", "label": "Where were we", "text": "Where were we? Right."},
             {"id": "carrying_on", "label": "Carrying on", "text": "Carrying on."},
         ])},
        {"id": "polite", "label": "Takes over politely", "weight": 1.0,
         "direction": "a polite relay handover, warm and unhurried",
         "items": _items([
             {"id": "if_i_may", "label": "If I may", "text": "If I may."},
             {"id": "allow_me", "label": "Allow me", "text": "Allow me."},
             {"id": "from_here", "label": "I'll take it from here", "text": "Thank you, {prev}. I'll take it from here."},
         ])},
        {"id": "heckles", "label": "Heckles, then continues", "weight": 0.7,
         "direction": "a jab at the one who was reading, then reads on straight-faced",
         "items": _items([
             {"id": "mumbling", "label": "You're mumbling", "text": "You're mumbling, {prev}. Give it here."},
             {"id": "nobody_hears", "label": "Nobody can hear you", "text": "Nobody can hear you. Listen."},
             {"id": "my_voice", "label": "Better in my voice", "text": "Sounds better in my voice anyway."},
         ])},
    ],
}
DEFAULT_TABLES.append(IL1)                                                   # [s3-split]

# --- The banter cycle (PDF p.3) --------------------------------------------
#
# Initial Statement [CTS1] -> Response A [ES1, RS1] -> Response B [ES1, RS1]
# -> Initiator's Response [ES1, RS1, IRS1] -> Response A -> Response B ->
# Frame [FL1] -> hand off the initiator role -> loop for the segment
# duration. "I don't mean the dialogue loops. I mean the structure for how
# banter is constructed." The prepend/append marks are the ones drawn on
# p.7; they are data, editable in the structure view ("allow me to mark
# lines for prepend / append speakerbox insertions").
DEFAULT_STRUCTURE = {
    "id": "banter_cycle", "label": "[Banter]", "version": 1,
    "steps": [
        {"id": "initial", "label": "Initial Statement", "speaker": "initiator",
         "draws": [{"family": "CTS"}, {"family": "ES"}], "speakerbox": ["prepend", "append"],
         # [s3-split] a speaker-box monologue read on this step is shared out when it runs long
         "splits": True, "max_splits": 3},
        {"id": "response_a", "label": "Response A", "speaker": "responder_a",
         "draws": [{"family": "ES"}, {"family": "RS"}, {"family": "FL", "tables": ["FL2"]}]},
        {"id": "response_b", "label": "Response B", "speaker": "responder_b", "optional": True,
         "draws": [{"family": "ES"}, {"family": "RS"}]},
        {"id": "initiator_response", "label": "Initiator's Response", "speaker": "initiator",
         "draws": [{"family": "ES"}, {"family": "RS"}, {"family": "IRS"}],
         "speakerbox": ["prepend", "append"]},
        {"id": "response_a2", "label": "Response A", "speaker": "responder_a",
         "draws": [{"family": "ES"}, {"family": "RS"}, {"family": "FL", "tables": ["FL2"]}]},
        {"id": "response_b2", "label": "Response B", "speaker": "responder_b", "optional": True,
         "draws": [{"family": "ES"}, {"family": "RS"}]},
        {"id": "frame", "label": "Frame", "speaker": "frame",
         "draws": [{"family": "ES"}, {"family": "FL", "tables": ["FL1"]}],
         "speakerbox": ["prepend", "append"]},
    ],
    # The closing turn of the scene: whoever's turn it is lands it.
    "closing": {"id": "closing", "label": "Closing", "draws": [
        {"family": "ES"}, {"family": "FL", "tables": ["FL2"], "closes": True}]},
    "handoff": True,
}


# [s3-calls] THE REQUEST-LINE CALL AS SYSTEM 3 NODES. Each leg is one leg of
# call_flow_report, in the order the checker reads them, written as the turn
# that satisfies it (the words #1392's call_beat_sheet gave the writer). A
# leg's `place` is open (the fixed opening), middle (repeated until the turn
# budget is met, seats alternating back from the landing so a host always
# speaks before it) or close. {FIRST}/{first} is the caller's first name.
# Every leg rolls ES; the legs the protocol leaves open roll RS and FL too.
DEFAULT_CALL_STRUCTURE = {
    "id": "call_protocol", "label": "[Request-line call]", "version": 1, "kind": "protocol",
    "min_turns": 9, "max_turns": 22, "caller_share": 0.38,
    "legs": [
        {"id": "answer", "label": "Answer the line", "place": "open", "seat": "A",
         "act": "ANSWER THE RINGING LINE. Say the word \"line\" or \"call\" out loud - \"the request line is "
                "ringing, you're live, go ahead\". You do NOT know who this is: do not say any name.",
         "draws": [{"family": "ES"}]},
        {"id": "introduce", "label": "The caller introduces themself", "place": "open", "seat": "C",
         "act": "{FIRST} INTRODUCES THEMSELF and nothing more. Say \"I'm {first}\" or \"{first} here\". "
                "Under thirty words. Do NOT start the story yet.",
         "draws": [{"family": "ES"}]},
        {"id": "greet", "label": "Greet them by name", "place": "open", "seat": "A",
         "act": "GREET THEM BY NAME. Say \"{first}\" out loud, then ask the first question.",
         "draws": [{"family": "ES"}]},
        {"id": "detail_1", "label": "The first detail", "place": "open", "seat": "C",
         "act": "answers, and gives one CONCRETE detail - a thing, a place, a number, a name.",
         "draws": [{"family": "ES"}, {"family": "RS"}]},
        {"id": "ask_1", "label": "Ask about it", "place": "open", "seat": "A",
         "act": "ASK ABOUT THAT EXACT DETAIL. Repeat the caller's own word back inside your question. "
                "This is the one the check counts; a general question does not count.",
         "draws": [{"family": "ES"}, {"family": "RS"}]},
        {"id": "detail_2", "label": "The second detail", "place": "open", "seat": "C",
         "act": "answers it, and gives a second concrete detail.",
         "draws": [{"family": "ES"}, {"family": "RS"}]},
        {"id": "ask_2", "label": "Ask about the second", "place": "open", "seat": "B",
         "act": "ASK ABOUT THAT SECOND DETAIL, using the caller's own word again. Two of these are required.",
         "draws": [{"family": "ES"}, {"family": "RS"}]},
        {"id": "keeps_going", "label": "Keeps it going", "place": "middle", "seat": "alternate",
         "act": "keeps it going; every turn answers the one before it and quotes a word from it.",
         "draws": [{"family": "ES"}, {"family": "RS"}, {"family": "FL", "tables": ["FL2"]}]},
        # [s3-callend] the call's end: resolution, reaction, response chain, rebuttal, wrap call
        *copy.deepcopy(CALLEND_LEGS),
    ],
    "head": "THE RUNNING ORDER OF THIS CALL. This is a request-line call and it has a protocol; write "
            "exactly these turns, in this order, one line each, nothing else. {first} has about "
            "{caller_turns} of the turns.",
    "material": "--  SOMEWHERE IN THE MIDDLE, one of you must bring up this, in your own words, and "
                "{first} must react to it: {passage}",
    "tail": "Every one of those is checked after you write it, and a call that misses one is thrown "
            "away unheard - so the two questions that repeat the caller's own words, the caller speaking "
            "second to last, and the spoken sign-off on the last turn are not style notes. They are the call.",
}
# --- [s3-roads] EVERY ROAD ON THE STATION, AS SYSTEM 3 KNOWS IT --------------
#
# Operator, 2026-09-27: "Nothing is outside of system 3. It takes over
# everything." "Every segment should be comprised of nodes going through the
# rolodex made in a way that can be customized, expanded and altered." "I
# don't want any wedges outside of dictating dialogue. It needs to all be
# part of the RNG system with full accountability to its origin. There
# aren't intended to be any exceptions to that."
#
# Every road that puts words on air is on this register, and every one is
# built from System 3's own nodes: its structure below (or the banter cycle),
# rolled through the Rolodex, editable. `writer` names the station code that
# writes the road and `hook` the System 3 door it goes through, so a line's
# origin is a fact on the ledger, not a guess. A road that stands aside
# (mode off, or a planner fault) airs the station's own words and is
# labelled "not directed by System 3" wherever it shows.
ROAD_REGISTER = [
    {"id": "banter", "label": "Banter", "shape": "cycle",
     "writer": "dj_banter", "hook": "system3_direct_banter",
     "what": "the booth two-hander: the banter cycle, the initiator role handed on"},
    {"id": "caller", "label": "Request-line call", "shape": "legs",
     "writer": "dj_banter (caller_name)", "hook": "system3_direct_banter",
     "what": "a call: the protocol as legs, every leg rolled"},
    {"id": "recap", "label": "Recap on the hour", "shape": "legs",
     "writer": "dj_recap_round -> dj_banter", "hook": "system3_direct_banter",
     "what": "the hour recapped from the station's own log"},
    {"id": "ad", "label": "Sponsor spot", "shape": "legs",
     "writer": "dj_service_ad / dj_engineering_ad -> dj_banter", "hook": "system3_direct_banter",
     "what": "a spot the two of them sell together"},
    {"id": "news", "label": "News", "shape": "legs",
     "writer": "_news_once -> dj_banter", "hook": "system3_direct_banter",
     "what": "a bulletin, or one stretch of the news segment, off the wire"},
    {"id": "manager", "label": "Upstairs", "shape": "legs",
     "writer": "dj_upstairs_page / _manager_rings_booth / dj_manager_call -> dj_banter",
     "hook": "system3_direct_banter",
     "what": "the pair dealing with the manager: a page over the intercom, the internal line, the boss in the booth"},
    {"id": "memo", "label": "Memo from upstairs", "shape": "legs",
     "writer": "dj_manager_note -> dj_banter (whole)", "hook": "system3_direct_banter",
     "what": "a memo read out on air and taken personally"},
    {"id": "gallery", "label": "Gallery", "shape": "legs",
     "writer": "dj_gallery_round / dj_reanalysis_round / dj_hawk_round -> dj_banter",
     "hook": "system3_direct_banter",
     "what": "a painting: the gallery round, a re-analysis, a sale to a buyer on the line"},
    {"id": "mixtape", "label": "MX mixtape", "shape": "legs",
     "writer": "dj_mixtape_intro / dj_mixtape_outro -> dj_banter", "hook": "system3_direct_banter",
     "what": "an MX tape opened, or seen off"},
    {"id": "open_show", "label": "Opening the session", "shape": "legs",
     "writer": "dj_open_show -> dj_banter", "hook": "system3_direct_banter",
     "what": "the welcome, and the hand to the first record"},
    {"id": "fan_mail", "label": "Fan mail", "shape": "legs",
     "writer": "dj_fan_mail -> dj_banter", "hook": "system3_direct_banter",
     "what": "a letter opened and read out on air"},
    {"id": "guest", "label": "Guest send-off", "shape": "legs",
     "writer": "dj_guest_send_home -> dj_banter", "hook": "system3_direct_banter",
     "what": "the studio guest sent home"},
    {"id": "sfxguy", "label": "The SFX Guy's mouth", "shape": "node",
     "writer": "speak_turns / _sfx_cadence_additions_inner -> sfxguy_line",
     "hook": "system3_sfxguy_direction / system3_sfxguy_chooser",
     "what": "his line between statements: a node on every host turn - whether he pipes up, what kind "
             "of line, and which one; every number System 3's"},
    {"id": "track_talk", "label": "Record talk", "shape": "line",
     "writer": "track_talk_write", "hook": "system3_direct_line",
     "what": "a record's intro or send-off, one voice: one leg, the feeling rolled, the words written to it"},
    {"id": "station_id", "label": "Station ID", "shape": "line",
     "writer": "prep_station_id (drop_liner)", "hook": "system3_direct_line",
     "what": "a bumper in the SFX Guy's voice: one leg, the feeling rolled"},
    {"id": "upstairs", "label": "The manager's own page", "shape": "line",
     "writer": "dj_upstairs_write", "hook": "system3_direct_line",
     "what": "the manager paging the booth in his own voice: one leg, the feeling rolled"},
    {"id": "interject", "label": "Stock interjections", "shape": "line",
     "writer": "dj_speak(interject): MANAGER_BREAK_LINES; the cadence's COMPLAINT_LINES",
     "hook": "system3_direct_line (LINE draw over the list)",
     "what": "a fixed line off a list: the memo announcement, a complaint about a clip - the list is the "
             "Rolodex, the pick is a recorded draw"},
    # [s3-lines] the single lines dj_speak still spoke outside any road: under the
    # strict gate they were withheld; now each is a road with a node
    {"id": "reply", "label": "Reply", "shape": "line",
     "writer": "dj_speak(reply): an answer to a listener's or the operator's message",
     "hook": "system3_direct_line (one leg, ES rolled)",
     "what": "one voice answers the message in front of it, in the feeling rolled"},
    {"id": "request", "label": "Request line", "shape": "line",
     "writer": "dj_speak(request): the request line acknowledged",
     "hook": "system3_direct_line (one leg, ES rolled)",
     "what": "one voice takes the request and says what happens to it"},
    {"id": "open", "label": "Show open", "shape": "line",
     "writer": "dj_speak(open): the show opened",
     "hook": "system3_direct_line (one leg, ES rolled)",
     "what": "one voice opens the show: the name, the hour, what is coming"},
    {"id": "aside", "label": "Aside", "shape": "line",
     "writer": "dj_speak(aside): a remark between things",
     "hook": "system3_direct_line (one leg, ES rolled)",
     "what": "one voice, one remark between two things, in the feeling rolled"},
    {"id": "ad_spot", "label": "Produced advert", "shape": "line",
     "writer": "dj_ad_break: ad_pick", "hook": "system3_direct_line (LINE draw over the book)",
     "what": "a stored or produced spot: the ad book's rows are the Rolodex, the pick is a recorded draw"},
    # [h3-speak] the words the people in the hourly H3 video say
    {"id": "h3_speak", "label": "H3 video dialogue (H3SPEAK)", "shape": "node",
     "writer": "h3_hourly_render -> h3_speak_gather / h3_speak_take (app.py)",
     "hook": "the dice door: POOLS1 h3.speak_lean / h3.speak_count / h3.speak_forced; "
             "picks h3.speak_line / h3.speak_sentences / h3.speak_doc",
     "what": "the hourly H3 video's spoken line: a line or monologue a person was heard saying on air "
             "(leaned on by its feeling), then 1-3 whole sentences of it that fit the clip - a Speakerbox "
             "document when no aired line passes, the FORCED line when nothing does"},
]
ROAD_IDS = tuple(r["id"] for r in ROAD_REGISTER)


def _legs_structure(road, label, min_turns, max_turns, legs, head_what, alternate=None, topics=False):
    return {
        "id": "%s_legs" % road, "label": "[%s]" % label, "version": 1, "kind": "legs",
        "min_turns": int(min_turns), "max_turns": int(max_turns), "topics": bool(topics),
        **({"alternate_seats": list(alternate)} if alternate else {}),
        "legs": legs,
        "head": ("THE RUNNING ORDER OF THIS %s. Write exactly these turns, in this order, one line each, "
                 "and nothing else. Each line says what the turn does and the feeling to speak in - "
                 "perform both, never name them:" % head_what),
        "tail": ("Every numbered turn answers the turn above it by name or by quoting a word out of it, and "
                 "then says something of its own: no turn repeats or echoes a line already said. The "
                 "feeling on a row is how that speaker feels about the line they are answering."),
    }


def _line_structure(road, label, legs, head_what):
    return {
        "id": "%s_line" % road, "label": "[%s]" % label, "version": 1, "kind": "line",
        "min_turns": 1, "max_turns": len(legs), "topics": False, "legs": legs,
        "head": ("HOW THIS %s IS SAID. One voice. Each line below is one thing it does and the feeling "
                 "to say it in - perform the feeling, never name it:" % head_what),
        "tail": "",
    }


def _leg(id_, label, place, seat, act, *families):
    draws = []
    for fam in families or ("ES",):
        if fam == "FL2":
            draws.append({"family": "FL", "tables": ["FL2"]})
        elif fam == "FL2close":
            draws.append({"family": "FL", "tables": ["FL2"], "closes": True})
        else:
            draws.append({"family": fam})
    return {"id": id_, "label": label, "place": place, "seat": seat, "act": act, "draws": draws}


# [s3-roads] THE SEGMENTS AS SYSTEM 3 NODES. Each is the shape the road's own
# writer already asked for, written as legs: the fixed opening, a middle leg
# repeated to the turn budget with the seats alternating, and the landing.
# Every leg rolls ES (how it is said); the open legs roll RS (how it answers)
# and FL2 (where it goes). The road's own subject - the hour's log, the wire,
# the painting, the memo - stays the road's and arrives in the prompt as it
# always did (CTS OBLIGATED). All of it is editable: PUT /api/system3/structures/{road}.
DEFAULT_ROAD_STRUCTURES = {
    "recap": _legs_structure("recap", "Recap on the hour", 4, 10, [
        _leg("open", "Opens the recap", "open", "A",
             "OPENS THE RECAP: says the time out loud and that this is the recap on the hour.", "ES"),
        _leg("first", "The first thing off the hour", "open", "B",
             "picks the first thing worth recapping off the list - a record that really played, or something "
             "one of you said - and says what it was.", "ES", "RS"),
        _leg("next", "The next thing off the hour", "middle", "alternate",
             "takes the next item off the hour and answers the line before it: a record, a call, a story, "
             "in one breath each.", "ES", "RS", "FL2"),
        _leg("land", "Lands the recap", "close", "A",
             "LANDS THE RECAP: what is coming next, and hands back to the music.", "ES", "FL2close"),
    ], "RECAP"),
    "ad": _legs_structure("ad", "Sponsor spot", 3, 8, [
        _leg("open", "Opens the spot", "open", "A",
             "OPENS THE SPOT: names the sponsor out loud in the first sentence.", "ES"),
        _leg("pitch", "Trades the pitch", "middle", "alternate",
             "trades the pitch back and forth: one figure or claim, and the other tops it or is incredulous "
             "- never a monologue; answers the line before.", "ES", "RS"),
        _leg("land", "Lands the pitch", "close", "B",
             "LANDS THE PITCH: the sponsor's name once more, and one line that sells it.", "ES", "FL2close"),
    ], "SPONSOR SPOT"),
    "news": _legs_structure("news", "News", 4, 10, [
        _leg("lead", "The lead", "open", "A",
             "THE LEAD: the top story off the wire - the headline first, then what it says.", "ES"),
        _leg("react", "Reacts to the lead", "open", "B",
             "reacts to the lead - a real reaction - then one question or detail out of the story.", "ES", "RS"),
        _leg("next", "The next story", "middle", "alternate",
             "the next story off the page: says it, and what they make of it; answers the line before.",
             "ES", "RS", "FL2"),
        _leg("back", "Back to the music", "close", "A",
             "BACK TO THE MUSIC: one line that closes the bulletin and hands over.", "ES", "FL2close"),
    ], "NEWS"),
    "manager": _legs_structure("manager", "Upstairs", 3, 14, [
        _leg("deal", "Deals with upstairs", "open", "A",
             "DEALS WITH WHAT CAME DOWN FROM UPSTAIRS: names it, and says what they make of it.", "ES", "RS"),
        _leg("argue", "Argues it out", "middle", "alternate",
             "argues it out - who he meant, whether he is right, what it costs them - answering the line "
             "before.", "ES", "RS", "FL2"),
        _leg("land", "Lands it", "close", "B",
             "LANDS IT: what they will do about upstairs, and back to the show.", "ES", "FL2close"),
    ], "EXCHANGE WITH UPSTAIRS"),
    "memo": _legs_structure("memo", "Memo from upstairs", 3, 12, [
        _leg("read", "Reads the memo out", "open", "A",
             "READS THE MEMO OUT: who it is from and what it says, word for word where it matters.", "ES"),
        _leg("react", "Reacts to it", "middle", "alternate",
             "reacts to the memo and answers the line before: takes it personally, finds it funny, "
             "argues with it.", "ES", "RS", "FL2"),
        _leg("land", "Lands it", "close", "B",
             "LANDS IT: what they will actually do about the memo, and back to the show.", "ES", "FL2close"),
    ], "MEMO"),
    "gallery": _legs_structure("gallery", "Gallery", 5, 16, [
        _leg("open", "Opens on the painting", "open", "A",
             "OPENS ON THE PAINTING: names it and says the first true thing about it.", "ES"),
        _leg("see", "What they see in it", "open", "B",
             "answers with what THEY see in it - a detail, a colour, a figure - and disagrees or adds to it.",
             "ES", "RS"),
        _leg("look", "Keeps looking", "middle", "alternate",
             "keeps looking: one specific thing in the picture per turn, answering the line before.",
             "ES", "RS", "FL2"),
        _leg("land", "Lands it", "close", "A",
             "LANDS IT: what the painting is worth to them, and hands on.", "ES", "FL2close"),
    ], "PAINTING ROUND"),
    "mixtape": _legs_structure("mixtape", "MX mixtape", 3, 8, [
        _leg("open", "Opens on the tape", "open", "A",
             "OPENS ON THE TAPE: names MX and the tape, and what has just happened with it.", "ES"),
        _leg("music", "The music itself", "middle", "alternate",
             "one specific thing about the music - tempo, chords, production, the tradition it sits in - "
             "answering the line before; not one ironic word about MX.", "ES", "RS"),
        _leg("land", "Lands it", "close", "B",
             "LANDS IT: back to the station, glowing.", "ES", "FL2close"),
    ], "MIXTAPE ROUND"),
    "open_show": _legs_structure("open_show", "Opening the session", 3, 8, [
        _leg("welcome", "Welcomes people", "open", "A",
             "OPENS THE SESSION: welcomes people to the station by name.", "ES"),
        _leg("lately", "What he has had them doing", "middle", "alternate",
             "what he has had the two of you doing lately - one thing per turn, answering the line before.",
             "ES", "RS"),
        _leg("hand", "Hands to the first record", "close", "A",
             "HANDS OVER to the first record of the session.", "ES", "FL2close"),
    ], "OPENING"),
    "fan_mail": _legs_structure("fan_mail", "Fan mail", 3, 10, [
        _leg("open", "Opens the letter", "open", "A",
             "OPENS THE LETTER on air: the envelope, the paper, the handwriting.", "ES"),
        _leg("read", "Reads and reacts", "middle", "alternate",
             "reads a line of the letter, or reacts to the line just read - delighted, suspicious, moved, "
             "alarmed; answers the line before.", "ES", "RS", "FL2"),
        _leg("land", "Lands it", "close", "B",
             "LANDS IT: what they make of the letter, and back to the show.", "ES", "FL2close"),
    ], "LETTER"),
    "guest": _legs_structure("guest", "Guest send-off", 3, 14, [
        _leg("open", "Opens the send-off", "open", "A",
             "OPENS THE SEND-OFF: says the guest is leaving and thanks them by name.", "ES"),
        _leg("last", "One last exchange", "middle", "alternate",
             "one last exchange with the guest - a question, a memory of the visit - answering the line "
             "before.", "ES", "RS", "FL2"),
        _leg("home", "Sends them home", "close", "A",
             "SENDS THEM HOME: the goodbye, and back to the music.", "ES", "FL2close"),
    ], "SEND-OFF", alternate=["A", "D", "B"]),
    # [s3-roads] THE SINGLE-VOICE ROADS: one seat, one leg, the feeling rolled.
    # Where the road hands System 3 a list (the stock lines, the ad book), the
    # LINE draw over that list is the Rolodex where random.choice() was.
    "track_talk": _line_structure("track_talk", "Record talk", [
        _leg("link", "The record link", "close", "A",
             "names the record and says one true thing about the sound.", "ES")], "RECORD LINK"),
    "station_id": _line_structure("station_id", "Station ID", [
        _leg("id", "The station ID", "close", "D",
             "shouts the station's name like it is the only station there is.", "ES")], "STATION ID"),
    "upstairs": _line_structure("upstairs", "The manager's own page", [
        dict(_leg("page", "The page from upstairs", "close", "C",
                  "pages the booth over the intercom: the grievance, the threat out of all proportion.",
                  "ES"), splits=True, max_splits=3)], "PAGE FROM UPSTAIRS"),   # [s3-split] a booth voice reads on
    "interject": _line_structure("interject", "Stock interjection", [
        _leg("line", "The stock line", "close", "A",
             "says the line drawn off the list, as written.", "ES")], "INTERJECTION"),
    "ad_spot": _line_structure("ad_spot", "Produced advert", [
        dict(_leg("spot", "The produced spot", "close", "A",
                  "the spot drawn off the ad book plays as recorded.", "ES"),
             splits=True, max_splits=3)], "PRODUCED SPOT"),                   # [s3-split] a long read is shared out
    # [s3-lines] the four single lines dj_speak still spoke outside any road
    "reply": _line_structure("reply", "Reply", [
        _leg("answer", "The answer", "close", "A",
             "answers the message in front of them: what was asked, and the answer, plainly.", "ES")], "REPLY"),
    "request": _line_structure("request", "Request line", [
        _leg("take", "The request taken", "close", "A",
             "takes the request off the line: names it, and says what happens to it.", "ES")], "REQUEST LINE"),
    "open": _line_structure("open", "Show open", [
        _leg("open", "The show opened", "close", "A",
             "opens the show: the station's name, the hour, and what is coming.", "ES")], "SHOW OPEN"),
    "aside": _line_structure("aside", "Aside", [
        _leg("remark", "The remark", "close", "A",
             "one remark between two things - short, in the feeling rolled.", "ES")], "ASIDE"),
}
LINE_ROADS = ("track_talk", "station_id", "upstairs", "interject", "ad_spot", "reply", "request", "open", "aside")
PLACES = ("open", "middle", "close")


# [s3-story] A caller ringing back to carry on their story (#1039): the two legs
# that would introduce them from scratch and start a fresh story say where the
# story left off instead. A structure may carry its own `story_acts`.
STORY_ACTS = {
    "introduce": ("{FIRST} says who they are and that they have rung before - one line reminding the pair "
                  "where their story left off. Under thirty words."),
    "detail_1": ("picks the story up where it left off and gives the next CONCRETE thing that happened - "
                 "a thing, a place, a number, a name."),
}


def default_structures():
    """[s3-calls] One structure per road System 3 builds from its own nodes.
    [s3-roads] Every road on the register has one: the call protocol, the
    legs of each segment (recap, ad, news, manager, memo, gallery, mixtape,
    open_show, fan_mail, guest) and the one-leg line roads. Banter keeps
    its cycle in config["structure"]."""
    out = {"caller": copy.deepcopy(DEFAULT_CALL_STRUCTURE)}
    for road, st in DEFAULT_ROAD_STRUCTURES.items():
        out[road] = copy.deepcopy(st)
    return out


def road_register():
    return copy.deepcopy(ROAD_REGISTER)


# [s3-split] THE SPLIT NODE'S SWITCH on a step or a leg: `splits` (the
# checkbox) and `max_splits` - how many times one read may be split, 1 to 3.
# It is on by default where the long reads are: the produced advert, the
# manager's own page, and the banter cycle's opening step (the speaker-box
# monologue). The runtime switches it on once for a config saved before it
# existed (split_defaults_added); a box the operator unticks stays unticked.
SPLIT_MAX_SPLITS = 3
SPLIT_DEFAULT_NODES = (("banter", "initial"), ("ad_spot", "spot"), ("upstairs", "page"))


def split_problems(node, where):
    """[s3-split] What is wrong with a node's split switch, as a list."""
    out = []
    if not isinstance(node, dict):
        return out
    if "splits" in node and not isinstance(node.get("splits"), bool):
        out.append("%s: splits is a checkbox (true or false)" % where)
    if "max_splits" in node:
        n = node.get("max_splits")
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= SPLIT_MAX_SPLITS:
            out.append("%s: max_splits must be a whole number from 1 to %d" % (where, SPLIT_MAX_SPLITS))
    return out


def validate_structure(road, st):
    """A road structure an operator may save: legs with ids, a place, a seat
    and draws of known families. Returns the list of problems."""
    out = []
    legs = st.get("legs") if isinstance(st, dict) else None
    if not isinstance(legs, list) or not legs:
        return ["the %s structure needs legs" % road]
    ids = set()
    for leg in legs:
        if not isinstance(leg, dict) or not str(leg.get("id") or "").strip():
            out.append("every leg needs an id")
            continue
        if leg["id"] in ids:
            out.append("leg %s appears twice" % leg["id"])
        ids.add(leg["id"])
        if leg.get("place") not in PLACES:
            out.append("leg %s: place must be one of %s" % (leg["id"], ", ".join(PLACES)))
        if str(leg.get("seat") or "") not in ("A", "B", "C", "D", "E", "alternate"):
            out.append("leg %s: seat must be A-E or alternate" % leg["id"])
        for d in leg.get("draws") or []:
            if not isinstance(d, dict) or d.get("family") not in ("ES", "RS", "IRS", "FL", "CTS"):
                out.append("leg %s: unknown draw %r" % (leg["id"], d))
        out.extend(split_problems(leg, "leg %s" % leg["id"]))                  # [s3-split]
    if not [leg for leg in legs if isinstance(leg, dict) and leg.get("place") == "close"]:
        out.append("the %s structure needs a closing leg" % road)
    alt = st.get("alternate_seats")
    if alt is not None and (not isinstance(alt, list) or not alt
                            or any(str(x) not in ("A", "B", "C", "D", "E") for x in alt)):
        out.append("alternate_seats must be a list of seats A-E")
    for key in ("min_turns", "max_turns"):
        if key in st and (not isinstance(st[key], int) or st[key] < 1 or st[key] > 60):
            out.append("%s must be a whole number from 1 to 60" % key)
    if road == "caller":                                                    # [s3-callend] the call's end families
        mine = {"leg %s: unknown draw %r" % (leg["id"], d) for leg in legs
                if isinstance(leg, dict) and str(leg.get("id") or "").strip()
                for d in leg.get("draws") or [] if isinstance(d, dict) and d.get("family") in CALLEND_FAMILIES}
        out = [p for p in out if p not in mine]
        for leg in legs:
            if isinstance(leg, dict) and leg.get("end") and leg.get("end") not in CALLEND_ROLES:
                out.append("leg %s: end must be one of %s" % (leg.get("id"), ", ".join(CALLEND_ROLES)))
    return out


def default_tables():
    return copy.deepcopy(DEFAULT_TABLES)


def default_structure():
    return copy.deepcopy(DEFAULT_STRUCTURE)

# --- [s3-live-event] STATION EVENTS, FIRST-CLASS IN THE WHEELS ----------------------
#
# 2026-09-28, the operator: "When it comes to music based nodes in System3. I want
# there to be options added to have dialogue made for the live event and to have the
# DJs able to dicuss the event in segments in passing and having it as an option in
# the relevant roulette wheels (when relevant). Events should be able to be
# activatable and used in generated conversational node trees without uptrooting the
# entire system." And: during a PineLive set the DJs TALK OVER IT, ducked - so the
# rows below are relevant while the set is live, not only afterwards.
#
# An EVENT is a registry entry (DEFAULT_EVENTS; the live copy is config["events"]):
# an id, a name, where its on/off comes from (`source`: "pinelive" follows the
# PineLive event switch, "manual" is System 3's own switch), its facts, and an
# optional window (starts_at / ends_at, epoch seconds, 0 = none).
#
# Its ROWS are ordinary table rows, tagged: `"event": "<id>"` on a table, and
# `"event_stages"` on a category for the part of the event it fits -
#   upcoming  armed, waiting for the first sound (or a window not yet started)
#   live      on the air: the live input is the music, the station's records wait
#   fallback  running, but the input dropped out and the station has the air back
#   after     finished within the event's after_window
# While the event is on, its rows join their wheels. While it is off they are taken
# out BEFORE any weight is computed (system3.event_view), so with no event on every
# draw is today's draw. A row that talks about an event never lands on a banked
# round (it could air after the event has changed) unless the table says
# "event_banked": true.
#
# NOTHING HERE TOUCHES DEFAULT_TABLES OR DEFAULT_BLOCKS: default_config()'s hash is
# pinned (tests/test_system3.py) and these rows reach the LIVE config once, through
# the runtime's add_missing_default_tables / add_missing_station_events - saved as a
# version with a note, editable in Tables, deletable for good.
#
# The wheels MX Live joins:
#   MXLIVE1       EVENT       in passing, inside a segment's exchange (banter, mixtape,
#                             recap, the open, fan mail, the gallery, upstairs, a guest):
#                             reactions to the set, shout-outs, the trail, the dropout,
#                             the look back - each kind its own die (seed|round:EVENT:...)
#   MXLIVECALL1   EVENT       on a call: the caller reacts to the set, asks after it;
#                             the host tells the caller it is on
#   MXLIVECTS1    CTS         a topic change: the subject turns to the live set
#   MXLIVETRACK1  TRACK_TALK  the live record comment: the banter's TRACK_TALK moment
#                             talks about the set while the station's record is held -
#                             never the held record. The track_talk control is still
#                             the die; only the comment's direction is one of these.
#   MXLIVEID1     EVENT       a station ID drawn while it is live (the station_id
#                             road's LINE wheel; a banked ID never takes one)
#   MXLIVEANGLE1  ANGLE       a free banter round's whole angle: joins the station's
#                             stock-angle wheel (`pool` names it: banter.stock_angle)
EVENT_STAGES = ("upcoming", "live", "fallback", "after")
EVENT_SOURCES = ("pinelive", "manual")

DEFAULT_EVENTS = {
    "mxlive": {
        "id": "mxlive", "name": "MX Live", "source": "pinelive", "enabled": True,
        "what": "PineLive: MX playing live into the station while the station's own records wait",
        "facts": {
            "what": "MX's live set - MX playing live into the station, with the station's own records held until it ends",
            "who": "MX",
            "device": "EP-133 K.O. II",
            "notes": ["There is no track list for a live set: never name a title or an artist for what is being "
                      "played live - talk about the sound, the energy and what MX is doing with the machine."],
        },
        "after_window": 1800,           # seconds the "after" rows stay eligible once it ends
        "starts_at": 0, "ends_at": 0,   # an optional window (epoch seconds; 0 = none)
    },
}


def default_events():
    return copy.deepcopy(DEFAULT_EVENTS)


_MX_TALK_ROADS = ["banter", "mixtape", "recap", "open_show", "fan_mail", "gallery", "manager", "guest"]

MXLIVE1 = {
    "id": "MXLIVE1", "family": "EVENT", "label": "MX Live: in passing (a segment's exchange)", "version": 1,
    "enabled": True, "weight": 1.0, "event": "mxlive", "roads": list(_MX_TALK_ROADS), "max_events": 1,
    "description": "While MX Live is on, one of the DJs may mention it in passing inside the exchange - a reaction "
                   "to the set playing underneath, a shout-out, the trail before it starts, the dropout, the look "
                   "back. Each kind is its own die per segment; a hit lands on one host turn and the next turn "
                   "answers it like any other line. Invisible to the dice while the event is off.",
    "categories": [
        {"id": "reacts", "label": "MX Live: reacts to the set", "weight": 1.0, "odds": 0.35, "seat": "host",
         "place": "any", "event_stages": ["live"],
         "items": _items([
             {"id": "hears_it", "label": "Hears something in it",
              "text": "reacts in passing to the live set playing underneath them - one specific thing MX just did "
                      "with the sound - and carries straight on"},
             {"id": "breaks_off", "label": "Breaks off for a second",
              "text": "breaks off for a second because the live set underneath just did something - a drop, a switch, "
                      "a build - says so in a few words, then comes back to the conversation"},
             {"id": "nodding", "label": "Has been nodding along",
              "text": "admits in passing they have been nodding along to the live set the whole time, and says what it "
                      "is doing to the room"},
         ])},
        {"id": "shout_out", "label": "MX Live: a shout-out", "weight": 1.0, "odds": 0.2, "seat": "host",
         "place": "any", "event_stages": ["live", "fallback"],
         "items": _items([
             {"id": "shout", "label": "Shouts out MX",
              "text": "gives MX a shout-out on air for playing live on the station right now, in one line, then back "
                      "to the conversation"},
             {"id": "stay_put", "label": "Tells the listeners to stay put",
              "text": "tells the listeners in passing to stay put, because MX is live on the station right now"},
         ])},
        {"id": "trail", "label": "MX Live: the trail", "weight": 1.0, "odds": 0.2, "seat": "host",
         "place": "any", "event_stages": ["upcoming"],
         "items": _items([
             {"id": "coming", "label": "It is switched on for today",
              "text": "mentions in passing that MX Live is armed - MX is about to play live into the station - "
                      "without promising a time"},
         ])},
        {"id": "dropout", "label": "MX Live: the input dropped out", "weight": 1.0, "odds": 0.5, "seat": "host",
         "place": "any", "event_stages": ["fallback"],
         "items": _items([
             {"id": "back_soon", "label": "The station has the air for a moment",
              "text": "notes in passing that the live set dropped out for a moment and the station has the air until "
                      "it comes back - no fuss, straight back to the conversation"},
         ])},
        {"id": "after", "label": "MX Live: looking back", "weight": 1.0, "odds": 0.3, "seat": "host",
         "place": "any", "event_stages": ["after"],
         "items": _items([
             {"id": "that_was", "label": "One moment that stuck",
              "text": "looks back in passing on the live set MX just finished - one moment of it that stuck with them"},
         ])},
    ],
}

MXLIVECALL1 = {
    "id": "MXLIVECALL1", "family": "EVENT", "label": "MX Live: on a call", "version": 1,
    "enabled": True, "weight": 1.0, "event": "mxlive", "roads": ["caller"], "max_events": 1,
    "description": "While MX Live is on, a caller may bring it up, or a host may tell the caller it is on. {first} is "
                   "the caller's first name. Invisible to the dice while the event is off.",
    "categories": [
        {"id": "caller_live", "label": "MX Live: the caller has it on", "weight": 1.0, "odds": 0.3, "seat": "caller",
         "place": "any", "event_stages": ["live", "fallback"],
         "items": _items([
             {"id": "has_it_on", "label": "Has the set on",
              "text": "{first} says in passing they have MX's live set on right now, and what they make of it so far"},
             {"id": "tell_mx", "label": "Asks them to tell MX something",
              "text": "{first} asks the hosts to tell MX one thing about the live set, in passing"},
         ])},
        {"id": "caller_upcoming", "label": "MX Live: the caller asks after it", "weight": 1.0, "odds": 0.15,
         "seat": "caller", "place": "any", "event_stages": ["upcoming"],
         "items": _items([
             {"id": "when", "label": "Asks when it starts",
              "text": "{first} asks in passing when MX goes live, and the hosts cannot promise a time"},
         ])},
        {"id": "host_live", "label": "MX Live: the host tells the caller", "weight": 1.0, "odds": 0.15,
         "seat": "host", "place": "any", "event_stages": ["live"],
         "items": _items([
             {"id": "its_on", "label": "Tells the caller MX is live",
              "text": "tells {first} in passing that MX is live on the station right now, underneath this very call"},
         ])},
    ],
}

MXLIVECTS1 = {
    "id": "MXLIVECTS1", "family": "CTS", "label": "MX Live: topics", "version": 1,
    "enabled": True, "weight": 0.6, "event": "mxlive",
    "description": "While MX Live is on, a change of subject may turn to it (beside CTS1, at this table's weight). "
                   "Invisible to the dice while the event is off.",
    "categories": [
        {"id": "live_set", "label": "MX Live: the set on the air", "weight": 1.0, "resolver": "direction",
         "event_stages": ["live", "fallback"],
         "items": _items([
             {"id": "the_set", "label": "The live set itself",
              "text": "turns to MX Live - the set MX is playing live into the station right now - and what they make "
                      "of it; the live set comes up in passing, the exchange stays theirs"},
             {"id": "live_vs_records", "label": "Live against the records",
              "text": "turns to what it is like having MX live instead of the station's own records tonight - which "
                      "they would rather have"},
         ])},
        {"id": "upcoming", "label": "MX Live: switched on, not started", "weight": 1.0, "resolver": "direction",
         "event_stages": ["upcoming"],
         "items": _items([
             {"id": "what_he_plays", "label": "What MX will play",
              "text": "turns to MX Live, armed for today - what they expect MX to do when the set starts, "
                      "without promising a time"},
         ])},
        {"id": "after", "label": "MX Live: just finished", "weight": 1.0, "resolver": "direction",
         "event_stages": ["after"],
         "items": _items([
             {"id": "looks_back", "label": "Looks back on the set",
              "text": "turns back to the live set MX just finished and what they made of it"},
         ])},
    ],
}

MXLIVETRACK1 = {
    "id": "MXLIVETRACK1", "family": "TRACK_TALK", "label": "MX Live: the live record comment", "version": 1,
    "enabled": True, "weight": 1.0, "event": "mxlive",
    "description": "The banter's TRACK_TALK moment (a passing comment on what is playing underneath) while MX is "
                   "live: the station's record is held, so the comment is about the live set - one of these rows, "
                   "drawn on its own stream. The track_talk control is still the die. Invisible while the event "
                   "is off.",
    "categories": [
        {"id": "live_set", "label": "MX Live: what is being played live", "weight": 1.0, "event_stages": ["live"],
         "items": _items([
             {"id": "the_sound", "label": "The sound of it",
              "text": "the live set MX is playing underneath them right now - one specific thing about its sound: "
                      "the drums, the texture, a change it just made"},
             {"id": "the_energy", "label": "Where it has gone",
              "text": "where MX's live set has gone in the last few minutes - the energy of it, underneath them"},
             {"id": "the_machine", "label": "What MX is doing with the machine",
              "text": "what MX is doing with the EP-133 K.O. II right now - the chops, the loops, the pads - as the "
                      "set plays underneath"},
         ])},
    ],
}

MXLIVEID1 = {
    "id": "MXLIVEID1", "family": "EVENT", "label": "MX Live: station IDs", "version": 1,
    "enabled": True, "weight": 1.0, "event": "mxlive", "roads": ["station_id"], "max_events": 1,
    "description": "While MX is live, the station-ID road's LINE wheel offers these beside the stock IDs (the words "
                   "as written; {station} is the station's name). A banked ID never takes one - it could air after "
                   "the set. Invisible while the event is off.",
    "categories": [
        {"id": "id", "label": "MX Live: the ID", "weight": 1.0, "odds": 0.5, "seat": "any", "place": "any",
         "event_stages": ["live"],
         "items": _items([
             {"id": "right_now", "label": "Right now", "text": "MX Live. Right now. Only on {station}."},
             {"id": "dont_touch", "label": "Do not touch that dial",
              "text": "{station}. MX is live. Do not touch that dial."},
             {"id": "no_net", "label": "No net", "text": "This is MX Live on {station}. Loud, live, no net."},
         ])},
    ],
}

MXLIVEANGLE1 = {
    "id": "MXLIVEANGLE1", "family": "ANGLE", "label": "MX Live: banter angles", "version": 1,
    "enabled": True, "weight": 1.0, "event": "mxlive", "pool": "banter.stock_angle",
    "description": "While MX Live is on, the station's stock-angle wheel for a free banter round (the POOLS row "
                   "banter.stock_angle) offers these rows too: the round is ABOUT the event. The round's own node "
                   "chain is unchanged - an initial message, a response from each seat, the rebuttal. Invisible "
                   "while the event is off.",
    "categories": [
        {"id": "live", "label": "MX Live: while it is live", "weight": 1.0, "event_stages": ["live"],
         "items": _items([
             {"id": "side_of_stage", "label": "Side of the stage",
              "text": "MX is live on the station right now - talk over the set like two people at the side of the "
                      "stage: what MX is doing, what it does to the room, whether either of you could do it"},
             {"id": "live_vs_records", "label": "Live against the records",
              "text": "argue about live sets against records, with MX's live set going out underneath you as "
                      "exhibit A"},
         ])},
        {"id": "upcoming", "label": "MX Live: before it starts", "weight": 1.0, "event_stages": ["upcoming"],
         "items": _items([
             {"id": "what_will_he_play", "label": "What MX will play",
              "text": "MX Live is armed for today - speculate about what MX will do when the set starts, "
                      "without promising a time"},
         ])},
        {"id": "after", "label": "MX Live: after it ends", "weight": 1.0, "event_stages": ["after"],
         "items": _items([
             {"id": "moments", "label": "The moments that stuck",
              "text": "MX just finished playing live on the station - trade the moments of the set that stuck "
                      "with you"},
         ])},
    ],
}

# The event tables reach the LIVE config once (runtime add_missing_default_tables),
# never default_config(): its hash is pinned.
EVENT_TABLES = [MXLIVE1, MXLIVECALL1, MXLIVECTS1, MXLIVETRACK1, MXLIVEID1, MXLIVEANGLE1]


def default_event_tables():
    return copy.deepcopy(EVENT_TABLES)


# THE EVENT'S FACTS ARE A NODE. They reach the writer as their own block, marked
# where System 3's running order enters the prompt, and only when a roll in this
# round landed on an event row claims it (kind "claimed" - system3.decide_blocks);
# otherwise the block is never built. Never a wedge. Reaches config["blocks"] once
# through the runtime (add_missing_station_events), never DEFAULT_BLOCKS.
EVENT_BLOCKS = {
    "event_facts": {
        "kind": "claimed", "label": "A station event's facts (MX Live ...)",
        "helper": "system3_event_facts (the runtime's event_facts_text)",
        "what": "sent only when a roll in the round landed on an event row (MXLIVE1, MXLIVECTS1 ...)"},
}


def default_event_blocks():
    return copy.deepcopy(EVENT_BLOCKS)

# --- [es-v2] ES1, SECOND EDITION: how a feeling sounds, recalibrated, and what the
# writer is told, as an actor is directed (emotion engine steps 3 + 7) --------------
#
# THE VOICES (step 3), checked against the master table of emotional prosody
# (Banse & Scherer 1996 z-profiles, Juslin & Laukka 2003's 104-study consensus,
# Burkhardt & Sendlmeier 2000 / Schroeder 2001 synthesis-verified settings,
# Paeschke & Sendlmeier 2000 contours), scaled into the house bounds. The families
# the v1 blocks blurred are split where the literature measures OPPOSITE signs:
#   panic (F0 +1.23z) vs anxiety (-0.58z, the most monotone of 14, quiet);
#   elation (+1.24z) vs contentment (-0.64z, slower, quieter);
#   quiet sorrow (-0.32z, quietest) vs despair (+0.99z, loud, range narrowed);
#   hot anger vs contempt (-1.03z, the lowest F0 of all, quiet).
# Fear keeps its counter-intuitive geometry: register UP, span NOT widened
# (SdF0 -0.63z, accent span 8.6 st vs 9.5 neutral) - no fear row swings wider than
# 1.0 - and its "mixed model" (breath-grabbing pauses inside a fast line) is
# pause > 1 with tempo > 1. Disgust and contempt are darker (energy -), never
# brighter; interest is brisk (the third-fastest articulation) at a neutral pitch;
# the self-conscious family (shame, pride) sits low.
# A block names what it sets; an item's block names only what differs from its
# category (as in v1). An item absent here keeps its v1 block.
ES_V2_VOICE = {
    #               tempo          pitch          range          energy          pause          temp
    "surprise":    {"tempo": 1.05, "pitch": 1.6,  "range": 1.40, "energy": 0.30,  "pause": 0.85, "temp": 0.06},
    "anger":       {"tempo": 1.10, "pitch": 1.0,  "range": 1.35, "energy": 0.60,  "pause": 0.78, "temp": 0.05},
    "fear":        {"tempo": 1.10, "pitch": 1.2,  "range": 0.90, "energy": 0.25,  "pause": 1.08, "temp": 0.05},
    "sadness":     {"tempo": 0.86, "pitch": -1.0, "range": 0.70, "energy": -0.50, "pause": 1.40, "temp": -0.05},
    "joy":         {"tempo": 1.08, "pitch": 1.2,  "range": 1.35, "energy": 0.40,  "pause": 0.90, "temp": 0.05},
    "disgust":     {"tempo": 0.90, "pitch": -0.8, "range": 1.15, "energy": -0.25, "pause": 1.15, "temp": -0.02},
    "interest":    {"tempo": 1.06, "pitch": 0.0,  "range": 1.20, "energy": 0.25,  "pause": 0.92, "temp": 0.03},
    "social":      {"tempo": 0.96, "pitch": -0.4, "range": 0.90, "energy": -0.25, "pause": 1.15, "temp": 0.0},
    "low_arousal": {"tempo": 0.87, "pitch": -1.0, "range": 0.65, "energy": -0.55, "pause": 1.35, "temp": -0.07},
}
ES_V2_ITEM_VOICE = {
    # anger: hot stays hot; contempt is cold, low and quiet; resentment cold and controlled
    "contempt":       {"tempo": 0.95, "pitch": -1.2, "range": 1.10, "energy": -0.20, "pause": 1.10, "temp": 0.0},
    "resentment":     {"tempo": 1.0, "pitch": -0.2, "range": 1.15, "energy": 0.30, "pause": 1.0, "temp": 0.0},
    "anger.disgust":  {"tempo": 0.95, "pitch": -0.5, "range": 1.15, "energy": 0.10, "pause": 1.05},
    # fear: the panic side up and fast, span never widened; the anxious side low, flat, quiet
    "unease":         {"tempo": 1.02, "pitch": -0.2, "range": 0.85, "energy": -0.10, "pause": 1.10, "temp": 0.02},
    "apprehension":   {"tempo": 1.04, "pitch": -0.2, "range": 0.85, "energy": 0.0, "pause": 1.05},
    "anxiety":        {"tempo": 1.04, "pitch": -0.6, "range": 0.70, "energy": -0.25, "pause": 1.15, "temp": 0.0},
    "alarm":          {"tempo": 1.10, "pitch": 1.4, "range": 0.95, "energy": 0.40, "pause": 1.05},
    "dread":          {"tempo": 0.98, "pitch": -0.4, "range": 0.70, "energy": -0.20, "pause": 1.25, "temp": -0.02},
    "panic":          {"tempo": 1.14, "pitch": 1.8, "range": 0.95, "energy": 0.50, "pause": 1.10, "temp": 0.07},
    "horror":         {"tempo": 1.04, "pitch": 1.2, "range": 1.0, "energy": 0.35, "pause": 1.10},
    # sadness: despair is the high, loud, narrowed protest - the sign flips
    "despair":        {"tempo": 0.90, "pitch": 1.0, "range": 0.80, "energy": 0.35, "pause": 1.30, "temp": 0.03},
    # joy: the savouring side (contentment) sits lower, slower and softer than elation
    "pleasure":       {"tempo": 0.98, "pitch": 0.0, "range": 1.20, "energy": -0.10, "pause": 1.0},
    "happiness":      {"tempo": 1.0, "pitch": 0.2, "range": 1.25, "energy": 0.05, "pause": 0.98},
    "satisfaction":   {"tempo": 0.96, "pitch": -0.5, "range": 1.10, "energy": -0.25, "pause": 1.10, "temp": 0.0},
    # disgust: darker, never brighter
    "distaste":       {"tempo": 0.95, "pitch": -0.5, "range": 1.05, "energy": -0.15, "pause": 1.10},
    "revulsion":      {"tempo": 0.90, "pitch": -1.0, "range": 1.25, "energy": -0.10, "pause": 1.20},
    "repulsion":      {"tempo": 0.91, "pitch": -0.9, "range": 1.20, "energy": -0.10, "pause": 1.18},
    "moral disgust":  {"tempo": 0.94, "pitch": -0.6, "range": 1.20, "energy": -0.10, "pause": 1.10},
    # interest: brisk, near the speaker's own pitch
    "fascination":    {"tempo": 1.02, "pitch": 0.4, "range": 1.30, "energy": 0.20},
    "attentiveness":  {"tempo": 1.02, "pitch": 0.2, "range": 1.05, "energy": 0.05, "pause": 1.0},
    # social: pride is low and even, not bright
    "pride":          {"tempo": 1.02, "pitch": -0.2, "range": 1.15, "energy": 0.0, "pause": 1.05, "temp": 0.01},
}

# THE WRITER'S DIRECTION (step 7). The operator, 2026-09-28: "the emotions and
# response acceptances are stages while mentally processing the speakerbox seeded
# text" - so the feeling is written as the stage the speaker is at while taking in
# what was put to them, and the direction is an actor's: a playable verb, the word
# the line leans on, the clause shape (the pause knob: sorrow fragments, anger
# runs on), and what the END of the line leaves open (a fall to the floor is
# certainty; a high, floating end is appeal, alarm, surprise). Valence barely
# travels in the acoustics, so the WORDS carry it: congruent wording per family.
# No sound words and no stage directions (the station strips a leading "ugh",
# #598, and a bracketed one is never said). One sentence, well under the 400-char
# cap; {name} and {feeling} are filled when the turn is planned (es_direction).
ES_V2_DIRECTION_LEAD = "{name} processes this as {feeling}: play it to "
ES_V2_DIRECTION = {
    "surprise":    "REACT - quick short phrases, one big late accent on the news-word, and let the end lift and float, unresolved.",
    "anger":       "CONFRONT - short hard words in one run-on push with no room to breathe, lean on the word that offends, and land the end with a hard fall.",
    "fear":        "WARN - quick broken phrases, a question left hanging, the voice climbing, and leave the end high and open, never settled.",
    "sadness":     "CONFIDE - short, plain, fragmented clauses with room between them, soft words, and let each end fall short and quiet.",
    "joy":         "CELEBRATE - bright, warm, generous words, lift the word that delights, keep it moving, and ride a long smooth fall at the end.",
    "disgust":     "DISMISS - clipped, flat, withholding words, slow down on the word that repels, and drop the end to the floor.",
    "interest":    "PROBE - brisk and precise, a pointed follow-up, light accents on the facts, and keep the end rising so the floor stays open.",
    "social":      "SAVE FACE - hedged, self-aware words, a small qualifier or two, and a soft, unresolved end.",
    "low_arousal": "SHRUG IT OFF - few, flat, unhurried words, nothing exclaimed, and let every end sink to the floor.",
}
ES_V2_ITEM_DIRECTION = {
    "fury":          "THREATEN, boiling - hit every stressed word, no pauses at all, and slam each end down.",
    "outrage":       "THREATEN, boiling - hit every stressed word, no pauses at all, and slam each end down.",
    "contempt":      "DISMISS, icy - controlled, over-precise words, nothing raised, and a low flat end.",
    "resentment":    "NEEDLE - controlled and precise, the grievance under every word, and a low flat end.",
    "anxiety":       "WORRY aloud - soft and even, a hesitation before the point, and a mid, unresolved end.",
    "unease":        "WORRY aloud - soft and even, a hesitation before the point, and a mid, unresolved end.",
    "dread":         "WORRY aloud - slow and low, a hesitation before the point, and an end that hangs.",
    "panic":         "RAISE THE ALARM - rapid fragments with breath-grabbing breaks, and the end high with no fall.",
    "despair":       "PLEAD - broken, reaching phrases that go back over the same point, strained and pitched up, the end falling away.",
    "grief":         "GRIEVE quietly - very plain words, short fragments with long gaps, and a shallow, late-falling end.",
    "pleasure":      "SAVOUR - easy, warm, unhurried words, gentle accents, and a soft settled end.",
    "satisfaction":  "SAVOUR - easy, warm, unhurried words, gentle accents, and a soft settled end.",
    "relief":        "SAVOUR - easy, warm, unhurried words, a breath of release, and a soft settled end.",
    "excitement":    "ENTHUSE - fast, bright, run-together words, a lift on every good thing, and a long smooth fall at the end.",
    "boredom":       "ENDURE - as few words as will do, drawn out and flat, and a steady fall to the floor at the end.",
    "calm":          "SOOTHE - slow, soft, even words, no contrast between them, and a gentle downward end.",
}


def _es_v2_item_voice(cid, word):
    got = ES_V2_ITEM_VOICE.get("%s.%s" % (cid, word), ES_V2_ITEM_VOICE.get(word))
    return dict(got) if got is not None else _es_item_voice(cid, word)


def _es1_v2():
    """ES1 with the v2 voices and directions (same ids, weights, badges, dims)."""
    table = copy.deepcopy(ES1)
    for cat in table["categories"]:
        cid = cat["id"]
        cat["voice"] = dict(ES_V2_VOICE[cid])
        for item in cat["items"]:
            word = item["label"]
            voice = _es_v2_item_voice(cid, word)
            if voice is not None:
                item["voice"] = voice
            item["text"] = ES_V2_DIRECTION_LEAD + ES_V2_ITEM_DIRECTION.get(word, ES_V2_DIRECTION[cid])
    return table


ES1_V2 = _es1_v2()

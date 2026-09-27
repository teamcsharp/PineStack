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

ES1 = {
    "id": "ES1", "family": "ES", "label": "Emotional Set 1", "version": 1,
    "enabled": True, "weight": 1.0,
    "description": "The emotion each turn is spoken in: guides the wording and the voice.",
    "categories": [
        {"id": cid, "label": label, "weight": 1.0, "valence": val, "arousal": ar,
         "dims": dims, "modifiers": mods, "after_lean": _ES_AFTER.get(cid, {}),
         "items": _items([{"id": f"{cid}.{w.replace(' ', '_')}", "label": w,
                           **({"arousal": _ES_AROUSAL[w]} if w in _ES_AROUSAL else {}),
                           **({"valence": _ES_VALENCE[w]} if w in _ES_VALENCE else {})}
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
              "cue": "disagree", "text": "rebuts it with the facts as they know them"},
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
        {"id": "playful", "label": "Playful", "weight": 1.0, "lean": 0, "tags": ["humor"],
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
        {"id": "comedic", "label": "Comedic (making fun of the response)", "weight": 1.0, "lean": -1,
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
        {"id": "confrontational", "label": "Confrontational", "weight": 1.0, "lean": -1,
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
        {"id": "yield", "label": "Yield", "weight": 0.8, "lean": 1, "tags": ["agreement"],
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
        {"id": "anger", "label": "Anger", "weight": 0.7, "speaker": "any", "new_topic": True,
         "min_turns_left": 4, "not_phases": ["SEGUE"], "tags": ["escalation"],
         "emotions": {"anger": 2.0, "disgust": 1.4, "joy": 0.4},
         "effects": {"tension": 0.25, "energy": 0.15},
         "items": _items([{"id": "parking_lot", "label": "Request to fight outside",
                           "text": "decides the topic is not worth discussing and invites them out to the parking lot for a battle"}])},
        {"id": "enjoyment", "label": "Enjoyment", "weight": 1.0, "speaker": "initiator",
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

DEFAULT_TABLES = [CTS1, ES1, RS1, RS2, IRS1, IRS2, FL1, FL2]

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
         "draws": [{"family": "CTS"}, {"family": "ES"}], "speakerbox": ["prepend", "append"]},
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
        {"id": "lands", "label": "The caller lands it", "place": "close", "seat": "C",
         "act": "{FIRST} LANDS IT. The caller says the last word of their own story here. This must be "
                "the SECOND TO LAST turn of the whole call.",
         "draws": [{"family": "ES"}]},
        {"id": "sign_off", "label": "Sign off", "place": "close", "seat": "A",
         "act": "SIGN OFF. The final turn is a host, and it must contain one of these words out loud: "
                "thanks, thank you, goodbye, goodnight, take care, appreciate.",
         "draws": [{"family": "ES"}]},
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
    {"id": "ad_spot", "label": "Produced advert", "shape": "line",
     "writer": "dj_ad_break: ad_pick", "hook": "system3_direct_line (LINE draw over the book)",
     "what": "a stored or produced spot: the ad book's rows are the Rolodex, the pick is a recorded draw"},
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
        _leg("page", "The page from upstairs", "close", "C",
             "pages the booth over the intercom: the grievance, the threat out of all proportion.",
             "ES")], "PAGE FROM UPSTAIRS"),
    "interject": _line_structure("interject", "Stock interjection", [
        _leg("line", "The stock line", "close", "A",
             "says the line drawn off the list, as written.", "ES")], "INTERJECTION"),
    "ad_spot": _line_structure("ad_spot", "Produced advert", [
        _leg("spot", "The produced spot", "close", "A",
             "the spot drawn off the ad book plays as recorded.", "ES")], "PRODUCED SPOT"),
}
LINE_ROADS = ("track_talk", "station_id", "upstairs", "interject", "ad_spot")
PLACES = ("open", "middle", "close")


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
    if not [leg for leg in legs if isinstance(leg, dict) and leg.get("place") == "close"]:
        out.append("the %s structure needs a closing leg" % road)
    alt = st.get("alternate_seats")
    if alt is not None and (not isinstance(alt, list) or not alt
                            or any(str(x) not in ("A", "B", "C", "D", "E") for x in alt)):
        out.append("alternate_seats must be a list of seats A-E")
    for key in ("min_turns", "max_turns"):
        if key in st and (not isinstance(st[key], int) or st[key] < 1 or st[key] > 60):
            out.append("%s must be a whole number from 1 to 60" % key)
    return out


def default_tables():
    return copy.deepcopy(DEFAULT_TABLES)


def default_structure():
    return copy.deepcopy(DEFAULT_STRUCTURE)

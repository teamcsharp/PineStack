"""[outlandish] THE OUTLANDISH METER, and the structure that reacts to it.

The operator, 2026-09-29: there is NO censorship. The stream is built for about
ten scientists who analyse the logic systems; outlandish, appalling and
inappropriate statements are deliberate - they exist so the co-hosts dispute
them. Nothing here filters, softens, blocks or rewrites a word. It MEASURES a
line that aired (or is about to), SURFACES it (the audit log, the roll tiles, a
review list) and lets System 3 REACT with structure: the odds that the next
seat disputes it, the SFX Guy's reaction clip, and the interjection's mini-round.

Everything tunable is a System 3 table (editable in the Tables editor, saved as
a config version like any other table). A "dials" category holds the numbers;
each dial's value is its item's weight, scaled as its label says:
  x10  - points and scores (a slider at 6.0 is a threshold of 60)
  /5   - odds (a slider at 4.25 is 85%)
  raw  - multipliers

Tables (family):
  OUTLANDISH1 (MEASURE)  categories = tags; items = cues, `text` is the cue's
                         regular expression, weight x10 = its points.
  OUTDISPUTE1 (MEASURE)  after a line scores >= `from`, the next seat's RS/IRS
                         rows named here weigh up to x weight (at score 100).
  SFXREACT1   (SFXREACT) the SFX Guy's reaction topics; a category's `tags`
                         (advanced JSON) weigh it by the line's tags; items are
                         the words his clip search and repertoire use.
  CUTIN1      (CUTIN)    the chance another seat cuts in on a long turn.
  MINIROUND1  (MINIROUND) an interjection's mini-round: reply -> rebuttal ->
                         the exit roll (how it ends: its turns).
  HOLDBANTER1 (HOLD)     the pipeline is behind: an in-character aside (never a
                         word about waiting) beside the SFX Guy's time-buyers.

Pure: no station imports. Every draw takes its uniform from the caller, so the
engine's streams stay the engine's and a test can pin every number.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
from typing import Any, Iterable

VERSION = "outlandish/1"
FAMILIES = ("MEASURE", "SFXREACT", "CUTIN", "MINIROUND", "HOLD")
TABLE_IDS = ("OUTLANDISH1", "OUTDISPUTE1", "SFXREACT1", "CUTIN1", "MINIROUND1", "HOLDBANTER1")
DISPUTE_KEYS = ("RS:argue", "RS:push_back", "RS:oppositional",
                "IRS:refutation", "IRS:confrontational", "IRS:opposite")


def _cue(id_, label, rx, points=2.5, **kw):
    return dict({"id": id_, "label": label, "text": rx, "weight": points}, **kw)


def _dial(id_, label, weight, text=""):
    return {"id": id_, "label": label, "weight": weight, "text": text or label}


# --- OUTLANDISH1: the meter ---------------------------------------------------
# A tag's points are the sum of its distinct cues (each cue counts once however
# often it is said), capped at `cap`, times the category weight. The score is
# 100 * (1 - exp(-raw / scale)): one strong cue reads about 50, two about 75,
# three or more 90+. A slur scores high on its own by weight - that is the
# point of measuring it, so the scientists can see the dispute it drew.
OUTLANDISH1 = {
    "id": "OUTLANDISH1", "family": "MEASURE", "label": "The OUTLANDISH meter (measure, never filter)",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "Scores every aired spoken line 0-100 for outlandish / appalling / inappropriate content. "
                   "It never filters: a high score goes to the audit log, raises the next seat's dispute odds "
                   "(OUTDISPUTE1) and wakes the SFX Guy's reaction roll (SFXREACT1). Items are cues: the text is "
                   "the pattern, the weight x10 its points. Category weight = the tag's multiplier. The dials "
                   "category holds the thresholds (x10).",
    "categories": [
        {"id": "conspiracy", "label": "Conspiracy", "weight": 1.0, "items": [
            _cue("conspiracy", "conspiracy / cover-up", r"\b(conspirac(?:y|ies)|cover[- ]?ups?|false flags?|psy-?ops?)\b", 3.0),
            _cue("chemtrails", "chemtrails, 5G, microchips", r"\b(chemtrails?|5g (?:tower|causes|is)|microchips? in|tracking chips?)\b", 3.5),
            _cue("reptilians", "lizard people / reptilians", r"\b(lizard (?:people|men)|reptilians?|shape-?shift)", 3.5),
            _cue("flat_earth", "flat / hollow earth", r"\b(flat[- ]earth|earth is (?:flat|hollow)|hollow earth)\b", 3.5),
            _cue("faked", "it was faked / staged / a hoax", r"\b(was (?:faked|staged|a hoax)|fake(?:d)? (?:moon|landing)|moon landing|hoax|crisis actors?|never happened)\b", 3.0),
            _cue("they_hide", "they don't want you to know", r"\b(they don'?t want you to know|wake up,? (?:people|sheeple)|sheeple|do your own research|the truth is out there)\b", 3.0),
            _cue("cabal", "deep state / illuminati / NWO", r"\b(deep state|illuminati|new world order|globalists?|the cabal|secret societ(?:y|ies)|big pharma)\b", 3.0),
            _cue("mind_control", "mind control / controlled", r"\b(mind control|brainwash(?:ed|ing)?|controlled demolition|population control)\b", 3.0),
        ]},
        {"id": "slur", "label": "Slur", "weight": 1.4, "items": [
            _cue("slur_race", "racial slur", r"\b(n[i1]gg(?:er|a|az)s?|k[i1]kes?|sp[i1]cs?|ch[i1]nks?|g[o0]{2}ks?|wetbacks?|beaners?|raghead|towelhead|coons?)\b", 5.0),
            _cue("slur_orient", "slur (orientation / gender)", r"\b(f[a@]gg?(?:ot)?s?|dykes?|trann(?:y|ies)|shemales?)\b", 5.0),
            _cue("slur_ability", "slur (ability)", r"\b(retard(?:ed|s)?|spaz|mongoloid|cripples?)\b", 4.0),
        ]},
        {"id": "violence", "label": "Violence", "weight": 1.0, "items": [
            _cue("kill", "kill / murder", r"\b(kill(?:ed|ing|s)?|murder(?:ed|ing|s)?|slaughter(?:ed)?|execut(?:e|ed|ion))\b(?! me\b| it\b)", 2.5),
            _cue("atrocity", "massacre / genocide / behead", r"\b(massacre|genocide|behead(?:ed|ing)?|lynch(?:ed|ing)?|ethnic cleansing)\b", 3.5),
            _cue("weapon", "shoot / stab / bomb", r"\b(shoot (?:him|her|them|you|up)|stab(?:bed|bing)?|bomb(?:ed|ing)? (?:the|a|them)|blow (?:it|them) up)\b", 3.0),
            _cue("harm", "beat / torture / burn it down", r"\b(beat (?:him|her|them|you) up|tortur(?:e|ed|ing)|burn (?:it|them|the \w+) down|strangl(?:e|ed))\b", 3.0),
            _cue("deserve_die", "deserves to die", r"\b(deserves? to die|should (?:be|all be) (?:shot|hanged|killed|executed)|put (?:them|him|her) down)\b", 4.0),
        ]},
        {"id": "shock", "label": "Shock claim", "weight": 1.0, "items": [
            _cue("taboo_act", "cannibalism / incest / eat people", r"\b(cannibal\w*|incest\w*|necrophil\w*|eat(?:ing)? (?:a |the )?(?:baby|babies|people|humans?|children))\b", 4.0),
            _cue("ban_absurd", "ban / abolish something basic", r"\b(?:ban|abolish|outlaw) (?:the )?(?:sun|oxygen|water|children|women|men|voting|sleep|gravity)\b", 3.0),
            _cue("group_claim", "sweeping claim about a group", r"\b(?:all|every|no) (?:women|men|immigrants|foreigners|old people|kids|children|christians|muslims|jews|atheists|scientists|doctors) (?:are|should|can'?t|deserve)\b", 3.5),
            _cue("they_lie", "scientists / doctors are lying", r"\b(?:scientists|doctors|the government|the media|nasa) (?:are|is) (?:lying|lie|in on it|hiding)\b", 3.0),
            _cue("certainty", "certainty markers (trust me, fact)", r"\b(trust me|i swear|that'?s a fact|it'?s a fact|everyone knows|proven fact|100 percent true|the real truth)\b", 1.5),
        ]},
        {"id": "absurdity", "label": "Absurdity", "weight": 0.8, "items": [
            _cue("aliens", "aliens / UFOs / bigfoot", r"\b(aliens?|ufos?|flying saucers?|bigfoot|sasquatch|loch ness)\b", 2.0),
            _cue("time_travel", "time travel / clones / simulation", r"\b(time[- ]travel\w*|clones?|clon(?:ed|ing)|(?:we|it) (?:live|is) in a simulation|parallel universe)\b", 2.0),
            _cue("birds", "birds aren't real / pigeons are drones", r"\b(birds? (?:aren'?t|are not) real|pigeons? (?:are|work for)|drones? (?:disguised|pretending))\b", 3.0),
            _cue("undead", "ghosts / vampires / immortal", r"\b(ghosts?|haunted|vampires?|werewolf|werewolves|immortal|telepath\w*|psychic)\b", 1.5),
            _cue("dinos", "dinosaurs alive / moon is cheese", r"\b(dinosaurs? (?:are|still) alive|moon is (?:made|hollow|fake|cheese))\b", 3.0),
            _cue("hyperbole", "impossible numbers", r"\b(a (?:million|billion|thousand) percent|\d{4,} percent|infinity percent)\b", 1.5),
        ]},
        {"id": "insult", "label": "Insult", "weight": 0.8, "items": [
            _cue("dumb", "idiot / moron / stupid", r"\b(idiots?|morons?|stupid|imbeciles?|dumbass\w*|cretins?|dimwits?|numpt(?:y|ies))\b", 1.5),
            _cue("scum", "scum / trash / pathetic", r"\b(scum(?:bag)?s?|trash|garbage (?:person|human)|pathetic|losers?|disgusting|vermin)\b", 1.8),
            _cue("shut_up", "shut up", r"\b(shut (?:up|your mouth|it)|nobody asked)\b", 1.2),
        ]},
        {"id": "obscene", "label": "Obscene", "weight": 0.8, "items": [
            _cue("swear", "swearing", r"\b(fuck\w*|shit\w*|bollocks|bastards?|bitch\w*|wank\w*|twats?|arse ?holes?|asshole\w*)\b", 1.2),
            _cue("slur_sex", "c-word / whore / slut", r"\b(cunts?|whores?|sluts?)\b", 2.5),
            _cue("sexual", "sexual", r"\b(porn\w*|orgasm\w*|genital\w*|horny|naked|sex(?:ual|ually)?|cock|dick|pussy)\b", 1.5),
        ]},
        {"id": "taboo", "label": "Taboo", "weight": 0.9, "items": [
            _cue("drugs", "hard drugs", r"\b(cocaine|heroin|meth(?:amphetamine)?|crack pipe|ketamine|overdos\w*|fentanyl)\b", 1.8),
            _cue("self_harm", "suicide", r"\b(suicide|kill (?:my|your|him|her)sel(?:f|ves))\b", 2.5),
            _cue("extremism", "nazi / hitler / kkk / eugenics", r"\b(nazis?|hitler|holocaust|kkk|white power|racial purity|eugenics|master race)\b", 3.5),
            _cue("blasphemy", "satan / antichrist", r"\b(satan\w*|antichrist|devil worship\w*|blasphem\w*)\b", 1.5),
        ]},
        {"id": "dials", "label": "Dials (not a tag)", "weight": 0.0, "items": [
            _dial("audit_at", "audit log from (x10)", 5.0, "a line at or above this score goes to the AUDIT log"),
            _dial("react_at", "SFX Guy reacts from (x10)", 6.0, "at or above this score SFXREACT1 rolls"),
            _dial("dispute_at", "dispute odds rise from (x10)", 4.0, "at or above this score the next seat's dispute rows weigh up (OUTDISPUTE1)"),
            _dial("scale", "score scale (x10)", 4.0, "raw points at which the score reads 63"),
            _dial("cap", "most points one tag can add (x10)", 6.0),
            _dial("caps", "points per shouted word, 2+ words (x1)", 0.6),
            _dial("bang", "points per ! up to three (x1)", 0.5),
            _dial("model_pass", "model pass share (/5; 0 = off)", 0.0,
                  "blend of an idle-only, lowest-priority model reading into the rule score"),
            _dial("model_min", "model pass asks from rule score (x10)", 2.0,
                  "only lines whose rule score is at least this are sent to the model pass"),
            _dial("model_per_hour", "model pass at most per hour (x10)", 6.0),
        ]},
    ],
}

OUTDISPUTE1 = {
    "id": "OUTDISPUTE1", "family": "MEASURE", "label": "After an outlandish line: the dispute odds",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "After a line scores at or above `from`, the next seat's RS/IRS rows named here weigh more: "
                   "the item's weight is the multiplier at score 100, ramping from x1 at `from`. The id names the "
                   "row as FAMILY:category (or FAMILY:item). Recorded as a reason on every candidate it touches.",
    "categories": [
        {"id": "after_high", "label": "Rows that weigh up", "weight": 1.0, "items": [
            {"id": "RS:argue", "label": "RS argue", "weight": 2.6},
            {"id": "RS:push_back", "label": "RS push back", "weight": 2.4},
            {"id": "RS:oppositional", "label": "RS oppositional", "weight": 2.4},
            {"id": "IRS:refutation", "label": "IRS refutation", "weight": 2.6},
            {"id": "IRS:confrontational", "label": "IRS confrontational", "weight": 2.0},
            {"id": "IRS:opposite", "label": "IRS opposite", "weight": 1.8},
            {"id": "RS:supportive", "label": "RS supportive (weighs down)", "weight": 0.5},
            {"id": "IRS:yield", "label": "IRS yield (weighs down)", "weight": 0.6},
        ]},
        {"id": "dials", "label": "Dials", "weight": 0.0, "items": [
            _dial("from", "the ramp starts at score (x10)", 4.0),
        ]},
    ],
}


def _react(id_, label, weight, tags, words):
    return {"id": id_, "label": label, "weight": weight, "tags": dict(tags),
            "items": [{"id": "w%d" % i, "label": w, "text": w, "weight": 1.0} for i, w in enumerate(words)]}


SFXREACT1 = {
    "id": "SFXREACT1", "family": "SFXREACT", "label": "The SFX Guy's reaction (after an outlandish line)",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "When a line scores at the meter's react threshold, the SFX Guy rolls a reaction topic, weighted "
                   "by the score and the line's tags (a category's `tags` in its advanced JSON), then scrolls his "
                   "repertoire and the clip search for a matching clip - MP4-only when the slider says so, never a "
                   "clip heard inside the day. It plays after the line and before the reply. Items are the words "
                   "the search uses. Dials: odds (/5) at the react threshold and at 100.",
    "categories": [
        _react("gasp", "Gasp", 1.0, {"shock": 1.6, "violence": 1.4, "slur": 1.5, "taboo": 1.4},
               ["gasp", "oh my god", "shocked", "omg", "no way"]),
        _react("boo", "Boo", 0.9, {"slur": 1.8, "insult": 1.4, "extremism": 1.5, "taboo": 1.3},
               ["boo", "booing", "crowd boo", "hiss"]),
        _react("record_scratch", "Record scratch", 1.0, {"absurdity": 1.5, "conspiracy": 1.4, "shock": 1.2},
               ["record scratch", "scratch", "needle", "stop"]),
        _react("what", "\"What?!\"", 1.0, {"absurdity": 1.6, "conspiracy": 1.5, "shock": 1.3},
               ["what", "wait what", "excuse me", "huh"]),
        _react("uproar", "Crowd uproar", 0.8, {"violence": 1.4, "slur": 1.4, "shock": 1.3, "obscene": 1.2},
               ["crowd", "uproar", "riot", "audience", "outrage"]),
        _react("sad_trombone", "Sad trombone", 0.9, {"absurdity": 1.4, "conspiracy": 1.3, "insult": 1.1},
               ["sad trombone", "wah wah", "trombone", "fail"]),
        _react("cringe", "Cringe", 0.8, {"obscene": 1.6, "insult": 1.3, "taboo": 1.2},
               ["cringe", "awkward", "yikes", "oof"]),
        _react("laugh", "Laugh", 0.7, {"absurdity": 1.5, "insult": 1.2},
               ["laugh", "laughing", "laugh track", "haha"]),
        _react("fail", "Fail", 0.7, {"absurdity": 1.3, "conspiracy": 1.2},
               ["fail", "game over", "you died", "wasted", "error"]),
        _react("victory", "Victory", 0.4, {"shock": 1.1},
               ["victory", "level up", "achievement", "winner"]),
        _react("rimshot", "Rimshot", 0.6, {"absurdity": 1.3, "insult": 1.2},
               ["rimshot", "ba dum tss", "drum"]),
        _react("crickets", "Crickets", 0.5, {"absurdity": 1.2},
               ["crickets", "silence", "awkward silence"]),
        {"id": "dials", "label": "Dials", "weight": 0.0, "tags": {}, "items": [
            _dial("odds_at_react", "odds at the react threshold (/5)", 3.5),
            _dial("odds_at_100", "odds at score 100 (/5)", 4.75),
            _dial("shortlist", "clips on his shortlist per roll (x10)", 2.4),
            _dial("max_seconds", "longest reaction clip, seconds (x10)", 0.8),
        ]},
    ],
}

CUTIN1 = {
    "id": "CUTIN1", "family": "CUTIN", "label": "Cut-ins (a word in edgewise on a long turn)",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "On each long host turn a chance die rolls whether another seat cuts in edgewise. The odds rise "
                   "with the turn's planned length. A hit is a real turn in the round: its own ES and RS roll, its "
                   "words drawn off INTERJECT1 (or the desk's diatribe list) as its Rolodex, and the first speaker "
                   "carries on over it. `who` picks the seat that cuts in. Dials: odds /5, words x10.",
    "categories": [
        {"id": "who", "label": "Who cuts in", "weight": 1.0, "items": [
            {"id": "other_host", "label": "the other host", "weight": 1.0, "text": "other_host"},
            {"id": "third", "label": "the third seat", "weight": 0.4, "text": "third"},
        ]},
        {"id": "dials", "label": "Dials", "weight": 0.0, "items": [
            _dial("min_words", "a turn is long from (words, x10)", 3.0),
            _dial("base", "odds at that length (/5)", 0.4),
            _dial("per_10", "odds added per 10 more words (/5)", 0.25),
            _dial("max", "odds at most (/5)", 3.0),
            _dial("per_round", "cut-ins per round at most (x1)", 2.0),
        ]},
    ],
}

MINIROUND1 = {
    "id": "MINIROUND1", "family": "MINIROUND", "label": "An interjection's mini-round (reply, rebuttal, exit)",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "After an interjection lands (a reaction, an outburst, a claim) it always grows into a mini-round: "
                   "a reply, a rebuttal, then this exit roll decides how it ends. `turns` in an item's advanced "
                   "JSON is the whole exchange with the interjection as turn one. Holding lines and bumpers never "
                   "take one.",
    "categories": [
        {"id": "exit", "label": "How it ends", "weight": 1.0, "items": [
            {"id": "lands", "label": "a last word lands", "weight": 1.0, "turns": 4,
             "text": "the one the rebuttal hit gets a last word, and it ends there"},
            {"id": "rebuttal_stands", "label": "the rebuttal stands", "weight": 0.6, "turns": 3,
             "text": "the rebuttal is the last word"},
            {"id": "one_more", "label": "one more pass", "weight": 0.5, "turns": 6,
             "text": "it goes round once more: reply and rebuttal again, then a last word"},
        ]},
    ],
}

HOLDBANTER1 = {
    "id": "HOLDBANTER1", "family": "HOLD", "label": "When the pipeline is behind: a hosts' aside",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "Replaces the old holding lines (\"the next conversation is taking a little longer\"). When the "
                   "station is short of rendered talk, the hosts toss off a quick, in-character, standalone aside - "
                   "rolled like everything else (this subject, the seat, then the aside road's own ES and running "
                   "order) and it never mentions waiting - beside the SFX Guy's time-buying clips. Dials: the share "
                   "of holding moments that get an aside (/5).",
    "categories": [
        {"id": "gripe", "label": "A gripe", "weight": 1.0, "items": [
            {"id": "studio_gripe", "label": "studio gripe", "text": "a quick in-character gripe about something small in the studio right now"},
            {"id": "pet_peeve", "label": "pet peeve", "text": "a pet peeve, stated like a law of physics"},
        ]},
        {"id": "confession", "label": "A confession", "weight": 0.8, "items": [
            {"id": "confession", "label": "confession", "text": "a small, slightly embarrassing confession, told straight"},
            {"id": "bad_habit", "label": "bad habit", "text": "admits a bad habit and defends it badly"},
        ]},
        {"id": "hot_take", "label": "A hot take", "weight": 1.0, "items": [
            {"id": "hot_take", "label": "hot take", "text": "an unprompted hot take on something ordinary, stated with total conviction"},
            {"id": "ranking", "label": "ranking", "text": "ranks three ordinary things and will not explain the order"},
        ]},
        {"id": "memory", "label": "A memory", "weight": 0.7, "items": [
            {"id": "memory", "label": "memory", "text": "a vivid little memory that has nothing to do with anything"},
        ]},
        {"id": "seat", "label": "Who says it", "weight": 0.0, "items": [
            {"id": "A", "label": "the host", "weight": 1.0, "text": "dj"},
            {"id": "B", "label": "the co-host", "weight": 1.0, "text": "cohost"},
            {"id": "D", "label": "the third seat", "weight": 0.4, "text": "third"},
        ]},
        {"id": "dials", "label": "Dials", "weight": 0.0, "items": [
            _dial("banter_share", "holding moments that get an aside (/5)", 3.0),
        ]},
    ],
}


def default_tables() -> list[dict[str, Any]]:
    return copy.deepcopy([OUTLANDISH1, OUTDISPUTE1, SFXREACT1, CUTIN1, MINIROUND1, HOLDBANTER1])


_DEFAULTS = {t["id"]: t for t in (OUTLANDISH1, OUTDISPUTE1, SFXREACT1, CUTIN1, MINIROUND1, HOLDBANTER1)}


def table_of(config: Any, tid: str, fallback: bool = True) -> dict[str, Any] | None:
    """The config's table `tid` (enabled), else the default when `fallback`."""
    for t in ((config or {}).get("tables") or []) if isinstance(config, dict) else []:
        if isinstance(t, dict) and t.get("id") == tid:
            return t if t.get("enabled", True) else None
    return _DEFAULTS.get(tid) if fallback else None


def has_table(config: Any, tid: str) -> bool:
    return table_of(config, tid, fallback=False) is not None


def dials(table: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    for cat in (table or {}).get("categories") or []:
        if cat.get("id") != "dials":
            continue
        for it in cat.get("items") or []:
            if it.get("enabled", True) is False:
                continue
            try:
                out[str(it.get("id"))] = float(it.get("weight", 0) or 0)
            except (TypeError, ValueError):
                continue
    return out


def dial(table: Any, key: str, default: float, scale: str = "x10") -> float:
    """A dial's value: x10 (points/scores), /5 (odds), raw."""
    got = dials(table)
    if key not in got:
        return float(default)
    v = got[key]
    return v * 10.0 if scale == "x10" else (max(0.0, min(1.0, v / 5.0)) if scale == "/5" else v)


def thresholds(table: Any = None) -> dict[str, float]:
    t = table or OUTLANDISH1
    return {"audit": dial(t, "audit_at", 50), "react": dial(t, "react_at", 60),
            "dispute": dial(t, "dispute_at", 40)}


# --- the rule pass --------------------------------------------------------------
_RX_CACHE: dict[str, Any] = {}
_CAPS = re.compile(r"\b[A-Z]{3,}\b")
_NOT_SHOUT = frozenset({"DJ", "FM", "AM", "MX", "SFX", "USA", "UK", "NASA", "FBI", "CIA", "TV", "OK", "NYC", "LA",
                        "AI", "BBC", "CNN", "UFO", "UFOS", "KKK", "LOL", "OMG", "PINE", "BOX"})


def _rx(pattern: str):
    got = _RX_CACHE.get(pattern)
    if got is None:
        try:
            got = re.compile(pattern, re.I)
        except re.error:
            got = False
        _RX_CACHE[pattern] = got
        if len(_RX_CACHE) > 4000:
            _RX_CACHE.clear()
    return got or None


def level_of(score: float, table: Any = None) -> str:
    th = thresholds(table)
    if score >= th["react"]:
        return "high"
    if score >= th["audit"]:
        return "audit"
    if score >= th["dispute"]:
        return "dispute"
    return "low" if score > 0 else "none"


def score(text: Any, table: Any = None, model: dict[str, Any] | None = None) -> dict[str, Any]:
    """The meter's reading of one line: score 0-100, tags, and every cue it
    matched (its reasons). `model` is an optional model-pass reading
    {score, tags} blended in at the model_pass dial. Never raises."""
    t0 = time.perf_counter()
    t = table or OUTLANDISH1
    s = " ".join(str(text or "").split())
    cap = dial(t, "cap", 60)
    parts: dict[str, float] = {}
    cues: list[dict[str, Any]] = []
    for cat in t.get("categories") or []:
        cid = str(cat.get("id") or "")
        if cid == "dials" or not s:
            continue
        cw = float(cat.get("weight", 1.0) or 0)
        if cw <= 0:
            continue
        got = 0.0
        for it in cat.get("items") or []:
            if it.get("enabled", True) is False:
                continue
            rx = _rx(str(it.get("text") or ""))
            if rx is None:
                continue
            m = rx.search(s)
            if not m:
                continue
            pts = max(0.0, float(it.get("weight", 0) or 0)) * 10.0
            got += pts
            cues.append({"tag": cid, "id": str(it.get("id")), "label": str(it.get("label") or it.get("id")),
                         "match": m.group(0)[:60], "points": round(pts * cw, 2)})
        if got > 0:
            parts[cid] = round(min(cap, got) * cw, 2)
    style: dict[str, Any] = {}
    shout = [w for w in _CAPS.findall(s) if w not in _NOT_SHOUT]
    if len(shout) >= 2:
        style["shouted"] = len(shout)
        parts["_style"] = parts.get("_style", 0.0) + min(5, len(shout)) * dial(t, "caps", 0.6, "raw")
    bangs = s.count("!")
    if bangs:
        style["bangs"] = bangs
        parts["_style"] = parts.get("_style", 0.0) + min(3, bangs) * dial(t, "bang", 0.5, "raw")
    raw = sum(parts.values())
    sc = max(1.0, dial(t, "scale", 40))
    rule = 0.0 if raw <= 0 else round(100.0 * (1.0 - math.exp(-raw / sc)), 1)
    tags = [k for k, _v in sorted(parts.items(), key=lambda kv: -kv[1]) if not k.startswith("_")]
    out = {"score": int(round(rule)), "rule_score": rule, "raw": round(raw, 2), "tags": tags,
           "parts": {k: round(v, 2) for k, v in parts.items()}, "cues": cues, "style": style,
           "table": str(t.get("id") or "OUTLANDISH1"), "version": int(t.get("version") or 1),
           "engine": VERSION}
    share = dial(t, "model_pass", 0.0, "/5")
    if isinstance(model, dict) and model.get("score") is not None and share > 0:
        try:
            ms = max(0.0, min(100.0, float(model["score"])))
            out["model"] = {"score": ms, "tags": list(model.get("tags") or [])[:6], "share": share,
                            "ms": model.get("ms")}
            out["score"] = int(round((1 - share) * rule + share * ms))
            for tg in out["model"]["tags"]:
                if tg not in out["tags"]:
                    out["tags"].append(str(tg))
        except (TypeError, ValueError):
            pass
    out["level"] = level_of(out["score"], t)
    out["rule_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
    return out


def headline(result: dict[str, Any]) -> str:
    """"OUTLANDISH 82 · conspiracy, slur"."""
    tags = ", ".join((result or {}).get("tags") or []) or "clean"
    return "OUTLANDISH %d · %s" % (int((result or {}).get("score") or 0), tags)


def text_key(text: Any) -> str:
    return hashlib.sha1(" ".join(str(text or "").lower().split()).encode("utf-8")).hexdigest()[:16]


def measure_event(result: dict[str, Any], conversation_id: str = "", turn_id: str = "", line_id: str = "",
                  who: str = "", text: str = "", at: float | None = None) -> dict[str, Any]:
    """The reading as a System 3 decision-shaped record: stages the roll tiles
    already draw (the tags as the category wheel, the cues as the item wheel),
    its "die" is the score. Not a roll - the meter's reading - and it says so."""
    r = result or {}
    parts = {k: v for k, v in (r.get("parts") or {}).items() if not str(k).startswith("_")}
    total = sum(parts.values()) or 1.0
    sc = int(r.get("score") or 0)
    draw = {"label": "OUTLANDISH:meter", "u": round(sc / 100.0, 4), "dice": sc}
    if parts:
        tag_rows = [{"id": k, "label": "%s %d" % (k, int(round(v))), "base": v, "weight": v,
                     "p": round(v / total, 4),
                     "why": [c["label"] + ": \"" + c["match"] + "\"" for c in r.get("cues") or [] if c["tag"] == k]}
                    for k, v in sorted(parts.items(), key=lambda kv: -kv[1])]
    else:
        tag_rows = [{"id": "clean", "label": "clean", "base": 1.0, "weight": 1.0, "p": 1.0, "why": ["no cue matched"]}]
    cue_rows = [{"id": c["id"], "label": "%s · %s" % (c["label"], c["match"]), "base": c["points"],
                 "weight": c["points"], "p": 0.0, "why": [c["tag"]]} for c in (r.get("cues") or [])[:12]]
    ctotal = sum(c["weight"] for c in cue_rows) or 1.0
    for c in cue_rows:
        c["p"] = round(c["weight"] / ctotal, 4)
    stages = [{"stage": "category", "candidates": tag_rows, "excluded": [], "total": round(total, 2),
               "draw": draw, "selected": tag_rows[0]["id"], "selected_index": 1, "of": len(tag_rows),
               "rule": "the meter's reading: the tags by their points (not a draw)"}]
    if cue_rows:
        stages.append({"stage": "item", "candidates": cue_rows, "excluded": [], "total": round(ctotal, 2),
                       "draw": None, "selected": cue_rows[0]["id"], "selected_index": 1, "of": len(cue_rows)})
    cid = str(conversation_id or "")
    lid = str(line_id or "")
    return {"schema": "system3-measure/1", "kind": "observation", "family": "MEASURE",
            "event_id": "%s:m:%s" % (cid or "line", lid or text_key(text)),
            "conversation_id": cid, "turn_id": str(turn_id or ""), "line_id": lid, "lines": [lid] if lid else [],
            "who": str(who or ""), "at": float(at or time.time()), "stages": stages, "rng": draw,
            "selected": {"table": r.get("table") or "OUTLANDISH1", "id": r.get("level") or "none",
                         "label": headline(r), "category": tag_rows[0]["id"],
                         "category_label": tag_rows[0]["label"], "score": sc, "tags": list(r.get("tags") or []),
                         "index": 1, "of": len(tag_rows)},
            "measure": {k: r.get(k) for k in ("score", "rule_score", "raw", "tags", "parts", "cues", "style",
                                              "level", "version", "model", "rule_ms")},
            "meta": {"measure": True, "why": "the meter's reading on the line's words - it measures, it never filters",
                     "engine": VERSION}}


# --- the dispute that follows -----------------------------------------------------
def dispute_boost(score_value: float, table: Any = None) -> dict[str, float]:
    """{"RS:argue": 2.1, ...}: the multipliers for the next seat's rows."""
    t = table or OUTDISPUTE1
    start = dial(t, "from", 40)
    sc = float(score_value or 0)
    if sc < start:
        return {}
    ramp = 1.0 if start >= 100 else max(0.0, min(1.0, (sc - start) / (100.0 - start)))
    out = {}
    for cat in t.get("categories") or []:
        if cat.get("id") == "dials":
            continue
        for it in cat.get("items") or []:
            if it.get("enabled", True) is False:
                continue
            w = max(0.0, float(it.get("weight", 1.0) or 0))
            out[str(it.get("id"))] = round(1.0 + (w - 1.0) * ramp, 4)
    return out


def boost_for(spec: dict[str, Any], boost: dict[str, float]) -> tuple[float, str]:
    """The multiplier one candidate takes from a boost, and its key."""
    if not boost or not isinstance(spec, dict):
        return 1.0, ""
    fam = str(spec.get("family") or "")
    for key in ("%s:%s" % (fam, spec.get("category")), "%s:%s" % (fam, spec.get("id"))):
        if key in boost:
            return float(boost[key]), key
    return 1.0, ""


def is_dispute(decisions: Iterable[Any]) -> bool:
    keys = set()
    for d in decisions or ():
        if not isinstance(d, dict):
            continue
        fam = str(d.get("family") or "")
        for k in ("category", "item"):
            if d.get(k):
                keys.add("%s:%s" % (fam, d[k]))
    return bool(keys & set(DISPUTE_KEYS))


def follow_of(turns: list[dict[str, Any]], index: int, aired_turn_ids: Iterable[str], look: int = 3) -> dict[str, Any]:
    """Did a dispute follow turn `index`? The next `look` turns by another seat:
    one with a dispute roll -> aired (its line went out) or planned_cut; none ->
    none. {state, turn, turn_id, why}."""
    aired = set(str(x) for x in aired_turn_ids or ())
    if not (0 <= index < len(turns or [])):
        return {"state": "none", "why": "the line is not a planned turn"}
    me = turns[index].get("speaker")
    seen = 0
    for t in turns[index + 1:]:
        if t.get("speaker") == me:
            continue
        seen += 1
        if is_dispute(t.get("decisions") or []):
            tid = str(t.get("turn_id") or "")
            return {"state": "aired" if tid in aired else "planned_cut", "turn": t.get("index"), "turn_id": tid,
                    "speaker": t.get("speaker"),
                    "why": "turn %d rolled a dispute%s" % (int(t.get("index", 0)) + 1,
                                                           "" if tid in aired else " but never aired")}
        if seen >= look:
            break
    return {"state": "none", "why": "no dispute rolled in the next %d turns by another seat" % look}


# --- draws (uniforms come from the caller) ------------------------------------------
def _pick(weights: list[float], u: float) -> int:
    total = sum(w for w in weights if w > 0)
    if total <= 0:
        return -1
    x = max(0.0, min(0.999999, float(u))) * total
    acc = 0.0
    for i, w in enumerate(weights):
        if w <= 0:
            continue
        acc += w
        if x < acc:
            return i
    return max(i for i, w in enumerate(weights) if w > 0)


def _dice(u: float) -> int:
    return int(max(0.0, min(0.999999, float(u))) * 100) + 1


def _stage(name, rows, k, u, rule=""):
    total = sum(r["weight"] for r in rows) or 0.0
    st = {"stage": name, "candidates": [{"id": r["id"], "label": r["label"], "base": round(r.get("base", r["weight"]), 4),
                                         "weight": round(r["weight"], 4),
                                         "p": round(r["weight"] / total, 4) if total else 0.0,
                                         "why": list(r.get("why") or [])} for r in rows],
          "excluded": [], "total": round(total, 4),
          "draw": ({"u": round(float(u), 6), "dice": _dice(u), "label": name} if u is not None else None),
          "selected": rows[k]["id"] if k >= 0 else None, "selected_index": k + 1 if k >= 0 else 0, "of": len(rows)}
    if rule:
        st["rule"] = rule
    return st


def react_plan(result: dict[str, Any], table: Any = None, u_speak: float = 0.0, u_cat: float = 0.0,
               meter: Any = None) -> dict[str, Any]:
    """Does the SFX Guy react, and with which topic. {react, category, label,
    words, odds, stages, event}. Below the react threshold: no roll at all."""
    t = table or SFXREACT1
    sc = float((result or {}).get("score") or 0)
    th = thresholds(meter)["react"]
    if sc < th:
        return {"react": False, "why": "score %d is under the react threshold %d" % (sc, th), "stages": []}
    lo, hi = dial(t, "odds_at_react", 3.5, "/5"), dial(t, "odds_at_100", 4.75, "/5")
    ramp = 1.0 if th >= 100 else max(0.0, min(1.0, (sc - th) / (100.0 - th)))
    odds = round(lo + (hi - lo) * ramp, 4)
    speak = float(u_speak) < odds
    stages = [{"stage": "dice", "draw": {"u": round(float(u_speak), 6), "dice": _dice(u_speak), "label": "SFXREACT:speak"},
               "threshold": odds, "rule": "he reacts when u < %.2f (score %d between %d and 100)" % (odds, sc, th),
               "selected": "REACT" if speak else "PASS"}]
    out = {"react": speak, "odds": odds, "stages": stages, "score": sc}
    if not speak:
        out["why"] = "the dice said pass"
        return out
    tags = list((result or {}).get("tags") or [])
    rows = []
    for cat in t.get("categories") or []:
        if cat.get("id") == "dials":
            continue
        base = float(cat.get("weight", 1.0) or 0)
        w, why = base, []
        aff = cat.get("tags") if isinstance(cat.get("tags"), dict) else {}
        for tg in tags:
            if tg in aff:
                m = max(0.0, float(aff[tg]))
                w *= m
                why.append("the line is %s x%.2f" % (tg, m))
        if w <= 0:
            continue
        rows.append({"id": str(cat["id"]), "label": str(cat.get("label") or cat["id"]), "base": base, "weight": w,
                     "why": why, "words": [str(i.get("text") or i.get("label") or "") for i in cat.get("items") or []
                                           if i.get("enabled", True) is not False]})
    k = _pick([r["weight"] for r in rows], u_cat)
    if k < 0:
        out.update(react=False, why="no reaction topic has weight")
        return out
    stages.append(_stage("category", rows, k, u_cat))
    out.update(category=rows[k]["id"], label=rows[k]["label"], words=rows[k]["words"])
    return out


def clip_stage(cands: list[dict[str, Any]], u: float) -> tuple[int, dict[str, Any]]:
    """The draw among the clips he scrolled: [{id, label, weight, why}]."""
    k = _pick([float(c.get("weight") or 0) for c in cands], u)
    return k, _stage("item", [dict(c, weight=float(c.get("weight") or 0)) for c in cands], k, u,
                     rule="the repertoire's shortlist and the clip search, by fit, your votes and freshness")


def react_event(plan: dict[str, Any], result: dict[str, Any], conversation_id: str = "", turn_id: str = "",
                line_id: str = "", clip: dict[str, Any] | None = None, table_id: str = "SFXREACT1") -> dict[str, Any]:
    stages = list(plan.get("stages") or [])
    if clip and clip.get("stage"):
        stages.append(clip["stage"])
    rng = stages[-1].get("draw") if stages and stages[-1].get("draw") else (stages[0].get("draw") if stages else None)
    label = ("reacts: %s" % plan.get("label")) if plan.get("react") else "keeps his hands off the board"
    if clip and clip.get("name"):
        label += " · " + str(clip["name"])[:60]
    if clip and clip.get("source"):
        label += " (" + str(clip["source"]) + ")"
    return {"schema": "system3-measure/1", "kind": "observation", "family": "SFXREACT",
            "event_id": "%s:r:%s" % (conversation_id or "line", line_id or text_key(label)),
            "conversation_id": str(conversation_id or ""), "turn_id": str(turn_id or ""),
            "line_id": str(line_id or ""), "lines": [str(line_id)] if line_id else [], "at": time.time(),
            "stages": stages, "rng": rng,
            "selected": {"table": table_id, "id": plan.get("category") or ("PASS" if not plan.get("react") else ""),
                         "label": label, "category": plan.get("category") or "",
                         "category_label": plan.get("label") or "", "clip": (clip or {}).get("path", "")},
            "meta": {"after_score": (result or {}).get("score"), "tags": (result or {}).get("tags"),
                     "odds": plan.get("odds"), "why": plan.get("why", "")}}


def miniround_plan(table: Any = None, u: float = 0.0) -> dict[str, Any]:
    t = table or MINIROUND1
    rows = []
    for cat in t.get("categories") or []:
        if cat.get("id") != "exit":
            continue
        for it in cat.get("items") or []:
            if it.get("enabled", True) is False:
                continue
            rows.append({"id": str(it["id"]), "label": str(it.get("label") or it["id"]),
                         "weight": max(0.0, float(it.get("weight", 1.0) or 0)),
                         "turns": max(3, min(8, int(it.get("turns") or 4))), "text": str(it.get("text") or "")})
    k = _pick([r["weight"] for r in rows], u)
    if k < 0:
        return {"turns": 4, "exit": "lands", "stages": [], "why": "no exit row has weight: a last word lands"}
    return {"turns": rows[k]["turns"], "exit": rows[k]["id"], "label": rows[k]["label"], "text": rows[k]["text"],
            "stages": [_stage("item", rows, k, u, rule="the exit roll: how the mini-round ends")]}


def miniround_until(conv: dict[str, Any], config: Any) -> int | None:
    """[outl-mini] An interjection's exchange is a mini-round: reply, rebuttal,
    then the exit roll (MINIROUND1) says how many turns it runs. Recorded as a
    MINIROUND decision on the conversation, off its own stream (seed|miniround)
    so the round's other draws are untouched. None (the road's own length) when
    the table is absent, or the line is a sound or a one-liner."""
    if not has_table(config, "MINIROUND1"):
        return None
    inputs = conv.get("inputs") or {}
    roles = inputs.get("roles") or {}
    seat = str(inputs.get("line_seat") or (inputs.get("seats") or [""])[0])
    if roles.get(seat) == "board" or inputs.get("one_line"):
        return None
    import system3                                        # the engine (loaded: it called us)
    own = system3.DrawStream(str(conv["seed"]) + "|miniround", int(conv.get("miniround_draws") or 0))
    d = own.next("MINIROUND:exit")
    conv["miniround_draws"] = own.n
    plan = miniround_plan(table_of(config, "MINIROUND1"), d["u"])
    stages = plan.get("stages") or []
    if stages:
        stages[0]["draw"] = d
    sel = {"id": plan.get("exit"), "table": "MINIROUND1",
           "label": "a mini-round of %d turns: the line, a reply, a rebuttal%s" % (
               plan["turns"], {"lands": ", a last word", "one_more": ", once more round, a last word"}.get(
                   plan.get("exit"), "")),
           "text": plan.get("text", "")}
    ev = system3._event(conv, {"turn_id": "", "turn_index": -1}, "MINIROUND", stages, sel,
                        system3._snapshot(conv, seat), rng=d,
                        meta={"why": "an interjection always grows into a mini-round; this roll is how it ends",
                              "stream": "its own (seed|miniround)"})
    conv["miniround"] = {"turns": plan["turns"], "exit": plan.get("exit"), "event_id": ev["event_id"]}
    return int(plan["turns"])


def cutin_odds(words: float, table: Any = None) -> tuple[float, str]:
    t = table or CUTIN1
    mn = dial(t, "min_words", 30)
    if float(words or 0) < mn:
        return 0.0, "%d words is under the long-turn mark (%d)" % (int(words or 0), int(mn))
    base, per, top = dial(t, "base", 0.5, "/5"), dial(t, "per_10", 0.25, "/5"), dial(t, "max", 3.0, "/5")
    odds = round(min(top, base + per * (float(words) - mn) / 10.0), 4)
    return odds, "%d words: %.2f + %.2f per 10 words over %d, at most %.2f" % (int(words), base, per, int(mn), top)


def cutin_seat_rows(table: Any = None) -> list[dict[str, Any]]:
    t = table or CUTIN1
    for cat in t.get("categories") or []:
        if cat.get("id") == "who":
            return [{"id": str(i["id"]), "label": str(i.get("label") or i["id"]),
                     "weight": max(0.0, float(i.get("weight", 1.0) or 0)), "text": str(i.get("text") or i["id"])}
                    for i in cat.get("items") or [] if i.get("enabled", True) is not False]
    return [{"id": "other_host", "label": "the other host", "weight": 1.0, "text": "other_host"}]


def hold_plan(table: Any = None, u_share: float = 0.0, u_cat: float = 0.0, u_item: float = 0.0,
              u_seat: float = 0.0) -> dict[str, Any]:
    """The holding moment: an aside (subject + seat) or the SFX Guy alone."""
    t = table or HOLDBANTER1
    share = dial(t, "banter_share", 3.0, "/5")
    aside = float(u_share) < share
    stages = [{"stage": "dice", "draw": {"u": round(float(u_share), 6), "dice": _dice(u_share), "label": "HOLD:aside"},
               "threshold": share, "rule": "an aside when u < %.2f, else the SFX Guy's time-buyers alone" % share,
               "selected": "ASIDE" if aside else "SFX"}]
    out: dict[str, Any] = {"aside": aside, "share": share, "stages": stages}
    if not aside:
        return out
    cats = [c for c in t.get("categories") or [] if c.get("id") not in ("dials", "seat")
            and float(c.get("weight", 1.0) or 0) > 0 and c.get("items")]
    rows = [{"id": str(c["id"]), "label": str(c.get("label") or c["id"]), "weight": float(c.get("weight", 1.0))}
            for c in cats]
    k = _pick([r["weight"] for r in rows], u_cat)
    if k < 0:
        out["aside"] = False
        return out
    stages.append(_stage("category", rows, k, u_cat))
    items = [{"id": str(i["id"]), "label": str(i.get("label") or i["id"]), "text": str(i.get("text") or ""),
              "weight": max(0.0, float(i.get("weight", 1.0) or 0))} for i in cats[k].get("items") or []
             if i.get("enabled", True) is not False]
    j = _pick([i["weight"] for i in items], u_item)
    if j < 0:
        out["aside"] = False
        return out
    stages.append(_stage("item", items, j, u_item))
    seats = []
    for c in t.get("categories") or []:
        if c.get("id") == "seat":
            seats = [{"id": str(i["id"]), "label": str(i.get("label") or i["id"]), "text": str(i.get("text") or ""),
                      "weight": max(0.0, float(i.get("weight", 1.0) or 0))} for i in c.get("items") or []
                     if i.get("enabled", True) is not False]
    seats = seats or [{"id": "A", "label": "the host", "text": "dj", "weight": 1.0}]
    s = _pick([x["weight"] for x in seats], u_seat)
    stages.append(_stage("seat", seats, s, u_seat))
    out.update(subject=rows[k]["id"], item=items[j]["id"], direction=items[j]["text"],
               seat=seats[s]["id"], who=seats[s]["text"] or "dj")
    return out


def hold_direction(plan: dict[str, Any]) -> str:
    """The aside's direction for the writer: in character, standalone, and
    never a word about waiting, preparing or what comes next."""
    return ("A QUICK ASIDE, IN CHARACTER: %s. One or two sentences, standalone, said as if it just occurred to "
            "you. Do NOT mention waiting, preparing, the next conversation, the studio being busy or anything "
            "coming up." % str(plan.get("direction") or "a passing thought"))


# --- the model pass (optional, idle-only, lowest priority) ----------------------
MODEL_PROMPT = ("Rate how outlandish, appalling or inappropriate this radio line is, from 0 (ordinary) to 100 "
                "(wildly outlandish or offensive). This is measurement only; nothing is removed. Reply with JSON "
                "only: {\"score\": <0-100>, \"tags\": [up to 3 of conspiracy, slur, violence, shock, absurdity, "
                "insult, obscene, taboo]}.\nLINE: ")


def model_prompt(text: Any) -> str:
    return MODEL_PROMPT + " ".join(str(text or "").split())[:600]


def parse_model(reply: Any) -> dict[str, Any] | None:
    s = str(reply or "")
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        return None
    try:
        got = json.loads(m.group(0))
        sc = max(0.0, min(100.0, float(got.get("score"))))
        tags = [str(x).lower() for x in (got.get("tags") or []) if isinstance(x, str)][:3]
        return {"score": sc, "tags": tags}
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


# --- validation (System 3's validate_table hands these families here) -------------
def validate_table(table: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(table, dict):
        raise ValueError("a table is an object")
    tid = str(table.get("id") or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,23}", tid):
        raise ValueError("table id must be a short name such as OUTLANDISH2")
    fam = str(table.get("family") or "")
    if fam not in FAMILIES:
        raise ValueError("family must be one of " + ", ".join(FAMILIES))
    cats = table.get("categories")
    if not isinstance(cats, list) or not cats:
        raise ValueError("a table needs at least one category")
    out = copy.deepcopy(table)
    out["id"], out["family"] = tid, fam
    out["weight"] = max(0.0, float(table.get("weight", 1.0) or 0))
    out["enabled"] = bool(table.get("enabled", True))
    out["version"] = int(table.get("version") or 1)
    seen = set()
    for cat in out["categories"]:
        if not isinstance(cat, dict) or not str(cat.get("id") or "").strip():
            raise ValueError("every category needs an id")
        cat["weight"] = max(0.0, float(cat.get("weight", 1.0) or 0))
        if "tags" in cat and not isinstance(cat["tags"], dict):
            raise ValueError("category %s: tags is {tag: multiplier}" % cat["id"])
        items = cat.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("category %s has no items" % cat["id"])
        for it in items:
            if not isinstance(it, dict) or not str(it.get("id") or "").strip():
                raise ValueError("every item needs an id")
            key = (cat["id"], it["id"])
            if key in seen:
                raise ValueError("duplicate item %s/%s" % key)
            seen.add(key)
            it["weight"] = max(0.0, float(it.get("weight", 1.0) or 0))
            it.setdefault("label", it["id"])
            if fam == "MEASURE" and tid.startswith("OUTLANDISH") and cat["id"] != "dials":
                try:
                    re.compile(str(it.get("text") or ""), re.I)
                except re.error as exc:
                    raise ValueError("cue %s/%s is not a pattern: %s" % (cat["id"], it["id"], exc)) from exc
                if not str(it.get("text") or "").strip():
                    raise ValueError("cue %s/%s has no pattern" % (cat["id"], it["id"]))
            if fam == "MINIROUND" and "turns" in it:
                it["turns"] = max(3, min(8, int(it.get("turns") or 4)))
    return out

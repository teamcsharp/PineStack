"""[s3-gold] GOLD IS A REPLY THE ROULETTE CAN LAND ON.

The operator, 2026-09-29: "The gold system will need to be fully transitioned
to system 3, made into an option for the roulette to access as a reply
possibility. By chance the people in the booth should roll a dice for a chance
to say a gold line."

A gold line is a line the station kept (gold_bars.json: rhymed, recorded,
liked). Until now it reached the air FORCED - a run of bars poured into a gap
(gold_fill_gap), or a bar dropped into a live round at a sting moment
(gold_in_round_due) - with a roll only on whether the road fired. Here it is a
reply option on System 3's node:

  1. On a host seat's REPLY turn (never the opener, never the close, never a
     turn whose words are already fixed, never a caller), System 3 rolls the
     GOLD die off the GOLD1 table's `gold.reply` row: the "gold" item's weight
     against the "own words" item's weight is the chance.
  2. On a hit a second roll picks WHICH gold line, among the bank the station
     hands in (inputs["gold_bank"]: System 3-minted bars, none heard inside the
     last 24 hours - the station strikes those before anything is rolled).
     Each candidate's weight is the table's `gold.seat` row (a line this seat
     said itself / another seat's) times its `gold.topic` row (shares words
     with this exchange / about something else), scaled by how much of it this
     exchange shares and eased for a line fired often. Relevance wins when
     there is any.
  3. The turn carries the line (turn["gold"]); the writer is told the seat
     answers with these exact words - a callback - and the DIRECTION FOR THIS
     LINE / emotion roll still governs the delivery: the words are fixed, the
     performance follows the roll.

Every draw is on the round's own GOLD stream (seed|gold), so no other family's
dice move and the golden trajectory is untouched; with no gold bank in the
inputs (a replay, a test fixture, the table switched off) nothing is drawn.
Both rolls are one GOLD decision event on the turn: why_line / the Rolodex read
"rolled gold 7 of 40".

GOLD1 is a POOL-family table (the dice door's format: each category id is a
key, its items weighted) so the Tables editor shows and edits it like any
other; it reaches a stored config once through the runtime's
add_missing_default_tables, and never touches DEFAULT_TABLES (the default
config hash is pinned).
"""
from __future__ import annotations

import copy
import re
from typing import Any

TABLE_ID = "GOLD1"
REPLY_KEY = "gold.reply"
SEAT_KEY = "gold.seat"
TOPIC_KEY = "gold.topic"
HOST_ROLES = ("dj", "cohost", "third")
MOST_A_ROUND = 1                 # at most one gold reply a round (the table's "most" overrides)
BANK_MOST = 80

GOLD1 = {
    "id": TABLE_ID, "family": "POOL", "label": "Gold lines as replies (the booth rolls for a kept line)",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "On a host's reply turn System 3 rolls gold.reply: the 'gold' weight against the 'own words' "
                   "weight is the chance the seat answers with a line the station kept, word for word. On a hit "
                   "it rolls which one, weighted by gold.seat and gold.topic. Lines heard in the last 24 hours "
                   "are never offered. Switch the table off and no gold line is rolled.",
    "most": MOST_A_ROUND,
    "categories": [
        {"id": REPLY_KEY, "label": "Does the seat reply with a gold line?", "weight": 1.0, "items": [
            {"id": "gold", "label": "a gold line, as the reply", "text": "a gold line, as the reply",
             "weight": 8.0, "enabled": True},
            {"id": "own", "label": "their own words", "text": "their own words", "weight": 92.0, "enabled": True},
        ]},
        {"id": SEAT_KEY, "label": "Whose gold line", "weight": 1.0, "items": [
            {"id": "same_seat", "label": "a line this seat said itself", "text": "a line this seat said itself",
             "weight": 2.0, "enabled": True},
            {"id": "other_seat", "label": "a line another seat said", "text": "a line another seat said",
             "weight": 1.0, "enabled": True},
        ]},
        {"id": TOPIC_KEY, "label": "Relevance to this exchange", "weight": 1.0, "items": [
            {"id": "on_subject", "label": "shares words with this exchange", "text": "shares words with this exchange",
             "weight": 4.0, "enabled": True},
            {"id": "off_subject", "label": "about something else", "text": "about something else",
             "weight": 1.0, "enabled": True},
        ]},
    ],
}

_STOP = frozenset("""a about above after again against all am an and any are as at be because been before being
below between both but by can did do does doing down during each few for from further had has have having he her
here hers herself him himself his how i if in into is it its itself just me more most my myself no nor not now of
off on once only or other our ours out over own same she should so some such than that the their theirs them then
there these they this those through to too under until up very was we were what when where which while who whom why
will with you your yours yeah okay oh like get got gonna really thing things know think""".split())


def default_tables() -> list[dict[str, Any]]:
    return [copy.deepcopy(GOLD1)]


def words(text: Any) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z']{2,}", str(text or "").lower()) if w not in _STOP}


def _table(config: Any) -> dict[str, Any] | None:
    for t in (config or {}).get("tables") or []:
        if isinstance(t, dict) and t.get("id") == TABLE_ID:
            return t if t.get("enabled", True) is not False else None
    return None


def _weights(table: dict[str, Any], cat_id: str) -> dict[str, float]:
    for c in table.get("categories") or []:
        if isinstance(c, dict) and c.get("id") == cat_id and c.get("enabled", True) is not False:
            out = {}
            for it in c.get("items") or []:
                if isinstance(it, dict) and it.get("id"):
                    try:
                        w = float(it.get("weight", 1.0) or 0)
                    except (TypeError, ValueError):
                        w = 0.0
                    out[str(it["id"])] = w if it.get("enabled", True) is not False else 0.0
            return out
    return {}


def relevance(line: Any, context: set[str]) -> float:
    """How much of the gold line this exchange shares: 0..1 of its content words."""
    mine = words(line)
    if not mine or not context:
        return 0.0
    return len(mine & context) / float(len(mine))


def exchange_words(conv: dict[str, Any]) -> set[str]:
    subj = conv.get("subject") or {}
    bits = [subj.get("topic"), subj.get("angle"), " ".join(subj.get("keywords") or [])]
    for t in (conv.get("turns") or [])[-3:]:
        bits.append((t.get("bank_topic") or {}).get("text"))
        bits.append((t.get("topic_material") or {}).get("text"))
        bits.append(t.get("text"))
    return words(" ".join(str(b or "") for b in bits))


def decide(s3: Any, conv: dict[str, Any], config: dict[str, Any], turn: dict[str, Any], idx: int, want: int,
           inputs: dict[str, Any], closing: bool = False) -> dict[str, Any] | None:
    """The GOLD roll on one turn (see the module note). Returns the turn's gold
    ({id, text, who, index, of, dice, event_id}) on a hit, else None. Records
    one GOLD decision event whenever a die is cast; casts none when the turn
    cannot take a gold reply."""
    bank = [g for g in (inputs.get("gold_bank") or []) if isinstance(g, dict)
            and str(g.get("id") or "") and str(g.get("text") or "").strip()]
    if not bank or closing or idx <= 0 or idx >= want - 1:
        return None
    table = _table(config)
    if table is None:
        return None
    if turn.get("bank_topic") or turn.get("bank_topic_reply") or turn.get("topic_override"):
        return None
    if str(turn.get("step") or "") in ("interject", "carry_on"):
        return None
    turns = conv.get("turns") or []
    prev = turns[-1] if turns else None
    if not prev or prev.get("speaker") == turn.get("speaker"):
        return None                                      # a reply answers somebody else
    me = s3.participant(conv, turn.get("speaker"))
    role = str((me or {}).get("role") or "")
    if role not in HOST_ROLES:
        return None                                      # a caller never speaks the station's kept lines
    used = list(conv.get("gold_used") or [])
    most = int(table.get("most", MOST_A_ROUND) or 0)
    if most <= 0 or len(used) >= most:
        return None
    reply = _weights(table, REPLY_KEY)
    wg, wo = max(0.0, reply.get("gold", 0.0)), max(0.0, reply.get("own", 0.0))
    if wg <= 0:
        return None
    p = wg / (wg + wo) if (wg + wo) > 0 else 0.0
    own = s3.DrawStream(str(conv["seed"]) + "|gold", int(conv.get("gold_draws") or 0))
    before = s3._snapshot(conv, turn.get("speaker"))
    d = own.next("GOLD:dice")
    hit = d["u"] < p
    stages = [{"stage": "dice", "draw": d, "threshold": round(p, 4),
               "rule": "a gold reply when u < %.3f - gold %.0f : own words %.0f on %s"
                       % (p, wg, wo, REPLY_KEY),
               "selected": "GOLD" if hit else "OWN"}]
    picked = None
    k = -1
    rows: list[dict[str, Any]] = []
    cands: list[dict[str, Any]] = []
    if hit:
        seatw = _weights(table, SEAT_KEY)
        topicw = _weights(table, TOPIC_KEY)
        ctxw = exchange_words(conv)
        cands = [g for g in bank if str(g["id"]) not in used][:BANK_MOST]
        for g in cands:
            rel = relevance(g.get("text"), ctxw)
            same = str(g.get("who") or "") == role
            sw = float(seatw.get("same_seat" if same else "other_seat", 1.0))
            tw = float(topicw.get("on_subject" if rel > 0 else "off_subject", 1.0))
            fired = max(0, int(g.get("fired") or 0))
            w = sw * tw * (1.0 + 3.0 * rel) / (1.0 + 0.25 * fired)
            why = ["%s (%s x%.1f)" % ("this seat's own line" if same else "another seat's line",
                                      SEAT_KEY, sw),
                   "%s (%s x%.1f)" % ("shares %.0f%% of its words with this exchange" % (rel * 100) if rel > 0
                                      else "about something else", TOPIC_KEY, tw)]
            if fired:
                why.append("fired %d time(s) before" % fired)
            rows.append({"id": str(g["id"]), "label": s3.label_cut(g["text"]),
                         "base": 1.0, "weight": round(max(0.0, w), 6), "why": why})
        if rows and sum(r["weight"] for r in rows) > 0:
            d2 = own.next("GOLD:item")
            k = s3.pick_index([r["weight"] for r in rows], d2["u"])
            if k >= 0:
                stages.append(s3._stage("item", rows, k, d2))
                picked = cands[k]
        if picked is None:
            stages.append({"stage": "item", "draw": None, "selected": None,
                           "rule": "a hit, but no gold line could be offered (all heard today, or none weighted)"})
    conv["gold_draws"] = own.n
    if picked is not None:
        sel = {"id": str(picked["id"]), "label": "rolled gold %d of %d: %s" % (k + 1, len(rows),
                                                                               s3.label_cut(picked["text"])),
               "index": k + 1, "of": len(rows)}
    else:
        sel = {"id": "OWN" if not hit else "NONE",
               "label": "their own words" if not hit else "a gold hit with nothing to offer"}
    ev = s3._event(conv, {"turn_id": turn["turn_id"], "turn_index": turn["index"]}, "GOLD", stages, sel, before,
                   meta={"table": TABLE_ID, "chance": round(p, 4), "bank": len(bank), "offered": len(rows),
                         "stream": "its own (seed|gold): the round's draws are untouched",
                         "why": "a host's reply turn: the booth rolls for a kept line"}, rng=d)
    ev["state_after"] = before
    dec = {"family": "GOLD", "event_id": ev["event_id"], "item": sel["id"] if picked is not None else None,
           "label": sel["label"]}
    turn["decisions"].append(dec)
    if picked is None:
        return None
    gold = {"id": str(picked["id"]), "text": " ".join(str(picked["text"]).split()),
            "who": str(picked.get("who") or ""), "index": k + 1, "of": len(rows),
            "dice": [d["dice"], stages[-1]["draw"]["dice"]], "event_id": ev["event_id"]}
    turn["gold"] = gold
    conv["gold_used"] = used + [gold["id"]]
    return gold

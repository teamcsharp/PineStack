#!/usr/bin/env python3
"""[outlandish] system3.py: the meter's structure inside the engine.

  S1 [outl-families]     validate_table hands MEASURE/SFXREACT/CUTIN/MINIROUND/HOLD to outlandish.py
  S2 [outl-dispute]      _decide_turn: the line before is measured (a written turn in Mode B,
                         a line road's own words); the reading is a MEASURE decision on it
  S3 [outl-dispute-odds] _item_factor: at/above the dispute threshold the next seat's RS/IRS
                         rows weigh up by OUTDISPUTE1, the reason recorded on every candidate
  S4 [outl-cutin]        _round_rolls: with CUTIN1 the single INTERJECT roll gives way to a
                         chance die on every long host turn
  S5 [outl-cutin-turn]   _interject_after dispatches to the cut-in node
  S7 [outl-dispute-why]  weighted_decision: a category's row says the boost its items took
  S6 [outl-fns]          the functions (no stream is drawn for the meter; the cut-in has its
                         own stream seed|cutin)
Without OUTLANDISH1 / CUTIN1 in the config nothing changes: the golden trajectory stands.

usage: outlandish_system3_patch.py --check|--apply system3.py   (0 ready, 2 applied, 1 missing)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outlandish_patchlib import run  # noqa: E402

FNS = '''# --- [outl-fns] THE OUTLANDISH METER'S STRUCTURE (outlandish.py) ------------------------
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


'''

EDITS = [
    ("[outl-families]", "after",
     '    if family in ("MGRTOPIC", "MGRSUB"):                  # [s3-mgrtopics] the manager\'s topics, his sub messages\n'
     '        import system3_mgrtopics\n'
     '        return system3_mgrtopics.validate_table(table)\n',
     '    if family in ("MEASURE", "SFXREACT", "CUTIN", "MINIROUND", "HOLD"):      # [outl-families] the meter\'s tables\n'
     '        import outlandish\n'
     '        return outlandish.validate_table(table)\n'),
    ("[outl-dispute]", "after",
     '           "prev_lean": prev_lean,\n'
     '           "event_emotions": _event_emotions(conv, idx)}                     # [s3-events]\n',
     '    _outl = _outlandish_ctx(conv, config, prev, inputs, idx)                  # [outl-dispute] the line before, measured\n'
     '    if _outl:\n'
     '        ctx["outlandish"] = _outl\n'),
    ("[outl-dispute-odds]", "before",
     '    recent = _recent_items(conv, spec["family"], 6)\n',
     '    _ob = (ctx.get("outlandish") or {}).get("boost")                         # [outl-dispute-odds]\n'
     '    if _ob and spec["family"] in ("RS", "IRS"):\n'
     '        _om, _ok = _outlandish_mult(spec, _ob)\n'
     '        if _ok and abs(_om - 1) > 0.005:\n'
     '            reasons.append("after an outlandish line (%d) %s x%.2f"\n'
     '                           % (int(ctx["outlandish"].get("score") or 0), _ok, _om))\n'
     '            f *= _om\n'),
    ("[outl-cutin]", "after",
     '    table_rows = _round_rows(config, "INTERJECT")\n',
     '    if _cutin_setup(conv, config, inputs, phrases, table_rows, banter, hosts):    # [outl-cutin] CUTIN1 per long turn\n'
     '        phrases, table_rows = [], []\n'),
    ("[outl-cutin-turn]", "after",
     '    so the seat order the bind aligns on is exactly what the writer is told."""\n',
     '    if isinstance(conv.get("cutin"), dict):                                   # [outl-cutin-turn]\n'
     '        return _cutin_after(conv, config, settings, stream, want, inputs, seats)\n'),
    ("[outl-dispute-why]", "replace",
     '                         "why": ["mean eligible item weight %.3f" % mean] if items else [],\n',
     '                         "why": ((["mean eligible item weight %.3f" % mean] if items else [])   # [outl-dispute-why]\n'
     '                                 + sorted({w for i in items for w in i["why"]\n'
     '                                           if w.startswith("after an outlandish")})[:2]),\n'),
    ("[outl-fns]", "before",
     'def _interject_after(conv, config, settings, stream, want, inputs, seats):\n', FNS),
]


if __name__ == "__main__":
    sys.exit(run(EDITS, sys.argv))

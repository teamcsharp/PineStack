"""System 3's TOPIC roll: the operator's topics board, through the roulette.

Operator, 2026-09-27: "Topic should be accessed via the RNG system on the
roulette rolodex allowing for it come up naturally in conversation." and
"the entire dialogue system is now being built by the RNG system. Nothing
should be automatically wedged into conversation"
(tools/rng_topics_patch.py turns the station's own topic roads off).

Three draws per round, all recorded as one TOPIC decision event:
  dice       does something off the board come up at all - the `topics`
             control, 0.5 -> 40% of rounds, 1.0 -> 80%, 0 -> never
  item       which topic - the least-sprung weigh most, 1/(1 + uses)
  turn       which turn raises it - never the opener or the close, so it
             arrives in a conversation already going; on a phone call only
             a turn the protocol leaves open (#1392)
The chosen turn answers the line before it as the dice said, and then it
"puts them in mind of" the topic, brought up in their own words; a board
entry written "1. ... 2. ..." is said word for word there and answered word
for word on the next turn. A round without a board in its inputs draws
nothing, so every conversation planned before this replays unchanged; a
round carrying the operator's own exchange does not roll (that exchange IS
its subject).

Edits system3.py (the engine) and system3_runtime.py (the board goes into
a round's inputs; a raised topic counts as a use). Idempotent: --check
exits 0 when every edit can apply, 2 when already applied, 1 when an anchor
is missing; --apply writes the files.
"""
import sys
from pathlib import Path

ENGINE = [
    ('FAMILIES = ("CTS", "ES", "RS", "IRS", "FL", "SPEAKERBOX", "SFX")\n',
     'FAMILIES = ("CTS", "ES", "RS", "IRS", "FL", "SPEAKERBOX", "SFX", "TOPIC")\n'),
    ('    "closure_aggressiveness": 0.5,\n'
     '}\n',
     '    "closure_aggressiveness": 0.5,\n'
     '    # [rng-topics] how often something off the operator\'s topics board\n'
     '    # comes up: rate = TOPIC_RATE_AT_FULL x this (0.5 -> 40% of rounds).\n'
     '    "topics": 0.5,\n'
     '}\n'),
    ('SECONDS_PER_WORD = 0.4          # 150 wpm; recalibrated from rendered audio\n',
     'SECONDS_PER_WORD = 0.4          # 150 wpm; recalibrated from rendered audio\n'
     'TOPIC_RATE_AT_FULL = 0.8        # [rng-topics] the TOPIC dice at topics = 1.0\n'),
    # the roll itself, beside the other per-round planning
    ('def plan_more(conv, config, until=None, inputs=None):\n',
     'def _topic_decision(conv, settings, stream, inputs, want, open_turns=None, replies=True):\n'
     '    """[rng-topics] THE OPERATOR\'S TOPICS BOARD, THROUGH THE ROULETTE.\n'
     '\n'
     '    Three recorded draws: whether something off the board comes up in\n'
     '    this round (the `topics` control), which one (the least-sprung weigh\n'
     '    most) and on which turn (never the opener or the close; on a call,\n'
     '    only a turn the protocol leaves open). The plan is kept on the\n'
     '    aggregate and the turn takes it when it is planned. No board in the\n'
     '    inputs: nothing is drawn, so older conversations replay unchanged."""\n'
     '    if conv.get("topic_plan") is not None:\n'
     '        return None\n'
     '    bank = [t for t in (inputs.get("topic_bank") or [])\n'
     '            if isinstance(t, dict) and t.get("id") and str(t.get("text") or "").strip()]\n'
     '    if not bank:\n'
     '        return None\n'
     '    ctx = {"turn_id": "", "turn_index": -1}\n'
     '    before = _snapshot(conv)\n'
     '    control = clamp((settings.get("controls") or {}).get("topics", DEFAULT_CONTROLS["topics"]))\n'
     '    rate = round(TOPIC_RATE_AT_FULL * control, 4)\n'
     '    meta = {"rate": rate, "control": round(control, 3), "bank": len(bank)}\n'
     '    if (conv["subject"].get("exchange") or {}).get("opener"):\n'
     '        conv["topic_plan"] = {}\n'
     '        return _event(conv, ctx, "TOPIC", [], {"id": "NONE", "label": "the round carries the operator\'s own exchange"},\n'
     '                      before, meta=dict(meta, applies=False, why="the operator\'s own exchange is this round\'s subject"))\n'
     '    slots = [i for i in (open_turns if open_turns is not None else range(want))\n'
     '             if 0 < i < want - 1]\n'
     '    d = stream.next("TOPIC:dice")\n'
     '    rows = [{"id": "RAISE", "label": "something off the board comes up", "base": rate, "weight": rate,\n'
     '             "why": ["topics control %.2f x %.1f" % (control, TOPIC_RATE_AT_FULL)]},\n'
     '            {"id": "NONE", "label": "nothing off the board this round", "base": round(1 - rate, 4),\n'
     '             "weight": round(1 - rate, 4), "why": []}]\n'
     '    pick = pick_index([r["weight"] for r in rows], d["u"])\n'
     '    stages = [_stage("dice", rows, pick, d)]\n'
     '    if pick < 0 or rows[pick]["id"] != "RAISE" or not slots:\n'
     '        conv["topic_plan"] = {}\n'
     '        why = "" if slots else "no turn in the middle of this round to raise it on"\n'
     '        return _event(conv, ctx, "TOPIC", stages, {"id": "NONE", "label": "nothing off the board this round"},\n'
     '                      before, meta=dict(meta, why=why) if why else meta, rng=d)\n'
     '    d2 = stream.next("TOPIC:item")\n'
     '    trows = [{"id": str(t["id"]), "label": " ".join(str(t["text"]).split())[:90], "base": 1.0,\n'
     '              "weight": round(1.0 / (1 + max(0, int(t.get("used") or 0))), 4),\n'
     '              "why": ["sprung %d time(s)" % int(t.get("used") or 0)]} for t in bank]\n'
     '    tpick = pick_index([r["weight"] for r in trows], d2["u"])\n'
     '    stages.append(_stage("item", trows, tpick, d2))\n'
     '    chosen = bank[tpick]\n'
     '    reply = " ".join(str(chosen.get("reply") or "").split())[:400] if replies else ""\n'
     '    if reply:\n'
     '        slots = [i for i in slots if i + 1 < want] or slots\n'
     '    d3 = stream.next("TOPIC:turn")\n'
     '    srows = [{"id": "t%d" % i, "label": "turn %d" % (i + 1), "base": 1.0, "weight": 1.0, "why": []}\n'
     '             for i in slots]\n'
     '    spick = pick_index([r["weight"] for r in srows], d3["u"])\n'
     '    stages.append(_stage("turn", srows, spick, d3))\n'
     '    plan = {"id": str(chosen["id"]), "text": " ".join(str(chosen["text"]).split())[:400],\n'
     '            "reply": reply, "turn_index": slots[spick]}\n'
     '    ev = _event(conv, ctx, "TOPIC", stages, {"id": plan["id"], "label": plan["text"][:90]}, before,\n'
     '                meta=dict(meta, turn_index=plan["turn_index"], reply=bool(reply)), rng=d2)\n'
     '    plan["event_id"] = ev["event_id"]\n'
     '    conv["topic_plan"] = plan\n'
     '    conv.setdefault("topics_used", []).append(plan["id"])\n'
     '    return ev\n'
     '\n'
     '\n'
     'def plan_more(conv, config, until=None, inputs=None):\n'),
    ('    guard = 0\n'
     '    while len(conv["turns"]) < want and guard < 400:\n',
     '    if not conv["turns"]:\n'
     '        # [rng-topics] once per round, before its first turn, against the\n'
     '        # whole budget (Mode B plans a turn at a time).\n'
     '        _topic_decision(conv, settings, stream, inputs, int(conv["timing"]["turn_budget"] or want))\n'
     '    guard = 0\n'
     '    while len(conv["turns"]) < want and guard < 400:\n'),
    ('    stream = DrawStream(conv["seed"], conv.get("draws", 0))\n'
     '    want = len(rows)\n'
     '    for number, seat, work in rows:\n',
     '    stream = DrawStream(conv["seed"], conv.get("draws", 0))\n'
     '    want = len(rows)\n'
     '    # [rng-topics] a call keeps its legs: only a turn the protocol leaves\n'
     '    # open may raise something off the board, and in its own words.\n'
     '    _topic_decision(conv, conv["settings"], stream, inputs, want, replies=False,\n'
     '                    open_turns=[i for i, (_n, _s, _w) in enumerate(rows) if _PROTOCOL_OPEN.search(_w or "")])\n'
     '    for number, seat, work in rows:\n'),
    # CTS1's "From Topics Database" names a real entry, drawn and recorded
    ('    turn["topic_change"] = True\n'
     '    if spec.get("resolver") == "speakbox":\n',
     '    turn["topic_change"] = True\n'
     '    if spec.get("category") == "topic":\n'
     '        # [rng-topics] THE TOPICS DATABASE, RESOLVED. CTS1\'s "From Topics\n'
     '        # Database" used to reach the writer as a bare direction - "raises\n'
     '        # the next subject from the station\'s topic book" - with no entry,\n'
     '        # so the writer invented one. It names a real one now, drawn here\n'
     '        # off the board (the least-sprung weigh most, none twice in a\n'
     '        # round) and recorded as this event\'s own stage.\n'
     '        _used = set(conv.get("topics_used") or [])\n'
     '        _bank = [t for t in (conv["inputs"].get("topic_bank") or [])\n'
     '                 if isinstance(t, dict) and t.get("id") and str(t["id"]) not in _used]\n'
     '        if _bank:\n'
     '            _d = stream.next("CTS:topic")\n'
     '            _rows = [{"id": str(t["id"]), "label": " ".join(str(t["text"]).split())[:90], "base": 1.0,\n'
     '                      "weight": round(1.0 / (1 + max(0, int(t.get("used") or 0))), 4),\n'
     '                      "why": ["sprung %d time(s)" % int(t.get("used") or 0)]} for t in _bank]\n'
     '            _k = pick_index([r["weight"] for r in _rows], _d["u"])\n'
     '            ev["stages"].append(_stage("topic", _rows, _k, _d))\n'
     '            _t = _bank[_k]\n'
     '            # no "file": the station stamps turns with a document\'s name and\n'
     '            # remembers it as a heard passage, and a board entry is neither\n'
     '            turn["topic_material"] = {"text": " ".join(str(_t["text"]).split())[:400],\n'
     '                                      "file": "", "source": "the topics board", "topic_id": str(_t["id"])}\n'
     '            ev["selected"]["topic"] = {"id": str(_t["id"]), "text": turn["topic_material"]["text"][:120]}\n'
     '            conv.setdefault("topics_used", []).append(str(_t["id"]))\n'
     '    if spec.get("resolver") == "speakbox":\n'),
    # the turn takes the plan when it is planned
    ('           "prev_lean": prev_lean}\n'
     '    draws = (config["structure"].get("closing") or {}).get("draws") if closing else step.get("draws")\n',
     '           "prev_lean": prev_lean}\n'
     '    tp = conv.get("topic_plan") or {}                                    # [rng-topics]\n'
     '    if tp.get("id") and tp.get("turn_index") == idx:\n'
     '        turn["bank_topic"] = {"id": tp["id"], "text": tp.get("text", ""), "reply": tp.get("reply", "")}\n'
     '        turn["decisions"].append({"family": "TOPIC", "event_id": tp.get("event_id", ""),\n'
     '                                  "item": tp["id"], "label": tp.get("text", "")[:90]})\n'
     '        for _ev in conv["decision_events"]:\n'
     '            if _ev["event_id"] == tp.get("event_id"):\n'
     '                _ev["turn_id"], _ev["turn_index"] = turn_id, idx\n'
     '    elif tp.get("id") and tp.get("reply") and tp.get("turn_index") == idx - 1:\n'
     '        turn["bank_topic_reply"] = tp["reply"]\n'
     '    draws = (config["structure"].get("closing") or {}).get("draws") if closing else step.get("draws")\n'),
    # the running order says it
    ('    answer_line = replying and turn["index"] == 1 and bool(exchange.get("reply"))\n'
     '    if answer_line:\n'
     '        desc = ("answers %s with these exact words, as written: %s" % (prev_name, json.dumps(exchange["reply"]))\n',
     '    # [rng-topics] ...and the answer to a "1. / 2." board entry the roulette\n'
     '    # raised on the turn before, said the same way.\n'
     '    answer_text = (exchange.get("reply") if turn["index"] == 1 and exchange.get("reply")\n'
     '                   else turn.get("bank_topic_reply") or "")\n'
     '    answer_line = replying and bool(answer_text)\n'
     '    if answer_line:\n'
     '        desc = ("answers %s with these exact words, as written: %s" % (prev_name, json.dumps(answer_text))\n'),
    ('    if replying and not answer_line:\n'
     '        body += (". Picks up a word or claim from %s\'s line and takes it somewhere new - "\n'
     '                 "never hands that line back as the whole turn" % prev_name)\n'
     '    return body.strip().rstrip(".") + "."\n',
     '    if replying and not answer_line:\n'
     '        body += (". Picks up a word or claim from %s\'s line and takes it somewhere new - "\n'
     '                 "never hands that line back as the whole turn" % prev_name)\n'
     '    topic = turn.get("bank_topic") or {}                                  # [rng-topics]\n'
     '    if topic.get("reply"):\n'
     '        body += (". Then, as though it has just come to mind, says these exact words, as written: %s"\n'
     '                 % json.dumps(topic["text"]))\n'
     '    elif topic.get("text"):\n'
     '        body += (". It puts them in mind of something off the operator\'s topics board, and they "\n'
     '                 "bring it up in their own words: %s" % json.dumps(topic["text"][:300]))\n'
     '    return body.strip().rstrip(".") + "."\n'),
    ('            if acts:\n'
     '                add += "; while doing it, " + acts[0]\n'
     '            add += ".]"\n',
     '            if acts:\n'
     '                add += "; while doing it, " + acts[0]\n'
     '            add += ".]"\n'
     '        topic = t.get("bank_topic") or {}                                 # [rng-topics]\n'
     '        if topic.get("text"):\n'
     '            add += (" [It puts them in mind of something off the operator\'s topics board, and "\n'
     '                    "they bring it up in their own words: %s.]" % json.dumps(topic["text"][:300]))\n'),
]

RUNTIME = [
    ('            "manager": False, "gallery": False, "topics": False, "research": False,\n'
     '        }\n',
     '            "manager": False, "gallery": False, "research": False,\n'
     '        }\n'
     '        # [rng-topics] the operator\'s topics board, for the TOPIC roll\n'
     '        topic_bank = self._topic_bank(ctx)\n'
     '        availability["topics"] = bool(topic_bank)\n'),
    ('            "seed_text": " ".join(seed_text.split())[:1500],\n'
     '        }\n',
     '            "seed_text": " ".join(seed_text.split())[:1500],\n'
     '            "topic_bank": topic_bank,\n'
     '        }\n'
     '\n'
     '    def _topic_bank(self, ctx):\n'
     '        """[rng-topics] The board, least-sprung first, as System 3\'s TOPIC\n'
     '        roll draws from it - the only road a topic takes into a round now.\n'
     '        Empty when the round carries the operator\'s own exchange, or on a\n'
     '        host with no board."""\n'
     '        if _exchange_of(ctx).get("opener"):\n'
     '            return []\n'
     '        try:\n'
     '            rows = self.host.read_bombshells() or []\n'
     '        except Exception:  # noqa: BLE001\n'
     '            return []\n'
     '        out = []\n'
     '        for r in rows:\n'
     '            if not isinstance(r, dict) or not r.get("id"):\n'
     '                continue\n'
     '            text = " ".join(str(r.get("text") or "").split())\n'
     '            if not 12 <= len(text) <= 400:\n'
     '                continue\n'
     '            out.append({"id": str(r["id"]), "text": text, "used": int(r.get("used") or 0),\n'
     '                        "reply": " ".join(str(r.get("reply") or "").split())[:400]})\n'
     '        out.sort(key=lambda r: r["used"])\n'
     '        return out[:60]\n'),
    ('            conv["plan"] = {"sheet": handle.sheet, "plan_ms": handle.plan_ms, "active": handle.active}\n',
     '            # [rng-topics] a topic the roulette raised on a round that airs is\n'
     '            # a use of it (the TOPIC roll or CTS1\'s topics database): the\n'
     '            # least-sprung weigh most at the next draw.\n'
     '            if handle.active:\n'
     '                for _tid in dict.fromkeys(conv.get("topics_used") or []):\n'
     '                    try:\n'
     '                        self.host.use_bombshell(_tid, "")\n'
     '                    except Exception:  # noqa: BLE001\n'
     '                        pass\n'
     '            conv["plan"] = {"sheet": handle.sheet, "plan_ms": handle.plan_ms, "active": handle.active}\n'),
]


def patch(path, edits, apply):
    text = Path(path).read_text(encoding="utf-8").replace("\r\n", "\n")
    todo = 0
    for old, new in edits:
        if new in text:
            continue
        if text.count(old) != 1:
            print("MISSING (%d) in %s: %r" % (text.count(old), path, old[:90]))
            return None
        text = text.replace(old, new)
        todo += 1
    return text, todo


def main(argv):
    apply = "--apply" in argv
    out = {}
    for path, edits in (("system3.py", ENGINE), ("system3_runtime.py", RUNTIME)):
        got = patch(path, edits, apply)
        if got is None:
            return 1
        out[path] = got
    todo = sum(n for _, n in out.values())
    if not todo:
        print("already applied")
        return 2
    if not apply:
        print("can apply: %d edit(s)" % todo)
        return 0
    for path, (text, n) in out.items():
        if n:
            Path(path).write_text(text, encoding="utf-8", newline="\n")
    print("applied: %d edit(s)" % todo)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Reply targets, nested exchanges and cast reactions on System Three's graph.

All elections use the planner's seeded stream and GRAPH decision ledger.
The extra-turn ceiling is an explicit operator budget, never a prose veto.
"""
import hashlib

DEFAULTS = {"enabled": True, "initiator_weight": 1.0, "last_weight": 1.0,
            "answer_weight": 2.0, "other_weight": 1.0, "return_weight": 2.0,
            "max_credits": 8, "react_all": True, "max_reaction_groups": 4}


def normalize(raw):
    source = raw if isinstance(raw, dict) else {}
    out = {"enabled": bool(source.get("enabled", True)), "react_all": bool(source.get("react_all", True))}
    for key, fallback in DEFAULTS.items():
        if key in out:
            continue
        try:
            val = float(source.get(key, fallback))
            if val != val or abs(val) == float("inf"):
                val = fallback
        except (TypeError, ValueError):
            val = fallback
        out[key] = int(max(0, min(32, val))) if key in ("max_credits", "max_reaction_groups") else round(max(0, min(100, val)), 3)
    return out


class Replies:
    def __init__(self, engine, conv, config, graph, stream, record, seats, inputs):
        self.e, self.conv, self.config = engine, conv, config
        self.cur, self.stream, self.record, self.seats, self.inputs = conv["cursor"], stream, record, seats, inputs
        self.settings = normalize(graph.get("reply_roulette"))

    def choose(self, stage, choices, meta):
        rows = [{"id": ident, "label": label, "base": weight, "weight": weight, "why": [reason]}
                for ident, label, weight, reason in choices]
        if not rows or not any(row["weight"] > 0 for row in rows):
            return None
        draw = self.stream.next("GRAPH:%s:%d" % (stage, len(self.conv["decision_events"])))
        pick = self.e.pick_index([r["weight"] for r in rows], draw["u"])
        self.last_event = self.record(stage, rows, pick, draw, meta)
        return rows[pick]["id"]

    def room(self):
        return int(self.cur.get("reply_credits", 0)) < self.settings["max_credits"]

    def credit(self):
        if not self.room():
            return 0
        self.cur["reply_credits"] = int(self.cur.get("reply_credits", 0)) + 1
        return 1

    def name(self, seat):
        return (self.e.participant(self.conv, seat) or {}).get("name") or seat

    def queue(self, seat, target, kind="reply"):
        self.cur.setdefault("reply_pending", []).append({"seat": seat, "target": target["turn_id"], "kind": kind})

    def reactions(self):
        if not self.settings["enabled"] or not self.settings["react_all"] or not self.conv["turns"]:
            return
        import outlandish
        if not outlandish.has_table(self.config, "OUTLANDISH1"):
            return
        prev = self.conv["turns"][-1]
        text = str(prev.get("text") or (self.inputs.get("line_text") if prev["index"] == 0 else "") or "")
        # observe() supplies the spoken text, including Speakerbox words.
        # An unresolved passage is not evidence of an extreme statement.
        if not text.strip():
            return
        key = prev["turn_id"] + ":" + hashlib.sha256(text.encode()).hexdigest()[:12]
        if key in self.cur.get("reaction_seen", []):
            return
        self.cur.setdefault("reaction_seen", []).append(key)
        meter = outlandish.table_of(self.config, "OUTLANDISH1")
        scored = outlandish.score(text, meter)
        if scored["score"] < outlandish.thresholds(meter)["react"]:
            return
        groups = int(self.cur.get("reaction_groups", 0))
        if groups >= self.settings["max_reaction_groups"]:
            self.conv.setdefault("reaction_limits", []).append({"source_turn": prev["turn_id"],
                "score": scored["score"], "why": "operator's cast reaction group budget exhausted"})
            return
        self.cur["reaction_groups"] = groups + 1
        # All present people get independent ES/RS rolls on their reaction turn.
        # Election changes their order; it never chooses one instead of the rest.
        remaining = [p["actor_id"] for p in self.conv["participants"] if p["actor_id"] != prev["speaker"]]
        ordered = []
        while remaining:
            seat = self.choose("reaction_order", [(s, self.name(s), 1, "present; reacting to the extreme line") for s in remaining],
                               {"source_turn": prev["turn_id"], "score": scored["score"], "tags": scored["tags"],
                                "turn_index": len(self.conv["turns"]) + len(ordered)})
            ordered.append({"seat": seat, "target": prev["turn_id"], "kind": "reaction"})
            remaining.remove(seat)
        # Interrupt a pending exchange and resume it after everybody's reaction.
        self.cur["reply_pending"] = ordered + self.cur.get("reply_pending", [])

    def pending_node(self, template):
        pending = self.cur.get("reply_pending") or []
        if not pending:
            return None
        entry = pending.pop(0)
        node = dict(template)
        node.update(id="__%s_%d" % (entry["kind"], len(self.conv["turns"])),
                    type="rebuttal" if entry["kind"] == "return" else "reply",
                    label="Cast reaction" if entry["kind"] == "reaction" else "Inner exchange",
                    speaker=entry["seat"], respond_to="", prompt="", target="",
                    draws=[{"family": "ES"}, {"family": "IRS" if entry["kind"] == "return" else "RS"}],
                    chance=1, seconds=12, speakerbox=[], splits=False,
                    reply_entry=entry)
        return node

    def target(self, node):
        if not self.settings["enabled"] or (node["type"] != "reply" and not node.get("reply_entry")) or node.get("respond_to"):
            return None, 0
        turns = self.conv["turns"]
        if not turns:
            return None, 0
        entry = node.get("reply_entry")
        if entry:
            target = next((t for t in turns if t["turn_id"] == entry["target"]), None)
            if entry["kind"] == "reaction":
                self.cur["reaction_credits"] = int(self.cur.get("reaction_credits", 0)) + 1
                return target, 1
            return target, self.credit() if entry["kind"] != "return" else 0
        last = turns[-1]
        initiator = self.cur["initiator"]
        opening = next((t for t in reversed(turns) if t.get("graph_type") == "initiator"), turns[0])
        original = next((t for t in reversed(turns[opening["index"]:]) if t["speaker"] == initiator), opening)
        distinct = last["speaker"] != initiator
        choices = [("initiator", self.name(initiator), self.settings["initiator_weight"], "reply to the topic instigator")]
        if distinct:
            choices.append(("last", self.name(last["speaker"]), self.settings["last_weight"] if self.room() else 0,
                            "reply to the latest speaker; restore this turn" if self.room() else "extra-turn budget exhausted"))
        target = self.choose("reply_target", choices, {"node": node["id"], "initiator": initiator,
                              "last_speaker": last["speaker"], "credits": self.cur.get("reply_credits", 0)})
        if target is None:
            return None, 0
        chosen, credit = (last, self.credit()) if target == "last" else (original, 0)
        self.last_event["meta"].update(target_turn_id=chosen["turn_id"], target_name=chosen["name"], turn_credit=credit)
        return chosen, credit

    def apply(self, turn, target, credit, node):
        if not target:
            return
        turn["reply_to"] = {"turn_id": target["turn_id"], "speaker": target["speaker"], "name": target["name"],
                            "index": target["index"]}
        turn["turn_credit"] = credit
        entry = node.get("reply_entry") or {}
        turn["inner_reply"] = entry.get("kind") != "return" and (bool(entry) or bool(credit))
        turn["cast_reaction"] = entry.get("kind") == "reaction"
        earlier_protocol = turn.get("protocol", "")
        turn["protocol"] = ("React to the extreme claim" if turn["cast_reaction"] else "Answer the actual point") + \
            " made by %s. Aim your rolled feeling at %s: make them feel heard through your own words, " \
            "attitude and delivery before adding your next point." % (target["name"], target["name"])
        if not turn["cast_reaction"]:
            turn["protocol"] = "It answers what %s just said. " % target["name"] + turn["protocol"]
        if entry.get("kind") == "return":
            turn["protocol"] += " As the topic instigator, take charge again and develop the main topic from this exchange. " + earlier_protocol
        # A stable machine annotation survives the human running-order parser.
        turn["protocol"] += " [reply-target=%d]" % (target["index"] + 1)

    def followup(self, turn):
        if not turn.get("inner_reply") or (self.cur.get("reply_pending") or []):
            return
        if turn.get("graph_type") != "reply" or not turn.get("reply_to"):
            return
        target = turn["reply_to"]["speaker"]
        initiator = self.cur["initiator"]
        other = [s for s in self.seats if s not in (turn["speaker"], target)]
        room = self.room()
        outcome = self.choose("reply_followup", [
            ("answer", self.name(target) + " answers back", self.settings["answer_weight"] if room else 0,
             "addressed person gets an answer roll" if room else "extra-turn budget exhausted"),
            ("other", "Another DJ joins", self.settings["other_weight"] if room and other else 0, "another present DJ may react"),
            ("return", self.name(initiator) + " resumes the topic", self.settings["return_weight"], "return to the mainline topic")],
            {"source_turn": turn["turn_id"], "credits": self.cur.get("reply_credits", 0), "max_credits": self.settings["max_credits"]})
        if outcome == "answer":
            self.queue(target, turn)
        elif outcome == "other":
            seat = self.choose("reply_speaker", [(s, self.name(s), 1, "present; joining the inner exchange") for s in other],
                               {"source_turn": turn["turn_id"]})
            self.queue(seat, turn)
        elif outcome == "return" and initiator != turn["speaker"]:
            self.queue(initiator, turn, "return")

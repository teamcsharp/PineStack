"""System 3's engine and ledger (docs/system3_blueprint.md section 20).

Unit tests for weighted selection, seeds, transitions, cooldowns, time
gating, config and serialisation; invariant tests over many seeds; a
golden-seed trajectory; decision replay; Mode B; the store."""
import copy
import json
import re
from pathlib import Path
import tempfile
import unittest

import system3
import system3_tables
from system3_store import System3Store


def inputs(**over):
    base = {"road": "banter", "seats": ["A", "B"], "turns": 10,
            "subject": {"topic": "raccoon van", "keywords": ["raccoon"]},
            "availability": {"speakbox": True},
            "speakerbox_rates": {"prepend": 0.49, "append": 0.68}}
    base.update(over)
    return base


def settings(**over):
    raw = {"mode": "active", "test_seed": "golden-1"}
    raw.update(over)
    return system3.normalise_settings(raw)


def plan(seed="golden-1", cid="golden", config=None, **over):
    return system3.plan_scene(inputs(**over), config or system3.default_config(),
                              settings(test_seed=seed), conversation_id=cid)


# Recorded 2026-09-26 from engine system3-engine/2 and the default tables
# (config 1f82ec0b14f3cdac). A change here is a change in behaviour and must be
# deliberate: bump the tables' version or the engine's.
GOLDEN = [["A", "initial", "OBLIGATED", "sadness.despair"],
          ["B", "response_a", "sadness.sadness", "qualify", "deepen"],
          ["A", "initiator_response", "sadness.disappointment", "misunderstand", "more_speakerbox"],
          ["B", "response_a2", "low_arousal.boredom", "make_fun", "tangent"],
          ["A", "frame", "surprise.bewilderment", "go_deeper"],
          ["B", "response_a", "social.pride", "disparage", "anecdotal_reframe"],
          ["A", "initiator_response", "sadness.melancholy", "disagree", "detail"],
          ["B", "response_a2", "interest.uncertainty", "llm_rebuttal", "de_escalation"],
          ["A", "frame", "sadness.despair", "concede_move_on"],
          ["B", "initial", "interest.skepticism", "final_callback"]]


class RngTests(unittest.TestCase):
    def test_same_seed_same_stream_and_labels_matter(self):
        a, b = system3.DrawStream("s"), system3.DrawStream("s")
        self.assertEqual([a.next("x")["u"] for _ in range(5)], [b.next("x")["u"] for _ in range(5)])
        self.assertNotEqual(system3.DrawStream("s").next("x")["u"], system3.DrawStream("s").next("y")["u"])
        self.assertNotEqual(system3.DrawStream("s").next("x")["u"], system3.DrawStream("t").next("x")["u"])

    def test_dice_is_one_to_hundred(self):
        stream = system3.DrawStream("dice")
        faces = {stream.next("d")["dice"] for _ in range(3000)}
        self.assertEqual(min(faces), 1)
        self.assertEqual(max(faces), 100)

    def test_pick_index_respects_weights_and_skips_zero(self):
        self.assertEqual(system3.pick_index([0, 1, 0], 0.99), 1)
        self.assertEqual(system3.pick_index([1, 1], 0.0), 0)
        self.assertEqual(system3.pick_index([1, 1], 0.999), 1)
        self.assertEqual(system3.pick_index([0, 0], 0.5), -1)
        counts = [0, 0]
        stream = system3.DrawStream("w")
        for _ in range(4000):
            counts[system3.pick_index([3, 1], stream.next("w")["u"])] += 1
        self.assertAlmostEqual(counts[0] / 4000, 0.75, delta=0.03)


class PlanTests(unittest.TestCase):
    def test_golden_seed_trajectory(self):
        conv = plan()
        got = [[t["speaker"], t["step"]] + [d.get("item") for d in t["decisions"]] for t in conv["turns"]]
        self.assertEqual(got, GOLDEN)
        # 2026-09-27 [s3-calls]: the default config gained road structures (the
        # call's legs) - the banter trajectory above is unchanged.
        # 2026-09-27 [s3-roads]: ...and one structure per road on the register
        # plus the SFX Guy's section; his node rolls on its own stream, so the
        # trajectory above is still unchanged (engine/3).
        self.assertEqual(system3.config_hash(system3.default_config()), "48e47262ef173867")

    def test_same_state_config_seed_reproduces_the_plan(self):
        a, b = plan(seed="r"), plan(seed="r")
        strip = lambda c: [(e["family"], e["selected"], (e.get("rng") or {}).get("u")) for e in c["decision_events"]]
        self.assertEqual(strip(a), strip(b))
        self.assertNotEqual(strip(a), strip(plan(seed="other")))

    def test_follows_the_banter_cycle_and_hands_off(self):
        """After the frame the initiator role passes to the other party -
        unless the frame drew a keep-the-initiator outcome (Enjoyment), in
        which case the frame itself opened the next exchange."""
        handed = kept = 0
        for seed in map(str, range(30)):
            conv = plan(seed=seed, turns=12)
            steps = [t["step"] for t in conv["turns"]]
            self.assertEqual(steps[:5], ["initial", "response_a", "initiator_response", "response_a2", "frame"])
            frame_fl = [d for d in conv["turns"][4]["decisions"] if d["family"] == "FL" and d.get("item")]
            keeps = bool(frame_fl) and frame_fl[0]["category"] == "enjoyment"
            nxt = conv["turns"][5]
            if keeps:
                kept += 1
                self.assertEqual((nxt["step"], nxt["speaker"]), ("response_a", "B"))
            else:
                handed += 1
                self.assertEqual((nxt["step"], nxt["speaker"]), ("initial", "B"),
                                 "the initiator role is handed to the other party")
        self.assertTrue(handed and kept, (handed, kept))

    def test_three_seats_everyone_participates_and_nobody_speaks_twice(self):
        for seed in ("a", "b", "c", "d"):
            conv = plan(seed=seed, seats=["A", "B", "D"], turns=16)
            seats = [t["speaker"] for t in conv["turns"]]
            self.assertEqual(set(seats), {"A", "B", "D"})
            self.assertTrue(all(x != y for x, y in zip(seats, seats[1:])), seats)

    def test_closing_turn_draws_a_closing_move(self):
        for seed in map(str, range(20)):
            conv = plan(seed=seed, turns=9)
            last = conv["turns"][-1]
            fl = [d for d in last["decisions"] if d["family"] == "FL" and d.get("item")]
            self.assertTrue(fl, "turn %d has no flow decision" % last["index"])
            self.assertIn(fl[0]["category"], ("land",))
            self.assertEqual(last["phase"], "SEGUE")

    def test_segue_is_never_drawn_before_the_last_turn(self):
        for seed in map(str, range(40)):
            conv = plan(seed=seed, turns=12)
            early = [d["item"] for t in conv["turns"][:-1] for d in t["decisions"]]
            self.assertNotIn("segue", early)

    def test_subject_obligation_is_recorded_not_drawn(self):
        conv = plan()
        first = conv["turns"][0]["decisions"][0]
        self.assertEqual((first["family"], first["item"]), ("CTS", "OBLIGATED"))
        ev = conv["decision_events"][int(first["event_id"].split(":")[-1])]
        self.assertIsNone(ev["rng"])
        self.assertEqual(conv["subject"]["topic"], "raccoon van")

    def test_material_that_is_not_there_is_never_eligible(self):
        for seed in map(str, range(30)):
            conv = plan(seed=seed, turns=14, availability={"speakbox": False})
            for t in conv["turns"]:
                for d in t["decisions"]:
                    self.assertNotIn(d.get("item"), ("speakerbox_rebuttal", "more_speakerbox", "more_news",
                                                     "quote_1_2", "quote_2_3", "drudge"))
                for sb in t["speakerbox"]:
                    self.assertEqual(sb["mode"], "NONE")

    def test_disabled_items_and_tables_are_never_selected(self):
        cfg = system3.default_config()
        for t in cfg["tables"]:
            if t["id"] == "RS2":
                t["enabled"] = False
        for seed in map(str, range(25)):
            conv = plan(seed=seed, config=cfg, turns=12)
            for e in conv["decision_events"]:
                for st in e["stages"]:
                    if st["stage"] == "table" and e["family"] == "RS":
                        self.assertNotIn("RS2", [c["id"] for c in st["candidates"]])
            used = [d.get("item") for t in conv["turns"] for d in t["decisions"]]
            self.assertNotIn("calling_slur", used, "the switched-off row")

    def test_cooldown_blocks_an_immediate_repeat(self):
        cfg = system3.default_config()
        cfg["tables"] = [t for t in cfg["tables"] if t["id"] != "RS2"]
        for t in cfg["tables"]:
            if t["id"] == "RS1":
                t["categories"] = [c for c in t["categories"] if c["id"] == "push_back"]
                t["categories"][0]["items"] = t["categories"][0]["items"][:2]
                t["categories"][0]["cooldown_turns"] = 1
        for seed in map(str, range(20)):
            conv = plan(seed=seed, config=cfg, turns=12, seats=["A", "B", "D"])
            # "not within one TURN": the RS of adjacent turns always differs;
            # a turn that draws no RS (a frame, an opener) lets it come back.
            per_turn = [next((d["item"] for d in t["decisions"] if d["family"] == "RS" and d.get("item")), None)
                        for t in conv["turns"]]
            for a, b in zip(per_turn, per_turn[1:]):
                if a and b:
                    self.assertNotEqual(a, b, per_turn)

    def test_time_gating_suppresses_new_tangents_near_the_end(self):
        conv = plan(turns=20, seed="tg")
        for t in conv["turns"]:
            if t["index"] >= 17:
                items = [d.get("item") for d in t["decisions"]]
                self.assertNotIn("tangent", items)
                self.assertNotIn("agree_to_disagree", items)

    def test_controls_move_documented_weights(self):
        lo = system3.normalise_settings({"mode": "active", "controls": {"disagreement": 0.0}})
        hi = system3.normalise_settings({"mode": "active", "controls": {"disagreement": 1.0}})

        def oppositional(st):
            n = 0
            for seed in map(str, range(40)):
                conv = system3.plan_scene(inputs(turns=10), system3.default_config(),
                                          dict(st, test_seed=seed))
                n += sum(1 for t in conv["turns"] for d in t["decisions"]
                         if d["family"] in ("RS", "IRS") and d.get("lean") == -1)
            return n
        self.assertGreater(oppositional(hi), oppositional(lo) * 1.25)

    def test_every_event_is_well_formed_and_correlatable(self):
        for seed in map(str, range(15)):
            conv = plan(seed=seed, turns=14, seats=["A", "B", "D"])
            turn_ids = {t["turn_id"] for t in conv["turns"]}
            ids = [e["event_id"] for e in conv["decision_events"]]
            self.assertEqual(len(ids), len(set(ids)))
            for e in conv["decision_events"]:
                self.assertEqual(e["schema"], system3.EVENT_SCHEMA)
                self.assertEqual(e["conversation_id"], "golden")
                self.assertTrue(e["turn_id"] == "" or e["turn_id"] in turn_ids)
                for st in e["stages"]:
                    ws = [c["weight"] for c in st.get("candidates") or []]
                    self.assertTrue(all(w > 0 for w in ws), "an excluded candidate stayed in the draw")
                    if ws and st.get("draw") is not None:
                        self.assertAlmostEqual(sum(c["p"] for c in st["candidates"]), 1.0, places=2)
                        self.assertIn(st["selected"], [c["id"] for c in st["candidates"]])
            for t in conv["turns"]:
                self.assertTrue(t["decision_bundle_id"].startswith(t["turn_id"]))
                for d in t["decisions"]:
                    self.assertIn(d["event_id"], ids)

    def test_serialisation_round_trip(self):
        conv = plan()
        again = json.loads(json.dumps(conv))
        self.assertEqual(again["turns"], json.loads(json.dumps(conv["turns"])))
        self.assertTrue(system3.replay(again, system3.default_config())["ok"])


class SheetTests(unittest.TestCase):
    def test_sheet_uses_the_1386_row_grammar(self):
        import re
        conv = plan()
        sheet = system3.render_sheet(conv)
        rows = re.findall(r"(?m)^\s*(\d+)\s+([ABCD])\s+[-–—]\s*(.+?)\s*$", sheet)
        self.assertEqual([int(r[0]) for r in rows], list(range(1, 11)))
        self.assertEqual([r[1] for r in rows], [t["speaker"] for t in conv["turns"]])
        self.assertIn("never name them", sheet)

    def test_legacy_rolls_carry_the_system3_reference(self):
        conv = plan()
        for roll in system3.legacy_rolls(conv):
            self.assertEqual(roll["s3"]["conversation_id"], "golden")
            self.assertIn(roll["axis"], ("stance", "rebuttal"))

    def test_protocol_annotation_keeps_every_protocol_line(self):
        sheet = ("\n\nTHE RUNNING ORDER OF THIS CALL.\n 1  A  - ANSWER THE RINGING LINE.\n"
                 " 2  C  - BETTY INTRODUCES THEMSELF.\n 3  A  - keeps it going; every turn answers.\n"
                 " 4  C  - BETTY LANDS IT.\n 5  A  - SIGN OFF. thanks.\nEvery one of those is checked.")
        import re
        rows = [(int(n), s, w) for n, s, w in re.findall(r"(?m)^\s*(\d+)\s+([ABCDE])\s+[-]\s*(.+?)\s*$", sheet)]
        conv = system3.new_conversation(inputs(road="caller", seats=["A", "B", "C"], turns=5,
                                               availability={}), system3.default_config(), settings())
        system3.plan_protocol(conv, system3.default_config(), rows)
        out = system3.annotate_protocol(conv, sheet)
        for line in sheet.splitlines():
            self.assertIn(line, out)
        self.assertEqual(out.count("[Say it in"), 5)
        rs_turns = [t["index"] for t in conv["turns"] if any(d["family"] == "RS" for d in t["decisions"])]
        self.assertEqual(rs_turns, [2], "only the open protocol turn carries a response act")


class ValidationTests(unittest.TestCase):
    def test_alignment_survives_a_prepended_door_turn(self):
        conv = plan(turns=6)
        written = [("B", "a door passage, word for word.")] + [
            (t["speaker"], "no, that is wrong? " + t["turn_id"]) for t in conv["turns"]]
        mapping = system3.align(conv, written)
        self.assertEqual(mapping[0], 1)
        self.assertEqual(len(mapping), 6)

    def test_validation_is_deterministic_and_lexical(self):
        conv = plan(turns=6)
        things = ["the van", "the raccoon", "the mug", "the key", "the dashboard", "the station"]
        written = [(t["speaker"], "No, that's wrong about %s and you know it? Thanks, back to the music." % things[i])
                   for i, t in enumerate(conv["turns"])]
        val = system3.validate(conv, written)
        self.assertEqual(val["method"], "deterministic/lexical")
        self.assertEqual(val["seat_order"], 1.0)
        self.assertFalse(val["repair_wanted"])
        self.assertFalse(val["echo"]["loop"])
        self.assertEqual(system3.validate(conv, written)["score"], val["score"])

    def test_an_echo_loop_is_caught_and_asks_for_repair(self):
        # 2026-09-27, as it aired six times: a banked round that parroted one
        # passage - "Shave it." / "Shave it? What do you mean by that?" -
        # passed because the old repair rule only counted turns and seats.
        conv = plan(turns=12)
        lines = ["You can't keep this up don't you know what's gonna happen every time you shave it"]
        for i in range(11):
            lines.append("Shave it." if i % 2 == 0 else "Shave it? What do you mean by that?")
        written = [(t["speaker"], lines[i]) for i, t in enumerate(conv["turns"])]
        val = system3.validate(conv, written)
        self.assertTrue(val["echo"]["loop"])
        self.assertGreaterEqual(len(val["echo"]["turns"]), 9)
        self.assertEqual(val["verdict"], "non_compliant")
        self.assertTrue(val["repair_wanted"])

    def test_a_turn_that_quotes_a_word_back_is_not_an_echo(self):
        written = [("A", "You can't keep this up every time you shave it."),
                   ("B", "Shave it? That is the worst advice anybody has given on this station all week, and I include the raccoon."),
                   ("A", "The raccoon at least had a plan, which is more than your haircut ever had going for it."),
                   ("B", "My haircut has a plan: it is called patience, and it has outlived three of your theories.")]
        self.assertEqual(system3._echoes(written), [])

    def test_the_operators_exchange_opens_the_round_word_for_word(self):
        # "1. This is my studio / 2. That's what you think" from the topic desk
        conv = plan(turns=6, subject={"topic": "This is my studio", "keywords": ["studio"],
                                      "exchange": {"opener": "This is my studio", "reply": "That's what you think"}})
        rows = [ln for ln in system3.render_sheet(conv).splitlines() if re.match(r"^\s*\d+\s+[A-Z]\s+-", ln)]
        self.assertIn('opens with these exact words, as written: "This is my studio"', rows[0])
        self.assertIn('with these exact words, as written: "That\'s what you think"', rows[1])
        self.assertNotIn("Picks up a word", rows[1])
        self.assertIn("answers what", rows[2])

    # [rng-topics] "Topic should be accessed via the RNG system on the
    # roulette rolodex allowing for it come up naturally in conversation"
    BOARD = [{"id": "t1", "text": "My grandmother is being abused in the old folks home", "used": 0},
             {"id": "t2", "text": "Tomorrow is Valentine's Day, so I propose an idea", "used": 5}]

    def topic_plan(self, n, board=None, rate=1.0, turns=8, prefix="topic"):
        return system3.plan_scene(inputs(turns=turns, topic_bank=board or self.BOARD), system3.default_config(),
                                  settings(test_seed="%s-%d" % (prefix, n), controls={"topics": rate}),
                                  conversation_id="%s%d" % (prefix, n))

    def test_a_topic_off_the_board_comes_up_through_the_roulette(self):
        raised = None
        for n in range(60):
            conv = self.topic_plan(n)
            ev = [e for e in conv["decision_events"] if e["family"] == "TOPIC"]
            self.assertEqual(len(ev), 1, "one TOPIC roll per round")
            self.assertEqual(ev[0]["stages"][0]["stage"], "dice")
            if ev[0]["selected"]["id"] != "NONE":
                raised = (conv, ev[0])
                break
        self.assertIsNotNone(raised, "at topics 1.0 (80%) some seed raises a topic")
        conv, ev = raised
        self.assertEqual([s["stage"] for s in ev["stages"]], ["dice", "item", "turn"])
        turn = next(t for t in conv["turns"] if t.get("bank_topic"))
        self.assertEqual(ev["turn_id"], turn["turn_id"])
        self.assertTrue(0 < turn["index"] < len(conv["turns"]) - 1, "never the opener or the close")
        self.assertIn(ev["event_id"], [d["event_id"] for d in turn["decisions"]])
        rows = [ln for ln in system3.render_sheet(conv).splitlines() if re.match(r"^\s*\d+\s+[A-Z]\s+-", ln)]
        row = rows[turn["index"]]
        self.assertIn("topics board", row)
        self.assertIn(turn["bank_topic"]["text"], row)
        self.assertIn("answers what", row, "it still answers the line before it")
        again = system3.plan_scene(inputs(turns=8, topic_bank=self.BOARD), system3.default_config(),
                                   settings(test_seed=conv["seed"], controls={"topics": 1.0}), conversation_id="again")
        ev2 = next(e for e in again["decision_events"] if e["family"] == "TOPIC")
        self.assertEqual((ev2["selected"], ev2["meta"]["turn_index"]), (ev["selected"], ev["meta"]["turn_index"]))

    def test_no_board_draws_nothing_and_a_zero_dial_never_raises(self):
        self.assertFalse([e for e in plan(turns=8)["decision_events"] if e["family"] == "TOPIC"])
        for n in range(20):
            conv = self.topic_plan(n, rate=0.0, prefix="zero")
            ev = next(e for e in conv["decision_events"] if e["family"] == "TOPIC")
            self.assertEqual(ev["selected"]["id"], "NONE")
            self.assertFalse([t for t in conv["turns"] if t.get("bank_topic")])

    def test_a_numbered_board_entry_is_said_and_answered_word_for_word(self):
        board = [{"id": "x1", "text": "When was the station even established?", "reply": "How should I know?", "used": 0}]
        found = None
        for n in range(120):
            conv = self.topic_plan(n, board=board, prefix="ex")
            t = next((t for t in conv["turns"] if t.get("bank_topic")), None)
            if t and not conv["turns"][t["index"] + 1].get("topic_change"):
                found = (conv, t)
                break
        self.assertIsNotNone(found)
        conv, t = found
        rows = [ln for ln in system3.render_sheet(conv).splitlines() if re.match(r"^\s*\d+\s+[A-Z]\s+-", ln)]
        self.assertIn('says these exact words, as written: "When was the station even established?"', rows[t["index"]])
        self.assertIn('with these exact words, as written: "How should I know?"', rows[t["index"] + 1])

    def test_the_operators_own_exchange_is_not_topped_with_a_board_topic(self):
        conv = system3.plan_scene(inputs(turns=6, topic_bank=self.BOARD,
                                         subject={"topic": "This is my studio",
                                                  "exchange": {"opener": "This is my studio", "reply": "That's what you think"}}),
                                  system3.default_config(), settings(controls={"topics": 1.0}), conversation_id="own")
        ev = next(e for e in conv["decision_events"] if e["family"] == "TOPIC")
        self.assertIs(ev["meta"].get("applies"), False)
        self.assertFalse([t for t in conv["turns"] if t.get("bank_topic")])

    def test_a_call_raises_a_board_topic_only_on_a_leg_left_open(self):
        rows = [(1, "A", "rings the line in"), (2, "C", "says who they are"), (3, "B", "answers the caller and keeps it going"),
                (4, "C", "states the problem"), (5, "A", "reacts to it"), (6, "C", "lands it"), (7, "B", "thanks them")]
        for n in range(80):
            conv = system3.new_conversation(inputs(road="caller", seats=["A", "B", "C"], turns=7, topic_bank=self.BOARD),
                                            system3.default_config(), settings(test_seed="call-%d" % n, controls={"topics": 1.0}),
                                            conversation_id="call%d" % n)
            system3.plan_protocol(conv, system3.default_config(), rows)
            t = next((t for t in conv["turns"] if t.get("bank_topic")), None)
            if t:
                self.assertIn(t["index"], (2, 4), "only a leg the protocol leaves open")
                self.assertFalse(t["bank_topic"]["reply"], "a call's legs keep their own words")
                sheet = "\n".join("%d  %s  - %s" % r for r in rows)
                self.assertIn("topics board", system3.annotate_protocol(conv, sheet))
                return
        self.fail("no seed raised a topic on a call at topics 1.0")

    # [s3-calls] "calls should also go through system 3 and be constructed
    # through RNG and the rolodex system"
    def call_plan(self, seed="call-1", turns=12, config=None, **call):
        base = {"name": "Monk Brennan", "first": "Monk", "other": "Skip",
                "speakerbox": "The cat kidnapped somebody from the sewer."}
        base.update(call)
        cfg = config or system3.default_config()
        conv = system3.new_conversation(inputs(road="caller", seats=["A", "B", "C"], turns=turns, call=base),
                                        cfg, settings(test_seed=seed), conversation_id="c-" + seed)
        return system3.plan_call(conv, cfg)

    def test_a_call_is_planned_from_system3s_own_legs(self):
        conv = self.call_plan()
        legs = [t["leg"] for t in conv["turns"]]
        self.assertEqual(legs[:7], ["answer", "introduce", "greet", "detail_1", "ask_1", "detail_2", "ask_2"])
        self.assertEqual(legs[-2:], ["lands", "sign_off"])
        self.assertEqual(len(conv["turns"]), 12)
        self.assertEqual(conv["turns"][-2]["speaker"], "C", "the caller lands it second to last")
        self.assertEqual(conv["turns"][-3]["speaker"], "A", "a host speaks just before the caller lands it")
        for t in conv["turns"]:
            self.assertTrue(any(d["family"] == "ES" for d in t["decisions"]), "every leg rolls its feeling")
            if t["leg"] == "keeps_going":
                self.assertTrue(any(d["family"] == "RS" for d in t["decisions"]), "an open leg rolls its act")
        sheet = system3.render_call_sheet(conv)
        for words in ("THE RUNNING ORDER OF THIS CALL", "MONK INTRODUCES THEMSELF", "They are the call.",
                      "[Say it in", "SOMEWHERE IN THE MIDDLE"):
            self.assertIn(words, sheet)
        rows = [ln for ln in sheet.splitlines() if re.match(r"^\s*\d+\s+[A-Z]\s+-", ln)]
        self.assertEqual(len(rows), 12)
        self.assertTrue(rows[-1].split("-", 1)[1].strip().startswith("SIGN OFF"))

    def test_a_call_keeps_its_protocol_floor_and_replays(self):
        self.assertEqual(len(self.call_plan(turns=3)["turns"]), 9, "the protocol's floor is nine turns")
        a, b = self.call_plan(seed="same"), self.call_plan(seed="same")
        self.assertEqual([(t["speaker"], (t["performance"] or {}).get("emotion")) for t in a["turns"]],
                         [(t["speaker"], (t["performance"] or {}).get("emotion")) for t in b["turns"]])

    def test_a_call_structure_can_be_altered_and_is_checked(self):
        cfg = system3.default_config()
        cfg["structures"]["caller"]["legs"].insert(7, {"id": "tease", "label": "A tease", "place": "open", "seat": "B",
            "act": "teases {first} about it.", "draws": [{"family": "ES"}, {"family": "RS"}]})
        self.assertEqual(system3_tables.validate_structure("caller", cfg["structures"]["caller"]), [])
        conv = self.call_plan(seed="alt", config=cfg)
        self.assertEqual(conv["turns"][7]["leg"], "tease")
        self.assertIn("teases Monk about it.", system3.render_call_sheet(conv))
        bad = system3_tables.validate_structure("caller", {"legs": [{"id": "x", "place": "nowhere", "seat": "Z", "draws": []}]})
        self.assertTrue(bad)

    def test_every_row_answers_the_line_before_it(self):
        conv = plan(turns=6)
        sheet = system3.render_sheet(conv)
        rows = [ln for ln in sheet.splitlines() if re.match(r"^\s*\d+\s+[A-Z]\s+-", ln)]
        for i, ln in enumerate(rows):
            t = conv["turns"][i]
            if i and not t.get("topic_change"):
                prev = conv["turns"][i - 1]
                self.assertIn("answers what %s just said" % (prev.get("name") or prev["speaker"]), ln)
        self.assertIn("no turn repeats or echoes a line already said", sheet)
        self.assertIn("how that speaker feels about the line they are answering", sheet)
        self.assertNotIn("Quote back the word or claim you are answering", sheet)

    def test_a_writer_that_ignored_the_order_asks_for_repair(self):
        conv = plan(turns=8)
        val = system3.validate(conv, [("A", "one long speech.")])
        self.assertTrue(val["repair_wanted"])
        self.assertEqual(val["verdict"], "non_compliant")

    def test_bind_never_mutates_the_script(self):
        conv = plan(turns=6)
        written = [(t["speaker"], "Words %d." % i) for i, t in enumerate(conv["turns"])]
        frozen = copy.deepcopy(written)
        system3.bind(conv, written)
        self.assertEqual(written, frozen)
        self.assertEqual(conv["turns"][2]["text"], "Words 2.")
        self.assertEqual(conv["turns"][2]["script_index"], 2)

    def test_prohibited_behaviour_is_flagged(self):
        conv = plan(turns=3)
        val = system3.validate(conv, [("A", "**bold** see https://x.y"), ("B", "fine."), ("A", "ok.")])
        flagged = [c["what"] for r in val["turns"] for c in r["checks"] if c["result"] == "violated"]
        self.assertIn("prohibited:markdown", flagged)
        self.assertIn("prohibited:url", flagged)

    def test_shadow_comparison_never_changes_the_plan(self):
        conv = plan(turns=6)
        before = json.dumps(conv["turns"])
        cmp = system3.compare_shadow(conv, [("A", "hi."), ("B", "hello.")])
        self.assertEqual(json.dumps(conv["turns"]), before)
        self.assertEqual(cmp["actual_turns"], 2)


class ModeBTests(unittest.TestCase):
    def test_observe_then_replan_is_recorded_and_replayable(self):
        cfg = system3.default_config()
        conv = plan(turns=10, config=cfg)
        n_before = len(conv["decision_events"])
        for i in range(4):
            system3.observe(conv, i, "No! That is ridiculous!! You are wrong.")
        system3.replan(conv, cfg, 4, until=10)
        self.assertEqual(len(conv["turns"]), 10)
        self.assertEqual(conv["identity"]["revision"], 2)
        self.assertGreater(len(conv["decision_events"]), n_before)
        self.assertGreater(conv["observed_delta"].get("tension", 0), 0)
        stored = json.loads(json.dumps(conv))
        self.assertTrue(system3.replay(stored, cfg)["ok"])

    def test_replan_keeps_the_seat_rhythm(self):
        cfg = system3.default_config()
        conv = plan(turns=10, config=cfg)
        system3.observe(conv, 0, "hello there.")
        system3.replan(conv, cfg, 1, until=10)
        seats = [t["speaker"] for t in conv["turns"]]
        self.assertTrue(all(x != y for x, y in zip(seats, seats[1:])), seats)


class SpeakerboxTests(unittest.TestCase):
    def test_full_swath_is_one_speakers_opening_monologue(self):
        """Engine v2: the full-swath dial never deals a passage across the
        seats. It opens turn 1 with a monologue its initiator reads, and the
        next turn answers it; a round never gets two openers."""
        seen = 0
        for seed in map(str, range(40)):
            conv = plan(seed=seed, speakerbox_rates={"full": 1.0, "prepend": 1.0, "append": 0.0})
            first = conv["turns"][0]["speakerbox"]
            modes = [x["mode"] for x in first]
            self.assertIn("FULL_SWATH", modes)
            self.assertNotIn("prepend", [x["mark"] for x in first])
            req = [r for r in conv["material_requests"] if r["mode"] == "FULL_SWATH"]
            self.assertEqual(len(req), 1)
            self.assertEqual(req[0]["turn_index"], 0)
            self.assertEqual(req[0]["chars"], 700)
            seen += 1
        self.assertEqual(seen, 40)

    def test_a_seeded_round_gets_no_second_opener(self):
        conv = plan(speakerbox_rates={"full": 1.0, "prepend": 0.0, "append": 0.0},
                    subject={"topic": "t", "seeded": True})
        self.assertNotIn("FULL_SWATH", [x["mode"] for x in conv["turns"][0]["speakerbox"]])

    def test_the_monologue_is_in_the_running_order(self):
        conv = plan(speakerbox_rates={"full": 1.0, "prepend": 0.0, "append": 0.0})
        sb = next(x for x in conv["turns"][0]["speakerbox"] if x["mode"] == "FULL_SWATH")
        sb["material"] = {"file": "43d.md", "text": "I want to eat. Someone got eaten."}
        sheet = system3.render_sheet(conv)
        self.assertIn("speaker-box monologue", sheet)
        self.assertIn("Someone got eaten.", sheet)


class ReplayTests(unittest.TestCase):
    def test_replay_names_a_different_engine(self):
        conv = json.loads(json.dumps(plan()))
        conv["engine"] = "system3-engine/1"
        got = system3.replay(conv, system3.default_config())
        self.assertFalse(got["ok"])
        self.assertIn("system3-engine/1", got["why"])

    def test_replay_refuses_a_different_config(self):
        conv = json.loads(json.dumps(plan()))
        cfg = system3.default_config()
        cfg["tables"][1]["weight"] = 2.0
        self.assertFalse(system3.replay(conv, cfg)["ok"])

    def test_replay_reports_divergence(self):
        conv = json.loads(json.dumps(plan()))
        at = next(i for i, e in enumerate(conv["decision_events"]) if e["rng"] and i > 3)
        conv["decision_events"][at]["rng"]["u"] = 0.123456
        got = system3.replay(conv, system3.default_config())
        self.assertFalse(got["ok"])
        self.assertEqual(got["first_difference"], at)


class ConfigTests(unittest.TestCase):
    def test_a_supplemental_table_is_drawn_from(self):
        cfg = system3.default_config()
        es2 = copy.deepcopy(next(t for t in cfg["tables"] if t["id"] == "ES1"))
        es2.update(id="ES2", label="Emotional Set 2", weight=50.0)
        es2["categories"] = [{"id": "giddy", "label": "GIDDY", "weight": 1, "valence": 0.9, "arousal": 0.9,
                              "dims": {"amusement": 1.0}, "items": [{"id": "giddy.hysterical", "label": "hysterical"}]}]
        cfg["tables"].append(system3.validate_table(es2))
        conv = plan(config=cfg, turns=8)
        used = [d["table"] for t in conv["turns"] for d in t["decisions"] if d["family"] == "ES"]
        self.assertIn("ES2", used)

    def test_validate_table_refuses_nonsense(self):
        with self.assertRaises(ValueError):
            system3.validate_table({"id": "1bad", "family": "ES", "categories": []})
        with self.assertRaises(ValueError):
            system3.validate_table({"id": "ES9", "family": "XX", "categories": [{"id": "a", "items": [{"id": "b"}]}]})
        with self.assertRaises(ValueError):
            system3.validate_table({"id": "ES9", "family": "ES", "categories": [{"id": "a", "items": [
                {"id": "b"}, {"id": "b"}]}]})

    def test_settings_are_normalised(self):
        st = system3.normalise_settings({"mode": "bogus", "controls": {"sfx_aggression": 7}, "roads": ["x", "banter"]})
        self.assertEqual(st["mode"], "shadow")
        self.assertEqual(st["controls"]["sfx_aggression"], 1.0)
        self.assertEqual(st["roads"], ["banter"])

    def test_road_modes(self):
        self.assertEqual(system3.road_mode({"mode": "off"}, "banter"), "off")
        self.assertEqual(system3.road_mode({"mode": "shadow"}, "banter"), "shadow")
        self.assertEqual(system3.road_mode({"mode": "active_selected_roads", "roads": ["banter"]}, "banter"), "active")
        self.assertEqual(system3.road_mode({"mode": "active_selected_roads", "roads": ["banter"]}, "caller"), "shadow")
        self.assertEqual(system3.road_mode({"mode": "active"}, "caller"), "active")

    def test_pdf_lists_are_all_present(self):
        cfg = system3_tables.default_tables()
        labels = {i["label"].lower() for t in cfg for c in t["categories"] for i in c["items"]}
        for want in ("shock", "moral disgust", "defensiveness", "acceptance", "you sure about that?",
                     "doubling down on original point", "request to fight outside",
                     "drudge report (preferred)", "lost pets"):
            self.assertIn(want, labels)


class PerformanceTests(unittest.TestCase):
    def test_emotion_reaches_the_six_dimensions(self):
        es = next(t for t in system3.default_config()["tables"] if t["id"] == "ES1")
        anger = next(c for c in es["categories"] if c["id"] == "anger")
        spec = system3._spec(es, anger, anger["items"][6])        # fury
        hard = system3.performance_intent(spec, 1.0, {"tension": 0.8})
        soft = system3.performance_intent(spec, 0.1, {"tension": 0.8})
        self.assertEqual(set(hard["dims"]), set(system3.EMOTION_DIMS))
        self.assertGreater(hard["dims"]["irritation"], soft["dims"]["irritation"])
        self.assertEqual(hard["pause_style"], "clipped")


class SfxTests(unittest.TestCase):
    def test_first_exchange_carries_a_clip_and_aggression_scales(self):
        conv = plan(turns=10)
        self.assertTrue(conv["turns"][2]["sfx"]["play"])
        self.assertEqual(conv["turns"][2]["sfx"]["reason"], "first_exchange")

        def plays(level):
            st = system3.normalise_settings({"mode": "active", "controls": {"sfx_aggression": level}})
            n = 0
            for seed in map(str, range(30)):
                c = system3.plan_scene(inputs(turns=10), system3.default_config(), dict(st, test_seed=seed))
                n += sum(1 for t in c["turns"] if t["sfx"]["play"])
            return n
        self.assertGreater(plays(1.0), plays(0.0) * 2)

    def test_no_path_is_ever_invented(self):
        conv = plan()
        for t in conv["turns"]:
            self.assertNotIn("path", t["sfx"])
            self.assertNotIn("clip", t["sfx"])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = System3Store(Path(self.tmp.name) / "system3.sqlite3")
        self.addCleanup(self.store.close)

    def test_round_trip_events_lines_and_idempotent_save(self):
        conv = plan()
        self.assertEqual(self.store.save_conversation(conv), len(conv["decision_events"]))
        self.assertEqual(self.store.save_conversation(conv), 0, "a second save adds no duplicate events")
        self.store.add_observation("golden", "SFX", {"stage": "air", "turn_id": "golden:t02"})
        self.store.add_lines([{"line_id": "L1", "conversation_id": "golden", "turn_id": "golden:t00",
                               "block": 7, "ord": 0, "text": "hello"}])
        got = self.store.conversation("golden")
        self.assertEqual(len(got["decision_events"]), len(conv["decision_events"]))
        self.assertEqual(got["observations_air"][0]["family"], "SFX")
        self.assertEqual(got["lines"][0]["block"], 7)
        self.assertEqual(self.store.line("L1")["turn_id"], "golden:t00")
        feed = self.store.events_after(0, 5)
        self.assertEqual(len(feed["events"]), 5)
        more = self.store.events_after(feed["cursor"], 1000)
        self.assertEqual(len(feed["events"]) + len(more["events"]), len(conv["decision_events"]) + 1)
        self.assertTrue(system3.replay(got, system3.default_config())["ok"])

    def test_settings_and_config_versions(self):
        self.store.save_settings({"mode": "active_selected_roads", "roads": ["banter"]})
        self.assertEqual(self.store.settings()["mode"], "active_selected_roads")
        cfg = self.store.config()
        h1 = system3.config_hash(cfg)
        cfg["sfx"]["p_high"] = 0.9
        h2 = self.store.save_config(cfg, "louder")
        self.assertNotEqual(h1, h2)
        self.assertEqual(self.store.config_by_hash(h1)["sfx"]["p_high"], 0.7, "old versions stay interpretable")
        self.assertEqual(self.store.config()["sfx"]["p_high"], 0.9)

    def test_retention(self):
        for i in range(5):
            c = plan(cid="c%d" % i)
            c["created"] = 1000.0 + i
            self.store.save_conversation(c)
        self.assertEqual(self.store.retention(max_age_days=1, max_conversations=100), 5)
        self.assertEqual(self.store.counts()["events"], 0)


if __name__ == "__main__":
    unittest.main()

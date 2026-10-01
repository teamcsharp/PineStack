"""[s3-callarc] The call as radio: its arc, its detour and the station's own results.

The operator, 2026-10-01: "whenever they call the calls need to have a resolution or an
escalation or an argument or a confrontation and then lead to a result. Like they win a
prize, like they get one of the paintings and are enthusiastic about it ... trigger the
manager to say something, or say something about the manager or his message or have
something to say about the news ... 80% they should change topic and subsequent rolls
should have a graduating chance of rolling a change to say something to drive the
customer back on topic and if the roll fails the customer goes even further into their
tangent." His answers: one arc per call, rolled; the manager cuts into the call himself.
"""
import copy
import unittest

import system3
import system3_tables

from test_system3_callend import no_events, pinned, call_inputs, settings, PAINTING

MEMO = "Effective immediately the break room fridge is a listening post. Label your yoghurt."
UNSOLD = {"name": "harbour_at_dawn_00275_.png", "title": "harbour at dawn", "price": 120}


def cfg_with(first=None, back_start=None, back_step=None, most=None, arc=True):
    cfg = copy.deepcopy(system3.default_config())
    for t in cfg["tables"]:
        if t["family"] == "EVENT":
            for c in t["categories"]:
                c["odds"] = 0.0
        if t["id"] == "CALLSHIFT1":
            for k, v in (("first_odds", first), ("back_start", back_start), ("back_step", back_step), ("most", most)):
                if v is not None:
                    t[k] = v
        if t["family"] == "CALLARC" and not arc:
            t["enabled"] = False
    return cfg


def plan(seed, cfg, **call):
    inp = call_inputs()
    inp["call"].update(call)
    inp["call"].setdefault("topic", "a raccoon in the van")
    conv = system3.new_conversation(inp, cfg, settings(seed), conversation_id="arc-" + seed)
    return system3.plan_call(conv, cfg, conv["inputs"])


def legs(conv):
    return [t["leg"] for t in conv["turns"]]


class Arc(unittest.TestCase):
    def test_every_call_rolls_one_arc_and_plays_its_beats(self):
        seen = set()
        for n in range(24):
            conv = plan("a%d" % n, cfg_with(first=0.0))
            arc = conv["callarc"]
            self.assertIn(arc["arc"], ("resolution", "escalation", "argument", "confrontation"))
            seen.add(arc["arc"])
            ls = legs(conv)
            self.assertEqual(ls[:7], ["answer", "introduce", "greet", "detail_1", "ask_1", "detail_2", "ask_2"])
            for b in arc["beats"]:
                self.assertIn(b, ls)
            self.assertLess(ls.index(arc["beats"][-1]), ls.index("resolution"))
            ev = [e for e in conv["decision_events"] if e["family"] == "CALLARC"]
            self.assertEqual(len(ev), 1)
            self.assertEqual(ev[0]["turn_index"], ls.index(arc["beats"][0]))
        self.assertGreaterEqual(len(seen), 3, "the arc is a roll, not a constant")

    def test_no_seat_speaks_twice_in_a_row(self):
        for n in range(30):
            conv = plan("s%d" % n, cfg_with(), memo=MEMO, news="Town hall roof found on a different town hall",
                        unsold=UNSOLD)
            seats = [t["speaker"] for t in conv["turns"]]
            for a, b in zip(seats, seats[1:]):
                self.assertNotEqual(a, b, (n, list(zip(legs(conv), seats))))

    def test_the_same_seed_is_the_same_call(self):
        a = plan("same", cfg_with(), memo=MEMO)
        b = plan("same", cfg_with(), memo=MEMO)
        self.assertEqual(legs(a), legs(b))
        self.assertEqual([t.get("protocol") for t in a["turns"]], [t.get("protocol") for t in b["turns"]])

    def test_switched_off_the_call_is_the_old_call(self):
        old = no_events(system3.default_config())
        conv = plan("off", old)
        self.assertNotIn("topic_shift", legs(conv))
        self.assertFalse(conv["callarc"].get("rolled"))


class Detour(unittest.TestCase):
    def test_a_detour_at_its_odds_and_where_its_subject_comes_from(self):
        conv = plan("d1", cfg_with(first=1.0, back_start=1.0), memo=MEMO)
        d = conv["callshift"]
        self.assertTrue(d["detour"])
        ls = legs(conv)
        self.assertEqual(ls[7], "topic_shift")
        self.assertEqual(ls[8], "steer_1")
        self.assertEqual(ls[9], "back_on_topic")
        self.assertTrue(d["came_back"])
        shift = conv["turns"][7]["protocol"]
        self.assertIn("CHANGES THE SUBJECT", shift)
        if d["source"] == "memo":
            self.assertIn("listening post", shift)
        none = plan("d2", cfg_with(first=0.0))
        self.assertFalse(none["callshift"]["detour"])
        self.assertNotIn("topic_shift", legs(none))
        stay = [e for e in none["decision_events"] if e["family"] == "CALLSHIFT"]
        self.assertEqual(stay[0]["selected"]["id"], "no")
        self.assertEqual(stay[0]["selected"]["odds"], 0.0)

    def test_the_steer_back_chance_graduates_and_a_miss_goes_further(self):
        conv = plan("d3", cfg_with(first=1.0, back_start=0.0, back_step=0.0, most=3))
        d = conv["callshift"]
        self.assertFalse(d["came_back"])
        self.assertEqual([r["back"] for r in d["rolls"]], [False, False, False])
        ls = legs(conv)
        self.assertEqual([x for x in ls if x.startswith("further_")], ["further_1", "further_2", "further_3"])
        self.assertIn("detour_lands", ls)
        self.assertIn("GIVES UP STEERING", conv["turns"][ls.index("detour_lands")]["protocol"])
        rising = plan("d4", cfg_with(first=1.0, back_start=0.35, back_step=0.2, most=3))
        backs = [e for e in rising["decision_events"]
                 if e["family"] == "CALLSHIFT" and (e.get("meta") or {}).get("kind", "").startswith("back_")]
        odds = [e["meta"]["odds"] for e in backs]
        self.assertEqual(odds, sorted(odds))
        self.assertAlmostEqual(odds[0], 0.35)
        for e in backs:
            self.assertEqual(len(e["stages"][0]["candidates"]), 2)
            self.assertIsNotNone(e["stages"][0]["draw"])

    def test_eighty_percent_by_default(self):
        hits = sum(bool(plan("p%d" % n, cfg_with())["callshift"]["detour"]) for n in range(60))
        self.assertTrue(36 <= hits <= 58, hits)


class Results(unittest.TestCase):
    def test_the_manager_cuts_into_the_call_on_his_own_seat(self):
        cfg = pinned(cfg_with(first=0.0), "RESOLVE", fixed="scolds")
        conv = plan("m1", cfg, memo=MEMO, manager="Mr Halvorsen")
        ls = legs(conv)
        at = ls.index("manager_cuts_in")
        self.assertEqual(ls[at - 1], "resolution")
        self.assertEqual(ls[at + 1], "reaction")
        turn = conv["turns"][at]
        self.assertEqual(turn["speaker"], "E")
        self.assertIn("MR HALVORSEN", turn["protocol"])
        self.assertIn("listening post", turn["protocol"])
        mark = system3.callend_mark(conv)
        self.assertTrue(mark["resolve"]["manager_act"])
        self.assertEqual(mark["resolve"]["seat_in"], "E")

    def test_no_memo_no_manager(self):
        cfg = cfg_with(first=0.0)
        for n in range(20):
            conv = plan("m%d" % n, cfg)
            self.assertNotIn("manager_cuts_in", legs(conv))
            res = (conv.get("callend") or {}).get("resolve") or {}
            self.assertNotIn(res.get("category"), ("manager", "memo_remark", "news_remark", "unsold"))

    def test_a_painting_off_the_unsold_pile_is_the_one_awarded(self):
        cfg = pinned(cfg_with(first=0.0), "RESOLVE", fixed="wins_painting")
        conv = plan("u1", cfg, unsold=UNSOLD)
        res = conv["callend"]["resolve"]
        self.assertEqual(res["painting"]["image"], UNSOLD["name"])
        self.assertEqual(res["effect"], "awarded")
        react = conv["turns"][legs(conv).index("reaction")]["protocol"]
        self.assertIn("harbour at dawn", react)

    def test_the_tables_validate_and_are_defaults(self):
        ids = [t["id"] for t in system3.default_config()["tables"]]
        for tid in ("CALLARC1", "CALLSHIFT1", "RESOLVE2"):
            self.assertIn(tid, ids)
        for t in (system3_tables.CALLARC1, system3_tables.CALLSHIFT1, system3_tables.RESOLVE2):
            system3.validate_table(t)


if __name__ == "__main__":
    unittest.main()


class TopicGrade(unittest.TestCase):
    def test_the_detour_is_not_graded_against_the_subject(self):
        import app
        conv = plan("g1", cfg_with(first=1.0, back_start=0.0, back_step=0.0, most=2), memo=MEMO)
        mark = system3.callend_mark(conv)
        self.assertTrue(mark["detour_turns"])
        turns = [(t["speaker"], "turn %d" % t["index"]) for t in conv["turns"]]
        got = app.s3_callend_topic_turns(turns, {"callend": mark})
        for i in mark["detour_turns"]:
            self.assertNotIn(turns[i], got)
        self.assertEqual(got[-1], turns[-1])           # the sign-off is still there

"""[s3-rounds] [s3-carry] [s3-withhold] The round's own rolls (tempers, the
shock beat, the interjections, the mention), the carry between rounds, and
a planned round that says why it never aired."""
import asyncio
import copy
import json
import re
import time
import unittest

import system3
import system3_tables
import system3_runtime

from test_system3_runtime import FakeStation, ctx, settle, written
from fastapi import FastAPI
from fastapi.testclient import TestClient


def rolls_inputs(**over):
    base = {"road": "banter", "seats": ["A", "B"], "turns": 12, "names": {"A": "Host", "B": "Skip"},
            "subject": {"topic": "raccoon van", "keywords": ["raccoon"]}, "availability": {"speakbox": True},
            "speakerbox_rates": {"prepend": 0.49, "append": 0.68},
            "round_rolls": True, "dice_hosts": True, "station_name": "Pine Box FM",
            "interjections": ["Oh come on.", "No.", "What?", "Stop it.", "Here we go."]}
    base.update(over)
    return base


def carry_in(**over):
    base = {"from": "prev", "road": "news", "age": 300.0, "factor": 0.75,
            "seats": {"A": {"table": "ES1", "category": "anger", "id": "anger.fury", "label": "fury",
                            "intensity": 0.8, "dims": {"irritation": 0.9}, "position": -0.5, "energy": 0.7}},
            "dynamics": {"tension": 0.8}, "unresolved": [{"turn": 3, "by": "A", "act": "challenge"}],
            "landing": {"who": "cohost", "name": "Skip", "text": "And that is why the cat was never in the sewer."},
            "tempers": ["smug"]}
    base.update(over)
    return base


def plan(seed, **over):
    return system3.plan_scene(rolls_inputs(**over), system3.default_config(),
                              system3.normalise_settings({"mode": "active", "test_seed": seed}), conversation_id="r-" + seed)


class RoundRollTests(unittest.TestCase):
    def test_live_record_talk_is_a_roulette_event_inside_banter(self):
        record = {"id": "record-17", "title": "Blue Hour", "artist": "The Harbor"}
        settings = system3.normalise_settings(
            {"mode": "active", "test_seed": "record-talk", "controls": {"track_talk": 1.0}})
        conv = system3.plan_scene(rolls_inputs(record=record), system3.default_config(), settings)
        events = [e for e in conv["decision_events"] if e["family"] == "TRACK_TALK"]
        self.assertEqual(len(events), 1)
        self.assertIsNotNone(events[0]["rng"])
        turns = [t for t in conv["turns"] if t.get("track_talk")]
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["track_talk"], record)
        self.assertEqual(events[0]["turn_id"], turns[0]["turn_id"])
        self.assertIn("Blue Hour", system3.render_sheet(conv))
        self.assertIn("The Harbor", system3.render_sheet(conv))
        self.assertTrue(system3.replay(json.loads(json.dumps(conv)), system3.default_config())["ok"])
        for missing in (rolls_inputs(), rolls_inputs(record=record, bank=True)):
            absent = system3.plan_scene(missing, system3.default_config(), settings)
            self.assertFalse(any(e["family"] == "TRACK_TALK" for e in absent["decision_events"]))

    def test_default_config_carries_the_three_new_tables_and_controls(self):
        cfg = system3.default_config()
        # [s3-cast] [s3-events] later default tables come after them
        ids = [t["id"] for t in cfg["tables"]]
        self.assertEqual(ids[ids.index("TEMPER1"):ids.index("TEMPER1") + 3], ["TEMPER1", "SHOCK1", "INTERJECT1"])
        for key in ("shock_beat", "interjections", "mention"):
            self.assertEqual(system3.DEFAULT_CONTROLS[key], 0.5)
        # the new families validate as tables the desk can edit
        system3.validate_table(system3_tables.TEMPER1)

    def test_rolls_are_recorded_and_land_in_the_running_order(self):
        hits = {"TEMPER": 0, "SHOCK": 0, "INTERJECT": 0, "MENTION": 0}
        attached = {"shock": 0, "mention": 0, "interject": 0}
        for i in range(40):
            conv = plan("s%d" % i)
            fams = [e["family"] for e in conv["decision_events"]]
            for f in hits:
                hits[f] += fams.count(f)
            # the tempers: one per host seat, never the same one twice, in the head
            self.assertEqual(sorted(conv["tempers"]), ["A", "B"])
            self.assertNotEqual(conv["tempers"]["A"]["id"], conv["tempers"]["B"]["id"])
            sheet = system3.render_sheet(conv)
            self.assertIn("TONIGHT'S TEMPERS (rolled): A (Host) is " + conv["tempers"]["A"]["text"], sheet)
            if conv.get("shock_plan"):
                t = next(t for t in conv["turns"] if t.get("shock"))
                attached["shock"] += 1
                self.assertIn("IS OPENLY %s" % conv["shock_plan"]["text"].upper(), sheet)
                self.assertTrue(t["index"] >= 1)
                self.assertIn(t["speaker"], system3.HOST_SEATS)
                self.assertTrue(any(d["family"] == "SHOCK" for d in t["decisions"]))
            if conv.get("mention_plan"):
                attached["mention"] += 1
                self.assertIn("Works the station's name, Pine Box FM, in naturally here", sheet)
            if conv.get("interject_plan"):
                attached["interject"] += 1
                steps = [t["step"] for t in conv["turns"]]
                i_at = steps.index("interject")
                self.assertEqual(steps[i_at + 1], "carry_on")
                self.assertTrue(conv["turns"][i_at - 1].get("long_roll"))
                self.assertEqual(conv["turns"][i_at - 1]["speaker"], conv["turns"][i_at + 1]["speaker"])
                self.assertNotEqual(conv["turns"][i_at]["speaker"], conv["turns"][i_at + 1]["speaker"])
                self.assertIn("gets a word in edgewise while", sheet)
                self.assertIn("carries straight on over the interruption", sheet)
                for phrase in conv["interject_plan"]["phrases"]:
                    self.assertIn(json.dumps(phrase), sheet)
            # nobody speaks twice in a row, the budget is kept, every draw replays
            seats = [t["speaker"] for t in conv["turns"]]
            self.assertFalse(any(seats[j] == seats[j + 1] for j in range(len(seats) - 1)))
            self.assertEqual(len(conv["turns"]), 12)
            self.assertTrue(system3.replay(json.loads(json.dumps(conv)), system3.default_config())["ok"])
        self.assertEqual(hits["TEMPER"], 80)
        self.assertEqual(hits["SHOCK"], 40)
        self.assertEqual(hits["INTERJECT"], 40)
        self.assertEqual(hits["MENTION"], 40)
        # the odds: a control of 0.5 is one round in two for the beat and the roll, ~30% for the mention
        self.assertTrue(10 <= attached["shock"] <= 30, attached)
        self.assertTrue(10 <= attached["interject"] <= 30, attached)
        self.assertTrue(4 <= attached["mention"] <= 22, attached)

    def test_rolls_are_opt_in_and_on_their_own_stream(self):
        # no round_rolls: nothing drawn, the golden trajectory untouched
        plain = system3.plan_scene({"road": "banter", "seats": ["A", "B"], "turns": 10,
                                    "subject": {"topic": "raccoon van", "keywords": ["raccoon"]},
                                    "availability": {"speakbox": True},
                                    "speakerbox_rates": {"prepend": 0.49, "append": 0.68}},
                                   system3.default_config(), system3.normalise_settings({"mode": "active", "test_seed": "golden-1"}),
                                   conversation_id="golden")
        self.assertFalse(any(e["family"] in ("TEMPER", "SHOCK", "INTERJECT", "MENTION", "CARRY") for e in plain["decision_events"]))
        # with the rolls but the desk's dice_hosts off: no TEMPER; the turn draws (main stream) are the same
        # as a round with the switch on, because the round rolls live on seed|round
        a = plan("same", dice_hosts=False)
        b = plan("same", dice_hosts=True)
        self.assertFalse(any(e["family"] == "TEMPER" for e in a["decision_events"]))
        self.assertTrue(any(e["family"] == "TEMPER" for e in b["decision_events"]))
        es = lambda c: [(e["family"], (e.get("rng") or {}).get("u")) for e in c["decision_events"] if e["family"] == "ES"]
        self.assertEqual(es(a), es(b))
        # a call never rolls interjections; a caller's turn never takes the shock beat
        call = plan("call", seats=["A", "B", "C"], interjections=[])
        self.assertFalse(any(e["family"] == "INTERJECT" for e in call["decision_events"]))
        for t in call["turns"]:
            if t.get("shock"):
                self.assertIn(t["speaker"], system3.HOST_SEATS)

    def test_a_worn_temper_weighs_a_quarter(self):
        conv = plan("worn", carry=carry_in(tempers=["smug", "giddy"]))
        ev = next(e for e in conv["decision_events"] if e["family"] == "TEMPER")
        rows = {r["id"]: r for r in ev["stages"][0]["candidates"]}
        self.assertEqual(rows["smug"]["weight"], 0.25)
        self.assertIn("worn in the last rounds x0.25", rows["smug"]["why"])
        self.assertEqual(rows["bored"]["weight"], 1.0)

    def test_a_call_rolls_tempers_shock_and_mention_but_never_interjections(self):
        cfg = system3.default_config()
        inp = rolls_inputs(road="caller", seats=["A", "B", "C"], turns=11, names={"A": "Host", "B": "Skip", "C": "Fez"},
                           call={"name": "Fez", "first": "Fez", "other": "Skip", "topic": "", "speakerbox": "", "story": False,
                                 "scenario_clause": ""})
        conv = system3.new_conversation(inp, cfg, system3.normalise_settings({"mode": "active", "test_seed": "c1"}), conversation_id="c1")
        system3.plan_call(conv, cfg, inp)
        fams = [e["family"] for e in conv["decision_events"]]
        self.assertEqual(fams.count("TEMPER"), 2)                 # A and B, never the caller
        self.assertEqual(fams.count("SHOCK"), 1)
        self.assertEqual(fams.count("MENTION"), 1)
        self.assertEqual(fams.count("INTERJECT"), 0)
        self.assertNotIn("C", conv["tempers"])
        sheet = system3.render_call_sheet(conv)
        self.assertIn("TONIGHT'S TEMPERS (rolled)", sheet)
        for tn in conv["turns"]:
            if tn.get("shock") or tn.get("mention"):
                self.assertIn(tn["speaker"], system3.HOST_SEATS)
        self.assertTrue(system3.replay(json.loads(json.dumps(conv)), cfg)["ok"])

    def test_legs_roads_roll_tempers_shock_and_mention_but_not_interjections(self):
        cfg = system3.default_config()
        inp = rolls_inputs(road="news", turns=6, availability={"news": True})
        conv = system3.new_conversation(inp, cfg, system3.normalise_settings({"mode": "active", "test_seed": "n1"}), conversation_id="n1")
        system3.plan_legs(conv, cfg, inp, "news")
        fams = [e["family"] for e in conv["decision_events"]]
        self.assertEqual(fams.count("TEMPER"), 2)
        self.assertEqual(fams.count("SHOCK"), 1)
        self.assertEqual(fams.count("MENTION"), 1)
        self.assertEqual(fams.count("INTERJECT"), 0)
        self.assertIn("TONIGHT'S TEMPERS (rolled)", system3.render_legs_sheet(conv))
        self.assertEqual(conv["road_structure"]["road"], "news")


class CarryTests(unittest.TestCase):
    def test_the_carry_is_this_rounds_start_and_turn_one_picks_it_up(self):
        conv = plan("carry", carry=carry_in())
        a = conv["turns"][0]["state_before"]["participants"][0]
        self.assertEqual(a["emotion"]["source"], "carried")
        self.assertEqual(a["emotion"]["category"], "anger")
        self.assertAlmostEqual(a["emotion"]["intensity"], 0.6, places=3)          # 0.8 x 0.75
        self.assertAlmostEqual(a["position"], -0.375, places=3)
        self.assertEqual(conv["turns"][0]["state_before"]["subject"]["unresolved_points"][0]["act"], "challenge")
        # the dynamics moved toward the carry by the factor
        self.assertAlmostEqual(conv["turns"][0]["state_before"]["dynamics"]["tension"], 0.35 + (0.8 - 0.35) * 0.75, places=3)
        ev = conv["decision_events"][0]
        self.assertEqual(ev["family"], "CARRY")
        self.assertIsNone(ev["rng"])
        self.assertEqual(ev["meta"]["from"], "prev")
        self.assertEqual(conv["carry"]["seats"], ["A"])
        sheet = system3.render_sheet(conv)
        self.assertIn(' 1  A  - picks straight up from where the last exchange landed - Skip said: "And that is why the cat was never in the sewer." - and opens the subject', sheet)
        self.assertTrue(system3.replay(json.loads(json.dumps(conv)), system3.default_config())["ok"])

    def test_a_seeded_round_keeps_its_passage_opening(self):
        conv = plan("seeded", carry=carry_in(), subject={"topic": "x", "seeded": True})
        self.assertIn(" 1  A  - opens with the passage above, word for word, as their own speech - as their answer to "
                      "where the last exchange landed (Skip said: \"And that is why the cat was never in the sewer.\")", system3.render_sheet(conv))
        self.assertNotIn("picks straight up", system3.render_sheet(conv))

    def test_no_carry_means_a_cold_start_and_no_event(self):
        conv = plan("cold")
        self.assertIsNone(conv["carry"])
        self.assertFalse(any(e["family"] == "CARRY" for e in conv["decision_events"]))
        self.assertEqual(conv["turns"][0]["state_before"]["participants"][0]["emotion"]["source"], "initial")

    def test_legs_sheet_names_the_landing(self):
        cfg = system3.default_config()
        inp = rolls_inputs(road="memo", turns=4, carry=carry_in())
        conv = system3.new_conversation(inp, cfg, system3.normalise_settings({"mode": "active", "test_seed": "m1"}), conversation_id="m1")
        system3.plan_legs(conv, cfg, inp, "memo")
        sheet = system3.render_legs_sheet(conv)
        self.assertIn("It follows straight on from the last exchange, which landed on Skip's words: \"And that is why the cat was never in the sewer.\" - turn 1 picks up from there.", sheet)


class RuntimeCarryTests(unittest.TestCase):
    def boot(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.station = FakeStation(self.tmp.name)
        self.station["read_bombshells"] = lambda: []
        app = FastAPI()
        system3_runtime.install(app, self.station)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.rt = self.station["_system3"]()
        self.addCleanup(self.rt.store.close)
        self.addCleanup(settle)
        r = self.client.post("/api/system3/settings", json={"mode": "active", "roads": ["banter"], "test_seed": "rc-1"},
                             headers={"Authorization": "Bearer k"})
        self.assertEqual(r.status_code, 200, r.text)
        return self.rt

    def run_(self, coro):
        return asyncio.new_event_loop().run_until_complete(coro)

    def live_ctx(self, **over):
        c = ctx(bank=False, dj={"host_name": "Caine", "cohost_name": "Skip", "station_name": "Pine Box FM",
                                "dice_hosts": True, "diatribe_interjections": ["Oh come on.", "No.", "What?"],
                                "speakbox_prepend_rate": 0.9, "speakbox_append_rate": 0.9})
        c.update(over)
        return c

    def test_a_round_on_the_ledger_hands_its_ending_to_the_next_live_round(self):
        rt = self.boot()
        first = self.run_(self.station["system3_direct_banter"](**self.live_ctx()))
        self.assertTrue(first.active)
        self.assertIsNone(first.conv["carry"])
        self.assertTrue(first.conv["inputs"]["round_rolls"])
        self.assertEqual(first.conv["inputs"]["station_name"], "Pine Box FM")
        self.assertEqual(first.conv["inputs"]["interjections"], ["Oh come on.", "No.", "What?"])
        entry = {"script": written(first), "quotes": {}, "dealt": []}
        self.station["system3_bind_entry"](entry, first)
        self.assertEqual(entry["system3"]["planned_turns"], len(first.conv["turns"]))
        self.assertFalse(entry["system3"]["bank"])
        self.assertEqual(len(rt.open), 0)                       # bound: no longer open
        # the ledger commit: what the round left on the air
        rows = [{"line_id": "l%d" % i, "who": "dj" if t["speaker"] == "A" else "cohost", "text": t["text"],
                 "system3": {"conversation_id": first.id, "turn_id": t["turn_id"]}}
                for i, t in enumerate(first.conv["turns"])]
        self.station["system3_observe_ledger"](7, "sid-1", rows, "banter")
        settle()
        carry = rt.carry_now()
        self.assertEqual(carry["from"], first.id)
        self.assertEqual(sorted(carry["seats"]), ["A", "B"])
        self.assertEqual(carry["landing"]["text"], first.conv["turns"][-1]["text"])
        self.assertEqual(carry["landing"]["name"], "Skip" if first.conv["turns"][-1]["speaker"] == "B" else "Caine")
        self.assertEqual(sorted(carry["tempers"]), sorted(t["id"] for t in first.conv["tempers"].values()))
        status = self.client.get("/api/system3/status").json()
        self.assertEqual(status["carry"]["from"], first.id)
        # the next LIVE round starts there
        second = self.run_(self.station["system3_direct_banter"](**self.live_ctx()))
        self.assertEqual(second.conv["carry"]["from"], first.id)
        fams = [e["family"] for e in second.conv["decision_events"]]
        self.assertIn("CARRY", fams)
        self.assertLess(fams.index("CARRY"), fams.index("TEMPER"))
        self.assertIn("where the last exchange landed", second.sheet)
        self.assertEqual(second.conv["turns"][0]["state_before"]["participants"][0]["emotion"]["source"], "carried")
        # a BANKED round gets no carry in its words...
        banked = self.run_(self.station["system3_direct_banter"](**self.live_ctx(bank=True)))
        self.assertIsNone(banked.conv["carry"])
        self.assertNotIn("the last exchange landed", banked.sheet)
        # ...but its voice starts from the carry at air
        bentry = {"script": written(banked), "quotes": {}, "dealt": []}
        self.station["system3_bind_entry"](bentry, banked)
        self.assertTrue(bentry["system3"]["bank"])
        text = self.station["banter_turns"](bentry["script"])[1][1]
        who = "cohost" if banked.conv["turns"][1]["speaker"] == "B" else "dj"
        blended = self.station["system3_perf_state"](bentry, None, text, who)
        planned = banked.conv["turns"][1]["performance"]["dims"]
        seat = "B" if who == "cohost" else "A"
        f = 0.4 * carry["factor"]
        for d in system3.EMOTION_DIMS:
            self.assertAlmostEqual(blended[d], (1 - f) * planned[d] + f * carry["seats"][seat]["dims"][d], places=2)
        settle()
        obs = [e for e in rt.store.conversation(banked.id)["observations_air"] if e.get("stage") == "delivery"]
        self.assertEqual(len(obs), 1)
        self.assertEqual(rt.metrics["carry_delivery"], 1)
        self.assertEqual(rt.metrics["carried"], 1)
        self.assertEqual(rt.metrics["carry_in"], 1)

    def test_the_carry_fades_and_a_single_line_hands_nothing_on(self):
        rt = self.boot()
        with rt.lock:
            rt.carry = {"at": time.time() - system3_runtime.CARRY_WINDOW - 5, "from": "old", "seats": {"A": {"category": "joy"}}}
        self.assertIsNone(rt.carry_now())
        h = self.run_(self.station["system3_direct_banter"](**self.live_ctx()))
        self.assertIsNone(h.conv["carry"])
        line = self.run_(self.station["system3_direct_line"](road="station_id", who="third", dj={}, text="Pine Box FM."))
        self.assertIsNone(rt._hand_on(line.conv, [{"who": "third", "text": "Pine Box FM."}]))

    def test_a_withheld_round_says_why_and_a_forgotten_one_is_swept(self):
        rt = self.boot()
        h = self.run_(self.station["system3_direct_banter"](**self.live_ctx()))
        self.assertIn(h.id, rt.open)
        self.station["system3_withhold"](h, "the writer returned no turns", "writing")
        settle()
        self.assertNotIn(h.id, rt.open)
        self.assertEqual(h.conv["status"], "withheld")
        got = rt.store.conversation(h.id)
        self.assertEqual(got["status"], "withheld")
        self.assertEqual([e["why"] for e in got["observations_air"] if e.get("stage") == "writing"], ["the writer returned no turns"])
        self.assertEqual(rt.metrics["withheld"], 1)
        # a round planned and then forgotten by the station
        h2 = self.run_(self.station["system3_direct_banter"](**self.live_ctx()))
        self.assertEqual(rt.sweep_open(now=time.time()), 0)                 # too young
        self.assertEqual(rt.sweep_open(now=time.time() + system3_runtime.ABANDON_AFTER + 1), 1)
        settle()
        got2 = rt.store.conversation(h2.id)
        self.assertEqual(got2["status"], "abandoned")
        self.assertTrue(any(e.get("stage") == "abandoned" for e in got2["observations_air"]))
        self.assertEqual(rt.metrics["abandoned"], 1)
        self.assertNotIn(h2.id, rt.open)
        self.assertEqual(self.client.get("/api/system3/status").json()["open_rounds"], 0)

    def test_a_stored_config_gains_the_tables_it_predates_once(self):
        rt = self.boot()
        old = system3.default_config()
        old["tables"] = [t for t in old["tables"] if t["family"] in ("CTS", "ES", "RS", "IRS", "FL")]
        rt.store.save_config(old, "as saved before the round rolls existed")
        rt.load()
        ids = [t["id"] for t in rt.config["tables"]]
        added = [t["id"] for t in system3_tables.default_tables() if t["family"] not in ("CTS", "ES", "RS", "IRS", "FL")]
        self.assertEqual(ids[-len(added):], added)
        self.assertEqual(rt.config["defaults_added"], sorted(added))
        # the store keys versions by content: this config IS the default, so the pointer moved to it
        self.assertEqual(system3.config_hash(rt.store.config()), system3.config_hash(rt.config))
        self.assertEqual(rt.add_missing_default_tables(), [])
        # a deleted table stays deleted on the next load
        without = copy.deepcopy(rt.config)
        without["tables"] = [t for t in without["tables"] if t["id"] != "SHOCK1"]
        rt.store.save_config(without, "SHOCK1 removed by the operator")
        rt.load()
        self.assertNotIn("SHOCK1", [t["id"] for t in rt.config["tables"]])
        self.assertEqual(rt.add_missing_default_tables(), [])

    def test_a_legs_round_reports_its_row_count_as_the_rounds_size(self):
        rt = self.boot()
        self.client.post("/api/system3/settings", json={"mode": "active"}, headers={"Authorization": "Bearer k"})
        h = self.run_(self.station["system3_direct_banter"](**self.live_ctx(road="news", lines=6, news_titles="A / B", own_material=True)))
        self.assertTrue(h.active)
        rows = len(re.findall(r"(?m)^\s*\d+\s+[AB]\s+-", h.sheet))
        self.assertEqual(h.turns, rows)
        self.assertEqual(h.turns, len(h.conv["turns"]))


if __name__ == "__main__":
    unittest.main()

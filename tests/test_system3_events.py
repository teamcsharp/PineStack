"""[s3-events] What can happen in a segment (EVENT tables): a caller who gets
emotional, wins a prize, turns on the hosts, is interrupted from upstairs, goes
off on a tangent, is pulled away by what is going on around them or loses the
line - each kind its own die, landing on one turn, an ending cutting the call
there and a host reacting to the dead line."""
import asyncio
import copy
import json
import tempfile
import unittest

import system3
import system3_tables
import system3_runtime

from test_system3_runtime import FakeStation, ctx, settle
from fastapi import FastAPI
from fastapi.testclient import TestClient


def event_config(odds=None, roads=None, max_events=None):
    """The default config with CALLEVENT1's odds overridden per kind."""
    cfg = system3.default_config()
    t = next(t for t in cfg["tables"] if t["id"] == "CALLEVENT1")
    for cat in t["categories"]:
        cat["odds"] = (odds or {}).get(cat["id"], 0.0)
    if roads is not None:
        t["roads"] = roads
    if max_events is not None:
        t["max_events"] = max_events
    for other in cfg["tables"]:                 # [s3-callarc] the events are tested on the old middle
        if other["family"] in ("CALLARC", "CALLSHIFT"):
            other["enabled"] = False
    return cfg


def call_inputs(**over):
    base = {"road": "caller", "seats": ["A", "B", "C"], "turns": 12, "at": 1_800_000_000.0,
            "names": {"A": "Host", "B": "Skip", "C": "Dana"}, "roles": {"A": "dj", "B": "cohost", "C": "caller"},
            "subject": {"topic": "a raccoon in the van"}, "availability": {"call_passage": True},
            "call": {"name": "Dana", "first": "Dana", "other": "Skip", "speakerbox": "The raccoon took the van."},
            "event_rolls": True}
    base.update(over)
    return base


def settings(seed):
    return system3.normalise_settings({"mode": "active", "test_seed": seed})


def plan_call(seed, cfg, **over):
    conv = system3.new_conversation(call_inputs(**over), cfg, settings(seed), conversation_id="ev-" + seed)
    return system3.plan_call(conv, cfg, conv["inputs"])


def events(conv):
    return [e for e in conv["decision_events"] if e["family"] == "EVENT"]


class EventTableTests(unittest.TestCase):
    def test_the_call_events_table_is_a_default_and_validates(self):
        ids = [t["id"] for t in system3.default_config()["tables"]]
        self.assertIn("CALLEVENT1", ids)
        got = system3.validate_table(system3_tables.CALLEVENT1)
        kinds = {c["id"]: c for c in got["categories"]}
        for want in ("outburst", "upstairs", "tangent", "background", "pulled_away", "lost", "hangs_up"):
            self.assertIn(want, kinds)
        self.assertTrue(kinds["pulled_away"]["ends"] and kinds["lost"]["ends"] and kinds["hangs_up"]["ends"])
        self.assertFalse(kinds["background"]["ends"])
        self.assertEqual(got["roads"], ["caller"])
        bad = copy.deepcopy(system3_tables.CALLEVENT1)
        bad["categories"][0]["odds"] = 5
        bad["categories"][0]["seat"] = "nobody"
        fixed = system3.validate_table(bad)["categories"][0]
        self.assertEqual((fixed["odds"], fixed["seat"]), (1.0, "any"))


class CallEventTests(unittest.TestCase):
    def test_a_happening_is_three_draws_on_one_turn_of_its_seat(self):
        conv = plan_call("upstairs", event_config({"upstairs": 1.0}))
        ev = [e for e in events(conv) if e["meta"]["kind"] == "upstairs"][0]
        self.assertEqual([s["stage"] for s in ev["stages"]], ["dice", "item", "turn"])
        landed = [t for t in conv["turns"] if t.get("events")]
        self.assertEqual(len(landed), 1)
        self.assertIn(landed[0]["speaker"], system3.HOST_SEATS)
        self.assertNotIn(landed[0].get("leg"), system3.EVENT_FIXED_LEGS)
        self.assertEqual(ev["turn_id"], landed[0]["turn_id"])
        sheet = system3.render_call_sheet(conv)
        self.assertIn("WHAT HAPPENS ON THIS TURN (A message from upstairs)", sheet)
        self.assertIn("Dana", sheet)
        self.assertTrue(system3.turn_stamp(conv, landed[0])["round"].get("events"))

    def test_an_ending_cuts_the_call_and_a_host_reacts_to_the_dead_line(self):
        full = plan_call("end", event_config({}))
        conv = plan_call("end", event_config({"pulled_away": 1.0}))
        ev = [e for e in events(conv) if e["meta"]["kind"] == "pulled_away"][0]
        self.assertTrue(ev["selected"]["ends"])
        at = conv["event_end"]
        self.assertIsNotNone(at)
        self.assertGreaterEqual(at, 6, "never before the call has its turns")
        self.assertEqual(len(conv["turns"]), at + 2)
        self.assertLess(len(conv["turns"]), len(full["turns"]) + 1)
        end_turn, last = conv["turns"][at], conv["turns"][-1]
        self.assertEqual(end_turn["speaker"], "C")
        self.assertTrue(end_turn.get("ends_here"))
        self.assertIn(last["speaker"], system3.HOST_SEATS)
        self.assertTrue(last.get("after_end"))
        sheet = system3.render_call_sheet(conv)
        self.assertIn("THIS IS WHERE IT ENDS", sheet)
        self.assertIn("The line has just gone dead", sheet)
        self.assertIn("This call ENDS EARLY", sheet)
        self.assertNotIn("the spoken sign-off on the last turn are not style notes", sheet)

    def test_at_most_max_events_land_and_only_one_ending(self):
        every = {k: 1.0 for k in ("outburst", "prize", "anger", "upstairs", "tangent", "background",
                                  "pulled_away", "lost", "hangs_up")}
        conv = plan_call("cap", event_config(every, max_events=2), turns=16)
        landed = [e for e in events(conv) if e["selected"]["id"] != "NONE"]
        self.assertEqual(len(landed), 2)
        self.assertLessEqual(sum(1 for e in landed if e["selected"].get("ends")), 1)
        skipped = [e for e in events(conv) if e["meta"].get("why", "").startswith("the segment already holds")]
        self.assertTrue(skipped)
        self.assertEqual(sum(len(t.get("events") or []) for t in conv["turns"]), 2)

    def test_a_happening_after_the_ending_never_happens(self):
        conv = plan_call("after", event_config({"pulled_away": 1.0, "background": 1.0}, max_events=3), turns=16)
        end = conv["event_end"]
        for t in conv["turns"]:
            for e in t.get("events") or []:
                self.assertLessEqual(t["index"], end)

    def test_the_rolls_are_opt_in_and_on_their_own_streams(self):
        cfg = event_config({"background": 1.0, "upstairs": 1.0})
        with_ev = plan_call("same", cfg)
        without = plan_call("same", cfg, event_rolls=False)
        strip = lambda c: [(e["family"], (e["selected"] or {}).get("id"), (e.get("rng") or {}).get("u"))
                           for e in c["decision_events"] if e["family"] != "EVENT"]
        self.assertEqual(strip(with_ev), strip(without))
        self.assertFalse(events(without))

    def test_a_tangent_needs_the_calls_own_passage(self):
        conv = plan_call("tan", event_config({"tangent": 1.0}), availability={})
        ev = [e for e in events(conv) if e["meta"]["kind"] == "tangent"][0]
        self.assertEqual(ev["selected"]["id"], "NONE")
        self.assertIn("call_passage", ev["meta"]["why"])

    def test_the_happening_leans_the_feeling_of_its_turn(self):
        cfg = event_config({"outburst": 1.0})
        t = next(t for t in cfg["tables"] if t["id"] == "CALLEVENT1")
        cat = next(c for c in t["categories"] if c["id"] == "outburst")
        cat["items"] = [i for i in cat["items"] if i["id"] == "tears"]
        conv = plan_call("tears", cfg)
        plain = plan_call("tears", cfg, event_rolls=False)
        turn = next(t for t in conv["turns"] if t.get("events"))

        def sadness_weight(c):
            es = next(e for e in c["decision_events"] if e["family"] == "ES" and e["turn_index"] == turn["index"])
            cats = next(s for s in es["stages"] if s["stage"] == "category")
            return next(x["weight"] for x in cats["candidates"] if x["id"] == "sadness")
        self.assertAlmostEqual(sadness_weight(conv) / sadness_weight(plain), 4.0, places=2)

    def test_replay_reproduces_a_call_that_ended_early(self):
        cfg = event_config({"lost": 1.0, "outburst": 1.0})
        conv = plan_call("replay", cfg)
        self.assertTrue(system3.replay(json.loads(json.dumps(conv)), cfg)["ok"])

    def test_a_banter_round_can_have_happenings_but_never_ends(self):
        cfg = event_config({"background": 1.0, "pulled_away": 1.0}, roads=["banter"])
        # a banter table's seats are hosts: make the kinds any-seat
        t = next(t for t in cfg["tables"] if t["id"] == "CALLEVENT1")
        for c in t["categories"]:
            c["seat"] = "any"
        conv = system3.plan_scene({"road": "banter", "seats": ["A", "B"], "turns": 10, "event_rolls": True,
                                   "subject": {"topic": "x"}}, cfg, settings("bt"))
        self.assertTrue(any(t.get("events") for t in conv["turns"]))
        self.assertIsNone(conv.get("event_end"))
        self.assertEqual(len(conv["turns"]), conv["timing"]["turn_budget"])


class RuntimeEventTests(unittest.TestCase):
    def test_a_call_the_roulette_ends_is_marked_on_the_stations_call_meta(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        station = FakeStation(tmp.name)
        station["read_bombshells"] = lambda: []
        app = FastAPI()
        system3_runtime.install(app, station)
        client = TestClient(app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        rt = station["_system3"]()
        self.addCleanup(rt.store.close)
        self.addCleanup(settle)
        client.post("/api/system3/settings", json={"mode": "active", "test_seed": "rt-end"},
                    headers={"Authorization": "Bearer k"})
        t = next(t for t in rt.config["tables"] if t["id"] == "CALLEVENT1")
        t = copy.deepcopy(t)
        for c in t["categories"]:
            c["odds"] = 1.0 if c["id"] == "lost" else 0.0
        r = client.put("/api/system3/tables/CALLEVENT1", json=t, headers={"Authorization": "Bearer k"})
        self.assertEqual(r.status_code, 200, r.text)
        meta = {"topic": "the van", "speakerbox_text": "The raccoon took the van."}
        h = asyncio.new_event_loop().run_until_complete(station["system3_direct_banter"](
            **ctx(bank=False, lines=12, caller_name="Dana Reyes", seats=["A", "B", "C"], road="caller",
                  call_meta=meta, dj={"host_name": "Caine", "cohost_name": "Skip"})))
        self.assertTrue(h.active)
        self.assertIsNotNone(h.conv.get("event_end"))
        self.assertTrue(meta.get("ended", "").startswith("The call is lost"))
        self.assertIn("ENDS EARLY", h.sheet)


if __name__ == "__main__":
    unittest.main()

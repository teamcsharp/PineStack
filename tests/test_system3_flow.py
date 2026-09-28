"""[s3-flow] One message's roulette feeds the next: follow-on odds, a static
node whose item still rolls, who opens, the operator's topic, uniqueness across
rounds, and each reply told what it answers."""
import copy
import unittest

import system3


def inputs(**over):
    base = {"road": "banter", "seats": ["A", "B"], "turns": 10, "names": {"A": "Host", "B": "Skip"},
            "subject": {"topic": "the raccoon took the van"}}
    base.update(over)
    return base


def settings(seed):
    return system3.normalise_settings({"mode": "active", "test_seed": seed})


def plan(seed, cfg=None, **over):
    return system3.plan_scene(inputs(**over), cfg or system3.default_config(), settings(seed))


def es_or_act_events(conv, family):
    return [e for e in conv["decision_events"] if e["family"] == family]


class FollowOnTests(unittest.TestCase):
    def test_a_follow_on_multiplies_the_next_wheel_and_says_why(self):
        cfg = system3.default_config()
        # every IRS category leans hard after ANY RS item the round rolls, via its category key
        rs_cats = {c["id"] for t in cfg["tables"] if t["family"] == "RS" for c in t["categories"]}
        for t in cfg["tables"]:
            if t["family"] == "IRS":
                for c in t["categories"]:
                    c["after"] = {"RS:" + rc: 3.0 for rc in rs_cats}
        conv = plan("follow", cfg)
        irs = es_or_act_events(conv, "IRS")
        self.assertTrue(irs)
        reasons = [w for e in irs for st in e["stages"] if st["stage"] == "item"
                   for c in st["candidates"] for w in c.get("why") or []]
        self.assertTrue(any(w.startswith("after RS:") and "x3.00" in w for w in reasons), reasons[:10])

    def test_the_default_tables_carry_follow_on_odds(self):
        cfg = system3.default_config()
        irs1 = next(t for t in cfg["tables"] if t["id"] == "IRS1")
        conf = next(c for c in irs1["categories"] if c["id"] == "confrontational")
        self.assertEqual(conf["after"]["RS:argue"], 1.6)

    def test_each_reply_is_told_what_it_answers(self):
        conv = plan("answers")
        rows = system3.render_sheet(conv).split("\n")
        told = [r for r in rows if "answers what" in r and " (" in r.split("answers what", 1)[1][:60]]
        self.assertTrue(told, "a reply names the act and feeling of the turn before")


class OverrideTests(unittest.TestCase):
    def test_a_static_node_pins_the_category_and_rolls_the_item(self):
        cfg = system3.default_config()
        steps = cfg["structure"]["steps"]
        for d in steps[1]["draws"]:
            if d["family"] == "RS":
                d["category"] = "argue"
        conv = plan("static", cfg)
        ev = next(e for e in conv["decision_events"] if e["family"] == "RS" and e["turn_index"] == 1)
        self.assertEqual(ev["selected"]["category"], "argue")
        self.assertEqual(ev["meta"].get("authority"), "category")
        self.assertIsNotNone(ev["rng"], "the item inside the pinned category is still a roll")
        cats = next(s for s in ev["stages"] if s["stage"] == "category")
        self.assertEqual([c["id"] for c in cats["candidates"]], ["argue"])

    def test_a_category_nobody_holds_rolls_the_whole_family_and_says_so(self):
        cfg = system3.default_config()
        for d in cfg["structure"]["steps"][1]["draws"]:
            if d["family"] == "RS":
                d["category"] = "no_such_category"
        conv = plan("missing", cfg)
        ev = next(e for e in conv["decision_events"] if e["family"] == "RS" and e["turn_index"] == 1)
        self.assertIn("no table holds", ev["meta"].get("why", ""))

    def test_the_structure_names_who_opens(self):
        cfg = system3.default_config()
        cfg["structure"]["initiator"] = "B"
        conv = plan("opener", cfg)
        self.assertEqual(conv["turns"][0]["speaker"], "B")
        self.assertEqual(plan("opener")["turns"][0]["speaker"], "A")

    def test_the_operators_topic_leads_its_turn(self):
        cfg = system3.default_config()
        cfg["structure"]["steps"][0]["topic"] = "the pigeons downtown are unionizing"
        conv = plan("topic", cfg)
        self.assertEqual(conv["subject"]["topic"], "the pigeons downtown are unionizing")
        self.assertEqual(conv["subject"]["authority"], "operator")
        row1 = next(r for r in system3.render_sheet(conv).split("\n") if r.startswith(" 1  "))
        self.assertIn('on this subject, in their own words: "the pigeons downtown are unionizing"', row1)


class UniquenessTests(unittest.TestCase):
    def test_an_item_a_recent_round_used_weighs_a_quarter(self):
        cfg = system3.default_config()
        rs_items = ["RS:%s" % i["id"] for t in cfg["tables"] if t["family"] == "RS"
                    for c in t["categories"] for i in c["items"]]
        conv = plan("unique", cfg, recent_items=rs_items)
        reasons = [w for e in es_or_act_events(conv, "RS") for st in e["stages"] if st["stage"] == "item"
                   for c in st["candidates"] for w in c.get("why") or []]
        self.assertIn("used in a recent round x0.25", reasons)


class RuntimeUniquenessTests(unittest.TestCase):
    def test_recent_rounds_and_recent_air_reach_the_next_round(self):
        import asyncio
        import tempfile
        import system3_runtime
        from test_system3_runtime import FakeStation, ctx, settle
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
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
        client.post("/api/system3/settings", json={"mode": "active", "test_seed": "uniq"},
                    headers={"Authorization": "Bearer k"})
        run = lambda c: asyncio.new_event_loop().run_until_complete(c)
        h1 = run(station["system3_direct_banter"](**ctx(bank=True, dj={"host_name": "Caine", "cohost_name": "Skip"})))
        self.assertTrue(rt.recent_used(), "an active round's items rest for the next")
        h2 = run(station["system3_direct_banter"](**ctx(bank=True, dj={"host_name": "Caine", "cohost_name": "Skip"})))
        self.assertTrue(h2.conv["inputs"]["recent_items"], "the next round is handed what the last one used")
        aired = "the raccoon drove the van straight through the car wash and waved at the whole town"
        rt.observe_ledger(7, "sid", [{"line_id": "x1", "who": "dj", "text": aired}])
        script = "\n".join("%s: %s" % (t["speaker"], aired if i == 1 else "Something new entirely, said once only here.")
                           for i, t in enumerate(h1.conv["turns"]))
        self.assertTrue(rt.repair_wanted(h1, script) or h1.conv.get("repair_roll", {}).get("repair") is False)
        settle()
        got = rt.store.conversation(h1.id)
        self.assertTrue(any(e.get("family") == "REPEAT" for e in got.get("observations_air") or []))


if __name__ == "__main__":
    unittest.main()

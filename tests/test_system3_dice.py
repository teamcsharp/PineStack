"""[s3-dice-door] The station's own rolls are System 3's: every `random() < p`
and `random.choice(...)` a station road makes on the air's behalf is a row on
the desk (STATION1 odds, POOLS1 options), drawn by System 3's dice, recorded
on the round it shaped and in the Audit feed."""
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


class DiceDoorTests(unittest.TestCase):
    def boot(self, mode="active"):
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
        r = self.client.post("/api/system3/settings", json={"mode": mode, "test_seed": "dice"},
                             headers={"Authorization": "Bearer k"})
        self.assertEqual(r.status_code, 200, r.text)
        system3_runtime._S3_ROLLS.set(None)
        return self.rt

    def flush(self):
        return system3_runtime._STORE_POOL.submit(self.rt.dice_flush).result(timeout=10)

    def put(self, table):
        r = self.client.put("/api/system3/tables/" + table["id"], json=table, headers={"Authorization": "Bearer k"})
        self.assertEqual(r.status_code, 200, r.text)

    def table(self, tid):
        return copy.deepcopy(next(t for t in self.rt.config["tables"] if t["id"] == tid))

    def test_system3_off_means_the_stations_own_random(self):
        rt = self.boot(mode="off")
        self.assertIsNone(self.station["system3_chance"]("call.prize", 0.3, "a prize"))
        self.assertIsNone(self.station["system3_pool"]("call.states", ["calm"], "states"))
        self.assertIsNone(self.station["system3_pick"]("call.states", ["calm"]))

    def test_a_roll_becomes_a_desk_row_and_the_desk_odds_are_rolled(self):
        rt = self.boot()
        got = self.station["system3_chance"]("call.prize", 0.3, "the caller wins something")
        self.assertIn(got, (True, False))
        self.assertEqual(rt.station_view()[-1]["key"], "call.prize")
        self.assertEqual(self.flush(), ["call.prize"])
        st = self.table("STATION1")
        row = st["categories"][0]["items"][0]
        self.assertEqual((st["categories"][0]["id"], row["id"], row["odds"]), ("call", "call.prize", 0.3))
        self.assertIn("station rolls tabled", rt.store.config_versions()[0]["note"])
        row["odds"] = 1.0
        self.put(st)
        self.assertTrue(all(self.station["system3_chance"]("call.prize", 0.0) for _ in range(20)))
        row["odds"] = 0.0
        self.put(st)
        self.assertFalse(any(self.station["system3_chance"]("call.prize", 1.0) for _ in range(20)))
        self.assertEqual(self.flush(), [], "a row is added once")

    def test_a_row_that_follows_a_desk_dial_rolls_at_the_dial(self):
        rt = self.boot()
        self.station["system3_chance"]("call.insanity", 0.45, "the speakerbox obsession", dial="caller_insanity")
        self.flush()
        st = self.table("STATION1")
        row = st["categories"][0]["items"][0]
        self.assertEqual(row["dial"], "caller_insanity")
        row["odds"] = 0.0                          # ignored: the dial is the odds
        self.put(st)
        self.assertTrue(all(self.station["system3_chance"]("call.insanity", 1.0, dial="caller_insanity") for _ in range(10)))
        self.assertIn("follows the desk dial", rt.station_view()[-1]["why"])

    def test_a_pool_is_the_stations_list_until_the_desk_edits_it(self):
        rt = self.boot()
        states = ["calm", "furious", "drunk"]
        self.assertEqual(self.station["system3_pool"]("call.states", states, "caller state"), states)
        self.flush()
        pl = self.table("POOLS1")
        cat = pl["categories"][0]
        self.assertEqual((cat["id"], [i["text"] for i in cat["items"]]), ("call.states", states))
        cat["items"][1]["enabled"] = False
        cat["items"].append({"id": "o9", "label": "whispering", "text": "whispering", "weight": 1.0})
        self.put(pl)
        self.assertEqual(self.station["system3_pool"]("call.states", states), ["calm", "drunk", "whispering"])

    def test_a_pick_honours_the_desk_weights(self):
        rt = self.boot()
        self.station["system3_pool"]("call.prizes", ["a mug", "a sweater"], "prizes")
        self.flush()
        pl = self.table("POOLS1")
        next(i for i in pl["categories"][0]["items"] if i["text"] == "a mug")["weight"] = 0.0
        self.put(pl)
        picks = {self.station["system3_pick"]("call.prizes", ["a mug", "a sweater"]) for _ in range(30)}
        self.assertEqual(picks, {1})
        self.assertEqual(rt.station_view()[-1]["picked"], "a sweater")

    def test_the_roads_rolls_are_the_rounds_first_events_and_replay_skips_them(self):
        rt = self.boot()

        async def road():
            self.station["system3_chance"]("call.tickets", 0.35, "arena tickets")
            self.station["system3_pick"]("call.weather", ["flustered", "exhausted"])
            return await self.station["system3_direct_banter"](**ctx(bank=False, dj={"host_name": "Caine", "cohost_name": "Skip"}))
        h = asyncio.new_event_loop().run_until_complete(road())
        fam = [e["family"] for e in h.conv["decision_events"]]
        self.assertEqual(fam[:2], ["STATION", "STATION"])
        self.assertEqual({e["meta"]["key"] for e in h.conv["decision_events"][:2]}, {"call.tickets", "call.weather"})
        self.assertTrue(system3.replay(json.loads(json.dumps(h.conv)), rt.config)["ok"])
        # a second round on the same road does not take them in twice
        h2 = asyncio.new_event_loop().run_until_complete(
            self.station["system3_direct_banter"](**ctx(bank=False, dj={"host_name": "Caine", "cohost_name": "Skip"})))
        self.assertNotIn("STATION", [e["family"] for e in h2.conv["decision_events"]])
        settle()
        feed = rt.store.events_after(0, 1000)["events"]
        self.assertTrue(any(e.get("family") == "STATION" for e in feed))
        self.assertEqual(self.client.get("/api/system3/station").json()["rolls"][-1]["key"], "call.weather")


if __name__ == "__main__":
    unittest.main()

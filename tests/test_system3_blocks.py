"""[s3-blocks] Every block of a writer prompt is a System 3 node: an obligation
(always sent, recorded, switchable), a roll (a die at its odds or a desk dial),
a tint block (only while the crystal tint is on), or off - and a block no node
claims is a wedge and is stripped. Each prompt's decisions are kept by the
digest of the words sent, for the Prompt tab."""
import asyncio
import hashlib
import tempfile
import unittest

import system3
import system3_tables
import system3_runtime

from test_system3_runtime import FakeStation, ctx, settle
from fastapi import FastAPI
from fastapi.testclient import TestClient


class BlockEngineTests(unittest.TestCase):
    def test_every_kind_is_decided_and_a_wedge_is_stripped(self):
        cfg = system3.default_config()
        got = {d["name"]: d for d in system3.decide_blocks(
            ["persona", "battle", "approach", "made_up_block", "disposition"], cfg, "s1", tint_on=False,
            dial={"personality": 1.0})}
        self.assertTrue(got["persona"]["keep"])
        self.assertEqual(got["persona"]["kind"], "obligation")
        self.assertFalse(got["battle"]["keep"])
        self.assertEqual(got["battle"]["kind"], "tint")
        self.assertFalse(got["approach"]["keep"])
        self.assertEqual(got["made_up_block"]["kind"], "wedge")
        self.assertFalse(got["made_up_block"]["keep"])
        self.assertTrue(got["disposition"]["keep"], "an obligation: its gate is the station's personality roll")
        on = {d["name"]: d for d in system3.decide_blocks(["battle", "crystal"], cfg, "s1", tint_on=True)}
        self.assertTrue(on["battle"]["keep"] and on["crystal"]["keep"])
        cfg2 = dict(cfg, blocks={"disposition": {"kind": "roll", "odds": 1.0, "odds_from": "personality"}})
        never = system3.decide_blocks(["disposition"], cfg2, "s2", dial={"personality": 0.0})[0]
        self.assertFalse(never["keep"], "a roll that follows a dial rolls at the dial")

    def test_the_desk_overrides_a_rule_and_rolls_are_recorded_on_the_round(self):
        cfg = system3.default_config()
        cfg["blocks"] = {"day": {"kind": "off"}, "show_memory": {"kind": "roll", "odds": 0.0}}
        conv = system3.plan_scene({"road": "banter", "seats": ["A", "B"], "turns": 4, "subject": {"topic": "x"}},
                                  cfg, system3.normalise_settings({"mode": "active", "test_seed": "b"}))
        out = system3.decide_blocks(["day", "show_memory", "persona"], cfg, "s", conv=conv)
        self.assertEqual([d["keep"] for d in out], [False, False, True])
        evs = [e for e in conv["decision_events"] if e["family"] == "BLOCK"]
        self.assertEqual([e["selected"]["block"] for e in evs], ["day", "show_memory", "persona"])
        self.assertIsNotNone(evs[1]["rng"])
        self.assertIsNone(evs[0]["rng"])

    def test_the_block_rules_validate(self):
        self.assertEqual(system3.validate_blocks({"day": {"kind": "roll", "odds": 5}})["day"]["odds"], 1.0)
        with self.assertRaises(ValueError):
            system3.validate_blocks({"day": {"kind": "sometimes"}})
        with self.assertRaises(ValueError):
            system3.validate_blocks({"Bad Name": {"kind": "off"}})
        self.assertIn("persona", system3_tables.default_blocks())


class BlockRuntimeTests(unittest.TestCase):
    def boot(self):
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
        self.client.post("/api/system3/settings", json={"mode": "active", "test_seed": "blk"},
                         headers={"Authorization": "Bearer k"})
        return self.rt

    def test_a_prompts_blocks_are_recorded_on_the_round_it_writes_and_found_by_its_words(self):
        rt = self.boot()
        h = asyncio.new_event_loop().run_until_complete(
            self.station["system3_direct_banter"](**ctx(bank=False, dj={"host_name": "Caine", "cohost_name": "Skip"})))
        token = self.station["system3_writing_for"].set(h)
        try:
            out = self.station["system3_blocks"](["persona", "made_up", "sheet"], {"kind": "round"}, False, {})
        finally:
            self.station["system3_writing_for"].reset(token)
        self.assertEqual([d["keep"] for d in out], [True, False, True])
        self.assertEqual(sum(1 for e in h.conv["decision_events"] if e["family"] == "BLOCK"), 3)
        text = "the words actually sent"
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        self.station["system3_note_prompt"](digest, out, {"kind": "round"})
        got = self.client.post("/api/system3/prompt-blocks", json={"text": text}).json()
        self.assertEqual(got["digest"], digest)
        self.assertEqual([b["name"] for b in got["prompt"]["blocks"]], ["persona", "made_up", "sheet"])
        self.assertIn("persona", got["rules"])
        self.assertEqual(rt.metrics["blocks_stripped"], 1)

    def test_the_desk_edits_the_rules_and_off_means_the_station_as_it_was(self):
        rt = self.boot()
        r = self.client.put("/api/system3/config/section/blocks", json={"persona": {"kind": "off"}},
                            headers={"Authorization": "Bearer k"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(self.station["system3_blocks"](["persona"], {}, False, {})[0]["keep"])
        self.assertEqual(self.client.get("/api/system3/config").json()["config"]["blocks"]["persona"]["kind"], "off")
        bad = self.client.put("/api/system3/config/section/blocks", json={"persona": {"kind": "maybe"}},
                              headers={"Authorization": "Bearer k"})
        self.assertEqual(bad.status_code, 400)
        self.client.post("/api/system3/settings", json={"mode": "off"}, headers={"Authorization": "Bearer k"})
        self.assertIsNone(self.station["system3_blocks"](["persona"], {}, False, {}))


if __name__ == "__main__":
    unittest.main()

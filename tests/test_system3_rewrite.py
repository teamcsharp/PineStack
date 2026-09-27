"""[s3-rewrite] The rewrite passes are System 3 rolls: TINT per turn, REPAIR
and ROOM per round - opt-in, on their own streams, bound onto the entry, and
read by the runtime's doors."""
import asyncio
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

import system3
import system3_runtime
try:
    from tests.test_system3 import inputs, plan, settings
    from tests.test_system3_runtime import FakeStation, ctx, settle
except ModuleNotFoundError:  # the container runs the suites with tests/ on the path
    from test_system3 import inputs, plan, settings
    from test_system3_runtime import FakeStation, ctx, settle


def rolled(seed="rw-1", tint_on=True, control=None, **over):
    raw = {"mode": "active", "test_seed": seed}
    if control:
        raw["controls"] = control
    return system3.plan_scene(inputs(rewrite_rolls=True, tint={"wanted": tint_on, "coverage": 82}, **over),
                              system3.default_config(), system3.normalise_settings(raw), conversation_id="rw-" + seed)


class RewriteRollTests(unittest.TestCase):
    def test_nothing_rolls_unless_the_round_opts_in(self):
        conv = plan(turns=8)
        self.assertFalse([e for e in conv["decision_events"] if e["family"] in ("TINT", "REPAIR", "ROOM")])
        self.assertTrue(all(t.get("tint") is None for t in conv["turns"]))

    def test_tint_rolls_every_turn_and_the_round_rolls_repair_and_room_once(self):
        conv = rolled(turns=8)
        fams = [e["family"] for e in conv["decision_events"]]
        self.assertEqual(fams.count("REPAIR"), 1)
        self.assertEqual(fams.count("ROOM"), 1)
        self.assertEqual(fams.count("TINT"), len(conv["turns"]))
        for t in conv["turns"]:
            self.assertIn(t["tint"]["rhyme"], (True, False))
            self.assertTrue(any(d["family"] == "TINT" for d in t["decisions"]))
        self.assertIn(conv["repair_roll"]["repair"], (True, False))
        self.assertIn(conv["room_roll"]["room"], (True, False))
        stamp = system3.turn_stamp(conv, conv["turns"][0])
        self.assertEqual(stamp["tint"]["rhyme"], conv["turns"][0]["tint"]["rhyme"])

    def test_the_rolls_ride_their_own_streams(self):
        a = plan(seed="same-seed", turns=8)
        b = rolled(seed="same-seed", turns=8)
        strip = lambda c: [(e["family"], e["selected"]) for e in c["decision_events"]
                           if e["family"] not in ("TINT", "REPAIR", "ROOM")]
        self.assertEqual(strip(a), strip(b), "the turn trajectory is unchanged by the new rolls")

    def test_the_controls_set_the_odds(self):
        never = rolled(seed="c0", turns=10, control={"tint": 0.0, "repair": 0.0, "room": 0.0})
        self.assertFalse(any(t["tint"]["rhyme"] for t in never["turns"]))
        self.assertFalse(never["repair_roll"]["repair"])
        self.assertFalse(never["room_roll"]["room"])
        always = rolled(seed="c1", turns=10, control={"tint": 1.0, "repair": 1.0, "room": 1.0})
        self.assertTrue(all(t["tint"]["rhyme"] for t in always["turns"]))
        self.assertTrue(always["repair_roll"]["repair"])
        self.assertTrue(always["room_roll"]["room"])

    def test_a_station_with_the_tint_off_says_so_once_and_rolls_no_turn(self):
        conv = rolled(seed="off", tint_on=False, turns=6)
        tints = [e for e in conv["decision_events"] if e["family"] == "TINT"]
        self.assertEqual(len(tints), 1)
        self.assertIs(tints[0]["meta"].get("applies"), False)
        self.assertEqual(tints[0]["turn_id"], "")
        self.assertTrue(all(t.get("tint") is None for t in conv["turns"]))

    def test_the_default_controls_carry_the_three_dials(self):
        for key in ("tint", "repair", "room"):
            self.assertEqual(system3.DEFAULT_CONTROLS[key], 0.5)
            self.assertEqual(system3.normalise_settings({})["controls"][key], 0.5)


class RewriteRuntimeTests(unittest.TestCase):
    def boot(self, tint_wanted=True):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.station = FakeStation(self.tmp.name)
        self.station["dialogue_tint_wanted"] = lambda: tint_wanted
        self.station["crystal_coverage_target"] = lambda: 82
        app = FastAPI()
        system3_runtime.install(app, self.station)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        rt = self.station["_system3"]()
        self.addCleanup(rt.store.close)
        self.addCleanup(settle)
        r = self.client.post("/api/system3/settings", json={"mode": "active", "roads": ["banter"], "test_seed": "rt-rw"},
                             headers={"Authorization": "Bearer k"})
        self.assertEqual(r.status_code, 200, r.text)
        return rt

    def run_(self, coro):
        return asyncio.new_event_loop().run_until_complete(coro)

    def test_the_bind_stamps_the_rolls_and_the_doors_read_them(self):
        rt = self.boot()
        h = self.run_(self.station["system3_direct_banter"](**ctx(lines=6)))
        self.assertTrue(h.active)
        conv = h.conv
        self.assertTrue(all(t.get("tint") for t in conv["turns"]), "every turn rolled TINT")
        script = "\n".join("%s: %s" % (t["speaker"], "Line number %d about the raccoon van." % t["index"]) for t in conv["turns"])
        want = {t["index"] for t in conv["turns"] if t["tint"]["rhyme"]}
        self.assertEqual(rt.tint_turns(h, script), want)
        entry = {"script": script}
        rt.bind_entry(entry, h)
        self.assertEqual(set(entry["system3"]["tint_turns"]), want)
        self.assertEqual(entry["system3"]["repair"], conv["repair_roll"]["repair"])
        self.assertEqual(entry["system3"]["room"], conv["room_roll"]["room"])
        self.assertEqual(rt.tint_turns_entry(entry), want)
        self.assertEqual(rt.room_allowed(entry), conv["room_roll"]["room"])
        self.assertTrue(rt.room_allowed({}), "a round with no roll is the old rules")
        self.assertIsNone(rt.tint_turns_entry({}))
        self.assertEqual(rt.repair_roll(h), conv["repair_roll"]["repair"])
        # the dice reach the air stamp the recording tint reads
        self.assertIn("tint", entry["turn_dice"][str(conv["turns"][0]["script_index"])]["s3"])

    def test_a_round_that_rolled_stands_is_not_sent_back(self):
        rt = self.boot()
        rt.settings["repair"] = True
        h = self.run_(self.station["system3_direct_banter"](**ctx(lines=6, bank=True)))
        self.assertTrue(h.active)
        # a script that ignores the running order entirely: one seat, two turns
        bad = "A: One.\nA: Two."
        h.conv["repair_roll"] = {"repair": False, "event_id": "x"}
        self.assertFalse(rt.repair_wanted(h, bad))
        h.conv["repair_roll"] = {"repair": True, "event_id": "x"}
        self.assertTrue(rt.repair_wanted(h, bad))

    def test_the_tint_state_reaches_the_inputs(self):
        rt = self.boot(tint_wanted=False)
        h = self.run_(self.station["system3_direct_banter"](**ctx(lines=6)))
        tints = [e for e in h.conv["decision_events"] if e["family"] == "TINT"]
        self.assertEqual(len(tints), 1)
        self.assertIs(tints[0]["meta"]["applies"], False)
        self.assertIsNone(rt.tint_turns(h, "A: x.\nB: y."))


if __name__ == "__main__":
    unittest.main()

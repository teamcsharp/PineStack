"""[s3-deadair] The dead-air node (#1571, 2026-10-05).

Run from the repo root:  python3 tests/test_deadair_node_2026_10_05.py
Reads the source the station runs; imports nothing of the station.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")


def body(head: str, stop: str) -> str:
    start = APP.index(head)
    return APP[start:APP.index(stop, start + len(head))]


class DeadAirNodeTest(unittest.TestCase):
    def test_the_six_kinds_the_operator_named(self):
        got = re.search(r"DEADAIR_KINDS = \((.*?)\)", APP, re.S).group(1)
        kinds = set(re.findall(r'"([^"]+)"', got))
        self.assertEqual(kinds, {"quote", "sfx clip", "discussion topic", "conversation redirect",
                                 "response", "banked response"})

    def test_system3_rolls_whether_who_and_what(self):
        ask = body("def s3_dead_air_node(", "\nasync def dead_air_watch(")
        run = body("async def _deadair_run(", "\ndef s3_dead_air_node(")
        self.assertIn('s3_chance("deadair.node", 1.0', ask)
        self.assertIn('s3_choice("deadair.who"', run)
        self.assertIn('s3_choice("deadair.kind", list(DEADAIR_KINDS)', run)     # a desk category: weights, on/off
        self.assertNotIn("random.", ask + run)                                   # nothing here is the station's own dice

    def test_the_rolls_and_the_line_share_one_task(self):
        """The rolls ride the line's stamp only when the same task makes both."""
        ask = body("def s3_dead_air_node(", "\nasync def dead_air_watch(")
        self.assertIn("asyncio.create_task(_deadair_run(", ask)
        self.assertNotIn("s3_choice(", ask)

    def test_the_watchdog_never_waits_on_the_node(self):
        watch = body("async def dead_air_watch(", "\nasync def ")
        at = watch.index("s3_dead_air_node(")
        line = watch[watch.rfind("\n", 0, at) + 1:watch.index("\n", at)]
        self.assertNotIn("await", line)
        handoff = watch.index("_went = await _silence_cupboard_handoff()")
        filler = watch.index('_dead_air_pass("the gap filler")')
        self.assertTrue(handoff < at < filler)          # only when the cupboard gave nothing; the clip covers it

    def test_one_node_at_a_time_with_a_rest(self):
        ask = body("def s3_dead_air_node(", "\nasync def dead_air_watch(")
        self.assertIn("not task.done()", ask)
        self.assertIn("DEADAIR_REST", ask)
        self.assertIn("radio_paused()", ask)

    def test_an_insert_spends_nothing_of_a_conversation(self):
        run = body("async def _deadair_run(", "\ndef s3_dead_air_node(")
        calls = re.findall(r"dj_speak\((.*?)\)\n", run, re.S)
        self.assertEqual(len(calls), 5)
        for call in calls:
            self.assertIn('"aside", None', call)        # a line of its own road, bound to no round
            self.assertIn("sting=False", call)          # and it does not count toward the SFX cadence
        self.assertNotIn("turn_dice", run)
        self.assertNotIn("speak_turns", run)

    def test_the_ledger_carries_the_tally(self):
        route = body("async def api_flow_ledger(", "\n@app.post(\"/api/flow/release\")")
        self.assertIn('"deadair"', route)
        self.assertIn('if k != "task"', route)


class ProducedSpotTest(unittest.TestCase):
    """[s3-produced] System2's produced spot carries a System 3 node (#1474 #1492 #1554 #1563)."""

    @classmethod
    def setUpClass(cls):
        cls.src = (ROOT / "system2_media.py").read_bytes().decode("utf-8").replace("\r\n", "\n")

    def test_the_spot_asks_for_its_node_before_it_is_published(self):
        start = self.src.index("    async def _deliver_produced(")
        deliver = self.src[start:]
        ask = deliver.index("stamp = await self._s3_spot_stamp(take)")
        self.assertLess(ask, deliver.index("h.page_feed_append(clip)"))
        self.assertLess(ask, deliver.index("h._play_on_box("))
        self.assertIn('row["system3"] = stamp', deliver)
        self.assertIn("_s3_line_remember", deliver)

    def test_a_planner_fault_never_holds_the_spot(self):
        start = self.src.index("    async def _s3_spot_stamp(")
        helper = self.src[start:self.src.index("    async def _deliver_produced(")]
        self.assertIn('road="ad_spot"', helper)
        self.assertIn("except Exception", helper)
        self.assertNotIn("raise", helper)
        self.assertEqual(helper.count("return None"), 3)      # no planner, no active node, any fault
        self.assertIn("else None", helper)                      # and a stamp without a conversation


if __name__ == "__main__":
    unittest.main()

"""[match-coalesce] 2026-10-06: the clip matcher rebuilds at most once a quarter hour.

Measured: 161 index rebuilds in three hours (one a minute, 4-123 s of Python each)
held the GIL from the event loop; the endless cycle froze and the API timed out.
"""
import time
import unittest
from unittest import mock

import app


class FakeThread:
    started = []

    def __init__(self, target=None, name="", daemon=False):
        self.target, self.name, self.daemon, self.alive = target, name, daemon, False

    def start(self):
        FakeThread.started.append(self.name)
        self.alive = False

    def is_alive(self):
        return self.alive


class Coalesce(unittest.TestCase):
    def setUp(self):
        FakeThread.started = []

    def _kick(self, built_ago, force=False, timer_slot=None):
        state = {"index": object(), "at": time.time() - built_ago, "building": False, "why": "",
                 "rows": 0, "ms": 0, "stats": {}, "kicks": 0, "picks": 0, "matched": 0, "fell_back": 0}
        slot = timer_slot if timer_slot is not None else [None]
        with mock.patch.object(app, "_sfx_match", object()), \
                mock.patch.object(app, "_SFX_MATCH", state), \
                mock.patch.object(app, "_SFX_MATCH_THREAD", [None]), \
                mock.patch.object(app, "_SFX_MATCH_TIMER", slot), \
                mock.patch.object(app, "Thread", FakeThread):
            got = app.sfx_match_kick(force=force)
        return got, state, slot

    def test_a_kick_inside_the_rest_is_batched_into_one_timer(self):
        slot = [None]
        got, state, slot = self._kick(10, timer_slot=slot)
        try:
            self.assertFalse(got)
            self.assertEqual(state["coalesced"], 1)
            self.assertEqual(FakeThread.started, [], "no rebuild inside the rest")
            self.assertIsNotNone(slot[0])
            self.assertTrue(slot[0].is_alive(), "one daemon timer waits for the rest to end")
            self.assertTrue(slot[0].daemon)
            first = slot[0]
            got2, state2, slot = self._kick(10, timer_slot=slot)
            self.assertFalse(got2)
            self.assertIs(slot[0], first, "a second kick re-uses the pending timer")
        finally:
            if slot[0] is not None:
                slot[0].cancel()

    def test_a_kick_after_the_rest_rebuilds_now(self):
        got, state, slot = self._kick(app.SFX_MATCH_REBUILD_EVERY + 5)
        self.assertTrue(got)
        self.assertEqual(FakeThread.started, ["sfx-match-index"])
        self.assertIsNone(slot[0])
        self.assertEqual(state["kicks"], 1)

    def test_force_rebuilds_inside_the_rest(self):
        got, state, slot = self._kick(10, force=True)
        self.assertTrue(got)
        self.assertEqual(FakeThread.started, ["sfx-match-index"])

    def test_the_rest_is_a_quarter_hour_by_default(self):
        self.assertGreaterEqual(app.SFX_MATCH_REBUILD_EVERY, 600.0)
        self.assertIn("coalesced", app.sfx_match_state())


if __name__ == "__main__":
    unittest.main()

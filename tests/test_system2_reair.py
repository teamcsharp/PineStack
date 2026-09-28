"""[s3-banks-roll] System2's slot is a road that re-airs the bank.

System2 offers every larder entry and shelf row as a candidate, so a banked
round that has already aired can be allocated again. edit_system2_runtime.py
puts that road under the station's re-air rules: a round the re-air gate
retired is not eligible (candidate), and a round that has aired goes out again
only on the roulette (dispatch, app.py bank_reair_pick), stamped a replay.
A host without those functions is untouched.

Runs where test_system2_runtime runs (the container: httpx, fastapi).
"""
import time
import unittest
from unittest import mock

import reair_gate

try:
    from test_system2_runtime import Host, adapter
except Exception as exc:  # noqa: BLE001
    raise unittest.SkipTest("test_system2_runtime's harness is not importable here: %s" % exc)

BROKEN = """A: Whoa, hold on. You're trying to frame this like it's about what we saw or what the studio decided.
B: Exactly! It's a joke, right? I'm just saying it's a joke. No, apparently music is everything.
A: Whoa, hold on. You're trying to frame this like it's about what we saw or what the studio decided.
B: Exactly! It's a joke, right? I'm just saying it's a joke. No, apparently music is everything. 10"""


class System2ReairTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 10000.0
        timer = mock.patch.object(adapter.time, "time", side_effect=lambda: self.now)
        timer.start()
        self.addCleanup(timer.stop)
        self.host = Host(self.temp.name, lambda: self.now)
        self.runtime = adapter.System2Runtime(self.host)
        self.runtime.store.now = lambda: self.now
        self.runtime.config.update(engine="system2", horizon_hours=1)

    def gate(self):
        self.host.bank_reair_refusal = lambda kind, row, cid="": reair_gate.refusal(row, {})

    async def test_a_retired_replay_is_never_offered_to_a_slot_again(self):
        self.gate()
        broken = self.host.add("broken", aired=3, aired_at=self.now - 7200)
        broken["script"] = BROKEN
        got = self.runtime.candidate("news", broken)
        self.assertFalse(got["eligible"])
        self.assertTrue(any("re-air gate" in w for w in got["why"]), got["why"])
        first = self.host.add("first-airing")
        first["script"] = BROKEN
        self.assertTrue(self.runtime.candidate("news", first)["eligible"],
                        "a first airing is not the re-air gate's question")

    async def test_a_replay_goes_out_again_only_on_the_roulette(self):
        self.gate()
        row = self.host.add("replay", aired=1, aired_at=self.now - 7200)
        self.host.bank_reair_pick = mock.Mock(return_value=(None, None))
        self.assertFalse(await self.runtime.dispatch())
        self.host.bank_reair_pick.assert_called_once()
        self.assertIs(self.host.bank_reair_pick.call_args.args[1][0], row)
        self.host._banter_air.assert_not_awaited()
        self.assertTrue(any("only on the roulette" in str(c.args[1])
                            for c in self.host.pipeline_log.call_args_list))

    async def test_a_replay_the_roulette_lets_out_airs_stamped(self):
        self.gate()
        row = self.host.add("replay", aired=1, aired_at=self.now - 7200)
        stamp = {"at": time.time(), "label": "replay, first aired 07:14, airing 2", "airing": 2}
        self.host.bank_reair_pick = mock.Mock(return_value=(row, stamp))
        self.assertTrue(await self.runtime.dispatch())
        self.assertEqual(self.host.aired[0]["_s3_replay"], stamp)

    async def test_a_first_airing_is_never_rolled(self):
        self.gate()
        self.host.add("fresh")
        self.host.bank_reair_pick = mock.Mock(side_effect=AssertionError("rolled for a first airing"))
        self.assertTrue(await self.runtime.dispatch())
        self.assertNotIn("_s3_replay", self.host.aired[0])

    async def test_a_host_without_the_rules_is_untouched(self):
        self.host.add("replay", aired=1, aired_at=self.now - 7200)
        self.assertTrue(await self.runtime.dispatch())
        self.assertNotIn("_s3_replay", self.host.aired[0])


if __name__ == "__main__":
    unittest.main()

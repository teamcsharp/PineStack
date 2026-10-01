"""[boot-dj] 2026-09-30: after a reboot the first thing on air is a banked DJ round.

The operator: "DJs talk right away - the first thing on air is a banked, ready
DJ round, then the music continues. No minutes-long wait for the DJs."

Two faults were measured on the boot of 06:58:37Z. The boot road (resume_radio's
#824 instant open) asked only cover_the_gap, whose 100%-talk ladder reads the
banter larder and then rolls a record - the cupboard was never asked. And the
cupboard's "ready" counted rounds System 3's booth withholds ("incomplete
conversation withheld after repair"), so every rescue and every standing-consumer
walk handed the booth a round it refused.

These tests run the REAL booth (_speak_turns_floorless) on the same fixtures as
s3_binding_withheld(), so the read-ahead and the gate it reads cannot drift."""
import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import app


def _round(turns, *, planned=None, bound=None, lines=None, s3=True, dice_ids=None):
    """A stored conversation in the shape _ready_air_entry hands the booth."""
    script = "\n".join("%s: %s" % (who, text) for who, text in turns)
    n = len(turns)
    bound = list(range(n)) if bound is None else bound
    ids = {str(i): "turn-%d" % i for i in bound}
    dice_ids = ids if dice_ids is None else dice_ids
    entry = {
        "script": script,
        "lines": n if lines is None else lines,
        "prep_kind": "manager",
        "turn_dice": {k: {"s3": {"turn_id": v}} for k, v in dice_ids.items()},
    }
    if s3:
        entry["system3"] = {"mode": "active", "turns": ids,
                            "planned_turns": n if planned is None else planned}
    return entry


LINES = [("A", "The memo from upstairs says the tower lights stay on all night."),
         ("B", "All night? Who is paying for the tower lights, then?"),
         ("A", "Upstairs is, apparently, out of the plant budget."),
         ("B", "Then the ferns are going to have words with upstairs.")]

FIXTURES = {
    "complete": _round(LINES),
    "bound turns short of the plan": _round(LINES, planned=5),
    "limit under the plan": _round(LINES, lines=3),
    "one speaker only": _round([("A", t) for _w, t in LINES]),
    "no System 3 conversation": _round(LINES, s3=False),
    "no bound roulette turns": _round(LINES, dice_ids={"0": "other", "1": "other"}),
    "dropped turn after repair": _round(LINES, bound=[0, 1, 3], planned=4),
    # [s3-coverage] completeness is coverage now: 3 of 4 airs, 3 of 6 is a fragment
    "a fragment of the plan": _round(LINES, bound=[0, 1, 3], planned=6),
}


class _Booth:
    """Runs the real booth with its air side stubbed: a round the System 3 gate
    lets through reaches the operator-forgotten check, which is stubbed to
    withhold, so nothing is ever rendered or published."""

    def __init__(self):
        self.logs = []

    def log(self, kind, text, extra=""):
        self.logs.append((kind, str(text)))

    async def run(self, entry):
        del self.logs[:]
        turns = app.banter_turns(entry["script"])
        await app._speak_turns_floorless(
            turns, None, entry["lines"], round_meta=dict(entry),
            turn_dice=app._turn_dice_map(entry))
        gate = [t for k, t in self.logs if k == "system3" and (
            t.startswith("round withheld without") or
            t.startswith("incomplete conversation withheld"))]
        reached = any(k == "drop" and "operator-forgotten" in t for k, t in self.logs)
        return gate, reached


class BoothGateReadAhead(unittest.IsolatedAsyncioTestCase):
    async def test_the_read_ahead_agrees_with_the_real_booth(self):
        booth = _Booth()
        with (mock.patch.object(app, "_s3_active", return_value=True),
              mock.patch.object(app, "pipeline_log", side_effect=booth.log),
              mock.patch.object(app, "line_forgotten", return_value=True),
              mock.patch.object(app, "modifiers_ride_round", return_value=None),
              mock.patch.object(app, "session_voices",
                                new=mock.AsyncMock(return_value={}))):
            for name, entry in FIXTURES.items():
                with self.subTest(name):
                    gate, reached = await booth.run(entry)
                    why = app.s3_binding_withheld(dict(entry))
                    self.assertEqual(bool(why), bool(gate),
                                     "%s: read-ahead %r, booth %r" % (name, why, gate))
                    if why:
                        self.assertTrue(why.startswith(gate[0]), (why, gate))
                    else:
                        self.assertTrue(reached, "%s passed the gate but the booth "
                                                 "stopped before the end" % name)
        self.assertEqual(app.s3_binding_withheld(dict(FIXTURES["complete"])), "")

    def test_nothing_changes_while_system3_is_not_active(self):
        with mock.patch.object(app, "_s3_active", return_value=False):
            for name, entry in FIXTURES.items():
                self.assertEqual(app.s3_binding_withheld(dict(entry)), "", name)

    def test_the_answer_follows_the_entry_when_it_changes(self):
        entry = dict(FIXTURES["complete"])
        with mock.patch.object(app, "_s3_active", return_value=True):
            self.assertEqual(app.s3_binding_withheld(entry), "")
            entry["lines"] = 2                          # the same dict, cut short
            self.assertIn("incomplete", app.s3_binding_withheld(entry))


class ReadyMeansAirable(unittest.TestCase):
    """dialogue_row_ready - the one zero-work-to-air predicate every road, the
    rescue and the standing consumer read - no longer calls a round ready that
    the booth will withhold."""

    def _ready(self, entry):
        row = {"entry": entry, "at": time.time() - 9000}
        with (mock.patch.object(app, "_s3_active", return_value=True),
              mock.patch.object(app, "_larder_current", return_value=True),
              mock.patch.object(app, "dialogue_tint_ready", return_value=True),
              mock.patch.object(app, "dialogue_audio_ready", return_value=True)):
            return (app.dialogue_row_ready("manager", row),
                    app.dialogue_row_ready_why("manager", row))

    def test_a_complete_round_is_ready(self):
        ready, why = self._ready(dict(FIXTURES["complete"]))
        self.assertTrue(ready)
        self.assertEqual(why, "")

    def test_a_round_the_booth_withholds_is_not_ready_and_says_why(self):
        for name in ("a fragment of the plan", "no bound roulette turns",
                     "no System 3 conversation", "limit under the plan"):
            with self.subTest(name):
                ready, why = self._ready(dict(FIXTURES[name]))
                self.assertFalse(ready)
                self.assertIn("System 3 would withhold it at the booth", why)

    def test_one_turn_short_of_the_plan_still_airs(self):
        """[s3-coverage] 2026-10-01: all-or-nothing withheld nearly every live round
        for one unaligned turn and the DJs went silent."""
        ready, why = self._ready(dict(FIXTURES["dropped turn after repair"]))
        self.assertTrue(ready)
        self.assertEqual(why, "")


class TheBootRoadOpensWithABankedRound(unittest.IsolatedAsyncioTestCase):
    async def _boot(self, rescue_answer):
        order = []
        spawned = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        on = Path(tmp.name) / "radio_on.json"
        on.write_text(json.dumps({"on": True, "station": "all"}))

        async def rescue(quiet, why=""):
            order.append(("rescue", quiet, why))
            return rescue_answer

        async def cover(blocked="dj", why=""):
            order.append(("cover", blocked, why))
            return True

        with (mock.patch.object(app, "RADIO_ON_PATH", on),
              mock.patch.object(app.asyncio, "sleep",
                                new=mock.AsyncMock(return_value=None)),
              mock.patch.object(app, "box_worth_healing", return_value=False),
              mock.patch.object(app, "dj_best_station", side_effect=lambda s="": s),
              mock.patch.object(app, "dj_start",
                                side_effect=lambda s: order.append(("dj_start", s))),
              mock.patch.object(app, "fire_and_forget", side_effect=spawned.append),
              mock.patch.object(app, "dead_air_rescue", side_effect=rescue),
              mock.patch.object(app, "cover_the_gap", side_effect=cover)):
            await app.resume_radio()
            for coro in spawned:
                await coro
        return order

    async def test_the_first_answer_is_the_cupboard_after_the_station_is_on(self):
        order = await self._boot("manager")
        self.assertEqual(order[0], ("dj_start", "all"))
        self.assertEqual(order[1][0], "rescue")
        self.assertEqual(order[1][1], 0.0)
        self.assertIn("restart", order[1][2])
        self.assertNotIn("cover", [o[0] for o in order],
                         "a banked round aired - the record roll must not follow it")

    async def test_an_empty_cupboard_falls_back_to_the_old_cover(self):
        order = await self._boot("")
        self.assertEqual([o[0] for o in order], ["dj_start", "rescue", "cover"])
        self.assertEqual(order[2][2], "the station is respinning (#824)")


class NoRebootReairsTheLastOne(unittest.IsolatedAsyncioTestCase):
    """A restart loop must not open every boot with the same round."""

    async def test_the_boot_rescue_keeps_the_repeat_check(self):
        calls = []

        async def shelf_air(kind, track=None, **kw):
            calls.append((kind, kw))
            return ["a line"]

        with (mock.patch.object(app, "dead_air_stock", return_value={"manager": 1}),
              mock.patch.object(app, "schedule_take", return_value={}),
              mock.patch.object(app, "_ready_shelf_air", side_effect=shelf_air),
              mock.patch.object(app, "radio_paused", return_value=False),
              mock.patch.object(app, "repair_note") as note,
              mock.patch.dict(app.__dict__, {"system3_injected_node": mock.Mock()}),
              mock.patch.object(app, "pipeline_log"),
              mock.patch.dict(app._RADIO, {"on": True}),
              mock.patch.object(app, "_RESCUE_AT", [0.0])):
            got = await app.dead_air_rescue(0.0, "the station came back on air after a restart")
        self.assertEqual(got, "manager")
        self.assertEqual(calls[0][0], "manager")
        self.assertTrue(calls[0][1].get("rescue"))
        # no `force`: the booth's repeat check stands (despite_repeats False)
        self.assertFalse(calls[0][1].get("force"))
        self.assertIn("after a restart", note.call_args[0][0])

    def test_a_round_the_last_boot_aired_is_not_offered_again(self):
        if not app.norepeat_on():
            self.skipTest("the 24 h no-repeat book is switched off")
        entry = dict(FIXTURES["complete"])
        row = {"entry": entry, "at": time.time() - 9000,
               "aired_at": time.time() - 60, "aired": 1}
        # heard is heard: not a first airing any more ...
        self.assertFalse(app.row_unaired(row))
        # ... and as a replay the re-air gate's 24 h leg strikes it before any roll
        with mock.patch.object(app, "norepeat_select_refuse"):
            why = app.norepeat_round_refusal("manager", row)
            self.assertIn("no repeats inside a day", why)
            with mock.patch.object(app, "_bank_reair_refusal_gate", return_value=""):
                picked, stamp = app.bank_reair_pick("manager", [row], "a reboot")
        self.assertIsNone(picked)
        self.assertIsNone(stamp)


if __name__ == "__main__":
    unittest.main()

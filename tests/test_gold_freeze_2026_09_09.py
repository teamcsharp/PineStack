"""#1157, 2026-09-09: a rhymed line is not deleted, and the bank fills the air.

The operator: "i dont want lines getting removed until the dialogue is able
to be pumped without relenting and the dead air is minimal. The goal is to
have activity and dialogue back to back to back."

Three audits found the same shape from different directions:

 - the retirement desk had never recorded ANYTHING - no ledger file, zeros on
   /api/retire - while the caller shelf fell 16 -> 13 -> 10 -> 9. Both facts
   were true at once because `resort_may_drop` returned False for a rhymed
   row BEFORE it reached `retire_may`, so the only shelf-side road to the
   desk was unreachable for exactly the work the desk exists to protect;
   meanwhile six other roads deleted rhymed work without ever asking it.
 - the keep was 96 HOURS. A keep expressed as a date is a day on which every
   shield in the station switches off at once - here 2026-09-12.
 - the render engine is SLOWER than speech: fitted over 600 renders,
   render = 2.97 + 1.05 x audio. Continuous talk cannot be live-rendered at
   any budget. Only banked audio can fill a hole, and `cover_the_gap`
   returned False whenever the floor was held - which is exactly when the
   holes are.
"""
import time
import unittest
from unittest import mock

import app
import crystal_prompts


def _rhymed_row(kind="caller", text="I spit it legit and the bit of it fits"):
    """A row the station would call rhymed: a tinted script that IS the script."""
    entry = {"script": text, "script_tinted": text, "at": time.time()}
    return {"at": time.time(), "entry": entry, "text": text,
            "key": "k-%s" % abs(hash(text)) , "kind": kind}


class TheKeepDoesNotExpire(unittest.TestCase):
    def test_a_kind_keeps_rhymed_work_for_good_by_default(self):
        # News still dies with its stories; everything else is the operator's.
        self.assertLess(float(app.retire_rule_default("banter")["keep_hours"]), 0)
        self.assertLess(float(app.retire_rule_default("caller")["keep_hours"]), 0)
        self.assertEqual(float(app.retire_rule_default("news")["keep_hours"]), 0.0)

    def test_forever_overrides_an_hours_stamp_already_on_the_row(self):
        """The four days of rounds stamped before the freeze are covered too."""
        row = _rhymed_row("banter")
        row["keep_until"] = time.time() + 3600.0        # an old 96-hour stamp
        with mock.patch.object(app, "retire_rule",
                               return_value={"ask": "tinted", "keep_hours": -1.0,
                                             "innings": 12}):
            got = app.tinted_keep_until("banter", row)
        self.assertEqual(got, app.KEEP_FOREVER_AT)
        self.assertEqual(row["keep_until"], app.KEEP_FOREVER_AT)
        self.assertEqual(row["entry"]["keep_until"], app.KEEP_FOREVER_AT)

    def test_an_hours_rule_still_expires(self):
        row = _rhymed_row("banter")
        soon = time.time() + 60.0
        row["keep_until"] = soon
        with mock.patch.object(app, "retire_rule",
                               return_value={"ask": "tinted", "keep_hours": 96.0,
                                             "innings": 12}):
            self.assertEqual(app.tinted_keep_until("banter", row), soon)

    def test_a_plain_row_is_not_kept_by_a_forever_rule(self):
        plain = {"at": time.time(), "entry": {"script": "just words"}}
        with mock.patch.object(app, "retire_rule",
                               return_value={"ask": "tinted", "keep_hours": -1.0,
                                             "innings": 12}), \
             mock.patch.object(app, "dialogue_tint_required", return_value=True), \
             mock.patch.object(app, "dialogue_tint_ready", return_value=False):
            self.assertEqual(app.tinted_keep_until("banter", plain), 0.0)


class TheGoldLock(unittest.TestCase):
    def test_a_rhymed_row_is_locked_until_the_operator_says_remove(self):
        row = _rhymed_row("caller")
        with mock.patch.object(app, "_retire_load"), \
             mock.patch.dict(app._RETIRE, {"ledger": {}}, clear=False):
            self.assertTrue(app.gold_locked("caller", row))

    def test_an_explicit_remove_releases_it(self):
        row = _rhymed_row("caller")
        rid = app.retire_id("caller", row)
        with mock.patch.object(app, "_retire_load"), \
             mock.patch.dict(app._RETIRE,
                             {"ledger": {rid: {"state": "remove"}}}, clear=False):
            self.assertFalse(app.gold_locked("caller", row))

    def test_a_plain_row_is_never_locked(self):
        plain = {"at": time.time(), "entry": {"script": "just words"}}
        self.assertFalse(app.gold_locked("caller", plain))

    def test_a_fault_never_deletes_rhymed_work(self):
        row = _rhymed_row("caller")
        with mock.patch.object(app, "retire_id", side_effect=RuntimeError("boom")):
            self.assertTrue(app.gold_locked("caller", row))


class TheShieldTellsTheDesk(unittest.TestCase):
    """resort_may_drop returned False flat, so `remove` was ignored and
    retire_may below it was unreachable for every rhymed row."""

    def test_a_locked_rhymed_row_is_still_held(self):
        row = _rhymed_row("gallery")
        row["aired_at"] = time.time() - 99999.0
        row["aired"] = 3
        with mock.patch.object(app, "tinted_kept", return_value=True), \
             mock.patch.object(app, "resort_keys", return_value=set()), \
             mock.patch.object(app, "gold_locked", return_value=True):
            self.assertFalse(app.resort_may_drop("gallery", row, set()))

    def test_the_operators_remove_now_gets_through_the_keep(self):
        row = _rhymed_row("gallery")
        row["aired_at"] = time.time() - 99999.0
        row["aired"] = 3
        with mock.patch.object(app, "tinted_kept", return_value=True), \
             mock.patch.object(app, "resort_keys", return_value=set()), \
             mock.patch.object(app, "gold_locked", return_value=False):
            self.assertTrue(app.resort_may_drop("gallery", row, set()))


class TheCallerShelfStopsBurningRhymedCalls(unittest.TestCase):
    """Every rhymed call the station ever aired left the shelf at this line,
    and the re-air queue built for it in #1033 was dead code in consequence -
    no caller row could ever carry aired_at."""

    def test_a_rhymed_call_is_stamped_and_kept_not_deleted(self):
        rows = [_rhymed_row("caller")]
        row = rows[0]
        with mock.patch.object(app, "gold_locked", return_value=True), \
             mock.patch.object(app, "stock_expires_at", return_value=0.0):
            # The branch under test, executed as shelf_take runs it.
            row["taken_at"] = time.time()
            if app.gold_locked("caller", row):
                row["aired_at"] = time.time()
                row["aired"] = int(row.get("aired") or 0) + 1
                row["expires_at"] = app.stock_expires_at("caller", row)
                rows[:] = ([r for r in rows if r is not row] + [row])
            else:
                rows[:] = [r for r in rows if r is not row]
        self.assertEqual(len(rows), 1)
        self.assertFalse(app.row_unaired(row))      # no longer fresh stock
        self.assertEqual(row["aired"], 1)

    def test_the_live_road_keeps_it(self):
        """Through shelf_take itself, not a re-enactment."""
        row = _rhymed_row("caller")
        shelf = {"caller": [row]}
        with mock.patch.dict(app._SHELF, shelf, clear=True), \
             mock.patch.object(app, "gold_locked", return_value=True), \
             mock.patch.object(app, "stock_expires_at", return_value=0.0), \
             mock.patch.object(app, "dialogue_row_ready", return_value=True), \
             mock.patch.object(app, "dialogue_row_viable", return_value=True), \
             mock.patch.object(app, "shelf_cast_stale", return_value=False), \
             mock.patch.object(app, "_larder_current", return_value=True), \
             mock.patch.object(app, "pantry_get", return_value={"path": "x.wav"}), \
             mock.patch.object(app, "resort_keys", return_value=set()), \
             mock.patch.object(app, "alt_took"), \
             mock.patch.object(app, "alt_shelf_trim"):
            got = app.shelf_take("caller")
            left = list(app._SHELF.get("caller") or [])   # before patch.dict restores
        self.assertIsNotNone(got)
        self.assertEqual(len(left), 1,
                         "the rhymed call must survive its own dispatch")
        self.assertFalse(app.row_unaired(left[0]),
                         "and it must not still read as fresh stock")


class TheTrimSparesRhymedWork(unittest.TestCase):
    def test_a_non_viable_rhymed_row_is_not_evicted_first(self):
        """The 'rejected' branch runs ABOVE the #1091 pin sweep and returns
        before it, so a rhymed row whose contract moved was deleted here
        ahead of every plain row, and the desk was never told."""
        rows = [_rhymed_row("gallery") for _ in range(6)]
        with mock.patch.object(app, "shelf_cap", return_value=2), \
             mock.patch.object(app, "dialogue_row_viable", return_value=False), \
             mock.patch.object(app, "gold_locked", return_value=True), \
             mock.patch.object(app, "alt_pin_map", return_value={"ids": set()}), \
             mock.patch.object(app, "resort_keys", return_value=set()), \
             mock.patch.object(app, "resort_may_drop", return_value=False), \
             mock.patch.object(app, "retire_forced") as forced:
            app.alt_shelf_trim("gallery", rows)
        self.assertEqual(len(rows), 4, "the hard ceiling (cap*2) still bounds it")
        self.assertTrue(forced.called, "and what it does take is written down")

    def test_a_plain_non_viable_row_is_still_evicted(self):
        """goldkeep's rule 7: rhymed-or-swept is the point of the gate."""
        rows = [_rhymed_row("gallery") for _ in range(6)]
        with mock.patch.object(app, "shelf_cap", return_value=2), \
             mock.patch.object(app, "dialogue_row_viable", return_value=False), \
             mock.patch.object(app, "gold_locked", return_value=False), \
             mock.patch.object(app, "alt_pin_map", return_value={"ids": set()}), \
             mock.patch.object(app, "resort_keys", return_value=set()), \
             mock.patch.object(app, "resort_may_drop", return_value=False):
            app.alt_shelf_trim("gallery", rows)
        self.assertEqual(len(rows), 2)


class TheBankSpendsAudioNeverTheLine(unittest.TestCase):
    """`del rows[:-GOLD_MAX]` was a silent FIFO on rhymed lines."""

    def setUp(self):
        self._rows = [
            {"key": "a", "text": "never heard", "path": "a.wav", "fired": 0, "at": 1.0},
            {"key": "b", "text": "out ten times", "path": "b.wav", "fired": 10, "at": 2.0},
            {"key": "c", "text": "out twice", "path": "c.wav", "fired": 2, "at": 3.0},
        ]

    def test_the_most_fired_take_goes_and_every_line_stays(self):
        with mock.patch.object(app, "_gold_rows", return_value=self._rows), \
             mock.patch.object(app, "GOLD_MAX", 2):
            app.gold_trim()
        self.assertEqual(len(self._rows), 3, "no bar's words are ever deleted")
        by = {r["key"]: r for r in self._rows}
        self.assertEqual(by["b"]["path"], "", "the ten-times bar gives its seconds back")
        self.assertEqual(by["a"]["path"], "a.wav", "the unheard bar keeps its take")
        self.assertEqual(by["c"]["path"], "c.wav")

    def test_under_the_cap_nothing_is_touched(self):
        with mock.patch.object(app, "_gold_rows", return_value=self._rows), \
             mock.patch.object(app, "GOLD_MAX", 50):
            app.gold_trim()
        self.assertTrue(all(r["path"] for r in self._rows))


class TheAirIsPumped(unittest.TestCase):
    def test_preparation_gets_more_than_one_booth(self):
        """prep_limit is capacity - 2; at ENGINE_BUDGET 3 the whole station
        banked audio on ONE slot and 76 of 87 prepared rounds held none."""
        self.assertGreaterEqual(app.ENGINE_BUDGET, 5)
        with mock.patch.object(app, "radio_paused", return_value=False):
            self.assertGreaterEqual(app.recording_booths()["prep_limit"], 3)

    def test_the_ten_second_rule_is_detectable_inside_itself(self):
        # detection + the 2s tick + the announce must fit inside ten.
        self.assertLessEqual(app.TALK_INCESSANT_QUIET_MOST
                             + app.TALK_INCESSANT_WATCH_TICK, 8.0)

    def test_a_held_floor_is_not_a_talking_mouth(self):
        """cover_the_gap returned False whenever the floor was held, which is
        exactly when the holes are - the floor is held across a render."""
        import asyncio
        calls = {}

        async def _gold(why="", floorless=False):
            calls["why"], calls["floorless"] = why, floorless
            return "bar"

        app._COVER_AT[0] = 0.0
        with mock.patch.object(app, "_SPEAKING", [False]), \
             mock.patch.object(app, "_floor_busy", return_value=True), \
             mock.patch.object(app, "talk_is_incessant", return_value=True), \
             mock.patch.object(app, "talk_quiet_for", return_value=9.0), \
             mock.patch.object(app, "gold_fill_gap", _gold):
            went = asyncio.run(app.cover_the_gap("dj", "the floor is held"))
        self.assertTrue(went, "the bank must speak into a held floor")
        self.assertTrue(calls.get("floorless"),
                        "and it must not try to take the floor to do it")

    def test_a_beat_between_phrases_is_not_a_hole(self):
        import asyncio
        app._COVER_AT[0] = 0.0
        with mock.patch.object(app, "_SPEAKING", [False]), \
             mock.patch.object(app, "_floor_busy", return_value=True), \
             mock.patch.object(app, "talk_is_incessant", return_value=True), \
             mock.patch.object(app, "talk_quiet_for", return_value=0.5), \
             mock.patch.object(app, "gold_fill_gap") as gold:
            went = asyncio.run(app.cover_the_gap("dj", ""))
        self.assertFalse(went)
        self.assertFalse(gold.called, "half a second is a breath, not dead air")


class TheCrystalsRegisterReachesTheMouth(unittest.TestCase):
    """Measured: across 199 tint turns the deep model proposed a swear ZERO
    times - never refused (no stop list in the station holds one), never
    written, because _register only ever spoke to the printed Gazette."""

    def test_a_spoken_turn_now_gets_a_register_clause(self):
        got = crystal_prompts._register("dialogue")
        self.assertIn("Register:", got)
        self.assertIn("profanity", got.lower())
        self.assertIn("late-night", got.lower())

    def test_the_line_is_drawn_at_a_person_not_at_a_coarse_word(self):
        got = crystal_prompts._register("dialogue").lower()
        for aimed in ("race", "sex", "religion", "cruelty"):
            self.assertIn(aimed, got)

    def test_the_gazette_keeps_its_own_printed_register(self):
        paper = crystal_prompts._register("paper")
        self.assertIn("PRINTED newspaper paragraph", paper)
        self.assertNotIn("profanity", paper.lower())

    def test_the_register_reaches_the_frame_a_spoken_turn_is_built_from(self):
        frame = crystal_prompts._frame("a style world", [], 0.9, "dialogue", "")
        self.assertIn("Register:", frame)
        self.assertIn("swear", frame.lower())


if __name__ == "__main__":
    unittest.main()

"""2026-09-09: the craft the tint asks for, and the ONE revision that follows.

The operator: "i need the system that tints it to give it dense internal
rhymes, multisyllabic chains, off-kilter imagery, technical or literary
vocabulary, and metaphorical leaps. Also, give it a revision loop. Tell it to
rewrite once to replace any simple or predictable rhymes with more unexpected
phrasing."

What is proved here: the craft reaches the prompt every road shares; the
revision is exactly one ask; it never costs a line that already passed; and it
stands down before the air does. Every model response is replaced.
"""
import unittest
from contextlib import ExitStack
from unittest import mock

import app
from crystal_prompts import (CLICHE_PAIRS, PROMPT_VERSION, cliche_pairs_text,
                            revision_prompt, turn_prompt)


class CraftInstructionTests(unittest.TestCase):
    SOURCE = "Mara cannot return the twelve copper plates before midnight."
    WORLD = "Dry comic images and dense internal rhyme."
    CHUNKS = [{"file": "style.txt", "text": "Operation meets calibration."}]

    def prompt(self, kind="banter"):
        return turn_prompt(self.SOURCE, self.WORLD, self.CHUNKS, .88, kind)

    def test_the_craft_asks_for_what_the_operator_asked_for(self):
        text = self.prompt()
        for demanded in ("INSIDE THE BAR, NOT ONLY AT ITS END",
                         "more than one syllable",
                         "SLANT BEFORE EXACT",
                         "web of near rhyme",
                         "OFF-KILTER IMAGERY, TECHNICAL AND LITERARY",
                         "METAPHOR AND ALLEGORY",
                         # 2026-09-09: the operator asked for the wordplay to
                         # be more robust, so it is its own demand with the
                         # devices named and a quota, not one clause among five.
                         "WORDPLAY - AT LEAST ONE TURN EVERY TWO BARS",
                         "THE PIVOT (double entendre)",
                         "THE RE-READ",
                         "THE SAME WORD TWICE, TWO SENSES",
                         "THE DEAD IDIOM",
                         "THE NEAR-HOMOPHONE PIVOT",
                         "second sense must be TRUE of the conversation",
                         "CADENCE THAT SOUNDS LIKE TALK",
                         "nursery-rhyme metre"):
            self.assertIn(demanded, text, demanded)
        # The craft never buys permission to change the claim.
        self.assertIn("unexpected WORDING", text)

    def test_the_tired_pairs_are_named_not_described(self):
        text = self.prompt()
        self.assertIn(cliche_pairs_text(), text)
        for one, other in CLICHE_PAIRS:
            self.assertIn(one + "/" + other, text)
        for pair in ("time/mind", "fire/higher", "real/feel", "day/way"):
            self.assertIn(pair, text)

    def test_the_craft_rides_the_cacheable_prefix_on_every_road(self):
        """#1081: the frame is one prefix across roads, so the craft must sit
        inside it rather than being appended per line."""
        for kind in ("", "banter", "caller", "gallery", "paper"):
            text = turn_prompt(self.SOURCE, self.WORLD, self.CHUNKS, .88, kind)
            self.assertLess(text.index("6. THE CRAFT"), text.index("Road: "), kind)

    def test_the_prompt_version_moved_with_the_words(self):
        self.assertGreaterEqual(PROMPT_VERSION, 6)


class RevisionPromptTests(unittest.TestCase):
    SOURCE = "Mara cannot return the twelve copper plates before midnight."
    BAR = "Mara can't hand back twelve copper plates tonight / the ledger keeps its light."

    def test_the_revision_edits_the_accepted_bar_and_names_its_four_moves(self):
        text = revision_prompt(self.SOURCE, self.BAR, "world", [{"text": "sample"}], .88, "banter")
        self.assertIn("ACCEPTED BAR", text)
        self.assertIn(self.BAR, text)
        self.assertIn("THE ONE REVISION", text)
        self.assertIn("the only one you get", text)
        # 2026-09-09 (#1089): the operator asked for an ANTI-LAZINESS PASS
        # in those words - inspect every rhyme, hunt the one-syllable
        # perfect couplet first, and give the flattest literal phrase a
        # second sense.
        self.assertIn("THE ANTI-LAZINESS PASS", text)
        self.assertIn("INSPECT EVERY RHYME IN THE BAR", text)
        self.assertIn("one-syllable PERFECT couplets", text)
        self.assertIn("give it a second sense", text)
        self.assertIn("Replace generic words", text)
        self.assertIn("Thicken the rhyme INSIDE a bar", text)
        # It is an edit, not a fresh attempt: the source contract still rules
        # and the bar is explicitly not offered as a rejected candidate.
        self.assertIn("SOURCE CONTRACT:", text)
        self.assertNotIn("REPAIR EVIDENCE", text)
        self.assertIn("6. THE CRAFT", text)

    def test_a_revision_needs_both_the_source_and_the_bar(self):
        with self.assertRaises(ValueError):
            revision_prompt(self.SOURCE, "  ", "world", [], .88, "banter")
        with self.assertRaises(ValueError):
            revision_prompt("", self.BAR, "world", [], .88, "banter")


class RevisionGateTests(unittest.TestCase):
    """#1063/#1064: the tint yields to the air, and a polish yields first."""

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.settings = {**app.DEFAULT_DJ, "crystal_revision": "deep"}
        self.jobs = {"jobs": []}
        for name, value in {
                "dj_settings": mock.Mock(return_value=self.settings),
                "tint_budget_left": mock.Mock(return_value=300.0),
                "tint_budget": mock.Mock(return_value=600.0),
                "prepared_seconds": mock.Mock(return_value=3600.0),
                "tint_should_stop": mock.Mock(return_value=""),
                "writing_room_state": mock.Mock(return_value=self.jobs)}.items():
            self.stack.enter_context(mock.patch.object(app, name, value))

    def test_the_deep_roads_run_it_and_the_rest_do_not(self):
        self.assertEqual(app.crystal_revision_skip("banter"), "")
        self.assertIn("deep roads only", app.crystal_revision_skip("news"))
        self.settings["crystal_revision"] = "all"
        self.assertEqual(app.crystal_revision_skip("news"), "")

    def test_the_switch_turns_it_off_entirely(self):
        self.settings["crystal_revision"] = "off"
        self.assertIn("off", app.crystal_revision_skip("banter"))

    def test_an_unreadable_setting_reads_as_the_default_not_as_all(self):
        self.settings["crystal_revision"] = "yes please"
        self.assertEqual(app.crystal_revision_mode(), app.DEFAULT_DJ["crystal_revision"])
        self.assertIn("deep roads only", app.crystal_revision_skip("news"))

    def test_a_polish_pays_for_its_own_model_time_even_under_the_hold(self):
        """tint_pressure() exempts the budget while crystal_tint_hold is on,
        on the #1064 grounds that under the hold the rewrite IS the show. A
        revision of an accepted bar is never the show, so it is asked here
        directly rather than through that exemption."""
        app.tint_budget_left.return_value = 0.0
        self.assertIn("share of the hour", app.crystal_revision_skip("banter"))

    def test_it_stands_down_for_fresh_rounds_the_operator_and_one_waiter(self):
        with mock.patch.object(app, "_LARDER_WRITING", [True]):
            app.prepared_seconds.return_value = app.TINT_FAMINE_SECONDS - 1
            self.assertIn("fresh rounds first", app.crystal_revision_skip("banter"))
        app.prepared_seconds.return_value = 3600.0
        app.tint_should_stop.return_value = "a forced interjection"
        self.assertEqual(app.crystal_revision_skip("banter"), "a forced interjection")
        app.tint_should_stop.return_value = ""
        # Legacy repair waits for two waiters; a polish waits for one.
        self.jobs["jobs"] = [{"state": "waiting", "purpose": "station:tint turn"}]
        self.assertIn("1 waiting", app.crystal_revision_skip("banter"))


class RevisionPassTests(unittest.IsolatedAsyncioTestCase):
    SOURCE = "Mara cannot return the twelve copper plates before midnight."
    RAW_GOOD = "Mara cannot return twelve copper plates before midnight / the wait is watertight."
    RAW_BETTER = "Mara cannot return twelve copper plates before midnight / the ledger's dolomite."
    RAW_WORSE = "Somebody sold some gold plates around noon."

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.settings = {**app.DEFAULT_DJ, "reply_max_chars": 1000,
                         "crystal_revision": "deep"}
        self.skip = [""]
        self.flow = mock.Mock()
        self.notes = []
        values = {
            "dj_settings": mock.Mock(return_value=self.settings),
            "crystal_force": mock.Mock(return_value=.88),
            "crystal_operator_refinement": mock.Mock(return_value=""),
            "crystal_active": mock.Mock(return_value=[{"name": "fixture", "on": True}]),
            "crystal_prompt_contract": mock.Mock(side_effect=lambda text: "Contract: " + text),
            "_crystal_vocab": mock.Mock(return_value=frozenset()),
            "tint_model_for": mock.Mock(return_value="fixture-model"),
            "tint_should_stop": mock.Mock(return_value=""),
            "line_review_permits": mock.Mock(return_value=False),
            "line_review_policy": mock.Mock(return_value={"enabled": True}),
            "line_review_capture": mock.Mock(return_value={"id": "fixture", "event_seq": 1}),
            "crystal_revision_skip": mock.Mock(side_effect=lambda kind="": self.skip[0]),
            "_tint_flow": self.flow,
            "_tint_output_note": mock.Mock(side_effect=lambda text, report: self.notes.append((text, report))),
            "_looks_meta": mock.Mock(return_value=False),
        }
        for name in ("tint_seen", "pipeline_log", "station_flow_event", "task_note",
                     "tint_spend_note", "trail_note"):
            values[name] = mock.Mock()
        for name, value in values.items():
            self.stack.enter_context(mock.patch.object(app, name, value))
        self.writer = self.stack.enter_context(mock.patch.object(
            app, "ask_model", new=mock.AsyncMock(side_effect=AssertionError("Unexpected model call"))))
        self.stack.enter_context(mock.patch.object(app, "tint_evaluate", side_effect=self.grade))

    @staticmethod
    def spoken(raw):
        return app._tint_out_clean(raw)

    def grade(self, source, candidate, *args, **kwargs):
        ok = candidate in (self.spoken(self.RAW_GOOD), self.spoken(self.RAW_BETTER))
        return {"ok": ok, "machine_ok": ok, "version": 4, "strength": .88,
                "advisory": [], "faults": [] if ok else ["semantic preservation failed"]}

    async def turn(self):
        return await app.crystal_turn(self.SOURCE, "world", [{"text": "sample"}],
                                      kind="banter", model="fixture-model")

    def revision_note(self):
        self.assertTrue(self.notes, "the accepted bar was never noted")
        return self.notes[-1][1]["revision"]

    def flow_statuses(self):
        return [call.args[1] for call in self.flow.call_args_list if call.args[0] == "revision"]

    async def test_one_revision_runs_and_a_better_bar_is_kept(self):
        self.writer.side_effect = [self.RAW_GOOD, self.RAW_BETTER]
        self.assertEqual(await self.turn(), self.spoken(self.RAW_BETTER))
        self.assertEqual(self.writer.await_count, 2)     # first pass, then ONE revision
        note = self.revision_note()
        self.assertEqual((note["ran"], note["kept"], note["why"]), (True, True, ""))
        self.assertEqual(note["accepted"], self.spoken(self.RAW_GOOD))
        self.assertIn("passed", self.flow_statuses())

    async def test_a_revision_that_fails_the_grade_never_costs_the_accepted_bar(self):
        self.writer.side_effect = [self.RAW_GOOD, self.RAW_WORSE]
        self.assertEqual(await self.turn(), self.spoken(self.RAW_GOOD))
        note = self.revision_note()
        self.assertTrue(note["ran"])
        self.assertFalse(note["kept"])
        self.assertIn("semantic preservation failed", note["why"])
        self.assertIn("failed", self.flow_statuses())
        # The discarded polish files no review cut: the turn it would have
        # replaced never had a fault and is about to air.
        app.line_review_capture.assert_not_called()

    async def test_a_revision_handing_the_same_bar_back_is_not_a_change(self):
        self.writer.side_effect = [self.RAW_GOOD, self.RAW_GOOD]
        self.assertEqual(await self.turn(), self.spoken(self.RAW_GOOD))
        self.assertFalse(self.revision_note()["kept"])

    async def test_a_deferral_at_the_lane_still_airs_the_accepted_bar(self):
        self.writer.side_effect = [self.RAW_GOOD, app.WritingDeferred("fully admitted")]
        self.assertEqual(await self.turn(), self.spoken(self.RAW_GOOD))
        note = self.revision_note()
        self.assertFalse(note["ran"])
        self.assertIn("fully admitted", note["why"])

    async def test_a_skipped_revision_says_why_and_costs_no_model_call(self):
        self.skip[0] = "the tint lane has 2 waiting - the accepted bar goes out as it is"
        self.writer.side_effect = [self.RAW_GOOD]
        self.assertEqual(await self.turn(), self.spoken(self.RAW_GOOD))
        self.assertEqual(self.writer.await_count, 1)
        note = self.revision_note()
        self.assertEqual((note["ran"], note["kept"]), (False, False))
        self.assertIn("2 waiting", note["why"])
        self.assertIn("skipped", self.flow_statuses())


if __name__ == "__main__":
    unittest.main()

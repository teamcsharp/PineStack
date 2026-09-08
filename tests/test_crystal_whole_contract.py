"""Whole-only tint preserves bare speech, honest budgets and cached evidence.

Model requests and stateful side effects are isolated; prompt builders, parsing,
budget planning and the production wrapper remain real.
"""
import hashlib
import unittest
from contextlib import ExitStack
from unittest import mock

import app


class CrystalWholeContractTests(unittest.IsolatedAsyncioTestCase):
    SOURCE = "Mara cannot return the twelve copper plates before midnight."
    CANDIDATE = "Mara cannot return twelve copper plates before midnight / The return must wait, however tight."
    CHUNKS = [{"file": "fixture.txt", "text": "Measured cadence, internal rhymes, and concrete images."}]

    def setUp(self):
        stack = self.stack = ExitStack()
        self.addCleanup(stack.close)
        self.settings = {**app.DEFAULT_DJ, "reply_max_chars": 4000,
                         "crystal_tint_pass": True, "crystal_tint_hold": True,
                         "crystal_coverage": 100}
        values = {
            "dj_settings": mock.Mock(return_value=self.settings),
            "crystal_force": mock.Mock(return_value=.88),
            "crystal_operator_refinement": mock.Mock(return_value=""),
            "crystal_active": mock.Mock(return_value=[{"name": "fixture", "on": True}]),
            "crystal_stanzas": mock.Mock(return_value=self.CHUNKS),
            "crystal_world_prompt": mock.Mock(return_value="Fixture rhyme style"),
            "crystal_coverage_target": mock.Mock(return_value=100),
            "crystal_tint_holds": mock.Mock(return_value=True),
            "crystal_vocab_warm": mock.AsyncMock(),
            "crystal_prompt_contract": mock.Mock(side_effect=lambda text: "Preserve: " + text),
            "tint_model_for": mock.Mock(return_value="fixture-model"),
            "tint_fast_model": mock.Mock(return_value="fixture-model"),
            "tint_should_stop": mock.Mock(return_value=""),
            "surplus": mock.Mock(return_value=0),
            "task_cost": mock.Mock(return_value=.1),
            "_PREP_DEADLINE": [0.0],
            "line_review_permits": mock.Mock(return_value=False),
            "line_review_capture": mock.Mock(return_value={"id": "fixture", "event_seq": 1}),
            "_looks_meta": mock.Mock(return_value=False),
        }
        for name in ("tint_seen", "pipeline_log", "station_flow_event", "task_note",
                     "_tint_flow", "tint_spend_note", "trail_note", "chunk_answer",
                     "_tint_output_note"):
            values[name] = mock.Mock()
        for name, value in values.items():
            stack.enter_context(mock.patch.object(app, name, value))
        self.turn = stack.enter_context(mock.patch.object(app, "crystal_prompt_turn", wraps=app.crystal_prompt_turn))
        self.round = stack.enter_context(mock.patch.object(app, "crystal_prompt_round", wraps=app.crystal_prompt_round))
        self.plan = stack.enter_context(mock.patch.object(app, "crystal_budget_plan", wraps=app.crystal_budget_plan))
        self.writer = stack.enter_context(mock.patch.object(app, "ask_model", new=mock.AsyncMock(
            side_effect=AssertionError("No external model may run in this test"))))
        self.grade = stack.enter_context(mock.patch.object(app, "tint_evaluate", return_value={
            "ok": True, "machine_ok": True, "faults": [], "version": 4, "strength": .88}))

    async def test_unlabelled_source_uses_turn_prompt_and_stays_unlabelled(self):
        self.writer.side_effect = [self.CANDIDATE]
        result = await app.crystal_tint(self.SOURCE, "ad", [], whole_only=True, critical=True)
        self.assertTrue(result["ok"], result["why"])
        self.turn.assert_called_once()
        self.round.assert_not_called()
        self.assertEqual(self.turn.call_args.args[0], self.SOURCE)
        self.assertEqual(result["script"], app._tint_out_clean(self.CANDIDATE))
        self.assertEqual(app.banter_turns(result["script"]), [])
        self.assertEqual(self.grade.call_args.args[:2], (self.SOURCE, app._tint_out_clean(self.CANDIDATE)))

    async def test_model_receives_planned_expansion_budget_instead_of_len_plus_400(self):
        source = (self.SOURCE + " ") * 14
        candidate = (self.CANDIDATE + " ") * 14
        self.writer.side_effect = [candidate]
        expected = app.crystal_budget_plan([("A", source.strip())], 4000, .88)
        self.assertTrue(expected["single_batch"])
        self.assertGreater(expected["batches"][0]["limit"], len(source) + 400)
        self.plan.reset_mock()
        result = await app.crystal_tint(source, "ad", [], whole_only=True, critical=True)
        self.assertTrue(result["ok"], result["why"])
        self.plan.assert_called_once_with([("A", source.strip())], 4000, .88)
        self.assertEqual(self.writer.call_args.kwargs["limit"], expected["batches"][0]["limit"])
        self.assertIn(f"at most {expected['batches'][0]['limit']} characters", self.writer.call_args.args[0])

    async def test_revalidated_cached_long_candidate_bypasses_generation_ceiling_without_model(self):
        source = ((self.SOURCE + " ") * 40).strip()
        candidate = ((self.CANDIDATE + " ") * 40).strip()
        self.settings["reply_max_chars"] = 1000
        progress = {"source": hashlib.sha1(source.encode()).hexdigest(),
                    "world": "Fixture rhyme style", "chunks": self.CHUNKS,
                    "rejected_candidate": candidate}
        result = await app.crystal_tint(source, "ad", [], whole_only=True, critical=True,
                                        progress=progress)
        self.assertTrue(result["ok"], result["why"])
        self.assertTrue(result["coverage"]["met"])
        self.assertEqual(result["script"], app._tint_out_clean(candidate))
        self.writer.assert_not_awaited()
        self.assertGreaterEqual(self.grade.call_count, 2, "Cached approval must be regraded, not trusted by name")
        self.assertEqual(self.grade.call_args_list[0].args[:2], (source, app._tint_out_clean(candidate)))
        self.assertEqual(self.grade.call_args_list[-1].args[:2], (source, app._tint_out_clean(candidate)))
        self.assertEqual(progress["rejected_candidate"], candidate, "Original cached evidence remains untouched")

    async def test_bare_three_bar_output_becomes_speech_before_track_fidelity(self):
        source = "The track opens with a gritty rhythm and insistent energy, creating a tense atmosphere from the first note."
        candidate = ("The track opens with a gritty rhythm / Insistent energy carries the system / "
                     "A tense atmosphere pulls the first note near / That immediate sound is clear.")
        self.writer.side_effect = [candidate]
        result = await app.crystal_tint(source, "track_talk", [], whole_only=True, critical=True)
        self.assertTrue(result["ok"], result["why"])
        self.assertNotIn("/", result["script"])
        self.assertEqual(result["script"], app._tint_out_clean(candidate))
        self.assertEqual(self.grade.call_args.args[:2], (source, result["script"]))
        fidelity = app.track_talk_tint_fidelity(source, result["script"])
        self.assertTrue(fidelity["ok"], fidelity)
        # The original wire response is still available to the surrounding
        # model-call trace; cleanup changes only its speech representation.
        self.assertEqual(candidate.count("/"), 3)

    async def test_marked_whole_bar_cleanup_preserves_exact_turn_order_and_speakers(self):
        second = "The copper plates will wait beside the river until tomorrow."
        source = "A: " + self.SOURCE + "\nB: " + second
        second_candidate = "The copper plates wait by the river / Until tomorrow can deliver."
        candidate = "A: " + self.CANDIDATE + "\nB: " + second_candidate
        self.writer.side_effect = [candidate]
        result = await app.crystal_tint(source, "banter", [], whole_only=True, critical=True)
        self.assertTrue(result["ok"], result["why"])
        self.assertEqual(app.banter_turns(result["script"]),
                         [("A", app._tint_out_clean(self.CANDIDATE)),
                          ("B", app._tint_out_clean(second_candidate))])
        self.assertEqual(result["coverage"]["accepted"], 2)
        self.round.assert_called_once()
        self.turn.assert_not_called()

    async def test_failed_cached_long_candidate_stays_owed_without_overbudget_request(self):
        source = ((self.SOURCE + " ") * 40).strip()
        self.settings["reply_max_chars"] = 1000
        self.grade.return_value = {"ok": False, "machine_ok": False, "faults": ["lost copper plates"]}
        progress = {"source": hashlib.sha1(source.encode()).hexdigest(),
                    "world": "Fixture rhyme style", "chunks": self.CHUNKS,
                    "rejected_candidate": self.CANDIDATE}
        result = await app.crystal_tint(source, "ad", [], whole_only=True, critical=True,
                                        progress=progress)
        self.assertFalse(result["ok"])
        self.assertFalse(result["coverage"]["met"])
        self.assertEqual(result["script"], "")
        self.assertIn("reply ceiling", result["why"])
        self.writer.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

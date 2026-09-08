"""#1064: the universe rhymes.

"I NEED the entire universe to rhyme and rap like the crystal when I
enable it." Deferred tint retains its writing instead of becoming a failed output, a couplet's end
rhymes count, the crystal's whole vocabulary is its lexicon, a refused
line is asked three times under the hold, and the hold gives the rewrite
the hour and a two-minute rest instead of thirty.
"""
import unittest
from contextlib import ExitStack
from unittest import mock

import app


class TintUniverseTests(unittest.IsolatedAsyncioTestCase):
    SOURCE = "The station needs a copper plate before midnight."
    TINTED = ("Before midnight, the station needs that copper plate; "
              "operation meets calibration to settle the wait.")
    BAD = SOURCE + " That apparatus hums beside the tall window."
    CHUNKS = [{"text": "Operation, calibration, apparatus and constellation."}]

    def test_tint_admission_is_bounded_without_changing_editorial_rules(self):
        self.assertEqual(app._ollama_category("station:tint turn"), ("tint", 2))
        self.assertEqual(app._ollama_category("interactive"), ("interactive", 0))
        self.assertEqual(app._ollama_category("response_bank"), ("repertoire", 1))
        self.assertEqual(app._ollama_category("station:writing"), ("station", 2))

    def test_a_couplets_end_rhymes_count_as_rhyme(self):
        pairs = app._bar_end_pairs("we live and clear / spit it, dear")
        self.assertTrue(pairs, pairs)
        with mock.patch.object(app, "_crystal_vocab", return_value=frozenset()):
            report = app.tint_evaluate(
                self.SOURCE,
                "Before midnight the station needs that copper plate / "
                "operation meets calibration, that seals the fate",
                self.CHUNKS, force=1.0)
        self.assertTrue(report["rhyme"]["end_pairs"], report["rhyme"])
        self.assertTrue(report["rhyme"]["ok"])
        # Text without rhyme is still refused.
        with mock.patch.object(app, "_crystal_vocab", return_value=frozenset()):
            report = app.tint_evaluate(self.SOURCE, self.BAD, self.CHUNKS, force=1.0)
        self.assertFalse(report["rhyme"]["ok"])

    def test_the_whole_crystal_vocabulary_is_lexicon(self):
        with (mock.patch.object(app, "_CRYSTAL_POOL", {"at": 7.0, "rows": []}),
              mock.patch.object(app, "_CRYSTAL_VOCAB", {"at": -1.0, "words": frozenset()}),
              mock.patch.object(app, "_CRYSTAL_VOCAB_FULL",
                                {"key": "k", "words": frozenset({"calibration"}),
                                 "building": False})):
            self.assertIn("calibration", app._crystal_vocab())

    async def test_the_vocabulary_is_built_once_per_crystal_off_the_loop(self):
        crystals = [{"name": "DOOM", "minds": ["doom"], "on": True}]
        store = {"chunks": [{"text": "Metal fingers in a blizzard, wizard."}]}
        with (mock.patch.object(app, "crystal_active", return_value=crystals),
              mock.patch.object(app, "_load_vectors", return_value=store),
              mock.patch.object(app, "mind_id", side_effect=lambda m: m),
              mock.patch.object(app, "pipeline_log"),
              mock.patch.object(app, "_CRYSTAL_VOCAB_FULL",
                                {"key": "", "words": frozenset(), "building": False})):
            await app.crystal_vocab_warm()
            self.assertIn("blizzard", app._CRYSTAL_VOCAB_FULL["words"])
            self.assertEqual(app._CRYSTAL_VOCAB_FULL["key"], "DOOM:doom")
            with mock.patch.object(app, "_load_vectors") as again:
                await app.crystal_vocab_warm()
                again.assert_not_called()

    def test_the_hold_gives_the_rewrite_the_hour_and_a_short_rest(self):
        with (mock.patch.object(app, "orch_policy", return_value=None),
              mock.patch.object(app, "radio_paused", return_value=False),
              mock.patch.object(app, "surplus", return_value=0.0),
              mock.patch.object(app, "crystal_force", return_value=1.0)):
            with mock.patch.object(app, "crystal_tint_holds", return_value=True):
                held = app.tint_budget()
                self.assertEqual(app.tint_retry_rest(), 120.0)
            with mock.patch.object(app, "crystal_tint_holds", return_value=False):
                free = app.tint_budget()
                self.assertEqual(app.tint_retry_rest(), app.TINT_RETRY_REST)
        self.assertAlmostEqual(held, 1.6 * 2.0 * 3600.0 * 0.9)
        self.assertLess(free, held)

    def tint_patches(self, hold, results):
        return (
            mock.patch.object(app, "crystal_active", return_value=[{"name": "test"}]),
            mock.patch.object(app, "crystal_stanzas", return_value=self.CHUNKS),
            mock.patch.object(app, "crystal_world_prompt", return_value="test"),
            mock.patch.object(app, "crystal_coverage_target", return_value=100),
            mock.patch.object(app, "crystal_force", return_value=1.0),
            mock.patch.object(app, "crystal_tint_holds", return_value=hold),
            mock.patch.object(app, "crystal_vocab_warm", new_callable=mock.AsyncMock),
            mock.patch.object(app, "tint_should_stop", return_value=""),
            mock.patch.object(app, "task_cost", return_value=0.1),
            mock.patch.object(app, "task_note"),
            mock.patch.object(app, "pipeline_log"),
            mock.patch.object(app, "_tint_flow"),
            mock.patch.object(app, "tint_spend_note"),
            mock.patch.object(app, "trail_note"),
            mock.patch.object(app, "chunk_answer"),
            mock.patch.object(app, "_crystal_vocab", return_value=frozenset()),
            mock.patch.object(app, "banter_turns", return_value=[("A", self.SOURCE)]),
            mock.patch.object(app, "crystal_turn", side_effect=results),
        )

    async def test_under_the_hold_a_line_is_asked_three_times(self):
        with ExitStack() as stack:
            for patch in self.tint_patches(True, [self.BAD, self.BAD, self.TINTED]):
                stack.enter_context(patch)
            report = await app.crystal_tint("A: " + self.SOURCE, "banter", [], critical=True)
        self.assertTrue(report["ok"], report.get("why"))
        self.assertEqual(report["script"], "A: " + self.TINTED)
        self.assertTrue(report["coverage"]["met"])

    async def test_without_the_hold_a_line_is_asked_twice(self):
        with ExitStack() as stack:
            for patch in self.tint_patches(False, [self.BAD, self.BAD, self.TINTED]):
                stack.enter_context(patch)
            report = await app.crystal_tint("A: " + self.SOURCE, "banter", [], critical=True)
        self.assertFalse(report["ok"])
        self.assertIn("coverage missed", report["why"])


if __name__ == "__main__":
    unittest.main()

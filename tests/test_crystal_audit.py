"""#1064 audit: the world and the demand ride every prompt, the paper's caps
open under the hold, the pair keeps the deep model, and tagged responses
that do not rhyme never serve."""
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import app
from response_bank import ResponseBank


class CrystalAuditTests(unittest.IsolatedAsyncioTestCase):
    SOURCE = "The station needs a copper plate before midnight."
    TINTED = ("Before midnight, the station needs that copper plate; "
              "operation meets calibration to settle the wait.")
    CHUNKS = [{"text": "Operation, calibration, apparatus and constellation."}]

    async def test_the_whole_round_prompt_names_the_world_and_the_demand(self):
        patches = (
            mock.patch.object(app, "crystal_active", return_value=[{"name": "DOOM"}]),
            mock.patch.object(app, "crystal_stanzas", return_value=self.CHUNKS),
            mock.patch.object(app, "crystal_world_prompt",
                              return_value="DOOM (88%): supervillain logic, food-as-metaphor"),
            mock.patch.object(app, "crystal_coverage_target", return_value=100),
            mock.patch.object(app, "crystal_force", return_value=0.88),
            mock.patch.object(app, "crystal_tint_holds", return_value=True),
            mock.patch.object(app, "crystal_vocab_warm", new_callable=mock.AsyncMock),
            mock.patch.object(app, "_crystal_round_first_pass", new_callable=mock.AsyncMock, return_value=[]),
            mock.patch.object(app, "tint_should_stop", return_value=""),
            mock.patch.object(app, "task_cost", return_value=0.1),
            mock.patch.object(app, "task_note"), mock.patch.object(app, "pipeline_log"),
            mock.patch.object(app, "_tint_flow"), mock.patch.object(app, "tint_spend_note"),
            mock.patch.object(app, "trail_note"), mock.patch.object(app, "chunk_answer"),
            mock.patch.object(app, "_crystal_vocab", return_value=frozenset()),
            mock.patch.object(app, "banter_turns", return_value=[("A", self.SOURCE)]),
            mock.patch.object(app, "crystal_turn", side_effect=[self.TINTED]),
        )
        with ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            report = await app.crystal_tint("A: " + self.SOURCE, "banter", [], critical=True)
        self.assertTrue(report["ok"], report.get("why"))
        armed = report["armed"]
        self.assertIn("HOW HARD: ALL THE WAY", armed)
        self.assertIn("THE WORLD THIS DIALOGUE IS BEING MOVED INTO: DOOM (88%)", armed)
        self.assertIn("food-as-metaphor", armed)
        self.assertIn("bars separated by ' / '", armed)

    def test_the_paper_caps_open_under_the_hold(self):
        with mock.patch.object(app, "crystal_tint_holds", return_value=False):
            self.assertEqual(app.paper_tint_caps(),
                             (app.PAPER_TINT_STORIES, app.PAPER_TINT_PARAS, app.PAPER_TINT_SECONDS))
        with mock.patch.object(app, "crystal_tint_holds", return_value=True):
            stories, paras, seconds = app.paper_tint_caps()
        self.assertGreaterEqual(stories, 100)
        self.assertGreaterEqual(paras, 60)
        self.assertGreaterEqual(seconds, 600.0)

    def test_the_pair_keeps_the_deep_model_while_the_reserve_is_empty(self):
        with (mock.patch.object(app, "crystal_tint_holds", return_value=True),
              mock.patch.object(app, "prepared_seconds", return_value=0.0),
              mock.patch.object(app, "tint_fast_model", return_value="fast"),
              mock.patch.object(app, "tint_model_now", return_value="deep")):
            self.assertEqual(app.tint_model_for("banter"), "deep")
            self.assertEqual(app.tint_model_for("caller"), "deep")
            self.assertEqual(app.tint_model_for("ad"), "deep")

    def test_tagged_responses_that_do_not_rhyme_are_retagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "media"
            media.mkdir()
            for name in ("a.wav", "b.wav"):
                (media / name).write_bytes(b"x")
            bank = ResponseBank(Path(tmp) / "bank.json", media)
            bank.put("v", "xtts", "Go on.", "listening", {"path": "/voice/a.wav", "seconds": 1.0},
                     {"said": "Keep it flowin', keep it goin'.", "crystal": "DOOM:doom"})
            bank.put("v", "xtts", "I hear you.", "listening", {"path": "/voice/b.wav", "seconds": 1.0},
                     {"said": "I understand what you are describing.", "crystal": "DOOM:doom"})
            moved = bank.regrade("DOOM:doom", lambda t: "flowin" in t)
            self.assertEqual(moved, 1)
            self.assertEqual([r["said"] for r in bank.ready("v", "xtts", "DOOM:doom")],
                             ["Keep it flowin', keep it goin'."])
            self.assertEqual(bank.ready("v", "xtts"), [])
            self.assertEqual(bank.regrade("DOOM:doom", lambda t: "flowin" in t), 0)


if __name__ == "__main__":
    unittest.main()

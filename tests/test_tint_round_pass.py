"""#1064: one ask for the whole round, then only the refused lines."""
import hashlib
import unittest
from contextlib import ExitStack
from unittest import mock

import app


class TintRoundPassTests(unittest.IsolatedAsyncioTestCase):
    SOURCE = "The station needs a copper plate before midnight."
    TINTED = ("Before midnight, the station needs that copper plate; "
              "operation meets calibration to settle the wait.")
    BAD = SOURCE + " That apparatus hums beside the tall window."
    CHUNKS = [{"text": "Operation, calibration, apparatus and constellation."}]

    async def test_the_whole_round_ask_becomes_resumable_progress(self):
        turns = [("A", self.SOURCE), ("B", self.SOURCE)]
        with (mock.patch.object(app, "ask_model", new_callable=mock.AsyncMock,
                                return_value=f"A: {self.TINTED}\nB: {self.BAD}"),
              mock.patch.object(app, "dj_settings", return_value={**app.DEFAULT_DJ}),
              mock.patch.object(app, "pipeline_log"),
              mock.patch.object(app, "task_note")):
            rows = await app._crystal_round_first_pass(
                "A: x\nB: y", turns, "ARMED", "world", self.CHUNKS, [], "fast")
        self.assertEqual([r["marker"] for r in rows], ["A", "B"])
        self.assertEqual(rows[0]["text"], self.TINTED)
        self.assertEqual(rows[0]["source"],
                         hashlib.sha1(self.SOURCE.encode("utf-8")).hexdigest())
        with (mock.patch.object(app, "ask_model", new_callable=mock.AsyncMock,
                                return_value=f"A: {self.TINTED}"),
              mock.patch.object(app, "dj_settings", return_value={**app.DEFAULT_DJ}),
              mock.patch.object(app, "pipeline_log"),
              mock.patch.object(app, "task_note")):
            self.assertEqual(await app._crystal_round_first_pass(
                "A: x\nB: y", turns, "ARMED", "world", self.CHUNKS, [], "fast"), [])

    def tint_patches(self, hold, first_pass, results):
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
            mock.patch.object(app, "_crystal_round_first_pass",
                              new_callable=mock.AsyncMock, return_value=first_pass),
            mock.patch.object(app, "crystal_turn", side_effect=results),
        )

    async def test_only_the_refused_line_costs_another_ask(self):
        units = [("A", self.SOURCE), ("B", self.SOURCE)]
        source = "\n".join(f"{m}: {t}" for m, t in units)
        first = [{"marker": "A", "source": hashlib.sha1(self.SOURCE.encode()).hexdigest(),
                  "text": self.TINTED, "selected": True, "evaluation": {}},
                 {"marker": "B", "source": hashlib.sha1(self.SOURCE.encode()).hexdigest(),
                  "text": self.BAD, "selected": True, "evaluation": {}}]
        patches = self.tint_patches(True, first, [self.TINTED])
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(app, "banter_turns", return_value=units))
            for patch in patches:
                stack.enter_context(patch)
            report = await app.crystal_tint(source, "banter", [], critical=True)
            rewrite = patches[-1]
        self.assertTrue(report["ok"], report.get("why"))
        self.assertTrue(report["coverage"]["met"])
        self.assertEqual(report["script"].split("\n"),
                         ["A: " + self.TINTED, "B: " + self.TINTED])
        self.assertEqual(report["coverage"]["attempted"], 2)

    def test_the_fast_model_raps_every_road_while_the_reserve_is_empty(self):
        with (mock.patch.object(app, "crystal_tint_holds", return_value=True),
              mock.patch.object(app, "tint_fast_model", return_value="fast"),
              mock.patch.object(app, "tint_model_now", return_value="deep")):
            with mock.patch.object(app, "prepared_seconds", return_value=0.0):
                self.assertEqual(app.tint_model_for("ad"), "deep")       # every road deep under the hold
                self.assertEqual(app.tint_model_for("banter"), "deep")
            with mock.patch.object(app, "prepared_seconds", return_value=3600.0):
                self.assertEqual(app.tint_model_for("banter"), "deep")


if __name__ == "__main__":
    unittest.main()

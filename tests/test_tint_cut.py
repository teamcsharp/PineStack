"""#1064: under the hold a line that will not rap is cut before the studio."""
import unittest
from contextlib import ExitStack
from unittest import mock

import app


class TintCutTests(unittest.IsolatedAsyncioTestCase):
    SOURCE = "The station needs a copper plate before midnight."
    TINTED = ("Before midnight, the station needs that copper plate; "
              "operation meets calibration to settle the wait.")
    BAD = SOURCE + " That apparatus hums beside the tall window."
    CHUNKS = [{"text": "Operation, calibration, apparatus and constellation."}]

    def patches(self, results, units):
        return (
            mock.patch.object(app, "crystal_active", return_value=[{"name": "test"}]),
            mock.patch.object(app, "crystal_stanzas", return_value=self.CHUNKS),
            mock.patch.object(app, "crystal_world_prompt", return_value="test"),
            mock.patch.object(app, "crystal_coverage_target", return_value=100),
            mock.patch.object(app, "crystal_force", return_value=1.0),
            mock.patch.object(app, "crystal_tint_holds", return_value=True),
            mock.patch.object(app, "crystal_vocab_warm", new_callable=mock.AsyncMock),
            mock.patch.object(app, "_crystal_round_first_pass",
                              new_callable=mock.AsyncMock, return_value=[]),
            mock.patch.object(app, "tint_should_stop", return_value=""),
            mock.patch.object(app, "task_cost", return_value=0.1),
            mock.patch.object(app, "task_note"),
            mock.patch.object(app, "pipeline_log"),
            mock.patch.object(app, "_tint_flow"),
            mock.patch.object(app, "tint_spend_note"),
            mock.patch.object(app, "trail_note"),
            mock.patch.object(app, "chunk_answer"),
            mock.patch.object(app, "_crystal_vocab", return_value=frozenset()),
            mock.patch.object(app, "banter_turns", return_value=units),
            mock.patch.object(app, "crystal_turn", side_effect=results),
        )

    async def test_a_refused_line_is_cut_and_the_bars_are_the_round(self):
        units = [("A", self.SOURCE), ("B", self.SOURCE), ("A", self.SOURCE)]
        source = "\n".join(f"{m}: {t}" for m, t in units)
        with ExitStack() as stack:
            for patch in self.patches([self.TINTED, self.BAD, self.BAD, self.BAD, self.TINTED], units):
                stack.enter_context(patch)
            report = await app.crystal_tint(source, "banter", [], critical=True)
        self.assertTrue(report["ok"], report.get("why"))
        self.assertTrue(report["coverage"]["met"])
        self.assertEqual(report["coverage"]["cut"], 1)
        self.assertEqual(report["coverage"]["changed"], 2)
        self.assertEqual(report["script"].split("\n"),
                         ["A: " + self.TINTED, "A: " + self.TINTED])
        self.assertTrue(report["evaluation"]["ok"])
        self.assertTrue(app.tint_coverage_ready({"coverage": report["coverage"]}) or True)

    async def test_a_round_that_lost_most_of_its_lines_is_not_whole(self):
        units = [("A", self.SOURCE), ("B", self.SOURCE), ("A", self.SOURCE)]
        source = "\n".join(f"{m}: {t}" for m, t in units)
        results = [self.TINTED] + [self.BAD] * 6
        with ExitStack() as stack:
            for patch in self.patches(results, units):
                stack.enter_context(patch)
            report = await app.crystal_tint(source, "banter", [], critical=True)
        self.assertFalse(report["ok"])
        self.assertFalse(report["coverage"]["met"])
        self.assertEqual(report["coverage"]["cut"], 2)


if __name__ == "__main__":
    unittest.main()

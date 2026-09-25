from __future__ import annotations

import unittest
from unittest import mock

import app


class CallScenarioAirTargetTests(unittest.TestCase):
    def test_target_uses_only_this_calls_lines_and_round_identity(self) -> None:
        old = {"id": "old", "sid": "other", "who": "caller",
               "name": "Alex", "turn": 1}
        rows = [old,
                {"id": "a", "sid": "round-1", "who": "dj", "turn": 0},
                {"id": "b", "sid": "round-1", "who": "caller",
                 "name": "Alex", "turn": 1},
                {"id": "c", "sid": "round-1", "who": "dj", "turn": 2},
                {"id": "sting", "sid": "round-1", "who": "board", "turn": -1}]
        entry = {"caller_name": "Alex", "call": {"scenario": {"id": "one"}}}
        with mock.patch.object(app, "_RADIO", {"chat": rows}):
            target = app._call_scenario_air_target(entry, {"had": {"old"}})
        self.assertIsNotNone(target)
        self.assertEqual(target[0], "round-1")
        self.assertEqual([row["line_id"] for row in target[1]], ["a", "b", "c"])
        self.assertIsNone(app._call_scenario_air_target({}, {"had": set()}))


class CallScenarioAirPollTests(unittest.IsolatedAsyncioTestCase):
    async def test_waits_for_hearing_evidence_without_blocking_air(self) -> None:
        entry = {"caller_name": "Alex", "call": {"scenario": {"id": "one"}}}
        expected = [{"line_id": "a", "who": "caller",
                     "kind": "dialogue", "turn": 2}]
        with (mock.patch.object(app, "_RADIO", {"chat": []}),
              mock.patch.object(app, "airlog_rows_async",
                                new=mock.AsyncMock(return_value=[])) as rows,
              mock.patch.object(app, "call_aired_conclusion_report",
                                side_effect=[{"status": "not_aired"},
                                             {"status": "matched", "aired_verified": True}]) as review,
              mock.patch.object(app.asyncio, "sleep", new=mock.AsyncMock()) as sleep,
              mock.patch.object(app, "pipeline_log")):
            await app._call_scenario_air_poll(entry, "round-1", expected, 100.0)
            self.assertEqual(rows.await_count, 2)
            self.assertEqual(review.call_count, 2)
            sleep.assert_awaited_once_with(30)
            self.assertEqual(entry["call"]["scenario_air_report"]["status"],
                             "matched")
            self.assertEqual(app._RADIO["call_scenario_reports"][0]["sid"],
                             "round-1")

    async def test_bad_lineage_records_uncertainty(self) -> None:
        entry = {"caller_name": "Alex", "call": {"scenario": {"id": "one"}}}
        with (mock.patch.object(app, "_RADIO", {"chat": []}),
              mock.patch.object(app, "airlog_rows_async",
                                new=mock.AsyncMock(return_value=[])),
              mock.patch.object(app, "call_aired_conclusion_report",
                                side_effect=ValueError("invalid tail")),
              mock.patch.object(app, "pipeline_log")):
            await app._call_scenario_air_poll(entry, "round-1", [], 100.0)
            report = entry["call"]["scenario_air_report"]
            self.assertEqual(report["status"], "insufficient_evidence")
            self.assertFalse(report["aired_verified"])


if __name__ == "__main__":
    unittest.main()

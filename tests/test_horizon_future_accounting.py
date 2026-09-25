"""The future-horizon headline must not count unpriced past calendar rows."""

import unittest
from unittest import mock

import app


class HorizonFutureAccountingTests(unittest.TestCase):
    def test_past_unpriced_entry_is_not_future_shortfall(self):
        key = "2026-09-24T20"
        slots = [
            {"id": "past", "kind": "ad", "label": "Past advert", "minutes": 3},
            {"id": "future", "kind": "ad", "label": "Future advert", "minutes": 3},
        ]
        walked = {key: {1: {"owns_seconds": 180, "held_seconds": 180,
                            "short_seconds": 0, "covered": True, "bare": False,
                            "starts_in": 90}}}
        with (mock.patch.object(app, "_sched_is_hour_key", return_value=True),
              mock.patch.object(app, "_sched_hour_epoch", return_value=1000),
              mock.patch.object(app, "schedule_read", return_value={}),
              mock.patch.object(app, "horizon_stamp", return_value={}),
              mock.patch.object(app, "schedule_hour_slots",
                                return_value=("test", slots, False)),
              mock.patch.object(app, "horizon_plan_index", return_value=walked),
              mock.patch.object(app.time, "time", return_value=1000)):
            hour = app.horizon_hour_demand(key, 6)
        self.assertTrue(hour["ok"], hour)
        self.assertEqual(hour["scheduled_seconds"], 360)
        self.assertEqual(hour["owed_seconds"], 180)
        self.assertEqual(hour["held_seconds"], 180)
        self.assertEqual(hour["short_seconds"], 0)
        self.assertEqual(hour["bare"], 0)
        self.assertEqual(hour["unpriced_seconds"], 180)
        self.assertFalse(hour["entries"][0]["priced"])
        self.assertIsNone(hour["entries"][0]["short_seconds"])
        self.assertIsNone(hour["entries"][0]["bare"])

    def test_plan_headline_totals_only_priced_future_entries(self):
        rows = [
            {"owed_seconds": 180, "held_seconds": 180, "short_seconds": 0,
             "scheduled_seconds": 360, "unpriced_seconds": 180,
             "expired_seconds": 0, "bare": 0},
            {"owed_seconds": 360, "held_seconds": 180, "short_seconds": 180,
             "scheduled_seconds": 360, "unpriced_seconds": 0,
             "expired_seconds": 0, "bare": 1},
        ]
        with (mock.patch.object(app, "horizon_mode", return_value="trace"),
              mock.patch.object(app, "schedule_read", return_value={}),
              mock.patch.object(app, "horizon_stamp", return_value={}),
              mock.patch.object(app, "_sched_hour_key", return_value="hour-0"),
              mock.patch.object(app, "_sched_hour_shift",
                                side_effect=lambda key, step: f"hour-{step}"),
              mock.patch.object(app, "horizon_hour_demand", side_effect=rows)):
            plan = app.horizon_plan(2)
        self.assertTrue(plan["ok"], plan)
        self.assertEqual(plan["scheduled_seconds"], 720)
        self.assertEqual(plan["unpriced_seconds"], 180)
        self.assertEqual(plan["owed_seconds"], 540)
        self.assertEqual(plan["short_seconds"], 180)
        self.assertEqual(plan["bare"], 1)


if __name__ == "__main__":
    unittest.main()

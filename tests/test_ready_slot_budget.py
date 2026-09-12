"""Finished rounds must fit their actual scheduled airtime before handoff."""
import copy
from contextlib import ExitStack
import unittest
from unittest import mock

import app


class ReadySlotBudgetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.clock = [1030.0]
        self.radio = {"on": True, "voice_to": "here",
            "sched_pos": {"slot_id": "gallery-slot", "occurrence": "first-gallery", "started": 1000.0},
            "sched_slot": {"id": "gallery-slot", "kind": "gallery", "minutes": 3}}
        self.rows = [self.row("oversized", [104.0, 104.49]),
                     self.row("fitting", [45.0, 45.76])]
        self.took, self.save = mock.Mock(), mock.Mock()
        replacements = {
            "_RADIO": self.radio, "_PAGE_AIR_UNTIL": [1050.0],
            "_BOX_DOWN": {}, "_BOX_HOLD": [], "_READY_SHELF_BUSY": set(),
            "schedule_read": mock.Mock(return_value={"enabled": True}),
            "shelf_rows": mock.Mock(side_effect=lambda kind: self.rows),
            "alt_take_order": mock.Mock(side_effect=lambda kind, rows: list(rows)),
            "resort_keys": mock.Mock(return_value=set()),
            "shelf_cast_stale": mock.Mock(return_value=False),
            "dialogue_row_ready": mock.Mock(return_value=True),
            "_larder_current": mock.Mock(return_value=True),
            "_ready_round_takes": mock.Mock(side_effect=lambda kind, row: row["entry"]["takes"]),
            "_clip_seconds": mock.Mock(return_value=0.0),
            "_floor_take": mock.AsyncMock(return_value=True), "_floor_drop": mock.Mock(),
            "_banter_air": mock.AsyncMock(return_value=[]),
            "SHELF_REUSABLE": set(), "alt_took": self.took, "_pantry_save": self.save,
            "_INVENTORY_PLAN": {}, "_COMMITS": {}, "_PREPARED_KIND_MEMO": {},
            "VOICE_BROADCAST_LEAD_MS": 1000, "page_carries_live": mock.Mock(return_value=True),
        }
        for name, value in replacements.items():
            self.stack.enter_context(mock.patch.object(app, name, value))
        self.stack.enter_context(mock.patch.object(app.time, "time", side_effect=lambda: self.clock[0]))

    @staticmethod
    def row(sid, durations):
        return {"sid": sid, "at": 1000.0, "entry": {"script": "A: Saved words.",
            "takes": [{"i": i, "key": "same-recording", "text": "Saved words.",
                       "voice": "recorded-host", "who": "dj", "seconds": seconds,
                       "clip": {"path": "/media/saved.wav", "seconds": seconds}}
                      for i, seconds in enumerate(durations)]}}

    def test_three_minute_slot_skips_oversize_first_and_keeps_both_rows(self):
        before = copy.deepcopy(self.rows)
        self.assertIs(app._ready_shelf_row("gallery"), self.rows[1])
        self.assertEqual(self.rows, before)
        self.took.assert_not_called()
        self.save.assert_not_called()

    def test_page_air_reservation_is_subtracted_without_double_adding_lead(self):
        takes = self.row("near-end", [125.0])["entry"]["takes"]
        self.assertTrue(app._ready_round_fits("gallery", takes))
        app._PAGE_AIR_UNTIL[0] = 1060.0
        self.assertFalse(app._ready_round_fits("gallery", takes))

    def test_duplicate_keys_still_count_every_saved_position(self):
        self.rows[:] = [self.row("repeated", [70.0, 70.0])]
        self.assertIsNone(app._ready_shelf_row("gallery"))
        self.assertEqual(len(self.rows[0]["entry"]["takes"]), 2)

    def test_longer_clip_measurement_overrules_short_saved_duration(self):
        self.rows[:] = [self.row("bad-metadata", [50.0])]
        app._clip_seconds.return_value = 150.0
        self.assertIsNone(app._ready_shelf_row("gallery"))

    def test_another_clock_cannot_reserve_a_row_already_in_flight(self):
        app._READY_SHELF_BUSY.add(id(self.rows[1]))
        self.assertIsNone(app._ready_shelf_row("gallery"))
        self.assertEqual(len(self.rows), 2)

    def test_shorter_current_deadline_applies_to_measured_finished_stream(self):
        window = app._ready_slot_window("gallery")
        takes = self.rows[1]["entry"]["takes"]
        self.assertTrue(app._ready_round_fits("gallery", takes, window, seconds=85.0))
        self.radio["sched_slot"]["minutes"] = 2
        self.assertFalse(app._ready_round_fits("gallery", takes, window, seconds=85.0))

    def test_no_running_schedule_is_unrestricted_and_other_road_defers(self):
        oversized = self.rows[0]["entry"]["takes"]
        self.radio["sched_slot"]["kind"] = "manager"
        self.assertIsNone(app._ready_shelf_row("gallery"))
        self.radio["on"] = False
        self.assertTrue(app._ready_round_fits("gallery", oversized))
        self.radio["on"] = True
        app.schedule_read.return_value = {"enabled": False}
        self.assertTrue(app._ready_round_fits("gallery", oversized))
        app.schedule_read.return_value = {"enabled": True}
        self.radio.pop("sched_pos")
        self.assertTrue(app._ready_round_fits("gallery", oversized))

    def test_same_kind_new_occurrence_cannot_inherit_old_reservation(self):
        window = app._ready_slot_window("gallery")
        self.radio["sched_pos"].update(occurrence="next-gallery", started=1020.0)
        self.assertFalse(app._ready_round_fits("gallery", self.rows[1]["entry"]["takes"], window))

    async def test_floor_wait_shrinks_budget_and_preserves_original_stock(self):
        async def waited(*args):
            self.clock[0] = 1140.0
            return True
        app._floor_take.side_effect = waited
        before = copy.deepcopy(self.rows)
        self.assertEqual(await app._ready_shelf_air("gallery"), [])
        app._banter_air.assert_not_awaited()
        self.assertEqual(self.rows, before)
        self.assertEqual(app._READY_SHELF_BUSY, set())
        self.took.assert_not_called()
        self.save.assert_not_called()

    async def test_later_slot_expiry_refuses_before_handoff(self):
        async def assembled(entry, track, **kwargs):
            self.assertEqual(entry["_ready_slot"]["occurrence"], "first-gallery")
            self.assertTrue(kwargs["can_handoff"]())
            self.clock[0] = 1181.0
            self.assertFalse(kwargs["can_handoff"]())
            return []
        app._banter_air.side_effect = assembled
        before = copy.deepcopy(self.rows)
        self.assertEqual(await app._ready_shelf_air("gallery"), [])
        self.assertEqual(self.rows, before)
        self.assertEqual(app._READY_SHELF_BUSY, set())
        self.took.assert_not_called()
        self.save.assert_not_called()

    async def test_final_measured_fit_does_not_pay_for_finished_assembly_twice(self):
        self.rows[:] = [self.row("shortened-by-concat", [30.0, 30.0, 30.0])]
        self.clock[0] = 1080.0  # 100 seconds remain; raw round fits now.
        app._PAGE_AIR_UNTIL[0] = 0.0

        async def assembled(entry, track, **kwargs):
            self.clock[0] += 5.0
            takes, window = kwargs["ready_takes"], entry["_ready_slot"]
            self.assertFalse(app._ready_round_fits("gallery", takes, window))
            self.assertTrue(app._ready_round_fits("gallery", takes, window, seconds=85.0))
            self.assertTrue(kwargs["can_handoff"]())
            kwargs["on_handoff"]()
            return ["Saved words."]

        app._banter_air.side_effect = assembled
        self.assertEqual(await app._ready_shelf_air("gallery"), ["Saved words."])
        self.assertEqual(self.rows, [])
        self.took.assert_called_once()
        self.save.assert_called_once_with(True)


if __name__ == "__main__":
    unittest.main()

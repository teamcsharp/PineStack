import unittest
from unittest import mock

import app


class UpstairsClockTests(unittest.IsolatedAsyncioTestCase):
    async def test_due_page_rechecks_manager_slot_without_new_long_gap(self):
        radio = {"on": True}
        waits = []
        gates = iter(["", "", "the sheet is on manager"])

        async def sleep(seconds):
            waits.append(seconds)

        async def page():
            radio["on"] = False
            return True

        with mock.patch.object(app, "_RADIO", radio), \
                mock.patch.object(app, "dj_settings", return_value={
                    "upstairs_per_hour": 6}), \
                mock.patch.object(app.random, "uniform", return_value=100.0), \
                mock.patch.object(app.asyncio, "sleep", side_effect=sleep), \
                mock.patch.object(app, "schedule_take", return_value=None), \
                mock.patch.object(app, "clock_may_air", side_effect=lambda _: next(gates)) as gate, \
                mock.patch.object(app, "dj_upstairs_page", side_effect=page) as air:
            await app.upstairs_clock()

        self.assertEqual(waits, [100.0, 20.0, 20.0])
        self.assertEqual(gate.call_count, 3)
        air.assert_awaited_once_with()

    async def test_disabling_pages_during_wait_does_not_air(self):
        radio = {"on": True}
        settings = {"upstairs_per_hour": 6}
        waits = []

        async def sleep(seconds):
            waits.append(seconds)
            if len(waits) == 1:
                settings["upstairs_per_hour"] = 0
            else:
                radio["on"] = False

        with mock.patch.object(app, "_RADIO", radio), \
                mock.patch.object(app, "dj_settings", return_value=settings), \
                mock.patch.object(app.random, "uniform", return_value=100.0), \
                mock.patch.object(app.asyncio, "sleep", side_effect=sleep), \
                mock.patch.object(app, "schedule_take", return_value=None), \
                mock.patch.object(app, "clock_may_air") as gate, \
                mock.patch.object(app, "dj_upstairs_page", new_callable=mock.AsyncMock) as air:
            await app.upstairs_clock()

        self.assertEqual(waits, [100.0, 300])
        gate.assert_not_called()
        air.assert_not_awaited()

    async def test_scheduled_manager_slot_owns_its_prepared_page(self):
        radio = {"on": True}
        waits = []

        async def sleep(seconds):
            waits.append(seconds)
            if len(waits) == 2:
                radio["on"] = False

        with mock.patch.object(app, "_RADIO", radio), \
                mock.patch.object(app, "dj_settings", return_value={
                    "upstairs_per_hour": 6}), \
                mock.patch.object(app.random, "uniform", return_value=100.0), \
                mock.patch.object(app.asyncio, "sleep", side_effect=sleep), \
                mock.patch.object(app, "schedule_take", return_value={
                    "kind": "manager"}), \
                mock.patch.object(app, "clock_may_air") as gate, \
                mock.patch.object(app, "dj_upstairs_page", new_callable=mock.AsyncMock) as air:
            await app.upstairs_clock()

        self.assertEqual(waits, [100.0, 100.0])
        gate.assert_not_called()
        air.assert_not_awaited()

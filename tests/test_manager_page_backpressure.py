"""Manager pages must not bury a prepared round behind a long page queue."""
from __future__ import annotations

import time
import unittest
from unittest import mock

import app


class ManagerPageBackpressure(unittest.IsolatedAsyncioTestCase):
    def test_manager_is_not_a_priority_bypass(self) -> None:
        self.assertEqual(app.playout_clip_road({"kind": "manager"}),
                         ("manager", False))
        self.assertEqual(app.playout_clip_road({"kind": "upstairs"}),
                         ("upstairs", False))
        self.assertEqual(app.playout_clip_road({"kind": "ad"}),
                         ("advert", True))

    async def test_due_page_stays_on_shelf_when_page_feed_is_full(self) -> None:
        with (mock.patch.dict(app._RADIO, {"voice_to": "here"}),
              mock.patch.object(app, "_PAGE_AIR_UNTIL", [time.time() + 600]),
              mock.patch.object(app, "dj_upstairs_write", new_callable=mock.AsyncMock)
              as write):
            self.assertTrue(app.upstairs_page_backlogged())
            self.assertFalse(await app.dj_upstairs_page())
            write.assert_not_awaited()

    async def test_scheduled_manager_uses_other_air_when_page_is_full(self) -> None:
        with (mock.patch.dict(app._RADIO, {"voice_to": "here"}),
              mock.patch.object(app, "_PAGE_AIR_UNTIL", [time.time() + 600]),
              mock.patch.object(app, "manager_prepared_page") as prepared,
              mock.patch.object(app, "dj_manager_note", new_callable=mock.AsyncMock)
              as fallback):
            self.assertFalse(await app.dj_manager_scheduled_round())
            prepared.assert_not_called()
            fallback.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

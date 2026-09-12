"""Recorded-but-exhausted bulletins must not suppress their replacement."""
import copy
from contextlib import ExitStack
import time
import unittest
from unittest import mock

import app


class NewsReplenishmentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        now = time.time()
        self.rows = [{"sid": "old-" + str(i), "seconds": 70, "aired": 9,
            "aired_at": now - 50, "at": now - 100,
            "entry": {"prep_news_at": now - 200, "prepared": True,
                      "takes": [{"key": "original-audio-" + str(i), "voice": "original-actor"}]}}
            for i in range(2)]
        self.policy = {"innings_bonus": 6, "repeats_hard": True}
        for name, value in {"shelf_rows": lambda kind: self.rows,
                "dialogue_row_viable": lambda *a: True,
                "dialogue_row_ready": lambda *a: True,
                "repeat_safe": lambda *a: True,
                "orch_policy": lambda key: self.policy.get(key),
                "news_shelf_most": lambda: 2,
                "news_want_seconds": lambda: 120,
                "news_due": lambda: {"starts_in": 30, "owns": 120},
                "news_prep_ahead": lambda: 300,
                "pipeline_log": mock.Mock()}.items():
            self.stack.enter_context(mock.patch.object(app, name, value))

    async def test_exhausted_news_reaches_replacement_producer_without_deleting_old_recordings(self):
        before, policy = copy.deepcopy(self.rows), copy.deepcopy(self.policy)
        self.assertEqual(app.shelf_innings("news"), 9)
        self.assertTrue(all(not app.shelf_is_repeat("news", row) for row in self.rows))
        self.assertFalse(app.shelf_full("news"))
        async def write(*args, **kwargs):
            kwargs["bank_to"].append({"script": "Fixture replacement.", "seconds": 30})
        with (mock.patch.object(app, "dj_news", side_effect=write) as writer,
              mock.patch.object(app, "larder_prepare", new_callable=mock.AsyncMock) as record,
              mock.patch.object(app, "shelf_put") as put):
            self.assertTrue(await app.prep_news())
        writer.assert_awaited_once(); record.assert_awaited_once(); put.assert_called_once()
        self.assertEqual(self.rows, before)
        self.assertEqual(self.policy, policy)

    async def test_unaired_and_still_reusable_news_continue_to_cover_existing_obligations(self):
        self.rows[0].update(aired=8)
        self.rows[1].pop("aired_at")
        before = copy.deepcopy(self.rows)
        self.assertTrue(app.shelf_full("news"))
        with mock.patch.object(app, "dj_news", new_callable=mock.AsyncMock) as writer:
            self.assertFalse(await app.prep_news())
        writer.assert_not_awaited()
        self.assertEqual(self.rows, before)


if __name__ == "__main__":
    unittest.main()

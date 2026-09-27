import time
import unittest
from contextlib import ExitStack
from unittest import mock

import app


class FillBehindThePileTests(unittest.IsolatedAsyncioTestCase):  # [#1463]
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(app, "_PAGE_AIR_UNTIL", [0.0]))
        self.stack.enter_context(mock.patch.object(app, "radio_paused", lambda: False))
        self.stack.enter_context(mock.patch.object(app, "_RADIO", {"on": True}))
        self.stack.enter_context(mock.patch.object(app, "gold_fired", lambda row: None))
        self.stack.enter_context(mock.patch.object(app, "media_sign", lambda name: "s"))
        self.stack.enter_context(mock.patch.object(app, "pipeline_log", lambda *a, **k: None))
        self.bars = [{"path": "b%d.wav" % i, "text": "bar %d" % i, "seconds": 10.0,
                      "who": ("dj", "cohost")[i % 2]} for i in range(20)]
        self.stack.enter_context(mock.patch.object(
            app, "gold_pick", lambda exclude_who="", min_rest=None: self.bars.pop(0)))

        async def book(*a, clip=None, **k):
            # What page_feed_append does: the clip is stamped behind the
            # cursor and the cursor moves past it.
            app._PAGE_AIR_UNTIL[0] = (max(app._PAGE_AIR_UNTIL[0], time.time())
                                      + float((clip or {}).get("seconds") or 0))
            return "ok"
        self.speak = mock.AsyncMock(side_effect=book)
        self.stack.enter_context(mock.patch.object(app, "dj_speak", self.speak))

    async def test_air_already_sold_past_the_run_lays_nothing(self):
        app._PAGE_AIR_UNTIL[0] = time.time() + 600
        self.assertEqual(await app.gold_fill_gap("dead air", ahead=45), "")
        self.speak.assert_not_awaited()

    async def test_the_run_tops_up_to_the_target_not_past_it(self):
        app._PAGE_AIR_UNTIL[0] = time.time() + 26
        await app.gold_fill_gap("dead air", ahead=45)
        self.assertEqual(self.speak.await_count, 2)   # 26 -> 36 -> 46

    async def test_nothing_sold_lays_the_full_run(self):
        await app.gold_fill_gap("dead air", ahead=45)
        self.assertEqual(self.speak.await_count, 5)   # 10, 20, 30, 40, then 50


if __name__ == "__main__":
    unittest.main()

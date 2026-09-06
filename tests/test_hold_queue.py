import asyncio
import time
import unittest
from contextlib import ExitStack
from unittest import mock

import app


class HoldQueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        replacements = {
            "_BOX_HOLD": [], "_HOLD_DRAIN_LOCK": asyncio.Lock(),
            "_FLOOR_LOCK": asyncio.Lock(),
            "_FLOOR_OWNER": {"task": None, "at": 0.0, "label": ""},
            "_box_hold_save": mock.Mock(), "pipeline_log": mock.Mock(),
            "radio_paused": mock.Mock(return_value=False),
        }
        for name, value in replacements.items():
            self.stack.enter_context(mock.patch.object(app, name, value))

    async def test_simultaneous_drains_play_each_head_once_in_order(self):
        first, second = {"id": "a"}, {"id": "b"}
        app._BOX_HOLD.extend([first, second])
        played = []

        async def replay(row):
            played.append(row["id"])
            await asyncio.sleep(0.01)
            return True

        with mock.patch.object(app, "_replay_held", side_effect=replay):
            drained = await asyncio.gather(app.box_hold_drain_one(),
                                           app.box_hold_drain_one())
        self.assertEqual(played, ["a", "b"])
        self.assertEqual(drained, [first, second])
        self.assertEqual(app._BOX_HOLD, [])
        self.assertFalse(app._FLOOR_LOCK.locked())

    async def test_operator_removal_during_playback_preserves_unheard_next(self):
        first, second = {"id": "a"}, {"id": "b"}
        app._BOX_HOLD.extend([first, second])

        async def replay(row):
            app._BOX_HOLD.remove(row)
            return True

        with mock.patch.object(app, "_replay_held", side_effect=replay):
            self.assertIs(await app.box_hold_drain_one(), first)
        self.assertEqual(app._BOX_HOLD, [second])

    async def test_old_failed_head_retained_and_concurrent_retries_back_off(self):
        first = {"id": "a", "ts": 1, "tries": 3}
        second = {"id": "b"}
        app._BOX_HOLD.extend([first, second])
        with mock.patch.object(app, "_replay_held", return_value=False) as replay:
            self.assertEqual(await asyncio.gather(app.box_hold_drain_one(),
                                                 app.box_hold_drain_one()),
                             [None, None])
            self.assertEqual(replay.await_count, 1)
            self.assertEqual(first["tries"], 4)
            self.assertGreater(first["retry_after"], time.time())
            first["retry_after"] = 0
            await app.box_hold_drain_one()
        self.assertEqual(first["tries"], 5)
        self.assertEqual(app._BOX_HOLD, [first, second])

    async def test_pause_does_not_attempt_or_count_failure(self):
        first = {"id": "a"}
        app._BOX_HOLD.append(first)
        app.radio_paused.return_value = True
        with mock.patch.object(app, "_replay_held") as replay:
            self.assertIsNone(await app.box_hold_drain_one())
            replay.assert_not_awaited()
        self.assertNotIn("tries", first)
        self.assertEqual(app._BOX_HOLD, [first])

    async def test_existing_floor_owner_can_drain_without_releasing_outer_floor(self):
        app._BOX_HOLD.append({"id": "a"})
        owned = await app._floor_take("test show")
        try:
            with mock.patch.object(app, "_replay_held", return_value=True):
                await app.box_hold_drain_one()
        finally:
            self.assertTrue(app._FLOOR_LOCK.locked())
            app._floor_drop(owned)

    async def test_negative_playout_measurement_never_marks_held_line_heard(self):
        first = {"id": "a", "path": "/media/a.wav", "sig": "a", "cast": "cast",
                 "text": "First line.", "who": "dj"}
        chat = {"id": "a", "aired": "held"}
        app._BOX_HOLD.append(first)
        replacements = {
            "_radio_cast_signature": mock.Mock(return_value="cast"),
            "_play_on_box": mock.AsyncMock(return_value="/media/a.wav"),
            "_LAST_PLAYOUT": {"key": app._played_out_key(first["path"]),
                               "at": time.time(), "ok": False},
            "_RADIO": {"chat": [chat]},
            "_speaking_now_set": mock.Mock(), "_speaking_now_clear": mock.Mock(),
            "air_remember": mock.Mock(), "talk_said_now": mock.Mock(),
            "render_backlog_ack": mock.Mock(),
        }
        with ExitStack() as stack:
            for name, value in replacements.items():
                stack.enter_context(mock.patch.object(app, name, value))
            self.assertFalse(await app._replay_held(first))
            app.air_remember.assert_not_called()
            app.talk_said_now.assert_not_called()
            app.render_backlog_ack.assert_not_called()
        self.assertEqual(chat["aired"], "held")
        self.assertEqual(app._BOX_HOLD, [first])


if __name__ == "__main__":
    unittest.main()
